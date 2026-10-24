"""P12-A5 — Windows Task Scheduler の task の定義（決定論の XML ・名前空間 ・所有の印）。market の意味は持たない: CLI を起こすだけ。

- 名前: `\\Compass\\P12\\<schedule_id>\\<slot_id>`（衝突しない ・所有の印 `P12_OWNED` を Description に持つ）。
- trigger: 週の CalendarTrigger（slot の weekday_mask ・local_time）。StartBoundary は機械の local time（offset 無し）。install は機械の
  time zone が `Tokyo Standard Time` であることを要求する（schedule authority の timezone ＝ Asia/Tokyo）。
- 方針（v1 ・保守的）: 利用者が logon している時だけ（InteractiveToken）・昇格なし（LeastPrivilege）・password を保存しない ・
  StartWhenAvailable=true（遅れた起動は P12 の late window が判定）・MultipleInstancesPolicy=IgnoreNew（重複は A4 の lock が最終の防御）・
  WakeToRun=false ・battery でも走る（networkless の軽い処理）・ExecutionTimeLimit=PT30M ・RunOnlyIfNetworkAvailable=false ・Hidden=false。
- Exec: `<interpreter> -m src.intelligence.automation.run_cli scheduled-run --slot-id ... --private-root ... --p9-root ... --p10-root ...
  --repo-root ... --runtime-root ...`、WorkingDirectory ＝ repo。引数は path だけ（private な payload ・資格情報は無い）。XML は P12 の
  private root の `scheduler/` にだけ置き、安全な出力には名前と digest しか出さない。
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Any, Dict, Mapping, Tuple
from xml.sax.saxutils import escape

from .failure_codes import AutomationError
from .schedule_model import WEEKDAYS, AutomationSchedule, ScheduleSlot

TASK_NAMESPACE = "\\Compass\\P12"
OWNER_MARKER = "P12_OWNED"
TASK_AUTHOR = "P12"
TASK_DEFINITION_VERSION = "p12_task_definition:0.1.0"
REQUIRED_TIMEZONE = "Tokyo Standard Time"
TRIGGER_START_DATE = "2000-01-03"                                                       # 固定の月曜（週の trigger の基準。意味は無い）
EXECUTION_TIME_LIMIT = "PT30M"
CLI_MODULE = "src.intelligence.automation.run_cli"
_DAY_ELEMENTS = {"MON": "Monday", "TUE": "Tuesday", "WED": "Wednesday", "THU": "Thursday", "FRI": "Friday", "SAT": "Saturday",
                 "SUN": "Sunday"}


@dataclass(frozen=True, repr=False)
class SchedulerPaths:
    """install の時に人が渡す private な path（repr に出さない）。"""

    interpreter: str
    repo_root: str
    runtime_root: str
    private_root: str
    p9_root: str
    p10_root: str

    def __post_init__(self) -> None:
        for value in (self.interpreter, self.repo_root, self.runtime_root, self.private_root, self.p9_root, self.p10_root):
            if not isinstance(value, str) or value.strip() == "" or '"' in value or "\n" in value:
                raise AutomationError("SCHEMA_INVALID", "SCHEDULER_PATH")

    def __repr__(self) -> str:
        return "SchedulerPaths(<private>)"


def task_name(schedule_id: str, slot_id: str) -> str:
    return f"{TASK_NAMESPACE}\\{schedule_id}\\{slot_id}"


def owner_description(schedule: AutomationSchedule) -> str:
    return f"{OWNER_MARKER} schedule_digest={schedule.content_digest} version={TASK_DEFINITION_VERSION}"


def _quote(value: str) -> str:
    return f'"{value}"' if " " in value else value


def exec_arguments(slot: ScheduleSlot, paths: SchedulerPaths) -> str:
    parts = ["-m", CLI_MODULE, "scheduled-run", "--slot-id", slot.slot_id, "--private-root", _quote(paths.private_root),
             "--p9-root", _quote(paths.p9_root), "--p10-root", _quote(paths.p10_root), "--repo-root", _quote(paths.repo_root),
             "--runtime-root", _quote(paths.runtime_root)]
    return " ".join(parts)


def task_xml(schedule: AutomationSchedule, slot: ScheduleSlot, paths: SchedulerPaths) -> bytes:
    """決定論の Task Scheduler XML（UTF-16 LE ・BOM ・CRLF。Windows の export と同じ形）。"""
    days = "".join(f"<{_DAY_ELEMENTS[d]} />" for d in WEEKDAYS if d in slot.weekday_mask)
    lines = [
        '<?xml version="1.0" encoding="UTF-16"?>',
        '<Task version="1.4" xmlns="http://schemas.microsoft.com/windows/2004/02/mit/task">',
        "  <RegistrationInfo>",
        f"    <Author>{TASK_AUTHOR}</Author>",
        f"    <Description>{escape(owner_description(schedule))}</Description>",
        f"    <URI>{escape(task_name(schedule.schedule_id, slot.slot_id))}</URI>",
        "  </RegistrationInfo>",
        "  <Triggers>",
        "    <CalendarTrigger>",
        f"      <StartBoundary>{TRIGGER_START_DATE}T{slot.local_time}:00</StartBoundary>",
        f"      <Enabled>{'true' if slot.enabled and schedule.enabled else 'false'}</Enabled>",
        "      <ScheduleByWeek>",
        f"        <DaysOfWeek>{days}</DaysOfWeek>",
        "        <WeeksInterval>1</WeeksInterval>",
        "      </ScheduleByWeek>",
        "    </CalendarTrigger>",
        "  </Triggers>",
        "  <Principals>",
        '    <Principal id="Author">',
        "      <LogonType>InteractiveToken</LogonType>",
        "      <RunLevel>LeastPrivilege</RunLevel>",
        "    </Principal>",
        "  </Principals>",
        "  <Settings>",
        "    <MultipleInstancesPolicy>IgnoreNew</MultipleInstancesPolicy>",
        "    <DisallowStartIfOnBatteries>false</DisallowStartIfOnBatteries>",
        "    <StopIfGoingOnBatteries>false</StopIfGoingOnBatteries>",
        "    <AllowHardTerminate>true</AllowHardTerminate>",
        "    <StartWhenAvailable>true</StartWhenAvailable>",
        "    <RunOnlyIfNetworkAvailable>false</RunOnlyIfNetworkAvailable>",
        "    <AllowStartOnDemand>true</AllowStartOnDemand>",
        "    <Enabled>true</Enabled>",
        "    <Hidden>false</Hidden>",
        "    <RunOnlyIfIdle>false</RunOnlyIfIdle>",
        "    <WakeToRun>false</WakeToRun>",
        f"    <ExecutionTimeLimit>{EXECUTION_TIME_LIMIT}</ExecutionTimeLimit>",
        "    <Priority>7</Priority>",
        "  </Settings>",
        '  <Actions Context="Author">',
        "    <Exec>",
        f"      <Command>{escape(paths.interpreter)}</Command>",
        f"      <Arguments>{escape(exec_arguments(slot, paths))}</Arguments>",
        f"      <WorkingDirectory>{escape(paths.repo_root)}</WorkingDirectory>",
        "    </Exec>",
        "  </Actions>",
        "</Task>",
    ]
    return ("\r\n".join(lines) + "\r\n").encode("utf-16")


@dataclass(frozen=True)
class TaskDefinition:
    task_name: str
    slot_id: str
    enabled: bool
    xml: bytes

    @property
    def xml_digest(self) -> str:
        return hashlib.sha256(self.xml).hexdigest()

    def to_safe_dict(self) -> Dict[str, Any]:
        return {"task_name": self.task_name, "slot_id": self.slot_id, "enabled": self.enabled, "xml_digest": self.xml_digest}


def task_definitions(schedule: AutomationSchedule, paths: SchedulerPaths) -> Tuple[TaskDefinition, ...]:
    """schedule の全 slot の定義（slot_id の順）。無効な slot も定義は作る（trigger は無効）。"""
    if not isinstance(schedule, AutomationSchedule) or not isinstance(paths, SchedulerPaths):
        raise AutomationError("SCHEMA_INVALID", "TASK_DEFINITION_INPUT")
    return tuple(TaskDefinition(task_name=task_name(schedule.schedule_id, slot.slot_id), slot_id=slot.slot_id,
                                enabled=schedule.enabled and slot.enabled, xml=task_xml(schedule, slot, paths)) for slot in schedule.slots)


def owned_task_names(schedule: AutomationSchedule) -> Tuple[str, ...]:
    return tuple(task_name(schedule.schedule_id, slot.slot_id) for slot in schedule.slots)


def xml_is_owned(xml_text: str, schedule: AutomationSchedule, name: str) -> bool:
    return OWNER_MARKER in xml_text and f"<URI>{escape(name)}</URI>" in xml_text and f"<Author>{TASK_AUTHOR}</Author>" in xml_text


__all__ = ["CLI_MODULE", "EXECUTION_TIME_LIMIT", "OWNER_MARKER", "REQUIRED_TIMEZONE", "TASK_AUTHOR", "TASK_DEFINITION_VERSION",
           "TASK_NAMESPACE", "TRIGGER_START_DATE", "SchedulerPaths", "TaskDefinition", "exec_arguments", "owned_task_names",
           "owner_description", "task_definitions", "task_name", "task_xml", "xml_is_owned"]
