"""P9-A2 — Watchlist の項目の意味の model（発行体だけ ・人の authority ・不変の revision ・純）。

Watchlist の項目 ＝ 人が「この発行体を追う」と決めた記録（理由 ・次の見直しの日つき）。P8 の Screener の結果 ・Thesis ・推奨 ・売買の
指示ではない。主語は凍結 A1 の IssuerId だけ（security の watch は v1 に無い）。

- root: `watch_entry_id`（`p9wat_<24 hex>`）＝ 発行体 ・作成の reviewed_at ・著者 ・出所から導く。削除の後の再追加は別の root。
- revision: `revision_id`（`p9wrv_<24 hex>`）＝ 全欄の内容 address。`seq` ・`prev_revision_id` ・`reviewed_at` ・`author_ref`（`human:`）。
- 状態: `ACTIVE` ・`PAUSED` ・`REMOVED`（終端）。(作成) → ACTIVE ／ ACTIVE ⇄ PAUSED ／ ACTIVE ・PAUSED → REMOVED。
  `PROPOSED` ・`OVERDUE` は保存しない（L0 の提案 ・派生）。自動の遷移は無い（全て人の revision）。
- 出所: `P8_PROPOSAL`（run ・結果 ・方針 ・Universe ・日 ・提案の digest）か `MANUAL`。作成で固定し、以後の revision は同じ。
- `thesis_ids`: 人が宣言した参照の索引だけで authority ではない。link の authority は Thesis の `watch_entry_id`（cross_rules）。

記録: `docs/databank/PHASE9_A2_WATCHLIST_THESIS_SEMANTICS.md`。
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from enum import Enum
from typing import Any, Dict, Optional, Sequence, Tuple, Union

from .revision_model import (ChangeKind, SEMANTICS_RULES_VERSION, check_author, check_correction_reference, check_date,
                             check_id, check_instant, check_issuer, check_successor_frame, check_text, derive_id,
                             id_pattern, iso_date, iso_instant, ordered_chain, require)

WATCH_ENTRY_ID_PREFIX = "p9wat"
WATCH_REVISION_ID_PREFIX = "p9wrv"
WATCH_SCHEMA_VERSION = "p9_watch_entry_revision:0.1.0"
WATCH_AUTHORITY_CLASS = "HUMAN_REVIEWED_WATCH_ENTRY_NOT_A_THESIS_NOT_A_RECOMMENDATION"
_WATCH_ENTRY_RE = id_pattern(WATCH_ENTRY_ID_PREFIX)
_WATCH_REVISION_RE = id_pattern(WATCH_REVISION_ID_PREFIX)
_THESIS_ID_RE = id_pattern("p9ths")
_RUN_ID_RE = id_pattern("p8run")
_SCREEN_RESULT_ID_RE = id_pattern("p8srs")
_POLICY_ID_RE = id_pattern("p8pol")
_UNIVERSE_ID_RE = id_pattern("p8uni")
_PROPOSAL_ID_RE = id_pattern("p9prp")


class WatchStatus(str, Enum):
    ACTIVE = "ACTIVE"
    PAUSED = "PAUSED"
    REMOVED = "REMOVED"


#: 状態機械（人の TRANSITION だけ）。REMOVED は終端
WATCH_TRANSITIONS: Dict[WatchStatus, Tuple[WatchStatus, ...]] = {
    WatchStatus.ACTIVE: (WatchStatus.PAUSED, WatchStatus.REMOVED),
    WatchStatus.PAUSED: (WatchStatus.ACTIVE, WatchStatus.REMOVED),
    WatchStatus.REMOVED: (),
}


class ProvenanceKind(str, Enum):
    P8_PROPOSAL = "P8_PROPOSAL"
    MANUAL = "MANUAL"


@dataclass(frozen=True, kw_only=True)
class P8ProposalProvenance:
    """P8 の完了した run から導いた L0 の提案に、人が結び付けた出所（P8 の MATCH は特別な authority ではない）。"""

    run_id: str
    screen_result_id: str
    policy_id: str
    policy_version: int
    universe_id: str
    universe_version: int
    authority_day: date
    proposal_digest: str
    kind: ProvenanceKind = ProvenanceKind.P8_PROPOSAL

    def __post_init__(self) -> None:
        check_id(self.run_id, _RUN_ID_RE, "run_id")
        check_id(self.screen_result_id, _SCREEN_RESULT_ID_RE, "screen_result_id")
        check_id(self.policy_id, _POLICY_ID_RE, "policy_id")
        check_id(self.universe_id, _UNIVERSE_ID_RE, "universe_id")
        check_id(self.proposal_digest, _PROPOSAL_ID_RE, "proposal_digest")
        require(type(self.policy_version) is int and self.policy_version >= 1, "INVALID_VERSION", "policy_version")
        require(type(self.universe_version) is int and self.universe_version >= 1, "INVALID_VERSION",
                "universe_version")
        check_date(self.authority_day, "authority_day", required=True)
        require(self.kind is ProvenanceKind.P8_PROPOSAL, "PROVENANCE_KIND_MISMATCH", "kind")

    def as_dict(self) -> Dict[str, Any]:
        return {"authority_day": self.authority_day.isoformat(), "kind": self.kind.value,
                "policy_id": self.policy_id, "policy_version": self.policy_version,
                "proposal_digest": self.proposal_digest, "run_id": self.run_id,
                "screen_result_id": self.screen_result_id, "universe_id": self.universe_id,
                "universe_version": self.universe_version}


@dataclass(frozen=True, kw_only=True)
class ManualProvenance:
    """人が P8 の提案なしに直接作った項目。"""

    kind: ProvenanceKind = ProvenanceKind.MANUAL

    def __post_init__(self) -> None:
        require(self.kind is ProvenanceKind.MANUAL, "PROVENANCE_KIND_MISMATCH", "kind")

    def as_dict(self) -> Dict[str, Any]:
        return {"kind": self.kind.value}


WatchProvenance = Union[P8ProposalProvenance, ManualProvenance]


def derive_watch_entry_id(*, issuer_id: str, author_ref: str, reviewed_at: datetime,
                          provenance: WatchProvenance) -> str:
    """root の安定 id（作成の revision の発行体 ・著者 ・審査の瞬間 ・出所）。再追加は別の reviewed_at → 別の root。"""
    return derive_id(WATCH_ENTRY_ID_PREFIX, {"author_ref": author_ref, "issuer_id": issuer_id,
                                             "provenance": provenance.as_dict(),
                                             "reviewed_at": iso_instant(reviewed_at)})


@dataclass(frozen=True, kw_only=True)
class WatchEntryRevision:
    """Watchlist の項目の不変の 1 revision（人の authority）。上書きしない。"""

    watch_entry_id: str
    seq: int
    prev_revision_id: str
    change_kind: ChangeKind
    issuer_id: str
    status: WatchStatus
    rationale: str
    review_due_on: Optional[date]
    removal_reason: str
    thesis_ids: Tuple[str, ...]
    provenance: WatchProvenance
    author_ref: str
    reviewed_at: datetime
    corrects_revision_id: str = ""
    correction_reason: str = ""
    authority_class: str = WATCH_AUTHORITY_CLASS
    rules_version: str = SEMANTICS_RULES_VERSION
    schema_version: str = WATCH_SCHEMA_VERSION

    def __post_init__(self) -> None:
        check_id(self.watch_entry_id, _WATCH_ENTRY_RE, "watch_entry_id")
        require(type(self.seq) is int and self.seq >= 1, "INVALID_SEQ", "seq")
        require(isinstance(self.change_kind, ChangeKind), "INVALID_CHANGE_KIND", "change_kind")
        require(isinstance(self.status, WatchStatus), "INVALID_STATUS", "status")
        check_issuer(self.issuer_id)
        check_author(self.author_ref)
        check_instant(self.reviewed_at, "reviewed_at")
        check_text(self.rationale, "rationale")
        require(isinstance(self.provenance, (P8ProposalProvenance, ManualProvenance)), "INVALID_PROVENANCE",
                "provenance")
        require(isinstance(self.thesis_ids, tuple) and len(set(self.thesis_ids)) == len(self.thesis_ids)
                and list(self.thesis_ids) == sorted(self.thesis_ids), "INVALID_THESIS_IDS", "thesis_ids")
        for thesis_id in self.thesis_ids:
            check_id(thesis_id, _THESIS_ID_RE, "thesis_ids")
        # 見直しの日: ACTIVE は必須（caller が渡す）・PAUSED は任意（見直しの停止）・REMOVED は無い
        check_date(self.review_due_on, "review_due_on", required=self.status is WatchStatus.ACTIVE)
        if self.status is WatchStatus.REMOVED:
            require(self.review_due_on is None, "REVIEW_DUE_ON_REMOVED", "review_due_on")
            check_text(self.removal_reason, "removal_reason")
        else:
            require(self.removal_reason == "", "REMOVAL_REASON_ONLY_FOR_REMOVED", "removal_reason")
        if self.seq == 1:
            require(self.change_kind is ChangeKind.CREATE and self.prev_revision_id == ""
                    and self.status is WatchStatus.ACTIVE, "INVALID_INITIAL_REVISION", "seq")
            require(self.watch_entry_id == derive_watch_entry_id(issuer_id=self.issuer_id, author_ref=self.author_ref,
                                                                 reviewed_at=self.reviewed_at,
                                                                 provenance=self.provenance),
                    "WATCH_ENTRY_ID_MISMATCH", "watch_entry_id")
        else:
            check_id(self.prev_revision_id, _WATCH_REVISION_RE, "prev_revision_id")
        if self.change_kind is ChangeKind.CORRECTION:
            check_id(self.corrects_revision_id, _WATCH_REVISION_RE, "corrects_revision_id")
            check_text(self.correction_reason, "correction_reason")
        else:
            require(self.corrects_revision_id == "" and self.correction_reason == "", "CORRECTION_FIELDS_UNEXPECTED",
                    "corrects_revision_id")
        require(self.authority_class == WATCH_AUTHORITY_CLASS, "AUTHORITY_CLASS_MISMATCH", "authority_class")
        require(self.rules_version == SEMANTICS_RULES_VERSION, "RULES_VERSION_MISMATCH", "rules_version")
        require(self.schema_version == WATCH_SCHEMA_VERSION, "SCHEMA_MISMATCH", "schema_version")

    @property
    def root_id(self) -> str:
        return self.watch_entry_id

    def identity_payload(self) -> Dict[str, Any]:
        return {"authority_class": self.authority_class, "author_ref": self.author_ref,
                "change_kind": self.change_kind.value, "correction_reason": self.correction_reason,
                "corrects_revision_id": self.corrects_revision_id, "issuer_id": self.issuer_id,
                "prev_revision_id": self.prev_revision_id, "provenance": self.provenance.as_dict(),
                "rationale": self.rationale, "removal_reason": self.removal_reason,
                "review_due_on": iso_date(self.review_due_on), "reviewed_at": iso_instant(self.reviewed_at),
                "rules_version": self.rules_version, "schema_version": self.schema_version, "seq": self.seq,
                "status": self.status.value, "thesis_ids": list(self.thesis_ids),
                "watch_entry_id": self.watch_entry_id}

    @property
    def revision_id(self) -> str:
        return derive_id(WATCH_REVISION_ID_PREFIX, self.identity_payload())

    def as_dict(self) -> Dict[str, Any]:
        return {**self.identity_payload(), "revision_id": self.revision_id}


def validate_watch_successor(prev: WatchEntryRevision, nxt: WatchEntryRevision,
                             chain: Sequence[WatchEntryRevision] = ()) -> None:
    """直前の revision → 次の revision の規則（純）。自動の遷移 ・終端からの復活 ・出所 ／ 発行体の変更は無い。"""
    require(isinstance(prev, WatchEntryRevision) and isinstance(nxt, WatchEntryRevision), "INVALID_REVISION",
            "revision")
    check_successor_frame(prev, nxt)
    require(prev.status is not WatchStatus.REMOVED, "TERMINAL_STATUS", prev.status.value)   # 復活しない ・訂正もしない
    require(nxt.issuer_id == prev.issuer_id, "ISSUER_CHANGED", "issuer_id")
    require(nxt.provenance == prev.provenance, "PROVENANCE_CHANGED", "provenance")
    if nxt.change_kind is ChangeKind.TRANSITION:
        require(nxt.status in WATCH_TRANSITIONS[prev.status], "ILLEGAL_TRANSITION",
                f"{prev.status.value}->{nxt.status.value}")
    else:                                                                        # REVISE ・CORRECTION は状態を変えない
        require(nxt.status is prev.status, "STATUS_CHANGE_REQUIRES_TRANSITION", nxt.change_kind.value)
    check_correction_reference(list(chain) or [prev], nxt)


def validate_watch_chain(revisions: Sequence[WatchEntryRevision]) -> Tuple[WatchEntryRevision, ...]:
    """1 つの root の revision の集まり → seq 順の検査済みの鎖（file の順に依らない）。"""
    for revision in revisions:
        require(isinstance(revision, WatchEntryRevision), "INVALID_REVISION", "revision")
    return tuple(ordered_chain(revisions, validate_watch_successor))


__all__ = ["ManualProvenance", "P8ProposalProvenance", "ProvenanceKind", "WATCH_AUTHORITY_CLASS",
           "WATCH_ENTRY_ID_PREFIX", "WATCH_REVISION_ID_PREFIX", "WATCH_SCHEMA_VERSION", "WATCH_TRANSITIONS",
           "WatchEntryRevision", "WatchProvenance", "WatchStatus", "derive_watch_entry_id", "validate_watch_chain",
           "validate_watch_successor"]
