"""Derived evaluation store（Phase 3.9.2）— rebuildable。Decision store とは別物で、混ぜない。

`<data_root>/compass_evaluation/`
    evaluations.jsonl        … 現行 policy での全 pattern の評価（毎回 **決定的に置換**。append-only ではない）
    evaluation_snapshot.json … 集計 read model

evaluation は derived なので append-only にしない（Decision history の純度を保つため、そちらへは絶対書かない）。
書き込みは temp file → `os.replace` の atomic 置換で、途中で落ちても壊れた state を残さない。
"""
from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any, Dict, Iterator, List, Mapping, Optional, Sequence

from ..core.paths import data_root
from .models import EvaluationRecord, validate_record

EVALUATION_ROOT_NAME = "compass_evaluation"
EVALUATIONS_FILE = "evaluations.jsonl"
SNAPSHOT_FILE = "evaluation_snapshot.json"
_VOLATILE_KEYS = ("evaluated_at", "generated_at")


class EvaluationStoreCorrupt(RuntimeError):
    def __init__(self, line_no: int, code: str, detail: str = "") -> None:
        super().__init__(f"evaluation store corrupt at line {line_no}: {code}{(' ' + detail) if detail else ''}")
        self.line_no = line_no
        self.code = code
        self.detail = detail


def evaluation_root(base: Optional[Path] = None) -> Path:
    return Path(base or data_root()) / EVALUATION_ROOT_NAME


def _strip_volatile(obj: Any) -> Any:
    if isinstance(obj, dict):
        return {k: _strip_volatile(v) for k, v in sorted(obj.items()) if k not in _VOLATILE_KEYS}
    if isinstance(obj, list):
        return [_strip_volatile(v) for v in obj]
    return obj


class EvaluationStore:
    def __init__(self, root: Path) -> None:
        self.root = Path(root)          # 読み取りでは mkdir しない（read は non-mutating）

    @property
    def path(self) -> Path:
        return self.root / EVALUATIONS_FILE

    @property
    def snapshot_path(self) -> Path:
        return self.root / SNAPSHOT_FILE

    def exists(self) -> bool:
        return self.path.is_file()

    # ------------------------------------------------------------- read
    def iter_records(self) -> Iterator[Dict[str, Any]]:
        if not self.path.is_file():
            return
        with self.path.open(encoding="utf-8") as handle:
            for line_no, line in enumerate(handle, start=1):
                text = line.strip()
                if not text:
                    raise EvaluationStoreCorrupt(line_no, "BLANK_LINE")
                try:
                    row = json.loads(text)
                except json.JSONDecodeError as exc:
                    raise EvaluationStoreCorrupt(line_no, "INVALID_JSON", str(exc)) from None
                errors = validate_record(row)
                if errors:
                    raise EvaluationStoreCorrupt(line_no, "SCHEMA_INVALID", ",".join(errors))
                yield row

    def records(self) -> List[Dict[str, Any]]:
        return list(self.iter_records())

    def get(self, pattern_id: str) -> Optional[Dict[str, Any]]:
        for row in self.iter_records():
            if row.get("pattern_id") == pattern_id:
                return row
        return None

    def snapshot(self) -> Dict[str, Any]:
        if not self.snapshot_path.is_file():
            return {}
        try:
            return dict(json.loads(self.snapshot_path.read_text(encoding="utf-8")) or {})
        except (OSError, ValueError):
            return {}

    # ------------------------------------------------------------- write（唯一の mutating path）
    def _atomic_write(self, path: Path, text: str) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=f".{path.name}-", suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                handle.write(text)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(tmp, path)
        finally:
            if os.path.exists(tmp):
                os.unlink(tmp)

    def replace_all(self, records: Sequence[EvaluationRecord], snapshot: Mapping[str, Any]) -> Dict[str, int]:
        """現行 policy での評価一式を決定的に置換する（pattern_id 昇順）。"""
        rows = [r.as_dict() for r in sorted(records, key=lambda x: x.pattern_id)]
        for row in rows:
            errors = validate_record(row)
            if errors:
                raise ValueError("refusing to write invalid evaluation record: " + ",".join(errors))
        self._atomic_write(self.path, "".join(
            json.dumps(row, ensure_ascii=False, sort_keys=True, default=str) + "\n" for row in rows))
        self._atomic_write(self.snapshot_path,
                           json.dumps(dict(snapshot), ensure_ascii=False, indent=1, sort_keys=True, default=str))
        return {"written": len(rows)}

    def derived_digest(self) -> str:
        """timestamps を除いた derived state の content hash（replay 同一性の検証用）。"""
        import hashlib

        view = [_strip_volatile(row) for row in self.records()]
        blob = json.dumps(view, ensure_ascii=False, sort_keys=True, default=str)
        return hashlib.sha256(blob.encode("utf-8")).hexdigest()
