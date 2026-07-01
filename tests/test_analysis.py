"""src/analysis/ 配下の各モジュールをネットワークなしで検証する。"""
from datetime import datetime

from src.analysis import (
    ai_summary,
    causal_chain,
    chat_topics,
    events,
    key_levels,
    long_term_picks,
    news_ranking,
    sales_prep,
    scenario,
    sector_ranking,
    stock_ranking,
    themes_forecast,
    watchlist_analysis,
    watchlist_quicklist,
)
from src.collectors.earnings import EarningsEvent
from src.collectors.market_data import Quote
from src.collectors.news import Headline
from src.collectors.themes import SectorMatch, ThemeMatch, match_sectors, match_themes


def _quote(name, price, change, change_pct, symbol="TEST"):
    return Quote(
        name=name,
        symbol=symbol,
        price=price,
        change=change,
        change_pct=change_pct,
        source_label="Test",
        source_url="https://example.com",
    )


def _market_with_data():
    return {
        "indices": [
            _quote("日経平均株価", 38000.0, 150.0, 0.4),
            _quote("NYダウ", 39500.0, 350.0, 0.9),
            _quote("S&P500", 5200.0, 30.0, 0.6),
            _quote("ナスダック総合", 16500.0, 100.0, 0.6),
            _quote("VIX指数（恐怖指数）", 14.5, -0.5, -3.3),
        ],
        "forex": [_quote("米ドル/円", 156.2, 0.3, 0.19)],
        "rates": [_quote("米10年国債利回り", 4.3, 0.02, 0.47)],
        "commodities": [],
    }


def test_scenario_probabilities_sum_to_100_with_data():
    market = _market_with_data()
    result = scenario.build_scenario(market, [])
    assert result.bull_pct + result.neutral_pct + result.bear_pct == 100
    assert result.bull_pct > result.bear_pct  # 好材料が多いケース


def test_scenario_probabilities_sum_to_100_without_data():
    empty_market = {"indices": [], "forex": [], "rates": [], "commodities": []}
    result = scenario.build_scenario(empty_market, [])
    assert result.bull_pct + result.neutral_pct + result.bear_pct == 100
    assert "取得不可" in result.reasoning


def test_causal_chain_has_six_arrow_linked_nodes():
    text = causal_chain.build_causal_chain(_market_with_data(), [], {})
    assert text.count("↓") == 5
    for node in ["米国株", "金利", "為替", "日本株", "業界", "個別株"]:
        assert node in text


def test_news_ranking_forces_single_top_pick():
    headlines = [
        Headline(title="どうでもいいニュース", link="https://example.com/1", source="Test"),
        Headline(title="半導体関連が上方修正、トヨタ自動車にも波及", link="https://example.com/2", source="Test"),
    ]
    ranking = news_ranking.build_news_ranking(headlines, ["半導体"], {}, ["トヨタ自動車"])
    top_picks = [item for item in ranking if item.is_top_pick]
    assert len(top_picks) == 1
    assert top_picks[0].rank == 1
    assert top_picks[0].headline.title == "半導体関連が上方修正、トヨタ自動車にも波及"


def test_theme_forecasts_ranked_by_headline_count():
    headlines = [Headline(title=f"半導体ニュース{i}", link="https://example.com", source="Test") for i in range(4)]
    headlines.append(Headline(title="円安ニュース", link="https://example.com", source="Test"))
    theme_matches = match_themes(headlines, ["半導体", "円安"])
    forecasts = themes_forecast.build_theme_forecasts(theme_matches)
    assert forecasts[0].label == "半導体"
    assert forecasts[0].rank == 1
    assert len(forecasts[0].headlines) == 4


def test_sector_ranking_capped_at_ten():
    sector_matches = [
        SectorMatch(label=f"業種{i}", tailwind=[Headline(title="上昇", link="x", source="t")], headwind=[], neutral=[], related_tickers=[])
        for i in range(15)
    ]
    ranking = sector_ranking.build_sector_ranking(sector_matches, {})
    assert len(ranking) == 10


def test_stock_ranking_ranks_by_absolute_change_and_caps_at_ten():
    quotes = [_quote(f"銘柄{i}", 100.0, i, float(i), symbol=f"T{i}") for i in range(1, 13)]
    result = stock_ranking.build_stock_ranking(quotes, [], [], [])
    assert len(result["jp"]) == 10
    assert result["jp"][0].quote.name == "銘柄12"  # 変化率絶対値が最大


def test_watchlist_analysis_covers_every_quote_not_just_top10():
    quotes = [_quote(f"銘柄{i}", 100.0, 0.1, 0.1, symbol=f"T{i}") for i in range(15)]
    result = watchlist_analysis.build_watchlist_analysis(quotes, [], [], [], [], datetime(2026, 7, 1))
    assert len(result["jp"]) == 15


def test_long_term_picks_capped_at_five_and_prefers_tailwind_sector():
    quotes = [_quote(f"銘柄{i}", 100.0, 0.1, 0.1, symbol=f"T{i}") for i in range(8)]
    tailwind_sector = SectorMatch(
        label="追い風業種",
        tailwind=[Headline(title="a", link="x", source="t"), Headline(title="b", link="x", source="t")],
        headwind=[],
        neutral=[],
        related_tickers=["T0"],
    )
    picks = long_term_picks.build_long_term_picks(quotes, [], [tailwind_sector], [])
    assert len(picks) == 5
    assert picks[0].quote.symbol == "T0"


def test_ai_summary_never_exceeds_300_chars():
    result = ai_summary.build_ai_summary(
        scenario.ScenarioForecast(60, 25, 15, "テスト理由" * 50),
        [],
        [],
    )
    assert len(result) <= 300


def test_chat_topics_always_returns_three_items():
    result = chat_topics.build_chat_topics({"indices": [], "forex": [], "rates": [], "commodities": []}, [], [])
    assert len(result) == 3
    assert len(set(result)) == 3  # フォールバック時も文言が重複しない


def test_events_breakdown_categorizes_by_days_until():
    reference = datetime(2026, 7, 1)
    earnings_events = [
        EarningsEvent(ticker="T1", name="今日決算", date="2026-07-01", source_url="https://example.com"),
        EarningsEvent(ticker="T2", name="今週決算", date="2026-07-05", source_url="https://example.com"),
        EarningsEvent(ticker="T3", name="今月決算", date="2026-07-20", source_url="https://example.com"),
    ]
    macro_events = [{"date": "2026-07-06", "label": "FOMC"}]
    breakdown = events.build_events_breakdown(earnings_events, [], macro_events, reference)
    assert any("今日決算" in line for line in breakdown.today)
    assert any("今週決算" in line for line in breakdown.this_week)
    assert any("今月決算" in line for line in breakdown.this_month)
    assert any("FOMC" in line for line in breakdown.this_week)


# --- ③ AIシナリオ分析強化: 強気/中立/弱気それぞれの理由・注目指標 ---


def test_scenario_populates_per_branch_reason_and_indicator():
    result = scenario.build_scenario(_market_with_data(), [])
    assert result.bull_reason and "取得不可" not in result.bull_reason
    assert result.neutral_reason
    assert result.bear_reason
    assert result.bull_indicator and result.neutral_indicator and result.bear_indicator
    for text in [result.bull_reason, result.neutral_reason, result.bear_reason]:
        assert "断定" not in text  # 断定的な表現を含まないこと


# --- ② 今日の重要ニュースランキング: 理由・影響市場・影響業種 ---


def test_news_ranking_includes_reason_and_affected_fields():
    headlines = [
        Headline(title="半導体関連が上方修正、トヨタ自動車にも波及", link="https://example.com/1", source="Test"),
        Headline(title="ドル円が急変動", link="https://example.com/2", source="Test"),
    ]
    ranking = news_ranking.build_news_ranking(headlines, ["半導体"], {}, ["トヨタ自動車"])
    top = ranking[0]
    assert top.reason
    assert top.affected_market in {"為替", "米国株", "日本株", "金利", "市場全体"}
    assert top.affected_sector

    fx_item = next(item for item in ranking if item.headline.title == "ドル円が急変動")
    assert fx_item.affected_market == "為替"


# --- ④ 因果チェーン: 3〜5本の短い原因→影響→影響先チェーン ---


def test_build_causal_chains_returns_multiple_short_chains():
    market = _market_with_data()
    sector_matches = [
        SectorMatch(
            label="半導体・電子部品",
            tailwind=[Headline(title="半導体上方修正", link="x", source="t")],
            headwind=[],
            neutral=[],
            related_tickers=["T0"],
        )
    ]
    theme_matches = match_themes(
        [Headline(title=f"半導体ニュース{i}", link="x", source="t") for i in range(3)], ["半導体"]
    )
    ticker_lookup = {"T0": _quote("テスト銘柄", 100.0, 1.0, 1.0, symbol="T0")}

    chains = causal_chain.build_causal_chains(market, sector_matches, theme_matches, ticker_lookup)
    assert 1 <= len(chains) <= 5
    for chain in chains:
        assert "↓" in chain


def test_build_causal_chains_empty_when_no_data():
    empty_market = {"indices": [], "forex": [], "rates": [], "commodities": []}
    chains = causal_chain.build_causal_chains(empty_market, [], [], {})
    assert chains == []


# --- ⑤ 今日見るべき指標 ---


def test_key_levels_picks_nearest_line_and_note():
    market = _market_with_data()
    config = {
        "key_levels": [
            {
                "name": "米ドル/円",
                "lines": [150, 155, 160],
                "above_note": "円安が進行しやすい水準です。",
                "below_note": "円高方向への転換が意識されやすい水準です。",
            }
        ]
    }
    entries = key_levels.build_key_levels(market, config)
    assert len(entries) == 1
    entry = entries[0]
    assert entry.key_line == 155  # 156.2に最も近いライン
    assert entry.note == "円安が進行しやすい水準です。"


def test_key_levels_handles_missing_quote():
    empty_market = {"indices": [], "forex": [], "rates": [], "commodities": []}
    config = {"key_levels": [{"name": "米ドル/円", "lines": [150], "above_note": "a", "below_note": "b"}]}
    entries = key_levels.build_key_levels(empty_market, config)
    assert len(entries) == 1
    assert "取得不可" in entries[0].note


# --- ⑥ 今日のウォッチリスト ---


def test_watchlist_quicklist_covers_all_quotes_with_stars_and_reason():
    quotes = [_quote(f"銘柄{i}", 100.0, 1.0, 1.0, symbol=f"T{i}") for i in range(12)]
    result = watchlist_quicklist.build_watchlist_quicklist(quotes, [], [], [])
    assert len(result["jp"]) == 12
    for entry in result["jp"]:
        assert entry.stars
        assert entry.reason


# --- ① 営業準備 ---


def test_sales_prep_generates_all_content_types():
    market = _market_with_data()
    forecast = scenario.build_scenario(market, [])
    stock_ranking_result = {"jp": [], "us": []}
    general_headlines = [
        Headline(title="大谷翔平が話題の新記録", link="https://example.com/1", source="Test"),
        Headline(title="日経平均が上昇", link="https://example.com/2", source="Test"),  # 市場系は除外される
    ]
    result = sales_prep.build_sales_prep(market, forecast, [], [], stock_ranking_result, general_headlines)

    assert result.ceo_lines
    assert result.wealthy_topics
    assert len(result.beginner_glossary) == 4
    assert any("大谷翔平" in topic for topic in result.casual_topics)
    assert not any("日経平均" in topic for topic in result.casual_topics)
    assert 1 <= len(result.qa) <= 5


def test_sales_prep_casual_topics_fallback_when_no_general_news():
    market = _market_with_data()
    forecast = scenario.build_scenario(market, [])
    result = sales_prep.build_sales_prep(market, forecast, [], [], {"jp": [], "us": []}, [])
    assert "取得不可" in result.casual_topics[0]
