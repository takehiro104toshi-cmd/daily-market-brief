"""P13-A1 — Market Memory の正準化（P12 の慣例を鏡写しにする。P12 ・凍結の phase は import しない）。

- 正準 JSON: 鍵は sort ・区切りは `,` `:` ・ASCII 以外はそのまま（`ensure_ascii=False`）・float ・非正準の型は拒む（決定論のため）。
- digest は `sha256(domain + "\\0" + canonical_json)`（domain は用途ごとに別）。完全な 64 hex を保つ。短縮 id は接頭辞 ＋ 先頭 24 hex の
  **略記**であり、別の完全な digest が同じ略記を持てば fail closed（`assert_no_short_id_collision`）。
- 瞬間は aware だけ（naive は拒む）・UTC に正準化。日は `date` だけ（`datetime` は拒む）。時計 ・既定は無い。
"""
from __future__ import annotations

import hashlib
import json
import re
from datetime import date, datetime, timezone
from typing import Any, Iterable, Mapping, Tuple

DIGEST_HEX_LENGTH = 64
SHORT_ID_HEX_LENGTH = 24
_DIGEST_RE = re.compile(r"^[0-9a-f]{64}$")
_UTC_ISO_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d{1,6})?\+00:00$")
_DATE_ISO_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_SAFE_CODE_RE = re.compile(r"^[A-Z][A-Z0-9_]{0,63}$")


class CanonicalError(ValueError):
    """正準化 ・schema の失敗（code ・短い detail だけ。値 ・本文は持たない）。"""

    def __init__(self, code: str, detail: str = "") -> None:
        super().__init__(f"{code}:{detail}" if detail else code)
        self.code = code
        self.detail = detail


def _reject_noncanonical(value: Any, where: str) -> None:
    if value is None or isinstance(value, (bool, int, str)):
        return
    if isinstance(value, float):
        raise CanonicalError("NON_CANONICAL_FLOAT", where)
    if isinstance(value, (list, tuple)):
        for index, item in enumerate(value):
            _reject_noncanonical(item, f"{where}[{index}]")
        return
    if isinstance(value, Mapping):
        for key, item in value.items():
            if not isinstance(key, str):
                raise CanonicalError("NON_CANONICAL_KEY", where)
            _reject_noncanonical(item, f"{where}.{key}")
        return
    raise CanonicalError("NON_CANONICAL_TYPE", where)


def canonical_json(value: Any) -> str:
    _reject_noncanonical(value, "value")
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)


def domain_digest(domain: str, value: Any) -> str:
    if not isinstance(domain, str) or not domain:
        raise CanonicalError("DOMAIN_REQUIRED")
    return hashlib.sha256(domain.encode("utf-8") + b"\0" + canonical_json(value).encode("utf-8")).hexdigest()


def is_digest(value: object) -> bool:
    return isinstance(value, str) and bool(_DIGEST_RE.match(value))


def short_id(prefix: str, digest: str) -> str:
    """接頭辞 ＋ 先頭 24 hex の略記（識別は完全な digest で行う）。"""
    if not is_digest(digest):
        raise CanonicalError("DIGEST_INVALID", prefix)
    return prefix + digest[:SHORT_ID_HEX_LENGTH]


def assert_no_short_id_collision(pairs: Iterable[Tuple[str, str]]) -> None:
    """(短縮 id, 完全な digest) の列で、同じ短縮 id に別の完全な digest が在れば fail closed。"""
    seen: dict = {}
    for short, full in pairs:
        if not is_digest(full):
            raise CanonicalError("DIGEST_INVALID", short)
        if seen.get(short, full) != full:
            raise CanonicalError("SHORT_ID_COLLISION", short)
        seen[short] = full


def require_aware(instant: Any, code: str) -> datetime:
    """aware な datetime だけを受け、UTC に正準化して返す（naive ・date ・文字列は拒む）。"""
    if not isinstance(instant, datetime) or instant.tzinfo is None or instant.tzinfo.utcoffset(instant) is None:
        raise CanonicalError(code, "INSTANT_NOT_AWARE")
    return instant.astimezone(timezone.utc)


def utc_iso(instant: datetime) -> str:
    return require_aware(instant, "INSTANT_INVALID").isoformat()


def parse_utc_iso(text: Any) -> datetime:
    if not isinstance(text, str) or not _UTC_ISO_RE.match(text):
        raise CanonicalError("INSTANT_INVALID", "UTC_ISO")
    return datetime.fromisoformat(text)


def require_date(value: Any, code: str) -> date:
    """`date` だけを受ける（`datetime` は date の subclass だが拒む。`at` から導くことも無い）。"""
    if type(value) is not date:
        raise CanonicalError(code, "INVALID_DATE")
    return value


def date_iso(day: date) -> str:
    return require_date(day, "DATE_INVALID").isoformat()


def parse_date_iso(text: Any) -> date:
    if not isinstance(text, str) or not _DATE_ISO_RE.match(text):
        raise CanonicalError("DATE_INVALID", "DATE_ISO")
    return date.fromisoformat(text)


def require_safe_code(value: Any, code: str) -> str:
    """大文字の code だけ（文 ・値 ・path ・private な形は入らない）。"""
    if not isinstance(value, str) or not _SAFE_CODE_RE.match(value):
        raise CanonicalError(code, "SAFE_CODE")
    return value


def require_fields(data: Any, required: frozenset, context: str) -> dict:
    """鍵の集合の完全一致（欠落 ・未知の鍵は拒む）。"""
    if not isinstance(data, Mapping):
        raise CanonicalError("SCHEMA_INVALID", f"{context}:NOT_A_MAPPING")
    keys = set(data)
    if keys != set(required):
        raise CanonicalError("SCHEMA_INVALID", f"{context}:FIELDS")
    return dict(data)


__all__ = ["CanonicalError", "DIGEST_HEX_LENGTH", "SHORT_ID_HEX_LENGTH", "assert_no_short_id_collision", "canonical_json",
           "date_iso", "domain_digest", "is_digest", "parse_date_iso", "parse_utc_iso", "require_aware", "require_date",
           "require_fields", "require_safe_code", "short_id", "utc_iso"]
