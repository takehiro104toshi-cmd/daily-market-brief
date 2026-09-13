"""Phase 3.9.5 candidate #1 execution wrapper（凍結された 1 候補・1 回だけ REJECTED を書く）。

`python -X utf8 -m src.intelligence.formal_review.pilot_execute --require-commit <sha> --expect-<layer> <digest>
 --pattern cpt_4d2f4477a946c17e --action reject --actor P395_HUMAN_SUPERVISED_REVIEW --confirm "CONFIRM REJECTED cpt_4d2f4477a946c17e"`

pilot.py（読み取り専用 driver）の HEAD / policy / baseline / build / candidate / freshness をそのまま使い、
人間が選んだ REJECTED を **stage 1 dry-run → 完全一致 confirmation → real write 1 回** の順で実行する。
凍結値以外の pattern / action / actor / reason / confirmation token はすべて拒否する（汎用 batch executor ではない）。
real write は 1 回だけ試みる。失敗しても自動再試行しない: DecisionStore を読み取り専用で確認し、
一致する row があれば POSSIBLE_WRITE_SUCCEEDED_RESPONSE_FAILED として監査、無ければ WRITE_FAILED_NO_ROW として停止する。
出力は ASCII の key=value 行と `::P395D_*::` marker。失敗は `::P395D_FAIL:: stage= reason=`。
exit 0 = ok / 3 = FormalReviewError / 4 = 実行失敗 / 5 = 想定外。人間の reason 本文・PDF 名・source text・local path は出さない。
"""
from __future__ import annotations

import argparse
import json
import time
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence

from ..decision.models import record_hash_for
from ..decision.store import DecisionStoreCorrupt
from ..evaluation.models import REJECT_RECOMMENDED
from ..evaluation.store import EvaluationStoreCorrupt
from ..shadow_review.events import ShadowReviewStoreCorrupt
from .config import REJECTED
from .errors import FormalReviewError
from .pilot import CandidateOnePilot, PilotFailure, git
from .service import FormalDecisionRequest
from .session import confirmation_token
from .validation import POLICY_LAYERS

EXIT_OK, EXIT_FORMAL_REVIEW, EXIT_EXECUTE, EXIT_UNEXPECTED = 0, 3, 4, 5

#: 監督者が凍結した candidate #1 の human decision。この module はこれ以外を実行できない。
FROZEN_PATTERN_ID = "cpt_4d2f4477a946c17e"
FROZEN_ACTION = "reject"
FROZEN_DECISION_TYPE = REJECTED
FROZEN_ACTOR = "P395_HUMAN_SUPERVISED_REVIEW"
FROZEN_REASON = ("Supporting evidence remains directionally contradictory across a long observation span; "
                 "the contradiction is repeated and active, with no recovery or reversal in replay.")
FROZEN_CONFIRM = confirmation_token(FROZEN_DECISION_TYPE, FROZEN_PATTERN_ID)
FROZEN_RECOMMENDATION = REJECT_RECOMMENDED
FROZEN_REJECT_DRIVER = "SUPPORTING_DOCUMENT_UP_DOWN_CONTRADICTION"

WRITE_RESPONSE_FAILED = "POSSIBLE_WRITE_SUCCEEDED_RESPONSE_FAILED"
WRITE_FAILED_NO_ROW = "WRITE_FAILED_NO_ROW"
EVIDENCE_CHANGED = "HUMAN_REVIEW_EVIDENCE_CHANGED"


class ExecuteFailure(Exception):
    def __init__(self, stage: str, reason: str) -> None:
        super().__init__(f"{stage}: {reason}")
        self.stage = stage
        self.reason = reason


def _emit(key: str, value: Any) -> None:
    if isinstance(value, (dict, list, tuple)):
        value = json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)
    print(f"{key}={value}", flush=True)


def _marker(name: str) -> None:
    print(f"::P395D_{name}::", flush=True)


class CandidateOneExecutor:
    """凍結された candidate #1 の REJECTED を 1 回だけ書く。pilot の読み取り専用 section を composition で再利用する。"""

    def __init__(self, data_root: Path, repo_root: Path, *, pattern_id: str, action: str, actor: str, confirm: str,
                 reason: str = FROZEN_REASON, require_commit: str = "",
                 expected_digests: Optional[Mapping[str, str]] = None, skip_git: bool = False,
                 corpus_state_resolver: Optional[Any] = None, clock: Optional[Any] = None) -> None:
        self.pattern_id = str(pattern_id or "").strip()
        self.action = str(action or "").strip()
        self.actor = str(actor or "").strip()
        self.confirm = str(confirm or "")
        self.reason = str(reason or "")
        kw: Dict[str, Any] = {"require_commit": require_commit, "expected_digests": expected_digests,
                              "actor": self.actor, "skip_git": skip_git}
        if corpus_state_resolver is not None:
            kw["corpus_state_resolver"] = corpus_state_resolver
        if clock is not None:
            kw["clock"] = clock
        self.pilot = CandidateOnePilot(data_root, repo_root, **kw)
        self.repo = Path(repo_root)
        self.t0 = time.perf_counter()
        self.reviewed: Dict[str, str] = {}
        self.reviewed_policy_digests: Dict[str, str] = {}
        self.write_attempts = 0
        self.write_response = ""
        self.row: Dict[str, Any] = {}

    # ------------------------------------------------------------- generic
    def fail(self, stage: str, reason: str) -> None:
        raise ExecuteFailure(stage, reason)

    def check(self, stage: str, cond: bool, reason: str) -> None:
        if not cond:
            self.fail(stage, reason)

    def records(self) -> List[Dict[str, Any]]:
        """decision store の読み取り（append はしない。store は service が保持しているものを使う）。"""
        return [r.as_dict() for r in self.pilot.service().decision_store.records()]

    # ------------------------------------------------------------- 0. arguments
    def arguments(self) -> None:
        _marker("ARGUMENTS")
        _emit("pilot_scope", "SINGLE_CANDIDATE_ONLY")
        _emit("pattern", self.pattern_id)
        _emit("action", self.action)
        _emit("actor", self.actor)
        _emit("confirmation_token_matches_frozen", self.confirm == FROZEN_CONFIRM)
        _emit("reason_matches_frozen_human_reason", self.reason == FROZEN_REASON)
        self.check("ARGUMENTS", self.pattern_id == FROZEN_PATTERN_ID, "PATTERN_NOT_THIS_PILOT")
        self.check("ARGUMENTS", self.action == FROZEN_ACTION, "ACTION_NOT_THIS_PILOT")
        self.check("ARGUMENTS", self.actor == FROZEN_ACTOR, "ACTOR_NOT_THIS_PILOT")
        self.check("ARGUMENTS", self.reason == FROZEN_REASON, "REASON_NOT_THE_FROZEN_HUMAN_REASON")
        self.check("ARGUMENTS", self.confirm == FROZEN_CONFIRM, "CONFIRMATION_MISMATCH")
        _emit("arguments_check", "PASSED")

    # ------------------------------------------------------------- 1-4 read-only pre-write gates
    def head(self) -> None:
        _marker("HEAD")
        self.pilot.head()

    def policy(self) -> None:
        _marker("POLICY")
        self.pilot.policy()

    def baseline(self) -> None:
        _marker("BASELINE")
        self.pilot.baseline_section()
        rows = int(self.pilot.baseline["decisions"]["lines"])
        _emit("decision_rows_before", rows)
        self.check("BASELINE", rows == 0, "DECISION_STORE_NOT_EMPTY")

    def build(self) -> None:
        _marker("FRESH_BUILD")
        self.pilot.build()

    def evidence_recheck(self) -> None:
        _marker("EVIDENCE_RECHECK")
        self.pilot.candidate()
        row = self.pilot.row
        self.check("EVIDENCE_RECHECK", str(row.get("pattern_id")) == FROZEN_PATTERN_ID, "CANDIDATE_HEAD_CHANGED")
        self.check("EVIDENCE_RECHECK", str(row.get("recommendation")) == FROZEN_RECOMMENDATION, "RECOMMENDATION_CHANGED")
        self.pilot.freshness()
        packet = self.pilot.packet
        consistency = dict(packet.get("consistency") or {})
        replay = dict(packet.get("replay") or {})
        stress = dict(replay.get("stress") or {})
        decision = dict(packet.get("decision") or {})
        evidence = {
            "document_contradiction": bool(consistency.get("document_contradiction")),
            "document_contradiction_repeated": bool(consistency.get("document_contradiction_repeated")),
            "contradiction_active": bool(consistency.get("contradiction_active")),
            "reject_driver": stress.get("reject_driver"),
            "contradiction_recovery_positions": stress.get("contradiction_recovery_positions"),
            "reversal_count": replay.get("reversal_count"),
            "first_recommendation_position": replay.get("first_recommendation_position"),
            "persistence_ratio": replay.get("persistence_ratio"),
            "span_days": (packet.get("axes") or {}).get("span_days"),
            "replay_available": bool(replay.get("available")),
            "replay_current_compatible": bool(replay.get("current_compatible")),
            "formal_review_gate_reached": bool((packet.get("recommendation") or {}).get("formal_review_gate_reached")),
            "decision_head": str(decision.get("current_state", "")),
            "decision_history_length": int(decision.get("history_length", 0) or 0),
            "allowed_next_actions": list(decision.get("allowed_next_actions") or []),
        }
        _emit("reject_evidence", evidence)
        checks = [
            (f"{EVIDENCE_CHANGED}_CONTRADICTION", evidence["document_contradiction"]
             and evidence["document_contradiction_repeated"] and evidence["contradiction_active"]),
            (f"{EVIDENCE_CHANGED}_REJECT_DRIVER", evidence["reject_driver"] == FROZEN_REJECT_DRIVER),
            (f"{EVIDENCE_CHANGED}_RECOVERY", not list(evidence["contradiction_recovery_positions"] or [])),
            (f"{EVIDENCE_CHANGED}_REVERSAL", int(evidence["reversal_count"] or 0) == 0),
            ("REPLAY_NOT_COMPATIBLE", evidence["replay_available"] and evidence["replay_current_compatible"]
             and not list(replay.get("compatibility_reasons") or [])),
            ("FORMAL_GATE_NOT_REACHED", evidence["formal_review_gate_reached"]),
            ("DECISION_HEAD_CHANGED", evidence["decision_head"] == "NONE" and evidence["decision_history_length"] == 0),
            ("REJECT_NOT_ALLOWED", FROZEN_DECISION_TYPE in evidence["allowed_next_actions"]),
        ]
        for name, ok in checks:
            if not ok:
                self.fail("EVIDENCE_RECHECK", name)
        freshness = dict(packet.get("freshness") or {})
        self.reviewed = {"packet_id": str(packet["identity"]["packet_id"]),
                         "packet_evidence_digest": str(freshness.get("packet_evidence_digest", "")),
                         "material_digest": str(freshness.get("material_digest", ""))}
        self.reviewed_policy_digests = dict(freshness.get("policy_digests") or {})
        _emit("reviewed_binding", {**self.reviewed, "pattern_id": FROZEN_PATTERN_ID})
        _emit("evidence_recheck", "PASSED")

    # ------------------------------------------------------------- 5-7 stage 1 / confirmation / single write
    def request(self) -> FormalDecisionRequest:
        return FormalDecisionRequest(pattern_id=FROZEN_PATTERN_ID, action=FROZEN_ACTION,
                                     packet_id=self.reviewed["packet_id"], reason=FROZEN_REASON, actor=FROZEN_ACTOR)

    def stage1_dry_run(self) -> None:
        _marker("STAGE1_DRY_RUN")
        result = self.pilot.service().decide(self.request(), dry_run=True)
        _emit("guard_checks_passed", len(result["guard"]["checks_passed"]))
        _emit("validation_ok", bool(result["validation"]["ok"]))
        _emit("mutation", result["mutation"])
        _emit("promotion_status", result["promotion_status"])
        _emit("metadata_packet_binding",
              {k: result["metadata"].get(k) for k in ("packet_id", "packet_evidence_digest", "material_digest")})
        self.check("STAGE1_DRY_RUN", result["mutation"] == "NONE (dry run)", "DRY_RUN_REPORTED_A_MUTATION")
        self.check("STAGE1_DRY_RUN", bool(result["validation"]["ok"]),
                   f"DRY_RUN_VALIDATION_FAILED:{[e.get('code') for e in result['validation']['errors']]}")
        _emit("result", "DRY_RUN_PASS")

    def stage2_confirm(self) -> None:
        _marker("STAGE2_CONFIRM")
        expected = confirmation_token(FROZEN_DECISION_TYPE, FROZEN_PATTERN_ID)
        _emit("expected_confirmation_token", expected)
        _emit("received_matches", self.confirm == expected)
        self.check("STAGE2_CONFIRM", self.confirm == expected, "CONFIRMATION_MISMATCH")
        _emit("authorised_writes", 1)

    def stage2_write(self) -> None:
        """production write は生涯 1 回だけ試みる。例外時は読み取り専用の確認へ移り、決して再試行しない。"""
        _marker("STAGE2_WRITE")
        self.check("STAGE2_WRITE", self.write_attempts == 0, "SECOND_WRITE_ATTEMPT_REFUSED")
        self.write_attempts += 1
        _emit("write_attempt", self.write_attempts)
        try:
            result = self.pilot.service().decide(self.request(), dry_run=False)
        except Exception as exc:                                        # noqa: BLE001 — 再試行せず read-only で確認する
            self._inspect_after_write_exception(exc)
            return
        self.write_response = "WRITE_RESPONSE_RECEIVED"
        _emit("write_response", self.write_response)
        _emit("mutation", result["mutation"])
        outcome = dict(result.get("outcome") or {})
        _emit("appended", bool(outcome.get("appended")))
        _emit("decision_id", outcome.get("decision_id"))
        self.check("STAGE2_WRITE", bool(outcome.get("appended")), f"WRITE_DID_NOT_APPEND:{result['mutation']}")

    def _inspect_after_write_exception(self, exc: Exception) -> None:
        self.write_response = "WRITE_RESPONSE_EXCEPTION"
        _emit("write_response", self.write_response)
        _emit("write_exception_type", type(exc).__name__)
        _emit("retry_policy", "NO_AUTOMATIC_RETRY")
        try:
            rows = [r for r in self.records() if str(r.get("pattern_id")) == FROZEN_PATTERN_ID
                    and str(r.get("decision_type")) == FROZEN_DECISION_TYPE
                    and str((r.get("metadata") or {}).get("packet_id", "")) == self.reviewed["packet_id"]]
        except DecisionStoreCorrupt as corrupt:
            _emit("read_only_inspection", "DECISION_STORE_CORRUPT")
            self.fail("STAGE2_WRITE", f"{WRITE_FAILED_NO_ROW}:STORE_UNREADABLE:{type(corrupt).__name__}")
            return
        _emit("matching_rows_found", len(rows))
        if len(rows) == 1:
            self.write_response = WRITE_RESPONSE_FAILED
            _emit("write_response", self.write_response)
            _emit("next_step", "AUDIT_THE_EXISTING_ROW; DO NOT WRITE AGAIN")
            return
        _emit("write_response", WRITE_FAILED_NO_ROW)
        self.fail("STAGE2_WRITE", WRITE_FAILED_NO_ROW)

    # ------------------------------------------------------------- 8-9 audits
    def decision_audit(self) -> None:
        _marker("DECISION_AUDIT")
        rows = self.records()                                           # records() が sequence と hash chain を検証する
        _emit("decision_rows", len(rows))
        self.check("DECISION_AUDIT", len(rows) == 1, "EXPECTED_EXACTLY_ONE_DECISION_ROW")
        row = dict(rows[0])
        self.row = row
        metadata = dict(row.get("metadata") or {})
        recomputed = dict(row)
        recomputed["record_hash"] = ""
        _emit("decision_row", {k: row.get(k) for k in (
            "decision_id", "sequence", "pattern_id", "decision_type", "actor", "actor_type", "review_mode",
            "promotion_status", "previous_state", "previous_decision_id", "previous_record_hash", "record_hash",
            "decided_at", "idempotency_key", "corpus_size")})
        _emit("metadata_binding", metadata)
        _emit("metadata_key_count", len(metadata))
        _emit("reason_chars", len(str(row.get("reason") or "")))
        _emit("reason_matches_frozen_human_reason", str(row.get("reason", "")) == FROZEN_REASON)
        policy_digests = str(metadata.get("policy_digests", ""))
        checks = [
            ("STATE_REJECTED", str(row.get("decision_type")) == FROZEN_DECISION_TYPE),
            ("PATTERN_ID", str(row.get("pattern_id")) == FROZEN_PATTERN_ID),
            ("ACTOR", str(row.get("actor")) == FROZEN_ACTOR),
            ("ACTOR_TYPE_HUMAN", str(row.get("actor_type")) == "HUMAN"),
            ("REVIEW_MODE_FORMAL", str(row.get("review_mode")) == "FORMAL"),
            ("NOT_PROMOTED", str(row.get("promotion_status")) == "NOT_PROMOTED"),
            ("SEQUENCE_1", int(row.get("sequence") or 0) == 1),
            ("CHAIN_ROOT", not row.get("previous_record_hash") and not row.get("previous_state")
             and not row.get("previous_decision_id")),
            ("RECORD_HASH_RECOMPUTES", bool(row.get("record_hash")) and record_hash_for(recomputed) == row.get("record_hash")),
            ("PACKET_ID_BOUND", str(metadata.get("packet_id", "")) == self.reviewed["packet_id"]),
            ("PACKET_EVIDENCE_DIGEST_BOUND",
             str(metadata.get("packet_evidence_digest", "")) == self.reviewed["packet_evidence_digest"]),
            ("MATERIAL_DIGEST_BOUND", str(metadata.get("material_digest", "")) == self.reviewed["material_digest"]),
            ("SIX_POLICY_LAYERS_BOUND",
             all(f"{layer}:{self.reviewed_policy_digests.get(layer, '')}" in policy_digests for layer in POLICY_LAYERS)),
            ("REPLAY_BINDING_PRESENT", bool(metadata.get("replay_run_id")) and bool(metadata.get("replay_run_digest"))),
            ("EXACT_HUMAN_REASON_STORED", str(row.get("reason", "")) == FROZEN_REASON),
            ("IDEMPOTENCY_KEY_IS_PACKET", str(row.get("idempotency_key", "")) == self.reviewed["packet_id"]),
        ]
        for name, ok in checks:
            _emit(f"audit_{name}", "OK" if ok else "FAILED")
        self.check("DECISION_AUDIT", all(ok for _, ok in checks), "WRITTEN_DECISION_DOES_NOT_MATCH_REVIEWED_PACKET")
        _emit("decision_hash_chain", "VALID")
        _emit("write_response", self.write_response)

    def safety_audit(self) -> None:
        _marker("SAFETY")
        before, after = self.pilot.baseline, self.pilot._capture()
        intake = before["corpus"] != after["corpus"] or before["derived_evaluation"] != after["derived_evaluation"]
        _emit("intake_activity_observed", intake)
        protected = [key for key in ("review_events", "dna", "pdfs") if before[key] != after[key]]
        derived = [key for key in ("corpus", "derived_research", "derived_evaluation", "derived_shadow_review")
                   if before[key] != after[key]]
        _emit("shadow_review_events_unchanged", "review_events" not in protected)
        _emit("dna_blobs_unchanged", "dna" not in protected)
        _emit("pdf_inventory_unchanged", "pdfs" not in protected)
        _emit("derived_changed", sorted(derived))
        self.check("SAFETY", not protected, f"UNEXPECTED_CHANGE_OUTSIDE_DECISION_STORE:{sorted(protected)}")
        self.check("SAFETY", not derived or intake, f"DERIVED_STORE_CHANGED_WITHOUT_INTAKE:{sorted(derived)}")
        written = after["decisions"]["lines"] - before["decisions"]["lines"]
        _emit("real_decisions_written", written)
        self.check("SAFETY", written == 1, "DECISION_ROW_COUNT_DELTA_NOT_ONE")
        _emit("promotion_status_written", str(self.row.get("promotion_status", "")))
        self.check("SAFETY", str(self.row.get("promotion_status", "")) == "NOT_PROMOTED", "PROMOTION_STATUS_NOT_NOT_PROMOTED")
        if not self.pilot.skip_git:
            code, status = git(self.repo, "status", "--porcelain", "--untracked-files=no")
            _emit("tracked_worktree_unchanged", code == 0 and status == self.pilot.tracked_before)
            self.check("SAFETY", code == 0 and status == self.pilot.tracked_before, "TRACKED_WORKTREE_CHANGED")
        _emit("candidates_processed", 1)
        _emit("safety_check", "PASSED")

    # ------------------------------------------------------------- orchestration
    def run_all(self) -> int:
        try:
            self.arguments()
            self.head()
            self.policy()
            self.baseline()
            self.build()
            self.evidence_recheck()
            self.stage1_dry_run()
            self.stage2_confirm()
            self.stage2_write()
            self.decision_audit()
            self.safety_audit()
            _marker("PILOT_DECISION_OK")
            _emit("candidate", FROZEN_PATTERN_ID)
            _emit("decision_state", FROZEN_DECISION_TYPE)
            _emit("total_seconds", round(time.perf_counter() - self.t0, 1))
            _marker("END")
            return EXIT_OK
        except (ExecuteFailure, PilotFailure) as exc:
            stage = getattr(exc, "stage", "") or getattr(exc, "section", "")
            return self._fail(stage, exc.reason)
        except FormalReviewError as exc:
            return self._fail("FORMAL_REVIEW_GUARD", f"{exc.code}: {exc.message}", code=EXIT_FORMAL_REVIEW)
        except (DecisionStoreCorrupt, EvaluationStoreCorrupt, ShadowReviewStoreCorrupt) as exc:
            return self._fail("STORE_CORRUPT", f"{type(exc).__name__}: {exc}")
        except Exception as exc:                                        # noqa: BLE001
            return self._fail("UNEXPECTED", f"{type(exc).__name__}: {exc}", code=EXIT_UNEXPECTED)

    def _fail(self, stage: str, reason: str, *, code: int = EXIT_EXECUTE) -> int:
        _marker("FAIL")
        _emit("stage", stage)
        _emit("reason", self.pilot._redact(reason))
        _emit("write_attempts", self.write_attempts)
        _emit("retry_policy", "NO_AUTOMATIC_RETRY")
        return code


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Phase 3.9.5 candidate #1 execution wrapper (single candidate, one write)")
    parser.add_argument("--data-root", default="")
    parser.add_argument("--require-commit", default="")
    for layer in POLICY_LAYERS:
        parser.add_argument(f"--expect-{layer.replace('_', '-')}", default="", dest=f"expect_{layer}")
    parser.add_argument("--pattern", required=True, help=f"must be {FROZEN_PATTERN_ID}")
    parser.add_argument("--action", required=True, help=f"must be {FROZEN_ACTION}")
    parser.add_argument("--actor", required=True, help=f"must be {FROZEN_ACTOR}")
    parser.add_argument("--confirm", required=True, help="exact confirmation token for this frozen decision")
    parser.add_argument("--reason", default=FROZEN_REASON, help="defaults to the frozen human reason")
    parser.add_argument("--skip-git", action="store_true", help="skip repository identity checks (tests only)")
    args = parser.parse_args(argv)
    from .cli import resolve_root

    executor = CandidateOneExecutor(
        resolve_root(args.data_root), Path.cwd(), pattern_id=args.pattern, action=args.action, actor=args.actor,
        confirm=args.confirm, reason=args.reason, require_commit=args.require_commit, skip_git=bool(args.skip_git),
        expected_digests={layer: getattr(args, f"expect_{layer}") for layer in POLICY_LAYERS})
    return executor.run_all()


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
