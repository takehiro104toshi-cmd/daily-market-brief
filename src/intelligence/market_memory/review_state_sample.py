"""P13-A1 — Review State Memory の標本（`ReviewStateSample`）の純粋な model。

P12.5-A2 §7 の意味をそのまま型にする:
- 標本 ＝ 明示の cutoff `(at, as_of_date)` で有効だった **先頭の状態**。source の `known_at` ・`reviewed_at` ・P10 の revision の id ／ digest は
  governed な view が返さないので **持たない ・作らない**（`PROVENANCE_CLASS` がその限界を記録する）。
- `sampled_at` などの telemetry は `SampleEvidence` に分け、identity ・内容 ・PIT の判定に一切使わない。
- 入力は P10 の governed な view と同じ形の **合成の入力**（A1 では凍結の phase を import しない）。view の件数は実際の意味で検算する。
- 失敗の区別: MISSING（source が無い）／ INTEGRITY_FAILURE（壊れている ・矛盾）／ 空の標本（有効で項目が 0）。失敗から部分の標本は作らない。
- STALE は人が宣言した窓による label で trigger ではない。UNKNOWN ／ UNCERTAIN ／ AMBIGUOUS は予約語で、この経路では出ない。
- 時計 ・既定 ・「最新」は無い。file ・環境 ・socket ・process ・乱数に触れない。
"""
from __future__ import annotations

from dataclasses import dataclass, fields
from datetime import date, datetime
from enum import Enum
from typing import Any, Dict, Mapping, Optional, Sequence, Tuple

from .canonical import (CanonicalError, assert_no_short_id_collision, canonical_json, date_iso, domain_digest, is_digest,
                        parse_date_iso, parse_utc_iso, require_aware, require_date, require_fields, require_safe_code,
                        short_id, utc_iso)

SAMPLE_SCHEMA_VERSION = "p13_review_state_sample:0.1.0"
SAMPLE_DOMAIN = "p13.review_state_sample.v1"
BUILD_DOMAIN = "p13.review_state_build.v1"
SAMPLE_ID_PREFIX = "p13smp_"
AUTHORITY_CLASS = "DERIVED_REVIEW_STATE_SAMPLE_NON_AUTHORITY"
PROVENANCE_CLASS = "P10_GOVERNED_VIEW_SAMPLE_NO_SOURCE_KNOWN_AT_NO_P10_REVISION_DIGEST"
#: 標本 ・変化に決して置かない欄（schema の guard が pin する。文 ・著者 ・source の時刻 ・P10 の revision ・値 ・run ・path ・telemetry）
FORBIDDEN_FIELD_NAMES = frozenset({"rationale", "statement", "mechanism", "note", "notes", "author_ref", "reviewed_at", "known_at",
                                   "profile_revision_id", "attention_revision_id", "excluded_issuer_ids", "value", "amount",
                                   "price", "code", "run_id", "screen_result_id", "sampled_at", "ordinal", "host", "pid"})
#: 変化の検出で比べる構造の欄（identity の鍵 `record_kind` ・`p9_root_id` を除く全て）
STRUCTURAL_FIELDS: Tuple[str, ...] = ("p9_revision_id", "issuer_id", "linked_watch_entry_id", "p9_status", "p9_provenance_kind",
                                      "review_due_on", "due_class", "attention", "excluded_by_profile", "surface_group")
#: PersonalSafeProjection の整数の欄（完全一致で要る）
PERSONAL_COUNT_KEYS = frozenset({"active_profile_count", "live_focus_mark_count", "live_mute_mark_count", "cleared_mark_count",
                                 "review_entry_count", "overdue_count", "due_count", "upcoming_count", "later_count",
                                 "no_due_date_count", "focus_entry_count", "muted_entry_count", "excluded_by_profile_count"})
#: source の失敗 code → 結果（それ以外の code は fail closed で INTEGRITY_FAILURE）
MISSING_SOURCE_CODES = frozenset({"P10_STORE_UNAVAILABLE", "P9_UNAVAILABLE"})
INTEGRITY_SOURCE_CODES = frozenset({"P10_WORLD_INVALID", "P9_INVALID"})
Counts = Tuple[Tuple[str, int], ...]


class RecordKind(str, Enum):
    WATCH_ENTRY = "WATCH_ENTRY"
    THESIS = "THESIS"


class AttentionMark(str, Enum):
    FOCUS = "FOCUS"
    NORMAL = "NORMAL"
    MUTE = "MUTE"


class DueClass(str, Enum):
    OVERDUE = "OVERDUE"
    DUE = "DUE"
    UPCOMING = "UPCOMING"
    LATER = "LATER"
    NO_DUE_DATE = "NO_DUE_DATE"


class SurfaceGroup(str, Enum):
    REVIEW = "REVIEW"
    MUTED = "MUTED"
    EXCLUDED_BY_PROFILE = "EXCLUDED_BY_PROFILE"


class OutcomeStatus(str, Enum):
    SAMPLED = "SAMPLED"
    MISSING = "MISSING"
    INTEGRITY_FAILURE = "INTEGRITY_FAILURE"


class StalenessLabel(str, Enum):
    FRESH = "FRESH"
    STALE = "STALE"
    UNDETERMINED = "UNDETERMINED"


class PitState(str, Enum):
    """P8 の `KnowledgeTime` の語彙の予約（将来の `MemoryItem` の族のため）。P9 ／ P10 の標本の経路は **出さない**。"""

    KNOWN = "KNOWN"
    UNKNOWN = "UNKNOWN"
    UNCERTAIN = "UNCERTAIN"
    AMBIGUOUS = "AMBIGUOUS"


RESERVED_PIT_STATES = (PitState.UNKNOWN, PitState.UNCERTAIN, PitState.AMBIGUOUS)


class ReviewStateError(ValueError):
    def __init__(self, code: str, detail: str = "") -> None:
        super().__init__(f"{code}:{detail}" if detail else code)
        self.code = code
        self.detail = detail


def _require(condition: bool, code: str, detail: str = "") -> None:
    if not condition:
        raise ReviewStateError(code, detail)


def _enum(kind: Any, value: Any, code: str) -> Any:
    try:
        return kind(value.value if isinstance(value, Enum) else value)
    except ValueError:
        raise ReviewStateError(code, kind.__name__) from None


def _identifier(value: Any, code: str, *, allow_empty: bool = False) -> str:
    _require(isinstance(value, str), code, "NOT_A_STRING")
    if value == "":
        _require(allow_empty, code, "EMPTY")
        return value
    _require(1 <= len(value) <= 128 and all(ch.isalnum() or ch in "_-.:" for ch in value), code, "IDENTIFIER")
    return value


def _counts(value: Any, code: str) -> Counts:
    _require(isinstance(value, (tuple, list)), code, "NOT_A_SEQUENCE")
    pairs = []
    for pair in value:
        _require(isinstance(pair, (tuple, list)) and len(pair) == 2, code, "PAIR")
        key, count = pair
        _require(isinstance(key, str) and key != "", code, "KEY")
        _require(type(count) is int and count >= 0, code, "COUNT")
        pairs.append((key, count))
    keys = [k for k, _ in pairs]
    _require(keys == sorted(keys) and len(set(keys)) == len(keys), code, "ORDER")
    return tuple(pairs)


def _nonnegative(value: Any, code: str) -> int:
    _require(type(value) is int and value >= 0, code, "NONNEGATIVE_INT")
    return value


def _check_no_forbidden_fields(kind: type) -> None:
    names = {f.name for f in fields(kind)}
    _require(not names & FORBIDDEN_FIELD_NAMES, "SCHEMA_INVALID", f"{kind.__name__}:FORBIDDEN_FIELD")


# ---------------------------------------------------------------- cutoff ・view の identity


@dataclass(frozen=True, kw_only=True)
class SampleCutoff:
    """明示の PIT の cutoff。`at` は aware（UTC に正準化）・`as_of_date` は明示の `date`（`at` から導かない）。"""

    at: datetime
    as_of_date: date

    def __post_init__(self) -> None:
        object.__setattr__(self, "at", require_aware(self.at, "CUTOFF_INVALID"))
        require_date(self.as_of_date, "CUTOFF_INVALID")

    def content(self) -> Dict[str, str]:
        return {"at": utc_iso(self.at), "as_of_date": date_iso(self.as_of_date)}

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "SampleCutoff":
        fields_ = require_fields(data, frozenset({"at", "as_of_date"}), "SampleCutoff")
        return cls(at=parse_utc_iso(fields_["at"]), as_of_date=parse_date_iso(fields_["as_of_date"]))

    def sort_key(self) -> Tuple[str, str]:
        return (utc_iso(self.at), date_iso(self.as_of_date))


@dataclass(frozen=True, kw_only=True)
class SourceViewIdentity:
    """標本を作った governed な view の schema ／ rules の version（source の view の schema の identity）。文字はそのまま運ぶ。"""

    review_view_schema_version: str
    p9_safe_view_schema_version: str
    p9_view_rules_version: str
    personal_projection_schema_version: str

    def __post_init__(self) -> None:
        for f in fields(self):
            _identifier(getattr(self, f.name), "VIEW_IDENTITY_INVALID")

    def content(self) -> Dict[str, str]:
        return {f.name: getattr(self, f.name) for f in fields(self)}

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "SourceViewIdentity":
        return cls(**require_fields(data, frozenset(f.name for f in fields(cls)), "SourceViewIdentity"))


# ---------------------------------------------------------------- 項目 ・件数


@dataclass(frozen=True, kw_only=True)
class ReviewStateEntry:
    """P10 の governed な見直しの 1 行の構造の欄（文 ・著者 ・瞬間 ・P10 の revision は無い）。"""

    record_kind: RecordKind
    p9_root_id: str
    p9_revision_id: str
    issuer_id: Optional[str]
    linked_watch_entry_id: str
    p9_status: str
    p9_provenance_kind: str
    review_due_on: Optional[date]
    due_class: DueClass
    attention: AttentionMark
    excluded_by_profile: bool
    surface_group: SurfaceGroup

    def __post_init__(self) -> None:
        object.__setattr__(self, "record_kind", _enum(RecordKind, self.record_kind, "ENTRY_INVALID"))
        object.__setattr__(self, "due_class", _enum(DueClass, self.due_class, "ENTRY_INVALID"))
        object.__setattr__(self, "attention", _enum(AttentionMark, self.attention, "ENTRY_INVALID"))
        object.__setattr__(self, "surface_group", _enum(SurfaceGroup, self.surface_group, "ENTRY_INVALID"))
        _identifier(self.p9_root_id, "ENTRY_INVALID")
        _identifier(self.p9_revision_id, "ENTRY_INVALID")
        if self.issuer_id is not None:
            _identifier(self.issuer_id, "ENTRY_INVALID")
        _identifier(self.linked_watch_entry_id, "ENTRY_INVALID", allow_empty=True)
        require_safe_code(self.p9_status, "ENTRY_INVALID")
        if self.p9_provenance_kind != "":
            require_safe_code(self.p9_provenance_kind, "ENTRY_INVALID")
        if self.review_due_on is not None:
            require_date(self.review_due_on, "ENTRY_INVALID")
        _require(type(self.excluded_by_profile) is bool, "ENTRY_INVALID", "EXCLUDED_NOT_BOOL")
        if self.record_kind is RecordKind.WATCH_ENTRY:                                   # view の形: 発行体 ・出所が在り link は無い
            _require(self.issuer_id is not None, "ENTRY_INVALID", "WATCH_ISSUER_REQUIRED")
            _require(self.linked_watch_entry_id == "", "ENTRY_INVALID", "WATCH_HAS_LINK")
            _require(self.p9_provenance_kind != "", "ENTRY_INVALID", "WATCH_PROVENANCE_REQUIRED")
        else:                                                                             # Thesis: link が在り出所の種類は無い
            _require(self.linked_watch_entry_id != "", "ENTRY_INVALID", "THESIS_LINK_REQUIRED")
            _require(self.p9_provenance_kind == "", "ENTRY_INVALID", "THESIS_HAS_PROVENANCE")
        expected_group = (SurfaceGroup.EXCLUDED_BY_PROFILE if self.excluded_by_profile
                          else SurfaceGroup.MUTED if self.attention is AttentionMark.MUTE else SurfaceGroup.REVIEW)
        _require(self.surface_group is expected_group, "ENTRY_INVALID", "SURFACE_GROUP_INCONSISTENT")
        _require((self.review_due_on is None) == (self.due_class is DueClass.NO_DUE_DATE), "ENTRY_INVALID", "DUE_CLASS_INCONSISTENT")

    @property
    def key(self) -> Tuple[str, str]:
        return (self.record_kind.value, self.p9_root_id)

    def structural_values(self) -> Dict[str, Any]:
        content = self.content()
        return {name: content[name] for name in STRUCTURAL_FIELDS}

    def content(self) -> Dict[str, Any]:
        return {"record_kind": self.record_kind.value, "p9_root_id": self.p9_root_id, "p9_revision_id": self.p9_revision_id,
                "issuer_id": self.issuer_id, "linked_watch_entry_id": self.linked_watch_entry_id, "p9_status": self.p9_status,
                "p9_provenance_kind": self.p9_provenance_kind,
                "review_due_on": None if self.review_due_on is None else date_iso(self.review_due_on),
                "due_class": self.due_class.value, "attention": self.attention.value,
                "excluded_by_profile": self.excluded_by_profile, "surface_group": self.surface_group.value}

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "ReviewStateEntry":
        fields_ = require_fields(data, frozenset(f.name for f in fields(cls)), "ReviewStateEntry")
        due = fields_["review_due_on"]
        return cls(**{**fields_, "review_due_on": None if due is None else parse_date_iso(due)})


def check_due_class(entry: ReviewStateEntry, cutoff: SampleCutoff, review_lookahead_days: int) -> None:
    """期日の区分を view の実際の規則で検算する（NO_DUE_DATE ／ OVERDUE ／ DUE ／ UPCOMING（窓の内）／ LATER）。"""
    due = entry.review_due_on
    if due is None:
        expected = DueClass.NO_DUE_DATE
    elif due < cutoff.as_of_date:
        expected = DueClass.OVERDUE
    elif due == cutoff.as_of_date:
        expected = DueClass.DUE
    else:
        expected = DueClass.UPCOMING if (due - cutoff.as_of_date).days <= review_lookahead_days else DueClass.LATER
    _require(entry.due_class is expected, "COUNTS_INCONSISTENT", f"DUE_CLASS:{entry.record_kind.value}")


@dataclass(frozen=True, kw_only=True)
class P9SafeCounts:
    """凍結 P9 の安全な投影（件数だけ）の欄。"""

    watch_count: int
    watch_status_counts: Counts
    watch_provenance_kind_counts: Counts
    watch_review_due_count: int
    watch_declared_thesis_link_count: int
    thesis_count: int
    thesis_status_counts: Counts
    thesis_review_due_count: int
    thesis_invalidation_basis_counts: Counts
    thesis_supporting_evidence_kind_counts: Counts
    thesis_counter_evidence_kind_counts: Counts

    def __post_init__(self) -> None:
        for f in fields(self):
            value = getattr(self, f.name)
            if f.name.endswith("_counts"):
                object.__setattr__(self, f.name, _counts(value, "COUNTS_INVALID"))
            else:
                _nonnegative(value, "COUNTS_INVALID")
        _require(sum(c for _, c in self.watch_status_counts) == self.watch_count, "COUNTS_INCONSISTENT", "WATCH_STATUS_SUM")
        _require(sum(c for _, c in self.watch_provenance_kind_counts) == self.watch_count, "COUNTS_INCONSISTENT", "WATCH_PROVENANCE_SUM")
        _require(sum(c for _, c in self.thesis_status_counts) == self.thesis_count, "COUNTS_INCONSISTENT", "THESIS_STATUS_SUM")
        _require(sum(c for _, c in self.thesis_invalidation_basis_counts) <= self.thesis_count, "COUNTS_INCONSISTENT", "INVALIDATION_SUM")
        _require(self.watch_review_due_count <= self.watch_count and self.thesis_review_due_count <= self.thesis_count,
                 "COUNTS_INCONSISTENT", "REVIEW_DUE_BOUND")

    def content(self) -> Dict[str, Any]:
        return {f.name: (list(map(list, getattr(self, f.name))) if f.name.endswith("_counts") else getattr(self, f.name))
                for f in fields(self)}

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "P9SafeCounts":
        fields_ = require_fields(data, frozenset(f.name for f in fields(cls)), "P9SafeCounts")
        return cls(**{k: (tuple(tuple(p) for p in v) if k.endswith("_counts") else v) for k, v in fields_.items()})


@dataclass(frozen=True, kw_only=True)
class ReviewStateCounts:
    """見直しの view の件数 ＋ 凍結 P9 の安全な投影 ＋ 個人の安全な投影（全て件数 ・真偽 ・日数だけ）。"""

    active_profile_present: bool
    review_lookahead_days: int
    live_focus_marks: int
    live_mute_marks: int
    cleared_marks: int
    unmatched_live_marks: int
    p9: P9SafeCounts
    personal: Counts

    def __post_init__(self) -> None:
        _require(type(self.active_profile_present) is bool, "COUNTS_INVALID", "ACTIVE_PROFILE_NOT_BOOL")
        for name in ("review_lookahead_days", "live_focus_marks", "live_mute_marks", "cleared_marks", "unmatched_live_marks"):
            _nonnegative(getattr(self, name), "COUNTS_INVALID")
        _require(isinstance(self.p9, P9SafeCounts), "COUNTS_INVALID", "P9")
        object.__setattr__(self, "personal", _counts(self.personal, "COUNTS_INVALID"))
        _require({k for k, _ in self.personal} == PERSONAL_COUNT_KEYS, "COUNTS_INVALID", "PERSONAL_KEYS")
        personal = dict(self.personal)
        _require(personal["active_profile_count"] == (1 if self.active_profile_present else 0), "COUNTS_INCONSISTENT", "ACTIVE_PROFILE")
        _require(personal["live_focus_mark_count"] == self.live_focus_marks, "COUNTS_INCONSISTENT", "LIVE_FOCUS")
        _require(personal["live_mute_mark_count"] == self.live_mute_marks, "COUNTS_INCONSISTENT", "LIVE_MUTE")
        _require(personal["cleared_mark_count"] == self.cleared_marks, "COUNTS_INCONSISTENT", "CLEARED")
        _require(not self.active_profile_present or self.review_lookahead_days >= 0, "COUNTS_INCONSISTENT", "WINDOW")
        _require(self.active_profile_present or self.review_lookahead_days == 0, "COUNTS_INCONSISTENT", "WINDOW_WITHOUT_PROFILE")

    def content(self) -> Dict[str, Any]:
        return {"active_profile_present": self.active_profile_present, "review_lookahead_days": self.review_lookahead_days,
                "live_focus_marks": self.live_focus_marks, "live_mute_marks": self.live_mute_marks, "cleared_marks": self.cleared_marks,
                "unmatched_live_marks": self.unmatched_live_marks, "p9": self.p9.content(), "personal": list(map(list, self.personal))}

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "ReviewStateCounts":
        fields_ = require_fields(data, frozenset(f.name for f in fields(cls)), "ReviewStateCounts")
        return cls(**{**fields_, "p9": P9SafeCounts.from_dict(fields_["p9"]), "personal": tuple(tuple(p) for p in fields_["personal"])})


def check_counts_against_entries(entries: Sequence[ReviewStateEntry], counts: ReviewStateCounts, cutoff: SampleCutoff) -> None:
    """件数を項目で、view の実際の意味どおりに検算する（矛盾は INTEGRITY_FAILURE）。"""
    personal = dict(counts.personal)
    by_due = {c: sum(1 for e in entries if e.due_class is c) for c in DueClass}
    _require(personal["review_entry_count"] == len(entries), "COUNTS_INCONSISTENT", "REVIEW_ENTRY_COUNT")
    for key, due_class in (("overdue_count", DueClass.OVERDUE), ("due_count", DueClass.DUE), ("upcoming_count", DueClass.UPCOMING),
                           ("later_count", DueClass.LATER), ("no_due_date_count", DueClass.NO_DUE_DATE)):
        _require(personal[key] == by_due[due_class], "COUNTS_INCONSISTENT", key.upper())
    focus = sum(1 for e in entries if e.attention is AttentionMark.FOCUS)
    mute = sum(1 for e in entries if e.attention is AttentionMark.MUTE)
    _require(personal["focus_entry_count"] == focus, "COUNTS_INCONSISTENT", "FOCUS_ENTRY_COUNT")
    _require(personal["muted_entry_count"] == mute, "COUNTS_INCONSISTENT", "MUTED_ENTRY_COUNT")
    _require(personal["excluded_by_profile_count"] == sum(1 for e in entries if e.excluded_by_profile), "COUNTS_INCONSISTENT", "EXCLUDED_COUNT")
    _require(focus + mute + counts.unmatched_live_marks == counts.live_focus_marks + counts.live_mute_marks,
             "COUNTS_INCONSISTENT", "LIVE_MARKS_PARTITION")
    _require(not entries or counts.active_profile_present or not any(e.excluded_by_profile for e in entries),
             "COUNTS_INCONSISTENT", "EXCLUSION_WITHOUT_PROFILE")
    watches = [e for e in entries if e.record_kind is RecordKind.WATCH_ENTRY]
    theses = [e for e in entries if e.record_kind is RecordKind.THESIS]
    p9 = counts.p9
    _require(p9.watch_count == len(watches) and p9.thesis_count == len(theses), "COUNTS_INCONSISTENT", "P9_ROOT_COUNTS")

    def distribution(values) -> Counts:
        tally: Dict[str, int] = {}
        for value in values:
            tally[value] = tally.get(value, 0) + 1
        return tuple(sorted(tally.items()))

    _require(p9.watch_status_counts == distribution(e.p9_status for e in watches), "COUNTS_INCONSISTENT", "WATCH_STATUS_COUNTS")
    _require(p9.watch_provenance_kind_counts == distribution(e.p9_provenance_kind for e in watches), "COUNTS_INCONSISTENT", "WATCH_PROVENANCE_COUNTS")
    _require(p9.thesis_status_counts == distribution(e.p9_status for e in theses), "COUNTS_INCONSISTENT", "THESIS_STATUS_COUNTS")
    due = lambda rows: sum(1 for e in rows if e.review_due_on is not None and e.review_due_on <= cutoff.as_of_date)  # noqa: E731
    _require(p9.watch_review_due_count == due(watches) and p9.thesis_review_due_count == due(theses), "COUNTS_INCONSISTENT", "P9_REVIEW_DUE")
    for entry in entries:
        check_due_class(entry, cutoff, counts.review_lookahead_days)


# ---------------------------------------------------------------- 標本 ・証拠 ・結果


@dataclass(frozen=True, kw_only=True)
class ReviewStateSample:
    """cutoff で有効だった見直しの状態の標本（DERIVED ・非 authority）。identity に telemetry は入らない。"""

    cutoff: SampleCutoff
    view_identity: SourceViewIdentity
    entries: Tuple[ReviewStateEntry, ...]
    counts: ReviewStateCounts
    rules_version: str
    provenance_class: str = PROVENANCE_CLASS
    authority_class: str = AUTHORITY_CLASS
    schema_version: str = SAMPLE_SCHEMA_VERSION

    def __post_init__(self) -> None:
        _require(isinstance(self.cutoff, SampleCutoff), "SAMPLE_INVALID", "CUTOFF")
        _require(isinstance(self.view_identity, SourceViewIdentity), "SAMPLE_INVALID", "VIEW_IDENTITY")
        _require(isinstance(self.counts, ReviewStateCounts), "SAMPLE_INVALID", "COUNTS")
        _identifier(self.rules_version, "SAMPLE_INVALID")
        _require(self.provenance_class == PROVENANCE_CLASS and self.authority_class == AUTHORITY_CLASS
                 and self.schema_version == SAMPLE_SCHEMA_VERSION, "SAMPLE_INVALID", "CLASS")
        _require(isinstance(self.entries, tuple) and all(isinstance(e, ReviewStateEntry) for e in self.entries), "SAMPLE_INVALID", "ENTRIES")
        keys = [e.key for e in self.entries]
        _require(keys == sorted(keys) and len(set(keys)) == len(keys), "SAMPLE_INVALID", "ENTRY_ORDER_OR_DUPLICATE")
        roots = [e.p9_root_id for e in self.entries]
        _require(len(set(roots)) == len(roots), "SAMPLE_INVALID", "DUPLICATE_ROOT_ID")
        watch_ids = {e.p9_root_id for e in self.entries if e.record_kind is RecordKind.WATCH_ENTRY}
        for entry in self.entries:
            if entry.record_kind is RecordKind.THESIS and entry.linked_watch_entry_id in watch_ids:
                linked = next(e for e in self.entries if e.p9_root_id == entry.linked_watch_entry_id)
                _require(entry.issuer_id == linked.issuer_id, "SAMPLE_INVALID", "THESIS_ISSUER_MISMATCH")
            elif entry.record_kind is RecordKind.THESIS:
                _require(entry.issuer_id is None, "SAMPLE_INVALID", "THESIS_ISSUER_WITHOUT_LINK")

    def content(self) -> Dict[str, Any]:
        return {"schema_version": self.schema_version, "rules_version": self.rules_version, "cutoff": self.cutoff.content(),
                "view_identity": self.view_identity.content(), "entries": [e.content() for e in self.entries],
                "counts": self.counts.content(), "provenance_class": self.provenance_class, "authority_class": self.authority_class}

    @property
    def sample_digest(self) -> str:
        return domain_digest(SAMPLE_DOMAIN, self.content())

    @property
    def sample_id(self) -> str:
        return short_id(SAMPLE_ID_PREFIX, self.sample_digest)

    def to_json(self) -> str:
        return canonical_json(self.content())

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "ReviewStateSample":
        fields_ = require_fields(data, frozenset(f.name for f in fields(cls)), "ReviewStateSample")
        return cls(cutoff=SampleCutoff.from_dict(fields_["cutoff"]), view_identity=SourceViewIdentity.from_dict(fields_["view_identity"]),
                   entries=tuple(ReviewStateEntry.from_dict(e) for e in fields_["entries"]),
                   counts=ReviewStateCounts.from_dict(fields_["counts"]), rules_version=fields_["rules_version"],
                   provenance_class=fields_["provenance_class"], authority_class=fields_["authority_class"],
                   schema_version=fields_["schema_version"])


@dataclass(frozen=True, kw_only=True)
class SampleEvidence:
    """標本の telemetry（取った壁時計の時刻 ・build の参照）。identity ・内容 ・PIT の判定には使わない。known_at ではない。"""

    sample_id: str
    sample_digest: str
    sampled_at: datetime
    build_ref: str

    def __post_init__(self) -> None:
        _require(is_digest(self.sample_digest) and self.sample_id == short_id(SAMPLE_ID_PREFIX, self.sample_digest), "EVIDENCE_INVALID", "ID")
        object.__setattr__(self, "sampled_at", require_aware(self.sampled_at, "EVIDENCE_INVALID"))
        require_safe_code(self.build_ref, "EVIDENCE_INVALID")

    def content(self) -> Dict[str, str]:
        return {"sample_id": self.sample_id, "sample_digest": self.sample_digest, "sampled_at": utc_iso(self.sampled_at),
                "build_ref": self.build_ref, "telemetry": "NOT_KNOWN_AT_NOT_IDENTITY"}


@dataclass(frozen=True, kw_only=True)
class SampleOutcome:
    """標本化の結果: SAMPLED（標本あり）／ MISSING（source が無い）／ INTEGRITY_FAILURE（壊れている ・矛盾）。失敗に部分の標本は無い。"""

    status: OutcomeStatus
    failure_code: str
    sample: Optional[ReviewStateSample]

    def __post_init__(self) -> None:
        object.__setattr__(self, "status", _enum(OutcomeStatus, self.status, "OUTCOME_INVALID"))
        if self.status is OutcomeStatus.SAMPLED:
            _require(isinstance(self.sample, ReviewStateSample) and self.failure_code == "", "OUTCOME_INVALID", "SAMPLED_SHAPE")
        else:
            _require(self.sample is None, "OUTCOME_INVALID", "PARTIAL_SAMPLE")
            require_safe_code(self.failure_code, "OUTCOME_INVALID")

    @property
    def is_empty_sample(self) -> bool:
        return self.status is OutcomeStatus.SAMPLED and self.sample is not None and not self.sample.entries


def build_sample(*, cutoff: SampleCutoff, view_identity: SourceViewIdentity, entries: Sequence[ReviewStateEntry],
                 counts: ReviewStateCounts, rules_version: str) -> SampleOutcome:
    """合成（または将来 governed）の view の内容から標本を作る。矛盾 ・不正は INTEGRITY_FAILURE（部分の標本は無い）。"""
    try:
        ordered = tuple(sorted(entries, key=lambda e: e.key))
        check_counts_against_entries(ordered, counts, cutoff)
        sample = ReviewStateSample(cutoff=cutoff, view_identity=view_identity, entries=ordered, counts=counts,
                                   rules_version=rules_version)
    except (ReviewStateError, CanonicalError) as exc:
        return SampleOutcome(status=OutcomeStatus.INTEGRITY_FAILURE, failure_code=exc.code, sample=None)
    return SampleOutcome(status=OutcomeStatus.SAMPLED, failure_code="", sample=sample)


def outcome_for_source_failure(source_code: Any) -> SampleOutcome:
    """governed な view の失敗 code を結果に写す。未知の code は fail closed（INTEGRITY_FAILURE）。"""
    code = source_code if isinstance(source_code, str) and source_code else "SOURCE_FAILURE_UNCLASSIFIED"
    try:
        require_safe_code(code, "OUTCOME_INVALID")
    except CanonicalError:
        code = "SOURCE_FAILURE_UNCLASSIFIED"
    status = OutcomeStatus.MISSING if code in MISSING_SOURCE_CODES else OutcomeStatus.INTEGRITY_FAILURE
    return SampleOutcome(status=status, failure_code=code, sample=None)


# ---------------------------------------------------------------- 鮮度の label ・build の identity


def staleness_label(previous: Optional[SampleCutoff], cutoff: SampleCutoff, *, window_days: int) -> StalenessLabel:
    """人が宣言した窓（日）による label。trigger ではない。前の標本が無ければ UNDETERMINED。"""
    _nonnegative(window_days, "WINDOW_INVALID")
    _require(isinstance(cutoff, SampleCutoff), "CUTOFF_INVALID", "CUTOFF")
    if previous is None:
        return StalenessLabel.UNDETERMINED
    _require(isinstance(previous, SampleCutoff) and previous.at < cutoff.at, "CUTOFF_ORDER_INVALID", "PREVIOUS_NOT_EARLIER")
    return StalenessLabel.STALE if (cutoff.at - previous.at).days > window_days else StalenessLabel.FRESH


def build_digest(cutoffs: Sequence[SampleCutoff], view_identity: SourceViewIdentity, *, rules_version: str,
                 input_descriptors: Tuple[Tuple[str, str], ...] = ()) -> str:
    """build の identity: 明示の順序つきの cutoff の集合 ・view の identity ・規則の version ・任意の入力の記述子。telemetry は無い。
    決定論の identity は source の authority の不変を証明しない（root の manifest は任意の記述子として将来入る）。"""
    _require(isinstance(view_identity, SourceViewIdentity), "BUILD_INVALID", "VIEW_IDENTITY")
    _identifier(rules_version, "BUILD_INVALID")
    _require(len(cutoffs) >= 1 and all(isinstance(c, SampleCutoff) for c in cutoffs), "BUILD_INVALID", "CUTOFFS")
    keys = [c.sort_key() for c in cutoffs]
    _require(keys == sorted(keys) and len(set(keys)) == len(keys), "CUTOFF_ORDER_INVALID", "BUILD_CUTOFFS")
    descriptors = []
    for pair in input_descriptors:
        _require(isinstance(pair, tuple) and len(pair) == 2, "BUILD_INVALID", "DESCRIPTOR")
        descriptors.append([require_safe_code(pair[0], "BUILD_INVALID"), _identifier(pair[1], "BUILD_INVALID")])
    _require(descriptors == sorted(descriptors) and len({d[0] for d in descriptors}) == len(descriptors), "BUILD_INVALID", "DESCRIPTOR_ORDER")
    return domain_digest(BUILD_DOMAIN, {"schema_version": SAMPLE_SCHEMA_VERSION, "rules_version": rules_version,
                                        "cutoffs": [c.content() for c in cutoffs], "view_identity": view_identity.content(),
                                        "input_descriptors": descriptors})


def check_sample_ids(samples: Sequence[ReviewStateSample]) -> None:
    """複数の標本を合わせる時、短縮 id の衝突（別の完全な digest が同じ略記）を fail closed で検出する。"""
    assert_no_short_id_collision((s.sample_id, s.sample_digest) for s in samples)


for _record_kind in (SampleCutoff, SourceViewIdentity, ReviewStateEntry, P9SafeCounts, ReviewStateCounts, ReviewStateSample, SampleOutcome):
    _check_no_forbidden_fields(_record_kind)                      # schema の自己検査: 文 ・著者 ・source の時刻 ・P10 の revision ・telemetry の欄は無い


__all__ = ["AUTHORITY_CLASS", "AttentionMark", "BUILD_DOMAIN", "Counts", "DueClass", "FORBIDDEN_FIELD_NAMES", "INTEGRITY_SOURCE_CODES",
           "MISSING_SOURCE_CODES", "OutcomeStatus", "P9SafeCounts", "PERSONAL_COUNT_KEYS", "PROVENANCE_CLASS", "PitState",
           "RESERVED_PIT_STATES", "RecordKind", "ReviewStateCounts", "ReviewStateEntry", "ReviewStateError", "ReviewStateSample",
           "SAMPLE_DOMAIN", "SAMPLE_ID_PREFIX", "SAMPLE_SCHEMA_VERSION", "STRUCTURAL_FIELDS", "SampleCutoff", "SampleEvidence",
           "SampleOutcome", "SourceViewIdentity", "StalenessLabel", "SurfaceGroup", "build_digest", "build_sample",
           "check_counts_against_entries", "check_due_class", "check_sample_ids", "outcome_for_source_failure", "staleness_label"]
