"""P8-PILOT2B — PILOT2 runner の取得の authority の配線（ACQ0 → EXE → manifest → F1 → A3-RA → 安全な要約）の test。

合成 transport ・合成 identity ・tmp_path の private root だけ。実 network ・実 credential ・実 payload は使わない。凍結の層は変えない。
PILOT2A の経路（`acquired_at` なし）は `test_screener_pilot2_local_runner.py` が不変のまま pin する。
"""
from __future__ import annotations

import json
from dataclasses import replace
from datetime import datetime
from pathlib import Path

import pytest

from src.intelligence import jquants_pilot2_local as pl
from src.intelligence.jquants_pilot2_local import PilotError, execute, prepare
from src.intelligence.screener_intelligence import identity_store as ist
from src.intelligence.screener_intelligence import observation_store as ost
from src.intelligence.screener_intelligence.acquisition_event_store import AcquisitionEventStore
from src.intelligence.screener_intelligence.acquisition_manifest_store import ManifestStore
from src.intelligence.screener_intelligence.jquants_live_model import SyntheticTransport, TransportResponse
from src.intelligence.screener_intelligence.provider_holdings_store import ProviderHoldingsStore
from tests.intelligence.test_screener_jquants_adapter import row as fins_row
from tests.intelligence.test_screener_jquants_live import master
from tests.intelligence.test_screener_pilot2_local_runner import (D0, FINS, FORBIDDEN_IN_SUMMARY, MASTER, decide,
                                                                  fins_key, fins_rows, journal_lines, master_key,
                                                                  payload, pilot_dir, read, standard_transport)
from tests.intelligence.test_screener_pilot2_local_runner import root  # noqa: F401  fixture
from tests.intelligence.test_screener_pilot2_local_runner import transport as make_transport

ACQ = "2026-06-30T20:00:00+09:00"                                                # D0 の当日 ・審査（19:05）の後の取得
ACQ2 = "2026-06-30T21:00:00+09:00"                                               # 同じ日の再取得
ACQ_NEXT_DAY = "2026-07-01T18:30:00+09:00"                                       # D0 の翌日（identity の coverage の外）
METRICS = ("REVENUE_GROWTH", "OPERATING_MARGIN", "NET_MARGIN", "ROA_POINT_IN_TIME")
ISSUER_KEYS = {"acquisition", "manifest", "f1", "holdings_epoch_count", "retrospective_metrics", "failure_code"}
METRIC_KEYS = {"metric", "target_available", "outer_status", "has_value", "resolution_mode", "diagnostic_codes",
               "observation_id_count", "epoch_ref_count"}
AUTHORITY_KEYS = {"schema", "state", "acquired_at", "issuers"}
FORBIDDEN_AUTHORITY = FORBIDDEN_IN_SUMMARY + ("jq.acq:", "jq.man:", "jq.pvh:", "p8pvh_", "p8man_", "p8acq_", "0.08",
                                              "0.06", "0.033333")


def q1_row(code: str, **overrides) -> dict:
    """FY2025 の 1Q 累計（period_end 2025-06-30。FY2024 の末日より新しい）。"""
    return fins_row(Code=code, DiscNo="20250808000001", DiscDate="2025-08-08", CurPerType="1Q", CurPerSt="2025-04-01",
                    CurPerEn="2025-06-30", CurFYSt="2025-04-01", CurFYEn="2026-03-31",
                    DocType="1QFinancialStatements_Consolidated_JP", Sales="130000000000", OP="9100000000",
                    NP="6000000000", TA="950000000000", **overrides)


def fins_transport(*rows, pagination: str = "") -> SyntheticTransport:
    extra = {"pagination_key": pagination} if pagination else {}
    return make_transport({master_key(): payload(master("13010")), fins_key("13010"): payload(*rows, **extra)})


def prepared(root: Path) -> None:
    prepare(d0=D0, codes=["13010"], data_root=root, transport=standard_transport())
    decide(root)


def run(root: Path, transport=None, acquired_at: str = ACQ) -> dict:
    return execute(data_root=root, transport=transport or standard_transport(), acquired_at=acquired_at)


def issuer(summary: dict, index: int = 0) -> dict:
    return summary["acquisition_authority"]["issuers"][index]


def metric(summary: dict, name: str, index: int = 0) -> dict:
    return next(m for m in issuer(summary, index)["retrospective_metrics"] if m["metric"] == name)


def holdings(root: Path) -> ProviderHoldingsStore:
    return ProviderHoldingsStore.open(root, read_only=True)


# ================================================================ A acquired_at（D-P2B-1）


def test_a_execute_without_acquired_at_keeps_the_pilot2a_path_and_builds_no_acquisition_authority(root: Path) -> None:
    prepared(root)
    summary = execute(data_root=root, transport=standard_transport())
    assert summary["state"] == "PILOT_PASS" and summary["acquisition_authority"] == {
        "schema": pl.AUTHORITY_SCHEMA, "state": "NOT_REQUESTED", "acquired_at": None, "issuers": []}
    assert set(summary["store_integrity"]) == {"identity", "observation", "semantic_metadata", "held"}
    assert {p.name for p in (root / "screener_intelligence").iterdir()} == {
        "identity_records.jsonl", "observation_records.jsonl", "semantic_metadata.jsonl", "held_observations.jsonl"}
    assert not (pilot_dir(root) / "acquisition_state.json").exists()


@pytest.mark.parametrize("value,code", [("2026-06-30T20:00:00", "ACQUIRED_AT_NAIVE"),
                                        ("not a time", "ACQUIRED_AT_INVALID"), ("", "ACQUIRED_AT_MISSING"),
                                        ("2026-06-30T19:04:59+09:00", "ACQUIRED_AT_BEFORE_ACCEPTED_AT")])
def test_a_malformed_naive_or_too_early_acquired_at_fails_before_any_request(root: Path, value: str, code: str) -> None:
    prepared(root)
    fake = standard_transport()
    with pytest.raises(PilotError) as exc:
        run(root, fake, acquired_at=value)
    assert exc.value.code == code and not fake.calls
    assert read(root, "budget_state.json")["used"] == 1 and journal_lines(root, "acquisition_events.jsonl") == -1


def test_a_the_cli_requires_a_parsable_aware_acquired_at_before_touching_the_transport(root: Path, monkeypatch,
                                                                                       capsys) -> None:
    prepared(root)
    fake = standard_transport()
    monkeypatch.setattr(pl, "LocalHttpsTransport", lambda credential_env: fake)
    monkeypatch.setenv("JQUANTS_API_KEY", "synthetic-key-not-real")
    assert pl.main(["execute", "--data-root", str(root), "--acquired-at", "2026-06-30T20:00:00"]) == 2
    assert '"code": "ACQUIRED_AT_NAIVE"' in capsys.readouterr().out and not fake.calls
    assert pl.main(["execute", "--data-root", str(root), "--acquired-at", ACQ]) == 0
    out = capsys.readouterr().out
    assert '"state": "PILOT_PASS"' in out and '"acquired_at": "2026-06-30T20:00:00+09:00"' in out
    for forbidden in FORBIDDEN_AUTHORITY:
        assert forbidden not in out, forbidden


# ================================================================ B chain（COMPLETE の取得 → EXE → manifest → F1 → A3-RA）


def test_b_complete_acquisition_runs_the_whole_chain_and_reads_out_four_metrics(root: Path) -> None:
    prepared(root)
    summary = run(root)
    assert summary["state"] == "PILOT_PASS" and summary["acquisition_authority"]["state"] == "REQUESTED"
    assert summary["acquisition_authority"]["acquired_at"] == ACQ
    entry = issuer(summary)
    assert set(entry) == ISSUER_KEYS and set(summary["acquisition_authority"]) == AUTHORITY_KEYS
    assert entry["acquisition"] == {"status": "COMPLETE", "reused": False, "row_count": 2}
    assert entry["manifest"] == {"status": "APPENDED"} and entry["failure_code"] == ""
    assert entry["f1"] == {"status": "APPENDED", "appended_count": 2, "reused_count": 0}
    assert entry["holdings_epoch_count"] == 2
    assert [m["metric"] for m in entry["retrospective_metrics"]] == list(METRICS)
    for m in entry["retrospective_metrics"]:
        assert set(m) == METRIC_KEYS and m["outer_status"] == "VALUE" and m["has_value"] is True
        assert m["resolution_mode"] == "RETROSPECTIVE_PROVIDER_AUTHORITY" and m["diagnostic_codes"] == []
        assert m["target_available"] is True and m["observation_id_count"] == 2
    assert metric(summary, "REVENUE_GROWTH")["epoch_ref_count"] == 2                            # 2 つの期間 ＝ 2 つの epoch
    assert metric(summary, "OPERATING_MARGIN")["epoch_ref_count"] == 1
    assert summary["exe_outcomes"] == {"APPENDED": 2} and summary["request"]["used"] == 2
    assert set(summary["store_integrity"]) == {"identity", "observation", "semantic_metadata", "held",
                                               "acquisition_events", "manifests", "provider_holdings"}
    assert summary["metrics"][0]["OPERATING_MARGIN"]["status"] == "INSUFFICIENT_DATA"   # STRICT は不変（coverage なし）
    assert ost.ObservationStore.open(root, read_only=True).history.coverages == []
    assert journal_lines(root, "acquisition_events.jsonl") == 1
    assert journal_lines(root, "acquisition_manifests.jsonl") == 1
    assert journal_lines(root, "provider_holdings_coverage.jsonl") == 2
    text = json.dumps(summary, ensure_ascii=False)
    for forbidden in FORBIDDEN_AUTHORITY:
        assert forbidden not in text, forbidden
    assert (pilot_dir(root) / "safe_summary.json").read_text(encoding="utf-8") == json.dumps(
        summary, ensure_ascii=False, sort_keys=True, indent=2) + "\n"
    state = read(root, "acquisition_state.json")
    assert state["schema"] == pl.ACQUISITION_STATE_SCHEMA and len(state["bindings"]) == 1
    binding = next(iter(state["bindings"].values()))
    assert binding["acquired_at"] == ACQ and binding["completed"] is True and len(binding["content_digest"]) == 64
    assert "13010" not in json.dumps(state)


def test_b_authority_as_of_and_identity_valid_at_are_the_acquisition_instant(root: Path, monkeypatch) -> None:
    prepared(root)
    seen = []
    original = pl.resolve_retrospective_metric

    def spy(metric, history, **kwargs):
        seen.append((kwargs["authority_as_of"], kwargs["identity_valid_at"]))
        return original(metric, history, **kwargs)
    monkeypatch.setattr(pl, "resolve_retrospective_metric", spy)
    run(root)
    instant = datetime.fromisoformat(ACQ)
    assert seen and all(pair == (instant, instant) for pair in seen)
    event = AcquisitionEventStore.open(root, read_only=True).records()[0]
    assert event.acquired_at == instant and event.status.value == "COMPLETE" and event.row_count == 2
    assert event.scope.endpoint == FINS and tuple(k for k, _ in event.scope.params) == ("code",)
    for record in holdings(root).records():
        assert record.holdings_as_of == instant and record.acquisition_ref == event.reference


def test_b_exe_receives_acquired_at_but_frozen_exe_r_decides_the_knowledge_rule(root: Path) -> None:
    prepared(root)
    run(root)
    history = ost.ObservationStore.open(root, read_only=True).history
    first_seen = [r for r in history.records if r.KIND.value == "FUNDAMENTAL_ACTUAL"]
    assert first_seen and all(r.knowledge.at.date().isoformat() in ("2024-05-12", "2025-05-12") for r in first_seen)
    revised = [fins_row(**{**r, "Sales": str(int(r["Sales"]) + 7)}) for r in fins_rows("13010")]     # 同じ DiscNo ・内容が違う
    summary = run(root, fins_transport(*revised), acquired_at=ACQ2)
    assert summary["exe_outcomes"] == {"APPENDED": 2} and summary["state"] == "PILOT_PASS"
    history = ost.ObservationStore.open(root, read_only=True).history
    revisions = [r for r in history.records if r.KIND.value == "FUNDAMENTAL_ACTUAL" and r.supersedes]
    assert revisions and all(r.knowledge.at == datetime.fromisoformat(ACQ2) for r in revisions)   # 修正の知識 ＝ 取得の瞬間
    assert issuer(summary)["holdings_epoch_count"] == 4 and metric(summary, "NET_MARGIN")["has_value"] is True


def test_b_exact_replay_reuses_event_manifest_holdings_and_observations(root: Path) -> None:
    prepared(root)
    first = run(root)
    before = {name: journal_lines(root, name) for name in ("acquisition_events.jsonl", "acquisition_manifests.jsonl",
                                                             "provider_holdings_coverage.jsonl",
                                                             "observation_records.jsonl", "identity_records.jsonl")}
    again = run(root)
    entry = issuer(again)
    assert again["state"] == "PILOT_PASS" and entry["acquisition"] == {"status": "COMPLETE", "reused": True,
                                                                        "row_count": 2}
    assert entry["manifest"] == {"status": "REUSED"} and entry["f1"] == {"status": "REUSED", "appended_count": 0,
                                                                          "reused_count": 2}
    assert again["exe_outcomes"] == {"REUSED": 2} and again["id2"]["outcome"] == "REUSED"
    assert {name: journal_lines(root, name) for name in before} == before
    assert entry["retrospective_metrics"] == issuer(first)["retrospective_metrics"]
    assert again["request"]["used"] == 3                                                        # fins は再取得（予算は続く）


def test_b_reacquisition_with_a_new_acquired_at_appends_a_new_epoch_and_keeps_values_and_observations(
        root: Path) -> None:
    prepared(root)
    run(root)
    later = run(root, acquired_at=ACQ2)
    entry = issuer(later)
    assert later["state"] == "PILOT_PASS" and entry["acquisition"]["reused"] is False
    assert entry["manifest"] == {"status": "APPENDED"} and entry["f1"]["appended_count"] == 2
    assert entry["holdings_epoch_count"] == 4 and later["exe_outcomes"] == {"REUSED": 2}
    assert all(m["has_value"] for m in entry["retrospective_metrics"])
    assert journal_lines(root, "acquisition_events.jsonl") == 2
    assert journal_lines(root, "observation_records.jsonl") == 8
    epochs = holdings(root).records()
    assert {r.holdings_as_of for r in epochs} == {datetime.fromisoformat(ACQ), datetime.fromisoformat(ACQ2)}
    assert len({r.acquisition_ref for r in epochs}) == 2
    assert len(read(root, "acquisition_state.json")["bindings"]) == 1                            # 同じ範囲 ・新しい結び付き


def test_b_resume_binding_refuses_a_different_acquired_at_for_an_incomplete_identical_acquisition(root: Path) -> None:
    prepared(root)
    run(root)
    state = read(root, "acquisition_state.json")
    key = next(iter(state["bindings"]))
    state["bindings"][key]["completed"] = False                                                   # 途中で止まった取得を再現
    (pilot_dir(root) / "acquisition_state.json").write_text(json.dumps(state), encoding="utf-8")
    mismatch = run(root, acquired_at=ACQ2)
    assert mismatch["state"] == "PILOT_FAILED" and issuer(mismatch)["failure_code"] == "ACQUIRED_AT_RESUME_MISMATCH"
    assert issuer(mismatch)["acquisition"]["status"] == "RESUME_MISMATCH"
    assert issuer(mismatch)["f1"]["status"] == "NOT_ATTEMPTED"
    assert journal_lines(root, "acquisition_events.jsonl") == 1                                  # 新しい epoch は作らない
    resumed = run(root, acquired_at=ACQ)                                                         # 同じ acquired_at なら再開
    assert resumed["state"] == "PILOT_PASS" and issuer(resumed)["acquisition"]["reused"] is True
    assert read(root, "acquisition_state.json")["bindings"][key]["completed"] is True


# ================================================================ C target の選択（D-P2B-4 ・5）


def test_c_margins_take_the_newest_supported_period_roa_takes_the_fy_and_growth_needs_a_comparable_prior(
        root: Path) -> None:
    prepared(root)
    summary = run(root, fins_transport(*fins_rows("13010"), q1_row("13010")))
    assert summary["state"] == "PILOT_PASS" and issuer(summary)["holdings_epoch_count"] == 3
    history = ost.ObservationStore.open(root, read_only=True).history
    manifest = ManifestStore.open(root, read_only=True).records()[0]
    ends = {history.get(e.observation_ids[0]).period.period_end.isoformat() for e in manifest.entries}
    assert ends == {"2024-03-31", "2025-03-31", "2025-06-30"}
    for name in METRICS:
        assert metric(summary, name)["outer_status"] == "VALUE", name
    with_quarter = run(root, fins_transport(*fins_rows("13010"), q1_row("13010")), acquired_at=ACQ2)
    seen = {}
    original = pl.resolve_retrospective_metric

    def spy(kind, history, **kwargs):
        seen.setdefault(kind.value, []).append((kwargs["target_period"].period_end.isoformat(),
                                               kwargs.get("comparison_period").period_end.isoformat()
                                               if kwargs.get("comparison_period") else None))
        return original(kind, history, **kwargs)
    pl.resolve_retrospective_metric = spy
    try:
        run(root, fins_transport(*fins_rows("13010"), q1_row("13010")), acquired_at=ACQ2)
    finally:
        pl.resolve_retrospective_metric = original
    assert seen["OPERATING_MARGIN"] == [("2025-06-30", None)] and seen["NET_MARGIN"] == [("2025-06-30", None)]
    assert seen["ROA_POINT_IN_TIME"] == [("2025-03-31", None)]                                    # 年度だけ
    assert seen["REVENUE_GROWTH"][0] == ("2025-06-30", "2025-03-31")                    # 1Q と年度は comparable でない
    assert seen["REVENUE_GROWTH"][-1] == ("2025-03-31", "2024-03-31")                             # 最初の comparable な対
    assert with_quarter["state"] == "PILOT_PASS"


def test_c_missing_prior_makes_revenue_growth_unavailable_not_a_pilot_failure(root: Path) -> None:
    prepared(root)
    summary = run(root, fins_transport(*fins_rows("13010", years=(2025,))))
    assert summary["state"] == "PILOT_PASS"
    growth = metric(summary, "REVENUE_GROWTH")
    assert growth == {"metric": "REVENUE_GROWTH", "target_available": False, "outer_status": "UNAVAILABLE",
                      "has_value": False, "resolution_mode": "RETROSPECTIVE_PROVIDER_AUTHORITY",
                      "diagnostic_codes": ["NO_COMPARABLE_PRIOR_PERIOD"], "observation_id_count": 0,
                      "epoch_ref_count": 0}
    assert metric(summary, "ROA_POINT_IN_TIME")["outer_status"] == "VALUE"


def test_c_target_ambiguity_is_unavailable_never_an_arbitrary_choice(root: Path, monkeypatch) -> None:
    prepared(root)
    original = pl._target_candidates

    def ambiguous(root_, issuer_id, authority):
        candidates = original(root_, issuer_id, authority)
        newest = max(candidates)
        period = next(iter(candidates[newest]))
        start = period.fiscal_year_start.replace(month=1, day=1)                                # 15 か月の年度（別の意味）
        other = replace(period, fiscal_year_start=start, period_start=start)
        candidates[newest] = {period, other}                                                     # 同じ末日 ・意味の違う期間
        return candidates
    monkeypatch.setattr(pl, "_target_candidates", ambiguous)
    summary = run(root)
    assert summary["state"] == "PILOT_PASS"
    for name in METRICS:
        assert metric(summary, name)["outer_status"] == "UNAVAILABLE", name
        assert metric(summary, name)["diagnostic_codes"] == ["TARGET_AMBIGUOUS"], name
    assert pl._select_target({}, pl.SUPPORTED_TARGET_BASES) == (None, "NO_SUPPORTED_TARGET")


# ================================================================ D 真の非値 ・保留 ・0 epoch ・pagination


def test_d_value_absent_is_reported_without_a_value_and_the_pilot_passes(root: Path) -> None:
    prepared(root)
    rows = [fins_row(**{**r, "OP": ""}) for r in fins_rows("13010")]
    summary = run(root, fins_transport(*rows))
    assert summary["state"] == "PILOT_PASS"
    om = metric(summary, "OPERATING_MARGIN")
    assert om["outer_status"] == "INSUFFICIENT_DATA" and om["has_value"] is False and om["target_available"] is True
    assert "OPERATING_INCOME:VALUE_ABSENT" in om["diagnostic_codes"]
    assert any(c.startswith("OPERATING_INCOME:VALUE_ABSENT:") for c in om["diagnostic_codes"])
    assert metric(summary, "NET_MARGIN")["outer_status"] == "VALUE"


def test_d_semantic_hold_is_reported_as_a_typed_hold_and_the_pilot_passes(root: Path) -> None:
    prepared(root)
    foreign = fins_row(**{**fins_rows("13010")[1], "DiscNo": "20250512000009",
                          "DocType": "FYFinancialStatements_Consolidated_Foreign"})           # 同じ年度の保留（P 既知）
    thin = fins_row(**{**fins_rows("13010")[1], "OP": ""})                                       # 営業利益は記載なし
    summary = run(root, fins_transport(fins_rows("13010")[0], thin, foreign))
    assert summary["state"] == "PILOT_PASS" and summary["held_reasons"] != {}
    om = metric(summary, "OPERATING_MARGIN")
    assert om["outer_status"] == "SEMANTIC_HOLD" and om["has_value"] is False
    assert "OPERATING_INCOME:SEMANTIC_HOLD:HELD_ROW_AT_PERIOD" in om["diagnostic_codes"]
    assert metric(summary, "NET_MARGIN")["outer_status"] == "VALUE"                               # member は値


def test_d_f1_zero_epoch_cases_do_not_fabricate_authority(root: Path) -> None:
    prepared(root)
    unknown = fins_row(**{**fins_rows("13010")[1], "CurPerType": "4Q"})                          # 期間が不明な保留
    held = run(root, fins_transport(fins_rows("13010")[0], unknown))
    entry = issuer(held)
    assert held["state"] == "PILOT_HOLD" and entry["f1"]["status"] == "UNKNOWN_PERIOD_HELD_ROW"
    assert entry["holdings_epoch_count"] == 0 and entry["manifest"] == {"status": "APPENDED"}
    assert all(m["outer_status"] == "UNAVAILABLE" and m["diagnostic_codes"] == ["UNKNOWN_PERIOD_HELD_ROW"]
               for m in entry["retrospective_metrics"])
    broken = [fins_row(**{**r, "Sales": "1,000"}) for r in fins_rows("13010")]
    partial = run(root, fins_transport(*broken), acquired_at=ACQ2)
    entry = issuer(partial)
    assert partial["state"] == "PILOT_PARTIAL" and entry["f1"]["status"] == "NO_CANONICAL_PERIODS"
    assert all(m["diagnostic_codes"] == ["NO_CANONICAL_PERIODS"] for m in entry["retrospective_metrics"])
    assert journal_lines(root, "provider_holdings_coverage.jsonl") == 0


def test_d_pagination_is_recorded_as_partial_never_followed_and_builds_no_authority(root: Path) -> None:
    prepared(root)
    fake = fins_transport(*fins_rows("13010"), pagination="abc123")
    summary = run(root, fake)
    entry = issuer(summary)
    assert summary["state"] == "PILOT_PARTIAL" and entry["acquisition"] == {"status": "PARTIAL_PAGINATED",
                                                                             "reused": False, "row_count": 2}
    assert entry["manifest"] == {"status": "NOT_ATTEMPTED"} and entry["f1"]["status"] == "NOT_ATTEMPTED"
    assert entry["retrospective_metrics"] == [] and entry["failure_code"] == ""
    assert [c[0] for c in fake.calls] == [FINS] and summary["request"]["used"] == 2                # page は追わない
    assert summary["exe_outcomes"] == {} and journal_lines(root, "observation_records.jsonl") == 0
    assert journal_lines(root, "acquisition_events.jsonl") == 1
    assert journal_lines(root, "provider_holdings_coverage.jsonl") == 0
    assert summary["fins"]["pagination_seen"] == 1


def test_d_provider_fix_across_acquisitions_composes_through_exe_manifest_f1_and_a3_ra(root: Path) -> None:
    prepared(root)
    good, broken = fins_rows("13010")[0], fins_row(**{**fins_rows("13010")[1], "Sales": "1,000"})
    first = run(root, fins_transport(good, broken))
    assert first["state"] == "PILOT_PASS" and issuer(first)["holdings_epoch_count"] == 1          # FY2023 だけ
    assert metric(first, "REVENUE_GROWTH")["outer_status"] == "UNAVAILABLE"
    assert metric(first, "OPERATING_MARGIN")["outer_status"] == "VALUE"
    fixed = run(root, fins_transport(*fins_rows("13010")), acquired_at=ACQ2)
    assert fixed["state"] == "PILOT_PASS" and issuer(fixed)["holdings_epoch_count"] == 3
    assert metric(fixed, "REVENUE_GROWTH")["outer_status"] == "VALUE"
    assert metric(fixed, "REVENUE_GROWTH")["epoch_ref_count"] == 2
    assert journal_lines(root, "held_observations.jsonl") == 1                                   # 保留は残る（消さない）


# ================================================================ E 状態 ・resume ・STRICT の孤立 ・privacy


def test_e_pilot_failed_on_store_corruption_and_on_authority_failure(root: Path) -> None:
    prepared(root)
    run(root)
    path = root / "screener_intelligence" / "acquisition_manifests.jsonl"
    original = path.read_bytes()
    path.write_bytes(original + b"{not json\n")
    corrupt = run(root, acquired_at=ACQ2)
    assert corrupt["state"] == "PILOT_FAILED" and corrupt["store_integrity"]["manifests"].startswith("CORRUPT_")
    assert corrupt["acquisition_authority"]["issuers"] == [] and corrupt["id2"]["outcome"] == "NOT_ATTEMPTED"
    assert path.read_bytes() == original + b"{not json\n"                                        # 修復しない


def test_e_resume_from_an_existing_pilot2a_root_adds_the_authority_without_rewriting_anything(root: Path) -> None:
    prepared(root)
    legacy = execute(data_root=root, transport=standard_transport())
    before = {name: (root / "screener_intelligence" / name).read_bytes()
              for name in ("identity_records.jsonl", "observation_records.jsonl", "semantic_metadata.jsonl",
                           "held_observations.jsonl")}
    summary = run(root)
    assert legacy["state"] == summary["state"] == "PILOT_PASS" and summary["id2"]["outcome"] == "REUSED"
    assert summary["exe_outcomes"] == {"REUSED": 2} and issuer(summary)["acquisition"]["reused"] is False
    assert issuer(summary)["f1"]["status"] == "APPENDED"
    assert all(m["has_value"] for m in issuer(summary)["retrospective_metrics"])
    assert {name: (root / "screener_intelligence" / name).read_bytes() for name in before} == before
    assert summary["metrics"] == legacy["metrics"]                                               # STRICT の答えは不変


def test_e_safe_summary_has_pinned_keys_and_no_names_codes_values_rows_or_references(root: Path) -> None:
    prepared(root)
    summary = run(root, fins_transport(*fins_rows("13010"), q1_row("13010")))
    text = json.dumps(summary, ensure_ascii=False)
    for forbidden in FORBIDDEN_AUTHORITY + ("130000000000", "9100000000", "DiscNo", "CurPerEn"):
        assert forbidden not in text, forbidden
    assert set(summary["acquisition_authority"]) == AUTHORITY_KEYS and set(issuer(summary)) == ISSUER_KEYS
    assert all(set(m) == METRIC_KEYS for m in issuer(summary)["retrospective_metrics"])
    assert set(issuer(summary)["acquisition"]) == {"status", "reused", "row_count"}
    assert set(issuer(summary)["f1"]) == {"status", "appended_count", "reused_count"}
    assert all(isinstance(m["has_value"], bool) for m in issuer(summary)["retrospective_metrics"])
    assert "value" not in {k for m in issuer(summary)["retrospective_metrics"] for k in m}
    assert {p.name for p in root.iterdir()} == {"pilot2", "screener_intelligence"}
    assert {p.name for p in pilot_dir(root).iterdir()} == {"review_packet.json", "decision_template.json",
                                                           "decision.json", "budget_state.json", "safe_summary.json",
                                                           "acquisition_state.json"}


def test_e_statuses_are_the_locked_vocabulary_and_strict_metrics_stay_typed(root: Path) -> None:
    prepared(root)
    summary = run(root)
    assert summary["state"] in ("PILOT_PASS", "PILOT_HOLD", "PILOT_PARTIAL", "PILOT_FAILED")
    for name in METRICS:
        assert summary["metrics"][0][name]["status"] == "INSUFFICIENT_DATA"                       # STRICT: coverage なし
    later = run(root, acquired_at=ACQ_NEXT_DAY)                                        # identity の coverage の外
    assert later["state"] == "PILOT_PASS"                                                        # infrastructure は通る
    for m in issuer(later)["retrospective_metrics"]:
        assert m["outer_status"] == "INSUFFICIENT_DATA" and m["has_value"] is False
        assert any("SUBJECT_NOT_RESOLVED" in c for c in m["diagnostic_codes"])
    assert ist.IdentityStore.open(root, read_only=True).history.issuers
