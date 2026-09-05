"""Review CLI（Phase 2-F——本格frontendなし。service layerの薄い操作面）。

使い方（リポジトリrootで）:
    python -m src.intelligence.review.cli list [--status open] [--type identity_candidate]
    python -m src.intelligence.review.cli show <review_id>
    python -m src.intelligence.review.cli decide <review_id> <decision> --by <name>
        [--param key=value ...] [--notes ...]

将来のPWAは本CLIではなくReviewService（同一契約）を呼ぶ。
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from ..core.paths import data_root
from ..databank.article_store import JsonlArticleStore
from ..enrichment.store import JsonlEnrichmentStore
from .model import ReviewDecisionKind, ReviewStatus, ReviewType
from .service import ReviewService
from .store import JsonlReviewStore


def _service(bank_root: Path) -> ReviewService:
    return ReviewService(
        JsonlReviewStore(bank_root / "news" / "review"),
        article_store=JsonlArticleStore(bank_root / "articles"),
        enrichment_store=JsonlEnrichmentStore(bank_root / "news" / "enrichment"),
    )


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Data Bank human review CLI")
    parser.add_argument("--bank-root", default=str(data_root() / "databank"))
    sub = parser.add_subparsers(dest="command", required=True)

    p_list = sub.add_parser("list")
    p_list.add_argument("--status", default="open")
    p_list.add_argument("--type", default="")

    p_show = sub.add_parser("show")
    p_show.add_argument("review_id")

    p_decide = sub.add_parser("decide")
    p_decide.add_argument("review_id")
    p_decide.add_argument("decision", choices=[d.value for d in ReviewDecisionKind])
    p_decide.add_argument("--by", required=True)
    p_decide.add_argument("--param", action="append", default=[])
    p_decide.add_argument("--notes", default="")

    args = parser.parse_args(argv)
    service = _service(Path(args.bank_root))

    if args.command == "list":
        status = ReviewStatus(args.status) if args.status else None
        review_type = ReviewType(args.type) if args.type else None
        for item in service.reviews.iter_items(status=status, review_type=review_type):
            print(f"{item.review_id}  {item.review_type.value:22s} "
                  f"{item.status.value:9s} {item.record_id}  "
                  f"{','.join(item.candidate_values)[:50]}")
        counts = service.reviews.counts_by_status()
        print(f"-- counts: {counts}")
        return 0

    if args.command == "show":
        item = service.reviews.get_item(args.review_id)
        if item is None:
            print("not found", file=sys.stderr)
            return 1
        for key in ("review_id", "record_id", "record_type", "review_type", "status",
                    "reason_codes", "candidate_values", "evidence_refs", "resolution",
                    "resolved_by", "notes"):
            value = getattr(item, key)
            print(f"{key}: {getattr(value, 'value', value)}")
        for d in service.reviews.decisions_for(args.review_id):
            print(f"decision: {d.decision.value} by {d.decided_by} at "
                  f"{d.decided_at.isoformat()} effects={d.applied_effects}")
        return 0

    params = dict(p.split("=", 1) for p in args.param)
    record = service.decide(
        args.review_id, ReviewDecisionKind(args.decision),
        decided_by=f"user:{args.by}", params=params, notes=args.notes)
    print(f"decided: {record.decision_id} effects={record.applied_effects}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
