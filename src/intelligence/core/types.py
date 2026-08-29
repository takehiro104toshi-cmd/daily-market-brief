"""vNext共有プリミティブ（schema 0.2.0 / Phase 1-A）。

Stage 1版（0.1）からの変更（0.xのためbackward compatibility非保証・意図的な破壊的変更）:
- EvidenceRecord / SourceMeta / ForecastAttributes / MarketObservation を廃止し、
  正式ドメインモデルへ再配置した:
    出所（provenance）  → src/intelligence/sources/model.py  (Source / SourceDocument / RawItem)
    観測値              → src/intelligence/market/model.py   (Observation)
    言明（claim）        → src/intelligence/evidence/model.py (Fact/Analysis/ForecastStatement,
                                                              ForecastMetadata, EvidenceLink)
- StatementTypeからFACT_UNVERIFIEDを削除（伝聞はFactStatement.attribution=REPORTED、
  裏付け無しはVerificationState.UNSUPPORTEDとして直交表現する）。
- VerificationState（検証状態）を新設。source tier・confidenceとは独立の軸
  （tier=情報源の格 / verification=裏付け状態 / confidence=予測の確信度）。

本モジュールに置くのは「複数ドメインが共有する列挙・定数・LLM境界型」のみ。
God Model禁止——ドメイン型は各ドメインパッケージが所有する。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum, IntEnum
from typing import Tuple

SCHEMA_VERSION = "0.2.0"


class SourceTier(IntEnum):
    """情報源の格（knowledge/source_reliability/ と対応）。

    真実性の確率・検証状態・確信度そのものではない（別フィールドで扱う）。
    TIER1: 一次情報（中央銀行・政府統計・取引所・企業IR・規制当局）
    TIER2: 高品質なセカンダリソース（主要報道・市場データ）
    TIER3: 一般ニュース等
    """

    TIER1 = 1
    TIER2 = 2
    TIER3 = 3


class StatementType(str, Enum):
    """言明の種別。FACTとFORECASTを混同しないための中核タグ。"""

    FACT = "fact"
    ANALYSIS = "analysis"
    FORECAST = "forecast"


class VerificationState(str, Enum):
    """検証状態（source tierとは独立の軸）。

    UNVERIFIED  … 未検証（初期状態）
    VERIFIED    … 裏付けEvidenceで確認済み
    CONFLICTING … 相反するEvidenceが併存（どちらも自動削除しない）
    STALE       … 有効期限切れ・鮮度喪失
    RETRACTED   … 情報源自身が撤回
    UNSUPPORTED … 裏付けEvidenceが存在しない（FACTを名乗る資格がない状態）
    """

    UNVERIFIED = "unverified"
    VERIFIED = "verified"
    CONFLICTING = "conflicting"
    STALE = "stale"
    RETRACTED = "retracted"
    UNSUPPORTED = "unsupported"


class Horizon(str, Enum):
    """時間軸（Compass DNA JP-TIME-001 の語彙に対応）。"""

    INTRADAY = "intraday"
    ONE_DAY = "1d"
    ONE_WEEK = "1w"
    MEDIUM = "medium"
    LONG = "long"


class Direction(str, Enum):
    """予測の方向（Compass DNAの5段階シグナル＋レンジ予測に対応）。"""

    UP = "up"
    SLIGHTLY_UP = "slightly_up"
    FLAT = "flat"
    SLIGHTLY_DOWN = "slightly_down"
    DOWN = "down"
    RANGE = "range"  # 為替レンジ予測など（ForecastMetadata.target_low/highと併用）


# FORECASTの確信度は0〜5の整数（FACT_ANALYSIS_FORECAST_SPEC.md §3の語彙ラダー準拠。
# 5=投資妙味/押し目好機, 4=想定する, 3=期待, 2=注目, 1=可能性, 0=条件付き）。
# 将来のcalibration（Phase 5）はこの離散値と実績の対応表として実装できる。
CONFIDENCE_MIN = 0
CONFIDENCE_MAX = 5


def validate_confidence(value: int) -> int:
    if not (CONFIDENCE_MIN <= value <= CONFIDENCE_MAX):
        raise ValueError(
            f"confidence must be in [{CONFIDENCE_MIN}, {CONFIDENCE_MAX}], got {value}"
        )
    return value


@dataclass(frozen=True, kw_only=True)
class LLMResult:
    """LLM呼び出しの結果（provider中立）。

    provider/modelは実行metadataであり、core domainは特定ベンダーへ依存しない。
    """

    text: str
    provider: str  # 実装側が名乗る識別子（例: "anthropic", "openai", "local", "null"）
    model: str
    input_evidence_ids: Tuple[str, ...] = field(default=())
