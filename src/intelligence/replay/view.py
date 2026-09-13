"""ReplayCorpusView（Phase 3.9.4）— prefix に閉じた読み取り専用 CorpusStore 互換 view。

Phase 3.8 engine / build_snapshot が呼ぶ読み取り API だけを持つ。prefix 外の document を要求されたら
`ReplayLeakageDetected`（未来データ漏洩を**構造的に**不可能にする）。書き込み API は一切公開しない。
基になる store は凍結 snapshot（backup copy）の CorpusStore。
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Set

from ..corpus.store import CorpusStore
from .errors import ReplayLeakageDetected


class ReplayCorpusView:
    def __init__(self, store: CorpusStore, allowed: Iterable[str] = ()) -> None:
        self._store = store
        self._allowed: Set[str] = set(allowed)
        self.root: Path = store.root

    # ------------------------------------------------------------- prefix control
    @property
    def allowed(self) -> Set[str]:
        return set(self._allowed)

    def allow(self, document_ids: Iterable[str]) -> None:
        self._allowed.update(str(d) for d in document_ids)

    def restrict(self, document_ids: Iterable[str]) -> None:
        self._allowed = set(str(d) for d in document_ids)

    def _check(self, document_id: str, api: str) -> str:
        if str(document_id) not in self._allowed:
            raise ReplayLeakageDetected(f"{api} requested document outside replay prefix: {document_id}")
        return str(document_id)

    # ------------------------------------------------------------- reads used by Phase 3.8 / build_snapshot
    def documents(self):
        return [d for d in self._store.documents() if d.document_id in self._allowed]

    def document(self, document_id: str):
        return self._store.document(self._check(document_id, "document"))

    def current_status(self, document_id: str) -> str:
        return self._store.current_status(self._check(document_id, "current_status"))

    def status_history(self, document_id: str) -> List[Dict]:
        return self._store.status_history(self._check(document_id, "status_history"))

    def analyses_for(self, document_id: str) -> List[Dict]:
        return self._store.analyses_for(self._check(document_id, "analyses_for"))

    def current_analysis(self, document_id: str) -> Optional[Dict]:
        return self._store.current_analysis(self._check(document_id, "current_analysis"))

    def artifacts_for(self, document_id: str, extractor_version: str = "") -> List[Dict]:
        self._check(document_id, "artifacts_for")
        if extractor_version:
            return self._store.artifacts_for(document_id, extractor_version)
        return self._store.artifacts_for(document_id)

    def quality_for(self, document_id: str) -> Optional[Dict]:
        return self._store.quality_for(self._check(document_id, "quality_for"))

    def coverage_for(self, document_id: str) -> Optional[Dict]:
        return self._store.coverage_for(self._check(document_id, "coverage_for"))

    def temporal_for(self, document_id: str) -> Optional[Dict]:
        return self._store.temporal_for(self._check(document_id, "temporal_for"))

    def alignments_for(self, document_id: str) -> List[Dict]:
        return self._store.alignments_for(self._check(document_id, "alignments_for"))

    def extraction_for(self, document_id: str) -> Optional[Dict]:
        return self._store.extraction_for(self._check(document_id, "extraction_for"))

    def observation(self, observation_id: str) -> Optional[Dict]:
        row = self._store.observation(observation_id)
        if row is not None:
            self._check(str(row.get("document_id", "")), "observation")
        return row

    def duplicates(self) -> List[Dict]:
        return [d for d in self._store.duplicates() if str(d.get("existing_document_id", "")) in self._allowed]

    def counts(self) -> Dict[str, int]:
        out = dict(self._store.counts())
        out["documents"] = len(self._allowed)
        out["duplicates"] = len(self.duplicates())
        return out

    def close(self) -> None:
        self._store.close()
