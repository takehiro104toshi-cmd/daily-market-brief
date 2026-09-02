"""Setup readiness と init（Phase 3.75 §22 / §23 / §26）。credential は扱わない・出力しない。

    python -m src.intelligence.mobile_intake.setup check
    python -m src.intelligence.mobile_intake.setup init --inbox <dir> [--data-root <dir>] [--provider ICLOUD_DRIVE]
    python -m src.intelligence.mobile_intake.setup task        # schtasks コマンドを表示（実行はユーザー）
    python -m src.intelligence.mobile_intake.setup shortcut    # iPhone ショートカット手順を表示
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Dict, List, Optional

from ..core.paths import data_root
from ..corpus.config import load_corpus_config
from ..corpus.store import corpus_root
from .adapters import PROVIDERS, SyncFolderAdapter, default_sync_root
from .config import MobileIntakeConfig, load_mobile_intake_config
from .local_config import (
    LocalConfig,
    is_git_ignored,
    is_inside_repo,
    load_local_config,
    redact_path,
    write_local_config,
)
from .scheduler import (
    RUN_SCRIPT,
    is_task_registered,
    schtasks_create_command,
    schtasks_query_command,
    write_run_script,
)
from .shortcut import INSTRUCTIONS_FILE, MOBILE_ACTION_COUNT, build_instructions_ja, write_instructions

READY = "MOBILE_INTAKE_READY"
PARTIAL = "MOBILE_INTAKE_PARTIAL"
NOT_READY = "MOBILE_INTAKE_NOT_READY"


def readiness(config: MobileIntakeConfig, local: LocalConfig, *, repo_root: Path,
              task_registered: Optional[bool] = None, env=None) -> Dict[str, object]:
    environ = os.environ if env is None else env
    checks: Dict[str, object] = {}
    diagnostics: List[str] = []
    inbox = local.inbox_dir
    checks["inbox_configured"] = inbox is not None
    if inbox is None:
        diagnostics.append("Inbox 未設定: `setup init --inbox <同期フォルダ>` を実行してください")
    adapter = SyncFolderAdapter(local.provider, inbox, config.status_dir_name) if inbox else None
    desc = adapter.describe() if adapter else {"exists": False, "readable": False, "writable": False}
    checks["inbox_exists"] = bool(desc["exists"])
    checks["inbox_readable"] = bool(desc["readable"])
    checks["inbox_writable"] = bool(desc["writable"])
    if inbox is not None and not desc["exists"]:
        diagnostics.append("Inbox フォルダが存在しません（同期クライアント未設定 or 未同期）")
    if inbox is not None:
        inside = is_inside_repo(inbox, repo_root)
        ignored = is_git_ignored(inbox, repo_root) if inside else None
        checks["inbox_outside_repo_or_ignored"] = (not inside) or bool(ignored)
        if inside and not ignored:
            diagnostics.append("Inbox が repository 内で gitignore されていません（PDF が commit され得ます）")
    else:
        checks["inbox_outside_repo_or_ignored"] = False
    root = corpus_root(local.data_root)
    anchor = root
    while not anchor.exists() and anchor.parent != anchor:      # 最初に存在する祖先（data root は初回に作られる）
        anchor = anchor.parent
    reachable = anchor.exists() and os.access(anchor, os.W_OK)
    checks["corpus_reachable"] = bool(reachable)
    if not reachable:
        diagnostics.append("Corpus root に到達できません（INTELLIGENCE_DATA_ROOT を確認）")
    run_script = local.home / RUN_SCRIPT
    checks["run_script_generated"] = run_script.is_file()
    if task_registered is None:
        task_registered = is_task_registered(config)
    checks["processor_configured"] = task_registered          # True / False / None(非 Windows)
    if task_registered is False:
        diagnostics.append(f"Task Scheduler 未登録: `setup task` の schtasks コマンドを実行してください")
    elif task_registered is None:
        diagnostics.append("この OS では Task Scheduler を確認できません（Windows で `setup check` を実行）")
    checks["shortcut_instructions_generated"] = (local.home / INSTRUCTIONS_FILE).is_file()
    if not checks["shortcut_instructions_generated"]:
        diagnostics.append("iPhone ショートカット手順が未生成（`setup init` で生成）")
    sync_root = default_sync_root(local.provider, environ)
    checks["provider_sync_root_detected"] = bool(sync_root and sync_root.exists())
    checks["provider"] = local.provider
    checks["mobile_action_count"] = MOBILE_ACTION_COUNT

    core_ok = all(bool(checks[k]) for k in ("inbox_configured", "inbox_exists", "inbox_readable",
                                             "inbox_writable", "corpus_reachable"))
    if not core_ok:
        status = NOT_READY
    elif checks["processor_configured"] is True and checks["shortcut_instructions_generated"] \
            and checks["inbox_outside_repo_or_ignored"]:
        status = READY
    else:
        status = PARTIAL
    return {"status": status, "checks": checks, "diagnostics": diagnostics,
            "inbox": redact_path(inbox) if inbox else "", "home": redact_path(local.home),
            "corpus_root": redact_path(root), "sources": dict(local.sources)}


def init(config: MobileIntakeConfig, *, home: Path, inbox_dir: Optional[Path],
         data_root_dir: Optional[Path], provider: str, python_exe: str, repo_root: Path
         ) -> Dict[str, object]:
    """機械ローカル設定・run script・ショートカット手順を生成し、Inbox と _status を作る。"""
    home = Path(home)
    if provider and provider.upper() not in PROVIDERS:
        raise ValueError(f"unknown provider: {provider}")
    cfg_path = write_local_config(home, inbox_dir=inbox_dir, data_root_dir=data_root_dir,
                                  provider=provider)
    created_inbox = False
    if inbox_dir is not None and Path(inbox_dir).parent.exists():
        Path(inbox_dir).mkdir(parents=True, exist_ok=True)
        (Path(inbox_dir) / config.status_dir_name).mkdir(exist_ok=True)
        created_inbox = True
    script = write_run_script(home, python_exe, repo_root)
    instructions = write_instructions(home, config)
    return {"local_config": redact_path(cfg_path), "run_script": redact_path(script),
            "shortcut_instructions": redact_path(instructions), "inbox_created": created_inbox,
            "inbox": redact_path(inbox_dir) if inbox_dir else "",
            "task_command": schtasks_create_command(config, home)}


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Compass mobile intake setup")
    sub = parser.add_subparsers(dest="command")
    sub.add_parser("check")
    p_init = sub.add_parser("init")
    p_init.add_argument("--inbox", default="")
    p_init.add_argument("--data-root", default="")
    p_init.add_argument("--provider", default="")
    p_init.add_argument("--home", default="")
    sub.add_parser("task")
    sub.add_parser("shortcut")
    args = parser.parse_args(argv)
    config = load_mobile_intake_config()
    repo_root = Path.cwd()
    if args.command == "init":
        home = Path(args.home) if args.home else load_local_config(config).home
        out = init(config, home=home, inbox_dir=Path(args.inbox) if args.inbox else None,
                   data_root_dir=Path(args.data_root) if args.data_root else None,
                   provider=args.provider, python_exe=sys.executable, repo_root=repo_root)
        print(json.dumps(out, ensure_ascii=False, indent=1))
        return 0
    local = load_local_config(config)
    if args.command == "task":
        print(schtasks_create_command(config, local.home))
        print(schtasks_query_command(config))
        return 0
    if args.command == "shortcut":
        print(build_instructions_ja(config))
        return 0
    result = readiness(config, local, repo_root=repo_root)
    print(json.dumps(result, ensure_ascii=False, indent=1))
    return 0 if result["status"] == READY else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
