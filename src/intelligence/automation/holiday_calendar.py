"""P12-A1 — 休日 calendar の純粋な model（人が維持する運用の authority。市場の authority ではない）。

- `HolidayCalendar`: calendar_id ・version ・dates（YYYY-MM-DD の sort 済み ・重複なし）・schema_version。`content_digest` は
  domain 付き sha256。`reference()` が schedule の `HolidayCalendarReference` と一致しなければ planner は CALENDAR_UNAVAILABLE。
- 営業日 ＝ 月〜金 かつ calendar の休日でない日。週末 ・休日の意味はここだけで決める（planner は問い合わせるだけ）。
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any, Dict, Optional, Tuple

from .canonical import canonical_json, date_iso, domain_digest, parse_date_iso, require_fields
from .failure_codes import AutomationError
from .schedule_model import HolidayCalendarReference, _require_id, _require_int

CALENDAR_SCHEMA_VERSION = "p12_holiday_calendar:0.1.0"
CALENDAR_DIGEST_DOMAIN = "p12.holiday_calendar.v1"
MAX_HOLIDAYS = 4000
MAX_SESSION_LOOKBACK_DAYS = 14
_CALENDAR_FIELDS = frozenset({"schema_version", "calendar_id", "version", "dates", "content_digest"})


@dataclass(frozen=True)
class HolidayCalendar:
    calendar_id: str
    version: int
    dates: Tuple[str, ...]
    schema_version: str = CALENDAR_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.schema_version != CALENDAR_SCHEMA_VERSION:
            raise AutomationError("SCHEMA_INVALID", "CALENDAR_SCHEMA_VERSION")
        _require_id(self.calendar_id, "CALENDAR")
        _require_int(self.version, "CALENDAR_VERSION", 1, 10 ** 6)
        if not isinstance(self.dates, tuple) or len(self.dates) > MAX_HOLIDAYS:
            raise AutomationError("SCHEMA_INVALID", "CALENDAR_DATES")
        parsed = [date_iso(parse_date_iso(d)) for d in self.dates]
        if parsed != list(self.dates) or sorted(set(parsed)) != list(self.dates):
            raise AutomationError("SCHEMA_INVALID", "CALENDAR_DATES_ORDER")                  # sort 済み ・重複なし ・正準

    def content(self) -> Dict[str, Any]:
        return {"schema_version": self.schema_version, "calendar_id": self.calendar_id, "version": self.version,
                "dates": list(self.dates)}

    @property
    def content_digest(self) -> str:
        return domain_digest(CALENDAR_DIGEST_DOMAIN, self.content())

    def reference(self) -> HolidayCalendarReference:
        return HolidayCalendarReference(calendar_id=self.calendar_id, version=self.version,
                                        content_digest=self.content_digest)

    def to_dict(self) -> Dict[str, Any]:
        return {**self.content(), "content_digest": self.content_digest}

    def to_json(self) -> str:
        return canonical_json(self.to_dict())

    @classmethod
    def from_dict(cls, data: Any) -> "HolidayCalendar":
        fields = require_fields(data, _CALENDAR_FIELDS, "CALENDAR")
        if not isinstance(fields["dates"], list):
            raise AutomationError("SCHEMA_INVALID", "CALENDAR_DATES")
        calendar = cls(calendar_id=fields["calendar_id"], version=fields["version"], dates=tuple(fields["dates"]),
                       schema_version=fields["schema_version"])
        if fields["content_digest"] != calendar.content_digest:
            raise AutomationError("SCHEMA_INVALID", "CALENDAR_DIGEST_MISMATCH")
        return calendar

    def is_holiday(self, day: date) -> bool:
        return date_iso(day) in self.dates

    def is_business_day(self, day: date) -> bool:
        return day.weekday() < 5 and not self.is_holiday(day)

    def last_business_day_on_or_before(self, day: date) -> Optional[date]:
        """`day` 以前の直近の営業日（最大 MAX_SESSION_LOOKBACK_DAYS 日まで戻る。無ければ None）。"""
        for offset in range(MAX_SESSION_LOOKBACK_DAYS + 1):
            candidate = day - timedelta(days=offset)
            if self.is_business_day(candidate):
                return candidate
        return None


__all__ = ["CALENDAR_DIGEST_DOMAIN", "CALENDAR_SCHEMA_VERSION", "HolidayCalendar", "MAX_HOLIDAYS",
           "MAX_SESSION_LOOKBACK_DAYS"]
