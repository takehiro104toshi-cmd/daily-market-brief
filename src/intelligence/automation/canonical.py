"""P12-A1 — 正準の直列化と内容 address の digest（domain を分けた sha256）。

- 正準 JSON: 鍵は sort ・区切りは `,` `:` ・ASCII 以外はそのまま（`ensure_ascii=False`）・float は拒む（決定論のため）。
- digest は `sha256(domain + "\\0" + canonical_json)`。domain は用途ごとに別（schedule ・calendar ・run ・ledger record）。
- aware な瞬間は UTC の ISO（`+00:00`）に正規化してから直列化する（offset の表現の違いで digest が変わらない）。
"""
from __future__ import annotations

import hashlib
import json
from datetime import date, datetime, timezone
from typing import Any

from .failure_codes import AutomationError

DIGEST_HEX_LENGTH = 64


def canonical_json(value: Any) -> str:
    _reject_floats(value)
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)


def _reject_floats(value: Any) -> None:
    if isinstance(value, float):
        raise AutomationError("SCHEMA_INVALID", "FLOAT_NOT_CANONICAL")
    if isinstance(value, dict):
        for key, item in value.items():
            if not isinstance(key, str):
                raise AutomationError("SCHEMA_INVALID", "KEY_NOT_STRING")
            _reject_floats(item)
    elif isinstance(value, (list, tuple)):
        for item in value:
            _reject_floats(item)


def domain_digest(domain: str, value: Any) -> str:
    return hashlib.sha256(domain.encode("utf-8") + b"\0" + canonical_json(value).encode("utf-8")).hexdigest()


def is_digest(value: object) -> bool:
    return isinstance(value, str) and len(value) == DIGEST_HEX_LENGTH and all(c in "0123456789abcdef" for c in value)


def is_git_anchor(value: object) -> bool:
    return isinstance(value, str) and len(value) == 40 and all(c in "0123456789abcdef" for c in value)


def require_aware(instant: Any, code: str) -> datetime:
    if not isinstance(instant, datetime) or instant.tzinfo is None or instant.tzinfo.utcoffset(instant) is None:
        raise AutomationError(code)
    return instant


def utc_iso(instant: datetime) -> str:
    """aware な瞬間 → UTC の ISO 8601（秒まで ・接尾の `Z`）。microsecond は拒む（決定論 ・schedule は秒の粒）。"""
    aware = require_aware(instant, "SCHEMA_INVALID")
    if aware.microsecond != 0:
        raise AutomationError("SCHEMA_INVALID", "SUBSECOND_INSTANT")
    return aware.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def parse_utc_iso(text: Any) -> datetime:
    if not isinstance(text, str):
        raise AutomationError("SCHEMA_INVALID", "INSTANT_NOT_STRING")
    try:
        parsed = datetime.fromisoformat(text[:-1] + "+00:00" if text.endswith("Z") else text)
    except ValueError:
        raise AutomationError("SCHEMA_INVALID", "INSTANT_FORMAT") from None
    aware = require_aware(parsed, "SCHEMA_INVALID")
    if aware.microsecond != 0:
        raise AutomationError("SCHEMA_INVALID", "SUBSECOND_INSTANT")
    return aware.astimezone(timezone.utc)


def date_iso(day: date) -> str:
    if not isinstance(day, date) or isinstance(day, datetime):
        raise AutomationError("SCHEMA_INVALID", "DATE_TYPE")
    return day.isoformat()


def parse_date_iso(text: Any) -> date:
    if not isinstance(text, str) or len(text) != 10:
        raise AutomationError("SCHEMA_INVALID", "DATE_FORMAT")
    try:
        return date.fromisoformat(text)
    except ValueError:
        raise AutomationError("SCHEMA_INVALID", "DATE_FORMAT") from None


def require_fields(data: Any, required: frozenset, context: str) -> dict:
    """鍵の集合の完全一致（未知の鍵 ・欠けた鍵は fail closed）。"""
    if not isinstance(data, dict):
        raise AutomationError("SCHEMA_INVALID", f"{context}_NOT_OBJECT")
    keys = set(data)
    if keys - required:
        raise AutomationError("SCHEMA_INVALID", f"{context}_UNKNOWN_FIELD")
    if required - keys:
        raise AutomationError("SCHEMA_INVALID", f"{context}_MISSING_FIELD")
    return data


__all__ = ["DIGEST_HEX_LENGTH", "canonical_json", "date_iso", "domain_digest", "is_digest", "is_git_anchor",
           "parse_date_iso", "parse_utc_iso", "require_aware", "require_fields", "utc_iso"]
