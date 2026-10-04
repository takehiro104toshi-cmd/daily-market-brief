"""P8-ACQ0 — 取得 event の authority の基盤（model ・追記専用 store）の test。

境界 ／ 凍結の guard は `test_screener_intelligence_boundary.py`。
すべて合成（架空の code ・日付 ・行）。network ・時計 ・実データ ・LLM ・raw の応答は使わない。`acquired_at` は test が明示に渡す。
"""
from __future__ import annotations

import ast
import json
from dataclasses import FrozenInstanceError
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from src.intelligence.screener_intelligence import acquisition_event_model as am
from src.intelligence.screener_intelligence import acquisition_event_store as st
from src.intelligence.screener_intelligence.acquisition_event_model import (AcquisitionEvent, AcquisitionModelError,
                                                                            AcquisitionStatus, BoundedContent,
                                                                            RequestScope, acquisition_reference,
                                                                            bounded_content_digest,
                                                                            is_acquisition_reference)
from src.intelligence.screener_intelligence.acquisition_event_store import (AcquisitionAppendRejected,
                                                                            AcquisitionConcurrentModification,
                                                                            AcquisitionEventStore,
                                                                            AcquisitionStoreCorrupt,
                                                                            AcquisitionStoreMissing, AppendStatus)
from src.intelligence.screener_intelligence.identity_model import SourceClass
from src.intelligence.screener_intelligence.jquants_adapter_model import SUPPORTED_FIELDS
from src.intelligence.screener_intelligence.jquants_live_model import FINS_SUMMARY_PATH, MASTER_PATH
from src.intelligence.screener_intelligence.jquants_master_ingress import ELIGIBILITY_FIELDS
from tests.intelligence.phase8_runtime_registry import PHASE8_PACKAGE
from tests.intelligence.test_prediction_record import executable_source

REPO_ROOT = Path(__file__).resolve().parents[2]
PACKAGE_DIR = REPO_ROOT / PHASE8_PACKAGE
JST = timezone(timedelta(hours=9))
ACQUIRED = datetime(2026, 7, 1, 18, 5, 0, tzinfo=JST)                                 # test が明示に渡す（時計なし）
MASTER_ROW = {"Date": "2026-07-01", "Code": "13010", "CoName": "合成一号", "CoNameEn": "Synth One", "Mkt": "0111",
              "ProdCat": "011"}
FINS_ROW = {"Code": "13010", "DiscDate": "2025-05-12", "DiscTime": "15:00:00", "DiscNo": "20250512000001",
            "DocType": "FYFinancialStatements_Consolidated_JP", "CurPerType": "FY", "CurPerSt": "2024-04-01",
            "CurPerEn": "2025-03-31", "CurFYSt": "2024-04-01", "CurFYEn": "2025-03-31", "Sales": "500000000000",
            "OP": "40000000000", "NP": "30000000000", "TA": "900000000000"}


def master_scope(day: str = "2026-07-01") -> RequestScope:
    return RequestScope.of(MASTER_PATH, {"date": day})


def fins_scope(code: str = "13010") -> RequestScope:
    return RequestScope.of(FINS_SUMMARY_PATH, {"code": code})


def event(scope: RequestScope = None, *, rows=(FINS_ROW,), status=AcquisitionStatus.COMPLETE, acquired_at=ACQUIRED,
          pagination=False, pages=1, failure_code="") -> AcquisitionEvent:
    scope = scope or fins_scope()
    content = bounded_content_digest(scope.endpoint, rows)
    return AcquisitionEvent(provider=SourceClass.JQUANTS, scope=scope, acquired_at=acquired_at, status=status,
                            row_count=content.row_count, pagination_key_present=pagination, pages_followed=pages,
                            content_digest=content.digest, failure_code=failure_code)


@pytest.fixture
def root(tmp_path: Path) -> Path:
    private = tmp_path / "private_root"
    AcquisitionEventStore.initialize(private)
    return private


# ================================================================ A 範囲（request scope）


def test_a_request_scope_is_canonical_sorted_and_distinguishes_master_from_fins() -> None:
    both = RequestScope.of(FINS_SUMMARY_PATH, {"date": "2026-07-01", "code": "13010"})
    assert both.params == (("code", "13010"), ("date", "2026-07-01"))                   # key の整列
    assert both.as_dict() == {"endpoint": FINS_SUMMARY_PATH, "params": [["code", "13010"], ["date", "2026-07-01"]]}
    assert RequestScope.from_dict(both.as_dict()) == both
    assert master_scope().params == (("date", "2026-07-01"),)
    assert am.SCOPE_KEYS == {MASTER_PATH: ("date",), FINS_SUMMARY_PATH: ("code", "date")}


@pytest.mark.parametrize("endpoint,params,code", [
    (MASTER_PATH, {"code": "13010"}, "SCOPE_KEY_NOT_ALLOWED"),                         # master は date だけ
    (MASTER_PATH, {"date": "2026-07-01", "code": "13010"}, "SCOPE_KEY_NOT_ALLOWED"),
    (MASTER_PATH, {}, "SCOPE_EMPTY"),
    (FINS_SUMMARY_PATH, {}, "SCOPE_EMPTY"),
    (FINS_SUMMARY_PATH, {"pagination_key": "abc"}, "SCOPE_KEY_NOT_ALLOWED"),            # 範囲ではなく状態
    (FINS_SUMMARY_PATH, {"symbol": "13010"}, "QUERY_KEY_NOT_ALLOWED"),                  # 未知の key
    (FINS_SUMMARY_PATH, {"x-api-key": "abc"}, "CREDENTIAL_IN_QUERY"),
    (FINS_SUMMARY_PATH, {"Authorization": "Bearer x"}, "CREDENTIAL_IN_QUERY"),
    (FINS_SUMMARY_PATH, {"token": "abc"}, "CREDENTIAL_IN_QUERY"),
    (FINS_SUMMARY_PATH, {"code": "1301 0"}, "INVALID_QUERY_VALUE"),
    ("/v2/equities/daily", {"code": "13010"}, "ENDPOINT_NOT_ALLOWED"),
    ("https://example.invalid/v2/fins/summary", {"code": "13010"}, "ENDPOINT_NOT_ALLOWED")])
def test_a_unknown_keys_credentials_headers_and_urls_are_rejected(endpoint, params, code) -> None:
    with pytest.raises(AcquisitionModelError) as exc:
        RequestScope.of(endpoint, params)
    assert exc.value.code == code


def test_a_non_canonical_or_duplicate_params_are_rejected_at_construction() -> None:
    with pytest.raises(AcquisitionModelError) as exc:
        RequestScope(endpoint=FINS_SUMMARY_PATH, params=(("date", "2026-07-01"), ("code", "13010")))
    assert exc.value.code == "SCOPE_NOT_CANONICAL"
    with pytest.raises(AcquisitionModelError):
        RequestScope.from_dict({"endpoint": FINS_SUMMARY_PATH, "params": [["code", "13010"]], "url": "x"})


# ================================================================ B acquired_at


def test_b_acquired_at_must_be_timezone_aware_and_is_stored_as_utc() -> None:
    with pytest.raises(AcquisitionModelError) as exc:
        event(acquired_at=datetime(2026, 7, 1, 18, 5))
    assert exc.value.code == "NAIVE_DATETIME"
    with pytest.raises(AcquisitionModelError):
        event(acquired_at="2026-07-01T18:05:00+09:00")
    assert event().as_dict()["acquired_at"] == "2026-07-01T09:05:00+00:00"
    same_instant = event(acquired_at=datetime(2026, 7, 1, 9, 5, tzinfo=timezone.utc))
    assert same_instant.record_id == event().record_id                                   # 同じ瞬間 ＝ 同じ event


def test_b_the_model_and_store_read_no_clock() -> None:
    for name in ("acquisition_event_model", "acquisition_event_store"):
        source = executable_source(PACKAGE_DIR / f"{name}.py")
        for token in ("now(", "utcnow", "today(", "time.time", "monotonic", "perf_counter"):
            assert token not in source, (name, token)


# ================================================================ C 内容の digest


def test_c_bounded_content_digest_is_deterministic_and_order_sensitive() -> None:
    second = {**FINS_ROW, "DiscNo": "20250512000002"}
    one = bounded_content_digest(FINS_SUMMARY_PATH, [FINS_ROW, second])
    again = bounded_content_digest(FINS_SUMMARY_PATH, [dict(reversed(list(FINS_ROW.items()))), second])
    assert one == again and one.row_count == 2 and len(one.digest) == 64              # key の順に依らない
    reordered = bounded_content_digest(FINS_SUMMARY_PATH, [second, FINS_ROW])
    assert reordered.digest != one.digest                                                # 行の順は意味を持つ（整列しない）
    assert am.ROW_ORDER_RULE == "HANDOFF_ORDER_AS_RECEIVED"
    empty = bounded_content_digest(FINS_SUMMARY_PATH, [])
    assert empty.row_count == 0 and empty == bounded_content_digest(FINS_SUMMARY_PATH, ())
    assert bounded_content_digest(MASTER_PATH, [MASTER_ROW]).row_count == 1


def test_c_the_digest_accepts_only_the_frozen_bounded_fields_and_no_values_leak_into_the_digest() -> None:
    assert am.BOUNDED_FIELDS == {MASTER_PATH: ELIGIBILITY_FIELDS, FINS_SUMMARY_PATH: SUPPORTED_FIELDS}
    with pytest.raises(AcquisitionModelError) as exc:
        bounded_content_digest(FINS_SUMMARY_PATH, [{**FINS_ROW, "EPS": "1.0"}])          # 公式の他の欄を広げない
    assert exc.value.code == "ROW_FIELDS_NOT_BOUNDED"
    with pytest.raises(AcquisitionModelError):
        bounded_content_digest(FINS_SUMMARY_PATH, [{k: v for k, v in FINS_ROW.items() if k != "TA"}])
    with pytest.raises(AcquisitionModelError):
        bounded_content_digest(FINS_SUMMARY_PATH, [{**FINS_ROW, "Sales": 500}])
    with pytest.raises(AcquisitionModelError):
        bounded_content_digest(MASTER_PATH, [FINS_ROW])
    with pytest.raises(AcquisitionModelError):
        BoundedContent(row_count=1, digest="abc")
    text = event().canonical_line()
    for value in ("500000000000", "40000000000", "合成一号", "Synth", "20250512000001", "FYFinancialStatements"):
        assert value not in text, value                                                  # 値 ・名前 ・DocType は残らない


# ================================================================ D 状態


def test_d_complete_partial_failed_and_empty_are_the_only_states_with_consistent_facts() -> None:
    assert [s.value for s in AcquisitionStatus] == ["COMPLETE", "PARTIAL_PAGINATED", "FAILED", "EMPTY"]
    complete = event()
    assert complete.status is AcquisitionStatus.COMPLETE and complete.row_count == 1
    partial = event(rows=[FINS_ROW], status=AcquisitionStatus.PARTIAL_PAGINATED, pagination=True, pages=1)
    assert partial.pagination_key_present and partial.pages_followed == 1
    followed = event(rows=[FINS_ROW, {**FINS_ROW, "DiscNo": "20250512000002"}], pages=2)   # 2 page を追って完了
    assert followed.status is AcquisitionStatus.COMPLETE and followed.pages_followed == 2
    empty = event(rows=[], status=AcquisitionStatus.EMPTY)
    assert empty.row_count == 0 and not empty.pagination_key_present
    failed = event(rows=[], status=AcquisitionStatus.FAILED, failure_code="HTTP_STATUS_503", pages=0)
    assert failed.failure_code == "HTTP_STATUS_503" and failed.row_count == 0
    failed_mid = event(rows=[FINS_ROW], status=AcquisitionStatus.FAILED, failure_code="BUDGET_EXHAUSTED",
                       pagination=True, pages=1)
    assert failed_mid.row_count == 1                                                     # 届いた分の digest を残す


@pytest.mark.parametrize("kwargs,code", [
    (dict(rows=[], status=AcquisitionStatus.COMPLETE), "STATUS_INCONSISTENT"),           # 0 行の COMPLETE は EMPTY
    (dict(rows=[FINS_ROW], status=AcquisitionStatus.COMPLETE, pagination=True), "STATUS_INCONSISTENT"),
    (dict(rows=[FINS_ROW], status=AcquisitionStatus.EMPTY), "STATUS_INCONSISTENT"),
    (dict(rows=[], status=AcquisitionStatus.EMPTY, pagination=True), "STATUS_INCONSISTENT"),
    (dict(rows=[FINS_ROW], status=AcquisitionStatus.PARTIAL_PAGINATED, pagination=False), "STATUS_INCONSISTENT"),
    (dict(rows=[FINS_ROW], status=AcquisitionStatus.COMPLETE, pages=0), "PAGES_REQUIRED"),
    (dict(rows=[], status=AcquisitionStatus.FAILED), "FAILURE_CODE_REQUIRED"),
    (dict(rows=[FINS_ROW], status=AcquisitionStatus.COMPLETE, failure_code="X"), "FAILURE_CODE_NOT_ALLOWED"),
    (dict(rows=[], status=AcquisitionStatus.FAILED, failure_code="http 503"), "INVALID_FAILURE_CODE"),
    (dict(rows=[], status=AcquisitionStatus.FAILED, failure_code="BAD_TOKEN"), "CREDENTIAL_LIKE_TEXT")])
def test_d_inconsistent_facts_fail_closed(kwargs, code) -> None:
    with pytest.raises(AcquisitionModelError) as exc:
        event(**kwargs)
    assert exc.value.code == code


def test_d_empty_and_failed_and_complete_carry_no_coverage_or_truth_semantics() -> None:
    for name in ("acquisition_event_model", "acquisition_event_store"):
        source = executable_source(PACKAGE_DIR / f"{name}.py").lower()
        for token in ("coverage(", "observationcoverage", "complete_through", "effective_from", "effective_to",
                      "data_from", "data_to", "covers(", "no_disclosure", "absence", "resolve("):
            assert token not in source, (name, token)
        tree = ast.parse((PACKAGE_DIR / f"{name}.py").read_text(encoding="utf-8"))
        imported = {node.module for node in ast.walk(tree) if isinstance(node, ast.ImportFrom) and node.module}
        assert not any(m.endswith(("identity_store", "observation_store", "observation_model", "identity_resolver",
                                   "observation_resolver", "semantic_metadata_store", "held_observation_store"))
                       for m in imported), (name, imported)
    for status in AcquisitionStatus:
        payload = (event(rows=[] if status in (AcquisitionStatus.EMPTY, AcquisitionStatus.FAILED) else [FINS_ROW],
                         status=status, pagination=status is AcquisitionStatus.PARTIAL_PAGINATED,
                         failure_code="NETWORK_ERROR" if status is AcquisitionStatus.FAILED else "")).as_dict()
        assert set(payload) == {"acquired_at", "api_version", "authority_version", "content_digest", "failure_code",
                                "pages_followed", "pagination_key_present", "provider", "record_id", "record_kind",
                                "row_count", "row_order", "schema_version", "scope", "status"}


# ================================================================ E record ・identity ・参照


def test_e_canonical_serialization_round_trips_and_the_event_id_is_deterministic() -> None:
    first = event()
    line = first.canonical_line()
    assert line.endswith("\n") and json.loads(line) == first.as_dict()
    assert list(json.loads(line)) == sorted(json.loads(line))                            # key は整列
    assert AcquisitionEvent.from_dict(json.loads(line)) == first and st.parse_acquisition_line(line) == first
    assert first.record_id == event().record_id and first.record_id.startswith("p8acq_")
    assert len(first.record_id) == len("p8acq_") + 24
    assert first.record_id != event(acquired_at=ACQUIRED + timedelta(seconds=1)).record_id
    assert first.record_id != event(fins_scope("13020")).record_id
    assert first.record_id != event(rows=[{**FINS_ROW, "Sales": "1"}]).record_id            # 内容が違えば別の event
    with pytest.raises(FrozenInstanceError):
        first.row_count = 2  # type: ignore[misc]
    assert first.AUTHORITY_CLASS == "ACQUISITION_EVIDENCE_RECORD" and first.as_dict()["api_version"] == "v2"


@pytest.mark.parametrize("mutate,code", [
    (lambda d: d.update(record_id="p8acq_" + "0" * 24), "RECORD_ID_MISMATCH"),
    (lambda d: d.update(schema_version="p8_acquisition_event:9.0.0"), "SCHEMA_MISMATCH"),
    (lambda d: d.update(record_kind="OBSERVATION"), "KIND_MISMATCH"),
    (lambda d: d.update(api_version="v1"), "API_VERSION_MISMATCH"),
    (lambda d: d.update(row_order="SORTED"), "ROW_ORDER_MISMATCH"),
    (lambda d: d.update(raw_payload="{}"), "UNKNOWN_FIELD"),
    (lambda d: d.update(api_key="x"), "UNKNOWN_FIELD"),
    (lambda d: d.update(headers={}), "UNKNOWN_FIELD"),
    (lambda d: d.pop("scope"), "MISSING_FIELD"),
    (lambda d: d.update(acquired_at="2026-07-01T18:05:00"), "INVALID_DATETIME"),
    (lambda d: d.update(provider="OFFICIAL_EXCHANGE"), "PROVIDER_NOT_ALLOWED"),
    (lambda d: d.update(status="DONE"), "INVALID_VOCABULARY")])
def test_e_from_dict_rejects_unknown_fields_raw_payload_credentials_and_forged_ids(mutate, code) -> None:
    data = event().as_dict()
    mutate(data)
    with pytest.raises(AcquisitionModelError) as exc:
        AcquisitionEvent.from_dict(data)
    assert exc.value.code == code


def test_e_the_provenance_reference_is_derived_deterministically_from_the_event_id() -> None:
    first = event()
    assert first.reference == "jq.acq:" + first.record_id[len("p8acq_"):]
    assert is_acquisition_reference(first.reference) and acquisition_reference(first.record_id) == first.reference
    assert len(first.reference) == len("jq.acq:") + 24 and first.reference == event().reference
    assert not is_acquisition_reference("jq.acq:xyz") and not is_acquisition_reference("p8acq_" + "0" * 24)
    with pytest.raises(AcquisitionModelError):
        acquisition_reference("p8idr_" + "0" * 24)
    assert am.REFERENCE_PREFIX == "jq.acq:"


# ================================================================ F store


def test_f_append_reused_and_order_are_preserved(root: Path) -> None:
    store = AcquisitionEventStore.open(root)
    first, second = event(), event(fins_scope("13020"), rows=[{**FINS_ROW, "Code": "13020"}])
    assert store.append(first).status is AppendStatus.APPENDED
    assert store.append(first).status is AppendStatus.REUSED                             # byte 一致は収束
    assert store.append(second).status is AppendStatus.APPENDED
    assert [r.record_id for r in store.records()] == [first.record_id, second.record_id]
    assert store.counts() == {"COMPLETE": 2} and store.get(first.record_id) == first and store.get("x") is None
    reopened = AcquisitionEventStore.open(root, read_only=True)
    assert reopened.canonical_lines() == store.canonical_lines() and len(reopened.records()) == 2
    with pytest.raises(AcquisitionAppendRejected) as exc:
        reopened.append(first)
    assert exc.value.code == "READ_ONLY"
    with pytest.raises(AcquisitionAppendRejected):
        store.append({"record_kind": "ACQUISITION_EVENT"})
    assert (root / "screener_intelligence" / "acquisition_events.jsonl").read_text(encoding="utf-8") == \
        first.canonical_line() + second.canonical_line()


def test_f_conflicting_duplicate_id_with_different_content_fails_closed(root: Path, monkeypatch) -> None:
    store = AcquisitionEventStore.open(root)
    first = event()
    store.append(first)
    fixed_id = first.record_id
    monkeypatch.setattr(AcquisitionEvent, "record_id", property(lambda self: fixed_id))
    with pytest.raises(AcquisitionAppendRejected) as exc:
        store.append(event(fins_scope("13020"), rows=[{**FINS_ROW, "Code": "13020"}]))
    assert exc.value.code == "ACQUISITION_CONTENT_CONFLICT" and len(store.records()) == 1


@pytest.mark.parametrize("tail,code", [
    (b'{"record_kind": "GARBAGE"}\n', "INVALID_RECORD"),
    (b"\n", "BLANK_LINE"),
    (b'{"a": 1', "TRUNCATED_FINAL_LINE"),
    (b"\xff\xfe\n", "INVALID_ENCODING")])
def test_f_malformed_journal_fails_closed_and_is_never_repaired(root: Path, tail: bytes, code: str) -> None:
    store = AcquisitionEventStore.open(root)
    store.append(event())
    path = root / "screener_intelligence" / "acquisition_events.jsonl"
    with path.open("ab") as handle:
        handle.write(tail)
    before = path.read_bytes()
    with pytest.raises(AcquisitionStoreCorrupt) as exc:
        AcquisitionEventStore.open(root)
    assert exc.value.code == code and path.read_bytes() == before


def test_f_non_canonical_physical_duplicate_and_external_change_fail_closed(root: Path) -> None:
    store = AcquisitionEventStore.open(root)
    first = event()
    store.append(first)
    path = root / "screener_intelligence" / "acquisition_events.jsonl"
    line = first.canonical_line()
    with path.open("ab") as handle:
        handle.write(line.encode("utf-8"))                                               # 物理的な重複
    with pytest.raises(AcquisitionStoreCorrupt) as exc:
        AcquisitionEventStore.open(root)
    assert exc.value.code == "PHYSICAL_DUPLICATE" and exc.value.line_number == 2
    with pytest.raises(AcquisitionConcurrentModification):
        store.append(event(fins_scope("13020"), rows=[{**FINS_ROW, "Code": "13020"}]))   # 外部の変更を検知
    path.write_bytes(line.replace('"status"', '"status" ').encode("utf-8"))             # 非正準の行
    with pytest.raises(AcquisitionStoreCorrupt) as exc:
        AcquisitionEventStore.open(root)
    assert exc.value.code == "NON_CANONICAL_LINE"
    with pytest.raises(AcquisitionStoreMissing):
        AcquisitionEventStore.open(root / "elsewhere")
    with pytest.raises(AcquisitionAppendRejected):
        AcquisitionEventStore.open("")


def test_f_replay_uses_the_stored_acquired_at_and_needs_no_clock(root: Path) -> None:
    store = AcquisitionEventStore.open(root)
    events = [event(acquired_at=ACQUIRED + timedelta(days=i)) for i in range(3)]
    for item in events:
        store.append(item)
    replayed = AcquisitionEventStore.open(root, read_only=True).records()
    assert [r.acquired_at for r in replayed] == [e.acquired_at for e in events]
    assert [r.record_id for r in replayed] == [e.record_id for e in events]
    assert [r.reference for r in replayed] == [e.reference for e in events]
    assert all(r.canonical_line() == e.canonical_line() for r, e in zip(replayed, events))


def test_f_the_store_touches_only_its_own_journal(root: Path) -> None:
    store = AcquisitionEventStore.open(root)
    store.append(event())
    store.append(event(master_scope(), rows=[MASTER_ROW]))
    assert {p.name for p in (root / "screener_intelligence").iterdir()} == {"acquisition_events.jsonl"}
    assert st.ACQUISITION_DIRNAME == "screener_intelligence" and st.ACQUISITION_FILENAME == "acquisition_events.jsonl"


# ================================================================ G privacy ・architecture


def test_g_the_journal_holds_acquisition_metadata_only(root: Path) -> None:
    store = AcquisitionEventStore.open(root)
    store.append(event(master_scope(), rows=[MASTER_ROW]))
    store.append(event())
    store.append(event(rows=[], status=AcquisitionStatus.FAILED, failure_code="HTTP_STATUS_401"))
    text = (root / "screener_intelligence" / "acquisition_events.jsonl").read_text(encoding="utf-8")
    for forbidden in ("合成一号", "Synth One", "500000000000", "40000000000", "30000000000", "900000000000",
                      "20250512000001", "FYFinancialStatements", "0111", "apikey", "api_key", "api-key", "token",
                      "Bearer", "://", "x-api-key", "Authorization", "raw", "payload", "header", "body", "secret"):
        assert forbidden not in text, forbidden
    assert "13010" in text                                                               # 承認済みの範囲の次元だけ残る


def test_g_architecture_no_network_no_io_outside_the_store_and_frozen_layers_do_not_import_acq0() -> None:
    model = executable_source(PACKAGE_DIR / "acquisition_event_model.py")
    for token in ("open(", "Path(", "os.", "urllib", "socket", "http", "environ", "getenv", "://"):
        assert token not in model, token
    store_source = executable_source(PACKAGE_DIR / "acquisition_event_store.py")
    for token in ("urllib", "socket", "http", "environ", "getenv", "://", "sqlite", "unlink", "rename", "truncate",
                  '"wb"', '"w"', "write_text", "write_bytes"):
        assert token not in store_source, token
    consumers = ("identity_continuity_coverage",)                                        # 後の gate の consumer（OBS60-I1）
    for path in sorted(PACKAGE_DIR.glob("*.py")):
        if path.stem not in ("acquisition_event_model", "acquisition_event_store", *consumers):
            assert "acquisition_event" not in path.read_text(encoding="utf-8"), path.name   # 先行の層は ACQ0 を知らない
    for path in (REPO_ROOT / "src" / "intelligence" / "jquants_local_transport.py",
                 REPO_ROOT / "src" / "intelligence" / "jquants_pilot2_local.py", REPO_ROOT / "main.py"):
        assert "acquisition_event" not in path.read_text(encoding="utf-8"), path.name     # 配線は後の gate
