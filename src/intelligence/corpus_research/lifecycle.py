"""Pattern lifecycle（Phase 3.8 §18–§20）。support count だけでは昇格しない（regime diversity・期間・quality）。

Phase 3.8 が付与できる status は STRONG_PATTERN_CANDIDATE まで。APPROVED / REJECTED / SUPERSEDED は
監督者 process（Phase 3.9）専用で、本モジュールは絶対に返さない。
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Dict, List, Mapping, Sequence

OBSERVED = "OBSERVED"
SUPPORTING_EXAMPLE = "SUPPORTING_EXAMPLE"
NEW_PATTERN_CANDIDATE = "NEW_PATTERN_CANDIDATE"
REVIEW_CANDIDATE = "REVIEW_CANDIDATE"
STRONG_PATTERN_CANDIDATE = "STRONG_PATTERN_CANDIDATE"
APPROVED = "APPROVED"
REJECTED = "REJECTED"
SUPERSEDED = "SUPERSEDED"
STATUSES = (OBSERVED, SUPPORTING_EXAMPLE, NEW_PATTERN_CANDIDATE, REVIEW_CANDIDATE, STRONG_PATTERN_CANDIDATE,
            APPROVED, REJECTED, SUPERSEDED)
PHASE_38_MAX_STATUS = STRONG_PATTERN_CANDIDATE
PHASE_38_ALLOWED = (OBSERVED, NEW_PATTERN_CANDIDATE, REVIEW_CANDIDATE, STRONG_PATTERN_CANDIDATE)


@dataclass(frozen=True)
class SupportProfile:
    support_count: int
    eligible_support: int
    regime_count: int
    span_days: int
    valid_ratio: Decimal
    first_seen: str
    last_seen: str

    def as_dict(self) -> Dict[str, object]:
        return {"support_count": self.support_count, "eligible_support": self.eligible_support,
                "regime_count": self.regime_count, "span_days": self.span_days,
                "valid_ratio": str(self.valid_ratio), "first_seen": self.first_seen, "last_seen": self.last_seen}


def support_profile(assignments: Sequence[Mapping[str, object]]) -> SupportProfile:
    docs = {str(a["document_id"]): a for a in assignments}
    dates = sorted(str(a.get("document_date", "")) for a in docs.values() if a.get("document_date"))
    span = 0
    if len(dates) >= 2:
        try:
            span = (date.fromisoformat(dates[-1]) - date.fromisoformat(dates[0])).days
        except ValueError:
            span = 0
    regimes = {str(a.get("regime_key", "regime:UNKNOWN")) for a in docs.values()}
    regimes.discard("regime:UNKNOWN")
    valid = sum(1 for a in docs.values() if str(a.get("quality", "")) == "VALID")
    eligible = sum(1 for a in docs.values() if a.get("eligible"))
    ratio = (Decimal(valid) / Decimal(len(docs))).quantize(Decimal("0.01")) if docs else Decimal("0")
    return SupportProfile(support_count=len(docs), eligible_support=eligible, regime_count=len(regimes),
                          span_days=span, valid_ratio=ratio, first_seen=dates[0] if dates else "",
                          last_seen=dates[-1] if dates else "")


def lifecycle_status(profile: SupportProfile, thresholds: Mapping[str, object]) -> str:
    """versioned thresholds → status（STRONG_PATTERN_CANDIDATE が上限）。"""
    strong = dict(thresholds.get("strong_candidate") or {})
    review = dict(thresholds.get("review_candidate") or {})
    new = dict(thresholds.get("new_candidate") or {})
    if (profile.eligible_support >= int(strong.get("support", 5)) and profile.regime_count >= int(strong.get("regimes", 3))
            and profile.span_days >= int(strong.get("span_days", 90))
            and profile.valid_ratio >= Decimal(str(strong.get("min_valid_ratio", "1.0")))):
        return STRONG_PATTERN_CANDIDATE
    if (profile.eligible_support >= int(review.get("support", 3)) and profile.regime_count >= int(review.get("regimes", 2))
            and profile.span_days >= int(review.get("span_days", 30))):
        return REVIEW_CANDIDATE
    if profile.support_count >= int(new.get("support", 2)):
        return NEW_PATTERN_CANDIDATE
    return OBSERVED


def pattern_limitations(profile: SupportProfile) -> List[str]:
    """pattern 自身の support から決まる limitation（record に保存。corpus 規模に依存しない＝incremental ≈ rebuild）。"""
    out: List[str] = []
    if profile.regime_count <= 1:
        out.append("SINGLE_REGIME: support comes from one regime signature; not generalizable")
    out.append("NOT_PREDICTIVE: pattern support measures analytical reconstruction, not forecasting accuracy")
    return out


def corpus_limitations(eligible_corpus: int, corpus_span_days: int, thresholds: Mapping[str, object]) -> List[str]:
    """corpus 規模・期間から決まる limitation（registry / snapshot の表示時に付ける）。"""
    out: List[str] = []
    caveat_below = int(thresholds.get("corpus_size_caveat_below", 30))
    if eligible_corpus < caveat_below:
        out.append(f"CORPUS_SIZE: eligible documents {eligible_corpus} < {caveat_below}; research evidence only")
    review = dict(thresholds.get("review_candidate") or {})
    if corpus_span_days < int(review.get("span_days", 30)):
        out.append(f"SHORT_SPAN: corpus spans {corpus_span_days} days; regime diversity cannot be established")
    return out


def limitations(profile: SupportProfile, eligible_corpus: int, corpus_span_days: int,
                thresholds: Mapping[str, object]) -> List[str]:
    """anti-overfitting: 結論に必ず付ける limitation（普遍的な市場ルールとも予測妥当性とも主張しない）。"""
    return corpus_limitations(eligible_corpus, corpus_span_days, thresholds) + pattern_limitations(profile)
