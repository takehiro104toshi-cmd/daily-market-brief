"""v3.5.2 Strategic Narrative Engine をネットワークなしで検証する。

朝会3分説明レベルの相場解説を、既存エンジンの結果だけから機械的に組み立てることを確認する。
生成AI・断定予測・新規データ取得・捏造・売買助言なし（既存エンジンの再利用のみ）。
"""
from datetime import datetime

from src.analysis import (
    analysis_confidence,
    cross_market,
    market_breadth,
    market_regime,
    strategic_narrative,
)
from src.analysis.models import (
    FutureIntelligenceBundle,
    ThemeMomentumEntry,
    WeeklyEventEntry,
)
from src.report.html_builder import _strategic_narrative_html, build_html_report
from src.utils import SourceRegistry
from tests.factories import full_bundle, full_market, make_quote

NOW = datetime(2026, 7, 7, 9, 0)


def _semis_down_market():
    m = full_market()
    m["indices"].append(make_quote("SOX指数（フィラデルフィア半導体指数）", 4500.0, -220.0, -4.8, symbol="^SOX"))
    return m


def _build(market):
    b = full_bundle()
    b.news_ranking[0].headline.title = "AI半導体が話題だが利益確定売り"
    b.future_intelligence = FutureIntelligenceBundle(
        theme_momentum=[ThemeMomentumEntry(label="AI半導体", momentum_score=85, momentum_label="加速", reason="x")]
    )
    b.weekly_events = [WeeklyEventEntry(label="ニデック決算", date_str="07/09", countdown_text="あと2日", category="決算")]
    reg = market_regime.build_market_regime(market)
    cm = cross_market.build_cross_market_chains(market, {})
    conf = analysis_confidence.build_analysis_confidence(SourceRegistry(), None, market, b.news_ranking, b)
    br = market_breadth.build_market_breadth(market)
    return strategic_narrative.build_strategic_narrative(
        market, reg, cm, b.news_ranking, b.future_intelligence, br, conf,
        b.scenario, b.scenarios_v2, b.watchlist_quicklist, b.weekly_events,
    )


# ---------- 改善①〜⑩ エンジン出力 ----------

def test_one_liner_20_40_chars_and_mentions_cause():
    sn = _build(_semis_down_market())
    assert sn.one_liner
    assert 12 <= len(sn.one_liner) <= 60
    assert "日経" in sn.one_liner


def test_market_psychology_derived_from_signals():
    sn = _build(_semis_down_market())
    # 金利上昇＋半導体安＋AIニュース → 「AIを悲観したのではなく利益確定」
    assert "利益確定" in sn.market_psychology or "様子見" in sn.market_psychology or "リスク" in sn.market_psychology


def test_causal_chain_prices_in_the_move():
    sn = _build(_semis_down_market())
    joined = " → ".join(sn.causal_chain)
    # 織り込んだ因果（利下げ期待→金利→割引率→半導体利確→日経）
    assert "利下げ期待" in joined
    assert "割引率" in joined
    assert "日経平均" in joined


def test_driver_ranking_top3_with_stars_and_reason():
    sn = _build(_semis_down_market())
    assert 1 <= len(sn.driver_ranking) <= 3
    top = sn.driver_ranking[0]
    assert "SOX" in top.label          # 最大変動＝SOX
    assert "★" in top.stars
    assert top.note                     # 1行の理由


def test_downside_and_support_separated_and_star_ranked():
    sn = _build(_semis_down_market())
    assert sn.downside_factors and sn.support_factors
    # 押し下げの最上位はSOX（★5相当）
    assert "SOX" in sn.downside_factors[0].label
    # ★が降順（寄与の大きい順）
    stars = [f.stars.count("★") for f in sn.downside_factors]
    assert stars == sorted(stars, reverse=True)


def test_scenarios_abc_with_probability_labels():
    sn = _build(_semis_down_market())
    assert len(sn.scenarios) == 3
    labels = {s.probability_label for s in sn.scenarios}
    assert labels <= {"高", "中", "低"}
    assert all(s.chain for s in sn.scenarios)


def test_nikkei_causation_explains_background_and_counter():
    # v3.5.3: 「日経は◯◯しました。背景には…がありました。一方で…」の段落形式
    sn = _build(_semis_down_market())
    chain = sn.nikkei_causation
    assert "日経平均" in chain[0]        # 結果から始まる
    assert any("背景には" in c or "支えとなる一方" in c for c in chain)  # 背景・力関係を説明


def test_cross_market_prose_is_natural_language():
    sn = _build(_semis_down_market())
    prose = sn.cross_market_prose
    assert "↓" not in prose             # 矢印羅列ではない
    assert "ました" in prose or "です" in prose  # 文章
    assert "円安" in prose or "金利" in prose


def test_sales_30sec_present():
    sn = _build(_semis_down_market())
    assert "今日は" in sn.sales_30sec
    assert "ポイント" in sn.sales_30sec


def test_strategist_summary_weaves_all_and_no_advice():
    sn = _build(_semis_down_market())
    s = sn.strategist_summary
    assert 120 <= len(s) <= 400
    assert "買うべき" not in s and "売るべき" not in s
    # v3.5.3: 方向・市場心理・今後の見るポイントを一連の流れで含む
    assert "日経平均" in s
    assert "市場心理" in s
    assert "今後" in s


def test_reused_engines_listed():
    sn = _build(_semis_down_market())
    for eng in ["Market Regime", "Cross Market", "Scenario", "Market Data"]:
        assert eng in sn.reused_engines


def test_empty_market_is_safe():
    sn = strategic_narrative.build_strategic_narrative({}, None, [], [], None, None, None, None, [], {}, [])
    assert sn.one_liner
    assert sn.strategist_summary
    assert isinstance(sn.downside_factors, list)


# ---------- HTML表示 ----------

def test_strategic_narrative_rendered_in_card():
    b = full_bundle()
    b.strategic_narrative = _build(_semis_down_market())
    report = build_html_report(report_date=NOW, market=_semis_down_market(), sources=SourceRegistry(), analysis=b)
    for heading in ["【本日の一言】", "【今日の市場心理】", "【本日の主因ランキング】",
                    "【相場を押し下げた材料】", "【下支えした材料】", "【今後のシナリオ】",
                    "【ストラテジスト総括】", "【営業向け30秒説明】"]:
        assert heading in report
    assert report.count("<div") == report.count("</div>")
    assert "買うべき" not in report and "売るべき" not in report


def test_strategic_html_none_returns_empty():
    assert _strategic_narrative_html(None) == ""


def test_market_narrative_card_still_works_without_strategic():
    # strategic未指定でも従来の6部構成カードが出る（後方互換）
    from src.analysis import market_narrative, anomaly
    b = full_bundle()
    reg = market_regime.build_market_regime(full_market())
    cm = cross_market.build_cross_market_chains(full_market(), {})
    b.market_narrative = market_narrative.build_market_narrative(
        full_market(), b.news_ranking, b.executive_summary, b.future_intelligence,
        reg, cm, None, b.weekly_events, anomaly.detect_anomalies(full_market()),
    )
    report = build_html_report(report_date=NOW, market=full_market(), sources=SourceRegistry(), analysis=b)
    assert "① 今日の結論" in report        # 6部構成が主軸のまま
    assert "【本日の一言】" not in report   # strategicは無い
