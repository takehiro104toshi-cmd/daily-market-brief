"""P8-A2R — J-Quants `/v2/fins/summary` の `DocType` から canonical の会計の意味への**明示の版つき表引き**（A2 を変えない追加）。

- 表の鍵は公式の文書（開示書類種別の一覧。45 値）に**列挙された `DocType` の値そのもの**。写しは完全一致の表引きだけで、
  文字列の分解 ・部分一致 ・接尾辞の判定を意味の authority にしない（監督の決定 d1）。表に無い値は `UNRECOGNIZED` で両方の
  次元が `UNKNOWN`（fail closed）。将来の値が token の形で意味を得ることは無い。
- 会計基準は表の `JP` → `JP_GAAP`、`US` → `US_GAAP`、`IFRS` → `IFRS`、`JMIS` → `JMIS`。`Foreign`（外国株）・`REIT` は会計基準
  ではないので `UNKNOWN`。
- 連結の区分:
  - `NC` の接頭辞の欄（`NCSales` ・`FNCSales` 等）: 公式の欄の定義「_非連結」→ `NON_CONSOLIDATED`（DOCUMENTED）。会計基準は
    行の token が `NC` の欄に当たるかを公式が定めないので `UNKNOWN`。
  - `Consolidated` の行の接頭辞の無い欄: `CONSOLIDATED`（DOCUMENTED）。
  - `NonConsolidated` の行の接頭辞の無い欄: 公式の欄の定義は区分を明記しない。PILOT1 で観測した 4 値
    （`{1Q,2Q,3Q,FY}FinancialStatements_NonConsolidated_JP`）に限り、監督の決定 d2 で `NON_CONSOLIDATED` に写す。根拠は
    OBSERVED_IN_PILOT ＋ SUPERVISOR_APPROVED_MAPPING_RULE の**組**で、DOCUMENTED にしない。観測していない `NonConsolidated`
    の値（IFRS ・Foreign ・OtherPeriod）は `UNKNOWN`。
  - 予想の修正の行（`EarnForecastRevision` 等）: 区分 ・会計基準の token が無い。接頭辞の無い欄は両方 `UNKNOWN`。他の行から
    継承しない（監督の決定 d3）。
  - REIT の行: 財務の指標の対象外。両方 `UNKNOWN`。
- 出力は不変の値（`MappedSemantics`）と、観測の record id を指す注記 ・provenance の record の組。時計 ・乱数 ・IO ・LLM は無い。

記録: `docs/databank/PHASE8_A2R_IMPLEMENTATION.md`。
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, FrozenSet, Mapping, Optional, Tuple

from .identity_model import SourceClass
from .observation_model import StatementBasis
from .observation_semantics_model import (AccountingStandard, DocumentKind, FieldFamily, ObservationSemantics,
                                          SchemaFamily, SemanticEvidence, SemanticMappingProvenance,
                                          SemanticsModelError, is_observation_id, semantic_status_for)

DOCTYPE_MAPPING_VERSION = "p8_jquants_v2_fins_summary_doctype:0.1.0"
#: 公式の文書の参照（token。URL ・path ではない）
DOCTYPE_DOCUMENTATION_REF = "jquants-v2:spec.fin-summary.typeofdocument"
FIELD_DOCUMENTATION_REF = "jquants-v2:spec.fin-summary.data-item"
PILOT_DOCUMENTATION_REF = "p8-pilot1:report.section-8"
SUPERVISOR_RULE_REF = "p8-a2r-impl:decision-d2"

_JP, _US, _IFRS, _JMIS, _NA = (AccountingStandard.JP_GAAP, AccountingStandard.US_GAAP, AccountingStandard.IFRS,
                               AccountingStandard.JMIS, AccountingStandard.UNKNOWN)
_CONS, _NONCONS = StatementBasis.CONSOLIDATED, StatementBasis.NON_CONSOLIDATED
_FS, _REV, _REIT_FS, _REIT_REV = (DocumentKind.FINANCIAL_STATEMENTS, DocumentKind.FORECAST_REVISION,
                                  DocumentKind.REIT_FINANCIAL_STATEMENTS, DocumentKind.REIT_FORECAST_REVISION)
_DOCUMENTED = (SemanticEvidence.DOCUMENTED,)
_PILOT_AND_SUPERVISOR = (SemanticEvidence.OBSERVED_IN_PILOT, SemanticEvidence.SUPERVISOR_APPROVED_MAPPING_RULE)
_NO_EVIDENCE: Tuple[SemanticEvidence, ...] = ()


@dataclass(frozen=True)
class DocumentedType:
    """公式に列挙された 1 つの `DocType` の意味（書類の種類 ・行の会計基準 ・行の連結の区分）。"""

    document_kind: DocumentKind
    accounting_standard: AccountingStandard
    statement_basis: Optional[StatementBasis]


#: 公式の開示書類種別の一覧（2026-09-28 取得。45 値）。鍵は値そのもの。表に無い値は写さない
DOCUMENTED_DOC_TYPES: Mapping[str, DocumentedType] = {
    "FYFinancialStatements_Consolidated_JP": DocumentedType(_FS, _JP, _CONS),
    "FYFinancialStatements_Consolidated_US": DocumentedType(_FS, _US, _CONS),
    "FYFinancialStatements_NonConsolidated_JP": DocumentedType(_FS, _JP, _NONCONS),
    "1QFinancialStatements_Consolidated_JP": DocumentedType(_FS, _JP, _CONS),
    "1QFinancialStatements_Consolidated_US": DocumentedType(_FS, _US, _CONS),
    "1QFinancialStatements_NonConsolidated_JP": DocumentedType(_FS, _JP, _NONCONS),
    "2QFinancialStatements_Consolidated_JP": DocumentedType(_FS, _JP, _CONS),
    "2QFinancialStatements_Consolidated_US": DocumentedType(_FS, _US, _CONS),
    "2QFinancialStatements_NonConsolidated_JP": DocumentedType(_FS, _JP, _NONCONS),
    "3QFinancialStatements_Consolidated_JP": DocumentedType(_FS, _JP, _CONS),
    "3QFinancialStatements_Consolidated_US": DocumentedType(_FS, _US, _CONS),
    "3QFinancialStatements_NonConsolidated_JP": DocumentedType(_FS, _JP, _NONCONS),
    "OtherPeriodFinancialStatements_Consolidated_JP": DocumentedType(_FS, _JP, _CONS),
    "OtherPeriodFinancialStatements_Consolidated_US": DocumentedType(_FS, _US, _CONS),
    "OtherPeriodFinancialStatements_NonConsolidated_JP": DocumentedType(_FS, _JP, _NONCONS),
    "FYFinancialStatements_Consolidated_JMIS": DocumentedType(_FS, _JMIS, _CONS),
    "1QFinancialStatements_Consolidated_JMIS": DocumentedType(_FS, _JMIS, _CONS),
    "2QFinancialStatements_Consolidated_JMIS": DocumentedType(_FS, _JMIS, _CONS),
    "3QFinancialStatements_Consolidated_JMIS": DocumentedType(_FS, _JMIS, _CONS),
    "OtherPeriodFinancialStatements_Consolidated_JMIS": DocumentedType(_FS, _JMIS, _CONS),
    "FYFinancialStatements_NonConsolidated_IFRS": DocumentedType(_FS, _IFRS, _NONCONS),
    "1QFinancialStatements_NonConsolidated_IFRS": DocumentedType(_FS, _IFRS, _NONCONS),
    "2QFinancialStatements_NonConsolidated_IFRS": DocumentedType(_FS, _IFRS, _NONCONS),
    "3QFinancialStatements_NonConsolidated_IFRS": DocumentedType(_FS, _IFRS, _NONCONS),
    "OtherPeriodFinancialStatements_NonConsolidated_IFRS": DocumentedType(_FS, _IFRS, _NONCONS),
    "FYFinancialStatements_Consolidated_IFRS": DocumentedType(_FS, _IFRS, _CONS),
    "1QFinancialStatements_Consolidated_IFRS": DocumentedType(_FS, _IFRS, _CONS),
    "2QFinancialStatements_Consolidated_IFRS": DocumentedType(_FS, _IFRS, _CONS),
    "3QFinancialStatements_Consolidated_IFRS": DocumentedType(_FS, _IFRS, _CONS),
    "OtherPeriodFinancialStatements_Consolidated_IFRS": DocumentedType(_FS, _IFRS, _CONS),
    "FYFinancialStatements_NonConsolidated_Foreign": DocumentedType(_FS, _NA, _NONCONS),
    "1QFinancialStatements_NonConsolidated_Foreign": DocumentedType(_FS, _NA, _NONCONS),
    "2QFinancialStatements_NonConsolidated_Foreign": DocumentedType(_FS, _NA, _NONCONS),
    "3QFinancialStatements_NonConsolidated_Foreign": DocumentedType(_FS, _NA, _NONCONS),
    "OtherPeriodFinancialStatements_NonConsolidated_Foreign": DocumentedType(_FS, _NA, _NONCONS),
    "FYFinancialStatements_Consolidated_Foreign": DocumentedType(_FS, _NA, _CONS),
    "1QFinancialStatements_Consolidated_Foreign": DocumentedType(_FS, _NA, _CONS),
    "2QFinancialStatements_Consolidated_Foreign": DocumentedType(_FS, _NA, _CONS),
    "3QFinancialStatements_Consolidated_Foreign": DocumentedType(_FS, _NA, _CONS),
    "OtherPeriodFinancialStatements_Consolidated_Foreign": DocumentedType(_FS, _NA, _CONS),
    "FYFinancialStatements_Consolidated_REIT": DocumentedType(_REIT_FS, _NA, None),
    "DividendForecastRevision": DocumentedType(_REV, _NA, None),
    "EarnForecastRevision": DocumentedType(_REV, _NA, None),
    "REITDividendForecastRevision": DocumentedType(_REIT_REV, _NA, None),
    "REITEarnForecastRevision": DocumentedType(_REIT_REV, _NA, None),
}
#: 監督の決定 d2 が当たる `NonConsolidated` の値（PILOT1 で接頭辞の無い欄に単体の値を観測した 4 値だけ）
PILOT_OBSERVED_NONCONSOLIDATED_DOC_TYPES: FrozenSet[str] = frozenset({
    "1QFinancialStatements_NonConsolidated_JP", "2QFinancialStatements_NonConsolidated_JP",
    "3QFinancialStatements_NonConsolidated_JP", "FYFinancialStatements_NonConsolidated_JP"})
_NC_FAMILIES = frozenset({FieldFamily.NC_PREFIXED_ACTUAL, FieldFamily.NC_PREFIXED_FORECAST})


@dataclass(frozen=True)
class MappedSemantics:
    """1 つの `DocType` × 欄の family の写しの結果（不変の値。id は無い）。"""

    document_kind: DocumentKind
    accounting_standard: AccountingStandard
    statement_basis: Optional[StatementBasis]
    accounting_standard_evidence: Tuple[SemanticEvidence, ...]
    statement_basis_evidence: Tuple[SemanticEvidence, ...]
    documentation_ref: str


def _unknown(kind: DocumentKind, ref: str = "") -> MappedSemantics:
    return MappedSemantics(kind, _NA, None, _NO_EVIDENCE, _NO_EVIDENCE, ref)


def map_row_semantics(doc_type: Any, field_family: Any) -> MappedSemantics:
    """`DocType` の完全一致の表引き（決定論 ・fail closed）。"""
    if not isinstance(field_family, FieldFamily):
        raise SemanticsModelError("INVALID_VOCABULARY", "field_family")
    if not isinstance(doc_type, str):
        raise SemanticsModelError("INVALID_DOC_TYPE", "doc_type")
    documented = DOCUMENTED_DOC_TYPES.get(doc_type)
    if documented is None:
        return _unknown(DocumentKind.UNRECOGNIZED)
    kind = documented.document_kind
    if kind in (DocumentKind.REIT_FINANCIAL_STATEMENTS, DocumentKind.REIT_FORECAST_REVISION):
        return _unknown(kind, DOCTYPE_DOCUMENTATION_REF)
    if field_family in _NC_FAMILIES:                                       # 「_非連結」の欄。会計基準は行から継承しない
        return MappedSemantics(kind, _NA, _NONCONS, _NO_EVIDENCE, _DOCUMENTED, FIELD_DOCUMENTATION_REF)
    if kind is DocumentKind.FORECAST_REVISION:                             # token が無い。他の行から継承しない
        return _unknown(kind, DOCTYPE_DOCUMENTATION_REF)
    standard = documented.accounting_standard
    standard_evidence = _DOCUMENTED if standard is not _NA else _NO_EVIDENCE
    if documented.statement_basis is _CONS:
        return MappedSemantics(kind, standard, _CONS, standard_evidence, _DOCUMENTED, DOCTYPE_DOCUMENTATION_REF)
    if doc_type in PILOT_OBSERVED_NONCONSOLIDATED_DOC_TYPES:
        return MappedSemantics(kind, standard, _NONCONS, standard_evidence, _PILOT_AND_SUPERVISOR,
                               SUPERVISOR_RULE_REF)
    return MappedSemantics(kind, standard, None, standard_evidence, _NO_EVIDENCE, DOCTYPE_DOCUMENTATION_REF)


def derive_observation_semantics(observation_id: str, doc_type: Any,
                                 field_family: Any) -> Tuple[ObservationSemantics, SemanticMappingProvenance]:
    """A2 の観測の record id に付く注記と provenance の組を作る（record は作るだけ。保存 ・A2 への追記はしない）。"""
    if not is_observation_id(observation_id):
        raise SemanticsModelError("INVALID_ID", "observation_id")
    mapped = map_row_semantics(doc_type, field_family)
    provenance = SemanticMappingProvenance(
        observation_id=observation_id, provider=SourceClass.JQUANTS, schema_family=SchemaFamily.JQUANTS_V2_FINS_SUMMARY,
        doc_type=doc_type, field_family=field_family, document_kind=mapped.document_kind,
        mapping_rule_version=DOCTYPE_MAPPING_VERSION,
        accounting_standard_evidence=mapped.accounting_standard_evidence,
        statement_basis_evidence=mapped.statement_basis_evidence, documentation_ref=mapped.documentation_ref)
    semantics = ObservationSemantics(
        observation_id=observation_id, accounting_standard=mapped.accounting_standard,
        statement_basis=mapped.statement_basis,
        semantic_status=semantic_status_for(mapped.accounting_standard, mapped.statement_basis),
        mapping_rule_version=DOCTYPE_MAPPING_VERSION, mapping_provenance_id=provenance.record_id)
    return semantics, provenance
