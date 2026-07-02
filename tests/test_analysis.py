"""src/analysis/ 配下の各モジュールをネットワークなしで検証する。"""
from datetime import datetime

from src.analysis import (
    ai_summary,
    call_priority,
    causal_chain,
    chat_topics,
    events,
    executive_summary,
    instrument_scenarios,
    key_levels,
    long_term_picks,
    market_impact,
    morning_meeting_comment,
    news_ranking,
    okasan_sales_comments,
    sales_comments,
    sales_prep,
    scenario,
    sector_ranking,
    sector_strength,
    stock_ranking,
    themes_forecast,
    top_picks,
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


# --- 営業向けコメント（7オーディエンス）と想定質問と回答例 ---


def test_sales_comments_generates_all_seven_audiences_without_definitive_language():
    market = _market_with_data()
    forecast = scenario.build_scenario(market, [])
    jp_quotes = [_quote("トヨタ自動車", 3200.0, 20.0, 0.6, symbol="7203.T")]
    us_quotes = [_quote("NVIDIA", 120.0, 3.0, 2.6, symbol="NVDA")]

    result = sales_comments.build_sales_comments(market, forecast, [], [], jp_quotes, us_quotes)

    hedge_phrases = ("可能性があります", "注目されています", "局面です", "考えられます")
    for text in (
        result.corporate,
        result.wealthy,
        result.retail,
        result.nisa_beginner,
        result.fx_interested,
        result.us_stock_interested,
        result.jp_stock_interested,
    ):
        assert text
        assert any(phrase in text for phrase in hedge_phrases)


def test_sales_comments_handles_missing_market_data():
    empty_market = {"indices": [], "forex": [], "rates": [], "commodities": []}
    forecast = scenario.build_scenario(empty_market, [])
    result = sales_comments.build_sales_comments(empty_market, forecast, [], [], [], [])
    assert "取得不可" in result.corporate or "取得不可" in result.retail


def test_expanded_qa_includes_the_five_required_questions():
    market = _market_with_data()
    forecast = scenario.build_scenario(market, [])
    us_quotes = [_quote("NVIDIA", 120.0, 3.0, 2.6, symbol="NVDA")]

    qa_items = sales_comments.build_expanded_qa(market, forecast, [], [], us_quotes)
    questions = [item.question for item in qa_items]

    assert "日経平均はまだ上がりますか？" in questions
    assert "円安は続きますか？" in questions
    assert "NVIDIAはまだ強いですか？" in questions
    assert "日本株で今見るべき業種は？" in questions
    assert "NISAで何を買えばいいですか？" in questions
    for item in qa_items:
        assert item.answer


def test_expanded_qa_handles_missing_nvda_quote():
    market = _market_with_data()
    forecast = scenario.build_scenario(market, [])
    qa_items = sales_comments.build_expanded_qa(market, forecast, [], [], [])
    nvda_answer = next(item.answer for item in qa_items if item.question == "NVIDIAはまだ強いですか？")
    assert "取得不可" in nvda_answer


# --- v3: 今日の注目5銘柄 ---


def test_top_picks_returns_at_most_five_per_market_ranked_by_absolute_change():
    jp_quotes = [_quote(f"日本株{i}", 100.0, i, float(i), symbol=f"J{i}") for i in range(1, 8)]
    us_quotes = [_quote(f"米国株{i}", 100.0, i, float(i), symbol=f"U{i}") for i in range(1, 4)]
    result = top_picks.build_top_picks(jp_quotes, us_quotes, [], [])
    assert len(result["jp"]) == 5
    assert len(result["us"]) == 3
    assert result["jp"][0].rank == 1
    # 変化率の絶対値が大きい順（最大はJ7の7%）
    assert result["jp"][0].quote.symbol == "J7"
    for entry in result["jp"] + result["us"]:
        assert entry.reason
        assert entry.material
        assert entry.short_term


def test_top_picks_empty_when_no_quotes():
    result = top_picks.build_top_picks([], [], [], [])
    assert result == {"jp": [], "us": []}


# --- v3: 日経平均・ドル円・米国市場 個別シナリオ ---


def test_instrument_scenarios_returns_three_entries_with_data():
    market = _market_with_data()
    result = instrument_scenarios.build_instrument_scenarios(market, [])
    labels = [s.label for s in result]
    assert labels == ["日経平均", "ドル円", "米国市場"]
    for s in result:
        assert s.outlook
        assert s.key_driver
        assert s.bull_text
        assert s.neutral_text
        assert s.bear_text


def test_instrument_scenarios_handles_missing_data():
    empty_market = {"indices": [], "forex": [], "rates": [], "commodities": []}
    result = instrument_scenarios.build_instrument_scenarios(empty_market, [])
    for s in result:
        assert "取得不可" in s.outlook


def test_instrument_scenarios_mentions_boj_headline_for_usdjpy():
    market = _market_with_data()
    headlines = [Headline(title="日銀、金融政策を維持", link="https://example.com", source="Test")]
    result = instrument_scenarios.build_instrument_scenarios(market, headlines)
    usdjpy_scenario = next(s for s in result if s.label == "ドル円")
    assert "日銀" in usdjpy_scenario.outlook


# --- v3: 岡三証券営業向けコメント ---


def test_okasan_sales_comments_generates_all_five_customer_types():
    market = _market_with_data()
    forecast = scenario.build_scenario(market, [])
    jp_quotes = [_quote("トヨタ自動車", 3200.0, 20.0, 0.6, symbol="7203.T")]

    result = okasan_sales_comments.build_okasan_sales_comments(market, forecast, [], [], jp_quotes)

    for text in (result.wealthy, result.corporate, result.nisa, result.retirement, result.inheritance):
        assert text
        assert "断定" not in text


def test_okasan_sales_comments_handles_missing_market_data():
    empty_market = {"indices": [], "forex": [], "rates": [], "commodities": []}
    forecast = scenario.build_scenario(empty_market, [])
    result = okasan_sales_comments.build_okasan_sales_comments(empty_market, forecast, [], [], [])
    assert "取得不可" in result.wealthy or "取得不可" in result.corporate


# --- v4: AI Executive Summary ---


def test_executive_summary_builds_up_to_three_items_with_impacts():
    market = _market_with_data()
    headlines = [
        Headline(title=f"半導体関連ニュース{i}", link=f"https://example.com/{i}", source="Test")
        for i in range(5)
    ]
    news_items = news_ranking.build_news_ranking(headlines, ["半導体"], {}, [])
    sector_matches = match_sectors(headlines, {"半導体・電子部品": {"keywords": ["半導体"], "related_tickers": ["8035.T"]}})
    ticker_lookup = {"8035.T": _quote("東京エレクトロン", 25000.0, 100.0, 0.4, symbol="8035.T")}

    result = executive_summary.build_executive_summary(news_items, market, sector_matches, ticker_lookup)

    assert 1 <= len(result) <= 3
    for item in result:
        assert item.conclusion
        assert item.jp_stock_impact
        assert item.usdjpy_impact
        assert item.rate_impact
        assert len(item.sales_talk) <= 100


def test_executive_summary_empty_when_no_news():
    market = _market_with_data()
    result = executive_summary.build_executive_summary([], market, [], {})
    assert result == []


# --- v4: 今日電話すべき顧客 ---


def test_call_priorities_covers_six_customer_types():
    market = _market_with_data()
    forecast = scenario.build_scenario(market, [])
    result = call_priority.build_call_priorities(market, forecast, [], [])
    customer_types = {entry.customer_type for entry in result}
    assert customer_types == {"富裕層", "NISA", "退職金", "法人", "相続", "若年層"}
    for entry in result:
        assert entry.reason
        assert entry.topic
        assert entry.sales_talk


# --- v4: マーケットインパクト ---


def test_market_impact_covers_all_twelve_targets():
    market = _market_with_data()
    headlines = [Headline(title="トヨタ自動車が増産", link="https://example.com/1", source="Test")]
    result = market_impact.build_market_impact(market, headlines)
    targets = [entry.target for entry in result]
    assert targets == [
        "日経平均", "TOPIX", "ドル円", "長期金利",
        "半導体", "銀行", "商社", "自動車", "海運", "電力", "素材", "不動産",
    ]
    for entry in result:
        assert entry.direction in ("プラス", "マイナス", "中立")


def test_market_impact_handles_missing_market_data():
    empty_market = {"indices": [], "forex": [], "rates": [], "commodities": []}
    result = market_impact.build_market_impact(empty_market, [])
    assert len(result) == 12


# --- v4: セクターランキング（強弱予測） ---


def test_sector_strength_arrow_reflects_tailwind_headwind_balance():
    tailwind_headline = Headline(title="上昇", link="https://example.com/1", source="Test")
    headwind_headline = Headline(title="下落", link="https://example.com/2", source="Test")
    sector_matches = [
        SectorMatch(label="強い業種", tailwind=[tailwind_headline, tailwind_headline], headwind=[], neutral=[], related_tickers=[]),
        SectorMatch(label="弱い業種", tailwind=[], headwind=[headwind_headline], neutral=[], related_tickers=[]),
    ]
    result = sector_strength.build_sector_strength(sector_matches)
    by_label = {entry.label: entry for entry in result}
    assert by_label["強い業種"].arrow == "↑"
    assert by_label["弱い業種"].arrow == "↓"
    # 強そう(↑)が先頭に来るよう並べ替えられていること
    assert result[0].label == "強い業種"


# --- v4: 朝会コメント（30秒/1分/3分） ---


def test_morning_meeting_comment_generates_three_lengths_within_limits():
    market = _market_with_data()
    forecast = scenario.build_scenario(market, [])
    headline = Headline(title="半導体関連株が上昇", link="https://example.com/1", source="Test")
    news_items = news_ranking.build_news_ranking([headline], ["半導体"], {}, [])

    result = morning_meeting_comment.build_morning_meeting_comment(forecast, news_items, [], [])

    assert result.short_30s and len(result.short_30s) <= 130
    assert result.medium_1min and len(result.medium_1min) <= 300
    assert result.long_3min and len(result.long_3min) <= 750
    assert len(result.short_30s) < len(result.medium_1min) < len(result.long_3min)
