"""Weekly Event Impact Calendar（v2.7）をネットワークなしで検証する。"""
from datetime import datetime

import pytz

from src.analysis.weekly_events import build_weekly_event_calendar
from src.collectors.earnings import EarningsEvent
from src.report.html_builder import _weekly_events_html, build_html_report
from src.utils import SourceRegistry
from tests.factories import full_bundle, full_market

JST = pytz.timezone("Asia/Tokyo")
NOW = JST.localize(datetime(2026, 7, 6, 7, 0))

MACRO_EVENTS = [
    {"date": "2026-07-06", "label": "米CPI（消費者物価指数）発表", "time": "21:30"},
    {"date": "2026-07-09", "label": "FOMC（米連邦公開市場委員会）政策金利発表"},
    {"date": "2026-07-05", "label": "過去の日銀会合"},          # 昨日 → 除外
    {"date": "2026-07-20", "label": "2週間先の米雇用統計"},      # 7日超 → 除外
    {"date": "2026-07-10", "label": "SQ（特別清算指数算出日）"},
]


def test_only_events_within_one_week_are_included():
    entries = build_weekly_event_calendar(NOW, MACRO_EVENTS)
    labels = [e.label for e in entries]
    assert "過去の日銀会合" not in labels          # 過去イベントは表示されない
    assert "2週間先の米雇用統計" not in labels     # 1週間より先は表示されない
    assert len(entries) == 3


def test_countdown_days_and_hours():
    entries = build_weekly_event_calendar(NOW, MACRO_EVENTS)
    cpi = next(e for e in entries if "CPI" in e.label)
    fomc = next(e for e in entries if "FOMC" in e.label)
    # 本日・時刻登録あり → 「本日21:30（あと14時間）」
    assert cpi.countdown_text.startswith("本日21:30")
    assert "あと14時間" in cpi.countdown_text
    # 3日後・時刻なし → 「あと3日」
    assert fomc.countdown_text == "あと3日"


def test_importance_and_impact_targets():
    entries = build_weekly_event_calendar(NOW, MACRO_EVENTS)
    cpi = next(e for e in entries if "CPI" in e.label)
    assert cpi.stars == "★★★★★"
    assert cpi.importance == 100
    assert "ドル円" in cpi.impact_targets
    assert "米金利" in cpi.impact_targets
    assert "インフレ" in cpi.expected_impact


def test_sorted_by_proximity_then_importance():
    entries = build_weekly_event_calendar(NOW, MACRO_EVENTS)
    assert [e.days_until for e in entries] == sorted(e.days_until for e in entries)
    assert "CPI" in entries[0].label  # 本日のCPIが先頭


def test_earnings_events_within_week_are_included():
    earnings = [
        EarningsEvent(ticker="7203.T", name="トヨタ自動車", date="2026-07-08", source_url="https://example.com"),
        EarningsEvent(ticker="6758.T", name="ソニーグループ", date="2026-08-01", source_url="https://example.com"),
    ]
    entries = build_weekly_event_calendar(NOW, [], earnings)
    labels = [e.label for e in entries]
    assert any("トヨタ自動車" in l and "決算発表" in l for l in labels)
    assert not any("ソニーグループ" in l for l in labels)  # 1週間超は対象外


def test_empty_input_is_safe():
    assert build_weekly_event_calendar(NOW, []) == []
    assert build_weekly_event_calendar(NOW, None, None) == []
    html = _weekly_events_html([])
    assert "直近1週間の重要イベントは登録されていません" in html


def test_html_section_with_detail_button():
    bundle = full_bundle()
    bundle.weekly_events = build_weekly_event_calendar(NOW, MACRO_EVENTS)
    report = build_html_report(
        report_date=datetime(2026, 7, 6),
        market=full_market(),
        sources=SourceRegistry(),
        analysis=bundle,
    )
    assert "今週の重要イベント・経済指標" in report
    assert "event-countdown" in report
    assert "なぜ重要か" in report          # 「詳しく」内の項目
    assert ">詳しく</summary>" in report
    assert "重要度100" in report
