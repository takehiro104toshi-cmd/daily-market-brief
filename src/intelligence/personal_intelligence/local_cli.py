"""P10-A4 — Phase 10 の private ・local だけの狭い CLI（対話の UI ・network ・J-Quants ・LLM ・既定の root ・時計なし）。

`python -m src.intelligence.personal_intelligence.local_cli <command> ...`:
- `init --p10-root PATH`: 明示の管理の初期化（`admin_init` ・部分の配置は拒む）。
- `apply ／ dry-run --p10-root PATH --decision FILE [--p9-root PATH] [--private]`: local の JSON の決定（欄の完全一致）を実行器へ。
- `review --p10-root PATH --p9-root PATH --at ISO --as-of-date YYYY-MM-DD [--private]`: 既定は組 ・期日の区分の件数だけ。
  `--private` を明示した時だけ private な行（P9 の id ・発行体を含む）を出す。
- `summary`（`review` と同じ引数）: 件数だけの安全な投影。

標準出力は 1 行の正準の JSON。既定の出力に profile の文 ・除外 ・id ・発行体 ・著者は出さない。拒否は `{"status":"REFUSED",...}` と
終了 code 2。root ・瞬間 ・日は全て明示（推測 ・既定 ・環境変数なし）。

記録: `docs/databank/PHASE10_A4_EXECUTOR_REVIEW_VIEW.md`。
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import date, datetime
from pathlib import Path
from typing import Any, Dict, Optional, Sequence

from .admin_init import InitRefusal, init_personal_root
from .decisions import DecisionInputError, decision_from_mapping
from .executor import ExecutionRefusal, apply_decision, dry_run_decision
from .personal_projection import personal_safe_projection
from .review_view import ReviewViewError, read_personal_review

MAX_DECISION_BYTES = 65536


class _Refused(Exception):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


def _emit(stream: Any, payload: Dict[str, Any]) -> None:
    stream.write(json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True) + "\n")


def _local_file(value: str) -> Path:
    path = Path(value)
    if not path.is_absolute() or ".." in path.parts:
        raise _Refused("INPUT_REJECTED:DECISION_PATH_REJECTED")
    if path.is_symlink() or not path.is_file():
        raise _Refused("INPUT_REJECTED:DECISION_FILE_MISSING")
    return path


def _decision(value: str) -> Any:
    data = _local_file(value).read_bytes()
    if len(data) > MAX_DECISION_BYTES:
        raise _Refused("INPUT_REJECTED:DECISION_TOO_LARGE")
    try:
        record = json.loads(data.decode("utf-8"))
    except (UnicodeDecodeError, ValueError):
        raise _Refused("INPUT_REJECTED:DECISION_NOT_JSON") from None
    try:
        return decision_from_mapping(record)
    except DecisionInputError as exc:
        raise _Refused(f"INPUT_REJECTED:{exc.code}") from None


def _instant(value: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        raise _Refused("INPUT_REJECTED:INVALID_AT") from None
    if parsed.tzinfo is None or parsed.tzinfo.utcoffset(parsed) is None:
        raise _Refused("INPUT_REJECTED:INSTANT_NOT_AWARE")
    return parsed


def _day(value: str) -> date:
    try:
        return date.fromisoformat(value)
    except ValueError:
        raise _Refused("INPUT_REJECTED:INVALID_AS_OF_DATE") from None


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="personal_intelligence", description="Phase 10 private local CLI")
    sub = parser.add_subparsers(dest="command", required=True)
    init = sub.add_parser("init")
    init.add_argument("--p10-root", required=True)
    for name in ("apply", "dry-run"):
        command = sub.add_parser(name)
        command.add_argument("--p10-root", required=True)
        command.add_argument("--decision", required=True)
        command.add_argument("--p9-root")
        command.add_argument("--private", action="store_true")
    for name in ("review", "summary"):
        command = sub.add_parser(name)
        command.add_argument("--p10-root", required=True)
        command.add_argument("--p9-root", required=True)
        command.add_argument("--at", required=True)
        command.add_argument("--as-of-date", required=True)
        if name == "review":
            command.add_argument("--private", action="store_true")
    return parser


def _review_payload(review: Any, private: bool) -> Dict[str, Any]:
    groups: Dict[str, int] = {}
    due: Dict[str, int] = {}
    for entry in review.entries:
        groups[entry.surface_group.value] = groups.get(entry.surface_group.value, 0) + 1
        due[entry.due_class.value] = due.get(entry.due_class.value, 0) + 1
    payload: Dict[str, Any] = {"command": "review", "entries": len(review.entries), "groups": groups,
                               "due_classes": due}
    if private:                                                                   # 明示した時だけ（private ・local）
        payload["private_entries"] = [
            {"record_kind": e.record_kind.value, "p9_root_id": e.p9_root_id, "issuer_id": e.issuer_id,
             "p9_status": e.p9_status, "review_due_on": e.review_due_on.isoformat() if e.review_due_on else None,
             "due_class": e.due_class.value, "attention": e.attention.value,
             "excluded_by_profile": e.excluded_by_profile, "surface_group": e.surface_group.value}
            for e in review.entries]
    return payload


def _run(args: argparse.Namespace) -> Dict[str, Any]:
    if args.command == "init":
        return {"command": "init", "status": init_personal_root(args.p10_root).value}
    if args.command in ("apply", "dry-run"):
        decision = _decision(args.decision)
        if args.command == "dry-run":
            result = dry_run_decision(decision, p10_root=args.p10_root, p9_root=args.p9_root)
            return {"command": "dry-run", "operation": result.operation, "status": result.status.value,
                    "refusal": result.refusal}
        receipt = apply_decision(decision, p10_root=args.p10_root, p9_root=args.p9_root)
        payload = {"command": "apply", "operation": receipt.operation, "status": receipt.status.value}
        if args.private:
            payload.update(root_id=receipt.root_id, revision_id=receipt.revision_id)
        return payload
    review = read_personal_review(args.p10_root, args.p9_root, at=_instant(args.at), as_of_date=_day(args.as_of_date))
    if args.command == "summary":
        projection = personal_safe_projection(review)
        return {"command": "summary", "counts": {k: v for k, v in sorted(vars(projection).items())
                                                 if isinstance(v, int)}}
    return _review_payload(review, args.private)


def main(argv: Optional[Sequence[str]] = None, stdout: Optional[Any] = None) -> int:
    stream = stdout if stdout is not None else sys.stdout
    args = _parser().parse_args(argv)
    try:
        _emit(stream, _run(args))
    except _Refused as exc:
        _emit(stream, {"command": args.command, "status": "REFUSED", "code": exc.code})
        return 2
    except (InitRefusal, ExecutionRefusal, ReviewViewError) as exc:
        code = f"{exc.code}:{exc.detail}" if exc.detail else exc.code
        _emit(stream, {"command": args.command, "status": "REFUSED", "code": code})
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
