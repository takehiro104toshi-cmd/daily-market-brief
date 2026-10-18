"""P12-A3 — 休日 calendar の運用の authority の file I/O（`<p12_root>/authority/holiday_calendar.json`。人が作る ・network から取らない）。

- 読み: 正準 JSON → A1 `HolidayCalendar.from_dict`。`expected` の `HolidayCalendarReference` を渡せば一致を要求し、無い ・違うは
  `CALENDAR_UNAVAILABLE:<detail>`（計画は fail closed）。
- 書き（人だけ）: 既存の版があれば version ＞ 旧 を要求し、旧の byte を `authority/history/holiday_calendar.<旧 digest>.json` に残して
  原子的に置換する。自動の更新 ・download は無い。
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Optional

from .atomic_files import ensure_directory, ensure_root_subdirectory, read_text_file, replace_atomically
from .failure_codes import AutomationError
from .holiday_calendar import HolidayCalendar
from .schedule_authority import AUTHORITY_DIRECTORY, HISTORY_DIRECTORY, HUMAN_OPERATOR
from .schedule_model import HolidayCalendarReference

CALENDAR_FILE_NAME = "holiday_calendar.json"


def calendar_file(p12_root: Any) -> Path:
    return Path(p12_root) / AUTHORITY_DIRECTORY / CALENDAR_FILE_NAME


def _parse(text: str) -> HolidayCalendar:
    try:
        data = json.loads(text)
    except ValueError:
        raise AutomationError("CALENDAR_UNAVAILABLE", "CALENDAR_NOT_JSON") from None
    try:
        calendar = HolidayCalendar.from_dict(data)
    except AutomationError as exc:
        raise AutomationError("CALENDAR_UNAVAILABLE", exc.detail or "CALENDAR_INVALID") from None
    if calendar.to_json() + "\n" != text:
        raise AutomationError("CALENDAR_UNAVAILABLE", "CALENDAR_NOT_CANONICAL")
    return calendar


def read_calendar_authority(p12_root: Any, expected: Optional[HolidayCalendarReference] = None) -> HolidayCalendar:
    text = read_text_file(calendar_file(p12_root))
    if text is None:
        raise AutomationError("CALENDAR_UNAVAILABLE", "CALENDAR_MISSING")
    calendar = _parse(text)
    if expected is not None and calendar.reference() != expected:
        raise AutomationError("CALENDAR_UNAVAILABLE", "CALENDAR_REF_MISMATCH")
    return calendar


def write_calendar_authority(p12_root: Any, calendar: HolidayCalendar, *, operator: str) -> str:
    if operator != HUMAN_OPERATOR:
        raise AutomationError("SCHEMA_INVALID", "AUTHORITY_WRITE_NOT_HUMAN")
    if not isinstance(calendar, HolidayCalendar):
        raise AutomationError("SCHEMA_INVALID", "CALENDAR_TYPE")
    target = calendar_file(p12_root)
    existing_text = read_text_file(target)
    directory = ensure_root_subdirectory(p12_root, AUTHORITY_DIRECTORY)
    if existing_text is not None:
        existing = _parse(existing_text)
        if existing.content_digest == calendar.content_digest:
            return calendar.content_digest
        if existing.calendar_id != calendar.calendar_id:
            raise AutomationError("SCHEMA_INVALID", "CALENDAR_ID_CHANGED")
        if calendar.version <= existing.version:
            raise AutomationError("SCHEMA_INVALID", "VERSION_NOT_INCREASED")
        history = ensure_directory(directory / HISTORY_DIRECTORY)
        replace_atomically(history / f"holiday_calendar.{existing.content_digest}.json", existing_text.encode("utf-8"))
    replace_atomically(target, (calendar.to_json() + "\n").encode("utf-8"))
    return calendar.content_digest


__all__ = ["CALENDAR_FILE_NAME", "calendar_file", "read_calendar_authority", "write_calendar_authority"]
