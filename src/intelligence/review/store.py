"""Review永続化（Phase 2-F）。

    <news bank root>/review/
    ├── review_items.jsonl      … ReviewItem（追記ログ・同一IDの新version追記=最新正。
    │                             旧versionもログに残る——status更新の履歴保持）
    └── review_decisions.jsonl  … ReviewDecisionRecord（append-only。削除不可）
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Dict, Iterator, List, Optional, Tuple

from ..core import serialization
from .model import ReviewDecisionRecord, ReviewItem, ReviewStatus


class JsonlReviewStore:
    def __init__(self, root: Path) -> None:
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        serialization.register_domain_types()
        self._items_path = self.root / "review_items.jsonl"
        self._decisions_path = self.root / "review_decisions.jsonl"
        self._items: Dict[str, ReviewItem] = {}
        self._decisions: List[ReviewDecisionRecord] = []
        self.recovered_lines = 0
        self._load()

    def _load(self) -> None:
        for path, sink in ((self._items_path, "item"), (self._decisions_path, "decision")):
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
                    if sink == "item":
                        self._items[obj.review_id] = obj  # latest-wins
                    else:
                        self._decisions.append(obj)

    def _append(self, path: Path, obj) -> None:
        with path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(serialization.encode(obj), ensure_ascii=False) + "\n")
            f.flush()
            os.fsync(f.fileno())

    # ------------------------------------------------------------- items

    def upsert_item(self, item: ReviewItem) -> bool:
        """新規または新version追記（同一内容はskip=冪等intake）。"""
        existing = self._items.get(item.review_id)
        if existing is not None and \
                serialization.encode(existing) == serialization.encode(item):
            return False
        self._append(self._items_path, item)
        self._items[item.review_id] = item
        return True

    def get_item(self, review_id: str) -> Optional[ReviewItem]:
        return self._items.get(review_id)

    def iter_items(self, *, status: Optional[ReviewStatus] = None,
                   review_type=None) -> Iterator[ReviewItem]:
        for item in list(self._items.values()):
            if status is not None and item.status is not status:
                continue
            if review_type is not None and item.review_type is not review_type:
                continue
            yield item

    def counts_by_status(self) -> Dict[str, int]:
        counts: Dict[str, int] = {}
        for item in self._items.values():
            counts[item.status.value] = counts.get(item.status.value, 0) + 1
        return counts

    # ------------------------------------------------------------- decisions

    def add_decision(self, decision: ReviewDecisionRecord) -> None:
        self._append(self._decisions_path, decision)
        self._decisions.append(decision)

    def iter_decisions(self) -> Iterator[ReviewDecisionRecord]:
        return iter(list(self._decisions))

    def decisions_for(self, review_id: str) -> Tuple[ReviewDecisionRecord, ...]:
        return tuple(d for d in self._decisions if d.review_id == review_id)
