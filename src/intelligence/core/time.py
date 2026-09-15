"""時刻モデルの基盤（Phase 1-A）。

原則:
- vNextの全datetimeは **timezone-aware必須**（naiveは構築時に拒否する）。
- 特定タイムゾーン（JST等）への固定は禁止。保存はawareのまま、
  シリアライズはUTCオフセット付きISO 8601。
- 意味の異なる時刻を混同しない:
    event_time    … 出来事が起きた時刻（声明の対象事象・観測値の基準時点）
    published_at  … 情報源が公表した時刻
    retrieved_at  … 本システムが取得した時刻
    valid_from / valid_until … その記録が有効な期間（改定・失効の表現）
    created_at / generated_at … 本システム内でレコード/分析/予測を生成した時刻
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional


def ensure_aware(value: datetime, field_name: str) -> datetime:
    """timezone-awareであることを強制する。naiveならValueError。"""
    if value.tzinfo is None or value.tzinfo.utcoffset(value) is None:
        raise ValueError(f"{field_name} must be timezone-aware (naive datetime rejected)")
    return value


def ensure_aware_or_none(value: Optional[datetime], field_name: str) -> Optional[datetime]:
    if value is None:
        return None
    return ensure_aware(value, field_name)


def to_utc_iso(value: datetime) -> str:
    """シリアライズ用: UTCへ正規化したISO 8601文字列。"""
    return value.astimezone(timezone.utc).isoformat()


def from_iso(value: str) -> datetime:
    dt = datetime.fromisoformat(value)
    return ensure_aware(dt, "serialized datetime")
