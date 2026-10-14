"""P9-A3 — Watchlist ／ Thesis の authority の正準の直列化 ／ 復元（純 ・既定値を作らない）。

1 行 ＝ `canonical_json(revision.as_dict())`（A2 の `as_dict` ＝ 内容 address の全欄 ＋ `revision_id`）。復元は欄の集合の完全一致 ・
enum ・id ・aware な瞬間（UTC の ISO の正準形だけ）・日（`YYYY-MM-DD` の正準形だけ）を検査し、A2 の model を作り直して
`revision_id` の一致を要求する（違えば fail closed）。未知の欄 ・欠けた欄 ・既定値の補完は無い。

記録: `docs/databank/PHASE9_A3_AUTHORITY_STORES.md`。
"""
from __future__ import annotations

from datetime import date, datetime
from typing import Any, Dict, Mapping, Tuple

from .revision_model import ChangeKind, SemanticModelError, canonical_json, iso_instant, require
from .thesis_model import (EvidenceKind, HumanNoteEvidence, InvalidationBasis, InvalidationCondition,
                           P8ScreenEvidence, ThesisRevision, ThesisStatus)
from .watch_model import ManualProvenance, P8ProposalProvenance, ProvenanceKind, WatchEntryRevision, WatchStatus

SERIALIZATION_RULES_VERSION = "p9_authority_serialization:0.1.0"
_WATCH_FIELDS = frozenset(("authority_class", "author_ref", "change_kind", "correction_reason", "corrects_revision_id",
                           "issuer_id", "prev_revision_id", "provenance", "rationale", "removal_reason",
                           "review_due_on", "reviewed_at", "revision_id", "rules_version", "schema_version", "seq",
                           "status", "thesis_ids", "watch_entry_id"))
_THESIS_FIELDS = frozenset(("assumptions", "authority_class", "author_ref", "catalysts", "change_kind",
                            "confidence_note", "correction_reason", "corrects_revision_id", "counter_evidence",
                            "horizon_note", "invalidated_condition_ids", "invalidation_basis",
                            "invalidation_conditions", "issuer_id", "mechanism", "prev_revision_id", "review_due_on",
                            "reviewed_at", "revision_id", "risks", "rules_version", "schema_version", "seq",
                            "statement", "status", "status_reason", "supporting_evidence", "thesis_id",
                            "watch_entry_id"))
_P8_PROVENANCE_FIELDS = frozenset(("authority_day", "kind", "policy_id", "policy_version", "proposal_digest",
                                   "run_id", "screen_result_id", "universe_id", "universe_version"))
_P8_EVIDENCE_FIELDS = frozenset(("issuer_id", "kind", "run_id", "screen_result_id", "screener_state"))
_NOTE_FIELDS = frozenset(("kind", "note"))
_CONDITION_FIELDS = frozenset(("condition_id", "key", "text"))


def _fields(data: Any, field_set: frozenset, what: str) -> Mapping[str, Any]:
    require(isinstance(data, dict), "INVALID_RECORD", what)
    keys = set(data)
    require(not keys - field_set, "UNKNOWN_FIELD", f"{what}:{sorted(keys - field_set)}")
    require(not field_set - keys, "MISSING_FIELD", f"{what}:{sorted(field_set - keys)}")
    return data


def _enum(cls: Any, value: Any, what: str) -> Any:
    require(isinstance(value, str), "INVALID_ENUM", what)
    try:
        return cls(value)
    except ValueError:
        raise SemanticModelError("INVALID_ENUM", what) from None


def _instant(value: Any, what: str) -> datetime:
    """UTC の ISO の正準形だけ（`iso_instant` と同じ文字列に戻ること）。naive ・他の形は拒む。"""
    require(isinstance(value, str), "INVALID_INSTANT", what)
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        raise SemanticModelError("INVALID_INSTANT", what) from None
    require(parsed.tzinfo is not None and parsed.tzinfo.utcoffset(parsed) is not None, "INSTANT_NOT_AWARE", what)
    require(iso_instant(parsed) == value, "NON_CANONICAL_INSTANT", what)
    return parsed


def _day(value: Any, what: str, *, nullable: bool) -> Any:
    if value is None:
        require(nullable, "MISSING_DATE", what)
        return None
    require(isinstance(value, str), "INVALID_DATE", what)
    try:
        parsed = date.fromisoformat(value)
    except ValueError:
        raise SemanticModelError("INVALID_DATE", what) from None
    require(parsed.isoformat() == value, "NON_CANONICAL_DATE", what)
    return parsed


def _int(value: Any, what: str) -> int:
    require(type(value) is int, "INVALID_INTEGER", what)
    return value


def _str(value: Any, what: str) -> str:
    require(isinstance(value, str), "INVALID_STRING", what)
    return value


def _strings(value: Any, what: str) -> Tuple[str, ...]:
    require(isinstance(value, list) and all(isinstance(v, str) for v in value), "INVALID_LIST", what)
    return tuple(value)


def _provenance(data: Any) -> Any:
    require(isinstance(data, dict), "INVALID_RECORD", "provenance")
    kind = _enum(ProvenanceKind, data.get("kind"), "provenance.kind")
    if kind is ProvenanceKind.MANUAL:
        _fields(data, frozenset(("kind",)), "provenance")
        return ManualProvenance()
    _fields(data, _P8_PROVENANCE_FIELDS, "provenance")
    return P8ProposalProvenance(run_id=_str(data["run_id"], "run_id"),
                                screen_result_id=_str(data["screen_result_id"], "screen_result_id"),
                                policy_id=_str(data["policy_id"], "policy_id"),
                                policy_version=_int(data["policy_version"], "policy_version"),
                                universe_id=_str(data["universe_id"], "universe_id"),
                                universe_version=_int(data["universe_version"], "universe_version"),
                                authority_day=_day(data["authority_day"], "authority_day", nullable=False),
                                proposal_digest=_str(data["proposal_digest"], "proposal_digest"))


def _evidence(data: Any, what: str) -> Any:
    require(isinstance(data, dict), "INVALID_RECORD", what)
    kind = _enum(EvidenceKind, data.get("kind"), f"{what}.kind")
    if kind is EvidenceKind.HUMAN_NOTE:
        _fields(data, _NOTE_FIELDS, what)
        return HumanNoteEvidence(note=_str(data["note"], "note"))
    _fields(data, _P8_EVIDENCE_FIELDS, what)
    return P8ScreenEvidence(run_id=_str(data["run_id"], "run_id"),
                            screen_result_id=_str(data["screen_result_id"], "screen_result_id"),
                            issuer_id=_str(data["issuer_id"], "issuer_id"),
                            screener_state=_str(data["screener_state"], "screener_state"))


def _evidence_list(value: Any, what: str) -> Tuple[Any, ...]:
    require(isinstance(value, list), "INVALID_LIST", what)
    return tuple(_evidence(item, what) for item in value)


def _condition(data: Any) -> InvalidationCondition:
    _fields(data, _CONDITION_FIELDS, "invalidation_condition")
    return InvalidationCondition(condition_id=_str(data["condition_id"], "condition_id"),
                                 key=_str(data["key"], "key"), text=_str(data["text"], "text"))


def watch_to_dict(revision: WatchEntryRevision) -> Dict[str, Any]:
    require(isinstance(revision, WatchEntryRevision), "INVALID_REVISION", "watch")
    return revision.as_dict()


def thesis_to_dict(revision: ThesisRevision) -> Dict[str, Any]:
    require(isinstance(revision, ThesisRevision), "INVALID_REVISION", "thesis")
    return revision.as_dict()


def watch_from_dict(data: Any) -> WatchEntryRevision:
    """正準の dict → A2 の Watchlist の revision（全欄の検査 ・`revision_id` の一致）。"""
    data = _fields(data, _WATCH_FIELDS, "watch")
    revision = WatchEntryRevision(
        watch_entry_id=_str(data["watch_entry_id"], "watch_entry_id"), seq=_int(data["seq"], "seq"),
        prev_revision_id=_str(data["prev_revision_id"], "prev_revision_id"),
        change_kind=_enum(ChangeKind, data["change_kind"], "change_kind"),
        issuer_id=_str(data["issuer_id"], "issuer_id"), status=_enum(WatchStatus, data["status"], "status"),
        rationale=_str(data["rationale"], "rationale"),
        review_due_on=_day(data["review_due_on"], "review_due_on", nullable=True),
        removal_reason=_str(data["removal_reason"], "removal_reason"),
        thesis_ids=_strings(data["thesis_ids"], "thesis_ids"), provenance=_provenance(data["provenance"]),
        author_ref=_str(data["author_ref"], "author_ref"), reviewed_at=_instant(data["reviewed_at"], "reviewed_at"),
        corrects_revision_id=_str(data["corrects_revision_id"], "corrects_revision_id"),
        correction_reason=_str(data["correction_reason"], "correction_reason"),
        authority_class=_str(data["authority_class"], "authority_class"),
        rules_version=_str(data["rules_version"], "rules_version"),
        schema_version=_str(data["schema_version"], "schema_version"))
    require(revision.revision_id == data["revision_id"], "REVISION_ID_MISMATCH", "revision_id")
    return revision


def thesis_from_dict(data: Any) -> ThesisRevision:
    """正準の dict → A2 の Thesis の revision（全欄の検査 ・`revision_id` の一致）。"""
    data = _fields(data, _THESIS_FIELDS, "thesis")
    basis = data["invalidation_basis"]
    require(isinstance(data["invalidation_conditions"], list), "INVALID_LIST", "invalidation_conditions")
    revision = ThesisRevision(
        thesis_id=_str(data["thesis_id"], "thesis_id"), seq=_int(data["seq"], "seq"),
        prev_revision_id=_str(data["prev_revision_id"], "prev_revision_id"),
        change_kind=_enum(ChangeKind, data["change_kind"], "change_kind"),
        issuer_id=_str(data["issuer_id"], "issuer_id"), watch_entry_id=_str(data["watch_entry_id"], "watch_entry_id"),
        status=_enum(ThesisStatus, data["status"], "status"), statement=_str(data["statement"], "statement"),
        mechanism=_str(data["mechanism"], "mechanism"), catalysts=_strings(data["catalysts"], "catalysts"),
        risks=_strings(data["risks"], "risks"), assumptions=_strings(data["assumptions"], "assumptions"),
        invalidation_conditions=tuple(_condition(item) for item in data["invalidation_conditions"]),
        supporting_evidence=_evidence_list(data["supporting_evidence"], "supporting_evidence"),
        counter_evidence=_evidence_list(data["counter_evidence"], "counter_evidence"),
        horizon_note=_str(data["horizon_note"], "horizon_note"),
        review_due_on=_day(data["review_due_on"], "review_due_on", nullable=True),
        confidence_note=_str(data["confidence_note"], "confidence_note"),
        author_ref=_str(data["author_ref"], "author_ref"), reviewed_at=_instant(data["reviewed_at"], "reviewed_at"),
        status_reason=_str(data["status_reason"], "status_reason"),
        invalidation_basis=None if basis is None else _enum(InvalidationBasis, basis, "invalidation_basis"),
        invalidated_condition_ids=_strings(data["invalidated_condition_ids"], "invalidated_condition_ids"),
        corrects_revision_id=_str(data["corrects_revision_id"], "corrects_revision_id"),
        correction_reason=_str(data["correction_reason"], "correction_reason"),
        authority_class=_str(data["authority_class"], "authority_class"),
        rules_version=_str(data["rules_version"], "rules_version"),
        schema_version=_str(data["schema_version"], "schema_version"))
    require(revision.revision_id == data["revision_id"], "REVISION_ID_MISMATCH", "revision_id")
    return revision


def watch_line(revision: WatchEntryRevision) -> str:
    return canonical_json(watch_to_dict(revision))


def thesis_line(revision: ThesisRevision) -> str:
    return canonical_json(thesis_to_dict(revision))


__all__ = ["SERIALIZATION_RULES_VERSION", "thesis_from_dict", "thesis_line", "thesis_to_dict", "watch_from_dict",
           "watch_line", "watch_to_dict"]
