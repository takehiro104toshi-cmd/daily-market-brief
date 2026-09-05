"""Phase 3.9.4 Replay / Simulation のオフラインテスト（実データ・network・PDF 再読なし）。

snapshot 一貫性 / Context 凍結 / 順序 / 適格性 / prefix view / leakage / identity / mode / events /
metrics / provisional 分類 / stress sanity / queue replay / handoff / storage / determinism / drift /
temp cleanup / 安全境界（AST）/ 禁止 key。合成 production root を corpus_research のヘルパで作る。
"""
from __future__ import annotations

import ast
import copy
import hashlib
import importlib.util
import json
import shutil
import sqlite3
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

import pytest

from src.intelligence.corpus.intake import SOURCE_HISTORICAL_IMPORT
from src.intelligence.corpus.pipeline import ingest_path
from src.intelligence.corpus.store import CorpusStore, corpus_root
from src.intelligence.evaluation.config import load_policies
from src.intelligence.replay import cli as rp_cli
from src.intelligence.replay.config import (
    INSUFFICIENT_HISTORY,
    MODE_FULL,
    MODE_MILESTONE,
    MODE_MILESTONE_AND_TRANSITION,
    MODE_TRANSITION,
    ORDER_CHRONOLOGICAL,
    ORDER_INGESTION,
    OSCILLATING,
    RECENT_TRANSITION,
    STABLE,
    ReplayPolicy,
    load_replay_policy,
    replay_policy_from_mapping,
)
from src.intelligence.replay.errors import (
    ReplayIdentityAmbiguity,
    ReplayInputMutated,
    ReplayLeakageDetected,
    ReplayPolicyError,
    ReplayRebuildMismatch,
    ReplayTempCorrupt,
    ReplayUndatedExceeded,
)
from src.intelligence.replay.evaluate import IdentityRegistry, SnapshotEvaluator
from src.intelligence.replay.events import derive_events
from src.intelligence.replay.manifest import ManifestDocument, build_manifest, detect_input_mutation
from src.intelligence.replay.metrics import all_pattern_metrics, classify, pattern_metrics
from src.intelligence.replay.ordering import canonical_order, coarse_positions, milestone_positions
from src.intelligence.replay.runner import OWNER_MARKER, ReplayRunner
from src.intelligence.replay.snapshot import (
    capture_corpus_snapshot,
    export_context_snapshot,
    live_context_digest,
    live_document_identity,
)
from src.intelligence.replay.store import MANIFEST_FILE, SUMMARY_FILE, TIMELINES_FILE, ReplayStore, replay_root
from src.intelligence.replay.stress import approve_stress, formal_review_input, reject_stress
from src.intelligence.replay.timeline import SECTION_MAIN, SECTION_NOT_SURFACED, rows_digest, semantic_row
from src.intelligence.replay.view import ReplayCorpusView
from src.intelligence.shadow_review.models import find_forbidden_keys

REPO_ROOT = Path(__file__).resolve().parents[2]
PKG = REPO_ROOT / "src" / "intelligence" / "replay"
_spec = importlib.util.spec_from_file_location("_tcr", Path(__file__).with_name("test_corpus_research.py"))
_tcr = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_tcr)
CCFG, DATES, NOW, research_pages, make_pdf, LiveFakeExtractor = (
    _tcr.CCFG, _tcr.DATES, _tcr.NOW, _tcr.research_pages, _tcr.make_pdf, _tcr.LiveFakeExtractor)
EVAL_POLICY, REC_POLICY = load_policies()
CLOCK = lambda: datetime(2026, 9, 5, 0, 0, tzinfo=timezone.utc)   # noqa: E731
SESSION = DATES[0][2]                                              # "2026-06-18"
N_DOCS = 14                                                        # 13 VALID + 1 PARTIAL


# ------------------------------------------------------------------ helpers
def _context_row(context_id: str, session_date: str, known_at: str, status: str = "AVAILABLE") -> tuple:
    return (context_id, "MARKET_TREND", "INDEX", "NIKKEI225", "", "", session_date, known_at, 1,
            "UP", "", "", "", "rule", status, "OK", "BACKGROUND", "1.0.0", "{}", "", known_at, "1.0.0", "")


def add_context_rows(prod: Path, rows) -> None:
    from src.intelligence.context.store import ContextStore

    store = ContextStore(prod)
    try:
        store._conn.executemany("INSERT OR REPLACE INTO contexts VALUES (" + ",".join("?" * 23) + ")", rows)
        store._conn.commit()
    finally:
        store.close()


def build_production(root: Path, n: int = N_DOCS, partial_indexes=(N_DOCS - 1,), context: bool = True,
                     indexes=None) -> Path:
    prod = Path(root) / "prod"
    store = CorpusStore(corpus_root(prod))
    texts = {}
    extractor = LiveFakeExtractor(texts, CCFG.extractor_version)
    try:
        for i in (range(n) if indexes is None else indexes):
            name = f"doc{i:02d}.pdf"
            pages = research_pages(i % len(DATES))
            if i in partial_indexes:
                pages[2] = "short"                                        # LOW_TEXT → PARTIAL（usable・非 eligible）
            texts[name] = pages
            ingest_path(store, make_pdf(prod / "src" / name, name), config=CCFG, extractor=extractor,
                        now=NOW, source_type=SOURCE_HISTORICAL_IMPORT)
    finally:
        store.close()
    if context:
        add_context_rows(prod, [_context_row("ctx_a", SESSION, "2026-06-17T20:00:00+00:00"),
                                _context_row("ctx_b", DATES[1][2], "2026-06-18T20:00:00+00:00")])
    return prod


def policy_for(tmp: Path, **overrides) -> ReplayPolicy:
    return ReplayPolicy(temp_workspace=str(Path(tmp) / "ws"), **overrides)


def run_replay(prod: Path, tmp: Path, *, mode: str = "", ordering: str = "", clock=CLOCK, retain=None, **pol):
    runner = ReplayRunner(prod, replay_policy=policy_for(tmp, **pol), clock=clock, mode=mode, ordering=ordering,
                          retain_temp=retain)
    result = runner.run()
    store = ReplayStore(replay_root(prod))
    return {"result": result, "runner": runner, "store": store,
            "manifest": store.read_json(result["run_id"], MANIFEST_FILE),
            "summary": store.read_json(result["run_id"], SUMMARY_FILE),
            "rows": store.read_jsonl(result["run_id"], TIMELINES_FILE),
            "events": store.read_jsonl(result["run_id"], "transition_events.jsonl"),
            "snapshots": store.read_jsonl(result["run_id"], "snapshots.jsonl")}


def prod_sha(prod: Path) -> str:
    return hashlib.sha256((corpus_root(prod) / "index" / "corpus.sqlite3").read_bytes()).hexdigest()


def mdoc(i: int, date: str, seq: int = 1, quality: str = "VALID", status: str = "ANALYZED",
         received: str = "2026-09-01T00:00:00+00:00") -> ManifestDocument:
    return ManifestDocument(document_id=f"d{i:02d}", sha256=f"{i:064x}", document_date=date, date_sequence=seq,
                            received_at=received, quality=quality, eligible=quality == "VALID", status=status)


def row(pid: str, position: int, rec: str, life: str = "OBSERVED", cons: str = "MEDIUM", section: str = SECTION_NOT_SURFACED,
        rank=None, date: str = "2026-07-01", first_seen: str = "2026-04-01", span: int = 70, months: int = 3,
        support: int = 4, cross: str = "MEDIUM", time_: str = "HIGH") -> dict:
    return {"pattern_id": pid, "pattern_type": "STATE_OUTLOOK", "position": position, "recommendation": rec,
            "lifecycle_status": life, "queue_section": section, "queue_rank": rank, "latest_document_date": date,
            "snapshot_id": f"crs_{position}", "pattern_first_seen": first_seen, "span_days": span,
            "distinct_calendar_months": months, "eligible_support": support, "dna_classification": "NEW", "dna_conflicts": 0,
            "axis_states": {"evidence_consistency": cons, "cross_regime": cross, "time_stability": time_},
            "axis_applicability": {"cross_regime": "APPLICABLE"}, "axis_reasons": {"evidence_consistency": "X"},
            "contradiction": {}}


@pytest.fixture(scope="module")
def base_prod(tmp_path_factory) -> Path:
    return build_production(tmp_path_factory.mktemp("base"))


@pytest.fixture()
def prod(base_prod, tmp_path) -> Path:
    dest = tmp_path / "prod"
    shutil.copytree(base_prod, dest)
    return dest


# ================================================================== policy
def test_policy_digest_deterministic_and_config_matches_default():
    assert load_replay_policy().digest() == ReplayPolicy().digest() == ReplayPolicy().digest()
    assert load_replay_policy().stability_calibration_state == "PROVISIONAL_CALIBRATION_ONLY"


def test_policy_fail_closed_rules():
    with pytest.raises(ReplayPolicyError):
        replay_policy_from_mapping({"default_mode": "FULL_REPLAY"})                # FULL は既定にできない
    with pytest.raises(ReplayPolicyError):
        replay_policy_from_mapping({"stability": {"unit": "snapshots"}})           # snapshot 数は禁止
    with pytest.raises(ReplayPolicyError):
        replay_policy_from_mapping({"identity_ambiguity_tolerance": 1})
    with pytest.raises(ReplayPolicyError):
        replay_policy_from_mapping({"default_ordering": "RANDOM"})
    with pytest.raises(ReplayPolicyError):
        replay_policy_from_mapping({"milestone_points": [50, 10]})


def test_same_version_changed_replay_policy_fails_closed(prod, tmp_path):
    run_replay(prod, tmp_path)
    drifted = replay_policy_from_mapping({"policy_version": "1.0.0", "transition_resolution": 3,
                                          "temp_workspace": str(tmp_path / "ws2")})
    with pytest.raises(ReplayPolicyError):
        ReplayRunner(prod, replay_policy=drifted, clock=CLOCK).run()


# ================================================================== 1-4 snapshots
def test_sqlite_backup_is_consistent_even_with_open_writer(prod, tmp_path):
    db = corpus_root(prod) / "index" / "corpus.sqlite3"
    writer = sqlite3.connect(db)
    writer.execute("BEGIN")
    writer.execute("INSERT INTO status_events VALUES ('ev_x','ghost','RECEIVED','','2026-09-05T00:00:00+00:00','1')")
    try:                                                                      # 未 commit の書き手がいる最中に backup
        info = capture_corpus_snapshot(corpus_root(prod), tmp_path / "snap")
    finally:
        writer.rollback()
        writer.close()
    snap = sqlite3.connect(tmp_path / "snap" / "index" / "corpus.sqlite3")
    assert snap.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
    assert snap.execute("SELECT COUNT(*) FROM status_events WHERE document_id='ghost'").fetchone()[0] == 0
    assert info.tables["documents"] == N_DOCS
    snap.close()


def test_live_corpus_writes_after_backup_do_not_enter_snapshot(prod, tmp_path):
    capture_corpus_snapshot(corpus_root(prod), tmp_path / "snap")
    store = CorpusStore(corpus_root(prod))
    texts = {"late.pdf": research_pages(4)}
    ingest_path(store, make_pdf(prod / "src" / "late.pdf", "late.pdf"), config=CCFG,
                extractor=LiveFakeExtractor(texts, CCFG.extractor_version), now=NOW, source_type=SOURCE_HISTORICAL_IMPORT)
    store.close()
    assert build_manifest(tmp_path / "snap").captured_documents == N_DOCS
    assert build_manifest(corpus_root(prod)).captured_documents == N_DOCS + 1          # production は進んでいる


def test_context_snapshot_is_immutable_after_capture(prod, tmp_path):
    snap = export_context_snapshot(prod, tmp_path / "ctx", DATES[-1][2])
    before = snap.context_manifest_digest
    rows_before = [r["context_id"] for r in snap.connector()._context_rows(SESSION)]
    add_context_rows(prod, [_context_row("ctx_late", SESSION, "2026-06-17T21:00:00+00:00")])
    assert [r["context_id"] for r in snap.connector()._context_rows(SESSION)] == rows_before      # 凍結
    assert live_context_digest(prod, DATES[-1][2]) != before                                       # live は変わった
    assert snap.context_manifest_digest == before


def test_future_session_context_rows_do_not_change_digest(prod, tmp_path):
    before = export_context_snapshot(prod, tmp_path / "c1", DATES[-1][2]).context_manifest_digest
    add_context_rows(prod, [_context_row("ctx_future", "2027-01-05", "2027-01-04T20:00:00+00:00")])
    assert export_context_snapshot(prod, tmp_path / "c2", DATES[-1][2]).context_manifest_digest == before


# ================================================================== 5-11 ordering / eligibility
def test_chronological_ordering_deterministic_with_same_date_tiebreak():
    docs = [mdoc(3, "2026-06-20"), mdoc(1, "2026-06-18", seq=2), mdoc(2, "2026-06-18", seq=1), mdoc(4, "2026-06-19")]
    from src.intelligence.replay.manifest import InputManifest

    manifest = InputManifest(documents=tuple(docs), duplicates_summary={}, excluded=(), input_manifest_digest="x",
                             captured_eligible=4, captured_usable=4, captured_documents=4, latest_document_date="2026-06-20")
    order = canonical_order(manifest, ORDER_CHRONOLOGICAL, ReplayPolicy())
    assert [o.document.document_id for o in order.items] == ["d02", "d01", "d04", "d03"]
    assert [o.eligible_position for o in order.items] == [1, 2, 3, 4]


def test_ingestion_ordering_deterministic():
    from src.intelligence.replay.manifest import InputManifest

    docs = [mdoc(1, "2026-06-18", received="2026-09-02T00:00:00+00:00"),
            mdoc(2, "2026-06-01", received="2026-09-03T00:00:00+00:00"),
            mdoc(3, "", received="2026-09-01T00:00:00+00:00")]                # undated も INGESTION には入る
    manifest = InputManifest(documents=tuple(docs), duplicates_summary={}, excluded=(), input_manifest_digest="x",
                             captured_eligible=3, captured_usable=3, captured_documents=3, latest_document_date="2026-06-18")
    order = canonical_order(manifest, ORDER_INGESTION, ReplayPolicy())
    assert [o.document.document_id for o in order.items] == ["d03", "d01", "d02"]


def test_undated_excluded_in_chronological_and_threshold_fails_closed():
    from src.intelligence.replay.manifest import InputManifest

    docs = [mdoc(i, "2026-06-%02d" % (10 + i)) for i in range(19)] + [mdoc(99, "")]
    manifest = InputManifest(documents=tuple(docs), duplicates_summary={}, excluded=(), input_manifest_digest="x",
                             captured_eligible=20, captured_usable=20, captured_documents=20, latest_document_date="2026-06-28")
    order = canonical_order(manifest, ORDER_CHRONOLOGICAL, ReplayPolicy())          # 1/20 = 0.05 は許容
    assert order.excluded_undated == ("d99",) and len(order.items) == 19
    strict = replay_policy_from_mapping({"max_undated_ratio": "0.01"})
    with pytest.raises(ReplayUndatedExceeded):
        canonical_order(manifest, ORDER_CHRONOLOGICAL, strict)


def test_eligibility_semantics_valid_partial_and_duplicates(prod, tmp_path):
    store = CorpusStore(corpus_root(prod))
    texts = {"dup.pdf": research_pages(0)}                                        # doc00 と同一 bytes → duplicate
    ingest_path(store, make_pdf(prod / "src" / "dup.pdf", "doc00.pdf"), config=CCFG,
                extractor=LiveFakeExtractor(texts, CCFG.extractor_version), now=NOW, source_type=SOURCE_HISTORICAL_IMPORT)
    store.close()
    capture_corpus_snapshot(corpus_root(prod), tmp_path / "snap")
    manifest = build_manifest(tmp_path / "snap")
    assert manifest.captured_documents == N_DOCS                                   # duplicate は文書ではない
    assert manifest.duplicates_summary["count"] == 1
    partial = [d for d in manifest.documents if d.quality == "PARTIAL"]
    assert len(partial) == 1 and partial[0].usable and not partial[0].eligible
    assert manifest.captured_usable == N_DOCS and manifest.captured_eligible == N_DOCS - 1


# ================================================================== 12-15 view / leakage
def test_prefix_external_access_is_blocked(prod, tmp_path):
    capture_corpus_snapshot(corpus_root(prod), tmp_path / "snap")
    store = CorpusStore(tmp_path / "snap")
    ids = [d.document_id for d in store.documents()]
    view = ReplayCorpusView(store, ids[:3])
    try:
        assert [d.document_id for d in view.documents()] == ids[:3]
        for api in ("document", "current_analysis", "artifacts_for", "quality_for", "coverage_for",
                    "temporal_for", "alignments_for", "analyses_for", "status_history", "current_status"):
            with pytest.raises(ReplayLeakageDetected):
                getattr(view, api)(ids[5])
        assert view.counts()["documents"] == 3
        assert not any(hasattr(view, w) for w in ("add_document", "add_quality", "add_status_event", "update_document"))
    finally:
        store.close()


def test_future_support_document_leakage_detected(prod, tmp_path, monkeypatch):
    from src.intelligence.evaluation.engine import EvaluationEngine

    real = EvaluationEngine.load_inputs

    def leaking(self, pattern_version="1.0.0"):
        data = real(self, pattern_version)
        for rec in data["patterns"].values():
            rec["supporting_document_ids"] = list(rec.get("supporting_document_ids") or []) + ["ghost_future_doc"]
            break
        return data

    monkeypatch.setattr(EvaluationEngine, "load_inputs", leaking)
    with pytest.raises(ReplayLeakageDetected):
        run_replay(prod, tmp_path)


def test_lifecycle_and_support_never_exceed_prefix(prod, tmp_path):
    out = run_replay(prod, tmp_path)
    for r in out["rows"]:
        assert r["support_count"] <= r["usable_position"]
        assert r["eligible_support"] <= r["position"]
        assert r["latest_document_date"] and r["pattern_first_seen"] <= r["latest_document_date"]


def test_prefix_closure_no_future_contradiction_or_lifecycle_leakage(prod, tmp_path):
    """position p の snapshot は、corpus が p 件で終わっていた世界と semantic に同一（矛盾・lifecycle・支持の将来漏洩なし）。"""
    full = run_replay(prod, tmp_path / "full")
    ordered = sorted(full["manifest"]["documents"], key=lambda d: (d["document_date"], d["date_sequence"], d["document_id"]))
    prefix, eligible = [], 0
    for d in ordered:                                                      # 10 件目の eligible までの chronological prefix
        prefix.append(d["sha256"]); eligible += int(bool(d["eligible"]))
        if eligible == 10:
            break
    by_sha = {hashlib.sha256((prod / "src" / f"doc{i:02d}.pdf").read_bytes()).hexdigest(): i for i in range(N_DOCS)}
    indexes = sorted(by_sha[sha] for sha in prefix)
    assert indexes != list(range(10))                                      # 日付が循環するので単純な先頭 10 件ではない
    truncated = build_production(tmp_path / "trunc", indexes=indexes)
    short = run_replay(truncated, tmp_path / "short")
    full_10 = next(s for s in full["snapshots"] if s["position"] == 10)
    short_10 = next(s for s in short["snapshots"] if s["position"] == 10)
    assert full_10["research_digest"] == short_10["research_digest"]      # Phase 3.8 状態が prefix だけで決まる
    assert full_10["snapshot_digest"] != short_10["snapshot_digest"]      # snapshot_id は run の入力宇宙に束縛される

    def strip(r):
        return {k: v for k, v in semantic_row(r).items() if k != "snapshot_id"}

    rows_full = [strip(r) for r in full["rows"] if r["position"] == 10]
    rows_short = [strip(r) for r in short["rows"] if r["position"] == 10]
    assert sorted(map(json.dumps, rows_full)) == sorted(map(json.dumps, rows_short))
    assert any(r["contradiction"] for r in rows_full)                        # 矛盾要約は存在し、prefix 内だけで決まる


def test_replay_package_never_reads_production_research_or_evaluation():
    for py in sorted(PKG.glob("*.py")):
        tree = ast.parse(py.read_text(encoding="utf-8"))
        names = {a.name for node in ast.walk(tree) if isinstance(node, ast.ImportFrom) for a in node.names}
        assert "research_root" not in names and "evaluation_root" not in names, py.name


# ================================================================== 16-18 rebuild / identity
def test_incremental_equals_full_rebuild_at_milestones(prod, tmp_path):
    out = run_replay(prod, tmp_path)
    eq = out["summary"]["rebuild_equivalence"]
    assert [e["position"] for e in eq] == [10, N_DOCS - 1] and all(e["equal"] for e in eq)


def test_rebuild_mismatch_fails_closed(prod, tmp_path, monkeypatch):
    from src.intelligence.corpus_research.engine import ResearchEngine

    monkeypatch.setattr(ResearchEngine, "equivalence", lambda self, other: {"equal": False, "differing_sections": ["patterns"]})
    with pytest.raises(ReplayRebuildMismatch):
        run_replay(prod, tmp_path)


def test_pattern_identity_stable_across_snapshots(prod, tmp_path):
    out = run_replay(prod, tmp_path)
    digests = {}
    for r in out["rows"]:
        digests.setdefault(r["pattern_id"], set()).add(r["components_digest"])
    assert all(len(v) == 1 for v in digests.values()) and len(digests) >= 5


def test_identity_ambiguity_fails_closed():
    reg = IdentityRegistry()
    reg.check("cpt_x", {"pattern_type": "FULL", "evidence": ["A"]})
    reg.check("cpt_x", {"pattern_type": "FULL", "evidence": ["A"]})
    with pytest.raises(ReplayIdentityAmbiguity):
        reg.check("cpt_x", {"pattern_type": "FULL", "evidence": ["B"]})


# ================================================================== 19-22 modes
def test_milestone_positions_and_mode(prod, tmp_path):
    assert milestone_positions(ReplayPolicy(), 13) == [10, 13]
    assert milestone_positions(ReplayPolicy(), 100) == [10, 30, 50, 100]
    out = run_replay(prod, tmp_path, mode=MODE_MILESTONE)
    assert out["summary"]["positions"] == [10, N_DOCS - 1] and out["summary"]["refined_intervals"] == []


def test_transition_coarse_positions():
    assert coarse_positions(ReplayPolicy(), MODE_TRANSITION, 13) == [5, 10, 13]
    assert coarse_positions(ReplayPolicy(), MODE_MILESTONE_AND_TRANSITION, 23) == [5, 10, 15, 20, 23]
    with pytest.raises(ReplayPolicyError):
        coarse_positions(ReplayPolicy(), MODE_FULL, 13)                          # 明示有効化なしの FULL は拒否


def test_transition_refinement_adds_intermediate_positions(prod, tmp_path):
    out = run_replay(prod, tmp_path, mode=MODE_MILESTONE_AND_TRANSITION)
    positions = out["summary"]["positions"]
    assert 5 in positions and 10 in positions and (N_DOCS - 1) in positions
    refined = out["summary"]["refined_intervals"]
    assert refined and all(p in positions for r in refined for p in range(r["from"] + 1, r["to"]))


def test_full_replay_every_eligible_increment(prod, tmp_path):
    out = run_replay(prod, tmp_path, mode=MODE_FULL, full_replay_enabled=True)
    assert out["summary"]["positions"] == list(range(1, N_DOCS))
    assert out["summary"]["refined_intervals"] == []


# ================================================================== 23-27 events / metrics
def test_first_events_only_once_and_changes_recorded():
    rows = [row("p", 5, "KEEP_REVIEWING", "OBSERVED"), row("p", 10, "REVIEW_RECOMMENDED", "NEW_PATTERN_CANDIDATE"),
            row("p", 15, "REVIEW_RECOMMENDED", "REVIEW_CANDIDATE", cons="LOW"),
            row("p", 20, "REVIEW_RECOMMENDED", "REVIEW_CANDIDATE", cons="LOW", section=SECTION_MAIN, rank=3)]
    events = derive_events("run", rows)
    kinds = [e["event"] for e in events]
    assert kinds.count("FIRST_OBSERVED") == 1 and kinds.count("FIRST_REVIEW_RECOMMENDED") == 1
    assert kinds.count("FIRST_NEW_PATTERN_CANDIDATE") == 1 and kinds.count("FIRST_REVIEW_CANDIDATE") == 1
    assert kinds.count("RECOMMENDATION_CHANGED") == 1 and kinds.count("LIFECYCLE_CHANGED") == 2
    assert kinds.count("CONSISTENCY_CHANGED") == 1 and kinds.count("FIRST_SURFACED_IN_MAIN") == 1
    assert next(e for e in events if e["event"] == "RECOMMENDATION_CHANGED")["from_state"] == "KEEP_REVIEWING"


def test_reversal_counting_and_raw_metrics():
    rows = [row("p", 5, "KEEP_REVIEWING"), row("p", 10, "REVIEW_RECOMMENDED"), row("p", 15, "KEEP_REVIEWING"),
            row("p", 20, "REVIEW_RECOMMENDED"), row("p", 25, "APPROVE_RECOMMENDED", cons="HIGH", section=SECTION_MAIN, rank=1),
            row("p", 30, "APPROVE_RECOMMENDED", cons="HIGH")]
    m = pattern_metrics(rows, ReplayPolicy(), final_position=30)
    assert m["recommendation_transition_count"] == 4 and m["recommendation_reversal_count"] == 2
    assert m["first_review_recommended_position"] == 10 and m["first_approve_recommended_position"] == 25
    assert m["documents_to_approve_recommended"] == 25 and m["eligible_documents_in_current_state"] == 5
    assert m["approve_persistence_ratio"] == "1.0000" and m["worst_consistency_observed"] == "MEDIUM"
    assert m["positions_with_time_high"] == 6 and m["main_appearance_count"] == 1
    assert m["first_surfaced_in_main_position"] == 25 and m["time_to_approve_recommended_days"] == 91


def test_provisional_classification_marked_and_units_are_eligible_documents():
    pol = ReplayPolicy()
    base = {"recommendation_reversal_count": 0, "eligible_documents_in_current_state": 20,
            "history_eligible_documents": 40, "state_persistence_ratio": "1.0000"}
    c = classify(base, pol)
    assert c["stability_class"] == STABLE and c["provisional"] is True and c["unit"] == "eligible_documents"
    assert classify({**base, "recommendation_reversal_count": 2}, pol)["stability_class"] == OSCILLATING
    assert classify({**base, "history_eligible_documents": 5}, pol)["stability_class"] == INSUFFICIENT_HISTORY
    assert classify({**base, "eligible_documents_in_current_state": 0}, pol)["stability_class"] == RECENT_TRANSITION


# ================================================================== 28-29 sanity
class _Fake:
    epol, rpol = EVAL_POLICY, REC_POLICY


def test_impossible_early_approve_fails_closed():
    good = row("p", 30, "APPROVE_RECOMMENDED", span=70, months=3)
    SnapshotEvaluator._sanity(_Fake(), good)
    with pytest.raises(ReplayLeakageDetected):
        SnapshotEvaluator._sanity(_Fake(), row("p", 30, "APPROVE_RECOMMENDED", span=10, months=1))
    with pytest.raises(ReplayLeakageDetected):
        SnapshotEvaluator._sanity(_Fake(), row("p", 30, "APPROVE_RECOMMENDED", first_seen="2026-06-25", date="2026-07-01"))


def test_impossible_early_reject_fails_closed():
    SnapshotEvaluator._sanity(_Fake(), row("p", 30, "REJECT_RECOMMENDED", support=4))
    with pytest.raises(ReplayLeakageDetected):
        SnapshotEvaluator._sanity(_Fake(), row("p", 30, "REJECT_RECOMMENDED", support=2))


# ================================================================== 30-32 queue replay / handoff
def test_historical_queue_uses_empty_event_store_and_no_fabricated_history(prod, tmp_path):
    out = run_replay(prod, tmp_path, retain=True)
    temp = out["runner"].temp_root
    assert not (temp / "shadow_review" / "review_events.jsonl").exists()
    sections = {r["queue_section"] for r in out["rows"]}
    assert sections <= {"MAIN", "ADVERSE_OVERFLOW", "BACKLOG", "NOT_SURFACED"}
    for item in out["summary"]["formal_review_input"]["items"]:
        assert item["production_reference"]["shadow_review_events"] == 0
    blob = json.dumps(out["summary"], ensure_ascii=False)
    assert "review_outcome" not in blob and "AGREE" not in blob
    out["runner"].retain_temp = False
    out["runner"].cleanup_temp()


def test_stress_sections_and_handoff_from_synthetic_rows():
    rows = [row("a", 40, "REVIEW_RECOMMENDED"), row("a", 60, "APPROVE_RECOMMENDED", cons="HIGH", section=SECTION_MAIN, rank=2),
            row("a", 80, "REVIEW_RECOMMENDED"), row("a", 110, "APPROVE_RECOMMENDED", cons="HIGH"),
            row("b", 40, "REVIEW_RECOMMENDED"), row("b", 60, "REVIEW_RECOMMENDED", cons="LOW"),
            row("b", 80, "REJECT_RECOMMENDED", cons="LOW", support=6), row("b", 110, "REJECT_RECOMMENDED", cons="LOW", support=7)]
    metrics = all_pattern_metrics(rows, ReplayPolicy(), 110)
    ap = approve_stress(rows, metrics, 110)
    assert ap["count"] == 1 and ap["items"][0]["recommendation_at"]["50"]["recommendation"] == "REVIEW_RECOMMENDED"
    assert ap["items"][0]["recommendation_at"]["75"]["recommendation"] == "APPROVE_RECOMMENDED"
    assert ap["items"][0]["reversions"] == {"APPROVE_RECOMMENDED->REVIEW_RECOMMENDED": 1}
    assert ap["items"][0]["appeared_only_after_100"] is False
    rj = reject_stress(rows, metrics)
    assert rj["count"] == 1 and rj["items"][0]["first_material_contradiction_position"] == 60
    assert rj["items"][0]["was_review_before_reject"] is True and rj["items"][0]["first_reject_position"] == 80
    fri = formal_review_input(rows, metrics, {"a": {"decision_state": ""}, "b": {"decision_state": ""}})
    assert fri["count"] == 2 and all(i["provisional"] for i in fri["items"])
    assert any("never converts to APPROVED" in b for b in fri["boundaries"])


def test_decision_and_review_apis_are_read_only_imports():
    write_apis = {"DecisionService", "DecisionRequest"}
    for py in sorted(PKG.glob("*.py")):
        tree = ast.parse(py.read_text(encoding="utf-8"))
        imported = {a.name for node in ast.walk(tree) if isinstance(node, (ast.Import, ast.ImportFrom)) for a in node.names}
        assert not (imported & write_apis), py.name
        from_decision = {a.name for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)
                         and "decision" in (node.module or "") for a in node.names}
        if from_decision:
            assert py.name == "stress.py" and from_decision <= {"DecisionStore", "decisions_root", "derive_current_states"}
        text = py.read_text(encoding="utf-8")
        assert ".append(" not in text.replace("events.append", "").replace("items.append", "").replace(
            "changes.append", "").replace("excluded.append", "").replace("docs.append", "").replace(
            "rows.append", "").replace("pending.append", "").replace("equivalence.append", "").replace(
            "refined_intervals.append", "").replace("candidates.append", "").replace("recovery.append", "") \
            or "store.append(" not in text, py.name          # decision / review event store への append 呼び出しなし


# ================================================================== 33-37 safety
def test_replay_writes_nothing_to_production(prod, tmp_path):
    dna = [REPO_ROOT / "src" / "intelligence" / "compass" / "market_principles.py",
           REPO_ROOT / "knowledge" / "compass_dna" / "market_rules.yaml"]
    dna_before = [hashlib.sha256(p.read_bytes()).hexdigest() for p in dna]
    corpus_before = prod_sha(prod)
    out = run_replay(prod, tmp_path)
    assert prod_sha(prod) == corpus_before                                     # corpus DB は byte 単位で不変
    assert [hashlib.sha256(p.read_bytes()).hexdigest() for p in dna] == dna_before
    for forbidden in ("compass_decisions", "compass_shadow_review", "compass_research", "compass_evaluation"):
        assert not (prod / forbidden).exists(), forbidden
    assert (prod / "compass_replay" / "runs" / out["result"]["run_id"] / SUMMARY_FILE).is_file()


def test_replay_never_writes_decision_or_human_review_event(prod, tmp_path):
    from src.intelligence.decision.store import DecisionStore, decisions_root
    from src.intelligence.shadow_review.events import ShadowReviewEventStore, shadow_review_root

    dec_root, rev_root = decisions_root(prod), shadow_review_root(prod)
    assert not dec_root.exists() and not rev_root.exists()
    rev_root.mkdir(parents=True)
    ShadowReviewEventStore(rev_root).path.write_text("", encoding="utf-8")   # 空の本番 event store（存在するが 0 件）
    before_rev = ShadowReviewEventStore(rev_root).path.read_bytes()
    run_replay(prod, tmp_path)
    assert ShadowReviewEventStore(rev_root).path.read_bytes() == before_rev  # 人間レビュー履歴は 1 byte も増えない
    assert not DecisionStore(dec_root).exists()                              # Decision record は書かれない
    assert list((rev_root).iterdir()) == [ShadowReviewEventStore(rev_root).path]


def test_replay_package_has_no_pdf_reading_path():
    banned = ("pypdf", "PypdfExtractor", "ingest_path", "extract_text", "TextLayerExtractor", "ocr")
    for py in sorted(PKG.glob("*.py")):
        text = py.read_text(encoding="utf-8")
        for token in banned:
            assert token not in text, (py.name, token)
        tree = ast.parse(text)
        modules = {node.module or "" for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)}
        assert not any(m.endswith(("corpus.pipeline", "corpus.extraction", "corpus.inbox")) for m in modules), py.name


# ================================================================== 38-43 determinism / drift
def test_manifest_snapshot_and_run_digests_deterministic_across_clocks(prod, tmp_path):
    a = run_replay(prod, tmp_path / "a")
    b = run_replay(prod, tmp_path / "b", clock=lambda: datetime(2026, 9, 6, 12, 0, tzinfo=timezone.utc))
    assert a["result"]["run_id"] != b["result"]["run_id"]                      # 時刻は id にだけ現れる
    assert a["manifest"]["input_manifest_digest"] == b["manifest"]["input_manifest_digest"]
    assert a["manifest"]["context_manifest_digest"] == b["manifest"]["context_manifest_digest"]
    assert [s["snapshot_digest"] for s in a["snapshots"]] == [s["snapshot_digest"] for s in b["snapshots"]]
    assert a["result"]["run_digest"] == b["result"]["run_digest"]
    assert a["summary"]["run_created_at"] != b["summary"]["run_created_at"]   # 生成時刻は残るが digest に入らない


def test_generated_timestamps_excluded_from_semantic_digests(prod, tmp_path):
    out = run_replay(prod, tmp_path)
    for r in out["rows"]:
        assert not any(k.endswith(("_at", "generated")) or k == "run_created_at" for k in r), sorted(r)
    a = row("p", 5, "KEEP_REVIEWING"); a["run_id"] = "run_a"
    b = dict(a); b["run_id"] = "run_b"
    assert rows_digest([a]) == rows_digest([b])                                # run 固有値は semantic digest 外
    assert out["result"]["run_digest"] == out["summary"]["run_digest"]
    assert "run_created_at" in out["summary"] and "run_created_at" in out["manifest"]
    for s in out["snapshots"]:
        assert s["snapshot_digest"] == rows_digest([r for r in out["rows"] if r["position"] == s["position"]])


def test_live_incoming_documents_during_run_do_not_alter_run(prod, tmp_path, monkeypatch):
    from src.intelligence.replay import runner as runner_mod

    real = runner_mod.capture_corpus_snapshot

    def capture_then_intake(src_root, dest_root):
        info = real(src_root, dest_root)
        store = CorpusStore(corpus_root(prod))                                 # 捕捉直後に production へ新文書
        texts = {"late.pdf": research_pages(5)}
        ingest_path(store, make_pdf(prod / "src" / "late.pdf", "late.pdf"), config=CCFG,
                    extractor=LiveFakeExtractor(texts, CCFG.extractor_version), now=NOW, source_type=SOURCE_HISTORICAL_IMPORT)
        store.close()
        return info

    monkeypatch.setattr(runner_mod, "capture_corpus_snapshot", capture_then_intake)
    out = run_replay(prod, tmp_path)
    assert out["manifest"]["captured_documents"] == N_DOCS
    assert out["manifest"]["live_production_corpus_at_end"]["documents"] == N_DOCS + 1
    assert out["manifest"]["new_documents_ingested_during_run"] == 1
    assert out["summary"]["final_position"] == N_DOCS - 1


def test_captured_input_mutation_fails_closed(prod, tmp_path, monkeypatch):
    from src.intelligence.replay import runner as runner_mod

    real = runner_mod.capture_corpus_snapshot

    def capture_then_mutate(src_root, dest_root):
        info = real(src_root, dest_root)
        conn = sqlite3.connect(corpus_root(prod) / "index" / "corpus.sqlite3")
        doc = conn.execute("SELECT document_id FROM documents ORDER BY document_id LIMIT 1").fetchone()[0]
        conn.execute("INSERT INTO status_events VALUES ('ev_mut',?,'QUARANTINED','test','2026-09-05T00:00:00+00:00','1')", (doc,))
        conn.commit()
        conn.close()
        return info

    monkeypatch.setattr(runner_mod, "capture_corpus_snapshot", capture_then_mutate)
    with pytest.raises(ReplayInputMutated):
        run_replay(prod, tmp_path)


def test_context_mutation_in_captured_range_fails_closed(prod, tmp_path, monkeypatch):
    from src.intelligence.replay import runner as runner_mod

    real = runner_mod.export_context_snapshot

    def export_then_mutate(root, snapshot_dir, upto):
        snap = real(root, snapshot_dir, upto)
        add_context_rows(prod, [_context_row("ctx_mut", SESSION, "2026-06-17T19:00:00+00:00")])
        return snap

    monkeypatch.setattr(runner_mod, "export_context_snapshot", export_then_mutate)
    with pytest.raises(ReplayInputMutated):
        run_replay(prod, tmp_path)


def test_drift_helpers_detect_changes(prod, tmp_path):
    capture_corpus_snapshot(corpus_root(prod), tmp_path / "snap")
    manifest = build_manifest(tmp_path / "snap")
    live = live_document_identity(corpus_root(prod), [d.document_id for d in manifest.documents])
    assert detect_input_mutation(manifest, live) == []
    live[manifest.documents[0].document_id]["quality"] = "LIMITED_USE"
    assert detect_input_mutation(manifest, live)[0]["change"] == "quality"


# ================================================================== 44-45 cleanup / privacy
def test_temp_cleanup_only_removes_replay_owned_path(prod, tmp_path):
    out = run_replay(prod, tmp_path)
    runner = out["runner"]
    assert not runner.temp_root.exists()                                         # 成功後は消えている
    stray = tmp_path / "ws" / "compass_replay_runs" / "not_mine"
    stray.mkdir(parents=True)
    (stray / "keep.txt").write_text("x")
    runner.temp_root = stray
    with pytest.raises(ReplayTempCorrupt):                                        # marker 無し → 削除拒否
        runner.cleanup_temp()
    assert (stray / "keep.txt").exists()
    outside = tmp_path / "elsewhere"
    outside.mkdir()
    (outside / OWNER_MARKER).write_text("x")
    runner.temp_root = outside
    with pytest.raises(ReplayTempCorrupt):                                        # 親が違う → 削除拒否
        runner.cleanup_temp()


def test_all_outputs_pass_forbidden_key_scan(prod, tmp_path):
    out = run_replay(prod, tmp_path)
    for doc in (out["manifest"], out["summary"], *out["rows"], *out["events"], *out["snapshots"]):
        assert find_forbidden_keys(doc) == []
    blob = json.dumps([out["manifest"], out["summary"]], ensure_ascii=False)
    assert str(prod) not in blob and ".pdf" not in blob.lower()


# ================================================================== CLI
def test_cli_run_summary_show_and_read_only_commands(prod, tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(rp_cli, "resolve_root", lambda override="": prod)
    monkeypatch.setattr(rp_cli, "load_replay_policy", lambda: policy_for(tmp_path))
    from src.intelligence.replay import runner as runner_mod

    monkeypatch.setattr(runner_mod, "load_replay_policy", lambda: policy_for(tmp_path))
    assert rp_cli.main(["validate-policy"]) == 0
    assert json.loads(capsys.readouterr().out)["compass_replay"]["digest"] == policy_for(tmp_path).digest()
    assert rp_cli.main(["summary"]) == 1
    capsys.readouterr()
    assert rp_cli.main(["run"]) == 0
    result = json.loads(capsys.readouterr().out)
    assert result["mutation"].startswith("WRITE compass_replay") and result["snapshots"] >= 3
    fingerprint = {p.name: p.read_bytes() for p in (prod / "compass_replay" / "runs" / result["run_id"]).iterdir()}
    for argv in (["summary"], ["summary", "--section", "approve_stress"], ["list-runs"]):
        assert rp_cli.main(argv) == 0, argv
        capsys.readouterr()
    pid = next(iter(json.loads((prod / "compass_replay" / "runs" / result["run_id"] / SUMMARY_FILE).read_text())["pattern_metrics"]))
    assert rp_cli.main(["show", pid]) == 0
    capsys.readouterr()
    assert {p.name: p.read_bytes() for p in (prod / "compass_replay" / "runs" / result["run_id"]).iterdir()} == fingerprint
    assert rp_cli.main(["run", "--mode", "FULL_REPLAY"]) == 2                    # 有効化なしの FULL は policy error
    capsys.readouterr()
