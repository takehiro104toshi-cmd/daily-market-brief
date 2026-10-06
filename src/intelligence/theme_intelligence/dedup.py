"""Exact dedup review（P6-B3）— THEME_CANDIDATE proposal と既存 Theme / 他 proposal の **exact fingerprint 比較**。

- 出力は DEDUP_REVIEW proposal（RULE）。identity authority ではなく merge を起こさない（人間が NOT_DUPLICATE を記録できる。
  実際の MERGE は Foundation governance の人間操作であり B3 は実行しない）。
- 比較は semantic fingerprint exact と identity core fingerprint exact のみ。similarity / confidence / priority score・
  ranking・nearest・top-N・embedding は無い。複数 exact counterpart は全て列挙し、勝者を選ばない。
- SCOPE_VARIANT / SUBJECT_VARIANT / MECHANISM_VARIANT / PARENT_CHILD_CANDIDATE は生成しない（heuristic を導入しないため）。
- suppression（derived）: 同じ subject fingerprint・同じ counterpart（ref ＋ fingerprint）・同じ basis・同じ dedup model
  version について active な NOT_DUPLICATE があれば再提示しない。fingerprint / version が変われば再提示できる。
  既に同一 id の review が存在する場合も再提示しない（open のまま）。proposal 履歴は削除しない。
- Foundation は `ThemeResolution`（read-only の再構成結果）として受け取るだけで、store を読みも書きもしない。
"""
from __future__ import annotations

from datetime import datetime
from typing import Dict, Iterable, List, Sequence, Set, Tuple

from ..themes.resolver import ResolutionStatus, ThemeResolution
from .proposal_model import (DEDUP_MODEL_VERSION, ComparisonBasis, ComparisonBasisKind, CounterpartKind, DecisionKind,
                             DedupClass, DedupCounterpart, DedupReviewProposal, Proposal, ProposalDecision, ProposalProvenance,
                             ProposalType, ProposerClass, ThemeCandidateProposal)
from .proposal_resolution import ProposalStatus, derive_proposal_status, resolve_active_decision

DEDUP_RULE_REF = "rule:theme_dedup_exact"
_BASIS_FOR_CLASS = {DedupClass.EXACT_SEMANTIC_MATCH: ComparisonBasisKind.SEMANTIC_FINGERPRINT,
                    DedupClass.EXACT_IDENTITY_CORE_MATCH: ComparisonBasisKind.IDENTITY_CORE_FINGERPRINT}


def detect_exact_duplicates(subject: ThemeCandidateProposal, *, resolutions: Sequence[ThemeResolution] = (),
                            proposals: Sequence[Proposal] = (), decisions: Sequence[ProposalDecision] = (),
                            created_at: datetime, dedup_model_version: str = DEDUP_MODEL_VERSION) -> Tuple[DedupReviewProposal, ...]:
    """subject に対する exact dedup review を 0〜2 件返す（EXACT_SEMANTIC_MATCH / EXACT_IDENTITY_CORE_MATCH）。"""
    if not isinstance(subject, ThemeCandidateProposal):
        raise TypeError("dedup subject must be a THEME_CANDIDATE proposal")
    proposals = tuple(proposals)
    decisions = tuple(decisions)
    existing_ids = {p.proposal_id for p in proposals}
    semantic: List[DedupCounterpart] = []
    identity_only: List[DedupCounterpart] = []
    for resolution in resolutions:
        if resolution.status is not ResolutionStatus.RESOLVED or resolution.derived is None:
            continue          # NO_STATE / UNRESOLVED / 失敗の root は比較対象を持たない（推測しない）
        _classify(subject, resolution.derived.semantic_fingerprint, resolution.derived.identity_core_fingerprint,
                  CounterpartKind.THEME_ROOT, resolution.root_id, resolution.observation.observation_id, semantic, identity_only)
    for other in proposals:
        if not isinstance(other, ThemeCandidateProposal) or other.proposal_id == subject.proposal_id:
            continue
        if derive_proposal_status(other, decisions) is ProposalStatus.REJECTED:
            continue          # 却下済み候補は counterpart にしない（履歴は残る）
        _classify(subject, other.semantic_fingerprint, other.identity_core_fingerprint, CounterpartKind.THEME_PROPOSAL,
                  other.proposal_id, "", semantic, identity_only)
    out: List[DedupReviewProposal] = []
    for dedup_class, counterparts, fingerprint in (
            (DedupClass.EXACT_SEMANTIC_MATCH, semantic, subject.semantic_fingerprint),
            (DedupClass.EXACT_IDENTITY_CORE_MATCH, identity_only, subject.identity_core_fingerprint)):
        basis = ComparisonBasis(_BASIS_FOR_CLASS[dedup_class], fingerprint)
        suppressed = suppressed_counterparts(subject.proposal_id, basis, proposals, decisions, dedup_model_version)
        remaining = tuple(sorted((c for c in counterparts if (c.kind, c.ref_id, c.fingerprint) not in suppressed),
                                 key=lambda c: (c.kind.value, c.ref_id)))
        if not remaining:
            continue
        review = DedupReviewProposal.build(
            subject_proposal_id=subject.proposal_id, counterparts=remaining, dedup_class=dedup_class, comparison_basis=basis,
            provenance=ProposalProvenance(ProposerClass.RULE, DEDUP_RULE_REF, rule_version=dedup_model_version,
                                          reason="exact fingerprint comparison"),
            created_at=created_at, dedup_model_version=dedup_model_version)
        if review.proposal_id in existing_ids:
            continue          # 同一 review は既に提示済み（open のまま。再提示しない）
        out.append(review)
    return tuple(out)


def suppressed_counterparts(subject_proposal_id: str, basis: ComparisonBasis, proposals: Iterable[Proposal],
                            decisions: Sequence[ProposalDecision], dedup_model_version: str) -> Set[Tuple[CounterpartKind, str, str]]:
    """active な NOT_DUPLICATE で確定済みの (counterpart kind, ref, fingerprint)（同 subject fingerprint・同 basis・同 version）。"""
    out: Set[Tuple[CounterpartKind, str, str]] = set()
    for proposal in proposals:
        if not isinstance(proposal, DedupReviewProposal) or proposal.subject_proposal_id != subject_proposal_id:
            continue
        if proposal.dedup_model_version != dedup_model_version or proposal.comparison_basis != basis:
            continue
        resolution = resolve_active_decision(proposal.proposal_id, decisions)
        if resolution.active_decision is None or resolution.active_decision.decision is not DecisionKind.NOT_DUPLICATE:
            continue
        for counterpart in proposal.counterparts:
            out.add((counterpart.kind, counterpart.ref_id, counterpart.fingerprint))
    return out


def _classify(subject: ThemeCandidateProposal, semantic_fp: str, core_fp: str, kind: CounterpartKind, ref_id: str,
              observation_id: str, semantic: List[DedupCounterpart], identity_only: List[DedupCounterpart]) -> None:
    if semantic_fp == subject.semantic_fingerprint:
        semantic.append(DedupCounterpart(kind, ref_id, semantic_fp, observation_id))
    elif core_fp == subject.identity_core_fingerprint:
        identity_only.append(DedupCounterpart(kind, ref_id, core_fp, observation_id))


__all__ = ["DEDUP_RULE_REF", "detect_exact_duplicates", "suppressed_counterparts"]
