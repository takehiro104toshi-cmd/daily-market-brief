"""日付正規化（Phase 1-D）: source提供/推定の分離・決定論・silent substitution禁止。"""
from __future__ import annotations

from datetime import datetime, timezone

from src.intelligence.ingestion.date_quality import DateQuality
from src.intelligence.normalization.dates import (
    infer_date_from_url,
    normalize_published,
)

REF = datetime(2026, 8, 30, 12, 0, tzinfo=timezone.utc)  # RawItem.retrieved_at相当


def test_tz_provided_date_is_adopted() -> None:
    d = normalize_published("Fri, 28 Aug 2026 09:00:00 +0900", reference_time=REF)
    assert d.quality is DateQuality.SOURCE_PROVIDED_TZ
    assert d.adopted_utc == datetime(2026, 8, 28, 0, 0, tzinfo=timezone.utc)
    assert not d.inferred


def test_naive_date_not_adopted_and_no_tz_guess() -> None:
    d = normalize_published("2026-08-28T10:30:00", reference_time=REF)
    assert d.quality is DateQuality.SOURCE_PROVIDED_NAIVE
    assert d.parsed_utc is None and d.adopted_utc is None  # timezoneを勝手に確定しない
    assert d.raw == "2026-08-28T10:30:00"  # 元文字列は保持


def test_missing_date_unknown_is_valid_result() -> None:
    d = normalize_published("", reference_time=REF)
    assert d.quality is DateQuality.MISSING
    assert d.adopted_utc is None  # published_at = unknown は正しい結果
    assert not d.inferred  # retrieved_atを黙って代入していない


def test_fallback_to_updated_raw() -> None:
    d = normalize_published("", fallback_raw="2026-08-28T10:30:00Z", reference_time=REF)
    assert d.adopted_utc == datetime(2026, 8, 28, 10, 30, tzinfo=timezone.utc)


def test_url_date_inference_is_deterministic_and_flagged() -> None:
    d = normalize_published(
        "", link="https://example.org/news/2026/08/29/article-slug", reference_time=REF)
    assert d.inferred and d.inferred_from == "url_date"
    assert d.inferred_utc == datetime(2026, 8, 29, tzinfo=timezone.utc)
    assert d.adopted_utc == d.inferred_utc
    assert d.parsed_utc is None  # source提供値とinferred値を混同しない


def test_url_inference_not_used_when_source_date_good() -> None:
    d = normalize_published(
        "2026-08-28T10:30:00Z", link="https://example.org/2026/01/01/a", reference_time=REF)
    assert not d.inferred
    assert d.adopted_utc == datetime(2026, 8, 28, 10, 30, tzinfo=timezone.utc)


def test_anomalous_source_date_is_flagged_not_adopted() -> None:
    d = normalize_published("2027-05-01T00:00:00Z", reference_time=REF)
    assert d.anomaly == "future"
    assert d.parsed_utc is not None  # 値は保持（破棄しない）
    assert d.adopted_utc is None  # だが採用しない（silent correctionなし）


def test_determinism_uses_reference_time_not_now() -> None:
    """同じRawItem（同じretrieved_at）→ 常に同じ結果（現在時刻非依存）。"""
    a = normalize_published("2026-09-05T00:00:00Z", reference_time=REF)
    b = normalize_published("2026-09-05T00:00:00Z", reference_time=REF)
    assert a == b
    old_ref = datetime(2026, 9, 10, tzinfo=timezone.utc)
    c = normalize_published("2026-09-05T00:00:00Z", reference_time=old_ref)
    assert a.anomaly == "future" and c.anomaly == ""  # 判定基準はreference_timeのみ


def test_invalid_url_dates_rejected() -> None:
    assert infer_date_from_url("https://e.org/2026/13/45/x") is None
    assert infer_date_from_url("https://e.org/plain/path") is None
    assert infer_date_from_url("") is None
