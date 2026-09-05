"""日付品質（Phase 1-C。tank date_quality.py の概念移植・vNext時刻規律へ適合）。

監督者決定（P1-A Open Question②）:
- source提供日時とinferred日時を**絶対に混同しない**。
- P1-Cでは日付をFactとして確定しない。分類して保持するだけ。

tankとの差分（意図的）:
- tankは異常日付をfetched_atへ**補正して**date_inferred=Trueを立てた。
  vNextでは補正済み値を正として保存せず、ResolvedDate（分類結果）を返すに留める。
  fetched_atへのフォールバック採用はP1-D正規化層の明示判断とする。
- naive日時（tz欠落）はUTC仮定で確定させない（SOURCE_PROVIDED_NAIVEとして区別保持）。
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from enum import Enum
from typing import Optional

DEFAULT_MAX_FUTURE_HOURS = 24  # tank実運用値: フィード時刻ずれの許容幅
DEFAULT_MAX_AGE_YEARS = 20     # これより古い日付は異常とみなす（値は保持・採用はしない）


class DateQuality(str, Enum):
    SOURCE_PROVIDED_TZ = "source_provided_tz"        # tz付きで供給→そのまま使える
    SOURCE_PROVIDED_NAIVE = "source_provided_naive"  # 供給されたがtz欠落→確定させない
    UNPARSABLE = "unparsable"                        # 供給されたが解析不能
    MISSING = "missing"                              # 供給なし


@dataclass(frozen=True, kw_only=True)
class ResolvedDate:
    """source提供日時の分類結果。inferred値はここには存在しない（P1-Dの責務）。"""

    source_value: str  # フィードが供給した元文字列（常に保持。無ければ""）
    parsed_utc: Optional[datetime] = None  # tz付きで解析できた場合のみ（UTC正規化）
    quality: DateQuality = DateQuality.MISSING
    anomaly: str = ""  # "" / "future" / "too_old"（値は保持しつつ異常フラグ）


def _try_parse(value: str) -> tuple[Optional[datetime], bool]:
    """(datetime, tz_aware) を返す。両形式（RFC3339/ISO・RFC822）を試す。"""
    v = value.strip()
    try:
        dt = datetime.fromisoformat(v.replace("Z", "+00:00"))
        return dt, dt.tzinfo is not None
    except (ValueError, TypeError):
        pass
    try:
        dt = parsedate_to_datetime(v)
        if dt is not None:
            return dt, dt.tzinfo is not None
    except (TypeError, ValueError, IndexError):
        pass
    return None, False


def resolve_published(
    source_value: str,
    *,
    now: Optional[datetime] = None,
    max_future_hours: int = DEFAULT_MAX_FUTURE_HOURS,
    max_age_years: int = DEFAULT_MAX_AGE_YEARS,
) -> ResolvedDate:
    """フィード供給の公開日時文字列を分類する（推測しない・補正しない・破棄しない）。"""
    raw = (source_value or "").strip()
    if not raw:
        return ResolvedDate(source_value="", quality=DateQuality.MISSING)
    dt, aware = _try_parse(raw)
    if dt is None:
        return ResolvedDate(source_value=raw, quality=DateQuality.UNPARSABLE)
    if not aware:
        return ResolvedDate(source_value=raw, quality=DateQuality.SOURCE_PROVIDED_NAIVE)
    utc = dt.astimezone(timezone.utc)
    now = now or datetime.now(timezone.utc)
    anomaly = ""
    if utc > now + timedelta(hours=max_future_hours):
        anomaly = "future"  # 値は保持する（採用判断はP1-D。tankの「破棄しない」原則を継承）
    elif utc < now - timedelta(days=365 * max_age_years):
        anomaly = "too_old"
    return ResolvedDate(
        source_value=raw,
        parsed_utc=utc,
        quality=DateQuality.SOURCE_PROVIDED_TZ,
        anomaly=anomaly,
    )
