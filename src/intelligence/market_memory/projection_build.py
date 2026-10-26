"""P13-A4b — Obsidian 投影の export の orchestration（filesystem の呼び出しは無い ・store ・A3 ・A4a1 の公開の面だけを使う）。

公開（`publish_projection`）: 入力の検証（明示の完全な generation ／ manifest の digest ・容量の上限は狭めるだけ）→ store を開く（composition
root ・vault ・Obsidian の設定）→ 2 つの writer lock → A3 の公開の読み（`open_memory_store` ・`read_publication` ・`read_generation` が
VERIFIED ・要求した generation が A3 の検証済みの公開と一致 ・A3 の staging は無い）→ A4a1 の後継の契約で public な版と private な binding を
作る（`build_projection_target`）→ 走査（承認した全ての pattern の識別子 ・pattern ごとの検出の件数 ・規則の digest ・被覆した file の
digest）・source の読みの private な証拠の record → 観測と A4a1 の分類を繰り返す:
- 次の遷移が自動の収束（`check_recovery_proposal`）か、回復の要らない PREPARE_INTENT ／ RECORD_PRIVATE_BINDING の時だけ書く。書く前に作業中の
  残りが今の遷移の決定論の byte であること ・遷移の後の観測を純粋に予測して分類した状態が期待どおりで FAIL_CLOSED でないこと ・容量を確かめる。
- 書いた後は disk から観測し直し、予測した観測と byte で一致しなければ FAILED（記憶の中の結果を仮定しない）。
- NO_CHANGE は新しい private な binding を記録してからだけ成功（記録できなければ FAILED）。HOLD ・明示の保存だけの状態は止まる（HELD）。
人の明示の保存（`preserve_projection_staging`）: 同じ lock ・読み ・観測の下で `check_preservation_proposal` が認めた 1 つの保存だけ。
lock の下で止まった全ての試みは、安全に書ける時だけ private な FAILED の証拠を残す（書けなければ書けないと報告する）。作業中の残りは、次の遷移が
同じ名前で書く決定論の byte だけを続きに使い、それ以外（残った ・曖昧な FAILED の一時 file を含む）は公開 ・保存 ・失敗の記録の全てを止める（HOLD）。結果は固定の code ・
public な digest ・label だけ（root ・private な digest ・時刻は無い）。時計 ・telemetry は使わない。
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, replace
from enum import Enum
from typing import Any, Dict, Mapping, Optional, Tuple

from .canonical import CanonicalError, domain_digest, is_digest, require_safe_code
from .memory_generation import record_bytes, sha256_hex
from .memory_store import GENERATION_VERIFIED, PUBLICATION_VERIFIED, MemoryStoreError, ReadStatus, open_memory_store
from .projection_contract import (AUTO_CONVERGE_ACTIONS, CONTRACT_RULES_VERSION, EVIDENCE_COMPLETION, EVIDENCE_INTENT,
                                  EVIDENCE_PRIVATE_BINDING, EVIDENCE_PUBLIC_EXPORT, EXPLICIT_PRESERVATION_ACTIONS, MAX_OBSERVED_OBJECTS,
                                  POINTER_NOTE_NAME, PRESERVE_AREA_RESERVATION, PRESERVE_AREA_STAGING, PrivateBinding, ProjectionError,
                                  ProjectionTarget, ProposedAction, PublicationObservation, PublicationState, PublicExportManifest,
                                  RecoveryEligibility, TransitionPlan, build_projection_target, check_preservation_proposal,
                                  check_recovery_proposal, classify_publication, parse_intent, parse_private_binding,
                                  parse_public_export_manifest, render_pointer, scan_private_shapes, validate_public_note)
from .projection_store import (BINDING_RECORD, BINDINGS_DIRECTORY, BUNDLES_DIRECTORY, COMPLETIONS_DIRECTORY, EVIDENCE_ALREADY_RECORDED,
                               FAILURES_DIRECTORY, INTENT_RECORD, LOCK_NOT_ACQUIRED, PROJECTION_ROOT_LABEL, PUBLIC_EXPORT_RECORD, SCAN_RECORD,
                               SIZE_UNIT, SOURCE_RECORD, VAULT_ROOT_LABEL, ExportLocks, PrivateSnapshot, ProjectionStore,
                               ProjectionStoreError, VaultSnapshot, open_projection_store, storage_units)

SCAN_SCHEMA_VERSION = "p13_projection_scan:0.1.0"
SCAN_DOMAIN = "p13.projection_scan.v1"
SCAN_RULES_VERSION = "p13_projection_scan_rules:0.1.0"
SCAN_RULES_DOMAIN = "p13.projection_scan_rules.v1"
#: 走査の手順（承認した pattern ごとの件数 ・承認した走査器 `scan_private_shapes` との一致 ・A4a1 の `validate_public_note` の byte の規則 ・
#: 文法 ・public な digest の正の検査）。1 つでも当たれば PASSED にならない
SCAN_PROCEDURE = "A4A1_VALIDATE_PUBLIC_NOTE_BYTES_PRIVATE_SHAPES_GRAMMAR_POSITIVE_HEX"
SCAN_RESULT_PASSED = "PASSED"
SCAN_RESULT_DETECTED = "DETECTED"
#: 承認した private の形の pattern の表（凍結の A4a の表 ・A4a1 が再利用する走査器 `scan_private_shapes` の表と同じ順 ・同じ正規表現）。A4b は
#: 凍結の module を import しないので写しを持つ。boundary の guard が凍結の表との完全一致を pin し、実行の時は file ごとに承認した走査器の
#: 結果と照らす（違えば SCAN_RULES_DRIFT で止まる ・pattern の不一致の写しは決して使わない）
SCAN_PATTERNS = (
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
_SCAN_SHAPES = tuple((label, re.compile(pattern)) for label, pattern in SCAN_PATTERNS)
SCAN_AUTHORITY_CLASS = "DERIVED_SCAN_EVIDENCE_NON_AUTHORITY"
SOURCE_READ_SCHEMA_VERSION = "p13_projection_source_read:0.1.0"
SOURCE_READ_DOMAIN = "p13.projection_source_read.v1"
#: A4b が確立する読み: lock の下の同じ操作で A3 の公開の API が VERIFIED を返した（A3 の書き込みとの不可分ではない ・A3 の lock は取らない）
SOURCE_READ_ATTESTATION = "A4B_A3_PUBLIC_READ_VERIFIED_UNDER_EXPORT_LOCKS_NOT_ATOMIC_WITH_A3_WRITES"
FAILURE_SCHEMA_VERSION = "p13_projection_failure:0.1.0"
FAILURE_DOMAIN = "p13.projection_failure.v1"
FAILURE_AUTHORITY_CLASS = "DERIVED_FAILURE_EVIDENCE_NON_AUTHORITY"
FAILURE_STAGES = ("SOURCE", "RENDER", "SCAN", "OBSERVE", "CLASSIFY", "CAPACITY", "WRITE", "VERIFY", "PRESERVE")
INTENT_BUNDLE_RECORDS = frozenset({INTENT_RECORD, PUBLIC_EXPORT_RECORD, BINDING_RECORD, SCAN_RECORD, SOURCE_RECORD})
BINDING_BUNDLE_RECORDS = frozenset({BINDING_RECORD, SCAN_RECORD, SOURCE_RECORD})
#: 暫定の容量の上限（呼び出し側は狭めるだけ ・緩めれば拒む）
MAX_RETAINED_VERSIONS = 64
MAX_VAULT_EXPORT_BYTES = 256 * 1024 * 1024
MAX_PRIVATE_EVIDENCE_BYTES = 64 * 1024 * 1024
MAX_OBSERVATION_OBJECTS = MAX_OBSERVED_OBJECTS
MIN_FREE_MARGIN_BYTES = 512 * 1024 * 1024
MAX_TRANSITIONS = 8

#: 結果の code（固定の定数だけ）
EXPORT_INPUT_INVALID = "EXPORT_INPUT_INVALID"
LIMIT_LOOSENED = "LIMIT_LOOSENED"
SOURCE_UNAVAILABLE = "SOURCE_UNAVAILABLE"
SOURCE_NOT_VERIFIED = "SOURCE_NOT_VERIFIED"
SOURCE_NOT_PUBLISHED_GENERATION = "SOURCE_NOT_PUBLISHED_GENERATION"
SOURCE_UNVERIFIED = "SOURCE_UNVERIFIED"
SOURCE_STAGING_PRESENT = "SOURCE_STAGING_PRESENT"
SCAN_FAILED = "SCAN_FAILED"
SCAN_RULES_DRIFT = "SCAN_RULES_DRIFT"
EVIDENCE_INVALID = "EVIDENCE_INVALID"
SCAN_EVIDENCE_INVALID = "SCAN_EVIDENCE_INVALID"
SOURCE_EVIDENCE_INVALID = "SOURCE_EVIDENCE_INVALID"
FAILURE_EVIDENCE_INVALID = "FAILURE_EVIDENCE_INVALID"
EVIDENCE_DUPLICATE = "EVIDENCE_DUPLICATE"
EVIDENCE_STAGING_RESIDUE = "EVIDENCE_STAGING_RESIDUE"
VAULT_STAGING_RESIDUE = "VAULT_STAGING_RESIDUE"
EXPLICIT_PRESERVATION_REQUIRED = "EXPLICIT_PRESERVATION_REQUIRED"
UNSUPPORTED_TRANSITION = "UNSUPPORTED_TRANSITION"
PREDICTED_STATE_INVALID = "PREDICTED_STATE_INVALID"
POST_STATE_MISMATCH = "POST_STATE_MISMATCH"
TRANSITION_LIMIT = "TRANSITION_LIMIT"
CAPACITY_EXCEEDED = "CAPACITY_EXCEEDED"
PRESERVED = "PRESERVED"
FAILURE_RECORDED = "FAILURE_RECORDED"
FAILURE_ALREADY_RECORDED = "FAILURE_ALREADY_RECORDED"
FAILURE_NOT_RECORDED = "FAILURE_NOT_RECORDED"
FAILURE_NOT_REQUIRED = "FAILURE_NOT_REQUIRED"

_A = ProposedAction
#: 書いた後に期待する状態（それ以外 ・FAIL_CLOSED は書く前に止める）
_EXPECTED_STATE = {_A.PREPARE_INTENT: PublicationState.INTENT_PREPARED, _A.STAGE_VERSION: PublicationState.STAGED_VERIFIED,
                   _A.CONTINUE_STAGING: PublicationState.STAGED_VERIFIED, _A.MOVE_STAGED_TO_VERSION: PublicationState.VERSION_VERIFIED,
                   _A.REPLACE_POINTER: PublicationState.POINTER_SWITCHED, _A.RECORD_COMPLETION: PublicationState.NO_CHANGE,
                   _A.RECORD_PRIVATE_BINDING: PublicationState.NO_CHANGE}
#: 遷移ごとに続きに使ってよい private な作業中の残り（種類 ・名前の digest ・それ以外の残りは HOLD）
_RESIDUE_KIND = {_A.PREPARE_INTENT: "BUNDLE", _A.RECORD_PRIVATE_BINDING: "BINDING", _A.RECORD_COMPLETION: "COMPLETION"}


class ExportStatus(str, Enum):
    PUBLISHED = "PUBLISHED"
    NO_CHANGE = "NO_CHANGE"
    PRESERVED = "PRESERVED"
    HELD = "HELD"
    FAILED = "FAILED"
    REFUSED = "REFUSED"


class ExportInputError(ValueError):
    """呼び出し側の入力の誤り（digest の形 ・容量の上限 ・保護の root の label ・保存の action）。filesystem ・A3 は読まない。"""

    def __init__(self, code: str, detail: str = "") -> None:
        super().__init__(f"{code}:{detail}" if detail else code)
        self.code = code
        self.detail = detail


@dataclass(frozen=True, kw_only=True)
class ExportLimits:
    """容量の上限（暫定の最大 ・呼び出し側は狭めるだけ ・空きの余白は広げるだけ）。"""

    retained_versions: int = MAX_RETAINED_VERSIONS
    vault_export_bytes: int = MAX_VAULT_EXPORT_BYTES
    private_evidence_bytes: int = MAX_PRIVATE_EVIDENCE_BYTES
    observation_objects: int = MAX_OBSERVATION_OBJECTS
    free_margin_bytes: int = MIN_FREE_MARGIN_BYTES

    def __post_init__(self) -> None:
        for name, maximum in (("retained_versions", MAX_RETAINED_VERSIONS), ("vault_export_bytes", MAX_VAULT_EXPORT_BYTES),
                              ("private_evidence_bytes", MAX_PRIVATE_EVIDENCE_BYTES), ("observation_objects", MAX_OBSERVATION_OBJECTS)):
            value = self.__dict__[name]
            if type(value) is not int or value < 0:
                raise ExportInputError(EXPORT_INPUT_INVALID, name.upper())
            if value > maximum:
                raise ExportInputError(LIMIT_LOOSENED, name.upper())
        if type(self.free_margin_bytes) is not int or self.free_margin_bytes < 0:
            raise ExportInputError(EXPORT_INPUT_INVALID, "FREE_MARGIN_BYTES")
        if self.free_margin_bytes < MIN_FREE_MARGIN_BYTES:
            raise ExportInputError(LIMIT_LOOSENED, "FREE_MARGIN_BYTES")


@dataclass(frozen=True, kw_only=True)
class ExportResult:
    """export の結果（固定の code ・public な digest ・label だけ）。`proposed_action` は人の明示の保存が要る時の A4a1 の action。
    `lock_release` は (vault, private) の解放の code。"""

    status: ExportStatus
    code: str
    state: Optional[str] = None
    transitions: Tuple[str, ...] = ()
    public_export_digest: Optional[str] = None
    version_label: Optional[str] = None
    binding_recorded: Optional[bool] = None
    proposed_action: Optional[str] = None
    failure_evidence: str = FAILURE_NOT_REQUIRED
    failure_residue: int = 0
    lock_release: Tuple[str, str] = (LOCK_NOT_ACQUIRED, LOCK_NOT_ACQUIRED)


class ExportScanError(ValueError):
    """走査の失敗（固定の code ・当たった pattern の識別子だけ ・当たった文字列は持たない）。"""

    def __init__(self, code: str, detail: str = "") -> None:
        super().__init__(f"{code}:{detail}" if detail else code)
        self.code = code
        self.detail = detail


class _Stop(Exception):
    """lock の下で止まる理由（固定の status ・段 ・code ・安全な detail だけ）。"""

    def __init__(self, status: ExportStatus, stage: str, code: str, detail: Optional[str] = None, state: Optional[str] = None) -> None:
        super().__init__(code)
        self.status, self.stage, self.code, self.detail, self.state = status, stage, code, detail, state


def _safe_detail(value: Any) -> Optional[str]:
    try:
        return require_safe_code(value, EXPORT_INPUT_INVALID)
    except CanonicalError:
        return None


# ---------------------------------------------------------------- private な証拠の record（走査 ・source の読み ・失敗）


def scan_rules_digest() -> str:
    """走査の規則の identity（規則の version ・A4a1 の規則の version ・承認した全ての pattern の識別子と正規表現 ・表の順）。"""
    return domain_digest(SCAN_RULES_DOMAIN, {"scan_rules_version": SCAN_RULES_VERSION, "projection_rules_version": CONTRACT_RULES_VERSION,
                                             "patterns": [[label, pattern] for label, pattern in SCAN_PATTERNS]})


def _pattern_counts(text: str) -> Tuple[int, ...]:
    """承認した pattern ごとの当たりの件数（表の順 ・当たった文字列は返さない）。承認した走査器と当たりの集合が違えば規則の drift。"""
    counts = tuple(sum(1 for _ in pattern.finditer(text)) for _, pattern in _SCAN_SHAPES)
    if tuple(label for (label, _), count in zip(SCAN_PATTERNS, counts) if count) != scan_private_shapes(text):
        raise ExportScanError(SCAN_RULES_DRIFT, "APPROVED_SCANNER_DISAGREES")
    return counts


def _scan_content(public_version_digest: str, public_export_digest: str, files: list, totals: list) -> Dict[str, Any]:
    detected = sum(totals)
    return {"schema_version": SCAN_SCHEMA_VERSION, "scan_rules_version": SCAN_RULES_VERSION, "scan_rules_digest": scan_rules_digest(),
            "projection_rules_version": CONTRACT_RULES_VERSION, "procedure": SCAN_PROCEDURE,
            "patterns": [label for label, _ in SCAN_PATTERNS],
            "pattern_counts": [[label, count] for (label, _), count in zip(SCAN_PATTERNS, totals)],
            "public_version_digest": public_version_digest, "public_export_digest": public_export_digest, "files": files,
            "file_count": len(files), "detected_count": detected, "result": SCAN_RESULT_PASSED if detected == 0 else SCAN_RESULT_DETECTED,
            "authority_class": SCAN_AUTHORITY_CLASS}


def scan_record(target: ProjectionTarget) -> bytes:
    """公開する全ての byte（版の note ・pointer）の private な走査の証拠: 規則の version ・digest ・承認した全ての pattern の識別子 ・pattern
    ごとの検出の件数 ・被覆した file の名前 ・長さ ・sha256 ・件数 ・決定論の結果（当たった文字列 ・path ・時刻は無い）。1 つでも当たれば
    PASSED の record は作らず ExportScanError（当たった pattern の識別子だけ）。全ての file は A4a1 の検証も通る。"""
    if not isinstance(target, ProjectionTarget):
        raise ExportInputError(EXPORT_INPUT_INVALID, "TARGET")
    files, totals = [], [0] * len(SCAN_PATTERNS)
    for name, data in (*target.public_export.notes, (POINTER_NOTE_NAME, target.public_export.pointer_note())):
        try:
            text = data.decode("utf-8")
        except UnicodeDecodeError:
            raise ExportScanError(SCAN_FAILED, "UTF8") from None
        counts = _pattern_counts(text)
        if any(counts):
            raise ExportScanError(SCAN_FAILED, next(label for (label, _), count in zip(SCAN_PATTERNS, counts) if count))
        try:
            validate_public_note(data, name=name)
        except ProjectionError as exc:
            raise ExportScanError(SCAN_FAILED, _safe_detail(exc.detail) or exc.code) from None
        totals = [a + b for a, b in zip(totals, counts)]
        files.append([name, len(data), sha256_hex(data), sum(counts)])
    manifest = target.public_export.manifest
    return record_bytes(_scan_content(manifest.public_version_digest, manifest.public_export_digest, files, totals))


def scan_record_digest(data: bytes) -> str:
    """走査の証拠の決定論の identity（正準の byte の内容の domain digest）。"""
    return domain_digest(SCAN_DOMAIN, _record_of(data, SCAN_SCHEMA_VERSION, SCAN_EVIDENCE_INVALID))


def _record_of(data: Any, schema: str, code: str) -> Dict[str, Any]:
    try:
        value = json.loads(data.decode("utf-8")) if isinstance(data, bytes) else None
    except (UnicodeDecodeError, ValueError, RecursionError):
        value = None
    if not isinstance(value, dict) or value.get("schema_version") != schema:
        raise _Stop(ExportStatus.HELD, "OBSERVE", code, "SCHEMA")
    try:
        canonical = record_bytes(value)
    except CanonicalError:
        raise _Stop(ExportStatus.HELD, "OBSERVE", code, "NON_CANONICAL") from None
    if canonical != data:
        raise _Stop(ExportStatus.HELD, "OBSERVE", code, "NON_CANONICAL")
    return value


def _check_scan_record(data: Any, manifest: PublicExportManifest) -> None:
    """走査の証拠の完全な再検証（正準の byte ・規則の version ／ digest の今の表との一致 ・承認した全ての pattern の識別子と順 ・全ての件数が 0 ・
    manifest の全 file と pointer の名前 ／ 長さ ／ sha256 の完全な被覆 ・PASSED）。1 つでも違えば HOLD（規則の drift ・偽の件数 ・欠けた被覆）。"""
    value = _record_of(data, SCAN_SCHEMA_VERSION, SCAN_EVIDENCE_INVALID)
    pointer = render_pointer(manifest)
    files = [[f.name, f.size, f.sha256, 0] for f in manifest.files] + [[POINTER_NOTE_NAME, len(pointer), sha256_hex(pointer), 0]]
    expected = _scan_content(manifest.public_version_digest, manifest.public_export_digest, files, [0] * len(SCAN_PATTERNS))
    if value.get("scan_rules_version") != SCAN_RULES_VERSION or value.get("scan_rules_digest") != scan_rules_digest():
        raise _Stop(ExportStatus.HELD, "OBSERVE", SCAN_EVIDENCE_INVALID, "SCAN_RULES")
    if value != expected:
        raise _Stop(ExportStatus.HELD, "OBSERVE", SCAN_EVIDENCE_INVALID, "CONTENT")


def source_record(binding: PrivateBinding) -> bytes:
    """A3 の公開の読みの証拠（private ・binding の完全な digest と A3 が返した状態だけ）。"""
    return record_bytes({"schema_version": SOURCE_READ_SCHEMA_VERSION, "binding_digest": binding.binding_digest,
                         "private_generation_digest": binding.private_generation_digest,
                         "private_source_manifest_digest": binding.private_source_manifest_digest,
                         "generation_read_status": ReadStatus.VERIFIED.value, "generation_read_code": GENERATION_VERIFIED,
                         "publication_read_status": ReadStatus.VERIFIED.value, "publication_read_code": PUBLICATION_VERIFIED,
                         "requested_generation_is_publication": True, "attestation": SOURCE_READ_ATTESTATION})


def _check_source_record(data: Any, binding: PrivateBinding) -> None:
    """source の読みの証拠の厳密な照合（正準の byte ・binding の完全な digest との完全一致）。"""
    _record_of(data, SOURCE_READ_SCHEMA_VERSION, SOURCE_EVIDENCE_INVALID)
    if data != source_record(binding):
        raise _Stop(ExportStatus.HELD, "OBSERVE", SOURCE_EVIDENCE_INVALID, "CONTENT")


def failure_record(*, operation: str, stage: str, code: str, detail: Optional[str], generation_digest: str, manifest_digest: str,
                   public_export_digest: Optional[str]) -> bytes:
    """止まった試みの private な証拠（固定の段 ・code ・安全な detail ・要求した digest だけ ・例外の文 ・時刻 ・path は無い ・同じ失敗は同じ byte）。"""
    if stage not in FAILURE_STAGES or _safe_detail(code) is None or not (is_digest(generation_digest) and is_digest(manifest_digest)):
        raise ExportInputError(EXPORT_INPUT_INVALID, "FAILURE")
    return record_bytes({"schema_version": FAILURE_SCHEMA_VERSION, "operation": operation, "stage": stage, "code": code,
                         "detail": _safe_detail(detail), "requested_generation_digest": generation_digest,
                         "requested_manifest_digest": manifest_digest,
                         "public_export_digest": public_export_digest if is_digest(public_export_digest) else None,
                         "authority_class": FAILURE_AUTHORITY_CLASS})


_FAILURE_FIELDS = frozenset({"schema_version", "operation", "stage", "code", "detail", "requested_generation_digest",
                             "requested_manifest_digest", "public_export_digest", "authority_class"})


def _failure_digest(data: bytes) -> str:
    """失敗の証拠の厳密な読み（鍵の完全一致 ・固定の段 ・安全な code ・正準の byte）と digest。"""
    value = _record_of(data, FAILURE_SCHEMA_VERSION, FAILURE_EVIDENCE_INVALID)
    if (set(value) != _FAILURE_FIELDS or value["stage"] not in FAILURE_STAGES or _safe_detail(value["code"]) is None
            or value["authority_class"] != FAILURE_AUTHORITY_CLASS):
        raise _Stop(ExportStatus.HELD, "OBSERVE", FAILURE_EVIDENCE_INVALID, "FIELDS")
    return domain_digest(FAILURE_DOMAIN, value)


# ---------------------------------------------------------------- 観測の組み立て（I5: 観測の外の管理の object は分類の前に厳密に検証する）


@dataclass(frozen=True, kw_only=True)
class _Observed:
    observation: PublicationObservation
    residue: Mapping[Tuple[str, str], Any]
    pointer_temps: Mapping[str, bytes]
    objects: int
    versions: int
    vault_bytes: int
    private_bytes: int


def _parsed(parse: Any, data: Any) -> Any:
    try:
        return parse(data)
    except ProjectionError as exc:
        raise _Stop(ExportStatus.HELD, "OBSERVE", exc.code, "EVIDENCE") from None


def _observed_of(private: PrivateSnapshot, vault: VaultSnapshot) -> _Observed:
    exports: Dict[str, bytes] = {}
    manifests: Dict[str, PublicExportManifest] = {}
    bindings: Dict[str, bytes] = {}
    intents: Dict[str, bytes] = {}
    for digest, files in sorted(private.bundles.items()):
        if set(files) != INTENT_BUNDLE_RECORDS:
            raise _Stop(ExportStatus.HELD, "OBSERVE", EVIDENCE_INVALID, "BUNDLE_RECORDS")
        intent = _parsed(parse_intent, files[INTENT_RECORD])
        export = _parsed(parse_public_export_manifest, files[PUBLIC_EXPORT_RECORD])
        binding = _parsed(parse_private_binding, files[BINDING_RECORD])
        if (intent.intent_digest != digest or export.public_export_digest != intent.to_public_export_digest
                or binding.binding_digest != intent.to_binding_digest or binding.public_export_digest != export.public_export_digest):
            raise _Stop(ExportStatus.HELD, "OBSERVE", EVIDENCE_INVALID, "BUNDLE_LINKS")
        _check_scan_record(files[SCAN_RECORD], export)
        _check_source_record(files[SOURCE_RECORD], binding)
        if export.public_export_digest in exports or binding.binding_digest in bindings:
            raise _Stop(ExportStatus.HELD, "OBSERVE", EVIDENCE_DUPLICATE, "BUNDLE")
        exports[export.public_export_digest], manifests[export.public_export_digest] = files[PUBLIC_EXPORT_RECORD], export
        bindings[binding.binding_digest], intents[digest] = files[BINDING_RECORD], files[INTENT_RECORD]
    for digest, files in sorted(private.bindings.items()):
        if set(files) != BINDING_BUNDLE_RECORDS:
            raise _Stop(ExportStatus.HELD, "OBSERVE", EVIDENCE_INVALID, "BINDING_RECORDS")
        binding = _parsed(parse_private_binding, files[BINDING_RECORD])
        export = manifests.get(binding.public_export_digest)
        if binding.binding_digest != digest or export is None:
            raise _Stop(ExportStatus.HELD, "OBSERVE", EVIDENCE_INVALID, "BINDING_LINKS")
        _check_scan_record(files[SCAN_RECORD], export)
        _check_source_record(files[SOURCE_RECORD], binding)
        if digest in bindings:
            raise _Stop(ExportStatus.HELD, "OBSERVE", EVIDENCE_DUPLICATE, "BINDING")
        bindings[digest] = files[BINDING_RECORD]
    for digest, data in sorted(private.failures.items()):
        if _failure_digest(data) != digest:
            raise _Stop(ExportStatus.HELD, "OBSERVE", FAILURE_EVIDENCE_INVALID, "DIGEST")
    observation = PublicationObservation(pointer=vault.pointer, versions=vault.versions, staging=vault.staging, public_exports=exports,
                                         private_bindings=bindings, intents=intents, completions=dict(private.completions), aborts={})
    objects = sum(1 + len(notes) for group in (vault.versions, vault.staging) for notes in group.values())
    objects += len(exports) + len(bindings) + len(intents) + len(private.completions)
    return _Observed(observation=observation, residue=private.residue, pointer_temps=vault.pointer_temps,
                     objects=objects, versions=len(set(vault.versions) | set(vault.staging)), vault_bytes=vault.used_bytes,
                     private_bytes=private.used_bytes)


def _predict(observation: PublicationObservation, plan: TransitionPlan) -> PublicationObservation:
    """遷移の後の観測の純粋な予測（追加 ・pointer の置換 ・開いた intent の staging の移動 ・明示の保存だけ。削除 ・上書きは無い）。"""
    versions = {k: dict(v) for k, v in observation.versions.items()}
    staging = {k: dict(v) for k, v in observation.staging.items()}
    groups = {EVIDENCE_PUBLIC_EXPORT: dict(observation.public_exports), EVIDENCE_PRIVATE_BINDING: dict(observation.private_bindings),
              EVIDENCE_INTENT: dict(observation.intents), EVIDENCE_COMPLETION: dict(observation.completions)}
    pointer = observation.pointer
    if plan.action in (_A.PREPARE_INTENT, _A.RECORD_COMPLETION, _A.RECORD_PRIVATE_BINDING):
        for kind, digest, data in plan.evidence:
            groups[kind][digest] = data
    elif plan.action is _A.STAGE_VERSION:
        staging[plan.version_label] = dict(plan.staged_notes)
    elif plan.action is _A.CONTINUE_STAGING:
        staging[plan.version_label].update(dict(plan.staged_notes))
    elif plan.action is _A.MOVE_STAGED_TO_VERSION:
        versions[plan.version_label] = staging.pop(plan.version_label)
    elif plan.action is _A.REPLACE_POINTER:
        pointer = plan.replacement_pointer
    elif plan.action is _A.PRESERVE_STAGING:
        staging.pop(plan.preserve_label)
    elif plan.action is _A.PRESERVE_EMPTY_RESERVATION:
        versions.pop(plan.preserve_label)
    return PublicationObservation(pointer=pointer, versions=versions, staging=staging, public_exports=groups[EVIDENCE_PUBLIC_EXPORT],
                                  private_bindings=groups[EVIDENCE_PRIVATE_BINDING], intents=groups[EVIDENCE_INTENT],
                                  completions=groups[EVIDENCE_COMPLETION], aborts=dict(observation.aborts))


def _groups(observation: PublicationObservation) -> Tuple[Any, ...]:
    folders = tuple({k: dict(v) for k, v in group.items()} for group in (observation.versions, observation.staging))
    evidence = tuple(dict(group) for group in (observation.public_exports, observation.private_bindings, observation.intents,
                                               observation.completions, observation.aborts))
    return (observation.pointer, *folders, *evidence)


def _same(left: PublicationObservation, right: PublicationObservation) -> bool:
    """観測の byte の完全一致（pointer ・版 ・staging ・全ての証拠の写像）。"""
    return _groups(left) == _groups(right)


# ---------------------------------------------------------------- 容量（取引の頂点の必要量 ・観測した実際の合計を使う）


@dataclass(frozen=True, kw_only=True)
class _Requirement:
    vault_bytes: int
    private_bytes: int
    objects: int
    versions: int


def _requirement(plan: TransitionPlan, target: ProjectionTarget, bundle: Mapping[str, bytes]) -> _Requirement:
    """遷移から取引の終わりまでに新しく作る byte ・object の頂点（vault: staging の directory ・label の directory ・note ・移動の予約 ・pointer
    の一時 file ／ private: bundle ・完了 ・失敗の予備 ・切り上げ）。後の段の「観測 ＋ 必要」は PREPARE で確かめた値を超えない（単調）。"""
    notes = dict(target.public_export.notes)
    pointer = storage_units(len(target.public_export.pointer_note()))
    reserve = 2 * SIZE_UNIT                                                              # 完了の record と失敗の record の予備
    bundle_units = sum(storage_units(len(d)) for d in bundle.values()) + SIZE_UNIT
    every_note = sum(storage_units(len(d)) for d in notes.values())
    action = plan.action
    if action is _A.PREPARE_INTENT:
        return _Requirement(vault_bytes=every_note + 3 * SIZE_UNIT + pointer, private_bytes=bundle_units + reserve,
                            objects=3 + 1 + len(notes) + 1, versions=1)
    if action is _A.STAGE_VERSION:
        return _Requirement(vault_bytes=every_note + 3 * SIZE_UNIT + pointer, private_bytes=reserve, objects=1 + len(notes) + 1, versions=0)
    if action is _A.CONTINUE_STAGING:
        missing = sum(storage_units(len(d)) for _, d in plan.staged_notes)
        return _Requirement(vault_bytes=missing + SIZE_UNIT + pointer, private_bytes=reserve, objects=len(plan.staged_notes) + 1, versions=0)
    if action is _A.MOVE_STAGED_TO_VERSION:
        return _Requirement(vault_bytes=SIZE_UNIT + pointer, private_bytes=reserve, objects=1, versions=0)
    if action is _A.REPLACE_POINTER:
        return _Requirement(vault_bytes=pointer, private_bytes=reserve, objects=1, versions=0)
    if action is _A.RECORD_COMPLETION:
        return _Requirement(vault_bytes=0, private_bytes=reserve, objects=1, versions=0)
    if action is _A.RECORD_PRIVATE_BINDING:
        return _Requirement(vault_bytes=0, private_bytes=bundle_units + SIZE_UNIT, objects=1, versions=0)
    return _Requirement(vault_bytes=2 * SIZE_UNIT, private_bytes=SIZE_UNIT, objects=0, versions=0)          # 明示の保存


# ---------------------------------------------------------------- lock の下の 1 つの操作


class _Session:
    def __init__(self, store: ProjectionStore, locks: ExportLocks, operation: str, generation_digest: str, manifest_digest: str,
                 roots: Mapping[str, Any], limits: ExportLimits) -> None:
        self.store, self.locks, self.operation = store, locks, operation
        self.generation_digest, self.manifest_digest, self.roots, self.limits = generation_digest, manifest_digest, roots, limits
        self.target: Optional[ProjectionTarget] = None
        self.scan: bytes = b""
        self.source: bytes = b""
        self.transitions: list = []
        self.residue_count = 0

    # ------------------------------------------------ A3 の公開の読み ・public な版 ・証拠の record

    def _verified_source(self) -> Any:
        store = self.store
        roots = {**self.roots, PROJECTION_ROOT_LABEL: store.projection_location, VAULT_ROOT_LABEL: store.vault_location}
        try:
            memory = open_memory_store(store.memory_location, protected_roots=roots)
            publication = memory.read_publication()
            generation = memory.read_generation(self.generation_digest)
        except MemoryStoreError as exc:
            raise _Stop(ExportStatus.REFUSED, "SOURCE", SOURCE_UNAVAILABLE, exc.code) from None
        if publication.status is not ReadStatus.VERIFIED or publication.code != PUBLICATION_VERIFIED:
            raise _Stop(ExportStatus.REFUSED, "SOURCE", SOURCE_NOT_VERIFIED, publication.code)
        if (publication.generation_digest, publication.manifest_digest) != (self.generation_digest, self.manifest_digest):
            raise _Stop(ExportStatus.REFUSED, "SOURCE", SOURCE_NOT_PUBLISHED_GENERATION)   # 公開を暗黙の選択に使わない ・一致だけを要する
        if (generation.status is not ReadStatus.VERIFIED or generation.code != GENERATION_VERIFIED
                or generation.generation_digest != self.generation_digest or generation.manifest_digest != self.manifest_digest):
            raise _Stop(ExportStatus.REFUSED, "SOURCE", SOURCE_UNVERIFIED, generation.code)
        if publication.staging_present or generation.staging_present:
            raise _Stop(ExportStatus.REFUSED, "SOURCE", SOURCE_STAGING_PRESENT)
        return generation.verified

    def _prepare_target(self) -> ProjectionTarget:
        verified = self._verified_source()
        try:
            target = build_projection_target(verified, generation_digest=self.generation_digest, manifest_digest=self.manifest_digest)
        except ProjectionError as exc:
            raise _Stop(ExportStatus.REFUSED, "RENDER", exc.code, _safe_detail(exc.detail)) from None
        self.target = target
        try:
            self.scan = scan_record(target)
        except ExportScanError as exc:
            raise _Stop(ExportStatus.REFUSED, "SCAN", exc.code, _safe_detail(exc.detail)) from None
        self.source = source_record(target.binding)
        return target

    # ------------------------------------------------ 観測 ・容量

    def _observe(self) -> _Observed:
        try:
            private = self.store.snapshot_private(self.locks)
            vault = self.store.snapshot_vault(self.locks)
        except ProjectionStoreError as exc:
            raise _Stop(ExportStatus.HELD, "OBSERVE", exc.code, _safe_detail(exc.detail)) from None
        observed = _observed_of(private, vault)
        self.residue_count = sum(1 for kind, _ in observed.residue if kind == "FAILURE")
        return observed

    def _bundle_of(self, plan: TransitionPlan) -> Dict[str, bytes]:
        evidence = {kind: data for kind, _, data in plan.evidence}
        if plan.action is _A.PREPARE_INTENT:
            return {INTENT_RECORD: evidence[EVIDENCE_INTENT], PUBLIC_EXPORT_RECORD: evidence[EVIDENCE_PUBLIC_EXPORT],
                    BINDING_RECORD: evidence[EVIDENCE_PRIVATE_BINDING], SCAN_RECORD: self.scan, SOURCE_RECORD: self.source}
        if plan.action is _A.RECORD_PRIVATE_BINDING:
            return {BINDING_RECORD: evidence[EVIDENCE_PRIVATE_BINDING], SCAN_RECORD: self.scan, SOURCE_RECORD: self.source}
        return {}

    def _check_capacity(self, observed: _Observed, plan: TransitionPlan) -> None:
        need = _requirement(plan, self.target, self._bundle_of(plan))
        limits = self.limits
        for name, used, extra, limit in (("OBSERVATION_OBJECTS", observed.objects, need.objects, limits.observation_objects),
                                         ("RETAINED_VERSIONS", observed.versions, need.versions, limits.retained_versions),
                                         ("VAULT_EXPORT_BYTES", observed.vault_bytes, need.vault_bytes, limits.vault_export_bytes),
                                         ("PRIVATE_EVIDENCE_BYTES", observed.private_bytes, need.private_bytes, limits.private_evidence_bytes)):
            if used + extra > limit:
                raise _Stop(ExportStatus.REFUSED, "CAPACITY", CAPACITY_EXCEEDED, name)
        try:
            free = self.store.free_space(self.locks)
        except ProjectionStoreError as exc:
            raise _Stop(ExportStatus.REFUSED, "CAPACITY", exc.code, _safe_detail(exc.detail)) from None
        margin = limits.free_margin_bytes
        if free.same_volume:
            enough = need.vault_bytes + need.private_bytes + margin <= min(free.vault_free, free.private_free)
        else:
            enough = need.vault_bytes + margin <= free.vault_free and need.private_bytes + margin <= free.private_free
        if not enough:
            raise _Stop(ExportStatus.REFUSED, "CAPACITY", CAPACITY_EXCEEDED, "FREE_SPACE")

    # ------------------------------------------------ 遷移

    def _checked_plan(self, observed: _Observed, classification: Any) -> TransitionPlan:
        action = classification.action
        if action in AUTO_CONVERGE_ACTIONS:
            try:
                return check_recovery_proposal(observed.observation, action, target=self.target)
            except ProjectionError as exc:
                raise _Stop(ExportStatus.HELD, "CLASSIFY", exc.code) from None
        if (action in (_A.PREPARE_INTENT, _A.RECORD_PRIVATE_BINDING) and classification.recovery is RecoveryEligibility.NOT_REQUIRED
                and classification.transition is not None and classification.transition.action is action):
            return classification.transition
        raise _Stop(ExportStatus.HELD, "CLASSIFY", UNSUPPORTED_TRANSITION, action.value)

    def _check_residue(self, observed: _Observed, plan: Optional[TransitionPlan]) -> None:
        """作業中の残りは、次の遷移が同じ名前で書く決定論の byte だけを続きに使う。それ以外の残り（残った ・曖昧な FAILED の一時 file を
        含む ・FAILED の一時 file は決して続きに使わない）は、書かない回 ・明示の保存も含めて HOLD（消さない ・移さない ・採らない）。"""
        action = None if plan is None else plan.action
        allowed = None
        if action in _RESIDUE_KIND:
            allowed = (_RESIDUE_KIND[action], plan.intent_digest if action is _A.PREPARE_INTENT else plan.evidence[0][1])
        for key in sorted(observed.residue):
            if key != allowed:
                raise _Stop(ExportStatus.HELD, "OBSERVE", EVIDENCE_STAGING_RESIDUE, key[0])
        for digest in observed.pointer_temps:
            if not (action is _A.REPLACE_POINTER and digest == self.target.public_export_digest):
                raise _Stop(ExportStatus.HELD, "OBSERVE", VAULT_STAGING_RESIDUE)

    def _execute(self, plan: TransitionPlan) -> None:
        store, locks, action = self.store, self.locks, plan.action
        try:
            if action is _A.PREPARE_INTENT:
                store.write_evidence_bundle(locks, BUNDLES_DIRECTORY, plan.intent_digest, self._bundle_of(plan))
            elif action is _A.RECORD_PRIVATE_BINDING:
                store.write_evidence_bundle(locks, BINDINGS_DIRECTORY, plan.evidence[0][1], self._bundle_of(plan))
            elif action in (_A.STAGE_VERSION, _A.CONTINUE_STAGING):
                store.stage_notes(locks, plan.version_label, dict(plan.staged_notes), tuple(plan.existing_notes))
            elif action is _A.MOVE_STAGED_TO_VERSION:
                store.move_staged(locks, plan.version_label)
            elif action is _A.REPLACE_POINTER:
                store.replace_pointer(locks, plan.expected_pointer, plan.replacement_pointer, self.target.public_export_digest)
            elif action is _A.RECORD_COMPLETION:
                _, digest, data = plan.evidence[0]
                store.write_record(locks, COMPLETIONS_DIRECTORY, digest, data)
            elif action in EXPLICIT_PRESERVATION_ACTIONS:
                store.preserve(locks, plan.preserve_area, plan.preserve_label)
            else:
                raise _Stop(ExportStatus.HELD, "CLASSIFY", UNSUPPORTED_TRANSITION, action.value)
        except ProjectionStoreError as exc:
            raise _Stop(ExportStatus.FAILED, "PRESERVE" if action in EXPLICIT_PRESERVATION_ACTIONS else "WRITE", exc.code,
                        _safe_detail(exc.detail)) from None
        self.transitions.append(action.value)

    def _result(self, status: ExportStatus, code: str, state: Optional[str], binding_recorded: Optional[bool]) -> ExportResult:
        target = self.target
        return ExportResult(status=status, code=code, state=state, transitions=tuple(self.transitions),
                            public_export_digest=None if target is None else target.public_export_digest,
                            version_label=None if target is None else target.version_label, binding_recorded=binding_recorded,
                            failure_residue=self.residue_count)

    def publish(self) -> ExportResult:
        try:
            target = self._prepare_target()
            predicted: Optional[PublicationObservation] = None
            for _ in range(MAX_TRANSITIONS):
                observed = self._observe()
                if predicted is not None and not _same(observed.observation, predicted):
                    raise _Stop(ExportStatus.FAILED, "VERIFY", POST_STATE_MISMATCH)        # 書いた後の disk が予測と byte で一致しない
                classification = classify_publication(observed.observation, target=target)
                action = classification.action
                self._check_residue(observed, classification.transition if action in _EXPECTED_STATE else None)
                if action is _A.NONE:
                    if classification.state is PublicationState.NO_CHANGE and classification.target_binding_recorded:
                        published = any(t != _A.RECORD_PRIVATE_BINDING.value for t in self.transitions)
                        status = ExportStatus.PUBLISHED if published else ExportStatus.NO_CHANGE
                        return self._result(status, status.value, classification.state.value, True)
                    raise _Stop(ExportStatus.HELD, "CLASSIFY", classification.code, state=classification.state.value)
                if action is _A.HOLD:
                    raise _Stop(ExportStatus.HELD, "CLASSIFY", classification.code, state=classification.state.value)
                if action in EXPLICIT_PRESERVATION_ACTIONS:
                    raise _Stop(ExportStatus.HELD, "CLASSIFY", EXPLICIT_PRESERVATION_REQUIRED, action.value, classification.state.value)
                plan = self._checked_plan(observed, classification)
                self._check_residue(observed, plan)                                            # 検査した遷移でもう一度
                predicted = _predict(observed.observation, plan)
                after = classify_publication(predicted, target=target)
                if after.state is PublicationState.FAIL_CLOSED or after.state is not _EXPECTED_STATE[action]:
                    raise _Stop(ExportStatus.HELD, "CLASSIFY", PREDICTED_STATE_INVALID, after.code)
                self._check_capacity(observed, plan)
                self._execute(plan)
            raise _Stop(ExportStatus.FAILED, "CLASSIFY", TRANSITION_LIMIT)
        except _Stop as stop:
            return self._stopped(stop)

    def preserve(self, action: ProposedAction) -> ExportResult:
        try:
            target = self._prepare_target()
            observed = self._observe()
            self._check_residue(observed, None)                                                 # 曖昧な残りが在れば保存もしない
            try:
                plan = check_preservation_proposal(observed.observation, action, target=target)
            except ProjectionError as exc:
                raise _Stop(ExportStatus.HELD, "PRESERVE", exc.code) from None
            if plan.preserve_area not in (PRESERVE_AREA_STAGING, PRESERVE_AREA_RESERVATION):
                raise _Stop(ExportStatus.HELD, "PRESERVE", UNSUPPORTED_TRANSITION)
            predicted = _predict(observed.observation, plan)
            after = classify_publication(predicted, target=target)
            if after.state is PublicationState.FAIL_CLOSED:
                raise _Stop(ExportStatus.HELD, "PRESERVE", PREDICTED_STATE_INVALID, after.code)
            self._check_capacity(observed, plan)
            self._execute(plan)
            reobserved = self._observe()
            if not _same(reobserved.observation, predicted):
                raise _Stop(ExportStatus.FAILED, "VERIFY", POST_STATE_MISMATCH)
            state = classify_publication(reobserved.observation, target=target).state.value
            return self._result(ExportStatus.PRESERVED, PRESERVED, state, None)
        except _Stop as stop:
            return self._stopped(stop)

    # ------------------------------------------------ 失敗の証拠（lock ・root を確かめて書ける時だけ）

    def _stopped(self, stop: _Stop) -> ExportResult:
        result = self._result(stop.status, stop.code, stop.state, None)
        proposed = stop.detail if stop.code == EXPLICIT_PRESERVATION_REQUIRED else None
        return replace(result, proposed_action=proposed, failure_evidence=self._record_failure(stop))

    def _record_failure(self, stop: _Stop) -> str:
        target = self.target
        data = failure_record(operation=self.operation, stage=stop.stage, code=stop.code, detail=stop.detail,
                              generation_digest=self.generation_digest, manifest_digest=self.manifest_digest,
                              public_export_digest=None if target is None else target.public_export_digest)
        try:
            private = self.store.snapshot_private(self.locks)
            if any(kind == "FAILURE" for kind, _ in private.residue):
                return FAILURE_NOT_RECORDED                                                     # 残った ・曖昧な FAILED の一時 file の横には書かない
            need = 2 * storage_units(len(data))
            if private.used_bytes + need > self.limits.private_evidence_bytes:
                return FAILURE_NOT_RECORDED
            if self.store.private_free_space(self.locks) < need + self.limits.free_margin_bytes:
                return FAILURE_NOT_RECORDED
            code = self.store.write_record(self.locks, FAILURES_DIRECTORY, _failure_digest(data), data)
        except (ProjectionStoreError, _Stop):
            return FAILURE_NOT_RECORDED
        return FAILURE_ALREADY_RECORDED if code == EVIDENCE_ALREADY_RECORDED else FAILURE_RECORDED


# ---------------------------------------------------------------- 明示の入口


def _require_inputs(generation_digest: Any, manifest_digest: Any, protected_roots: Any, limits: Any) -> Tuple[Dict[str, Any], ExportLimits]:
    if not (is_digest(generation_digest) and is_digest(manifest_digest)):
        raise ExportInputError(EXPORT_INPUT_INVALID, "FULL_DIGEST_REQUIRED")                # 既定 ・「最新」の選択は無い
    if not isinstance(protected_roots, Mapping):
        raise ExportInputError(EXPORT_INPUT_INVALID, "PROTECTED_ROOTS")
    if set(protected_roots) & {PROJECTION_ROOT_LABEL, VAULT_ROOT_LABEL}:
        raise ExportInputError(EXPORT_INPUT_INVALID, "RESERVED_LABEL")
    if limits is None:
        limits = ExportLimits()
    if not isinstance(limits, ExportLimits):
        raise ExportInputError(EXPORT_INPUT_INVALID, "LIMITS")
    return dict(protected_roots), limits


def _run(private_root: Any, vault_root: Any, operation: str, generation_digest: str, manifest_digest: str, roots: Dict[str, Any],
         limits: ExportLimits, action: Optional[ProposedAction]) -> ExportResult:
    try:
        store = open_projection_store(private_root, vault_root, protected_roots=roots)
        locks = store.acquire_locks(operation=operation)
    except ProjectionStoreError as exc:
        return ExportResult(status=ExportStatus.REFUSED, code=exc.code)                  # lock の外: 証拠は書かない
    session = _Session(store, locks, operation, generation_digest, manifest_digest, roots, limits)
    try:
        result = session.publish() if action is None else session.preserve(action)
    finally:
        release = locks.release()                                                         # 全ての経路（所有を検証できなければ残す）
    return replace(result, lock_release=release)


def publish_projection(private_root: Any, vault_root: Any, *, generation_digest: str, manifest_digest: str,
                       protected_roots: Mapping[str, Any], limits: Optional[ExportLimits] = None) -> ExportResult:
    """A3 の検証済みの公開と一致する明示の generation を、A4a1 の後継の契約に従って vault の `generated/` に版として公開する。"""
    roots, checked = _require_inputs(generation_digest, manifest_digest, protected_roots, limits)
    return _run(private_root, vault_root, "PUBLISH", generation_digest, manifest_digest, roots, checked, None)


def preserve_projection_staging(private_root: Any, vault_root: Any, *, generation_digest: str, manifest_digest: str,
                                protected_roots: Mapping[str, Any], action: Any, limits: Optional[ExportLimits] = None) -> ExportResult:
    """人の明示の保存: A4a1 が明示だけの適格と認めた 1 つの保存（切れた staging ・空の版の予約）を `.p13-interrupted/` に移す（消さない ・
    自動では呼ばれない ・公開は続けない）。"""
    roots, checked = _require_inputs(generation_digest, manifest_digest, protected_roots, limits)
    try:
        chosen = ProposedAction(action)
    except ValueError:
        raise ExportInputError(EXPORT_INPUT_INVALID, "ACTION") from None
    if chosen not in EXPLICIT_PRESERVATION_ACTIONS:
        raise ExportInputError(EXPORT_INPUT_INVALID, "ACTION")
    return _run(private_root, vault_root, "PRESERVE", generation_digest, manifest_digest, roots, checked, chosen)


__all__ = ["BINDING_BUNDLE_RECORDS", "CAPACITY_EXCEEDED", "EVIDENCE_DUPLICATE", "EVIDENCE_INVALID", "EVIDENCE_STAGING_RESIDUE",
           "EXPLICIT_PRESERVATION_REQUIRED", "EXPORT_INPUT_INVALID", "ExportInputError", "ExportLimits", "ExportResult", "ExportScanError",
           "ExportStatus", "FAILURE_ALREADY_RECORDED", "FAILURE_AUTHORITY_CLASS", "FAILURE_DOMAIN", "FAILURE_EVIDENCE_INVALID",
           "FAILURE_NOT_RECORDED", "FAILURE_NOT_REQUIRED", "FAILURE_RECORDED", "FAILURE_SCHEMA_VERSION", "FAILURE_STAGES",
           "INTENT_BUNDLE_RECORDS", "LIMIT_LOOSENED", "MAX_OBSERVATION_OBJECTS", "MAX_PRIVATE_EVIDENCE_BYTES", "MAX_RETAINED_VERSIONS",
           "MAX_TRANSITIONS", "MAX_VAULT_EXPORT_BYTES", "MIN_FREE_MARGIN_BYTES", "POST_STATE_MISMATCH", "PREDICTED_STATE_INVALID",
           "PRESERVED", "SCAN_AUTHORITY_CLASS", "SCAN_DOMAIN", "SCAN_EVIDENCE_INVALID", "SCAN_FAILED", "SCAN_PATTERNS", "SCAN_PROCEDURE",
           "SCAN_RESULT_DETECTED", "SCAN_RESULT_PASSED", "SCAN_RULES_DOMAIN", "SCAN_RULES_DRIFT", "SCAN_RULES_VERSION",
           "SCAN_SCHEMA_VERSION", "SOURCE_EVIDENCE_INVALID", "SOURCE_NOT_PUBLISHED_GENERATION", "SOURCE_NOT_VERIFIED",
           "SOURCE_READ_ATTESTATION", "SOURCE_READ_DOMAIN", "SOURCE_READ_SCHEMA_VERSION", "SOURCE_STAGING_PRESENT", "SOURCE_UNAVAILABLE",
           "SOURCE_UNVERIFIED", "TRANSITION_LIMIT", "UNSUPPORTED_TRANSITION", "VAULT_STAGING_RESIDUE", "failure_record",
           "preserve_projection_staging", "publish_projection", "scan_record", "scan_record_digest", "scan_rules_digest", "source_record"]
