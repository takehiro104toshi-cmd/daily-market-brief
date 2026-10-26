"""P12-A5 — 無人の実行が受け入れる runtime の anchor の pin（`<p12_root>/authority/runtime_pin.json`。人だけが書く）。

- Task Scheduler の定義には HEAD を焼き込まない。scheduled-run は起動の度にこの pin を読み、repo の HEAD（読み取りの `git rev-parse`）と
  一致しなければ実行を拒む（`REPO_HEAD_MISMATCH`）。pull ・fetch ・checkout はしない: 自動化は在る code をそのまま走らせる。
- `pin-runtime` は clean な repo の今の HEAD を pin に書く（人の手）。文書だけの commit でも HEAD は変わるので pin の更新が要る
  （v1 の意図: 検証した code だけが無人で走る）。
"""
from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any, Dict, Optional

from .atomic_files import ensure_root_subdirectory, read_text_file, replace_atomically
from .canonical import canonical_json, is_git_anchor, require_fields, utc_iso
from .failure_codes import AutomationError
from .schedule_authority import AUTHORITY_DIRECTORY, HUMAN_OPERATOR

PIN_FILE_NAME = "runtime_pin.json"
PIN_SCHEMA_VERSION = "p12_runtime_pin:0.1.0"
GIT_TIMEOUT_SECONDS = 60
_FIELDS = frozenset({"schema_version", "runtime_anchor", "pinned_at", "operator"})


def pin_file(p12_root: Any) -> Path:
    return Path(p12_root) / AUTHORITY_DIRECTORY / PIN_FILE_NAME


def repo_head(repo_root: Any) -> Optional[str]:
    """読み取りの `git rev-parse --verify HEAD`。失敗 ・不在 ・形が違えば None（出力は返さない）。"""
    try:
        completed = subprocess.run(["git", "-C", str(repo_root), "rev-parse", "--verify", "HEAD"], capture_output=True, check=False,
                                   timeout=GIT_TIMEOUT_SECONDS)
    except (OSError, subprocess.SubprocessError):
        return None
    if completed.returncode != 0:
        return None
    head = completed.stdout.decode("utf-8", "replace").strip()
    return head if is_git_anchor(head) else None


def repo_is_clean(repo_root: Any) -> Optional[bool]:
    try:
        completed = subprocess.run(["git", "-C", str(repo_root), "status", "--porcelain", "--untracked-files=all"], capture_output=True,
                                   check=False, timeout=GIT_TIMEOUT_SECONDS)
    except (OSError, subprocess.SubprocessError):
        return None
    if completed.returncode != 0:
        return None
    return completed.stdout.strip() == b""


def write_runtime_pin(p12_root: Any, runtime_anchor: str, *, operator: str, pinned_at: Any) -> Dict[str, Any]:
    if operator != HUMAN_OPERATOR:
        raise AutomationError("SCHEMA_INVALID", "AUTHORITY_WRITE_NOT_HUMAN")
    if not is_git_anchor(runtime_anchor):
        raise AutomationError("SCHEMA_INVALID", "RUNTIME_ANCHOR")
    document = {"schema_version": PIN_SCHEMA_VERSION, "runtime_anchor": runtime_anchor, "pinned_at": utc_iso(pinned_at),
                "operator": operator}
    ensure_root_subdirectory(p12_root, AUTHORITY_DIRECTORY)
    replace_atomically(pin_file(p12_root), (canonical_json(document) + "\n").encode("utf-8"))
    return document


def read_runtime_pin(p12_root: Any) -> str:
    text = read_text_file(pin_file(p12_root))
    if text is None:
        raise AutomationError("SCHEMA_INVALID", "RUNTIME_PIN_MISSING")
    try:
        fields = require_fields(json.loads(text), _FIELDS, "RUNTIME_PIN")
    except (ValueError, AutomationError):
        raise AutomationError("SCHEMA_INVALID", "RUNTIME_PIN_MALFORMED") from None
    if fields["schema_version"] != PIN_SCHEMA_VERSION or not is_git_anchor(fields["runtime_anchor"]) or fields["operator"] != HUMAN_OPERATOR:
        raise AutomationError("SCHEMA_INVALID", "RUNTIME_PIN_MALFORMED")
    if canonical_json(fields) + "\n" != text:
        raise AutomationError("SCHEMA_INVALID", "RUNTIME_PIN_NOT_CANONICAL")
    return fields["runtime_anchor"]


def pin_clean_head(p12_root: Any, repo_root: Any, *, operator: str, pinned_at: Any) -> str:
    """clean な repo の今の HEAD を pin する（人の手）。汚れていれば拒む。"""
    head = repo_head(repo_root)
    if head is None:
        raise AutomationError("REPO_HEAD_MISMATCH", "GIT_UNAVAILABLE")
    if repo_is_clean(repo_root) is not True:
        raise AutomationError("REPO_NOT_CLEAN")
    write_runtime_pin(p12_root, head, operator=operator, pinned_at=pinned_at)
    return head


__all__ = ["GIT_TIMEOUT_SECONDS", "PIN_FILE_NAME", "PIN_SCHEMA_VERSION", "pin_clean_head", "pin_file", "read_runtime_pin", "repo_head",
           "repo_is_clean", "write_runtime_pin"]
