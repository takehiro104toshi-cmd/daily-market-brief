"""P8-B4A — 明示の方針の authority（B3）→ 凍結 B1 → 凍結 B2 → private の結果 → 安全な投影、の合成の統合の test。

合成だけ（閾値 ・値 ・主語はすべて harness の合成の値）。pin するもの: 正確な選択だけ（自動の選択なし）・store の integrity の先行検査 ・
B3 の復元 ・B2 に渡る方針は解決した方針そのもの ・実の凍結 A3-RA の経路での MATCH ・NO_MATCH ・NOT_EVALUABLE ・選択の失敗 ・authority の
破損 ・private の結果は値を持ち安全な投影は値 ・閾値 ・主語 ・著者 ・意図 ・参照を構造的に持たない（件数だけ）・決定論の直列化 ・順位 ・推奨の
語彙なし ・結果の保存なし ・JQ ・P5〜P7 ・runner の import なし。
"""
from __future__ import annotations

import ast
import json
from dataclasses import FrozenInstanceError, fields, replace
from datetime import timedelta
from pathlib import Path

import pytest

from src.intelligence.screener_intelligence import screener_policy_evaluation as pe
from src.intelligence.screener_intelligence import screener_result_summary as rs
from src.intelligence.screener_intelligence.screener_criteria_model import (CriterionState, DataCompleteness,
                                                                            ScreenerAuthorityMode, ScreenerResult,
                                                                            ScreenerState)
from src.intelligence.screener_intelligence.screener_evaluator import EvaluationInputs
from src.intelligence.screener_intelligence.screener_policy_authority_model import PolicyAuthorityRecord
from src.intelligence.screener_intelligence.screener_policy_authority_store import PolicyAuthorityStore
from src.intelligence.screener_intelligence.screener_policy_evaluation import (PolicyEvaluationError,
                                                                               PolicyEvaluationFailure,
                                                                               PolicySelector,
                                                                               evaluate_selected_policy)
from src.intelligence.screener_intelligence.screener_result_summary import (FORBIDDEN_SUMMARY_FIELDS,
                                                                            SafeScreenerSummary,
                                                                            project_safe_summary)
from tests.intelligence.phase8_runtime_registry import PHASE8_PACKAGE
from tests.intelligence.test_prediction_record import executable_source
from tests.intelligence.test_screener_acquisition_manifest import ACQ1, ACQ2, CTX1, I1
from tests.intelligence.test_screener_acquisition_manifest import root as manifest_root  # noqa: F401  fixture
from tests.intelligence.test_screener_criteria_model import criterion, policy
from tests.intelligence.test_screener_evaluator import C, K, T_NM, T_OM, by_metric, context, crit, retro_inputs
from tests.intelligence.test_screener_observation_retrospective import history_of
from tests.intelligence.test_screener_provider_holdings_executor import produce
from tests.intelligence.test_screener_retrospective_metrics import PRIOR_1Q, PRIOR_FY, fy_epoch, semantics_of
from tests.intelligence.test_screener_retrospective_metrics import root  # noqa: F401  fixture

REPO_ROOT = Path(__file__).resolve().parents[2]
PACKAGE_DIR = REPO_ROOT / PHASE8_PACKAGE
ORCH = PACKAGE_DIR / "screener_policy_evaluation.py"
SUMMARY = PACKAGE_DIR / "screener_result_summary.py"
F = PolicyEvaluationFailure
RETRO = ScreenerAuthorityMode.RETROSPECTIVE_PROVIDER_AUTHORITY
#: 安全な投影に決して現れてはならない合成の sentinel
SENTINEL_INTENT = "synthetic sentinel intent zq7"
SENTINEL_AUTHOR = "human:sentinel-reviewer-zq7"
SENTINEL_COMPANY = "Sentinel Synthetic Kabushiki Kaisha"
SENTINEL_CODE = "99999"
SENTINEL_CREDENTIAL = "api_key=SENTINELSECRET"
SENTINEL_PATH = "/private/sentinel/root"


@pytest.fixture
def policy_root(tmp_path: Path) -> Path:
    private = tmp_path / "policy_root"
    PolicyAuthorityStore.initialize(private)
    return private


def matching_policy(**overrides):
    base = dict(intent=SENTINEL_INTENT, author_ref=SENTINEL_AUTHOR)
    return policy(crit(K.OPERATING_MARGIN, C.GE, T_OM), crit(K.REVENUE_GROWTH, C.BETWEEN, "0.2", high="0.25"),
                  **{**base, **overrides})


def stored(policy_root: Path, *policies) -> None:
    store = PolicyAuthorityStore.open(policy_root)
    for pol in policies:
        store.append(PolicyAuthorityRecord(policy=pol))


def prepared(root: Path) -> None:
    produce(root, [PRIOR_FY, PRIOR_1Q], CTX1)
    fy_epoch(root)


def fails(failure: F, fn, *args, code: str = None, **kwargs) -> PolicyEvaluationError:
    with pytest.raises(PolicyEvaluationError) as exc:
        fn(*args, **kwargs)
    assert exc.value.failure is failure, (exc.value.failure, exc.value.code)
    if code is not None:
        assert exc.value.code == code, exc.value.code
    return exc.value


def selector_id(pol) -> PolicySelector:
    return PolicySelector(policy_id=pol.policy_id)


# ================================================ A 明示の選択だけ


def test_a_selector_is_exactly_one_explicit_shape_and_has_no_automatic_form() -> None:
    assert PolicySelector(policy_id="p8pol_" + "0" * 24).as_dict() == {"policy_id": "p8pol_" + "0" * 24,
                                                                        "policy_key": None, "version": None}
    assert PolicySelector(policy_key="synthetic", version=2).version == 2
    for kwargs in (dict(), dict(policy_id="p8pol_" + "0" * 24, policy_key="k", version=1),
                   dict(policy_id="p8pol_" + "0" * 24, version=1), dict(policy_key="k"), dict(version=1),
                   dict(policy_id="p8crt_" + "0" * 24), dict(policy_id=""), dict(policy_key="", version=1),
                   dict(policy_key="k", version="1"), dict(policy_key="k", version=True),
                   dict(policy_key="k", version=1.0)):
        fails(F.SELECTOR_INVALID, PolicySelector, **kwargs)
    assert set(fields(PolicySelector).__iter__.__self__ and (f.name for f in fields(PolicySelector))) == {
        "policy_id", "policy_key", "version"}
    with pytest.raises(FrozenInstanceError):
        PolicySelector(policy_key="k", version=1).version = 2                                     # type: ignore[misc]
    assert pe.SELECTION_RULE == "EXPLICIT_POLICY_ID_OR_EXACT_KEY_VERSION_ONLY_NO_AUTOMATIC_SELECTION"


def test_a_exact_policy_id_and_exact_key_version_resolve_the_same_authority_record(root: Path, policy_root: Path):
    prepared(root)
    pol = matching_policy()
    stored(policy_root, pol, matching_policy(version=2, reviewed_at=pol.reviewed_at + timedelta(days=1)))
    by_id = evaluate_selected_policy(policy_root, selector_id(pol), context(pol, ACQ2), retro_inputs(root))
    by_key = evaluate_selected_policy(policy_root, PolicySelector(policy_key=pol.policy_key, version=1),
                                      context(pol, ACQ2), retro_inputs(root))
    assert by_id.record == by_key.record and by_id.record.policy == pol and by_id.policy is by_id.record.policy
    assert by_id.result == by_key.result and by_id.rules_version == "p8_screener_policy_evaluation:0.1.0"
    assert by_id.result.policy_id == pol.policy_id and by_id.result.policy_version == 1


def test_a_no_automatic_selection_exists_and_unresolved_selectors_fail_closed(root: Path, policy_root: Path) -> None:
    prepared(root)
    pol = matching_policy()
    stored(policy_root, pol, matching_policy(version=3, reviewed_at=pol.reviewed_at + timedelta(days=1)))
    other = matching_policy(policy_key="other-synthetic-key")
    fails(F.POLICY_NOT_FOUND, evaluate_selected_policy, policy_root, selector_id(other), context(other, ACQ2),
          retro_inputs(root))
    fails(F.KEY_VERSION_NOT_FOUND, evaluate_selected_policy, policy_root,
          PolicySelector(policy_key=pol.policy_key, version=2), context(pol, ACQ2), retro_inputs(root))
    fails(F.KEY_VERSION_NOT_FOUND, evaluate_selected_policy, policy_root,
          PolicySelector(policy_key="other-synthetic-key", version=1), context(pol, ACQ2), retro_inputs(root))
    source = executable_source(ORCH) + executable_source(SUMMARY)
    for token in ("latest", "current_policy", "active_policy", "default_policy", "highest", "newest", "max(", "min(",
                  "sorted(", "list_metadata", "discover", "fallback(", "records()[", "[-1]", "[0]"):
        assert token not in source, token
    public = {n for n in dir(pe) if not n.startswith("_") and callable(getattr(pe, n))}
    assert not any("latest" in n.lower() or "current" in n.lower() or "default" in n.lower() for n in public)


# ================================================ B authority の検証（store → B3 → mode ・文脈）


def test_b_store_integrity_is_checked_before_evaluation_and_corruption_is_not_missing_data(root: Path, policy_root,
                                                                                            monkeypatch) -> None:
    prepared(root)
    pol = matching_policy()
    stored(policy_root, pol)
    journal = policy_root / "screener_intelligence" / "screener_policy_authority.jsonl"
    original = journal.read_bytes()
    monkeypatch.setattr(pe, "evaluate_policy", lambda *a, **k: pytest.fail("B2 must not run on a corrupt store"))
    for tail, code in ((b"not json\n", "INVALID_RECORD"),
                       (b'{"record_kind": "SCREENER_POLICY_AUTHORITY"', "TRUNCATED_FINAL_LINE"),
                       (original, "PHYSICAL_DUPLICATE")):
        journal.write_bytes(original + tail)
        error = fails(F.STORE_INTEGRITY_FAILURE, evaluate_selected_policy, policy_root, selector_id(pol),
                      context(pol, ACQ2), retro_inputs(root), code=code)
        assert "NOT_EVALUABLE" not in str(error) and journal.read_bytes() == original + tail      # 修復しない
    forged = json.loads(original.decode())
    forged["policy"]["policy_id"] = "p8pol_" + "f" * 24
    journal.write_bytes((json.dumps(forged, sort_keys=True, separators=(",", ":"), ensure_ascii=False) + "\n").encode())
    fails(F.STORE_INTEGRITY_FAILURE, evaluate_selected_policy, policy_root, selector_id(pol), context(pol, ACQ2),
          retro_inputs(root), code="POLICY_ID_MISMATCH")
    journal.unlink()
    fails(F.STORE_INTEGRITY_FAILURE, evaluate_selected_policy, policy_root, selector_id(pol), context(pol, ACQ2),
          retro_inputs(root), code="STORE_MISSING")
    fails(F.INVALID_INPUT, evaluate_selected_policy, "", selector_id(pol), context(pol, ACQ2), retro_inputs(root),
          code="DATA_ROOT_REQUIRED")


def test_b_the_store_is_opened_read_only_and_is_the_only_policy_source(root: Path, policy_root: Path, monkeypatch):
    prepared(root)
    pol = matching_policy()
    stored(policy_root, pol)
    opened = []
    real_open = PolicyAuthorityStore.open

    def spy_open(data_root, *, read_only=False):
        opened.append(read_only)
        return real_open(data_root, read_only=read_only)
    monkeypatch.setattr(PolicyAuthorityStore, "open", spy_open)
    seen = {}
    real_eval = pe.evaluate_policy

    def spy_eval(policy, ctx, inputs):
        seen["policy"], seen["context"], seen["inputs"] = policy, ctx, inputs
        return real_eval(policy, ctx, inputs)
    monkeypatch.setattr(pe, "evaluate_policy", spy_eval)
    ctx, inputs = context(pol, ACQ2), retro_inputs(root)
    before = (policy_root / "screener_intelligence" / "screener_policy_authority.jsonl").read_bytes()
    outcome = evaluate_selected_policy(policy_root, selector_id(pol), ctx, inputs)
    assert opened == [True] and seen["context"] is ctx and seen["inputs"] is inputs
    assert seen["policy"] == pol and seen["policy"] is outcome.record.policy                   # 解決した方針そのもの
    assert (policy_root / "screener_intelligence" / "screener_policy_authority.jsonl").read_bytes() == before
    assert sorted(p.name for p in policy_root.rglob("*") if p.is_file()) == ["screener_policy_authority.jsonl"]


def test_b_context_must_name_the_resolved_policy_and_share_its_authority_mode(root: Path, policy_root: Path,
                                                                             monkeypatch) -> None:
    prepared(root)
    pol = matching_policy()
    other = matching_policy(version=2, reviewed_at=pol.reviewed_at + timedelta(hours=1))
    stored(policy_root, pol, other)
    monkeypatch.setattr(pe, "evaluate_policy", lambda *a, **k: pytest.fail("B2 must not run"))
    fails(F.CONTEXT_POLICY_MISMATCH, evaluate_selected_policy, policy_root, selector_id(pol), context(other, ACQ2),
          retro_inputs(root))
    fails(F.AUTHORITY_MODE_MISMATCH, evaluate_selected_policy, policy_root, selector_id(pol),
          context(pol, ACQ2, mode=ScreenerAuthorityMode.STRICT_PIT), retro_inputs(root))
    fails(F.INVALID_INPUT, evaluate_selected_policy, policy_root, pol.policy_id, context(pol, ACQ2), retro_inputs(root))
    fails(F.INVALID_INPUT, evaluate_selected_policy, policy_root, selector_id(pol), object(), retro_inputs(root))
    fails(F.INVALID_INPUT, evaluate_selected_policy, policy_root, selector_id(pol), context(pol, ACQ2), object())


def test_b_evaluator_contract_failures_are_typed_and_not_collapsed(root: Path, policy_root: Path) -> None:
    prepared(root)
    pol = matching_policy()
    stored(policy_root, pol)
    strict_only = EvaluationInputs(history=history_of(root), semantics=semantics_of(root))      # 保持の像が無い
    error = fails(F.EVALUATOR_CONTRACT_FAILURE, evaluate_selected_policy, policy_root, selector_id(pol),
                  context(pol, ACQ2), strict_only, code="RETROSPECTIVE_INPUTS_REQUIRED")
    assert isinstance(error, RuntimeError) and error.failure.value == "EVALUATOR_CONTRACT_FAILURE"
    assert {f.value for f in F} == {"SELECTOR_INVALID", "POLICY_NOT_FOUND", "KEY_VERSION_NOT_FOUND",
                                    "STORE_INTEGRITY_FAILURE", "AUTHORITY_CORRUPTION", "AUTHORITY_CLASS_MISMATCH",
                                    "AUTHORITY_MODE_MISMATCH", "CONTEXT_POLICY_MISMATCH",
                                    "EVALUATOR_CONTRACT_FAILURE", "INVALID_INPUT"}


# ================================================ C 合成の E2E（B3 → B1 → 凍結 A3-RA の下の B2 → 投影）


def test_c_match_end_to_end_through_the_real_frozen_a3_ra_path(root: Path, policy_root: Path) -> None:
    prepared(root)
    pol = matching_policy()
    stored(policy_root, pol)
    outcome = evaluate_selected_policy(policy_root, selector_id(pol), context(pol, ACQ2), retro_inputs(root))
    result = outcome.result
    assert isinstance(result, ScreenerResult) and result.state is ScreenerState.MATCH
    assert result.completeness is DataCompleteness.COMPLETE and result.subject_id == I1
    r = by_metric(result)
    assert r[K.OPERATING_MARGIN].observed_value == "0.08" and r[K.REVENUE_GROWTH].observed_value == "0.25"
    assert all(c.coverage_epoch_ids and c.manifest_refs and c.observation_ids for c in result.criterion_results)
    summary = project_safe_summary(result)
    assert summary.state is ScreenerState.MATCH and summary.completeness is DataCompleteness.COMPLETE
    assert summary.policy_ref == pol.policy_id and summary.policy_version == 1 and summary.criterion_count == 2
    assert [c.state for c in summary.criteria] == [CriterionState.MATCH, CriterionState.MATCH]
    assert [c.has_value for c in summary.criteria] == [True, True]
    assert [(c.observation_id_count, c.coverage_epoch_ref_count, c.manifest_ref_count) for c in summary.criteria] \
        == [(2, 1, 1), (2, 2, 2)]
    assert summary.evaluation_as_of == ACQ2 and summary.authority_mode is RETRO
    assert result.authority_class == "DERIVED_NON_AUTHORITY_NON_PERSISTENT"
    assert summary.summary_class == "DERIVED_SAFE_PROJECTION_NON_AUTHORITY_NON_PERSISTENT"


def test_c_no_match_and_not_evaluable_project_truthfully(root: Path, policy_root: Path) -> None:
    prepared(root)
    no_match = policy(crit(K.OPERATING_MARGIN, C.GE, T_OM), crit(K.NET_MARGIN, C.GT, T_NM), policy_key="nm-synthetic")
    stored(policy_root, no_match)
    outcome = evaluate_selected_policy(policy_root, selector_id(no_match), context(no_match, ACQ2),
                                       retro_inputs(root))
    assert outcome.result.state is ScreenerState.NO_MATCH                                      # B: 0.06 > 0.10 は偽
    summary = project_safe_summary(outcome.result)
    assert summary.state is ScreenerState.NO_MATCH and summary.completeness is DataCompleteness.COMPLETE
    assert [c.state for c in summary.criteria] == [CriterionState.MATCH, CriterionState.NO_MATCH]
    assert all(c.has_value for c in summary.criteria)
    early = evaluate_selected_policy(policy_root, selector_id(no_match),
                                     context(no_match, ACQ1 - timedelta(hours=1)), retro_inputs(root))
    assert early.result.state is ScreenerState.NOT_EVALUABLE                                   # C: 保持が見えない
    summary = project_safe_summary(early.result)
    assert summary.state is ScreenerState.NOT_EVALUABLE and summary.completeness is DataCompleteness.NONE
    assert all(c.state is CriterionState.NOT_EVALUABLE and not c.has_value for c in summary.criteria)
    assert all(c.reason_codes == ("TARGET_UNAVAILABLE",) for c in summary.criteria)
    assert all((c.observation_id_count, c.coverage_epoch_ref_count, c.manifest_ref_count) == (0, 0, 0)
               for c in summary.criteria)


# ================================================ D 安全な投影（値 ・閾値 ・主語 ・著者 ・意図 ・参照は無い）


def test_d_private_result_carries_values_and_the_safe_projection_structurally_cannot(root: Path, policy_root: Path):
    prepared(root)
    pol = matching_policy()
    stored(policy_root, pol)
    result = evaluate_selected_policy(policy_root, selector_id(pol), context(pol, ACQ2), retro_inputs(root)).result
    private = json.dumps(result.as_dict(include_values=True), ensure_ascii=False)
    assert "0.08" in private and I1 in private and "p8obs_" in private and "jq.pvh:" in private   # private は持つ
    summary = project_safe_summary(result)
    text = summary.canonical_json()
    sentinels = (I1, SENTINEL_COMPANY, SENTINEL_CODE, "0.08", "0.25", T_OM, "0.2", SENTINEL_AUTHOR, SENTINEL_INTENT,
                 SENTINEL_CREDENTIAL, SENTINEL_PATH, *[i for c in result.criterion_results for i in c.observation_ids],
                 *[e for c in result.criterion_results for e in c.coverage_epoch_ids],
                 *[m for c in result.criterion_results for m in c.manifest_refs], "p8obs_", "jq.pvh:", "jq.man:",
                 "p8iss_", "p8sec_", "0.0", "/private", "api_key", "2025-03-31", "2024-03-31")
    for sentinel in sentinels:
        assert sentinel not in text, sentinel
    names = rs.summary_field_names()
    for cls, field_names in names.items():
        assert not set(field_names) & set(FORBIDDEN_SUMMARY_FIELDS), cls
        for forbidden in ("observed_value", "threshold", "threshold_high", "author_ref", "intent", "company", "issuer",
                          "security", "ticker", "code", "observation_ids", "coverage_epoch_ids", "manifest_refs"):
            assert forbidden not in field_names, (cls, forbidden)
    data = summary.as_dict()
    keys = set(data) | {k for c in data["criteria"] for k in c}
    assert not keys & set(FORBIDDEN_SUMMARY_FIELDS)
    assert keys == {"authority_mode", "completeness", "criteria", "criterion_count", "evaluation_as_of",
                    "match_meaning", "policy_ref", "policy_version", "rules_version", "schema_version", "state",
                    "summary_class", "coverage_epoch_ref_count", "criterion_id", "has_value", "inner_metric_status",
                    "manifest_ref_count", "metric", "observation_id_count", "reason_codes"}
    assert all(isinstance(c[k], int) and not isinstance(c[k], bool) for c in data["criteria"]
               for k in ("observation_id_count", "coverage_epoch_ref_count", "manifest_ref_count"))
    assert all(isinstance(code, str) and "." not in code and " " not in code for c in summary.criteria
               for code in c.reason_codes)                                                       # 値を運べない語彙
    assert "subject" not in text and "issuer" not in text.lower().replace("issuer_satisfied", "")


def test_d_safe_serialization_is_deterministic_and_uses_frozen_state_vocabulary_only(root: Path, policy_root: Path):
    prepared(root)
    pol = matching_policy()
    stored(policy_root, pol)
    first = project_safe_summary(evaluate_selected_policy(policy_root, selector_id(pol), context(pol, ACQ2),
                                                          retro_inputs(root)).result)
    second = project_safe_summary(evaluate_selected_policy(policy_root, selector_id(pol), context(pol, ACQ2),
                                                           retro_inputs(root)).result)
    assert first == second and first.canonical_json() == second.canonical_json()
    assert first.canonical_json() == json.dumps(first.as_dict(), sort_keys=True, separators=(",", ":"),
                                                ensure_ascii=False)
    assert first.as_dict()["state"] in {s.value for s in ScreenerState}
    assert {c["state"] for c in first.as_dict()["criteria"]} <= {s.value for s in CriterionState}
    assert first.as_dict()["match_meaning"] == rs.MATCH_MEANING
    lowered = first.canonical_json().lower()
    for word in ("good", "attractive", "promising", "recommend", "buy", "opportunity", "winner", "top", "pass stock",
                 "score", "rank"):
        assert word not in lowered, word
    with pytest.raises(FrozenInstanceError):
        first.state = ScreenerState.NO_MATCH                                                     # type: ignore[misc]
    with pytest.raises(rs.SummaryProjectionError) as exc:
        replace(first, criterion_count=5)
    assert exc.value.code == "CRITERION_COUNT_MISMATCH"
    with pytest.raises(rs.SummaryProjectionError) as exc:
        project_safe_summary(first)                                                             # type: ignore[arg-type]
    assert exc.value.code == "INVALID_SCREENER_RESULT"
    assert isinstance(first, SafeScreenerSummary)


# ================================================ E 表面の guard（順位 ・推奨 ・保存 ・runner ・JQ なし）


def test_e_the_integration_is_a_pure_orchestration_without_ranking_persistence_or_runner_coupling() -> None:
    for module, allowed in ((ORCH, {"__future__", "dataclasses", "enum", "typing", ".screener_criteria_model",
                                    ".screener_evaluator", ".screener_policy_authority_model",
                                    ".screener_policy_authority_store"}),
                            (SUMMARY, {"__future__", "dataclasses", "datetime", "typing", "..core.time",
                                       ".identity_model", ".metric_model", ".screener_criteria_model"})):
        tree = ast.parse(module.read_text(encoding="utf-8"))
        imported = {"." * node.level + (node.module or "") for node in ast.walk(tree)
                    if isinstance(node, ast.ImportFrom)}
        imported |= {alias.name for node in ast.walk(tree) if isinstance(node, ast.Import) for alias in node.names}
        assert imported == allowed, (module.name, imported ^ allowed)
        names = {alias.name for node in ast.walk(tree) if isinstance(node, ast.ImportFrom) for alias in node.names}
        assert not any(n.startswith("_") for n in names - {"__future__"})
        source = executable_source(module)
        if module is SUMMARY:                                                # 禁止の欄の一覧の定数だけが禁止の語を含む
            head, tail = source.index("FORBIDDEN_SUMMARY_FIELDS"), source.index("class SummaryProjectionError")
            assert source[head:tail].count("score") == 1 and source[head:tail].count("rank") == 1
            source = source[:head] + source[tail:]
        for token in ("score", "rank", "rating", "weight", "priority", "attractiveness", "recommend", "target_price",
                      "expected_return", "threshold_distance", "watchlist", "portfolio", "jquants_pilot2", "jquants",
                      "theme", "Theme", "narrative", "p5", "p6", "p7", "with open(", "Path(", "os.", "json.dump",
                      "write", "append(", "store.append", "initialize(", "now(", "today(", "utcnow", "://", "llm",
                      "prompt", "float(", "round(", "Decimal", "sorted(", "sort(", "max(", "min(", "sum(", "key=",
                      "company", "ticker", "security_code", "getattr", "importlib", "universe", "exposure"):
            assert token not in source, (module.name, token)
        for node in ast.walk(tree):
            assert not (isinstance(node, ast.ExceptHandler) and (node.type is None or (
                isinstance(node.type, ast.Name) and node.type.id == "Exception"))), "broad except"
            assert not (isinstance(node, ast.Name) and node.id in {"open", "float", "round", "print", "eval", "exec"})
            assert not isinstance(node, ast.BinOp), ast.dump(node)                              # 算術は無い
        for line in module.read_text(encoding="utf-8").splitlines():
            assert len(line) <= 120, line
    orch = executable_source(ORCH)
    assert "read_only=True" in orch and "validate(" in orch and "evaluate_policy(" in orch
    assert "operating_margin" not in orch and "resolve_retro" not in orch and "compare(" not in orch
    assert set(pe.__all__) == {"ORCHESTRATION_RULES_VERSION", "SELECTION_RULE", "PolicyEvaluationError",
                               "PolicyEvaluationFailure", "PolicyEvaluationOutcome", "PolicySelector",
                               "evaluate_selected_policy", "open_verified_store", "resolve_policy"}
    assert set(rs.__all__) == {"FORBIDDEN_SUMMARY_FIELDS", "MATCH_MEANING", "SUMMARY_CLASS", "SUMMARY_RULES_VERSION",
                               "SUMMARY_SCHEMA_VERSION", "SafeCriterionSummary", "SafeScreenerSummary",
                               "SummaryProjectionError", "project_safe_summary", "summary_field_names"}
    assert not list(REPO_ROOT.glob("**/screener_result*.jsonl")) and not list(PACKAGE_DIR.glob("*watchlist*"))


def test_e_documents_and_changelog_carry_no_policy_values_or_recommendation_language() -> None:
    doc = (REPO_ROOT / "docs/databank/PHASE8_B4A_POLICY_EVALUATION_SAFE_PROJECTION.md").read_text(encoding="utf-8")
    changelog = (REPO_ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    section = changelog[changelog.index("## v5.88"):changelog.index("## v5.87")]
    for text, name in ((doc, "doc"), (section, "CHANGELOG v5.88")):
        assert '"threshold":"' not in text and "threshold=" not in text and "p8pol_" not in text.replace("p8pol_…", "")
        assert "reviewer-1" not in text and SENTINEL_INTENT not in text, name
    assert "attractive" not in section.lower() and "recommend" not in section.lower().replace("recommendation", "")
    assert "DERIVED_NON_AUTHORITY_NON_PERSISTENT" in doc and "ISSUER_SATISFIED_EVERY_CRITERION" in doc
