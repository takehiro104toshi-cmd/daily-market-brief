#!/usr/bin/env python3
"""GitHub Actions 用: トリガー種別から (slot_id, mode, trigger_type) を解決して GITHUB_OUTPUT へ書く。

巨大な if 文をシェルに書く代わりに、cron 文字列や workflow_dispatch の入力を Python 側で
config.yaml のスロット定義と突き合わせて解決する（JST 基準）。副作用は標準出力と
GITHUB_OUTPUT への追記のみ。

読み取る環境変数（いずれも任意・GitHub Actions が設定）:
  EVENT_NAME          github.event_name（"schedule" / "workflow_dispatch"）
  CRON                github.event.schedule（schedule 実行時の cron 文字列）
  INPUT_REPORT_SLOT   workflow_dispatch の report_slot（"auto" ほか slot_id）
  INPUT_FORCE         workflow_dispatch の force（"true"/"false"）
  INPUT_RECOVERY      workflow_dispatch の recovery（"true"/"false"）
  INPUT_TRIGGER_TYPE  任意の上書き（"one_tap" 等）
  CONFIG_PATH         config.yaml のパス（既定 "config.yaml"）

出力（GITHUB_OUTPUT）:
  slot_id       解決した slot_id（"auto" の場合は main.py 側で直前スロットへ解決）
  mode          "generate" / "recovery"
  trigger_type  "schedule" / "recovery" / "manual" / "one_tap" / "unknown"
  force         "true" / "false"
  recovery      "true" / "false"
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

# リポジトリルートを import パスへ追加（scripts/ から src を読むため）。
ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.analysis import report_schedule as RS  # noqa: E402


def _load_config(path: str) -> dict:
    try:
        from src.utils import load_config
        return load_config(path)
    except Exception:  # noqa: BLE001  config が読めなくても既定スロットで解決できる
        return {}


def resolve(env: dict, config: dict) -> dict:
    event = (env.get("EVENT_NAME") or "").strip()
    cron = (env.get("CRON") or "").strip()
    slot_input = (env.get("INPUT_REPORT_SLOT") or "").strip()
    force = (env.get("INPUT_FORCE") or "false").strip().lower() == "true"
    recovery_input = (env.get("INPUT_RECOVERY") or "false").strip().lower() == "true"
    trigger_override = (env.get("INPUT_TRIGGER_TYPE") or "").strip()

    if event == "schedule" or cron:
        slot_id, mode = RS.resolve_cron(config, cron)
        if slot_id is None:
            # 未知の cron → 直前スロットを生成（安全側）
            return {"slot_id": "auto", "mode": "generate", "trigger_type": "schedule",
                    "force": force, "recovery": False}
        trigger_type = "recovery" if mode == "recovery" else "schedule"
        return {"slot_id": slot_id, "mode": mode, "trigger_type": trigger_type,
                "force": force, "recovery": mode == "recovery"}

    if event == "workflow_dispatch" or slot_input:
        slot_id = slot_input or "auto"
        if slot_id == "auto":
            slot_id = "auto"  # main.py 側で直前スロットへ解決
        mode = "recovery" if recovery_input else "generate"
        trigger_type = trigger_override or "manual"
        return {"slot_id": slot_id, "mode": mode, "trigger_type": trigger_type,
                "force": force, "recovery": recovery_input}

    # 情報が無い（ローカル等）→ 臨時生成
    return {"slot_id": "auto", "mode": "generate", "trigger_type": trigger_override or "unknown",
            "force": force, "recovery": False}


def _write_output(result: dict) -> None:
    lines = [
        f"slot_id={result['slot_id']}",
        f"mode={result['mode']}",
        f"trigger_type={result['trigger_type']}",
        f"force={'true' if result['force'] else 'false'}",
        f"recovery={'true' if result['recovery'] else 'false'}",
    ]
    for line in lines:
        print(line)
    out_path = os.environ.get("GITHUB_OUTPUT")
    if out_path:
        with open(out_path, "a", encoding="utf-8") as f:
            for line in lines:
                f.write(line + "\n")


def main() -> int:
    config = _load_config(os.environ.get("CONFIG_PATH", "config.yaml"))
    result = resolve(dict(os.environ), config)
    _write_output(result)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
