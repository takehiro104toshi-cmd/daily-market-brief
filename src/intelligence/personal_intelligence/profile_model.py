"""P10-A2 — Personal Profile の意味の model（人の authority ・質的 ・不変の revision ・純）。

Personal Profile ＝ 人が自分の調べ方の文脈を質的に書いた記録。点数 ・格付け ・適合性の区分 ・目標の利回り ・配分 ・建玉の大きさ ・
保有 ・売買の指示ではなく、その型の欄も無い（欄は `PROFILE_CONTENT_FIELDS` だけ）。

- root: `profile_id`（`p10prf_<24 hex>`）＝ 作成の著者 ・reviewed_at から導く。退役の後の新しい profile は別の root。
- revision: `revision_id`（`p10prv_<24 hex>`）＝ 全欄の内容 address。
- 状態: `ACTIVE` ・`RETIRED`（終端）。CREATE → ACTIVE ／ ACTIVE → ACTIVE（REVISE ・CORRECTION）／ ACTIVE → RETIRED（TRANSITION）。
  RETIRED → ACTIVE は無い。時点ごとに ACTIVE な profile は高々 1 つ（`cross_rules`）。
- REVISE ＝ 人の考えが変わった。CORRECTION ＝ 以前の revision の誤りを正す（`corrects_revision_id` ・理由つき）。どちらも内容の欄を
  変えてよく、過去の revision は書き換えない（時点 T < 訂正の reviewed_at の状態は記録のまま）。TRANSITION は状態だけを変える。
- 文（`*_note`）は解釈しない。数の authority は `review_lookahead_days`（表示 ／ 見直しの窓の日数だけ ・範囲つき）だけ。
- `excluded_issuer_ids`: 人が持つ除外。発行体の id の構文だけ（P9 に在るとは主張しない）。文字の順 ・重複なしの正準の tuple。

記録: `docs/databank/PHASE10_A2_PROFILE_ATTENTION_SEMANTICS.md`。
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Any, Dict, Iterable, Sequence, Tuple

from .revision_model import (ChangeKind, P9_ISSUER_ID_PREFIX, PERSONAL_RULES_VERSION, check_author, check_id,
                             check_instant, check_note, check_successor_frame, derive_id, id_pattern, iso_instant,
                             ordered_chain, require)

PROFILE_ID_PREFIX = "p10prf"
PROFILE_REVISION_ID_PREFIX = "p10prv"
PROFILE_SCHEMA_VERSION = "p10_personal_profile_revision:0.1.0"
PROFILE_AUTHORITY_CLASS = "HUMAN_REVIEWED_QUALITATIVE_PROFILE_NOT_A_SCORE_NOT_A_RECOMMENDATION"
#: 見直しの窓（日）。表示 ／ 見直しの範囲だけ（点数 ・危険の尺度ではない）。0 ＝ 期日 ／ 期日を過ぎたものだけ
REVIEW_LOOKAHEAD_MIN_DAYS = 0
REVIEW_LOOKAHEAD_MAX_DAYS = 90
MAX_EXCLUDED_ISSUERS = 200
#: 内容の欄（完全な一覧。型の authority はこれだけ）
PROFILE_CONTENT_FIELDS = ("horizon_note", "liquidity_note", "risk_context_note", "review_lookahead_days",
                          "excluded_issuer_ids", "exclusion_reason_note")
_PROFILE_RE = id_pattern(PROFILE_ID_PREFIX)
_PROFILE_REVISION_RE = id_pattern(PROFILE_REVISION_ID_PREFIX)
_ISSUER_RE = id_pattern(P9_ISSUER_ID_PREFIX)


class ProfileStatus(str, Enum):
    ACTIVE = "ACTIVE"
    RETIRED = "RETIRED"


#: 状態機械（人の TRANSITION だけ）。RETIRED は終端
PROFILE_TRANSITIONS: Dict[ProfileStatus, Tuple[ProfileStatus, ...]] = {
    ProfileStatus.ACTIVE: (ProfileStatus.RETIRED,),
    ProfileStatus.RETIRED: (),
}


def canonical_excluded_issuer_ids(values: Iterable[Any]) -> Tuple[str, ...]:
    """除外の正準化（明示）: 構文の検査 → 重複は拒否 → 文字の順の tuple。"""
    items = list(values)
    for value in items:
        check_id(value, _ISSUER_RE, "excluded_issuer_ids")
    require(len(set(items)) == len(items), "DUPLICATE_EXCLUDED_ISSUER", "excluded_issuer_ids")
    return tuple(sorted(items))


def derive_profile_id(*, author_ref: str, reviewed_at: datetime) -> str:
    """root の安定 id（作成の revision の著者 ・審査の瞬間）。退役の後の新しい profile は別の reviewed_at → 別の root。"""
    return derive_id(PROFILE_ID_PREFIX, {"author_ref": author_ref, "reviewed_at": iso_instant(reviewed_at),
                                         "schema_version": PROFILE_SCHEMA_VERSION})


@dataclass(frozen=True, kw_only=True)
class PersonalProfileRevision:
    """Personal Profile の不変の 1 revision（人の authority）。未知の欄は型が受けない（kw_only）。"""

    profile_id: str
    seq: int
    prev_revision_id: str
    change_kind: ChangeKind
    status: ProfileStatus
    horizon_note: str
    liquidity_note: str
    risk_context_note: str
    review_lookahead_days: int
    excluded_issuer_ids: Tuple[str, ...]
    exclusion_reason_note: str
    author_ref: str
    reviewed_at: datetime
    retirement_reason: str = ""
    corrects_revision_id: str = ""
    correction_reason: str = ""
    authority_class: str = PROFILE_AUTHORITY_CLASS
    rules_version: str = PERSONAL_RULES_VERSION
    schema_version: str = PROFILE_SCHEMA_VERSION

    def __post_init__(self) -> None:
        check_id(self.profile_id, _PROFILE_RE, "profile_id")
        require(type(self.seq) is int and self.seq >= 1, "INVALID_SEQ", "seq")
        require(isinstance(self.change_kind, ChangeKind), "INVALID_CHANGE_KIND", "change_kind")
        require(isinstance(self.status, ProfileStatus), "INVALID_STATUS", "status")
        check_author(self.author_ref)
        check_instant(self.reviewed_at, "reviewed_at")
        check_note(self.horizon_note, "horizon_note", required=False)
        check_note(self.liquidity_note, "liquidity_note", required=False)
        check_note(self.risk_context_note, "risk_context_note", required=False)
        require(type(self.review_lookahead_days) is int
                and REVIEW_LOOKAHEAD_MIN_DAYS <= self.review_lookahead_days <= REVIEW_LOOKAHEAD_MAX_DAYS,
                "INVALID_REVIEW_LOOKAHEAD_DAYS", "review_lookahead_days")
        require(isinstance(self.excluded_issuer_ids, tuple) and len(self.excluded_issuer_ids) <= MAX_EXCLUDED_ISSUERS,
                "INVALID_EXCLUDED_ISSUER_IDS", "excluded_issuer_ids")
        require(canonical_excluded_issuer_ids(self.excluded_issuer_ids) == self.excluded_issuer_ids,
                "EXCLUDED_ISSUER_IDS_NOT_CANONICAL", "excluded_issuer_ids")
        # 除外の理由: 除外があれば必須 ・無ければ空（宙に浮いた理由は無い）
        check_note(self.exclusion_reason_note, "exclusion_reason_note", required=bool(self.excluded_issuer_ids))
        require(bool(self.excluded_issuer_ids) or self.exclusion_reason_note == "", "EXCLUSION_REASON_WITHOUT_EXCLUSION",
                "exclusion_reason_note")
        if self.status is ProfileStatus.RETIRED:
            check_note(self.retirement_reason, "retirement_reason", required=True)
        else:
            require(self.retirement_reason == "", "RETIREMENT_REASON_ONLY_FOR_RETIRED", "retirement_reason")
        if self.seq == 1:
            require(self.change_kind is ChangeKind.CREATE and self.prev_revision_id == ""
                    and self.status is ProfileStatus.ACTIVE, "INVALID_INITIAL_REVISION", "seq")
            require(self.profile_id == derive_profile_id(author_ref=self.author_ref, reviewed_at=self.reviewed_at),
                    "PROFILE_ID_MISMATCH", "profile_id")
        else:
            check_id(self.prev_revision_id, _PROFILE_REVISION_RE, "prev_revision_id")
        if self.change_kind is ChangeKind.CORRECTION:
            check_id(self.corrects_revision_id, _PROFILE_REVISION_RE, "corrects_revision_id")
            check_note(self.correction_reason, "correction_reason", required=True)
        else:
            require(self.corrects_revision_id == "" and self.correction_reason == "", "CORRECTION_FIELDS_UNEXPECTED",
                    "corrects_revision_id")
        require(self.authority_class == PROFILE_AUTHORITY_CLASS, "AUTHORITY_CLASS_MISMATCH", "authority_class")
        require(self.rules_version == PERSONAL_RULES_VERSION, "RULES_VERSION_MISMATCH", "rules_version")
        require(self.schema_version == PROFILE_SCHEMA_VERSION, "SCHEMA_MISMATCH", "schema_version")

    @property
    def root_id(self) -> str:
        return self.profile_id

    def content(self) -> Tuple[Any, ...]:
        """内容の欄の値（`PROFILE_CONTENT_FIELDS` の順）。差が要る消費者はこれを明示に比べる。"""
        return (self.horizon_note, self.liquidity_note, self.risk_context_note, self.review_lookahead_days,
                self.excluded_issuer_ids, self.exclusion_reason_note)

    def identity_payload(self) -> Dict[str, Any]:
        return {"authority_class": self.authority_class, "author_ref": self.author_ref,
                "change_kind": self.change_kind.value, "correction_reason": self.correction_reason,
                "corrects_revision_id": self.corrects_revision_id,
                "excluded_issuer_ids": list(self.excluded_issuer_ids),
                "exclusion_reason_note": self.exclusion_reason_note, "horizon_note": self.horizon_note,
                "liquidity_note": self.liquidity_note, "prev_revision_id": self.prev_revision_id,
                "profile_id": self.profile_id, "retirement_reason": self.retirement_reason,
                "review_lookahead_days": self.review_lookahead_days, "reviewed_at": iso_instant(self.reviewed_at),
                "risk_context_note": self.risk_context_note, "rules_version": self.rules_version,
                "schema_version": self.schema_version, "seq": self.seq, "status": self.status.value}

    @property
    def revision_id(self) -> str:
        return derive_id(PROFILE_REVISION_ID_PREFIX, self.identity_payload())

    def as_dict(self) -> Dict[str, Any]:
        return {**self.identity_payload(), "revision_id": self.revision_id}


def validate_profile_successor(prev: PersonalProfileRevision, nxt: PersonalProfileRevision,
                               chain: Sequence[PersonalProfileRevision] = ()) -> None:
    """直前の revision → 次の revision の規則（純）。終端からの復活 ・訂正は無い ・TRANSITION は内容を変えない。"""
    require(isinstance(prev, PersonalProfileRevision) and isinstance(nxt, PersonalProfileRevision),
            "INVALID_REVISION", "revision")
    check_successor_frame(prev, nxt)
    require(prev.status is not ProfileStatus.RETIRED, "TERMINAL_STATUS", prev.status.value)
    if nxt.change_kind is ChangeKind.TRANSITION:
        require(nxt.status in PROFILE_TRANSITIONS[prev.status], "ILLEGAL_TRANSITION",
                f"{prev.status.value}->{nxt.status.value}")
        require(nxt.content() == prev.content(), "TRANSITION_CHANGES_CONTENT", "content")
    else:                                                                        # REVISE ・CORRECTION は状態を変えない
        require(nxt.status is prev.status, "STATUS_CHANGE_REQUIRES_TRANSITION", nxt.change_kind.value)
    if nxt.change_kind is ChangeKind.CORRECTION:
        require(nxt.corrects_revision_id in {r.revision_id for r in (list(chain) or [prev])},
                "CORRECTION_TARGET_UNKNOWN", "corrects_revision_id")


def validate_profile_chain(revisions: Sequence[PersonalProfileRevision]) -> Tuple[PersonalProfileRevision, ...]:
    """1 つの root の revision の集まり → seq 順の検査済みの鎖（入力の順に依らない）。"""
    for revision in revisions:
        require(isinstance(revision, PersonalProfileRevision), "INVALID_REVISION", "revision")
    return tuple(ordered_chain(revisions, validate_profile_successor))


__all__ = ["MAX_EXCLUDED_ISSUERS", "PROFILE_AUTHORITY_CLASS", "PROFILE_CONTENT_FIELDS", "PROFILE_ID_PREFIX",
           "PROFILE_REVISION_ID_PREFIX", "PROFILE_SCHEMA_VERSION", "PROFILE_TRANSITIONS", "PersonalProfileRevision",
           "ProfileStatus", "REVIEW_LOOKAHEAD_MAX_DAYS", "REVIEW_LOOKAHEAD_MIN_DAYS", "canonical_excluded_issuer_ids",
           "derive_profile_id", "validate_profile_chain", "validate_profile_successor"]
