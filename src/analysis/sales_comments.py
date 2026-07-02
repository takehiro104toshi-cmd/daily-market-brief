"""「営業向けコメント」(7オーディエンス別・各約30秒)と「想定質問と回答例」を生成する。

いずれも断定表現は使わず、「〜の可能性があります」「〜が注目されています」
「〜を確認したい局面です」等の言い回しに統一する。事実の紹介・情報整理に
とどめ、投資助言（売買の推奨・勧誘）は行わない。
"""
from __future__ import annotations

from typing import List, Optional

from ..collectors.market_data import Quote
from ..collectors.themes import SectorMatch, ThemeMatch
from ..report.format_utils import NOT_AVAILABLE, find_quote, fmt_change, fmt_price
from .models import QAItem, SalesComments, ScenarioForecast


def _top_sector(sector_matches: List[SectorMatch]) -> Optional[SectorMatch]:
    if not sector_matches:
        return None
    return sorted(sector_matches, key=lambda m: len(m.tailwind) - len(m.headwind), reverse=True)[0]


def build_sales_comments(
    market: dict,
    scenario: ScenarioForecast,
    theme_matches: List[ThemeMatch],
    sector_matches: List[SectorMatch],
    jp_quotes: List[Quote],
    us_quotes: List[Quote],
) -> SalesComments:
    usdjpy = find_quote(market["forex"], "米ドル/円")
    tnx = find_quote(market["rates"], "10年")
    n225 = find_quote(market["indices"], "日経")
    dji = find_quote(market["indices"], "ダウ")
    vix = find_quote(market["indices"], "VIX")
    top_theme = theme_matches[0].label if theme_matches else None
    top_sector = _top_sector(sector_matches)

    usdjpy_txt = f"{usdjpy.price:.2f}円" if usdjpy and usdjpy.price is not None else NOT_AVAILABLE
    tnx_txt = f"{tnx.price:.2f}%" if tnx and tnx.price is not None else NOT_AVAILABLE
    n225_txt = fmt_price(n225.price) if n225 else NOT_AVAILABLE
    dji_change_txt = fmt_change(dji.change, dji.change_pct) if dji else NOT_AVAILABLE

    corporate = (
        f"為替は米ドル/円{usdjpy_txt}、米金利は{tnx_txt}付近で推移しており、"
        "資金調達コストや輸出入採算への影響が注目されています。"
        f"{('『' + top_sector.label + '』関連の話題が業界動向として意識されています。') if top_sector else ''}"
        "経営判断の参考として、引き続き為替・金利の水準を確認したい局面です。"
    ).strip()

    wealthy = (
        f"為替（米ドル/円{usdjpy_txt}）と米金利（{tnx_txt}）の組み合わせは、"
        "資産全体の通貨・金利エクスポージャーを見直すきっかけになる可能性があります。"
        f"{('『' + top_theme + '』のような構造的テーマも話題になっています。') if top_theme else ''}"
        "短期の値動きよりも、資産配分・分散の観点から相場環境を確認したい局面です。"
    ).strip()

    retail = (
        f"日経平均は{n225_txt}付近、NYダウは前日比{dji_change_txt}で推移しています。"
        f"{('本日は' + top_theme + '関連のニュースが注目されています。') if top_theme else '本日は目立った個別材料は確認されていません。'}"
        "投資判断は最新の情報をご自身でご確認いただきたい局面です。"
    ).strip()

    nisa_beginner = (
        "NISA（少額投資非課税制度）は、一定額までの投資利益が非課税になる制度です。"
        f"本日の市場は日経平均{n225_txt}、為替は米ドル/円{usdjpy_txt}という状況で、"
        "短期の値動きに一喜一憂せず、長期・積立・分散という基本を確認したい局面と考えられます。"
        "個別商品の選定は、ご自身の目的やリスク許容度に応じてご検討いただく話題です。"
    ).strip()

    vix_level = "やや高め" if (vix and vix.price is not None and vix.price >= 20) else "落ち着いた"
    fx_interested = (
        f"米ドル/円は{usdjpy_txt}で推移しており、日米の金利差（米10年金利{tnx_txt}）が"
        "変動要因の一つとして注目されています。"
        f"市場のリスク許容度を示すVIX指数は{vix_level}水準との見方があり、"
        "為替の変動幅にも影響しうる局面として確認したい状況です。"
    ).strip()

    us_stock_interested = (
        f"NYダウは前日比{dji_change_txt}で推移しています。"
        f"{('『' + top_theme + '』関連のテーマが引き続き注目されています。') if top_theme else '目立ったテーマ材料は本日確認されていません。'}"
        "米金利・インフレ動向とあわせて、値動きの背景を確認したい局面です。"
    ).strip()

    jp_stock_interested = (
        f"日経平均は{n225_txt}付近で推移しており、為替（米ドル/円{usdjpy_txt}）の動向が"
        "輸出関連株を中心に意識されやすい状況です。"
        f"{('業種では『' + top_sector.label + '』が注目されています。') if top_sector else ''}"
        "業種ごとの追い風・逆風のバランスを確認したい局面と考えられます。"
    ).strip()

    return SalesComments(
        corporate=corporate,
        wealthy=wealthy,
        retail=retail,
        nisa_beginner=nisa_beginner,
        fx_interested=fx_interested,
        us_stock_interested=us_stock_interested,
        jp_stock_interested=jp_stock_interested,
    )


def build_expanded_qa(
    market: dict,
    scenario: ScenarioForecast,
    theme_matches: List[ThemeMatch],
    sector_matches: List[SectorMatch],
    us_quotes: List[Quote],
) -> List[QAItem]:
    top_sector = _top_sector(sector_matches)
    top_theme = theme_matches[0].label if theme_matches else None
    nvda = find_quote(us_quotes, "NVIDIA")

    qa: List[QAItem] = [
        QAItem(
            "日経平均はまだ上がりますか？",
            f"AIの機械的な見立てでは強気{scenario.bull_pct}%・中立{scenario.neutral_pct}%・弱気{scenario.bear_pct}%です。"
            "将来を断定するものではなく、あくまで情報整理としての参考値とお考えください。",
        ),
        QAItem(
            "円安は続きますか？",
            _fx_outlook_answer(market),
        ),
        QAItem(
            "NVIDIAはまだ強いですか？",
            (
                f"直近値は{fmt_price(nvda.price)}（前日比{fmt_change(nvda.change, nvda.change_pct)}）です。"
                if nvda is not None
                else f"NVIDIAの直近データは{NOT_AVAILABLE}でした。"
            )
            + f"{('半導体・AI関連の話題が注目されている局面です。') if top_theme else ''}"
            "個別銘柄の先行きを断定することはできず、業績や需給の動向を確認したい局面です。",
        ),
        QAItem(
            "日本株で今見るべき業種は？",
            (
                f"本日のニュースからは『{top_sector.label}』への追い風・逆風の材料が比較的多く確認されています。"
                if top_sector is not None
                else f"本日は業種別の明確な傾向を示すデータが{NOT_AVAILABLE}でした。"
            )
            + "特定の業種を推奨するものではなく、材料の多寡から確認したい業種として参考にしてください。",
        ),
        QAItem(
            "NISAで何を買えばいいですか？",
            "特定の商品名を挙げてお勧めすることはできません。"
            "一般的には、長期・積立・分散といった基本的な考え方が紹介されることが多く、"
            "ご自身の目的やリスク許容度に応じて金融機関・専門家にご相談いただくことをお勧めします。",
        ),
    ]
    return qa


def _fx_outlook_answer(market: dict) -> str:
    usdjpy = find_quote(market["forex"], "米ドル/円")
    tnx = find_quote(market["rates"], "10年")
    if usdjpy is None or usdjpy.price is None:
        return f"為替データを{NOT_AVAILABLE}のため、最新のレートを別途ご確認ください。"
    base = f"現在は米ドル/円{usdjpy.price:.2f}円付近です。"
    if tnx is not None and tnx.price is not None:
        base += f"米10年金利（{tnx.price:.2f}%）との金利差が引き続き注目材料とされています。"
    base += "為替の先行きを断定することはできず、金融政策や金利動向を確認したい局面です。"
    return base
