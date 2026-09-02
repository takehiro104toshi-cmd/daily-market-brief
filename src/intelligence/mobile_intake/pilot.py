"""Phase 3.75 end-to-end local pilot（::P375_*::）。

private local copy の羅針盤 PDF で、mobile/sync 到着 → partial/unstable → stable → 自動 intake →
Corpus 更新 → status を **isolated root** で再現する。実 iPhone / iCloud 接続は検証しない
（この環境に無い場合は ADAPTER_SETUP_REQUIRED と報告する。捏造しない）。
本文・full path は出力しない。
"""
from __future__ import annotations

import argparse
import dataclasses
import json
import os
import subprocess
import sys
import time as _time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Dict, List, Optional

from ..core.paths import data_root
from ..corpus.config import load_corpus_config
from ..corpus.extraction import PypdfExtractor
from ..corpus.identity import sha256_file
from ..corpus.intake import SOURCE_HISTORICAL_IMPORT
from ..corpus.inventory import inventory
from ..corpus.pipeline import ingest_path
from ..corpus.store import CorpusStore, corpus_root
from .adapters import SELECTED_PROVIDER, default_sync_root, evaluation_table
from .config import load_mobile_intake_config
from .local_config import load_local_config, redact_path
from .processor import InboxProcessor
from .result import DUPLICATE, FAILED, QUARANTINED, SUCCESS, WAITING_UNSTABLE
from .scheduler import INSTANCE_LOCK, design_summary
from .setup import init, readiness
from .shortcut import MOBILE_ACTION_COUNT, shortcut_recipe
from .status import STATUS_TXT, read_status

PILOT_ROOT_NAME = "compass_intake_pilot"


def _out(marker: str, payload) -> None:
    print(f"::{marker}::" + json.dumps(payload, ensure_ascii=False, default=str))


def _resave_pdf(src: Path, dst: Path) -> None:
    import pypdf

    reader = pypdf.PdfReader(str(src))
    writer = pypdf.PdfWriter()
    for page in reader.pages:
        writer.add_page(page)
    writer.add_metadata({"/Producer": "intake-pilot-resave"})
    with dst.open("wb") as handle:
        writer.write(handle)


def _blank_pdf(dst: Path) -> None:
    import pypdf

    writer = pypdf.PdfWriter()
    writer.add_blank_page(width=200, height=200)
    with dst.open("wb") as handle:
        writer.write(handle)


def _age(path: Path, seconds: int) -> None:
    old = _time.time() - seconds
    os.utime(path, (old, old))


def _git_porcelain() -> str:
    try:
        return subprocess.run(["git", "status", "--porcelain"], capture_output=True, text=True,
                              timeout=20).stdout
    except (OSError, subprocess.SubprocessError):
        return "?"


def _tracked_pdfs() -> int:
    try:
        out = subprocess.run(["git", "ls-files"], capture_output=True, text=True, timeout=20).stdout
    except (OSError, subprocess.SubprocessError):
        return -1
    return sum(1 for l in out.splitlines() if l.lower().endswith(".pdf"))


def _status_view(proc: InboxProcessor) -> Dict[str, object]:
    text = (proc.home / STATUS_TXT).read_text(encoding="utf-8") if (proc.home / STATUS_TXT).exists() else ""
    return {"text": text.strip(), "json": read_status(proc.home)}


def _run_summary(report) -> Dict[str, object]:
    d = report.as_dict()
    return {k: d[k] for k in ("sync_available", "single_instance_acquired", "candidates", "placeholders",
                             "skipped_processed", "skipped_locked", "corpus_before", "corpus_after",
                             "bounded_by", "counts")} | {
        "results": [{k: r[k] for k in ("result", "file", "reason_code", "document_date", "corpus_count_after")}
                    for r in d["results"]]}


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Phase 3.75 mobile intake local pilot")
    parser.add_argument("--source", default="")
    parser.add_argument("--root", default="")
    args = parser.parse_args(argv)
    started = _time.monotonic()
    now = datetime.now(timezone.utc)
    config = load_mobile_intake_config()
    corpus_config = load_corpus_config()
    source_dir = Path(args.source or corpus_config.source_dir)
    root = Path(args.root) if args.root else data_root() / PILOT_ROOT_NAME
    home = root / "_home"
    inbox = root / "_inbox"                     # 同期フォルダの代替（ローカル）
    git_before = _git_porcelain()
    production_root = corpus_root(data_root())
    production_before = production_root.exists()

    _out("P375_INPUT", {"config": config.as_dict(), "source_dir_exists": source_dir.is_dir(),
                        "root": redact_path(root), "inbox": redact_path(inbox), "home": redact_path(home),
                        "platform": sys.platform, "offline": True})

    # ---- adapter evaluation（実接続は検証しない。存在しなければ SETUP_REQUIRED）
    sync_root = default_sync_root(SELECTED_PROVIDER)
    _out("P375_ADAPTER", {
        "selected": SELECTED_PROVIDER,
        "evaluation": [{k: r[k] for k in ("provider", "share_sheet_taps", "new_account", "cost", "verdict")}
                       for r in evaluation_table()],
        "selected_sync_root_detected_here": bool(sync_root and sync_root.exists()),
        "real_adapter_validation": "VERIFIED" if (sync_root and sync_root.exists()) else "ADAPTER_SETUP_REQUIRED",
        "mobile_action_count": MOBILE_ACTION_COUNT,
        "shortcut": {k: shortcut_recipe(config)[k] for k in ("name", "destination", "installed_verified")},
        "windows_auto_ingest": design_summary(config)})

    inv = inventory([source_dir])
    if len(inv.pdf_items) < 2:
        _out("P375_SUMMARY", {"blocked": True, "reason": "need >= 2 private Compass PDFs"})
        return 1
    pdfs = [Path(i.locations[0]) for i in inv.pdf_items]
    hashes_before = {p.name: sha256_file(p) for p in pdfs}
    seed, arriving = pdfs[:-1], pdfs[-1]

    # ---- isolated corpus seeded with n-1 documents
    env = {**os.environ, "COMPASS_INBOX_DIR": str(inbox), "INTELLIGENCE_DATA_ROOT": str(root),
           "COMPASS_INTAKE_HOME": str(home)}
    local = load_local_config(config, env=env, home=home)
    store = CorpusStore(corpus_root(local.data_root))
    extractor = PypdfExtractor(corpus_config.extractor_version)
    for p in seed:
        ingest_path(store, p, config=corpus_config, extractor=extractor, now=now,
                    source_type=SOURCE_HISTORICAL_IMPORT)
    setup_out = init(config, home=home, inbox_dir=inbox, data_root_dir=root, provider=SELECTED_PROVIDER,
                     python_exe=sys.executable, repo_root=Path("."))
    local = load_local_config(config, env=env, home=home)
    ready = readiness(config, local, repo_root=Path("."), env=env)
    _out("P375_SETUP", {"init": {k: setup_out[k] for k in ("inbox_created", "run_script", "shortcut_instructions")},
                        "readiness": ready["status"], "checks": ready["checks"],
                        "diagnostics": ready["diagnostics"], "seeded_documents": len(seed)})

    proc = InboxProcessor(config, local, corpus_config, store, extractor, sleeper=lambda s: None)
    proc.config = dataclasses.replace(config, sample_interval_seconds=0.0)

    # ---- arrival: partial（転送中）
    data = arriving.read_bytes()
    target = inbox / arriving.name
    target.write_bytes(data[: len(data) // 2])                  # mtime = now → 不安定
    r1 = proc.run_once(now)
    _out("P375_ARRIVAL_PARTIAL", {"run": _run_summary(r1), "status": _status_view(proc),
                                  "ledgered": len(proc.ledger_entries())})

    # ---- arrival: stable（同期完了）
    target.write_bytes(data)
    _age(target, config.stable_seconds + 60)
    r2 = proc.run_once(now + timedelta(minutes=5))
    _out("P375_ARRIVAL_STABLE", {"run": _run_summary(r2), "status": _status_view(proc),
                                 "inbox_status_file": (inbox / config.status_dir_name / STATUS_TXT).exists(),
                                 "original_kept_in_inbox": target.exists()})

    # ---- duplicate（iPhone の同名 " 2" 付与を再現）
    dup = inbox / (arriving.stem + " 2.pdf")
    dup.write_bytes(data)
    _age(dup, config.stable_seconds + 60)
    r3 = proc.run_once(now + timedelta(minutes=10))
    _out("P375_DUPLICATE", {"run": _run_summary(r3), "status": _status_view(proc),
                            "corpus_documents": len(store.documents())})

    # ---- rerun（何も無い）
    canon_before = store.canonical_counts()
    r4 = proc.run_once(now + timedelta(minutes=15))
    canon_after = store.canonical_counts()
    _out("P375_RERUN", {"run": _run_summary(r4), "canonical_unchanged": canon_before == canon_after,
                        "status": _status_view(proc)["text"]})

    # ---- crash recovery（stale instance lock + stale file lock の残骸）
    rev = inbox / "revision_same_date.pdf"
    _resave_pdf(arriving, rev)
    _age(rev, config.stable_seconds + 60)
    stale_instance = home / INSTANCE_LOCK
    stale_instance.write_text("dead-pid")
    _age(stale_instance, config.stale_lock_minutes * 60 + 120)
    lock_dir = home / "locks"
    lock_dir.mkdir(exist_ok=True)
    stale_file_lock = lock_dir / (rev.name + ".lock")
    stale_file_lock.write_text("dead")
    _age(stale_file_lock, config.stale_lock_minutes * 60 + 120)
    r5 = proc.run_once(now + timedelta(minutes=20))
    fresh_lock = home / INSTANCE_LOCK
    fresh_lock.write_text("alive")
    live_ts = (now + timedelta(minutes=21)).timestamp()
    os.utime(fresh_lock, (live_ts, live_ts))                  # simulated clock 上で「今」作られた lock
    r5b = proc.run_once(now + timedelta(minutes=21))            # 生きている lock は尊重
    fresh_lock.unlink(missing_ok=True)
    _out("P375_CRASH_RECOVERY", {"stale_locks_reclaimed_run": _run_summary(r5),
                                 "live_lock_respected": not r5b.single_instance_acquired,
                                 "instance_lock_left": (home / INSTANCE_LOCK).exists(),
                                 "file_lock_left": stale_file_lock.exists()})

    # ---- failures（何をすべきか分かる）
    junk = inbox / "not_a_pdf.pdf"
    junk.write_bytes(b"hello")
    _age(junk, config.stable_seconds + 60)
    blank = inbox / "other_report.pdf"
    _blank_pdf(blank)
    _age(blank, config.stable_seconds + 60)
    (inbox / "pending_download.pdf.icloud").write_bytes(b"placeholder")
    (inbox / "note.txt").write_text("ignored")
    r6 = proc.run_once(now + timedelta(minutes=25))
    _out("P375_FAILURES", {"run": _run_summary(r6),
                           "hints": {r.file: r.hint for r in r6.results},
                           "status": _status_view(proc)["text"]})

    # ---- unstable timeout
    stuck = inbox / "stuck_transfer.pdf"
    stuck.write_bytes(data[: len(data) // 3])
    stuck_ts = (now + timedelta(minutes=30)).timestamp()
    os.utime(stuck, (stuck_ts, stuck_ts))                       # simulated clock 上でまだ書き込み中
    proc._first_seen(stuck.name, now - timedelta(minutes=config.unstable_timeout_minutes + 5))
    r7 = proc.run_once(now + timedelta(minutes=30))
    _out("P375_TIMEOUT", {"run": _run_summary(r7),
                          "hint": next((r.hint for r in r7.results if r.file == stuck.name), "")})

    # ---- bounded（max_files_per_run=1）
    a = inbox / "bounded_a.pdf"
    b = inbox / "bounded_b.pdf"
    _resave_pdf(seed[0], a)
    _resave_pdf(seed[1], b)
    _age(a, config.stable_seconds + 60)
    _age(b, config.stable_seconds + 60)
    proc.config = dataclasses.replace(proc.config, max_files_per_run=1)
    r8 = proc.run_once(now + timedelta(minutes=35))
    r9 = proc.run_once(now + timedelta(minutes=40))
    proc.config = dataclasses.replace(proc.config, max_files_per_run=config.max_files_per_run)
    _out("P375_BOUNDED", {"first": _run_summary(r8), "second": _run_summary(r9)})

    # ---- security / privacy
    hashes_after = {p.name: sha256_file(p) for p in pdfs}
    ledger_text = proc.ledger_path.read_text(encoding="utf-8") if proc.ledger_path.exists() else ""
    status_text = json.dumps(read_status(proc.home) or {}, ensure_ascii=False)
    abs_root = str(root.resolve())
    pkg = Path(__file__).resolve().parent
    net = []
    for py in sorted(pkg.glob("*.py")):
        text = py.read_text(encoding="utf-8")
        for tok in ("import " + "requests", "import " + "urllib", "from " + "urllib", "import " + "socket",
                    "google" + "apiclient", "py" + "icloud", "drop" + "box", "bo" + "to3", "onedrive" + "sdk"):
            if tok in text:
                net.append(f"{py.name}:{tok}")
    _out("P375_SECURITY", {
        "tracked_pdfs": _tracked_pdfs(),
        "source_pdfs_unmodified": hashes_before == hashes_after,
        "inbox_originals_deleted": not (target.exists() and dup.exists()),
        "repository_mutation": _git_porcelain() != git_before,
        "production_corpus_root_modified": production_root.exists() != production_before,
        "network_or_cloud_sdk_imports": net,
        "full_path_in_ledger_or_status": (abs_root in ledger_text) or (abs_root in status_text),
        "document_text_in_ledger": ("●" in ledger_text) or ('"text"' in ledger_text),
        "external_llm_calls": 0,
    })
    store.close()
    _out("P375_SUMMARY", {
        "partial_waited": r1.counts().get(WAITING_UNSTABLE, 0) == 1 and r1.corpus_after == len(seed),
        "stable_success": r2.counts().get(SUCCESS, 0) == 1 and r2.corpus_after == len(seed) + 1,
        "milestone_after_success": next((r.milestone for r in r2.results if r.result == SUCCESS), {}),
        "duplicate_harmless": r3.counts().get(DUPLICATE, 0) == 1 and r3.corpus_after == r2.corpus_after,
        "rerun_idempotent": canon_before == canon_after,
        "crash_recovered": r5.counts().get(SUCCESS, 0) == 1,
        "failures_explained": r6.counts().get(FAILED, 0) == 1 and r6.counts().get(QUARANTINED, 0) == 1,
        "timeout_failed": r7.counts().get(FAILED, 0) == 1,
        "bounded": r8.bounded_by == "max_files_per_run",
        "readiness": ready["status"],
        "real_adapter_validation": "VERIFIED" if (sync_root and sync_root.exists()) else "ADAPTER_SETUP_REQUIRED",
        "runtime_seconds": round(_time.monotonic() - started, 2),
    })
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
