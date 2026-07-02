"""main.py の --date オプションと latest_market_brief.md 生成をネットワークなしで検証する。"""
from unittest.mock import patch

import yaml

import main as main_module


def _write_minimal_config(tmp_path) -> str:
    config = {
        "watchlist": {"jp_stocks": [], "us_stocks": []},
        "indices": [],
        "forex": [],
        "rates": [],
        "commodities": [],
        "news_sources": [],
        # 存在しないローカルアドレスにして、実ネットワークへ問い合わせず即座に失敗させる
        "tdnet": {"list_url_template": "http://127.0.0.1:1/I_list_001_{date}.html", "lookback_days": 1},
        # 追加収集モジュール（nikkei/bloomberg/reuters/cnbc/wsj/marketwatch/investing/
        # boj/mof/edinet/fred）も同様に到達不能なローカルアドレスへ差し替え、
        # オフラインテストで実ネットワークへ問い合わせないようにする。
        "nikkei_sources": [],
        "bloomberg_sources": [],
        "reuters_sources": [],
        "cnbc_sources": [],
        "wsj_sources": [],
        "marketwatch_sources": [],
        "investing_sources": [],
        "boj_sources": [],
        "mof_sources": [],
        "edinet": {"documents_url": "http://127.0.0.1:1/documents.json"},
        "fred": {
            "csv_url_template": "http://127.0.0.1:1/fredgraph.csv?id={series_id}",
            "series": [{"id": "T10Y2Y", "name": "米10年-2年金利差"}],
        },
        "themes": [],
        "sectors": {},
        "output": {"dir": str(tmp_path), "timezone": "Asia/Tokyo", "headlines_per_source": 8},
    }
    config_path = tmp_path / "config.yaml"
    config_path.write_text(yaml.safe_dump(config, allow_unicode=True), encoding="utf-8")
    return str(config_path)


def test_generate_report_with_date_option_creates_dated_and_latest_files(tmp_path):
    config_path = _write_minimal_config(tmp_path)

    out_path = main_module.generate_report(config_path=config_path, date_str="2026-07-01")

    assert out_path.name == "2026-07-01_market_brief.md"
    assert out_path.exists()

    latest_path = tmp_path / main_module.LATEST_FILENAME
    assert latest_path.exists()
    assert out_path.read_text(encoding="utf-8") == latest_path.read_text(encoding="utf-8")
    assert "Market Intelligence System v4 — 朝レポート 2026年07月01日" in out_path.read_text(encoding="utf-8")


def test_generate_report_rejects_invalid_date(tmp_path):
    config_path = _write_minimal_config(tmp_path)

    try:
        main_module.generate_report(config_path=config_path, date_str="2026/07/01")
        assert False, "SystemExitが発生するはず"
    except SystemExit as exc:
        assert "YYYY-MM-DD" in str(exc)


def test_generate_report_creates_mobile_and_html_files(tmp_path):
    config_path = _write_minimal_config(tmp_path)

    main_module.generate_report(config_path=config_path, date_str="2026-07-01")

    assert (tmp_path / main_module.MOBILE_FILENAME).exists()
    assert (tmp_path / main_module.LATEST_HTML_FILENAME).exists()
    assert (tmp_path / "2026-07-01_market_brief.html").exists()


def test_generate_report_succeeds_without_any_notification_env_vars(tmp_path, monkeypatch):
    for var in (
        "SMTP_HOST", "SMTP_PORT", "SMTP_USER", "SMTP_PASSWORD", "MAIL_TO", "MAIL_FROM",
        "LINE_CHANNEL_ACCESS_TOKEN", "LINE_TO",
    ):
        monkeypatch.delenv(var, raising=False)
    config_path = _write_minimal_config(tmp_path)

    # 通知未設定でも例外を出さずレポートが生成されること
    out_path = main_module.generate_report(config_path=config_path, date_str="2026-07-01")
    assert out_path.exists()


def test_generate_report_sends_notifications_when_configured(tmp_path, monkeypatch):
    monkeypatch.setenv("SMTP_HOST", "smtp.example.com")
    monkeypatch.setenv("SMTP_PORT", "587")
    monkeypatch.setenv("SMTP_USER", "user@example.com")
    monkeypatch.setenv("SMTP_PASSWORD", "secret")
    monkeypatch.setenv("MAIL_TO", "to@example.com")
    monkeypatch.setenv("LINE_CHANNEL_ACCESS_TOKEN", "token123")
    monkeypatch.setenv("LINE_TO", "user123")
    config_path = _write_minimal_config(tmp_path)

    with patch("notifiers.email_sender.EmailNotifier.send", return_value=True) as mock_email_send, \
         patch("notifiers.line_sender.LineNotifier.send", return_value=True) as mock_line_send:
        out_path = main_module.generate_report(config_path=config_path, date_str="2026-07-01")

    assert out_path.exists()
    mock_email_send.assert_called_once()
    mock_line_send.assert_called_once()
    payload = mock_email_send.call_args[0][0]
    assert payload.title == "【Market Brief】2026-07-01 朝刊"


def test_generate_report_skips_notifications_when_disabled_in_config(tmp_path, monkeypatch):
    monkeypatch.setenv("SMTP_HOST", "smtp.example.com")
    monkeypatch.setenv("SMTP_USER", "user@example.com")
    monkeypatch.setenv("SMTP_PASSWORD", "secret")
    monkeypatch.setenv("MAIL_TO", "to@example.com")
    monkeypatch.setenv("LINE_CHANNEL_ACCESS_TOKEN", "token123")
    monkeypatch.setenv("LINE_TO", "user123")

    config_path = _write_minimal_config(tmp_path)
    config = yaml.safe_load(open(config_path, encoding="utf-8"))
    config["notifications"] = {"email": {"enabled": False}, "line": {"enabled": False}}
    with open(config_path, "w", encoding="utf-8") as f:
        yaml.safe_dump(config, f, allow_unicode=True)

    with patch("notifiers.email_sender.EmailNotifier.send", return_value=True) as mock_email_send, \
         patch("notifiers.line_sender.LineNotifier.send", return_value=True) as mock_line_send:
        out_path = main_module.generate_report(config_path=config_path, date_str="2026-07-01")

    assert out_path.exists()
    mock_email_send.assert_not_called()
    mock_line_send.assert_not_called()


def test_generate_report_continues_even_if_notification_send_raises(tmp_path, monkeypatch):
    monkeypatch.setenv("SMTP_HOST", "smtp.example.com")
    monkeypatch.setenv("SMTP_USER", "user@example.com")
    monkeypatch.setenv("SMTP_PASSWORD", "secret")
    monkeypatch.setenv("MAIL_TO", "to@example.com")
    config_path = _write_minimal_config(tmp_path)

    with patch("notifiers.email_sender.EmailNotifier.send", side_effect=RuntimeError("boom")):
        # 通知送信中に予期しない例外が出てもレポート生成自体は成功すること
        out_path = main_module.generate_report(config_path=config_path, date_str="2026-07-01")

    assert out_path.exists()
