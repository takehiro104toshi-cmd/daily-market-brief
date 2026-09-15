"""機械ローカル設定と path privacy（Phase 3.75 §9 / §21 / §22）。

repository 設定（config.yaml）と **機械固有の private 設定** を分離する。
Inbox の場所は次の順で解決する（絶対 path を repository に commit しない）:
    1. 環境変数 COMPASS_INBOX_DIR
    2. ローカル設定ファイル <home>/local_config.json（home = COMPASS_INTAKE_HOME or ~/.compass_intake）
    3. provider の既定同期 root ＋ config inbox_subpath（存在する場合のみ）
    4. 未設定（None）→ setup が案内する
log / status には full path を出さず、redact_path()（末尾 2 要素）か logical locator（inbox://<basename>）を使う。
"""
from __future__ import annotations

import json
import os
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, Mapping, Optional

from ..core.paths import DATA_ROOT_ENV, data_root
from .config import MobileIntakeConfig

ENV_INBOX = "COMPASS_INBOX_DIR"
ENV_HOME = "COMPASS_INTAKE_HOME"
LOCAL_FILE = "local_config.json"

SRC_ENV = "ENV"
SRC_LOCAL_FILE = "LOCAL_FILE"
SRC_PROVIDER_DEFAULT = "PROVIDER_DEFAULT"
SRC_REPO_CONFIG = "REPO_CONFIG"
SRC_NONE = "NONE"


@dataclass(frozen=True)
class LocalConfig:
    home: Path
    inbox_dir: Optional[Path]
    data_root: Path
    provider: str
    sources: Mapping[str, str] = field(default_factory=dict)   # 各値の由来

    def as_dict(self) -> Dict[str, object]:
        return {"home": redact_path(self.home),
                "inbox_dir": redact_path(self.inbox_dir) if self.inbox_dir else "",
                "data_root": redact_path(self.data_root), "provider": self.provider,
                "sources": dict(self.sources)}


def environment_with(overrides: Optional[Mapping[str, str]] = None) -> Dict[str, str]:
    """os.environ に overrides を重ねた dict（env を読む場所を本モジュールに集約する）。"""
    merged = dict(os.environ)
    for k, v in dict(overrides or {}).items():
        if v:
            merged[str(k)] = str(v)
    return merged


def local_home(env: Optional[Mapping[str, str]] = None,
               dir_name: str = ".compass_intake") -> Path:
    environ = os.environ if env is None else env
    override = str(environ.get(ENV_HOME, "") or "").strip()
    if override:
        return Path(override)
    return Path.home() / dir_name


def read_local_file(home: Path) -> Dict[str, str]:
    path = Path(home) / LOCAL_FILE
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8")) or {}
    except (OSError, json.JSONDecodeError):
        return {}
    return {str(k): str(v) for k, v in dict(data).items() if v is not None}


def write_local_config(home: Path, *, inbox_dir: Optional[Path] = None,
                       data_root_dir: Optional[Path] = None, provider: str = "") -> Path:
    """機械ローカル設定を <home>/local_config.json に書く（repository の外）。既存値は保持。"""
    home = Path(home)
    home.mkdir(parents=True, exist_ok=True)
    current = read_local_file(home)
    if inbox_dir is not None:
        current["inbox_dir"] = str(Path(inbox_dir))
    if data_root_dir is not None:
        current["data_root"] = str(Path(data_root_dir))
    if provider:
        current["provider"] = provider.upper()
    path = home / LOCAL_FILE
    path.write_text(json.dumps(current, ensure_ascii=False, indent=1), encoding="utf-8")
    return path


def load_local_config(config: MobileIntakeConfig, *, env: Optional[Mapping[str, str]] = None,
                      home: Optional[Path] = None) -> LocalConfig:
    from .adapters import default_inbox_dir

    environ = os.environ if env is None else env
    home = Path(home) if home else local_home(environ, config.local_config_dir_name)
    local = read_local_file(home)
    sources: Dict[str, str] = {}

    provider = config.provider
    sources["provider"] = SRC_REPO_CONFIG
    if local.get("provider"):
        provider, sources["provider"] = local["provider"].upper(), SRC_LOCAL_FILE

    inbox: Optional[Path] = None
    env_inbox = str(environ.get(ENV_INBOX, "") or "").strip()
    if env_inbox:
        inbox, sources["inbox_dir"] = Path(env_inbox), SRC_ENV
    elif local.get("inbox_dir"):
        inbox, sources["inbox_dir"] = Path(local["inbox_dir"]), SRC_LOCAL_FILE
    else:
        default = default_inbox_dir(provider, config.inbox_subpath, environ)
        if default is not None and default.parent.exists():
            inbox, sources["inbox_dir"] = default, SRC_PROVIDER_DEFAULT
        else:
            sources["inbox_dir"] = SRC_NONE

    if str(environ.get(DATA_ROOT_ENV, "") or "").strip():
        root, sources["data_root"] = data_root(env=dict(environ)), SRC_ENV
    elif local.get("data_root"):
        root, sources["data_root"] = Path(local["data_root"]), SRC_LOCAL_FILE
    else:
        root, sources["data_root"] = data_root(env=dict(environ)), SRC_REPO_CONFIG
    return LocalConfig(home=home, inbox_dir=inbox, data_root=root, provider=provider,
                       sources=sources)


# ------------------------------------------------------------- path privacy

def redact_path(path: Optional[Path], keep: int = 2) -> str:
    """個人の full path を出さない: 末尾 keep 要素だけ（例: ".../Shortcuts/CompassInbox"）。"""
    if path is None:
        return ""
    parts = [p for p in Path(path).parts if p not in ("/", "\\")]
    if len(parts) <= keep:
        return "/".join(parts)
    return ".../" + "/".join(parts[-keep:])


def logical_locator(path: Path) -> str:
    return "inbox://" + Path(path).name


def is_inside_repo(path: Path, repo_root: Path) -> bool:
    try:
        Path(path).resolve().relative_to(Path(repo_root).resolve())
        return True
    except (ValueError, OSError):
        return False


def is_git_ignored(path: Path, repo_root: Path) -> Optional[bool]:
    """repository 内の path が gitignore されているか（git が無ければ None）。"""
    try:
        rc = subprocess.run(["git", "check-ignore", "-q", str(path)], cwd=str(repo_root),
                            capture_output=True, timeout=10).returncode
    except (OSError, subprocess.SubprocessError):
        return None
    return rc == 0
