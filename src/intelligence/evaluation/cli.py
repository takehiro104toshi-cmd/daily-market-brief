"""Evaluation CLI（Phase 3.9.2）— `python -m src.intelligence.evaluation.cli <command>`。

read command（summary / show / list / validate-policy）は何も書かない。
`evaluate` だけが derived evaluation store を置換する（`--dry-run` で完全 read-only）。
decision / corpus / research artifact / DNA へは、どの command からも書かない。
exit: 0 = ok / 1 = 見つからない・未評価 / 2 = policy error or store corruption。
"""
from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional

from ..corpus_research.store import research_root
from .config import PolicyError, load_policies
from .engine import EvaluationEngine
from .score import ordering_key
from .store import EvaluationStore, EvaluationStoreCorrupt, evaluation_root


def resolve_root(data_root_override: str = "") -> Path:
    from ..corpus_research.batch_import import resolve_data_root      # processor / batch_import と同じ解決順

    return resolve_data_root(data_root_override)


def corpus_state_for(root: Path) -> dict:
    """Phase 3.9.1 と同じ canonical metric（eligible_for_pattern_evidence）。無ければ 0 件。"""
    from ..decision.corpus_state import corpus_state_from_data_root

    return corpus_state_from_data_root(root, datetime.now(timezone.utc)).as_dict()


def build_engine(root: Path, decision_signals: bool = False) -> EvaluationEngine:
    evaluation_policy, recommendation_policy = load_policies()
    lookup = None
    if decision_signals:                                   # 任意。read-only（decision へは書かない）
        from ..decision.store import DecisionStore, decisions_root
        from ..decision.state import derive_current_states

        store = DecisionStore(decisions_root(root))
        states = derive_current_states(store.records()) if store.exists() else {}
        lookup = lambda pid: (states[pid].state if pid in states else "")   # noqa: E731
    return EvaluationEngine(research_root(root), EvaluationStore(evaluation_root(root)),
                            evaluation_policy, recommendation_policy,
                            corpus_state=corpus_state_for(root), decision_state_lookup=lookup)


def _dump(payload) -> None:
    print(json.dumps(payload, ensure_ascii=False, indent=1, sort_keys=True, default=str))


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="Compass evaluation engine (Phase 3.9.2) — read commands never write; "
                    "evaluate writes only the derived evaluation store")
    parser.add_argument("--data-root", default="", help="INTELLIGENCE_DATA_ROOT override (default: local config chain)")
    parser.add_argument("--pattern-version", default="1.0.0")
    sub = parser.add_subparsers(dest="command")
    p_eval = sub.add_parser("evaluate", help="evaluate every pattern (WRITES the derived evaluation store)")
    p_eval.add_argument("--dry-run", action="store_true", help="evaluate and print, write nothing")
    p_eval.add_argument("--decision-signals", action="store_true",
                        help="also derive reopen/adverse signals by READING the decision store")
    p_one = sub.add_parser("evaluate-one", help="evaluate a single pattern and print it (never writes)")
    p_one.add_argument("--pattern", required=True)
    p_show = sub.add_parser("show", help="show one stored evaluation (read-only)")
    p_show.add_argument("--pattern", required=True)
    sub.add_parser("summary", help="stored evaluation snapshot (read-only)")
    p_list = sub.add_parser("list", help="stored evaluations ordered for review (read-only)")
    p_list.add_argument("--state", default="")
    p_list.add_argument("--limit", type=int, default=20)
    sub.add_parser("validate-policy", help="validate config policies and print their digests (read-only)")
    args = parser.parse_args(argv)
    if not args.command:
        parser.print_help()
        return 1
    root = resolve_root(args.data_root)
    try:
        if args.command == "validate-policy":
            evaluation_policy, recommendation_policy = load_policies()
            _dump({"compass_evaluation": {"policy_version": evaluation_policy.policy_version,
                                          "digest": evaluation_policy.digest(),
                                          "policy": evaluation_policy.as_dict()},
                   "compass_recommendation": {"policy_version": recommendation_policy.policy_version,
                                              "digest": recommendation_policy.digest(),
                                              "policy": recommendation_policy.as_dict()},
                   "corpus": corpus_state_for(root)})
            return 0
        store = EvaluationStore(evaluation_root(root))
        if args.command == "summary":
            snap = store.snapshot()
            _dump(snap or {"evaluated": 0, "note": "no evaluation has been written yet"})
            return 0 if snap else 1
        if args.command == "show":
            row = store.get(args.pattern)
            _dump(row or {"pattern_id": args.pattern, "found": False})
            return 0 if row else 1
        if args.command == "list":
            evaluation_policy, _ = load_policies()
            rows = [r for r in store.records() if not args.state or r.get("recommendation") == args.state]
            rows.sort(key=lambda r: ordering_key(r, evaluation_policy))
            _dump({"count": len(rows), "ordering": "applicable HIGH axes, then reference score, then share",
                   "items": [{k: r[k] for k in ("pattern_id", "pattern_type", "recommendation", "axis_states",
                                                "reference_score", "reference_score_comparable",
                                                "applicable_weight_sum", "blocking_rules")}
                             for r in rows[:max(1, args.limit)]]})
            return 0
        engine = build_engine(root, decision_signals=getattr(args, "decision_signals", False))
        if args.command == "evaluate-one":
            report, records = engine.evaluate_all(args.pattern_version, dry_run=True, only_pattern=args.pattern)
            if not records:
                _dump({"pattern_id": args.pattern, "found": False, "mutation": "NONE"})
                return 1
            _dump({"mutation": "NONE (read-only)", **records[0].as_dict()})
            return 0
        report, _ = engine.evaluate_all(args.pattern_version, dry_run=args.dry_run)
        _dump({"mutation": "NONE (dry run)" if args.dry_run else "REPLACE compass_evaluation/evaluations.jsonl",
               **report.as_dict()})
        return 0
    except EvaluationStoreCorrupt as exc:
        _dump({"error": "EVALUATION_STORE_CORRUPT", "line": exc.line_no, "code": exc.code, "detail": exc.detail,
               "hint": "the evaluation store is derived; re-run `evaluate` to rebuild it"})
        return 2
    except PolicyError as exc:
        _dump({"error": "POLICY_ERROR", "detail": str(exc),
               "hint": "bump compass_evaluation / compass_recommendation policy_version instead of "
                       "changing thresholds in place"})
        return 2


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
