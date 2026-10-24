"""P12-A3 — private root の中の小さな file の原子的な置換と正準な読み（ledger の checkpoint ・status ・authority が使う）。

- `replace_atomically(target, data)`: 同じ directory に一時 file を `open("xb")` で作り、書き ・flush ・fsync し、`os.replace` で 1 回だけ
  target に替え、directory を fsync する。失敗は `AutomationError("STEP_FAILED", "ATOMIC_REPLACE_IO")`（path ・OS の文は出さない）。
- `read_text_file(target)`: 無ければ None。読めなければ同じ code。byte は UTF-8 ・LF ・末尾の改行 1 つを要求する。
- `append_line(target, line)`: 追記専用（`open("ab")` ・flush ・fsync）。行は改行を含まない正準 JSON。
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Optional

from .failure_codes import AutomationError

TEMP_SUFFIX = ".tmp"


def fsync_directory(directory: Path) -> None:
    try:
        fd = os.open(str(directory), os.O_RDONLY)
    except OSError:
        return                                                                         # Windows: directory の fd は開けない
    try:
        os.fsync(fd)
    except OSError:
        pass
    finally:
        os.close(fd)


def ensure_directory(directory: Any) -> Path:
    target = Path(directory)
    try:
        target.mkdir(parents=False, exist_ok=True)
    except OSError:
        raise AutomationError("STEP_FAILED", "DIRECTORY_IO") from None
    return target


def ensure_root_subdirectory(p12_root: Any, name: str) -> Path:
    """明示の P12 root（親は在ること）とその直下の 1 つの directory だけを初期化する。"""
    root = Path(p12_root)
    if not root.parent.is_dir():
        raise AutomationError("ROOT_MISSING", "P12")
    ensure_directory(root)
    return ensure_directory(root / name)


def replace_atomically(target: Any, data: bytes) -> None:
    final = Path(target)
    if not isinstance(data, bytes) or b"\r" in data or not data.endswith(b"\n"):
        raise AutomationError("SCHEMA_INVALID", "FILE_BYTES")
    temporary = final.with_name(final.name + TEMP_SUFFIX)
    try:
        if temporary.exists() or temporary.is_symlink():
            temporary.unlink()                                                         # 前回の中断の一時 file だけ（target は触らない）
        with open(temporary, "xb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, final)
        fsync_directory(final.parent)
    except OSError:
        raise AutomationError("STEP_FAILED", "ATOMIC_REPLACE_IO") from None


def read_text_file(target: Any) -> Optional[str]:
    final = Path(target)
    try:
        if not final.exists():
            return None
        if final.is_symlink() or not final.is_file():
            raise AutomationError("SCHEMA_INVALID", "FILE_KIND")
        data = final.read_bytes()
    except OSError:
        raise AutomationError("STEP_FAILED", "FILE_READ_IO") from None
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        raise AutomationError("SCHEMA_INVALID", "FILE_NOT_UTF8") from None


def append_line(target: Any, line: str) -> None:
    if not isinstance(line, str) or "\n" in line or "\r" in line or line == "":
        raise AutomationError("SCHEMA_INVALID", "LINE_SHAPE")
    try:
        with open(Path(target), "ab") as handle:
            handle.write(line.encode("utf-8") + b"\n")
            handle.flush()
            os.fsync(handle.fileno())
        fsync_directory(Path(target).parent)
    except OSError:
        raise AutomationError("STEP_FAILED", "APPEND_IO") from None


__all__ = ["TEMP_SUFFIX", "append_line", "ensure_directory", "ensure_root_subdirectory", "fsync_directory", "read_text_file",
           "replace_atomically"]
