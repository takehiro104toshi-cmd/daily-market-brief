"""main.py の --date オプションと latest_market_brief.md 生成をネットワークなしで検証する。"""
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
    assert "Market Intelligence System v2 — 朝レポート 2026年07月01日" in out_path.read_text(encoding="utf-8")


def test_generate_report_rejects_invalid_date(tmp_path):
    config_path = _write_minimal_config(tmp_path)

    try:
        main_module.generate_report(config_path=config_path, date_str="2026/07/01")
        assert False, "SystemExitが発生するはず"
    except SystemExit as exc:
        assert "YYYY-MM-DD" in str(exc)
