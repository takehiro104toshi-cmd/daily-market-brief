"""v3.3 Latest Report Generation Button Upgrade をネットワークなしで検証する。

対象: ①ボタンUI再設計（再読み込み／最新レポート生成／スマホ手順） ②Actions画面への
リンク精度（config.yaml の output.actions_url 優先） ③生成状態の説明 ④将来の
ワンタップ生成枠（realtime.enabled=true かつ endpoint_url設定時のみ） ⑤セキュリティ
（GitHub Token/Secretsの類を一切HTMLへ出さない）。
"""
from datetime import datetime

import main as main_module
from src.report.html_builder import build_html_report
from src.utils import SourceRegistry
from tests.factories import full_bundle, full_market

ACTIONS_URL = "https://github.com/example/daily-market-brief/actions/workflows/daily-market-brief.yml"


def _report(actions_url=None, realtime=None):
    return build_html_report(
        report_date=datetime(2026, 7, 7, 9, 0),
        market=full_market(),
        sources=SourceRegistry(),
        analysis=full_bundle(),
        actions_url=actions_url,
        realtime=realtime,
    )


# ---------- 改善① ボタンUI ----------

def test_reload_button_always_shown():
    report = _report()
    assert 'class="refresh-btn"' in report
    assert 'href="javascript:location.reload()"' in report
    assert "ページを再読み込み" in report


def test_regenerate_button_shown_with_actions_url():
    report = _report(actions_url=ACTIONS_URL)
    assert 'class="regenerate-btn"' in report
    assert ACTIONS_URL in report
    assert "最新レポートを生成する" in report


def test_mobile_steps_details_shown():
    report = _report(actions_url=ACTIONS_URL)
    assert "<details class='mobile-steps'>" in report
    assert "スマホでの実行手順" in report
    assert "Run workflow" in report


def test_actions_url_unset_shows_pending_message_not_hidden():
    report = _report(actions_url="")
    assert 'class="regenerate-btn"' not in report
    assert "設定未完了" in report
    assert "最新レポートを生成する" in report  # ボタンは消えず文言として残る


# ---------- 改善③ 生成状態の説明 ----------

def test_generation_status_explains_reload_vs_regenerate():
    report = _report(actions_url=ACTIONS_URL)
    assert "最終生成時刻" in report
    assert "新しいデータは取得しません" in report


# ---------- 改善④ 将来のワンタップ生成枠 ----------

def test_one_tap_button_absent_when_realtime_disabled():
    report = _report(actions_url=ACTIONS_URL, realtime={"enabled": False, "endpoint_url": ""})
    assert "ワンタップで最新生成" not in report
    report_none = _report(actions_url=ACTIONS_URL, realtime=None)
    assert "ワンタップで最新生成" not in report_none


def test_one_tap_button_present_when_realtime_enabled_with_endpoint():
    report = _report(
        actions_url=ACTIONS_URL,
        realtime={"enabled": True, "endpoint_url": "https://relay.example.com/hook", "provider": "cloudflare_worker"},
    )
    assert "ワンタップで最新生成" in report
    assert 'class=\'one-tap-btn\' disabled' in report or "disabled" in report


def test_one_tap_button_absent_when_enabled_but_no_endpoint():
    report = _report(actions_url=ACTIONS_URL, realtime={"enabled": True, "endpoint_url": ""})
    assert "ワンタップで最新生成" not in report


# ---------- 改善⑤ セキュリティ ----------

def test_no_token_or_secret_like_strings_in_html():
    report = _report(
        actions_url=ACTIONS_URL,
        realtime={"enabled": True, "endpoint_url": "https://relay.example.com/hook"},
    )
    assert "token" not in report.lower()
    assert "ghp_" not in report
    assert "ANTHROPIC_API_KEY" not in report
    assert report.count("<div") == report.count("</div>")


# ---------- 改善② Actions画面へのリンク精度 ----------

def test_resolve_actions_url_prefers_config_value(monkeypatch):
    monkeypatch.delenv("ACTIONS_URL", raising=False)
    monkeypatch.delenv("GITHUB_REPOSITORY", raising=False)
    config = {"output": {"actions_url": ACTIONS_URL}}
    assert main_module._resolve_actions_url(config) == ACTIONS_URL


def test_resolve_actions_url_falls_back_to_github_repository(monkeypatch):
    monkeypatch.delenv("ACTIONS_URL", raising=False)
    monkeypatch.setenv("GITHUB_REPOSITORY", "example/daily-market-brief")
    config = {"output": {"actions_url": ""}}
    url = main_module._resolve_actions_url(config)
    assert url == "https://github.com/example/daily-market-brief/actions/workflows/daily-market-brief.yml"


def test_resolve_actions_url_env_override_wins(monkeypatch):
    monkeypatch.setenv("ACTIONS_URL", "https://github.com/override/repo/actions/workflows/daily-market-brief.yml")
    monkeypatch.setenv("GITHUB_REPOSITORY", "example/daily-market-brief")
    config = {"output": {"actions_url": ACTIONS_URL}}
    assert main_module._resolve_actions_url(config) == "https://github.com/override/repo/actions/workflows/daily-market-brief.yml"


def test_resolve_actions_url_empty_when_nothing_set(monkeypatch):
    monkeypatch.delenv("ACTIONS_URL", raising=False)
    monkeypatch.delenv("GITHUB_REPOSITORY", raising=False)
    assert main_module._resolve_actions_url({"output": {"actions_url": ""}}) == ""
