"""date_quality（Phase 1-C）: source提供日時とinferredを絶対に混同しない。"""
from __future__ import annotations

from datetime import datetime, timezone

from src.intelligence.ingestion.date_quality import DateQuality, resolve_published

NOW = datetime(2026, 8, 30, 0, 0, tzinfo=timezone.utc)


def test_tz_aware_rfc822_is_source_provided() -> None:
    r = resolve_published("Fri, 28 Aug 2026 09:00:00 +0900", now=NOW)
    assert r.quality is DateQuality.SOURCE_PROVIDED_TZ
    assert r.parsed_utc == datetime(2026, 8, 28, 0, 0, tzinfo=timezone.utc)
    assert r.source_value == "Fri, 28 Aug 2026 09:00:00 +0900"  # 元文字列は常に保持
    assert r.anomaly == ""


def test_tz_aware_iso_is_source_provided() -> None:
    r = resolve_published("2026-08-28T10:30:00Z", now=NOW)
    assert r.quality is DateQuality.SOURCE_PROVIDED_TZ
    assert r.parsed_utc == datetime(2026, 8, 28, 10, 30, tzinfo=timezone.utc)


def test_naive_date_is_never_silently_assumed_utc() -> None:
    r = resolve_published("2026-08-28T10:30:00", now=NOW)
    assert r.quality is DateQuality.SOURCE_PROVIDED_NAIVE
    assert r.parsed_utc is None  # tz不明のまま確定させない（推測しない）
    assert r.source_value == "2026-08-28T10:30:00"


def test_missing_and_unparsable_are_distinct() -> None:
    assert resolve_published("", now=NOW).quality is DateQuality.MISSING
    assert resolve_published("yesterday-ish", now=NOW).quality is DateQuality.UNPARSABLE


def test_future_and_too_old_flagged_but_value_kept() -> None:
    fut = resolve_published("2026-09-15T00:00:00Z", now=NOW)
    assert fut.anomaly == "future" and fut.parsed_utc is not None  # 破棄しない・補正もしない
    old = resolve_published("1999-01-01T00:00:00Z", now=NOW)
    assert old.anomaly == "too_old" and old.parsed_utc is not None
