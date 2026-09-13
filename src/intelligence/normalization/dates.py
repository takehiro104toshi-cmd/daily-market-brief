"""日付正規化（Phase 1-D）。P1-C date_qualityの正式活用。

区別を必ず保持する:
    published_raw       … source供給の元文字列（常に保持）
    published_parsed    … tz付きで解析できた値のみ（UTC正規化）
    published_inferred  … 決定論ルールで推定した値（inferred=True・根拠をinferred_fromへ）
    date_quality        … SOURCE_PROVIDED_TZ / SOURCE_PROVIDED_NAIVE / UNPARSABLE / MISSING

規律:
- naive（tz欠落）はtimezoneを勝手に確定しない。
- retrieved_atをpublished_atへ**黙って代入しない**（推定はinferred=Trueで機械可読に）。
- published_at = unknown は正しい結果（値の捏造をしない）。
- 決定論: 異常判定（future/too_old）の基準時刻は**RawItem.retrieved_at**を使う
  （現在時刻に依存させない——同じRawItemからは常に同じ結果）。
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional

from ..ingestion.date_quality import DateQuality, resolve_published

#: P1-Dで許可する推定根拠（決定論ルールのみ。LLM・現在時刻・外部検索は不可）
INFERENCE_SOURCES = ("url_date",)

_URL_DATE_PATTERNS = (
    re.compile(r"/(20\d{2})/(\d{1,2})/(\d{1,2})(?:/|$)"),
    re.compile(r"[/_-](20\d{2})-(\d{2})-(\d{2})(?:[/_.-]|$)"),
    re.compile(r"/(20\d{2})(\d{2})(\d{2})(?:[/_.-]|$)"),
)


@dataclass(frozen=True, kw_only=True)
class NormalizedDate:
    raw: str  # source供給の元文字列（無ければ""）
    parsed_utc: Optional[datetime] = None  # tz付きsource提供のみ（UTC）
    quality: DateQuality = DateQuality.MISSING
    anomaly: str = ""  # "" / "future" / "too_old"
    inferred_utc: Optional[datetime] = None  # 決定論的推定値（日付精度）
    inferred: bool = False
    inferred_from: str = ""  # INFERENCE_SOURCESのいずれか

    @property
    def adopted_utc(self) -> Optional[datetime]:
        """SourceDocument.published_atへ採用する値。

        source提供のtz付き・異常なし → その値。無ければ推定値（inferredフラグは
        呼び出し側がdocへ転記する）。どちらも無ければNone（unknownは正しい結果）。
        異常（future/too_old）のsource値は採用しない（値自体はraw/parsedに保持）。
        """
        if self.parsed_utc is not None and not self.anomaly:
            return self.parsed_utc
        return self.inferred_utc


def infer_date_from_url(url: str) -> Optional[datetime]:
    """URLパスの日付パターンから日付（UTC 00:00・日付精度）を決定論的に推定する。"""
    if not url:
        return None
    for pattern in _URL_DATE_PATTERNS:
        m = pattern.search(url)
        if m:
            year, month, day = int(m.group(1)), int(m.group(2)), int(m.group(3))
            try:
                return datetime(year, month, day, tzinfo=timezone.utc)
            except ValueError:
                continue  # 13月等の偽パターンは推定しない
    return None


def normalize_published(
    raw_value: str,
    *,
    fallback_raw: str = "",
    link: str = "",
    reference_time: datetime,
) -> NormalizedDate:
    """published日時を正規化する。

    reference_time: 異常判定（future/too_old）の基準。**RawItem.retrieved_atを渡す**
    （現在時刻を使わない＝決定論）。
    raw_valueが空ならfallback_raw（updated等）を試す。
    """
    chosen = (raw_value or "").strip() or (fallback_raw or "").strip()
    resolved = resolve_published(chosen, now=reference_time)

    inferred_utc: Optional[datetime] = None
    inferred_from = ""
    # source提供のtz付き正常値が無い場合のみ、決定論的推定を試みる
    if resolved.parsed_utc is None or resolved.anomaly:
        url_date = infer_date_from_url(link)
        if url_date is not None:
            inferred_utc = url_date
            inferred_from = "url_date"

    return NormalizedDate(
        raw=resolved.source_value,
        parsed_utc=resolved.parsed_utc,
        quality=resolved.quality,
        anomaly=resolved.anomaly,
        inferred_utc=inferred_utc,
        inferred=inferred_utc is not None,
        inferred_from=inferred_from,
    )
