"""P12-A3 — live の status の projection（`<p12_root>/status/status.json`）。A1 の純粋な `project_status` から導く。**authority ではない**。

- `write_status(p12_root, state, *, runtime_anchor, schedule_id, as_of)`: 検証済みの ledger の状態から projection を作り、ledger の head
  （record_count ・head_digest）と telemetry（generated_at ＝ as_of）を添えて正準 JSON を原子的に置換する。
- `classify_status(p12_root, state)`: `STATUS_OK` ・`STATUS_STALE`（無い ・壊れている ・head が ledger と違う）。
- 常に再生成できる。消しても authority は失われない。不正な ledger からは健全な status を作らない（caller が検証済みの状態を渡す）。
"""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional

from .atomic_files import ensure_root_subdirectory, read_text_file, replace_atomically
from .canonical import canonical_json, utc_iso
from .failure_codes import AutomationError
from .ledger_store import LedgerState
from .status_projection import StatusProjection, project_status

STATUS_DIRECTORY = "status"
STATUS_FILE_NAME = "status.json"
STATUS_FILE_SCHEMA_VERSION = "p12_status_file:0.1.0"
STATUS_OK = "STATUS_OK"
STATUS_STALE = "STATUS_STALE"


def status_file(p12_root: Any) -> Path:
    return Path(p12_root) / STATUS_DIRECTORY / STATUS_FILE_NAME


def status_document(state: LedgerState, projection: StatusProjection, generated_at: Optional[datetime]) -> Dict[str, Any]:
    return {"schema_version": STATUS_FILE_SCHEMA_VERSION, "ledger_record_count": state.summary.record_count,
            "ledger_head_digest": state.summary.head_digest, "checkpoint_class": state.checkpoint_class,
            "generated_at": None if generated_at is None else utc_iso(generated_at), "projection": projection.to_dict()}


def write_status(p12_root: Any, state: LedgerState, *, runtime_anchor: str, schedule_id: str,
                 as_of: Optional[datetime] = None) -> Dict[str, Any]:
    projection = project_status(state.records, runtime_anchor=runtime_anchor, schedule_id=schedule_id, as_of=as_of)
    document = status_document(state, projection, as_of)
    ensure_root_subdirectory(p12_root, STATUS_DIRECTORY)
    replace_atomically(status_file(p12_root), (canonical_json(document) + "\n").encode("utf-8"))
    return document


def read_status(p12_root: Any) -> Optional[Dict[str, Any]]:
    """status.json を読む（無ければ None ・壊れていれば None。authority ではないので失敗は分類で表す）。"""
    try:
        text = read_text_file(status_file(p12_root))
    except AutomationError:                                                            # status は authority ではない: 読めなければ「古い」
        return None
    if text is None:
        return None
    try:
        data = json.loads(text)
    except ValueError:
        return None
    return data if isinstance(data, dict) else None


def classify_status(p12_root: Any, state: LedgerState) -> str:
    data = read_status(p12_root)
    if data is None or data.get("schema_version") != STATUS_FILE_SCHEMA_VERSION:
        return STATUS_STALE
    if data.get("ledger_head_digest") != state.summary.head_digest or data.get("ledger_record_count") != state.summary.record_count:
        return STATUS_STALE
    return STATUS_OK


__all__ = ["STATUS_DIRECTORY", "STATUS_FILE_NAME", "STATUS_FILE_SCHEMA_VERSION", "STATUS_OK", "STATUS_STALE", "classify_status",
           "read_status", "status_document", "status_file", "write_status"]
