"""P8-PILOT2A — 2 段の local runner の test（合成 transport ・合成 identity ・tmp_path の private root だけ）。

実 network ・実 credential ・実 payload は使わない。凍結の層は変えない。
"""
from __future__ import annotations

import ast
import json
from datetime import date
from pathlib import Path

import pytest

from src.intelligence import jquants_pilot2_local as pl
from src.intelligence.jquants_pilot2_local import PilotError, execute, prepare, validate_data_root
from src.intelligence.screener_intelligence import identity_store as ist
from src.intelligence.screener_intelligence import observation_store as ost
from src.intelligence.screener_intelligence.jquants_live_model import (LiveInputError, SyntheticTransport,
                                                                       TransportResponse)
from tests.intelligence.test_prediction_record import executable_source
from tests.intelligence.test_screener_jquants_adapter import row as fins_row
from tests.intelligence.test_screener_jquants_live import master

REPO_ROOT = Path(__file__).resolve().parents[2]
MODULE = REPO_ROOT / "src" / "intelligence" / "jquants_pilot2_local.py"
D0 = "2026-06-30"
MASTER = "/v2/equities/master"
FINS = "/v2/fins/summary"
ACCEPTED = "2026-06-30T19:05:00+09:00"                                          # D0 の当日の審査（指標の PIT に要る）
ACCEPTED_LATER = "2026-07-01T18:05:00+09:00"
FORBIDDEN_IN_SUMMARY = ("13010", "13020", "13030", "合成", "Synth", "500000000000", "40000000000", "Sales", "CoName",
                        "synthetic-key", "p8obs_", "p8idr_", "x-api-key")


def payload(*rows, **top) -> str:
    return json.dumps({"data": list(rows), **top}, ensure_ascii=False)


def master_key(day: str = D0):
    return (MASTER, (("date", day),))


def fins_key(code: str, pagination: str = ""):
    return (FINS, (("code", code),) if not pagination else (("code", code), ("pagination_key", pagination)))


def fins_rows(code: str, *, ifrs: bool = False, foreign: bool = False, years=(2024, 2025)) -> list:
    rows = []
    for year in years:
        rows.append(fins_row(Code=code, DiscNo=f"{year}0512000001", DiscDate=f"{year}-05-12",
                             CurPerSt=f"{year - 1}-04-01", CurPerEn=f"{year}-03-31", CurFYSt=f"{year - 1}-04-01",
                             CurFYEn=f"{year}-03-31",
                             Sales=str(500000000000 + year), OP="40000000000", NP="30000000000", TA="900000000000",
                             DocType="FYFinancialStatements_Consolidated_Foreign" if foreign else
                             "FYFinancialStatements_Consolidated_IFRS" if ifrs else
                             "FYFinancialStatements_Consolidated_JP"))
    return rows


def transport(mapping: dict) -> SyntheticTransport:
    return SyntheticTransport({key: TransportResponse(200, body) if isinstance(body, str) else body
                               for key, body in mapping.items()})


def standard_transport(codes=("13010",), ifrs=False, foreign=False) -> SyntheticTransport:
    mapping = {master_key(): payload(master("13010"), master("13020", "0112"), master("13030", "0113"),
                                     master("13040", prodcat="021"), master("13050", mkt="0109"))}
    for code in codes:
        mapping[fins_key(code)] = payload(*fins_rows(code, ifrs=ifrs, foreign=foreign))
    return transport(mapping)


@pytest.fixture
def root(tmp_path: Path, monkeypatch) -> Path:
    monkeypatch.delenv("GITHUB_ACTIONS", raising=False)
    monkeypatch.delenv("GITHUB_WORKSPACE", raising=False)
    return tmp_path / "private_root"


def pilot_dir(root: Path) -> Path:
    return root / "pilot2"


def read(root: Path, name: str) -> dict:
    return json.loads((pilot_dir(root) / name).read_text(encoding="utf-8"))


def decide(root: Path, disposition="APPROVE", accepted_at=ACCEPTED, **per_code) -> Path:
    template = read(root, "decision_template.json")
    for item in template["decisions"]:
        item["disposition"] = per_code.get(item["code"], disposition)
    template["accepted_at"] = accepted_at
    path = pilot_dir(root) / "decision.json"
    path.write_text(json.dumps(template, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def journal_lines(root: Path, name: str) -> int:
    path = root / "screener_intelligence" / name
    return len(path.read_text(encoding="utf-8").splitlines()) if path.exists() else -1


# ================================================================ data root


def test_data_root_must_be_private_absolute_and_outside_repo_git_and_actions(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.delenv("GITHUB_ACTIONS", raising=False)
    monkeypatch.delenv("GITHUB_WORKSPACE", raising=False)
    assert validate_data_root(tmp_path / "ok") == (tmp_path / "ok").resolve()
    for bad, code in ((None, "DATA_ROOT_REQUIRED"), ("", "DATA_ROOT_REQUIRED"),
                      ("relative/dir", "DATA_ROOT_NOT_ABSOLUTE"),
                      (str(REPO_ROOT / "data" / "pilot"), "DATA_ROOT_INSIDE_REPO"),
                      (str(REPO_ROOT), "DATA_ROOT_INSIDE_REPO"),
                      (str(tmp_path / ".git" / "x"), "DATA_ROOT_INSIDE_GIT")):
        with pytest.raises(PilotError) as info:
            validate_data_root(bad)
        assert info.value.code == code, bad
    monkeypatch.setenv("GITHUB_WORKSPACE", str(tmp_path / "ws"))
    with pytest.raises(PilotError) as info:
        validate_data_root(tmp_path / "ws" / "root")
    assert info.value.code == "DATA_ROOT_INSIDE_WORKSPACE"
    monkeypatch.setenv("GITHUB_ACTIONS", "true")
    with pytest.raises(PilotError) as info:
        validate_data_root(tmp_path / "ok")
    assert info.value.code == "GITHUB_ACTIONS_NOT_ALLOWED"


# ================================================================ PREPARE


def test_prepare_one_eligible_target_writes_bounded_packet_and_stops(root: Path) -> None:
    fake = standard_transport()
    result = prepare(d0=D0, codes=["13010"], data_root=root, transport=fake)
    assert result["state"] == "HUMAN_REVIEW_REQUIRED" and result["target_count"] == 1
    assert result["eligibility_counts"] == {"ELIGIBLE_FOR_ID1": 1} and result["proposal_count"] == 1
    assert result["request"] == {"limit": 8, "paths": [MASTER], "remaining": 7, "used": 1}
    assert [c[0] for c in fake.calls] == [MASTER]                                             # fins は呼ばない
    packet = read(root, "review_packet.json")
    assert packet["schema"] == "p8_pilot2_review_packet:0.1.0" and packet["d0"] == D0
    target = packet["targets"][0]
    assert set(target) == {"code", "eligibility", "reasons", "market", "product_category", "name_ja", "name_en",
                           "checklist", "proposal_id", "proposal_digest", "issuer_anchor", "security_anchor",
                           "issuer_id", "security_id"}
    assert target["checklist"] == {"code_is_five_digit_common_equity": True, "market_supported": True,
                                   "product_category_is_domestic_equity": True, "name_present": True,
                                   "eligible_for_id1": True}
    assert set(packet["id1_rows"][0]) == {"Date", "Code", "CoName", "CoNameEn", "Mkt"}
    text = (pilot_dir(root) / "review_packet.json").read_text(encoding="utf-8")
    for raw_field in ("S17", "S33", "ScaleCat", "MktNm", "Mrgn", "TOPIX", "synthetic-key", "x-api-key"):
        assert raw_field not in text, raw_field
    template = read(root, "decision_template.json")
    assert template["accepted_at"] == "" and template["decisions"][0]["disposition"] == ""    # 既定の承認は無い
    assert not (root / "screener_intelligence").exists()                                        # A1 ・A2 に触れない
    assert {p.name for p in pilot_dir(root).iterdir()} == {"review_packet.json", "decision_template.json",
                                                           "budget_state.json"}
    for forbidden in ("13010", "合成"):
        assert forbidden not in json.dumps(result, ensure_ascii=False)                          # stdout の要約は安全


def test_prepare_three_targets_mixed_states_and_not_returned(root: Path) -> None:
    result = prepare(d0=D0, codes=["13010", "13040", "13990"], data_root=root, transport=standard_transport())
    assert result["eligibility_counts"] == {"ELIGIBLE_FOR_ID1": 1, "EXCLUDED": 1, "NOT_RETURNED": 1}
    packet = read(root, "review_packet.json")
    by_code = {t["code"]: t for t in packet["targets"]}
    assert by_code["13040"]["reasons"] == ["PRODUCT_CATEGORY_EXCLUDED"] and "proposal_id" not in by_code["13040"]
    assert by_code["13990"]["eligibility"] == "NOT_RETURNED"
    assert by_code["13990"]["reasons"] == ["TARGET_NOT_IN_SNAPSHOT"]
    assert len(read(root, "decision_template.json")["decisions"]) == 1


def test_prepare_three_eligible_targets_and_hold(root: Path, tmp_path: Path) -> None:
    result = prepare(d0=D0, codes=["13010", "13020", "13030"], data_root=root, transport=standard_transport())
    assert result["eligibility_counts"] == {"ELIGIBLE_FOR_ID1": 3} and result["proposal_count"] == 3
    other = tmp_path / "second"
    held = prepare(d0=D0, codes=["13050"], data_root=other, transport=standard_transport())
    assert held["eligibility_counts"] == {"HOLD": 1} and held["proposal_count"] == 0
    assert read(other, "decision_template.json")["decisions"] == []


def test_prepare_rejects_too_many_malformed_or_duplicate_targets_and_bad_d0(root: Path) -> None:
    fake = standard_transport()
    for codes, code in ((["13010", "13020", "13030", "13040"], "TARGET_COUNT_INVALID"), ([], "TARGET_COUNT_INVALID"),
                        (["1301"], "TARGET_CODE_INVALID"), (["13015"], "TARGET_CODE_INVALID"),
                        (["1301A"], "TARGET_CODE_INVALID"), (["13010", "13010"], "TARGET_CODE_DUPLICATE")):
        with pytest.raises(PilotError) as info:
            prepare(d0=D0, codes=codes, data_root=root, transport=fake)
        assert info.value.code == code, codes
    with pytest.raises(PilotError) as info:
        prepare(d0="2026/06/30", codes=["13010"], data_root=root, transport=fake)
    assert info.value.code == "D0_INVALID" and fake.calls == () and not root.exists()


def test_prepare_twice_is_refused_and_failed_request_consumes_budget(root: Path) -> None:
    prepare(d0=D0, codes=["13010"], data_root=root, transport=standard_transport())
    with pytest.raises(PilotError) as info:
        prepare(d0=D0, codes=["13010"], data_root=root, transport=standard_transport())
    assert info.value.code == "PACKET_ALREADY_EXISTS" and read(root, "budget_state.json")["used"] == 1
    other = root.parent / "failing"
    broken = transport({master_key(): TransportResponse(500, "")})
    with pytest.raises(LiveInputError) as info:
        prepare(d0=D0, codes=["13010"], data_root=other, transport=broken)
    assert info.value.code == "HTTP_STATUS_500" and read(other, "budget_state.json")["used"] == 1


# ================================================================ HUMAN decision


def test_execute_requires_explicit_decision_and_rejects_missing_empty_or_invalid_dispositions(root: Path) -> None:
    prepare(d0=D0, codes=["13010"], data_root=root, transport=standard_transport())
    fake = standard_transport()
    with pytest.raises(PilotError) as info:
        execute(data_root=root, transport=fake)
    assert info.value.code == "DECISION_MISSING"
    decide(root, disposition="")
    with pytest.raises(PilotError) as info:
        execute(data_root=root, transport=fake)
    assert info.value.code == "DECISION_DISPOSITION_MISSING"
    decide(root, disposition="yes")
    with pytest.raises(PilotError) as info:
        execute(data_root=root, transport=fake)
    assert info.value.code == "DECISION_DISPOSITION_MISSING"
    assert fake.calls == () and not (root / "screener_intelligence").exists()                  # 書かない ・呼ばない


@pytest.mark.parametrize("accepted,code", [("", "ACCEPTED_AT_MISSING"), ("2026-07-01T18:05:00", "ACCEPTED_AT_NAIVE"),
                                           ("July 1", "ACCEPTED_AT_INVALID")])
def test_execute_requires_timezone_aware_accepted_at(root: Path, accepted: str, code: str) -> None:
    prepare(d0=D0, codes=["13010"], data_root=root, transport=standard_transport())
    decide(root, accepted_at=accepted)
    with pytest.raises(PilotError) as info:
        execute(data_root=root, transport=standard_transport())
    assert info.value.code == code and not (root / "screener_intelligence").exists()


def test_execute_rejects_stale_manifest_and_wrong_proposal_digest(root: Path) -> None:
    prepare(d0=D0, codes=["13010"], data_root=root, transport=standard_transport())
    path = decide(root)
    decision = json.loads(path.read_text(encoding="utf-8"))
    decision["manifest_digest"] = "0" * 64
    path.write_text(json.dumps(decision), encoding="utf-8")
    with pytest.raises(PilotError) as info:
        execute(data_root=root, transport=standard_transport())
    assert info.value.code == "DECISION_MANIFEST_STALE"
    decision = json.loads(decide(root).read_text(encoding="utf-8"))
    decision["decisions"][0]["proposal_digest"] = "f" * 64
    path.write_text(json.dumps(decision), encoding="utf-8")
    with pytest.raises(PilotError) as info:
        execute(data_root=root, transport=standard_transport())
    assert info.value.code == "DECISION_PROPOSAL_STALE"
    packet_path = pilot_dir(root) / "review_packet.json"
    packet = json.loads(packet_path.read_text(encoding="utf-8"))
    packet["id1_rows"][0]["CoName"] = "改ざん"
    packet_path.write_text(json.dumps(packet, ensure_ascii=False), encoding="utf-8")
    decide(root)
    with pytest.raises(PilotError) as info:
        execute(data_root=root, transport=standard_transport())
    assert info.value.code == "PACKET_MANIFEST_STALE" and not (root / "screener_intelligence").exists()


@pytest.mark.parametrize("disposition", ["REJECT", "DEFER"])
def test_execute_reject_and_defer_register_nothing_and_fetch_no_fins(root: Path, disposition: str) -> None:
    prepare(d0=D0, codes=["13010"], data_root=root, transport=standard_transport())
    decide(root, disposition=disposition)
    fake = standard_transport()
    summary = execute(data_root=root, transport=fake)
    assert summary["id2"]["outcome"] == "NO_AUTHORIZED_ITEMS" and summary["state"] == "PILOT_FAIL"
    assert summary["decision_counts"] == {disposition: 1} and fake.calls == ()
    assert journal_lines(root, "identity_records.jsonl") == 0 and summary["request"]["used"] == 1


# ================================================================ EXECUTE happy path


def test_execute_end_to_end_pass_and_safe_summary(root: Path) -> None:
    prepare(d0=D0, codes=["13010"], data_root=root, transport=standard_transport())
    decide(root)
    fake = standard_transport()
    summary = execute(data_root=root, transport=fake)
    assert summary["state"] == "PILOT_PASS" and summary["id2"] == {"outcome": "APPENDED", "reasons": [],
                                                                    "bundles": {"APPENDED": 1}, "failure_code": ""}
    assert summary["identity_verification"] == {"ok": 1, "failed": 0, "reasons": []}
    assert summary["fins"]["success"] == 1 and summary["fins"]["rows"] == 2
    assert summary["exe_outcomes"] == {"APPENDED": 2} and summary["held_reasons"] == {}
    assert summary["request"] == {"limit": 8, "paths": [MASTER, FINS], "remaining": 6, "used": 2}
    assert [c[0] for c in fake.calls] == [FINS]                                                # master を再取得しない
    assert summary["store_integrity"] == {"identity": "OK", "observation": "OK", "semantic_metadata": "OK",
                                          "held": "OK"}
    metrics = summary["metrics"][0]                                              # 凍結 A2 の coverage 宣言が無い → typed
    for name in ("REVENUE_GROWTH", "OPERATING_MARGIN", "NET_MARGIN", "ROA_POINT_IN_TIME"):
        assert metrics[name]["status"] == "INSUFFICIENT_DATA"
        assert all(r.endswith(":OUTSIDE_COVERAGE") for r in metrics[name]["reasons"]), name
    assert len(summary["digests"]["manifest"]) == 64 and len(summary["digests"]["reviewed"]) == 64
    assert journal_lines(root, "semantic_metadata.jsonl") == 16
    text = json.dumps(summary, ensure_ascii=False)
    for forbidden in FORBIDDEN_IN_SUMMARY:
        assert forbidden not in text, forbidden
    assert "value" not in {k for m in summary["metrics"] for v in m.values() for k in v}      # 値は無い
    assert (pilot_dir(root) / "safe_summary.json").read_text(encoding="utf-8") == json.dumps(
        summary, ensure_ascii=False, sort_keys=True, indent=2) + "\n"
    assert journal_lines(root, "identity_records.jsonl") == 8 and journal_lines(root, "observation_records.jsonl") == 8
    assert {p.name for p in root.iterdir()} == {"pilot2", "screener_intelligence"}
    assert not list(root.glob("**/*.log")) and not list(root.glob("**/raw*"))


def test_execute_rerun_converges_and_budget_does_not_reset(root: Path) -> None:
    prepare(d0=D0, codes=["13010"], data_root=root, transport=standard_transport())
    decide(root)
    execute(data_root=root, transport=standard_transport())
    again = execute(data_root=root, transport=standard_transport())
    assert again["id2"]["outcome"] == "REUSED" and again["exe_outcomes"] == {"REUSED": 2}
    assert again["state"] == "PILOT_PASS" and again["request"]["used"] == 3                 # fins は再取得（予算は続く）
    assert journal_lines(root, "identity_records.jsonl") == 8 and journal_lines(root, "observation_records.jsonl") == 8
    assert read(root, "budget_state.json")["used"] == 3


def test_execute_three_approved_targets_and_budget_exhaustion_is_typed(root: Path) -> None:
    prepare(d0=D0, codes=["13010", "13020", "13030"], data_root=root, transport=standard_transport())
    decide(root)
    fake = standard_transport(codes=("13010", "13020", "13030"))
    summary = execute(data_root=root, transport=fake)
    assert summary["state"] == "PILOT_PASS" and summary["id2"]["bundles"] == {"APPENDED": 3}
    assert summary["fins"]["success"] == 3 and summary["request"]["used"] == 4 and len(summary["metrics"]) == 3
    state = read(root, "budget_state.json")
    state["used"], state["paths"] = 7, [MASTER] + [FINS] * 6                                   # 予算が残り 1 の状態を再現
    (pilot_dir(root) / "budget_state.json").write_text(json.dumps(state), encoding="utf-8")
    again = execute(data_root=root, transport=standard_transport(codes=("13010", "13020", "13030")))
    assert again["fins"]["success"] == 1 and again["fins"]["skipped_budget"] == 2
    assert again["fins"]["reasons"] == ["BUDGET_EXHAUSTED", "BUDGET_EXHAUSTED"] and again["request"]["used"] == 8
    assert again["state"] == "PILOT_PARTIAL"
    third = execute(data_root=root, transport=standard_transport(codes=("13010", "13020", "13030")))
    assert third["fins"]["skipped_budget"] == 3 and third["request"]["used"] == 8                # 9 回目は無い


def test_execute_mixed_dispositions_fetch_fins_only_for_approved(root: Path) -> None:
    prepare(d0=D0, codes=["13010", "13020", "13030"], data_root=root, transport=standard_transport())
    decide(root, **{"13010": "APPROVE", "13020": "REJECT", "13030": "DEFER"})
    fake = standard_transport(codes=("13010", "13020", "13030"))
    summary = execute(data_root=root, transport=fake)
    assert summary["decision_counts"] == {"APPROVE": 1, "REJECT": 1, "DEFER": 1}
    assert summary["id2"]["bundles"] == {"APPENDED": 1} and [c for c in fake.calls] == [fins_key("13010")]
    assert summary["state"] == "PILOT_PASS"


# ================================================================ EXECUTE failure paths


def test_execute_fins_malformed_and_accounting_standard_hold(root: Path) -> None:
    prepare(d0=D0, codes=["13010"], data_root=root, transport=standard_transport())
    decide(root)
    broken = transport({fins_key("13010"): "not json"})
    summary = execute(data_root=root, transport=broken)
    assert summary["fins"] == {"success": 0, "failed": 1, "skipped_budget": 0, "reasons": ["PAYLOAD_NOT_JSON"],
                               "rows": 0, "pagination_seen": 0}
    assert summary["state"] == "PILOT_PARTIAL" and summary["request"]["used"] == 2 and summary["metrics"] == []
    foreign = execute(data_root=root, transport=standard_transport(foreign=True))    # Foreign は fail closed のまま
    assert foreign["exe_outcomes"] == {"HELD": 2} and foreign["held_reasons"] == {"ACCOUNTING_STANDARD_UNKNOWN": 2,
                                                                                "CURRENCY_UNKNOWN": 2}
    assert foreign["exe_reasons"] == {"ADAPTER_HELD": 2} and foreign["state"] == "PILOT_PARTIAL"
    assert foreign["metrics"][0]["OPERATING_MARGIN"] == {"status": "UNAVAILABLE",
                                                         "reasons": ["NO_FISCAL_YEAR_OBSERVATION"]}
    assert journal_lines(root, "held_observations.jsonl") == 2 and journal_lines(root, "observation_records.jsonl") == 0


def test_execute_adp0r_a_documented_non_jp_standard_reaches_a2_and_the_next_limit_is_coverage(root: Path) -> None:
    """ADP0R: IFRS の行は保留されず A2 に届く（実 PILOT2 の 21 行 HELD の再現の反転）。次の限界は OBS-60 の coverage。"""
    prepare(d0=D0, codes=["13010"], data_root=root, transport=standard_transport(ifrs=True))
    decide(root)
    summary = execute(data_root=root, transport=standard_transport(ifrs=True))
    assert summary["exe_outcomes"] == {"APPENDED": 2} and summary["held_reasons"] == {}
    assert summary["state"] == "PILOT_PASS"
    assert journal_lines(root, "held_observations.jsonl") == 0 and journal_lines(root, "observation_records.jsonl") == 8
    for metric in ("REVENUE_GROWTH", "OPERATING_MARGIN", "NET_MARGIN", "ROA_POINT_IN_TIME"):
        status = summary["metrics"][0][metric]
        assert status["status"] == "INSUFFICIENT_DATA"
        assert all(r.endswith(":OUTSIDE_COVERAGE") for r in status["reasons"])
    text = json.dumps(summary, ensure_ascii=False)
    for forbidden in FORBIDDEN_IN_SUMMARY:
        assert forbidden not in text, forbidden


def test_execute_metric_unavailable_without_prior_year_is_typed(root: Path) -> None:
    prepare(d0=D0, codes=["13010"], data_root=root, transport=standard_transport())
    decide(root)
    single = transport({fins_key("13010"): payload(*fins_rows("13010", years=(2025,)))})
    summary = execute(data_root=root, transport=single)
    metrics = summary["metrics"][0]
    assert metrics["REVENUE_GROWTH"] == {"status": "INSUFFICIENT_DATA", "reasons": ["NO_PRIOR_FISCAL_YEAR"]}
    assert metrics["NET_MARGIN"]["status"] == "INSUFFICIENT_DATA" and summary["state"] == "PILOT_PASS"


def test_metrics_become_available_once_a_fundamental_coverage_declaration_exists(root: Path) -> None:
    """runner の A3 の配線の証明: test だけが凍結 A2 の coverage record を足す（runner ・EXE は宣言しない。P8-OBS-60）。"""
    from datetime import date as _date, datetime as _dt, timezone as _tz
    from src.intelligence.screener_intelligence.identity_model import SourceClass
    from src.intelligence.screener_intelligence.observation_model import (CoverageDataset, ObservationCoverage,
                                                                          ObservationProvenance)
    prepare(d0=D0, codes=["13010"], data_root=root, transport=standard_transport())
    decide(root)
    summary = execute(data_root=root, transport=standard_transport())
    assert summary["metrics"][0]["NET_MARGIN"]["status"] == "INSUFFICIENT_DATA"
    store = ost.ObservationStore.open(root)
    store.append(ObservationCoverage(dataset=CoverageDataset.FUNDAMENTAL_DISCLOSURE, data_from=_date(2021, 4, 1),
                                     data_to=_date(2026, 7, 1), complete_through=_dt(2026, 7, 1, tzinfo=_tz.utc),
                                     provenance=ObservationProvenance(source_class=SourceClass.JQUANTS,
                                                                      source_record_ref="jq.test:coverage",
                                                                      source_field="")))
    issuer_id = next(iter(ist.IdentityStore.open(root).history.issuers))
    metrics = pl._metrics_for(root, issuer_id)
    assert {m["status"] for m in metrics.values()} == {"VALUE"} and "value" not in json.dumps(metrics)


def test_execute_review_after_d0_leaves_metrics_typed_unresolved_but_pilot_can_pass(root: Path) -> None:
    """凍結の PIT: identity は審査の時刻に知られ、bootstrap の coverage は D0 の 1 日。D0 の後の審査では指標の主語が解けない。"""
    prepare(d0=D0, codes=["13010"], data_root=root, transport=standard_transport())
    decide(root, accepted_at=ACCEPTED_LATER)
    summary = execute(data_root=root, transport=standard_transport())
    assert summary["state"] == "PILOT_PASS" and summary["exe_outcomes"] == {"APPENDED": 2}
    metrics = summary["metrics"][0]
    assert metrics["OPERATING_MARGIN"]["status"] == "INSUFFICIENT_DATA"
    assert all(r.endswith((":SUBJECT_NOT_RESOLVED", ":OUTSIDE_COVERAGE"))
               for r in metrics["OPERATING_MARGIN"]["reasons"])


def test_execute_identity_failure_prevents_fins(root: Path, monkeypatch) -> None:
    prepare(d0=D0, codes=["13010"], data_root=root, transport=standard_transport())
    decide(root)
    fake = standard_transport()

    def unresolved(history, code):
        raise LiveInputError("IDENTITY_NOT_REGISTERED", "code")

    monkeypatch.setattr(pl, "verify_identity_for_code", unresolved)
    summary = execute(data_root=root, transport=fake)
    assert summary["identity_verification"] == {"ok": 0, "failed": 1, "reasons": ["IDENTITY_NOT_REGISTERED"]}
    assert fake.calls == () and summary["fins"]["success"] == 0 and summary["state"] == "PILOT_PARTIAL"


def test_execute_partial_id2_write_then_rerun_converges_without_deleting_journals(root: Path, monkeypatch) -> None:
    prepare(d0=D0, codes=["13010"], data_root=root, transport=standard_transport())
    decide(root)
    original = ist.IdentityStore.append
    calls = {"n": 0}

    def failing_third(self, record):
        calls["n"] += 1
        if calls["n"] == 3:
            raise OSError(28, "no space")
        return original(self, record)

    monkeypatch.setattr(ist.IdentityStore, "append", failing_third)
    fake = standard_transport()
    summary = execute(data_root=root, transport=fake)
    assert summary["id2"]["outcome"] == "PARTIAL_FAILURE" and summary["state"] == "PILOT_FAIL"
    assert fake.calls == () and journal_lines(root, "identity_records.jsonl") == 2                # fins は発しない
    monkeypatch.setattr(ist.IdentityStore, "append", original)
    rerun = execute(data_root=root, transport=standard_transport())
    assert rerun["id2"]["outcome"] == "APPENDED" and rerun["state"] == "PILOT_PASS"
    assert journal_lines(root, "identity_records.jsonl") == 8 and rerun["request"]["used"] == 2


def test_execute_partial_exe_write_then_rerun_converges(root: Path, monkeypatch) -> None:
    prepare(d0=D0, codes=["13010"], data_root=root, transport=standard_transport())
    decide(root)
    original = ost.ObservationStore.append

    def failing(self, record):
        raise OSError(5, "io")

    monkeypatch.setattr(ost.ObservationStore, "append", failing)
    summary = execute(data_root=root, transport=standard_transport())
    assert summary["exe_outcomes"] == {"PARTIAL_FAILURE": 2} and summary["state"] == "PILOT_PARTIAL"
    assert journal_lines(root, "semantic_metadata.jsonl") == 4 and journal_lines(root, "observation_records.jsonl") == 0
    monkeypatch.setattr(ost.ObservationStore, "append", original)
    rerun = execute(data_root=root, transport=standard_transport())
    assert rerun["exe_outcomes"] == {"APPENDED": 2} and rerun["state"] == "PILOT_PASS"
    assert journal_lines(root, "semantic_metadata.jsonl") == 16
    assert journal_lines(root, "observation_records.jsonl") == 8


def test_execute_corrupt_store_is_reported_not_repaired(root: Path) -> None:
    prepare(d0=D0, codes=["13010"], data_root=root, transport=standard_transport())
    decide(root)
    execute(data_root=root, transport=standard_transport())
    path = root / "screener_intelligence" / "held_observations.jsonl"
    path.write_bytes(path.read_bytes() + b"garbage\n")
    fake = standard_transport()
    summary = execute(data_root=root, transport=fake)
    assert summary["store_integrity"]["held"].startswith("CORRUPT") and summary["state"] == "PILOT_FAIL"
    assert summary["id2"]["outcome"] == "NOT_ATTEMPTED" and fake.calls == ()                  # 書かない ・呼ばない
    assert path.read_bytes().endswith(b"garbage\n")                                             # 修復 ・削除しない


# ================================================================ CLI / architecture


def test_cli_prepare_and_execute_use_the_local_transport_and_print_only_safe_output(root: Path, monkeypatch,
                                                                                    capsys) -> None:
    from src.intelligence import jquants_local_transport as lt

    class FakeConnection:
        script = [payload(master("13010")), payload(*fins_rows("13010"))]

        def __init__(self, host, port, timeout=None, context=None):
            assert host == "api.jquants.com"

        def request(self, method, url, headers=None):
            assert headers["x-api-key"] == "synthetic-key-not-real"

        def getresponse(self):
            body = FakeConnection.script.pop(0).encode("utf-8")

            class R:
                status = 200

                def read(self, n=None):
                    return body[:n] if n else body
            return R()

        def close(self):
            pass

    monkeypatch.setattr(lt, "_HTTPSConnection", FakeConnection)
    monkeypatch.setenv("JQUANTS_API_KEY", "synthetic-key-not-real")
    assert pl.main(["prepare", "--d0", D0, "--codes", "13010", "--data-root", str(root)]) == 0
    out = capsys.readouterr().out
    assert '"state": "HUMAN_REVIEW_REQUIRED"' in out and "13010" not in out and "synthetic-key" not in out
    decide(root)
    assert pl.main(["execute", "--data-root", str(root)]) == 0
    out = capsys.readouterr().out
    assert '"state": "PILOT_PASS"' in out and "13010" not in out and "合成" not in out
    monkeypatch.delenv("JQUANTS_API_KEY")
    assert pl.main(["execute", "--data-root", str(root)]) == 2
    assert '"code": "CREDENTIAL_MISSING"' in capsys.readouterr().out


def test_architecture_runner_is_local_only_and_not_wired_anywhere() -> None:
    source = MODULE.read_text(encoding="utf-8")
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.level:
            assert node.module.startswith("screener_intelligence.") or node.module == "jquants_local_transport", \
                node.module
        if isinstance(node, ast.ImportFrom) and not node.level:
            assert node.module in ("__future__", "datetime", "pathlib", "typing"), node.module
        if isinstance(node, ast.Import):
            assert all(a.name in ("argparse", "hashlib", "json", "os", "re", "sys") for a in node.names)
        if isinstance(node, ast.Attribute):
            assert node.attr not in {"now", "utcnow", "today", "urlopen", "uuid4", "random", "unlink", "rmtree",
                                     "remove", "sleep"}, node.attr
    lowered = executable_source(MODULE).lower()
    for token in ("screening", "rank", "score", "recommend", "theme", "llm", "prompt", "anthropic", "openai",
                  "docs/pages", "morning", "cron", "schedule", "logging", "api.jquants.com", "://"):   # PILOT2B: ACQ0 の欄名
        assert token not in lowered, token
    for root_name in ("main.py", ".github", "scripts", "src/intelligence/reports",
                      "src/intelligence/narrative_intelligence", "src/intelligence/theme_intelligence",
                      "src/intelligence/market"):
        path = REPO_ROOT / root_name
        files = [path] if path.is_file() else (list(path.rglob("*")) if path.exists() else [])
        for file in files:
            if file.is_file() and file.suffix in (".py", ".yml", ".yaml", ".toml", ".sh", ".md"):
                assert "jquants_pilot2_local" not in file.read_text(encoding="utf-8", errors="replace"), file
    from tests.intelligence.test_p43b2c_production_bundle import runtime_closure
    assert not any("jquants_pilot2_local" in m or "jquants_local_transport" in m for m in runtime_closure())
    assert pl.MAX_TARGET_CODES == 3 and pl.SUPPORTED_MARKETS == ("0111", "0112", "0113")
