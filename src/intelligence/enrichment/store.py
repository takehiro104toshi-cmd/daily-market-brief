"""Enrichment永続化（Phase 2-E）。

    <news bank root>/enrichment/
    ├── classifications.jsonl   … NewsClassification（append-only・冪等）
    ├── enrichment_events.jsonl … EnrichmentEvent（append-only監査履歴）
    ├── review_queue.jsonl      … ReviewQueueItem（冪等——同一候補の重複積み上げなし）
    ├── enrichment_runs.jsonl   … EnrichmentRun manifest（append-only）
    └── llm_audit.jsonl         … LLM呼び出しの構造化audit（生応答・model・prompt版）

保証は既存store群と同型: append-only / 冪等（同一ID同一内容skip・内容差はエラー）/
crash-safe（破損行recovered_lines申告）/ 再オープンでJSONLから再構築。

NO DESTRUCTIVE UPDATE: NewsItem・旧classificationの書き換えAPIは存在しない。
「現在有効な分類」は履歴からの**導出**（effective_classifications——
USER > SOURCE_EXPLICIT > ENTITY_DATABASE > RULE_BASED > LLM、RETRACT済み除外）。
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Dict, Iterator, List, Optional, Tuple

from ..core import serialization
from ..databank.news_model import ClassificationProvenance, NewsClassification
from .model import EnrichmentAction, EnrichmentEvent, EnrichmentRun, ReviewQueueItem

#: effective view導出の優先順位（大きいほど優先）
_PRECEDENCE = {
    ClassificationProvenance.LLM: 1,
    ClassificationProvenance.RULE_BASED: 2,
    ClassificationProvenance.ENTITY_DATABASE: 3,
    ClassificationProvenance.SOURCE_EXPLICIT: 4,
    ClassificationProvenance.USER: 5,
}


class JsonlEnrichmentStore:
    def __init__(self, root: Path) -> None:
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        serialization.register_domain_types()
        self._cls_path = self.root / "classifications.jsonl"
        self._events_path = self.root / "enrichment_events.jsonl"
        self._review_path = self.root / "review_queue.jsonl"
        self._runs_path = self.root / "enrichment_runs.jsonl"
        self._llm_audit_path = self.root / "llm_audit.jsonl"
        self._classifications: Dict[str, NewsClassification] = {}
        self._events: List[EnrichmentEvent] = []
        self._review: Dict[str, ReviewQueueItem] = {}
        self._runs: List[EnrichmentRun] = []
        self.recovered_lines = 0
        self._load()

    # ------------------------------------------------------------- 読み戻し

    def _load(self) -> None:
        for path, sink in ((self._cls_path, "cls"), (self._events_path, "event"),
                           (self._review_path, "review"), (self._runs_path, "run")):
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
                    if sink == "cls":
                        self._classifications[obj.classification_id] = obj
                    elif sink == "event":
                        self._events.append(obj)
                    elif sink == "review":
                        self._review[obj.review_id] = obj
                    else:
                        self._runs.append(obj)

    @staticmethod
    def _append_line(path: Path, payload: dict) -> None:
        line = json.dumps(payload, ensure_ascii=False)
        with path.open("a", encoding="utf-8") as f:
            f.write(line + "\n")
            f.flush()
            os.fsync(f.fileno())

    def _append(self, path: Path, obj) -> None:
        self._append_line(path, serialization.encode(obj))

    # ------------------------------------------------------------- classification

    def add_classification(self, cls: NewsClassification) -> bool:
        """冪等追加（同一ID同一内容=skip・同一ID内容差=エラー）。"""
        existing = self._classifications.get(cls.classification_id)
        if existing is not None:
            if serialization.encode(existing) == serialization.encode(cls):
                return False
            raise ValueError(
                f"classification id collision with different content: {cls.classification_id}")
        self._append(self._cls_path, cls)
        self._classifications[cls.classification_id] = cls
        return True

    def get_classification(self, classification_id: str) -> Optional[NewsClassification]:
        return self._classifications.get(classification_id)

    def iter_classifications(self) -> Iterator[NewsClassification]:
        return iter(list(self._classifications.values()))

    def classifications_for(self, news_item_id: str) -> Tuple[NewsClassification, ...]:
        return tuple(c for c in self._classifications.values()
                     if c.news_item_id == news_item_id)

    # ------------------------------------------------------------- events / review / runs

    def add_event(self, event: EnrichmentEvent) -> None:
        self._append(self._events_path, event)
        self._events.append(event)

    def iter_events(self) -> Iterator[EnrichmentEvent]:
        return iter(list(self._events))

    def add_review_item(self, item: ReviewQueueItem) -> bool:
        if item.review_id in self._review:
            return False  # 同一候補は積み上げない（冪等）
        self._append(self._review_path, item)
        self._review[item.review_id] = item
        return True

    def iter_review_queue(self) -> Iterator[ReviewQueueItem]:
        return iter(list(self._review.values()))

    def add_run(self, run: EnrichmentRun) -> None:
        self._append(self._runs_path, run)
        self._runs.append(run)

    def iter_runs(self) -> Iterator[EnrichmentRun]:
        return iter(list(self._runs))

    def add_llm_audit(self, payload: dict) -> None:
        """LLM呼び出しのaudit（生構造化応答・model・prompt版等）。Secretは含めない。"""
        self._append_line(self._llm_audit_path, payload)

    def iter_llm_audit(self) -> Iterator[dict]:
        if not self._llm_audit_path.exists():
            return iter(())
        entries = []
        with self._llm_audit_path.open(encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    try:
                        entries.append(json.loads(line))
                    except json.JSONDecodeError:
                        self.recovered_lines += 1
        return iter(entries)

    # ------------------------------------------------------------- effective view（導出）

    def retracted_ids(self) -> frozenset:
        return frozenset(
            e.previous_classification_id for e in self._events
            if e.action in (EnrichmentAction.RETRACT, EnrichmentAction.OVERRIDE)
            and e.previous_classification_id)

    def effective_classifications(self, news_item_id: str) -> Tuple[NewsClassification, ...]:
        """現在有効な分類（履歴からの導出。canonicalの書き換えはしない）。

        - RETRACT / OVERRIDEされた旧classificationを除外
        - 同一(dimension, value)に複数provenanceがある場合は優先順位の最上位を代表に
          （USER > SOURCE_EXPLICIT > ENTITY_DATABASE > RULE_BASED > LLM）
        """
        retracted = self.retracted_ids()
        best: Dict[Tuple[str, str], NewsClassification] = {}
        for c in sorted(self.classifications_for(news_item_id),
                        key=lambda c: (c.created_at, c.classification_id)):
            if c.classification_id in retracted:
                continue
            key = (c.dimension.value, c.value)
            current = best.get(key)
            if current is None or _PRECEDENCE[c.provenance] >= _PRECEDENCE[current.provenance]:
                best[key] = c
        return tuple(best.values())
