"""P9-A4 — Watchlist ／ Thesis の private な安全な投影（件数だけ ・派生 ・非 authority ・保存しない）と、見直しの日の報告。

- 安全な投影（既定）: caller が渡す瞬間 `at`（aware）の各 root の状態と、caller が渡す日 `as_of_date` から、状態 ・出所の種類 ・
  根拠の種類 ・無効の根拠 ・見直しの日が来た数の **件数だけ** を作る。発行体 ・名前 ・code ・理由 ・主張 ・根拠の文 ・run ・
  `screen_result_id` ・提案の digest ・著者 ・正確な `reviewed_at` ・財務の値 ・閾値 ・P9 の id は欄が無い。
- 見直しの日の報告（private な root ごとの view ・既定の投影とは別）: A2 の `review_due_proposals`（L0 ・P9 の id と日だけ）。
- 時計を読まない ・追記しない ・状態を変えない ・OVERDUE ／ 期限を保存しない。公開の出力は無い。

記録: `docs/databank/PHASE9_A4_HUMAN_DECISION_EXECUTOR.md`。
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from typing import Any, Dict, Iterable, Tuple

from .proposal_model import ReviewDueProposal, review_due_proposals
from .revision_model import SEMANTICS_RULES_VERSION, check_date, check_instant

PROJECTION_SCHEMA_VERSION = "p9_safe_authority_projection:0.1.0"
PROJECTION_CLASS = "DERIVED_SAFE_PROJECTION_COUNTS_ONLY_NON_AUTHORITY_NON_PERSISTENT_PRIVATE_LOCAL"
#: 既定の投影に決して置かない欄（test が pin する）
FORBIDDEN_PROJECTION_FIELDS: Tuple[str, ...] = (
    "issuer_id", "issuer_ids", "name", "code", "rationale", "statement", "mechanism", "note", "evidence_text",
    "run_id", "screen_result_id", "proposal_digest", "author_ref", "reviewed_at", "value", "threshold",
    "watch_entry_id", "thesis_id", "revision_id", "root_id")


def _counts(values: Iterable[str]) -> Dict[str, int]:
    counts: Dict[str, int] = {}
    for value in values:
        counts[value] = counts.get(value, 0) + 1
    return {key: counts[key] for key in sorted(counts)}


@dataclass(frozen=True, kw_only=True)
class SafeAuthorityProjection:
    as_of_date: date
    watch_entry_count: int
    watch_status_counts: Dict[str, int]
    watch_provenance_kind_counts: Dict[str, int]
    watch_review_due_count: int
    watch_declared_thesis_link_count: int
    thesis_count: int
    thesis_status_counts: Dict[str, int]
    thesis_review_due_count: int
    thesis_invalidation_basis_counts: Dict[str, int]
    thesis_supporting_evidence_kind_counts: Dict[str, int]
    thesis_counter_evidence_kind_counts: Dict[str, int]
    projection_class: str = PROJECTION_CLASS
    rules_version: str = SEMANTICS_RULES_VERSION
    schema_version: str = PROJECTION_SCHEMA_VERSION

    def as_dict(self) -> Dict[str, Any]:
        return {"as_of_date": self.as_of_date.isoformat(), "projection_class": self.projection_class,
                "rules_version": self.rules_version, "schema_version": self.schema_version,
                "thesis": {"count": self.thesis_count, "status_counts": dict(self.thesis_status_counts),
                           "review_due_count": self.thesis_review_due_count,
                           "invalidation_basis_counts": dict(self.thesis_invalidation_basis_counts),
                           "supporting_evidence_kind_counts": dict(self.thesis_supporting_evidence_kind_counts),
                           "counter_evidence_kind_counts": dict(self.thesis_counter_evidence_kind_counts)},
                "watch": {"count": self.watch_entry_count, "status_counts": dict(self.watch_status_counts),
                          "provenance_kind_counts": dict(self.watch_provenance_kind_counts),
                          "review_due_count": self.watch_review_due_count,
                          "declared_thesis_link_count": self.watch_declared_thesis_link_count}}


def _heads(stores: Any, at: datetime) -> Tuple[Tuple[Any, ...], Tuple[Any, ...]]:
    instant = check_instant(at, "at")
    return tuple(stores.watch.states_at(instant).values()), tuple(stores.thesis.states_at(instant).values())


def safe_projection(stores: Any, *, at: datetime, as_of_date: date) -> SafeAuthorityProjection:
    """時点 `at` の像の件数だけ（`as_of_date` は見直しの日の比較だけに使う）。"""
    day = check_date(as_of_date, "as_of_date", required=True)
    watches, theses = _heads(stores, at)
    due = lambda heads: sum(1 for h in heads if h.review_due_on is not None and h.review_due_on <= day)  # noqa: E731
    return SafeAuthorityProjection(
        as_of_date=day, watch_entry_count=len(watches), watch_status_counts=_counts(h.status.value for h in watches),
        watch_provenance_kind_counts=_counts(h.provenance.kind.value for h in watches),
        watch_review_due_count=due(watches), watch_declared_thesis_link_count=sum(len(h.thesis_ids) for h in watches),
        thesis_count=len(theses), thesis_status_counts=_counts(h.status.value for h in theses),
        thesis_review_due_count=due(theses),
        thesis_invalidation_basis_counts=_counts(h.invalidation_basis.value for h in theses if h.invalidation_basis),
        thesis_supporting_evidence_kind_counts=_counts(e.kind.value for h in theses for e in h.supporting_evidence),
        thesis_counter_evidence_kind_counts=_counts(e.kind.value for h in theses for e in h.counter_evidence))


def review_due_report(stores: Any, *, at: datetime, as_of_date: date) -> Tuple[ReviewDueProposal, ...]:
    """private な root ごとの見直しの日の報告（L0 ・P9 の id と日だけ ・既定の投影とは別）。"""
    watches, theses = _heads(stores, at)
    return review_due_proposals((*watches, *theses), as_of=as_of_date)


__all__ = ["FORBIDDEN_PROJECTION_FIELDS", "PROJECTION_CLASS", "PROJECTION_SCHEMA_VERSION",
           "SafeAuthorityProjection", "review_due_report", "safe_projection"]
