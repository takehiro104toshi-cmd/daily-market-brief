"""P9-A2 — Thesis の意味の model（発行体だけ ・人が書く ・不変の revision ・純）。

Thesis ＝ 人が書いた「なぜこの発行体を追うか」の説明（主張 ・仕組み ・きっかけ ・危険 ・前提 ・無効の条件 ・根拠 ・反証）。推奨 ・目標株価 ・
期待収益 ・建玉 ・売買の指示は無い。確信は文だけ（数 ・順序の欄は無い）。

- root: `thesis_id`（`p9ths_<24 hex>`）＝ 発行体 ・Watchlist の項目 ・著者 ・作成の reviewed_at。revision: `p9trv_<24 hex>`。
- 無効の条件: 人が付けた key から安定の `condition_id`（`p9inv_<24 hex>` ＝ thesis ・key）。文を直しても id は変わらない。
- 根拠: v1 は `P8_SCREEN_RESULT`（run ・結果 ・発行体 ・Screener の状態。指標の値は無い）と `HUMAN_NOTE` だけ。支持 ・反証は別の欄。
- 状態: `ACTIVE` ・`CHALLENGED` ・`INVALIDATED`（終端）・`RETIRED`（終端）。(作成) → ACTIVE ／ ACTIVE → ACTIVE（REVISE）／
  ACTIVE ⇄ CHALLENGED ／ ACTIVE ・CHALLENGED → INVALIDATED ・RETIRED。INVALIDATED は直前の revision の既知の条件の id か、
  明示の OTHER ＋ 人の理由。自動の遷移は無い。

記録: `docs/databank/PHASE9_A2_WATCHLIST_THESIS_SEMANTICS.md`。
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime
from enum import Enum
from typing import Any, Dict, Optional, Sequence, Tuple, Union

from .revision_model import (ChangeKind, SEMANTICS_RULES_VERSION, check_author, check_correction_reference, check_date,
                             check_id, check_instant, check_issuer, check_successor_frame, check_text,
                             check_text_list, derive_id, id_pattern, iso_date, iso_instant, ordered_chain, require)

THESIS_ID_PREFIX = "p9ths"
THESIS_REVISION_ID_PREFIX = "p9trv"
CONDITION_ID_PREFIX = "p9inv"
THESIS_SCHEMA_VERSION = "p9_thesis_revision:0.1.0"
THESIS_AUTHORITY_CLASS = "HUMAN_AUTHORED_THESIS_NOT_A_RECOMMENDATION_NOT_A_TRADE_INSTRUCTION"
#: 凍結 P8 の Screener の状態（複製。一致は test が凍結 B1 の enum で pin）
P8_SCREENER_STATES: Tuple[str, ...] = ("MATCH", "NO_MATCH", "HOLD", "NOT_EVALUABLE", "AUTHORITY_FAILURE")
_THESIS_RE = id_pattern(THESIS_ID_PREFIX)
_THESIS_REVISION_RE = id_pattern(THESIS_REVISION_ID_PREFIX)
_CONDITION_RE = id_pattern(CONDITION_ID_PREFIX)
_WATCH_ENTRY_RE = id_pattern("p9wat")
_RUN_ID_RE = id_pattern("p8run")
_SCREEN_RESULT_ID_RE = id_pattern("p8srs")
_KEY_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,31}$")
#: 確信の文が数 ・割合 ・比だけなら拒む（数の確信は点数の代わりになる）。普通の文は検閲しない
_BARE_NUMBER_RE = re.compile(r"^\s*[+-]?\d+(\.\d+)?\s*(%|/\s*\d+(\.\d+)?)?\s*$")


class ThesisStatus(str, Enum):
    ACTIVE = "ACTIVE"
    CHALLENGED = "CHALLENGED"
    INVALIDATED = "INVALIDATED"
    RETIRED = "RETIRED"


LIVE_THESIS_STATUSES: Tuple[ThesisStatus, ...] = (ThesisStatus.ACTIVE, ThesisStatus.CHALLENGED)
#: 状態機械（人の TRANSITION だけ）。INVALIDATED ・RETIRED は終端。ACTIVE → ACTIVE は REVISE（内容の revision）
THESIS_TRANSITIONS: Dict[ThesisStatus, Tuple[ThesisStatus, ...]] = {
    ThesisStatus.ACTIVE: (ThesisStatus.CHALLENGED, ThesisStatus.INVALIDATED, ThesisStatus.RETIRED),
    ThesisStatus.CHALLENGED: (ThesisStatus.ACTIVE, ThesisStatus.INVALIDATED, ThesisStatus.RETIRED),
    ThesisStatus.INVALIDATED: (),
    ThesisStatus.RETIRED: (),
}


class InvalidationBasis(str, Enum):
    CONDITIONS = "CONDITIONS"
    OTHER = "OTHER"


class EvidenceKind(str, Enum):
    P8_SCREEN_RESULT = "P8_SCREEN_RESULT"
    HUMAN_NOTE = "HUMAN_NOTE"


@dataclass(frozen=True, kw_only=True)
class P8ScreenEvidence:
    """凍結 P8 の完了した run の 1 発行体の結果への参照（状態だけ ・指標の値なし）。"""

    run_id: str
    screen_result_id: str
    issuer_id: str
    screener_state: str
    kind: EvidenceKind = EvidenceKind.P8_SCREEN_RESULT

    def __post_init__(self) -> None:
        check_id(self.run_id, _RUN_ID_RE, "run_id")
        check_id(self.screen_result_id, _SCREEN_RESULT_ID_RE, "screen_result_id")
        check_issuer(self.issuer_id)
        require(self.screener_state in P8_SCREENER_STATES, "INVALID_SCREENER_STATE", "screener_state")
        require(self.kind is EvidenceKind.P8_SCREEN_RESULT, "EVIDENCE_KIND_MISMATCH", "kind")

    def as_dict(self) -> Dict[str, Any]:
        return {"issuer_id": self.issuer_id, "kind": self.kind.value, "run_id": self.run_id,
                "screen_result_id": self.screen_result_id, "screener_state": self.screener_state}


@dataclass(frozen=True, kw_only=True)
class HumanNoteEvidence:
    note: str
    kind: EvidenceKind = EvidenceKind.HUMAN_NOTE

    def __post_init__(self) -> None:
        check_text(self.note, "note")
        require(self.kind is EvidenceKind.HUMAN_NOTE, "EVIDENCE_KIND_MISMATCH", "kind")

    def as_dict(self) -> Dict[str, Any]:
        return {"kind": self.kind.value, "note": self.note}


Evidence = Union[P8ScreenEvidence, HumanNoteEvidence]


def derive_condition_id(thesis_id: str, key: str) -> str:
    return derive_id(CONDITION_ID_PREFIX, {"key": key, "thesis_id": thesis_id})


@dataclass(frozen=True, kw_only=True)
class InvalidationCondition:
    """無効の条件（人の文）。`condition_id` は thesis ・key から導く安定の id（文を直しても変わらない）。"""

    condition_id: str
    key: str
    text: str

    def __post_init__(self) -> None:
        check_id(self.condition_id, _CONDITION_RE, "condition_id")
        require(isinstance(self.key, str) and bool(_KEY_RE.match(self.key)), "INVALID_CONDITION_KEY", "key")
        check_text(self.text, "invalidation_condition")

    def as_dict(self) -> Dict[str, Any]:
        return {"condition_id": self.condition_id, "key": self.key, "text": self.text}


def derive_thesis_id(*, issuer_id: str, watch_entry_id: str, author_ref: str, reviewed_at: datetime) -> str:
    return derive_id(THESIS_ID_PREFIX, {"author_ref": author_ref, "issuer_id": issuer_id,
                                        "reviewed_at": iso_instant(reviewed_at), "watch_entry_id": watch_entry_id})


def _check_evidence(values: Any, field_name: str, issuer_id: str) -> None:
    require(isinstance(values, tuple), "INVALID_EVIDENCE", field_name)
    for evidence in values:
        require(isinstance(evidence, (P8ScreenEvidence, HumanNoteEvidence)), "INVALID_EVIDENCE_KIND", field_name)
        if isinstance(evidence, P8ScreenEvidence):
            require(evidence.issuer_id == issuer_id, "EVIDENCE_ISSUER_MISMATCH", field_name)
    require(len({_evidence_key(e) for e in values}) == len(values), "DUPLICATE_EVIDENCE", field_name)


def _evidence_key(evidence: Evidence) -> str:
    return derive_id("p9evd", evidence.as_dict())


@dataclass(frozen=True, kw_only=True)
class ThesisRevision:
    """Thesis の不変の 1 revision（人の authority）。上書きしない。"""

    thesis_id: str
    seq: int
    prev_revision_id: str
    change_kind: ChangeKind
    issuer_id: str
    watch_entry_id: str
    status: ThesisStatus
    statement: str
    mechanism: str
    catalysts: Tuple[str, ...]
    risks: Tuple[str, ...]
    assumptions: Tuple[str, ...]
    invalidation_conditions: Tuple[InvalidationCondition, ...]
    supporting_evidence: Tuple[Evidence, ...]
    counter_evidence: Tuple[Evidence, ...]
    horizon_note: str
    review_due_on: Optional[date]
    confidence_note: str
    author_ref: str
    reviewed_at: datetime
    status_reason: str = ""
    invalidation_basis: Optional[InvalidationBasis] = None
    invalidated_condition_ids: Tuple[str, ...] = ()
    corrects_revision_id: str = ""
    correction_reason: str = ""
    authority_class: str = THESIS_AUTHORITY_CLASS
    rules_version: str = SEMANTICS_RULES_VERSION
    schema_version: str = THESIS_SCHEMA_VERSION

    def __post_init__(self) -> None:
        check_id(self.thesis_id, _THESIS_RE, "thesis_id")
        check_id(self.watch_entry_id, _WATCH_ENTRY_RE, "watch_entry_id")
        require(type(self.seq) is int and self.seq >= 1, "INVALID_SEQ", "seq")
        require(isinstance(self.change_kind, ChangeKind), "INVALID_CHANGE_KIND", "change_kind")
        require(isinstance(self.status, ThesisStatus), "INVALID_STATUS", "status")
        check_issuer(self.issuer_id)
        check_author(self.author_ref)
        check_instant(self.reviewed_at, "reviewed_at")
        check_text(self.statement, "statement")
        check_text(self.mechanism, "mechanism")
        for name in ("catalysts", "risks", "assumptions"):
            check_text_list(self.__dict__[name], name)
        check_text(self.horizon_note, "horizon_note", required=False)
        check_text(self.confidence_note, "confidence_note", required=False)      # 文だけ（型は str）
        require(not _BARE_NUMBER_RE.match(self.confidence_note), "NUMERIC_CONFIDENCE_REJECTED", "confidence_note")
        require(isinstance(self.invalidation_conditions, tuple) and len(self.invalidation_conditions) >= 1,
                "INVALIDATION_CONDITIONS_REQUIRED", "invalidation_conditions")
        for condition in self.invalidation_conditions:
            require(isinstance(condition, InvalidationCondition), "INVALID_CONDITION", "invalidation_conditions")
            require(condition.condition_id == derive_condition_id(self.thesis_id, condition.key),
                    "CONDITION_ID_MISMATCH", condition.key)
        require(len({c.key for c in self.invalidation_conditions}) == len(self.invalidation_conditions),
                "DUPLICATE_CONDITION_KEY", "invalidation_conditions")
        _check_evidence(self.supporting_evidence, "supporting_evidence", self.issuer_id)
        _check_evidence(self.counter_evidence, "counter_evidence", self.issuer_id)
        supporting = {_evidence_key(e) for e in self.supporting_evidence}
        require(not supporting & {_evidence_key(e) for e in self.counter_evidence},
                "EVIDENCE_BOTH_SUPPORTING_AND_COUNTER", "counter_evidence")
        live = self.status in LIVE_THESIS_STATUSES
        check_date(self.review_due_on, "review_due_on", required=live)
        if not live:
            require(self.review_due_on is None, "REVIEW_DUE_ON_TERMINAL", "review_due_on")
        if self.change_kind is ChangeKind.TRANSITION:
            check_text(self.status_reason, "status_reason")                     # 遷移の人の理由
        else:
            require(self.status_reason == "", "STATUS_REASON_ONLY_FOR_TRANSITION", "status_reason")
        self._check_invalidation()
        if self.seq == 1:
            require(self.change_kind is ChangeKind.CREATE and self.prev_revision_id == ""
                    and self.status is ThesisStatus.ACTIVE, "INVALID_INITIAL_REVISION", "seq")
            require(self.thesis_id == derive_thesis_id(issuer_id=self.issuer_id, watch_entry_id=self.watch_entry_id,
                                                       author_ref=self.author_ref, reviewed_at=self.reviewed_at),
                    "THESIS_ID_MISMATCH", "thesis_id")
        else:
            check_id(self.prev_revision_id, _THESIS_REVISION_RE, "prev_revision_id")
        if self.change_kind is ChangeKind.CORRECTION:
            check_id(self.corrects_revision_id, _THESIS_REVISION_RE, "corrects_revision_id")
            check_text(self.correction_reason, "correction_reason")
        else:
            require(self.corrects_revision_id == "" and self.correction_reason == "", "CORRECTION_FIELDS_UNEXPECTED",
                    "corrects_revision_id")
        require(self.authority_class == THESIS_AUTHORITY_CLASS, "AUTHORITY_CLASS_MISMATCH", "authority_class")
        require(self.rules_version == SEMANTICS_RULES_VERSION, "RULES_VERSION_MISMATCH", "rules_version")
        require(self.schema_version == THESIS_SCHEMA_VERSION, "SCHEMA_MISMATCH", "schema_version")

    def _check_invalidation(self) -> None:
        if self.status is not ThesisStatus.INVALIDATED:
            require(self.invalidation_basis is None and self.invalidated_condition_ids == (),
                    "INVALIDATION_FIELDS_ONLY_FOR_INVALIDATED", "invalidation_basis")
            return
        require(isinstance(self.invalidation_basis, InvalidationBasis), "INVALIDATION_BASIS_REQUIRED",
                "invalidation_basis")
        ids = self.invalidated_condition_ids
        require(isinstance(ids, tuple) and len(set(ids)) == len(ids) and list(ids) == sorted(ids),
                "INVALID_CONDITION_REFS", "invalidated_condition_ids")
        if self.invalidation_basis is InvalidationBasis.CONDITIONS:
            known = {c.condition_id for c in self.invalidation_conditions}
            require(len(ids) >= 1 and set(ids) <= known, "UNKNOWN_CONDITION_REF", "invalidated_condition_ids")
        else:                                                                    # OTHER ＋ 人の理由（status_reason）
            require(ids == (), "OTHER_WITH_CONDITION_REFS", "invalidated_condition_ids")

    @property
    def root_id(self) -> str:
        return self.thesis_id

    @property
    def condition_ids(self) -> Tuple[str, ...]:
        return tuple(sorted(c.condition_id for c in self.invalidation_conditions))

    def identity_payload(self) -> Dict[str, Any]:
        return {"assumptions": list(self.assumptions), "authority_class": self.authority_class,
                "author_ref": self.author_ref, "catalysts": list(self.catalysts),
                "change_kind": self.change_kind.value, "confidence_note": self.confidence_note,
                "correction_reason": self.correction_reason, "corrects_revision_id": self.corrects_revision_id,
                "counter_evidence": [e.as_dict() for e in self.counter_evidence],
                "horizon_note": self.horizon_note,
                "invalidated_condition_ids": list(self.invalidated_condition_ids),
                "invalidation_basis": self.invalidation_basis.value if self.invalidation_basis else None,
                "invalidation_conditions": [c.as_dict() for c in self.invalidation_conditions],
                "issuer_id": self.issuer_id, "mechanism": self.mechanism, "prev_revision_id": self.prev_revision_id,
                "review_due_on": iso_date(self.review_due_on), "reviewed_at": iso_instant(self.reviewed_at),
                "risks": list(self.risks), "rules_version": self.rules_version, "schema_version": self.schema_version,
                "seq": self.seq, "statement": self.statement, "status": self.status.value,
                "status_reason": self.status_reason,
                "supporting_evidence": [e.as_dict() for e in self.supporting_evidence],
                "thesis_id": self.thesis_id, "watch_entry_id": self.watch_entry_id}

    @property
    def revision_id(self) -> str:
        return derive_id(THESIS_REVISION_ID_PREFIX, self.identity_payload())

    def as_dict(self) -> Dict[str, Any]:
        return {**self.identity_payload(), "revision_id": self.revision_id}


def validate_thesis_successor(prev: ThesisRevision, nxt: ThesisRevision, chain: Sequence[ThesisRevision] = ()) -> None:
    """直前の revision → 次の revision の規則（純）。終端からの復活 ・発行体 ／ Watchlist の項目の変更 ・自動の遷移は無い。"""
    require(isinstance(prev, ThesisRevision) and isinstance(nxt, ThesisRevision), "INVALID_REVISION", "revision")
    check_successor_frame(prev, nxt)
    require(prev.status in LIVE_THESIS_STATUSES, "TERMINAL_STATUS", prev.status.value)
    require(nxt.issuer_id == prev.issuer_id, "ISSUER_CHANGED", "issuer_id")
    require(nxt.watch_entry_id == prev.watch_entry_id, "WATCH_ENTRY_CHANGED", "watch_entry_id")
    if nxt.change_kind is ChangeKind.TRANSITION:
        require(nxt.status in THESIS_TRANSITIONS[prev.status], "ILLEGAL_TRANSITION",
                f"{prev.status.value}->{nxt.status.value}")
        if nxt.invalidation_basis is InvalidationBasis.CONDITIONS:              # 直前の revision の既知の条件だけ
            require(set(nxt.invalidated_condition_ids) <= set(prev.condition_ids), "UNKNOWN_CONDITION_REF",
                    "invalidated_condition_ids")
    elif nxt.change_kind is ChangeKind.REVISE:                                   # ACTIVE → ACTIVE の内容の revision だけ
        require(prev.status is ThesisStatus.ACTIVE and nxt.status is ThesisStatus.ACTIVE, "REVISE_ONLY_WHEN_ACTIVE",
                prev.status.value)
    else:                                                                        # CORRECTION は状態を変えない
        require(nxt.status is prev.status, "STATUS_CHANGE_REQUIRES_TRANSITION", nxt.change_kind.value)
    check_correction_reference(list(chain) or [prev], nxt)


def validate_thesis_chain(revisions: Sequence[ThesisRevision]) -> Tuple[ThesisRevision, ...]:
    for revision in revisions:
        require(isinstance(revision, ThesisRevision), "INVALID_REVISION", "revision")
    return tuple(ordered_chain(revisions, validate_thesis_successor))


__all__ = ["CONDITION_ID_PREFIX", "Evidence", "EvidenceKind", "HumanNoteEvidence", "InvalidationBasis",
           "InvalidationCondition", "LIVE_THESIS_STATUSES", "P8ScreenEvidence", "P8_SCREENER_STATES",
           "THESIS_AUTHORITY_CLASS", "THESIS_ID_PREFIX", "THESIS_REVISION_ID_PREFIX", "THESIS_SCHEMA_VERSION",
           "THESIS_TRANSITIONS", "ThesisRevision", "ThesisStatus", "derive_condition_id", "derive_thesis_id",
           "validate_thesis_chain", "validate_thesis_successor"]
