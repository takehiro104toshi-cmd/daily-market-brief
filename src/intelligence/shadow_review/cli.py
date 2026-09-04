"""Shadow Review CLI（Phase 3.9.3）— `python -m src.intelligence.shadow_review.cli <command>`。

書き込みは 2 系統だけ:
    build   … derived（queue.json / summary.json / current_reviews.json）を atomic 置換。`--dry-run` は完全 read-only
    record  … 人間レビュー 1 件を review_events.jsonl へ append（append-only・不変）

summary / list / show / history / validate-policy / validate-events は何も書かない。
formal Decision を書く command は存在しない。DNA へ promote する command も存在しない。
exit: 0 = ok / 1 = 見つからない・未生成 / 2 = policy error or store corruption / 3 = 書き込み拒否。
"""
from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from ..corpus_research.store import research_root
from ..evaluation.config import PolicyError, load_policies
from ..evaluation.store import EvaluationStore, EvaluationStoreCorrupt, evaluation_root
from .config import (
    MISSING_CATEGORIES,
    OUTCOMES,
    REVIEWER_TYPE_HUMAN,
    SECTION_ADVERSE_OVERFLOW,
    SECTION_BACKLOG,
    SECTION_MAIN,
    SECTION_WATCH,
    ShadowReviewPolicyError,
    load_shadow_review_policy,
)
from .events import ShadowReviewEventStore, ShadowReviewStoreCorrupt, shadow_review_root
from .material import material_digest
from .models import ShadowReviewValidationError, shadow_review_id_for
from .queue import (
    CURRENT_REVIEWS_FILE,
    QUEUE_FILE,
    SUMMARY_FILE,
    ShadowReviewQueueBuilder,
    read_json,
)
from .state import derive_current_reviews


def resolve_root(data_root_override: str = "") -> Path:
    from ..corpus_research.batch_import import resolve_data_root      # 他 Phase と同じ解決順

    return resolve_data_root(data_root_override)


def corpus_state_for(root: Path) -> Dict[str, Any]:
    """Phase 3.9.1 / 3.9.2 と同じ canonical metric（eligible_for_pattern_evidence）。読み取りのみ。"""
    from ..decision.corpus_state import corpus_state_from_data_root

    return corpus_state_from_data_root(root, datetime.now(timezone.utc)).as_dict()


def build_builder(root: Path) -> ShadowReviewQueueBuilder:
    evaluation_policy, recommendation_policy = load_policies()
    return ShadowReviewQueueBuilder(
        research_root(root), EvaluationStore(evaluation_root(root)),
        ShadowReviewEventStore(shadow_review_root(root)), load_shadow_review_policy(),
        evaluation_policy, recommendation_policy, corpus_state=corpus_state_for(root))


def _dump(payload: Any) -> None:
    print(json.dumps(payload, ensure_ascii=False, indent=1, sort_keys=True, default=str))


def _sections(queue: Dict[str, Any], section: str) -> List[Dict[str, Any]]:
    if section == SECTION_MAIN:
        return list(queue.get("main") or [])
    if section == SECTION_ADVERSE_OVERFLOW:
        return list(queue.get("adverse_overflow") or [])
    if section == SECTION_WATCH:
        return list(queue.get("watch") or [])
    return list((queue.get("backlog") or {}).get("items") or [])


def _record(args, root: Path) -> int:
    """人間レビューを 1 件 append する（唯一の history write）。"""
    policy = load_shadow_review_policy()
    evaluation_policy, recommendation_policy = load_policies()
    store = EvaluationStore(evaluation_root(root))
    evaluation = store.get(args.pattern) if store.exists() else None
    if evaluation is None:
        _dump({"error": "PATTERN_NOT_EVALUATED", "pattern_id": args.pattern,
               "hint": "run `python -m src.intelligence.evaluation.cli evaluate` first"})
        return 1
    events = ShadowReviewEventStore(shadow_review_root(root))
    queue = read_json(shadow_review_root(root) / QUEUE_FILE)
    rank, section = 0, SECTION_BACKLOG
    for name in (SECTION_MAIN, SECTION_ADVERSE_OVERFLOW, SECTION_WATCH):
        for card in _sections(queue, name):
            if str(card.get("pattern_id")) == args.pattern:
                rank, section = int(card.get("queue_rank", 0) or 0), name
    lifecycle = ""
    for card in _sections(queue, SECTION_MAIN) + _sections(queue, SECTION_ADVERSE_OVERFLOW) + \
            _sections(queue, SECTION_WATCH):
        if str(card.get("pattern_id")) == args.pattern:
            lifecycle = str(card.get("lifecycle_status", ""))
    structured: Dict[str, Any] = {}
    if args.missing:
        structured["missing"] = [c.strip() for c in str(args.missing).split(",") if c.strip()]
    corpus = corpus_state_for(root)
    payload: Dict[str, Any] = {
        "pattern_id": args.pattern,
        "reviewed_at": datetime.now(timezone.utc).isoformat(),
        "reviewer_id": args.reviewer or policy.default_reviewer_id,
        "reviewer_type": REVIEWER_TYPE_HUMAN,
        "review_outcome": args.outcome,
        "reason": args.reason or "",
        "structured_reason": structured,
        "related_pattern_id": args.related_pattern or "",
        "recommendation_at_review": str(evaluation.get("recommendation", "")),
        "axis_states_at_review": dict(evaluation.get("axis_states") or {}),
        "axis_applicability_at_review": dict(evaluation.get("axis_applicability") or {}),
        "reference_score_at_review": evaluation.get("reference_score"),
        "queue_rank_at_review": rank,
        "queue_section_at_review": section,
        "material_digest_at_review": material_digest(evaluation, lifecycle, policy),
        "evaluation_id": str(evaluation.get("evaluation_id", "")),
        "inputs_digest": str(evaluation.get("inputs_digest", "")),
        "lifecycle_at_review": lifecycle,
        "evaluation_policy_version": evaluation_policy.policy_version,
        "evaluation_policy_digest": evaluation_policy.digest(),
        "recommendation_policy_version": recommendation_policy.policy_version,
        "recommendation_policy_digest": recommendation_policy.digest(),
        "shadow_review_policy_version": policy.policy_version,
        "shadow_review_policy_digest": policy.digest(),
        "corpus_size": int(corpus.get("eligible", 0)),
        "corpus_milestone": str(corpus.get("milestone", "")),
        "shadow_mode": bool(evaluation.get("shadow_mode", True)),
        "formal_review_gate_reached": bool(evaluation.get("formal_review_gate_reached", False)),
        "schema_version": "1.0.0", "sequence": 0, "previous_record_hash": "", "record_hash": "",
    }
    payload["shadow_review_id"] = shadow_review_id_for(payload)
    result = events.append(payload, policy)
    record = result["record"]
    _dump({"appended": result["appended"], "reason": result["reason"],
           "shadow_review_id": record.shadow_review_id, "sequence": record.sequence,
           "pattern_id": record.pattern_id, "review_outcome": record.review_outcome,
           "mutation": "APPEND review_events.jsonl" if result["appended"] else "NONE",
           "note": "shadow review feedback only; no formal decision and no DNA promotion"})
    return 0


def main(argv: Optional[List[str]] = None) -> int:  # noqa: C901 CLI の分岐は 1 箇所に集める
    parser = argparse.ArgumentParser(
        description="Compass shadow review (Phase 3.9.3) — build writes only derived files, "
                    "record appends only human review history; no decision or DNA writes exist")
    parser.add_argument("--data-root", default="", help="INTELLIGENCE_DATA_ROOT override")
    parser.add_argument("--pattern-version", default="1.0.0")
    sub = parser.add_subparsers(dest="command")
    p_build = sub.add_parser("build", help="rebuild the derived queue (WRITES derived files only)")
    p_build.add_argument("--dry-run", action="store_true", help="build and print, write nothing")
    sub.add_parser("summary", help="stored queue summary (read-only)")
    p_list = sub.add_parser("list", help="stored queue items (read-only)")
    p_list.add_argument("--section", default=SECTION_MAIN,
                        choices=[SECTION_MAIN, SECTION_ADVERSE_OVERFLOW, SECTION_WATCH, SECTION_BACKLOG])
    p_list.add_argument("--limit", type=int, default=20)
    p_show = sub.add_parser("show", help="show one review card (read-only)")
    p_show.add_argument("pattern_id")
    p_history = sub.add_parser("history", help="human review history for one pattern (read-only)")
    p_history.add_argument("pattern_id")
    sub.add_parser("validate-policy", help="validate the shadow review policy and print its digest (read-only)")
    sub.add_parser("validate-events", help="validate the append-only event chain (read-only)")
    p_rec = sub.add_parser("record", help="append one human review event (the only history write)")
    p_rec.add_argument("--pattern", required=True)
    p_rec.add_argument("--outcome", required=True, choices=list(OUTCOMES))
    p_rec.add_argument("--reason", default="")
    p_rec.add_argument("--missing", default="", help=f"comma separated: {','.join(MISSING_CATEGORIES)}")
    p_rec.add_argument("--related-pattern", dest="related_pattern", default="")
    p_rec.add_argument("--reviewer", default="")
    args = parser.parse_args(argv)
    if not args.command:
        parser.print_help()
        return 1
    root = resolve_root(args.data_root)
    review_root = shadow_review_root(root)
    try:
        if args.command == "validate-policy":
            policy = load_shadow_review_policy()
            _dump({"compass_shadow_review": {"policy_version": policy.policy_version,
                                             "digest": policy.digest(), "policy": policy.as_dict()},
                   "corpus": corpus_state_for(root), "mutation": "NONE"})
            return 0
        if args.command == "validate-events":
            store = ShadowReviewEventStore(review_root)
            if not store.exists():
                _dump({"valid": True, "events": 0, "note": "no shadow review has been recorded yet",
                       "mutation": "NONE"})
                return 0
            _dump({**store.validate(), "mutation": "NONE"})
            return 0
        if args.command == "summary":
            summary = read_json(review_root / SUMMARY_FILE)
            _dump(summary or {"escalated": 0, "note": f"no {SUMMARY_FILE} yet; run `build`"})
            return 0 if summary else 1
        if args.command == "list":
            queue = read_json(review_root / QUEUE_FILE)
            if not queue:
                _dump({"note": f"no {QUEUE_FILE} yet; run `build`"})
                return 1
            items = _sections(queue, args.section)
            _dump({"section": args.section, "count": len(items),
                   "ordering": queue.get("ordering"), "items": items[:max(1, args.limit)],
                   "mutation": "NONE"})
            return 0
        if args.command == "show":
            queue = read_json(review_root / QUEUE_FILE)
            for name in (SECTION_MAIN, SECTION_ADVERSE_OVERFLOW, SECTION_WATCH):
                for card in _sections(queue, name):
                    if str(card.get("pattern_id")) == args.pattern_id:
                        _dump({**card, "mutation": "NONE"})
                        return 0
            _dump({"pattern_id": args.pattern_id, "found": False,
                   "hint": "the pattern may be in BACKLOG; run `list --section BACKLOG`"})
            return 1
        if args.command == "history":
            store = ShadowReviewEventStore(review_root)
            history = store.for_pattern(args.pattern_id) if store.exists() else []
            policy = load_shadow_review_policy()
            derived = derive_current_reviews(history, policy)
            _dump({"pattern_id": args.pattern_id, "review_count": len(history),
                   "events": [e.as_dict() for e in history],
                   "current": derived[args.pattern_id].as_dict() if args.pattern_id in derived else {},
                   "mutation": "NONE"})
            return 0 if history else 1
        if args.command == "record":
            return _record(args, root)
        builder = build_builder(root)
        report, queue_doc, _summary_doc, _current = builder.build(args.pattern_version, dry_run=args.dry_run)
        payload = report.as_dict()
        if args.dry_run:
            payload["top_n_composition"] = [
                {"queue_rank": c["queue_rank"], "pattern_id": c["pattern_id"],
                 "pattern_type": c["pattern_type"], "recommendation": c["recommendation"]}
                for c in queue_doc.get("main") or []]
            payload["backlog"] = {k: v for k, v in (queue_doc.get("backlog") or {}).items() if k != "items"}
        _dump(payload)
        return 0
    except ShadowReviewValidationError as exc:
        _dump({"error": "SHADOW_REVIEW_WRITE_REJECTED", "errors": exc.errors, "mutation": "NONE"})
        return 3
    except ShadowReviewStoreCorrupt as exc:
        _dump({"error": "SHADOW_REVIEW_EVENTS_CORRUPT", "line": exc.line_no, "code": exc.code,
               "detail": exc.detail,
               "hint": "review_events.jsonl is human history and is never rewritten automatically"})
        return 2
    except EvaluationStoreCorrupt as exc:
        _dump({"error": "EVALUATION_STORE_CORRUPT", "line": exc.line_no, "code": exc.code, "detail": exc.detail,
               "hint": "the evaluation store is derived; re-run the Phase 3.9.2 `evaluate` command"})
        return 2
    except (ShadowReviewPolicyError, PolicyError) as exc:
        _dump({"error": "POLICY_ERROR", "detail": str(exc),
               "hint": "bump compass_shadow_review policy_version instead of changing it in place"})
        return 2


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
