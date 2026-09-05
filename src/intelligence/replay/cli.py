"""Replay CLI（Phase 3.9.4）— `python -m src.intelligence.replay.cli <command>`。

run は <data_root>/compass_replay/ と一時 workspace にしか書かない。production corpus / research /
evaluation / shadow review / decision / DNA へは何も書かない。PDF も開かない。
exit: 0 = ok / 1 = 未生成 / 2 = policy error / 3 = replay fail-closed（漏洩・改変・不一致など）。
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, List, Optional

from .config import MODES, ORDERINGS, load_replay_policy
from .errors import ReplayError, ReplayPolicyError
from .runner import ReplayRunner
from .store import MANIFEST_FILE, SUMMARY_FILE, TIMELINES_FILE, ReplayStore, replay_root


def resolve_root(data_root_override: str = "") -> Path:
    from ..corpus_research.batch_import import resolve_data_root

    return resolve_data_root(data_root_override)


def _dump(payload: Any) -> None:
    print(json.dumps(payload, ensure_ascii=False, indent=1, sort_keys=True, default=str))


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Compass replay (Phase 3.9.4) — retrospective stability study")
    parser.add_argument("--data-root", default="")
    sub = parser.add_subparsers(dest="command")
    p_run = sub.add_parser("run", help="run a replay over an immutable snapshot (writes compass_replay/ only)")
    p_run.add_argument("--mode", default="", choices=[""] + list(MODES))
    p_run.add_argument("--ordering", default="", choices=[""] + list(ORDERINGS))
    p_run.add_argument("--retain-temp", action="store_true")
    sub.add_parser("validate-policy", help="validate compass_replay and print its digest (read-only)")
    sub.add_parser("list-runs", help="list stored runs (read-only)")
    p_sum = sub.add_parser("summary", help="summary of a run (read-only)")
    p_sum.add_argument("--run", default="")
    p_sum.add_argument("--section", default="", help="e.g. approve_stress / reject_stress / formal_review_input")
    p_show = sub.add_parser("show", help="timeline of one pattern (read-only)")
    p_show.add_argument("pattern_id")
    p_show.add_argument("--run", default="")
    args = parser.parse_args(argv)
    if not args.command:
        parser.print_help()
        return 1
    root = resolve_root(args.data_root)
    try:
        if args.command == "validate-policy":
            policy = load_replay_policy()
            _dump({"compass_replay": {"policy_version": policy.policy_version, "digest": policy.digest(),
                                      "policy": policy.as_dict()}, "mutation": "NONE"})
            return 0
        store = ReplayStore(replay_root(root))
        if args.command == "list-runs":
            _dump({"runs": store.list_runs(), "latest": store.latest(), "mutation": "NONE"})
            return 0
        if args.command in ("summary", "show"):
            run_id = args.run or str(store.latest().get("run_id", ""))
            if not run_id:
                _dump({"note": "no replay run yet; run `run` first"})
                return 1
            if args.command == "summary":
                summary = store.read_json(run_id, SUMMARY_FILE)
                if args.section:
                    _dump({"run_id": run_id, args.section: summary.get(args.section), "mutation": "NONE"})
                else:
                    _dump({**{k: v for k, v in summary.items() if k != "pattern_metrics"}, "mutation": "NONE"})
                return 0 if summary else 1
            rows = [r for r in store.read_jsonl(run_id, TIMELINES_FILE) if r.get("pattern_id") == args.pattern_id]
            summary = store.read_json(run_id, SUMMARY_FILE)
            _dump({"run_id": run_id, "pattern_id": args.pattern_id, "rows": rows,
                   "metrics": (summary.get("pattern_metrics") or {}).get(args.pattern_id), "mutation": "NONE"})
            return 0 if rows else 1
        runner = ReplayRunner(root, mode=args.mode, ordering=args.ordering,
                              retain_temp=True if args.retain_temp else None)
        result = runner.run()
        _dump({**result, "mutation": "WRITE compass_replay/runs/<run_id>/ (derived) and latest.json"})
        return 0
    except ReplayPolicyError as exc:
        _dump({"error": "REPLAY_POLICY_ERROR", "detail": str(exc)})
        return 2
    except ReplayError as exc:
        _dump({"error": type(exc).__name__, "detail": str(exc), "mutation": "NONE (production)",
               "hint": "replay failed closed; nothing was published"})
        return 3


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
