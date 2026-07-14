"""v4.x Six Daily Report Schedule & Reliability Upgrade をネットワークなしで検証する（§19）。

JST/UTC変換・cron対応・二重生成防止・回復・実行記録の読み書き・HTML状態カード・
resolve_report_schedule スクリプト・main.py の後方互換を確認する。
"""
import datetime
import json
from pathlib import Path

import pytz

from src.analysis import report_schedule as RS
from src.report.schedule_status import render_schedule_status_card

JST = pytz.timezone("Asia/Tokyo")


def _jst(y, mo, d, h, mi):
    return JST.localize(datetime.datetime(y, mo, d, h, mi))


# ---------- 1) JST/UTC 変換 ----------

def test_jst_hm_to_utc_hm_basic():
    assert RS.jst_hm_to_utc_hm(9, 10) == (0, 10)     # 09:10 JST = 00:10 UTC
    assert RS.jst_hm_to_utc_hm(11, 30) == (2, 30)


# 2) 07:30 JST が前日 22:30 UTC になる
def test_pre_market_cron_is_prev_day_2230_utc():
    assert RS.jst_hm_to_utc_hm(7, 30) == (22, 30)
    slot = {"id": "pre_market", "time": "07:30", "label": "寄り前"}
    assert RS.normal_cron_for_slot(slot) == "30 22 * * *"


# 3) 各通常 cron と slot_id の対応
def test_normal_cron_to_slot_mapping():
    cfg = None
    cases = {
        "30 22 * * *": "pre_market",
        "10 0 * * *": "market_open",
        "30 2 * * *": "morning_close",
        "40 3 * * *": "afternoon_open",
        "40 6 * * *": "market_close",
        "20 8 * * *": "evening",
    }
    for cron, slot_id in cases.items():
        assert RS.resolve_cron(cfg, cron) == (slot_id, "generate"), cron


# 4) 各回復 cron と slot_id の対応
def test_recovery_cron_to_slot_mapping():
    cfg = None
    cases = {
        "45 22 * * *": "pre_market",
        "25 0 * * *": "market_open",
        "45 2 * * *": "morning_close",
        "55 3 * * *": "afternoon_open",
        "55 6 * * *": "market_close",
        "35 8 * * *": "evening",
    }
    for cron, slot_id in cases.items():
        assert RS.resolve_cron(cfg, cron) == (slot_id, "recovery"), cron


def test_unknown_cron_returns_none():
    assert RS.resolve_cron(None, "0 5 * * *") == (None, None)


# 5) JST 日付境界（auto slot の直前解決）
def test_auto_slot_resolves_previous_slot():
    assert RS.resolve_auto_slot(None, _jst(2026, 7, 14, 12, 50)) == "afternoon_open"
    assert RS.resolve_auto_slot(None, _jst(2026, 7, 14, 9, 9)) == "pre_market"
    assert RS.resolve_auto_slot(None, _jst(2026, 7, 14, 6, 0)) is None  # 早朝は直前slotなし


# 11+12) 実行記録の読み書き / 初回（ファイルなし）
def test_runs_read_write_roundtrip(tmp_path):
    path = tmp_path / "2026-07-14.json"
    doc = RS.load_runs(path, "2026-07-14")  # 初回: 存在しない → 空
    assert doc["slots"] == {}
    RS.upsert_slot_record(doc, "market_close", {"status": "success", "generated_at": "x"})
    RS.save_runs_atomic(path, doc)
    reloaded = RS.load_runs(path, "2026-07-14")
    assert reloaded["slots"]["market_close"]["status"] == "success"


def test_load_runs_handles_corrupt_json(tmp_path):
    path = tmp_path / "bad.json"
    path.write_text("{ this is not json", encoding="utf-8")
    doc = RS.load_runs(path, "2026-07-14")
    assert doc["slots"] == {}  # 壊れていても例外を投げず空で返す


# 6) 二重生成防止（success はスキップ）
def test_success_slot_is_skipped():
    runs = {"slots": {"market_close": {"status": "success"}}}
    should, reason = RS.decide_action(None, runs, "market_close", now=_jst(2026, 7, 14, 16, 0))
    assert should is False and reason == "already_success"


# 7) force 指定時は再生成
def test_force_regenerates_success_slot():
    runs = {"slots": {"market_close": {"status": "success"}}}
    should, _ = RS.decide_action(None, runs, "market_close", force=True, now=_jst(2026, 7, 14, 16, 0))
    assert should is True


# 8) failed slot は回復実行で再生成
def test_failed_slot_recovery_regenerates():
    runs = {"slots": {"market_close": {"status": "failed"}}}
    should, reason = RS.decide_action(None, runs, "market_close", is_recovery=True, now=_jst(2026, 7, 14, 16, 0))
    assert should is True and reason == "retry_failed"


# 9) success slot への回復処理は no-op
def test_recovery_on_success_is_noop():
    runs = {"slots": {"market_close": {"status": "success", "is_recovery_run": False}}}
    should, reason = RS.decide_action(None, runs, "market_close", is_recovery=True, now=_jst(2026, 7, 14, 16, 0))
    assert should is False and reason == "already_success"


# 10) stale slot の回復
def test_stale_running_is_regenerated():
    started = _jst(2026, 7, 14, 15, 40).isoformat()
    runs = {"slots": {"market_close": {"status": "running", "started_at": started}}}
    # 1時間後 → stale_after 30分を超過
    now = _jst(2026, 7, 14, 16, 40)
    assert RS.is_stale(runs["slots"]["market_close"], now, 30) is True
    should, reason = RS.decide_action(None, runs, "market_close", is_recovery=True, now=now)
    assert should is True and reason == "stale_running"


def test_running_not_stale_is_skipped():
    started = _jst(2026, 7, 14, 15, 40).isoformat()
    runs = {"slots": {"market_close": {"status": "running", "started_at": started}}}
    now = _jst(2026, 7, 14, 15, 50)  # 10分後 → まだ stale でない
    should, reason = RS.decide_action(None, runs, "market_close", now=now)
    assert should is False and reason == "running_in_progress"


# 19) 生成状況カードの表示
def test_status_card_renders_all_slots():
    runs = {"date": "2026-07-14", "slots": {
        "pre_market": {"status": "success", "generated_at": _jst(2026, 7, 14, 7, 33).isoformat()},
    }}
    ctx = RS.build_status_context(None, runs, now=_jst(2026, 7, 14, 9, 0), current_slot_id="pre_market")
    html = render_schedule_status_card(ctx)
    assert "本日のレポート生成状況" in html
    assert "寄り前レポート" in html and "夕方総括" in html
    assert "現在表示中" in html
    assert "生成済み" in html


def test_status_card_empty_when_no_context():
    assert render_schedule_status_card(None) == ""
    assert render_schedule_status_card({"rows": []}) == ""


# 20) 予定時刻前を failed 扱いしない
def test_future_slot_is_pending_not_failed():
    runs = {"date": "2026-07-14", "slots": {}}
    # 08:00 時点で market_close(15:40) は未来 → pending、overdue にも入らない
    ctx = RS.build_status_context(None, runs, now=_jst(2026, 7, 14, 8, 0))
    statuses = {r["slot_id"]: r["status"] for r in ctx["rows"]}
    assert statuses["market_close"] == "pending"
    overdue_ids = {o["slot_id"] for o in ctx["overdue"]}
    assert "market_close" not in overdue_ids


def test_past_slot_missing_is_overdue():
    runs = {"date": "2026-07-14", "slots": {}}
    # 18:00 時点なら全 slot が過去 → 全部 overdue（警告対象）
    ctx = RS.build_status_context(None, runs, now=_jst(2026, 7, 14, 18, 0))
    overdue_ids = {o["slot_id"] for o in ctx["overdue"]}
    assert "market_close" in overdue_ids and "pre_market" in overdue_ids


def test_recovered_status_when_recovery_run():
    runs = {"date": "2026-07-14", "slots": {
        "market_close": {"status": "success", "is_recovery_run": True,
                         "generated_at": _jst(2026, 7, 14, 15, 58).isoformat()},
    }}
    assert RS.slot_display_status(None, runs, "market_close", now=_jst(2026, 7, 14, 16, 0)) == "recovered"


# 21) 土日設定（run_on_weekends のデフォルト True・設定読取り）
def test_schedule_config_defaults_and_weekends():
    cfg = RS.get_schedule_config({})
    assert cfg["run_on_weekends"] is True
    assert cfg["timezone"] == "Asia/Tokyo"
    assert cfg["stale_after_minutes"] == 30
    assert len(cfg["slots"]) == 6
    cfg2 = RS.get_schedule_config({"report_schedule": {"run_on_weekends": False}})
    assert cfg2["run_on_weekends"] is False


# ---------- resolve_report_schedule スクリプト ----------

def test_resolve_script_schedule_generate():
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "resolve_rs", Path(__file__).resolve().parent.parent / "scripts" / "resolve_report_schedule.py"
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    r = mod.resolve({"EVENT_NAME": "schedule", "CRON": "40 6 * * *"}, {})
    assert r == {"slot_id": "market_close", "mode": "generate", "trigger_type": "schedule",
                 "force": False, "recovery": False}


def test_resolve_script_recovery_and_dispatch():
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "resolve_rs2", Path(__file__).resolve().parent.parent / "scripts" / "resolve_report_schedule.py"
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    rec = mod.resolve({"EVENT_NAME": "schedule", "CRON": "55 6 * * *"}, {})
    assert rec["mode"] == "recovery" and rec["slot_id"] == "market_close" and rec["recovery"] is True
    disp = mod.resolve({"EVENT_NAME": "workflow_dispatch", "INPUT_REPORT_SLOT": "auto",
                        "INPUT_FORCE": "true", "INPUT_RECOVERY": "false"}, {})
    assert disp["slot_id"] == "auto" and disp["force"] is True and disp["trigger_type"] == "manual"
    # inputs 無しの dispatch（Cloudflare Worker のワンタップ）でも壊れない
    onetap = mod.resolve({"EVENT_NAME": "workflow_dispatch"}, {})
    assert onetap["slot_id"] == "auto" and onetap["mode"] == "generate"
