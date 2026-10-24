"""P13-A2a — P10 の governed な safe view だけを読む read-only の adapter（Review State Memory の標本の唯一の入口）。

使う面は P10 の 5 つの名前だけ（`read_personal_review` ・`read_p9_safe_view` ・`personal_safe_projection` ・`ReviewViewError` ・`P9ViewError`）。
P10 ／ P9 の store の class ・private な snapshot は import しない。root は P10 の reader に渡すだけで、この module は file を開かない ・
書かない ・時計 ・環境 ・network ・process を使わない。標本の telemetry（`SampleEvidence` ・`sampled_at`）は作らない。

手順（明示の `SampleCutoff` の `at` ・`as_of_date` を 3 回の読みに同じく渡す）:
1. P9 の safe view を読む（失敗は P9 の category で分類する。review の経路は P9 の category を落とすため先に読む）。
2. 見直しの view を読む。
3. P9 の safe view をもう一度読み、1 と全ての欄 ・class ・schema ・rules が一致することを確かめる。
4. 形 ・schema ／ rules の version ・view の class ・`as_of_date` を、検証済みの固定の literal と比べる（返った値から期待を導かない）。
5. 個人の安全な投影を作る。6. 承認した欄だけを P13 の model に写す。7. 標本を作る。

限界: 2 回の P9 の読みが一致しても、store をまたぐ不可分な snapshot の証明ではなく、間の往復（ABA）を除外できない。

失敗の分類はこの module が行う（P13-A1 の `outcome_for_source_failure` に P10 の生の code を渡さない。P10 の
`P10_STORE_UNAVAILABLE` ・`P9_UNAVAILABLE` は破損も含むため）。結果の code は固定の定数だけで、例外の detail ・root は出さない。
"""
from __future__ import annotations

from dataclasses import fields, is_dataclass
from typing import Any, Dict, FrozenSet, Tuple

from ..personal_intelligence.p9_view import P9ViewError, read_p9_safe_view
from ..personal_intelligence.personal_projection import personal_safe_projection
from ..personal_intelligence.review_view import ReviewViewError, read_personal_review
from .canonical import CanonicalError
from .review_state_sample import (PERSONAL_COUNT_KEYS, OutcomeStatus, P9SafeCounts, ReviewStateCounts, ReviewStateEntry,
                                  ReviewStateError, SampleCutoff, SampleOutcome, SourceViewIdentity, build_sample)

ADAPTER_RULES_VERSION = "p13_governed_review_source:0.1.0"
#: 検証済みの governed な view の版 ・class（P10 の凍結の定数と test が一致を確かめる）。これ以外は fail closed
SUPPORTED_REVIEW_VIEW_SCHEMA = "p10_personal_review:0.1.0"
SUPPORTED_REVIEW_VIEW_CLASS = "PERSONAL_REVIEW_PRIVATE_LOCAL_DERIVED_NON_AUTHORITY_SURFACING_ONLY"
SUPPORTED_P9_VIEW_SCHEMA = "p10_p9_view:0.1.0"
SUPPORTED_P9_VIEW_RULES = "p10_p9_view:0.1.0"
SUPPORTED_P9_VIEW_CLASS = "P9_SAFE_VIEW_COUNTS_ONLY_DERIVED_NON_AUTHORITY_READ_ONLY"
SUPPORTED_PROJECTION_SCHEMA = "p10_personal_safe_projection:0.1.0"
SUPPORTED_PROJECTION_CLASS = "PERSONAL_SAFE_PROJECTION_COUNTS_ONLY_DERIVED_NON_AUTHORITY_NOT_PERSISTED"
SUPPORTED_VIEW_IDENTITY = SourceViewIdentity(review_view_schema_version=SUPPORTED_REVIEW_VIEW_SCHEMA,
                                             p9_safe_view_schema_version=SUPPORTED_P9_VIEW_SCHEMA,
                                             p9_view_rules_version=SUPPORTED_P9_VIEW_RULES,
                                             personal_projection_schema_version=SUPPORTED_PROJECTION_SCHEMA)

#: 結果の code（固定の定数だけ）
P9_STORE_MISSING = "P9_STORE_MISSING"
P10_STORE_MISSING = "P10_STORE_MISSING"
P9_STORE_CORRUPTION = "P9_STORE_CORRUPTION"
P10_STORE_CORRUPTION = "P10_STORE_CORRUPTION"
P9_WORLD_INVALID = "P9_WORLD_INVALID"
P10_WORLD_INVALID = "P10_WORLD_INVALID"
SOURCE_CHANGED_DURING_READ = "SOURCE_CHANGED_DURING_READ"
SOURCE_INPUT_REJECTED = "SOURCE_INPUT_REJECTED"
SOURCE_READ_UNCLASSIFIED = "SOURCE_READ_UNCLASSIFIED"
VIEW_SHAPE_UNSUPPORTED = "VIEW_SHAPE_UNSUPPORTED"
VIEW_SCHEMA_UNSUPPORTED = "VIEW_SCHEMA_UNSUPPORTED"
VIEW_CLASS_UNSUPPORTED = "VIEW_CLASS_UNSUPPORTED"
VIEW_AS_OF_MISMATCH = "VIEW_AS_OF_MISMATCH"
VIEW_CONTENT_INVALID = "VIEW_CONTENT_INVALID"
ADAPTER_FAILURE_CODES: FrozenSet[str] = frozenset({
    P9_STORE_MISSING, P10_STORE_MISSING, P9_STORE_CORRUPTION, P10_STORE_CORRUPTION, P9_WORLD_INVALID, P10_WORLD_INVALID,
    SOURCE_CHANGED_DURING_READ, SOURCE_INPUT_REJECTED, SOURCE_READ_UNCLASSIFIED, VIEW_SHAPE_UNSUPPORTED, VIEW_SCHEMA_UNSUPPORTED,
    VIEW_CLASS_UNSUPPORTED, VIEW_AS_OF_MISMATCH, VIEW_CONTENT_INVALID})
MISSING_CODES: FrozenSet[str] = frozenset({P9_STORE_MISSING, P10_STORE_MISSING})
#: 呼び出し側の入力の誤り（source を読む前の型の検査）は例外にする（結果ではない）
ADAPTER_INPUT_INVALID = "ADAPTER_INPUT_INVALID"

#: governed な reader の不在の code（category `STORE_MISSING` の中でも、これだけが不在。他は fail closed）
_P9_ABSENCE_CODES = frozenset({"P9_ROOT_MISSING", "STORE_MISSING"})
_P10_ABSENCE_CODES = frozenset({"P10_ROOT_MISSING", "AUTHORITY_DIR_MISSING", "STORE_MISSING"})
#: P9 の root の拒否（P9 の store は category `STORE_MISSING` で返す）
_P9_ROOT_REJECTION_CODES = frozenset({"ROOT_REQUIRED", "ROOT_NOT_ABSOLUTE"})
_INPUT_CODES = frozenset({"INSTANT_NOT_AWARE", "INVALID_DATE"})

#: 期待する欄の集合（固定 ・P13 の model の型から。返った object からは導かない）
_ENTRY_FIELDS: Tuple[str, ...] = tuple(f.name for f in fields(ReviewStateEntry))
_P9_COUNT_FIELDS: Tuple[str, ...] = tuple(f.name for f in fields(P9SafeCounts))
_REVIEW_FIELDS = frozenset({"as_of_date", "review_lookahead_days", "active_profile_present", "entries", "live_focus_marks",
                            "live_mute_marks", "cleared_marks", "unmatched_live_marks", "view_class", "schema_version"})
_P9_VIEW_FIELDS = frozenset(_P9_COUNT_FIELDS) | {"as_of_date", "view_class", "rules_version", "schema_version"}
_PROJECTION_FIELDS = frozenset(PERSONAL_COUNT_KEYS) | {"projection_class", "schema_version"}


def _failed(status: OutcomeStatus, code: str) -> SampleOutcome:
    return SampleOutcome(status=status, failure_code=code, sample=None)


def _missing(code: str) -> SampleOutcome:
    return _failed(OutcomeStatus.MISSING, code)


def _integrity(code: str) -> SampleOutcome:
    return _failed(OutcomeStatus.INTEGRITY_FAILURE, code)


def _split_detail(detail: Any) -> Tuple[str, str]:
    """governed な reader の detail `<category>:<code>` を分ける（形が違えば空 ＝ 分類できない）。"""
    if not isinstance(detail, str) or ":" not in detail:
        return "", ""
    category, code = detail.split(":", 1)
    return category, code


def _classify_first_p9_failure(exc: P9ViewError) -> SampleOutcome:
    if exc.code == "P9_STORE_UNAVAILABLE":
        category, code = _split_detail(exc.detail)
        if category == "STORE_MISSING" and code in _P9_ABSENCE_CODES:
            return _missing(P9_STORE_MISSING)
        if category == "STORE_MISSING" and code in _P9_ROOT_REJECTION_CODES:
            return _integrity(SOURCE_INPUT_REJECTED)
        if category == "STORE_CORRUPTION":
            return _integrity(P9_STORE_CORRUPTION)
        if category == "CONCURRENT_MODIFICATION":
            return _integrity(SOURCE_CHANGED_DURING_READ)
        return _integrity(SOURCE_READ_UNCLASSIFIED)
    if exc.code == "P9_WORLD_INVALID":
        return _integrity(P9_WORLD_INVALID)
    if exc.code in _INPUT_CODES:
        return _integrity(SOURCE_INPUT_REJECTED)
    return _integrity(SOURCE_READ_UNCLASSIFIED)


def _classify_review_failure(exc: ReviewViewError) -> SampleOutcome:
    """P9 は直前に読めている。P10 の不在だけが MISSING で、P9 の失敗は読みの間の変化として扱う。"""
    if exc.code == "P10_STORE_UNAVAILABLE":
        category, code = _split_detail(exc.detail)
        if category == "STORE_MISSING" and code in _P10_ABSENCE_CODES:
            return _missing(P10_STORE_MISSING)
        if category == "ROOT_REJECTED":
            return _integrity(SOURCE_INPUT_REJECTED)
        if category == "STORE_CORRUPTION":
            return _integrity(P10_STORE_CORRUPTION)
        if category == "CONCURRENT_MODIFICATION":
            return _integrity(SOURCE_CHANGED_DURING_READ)
        return _integrity(SOURCE_READ_UNCLASSIFIED)
    if exc.code == "P10_WORLD_INVALID":
        return _integrity(P10_WORLD_INVALID)
    if exc.code == "P9_UNAVAILABLE":
        return _integrity(SOURCE_CHANGED_DURING_READ)
    if exc.code in _INPUT_CODES:
        return _integrity(SOURCE_INPUT_REJECTED)
    return _integrity(SOURCE_READ_UNCLASSIFIED)


def _check_root(value: Any, field_code: str) -> None:
    if isinstance(value, str):
        accepted = value.strip() != "" and "\x00" not in value
    else:
        accepted = hasattr(value, "__fspath__")
    if not accepted:
        raise ReviewStateError(ADAPTER_INPUT_INVALID, field_code)


def _check_rules_version(value: Any) -> None:
    accepted = (isinstance(value, str) and 1 <= len(value) <= 128
                and all(ch.isalnum() or ch in "_-.:" for ch in value))
    if not accepted:
        raise ReviewStateError(ADAPTER_INPUT_INVALID, "RULES_VERSION")


def _has_shape(record: Any, expected: FrozenSet[str]) -> bool:
    return is_dataclass(record) and not isinstance(record, type) and {f.name for f in fields(record)} == expected


def _record_values(record: Any) -> Tuple[Tuple[str, Any], ...]:
    return tuple((name, getattr(record, name)) for name in sorted(f.name for f in fields(record)))


def sample_review_state(p10_root: Any, p9_root: Any, *, cutoff: SampleCutoff, rules_version: str) -> SampleOutcome:
    """明示の cutoff で P10 の governed な view を読み、Review State Memory の標本の結果を返す（書かない ・作らない）。"""
    _check_root(p10_root, "P10_ROOT")
    _check_root(p9_root, "P9_ROOT")
    if not isinstance(cutoff, SampleCutoff):
        raise ReviewStateError(ADAPTER_INPUT_INVALID, "CUTOFF")
    _check_rules_version(rules_version)
    at, day = cutoff.at, cutoff.as_of_date

    try:                                                                                 # 1. P9（category を保つ経路を先に）
        first_p9 = read_p9_safe_view(p9_root, at=at, as_of_date=day)
    except P9ViewError as exc:
        return _classify_first_p9_failure(exc)
    try:                                                                                 # 2. 見直しの view
        review = read_personal_review(p10_root, p9_root, at=at, as_of_date=day)
    except ReviewViewError as exc:
        return _classify_review_failure(exc)
    try:                                                                                 # 3. P9 の再読（後の失敗は変化として扱う）
        second_p9 = read_p9_safe_view(p9_root, at=at, as_of_date=day)
    except P9ViewError:
        return _integrity(SOURCE_CHANGED_DURING_READ)

    if not (_has_shape(first_p9, _P9_VIEW_FIELDS) and _has_shape(second_p9, _P9_VIEW_FIELDS)
            and _has_shape(review, _REVIEW_FIELDS)):
        return _integrity(VIEW_SHAPE_UNSUPPORTED)
    if _record_values(first_p9) != _record_values(second_p9):                           # 4. 2 回の P9 の読みの一致（ABA は除外できない）
        return _integrity(SOURCE_CHANGED_DURING_READ)
    if (review.schema_version != SUPPORTED_REVIEW_VIEW_SCHEMA or first_p9.schema_version != SUPPORTED_P9_VIEW_SCHEMA
            or first_p9.rules_version != SUPPORTED_P9_VIEW_RULES):
        return _integrity(VIEW_SCHEMA_UNSUPPORTED)
    if review.view_class != SUPPORTED_REVIEW_VIEW_CLASS or first_p9.view_class != SUPPORTED_P9_VIEW_CLASS:
        return _integrity(VIEW_CLASS_UNSUPPORTED)
    if review.as_of_date != day or first_p9.as_of_date != day:
        return _integrity(VIEW_AS_OF_MISMATCH)
    if not (isinstance(review.entries, tuple) and all(_has_shape(e, frozenset(_ENTRY_FIELDS)) for e in review.entries)):
        return _integrity(VIEW_SHAPE_UNSUPPORTED)

    projection = personal_safe_projection(review)                                       # 5. 個人の安全な投影（純粋）
    if not _has_shape(projection, _PROJECTION_FIELDS):
        return _integrity(VIEW_SHAPE_UNSUPPORTED)
    if projection.schema_version != SUPPORTED_PROJECTION_SCHEMA:
        return _integrity(VIEW_SCHEMA_UNSUPPORTED)
    if projection.projection_class != SUPPORTED_PROJECTION_CLASS:
        return _integrity(VIEW_CLASS_UNSUPPORTED)

    try:                                                                                 # 6. 承認した欄だけを写す
        entries = tuple(ReviewStateEntry(**{name: getattr(entry, name) for name in _ENTRY_FIELDS}) for entry in review.entries)
        p9_counts = P9SafeCounts(**{name: getattr(first_p9, name) for name in _P9_COUNT_FIELDS})
        personal: Dict[str, Any] = {key: getattr(projection, key) for key in PERSONAL_COUNT_KEYS}
        counts = ReviewStateCounts(active_profile_present=review.active_profile_present,
                                   review_lookahead_days=review.review_lookahead_days,
                                   live_focus_marks=review.live_focus_marks, live_mute_marks=review.live_mute_marks,
                                   cleared_marks=review.cleared_marks, unmatched_live_marks=review.unmatched_live_marks,
                                   p9=p9_counts, personal=tuple(sorted(personal.items())))
    except (ReviewStateError, CanonicalError):
        return _integrity(VIEW_CONTENT_INVALID)
    return build_sample(cutoff=cutoff, view_identity=SUPPORTED_VIEW_IDENTITY, entries=entries, counts=counts,  # 7. 標本
                        rules_version=rules_version)


__all__ = ["ADAPTER_FAILURE_CODES", "ADAPTER_INPUT_INVALID", "ADAPTER_RULES_VERSION", "MISSING_CODES", "P10_STORE_CORRUPTION",
           "P10_STORE_MISSING", "P10_WORLD_INVALID", "P9_STORE_CORRUPTION", "P9_STORE_MISSING", "P9_WORLD_INVALID",
           "SOURCE_CHANGED_DURING_READ", "SOURCE_INPUT_REJECTED", "SOURCE_READ_UNCLASSIFIED", "SUPPORTED_P9_VIEW_CLASS",
           "SUPPORTED_P9_VIEW_RULES", "SUPPORTED_P9_VIEW_SCHEMA", "SUPPORTED_PROJECTION_CLASS", "SUPPORTED_PROJECTION_SCHEMA",
           "SUPPORTED_REVIEW_VIEW_CLASS", "SUPPORTED_REVIEW_VIEW_SCHEMA", "SUPPORTED_VIEW_IDENTITY", "VIEW_AS_OF_MISMATCH",
           "VIEW_CLASS_UNSUPPORTED", "VIEW_CONTENT_INVALID", "VIEW_SCHEMA_UNSUPPORTED", "VIEW_SHAPE_UNSUPPORTED",
           "sample_review_state"]
