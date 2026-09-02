"""Historical Compass の private batch 追加（Phase 3.8 §39）。

dedup（Corpus の hash identity）/ bounded batch / progress / failure isolation / Git 非追跡（data root のみ）/
最後に incremental analyzer を 1 回呼ぶ。外部からの scrape / download はしない（ローカル dir だけ）。
"""
from __future__ import annotations

import argparse
import json
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Dict, List, Optional

from ..core.paths import data_root
from ..corpus.config import CorpusConfig, load_corpus_config
from ..corpus.extraction import PypdfExtractor, TextLayerExtractor
from ..corpus.intake import SOURCE_HISTORICAL_IMPORT
from ..corpus.pipeline import ingest_path
from ..corpus.store import CorpusStore, corpus_root


@dataclass
class BatchReport:
    source_dir: str
    scanned: int = 0
    processed: int = 0
    added: int = 0
    duplicates: int = 0
    quarantined: int = 0
    failed: int = 0
    errors: int = 0
    skipped_over_limit: int = 0
    results: List[Dict[str, object]] = field(default_factory=list)
    research: Dict[str, object] = field(default_factory=dict)
    duration_seconds: float = 0.0

    def as_dict(self) -> Dict[str, object]:
        return dict(self.__dict__)


def batch_import(source_dir: Path, store: CorpusStore, *, corpus_config: CorpusConfig, extractor: TextLayerExtractor,
                 max_files: int, now: Optional[datetime] = None, on_progress: Optional[Callable[[int, int, str], None]] = None,
                 research_engine=None) -> BatchReport:
    now = now or datetime.now(timezone.utc)
    t0 = time.monotonic()
    source_dir = Path(source_dir)
    report = BatchReport(source_dir=source_dir.name)
    pdfs = sorted(p for p in source_dir.rglob("*.pdf") if p.is_file()) if source_dir.is_dir() else []
    report.scanned = len(pdfs)
    for i, pdf in enumerate(pdfs, start=1):
        if report.processed >= max_files:
            report.skipped_over_limit += 1
            continue
        report.processed += 1
        if on_progress:
            on_progress(i, len(pdfs), pdf.name)
        try:
            r = ingest_path(store, pdf, config=corpus_config, extractor=extractor, now=now,
                            source_type=SOURCE_HISTORICAL_IMPORT)
            status = r.status
            if r.status == "DUPLICATE":
                report.duplicates += 1
            elif r.status in ("ANALYZED", "PARTIAL"):
                report.added += 1
            elif r.status == "QUARANTINED":
                report.quarantined += 1
            else:
                report.failed += 1
            report.results.append({"file": pdf.name, "status": status, "document_id": r.document_id,
                                   "document_date": r.document_date, "reasons": list(r.reasons)})
        except Exception as exc:  # noqa: BLE001 1 ファイルの失敗を batch 全体へ広げない
            report.errors += 1
            report.results.append({"file": pdf.name, "status": "ERROR", "error_type": type(exc).__name__})
    if research_engine is not None and report.added:
        try:
            rr = research_engine.run_incremental(now)
            report.research = {"run_id": rr.run_id, "new_documents": len(rr.new_documents),
                               "structures_added": rr.structures_added, "errors": rr.errors}
        except Exception as exc:  # noqa: BLE001
            report.research = {"error_type": type(exc).__name__, "corpus_preserved": True}
    report.duration_seconds = round(time.monotonic() - t0, 3)
    return report


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Compass corpus private batch import")
    parser.add_argument("--source", required=True)
    parser.add_argument("--max", type=int, default=0)
    parser.add_argument("--no-research", action="store_true")
    args = parser.parse_args(argv)
    corpus_config = load_corpus_config()
    from .config import load_research_config
    from .engine import ResearchEngine
    from .regime import MarketConnector
    from .store import ResearchStore, research_root

    root = data_root()
    store = CorpusStore(corpus_root(root))
    engine = None
    if not args.no_research:
        rc = load_research_config()
        engine = ResearchEngine(store, ResearchStore(research_root(root)), rc, corpus_config, MarketConnector(root))
    max_files = args.max or load_research_config().batch_max_files
    report = batch_import(Path(args.source), store, corpus_config=corpus_config,
                          extractor=PypdfExtractor(corpus_config.extractor_version), max_files=max_files,
                          on_progress=lambda i, n, name: print(f"[batch] {i}/{n} {name}"), research_engine=engine)
    store.close()
    print(json.dumps({k: v for k, v in report.as_dict().items() if k != "results"}, ensure_ascii=False))
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
