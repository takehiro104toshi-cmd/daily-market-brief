"""Formal review CLI（Phase 3.9.5）— `python -m src.intelligence.formal_review.cli <command>`。

build（derived のみ書く）/ list / show / status / reopen-check は formal Decision を書かない。
decide は 1 pattern だけ・packet_id 必須。--dry-run は guard と DecisionService.validate を実行して何も書かない。
exit: 0 ok / 1 validation failed / 2 policy / 3 formal review guard / 4 store corrupt。batch command は存在しない。
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import List, Optional

from ..decision.store import DecisionStoreCorrupt
from ..evaluation.store import EvaluationStoreCorrupt
from ..shadow_review.events import ShadowReviewStoreCorrupt
from .config import ACTIONS, FormalReviewPolicy, load_formal_review_policy
from .errors import FormalReviewError, FormalReviewPolicyError
from .service import FormalDecisionRequest, FormalReviewService

EXIT_OK, EXIT_VALIDATION, EXIT_POLICY, EXIT_GUARD, EXIT_CORRUPT = 0, 1, 2, 3, 4


def resolve_root(data_root_override: str = "") -> Path:
    from ..corpus_research.batch_import import resolve_data_root

    return resolve_data_root(data_root_override)


def _dump(payload) -> None:
    print(json.dumps(payload, ensure_ascii=False, indent=1, sort_keys=True, default=str))


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Compass formal review (Phase 3.9.5) — human-bound evidence packets")
    parser.add_argument("--data-root", default="")
    sub = parser.add_subparsers(dest="command")
    sub.add_parser("build", help="build derived packets / queue / summary (writes compass_formal_review/ only)")
    sub.add_parser("list", help="ordered queue (read-only)")
    p_show = sub.add_parser("show", help="one packet (read-only)")
    p_show.add_argument("pattern_id")
    p_dec = sub.add_parser("decide", help="ONE formal human decision bound to a packet (MUTATING unless --dry-run)")
    p_dec.add_argument("pattern_id", help="exactly one pattern id")
    p_dec.add_argument("--packet", required=True, dest="packet_id")
    p_dec.add_argument("--action", required=True, choices=sorted(ACTIONS))
    p_dec.add_argument("--reason", required=True)
    p_dec.add_argument("--actor", required=True, help="human actor id (actor_type is always HUMAN)")
    p_dec.add_argument("--acknowledge-sibling", action="append", default=[], dest="acknowledge")
    p_dec.add_argument("--related-pattern", default="")
    p_dec.add_argument("--replacement-pattern", default="")
    p_dec.add_argument("--reason-category", default="")
    p_dec.add_argument("--disposition", default="", help="DUPLICATE_OR_OVERLAPPING (KEEP_REVIEWING only)")
    p_dec.add_argument("--dry-run", action="store_true")
    sub.add_parser("status", help="operational metrics (read-only)")
    sub.add_parser("reopen-check", help="REOPEN_ELIGIBLE status of REJECTED patterns (read-only; never writes)")
    sub.add_parser("validate-policy", help="validate compass_formal_review and print its digest")
    args = parser.parse_args(argv)
    if not args.command:
        parser.print_help()
        return EXIT_VALIDATION
    try:
        if args.command == "validate-policy":
            policy = load_formal_review_policy()
            _dump({"compass_formal_review": {"policy_version": policy.policy_version, "digest": policy.digest(),
                                             "policy": policy.as_dict()}, "mutation": "NONE"})
            return EXIT_OK
        service = FormalReviewService(resolve_root(args.data_root))
        if args.command == "build":
            _dump(service.build())
            return EXIT_OK
        if args.command == "list":
            queue = service.store.queue()
            _dump({"sections": {k: [{f: r.get(f) for f in ("queue_rank", "pattern_id", "packet_id", "recommendation",
                                                            "decision_state", "stability_class", "allowed_next_actions",
                                                            "warnings")} for r in rows]
                                for k, rows in (queue.get("sections") or {}).items()},
                   "context": queue.get("context"), "built_at": queue.get("built_at"), "mutation": "NONE"})
            return EXIT_OK
        if args.command == "show":
            packet = service.store.packet(args.pattern_id)
            _dump(packet or {"pattern_id": args.pattern_id, "found": False})
            return EXIT_OK if packet else EXIT_VALIDATION
        if args.command == "status":
            summary = service.store.summary()
            _dump({"metrics": summary.get("metrics"), "population": summary.get("population"),
                   "built_at": summary.get("built_at"), "decision_rows": len(service.decision_store.records()),
                   "mutation": "NONE"})
            return EXIT_OK
        if args.command == "reopen-check":
            _dump({"rejected": service.reopen_check(), "mutation": "NONE"})
            return EXIT_OK
        request = FormalDecisionRequest(pattern_id=args.pattern_id, action=args.action, packet_id=args.packet_id,
                                        reason=args.reason, actor=args.actor, acknowledge_siblings=tuple(args.acknowledge),
                                        related_pattern_id=args.related_pattern, replacement_pattern_id=args.replacement_pattern,
                                        reason_category=args.reason_category, disposition=args.disposition)
        result = service.decide(request, dry_run=bool(args.dry_run))
        _dump(result)
        return EXIT_OK if result["validation"]["ok"] else EXIT_VALIDATION
    except FormalReviewPolicyError as exc:
        _dump({"error": exc.code, "detail": exc.message, "mutation": "NONE"})
        return EXIT_POLICY
    except FormalReviewError as exc:
        _dump({"error": exc.code, "detail": exc.message, "mutation": "NONE (guard failed closed)"})
        return EXIT_GUARD
    except (DecisionStoreCorrupt, EvaluationStoreCorrupt, ShadowReviewStoreCorrupt) as exc:
        _dump({"error": type(exc).__name__, "detail": str(exc), "mutation": "NONE"})
        return EXIT_CORRUPT


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
