"""P12-A3 — 人が手で使う P12 の CLI（`python -m src.intelligence.automation.run_cli`）。scheduler ・background ・network ・資格情報は無い。

    run            --request-file <正準な実行の要求の JSON> --private-root --p9-root --p10-root --repo-root --runtime-root
    write-schedule --file <正準な schedule の JSON> --private-root
    write-calendar --file <正準な休日 calendar の JSON> --private-root
    classify       --run-id <run_id> --private-root

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
from .execution_request import AutomationExecutionRequest
from .failure_codes import AutomationError
from .holiday_calendar import HolidayCalendar
from .preconditions import PrivateRoots, credential_present
from .run_transaction import classify_after_crash, commit_run
from .schedule_authority import HUMAN_OPERATOR, write_schedule_authority
from .schedule_model import AutomationSchedule

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
         environment: Optional[Mapping[str, str]] = None) -> int:
    out = sys.stdout if stdout is None else stdout
    env = os.environ if environment is None else environment                           # 値は有無の比較だけ ・保持しない
    try:
        args = _parser().parse_args(argv)
    except SystemExit as exc:                                                          # argparse の使い方の誤り（文は argparse が stderr へ）
        return EXIT_USAGE if exc.code not in (0, None) else EXIT_SUCCEEDED
    try:
        if args.command == "run":
            return _command_run(args, out, env)
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
