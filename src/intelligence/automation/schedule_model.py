"""P12-A1 — schedule の authority の純粋な model（運用の authority ・市場の authority ではない）。

- `AutomationSchedule`: schedule_id ・version ・timezone（v1 は `Asia/Tokyo` だけ ・暗黙の timezone 無し）・enabled ・slots ・
  holiday_calendar_ref ・created_at（人が宣言した aware な瞬間。内容の一部）・supersedes ・schema_version。`content_digest` は
  正準 JSON（digest 自身を除く）の domain 付き sha256（hash-addressed。署名ではない）。
- `ScheduleSlot`: slot_id ・local_time（HH:MM）・weekday_mask（明示 ・既定なし）・late_window_seconds（明示 ・既定なし）・
  readiness_on_non_business_day ・enabled。
- 未知の鍵 ・欠けた鍵 ・型の違い ・v1 以外の timezone は fail closed（`AutomationError("SCHEMA_INVALID", ...)`）。
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import timedelta, timezone
from typing import Any, Dict, Mapping, Optional, Tuple

from .canonical import (canonical_json, domain_digest, is_digest, parse_utc_iso, require_fields, utc_iso)
from .failure_codes import AutomationError

SCHEDULE_SCHEMA_VERSION = "p12_automation_schedule:0.1.0"
SCHEDULE_DIGEST_DOMAIN = "p12.automation_schedule.v1"
TIMEZONE_V1 = "Asia/Tokyo"
#: Asia/Tokyo は DST を持たない: 固定の +09:00 を名前付きで使う（tzdata に依らず Windows でも決定論）
TOKYO = timezone(timedelta(hours=9), TIMEZONE_V1)
WEEKDAYS: Tuple[str, ...] = ("MON", "TUE", "WED", "THU", "FRI", "SAT", "SUN")
MAX_SLOTS = 32
MAX_LATE_WINDOW_SECONDS = 86399
_ID_RE = re.compile(r"\A[a-z][a-z0-9_-]{0,39}\Z")
_LOCAL_TIME_RE = re.compile(r"\A([01]\d|2[0-3]):[0-5]\d\Z")
_SLOT_FIELDS = frozenset({"slot_id", "local_time", "weekday_mask", "late_window_seconds", "readiness_on_non_business_day",
                          "enabled"})
_REF_FIELDS = frozenset({"calendar_id", "version", "content_digest"})
_SCHEDULE_FIELDS = frozenset({"schema_version", "schedule_id", "version", "timezone", "enabled", "slots",
                              "holiday_calendar_ref", "created_at", "supersedes", "content_digest"})


def _require_id(value: Any, context: str) -> str:
    if not isinstance(value, str) or not _ID_RE.match(value):
        raise AutomationError("SCHEMA_INVALID", f"{context}_ID")
    return value


def _require_bool(value: Any, context: str) -> bool:
    if not isinstance(value, bool):
        raise AutomationError("SCHEMA_INVALID", f"{context}_NOT_BOOL")
    return value


def _require_int(value: Any, context: str, low: int, high: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not low <= value <= high:
        raise AutomationError("SCHEMA_INVALID", f"{context}_RANGE")
    return value


@dataclass(frozen=True)
class HolidayCalendarReference:
    """schedule が参照する休日 calendar の identity（id ・版 ・内容の digest）。"""

    calendar_id: str
    version: int
    content_digest: str

    def __post_init__(self) -> None:
        _require_id(self.calendar_id, "CALENDAR")
        _require_int(self.version, "CALENDAR_VERSION", 1, 10 ** 6)
        if not is_digest(self.content_digest):
            raise AutomationError("SCHEMA_INVALID", "CALENDAR_DIGEST")

    def to_dict(self) -> Dict[str, Any]:
        return {"calendar_id": self.calendar_id, "version": self.version, "content_digest": self.content_digest}

    @classmethod
    def from_dict(cls, data: Any) -> "HolidayCalendarReference":
        fields = require_fields(data, _REF_FIELDS, "CALENDAR_REF")
        return cls(calendar_id=fields["calendar_id"], version=fields["version"], content_digest=fields["content_digest"])


@dataclass(frozen=True)
class ScheduleSlot:
    slot_id: str
    local_time: str
    weekday_mask: Tuple[str, ...]
    late_window_seconds: int
    readiness_on_non_business_day: bool
    enabled: bool

    def __post_init__(self) -> None:
        _require_id(self.slot_id, "SLOT")
        if not isinstance(self.local_time, str) or not _LOCAL_TIME_RE.match(self.local_time):
            raise AutomationError("SCHEMA_INVALID", "SLOT_LOCAL_TIME")
        mask = self.weekday_mask
        if not isinstance(mask, tuple) or not mask or len(set(mask)) != len(mask) or any(d not in WEEKDAYS for d in mask):
            raise AutomationError("SCHEMA_INVALID", "SLOT_WEEKDAY_MASK")
        if tuple(sorted(mask, key=WEEKDAYS.index)) != mask:
            raise AutomationError("SCHEMA_INVALID", "SLOT_WEEKDAY_MASK_ORDER")            # 正準の順（MON → SUN）だけ
        _require_int(self.late_window_seconds, "SLOT_LATE_WINDOW", 0, MAX_LATE_WINDOW_SECONDS)
        _require_bool(self.readiness_on_non_business_day, "SLOT_READINESS")
        _require_bool(self.enabled, "SLOT_ENABLED")

    @property
    def hour(self) -> int:
        return int(self.local_time[:2])

    @property
    def minute(self) -> int:
        return int(self.local_time[3:])

    def to_dict(self) -> Dict[str, Any]:
        return {"slot_id": self.slot_id, "local_time": self.local_time, "weekday_mask": list(self.weekday_mask),
                "late_window_seconds": self.late_window_seconds,
                "readiness_on_non_business_day": self.readiness_on_non_business_day, "enabled": self.enabled}

    @classmethod
    def from_dict(cls, data: Any) -> "ScheduleSlot":
        fields = require_fields(data, _SLOT_FIELDS, "SLOT")
        mask = fields["weekday_mask"]
        if not isinstance(mask, list):
            raise AutomationError("SCHEMA_INVALID", "SLOT_WEEKDAY_MASK")
        return cls(slot_id=fields["slot_id"], local_time=fields["local_time"], weekday_mask=tuple(mask),
                   late_window_seconds=fields["late_window_seconds"],
                   readiness_on_non_business_day=fields["readiness_on_non_business_day"], enabled=fields["enabled"])


@dataclass(frozen=True)
class AutomationSchedule:
    schedule_id: str
    version: int
    timezone: str
    enabled: bool
    slots: Tuple[ScheduleSlot, ...]
    holiday_calendar_ref: HolidayCalendarReference
    created_at: str                                   # aware な瞬間の UTC ISO（人の宣言。内容の一部 ・時計ではない）
    supersedes: Optional[str] = None                  # 前の版の content_digest（鎖の説明。identity ではない）
    schema_version: str = SCHEDULE_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.schema_version != SCHEDULE_SCHEMA_VERSION:
            raise AutomationError("SCHEMA_INVALID", "SCHEDULE_SCHEMA_VERSION")
        _require_id(self.schedule_id, "SCHEDULE")
        _require_int(self.version, "SCHEDULE_VERSION", 1, 10 ** 6)
        if self.timezone != TIMEZONE_V1:
            raise AutomationError("SCHEMA_INVALID", "TIMEZONE_NOT_SUPPORTED")
        _require_bool(self.enabled, "SCHEDULE_ENABLED")
        if not isinstance(self.slots, tuple) or not self.slots or len(self.slots) > MAX_SLOTS \
                or not all(isinstance(s, ScheduleSlot) for s in self.slots):
            raise AutomationError("SCHEMA_INVALID", "SCHEDULE_SLOTS")
        ids = [s.slot_id for s in self.slots]
        if len(set(ids)) != len(ids):
            raise AutomationError("SCHEMA_INVALID", "SLOT_ID_DUPLICATE")
        if ids != sorted(ids):
            raise AutomationError("SCHEMA_INVALID", "SLOT_ORDER")                           # 正準の順（slot_id）だけ
        if not isinstance(self.holiday_calendar_ref, HolidayCalendarReference):
            raise AutomationError("SCHEMA_INVALID", "CALENDAR_REF")
        if utc_iso(parse_utc_iso(self.created_at)) != self.created_at:
            raise AutomationError("SCHEMA_INVALID", "CREATED_AT_NOT_CANONICAL")
        if self.supersedes is not None and not is_digest(self.supersedes):
            raise AutomationError("SCHEMA_INVALID", "SUPERSEDES_DIGEST")

    def slot(self, slot_id: str) -> Optional[ScheduleSlot]:
        for candidate in self.slots:
            if candidate.slot_id == slot_id:
                return candidate
        return None

    def content(self) -> Dict[str, Any]:
        """digest の対象（content_digest 自身を除く）。"""
        return {"schema_version": self.schema_version, "schedule_id": self.schedule_id, "version": self.version,
                "timezone": self.timezone, "enabled": self.enabled, "slots": [s.to_dict() for s in self.slots],
                "holiday_calendar_ref": self.holiday_calendar_ref.to_dict(), "created_at": self.created_at,
                "supersedes": self.supersedes}

    @property
    def content_digest(self) -> str:
        return domain_digest(SCHEDULE_DIGEST_DOMAIN, self.content())

    def to_dict(self) -> Dict[str, Any]:
        return {**self.content(), "content_digest": self.content_digest}

    def to_json(self) -> str:
        return canonical_json(self.to_dict())

    @classmethod
    def from_dict(cls, data: Any) -> "AutomationSchedule":
        fields = require_fields(data, _SCHEDULE_FIELDS, "SCHEDULE")
        slots_raw = fields["slots"]
        if not isinstance(slots_raw, list):
            raise AutomationError("SCHEMA_INVALID", "SCHEDULE_SLOTS")
        schedule = cls(schedule_id=fields["schedule_id"], version=fields["version"], timezone=fields["timezone"],
                       enabled=fields["enabled"], slots=tuple(ScheduleSlot.from_dict(s) for s in slots_raw),
                       holiday_calendar_ref=HolidayCalendarReference.from_dict(fields["holiday_calendar_ref"]),
                       created_at=fields["created_at"], supersedes=fields["supersedes"],
                       schema_version=fields["schema_version"])
        if fields["content_digest"] != schedule.content_digest:
            raise AutomationError("SCHEMA_INVALID", "SCHEDULE_DIGEST_MISMATCH")                # 内容と digest の不一致は拒む
        return schedule


__all__ = ["AutomationSchedule", "HolidayCalendarReference", "MAX_LATE_WINDOW_SECONDS", "MAX_SLOTS",
           "SCHEDULE_DIGEST_DOMAIN", "SCHEDULE_SCHEMA_VERSION", "ScheduleSlot", "TIMEZONE_V1", "TOKYO", "WEEKDAYS"]
