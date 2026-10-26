"""P12-A4 — 協調的な cancel の authority（`<p12_root>/authority/cancel/<run_id>.json`。人だけが書く ・kill の意味は無い）。

transaction は決まった step の間（PLANNED の前 ・実行の前）で `cancel_requested(p12_root, run_id)` を見て、要求が在れば CANCELLED の
終端を commit する。ledger の追記 ・checkpoint の臨界の中では見ない。実行（A2）が始まった後は見ない（artifact が finalize された run の
commit を途中で止めない）。record は正準 JSON（run_id ・requested_at ・operator=human ・reason_code）。理由の文は無い。
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Dict, Optional

from .atomic_files import ensure_directory, ensure_root_subdirectory, read_text_file, replace_atomically
from .canonical import canonical_json, is_digest, require_fields, utc_iso
from .failure_codes import AutomationError
from .schedule_authority import AUTHORITY_DIRECTORY, HUMAN_OPERATOR

CANCEL_DIRECTORY = "cancel"
CANCEL_SCHEMA_VERSION = "p12_cancel_request:0.1.0"
_REASON_RE = re.compile(r"\A[A-Z][A-Z0-9_]{1,40}\Z")
_FIELDS = frozenset({"schema_version", "run_id", "requested_at", "operator", "reason_code"})


def cancel_file(p12_root: Any, run_id: str) -> Path:
    if not is_digest(run_id):
        raise AutomationError("SCHEMA_INVALID", "RUN_ID")
    return Path(p12_root) / AUTHORITY_DIRECTORY / CANCEL_DIRECTORY / f"{run_id}.json"


def write_cancel_request(p12_root: Any, run_id: str, *, operator: str, requested_at: Any, reason_code: str = "HUMAN_CANCEL") -> Dict[str, Any]:
    if operator != HUMAN_OPERATOR:
        raise AutomationError("SCHEMA_INVALID", "AUTHORITY_WRITE_NOT_HUMAN")
    if not _REASON_RE.match(reason_code or ""):
        raise AutomationError("SCHEMA_INVALID", "CANCEL_REASON_CODE")
    target = cancel_file(p12_root, run_id)
    document = {"schema_version": CANCEL_SCHEMA_VERSION, "run_id": run_id, "requested_at": utc_iso(requested_at),
                "operator": operator, "reason_code": reason_code}
    ensure_directory(ensure_root_subdirectory(p12_root, AUTHORITY_DIRECTORY) / CANCEL_DIRECTORY)
    replace_atomically(target, (canonical_json(document) + "\n").encode("utf-8"))
    return document


def cancel_requested(p12_root: Any, run_id: str) -> Optional[Dict[str, Any]]:
    """要求が在れば検証済みの document、無ければ None。壊れた要求は fail closed（`SCHEMA_INVALID:CANCEL_MALFORMED`）。"""
    text = read_text_file(cancel_file(p12_root, run_id))
    if text is None:
        return None
    try:
        fields = require_fields(json.loads(text), _FIELDS, "CANCEL")
    except (ValueError, AutomationError):
        raise AutomationError("SCHEMA_INVALID", "CANCEL_MALFORMED") from None
    if fields["schema_version"] != CANCEL_SCHEMA_VERSION or fields["run_id"] != run_id or fields["operator"] != HUMAN_OPERATOR \
            or not _REASON_RE.match(str(fields["reason_code"])):
        raise AutomationError("SCHEMA_INVALID", "CANCEL_MALFORMED")
    return fields


__all__ = ["CANCEL_DIRECTORY", "CANCEL_SCHEMA_VERSION", "cancel_file", "cancel_requested", "write_cancel_request"]
