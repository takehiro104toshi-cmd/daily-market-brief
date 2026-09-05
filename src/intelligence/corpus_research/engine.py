"""Research engine（Phase 3.8 §22–§25, §36）— incremental / full rebuild / equivalence。

- incremental: 未解析 document だけ structure を作り、それに関わる similarity / pattern support / DNA 比較 /
  review queue / benchmark / snapshot を更新する。決定的・idempotent（同じ入力で再実行しても追記 0）。
- full rebuild: immutable source（Corpus）＋ 現 analyzer versions ＋ alignment 入力から fresh root に再構築。
- equivalence: 両者の derived digest（timestamps 除外）が一致することを検証する。
- 旧 analyzer version の結果は残す（version_key ごとに state を持つ）。異なる version を混ぜない。
"""
from __future__ import annotations

import hashlib
import time
from decimal import Decimal
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Dict, List, Mapping, Optional, Sequence

from ..corpus.config import CorpusConfig
from ..corpus.snapshot import build_snapshot
from ..corpus.status import ANALYZED, PARTIAL
from ..corpus.store import CorpusStore
from .acquisition import recommendations
from .benchmark import compute_benchmark
from .comparator import similar_documents, similarity, SimilarityResult
from .config import ResearchConfig
from .dna_comparison import CONFLICT, compare_pattern, conflict_record, load_rules
from .lifecycle import PHASE_38_ALLOWED, corpus_limitations, lifecycle_status, pattern_limitations, support_profile
from .patterns import derive_assignments
from .regime import MarketConnector
from .research_snapshot import build_research_snapshot
from .review_queue import build_review_items
from .store import REGISTRY_FILE, SNAPSHOT_FILE, ResearchStore
from .structure import analyze_structure

MODE_INCREMENTAL = "INCREMENTAL"
MODE_FULL_REBUILD = "FULL_REBUILD"


@dataclass
class RunReport:
    run_id: str
    mode: str
    version_key: str
    started_at: str
    new_documents: List[str] = field(default_factory=list)
    structures_added: int = 0
    similarities_added: int = 0
    assignments_added: int = 0
    pattern_records_added: int = 0
    affected_patterns: int = 0
    dna_comparisons_added: int = 0
    conflicts_added: int = 0
    review_items_added: int = 0
    benchmark_id: str = ""
    benchmark_added: bool = False
    digest: str = ""
    duration_seconds: float = 0.0
    errors: List[str] = field(default_factory=list)

    def as_dict(self) -> Dict[str, object]:
        return dict(self.__dict__)


class ResearchEngine:
    def __init__(self, corpus: CorpusStore, research: ResearchStore, config: ResearchConfig,
                 corpus_config: CorpusConfig, connector: MarketConnector, rules_path: Optional[Path] = None) -> None:
        self.corpus = corpus
        self.research = research
        self.config = config
        self.corpus_config = corpus_config
        self.connector = connector
        self.rules = load_rules(Path(rules_path or config.dna_rules_path))

    # ------------------------------------------------------------- helpers
    def usable_document_ids(self) -> List[str]:
        return [d.document_id for d in self.corpus.documents()
                if self.corpus.current_status(d.document_id) in (ANALYZED, PARTIAL)]

    def _pending_documents(self) -> List[str]:
        state = self.research.state()
        analyzed = dict(state.get("analyzed", {}).get(self.config.version_key, {}))
        pending = []
        for doc in self.usable_document_ids():
            current = self.corpus.current_analysis(doc) or {}
            key = f"{current.get('record_id', '')}"
            if analyzed.get(doc) != key:
                pending.append(doc)
        return pending

    def _mark_analyzed(self, docs: Sequence[str]) -> None:
        state = self.research.state()
        analyzed = state.setdefault("analyzed", {}).setdefault(self.config.version_key, {})
        for doc in docs:
            current = self.corpus.current_analysis(doc) or {}
            analyzed[doc] = f"{current.get('record_id', '')}"
        state["last_version_key"] = self.config.version_key
        self.research.save_state(state)

    # ------------------------------------------------------------- pattern records
    def _pattern_record(self, pattern_id: str, assignments: Sequence[Mapping], now: datetime) -> Dict[str, object]:
        profile = support_profile(assignments)
        status = lifecycle_status(profile, self.config.thresholds())
        assert status in PHASE_38_ALLOWED
        docs = sorted({str(a["document_id"]) for a in assignments})
        refs: List[str] = []
        for a in sorted(assignments, key=lambda x: str(x["document_id"])):
            refs.extend(str(r) for r in a.get("evidence_refs") or [])
        regimes = sorted({str(a.get("regime_key")) for a in assignments} - {"regime:UNKNOWN"})
        qualities = [str(a.get("quality", "")) for a in assignments]
        first = assignments[0]
        rec_seed = f"{pattern_id}|{self.config.pattern_version}|{','.join(docs)}|{status}|{self.config.lifecycle_thresholds_version}"
        return {
            "pattern_record_id": "cpr_" + hashlib.sha1(rec_seed.encode("utf-8")).hexdigest()[:16],
            "pattern_id": pattern_id, "pattern_version": self.config.pattern_version,
            "pattern_type": first.get("pattern_type"), "components": dict(first.get("components") or {}),
            "supporting_document_ids": docs, "support_count": profile.support_count,
            "eligible_support": profile.eligible_support, "regime_count": profile.regime_count,
            "regime_coverage": regimes, "date_range": [profile.first_seen, profile.last_seen],
            "span_days": profile.span_days, "valid_ratio": str(profile.valid_ratio), "status": status,
            "thresholds_version": self.config.lifecycle_thresholds_version,
            "evidence_references": list(dict.fromkeys(refs)),
            "quality": "VALID" if qualities and all(q == "VALID" for q in qualities) else (min(qualities) if qualities else ""),
            "first_seen": profile.first_seen, "last_seen": profile.last_seen,
            "limitations": pattern_limitations(profile),
            "created_at": now.isoformat(),
        }

    def _corpus_span_days(self, structures: Mapping[str, Mapping]) -> int:
        dates = sorted(str(s.get("document_date", "")) for s in structures.values() if s.get("document_date"))
        if len(dates) < 2:
            return 0
        try:
            return (date.fromisoformat(dates[-1]) - date.fromisoformat(dates[0])).days
        except ValueError:
            return 0

    # ------------------------------------------------------------- runs
    def run_incremental(self, now: Optional[datetime] = None, mode: str = MODE_INCREMENTAL) -> RunReport:
        now = now or datetime.now(timezone.utc)
        t0 = time.monotonic()
        pending = self._pending_documents()
        report = RunReport(run_id="", mode=mode, version_key=self.config.version_key,
                           started_at=now.isoformat(), new_documents=list(pending))
        # 1) structures for new documents
        new_structs: Dict[str, Dict] = {}
        for doc in pending:
            try:
                st = analyze_structure(self.corpus, doc, self.config, self.connector, now)
            except Exception as exc:  # noqa: BLE001 1 document の失敗を run 全体へ広げない
                report.errors.append(f"{doc}:{type(exc).__name__}")
                continue
            if st is None:
                continue
            new_structs[doc] = st.as_dict()
        report.structures_added = self.research.append("structures", list(new_structs.values()))["added"]
        self._mark_analyzed(list(new_structs))
        structures = self.research.current_structures(self.config.version_key)

        # 2) similarities: 新 document を含む pair だけ（初回は全 pair）
        existing = {s["similarity_id"] for s in self.research.similarities_current(self.config.similarity_version)}
        sims: List[SimilarityResult] = []
        ids = sorted(structures)
        for i, a in enumerate(ids):
            for b in ids[i + 1:]:
                if not existing or a in new_structs or b in new_structs:
                    sims.append(similarity(structures[a], structures[b]))
        report.similarities_added = self.research.append("similarities", [s.as_dict() for s in sims])["added"]

        # 3) assignments for new documents → affected patterns
        new_assign = []
        for doc in new_structs:
            new_assign.extend(a.as_dict() for a in derive_assignments(
                new_structs[doc], evidence_categories=self.config.pattern_evidence_categories,
                version=self.config.pattern_version))
        report.assignments_added = self.research.append("assignments", new_assign)["added"]
        all_assign = [a for a in self.research.assignments_current(self.config.pattern_version)
                      if str(a["document_id"]) in structures]
        affected = {str(a["pattern_id"]) for a in new_assign}
        current_records = self.research.pattern_records_current(self.config.pattern_version)
        if not current_records:
            affected = {str(a["pattern_id"]) for a in all_assign}
        eligible_corpus = sum(1 for s in structures.values() if s.get("eligible"))
        span = self._corpus_span_days(structures)
        by_pattern: Dict[str, List[Mapping]] = {}
        for a in all_assign:
            by_pattern.setdefault(str(a["pattern_id"]), []).append(a)
        records = [self._pattern_record(pid, by_pattern[pid], now) for pid in sorted(affected) if pid in by_pattern]
        corpus_limits = corpus_limitations(eligible_corpus, span, self.config.thresholds())
        report.affected_patterns = len(records)
        report.pattern_records_added = self.research.append("patterns", records)["added"]
        current_records = self.research.pattern_records_current(self.config.pattern_version)

        # 4) DNA comparison / conflicts for affected patterns
        comparisons = []
        conflicts = []
        for pid in sorted(affected):
            rec = current_records.get(pid)
            if rec is None:
                continue
            cmp_ = compare_pattern(pid, rec.get("components") or {}, self.rules)
            comparisons.append(cmp_.as_dict())
            if cmp_.classification == CONFLICT:
                conflicts.append(conflict_record(cmp_, rec))
        report.dna_comparisons_added = self.research.append("dna_comparisons", comparisons)["added"]
        report.conflicts_added = self.research.append("conflicts", conflicts)["added"]
        all_conflicts = [c for c in self.research.rows("conflicts") if c["pattern_id"] in current_records]
        dna_counts: Dict[str, int] = {}
        for c in self.research.rows("dna_comparisons"):
            if c["pattern_id"] in current_records:
                dna_counts[str(c["classification"])] = dna_counts.get(str(c["classification"]), 0) + 1

        # 5) review queue（idempotent ids）
        items = build_review_items(pattern_records=current_records, conflicts=all_conflicts, structures=structures, now=now)
        report.review_items_added = self.research.append("review_queue", items)["added"]

        # 6) benchmark（inputs digest が同じなら追記されない）
        recomputed = []
        for s in structures.values():
            recomputed.extend(a.as_dict() for a in derive_assignments(
                s, evidence_categories=self.config.pattern_evidence_categories, version=self.config.pattern_version))
        digest = self.research.digest(self.config.version_key, self.config.pattern_version, self.config.similarity_version)
        report.digest = digest
        bench = compute_benchmark(list(structures.values()), stored_assignments=all_assign, recomputed_assignments=recomputed,
                                  rebuild_equivalence=None, incremental_equivalence=None, inputs_digest=digest,
                                  version=self.config.benchmark_version)
        report.benchmark_id = bench["benchmark_id"]
        report.benchmark_added = self.research.append("benchmarks", [bench])["added"] == 1

        # 7) registry view + research snapshot
        corpus_snap = build_snapshot(self.corpus, self.corpus_config, now).as_dict()
        similar = {d: similar_documents(d, [SimilarityResult(**{**s, "score": Decimal(s["score"]),
                                                              "shared_features": tuple(s["shared_features"]),
                                                              "different_features": tuple(s["different_features"])})
                                            for s in self.research.similarities_current(self.config.similarity_version)
                                            if s["document_a"] in structures and s["document_b"] in structures],
                                       top_k=self.config.similarity_top_k, min_score=self.config.similarity_min_score)
                   for d in ids}
        acq = recommendations(corpus_snap.get("coverage") or {})
        limits = corpus_limits + sorted({l for r in current_records.values() for l in r.get("limitations") or []})
        snapshot = build_research_snapshot(
            corpus_snapshot=corpus_snap, structures=structures, pattern_records=current_records, similar=similar,
            dna_counts=dna_counts, conflicts=all_conflicts, benchmark=bench, review_items=self.research.review_items(),
            acquisition=acq, connector_availability=self.connector.availability, config=self.config, now=now,
            limitations=limits)
        self.research.write_json(SNAPSHOT_FILE, snapshot)
        self.research.write_json(REGISTRY_FILE, {
            "registry_version": self.config.pattern_version, "generated_at": now.isoformat(),
            "is_production_rule_source": False,
            "note": "research evidence only; never synchronized to market_principles.py / market_rules.yaml",
            "corpus_limitations": corpus_limits,
            "patterns": [current_records[p] for p in sorted(current_records)]})
        report.duration_seconds = time.monotonic() - t0
        report.run_id = "crr_" + hashlib.sha1(f"{mode}|{now.isoformat()}|{digest}".encode("utf-8")).hexdigest()[:16]
        self.research.append("runs", [report.as_dict()])
        return report

    def run_full_rebuild(self, target_root: Path, now: Optional[datetime] = None) -> "tuple[ResearchStore, RunReport]":
        fresh = ResearchStore(Path(target_root))
        engine = ResearchEngine(self.corpus, fresh, self.config, self.corpus_config, self.connector)
        engine.rules = self.rules
        report = engine.run_incremental(now, mode=MODE_FULL_REBUILD)
        return fresh, report

    def equivalence(self, other: ResearchStore) -> Dict[str, object]:
        a = self.research.derived_view(self.config.version_key, self.config.pattern_version, self.config.similarity_version)
        b = other.derived_view(self.config.version_key, self.config.pattern_version, self.config.similarity_version)
        diffs = [k for k in a if a[k] != b.get(k)]
        da = self.research.digest(self.config.version_key, self.config.pattern_version, self.config.similarity_version)
        db = other.digest(self.config.version_key, self.config.pattern_version, self.config.similarity_version)
        return {"equal": da == db, "digest_incremental": da, "digest_rebuild": db, "differing_sections": diffs,
                "structures": len(a["structures"]), "patterns": len(a["patterns"])}
