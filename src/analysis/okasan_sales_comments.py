"""「岡三証券営業向けコメント」(富裕層・法人・NISA・退職金・相続の5顧客タイプ・各約30秒)を生成する。

断定表現は使わず、「〜の可能性があります」「〜が注目されています」
「〜を確認したい局面です」等の言い回しに統一する。事実の紹介・情報整理に
とどめ、投資助言（売買の推奨・勧誘）は行わない。特定の金融商品名は挙げない。
"""
from __future__ import annotations

from typing import List, Optional

from ..collectors.market_data import Quote
from ..collectors.themes import SectorMatch, ThemeMatch
from ..report.format_utils import NOT_AVAILABLE, find_quote
from .models import OkasanSalesComments, ScenarioForecast


def _top_sector(sector_matches: List[SectorMatch]) -> Optional[SectorMatch]:
    if not sector_matches:
        return None
    return sorted(sector_matches, key=lambda m: len(m.tailwind) - len(m.headwind), reverse=True)[0]


def build_okasan_sales_comments(
    market: dict,
    scenario: ScenarioForecast,
    theme_matches: List[ThemeMatch],
    sector_matches: List[SectorMatch],
    jp_quotes: List[Quote],
) -> OkasanSalesComments:
    usdjpy = find_quote(market["forex"], "米ドル/円")
    tnx = find_quote(market["rates"], "10年")
    n225 = find_quote(market["indices"], "日経")
    top_theme = theme_matches[0].label if theme_matches else None
    top_sector = _top_sector(sector_matches)

    usdjpy_txt = f"{usdjpy.price:.2f}円" if usdjpy and usdjpy.price is not None else NOT_AVAILABLE
    tnx_txt = f"{tnx.price:.2f}%" if tnx and tnx.price is not None else NOT_AVAILABLE
    n225_txt = f"{n225.price:,.0f}円" if n225 and n225.price is not None else NOT_AVAILABLE

    wealthy = (
        f"為替（米ドル/円{usdjpy_txt}）と米金利（{tnx_txt}）の水準は、"
        "外貨建て資産や資産全体の通貨・金利エクスポージャーを見直す話題につながる可能性があります。"
        f"{('『' + top_theme + '』のような構造的テーマも話題になっています。') if top_theme else ''}"
        "短期の値動きよりも、資産配分・分散の観点から相場環境を確認したい局面です。"
    ).strip()

    corporate = (
        f"為替は米ドル/円{usdjpy_txt}、米金利は{tnx_txt}付近で推移しており、"
        "輸出入採算や資金調達コストへの影響が注目されています。"
        f"{('業界動向として『' + top_sector.label + '』が話題になっています。') if top_sector else ''}"
        "法人のお客様には、為替・金利のヘッジや資金計画を確認したい局面としてお伝えできます。"
    ).strip()

    nisa = (
        f"本日の日経平均は{n225_txt}付近、為替は米ドル/円{usdjpy_txt}という状況です。"
        "NISA（少額投資非課税制度）をご活用中のお客様には、短期の値動きに一喜一憂せず、"
        "長期・積立・分散という基本方針を確認いただきたい局面とお伝えできます。"
        "個別商品のご提案ではなく、制度活用状況の確認としてご案内ください。"
    ).strip()

    retirement = (
        "退職金のご相談では、まとまった資金を一度に投じるのではなく、"
        "時間分散や生活資金とのバランスを確認したい局面である旨をご案内できます。"
        f"{('市場では『' + top_theme + '』が話題になっていますが、') if top_theme else ''}"
        "退職後の資金計画は市場動向以上にお客様ご自身のライフプランに即して"
        "ご確認いただくことが重要です。"
    ).strip()

    inheritance = (
        "相続・資産承継のご相談では、市場動向にかかわらず、資産全体の棚卸しや"
        "承継方法の整理をするきっかけとしてお声がけできる局面です。"
        f"為替（米ドル/円{usdjpy_txt}）や金利（{tnx_txt}）の動きは、"
        "承継時の評価額に影響しうる要素として参考情報にとどめてお伝えください。"
    ).strip()

    return OkasanSalesComments(
        wealthy=wealthy,
        corporate=corporate,
        nisa=nisa,
        retirement=retirement,
        inheritance=inheritance,
    )
