"""v3.2 Analysis Accuracy Upgrade をネットワークなしで検証する（分析エンジンのみ）。

対象:
 改善1 Market Regime Engine（Risk On/Off/Neutral + Risk Score 0〜100）
 改善2 Cross Market Analysis（多段の波及チェーン・条件成立時のみ）
 改善3 News Impact Score（0〜100）
 改善4 Source Tier（Tier1〜4）
 改善5 Duplicate Intelligence（Major Story = 3社以上）
 改善6 Macro Intelligence 構造（consensus/previous/forecast/actual/surprise）
 改善7 Future Probability（if条件型・triggered）
 改善8 Theme Rotation（テーマ間の資金移動）
 改善9 Market Breadth（Breadth Score）
 改善10 Analysis Confidence（分析根拠の充実度 0〜100）
"""
from datetime import datetime, timezone

from src.analysis import (
    analysis_confidence,
    cross_market,
    future_probability,
    market_breadth,
    market_regime,
    news_impact,
    theme_rotation,
)
from src.analysis.models import (
    NewsRankingItem,
    ThemeMomentumEntry,
    WeeklyEventEntry,
)
from src.analysis.source_trust import source_tier, tier_label_for_score
from src.collectors.news import Headline
from src.utils import SourceRegistry
from tests.factories import full_bundle, full_market, make_quote

NOW = datetime(2026, 7, 7, tzinfo=timezone.utc)


def _risk_on_market():
    return {
        "indices": [
            make_quote("S&P500", 5200.0, 60.0, 1.5),
            make_quote("ナスダック総合", 17000.0, 250.0, 2.0),
            make_quote("SOX指数（フィラデルフィア半導体指数）", 5000.0, 120.0, 2.5),
            make_quote("NYダウ", 39500.0, 300.0, 0.8),
            make_quote("VIX指数（恐怖指数）", 12.5, -1.0, -7.0),
            make_quote("ドル指数（DXY）", 104.0, -0.3, -0.3),
        ],
        "forex": [make_quote("米ドル/円", 157.0, 0.8, 0.5)],
        "rates": [make_quote("米10年国債利回り", 4.2, -0.05, -1.2)],
        "commodities": [
            make_quote("WTI原油先物", 80.0, 1.0, 1.3),
            make_quote("金先物（ゴールド）", 2300.0, -5.0, -0.2),
            make_quote("ビットコイン", 65000.0, 1500.0, 2.4),
        ],
    }


def _risk_off_market():
    return {
        "indices": [
            make_quote("S&P500", 5000.0, -120.0, -2.4),
            make_quote("ナスダック総合", 16000.0, -400.0, -2.5),
            make_quote("SOX指数（フィラデルフィア半導体指数）", 4500.0, -200.0, -4.3),
            make_quote("NYダウ", 38000.0, -500.0, -1.3),
            make_quote("VIX指数（恐怖指数）", 32.0, 6.0, 23.0),
            make_quote("ドル指数（DXY）", 106.0, 0.9, 0.9),
        ],
        "forex": [make_quote("米ドル/円", 150.0, -1.5, -1.0)],
        "rates": [make_quote("米10年国債利回り", 4.5, 0.1, 2.3)],
        "commodities": [
            make_quote("WTI原油先物", 70.0, -2.0, -2.8),
            make_quote("金先物（ゴールド）", 2400.0, 40.0, 1.7),
            make_quote("ビットコイン", 60000.0, -3000.0, -4.8),
        ],
    }


# ---------- 改善1 Market Regime ----------

def test_market_regime_risk_on():
    reg = market_regime.build_market_regime(_risk_on_market())
    assert reg.regime == "Risk On"
    assert reg.stance == "Bullish"
    assert reg.risk_score >= 60
    assert reg.evaluated_count >= 5
    assert 0 <= reg.risk_score <= 100


def test_market_regime_risk_off():
    reg = market_regime.build_market_regime(_risk_off_market())
    assert reg.regime == "Risk Off"
    assert reg.stance == "Bearish"
    assert reg.risk_score <= 40


def test_market_regime_no_data_is_safe():
    reg = market_regime.build_market_regime({})
    assert reg.regime == "判定不能"
    assert reg.risk_score == 50
    assert reg.evaluated_count == 0


# ---------- 改善2 Cross Market ----------

def test_cross_market_chain_multistep_on_rate_up():
    market = full_market()  # 米10年 change=0.02（上昇）
    chains = cross_market.build_cross_market_chains(market, {})
    labels = [c.label for c in chains]
    assert "米金利上昇の波及" in labels
    rate_chain = next(c for c in chains if c.label == "米金利上昇の波及")
    # 多段（従来の因果チェーンより長い）であること
    assert len(rate_chain.nodes) >= 6
    assert "電線・重電" in rate_chain.nodes


def test_cross_market_no_data_returns_empty():
    assert cross_market.build_cross_market_chains({}, {}) == []


def test_cross_market_config_rule_applied():
    market = {"indices": [make_quote("SOX指数", 5000.0, 120.0, 2.5)]}
    config = {"cross_market_rules": [
        {"label": "登録SOXルール", "category": "indices", "keyword": "SOX",
         "direction": "up", "threshold": 1.0, "nodes": ["SOX↑", "AI設備投資", "電力"]},
    ]}
    chains = cross_market.build_cross_market_chains(market, config)
    assert any(c.label == "登録SOXルール" for c in chains)


# ---------- 改善3/4/5 News Impact / Tier / Major Story ----------

def test_news_impact_score_range_and_fields():
    bundle = full_bundle()
    news_impact.apply_news_impact_scores(bundle.news_ranking, NOW)
    item = bundle.news_ranking[0]
    assert 0 <= item.impact_score <= 100
    assert item.source_tier in ("Tier1", "Tier2", "Tier3", "Tier4")
    assert isinstance(item.impact_breakdown, dict) and item.impact_breakdown


def test_source_tier_mapping():
    assert tier_label_for_score(5) == "Tier1"
    assert tier_label_for_score(4) == "Tier2"
    assert tier_label_for_score(3) == "Tier3"
    assert tier_label_for_score(2) == "Tier4"
    assert source_tier("FOMC") == "Tier1"
    assert source_tier("Reuters") == "Tier2"
    assert source_tier("Yahoo") == "Tier3"


def test_major_story_flag_three_sources():
    h = Headline(title="米CPI発表", link="x", source="Reuters",
                 duplicate_sources=["Bloomberg", "CNBC"], source_count=3)
    item = NewsRankingItem(rank=1, stars="★★★★☆", headline=h, affected_market="金利", affected_sector="特定業種なし")
    result = news_impact.score_news_item(item, NOW)
    assert result["is_major_story"] is True
    news_impact.apply_news_impact_scores([item], NOW)
    assert item.is_major_story is True
    assert news_impact.count_major_stories([item]) == 1


def test_tier1_scores_higher_than_tier3_all_else_equal():
    h1 = Headline(title="FOMC 政策金利を据え置き", link="a", source="FOMC")
    h3 = Headline(title="FOMC 政策金利を据え置き", link="b", source="Yahoo")
    item1 = NewsRankingItem(rank=1, stars="★★★★☆", headline=h1, affected_market="金利", affected_sector="銀行")
    item3 = NewsRankingItem(rank=1, stars="★★★★☆", headline=h3, affected_market="金利", affected_sector="銀行")
    s1 = news_impact.score_news_item(item1, NOW)["score"]
    s3 = news_impact.score_news_item(item3, NOW)["score"]
    assert s1 > s3  # Tier1（一次情報）は加点が大きい


# ---------- 改善6 Macro Intelligence 構造 ----------

def test_weekly_event_macro_fields_exist_and_default_empty():
    e = WeeklyEventEntry(label="米CPI")
    assert e.consensus == "" and e.previous == "" and e.forecast == "" and e.actual == "" and e.surprise == ""
    e2 = WeeklyEventEntry(label="米CPI", consensus="3.2%", previous="3.4%", forecast="3.2%", actual="3.1%", surprise="下振れ")
    assert e2.actual == "3.1%" and e2.surprise == "下振れ"


# ---------- 改善7 Future Probability ----------

def test_future_probability_conditional_triggered():
    scenarios = future_probability.build_conditional_scenarios(_risk_off_market())
    labels = {s.label for s in scenarios}
    assert "景気後退懸念シナリオ" in labels
    recession = next(s for s in scenarios if s.label == "景気後退懸念シナリオ")
    # VIX>=22 かつ 10年金利低下 → risk_offでは金利は上昇なので後退懸念は不成立
    # （安全資産選好は成立する）
    safe = next(s for s in scenarios if s.label == "安全資産選好シナリオ")
    assert safe.triggered is True
    assert safe.conditions and safe.outcome


def test_future_probability_no_data_not_triggered():
    scenarios = future_probability.build_conditional_scenarios({})
    assert all(s.triggered is False for s in scenarios)


# ---------- 改善8 Theme Rotation ----------

def test_theme_rotation_direction():
    tm = [
        ThemeMomentumEntry(label="AI", momentum_score=90, momentum_label="加速", reason="x"),
        ThemeMomentumEntry(label="半導体", momentum_score=72, momentum_label="加速", reason="x"),
        ThemeMomentumEntry(label="電力", momentum_score=55, momentum_label="横ばい", reason="x"),
    ]
    relations = {"AI": ["半導体", "電力"], "半導体": ["電力"]}
    rot = theme_rotation.build_theme_rotation(tm, relations)
    assert rot
    pairs = {(r.from_theme, r.to_theme): r.signal for r in rot}
    assert pairs.get(("AI", "半導体")) == "資金が移りやすい"
    # from 側の勢いが強い順に並ぶ
    assert rot[0].from_theme == "AI"


def test_theme_rotation_empty_without_momentum():
    assert theme_rotation.build_theme_rotation([], {"AI": ["半導体"]}) == []


# ---------- 改善9 Market Breadth ----------

def test_market_breadth_score_and_proxy_flag():
    br = market_breadth.build_market_breadth(_risk_on_market())
    assert br.advancers >= 1 and br.breadth_score >= 60
    assert br.is_proxy is True
    assert "代用" in br.basis or "全銘柄" in br.basis


def test_market_breadth_no_data_neutral():
    br = market_breadth.build_market_breadth({})
    assert br.breadth_score == 50


# ---------- 改善10 Analysis Confidence ----------

def test_analysis_confidence_higher_with_more_evidence():
    bundle = full_bundle()
    news_impact.apply_news_impact_scores(bundle.news_ranking, NOW)
    sources = SourceRegistry()
    for i in range(10):
        sources.add(f"日銀{i}", f"https://www.boj.or.jp/{i}", "公式")
    rich = analysis_confidence.build_analysis_confidence(sources, None, full_market(), bundle.news_ranking, bundle)
    poor = analysis_confidence.build_analysis_confidence(SourceRegistry(), None, {}, [], bundle)
    assert 0 <= rich.score <= 100
    assert rich.score > poor.score
    assert rich.grade in ("高", "中", "低", "判定不能")
    assert rich.components
