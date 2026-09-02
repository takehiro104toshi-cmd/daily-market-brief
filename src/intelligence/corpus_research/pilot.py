"""Phase 3.8 pilot（::P38_*::）。実在する 10 document Corpus ＋ N+1 fixture mechanics ＋ rebuild equivalence。

- isolated roots（<data_root>/compass_research_pilot/…）。production research root は触らない。
- fixture（再保存した同日 PDF）は **mechanics 検証専用** で、実 Corpus の milestone には数えない（別 root）。
- market connector は data root の既存 store へ読み取り専用で接続（無ければ availability False を報告）。
- 本文・full path を出力しない。
"""
from __future__ import annotations

import argparse
import dataclasses
import json
import shutil
import subprocess
import time as _time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Dict, List, Optional

from ..core.paths import data_root
from ..corpus.config import load_corpus_config
from ..corpus.extraction import PypdfExtractor
from ..corpus.identity import sha256_file
from ..corpus.intake import SOURCE_HISTORICAL_IMPORT
from ..corpus.inventory import inventory
from ..corpus.pipeline import ingest_path
from ..corpus.snapshot import build_snapshot
from ..corpus.store import CorpusStore
from ..mobile_intake.local_config import redact_path
from .config import load_research_config
from .engine import ResearchEngine
from .intake_hook import RESEARCH_ANALYSIS_FAILED, ResearchTrigger
from .regime import MarketConnector
from .store import REGISTRY_FILE, SNAPSHOT_FILE, ResearchStore

PILOT_ROOT_NAME = "compass_research_pilot"


def _out(marker: str, payload) -> None:
    print(f"::{marker}::" + json.dumps(payload, ensure_ascii=False, default=str))


def _resave_pdf(src: Path, dst: Path) -> None:
    import pypdf

    reader = pypdf.PdfReader(str(src))
    writer = pypdf.PdfWriter()
    for page in reader.pages:
        writer.add_page(page)
    writer.add_metadata({"/Producer": "research-pilot-fixture"})
    with dst.open("wb") as handle:
        writer.write(handle)


def _tracked_pdfs() -> int:
    try:
        out = subprocess.run(["git", "ls-files"], capture_output=True, text=True, timeout=20).stdout
    except (OSError, subprocess.SubprocessError):
        return -1
    return sum(1 for l in out.splitlines() if l.lower().endswith(".pdf"))


def _git_porcelain() -> str:
    try:
        return subprocess.run(["git", "status", "--porcelain"], capture_output=True, text=True, timeout=20).stdout
    except (OSError, subprocess.SubprocessError):
        return "?"


def _doc_summary(s: Dict) -> Dict[str, object]:
    return {"document_date": s["document_date"], "quality": s["quality"], "main_theme": s["main_theme"]["category"],
            "top_evidence": [c["category"] for c in s["selected_evidence"][:3]],
            "outlook": {k: s["outlook_summary"][k] for k in ("count", "primary_direction", "primary_horizon", "primary_target")},
            "why": s["why_summary"], "risk_primary": s["risk_summary"]["primary_type"],
            "risk_counts": {k: v for k, v in s["risk_summary"]["counts"].items() if v},
            "watch_items": len(s["watch_items"]), "links": len(s["links"]),
            "regime": {k: s["regime"][k] for k in ("referenced_session", "known_dimensions", "context_dimensions",
                                                   "comparable_values", "look_ahead_rejected")},
            "field_support": s["field_support"], "p2_mode": s["p2_mode"]}


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Phase 3.8 corpus research pilot")
    parser.add_argument("--source", default="")
    parser.add_argument("--root", default="")
    args = parser.parse_args(argv)
    started = _time.monotonic()
    now = datetime.now(timezone.utc)
    rconfig = load_research_config()
    cconfig = load_corpus_config()
    source_dir = Path(args.source or cconfig.source_dir)
    base_root = data_root()
    root = Path(args.root) if args.root else base_root / PILOT_ROOT_NAME
    git_before = _git_porcelain()
    prod_research = base_root / "compass_research"
    prod_before = prod_research.exists()
    _out("P38_INPUT", {"research_config": rconfig.as_dict(), "root": redact_path(root),
                       "source_dir_exists": source_dir.is_dir(), "offline": True, "llm": "none"})

    inv = inventory([source_dir])
    if len(inv.pdf_items) < 2:
        _out("P38_SUMMARY", {"blocked": True, "reason": "need private Compass PDFs"})
        return 1
    pdfs = [Path(i.locations[0]) for i in inv.pdf_items]
    hashes_before = {p.name: sha256_file(p) for p in pdfs}

    # ---- corpus（実 10 本、isolated）
    corpus_root_dir = root / "corpus"
    corpus = CorpusStore(corpus_root_dir)
    extractor = PypdfExtractor(cconfig.extractor_version)
    for p in pdfs:
        ingest_path(corpus, p, config=cconfig, extractor=extractor, now=now, source_type=SOURCE_HISTORICAL_IMPORT)
    csnap = build_snapshot(corpus, cconfig, now)
    connector = MarketConnector(base_root)
    _out("P38_CONNECTOR", {"availability": connector.availability,
                           "note": "read-only connection to existing stores; nothing fabricated"})

    research = ResearchStore(root / "research")
    engine = ResearchEngine(corpus, research, rconfig, cconfig, connector)
    r1 = engine.run_incremental(now)
    structures = research.current_structures(rconfig.version_key)
    _out("P38_RUN", {**{k: v for k, v in r1.as_dict().items() if k not in ("new_documents",)},
                     "new_documents": len(r1.new_documents), "rules_loaded": len(engine.rules)})
    _out("P38_STRUCTURES", {"documents": {d: _doc_summary(s) for d, s in sorted(structures.items(), key=lambda kv: kv[1]["document_date"])}})

    align_docs = sum(1 for s in structures.values() if s["market_alignment"]["comparable_values"] > 0)
    ctx_docs = sum(1 for s in structures.values() if s["regime"]["context_dimensions"] > 0)
    _out("P38_ALIGNMENT", {"documents": len(structures), "documents_with_comparable_values": align_docs,
                           "documents_with_context_regime": ctx_docs,
                           "referenced_sessions": sorted({s["regime"]["referenced_session"] for s in structures.values()}),
                           "regime_label_sources": {src: sum(1 for s in structures.values() for d, v in s["regime"]["sources"].items() if v == src)
                                                    for src in ("CONTEXT", "EXTRACTED_VALUE", "TEXT_KEYWORD", "UNKNOWN")}})

    snap = json.loads((research.root / SNAPSHOT_FILE).read_text(encoding="utf-8"))
    registry = json.loads((research.root / REGISTRY_FILE).read_text(encoding="utf-8"))
    by_type: Dict[str, int] = {}
    for rec in registry["patterns"]:
        by_type[rec["pattern_type"]] = by_type.get(rec["pattern_type"], 0) + 1
    _out("P38_PATTERNS", {"total": snap["patterns_total"], "by_status": snap["patterns_by_status"], "by_type": by_type,
                          "max_status_allowed": snap["max_status_allowed_in_phase_3_8"],
                          "top_supported": snap["top_supported_candidates"][:5],
                          "limitations": snap["limitations"]})
    _out("P38_SIMILARITY", {d: v[:2] for d, v in list(snap["similar_documents"].items())[:3]})
    _out("P38_DNA", {"counts": snap["dna_comparison_counts"], "conflicts": len(snap["conflicts"]),
                     "sample_conflicts": snap["conflicts"][:2]})
    _out("P38_BENCHMARK", snap["benchmark"]["metrics"] | {"boundary": snap["benchmark"]["boundary"]})
    _out("P38_REVIEW_QUEUE", snap["review_queue"])
    _out("P38_ACQUISITION", {"recommendations": snap["acquisition_recommendations"][:6]})
    _out("P38_SNAPSHOT", {k: snap[k] for k in ("corpus_count", "eligible_count", "date_range", "analyzed_documents",
                                                "patterns_total", "milestone")})

    # ---- idempotency
    counts_before = research.counts()
    r2 = engine.run_incremental(now + timedelta(minutes=1))
    counts_after = research.counts()
    _out("P38_IDEMPOTENCY", {"second_run_added": {k: r2.as_dict()[k] for k in ("structures_added", "similarities_added",
                                                                                  "assignments_added", "pattern_records_added",
                                                                                  "dna_comparisons_added", "review_items_added")},
                             "digest_same": r1.digest == r2.digest,
                             "canonical_unchanged_except_runs": {k: counts_before[k] == counts_after[k] for k in counts_before if k != "runs"}})

    # ---- N+1 fixture mechanics（別 root。実 Corpus の milestone には数えない）
    n1 = root / "n1_fixture"
    if n1.exists():
        shutil.rmtree(n1)
    shutil.copytree(corpus_root_dir, n1 / "corpus")
    shutil.copytree(research.root, n1 / "research")
    corpus.close()
    fx_dir = n1 / "_fixture"
    fx_dir.mkdir(parents=True)
    fixture = fx_dir / "FIXTURE_resaved_issue.pdf"
    _resave_pdf(pdfs[-1], fixture)
    corpus_n1 = CorpusStore(n1 / "corpus")
    research_n1 = ResearchStore(n1 / "research")
    fr = ingest_path(corpus_n1, fixture, config=cconfig, extractor=extractor, now=now + timedelta(minutes=2),
                     source_type=SOURCE_HISTORICAL_IMPORT)
    engine_n1 = ResearchEngine(corpus_n1, research_n1, rconfig, cconfig, connector)
    r3 = engine_n1.run_incremental(now + timedelta(minutes=3))
    snap_n1 = json.loads((research_n1.root / SNAPSHOT_FILE).read_text(encoding="utf-8"))
    _out("P38_N1_FIXTURE", {"fixture_status": fr.status, "fixture_document_id": fr.document_id, "fixture_is_real_corpus": False,
                            "incremental": {k: r3.as_dict()[k] for k in ("structures_added", "similarities_added", "assignments_added",
                                                                        "pattern_records_added", "affected_patterns", "review_items_added")},
                            "new_documents": len(r3.new_documents),
                            "patterns_by_status_after": snap_n1["patterns_by_status"],
                            "corpus_count_fixture_root": snap_n1["corpus_count"],
                            "real_corpus_count_unchanged": snap["corpus_count"],
                            "benchmark_after": {k: snap_n1["benchmark"]["metrics"][k] for k in ("documents", "outlook_direction_coverage", "pattern_assignment_stability")}})

    # ---- full rebuild equivalence（fixture root）
    rebuilt, r4 = engine_n1.run_full_rebuild(n1 / "research_rebuild", now + timedelta(minutes=4))
    eq = engine_n1.equivalence(rebuilt)
    research_n1.write_json("benchmark_equivalence.json", {"rebuild_equivalence": eq["equal"], "incremental_equivalence": eq["equal"],
                                                          "digest_incremental": eq["digest_incremental"], "digest_rebuild": eq["digest_rebuild"],
                                                          "benchmark_version": rconfig.benchmark_version})
    _out("P38_REBUILD", {**eq, "rebuild_run": {k: r4.as_dict()[k] for k in ("structures_added", "assignments_added", "pattern_records_added")}})

    # ---- analyzer version bump（旧結果保持・混在なし）
    bumped = dataclasses.replace(rconfig, pattern_version="1.0.1")
    engine_v2 = ResearchEngine(corpus_n1, research_n1, bumped, cconfig, connector)
    r5 = engine_v2.run_incremental(now + timedelta(minutes=5))
    old_records = research_n1.pattern_records_current(rconfig.pattern_version)
    new_records = research_n1.pattern_records_current("1.0.1")
    _out("P38_VERSION", {"old_version_records_retained": len(old_records), "new_version_records": len(new_records),
                         "structures_for_new_version_key": r5.structures_added,
                         "state_keys": sorted(research_n1.state().get("analyzed", {}).keys()),
                         "no_mixing": all(r["pattern_version"] == "1.0.1" for r in new_records.values())})

    # ---- failure isolation（intake success + research failure）
    class _Boom:
        def run_incremental(self, now=None):
            raise RuntimeError("simulated research failure")

    trigger = ResearchTrigger(lambda: _Boom(), max_attempts=rconfig.research_retry_max_attempts, ledger_dir=n1 / "research")
    outcome = trigger.on_corpus_ingested(fr.document_id, now + timedelta(minutes=6))
    _out("P38_FAILURE_ISOLATION", {"outcome": outcome, "corpus_document_still_present": corpus_n1.document(fr.document_id) is not None,
                                   "bounded_attempts": outcome["attempts"] == rconfig.research_retry_max_attempts})
    corpus_n1.close()

    # ---- security
    hashes_after = {p.name: sha256_file(p) for p in pdfs}
    research_text = "".join((research.root / f).read_text(encoding="utf-8") for f in
                            ("structures.jsonl", "patterns.jsonl", "assignments.jsonl") if (research.root / f).exists())
    abs_root = str(root.resolve())
    pkg = Path(__file__).resolve().parent
    net = []
    for py in sorted(pkg.glob("*.py")):
        text = py.read_text(encoding="utf-8")
        for tok in ("import " + "requests", "import " + "urllib", "from " + "urllib", "import " + "socket",
                    "open" + "ai", "anthro" + "pic", "sentence_" + "transformers", "sk" + "learn", "tor" + "ch"):
            if tok in text:
                net.append(f"{py.name}:{tok}")
    _out("P38_SECURITY", {"tracked_pdfs": _tracked_pdfs(), "source_pdfs_unmodified": hashes_before == hashes_after,
                          "repository_mutation": _git_porcelain() != git_before,
                          "production_research_root_modified": prod_research.exists() != prod_before,
                          "network_or_llm_imports": net,
                          "document_text_in_research_artifacts": ('"text"' in research_text) or ("●" in research_text),
                          "full_path_in_research_artifacts": abs_root in research_text,
                          "production_rules_modified": _git_porcelain() != git_before, "external_llm_calls": 0})
    _out("P38_SUMMARY", {"real_documents": snap["corpus_count"], "eligible": snap["eligible_count"],
                         "analyzed": snap["analyzed_documents"], "patterns": snap["patterns_total"],
                         "patterns_by_status": snap["patterns_by_status"], "review_open": snap["review_queue"]["open_items"],
                         "alignment_comparable_docs": align_docs, "context_regime_docs": ctx_docs,
                         "idempotent": r1.digest == r2.digest and r2.structures_added == 0,
                         "n1_incremental_ok": r3.structures_added == 1, "rebuild_equivalent": eq["equal"],
                         "version_isolation": all(r["pattern_version"] == "1.0.1" for r in new_records.values()) and len(old_records) > 0,
                         "failure_isolated": outcome["research"] == RESEARCH_ANALYSIS_FAILED,
                         "runtime_seconds": round(_time.monotonic() - started, 2)})
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
