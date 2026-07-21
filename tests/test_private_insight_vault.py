"""Rashinban Private Insight Vault（daily-market-brief側）のオフラインテスト。

派生情報クライアント（disabled/ok/unavailable・fake transport）、
入力カード（api_url未設定/設定・Secret非埋め込み）、Future Outlookカード、
既存レポートとの互換を検証する。ネットワークは使わない。
"""
from __future__ import annotations

from datetime import datetime, timezone

from src.analysis.models import PrivateInsightOutlook
from src.data.private_insight_client import count_recent, fetch_derived_summaries
from src.report.html_builder import (
    _private_insight_intake_card,
    _private_insight_outlook_card,
)

SAMPLE_SUMMARY = {
    "private_article_id": "pai_abc",
    "title": "データセンター向け送電網投資が拡大",
    "source_name": "日本経済新聞",
    "submitted_at": "2026-07-20T21:00:00+09:00",
    "short_summary": "電力インフラ投資に関するprivate保存記事。",
    "themes": ["electric_power"],
    "impression_hint": "設備投資は変圧器・電線・冷却・電力供給へ波及する可能性が高い",
    "forecast_summary": [
        {"scenario_type": "base", "scenario_title": "電力インフラ投資の増加が継続", "horizon": "1m",
         "confidence": 0.55, "leading_indicators": ["電力会社の設備投資計画", "変圧器受注"],
         "next_review_date": "2026-08-20", "validation_status": "pending"},
    ],
    "confidence": 0.55,
    "next_review_date": "2026-08-20",
}


# ---------- クライアント ----------

def test_client_disabled_without_config_or_token(monkeypatch):
    monkeypatch.delenv("INSIGHT_API_TOKEN", raising=False)
    items, status = fetch_derived_summaries({"private_insight_intake": {"api_url": ""}})
    assert items == [] and status["state"] == "disabled"

    # api_urlがあってもトークンが無ければdisabled（ネットワークアクセスなし）
    items, status = fetch_derived_summaries(
        {"private_insight_intake": {"api_url": "https://w.example/api"}})
    assert status["state"] == "disabled"


def test_client_fetches_with_fake_transport(monkeypatch):
    monkeypatch.setenv("INSIGHT_API_TOKEN", "tok")
    calls = []

    def fake_transport(url, token, timeout):
        calls.append((url, token))
        return {"ok": True, "items": [SAMPLE_SUMMARY]}

    items, status = fetch_derived_summaries(
        {"private_insight_intake": {"api_url": "https://w.example/api/private-insight"}},
        transport=fake_transport)
    assert status["state"] == "ok" and len(items) == 1
    assert calls[0][0].endswith("/derived")


def test_client_failure_returns_unavailable_not_exception(monkeypatch):
    monkeypatch.setenv("INSIGHT_API_TOKEN", "tok")

    def broken(url, token, timeout):
        raise TimeoutError("boom")

    items, status = fetch_derived_summaries(
        {"private_insight_intake": {"api_url": "https://w.example/api"}}, transport=broken)
    assert items == [] and status["state"] == "unavailable"


def test_count_recent_today_and_week():
    now = datetime(2026, 7, 20, 12, 0, tzinfo=timezone.utc)  # JST 21:00
    summaries = [
        {"submitted_at": "2026-07-20T21:00:00+09:00"},   # 今日
        {"submitted_at": "2026-07-16T10:00:00+09:00"},   # 週内
        {"submitted_at": "2026-06-01T10:00:00+09:00"},   # 週外
    ]
    today, week = count_recent(summaries, now=now)
    assert today == 1 and week == 2


# ---------- 入力カード ----------

def test_intake_card_without_api_url_shows_setup_note_only():
    html = _private_insight_intake_card({"enabled": True, "api_url": ""})
    assert "Rashinban Private Insight Vault" in html
    assert "api_url が未設定" in html
    assert "piSend" not in html  # 送信UIは出さない


def test_intake_card_with_api_url_has_form_and_no_secrets():
    cfg = {"enabled": True, "api_url": "https://w.example/api/private-insight",
           "max_body_chars": 30000}
    html = _private_insight_intake_card(cfg)
    assert "Data Tankへ転送して分析" in html
    assert "pi-body" in html and "piSend" in html
    assert "X-Insight-Key" in html            # パスフレーズはヘッダー送信
    assert "type='password'" in html          # 入力欄はpassword
    # トークン・パスフレーズの値がHTMLへ埋め込まれていない
    assert "INSIGHT_API_TOKEN" not in html
    assert "PASSPHRASE" not in html
    # 失敗時に本文を保持する文言
    assert "本文はこの画面に残っています" in html


def test_intake_card_disabled_returns_empty():
    assert _private_insight_intake_card({"enabled": False, "api_url": "https://x"}) == ""


# ---------- Future Outlook カード ----------

def test_outlook_card_renders_summaries_without_body():
    outlook = PrivateInsightOutlook(state="ok", new_today=1, new_last7days=2,
                                    summaries=[SAMPLE_SUMMARY])
    html = _private_insight_outlook_card(outlook)
    assert "Private Research Future Outlook" in html
    assert "データセンター向け送電網投資が拡大" in html      # タイトル（allowlist）
    assert "電力会社の設備投資計画" in html                  # 確認指標
    assert "2026-08-20" in html                             # 次回検証日
    assert "波及する可能性" in html                          # AI所感
    # bundleに本文フィールド自体が無い（構造的保証）
    assert not hasattr(outlook, "raw_body")


def test_outlook_card_hidden_when_disabled_and_warns_when_unavailable():
    assert _private_insight_outlook_card(None) == ""
    assert _private_insight_outlook_card(PrivateInsightOutlook(state="disabled")) == ""
    warn = _private_insight_outlook_card(PrivateInsightOutlook(state="unavailable", reason="TimeoutError"))
    assert "取得に失敗" in warn
    assert "通常通り生成" in warn


# ---------- 既存レポート互換 ----------

def test_full_report_still_builds_with_new_cards():
    from datetime import datetime as dt
    from src.report.html_builder import build_html_report
    from src.utils import SourceRegistry
    from tests.factories import full_bundle, full_market

    bundle = full_bundle()
    bundle.private_insight_outlook = PrivateInsightOutlook(
        state="ok", new_today=1, new_last7days=1, summaries=[SAMPLE_SUMMARY])
    report = build_html_report(
        report_date=dt(2026, 7, 20), market=full_market(), sources=SourceRegistry(),
        analysis=bundle,
        private_insight_intake={"enabled": True, "api_url": "https://w.example/api/private-insight"},
    )
    assert "Rashinban Private Insight Vault" in report
    assert "Private Research Future Outlook" in report
    assert report.count("<div") == report.count("</div>")


def test_main_module_wires_private_insight():
    import main as main_module
    assert hasattr(main_module, "private_insight_client")
