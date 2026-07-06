"""v2.8 Smart Intelligence Evolution をネットワークなしで検証する。

対象: Source Trust（⑥）/ Why Today（⑦）/ 低重要度折りたたみ（⑧⑨）/
Scenario v2（③）/ Investment Journal（①）/ Theme Confidence Learning（②）/
英語翻訳スキャフォールド（④）/ 経済カレンダー結合（⑤）。
"""
from datetime import datetime, timedelta, timezone

import pytz

from src.analysis import investment_journal, theme_learning, why_today
from src.analysis.models import (
    NewsRankingItem,
    ScenarioForecast,
    ThemeDiagnosisEntry,
)
from src.analysis.scenario_v2 import build_scenarios_v2
from src.analysis.source_trust import trust_for_source
from src.analysis.translation import is_english, translate_headlines
from src.collectors.economic_calendar import merge_events
from src.collectors.news import Headline
from src.collectors.themes import SectorMatch
from src.report.html_builder import build_html_report
from src.utils import SourceRegistry
from tests.factories import full_bundle, full_market

NOW = datetime(2026, 7, 6, 7, 0, tzinfo=timezone.utc)


# ---------- ⑥ Source Trust ----------

def test_official_sources_are_five_stars():
    for name in ["FRB", "日銀", "財務省", "企業IR", "TDnet", "EDINET"]:
        assert trust_for_source(name).score == 5, name
        assert trust_for_source(name).stars == "★★★★★"


def test_top_media_are_four_stars():
    for name in ["Reuters", "Bloomberg", "日経", "WSJ", "CNBC"]:
        t = trust_for_source(name)
        assert t.score == 4, name
        assert t.stars == "★★★★☆"


def test_major_and_unknown_sources():
    assert trust_for_source("株探").score == 3
    assert trust_for_source("どこかのブログ").score == 2       # 一般メディア（既定）
    assert trust_for_source("").score == 1                      # 出典不明＝参考情報


def test_source_trust_shown_in_html():
    report = build_html_report(
        report_date=datetime(2026, 7, 6), market=full_market(),
        sources=SourceRegistry(), analysis=full_bundle(),
    )
    assert "Source Trust" in report


# ---------- ⑦ Why Today ----------

def test_why_today_generated_and_short():
    bundle = full_bundle()
    result = why_today.build_why_today(bundle, None, bundle.weekly_events, NOW)
    assert "news-ranking" in result or "future-intelligence" in result
    for line in result.values():
        assert 0 < len(line) <= why_today.MAX_CHARS


def test_why_today_rendered_in_html():
    bundle = full_bundle()
    wt = {"news-ranking": "24時間以内の新しい重要ニュースが複数あります。"}
    report = build_html_report(
        report_date=datetime(2026, 7, 6), market=full_market(),
        sources=SourceRegistry(), analysis=bundle, why_today=wt,
    )
    assert "why-today" in report
    assert "Why Today" in report


# ---------- ⑧⑨ 低重要度折りたたみ ----------

def _news_item(rank, stars, title, published=""):
    return NewsRankingItem(
        rank=rank, stars=stars,
        headline=Headline(title=title, link=f"https://example.com/{rank}", source="Reuters", published=published),
        is_top_pick=(rank == 1), reason="理由", affected_market="日本株", affected_sector="半導体", sales_talk="トーク",
    )


def test_high_importance_shown_low_folded():
    from src.report.html_builder import _news_ranking_html

    fresh = (NOW - timedelta(hours=2)).strftime("%a, %d %b %Y %H:%M:%S +0000")
    items = [
        _news_item(1, "★★★★★", "重要ニュース"),
        _news_item(2, "★★★★☆", "高重要度ニュース"),
        _news_item(3, "★★☆☆☆", "低重要度ニュース1"),
        _news_item(4, "★★☆☆☆", "低重要度ニュース2"),
    ]
    html = _news_ranking_html(items, now=NOW)
    # 高重要度（★★★★☆以上）は初期表示、低重要度は折りたたみに入る
    fold_idx = html.index("低重要度・古い記事を表示")
    assert html.index("高重要度ニュース") < fold_idx
    # 折りたたみ内に低重要度記事が残っている（削除しない）
    assert "低重要度ニュース1" in html
    assert "低重要度ニュース2" in html


def test_fresh_high_importance_shown_open():
    from src.report.html_builder import _news_ranking_html

    fresh = (NOW - timedelta(hours=2)).strftime("%a, %d %b %Y %H:%M:%S +0000")
    items = [_news_item(1, "★★★★★", "A"), _news_item(2, "★★★☆☆", "B24h", published=fresh)]
    html = _news_ranking_html(items, now=NOW)
    # 24時間以内かつ★★★☆☆以上は初期表示（折りたたみが発生しない）
    assert "低重要度・古い記事を表示" not in html


# ---------- ③ Scenario v2 ----------

def _scenario(bull, neutral, bear):
    return ScenarioForecast(
        bull, neutral, bear, "reason",
        bull_reason="強気条件", neutral_reason="中立条件", bear_reason="弱気条件",
        bull_indicator="A", neutral_indicator="B", bear_indicator="C",
    )


def test_scenarios_v2_max_three_ranked_by_probability():
    sectors = [
        SectorMatch(label="半導体", tailwind=[1, 2, 3], headwind=[], neutral=[], related_tickers=[]),
        SectorMatch(label="銀行", tailwind=[], headwind=[1, 2], neutral=[], related_tickers=[]),
    ]
    scenarios = build_scenarios_v2(_scenario(55, 30, 15), sectors, ["トヨタ自動車"], ["chainA", "chainB"])
    assert len(scenarios) == 3
    probs = [s.probability for s in scenarios]
    assert probs == sorted(probs, reverse=True)   # 期待値（確率）の高い順
    assert scenarios[0].rank == 1
    assert scenarios[0].probability == 55
    assert "半導体" in scenarios[0].beneficiary_sectors


def test_scenarios_v2_html_has_top3_and_detail():
    bundle = full_bundle()
    bundle.scenarios_v2 = build_scenarios_v2(_scenario(50, 30, 20), [], [], [])
    report = build_html_report(
        report_date=datetime(2026, 7, 6), market=full_market(),
        sources=SourceRegistry(), analysis=bundle,
    )
    assert "今日の3大シナリオ" in report
    assert "①" in report and "確率" in report


# ---------- ① Investment Journal ----------

def test_journal_record_and_learning_history(tmp_path):
    bundle = full_bundle()
    snapshot = investment_journal.build_snapshot("2026-01-01", bundle, full_market())
    assert snapshot["scenario"]["dominant"] == "bull"
    assert "日経平均" in snapshot["market_ref"]
    investment_journal.record_daily_journal(str(tmp_path), "2026-01-01", snapshot)
    # 同一日付は上書き（重複しない）
    investment_journal.record_daily_journal(str(tmp_path), "2026-01-01", snapshot)

    history = investment_journal.build_learning_history(str(tmp_path), NOW)
    assert len(history) == 1
    assert history[0].date == "2026-01-01"
    assert history[0].evaluated is False   # まだ市場比較していない → 評価待ち


def test_journal_evaluation_after_horizon(tmp_path):
    bundle = full_bundle()
    # 記録時の日経平均を 38000 とする（full_market）
    snapshot = investment_journal.build_snapshot("2026-01-01", bundle, full_market())
    investment_journal.record_daily_journal(str(tmp_path), "2026-01-01", snapshot)

    # 40日後・日経平均が +8% した市場で答え合わせ → bull想定は的中
    later_market = full_market()
    later_market["indices"][0].price = 38000 * 1.08
    later = datetime(2026, 2, 10, tzinfo=timezone.utc)
    investment_journal.evaluate_journal(str(tmp_path), later_market, later)

    history = investment_journal.build_learning_history(str(tmp_path), later)
    assert history[0].evaluated is True
    assert history[0].evaluation_status == "的中"
    assert history[0].evaluation_horizon == 30


# ---------- ② Theme Confidence Learning ----------

def _diag(label, momentum, confidence):
    return ThemeDiagnosisEntry(
        label=label, momentum_score=momentum, momentum_label="加速",
        phase="成長初期", continuity="高い", confidence_score=confidence,
    )


def test_theme_learning_record_evaluate_winrate(tmp_path):
    diags = [_diag("半導体", 70, 80), _diag("銀行", 40, 50)]
    theme_learning.record_theme_predictions(str(tmp_path), "2026-01-01", diags, full_market())

    later_market = full_market()
    later_market["indices"][0].price = 38000 * 1.05   # +5%（上昇）
    later = datetime(2026, 2, 10, tzinfo=timezone.utc)
    theme_learning.evaluate_theme_learning(str(tmp_path), later_market, later)

    stats = {s.label: s for s in theme_learning.build_theme_learning_stats(str(tmp_path))}
    # 半導体（up予想）は地合い上昇で的中、銀行（flat予想）は+5%で外れ
    assert stats["半導体"].win_rate == 1.0
    assert stats["銀行"].win_rate == 0.0


def test_confidence_adjustment_bounds():
    assert theme_learning.confidence_adjustment(None) == 0
    assert theme_learning.confidence_adjustment(0.5) == 0
    assert theme_learning.confidence_adjustment(1.0) == theme_learning.ADJUST_MAX   # 上限
    assert theme_learning.confidence_adjustment(0.0) == theme_learning.ADJUST_MIN   # 下限


def test_confidence_adjustment_applied_in_fi():
    from src.analysis.future_intelligence import build_future_intelligence

    config = {
        "macro_themes": [{"label": "半導体", "keywords": ["半導体"]}],
        "durable_themes": ["半導体"],
        "causal_rules": [],
    }
    headlines = [Headline(title="半導体の投資拡大", link="x", source="Reuters")]
    base = build_future_intelligence(headlines, config, {}, {})
    boosted = build_future_intelligence(headlines, config, {}, {}, theme_win_rates={"半導体": 1.0})
    base_conf = {d.label: d.confidence_score for d in base.theme_diagnosis}
    boost_conf = {d.label: d.confidence_score for d in boosted.theme_diagnosis}
    assert boost_conf["半導体"] >= base_conf["半導体"]   # 勝率100%で上振れ（または据え置き）


# ---------- ④ 翻訳スキャフォールド ----------

def test_is_english_detection():
    assert is_english("Fed holds rates steady amid inflation concerns")
    assert not is_english("日銀が金融政策を据え置き")
    assert not is_english("AI")   # 短すぎる


def test_translate_is_noop_without_api_key():
    # ANTHROPIC_API_KEYが無い環境では翻訳は行われず、原文のまま
    headlines = [Headline(title="Fed holds rates steady", link="x", source="Reuters")]
    count = translate_headlines(headlines)
    assert count == 0
    assert headlines[0].title_ja == ""
    assert headlines[0].display_title() == "Fed holds rates steady"


def test_display_title_prefers_japanese():
    h = Headline(title="Fed holds rates steady", link="x", source="Reuters", title_ja="FRBが金利を据え置き")
    assert h.display_title() == "FRBが金利を据え置き"


# ---------- ⑤ 経済カレンダー結合 ----------

def test_merge_events_dedupes():
    config_events = [{"date": "2026-07-10", "label": "FOMC"}]
    auto_events = [{"date": "2026-07-10", "label": "FOMC"}, {"date": "2026-07-11", "label": "米CPI"}]
    merged = merge_events(config_events, auto_events)
    labels = [e["label"] for e in merged]
    assert labels.count("FOMC") == 1     # 重複除去
    assert "米CPI" in labels


def test_merge_events_empty_safe():
    assert merge_events([], []) == []
    assert merge_events(None, None) == []
