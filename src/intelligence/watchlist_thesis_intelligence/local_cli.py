"""P9-A4 — 本人の環境でだけ使う local な実行の入口（production ・公開 ・web ・API ・PWA ・Morning Brief ・scheduler の外）。

- `apply --p9-root R --decision FILE [--p8-root P] [--dry-run]`: 人の判断の file（JSON）を検査して適用する（`--dry-run` は書かない）。
  出力は local の受領（状態 ・P9 の root ／ revision の id ・seq）だけ。
- `summary --p9-root R --at ISO --as-of-date YYYY-MM-DD`: 安全な投影（件数だけ）。
- `review-due --p9-root R --at ISO --as-of-date YYYY-MM-DD`: private な見直しの日の報告（P9 の id と日だけ）。

時計を読まない（瞬間 ・日は引数で明示）。credential ・network は使わない（P8 の root は read-only の照合だけ）。

記録: `docs/databank/PHASE9_A4_HUMAN_DECISION_EXECUTOR.md`。
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import date, datetime
from pathlib import Path
from typing import Any, List, Optional

from .authority_stores import AuthorityStores
from .decision_model import decision_from_dict
from .executor import ExecutorError, HumanDecisionExecutor
from .projection import review_due_report, safe_projection
from .revision_model import SemanticModelError
from .store_io import AuthorityStoreError


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="p9_local", description="P9 private watchlist / thesis authority (local)")
    sub = parser.add_subparsers(dest="command", required=True)
    apply = sub.add_parser("apply")
    apply.add_argument("--p9-root", required=True)
    apply.add_argument("--decision", required=True)
    apply.add_argument("--p8-root", default=None)
    apply.add_argument("--dry-run", action="store_true")
    for name in ("summary", "review-due"):
        view = sub.add_parser(name)
        view.add_argument("--p9-root", required=True)
        view.add_argument("--at", required=True, help="explicit aware instant")
        view.add_argument("--as-of-date", required=True, help="explicit YYYY-MM-DD")
    return parser


def _emit(payload: Any) -> None:
    sys.stdout.write(json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2) + "\n")


def run_cli(argv: Optional[List[str]] = None) -> int:
    args = _parser().parse_args(argv)
    try:
        if args.command == "apply":
            data = json.loads(Path(args.decision).read_text(encoding="utf-8"))
            executor = HumanDecisionExecutor(args.p9_root, p8_root=args.p8_root)
            _emit(executor.execute(decision_from_dict(data), dry_run=args.dry_run).as_dict())
            return 0
        at, day = datetime.fromisoformat(args.at), date.fromisoformat(args.as_of_date)
        stores = AuthorityStores.open(args.p9_root)
        if args.command == "summary":
            _emit(safe_projection(stores, at=at, as_of_date=day).as_dict())
        else:
            _emit([{"kind": p.kind.value, "review_due_on": p.review_due_on.isoformat(), "revision_id": p.revision_id,
                    "root_id": p.root_id} for p in review_due_report(stores, at=at, as_of_date=day)])
        return 0
    except (ExecutorError, SemanticModelError) as exc:
        _emit({"state": "FAILED", "code": exc.code, "detail": exc.detail})
    except AuthorityStoreError as exc:
        _emit({"state": "FAILED", "category": exc.category.value, "code": exc.code, "detail": exc.detail})
    except (ValueError, OSError) as exc:
        _emit({"state": "FAILED", "code": "INPUT_INVALID", "detail": type(exc).__name__})
    return 2


if __name__ == "__main__":                                                       # pragma: no cover
    raise SystemExit(run_cli())
