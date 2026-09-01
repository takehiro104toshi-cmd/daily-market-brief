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
}

#: 主語キー → market state dimension（missingness validatorが参照）
KEY_DIMENSION: Dict[str, str] = {
    TOPIX_KEY: "japan_equities", NIKKEI_KEY: "japan_equities", NT_KEY: "nt_ratio",
    CURVE_KEY: "us_curve", JGB10Y_KEY: "japan_rates", UST10Y_KEY: "us_rates_10y",
    UST2Y_KEY: "us_rates_2y", FX_KEY: "usd_jpy",
}

#: 文中の主語を拾う（**順序が優先度**。長い・特異なものを先に置く）
SUBJECT_PATTERN = re.compile(
    r"(?P<nt>NT倍率)"
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
    r"(?P<weaker>円安)|(?P<stronger>円高)"
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
