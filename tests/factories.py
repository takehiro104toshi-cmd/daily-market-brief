"""テスト用の共通フィクスチャ生成ヘルパー（test_report_builder.py / test_mobile_builder.py で共有）。"""
from __future__ import annotations

from src.analysis.models import (
    AnalysisBundle,
    CallPriorityEntry,
    EventsBreakdown,
    ExecutiveSummaryItem,
    GlossaryItem,
    InstrumentScenario,
    KeyLevelEntry,
    LongTermPick,
    MarketImpactEntry,
    MorningMeetingComment,
    NewsRankingItem,
    OkasanSalesComments,
    QAItem,
    SalesComments,
    SalesPrep,
    SalesTalkBullets,
    ScenarioForecast,
    SectorRankingEntry,
    SectorStrengthEntry,
    StockRankingEntry,
    ThemeForecast,
    TopPickEntry,
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
                sales_talk="「半導体」関連は材料出尽くしや利益確定売りが入りやすい局面と考えられます。",
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
            "jp": [WatchlistEntry(quote=toyota, today="今日の材料。", next_week="来週の見立て。", next_month="来月の見立て。", long_term="長期評価。", risk="リスク要因。")],
            "us": [WatchlistEntry(quote=apple, today="今日の材料。", next_week="来週の見立て。", next_month="来月の見立て。", long_term="長期評価。", risk="リスク要因。")],
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
        sales_comments=SalesComments(
            corporate="法人社長向けコメントの例です。",
            wealthy="富裕層向けコメントの例です。",
            retail="個人投資家向けコメントの例です。",
            nisa_beginner="NISA初心者向けコメントの例です。",
            fx_interested="為替に関心がある顧客向けコメントの例です。",
            us_stock_interested="米国株に関心がある顧客向けコメントの例です。",
            jp_stock_interested="日本株に関心がある顧客向けコメントの例です。",
        ),
        expanded_qa=[
            QAItem("日経平均はまだ上がりますか？", "強気55%・中立30%・弱気15%です（断定はできません）。"),
            QAItem("円安は続きますか？", "現在は156.20円付近です（断定はできません）。"),
        ],
        top_picks={
            "jp": [
                TopPickEntry(rank=1, quote=toyota, stars="★★★★☆", reason="前日比+0.60%と値動きが大きく、本日の注目銘柄として選定しました。", material="「半導体関連株が上昇」（Test）", short_term="業種「半導体・電子部品」への追い風が続けば、短期的に堅調な推移が意識される可能性があります。"),
            ],
            "us": [
                TopPickEntry(rank=1, quote=apple, stars="★★★☆☆", reason="前日比+0.60%と値動きが大きく、本日の注目銘柄として選定しました。", material="個別の関連見出しは確認されていません（取得不可または該当なし）。", short_term="業種動向からの短期見通しは、本日時点では判断材料が不足しています。"),
            ],
        },
        instrument_scenarios=[
            InstrumentScenario(label="日経平均", outlook="前日は+0.40%と底堅い動きでした。為替が円安方向にあり、輸出関連株には追い風となりやすい局面です。", key_driver="米ドル/円（円安方向）", bull_text="上値を試す展開の可能性があります。", neutral_text="レンジ内推移の可能性があります。", bear_text="下押しする可能性があります。"),
            InstrumentScenario(label="ドル円", outlook="現在は156.20円付近で推移しています。米金利が上昇方向にあり、日米金利差の観点から円安圧力が意識されやすい局面です。", key_driver="米10年金利（上昇方向）", bull_text="円安方向にシフトする可能性があります。", neutral_text="レンジ内推移の可能性があります。", bear_text="円高方向にシフトする可能性があります。"),
            InstrumentScenario(label="米国市場", outlook="主要3指数の方向感がまちまちで、強弱材料が拮抗している状況です。VIX指数は24.50と警戒的な水準にあります。", key_driver="VIX指数（警戒水準）", bull_text="上値を試す展開の可能性があります。", neutral_text="レンジ内推移の可能性があります。", bear_text="下押しする可能性があります。"),
        ],
        okasan_sales_comments=OkasanSalesComments(
            wealthy="富裕層のお客様向けコメントの例です。",
            corporate="法人のお客様向けコメントの例です。",
            nisa="NISAご利用のお客様向けコメントの例です。",
            retirement="退職金のご相談のお客様向けコメントの例です。",
            inheritance="相続・資産承継のご相談のお客様向けコメントの例です。",
        ),
        executive_summary=[
            ExecutiveSummaryItem(
                rank=1,
                headline=headline,
                stars="★★★★★",
                conclusion="「半導体関連株が上昇」（Test）",
                reason="テーマ「半導体」に関連するため、重要度が高いと判断しました。",
                jp_stock_impact="東京エレクトロンなど「半導体・電子部品」関連銘柄への追い風が意識されやすい局面です。",
                usdjpy_impact="為替への直接的な影響は限定的とみられます。",
                rate_impact="金利への直接的な影響は限定的とみられます。",
                sales_talk="半導体関連は短期的に利益確定売りが入りやすい状況です。",
            ),
        ],
        call_priorities=[
            CallPriorityEntry(customer_type="富裕層", reason="為替・金利の動きがあり、資産配分の見直し話題としてお声がけしやすいタイミングです。", topic="外貨建て資産・分散投資の状況確認", sales_talk="市場環境の変化を踏まえ、資産配分を確認するお時間をいただけますでしょうか。"),
            CallPriorityEntry(customer_type="NISA", reason="市場のボラティリティが落ち着いており、積立方針を再確認いただく良いタイミングです。", topic="NISA枠の活用状況", sales_talk="積立方針を一緒に確認させていただけますでしょうか。"),
            CallPriorityEntry(customer_type="退職金", reason="生活資金とのバランス確認が重要な局面です。", topic="時間分散の考え方", sales_talk="退職金の運用方針について整理するお時間を頂戴できればと思います。"),
            CallPriorityEntry(customer_type="法人", reason="為替・金利の動きが資金調達コストに影響しうる局面です。", topic="為替・金利ヘッジの状況確認", sales_talk="資金計画を確認するお時間をいただけますでしょうか。"),
            CallPriorityEntry(customer_type="相続", reason="資産全体の棚卸しをするきっかけとしてお声がけしやすい局面です。", topic="資産全体の棚卸し", sales_talk="資産状況を一度整理するお手伝いができればと思います。"),
            CallPriorityEntry(customer_type="若年層", reason="話題性のあるテーマが注目されており、投資を始めるきっかけになりやすい局面です。", topic="少額投資・積立投資の始め方", sales_talk="少額から始められる積立投資について、一度お話しさせていただけますでしょうか。"),
        ],
        market_impact=[
            MarketImpactEntry(target="日経平均", stars="★★☆☆☆", direction="プラス"),
            MarketImpactEntry(target="TOPIX", stars="★☆☆☆☆", direction="中立"),
            MarketImpactEntry(target="ドル円", stars="★☆☆☆☆", direction="プラス"),
            MarketImpactEntry(target="長期金利", stars="★☆☆☆☆", direction="プラス"),
            MarketImpactEntry(target="半導体", stars="★★★☆☆", direction="プラス"),
            MarketImpactEntry(target="銀行", stars="★☆☆☆☆", direction="中立"),
            MarketImpactEntry(target="商社", stars="★☆☆☆☆", direction="中立"),
            MarketImpactEntry(target="自動車", stars="★☆☆☆☆", direction="中立"),
            MarketImpactEntry(target="海運", stars="★☆☆☆☆", direction="中立"),
            MarketImpactEntry(target="電力", stars="★☆☆☆☆", direction="中立"),
            MarketImpactEntry(target="素材", stars="★☆☆☆☆", direction="中立"),
            MarketImpactEntry(target="不動産", stars="★☆☆☆☆", direction="中立"),
        ],
        sector_strength=[
            SectorStrengthEntry(label="半導体・電子部品", arrow="↑", reason="追い風ニュースが1件と逆風（0件）を上回っており、強含みが意識されやすい状況です。"),
        ],
        morning_meeting_comment=MorningMeetingComment(
            short_30s="おはようございます。本日の相場は強気55%、弱気15%と見立てています。最重要ニュースは「半導体関連株が上昇」です。以上、簡単ですが朝の相場感の共有でした。",
            medium_1min="おはようございます。本日の相場は強気55%・中立30%・弱気15%と見立てています。NYダウが上昇したことなどから。注目ニュースとして「半導体関連株が上昇」が挙げられ、テーマ「半導体」に関連するため、重要度が高いと判断しました。本日のテーマとしては「半導体」が注目されています。いずれも情報整理であり、投資助言ではない点にご留意ください。",
            long_3min="おはようございます。本日の朝会コメントをお伝えします。本日の相場シナリオは、強気55%・中立30%・弱気15%です。NYダウが上昇したことなどから。強気シナリオの理由としては、NYダウが底堅く推移していることなどが続けば、上値を試す展開もあり得ると考えられます。注目ニュースとして「半導体関連株が上昇」があり、テーマ「半導体」に関連するため、重要度が高いと判断しました。業種では「半導体・電子部品」に追い風の材料が優勢で、資金流入余地が意識されています。テーマとしては「半導体」が引き続き注目されています。以上、いずれも公開情報に基づく機械的な考察であり、投資助言ではありません。本日もよろしくお願いいたします。",
        ),
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
