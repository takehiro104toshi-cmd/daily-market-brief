"""src/analysis/strategist_engine.py をネットワークなしで検証する。

「岡三ストラテジスト視点」パイプライン（ニュース→ストラテジスト視点→重要
テーマ→関連セクター→恩恵銘柄→悪影響銘柄→営業ポイント→重要度）と、
8軸★スコアリングが期待通りに機能することを確認する。
"""
from src.analysis import news_ranking, strategist_engine
from src.collectors.news import Headline

SECTORS = {
    "自動車": {"keywords": ["自動車", "トヨタ"], "related_tickers": ["7203.T"]},
    "資源・エネルギー": {"keywords": ["原油", "資源"], "related_tickers": []},
    "半導体・電子部品": {"keywords": ["半導体"], "related_tickers": ["8035.T"]},
}

CAUSAL_RULES = [
    {
        "trigger_keywords": ["原油安", "原油下落"],
        "theme": "資源価格",
        "beneficiary_sectors": ["自動車"],
        "negative_sectors": ["資源・エネルギー"],
        "durable": False,
        "note": "原油安は輸送コスト低下を通じて自動車関連には追い風となりやすい",
    },
    {
        "trigger_keywords": ["半導体投資拡大"],
        "theme": "AI・半導体設備投資",
        "beneficiary_sectors": ["半導体・電子部品"],
        "negative_sectors": [],
        "durable": True,
        "note": "AI関連の設備投資拡大は周辺サプライチェーンへ波及しやすい",
    },
]

CONFIG = {
    "themes": ["半導体", "資源"],
    "sectors": SECTORS,
    "durable_themes": ["半導体"],
    "causal_rules": CAUSAL_RULES,
}


class _Quote:
    def __init__(self, symbol, name):
        self.symbol = symbol
        self.name = name


TICKER_LOOKUP = {"7203.T": _Quote("7203.T", "トヨタ自動車"), "8035.T": _Quote("8035.T", "東京エレクトロン")}


def _headline(title):
    return Headline(title=title, link="https://example.com", source="Test")


def test_build_strategist_views_resolves_beneficiary_and_negative_tickers():
    headlines = [_headline("原油安が進行、資源国通貨が下落")]
    ranking = news_ranking.build_news_ranking(headlines, [], SECTORS, [])
    views = strategist_engine.build_strategist_views(ranking, CONFIG, TICKER_LOOKUP)

    assert len(views) == 1
    view = views[0]
    assert view.theme == "資源価格"
    assert "トヨタ自動車" in view.beneficiary_names
    assert view.negative_names == []  # 資源・エネルギーのrelated_tickersは空のため
    assert view.score is not None
    assert view.importance_stars.count("★") >= 1


def test_durable_theme_boosts_continuity_and_weeks_ahead():
    headline = _headline("半導体投資拡大が続く")
    durable_score = strategist_engine.score_headline_8axis(
        headline=headline,
        matched_themes=["半導体"],
        matched_sector="半導体・電子部品",
        causal_rule=strategist_engine.parse_causal_rules(CAUSAL_RULES)[1],
        durable_themes=["半導体"],
        beneficiary_tickers=["8035.T"],
        negative_tickers=[],
        watchlist_names=[],
    )
    assert durable_score.continuity == 5
    assert durable_score.weeks_ahead == 5

    one_off_headline = _headline("自動車メーカーが規制対応で撤退")
    one_off_score = strategist_engine.score_headline_8axis(
        headline=one_off_headline,
        matched_themes=[],
        matched_sector="自動車",
        causal_rule=None,
        durable_themes=["半導体"],
        beneficiary_tickers=[],
        negative_tickers=[],
        watchlist_names=[],
    )
    assert one_off_score.continuity < durable_score.continuity
    assert one_off_score.weeks_ahead < durable_score.weeks_ahead


def test_score_headline_8axis_all_axes_clipped_between_1_and_5():
    headline = _headline("上方修正 買収 提携 決算 規制 撤退")
    score = strategist_engine.score_headline_8axis(
        headline=headline,
        matched_themes=["半導体", "資源"],
        matched_sector="半導体・電子部品",
        causal_rule=strategist_engine.parse_causal_rules(CAUSAL_RULES)[1],
        durable_themes=["半導体"],
        beneficiary_tickers=["8035.T", "7203.T", "9999.T"],
        negative_tickers=["1111.T"],
        watchlist_names=["トヨタ自動車"],
    )
    for axis_value in (
        score.market_impact,
        score.continuity,
        score.sales_value,
        score.jp_impact,
        score.us_impact,
        score.stock_expansion,
        score.theme_expansion,
        score.weeks_ahead,
    ):
        assert 1 <= axis_value <= 5
    assert 8 <= score.total <= 40
    assert 1 <= score.overall_stars <= 5


def test_build_strategist_views_handles_no_match_gracefully():
    headlines = [_headline("特に材料のない日常ニュース")]
    ranking = news_ranking.build_news_ranking(headlines, [], {}, [])
    views = strategist_engine.build_strategist_views(ranking, {"themes": [], "sectors": {}}, {})

    assert len(views) == 1
    view = views[0]
    assert view.theme == "特定テーマなし"
    assert view.related_sector == "特定業種なし"
    assert view.beneficiary_names == []
    assert view.negative_names == []


def test_build_strategist_views_empty_when_no_news():
    assert strategist_engine.build_strategist_views([], CONFIG, TICKER_LOOKUP) == []


def test_news_ranking_populates_beneficiary_and_negative_tickers_from_causal_rules():
    headlines = [_headline("原油安が進行、市場心理が改善")]
    ranking = news_ranking.build_news_ranking(
        headlines,
        [],
        SECTORS,
        [],
        causal_rules=CAUSAL_RULES,
        durable_themes=["半導体"],
    )
    assert ranking[0].beneficiary_tickers == ["7203.T"]
    assert ranking[0].negative_tickers == []


def test_news_ranking_backward_compatible_without_causal_rules():
    headlines = [_headline("半導体関連が上方修正")]
    ranking = news_ranking.build_news_ranking(headlines, ["半導体"], SECTORS, [])
    assert ranking[0].beneficiary_tickers == []
    assert ranking[0].negative_tickers == []
