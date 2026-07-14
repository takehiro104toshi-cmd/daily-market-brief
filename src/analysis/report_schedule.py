"""Report Schedule & Reliability Engine（v4.x）— 1日6回の自動生成を信頼性高く運用する基盤。

GitHub Actions の schedule cron は UTC 基準だが、レポート日付・保存日付・slot 判定は
すべて Asia/Tokyo（JST）基準で行う（cron の時刻から JST 日付を推測しない）。

このモジュールは「純粋なロジック」だけを提供する（副作用は run-record の読み書きのみ）:
  - JST/UTC の時刻変換、通常 cron と回復 cron の生成
  - cron 文字列 → (slot_id, mode) の対応付け
  - 実行時刻 → 直前 slot の解決（--report-slot auto 用）
  - 実行記録（data/report_runs/YYYY-MM-DD.json）の atomic な読み書き
  - 同一日・同一 slot の二重生成防止（success/running/failed/stale 判定）
  - HTML 表示用のスロット状態（success/running/pending/failed/recovered/stale/skipped）

新規ニュース取得・生成AI・外部APIは一切使わない。既存動作へは影響しない
（main.py から明示的に呼ばれた時のみ機能する）。
"""
from __future__ import annotations

import json
import os
import tempfile
from datetime import datetime, time as dtime, timedelta
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import pytz

# 既定のスロット定義（config.yaml の report_schedule.slots が無い場合のフォールバック）。
DEFAULT_SLOTS: List[Dict[str, str]] = [
    {"id": "pre_market", "time": "07:30", "label": "寄り前レポート"},
    {"id": "market_open", "time": "09:10", "label": "寄り付き確認"},
    {"id": "morning_close", "time": "11:30", "label": "前場終了レポート"},
    {"id": "afternoon_open", "time": "12:40", "label": "後場開始確認"},
    {"id": "market_close", "time": "15:40", "label": "大引けレポート"},
    {"id": "evening", "time": "17:20", "label": "夕方総括"},
]

DEFAULT_TIMEZONE = "Asia/Tokyo"
DEFAULT_RUNS_DIR = "data/report_runs"
DEFAULT_HISTORY_DIR = "output/history"
DEFAULT_STALE_AFTER_MINUTES = 30
DEFAULT_RECOVERY_OFFSET_MINUTES = 15
DEFAULT_MAX_RETRY_COUNT = 2
DEFAULT_RETRY_WAIT_SECONDS = 120

VALID_TRIGGER_TYPES = ("schedule", "manual", "one_tap", "recovery", "unknown")


# ---------- 設定の取り出し（デフォルト補完） ----------

def get_schedule_config(config: Optional[dict]) -> dict:
    """config.yaml の report_schedule ブロックを、デフォルト補完つきで返す。"""
    cfg = (config or {}).get("report_schedule", {}) or {}
    return {
        "enabled": cfg.get("enabled", True),
        "timezone": cfg.get("timezone", DEFAULT_TIMEZONE),
        "run_on_weekends": cfg.get("run_on_weekends", True),
        "run_on_japanese_holidays": cfg.get("run_on_japanese_holidays", True),
        "archive_reports": cfg.get("archive_reports", True),
        "recovery_enabled": cfg.get("recovery_enabled", True),
        "max_retry_count": cfg.get("max_retry_count", DEFAULT_MAX_RETRY_COUNT),
        "retry_wait_seconds": cfg.get("retry_wait_seconds", DEFAULT_RETRY_WAIT_SECONDS),
        "stale_after_minutes": cfg.get("stale_after_minutes", DEFAULT_STALE_AFTER_MINUTES),
        "recovery_offset_minutes": cfg.get("recovery_offset_minutes", DEFAULT_RECOVERY_OFFSET_MINUTES),
        "runs_dir": cfg.get("runs_dir", DEFAULT_RUNS_DIR),
        "history_dir": cfg.get("history_dir", DEFAULT_HISTORY_DIR),
        "slots": cfg.get("slots") or DEFAULT_SLOTS,
    }


def get_slots(config: Optional[dict]) -> List[Dict[str, str]]:
    return list(get_schedule_config(config)["slots"])


def get_timezone(config: Optional[dict]) -> pytz.BaseTzInfo:
    return pytz.timezone(get_schedule_config(config)["timezone"])


def slot_by_id(config: Optional[dict], slot_id: str) -> Optional[Dict[str, str]]:
    for s in get_slots(config):
        if s.get("id") == slot_id:
            return s
    return None


def slot_label(config: Optional[dict], slot_id: str) -> str:
    s = slot_by_id(config, slot_id)
    return s.get("label", "") if s else ""


# ---------- 時刻ユーティリティ（JST 基準） ----------

def parse_hm(hhmm: str) -> Tuple[int, int]:
    h, m = hhmm.strip().split(":")
    return int(h), int(m)


def now_jst(config: Optional[dict] = None, now: Optional[datetime] = None) -> datetime:
    tz = get_timezone(config)
    if now is None:
        return datetime.now(tz)
    if now.tzinfo is None:
        return tz.localize(now)
    return now.astimezone(tz)


def jst_hm_to_utc_hm(h: int, m: int) -> Tuple[int, int]:
    """JST の (時, 分) を UTC の (時, 分) へ変換する。JST = UTC + 9h。"""
    total = (h - 9) * 60 + m
    total %= 24 * 60
    return total // 60, total % 60


def _cron_key(minute: int, hour: int) -> str:
    return f"{minute} {hour}"


def normal_cron_for_slot(slot: Dict[str, str]) -> str:
    h, m = parse_hm(slot["time"])
    uh, um = jst_hm_to_utc_hm(h, m)
    return f"{um} {uh} * * *"


def recovery_cron_for_slot(slot: Dict[str, str], offset_minutes: int = DEFAULT_RECOVERY_OFFSET_MINUTES) -> str:
    h, m = parse_hm(slot["time"])
    total = h * 60 + m + offset_minutes
    h2, m2 = (total // 60) % 24, total % 60
    uh, um = jst_hm_to_utc_hm(h2, m2)
    return f"{um} {uh} * * *"


def build_cron_slot_map(config: Optional[dict]) -> Dict[str, Dict[str, str]]:
    """cron 文字列（"M H" で正規化）→ {slot_id, mode} の対応表を作る。

    mode は "generate"（通常実行）/ "recovery"（欠損回復チェック）。
    """
    sched = get_schedule_config(config)
    offset = sched["recovery_offset_minutes"]
    out: Dict[str, Dict[str, str]] = {}
    for slot in sched["slots"]:
        h, m = parse_hm(slot["time"])
        uh, um = jst_hm_to_utc_hm(h, m)
        out[_cron_key(um, uh)] = {"slot_id": slot["id"], "mode": "generate"}
    for slot in sched["slots"]:
        h, m = parse_hm(slot["time"])
        total = h * 60 + m + offset
        h2, m2 = (total // 60) % 24, total % 60
        uh, um = jst_hm_to_utc_hm(h2, m2)
        out[_cron_key(um, uh)] = {"slot_id": slot["id"], "mode": "recovery"}
    return out


def resolve_cron(config: Optional[dict], cron_str: str) -> Tuple[Optional[str], Optional[str]]:
    """GitHub Actions が渡す cron 文字列（例 "30 22 * * *"）から (slot_id, mode) を返す。

    未知の cron なら (None, None)。分・時フィールドだけで照合する。
    """
    if not cron_str:
        return None, None
    parts = cron_str.split()
    if len(parts) < 2:
        return None, None
    key = _cron_key(int(parts[0]), int(parts[1]))
    hit = build_cron_slot_map(config).get(key)
    if hit is None:
        return None, None
    return hit["slot_id"], hit["mode"]


def scheduled_datetime(config: Optional[dict], slot_id: str, ref_jst: datetime) -> Optional[datetime]:
    """ref_jst の日付における slot の予定時刻（JST aware datetime）を返す。"""
    slot = slot_by_id(config, slot_id)
    if slot is None:
        return None
    h, m = parse_hm(slot["time"])
    tz = get_timezone(config)
    ref = now_jst(config, ref_jst)
    return tz.localize(datetime.combine(ref.date(), dtime(h, m)))


def resolve_auto_slot(config: Optional[dict], now: Optional[datetime] = None) -> Optional[str]:
    """手動/ワンタップ実行（--report-slot auto）で、現在 JST 時刻に最も近い「直前 slot」を返す。

    現在時刻より前に予定 slot が1つも無い（早朝など）場合は None（＝臨時レポート扱い）。
    """
    cur = now_jst(config, now)
    cur_minutes = cur.hour * 60 + cur.minute
    best: Optional[Tuple[int, str]] = None
    for slot in get_slots(config):
        h, m = parse_hm(slot["time"])
        sm = h * 60 + m
        if sm <= cur_minutes and (best is None or sm > best[0]):
            best = (sm, slot["id"])
    return best[1] if best else None


# ---------- 実行記録（data/report_runs/YYYY-MM-DD.json） ----------

def runs_dir(config: Optional[dict]) -> str:
    return get_schedule_config(config)["runs_dir"]


def runs_path(config: Optional[dict], date_key: str, base_dir: Optional[Path] = None) -> Path:
    d = Path(runs_dir(config))
    if base_dir is not None:
        d = base_dir / d
    return d / f"{date_key}.json"


def new_runs_doc(date_key: str, tz_name: str = DEFAULT_TIMEZONE) -> dict:
    return {"date": date_key, "timezone": tz_name, "slots": {}}


def load_runs(path: Path, date_key: str = "", tz_name: str = DEFAULT_TIMEZONE) -> dict:
    """実行記録 JSON を読み込む。存在しない/壊れている場合は空の記録を返す（例外を投げない）。"""
    try:
        raw = Path(path).read_text(encoding="utf-8")
        data = json.loads(raw)
        if not isinstance(data, dict) or "slots" not in data or not isinstance(data["slots"], dict):
            raise ValueError("invalid runs document")
        return data
    except (FileNotFoundError, ValueError, json.JSONDecodeError, OSError):
        return new_runs_doc(date_key or Path(path).stem, tz_name)


def save_runs_atomic(path: Path, data: dict) -> None:
    """一時ファイルへ書き込んでから os.replace で atomic に差し替える（JSON 破損防止）。"""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=".runs-", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.remove(tmp)


def get_slot_record(runs: dict, slot_id: str) -> Optional[dict]:
    return (runs.get("slots") or {}).get(slot_id)


def upsert_slot_record(runs: dict, slot_id: str, record: dict) -> dict:
    """同一日・同一 slot の記録を安全に更新（マージ）する。"""
    runs.setdefault("slots", {})
    existing = runs["slots"].get(slot_id, {})
    merged = dict(existing)
    merged.update({k: v for k, v in record.items() if v is not None})
    runs["slots"][slot_id] = merged
    return merged


# ---------- 二重生成防止・stale 判定 ----------

def _parse_iso(value: Optional[str]) -> Optional[datetime]:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def is_stale(record: Optional[dict], now: datetime, stale_after_minutes: int) -> bool:
    """status=running のまま stale_after_minutes 以上経過していれば stale。"""
    if not record or record.get("status") != "running":
        return False
    started = _parse_iso(record.get("started_at") or record.get("generated_at"))
    if started is None:
        return True  # 開始時刻不明で running のまま → 回復可能とみなす
    if started.tzinfo is None:
        started = now_jst(None, started)
    return (now - started) >= timedelta(minutes=stale_after_minutes)


def decide_action(
    config: Optional[dict],
    runs: dict,
    slot_id: Optional[str],
    force: bool = False,
    is_recovery: bool = False,
    now: Optional[datetime] = None,
) -> Tuple[bool, str]:
    """このスロットを（再）生成すべきか判定する。戻り値 (should_generate, reason)。

    ルール:
      - slot_id が無い（manual/one_tap の臨時）→ 常に生成（従来どおり最新レポート）。
      - --force → 常に生成。
      - recovery: success はスキップ（no-op）。missing/failed/stale のみ生成。
      - 通常: success はスキップ。running かつ非 stale はスキップ。
              failed / missing / stale の running は生成。
    """
    cur = now_jst(config, now)
    stale_after = get_schedule_config(config)["stale_after_minutes"]
    if not slot_id:
        return True, "adhoc_no_slot"
    if force:
        return True, "forced"
    rec = get_slot_record(runs, slot_id)
    status = rec.get("status") if rec else "missing"
    stale = is_stale(rec, cur, stale_after)

    if status == "success":
        return False, "already_success"
    if status == "running":
        if stale:
            return True, "stale_running"
        return False, "running_in_progress"
    if status == "failed":
        return True, "retry_failed"
    # missing
    if is_recovery:
        return True, "recovery_missing"
    return True, "generate_missing"


# ---------- 記録の開始/確定ヘルパー ----------

def record_start(
    runs: dict,
    slot_id: str,
    scheduled_time: str = "",
    trigger_type: str = "unknown",
    is_recovery_run: bool = False,
    now: Optional[datetime] = None,
    workflow_run_id: str = "",
) -> dict:
    cur = now_jst(None, now)
    prev = get_slot_record(runs, slot_id) or {}
    return upsert_slot_record(
        runs,
        slot_id,
        {
            "status": "running",
            "scheduled_time": scheduled_time or prev.get("scheduled_time", ""),
            "started_at": cur.isoformat(),
            "data_fetch_started_at": cur.isoformat(),
            "trigger_type": trigger_type,
            "is_recovery_run": is_recovery_run,
            "workflow_run_id": workflow_run_id or prev.get("workflow_run_id", ""),
        },
    )


def record_result(
    runs: dict,
    slot_id: str,
    status: str,
    now: Optional[datetime] = None,
    meta: Optional[dict] = None,
) -> dict:
    """status は "success" / "failed"。meta に生成メタデータをマージする。"""
    cur = now_jst(None, now)
    rec = get_slot_record(runs, slot_id) or {}
    retry_count = rec.get("retry_count", 0)
    if status == "failed":
        retry_count = int(retry_count) + 1 if rec.get("status") == "running" else int(retry_count)
    payload = {
        "status": status,
        "generated_at": cur.isoformat(),
        "report_build_completed_at": cur.isoformat(),
        "retry_count": retry_count,
    }
    if meta:
        payload.update(meta)
    return upsert_slot_record(runs, slot_id, payload)


# ---------- HTML 表示用: スロット状態の算出 ----------

def slot_display_status(config: Optional[dict], runs: dict, slot_id: str, now: Optional[datetime] = None) -> str:
    """1スロットの表示ステータスを返す。

    success / running / pending / failed / recovered / stale / skipped のいずれか。
    予定時刻より前で未実行なら pending（failed 扱いにしない）。
    """
    sched = get_schedule_config(config)
    cur = now_jst(config, now)
    rec = get_slot_record(runs, slot_id)
    if rec is None:
        return "pending"
    status = rec.get("status", "pending")
    if status == "success":
        return "recovered" if rec.get("is_recovery_run") else "success"
    if status == "running":
        return "stale" if is_stale(rec, cur, sched["stale_after_minutes"]) else "running"
    if status in ("failed", "skipped", "pending"):
        return status
    return "pending"


def build_status_context(config: Optional[dict], runs: dict, now: Optional[datetime] = None,
                         current_slot_id: Optional[str] = None) -> dict:
    """HTML の「本日の自動生成状況」カード用の表示コンテキストを組み立てる。"""
    cur = now_jst(config, now)
    sched = get_schedule_config(config)
    rows = []
    overdue = []
    for slot in sched["slots"]:
        sid = slot["id"]
        rec = get_slot_record(runs, sid) or {}
        st = slot_display_status(config, runs, sid, cur)
        sdt = scheduled_datetime(config, sid, cur)
        is_future = sdt is not None and cur < sdt
        # 予定時刻を過ぎても success/recovered が無い → 警告対象（未来スロットは対象外）
        if not is_future and st not in ("success", "recovered", "running"):
            overdue.append({"slot_id": sid, "label": slot["label"], "time": slot["time"]})
        gen_at = rec.get("generated_at", "")
        gen_hm = ""
        gdt = _parse_iso(gen_at)
        if gdt is not None:
            gen_hm = now_jst(config, gdt).strftime("%H:%M")
        rows.append({
            "slot_id": sid,
            "time": slot["time"],
            "label": slot["label"],
            "status": st,
            "generated_hm": gen_hm,
            "is_future": is_future,
        })
    current = None
    if current_slot_id:
        crec = get_slot_record(runs, current_slot_id) or {}
        cslot = slot_by_id(config, current_slot_id) or {}
        current = {
            "slot_id": current_slot_id,
            "label": cslot.get("label", ""),
            "time": cslot.get("time", ""),
            "generated_at": crec.get("generated_at", ""),
            "trigger_type": crec.get("trigger_type", ""),
            "is_recovery_run": crec.get("is_recovery_run", False),
        }
    return {
        "date": runs.get("date", cur.strftime("%Y-%m-%d")),
        "now_hm": cur.strftime("%H:%M"),
        "rows": rows,
        "overdue": overdue,
        "current": current,
        "recovery_offset_minutes": sched["recovery_offset_minutes"],
    }
