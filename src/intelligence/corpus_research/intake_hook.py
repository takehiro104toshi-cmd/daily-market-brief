"""Phase 3.75 との event / service boundary（Phase 3.8 §34–§35）。

    Corpus ingestion SUCCESS → on_corpus_ingested(document_id) → bounded incremental research

研究解析が失敗しても **Corpus ingestion は巻き戻さない**（CORPUS_SUCCESS + RESEARCH_ANALYSIS_FAILED を記録し、
bounded retry）。mobile adapter は research を import しない（processor は callable を受け取るだけ）。
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Dict, Optional

CORPUS_SUCCESS = "CORPUS_SUCCESS"
RESEARCH_OK = "RESEARCH_OK"
RESEARCH_ANALYSIS_FAILED = "RESEARCH_ANALYSIS_FAILED"
FAILURE_LEDGER = "research_failures.jsonl"


class ResearchTrigger:
    def __init__(self, engine_factory: Callable[[], object], *, max_attempts: int = 2,
                 ledger_dir: Optional[Path] = None) -> None:
        self.engine_factory = engine_factory
        self.max_attempts = max(1, int(max_attempts))
        self.ledger_dir = Path(ledger_dir) if ledger_dir else None

    def _record(self, entry: Dict[str, object]) -> None:
        if self.ledger_dir is None:
            return
        self.ledger_dir.mkdir(parents=True, exist_ok=True)
        with (self.ledger_dir / FAILURE_LEDGER).open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(entry, ensure_ascii=False, default=str) + "\n")

    def on_corpus_ingested(self, document_id: str, now: Optional[datetime] = None) -> Dict[str, object]:
        now = now or datetime.now(timezone.utc)
        attempts = 0
        last_error = ""
        while attempts < self.max_attempts:
            attempts += 1
            try:
                engine = self.engine_factory()
                report = engine.run_incremental(now)
                return {"corpus": CORPUS_SUCCESS, "research": RESEARCH_OK, "attempts": attempts,
                        "run_id": getattr(report, "run_id", ""), "new_documents": list(getattr(report, "new_documents", [])),
                        "structures_added": getattr(report, "structures_added", 0)}
            except Exception as exc:  # noqa: BLE001 型名のみ記録（本文・path を出さない）
                last_error = type(exc).__name__
        entry = {"document_id": document_id, "corpus": CORPUS_SUCCESS, "research": RESEARCH_ANALYSIS_FAILED,
                 "attempts": attempts, "error_type": last_error, "at": now.isoformat(),
                 "retry_allowed": True}
        self._record(entry)
        return entry


def make_post_ingest_hook(data_root_dir: Path, *, max_attempts: Optional[int] = None) -> Callable[[str], Dict[str, object]]:
    """mobile_intake.processor へ渡す callable（lazy import で research 側の依存を processor から隠す）。"""
    from ..corpus.config import load_corpus_config
    from ..corpus.store import CorpusStore, corpus_root
    from .config import load_research_config
    from .engine import ResearchEngine
    from .regime import MarketConnector
    from .store import ResearchStore, research_root

    config = load_research_config()

    def factory() -> ResearchEngine:
        return ResearchEngine(CorpusStore(corpus_root(data_root_dir)), ResearchStore(research_root(data_root_dir)),
                              config, load_corpus_config(), MarketConnector(data_root_dir))

    trigger = ResearchTrigger(factory, max_attempts=max_attempts or config.research_retry_max_attempts,
                              ledger_dir=research_root(data_root_dir))
    return trigger.on_corpus_ingested
