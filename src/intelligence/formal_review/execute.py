"""Phase 3.9.5 generic formal review execution session（1 invocation = 1 candidate = real write 最大 1 回）。

`python -X utf8 -m src.intelligence.formal_review.execute --require-commit <sha> --expect-<layer> <digest>
 --pattern <id> --action <approve|reject|keep-reviewing> --actor <id> --reason "<human reason>"
 --confirm "CONFIRM <STATE> <id>" --expect-rows-before <N> --expect-current-state <STATE|NONE>
 --expect-machine-recommendation <REC> [--require-queue-rank 1] [--expect-group-state-digest <digest>]
 [--expect-group-material-digest <digest>] [--expect-fact key=value ...] [--acknowledge-sibling <id> ...]`

**orchestration only**: Decision state model・遷移・population・recommendation・packet schema・policy・replay・
group の各 semantics は一切変更せず、呼び出し側が束縛した「レビュー時点の期待状態」を検査してから、既存の
authoritative write path（`FormalReviewGuard → DecisionRequest → DecisionService.validate → decide →
DecisionStore.append`）をそのまま使う。candidate 固有の凍結値は持たない（すべて引数）。

deferred KEEP_REVIEWING（queue progression 1.1.0）は既定で target にできない（`TARGET_DEFERRED_KEEP_REVIEWING`）。
意図的に扱う場合だけ `--allow-deferred` を明示する（通常の実行 semantics は変えない）。
順序: ARGUMENTS → HEAD → POLICY → DECISION_CHAIN → BASELINE → FRESH_BUILD → TARGET → PACKET_FRESHNESS →
EXPECTED_FACTS → GROUP_CONTEXT → STAGE1_DRY_RUN → STAGE2_CONFIRM → STAGE2_WRITE → DECISION_AUDIT → SAFETY → STOP。
stage 1 と stage 2 は同一 packet（間で rebuild しない）。real write は生涯 1 回だけ試み、失敗しても自動再試行せず
DecisionStore を読み取り専用で確認して POSSIBLE_WRITE_SUCCEEDED_RESPONSE_FAILED / WRITE_FAILED_NO_ROW /
AMBIGUOUS_WRITE_RESULT を報告する。batch / 複数 pattern の入口は持たない。
出力は ASCII の key=value 行と `::P395X_*::` marker（人間 reason 本文は出さず文字数と digest だけ出す）。
失敗は `::P395X_FAIL:: stage= reason=`。exit 0 ok / 3 FormalReviewError / 4 実行失敗 / 5 想定外。
"""
from __future__ import annotations

import argparse
import hashlib
import json
import time
from pathlib import Path
from typing import Any, Callable, Dict, List, Mapping, Optional, Sequence, Tuple

from ..decision.models import ACTOR_HUMAN, record_hash_for
from ..decision.store import DecisionStoreCorrupt
from ..evaluation.store import EvaluationStoreCorrupt
from ..shadow_review.events import ShadowReviewStoreCorrupt
from .config import ACTIONS
from .errors import FormalReviewError
from .groups import opposite_members
from .ordering import SECTION_APPROVE, SECTION_REJECT, SECTION_REOPEN
from .pilot import CandidateOnePilot, PilotFailure, git
from .service import FormalDecisionRequest
from .session import confirmation_token, sibling_status
from .validation import POLICY_LAYERS

EXIT_OK, EXIT_FORMAL_REVIEW, EXIT_EXECUTE, EXIT_UNEXPECTED = 0, 3, 4, 5

PRIMARY_SECTIONS = (SECTION_REJECT, SECTION_APPROVE, SECTION_REOPEN)
STATE_NONE = "NONE"
WRITE_RESPONSE_FAILED = "POSSIBLE_WRITE_SUCCEEDED_RESPONSE_FAILED"
WRITE_FAILED_NO_ROW = "WRITE_FAILED_NO_ROW"
AMBIGUOUS_WRITE = "AMBIGUOUS_WRITE_RESULT"
GROUP_CONTEXT_CHANGED = "HUMAN_REVIEW_EVIDENCE_CHANGED_GROUP_CONTEXT"
TARGET_DEFERRED = "TARGET_DEFERRED_KEEP_REVIEWING"

#: `--expect-fact` の allowlist。任意の object path / 式は受け付けない（型付きの取り出しだけ）。
FACT_EXTRACTORS: Dict[str, Tuple[str, Callable[[Mapping[str, Any]], Any]]] = {
    "document_contradiction": ("bool", lambda p: bool((p.get("consistency") or {}).get("document_contradiction"))),
    "document_contradiction_repeated": ("bool", lambda p: bool((p.get("consistency") or {}).get("document_contradiction_repeated"))),
    "narrow_sibling_contradiction": ("bool", lambda p: bool((p.get("consistency") or {}).get("narrow_sibling_contradiction"))),
    "narrow_sibling_repeated": ("bool", lambda p: bool((p.get("consistency") or {}).get("narrow_sibling_repeated"))),
    "contradiction_active": ("bool", lambda p: bool((p.get("consistency") or {}).get("contradiction_active"))),
    "direction_class": ("str", lambda p: str((p.get("consistency") or {}).get("direction_class", ""))),
    "dna_conflict_count": ("int", lambda p: int((p.get("dna") or {}).get("conflict_count", 0) or 0)),
    "reject_driver": ("str", lambda p: str(((p.get("replay") or {}).get("stress") or {}).get("reject_driver", ""))),
    "reversal_count": ("int", lambda p: int((p.get("replay") or {}).get("reversal_count", 0) or 0)),
    "recovery_count": ("int", lambda p: len(list(((p.get("replay") or {}).get("stress") or {}).get("contradiction_recovery_positions") or []))),
    "opposite_sibling_count": ("int", lambda p: len(opposite_members(p.get("group") or {}))),
    "sibling_member_count": ("int", lambda p: len((p.get("group") or {}).get("members") or [])),
    "eligible_support": ("int", lambda p: int((p.get("axes") or {}).get("eligible_support", 0) or 0)),
    "formal_review_gate_reached": ("bool", lambda p: bool((p.get("recommendation") or {}).get("formal_review_gate_reached"))),
    "replay_current_compatible": ("bool", lambda p: bool((p.get("replay") or {}).get("current_compatible"))),
    "stability_class": ("str", lambda p: str((p.get("replay") or {}).get("stability_class", ""))),
}


def group_material_digest(view: Mapping[str, Any]) -> str:
    """material group view の content hash。member 個々の material_digest（表現の再生成で変わる）は含まない。"""
    blob = json.dumps(view, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:16]


class ExecutionFailure(Exception):
    def __init__(self, stage: str, reason: str) -> None:
        super().__init__(f"{stage}: {reason}")
        self.stage = stage
        self.reason = reason


def _emit(key: str, value: Any) -> None:
    if isinstance(value, (dict, list, tuple)):
        value = json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)
    print(f"{key}={value}", flush=True)


def _marker(name: str) -> None:
    print(f"::P395X_{name}::", flush=True)


def parse_fact(text: str) -> Tuple[str, Any]:
    """`key=value` を allowlist の型で解釈する。未知 key / 型不一致は拒否（式評価はしない）。"""
    key, sep, raw = str(text).partition("=")
    key, raw = key.strip(), raw.strip()
    if not sep or key not in FACT_EXTRACTORS:
        raise ExecutionFailure("ARGUMENTS", f"UNKNOWN_EXPECTED_FACT:{key or text}")
    kind = FACT_EXTRACTORS[key][0]
    if kind == "bool":
        if raw not in ("true", "false"):
            raise ExecutionFailure("ARGUMENTS", f"EXPECTED_FACT_NOT_BOOLEAN:{key}")
        return key, raw == "true"
    if kind == "int":
        if not raw.isdigit():
            raise ExecutionFailure("ARGUMENTS", f"EXPECTED_FACT_NOT_INTEGER:{key}")
        return key, int(raw)
    return key, raw


def material_group_view(packet: Mapping[str, Any]) -> Dict[str, Any]:
    """group_state_digest が変わったときに比較する実質 semantics（表現の再生成では変わらない部分）。"""
    status = sibling_status(packet)
    group = dict(packet.get("group") or {})
    return {
        "sibling_group_key": str(group.get("sibling_group_key", "")),
        "own_direction": str(group.get("own_direction", "")),
        "member_ids": sorted(str(m.get("pattern_id")) for m in group.get("members") or []),
        "opposite_member_ids": sorted(str(m.get("pattern_id")) for m in opposite_members(group)),
        "member_decision_states": dict(status["member_decision_states"]),
        "C1_status": status["C1_status"],
        "C1_blocking_approved_siblings": sorted(status["C1_blocking_approved_siblings"]),
        "C3_status": status["C3_status"],
        "C3_acknowledgement_required_for": sorted(status["C3_acknowledgement_required_for"]),
    }


class FormalExecutionSession:
    """1 invocation で 1 candidate の human formal decision を実行する（orchestration only）。"""

    def __init__(self, data_root: Path, repo_root: Path, *, pattern_id: str, action: str, actor: str, reason: str,
                 confirm: str, expect_rows_before: int, expect_current_state: str, expect_recommendation: str = "",
                 require_queue_rank: Optional[int] = None, expect_group_state_digest: str = "",
                 expect_group_material_digest: str = "",
                 expect_facts: Optional[Mapping[str, Any]] = None, acknowledge_siblings: Sequence[str] = (),
                 allow_deferred: bool = False, require_commit: str = "",
                 expected_digests: Optional[Mapping[str, str]] = None, skip_git: bool = False,
                 corpus_state_resolver: Optional[Any] = None, clock: Optional[Any] = None) -> None:
        self.pattern_id = str(pattern_id or "").strip()
        self.action = str(action or "").strip()
        self.actor = str(actor or "").strip()
        self.reason = str(reason or "")
        self.confirm = str(confirm or "")
        self.expect_rows_before = int(expect_rows_before)
        self.expect_current_state = str(expect_current_state or "").strip()
        self.expect_recommendation = str(expect_recommendation or "").strip()
        self.require_queue_rank = require_queue_rank
        self.expect_group_state_digest = str(expect_group_state_digest or "").strip()
        self.expect_group_material_digest = str(expect_group_material_digest or "").strip()
        self.expect_facts = dict(expect_facts or {})
        self.acknowledge_siblings = tuple(str(s).strip() for s in acknowledge_siblings if str(s).strip())
        self.allow_deferred = bool(allow_deferred)
        kw: Dict[str, Any] = {"require_commit": require_commit, "expected_digests": expected_digests,
                              "actor": self.actor, "skip_git": skip_git}
        if corpus_state_resolver is not None:
            kw["corpus_state_resolver"] = corpus_state_resolver
        if clock is not None:
            kw["clock"] = clock
        self.pilot = CandidateOnePilot(data_root, repo_root, **kw)
        self.repo = Path(repo_root)
        self.t0 = time.perf_counter()
        self.rows_before: List[Dict[str, Any]] = []
        self.prior_head: Dict[str, Any] = {}
        self.reviewed: Dict[str, str] = {}
        self.reviewed_policy_digests: Dict[str, str] = {}
        self.packet: Dict[str, Any] = {}
        self.write_attempts = 0
        self.write_response = ""
        self.new_row: Dict[str, Any] = {}

    # ------------------------------------------------------------- generic
    @property
    def decision_type(self) -> str:
        return ACTIONS.get(self.action, "")

    def fail(self, stage: str, reason: str) -> None:
        raise ExecutionFailure(stage, reason)

    def check(self, stage: str, cond: bool, reason: str) -> None:
        if not cond:
            self.fail(stage, reason)

    def rows(self) -> List[Dict[str, Any]]:
        """Decision store の読み取りのみ（service が保持する store を使う。append はしない）。"""
        return [r.as_dict() for r in self.pilot.service().decision_store.records()]

    # ------------------------------------------------------------- 1. arguments
    def arguments(self) -> None:
        _marker("ARGUMENTS")
        _emit("execution_scope", "ONE_CANDIDATE_ONE_WRITE")
        _emit("pattern", self.pattern_id)
        _emit("action", self.action)
        _emit("decision_type", self.decision_type)
        _emit("actor", self.actor)
        _emit("reason_chars", len(self.reason))
        _emit("reason_digest", hashlib.sha256(self.reason.encode("utf-8")).hexdigest()[:16])
        _emit("expect_rows_before", self.expect_rows_before)
        _emit("expect_current_state", self.expect_current_state)
        _emit("expect_recommendation", self.expect_recommendation or "NOT_BOUND")
        _emit("require_queue_rank", self.require_queue_rank if self.require_queue_rank is not None else "NOT_BOUND")
        _emit("expect_group_state_digest", self.expect_group_state_digest or "NOT_BOUND")
        _emit("expect_facts", {k: self.expect_facts[k] for k in sorted(self.expect_facts)})
        _emit("acknowledge_siblings", list(self.acknowledge_siblings))
        _emit("allow_deferred", self.allow_deferred)
        self.check("ARGUMENTS", bool(self.pattern_id) and "," not in self.pattern_id, "ONE_PATTERN_PER_INVOCATION")
        self.check("ARGUMENTS", bool(self.decision_type), f"UNKNOWN_ACTION:{self.action}")
        self.check("ARGUMENTS", bool(self.actor), "ACTOR_REQUIRED")
        self.check("ARGUMENTS", bool(self.reason.strip()), "REASON_REQUIRED")
        self.check("ARGUMENTS", self.expect_rows_before >= 0, "EXPECT_ROWS_BEFORE_REQUIRED")
        self.check("ARGUMENTS", bool(self.expect_current_state), "EXPECT_CURRENT_STATE_REQUIRED")
        self.check("ARGUMENTS", all(k in FACT_EXTRACTORS for k in self.expect_facts), "UNKNOWN_EXPECTED_FACT")
        expected_token = confirmation_token(self.decision_type, self.pattern_id)
        _emit("expected_confirmation_token", expected_token)
        self.check("ARGUMENTS", self.confirm == expected_token, "CONFIRMATION_MISMATCH")
        _emit("arguments_check", "PASSED")

    # ------------------------------------------------------------- 2-5 read-only pre-write gates
    def head(self) -> None:
        _marker("HEAD")
        self.pilot.head()

    def policy(self) -> None:
        _marker("POLICY")
        self.pilot.policy()

    def decision_chain(self) -> None:
        _marker("DECISION_CHAIN")
        rows = self.rows()
        _emit("decision_rows_before", len(rows))
        self.check("DECISION_CHAIN", len(rows) == self.expect_rows_before,
                   f"DECISION_ROWS_BEFORE_MISMATCH:{len(rows)}!={self.expect_rows_before}")
        previous = ""
        for index, row in enumerate(rows, start=1):
            recomputed = dict(row)
            recomputed["record_hash"] = ""
            ok = (int(row.get("sequence") or 0) == index
                  and bool(row.get("record_hash")) and record_hash_for(recomputed) == row.get("record_hash")
                  and str(row.get("previous_record_hash", "")) == previous
                  and str(row.get("promotion_status")) == "NOT_PROMOTED")
            self.check("DECISION_CHAIN", ok, f"ROW_{index}_INTEGRITY_FAILED")
            previous = str(row.get("record_hash", ""))
        self.rows_before = rows
        mine = [r for r in rows if str(r.get("pattern_id")) == self.pattern_id]
        self.prior_head = dict(mine[-1]) if mine else {}
        _emit("decision_hash_chain", "VALID")
        _emit("prior_head_for_pattern", {"decision_id": self.prior_head.get("decision_id", ""),
                                         "decision_type": self.prior_head.get("decision_type", ""),
                                         "sequence": self.prior_head.get("sequence", 0)} if self.prior_head else "NONE")
        _emit("decision_chain_check", "PASSED")

    def baseline(self) -> None:
        _marker("BASELINE")
        self.pilot.baseline_section()
        lines = int(self.pilot.baseline["decisions"]["lines"])
        self.check("BASELINE", lines == self.expect_rows_before,
                   f"DECISION_ROWS_BEFORE_MISMATCH:{lines}!={self.expect_rows_before}")

    def build(self) -> None:
        _marker("FRESH_BUILD")
        self.pilot.build()

    # ------------------------------------------------------------- 6-9 target / freshness / facts / group
    def target(self) -> None:
        _marker("TARGET")
        queue = self.pilot.service().store.queue()
        sections = dict(queue.get("sections") or {})
        rows = [r for name in PRIMARY_SECTIONS for r in sections.get(name, [])]
        row = next((r for r in rows if str(r.get("pattern_id")) == self.pattern_id), None)
        deferred = next((r for r in queue.get("deferred") or [] if str(r.get("pattern_id")) == self.pattern_id), None)
        if row is None and deferred is not None:
            _emit("target_queue_status", deferred.get("queue_status"))
            self.check("TARGET", self.allow_deferred, TARGET_DEFERRED)           # 既定: deferred は target にしない
            _emit("deferred_target_allowed", True)
            row = {**deferred, "queue_rank": None, "section": "deferred"}
        self.check("TARGET", row is not None, "TARGET_NOT_IN_PRIMARY_QUEUE")
        self.pilot.row = dict(row)
        _emit("queue_rank", row.get("queue_rank"))
        _emit("section", row.get("section"))
        _emit("pattern_id", row.get("pattern_id"))
        _emit("pattern_type", row.get("pattern_type"))
        _emit("recommendation", row.get("recommendation"))
        if self.require_queue_rank is not None:
            self.check("TARGET", int(row.get("queue_rank") or 0) == int(self.require_queue_rank), "CANDIDATE_HEAD_CHANGED")
        if self.expect_recommendation:
            self.check("TARGET", str(row.get("recommendation")) == self.expect_recommendation, "RECOMMENDATION_CHANGED")
        packet = self.pilot.service().store.packet(self.pattern_id)
        self.check("TARGET", packet is not None, "TARGET_HAS_NO_BUILT_PACKET")
        self.packet = dict(packet)
        self.pilot.packet = self.packet
        decision = dict(self.packet.get("decision") or {})
        current_state = str(decision.get("current_state", "")) or STATE_NONE
        _emit("current_formal_state", current_state)
        _emit("history_length", decision.get("history_length"))
        _emit("allowed_next_actions", list(decision.get("allowed_next_actions") or []))
        self.check("TARGET", current_state == self.expect_current_state,
                   f"CURRENT_STATE_MISMATCH:{current_state}!={self.expect_current_state}")
        self.check("TARGET", self.decision_type in list(decision.get("allowed_next_actions") or []),
                   f"ACTION_NOT_ALLOWED_FOR_CURRENT_STATE:{self.decision_type}")
        _emit("candidates_targeted", 1)
        _emit("target_check", "PASSED")

    def freshness(self) -> None:
        _marker("PACKET_FRESHNESS")
        self.pilot.freshness()
        block = dict(self.packet.get("freshness") or {})
        self.reviewed = {"packet_id": str(self.packet["identity"]["packet_id"]),
                         "packet_evidence_digest": str(block.get("packet_evidence_digest", "")),
                         "material_digest": str(block.get("material_digest", "")),
                         "group_state_digest": str((self.packet.get("group") or {}).get("group_state_digest", ""))}
        self.reviewed_policy_digests = dict(block.get("policy_digests") or {})
        _emit("reviewed_binding", self.reviewed)

    def expected_facts(self) -> None:
        _marker("EXPECTED_FACTS")
        if not self.expect_facts:
            _emit("expected_facts", "NOT_BOUND")
            return
        observed = {key: FACT_EXTRACTORS[key][1](self.packet) for key in sorted(self.expect_facts)}
        _emit("observed_facts", observed)
        mismatched = sorted(k for k, want in self.expect_facts.items() if observed[k] != want)
        _emit("fact_mismatches", mismatched)
        self.check("EXPECTED_FACTS", not mismatched, f"HUMAN_REVIEW_EVIDENCE_CHANGED:{','.join(mismatched)}")
        _emit("expected_facts_check", "PASSED")

    def group_context(self) -> None:
        """digest 一致なら UNCHANGED。違えば material view を比較し、証明できない限り fail closed（黙って無視しない）。"""
        _marker("GROUP_CONTEXT")
        fresh = self.reviewed["group_state_digest"]
        material = material_group_view(self.packet)
        material_digest_value = group_material_digest(material)
        _emit("fresh_group_state_digest", fresh or "NONE")
        _emit("fresh_group_material_digest", material_digest_value)
        _emit("group_material_view", material)
        if not self.expect_group_state_digest:
            _emit("group_context", "NOT_BOUND")
            return
        if fresh == self.expect_group_state_digest:
            _emit("group_context", "GROUP_CONTEXT_UNCHANGED")
            return
        _emit("group_state_digest_changed", True)
        if not self.expect_group_material_digest:
            _emit("group_material_baseline", "NOT_SUPPLIED")
            _emit("group_context", GROUP_CONTEXT_CHANGED)
            self.fail("GROUP_CONTEXT", GROUP_CONTEXT_CHANGED)
        same = material_digest_value == self.expect_group_material_digest
        _emit("group_material_matches_reviewed", same)
        self.check("GROUP_CONTEXT", same, GROUP_CONTEXT_CHANGED)
        _emit("group_context", "EQUIVALENT_REPRESENTATION_REGENERATED")

    # ------------------------------------------------------------- 10-12 stage 1 / confirm / one write
    def request(self) -> FormalDecisionRequest:
        return FormalDecisionRequest(pattern_id=self.pattern_id, action=self.action,
                                     packet_id=self.reviewed["packet_id"], reason=self.reason, actor=self.actor,
                                     acknowledge_siblings=self.acknowledge_siblings)

    def stage1_dry_run(self) -> None:
        _marker("STAGE1_DRY_RUN")
        result = self.pilot.service().decide(self.request(), dry_run=True)
        _emit("guard_checks_passed", len(result["guard"]["checks_passed"]))
        _emit("validation_ok", bool(result["validation"]["ok"]))
        _emit("mutation", result["mutation"])
        _emit("promotion_status", result["promotion_status"])
        _emit("metadata_packet_binding", {k: result["metadata"].get(k) for k in
                                          ("packet_id", "packet_evidence_digest", "material_digest", "group_state_digest")})
        self.check("STAGE1_DRY_RUN", result["mutation"] == "NONE (dry run)", "DRY_RUN_REPORTED_A_MUTATION")
        self.check("STAGE1_DRY_RUN", str(result["promotion_status"]) == "NOT_PROMOTED", "DRY_RUN_PROMOTION_STATUS")
        self.check("STAGE1_DRY_RUN", bool(result["validation"]["ok"]),
                   f"DRY_RUN_VALIDATION_FAILED:{[e.get('code') for e in result['validation']['errors']]}")
        _emit("result", "DRY_RUN_PASS")

    def stage2_confirm(self) -> None:
        _marker("STAGE2_CONFIRM")
        expected = confirmation_token(self.decision_type, self.pattern_id)
        _emit("expected_confirmation_token", expected)
        _emit("received_matches", self.confirm == expected)
        self.check("STAGE2_CONFIRM", self.confirm == expected, "CONFIRMATION_MISMATCH")
        _emit("authorised_writes", 1)
        _emit("same_packet_as_stage_1", self.reviewed["packet_id"])

    def stage2_write(self) -> None:
        """real write は生涯 1 回だけ。stage 1 と同じ packet を使い、間に rebuild はしない。"""
        _marker("STAGE2_WRITE")
        self.check("STAGE2_WRITE", self.write_attempts == 0, "SECOND_WRITE_ATTEMPT_REFUSED")
        self.write_attempts += 1
        _emit("write_attempt", self.write_attempts)
        try:
            result = self.pilot.service().decide(self.request(), dry_run=False)
        except Exception as exc:                                        # noqa: BLE001 — 再試行せず read-only で確認
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
            rows = self.rows()
        except DecisionStoreCorrupt as corrupt:
            _emit("read_only_inspection", "DECISION_STORE_CORRUPT")
            self.fail("STAGE2_WRITE", f"{WRITE_FAILED_NO_ROW}:STORE_UNREADABLE:{type(corrupt).__name__}")
            return
        known = {str(r.get("decision_id")) for r in self.rows_before}
        matches = [r for r in rows if str(r.get("decision_id")) not in known
                   and str(r.get("pattern_id")) == self.pattern_id
                   and str(r.get("decision_type")) == self.decision_type
                   and str((r.get("metadata") or {}).get("packet_id", "")) == self.reviewed["packet_id"]]
        _emit("matching_new_rows_found", len(matches))
        if len(matches) == 1:
            self.write_response = WRITE_RESPONSE_FAILED
            _emit("write_response", self.write_response)
            _emit("next_step", "AUDIT_THE_EXISTING_ROW; DO NOT WRITE AGAIN")
            return
        if len(matches) > 1:
            _emit("write_response", AMBIGUOUS_WRITE)
            self.fail("STAGE2_WRITE", AMBIGUOUS_WRITE)
        _emit("write_response", WRITE_FAILED_NO_ROW)
        self.fail("STAGE2_WRITE", WRITE_FAILED_NO_ROW)

    # ------------------------------------------------------------- 13-14 audits
    def decision_audit(self) -> None:
        _marker("DECISION_AUDIT")
        rows = self.rows()                                              # records() が sequence と chain を検証する
        _emit("decision_rows_after", len(rows))
        self.check("DECISION_AUDIT", len(rows) == self.expect_rows_before + 1,
                   f"EXPECTED_EXACTLY_ONE_NEW_ROW:{len(rows)}")
        self.check("DECISION_AUDIT", rows[:-1] == self.rows_before, "PRE_EXISTING_ROWS_CHANGED")
        row = dict(rows[-1])
        self.new_row = row
        metadata = dict(row.get("metadata") or {})
        recomputed = dict(row)
        recomputed["record_hash"] = ""
        previous_row = self.rows_before[-1] if self.rows_before else {}
        _emit("decision_row", {k: row.get(k) for k in (
            "decision_id", "sequence", "pattern_id", "decision_type", "actor", "actor_type", "review_mode",
            "promotion_status", "previous_state", "previous_decision_id", "previous_record_hash", "record_hash",
            "decided_at", "idempotency_key", "corpus_size")})
        _emit("metadata_binding", metadata)
        _emit("reason_chars", len(str(row.get("reason") or "")))
        _emit("reason_matches_supplied_human_reason", str(row.get("reason", "")) == self.reason.strip())
        policy_digests = str(metadata.get("policy_digests", ""))
        group_digest = self.reviewed["group_state_digest"]
        checks = [
            ("PATTERN_ID", str(row.get("pattern_id")) == self.pattern_id),
            ("DECISION_TYPE", str(row.get("decision_type")) == self.decision_type),
            ("ACTOR", str(row.get("actor")) == self.actor),
            ("ACTOR_TYPE_HUMAN", str(row.get("actor_type")) == ACTOR_HUMAN),
            ("REVIEW_MODE_FORMAL", str(row.get("review_mode")) == "FORMAL"),
            ("NOT_PROMOTED", str(row.get("promotion_status")) == "NOT_PROMOTED"),
            ("SEQUENCE_IS_NEXT", int(row.get("sequence") or 0) == int(previous_row.get("sequence", 0) or 0) + 1),
            ("PREVIOUS_RECORD_HASH_IS_GLOBAL_TAIL",
             str(row.get("previous_record_hash", "")) == str(previous_row.get("record_hash", ""))),
            ("PREVIOUS_DECISION_ID_IS_PATTERN_HEAD",
             str(row.get("previous_decision_id", "")) == str(self.prior_head.get("decision_id", ""))),
            ("PREVIOUS_STATE_IS_PATTERN_HEAD",
             str(row.get("previous_state", "")) == str(self.prior_head.get("decision_type", ""))),
            ("RECORD_HASH_RECOMPUTES", bool(row.get("record_hash")) and record_hash_for(recomputed) == row.get("record_hash")),
            ("EXACT_HUMAN_REASON_STORED", str(row.get("reason", "")) == self.reason.strip()),
            ("PACKET_ID_BOUND", str(metadata.get("packet_id", "")) == self.reviewed["packet_id"]),
            ("PACKET_EVIDENCE_DIGEST_BOUND",
             str(metadata.get("packet_evidence_digest", "")) == self.reviewed["packet_evidence_digest"]),
            ("MATERIAL_DIGEST_BOUND", str(metadata.get("material_digest", "")) == self.reviewed["material_digest"]),
            ("GROUP_STATE_DIGEST_BOUND", not group_digest or str(metadata.get("group_state_digest", "")) == group_digest),
            ("SIX_POLICY_LAYERS_BOUND",
             all(f"{layer}:{self.reviewed_policy_digests.get(layer, '')}" in policy_digests for layer in POLICY_LAYERS)),
            ("REPLAY_BINDING_PRESENT", bool(metadata.get("replay_run_id")) and bool(metadata.get("replay_run_digest"))),
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
        _emit("real_decisions_written_by_this_operation", written)
        self.check("SAFETY", written == 1, "DECISION_ROW_COUNT_DELTA_NOT_ONE")
        _emit("promotion_status_written", str(self.new_row.get("promotion_status", "")))
        self.check("SAFETY", str(self.new_row.get("promotion_status", "")) == "NOT_PROMOTED", "PROMOTION_STATUS_NOT_NOT_PROMOTED")
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
            self.decision_chain()
            self.baseline()
            self.build()
            self.target()
            self.freshness()
            self.expected_facts()
            self.group_context()
            self.stage1_dry_run()
            self.stage2_confirm()
            self.stage2_write()
            self.decision_audit()
            self.safety_audit()
            _marker("EXECUTION_OK")
            _emit("pattern", self.pattern_id)
            _emit("decision_state", self.decision_type)
            _emit("total_seconds", round(time.perf_counter() - self.t0, 1))
            _marker("END")
            return EXIT_OK
        except (ExecutionFailure, PilotFailure) as exc:
            return self._fail(getattr(exc, "stage", "") or getattr(exc, "section", ""), exc.reason)
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
    parser = argparse.ArgumentParser(description="Phase 3.9.5 generic formal execution session (one candidate, one write)")
    parser.add_argument("--data-root", default="")
    parser.add_argument("--require-commit", default="")
    for layer in POLICY_LAYERS:
        parser.add_argument(f"--expect-{layer.replace('_', '-')}", default="", dest=f"expect_{layer}")
    parser.add_argument("--pattern", required=True, help="exactly one pattern id")
    parser.add_argument("--action", required=True, choices=sorted(ACTIONS))
    parser.add_argument("--actor", required=True, help="human actor id (actor_type is always HUMAN)")
    parser.add_argument("--reason", required=True, help="the human formal decision reason, verbatim")
    parser.add_argument("--confirm", required=True, help="exact token `CONFIRM <STATE> <pattern_id>`")
    parser.add_argument("--expect-rows-before", required=True, type=int, dest="expect_rows_before")
    parser.add_argument("--expect-current-state", required=True, dest="expect_current_state",
                        help="the reviewed formal head state (NONE / KEEP_REVIEWING / REOPENED_FOR_REVIEW / ...)")
    parser.add_argument("--expect-machine-recommendation", default="", dest="expect_machine_recommendation",
                        help="the machine recommendation the human reviewed (APPROVE_RECOMMENDED / REJECT_RECOMMENDED)")
    parser.add_argument("--require-queue-rank", default=None, type=int, dest="require_queue_rank")
    parser.add_argument("--expect-group-state-digest", default="", dest="expect_group_state_digest")
    parser.add_argument("--expect-group-material-digest", default="", dest="expect_group_material_digest",
                        help="reviewed material group view digest; lets an equivalent regeneration pass")
    parser.add_argument("--expect-fact", action="append", default=[], dest="expect_fact",
                        help="key=value from the frozen allowlist (repeatable)")
    parser.add_argument("--acknowledge-sibling", action="append", default=[], dest="acknowledge",
                        help="sibling pattern acknowledged for the frozen C3 rule (repeatable)")
    parser.add_argument("--allow-deferred", action="store_true", dest="allow_deferred",
                        help="explicit opt-in to target a deferred KEEP_REVIEWING pattern (default: refused)")
    parser.add_argument("--skip-git", action="store_true", help="skip repository identity checks (tests only)")
    args = parser.parse_args(argv)
    from .cli import resolve_root

    try:
        facts = dict(parse_fact(item) for item in args.expect_fact)
    except ExecutionFailure as exc:
        _marker("FAIL")
        _emit("stage", exc.stage)
        _emit("reason", exc.reason)
        _emit("write_attempts", 0)
        return EXIT_EXECUTE
    session = FormalExecutionSession(
        resolve_root(args.data_root), Path.cwd(), pattern_id=args.pattern, action=args.action, actor=args.actor,
        reason=args.reason, confirm=args.confirm, expect_rows_before=args.expect_rows_before,
        expect_current_state=args.expect_current_state, expect_recommendation=args.expect_machine_recommendation,
        require_queue_rank=args.require_queue_rank, expect_group_state_digest=args.expect_group_state_digest,
        expect_group_material_digest=args.expect_group_material_digest,
        expect_facts=facts, acknowledge_siblings=tuple(args.acknowledge), allow_deferred=bool(args.allow_deferred),
        require_commit=args.require_commit,
        skip_git=bool(args.skip_git),
        expected_digests={layer: getattr(args, f"expect_{layer}") for layer in POLICY_LAYERS})
    return session.run_all()


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
