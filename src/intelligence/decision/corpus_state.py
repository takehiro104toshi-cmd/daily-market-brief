"""Canonical corpus state resolver（Phase 3.9.1）— gate は directory の file 数ではなく Corpus snapshot の counts を使う。

corpus_size = eligible_for_pattern_evidence（quality VALID、Phase 3.7 canonical metric）。
読み取り専用: index が無ければ store を作らず MISSING を返す。
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Optional

SOURCE_CORPUS_STORE = "CORPUS_STORE"
SOURCE_MISSING = "CORPUS_STORE_MISSING"
SOURCE_INJECTED = "INJECTED"


@dataclass(frozen=True)
class CorpusState:
    documents: int = 0
    usable: int = 0
    eligible: int = 0                    # eligible_for_pattern_evidence（gate metric）
    valid: int = 0
    milestone: str = "NONE"
    next_milestone: str = ""
    snapshot_id: str = ""
    source: str = SOURCE_INJECTED

    def as_dict(self) -> Dict[str, object]:
        return {"documents": self.documents, "usable": self.usable, "eligible": self.eligible, "valid": self.valid,
                "milestone": self.milestone, "next_milestone": self.next_milestone,
                "snapshot_id": self.snapshot_id, "source": self.source}


def corpus_state_from_data_root(base: Path, now: Optional[datetime] = None) -> CorpusState:
    """<data_root>/compass_corpus を読む（存在しなければ MISSING、0 件）。書き込みは行わない。"""
    from ..corpus.config import load_corpus_config
    from ..corpus.snapshot import build_snapshot
    from ..corpus.store import CorpusStore, corpus_root

    root = corpus_root(Path(base))
    if not (root / "index" / "corpus.sqlite3").exists():
        return CorpusState(source=SOURCE_MISSING)
    store = CorpusStore(root)
    try:
        snap = build_snapshot(store, load_corpus_config(), now or datetime.now(timezone.utc))
    finally:
        store.close()
    counts = dict(snap.counts)
    ms = dict(snap.milestones)
    return CorpusState(documents=int(counts.get("documents", 0)), usable=int(counts.get("usable", 0)),
                       eligible=int(counts.get("eligible_for_pattern_evidence", 0)), valid=int(counts.get("valid", 0)),
                       milestone=str(ms.get("reached", "NONE")), next_milestone=str(ms.get("next_milestone", "")),
                       snapshot_id=str(snap.snapshot_id), source=SOURCE_CORPUS_STORE)
