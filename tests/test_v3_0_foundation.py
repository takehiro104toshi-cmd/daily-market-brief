"""v3.0 Foundation Completion をネットワークなしで検証する。

対象: ①翻訳キャッシュ永続化・翻訳UI ②Real-Time Update（2段階ボタン・取得時刻・
realtime設定枠）③経済カレンダー自動収集（JSON/RSS/CSVパース・7日フィルタ・
macro_eventsフォールバック・重複除去・取得失敗の安全性・Source表示）。
"""
from datetime import datetime, timezone

import pytz

from src.analysis import translation
from src.analysis.weekly_events import build_weekly_event_calendar
from src.collectors import economic_calendar as ec
from src.collectors.news import Headline
from src.report.html_builder import build_html_report
from src.utils import SourceRegistry
from tests.factories import full_bundle, full_market

JST = pytz.timezone("Asia/Tokyo")
NOW = JST.localize(datetime(2026, 7, 7, 7, 0))


# ---------- ① Translation cache ----------

def test_translation_cache_save_and_load(tmp_path):
    translation.save_cache(str(tmp_path), {"Fed holds rates": "FRBが金利を据え置き", "empty": ""})
    loaded = translation.load_cache(str(tmp_path))
    assert loaded["Fed holds rates"] == "FRBが金利を据え置き"
    # 空文字（翻訳失敗）はキャッシュに残さない
    assert "empty" not in loaded


def test_translation_corrupt_cache_is_safe(tmp_path):
    (tmp_path / translation.CACHE_FILENAME).write_text("{ this is not json", encoding="utf-8")
    assert translation.load_cache(str(tmp_path)) == {}  # 壊れていても空dict


def test_translation_reuses_cache_without_api_key(tmp_path):
    # APIキーが無くても、キャッシュ済みの見出しは日本語表示される
    translation.save_cache(str(tmp_path), {"Nvidia rises on AI demand": "エヌビディア、AI需要で上昇"})
    h = Headline(title="Nvidia rises on AI demand", link="x", source="Reuters")
    filled = translation.translate_headlines([h], cache_dir=str(tmp_path))
    assert filled == 1
    assert h.title_ja == "エヌビディア、AI需要で上昇"
    assert h.is_translated is True


def test_translation_japanese_not_translated_and_noop_without_key(tmp_path):
    jp = Headline(title="日銀が金融政策を維持", link="x", source="NHK")
    en = Headline(title="Fed signals possible rate cut", link="y", source="Reuters")
    filled = translation.translate_headlines([jp, en], cache_dir=str(tmp_path))
    # 日本語は対象外。英語もキャッシュにもAPIキーにも無いので原文のまま
    assert jp.title_ja == ""
    assert en.title_ja == ""
    assert filled == 0


def test_translation_english_detection():
    assert translation.is_english("Fed signals possible rate cut amid inflation")
    assert not translation.is_english("日銀会合の結果")


def test_translated_badge_and_original_in_html():
    bundle = full_bundle()
    bundle.news_ranking[0].headline.title = "Nvidia rises on strong AI GPU demand"
    bundle.news_ranking[0].headline.title_ja = "エヌビディア、AI向けGPU需要で上昇"
    report = build_html_report(
        report_date=datetime(2026, 7, 7), market=full_market(), sources=SourceRegistry(), analysis=bundle,
    )
    assert "エヌビディア、AI向けGPU需要で上昇" in report   # 日本語訳を優先表示
    assert "翻訳済み" in report                             # 翻訳済みバッジ
    assert "Nvidia rises on strong AI GPU demand" in report  # 原文も保持（詳しく内）


# ---------- ② Real-Time Update Engine ----------

def test_two_refresh_buttons_and_no_secret_leak():
    url = "https://github.com/example/repo/actions/workflows/daily-market-brief.yml"
    report = build_html_report(
        report_date=datetime(2026, 7, 7), market=full_market(), sources=SourceRegistry(),
        analysis=full_bundle(), actions_url=url,
    )
    assert "ページを再読み込み" in report
    assert 'class="regenerate-btn"' in report and url in report
    assert "Run workflow" in report
    # Token/SecretはHTMLに出さない
    assert "ghp_" not in report and "ANTHROPIC_API_KEY" not in report
    assert "github_token" not in report.lower()


def test_realtime_config_absent_does_not_break():
    # realtime設定が無くてもHTML生成は壊れない（realtimeは将来用の設定枠のみ）
    report = build_html_report(
        report_date=datetime(2026, 7, 7), market=full_market(), sources=SourceRegistry(), analysis=full_bundle(),
    )
    assert report.strip().endswith("</html>")
    assert report.count("<div") == report.count("</div>")


# ---------- ③ Economic Indicator Auto Collection ----------

def test_parse_json_events():
    text = '[{"date": "2026-07-10", "label": "US CPI", "time": "21:30", "region": "US"}]'
    events = ec._parse_json_events(text, "テストJSON", "http://x", "2026-07-07T07:00:00+00:00")
    assert len(events) == 1
    assert events[0]["date"] == "2026-07-10"
    assert events[0]["label"] == "US CPI"
    assert events[0]["time"] == "21:30"
    assert events[0]["source"] == "テストJSON"
    assert events[0]["fetched_at"]


def test_parse_rss_events():
    text = (
        "<rss><channel>"
        "<item><title>FOMC statement release</title><pubDate>Wed, 08 Jul 2026 18:00:00 GMT</pubDate></item>"
        "</channel></rss>"
    )
    events = ec._parse_rss_events(text, "FedRSS", "http://x", "2026-07-07T07:00:00+00:00")
    assert len(events) == 1
    assert events[0]["date"] == "2026-07-08"
    assert "FOMC" in events[0]["label"]


def test_parse_csv_events():
    text = "date,label,time,region\n2026-07-09,ISM Manufacturing,23:00,US\n"
    events = ec._parse_csv_events(text, "CSVsrc", "http://x", "2026-07-07T07:00:00+00:00")
    assert len(events) == 1
    assert events[0]["date"] == "2026-07-09"
    assert events[0]["label"] == "ISM Manufacturing"


def test_fetch_economic_calendar_no_sources_returns_empty():
    assert ec.fetch_economic_calendar({}, SourceRegistry()) == []
    assert ec.fetch_economic_calendar({"economic_calendar": {"sources": []}}, SourceRegistry()) == []


def test_fetch_economic_calendar_unreachable_is_safe():
    config = {"economic_calendar": {"sources": [{"name": "死んでる", "url": "http://127.0.0.1:1/x.json", "type": "json"}]}}
    assert ec.fetch_economic_calendar(config, SourceRegistry()) == []  # 例外を投げず空


def test_merge_events_prefers_config_and_dedupes():
    config_events = [{"date": "2026-07-10", "label": "米CPI"}]
    auto_events = [
        {"date": "2026-07-10", "label": "米CPI", "source": "auto"},
        {"date": "2026-07-11", "label": "FOMC", "source": "auto"},
    ]
    merged = ec.merge_events(config_events, auto_events)
    labels = [e["label"] for e in merged]
    assert labels.count("米CPI") == 1
    # config登録分（手入力）を優先（sourceキーが無い方が残る）
    cpi = next(e for e in merged if e["label"] == "米CPI")
    assert "source" not in cpi
    assert "FOMC" in labels


def test_weekly_events_only_within_7_days_and_excludes_14():
    macro = [
        {"date": "2026-07-09", "label": "FOMC 政策金利発表"},   # 2日後 → 表示
        {"date": "2026-07-21", "label": "2週間後の米CPI"},       # 14日後 → 除外
        {"date": "2026-07-06", "label": "昨日の日銀会合"},        # 過去 → 除外
    ]
    entries = build_weekly_event_calendar(NOW, macro)
    labels = [e.label for e in entries]
    assert "FOMC 政策金利発表" in labels
    assert "2週間後の米CPI" not in labels
    assert "昨日の日銀会合" not in labels


def test_weekly_event_auto_source_and_fetched_at_shown():
    macro = [
        {"date": "2026-07-09", "label": "米CPI発表", "time": "21:30",
         "source": "Fed カレンダーRSS", "fetched_at": "2026-07-07T07:00:00+00:00"},
    ]
    entries = build_weekly_event_calendar(NOW, macro)
    assert len(entries) == 1
    e = entries[0]
    assert e.source == "Fed カレンダーRSS"
    assert e.source_stars  # Source Trust の★が付く
    assert e.fetched_at == "2026-07-07T07:00:00+00:00"
    # 影響対象が自動補完される（米CPI → 米金利・ドル円・NASDAQ 等）
    assert "米金利" in e.impact_targets

    bundle = full_bundle()
    bundle.weekly_events = entries
    report = build_html_report(
        report_date=datetime(2026, 7, 7), market=full_market(), sources=SourceRegistry(), analysis=bundle,
    )
    assert "Source: Fed カレンダーRSS" in report
    assert "取得時刻" in report


def test_weekly_event_config_source_is_registered_info():
    macro = [{"date": "2026-07-09", "label": "日銀会合"}]  # source無し = 手入力
    entries = build_weekly_event_calendar(NOW, macro)
    assert entries[0].source == "登録情報"
    assert entries[0].source_stars == "★★★★★"  # 自分の管理情報
