"""v3.1 UX / Decision Quality Upgrade をネットワークなしで検証する。

対象:
 改善1 Today's Decision カード（最上部・Dashboardより上・市場判断/テーマ/銘柄/警戒/イベント/Confidence/鮮度）
 改善2 翻訳バグ修正（英文のまま残る場合の警告表示・日本語訳があれば日本語表示）
 改善3 異常値検知（日経±5%・ドル円±2%等）を Data Quality と Today's Decision に表示
 改善5 Watchlist 由来の「今日見るべき銘柄TOP5」
 改善6 営業系セクションの初期折りたたみ（card-collapsed）
 改善7 引用（情報源）の要約表示＋全URL折りたたみ
 改善8 Data Quality に翻訳API状態・経済カレンダー状態・異常値チェック・取得失敗ソースを追加
"""
from datetime import datetime, timedelta

import pytz

from src.analysis import data_freshness as df
from src.analysis import news_ranking
from src.analysis.anomaly import anomaly_status_label, detect_anomalies
from src.analysis.models import (
    FutureIntelligenceBundle,
    ThemeDiagnosisEntry,
    ThemeMomentumEntry,
    WeeklyEventEntry,
)
from src.collectors.news import Headline
from src.report.html_builder import build_html_report
from src.utils import SourceRegistry
from tests.factories import full_bundle, full_market

JST = pytz.timezone("Asia/Tokyo")
NOW = JST.localize(datetime(2026, 7, 7, 7, 0))


def _rfc(dt):
    return dt.strftime("%a, %d %b %Y %H:%M:%S %z")


def _stats():
    raw = [Headline(title="半導体 決算A", link="https://e/a", source="テストRSS", published=_rfc(NOW - timedelta(hours=2)))]
    items = news_ranking.build_news_ranking(raw, ["半導体"], {}, [])
    return df.build_data_freshness_stats(
        generated_at=NOW, raw_headlines=raw, deduped_headlines=raw, ranking_items=items,
        attempted_source_names=["死んでいるRSS"],
    )


def _fi_bundle():
    return FutureIntelligenceBundle(
        theme_momentum=[
            ThemeMomentumEntry(label="AI半導体", momentum_score=88, momentum_label="加速", reason="関連ニュース多数。"),
            ThemeMomentumEntry(label="電力・エネルギー", momentum_score=70, momentum_label="加速", reason="関連ニュース。"),
            ThemeMomentumEntry(label="防衛", momentum_score=55, momentum_label="横ばい", reason="関連ニュース。"),
        ],
        theme_diagnosis=[
            ThemeDiagnosisEntry(
                label="AI半導体", momentum_score=88, momentum_label="加速", phase="急成長期", continuity="高い",
                risks=["過熱による調整リスク"], confidence_score=72,
            ),
        ],
    )


def _report(analysis=None, market=None, freshness=None, sources=None):
    return build_html_report(
        report_date=datetime(2026, 7, 7),
        market=market if market is not None else full_market(),
        sources=sources if sources is not None else SourceRegistry(),
        analysis=analysis if analysis is not None else full_bundle(),
        freshness=freshness,
    )


# ---------- 改善1 Today's Decision ----------

def test_todays_decision_card_present_and_above_dashboard():
    report = _report()
    assert 'id="todays-decision"' in report
    # カード見出し（アポストロフィはHTMLエスケープされる）
    assert "Today&#x27;s Decision" in report or "Today's Decision" in report
    assert "今日の投資判断・3分サマリー" in report
    # Dashboard より上に配置される
    assert report.index('id="todays-decision"') < report.index('id="dashboard-top"')
    # 主要項目が並ぶ
    for label in ["今日の市場判断", "重要テーマTOP3", "今日見るべき銘柄TOP5", "警戒ポイントTOP3", "今週の重要イベント", "AI Confidence", "データ鮮度"]:
        assert label in report


def test_todays_decision_market_judgment_risk_on():
    # full_bundle は強気55%・弱気15% → リスクオン傾向
    report = _report()
    assert "リスクオン傾向" in report


def test_todays_decision_shows_watchlist_top5_stocks():
    report = _report()
    decision = report[report.index('id="todays-decision"'):report.index('id="dashboard-top"')]
    # ウォッチリスト由来の銘柄が「今日見るべき銘柄TOP5」に出る
    assert "トヨタ自動車" in decision
    assert "今日見るべき銘柄TOP5" in decision


def test_todays_decision_shows_themes_and_events_when_populated():
    bundle = full_bundle()
    bundle.future_intelligence = _fi_bundle()
    bundle.weekly_events = [WeeklyEventEntry(label="米CPI発表", date_str="07/10", countdown_text="あと3日")]
    report = _report(analysis=bundle)
    decision = report[report.index('id="todays-decision"'):report.index('id="dashboard-top"')]
    assert "AI半導体" in decision            # 重要テーマTOP3
    assert "米CPI発表" in decision            # 今週の重要イベント
    assert "72%" in decision                  # AI Confidence
    assert "過熱による調整リスク" in decision  # 警戒ポイント（テーマ診断Risk）


# ---------- 改善2 翻訳 ----------

def test_translation_unset_warning_shown_for_untranslated_english():
    bundle = full_bundle()
    bundle.news_ranking[0].headline.title = "Fed signals possible rate cut amid inflation"
    bundle.news_ranking[0].headline.title_ja = ""  # 未翻訳
    report = _report(analysis=bundle, freshness=_stats())
    assert "翻訳API未設定のため英文のまま表示" in report


def test_translation_japanese_shown_when_translated():
    bundle = full_bundle()
    bundle.news_ranking[0].headline.title = "Nvidia rises on strong AI GPU demand"
    bundle.news_ranking[0].headline.title_ja = "エヌビディア、AI向けGPU需要で上昇"
    report = _report(analysis=bundle, freshness=_stats())
    assert "エヌビディア、AI向けGPU需要で上昇" in report  # 日本語訳を優先表示
    assert "翻訳済み" in report
    # 全て翻訳済みなら未設定警告は出さない
    assert "翻訳API未設定のため英文のまま表示" not in report


# ---------- 改善3 異常値検知 ----------

def test_anomaly_detection_flags_large_move():
    market = full_market()
    market["indices"][0].change_pct = 6.5  # 日経 +6.5% → ±5%超で異常
    anomalies = detect_anomalies(market)
    assert len(anomalies) == 1
    assert anomaly_status_label(anomalies) == "要確認"
    report = _report(market=market, freshness=_stats())
    assert "要確認" in report
    assert "大きく変動" in report


def test_anomaly_none_shows_normal_label():
    anomalies = detect_anomalies(full_market())
    assert anomalies == []
    assert anomaly_status_label(anomalies) == "異常値なし"
    report = _report(freshness=_stats())
    assert "異常値なし" in report


# ---------- 改善6 営業セクション初期折りたたみ ----------

def test_sales_sections_collapsed_by_default():
    report = _report()
    for anchor in ["sales-prep", "sales-talk", "sales-comments", "okasan-sales-comments"]:
        section_start = report.index(f'id="{anchor}"')
        div_start = report.rindex("<div class=", 0, section_start)
        assert "card-collapsed" in report[div_start:section_start]
        assert "sales-section" in report[div_start:section_start]


# ---------- 改善7 引用の圧縮 ----------

def test_sources_compressed_with_summary_and_fold():
    sources = SourceRegistry()
    sources.add("日本銀行", "https://www.boj.or.jp/x", "公式")
    sources.add("Reuters", "https://www.reuters.com/y", "海外")
    report = _report(sources=sources)
    assert "情報源数" in report
    assert "公式ソース数" in report
    assert "海外ソース数" in report
    assert "主要ソースTOP10" in report
    assert "参照URLの全一覧を表示" in report
    # 全URLは保持（折りたたみ内に残る）
    assert "https://www.boj.or.jp/x" in report


# ---------- 改善8 Data Quality 拡充 ----------

def test_data_quality_has_translation_and_calendar_status():
    report = _report(freshness=_stats())
    assert "翻訳API状態" in report
    assert "経済カレンダー" in report
    assert "異常値チェック" in report
    assert "取得失敗ソース" in report
    assert "市場データ取得時刻" in report
