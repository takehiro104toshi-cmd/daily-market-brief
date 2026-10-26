"""P9-A4 — 人が書く判断 ／ 著述の入力の model と、その正準の復元（純 ・既定値なし ・時計なし）。

authority を持つ値（`author_ref` ・`reviewed_at` ・`review_due_on` ・理由 ・内容 ・出所の結び付き ・訂正の参照 ・更新の基準の
`expected_head_revision_id`）は全て入力に明示する。seq ・prev ・root id ・revision id は入力に無い（実行器が検査済みの鎖から導く）。

| kind | 意味 |
|---|---|
| `WATCH_CREATE_FROM_PROPOSAL` | P8 の L0 の提案（run ・`screen_result_id` ・`proposal_digest`）に結び付く Watchlist の作成 |
| `WATCH_CREATE_MANUAL` | 人が直接作る Watchlist の項目（凍結 A1 の人が審査した発行体の record の確認つき） |
| `WATCH_REVISE` ／ `WATCH_TRANSITION` ／ `WATCH_CORRECTION` | 既存の項目の内容 ・状態 ・訂正 |
| `THESIS_CREATE` ／ `THESIS_REVISE` ／ `THESIS_TRANSITION` ／ `THESIS_CORRECTION` | Thesis の作成 ・内容 ・状態 ・訂正 |

記録: `docs/databank/PHASE9_A4_HUMAN_DECISION_EXECUTOR.md`。
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from enum import Enum
from typing import Any, Dict, Optional, Tuple, Union

from .revision_model import (SemanticModelError, check_author, check_date, check_id, check_instant, check_issuer,
                             check_text, id_pattern, require)
from .thesis_model import HumanNoteEvidence, InvalidationBasis, P8ScreenEvidence, ThesisStatus
from .watch_model import WatchStatus

DECISION_SCHEMA_VERSION = "p9_human_decision:0.1.0"
_WATCH_ENTRY_RE = id_pattern("p9wat")
_WATCH_REVISION_RE = id_pattern("p9wrv")
_THESIS_RE = id_pattern("p9ths")
_THESIS_REVISION_RE = id_pattern("p9trv")
_RUN_RE = id_pattern("p8run")
_SCREEN_RESULT_RE = id_pattern("p8srs")
_PROPOSAL_RE = id_pattern("p9prp")


class DecisionKind(str, Enum):
    WATCH_CREATE_FROM_PROPOSAL = "WATCH_CREATE_FROM_PROPOSAL"
    WATCH_CREATE_MANUAL = "WATCH_CREATE_MANUAL"
    WATCH_REVISE = "WATCH_REVISE"
    WATCH_TRANSITION = "WATCH_TRANSITION"
    WATCH_CORRECTION = "WATCH_CORRECTION"
    THESIS_CREATE = "THESIS_CREATE"
    THESIS_REVISE = "THESIS_REVISE"
    THESIS_TRANSITION = "THESIS_TRANSITION"
    THESIS_CORRECTION = "THESIS_CORRECTION"


def _governance(author_ref: Any, reviewed_at: Any) -> None:
    check_author(author_ref)
    check_instant(reviewed_at, "reviewed_at")


@dataclass(frozen=True, kw_only=True)
class WatchCreateFromProposal:
    issuer_id: str
    run_id: str
    screen_result_id: str
    proposal_digest: str
    rationale: str
    review_due_on: date
    author_ref: str
    reviewed_at: datetime
    kind: DecisionKind = DecisionKind.WATCH_CREATE_FROM_PROPOSAL

    def __post_init__(self) -> None:
        check_issuer(self.issuer_id)
        check_id(self.run_id, _RUN_RE, "run_id")
        check_id(self.screen_result_id, _SCREEN_RESULT_RE, "screen_result_id")
        check_id(self.proposal_digest, _PROPOSAL_RE, "proposal_digest")
        check_text(self.rationale, "rationale")
        check_date(self.review_due_on, "review_due_on", required=True)
        _governance(self.author_ref, self.reviewed_at)


@dataclass(frozen=True, kw_only=True)
class WatchCreateManual:
    issuer_id: str
    rationale: str
    review_due_on: date
    author_ref: str
    reviewed_at: datetime
    kind: DecisionKind = DecisionKind.WATCH_CREATE_MANUAL

    def __post_init__(self) -> None:
        check_issuer(self.issuer_id)
        check_text(self.rationale, "rationale")
        check_date(self.review_due_on, "review_due_on", required=True)
        _governance(self.author_ref, self.reviewed_at)


@dataclass(frozen=True, kw_only=True)
class WatchUpdate:
    """REVISE ／ TRANSITION ／ CORRECTION（人が審査した先頭 `expected_head_revision_id` に結び付く）。"""

    kind: DecisionKind
    watch_entry_id: str
    expected_head_revision_id: str
    rationale: str
    review_due_on: Optional[date]
    thesis_ids: Tuple[str, ...]
    author_ref: str
    reviewed_at: datetime
    to_status: Optional[WatchStatus] = None
    removal_reason: str = ""
    corrects_revision_id: str = ""
    correction_reason: str = ""

    def __post_init__(self) -> None:
        require(self.kind in (DecisionKind.WATCH_REVISE, DecisionKind.WATCH_TRANSITION,
                              DecisionKind.WATCH_CORRECTION), "INVALID_DECISION_KIND", "kind")
        check_id(self.watch_entry_id, _WATCH_ENTRY_RE, "watch_entry_id")
        check_id(self.expected_head_revision_id, _WATCH_REVISION_RE, "expected_head_revision_id")
        check_text(self.rationale, "rationale")
        check_date(self.review_due_on, "review_due_on", required=False)
        _governance(self.author_ref, self.reviewed_at)
        require((self.to_status is not None) == (self.kind is DecisionKind.WATCH_TRANSITION),
                "TO_STATUS_ONLY_FOR_TRANSITION", "to_status")
        require(self.to_status is None or isinstance(self.to_status, WatchStatus), "INVALID_STATUS", "to_status")
        is_correction = self.kind is DecisionKind.WATCH_CORRECTION
        require(bool(self.corrects_revision_id) == is_correction, "CORRECTION_REFERENCE_ONLY_FOR_CORRECTION",
                "corrects_revision_id")


@dataclass(frozen=True, kw_only=True)
class ConditionInput:
    key: str
    text: str


@dataclass(frozen=True, kw_only=True)
class ThesisContent:
    """Thesis の内容（人の文）。根拠は A2 の型（`P8_SCREEN_RESULT` ・`HUMAN_NOTE`）。"""

    statement: str
    mechanism: str
    catalysts: Tuple[str, ...]
    risks: Tuple[str, ...]
    assumptions: Tuple[str, ...]
    invalidation_conditions: Tuple[ConditionInput, ...]
    supporting_evidence: Tuple[Union[P8ScreenEvidence, HumanNoteEvidence], ...]
    counter_evidence: Tuple[Union[P8ScreenEvidence, HumanNoteEvidence], ...]
    horizon_note: str
    confidence_note: str

    def __post_init__(self) -> None:
        require(isinstance(self.invalidation_conditions, tuple) and all(
            isinstance(c, ConditionInput) for c in self.invalidation_conditions), "INVALID_CONDITIONS",
            "invalidation_conditions")


@dataclass(frozen=True, kw_only=True)
class ThesisCreate:
    watch_entry_id: str
    issuer_id: str
    content: ThesisContent
    review_due_on: date
    author_ref: str
    reviewed_at: datetime
    kind: DecisionKind = DecisionKind.THESIS_CREATE

    def __post_init__(self) -> None:
        check_id(self.watch_entry_id, _WATCH_ENTRY_RE, "watch_entry_id")
        check_issuer(self.issuer_id)
        require(isinstance(self.content, ThesisContent), "INVALID_CONTENT", "content")
        check_date(self.review_due_on, "review_due_on", required=True)
        _governance(self.author_ref, self.reviewed_at)


@dataclass(frozen=True, kw_only=True)
class ThesisUpdate:
    """REVISE（内容）／ TRANSITION（状態 ・内容は先頭のまま）／ CORRECTION（内容の訂正 ・状態は先頭のまま）。"""

    kind: DecisionKind
    thesis_id: str
    expected_head_revision_id: str
    review_due_on: Optional[date]
    author_ref: str
    reviewed_at: datetime
    content: Optional[ThesisContent] = None
    to_status: Optional[ThesisStatus] = None
    status_reason: str = ""
    invalidation_basis: Optional[InvalidationBasis] = None
    invalidated_condition_keys: Tuple[str, ...] = ()
    corrects_revision_id: str = ""
    correction_reason: str = ""

    def __post_init__(self) -> None:
        require(self.kind in (DecisionKind.THESIS_REVISE, DecisionKind.THESIS_TRANSITION,
                              DecisionKind.THESIS_CORRECTION), "INVALID_DECISION_KIND", "kind")
        check_id(self.thesis_id, _THESIS_RE, "thesis_id")
        check_id(self.expected_head_revision_id, _THESIS_REVISION_RE, "expected_head_revision_id")
        check_date(self.review_due_on, "review_due_on", required=False)
        _governance(self.author_ref, self.reviewed_at)
        transition = self.kind is DecisionKind.THESIS_TRANSITION
        require((self.content is None) == transition, "CONTENT_ONLY_FOR_REVISE_OR_CORRECTION", "content")
        require((self.to_status is not None) == transition, "TO_STATUS_ONLY_FOR_TRANSITION", "to_status")
        require(bool(self.corrects_revision_id) == (self.kind is DecisionKind.THESIS_CORRECTION),
                "CORRECTION_REFERENCE_ONLY_FOR_CORRECTION", "corrects_revision_id")


Decision = Union[WatchCreateFromProposal, WatchCreateManual, WatchUpdate, ThesisCreate, ThesisUpdate]


# ---------------------------------------------------------------- 正準の復元（人の判断の file。既定値の補完なし）


def _fields(data: Any, names: Tuple[str, ...], what: str) -> Dict[str, Any]:
    require(isinstance(data, dict), "INVALID_DECISION", what)
    require(set(data) == set(names), "DECISION_FIELDS_MISMATCH", f"{what}:{sorted(set(data) ^ set(names))}")
    return data


def _instant(value: Any) -> datetime:
    require(isinstance(value, str), "INVALID_INSTANT", "reviewed_at")
    try:
        return datetime.fromisoformat(value)                                     # aware の検査は model
    except ValueError:
        raise SemanticModelError("INVALID_INSTANT", "reviewed_at") from None


def _day(value: Any, what: str) -> Optional[date]:
    if value is None:
        return None
    require(isinstance(value, str), "INVALID_DATE", what)
    try:
        parsed = date.fromisoformat(value)
    except ValueError:
        raise SemanticModelError("INVALID_DATE", what) from None
    require(parsed.isoformat() == value, "NON_CANONICAL_DATE", what)
    return parsed


def _strings(value: Any, what: str) -> Tuple[str, ...]:
    require(isinstance(value, list) and all(isinstance(v, str) for v in value), "INVALID_LIST", what)
    return tuple(value)


def _enum(cls: Any, value: Any, what: str) -> Any:
    if value is None:
        return None
    try:
        return cls(value)
    except ValueError:
        raise SemanticModelError("INVALID_ENUM", what) from None


def _evidence(item: Any) -> Union[P8ScreenEvidence, HumanNoteEvidence]:
    require(isinstance(item, dict), "INVALID_EVIDENCE", "evidence")
    if item.get("kind") == "HUMAN_NOTE":
        _fields(item, ("kind", "note"), "evidence")
        return HumanNoteEvidence(note=item["note"])
    _fields(item, ("issuer_id", "kind", "run_id", "screen_result_id", "screener_state"), "evidence")
    require(item["kind"] == "P8_SCREEN_RESULT", "INVALID_EVIDENCE_KIND", "evidence")
    return P8ScreenEvidence(run_id=item["run_id"], screen_result_id=item["screen_result_id"],
                            issuer_id=item["issuer_id"], screener_state=item["screener_state"])


_CONTENT_FIELDS = ("assumptions", "catalysts", "confidence_note", "counter_evidence", "horizon_note",
                   "invalidation_conditions", "mechanism", "risks", "statement", "supporting_evidence")


def _content(data: Any) -> ThesisContent:
    data = _fields(data, _CONTENT_FIELDS, "content")
    require(isinstance(data["invalidation_conditions"], list), "INVALID_LIST", "invalidation_conditions")
    require(isinstance(data["supporting_evidence"], list) and isinstance(data["counter_evidence"], list),
            "INVALID_LIST", "evidence")
    return ThesisContent(
        statement=data["statement"], mechanism=data["mechanism"], catalysts=_strings(data["catalysts"], "catalysts"),
        risks=_strings(data["risks"], "risks"), assumptions=_strings(data["assumptions"], "assumptions"),
        invalidation_conditions=tuple(ConditionInput(**_fields(c, ("key", "text"), "condition"))
                                      for c in data["invalidation_conditions"]),
        supporting_evidence=tuple(_evidence(e) for e in data["supporting_evidence"]),
        counter_evidence=tuple(_evidence(e) for e in data["counter_evidence"]),
        horizon_note=data["horizon_note"], confidence_note=data["confidence_note"])


_SPECS: Dict[DecisionKind, Tuple[str, ...]] = {
    DecisionKind.WATCH_CREATE_FROM_PROPOSAL: ("issuer_id", "run_id", "screen_result_id", "proposal_digest",
                                              "rationale", "review_due_on"),
    DecisionKind.WATCH_CREATE_MANUAL: ("issuer_id", "rationale", "review_due_on"),
    DecisionKind.WATCH_REVISE: ("watch_entry_id", "expected_head_revision_id", "rationale", "review_due_on",
                                "thesis_ids"),
    DecisionKind.WATCH_TRANSITION: ("watch_entry_id", "expected_head_revision_id", "rationale", "review_due_on",
                                    "thesis_ids", "to_status", "removal_reason"),
    DecisionKind.WATCH_CORRECTION: ("watch_entry_id", "expected_head_revision_id", "rationale", "review_due_on",
                                    "thesis_ids", "corrects_revision_id", "correction_reason"),
    DecisionKind.THESIS_CREATE: ("watch_entry_id", "issuer_id", "content", "review_due_on"),
    DecisionKind.THESIS_REVISE: ("thesis_id", "expected_head_revision_id", "content", "review_due_on"),
    DecisionKind.THESIS_TRANSITION: ("thesis_id", "expected_head_revision_id", "review_due_on", "to_status",
                                     "status_reason", "invalidation_basis", "invalidated_condition_keys"),
    DecisionKind.THESIS_CORRECTION: ("thesis_id", "expected_head_revision_id", "content", "review_due_on",
                                     "corrects_revision_id", "correction_reason"),
}


def decision_from_dict(data: Any) -> Decision:
    """人の判断の file（JSON の dict）→ 入力の model。schema ・kind ・欄の集合の完全一致（既定値の補完なし）。"""
    require(isinstance(data, dict), "INVALID_DECISION", "decision")
    require(data.get("schema_version") == DECISION_SCHEMA_VERSION, "DECISION_SCHEMA_MISMATCH", "schema_version")
    kind = _enum(DecisionKind, data.get("kind"), "kind")
    require(kind is not None, "INVALID_DECISION_KIND", "kind")
    data = _fields(data, ("schema_version", "kind", "author_ref", "reviewed_at") + _SPECS[kind], kind.value)
    common = dict(author_ref=data["author_ref"], reviewed_at=_instant(data["reviewed_at"]),
                  review_due_on=_day(data["review_due_on"], "review_due_on"))
    if kind is DecisionKind.WATCH_CREATE_FROM_PROPOSAL:
        return WatchCreateFromProposal(issuer_id=data["issuer_id"], run_id=data["run_id"],
                                       screen_result_id=data["screen_result_id"],
                                       proposal_digest=data["proposal_digest"], rationale=data["rationale"], **common)
    if kind is DecisionKind.WATCH_CREATE_MANUAL:
        return WatchCreateManual(issuer_id=data["issuer_id"], rationale=data["rationale"], **common)
    if kind in (DecisionKind.WATCH_REVISE, DecisionKind.WATCH_TRANSITION, DecisionKind.WATCH_CORRECTION):
        return WatchUpdate(kind=kind, watch_entry_id=data["watch_entry_id"],
                           expected_head_revision_id=data["expected_head_revision_id"], rationale=data["rationale"],
                           thesis_ids=_strings(data["thesis_ids"], "thesis_ids"),
                           to_status=_enum(WatchStatus, data.get("to_status"), "to_status"),
                           removal_reason=data.get("removal_reason", ""),
                           corrects_revision_id=data.get("corrects_revision_id", ""),
                           correction_reason=data.get("correction_reason", ""), **common)
    if kind is DecisionKind.THESIS_CREATE:
        return ThesisCreate(watch_entry_id=data["watch_entry_id"], issuer_id=data["issuer_id"],
                            content=_content(data["content"]), **common)
    return ThesisUpdate(kind=kind, thesis_id=data["thesis_id"],
                        expected_head_revision_id=data["expected_head_revision_id"],
                        content=_content(data["content"]) if "content" in data else None,
                        to_status=_enum(ThesisStatus, data.get("to_status"), "to_status"),
                        status_reason=data.get("status_reason", ""),
                        invalidation_basis=_enum(InvalidationBasis, data.get("invalidation_basis"),
                                                 "invalidation_basis"),
                        invalidated_condition_keys=_strings(data.get("invalidated_condition_keys", []),
                                                            "invalidated_condition_keys"),
                        corrects_revision_id=data.get("corrects_revision_id", ""),
                        correction_reason=data.get("correction_reason", ""), **common)


__all__ = ["ConditionInput", "DECISION_SCHEMA_VERSION", "Decision", "DecisionKind", "ThesisContent", "ThesisCreate",
           "ThesisUpdate", "WatchCreateFromProposal", "WatchCreateManual", "WatchUpdate", "decision_from_dict"]
