"""観測値（Observation）ドメインモデル（Phase 1-A / schema 0.2.0）。

Market Data・経済統計・決算数値を将来共通に扱う数値観測の型。

設計判断:
- **金融値はDecimal**（floatは構築時に拒否する）。0.1+0.2問題・価格の桁落ちを
  domain層から排除する。シリアライズは文字列で精度を保持。
- 欠測はNone（値の捏造をしない——Legacyの「取得不可」原則の型化）。
- raw（情報源から取得したままの値）とderived（本システムが計算した値）を区別し、
  derivedは **どの観測から**（inputs）**どの計算で**（calculation_method）を必須にする
  （MA乖離・相関係数などの派生指標のprovenance。Compass DNA MARKET_DATA_TAXONOMY対応）。
- as_of は「値が指す時点」（例: 終値の日時、CPIの基準月末）。公表時刻は
  SourceDocument.published_at、取得時刻は同retrieved_atが持つ——時刻の混同をしない。
- 統計の改定は上書きせず revision_of で新Observationを積む。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from enum import Enum
from typing import Optional, Tuple

from ..core.time import ensure_aware, ensure_aware_or_none
from ..core.types import SCHEMA_VERSION


class ObservationKind(str, Enum):
    RAW = "raw"          # 情報源の値そのまま
    DERIVED = "derived"  # 本システムが計算した値


@dataclass(frozen=True, kw_only=True)
class Observation:
    observation_id: str  # 時刻順ID: obs_<ULID>
    entity_id: str  # 対象（例: "index:nikkei225", "equity:7203.T", "macro:jp_cpi"）
    metric: str  # 指標名（例: "close", "yoy_pct", "eps", "dev_25dma"）
    value: Optional[Decimal]  # 欠測はNone。floatは拒否
    unit: str  # 例: "index", "pct", "pct_point", "jpy", "usd", "x"（倍率）
    as_of: datetime  # 値が指す時点（aware必須）
    kind: ObservationKind = ObservationKind.RAW
    currency: str = ""  # 通貨額のとき（例: "JPY", "USD"）。unitと重複しても明示する
    calculation_method: str = ""  # rawは取得方法（"close"等）/ derivedは計算式ID
    inputs: Tuple[str, ...] = field(default=())  # derivedの入力observation_id（provenance）
    source_id: str = ""  # 情報源（rawで必須）
    source_document_id: str = ""  # 由来文書（統計リリース等。無い取得経路は空）
    # Phase 2-A追加（0.x非破壊）: 市場系列への紐付け（databank/market_model.MarketSeries）。
    # 同じUSDJPYでもspot/Tokyo close/NY closeを別seriesとして区別するためのキー
    series_id: str = ""
    valid_from: Optional[datetime] = None
    valid_until: Optional[datetime] = None  # 改定で失効した場合等
    revision_of: Optional[str] = None  # 改定元observation_id（過去値は消さない）
    schema_version: str = SCHEMA_VERSION

    def __post_init__(self) -> None:
        if not self.observation_id:
            raise ValueError("observation_id is required")
        if not self.entity_id:
            raise ValueError("entity_id is required")
        if not self.metric:
            raise ValueError("metric is required")
        if not self.unit:
            raise ValueError("unit is required")
        if self.value is not None and not isinstance(self.value, Decimal):
            raise TypeError(
                f"Observation.value must be Decimal or None (got {type(self.value).__name__}; "
                "floatの金融値は精度問題のため禁止)"
            )
        ensure_aware(self.as_of, "Observation.as_of")
        ensure_aware_or_none(self.valid_from, "Observation.valid_from")
        ensure_aware_or_none(self.valid_until, "Observation.valid_until")
        if self.kind is ObservationKind.DERIVED:
            if not self.calculation_method:
                raise ValueError("derived observation requires calculation_method")
            if not self.inputs:
                raise ValueError("derived observation requires inputs (provenance)")
        else:
            if not self.source_id:
                raise ValueError("raw observation requires source_id")


def latest_revisions(observations: Tuple[Observation, ...]) -> Tuple[Observation, ...]:
    """改定で置換された観測を除いた最新版のみを返す（元データは消さない）。"""
    superseded = {o.revision_of for o in observations if o.revision_of}
    return tuple(o for o in observations if o.observation_id not in superseded)
