"""「営業準備」セクション: 社長向け一言・富裕層向け話題・初心者向け用語解説・
今日の雑談・想定質問（Q&A）をまとめて生成する。

いずれも事実の紹介・一般的な説明にとどめ、断定的な投資助言は行わない。
"""
from __future__ import annotations

from typing import Dict, List

from ..collectors.market_data import Quote
from ..collectors.news import Headline
from ..collectors.themes import SectorMatch, ThemeMatch
from ..report.format_utils import NOT_AVAILABLE, find_quote, fmt_change, fmt_price
from .models import GlossaryItem, QAItem, ScenarioForecast, SalesPrep, StockRankingEntry

# 相場に近い話題を「今日の雑談」から除外するためのキーワード
_MARKET_RELATED_KEYWORDS = ["株", "円安", "円高", "日経", "経済", "相場", "金利", "決算", "為替", "ドル"]

BEGINNER_GLOSSARY = [
    GlossaryItem("NISA", "少額投資非課税制度の愛称。一定額までの投資利益が非課税になる制度です。"),
    GlossaryItem("積立", "毎月など一定額を継続して購入する投資方法。時間分散でリスクを抑えやすいとされます。"),
    GlossaryItem("インフレ", "物価が継続的に上昇すること。同じ金額で買えるものが少なくなっていく状態です。"),
    GlossaryItem("円安", "円の価値が他通貨に対して下がること。輸出企業には追い風、輸入コストには逆風になりやすいとされます。"),
]


def _ceo_lines(market: dict, sector_matches: List[SectorMatch]) -> List[str]:
    lines = []
    if sector_matches:
        top_sector = sorted(sector_matches, key=lambda m: len(m.tailwind) - len(m.headwind), reverse=True)[0]
        lines.append(f"{top_sector.label}関連が注目されています")
    usdjpy = find_quote(market["forex"], "米ドル/円")
    if usdjpy and usdjpy.price is not None:
        lines.append(f"ドル円（{usdjpy.price:.2f}円）の変動が企業業績へ影響します")
    tnx = find_quote(market["rates"], "10年")
    if tnx and tnx.price is not None:
        lines.append("金利動向が設備投資判断へ影響する可能性があります")
    if not lines:
        lines.append(f"本日は主要データが取得できず、一言コメントを生成できませんでした（{NOT_AVAILABLE}）。")
    return lines[:3]


def _wealthy_topics(market: dict, sector_matches: List[SectorMatch]) -> List[str]:
    topics = []
    usdjpy = find_quote(market["forex"], "米ドル/円")
    if usdjpy and usdjpy.price is not None:
        topics.append(f"為替（米ドル/円{usdjpy.price:.2f}円）の水準は、外貨建て資産の話題にもつながります。")
    if sector_matches:
        top_sector = sorted(sector_matches, key=lambda m: len(m.tailwind) - len(m.headwind), reverse=True)[0]
        topics.append(f"「{top_sector.label}」のような成長テーマは、資産形成の話題として取り上げやすい分野です。")
    topics.append("NISA枠の活用状況を確認する良いタイミングかもしれません。")
    topics.append("相続・事業承継のご相談も、資産全体を棚卸しするきっかけになります。")
    return topics[:4]


def _casual_topics(general_headlines: List[Headline], limit: int = 3) -> List[str]:
    non_market = [
        h for h in general_headlines
        if not any(kw in h.title for kw in _MARKET_RELATED_KEYWORDS)
    ]
    if not non_market:
        return [f"本日は雑談に使える一般ニュースを取得できませんでした（{NOT_AVAILABLE}）。"]
    return [f"「{h.title}」（{h.source}）" for h in non_market[:limit]]


def _top_mover(stock_ranking: Dict[str, List[StockRankingEntry]]) -> Quote | None:
    candidates = stock_ranking.get("jp", []) + stock_ranking.get("us", [])
    with_data = [e for e in candidates if e.quote.change_pct is not None]
    if not with_data:
        return None
    return max(with_data, key=lambda e: abs(e.quote.change_pct)).quote


def _anticipated_qa(
    market: dict,
    scenario: ScenarioForecast,
    stock_ranking: Dict[str, List[StockRankingEntry]],
) -> List[QAItem]:
    qa = []

    usdjpy = find_quote(market["forex"], "米ドル/円")
    if usdjpy and usdjpy.price is not None:
        qa.append(
            QAItem(
                "ドル円どうなる？",
                f"現在は{usdjpy.price:.2f}円付近です。金利差や金融政策の動向次第で変動する可能性があります（断定はできません）。",
            )
        )
    else:
        qa.append(QAItem("ドル円どうなる？", f"為替データを取得できませんでした（{NOT_AVAILABLE}）。別途最新情報をご確認ください。"))

    top = _top_mover(stock_ranking)
    if top is not None:
        qa.append(
            QAItem(
                f"{top.name}はまだ買える？",
                f"{top.name}の直近値は{fmt_price(top.price)}（前日比{fmt_change(top.change, top.change_pct)}）です。"
                "個別の売買判断はご自身の責任でご確認ください。",
            )
        )

    n225 = find_quote(market["indices"], "日経")
    qa.append(
        QAItem(
            "日経平均は上がる？",
            f"AIの見立てでは強気{scenario.bull_pct}%・普通{scenario.neutral_pct}%・弱気{scenario.bear_pct}%です。"
            "将来を断定するものではなく、あくまで参考情報です。",
        )
    )

    qa.append(
        QAItem(
            "NISAって何？",
            BEGINNER_GLOSSARY[0].explanation,
        )
    )

    vix = find_quote(market["indices"], "VIX")
    if vix and vix.price is not None:
        qa.append(
            QAItem(
                "今の相場は荒れてる？",
                f"VIX指数（恐怖指数）は{vix.price:.2f}です。20を超えると警戒的、20未満だと落ち着いた水準の目安とされます。",
            )
        )

    return qa[:5]


def build_sales_prep(
    market: dict,
    scenario: ScenarioForecast,
    theme_matches: List[ThemeMatch],
    sector_matches: List[SectorMatch],
    stock_ranking: Dict[str, List[StockRankingEntry]],
    general_headlines: List[Headline],
) -> SalesPrep:
    return SalesPrep(
        ceo_lines=_ceo_lines(market, sector_matches),
        wealthy_topics=_wealthy_topics(market, sector_matches),
        beginner_glossary=list(BEGINNER_GLOSSARY),
        casual_topics=_casual_topics(general_headlines),
        qa=_anticipated_qa(market, scenario, stock_ranking),
    )
