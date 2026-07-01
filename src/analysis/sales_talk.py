"""営業トークを4種類（法人社長向け・個人投資家向け・初心者向け・富裕層向け）生成する。

いずれも事実の紹介にとどめ、売買の推奨・勧誘は行わない。
まず構造化データ（SalesTalkBullets）としてトーク文を組み立て、
それをMarkdownに整形する。構造化データのまま渡すことで、
モバイル版レポート（各1件のみ抜粋）でも同じロジックを再利用できる。
"""
from __future__ import annotations

from typing import List

from ..collectors.market_data import Quote
from ..collectors.themes import SectorMatch, ThemeMatch
from ..report.format_utils import NOT_AVAILABLE, find_quote, fmt_price
from .models import SalesTalkBullets


def build_sales_talk_bullets(
    market: dict,
    theme_matches: List[ThemeMatch],
    sector_matches: List[SectorMatch],
    jp_quotes: List[Quote],
) -> SalesTalkBullets:
    dji = find_quote(market["indices"], "ダウ")
    vix = find_quote(market["indices"], "VIX")
    usdjpy = find_quote(market["forex"], "米ドル/円")
    tnx = find_quote(market["rates"], "10年")
    top_theme = theme_matches[0].label if theme_matches else None
    top_sector = sector_matches[0].label if sector_matches else None

    corporate = []
    if usdjpy and usdjpy.price is not None:
        corporate.append(f"「為替は米ドル/円{usdjpy.price:.2f}円付近です。輸出入コストへの影響をご確認ください」")
    else:
        corporate.append(f"「本日の為替データは{NOT_AVAILABLE}のため、別途ご確認ください」")
    if tnx and tnx.price is not None:
        corporate.append(f"「米10年金利は{tnx.price:.2f}%です。資金調達コストの動向としてご留意ください」")
    else:
        corporate.append(f"「米金利データは{NOT_AVAILABLE}のため、別途ご確認ください」")
    if top_sector:
        corporate.append(f"「業界動向として{top_sector}が話題になっています」")

    retail = []
    if dji and dji.change_pct is not None:
        retail.append(f"「昨晩のNYダウは前日比{dji.change_pct:+.2f}%でした」")
    else:
        retail.append(f"「米国株の動きは{NOT_AVAILABLE}のため、別途ご確認ください」")
    if jp_quotes and jp_quotes[0].price is not None:
        top = jp_quotes[0]
        retail.append(f"「{top.name}の直近値は{fmt_price(top.price)}円です」")
    if top_theme:
        retail.append(f"「本日は{top_theme}関連のニュースが話題です」")
    if not retail:
        retail.append(f"本日は自動生成できる話題が見つかりませんでした（{NOT_AVAILABLE}）。")

    beginner = []
    if vix and vix.price is not None:
        level = "高め" if vix.price >= 20 else "落ち着いた"
        beginner.append(f"「VIX指数（別名：恐怖指数）は市場の不安の大きさを表す指標で、現在は{vix.price:.2f}と{level}水準です」")
    else:
        beginner.append(f"「VIX指数のデータは{NOT_AVAILABLE}でした」")
    if usdjpy and usdjpy.price is not None:
        beginner.append(f"「為替（米ドル/円）は今どれくらいの円安・円高かを示す指標で、現在は{usdjpy.price:.2f}円です」")
    else:
        beginner.append(f"「為替データは{NOT_AVAILABLE}でした」")
    beginner.append("「これらは市場の状況を知るための参考情報であり、そのまま売買の判断材料とするものではありません」")

    wealthy = []
    if usdjpy and usdjpy.price is not None and tnx and tnx.price is not None:
        wealthy.append(
            f"「為替（米ドル/円{usdjpy.price:.2f}円）と米金利（{tnx.price:.2f}%）の組み合わせは、"
            "資産全体の通貨・金利エクスポージャーを見直す材料になります」"
        )
    else:
        wealthy.append(f"「為替・金利データが{NOT_AVAILABLE}のため、資産配分への影響は別途ご確認ください」")
    if top_theme:
        wealthy.append(f"「『{top_theme}』のような構造的テーマは、コア・サテライト戦略のサテライト部分として話題にできます」")
    wealthy.append("「短期の値動きよりも、資産配分・分散の観点から市場環境を俯瞰する材料としてご活用ください」")

    return SalesTalkBullets(corporate=corporate, retail=retail, beginner=beginner, wealthy=wealthy)


def render_sales_talk_markdown(bullets: SalesTalkBullets) -> str:
    lines = ["### 法人社長向け"]
    lines.extend(f"- {b}" for b in bullets.corporate)
    lines.append("")
    lines.append("### 個人投資家向け")
    lines.extend(f"- {b}" for b in bullets.retail)
    lines.append("")
    lines.append("### 初心者向け")
    lines.extend(f"- {b}" for b in bullets.beginner)
    lines.append("")
    lines.append("### 富裕層向け")
    lines.extend(f"- {b}" for b in bullets.wealthy)
    lines.append("")
    lines.append("（いずれも事実の紹介にとどめ、売買の推奨・勧誘は行わないでください。）")
    return "\n".join(lines)
