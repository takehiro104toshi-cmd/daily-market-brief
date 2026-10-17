"""P8-B4B — PILOT2B runner への Screener の統合（明示の方針 → 凍結 B4A → 安全な要約の `screener` の節）の合成の test。

合成の transport ・合成の方針だけ（実 request ・実の方針 ・private の pilot root は無い）。pin するもの: 選択子なしは legacy のまま
（`screener` は NOT_REQUESTED の 1 節だけ追加）・正確な policy_id ／ (鍵, 版) → B3 → B4A → 安全な投影 ・MATCH ／ NO_MATCH ／ NOT_EVALUABLE は
runner の操作の状態と独立 ・方針なし ・store の破損 ・mode の不一致は fail closed ・replay は決定論で authority の行を増やさない ・sentinel の漏れなし ・
request の予算 ・network の呼び出しは Screener で変わらない ・凍結の runtime の byte 一致。
"""
from __future__ import annotations

import ast
import json
import re
from datetime import timedelta
from pathlib import Path

import pytest

from src.intelligence import jquants_pilot2_local as pl
from src.intelligence.jquants_pilot2_local import PilotError, execute
from src.intelligence.screener_intelligence.screener_criteria_model import ScreenerAuthorityMode
from src.intelligence.screener_intelligence.screener_policy_authority_model import PolicyAuthorityRecord
from src.intelligence.screener_intelligence.screener_policy_authority_store import PolicyAuthorityStore
from src.intelligence.screener_intelligence.screener_policy_evaluation import (PolicyEvaluationError,
                                                                               PolicyEvaluationFailure)
from tests.intelligence.phase8_runtime_registry import PHASE8_PACKAGE
from tests.intelligence.test_prediction_record import executable_source
from tests.intelligence.test_screener_criteria_model import criterion, policy
from tests.intelligence.test_screener_evaluator import C, K
from tests.intelligence.test_screener_pilot2_local_runner import (FORBIDDEN_IN_SUMMARY, pilot_dir, read,
                                                                    standard_transport)
from tests.intelligence.test_screener_pilot2_local_runner import root  # noqa: F401  fixture
from tests.intelligence.test_screener_pilot2b_retrospective_runner import (ACQ, ACQ2, FORBIDDEN_AUTHORITY, ISSUER_KEYS,
                                                                           issuer, prepared, run)

REPO_ROOT = Path(__file__).resolve().parents[2]
RUNNER = REPO_ROOT / "src/intelligence/jquants_pilot2_local.py"
POLICY_JOURNAL = Path("screener_intelligence") / "screener_policy_authority.jsonl"
SECTION_KEYS = {"schema", "state", "selector_kind", "issuers", "failure_code"}
SUMMARY_KEYS = {"authority_mode", "completeness", "criteria", "criterion_count", "evaluation_as_of", "match_meaning",
                "policy_ref", "policy_version", "rules_version", "schema_version", "state", "summary_class"}
#: 合成の sentinel（安全な要約に決して現れない）
SENTINEL_INTENT = "synthetic sentinel intent b4b"
SENTINEL_AUTHOR = "human:sentinel-reviewer-b4b"
SENTINELS = FORBIDDEN_AUTHORITY + (SENTINEL_INTENT, SENTINEL_AUTHOR, "0.07", "0.05", "synthetic-model-test",
                                   "p8iss_", "p8sec_", "api_key", "/private", "threshold", "observed_value",
                                   "author_ref", "intent", "subject_id", "observation_ids", "coverage_epoch_ids",
                                   "manifest_refs")


def synthetic_policy(*criteria, **overrides):
    """合成の方針（閾値は harness の値 0.08 ・0.06 ・≈0 の周りの合成の値。投資の方針ではない）。"""
    base = dict(intent=SENTINEL_INTENT, author_ref=SENTINEL_AUTHOR)
    return policy(*(criteria or (crit_om_ge("0.05"), crit_growth_ge("0"))), **{**base, **overrides})


def crit_om_ge(threshold: str, **overrides):
    return criterion(metric=K.OPERATING_MARGIN, operator=C.GE, threshold=threshold,
                     period_rule=_period_rule("NEWEST_SUPPORTED_FY_OR_CUMULATIVE"), **overrides)


def _period_rule(name: str):
    from src.intelligence.screener_intelligence.screener_criteria_model import PeriodRule
    return PeriodRule(name)


def crit_growth_ge(threshold: str, **overrides):
    return criterion(metric=K.REVENUE_GROWTH, operator=C.GE, threshold=threshold,
                     period_rule=_period_rule("NEWEST_WITH_COMPARABLE_PRIOR"), **overrides)


def crit_nm_gt(threshold: str, **overrides):
    return criterion(metric=K.NET_MARGIN, operator=C.GT, threshold=threshold,
                     period_rule=_period_rule("NEWEST_SUPPORTED_FY_OR_CUMULATIVE"), **overrides)


def stored(root: Path, *policies) -> None:
    store = PolicyAuthorityStore.initialize(root)
    for pol in policies:
        store.append(PolicyAuthorityRecord(policy=pol))


def run_with(root: Path, transport=None, acquired_at: str = ACQ, **selector) -> dict:
    return execute(data_root=root, transport=transport or standard_transport(), acquired_at=acquired_at, **selector)


def fails(code: str, **kwargs) -> PilotError:
    with pytest.raises(PilotError) as exc:
        run_with(**kwargs)
    assert exc.value.code == code, (exc.value.code, exc.value.detail)
    return exc.value


def screener_summary(summary: dict, index: int = 0) -> dict:
    return summary["screener"]["issuers"][index]["summary"]


# ================================================ A 選択子なし ＝ legacy（NOT_REQUESTED の節だけ）


def test_a_without_a_selector_legacy_behaviour_is_unchanged_except_for_the_not_requested_section(root: Path) -> None:
    prepared(root)
    transport = standard_transport()
    summary = run(root, transport)
    assert summary["screener"] == {"schema": "p8_pilot2b_screener_section:0.1.0", "state": "NOT_REQUESTED",
                                   "selector_kind": None, "issuers": [], "failure_code": ""}
    assert summary["state"] == "PILOT_PASS" and summary["request"]["used"] == 2 and len(transport.calls) == 1
    assert set(issuer(summary)) == ISSUER_KEYS
    legacy = {k: v for k, v in summary.items() if k != "screener"}
    assert set(legacy) == {"schema", "stage", "pilot_id", "d0", "target_count", "eligibility_counts", "decision_counts",
                           "id2", "digests", "identity_verification", "fins", "exe_outcomes", "exe_reasons",
                           "held_reasons", "metrics", "acquisition_authority", "rules_version", "request",
                           "store_integrity", "state"}
    assert summary["schema"] == "p8_pilot2_safe_summary:0.1.0"                                   # 版は上げない（OBS）
    assert not (root / POLICY_JOURNAL).exists()                                                   # 方針を作らない
    legacy_2a = execute(data_root=root, transport=standard_transport())                          # PILOT2A の経路も同じ
    assert legacy_2a["screener"]["state"] == "NOT_REQUESTED" and legacy_2a["acquisition_authority"]["state"] == \
        "NOT_REQUESTED"
    assert {p.name for p in pilot_dir(root).iterdir()} == {"review_packet.json", "decision_template.json",
                                                           "decision.json", "budget_state.json", "safe_summary.json",
                                                           "acquisition_state.json"}                # 新しい file は無い


# ================================================ B ・C 正確な選択 → B3 → B4A → MATCH


def test_b_exact_policy_id_runs_the_frozen_chain_then_b4a_and_projects_a_match(root: Path) -> None:
    prepared(root)
    pol = synthetic_policy()
    stored(root, pol)
    transport = standard_transport()
    summary = run_with(root, transport, screener_policy_id=pol.policy_id)
    assert summary["state"] == "PILOT_PASS" and summary["acquisition_authority"]["state"] == "REQUESTED"
    section = summary["screener"]
    assert set(section) == SECTION_KEYS and section["state"] == "REQUESTED" and section["selector_kind"] == "POLICY_ID"
    assert section["failure_code"] == "" and len(section["issuers"]) == 1
    assert set(section["issuers"][0]) == {"summary", "failure_code"} and section["issuers"][0]["failure_code"] == ""
    safe = screener_summary(summary)
    assert set(safe) == SUMMARY_KEYS and safe["state"] == "MATCH" and safe["completeness"] == "COMPLETE"
    assert safe["policy_ref"] == pol.policy_id and safe["policy_version"] == 1 and safe["criterion_count"] == 2
    assert safe["authority_mode"] == "RETROSPECTIVE_PROVIDER_AUTHORITY"
    assert safe["evaluation_as_of"] == "2026-06-30T11:00:00+00:00"                               # ＝ acquired_at（UTC）
    assert [c["state"] for c in safe["criteria"]] == ["MATCH", "MATCH"]
    assert [c["metric"] for c in safe["criteria"]] == ["OPERATING_MARGIN", "REVENUE_GROWTH"]
    assert all(c["has_value"] is True and c["inner_metric_status"] == "VALUE" for c in safe["criteria"])
    assert [(c["observation_id_count"], c["coverage_epoch_ref_count"], c["manifest_ref_count"])
            for c in safe["criteria"]] == [(2, 1, 1), (2, 2, 1)]
    assert safe["summary_class"] == "DERIVED_SAFE_PROJECTION_NON_AUTHORITY_NON_PERSISTENT"
    assert len(transport.calls) == 1 and summary["request"]["used"] == 2                         # fins の 1 回だけ
    assert issuer(summary)["holdings_epoch_count"] == 2 and issuer(summary)["failure_code"] == ""
    assert read(root, "safe_summary.json") == summary


def test_c_exact_key_and_version_resolve_the_same_policy_and_the_same_projection(root: Path) -> None:
    prepared(root)
    pol = synthetic_policy()
    stored(root, pol, synthetic_policy(version=3, reviewed_at=pol.reviewed_at + timedelta(days=1)))
    by_id = run_with(root, screener_policy_id=pol.policy_id)
    by_key = run_with(root, screener_policy_key=pol.policy_key, screener_policy_version=1)
    assert by_key["screener"]["selector_kind"] == "KEY_VERSION"
    assert screener_summary(by_key) == screener_summary(by_id) and screener_summary(by_key)["policy_version"] == 1
    v3 = run_with(root, screener_policy_key=pol.policy_key, screener_policy_version=3)
    assert screener_summary(v3)["policy_version"] == 3 and screener_summary(v3)["policy_ref"] != pol.policy_id


# ================================================ D ・E 結果の状態は runner の操作の状態と独立


def test_d_no_match_keeps_the_runner_operational_state_a_pass(root: Path) -> None:
    prepared(root)
    pol = synthetic_policy(crit_om_ge("0.05"), crit_nm_gt("0.10"))                               # 0.06 > 0.10 は偽
    stored(root, pol)
    summary = run_with(root, screener_policy_id=pol.policy_id)
    assert summary["state"] == "PILOT_PASS" and summary["screener"]["state"] == "REQUESTED"
    safe = screener_summary(summary)
    assert safe["state"] == "NO_MATCH" and [c["state"] for c in safe["criteria"]] == ["MATCH", "NO_MATCH"]
    assert safe["completeness"] == "COMPLETE" and all(c["has_value"] for c in safe["criteria"])
    text = json.dumps(summary, ensure_ascii=False)
    for word in ("bad", "good", "attractive", "recommend", "buy", "sell", "winner", "opportunity"):
        assert word not in text.lower(), word


def test_e_not_evaluable_is_truthful_and_never_a_failure_or_a_verdict(root: Path) -> None:
    prepared(root)
    strict = synthetic_policy(crit_om_ge("0.05", authority_mode=ScreenerAuthorityMode.STRICT_PIT),
                              authority_mode=ScreenerAuthorityMode.STRICT_PIT, policy_key="strict-synthetic")
    stored(root, strict)
    summary = run_with(root, screener_policy_id=strict.policy_id)
    assert summary["state"] == "PILOT_PASS" and summary["screener"]["state"] == "REQUESTED"
    safe = screener_summary(summary)
    assert safe["authority_mode"] == "STRICT_PIT" and safe["state"] == "NOT_EVALUABLE"            # coverage なし（捏造しない）
    assert safe["completeness"] == "NONE" and safe["criteria"][0]["has_value"] is False
    assert all(code.endswith(":OUTSIDE_COVERAGE") for code in safe["criteria"][0]["reason_codes"])
    assert safe["criteria"][0]["inner_metric_status"] == "INSUFFICIENT_DATA"
    assert (safe["criteria"][0]["observation_id_count"], safe["criteria"][0]["coverage_epoch_ref_count"]) == (0, 0)
    assert summary["metrics"][0]["OPERATING_MARGIN"]["status"] == "INSUFFICIENT_DATA"            # STRICT の表示は不変


# ================================================ F ・G ・H fail closed（方針なし ・破損 ・不一致）


def test_f_missing_policy_or_version_fails_closed_before_any_request(root: Path) -> None:
    prepared(root)
    pol = synthetic_policy()
    transport = standard_transport()
    error = fails("SCREENER_POLICY_UNAVAILABLE", root=root, transport=transport, screener_policy_id=pol.policy_id)
    assert error.detail.startswith("STORE_INTEGRITY_FAILURE:STORE_MISSING") and not transport.calls   # store なし
    stored(root, pol)
    other = synthetic_policy(policy_key="other-synthetic-key")
    error = fails("SCREENER_POLICY_UNAVAILABLE", root=root, transport=transport, screener_policy_id=other.policy_id)
    assert error.detail == "POLICY_NOT_FOUND:POLICY_NOT_FOUND" and not transport.calls
    error = fails("SCREENER_POLICY_UNAVAILABLE", root=root, transport=transport, screener_policy_key=pol.policy_key,
                  screener_policy_version=2)
    assert error.detail == "KEY_VERSION_NOT_FOUND:KEY_VERSION_NOT_FOUND" and not transport.calls
    assert not (pilot_dir(root) / "safe_summary.json").exists()                                  # 要約は書かない
    fails("SCREENER_REQUIRES_ACQUIRED_AT", root=root, transport=transport, acquired_at=None,
          screener_policy_id=pol.policy_id)
    for selector in (dict(screener_policy_id=pol.policy_id, screener_policy_key=pol.policy_key),
                     dict(screener_policy_key=pol.policy_key), dict(screener_policy_version=1),
                     dict(screener_policy_id="p8crt_" + "0" * 24),
                     dict(screener_policy_key=pol.policy_key, screener_policy_version="1")):
        fails("SCREENER_SELECTOR_INVALID", root=root, transport=transport, **selector)
    assert not transport.calls and read(root, "budget_state.json")["used"] == 1                    # prepare の 1 だけ


def test_g_corrupted_policy_store_fails_closed_without_requests_or_repair(root: Path) -> None:
    prepared(root)
    pol = synthetic_policy()
    stored(root, pol)
    journal = root / POLICY_JOURNAL
    original = journal.read_bytes()
    transport = standard_transport()
    for tail, code in ((b"not json\n", "INVALID_RECORD"), (original, "PHYSICAL_DUPLICATE"),
                       (b'{"record_kind": "SCREENER_POLICY_AUTHORITY"', "TRUNCATED_FINAL_LINE")):
        journal.write_bytes(original + tail)
        error = fails("SCREENER_POLICY_UNAVAILABLE", root=root, transport=transport, screener_policy_id=pol.policy_id)
        assert error.detail == f"STORE_INTEGRITY_FAILURE:{code}" and journal.read_bytes() == original + tail
    assert not transport.calls and not (pilot_dir(root) / "safe_summary.json").exists()
    journal.write_bytes(original)
    assert run_with(root, screener_policy_id=pol.policy_id)["state"] == "PILOT_PASS"


def test_h_an_orchestration_failure_after_the_chain_fails_the_run_closed_and_is_not_a_result(root: Path, monkeypatch):
    prepared(root)
    pol = synthetic_policy()
    stored(root, pol)

    def mismatch(*args, **kwargs):
        raise PolicyEvaluationError(PolicyEvaluationFailure.AUTHORITY_MODE_MISMATCH, "AUTHORITY_MODE_MISMATCH")
    monkeypatch.setattr(pl, "evaluate_selected_policy", mismatch)
    summary = run_with(root, screener_policy_id=pol.policy_id)
    assert summary["state"] == "PILOT_FAILED" and summary["screener"]["state"] == "FAILED"
    assert summary["screener"]["failure_code"] == "AUTHORITY_MODE_MISMATCH"
    assert summary["screener"]["issuers"] == [{"summary": None, "failure_code": "AUTHORITY_MODE_MISMATCH"}]
    assert issuer(summary)["failure_code"] == "" and issuer(summary)["holdings_epoch_count"] == 2   # chain は無傷
    assert summary["acquisition_authority"]["state"] == "REQUESTED"
    monkeypatch.undo()
    recovered = run_with(root, screener_policy_id=pol.policy_id)                                    # replay で回復
    assert recovered["state"] == "PILOT_PASS" and screener_summary(recovered)["state"] == "MATCH"


# ================================================ I replay ・idempotency


def test_i_exact_replay_is_deterministic_and_adds_no_authority_rows(root: Path) -> None:
    prepared(root)
    pol = synthetic_policy()
    stored(root, pol)
    journal = root / POLICY_JOURNAL
    first = run_with(root, screener_policy_id=pol.policy_id)
    before = {name: (root / "screener_intelligence" / name).read_bytes()
              for name in ("screener_policy_authority.jsonl", "acquisition_events.jsonl", "acquisition_manifests.jsonl",
                           "provider_holdings_coverage.jsonl")}
    second = run_with(root, screener_policy_id=pol.policy_id)
    assert second["screener"] == first["screener"] and screener_summary(second)["state"] == "MATCH"
    assert issuer(second)["acquisition"]["reused"] is True and issuer(second)["f1"]["reused_count"] == 2
    for name, content in before.items():
        assert (root / "screener_intelligence" / name).read_bytes() == content, name           # 行は増えない
    assert journal.read_bytes().count(b"\n") == 1
    later = run_with(root, acquired_at=ACQ2, screener_policy_id=pol.policy_id)                   # 新しい取得の瞬間
    assert screener_summary(later)["evaluation_as_of"] == "2026-06-30T12:00:00+00:00"
    assert screener_summary(later)["state"] == "MATCH" and journal.read_bytes().count(b"\n") == 1
    without = run_with(root)                                                                       # 選択子なしに戻せる
    assert without["screener"]["state"] == "NOT_REQUESTED" and without["state"] == "PILOT_PASS"
    assert not (pilot_dir(root) / "screener_state.json").exists()                                # 結び付きの file は無い


# ================================================ J ・L ・M 漏れ ・予算 ・network の不変


def test_j_safe_summary_carries_no_values_thresholds_subjects_authors_or_references(root: Path) -> None:
    prepared(root)
    pol = synthetic_policy(crit_om_ge("0.05"), crit_nm_gt("0.10"), crit_growth_ge("0"))
    stored(root, pol)
    summary = run_with(root, screener_policy_id=pol.policy_id)
    text = json.dumps(summary, ensure_ascii=False)
    for forbidden in SENTINELS:
        assert forbidden not in text, forbidden
    section_text = json.dumps(summary["screener"], ensure_ascii=False)
    assert not re.search(r"\d\.\d{2,}", section_text) and "p8obs_" not in section_text and "jq." not in section_text
    assert "policy_key" not in section_text and pol.policy_key not in section_text
    assert (pilot_dir(root) / "safe_summary.json").read_text(encoding="utf-8") == json.dumps(
        summary, ensure_ascii=False, sort_keys=True, indent=2) + "\n"
    cli_text = json.dumps(summary, ensure_ascii=False, sort_keys=True, indent=2)
    for forbidden in FORBIDDEN_IN_SUMMARY:
        assert forbidden not in cli_text, forbidden


def test_l_m_request_budget_and_network_calls_are_identical_with_and_without_the_screener(root: Path, tmp_path):
    prepared(root)
    pol = synthetic_policy()
    stored(root, pol)
    plain_transport, screener_transport = standard_transport(), standard_transport()
    plain = run(root, plain_transport)
    with_screener = run_with(root, screener_transport, screener_policy_id=pol.policy_id)
    assert plain_transport.calls == screener_transport.calls and len(screener_transport.calls) == 1
    assert with_screener["request"]["used"] == plain["request"]["used"] + 1                        # 1 run ＝ fins の 1 request
    assert with_screener["request"]["paths"] == plain["request"]["paths"] + ["/v2/fins/summary"]
    assert read(root, "budget_state.json")["used"] == with_screener["request"]["used"]
    plain_again = {k: v for k, v in plain["acquisition_authority"].items() if k != "issuers"}
    screener_again = {k: v for k, v in with_screener["acquisition_authority"].items() if k != "issuers"}
    assert plain_again == screener_again
    assert issuer(with_screener)["retrospective_metrics"] == issuer(plain)["retrospective_metrics"]
    assert issuer(with_screener)["holdings_epoch_count"] == issuer(plain)["holdings_epoch_count"]
    for key in ("metrics", "fins", "store_integrity", "state", "digests", "decision_counts"):
        assert plain[key] == with_screener[key], key                                               # 既存の出力は不変
    assert with_screener["id2"]["outcome"] == "REUSED" and with_screener["id2"]["failure_code"] == ""   # replay
    assert sum(plain["exe_outcomes"].values()) == sum(with_screener["exe_outcomes"].values()) == 2  # 2 行（replay は REUSED）


# ================================================ K ・CLI ・境界


def test_k_cli_accepts_only_explicit_selectors_and_prints_only_the_safe_summary(root: Path, monkeypatch, capsys):
    prepared(root)
    pol = synthetic_policy()
    stored(root, pol)
    monkeypatch.setenv("P8_TEST_CREDENTIAL", "synthetic-not-a-real-credential")
    monkeypatch.setattr(pl, "LocalHttpsTransport", lambda credential_env: standard_transport())
    code = pl.main(["execute", "--data-root", str(root), "--acquired-at", ACQ, "--credential-env", "P8_TEST_CREDENTIAL",
                    "--screener-policy-key", pol.policy_key, "--screener-policy-version", "1"])
    out = json.loads(capsys.readouterr().out)
    assert code == 0 and out["screener"]["selector_kind"] == "KEY_VERSION" and screener_summary(out)["state"] == "MATCH"
    code = pl.main(["execute", "--data-root", str(root), "--acquired-at", ACQ, "--credential-env", "P8_TEST_CREDENTIAL",
                    "--screener-policy-id", "p8pol_" + "0" * 24])
    out = json.loads(capsys.readouterr().out)
    assert code == 2 and out == {"state": "FAILED", "code": "SCREENER_POLICY_UNAVAILABLE",
                                 "detail": "POLICY_NOT_FOUND:POLICY_NOT_FOUND"}
    with pytest.raises(SystemExit):
        pl.main(["execute", "--data-root", str(root), "--screener-policy-version", "x"])          # int だけ
    parser = pl._parser()
    options = {a.option_strings[0] for a in parser._subparsers._group_actions[0].choices["execute"]._actions
               if a.option_strings}
    assert {"--screener-policy-id", "--screener-policy-key", "--screener-policy-version"} <= options
    assert not any("latest" in o or "current" in o or "default" in o for o in options)


def test_k_the_runner_consumes_only_b4a_and_keeps_the_frozen_chain_untouched() -> None:
    source = RUNNER.read_text(encoding="utf-8")
    lowered = executable_source(RUNNER).lower()
    tree = ast.parse(source)
    imports = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.level:
            imports[node.module] = {a.name for a in node.names}
    assert imports["screener_intelligence.screener_policy_evaluation"] == {
        "PolicyEvaluationError", "PolicySelector", "evaluate_selected_policy", "open_verified_store", "resolve_policy"}
    assert imports["screener_intelligence.screener_result_summary"] == {"project_safe_summary"}
    assert imports["screener_intelligence.screener_evaluator"] == {"EvaluationInputs"}             # 評価は B4A 経由だけ
    assert imports["screener_intelligence.screener_criteria_model"] == {"EvaluationContext", "ScreenerModelError"}
    assert not any(m.startswith("screener_intelligence.screener_policy_authority") for m in imports)
    assert "evaluate_policy(" not in source and "project_safe_summary(" in source
    assert "evaluate_selected_policy(root, selector, context, inputs)" in source
    assert "evaluation_as_of=acquired_at, identity_valid_at=acquired_at" in source
    assert "authority_mode=record.policy.authority_mode, policy_id=record.policy.policy_id" in source
    assert "open_verified_store(root)" in source and "PolicyAuthorityStore" not in source
    for token in ("screening", "rank", "score", "recommend", "latest", "current_policy", "default_policy",
                  "watchlist", "portfolio", "target_price", "expected_return", "match_count", "threshold",
                  "observed_value", "get_by_policy_id", "list_metadata", "store.append", "screener_result"):
        assert token not in lowered.replace("screener_result_summary", "").replace("project_safe_summary", ""), token
    assert "SCREENER_RESULT" not in source and "screener_results.jsonl" not in source              # 結果の journal は無い
    assert pl.SCREENER_SECTION_STATES == ("NOT_REQUESTED", "REQUESTED", "FAILED")
    assert pl.SUMMARY_SCHEMA == "p8_pilot2_safe_summary:0.1.0"                                       # 版は上げない
    package = REPO_ROOT / PHASE8_PACKAGE
    for path in sorted(package.glob("*.py")):
        assert "screener_policy_id" not in path.read_text(encoding="utf-8"), path.name
    for line in source.splitlines():
        assert len(line) <= 120, line
