"""資格判定・独立性・時間多様性・DIRECTLY_EVIDENCED link（A1 Q1〜Q8 / A2 §8 §13 §19）— DERIVED の純関数。

- record を変更しない。governance の受理をしない（L1 → L2 は人間 decision）。score・重み・閾値を持たない。
- 算入対象（A2 §19）: PRIMARY_OBSERVATIONAL × role ∈ {SUPPORTS, CONTRADICTS, INVALIDATES} × quality ≠ MISSING ×
  role_provenance ∈ {RULE, HUMAN}。
- SOURCE DIVERSITY ＝ independent source origin ≥ 2。TEMPORAL DIVERSITY ＝ evidence 日付 ≥ 2。A1 Q5 は両方。
- 独立性は保守的: origin が UNKNOWN の attachment は独立 origin に数えない。footprint（ref_id ∪ origin_key ∪
  lineage_refs）が交差する attachment は同一 origin（転載・派生・同一 record の複数 Fact・Observation とその Fact）。
- 上流の dereference は行わない。model snapshot だけで判定できないものは診断として返す（推測しない）。
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Dict, Iterable, List, Sequence, Tuple

from .model import (EVIDENTIARY_ROLES, SINGLE_PERIOD_FRAMES, EntityLinkClass, EntityRef, EvidenceAttachment,
                    EvidenceAuthorityClass, EvidenceRole, EvidenceTimeQuality, MechanismCertainty, ProvenanceClass,
                    ScopeDimension, ThemeObservation)


class QualificationStatus(str, Enum):
    QUALIFIES_SEMANTICALLY = "QUALIFIES_SEMANTICALLY"
    THEME_CANDIDATE_POSSIBLE = "THEME_CANDIDATE_POSSIBLE"
    DOES_NOT_QUALIFY = "DOES_NOT_QUALIFY"


#: 資格判定に算入する role provenance（LLM_PROPOSAL は provisional。A2 §10）
COUNTED_ROLE_PROVENANCE = (ProvenanceClass.RULE, ProvenanceClass.HUMAN)


# ---------------------------------------------------------------- 算入対象

def counted_attachments(attachments: Iterable[EvidenceAttachment]) -> Tuple[EvidenceAttachment, ...]:
    """A2 §19 の算入対象だけを返す（順序は attachment_key）。"""
    return tuple(sorted(
        (a for a in attachments
         if a.authority_class is EvidenceAuthorityClass.PRIMARY_OBSERVATIONAL
         and a.role in EVIDENTIARY_ROLES
         and a.evidence_time_quality is not EvidenceTimeQuality.MISSING
         and a.role_provenance in COUNTED_ROLE_PROVENANCE),
        key=lambda a: a.attachment_key))


def exclusion_diagnostics(attachments: Iterable[EvidenceAttachment]) -> Tuple[str, ...]:
    """算入されなかった理由を件数付きで返す（推測ではなく明示）。"""
    context = llm = missing = unknown = 0
    for a in attachments:
        if a.role is EvidenceRole.CONTEXT:
            context += 1
            continue
        if a.evidence_time_quality is EvidenceTimeQuality.MISSING:
            missing += 1
            continue
        if a.role_provenance not in COUNTED_ROLE_PROVENANCE:
            llm += 1
            continue
        if not a.source_origin.is_known:
            unknown += 1
    out: List[str] = []
    if context:
        out.append(f"CONTEXT_ROLE_EXCLUDED:{context}")
    if missing:
        out.append(f"MISSING_TIME_EXCLUDED:{missing}")
    if llm:
        out.append(f"LLM_PROPOSAL_ROLE_EXCLUDED:{llm}")
    if unknown:
        out.append(f"UNKNOWN_ORIGIN_EXCLUDED:{unknown}")
    return tuple(out)


# ---------------------------------------------------------------- source origin（独立性）

def origin_footprint(attachment: EvidenceAttachment) -> frozenset:
    """同一 origin 判定の足跡: ref_id ∪ origin_key ∪ lineage_refs。交差すれば同一 origin（保守的）。"""
    origin = attachment.source_origin
    return frozenset({attachment.ref_id, origin.origin_key} | set(origin.lineage_refs))


def source_origin_groups(attachments: Iterable[EvidenceAttachment]) -> Tuple[Tuple[str, ...], ...]:
    """独立 origin ごとの attachment_key の組。UNKNOWN origin は除外（独立とみなさない）。決定論的順序。"""
    known = sorted((a for a in attachments if a.source_origin.is_known), key=lambda a: a.attachment_key)
    parent: Dict[int, int] = {i: i for i in range(len(known))}

    def find(i: int) -> int:
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    footprints = [origin_footprint(a) for a in known]
    for i in range(len(known)):
        for j in range(i + 1, len(known)):
            if footprints[i] & footprints[j]:
                parent[find(i)] = find(j)
    groups: Dict[int, List[str]] = {}
    for i, a in enumerate(known):
        groups.setdefault(find(i), []).append(a.attachment_key)
    return tuple(sorted(tuple(sorted(keys)) for keys in groups.values()))


def source_origin_set(attachments: Iterable[EvidenceAttachment]) -> Tuple[str, ...]:
    """各独立 origin の代表 key（group 内で最小の attachment_key）。"""
    return tuple(group[0] for group in source_origin_groups(attachments))


def independent_origin_count(attachments: Iterable[EvidenceAttachment]) -> int:
    return len(source_origin_groups(attachments))


def has_source_diversity(attachments: Iterable[EvidenceAttachment]) -> bool:
    return independent_origin_count(attachments) >= 2


# ---------------------------------------------------------------- temporal diversity

def evidence_date_set(attachments: Iterable[EvidenceAttachment]) -> Tuple[str, ...]:
    """相異なる evidence 日付（同日内の複数時刻は 1。MISSING は含まない）。"""
    return tuple(sorted({a.evidence_date for a in attachments if a.evidence_date}))


def has_temporal_diversity(attachments: Iterable[EvidenceAttachment]) -> bool:
    return len(evidence_date_set(attachments)) >= 2


# ---------------------------------------------------------------- DIRECTLY_EVIDENCED link（DERIVED）

@dataclass(frozen=True, kw_only=True)
class DirectlyEvidencedLink:
    """付与済み PRIMARY evidence の subject に現れる entity（A2 §13）。再計算専用。observation には保存しない。"""

    entity: EntityRef
    ref_ids: Tuple[str, ...]
    link_class: EntityLinkClass = EntityLinkClass.DIRECTLY_EVIDENCED


def directly_evidenced_links(observation: ThemeObservation) -> Tuple[DirectlyEvidencedLink, ...]:
    by_entity: Dict[Tuple[str, str], set] = {}
    entities: Dict[Tuple[str, str], EntityRef] = {}
    for a in observation.attachments:
        if a.authority_class is not EvidenceAuthorityClass.PRIMARY_OBSERVATIONAL:
            continue
        for e in a.subject_refs:
            key = (e.kind.value, e.value)
            entities[key] = e
            by_entity.setdefault(key, set()).add(a.ref_id)
    return tuple(DirectlyEvidencedLink(entity=entities[k], ref_ids=tuple(sorted(by_entity[k])))
                 for k in sorted(by_entity))


# ---------------------------------------------------------------- 資格判定（純関数。score なし）

@dataclass(frozen=True, kw_only=True)
class QualificationResult:
    status: QualificationStatus
    diagnostics: Tuple[str, ...]
    counted_attachment_keys: Tuple[str, ...]
    independent_origins: int
    evidence_dates: Tuple[str, ...]


def period_frame(observation: ThemeObservation) -> str:
    for token in observation.scope:
        if token.dimension is ScopeDimension.PERIOD_FRAME:
            return token.value
    return ""


def certainty_class_diagnostics(observation: ThemeObservation, counted: Sequence[EvidenceAttachment]) -> Tuple[str, ...]:
    """宣言された確度 class と evidence 集合の整合に関する診断（class を変更・昇降格しない。A1 §12.2）。"""
    out: List[str] = []
    if observation.certainty_class is MechanismCertainty.EVIDENCE_SUPPORTED_MECHANISM:
        if not (has_source_diversity(counted) and has_temporal_diversity(counted)):
            out.append("EVIDENCE_SUPPORTED_CLASS_WITHOUT_DIVERSITY")
        if not any(a.role is EvidenceRole.CONTRADICTS for a in observation.attachments):
            out.append("NO_CONTRADICTING_EVIDENCE_RECORDED")
    if any(a.role is EvidenceRole.CONTRADICTS for a in observation.attachments):
        out.append("HAS_CONTRADICTING_EVIDENCE")
    if any(a.role is EvidenceRole.INVALIDATES for a in observation.attachments):
        out.append("HAS_INVALIDATING_EVIDENCE")
    return tuple(out)


def evaluate_qualification(observation: ThemeObservation) -> QualificationResult:
    """A1 Q1〜Q8 ＋ A2 §19。Q1 / Q2 / Q3 / Q6 / Q8 は model が構造的に保証する。Q7 は model に該当 field が無い。

    - Q4: PERIOD_FRAME が single_session / single_event → DOES_NOT_QUALIFY。
    - Q5: 算入対象について independent origin ≥ 2 かつ evidence 日付 ≥ 2 → QUALIFIES_SEMANTICALLY。
      それ以外 → THEME_CANDIDATE_POSSIBLE（理由を診断で明示）。
    """
    counted = counted_attachments(observation.attachments)
    diagnostics: List[str] = list(exclusion_diagnostics(observation.attachments))
    origins = independent_origin_count(counted)
    dates = evidence_date_set(counted)
    keys = tuple(a.attachment_key for a in counted)
    frame = period_frame(observation)
    if frame in SINGLE_PERIOD_FRAMES:
        diagnostics.append(f"Q4_SINGLE_PERIOD_FRAME:{frame}")
        return QualificationResult(status=QualificationStatus.DOES_NOT_QUALIFY, diagnostics=tuple(diagnostics),
                                   counted_attachment_keys=keys, independent_origins=origins, evidence_dates=dates)
    if not counted:
        diagnostics.append("NO_COUNTED_EVIDENCE")
    else:
        if origins < 2:
            diagnostics.append("SINGLE_SOURCE_ORIGIN" if origins == 1 else "NO_KNOWN_SOURCE_ORIGIN")
        if len(dates) < 2:
            diagnostics.append("SINGLE_EVIDENCE_DATE")
    diagnostics.extend(certainty_class_diagnostics(observation, counted))
    qualifies = bool(counted) and origins >= 2 and len(dates) >= 2
    status = QualificationStatus.QUALIFIES_SEMANTICALLY if qualifies else QualificationStatus.THEME_CANDIDATE_POSSIBLE
    return QualificationResult(status=status, diagnostics=tuple(diagnostics), counted_attachment_keys=keys,
                               independent_origins=origins, evidence_dates=dates)


__all__ = [
    "QualificationStatus", "QualificationResult", "DirectlyEvidencedLink", "COUNTED_ROLE_PROVENANCE",
    "counted_attachments", "exclusion_diagnostics", "origin_footprint", "source_origin_groups", "source_origin_set",
    "independent_origin_count", "has_source_diversity", "evidence_date_set", "has_temporal_diversity",
    "directly_evidenced_links", "period_frame", "certainty_class_diagnostics", "evaluate_qualification",
]
