"""P13-A3 — Memory の generation ・manifest ・公開の pointer ・試行の証拠の純粋な model（file の I/O は無い）。

3 つの identity を分ける（混ぜない）:
- **plan digest**: 要求した順序つきの cutoff の計画（A1 の `build_digest` に memory の規則 ・adapter の規則 ・変化 ／ generation ／ store の
  schema の記述子を足す）。読む前に計算できる。
- **generation digest**: 計画から実際に作った正準な結果（標本 ・変化の完全な digest の列 ・全ての schema ／ 規則の version）。同じ計画から
  byte 一致の結果が出れば同じ digest になる（REUSED）。
- **manifest digest**: 公開した artifact の集合（名前 ・byte 長 ・sha256）の完全性。
telemetry（取得の時刻 ・壁時計 ・host ・process ・root の位置 ・file system の metadata）はどれにも入らない。

検証（`verify_generation_records`）は byte の写像だけを受ける: manifest の file の集合の完全一致（欠落 ・余分）・長さ ・sha256 ・
全 record の正準性（往復）・標本の完全な digest と file 名の一致 ・変化の端点の差の再生（A1 の `detect_changes_over`）・計画 ／ generation の
digest の再計算 ・略記 id の衝突。source（P9 ／ P10）の authority の完全性 ・store をまたぐ不可分性は **確立しない**（A2a の ABA の限界を保つ）。
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from typing import Any, Dict, Mapping, Optional, Sequence, Tuple

from .canonical import (CanonicalError, assert_no_short_id_collision, canonical_json, domain_digest, is_digest, require_fields,
                        require_safe_code, short_id)
from .review_state_change import CHANGE_SCHEMA_VERSION, ReviewStateChange, detect_changes_over
from .review_state_sample import (SAMPLE_SCHEMA_VERSION, OutcomeStatus, ReviewStateError, ReviewStateSample, SampleCutoff,
                                  SampleOutcome, SourceViewIdentity, StalenessLabel, build_digest, check_sample_ids,
                                  staleness_label)

STORE_SCHEMA_VERSION = "p13_memory_store:0.1.0"
MEMORY_RULES_VERSION = "p13_memory_rules:0.1.0"
GENERATION_SCHEMA_VERSION = "p13_memory_generation:0.1.0"
MANIFEST_SCHEMA_VERSION = "p13_memory_manifest:0.1.0"
PUBLICATION_SCHEMA_VERSION = "p13_memory_publication:0.1.0"
ATTEMPT_SCHEMA_VERSION = "p13_memory_attempt:0.1.0"
GENERATION_DOMAIN = "p13.memory_generation.v1"
MANIFEST_DOMAIN = "p13.memory_manifest.v1"
ATTEMPT_DOMAIN = "p13.memory_attempt.v1"
GENERATION_ID_PREFIX = "p13gen_"
LOCK_SCHEMA_VERSION = "p13_memory_writer_lock:0.1.0"
LOCK_OPERATIONS = ("BUILD", "PRESERVE")
ROOT_CLASS = "P13_PRIVATE_MEMORY_ROOT_DERIVED_NON_AUTHORITY"
GENERATION_AUTHORITY_CLASS = "DERIVED_REVIEW_STATE_MEMORY_GENERATION_NON_AUTHORITY"
SOURCE_INTEGRITY_CLASS = "SOURCE_AUTHORITY_INTEGRITY_NOT_ESTABLISHED_NO_ROOT_MANIFEST_NO_CROSS_STORE_ATOMICITY"
ATTEMPT_DISPOSITION = "INCOMPLETE_PLAN_NOT_PUBLISHED"
#: 検証済みの adapter の規則の version（`governed_review_source.ADAPTER_RULES_VERSION` と test が一致を確かめる ・これ以外は fail closed）
SUPPORTED_ADAPTER_RULES_VERSIONS = frozenset({"p13_governed_review_source:0.1.0"})
GENERATION_RECORD_NAME = "generation.json"
CHANGES_RECORD_NAME = "changes.jsonl"
MANIFEST_RECORD_NAME = "manifest.json"
SAMPLE_RECORD_PREFIX = "sample."
RECORD_SUFFIX = ".json"
MAX_PLAN_CUTOFFS = 256
MAX_RECORD_BYTES = 16 * 1024 * 1024
MAX_GENERATION_RECORDS = MAX_PLAN_CUTOFFS + 3

#: 結果の code（固定の定数だけ ・値 ・path は持たない）
PLAN_INVALID = "PLAN_INVALID"
CUTOFF_ORDER_INVALID = "CUTOFF_ORDER_INVALID"
GENERATION_INVALID = "GENERATION_INVALID"
SAMPLES_INCONSISTENT = "SAMPLES_INCONSISTENT"
CHANGES_INCONSISTENT = "CHANGES_INCONSISTENT"
SHORT_ID_COLLISION = "SHORT_ID_COLLISION"
RECORD_CORRUPT = "RECORD_CORRUPT"
RECORD_DIGEST_MISMATCH = "RECORD_DIGEST_MISMATCH"
SCHEMA_UNSUPPORTED = "SCHEMA_UNSUPPORTED"
MANIFEST_INVALID = "MANIFEST_INVALID"
MANIFEST_MISMATCH = "MANIFEST_MISMATCH"
GENERATION_INCOMPLETE = "GENERATION_INCOMPLETE"
UNAUTHORIZED_ENTRY = "UNAUTHORIZED_ENTRY"
GENERATION_DIGEST_MISMATCH = "GENERATION_DIGEST_MISMATCH"
PLAN_DIGEST_MISMATCH = "PLAN_DIGEST_MISMATCH"
PUBLICATION_INVALID = "PUBLICATION_INVALID"
ATTEMPT_INVALID = "ATTEMPT_INVALID"
GENERATION_CODES = frozenset({PLAN_INVALID, CUTOFF_ORDER_INVALID, GENERATION_INVALID, SAMPLES_INCONSISTENT, CHANGES_INCONSISTENT,
                              SHORT_ID_COLLISION, RECORD_CORRUPT, RECORD_DIGEST_MISMATCH, SCHEMA_UNSUPPORTED, MANIFEST_INVALID,
                              MANIFEST_MISMATCH, GENERATION_INCOMPLETE, UNAUTHORIZED_ENTRY, GENERATION_DIGEST_MISMATCH,
                              PLAN_DIGEST_MISMATCH, PUBLICATION_INVALID, ATTEMPT_INVALID})

_GENERATION_FIELDS = frozenset({"schema_version", "store_schema_version", "memory_rules_version", "adapter_rules_version",
                                "sample_schema_version", "change_schema_version", "view_identity", "cutoffs", "plan_digest",
                                "sample_digests", "change_digests", "authority_class", "source_integrity_class"})
_MANIFEST_FIELDS = frozenset({"schema_version", "generation_digest", "files"})
_PUBLICATION_FIELDS = frozenset({"schema_version", "generation_digest", "manifest_digest"})
_ATTEMPT_FIELDS = frozenset({"schema_version", "plan_digest", "cutoffs", "outcomes", "disposition"})


class MemoryGenerationError(ValueError):
    """generation ・manifest ・pointer ・試行の証拠の失敗（固定の code ・短い detail だけ。値 ・本文 ・path は持たない）。"""

    def __init__(self, code: str, detail: str = "") -> None:
        super().__init__(f"{code}:{detail}" if detail else code)
        self.code = code
        self.detail = detail


def _require(condition: bool, code: str, detail: str = "") -> None:
    if not condition:
        raise MemoryGenerationError(code, detail)


def record_bytes(value: Any) -> bytes:
    """正準 JSON ＋ LF 1 つ（UTF-8 ・CR は無い）。全ての record の byte の形。"""
    return (canonical_json(value) + "\n").encode("utf-8")


def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sample_record_name(sample_digest: str) -> str:
    _require(is_digest(sample_digest), GENERATION_INVALID, "SAMPLE_DIGEST")
    return SAMPLE_RECORD_PREFIX + sample_digest + RECORD_SUFFIX


def is_generation_record_name(name: Any) -> bool:
    """generation の directory に在ってよい名前（manifest ・generation ・変化 ・`sample.<完全な digest>.json`）だけ。"""
    if not isinstance(name, str):
        return False
    if name in (MANIFEST_RECORD_NAME, GENERATION_RECORD_NAME, CHANGES_RECORD_NAME):
        return True
    middle = name[len(SAMPLE_RECORD_PREFIX):-len(RECORD_SUFFIX)]
    return name.startswith(SAMPLE_RECORD_PREFIX) and name.endswith(RECORD_SUFFIX) and is_digest(middle)


# ---------------------------------------------------------------- 計画（plan digest）


def validate_plan(cutoffs: Any) -> Tuple[SampleCutoff, ...]:
    """明示の順序つきの cutoff の計画: 1 〜 `MAX_PLAN_CUTOFFS` 個 ・`at` は厳密に増加 ・`as_of_date` は減らない（重複 ・逆順は拒む）。"""
    _require(isinstance(cutoffs, (tuple, list)) and 1 <= len(cutoffs) <= MAX_PLAN_CUTOFFS, PLAN_INVALID, "CUTOFF_COUNT")
    _require(all(isinstance(c, SampleCutoff) for c in cutoffs), PLAN_INVALID, "CUTOFF_TYPE")
    plan = tuple(cutoffs)
    for earlier, later in zip(plan, plan[1:]):
        _require(earlier.at < later.at and earlier.as_of_date <= later.as_of_date, CUTOFF_ORDER_INVALID, "NOT_STRICTLY_INCREASING")
    return plan


def plan_descriptors(adapter_rules_version: str) -> Tuple[Tuple[str, str], ...]:
    _require(adapter_rules_version in SUPPORTED_ADAPTER_RULES_VERSIONS, SCHEMA_UNSUPPORTED, "ADAPTER_RULES")
    return (("ADAPTER_RULES", adapter_rules_version), ("CHANGE_SCHEMA", CHANGE_SCHEMA_VERSION),
            ("GENERATION_SCHEMA", GENERATION_SCHEMA_VERSION), ("STORE_SCHEMA", STORE_SCHEMA_VERSION))


def plan_digest(cutoffs: Sequence[SampleCutoff], view_identity: SourceViewIdentity, *, adapter_rules_version: str) -> str:
    """要求した計画の identity（A1 の `build_digest` ・memory の規則の version ・記述子）。telemetry ・root の位置は無い。"""
    plan = validate_plan(cutoffs)
    _require(isinstance(view_identity, SourceViewIdentity), PLAN_INVALID, "VIEW_IDENTITY")
    descriptors = plan_descriptors(adapter_rules_version)
    try:
        return build_digest(plan, view_identity, rules_version=MEMORY_RULES_VERSION, input_descriptors=descriptors)
    except (ReviewStateError, CanonicalError) as exc:
        raise MemoryGenerationError(PLAN_INVALID, exc.code) from None


def replay_changes(samples: Tuple[ReviewStateSample, ...]) -> Tuple[ReviewStateChange, ...]:
    """隣接する標本の端点の差の再生（標本が 1 つなら変化は無い）。"""
    if len(samples) < 2:
        return ()
    try:
        return detect_changes_over(samples)
    except CanonicalError as exc:
        raise MemoryGenerationError(SHORT_ID_COLLISION if exc.code == "SHORT_ID_COLLISION" else SAMPLES_INCONSISTENT, exc.code) from None
    except ReviewStateError as exc:
        raise MemoryGenerationError(SAMPLES_INCONSISTENT, exc.code) from None


# ---------------------------------------------------------------- generation（generation digest）


@dataclass(frozen=True, kw_only=True)
class MemoryGeneration:
    """1 つの完全な計画（全ての cutoff が SAMPLED）から作った正準な結果。変化は標本から再生した列と一致すること。"""

    cutoffs: Tuple[SampleCutoff, ...]
    view_identity: SourceViewIdentity
    adapter_rules_version: str
    samples: Tuple[ReviewStateSample, ...]
    changes: Tuple[ReviewStateChange, ...]

    def __post_init__(self) -> None:
        _require(isinstance(self.cutoffs, tuple), PLAN_INVALID, "CUTOFFS_NOT_A_TUPLE")
        validate_plan(self.cutoffs)
        _require(isinstance(self.view_identity, SourceViewIdentity), GENERATION_INVALID, "VIEW_IDENTITY")
        _require(self.adapter_rules_version in SUPPORTED_ADAPTER_RULES_VERSIONS, SCHEMA_UNSUPPORTED, "ADAPTER_RULES")
        _require(isinstance(self.samples, tuple) and all(isinstance(s, ReviewStateSample) for s in self.samples),
                 GENERATION_INVALID, "SAMPLES")
        _require(len(self.samples) == len(self.cutoffs), SAMPLES_INCONSISTENT, "SAMPLE_COUNT")
        for cutoff, sample in zip(self.cutoffs, self.samples):
            _require(sample.cutoff == cutoff, SAMPLES_INCONSISTENT, "SAMPLE_CUTOFF")
            _require(sample.view_identity == self.view_identity, SAMPLES_INCONSISTENT, "SAMPLE_VIEW_IDENTITY")
            _require(sample.rules_version == self.adapter_rules_version, SAMPLES_INCONSISTENT, "SAMPLE_RULES_VERSION")
        try:
            check_sample_ids(self.samples)
        except CanonicalError as exc:
            raise MemoryGenerationError(SHORT_ID_COLLISION, exc.code) from None
        _require(isinstance(self.changes, tuple) and all(isinstance(c, ReviewStateChange) for c in self.changes),
                 GENERATION_INVALID, "CHANGES")
        expected = replay_changes(self.samples)
        _require([c.content() for c in self.changes] == [c.content() for c in expected], CHANGES_INCONSISTENT, "REPLAY")
        try:
            assert_no_short_id_collision((c.change_id, c.change_digest) for c in self.changes)
        except CanonicalError as exc:
            raise MemoryGenerationError(SHORT_ID_COLLISION, exc.code) from None

    @property
    def plan_digest(self) -> str:
        return plan_digest(self.cutoffs, self.view_identity, adapter_rules_version=self.adapter_rules_version)

    def content(self) -> Dict[str, Any]:
        return {"schema_version": GENERATION_SCHEMA_VERSION, "store_schema_version": STORE_SCHEMA_VERSION,
                "memory_rules_version": MEMORY_RULES_VERSION, "adapter_rules_version": self.adapter_rules_version,
                "sample_schema_version": SAMPLE_SCHEMA_VERSION, "change_schema_version": CHANGE_SCHEMA_VERSION,
                "view_identity": self.view_identity.content(), "cutoffs": [c.content() for c in self.cutoffs],
                "plan_digest": self.plan_digest, "sample_digests": [s.sample_digest for s in self.samples],
                "change_digests": [c.change_digest for c in self.changes], "authority_class": GENERATION_AUTHORITY_CLASS,
                "source_integrity_class": SOURCE_INTEGRITY_CLASS}

    @property
    def generation_digest(self) -> str:
        return domain_digest(GENERATION_DOMAIN, self.content())

    @property
    def generation_id(self) -> str:
        return short_id(GENERATION_ID_PREFIX, self.generation_digest)

    def records(self) -> Dict[str, bytes]:
        """manifest を除く artifact の byte（名前 → byte）。全て正準 ・LF だけ。変化が無ければ変化の file は空。"""
        records = {GENERATION_RECORD_NAME: record_bytes(self.content()),
                   CHANGES_RECORD_NAME: b"".join(record_bytes(c.content()) for c in self.changes)}
        for sample in self.samples:
            records[sample_record_name(sample.sample_digest)] = record_bytes(sample.content())
        return records

    def manifest(self) -> "GenerationManifest":
        entries = tuple(ManifestEntry(name=name, size=len(data), sha256=sha256_hex(data))
                        for name, data in sorted(self.records().items()))
        return GenerationManifest(generation_digest=self.generation_digest, entries=entries)


def build_generation(cutoffs: Sequence[SampleCutoff], view_identity: SourceViewIdentity, *, adapter_rules_version: str,
                     samples: Sequence[ReviewStateSample]) -> MemoryGeneration:
    """完全な計画の標本から generation を作る（変化は端点の差を再生する）。"""
    plan = validate_plan(cutoffs)
    _require(isinstance(samples, (tuple, list)), GENERATION_INVALID, "SAMPLES")
    ordered = tuple(samples)
    _require(all(isinstance(s, ReviewStateSample) for s in ordered), GENERATION_INVALID, "SAMPLES")
    return MemoryGeneration(cutoffs=plan, view_identity=view_identity, adapter_rules_version=adapter_rules_version,
                            samples=ordered, changes=replay_changes(ordered))


# ---------------------------------------------------------------- manifest（manifest digest）


@dataclass(frozen=True, kw_only=True)
class ManifestEntry:
    name: str
    size: int
    sha256: str

    def __post_init__(self) -> None:
        _require(is_generation_record_name(self.name) and self.name != MANIFEST_RECORD_NAME, MANIFEST_INVALID, "NAME")
        _require(type(self.size) is int and 0 <= self.size <= MAX_RECORD_BYTES, MANIFEST_INVALID, "SIZE")
        _require(is_digest(self.sha256), MANIFEST_INVALID, "SHA256")


@dataclass(frozen=True, kw_only=True)
class GenerationManifest:
    """generation の directory の manifest 以外の全 file（名前で sort ・重複無し）の名前 ・長さ ・sha256。"""

    generation_digest: str
    entries: Tuple[ManifestEntry, ...]
    schema_version: str = MANIFEST_SCHEMA_VERSION

    def __post_init__(self) -> None:
        _require(self.schema_version == MANIFEST_SCHEMA_VERSION, SCHEMA_UNSUPPORTED, "MANIFEST")
        _require(is_digest(self.generation_digest), MANIFEST_INVALID, "GENERATION_DIGEST")
        _require(isinstance(self.entries, tuple) and all(isinstance(e, ManifestEntry) for e in self.entries), MANIFEST_INVALID, "ENTRIES")
        names = [e.name for e in self.entries]
        _require(names == sorted(names) and len(set(names)) == len(names), MANIFEST_INVALID, "ENTRY_ORDER_OR_DUPLICATE")
        _require(GENERATION_RECORD_NAME in names and CHANGES_RECORD_NAME in names, MANIFEST_INVALID, "REQUIRED_ENTRIES")
        _require(len(names) <= MAX_GENERATION_RECORDS, MANIFEST_INVALID, "ENTRY_COUNT")

    def content(self) -> Dict[str, Any]:
        return {"schema_version": self.schema_version, "generation_digest": self.generation_digest,
                "files": [[e.name, e.size, e.sha256] for e in self.entries]}

    def to_bytes(self) -> bytes:
        return record_bytes(self.content())

    @property
    def manifest_digest(self) -> str:
        return domain_digest(MANIFEST_DOMAIN, self.content())


# ---------------------------------------------------------------- 公開の pointer ・試行の証拠


@dataclass(frozen=True, kw_only=True)
class PublicationRecord:
    """`publication.json`: 公開した generation の digest と、その manifest の digest（両方の再検証が公開の成功の条件）。"""

    generation_digest: str
    manifest_digest: str
    schema_version: str = PUBLICATION_SCHEMA_VERSION

    def __post_init__(self) -> None:
        _require(self.schema_version == PUBLICATION_SCHEMA_VERSION, SCHEMA_UNSUPPORTED, "PUBLICATION")
        _require(is_digest(self.generation_digest) and is_digest(self.manifest_digest), PUBLICATION_INVALID, "DIGESTS")

    def content(self) -> Dict[str, str]:
        return {"schema_version": self.schema_version, "generation_digest": self.generation_digest,
                "manifest_digest": self.manifest_digest}

    def to_bytes(self) -> bytes:
        return record_bytes(self.content())


@dataclass(frozen=True, kw_only=True)
class AttemptRecord:
    """完全でない計画の安全な証拠: 計画の digest ・cutoff ・cutoff ごとの状態と固定の code だけ（標本 ・source の詳細 ・telemetry は無い）。"""

    plan_digest: str
    cutoffs: Tuple[SampleCutoff, ...]
    outcomes: Tuple[Tuple[str, str], ...]
    disposition: str = ATTEMPT_DISPOSITION
    schema_version: str = ATTEMPT_SCHEMA_VERSION

    def __post_init__(self) -> None:
        _require(self.schema_version == ATTEMPT_SCHEMA_VERSION, SCHEMA_UNSUPPORTED, "ATTEMPT")
        _require(self.disposition == ATTEMPT_DISPOSITION, ATTEMPT_INVALID, "DISPOSITION")
        _require(is_digest(self.plan_digest), ATTEMPT_INVALID, "PLAN_DIGEST")
        _require(isinstance(self.cutoffs, tuple), ATTEMPT_INVALID, "CUTOFFS")
        validate_plan(self.cutoffs)
        _require(isinstance(self.outcomes, tuple) and len(self.outcomes) == len(self.cutoffs), ATTEMPT_INVALID, "OUTCOME_COUNT")
        for pair in self.outcomes:
            _require(isinstance(pair, tuple) and len(pair) == 2, ATTEMPT_INVALID, "OUTCOME_SHAPE")
            status, code = pair
            _require(status in {s.value for s in OutcomeStatus}, ATTEMPT_INVALID, "OUTCOME_STATUS")
            if status == OutcomeStatus.SAMPLED.value:
                _require(code == "", ATTEMPT_INVALID, "SAMPLED_WITH_CODE")
            else:
                try:
                    require_safe_code(code, ATTEMPT_INVALID)
                except CanonicalError:
                    raise MemoryGenerationError(ATTEMPT_INVALID, "FAILURE_CODE") from None
        _require(any(status != OutcomeStatus.SAMPLED.value for status, _ in self.outcomes), ATTEMPT_INVALID, "PLAN_WAS_COMPLETE")

    def content(self) -> Dict[str, Any]:
        return {"schema_version": self.schema_version, "plan_digest": self.plan_digest, "cutoffs": [c.content() for c in self.cutoffs],
                "outcomes": [[status, code] for status, code in self.outcomes], "disposition": self.disposition}

    @property
    def attempt_digest(self) -> str:
        return domain_digest(ATTEMPT_DOMAIN, self.content())

    def to_bytes(self) -> bytes:
        return record_bytes(self.content())


def attempt_from_outcomes(plan: str, cutoffs: Sequence[SampleCutoff], outcomes: Sequence[SampleOutcome]) -> AttemptRecord:
    _require(isinstance(outcomes, (tuple, list)) and all(isinstance(o, SampleOutcome) for o in outcomes), ATTEMPT_INVALID, "OUTCOMES")
    return AttemptRecord(plan_digest=plan, cutoffs=validate_plan(cutoffs),
                         outcomes=tuple((o.status.value, o.failure_code) for o in outcomes))


def marker_bytes() -> bytes:
    """root の目印の byte（store の schema の version と root の class だけ ・path ・時刻 ・host は無い）。"""
    return record_bytes({"schema_version": STORE_SCHEMA_VERSION, "root_class": ROOT_CLASS})


def lock_bytes(operation: str, plan: Optional[str]) -> bytes:
    """writer lock の byte（操作 ・計画の digest だけ。pid ・時刻 ・host ・user は無い ＝ 所有は作成した file の identity で確かめる）。"""
    _require(operation in LOCK_OPERATIONS, GENERATION_INVALID, "LOCK_OPERATION")
    _require(plan is None or is_digest(plan), GENERATION_INVALID, "LOCK_PLAN")
    return record_bytes({"schema_version": LOCK_SCHEMA_VERSION, "operation": operation, "plan_digest": plan})


# ---------------------------------------------------------------- 厳密な読み


def _parse_record(data: Any, *, schema: str, context: str) -> Dict[str, Any]:
    """UTF-8 の JSON の mapping ・文字の `schema_version` が支持する版（無ければ RECORD_CORRUPT ・違えば SCHEMA_UNSUPPORTED）。"""
    _require(isinstance(data, bytes), RECORD_CORRUPT, context)
    try:
        value = json.loads(data.decode("utf-8"))
    except (ValueError, RecursionError):
        raise MemoryGenerationError(RECORD_CORRUPT, context) from None
    _require(isinstance(value, dict) and isinstance(value.get("schema_version"), str), RECORD_CORRUPT, context)
    _require(value["schema_version"] == schema, SCHEMA_UNSUPPORTED, context)
    return value


def _require_canonical(data: bytes, content: Any, context: str) -> None:
    try:
        expected = record_bytes(content)
    except CanonicalError:
        raise MemoryGenerationError(RECORD_CORRUPT, context) from None
    _require(expected == data, RECORD_CORRUPT, f"{context}:NON_CANONICAL")


def check_marker(data: Any) -> None:
    """目印の厳密な照合（別の schema の版は SCHEMA_UNSUPPORTED ・それ以外の不一致は RECORD_CORRUPT）。"""
    _parse_record(data, schema=STORE_SCHEMA_VERSION, context="MARKER")
    _require(data == marker_bytes(), RECORD_CORRUPT, "MARKER")


def parse_manifest(data: Any) -> GenerationManifest:
    """manifest の厳密な読み（別の版は SCHEMA_UNSUPPORTED ・形 ・正準性 ・JSON の失敗は全て MANIFEST_INVALID）。"""
    try:
        value = _parse_record(data, schema=MANIFEST_SCHEMA_VERSION, context="MANIFEST")
        fields_ = require_fields(value, _MANIFEST_FIELDS, "GenerationManifest")
        files = fields_["files"]
        _require(isinstance(files, list) and all(isinstance(f, list) and len(f) == 3 for f in files), MANIFEST_INVALID, "FILES")
        manifest = GenerationManifest(generation_digest=fields_["generation_digest"],
                                      entries=tuple(ManifestEntry(name=n, size=s, sha256=h) for n, s, h in files))
        _require_canonical(data, manifest.content(), "MANIFEST")
    except MemoryGenerationError as exc:
        raise MemoryGenerationError(exc.code if exc.code == SCHEMA_UNSUPPORTED else MANIFEST_INVALID, exc.detail) from None
    except (ValueError, TypeError):
        raise MemoryGenerationError(MANIFEST_INVALID, "MANIFEST") from None
    return manifest


def parse_publication(data: Any) -> PublicationRecord:
    value = _parse_record(data, schema=PUBLICATION_SCHEMA_VERSION, context="PUBLICATION")
    try:
        record = PublicationRecord(**require_fields(value, _PUBLICATION_FIELDS, "PublicationRecord"))
    except MemoryGenerationError:
        raise
    except (ValueError, TypeError):
        raise MemoryGenerationError(PUBLICATION_INVALID, "PUBLICATION") from None
    _require_canonical(data, record.content(), "PUBLICATION")
    return record


def parse_attempt(data: Any) -> AttemptRecord:
    value = _parse_record(data, schema=ATTEMPT_SCHEMA_VERSION, context="ATTEMPT")
    try:
        fields_ = require_fields(value, _ATTEMPT_FIELDS, "AttemptRecord")
        record = AttemptRecord(plan_digest=fields_["plan_digest"],
                               cutoffs=tuple(SampleCutoff.from_dict(c) for c in fields_["cutoffs"]),
                               outcomes=tuple((s, c) for s, c in fields_["outcomes"]), disposition=fields_["disposition"])
    except MemoryGenerationError:
        raise
    except (ValueError, TypeError):
        raise MemoryGenerationError(ATTEMPT_INVALID, "ATTEMPT") from None
    _require_canonical(data, record.content(), "ATTEMPT")
    return record


def _parse_sample(data: bytes, expected_digest: str) -> ReviewStateSample:
    value = _parse_record(data, schema=SAMPLE_SCHEMA_VERSION, context="SAMPLE")
    try:
        sample = ReviewStateSample.from_dict(value)
    except (ValueError, TypeError):
        raise MemoryGenerationError(RECORD_CORRUPT, "SAMPLE") from None
    _require_canonical(data, sample.content(), "SAMPLE")
    _require(sample.sample_digest == expected_digest, RECORD_DIGEST_MISMATCH, "SAMPLE")
    return sample


def _parse_changes(data: bytes) -> Tuple[ReviewStateChange, ...]:
    _require(isinstance(data, bytes), RECORD_CORRUPT, "CHANGES")
    if data == b"":
        return ()
    _require(data.endswith(b"\n"), RECORD_CORRUPT, "CHANGES:LINE_END")
    changes = []
    for line in data[:-1].split(b"\n"):
        value = _parse_record(line, schema=CHANGE_SCHEMA_VERSION, context="CHANGE")
        try:
            change = ReviewStateChange.from_dict(value)
        except (ValueError, TypeError):
            raise MemoryGenerationError(RECORD_CORRUPT, "CHANGE") from None
        _require_canonical(line + b"\n", change.content(), "CHANGE")
        changes.append(change)
    return tuple(changes)


@dataclass(frozen=True, kw_only=True)
class VerifiedGeneration:
    """全ての検証を通った generation（byte から再構成した model と manifest）。"""

    generation: MemoryGeneration = field(repr=False)
    manifest: GenerationManifest = field(repr=False)

    @property
    def generation_digest(self) -> str:
        return self.generation.generation_digest

    @property
    def manifest_digest(self) -> str:
        return self.manifest.manifest_digest


def verify_generation_records(records: Mapping[str, bytes], *, expected_generation_digest: str) -> VerifiedGeneration:
    """generation の directory の byte の写像（名前 → byte）を厳密に検証する。どれか 1 つでも合わなければ fail closed。"""
    _require(is_digest(expected_generation_digest), GENERATION_INVALID, "EXPECTED_DIGEST")
    _require(isinstance(records, Mapping) and all(isinstance(v, bytes) for v in records.values()), GENERATION_INVALID, "RECORDS")
    names = set(records)
    _require(all(is_generation_record_name(n) for n in names), UNAUTHORIZED_ENTRY, "NAME")
    _require(MANIFEST_RECORD_NAME in names, GENERATION_INCOMPLETE, "MANIFEST")
    manifest = parse_manifest(records[MANIFEST_RECORD_NAME])
    listed = {e.name for e in manifest.entries}
    _require(not (names - {MANIFEST_RECORD_NAME}) - listed, UNAUTHORIZED_ENTRY, "UNLISTED_FILE")
    _require(not listed - names, GENERATION_INCOMPLETE, "LISTED_FILE_ABSENT")
    for entry in manifest.entries:
        data = records[entry.name]
        _require(len(data) == entry.size and sha256_hex(data) == entry.sha256, MANIFEST_MISMATCH, "SIZE_OR_SHA256")
    _require(manifest.generation_digest == expected_generation_digest, GENERATION_DIGEST_MISMATCH, "MANIFEST")

    value = _parse_record(records[GENERATION_RECORD_NAME], schema=GENERATION_SCHEMA_VERSION, context="GENERATION")
    try:
        fields_ = require_fields(value, _GENERATION_FIELDS, "MemoryGeneration")
    except CanonicalError:
        raise MemoryGenerationError(RECORD_CORRUPT, "GENERATION") from None
    supported = {"store_schema_version": STORE_SCHEMA_VERSION, "memory_rules_version": MEMORY_RULES_VERSION,
                 "sample_schema_version": SAMPLE_SCHEMA_VERSION, "change_schema_version": CHANGE_SCHEMA_VERSION}
    for key, version in supported.items():
        _require(fields_[key] == version, SCHEMA_UNSUPPORTED, key.upper())
    _require(fields_["adapter_rules_version"] in SUPPORTED_ADAPTER_RULES_VERSIONS, SCHEMA_UNSUPPORTED, "ADAPTER_RULES_VERSION")
    _require(fields_["authority_class"] == GENERATION_AUTHORITY_CLASS and fields_["source_integrity_class"] == SOURCE_INTEGRITY_CLASS,
             RECORD_CORRUPT, "GENERATION:CLASS")
    try:
        cutoffs = tuple(SampleCutoff.from_dict(c) for c in fields_["cutoffs"])
        view_identity = SourceViewIdentity.from_dict(fields_["view_identity"])
        sample_digests = list(fields_["sample_digests"])
    except (ValueError, TypeError):
        raise MemoryGenerationError(RECORD_CORRUPT, "GENERATION") from None
    _require(all(is_digest(d) for d in sample_digests) and len(set(sample_digests)) == len(sample_digests), RECORD_CORRUPT,
             "GENERATION:SAMPLE_DIGESTS")
    sample_names = {sample_record_name(d) for d in sample_digests}
    present_samples = {n for n in names if n.startswith(SAMPLE_RECORD_PREFIX)}
    _require(not present_samples - sample_names, UNAUTHORIZED_ENTRY, "UNREFERENCED_SAMPLE")
    _require(not sample_names - present_samples, GENERATION_INCOMPLETE, "SAMPLE_ABSENT")
    samples = tuple(_parse_sample(records[sample_record_name(d)], d) for d in sample_digests)
    changes = _parse_changes(records[CHANGES_RECORD_NAME])
    generation = MemoryGeneration(cutoffs=cutoffs, view_identity=view_identity, adapter_rules_version=fields_["adapter_rules_version"],
                                  samples=samples, changes=changes)                      # 変化の再生 ・略記 id の衝突はここで検査
    rebuilt = generation.content()
    _require(rebuilt["plan_digest"] == fields_["plan_digest"], PLAN_DIGEST_MISMATCH, "GENERATION")
    _require(rebuilt == fields_, GENERATION_DIGEST_MISMATCH, "GENERATION_CONTENT")
    _require_canonical(records[GENERATION_RECORD_NAME], rebuilt, "GENERATION")
    _require(generation.generation_digest == expected_generation_digest, GENERATION_DIGEST_MISMATCH, "EXPECTED")
    _require(generation.manifest() == manifest, MANIFEST_MISMATCH, "REBUILT_MANIFEST")
    return VerifiedGeneration(generation=generation, manifest=manifest)


def staleness_of(verified: VerifiedGeneration, *, evaluation_cutoff: SampleCutoff, window_days: int) -> StalenessLabel:
    """鮮度の label だけ（trigger ではない）: generation の最後の cutoff と、呼び出し側が明示した評価の cutoff の間の日数。時計は無い。"""
    _require(isinstance(verified, VerifiedGeneration), GENERATION_INVALID, "VERIFIED")
    try:
        return staleness_label(verified.generation.cutoffs[-1], evaluation_cutoff, window_days=window_days)
    except ReviewStateError as exc:
        raise MemoryGenerationError(CUTOFF_ORDER_INVALID if exc.code == "CUTOFF_ORDER_INVALID" else PLAN_INVALID, exc.code) from None


__all__ = ["ATTEMPT_DISPOSITION", "ATTEMPT_DOMAIN", "ATTEMPT_INVALID", "ATTEMPT_SCHEMA_VERSION", "AttemptRecord", "CHANGES_INCONSISTENT",
           "CHANGES_RECORD_NAME", "CUTOFF_ORDER_INVALID", "GENERATION_AUTHORITY_CLASS", "GENERATION_CODES", "GENERATION_DIGEST_MISMATCH",
           "GENERATION_DOMAIN", "GENERATION_ID_PREFIX", "GENERATION_INCOMPLETE", "GENERATION_INVALID", "GENERATION_RECORD_NAME",
           "GENERATION_SCHEMA_VERSION", "GenerationManifest", "LOCK_OPERATIONS", "LOCK_SCHEMA_VERSION", "MANIFEST_DOMAIN",
           "MANIFEST_INVALID", "MANIFEST_MISMATCH", "MANIFEST_RECORD_NAME", "MANIFEST_SCHEMA_VERSION", "MAX_GENERATION_RECORDS",
           "MAX_PLAN_CUTOFFS", "MAX_RECORD_BYTES", "MEMORY_RULES_VERSION", "ManifestEntry", "MemoryGeneration", "MemoryGenerationError",
           "PLAN_DIGEST_MISMATCH", "PLAN_INVALID", "PUBLICATION_INVALID", "PUBLICATION_SCHEMA_VERSION", "PublicationRecord",
           "RECORD_CORRUPT", "RECORD_DIGEST_MISMATCH", "RECORD_SUFFIX", "ROOT_CLASS", "SAMPLES_INCONSISTENT", "SAMPLE_RECORD_PREFIX",
           "SCHEMA_UNSUPPORTED", "SHORT_ID_COLLISION", "SOURCE_INTEGRITY_CLASS", "STORE_SCHEMA_VERSION",
           "SUPPORTED_ADAPTER_RULES_VERSIONS", "UNAUTHORIZED_ENTRY", "VerifiedGeneration", "attempt_from_outcomes", "build_generation",
           "check_marker", "is_generation_record_name", "lock_bytes", "marker_bytes", "parse_attempt", "parse_manifest",
           "parse_publication", "plan_descriptors", "plan_digest", "record_bytes", "replay_changes", "sample_record_name", "sha256_hex",
           "staleness_of", "validate_plan", "verify_generation_records"]
