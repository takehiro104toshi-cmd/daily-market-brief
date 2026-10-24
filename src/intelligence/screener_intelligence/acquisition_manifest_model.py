"""P8-EPOCH1 — 取得 manifest（`AcquisitionManifest`）の純 model: 1 つの COMPLETE な bounded provider 取得が、どの canonical ／ 保留の
意味の結果に写ったかの**明示の membership authority**（監督の決定 E3）。

- 何のために: 「provider の取得 epoch E に、A2 の canonical 観測 O は含まれていたか」を、**journal の物理的な位置 ・現在の store の状態 ・
  時刻の推定 ・時計 ・raw の payload に依らず**、決定論で replay できる形で答える（後の retrospective な解決の authority）。
  journal の位置は意味の authority ではない（監督の決定 E7。永久に不採用）。
- 何ではないか: raw の provider snapshot ではない。取得の authority（ACQ0）でも canonical 観測の authority（A2）でも coverage でもない。
  値 ・会社名 ・raw の行 ・header ・credential を持たない（metadata だけ。provider の code は private root の既存の方針の中）。
- entry: handed off された provider の行 1 つ ＝ entry 1 つ。順は凍結 ACQ0 の handoff の順（取得の内容の digest に結ばれる）。
  disposition は `CANONICAL` ／ `HELD_SEMANTIC` ／ `NOT_REPORTED_ONLY` ／ `UNSUPPORTED`（監督の決定 E2）。
- 知識の metadata（監督の決定 K2）: entry は知識を持たない。知識は参照する A2 の観測が持つ（EXE-R の後は同じ行の canonical 観測でも
  知識が違い得るので、entry 1 つの「知識」は誤解を招く）。期間 ・区分は CANONICAL の行は参照する観測から決定論で確かめて必ず持つ。
- 期間 ・区分の metadata（P8-EPOCH1R。監督の決定 D-E1R-1）: HELD_SEMANTIC ／ UNSUPPORTED ／ NOT_REPORTED_ONLY の entry も、凍結 ADP0 が
  決定論で確定した期間（`derive_reporting_period`）・区分（保留 record の `attempted_statement_basis` ／ 適格の材料）を持てる。確定
  できなければ `None`（番兵の日付 ・取得日 ・開示日 ・推定の年度末で埋めない）。将来の F1 は HELD_SEMANTIC ／ UNSUPPORTED の期間を
  「その period_end の不在の authority を withhold する」印に、`None` を「取得全体の不在の authority を withhold する」印に使う。
  NOT_REPORTED_ONLY は不在の authority を汚さない（行は在り ・値は記載なし ＝ 将来の VALUE_ABSENT）。
- identity は内容 address（`p8man_`）。参照は `jq.man:<24 hex>`。同じ内容 → 同じ id ・参照。

記録: `docs/databank/PHASE8_EPOCH1_ACQUISITION_MANIFEST.md`。
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum
from typing import Any, Dict, Iterable, Mapping, Optional, Tuple

from .identity_model import CREDENTIAL_MARKERS, canonical_json, is_issuer_id
from .observation_model import FundamentalField, ReportingPeriod, StatementBasis
from ..core.ids import content_id

MANIFEST_SCHEMA_VERSION = "p8_acquisition_manifest:0.2.0"                   # EPOCH1R: 非 canonical の entry も期間 ・区分を持てる
MANIFEST_RULES_VERSION = "p8_acquisition_manifest_authority:0.2.0"
MANIFEST_RECORD_KIND = "ACQUISITION_MANIFEST"
MANIFEST_ID_PREFIX = "p8man"
REFERENCE_PREFIX = "jq.man:"
#: 派生の membership authority（raw snapshot ・取得 ・観測 ・coverage の authority ではない）
MEMBERSHIP_AUTHORITY_RECORD = "ACQUISITION_MEMBERSHIP_RECORD"
#: entry の順: 凍結 ACQ0 の handoff の順（取得の内容の digest と同じ順）
ENTRY_ORDER_RULE = "ACQ0_HANDOFF_ORDER_AS_RECEIVED"
_ACQ_REF_RE = re.compile(r"^jq\.acq:[0-9a-f]{24}$")
_MAN_REF_RE = re.compile(r"^jq\.man:[0-9a-f]{24}$")
_DIGEST_RE = re.compile(r"^[0-9a-f]{64}$")
_PROVIDER_REF_RE = re.compile(r"^jq\.fins_summary:[A-Za-z0-9_-]{1,64}\.[A-Za-z0-9_-]{1,64}\.[A-Za-z0-9_-]{1,64}"
                              r":[0-9a-f]{24}$")
_OBSERVATION_ID_RE = re.compile(r"^p8obs_[0-9a-f]{24}$")
_HELD_ID_RE = re.compile(r"^p8hld_[0-9a-f]{24}$")
_CODE_RE = re.compile(r"^[0-9A-Z]{5}$")
_RULE_VERSION_RE = re.compile(r"^[a-z][a-z0-9_]{0,63}:[0-9]+\.[0-9]+\.[0-9]+$")
_MAX_ENTRIES = 100_000


class ManifestModelError(ValueError):
    """record の構造 ・語彙 ・値の違反（fail closed）。detail は field 名だけ。"""

    def __init__(self, code: str, detail: str = "") -> None:
        super().__init__(f"{code}: {detail}" if detail else code)
        self.code = code
        self.detail = detail


def _require(condition: bool, code: str, detail: str = "") -> None:
    if not condition:
        raise ManifestModelError(code, detail)


def _text(value: Any, pattern: "re.Pattern[str]", code: str, field_name: str) -> str:
    _require(isinstance(value, str) and bool(pattern.match(value)), code, field_name)
    lowered = value.lower()
    _require(not any(marker in lowered for marker in CREDENTIAL_MARKERS), "CREDENTIAL_LIKE_TEXT", field_name)
    return value


def _reject_unknown(data: Mapping[str, Any], allowed: Iterable[str], name: str) -> None:
    _require(isinstance(data, Mapping), "INVALID_RECORD", name)
    _require(set(data) <= set(allowed), "UNKNOWN_FIELD", name)
    _require(set(allowed) <= set(data), "MISSING_FIELD", name)


class ManifestDisposition(str, Enum):
    """provider の行 1 つの意味の結果（監督の決定 E2）。"""

    CANONICAL = "CANONICAL"                      # canonical 観測が 1 つ以上 A2 に入った（記載なしの欄は無い）
    HELD_SEMANTIC = "HELD_SEMANTIC"              # 行は在ったが意味の理由で保留（基準 ・区分 ・通貨 ・鎖の不連続 …）
    NOT_REPORTED_ONLY = "NOT_REPORTED_ONLY"      # 支える 4 欄がすべて記載なし（凍結 EXE の NO_REPORTED_FIELDS）
    UNSUPPORTED = "UNSUPPORTED"                  # 行は在ったが構造の理由で保留（書類種別 ・期間 ・値 ・時刻の形 …）


class ManifestExecution(str, Enum):
    """凍結 EXE の結果の membership に関わる面だけ。APPENDED（書いた）と REUSED（収束した）は同じ membership なので区別しない
    （同じ取得の replay が同じ manifest に収束するため。書いた ／ 収束したは実行の事実で、membership ではない）。"""

    MATERIALIZED = "MATERIALIZED"                # EXE APPENDED ／ REUSED: canonical 観測が A2 に在る
    HELD = "HELD"                                # EXE HELD: 保留 store にだけ在る
    NO_REPORTED_FIELDS = "NO_REPORTED_FIELDS"    # EXE NO_REPORTED_FIELDS: 書くものが無かった


_EXECUTION_FOR = {ManifestDisposition.CANONICAL: ManifestExecution.MATERIALIZED,
                  ManifestDisposition.HELD_SEMANTIC: ManifestExecution.HELD,
                  ManifestDisposition.UNSUPPORTED: ManifestExecution.HELD,
                  ManifestDisposition.NOT_REPORTED_ONLY: ManifestExecution.NO_REPORTED_FIELDS}


# ---------------------------------------------------------------- entry


@dataclass(frozen=True, kw_only=True)
class ManifestEntry:
    """handed off された provider の行 1 つの membership。値 ・名前は持たない。知識は持たない（K2）。"""

    provider_record_ref: str
    provider_record_digest: str
    disposition: ManifestDisposition
    execution_outcome: ManifestExecution
    fields: Tuple[Tuple[FundamentalField, str], ...] = ()
    held_record_id: str = ""
    period: Optional[ReportingPeriod] = None
    statement_basis: Optional[StatementBasis] = None

    def __post_init__(self) -> None:
        _text(self.provider_record_ref, _PROVIDER_REF_RE, "INVALID_PROVIDER_REF", "provider_record_ref")
        _require(isinstance(self.provider_record_digest, str) and bool(_DIGEST_RE.match(self.provider_record_digest)),
                 "INVALID_DIGEST", "provider_record_digest")
        _require(self.provider_record_ref.endswith(":" + self.provider_record_digest[:24]), "DIGEST_REF_MISMATCH",
                 "provider_record_digest")
        _require(isinstance(self.disposition, ManifestDisposition), "INVALID_VOCABULARY", "disposition")
        _require(isinstance(self.execution_outcome, ManifestExecution), "INVALID_VOCABULARY", "execution_outcome")
        _require(_EXECUTION_FOR[self.disposition] is self.execution_outcome, "EXECUTION_DISPOSITION_MISMATCH",
                 "execution_outcome")
        _require(isinstance(self.fields, tuple) and all(isinstance(f, tuple) and len(f) == 2 for f in self.fields),
                 "INVALID_FIELDS", "fields")
        names = [field for field, _ in self.fields]
        for field, observation_id in self.fields:
            _require(isinstance(field, FundamentalField), "INVALID_VOCABULARY", "fields")
            _text(observation_id, _OBSERVATION_ID_RE, "INVALID_OBSERVATION_ID", "fields")
        _require(len(set(names)) == len(names), "DUPLICATE_FIELD", "fields")
        _require([f.value for f in names] == sorted(f.value for f in names), "FIELDS_NOT_CANONICAL", "fields")
        _require(isinstance(self.held_record_id, str) and (self.held_record_id == ""
                 or bool(_HELD_ID_RE.match(self.held_record_id))), "INVALID_HELD_ID", "held_record_id")
        if self.period is not None:
            _require(isinstance(self.period, ReportingPeriod), "INVALID_PERIOD", "period")
        if self.statement_basis is not None:
            _require(isinstance(self.statement_basis, StatementBasis), "INVALID_VOCABULARY", "statement_basis")
        if self.disposition is ManifestDisposition.CANONICAL:                  # 不変条件（監督の指示 §6）
            _require(len(self.fields) >= 1, "CANONICAL_REQUIRES_OBSERVATION", "fields")
            _require(self.held_record_id == "", "CANONICAL_HAS_HELD", "held_record_id")
            _require(self.period is not None and self.statement_basis is not None, "CANONICAL_REQUIRES_PERIOD",
                     "period")
        else:
            _require(self.fields == (), "NON_CANONICAL_HAS_OBSERVATION", "fields")
            if self.disposition is ManifestDisposition.NOT_REPORTED_ONLY:
                _require(self.held_record_id == "", "NOT_REPORTED_HAS_HELD", "held_record_id")
            else:
                _require(self.held_record_id != "", "HELD_REQUIRES_HELD_ID", "held_record_id")

    @property
    def observation_ids(self) -> Tuple[str, ...]:
        return tuple(observation_id for _, observation_id in self.fields)

    @property
    def period_known(self) -> bool:
        """期間が凍結 ADP0 の規則で決定論に確定しているか（CANONICAL は常に True）。"""
        return self.period is not None

    @property
    def contaminates_absence(self) -> bool:
        """将来の F1 の不在の authority を汚す entry か（保留 ・構造の保留だけ。記載なしは汚さない）。"""
        return self.disposition in (ManifestDisposition.HELD_SEMANTIC, ManifestDisposition.UNSUPPORTED)

    def as_dict(self) -> Dict[str, Any]:
        return {"disposition": self.disposition.value, "execution_outcome": self.execution_outcome.value,
                "fields": {field.value: observation_id for field, observation_id in self.fields},
                "held_record_id": self.held_record_id,
                "period": self.period.as_dict() if self.period is not None else None,
                "provider_record_digest": self.provider_record_digest, "provider_record_ref": self.provider_record_ref,
                "statement_basis": self.statement_basis.value if self.statement_basis is not None else None}

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "ManifestEntry":
        _reject_unknown(data, ("disposition", "execution_outcome", "fields", "held_record_id", "period",
                               "provider_record_digest", "provider_record_ref", "statement_basis"), "entry")
        _require(isinstance(data["fields"], Mapping), "INVALID_FIELDS", "fields")
        try:
            disposition = ManifestDisposition(data["disposition"])
            execution = ManifestExecution(data["execution_outcome"])
            fields = tuple(sorted(((FundamentalField(name), observation_id)
                                   for name, observation_id in data["fields"].items()), key=lambda f: f[0].value))
            basis = StatementBasis(data["statement_basis"]) if data["statement_basis"] is not None else None
        except ValueError:
            raise ManifestModelError("INVALID_VOCABULARY", "entry") from None
        period = ReportingPeriod.from_dict(data["period"]) if data["period"] is not None else None
        return cls(provider_record_ref=data["provider_record_ref"],
                   provider_record_digest=data["provider_record_digest"],
                   disposition=disposition, execution_outcome=execution, fields=fields,
                   held_record_id=data["held_record_id"], period=period, statement_basis=basis)


# ---------------------------------------------------------------- manifest


@dataclass(frozen=True, kw_only=True)
class AcquisitionManifest:
    """1 つの COMPLETE な取得の membership（不変 ・内容 address）。entry の順 ・集合が digest に入る。"""

    KIND = MANIFEST_RECORD_KIND
    AUTHORITY_CLASS = MEMBERSHIP_AUTHORITY_RECORD
    acquisition_ref: str
    acquisition_content_digest: str
    subject_id: str
    provider_code: str
    executor_rules_version: str
    mapping_rule_version: str
    entries: Tuple[ManifestEntry, ...]
    manifest_rules_version: str = MANIFEST_RULES_VERSION

    def __post_init__(self) -> None:
        _text(self.acquisition_ref, _ACQ_REF_RE, "INVALID_ACQUISITION_REF", "acquisition_ref")
        _require(isinstance(self.acquisition_content_digest, str)
                 and bool(_DIGEST_RE.match(self.acquisition_content_digest)), "INVALID_DIGEST",
                 "acquisition_content_digest")
        _require(is_issuer_id(self.subject_id), "INVALID_SUBJECT", "subject_id")
        _text(self.provider_code, _CODE_RE, "INVALID_CODE", "provider_code")
        for name in ("executor_rules_version", "mapping_rule_version", "manifest_rules_version"):
            _text(self.__dict__[name], _RULE_VERSION_RE, "INVALID_RULE_VERSION", name)
        _require(isinstance(self.entries, tuple) and all(isinstance(e, ManifestEntry) for e in self.entries),
                 "INVALID_ENTRIES", "entries")
        _require(len(self.entries) <= _MAX_ENTRIES, "TOO_MANY_ENTRIES", "entries")
        refs = [entry.provider_record_ref for entry in self.entries]
        _require(len(set(refs)) == len(refs), "DUPLICATE_PROVIDER_ROW", "entries")
        natural: Dict[str, str] = {}
        for entry in self.entries:                                               # 同じ自然 key ・違う digest は 1 取得に無い
            head = entry.provider_record_ref.rpartition(":")[0]
            _require(natural.setdefault(head, entry.provider_record_digest) == entry.provider_record_digest,
                     "PROVIDER_ROWS_INCONSISTENT", "entries")
        observation_ids = [observation_id for entry in self.entries for observation_id in entry.observation_ids]
        _require(len(set(observation_ids)) == len(observation_ids), "DUPLICATE_OBSERVATION", "entries")
        for entry in self.entries:
            _require(entry.provider_record_ref.split(":")[1].split(".")[0] == self.provider_code,
                     "ENTRY_CODE_MISMATCH", "entries")

    @property
    def entry_count(self) -> int:
        return len(self.entries)

    @property
    def canonical_observation_count(self) -> int:
        return sum(len(entry.fields) for entry in self.entries)

    @property
    def observation_ids(self) -> Tuple[str, ...]:
        return tuple(observation_id for entry in self.entries for observation_id in entry.observation_ids)

    def identity_payload(self) -> Dict[str, Any]:
        return {"acquisition_content_digest": self.acquisition_content_digest, "acquisition_ref": self.acquisition_ref,
                "canonical_observation_count": self.canonical_observation_count,
                "entries": [entry.as_dict() for entry in self.entries], "entry_count": self.entry_count,
                "entry_order": ENTRY_ORDER_RULE, "executor_rules_version": self.executor_rules_version,
                "manifest_rules_version": self.manifest_rules_version,
                "mapping_rule_version": self.mapping_rule_version,
                "provider_code": self.provider_code, "record_kind": MANIFEST_RECORD_KIND,
                "schema_version": MANIFEST_SCHEMA_VERSION, "subject_id": self.subject_id}

    @property
    def record_id(self) -> str:
        return content_id(MANIFEST_ID_PREFIX, canonical_json(self.identity_payload()))

    @property
    def reference(self) -> str:
        return manifest_reference(self.record_id)

    def as_dict(self) -> Dict[str, Any]:
        return {**self.identity_payload(), "record_id": self.record_id}

    def canonical_line(self) -> str:
        return canonical_json(self.as_dict()) + "\n"

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "AcquisitionManifest":
        _reject_unknown(data, ("acquisition_content_digest", "acquisition_ref", "canonical_observation_count",
                               "entries", "entry_count", "entry_order", "executor_rules_version",
                               "manifest_rules_version", "mapping_rule_version", "provider_code", "record_id",
                               "record_kind", "schema_version", "subject_id"), "record")
        _require(data["schema_version"] == MANIFEST_SCHEMA_VERSION, "SCHEMA_MISMATCH", "schema_version")
        _require(data["record_kind"] == MANIFEST_RECORD_KIND, "KIND_MISMATCH", "record_kind")
        _require(data["entry_order"] == ENTRY_ORDER_RULE, "ENTRY_ORDER_MISMATCH", "entry_order")
        _require(isinstance(data["entries"], list), "INVALID_ENTRIES", "entries")
        record = cls(acquisition_ref=data["acquisition_ref"],
                     acquisition_content_digest=data["acquisition_content_digest"],
                     subject_id=data["subject_id"], provider_code=data["provider_code"],
                     executor_rules_version=data["executor_rules_version"],
                     mapping_rule_version=data["mapping_rule_version"],
                     entries=tuple(ManifestEntry.from_dict(entry) for entry in data["entries"]),
                     manifest_rules_version=data["manifest_rules_version"])
        _require(record.entry_count == data["entry_count"], "COUNT_MISMATCH", "entry_count")
        _require(record.canonical_observation_count == data["canonical_observation_count"], "COUNT_MISMATCH",
                 "canonical_observation_count")
        _require(record.record_id == data["record_id"], "RECORD_ID_MISMATCH", "record_id")
        return record


def manifest_reference(record_id: Any) -> str:
    _require(isinstance(record_id, str) and record_id.startswith(MANIFEST_ID_PREFIX + "_")
             and len(record_id) == len(MANIFEST_ID_PREFIX) + 25, "INVALID_RECORD_ID", "record_id")
    return REFERENCE_PREFIX + record_id[len(MANIFEST_ID_PREFIX) + 1:]


def is_manifest_reference(value: Any) -> bool:
    return isinstance(value, str) and bool(_MAN_REF_RE.match(value))


def is_acquisition_manifest(value: Any) -> bool:
    return isinstance(value, AcquisitionManifest)


__all__ = ["ENTRY_ORDER_RULE", "MANIFEST_ID_PREFIX", "MANIFEST_RECORD_KIND", "MANIFEST_RULES_VERSION",
           "MANIFEST_SCHEMA_VERSION", "MEMBERSHIP_AUTHORITY_RECORD", "REFERENCE_PREFIX", "AcquisitionManifest",
           "ManifestDisposition", "ManifestEntry", "ManifestExecution", "ManifestModelError", "is_acquisition_manifest",
           "is_manifest_reference", "manifest_reference"]
