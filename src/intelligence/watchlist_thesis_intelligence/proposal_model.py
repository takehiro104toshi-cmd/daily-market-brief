"""P9-A2 — L0 の提案の model（非 authority ・決定論 ・内容 address ・保存しない）。

- `WatchProposal`（`PROMOTION_CANDIDATE`）: 凍結 P8 の完了した run（P9-A1 の `P8RunHandoff`）の **EVALUATED の発行体ごと**に 1 つ。
  MATCH は特別ではない（どの Screener の状態でも提案になる ・状態で選ばない ・並べ替えない）。run 全体の件数（member の結果 ・
  Screener の状態）を必ず持つ（coverage の偏りを隠さない）。`proposal_digest`（`p9prp_<24 hex>`）＝ 全欄の内容 address。入力が
  変われば digest も変わる。人が Watchlist の項目を作るときは、この digest に正確に結び付ける（後の gate の実行器）。
- `ReviewDueProposal`: 見直しの日が caller の渡した日（`as_of`）以前の root（派生 ・保存しない ・時計を読まない）。
- 提案は状態 ・著者 ・審査の瞬間を持たない。authority を作らない ・自動の昇格 ・自動の遷移は無い。

記録: `docs/databank/PHASE9_A2_WATCHLIST_THESIS_SEMANTICS.md`。
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from enum import Enum
from typing import Any, Dict, Iterable, Mapping, Tuple

from .p8_handoff import P8RunHandoff
from .revision_model import SEMANTICS_RULES_VERSION, check_date, check_issuer, derive_id, id_pattern, require
from .thesis_model import P8_SCREENER_STATES
from .watch_model import P8ProposalProvenance

PROPOSAL_ID_PREFIX = "p9prp"
PROPOSAL_SCHEMA_VERSION = "p9_proposal:0.1.0"
#: 提案の意味（L0 ・非 authority ・保存しない）
PROPOSAL_CLASS = "NON_AUTHORITATIVE_L0_PROPOSAL_NOT_PERSISTED_NOT_A_RECOMMENDATION"
_PROPOSAL_RE = id_pattern(PROPOSAL_ID_PREFIX)


class ProposalKind(str, Enum):
    PROMOTION_CANDIDATE = "PROMOTION_CANDIDATE"
    REVIEW_DUE = "REVIEW_DUE"


def _counts(values: Mapping[str, int]) -> Dict[str, int]:
    require(isinstance(values, Mapping) and all(isinstance(k, str) and type(v) is int and v >= 0
                                                for k, v in values.items()), "INVALID_COUNTS", "counts")
    return {key: values[key] for key in sorted(values)}


@dataclass(frozen=True, kw_only=True)
class WatchProposal:
    """P8 の EVALUATED の発行体 1 つの Watchlist の候補（L0）。authority ・状態 ・著者は無い。"""

    run_id: str
    screen_result_id: str
    policy_id: str
    policy_version: int
    universe_id: str
    universe_version: int
    authority_day: date
    issuer_id: str
    screener_state: str
    run_member_count: int
    run_issuer_count: int
    run_member_outcome_counts: Mapping[str, int]
    run_screener_state_counts: Mapping[str, int]
    kind: ProposalKind = ProposalKind.PROMOTION_CANDIDATE
    proposal_class: str = PROPOSAL_CLASS
    rules_version: str = SEMANTICS_RULES_VERSION
    schema_version: str = PROPOSAL_SCHEMA_VERSION

    def __post_init__(self) -> None:
        check_issuer(self.issuer_id)
        check_date(self.authority_day, "authority_day", required=True)
        require(self.screener_state in P8_SCREENER_STATES, "INVALID_SCREENER_STATE", "screener_state")
        require(type(self.run_member_count) is int and type(self.run_issuer_count) is int
                and 1 <= self.run_issuer_count <= self.run_member_count, "INVALID_RUN_COUNTS", "run_counts")
        require(sum(_counts(self.run_member_outcome_counts).values()) == self.run_member_count, "INVALID_RUN_COUNTS",
                "run_member_outcome_counts")
        require(sum(_counts(self.run_screener_state_counts).values()) == self.run_issuer_count, "INVALID_RUN_COUNTS",
                "run_screener_state_counts")
        require(self.kind is ProposalKind.PROMOTION_CANDIDATE, "PROPOSAL_KIND_MISMATCH", "kind")
        require(self.proposal_class == PROPOSAL_CLASS, "PROPOSAL_CLASS_MISMATCH", "proposal_class")

    def as_payload(self) -> Dict[str, Any]:
        return {"authority_day": self.authority_day.isoformat(), "issuer_id": self.issuer_id, "kind": self.kind.value,
                "policy_id": self.policy_id, "policy_version": self.policy_version,
                "proposal_class": self.proposal_class, "rules_version": self.rules_version, "run_id": self.run_id,
                "run_issuer_count": self.run_issuer_count, "run_member_count": self.run_member_count,
                "run_member_outcome_counts": _counts(self.run_member_outcome_counts),
                "run_screener_state_counts": _counts(self.run_screener_state_counts),
                "schema_version": self.schema_version, "screen_result_id": self.screen_result_id,
                "screener_state": self.screener_state, "universe_id": self.universe_id,
                "universe_version": self.universe_version}

    @property
    def proposal_digest(self) -> str:
        return derive_id(PROPOSAL_ID_PREFIX, self.as_payload())

    def provenance(self) -> P8ProposalProvenance:
        """人が結び付ける出所（digest に正確に結び付く）。提案そのものは authority ではない。"""
        return P8ProposalProvenance(run_id=self.run_id, screen_result_id=self.screen_result_id,
                                    policy_id=self.policy_id, policy_version=self.policy_version,
                                    universe_id=self.universe_id, universe_version=self.universe_version,
                                    authority_day=self.authority_day, proposal_digest=self.proposal_digest)


def watch_proposals(handoff: Any) -> Tuple[WatchProposal, ...]:
    """完了した P8 の run（A1 の引き渡し）→ EVALUATED の発行体ごとの提案（状態で選ばない。順は発行体の id の文字の順 ・非意味）。"""
    require(isinstance(handoff, P8RunHandoff), "HANDOFF_INVALID", "handoff")
    meta, result = handoff.metadata, handoff.result
    member_counts = dict(result.member_outcome_counts)
    state_counts = dict(result.screener_state_counts)
    by_issuer = {item.issuer_id: item.evaluation.state.value for item in result.issuer_results}
    return tuple(WatchProposal(run_id=meta.run_id, screen_result_id=meta.screen_result_id,
                               policy_id=meta.policy_id, policy_version=meta.policy_version,
                               universe_id=meta.universe_id, universe_version=meta.universe_version,
                               authority_day=meta.authority_day, issuer_id=issuer_id,
                               screener_state=by_issuer[issuer_id], run_member_count=meta.member_count,
                               run_issuer_count=meta.issuer_count, run_member_outcome_counts=member_counts,
                               run_screener_state_counts=state_counts)
                 for issuer_id in sorted(by_issuer))


def require_proposal_binding(proposal: Any, provenance: Any) -> WatchProposal:
    """人の出所が提案の digest と全欄に正確に結び付くことを要求する（違えば PROPOSAL_BINDING_MISMATCH）。"""
    require(isinstance(proposal, WatchProposal), "PROPOSAL_INVALID", "proposal")
    require(isinstance(provenance, P8ProposalProvenance), "PROVENANCE_INVALID", "provenance")
    require(proposal.provenance() == provenance, "PROPOSAL_BINDING_MISMATCH", "proposal_digest")
    return proposal


@dataclass(frozen=True, kw_only=True)
class ReviewDueProposal:
    """見直しの日が `as_of` 以前の root（派生 ・L0）。OVERDUE は状態として保存しない。"""

    root_id: str
    revision_id: str
    review_due_on: date
    as_of: date
    kind: ProposalKind = ProposalKind.REVIEW_DUE
    proposal_class: str = PROPOSAL_CLASS

    def __post_init__(self) -> None:
        check_date(self.review_due_on, "review_due_on", required=True)
        check_date(self.as_of, "as_of", required=True)
        require(self.review_due_on <= self.as_of, "NOT_DUE", "review_due_on")
        require(self.kind is ProposalKind.REVIEW_DUE, "PROPOSAL_KIND_MISMATCH", "kind")


def review_due_proposals(heads: Iterable[Any], *, as_of: Any) -> Tuple[ReviewDueProposal, ...]:
    """現在の revision（root ごと）→ 見直しの日が `as_of`（caller が渡す日）以前のもの。時計は読まない ・状態を変えない。"""
    day = check_date(as_of, "as_of", required=True)
    due = [ReviewDueProposal(root_id=head.root_id, revision_id=head.revision_id, review_due_on=head.review_due_on,
                             as_of=day)
           for head in heads if head.review_due_on is not None and head.review_due_on <= day]
    return tuple(sorted(due, key=lambda p: p.root_id))


__all__ = ["PROPOSAL_CLASS", "PROPOSAL_ID_PREFIX", "PROPOSAL_SCHEMA_VERSION", "ProposalKind", "ReviewDueProposal",
           "WatchProposal", "require_proposal_binding", "review_due_proposals", "watch_proposals"]
