"""P12-A3 — P12 の運用の schedule authority の file I/O（`<p12_root>/authority/schedule.json`。人だけが書く）。

- 読み: 正準 JSON → A1 `AutomationSchedule.from_dict`（未知の鍵 ・digest の不一致は fail closed）。無ければ
  `SCHEMA_INVALID:SCHEDULE_AUTHORITY_MISSING`。byte が正準でなければ `SCHEMA_INVALID:SCHEDULE_AUTHORITY_NOT_CANONICAL`。
- 書き（`operator="human"` だけ）: 既に authority が在れば、新しい版は `supersedes` ＝ 旧の content_digest ・version ＞ 旧 を要求し、
  旧の byte を `authority/history/schedule.<旧 digest>.json` に先に残してから原子的に置換する。自動化の runtime は書かない。
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Optional

from .atomic_files import ensure_directory, ensure_root_subdirectory, read_text_file, replace_atomically
from .failure_codes import AutomationError
from .schedule_model import AutomationSchedule

AUTHORITY_DIRECTORY = "authority"
HISTORY_DIRECTORY = "history"
SCHEDULE_FILE_NAME = "schedule.json"
HUMAN_OPERATOR = "human"


def schedule_file(p12_root: Any) -> Path:
    return Path(p12_root) / AUTHORITY_DIRECTORY / SCHEDULE_FILE_NAME


def _parse(text: str, missing_code: str) -> AutomationSchedule:
    try:
        data = json.loads(text)
    except ValueError:
        raise AutomationError("SCHEMA_INVALID", f"{missing_code}_NOT_JSON") from None
    schedule = AutomationSchedule.from_dict(data)
    if schedule.to_json() + "\n" != text:
        raise AutomationError("SCHEMA_INVALID", f"{missing_code}_NOT_CANONICAL")
    return schedule


def read_schedule_authority(p12_root: Any) -> AutomationSchedule:
    text = read_text_file(schedule_file(p12_root))
    if text is None:
        raise AutomationError("SCHEMA_INVALID", "SCHEDULE_AUTHORITY_MISSING")
    return _parse(text, "SCHEDULE_AUTHORITY")


def read_schedule_authority_if_present(p12_root: Any) -> Optional[AutomationSchedule]:
    text = read_text_file(schedule_file(p12_root))
    return None if text is None else _parse(text, "SCHEDULE_AUTHORITY")


def write_schedule_authority(p12_root: Any, schedule: AutomationSchedule, *, operator: str) -> str:
    """人だけが書く。戻りは書いた authority の content_digest。"""
    if operator != HUMAN_OPERATOR:
        raise AutomationError("SCHEMA_INVALID", "AUTHORITY_WRITE_NOT_HUMAN")
    if not isinstance(schedule, AutomationSchedule):
        raise AutomationError("SCHEMA_INVALID", "SCHEDULE_TYPE")
    target = schedule_file(p12_root)
    existing_text = read_text_file(target)
    directory = ensure_root_subdirectory(p12_root, AUTHORITY_DIRECTORY)
    if existing_text is not None:
        existing = _parse(existing_text, "SCHEDULE_AUTHORITY")
        if existing.content_digest == schedule.content_digest:
            return schedule.content_digest                                             # 同じ内容: 何も書かない
        if existing.schedule_id != schedule.schedule_id:
            raise AutomationError("SCHEMA_INVALID", "SCHEDULE_ID_CHANGED")
        if schedule.supersedes != existing.content_digest:
            raise AutomationError("SCHEMA_INVALID", "SUPERSEDES_REQUIRED")               # 旧版の置換は明示だけ
        if schedule.version <= existing.version:
            raise AutomationError("SCHEMA_INVALID", "VERSION_NOT_INCREASED")
        history = ensure_directory(directory / HISTORY_DIRECTORY)
        replace_atomically(history / f"schedule.{existing.content_digest}.json", existing_text.encode("utf-8"))
    elif schedule.supersedes is not None:
        raise AutomationError("SCHEMA_INVALID", "SUPERSEDES_WITHOUT_PREDECESSOR")
    replace_atomically(target, (schedule.to_json() + "\n").encode("utf-8"))
    return schedule.content_digest


__all__ = ["AUTHORITY_DIRECTORY", "HISTORY_DIRECTORY", "HUMAN_OPERATOR", "SCHEDULE_FILE_NAME", "read_schedule_authority",
           "read_schedule_authority_if_present", "schedule_file", "write_schedule_authority"]
