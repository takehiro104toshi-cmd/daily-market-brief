"""P9-A4 — 人の判断の実行器（人の入力 → 決定論の検査 → A2 の revision の作成 → A3 `AuthorityStores` への追記）。

authority を作るのは検査済みの人の入力だけ（自動の作成 ・遷移 ・提案の受理 ・機械の著者は無い）。runtime で A2 の authority の
revision を作るのは本 module だけ（guard）。書き込みは A3 の `AuthorityStores.append_watch` ／ `append_thesis` だけ。

- P8 の提案からの Watchlist の作成: 明示の P8 root ・run ・`screen_result_id` → A1 `reconstruct_bound`（drift は
  `P8_RESULT_DRIFT`）→ 発行体が再構成の結果にあり member が EVALUATED → 同じ引き渡しから提案を決定論で再生成 → 入力の
  `proposal_digest` と完全一致 → 出所（`P8_PROPOSAL`）。MATCH は特別ではない。指標の値は取り込まない。
- `MANUAL` の作成: 明示の P8 root の凍結 A1 の人が審査した発行体の登録の record（`p8_identity`。上場 ・coverage の主張ではない）。
- 更新（REVISE ・TRANSITION ・CORRECTION）: 人が審査した先頭 `expected_head_revision_id` から seq ・prev を導く（caller は選べない）。
  同じ入力の再試行で同じ revision が既にあれば `REUSED`。無ければ現在の鎖の先頭が期待の先頭でなければ `STALE_AUTHORITY_HEAD`
  （新しい先頭に読み替えない）。
- Thesis の作成: Watchlist の項目が在り、`reviewed_at` の時点で REMOVED でなく、発行体が同じ。新しい P8 の根拠は再構成で確かめる。
- 最終の authority の検査は A3（鎖の先頭 ・`check_world`）。`dry_run` は書かずに同じ検査をする。

記録: `docs/databank/PHASE9_A4_HUMAN_DECISION_EXECUTOR.md`。
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Optional, Tuple

from .authority_stores import AuthorityStores
from .cross_rules import check_world
from .decision_model import (DecisionKind, ThesisContent, ThesisCreate, ThesisUpdate, WatchCreateFromProposal,
                             WatchCreateManual, WatchUpdate)
from .p8_handoff import HandoffError, reconstruct_bound
from .p8_identity import IssuerRecordError, confirm_reviewed_issuer_record
from .private_root import PrivateRootError, require_separate_roots
from .proposal_model import require_proposal_binding, watch_proposals
from .revision_model import ChangeKind, SemanticModelError
from .thesis_model import (InvalidationCondition, P8ScreenEvidence, ThesisRevision, ThesisStatus,
                           derive_condition_id, derive_thesis_id, validate_thesis_successor)
from .watch_model import (ManualProvenance, WATCH_TRANSITIONS, WatchEntryRevision, WatchStatus,
                          derive_watch_entry_id, validate_watch_successor)

EXECUTOR_RULES_VERSION = "p9_human_decision_executor:0.1.0"


class ExecutorError(ValueError):
    def __init__(self, code: str, detail: str = "") -> None:
        super().__init__(f"{code}: {detail}" if detail else code)
        self.code = code
        self.detail = detail


def _require(condition: bool, code: str, detail: str = "") -> None:
    if not condition:
        raise ExecutorError(code, detail)


@dataclass(frozen=True, kw_only=True)
class ExecutionReceipt:
    """本人の local な受領（P9 の id だけ。発行体 ・文 ・値は無い）。次の更新の `expected_head_revision_id` に使う。"""

    decision_kind: str
    status: str
    root_id: str
    revision_id: str
    seq: int

    def as_dict(self) -> Dict[str, Any]:
        return {"decision_kind": self.decision_kind, "revision_id": self.revision_id, "root_id": self.root_id,
                "seq": self.seq, "status": self.status}


def _build(factory: Any, **fields: Any) -> Any:
    try:
        return factory(**fields)
    except SemanticModelError as exc:
        raise ExecutorError(f"INVALID_DECISION:{exc.code}", exc.detail) from None


class HumanDecisionExecutor:
    """1 つの P9 の private root の authority に、人の判断を 1 つずつ適用する（P8 の root は read-only の照合だけ）。"""

    def __init__(self, p9_root: Any, *, p8_root: Any = None) -> None:
        if p8_root is not None:
            try:
                require_separate_roots(p8_root, p9_root)
            except PrivateRootError as exc:
                raise ExecutorError(exc.code, exc.detail) from None
        self.p8_root = p8_root
        self.stores = AuthorityStores.open(p9_root)

    # ------------------------------------------------------------ 入口

    def execute(self, decision: Any, *, dry_run: bool = False) -> ExecutionReceipt:
        if isinstance(decision, WatchCreateFromProposal):
            revision = self._watch_from_proposal(decision)
        elif isinstance(decision, WatchCreateManual):
            revision = self._watch_manual(decision)
        elif isinstance(decision, WatchUpdate):
            revision = self._watch_update(decision)
        elif isinstance(decision, ThesisCreate):
            revision = self._thesis_create(decision)
        elif isinstance(decision, ThesisUpdate):
            revision = self._thesis_update(decision)
        else:
            raise ExecutorError("INVALID_DECISION", "type")
        return self._apply(decision.kind, revision, dry_run=dry_run)

    # ------------------------------------------------------------ Watchlist

    def _p8_root(self) -> Any:
        _require(self.p8_root is not None, "P8_ROOT_REQUIRED", "p8_root")
        return self.p8_root

    def _handoff(self, run_id: str, screen_result_id: str) -> Any:
        try:
            return reconstruct_bound(self._p8_root(), run_id=run_id, screen_result_id=screen_result_id)
        except HandoffError as exc:
            raise ExecutorError(exc.code, exc.detail) from None

    @staticmethod
    def _evaluated(handoff: Any, issuer_id: str) -> None:
        members = [m for m in handoff.result.member_outcomes if m.issuer_id == issuer_id]
        _require(len(members) >= 1, "PROPOSAL_ISSUER_ABSENT", "issuer_id")
        _require(any(m.kind.value == "EVALUATED" for m in members), "PROPOSAL_MEMBER_NOT_EVALUATED", "issuer_id")

    def _watch_from_proposal(self, decision: WatchCreateFromProposal) -> WatchEntryRevision:
        handoff = self._handoff(decision.run_id, decision.screen_result_id)
        self._evaluated(handoff, decision.issuer_id)
        proposals = {p.issuer_id: p for p in watch_proposals(handoff)}             # 同じ引き渡しから決定論で再生成
        proposal = proposals.get(decision.issuer_id)
        _require(proposal is not None, "PROPOSAL_ISSUER_ABSENT", "issuer_id")
        _require(proposal.proposal_digest == decision.proposal_digest, "PROPOSAL_DIGEST_MISMATCH", "proposal_digest")
        provenance = proposal.provenance()
        require_proposal_binding(proposal, provenance)
        return self._watch_create(decision, provenance)

    def _watch_manual(self, decision: WatchCreateManual) -> WatchEntryRevision:
        try:
            confirm_reviewed_issuer_record(self._p8_root(), decision.issuer_id, decision.reviewed_at)
        except IssuerRecordError as exc:
            raise ExecutorError(exc.code, exc.detail) from None
        return self._watch_create(decision, ManualProvenance())

    @staticmethod
    def _watch_create(decision: Any, provenance: Any) -> WatchEntryRevision:
        root = derive_watch_entry_id(issuer_id=decision.issuer_id, author_ref=decision.author_ref,
                                     reviewed_at=decision.reviewed_at, provenance=provenance)
        return _build(WatchEntryRevision, watch_entry_id=root, seq=1, prev_revision_id="",
                      change_kind=ChangeKind.CREATE, issuer_id=decision.issuer_id, status=WatchStatus.ACTIVE,
                      rationale=decision.rationale, review_due_on=decision.review_due_on, removal_reason="",
                      thesis_ids=(), provenance=provenance, author_ref=decision.author_ref,
                      reviewed_at=decision.reviewed_at)

    def _expected(self, store: Any, root_id: str, expected_id: str, missing_code: str) -> Tuple[Tuple[Any, ...], Any]:
        _require(root_id in store.roots(), missing_code, root_id)
        chain = store.chain(root_id)
        expected = store.revision(expected_id)
        _require(expected is not None and expected.root_id == root_id, "EXPECTED_HEAD_UNKNOWN",
                 "expected_head_revision_id")
        return chain, expected

    def _watch_update(self, decision: WatchUpdate) -> WatchEntryRevision:
        chain, head = self._expected(self.stores.watch, decision.watch_entry_id, decision.expected_head_revision_id,
                                     "WATCH_ENTRY_NOT_FOUND")
        kind = {DecisionKind.WATCH_REVISE: ChangeKind.REVISE, DecisionKind.WATCH_TRANSITION: ChangeKind.TRANSITION,
                DecisionKind.WATCH_CORRECTION: ChangeKind.CORRECTION}[decision.kind]
        status = head.status
        if kind is ChangeKind.TRANSITION:
            _require(decision.to_status in WATCH_TRANSITIONS[head.status], "ILLEGAL_TRANSITION",
                     f"{head.status.value}->{decision.to_status.value}")
            status = decision.to_status
        revision = _build(WatchEntryRevision, watch_entry_id=head.watch_entry_id, seq=head.seq + 1,
                          prev_revision_id=head.revision_id, change_kind=kind, issuer_id=head.issuer_id,
                          status=status, rationale=decision.rationale, review_due_on=decision.review_due_on,
                          removal_reason=decision.removal_reason, thesis_ids=tuple(sorted(decision.thesis_ids)),
                          provenance=head.provenance, author_ref=decision.author_ref,
                          reviewed_at=decision.reviewed_at, corrects_revision_id=decision.corrects_revision_id,
                          correction_reason=decision.correction_reason)
        return self._successor(self.stores.watch, chain, head, revision, validate_watch_successor)

    # ------------------------------------------------------------ Thesis

    def _check_new_p8_evidence(self, content: ThesisContent, issuer_id: str, known: Tuple[Any, ...] = ()) -> None:
        """新しい P8 の根拠だけを再構成で確かめる（発行体が EVALUATED ・Screener の状態が一致）。"""
        fresh = [e for e in (*content.supporting_evidence, *content.counter_evidence)
                 if isinstance(e, P8ScreenEvidence) and e not in known]
        handoffs: Dict[Tuple[str, str], Any] = {}
        for evidence in fresh:
            key = (evidence.run_id, evidence.screen_result_id)
            if key not in handoffs:
                handoffs[key] = self._handoff(*key)
            handoff = handoffs[key]
            self._evaluated(handoff, evidence.issuer_id)
            states = {r.issuer_id: r.evaluation.state.value for r in handoff.result.issuer_results}
            _require(evidence.issuer_id == issuer_id and states.get(evidence.issuer_id) == evidence.screener_state,
                     "P8_EVIDENCE_MISMATCH", "screener_state")

    @staticmethod
    def _conditions(thesis_id: str, content: ThesisContent) -> Tuple[InvalidationCondition, ...]:
        return tuple(_build(InvalidationCondition, condition_id=derive_condition_id(thesis_id, c.key), key=c.key,
                            text=c.text) for c in content.invalidation_conditions)

    @staticmethod
    def _content_fields(thesis_id: str, content: ThesisContent) -> Dict[str, Any]:
        return dict(statement=content.statement, mechanism=content.mechanism, catalysts=content.catalysts,
                    risks=content.risks, assumptions=content.assumptions,
                    invalidation_conditions=HumanDecisionExecutor._conditions(thesis_id, content),
                    supporting_evidence=content.supporting_evidence, counter_evidence=content.counter_evidence,
                    horizon_note=content.horizon_note, confidence_note=content.confidence_note)

    def _thesis_create(self, decision: ThesisCreate) -> ThesisRevision:
        _require(decision.watch_entry_id in self.stores.watch.roots(), "WATCH_ENTRY_NOT_FOUND",
                 decision.watch_entry_id)
        watch = self.stores.watch.state_at(decision.watch_entry_id, decision.reviewed_at)
        _require(watch is not None and watch.status is not WatchStatus.REMOVED, "WATCH_ENTRY_NOT_LIVE_AT_REVIEW",
                 decision.watch_entry_id)
        _require(watch.issuer_id == decision.issuer_id, "ISSUER_MISMATCH", "issuer_id")
        self._check_new_p8_evidence(decision.content, decision.issuer_id)
        thesis_id = derive_thesis_id(issuer_id=decision.issuer_id, watch_entry_id=decision.watch_entry_id,
                                     author_ref=decision.author_ref, reviewed_at=decision.reviewed_at)
        return _build(ThesisRevision, thesis_id=thesis_id, seq=1, prev_revision_id="", change_kind=ChangeKind.CREATE,
                      issuer_id=decision.issuer_id, watch_entry_id=decision.watch_entry_id,
                      status=ThesisStatus.ACTIVE, review_due_on=decision.review_due_on,
                      author_ref=decision.author_ref, reviewed_at=decision.reviewed_at,
                      **self._content_fields(thesis_id, decision.content))

    def _thesis_update(self, decision: ThesisUpdate) -> ThesisRevision:
        chain, head = self._expected(self.stores.thesis, decision.thesis_id, decision.expected_head_revision_id,
                                     "THESIS_NOT_FOUND")
        kind = {DecisionKind.THESIS_REVISE: ChangeKind.REVISE, DecisionKind.THESIS_TRANSITION: ChangeKind.TRANSITION,
                DecisionKind.THESIS_CORRECTION: ChangeKind.CORRECTION}[decision.kind]
        if kind is ChangeKind.TRANSITION:                                         # 内容は先頭のまま ・状態だけ
            content = {name: head.__dict__[name] for name in (
                "statement", "mechanism", "catalysts", "risks", "assumptions", "invalidation_conditions",
                "supporting_evidence", "counter_evidence", "horizon_note", "confidence_note")}
            by_key = {c.key: c.condition_id for c in head.invalidation_conditions}
            unknown = [k for k in decision.invalidated_condition_keys if k not in by_key]
            _require(not unknown, "UNKNOWN_CONDITION_KEY", ",".join(unknown))
            status, extra = decision.to_status, dict(
                status_reason=decision.status_reason, invalidation_basis=decision.invalidation_basis,
                invalidated_condition_ids=tuple(sorted(by_key[k] for k in decision.invalidated_condition_keys)))
        else:
            self._check_new_p8_evidence(decision.content, head.issuer_id,
                                        (*head.supporting_evidence, *head.counter_evidence))
            content = self._content_fields(head.thesis_id, decision.content)
            status, extra = head.status, dict(corrects_revision_id=decision.corrects_revision_id,
                                              correction_reason=decision.correction_reason)
        revision = _build(ThesisRevision, thesis_id=head.thesis_id, seq=head.seq + 1,
                          prev_revision_id=head.revision_id, change_kind=kind, issuer_id=head.issuer_id,
                          watch_entry_id=head.watch_entry_id, status=status, review_due_on=decision.review_due_on,
                          author_ref=decision.author_ref, reviewed_at=decision.reviewed_at, **content, **extra)
        return self._successor(self.stores.thesis, chain, head, revision, validate_thesis_successor)

    # ------------------------------------------------------------ 先頭 ・冪等 ・追記

    @staticmethod
    def _successor(store: Any, chain: Tuple[Any, ...], head: Any, revision: Any, validate: Any) -> Any:
        if store.revision(revision.revision_id) is not None:                      # 同じ入力の再試行 → A3 が REUSED
            return revision
        _require(chain[-1].revision_id == head.revision_id, "STALE_AUTHORITY_HEAD", head.root_id)
        try:
            validate(head, revision, chain)
        except SemanticModelError as exc:
            raise ExecutorError(f"INVALID_DECISION:{exc.code}", exc.detail) from None
        return revision

    def _apply(self, kind: DecisionKind, revision: Any, *, dry_run: bool) -> ExecutionReceipt:
        watch = isinstance(revision, WatchEntryRevision)
        store = self.stores.watch if watch else self.stores.thesis
        if dry_run:                                                               # 書かずに A3 と同じ世界の検査
            self.stores.watch.verify_unchanged()
            self.stores.thesis.verify_unchanged()
            status = "VALID"
            if store.revision(revision.revision_id) is None:
                try:
                    check_world(list(self.stores.watch.all_revisions() + ((revision,) if watch else ())),
                                list(self.stores.thesis.all_revisions() + (() if watch else (revision,))))
                except SemanticModelError as exc:
                    raise ExecutorError(f"WOULD_BE_REJECTED:{exc.code}", exc.detail) from None
            else:
                status = "WOULD_REUSE"
        else:
            result = self.stores.append_watch(revision) if watch else self.stores.append_thesis(revision)
            status = result.status.value
        return ExecutionReceipt(decision_kind=kind.value, status=status, root_id=revision.root_id,
                                revision_id=revision.revision_id, seq=revision.seq)


__all__ = ["EXECUTOR_RULES_VERSION", "ExecutionReceipt", "ExecutorError", "HumanDecisionExecutor"]
