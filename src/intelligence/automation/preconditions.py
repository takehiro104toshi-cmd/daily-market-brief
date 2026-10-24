"""P12-A2 — 決定論の前提条件の検査（最初の失敗で止まる ・安全な code だけ ・git の出力 ・path ・例外の文は出さない）。

順（`PRECONDITION_ORDER`）:
 1. REQUEST_IDENTITY   要求の PIT の欄の一貫性と run_id の再計算（A1 の RunIdentity）
 2. CREDENTIAL_ABSENT  予約した資格情報の変数（`RESERVED_CREDENTIAL_VARIABLES` ・`JQUANTS_` の接頭辞）が環境に無い（値は見ない）
 3. NETWORK_POLICY     policy は NetworkPolicy（external を許す欄は存在しない）
 4. REPO_HEAD          `git rev-parse HEAD` ＝ 要求の runtime_anchor
 5. REPO_CLEAN         `git status --porcelain --untracked-files=all` が空
 6. P11_FROZEN         凍結の P11 の 12 file の worktree の byte の blob id ＝ 凍結 anchor の blob
 7. P9_ROOT ・8. P10_ROOT  在って読める directory
 9. P12_ROOT           明示に渡された root（無ければ親が在る ＝ 初期化できる）
git は読み取りの引数の list だけで呼ぶ（shell 無し ・push ・書き込み無し）。失敗は `PreconditionOutcome`（code）で返し、例外は投げない。
"""
from __future__ import annotations

import os
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Mapping, Optional, Sequence, Tuple

from .execution_request import AutomationExecutionRequest
from .failure_codes import AutomationError
from .frozen_anchors import P11_FROZEN_BLOBS, git_blob_id
from .network_deny import NetworkPolicy

PRECONDITION_ORDER: Tuple[str, ...] = ("REQUEST_IDENTITY", "CREDENTIAL_ABSENT", "NETWORK_POLICY", "REPO_HEAD", "REPO_CLEAN",
                                       "P11_FROZEN", "P9_ROOT", "P10_ROOT", "P12_ROOT")
RESERVED_CREDENTIAL_VARIABLES: Tuple[str, ...] = ("JQUANTS_API_KEY", "JQUANTS_REFRESH_TOKEN", "JQUANTS_ID_TOKEN",
                                                  "JQUANTS_MAIL_ADDRESS", "JQUANTS_PASSWORD")
CREDENTIAL_PREFIX = "JQUANTS_"
GIT_TIMEOUT_SECONDS = 60


@dataclass(frozen=True, repr=False)
class PrivateRoots:
    """private な root（repr ・str に path を出さない）。P12 の root は明示に渡す（既定 ・探索は無い）。"""

    p9_root: Any
    p10_root: Any
    p12_root: Any

    def __repr__(self) -> str:
        return "PrivateRoots(<private>)"

    __str__ = __repr__


@dataclass(frozen=True)
class PreconditionOutcome:
    passed: Tuple[str, ...]
    failure_code: Optional[str]

    @property
    def ok(self) -> bool:
        return self.failure_code is None

    def to_dict(self) -> Dict[str, Any]:
        return {"passed": list(self.passed), "failure_code": self.failure_code}


def _git(repo_root: Path, *args: str) -> Optional[str]:
    """読み取りの git。失敗 ・不在は None（stderr ・stdout は返さない ・出さない）。"""
    try:
        completed = subprocess.run(["git", "-C", str(repo_root), *args], capture_output=True, check=False,
                                   timeout=GIT_TIMEOUT_SECONDS)
    except (OSError, subprocess.SubprocessError):
        return None
    if completed.returncode != 0:
        return None
    try:
        return completed.stdout.decode("utf-8")
    except UnicodeDecodeError:
        return None


def _readable_dir(value: Any) -> bool:
    try:
        root = Path(value)
        if value in ("", None) or not root.is_dir() or root.is_symlink():
            return False
        if not os.access(root, os.R_OK | os.X_OK):
            return False
        next(iter(root.iterdir()), None)
        return True
    except (OSError, TypeError, ValueError):
        return False


def credential_present(environment: Mapping[str, str]) -> bool:
    """予約した名前 ・`JQUANTS_` の接頭辞の変数が非空か（値は比較以外に使わない ・返さない ・記録しない）。"""
    for name in environment:
        if (name in RESERVED_CREDENTIAL_VARIABLES or name.startswith(CREDENTIAL_PREFIX)) and environment.get(name, "") != "":
            return True
    return False


def frozen_p11_drift(runtime_root: Any) -> Tuple[str, ...]:
    """凍結 anchor の blob と worktree の byte の blob が違う（または無い）P11 の file（repo 相対）。空なら drift なし。"""
    drifted = []
    for relative, expected in sorted(P11_FROZEN_BLOBS.items()):
        target = Path(runtime_root) / relative
        try:
            actual = git_blob_id(target.read_bytes()) if target.is_file() and not target.is_symlink() else None
        except OSError:
            actual = None
        if actual != expected:
            drifted.append(relative)
    return tuple(drifted)


def check_preconditions(request: AutomationExecutionRequest, roots: PrivateRoots, *, repo_root: Any, runtime_root: Any,
                        environment: Mapping[str, str], policy: NetworkPolicy) -> PreconditionOutcome:
    passed = []

    def fail(code: str) -> PreconditionOutcome:
        return PreconditionOutcome(passed=tuple(passed), failure_code=code)

    if not isinstance(request, AutomationExecutionRequest):
        return fail("SCHEMA_INVALID:REQUEST_TYPE")
    try:
        if request.run.run_id != request.identity.run_id or len(request.run_id) != 64:
            return fail("SCHEMA_INVALID:RUN_ID")
    except AutomationError as exc:
        return fail(exc.public_code)
    passed.append("REQUEST_IDENTITY")
    if credential_present(environment):
        return fail("CREDENTIAL_PRESENT")
    passed.append("CREDENTIAL_ABSENT")
    if not isinstance(policy, NetworkPolicy):
        return fail("SCHEMA_INVALID:NETWORK_POLICY")
    passed.append("NETWORK_POLICY")
    repo = Path(repo_root)
    head = _git(repo, "rev-parse", "--verify", "HEAD")
    if head is None:
        return fail("REPO_HEAD_MISMATCH:GIT_UNAVAILABLE")
    if head.strip() != request.runtime_anchor:
        return fail("REPO_HEAD_MISMATCH")
    passed.append("REPO_HEAD")
    status = _git(repo, "status", "--porcelain", "--untracked-files=all")
    if status is None:
        return fail("REPO_NOT_CLEAN:GIT_UNAVAILABLE")
    if status.strip() != "":
        return fail("REPO_NOT_CLEAN")
    passed.append("REPO_CLEAN")
    if frozen_p11_drift(runtime_root):
        return fail("FROZEN_DRIFT:P11")
    passed.append("P11_FROZEN")
    if not isinstance(roots, PrivateRoots):
        return fail("SCHEMA_INVALID:ROOTS_TYPE")
    for name, value in (("P9_ROOT", roots.p9_root), ("P10_ROOT", roots.p10_root)):
        if not _readable_dir(value):
            return fail(f"ROOT_MISSING:{name[:-5]}")
        passed.append(name)
    try:
        p12 = Path(roots.p12_root) if roots.p12_root not in ("", None) else None
    except TypeError:
        p12 = None
    if p12 is None or not (p12.is_dir() or (not p12.exists() and p12.parent.is_dir())):
        return fail("ROOT_MISSING:P12")
    passed.append("P12_ROOT")
    return PreconditionOutcome(passed=tuple(passed), failure_code=None)


__all__ = ["CREDENTIAL_PREFIX", "GIT_TIMEOUT_SECONDS", "PRECONDITION_ORDER", "RESERVED_CREDENTIAL_VARIABLES",
           "PreconditionOutcome", "PrivateRoots", "check_preconditions", "credential_present", "frozen_p11_drift"]
