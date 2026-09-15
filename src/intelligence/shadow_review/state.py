"""Current review state（Phase 3.9.3）— append-only event から決定的に導く。history は不変。

順序規則: store の sequence（append 順）。pattern ごとの最後の event が current。
cooldown_until / eligible_for_requeue は **policy の関数**なので event には焼き込まず、
毎回ここで再計算する（policy を変えたら過去に遡って正しく効く）。
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence

from .config import DISAGREE, NEEDS_MORE_EVIDENCE, UNCLEAR, ShadowReviewPolicy
from .cooldown import cooldown_elapsed, cooldown_until
from .models import ShadowReviewEvent


@dataclass(frozen=True)
class CurrentReview:
    pattern_id: str
    last_outcome: str
    last_reviewed_at: str
    last_shadow_review_id: str
    review_count: int
    disagreement_count: int
    needs_more_evidence_count: int
    unclear_count: int
    last_material_digest: str
    last_recommendation: str
    outcome_history: Sequence[Mapping[str, str]] = ()
    recommendation_changed_since: Optional[bool] = None
    materially_changed_since: Optional[bool] = None
    cooldown_until: Optional[str] = None
    eligible_for_requeue: bool = True

    def as_dict(self) -> Dict[str, Any]:
        return {"pattern_id": self.pattern_id, "last_outcome": self.last_outcome,
                "last_reviewed_at": self.last_reviewed_at,
                "last_shadow_review_id": self.last_shadow_review_id,
                "review_count": self.review_count, "disagreement_count": self.disagreement_count,
                "needs_more_evidence_count": self.needs_more_evidence_count,
                "unclear_count": self.unclear_count,
                "last_material_digest": self.last_material_digest,
                "last_recommendation": self.last_recommendation,
                "outcome_history": [dict(h) for h in self.outcome_history],
                "recommendation_changed_since": self.recommendation_changed_since,
                "materially_changed_since": self.materially_changed_since,
                "cooldown_until": self.cooldown_until,
                "eligible_for_requeue": self.eligible_for_requeue}


def derive_current_reviews(events: Iterable[ShadowReviewEvent], policy: ShadowReviewPolicy,
                           current: Optional[Mapping[str, Mapping[str, Any]]] = None,
                           now: Optional[datetime] = None) -> Dict[str, CurrentReview]:
    """pattern ごとの現在状態。`current` は {pattern_id: {material_digest, recommendation}}（任意）。"""
    now = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    current = dict(current or {})
    grouped: Dict[str, List[ShadowReviewEvent]] = {}
    for event in sorted(events, key=lambda e: e.sequence):
        grouped.setdefault(event.pattern_id, []).append(event)

    out: Dict[str, CurrentReview] = {}
    for pattern_id, history in grouped.items():
        last = history[-1]
        now_state = dict(current.get(pattern_id) or {})
        current_recommendation = str(now_state.get("recommendation", ""))
        current_digest = str(now_state.get("material_digest", ""))
        materially_changed: Optional[bool] = None
        recommendation_changed: Optional[bool] = None
        if current_digest:
            materially_changed = current_digest != last.material_digest_at_review
        if current_recommendation:
            recommendation_changed = current_recommendation != last.recommendation_at_review
        until = cooldown_until(last.reviewed_at, last.review_outcome, policy,
                               recommendation_at_review=last.recommendation_at_review,
                               current_recommendation=current_recommendation)
        eligible = bool(materially_changed) or cooldown_elapsed(until, now)
        out[pattern_id] = CurrentReview(
            pattern_id=pattern_id,
            last_outcome=last.review_outcome,
            last_reviewed_at=last.reviewed_at,
            last_shadow_review_id=last.shadow_review_id,
            review_count=len(history),
            disagreement_count=sum(1 for e in history if e.review_outcome == DISAGREE),
            needs_more_evidence_count=sum(1 for e in history if e.review_outcome == NEEDS_MORE_EVIDENCE),
            unclear_count=sum(1 for e in history if e.review_outcome == UNCLEAR),
            last_material_digest=last.material_digest_at_review,
            last_recommendation=last.recommendation_at_review,
            outcome_history=tuple({"reviewed_at": e.reviewed_at, "outcome": e.review_outcome,
                                   "recommendation_at_review": e.recommendation_at_review,
                                   "shadow_review_id": e.shadow_review_id} for e in history),
            recommendation_changed_since=recommendation_changed,
            materially_changed_since=materially_changed,
            cooldown_until=until,
            eligible_for_requeue=eligible)
    return out
