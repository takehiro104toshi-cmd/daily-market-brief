"""P12-A5 — Task Scheduler との狭い adapter（本番は `schtasks.exe` ・`tzutil` を引数の list で呼ぶ。test は InMemoryTaskScheduler）。

- `register(name, xml_file)`: `schtasks /Create /TN <name> /XML <file> /F`。`delete(name)`: `schtasks /Delete /TN <name> /F`。
  `query(name)`: `schtasks /Query /TN <name> /XML` の XML（所有の印の照合に使う）と `/FO CSV /V` の Status ・Last Result。
  `system_timezone()`: `tzutil /g`。全て shell 無し ・timeout ・stdout ／ stderr は sanitize（返すのは真偽 ・整数 ・XML の文だけ。生の
  出力 ・path ・user 名は安全な結果に出さない）。
- 失敗は `AutomationError("STEP_FAILED", "SCHEDULER_<OP>")`。Windows 以外では本番 adapter は `SCHEDULER_UNAVAILABLE`。
"""
from __future__ import annotations

import csv
import io
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Optional

from .failure_codes import AutomationError

SCHTASKS_TIMEOUT_SECONDS = 60


@dataclass(frozen=True)
class TaskQuery:
    present: bool
    enabled: Optional[bool]
    last_result: Optional[int]
    xml_text: Optional[str]

    def to_safe_dict(self) -> Dict[str, Any]:
        return {"present": self.present, "enabled": self.enabled, "last_result": self.last_result}


class TaskSchedulerAdapter:
    def system_timezone(self) -> Optional[str]:
        raise NotImplementedError

    def register(self, name: str, xml_file: Path) -> None:
        raise NotImplementedError

    def delete(self, name: str) -> None:
        raise NotImplementedError

    def query(self, name: str) -> TaskQuery:
        raise NotImplementedError


def _run(argv: list) -> Optional[bytes]:
    try:
        completed = subprocess.run(argv, capture_output=True, check=False, timeout=SCHTASKS_TIMEOUT_SECONDS)
    except (OSError, subprocess.SubprocessError):
        return None
    return completed.stdout if completed.returncode == 0 else None


class SchtasksAdapter(TaskSchedulerAdapter):                                            # pragma: no cover - Windows だけ（A6 で実機）
    def _require_windows(self) -> None:
        if sys.platform != "win32":
            raise AutomationError("STEP_FAILED", "SCHEDULER_UNAVAILABLE")

    def system_timezone(self) -> Optional[str]:
        self._require_windows()
        out = _run(["tzutil", "/g"])
        if out is None:
            return None
        text = out.decode("utf-8", "replace").strip()
        return text if 0 < len(text) < 80 and text.isprintable() else None

    def register(self, name: str, xml_file: Path) -> None:
        self._require_windows()
        if _run(["schtasks", "/Create", "/TN", name, "/XML", str(xml_file), "/F"]) is None:
            raise AutomationError("STEP_FAILED", "SCHEDULER_CREATE")

    def delete(self, name: str) -> None:
        self._require_windows()
        if _run(["schtasks", "/Delete", "/TN", name, "/F"]) is None:
            raise AutomationError("STEP_FAILED", "SCHEDULER_DELETE")

    def query(self, name: str) -> TaskQuery:
        self._require_windows()
        xml_out = _run(["schtasks", "/Query", "/TN", name, "/XML"])
        if xml_out is None:
            return TaskQuery(present=False, enabled=None, last_result=None, xml_text=None)
        try:
            xml_text = xml_out.decode("utf-16") if xml_out[:2] in (b"\xff\xfe", b"\xfe\xff") else xml_out.decode("utf-8", "replace")
        except UnicodeDecodeError:
            xml_text = ""
        enabled: Optional[bool] = None
        last_result: Optional[int] = None
        csv_out = _run(["schtasks", "/Query", "/TN", name, "/FO", "CSV", "/V"])
        if csv_out is not None:
            try:
                rows = list(csv.DictReader(io.StringIO(csv_out.decode("utf-8", "replace"))))
            except csv.Error:
                rows = []
            for row in rows:
                state = (row.get("Scheduled Task State") or "").strip().lower()
                if state in ("enabled", "disabled"):
                    enabled = state == "enabled"
                raw = (row.get("Last Result") or "").strip()
                if raw.lstrip("-").isdigit():
                    last_result = int(raw)
        return TaskQuery(present=True, enabled=enabled, last_result=last_result, xml_text=xml_text)


class InMemoryTaskScheduler(TaskSchedulerAdapter):
    """決定論の test double（Windows 不要）。登録した XML と呼び出しの履歴を持つ。"""

    def __init__(self, timezone_name: Optional[str] = "Tokyo Standard Time") -> None:
        self.timezone_name = timezone_name
        self.tasks: Dict[str, Dict[str, Any]] = {}
        self.calls: list = []

    def system_timezone(self) -> Optional[str]:
        self.calls.append(("timezone",))
        return self.timezone_name

    def register(self, name: str, xml_file: Path) -> None:
        self.calls.append(("register", name))
        xml_text = Path(xml_file).read_bytes().decode("utf-16")
        self.tasks[name] = {"xml": xml_text, "enabled": "<Enabled>true</Enabled>" in xml_text.split("<Settings>")[0], "last_result": None}

    def delete(self, name: str) -> None:
        self.calls.append(("delete", name))
        if name not in self.tasks:
            raise AutomationError("STEP_FAILED", "SCHEDULER_DELETE")
        del self.tasks[name]

    def query(self, name: str) -> TaskQuery:
        self.calls.append(("query", name))
        task = self.tasks.get(name)
        if task is None:
            return TaskQuery(present=False, enabled=None, last_result=None, xml_text=None)
        return TaskQuery(present=True, enabled=task["enabled"], last_result=task["last_result"], xml_text=task["xml"])


__all__ = ["SCHTASKS_TIMEOUT_SECONDS", "InMemoryTaskScheduler", "SchtasksAdapter", "TaskQuery", "TaskSchedulerAdapter"]
