"""P8-ST1 — 注記の運用 store ・保留の観測の model ／ store の test matrix A〜E（境界 ／ 凍結は `test_screener_intelligence_boundary.py`）。

すべて合成の record（A2 の凍結の test の合成の identity ・架空の観測）。J-Quants ・network ・実データ ・LLM ・時計 ・乱数は使わない。
書き込みは tmp_path だけ（実の data root ・repo の data には何も作らない）。A1 ・A2 ・A2R ・A3 の module は変えない。
"""
from __future__ import annotations

import ast
import json
import re
from dataclasses import FrozenInstanceError, fields, replace
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from src.intelligence.screener_intelligence import held_observation_model as hm
from src.intelligence.screener_intelligence import held_observation_store as hs
from src.intelligence.screener_intelligence import semantic_metadata_store as ss
from src.intelligence.screener_intelligence.held_observation_model import (HeldObservation, HeldObservationModelError,
                                                                           HeldReason)
from src.intelligence.screener_intelligence.held_observation_store import HeldObservationStore
from src.intelligence.screener_intelligence.identity_model import SourceClass
from src.intelligence.screener_intelligence.observation_model import FundamentalField, StatementBasis
from src.intelligence.screener_intelligence.observation_semantics_mapping import derive_observation_semantics
from src.intelligence.screener_intelligence.observation_semantics_model import (FieldFamily, ObservationSemantics,
                                                                                SchemaFamily,
                                                                                SemanticMappingProvenance)
from src.intelligence.screener_intelligence.semantic_metadata_store import SemanticMetadataStore
from tests.intelligence.phase8_runtime_registry import PHASE8_PACKAGE
from tests.intelligence.test_prediction_record import executable_source
from tests.intelligence.test_screener_fundamental_metrics import FY23, FY24, I1, IDS, K_FY24, JP_CONS, IFRS_CONS, rec
from tests.intelligence.test_screener_observation import at

REPO_ROOT = Path(__file__).resolve().parents[2]
PACKAGE_DIR = REPO_ROOT / PHASE8_PACKAGE
REV = FundamentalField.REVENUE
CONS, NONCONS = StatementBasis.CONSOLIDATED, StatementBasis.NON_CONSOLIDATED
JP_NONCONS = "FYFinancialStatements_NonConsolidated_JP"
OBS = rec(I1, REV, "500000", FY24, K_FY24)
OBS2 = rec(I1, REV, "400000", FY23, K_FY24)
DIGEST = "ab" * 32
REF = "jq.fins_summary:00000.20250512000001.FYFinancialStatements_Consolidated_JP:0123456789abcdef01234567"
MAPPING = "p8_jquants_v2_fins_summary_doctype:0.1.0"
RULES = "p8_bridge_hold:0.1.0"
T1 = at(2026, 6, 30, 12)


def sem(observation=OBS, doc=JP_CONS):
    return derive_observation_semantics(observation.record_id, doc, FieldFamily.UNPREFIXED_ACTUAL)


def held(reasons=(HeldReason.ACCOUNTING_STANDARD_UNKNOWN,), **extra) -> HeldObservation:
    base = dict(provider=SourceClass.JQUANTS, schema_family=SchemaFamily.JQUANTS_V2_FINS_SUMMARY,
                provider_record_ref=REF, provider_record_digest=DIGEST, reasons=reasons, mapping_rule_version=MAPPING,
                rules_version=RULES)
    base.update(extra)
    return HeldObservation(**base)


@pytest.fixture()
def root(tmp_path: Path) -> Path:
    return tmp_path / "private_root"


# ================================================================ A 注記の store


def test_a_first_append_then_exact_replay_is_idempotent(root: Path) -> None:
    store = SemanticMetadataStore.initialize(root)
    semantics, provenance = sem()
    assert store.append(provenance).status is ss.AppendStatus.APPENDED
    assert store.append(semantics).status is ss.AppendStatus.APPENDED
    assert store.append(provenance).status is ss.AppendStatus.ALREADY_PRESENT
    assert store.append(semantics).status is ss.AppendStatus.ALREADY_PRESENT
    assert store.records() == (provenance, semantics) and store.counts() == {provenance.KIND: 1, semantics.KIND: 1}
    assert store.semantics_for(OBS.record_id) == semantics and store.provenance_for(OBS.record_id) == provenance
    reopened = SemanticMetadataStore.open(root, read_only=True)
    assert reopened.records() == (provenance, semantics) and reopened.canonical_lines() == store.canonical_lines()
    assert (root / "screener_intelligence" / "semantic_metadata.jsonl").read_text(encoding="utf-8") == "".join(
        store.canonical_lines())
    with pytest.raises(ss.SemanticMetadataAppendRejected) as info:
        reopened.append(sem(OBS2)[1])
    assert info.value.code == "READ_ONLY"


def test_a_same_observation_same_semantics_reuses_and_never_duplicates(root: Path) -> None:
    store = SemanticMetadataStore.initialize(root)
    semantics, provenance = sem()
    again, provenance_again = sem()                                                        # 再導出（同じ内容 ・同じ id）
    store.append(provenance)
    store.append(semantics)
    assert store.append(provenance_again).status is ss.AppendStatus.ALREADY_PRESENT
    assert store.append(again).status is ss.AppendStatus.ALREADY_PRESENT
    assert len(store.records()) == 2 and SemanticMetadataStore.open(root).reload() == 2


def test_a_different_standard_for_the_same_observation_is_a_conflict(root: Path) -> None:
    store = SemanticMetadataStore.initialize(root)
    jp, jp_prov = sem(OBS, JP_CONS)
    ifrs, ifrs_prov = sem(OBS, IFRS_CONS)
    store.append(jp_prov)
    store.append(jp)
    with pytest.raises(ss.SemanticMetadataAppendRejected) as info:
        store.append(ifrs_prov)                                                           # provenance が先に衝突
    assert info.value.code == "PROVENANCE_CONFLICT"
    with pytest.raises(ss.SemanticMetadataAppendRejected) as info:
        store.append(ifrs)                                                                # 注記も衝突（先勝ちにしない）
    assert info.value.code in ("SEMANTICS_CONFLICT", "PROVENANCE_MISSING")
    with pytest.raises(ss.SemanticMetadataJournalError) as info:                          # journal 単体でも衝突
        ss.SemanticMetadataJournal([jp_prov, jp, ifrs_prov])
    assert info.value.code == "PROVENANCE_CONFLICT"
    with pytest.raises(ss.SemanticMetadataJournalError) as info:
        ss.SemanticMetadataJournal([jp_prov, jp]).add(ifrs)                                 # 注記の衝突は provenance の前に
    assert info.value.code == "SEMANTICS_CONFLICT"
    assert store.records() == (jp_prov, jp) and store.semantics_for(OBS.record_id) == jp    # 後の物は残らない


def test_a_different_basis_for_the_same_observation_is_a_conflict(root: Path) -> None:
    store = SemanticMetadataStore.initialize(root)
    cons, cons_prov = sem(OBS, JP_CONS)
    noncons, noncons_prov = sem(OBS, JP_NONCONS)
    store.append(cons_prov)
    store.append(cons)
    with pytest.raises(ss.SemanticMetadataAppendRejected) as info:
        store.append(noncons_prov)
    assert info.value.code == "PROVENANCE_CONFLICT"
    with pytest.raises(ss.SemanticMetadataJournalError) as info:
        ss.SemanticMetadataJournal([cons_prov, cons]).add(noncons)
    assert info.value.code == "SEMANTICS_CONFLICT"


def test_a_semantics_require_their_own_provenance_first(root: Path) -> None:
    store = SemanticMetadataStore.initialize(root)
    semantics, provenance = sem()
    with pytest.raises(ss.SemanticMetadataAppendRejected) as info:
        store.append(semantics)                                                           # provenance が無い
    assert info.value.code == "PROVENANCE_MISSING"
    other_semantics, other_provenance = sem(OBS2)
    store.append(other_provenance)
    forged = replace(semantics, mapping_provenance_id=other_provenance.record_id)           # 別の観測の provenance を指す
    with pytest.raises(ss.SemanticMetadataAppendRejected) as info:
        store.append(forged)
    assert info.value.code == "PROVENANCE_MISMATCH"
    assert store.records() == (other_provenance,)


def test_a_malformed_records_and_a2_observations_are_rejected(root: Path) -> None:
    store = SemanticMetadataStore.initialize(root)
    for bad in (OBS, sem()[0].as_dict(), sem()[0].canonical_line(), b"{}", None, {"raw": "x"}):
        with pytest.raises(ss.SemanticMetadataAppendRejected) as info:
            store.append(bad)
        assert info.value.code == "INVALID_TYPE"
    assert store.records() == ()
    with pytest.raises(ss.SemanticMetadataAppendRejected) as info:
        ss.semantic_metadata_path("")
    assert info.value.code == "DATA_ROOT_REQUIRED"
    with pytest.raises(ss.SemanticMetadataMissing):
        SemanticMetadataStore.open(root / "elsewhere")


@pytest.mark.parametrize("tamper,code", [
    (lambda text: text + '{"record_kind":"OBSERVATION_SEMANTICS"}', "TRUNCATED_FINAL_LINE"),
    (lambda text: text + "\n", "BLANK_LINE"),
    (lambda text: text + "not json\n", "INVALID_RECORD"),
    (lambda text: text + text.splitlines()[0] + "\n", "PHYSICAL_DUPLICATE"),
    (lambda text: text.replace('"schema_version":"p8_observation_semantics:0.1.0"', '"schema_version":"x:9.9.9"', 1),
     "INVALID_RECORD"),
    (lambda text: text.replace("\n", "  \n", 1), "NON_CANONICAL_LINE"),
    (lambda text: text[:-1], "TRUNCATED_FINAL_LINE")])
def test_a_corrupt_or_truncated_journal_fails_closed(root: Path, tamper, code: str) -> None:
    store = SemanticMetadataStore.initialize(root)
    semantics, provenance = sem()
    store.append(provenance)
    store.append(semantics)
    path = root / "screener_intelligence" / "semantic_metadata.jsonl"
    path.write_text(tamper(path.read_text(encoding="utf-8")), encoding="utf-8")
    with pytest.raises(ss.SemanticMetadataCorrupt) as info:
        SemanticMetadataStore.open(root)
    assert info.value.code == code and info.value.line_number >= 1
    with pytest.raises(ss.SemanticMetadataConcurrentModification):
        store.append(sem(OBS2)[1])                                                        # 外部の変更は byte 長で検知
    path.write_bytes(b"\xff\xfe")
    with pytest.raises(ss.SemanticMetadataCorrupt) as info:
        SemanticMetadataStore.open(root)
    assert info.value.code == "INVALID_ENCODING"


def test_a_journal_with_a_conflict_on_disk_is_corruption_not_repair(root: Path) -> None:
    store = SemanticMetadataStore.initialize(root)
    jp, jp_prov = sem(OBS, JP_CONS)
    ifrs, ifrs_prov = sem(OBS, IFRS_CONS)
    store.append(jp_prov)
    store.append(jp)
    path = root / "screener_intelligence" / "semantic_metadata.jsonl"
    with path.open("a", encoding="utf-8") as handle:                                       # store を迂回した書き込み
        handle.write(ifrs_prov.canonical_line())
    with pytest.raises(ss.SemanticMetadataCorrupt) as info:
        SemanticMetadataStore.open(root)
    assert info.value.code == "INVALID_JOURNAL" and info.value.detail == "PROVENANCE_CONFLICT"


def test_a_replay_is_deterministic_and_serialization_canonical(root: Path) -> None:
    store = SemanticMetadataStore.initialize(root)
    for observation in (OBS, OBS2):
        semantics, provenance = sem(observation)
        store.append(provenance)
        store.append(semantics)
    lines = store.canonical_lines()
    other = SemanticMetadataStore.initialize(root.parent / "second")
    for observation in (OBS, OBS2):
        semantics, provenance = sem(observation)
        other.append(provenance)
        other.append(semantics)
    assert other.canonical_lines() == lines                                                # 別の root でも byte 一致
    for line in lines:
        data = json.loads(line)
        assert line == json.dumps(data, sort_keys=True, separators=(",", ":"), ensure_ascii=False) + "\n"
        assert ss.parse_semantic_metadata_line(line).canonical_line() == line
        assert not any(isinstance(v, float) for v in data["payload"].values())
    assert [type(r).__name__ for r in store.records()] == ["SemanticMappingProvenance", "ObservationSemantics"] * 2
    assert ss.AUTHORITY_CLASS == "SEMANTIC_METADATA_RECORD" and ss.STORE_RULES_VERSION.startswith("p8_semantic")


# ================================================================ B 保留の観測の model


def test_b_every_required_reason_exists_and_the_vocabulary_is_closed() -> None:
    required = {"IDENTITY_UNRESOLVED", "ACCOUNTING_STANDARD_UNKNOWN", "ACCOUNTING_STANDARD_UNSUPPORTED",
                "STATEMENT_BASIS_UNKNOWN", "DOCTYPE_UNRECOGNIZED", "CURRENCY_UNSUPPORTED", "CURRENCY_UNKNOWN",
                "PERIOD_UNSUPPORTED", "KNOWLEDGE_TIME_INSUFFICIENT", "SEMANTIC_CHAIN_CONFLICT",
                "PROVIDER_REVISION_CONFLICT", "MAPPING_UNSUPPORTED"}
    members = {member.value for member in HeldReason}
    assert required <= members
    assert members - required == {"DOCTYPE_OUT_OF_SCOPE", "VALUE_UNPARSEABLE", "KNOWLEDGE_TIME_INVALID",
                                  "SEMANTICS_CONFLICT", "TERMS_BOUNDARY"}                  # A3R §7 ・§9 ・§12 が要る分だけ
    for word in ("SEVERITY", "PRIORITY", "RANK", "SCORE", "HIGH", "LOW", "CRITICAL", "BUY", "SELL", "RETRY"):
        assert not any(word in value for value in members), word
    for reason in HeldReason:
        record = held((reason,))
        assert record.reasons == (reason,) and record.record_id.startswith("p8hld_")


def test_b_multiple_reasons_are_canonically_ordered_and_identity_bearing() -> None:
    a = held((HeldReason.PERIOD_UNSUPPORTED, HeldReason.IDENTITY_UNRESOLVED, HeldReason.IDENTITY_UNRESOLVED))
    b = held([HeldReason.IDENTITY_UNRESOLVED, HeldReason.PERIOD_UNSUPPORTED])
    assert a.reasons == (HeldReason.IDENTITY_UNRESOLVED, HeldReason.PERIOD_UNSUPPORTED) and a == b
    assert a.record_id == b.record_id
    assert held((HeldReason.PERIOD_UNSUPPORTED,)).record_id != a.record_id
    with pytest.raises(HeldObservationModelError) as info:
        held(())
    assert info.value.code == "INVALID_REASONS"
    with pytest.raises(HeldObservationModelError):
        held(("IDENTITY_UNRESOLVED",))                                                     # 文字列は語彙ではない


def test_b_identity_references_are_optional_and_validated() -> None:
    unresolved = held((HeldReason.IDENTITY_UNRESOLVED,))
    assert unresolved.issuer_id == "" and unresolved.security_id == ""
    resolved = held((HeldReason.CURRENCY_UNKNOWN,), issuer_id=I1, security_id=IDS.S1.security_id,
                    attempted_field=REV, attempted_statement_basis=CONS)
    assert resolved.issuer_id == I1 and resolved.attempted_field is REV
    assert resolved.record_id != held((HeldReason.CURRENCY_UNKNOWN,)).record_id
    for name, value in (("issuer_id", "issuer-1"), ("security_id", I1), ("attempted_field", "REVENUE"),
                        ("attempted_statement_basis", "CONSOLIDATED"), ("provider", "JQUANTS"),
                        ("schema_family", "JQUANTS_V2_FINS_SUMMARY")):
        with pytest.raises(HeldObservationModelError):
            held((HeldReason.CURRENCY_UNKNOWN,), **{name: value})


def test_b_operational_time_is_caller_supplied_and_aware_only() -> None:
    timed = held((HeldReason.KNOWLEDGE_TIME_INSUFFICIENT,), observed_at=T1)
    assert timed.observed_at == T1 and timed.as_dict()["observed_at"].endswith("+00:00")     # UTC の ISO
    assert timed.record_id != held((HeldReason.KNOWLEDGE_TIME_INSUFFICIENT,)).record_id     # 時刻は identity に入る
    jst = held((HeldReason.KNOWLEDGE_TIME_INSUFFICIENT,), observed_at=T1.astimezone(timezone(timedelta(hours=9))))
    assert jst.record_id == timed.record_id                                                # 同じ瞬間なら同じ id
    with pytest.raises(HeldObservationModelError) as info:
        held((HeldReason.KNOWLEDGE_TIME_INSUFFICIENT,), observed_at=datetime(2026, 6, 30, 12))
    assert info.value.code == "NAIVE_DATETIME"
    with pytest.raises(HeldObservationModelError):
        held((HeldReason.KNOWLEDGE_TIME_INSUFFICIENT,), observed_at="2026-06-30T12:00:00Z")
    assert held((HeldReason.KNOWLEDGE_TIME_INSUFFICIENT,)).observed_at is None              # 省けば無い（時計を読まない）


def test_b_raw_payloads_bodies_and_credentials_cannot_enter_the_record() -> None:
    raw_row = {"DiscDate": "2025-05-12", "Sales": "500000000000", "Code": "00000"}
    for name in ("raw", "payload", "response_body", "api_response", "body", "row"):
        with pytest.raises(TypeError):
            held((HeldReason.MAPPING_UNSUPPORTED,), **{name: raw_row})
    assert not {"raw", "payload", "response_body", "api_response", "body"} & {f.name for f in fields(HeldObservation)}
    for bad in (json.dumps(raw_row), str(raw_row), "a b", "x" * 161, "jq:" + "k" * 170, "http://x/y", "dir/file"):
        with pytest.raises(HeldObservationModelError) as info:
            held((HeldReason.MAPPING_UNSUPPORTED,), provider_record_ref=bad)
        assert info.value.code == "INVALID_PROVIDER_RECORD_REF", bad
    for bad in (b"\x00" * 64, json.dumps(raw_row).encode("utf-8"), "zz" * 32, "ab" * 31, DIGEST.upper()):
        with pytest.raises(HeldObservationModelError) as info:
            held((HeldReason.MAPPING_UNSUPPORTED,), provider_record_digest=bad)
        assert info.value.code == "INVALID_DIGEST"
    for name, value in (("provider_record_ref", "jq:apikey-1"), ("audit_note", "bearer abc"),
                        ("rules_version", "token:1.0.0")):
        with pytest.raises(HeldObservationModelError) as info:
            held((HeldReason.MAPPING_UNSUPPORTED,), **{name: value})
        assert info.value.code == "CREDENTIAL_LIKE_TEXT", name
    with pytest.raises(HeldObservationModelError):
        held((HeldReason.MAPPING_UNSUPPORTED,), audit_note="x" * 161)
    with pytest.raises(HeldObservationModelError):
        held((HeldReason.MAPPING_UNSUPPORTED,), audit_note="line1\nline2")


def test_b_audit_note_is_bounded_and_not_identity_bearing() -> None:
    plain = held((HeldReason.TERMS_BOUNDARY,))
    noted = held((HeldReason.TERMS_BOUNDARY,), audit_note="held pending terms confirmation")
    assert plain.record_id == noted.record_id and plain.canonical_line() != noted.canonical_line()
    assert "audit_note" not in noted.identity_payload() and noted.as_dict()["audit_note"] == noted.audit_note


def test_b_record_round_trips_and_rejects_tampering() -> None:
    record = held((HeldReason.DOCTYPE_UNRECOGNIZED, HeldReason.CURRENCY_UNKNOWN), issuer_id=I1, attempted_field=REV,
                  attempted_statement_basis=NONCONS, observed_at=T1, audit_note="note")
    data = json.loads(record.canonical_line())
    assert HeldObservation.from_dict(data) == record and hs.parse_held_line(record.canonical_line()) == record
    assert record.AUTHORITY_CLASS == "OPERATIONAL_HOLD_RECORD" and data["record_kind"] == "HELD_OBSERVATION"
    for broken, code in (({**data, "record_id": "p8hld_" + "0" * 24}, "ID_MISMATCH"),
                         ({**data, "schema_version": "x:0.0.1"}, "SCHEMA_MISMATCH"),
                         ({**data, "extra": 1}, "UNKNOWN_FIELD"),
                         ({**data, "reasons": ["CURRENCY_UNKNOWN", "DOCTYPE_UNRECOGNIZED"]}, "NON_CANONICAL_REASONS"),
                         ({**data, "reasons": ["SEVERITY_HIGH"]}, "INVALID_VOCABULARY"),
                         ({**data, "observed_at": "2026-06-30 12:00"}, "INVALID_DATETIME"),
                         ({**data, "raw": {}}, "UNKNOWN_FIELD")):
        with pytest.raises(HeldObservationModelError) as info:
            HeldObservation.from_dict(broken)
        assert info.value.code == code, code
    with pytest.raises(FrozenInstanceError):
        record.reasons = ()                                                                 # type: ignore[misc]
    assert not any(isinstance(v, float) for v in data.values())


# ================================================================ C 保留の store


def test_c_append_exact_replay_and_content_conflict(root: Path) -> None:
    store = HeldObservationStore.initialize(root)
    record = held((HeldReason.ACCOUNTING_STANDARD_UNKNOWN,), observed_at=T1)
    assert store.append(record).status is hs.AppendStatus.APPENDED
    assert store.append(record).status is hs.AppendStatus.ALREADY_PRESENT
    assert store.append(held((HeldReason.ACCOUNTING_STANDARD_UNKNOWN,), observed_at=T1)).status is \
        hs.AppendStatus.ALREADY_PRESENT                                                     # 再導出の同じ record
    with pytest.raises(hs.HeldAppendRejected) as info:
        store.append(replace(record, audit_note="different note"))                          # 同じ id ・違う内容
    assert info.value.code == "HELD_CONTENT_CONFLICT"
    assert store.records() == (record,) and store.get(record.record_id) == record
    assert store.counts() == {"ACCOUNTING_STANDARD_UNKNOWN": 1}
    later = held((HeldReason.ACCOUNTING_STANDARD_UNKNOWN,), observed_at=T1 + timedelta(days=1))
    assert store.append(later).status is hs.AppendStatus.APPENDED                           # 別の run は別の record
    assert len(store.records()) == 2 and len(HeldObservationStore.open(root, read_only=True).records()) == 2


def test_c_only_held_observations_are_accepted(root: Path) -> None:
    store = HeldObservationStore.initialize(root)
    semantics, provenance = sem()
    for bad in (OBS, semantics, provenance, held().as_dict(), held().canonical_line(), b"{}", {"raw": "x"}, None):
        with pytest.raises(hs.HeldAppendRejected) as info:
            store.append(bad)
        assert info.value.code == "INVALID_TYPE"
    assert store.records() == ()
    with pytest.raises(hs.HeldAppendRejected):
        HeldObservationStore.open(root, read_only=True).append(held())
    with pytest.raises(hs.HeldStoreMissing):
        HeldObservationStore.open(root / "elsewhere")


@pytest.mark.parametrize("tamper,code", [
    (lambda text: text[:-1], "TRUNCATED_FINAL_LINE"),
    (lambda text: text + "\n", "BLANK_LINE"),
    (lambda text: text + "{}\n", "INVALID_RECORD"),
    (lambda text: text + text, "PHYSICAL_DUPLICATE"),
    (lambda text: text.replace("\n", " \n", 1), "NON_CANONICAL_LINE"),
    (lambda text: text.replace('"record_kind":"HELD_OBSERVATION"', '"record_kind":"OBSERVATION_SEMANTICS"', 1),
     "INVALID_RECORD")])
def test_c_corrupt_or_truncated_journal_fails_closed(root: Path, tamper, code: str) -> None:
    store = HeldObservationStore.initialize(root)
    store.append(held((HeldReason.PERIOD_UNSUPPORTED,)))
    path = root / "screener_intelligence" / "held_observations.jsonl"
    path.write_text(tamper(path.read_text(encoding="utf-8")), encoding="utf-8")
    with pytest.raises(hs.HeldStoreCorrupt) as info:
        HeldObservationStore.open(root)
    assert info.value.code == code and info.value.line_number >= 1
    with pytest.raises(hs.HeldConcurrentModification):
        store.append(held((HeldReason.CURRENCY_UNKNOWN,)))


def test_c_replay_is_deterministic_and_there_is_no_retry_promotion_or_deletion(root: Path) -> None:
    records = [held((r,), observed_at=T1) for r in (HeldReason.IDENTITY_UNRESOLVED, HeldReason.CURRENCY_UNKNOWN)]
    first = HeldObservationStore.initialize(root)
    second = HeldObservationStore.initialize(root.parent / "second")
    for store in (first, second):
        for record in records:
            store.append(record)
    assert first.canonical_lines() == second.canonical_lines() and first.records() == tuple(records)
    for name in dir(HeldObservationStore):
        assert not any(word in name.lower() for word in ("retry", "promote", "release", "delete", "remove", "update",
                                                         "overwrite", "purge", "resolve"))
    for line in first.canonical_lines():
        assert line == json.dumps(json.loads(line), sort_keys=True, separators=(",", ":"), ensure_ascii=False) + "\n"
    assert hs.AUTHORITY_CLASS == "OPERATIONAL_HOLD_RECORD"


# ================================================================ D authority の分離 ・raw の禁止 ・private root


def test_d_neither_store_touches_a2_a1_metrics_or_public_output(root: Path) -> None:
    identity_file = root / "screener_intelligence" / "identity_records.jsonl"
    a2_file = root / "screener_intelligence" / "observation_records.jsonl"
    semantic = SemanticMetadataStore.initialize(root)
    held_store = HeldObservationStore.initialize(root)
    semantics, provenance = sem()
    semantic.append(provenance)
    semantic.append(semantics)
    held_store.append(held())
    assert not identity_file.exists() and not a2_file.exists()                              # A1 ・A2 の file を作らない
    assert sorted(p.name for p in (root / "screener_intelligence").iterdir()) == ["held_observations.jsonl",
                                                                                  "semantic_metadata.jsonl"]
    for name in ("semantic_metadata_store", "held_observation_store", "held_observation_model"):
        source = executable_source(PACKAGE_DIR / f"{name}.py")
        tree = ast.parse((PACKAGE_DIR / f"{name}.py").read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module:
                assert not any(token in node.module for token in (
                    "observation_store", "identity_store", "identity_correction", "fundamental_metrics", "metric_model",
                    "observation_resolver", "themes", "theme_intelligence", "narrative", "pages", "reports", "compass",
                    "market", "jquants")), (name, node.module)
            if isinstance(node, ast.Attribute):
                assert node.attr not in {"now", "utcnow", "today", "urlopen", "unlink", "truncate", "remove",
                                         "replace_file", "rename"}, (name, node.attr)
            if isinstance(node, ast.Constant):
                assert not isinstance(node.value, float)
        for word in ("ObservationStore", "IdentityStore", "ObservationHistory", "IdentityHistory"):
            assert not re.search(rf"(?<![A-Za-z]){word}(?![A-Za-z])", source), (name, word)   # A2 ・A1 の authority
        lowered = source.lower()
        for token in ("rank", "score", "recommend", "theme", "llm", "requests", "socket", "sqlite", "production"):
            assert token not in lowered, (name, token)
        for word in ("raw", "payload", "response_body", "api_response", "body"):              # 欄 ・変数の名前として無い
            assert not re.search(rf"(?<![A-Za-z_]){word}(?![A-Za-z_])", lowered), (name, word)


def test_d_stores_take_an_injected_root_and_never_a_default_or_absolute_user_path(tmp_path: Path) -> None:
    for module in (ss, hs):
        source = (PACKAGE_DIR / f"{module.__name__.rsplit('.', 1)[-1]}.py").read_text(encoding="utf-8")
        assert "data_root()" not in source and "INTELLIGENCE_DATA_ROOT" not in source and "/home/" not in source
        assert "config.yaml" not in source and "Path(\"data\")" not in source
    assert ss.semantic_metadata_path(tmp_path / "r") == \
        tmp_path / "r" / "screener_intelligence" / "semantic_metadata.jsonl"
    assert hs.held_path(tmp_path / "r") == tmp_path / "r" / "screener_intelligence" / "held_observations.jsonl"
    for bad in ("", None, "   "):
        with pytest.raises(ss.SemanticMetadataAppendRejected):
            ss.semantic_metadata_path(bad)
        with pytest.raises(hs.HeldAppendRejected):
            hs.held_path(bad)
    assert not (REPO_ROOT / "data" / "screener_intelligence").exists()                     # repo の data に何も作らない


def test_d_semantic_records_carry_no_provider_values(root: Path) -> None:
    semantics, provenance = sem()
    for record in (semantics, provenance):
        names = set(record.as_dict()["payload"])
        assert not names & {"raw", "payload", "response_body", "api_response", "amount", "value", "sales"}
    assert isinstance(provenance, SemanticMappingProvenance) and isinstance(semantics, ObservationSemantics)
