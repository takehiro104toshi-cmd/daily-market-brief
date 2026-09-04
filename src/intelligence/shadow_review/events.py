"""Shadow Review event store（Phase 3.9.3）— append-only・hash chain・非破壊。

`<data_root>/compass_shadow_review/review_events.jsonl`

Phase 3.9.1 Decision store と**同じ思想**（sequence + previous_record_hash の chain、fail closed な
読み込み）だが、**別の store・別のクラス**で、互いに import しない。ここは decision へは何も書かない。

冪等性: shadow_review_id は内容 hash なので、まったく同じレビューの再送は同じ id になり no-op。
同じ id なのに封印内容が違う行（改竄・破損）は CONFLICTING_DUPLICATE で拒否する。
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional

from ..core.paths import data_root
from .config import ShadowReviewPolicy
from .models import (
    ShadowReviewEvent,
    ShadowReviewValidationError,
    record_hash_for,
    validate_event,
)

SHADOW_REVIEW_ROOT_NAME = "compass_shadow_review"
EVENTS_FILE = "review_events.jsonl"


class ShadowReviewStoreCorrupt(RuntimeError):
    def __init__(self, line_no: int, code: str, detail: str = "") -> None:
        super().__init__(f"shadow review events corrupt at line {line_no}: {code}"
                         f"{(' ' + detail) if detail else ''}")
        self.line_no = line_no
        self.code = code
        self.detail = detail


def shadow_review_root(base: Optional[Path] = None) -> Path:
    return Path(base or data_root()) / SHADOW_REVIEW_ROOT_NAME


class ShadowReviewEventStore:
    """人間レビュー履歴の唯一の真実。追記のみ（上書き・切り詰め・削除の API を持たない）。"""

    def __init__(self, root: Path) -> None:
        self.root = Path(root)                      # 読み取りでは mkdir しない（read は non-mutating）
        self._cache: Optional[List[ShadowReviewEvent]] = None
        self._cache_size: int = -1

    @property
    def path(self) -> Path:
        return self.root / EVENTS_FILE

    def exists(self) -> bool:
        return self.path.is_file()

    # ------------------------------------------------------------- read（fail closed）
    def _load(self) -> List[ShadowReviewEvent]:
        out: List[ShadowReviewEvent] = []
        if not self.path.is_file():
            return out
        seen: set = set()
        previous_hash = ""
        with self.path.open(encoding="utf-8") as handle:
            for line_no, line in enumerate(handle, start=1):
                text = line.strip()
                if not text:
                    raise ShadowReviewStoreCorrupt(line_no, "BLANK_LINE")
                try:
                    row = json.loads(text)
                except json.JSONDecodeError as exc:
                    raise ShadowReviewStoreCorrupt(line_no, "INVALID_JSON", str(exc)) from None
                errors = validate_event(row)
                if errors:
                    raise ShadowReviewStoreCorrupt(line_no, "SCHEMA_INVALID", ",".join(errors))
                if row["sequence"] != line_no:
                    raise ShadowReviewStoreCorrupt(line_no, "SEQUENCE_MISMATCH",
                                                   f"expected {line_no} got {row['sequence']}")
                if row["previous_record_hash"] != previous_hash:
                    raise ShadowReviewStoreCorrupt(line_no, "CHAIN_BROKEN")
                if row["shadow_review_id"] in seen:
                    raise ShadowReviewStoreCorrupt(line_no, "DUPLICATE_REVIEW_ID", row["shadow_review_id"])
                seen.add(row["shadow_review_id"])
                previous_hash = row["record_hash"]
                out.append(ShadowReviewEvent.from_dict(row))
        return out

    def records(self) -> List[ShadowReviewEvent]:
        size = self.path.stat().st_size if self.path.is_file() else 0
        if self._cache is None or size != self._cache_size:
            self._cache = self._load()
            self._cache_size = size
        return list(self._cache)

    def for_pattern(self, pattern_id: str) -> List[ShadowReviewEvent]:
        return [r for r in self.records() if r.pattern_id == pattern_id]

    def get(self, shadow_review_id: str) -> Optional[ShadowReviewEvent]:
        for r in self.records():
            if r.shadow_review_id == shadow_review_id:
                return r
        return None

    def validate(self) -> Dict[str, Any]:
        """chain 全体を検証する（read-only）。壊れていれば ShadowReviewStoreCorrupt。"""
        records = self._load()
        return {"valid": True, "events": len(records),
                "patterns": len({r.pattern_id for r in records}),
                "head_hash": records[-1].record_hash if records else ""}

    # ------------------------------------------------------------- append（唯一の mutating path）
    def append(self, proposed: Mapping[str, Any], policy: ShadowReviewPolicy) -> Dict[str, Any]:
        """validate → seal（sequence / chain / hash）→ 1 行追記。既存と同一内容なら冪等 no-op。"""
        errors = validate_event(proposed, policy, allow_unsealed=True)
        if errors:
            raise ShadowReviewValidationError(errors)
        review_id = str(proposed["shadow_review_id"])
        existing = self.get(review_id)
        if existing is not None:
            if _same_content(existing.as_dict(), proposed):
                return {"appended": False, "record": existing, "reason": "DUPLICATE_EVENT_IDEMPOTENT"}
            raise ShadowReviewValidationError([f"CONFLICTING_DUPLICATE:{review_id}"])
        current = self.records()
        row = dict(proposed)
        row["sequence"] = len(current) + 1
        row["previous_record_hash"] = current[-1].record_hash if current else ""
        row["record_hash"] = ""
        row["record_hash"] = record_hash_for(row)
        sealed_errors = validate_event(row, policy)
        if sealed_errors:
            raise ShadowReviewValidationError(sealed_errors)
        self.root.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True, default=str) + "\n")
            handle.flush()
            os.fsync(handle.fileno())
        self._cache = None
        return {"appended": True, "record": ShadowReviewEvent.from_dict(row), "reason": "APPENDED"}


_SEALED = ("sequence", "previous_record_hash", "record_hash", "reviewed_at")


def _same_content(existing: Mapping[str, Any], proposed: Mapping[str, Any]) -> bool:
    """封印値と時刻を除いた内容が同じか（同一レビューの再送判定）。"""
    left = {k: v for k, v in dict(existing).items() if k not in _SEALED}
    right = {k: v for k, v in dict(proposed).items() if k not in _SEALED}
    return left == right
