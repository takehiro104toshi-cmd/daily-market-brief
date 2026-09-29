"""SAME_ROOT_NEW_OBSERVATION の純 helper（A2 §16 / A3 §5 §15）。永続化・時計・PENDING 修復は含まない。

- root_id を保持し、previous_observation_id ＝ 直前 observation の id とする。
- identity core（主題 / driver / channel / domain）が変われば IDENTITY_CORE_CHANGED で拒否する
  （NEW_ROOT_REQUIRED。successor は governance 経路。A3 §19）。
- recorded_at は注入され、直前より前であれば NON_MONOTONIC_RECORDED_AT（A3 §5 規則 4）。
- DERIVED 値は複製しない（record に存在しないため構造的に不可能）。
"""
from __future__ import annotations

from datetime import datetime
from typing import Optional, Sequence

from .fingerprint import identity_core_unchanged
from .model import (EvidenceAttachment, InferredExposureLink, InvalidationCondition, Limitation, Mechanism,
                    MechanismCertainty, ObservationProvenance, ScopeToken, ThemeModelError, ThemeObservation,
                    ThemeSubject)


def revise_observation(previous: ThemeObservation, *, recorded_at: datetime, provenance: ObservationProvenance,
                       subject: Optional[ThemeSubject] = None, mechanism: Optional[Mechanism] = None,
                       certainty_class: Optional[MechanismCertainty] = None,
                       scope: Optional[Sequence[ScopeToken]] = None,
                       limitations: Optional[Sequence[Limitation]] = None,
                       invalidation_conditions: Optional[Sequence[InvalidationCondition]] = None,
                       inferred_links: Optional[Sequence[InferredExposureLink]] = None,
                       attachments: Optional[Sequence[EvidenceAttachment]] = None) -> ThemeObservation:
    """同一 root の新 observation を構築する（None の field は直前から引き継ぐ）。"""
    if not isinstance(previous, ThemeObservation):
        raise ThemeModelError("INVALID_TYPE", "previous must be ThemeObservation")
    candidate = ThemeObservation.build(
        root_id=previous.root_id, previous_observation_id=previous.observation_id,
        subject=previous.subject if subject is None else subject,
        mechanism=previous.mechanism if mechanism is None else mechanism,
        certainty_class=previous.certainty_class if certainty_class is None else certainty_class,
        scope=previous.scope if scope is None else scope,
        limitations=previous.limitations if limitations is None else limitations,
        invalidation_conditions=(previous.invalidation_conditions if invalidation_conditions is None
                                 else invalidation_conditions),
        inferred_links=previous.inferred_links if inferred_links is None else inferred_links,
        attachments=previous.attachments if attachments is None else attachments,
        provenance=provenance, recorded_at=recorded_at)
    if candidate.recorded_at < previous.recorded_at:
        raise ThemeModelError("NON_MONOTONIC_RECORDED_AT",
                              "a revision cannot be recorded before its predecessor (A3 §5)")
    if not identity_core_unchanged(previous, candidate):
        raise ThemeModelError("IDENTITY_CORE_CHANGED",
                              "subject / driver / channel / domain changed: NEW_ROOT_REQUIRED (A2 §2.3 / §16)")
    return candidate


def attach_evidence(previous: ThemeObservation, new_attachments: Sequence[EvidenceAttachment], *,
                    recorded_at: datetime, provenance: ObservationProvenance) -> ThemeObservation:
    """evidence を追加した新 observation（SAME_ROOT_NEW_OBSERVATION）。既存 attachment は attached_at ごと引き継ぐ。"""
    if not new_attachments:
        raise ThemeModelError("MISSING_FIELD", "attach_evidence requires at least one attachment")
    return revise_observation(previous, recorded_at=recorded_at, provenance=provenance,
                              attachments=tuple(previous.attachments) + tuple(new_attachments))


__all__ = ["revise_observation", "attach_evidence"]
