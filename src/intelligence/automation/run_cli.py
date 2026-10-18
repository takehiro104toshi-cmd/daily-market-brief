"""P12-A3 〜 A5 — P12 の CLI（`python -m src.intelligence.automation.run_cli`）。network ・資格情報は無い。A5 で Task Scheduler が起こす
`scheduled-run` と、人の手の `pin-runtime` ・`scheduler-install` ／ `-remove` ／ `-status` を足した（daemon ・service は無い）。

    scheduled-run  --slot-id <slot_id> --private-root --p9-root --p10-root --repo-root --runtime-root
                   （Task Scheduler が起こす。selection_clock_at は入口で 1 回観測。exit code は scheduled_run を見よ。
                    `--selection-clock-at <UTC ISO>` は人の診断だけの明示の上書き: task の定義は渡さない）
    pin-runtime    --private-root --repo-root                            （人: clean な HEAD を無人の実行の pin に）
    scheduler-install --private-root --p9-root --p10-root --repo-root --runtime-root --interpreter <python> [--apply]
    scheduler-remove  --private-root [--apply]      scheduler-status --private-root

    run            --request-file <正準な実行の要求の JSON> --private-root --p9-root --p10-root --repo-root --runtime-root
    retry          --run-id <前の run_id> --private-root --p9-root --p10-root --repo-root --runtime-root   （A4: attempt ＋ 1 ・retry_of）
    cancel         --run-id <run_id> --private-root                     （A4: 協調的な cancel の要求。kill ではない）
    classify       --run-id <run_id> --private-root
    recover-orphan / recover-crashed / recover-partial  --run-id <run_id> --private-root   （A4: 分類が先 ・曖昧なら拒む）
    repair-checkpoint / regenerate-status               --private-root                     （A4）
    release-lock   --private-root [--run-id <run_id>]                   （A4: stale と証明できた lock だけ）
    write-schedule --file <正準な schedule の JSON> --private-root
    write-calendar --file <正準な休日 calendar の JSON> --private-root

- PIT の欄は要求の file から来る（暗黙の scheduled_for は無い）。`datetime.now` は telemetry（ledger の recorded_at ・status の
  generated_at）だけに使い、意味の欄 ・identity ・artifact の byte に影響しない。
- 要求の operator は `human` でなければ拒む（A3 の CLI は人の手だけ）。資格情報の変数が在れば orchestration の前に失敗する。
- stdout は `REPORT:` の行だけ（run_id ・step ・commit ・status ・結果 code）。path ・private な値 ・例外の文は出さない。
  exit code: 0 ＝ SUCCEEDED ・1 ＝ FAILED ・2 ＝ 使い方。
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from typing import Any, Mapping, Optional, Sequence

from .calendar_authority import write_calendar_authority
from .cancel_authority import write_cancel_request
from .execution_request import AutomationExecutionRequest
from .failure_codes import AutomationError
from .holiday_calendar import HolidayCalendar
from .ledger_store import LedgerStore
from .preconditions import PrivateRoots, credential_present
from .process_probe import ProcessProbe
from .recovery import (recover_crashed, recover_orphan, recover_partial, regenerate_status, release_lock,
                       repair_checkpoint)
from .retry import build_retry_request, retry_summary
from .run_transaction import TransactionResult, classify_after_crash, commit_run
from .runtime_pin import pin_clean_head
from .schedule_authority import HUMAN_OPERATOR, write_schedule_authority
from .schedule_model import AutomationSchedule
from .scheduled_run import run_scheduled
from .scheduler_install import install_tasks, plan_install, remove_tasks, scheduler_status
from .task_definition import SchedulerPaths
from .task_scheduler_adapter import SchtasksAdapter, TaskSchedulerAdapter

REPORT_PREFIX = "REPORT: "
EXIT_SUCCEEDED, EXIT_FAILED, EXIT_USAGE = 0, 1, 2


def _presence_environment(environment: Mapping[str, str]) -> Mapping[str, str]:
    """値を保持しない環境の写し（名前 → 非空か）。前提条件は有無だけを見る。"""
    return {name: ("present" if value != "" else "") for name, value in environment.items()}


def _telemetry_clock() -> datetime:
    return datetime.now(timezone.utc).replace(microsecond=0)                           # telemetry だけ（PIT には使わない）


def _load_json(file_name: str) -> Any:
    try:
        with open(file_name, "rb") as handle:
            data = handle.read()
    except OSError:
        raise AutomationError("SCHEMA_INVALID", "INPUT_FILE_UNREADABLE") from None
    try:
        return json.loads(data.decode("utf-8"))
    except (ValueError, UnicodeDecodeError):
        raise AutomationError("SCHEMA_INVALID", "INPUT_FILE_NOT_JSON") from None


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="p12-automation", description="Phase 12 manual operational CLI (human only)",
                                     add_help=True)
    commands = parser.add_subparsers(dest="command", required=True)
    run = commands.add_parser("run", help="commit one explicitly requested run")
    for name in ("--request-file", "--private-root", "--p9-root", "--p10-root", "--repo-root", "--runtime-root"):
        run.add_argument(name, required=True)
    retry = commands.add_parser("retry", help="retry a FAILED / CRASHED / ORPHANED run as a new attempt (human only)")
    for name in ("--run-id", "--private-root", "--p9-root", "--p10-root", "--repo-root", "--runtime-root"):
        retry.add_argument(name, required=True)
    for command, help_text in (("cancel", "request cooperative cancellation of one run (human only)"),
                               ("recover-orphan", "record ORPHANED_FINALIZATION for a finalized run without a terminal record"),
                               ("recover-crashed", "record CRASHED for an open run whose process is provably gone"),
                               ("recover-partial", "preserve a .partial directory as .crashed evidence after classification")):
        sub = commands.add_parser(command, help=help_text)
        sub.add_argument("--run-id", required=True)
        sub.add_argument("--private-root", required=True)
    for command, help_text in (("repair-checkpoint", "catch the ledger head checkpoint up to a verified ledger tail"),
                               ("regenerate-status", "regenerate status.json from the verified ledger")):
        sub = commands.add_parser(command, help=help_text)
        sub.add_argument("--private-root", required=True)
    release = commands.add_parser("release-lock", help="release a lock proven stale (evidence kept under locks/stale)")
    release.add_argument("--private-root", required=True)
    release.add_argument("--run-id", required=False, default=None)
    scheduled = commands.add_parser("scheduled-run", help="unattended entry invoked by Task Scheduler (one slot)")
    for name in ("--slot-id", "--private-root", "--p9-root", "--p10-root", "--repo-root", "--runtime-root"):
        scheduled.add_argument(name, required=True)
    scheduled.add_argument("--selection-clock-at", required=False, default=None)
    pin = commands.add_parser("pin-runtime", help="pin the current clean HEAD as the unattended runtime anchor (human only)")
    pin.add_argument("--private-root", required=True)
    pin.add_argument("--repo-root", required=True)
    sched_install = commands.add_parser("scheduler-install", help="plan (and with --apply register) the P12 Task Scheduler tasks")
    for name in ("--private-root", "--p9-root", "--p10-root", "--repo-root", "--runtime-root", "--interpreter"):
        sched_install.add_argument(name, required=True)
    sched_install.add_argument("--apply", action="store_true")
    sched_remove = commands.add_parser("scheduler-remove", help="remove only P12-owned tasks (plan unless --apply)")
    sched_remove.add_argument("--private-root", required=True)
    sched_remove.add_argument("--apply", action="store_true")
    sched_status = commands.add_parser("scheduler-status", help="safe scheduler status projection (non-authority)")
    sched_status.add_argument("--private-root", required=True)
    for command, help_text in (("write-schedule", "write the schedule authority (human only)"),
                               ("write-calendar", "write the holiday calendar authority (human only)")):
        sub = commands.add_parser(command, help=help_text)
        sub.add_argument("--file", required=True)
        sub.add_argument("--private-root", required=True)
    classify = commands.add_parser("classify", help="classify the evidence of one run (read only)")
    classify.add_argument("--run-id", required=True)
    classify.add_argument("--private-root", required=True)
    return parser


def _report(stdout: Any, line: str) -> None:
    stdout.write(REPORT_PREFIX + line + "\n")


def _command_run(args: argparse.Namespace, stdout: Any, environment: Mapping[str, str]) -> int:
    if credential_present(environment):
        _report(stdout, "RUN_FAILED CODE=CREDENTIAL_PRESENT")                          # orchestration の前
        return EXIT_FAILED
    request = AutomationExecutionRequest.from_dict(_load_json(args.request_file))
    if request.operator != HUMAN_OPERATOR:
        raise AutomationError("SCHEMA_INVALID", "OPERATOR_NOT_HUMAN")
    _report(stdout, f"RUN_ID={request.run_id}")
    roots = PrivateRoots(args.p9_root, args.p10_root, args.private_root)
    result = commit_run(request, roots, repo_root=args.repo_root, runtime_root=args.runtime_root,
                        environment=_presence_environment(environment), clock=_telemetry_clock)
    return _report_transaction(result, stdout)


def _report_transaction(result: TransactionResult, stdout: Any) -> int:
    if result.execution is not None:
        for step in result.execution.step_results:
            suffix = f" CODE={step.failure_code}" if step.failure_code else ""
            _report(stdout, f"STEP {step.step_code} {step.status}{suffix}")
    for stage in result.stages_completed:
        _report(stdout, f"STAGE {stage}")
    if "LEDGER_REVERIFIED" in result.stages_completed:
        _report(stdout, f"LEDGER_COMMIT_OK RECORDS={result.ledger_record_count} HEAD={result.ledger_head_digest}")
    if result.status_projection_written:
        _report(stdout, "STATUS_PROJECTION_OK")
    if result.status == "SUCCEEDED":
        _report(stdout, "RUN_SUCCEEDED")
        return EXIT_SUCCEEDED
    _report(stdout, f"RUN_FAILED CODE={result.failure_code}")
    return EXIT_FAILED


def _command_retry(args: argparse.Namespace, stdout: Any, environment: Mapping[str, str]) -> int:
    if credential_present(environment):
        _report(stdout, "RUN_FAILED CODE=CREDENTIAL_PRESENT")
        return EXIT_FAILED
    roots = PrivateRoots(args.p9_root, args.p10_root, args.private_root)
    probe = ProcessProbe()
    state = LedgerStore(args.private_root).open_verified()
    request = build_retry_request(roots, args.run_id, state=state, probe=probe, operator=HUMAN_OPERATOR)
    summary = retry_summary(args.run_id, request)
    _report(stdout, f"RETRY_OF={summary['retry_of']} ATTEMPT={summary['attempt']}")
    _report(stdout, f"RUN_ID={request.run_id}")
    result = commit_run(request, roots, repo_root=args.repo_root, runtime_root=args.runtime_root,
                        environment=_presence_environment(environment), clock=_telemetry_clock, probe=probe)
    return _report_transaction(result, stdout)


def _command_recovery(args: argparse.Namespace, stdout: Any) -> int:
    roots = PrivateRoots(None, None, args.private_root)
    probe = ProcessProbe()
    if args.command == "cancel":
        document = write_cancel_request(args.private_root, args.run_id, operator=HUMAN_OPERATOR, requested_at=_telemetry_clock())
        _report(stdout, f"CANCEL_REQUESTED RUN_ID={document['run_id']}")
        return EXIT_SUCCEEDED
    if args.command in ("recover-orphan", "recover-crashed", "recover-partial"):
        evidence = classify_after_crash(roots, args.run_id, probe=probe)
        _report(stdout, f"RUN_CLASSIFICATION RUN_ID={args.run_id} CLASS={evidence['classification']} LOCK={evidence['lock_class']}")
        action = {"recover-orphan": recover_orphan, "recover-crashed": recover_crashed, "recover-partial": recover_partial}[args.command]
        outcome = action(roots, args.run_id, probe=probe, clock=_telemetry_clock)
        _report(stdout, f"RECOVERY {outcome['recovery']} RUN_ID={args.run_id}")
        return EXIT_SUCCEEDED
    if args.command == "repair-checkpoint":
        outcome = repair_checkpoint(roots, probe=probe, clock=_telemetry_clock)
        _report(stdout, f"RECOVERY {outcome['recovery']} RECORDS={outcome['ledger_record_count']} HEAD={outcome['ledger_head_digest']}")
        return EXIT_SUCCEEDED
    if args.command == "regenerate-status":
        outcome = regenerate_status(roots, clock=_telemetry_clock)
        _report(stdout, f"RECOVERY {outcome['recovery']} HEALTH={outcome['health_code']}")
        return EXIT_SUCCEEDED
    outcome = release_lock(roots, probe=probe, run_id=args.run_id)
    _report(stdout, f"LOCK {outcome['lock_class']} RELEASED={'YES' if outcome['released'] else 'NO'}")
    return EXIT_SUCCEEDED


def _command_scheduled_run(args: argparse.Namespace, stdout: Any, environment: Mapping[str, str]) -> int:
    if args.selection_clock_at is None:
        selection_clock_at = datetime.now(timezone.utc).replace(microsecond=0)         # 入口で 1 回だけ: slot の選択にだけ使う
    else:
        from .canonical import parse_utc_iso
        selection_clock_at = parse_utc_iso(args.selection_clock_at)                    # 人の診断の明示の上書き
    roots = PrivateRoots(args.p9_root, args.p10_root, args.private_root)
    outcome = run_scheduled(args.slot_id, roots, repo_root=args.repo_root, runtime_root=args.runtime_root,
                            environment=_presence_environment(environment), selection_clock_at=selection_clock_at,
                            clock=_telemetry_clock)
    _report(stdout, f"SCHEDULED_RUN SLOT={args.slot_id} OUTCOME={outcome.kind} CODE={outcome.code}")
    if outcome.run_id is not None:
        _report(stdout, f"RUN_ID={outcome.run_id}")
    if outcome.transaction is not None:
        _report_transaction(outcome.transaction, stdout)
    _report(stdout, f"EXIT={outcome.exit_code}")
    return outcome.exit_code


def _command_scheduler(args: argparse.Namespace, stdout: Any, adapter: TaskSchedulerAdapter) -> int:
    if args.command == "pin-runtime":
        head = pin_clean_head(args.private_root, args.repo_root, operator=HUMAN_OPERATOR, pinned_at=_telemetry_clock())
        _report(stdout, f"RUNTIME_PINNED ANCHOR={head}")
        return EXIT_SUCCEEDED
    if args.command == "scheduler-install":
        paths = SchedulerPaths(interpreter=args.interpreter, repo_root=args.repo_root, runtime_root=args.runtime_root,
                               private_root=args.private_root, p9_root=args.p9_root, p10_root=args.p10_root)
        plan = plan_install(args.private_root, paths, adapter)
        for task in plan.to_safe_dict()["tasks"]:
            _report(stdout, f"SCHEDULER_TASK NAME={task['task_name']} SLOT={task['slot_id']} ENABLED={'YES' if task['enabled'] else 'NO'} "
                            f"XML_DIGEST={task['xml_digest']}")
        if not args.apply:
            _report(stdout, f"SCHEDULER_PLAN TASKS={len(plan.definitions)} APPLIED=NO")
            return EXIT_SUCCEEDED
        outcome = install_tasks(args.private_root, plan, adapter, operator=HUMAN_OPERATOR)
        _report(stdout, f"SCHEDULER_INSTALLED TASKS={outcome['task_count']}")
        return EXIT_SUCCEEDED
    if args.command == "scheduler-remove":
        outcome = remove_tasks(args.private_root, adapter, operator=HUMAN_OPERATOR, apply=args.apply)
        _report(stdout, f"SCHEDULER_REMOVE APPLIED={'YES' if outcome['applied'] else 'NO'} REMOVED={len(outcome['removed'])} "
                        f"ABSENT={len(outcome['absent'])} NOT_OWNED={len(outcome['not_owned'])}")
        return EXIT_SUCCEEDED
    projection = scheduler_status(args.private_root, adapter)
    _report(stdout, "SCHEDULER_STATUS " + " ".join(f"{key.upper()}={value}" for key, value in sorted(projection.items())))
    return EXIT_SUCCEEDED


def _command_write_schedule(args: argparse.Namespace, stdout: Any) -> int:
    schedule = AutomationSchedule.from_dict(_load_json(args.file))
    digest = write_schedule_authority(args.private_root, schedule, operator=HUMAN_OPERATOR)
    _report(stdout, f"SCHEDULE_AUTHORITY_WRITTEN DIGEST={digest}")
    return EXIT_SUCCEEDED


def _command_write_calendar(args: argparse.Namespace, stdout: Any) -> int:
    calendar = HolidayCalendar.from_dict(_load_json(args.file))
    digest = write_calendar_authority(args.private_root, calendar, operator=HUMAN_OPERATOR)
    _report(stdout, f"CALENDAR_AUTHORITY_WRITTEN DIGEST={digest}")
    return EXIT_SUCCEEDED


def _command_classify(args: argparse.Namespace, stdout: Any) -> int:
    evidence = classify_after_crash(PrivateRoots(None, None, args.private_root), args.run_id)
    _report(stdout, f"RUN_CLASSIFICATION RUN_ID={args.run_id} CLASS={evidence['classification']}")
    return EXIT_SUCCEEDED


def main(argv: Optional[Sequence[str]] = None, stdout: Optional[Any] = None,
         environment: Optional[Mapping[str, str]] = None, scheduler: Optional[TaskSchedulerAdapter] = None) -> int:
    out = sys.stdout if stdout is None else stdout
    env = os.environ if environment is None else environment                           # 値は有無の比較だけ ・保持しない
    adapter = SchtasksAdapter() if scheduler is None else scheduler
    try:
        args = _parser().parse_args(argv)
    except SystemExit as exc:                                                          # argparse の使い方の誤り（文は argparse が stderr へ）
        return EXIT_USAGE if exc.code not in (0, None) else EXIT_SUCCEEDED
    try:
        if args.command == "run":
            return _command_run(args, out, env)
        if args.command == "retry":
            return _command_retry(args, out, env)
        if args.command == "scheduled-run":
            return _command_scheduled_run(args, out, env)
        if args.command in ("pin-runtime", "scheduler-install", "scheduler-remove", "scheduler-status"):
            return _command_scheduler(args, out, adapter)
        if args.command in ("cancel", "recover-orphan", "recover-crashed", "recover-partial", "repair-checkpoint", "regenerate-status",
                            "release-lock"):
            return _command_recovery(args, out)
        if args.command == "write-schedule":
            return _command_write_schedule(args, out)
        if args.command == "write-calendar":
            return _command_write_calendar(args, out)
        return _command_classify(args, out)
    except AutomationError as exc:
        _report(out, f"RUN_FAILED CODE={exc.public_code}")
        return EXIT_FAILED


if __name__ == "__main__":                                                             # pragma: no cover - module の入口
    raise SystemExit(main())


__all__ = ["EXIT_FAILED", "EXIT_SUCCEEDED", "EXIT_USAGE", "REPORT_PREFIX", "main"]
