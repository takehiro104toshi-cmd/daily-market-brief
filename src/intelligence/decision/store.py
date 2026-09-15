"""Append-only decision store（Phase 3.9.1）— JSONL、validate-before-append、hash chain、fail closed。

- 1 行 = 1 decision event。persist 後の行は通常経路で編集しない（store に update / delete API は無い）。
- 各行は sequence（1 始まり連番）と previous_record_hash → record_hash の chain を持つ。
  行の改変・削除・並べ替え・不正 JSON はすべて load 時に DecisionStoreCorrupt（黙って読み飛ばさない）。
- decision_id は deterministic（models.decision_id_for）。同じ id の再 append は no-op（retry 安全）。
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional

from ..core.paths import data_root
from .models import DecisionRecord, record_hash_for, validate_record

DECISIONS_ROOT_NAME = "compass_decisions"
DECISIONS_FILE = "decisions.jsonl"


class DecisionStoreCorrupt(RuntimeError):
    """decision log が壊れている（改変・欠落・不正行）。state 導出は行わない。"""

    def __init__(self, line_no: int, code: str, detail: str = "") -> None:
        super().__init__(f"decision store corrupt at line {line_no}: {code}{(' ' + detail) if detail else ''}")
        self.line_no = line_no
        self.code = code
        self.detail = detail


class DecisionValidationError(ValueError):
    def __init__(self, errors: List[str]) -> None:
        super().__init__("invalid decision record: " + ",".join(errors))
        self.errors = list(errors)


def decisions_root(base: Optional[Path] = None) -> Path:
    """<data_root>/compass_decisions（corpus / research と同じ data root 規約）。"""
    return Path(base or data_root()) / DECISIONS_ROOT_NAME


class DecisionStore:
    def __init__(self, root: Path) -> None:
        self.root = Path(root)                      # 読み取りでは mkdir しない（read は non-mutating）
        self._cache: Optional[List[DecisionRecord]] = None
        self._cache_size: int = -1

    @property
    def path(self) -> Path:
        return self.root / DECISIONS_FILE

    def exists(self) -> bool:
        return self.path.is_file()

    # ------------------------------------------------------------- load（fail closed）
    def _load(self) -> List[DecisionRecord]:
        out: List[DecisionRecord] = []
        if not self.path.is_file():
            return out
        seen: set = set()
        previous_hash = ""
        with self.path.open(encoding="utf-8") as handle:
            for line_no, line in enumerate(handle, start=1):
                text = line.strip()
                if not text:
                    raise DecisionStoreCorrupt(line_no, "BLANK_LINE")
                try:
                    row = json.loads(text)
                except json.JSONDecodeError as exc:
                    raise DecisionStoreCorrupt(line_no, "INVALID_JSON", str(exc)) from None
                errors = validate_record(row)
                if errors:
                    raise DecisionStoreCorrupt(line_no, "SCHEMA_INVALID", ",".join(errors))
                if row["sequence"] != line_no:
                    raise DecisionStoreCorrupt(line_no, "SEQUENCE_MISMATCH", f"expected {line_no} got {row['sequence']}")
                if row["previous_record_hash"] != previous_hash:
                    raise DecisionStoreCorrupt(line_no, "CHAIN_BROKEN")
                if row["decision_id"] in seen:
                    raise DecisionStoreCorrupt(line_no, "DUPLICATE_DECISION_ID", row["decision_id"])
                seen.add(row["decision_id"])
                previous_hash = row["record_hash"]
                out.append(DecisionRecord.from_dict(row))
        return out

    def records(self) -> List[DecisionRecord]:
        size = self.path.stat().st_size if self.path.is_file() else 0
        if self._cache is None or size != self._cache_size:
            self._cache = self._load()
            self._cache_size = size
        return list(self._cache)

    def for_pattern(self, pattern_id: str) -> List[DecisionRecord]:
        return [r for r in self.records() if r.pattern_id == pattern_id]

    def head(self, pattern_id: str) -> Optional[DecisionRecord]:
        rows = self.for_pattern(pattern_id)
        return rows[-1] if rows else None

    def get(self, decision_id: str) -> Optional[DecisionRecord]:
        for r in self.records():
            if r.decision_id == decision_id:
                return r
        return None

    # ------------------------------------------------------------- append（唯一の mutating path）
    def append(self, proposed: Mapping[str, Any]) -> Dict[str, Any]:
        """validate → seal（sequence / chain / hash）→ 1 行追記。同じ decision_id は no-op（appended False）。"""
        errors = validate_record(proposed, allow_unsealed=True)
        if errors:
            raise DecisionValidationError(errors)
        existing = self.get(str(proposed["decision_id"]))
        if existing is not None:
            return {"appended": False, "record": existing, "reason": "DUPLICATE_DECISION_ID_IDEMPOTENT"}
        current = self.records()
        row = dict(proposed)
        row["sequence"] = len(current) + 1
        row["previous_record_hash"] = current[-1].record_hash if current else ""
        row["record_hash"] = ""
        row["record_hash"] = record_hash_for(row)
        sealed_errors = validate_record(row)
        if sealed_errors:
            raise DecisionValidationError(sealed_errors)
        self.root.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True, default=str) + "\n")
            handle.flush()
            os.fsync(handle.fileno())
        self._cache = None
        record = DecisionRecord.from_dict(row)
        return {"appended": True, "record": record, "reason": "APPENDED"}
