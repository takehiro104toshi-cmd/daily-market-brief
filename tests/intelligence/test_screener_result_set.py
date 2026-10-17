"""P8-B5B — 複数発行体の全結果の集合 ・完全性 ・安全な投影の test（純 ・決定論 ・合成）。

発行体の評価は凍結 B1 の合成の `ScreenerResult` を凍結 B4A の `project_safe_summary` に通したもの（値 ・閾値は投影の前に落ちる）。
pin するもの: member の結果（code ごと）と発行体の結果（IssuerId ごと）の分離 ・複数の code → 1 発行体 ・すべての member がちょうど 1 回 ・
発行体の結果の参照の整合 ・方針 ／ mode ／ 瞬間の一致 ・単一の authority の日 ・非意味の決定論の順 ・実行の完全性と data の完全性の分離 ・
派生の MATCH の部分集合 ・coverage の件数 ・安全な投影の漏れなし ・決定論の id ・保存 ・network ・順位なし。
"""
from __future__ import annotations

import ast
import json
from dataclasses import FrozenInstanceError, fields, replace
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pytest

from src.intelligence.screener_intelligence import screener_result_set as rs
from src.intelligence.screener_intelligence import screener_result_set_projection as rp
from src.intelligence.screener_intelligence.screener_criteria_model import (CriterionState, DataCompleteness,
                                                                            ScreenerAuthorityMode, ScreenerState)
from src.intelligence.screener_intelligence.screener_result_set import (ExecutionCompleteness, IssuerResult,
                                                                        MemberOutcome, MemberOutcomeKind,
                                                                        ResultSetError, ScreenResultSet,
                                                                        assemble_result_set)
from src.intelligence.screener_intelligence.screener_result_summary import project_safe_summary
from tests.intelligence.phase8_runtime_registry import PHASE8_PACKAGE
from tests.intelligence.test_prediction_record import executable_source
from tests.intelligence.test_screener_criteria_model import (EVAL, SYNTHETIC_THRESHOLD, criterion, policy, result,
                                                             screener)

REPO_ROOT = Path(__file__).resolve().parents[2]
PACKAGE_DIR = REPO_ROOT / PHASE8_PACKAGE
MODULE = PACKAGE_DIR / "screener_result_set.py"
PROJECTION = PACKAGE_DIR / "screener_result_set_projection.py"
JST = timezone(timedelta(hours=9))
RETRO = ScreenerAuthorityMode.RETROSPECTIVE_PROVIDER_AUTHORITY
D0 = date(2026, 10, 6)                                                                    # EVAL（B1 の合成）の JST の日
UNIVERSE_ID = "p8uni_" + "a" * 24
POL = policy()
#: 合成の code と発行体（実の上場物 ・発行体ではない）
A, B, C, D, E, F, G = "90010", "90020", "90030", "90040", "90050", "90060", "90070"
I1, I2, I3 = "p8iss_" + "1" * 24, "p8iss_" + "2" * 24, "p8iss_" + "3" * 24


def evaluation(state: ScreenerState = ScreenerState.MATCH, *, pol=POL, evaluation_as_of: datetime = EVAL):
    """凍結 B1 の合成の結果 → 凍結 B4A の投影（値 ・閾値 ・主語は投影で落ちる）。"""
    crit = pol.criteria[0]
    per_criterion = {ScreenerState.MATCH: CriterionState.MATCH, ScreenerState.NO_MATCH: CriterionState.NO_MATCH,
                     ScreenerState.HOLD: CriterionState.HOLD, ScreenerState.NOT_EVALUABLE: CriterionState.NOT_EVALUABLE,
                     ScreenerState.AUTHORITY_FAILURE: CriterionState.AUTHORITY_FAILURE}[state]
    extra = {} if per_criterion in (CriterionState.MATCH, CriterionState.NO_MATCH) else dict(
        reason_codes=("OPERATING_INCOME:FIELD_NOT_REPORTED_IN_EPOCH",), coverage_epoch_ids=(), manifest_refs=(),
        observation_ids=())
    private = screener((result(crit, per_criterion, **extra),), state, pol=pol, evaluation_as_of=evaluation_as_of,
                       identity_valid_at=evaluation_as_of)
    return project_safe_summary(private)


def issuer(issuer_id: str, state: ScreenerState = ScreenerState.MATCH, **kwargs) -> IssuerResult:
    return IssuerResult(issuer_id=issuer_id, evaluation=evaluation(state, **kwargs))


def evaluated(code: str, issuer_id: str) -> MemberOutcome:
    return MemberOutcome(member_code=code, kind=MemberOutcomeKind.EVALUATED, issuer_id=issuer_id)


def outcome(code: str, kind: MemberOutcomeKind, *reasons: str) -> MemberOutcome:
    codes = reasons or (f"SYNTHETIC_{kind.value}",)
    return MemberOutcome(member_code=code, kind=kind, reason_codes=tuple(sorted(codes)))


def result_set(members, outcomes, issuers, **overrides) -> ScreenResultSet:
    base = dict(universe_id=UNIVERSE_ID, universe_version=1, universe_members=tuple(members), policy_id=POL.policy_id,
                policy_version=POL.version, authority_mode=RETRO, authority_day=D0, evaluation_as_of=EVAL,
                member_outcomes=tuple(outcomes), issuer_results=tuple(issuers))
    return ScreenResultSet(**{**base, **overrides})


def mixed() -> ScreenResultSet:
    """7 member: 2 code → I1（MATCH）、I2 は NO_MATCH、I3 は NOT_EVALUABLE、不適格 ・未解決 ・予算の延期が 1 つずつ。"""
    return result_set((A, B, C, D, E, F, G),
                      (evaluated(A, I1), outcome(B, MemberOutcomeKind.NOT_ELIGIBLE, "CODE_NOT_COMMON_EQUITY"),
                       evaluated(C, I2), evaluated(D, I1), evaluated(E, I3),
                       outcome(F, MemberOutcomeKind.IDENTITY_UNRESOLVED, "SUBJECT_NOT_RESOLVED"),
                       outcome(G, MemberOutcomeKind.BUDGET_DEFERRED, "BUDGET_EXHAUSTED")),
                      (issuer(I1), issuer(I2, ScreenerState.NO_MATCH), issuer(I3, ScreenerState.NOT_EVALUABLE)))


def rejects(code: str, fn, *args, **kwargs) -> None:
    with pytest.raises(ResultSetError) as exc:
        fn(*args, **kwargs)
    assert exc.value.code == code, exc.value.code


# ================================================ A member の結果 ・発行体の結果


def test_a_member_outcomes_are_closed_and_only_evaluated_members_reference_an_issuer() -> None:
    assert [k.value for k in MemberOutcomeKind] == ["EVALUATED", "NOT_ELIGIBLE", "IDENTITY_UNRESOLVED",
                                                     "ACQUISITION_FAILED", "BUDGET_DEFERRED", "NOT_ATTEMPTED"]
    assert evaluated(A, I1).as_dict() == {"issuer_id": I1, "kind": "EVALUATED", "member_code": A, "reason_codes": []}
    rejects("EVALUATED_REQUIRES_ISSUER", MemberOutcome, member_code=A, kind=MemberOutcomeKind.EVALUATED)
    rejects("EVALUATED_REQUIRES_ISSUER", MemberOutcome, member_code=A, kind=MemberOutcomeKind.EVALUATED,
            issuer_id="p8sec_" + "1" * 24)
    for kind in set(MemberOutcomeKind) - {MemberOutcomeKind.EVALUATED}:
        rejects("ISSUER_ONLY_FOR_EVALUATED", MemberOutcome, member_code=A, kind=kind, issuer_id=I1,
                reason_codes=("X",))                                              # Screener の状態を装わない
        rejects("NON_EVALUATED_REQUIRES_REASON", MemberOutcome, member_code=A, kind=kind)
    rejects("INVALID_MEMBER_CODE", MemberOutcome, member_code="9001", kind=MemberOutcomeKind.NOT_ATTEMPTED,
            reason_codes=("X",))
    rejects("INVALID_REASON_CODES", outcome, A, MemberOutcomeKind.NOT_ELIGIBLE, "lower case")
    rejects("REASON_CODES_NOT_CANONICAL", MemberOutcome, member_code=A, kind=MemberOutcomeKind.NOT_ELIGIBLE,
            reason_codes=("B", "A"))
    assert not any(f.name in {"state", "screener_state", "score", "rank"} for f in fields(MemberOutcome))


def test_a_issuer_results_compose_the_frozen_b4a_projection_without_values_or_new_states() -> None:
    result_ = issuer(I1)
    assert result_.state is ScreenerState.MATCH and result_.completeness is DataCompleteness.COMPLETE
    assert "0.0200" not in json.dumps(result_.as_dict()) and SYNTHETIC_THRESHOLD not in json.dumps(result_.as_dict())
    rejects("INVALID_ISSUER", IssuerResult, issuer_id="p8sec_" + "1" * 24, evaluation=evaluation())
    rejects("INVALID_EVALUATION", IssuerResult, issuer_id=I1, evaluation=evaluation().as_dict())
    assert {f.name for f in fields(IssuerResult)} == {"issuer_id", "evaluation"}
    assert {s.value for s in ScreenerState} == {"MATCH", "NO_MATCH", "HOLD", "NOT_EVALUABLE", "AUTHORITY_FAILURE"}


# ================================================ B 全結果の集合の不変条件


def test_b_a_valid_mixed_result_set_with_two_codes_for_one_issuer() -> None:
    s = mixed()
    assert [m.member_code for m in s.member_outcomes] == [A, B, C, D, E, F, G]
    assert [r.issuer_id for r in s.issuer_results] == [I1, I2, I3]                         # 最初の参照の順（非意味）
    assert s.source_members(I1) == (A, D) and s.source_members(I2) == (C,)                 # 1 発行体 ＝ 1 評価
    assert s.member_outcome_counts == {"EVALUATED": 4, "NOT_ELIGIBLE": 1, "IDENTITY_UNRESOLVED": 1,
                                       "ACQUISITION_FAILED": 0, "BUDGET_DEFERRED": 1, "NOT_ATTEMPTED": 0}
    assert s.screener_state_counts == {"MATCH": 1, "NO_MATCH": 1, "HOLD": 0, "NOT_EVALUABLE": 1,
                                       "AUTHORITY_FAILURE": 0}
    assert s.data_completeness_counts == {"COMPLETE": 2, "PARTIAL": 0, "NONE": 1}
    assert s.execution_completeness is ExecutionCompleteness.PARTIAL                     # 予算の延期が残る
    assert s.match_issuer_ids == (I1,)
    assert s.authority_class == "DERIVED_NON_AUTHORITY_NON_PERSISTENT"
    with pytest.raises(FrozenInstanceError):
        s.member_outcomes = ()                                                           # type: ignore[misc]


@pytest.mark.parametrize("build, code", [
    (lambda: result_set((A, B), (evaluated(A, I1),), (issuer(I1),)), "MISSING_MEMBER_OUTCOME"),
    (lambda: result_set((A,), (evaluated(A, I1), outcome(B, MemberOutcomeKind.NOT_ATTEMPTED)), (issuer(I1),)),
     "EXTRA_MEMBER_OUTCOME"),
    (lambda: result_set((A, B), (evaluated(A, I1), evaluated(A, I1)), (issuer(I1),)), "DUPLICATE_MEMBER_OUTCOME"),
    (lambda: result_set((A,), (evaluated(A, I1),), (issuer(I1), issuer(I1))), "DUPLICATE_ISSUER_RESULT"),
    (lambda: result_set((A,), (evaluated(A, I1),), (issuer(I1), issuer(I2))), "ORPHAN_ISSUER_RESULT"),
    (lambda: result_set((A,), (outcome(A, MemberOutcomeKind.NOT_ELIGIBLE),), (issuer(I1),)), "ORPHAN_ISSUER_RESULT"),
    (lambda: result_set((A,), (evaluated(A, I1),), ()), "EVALUATED_MEMBER_WITHOUT_ISSUER_RESULT"),
    (lambda: result_set((A, B), (outcome(B, MemberOutcomeKind.NOT_ATTEMPTED), evaluated(A, I1)), (issuer(I1),)),
     "MEMBER_ORDER_NOT_DECLARED_ORDER"),
    (lambda: result_set((A, B), (evaluated(A, I1), evaluated(B, I2)), (issuer(I2), issuer(I1))),
     "ISSUER_ORDER_NOT_FIRST_MEMBER_ORDER"),
    (lambda: result_set((A,), (evaluated(A, I1),), (issuer(I1, pol=policy(version=2)),)), "POLICY_MISMATCH"),
    (lambda: result_set((A,), (evaluated(A, I1),), (issuer(I1),), policy_version=2), "POLICY_MISMATCH"),
    (lambda: result_set((A,), (evaluated(A, I1),), (issuer(I1),), authority_mode=ScreenerAuthorityMode.STRICT_PIT),
     "AUTHORITY_MODE_MISMATCH"),
    (lambda: result_set((A,), (evaluated(A, I1),), (issuer(I1, evaluation_as_of=EVAL + timedelta(minutes=1)),)),
     "EVALUATION_INSTANT_MISMATCH"),
    (lambda: result_set((A,), (evaluated(A, I1),), (issuer(I1),), authority_day=D0 + timedelta(days=1)),
     "EVALUATION_OUTSIDE_AUTHORITY_DAY"),
    (lambda: result_set((A, A), (evaluated(A, I1),), (issuer(I1),)), "DUPLICATE_UNIVERSE_MEMBER"),
    (lambda: result_set((), (), ()), "EMPTY_UNIVERSE"),
    (lambda: result_set((A,), (evaluated(A, I1),), (issuer(I1),), universe_id="p8pol_" + "a" * 24),
     "INVALID_UNIVERSE_ID"),
    (lambda: result_set((A,), (evaluated(A, I1),), (issuer(I1),), universe_version=0), "INVALID_VERSION"),
    (lambda: result_set((A,), (evaluated(A, I1),), (issuer(I1),), evaluation_as_of=datetime(2026, 10, 6, 18)),
     "NAIVE_OR_MISSING_DATETIME"),
    (lambda: result_set((A,), (evaluated(A, I1),), (issuer(I1),), authority_day=datetime(2026, 10, 6, tzinfo=JST)),
     "INVALID_AUTHORITY_DAY")])
def test_b_impossible_structures_fail_closed(build, code) -> None:
    rejects(code, build)


def test_b_the_authority_day_is_the_jst_calendar_day_of_the_evaluation_instant() -> None:
    late = datetime(2026, 10, 6, 23, 59, 59, tzinfo=JST)
    assert result_set((A,), (evaluated(A, I1),), (issuer(I1, evaluation_as_of=late),),
                      evaluation_as_of=late).authority_day == D0
    utc_same_instant = late.astimezone(timezone.utc)                                     # 同じ瞬間の UTC 表現も同じ日
    assert result_set((A,), (evaluated(A, I1),), (issuer(I1, evaluation_as_of=late),),
                      evaluation_as_of=utc_same_instant).authority_day == D0
    rejects("EVALUATION_OUTSIDE_AUTHORITY_DAY", result_set, (A,), (evaluated(A, I1),),
            (issuer(I1, evaluation_as_of=late + timedelta(seconds=1)),), evaluation_as_of=late + timedelta(seconds=1))


# ================================================ C 完全性（実行 ≠ 財務 data）・MATCH の部分集合


def test_c_execution_completeness_is_terminal_attempts_only_and_financial_states_never_make_it_partial() -> None:
    five = ["p8iss_" + f"{n}" * 24 for n in range(1, 6)]
    every_state = result_set((A, B, C, D, E), tuple(evaluated(code, i) for code, i in zip((A, B, C, D, E), five)),
                             tuple(issuer("p8iss_" + f"{n}" * 24, state) for n, state in
                                   zip(range(1, 6), (ScreenerState.MATCH, ScreenerState.NO_MATCH, ScreenerState.HOLD,
                                                     ScreenerState.NOT_EVALUABLE, ScreenerState.AUTHORITY_FAILURE))))
    assert every_state.execution_completeness is ExecutionCompleteness.COMPLETE           # NOT_EVALUABLE ・失敗も終端
    assert every_state.screener_state_counts == {s.value: 1 for s in ScreenerState}
    terminal = result_set((A, B, C, D), (evaluated(A, I1), outcome(B, MemberOutcomeKind.NOT_ELIGIBLE),
                                         outcome(C, MemberOutcomeKind.IDENTITY_UNRESOLVED),
                                         outcome(D, MemberOutcomeKind.ACQUISITION_FAILED)), (issuer(I1),))
    assert terminal.execution_completeness is ExecutionCompleteness.COMPLETE
    for kind in (MemberOutcomeKind.BUDGET_DEFERRED, MemberOutcomeKind.NOT_ATTEMPTED):
        partial = result_set((A, B), (evaluated(A, I1), outcome(B, kind)), (issuer(I1),))
        assert partial.execution_completeness is ExecutionCompleteness.PARTIAL, kind
    nothing = result_set((A,), (outcome(A, MemberOutcomeKind.NOT_ATTEMPTED),), ())
    assert nothing.execution_completeness is ExecutionCompleteness.PARTIAL and nothing.match_issuer_ids == ()
    assert set(rs.TERMINAL_MEMBER_OUTCOMES) == set(MemberOutcomeKind) - {MemberOutcomeKind.BUDGET_DEFERRED,
                                                                         MemberOutcomeKind.NOT_ATTEMPTED}
    assert {c.value for c in ExecutionCompleteness} == {"COMPLETE", "PARTIAL"}


def test_c_all_match_and_the_match_subset_is_only_derived_from_the_full_result() -> None:
    all_match = result_set((A, B), (evaluated(A, I1), evaluated(B, I2)), (issuer(I1), issuer(I2)))
    assert all_match.match_issuer_ids == (I1, I2) and all_match.screener_state_counts["MATCH"] == 2
    s = mixed()
    full = s.as_dict()
    assert full["match_issuer_ids"] == [I1] and full["match_subset_meaning"].startswith("ISSUERS_WHOSE_EVALUATION")
    assert len(full["member_outcomes"]) == 7 and len(full["issuer_results"]) == 3          # 全結果が先 ・MATCH は派生
    public = {n for n in dir(ScreenResultSet) if not n.startswith("_")}
    assert not any(word in n for n in public for word in ("top", "best", "rank", "score", "sorted", "latest"))


def test_c_assembly_orders_deterministically_and_non_semantically() -> None:
    outcomes = {G: outcome(G, MemberOutcomeKind.BUDGET_DEFERRED, "BUDGET_EXHAUSTED"), A: evaluated(A, I1),
                E: evaluated(E, I3), C: evaluated(C, I2), D: evaluated(D, I1),
                F: outcome(F, MemberOutcomeKind.IDENTITY_UNRESOLVED, "SUBJECT_NOT_RESOLVED"),
                B: outcome(B, MemberOutcomeKind.NOT_ELIGIBLE, "CODE_NOT_COMMON_EQUITY")}
    issuers = [issuer(I3, ScreenerState.NOT_EVALUABLE), issuer(I1), issuer(I2, ScreenerState.NO_MATCH)]
    built = assemble_result_set(universe_id=UNIVERSE_ID, universe_version=1, universe_members=(A, B, C, D, E, F, G),
                                policy_id=POL.policy_id, policy_version=1, authority_mode=RETRO, authority_day=D0,
                                evaluation_as_of=EVAL, member_outcomes=outcomes, issuer_results=issuers)
    assert built == mixed() and built.screen_result_id == mixed().screen_result_id
    assert [r.issuer_id for r in built.issuer_results] == [I1, I2, I3]                    # 状態 ・値の順ではない
    reordered = assemble_result_set(universe_id=UNIVERSE_ID, universe_version=1,
                                    universe_members=(G, F, E, D, C, B, A), policy_id=POL.policy_id,
                                    policy_version=1, authority_mode=RETRO, authority_day=D0, evaluation_as_of=EVAL,
                                    member_outcomes=outcomes, issuer_results=issuers)
    assert [r.issuer_id for r in reordered.issuer_results] == [I3, I1, I2]                # 宣言の順に従うだけ
    assert reordered.screener_state_counts == built.screener_state_counts
    assert rs.MEMBER_ORDER_RULE.endswith("NON_SEMANTIC") and rs.ISSUER_ORDER_RULE.endswith("NON_SEMANTIC")
    with pytest.raises(ResultSetError) as exc:
        assemble_result_set(universe_id=UNIVERSE_ID, universe_version=1, universe_members=(A, B),
                            policy_id=POL.policy_id, policy_version=1, authority_mode=RETRO, authority_day=D0,
                            evaluation_as_of=EVAL, member_outcomes={A: evaluated(A, I1), B: evaluated(A, I1)},
                            issuer_results=[issuer(I1)])
    assert exc.value.code == "MEMBER_OUTCOME_KEY_MISMATCH"


def test_c_the_result_identity_is_deterministic_and_covers_outcomes_but_not_serialization() -> None:
    s = mixed()
    assert s.screen_result_id == mixed().screen_result_id and s.screen_result_id.startswith("p8srs_")
    changed = [result_set((A,), (evaluated(A, I1),), (issuer(I1),)),
               result_set((A,), (evaluated(A, I1),), (issuer(I1, ScreenerState.NO_MATCH),)),
               result_set((A,), (outcome(A, MemberOutcomeKind.NOT_ELIGIBLE),), ()),
               result_set((A,), (evaluated(A, I1),), (issuer(I1),), universe_version=2)]
    assert len({c.screen_result_id for c in changed}) == 4
    utc = result_set((A,), (evaluated(A, I1),), (issuer(I1, evaluation_as_of=EVAL.astimezone(timezone.utc)),),
                     evaluation_as_of=EVAL.astimezone(timezone.utc))
    assert utc.screen_result_id == changed[0].screen_result_id                            # 同じ瞬間の表現の差は id に入らない


# ================================================ D coverage の偏り ・安全な投影


def test_d_coverage_counts_distinguish_five_of_five_from_five_of_a_hundred() -> None:
    codes = tuple(f"9{n:03d}0" for n in range(100))
    ids = ["p8iss_" + f"{n:024x}" for n in range(1, 101)]
    small = result_set(codes[:5], [evaluated(c, i) for c, i in zip(codes[:5], ids)], [issuer(i) for i in ids[:5]])
    big_outcomes = [evaluated(c, i) for c, i in zip(codes, ids)]
    big_issuers = [issuer(i) for i in ids[:5]] + [issuer(i, ScreenerState.NOT_EVALUABLE) for i in ids[5:]]
    big = result_set(codes, big_outcomes, big_issuers)
    small_safe, big_safe = rp.project_safe_set_summary(small), rp.project_safe_set_summary(big)
    assert small_safe.screener_state_counts["MATCH"] == big_safe.screener_state_counts["MATCH"] == 5
    assert small_safe.as_dict() != big_safe.as_dict()
    assert (big_safe.member_count, big_safe.issuer_count) == (100, 100)
    assert big_safe.screener_state_counts["NOT_EVALUABLE"] == 95
    assert big_safe.data_completeness_counts == {"COMPLETE": 5, "PARTIAL": 0, "NONE": 95}
    assert big_safe.evaluation_reason_code_counts == {"OPERATING_INCOME:FIELD_NOT_REPORTED_IN_EPOCH": 95}
    assert not any(isinstance(v, float) for v in big_safe.as_dict().values())            # 比率 ・点数は無い


def test_d_the_safe_projection_structurally_excludes_identities_values_thresholds_and_references() -> None:
    s = mixed()
    safe = rp.project_safe_set_summary(s)
    data = safe.as_dict()
    assert set(data) == {"authority_day", "authority_mode", "data_completeness_counts", "evaluation_reason_code_counts",
                         "execution_completeness", "issuer_count", "match_subset_meaning", "member_count",
                         "member_outcome_counts", "member_reason_code_counts", "policy_ref", "policy_version",
                         "rules_version", "schema_version", "screener_state_counts", "summary_class",
                         "universe_version"}
    assert not set(data) & set(rp.FORBIDDEN_SET_SUMMARY_FIELDS)
    assert not set(rp.set_summary_field_names()) & set(rp.FORBIDDEN_SET_SUMMARY_FIELDS)
    text = safe.canonical_json()
    private = json.dumps(s.as_dict())
    for present in (I1, I2, I3, A, G, UNIVERSE_ID, s.screen_result_id, "p8crt_"):        # private の全結果は持つ
        assert present in private, present
    for sentinel in (I1, I2, I3, A, B, C, D, E, F, G, UNIVERSE_ID, s.screen_result_id, "p8crt_", "p8obs_", "jq.pvh:",
                     "jq.man:", "0.0200", SYNTHETIC_THRESHOLD, "human:reviewer-1", "synthetic fixture",
                     "2026-10-06T09:00", "p8iss_", "api_key", "/"):
        assert sentinel not in text, sentinel                                              # 投影は持たない
    assert data["authority_day"] == "2026-10-06" and data["execution_completeness"] == "PARTIAL"
    assert data["member_outcome_counts"]["BUDGET_DEFERRED"] == 1 and data["member_count"] == 7
    assert data["member_reason_code_counts"] == {"BUDGET_EXHAUSTED": 1, "CODE_NOT_COMMON_EQUITY": 1,
                                                 "SUBJECT_NOT_RESOLVED": 1}
    assert data["policy_ref"] == POL.policy_id and data["summary_class"].endswith("PRIVATE_LOCAL")
    assert safe.canonical_json() == rp.project_safe_set_summary(mixed()).canonical_json()  # 決定論
    lowered = text.lower()
    for word in ("top", "best", "rank", "score", "recommend", "buy", "attractive", "winner", "watchlist", "confidence"):
        assert word not in lowered, word
    with pytest.raises(ResultSetError) as exc:
        replace(safe, member_count=8)
    assert exc.value.code == "COUNT_MISMATCH"


# ================================================ E 境界（純 ・保存なし ・network なし ・解決 ・適格の実行なし）


def test_e_the_result_layer_is_pure_and_imports_only_frozen_semantic_types() -> None:
    for module, allowed in ((MODULE, {"__future__", "re", "dataclasses", "datetime", "enum", "typing", "..core.ids",
                                      "..core.time", ".identity_bootstrap_model", ".identity_model", ".metric_model",
                                      ".screener_criteria_model", ".screener_result_summary"}),
                            (PROJECTION, {"__future__", "dataclasses", "datetime", "typing", ".identity_model",
                                          ".screener_result_set"})):
        tree = ast.parse(module.read_text(encoding="utf-8"))
        imported = {"." * node.level + (node.module or "") for node in ast.walk(tree)
                    if isinstance(node, ast.ImportFrom)}
        imported |= {alias.name for node in ast.walk(tree) if isinstance(node, ast.Import) for alias in node.names}
        assert imported == allowed, (module.name, imported ^ allowed)
        names = {alias.name for node in ast.walk(tree) if isinstance(node, ast.ImportFrom) for alias in node.names}
        assert not any(n.startswith("_") for n in names - {"__future__"})
        for node in ast.walk(tree):
            assert not (isinstance(node, ast.Name) and node.id in {"open", "Path", "os", "float", "round", "print"})
            assert not (isinstance(node, ast.Attribute) and node.attr in {"now", "utcnow", "today", "write",
                                                                          "write_text", "mkdir", "fsync"}), node.attr
            assert not (isinstance(node, ast.ExceptHandler) and (node.type is None or (
                isinstance(node.type, ast.Name) and node.type.id == "Exception"))), "broad except"
            assert not (isinstance(node, ast.BinOp) and isinstance(node.op, (ast.Div, ast.FloorDiv, ast.Mult, ast.Mod,
                                                                           ast.Pow))), ast.dump(node)  # 比率 ・点数なし
        for line in module.read_text(encoding="utf-8").splitlines():
            assert len(line) <= 120, line
    source = executable_source(MODULE).lower() + executable_source(PROJECTION).lower()
    for token in ("jquants_live", "jquants_master", "transport", "identity_store", "identity_resolver", "assess_master",
                  "evaluate_policy",
                  "screener_evaluator", "policy_authority_store", "screener_universe", "pilot2", "theme", "narrative",
                  "calibration", "watchlist", "portfolio", "latest", "llm", "prompt", "sqlite", "jsonl", "journal",
                  "sorted(" + "self.issuer_results"):
        assert token not in source, token
    assert not list(REPO_ROOT.glob("**/*screen_result*.jsonl"))
