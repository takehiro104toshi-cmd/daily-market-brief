"""P12-A5 — Task Scheduler への install ／ remove ／ status（人だけ ・計画が先 ・所有の印を照合 ・P12 の名前空間だけ）。

- `plan_install`: 検証済みの schedule authority（`authority/schedule.json`）と install の path から全 slot の定義を作り、安全な計画
  （task 名 ・slot ・enabled ・XML の digest）を返す。機械の time zone が `Tokyo Standard Time` でなければ拒む。
- `install`: 計画の XML を `<p12_root>/scheduler/` に置き（private）、adapter で登録する。`--apply` が無ければ計画だけ。
- `remove`: authority から導いた P12 の名前だけを、query の XML に所有の印が在る時だけ削除する（wildcard ・無関係な task は触らない）。
- `status`: 期待する task 数 ・登録済みの数 ・enabled の slot 数 ・最後の結果 code ・recovery_required（ledger の分類）。非 authority。
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

import os

from .atomic_files import ensure_root_subdirectory
from .failure_codes import AutomationError
from .ledger_store import LedgerStore
from .schedule_authority import HUMAN_OPERATOR, read_schedule_authority
from .task_definition import REQUIRED_TIMEZONE, SchedulerPaths, TaskDefinition, owned_task_names, task_definitions, xml_is_owned
from .task_scheduler_adapter import TaskSchedulerAdapter

SCHEDULER_DIRECTORY = "scheduler"


@dataclass(frozen=True)
class InstallPlan:
    schedule_id: str
    schedule_digest: str
    definitions: Tuple[TaskDefinition, ...]

    def to_safe_dict(self) -> Dict[str, Any]:
        return {"schedule_id": self.schedule_id, "schedule_digest": self.schedule_digest,
                "tasks": [d.to_safe_dict() for d in self.definitions]}


def plan_install(p12_root: Any, paths: SchedulerPaths, adapter: TaskSchedulerAdapter) -> InstallPlan:
    schedule = read_schedule_authority(p12_root)
    zone = adapter.system_timezone()
    if zone != REQUIRED_TIMEZONE:
        raise AutomationError("SCHEMA_INVALID", "SYSTEM_TIMEZONE_NOT_TOKYO")                # local time の trigger は Tokyo の機械だけ
    return InstallPlan(schedule_id=schedule.schedule_id, schedule_digest=schedule.content_digest,
                       definitions=task_definitions(schedule, paths))


def install_tasks(p12_root: Any, plan: InstallPlan, adapter: TaskSchedulerAdapter, *, operator: str) -> Dict[str, Any]:
    if operator != HUMAN_OPERATOR:
        raise AutomationError("SCHEMA_INVALID", "AUTHORITY_WRITE_NOT_HUMAN")
    schedule = read_schedule_authority(p12_root)
    for definition in plan.definitions:                                                  # 同名で所有の印の無い task があれば触らない
        existing = adapter.query(definition.task_name)
        if existing.present and not xml_is_owned(existing.xml_text or "", schedule, definition.task_name):
            raise AutomationError("DUPLICATE_INVOCATION", "TASK_NOT_OWNED")
    directory = ensure_root_subdirectory(p12_root, SCHEDULER_DIRECTORY)
    registered = []
    for definition in plan.definitions:
        xml_file = directory / f"{plan.schedule_id}.{definition.slot_id}.xml"
        _write_xml(xml_file, definition.xml)
        adapter.register(definition.task_name, xml_file)
        registered.append(definition.task_name)
    return {"installed": True, "task_count": len(registered), "tasks": registered}


def _write_xml(target: Path, xml: bytes) -> None:
    try:
        temporary = target.with_name(target.name + ".tmp")
        with open(temporary, "wb") as handle:
            handle.write(xml)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, target)
    except OSError:
        raise AutomationError("STEP_FAILED", "SCHEDULER_XML_IO") from None


def remove_tasks(p12_root: Any, adapter: TaskSchedulerAdapter, *, operator: str, apply: bool) -> Dict[str, Any]:
    if operator != HUMAN_OPERATOR:
        raise AutomationError("SCHEMA_INVALID", "AUTHORITY_WRITE_NOT_HUMAN")
    schedule = read_schedule_authority(p12_root)
    removed, skipped, foreign = [], [], []
    for name in owned_task_names(schedule):
        query = adapter.query(name)
        if not query.present:
            skipped.append(name)
            continue
        if not xml_is_owned(query.xml_text or "", schedule, name):
            foreign.append(name)                                                         # 同じ名前でも所有の印が無ければ触らない
            continue
        if apply:
            adapter.delete(name)
        removed.append(name)
    return {"applied": apply, "removed": removed, "absent": skipped, "not_owned": foreign}


def scheduler_status(p12_root: Any, adapter: TaskSchedulerAdapter) -> Dict[str, Any]:
    """scheduler の状態の安全な projection（非 authority。path ・user 名 ・command line は無い）。"""
    schedule = read_schedule_authority(p12_root)
    expected = owned_task_names(schedule)
    installed, enabled_tasks, results, foreign = 0, 0, [], 0
    for name in expected:
        query = adapter.query(name)
        if not query.present:
            continue
        if not xml_is_owned(query.xml_text or "", schedule, name):
            foreign += 1
            continue
        installed += 1
        enabled_tasks += 1 if query.enabled else 0
        if query.last_result is not None:
            results.append(query.last_result)
    recovery_required: Optional[bool]
    try:
        state = LedgerStore(p12_root).open_verified(allow_stale_checkpoint=True)
        recovery_required = state.checkpoint_class != "CHECKPOINT_OK" or any(
            s.value in ("PLANNED", "RUNNING") for s in state.run_states.values())
    except AutomationError:
        recovery_required = True
    return {"scheduler_installed": installed == len(expected) and installed > 0, "expected_task_count": len(expected),
            "installed_task_count": installed, "enabled_task_count": enabled_tasks, "not_owned_count": foreign,
            "enabled_slot_count": sum(1 for s in schedule.slots if s.enabled and schedule.enabled),
            "last_scheduler_result_code": max(results) if results else None, "recovery_required": recovery_required}


__all__ = ["SCHEDULER_DIRECTORY", "InstallPlan", "install_tasks", "plan_install", "remove_tasks", "scheduler_status"]
