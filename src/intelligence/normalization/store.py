"""Normalized Storage（Phase 1-D）。Raw storageと分離した正規化層の永続化。

    data/vnext/normalized/            ← git非管理（.gitignoreのdata/vnext/配下）
    ├── source_documents.jsonl        ← SourceDocument（append-only）
    ├── observations.jsonl            ← Observation（append-only）
    └── normalization_events.jsonl    ← NormalizationEvent（append-only）

保証（raw_storeと同型）:
- append-only / immutable（削除・上書きAPIなし。v2再処理は新IDの新レコード）
- 冪等（同一ID＋同一内容はスキップ。同一IDで内容差はValueError）
- crash-safe（末尾破損行はスキップ・recovered_linesで申告）
- 再オープンでJSONLからインデックス再構築（導出。二重保存しない）
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Dict, Iterator, List, Optional, Sequence, Tuple

from ..core import serialization
from ..market.model import Observation
from ..normalization.model import NormalizationEvent
from ..sources.model import SourceDocument


class JsonlNormalizedStore:
    """SourceDocument / Observation / NormalizationEvent のJSONL永続化。"""

    def __init__(self, root: Path) -> None:
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self._docs_path = self.root / "source_documents.jsonl"
        self._obs_path = self.root / "observations.jsonl"
        self._events_path = self.root / "normalization_events.jsonl"
        serialization.register_domain_types()
        self._docs: Dict[str, SourceDocument] = {}
        self._obs: Dict[str, Observation] = {}
        self._events: List[NormalizationEvent] = []
        self.recovered_lines = 0
        self._load()

    def _load(self) -> None:
        for path, sink in (
            (self._docs_path, "doc"), (self._obs_path, "obs"), (self._events_path, "event"),
        ):
            if not path.exists():
                continue
            with path.open(encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        obj = serialization.decode(json.loads(line))
                    except (json.JSONDecodeError, ValueError, TypeError, KeyError):
                        self.recovered_lines += 1
                        continue
                    if sink == "doc":
                        self._docs[obj.source_document_id] = obj
                    elif sink == "obs":
                        self._obs[obj.observation_id] = obj
                    else:
                        self._events.append(obj)

    @staticmethod
    def _append(path: Path, obj) -> None:
        line = json.dumps(serialization.encode(obj), ensure_ascii=False)
        with path.open("a", encoding="utf-8") as f:
            f.write(line + "\n")
            f.flush()
            os.fsync(f.fileno())

    def _add_unique(self, store: Dict[str, object], key: str, obj, path: Path) -> bool:
        existing = store.get(key)
        if existing is not None:
            if serialization.encode(existing) == serialization.encode(obj):
                return False  # 冪等スキップ
            raise ValueError(f"id collision with different content: {key}")
        self._append(path, obj)
        store[key] = obj
        return True

    # ------------------------------------------------- SourceDocumentRepository

    def add_documents(self, documents: Sequence[SourceDocument]) -> int:
        return sum(
            self._add_unique(self._docs, d.source_document_id, d, self._docs_path)
            for d in documents
        )

    def get_document(self, source_document_id: str) -> Optional[SourceDocument]:
        return self._docs.get(source_document_id)

    def iter_documents(self) -> Iterator[SourceDocument]:
        return iter(list(self._docs.values()))

    def documents_for_raw_item(self, raw_item_id: str) -> Tuple[SourceDocument, ...]:
        return tuple(d for d in self._docs.values() if d.raw_item_id == raw_item_id)

    # ------------------------------------------------- ObservationRepository

    def add_observations(self, observations: Sequence[Observation]) -> int:
        return sum(
            self._add_unique(self._obs, o.observation_id, o, self._obs_path)
            for o in observations
        )

    def get_observation(self, observation_id: str) -> Optional[Observation]:
        return self._obs.get(observation_id)

    def iter_observations(self) -> Iterator[Observation]:
        return iter(list(self._obs.values()))

    # ------------------------------------------------- NormalizationEventRepository

    def add_event(self, event: NormalizationEvent) -> bool:
        self._append(self._events_path, event)
        self._events.append(event)
        return True

    def iter_events(self) -> Iterator[NormalizationEvent]:
        return iter(list(self._events))

    def events_for_raw_item(self, raw_item_id: str) -> Tuple[NormalizationEvent, ...]:
        return tuple(e for e in self._events if e.raw_item_id == raw_item_id)
