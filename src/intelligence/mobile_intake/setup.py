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
from ..corpus.identity import sha256_file
from ..corpus.inbox import is_stable, sample_file
from ..corpus.snapshot import build_snapshot
from ..corpus.store import CorpusStore, corpus_root
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


def inventory_report(config: MobileIntakeConfig, local: LocalConfig, *, now_ts: Optional[float] = None,
                     max_names: int = 60) -> Dict[str, object]:
    """実 Inbox の棚卸し（読むだけ。移動・削除・改変しない）。full path は出さない。"""
    import time as _time

    now_ts = _time.time() if now_ts is None else now_ts
    inbox = local.inbox_dir
    if inbox is None or not Path(inbox).is_dir():
        return {"inbox": redact_path(inbox) if inbox else "", "exists": False}
    adapter = SyncFolderAdapter(local.provider, Path(inbox), config.status_dir_name)
    entries = sorted(Path(inbox).iterdir())
    dirs = [e for e in entries if e.is_dir()]
    files = [e for e in entries if e.is_file()]
    candidates, placeholders = adapter.discover()
    placeholder_names = {p.name for p, _ in placeholders}
    non_pdf = [f for f in files if f.suffix.lower() != ".pdf" and f.name not in placeholder_names]
    stable, unstable = [], []
    for f in candidates:
        try:
            samples = [sample_file(f), sample_file(f)]
            ok = is_stable(samples, now_ts, config.stable_seconds)
            with f.open("rb") as handle:
                handle.read(8)
        except OSError:
            ok = False
        (stable if ok else unstable).append(f)
    root = corpus_root(local.data_root)
    duplicates, new_candidates = [], []
    corpus_docs = 0
    if (root / "index" / "corpus.sqlite3").exists():
        store = CorpusStore(root)
        try:
            corpus_docs = len(store.documents())
            for f in stable:
                (duplicates if store.document_by_sha(sha256_file(f)) is not None else new_candidates).append(f)
        finally:
            store.close()
    else:
        new_candidates = list(stable)
    return {"inbox": redact_path(inbox), "exists": True, "provider": local.provider,
            "total_items": len(entries), "subfolders": len(dirs),
            "subfolder_names": [d.name for d in dirs][:max_names], "files": len(files),
            "pdf_candidates": len(candidates), "stable": len(stable), "unstable": len(unstable),
            "placeholders": len(placeholders), "placeholder_kinds": sorted({r for _, r in placeholders}),
            "non_pdf": len(non_pdf), "non_pdf_names": [f.name for f in non_pdf][:max_names],
            "corpus_documents": corpus_docs, "hash_duplicates_of_corpus": len(duplicates),
            "new_candidates": len(new_candidates), "new_candidate_names": [f.name for f in new_candidates][:max_names],
            "duplicate_names": [f.name for f in duplicates][:max_names],
            "note": "read-only inventory; nothing moved, deleted or modified"}


def status_report(local: LocalConfig) -> Dict[str, object]:
    """Corpus（3.7）と Research（3.8）の現在値。before / after 比較用。"""
    from datetime import datetime, timezone

    out: Dict[str, object] = {"data_root": redact_path(local.data_root)}
    root = corpus_root(local.data_root)
    if not (root / "index" / "corpus.sqlite3").exists():
        out["corpus"] = {"exists": False, "documents": 0}
    else:
        store = CorpusStore(root)
        try:
            snap = build_snapshot(store, load_corpus_config(), datetime.now(timezone.utc))
        finally:
            store.close()
        out["corpus"] = {"exists": True, **dict(snap.counts), "date_range": list(snap.date_range),
                         "milestone": snap.milestones["reached"], "next_milestone": snap.milestones["next_milestone"],
                         "documents_needed": snap.milestones["documents_needed"],
                         "underrepresented_regimes": snap.coverage["underrepresented_regimes"],
                         "missing_regimes": snap.coverage["missing_regimes"]}
    try:
        from ..corpus_research.config import load_research_config
        from ..corpus_research.store import SNAPSHOT_FILE, ResearchStore, research_root

        rroot = research_root(local.data_root)
        snap_path = rroot / SNAPSHOT_FILE
        if snap_path.is_file():
            rs = json.loads(snap_path.read_text(encoding="utf-8"))
            rconfig = load_research_config()
            structures = ResearchStore(rroot).current_structures(rconfig.version_key)
            regimes = {str((st.get("regime") or {}).get("regime_key", "regime:UNKNOWN")) for st in structures.values()}
            regimes.discard("regime:UNKNOWN")
            out["research"] = {"exists": True, "analyzed_documents": rs.get("analyzed_documents"),
                               "patterns_total": rs.get("patterns_total"), "patterns_by_status": rs.get("patterns_by_status"),
                               "conflicts": len(rs.get("conflicts") or []), "review_queue": rs.get("review_queue"),
                               "dna_comparison_counts": rs.get("dna_comparison_counts"),
                               "regime_signatures": len(regimes), "coverage": rs.get("coverage"),
                               "limitations": rs.get("limitations"), "analyzer_versions": rs.get("analyzer_versions")}
        else:
            out["research"] = {"exists": False}
    except Exception as exc:  # noqa: BLE001 research 層が無くても status は出す
        out["research"] = {"exists": False, "error_type": type(exc).__name__}
    return out


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Compass mobile intake setup")
    sub = parser.add_subparsers(dest="command")
    sub.add_parser("check")
    sub.add_parser("inventory")
    sub.add_parser("status")
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
    if args.command == "inventory":
        print(json.dumps(inventory_report(config, local), ensure_ascii=False, indent=1))
        return 0
    if args.command == "status":
        print(json.dumps(status_report(local), ensure_ascii=False, indent=1))
        return 0
    result = readiness(config, local, repo_root=repo_root)
    print(json.dumps(result, ensure_ascii=False, indent=1))
    return 0 if result["status"] == READY else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
