"""P12-A4 — process の生存 ・identity ・起動の token の探り（lock の stale の判定に使う。stdlib だけ ・出力は sanitize）。

- `ProcessProbe.is_alive(pid)`: True ／ False ／ None（分からない）。POSIX は `os.kill(pid, 0)`（EPERM も「生きている」）。Windows は
  `tasklist /FI "PID eq <pid>" /FO CSV /NH` を引数の list で呼び、出力に pid の列が在るかだけを見る（文は捨てる）。
- `ProcessProbe.identity(pid)`: その process の起動の identity（PID の再利用の検出）。Linux は `/proc/<pid>/stat` の starttime、
  Windows は PowerShell の CIM `CreationDate` を sanitize（数字だけ）して使う。得られなければ None（provenance 不明 ＝ fail closed）。
- `ProcessProbe.boot_marker()`: 機械の起動の token（Linux は `/proc/sys/kernel/random/boot_id`）。無ければ None。
- 全て sha256 で畳んで記録する（生の値 ・command line ・user 名は記録しない）。test は `StaticProbe` で差し替える。
"""
from __future__ import annotations

import hashlib
import os
import re
import subprocess
import sys
from typing import Any, Dict, Optional

PROBE_TIMEOUT_SECONDS = 15
_DIGITS = re.compile(r"\d+")


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


class ProcessProbe:
    """OS の process の探り。戻りは digest か None（分からない）。"""

    def is_alive(self, pid: int) -> Optional[bool]:
        if not isinstance(pid, int) or isinstance(pid, bool) or pid <= 0:
            return None
        if sys.platform == "win32":
            return self._windows_alive(pid)
        try:
            os.kill(pid, 0)
            return True
        except ProcessLookupError:
            return False
        except PermissionError:
            return True
        except OSError:
            return None

    def identity(self, pid: int) -> Optional[str]:
        if not isinstance(pid, int) or isinstance(pid, bool) or pid <= 0:
            return None
        if sys.platform == "win32":
            return self._windows_identity(pid)
        try:
            with open(f"/proc/{pid}/stat", "rb") as handle:
                stat_text = handle.read().decode("ascii", "replace")
        except OSError:
            return None
        fields = stat_text.rsplit(")", 1)[-1].split()
        if len(fields) < 20:
            return None
        return _digest(f"{pid}:{fields[19]}")                                          # 22 番目の欄 ＝ starttime（process 名の後）

    def boot_marker(self) -> Optional[str]:
        try:
            with open("/proc/sys/kernel/random/boot_id", "rb") as handle:
                return _digest(handle.read().decode("ascii", "replace").strip())
        except OSError:
            return None

    def _windows_alive(self, pid: int) -> Optional[bool]:                              # pragma: no cover - Windows だけ（A6 で実機）
        try:
            completed = subprocess.run(["tasklist", "/FI", f"PID eq {pid}", "/FO", "CSV", "/NH"], capture_output=True,
                                       timeout=PROBE_TIMEOUT_SECONDS, check=False)
        except (OSError, subprocess.SubprocessError):
            return None
        if completed.returncode != 0:
            return None
        text = completed.stdout.decode("utf-8", "replace")
        return any(f'"{pid}"' in line for line in text.splitlines())

    def _windows_identity(self, pid: int) -> Optional[str]:                            # pragma: no cover - Windows だけ（A6 で実機）
        command = ["powershell", "-NoProfile", "-NonInteractive", "-Command",
                   f"(Get-CimInstance Win32_Process -Filter 'ProcessId = {pid}').CreationDate.ToString('yyyyMMddHHmmssfff')"]
        try:
            completed = subprocess.run(command, capture_output=True, timeout=PROBE_TIMEOUT_SECONDS, check=False)
        except (OSError, subprocess.SubprocessError):
            return None
        if completed.returncode != 0:
            return None
        digits = _DIGITS.findall(completed.stdout.decode("utf-8", "replace"))
        return _digest(f"{pid}:{digits[0]}") if digits else None


class StaticProbe(ProcessProbe):
    """test ・模擬のための固定の答え（pid → alive ・identity ・boot）。"""

    def __init__(self, alive: Dict[int, Optional[bool]], identities: Optional[Dict[int, Optional[str]]] = None,
                 boot: Optional[str] = None) -> None:
        self._alive, self._identities, self._boot = dict(alive), dict(identities or {}), boot

    def is_alive(self, pid: int) -> Optional[bool]:
        return self._alive.get(pid)

    def identity(self, pid: int) -> Optional[str]:
        return self._identities.get(pid)

    def boot_marker(self) -> Optional[str]:
        return self._boot


def this_process(probe: ProcessProbe) -> Dict[str, Any]:
    pid = os.getpid()
    return {"pid": pid, "process_identity": probe.identity(pid), "boot_marker": probe.boot_marker()}


__all__ = ["PROBE_TIMEOUT_SECONDS", "ProcessProbe", "StaticProbe", "this_process"]
