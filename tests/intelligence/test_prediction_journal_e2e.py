"""Phase 5 P5-1D — Prediction Journal の end-to-end OFFLINE 検証（P5-1 最終 gate）。

凍結 P4 意味論オブジェクト → prediction_ingest → PredictionRecord → PredictionStore.append →
predictions.jsonl → **新しい store による権威 reload** → 元と同一の不変 PredictionRecord、を
1 つの系として証明する。単体テストの重複ではなく、component 横断の保証だけを扱う。

- 入力は P4 自身の凍結 builder（`make_brief_id` / `build_market_signal`）で作る本物の object
- 書き込みは `tmp_path` 隔離 root のみ（production root・研究 root・履歴 journal に触れない）
- 新しい分析・評価・市場観測・TOPIX・較正は一切行わない（journal 検証のみ）
"""
from __future__ import annotations

import dataclasses
import json
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Tuple

import pytest

from src.intelligence.compass.model import Confidence, OutlookDirection, QualityVerdict
from src.intelligence.predictions.prediction_ingest import ingest_prediction, IngestResult
from src.intelligence.predictions.prediction_record import PredictionOrigin, PredictionRecord
from src.intelligence.predictions.prediction_store import (
    SINGLE_WRITER_ONLY,
    AppendStatus,
    ConcurrentModificationDetected,
    PredictionConflict,
    PredictionJournalCorrupt,
    PredictionStore,
    serialize_record,
)
from src.intelligence.reports.market_signal import SignalLevel, build_market_signal
from tests.intelligence.test_p43b2c_production_bundle import EXCLUDED_PACKAGES, runtime_closure
from tests.intelligence.test_prediction_ingest import (
    CUTOFF,
    GENERATED_AT,
    Package,
    brief,
    compass_outlook,
    draft,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
LIVE, REPLAY = PredictionOrigin.LIVE, PredictionOrigin.REPLAY
KINDS = ("available", "neutral", "mixed", "abstained")
STATE_FIELDS = ("available", "level", "confidence", "horizon", "unavailable_reason", "origin")

#: P5-1 三 module を import したときに読み込まれてよい src.intelligence module（実測 13）
ALLOWED_CLOSURE = {
    "src.intelligence", "src.intelligence.compass", "src.intelligence.compass.model",
    "src.intelligence.core", "src.intelligence.core.ids", "src.intelligence.core.time",
    "src.intelligence.predictions", "src.intelligence.predictions.prediction_ingest",
    "src.intelligence.predictions.prediction_record",
    "src.intelligence.predictions.prediction_store",
    "src.intelligence.reports", "src.intelligence.reports.market_signal",
    "src.intelligence.reports.model",
}
FORBIDDEN_CLOSURE_FRAGMENTS = (
    "intelligence.market.", "jquants", "tokyo_calendar", "evaluation", "calibration",
    "delivery", "pages", "render", "notification", "analysis", "investment_journal", "corpus",
    "replay", "decision", "formal_review", "intelligence.context", "intelligence.facts",
    "intelligence.internals", "compass.pipeline", "compass.outlook",
    "compass.evidence_package", "compass.store",
)


# ---------------------------------------------------------------- P4 semantic set（合成・凍結 builder 経由）

@dataclasses.dataclass(frozen=True)
class P4Set:
    brief: object
    signal: object
    draft: object
    package: object

    def ingest(self, store: PredictionStore, origin: PredictionOrigin) -> IngestResult:
        return ingest_prediction(store, brief=self.brief, signal=self.signal,
                                 draft=self.draft, package=self.package, origin=origin)


def p4_set(kind: str = "available", *, session: str = "2026-09-17",
           reference: str = "2026-09-16", generated_at: datetime = GENERATED_AT,
           cutoff: datetime = CUTOFF, tier1_text: str = "one-liner",
           rule_version: str = "outlook:1.0.0") -> P4Set:
    outlooks = {
        "available": compass_outlook(rule_version=rule_version),
        "neutral": compass_outlook(OutlookDirection.RANGE_BOUND, Confidence.LOW,
                                   rule_version=rule_version),
        "mixed": compass_outlook(OutlookDirection.MIXED, Confidence.MEDIUM,
                                 rule_version=rule_version),
        "abstained": None,
    }
    outlook = outlooks[kind]
    sessions = dict(session_date=session, reference_session=reference)
    if outlook is None:
        b = brief(verdict=QualityVerdict.ABSTAINED, abstain_reason="draft_abstained",
                  tier1_text=tier1_text, **sessions)
        d = draft(verdict=QualityVerdict.ABSTAINED, abstain_reason="draft_abstained",
                  outlook=None, generated_at=generated_at, **sessions)
    else:
        b = brief(outlook=outlook, tier1_text=tier1_text, **sessions)
        d = draft(outlook=outlook, generated_at=generated_at, **sessions)
    return P4Set(brief=b, signal=build_market_signal(b), draft=d,
                 package=Package(cutoff=cutoff, **sessions))


def journal(root: Path) -> Path:
    return root / "predictions" / "predictions.jsonl"


def physical_lines(root: Path) -> list:
    raw = journal(root).read_bytes()
    assert raw.endswith(b"\n")
    return raw.split(b"\n")[:-1]


def state_of(record: PredictionRecord) -> Tuple:
    return tuple(getattr(record, f) for f in STATE_FIELDS)


def fresh_reload(root: Path) -> PredictionStore:
    """process 再起動相当: 既存 instance を捨て、JSONL だけから index を再構築する。"""
    return PredictionStore(root)


# ---------------------------------------------------------------- §4 happy path（A–L を 1 本で）

def test_happy_path_end_to_end(tmp_path: Path) -> None:
    root = tmp_path / "root"
    source = p4_set("available")                                       # A
    store = PredictionStore(root)
    result = source.ingest(store, LIVE)                                # B
    original = result.record
    assert result.append.status is AppendStatus.APPENDED               # C
    assert result.append.wrote_line and result.append.line_number == 1
    assert len(physical_lines(root)) == 1                              # D
    canonical_bytes = journal(root).read_bytes()
    assert canonical_bytes == serialize_record(original).encode("utf-8")

    del store                                                          # E
    reopened = fresh_reload(root)                                      # F / G
    assert len(reopened) == 1
    reloaded = reopened.get(original.prediction_id)
    assert reloaded == original                                        # H
    assert reloaded.prediction_id == original.prediction_id            # I
    assert reloaded.as_dict() == original.as_dict()                    # J（provenance / audit 含む全 field）
    assert reloaded.brief_id == source.brief.brief_id
    assert reloaded.signal_id == source.signal.signal_id
    assert reloaded.recorded_at == source.draft.generated_at
    assert reloaded.cutoff == source.package.cutoff
    assert journal(root).read_bytes() == canonical_bytes               # K
    assert serialize_record(reloaded).encode("utf-8") == canonical_bytes

    again = source.ingest(reopened, LIVE)                              # L（ingestion 境界から再投入）
    assert again.append.status is AppendStatus.ALREADY_PRESENT and not again.append.wrote_line
    assert again.record == original
    assert journal(root).read_bytes() == canonical_bytes


# ---------------------------------------------------------------- §5 state coverage

@pytest.mark.parametrize("origin", [LIVE, REPLAY])
@pytest.mark.parametrize("kind", KINDS)
def test_each_state_survives_the_full_path_unchanged(tmp_path: Path, kind: str,
                                                     origin: PredictionOrigin) -> None:
    source = p4_set(kind)
    original = source.ingest(PredictionStore(tmp_path), origin).record
    reloaded = fresh_reload(tmp_path).get(original.prediction_id)
    assert reloaded == original and state_of(reloaded) == state_of(original)
    assert reloaded.origin is origin
    expected = {
        "available": (True, SignalLevel.UPWARD_LEAN, "HIGH", "next_tokyo_session", ""),
        "neutral": (True, SignalLevel.NEUTRAL_RANGE, "LOW", "next_tokyo_session", ""),
        "mixed": (False, None, "MEDIUM", "next_tokyo_session", "direction_mixed"),
        "abstained": (False, None, "", "", "draft_abstained"),
    }[kind]
    assert state_of(reloaded)[:-1] == expected
    assert reloaded.is_abstention is (not expected[0])
    assert (source.signal.available, source.signal.level, source.signal.confidence,
            source.signal.horizon, source.signal.unavailable_reason) == expected


def test_all_states_and_origins_stay_distinguishable_after_restart(tmp_path: Path) -> None:
    store = PredictionStore(tmp_path)
    originals = {}
    for kind in KINDS:
        for origin in (LIVE, REPLAY):
            rec = p4_set(kind).ingest(store, origin).record
            originals[(kind, origin)] = rec
    assert len({r.prediction_id for r in originals.values()}) == 8
    reopened = fresh_reload(tmp_path)
    assert len(reopened) == 8
    for (kind, origin), original in originals.items():
        reloaded = reopened.get(original.prediction_id)
        assert reloaded == original and reloaded.origin is origin
        assert state_of(reloaded) == state_of(original)
    states = {state_of(r)[:-1] for r in reopened.iter_records()}
    assert len(states) == 4                       # 直列化で別の state へ変わっていない


# ---------------------------------------------------------------- §6 multi-record journal

def multi_record_sources() -> list:
    """3 session × 複数 state ＋ 同一 session の別意味論 ＋ REPLAY（追記順 = 物理順の期待値）。"""
    return [
        (p4_set("available", session="2026-09-10", reference="2026-09-09"), LIVE),
        (p4_set("neutral", session="2026-09-10", reference="2026-09-09"), LIVE),   # 同一 session・別意味論
        (p4_set("available", session="2026-09-10", reference="2026-09-09"), REPLAY),
        (p4_set("abstained", session="2026-09-11", reference="2026-09-10"), LIVE),
        (p4_set("mixed", session="2026-09-11", reference="2026-09-10"), LIVE),
        (p4_set("available", session="2026-09-12", reference="2026-09-11"), LIVE),
    ]


def test_multi_record_journal_is_preserved_in_physical_order(tmp_path: Path) -> None:
    store = PredictionStore(tmp_path)
    originals = []
    for source, origin in multi_record_sources():
        result = source.ingest(store, origin)
        assert result.append.status is AppendStatus.APPENDED
        assert result.append.line_number == len(originals) + 1
        originals.append(result.record)
    assert len({r.prediction_id for r in originals}) == 6
    assert len({r.session_date for r in originals}) == 3
    del store

    reopened = fresh_reload(tmp_path)
    assert len(reopened) == 6
    assert list(reopened.iter_records()) == originals
    for original in originals:
        assert reopened.get(original.prediction_id) == original
    same_day = [r for r in reopened.iter_records() if r.session_date == "2026-09-10"]
    assert len(same_day) == 3                                     # date-based overwrite なし
    assert physical_lines(tmp_path) == \
        [serialize_record(r).encode("utf-8").rstrip(b"\n") for r in originals]


# ---------------------------------------------------------------- §7 idempotency through ingestion

def test_idempotency_through_the_ingestion_boundary(tmp_path: Path) -> None:
    source = p4_set("available")
    store = PredictionStore(tmp_path)
    first = source.ingest(store, LIVE)
    assert first.append.status is AppendStatus.APPENDED
    after_first = journal(tmp_path).read_bytes()
    second = source.ingest(store, LIVE)
    assert second.append.status is AppendStatus.ALREADY_PRESENT and not second.append.wrote_line
    assert second.record == first.record
    assert journal(tmp_path).read_bytes() == after_first
    third = source.ingest(fresh_reload(tmp_path), LIVE)              # 再起動後も冪等
    assert third.append.status is AppendStatus.ALREADY_PRESENT
    assert journal(tmp_path).read_bytes() == after_first
    assert len(physical_lines(tmp_path)) == 1


# ---------------------------------------------------------------- §8 conflict through ingestion

@pytest.mark.parametrize("label,variant,expected_fields", [
    ("provenance: another projection", dict(tier1_text="another one-liner"),
     {"brief_id", "signal_id"}),
    ("audit: recorded_at", dict(generated_at=GENERATED_AT + timedelta(minutes=1)),
     {"recorded_at"}),
    ("audit: cutoff", dict(cutoff=CUTOFF - timedelta(minutes=30)), {"cutoff"}),
    ("audit: outlook_rule_version", dict(rule_version="outlook:1.0.1"),
     {"outlook_rule_version"}),
])
def test_conflict_through_the_ingestion_boundary(tmp_path: Path, label: str, variant: dict,
                                                 expected_fields: set) -> None:
    store = PredictionStore(tmp_path)
    original = p4_set("available").ingest(store, LIVE).record
    stored_bytes = journal(tmp_path).read_bytes()
    conflicting = p4_set("available", **variant)
    with pytest.raises(PredictionConflict) as info:
        conflicting.ingest(store, LIVE)
    assert info.value.prediction_id == original.prediction_id
    assert set(info.value.differing_fields) == expected_fields
    assert journal(tmp_path).read_bytes() == stored_bytes            # bytes 不変
    reopened = fresh_reload(tmp_path)                                # 権威 reload は成功
    assert len(reopened) == 1 and len(physical_lines(tmp_path)) == 1
    assert reopened.get(original.prediction_id) == original          # 元の記録は無傷
    with pytest.raises(PredictionConflict):                          # 再起動後も同じ判定
        conflicting.ingest(reopened, LIVE)


# ---------------------------------------------------------------- §9 corruption from a valid journal

def valid_journal(root: Path) -> Tuple[bytes, list]:
    store = PredictionStore(root)
    records = [source.ingest(store, origin).record for source, origin in multi_record_sources()[:3]]
    return journal(root).read_bytes(), records


def canonical(data: dict) -> bytes:
    return (json.dumps(data, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode()


@pytest.mark.parametrize("label,reason", [
    ("malformed JSON", "MALFORMED_JSON"),
    ("truncated final line", "TRUNCATED_FINAL_LINE"),
    ("forged prediction_id", "INVALID_RECORD"),
    ("physical duplicate identical", "PHYSICAL_DUPLICATE_IDENTICAL"),
    ("physical duplicate conflicting", "PHYSICAL_DUPLICATE_CONFLICTING"),
    ("non-canonical line", "NON_CANONICAL_LINE"),
])
def test_corruption_of_a_valid_journal_fails_closed_on_fresh_load(tmp_path: Path, label: str,
                                                                 reason: str) -> None:
    good_bytes, records = valid_journal(tmp_path / "valid")
    lines = good_bytes.split(b"\n")[:-1]
    last = json.loads(lines[-1])
    if reason == "MALFORMED_JSON":
        corrupt = good_bytes + b'{"prediction_id": "pred_' + b"\n"
    elif reason == "TRUNCATED_FINAL_LINE":
        corrupt = good_bytes[: -len(lines[-1]) // 2]
    elif reason == "INVALID_RECORD":
        corrupt = b"\n".join(lines[:-1] + [canonical({**last, "prediction_id": "pred_" + "0" * 24})[:-1]]) + b"\n"
    elif reason == "PHYSICAL_DUPLICATE_IDENTICAL":
        corrupt = good_bytes + lines[0] + b"\n"
    elif reason == "PHYSICAL_DUPLICATE_CONFLICTING":
        conflicting = p4_set("available", session="2026-09-10", reference="2026-09-09",
                             tier1_text="other projection")
        rec = conflicting.ingest(PredictionStore(tmp_path / "scratch"), LIVE).record
        assert rec.prediction_id == records[0].prediction_id and rec != records[0]
        corrupt = good_bytes + serialize_record(rec).encode()
    else:
        pretty = (json.dumps(last, ensure_ascii=False, sort_keys=True) + "\n").encode()
        assert pretty != lines[-1] + b"\n"
        corrupt = b"\n".join(lines[:-1] + [pretty[:-1]]) + b"\n"
    isolated = tmp_path / "isolated" / "predictions"
    isolated.mkdir(parents=True)
    (isolated / "predictions.jsonl").write_bytes(corrupt)
    store = None
    with pytest.raises(PredictionJournalCorrupt) as info:
        store = PredictionStore(tmp_path / "isolated")               # 部分 load なし
    assert store is None and info.value.reason == reason
    assert (isolated / "predictions.jsonl").read_bytes() == corrupt  # 修復しない
    assert len(fresh_reload(tmp_path / "valid")) == 3                # 元の journal は無傷


# ---------------------------------------------------------------- §10 restart / recovery boundary

def test_restart_recovery_boundary_proves_jsonl_is_the_authority(tmp_path: Path) -> None:
    sources = multi_record_sources()[:3]
    store = PredictionStore(tmp_path)
    originals = [source.ingest(store, origin).record for source, origin in sources]
    del store                                                          # in-memory state を捨てる

    restarted = fresh_reload(tmp_path)                                 # JSONL だけから再構築
    assert list(restarted.iter_records()) == originals
    for source, origin in sources:
        again = source.ingest(restarted, origin)
        assert again.append.status is AppendStatus.ALREADY_PRESENT     # 正確な再投入は冪等
    new_source = p4_set("neutral", session="2026-09-12", reference="2026-09-11")
    added = new_source.ingest(restarted, LIVE)
    assert added.append.status is AppendStatus.APPENDED and added.append.line_number == 4
    del restarted

    final = fresh_reload(tmp_path)
    assert len(final) == 4 and list(final.iter_records()) == originals + [added.record]
    assert all(isinstance(r, PredictionRecord) for r in final.iter_records())
    assert final.get(added.record.prediction_id) == added.record


# ---------------------------------------------------------------- §11 single-writer truthfulness

def test_single_writer_detection_still_fails_closed_through_ingestion(tmp_path: Path) -> None:
    assert SINGLE_WRITER_ONLY is True
    active = PredictionStore(tmp_path)
    p4_set("available").ingest(active, LIVE)
    other_writer = PredictionStore(tmp_path)                           # 外部の writer
    p4_set("neutral").ingest(other_writer, LIVE)
    before = journal(tmp_path).read_bytes()
    with pytest.raises(ConcurrentModificationDetected):
        p4_set("abstained").ingest(active, LIVE)                       # 古い index のまま書かない
    assert journal(tmp_path).read_bytes() == before
    assert active.reload() == 2
    assert p4_set("abstained").ingest(active, LIVE).append.line_number == 3
    assert len(fresh_reload(tmp_path)) == 3


# ---------------------------------------------------------------- §12 point-in-time evidence

def test_stored_audit_values_come_from_source_context_not_test_runtime(tmp_path: Path) -> None:
    generated = datetime(2025, 1, 6, 22, 45, tzinfo=timezone.utc)      # 検証時刻から遠い固定値
    cutoff = datetime(2025, 1, 6, 22, 30, tzinfo=timezone.utc)
    source = p4_set("available", session="2025-01-07", reference="2025-01-06",
                    generated_at=generated, cutoff=cutoff, rule_version="outlook:1.0.0")
    original = source.ingest(PredictionStore(tmp_path), LIVE).record
    reloaded = fresh_reload(tmp_path).get(original.prediction_id)
    assert reloaded.recorded_at == source.draft.generated_at == generated
    assert reloaded.cutoff == source.package.cutoff == cutoff
    assert reloaded.principle_refs == tuple(source.brief.tier3.principle_refs) == ("MP-01", "MP-07")
    assert reloaded.market_principle_version == "market_rules:1.0.0"
    assert reloaded.outlook_rule_version == source.draft.outlook.rule_version == "outlook:1.0.0"
    assert (reloaded.brief_id, reloaded.signal_id, reloaded.package_id, reloaded.draft_id) == \
        (source.brief.brief_id, source.signal.signal_id, source.brief.package_id,
         source.brief.draft_id)
    now = datetime.now(timezone.utc)
    assert abs(reloaded.recorded_at - now) > timedelta(days=365)      # datetime.now の代用なし
    text = journal(tmp_path).read_text(encoding="utf-8")
    assert now.strftime("%Y-%m-%dT%H") not in text and now.strftime("%Y-%m-%d") not in text
    assert not any(isinstance(v, datetime) for v in reloaded.identity_payload().values())
    assert "recorded_at" not in reloaded.identity_payload()


# ---------------------------------------------------------------- §13 negative dependency proof

def test_p5_1_runtime_closure_is_independent_of_every_forbidden_subsystem() -> None:
    code = (
        "import sys\n"
        "import src.intelligence.predictions.prediction_ingest\n"
        "import src.intelligence.predictions.prediction_store\n"
        "import src.intelligence.predictions.prediction_record\n"
        "print('\\n'.join(sorted(m for m in sys.modules if m.startswith('src.intelligence'))))\n"
    )
    proc = subprocess.run([sys.executable, "-c", code], cwd=REPO_ROOT, capture_output=True,
                          text=True, check=True, env={"PYTHONPATH": str(REPO_ROOT), "PATH": ""})
    closure = set(proc.stdout.split())
    assert closure == ALLOWED_CLOSURE
    for module in closure:
        for fragment in FORBIDDEN_CLOSURE_FRAGMENTS:
            assert fragment not in module, (module, fragment)
    assert "src.analysis.investment_journal" not in closure


def test_p5_remains_unreachable_from_the_p4_production_entrypoints() -> None:
    assert "predictions" in EXCLUDED_PACKAGES
    production = runtime_closure()
    assert not any("predictions" in module for module in production)
    assert not any(module.startswith("src.intelligence.predictions") for module in production)


def test_no_validation_runner_or_cli_was_added() -> None:
    package = REPO_ROOT / "src" / "intelligence" / "predictions"
    assert sorted(p.name for p in package.glob("*.py")) == [
        "__init__.py", "evaluation_record.py",            # P5-2A（object のみ。runner / CLI ではない）
        "prediction_ingest.py", "prediction_record.py", "prediction_store.py",
        "topix_neutral_band_measure.py", "topix_research_acquire.py",
    ]
    for name in ("prediction_ingest.py", "prediction_record.py", "prediction_store.py"):
        text = (package / name).read_text(encoding="utf-8")
        assert "__main__" not in text and "argparse" not in text
