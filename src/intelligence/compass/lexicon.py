"""Compass Generatorの統制語彙（Phase 3-C）。

生成側（deterministic renderer）と検証側（direction / missingness validator）が
**同じ表**を参照する。ここに無い言い回しは「検証できない」＝根拠なしとして
扱われる（validatorが落とす）。自由な語彙の追加は設計変更（監督者事項）。
"""
from __future__ import annotations

import re
from decimal import Decimal, ROUND_HALF_UP
from typing import Dict, FrozenSet, Optional, Sequence, Tuple

from ..context.builders import (
    CURVE_SUBJECT,
    JGB10Y,
    NIKKEI,
    NT_SUBJECT,
    TOPIX,
    USDJPY,
    UST2Y,
    UST10Y,
)
from ..context.model import Direction
from ..internals.types import (
    BREADTH_STATE,
    DEFAULT_FLOW_SECTION,
    DIM_BREADTH,
    DIM_FLOW,
    DIM_SECTOR,
    DIM_SIZE,
    DIM_TURNOVER,
    FOREIGN_INVESTORS,
    INVESTOR_FLOW_STATE,
    MARKET_SUBJECT,
    SECTOR_LEADERSHIP,
    SECTOR_SUMMARY_SUBJECT,
    SIZE_LEADERSHIP,
    SIZE_SUMMARY_SUBJECT,
    TURNOVER_STATE,
    flow_subject,
)
from .model import Confidence, OutlookDirection

#: 主語キー（validator内部の識別子）
TOPIX_KEY = "topix"
NIKKEI_KEY = "nikkei"
NT_KEY = "nt"
MA_KEY = "ma"
CURVE_KEY = "curve"
JGB10Y_KEY = "jgb10y"
UST10Y_KEY = "ust10y"
UST2Y_KEY = "ust2y"
FX_KEY = "fx"
#: Phase 3.5 market internals の主語キー
BREADTH_KEY = "breadth"
TURNOVER_KEY = "turnover"
SECTOR_KEY = "sector"
SIZE_KEY = "size"
FLOW_KEY = "flow"
INTERNALS_KEYS = (BREADTH_KEY, TURNOVER_KEY, SECTOR_KEY, SIZE_KEY, FLOW_KEY)
#: internals主語キー → context_type（direction validatorが参照）
INTERNALS_KEY_CONTEXT_TYPE: Dict[str, str] = {
    BREADTH_KEY: BREADTH_STATE, TURNOVER_KEY: TURNOVER_STATE,
    SECTOR_KEY: SECTOR_LEADERSHIP, SIZE_KEY: SIZE_LEADERSHIP,
    FLOW_KEY: INVESTOR_FLOW_STATE,
}

#: 生成側が使う表示ラベル（subject_id → ラベル）。validatorが認識できる語だけ。
SUBJECT_LABELS: Dict[str, str] = {
    TOPIX: "TOPIX",
    NIKKEI: "日経平均",
    JGB10Y: "日本10年国債利回り",
    UST2Y: "米2年国債利回り",
    UST10Y: "米10年国債利回り",
    USDJPY: "ドル円",
    CURVE_SUBJECT: "米10年-2年スプレッド",
    NT_SUBJECT: "NT倍率",
}

#: 主語キー → subject_id（相対比較・MA乖離は別扱い）
KEY_SUBJECT: Dict[str, str] = {
    TOPIX_KEY: TOPIX, NIKKEI_KEY: NIKKEI, NT_KEY: NT_SUBJECT, CURVE_KEY: CURVE_SUBJECT,
    JGB10Y_KEY: JGB10Y, UST10Y_KEY: UST10Y, UST2Y_KEY: UST2Y, FX_KEY: USDJPY,
    BREADTH_KEY: MARKET_SUBJECT, TURNOVER_KEY: MARKET_SUBJECT,
    SECTOR_KEY: SECTOR_SUMMARY_SUBJECT, SIZE_KEY: SIZE_SUMMARY_SUBJECT,
    FLOW_KEY: flow_subject(DEFAULT_FLOW_SECTION, FOREIGN_INVESTORS),
}

#: 主語キー → market state dimension（missingness validatorが参照）
KEY_DIMENSION: Dict[str, str] = {
    TOPIX_KEY: "japan_equities", NIKKEI_KEY: "japan_equities", NT_KEY: "nt_ratio",
    CURVE_KEY: "us_curve", JGB10Y_KEY: "japan_rates", UST10Y_KEY: "us_rates_10y",
    UST2Y_KEY: "us_rates_2y", FX_KEY: "usd_jpy",
    BREADTH_KEY: DIM_BREADTH, TURNOVER_KEY: DIM_TURNOVER, SECTOR_KEY: DIM_SECTOR,
    SIZE_KEY: DIM_SIZE, FLOW_KEY: DIM_FLOW,
}

#: 文中の主語を拾う（**順序が優先度**。長い・特異なものを先に置く）
SUBJECT_PATTERN = re.compile(
    r"(?P<breadth>値上がり[\d,]*銘柄|値下がり[\d,]*銘柄|騰落レシオ|騰落銘柄|騰落)"
    r"|(?P<turnover>売買代金)"
    r"|(?P<sector>業種別|業種|セクター)"
    r"|(?P<size>大型株|中型株|小型株|規模別)"
    r"|(?P<flow>海外投資家|外国人投資家|個人投資家|信託銀行|事業法人|投資部門別|投資家)"
    r"|(?P<nt>NT倍率)"
    r"|(?P<ma>25日(?:移動)?平均(?:線)?)"
    r"|(?P<curve>米?10年[-−–]2年(?:スプレッド|金利差)?|イールドカーブ|長短金利差|"
    r"米国?債?(?:の)?スプレッド)"
    r"|(?P<jgb10y>日本(?:の)?10年(?:国債)?(?:利回り|金利)?|国内長期金利|JGB10Y|新発10年債)"
    r"|(?P<ust10y>米(?:国)?10年(?:国債)?(?:利回り|金利)?(?:\(par\))?|米長期金利|UST10Y)"
    r"|(?P<ust2y>米(?:国)?2年(?:国債)?(?:利回り|金利)?(?:\(par\))?|UST2Y)"
    r"|(?P<fx>ドル円|円相場|為替|USDJPY|USD/JPY)"
    r"|(?P<nikkei>日経平均(?:株価)?|日経225|Nikkei)"
    r"|(?P<topix>TOPIX|東証株価指数)"
)

#: 方向語 → 種別。kind: "level"（UP/DOWN/FLAT）, "fx", "curve", "relative"
_UP = frozenset({Direction.UP})
_DOWN = frozenset({Direction.DOWN})
_FLAT = frozenset({Direction.FLAT})
DIRECTION_PATTERN = re.compile(
    r"(?P<netbuy>買い越し)|(?P<netsell>売り越し)"
    r"|(?P<weaker>円安)|(?P<stronger>円高)"
    r"|(?P<steep>スティープ(?:化)?|拡大)|(?P<flatten>フラット化|フラットニング|縮小)"
    r"|(?P<above>上回|アウトパフォーム)|(?P<below>下回|アンダーパフォーム)"
    r"|(?P<up>上昇|上げ|続伸|反発|プラス|強含|高い水準へ|切り上げ)"
    r"|(?P<down>下落|下げ|続落|反落|マイナス|弱含|低下|軟調|切り下げ)"
    r"|(?P<flat>横ばい|変わらず|小動き|ほぼ同水準)"
)

DIRECTION_GROUPS: Dict[str, Tuple[str, FrozenSet[Direction]]] = {
    "weaker": ("fx", frozenset({Direction.WEAKER})),
    "stronger": ("fx", frozenset({Direction.STRONGER})),
    "steep": ("curve", frozenset({Direction.STEEPENING})),
    "flatten": ("curve", frozenset({Direction.FLATTENING})),
    "above": ("relative", frozenset({Direction.ABOVE, Direction.OUTPERFORM})),
    "below": ("relative", frozenset({Direction.BELOW, Direction.UNDERPERFORM})),
    "up": ("level", _UP), "down": ("level", _DOWN), "flat": ("level", _FLAT),
    "netbuy": ("level", _UP), "netsell": ("level", _DOWN),    # 週次flow: 買い越し=UP
}

#: internals主語ごとの「level語（上昇/下落/横ばい・買い越し/売り越し）」の写像
INTERNALS_FROM_LEVEL: Dict[str, Dict[Direction, Direction]] = {
    BREADTH_KEY: {Direction.UP: Direction.UP, Direction.DOWN: Direction.DOWN,
                  Direction.FLAT: Direction.FLAT},
    FLOW_KEY: {Direction.UP: Direction.UP, Direction.DOWN: Direction.DOWN,
               Direction.FLAT: Direction.FLAT},
    TURNOVER_KEY: {Direction.UP: Direction.ABOVE, Direction.DOWN: Direction.BELOW,
                   Direction.FLAT: Direction.FLAT},
    SECTOR_KEY: {Direction.UP: Direction.OUTPERFORM, Direction.DOWN: Direction.UNDERPERFORM,
                 Direction.FLAT: Direction.FLAT},
    SIZE_KEY: {Direction.UP: Direction.OUTPERFORM, Direction.DOWN: Direction.UNDERPERFORM,
               Direction.FLAT: Direction.FLAT},
}
#: internals主語ごとの「相対語（上回る/下回る）」の写像
INTERNALS_FROM_RELATIVE: Dict[str, Dict[Direction, Direction]] = {
    BREADTH_KEY: {Direction.ABOVE: Direction.UP, Direction.OUTPERFORM: Direction.UP,
                  Direction.BELOW: Direction.DOWN, Direction.UNDERPERFORM: Direction.DOWN},
    TURNOVER_KEY: {Direction.ABOVE: Direction.ABOVE, Direction.OUTPERFORM: Direction.ABOVE,
                   Direction.BELOW: Direction.BELOW, Direction.UNDERPERFORM: Direction.BELOW},
    SECTOR_KEY: {Direction.ABOVE: Direction.OUTPERFORM, Direction.OUTPERFORM: Direction.OUTPERFORM,
                 Direction.BELOW: Direction.UNDERPERFORM,
                 Direction.UNDERPERFORM: Direction.UNDERPERFORM},
    SIZE_KEY: {Direction.ABOVE: Direction.OUTPERFORM, Direction.OUTPERFORM: Direction.OUTPERFORM,
               Direction.BELOW: Direction.UNDERPERFORM,
               Direction.UNDERPERFORM: Direction.UNDERPERFORM},
    FLOW_KEY: {Direction.ABOVE: Direction.UP, Direction.OUTPERFORM: Direction.UP,
               Direction.BELOW: Direction.DOWN, Direction.UNDERPERFORM: Direction.DOWN},
}

#: level系の語を fx / curve へ写像する（USDJPY UP = 円安、スプレッド UP = スティープ化）
FX_FROM_LEVEL = {Direction.UP: Direction.WEAKER, Direction.DOWN: Direction.STRONGER,
                 Direction.FLAT: Direction.FLAT}
CURVE_FROM_LEVEL = {Direction.UP: Direction.STEEPENING, Direction.DOWN: Direction.FLATTENING,
                    Direction.FLAT: Direction.FLAT}

#: 文の区切り（direction validatorの検査単位）
SEGMENT_SPLIT = re.compile(r"[。、,;/\n]|（|）|\(|\)")


def segments(text: str) -> Sequence[str]:
    return [s for s in SEGMENT_SPLIT.split(text) if s.strip()]


# ------------------------------------------------------------------ 見通しの強度（Phase 3.5 pre-flight B）

#: (direction, confidence) → 「次の東京セッションは」に続く見通し句。
#: **confidence → 言語強度** を機械的に固定する（HIGH=見込まれる / MEDIUM=可能性がある /
#: LOW=余地がある）。方向語は BIAS_LEXICON（outlook.py）が認識する語だけを使う。
OUTLOOK_PHRASES: Dict[Tuple[OutlookDirection, Confidence], str] = {
    (OutlookDirection.UPWARD_BIAS, Confidence.HIGH): "堅調な展開が見込まれる",
    (OutlookDirection.UPWARD_BIAS, Confidence.MEDIUM): "堅調に推移する可能性がある",
    (OutlookDirection.UPWARD_BIAS, Confidence.LOW): "方向感が限定的ながら上値を試す余地がある",
    (OutlookDirection.DOWNWARD_BIAS, Confidence.HIGH): "軟調な展開が見込まれる",
    (OutlookDirection.DOWNWARD_BIAS, Confidence.MEDIUM): "軟調に推移する可能性がある",
    (OutlookDirection.DOWNWARD_BIAS, Confidence.LOW): "方向感が限定的ながら下値を試す余地がある",
    (OutlookDirection.RANGE_BOUND, Confidence.HIGH): "方向感に乏しい展開が見込まれる",
    (OutlookDirection.RANGE_BOUND, Confidence.MEDIUM): "方向感に乏しい展開となる可能性がある",
    (OutlookDirection.RANGE_BOUND, Confidence.LOW): "方向感に乏しい展開となる余地がある",
    (OutlookDirection.MIXED, Confidence.HIGH): "強弱材料が交錯する展開が見込まれる",
    (OutlookDirection.MIXED, Confidence.MEDIUM): "強弱材料が交錯する展開となる可能性がある",
    (OutlookDirection.MIXED, Confidence.LOW): "強弱材料が交錯し方向感が限定的にとどまる余地がある",
    (OutlookDirection.UNCERTAIN, Confidence.HIGH): "見通しの確度が低い展開が見込まれる",
    (OutlookDirection.UNCERTAIN, Confidence.MEDIUM): "見通しの確度が低い展開となる可能性がある",
    (OutlookDirection.UNCERTAIN, Confidence.LOW): "見通しは不透明で方向感が限定的にとどまる余地がある",
}

#: 強度マーカー → confidence（文末の述語で判定する）。「となろう」は強い表現として扱う
STRENGTH_LEXICON: Tuple[Tuple[str, Confidence], ...] = (
    ("見込まれる", Confidence.HIGH), ("となろう", Confidence.HIGH),
    ("可能性がある", Confidence.MEDIUM),
    ("余地がある", Confidence.LOW),
)


def outlook_phrase(direction: OutlookDirection, confidence: Confidence) -> str:
    return OUTLOOK_PHRASES[(direction, confidence)]


def asserted_strength(text: str) -> Optional[Confidence]:
    """文中の強度マーカー（最後に現れる述語）から言語強度を読む。無ければNone。"""
    hits = [(text.rfind(word), confidence) for word, confidence in STRENGTH_LEXICON
            if word in text]
    if not hits:
        return None
    return max(hits, key=lambda h: h[0])[1]


# ------------------------------------------------------------------ 生成側の語彙

def direction_word(direction: Direction, *, unit_kind: str = "level") -> str:
    """統制語彙の**代表語**（validatorが必ず認識する語）。"""
    table = {
        Direction.UP: "上昇", Direction.DOWN: "下落", Direction.FLAT: "横ばい",
        Direction.WEAKER: "円安", Direction.STRONGER: "円高",
        Direction.STEEPENING: "スティープ化", Direction.FLATTENING: "フラット化",
        Direction.OUTPERFORM: "上回った", Direction.UNDERPERFORM: "下回った",
        Direction.ABOVE: "上回って", Direction.BELOW: "下回って",
    }
    return table.get(direction, "")


def fmt_signed(value: Optional[Decimal], places: int) -> str:
    """ROUND_HALF_UPで丸め、符号付きで返す（validatorと同じ丸め）。"""
    if value is None:
        return ""
    q = Decimal(1).scaleb(-places)
    rounded = value.quantize(q, rounding=ROUND_HALF_UP)
    sign = "+" if rounded > 0 else ("-" if rounded < 0 else "")
    return f"{sign}{abs(rounded):f}"


def fmt_level(value: Optional[Decimal], places: int = 2) -> str:
    if value is None:
        return ""
    q = Decimal(1).scaleb(-places)
    rounded = value.quantize(q, rounding=ROUND_HALF_UP)
    return f"{rounded:,.{places}f}"


def fmt_magnitude(value: Optional[Decimal], unit: str) -> str:
    """magnitude_unitごとの表記（pct→2桁%, pct_point→3桁pt, x→2桁倍, days→整数日）。"""
    if value is None:
        return ""
    if unit == "pct":
        return f"{fmt_signed(value, 2)}%"
    if unit == "pct_point":
        return f"{fmt_signed(value, 3)}pt"
    if unit == "x":
        return f"{fmt_signed(value, 2)}倍"
    if unit == "days":
        return f"{int(value)}日"
    return fmt_signed(value, 2)
