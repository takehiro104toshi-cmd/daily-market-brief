"""Provider応答 → Observation の決定論的正規化（Phase 2-D PART D）。

原則:
- **Decimalはstringトークンから直接**生成する（floatを経由しない）。
- 欠測は欠測のまま（value=None / 行なし）。0・前日値・補間で**埋めない**。
- trading_date（セッション日）と as_of（値が指す時点のUTC時刻）を分離する。
  as_ofの導出規約はカタログのas_of_policy（exchange_close / day_end_utc）で系列ごとに固定。
- サニティ検査は**検知のみ**（週末日付・未来日付・重複行等をissueとして申告。
  知識で値を「補正」することは絶対にしない）。
- observation_idはcontent-addressed（同一series×日×source×値→同一ID＝冪等）。
  同一(series, trading_date)で値が変わった場合は**新Observation＋revision_of**
  （旧値は消さない——PART E REVISION）。
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, time, timezone
from datetime import date as date_type
from decimal import Decimal, InvalidOperation
from typing import Dict, Mapping, Optional, Tuple
from zoneinfo import ZoneInfo

from ..core.ids import content_id
from .model import Observation, ObservationKind
from .providers import ProviderFetchResult
from .series_catalog import SeriesSpec

#: 本ingestの版（挙動変更時はversionを上げ、run manifestへ記録する）
INGEST_VERSION = "market_daily_ingest:1.0.0"

#: rawのcalculation_method（取得方法の申告——providerの日足close）
RAW_METHOD = "provider_daily_close"


def as_of_for(spec: SeriesSpec, trading_date: str) -> datetime:
    """セッションモデル: trading_date → as_of（UTC・aware）。

    - exchange_close: 取引所ローカルのclose時刻をUTCへ変換した確定時刻
      （例: 2026-08-28の日経終値 → 2026-08-28 15:30 JST = 06:30 UTC）。
    - day_end_utc: 単一クローズが定義できない系列の固定規約
      （trading_date 23:59:59Z——「当日中のどこか」を明示。時刻の捏造をしない）。
    """
    day = date_type.fromisoformat(trading_date)
    if spec.as_of_policy == "exchange_close":
        hh, mm = spec.close_time_local.split(":")
        local = datetime.combine(day, time(int(hh), int(mm)), tzinfo=ZoneInfo(spec.timezone))
        return local.astimezone(timezone.utc)
    return datetime(day.year, day.month, day.day, 23, 59, 59, tzinfo=timezone.utc)


def observation_id_for(
    series_id: str, trading_date: str, source_id: str, metric: str, value_token: str
) -> str:
    """決定論ID: 同一(series, 日, source, 値)→同一ID（再取得・再実行が冪等になる）。"""
    return content_id("obs", series_id, trading_date, source_id, metric,
                      value_token if value_token else "MISSING")


@dataclass(frozen=True, kw_only=True)
class IngestOutcome:
    """1系列・1取得分の正規化結果（observationsは trading_date昇順）。"""

    series_id: str
    provider_id: str
    records_seen: int = 0
    observations: Tuple[Observation, ...] = ()
    new_revisions: Tuple[Tuple[str, str], ...] = ()  # (旧observation_id, 新observation_id)
    source_changes: Tuple[str, ...] = ()  # "日付:旧source->新source"（silent switch禁止の記録）
    issues: Tuple[str, ...] = ()  # サニティ検知（検知のみ・補正しない）
    skipped: int = 0  # 数値化不能等でObservationを作らなかった行数（issuesに理由あり）


def build_observations(
    spec: SeriesSpec,
    result: ProviderFetchResult,
    *,
    existing_by_date: Mapping[str, Observation] = {},
    source_document_id: str = "",
) -> IngestOutcome:
    """ProviderFetchResult → IngestOutcome（純関数・I/Oなし）。

    existing_by_date: 既存canonicalの (trading_date → 最新Observation)。
    値が変わった行はrevision_of付きの新Observationになる（上書きしない）。
    """
    issues = []
    observations = []
    revisions = []
    source_changes = []
    skipped = 0
    seen_dates: Dict[str, int] = {}
    retrieved_date = result.retrieved_at.astimezone(timezone.utc).date()

    for record in sorted(result.records, key=lambda r: r.trading_date):
        day = record.trading_date
        if day in seen_dates:
            issues.append(f"duplicate_trading_date:{day}")
            skipped += 1
            continue
        seen_dates[day] = record.line_no

        weekday = date_type.fromisoformat(day).weekday()
        if spec.calendar == "weekdays" and weekday >= 5:
            issues.append(f"weekend_trading_date:{day}")  # 検知のみ（保存はする）
        if date_type.fromisoformat(day) > retrieved_date:
            issues.append(f"trading_date_in_future:{day}")

        token = record.close
        value: Optional[Decimal]
        if token == "":
            value = None
            issues.append(f"missing_close_token:{day}")
        else:
            try:
                value = Decimal(token)  # stringトークンから直接（float非経由）
            except InvalidOperation:
                issues.append(f"invalid_close_token:{day}:{token[:20]}")
                skipped += 1
                continue

        obs_id = observation_id_for(
            spec.series_id, day, result.provider_id, spec.series.metric, token)
        existing = existing_by_date.get(day)
        revision_of: Optional[str] = None
        if existing is not None:
            if existing.observation_id == obs_id:
                continue  # 完全同一（同ID同内容）——canonical追記不要
            if existing.source_id != result.provider_id:
                if existing.value == value:
                    # 別providerが同値を確認——重複保存せず記録のみ（cross-source比較はQA報告側）
                    issues.append(f"source_change_confirmed_equal:{day}")
                    continue
                source_changes.append(f"{day}:{existing.source_id}->{result.provider_id}")
            revision_of = existing.observation_id
            revisions.append((existing.observation_id, obs_id))

        observations.append(Observation(
            observation_id=obs_id,
            entity_id=spec.series.instrument_id,
            metric=spec.series.metric,
            value=value,
            unit=spec.unit,
            as_of=as_of_for(spec, day),
            kind=ObservationKind.RAW,
            currency=spec.currency,
            calculation_method=RAW_METHOD,
            source_id=result.provider_id,
            source_document_id=source_document_id,
            series_id=spec.series_id,
            trading_date=day,
            revision_of=revision_of,
        ))

    return IngestOutcome(
        series_id=spec.series_id,
        provider_id=result.provider_id,
        records_seen=len(result.records),
        observations=tuple(observations),
        new_revisions=tuple(revisions),
        source_changes=tuple(source_changes),
        issues=tuple(issues),
        skipped=skipped,
    )
