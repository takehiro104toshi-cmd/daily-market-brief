"""v3.5 Market Narrative & Section Pruning Upgrade をネットワークなしで検証する。

対象: ①本日の相場総括（Market Narrative）の生成と表示 ②market/news/regimeからの機械生成
③「なぜ動いたか」「今後見るべき点」 ④営業系の営業メモ統合 ⑤シナリオ系の整理
⑥Future Intelligence初期短縮（既存） ⑨目次（メニュー）の重要度順 ＋ 売買助言なし。
"""
from datetime import datetime, timezone

from src.analysis import analysis_confidence, anomaly, cross_market, market_narrative, market_regime
from src.analysis.models import (
    FutureIntelligenceBundle,
    ThemeDiagnosisEntry,
    ThemeMomentumEntry,
)
from src.report.html_builder import _market_narrative_html, build_html_report
from src.utils import SourceRegistry
from tests.factories import full_bundle, full_market, make_quote

NOW = datetime(2026, 7, 7, 9, 0)


def _rate_up_market():
    m = full_market()
    # SOX を追加（半導体株安）、米10年は full_market で change=+0.02（上昇）
    m["indices"].append(make_quote("SOX指数（フィラデルフィア半導体指数）", 4500.0, -110.0, -2.4, symbol="^SOX"))
    return m


def _narrated_bundle(market):
    b = full_bundle()
    b.news_ranking[0].headline.title = "AI半導体関連が世界的に話題"
    b.future_intelligence = FutureIntelligenceBundle(
        theme_momentum=[ThemeMomentumEntry(label="AI半導体", momentum_score=85, momentum_label="加速", reason="x")],
        theme_diagnosis=[ThemeDiagnosisEntry(label="AI半導体", momentum_score=85, momentum_label="加速",
                                             phase="急成長期", continuity="高い", risks=["過熱による調整"], confidence_score=70)],
    )
    regime = market_regime.build_market_regime(market)
    cm = cross_market.build_cross_market_chains(market, {})
    conf = analysis_confidence.build_analysis_confidence(SourceRegistry(), None, market, b.news_ranking, b)
    b.market_narrative = market_narrative.build_market_narrative(
        market, b.news_ranking, b.executive_summary, b.future_intelligence,
        regime, cm, conf, b.weekly_events, anomaly.detect_anomalies(market),
    )
    return b


# ---------- ①② Market Narrative の生成（ルールベース） ----------

def test_narrative_headline_reflects_market_and_regime():
    market = _rate_up_market()
    nar = _narrated_bundle(market).market_narrative
    # 米金利上昇＋半導体株安を背景にした総括見出し
    assert "米金利上昇" in nar.headline
    assert "半導体株安" in nar.headline
    assert "リスク" in nar.headline  # リスクオン/オフのトーン


def test_narrative_uses_market_news_regime_fields():
    market = _rate_up_market()
    nar = _narrated_bundle(market).market_narrative
    assert nar.market_move            # 何が起きたか（主要指標の変化）
    assert nar.main_causes            # なぜ動いたか
    assert nar.watch_points           # これから見るべき
    assert nar.near_term_view and nar.medium_term_view   # 今後の見立て（条件分岐）
    assert nar.implications           # 投資判断への示唆
    assert "Market Regime" in nar.source_items  # regimeを根拠に使う


def test_narrative_explains_theme_vs_price_divergence():
    market = _rate_up_market()  # AIニュース多いがSOX下落
    nar = _narrated_bundle(market).market_narrative
    joined = " ".join(nar.main_causes)
    assert "SOX" in joined or "半導体" in joined


def test_narrative_no_buy_sell_advice():
    market = _rate_up_market()
    nar = _narrated_bundle(market).market_narrative
    blob = " ".join(
        [nar.headline, nar.near_term_view, nar.medium_term_view]
        + nar.main_causes + nar.watch_points + nar.implications + nar.risk_factors
    )
    assert "買うべき" not in blob
    assert "売るべき" not in blob


def test_narrative_empty_market_is_safe():
    nar = market_narrative.build_market_narrative({}, [], [], FutureIntelligenceBundle(), None, [], None, [], [])
    assert nar.headline  # 何らかの総括見出しは返る
    assert isinstance(nar.market_move, list)


# ---------- ③ HTML表示 ----------

def test_narrative_card_rendered_at_top():
    market = _rate_up_market()
    b = _narrated_bundle(market)
    report = build_html_report(report_date=NOW, market=market, sources=SourceRegistry(), analysis=b)
    assert 'id="market-narrative"' in report
    assert "本日の相場総括" in report
    assert "なぜ動いたか" in report
    assert "これから何を見るべきか" in report
    # Today's Decision / Dashboard より上に配置
    assert report.index('id="market-narrative"') < report.index('id="todays-decision"')
    assert report.index('id="market-narrative"') < report.index('id="dashboard-top"')


def test_narrative_absent_when_not_provided_keeps_working():
    # market_narrative未指定（None）でも従来通りHTML生成できる
    report = build_html_report(report_date=NOW, market=full_market(), sources=SourceRegistry(), analysis=full_bundle())
    assert 'id="market-narrative"' not in report
    assert report.strip().endswith("</html>")
    assert report.count("<div") == report.count("</div>")


def test_narrative_html_none_returns_empty():
    assert _market_narrative_html(None) == ""


# ---------- ④ 営業メモ統合 / ⑤ シナリオ整理 / ⑨ メニュー ----------

def test_sales_sections_grouped_under_sales_memo():
    report = build_html_report(report_date=NOW, market=full_market(), sources=SourceRegistry(), analysis=_narrated_bundle(_rate_up_market()))
    assert 'id="sales-memo"' in report
    assert "営業メモ" in report
    # 営業メモ見出しが個別の営業カード群より前に出る
    assert report.index('id="sales-memo"') < report.index('id="call-priorities"')


def test_instrument_scenarios_folded_into_details():
    report = build_html_report(report_date=NOW, market=full_market(), sources=SourceRegistry(), analysis=_narrated_bundle(_rate_up_market()))
    assert "個別シナリオを表示" in report  # detailsに折りたたみ
    # 3大シナリオはメインのまま
    assert 'id="scenarios-v2"' in report


def test_menu_leads_with_market_narrative():
    report = build_html_report(report_date=NOW, market=full_market(), sources=SourceRegistry(), analysis=_narrated_bundle(_rate_up_market()))
    assert '<a class="menu-btn" href="#market-narrative"' in report
    # メニュー内で 相場総括 が Today's Decision より前
    assert report.index('href="#market-narrative"') < report.index('href="#todays-decision"')
