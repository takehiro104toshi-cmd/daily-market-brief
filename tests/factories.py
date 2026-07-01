"""テスト用の共通フィクスチャ生成ヘルパー（test_report_builder.py / test_mobile_builder.py で共有）。"""
from __future__ import annotations

from src.analysis.models import (
    AnalysisBundle,
    EventsBreakdown,
    GlossaryItem,
    KeyLevelEntry,
    LongTermPick,
    NewsRankingItem,
    QAItem,
    SalesPrep,
    SalesTalkBullets,
    ScenarioForecast,
    SectorRankingEntry,
    StockRankingEntry,
    ThemeForecast,
    WatchlistEntry,
    WatchlistQuickEntry,
)
from src.collectors.market_data import Quote
from src.collectors.news import Headline


def make_quote(name, price, change, change_pct, symbol="TEST"):
    return Quote(
        name=name,
        symbol=symbol,
        price=price,
        change=change,
        change_pct=change_pct,
        source_label="Test Source",
        source_url="https://example.com/test",
    )


def full_market() -> dict:
    return {
        "indices": [
            make_quote("日経平均株価", 38000.0, 150.0, 0.4),
            make_quote("NYダウ", 39500.0, -80.0, -0.2),
            make_quote("VIX指数（恐怖指数）", 24.5, 0.5, 2.8),
        ],
        "forex": [make_quote("米ドル/円", 156.2, 0.3, 0.19)],
        "rates": [make_quote("米10年国債利回り", 4.3, 0.02, 0.47)],
        "commodities": [make_quote("WTI原油先物", 78.1, -0.5, -0.6)],
    }


def full_bundle() -> AnalysisBundle:
    headline = Headline(title="半導体関連株が上昇", link="https://example.com/1", source="Test")
    toyota = make_quote("トヨタ自動車", 3200.0, 20.0, 0.6, symbol="7203.T")
    sony = make_quote("ソニーグループ", 2500.0, -10.0, -0.4, symbol="6758.T")
    apple = make_quote("Apple", 210.0, 1.2, 0.6, symbol="AAPL")
    msft = make_quote("Microsoft", 430.0, -2.0, -0.5, symbol="MSFT")

    return AnalysisBundle(
        scenario=ScenarioForecast(
            bull_pct=55,
            neutral_pct=30,
            bear_pct=15,
            reasoning="NYダウが上昇したことなどから。",
            bull_reason="NYダウが底堅く推移していることなどが続けば、上値を試す展開もあり得ると考えられます。",
            neutral_reason="強気・弱気材料が拮抗しており、方向感を欠く展開が続く可能性も考えられます。",
            bear_reason="VIX指数が警戒的な水準にあることなどを踏まえると、下押しリスクも意識される可能性があります。",
            bull_indicator="NYダウ・S&P500",
            neutral_indicator="米10年金利・為替",
            bear_indicator="VIX指数",
        ),
        news_ranking=[
            NewsRankingItem(
                rank=1,
                stars="★★★★★",
                headline=headline,
                is_top_pick=True,
                reason="テーマ「半導体」に関連するため、重要度が高いと判断しました。",
                affected_market="日本株",
                affected_sector="半導体・電子部品",
            ),
        ],
        causal_chain_text="**米国株**: NYダウ +0.50 (+0.20%)\n\n↓\n\n**個別株**: 追い風の可能性",
        causal_chains=[
            "米金利↑\n↓\nドル高圧力\n↓\n円安方向\n↓\n輸出関連株に追い風\n↓\n自動車・精密機器",
            "「半導体・電子部品」に追い風ニュース\n↓\n投資マネーの物色\n↓\n関連銘柄への資金流入\n↓\nトヨタ自動車",
        ],
        theme_forecasts=[
            ThemeForecast(
                rank=1,
                label="半導体",
                stars="★★★☆☆",
                why_now="半導体関連の報道が続いています。",
                outlook_1w="値動きが荒くなる可能性があります。",
                outlook_1m="物色の中心であり続ける可能性があります。",
                outlook_3m="構造的なテーマとして意識され続ける可能性があります。",
                headlines=[headline],
            )
        ],
        sector_ranking=[
            SectorRankingEntry(
                rank=1,
                label="半導体・電子部品",
                stars="★★★☆☆",
                tailwind=[headline],
                headwind=[],
                related=[toyota],
                related_unresolved=["9999.T"],
                sales_talk="「本日は半導体・電子部品に追い風のニュースが目立ちます」",
            )
        ],
        stock_ranking={
            "jp": [
                StockRankingEntry(rank=1, quote=toyota, stars="★★★★☆", short_term="短期材料あり。", mid_term="中期材料あり。", long_term="長期材料あり。"),
                StockRankingEntry(rank=2, quote=sony, stars="★★★☆☆", short_term="短期材料あり。", mid_term="中期材料あり。", long_term="長期材料あり。"),
            ],
            "us": [
                StockRankingEntry(rank=1, quote=apple, stars="★★★☆☆", short_term="短期材料あり。", mid_term="中期材料あり。", long_term="長期材料あり。"),
                StockRankingEntry(rank=2, quote=msft, stars="★★☆☆☆", short_term="短期材料あり。", mid_term="中期材料あり。", long_term="長期材料あり。"),
            ],
        },
        watchlist_analysis={
            "jp": [WatchlistEntry(quote=toyota, today="今日の材料。", next_week="来週の見立て。", next_month="来月の見立て。", long_term="長期評価。")],
            "us": [WatchlistEntry(quote=apple, today="今日の材料。", next_week="来週の見立て。", next_month="来月の見立て。", long_term="長期評価。")],
        },
        watchlist_quicklist={
            "jp": [
                WatchlistQuickEntry(quote=toyota, stars="★★★★☆", reason="業種「半導体・電子部品」に追い風の動きがあります。"),
                WatchlistQuickEntry(quote=sony, stars="★★★☆☆", reason="前日比下落、個別の材料は確認されませんでした。"),
            ],
            "us": [
                WatchlistQuickEntry(quote=apple, stars="★★★☆☆", reason="前日比上昇、個別の材料は確認されませんでした。"),
                WatchlistQuickEntry(quote=msft, stars="★★☆☆☆", reason="前日比下落、個別の材料は確認されませんでした。"),
            ],
        },
        long_term_picks=[LongTermPick(rank=1, quote=toyota, reasoning="長期候補として選定。")],
        sales_talk_bullets=SalesTalkBullets(
            corporate=["「法人社長向けトーク1」", "「法人社長向けトーク2」"],
            retail=["「個人投資家向けトーク1」"],
            beginner=["「初心者向けトーク1」"],
            wealthy=["「富裕層向けトーク1」"],
        ),
        sales_talk_text="### 法人社長向け\n- 「テスト」\n\n### 個人投資家向け\n- 「テスト」\n\n### 初心者向け\n- 「テスト」\n\n### 富裕層向け\n- 「テスト」\n",
        sales_prep=SalesPrep(
            ceo_lines=["半導体関連が注目されています", "ドル円の変動が企業業績へ影響します"],
            wealthy_topics=["NISA枠の活用状況を確認する良いタイミングかもしれません。"],
            beginner_glossary=[GlossaryItem("NISA", "少額投資非課税制度の愛称です。")],
            casual_topics=["「大型イベントのニュース」（Test）"],
            qa=[QAItem("ドル円どうなる？", "現在は156.20円付近です（断定はできません）。")],
        ),
        key_levels=[
            KeyLevelEntry(label="米ドル/円", quote=make_quote("米ドル/円", 156.2, 0.3, 0.19), key_line=155, note="円安が進行しやすい水準です。"),
        ],
        chat_topics=["雑談ネタ1", "雑談ネタ2", "雑談ネタ3"],
        events=EventsBreakdown(today=["[適時開示] 09:00 テスト社（0000）: テスト開示"], this_week=["[決算発表予定] テスト社: 2026-07-05"], this_month=[]),
        ai_summary_text="本日の相場は強気55%と見立てています。投資助言ではありません。",
    )


def empty_bundle() -> AnalysisBundle:
    return AnalysisBundle(
        scenario=ScenarioForecast(
            bull_pct=30,
            neutral_pct=40,
            bear_pct=30,
            reasoning="データ不足のため暫定値です（取得不可）。",
            bull_reason="データ不足のため理由を算出できませんでした（取得不可）。",
            neutral_reason="データ不足のため理由を算出できませんでした（取得不可）。",
            bear_reason="データ不足のため理由を算出できませんでした（取得不可）。",
            bull_indicator="NYダウ・S&P500",
            neutral_indicator="米10年金利・為替",
            bear_indicator="VIX指数",
        ),
        news_ranking=[],
        causal_chain_text="データ不足のため因果関係を整理できませんでした（取得不可）。",
        causal_chains=[],
        theme_forecasts=[],
        sector_ranking=[],
        stock_ranking={"jp": [], "us": []},
        watchlist_analysis={"jp": [], "us": []},
        watchlist_quicklist={"jp": [], "us": []},
        long_term_picks=[],
        sales_talk_bullets=SalesTalkBullets(),
        sales_talk_text="本日は営業トークを生成できませんでした（取得不可）。",
        sales_prep=SalesPrep(),
        key_levels=[],
        chat_topics=[],
        events=EventsBreakdown(),
        ai_summary_text="本日は主要データを十分に取得できなかったため、AIまとめを生成できませんでした（取得不可）。",
    )
