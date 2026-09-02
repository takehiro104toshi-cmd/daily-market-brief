"""Decision CLI（Phase 3.9.1）— `python -m src.intelligence.decision.cli <command>`。

read command（list / history / show / gate / validate）は何も書かない。
mutating command は `decide` だけ（明示。`--dry-run` で validate と同じ）。UI は作らない。
exit: 0 = ok / 1 = validation failed or blocked / 2 = policy or store corruption。
"""
from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional

from ..corpus_research.store import research_root
from .corpus_state import corpus_state_from_data_root
from .evidence import build_evidence_snapshot
from .models import ACTOR_HUMAN
from .policy import DECISION_STATES, PolicyError, load_decision_policy
from .service import DecisionRequest, DecisionService
from .store import DecisionStore, DecisionStoreCorrupt, decisions_root


def resolve_root(data_root_override: str = "") -> Path:
    from ..corpus_research.batch_import import resolve_data_root        # processor / batch_import と同じ解決順

    return resolve_data_root(data_root_override)


def build_service(root: Path, policy=None) -> DecisionService:
    policy = policy or load_decision_policy()
    now = datetime.now(timezone.utc)
    return DecisionService(DecisionStore(decisions_root(root)), policy,
                           corpus_state_resolver=lambda: corpus_state_from_data_root(root, now),
                           evidence_builder=lambda pid: build_evidence_snapshot(research_root(root), pid))


def _dump(payload) -> None:
    print(json.dumps(payload, ensure_ascii=False, indent=1, sort_keys=True, default=str))


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Compass decision foundation (Phase 3.9.1) — read commands never write")
    parser.add_argument("--data-root", default="", help="INTELLIGENCE_DATA_ROOT override (default: local config chain)")
    sub = parser.add_subparsers(dest="command")
    sub.add_parser("list", help="current decision state per pattern (read-only)")
    p_hist = sub.add_parser("history", help="append-only history of one pattern (read-only)")
    p_hist.add_argument("--pattern", required=True)
    p_show = sub.add_parser("show", help="one decision record (read-only)")
    p_show.add_argument("--decision", required=True)
    sub.add_parser("gate", help="CORPUS_100 formal review gate status (read-only)")
    for name, help_text in (("validate", "dry-run a proposed decision (read-only)"),
                            ("decide", "APPEND a human decision (MUTATING; --dry-run to validate only)")):
        p = sub.add_parser(name, help=help_text)
        p.add_argument("--pattern", required=True)
        p.add_argument("--type", required=True, choices=list(DECISION_STATES), dest="decision_type")
        p.add_argument("--reason", default="")
        p.add_argument("--actor", required=True, help="human actor name (actor_type is always HUMAN from the CLI)")
        p.add_argument("--notes", default="")
        p.add_argument("--idempotency-key", default="")
        if name == "decide":
            p.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)
    if not args.command:
        parser.print_help()
        return 1
    root = resolve_root(args.data_root)
    try:
        service = build_service(root)
        if args.command == "list":
            _dump({"decisions_file_exists": service.store.exists(), "patterns": service.current_states()})
            return 0
        if args.command == "history":
            _dump({"pattern_id": args.pattern, "history": service.history(args.pattern)})
            return 0
        if args.command == "show":
            rec = service.get(args.decision)
            _dump(rec or {"decision_id": args.decision, "found": False})
            return 0 if rec else 1
        if args.command == "gate":
            _dump(service.gate_status())
            return 0
        request = DecisionRequest(pattern_id=args.pattern, decision_type=args.decision_type, reason=args.reason,
                                  actor=args.actor, actor_type=ACTOR_HUMAN, notes=args.notes,
                                  idempotency_key=args.idempotency_key)
        if args.command == "validate" or getattr(args, "dry_run", False):
            v = service.validate(request)
            _dump({"mutation": "NONE (dry run)", **v.as_dict()})
            return 0 if v.ok else 1
        outcome = service.decide(request)
        _dump({"mutation": "APPEND decisions.jsonl" if outcome.appended else "NONE", **outcome.as_dict()})
        return 0 if outcome.validation.ok else 1
    except DecisionStoreCorrupt as exc:
        _dump({"error": "DECISION_STORE_CORRUPT", "line": exc.line_no, "code": exc.code, "detail": exc.detail,
               "hint": "decision log must not be edited; restore from backup and do not derive state from it"})
        return 2
    except PolicyError as exc:
        _dump({"error": "POLICY_INVALID", "detail": str(exc)})
        return 2


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
