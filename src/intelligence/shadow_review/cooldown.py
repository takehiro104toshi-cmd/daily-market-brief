"""Cooldown（Phase 3.9.3）— 「一度見たものをいつまた出すか」。

**重要な意味論**: cooldown の数値 0 は「cooldown 無し（毎日出す）」ではなく
`MATERIAL_CHANGE_ONLY`（時間経過では二度と戻さない。material change のみが再提示する）を意味する。
DISAGREE と NEEDS_MORE_EVIDENCE がこれに当たる。人間が明確に否定したものを日数経過だけで
再提示しない、という設計判断であり、数値の見た目に反するのでテストで固定する。

material change は常に cooldown を上書きする（§16）。REJECT_RECOMMENDED は
`adverse_cooldown_cap` 日で必ず再確認の機会を作る（逆行証拠を長く寝かせない）。
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Optional

from ..evaluation.models import REJECT_RECOMMENDED
from .config import MATERIAL_CHANGE_ONLY, ShadowReviewPolicy

MATERIAL_CHANGE_ONLY_LABEL = "MATERIAL_CHANGE_ONLY"


def is_material_change_only(days: int) -> bool:
    return int(days) <= MATERIAL_CHANGE_ONLY


def effective_cooldown_days(outcome: str, policy: ShadowReviewPolicy,
                            recommendation_at_review: str = "",
                            current_recommendation: str = "") -> Optional[int]:
    """有効 cooldown 日数。None = 時間では戻さない（material change のみ）。

    REJECT_RECOMMENDED（レビュー時点 or 現在）のときは adverse_cooldown_cap を上限として必ず適用し、
    material-change-only であっても cap 日で戻す。
    """
    configured = policy.cooldown_days(outcome)
    adverse = REJECT_RECOMMENDED in (recommendation_at_review, current_recommendation)
    if adverse:
        cap = int(policy.adverse_cooldown_cap)
        if is_material_change_only(configured):
            return cap
        return min(int(configured), cap)
    if is_material_change_only(configured):
        return None
    return int(configured)


def cooldown_until(last_reviewed_at: str, outcome: str, policy: ShadowReviewPolicy,
                   recommendation_at_review: str = "", current_recommendation: str = "") -> Optional[str]:
    """cooldown 満了時刻（ISO-8601 UTC）。None = 時間では戻さない。"""
    days = effective_cooldown_days(outcome, policy, recommendation_at_review, current_recommendation)
    if days is None:
        return None
    moment = _parse(last_reviewed_at)
    if moment is None:
        return None
    return (moment + timedelta(days=days)).astimezone(timezone.utc).isoformat()


def cooldown_elapsed(cooldown_until_iso: Optional[str], now: datetime) -> bool:
    """cooldown が満了しているか。None（material-change-only）は常に False。"""
    if not cooldown_until_iso:
        return False
    moment = _parse(cooldown_until_iso)
    if moment is None:
        return False
    return now.astimezone(timezone.utc) >= moment


def _parse(value: str) -> Optional[datetime]:
    try:
        moment = datetime.fromisoformat(str(value))
    except (TypeError, ValueError):
        return None
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return moment.astimezone(timezone.utc)
