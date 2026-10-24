"""P13-A4a — Review State Memory の Obsidian 投影の純粋な model（file ・network ・process ・時計 ・環境 ・資格情報に触れない）。

- 入力は明示の完全な generation digest と source の manifest digest を伴う `VerifiedGeneration` だけ（「最新」を選ばない）。A4a は record の
  byte を作り直して A3 の `verify_generation_records` で **純粋に再検証**するが、それは A3 の store から実際に読んだことの証明ではない
  （`SOURCE_ATTESTATION`）。A4b は A3 の公開の読み `MemoryStore.read_generation` が VERIFIED を返した結果だけを同じ呼び出しの中で渡す。
- 出力は counts-only の Markdown（件数 ・承認した構造の分類 ・日付 ・schema ／ 規則の version ・完全な digest ・固定の文 ・固定の link）。
  項目ごとの id ・発行体 ・擬名の hash（項目ごとの変化の digest を含む）・本文 ・著者 ・瞬間 ・URL ・HTML ・埋め込み ・plugin が実行する式 ・
  private な位置 ・資格情報は無い。全ての note は厳密な行の文法と private の形の走査の 2 つの層を通る（どちらかが外れれば fail closed）。
- 標本の cutoff の日は標本の区切りであり、source の known_at ではない（取り違えない ・瞬間は出さない）。
- identity: projection digest（計画 ・版の label）・export digest（版の folder の file の集合の manifest）・各 record の digest。略記は label
  だけで、別の完全な digest が同じ略記を持てば fail closed。
- 公開の状態の分類 ・回復の適格の分類は観測した byte だけから純粋に行い、次の 1 つの遷移を **提案するだけ**（I/O ・回復の実行は無い）。
  前の有効な版を archive ・削除 ・移動する action は存在しない。検証できない ・曖昧な状態は fail closed（OPEN ／ HOLD for A4b）。
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
from .review_state_change import ChangeKind
from .review_state_sample import PERSONAL_COUNT_KEYS, STRUCTURAL_FIELDS, RecordKind

PROJECTION_SCHEMA_VERSION = "p13_memory_projection:0.1.0"
PROJECTION_RULES_VERSION = "p13_projection_rules:0.1.0"
EXPORT_MANIFEST_SCHEMA_VERSION = "p13_projection_manifest:0.1.0"
POINTER_SCHEMA_VERSION = "p13_projection_pointer:0.1.0"
INTENT_SCHEMA_VERSION = "p13_projection_intent:0.1.0"
COMPLETION_SCHEMA_VERSION = "p13_projection_completion:0.1.0"
ABORT_SCHEMA_VERSION = "p13_projection_abort:0.1.0"
PROJECTION_DOMAIN = "p13.memory_projection_plan.v1"
INTERVAL_DOMAIN = "p13.memory_projection_interval.v1"
EXPORT_DOMAIN = "p13.memory_projection_export.v1"
INTENT_DOMAIN = "p13.memory_projection_intent.v1"
COMPLETION_DOMAIN = "p13.memory_projection_completion.v1"
ABORT_DOMAIN = "p13.memory_projection_abort.v1"
VERSION_LABEL_PREFIX = "p13prj_"
EXPORT_ID_PREFIX = "p13exp_"
INTERVAL_ID_PREFIX = "p13int_"
NOTE_SUFFIX = ".md"
POINTER_NOTE_NAME = "p13-memory.md"
PROJECTION_AUTHORITY_CLASS = "DERIVED_COUNTS_ONLY_PROJECTION_NON_AUTHORITY"
#: A4a の再検証は呼び出し側の object から作り直した byte に対するもの（A3 の store から読んだことの証明ではない）
SOURCE_ATTESTATION = "A4A_RECHECKED_RECORD_BYTES_STORE_READ_NOT_ATTESTED"
ABORT_REASONS = ("OPERATOR_ABORT", "VERIFICATION_FAILED")
MAX_RENDERED_COUNT = 9999
MAX_NOTE_BYTES = 1024 * 1024
MAX_NOTE_LINE_CHARS = 512
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
SHORT_ID_COLLISION = "SHORT_ID_COLLISION"
RECORD_CORRUPT = "RECORD_CORRUPT"
EVIDENCE_DIGEST_MISMATCH = "EVIDENCE_DIGEST_MISMATCH"
MANIFEST_MISSING = "MANIFEST_MISSING"
MANIFEST_CONFLICT = "MANIFEST_CONFLICT"
UNREFERENCED_MANIFEST = "UNREFERENCED_MANIFEST"
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
AMBIGUOUS_STAGING_AND_VERSION = "AMBIGUOUS_STAGING_AND_VERSION"
REPUBLICATION_OF_KNOWN_VERSION = "REPUBLICATION_OF_KNOWN_VERSION"
TARGET_CONFLICTS_WITH_OPEN_INTENT = "TARGET_CONFLICTS_WITH_OPEN_INTENT"
TARGET_REQUIRED_FOR_STAGING = "TARGET_REQUIRED_FOR_STAGING"
OBSERVATION_INVALID = "OBSERVATION_INVALID"
UNSAFE_RECOVERY_PROPOSAL = "UNSAFE_RECOVERY_PROPOSAL"
PROJECTION_CODES = frozenset({PROJECTION_INPUT_INVALID, SOURCE_UNVERIFIED, SOURCE_DIGEST_MISMATCH, SCHEMA_UNSUPPORTED, CATEGORY_UNAPPROVED,
                              COUNT_OUT_OF_RANGE, NOTE_INVALID, PRIVATE_SHAPE_DETECTED, SHORT_ID_COLLISION, RECORD_CORRUPT,
                              EVIDENCE_DIGEST_MISMATCH, MANIFEST_MISSING, MANIFEST_CONFLICT, UNREFERENCED_MANIFEST, POINTER_INVALID,
                              POINTER_MISSING, POINTER_UNEXPECTED, POINTER_WITHOUT_EVIDENCE, INTENT_REFERENCE_MISSING,
                              CONTRADICTORY_INTENT, INTENT_CHAIN_INVALID, MULTIPLE_OPEN_INTENTS, UNKNOWN_OBJECT, UNREFERENCED_VERSION,
                              VERSION_UNVERIFIED, PREVIOUS_VERSION_MISSING, ORPHAN_STAGING, STAGING_OF_CLOSED_INTENT, STAGING_UNVERIFIED,
                              AMBIGUOUS_STAGING_AND_VERSION, REPUBLICATION_OF_KNOWN_VERSION, TARGET_CONFLICTS_WITH_OPEN_INTENT,
                              TARGET_REQUIRED_FOR_STAGING, OBSERVATION_INVALID, UNSAFE_RECOVERY_PROPOSAL})

#: 承認した構造の分類の code（凍結の P9 の enum の値と同じ ・test が凍結の enum との完全一致を確かめる）。これ以外の分類は fail closed
APPROVED_CATEGORY_CODES: Tuple[Tuple[str, Tuple[str, ...]], ...] = (
    ("watch_status_counts", ("ACTIVE", "PAUSED", "REMOVED")),
    ("watch_provenance_kind_counts", ("MANUAL", "P8_PROPOSAL")),
    ("thesis_status_counts", ("ACTIVE", "CHALLENGED", "INVALIDATED", "RETIRED")),
    ("thesis_invalidation_basis_counts", ("CONDITIONS", "OTHER")),
    ("thesis_supporting_evidence_kind_counts", ("HUMAN_NOTE", "P8_SCREEN_RESULT")),
    ("thesis_counter_evidence_kind_counts", ("HUMAN_NOTE", "P8_SCREEN_RESULT")),
)
_INDEX_FIELDS = ("projection_schema", "projection_rules", "projection_digest", "generation_id", "generation_digest", "source_manifest_digest",
                 "adapter_rules", "personal_projection_schema_version", "p9_safe_view_schema_version", "p9_view_rules_version",
                 "review_view_schema_version", "sample_count", "interval_count", "first_sample_cutoff_date", "last_sample_cutoff_date")
_VIEW_FIELDS = ("personal_projection_schema_version", "p9_safe_view_schema_version", "p9_view_rules_version", "review_view_schema_version")
_SAMPLE_IDENTITY_FIELDS = ("sample_id", "sample_digest", "sample_cutoff_date", "active_profile_present")
_REVIEW_COUNT_FIELDS = ("live_focus_marks", "live_mute_marks", "cleared_marks", "unmatched_live_marks")
_P9_SCALAR_FIELDS = ("watch_count", "watch_review_due_count", "watch_declared_thesis_link_count", "thesis_count", "thesis_review_due_count")
_INTERVAL_IDENTITY_FIELDS = ("interval_id", "from_sample_id", "to_sample_id", "after_sample_cutoff_date", "through_sample_cutoff_date",
                             "change_record_count")
#: 表の行の先頭に在ってよい欄の名前（構造の名前だけ ・値ではない）
ALLOWED_FIELD_LABELS = frozenset(_INDEX_FIELDS + _SAMPLE_IDENTITY_FIELDS + _REVIEW_COUNT_FIELDS + _P9_SCALAR_FIELDS + _INTERVAL_IDENTITY_FIELDS
                                 + tuple(PERSONAL_COUNT_KEYS) + tuple(name for name, _ in APPROVED_CATEGORY_CODES) + STRUCTURAL_FIELDS)
ALLOWED_CODES = frozenset({code for _, codes in APPROVED_CATEGORY_CODES for code in codes} | {k.value for k in RecordKind}
                          | {k.value for k in ChangeKind})

TITLE_INDEX = "# Review State Memory の投影（counts-only）"
TITLE_SAMPLE = "# Review State Memory の標本（counts-only）"
TITLE_INTERVAL = "# Review State Memory の区間の端点の差（counts-only）"
TITLE_POINTER = "# Review State Memory の投影の pointer"
DERIVED_NOTICE = ("この note は private な Market Memory の generation から決定論で作った派生の投影であり、system の authority ではない。",
                  "件数 ・承認した構造の分類 ・日付 ・version ・digest だけを示す（個々の項目 ・発行体 ・本文 ・時刻 ・位置は含まない）。",
                  "標本の cutoff の日は標本を取った区切りの日であり、source の known_at（source が知られた時刻）ではない。")
INTERVAL_NOTICE = ("変化は隣接する 2 つの標本の端点の差の件数だけであり、区間の中の遷移の時刻 ・回数 ・経路ではない。",
                   "端点が一致しても、区間の中で変化が無かったことの証明ではない。")
VERSION_NOTICE = ("この版の folder は不変であり、前の有効な版は消さず ・移さず ・archive せずにそのまま残す。",)
POINTER_NOTICE = ("この pointer は検証済みの 1 つの版を指す。pointer の置換は Obsidian の表示の不可分な更新を保証しない。",
                  "pointer は system の authority ではない（authority は private な証拠の record に在る）。")
HEADING_IDENTITY = "## 識別"
HEADING_SAMPLES = "## 標本"
HEADING_INTERVALS = "## 区間"
HEADING_REVIEW = "## 見直しの件数"
HEADING_P9 = "## P9 の件数"
HEADING_CATEGORIES = "## P9 の分類の件数"
HEADING_KINDS = "## 種類ごとの変化の件数"
HEADING_FIELDS = "## 構造の欄ごとの変化の件数"
NO_INTERVALS_LINE = "標本が 1 つなので区間は無い。"
VALUE_TABLE = ("| field | value |", "| --- | --- |")
COUNT_TABLE = ("| field | count |", "| --- | --- |")
CATEGORY_TABLE = ("| field | category | count |", "| --- | --- | --- |")
KIND_TABLE = ("| record_kind | change_kind | count |", "| --- | --- | --- |")
FIXED_LINES = frozenset({TITLE_INDEX, TITLE_SAMPLE, TITLE_INTERVAL, TITLE_POINTER, *DERIVED_NOTICE, *INTERVAL_NOTICE, *VERSION_NOTICE,
                         *POINTER_NOTICE, HEADING_IDENTITY, HEADING_SAMPLES, HEADING_INTERVALS, HEADING_REVIEW, HEADING_P9,
                         HEADING_CATEGORIES, HEADING_KINDS, HEADING_FIELDS, NO_INTERVALS_LINE, *VALUE_TABLE, *COUNT_TABLE,
                         *CATEGORY_TABLE, *KIND_TABLE})

#: private な形の走査（文法とは独立の 2 つ目の層 ・note の全文）。凍結の guard の形を文字の class で表す（source に private の文字列
#: そのものは置かない）。どれか 1 つでも当たれば fail closed
PRIVATE_SHAPE_PATTERNS: Tuple[Tuple[str, str], ...] = (
    ("DRIVE_LOCATION", r"[A-Za-z]:[\\/]"),
    ("BACKSLASH", r"[\\]"),
    ("SLASH", r"[/]"),
    ("INSTANT", r"[0-9]{4}-[0-9]{2}-[0-9]{2}[Tt ][0-9]{1,2}:[0-9]{2}"),
    ("TIME_OF_DAY", r"(?<![0-9A-Za-z_.])[0-9]{1,2}:[0-9]{2}(?![0-9])"),
    ("LONG_NUMBER", r"\b[0-9]{5,}\b"),
    ("FROZEN_ID_PREFIX", r"p(?:[0-9]|1[0-2])[a-z]{3}_"),
    ("AUTHOR_PREFIX", r"[Hh][Uu][Mm][Aa][Nn]\s*:"),
    ("KEY_HEADER", r"[Xx]-[Aa][Pp][Ii]-[Kk][Ee][Yy]"),
    ("PROVIDER", r"[Jj][Qq][Uu][Aa][Nn][Tt][Ss]"),
    ("ACCESS_WORD", r"(?i)\b(?:password|passwd|api[_-]?key|bearer|authorization|refresh[_-]?key|secret)\b"),
    ("SID", r"S-1-[0-9]+-[0-9]"),
    ("URL", r"(?i)://|\bwww\.|\b(?:javascript|vbscript|data|file|mailto|obsidian|https?):"),
    ("HTML", r"<[A-Za-z!/?]|&[A-Za-z#][A-Za-z0-9]*;"),
    ("EMBED", r"!\["),
    ("CODE", r"`|~~~"),
    ("TEMPLATE", r"<%|%>|\{\{|\}\}|\$\{|\$"),
    ("COMMENT_OR_FOOTNOTE", r"%%|\[\^"),
)
_PRIVATE_SHAPES = tuple((label, re.compile(pattern)) for label, pattern in PRIVATE_SHAPE_PATTERNS)
_CONTROL_RE = re.compile(r"[\x00-\x09\x0b-\x1f\x7f-\x9f­؜᠎​-‏ -‮⁠-⁤⁦-⁯﻿￹-￻]")
_FRONTMATTER_LINE_RE = re.compile(r'^(p13_[a-z_]{1,32}): "([^"\\]{1,128})"$')
_TABLE_ROW_RE = re.compile(r"^\| ([^|]{1,128}) \| ([^|]{1,128}) \|(?: ([^|]{1,128}) \|)?$")
_LINK_ITEM_RE = re.compile(r"^- \[\[(p13prj_[0-9a-f]{24}(?:-p13(?:smp|int)_[0-9a-f]{24})?)\]\]$")
_NOTE_NAME_RE = re.compile(r"^(p13prj_[0-9a-f]{24})(?:-p13(?:smp|int)_[0-9a-f]{24})?\.md$")
_VERSION_LABEL_RE = re.compile(r"^p13prj_[0-9a-f]{24}$")
_INT_CELL_RE = re.compile(r"^(?:0|[1-9][0-9]{0,3})$")
_DATE_CELL_RE = re.compile(r"^[0-9]{4}-[0-9]{2}-[0-9]{2}$")
_LABEL_CELL_RE = re.compile(r"^p13(?:prj|exp|gen|smp|int)_[0-9a-f]{24}$")
_VERSION_CELL_RE = re.compile(r"^[a-z][a-z0-9_]{0,63}:[0-9]{1,3}\.[0-9]{1,3}\.[0-9]{1,3}$")
_POINTER_DIGEST_RE = re.compile(r'^p13_(projection|export): "([0-9a-f]{64})"$')
_FRONTMATTER_VALUES = {"p13_schema": frozenset({PROJECTION_SCHEMA_VERSION, POINTER_SCHEMA_VERSION}),
                       "p13_rules": frozenset({PROJECTION_RULES_VERSION}),
                       "p13_note": frozenset({"VERSION_INDEX", "SAMPLE", "INTERVAL", "POINTER"})}
_FRONTMATTER_DIGEST_KEYS = frozenset({"p13_projection", "p13_generation", "p13_source_manifest", "p13_sample", "p13_from_sample",
                                      "p13_to_sample", "p13_export"})
#: note の種類ごとの frontmatter の鍵の列（順序つきの完全一致）と schema
_FRONTMATTER_LAYOUT = {
    "VERSION_INDEX": (PROJECTION_SCHEMA_VERSION, ("p13_schema", "p13_rules", "p13_note", "p13_projection", "p13_generation",
                                                  "p13_source_manifest")),
    "SAMPLE": (PROJECTION_SCHEMA_VERSION, ("p13_schema", "p13_rules", "p13_note", "p13_sample")),
    "INTERVAL": (PROJECTION_SCHEMA_VERSION, ("p13_schema", "p13_rules", "p13_note", "p13_from_sample", "p13_to_sample")),
    "POINTER": (POINTER_SCHEMA_VERSION, ("p13_schema", "p13_note", "p13_projection", "p13_export")),
}


class ProjectionError(ValueError):
    """投影の失敗（固定の code ・短い detail だけ。値 ・本文 ・位置は持たない）。"""

    def __init__(self, code: str, detail: str = "") -> None:
        super().__init__(f"{code}:{detail}" if detail else code)
        self.code = code
        self.detail = detail


def _require(condition: Any, code: str, detail: str = "") -> None:
    if not condition:
        raise ProjectionError(code, detail)


def _no_collision(pairs: Sequence[Tuple[str, str]]) -> None:
    try:
        assert_no_short_id_collision(sorted(pairs))
    except CanonicalError:
        raise ProjectionError(SHORT_ID_COLLISION, "LABEL") from None


class NoteKind(str, Enum):
    VERSION_INDEX = "VERSION_INDEX"
    SAMPLE = "SAMPLE"
    INTERVAL = "INTERVAL"
    POINTER = "POINTER"


class PublicationState(str, Enum):
    """観測した byte の分類。完了を記録した状態は PUBLISHED_VERIFIED（中断した操作は開いた intent の状態か FAIL_CLOSED）。"""

    FIRST_PUBLICATION = "FIRST_PUBLICATION"
    PUBLISHED_VERIFIED = "PUBLISHED_VERIFIED"
    NO_CHANGE = "NO_CHANGE"
    INTENT_PREPARED = "INTENT_PREPARED"
    STAGED_VERIFIED = "STAGED_VERIFIED"
    VERSION_VERIFIED = "VERSION_VERIFIED"
    POINTER_SWITCHED = "POINTER_SWITCHED"
    FAIL_CLOSED = "FAIL_CLOSED"


class ProposedAction(str, Enum):
    """提案するだけの次の 1 つの遷移。前の版を archive ・削除 ・移動する action は無い（存在しない）。"""

    NONE = "NONE"
    PREPARE_INTENT = "PREPARE_INTENT"
    STAGE_VERSION = "STAGE_VERSION"
    MOVE_STAGED_TO_VERSION = "MOVE_STAGED_TO_VERSION"
    REPLACE_POINTER = "REPLACE_POINTER"
    RECORD_COMPLETION = "RECORD_COMPLETION"
    HOLD = "HOLD"


class RecoveryEligibility(str, Enum):
    NOT_REQUIRED = "NOT_REQUIRED"
    AUTO_CONVERGE_ELIGIBLE = "AUTO_CONVERGE_ELIGIBLE"
    HOLD_FAIL_CLOSED = "HOLD_FAIL_CLOSED"


#: 自動の収束の候補になりうる遷移（検証済みの開いた intent の続きだけ。新しい intent の準備 ・HOLD は含まない）
AUTO_CONVERGE_ACTIONS = (ProposedAction.STAGE_VERSION, ProposedAction.MOVE_STAGED_TO_VERSION, ProposedAction.REPLACE_POINTER,
                         ProposedAction.RECORD_COMPLETION)
EVIDENCE_MANIFEST = "MANIFEST"
EVIDENCE_INTENT = "INTENT"
EVIDENCE_COMPLETION = "COMPLETION"
EVIDENCE_ABORT = "ABORT"


# ---------------------------------------------------------------- 入力（明示の完全な digest ・純粋な再検証）


@dataclass(frozen=True, kw_only=True)
class ProjectionInput:
    """明示の完全な generation digest ・manifest digest と、byte から純粋に再検証した generation（store の読みの証明ではない）。"""

    verified: VerifiedGeneration = field(repr=False)
    generation_digest: str
    manifest_digest: str
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

    def plan_content(self) -> Dict[str, str]:
        return {"schema_version": PROJECTION_SCHEMA_VERSION, "rules_version": PROJECTION_RULES_VERSION,
                "generation_digest": self.generation_digest, "source_manifest_digest": self.manifest_digest,
                "authority_class": PROJECTION_AUTHORITY_CLASS}

    @property
    def projection_digest(self) -> str:
        return domain_digest(PROJECTION_DOMAIN, self.plan_content())

    @property
    def version_label(self) -> str:
        return short_id(VERSION_LABEL_PREFIX, self.projection_digest)


def build_projection_input(verified: VerifiedGeneration, *, generation_digest: str, manifest_digest: str) -> ProjectionInput:
    """明示の完全な digest が必須（既定 ・「最新」の選択は無い）。"""
    return ProjectionInput(verified=verified, generation_digest=generation_digest, manifest_digest=manifest_digest)


# ---------------------------------------------------------------- Markdown の文法 ・private の形の走査


def scan_private_shapes(text: Any) -> Tuple[str, ...]:
    """当たった private の形の label（固定の順）。"""
    _require(isinstance(text, str), NOTE_INVALID, "TEXT")
    return tuple(label for label, pattern in _PRIVATE_SHAPES if pattern.search(text))


def _cell_ok(cell: str) -> bool:
    if cell in ALLOWED_FIELD_LABELS or cell in ALLOWED_CODES or cell in ("true", "false"):
        return True
    if _INT_CELL_RE.match(cell) or is_digest(cell) or _LABEL_CELL_RE.match(cell) or _VERSION_CELL_RE.match(cell):
        return True
    if _DATE_CELL_RE.match(cell):
        try:
            parse_date_iso(cell)
        except (CanonicalError, ValueError):
            return False
        return True
    return False


def _frontmatter_ok(key: str, value: str) -> bool:
    if key in _FRONTMATTER_DIGEST_KEYS:
        return is_digest(value)
    return key in _FRONTMATTER_VALUES and value in _FRONTMATTER_VALUES[key]


def validate_note(data: Any) -> None:
    """byte の規則 → private の形の走査 → 行の文法（frontmatter ・固定の行 ・表の行 ・固定の link だけ）。外れれば fail closed。"""
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
    values: Dict[str, str] = {}
    for line in lines[1:close]:
        match = _FRONTMATTER_LINE_RE.match(line)
        _require(match is not None, NOTE_INVALID, "FRONTMATTER_LINE")
        key, value = match.group(1), match.group(2)
        _require(key not in values and _frontmatter_ok(key, value), NOTE_INVALID, "FRONTMATTER_VALUE")
        values[key] = value
    layout = _FRONTMATTER_LAYOUT.get(values.get("p13_note", ""))
    _require(layout is not None and tuple(values) == layout[1] and values["p13_schema"] == layout[0], NOTE_INVALID, "FRONTMATTER_KEYS")
    for line in lines[close + 1:]:
        _require(len(line) <= MAX_NOTE_LINE_CHARS and line == line.strip(), NOTE_INVALID, "LINE_SHAPE")
        if line == "" or line in FIXED_LINES:
            continue
        row = _TABLE_ROW_RE.match(line)
        if row is not None:
            _require(all(_cell_ok(cell) for cell in row.groups() if cell is not None), NOTE_INVALID, "TABLE_CELL")
            continue
        _require(_LINK_ITEM_RE.match(line) is not None, NOTE_INVALID, "LINE")


def _frontmatter(*pairs: Tuple[str, str]) -> list:
    return ["---", *(f'{key}: "{value}"' for key, value in pairs), "---"]


def _table(header: Tuple[str, str], rows: Sequence[Tuple[str, ...]]) -> list:
    return [header[0], header[1], *("| " + " | ".join(cells) + " |" for cells in rows)]


def _note_bytes(lines: Sequence[str]) -> bytes:
    data = ("\n".join(lines) + "\n").encode("utf-8")
    validate_note(data)
    return data


def _count_cell(value: Any) -> str:
    _require(type(value) is int and 0 <= value <= MAX_RENDERED_COUNT, COUNT_OUT_OF_RANGE, "COUNT")
    return str(value)


def _bool_cell(value: Any) -> str:
    _require(type(value) is bool, PROJECTION_INPUT_INVALID, "BOOL")
    return "true" if value else "false"


def _version_cell(value: Any) -> str:
    _require(isinstance(value, str) and _VERSION_CELL_RE.match(value) is not None, PROJECTION_INPUT_INVALID, "VERSION_LABEL")
    return value


def _link(name: str) -> str:
    return f"- [[{name[:-len(NOTE_SUFFIX)]}]]"


# ---------------------------------------------------------------- counts-only の note（項目 ・瞬間は読まない）


def _sample_note(sample: Any) -> bytes:
    counts = sample.counts.content()
    p9 = counts["p9"]
    personal = dict(sample.counts.personal)
    _require(set(personal) == PERSONAL_COUNT_KEYS, PROJECTION_INPUT_INVALID, "PERSONAL_FIELDS")
    _require(set(p9) == set(_P9_SCALAR_FIELDS) | {name for name, _ in APPROVED_CATEGORY_CODES}, PROJECTION_INPUT_INVALID, "P9_FIELDS")
    identity = [("sample_id", sample.sample_id), ("sample_digest", sample.sample_digest),
                ("sample_cutoff_date", date_iso(sample.cutoff.as_of_date)),
                ("active_profile_present", _bool_cell(counts["active_profile_present"]))]
    review = [(name, _count_cell(counts[name])) for name in _REVIEW_COUNT_FIELDS]
    review += [(name, _count_cell(personal[name])) for name in sorted(PERSONAL_COUNT_KEYS)]
    scalars = [(name, _count_cell(p9[name])) for name in _P9_SCALAR_FIELDS]
    categories = []
    for name, codes in APPROVED_CATEGORY_CODES:
        observed = {pair[0]: pair[1] for pair in p9[name]}
        _require(set(observed) <= set(codes), CATEGORY_UNAPPROVED, name.upper())
        categories += [(name, code, _count_cell(observed.get(code, 0))) for code in codes]
    return _note_bytes([*_frontmatter(("p13_schema", PROJECTION_SCHEMA_VERSION), ("p13_rules", PROJECTION_RULES_VERSION),
                                      ("p13_note", NoteKind.SAMPLE.value), ("p13_sample", sample.sample_digest)),
                        "", TITLE_SAMPLE, "", *DERIVED_NOTICE, "", HEADING_IDENTITY, "", *_table(VALUE_TABLE, identity),
                        "", HEADING_REVIEW, "", *_table(COUNT_TABLE, review), "", HEADING_P9, "", *_table(COUNT_TABLE, scalars),
                        "", HEADING_CATEGORIES, "", *_table(CATEGORY_TABLE, categories)])


def interval_digest(from_sample_digest: str, to_sample_digest: str) -> str:
    _require(is_digest(from_sample_digest) and is_digest(to_sample_digest), PROJECTION_INPUT_INVALID, "INTERVAL")
    return domain_digest(INTERVAL_DOMAIN, {"schema_version": PROJECTION_SCHEMA_VERSION, "rules_version": PROJECTION_RULES_VERSION,
                                           "from_sample_digest": from_sample_digest, "to_sample_digest": to_sample_digest})


def _interval_note(earlier: Any, later: Any, changes: Sequence[Any]) -> Tuple[str, str, bytes]:
    digest = interval_digest(earlier.sample_digest, later.sample_digest)
    interval_id = short_id(INTERVAL_ID_PREFIX, digest)
    by_kind = {(record.value, kind.value): 0 for record in RecordKind for kind in ChangeKind}
    by_field = {name: 0 for name in STRUCTURAL_FIELDS}
    for change in changes:
        by_kind[(change.record_kind.value, change.kind.value)] += 1
        for item in change.changed_fields:                               # 欄の名前だけを数える（前後の値は読まない）
            by_field[item[0]] += 1
    identity = [("interval_id", interval_id), ("from_sample_id", earlier.sample_id), ("to_sample_id", later.sample_id),
                ("after_sample_cutoff_date", date_iso(earlier.cutoff.as_of_date)),
                ("through_sample_cutoff_date", date_iso(later.cutoff.as_of_date)), ("change_record_count", _count_cell(len(changes)))]
    kinds = [(record, kind, _count_cell(count)) for (record, kind), count in by_kind.items()]
    fields_ = [(name, _count_cell(by_field[name])) for name in sorted(STRUCTURAL_FIELDS)]
    data = _note_bytes([*_frontmatter(("p13_schema", PROJECTION_SCHEMA_VERSION), ("p13_rules", PROJECTION_RULES_VERSION),
                                      ("p13_note", NoteKind.INTERVAL.value), ("p13_from_sample", earlier.sample_digest),
                                      ("p13_to_sample", later.sample_digest)),
                        "", TITLE_INTERVAL, "", *DERIVED_NOTICE, *INTERVAL_NOTICE, "", HEADING_IDENTITY, "",
                        *_table(VALUE_TABLE, identity), "", HEADING_KINDS, "", *_table(KIND_TABLE, kinds), "", HEADING_FIELDS, "",
                        *_table(COUNT_TABLE, fields_)])
    return interval_id, digest, data


def _index_note(source: ProjectionInput, sample_names: Sequence[str], interval_names: Sequence[str]) -> bytes:
    generation = source.verified.generation
    view = generation.view_identity.content()
    _require(set(view) == set(_VIEW_FIELDS), PROJECTION_INPUT_INVALID, "VIEW_FIELDS")
    rows = [("projection_schema", PROJECTION_SCHEMA_VERSION), ("projection_rules", PROJECTION_RULES_VERSION),
            ("projection_digest", source.projection_digest), ("generation_id", generation.generation_id),
            ("generation_digest", source.generation_digest), ("source_manifest_digest", source.manifest_digest),
            ("adapter_rules", _version_cell(generation.adapter_rules_version)),
            *((name, _version_cell(view[name])) for name in _VIEW_FIELDS),
            ("sample_count", _count_cell(len(generation.samples))), ("interval_count", _count_cell(len(interval_names))),
            ("first_sample_cutoff_date", date_iso(generation.cutoffs[0].as_of_date)),
            ("last_sample_cutoff_date", date_iso(generation.cutoffs[-1].as_of_date))]
    intervals = [_link(name) for name in interval_names] or [NO_INTERVALS_LINE]
    return _note_bytes([*_frontmatter(("p13_schema", PROJECTION_SCHEMA_VERSION), ("p13_rules", PROJECTION_RULES_VERSION),
                                      ("p13_note", NoteKind.VERSION_INDEX.value), ("p13_projection", source.projection_digest),
                                      ("p13_generation", source.generation_digest), ("p13_source_manifest", source.manifest_digest)),
                        "", TITLE_INDEX, "", *DERIVED_NOTICE, *VERSION_NOTICE, "", HEADING_IDENTITY, "", *_table(VALUE_TABLE, rows),
                        "", HEADING_SAMPLES, "", *(_link(name) for name in sample_names), "", HEADING_INTERVALS, "", *intervals])


# ---------------------------------------------------------------- export の manifest（export digest）・投影


@dataclass(frozen=True, kw_only=True)
class ExportFile:
    name: str
    size: int
    sha256: str

    def __post_init__(self) -> None:
        _require(isinstance(self.name, str) and _NOTE_NAME_RE.match(self.name) is not None, RECORD_CORRUPT, "EXPORT_FILE_NAME")
        _require(type(self.size) is int and 0 < self.size <= MAX_NOTE_BYTES, RECORD_CORRUPT, "EXPORT_FILE_SIZE")
        _require(is_digest(self.sha256), RECORD_CORRUPT, "EXPORT_FILE_SHA256")


@dataclass(frozen=True, kw_only=True)
class ExportManifest:
    """1 つの版の folder の全 note（名前で sort ・重複無し）の名前 ・長さ ・sha256 と、投影の計画 ・source の完全な digest。"""

    projection_digest: str
    generation_digest: str
    source_manifest_digest: str
    files: Tuple[ExportFile, ...]
    rules_version: str = PROJECTION_RULES_VERSION
    schema_version: str = EXPORT_MANIFEST_SCHEMA_VERSION

    def __post_init__(self) -> None:
        _require(self.schema_version == EXPORT_MANIFEST_SCHEMA_VERSION and self.rules_version == PROJECTION_RULES_VERSION,
                 SCHEMA_UNSUPPORTED, "EXPORT_MANIFEST")
        _require(is_digest(self.projection_digest) and is_digest(self.generation_digest) and is_digest(self.source_manifest_digest),
                 RECORD_CORRUPT, "EXPORT_MANIFEST_DIGESTS")
        _require(isinstance(self.files, tuple) and all(isinstance(f, ExportFile) for f in self.files), RECORD_CORRUPT, "EXPORT_FILES")
        names = [f.name for f in self.files]
        _require(1 <= len(names) <= MAX_EXPORT_FILES and names == sorted(names) and len(set(names)) == len(names), RECORD_CORRUPT,
                 "EXPORT_FILE_ORDER")
        _require(all(_NOTE_NAME_RE.match(n).group(1) == self.version_label for n in names), RECORD_CORRUPT, "EXPORT_FILE_LABEL")
        _require(self.version_label + NOTE_SUFFIX in names, RECORD_CORRUPT, "EXPORT_INDEX")

    @property
    def version_label(self) -> str:
        return short_id(VERSION_LABEL_PREFIX, self.projection_digest)

    def content(self) -> Dict[str, Any]:
        return {"schema_version": self.schema_version, "rules_version": self.rules_version, "projection_digest": self.projection_digest,
                "generation_digest": self.generation_digest, "source_manifest_digest": self.source_manifest_digest,
                "files": [[f.name, f.size, f.sha256] for f in self.files]}

    def to_bytes(self) -> bytes:
        return record_bytes(self.content())

    @property
    def export_digest(self) -> str:
        return domain_digest(EXPORT_DOMAIN, self.content())

    @property
    def export_id(self) -> str:
        return short_id(EXPORT_ID_PREFIX, self.export_digest)


def _verify_notes(notes: Any, manifest: ExportManifest, code: str) -> None:
    """観測した note の写像を manifest と完全一致で照らす（欠落 ・余分 ・長さ ・sha256 ・文法 ・private の形）。"""
    _require(isinstance(notes, Mapping) and all(isinstance(n, str) and isinstance(d, bytes) for n, d in notes.items()),
             OBSERVATION_INVALID, "NOTES")
    _require(sorted(notes) == [f.name for f in manifest.files], code, "FILE_SET")
    for entry in manifest.files:
        data = notes[entry.name]
        _require(len(data) == entry.size and sha256_hex(data) == entry.sha256, code, "SIZE_OR_SHA256")
        try:
            validate_note(data)
        except ProjectionError:
            raise ProjectionError(code, "NOTE") from None


@dataclass(frozen=True, kw_only=True)
class ProjectionExport:
    """1 つの再検証済みの generation から決定論で作った版（note の byte と manifest）。同じ入力からは byte 一致。"""

    source: ProjectionInput = field(repr=False)
    notes: Tuple[Tuple[str, bytes], ...] = field(repr=False)
    manifest: ExportManifest

    def __post_init__(self) -> None:
        _require(isinstance(self.source, ProjectionInput) and isinstance(self.manifest, ExportManifest), PROJECTION_INPUT_INVALID, "EXPORT")
        _require(self.manifest.projection_digest == self.source.projection_digest
                 and self.manifest.generation_digest == self.source.generation_digest
                 and self.manifest.source_manifest_digest == self.source.manifest_digest, MANIFEST_CONFLICT, "EXPORT_SOURCE")
        _require(isinstance(self.notes, tuple), PROJECTION_INPUT_INVALID, "NOTES")
        _verify_notes(dict(self.notes), self.manifest, MANIFEST_CONFLICT)

    def note_map(self) -> Dict[str, bytes]:
        return dict(self.notes)

    @property
    def export_digest(self) -> str:
        return self.manifest.export_digest

    @property
    def version_label(self) -> str:
        return self.manifest.version_label

    def pointer_note(self) -> bytes:
        return render_pointer(self.manifest)


def render_projection(source: ProjectionInput) -> ProjectionExport:
    """counts-only の版を作る: 標本ごとの note ・隣接する標本の区間の note ・版の index。全て文法 ・走査を通る。"""
    _require(isinstance(source, ProjectionInput), PROJECTION_INPUT_INVALID, "SOURCE")
    generation = source.verified.generation
    label = source.version_label
    notes: Dict[str, bytes] = {}
    sample_names = []
    for sample in generation.samples:
        name = f"{label}-{sample.sample_id}{NOTE_SUFFIX}"
        notes[name] = _sample_note(sample)
        sample_names.append(name)
    interval_names, identities, accounted = [], [], 0
    for earlier, later in zip(generation.samples, generation.samples[1:]):
        changes = tuple(c for c in generation.changes
                        if c.from_sample_digest == earlier.sample_digest and c.to_sample_digest == later.sample_digest)
        accounted += len(changes)
        interval_id, digest, data = _interval_note(earlier, later, changes)
        identities.append((interval_id, digest))
        name = f"{label}-{interval_id}{NOTE_SUFFIX}"
        notes[name] = data
        interval_names.append(name)
    _require(accounted == len(generation.changes), SOURCE_UNVERIFIED, "CHANGES_UNACCOUNTED")
    _no_collision(identities)
    notes[label + NOTE_SUFFIX] = _index_note(source, sample_names, interval_names)
    ordered = tuple(sorted(notes.items()))
    manifest = ExportManifest(projection_digest=source.projection_digest, generation_digest=source.generation_digest,
                              source_manifest_digest=source.manifest_digest,
                              files=tuple(ExportFile(name=n, size=len(d), sha256=sha256_hex(d)) for n, d in ordered))
    return ProjectionExport(source=source, notes=ordered, manifest=manifest)


# ---------------------------------------------------------------- pointer の note（1 つの file ・検証して置き換える）


@dataclass(frozen=True, kw_only=True)
class PointerRecord:
    projection_digest: str
    export_digest: str

    @property
    def version_label(self) -> str:
        return short_id(VERSION_LABEL_PREFIX, self.projection_digest)


def _pointer_bytes(projection_digest: str, export_digest: str) -> bytes:
    _require(is_digest(projection_digest) and is_digest(export_digest), POINTER_INVALID, "DIGESTS")
    return _note_bytes([*_frontmatter(("p13_schema", POINTER_SCHEMA_VERSION), ("p13_note", NoteKind.POINTER.value),
                                      ("p13_projection", projection_digest), ("p13_export", export_digest)),
                        "", TITLE_POINTER, "", *POINTER_NOTICE, "",
                        _link(short_id(VERSION_LABEL_PREFIX, projection_digest) + NOTE_SUFFIX)])


def render_pointer(manifest: ExportManifest) -> bytes:
    _require(isinstance(manifest, ExportManifest), POINTER_INVALID, "MANIFEST")
    return _pointer_bytes(manifest.projection_digest, manifest.export_digest)


def parse_pointer(data: Any) -> PointerRecord:
    """pointer の厳密な読み: 2 つの完全な digest を取り出し、作り直した byte と完全一致すること（それ以外は POINTER_INVALID）。"""
    _require(isinstance(data, bytes) and 0 < len(data) <= MAX_NOTE_BYTES, POINTER_INVALID, "BYTES")
    try:
        lines = data.decode("utf-8").split("\n")
    except UnicodeDecodeError:
        raise ProjectionError(POINTER_INVALID, "UTF8") from None
    found = {}
    for line in lines[3:5]:
        match = _POINTER_DIGEST_RE.match(line)
        if match is not None:
            found[match.group(1)] = match.group(2)
    _require(set(found) == {"projection", "export"}, POINTER_INVALID, "FIELDS")
    try:
        expected = _pointer_bytes(found["projection"], found["export"])
    except ProjectionError:
        raise ProjectionError(POINTER_INVALID, "RENDER") from None
    _require(expected == data, POINTER_INVALID, "NON_CANONICAL")
    return PointerRecord(projection_digest=found["projection"], export_digest=found["export"])


# ---------------------------------------------------------------- private な証拠の record（intent ・完了 ・中止）


@dataclass(frozen=True, kw_only=True)
class IntentRecord:
    """前の版（無ければ None）から次の版への 1 つの公開の意図。完全性は digest で検証する（暗号の認証ではない）。"""

    to_projection_digest: str
    to_export_digest: str
    generation_digest: str
    source_manifest_digest: str
    previous_projection_digest: Optional[str] = None
    previous_export_digest: Optional[str] = None
    schema_version: str = INTENT_SCHEMA_VERSION

    def __post_init__(self) -> None:
        _require(self.schema_version == INTENT_SCHEMA_VERSION, SCHEMA_UNSUPPORTED, "INTENT")
        _require(all(is_digest(d) for d in (self.to_projection_digest, self.to_export_digest, self.generation_digest,
                                             self.source_manifest_digest)), RECORD_CORRUPT, "INTENT_DIGESTS")
        _require((self.previous_projection_digest is None) == (self.previous_export_digest is None), RECORD_CORRUPT, "INTENT_PREVIOUS")
        _require(self.previous_export_digest is None or (is_digest(self.previous_export_digest)
                                                         and is_digest(self.previous_projection_digest)), RECORD_CORRUPT, "INTENT_PREVIOUS")
        _require(self.previous_export_digest != self.to_export_digest, RECORD_CORRUPT, "INTENT_SELF")

    def content(self) -> Dict[str, Any]:
        return {"schema_version": self.schema_version, "previous_projection_digest": self.previous_projection_digest,
                "previous_export_digest": self.previous_export_digest, "to_projection_digest": self.to_projection_digest,
                "to_export_digest": self.to_export_digest, "generation_digest": self.generation_digest,
                "source_manifest_digest": self.source_manifest_digest}

    def to_bytes(self) -> bytes:
        return record_bytes(self.content())

    @property
    def intent_digest(self) -> str:
        return domain_digest(INTENT_DOMAIN, self.content())

    @property
    def version_label(self) -> str:
        return short_id(VERSION_LABEL_PREFIX, self.to_projection_digest)


@dataclass(frozen=True, kw_only=True)
class CompletionRecord:
    intent_digest: str
    to_export_digest: str
    schema_version: str = COMPLETION_SCHEMA_VERSION

    def __post_init__(self) -> None:
        _require(self.schema_version == COMPLETION_SCHEMA_VERSION, SCHEMA_UNSUPPORTED, "COMPLETION")
        _require(is_digest(self.intent_digest) and is_digest(self.to_export_digest), RECORD_CORRUPT, "COMPLETION_DIGESTS")

    def content(self) -> Dict[str, str]:
        return {"schema_version": self.schema_version, "intent_digest": self.intent_digest, "to_export_digest": self.to_export_digest}

    def to_bytes(self) -> bytes:
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

    def to_bytes(self) -> bytes:
        return record_bytes(self.content())

    @property
    def abort_digest(self) -> str:
        return domain_digest(ABORT_DOMAIN, self.content())


def intent_for(target: ProjectionExport, previous: Optional[ExportManifest]) -> IntentRecord:
    _require(isinstance(target, ProjectionExport) and (previous is None or isinstance(previous, ExportManifest)),
             PROJECTION_INPUT_INVALID, "INTENT")
    return IntentRecord(to_projection_digest=target.manifest.projection_digest, to_export_digest=target.export_digest,
                        generation_digest=target.manifest.generation_digest, source_manifest_digest=target.manifest.source_manifest_digest,
                        previous_projection_digest=None if previous is None else previous.projection_digest,
                        previous_export_digest=None if previous is None else previous.export_digest)


def completion_for(intent: IntentRecord) -> CompletionRecord:
    _require(isinstance(intent, IntentRecord), PROJECTION_INPUT_INVALID, "COMPLETION")
    return CompletionRecord(intent_digest=intent.intent_digest, to_export_digest=intent.to_export_digest)


def abort_for(intent: IntentRecord, reason: str) -> AbortRecord:
    _require(isinstance(intent, IntentRecord), PROJECTION_INPUT_INVALID, "ABORT")
    return AbortRecord(intent_digest=intent.intent_digest, reason=reason)


_EXPORT_MANIFEST_FIELDS = frozenset({"schema_version", "rules_version", "projection_digest", "generation_digest", "source_manifest_digest",
                                     "files"})
_INTENT_FIELDS = frozenset({"schema_version", "previous_projection_digest", "previous_export_digest", "to_projection_digest",
                            "to_export_digest", "generation_digest", "source_manifest_digest"})
_COMPLETION_FIELDS = frozenset({"schema_version", "intent_digest", "to_export_digest"})
_ABORT_FIELDS = frozenset({"schema_version", "intent_digest", "reason"})


def _parse_record(data: Any, *, schema: str, required: frozenset, context: str) -> Dict[str, Any]:
    """UTF-8 の JSON の mapping ・文字の `schema_version` が支持する版 ・鍵の集合の完全一致（無ければ RECORD_CORRUPT）。"""
    _require(isinstance(data, bytes) and len(data) <= MAX_NOTE_BYTES, RECORD_CORRUPT, context)
    try:
        value = json.loads(data.decode("utf-8"))
    except (ValueError, RecursionError):
        raise ProjectionError(RECORD_CORRUPT, context) from None
    _require(isinstance(value, dict) and isinstance(value.get("schema_version"), str), RECORD_CORRUPT, context)
    _require(value["schema_version"] == schema, SCHEMA_UNSUPPORTED, context)
    _require(set(value) == set(required), RECORD_CORRUPT, f"{context}:FIELDS")
    return value


def _canonical(record: Any, data: bytes, context: str) -> Any:
    _require(record.to_bytes() == data, RECORD_CORRUPT, f"{context}:NON_CANONICAL")
    return record


def parse_export_manifest(data: Any) -> ExportManifest:
    value = _parse_record(data, schema=EXPORT_MANIFEST_SCHEMA_VERSION, required=_EXPORT_MANIFEST_FIELDS, context="EXPORT_MANIFEST")
    files = value["files"]
    _require(isinstance(files, list) and all(isinstance(f, list) and len(f) == 3 for f in files), RECORD_CORRUPT, "EXPORT_FILES")
    try:
        manifest = ExportManifest(projection_digest=value["projection_digest"], generation_digest=value["generation_digest"],
                                  source_manifest_digest=value["source_manifest_digest"], rules_version=value["rules_version"],
                                  files=tuple(ExportFile(name=n, size=s, sha256=h) for n, s, h in files))
    except (AttributeError, TypeError, CanonicalError):
        raise ProjectionError(RECORD_CORRUPT, "EXPORT_MANIFEST") from None
    return _canonical(manifest, data, "EXPORT_MANIFEST")


def parse_intent(data: Any) -> IntentRecord:
    value = _parse_record(data, schema=INTENT_SCHEMA_VERSION, required=_INTENT_FIELDS, context="INTENT")
    try:
        record = IntentRecord(**value)
    except TypeError:
        raise ProjectionError(RECORD_CORRUPT, "INTENT") from None
    return _canonical(record, data, "INTENT")


def parse_completion(data: Any) -> CompletionRecord:
    value = _parse_record(data, schema=COMPLETION_SCHEMA_VERSION, required=_COMPLETION_FIELDS, context="COMPLETION")
    return _canonical(CompletionRecord(**value), data, "COMPLETION")


def parse_abort(data: Any) -> AbortRecord:
    value = _parse_record(data, schema=ABORT_SCHEMA_VERSION, required=_ABORT_FIELDS, context="ABORT")
    return _canonical(AbortRecord(**value), data, "ABORT")


# ---------------------------------------------------------------- 公開の状態の分類 ・回復の適格（純粋 ・提案だけ）


@dataclass(frozen=True, kw_only=True)
class PublicationObservation:
    """A4b が読んだ byte（pointer ・版の folder ・staging ・private な証拠）。A4a は I/O をせず、この写像だけを分類する。"""

    pointer: Optional[bytes] = None
    versions: Mapping[str, Mapping[str, bytes]] = field(default_factory=dict)
    staging: Mapping[str, Mapping[str, bytes]] = field(default_factory=dict)
    manifests: Mapping[str, bytes] = field(default_factory=dict)
    intents: Mapping[str, bytes] = field(default_factory=dict)
    completions: Mapping[str, bytes] = field(default_factory=dict)
    aborts: Mapping[str, bytes] = field(default_factory=dict)


@dataclass(frozen=True, kw_only=True)
class TransitionPlan:
    """提案する 1 つの遷移（追加 ・pointer の置換 ・開いた intent の staging の移動だけ）。`retained_versions` は全て手を触れずに残す。"""

    action: ProposedAction
    intent_digest: Optional[str] = None
    version_label: Optional[str] = None
    evidence: Tuple[Tuple[str, str, bytes], ...] = field(default=(), repr=False)
    staged_notes: Tuple[Tuple[str, bytes], ...] = field(default=(), repr=False)
    expected_pointer: Optional[bytes] = field(default=None, repr=False)
    replacement_pointer: Optional[bytes] = field(default=None, repr=False)
    retained_versions: Tuple[str, ...] = ()


@dataclass(frozen=True, kw_only=True)
class PublicationClassification:
    state: PublicationState
    action: ProposedAction
    recovery: RecoveryEligibility
    code: str
    published_export_digest: Optional[str] = None
    open_intent_digest: Optional[str] = None
    completed_intent_count: int = 0
    aborted_intent_count: int = 0
    retained_versions: Tuple[str, ...] = ()
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
    for group in (observation.manifests, observation.intents, observation.completions, observation.aborts):
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
    """分類の失敗の時も、観測した版の folder の label を全て「残す」として返す（読めなければ空）。"""
    if isinstance(observation, PublicationObservation) and isinstance(observation.versions, Mapping):
        return tuple(sorted(label for label in observation.versions if isinstance(label, str)))
    return ()


def _fail_closed(code: str, observation: Any) -> PublicationClassification:
    return PublicationClassification(state=PublicationState.FAIL_CLOSED, action=ProposedAction.HOLD,
                                     recovery=RecoveryEligibility.HOLD_FAIL_CLOSED, code=code,
                                     retained_versions=_observed_version_labels(observation))


def classify_publication(observation: PublicationObservation, *,
                         target: Optional[ProjectionExport] = None) -> PublicationClassification:
    """観測した byte だけから公開の状態を分類し、次の 1 つの遷移を提案する。検証できない ・曖昧なものは全て FAIL_CLOSED（HOLD）。"""
    try:
        return _classify(observation, target)
    except ProjectionError as exc:
        return _fail_closed(exc.code, observation)


def _classify(observation: PublicationObservation, target: Optional[ProjectionExport]) -> PublicationClassification:
    _check_observation(observation)
    _require(target is None or isinstance(target, ProjectionExport), OBSERVATION_INVALID, "TARGET")
    manifests = _evidence(observation.manifests, parse_export_manifest, lambda r: r.export_digest, "MANIFEST")
    intents = _evidence(observation.intents, parse_intent, lambda r: r.intent_digest, "INTENT")
    completions = _evidence(observation.completions, parse_completion, lambda r: r.completion_digest, "COMPLETION")
    aborts = _evidence(observation.aborts, parse_abort, lambda r: r.abort_digest, "ABORT")

    closing: Dict[str, str] = {}
    for record in completions.values():
        _require(record.intent_digest in intents, INTENT_REFERENCE_MISSING, "COMPLETION")
        _require(record.to_export_digest == intents[record.intent_digest].to_export_digest, CONTRADICTORY_INTENT, "COMPLETION_TARGET")
        _require(record.intent_digest not in closing, CONTRADICTORY_INTENT, "DUPLICATE_CLOSING")
        closing[record.intent_digest] = EVIDENCE_COMPLETION
    for record in aborts.values():
        _require(record.intent_digest in intents, INTENT_REFERENCE_MISSING, "ABORT")
        _require(record.intent_digest not in closing, CONTRADICTORY_INTENT, "COMPLETED_AND_ABORTED")
        closing[record.intent_digest] = EVIDENCE_ABORT

    for intent in intents.values():                                              # intent ごとに 1 つの manifest（完全一致）
        manifest = manifests.get(intent.to_export_digest)
        _require(manifest is not None, MANIFEST_MISSING, "INTENT_TARGET")
        _require(manifest.projection_digest == intent.to_projection_digest and manifest.generation_digest == intent.generation_digest
                 and manifest.source_manifest_digest == intent.source_manifest_digest, MANIFEST_CONFLICT, "INTENT_TARGET")
    targets = [intent.to_export_digest for intent in intents.values()]
    _require(len(set(targets)) == len(targets), REPUBLICATION_OF_KNOWN_VERSION, "SHARED_TARGET")   # 版の所有は 1 つの intent だけ
    _require(set(manifests) <= set(targets), UNREFERENCED_MANIFEST, "MANIFEST")
    projections = [m.projection_digest for m in manifests.values()]
    _require(len(set(projections)) == len(projections), MANIFEST_CONFLICT, "PROJECTION_EXPORTS")
    _no_collision([(m.version_label, m.projection_digest) for m in manifests.values()]
                  + ([(target.version_label, target.manifest.projection_digest)] if target is not None else []))
    _no_collision([(m.export_id, m.export_digest) for m in manifests.values()]
                  + ([(target.manifest.export_id, target.export_digest)] if target is not None else []))

    completed = {d: i for d, i in intents.items() if closing.get(d) == EVIDENCE_COMPLETION}
    chain = []
    head: Optional[IntentRecord] = None
    while completed:                                                             # 完了した intent は None から始まる 1 本の鎖
        following = [d for d, i in completed.items() if i.previous_export_digest == (None if head is None else head.to_export_digest)]
        _require(len(following) == 1, INTENT_CHAIN_INVALID, "COMPLETED_CHAIN")
        intent = completed.pop(following[0])
        _require(head is None or intent.previous_projection_digest == head.to_projection_digest, INTENT_CHAIN_INVALID, "PREVIOUS_PROJECTION")
        chain.append(intent)
        head = intent
    chain_exports = {i.to_export_digest for i in chain}
    for d, intent in intents.items():
        if closing.get(d) == EVIDENCE_ABORT:
            _require(intent.previous_export_digest is None or intent.previous_export_digest in chain_exports, INTENT_CHAIN_INVALID, "ABORTED")
    open_ = [(d, i) for d, i in sorted(intents.items()) if d not in closing]
    _require(len(open_) <= 1, MULTIPLE_OPEN_INTENTS, "OPEN")
    open_digest, open_intent = open_[0] if open_ else (None, None)
    if open_intent is not None:
        _require(open_intent.previous_export_digest == (None if head is None else head.to_export_digest)
                 and open_intent.previous_projection_digest == (None if head is None else head.to_projection_digest),
                 INTENT_CHAIN_INVALID, "OPEN_PREVIOUS")

    owners = {i.version_label: (d, i) for d, i in intents.items()}            # 版の label → 所有する intent（短縮の衝突は上で拒む）
    for label in sorted(observation.versions):
        _require(label in owners, UNREFERENCED_VERSION, "VERSION")
        _verify_notes(observation.versions[label], manifests[owners[label][1].to_export_digest], VERSION_UNVERIFIED)
    for intent in chain:                                                         # 前の有効な版は全て在り ・検証できる
        _require(intent.version_label in observation.versions, PREVIOUS_VERSION_MISSING, "COMPLETED_VERSION")
    for label in sorted(observation.staging):
        _require(label in owners, ORPHAN_STAGING, "STAGING")
        _require(owners[label][0] == open_digest, STAGING_OF_CLOSED_INTENT, "STAGING")
    staged = open_intent is not None and open_intent.version_label in observation.staging
    if staged:
        _require(open_intent.version_label not in observation.versions, AMBIGUOUS_STAGING_AND_VERSION, "STAGING_AND_VERSION")
        _verify_notes(observation.staging[open_intent.version_label], manifests[open_intent.to_export_digest], STAGING_UNVERIFIED)

    pointer = None
    if observation.pointer is not None:
        pointer = parse_pointer(observation.pointer)
        _require(head is not None or open_intent is not None, POINTER_WITHOUT_EVIDENCE, "POINTER")
        acceptable = {i.to_export_digest for i in (head, open_intent) if i is not None}
        _require(pointer.export_digest in acceptable, POINTER_UNEXPECTED, "TARGET")
        _require(pointer.projection_digest == manifests[pointer.export_digest].projection_digest, POINTER_UNEXPECTED, "PROJECTION")
        _require(pointer.version_label in observation.versions, POINTER_UNEXPECTED, "VERSION_ABSENT")
    else:
        _require(head is None, POINTER_MISSING, "PUBLISHED_CHAIN")

    retained = tuple(sorted(observation.versions))
    summary = dict(published_export_digest=None if pointer is None else pointer.export_digest, open_intent_digest=open_digest,
                   completed_intent_count=len(chain), aborted_intent_count=sum(1 for v in closing.values() if v == EVIDENCE_ABORT),
                   retained_versions=retained)
    if open_intent is None:
        return _no_open_intent(observation, target, head, manifests, owners, summary)
    return _open_intent(observation, target, open_digest, open_intent, pointer, staged, manifests, summary)


def _no_open_intent(observation: PublicationObservation, target: Optional[ProjectionExport], head: Optional[IntentRecord],
                    manifests: Mapping[str, ExportManifest], owners: Mapping[str, Any], summary: Dict[str, Any]) -> PublicationClassification:
    state = PublicationState.FIRST_PUBLICATION if head is None else PublicationState.PUBLISHED_VERIFIED
    quiet = RecoveryEligibility.NOT_REQUIRED
    if target is None:
        return PublicationClassification(state=state, action=ProposedAction.NONE, recovery=quiet, code=state.value, **summary)
    if head is not None and target.export_digest == head.to_export_digest:
        return PublicationClassification(state=PublicationState.NO_CHANGE, action=ProposedAction.NONE, recovery=quiet,
                                         code=PublicationState.NO_CHANGE.value, **summary)
    if target.version_label in owners:
        known = manifests[owners[target.version_label][1].to_export_digest]
        code = REPUBLICATION_OF_KNOWN_VERSION if known.export_digest == target.export_digest else MANIFEST_CONFLICT
        return PublicationClassification(state=state, action=ProposedAction.HOLD, recovery=RecoveryEligibility.HOLD_FAIL_CLOSED,
                                         code=code, **summary)
    intent = intent_for(target, None if head is None else manifests[head.to_export_digest])
    plan = TransitionPlan(action=ProposedAction.PREPARE_INTENT, intent_digest=intent.intent_digest, version_label=target.version_label,
                          evidence=((EVIDENCE_MANIFEST, target.export_digest, target.manifest.to_bytes()),
                                    (EVIDENCE_INTENT, intent.intent_digest, intent.to_bytes())),
                          retained_versions=summary["retained_versions"])
    return PublicationClassification(state=state, action=ProposedAction.PREPARE_INTENT, recovery=quiet, code=state.value,
                                     transition=plan, **summary)


def _open_intent(observation: PublicationObservation, target: Optional[ProjectionExport], open_digest: str, open_intent: IntentRecord,
                 pointer: Optional[PointerRecord], staged: bool, manifests: Mapping[str, ExportManifest],
                 summary: Dict[str, Any]) -> PublicationClassification:
    label = open_intent.version_label
    retained = summary["retained_versions"]
    if pointer is not None and pointer.export_digest == open_intent.to_export_digest:
        state, action = PublicationState.POINTER_SWITCHED, ProposedAction.RECORD_COMPLETION
        record = completion_for(open_intent)
        plan = TransitionPlan(action=action, intent_digest=open_digest, version_label=label,
                              evidence=((EVIDENCE_COMPLETION, record.completion_digest, record.to_bytes()),), retained_versions=retained)
    elif label in observation.versions:
        state, action = PublicationState.VERSION_VERIFIED, ProposedAction.REPLACE_POINTER
        plan = TransitionPlan(action=action, intent_digest=open_digest, version_label=label, expected_pointer=observation.pointer,
                              replacement_pointer=render_pointer(manifests[open_intent.to_export_digest]), retained_versions=retained)
    elif staged:
        state, action = PublicationState.STAGED_VERIFIED, ProposedAction.MOVE_STAGED_TO_VERSION
        plan = TransitionPlan(action=action, intent_digest=open_digest, version_label=label, retained_versions=retained)
    else:
        state, action = PublicationState.INTENT_PREPARED, ProposedAction.STAGE_VERSION
        if target is None:                                                       # 書く byte を持たない段階は進めない
            return PublicationClassification(state=state, action=ProposedAction.HOLD, recovery=RecoveryEligibility.HOLD_FAIL_CLOSED,
                                             code=TARGET_REQUIRED_FOR_STAGING, **summary)
        plan = TransitionPlan(action=action, intent_digest=open_digest, version_label=label, staged_notes=target.notes,
                              retained_versions=retained)
    if target is not None and target.export_digest != open_intent.to_export_digest:
        return PublicationClassification(state=state, action=ProposedAction.HOLD, recovery=RecoveryEligibility.HOLD_FAIL_CLOSED,
                                         code=TARGET_CONFLICTS_WITH_OPEN_INTENT, **summary)
    return PublicationClassification(state=state, action=action, recovery=RecoveryEligibility.AUTO_CONVERGE_ELIGIBLE, code=state.value,
                                     transition=plan, **summary)


def check_recovery_proposal(observation: PublicationObservation, proposed: Any, *,
                            target: Optional[ProjectionExport] = None) -> TransitionPlan:
    """自動の収束の提案の検査: 観測を分類し直し、適格で ・提案がちょうど次の遷移のときだけ、その遷移を返す（それ以外は拒む）。"""
    try:
        action = ProposedAction(proposed)
    except ValueError:
        raise ProjectionError(UNSAFE_RECOVERY_PROPOSAL, "UNKNOWN_ACTION") from None
    classification = classify_publication(observation, target=target)
    _require(classification.recovery is RecoveryEligibility.AUTO_CONVERGE_ELIGIBLE, UNSAFE_RECOVERY_PROPOSAL, "NOT_ELIGIBLE")
    _require(action in AUTO_CONVERGE_ACTIONS and action is classification.action, UNSAFE_RECOVERY_PROPOSAL, "NOT_THE_NEXT_TRANSITION")
    _require(classification.transition is not None and classification.transition.action is action, UNSAFE_RECOVERY_PROPOSAL, "PLAN")
    return classification.transition


__all__ = ["ABORT_DOMAIN", "ABORT_REASONS", "ABORT_SCHEMA_VERSION", "ALLOWED_CODES", "ALLOWED_FIELD_LABELS", "AMBIGUOUS_STAGING_AND_VERSION",
           "APPROVED_CATEGORY_CODES", "AUTO_CONVERGE_ACTIONS", "AbortRecord", "CATEGORY_UNAPPROVED", "COMPLETION_DOMAIN",
           "COMPLETION_SCHEMA_VERSION", "CONTRADICTORY_INTENT", "COUNT_OUT_OF_RANGE", "CompletionRecord", "EVIDENCE_ABORT",
           "EVIDENCE_COMPLETION", "EVIDENCE_DIGEST_MISMATCH", "EVIDENCE_INTENT", "EVIDENCE_MANIFEST", "EXPORT_DOMAIN", "EXPORT_ID_PREFIX",
           "EXPORT_MANIFEST_SCHEMA_VERSION", "ExportFile", "ExportManifest", "FIXED_LINES", "INTENT_CHAIN_INVALID", "INTENT_DOMAIN",
           "INTENT_REFERENCE_MISSING", "INTENT_SCHEMA_VERSION", "INTERVAL_DOMAIN", "INTERVAL_ID_PREFIX", "IntentRecord", "MANIFEST_CONFLICT",
           "MANIFEST_MISSING", "MAX_EXPORT_FILES", "MAX_NOTE_BYTES", "MAX_OBSERVED_OBJECTS", "MAX_RENDERED_COUNT", "MULTIPLE_OPEN_INTENTS",
           "NOTE_INVALID", "NOTE_SUFFIX", "NoteKind", "OBSERVATION_INVALID", "ORPHAN_STAGING", "POINTER_INVALID", "POINTER_MISSING",
           "POINTER_NOTE_NAME", "POINTER_SCHEMA_VERSION", "POINTER_UNEXPECTED", "POINTER_WITHOUT_EVIDENCE", "PREVIOUS_VERSION_MISSING",
           "PRIVATE_SHAPE_DETECTED", "PRIVATE_SHAPE_PATTERNS", "PROJECTION_AUTHORITY_CLASS", "PROJECTION_CODES", "PROJECTION_DOMAIN",
           "PROJECTION_INPUT_INVALID", "PROJECTION_RULES_VERSION", "PROJECTION_SCHEMA_VERSION", "PointerRecord", "ProjectionError",
           "ProjectionExport", "ProjectionInput", "ProposedAction", "PublicationClassification", "PublicationObservation",
           "PublicationState", "RECORD_CORRUPT", "REPUBLICATION_OF_KNOWN_VERSION", "RecoveryEligibility", "SCHEMA_UNSUPPORTED",
           "SHORT_ID_COLLISION", "SOURCE_ATTESTATION", "SOURCE_DIGEST_MISMATCH", "SOURCE_UNVERIFIED", "STAGING_OF_CLOSED_INTENT",
           "STAGING_UNVERIFIED", "TARGET_CONFLICTS_WITH_OPEN_INTENT", "TARGET_REQUIRED_FOR_STAGING", "TransitionPlan", "UNKNOWN_OBJECT",
           "UNREFERENCED_MANIFEST", "UNREFERENCED_VERSION", "UNSAFE_RECOVERY_PROPOSAL", "VERSION_LABEL_PREFIX", "VERSION_UNVERIFIED",
           "abort_for", "build_projection_input", "check_recovery_proposal", "classify_publication", "completion_for", "intent_for",
           "interval_digest", "parse_abort", "parse_completion", "parse_export_manifest", "parse_intent", "parse_pointer", "render_pointer",
           "render_projection", "scan_private_shapes", "validate_note"]
