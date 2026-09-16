"""Market Internals の統制語彙・定数（Phase 3.5）。

他モジュール（context.salience / compass.lexicon / compass.evidence_package）から
参照される**依存の無い**定数だけを置く（循環importを作らない）。
"""
from __future__ import annotations

from typing import Mapping, Tuple

# ---- context types（Phase 3-B Context Engineの型として追加する）
BREADTH_STATE = "breadth_state"                 # 値上がり vs 値下がり銘柄数
BREADTH_TREND = "breadth_trend"                 # 5 vs 20セッションの騰落比率トレンド
TURNOVER_STATE = "turnover_state"               # 売買代金 vs 20セッション平均
SECTOR_LEADERSHIP = "sector_leadership"         # 業種の相対パフォーマンス
SIZE_LEADERSHIP = "size_leadership"             # 規模区分の相対パフォーマンス
INVESTOR_FLOW_STATE = "investor_flow_state"     # 投資部門別売買（**週次**）
INDEX_LEADERSHIP = "index_leadership"           # 日経/TOPIX主導 × breadth確認

INTERNALS_CONTEXT_TYPES: Tuple[str, ...] = (
    BREADTH_STATE, BREADTH_TREND, TURNOVER_STATE, SECTOR_LEADERSHIP,
    SIZE_LEADERSHIP, INVESTOR_FLOW_STATE, INDEX_LEADERSHIP,
)

# ---- market_internals 次元（Morning Snapshotの充足状況として報告する）
DIM_BREADTH = "breadth"
DIM_TURNOVER = "turnover"
DIM_SECTOR = "sector_leadership"
DIM_SIZE = "size_leadership"
DIM_FLOW = "investor_flow"
INTERNALS_DIMENSIONS: Tuple[str, ...] = (DIM_BREADTH, DIM_TURNOVER, DIM_SECTOR,
                                         DIM_SIZE, DIM_FLOW)

# ---- subject ids
MARKET_SUBJECT = "market:tse_prime"                  # universe（東証プライム普通株）
SECTOR_SUMMARY_SUBJECT = "sector:s17:leadership"     # 業種leaders/laggardsの要約
SIZE_SUMMARY_SUBJECT = "size:leadership"             # 大型 vs 小型の要約
INDEX_LEADERSHIP_SUBJECT = "index:leadership"
FLOW_SUBJECT_PREFIX = "flow"                         # flow:<section>:<investor_type>
SECTOR_SUBJECT_PREFIX = "sector:s17"                 # sector:s17:<code>
SIZE_SUBJECT_PREFIX = "size"                         # size:<category>
FOREIGN_INVESTORS = "foreign_investors"


def flow_subject(section: str, investor_type: str) -> str:
    return f"{FLOW_SUBJECT_PREFIX}:{section}:{investor_type}"


def sector_subject(code: str) -> str:
    return f"{SECTOR_SUBJECT_PREFIX}:{code}"


def size_subject(category: str) -> str:
    return f"{SIZE_SUBJECT_PREFIX}:{category}"


def internals_dimension_sources(section: str) -> Mapping[str, Tuple[str, str]]:
    """次元 → 代表Contextの (context_type, subject_id)。flowはsectionに依存する。"""
    return {
        DIM_BREADTH: (BREADTH_STATE, MARKET_SUBJECT),
        DIM_TURNOVER: (TURNOVER_STATE, MARKET_SUBJECT),
        DIM_SECTOR: (SECTOR_LEADERSHIP, SECTOR_SUMMARY_SUBJECT),
        DIM_SIZE: (SIZE_LEADERSHIP, SIZE_SUMMARY_SUBJECT),
        DIM_FLOW: (INVESTOR_FLOW_STATE, flow_subject(section, FOREIGN_INVESTORS)),
    }


#: 既定section（J-Quants investor-types の実測Section値。pilotが観測値を報告する）
DEFAULT_FLOW_SECTION = "TSEPrime"
INTERNALS_DIMENSION_SOURCES: Mapping[str, Tuple[str, str]] = internals_dimension_sources(
    DEFAULT_FLOW_SECTION)

# ---- index leadership の状態語彙（Contextのnoteに `state=` として残す）
NIKKEI_LED = "NIKKEI_LED"
TOPIX_LED = "TOPIX_LED"
BROAD_CONFIRMATION = "BROAD_CONFIRMATION"
NARROW_LEADERSHIP = "NARROW_LEADERSHIP"
MIXED_LEADERSHIP = "MIXED"
UNKNOWN_LEADERSHIP = "UNKNOWN"

# ---- 週次フローの状態語彙
NET_BUY = "NET_BUY"
NET_SELL = "NET_SELL"
FLOW_FLAT = "FLAT"

# ---- 規模区分（**sourceのScaleCat定義に従う**。市場規模の閾値を独自に発明しない）
#: TOPIX size分類（JPX定義）: TOPIX 100 = Core30 + Large70 / Mid400 / Small = Small 1 + Small 2
SCALE_LARGE = ("TOPIX Core30", "TOPIX Large70")
SCALE_MID = ("TOPIX Mid400",)
SCALE_SMALL = ("TOPIX Small 1", "TOPIX Small 2")
SIZE_GROUPS: Mapping[str, Tuple[str, ...]] = {
    "topix100": SCALE_LARGE, "mid400": SCALE_MID, "small": SCALE_SMALL,
}
SIZE_LABELS: Mapping[str, str] = {"topix100": "大型株", "mid400": "中型株", "small": "小型株"}
