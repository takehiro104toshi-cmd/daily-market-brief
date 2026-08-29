"""vNext共有ドメイン型（最小セット）。

Stage 1の方針:
- 旧AnalysisBundle（43フィールドのgod object）の轍を踏まず、ドメイン単位の
  小さなfrozen dataclassに分離する。
- FACT / ANALYSIS / FORECAST の分離を「文体」でなく「型」で強制する
  （EvidenceRecordの検証。docs/compass_dna/FACT_ANALYSIS_FORECAST_SPEC.md §5）。
- ここでは正式スキーマの確定はしない。Phase 1で拡張される前提の最小型定義のみ。
  フィールド追加は後方互換（default付き）で行う。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from enum import Enum, IntEnum
from typing import Optional, Tuple


class SourceTier(IntEnum):
    """情報源の信頼階層（knowledge/source_reliability/source_tiers.yaml と対応）。

    TIER1: 一次情報（政府・中央銀行・取引所・規制当局・企業公式）
    TIER2: 高信頼報道・市場データ
    TIER3: 一般ニュース・その他
    """

    TIER1 = 1
    TIER2 = 2
    TIER3 = 3


class StatementType(str, Enum):
    """文の種別。FACTとFORECASTを混同しないための中核タグ。"""

    FACT = "fact"
    FACT_UNVERIFIED = "fact_unverified"  # 伝聞・一部報道（語尾で減衰させて表示する）
    ANALYSIS = "analysis"
    FORECAST = "forecast"


class Horizon(str, Enum):
    """予測・分析の時間軸（Compass DNA JP-TIME-001 の語彙に対応）。"""

    INTRADAY = "intraday"
    ONE_DAY = "1d"
    ONE_WEEK = "1w"
    MEDIUM = "medium"
    LONG = "long"


# FORECASTの確信度は0〜5の整数（FACT_ANALYSIS_FORECAST_SPEC.md §3の語彙ラダーに対応。
# 5=投資妙味/押し目好機, 4=想定する, 3=期待, 2=注目, 1=可能性, 0=条件付き）
CONFIDENCE_MIN = 0
CONFIDENCE_MAX = 5


@dataclass(frozen=True)
class SourceMeta:
    """出典メタデータ。すべてのFACTはここへ遡れなければならない。"""

    name: str
    url: str
    tier: SourceTier
    retrieved_at: datetime


@dataclass(frozen=True)
class ForecastAttributes:
    """FORECAST文にのみ付与される属性。検証可能性（Phase 5）の最小要件。"""

    confidence: int  # CONFIDENCE_MIN..CONFIDENCE_MAX
    horizon: Horizon
    agent: str  # 予測主体: "system" / "会社計画" / "市場予想" など
    invalidation_condition: str = ""  # 無効化条件（空も許すがPhase 5で必須化予定）

    def __post_init__(self) -> None:
        if not (CONFIDENCE_MIN <= self.confidence <= CONFIDENCE_MAX):
            raise ValueError(
                f"confidence must be in [{CONFIDENCE_MIN}, {CONFIDENCE_MAX}], got {self.confidence}"
            )


@dataclass(frozen=True)
class EvidenceRecord:
    """文単位のEvidence（最小形）。Phase 1で正式拡張される。

    型レベルの不変条件:
    - statement_type == FORECAST のとき forecast 属性は必須。
    - FORECAST以外の文に forecast 属性を付けてはならない。
    """

    id: str
    statement_text: str
    statement_type: StatementType
    source: SourceMeta
    retrieved_at: datetime
    event_date: Optional[date] = None
    entities: Tuple[str, ...] = ()
    themes: Tuple[str, ...] = ()
    forecast: Optional[ForecastAttributes] = None

    def __post_init__(self) -> None:
        if self.statement_type is StatementType.FORECAST and self.forecast is None:
            raise ValueError("FORECAST record requires forecast attributes")
        if self.statement_type is not StatementType.FORECAST and self.forecast is not None:
            raise ValueError("only FORECAST records may carry forecast attributes")


@dataclass(frozen=True)
class MarketObservation:
    """市場指標の1観測値（時系列の1点）。

    unit/calc_method をデータ自身が持つ（Compass DNAの発見: 指標ごとに
    差分表現が異なる——%, %pt, 変化額, 乖離率——ため、値の解釈をメタデータ化する）。
    """

    metric_id: str  # 例: "nikkei225.close", "nikkei225.dev_25dma", "usdjpy.tokyo_0700"
    value: Optional[float]  # 欠測はNone（値の捏造をしない）
    unit: str  # 例: "index", "pct", "pct_point", "jpy", "trillion_jpy"
    as_of: datetime
    calc_method: str = "close"  # 例: "close", "pct_change_prev_close", "deviation_pct"
    source: str = ""


@dataclass(frozen=True)
class LLMResult:
    """LLM呼び出しの結果（provider中立）。"""

    text: str
    provider: str  # 実装側が名乗る識別子（例: "anthropic", "openai", "local"）
    model: str
    input_evidence_ids: Tuple[str, ...] = field(default=())
