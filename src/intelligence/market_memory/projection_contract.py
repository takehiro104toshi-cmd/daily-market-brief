"""P13-A4a1 — Obsidian 投影の後継の純粋な契約（public ／ private の identity の分離 ・frontmatter ・中断の staging の継続）。I/O は無い。

- **public の identity は公開する欄だけから導く**: 日付 ・承認した件数 ・承認した分類 ・schema ／ 規則の version ・序数。source の cutoff の
  瞬間 ・項目の id ・標本 ／ 変化 ／ generation ／ manifest ／ 計画の digest は public の byte ・file 名 ・link のどこにも入らない。低い entropy の
  private な入力の digest は候補の列挙で逆算できる（hash は秘匿ではない）。public の digest を逆算して得られるのは既に公開した値だけ。
- **private な binding**: public の版 ・export と、実際に検証した A3 の generation ／ manifest の完全な digest の結び付きは private な証拠の
  record（`PrivateBinding`）だけに在り、public の直列化の面には決して出ない。
- 防ぐのは digest を介した漏えいだけであり、公開する値そのもの（件数 ・日付）からの推論は防がない。
- frontmatter は P12.5-A0 §6.1 の欄を quote した値で持つ（`generated: "true"` は文字の値）。source の参照は `PRIVATE_EVIDENCE_ONLY` であり
  §6.1 の文字どおりの充足ではない（限定した逸脱 ・理由と範囲は `PHASE13_A4A1_PROJECTION_RECONCILIATION.md`）。
- 中断した staging: 検証した intent ・manifest ・対象が揃い、在る file が全て byte 一致の部分集合なら、足りない file の排他の作成だけで続ける。
  途中で切れた file は明示の保存 ・改竄 ／ 未知の entry は HOLD ・空の予約は明示の保存だけ。前の有効な版は決して動かさない。
- A4a（`memory_projection.py` ・0.1.0）は変えない。再利用は変わらない純粋な定数 ・固定の文 ・走査 ・error の class だけ。A3 の store の読みは
  証明しない（A4b が A3 の公開の読みで確立する）。
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, Mapping, Optional, Sequence, Tuple

from .canonical import CanonicalError, assert_no_short_id_collision, date_iso, domain_digest, is_digest, parse_date_iso, short_id
from .memory_generation import (MANIFEST_RECORD_NAME, MAX_PLAN_CUTOFFS, MemoryGenerationError, VerifiedGeneration, record_bytes,
                                sha256_hex, verify_generation_records)
from .memory_projection import (ABORT_REASONS, APPROVED_CATEGORY_CODES, CATEGORY_TABLE, COUNT_TABLE, DERIVED_NOTICE, HEADING_CATEGORIES,
                                HEADING_FIELDS, HEADING_IDENTITY, HEADING_INTERVALS, HEADING_KINDS, HEADING_P9, HEADING_REVIEW,
                                HEADING_SAMPLES, INTERVAL_NOTICE, KIND_TABLE, MAX_NOTE_BYTES, MAX_NOTE_LINE_CHARS, MAX_RENDERED_COUNT,
                                NO_INTERVALS_LINE, NOTE_SUFFIX, POINTER_NOTE_NAME, POINTER_NOTICE, TITLE_INDEX, TITLE_INTERVAL,
                                TITLE_POINTER, TITLE_SAMPLE, VALUE_TABLE, VERSION_NOTICE, ProjectionError, scan_private_shapes)
from .review_state_change import ChangeKind
from .review_state_sample import PERSONAL_COUNT_KEYS, PROVENANCE_CLASS, STRUCTURAL_FIELDS, RecordKind

CONTRACT_SCHEMA_VERSION = "p13_memory_projection:0.2.0"
CONTRACT_RULES_VERSION = "p13_projection_rules:0.2.0"
POINTER_SCHEMA_VERSION = "p13_projection_pointer:0.2.0"
PUBLIC_EXPORT_SCHEMA_VERSION = "p13_projection_public_export:0.2.0"
BINDING_SCHEMA_VERSION = "p13_projection_binding:0.2.0"
INTENT_SCHEMA_VERSION = "p13_projection_intent:0.2.0"
COMPLETION_SCHEMA_VERSION = "p13_projection_completion:0.2.0"
ABORT_SCHEMA_VERSION = "p13_projection_abort:0.2.0"
PUBLIC_VERSION_DOMAIN = "p13.projection_public_version.v2"
PUBLIC_NOTE_DOMAIN = "p13.projection_public_note.v2"
PUBLIC_EXPORT_DOMAIN = "p13.projection_public_export.v2"
POINTER_SLOT_DOMAIN = "p13.projection_pointer_slot.v2"
BINDING_DOMAIN = "p13.projection_binding.v2"
INTENT_DOMAIN = "p13.projection_intent.v2"
COMPLETION_DOMAIN = "p13.projection_completion.v2"
ABORT_DOMAIN = "p13.projection_abort.v2"
VERSION_PREFIX = "p13pvn_"
SAMPLE_NOTE_PREFIX = "p13psm_"
INTERVAL_NOTE_PREFIX = "p13piv_"
POINTER_SLOT_PREFIX = "p13ptr_"
GENERATED_VALUE = "true"
AUTHORITY_VALUE = "DERIVED"
NOT_AVAILABLE = "NOT_AVAILABLE"
SOURCE_REF_VALUE = "PRIVATE_EVIDENCE_ONLY"
BUILD_BASIS = "PUBLIC_EXPORT_BUILD_IDENTITY_PRIVATE_MEMORY_BUILD_WITHHELD"
AS_OF_BASIS = {"VERSION_INDEX": "GENERATION_FINAL_CUTOFF_AS_OF_DATE", "SAMPLE": "SAMPLE_CUTOFF_AS_OF_DATE",
               "INTERVAL": "INTERVAL_THROUGH_CUTOFF_AS_OF_DATE_NOT_TRANSITION_TIME", "POINTER": "POINTED_VERSION_FINAL_CUTOFF_AS_OF_DATE"}
PUBLIC_AUTHORITY_CLASS = "DERIVED_PUBLIC_COUNTS_ONLY_PROJECTION_NON_AUTHORITY"
#: 後継の再検証は呼び出し側の object から作り直した byte に対するもの（A3 の store から読んだことの証明ではない）
SOURCE_ATTESTATION = "A4A1_RECHECKED_RECORD_BYTES_STORE_READ_NOT_ATTESTED"
SOURCE_NOTICE = "source の参照 ・完全な digest は private な証拠だけに在り、この note には無い。"
MAX_EXPORT_FILES = 2 * MAX_PLAN_CUTOFFS
MAX_OBSERVED_OBJECTS = 4096

#: 結果の code（固定の定数だけ ・値 ・位置は持たない）
PROJECTION_INPUT_INVALID = "PROJECTION_INPUT_INVALID"
SOURCE_UNVERIFIED = "SOURCE_UNVERIFIED"
SOURCE_DIGEST_MISMATCH = "SOURCE_DIGEST_MISMATCH"
SCHEMA_UNSUPPORTED = "SCHEMA_UNSUPPORTED"
CATEGORY_UNAPPROVED = "CATEGORY_UNAPPROVED"
COUNT_OUT_OF_RANGE = "COUNT_OUT_OF_RANGE"
NOTE_INVALID = "NOTE_INVALID"
PRIVATE_SHAPE_DETECTED = "PRIVATE_SHAPE_DETECTED"
PUBLIC_DIGEST_INVALID = "PUBLIC_DIGEST_INVALID"
SHORT_ID_COLLISION = "SHORT_ID_COLLISION"
RECORD_CORRUPT = "RECORD_CORRUPT"
EVIDENCE_DIGEST_MISMATCH = "EVIDENCE_DIGEST_MISMATCH"
MANIFEST_MISSING = "MANIFEST_MISSING"
MANIFEST_CONFLICT = "MANIFEST_CONFLICT"
UNREFERENCED_MANIFEST = "UNREFERENCED_MANIFEST"
BINDING_MISSING = "BINDING_MISSING"
BINDING_CONFLICT = "BINDING_CONFLICT"
UNREFERENCED_BINDING = "UNREFERENCED_BINDING"
POINTER_INVALID = "POINTER_INVALID"
POINTER_MISSING = "POINTER_MISSING"
POINTER_UNEXPECTED = "POINTER_UNEXPECTED"
POINTER_WITHOUT_EVIDENCE = "POINTER_WITHOUT_EVIDENCE"
INTENT_REFERENCE_MISSING = "INTENT_REFERENCE_MISSING"
CONTRADICTORY_INTENT = "CONTRADICTORY_INTENT"
INTENT_CHAIN_INVALID = "INTENT_CHAIN_INVALID"
MULTIPLE_OPEN_INTENTS = "MULTIPLE_OPEN_INTENTS"
UNKNOWN_OBJECT = "UNKNOWN_OBJECT"
UNREFERENCED_VERSION = "UNREFERENCED_VERSION"
VERSION_UNVERIFIED = "VERSION_UNVERIFIED"
PREVIOUS_VERSION_MISSING = "PREVIOUS_VERSION_MISSING"
ORPHAN_STAGING = "ORPHAN_STAGING"
STAGING_OF_CLOSED_INTENT = "STAGING_OF_CLOSED_INTENT"
STAGING_UNVERIFIED = "STAGING_UNVERIFIED"
STAGING_TAMPERED = "STAGING_TAMPERED"
STAGING_FOREIGN_ENTRY = "STAGING_FOREIGN_ENTRY"
AMBIGUOUS_STAGING_AND_VERSION = "AMBIGUOUS_STAGING_AND_VERSION"
REPUBLICATION_OF_KNOWN_VERSION = "REPUBLICATION_OF_KNOWN_VERSION"
TARGET_CONFLICTS_WITH_OPEN_INTENT = "TARGET_CONFLICTS_WITH_OPEN_INTENT"
TARGET_REQUIRED_FOR_STAGING = "TARGET_REQUIRED_FOR_STAGING"
NO_CHANGE_BINDING_UNRECORDED = "NO_CHANGE_BINDING_UNRECORDED"
OBSERVATION_INVALID = "OBSERVATION_INVALID"
UNSAFE_RECOVERY_PROPOSAL = "UNSAFE_RECOVERY_PROPOSAL"
UNSAFE_PRESERVATION_PROPOSAL = "UNSAFE_PRESERVATION_PROPOSAL"
CONTRACT_CODES = frozenset({PROJECTION_INPUT_INVALID, SOURCE_UNVERIFIED, SOURCE_DIGEST_MISMATCH, SCHEMA_UNSUPPORTED, CATEGORY_UNAPPROVED,
                            COUNT_OUT_OF_RANGE, NOTE_INVALID, PRIVATE_SHAPE_DETECTED, PUBLIC_DIGEST_INVALID, SHORT_ID_COLLISION,
                            RECORD_CORRUPT, EVIDENCE_DIGEST_MISMATCH, MANIFEST_MISSING, MANIFEST_CONFLICT, UNREFERENCED_MANIFEST,
                            BINDING_MISSING, BINDING_CONFLICT, UNREFERENCED_BINDING, POINTER_INVALID, POINTER_MISSING, POINTER_UNEXPECTED,
                            POINTER_WITHOUT_EVIDENCE, INTENT_REFERENCE_MISSING, CONTRADICTORY_INTENT, INTENT_CHAIN_INVALID,
                            MULTIPLE_OPEN_INTENTS, UNKNOWN_OBJECT, UNREFERENCED_VERSION, VERSION_UNVERIFIED, PREVIOUS_VERSION_MISSING,
                            ORPHAN_STAGING, STAGING_OF_CLOSED_INTENT, STAGING_UNVERIFIED, STAGING_TAMPERED, STAGING_FOREIGN_ENTRY,
                            AMBIGUOUS_STAGING_AND_VERSION, REPUBLICATION_OF_KNOWN_VERSION, TARGET_CONFLICTS_WITH_OPEN_INTENT,
                            TARGET_REQUIRED_FOR_STAGING, NO_CHANGE_BINDING_UNRECORDED, OBSERVATION_INVALID, UNSAFE_RECOVERY_PROPOSAL,
                            UNSAFE_PRESERVATION_PROPOSAL})

_VIEW_FIELDS = ("personal_projection_schema_version", "p9_safe_view_schema_version", "p9_view_rules_version", "review_view_schema_version")
_REVIEW_COUNT_FIELDS = ("live_focus_marks", "live_mute_marks", "cleared_marks", "unmatched_live_marks")
_P9_SCALAR_FIELDS = ("watch_count", "watch_review_due_count", "watch_declared_thesis_link_count", "thesis_count", "thesis_review_due_count")
_INDEX_FIELDS = ("projection_schema", "projection_rules", "public_version_digest", "adapter_rules", *_VIEW_FIELDS, "sample_count",
                 "interval_count", "first_sample_cutoff_date", "last_sample_cutoff_date")
_SAMPLE_IDENTITY_FIELDS = ("sample_ordinal", "sample_cutoff_date", "active_profile_present")
_INTERVAL_IDENTITY_FIELDS = ("interval_ordinal", "after_sample_cutoff_date", "through_sample_cutoff_date", "change_record_count")
#: 表の行の先頭に在ってよい欄の名前（構造の名前だけ ・値ではない）
ALLOWED_FIELD_LABELS = frozenset(_INDEX_FIELDS + _SAMPLE_IDENTITY_FIELDS + _INTERVAL_IDENTITY_FIELDS + _REVIEW_COUNT_FIELDS
                                 + _P9_SCALAR_FIELDS + tuple(PERSONAL_COUNT_KEYS) + tuple(n for n, _ in APPROVED_CATEGORY_CODES)
                                 + STRUCTURAL_FIELDS)
ALLOWED_CODES = frozenset({code for _, codes in APPROVED_CATEGORY_CODES for code in codes} | {k.value for k in RecordKind}
                          | {k.value for k in ChangeKind})
FIXED_LINES = frozenset({TITLE_INDEX, TITLE_SAMPLE, TITLE_INTERVAL, TITLE_POINTER, *DERIVED_NOTICE, *INTERVAL_NOTICE, *VERSION_NOTICE,
                         *POINTER_NOTICE, SOURCE_NOTICE, HEADING_IDENTITY, HEADING_SAMPLES, HEADING_INTERVALS, HEADING_REVIEW,
                         HEADING_P9, HEADING_CATEGORIES, HEADING_KINDS, HEADING_FIELDS, NO_INTERVALS_LINE, *VALUE_TABLE, *COUNT_TABLE,
                         *CATEGORY_TABLE, *KIND_TABLE})
_COMMON_KEYS = ("generated", "authority", "item_id", "build_id", "p13_build_basis", "as_of", "p13_as_of_basis", "known_at",
                "acquisition_time", "p13_provenance", "p13_source_ref")
#: note の種類ごとの frontmatter の鍵の列（順序つきの完全一致）
FRONTMATTER_LAYOUTS = {
    "VERSION_INDEX": ("p13_schema", "p13_rules", "p13_note") + _COMMON_KEYS,
    "SAMPLE": ("p13_schema", "p13_rules", "p13_note") + _COMMON_KEYS + ("p13_ordinal",),
    "INTERVAL": ("p13_schema", "p13_rules", "p13_note") + _COMMON_KEYS + ("p13_ordinal",),
    "POINTER": ("p13_schema", "p13_rules", "p13_note") + _COMMON_KEYS + ("p13_export",),
}
_ITEM_PREFIXES = {"VERSION_INDEX": VERSION_PREFIX, "SAMPLE": SAMPLE_NOTE_PREFIX, "INTERVAL": INTERVAL_NOTE_PREFIX, "POINTER": POINTER_SLOT_PREFIX}
_SCHEMAS = {"VERSION_INDEX": CONTRACT_SCHEMA_VERSION, "SAMPLE": CONTRACT_SCHEMA_VERSION, "INTERVAL": CONTRACT_SCHEMA_VERSION,
            "POINTER": POINTER_SCHEMA_VERSION}
_FIXED_VALUES = {"p13_rules": CONTRACT_RULES_VERSION, "generated": GENERATED_VALUE, "authority": AUTHORITY_VALUE,
                 "p13_build_basis": BUILD_BASIS, "known_at": NOT_AVAILABLE, "acquisition_time": NOT_AVAILABLE,
                 "p13_provenance": PROVENANCE_CLASS, "p13_source_ref": SOURCE_REF_VALUE}
_CONTROL_RE = re.compile(r"[\x00-\x09\x0b-\x1f\x7f-\x9f­؜᠎​-‏ -‮⁠-⁤⁦-⁯﻿￹-￻]")
_FRONTMATTER_LINE_RE = re.compile(r'^([a-z][a-z0-9_]{1,31}): "([^"\\]{1,128})"$')
_TABLE_ROW_RE = re.compile(r"^\| ([^|]{1,128}) \| ([^|]{1,128}) \|(?: ([^|]{1,128}) \|)?$")
_LINK_ITEM_RE = re.compile(r"^- \[\[(p13pvn_[0-9a-f]{24})(-[si][0-9]{3})?\]\]$")
_NOTE_NAME_RE = re.compile(r"^(p13pvn_[0-9a-f]{24})(?:-([si])([0-9]{3}))?\.md$")
_VERSION_LABEL_RE = re.compile(r"^p13pvn_[0-9a-f]{24}$")
_ITEM_ID_RE = re.compile(r"^(p13(?:pvn|psm|piv|ptr)_)([0-9a-f]{64})$")
_HEX_RUN_RE = re.compile(r"(?<![0-9a-f])[0-9a-f]{16,}(?![0-9a-f])")
_INT_CELL_RE = re.compile(r"^(?:0|[1-9][0-9]{0,3})$")
_DATE_RE = re.compile(r"^[0-9]{4}-[0-9]{2}-[0-9]{2}$")
_ORDINAL_RE = re.compile(r"^[0-9]{3}$")
_VERSION_CELL_RE = re.compile(r"^[a-z][a-z0-9_]{0,63}:[0-9]{1,3}\.[0-9]{1,3}\.[0-9]{1,3}$")
_POINTER_FIELD_RE = re.compile(r'^(build_id|as_of|p13_export): "([0-9a-f]{64}|[0-9]{4}-[0-9]{2}-[0-9]{2})"$')


def _require(condition: Any, code: str, detail: str = "") -> None:
    if not condition:
        raise ProjectionError(code, detail)


def _no_collision(pairs: Sequence[Tuple[str, str]]) -> None:
    try:
        assert_no_short_id_collision(sorted(pairs))
    except CanonicalError:
        raise ProjectionError(SHORT_ID_COLLISION, "LABEL") from None


def _count(value: Any) -> int:
    _require(type(value) is int and 0 <= value <= MAX_RENDERED_COUNT, COUNT_OUT_OF_RANGE, "COUNT")
    return value


def _date_text(value: Any, code: str = PROJECTION_INPUT_INVALID) -> str:
    _require(isinstance(value, str) and _DATE_RE.match(value) is not None, code, "DATE")
    try:
        parse_date_iso(value)
    except (CanonicalError, ValueError):
        raise ProjectionError(code, "DATE") from None
    return value


def _version_text(value: Any) -> str:
    _require(isinstance(value, str) and _VERSION_CELL_RE.match(value) is not None, PROJECTION_INPUT_INVALID, "VERSION_LABEL")
    return value


def _review_order() -> Tuple[str, ...]:
    return _REVIEW_COUNT_FIELDS + tuple(sorted(PERSONAL_COUNT_KEYS))


class NoteKind(str, Enum):
    VERSION_INDEX = "VERSION_INDEX"
    SAMPLE = "SAMPLE"
    INTERVAL = "INTERVAL"
    POINTER = "POINTER"


class PublicationState(str, Enum):
    """観測した byte の分類（完了を記録した状態は PUBLISHED_VERIFIED ・中断は開いた intent の状態か FAIL_CLOSED）。"""

    FIRST_PUBLICATION = "FIRST_PUBLICATION"
    PUBLISHED_VERIFIED = "PUBLISHED_VERIFIED"
    NO_CHANGE = "NO_CHANGE"
    INTENT_PREPARED = "INTENT_PREPARED"
    STAGING_PARTIAL_VERIFIED = "STAGING_PARTIAL_VERIFIED"
    STAGING_TORN = "STAGING_TORN"
    STAGED_VERIFIED = "STAGED_VERIFIED"
    VERSION_RESERVED_EMPTY = "VERSION_RESERVED_EMPTY"
    VERSION_VERIFIED = "VERSION_VERIFIED"
    POINTER_SWITCHED = "POINTER_SWITCHED"
    STAGING_OF_CLOSED_INTENT = "STAGING_OF_CLOSED_INTENT"
    FAIL_CLOSED = "FAIL_CLOSED"


class ProposedAction(str, Enum):
    """提案するだけの次の 1 つの遷移。前の有効な版を archive ・削除 ・移動する action は存在しない。"""

    NONE = "NONE"
    PREPARE_INTENT = "PREPARE_INTENT"
    RECORD_PRIVATE_BINDING = "RECORD_PRIVATE_BINDING"
    STAGE_VERSION = "STAGE_VERSION"
    CONTINUE_STAGING = "CONTINUE_STAGING"
    MOVE_STAGED_TO_VERSION = "MOVE_STAGED_TO_VERSION"
    REPLACE_POINTER = "REPLACE_POINTER"
    RECORD_COMPLETION = "RECORD_COMPLETION"
    PRESERVE_STAGING = "PRESERVE_STAGING"
    PRESERVE_EMPTY_RESERVATION = "PRESERVE_EMPTY_RESERVATION"
    HOLD = "HOLD"


class RecoveryEligibility(str, Enum):
    NOT_REQUIRED = "NOT_REQUIRED"
    AUTO_CONVERGE_ELIGIBLE = "AUTO_CONVERGE_ELIGIBLE"
    EXPLICIT_PRESERVATION_ONLY = "EXPLICIT_PRESERVATION_ONLY"
    HOLD_FAIL_CLOSED = "HOLD_FAIL_CLOSED"


#: 自動の収束の候補（検証済みの開いた intent の続きだけ）・人の明示の保存だけの候補（自動では決して進めない）
AUTO_CONVERGE_ACTIONS = (ProposedAction.STAGE_VERSION, ProposedAction.CONTINUE_STAGING, ProposedAction.MOVE_STAGED_TO_VERSION,
                         ProposedAction.REPLACE_POINTER, ProposedAction.RECORD_COMPLETION)
EXPLICIT_PRESERVATION_ACTIONS = (ProposedAction.PRESERVE_STAGING, ProposedAction.PRESERVE_EMPTY_RESERVATION)
PRESERVE_AREA_STAGING = "STAGING"
PRESERVE_AREA_RESERVATION = "VERSION_RESERVATION"
EVIDENCE_PUBLIC_EXPORT = "PUBLIC_EXPORT"
EVIDENCE_PRIVATE_BINDING = "PRIVATE_BINDING"
EVIDENCE_INTENT = "INTENT"
EVIDENCE_COMPLETION = "COMPLETION"
EVIDENCE_ABORT = "ABORT"


# ---------------------------------------------------------------- private な入力（明示の完全な digest ・純粋な再検証）


@dataclass(frozen=True, kw_only=True)
class PrivateSourceInput:
    """明示の完全な generation ／ manifest の digest と、byte から純粋に再検証した generation（private ・public の面には出ない）。"""

    verified: VerifiedGeneration = field(repr=False)
    generation_digest: str = field(repr=False)
    manifest_digest: str = field(repr=False)
    source_attestation: str = SOURCE_ATTESTATION

    def __post_init__(self) -> None:
        _require(isinstance(self.verified, VerifiedGeneration), PROJECTION_INPUT_INVALID, "VERIFIED")
        _require(is_digest(self.generation_digest) and is_digest(self.manifest_digest), PROJECTION_INPUT_INVALID, "FULL_DIGEST_REQUIRED")
        _require(self.source_attestation == SOURCE_ATTESTATION, PROJECTION_INPUT_INVALID, "ATTESTATION")
        try:
            claimed = self.verified.generation.generation_digest
            records = dict(self.verified.generation.records())
            records[MANIFEST_RECORD_NAME] = self.verified.manifest.to_bytes()
        except MemoryGenerationError as exc:
            raise ProjectionError(SCHEMA_UNSUPPORTED if exc.code == SCHEMA_UNSUPPORTED else SOURCE_UNVERIFIED, exc.code) from None
        except (AttributeError, TypeError, ValueError):
            raise ProjectionError(SOURCE_UNVERIFIED, "RECORDS") from None
        _require(claimed == self.generation_digest, SOURCE_DIGEST_MISMATCH, "GENERATION_DIGEST")
        try:
            rechecked = verify_generation_records(records, expected_generation_digest=self.generation_digest)
        except MemoryGenerationError as exc:
            raise ProjectionError(SCHEMA_UNSUPPORTED if exc.code == SCHEMA_UNSUPPORTED else SOURCE_UNVERIFIED, exc.code) from None
        _require(rechecked.manifest == self.verified.manifest, SOURCE_UNVERIFIED, "MANIFEST")
        _require(rechecked.manifest_digest == self.manifest_digest, SOURCE_DIGEST_MISMATCH, "MANIFEST_DIGEST")
        object.__setattr__(self, "verified", rechecked)                      # 以後は byte から作り直した model だけを使う


# ---------------------------------------------------------------- public な model（公開する欄だけ ・private な digest は持たない）


@dataclass(frozen=True, kw_only=True)
class PublicSample:
    """1 つの標本の公開する欄（序数 ・cutoff の日 ・件数 ・承認した分類の件数）。cutoff の瞬間 ・項目 ・digest は持たない。"""

    ordinal: int
    as_of_date: str
    active_profile_present: bool
    review_counts: Tuple[Tuple[str, int], ...]
    p9_counts: Tuple[Tuple[str, int], ...]
    category_counts: Tuple[Tuple[str, str, int], ...]

    def __post_init__(self) -> None:
        _require(type(self.ordinal) is int and 1 <= self.ordinal <= MAX_PLAN_CUTOFFS, PROJECTION_INPUT_INVALID, "SAMPLE_ORDINAL")
        _date_text(self.as_of_date)
        _require(type(self.active_profile_present) is bool, PROJECTION_INPUT_INVALID, "ACTIVE_PROFILE")
        _require(isinstance(self.review_counts, tuple) and tuple(n for n, _ in self.review_counts) == _review_order(),
                 PROJECTION_INPUT_INVALID, "REVIEW_FIELDS")
        _require(isinstance(self.p9_counts, tuple) and tuple(n for n, _ in self.p9_counts) == _P9_SCALAR_FIELDS,
                 PROJECTION_INPUT_INVALID, "P9_FIELDS")
        expected = tuple((name, code) for name, codes in APPROVED_CATEGORY_CODES for code in codes)
        _require(isinstance(self.category_counts, tuple) and tuple((f, c) for f, c, _ in self.category_counts) == expected,
                 CATEGORY_UNAPPROVED, "CATEGORY_LAYOUT")
        for value in [v for _, v in self.review_counts + self.p9_counts] + [v for _, _, v in self.category_counts]:
            _count(value)

    def content(self) -> Dict[str, Any]:
        return {"ordinal": self.ordinal, "as_of_date": self.as_of_date, "active_profile_present": self.active_profile_present,
                "review_counts": [list(p) for p in self.review_counts], "p9_counts": [list(p) for p in self.p9_counts],
                "category_counts": [list(p) for p in self.category_counts]}


@dataclass(frozen=True, kw_only=True)
class PublicInterval:
    """隣接する 2 つの標本の端点の差の公開する欄（序数 ・2 つの日 ・件数）。遷移の時刻 ・項目 ・digest は持たない。"""

    ordinal: int
    after_date: str
    through_date: str
    change_record_count: int
    kind_counts: Tuple[Tuple[str, str, int], ...]
    field_counts: Tuple[Tuple[str, int], ...]

    def __post_init__(self) -> None:
        _require(type(self.ordinal) is int and 1 <= self.ordinal < MAX_PLAN_CUTOFFS, PROJECTION_INPUT_INVALID, "INTERVAL_ORDINAL")
        _require(_date_text(self.after_date) <= _date_text(self.through_date), PROJECTION_INPUT_INVALID, "INTERVAL_DATES")
        _count(self.change_record_count)
        expected = tuple((r.value, k.value) for r in RecordKind for k in ChangeKind)
        _require(isinstance(self.kind_counts, tuple) and tuple((r, k) for r, k, _ in self.kind_counts) == expected,
                 PROJECTION_INPUT_INVALID, "KIND_LAYOUT")
        _require(isinstance(self.field_counts, tuple) and tuple(n for n, _ in self.field_counts) == tuple(sorted(STRUCTURAL_FIELDS)),
                 PROJECTION_INPUT_INVALID, "FIELD_LAYOUT")
        for value in [v for _, _, v in self.kind_counts] + [v for _, v in self.field_counts]:
            _count(value)
        _require(sum(v for _, _, v in self.kind_counts) == self.change_record_count, PROJECTION_INPUT_INVALID, "KIND_SUM")

    def content(self) -> Dict[str, Any]:
        return {"ordinal": self.ordinal, "after_date": self.after_date, "through_date": self.through_date,
                "change_record_count": self.change_record_count, "kind_counts": [list(p) for p in self.kind_counts],
                "field_counts": [list(p) for p in self.field_counts]}


@dataclass(frozen=True, kw_only=True)
class PublicVersion:
    """公開する版の model（public の identity の唯一の入力）。全ての欄は note に印字され、ここからだけ描画する。"""

    adapter_rules_version: str
    view_versions: Tuple[Tuple[str, str], ...]
    public_samples: Tuple[PublicSample, ...]
    public_intervals: Tuple[PublicInterval, ...]

    def __post_init__(self) -> None:
        _version_text(self.adapter_rules_version)
        _require(isinstance(self.view_versions, tuple) and tuple(n for n, _ in self.view_versions) == _VIEW_FIELDS,
                 PROJECTION_INPUT_INVALID, "VIEW_FIELDS")
        for _, value in self.view_versions:
            _version_text(value)
        samples, intervals = self.public_samples, self.public_intervals
        _require(isinstance(samples, tuple) and 1 <= len(samples) <= MAX_PLAN_CUTOFFS
                 and all(isinstance(s, PublicSample) for s in samples), PROJECTION_INPUT_INVALID, "SAMPLES")
        _require([s.ordinal for s in samples] == list(range(1, len(samples) + 1)), PROJECTION_INPUT_INVALID, "SAMPLE_ORDER")
        _require(all(a.as_of_date <= b.as_of_date for a, b in zip(samples, samples[1:])), PROJECTION_INPUT_INVALID, "SAMPLE_DATES")
        _require(isinstance(intervals, tuple) and len(intervals) == len(samples) - 1
                 and all(isinstance(i, PublicInterval) for i in intervals), PROJECTION_INPUT_INVALID, "INTERVALS")
        for interval, (earlier, later) in zip(intervals, zip(samples, samples[1:])):
            _require(interval.ordinal == earlier.ordinal and interval.after_date == earlier.as_of_date
                     and interval.through_date == later.as_of_date, PROJECTION_INPUT_INVALID, "INTERVAL_ENDPOINTS")

    def content(self) -> Dict[str, Any]:
        return {"schema_version": CONTRACT_SCHEMA_VERSION, "rules_version": CONTRACT_RULES_VERSION, "authority_class": PUBLIC_AUTHORITY_CLASS,
                "adapter_rules_version": self.adapter_rules_version, "view_versions": [list(p) for p in self.view_versions],
                "samples": [s.content() for s in self.public_samples], "intervals": [i.content() for i in self.public_intervals]}

    @property
    def public_version_digest(self) -> str:
        return domain_digest(PUBLIC_VERSION_DOMAIN, self.content())

    @property
    def version_label(self) -> str:
        return short_id(VERSION_PREFIX, self.public_version_digest)

    @property
    def final_as_of_date(self) -> str:
        return self.public_samples[-1].as_of_date


def public_note_identity(public_version_digest: str, kind: str, ordinal: int) -> str:
    """生成した note の identity（public の版 ・種類 ・序数だけ）。source の事実 ・private な authority の record の identity ではない。"""
    _require(is_digest(public_version_digest) and kind in ("VERSION_INDEX", "SAMPLE", "INTERVAL") and type(ordinal) is int,
             PUBLIC_DIGEST_INVALID, "NOTE_IDENTITY")
    return domain_digest(PUBLIC_NOTE_DOMAIN, {"schema_version": CONTRACT_SCHEMA_VERSION, "rules_version": CONTRACT_RULES_VERSION,
                                              "public_version_digest": public_version_digest, "note": kind, "ordinal": ordinal})


def pointer_slot_identity() -> str:
    """pointer の slot 自身の決定論の identity（指す版 ・source に依らない定数）。"""
    return domain_digest(POINTER_SLOT_DOMAIN, {"schema_version": POINTER_SCHEMA_VERSION, "rules_version": CONTRACT_RULES_VERSION,
                                               "note_name": POINTER_NOTE_NAME})


def public_version_of(source: PrivateSourceInput) -> PublicVersion:
    """再検証した generation から公開する欄だけを取り出す（項目 ・瞬間 ・private な digest は public の model に入らない）。"""
    _require(isinstance(source, PrivateSourceInput), PROJECTION_INPUT_INVALID, "SOURCE")
    generation = source.verified.generation
    view = generation.view_identity.content()
    _require(set(view) == set(_VIEW_FIELDS), PROJECTION_INPUT_INVALID, "VIEW_FIELDS")
    public_samples = []
    for ordinal, sample in enumerate(generation.samples, 1):
        counts = sample.counts.content()
        p9 = counts["p9"]
        personal = dict(sample.counts.personal)
        _require(set(personal) == PERSONAL_COUNT_KEYS, PROJECTION_INPUT_INVALID, "PERSONAL_FIELDS")
        _require(set(p9) == set(_P9_SCALAR_FIELDS) | {name for name, _ in APPROVED_CATEGORY_CODES}, PROJECTION_INPUT_INVALID, "P9_FIELDS")
        categories = []
        for name, codes in APPROVED_CATEGORY_CODES:
            observed = {pair[0]: pair[1] for pair in p9[name]}
            _require(set(observed) <= set(codes), CATEGORY_UNAPPROVED, name.upper())
            categories += [(name, code, _count(observed.get(code, 0))) for code in codes]
        review = tuple((name, _count(counts[name])) for name in _REVIEW_COUNT_FIELDS)
        review += tuple((name, _count(personal[name])) for name in sorted(PERSONAL_COUNT_KEYS))
        public_samples.append(PublicSample(ordinal=ordinal, as_of_date=date_iso(sample.cutoff.as_of_date),
                                           active_profile_present=counts["active_profile_present"], review_counts=review,
                                           p9_counts=tuple((name, _count(p9[name])) for name in _P9_SCALAR_FIELDS),
                                           category_counts=tuple(categories)))
    public_intervals, accounted = [], 0
    for ordinal, (earlier, later) in enumerate(zip(generation.samples, generation.samples[1:]), 1):
        changes = [c for c in generation.changes
                   if c.from_sample_digest == earlier.sample_digest and c.to_sample_digest == later.sample_digest]
        accounted += len(changes)
        by_kind = {(r.value, k.value): 0 for r in RecordKind for k in ChangeKind}
        by_field = {name: 0 for name in STRUCTURAL_FIELDS}
        for change in changes:
            by_kind[(change.record_kind.value, change.kind.value)] += 1
            for item in change.changed_fields:                               # 欄の名前だけを数える（前後の値は読まない）
                by_field[item[0]] += 1
        public_intervals.append(PublicInterval(
            ordinal=ordinal, after_date=date_iso(earlier.cutoff.as_of_date), through_date=date_iso(later.cutoff.as_of_date),
            change_record_count=_count(len(changes)), kind_counts=tuple((r, k, _count(n)) for (r, k), n in by_kind.items()),
            field_counts=tuple((name, _count(by_field[name])) for name in sorted(STRUCTURAL_FIELDS))))
    _require(accounted == len(generation.changes), SOURCE_UNVERIFIED, "CHANGES_UNACCOUNTED")
    return PublicVersion(adapter_rules_version=generation.adapter_rules_version,
                         view_versions=tuple((name, view[name]) for name in _VIEW_FIELDS),
                         public_samples=tuple(public_samples), public_intervals=tuple(public_intervals))


# ---------------------------------------------------------------- public な Markdown（public な model だけから描画する）


def _frontmatter(kind: str, *, build_id: str, item_hex: str, as_of: str, extra: Mapping[str, str]) -> list:
    values = {**_FIXED_VALUES, "p13_schema": _SCHEMAS[kind], "p13_note": kind, "item_id": _ITEM_PREFIXES[kind] + item_hex,
              "build_id": build_id, "as_of": as_of, "p13_as_of_basis": AS_OF_BASIS[kind], **extra}
    return ["---", *(f'{key}: "{values[key]}"' for key in FRONTMATTER_LAYOUTS[kind]), "---"]


def _table(header: Tuple[str, str], rows: Sequence[Tuple[str, ...]]) -> list:
    return [header[0], header[1], *("| " + " | ".join(cells) + " |" for cells in rows)]


def _note_bytes(lines: Sequence[str], name: str) -> bytes:
    data = ("\n".join(lines) + "\n").encode("utf-8")
    validate_public_note(data, name=name)
    return data


def note_name(label: str, kind: str, ordinal: int) -> str:
    _require(isinstance(label, str) and _VERSION_LABEL_RE.match(label) is not None, NOTE_INVALID, "LABEL")
    if kind == "VERSION_INDEX":
        return label + NOTE_SUFFIX
    return f"{label}-{'s' if kind == 'SAMPLE' else 'i'}{ordinal:03d}{NOTE_SUFFIX}"


def _link(name: str) -> str:
    return f"- [[{name[:-len(NOTE_SUFFIX)]}]]"


def _bool_text(value: bool) -> str:
    return "true" if value else "false"


def _render_sample(version: PublicVersion, sample: PublicSample) -> Tuple[str, bytes]:
    digest = version.public_version_digest
    name = note_name(version.version_label, "SAMPLE", sample.ordinal)
    identity = [("sample_ordinal", str(sample.ordinal)), ("sample_cutoff_date", sample.as_of_date),
                ("active_profile_present", _bool_text(sample.active_profile_present))]
    return name, _note_bytes([*_frontmatter("SAMPLE", build_id=digest, item_hex=public_note_identity(digest, "SAMPLE", sample.ordinal),
                                            as_of=sample.as_of_date, extra={"p13_ordinal": f"{sample.ordinal:03d}"}),
                              "", TITLE_SAMPLE, "", *DERIVED_NOTICE, SOURCE_NOTICE, "", HEADING_IDENTITY, "", *_table(VALUE_TABLE, identity),
                              "", HEADING_REVIEW, "", *_table(COUNT_TABLE, [(n, str(v)) for n, v in sample.review_counts]),
                              "", HEADING_P9, "", *_table(COUNT_TABLE, [(n, str(v)) for n, v in sample.p9_counts]),
                              "", HEADING_CATEGORIES, "", *_table(CATEGORY_TABLE, [(f, c, str(v)) for f, c, v in sample.category_counts])],
                             name)


def _render_interval(version: PublicVersion, interval: PublicInterval) -> Tuple[str, bytes]:
    digest = version.public_version_digest
    name = note_name(version.version_label, "INTERVAL", interval.ordinal)
    identity = [("interval_ordinal", str(interval.ordinal)), ("after_sample_cutoff_date", interval.after_date),
                ("through_sample_cutoff_date", interval.through_date), ("change_record_count", str(interval.change_record_count))]
    return name, _note_bytes([*_frontmatter("INTERVAL", build_id=digest,
                                            item_hex=public_note_identity(digest, "INTERVAL", interval.ordinal),
                                            as_of=interval.through_date, extra={"p13_ordinal": f"{interval.ordinal:03d}"}),
                              "", TITLE_INTERVAL, "", *DERIVED_NOTICE, *INTERVAL_NOTICE, SOURCE_NOTICE, "", HEADING_IDENTITY, "",
                              *_table(VALUE_TABLE, identity), "", HEADING_KINDS, "",
                              *_table(KIND_TABLE, [(r, k, str(v)) for r, k, v in interval.kind_counts]), "", HEADING_FIELDS, "",
                              *_table(COUNT_TABLE, [(n, str(v)) for n, v in interval.field_counts])], name)


def _render_index(version: PublicVersion, sample_names: Sequence[str], interval_names: Sequence[str]) -> Tuple[str, bytes]:
    digest = version.public_version_digest
    name = note_name(version.version_label, "VERSION_INDEX", 0)
    rows = [("projection_schema", CONTRACT_SCHEMA_VERSION), ("projection_rules", CONTRACT_RULES_VERSION),
            ("public_version_digest", digest), ("adapter_rules", version.adapter_rules_version), *version.view_versions,
            ("sample_count", str(len(version.public_samples))), ("interval_count", str(len(version.public_intervals))),
            ("first_sample_cutoff_date", version.public_samples[0].as_of_date), ("last_sample_cutoff_date", version.final_as_of_date)]
    intervals = [_link(n) for n in interval_names] or [NO_INTERVALS_LINE]
    return name, _note_bytes([*_frontmatter("VERSION_INDEX", build_id=digest, item_hex=public_note_identity(digest, "VERSION_INDEX", 0),
                                            as_of=version.final_as_of_date, extra={}),
                              "", TITLE_INDEX, "", *DERIVED_NOTICE, *VERSION_NOTICE, SOURCE_NOTICE, "", HEADING_IDENTITY, "",
                              *_table(VALUE_TABLE, rows), "", HEADING_SAMPLES, "", *(_link(n) for n in sample_names), "",
                              HEADING_INTERVALS, "", *intervals], name)


# ---------------------------------------------------------------- public な export の manifest ・版 ・pointer


@dataclass(frozen=True, kw_only=True)
class PublicFile:
    name: str
    size: int
    sha256: str

    def __post_init__(self) -> None:
        _require(isinstance(self.name, str) and _NOTE_NAME_RE.match(self.name) is not None, RECORD_CORRUPT, "PUBLIC_FILE_NAME")
        _require(type(self.size) is int and 0 < self.size <= MAX_NOTE_BYTES, RECORD_CORRUPT, "PUBLIC_FILE_SIZE")
        _require(is_digest(self.sha256), RECORD_CORRUPT, "PUBLIC_FILE_SHA256")


@dataclass(frozen=True, kw_only=True)
class PublicExportManifest:
    """公開する版の folder の全 note の名前 ・長さ ・sha256 と public の版の digest だけ（private な digest は無い）。"""

    public_version_digest: str
    as_of_date: str
    files: Tuple[PublicFile, ...]
    rules_version: str = CONTRACT_RULES_VERSION
    schema_version: str = PUBLIC_EXPORT_SCHEMA_VERSION

    def __post_init__(self) -> None:
        _require(self.schema_version == PUBLIC_EXPORT_SCHEMA_VERSION and self.rules_version == CONTRACT_RULES_VERSION,
                 SCHEMA_UNSUPPORTED, "PUBLIC_EXPORT")
        _require(is_digest(self.public_version_digest), RECORD_CORRUPT, "PUBLIC_VERSION_DIGEST")
        _date_text(self.as_of_date, RECORD_CORRUPT)
        _require(isinstance(self.files, tuple) and all(isinstance(f, PublicFile) for f in self.files), RECORD_CORRUPT, "PUBLIC_FILES")
        names = [f.name for f in self.files]
        _require(1 <= len(names) <= MAX_EXPORT_FILES and names == sorted(names) and len(set(names)) == len(names), RECORD_CORRUPT,
                 "PUBLIC_FILE_ORDER")
        _require(all(_NOTE_NAME_RE.match(n).group(1) == self.version_label for n in names), RECORD_CORRUPT, "PUBLIC_FILE_LABEL")
        _require(self.version_label + NOTE_SUFFIX in names, RECORD_CORRUPT, "PUBLIC_INDEX")

    @property
    def version_label(self) -> str:
        return short_id(VERSION_PREFIX, self.public_version_digest)

    def content(self) -> Dict[str, Any]:
        return {"schema_version": self.schema_version, "rules_version": self.rules_version,
                "public_version_digest": self.public_version_digest, "as_of_date": self.as_of_date,
                "files": [[f.name, f.size, f.sha256] for f in self.files]}

    def to_public_bytes(self) -> bytes:
        return record_bytes(self.content())

    @property
    def public_export_digest(self) -> str:
        return domain_digest(PUBLIC_EXPORT_DOMAIN, self.content())


@dataclass(frozen=True, kw_only=True)
class PublicExport:
    """public な model だけから決定論で描画した版（note の byte と public な manifest）。同じ公開の欄からは byte 一致。"""

    public_version: PublicVersion
    notes: Tuple[Tuple[str, bytes], ...] = field(repr=False)
    manifest: PublicExportManifest

    def __post_init__(self) -> None:
        _require(isinstance(self.public_version, PublicVersion) and isinstance(self.manifest, PublicExportManifest),
                 PROJECTION_INPUT_INVALID, "PUBLIC_EXPORT")
        _require(self.manifest.public_version_digest == self.public_version.public_version_digest
                 and self.manifest.as_of_date == self.public_version.final_as_of_date, MANIFEST_CONFLICT, "PUBLIC_EXPORT_VERSION")
        _require(isinstance(self.notes, tuple), PROJECTION_INPUT_INVALID, "NOTES")
        _verify_files(dict(self.notes), self.manifest, MANIFEST_CONFLICT)

    def note_map(self) -> Dict[str, bytes]:
        return dict(self.notes)

    @property
    def public_export_digest(self) -> str:
        return self.manifest.public_export_digest

    @property
    def version_label(self) -> str:
        return self.manifest.version_label

    def pointer_note(self) -> bytes:
        return render_pointer(self.manifest)


def render_public_export(version: PublicVersion) -> PublicExport:
    """public な model だけから版を描画する（標本 ・区間 ・index の note）。全ての note は文法 ・走査 ・public の digest の検査を通る。"""
    _require(isinstance(version, PublicVersion), PROJECTION_INPUT_INVALID, "PUBLIC_VERSION")
    notes: Dict[str, bytes] = {}
    sample_names, interval_names = [], []
    for sample in version.public_samples:
        name, data = _render_sample(version, sample)
        notes[name] = data
        sample_names.append(name)
    for interval in version.public_intervals:
        name, data = _render_interval(version, interval)
        notes[name] = data
        interval_names.append(name)
    name, data = _render_index(version, sample_names, interval_names)
    notes[name] = data
    ordered = tuple(sorted(notes.items()))
    manifest = PublicExportManifest(public_version_digest=version.public_version_digest, as_of_date=version.final_as_of_date,
                                    files=tuple(PublicFile(name=n, size=len(d), sha256=sha256_hex(d)) for n, d in ordered))
    return PublicExport(public_version=version, notes=ordered, manifest=manifest)


def _pointer_bytes(public_version_digest: str, public_export_digest: str, as_of_date: str) -> bytes:
    _require(is_digest(public_version_digest) and is_digest(public_export_digest), POINTER_INVALID, "DIGESTS")
    label = short_id(VERSION_PREFIX, public_version_digest)
    return _note_bytes([*_frontmatter("POINTER", build_id=public_version_digest, item_hex=pointer_slot_identity(),
                                      as_of=_date_text(as_of_date, POINTER_INVALID), extra={"p13_export": public_export_digest}),
                        "", TITLE_POINTER, "", *POINTER_NOTICE, SOURCE_NOTICE, "", _link(label + NOTE_SUFFIX)], POINTER_NOTE_NAME)


def render_pointer(manifest: PublicExportManifest) -> bytes:
    _require(isinstance(manifest, PublicExportManifest), POINTER_INVALID, "MANIFEST")
    return _pointer_bytes(manifest.public_version_digest, manifest.public_export_digest, manifest.as_of_date)


@dataclass(frozen=True, kw_only=True)
class PointerRecord:
    public_version_digest: str
    public_export_digest: str
    as_of_date: str

    @property
    def version_label(self) -> str:
        return short_id(VERSION_PREFIX, self.public_version_digest)


def parse_pointer(data: Any) -> PointerRecord:
    """pointer の厳密な読み: public な 3 つの欄を取り出し、作り直した byte と完全一致すること（それ以外は POINTER_INVALID）。"""
    _require(isinstance(data, bytes) and 0 < len(data) <= MAX_NOTE_BYTES, POINTER_INVALID, "BYTES")
    try:
        lines = data.decode("utf-8").split("\n")
    except UnicodeDecodeError:
        raise ProjectionError(POINTER_INVALID, "UTF8") from None
    found: Dict[str, str] = {}
    for line in lines[1:len(FRONTMATTER_LAYOUTS["POINTER"]) + 1]:
        match = _POINTER_FIELD_RE.match(line)
        if match is not None:
            found[match.group(1)] = match.group(2)
    _require(set(found) == {"build_id", "as_of", "p13_export"}, POINTER_INVALID, "FIELDS")
    try:
        expected = _pointer_bytes(found["build_id"], found["p13_export"], found["as_of"])
    except ProjectionError:
        raise ProjectionError(POINTER_INVALID, "RENDER") from None
    _require(expected == data, POINTER_INVALID, "NON_CANONICAL")
    return PointerRecord(public_version_digest=found["build_id"], public_export_digest=found["p13_export"], as_of_date=found["as_of"])


# ---------------------------------------------------------------- 文法 ・private の形 ・public の digest の正の検査


@dataclass(frozen=True, kw_only=True)
class NoteParts:
    kind: str
    frontmatter: Tuple[Tuple[str, str], ...]
    rows: Tuple[Tuple[str, ...], ...]
    links: Tuple[str, ...]

    def value(self, key: str) -> str:
        return dict(self.frontmatter)[key]


def _cell_ok(cell: str) -> bool:
    if cell in ALLOWED_FIELD_LABELS or cell in ALLOWED_CODES or cell in ("true", "false"):
        return True
    if _INT_CELL_RE.match(cell) or is_digest(cell) or _VERSION_CELL_RE.match(cell):
        return True
    if _DATE_RE.match(cell):
        try:
            parse_date_iso(cell)
        except (CanonicalError, ValueError):
            return False
        return True
    return False


def _frontmatter_value_ok(kind: str, key: str, value: str) -> bool:
    if key in _FIXED_VALUES:
        return value == _FIXED_VALUES[key]
    if key == "p13_schema":
        return value == _SCHEMAS[kind]
    if key == "p13_note":
        return value == kind
    if key == "item_id":
        match = _ITEM_ID_RE.match(value)
        return match is not None and match.group(1) == _ITEM_PREFIXES[kind]
    if key in ("build_id", "p13_export"):
        return is_digest(value)
    if key == "as_of":
        try:
            return _date_text(value, NOTE_INVALID) == value
        except ProjectionError:
            return False
    if key == "p13_as_of_basis":
        return value == AS_OF_BASIS[kind]
    if key == "p13_ordinal":
        return _ORDINAL_RE.match(value) is not None and 1 <= int(value) <= MAX_PLAN_CUTOFFS
    return False


def validate_public_note(data: Any, *, name: Optional[str] = None) -> NoteParts:
    """byte の規則 → private の形の走査 → frontmatter の完全一致 → 本文の文法 → public の digest の正の検査（16 hex 以上の列は全て
    この note の公開の欄から再計算できる値だけ）→ file 名との整合。外れれば fail closed。"""
    _require(isinstance(data, bytes) and 0 < len(data) <= MAX_NOTE_BYTES, NOTE_INVALID, "SIZE")
    _require(not data.startswith(b"\xef\xbb\xbf"), NOTE_INVALID, "BOM")
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        raise ProjectionError(NOTE_INVALID, "UTF8") from None
    _require(_CONTROL_RE.search(text) is None, NOTE_INVALID, "CONTROL_CHARACTER")
    _require(text.endswith("\n") and not text.endswith("\n\n"), NOTE_INVALID, "LINE_END")
    found = scan_private_shapes(text)
    _require(not found, PRIVATE_SHAPE_DETECTED, found[0] if found else "")
    lines = text[:-1].split("\n")
    _require(lines[0] == "---" and "---" in lines[1:], NOTE_INVALID, "FRONTMATTER")
    close = lines.index("---", 1)
    pairs = []
    for line in lines[1:close]:
        match = _FRONTMATTER_LINE_RE.match(line)
        _require(match is not None, NOTE_INVALID, "FRONTMATTER_LINE")
        pairs.append((match.group(1), match.group(2)))
    values = dict(pairs)
    kind = values.get("p13_note", "")
    _require(kind in FRONTMATTER_LAYOUTS and tuple(k for k, _ in pairs) == FRONTMATTER_LAYOUTS[kind], NOTE_INVALID, "FRONTMATTER_KEYS")
    _require(all(_frontmatter_value_ok(kind, k, v) for k, v in pairs), NOTE_INVALID, "FRONTMATTER_VALUE")
    build_id = values["build_id"]
    item_hex = values["item_id"][len(_ITEM_PREFIXES[kind]):]
    if kind == "POINTER":
        expected_item = pointer_slot_identity()
    else:
        ordinal = 0 if kind == "VERSION_INDEX" else int(values["p13_ordinal"])
        expected_item = public_note_identity(build_id, kind, ordinal)
    _require(item_hex == expected_item, PUBLIC_DIGEST_INVALID, "ITEM_ID")
    label = short_id(VERSION_PREFIX, build_id)
    rows, links = [], []
    for line in lines[close + 1:]:
        _require(len(line) <= MAX_NOTE_LINE_CHARS and line == line.strip(), NOTE_INVALID, "LINE_SHAPE")
        if line == "" or line in FIXED_LINES:
            continue
        row = _TABLE_ROW_RE.match(line)
        if row is not None:
            cells = tuple(cell for cell in row.groups() if cell is not None)
            _require(all(_cell_ok(cell) for cell in cells), NOTE_INVALID, "TABLE_CELL")
            rows.append(cells)
            continue
        link = _LINK_ITEM_RE.match(line)
        _require(link is not None and link.group(1) == label, NOTE_INVALID, "LINE")
        _require((kind == "POINTER" and link.group(2) is None) or (kind == "VERSION_INDEX" and link.group(2) is not None),
                 NOTE_INVALID, "LINK_KIND")
        links.append(line)
    allowed = {build_id, item_hex, build_id[:24]} | ({values["p13_export"]} if kind == "POINTER" else set())
    _require(all(run in allowed for run in _HEX_RUN_RE.findall(text)), PUBLIC_DIGEST_INVALID, "UNDERIVED_HEX")
    digest_rows = [cells for cells in rows if any(is_digest(c) for c in cells)]
    _require(all(cells == ("public_version_digest", build_id) for cells in digest_rows), PUBLIC_DIGEST_INVALID, "DIGEST_ROW")
    if name is not None:
        if kind == "POINTER":
            _require(name == POINTER_NOTE_NAME, NOTE_INVALID, "NAME")
        else:
            ordinal = 0 if kind == "VERSION_INDEX" else int(values["p13_ordinal"])
            _require(name == note_name(label, kind, ordinal), NOTE_INVALID, "NAME")
    return NoteParts(kind=kind, frontmatter=tuple(pairs), rows=tuple(rows), links=tuple(links))


def _row_values(parts: NoteParts) -> Dict[str, str]:
    return {cells[0]: cells[1] for cells in parts.rows if len(cells) == 2}


def _int_of(rows: Mapping[str, str], key: str) -> int:
    _require(key in rows and _INT_CELL_RE.match(rows[key]) is not None, NOTE_INVALID, "ROW")
    return int(rows[key])


def _text_of(rows: Mapping[str, str], key: str) -> str:
    _require(key in rows, NOTE_INVALID, "ROW")
    return rows[key]


def parse_public_version(notes: Any) -> PublicVersion:
    """版の folder の note だけから public な model を再構成し、描画し直した byte との完全一致を要する（public の digest は公開の欄
    だけから再計算できることの正の証明）。"""
    _require(isinstance(notes, Mapping) and all(isinstance(n, str) and isinstance(d, bytes) for n, d in notes.items()),
             NOTE_INVALID, "NOTES")
    indexes = [n for n in notes if _NOTE_NAME_RE.match(n) is not None and _NOTE_NAME_RE.match(n).group(2) is None]
    _require(len(indexes) == 1, NOTE_INVALID, "INDEX")
    parts = {name: validate_public_note(data, name=name) for name, data in sorted(notes.items())}
    index = parts[indexes[0]]
    _require(index.kind == "VERSION_INDEX", NOTE_INVALID, "INDEX_KIND")
    digest = index.value("build_id")
    rows = _row_values(index)
    sample_count, interval_count = _int_of(rows, "sample_count"), _int_of(rows, "interval_count")
    _require(1 <= sample_count <= MAX_PLAN_CUTOFFS and interval_count == sample_count - 1, NOTE_INVALID, "COUNTS")
    label = short_id(VERSION_PREFIX, digest)
    expected = {note_name(label, "VERSION_INDEX", 0)} | {note_name(label, "SAMPLE", n) for n in range(1, sample_count + 1)} | {
        note_name(label, "INTERVAL", n) for n in range(1, interval_count + 1)}
    _require(set(notes) == expected, NOTE_INVALID, "FILE_SET")
    samples = []
    for ordinal in range(1, sample_count + 1):
        note = parts[note_name(label, "SAMPLE", ordinal)]
        values = _row_values(note)
        _require(note.kind == "SAMPLE" and _int_of(values, "sample_ordinal") == ordinal, NOTE_INVALID, "SAMPLE_ORDINAL")
        _require(_text_of(values, "active_profile_present") in ("true", "false"), NOTE_INVALID, "ACTIVE_PROFILE")
        samples.append(PublicSample(ordinal=ordinal, as_of_date=_text_of(values, "sample_cutoff_date"),
                                    active_profile_present=values["active_profile_present"] == "true",
                                    review_counts=tuple((n, _int_of(values, n)) for n in _review_order()),
                                    p9_counts=tuple((n, _int_of(values, n)) for n in _P9_SCALAR_FIELDS),
                                    category_counts=tuple((f, c, int(v)) for f, c, v in (r for r in note.rows if len(r) == 3))))
    intervals = []
    for ordinal in range(1, interval_count + 1):
        note = parts[note_name(label, "INTERVAL", ordinal)]
        values = _row_values(note)
        _require(note.kind == "INTERVAL" and _int_of(values, "interval_ordinal") == ordinal, NOTE_INVALID, "INTERVAL_ORDINAL")
        intervals.append(PublicInterval(ordinal=ordinal, after_date=_text_of(values, "after_sample_cutoff_date"),
                                        through_date=_text_of(values, "through_sample_cutoff_date"),
                                        change_record_count=_int_of(values, "change_record_count"),
                                        kind_counts=tuple((r, k, int(v)) for r, k, v in (x for x in note.rows if len(x) == 3)),
                                        field_counts=tuple((n, _int_of(values, n)) for n in sorted(STRUCTURAL_FIELDS))))
    version = PublicVersion(adapter_rules_version=_text_of(rows, "adapter_rules"),
                            view_versions=tuple((n, _text_of(rows, n)) for n in _VIEW_FIELDS),
                            public_samples=tuple(samples), public_intervals=tuple(intervals))
    _require(version.public_version_digest == digest, PUBLIC_DIGEST_INVALID, "PUBLIC_VERSION_DIGEST")
    _require(render_public_export(version).note_map() == dict(notes), PUBLIC_DIGEST_INVALID, "RENDER_ROUND_TRIP")
    return version


def _verify_files(notes: Any, manifest: PublicExportManifest, code: str) -> None:
    """観測した note の写像を public な manifest と完全一致で照らす（欠落 ・余分 ・長さ ・sha256 ・文法 ・走査）。"""
    _require(isinstance(notes, Mapping) and all(isinstance(n, str) and isinstance(d, bytes) for n, d in notes.items()),
             OBSERVATION_INVALID, "NOTES")
    _require(sorted(notes) == [f.name for f in manifest.files], code, "FILE_SET")
    for entry in manifest.files:
        data = notes[entry.name]
        _require(len(data) == entry.size and sha256_hex(data) == entry.sha256, code, "SIZE_OR_SHA256")
        try:
            validate_public_note(data, name=entry.name)
        except ProjectionError:
            raise ProjectionError(code, "NOTE") from None


def verify_public_version(notes: Any, manifest: PublicExportManifest) -> PublicVersion:
    """版の folder の検証: manifest との byte の完全一致 ・公開の欄だけからの public の digest の再計算 ・manifest の版の digest との一致。"""
    _verify_files(notes, manifest, VERSION_UNVERIFIED)
    try:
        version = parse_public_version(notes)
    except ProjectionError:
        raise ProjectionError(VERSION_UNVERIFIED, "PUBLIC_RECOMPUTATION") from None
    _require(version.public_version_digest == manifest.public_version_digest, VERSION_UNVERIFIED, "PUBLIC_VERSION_DIGEST")
    return version


# ---------------------------------------------------------------- private な binding ・証拠の record（public の面には出ない）


@dataclass(frozen=True, kw_only=True)
class PrivateBinding:
    """public の版 ・export と、実際に検証した A3 の generation ／ manifest の完全な digest の結び付き（private な証拠だけ）。"""

    public_version_digest: str
    public_export_digest: str
    private_generation_digest: str = field(repr=False)
    private_source_manifest_digest: str = field(repr=False)
    source_attestation: str = SOURCE_ATTESTATION
    rules_version: str = CONTRACT_RULES_VERSION
    schema_version: str = BINDING_SCHEMA_VERSION

    def __post_init__(self) -> None:
        _require(self.schema_version == BINDING_SCHEMA_VERSION and self.rules_version == CONTRACT_RULES_VERSION, SCHEMA_UNSUPPORTED, "BINDING")
        _require(all(is_digest(d) for d in (self.public_version_digest, self.public_export_digest, self.private_generation_digest,
                                             self.private_source_manifest_digest)), RECORD_CORRUPT, "BINDING_DIGESTS")
        _require(self.source_attestation == SOURCE_ATTESTATION, RECORD_CORRUPT, "BINDING_ATTESTATION")

    def content(self) -> Dict[str, str]:
        return {"schema_version": self.schema_version, "rules_version": self.rules_version,
                "public_version_digest": self.public_version_digest, "public_export_digest": self.public_export_digest,
                "private_generation_digest": self.private_generation_digest,
                "private_source_manifest_digest": self.private_source_manifest_digest, "source_attestation": self.source_attestation}

    def to_evidence_bytes(self) -> bytes:
        return record_bytes(self.content())

    @property
    def binding_digest(self) -> str:
        return domain_digest(BINDING_DOMAIN, self.content())


@dataclass(frozen=True, kw_only=True)
class ProjectionTarget:
    """公開する版（public）と、その private な binding の組。"""

    public_export: PublicExport
    binding: PrivateBinding = field(repr=False)

    def __post_init__(self) -> None:
        _require(isinstance(self.public_export, PublicExport) and isinstance(self.binding, PrivateBinding), PROJECTION_INPUT_INVALID, "TARGET")
        _require(self.binding.public_version_digest == self.public_export.manifest.public_version_digest
                 and self.binding.public_export_digest == self.public_export.public_export_digest, BINDING_CONFLICT, "TARGET")

    @property
    def public_export_digest(self) -> str:
        return self.public_export.public_export_digest

    @property
    def version_label(self) -> str:
        return self.public_export.version_label


def build_projection_target(verified: VerifiedGeneration, *, generation_digest: str, manifest_digest: str) -> ProjectionTarget:
    """明示の完全な digest が必須（既定 ・「最新」の選択は無い）。public の版は公開の欄だけから、binding は private に作る。"""
    source = PrivateSourceInput(verified=verified, generation_digest=generation_digest, manifest_digest=manifest_digest)
    export = render_public_export(public_version_of(source))
    binding = PrivateBinding(public_version_digest=export.manifest.public_version_digest, public_export_digest=export.public_export_digest,
                             private_generation_digest=source.generation_digest, private_source_manifest_digest=source.manifest_digest)
    return ProjectionTarget(public_export=export, binding=binding)


@dataclass(frozen=True, kw_only=True)
class IntentRecord:
    """前の版（無ければ None）から次の版への 1 つの公開の意図（private な証拠 ・digest で完全性を検証 ・暗号の認証ではない）。"""

    to_public_version_digest: str
    to_public_export_digest: str
    to_binding_digest: str
    previous_public_export_digest: Optional[str] = None
    previous_binding_digest: Optional[str] = None
    schema_version: str = INTENT_SCHEMA_VERSION

    def __post_init__(self) -> None:
        _require(self.schema_version == INTENT_SCHEMA_VERSION, SCHEMA_UNSUPPORTED, "INTENT")
        _require(all(is_digest(d) for d in (self.to_public_version_digest, self.to_public_export_digest, self.to_binding_digest)),
                 RECORD_CORRUPT, "INTENT_DIGESTS")
        _require((self.previous_public_export_digest is None) == (self.previous_binding_digest is None), RECORD_CORRUPT, "INTENT_PREVIOUS")
        _require(self.previous_public_export_digest is None or (is_digest(self.previous_public_export_digest)
                                                                and is_digest(self.previous_binding_digest)), RECORD_CORRUPT, "INTENT_PREVIOUS")
        _require(self.previous_public_export_digest != self.to_public_export_digest, RECORD_CORRUPT, "INTENT_SELF")

    def content(self) -> Dict[str, Any]:
        return {"schema_version": self.schema_version, "to_public_version_digest": self.to_public_version_digest,
                "to_public_export_digest": self.to_public_export_digest, "to_binding_digest": self.to_binding_digest,
                "previous_public_export_digest": self.previous_public_export_digest,
                "previous_binding_digest": self.previous_binding_digest}

    def to_evidence_bytes(self) -> bytes:
        return record_bytes(self.content())

    @property
    def intent_digest(self) -> str:
        return domain_digest(INTENT_DOMAIN, self.content())

    @property
    def version_label(self) -> str:
        return short_id(VERSION_PREFIX, self.to_public_version_digest)


@dataclass(frozen=True, kw_only=True)
class CompletionRecord:
    intent_digest: str
    to_public_export_digest: str
    schema_version: str = COMPLETION_SCHEMA_VERSION

    def __post_init__(self) -> None:
        _require(self.schema_version == COMPLETION_SCHEMA_VERSION, SCHEMA_UNSUPPORTED, "COMPLETION")
        _require(is_digest(self.intent_digest) and is_digest(self.to_public_export_digest), RECORD_CORRUPT, "COMPLETION_DIGESTS")

    def content(self) -> Dict[str, str]:
        return {"schema_version": self.schema_version, "intent_digest": self.intent_digest,
                "to_public_export_digest": self.to_public_export_digest}

    def to_evidence_bytes(self) -> bytes:
        return record_bytes(self.content())

    @property
    def completion_digest(self) -> str:
        return domain_digest(COMPLETION_DOMAIN, self.content())


@dataclass(frozen=True, kw_only=True)
class AbortRecord:
    intent_digest: str
    reason: str
    schema_version: str = ABORT_SCHEMA_VERSION

    def __post_init__(self) -> None:
        _require(self.schema_version == ABORT_SCHEMA_VERSION, SCHEMA_UNSUPPORTED, "ABORT")
        _require(is_digest(self.intent_digest) and self.reason in ABORT_REASONS, RECORD_CORRUPT, "ABORT_FIELDS")

    def content(self) -> Dict[str, str]:
        return {"schema_version": self.schema_version, "intent_digest": self.intent_digest, "reason": self.reason}

    def to_evidence_bytes(self) -> bytes:
        return record_bytes(self.content())

    @property
    def abort_digest(self) -> str:
        return domain_digest(ABORT_DOMAIN, self.content())


def intent_for(target: ProjectionTarget, previous: Optional[IntentRecord]) -> IntentRecord:
    _require(isinstance(target, ProjectionTarget) and (previous is None or isinstance(previous, IntentRecord)), PROJECTION_INPUT_INVALID, "INTENT")
    return IntentRecord(to_public_version_digest=target.binding.public_version_digest, to_public_export_digest=target.public_export_digest,
                        to_binding_digest=target.binding.binding_digest,
                        previous_public_export_digest=None if previous is None else previous.to_public_export_digest,
                        previous_binding_digest=None if previous is None else previous.to_binding_digest)


def completion_for(intent: IntentRecord) -> CompletionRecord:
    _require(isinstance(intent, IntentRecord), PROJECTION_INPUT_INVALID, "COMPLETION")
    return CompletionRecord(intent_digest=intent.intent_digest, to_public_export_digest=intent.to_public_export_digest)


def abort_for(intent: IntentRecord, reason: str) -> AbortRecord:
    _require(isinstance(intent, IntentRecord), PROJECTION_INPUT_INVALID, "ABORT")
    return AbortRecord(intent_digest=intent.intent_digest, reason=reason)


_PUBLIC_EXPORT_FIELDS = frozenset({"schema_version", "rules_version", "public_version_digest", "as_of_date", "files"})
_BINDING_FIELDS = frozenset({"schema_version", "rules_version", "public_version_digest", "public_export_digest", "private_generation_digest",
                             "private_source_manifest_digest", "source_attestation"})
_INTENT_FIELDS = frozenset({"schema_version", "to_public_version_digest", "to_public_export_digest", "to_binding_digest",
                            "previous_public_export_digest", "previous_binding_digest"})
_COMPLETION_FIELDS = frozenset({"schema_version", "intent_digest", "to_public_export_digest"})
_ABORT_FIELDS = frozenset({"schema_version", "intent_digest", "reason"})


def _parse_record(data: Any, *, schema: str, required: frozenset, context: str) -> Dict[str, Any]:
    _require(isinstance(data, bytes) and len(data) <= MAX_NOTE_BYTES, RECORD_CORRUPT, context)
    try:
        value = json.loads(data.decode("utf-8"))
    except (ValueError, RecursionError):
        raise ProjectionError(RECORD_CORRUPT, context) from None
    _require(isinstance(value, dict) and isinstance(value.get("schema_version"), str), RECORD_CORRUPT, context)
    _require(value["schema_version"] == schema, SCHEMA_UNSUPPORTED, context)
    _require(set(value) == set(required), RECORD_CORRUPT, f"{context}:FIELDS")
    return value


def _canonical(record: Any, data: bytes, encoded: bytes, context: str) -> Any:
    _require(encoded == data, RECORD_CORRUPT, f"{context}:NON_CANONICAL")
    return record


def parse_public_export_manifest(data: Any) -> PublicExportManifest:
    value = _parse_record(data, schema=PUBLIC_EXPORT_SCHEMA_VERSION, required=_PUBLIC_EXPORT_FIELDS, context="PUBLIC_EXPORT")
    files = value["files"]
    _require(isinstance(files, list) and all(isinstance(f, list) and len(f) == 3 for f in files), RECORD_CORRUPT, "PUBLIC_FILES")
    try:
        manifest = PublicExportManifest(public_version_digest=value["public_version_digest"], as_of_date=value["as_of_date"],
                                        rules_version=value["rules_version"], files=tuple(PublicFile(name=n, size=s, sha256=h) for n, s, h in files))
    except (AttributeError, TypeError, CanonicalError):
        raise ProjectionError(RECORD_CORRUPT, "PUBLIC_EXPORT") from None
    return _canonical(manifest, data, manifest.to_public_bytes(), "PUBLIC_EXPORT")


def parse_private_binding(data: Any) -> PrivateBinding:
    value = _parse_record(data, schema=BINDING_SCHEMA_VERSION, required=_BINDING_FIELDS, context="BINDING")
    try:
        record = PrivateBinding(**value)
    except TypeError:
        raise ProjectionError(RECORD_CORRUPT, "BINDING") from None
    return _canonical(record, data, record.to_evidence_bytes(), "BINDING")


def parse_intent(data: Any) -> IntentRecord:
    value = _parse_record(data, schema=INTENT_SCHEMA_VERSION, required=_INTENT_FIELDS, context="INTENT")
    try:
        record = IntentRecord(**value)
    except TypeError:
        raise ProjectionError(RECORD_CORRUPT, "INTENT") from None
    return _canonical(record, data, record.to_evidence_bytes(), "INTENT")


def parse_completion(data: Any) -> CompletionRecord:
    value = _parse_record(data, schema=COMPLETION_SCHEMA_VERSION, required=_COMPLETION_FIELDS, context="COMPLETION")
    record = CompletionRecord(**value)
    return _canonical(record, data, record.to_evidence_bytes(), "COMPLETION")


def parse_abort(data: Any) -> AbortRecord:
    value = _parse_record(data, schema=ABORT_SCHEMA_VERSION, required=_ABORT_FIELDS, context="ABORT")
    record = AbortRecord(**value)
    return _canonical(record, data, record.to_evidence_bytes(), "ABORT")


# ---------------------------------------------------------------- 公開の状態の分類 ・回復 ／ 保存の適格（純粋 ・提案だけ）


@dataclass(frozen=True, kw_only=True)
class PublicationObservation:
    """A4b が読んだ byte（pointer ・版の folder ・staging ・public な manifest ・private な binding と証拠）。A4a1 は I/O をしない。"""

    pointer: Optional[bytes] = None
    versions: Mapping[str, Mapping[str, bytes]] = field(default_factory=dict)
    staging: Mapping[str, Mapping[str, bytes]] = field(default_factory=dict)
    public_exports: Mapping[str, bytes] = field(default_factory=dict)
    private_bindings: Mapping[str, bytes] = field(default_factory=dict)
    intents: Mapping[str, bytes] = field(default_factory=dict)
    completions: Mapping[str, bytes] = field(default_factory=dict)
    aborts: Mapping[str, bytes] = field(default_factory=dict)


@dataclass(frozen=True, kw_only=True)
class TransitionPlan:
    """提案する 1 つの遷移（追加 ・pointer の置換 ・開いた intent の staging の移動 ・明示の保存だけ）。`retained_versions` は手を触れない。"""

    action: ProposedAction
    intent_digest: Optional[str] = None
    version_label: Optional[str] = None
    evidence: Tuple[Tuple[str, str, bytes], ...] = field(default=(), repr=False)
    staged_notes: Tuple[Tuple[str, bytes], ...] = field(default=(), repr=False)
    existing_notes: Tuple[str, ...] = ()
    preserve_area: Optional[str] = None
    preserve_label: Optional[str] = None
    expected_pointer: Optional[bytes] = field(default=None, repr=False)
    replacement_pointer: Optional[bytes] = field(default=None, repr=False)
    retained_versions: Tuple[str, ...] = ()


@dataclass(frozen=True, kw_only=True)
class PublicationClassification:
    state: PublicationState
    action: ProposedAction
    recovery: RecoveryEligibility
    code: str
    published_public_export_digest: Optional[str] = None
    open_intent_digest: Optional[str] = None
    completed_intent_count: int = 0
    aborted_intent_count: int = 0
    retained_versions: Tuple[str, ...] = ()
    target_binding_recorded: Optional[bool] = None
    transition: Optional[TransitionPlan] = field(default=None, repr=False)


def _check_observation(observation: Any) -> None:
    _require(isinstance(observation, PublicationObservation), OBSERVATION_INVALID, "TYPE")
    _require(observation.pointer is None or isinstance(observation.pointer, bytes), OBSERVATION_INVALID, "POINTER")
    total = 0
    for group in (observation.versions, observation.staging):
        _require(isinstance(group, Mapping), OBSERVATION_INVALID, "FOLDERS")
        for label, notes in group.items():
            _require(isinstance(label, str) and _VERSION_LABEL_RE.match(label) is not None, UNKNOWN_OBJECT, "FOLDER_NAME")
            _require(isinstance(notes, Mapping) and all(isinstance(n, str) and isinstance(d, bytes) for n, d in notes.items()),
                     OBSERVATION_INVALID, "NOTES")
            total += 1 + len(notes)
    for group in (observation.public_exports, observation.private_bindings, observation.intents, observation.completions,
                  observation.aborts):
        _require(isinstance(group, Mapping) and all(is_digest(k) and isinstance(v, bytes) for k, v in group.items()),
                 OBSERVATION_INVALID, "EVIDENCE")
        total += len(group)
    _require(total <= MAX_OBSERVED_OBJECTS, OBSERVATION_INVALID, "SIZE")


def _evidence(group: Mapping[str, bytes], parse: Any, digest_of: Any, context: str) -> Dict[str, Any]:
    parsed = {}
    for key in sorted(group):
        record = parse(group[key])
        _require(digest_of(record) == key, EVIDENCE_DIGEST_MISMATCH, context)
        parsed[key] = record
    return parsed


def _observed_version_labels(observation: Any) -> Tuple[str, ...]:
    if isinstance(observation, PublicationObservation) and isinstance(observation.versions, Mapping):
        return tuple(sorted(label for label in observation.versions if isinstance(label, str)))
    return ()


def _fail_closed(code: str, observation: Any) -> PublicationClassification:
    return PublicationClassification(state=PublicationState.FAIL_CLOSED, action=ProposedAction.HOLD,
                                     recovery=RecoveryEligibility.HOLD_FAIL_CLOSED, code=code,
                                     retained_versions=_observed_version_labels(observation))


def _staging_class(notes: Mapping[str, bytes], manifest: PublicExportManifest, expected_bytes: Optional[Mapping[str, bytes]]) -> str:
    """staging の内容の分類: FOREIGN（manifest に無い名前）・TAMPERED ・TORN（対象の byte の厳密な接頭）・UNVERIFIED（対象が無く区別できない）・
    COMPLETE ・PARTIAL（在る file は全て byte 一致の部分集合 ・空も含む）。"""
    expected = {f.name: f for f in manifest.files}
    if set(notes) - set(expected):
        return "FOREIGN"
    torn = tampered = False
    for name in sorted(notes):
        data, entry = notes[name], expected[name]
        if len(data) == entry.size and sha256_hex(data) == entry.sha256:
            try:
                validate_public_note(data, name=name)
            except ProjectionError:
                tampered = True
            continue
        if expected_bytes is None:
            return "UNVERIFIED"
        full = expected_bytes[name]
        if len(data) < len(full) and full[:len(data)] == data:
            torn = True
        else:
            tampered = True
    if tampered:
        return "TAMPERED"
    if torn:
        return "TORN"
    return "COMPLETE" if set(notes) == set(expected) else "PARTIAL"


def classify_publication(observation: PublicationObservation, *,
                         target: Optional[ProjectionTarget] = None) -> PublicationClassification:
    """観測した byte だけから公開の状態を分類し、次の 1 つの遷移を提案する。検証できない ・曖昧なものは全て FAIL_CLOSED（HOLD）。"""
    try:
        return _classify(observation, target)
    except ProjectionError as exc:
        return _fail_closed(exc.code, observation)


def _classify(observation: PublicationObservation, target: Optional[ProjectionTarget]) -> PublicationClassification:
    _check_observation(observation)
    _require(target is None or isinstance(target, ProjectionTarget), OBSERVATION_INVALID, "TARGET")
    exports = _evidence(observation.public_exports, parse_public_export_manifest, lambda r: r.public_export_digest, "PUBLIC_EXPORT")
    bindings = _evidence(observation.private_bindings, parse_private_binding, lambda r: r.binding_digest, "BINDING")
    intents = _evidence(observation.intents, parse_intent, lambda r: r.intent_digest, "INTENT")
    completions = _evidence(observation.completions, parse_completion, lambda r: r.completion_digest, "COMPLETION")
    aborts = _evidence(observation.aborts, parse_abort, lambda r: r.abort_digest, "ABORT")

    closing: Dict[str, str] = {}
    for record in completions.values():
        _require(record.intent_digest in intents, INTENT_REFERENCE_MISSING, "COMPLETION")
        _require(record.to_public_export_digest == intents[record.intent_digest].to_public_export_digest, CONTRADICTORY_INTENT, "COMPLETION_TARGET")
        _require(record.intent_digest not in closing, CONTRADICTORY_INTENT, "DUPLICATE_CLOSING")
        closing[record.intent_digest] = EVIDENCE_COMPLETION
    for record in aborts.values():
        _require(record.intent_digest in intents, INTENT_REFERENCE_MISSING, "ABORT")
        _require(record.intent_digest not in closing, CONTRADICTORY_INTENT, "COMPLETED_AND_ABORTED")
        closing[record.intent_digest] = EVIDENCE_ABORT

    for intent in intents.values():                                              # intent ごとに public な manifest と private な binding
        export = exports.get(intent.to_public_export_digest)
        _require(export is not None, MANIFEST_MISSING, "INTENT_TARGET")
        _require(export.public_version_digest == intent.to_public_version_digest, MANIFEST_CONFLICT, "INTENT_TARGET")
        binding = bindings.get(intent.to_binding_digest)
        _require(binding is not None, BINDING_MISSING, "INTENT_BINDING")
        _require(binding.public_export_digest == intent.to_public_export_digest
                 and binding.public_version_digest == intent.to_public_version_digest, BINDING_CONFLICT, "INTENT_BINDING")
    targets = [intent.to_public_export_digest for intent in intents.values()]
    _require(len(set(targets)) == len(targets), REPUBLICATION_OF_KNOWN_VERSION, "SHARED_TARGET")
    _require(set(exports) <= set(targets), UNREFERENCED_MANIFEST, "PUBLIC_EXPORT")
    versions_of = [m.public_version_digest for m in exports.values()]
    _require(len(set(versions_of)) == len(versions_of), MANIFEST_CONFLICT, "PUBLIC_VERSION_EXPORTS")
    for binding in bindings.values():
        _require(binding.public_export_digest in exports
                 and exports[binding.public_export_digest].public_version_digest == binding.public_version_digest,
                 UNREFERENCED_BINDING, "BINDING_EXPORT")
    _no_collision([(m.version_label, m.public_version_digest) for m in exports.values()]
                  + ([(target.version_label, target.binding.public_version_digest)] if target is not None else []))

    completed = {d: i for d, i in intents.items() if closing.get(d) == EVIDENCE_COMPLETION}
    chain = []
    head: Optional[IntentRecord] = None
    while completed:                                                             # 完了した intent は None から始まる 1 本の鎖
        following = [d for d, i in completed.items() if i.previous_public_export_digest == (None if head is None else head.to_public_export_digest)]
        _require(len(following) == 1, INTENT_CHAIN_INVALID, "COMPLETED_CHAIN")
        intent = completed.pop(following[0])
        _require(head is None or intent.previous_binding_digest == head.to_binding_digest, INTENT_CHAIN_INVALID, "PREVIOUS_BINDING")
        chain.append(intent)
        head = intent
    chain_exports = {i.to_public_export_digest for i in chain}
    for d, intent in intents.items():
        if closing.get(d) == EVIDENCE_ABORT:
            _require(intent.previous_public_export_digest is None or intent.previous_public_export_digest in chain_exports,
                     INTENT_CHAIN_INVALID, "ABORTED")
    referenced = {intent.to_binding_digest for intent in intents.values()}
    for digest, binding in bindings.items():                                     # 追加の provenance は完了した版にだけ結べる
        _require(digest in referenced or binding.public_export_digest in chain_exports, UNREFERENCED_BINDING, "EXTRA_BINDING")
    open_ = [(d, i) for d, i in sorted(intents.items()) if d not in closing]
    _require(len(open_) <= 1, MULTIPLE_OPEN_INTENTS, "OPEN")
    open_digest, open_intent = open_[0] if open_ else (None, None)
    if open_intent is not None:
        _require(open_intent.previous_public_export_digest == (None if head is None else head.to_public_export_digest)
                 and open_intent.previous_binding_digest == (None if head is None else head.to_binding_digest),
                 INTENT_CHAIN_INVALID, "OPEN_PREVIOUS")

    owners = {i.version_label: (d, i) for d, i in intents.items()}
    for label in sorted(observation.versions):
        _require(label in owners, UNREFERENCED_VERSION, "VERSION")
        notes = observation.versions[label]
        if not notes:                                                            # 空の予約は開いた intent のものだけ（下で扱う）
            _require(owners[label][0] == open_digest, VERSION_UNVERIFIED, "EMPTY_VERSION")
            continue
        verify_public_version(notes, exports[owners[label][1].to_public_export_digest])
    for intent in chain:                                                         # 前の有効な版は全て在り ・検証できる
        _require(bool(observation.versions.get(intent.version_label)), PREVIOUS_VERSION_MISSING, "COMPLETED_VERSION")
    for label in sorted(observation.staging):
        _require(label in owners, ORPHAN_STAGING, "STAGING")

    pointer = None
    if observation.pointer is not None:
        pointer = parse_pointer(observation.pointer)
        _require(head is not None or open_intent is not None, POINTER_WITHOUT_EVIDENCE, "POINTER")
        acceptable = {i.to_public_export_digest for i in (head, open_intent) if i is not None}
        _require(pointer.public_export_digest in acceptable, POINTER_UNEXPECTED, "TARGET")
        manifest = exports[pointer.public_export_digest]
        _require(pointer.public_version_digest == manifest.public_version_digest and pointer.as_of_date == manifest.as_of_date,
                 POINTER_UNEXPECTED, "PUBLIC_VERSION")
        _require(bool(observation.versions.get(pointer.version_label)), POINTER_UNEXPECTED, "VERSION_ABSENT")
    else:
        _require(head is None, POINTER_MISSING, "PUBLISHED_CHAIN")

    retained = tuple(sorted(observation.versions))
    summary = dict(published_public_export_digest=None if pointer is None else pointer.public_export_digest,
                   open_intent_digest=open_digest, completed_intent_count=len(chain),
                   aborted_intent_count=sum(1 for v in closing.values() if v == EVIDENCE_ABORT), retained_versions=retained)
    for label in sorted(observation.staging):                                    # 閉じた intent の staging は先に明示の保存だけ
        owner_digest, owner = owners[label]
        if owner_digest == open_digest:
            continue
        _require(closing.get(owner_digest) == EVIDENCE_ABORT, STAGING_OF_CLOSED_INTENT, "COMPLETED_INTENT_STAGING")
        kind = _staging_class(observation.staging[label], exports[owner.to_public_export_digest], None)
        _require(kind in ("PARTIAL", "COMPLETE"), STAGING_OF_CLOSED_INTENT, kind)
        plan = TransitionPlan(action=ProposedAction.PRESERVE_STAGING, intent_digest=owner_digest, version_label=label,
                              preserve_area=PRESERVE_AREA_STAGING, preserve_label=label, retained_versions=retained)
        return PublicationClassification(state=PublicationState.STAGING_OF_CLOSED_INTENT, action=ProposedAction.PRESERVE_STAGING,
                                         recovery=RecoveryEligibility.EXPLICIT_PRESERVATION_ONLY, code=STAGING_OF_CLOSED_INTENT,
                                         transition=plan, **summary)
    if open_intent is None:
        return _no_open_intent(target, head, exports, bindings, owners, summary)
    return _open_intent(observation, target, open_digest, open_intent, pointer, exports, summary)


def _no_open_intent(target: Optional[ProjectionTarget], head: Optional[IntentRecord], exports: Mapping[str, PublicExportManifest],
                    bindings: Mapping[str, PrivateBinding], owners: Mapping[str, Any], summary: Dict[str, Any]) -> PublicationClassification:
    state = PublicationState.FIRST_PUBLICATION if head is None else PublicationState.PUBLISHED_VERIFIED
    quiet = RecoveryEligibility.NOT_REQUIRED
    if target is None:
        return PublicationClassification(state=state, action=ProposedAction.NONE, recovery=quiet, code=state.value, **summary)
    recorded = target.binding.binding_digest in bindings
    if head is not None and target.public_export_digest == head.to_public_export_digest:
        if recorded:                                                             # 公開は同じ ・provenance も記録済み
            return PublicationClassification(state=PublicationState.NO_CHANGE, action=ProposedAction.NONE, recovery=quiet,
                                             code=PublicationState.NO_CHANGE.value, target_binding_recorded=True, **summary)
        plan = TransitionPlan(action=ProposedAction.RECORD_PRIVATE_BINDING, version_label=target.version_label,
                              evidence=((EVIDENCE_PRIVATE_BINDING, target.binding.binding_digest, target.binding.to_evidence_bytes()),),
                              retained_versions=summary["retained_versions"])
        return PublicationClassification(state=PublicationState.NO_CHANGE, action=ProposedAction.RECORD_PRIVATE_BINDING, recovery=quiet,
                                         code=NO_CHANGE_BINDING_UNRECORDED, target_binding_recorded=False, transition=plan, **summary)
    if target.version_label in owners:
        known = exports[owners[target.version_label][1].to_public_export_digest]
        code = REPUBLICATION_OF_KNOWN_VERSION if known.public_export_digest == target.public_export_digest else MANIFEST_CONFLICT
        return PublicationClassification(state=state, action=ProposedAction.HOLD, recovery=RecoveryEligibility.HOLD_FAIL_CLOSED,
                                         code=code, target_binding_recorded=recorded, **summary)
    intent = intent_for(target, head)
    plan = TransitionPlan(action=ProposedAction.PREPARE_INTENT, intent_digest=intent.intent_digest, version_label=target.version_label,
                          evidence=((EVIDENCE_PUBLIC_EXPORT, target.public_export_digest, target.public_export.manifest.to_public_bytes()),
                                    (EVIDENCE_PRIVATE_BINDING, target.binding.binding_digest, target.binding.to_evidence_bytes()),
                                    (EVIDENCE_INTENT, intent.intent_digest, intent.to_evidence_bytes())),
                          retained_versions=summary["retained_versions"])
    return PublicationClassification(state=state, action=ProposedAction.PREPARE_INTENT, recovery=quiet, code=state.value,
                                     target_binding_recorded=False, transition=plan, **summary)


def _open_intent(observation: PublicationObservation, target: Optional[ProjectionTarget], open_digest: str, open_intent: IntentRecord,
                 pointer: Optional[PointerRecord], exports: Mapping[str, PublicExportManifest],
                 summary: Dict[str, Any]) -> PublicationClassification:
    label = open_intent.version_label
    manifest = exports[open_intent.to_public_export_digest]
    retained = summary["retained_versions"]
    matching = target is not None and target.public_export_digest == open_intent.to_public_export_digest
    version_notes = observation.versions.get(label)
    staging_notes = observation.staging.get(label)
    expected_bytes = target.public_export.note_map() if matching else None
    kind = None if staging_notes is None else _staging_class(staging_notes, manifest, expected_bytes)
    explicit, auto = RecoveryEligibility.EXPLICIT_PRESERVATION_ONLY, RecoveryEligibility.AUTO_CONVERGE_ELIGIBLE
    _require(not (version_notes and staging_notes is not None), AMBIGUOUS_STAGING_AND_VERSION, "STAGING_AND_VERSION")
    if pointer is not None and pointer.public_export_digest == open_intent.to_public_export_digest:
        record = completion_for(open_intent)
        state, action, recovery = PublicationState.POINTER_SWITCHED, ProposedAction.RECORD_COMPLETION, auto
        plan = TransitionPlan(action=action, intent_digest=open_digest, version_label=label,
                              evidence=((EVIDENCE_COMPLETION, record.completion_digest, record.to_evidence_bytes()),), retained_versions=retained)
    elif version_notes:
        state, action, recovery = PublicationState.VERSION_VERIFIED, ProposedAction.REPLACE_POINTER, auto
        plan = TransitionPlan(action=action, intent_digest=open_digest, version_label=label, expected_pointer=observation.pointer,
                              replacement_pointer=render_pointer(manifest), retained_versions=retained)
    elif version_notes is not None:                                              # 空の予約（POSIX の移動の途中）
        _require(kind == "COMPLETE", VERSION_UNVERIFIED, "EMPTY_RESERVATION_WITHOUT_COMPLETE_STAGING")
        state, action, recovery = PublicationState.VERSION_RESERVED_EMPTY, ProposedAction.PRESERVE_EMPTY_RESERVATION, explicit
        plan = TransitionPlan(action=action, intent_digest=open_digest, version_label=label, preserve_area=PRESERVE_AREA_RESERVATION,
                              preserve_label=label, retained_versions=retained)
    elif kind == "COMPLETE":
        state, action, recovery = PublicationState.STAGED_VERIFIED, ProposedAction.MOVE_STAGED_TO_VERSION, auto
        plan = TransitionPlan(action=action, intent_digest=open_digest, version_label=label, retained_versions=retained)
    elif kind == "PARTIAL":
        state, action, recovery = PublicationState.STAGING_PARTIAL_VERIFIED, ProposedAction.CONTINUE_STAGING, auto
        if not matching:
            return PublicationClassification(state=state, action=ProposedAction.HOLD, recovery=RecoveryEligibility.HOLD_FAIL_CLOSED,
                                             code=TARGET_CONFLICTS_WITH_OPEN_INTENT if target is not None else TARGET_REQUIRED_FOR_STAGING,
                                             **summary)
        missing = tuple((n, d) for n, d in target.public_export.notes if n not in staging_notes)
        plan = TransitionPlan(action=action, intent_digest=open_digest, version_label=label, staged_notes=missing,
                              existing_notes=tuple(sorted(staging_notes)), retained_versions=retained)
    elif kind == "TORN":
        state, action, recovery = PublicationState.STAGING_TORN, ProposedAction.PRESERVE_STAGING, explicit
        plan = TransitionPlan(action=action, intent_digest=open_digest, version_label=label, preserve_area=PRESERVE_AREA_STAGING,
                              preserve_label=label, retained_versions=retained)
    elif kind is not None:
        raise ProjectionError({"TAMPERED": STAGING_TAMPERED, "FOREIGN": STAGING_FOREIGN_ENTRY}.get(kind, STAGING_UNVERIFIED), kind)
    else:
        state, action, recovery = PublicationState.INTENT_PREPARED, ProposedAction.STAGE_VERSION, auto
        if not matching:
            return PublicationClassification(state=state, action=ProposedAction.HOLD, recovery=RecoveryEligibility.HOLD_FAIL_CLOSED,
                                             code=TARGET_CONFLICTS_WITH_OPEN_INTENT if target is not None else TARGET_REQUIRED_FOR_STAGING,
                                             **summary)
        plan = TransitionPlan(action=action, intent_digest=open_digest, version_label=label, staged_notes=target.public_export.notes,
                              retained_versions=retained)
    if target is not None and not matching:
        return PublicationClassification(state=state, action=ProposedAction.HOLD, recovery=RecoveryEligibility.HOLD_FAIL_CLOSED,
                                         code=TARGET_CONFLICTS_WITH_OPEN_INTENT, **summary)
    return PublicationClassification(state=state, action=action, recovery=recovery, code=state.value, transition=plan, **summary)


def check_recovery_proposal(observation: PublicationObservation, proposed: Any, *,
                            target: Optional[ProjectionTarget] = None) -> TransitionPlan:
    """自動の収束の提案の検査: 観測を分類し直し、自動の適格で ・提案がちょうど次の遷移のときだけ、その遷移を返す。"""
    try:
        action = ProposedAction(proposed)
    except ValueError:
        raise ProjectionError(UNSAFE_RECOVERY_PROPOSAL, "UNKNOWN_ACTION") from None
    classification = classify_publication(observation, target=target)
    _require(classification.recovery is RecoveryEligibility.AUTO_CONVERGE_ELIGIBLE, UNSAFE_RECOVERY_PROPOSAL, "NOT_ELIGIBLE")
    _require(action in AUTO_CONVERGE_ACTIONS and action is classification.action, UNSAFE_RECOVERY_PROPOSAL, "NOT_THE_NEXT_TRANSITION")
    _require(classification.transition is not None and classification.transition.action is action, UNSAFE_RECOVERY_PROPOSAL, "PLAN")
    return classification.transition


def _without(observation: PublicationObservation, area: str, label: str) -> PublicationObservation:
    versions = {k: v for k, v in observation.versions.items() if not (area == PRESERVE_AREA_RESERVATION and k == label)}
    staging = {k: v for k, v in observation.staging.items() if not (area == PRESERVE_AREA_STAGING and k == label)}
    return PublicationObservation(pointer=observation.pointer, versions=versions, staging=staging,
                                  public_exports=observation.public_exports, private_bindings=observation.private_bindings,
                                  intents=observation.intents, completions=observation.completions, aborts=observation.aborts)


def check_preservation_proposal(observation: PublicationObservation, proposed: Any, *,
                                target: Optional[ProjectionTarget] = None) -> TransitionPlan:
    """人の明示の保存の提案の検査: 明示だけの適格で ・提案がちょうど次の遷移で ・対象が staging か空の予約（決して有効な版ではない）で ・
    保存の後の状態が FAIL_CLOSED でないときだけ、その遷移を返す（実行は A4b ・何も消さない）。"""
    try:
        action = ProposedAction(proposed)
    except ValueError:
        raise ProjectionError(UNSAFE_PRESERVATION_PROPOSAL, "UNKNOWN_ACTION") from None
    classification = classify_publication(observation, target=target)
    _require(classification.recovery is RecoveryEligibility.EXPLICIT_PRESERVATION_ONLY, UNSAFE_PRESERVATION_PROPOSAL, "NOT_ELIGIBLE")
    _require(action in EXPLICIT_PRESERVATION_ACTIONS and action is classification.action, UNSAFE_PRESERVATION_PROPOSAL,
             "NOT_THE_NEXT_TRANSITION")
    plan = classification.transition
    _require(plan is not None and plan.action is action and plan.preserve_label is not None, UNSAFE_PRESERVATION_PROPOSAL, "PLAN")
    if plan.preserve_area == PRESERVE_AREA_RESERVATION:
        _require(observation.versions.get(plan.preserve_label) == {}, UNSAFE_PRESERVATION_PROPOSAL, "NOT_EMPTY")
    else:
        _require(plan.preserve_area == PRESERVE_AREA_STAGING and plan.preserve_label in observation.staging,
                 UNSAFE_PRESERVATION_PROPOSAL, "NOT_STAGING")
    after = classify_publication(_without(observation, plan.preserve_area, plan.preserve_label), target=target)
    _require(after.state is not PublicationState.FAIL_CLOSED, UNSAFE_PRESERVATION_PROPOSAL, "POST_STATE")
    _require(set(classification.retained_versions) - ({plan.preserve_label} if plan.preserve_area == PRESERVE_AREA_RESERVATION else set())
             <= set(after.retained_versions), UNSAFE_PRESERVATION_PROPOSAL, "RETAINED")
    return plan


__all__ = ["ABORT_DOMAIN", "ABORT_SCHEMA_VERSION", "ALLOWED_CODES", "ALLOWED_FIELD_LABELS", "AS_OF_BASIS", "AUTHORITY_VALUE",
           "AUTO_CONVERGE_ACTIONS", "AbortRecord", "BINDING_DOMAIN", "BINDING_SCHEMA_VERSION", "BUILD_BASIS", "COMPLETION_DOMAIN",
           "COMPLETION_SCHEMA_VERSION", "CONTRACT_CODES", "CONTRACT_RULES_VERSION", "CONTRACT_SCHEMA_VERSION", "CompletionRecord",
           "EVIDENCE_ABORT", "EVIDENCE_COMPLETION", "EVIDENCE_INTENT", "EVIDENCE_PRIVATE_BINDING", "EVIDENCE_PUBLIC_EXPORT",
           "EXPLICIT_PRESERVATION_ACTIONS", "FIXED_LINES", "FRONTMATTER_LAYOUTS", "GENERATED_VALUE", "INTENT_DOMAIN",
           "INTENT_SCHEMA_VERSION", "INTERVAL_NOTE_PREFIX", "IntentRecord", "MAX_EXPORT_FILES", "MAX_OBSERVED_OBJECTS", "NOT_AVAILABLE",
           "NoteKind", "NoteParts", "POINTER_SCHEMA_VERSION", "POINTER_SLOT_DOMAIN", "POINTER_SLOT_PREFIX", "PRESERVE_AREA_RESERVATION",
           "PRESERVE_AREA_STAGING", "PUBLIC_AUTHORITY_CLASS", "PUBLIC_EXPORT_DOMAIN", "PUBLIC_EXPORT_SCHEMA_VERSION",
           "PUBLIC_NOTE_DOMAIN", "PUBLIC_VERSION_DOMAIN", "PointerRecord", "PrivateBinding", "PrivateSourceInput", "ProjectionTarget",
           "ProposedAction", "PublicExport", "PublicExportManifest", "PublicFile", "PublicInterval", "PublicSample", "PublicVersion",
           "PublicationClassification", "PublicationObservation", "PublicationState", "RecoveryEligibility", "SAMPLE_NOTE_PREFIX",
           "SOURCE_ATTESTATION", "SOURCE_NOTICE", "SOURCE_REF_VALUE", "TransitionPlan", "VERSION_PREFIX", "abort_for",
           "build_projection_target", "check_preservation_proposal", "check_recovery_proposal", "classify_publication",
           "completion_for", "intent_for", "note_name", "parse_abort", "parse_completion", "parse_intent", "parse_pointer",
           "parse_private_binding", "parse_public_export_manifest", "parse_public_version", "pointer_slot_identity",
           "public_note_identity", "public_version_of", "render_pointer", "render_public_export", "validate_public_note",
           "verify_public_version"]
