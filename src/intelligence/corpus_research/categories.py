"""Editorial selection の controlled vocabulary（Phase 3.8 §6）。

決定的 keyword rule。すべての文を無理に分類しない（OTHER / UNKNOWN を許す）。
"""
from __future__ import annotations

import re
from typing import List, Tuple

JAPAN_EQUITY = "JAPAN_EQUITY"
US_EQUITY = "US_EQUITY"
FX = "FX"
JAPAN_RATES = "JAPAN_RATES"
US_RATES = "US_RATES"
BREADTH = "BREADTH"
TURNOVER = "TURNOVER"
SECTOR = "SECTOR"
SIZE = "SIZE"
FLOW = "FLOW"
MACRO = "MACRO"
CENTRAL_BANK = "CENTRAL_BANK"
EARNINGS = "EARNINGS"
THEME = "THEME"
EVENT = "EVENT"
VALUATION = "VALUATION"
TECHNICAL = "TECHNICAL"
OTHER = "OTHER"
UNKNOWN = "UNKNOWN"

CATEGORIES: Tuple[str, ...] = (
    JAPAN_EQUITY, US_EQUITY, FX, JAPAN_RATES, US_RATES, BREADTH, TURNOVER, SECTOR, SIZE, FLOW,
    MACRO, CENTRAL_BANK, EARNINGS, THEME, EVENT, VALUATION, TECHNICAL, OTHER, UNKNOWN,
)

#: 優先順（先に一致したものが primary）。市場 entity より「何を見たか」を優先する順序。
CATEGORY_RULES: Tuple[Tuple[str, re.Pattern], ...] = (
    (CENTRAL_BANK, re.compile(r"FOMC|日銀|FRB|ECB|金融政策|利上げ|利下げ|中央銀行|総裁|議長|金融政策決定会合")),
    (EARNINGS, re.compile(r"決算|業績|増益|減益|ガイダンス|EPS|売上高|受注")),
    (BREADTH, re.compile(r"占有率|裾野|物色の広がり|寄与度|騰落|値上がり|値下がり|上位\d+位|主役交代|顔ぶれ|新高値|広がり")),
    (TURNOVER, re.compile(r"売買代金|商い|出来高")),
    (FLOW, re.compile(r"買い越し|売り越し|海外投資家|個人投資家|投資部門|需給|買付|資金流入|配当再投資")),
    (US_RATES, re.compile(r"米.{0,4}(金利|国債|利回り)|米10年|米長期金利|米国債")),
    (JAPAN_RATES, re.compile(r"日10年|国内金利|日本.{0,4}(金利|国債)|長期金利|国債利回り|JGB")),
    (FX, re.compile(r"ドル円|円高|円安|為替|ドル高|ドル安|ユーロ|介入")),
    (VALUATION, re.compile(r"PER|PBR|バリュエーション|割安|割高|益回り|配当利回り|σ")),
    (TECHNICAL, re.compile(r"25日|200日|移動平均|MA|乖離|節目|サポート|レジスタンス|チャート|テクニカル|押し目")),
    (SIZE, re.compile(r"大型株|小型株|中小型|時価総額|ラッセル")),
    (SECTOR, re.compile(r"銀行|半導体|電力|商社|自動車|不動産|証券|保険|建設|機械|素材|エネルギー|小売|通信|医薬|海運|鉄鋼|化学|金融株|ディフェンシブ|セクター|業種|バリュー|グロース")),
    (US_EQUITY, re.compile(r"米国株|NYダウ|S&P500|ナスダック|SOX|ハイテク株|米株|エヌビディア|マイクロン|フィラデルフィア")),
    (JAPAN_EQUITY, re.compile(r"日経平均|TOPIX|日本株|東証|プライム|先物|日経")),
    (MACRO, re.compile(r"CPI|雇用統計|GDP|PMI|物価|景気|インフレ|消費者|統計|経済指標|小売売上")),
    (THEME, re.compile(r"テーマ|AI|データセンター|光関連|光通信|関連銘柄|国策|防衛|フィジカル|電源|メモリ")),
    (EVENT, re.compile(r"イベント|会合|選挙|発表|協議|会談|関税|地政学|中東|停戦|通過")),
)


def categorize(text: str) -> Tuple[str, ...]:
    """一致した category を優先順で返す（空 = 該当なし）。"""
    text = text or ""
    return tuple(cat for cat, pattern in CATEGORY_RULES if pattern.search(text))


def primary_category(text: str) -> str:
    if not (text or "").strip():
        return UNKNOWN
    found = categorize(text)
    return found[0] if found else OTHER
