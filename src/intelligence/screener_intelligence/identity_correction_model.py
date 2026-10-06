"""P8-A1R — identity の訂正（追記専用）と、知識を固定した authority の像の純 model（A1 を変えない拡張）。

- 訂正は 2 つの原始の record だけ: `INVALIDATE_RECORD`（対象を以後の authority の像から外す）と `SUPERSEDE_RECORD`（対象を
  明示の置き換えの claim で替える）。対象は A1 の record id を明示で指す。元の record は消さない・書き換えない。
- 置き換えの claim は A1 の record の型そのもの（A1 の検査 ・直列化を再利用）。人の審査（`HUMAN_REVIEWED`）の出所を持ち、
  知った時刻は訂正の受理の時刻と同じ。登録の置き換えは同じ id を保つ（id を変える統合 ・分割は訂正で表さない）。
- 訂正の鎖は決定論: 対象の欠落 ・未来の対象 ・自己 ・循環 ・競合（同じ対象への 2 つ目の訂正）・種類の違う置き換えを拒む。
  append の順で「最新が勝つ」ことは無い。訂正の訂正は置き換えの record を対象にする。
- authority の像（`PinnedAuthorityView`）は、知識の cutoff（authority_as_of）までの A1 の record と訂正から作り直し、A1 の
  不変条件で検査し直す。像は journal ではないので、知識は固定され（`known_by` は自身）、有効時間の評価は A1 の resolver に任せる。
- authority の版は、像を作った record id の列だけからの内容 id（時計 ・乱数 ・path に依らない）。

契約: `docs/databank/PHASE8_IDENTITY_REMEDIATION_CONTRACT.md`。
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Any, Dict, Iterable, List, Mapping, Optional, Tuple

from .identity_model import (AUTHORITY_RULES_VERSION, CREDENTIAL_MARKERS, SCHEMA_VERSION, IdentityHistory,
                             IdentityHistoryError, IdentityModelError, RecordKind, SourceClass, canonical_json,
                             is_identity_record, parse_identity_record)
from ..core.ids import content_id
from ..core.time import from_iso, to_utc_iso

CORRECTION_SCHEMA_VERSION = "p8_identity_correction:0.1.0"
CORRECTION_RECORD_KIND = "IDENTITY_CORRECTION"
CORRECTION_ID_PREFIX = "p8idc"
AUTHORITY_VERSION_PREFIX = "p8idv"
VIEW_RULES_VERSION = "p8_identity_authority_view:0.1.0"
#: 訂正の authority の種類（契約 §15。人の審査だけ）
AUTHORITATIVE_CORRECTION_RECORD = "AUTHORITATIVE_CORRECTION_RECORD"
MAX_TARGETS = 16
MAX_EVIDENCE = 8
_IDENTITY_RECORD_ID_RE = re.compile(r"^p8idr_[0-9a-f]{24}$")
_VERSION_RE = re.compile(rf"^{AUTHORITY_VERSION_PREFIX}_[0-9a-f]{{24}}$")
#: 証拠の参照（A1 と同じ形: `/`・`\\`・空白なし・160 文字まで＝path ・URL ・本文を持てない）
_EVIDENCE_REF_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:#-]{0,159}$")
_DIGEST_RE = re.compile(r"^[0-9a-f]{64}$")


class CorrectionModelError(ValueError):
    """訂正の record の構造 ・語彙 ・値の違反（fail closed）。detail は field 名だけ。"""

    def __init__(self, code: str, detail: str = "") -> None:
        super().__init__(f"{code}: {detail}" if detail else code)
        self.code = code
        self.detail = detail


class CorrectionHistoryError(ValueError):
    """訂正の鎖の違反（欠落 ・未来 ・自己 ・循環 ・競合 ・種類 ・A1 の不変条件の破れ）。"""

    def __init__(self, code: str, detail: str = "") -> None:
        super().__init__(f"{code}: {detail}" if detail else code)
        self.code = code
        self.detail = detail


def _require(condition: bool, code: str, detail: str = "") -> None:
    if not condition:
        raise CorrectionModelError(code, detail)


# ---------------------------------------------------------------- 語彙（閉じた集合）


class CorrectionAction(str, Enum):
    INVALIDATE_RECORD = "INVALIDATE_RECORD"
    SUPERSEDE_RECORD = "SUPERSEDE_RECORD"


class CorrectionReason(str, Enum):
    WRONG_ISSUER_MAPPING = "WRONG_ISSUER_MAPPING"
    WRONG_ISSUE_CLASS = "WRONG_ISSUE_CLASS"
    WRONG_IDENTIFIER_VALUE = "WRONG_IDENTIFIER_VALUE"
    WRONG_EFFECTIVE_INTERVAL = "WRONG_EFFECTIVE_INTERVAL"
    WRONG_CONTINUITY = "WRONG_CONTINUITY"
    DUPLICATE_IDENTITY = "DUPLICATE_IDENTITY"
    WRONG_DISPLAY_NAME = "WRONG_DISPLAY_NAME"
    WRONG_COVERAGE = "WRONG_COVERAGE"
    NOT_SUPPORTED_BY_EVIDENCE = "NOT_SUPPORTED_BY_EVIDENCE"


class ReviewerClass(str, Enum):
    """審査した者の種類（個人の identity は持たない）。authority を作れるのは HUMAN だけ。"""

    HUMAN = "HUMAN"
    MACHINE = "MACHINE"


#: 訂正の authority を作れる審査者（契約 §15。machine ・adapter ・LLM は提案しかできない）
AUTHORIZED_REVIEWERS = frozenset({ReviewerClass.HUMAN})
#: 置き換えの claim が持つべき出所（人の審査の決定）
REPLACEMENT_SOURCE_CLASS = SourceClass.HUMAN_REVIEWED
_REGISTRATION_KINDS = (RecordKind.ISSUER_REGISTRATION, RecordKind.SECURITY_REGISTRATION)


# ---------------------------------------------------------------- 値の検査


def _enum(value: Any, enum_type, field_name: str):
    _require(isinstance(value, enum_type), "INVALID_VOCABULARY", field_name)
    return value


def _parse_enum(value: Any, enum_type, field_name: str):
    try:
        return enum_type(value)
    except (ValueError, TypeError):
        raise CorrectionModelError("INVALID_VOCABULARY", field_name) from None


def _aware(value: Any, field_name: str) -> datetime:
    _require(isinstance(value, datetime), "INVALID_DATETIME", field_name)
    _require(value.tzinfo is not None and value.tzinfo.utcoffset(value) is not None, "NAIVE_DATETIME", field_name)
    return value


def _parse_datetime(value: Any, field_name: str) -> datetime:
    _require(isinstance(value, str), "INVALID_DATETIME", field_name)
    try:
        return from_iso(value)
    except ValueError:
        raise CorrectionModelError("INVALID_DATETIME", field_name) from None


def _reject_unknown(data: Any, allowed: Iterable[str], name: str) -> None:
    _require(isinstance(data, Mapping), "INVALID_RECORD", name)
    _require(set(data) <= set(allowed), "UNKNOWN_FIELD", name)
    _require(set(allowed) <= set(data), "MISSING_FIELD", name)


def _no_credential_marker(value: str, field_name: str) -> None:
    lowered = value.lower()
    _require(not any(marker in lowered for marker in CREDENTIAL_MARKERS), "CREDENTIAL_LIKE_TEXT", field_name)


def is_identity_record_id(value: Any) -> bool:
    return isinstance(value, str) and bool(_IDENTITY_RECORD_ID_RE.match(value))


def is_authority_version(value: Any) -> bool:
    return isinstance(value, str) and bool(_VERSION_RE.match(value))


# ---------------------------------------------------------------- 審査の出所


@dataclass(frozen=True)
class ReviewEvidence:
    """審査に使った証拠の有界の参照（出所の class ・参照 ・任意の sha256）。本文 ・payload ・path は持たない。"""

    source_class: SourceClass
    source_ref: str
    digest: str = ""

    def __post_init__(self) -> None:
        _enum(self.source_class, SourceClass, "source_class")
        _require(isinstance(self.source_ref, str) and bool(_EVIDENCE_REF_RE.match(self.source_ref)),
                 "INVALID_EVIDENCE_REF", "source_ref")
        _no_credential_marker(self.source_ref, "source_ref")
        _require(isinstance(self.digest, str) and (self.digest == "" or bool(_DIGEST_RE.match(self.digest))),
                 "INVALID_DIGEST", "digest")

    def as_dict(self) -> Dict[str, Any]:
        return {"digest": self.digest, "source_class": self.source_class.value, "source_ref": self.source_ref}

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "ReviewEvidence":
        _reject_unknown(data, ("digest", "source_class", "source_ref"), "evidence")
        return cls(source_class=_parse_enum(data["source_class"], SourceClass, "source_class"),
                   source_ref=data["source_ref"], digest=data["digest"])


@dataclass(frozen=True)
class CorrectionReview:
    """人の審査（審査者の種類 ・審査の時刻 ・証拠）。個人の identity ・自由記述の文は持たない。"""

    reviewer_class: ReviewerClass
    reviewed_at: datetime
    evidence: Tuple[ReviewEvidence, ...]

    def __post_init__(self) -> None:
        _enum(self.reviewer_class, ReviewerClass, "reviewer_class")
        _require(self.reviewer_class in AUTHORIZED_REVIEWERS, "REVIEWER_NOT_AUTHORIZED", "reviewer_class")
        _aware(self.reviewed_at, "reviewed_at")
        _require(isinstance(self.evidence, tuple) and 0 < len(self.evidence) <= MAX_EVIDENCE, "INVALID_EVIDENCE",
                 "evidence")
        _require(all(isinstance(item, ReviewEvidence) for item in self.evidence), "INVALID_EVIDENCE", "evidence")
        _require(len({item.source_ref for item in self.evidence}) == len(self.evidence),
                 "DUPLICATE_EVIDENCE", "evidence")

    def as_dict(self) -> Dict[str, Any]:
        return {"evidence": [item.as_dict() for item in self.evidence], "reviewed_at": to_utc_iso(self.reviewed_at),
                "reviewer_class": self.reviewer_class.value}

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "CorrectionReview":
        _reject_unknown(data, ("evidence", "reviewed_at", "reviewer_class"), "review")
        _require(isinstance(data["evidence"], list), "INVALID_EVIDENCE", "evidence")
        return cls(reviewer_class=_parse_enum(data["reviewer_class"], ReviewerClass, "reviewer_class"),
                   reviewed_at=_parse_datetime(data["reviewed_at"], "reviewed_at"),
                   evidence=tuple(ReviewEvidence.from_dict(item) for item in data["evidence"]))


# ---------------------------------------------------------------- 訂正の record


@dataclass(frozen=True, kw_only=True)
class IdentityCorrection:
    """追記専用の訂正（不変 ・内容 address）。`accepted_at` は authority がこの訂正を受け入れた時刻（知識の時刻）。"""

    action: CorrectionAction
    reason: CorrectionReason
    targets: Tuple[str, ...]
    replacements: Tuple[Any, ...] = ()
    review: CorrectionReview
    accepted_at: datetime

    AUTHORITY_CLASS = AUTHORITATIVE_CORRECTION_RECORD

    def __post_init__(self) -> None:
        _enum(self.action, CorrectionAction, "action")
        _enum(self.reason, CorrectionReason, "reason")
        _require(isinstance(self.targets, tuple) and 0 < len(self.targets) <= MAX_TARGETS, "INVALID_TARGETS",
                 "targets")
        _require(all(is_identity_record_id(target) for target in self.targets), "INVALID_TARGETS", "targets")
        _require(len(set(self.targets)) == len(self.targets), "DUPLICATE_TARGET", "targets")
        _require(isinstance(self.review, CorrectionReview), "INVALID_REVIEW", "review")
        _aware(self.accepted_at, "accepted_at")
        _require(self.accepted_at >= self.review.reviewed_at, "ACCEPTED_BEFORE_REVIEW", "accepted_at")
        _require(isinstance(self.replacements, tuple), "INVALID_REPLACEMENTS", "replacements")
        if self.action is CorrectionAction.INVALIDATE_RECORD:
            _require(self.replacements == (), "INVALID_REPLACEMENTS", "invalidation has no replacement")
            return
        _require(len(self.replacements) == len(self.targets), "INVALID_REPLACEMENTS", "one replacement per target")
        for target, replacement in zip(self.targets, self.replacements):
            _require(is_identity_record(replacement), "INVALID_REPLACEMENTS", "replacement type")
            _require(replacement.provenance.source_class is REPLACEMENT_SOURCE_CLASS,
                     "REPLACEMENT_NOT_HUMAN_REVIEWED", "replacement provenance")
            _require(replacement.known_at == self.accepted_at, "REPLACEMENT_KNOWN_AT_MISMATCH",
                     "replacement known_at")
            _require(replacement.record_id != target, "SELF_TARGET", "replacement equals its target")
        _require(len({r.record_id for r in self.replacements}) == len(self.replacements), "DUPLICATE_REPLACEMENT",
                 "replacements")

    @property
    def known_at(self) -> datetime:
        return self.accepted_at

    def links(self) -> Tuple[Tuple[str, str], ...]:
        """(対象, 置き換え) の組（無効化は置き換えが空）。"""
        replaced = [r.record_id for r in self.replacements] or [""] * len(self.targets)
        return tuple(zip(self.targets, replaced))

    def identity_payload(self) -> Dict[str, Any]:
        payload = {"accepted_at": to_utc_iso(self.accepted_at), "action": self.action.value,
                   "reason": self.reason.value, "replacements": [r.as_dict() for r in self.replacements],
                   "review": self.review.as_dict(), "targets": list(self.targets)}
        return {"payload": payload, "record_kind": CORRECTION_RECORD_KIND,
                "schema_version": CORRECTION_SCHEMA_VERSION}

    @property
    def record_id(self) -> str:
        return content_id(CORRECTION_ID_PREFIX, canonical_json(self.identity_payload()))

    def as_dict(self) -> Dict[str, Any]:
        return {**self.identity_payload(), "record_id": self.record_id}

    def canonical_line(self) -> str:
        return canonical_json(self.as_dict()) + "\n"


def parse_correction(data: Mapping[str, Any]) -> IdentityCorrection:
    """直列化された 1 訂正を検査して復元する（未知の field ・版 ・id の不一致 ・不正な置き換えを拒む）。"""
    _reject_unknown(data, ("payload", "record_id", "record_kind", "schema_version"), "correction")
    _require(data["schema_version"] == CORRECTION_SCHEMA_VERSION, "UNSUPPORTED_SCHEMA_VERSION", "schema_version")
    _require(data["record_kind"] == CORRECTION_RECORD_KIND, "INVALID_VOCABULARY", "record_kind")
    payload = data["payload"]
    _reject_unknown(payload, ("accepted_at", "action", "reason", "replacements", "review", "targets"), "payload")
    _require(isinstance(payload["targets"], list) and isinstance(payload["replacements"], list), "INVALID_RECORD",
             "payload")
    replacements = []
    for item in payload["replacements"]:
        try:
            replacements.append(parse_identity_record(item))
        except IdentityModelError as exc:
            raise CorrectionModelError("INVALID_REPLACEMENT", exc.code) from None
    correction = IdentityCorrection(action=_parse_enum(payload["action"], CorrectionAction, "action"),
                                    reason=_parse_enum(payload["reason"], CorrectionReason, "reason"),
                                    targets=tuple(payload["targets"]), replacements=tuple(replacements),
                                    review=CorrectionReview.from_dict(payload["review"]),
                                    accepted_at=_parse_datetime(payload["accepted_at"], "accepted_at"))
    _require(data["record_id"] == correction.record_id, "ID_MISMATCH", "record_id")
    return correction


def parse_correction_line(line: str) -> IdentityCorrection:
    """1 行を復元し、それが訂正の正準の直列化と byte 一致することを確かめる。"""
    try:
        data = json.loads(line)
    except ValueError:
        raise CorrectionModelError("MALFORMED_JSON", "line") from None
    _require(isinstance(data, dict), "NOT_AN_OBJECT", "line")
    correction = parse_correction(data)
    _require(correction.canonical_line() == line, "NON_CANONICAL_LINE", "line")
    return correction


# ---------------------------------------------------------------- authority の像


class PinnedAuthorityView(IdentityHistory):
    """知識を固定した authority の像（journal ではない）。

    A1 の record の不変条件（参照 ・重なり ・分岐 ・継続の権限 ・登録の衝突）はそのまま検査する。journal の append の順の
    規則（`known_at` の非減少）だけを持たない。知識は像を作った時点で固定されているので `known_by` は自身を返し、
    A1 の resolver は有効時間だけを評価する。
    """

    def check(self, record: Any) -> None:
        if not is_identity_record(record):
            raise IdentityHistoryError("INVALID_TYPE", "not an identity record")
        checkers = {RecordKind.ISSUER_REGISTRATION: self._check_issuer_registration,
                    RecordKind.SECURITY_REGISTRATION: self._check_security_registration,
                    RecordKind.IDENTIFIER_ASSIGNMENT: self._check_identifier_assignment,
                    RecordKind.IDENTIFIER_RETIREMENT: self._check_identifier_retirement,
                    RecordKind.DISPLAY_NAME: self._check_display_name,
                    RecordKind.LISTING_START: self._check_listing_start,
                    RecordKind.LISTING_END: self._check_listing_end,
                    RecordKind.COVERAGE: self._check_coverage}
        checkers[record.KIND](record)

    def known_by(self, cutoff: datetime) -> "PinnedAuthorityView":
        return self


def _tier(record: Any) -> int:
    """像の中の順（Issuer の登録 → Security の登録 → その他）。同じ tier の中は journal の位置の順。"""
    return {RecordKind.ISSUER_REGISTRATION: 0, RecordKind.SECURITY_REGISTRATION: 1}.get(record.KIND, 2)


@dataclass(frozen=True)
class PinnedAuthority:
    """authority_as_of で固定した authority（像 ・版 ・像を作った record id）。派生で、永続しない。"""

    authority_as_of: datetime
    view: PinnedAuthorityView
    version: str
    identity_record_ids: Tuple[str, ...]
    correction_record_ids: Tuple[str, ...]


def authority_version(identity_record_ids: Iterable[str], correction_record_ids: Iterable[str]) -> str:
    """像を作った record id の列（順つき）と規則の版だけから決まる内容 id。"""
    body = {"correction_record_ids": list(correction_record_ids), "correction_schema": CORRECTION_SCHEMA_VERSION,
            "identity_record_ids": list(identity_record_ids), "identity_rules": AUTHORITY_RULES_VERSION,
            "identity_schema": SCHEMA_VERSION, "view_rules": VIEW_RULES_VERSION}
    return content_id(AUTHORITY_VERSION_PREFIX, canonical_json(body))


class CorrectionHistory:
    """A1 の authority（検証済みの `IdentityHistory`）と、それへの訂正の列（append 順）。

    - 訂正の `accepted_at` は append 順に非減少。
    - 対象は訂正の受理までに知られた A1 の record か、先の訂正の置き換え。1 つの対象を訂正できるのは 1 回だけ。
    - 受理の時点の像が A1 の不変条件を満たさない訂正は拒む。
    """

    def __init__(self, identity: IdentityHistory, corrections: Iterable[IdentityCorrection] = ()) -> None:
        if type(identity) is not IdentityHistory:
            raise CorrectionHistoryError("INVALID_HISTORY", "identity must be the A1 authority history")
        self.identity = identity
        self._corrections: List[IdentityCorrection] = []
        self._ids: Dict[str, IdentityCorrection] = {}
        self._corrected: Dict[str, str] = {}
        self._replacements: Dict[str, Any] = {}
        self._last_accepted_at: Optional[datetime] = None
        for correction in corrections:
            self.add(correction)

    @property
    def records(self) -> Tuple[IdentityCorrection, ...]:
        return tuple(self._corrections)

    def contains(self, record_id: str) -> bool:
        return record_id in self._ids

    def corrected_by(self, record_id: str) -> str:
        """その record を対象にした訂正の id（無ければ空）。"""
        return self._corrected.get(record_id, "")

    def replacement(self, record_id: str) -> Optional[Any]:
        return self._replacements.get(record_id)

    def add(self, correction: IdentityCorrection) -> bool:
        if isinstance(correction, IdentityCorrection) and correction.record_id in self._ids:
            return False
        self.check(correction)
        self._apply(correction)
        return True

    def known_records(self) -> Dict[str, Any]:
        """A1 の record と置き換え（id → record。無効化 ／ 置き換えられたものも含む）。"""
        known = {record.record_id: record for record in self.identity.records}
        known.update(self._replacements)
        return known

    def check(self, correction: IdentityCorrection) -> None:
        if not isinstance(correction, IdentityCorrection):
            raise CorrectionHistoryError("INVALID_TYPE", "not an identity correction")
        if self._last_accepted_at is not None and correction.accepted_at < self._last_accepted_at:
            raise CorrectionHistoryError("NON_MONOTONIC_ACCEPTED_AT", correction.action.value)
        known = self.known_records()
        for index, target in enumerate(correction.targets):
            record = known.get(target)
            if record is None:
                raise CorrectionHistoryError("MISSING_TARGET", "target")
            if record.known_at > correction.accepted_at:
                raise CorrectionHistoryError("FUTURE_TARGET", "target")
            if target in self._corrected:
                raise CorrectionHistoryError("CONFLICTING_CORRECTION", "target already corrected")
            if correction.action is not CorrectionAction.SUPERSEDE_RECORD:
                continue
            replacement = correction.replacements[index]
            if replacement.KIND is not record.KIND:
                raise CorrectionHistoryError("CROSS_KIND_CORRECTION", record.KIND.value)
            if record.KIND in _REGISTRATION_KINDS and _registered_id(replacement) != _registered_id(record):
                raise CorrectionHistoryError("IDENTITY_CHANGE_NOT_ALLOWED", record.KIND.value)
            if replacement.record_id in self._corrected or replacement.record_id in correction.targets:
                raise CorrectionHistoryError("CORRECTION_CYCLE", "replacement returns to a corrected record")
            if replacement.record_id in known:
                raise CorrectionHistoryError("DUPLICATE_REPLACEMENT", "replacement already present")
        try:
            _build_view(self.identity.records, self._corrections + [correction], correction.accepted_at)
        except IdentityHistoryError as exc:
            raise CorrectionHistoryError("CORRECTION_BREAKS_AUTHORITY", exc.code) from None

    def check_against_all(self, correction: IdentityCorrection) -> None:
        """store の append 用: 受理の時点に加え、両 journal の全体の像でも A1 の不変条件を満たすこと。"""
        self.check(correction)
        try:
            _build_view(self.identity.records, self._corrections + [correction], None)
        except IdentityHistoryError as exc:
            raise CorrectionHistoryError("CORRECTION_BREAKS_AUTHORITY", exc.code) from None

    def _apply(self, correction: IdentityCorrection) -> None:
        self._corrections.append(correction)
        self._ids[correction.record_id] = correction
        self._last_accepted_at = correction.accepted_at
        replacements = correction.replacements or (None,) * len(correction.targets)
        for target, replacement in zip(correction.targets, replacements):
            self._corrected[target] = correction.record_id
            if replacement is not None:
                self._replacements[replacement.record_id] = replacement

    def pin(self, authority_as_of: datetime) -> PinnedAuthority:
        """authority_as_of までの A1 の record と訂正で像を作る。A1 の不変条件に反すれば `CORRECTION_CONFLICT`。"""
        _aware(authority_as_of, "authority_as_of")
        identity_ids = tuple(r.record_id for r in self.identity.records if r.known_at <= authority_as_of)
        correction_ids = tuple(c.record_id for c in self._corrections if c.accepted_at <= authority_as_of)
        try:
            view = _build_view(self.identity.records, self._corrections, authority_as_of)
        except IdentityHistoryError as exc:
            raise CorrectionHistoryError("CORRECTION_CONFLICT", exc.code) from None
        return PinnedAuthority(authority_as_of, view, authority_version(identity_ids, correction_ids), identity_ids,
                               correction_ids)


def _registered_id(record: Any) -> str:
    return record.issuer_id if record.KIND is RecordKind.ISSUER_REGISTRATION else record.security_id


def _build_view(identity_records: Tuple[Any, ...], corrections: List[IdentityCorrection],
                authority_as_of: Optional[datetime]) -> PinnedAuthorityView:
    """知識の cutoff までの A1 の record に訂正を適用し、置き換えを対象の位置に置いて A1 の不変条件で検査し直す。"""
    position: Dict[str, Tuple[int, ...]] = {}
    effective: Dict[str, Any] = {}
    for index, record in enumerate(identity_records):
        if authority_as_of is None or record.known_at <= authority_as_of:
            position[record.record_id] = (index,)
            effective[record.record_id] = record
    for number, correction in enumerate(corrections):
        if authority_as_of is not None and correction.accepted_at > authority_as_of:
            continue
        for index, target in enumerate(correction.targets):
            if target not in effective:
                raise IdentityHistoryError("MISSING_TARGET", "target not in the authority view")
            del effective[target]
            if correction.action is CorrectionAction.SUPERSEDE_RECORD:
                replacement = correction.replacements[index]
                position[replacement.record_id] = position[target] + (number, index)
                effective[replacement.record_id] = replacement
    ordered = sorted(effective.values(), key=lambda record: (_tier(record), position[record.record_id]))
    return PinnedAuthorityView(ordered)


def record_subjects(record: Any, known: Mapping[str, Any]) -> Tuple[str, ...]:
    """record が関わる Issuer ／ Security の id（終わりの record は参照先を辿る）。coverage は空。"""
    kind = record.KIND
    if kind is RecordKind.ISSUER_REGISTRATION:
        return (record.issuer_id,)
    if kind is RecordKind.SECURITY_REGISTRATION:
        return (record.security_id, record.issuer_id)
    if kind in (RecordKind.IDENTIFIER_ASSIGNMENT, RecordKind.LISTING_START):
        return (record.security_id,)
    if kind is RecordKind.DISPLAY_NAME:
        return (record.subject_id,)
    if kind is RecordKind.IDENTIFIER_RETIREMENT:
        referenced = known.get(record.assignment_record_id)
        return (referenced.security_id,) if referenced is not None else ()
    if kind is RecordKind.LISTING_END:
        referenced = known.get(record.listing_record_id)
        return (referenced.security_id,) if referenced is not None else ()
    return ()


__all__ = ["AUTHORITATIVE_CORRECTION_RECORD", "AUTHORITY_VERSION_PREFIX", "AUTHORIZED_REVIEWERS",
           "CORRECTION_ID_PREFIX", "CORRECTION_RECORD_KIND", "CORRECTION_SCHEMA_VERSION", "CorrectionAction",
           "CorrectionHistory", "CorrectionHistoryError", "CorrectionModelError", "CorrectionReason",
           "CorrectionReview", "IdentityCorrection", "MAX_EVIDENCE", "MAX_TARGETS", "PinnedAuthority",
           "PinnedAuthorityView", "REPLACEMENT_SOURCE_CLASS", "ReviewEvidence", "ReviewerClass",
           "VIEW_RULES_VERSION", "authority_version", "is_authority_version", "is_identity_record_id",
           "parse_correction", "parse_correction_line", "record_subjects"]
