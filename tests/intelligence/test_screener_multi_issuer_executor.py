"""P8-B5C — 複数発行体の private 実行器（有限の batch ・決定論の継続の台帳）の test。合成の transport だけ（実 request なし）。

合成の identity（人が審査した形の凍結 A1 の record）・合成の Universe（B5A）・合成の方針（B3）・合成の master ／ fins の応答。pin するもの:
複数の呼び出しにまたがる継続（PARTIAL → 継続 → COMPLETE）・member の欠落 ／ 重複なし ・発行体の評価は 1 回 ・呼び出しごとの予算 ≤ 8 ・累計の
request ・決定論の順 ・方針 ／ Universe ／ 日 ／ mode ／ 瞬間の不変 ・混合の状態 ・不一致は network の前に fail closed ・台帳の破損は fail closed ・
D0 をまたぐ継続の拒否 ・凍結の部品の不変。
"""
from __future__ import annotations

import ast
import json
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pytest

from src.intelligence import jquants_screen_local as sl
from src.intelligence.jquants_screen_local import ScreenRunError, execute_screen, ledger_path, load_ledger
from src.intelligence.screener_intelligence import identity_model as im
from src.intelligence.screener_intelligence.identity_store import IdentityStore
from src.intelligence.screener_intelligence.jquants_live_model import SyntheticTransport, TransportResponse
from src.intelligence.screener_intelligence.metric_model import MetricKind
from src.intelligence.screener_intelligence.screener_criteria_model import (CriterionOperator, PeriodRule,
                                                                            ScreenerAuthorityMode)
from src.intelligence.screener_intelligence.screener_policy_authority_model import PolicyAuthorityRecord
from src.intelligence.screener_intelligence.screener_policy_authority_store import PolicyAuthorityStore
from src.intelligence.screener_intelligence.screener_result_set import MemberOutcomeKind
from src.intelligence.screener_intelligence.screener_universe_model import UniverseAuthorityRecord, UniverseSpec
from src.intelligence.screener_intelligence.screener_universe_store import UniverseAuthorityStore
from tests.intelligence.test_prediction_record import executable_source
from tests.intelligence.test_screener_criteria_model import criterion, policy
from tests.intelligence.test_screener_jquants_adapter import row as fins_row
from tests.intelligence.test_screener_jquants_live import fins_key, master, master_key, payload

REPO_ROOT = Path(__file__).resolve().parents[2]
RUNNER = REPO_ROOT / "src/intelligence/jquants_screen_local.py"
JST = timezone(timedelta(hours=9))
D0 = date(2026, 6, 30)
D0S = "2026-06-30"
T = datetime(2026, 6, 30, 22, 0, tzinfo=JST)                                             # 宣言の評価の瞬間（D0 の中）
ACQ = [datetime(2026, 6, 30, 20, 0, tzinfo=JST), datetime(2026, 6, 30, 20, 30, tzinfo=JST),
       datetime(2026, 6, 30, 21, 0, tzinfo=JST), datetime(2026, 6, 30, 21, 30, tzinfo=JST)]
RETRO = ScreenerAuthorityMode.RETROSPECTIVE_PROVIDER_AUTHORITY
K = MemberOutcomeKind
REVIEWED = datetime(2026, 6, 30, 9, 0, tzinfo=JST)


def fins(code: str, *, op: str = "40000000000") -> list:
    """合成の 2 期の年度（営業利益率 ≈ 0.08。`op` で変える）。"""
    return [fins_row(Code=code, DiscNo=f"{year}0512{code}", DiscDate=f"{year}-05-12", CurPerSt=f"{year - 1}-04-01",
                     CurPerEn=f"{year}-03-31", CurFYSt=f"{year - 1}-04-01", CurFYEn=f"{year}-03-31",
                     Sales="500000000000", OP=op, NP="30000000000", TA="900000000000",
                     DocType="FYFinancialStatements_Consolidated_JP") for year in (2024, 2025)]


def identity(root: Path, groups) -> dict:
    """合成の人が審査した identity: groups ＝ [(発行体の anchor, [code, ...]), ...]。D0 の identity coverage つき。"""
    store = IdentityStore.initialize(root)
    known = datetime(2026, 6, 30, 9, 0, tzinfo=JST)

    def prov():
        return im.SourceProvenance(source_class=im.SourceClass.HUMAN_REVIEWED, source_record_ref="review:b5c",
                                   known_at=known)
    issuers = {}
    for anchor, codes in groups:
        issuer = im.IssuerRegistration(registration_anchor=f"hr:{anchor}", provenance=prov())
        store.append(issuer)
        for code in codes:
            security = im.SecurityRegistration(registration_anchor=f"hr:{anchor}-{code}", issuer_id=issuer.issuer_id,
                                               issue_class=im.IssueClass.COMMON_EQUITY, provenance=prov())
            store.append(security)
            store.append(im.IdentifierAssignment(security_id=security.security_id,
                                                 scheme=im.IdentifierScheme.JQUANTS_CODE, value=code,
                                                 effective_from=known, provenance=prov()))
            store.append(im.ListingStart(security_id=security.security_id, venue=im.ListingVenue.TSE,
                                         effective_from=known, provenance=prov()))
        issuers[anchor] = issuer.issuer_id
    store.append(im.Coverage(scope=im.CoverageScope.JP_LISTED_EQUITY_IDENTITY,
                             effective_from=datetime(2026, 6, 30, 0, 0, tzinfo=JST),
                             effective_to=datetime(2026, 7, 1, 0, 0, tzinfo=JST), provenance=prov()))
    return issuers


def authorities(root: Path, members, *, threshold: str = "0.05", version: int = 1):
    universe = UniverseSpec(universe_key="synthetic-screen", version=version, intent="synthetic bounded test scope",
                            members=tuple(members))
    UniverseAuthorityStore.initialize(root).append(
        UniverseAuthorityRecord(universe=universe, author_ref="human:synthetic", reviewed_at=REVIEWED))
    pol = policy(criterion(metric=MetricKind.OPERATING_MARGIN, operator=CriterionOperator.GE, threshold=threshold,
                           period_rule=PeriodRule.NEWEST_SUPPORTED_FY_OR_CUMULATIVE), version=version)
    PolicyAuthorityStore.initialize(root).append(PolicyAuthorityRecord(policy=pol))
    return universe, pol


def transport(master_rows, fins_map) -> SyntheticTransport:
    mapping = {master_key(D0S): TransportResponse(200, payload(*master_rows))}
    for code, response in fins_map.items():
        mapping[fins_key(code)] = response if isinstance(response, TransportResponse) else TransportResponse(
            200, payload(*response))
    return SyntheticTransport(mapping)


def run(root, universe, pol, tx, acquired_at, *, continue_run_id=None, budget_limit=8, **overrides):
    base = dict(data_root=root, transport=tx, d0=D0S, evaluation_as_of=T, authority_mode=RETRO.value,
                acquired_at=acquired_at, universe_id=universe.universe_id, policy_id=pol.policy_id,
                continue_run_id=continue_run_id, budget_limit=budget_limit)
    return execute_screen(**{**base, **overrides})


def fails(code: str, fn, *args, **kwargs) -> ScreenRunError:
    with pytest.raises(ScreenRunError) as exc:
        fn(*args, **kwargs)
    assert exc.value.code == code, (exc.value.code, exc.value.detail)
    return exc.value


@pytest.fixture
def root(tmp_path: Path, monkeypatch) -> Path:
    monkeypatch.delenv("GITHUB_ACTIONS", raising=False)
    return tmp_path / "private_root"


# ================================================ A 複数の呼び出しにまたがる継続（PARTIAL → 継続 → COMPLETE）


def test_a_a_universe_larger_than_one_budget_completes_across_three_bounded_invocations(root: Path) -> None:
    codes = [f"9{n:03d}0" for n in range(1, 17)]                                         # 16 発行体 ＝ 1 master ＋ 16 fins
    ids = identity(root, [(f"issuer-{c}", [c]) for c in codes])
    universe, pol = authorities(root, codes)
    tx = transport([master(c) for c in codes], {c: fins(c) for c in codes})
    first = run(root, universe, pol, tx, ACQ[0])
    assert first.run_status["requests_used"] == 8 and len(tx.calls) == 8                 # master ＋ 7 fins
    assert first.result.execution_completeness.value == "PARTIAL"
    counts = first.result.member_outcome_counts
    assert counts["EVALUATED"] == 7 and counts["BUDGET_DEFERRED"] == 9 and sum(counts.values()) == 16
    run_id = first.run_id
    second = run(root, universe, pol, tx, ACQ[1], continue_run_id=run_id)
    assert second.run_id == run_id and second.run_status["requests_used"] == 8           # master は再取得しない
    assert second.result.member_outcome_counts["EVALUATED"] == 15
    assert second.result.execution_completeness.value == "PARTIAL"
    third = run(root, universe, pol, tx, ACQ[2], continue_run_id=run_id)
    assert third.run_status["requests_used"] == 1 and third.run_status["cumulative_requests"] == 17
    assert third.result.execution_completeness.value == "COMPLETE"
    assert len(tx.calls) == 17 and len(set(tx.calls)) == 17                               # 重複の request なし
    assert tx.calls[0] == master_key(D0S) and sum(1 for c in tx.calls if c[0] == "/v2/equities/master") == 1
    result = third.result
    assert [m.member_code for m in result.member_outcomes] == codes                       # 欠落 ・重複なし ・宣言の順
    assert all(m.kind is K.EVALUATED for m in result.member_outcomes)
    assert [r.issuer_id for r in result.issuer_results] == [ids[f"issuer-{c}"] for c in codes]
    assert result.screener_state_counts["MATCH"] == 16 and result.evaluation_as_of == T
    assert all(r.evaluation.evaluation_as_of == T for r in result.issuer_results)        # 宣言の瞬間（request の時刻ではない）
    assert result.policy_id == pol.policy_id and result.universe_id == universe.universe_id
    state = load_ledger(ledger_path(root, run_id), run_id)
    assert [inv["requests_used"] for inv in state.invocations] == [8, 8, 1]
    assert [inv["acquired_at"] for inv in state.invocations] == [a.isoformat() for a in ACQ[:3]]
    assert len(state.attempts) == 16 and all(a["status"] == "AUTHORITY_BUILT" for a in state.attempts.values())
    replay = run(root, universe, pol, tx, ACQ[3], continue_run_id=run_id)                # 終わった run: request なし
    assert replay.run_status["requests_used"] == 0 and len(tx.calls) == 17
    assert replay.result == third.result and replay.result.screen_result_id == third.result.screen_result_id
    assert len(load_ledger(ledger_path(root, run_id), run_id).invocations) == 3           # 仕事が無ければ呼び出しを足さない


def test_a_every_invocation_respects_the_frozen_budget_and_smaller_limits(root: Path) -> None:
    codes = [f"9{n:03d}0" for n in range(1, 6)]
    identity(root, [(f"issuer-{c}", [c]) for c in codes])
    universe, pol = authorities(root, codes)
    tx = transport([master(c) for c in codes], {c: fins(c) for c in codes})
    first = run(root, universe, pol, tx, ACQ[0], budget_limit=2)
    assert first.run_status["requests_used"] == 2 and first.result.member_outcome_counts["BUDGET_DEFERRED"] == 4
    second = run(root, universe, pol, tx, ACQ[1], continue_run_id=first.run_id, budget_limit=3)
    assert second.run_status["requests_used"] == 3 and second.result.member_outcome_counts["EVALUATED"] == 4
    third = run(root, universe, pol, tx, ACQ[2], continue_run_id=first.run_id, budget_limit=3)
    assert third.run_status["requests_used"] == 1 and third.result.execution_completeness.value == "COMPLETE"
    for limit in (0, 9, "8", True):
        fails("BUDGET_INVALID", run, root, universe, pol, tx, ACQ[3], continue_run_id=first.run_id,
              budget_limit=limit)
    assert len(tx.calls) == 6


# ================================================ B 混合の状態（凍結 B5B の状態だけ ・値を NO_MATCH に潰さない）


def test_b_a_mixed_universe_maps_every_execution_outcome_to_the_frozen_member_states(root: Path) -> None:
    A, B, C, D, E, F, G, H, I, J, L = ("90010", "90020", "90030", "90040", "90050", "90060", "90070", "90080",
                                       "90090", "90100", "90110")
    ids = identity(root, [("match", [A]), ("nomatch", [B]), ("absent-op", [C]), ("held-market", [D]),
                          ("http-fail", [G]), ("dual", [H, I]), ("paged", [J]), ("late-match", [L])])
    members = (A, B, C, D, E, F, G, H, I, J, L)
    universe, pol = authorities(root, members)
    tx = transport([master(A), master(B), master(C), master(D, mkt="0109"), master(F), master(G), master(H),
                    master(I), master(J), master(L)],                                   # E は snapshot に無い
                   {A: fins(A), B: fins(B, op="5000000000"), C: fins(C, op=""), G: TransportResponse(500, ""),
                    H: fins(H), J: TransportResponse(200, payload(*fins(J), pagination_key="NEXT")), L: fins(L)})
    first = run(root, universe, pol, tx, ACQ[0], budget_limit=5)                        # master ＋ 4 発行体
    assert first.result.member_outcome_counts["BUDGET_DEFERRED"] == 4                     # dual(H,I) ・paged ・late-match
    assert {m.member_code for m in first.result.member_outcomes if m.kind is K.BUDGET_DEFERRED} == {H, I, J, L}
    final = run(root, universe, pol, tx, ACQ[1], continue_run_id=first.run_id)
    result = final.result
    by_code = {m.member_code: m for m in result.member_outcomes}
    assert by_code[D].kind is K.NOT_ELIGIBLE and "MARKET_HOLD" in by_code[D].reason_codes
    assert by_code[E].kind is K.NOT_ELIGIBLE and by_code[E].reason_codes == ("NOT_IN_MASTER_SNAPSHOT",)
    assert by_code[F].kind is K.IDENTITY_UNRESOLVED and by_code[F].reason_codes == ("IDENTITY_NOT_FOUND",)
    assert by_code[G].kind is K.ACQUISITION_FAILED and by_code[G].reason_codes == ("FINS_HTTP_STATUS_500",)
    assert by_code[J].kind is K.ACQUISITION_FAILED and by_code[J].reason_codes == ("PAGINATION_NOT_FOLLOWED",)
    assert by_code[H].kind is by_code[I].kind is K.EVALUATED                              # 2 code → 1 発行体
    assert by_code[H].issuer_id == by_code[I].issuer_id == ids["dual"]
    assert result.source_members(ids["dual"]) == (H, I)
    states = {r.issuer_id: r.state.value for r in result.issuer_results}
    assert states == {ids["match"]: "MATCH", ids["nomatch"]: "NO_MATCH", ids["absent-op"]: "NOT_EVALUABLE",
                      ids["dual"]: "MATCH", ids["late-match"]: "MATCH"}
    assert result.execution_completeness.value == "COMPLETE"                               # 失敗 ・NOT_EVALUABLE も終端
    assert result.match_issuer_ids == (ids["match"], ids["dual"], ids["late-match"])
    assert sum(1 for c in tx.calls if c == fins_key(H)) == 1 and fins_key(I) not in tx.calls  # 発行体の取得は 1 回
    state = load_ledger(ledger_path(root, first.run_id), first.run_id)
    assert {r["route_code"] for r in state.assessed["routes"]} == {A, B, C, G, H, J, L}  # 経路は最初の code だけ
    safe = final.safe_summary.as_dict()
    assert safe["member_outcome_counts"] == {"EVALUATED": 6, "NOT_ELIGIBLE": 2, "IDENTITY_UNRESOLVED": 1,
                                             "ACQUISITION_FAILED": 2, "BUDGET_DEFERRED": 0, "NOT_ATTEMPTED": 0}
    assert safe["screener_state_counts"]["NOT_EVALUABLE"] == 1 and safe["issuer_count"] == 5
    text = json.dumps(safe)
    for sentinel in (*members, *ids.values(), "p8uni_", "0.0", "Synth", "合成"):
        assert sentinel not in text, sentinel


def test_b_a_master_failure_leaves_every_member_not_attempted_and_is_retried_only_by_an_explicit_continuation(
        root: Path) -> None:
    codes = ["90010", "90020"]
    identity(root, [("one", ["90010"]), ("two", ["90020"])])
    universe, pol = authorities(root, codes)
    broken = SyntheticTransport({master_key(D0S): TransportResponse(503, "")})
    first = run(root, universe, pol, broken, ACQ[0])
    assert first.run_status["master_assessed"] is False and first.run_status["requests_used"] == 1
    assert all(m.kind is K.NOT_ATTEMPTED and m.reason_codes == ("MASTER_NOT_ASSESSED",)
               for m in first.result.member_outcomes)
    assert len(broken.calls) == 1                                                          # 隠れた retry なし
    fixed = transport([master(c) for c in codes], {c: fins(c) for c in codes})
    second = run(root, universe, pol, fixed, ACQ[1], continue_run_id=first.run_id)
    assert second.result.execution_completeness.value == "COMPLETE"
    assert second.run_status["cumulative_requests"] == 4


# ================================================ C 不一致は network の前に fail closed


def test_c_every_continuation_mutation_fails_closed_before_any_provider_request(root: Path) -> None:
    codes = [f"9{n:03d}0" for n in range(1, 11)]
    identity(root, [(f"issuer-{c}", [c]) for c in codes])
    universe, pol = authorities(root, codes)
    tx = transport([master(c) for c in codes], {c: fins(c) for c in codes})
    first = run(root, universe, pol, tx, ACQ[0])
    run_id = first.run_id
    universe2, pol2 = authorities(root, codes, threshold="0.06", version=2)               # 別の版の方針 ・Universe
    other_pol = policy(criterion(metric=MetricKind.OPERATING_MARGIN, operator=CriterionOperator.GE, threshold="0.07",
                                 period_rule=PeriodRule.NEWEST_SUPPORTED_FY_OR_CUMULATIVE), policy_key="other-key")
    PolicyAuthorityStore.open(root).append(PolicyAuthorityRecord(policy=other_pol))
    counter = transport([master(c) for c in codes], {c: fins(c) for c in codes})
    next_day = dict(d0="2026-07-01", evaluation_as_of=T + timedelta(days=1))
    for acquired, overrides in ((ACQ[1], dict(policy_id=other_pol.policy_id)),
                                (ACQ[1], dict(policy_id=pol2.policy_id)),
                                (ACQ[1], dict(universe_id=universe2.universe_id)),
                                (ACQ[1] + timedelta(days=1), next_day),
                                (ACQ[1], dict(evaluation_as_of=T + timedelta(minutes=1)))):
        fails("RUN_SPEC_MISMATCH", run, root, universe, pol, counter, acquired, continue_run_id=run_id, **overrides)
    fails("AUTHORITY_MODE_NOT_SUPPORTED", run, root, universe, pol, counter, ACQ[1], continue_run_id=run_id,
          authority_mode="STRICT_PIT")
    fails("POLICY_AUTHORITY_UNAVAILABLE", run, root, universe, pol, counter, ACQ[1], continue_run_id=run_id,
          policy_id="p8pol_" + "0" * 24)
    fails("UNIVERSE_NOT_FOUND", run, root, universe, pol, counter, ACQ[1], continue_run_id=run_id,
          universe_id="p8uni_" + "0" * 24)
    fails("ACQUISITION_INSTANT_REGRESSED", run, root, universe, pol, counter, ACQ[0] - timedelta(minutes=1),
          continue_run_id=run_id)
    fails("ACQUISITION_AFTER_EVALUATION_INSTANT", run, root, universe, pol, counter, T + timedelta(minutes=1),
          continue_run_id=run_id)
    fails("RUN_ALREADY_STARTED", run, root, universe, pol, counter, ACQ[1])               # 継続は明示
    fails("RUN_SPEC_MISMATCH", run, root, universe, pol, counter, ACQ[1], continue_run_id="p8run_" + "0" * 24)
    assert counter.calls == ()                                                           # 1 つも request していない
    resumed = run(root, universe, pol, tx, ACQ[1], continue_run_id=run_id)
    assert resumed.result.execution_completeness.value == "COMPLETE"


def test_c_cross_day_and_out_of_day_instants_fail_closed_and_d0_is_never_the_wall_clock(root: Path) -> None:
    identity(root, [("one", ["90010"])])
    universe, pol = authorities(root, ["90010"])
    counter = transport([master("90010")], {"90010": fins("90010")})
    fails("ACQUISITION_OUTSIDE_AUTHORITY_DAY", run, root, universe, pol, counter, ACQ[0] + timedelta(days=1))
    fails("EVALUATION_OUTSIDE_AUTHORITY_DAY", run, root, universe, pol, counter, ACQ[0],
          evaluation_as_of=datetime(2026, 7, 1, 0, 0, tzinfo=JST))
    fails("INSTANT_NAIVE_OR_MISSING", run, root, universe, pol, counter, datetime(2026, 6, 30, 20, 0))
    fails("D0_INVALID", run, root, universe, pol, counter, ACQ[0], d0="2026/06/30")
    assert counter.calls == ()
    first = run(root, universe, pol, counter, ACQ[0], budget_limit=1)                    # master だけ
    fails("RUN_SPEC_MISMATCH", run, root, universe, pol, counter, ACQ[0] + timedelta(days=1),
          continue_run_id=first.run_id, d0="2026-07-01", evaluation_as_of=T + timedelta(days=1))
    assert len(counter.calls) == 1
    source = executable_source(RUNNER)
    for token in ("now(", "today(", "utcnow", "time.time", "date.today"):
        assert token not in source, token


def test_c_unresolvable_or_corrupt_authorities_fail_closed_before_network(root: Path) -> None:
    identity(root, [("one", ["90010"])])
    counter = transport([master("90010")], {"90010": fins("90010")})
    fails("UNIVERSE_AUTHORITY_UNAVAILABLE", execute_screen, data_root=root, transport=counter, d0=D0S,
          evaluation_as_of=T, authority_mode=RETRO.value, acquired_at=ACQ[0], universe_id="p8uni_" + "0" * 24,
          policy_id="p8pol_" + "0" * 24)
    universe, pol = authorities(root, ["90010"])
    journal = root / "screener_intelligence" / "screener_policy_authority.jsonl"
    original = journal.read_bytes()
    journal.write_bytes(original + b"not json\n")
    fails("POLICY_AUTHORITY_UNAVAILABLE", run, root, universe, pol, counter, ACQ[0])
    journal.write_bytes(original)
    for selector in (dict(universe_id=universe.universe_id, universe_key="synthetic-screen", universe_version=1),
                     dict(universe_id=None)):
        fails("UNIVERSE_SELECTOR_INVALID", run, root, universe, pol, counter, ACQ[0], **selector)
    fails("POLICY_SELECTOR_INVALID", run, root, universe, pol, counter, ACQ[0], policy_id=None)
    assert counter.calls == ()
    by_key = run(root, universe, pol, counter, ACQ[0], universe_id=None, universe_key="synthetic-screen",
                 universe_version=1, policy_id=None, policy_key=pol.policy_key, policy_version=1)
    assert by_key.result.execution_completeness.value == "COMPLETE"                     # 正確な (鍵, 版) でも同じ run


# ================================================ D 台帳の破損（修復 ・切り詰め ・上書きしない）


def _ledger_run(root: Path):
    codes = ["90010", "90020", "90030"]
    identity(root, [(f"issuer-{c}", [c]) for c in codes])
    universe, pol = authorities(root, codes)
    tx = transport([master(c) for c in codes], {c: fins(c) for c in codes})
    first = run(root, universe, pol, tx, ACQ[0], budget_limit=2)
    return universe, pol, first.run_id, ledger_path(root, first.run_id)


def _rewrite(event: dict) -> bytes:
    event = dict(event)
    event["digest"] = sl._event_digest(event)
    return (sl.canonical_json(event) + "\n").encode()


def test_d_ledger_corruption_fails_closed_without_repair(root: Path) -> None:
    universe, pol, run_id, path = _ledger_run(root)
    original = path.read_bytes()
    lines = original.decode().splitlines()
    events = [json.loads(line) for line in lines]
    counter = transport([], {})
    tampered_digest = json.loads(lines[2])
    tampered_digest["payload"]["routes"] = []                                              # digest を直さない
    started_twice = dict(events[1])
    started_twice.update(seq=len(events) + 1, prev_digest=events[-1]["digest"])
    attempted_again = dict(events[3])                                                      # 同じ発行体の 2 回目
    attempted_again.update(seq=len(events) + 1, prev_digest=events[-1]["digest"])
    orphan = dict(events[3])
    orphan.update(seq=2, prev_digest=events[0]["digest"])                                  # 呼び出し ・判定の前
    cases = [(original + b"not json\n", "LEDGER_INVALID_RECORD"),
             (original + b'{"event": "RUN_STARTED"', "LEDGER_TRUNCATED_FINAL_LINE"),
             (("\n".join(lines[:2] + [json.dumps(tampered_digest, sort_keys=True, separators=(",", ":"),
                                                  ensure_ascii=False)] + lines[3:]) + "\n").encode(),
              "LEDGER_DIGEST_MISMATCH"),
             (original + _rewrite(started_twice), "LEDGER_IMPOSSIBLE_TRANSITION"),
             (original + _rewrite(attempted_again), "LEDGER_MISSING_PRIOR_EVENT"),
             ((lines[0] + "\n").encode() + _rewrite(orphan), "LEDGER_MISSING_PRIOR_EVENT"),
             ((lines[0] + "\n" + lines[2] + "\n").encode(), "LEDGER_CHAIN_BROKEN"),
             (original.replace(b'"seq":2', b'"seq":7', 1), "LEDGER_DIGEST_MISMATCH"),
             ((json.dumps(events[0]) + "\n").encode(), "LEDGER_NON_CANONICAL_LINE")]
    for content, code in cases:
        path.write_bytes(content)
        fails(code, run, root, universe, pol, counter, ACQ[1], continue_run_id=run_id)
        assert path.read_bytes() == content, code                                         # 修復しない
    assert counter.calls == ()
    open_invocation = original + _rewrite({**events[1], "seq": len(events) + 1, "prev_digest": events[-1]["digest"],
                                           "payload": {**events[1]["payload"], "invocation": 2,
                                                       "acquired_at": ACQ[1].isoformat()}})
    path.write_bytes(open_invocation)
    fails("LEDGER_OPEN_INVOCATION", run, root, universe, pol, counter, ACQ[2], continue_run_id=run_id)
    path.write_bytes(original)
    assert run(root, universe, pol, transport([], {c: fins(c) for c in ("90010", "90020", "90030")}), ACQ[1],
               continue_run_id=run_id).result.execution_completeness.value == "COMPLETE"


# ================================================ E 境界（別の runner ・凍結の部品だけ ・保存 ・順位なし）


def test_e_the_executor_is_a_separate_private_runner_that_composes_frozen_layers_only() -> None:
    tree = ast.parse(RUNNER.read_text(encoding="utf-8"))
    imported = {"." * n.level + (n.module or "") for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)}
    assert ".jquants_pilot2_local" not in imported                                        # B4B の runner は使わない
    assert ".screener_intelligence.screener_evaluator" in imported                        # EvaluationInputs だけ
    names = {a.name for n in ast.walk(tree) if isinstance(n, ast.ImportFrom) for a in n.names}
    assert not any(n.startswith("_") for n in names - {"__future__"})
    assert "evaluate_policy" not in names and "evaluate_selected_policy" in names
    assert not names & {"execute_identity_registration", "propose_bootstrap", "review_manifest",
                        "PolicyAuthorityStore", "UniverseAuthorityStore.initialize"}
    source = executable_source(RUNNER)
    lowered = source.lower()
    for token in ("now(", "today(", "utcnow", "random", "sleep", "retry", "pagination_key=fins", "rank", "score",
                  "recommend", "watchlist", "portfolio", "theme", "narrative", "docs/pages", "morning", "llm", "prompt",
                  "screen_results", "result_store", "latest", "default_policy", "default_universe", "unlink",
                  "rmtree", ".truncate(", "write_text", "write_bytes"):
        assert token not in lowered, token
    assert source.count("fetch_fins_summary(handoff)") == 1 and source.count("fetch_master(") == 1
    assert "RequestBudget(budget_limit)" in source and "budget.remaining == 0" in source
    assert sl.SUPPORTED_AUTHORITY_MODES == (ScreenerAuthorityMode.RETROSPECTIVE_PROVIDER_AUTHORITY,)
    assert sl.WORK_ORDER_RULE.endswith("NON_SEMANTIC") and "ACQUISITION_ROUTING_ONLY" in sl.ROUTING_RULE
    for line in RUNNER.read_text(encoding="utf-8").splitlines():
        assert len(line) <= 120, line
