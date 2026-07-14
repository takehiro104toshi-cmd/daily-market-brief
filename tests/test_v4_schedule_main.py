"""v4.x スケジュール運用の main.py 統合をネットワークなしで検証する（§13-18）。

履歴HTML保存 / 最新index更新 / HTML妥当性チェックでindexを壊さない / 手動・one_tap・
slotなし実行の後方互換 / 実行記録の書き込みを確認する。
"""
import json
from pathlib import Path

import yaml

import main as main_module


def _config(tmp_path, extra_schedule=None) -> str:
    sched = {
        "enabled": True,
        "runs_dir": str(tmp_path / "runs"),
        "history_dir": str(tmp_path / "hist"),
        "archive_reports": True,
    }
    if extra_schedule:
        sched.update(extra_schedule)
    config = {
        "watchlist": {"jp_stocks": [], "us_stocks": []},
        "indices": [], "forex": [], "rates": [], "commodities": [],
        "news_sources": [], "nikkei_sources": [], "bloomberg_sources": [], "reuters_sources": [],
        "cnbc_sources": [], "wsj_sources": [], "marketwatch_sources": [], "investing_sources": [],
        "boj_sources": [], "mof_sources": [],
        "tdnet": {"list_url_template": "http://127.0.0.1:1/{date}.html", "lookback_days": 1},
        "edinet": {"documents_url": "http://127.0.0.1:1/d.json"},
        "fred": {"csv_url_template": "http://127.0.0.1:1/{series_id}.csv", "series": []},
        "themes": [], "sectors": {},
        "output": {"dir": str(tmp_path / "output"), "timezone": "Asia/Tokyo", "headlines_per_source": 8},
        "report_schedule": sched,
    }
    path = tmp_path / "config.yaml"
    path.write_text(yaml.safe_dump(config, allow_unicode=True), encoding="utf-8")
    return str(path)


# §18/§5: 実行記録に success が記録される
def test_slot_run_records_success(tmp_path):
    cfg = _config(tmp_path)
    main_module.generate_report(config_path=cfg, date_str="2026-07-14",
                                report_slot="market_close", trigger_type="schedule")
    runs = json.loads((tmp_path / "runs" / "2026-07-14.json").read_text(encoding="utf-8"))
    rec = runs["slots"]["market_close"]
    assert rec["status"] == "success"
    assert rec["slot_label"] == "大引けレポート"
    assert rec["trigger_type"] == "schedule"
    assert rec["report_date_jst"] == "2026-07-14"


# §13: 履歴HTML保存
def test_history_html_saved(tmp_path):
    cfg = _config(tmp_path)
    main_module.generate_report(config_path=cfg, date_str="2026-07-14",
                                report_slot="pre_market", trigger_type="schedule")
    hist = tmp_path / "hist" / "2026-07-14" / "pre_market.html"
    assert hist.exists() and "Market Intelligence System" in hist.read_text(encoding="utf-8")


# §6: archive_reports=false なら履歴を保存しない（最新は更新）
def test_history_not_saved_when_archive_disabled(tmp_path):
    cfg = _config(tmp_path, extra_schedule={"archive_reports": False})
    main_module.generate_report(config_path=cfg, date_str="2026-07-14",
                                report_slot="pre_market", trigger_type="schedule")
    assert not (tmp_path / "hist" / "2026-07-14" / "pre_market.html").exists()
    assert (tmp_path / "output" / "latest_market_brief.html").exists()


# §14: 最新 index.html が更新され、生成状況カードを含む
def test_latest_index_updated_with_status_card(tmp_path):
    cfg = _config(tmp_path)
    main_module.generate_report(config_path=cfg, date_str="2026-07-14",
                                report_slot="market_close", trigger_type="schedule")
    latest = (tmp_path / "output" / "latest_market_brief.html").read_text(encoding="utf-8")
    assert "本日のレポート生成状況" in latest
    assert "現在表示中" in latest


# §7/§9: 二重生成防止 & 回復 no-op
def test_duplicate_success_is_skipped(tmp_path):
    cfg = _config(tmp_path)
    main_module.generate_report(config_path=cfg, date_str="2026-07-14",
                                report_slot="market_close", trigger_type="schedule")
    runs_file = tmp_path / "runs" / "2026-07-14.json"
    first = runs_file.read_text(encoding="utf-8")
    # 同一slotを再度（force無し）→ 生成せずスキップ（記録は変わらない or successのまま）
    ret = main_module.generate_report(config_path=cfg, date_str="2026-07-14",
                                      report_slot="market_close", trigger_type="schedule")
    assert ret is not None  # 既存の最新パスを返す
    runs = json.loads(runs_file.read_text(encoding="utf-8"))
    assert runs["slots"]["market_close"]["status"] == "success"


def test_recovery_on_success_generates_nothing_new(tmp_path):
    cfg = _config(tmp_path)
    main_module.generate_report(config_path=cfg, date_str="2026-07-14",
                                report_slot="evening", trigger_type="schedule")
    hist = tmp_path / "hist" / "2026-07-14" / "evening.html"
    mtime_before = hist.stat().st_mtime
    # 回復（success済み）→ no-op、履歴は再生成されない
    main_module.generate_report(config_path=cfg, date_str="2026-07-14",
                                report_slot="evening", trigger_type="recovery", recovery=True)
    assert hist.stat().st_mtime == mtime_before


# §17: auto スロット解決（手動 auto）
def test_manual_auto_slot(tmp_path):
    cfg = _config(tmp_path)
    # date_str は 07:00 JST 固定 → 直前 slot は無し（早朝）→ 臨時扱いでも生成は成功する
    ret = main_module.generate_report(config_path=cfg, date_str="2026-07-14",
                                      report_slot="auto", trigger_type="manual")
    assert ret is not None


# §16/§18: slot なし（従来）実行は完全な後方互換（スケジュール記録なし）
def test_backward_compat_no_slot(tmp_path):
    cfg = _config(tmp_path)
    out = main_module.generate_report(config_path=cfg, date_str="2026-07-14")
    assert out.name == "2026-07-14_market_brief.md"
    # スケジュールに関与しない → runs も history も作られない
    assert not (tmp_path / "runs").exists()
    assert not (tmp_path / "hist").exists()


# §15: HTML妥当性チェック（正常HTMLは合格・壊れHTMLは不合格）
def test_validate_html():
    assert main_module._validate_html("") is False
    assert main_module._validate_html("<html>短い</html>") is False
    good = (
        "<!DOCTYPE html><html><head><title>Market Intelligence System v4</title></head>"
        "<body><p>最終更新: 2026-07-14 15:40 (JST)</p>"
        "<div class='card'>相場の目次・本日の相場総括をここに表示します。" + ("x" * 200) + "</div>"
        "</body></html>"
    )
    assert main_module._validate_html(good) is True
    # 必須トークン（最終更新）が欠けると不合格 → index を上書きしない根拠
    bad = good.replace("最終更新", "更新なし")
    assert main_module._validate_html(bad) is False
