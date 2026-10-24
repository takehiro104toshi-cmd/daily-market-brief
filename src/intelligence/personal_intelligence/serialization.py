"""P10-A3 — Personal Profile ／ Attention の revision の正準の直列化（1 行 ＝ 1 つの正準の JSON の object ・修復 ・正規化なし）。

- 書き: `canonical_json(revision.as_dict())`（A2 の正準の JSON ＝ key の文字の順 ・区切りの空白なし ・非 ASCII はそのまま）を UTF-8 で。
  列挙は `.value` ・tuple は文字の順の list ・瞬間は UTC の ISO（A2 の `iso_instant`）・`revision_id` を含む。UTF-8 にできない文字は拒む。
- 読み: 欄の集合の完全一致（未知 ・欠けは拒む ・既定値で補わない）・文字列 ・列挙 ・瞬間の型と正準の形 → A2 の型を全ての欄で明示に
  構築（A2 の全検査）→ 内容から再計算した `revision_id` が記録の `revision_id` と一致すること。行の正準の形は store_io が検査する。

記録: `docs/databank/PHASE10_A3_PROFILE_ATTENTION_STORES.md`。
"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Mapping, Tuple

from .attention_model import AttentionRevision, AttentionState, AttentionTargetKind
from .profile_model import PersonalProfileRevision, ProfileStatus
from .revision_model import ChangeKind, canonical_json, iso_instant, require

PROFILE_RECORD_FIELDS: Tuple[str, ...] = (
    "author_ref", "authority_class", "change_kind", "correction_reason", "corrects_revision_id",
    "excluded_issuer_ids", "exclusion_reason_note", "horizon_note", "liquidity_note", "prev_revision_id",
    "profile_id", "retirement_reason", "review_lookahead_days", "reviewed_at", "revision_id", "risk_context_note",
    "rules_version", "schema_version", "seq", "status")
ATTENTION_RECORD_FIELDS: Tuple[str, ...] = (
    "attention_id", "author_ref", "authority_class", "change_kind", "observed_p9_revision_id", "prev_revision_id",
    "reviewed_at", "revision_id", "rules_version", "schema_version", "seq", "state", "target_kind", "target_root_id")
_PROFILE_STRINGS = ("authority_class", "author_ref", "correction_reason", "corrects_revision_id", "exclusion_reason_note",
                    "horizon_note", "liquidity_note", "prev_revision_id", "profile_id", "retirement_reason",
                    "revision_id", "risk_context_note", "rules_version", "schema_version")
_ATTENTION_STRINGS = ("attention_id", "authority_class", "author_ref", "observed_p9_revision_id", "prev_revision_id",
                      "revision_id", "rules_version", "schema_version", "target_root_id")


def _fields(record: Any, expected: Tuple[str, ...], strings: Tuple[str, ...]) -> Mapping[str, Any]:
    require(isinstance(record, dict), "RECORD_NOT_OBJECT", "record")
    require(not set(record) - set(expected), "UNKNOWN_FIELDS", "record")
    require(not set(expected) - set(record), "MISSING_FIELDS", "record")
    for name in strings:
        require(isinstance(record[name], str), "INVALID_STRING", name)
    return record


def _enum(kind: Any, value: Any, field_name: str) -> Any:
    require(isinstance(value, str) and value in {member.value for member in kind}, "INVALID_ENUM", field_name)
    return kind(value)


def _instant(value: Any, field_name: str) -> datetime:
    require(isinstance(value, str), "INVALID_TIMESTAMP", field_name)
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        parsed = None
    require(parsed is not None and parsed.tzinfo is not None, "INVALID_TIMESTAMP", field_name)
    require(iso_instant(parsed) == value, "NON_CANONICAL_TIMESTAMP", field_name)  # UTC の ISO だけ
    return parsed


def _line(revision: Any) -> str:
    """正準の 1 行。UTF-8 にできない文字（対の無い surrogate 等。id の計算も失敗する）は型つきで拒む。"""
    try:
        line = canonical_json(revision.as_dict())
        line.encode("utf-8")
    except UnicodeEncodeError:
        line = ""
    require(line != "", "UNENCODABLE_TEXT", "record")
    return line


def profile_line(revision: Any) -> str:
    require(isinstance(revision, PersonalProfileRevision), "INVALID_REVISION", "profile")
    return _line(revision)


def attention_line(revision: Any) -> str:
    require(isinstance(revision, AttentionRevision), "INVALID_REVISION", "attention")
    return _line(revision)


def profile_from_record(record: Any) -> PersonalProfileRevision:
    data = _fields(record, PROFILE_RECORD_FIELDS, _PROFILE_STRINGS)
    issuers = data["excluded_issuer_ids"]
    require(isinstance(issuers, list) and all(isinstance(value, str) for value in issuers), "INVALID_LIST",
            "excluded_issuer_ids")
    revision = PersonalProfileRevision(
        profile_id=data["profile_id"], seq=data["seq"], prev_revision_id=data["prev_revision_id"],
        change_kind=_enum(ChangeKind, data["change_kind"], "change_kind"),
        status=_enum(ProfileStatus, data["status"], "status"), horizon_note=data["horizon_note"],
        liquidity_note=data["liquidity_note"], risk_context_note=data["risk_context_note"],
        review_lookahead_days=data["review_lookahead_days"], excluded_issuer_ids=tuple(issuers),
        exclusion_reason_note=data["exclusion_reason_note"], author_ref=data["author_ref"],
        reviewed_at=_instant(data["reviewed_at"], "reviewed_at"), retirement_reason=data["retirement_reason"],
        corrects_revision_id=data["corrects_revision_id"], correction_reason=data["correction_reason"],
        authority_class=data["authority_class"], rules_version=data["rules_version"],
        schema_version=data["schema_version"])
    require(revision.revision_id == data["revision_id"], "REVISION_ID_MISMATCH", "revision_id")
    return revision


def attention_from_record(record: Any) -> AttentionRevision:
    data = _fields(record, ATTENTION_RECORD_FIELDS, _ATTENTION_STRINGS)
    revision = AttentionRevision(
        attention_id=data["attention_id"], seq=data["seq"], prev_revision_id=data["prev_revision_id"],
        change_kind=_enum(ChangeKind, data["change_kind"], "change_kind"),
        target_kind=_enum(AttentionTargetKind, data["target_kind"], "target_kind"),
        target_root_id=data["target_root_id"], observed_p9_revision_id=data["observed_p9_revision_id"],
        state=_enum(AttentionState, data["state"], "state"), author_ref=data["author_ref"],
        reviewed_at=_instant(data["reviewed_at"], "reviewed_at"), authority_class=data["authority_class"],
        rules_version=data["rules_version"], schema_version=data["schema_version"])
    require(revision.revision_id == data["revision_id"], "REVISION_ID_MISMATCH", "revision_id")
    return revision


__all__ = ["ATTENTION_RECORD_FIELDS", "PROFILE_RECORD_FIELDS", "attention_from_record", "attention_line",
           "profile_from_record", "profile_line"]
