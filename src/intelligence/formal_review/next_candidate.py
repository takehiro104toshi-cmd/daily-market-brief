"""Phase 3.9.5 next candidate read-only review（Decision が 1 件以上ある状態からの次の 1 件）。

`python -X utf8 -m src.intelligence.formal_review.next_candidate --require-commit <sha> --expect-<layer> <digest>
 [--expect-decided <pattern_id>] [--reaudit-pattern <id> --reaudit-decision <id> --reaudit-state <state>
 --reaudit-record-hash <hash>]`

candidate #1 の real write 後に使う汎用の読み取り専用 driver。**書き込み経路を一切持たない**
（confirmation token を受け取らず、real write の呼び出しも持たない。test が静的に検査する）。
pilot.py の section を composition で再利用し、本 module 固有の読み取り検査は 2 つだけ:

- DECISION_CHAIN: Decision row が 1 件以上・sequence 連番・record_hash 再計算一致・HUMAN / FORMAL / NOT_PROMOTED、
  および任意で既存 1 行の再監査（decision_id / pattern / state / record hash / packet 束縛 / 6 層 policy / replay 束縛）。
- QUEUE_EXCLUSION: 既決 pattern が primary queue に残っていないこと（残っていれば
  `DECIDED_PATTERN_STILL_IN_PRIMARY_QUEUE` で fail closed）。`--expect-decided` は decided section での在席も要求する。

その後は fresh build から **現在の queue rank 1 を自力で特定**して 1 件だけ提示し、機械整合 action と
KEEP_REVIEWING の dry-run（技術的証明のみ）を行い、人間判断は PENDING のまま残す。
出力は ASCII の key=value 行と `::P395N_*::` marker（再利用した pilot section は `::P395C_*::` も出す）。
失敗は `::P395N_FAIL:: stage= reason=`。exit 0 = ok / 3 = FormalReviewError / 4 = 検査失敗 / 5 = 想定外。
"""
from __future__ import annotations

import argparse
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

from ..decision.models import record_hash_for
from ..decision.store import DecisionStoreCorrupt
from ..evaluation.store import EvaluationStoreCorrupt
from ..shadow_review.events import ShadowReviewStoreCorrupt
from .errors import FormalReviewError
from .ordering import SECTION_APPROVE, SECTION_REJECT, SECTION_REOPEN
from .pilot import CandidateOnePilot, PilotFailure, _emit as emit_pair
from .validation import POLICY_LAYERS

EXIT_OK, EXIT_FORMAL_REVIEW, EXIT_REVIEW, EXIT_UNEXPECTED = 0, 3, 4, 5

PRIMARY_SECTIONS = (SECTION_REJECT, SECTION_APPROVE, SECTION_REOPEN)
DECIDED_IN_PRIMARY = "DECIDED_PATTERN_STILL_IN_PRIMARY_QUEUE"


class ReviewFailure(Exception):
    def __init__(self, stage: str, reason: str) -> None:
        super().__init__(f"{stage}: {reason}")
        self.stage = stage
        self.reason = reason


def _marker(name: str) -> None:
    print(f"::P395N_{name}::", flush=True)


class NextCandidateReview:
    """既に Decision がある store から、現在の queue rank 1 を 1 件だけ読み取り専用で提示する。"""

    def __init__(self, data_root: Path, repo_root: Path, *, require_commit: str = "",
                 expected_digests: Optional[Dict[str, str]] = None, expect_decided: Sequence[str] = (),
                 reaudit: Optional[Dict[str, str]] = None, skip_git: bool = False,
                 corpus_state_resolver: Optional[Any] = None, clock: Optional[Any] = None) -> None:
        kw: Dict[str, Any] = {"require_commit": require_commit, "expected_digests": expected_digests,
                              "skip_git": skip_git}
        if corpus_state_resolver is not None:
            kw["corpus_state_resolver"] = corpus_state_resolver
        if clock is not None:
            kw["clock"] = clock
        self.pilot = CandidateOnePilot(data_root, repo_root, **kw)
        self.expect_decided = [str(p).strip() for p in expect_decided if str(p).strip()]
        self.reaudit = {k: str(v or "") for k, v in dict(reaudit or {}).items()}
        self.t0 = time.perf_counter()

    # ------------------------------------------------------------- generic
    def fail(self, stage: str, reason: str) -> None:
        raise ReviewFailure(stage, reason)

    def check(self, stage: str, cond: bool, reason: str) -> None:
        if not cond:
            self.fail(stage, reason)

    def rows(self) -> List[Dict[str, Any]]:
        """Decision store の読み取りのみ（records() が sequence と hash chain を検証する）。"""
        return [r.as_dict() for r in self.pilot.service().decision_store.records()]

    # ------------------------------------------------------------- new read-only checks
    def decision_chain(self) -> None:
        _marker("DECISION_CHAIN")
        rows = self.rows()
        emit_pair("decision_rows", len(rows))
        self.check("DECISION_CHAIN", len(rows) >= 1, "DECISION_STORE_EMPTY")
        sequences = [int(r.get("sequence") or 0) for r in rows]
        emit_pair("sequences", sequences)
        self.check("DECISION_CHAIN", sequences == list(range(1, len(rows) + 1)), "SEQUENCE_NOT_CONTIGUOUS")
        emit_pair("head_sequence", sequences[-1])
        self.check("DECISION_CHAIN", sequences[-1] == len(rows), "HEAD_SEQUENCE_INCONSISTENT")
        previous = ""
        for row in rows:
            recomputed = dict(row)
            recomputed["record_hash"] = ""
            checks = (bool(row.get("record_hash")) and record_hash_for(recomputed) == row.get("record_hash"),
                      str(row.get("previous_record_hash", "")) == previous,
                      str(row.get("actor_type")) == "HUMAN", str(row.get("review_mode")) == "FORMAL",
                      str(row.get("promotion_status")) == "NOT_PROMOTED",
                      bool((row.get("metadata") or {}).get("packet_id")))
            self.check("DECISION_CHAIN", all(checks), f"ROW_{row.get('sequence')}_INTEGRITY_FAILED")
            previous = str(row.get("record_hash", ""))
        emit_pair("decision_hash_chain", "VALID")
        emit_pair("all_rows_human_formal_not_promoted", True)
        emit_pair("decided_patterns", sorted({str(r.get("pattern_id")) for r in rows}))
        self._reaudit_row(rows)

    def _reaudit_row(self, rows: List[Dict[str, Any]]) -> None:
        pattern = self.reaudit.get("pattern", "")
        if not pattern:
            emit_pair("reaudit", "NOT_REQUESTED")
            return
        matches = [r for r in rows if str(r.get("pattern_id")) == pattern]
        emit_pair("reaudit_pattern", pattern)
        emit_pair("reaudit_rows_found", len(matches))
        self.check("DECISION_CHAIN", len(matches) == 1, "REAUDIT_ROW_NOT_FOUND_OR_DUPLICATED")
        row = matches[0]
        metadata = dict(row.get("metadata") or {})
        recomputed = dict(row)
        recomputed["record_hash"] = ""
        emit_pair("reaudit_row", {k: row.get(k) for k in (
            "decision_id", "sequence", "pattern_id", "decision_type", "actor", "actor_type", "review_mode",
            "promotion_status", "previous_record_hash", "record_hash", "decided_at", "idempotency_key")})
        emit_pair("reaudit_metadata", metadata)
        policy_digests = str(metadata.get("policy_digests", ""))
        current = self.pilot.service().policy_digests()
        results = [
            ("DECISION_ID", not self.reaudit.get("decision") or str(row.get("decision_id")) == self.reaudit["decision"]),
            ("DECISION_TYPE", not self.reaudit.get("state") or str(row.get("decision_type")) == self.reaudit["state"]),
            ("RECORD_HASH_MATCHES_EXPECTED",
             not self.reaudit.get("record_hash") or str(row.get("record_hash")) == self.reaudit["record_hash"]),
            ("RECORD_HASH_RECOMPUTES", record_hash_for(recomputed) == row.get("record_hash")),
            ("SEQUENCE", int(row.get("sequence") or 0) >= 1),
            ("PROMOTION_STATUS_NOT_PROMOTED", str(row.get("promotion_status")) == "NOT_PROMOTED"),
            ("PACKET_BINDING_PRESENT", bool(metadata.get("packet_id")) and bool(metadata.get("packet_evidence_digest"))),
            ("MATERIAL_DIGEST_BINDING_PRESENT", bool(metadata.get("material_digest"))),
            ("SIX_POLICY_LAYERS_BOUND", all(f"{layer}:{current[layer]}" in policy_digests for layer in POLICY_LAYERS)),
            ("REPLAY_BINDING_PRESENT", bool(metadata.get("replay_run_id")) and bool(metadata.get("replay_run_digest"))),
            ("HUMAN_REASON_PRESENT", len(str(row.get("reason") or "").strip()) >= 20),
            ("IDEMPOTENCY_KEY_IS_PACKET", str(row.get("idempotency_key", "")) == str(metadata.get("packet_id", ""))),
        ]
        for name, ok in results:
            emit_pair(f"reaudit_{name}", "OK" if ok else "FAILED")
        self.check("DECISION_CHAIN", all(ok for _, ok in results), "EXISTING_DECISION_ROW_REAUDIT_FAILED")
        emit_pair("reaudit", "PASSED")

    def queue_exclusion(self) -> None:
        _marker("QUEUE_EXCLUSION")
        queue = self.pilot.service().store.queue()
        sections = dict(queue.get("sections") or {})
        primary = [row["pattern_id"] for name in PRIMARY_SECTIONS for row in sections.get(name, [])]
        decided = {str(row.get("pattern_id")): str(row.get("decision_state", "")) for row in queue.get("decided") or []}
        emit_pair("primary_queue_size", len(primary))
        emit_pair("decided_rows_in_queue", len(decided))
        leaked = sorted(set(primary) & set(decided))
        emit_pair("decided_patterns_in_primary_queue", leaked)
        self.check("QUEUE_EXCLUSION", not leaked, DECIDED_IN_PRIMARY)
        for pattern in self.expect_decided:
            state = decided.get(pattern, "")
            emit_pair("expected_decided_state", {"pattern_id": pattern, "decision_state": state or "ABSENT",
                                                 "in_primary_queue": pattern in primary})
            self.check("QUEUE_EXCLUSION", pattern not in primary, DECIDED_IN_PRIMARY)
            self.check("QUEUE_EXCLUSION", bool(state), "EXPECTED_DECIDED_PATTERN_NOT_IN_DECIDED_CONTEXT")
        emit_pair("queue_exclusion_check", "PASSED")

    # ------------------------------------------------------------- orchestration
    def run_all(self) -> int:
        try:
            _marker("HEAD")
            self.pilot.head()
            _marker("POLICY")
            self.pilot.policy()
            self.decision_chain()
            _marker("BASELINE")
            self.pilot.baseline_section()
            _marker("FRESH_BUILD")
            self.pilot.build()
            self.queue_exclusion()
            _marker("NEXT_CANDIDATE")
            self.pilot.candidate()
            self.pilot.freshness()
            self.pilot.brief()
            _marker("DRY_RUN")
            self.pilot.machine_action_dry_run()
            self.pilot.keep_reviewing_dry_run()
            self.pilot.human_boundary()
            self.pilot.commands()
            _marker("SAFETY")
            self.pilot.safety()
            _marker("NEXT_REVIEW_OK")
            emit_pair("candidates_presented", 1)
            emit_pair("real_decisions_written_by_this_run", 0)
            emit_pair("total_seconds", round(time.perf_counter() - self.t0, 1))
            _marker("END")
            return EXIT_OK
        except (ReviewFailure, PilotFailure) as exc:
            return self._fail(getattr(exc, "stage", "") or getattr(exc, "section", ""), exc.reason)
        except FormalReviewError as exc:
            return self._fail("FORMAL_REVIEW_GUARD", f"{exc.code}: {exc.message}", code=EXIT_FORMAL_REVIEW)
        except (DecisionStoreCorrupt, EvaluationStoreCorrupt, ShadowReviewStoreCorrupt) as exc:
            return self._fail("STORE_CORRUPT", f"{type(exc).__name__}: {exc}")
        except Exception as exc:                                        # noqa: BLE001
            return self._fail("UNEXPECTED", f"{type(exc).__name__}: {exc}", code=EXIT_UNEXPECTED)

    def _fail(self, stage: str, reason: str, *, code: int = EXIT_REVIEW) -> int:
        _marker("FAIL")
        emit_pair("stage", stage)
        emit_pair("reason", self.pilot._redact(reason))
        emit_pair("real_decisions_written_by_this_run", 0)
        return code


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Phase 3.9.5 next candidate review (read-only, one candidate, no write path)")
    parser.add_argument("--data-root", default="")
    parser.add_argument("--require-commit", default="")
    for layer in POLICY_LAYERS:
        parser.add_argument(f"--expect-{layer.replace('_', '-')}", default="", dest=f"expect_{layer}")
    parser.add_argument("--expect-decided", action="append", default=[], dest="expect_decided",
                        help="pattern that must be decided and absent from the primary queue")
    parser.add_argument("--reaudit-pattern", default="", help="existing decided pattern to re-audit read-only")
    parser.add_argument("--reaudit-decision", default="")
    parser.add_argument("--reaudit-state", default="")
    parser.add_argument("--reaudit-record-hash", default="")
    parser.add_argument("--skip-git", action="store_true", help="skip repository identity checks (tests only)")
    args = parser.parse_args(argv)
    from .cli import resolve_root

    review = NextCandidateReview(
        resolve_root(args.data_root), Path.cwd(), require_commit=args.require_commit, skip_git=bool(args.skip_git),
        expected_digests={layer: getattr(args, f"expect_{layer}") for layer in POLICY_LAYERS},
        expect_decided=args.expect_decided,
        reaudit={"pattern": args.reaudit_pattern, "decision": args.reaudit_decision, "state": args.reaudit_state,
                 "record_hash": args.reaudit_record_hash})
    return review.run_all()


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
