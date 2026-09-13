"""Phase 3.9.5 next candidate read-only review（Decision が 1 件以上ある状態からの次の 1 件）。

`python -X utf8 -m src.intelligence.formal_review.next_candidate --require-commit <sha> --expect-<layer> <digest>
 [--expect-decided <pattern_id>] [--expect-deferred <pattern_id>] [--expect-row <seq>:<pattern_id>:<record_hash>]
 [--reaudit-pattern <id> --reaudit-decision <id> --reaudit-state <state> --reaudit-record-hash <hash>]
 [--identity-only] [--expect-rank-1 <pattern_id>] [--actor <actor_id>]`

candidate #1 の real write 後に使う汎用の読み取り専用 driver。**書き込み経路を一切持たない**
（confirmation token を受け取らず、real write の呼び出しも持たない。test が静的に検査する）。
pilot.py の section を composition で再利用し、本 module 固有の読み取り検査は 2 つだけ:

- DECISION_CHAIN: Decision row が 1 件以上・sequence 連番・record_hash 再計算一致・HUMAN / FORMAL / NOT_PROMOTED、
  および任意で既存 1 行の再監査（decision_id / pattern / state / record hash / packet 束縛 / 6 層 policy / replay 束縛）。
- QUEUE_EXCLUSION: 既決 pattern が primary queue に残っていないこと（残っていれば
  `DECIDED_PATTERN_STILL_IN_PRIMARY_QUEUE` で fail closed）。`--expect-decided` は decided section での在席も要求する。
- PROGRESSION（1.1.0）: deferred KEEP_REVIEWING が ranked primary に混ざっていないこと
  （混ざれば `DEFERRED_PATTERN_IN_PRIMARY_QUEUE`）。`--expect-deferred` は queue["deferred"] での在席も要求する。
  progression status / re-entry reason / unverifiable reason を pattern ごとに出す（reason 本文は無い）。
- `--expect-row <seq>:<pattern_id>:<record_hash>`（複数可）は既存 Decision row の不変証明（その sequence の row が
  同じ pattern・同じ record_hash であること。違えば `EXPECTED_ROW_CHANGED_OR_MISSING:<seq>` で fail closed）。
- `--identity-only` は rank 1 の identity（pattern_id / pattern_type / recommendation / decision_state）だけを出し、
  brief・dry-run・human boundary・command 提示を行わない（Windows READ-ONLY 確認用。SAFETY は常に実行する）。
- `--expect-rank-1 <pattern_id>` は fresh build の rank 1 をその id に束縛する（違えば `CANDIDATE_HEAD_CHANGED` で
  fail closed。freshness・brief・explanation・questions・dry-run・command 提示のいずれも行わない。
  診断は CANDIDATE section の identity / derived metrics と `expected_rank_1` / `fresh_rank_1` に限る）。
  `--actor` は dry-run の actor を差し替える（既定は pilot と同じ）。

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
from .config import SUPERSEDED_FORMAL_REVIEW_DIGESTS
from .errors import FormalReviewError
from .ordering import SECTION_APPROVE, SECTION_REJECT, SECTION_REOPEN
from .pilot import CandidateOnePilot, PilotFailure, _emit as emit_pair
from .validation import POLICY_LAYERS

EXIT_OK, EXIT_FORMAL_REVIEW, EXIT_REVIEW, EXIT_UNEXPECTED = 0, 3, 4, 5

PRIMARY_SECTIONS = (SECTION_REJECT, SECTION_APPROVE, SECTION_REOPEN)
DECIDED_IN_PRIMARY = "DECIDED_PATTERN_STILL_IN_PRIMARY_QUEUE"
DEFERRED_IN_PRIMARY = "DEFERRED_PATTERN_IN_PRIMARY_QUEUE"
EXPECTED_ROW_MISMATCH = "EXPECTED_ROW_CHANGED_OR_MISSING"
EXPECT_ROW_MALFORMED = "EXPECT_ROW_MALFORMED"
CANDIDATE_HEAD_CHANGED = "CANDIDATE_HEAD_CHANGED"


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
                 expect_deferred: Sequence[str] = (), expect_rows: Sequence[str] = (), identity_only: bool = False,
                 expect_rank_1: str = "", actor: str = "",
                 reaudit: Optional[Dict[str, str]] = None, skip_git: bool = False,
                 corpus_state_resolver: Optional[Any] = None, clock: Optional[Any] = None) -> None:
        kw: Dict[str, Any] = {"require_commit": require_commit, "expected_digests": expected_digests,
                              "skip_git": skip_git}
        if str(actor or "").strip():                                     # 省略時は pilot の既定 actor のまま
            kw["actor"] = str(actor).strip()
        if corpus_state_resolver is not None:
            kw["corpus_state_resolver"] = corpus_state_resolver
        if clock is not None:
            kw["clock"] = clock
        self.pilot = CandidateOnePilot(data_root, repo_root, **kw)
        self.expect_decided = [str(p).strip() for p in expect_decided if str(p).strip()]
        self.expect_deferred = [str(p).strip() for p in expect_deferred if str(p).strip()]
        self.expect_rows = [str(p).strip() for p in expect_rows if str(p).strip()]
        self.identity_only = bool(identity_only)
        self.expect_rank_1 = str(expect_rank_1 or "").strip()
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
        by_sequence = {int(r.get("sequence") or 0): r for r in rows}
        for spec in self.expect_rows:                                  # <seq>:<pattern_id>:<record_hash>（既存行の不変証明）
            parts = spec.split(":")
            self.check("DECISION_CHAIN", len(parts) == 3 and parts[0].isdigit(), f"{EXPECT_ROW_MALFORMED}:{spec}")
            row = by_sequence.get(int(parts[0])) or {}
            ok = str(row.get("pattern_id")) == parts[1] and str(row.get("record_hash")) == parts[2]
            emit_pair(f"expected_row_{parts[0]}", {"pattern_id": parts[1], "record_hash_matches": ok,
                                                    "decision_type": row.get("decision_type", "ABSENT")})
            self.check("DECISION_CHAIN", ok, f"{EXPECTED_ROW_MISMATCH}:{parts[0]}")
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
        bound = {part.split(":", 1)[0]: part.split(":", 1)[1] for part in policy_digests.split(";") if ":" in part}
        # formal_review だけは歴史的 digest（1.0.0 = cca7b436…）に束縛された row を書き換えずに認める（provenance）。
        formal_bound = bound.get("formal_review", "")
        formal_ok = formal_bound == current["formal_review"] or formal_bound in SUPERSEDED_FORMAL_REVIEW_DIGESTS
        emit_pair("reaudit_formal_review_binding",
                  "CURRENT" if formal_bound == current["formal_review"] else f"HISTORICAL:{formal_bound}" if formal_ok else "UNKNOWN")
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
            ("SIX_POLICY_LAYERS_BOUND", all(f"{layer}:{current[layer]}" in policy_digests for layer in POLICY_LAYERS
                                            if layer != "formal_review") and formal_ok),
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

    def progression(self) -> None:
        """deferred KEEP_REVIEWING は ranked primary に混ざらない・status と理由を pattern ごとに出す（reason 本文なし）。"""
        _marker("PROGRESSION")
        queue = self.pilot.service().store.queue()
        sections = dict(queue.get("sections") or {})
        primary = [row["pattern_id"] for name in PRIMARY_SECTIONS for row in sections.get(name, [])]
        deferred = {str(row.get("pattern_id")): row for row in queue.get("deferred") or []}
        progression = dict(queue.get("progression") or {})
        emit_pair("deferred_count", len(deferred))
        emit_pair("deferred_patterns", sorted(deferred))
        for pid in sorted(progression):
            p = progression[pid]
            emit_pair("progression", {"pattern_id": pid, "formal_head": p.get("formal_head"),
                                      "queue_status": p.get("queue_status"),
                                      "reentry_reasons": list(p.get("reentry_reasons") or []),
                                      "unverifiable_reasons": list(p.get("unverifiable_reasons") or []),
                                      "sibling_decided_since_review": bool(p.get("sibling_decided_since_review")),
                                      "in_ranked_primary": pid in primary, "in_deferred": pid in deferred})
        leaked = sorted(set(primary) & set(deferred))
        emit_pair("deferred_patterns_in_primary_queue", leaked)
        self.check("PROGRESSION", not leaked, DEFERRED_IN_PRIMARY)
        for pattern in self.expect_deferred:
            row = deferred.get(pattern)
            emit_pair("expected_deferred", {"pattern_id": pattern, "queue_status": (row or {}).get("queue_status", "ABSENT"),
                                            "decision_state": (row or {}).get("decision_state", "ABSENT"),
                                            "in_ranked_primary": pattern in primary, "in_deferred": row is not None})
            self.check("PROGRESSION", pattern not in primary, DEFERRED_IN_PRIMARY)
            self.check("PROGRESSION", row is not None, "EXPECTED_DEFERRED_PATTERN_NOT_IN_DEFERRED_QUEUE")
        emit_pair("progression_check", "PASSED")

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
            self.progression()
            _marker("NEXT_CANDIDATE")
            self.pilot.candidate()
            if self.expect_rank_1:                                   # head binding: 違う rank 1 は brief も dry-run も出さない
                fresh = str(self.pilot.row.get("pattern_id", ""))
                emit_pair("expected_rank_1", self.expect_rank_1)
                emit_pair("fresh_rank_1", fresh)
                self.check("NEXT_CANDIDATE", fresh == self.expect_rank_1, CANDIDATE_HEAD_CHANGED)
            self.pilot.freshness()
            if self.identity_only:                                   # identity だけ: brief も dry-run も command も出さない
                emit_pair("identity_only", True)
                emit_pair("next_rank_1", {"pattern_id": self.pilot.row.get("pattern_id"),
                                          "pattern_type": self.pilot.row.get("pattern_type"),
                                          "recommendation": self.pilot.row.get("recommendation"),
                                          "decision_state": self.pilot.row.get("decision_state")})
            else:
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
    parser.add_argument("--expect-deferred", action="append", default=[], dest="expect_deferred",
                        help="KEEP_REVIEWING pattern that must be in queue.deferred and absent from ranked primary")
    parser.add_argument("--expect-row", action="append", default=[], dest="expect_row",
                        help="<seq>:<pattern_id>:<record_hash> of an existing decision row that must be unchanged")
    parser.add_argument("--identity-only", action="store_true", dest="identity_only",
                        help="report only the rank 1 identity (no brief, no dry-run, no commands)")
    parser.add_argument("--expect-rank-1", default="", dest="expect_rank_1",
                        help="pattern id the fresh rank 1 must have; otherwise CANDIDATE_HEAD_CHANGED before any brief")
    parser.add_argument("--actor", default="", help="actor id for the technical dry-runs (default: the pilot actor)")
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
        expect_decided=args.expect_decided, expect_deferred=args.expect_deferred, expect_rows=args.expect_row,
        identity_only=bool(args.identity_only), expect_rank_1=args.expect_rank_1, actor=args.actor,
        reaudit={"pattern": args.reaudit_pattern, "decision": args.reaudit_decision, "state": args.reaudit_state,
                 "record_hash": args.reaudit_record_hash})
    return review.run_all()


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
