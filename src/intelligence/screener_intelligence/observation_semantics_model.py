"""P8-A2R — 財務の観測の会計の意味の純 model（canonical の意味の metadata ・provider の写しの provenance。A2 を変えない追加）。

答える問い: A2 の 1 つの財務の観測（`FundamentalActual` ／ `FundamentalForecast`）について、その値がどの**会計基準**と
どの**連結の区分**の下で報告されたと分かっているか、そしてその判断は何を根拠に（公式の文書 ・PILOT の観測 ・監督の承認した規則）
どの版の写しの規則で決めたか。良い会社か ・比べて良いか ・指標 ・screen ・順位は答えない。

- A2 の観測の slot の identity（主語 ・欄 ・`statement_basis` ・期間）には会計基準の次元が無い（P8-A2R の G1）。本 module は
  A2 の record を変えず、観測の record id を指す**注記**（`ObservationSemantics`）として会計基準と連結の区分の確定の状態を持つ。
- 会計基準の語彙は監督の決定 d1 で閉じる: `JP_GAAP` ・`US_GAAP` ・`IFRS` ・`JMIS` ・`UNKNOWN`。`Foreign` は会計基準ではない。
- 連結の区分は A2 の `StatementBasis` を再利用し、「不明」は `None` で表す（競合する語彙を作らない）。`semantic_status` は
  2 つの次元の確定の状態から決定論で決まり、直列化の往復で食い違えば拒む。
- provider の写しの provenance（`SemanticMappingProvenance`）は、provider ・schema の family ・元の `DocType` の文字列 ・欄の
  family ・写しの規則の版 ・次元ごとの根拠の class（DOCUMENTED ／ OBSERVED_IN_PILOT ／ SUPERVISOR_APPROVED_MAPPING_RULE の組）を
  持つ。組は潰さず明示する。raw の応答 ・credential ・本文 ・path は持たない。
- id は内容 address（時計 ・乱数 ・path に依らない）。float は無い。
- 注記は authority の観測ではない（`SEMANTIC_METADATA_RECORD`）。A2 の store には入らない。

記録: `docs/databank/PHASE8_A2R_IMPLEMENTATION.md`。
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum
from typing import Any, Dict, Iterable, Mapping, Optional, Tuple

from .identity_model import CREDENTIAL_MARKERS, SourceClass, canonical_json
from .observation_model import StatementBasis
from ..core.ids import content_id

SEMANTICS_SCHEMA_VERSION = "p8_observation_semantics:0.1.0"
SEMANTICS_RECORD_KIND = "OBSERVATION_SEMANTICS"
MAPPING_PROVENANCE_RECORD_KIND = "SEMANTIC_MAPPING_PROVENANCE"
SEMANTICS_ID_PREFIX = "p8sem"
MAPPING_PROVENANCE_ID_PREFIX = "p8map"
#: 注記の authority の種類（A2 の観測の authority ではない ・A2 の store に入らない）
SEMANTIC_METADATA_RECORD = "SEMANTIC_METADATA_RECORD"
MAX_DOC_TYPE_LENGTH = 64
_OBSERVATION_ID_RE = re.compile(r"^p8obs_[0-9a-f]{24}$")
_MAPPING_PROVENANCE_ID_RE = re.compile(rf"^{MAPPING_PROVENANCE_ID_PREFIX}_[0-9a-f]{{24}}$")
#: 写しの規則の版（名前:semver）
_RULE_VERSION_RE = re.compile(r"^[a-z][a-z0-9_]{0,63}:[0-9]+\.[0-9]+\.[0-9]+$")
#: 文書の参照（A1 の証拠の参照と同じ形: `/` ・`\\` ・空白なし ＝ path ・URL ・本文を持てない）
_DOCUMENTATION_REF_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:#-]{0,159}$")
#: provider の `DocType` の値そのまま（空は「行に無い」）。制御文字 ・空白 ・path を持てない
_DOC_TYPE_RE = re.compile(rf"^[A-Za-z0-9_-]{{0,{MAX_DOC_TYPE_LENGTH}}}$")


class SemanticsModelError(ValueError):
    """意味の record の構造 ・語彙 ・値の違反（fail closed）。detail は field 名だけ。"""

    def __init__(self, code: str, detail: str = "") -> None:
        super().__init__(f"{code}: {detail}" if detail else code)
        self.code = code
        self.detail = detail


def _require(condition: bool, code: str, detail: str = "") -> None:
    if not condition:
        raise SemanticsModelError(code, detail)


# ---------------------------------------------------------------- 語彙（閉じた集合）


class AccountingStandard(str, Enum):
    """会計基準（監督の決定 d1）。`Foreign` ・`REIT` は会計基準ではないので member にしない。"""

    JP_GAAP = "JP_GAAP"
    US_GAAP = "US_GAAP"
    IFRS = "IFRS"
    JMIS = "JMIS"
    UNKNOWN = "UNKNOWN"


class SemanticState(str, Enum):
    KNOWN = "KNOWN"
    UNKNOWN = "UNKNOWN"


class SemanticStatus(str, Enum):
    """2 つの次元の確定の状態の組（決定論で決まる）。"""

    KNOWN = "KNOWN"
    ACCOUNTING_STANDARD_UNKNOWN = "ACCOUNTING_STANDARD_UNKNOWN"
    STATEMENT_BASIS_UNKNOWN = "STATEMENT_BASIS_UNKNOWN"
    ACCOUNTING_STANDARD_AND_STATEMENT_BASIS_UNKNOWN = "ACCOUNTING_STANDARD_AND_STATEMENT_BASIS_UNKNOWN"


class SemanticEvidence(str, Enum):
    """次元の値を支える根拠の class。組は tuple で明示し、DOCUMENTED に潰さない。"""

    DOCUMENTED = "DOCUMENTED"
    OBSERVED_IN_PILOT = "OBSERVED_IN_PILOT"
    SUPERVISOR_APPROVED_MAPPING_RULE = "SUPERVISOR_APPROVED_MAPPING_RULE"


class SchemaFamily(str, Enum):
    JQUANTS_V2_FINS_SUMMARY = "JQUANTS_V2_FINS_SUMMARY"


class FieldFamily(str, Enum):
    """provider の行の中の欄の family（接頭辞 `NC` の有無 × 実績 ／ 予想）。欄の配置は canonical の意味ではない。"""

    UNPREFIXED_ACTUAL = "UNPREFIXED_ACTUAL"
    NC_PREFIXED_ACTUAL = "NC_PREFIXED_ACTUAL"
    UNPREFIXED_FORECAST = "UNPREFIXED_FORECAST"
    NC_PREFIXED_FORECAST = "NC_PREFIXED_FORECAST"


class DocumentKind(str, Enum):
    FINANCIAL_STATEMENTS = "FINANCIAL_STATEMENTS"
    FORECAST_REVISION = "FORECAST_REVISION"
    REIT_FINANCIAL_STATEMENTS = "REIT_FINANCIAL_STATEMENTS"
    REIT_FORECAST_REVISION = "REIT_FORECAST_REVISION"
    UNRECOGNIZED = "UNRECOGNIZED"


_EVIDENCE_ORDER: Mapping[SemanticEvidence, int] = {member: index for index, member in enumerate(SemanticEvidence)}


# ---------------------------------------------------------------- 値の検査


def _enum(value: Any, enum_type, field_name: str):
    _require(isinstance(value, enum_type), "INVALID_VOCABULARY", field_name)
    return value


def _parse_enum(value: Any, enum_type, field_name: str):
    try:
        return enum_type(value)
    except (ValueError, TypeError):
        raise SemanticsModelError("INVALID_VOCABULARY", field_name) from None


def _text(value: Any, pattern, code: str, field_name: str) -> str:
    _require(isinstance(value, str) and bool(pattern.match(value)), code, field_name)
    lowered = value.lower()
    _require(not any(marker in lowered for marker in CREDENTIAL_MARKERS), "CREDENTIAL_LIKE_TEXT", field_name)
    return value


def _evidence(value: Any, field_name: str) -> Tuple[SemanticEvidence, ...]:
    """根拠の組: tuple ・重複なし ・語彙の順（正準。集合として同じなら同じ id）。"""
    _require(isinstance(value, tuple), "INVALID_EVIDENCE", field_name)
    for item in value:
        _enum(item, SemanticEvidence, field_name)
    _require(len(set(value)) == len(value), "INVALID_EVIDENCE", field_name)
    _require(tuple(sorted(value, key=_EVIDENCE_ORDER.__getitem__)) == value, "INVALID_EVIDENCE", field_name)
    return value


def _parse_evidence(value: Any, field_name: str) -> Tuple[SemanticEvidence, ...]:
    _require(isinstance(value, list), "INVALID_EVIDENCE", field_name)
    return _evidence(tuple(_parse_enum(item, SemanticEvidence, field_name) for item in value), field_name)


def _reject_unknown(data: Mapping[str, Any], allowed: Iterable[str], name: str) -> None:
    _require(isinstance(data, Mapping), "INVALID_RECORD", name)
    _require(set(data) <= set(allowed), "UNKNOWN_FIELD", name)
    _require(set(allowed) <= set(data), "MISSING_FIELD", name)


def semantic_status_for(accounting_standard: AccountingStandard,
                        statement_basis: Optional[StatementBasis]) -> SemanticStatus:
    """2 つの次元から状態を決める（決定論）。"""
    standard_unknown = accounting_standard is AccountingStandard.UNKNOWN
    basis_unknown = statement_basis is None
    if standard_unknown and basis_unknown:
        return SemanticStatus.ACCOUNTING_STANDARD_AND_STATEMENT_BASIS_UNKNOWN
    if standard_unknown:
        return SemanticStatus.ACCOUNTING_STANDARD_UNKNOWN
    if basis_unknown:
        return SemanticStatus.STATEMENT_BASIS_UNKNOWN
    return SemanticStatus.KNOWN


def is_observation_id(value: Any) -> bool:
    return isinstance(value, str) and bool(_OBSERVATION_ID_RE.match(value))


# ---------------------------------------------------------------- record


class _SemanticRecord:
    """record の共通部（不変 ・内容 address ・authority の観測ではない）。"""

    KIND: str
    ID_PREFIX: str
    AUTHORITY_CLASS = SEMANTIC_METADATA_RECORD

    def _payload(self) -> Dict[str, Any]:
        raise NotImplementedError

    def identity_payload(self) -> Dict[str, Any]:
        return {"schema_version": SEMANTICS_SCHEMA_VERSION, "record_kind": self.KIND, "payload": self._payload()}

    @property
    def record_id(self) -> str:
        return content_id(self.ID_PREFIX, canonical_json(self.identity_payload()))

    def as_dict(self) -> Dict[str, Any]:
        return {**self.identity_payload(), "record_id": self.record_id}

    def canonical_line(self) -> str:
        return canonical_json(self.as_dict()) + "\n"


@dataclass(frozen=True, kw_only=True)
class SemanticMappingProvenance(_SemanticRecord):
    """provider の写しの provenance（監査に足る最小: provider ・schema ・元の DocType ・欄の family ・規則の版 ・根拠の class）。"""

    KIND = MAPPING_PROVENANCE_RECORD_KIND
    ID_PREFIX = MAPPING_PROVENANCE_ID_PREFIX
    observation_id: str
    provider: SourceClass
    schema_family: SchemaFamily
    doc_type: str
    field_family: FieldFamily
    document_kind: DocumentKind
    mapping_rule_version: str
    accounting_standard_evidence: Tuple[SemanticEvidence, ...]
    statement_basis_evidence: Tuple[SemanticEvidence, ...]
    documentation_ref: str = ""

    def __post_init__(self) -> None:
        _require(is_observation_id(self.observation_id), "INVALID_ID", "observation_id")
        _enum(self.provider, SourceClass, "provider")
        _enum(self.schema_family, SchemaFamily, "schema_family")
        _text(self.doc_type, _DOC_TYPE_RE, "INVALID_DOC_TYPE", "doc_type")
        _enum(self.field_family, FieldFamily, "field_family")
        _enum(self.document_kind, DocumentKind, "document_kind")
        _text(self.mapping_rule_version, _RULE_VERSION_RE, "INVALID_RULE_VERSION", "mapping_rule_version")
        _evidence(self.accounting_standard_evidence, "accounting_standard_evidence")
        _evidence(self.statement_basis_evidence, "statement_basis_evidence")
        if self.documentation_ref != "":
            _text(self.documentation_ref, _DOCUMENTATION_REF_RE, "INVALID_DOCUMENTATION_REF", "documentation_ref")

    def _payload(self) -> Dict[str, Any]:
        return {"accounting_standard_evidence": [item.value for item in self.accounting_standard_evidence],
                "doc_type": self.doc_type, "document_kind": self.document_kind.value,
                "documentation_ref": self.documentation_ref, "field_family": self.field_family.value,
                "mapping_rule_version": self.mapping_rule_version, "observation_id": self.observation_id,
                "provider": self.provider.value, "schema_family": self.schema_family.value,
                "statement_basis_evidence": [item.value for item in self.statement_basis_evidence]}

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "SemanticMappingProvenance":
        _reject_unknown(data, ("schema_version", "record_kind", "payload", "record_id"), "record")
        _require(data["schema_version"] == SEMANTICS_SCHEMA_VERSION, "SCHEMA_MISMATCH", "schema_version")
        _require(data["record_kind"] == cls.KIND, "KIND_MISMATCH", "record_kind")
        payload = data["payload"]
        _reject_unknown(payload, ("accounting_standard_evidence", "doc_type", "document_kind", "documentation_ref",
                                  "field_family", "mapping_rule_version", "observation_id", "provider",
                                  "schema_family", "statement_basis_evidence"), "payload")
        record = cls(observation_id=payload["observation_id"],
                     provider=_parse_enum(payload["provider"], SourceClass, "provider"),
                     schema_family=_parse_enum(payload["schema_family"], SchemaFamily, "schema_family"),
                     doc_type=payload["doc_type"],
                     field_family=_parse_enum(payload["field_family"], FieldFamily, "field_family"),
                     document_kind=_parse_enum(payload["document_kind"], DocumentKind, "document_kind"),
                     mapping_rule_version=payload["mapping_rule_version"],
                     accounting_standard_evidence=_parse_evidence(payload["accounting_standard_evidence"],
                                                                  "accounting_standard_evidence"),
                     statement_basis_evidence=_parse_evidence(payload["statement_basis_evidence"],
                                                              "statement_basis_evidence"),
                     documentation_ref=payload["documentation_ref"])
        _require(record.record_id == data["record_id"], "ID_MISMATCH", "record_id")
        return record


@dataclass(frozen=True, kw_only=True)
class ObservationSemantics(_SemanticRecord):
    """A2 の 1 つの財務の観測に付く canonical の意味の注記（会計基準 ・連結の区分 ・確定の状態 ・規則の版 ・provenance の参照）。"""

    KIND = SEMANTICS_RECORD_KIND
    ID_PREFIX = SEMANTICS_ID_PREFIX
    observation_id: str
    accounting_standard: AccountingStandard
    statement_basis: Optional[StatementBasis]
    semantic_status: SemanticStatus
    mapping_rule_version: str
    mapping_provenance_id: str

    def __post_init__(self) -> None:
        _require(is_observation_id(self.observation_id), "INVALID_ID", "observation_id")
        _enum(self.accounting_standard, AccountingStandard, "accounting_standard")
        if self.statement_basis is not None:
            _enum(self.statement_basis, StatementBasis, "statement_basis")
        _enum(self.semantic_status, SemanticStatus, "semantic_status")
        _require(self.semantic_status is semantic_status_for(self.accounting_standard, self.statement_basis),
                 "STATUS_MISMATCH", "semantic_status")
        _text(self.mapping_rule_version, _RULE_VERSION_RE, "INVALID_RULE_VERSION", "mapping_rule_version")
        _require(isinstance(self.mapping_provenance_id, str)
                 and bool(_MAPPING_PROVENANCE_ID_RE.match(self.mapping_provenance_id)), "INVALID_ID",
                 "mapping_provenance_id")

    @property
    def accounting_standard_state(self) -> SemanticState:
        return SemanticState.UNKNOWN if self.accounting_standard is AccountingStandard.UNKNOWN \
            else SemanticState.KNOWN

    @property
    def statement_basis_state(self) -> SemanticState:
        return SemanticState.UNKNOWN if self.statement_basis is None else SemanticState.KNOWN

    def _payload(self) -> Dict[str, Any]:
        return {"accounting_standard": self.accounting_standard.value,
                "mapping_provenance_id": self.mapping_provenance_id,
                "mapping_rule_version": self.mapping_rule_version, "observation_id": self.observation_id,
                "semantic_status": self.semantic_status.value,
                "statement_basis": None if self.statement_basis is None else self.statement_basis.value}

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "ObservationSemantics":
        _reject_unknown(data, ("schema_version", "record_kind", "payload", "record_id"), "record")
        _require(data["schema_version"] == SEMANTICS_SCHEMA_VERSION, "SCHEMA_MISMATCH", "schema_version")
        _require(data["record_kind"] == cls.KIND, "KIND_MISMATCH", "record_kind")
        payload = data["payload"]
        _reject_unknown(payload, ("accounting_standard", "mapping_provenance_id", "mapping_rule_version",
                                  "observation_id", "semantic_status", "statement_basis"), "payload")
        basis = payload["statement_basis"]
        record = cls(observation_id=payload["observation_id"],
                     accounting_standard=_parse_enum(payload["accounting_standard"], AccountingStandard,
                                                     "accounting_standard"),
                     statement_basis=None if basis is None else _parse_enum(basis, StatementBasis,
                                                                            "statement_basis"),
                     semantic_status=_parse_enum(payload["semantic_status"], SemanticStatus, "semantic_status"),
                     mapping_rule_version=payload["mapping_rule_version"],
                     mapping_provenance_id=payload["mapping_provenance_id"])
        _require(record.record_id == data["record_id"], "ID_MISMATCH", "record_id")
        return record
