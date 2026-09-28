"""P8-A2R-IMPL — 会計の意味の safety layer の test matrix A〜N（境界 ／ 凍結は `test_screener_intelligence_boundary.py`）。

すべて合成の観測（A2 の凍結の test の合成の identity ・架空の値）。J-Quants ・network ・実データ ・LLM ・時計 ・乱数は使わない。
A2 の 3 module ・A1 ・A1R は変えない（追加の 3 module だけを試す）。
"""
from __future__ import annotations

import ast
import inspect
import json
from dataclasses import FrozenInstanceError, fields, replace
from pathlib import Path

import pytest

from src.intelligence.screener_intelligence import observation_semantics_gate as gate
from src.intelligence.screener_intelligence import observation_semantics_mapping as mapping
from src.intelligence.screener_intelligence import observation_semantics_model as sm
from src.intelligence.screener_intelligence.identity_model import SourceClass
from src.intelligence.screener_intelligence.observation_model import (FundamentalActual, FundamentalField,
                                                                      ObservationHistory, StatementBasis)
from src.intelligence.screener_intelligence.observation_semantics_gate import (AppendEligibility,
                                                                               CompatibilityReason,
                                                                               CompatibilityVerdict, HoldReason,
                                                                               decide_compatibility, plan_append)
from src.intelligence.screener_intelligence.observation_semantics_mapping import (
    DOCTYPE_MAPPING_VERSION, DOCUMENTED_DOC_TYPES, PILOT_OBSERVED_NONCONSOLIDATED_DOC_TYPES, SUPERVISOR_RULE_REF,
    derive_observation_semantics, map_row_semantics)
from src.intelligence.screener_intelligence.observation_semantics_model import (
    AccountingStandard, DocumentKind, FieldFamily, ObservationSemantics, SemanticEvidence, SemanticMappingProvenance,
    SemanticState, SemanticStatus, SemanticsModelError, semantic_status_for)
from tests.intelligence.phase8_runtime_registry import PHASE8_PACKAGE
from tests.intelligence.test_screener_observation import (CONS, D0602, FY24, FY25, Q1C25, Identity, market, money,
                                                          price, src, ts)

REPO_ROOT = Path(__file__).resolve().parents[2]
PACKAGE_DIR = REPO_ROOT / PHASE8_PACKAGE
NONCONS = StatementBasis.NON_CONSOLIDATED
F = FieldFamily
E = SemanticEvidence
JP_CONS = "FYFinancialStatements_Consolidated_JP"
JP_NONCONS = "FYFinancialStatements_NonConsolidated_JP"
US_CONS = "1QFinancialStatements_Consolidated_US"
IFRS_CONS = "2QFinancialStatements_Consolidated_IFRS"
IFRS_NONCONS = "2QFinancialStatements_NonConsolidated_IFRS"
JMIS_CONS = "3QFinancialStatements_Consolidated_JMIS"
FOREIGN_CONS = "FYFinancialStatements_Consolidated_Foreign"
FOREIGN_NONCONS = "FYFinancialStatements_NonConsolidated_Foreign"
REIT = "FYFinancialStatements_Consolidated_REIT"
REVISIONS = ("EarnForecastRevision", "DividendForecastRevision", "REITEarnForecastRevision",
             "REITDividendForecastRevision")
UNRECOGNIZED = ("", "fyfinancialstatements_consolidated_jp", "FYFinancialStatements_Consolidated_JP_v2",
                "4QFinancialStatements_Consolidated_JP", "1QFinancialStatements_NonConsolidated_US",
                "FYFinancialStatements_NonConsolidated_JMIS", "2QFinancialStatements_Consolidated_KOREA",
                "IFRS", "Consolidated_IFRS", "FinancialStatements_Consolidated_IFRS_FY", "EarnForecastRevision_IFRS")
IDS = Identity()
ISSUER = IDS.I1.issuer_id
PILOT_NONCONS = tuple(sorted(PILOT_OBSERVED_NONCONSOLIDATED_DOC_TYPES))


def obs(field: FundamentalField = FundamentalField.REVENUE, period=FY24, *, basis: StatementBasis = CONS,
        amount: str = "100", supersedes: str = "", known=None) -> FundamentalActual:
    return FundamentalActual(subject=ISSUER, field=field, statement_basis=basis, period=period, value=money(amount),
                             knowledge=known or ts(2025, 5, 10), provenance=src(SourceClass.JQUANTS, "jq:fs-0001",
                                                                                "Sales"), supersedes=supersedes)


def sem(observation: FundamentalActual, doc_type: str, family: FieldFamily = F.UNPREFIXED_ACTUAL):
    return derive_observation_semantics(observation.record_id, doc_type, family)


def semantics_only(observation: FundamentalActual, doc_type: str, family: FieldFamily = F.UNPREFIXED_ACTUAL):
    return sem(observation, doc_type, family)[0]


# ================================================================ A 語彙


def test_a_the_accounting_standard_vocabulary_is_exactly_the_supervisor_decision_d1() -> None:
    assert {member.value for member in AccountingStandard} == {"JP_GAAP", "US_GAAP", "IFRS", "JMIS", "UNKNOWN"}
    assert not any(member.value in ("FOREIGN", "Foreign", "REIT") for member in AccountingStandard)
    assert {member.value for member in E} == {"DOCUMENTED", "OBSERVED_IN_PILOT", "SUPERVISOR_APPROVED_MAPPING_RULE"}
    assert {member.value for member in SemanticState} == {"KNOWN", "UNKNOWN"}
    assert set(SemanticStatus) == {SemanticStatus.KNOWN, SemanticStatus.ACCOUNTING_STANDARD_UNKNOWN,
                                   SemanticStatus.STATEMENT_BASIS_UNKNOWN,
                                   SemanticStatus.ACCOUNTING_STANDARD_AND_STATEMENT_BASIS_UNKNOWN}


def test_a_the_statement_basis_reuses_the_frozen_a2_vocabulary_and_unknown_is_none() -> None:
    assert not any(name.endswith("Basis") and name != "StatementBasis"
                   for name in (*vars(sm), *vars(mapping), *vars(gate)) if isinstance(name, str)
                   and not name.startswith("_"))
    for basis in StatementBasis:
        assert semantic_status_for(AccountingStandard.IFRS, basis) is SemanticStatus.KNOWN
    assert semantic_status_for(AccountingStandard.IFRS, None) is SemanticStatus.STATEMENT_BASIS_UNKNOWN
    assert semantic_status_for(AccountingStandard.UNKNOWN, CONS) is SemanticStatus.ACCOUNTING_STANDARD_UNKNOWN
    assert semantic_status_for(AccountingStandard.UNKNOWN, None) is \
        SemanticStatus.ACCOUNTING_STANDARD_AND_STATEMENT_BASIS_UNKNOWN


# ================================================================ B 公式の表


def test_b_the_doctype_table_is_the_official_enumeration_of_45_values() -> None:
    assert len(DOCUMENTED_DOC_TYPES) == 45
    periods = ("FY", "1Q", "2Q", "3Q", "OtherPeriod")
    groups = (("Consolidated_JP", AccountingStandard.JP_GAAP, CONS),
              ("Consolidated_US", AccountingStandard.US_GAAP, CONS),
              ("NonConsolidated_JP", AccountingStandard.JP_GAAP, NONCONS),
              ("Consolidated_JMIS", AccountingStandard.JMIS, CONS),
              ("NonConsolidated_IFRS", AccountingStandard.IFRS, NONCONS),
              ("Consolidated_IFRS", AccountingStandard.IFRS, CONS),
              ("NonConsolidated_Foreign", AccountingStandard.UNKNOWN, NONCONS),
              ("Consolidated_Foreign", AccountingStandard.UNKNOWN, CONS))
    expected = {f"{period}FinancialStatements_{suffix}" for period in periods for suffix, _, _ in groups}
    expected |= {REIT, *REVISIONS}
    assert set(DOCUMENTED_DOC_TYPES) == expected
    for period in periods:
        for suffix, standard, basis in groups:
            row = DOCUMENTED_DOC_TYPES[f"{period}FinancialStatements_{suffix}"]
            assert (row.document_kind, row.accounting_standard, row.statement_basis) == \
                (DocumentKind.FINANCIAL_STATEMENTS, standard, basis)
    assert DOCUMENTED_DOC_TYPES[REIT].document_kind is DocumentKind.REIT_FINANCIAL_STATEMENTS
    assert {DOCUMENTED_DOC_TYPES[r].document_kind for r in REVISIONS[:2]} == {DocumentKind.FORECAST_REVISION}
    assert {DOCUMENTED_DOC_TYPES[r].document_kind for r in REVISIONS[2:]} == {DocumentKind.REIT_FORECAST_REVISION}
    for name in (REIT, *REVISIONS):
        assert DOCUMENTED_DOC_TYPES[name].accounting_standard is AccountingStandard.UNKNOWN
        assert DOCUMENTED_DOC_TYPES[name].statement_basis is None
    assert DOCTYPE_MAPPING_VERSION == "p8_jquants_v2_fins_summary_doctype:0.1.0"
    assert PILOT_OBSERVED_NONCONSOLIDATED_DOC_TYPES == {f"{p}FinancialStatements_NonConsolidated_JP"
                                                       for p in ("1Q", "2Q", "3Q", "FY")}


def test_b_the_mapping_is_total_and_never_raises_for_any_documented_value() -> None:
    for doc_type in DOCUMENTED_DOC_TYPES:
        for family in F:
            mapped = map_row_semantics(doc_type, family)
            assert isinstance(mapped, mapping.MappedSemantics)
            assert (mapped.accounting_standard is AccountingStandard.UNKNOWN) == (mapped.accounting_standard_evidence
                                                                                  == ())
            assert (mapped.statement_basis is None) == (mapped.statement_basis_evidence == ())


# ================================================================ C〜G 会計基準 × 連結の区分


@pytest.mark.parametrize("doc_type,standard", [(JP_CONS, AccountingStandard.JP_GAAP),
                                               (US_CONS, AccountingStandard.US_GAAP),
                                               (IFRS_CONS, AccountingStandard.IFRS),
                                               (JMIS_CONS, AccountingStandard.JMIS)])
def test_c_e_consolidated_rows_map_standard_and_basis_from_the_official_table(doc_type, standard) -> None:
    for family in (F.UNPREFIXED_ACTUAL, F.UNPREFIXED_FORECAST):
        mapped = map_row_semantics(doc_type, family)
        assert (mapped.accounting_standard, mapped.statement_basis) == (standard, CONS)
        assert mapped.accounting_standard_evidence == (E.DOCUMENTED,)
        assert mapped.statement_basis_evidence == (E.DOCUMENTED,)
        assert mapped.document_kind is DocumentKind.FINANCIAL_STATEMENTS
    semantics, provenance = sem(obs(), doc_type)
    assert semantics.semantic_status is SemanticStatus.KNOWN
    assert semantics.accounting_standard_state is SemanticState.KNOWN
    assert semantics.statement_basis_state is SemanticState.KNOWN
    assert provenance.document_kind is DocumentKind.FINANCIAL_STATEMENTS
    assert provenance.provider is SourceClass.JQUANTS and provenance.doc_type == doc_type


@pytest.mark.parametrize("doc_type", PILOT_NONCONS)
def test_d_nonconsolidated_jp_unprefixed_values_carry_pilot_plus_supervisor_evidence_never_documented(doc_type) -> None:
    for family in (F.UNPREFIXED_ACTUAL, F.UNPREFIXED_FORECAST):
        mapped = map_row_semantics(doc_type, family)
        assert (mapped.accounting_standard, mapped.statement_basis) == (AccountingStandard.JP_GAAP, NONCONS)
        assert mapped.accounting_standard_evidence == (E.DOCUMENTED,)                 # 会計基準は DocType に明記
        assert mapped.statement_basis_evidence == (E.OBSERVED_IN_PILOT, E.SUPERVISOR_APPROVED_MAPPING_RULE)
        assert E.DOCUMENTED not in mapped.statement_basis_evidence
        assert mapped.documentation_ref == SUPERVISOR_RULE_REF
    semantics, provenance = sem(obs(basis=NONCONS), doc_type)
    assert semantics.semantic_status is SemanticStatus.KNOWN and semantics.statement_basis is NONCONS
    assert provenance.statement_basis_evidence == (E.OBSERVED_IN_PILOT, E.SUPERVISOR_APPROVED_MAPPING_RULE)
    assert json.loads(provenance.canonical_line())["payload"]["statement_basis_evidence"] == [
        "OBSERVED_IN_PILOT", "SUPERVISOR_APPROVED_MAPPING_RULE"]


@pytest.mark.parametrize("doc_type", ["OtherPeriodFinancialStatements_NonConsolidated_JP", IFRS_NONCONS,
                                      FOREIGN_NONCONS])
def test_d_nonconsolidated_rows_not_observed_in_pilot_keep_the_unprefixed_basis_unknown(doc_type) -> None:
    mapped = map_row_semantics(doc_type, F.UNPREFIXED_ACTUAL)
    assert mapped.statement_basis is None and mapped.statement_basis_evidence == ()
    assert semantics_only(obs(basis=NONCONS), doc_type).statement_basis_state is SemanticState.UNKNOWN


@pytest.mark.parametrize("doc_type", sorted(DOCUMENTED_DOC_TYPES))
def test_d_nc_prefixed_fields_are_documented_non_consolidated_and_never_inherit_the_row_standard(doc_type) -> None:
    kind = DOCUMENTED_DOC_TYPES[doc_type].document_kind
    for family in (F.NC_PREFIXED_ACTUAL, F.NC_PREFIXED_FORECAST):
        mapped = map_row_semantics(doc_type, family)
        assert mapped.accounting_standard is AccountingStandard.UNKNOWN
        assert mapped.accounting_standard_evidence == ()
        if kind in (DocumentKind.FINANCIAL_STATEMENTS, DocumentKind.FORECAST_REVISION):
            assert mapped.statement_basis is NONCONS and mapped.statement_basis_evidence == (E.DOCUMENTED,)
        else:
            assert mapped.statement_basis is None


@pytest.mark.parametrize("doc_type,basis", [(FOREIGN_CONS, CONS), (FOREIGN_NONCONS, None)])
def test_f_foreign_is_not_an_accounting_standard(doc_type, basis) -> None:
    mapped = map_row_semantics(doc_type, F.UNPREFIXED_ACTUAL)
    assert mapped.accounting_standard is AccountingStandard.UNKNOWN and mapped.accounting_standard_evidence == ()
    assert mapped.statement_basis is basis
    semantics = semantics_only(obs(), doc_type)
    assert semantics.accounting_standard_state is SemanticState.UNKNOWN
    assert plan_append(obs(), semantics).eligibility is AppendEligibility.HOLD


def test_g_reit_rows_are_unknown_on_both_dimensions() -> None:
    for family in F:
        mapped = map_row_semantics(REIT, family)
        assert mapped.document_kind is DocumentKind.REIT_FINANCIAL_STATEMENTS
        assert (mapped.accounting_standard, mapped.statement_basis) == (AccountingStandard.UNKNOWN, None)
        assert mapped.accounting_standard_evidence == () and mapped.statement_basis_evidence == ()


# ================================================================ H 未知の DocType ・token の解析の禁止


@pytest.mark.parametrize("doc_type", UNRECOGNIZED)
def test_h_unrecognized_doctypes_are_unknown_even_when_they_contain_official_tokens(doc_type) -> None:
    for family in F:
        mapped = map_row_semantics(doc_type, family)
        assert mapped.document_kind is DocumentKind.UNRECOGNIZED
        assert (mapped.accounting_standard, mapped.statement_basis) == (AccountingStandard.UNKNOWN, None)
        assert mapped.accounting_standard_evidence == () and mapped.statement_basis_evidence == ()
    semantics, provenance = sem(obs(), doc_type)
    assert semantics.semantic_status is SemanticStatus.ACCOUNTING_STANDARD_AND_STATEMENT_BASIS_UNKNOWN
    assert provenance.document_kind is DocumentKind.UNRECOGNIZED and provenance.doc_type == doc_type
    assert plan_append(obs(), semantics).reasons == (HoldReason.ACCOUNTING_STANDARD_UNKNOWN,
                                                     HoldReason.STATEMENT_BASIS_UNKNOWN)


def test_h_the_mapping_module_never_parses_doctype_strings_and_the_table_keys_are_literals() -> None:
    tree = ast.parse((PACKAGE_DIR / "observation_semantics_mapping.py").read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute):
            assert node.attr not in {"split", "rsplit", "partition", "rpartition", "endswith", "startswith", "find",
                                     "rfind", "index", "search", "match", "fullmatch", "lower", "upper", "strip"}, \
                node.attr
        if isinstance(node, ast.Compare):
            assert not any(isinstance(op, (ast.In, ast.NotIn)) and isinstance(node.left, ast.Constant)
                           for op in node.ops)
    table = next(n for n in tree.body if isinstance(n, ast.AnnAssign) and n.target.id == "DOCUMENTED_DOC_TYPES")
    assert isinstance(table.value, ast.Dict) and len(table.value.keys) == 45
    assert all(isinstance(key, ast.Constant) and isinstance(key.value, str) for key in table.value.keys)
    assert map_row_semantics("1QFinancialStatements_Consolidated_IFRS", F.UNPREFIXED_ACTUAL).accounting_standard \
        is AccountingStandard.IFRS
    for near_miss in (" 1QFinancialStatements_Consolidated_IFRS", "1QFinancialStatements_Consolidated_IFRS\n",
                      "1QFinancialStatements_Consolidated_ifrs", "1Q_FinancialStatements_Consolidated_IFRS"):
        assert map_row_semantics(near_miss, F.UNPREFIXED_ACTUAL).accounting_standard is AccountingStandard.UNKNOWN
    with pytest.raises(SemanticsModelError) as info:
        map_row_semantics(None, F.UNPREFIXED_ACTUAL)
    assert info.value.code == "INVALID_DOC_TYPE"
    with pytest.raises(SemanticsModelError) as info:
        map_row_semantics(JP_CONS, "UNPREFIXED_ACTUAL")
    assert info.value.code == "INVALID_VOCABULARY"


# ================================================================ I 予想の修正の行


@pytest.mark.parametrize("doc_type", REVISIONS)
def test_i_forecast_revision_rows_are_unknown_and_held(doc_type) -> None:
    for family in (F.UNPREFIXED_ACTUAL, F.UNPREFIXED_FORECAST):
        mapped = map_row_semantics(doc_type, family)
        assert (mapped.accounting_standard, mapped.statement_basis) == (AccountingStandard.UNKNOWN, None)
        assert mapped.accounting_standard_evidence == () and mapped.statement_basis_evidence == ()
    semantics = semantics_only(obs(), doc_type, F.UNPREFIXED_FORECAST)
    assert semantics.semantic_status is SemanticStatus.ACCOUNTING_STANDARD_AND_STATEMENT_BASIS_UNKNOWN
    plan = plan_append(obs(), semantics)
    assert plan.eligibility is AppendEligibility.HOLD
    assert HoldReason.ACCOUNTING_STANDARD_UNKNOWN in plan.reasons and HoldReason.STATEMENT_BASIS_UNKNOWN in plan.reasons


def test_i_forecast_revision_semantics_cannot_be_inherited_from_another_row() -> None:
    root = obs()
    root_semantics = semantics_only(root, JP_CONS)                                    # 先行の財務諸表の行: JP ・連結
    revised = obs(amount="120", supersedes=root.record_id, known=ts(2025, 8, 1))
    revised_semantics = semantics_only(revised, "EarnForecastRevision", F.UNPREFIXED_FORECAST)
    assert revised_semantics.accounting_standard is AccountingStandard.UNKNOWN          # 鎖の先頭から継承しない
    assert revised_semantics.statement_basis is None
    plan = plan_append(revised, revised_semantics, root, root_semantics)
    assert plan.eligibility is AppendEligibility.HOLD
    assert plan.reasons == (HoldReason.ACCOUNTING_STANDARD_UNKNOWN, HoldReason.STATEMENT_BASIS_UNKNOWN)
    assert plan.chain_head_id == root.record_id
    parameters = inspect.signature(derive_observation_semantics).parameters
    assert list(parameters) == ["observation_id", "doc_type", "field_family"]         # 他の行 ・発行体 ・年度を受けない
    assert list(inspect.signature(map_row_semantics).parameters) == ["doc_type", "field_family"]
    assert map_row_semantics("EarnForecastRevision", F.UNPREFIXED_FORECAST) == \
        map_row_semantics("EarnForecastRevision", F.UNPREFIXED_FORECAST)


# ================================================================ J 互換の gate


def _pair(left_doc: str, right_doc: str, left_family=F.UNPREFIXED_ACTUAL, right_family=F.UNPREFIXED_ACTUAL):
    left = semantics_only(obs(), left_doc, left_family)
    right = semantics_only(obs(amount="200"), right_doc, right_family)
    return left, right, decide_compatibility(left, right)


def test_j_same_known_standard_and_basis_is_compatible() -> None:
    left, right, decision = _pair(JP_CONS, "1QFinancialStatements_Consolidated_JP")
    assert decision.verdict is CompatibilityVerdict.COMPATIBLE and decision.reasons == ()
    assert (decision.left_observation_id, decision.right_observation_id) == (left.observation_id,
                                                                            right.observation_id)
    assert decision.authority_class == "DERIVED_NON_AUTHORITY_NON_PERSISTENT"
    assert decision.rules_version == gate.GATE_RULES_VERSION


def test_j_different_known_standards_are_incompatible() -> None:
    _, _, decision = _pair(JP_CONS, IFRS_CONS)
    assert decision.verdict is CompatibilityVerdict.INCOMPATIBLE
    assert decision.reasons == (CompatibilityReason.ACCOUNTING_STANDARD_DIFFERS,)


def test_j_different_known_bases_are_incompatible() -> None:
    _, _, decision = _pair(JP_CONS, JP_NONCONS)
    assert decision.verdict is CompatibilityVerdict.INCOMPATIBLE
    assert decision.reasons == (CompatibilityReason.STATEMENT_BASIS_DIFFERS,)
    _, _, both = _pair(IFRS_CONS, JP_NONCONS)
    assert both.reasons == (CompatibilityReason.ACCOUNTING_STANDARD_DIFFERS,
                            CompatibilityReason.STATEMENT_BASIS_DIFFERS)


def test_j_known_versus_unknown_is_ineligible_and_differences_are_not_judged() -> None:
    _, _, decision = _pair(JP_CONS, "EarnForecastRevision", right_family=F.UNPREFIXED_FORECAST)
    assert decision.verdict is CompatibilityVerdict.INELIGIBLE
    assert decision.reasons == (CompatibilityReason.RIGHT_ACCOUNTING_STANDARD_UNKNOWN,
                                CompatibilityReason.RIGHT_STATEMENT_BASIS_UNKNOWN)
    _, _, foreign = _pair(FOREIGN_CONS, JP_CONS)                                        # 会計基準だけ UNKNOWN
    assert foreign.verdict is CompatibilityVerdict.INELIGIBLE
    assert foreign.reasons == (CompatibilityReason.LEFT_ACCOUNTING_STANDARD_UNKNOWN,)
    _, _, basis = _pair(IFRS_NONCONS, JP_CONS)                                          # 連結の区分だけ UNKNOWN
    assert basis.reasons == (CompatibilityReason.LEFT_STATEMENT_BASIS_UNKNOWN,)
    assert CompatibilityReason.ACCOUNTING_STANDARD_DIFFERS not in basis.reasons


def test_j_unknown_versus_unknown_is_ineligible_not_compatible() -> None:
    _, _, decision = _pair("EarnForecastRevision", "DividendForecastRevision", F.UNPREFIXED_FORECAST,
                           F.UNPREFIXED_FORECAST)
    assert decision.verdict is CompatibilityVerdict.INELIGIBLE
    assert decision.reasons == (CompatibilityReason.LEFT_ACCOUNTING_STANDARD_UNKNOWN,
                                CompatibilityReason.LEFT_STATEMENT_BASIS_UNKNOWN,
                                CompatibilityReason.RIGHT_ACCOUNTING_STANDARD_UNKNOWN,
                                CompatibilityReason.RIGHT_STATEMENT_BASIS_UNKNOWN)


def test_j_the_gate_is_deterministic_symmetric_in_verdict_and_typed() -> None:
    left, right, decision = _pair(JP_CONS, IFRS_CONS)
    assert decision == decide_compatibility(left, right) and decision.as_dict() == decide_compatibility(
        left, right).as_dict()
    assert decide_compatibility(right, left).verdict is decision.verdict
    assert set(decision.as_dict()) == {"authority_class", "left_observation_id", "reasons", "right_observation_id",
                                       "rules_version", "verdict"}
    with pytest.raises(FrozenInstanceError):
        decision.verdict = CompatibilityVerdict.COMPATIBLE                                # type: ignore[misc]
    with pytest.raises(SemanticsModelError) as info:
        decide_compatibility(left, obs())                                                 # type: ignore[arg-type]
    assert info.value.code == "INVALID_SEMANTICS"


# ================================================================ K 追記の plan（監督の決定 d3）


def test_k_a_known_root_on_an_empty_chain_is_eligible() -> None:
    root = obs()
    plan = plan_append(root, semantics_only(root, JP_CONS))
    assert plan.eligibility is AppendEligibility.ELIGIBLE and plan.reasons == ()
    assert (plan.observation_id, plan.slot_key, plan.chain_head_id) == (root.record_id, root.slot_key, "")
    assert plan.authority_class == "DERIVED_NON_AUTHORITY_NON_PERSISTENT"


def test_k_a_matching_revision_of_a_known_chain_is_eligible() -> None:
    root = obs()
    revised = obs(amount="120", supersedes=root.record_id, known=ts(2025, 8, 1))
    plan = plan_append(revised, semantics_only(revised, JP_CONS), root, semantics_only(root, JP_CONS))
    assert plan.eligibility is AppendEligibility.ELIGIBLE and plan.chain_head_id == root.record_id


def test_k_g1_a_different_standard_is_accepted_by_frozen_a2_alone_but_held_by_the_gate() -> None:
    root = obs()
    revised = obs(amount="120", supersedes=root.record_id, known=ts(2025, 8, 1))
    history = ObservationHistory(IDS.history(), [root])
    history.check(revised)                                                                # A2 だけなら同じ鎖の revision
    plan = plan_append(revised, semantics_only(revised, IFRS_CONS), root, semantics_only(root, JP_CONS))
    assert plan.eligibility is AppendEligibility.HOLD
    assert plan.reasons == (HoldReason.ACCOUNTING_STANDARD_DIFFERS_FROM_CHAIN,)
    assert history.records == (root,)                                                     # plan は追記しない


def test_k_a_different_basis_from_the_chain_is_held() -> None:
    root = obs()
    revised = obs(amount="120", supersedes=root.record_id, known=ts(2025, 8, 1))
    plan = plan_append(revised, semantics_only(revised, JP_NONCONS), root, semantics_only(root, JP_CONS))
    assert plan.eligibility is AppendEligibility.HOLD
    assert plan.reasons == (HoldReason.STATEMENT_BASIS_DIFFERS_FROM_CHAIN,
                            HoldReason.STATEMENT_BASIS_INCONSISTENT_WITH_OBSERVATION)


@pytest.mark.parametrize("doc_type,reasons", [
    (FOREIGN_CONS, (HoldReason.ACCOUNTING_STANDARD_UNKNOWN,)),
    (IFRS_NONCONS, (HoldReason.STATEMENT_BASIS_UNKNOWN,)),
    ("EarnForecastRevision", (HoldReason.ACCOUNTING_STANDARD_UNKNOWN, HoldReason.STATEMENT_BASIS_UNKNOWN)),
    (REIT, (HoldReason.ACCOUNTING_STANDARD_UNKNOWN, HoldReason.STATEMENT_BASIS_UNKNOWN)),
    ("NotADocumentedValue", (HoldReason.ACCOUNTING_STANDARD_UNKNOWN, HoldReason.STATEMENT_BASIS_UNKNOWN))])
def test_k_unknown_dimensions_are_held_with_explicit_reasons(doc_type, reasons) -> None:
    root = obs(basis=NONCONS if doc_type == IFRS_NONCONS else CONS)
    plan = plan_append(root, semantics_only(root, doc_type))
    assert plan.eligibility is AppendEligibility.HOLD and plan.reasons == reasons


def test_k_an_unknown_chain_head_holds_even_a_known_incoming() -> None:
    root = obs()
    revised = obs(amount="120", supersedes=root.record_id, known=ts(2025, 8, 1))
    plan = plan_append(revised, semantics_only(revised, JP_CONS), root, semantics_only(root, FOREIGN_CONS))
    assert plan.reasons == (HoldReason.CHAIN_ACCOUNTING_STANDARD_UNKNOWN,)
    plan = plan_append(revised, semantics_only(revised, JP_CONS), root, semantics_only(root, "EarnForecastRevision"))
    assert plan.reasons == (HoldReason.CHAIN_ACCOUNTING_STANDARD_UNKNOWN, HoldReason.CHAIN_STATEMENT_BASIS_UNKNOWN)


def test_k_semantics_must_belong_to_the_observations_they_annotate() -> None:
    root, other = obs(), obs(amount="999")
    plan = plan_append(root, semantics_only(other, JP_CONS))
    assert plan.reasons == (HoldReason.SEMANTICS_NOT_FOR_THIS_OBSERVATION,)
    revised = obs(amount="120", supersedes=root.record_id, known=ts(2025, 8, 1))
    plan = plan_append(revised, semantics_only(revised, JP_CONS), root, semantics_only(other, JP_CONS))
    assert plan.reasons == (HoldReason.CHAIN_SEMANTICS_NOT_FOR_CHAIN_HEAD,)


def test_k_the_annotation_basis_must_agree_with_the_a2_observation() -> None:
    root = obs(basis=CONS)
    plan = plan_append(root, semantics_only(root, JP_NONCONS))                            # 注記は単体、観測は連結
    assert plan.reasons == (HoldReason.STATEMENT_BASIS_INCONSISTENT_WITH_OBSERVATION,)


def test_k_slot_and_supersedes_must_match_the_chain_head() -> None:
    root = obs()
    other_slot = obs(period=Q1C25, supersedes=root.record_id, known=ts(2025, 8, 1))
    plan = plan_append(other_slot, semantics_only(other_slot, JP_CONS), root, semantics_only(root, JP_CONS))
    assert plan.reasons == (HoldReason.CHAIN_SLOT_MISMATCH,)
    detached = obs(amount="120", known=ts(2025, 8, 1))                                    # supersedes が空
    plan = plan_append(detached, semantics_only(detached, JP_CONS), root, semantics_only(root, JP_CONS))
    assert plan.reasons == (HoldReason.SUPERSEDES_MISMATCH,)
    orphan = obs(supersedes="p8obs_000000000000000000000000")                             # 鎖が空なのに supersedes
    assert plan_append(orphan, semantics_only(orphan, JP_CONS)).reasons == (HoldReason.SUPERSEDES_MISMATCH,)


def test_k_the_plan_rejects_non_financial_observations_and_half_chains() -> None:
    root = obs()
    with pytest.raises(SemanticsModelError) as info:
        plan_append(market(IDS.S1, __import__("src.intelligence.screener_intelligence.observation_model",
                                              fromlist=["MarketField"]).MarketField.CLOSE, price("10"), D0602,
                           ts(2025, 6, 2, 7)), semantics_only(root, JP_CONS))
    assert info.value.code == "NOT_FINANCIAL_OBSERVATION"
    with pytest.raises(SemanticsModelError) as info:
        plan_append(root, semantics_only(root, JP_CONS), root, None)
    assert info.value.code == "INVALID_CHAIN"
    with pytest.raises(SemanticsModelError):
        plan_append(root, semantics_only(root, JP_CONS), None, semantics_only(root, JP_CONS))


def test_k_hold_and_eligible_are_the_only_outcomes_and_a_plan_is_immutable_and_non_persistent() -> None:
    assert {member.value for member in AppendEligibility} == {"ELIGIBLE", "HOLD"}
    plan = plan_append(obs(), semantics_only(obs(), JP_CONS))
    with pytest.raises(FrozenInstanceError):
        plan.eligibility = AppendEligibility.HOLD                                          # type: ignore[misc]
    assert set(plan.as_dict()) == {"authority_class", "chain_head_id", "eligibility", "observation_id", "reasons",
                                   "rules_version", "slot_key"}
    assert not hasattr(plan, "record_id") and not hasattr(plan, "canonical_line")
    tree = ast.parse((PACKAGE_DIR / "observation_semantics_gate.py").read_text(encoding="utf-8"))
    for node in ast.walk(tree):                                                           # append は局所の理由の list だけ
        if isinstance(node, ast.Attribute) and node.attr == "append":
            assert isinstance(node.value, ast.Name) and node.value.id == "reasons"
    assert not any(isinstance(node, ast.ImportFrom) and node.module and "store" in node.module
                   for node in ast.walk(tree))


# ================================================================ L identity ・直列化


def test_l_records_are_content_addressed_and_round_trip() -> None:
    root = obs()
    semantics, provenance = sem(root, JP_NONCONS)
    again, provenance_again = sem(root, JP_NONCONS)
    assert (semantics, provenance) == (again, provenance_again)
    assert semantics.record_id == again.record_id and provenance.record_id == provenance_again.record_id
    assert semantics.record_id.startswith("p8sem_") and provenance.record_id.startswith("p8map_")
    assert semantics.mapping_provenance_id == provenance.record_id
    assert ObservationSemantics.from_dict(json.loads(semantics.canonical_line())) == semantics
    assert SemanticMappingProvenance.from_dict(json.loads(provenance.canonical_line())) == provenance
    for line in (semantics.canonical_line(), provenance.canonical_line()):
        assert line.endswith("\n") and json.dumps(json.loads(line), sort_keys=True, separators=(",", ":"),
                                                  ensure_ascii=False) + "\n" == line
    other, _ = sem(root, JP_CONS)
    assert other.record_id != semantics.record_id                                         # 内容が違えば id が違う
    assert sem(obs(amount="7"), JP_NONCONS)[0].record_id != semantics.record_id           # 観測が違えば id が違う
    assert semantics.AUTHORITY_CLASS == "SEMANTIC_METADATA_RECORD" and not hasattr(semantics, "known_at")


def test_l_tampered_or_inconsistent_serializations_are_rejected() -> None:
    semantics, provenance = sem(obs(), JP_CONS)
    data = semantics.as_dict()
    for broken, code in (({**data, "record_id": "p8sem_" + "0" * 24}, "ID_MISMATCH"),
                         ({**data, "schema_version": "p8_observation_semantics:9.9.9"}, "SCHEMA_MISMATCH"),
                         ({**data, "record_kind": provenance.KIND}, "KIND_MISMATCH"),
                         ({**data, "extra": 1}, "UNKNOWN_FIELD"),
                         ({**data, "payload": {**data["payload"], "semantic_status": "STATEMENT_BASIS_UNKNOWN"}},
                          "STATUS_MISMATCH"),
                         ({**data, "payload": {**data["payload"], "accounting_standard": "Foreign"}},
                          "INVALID_VOCABULARY")):
        with pytest.raises(SemanticsModelError) as info:
            ObservationSemantics.from_dict(broken)
        assert info.value.code == code, code
    pdata = provenance.as_dict()
    for evidence, code in (([], None), (["DOCUMENTED", "DOCUMENTED"], "INVALID_EVIDENCE"),
                           (["SUPERVISOR_APPROVED_MAPPING_RULE", "OBSERVED_IN_PILOT"], "INVALID_EVIDENCE"),
                           (["FOUND_ON_THE_INTERNET"], "INVALID_VOCABULARY"), ("DOCUMENTED", "INVALID_EVIDENCE")):
        broken = {**pdata, "payload": {**pdata["payload"], "statement_basis_evidence": evidence}}
        if code is None:
            broken["record_id"] = SemanticMappingProvenance(**{
                **{f.name: getattr(provenance, f.name) for f in fields(provenance)},
                "statement_basis_evidence": ()}).record_id
            SemanticMappingProvenance.from_dict(broken)
            continue
        with pytest.raises(SemanticsModelError) as info:
            SemanticMappingProvenance.from_dict(broken)
        assert info.value.code == code, evidence


def test_l_records_reject_invalid_ids_versions_credentials_paths_and_floats() -> None:
    semantics, provenance = sem(obs(), JP_CONS)
    for name, value, code in (("observation_id", "p8idr_" + "0" * 24, "INVALID_ID"),
                              ("mapping_rule_version", "0.1.0", "INVALID_RULE_VERSION"),
                              ("mapping_provenance_id", "p8sem_" + "0" * 24, "INVALID_ID")):
        with pytest.raises(SemanticsModelError) as info:
            replace(semantics, **{name: value})
        assert info.value.code == code
    with pytest.raises(SemanticsModelError) as info:
        replace(semantics, semantic_status=SemanticStatus.STATEMENT_BASIS_UNKNOWN)
    assert info.value.code == "STATUS_MISMATCH"
    for name, value, code in (("doc_type", "x" * 65, "INVALID_DOC_TYPE"), ("doc_type", "a b", "INVALID_DOC_TYPE"),
                              ("doc_type", "apikey_FY", "CREDENTIAL_LIKE_TEXT"),
                              ("documentation_ref", "docs/spec.md", "INVALID_DOCUMENTATION_REF"),
                              ("documentation_ref", "bearer:x", "CREDENTIAL_LIKE_TEXT"),
                              ("provider", "JQUANTS", "INVALID_VOCABULARY"),
                              ("accounting_standard_evidence", [E.DOCUMENTED], "INVALID_EVIDENCE")):
        with pytest.raises(SemanticsModelError) as info:
            replace(provenance, **{name: value})
        assert info.value.code == code, name
    with pytest.raises(SemanticsModelError) as info:
        derive_observation_semantics("obs-1", JP_CONS, F.UNPREFIXED_ACTUAL)
    assert info.value.code == "INVALID_ID"
    for record in (semantics, provenance):
        assert all(f.type not in ("float", float) for f in fields(record))
        assert not any(isinstance(v, float) for v in json.loads(record.canonical_line())["payload"].values())


# ================================================================ M DOCUMENTED の主張の範囲


def test_m_documented_is_claimed_only_where_the_official_text_establishes_the_dimension() -> None:
    for doc_type, documented in DOCUMENTED_DOC_TYPES.items():
        for family in F:
            mapped = map_row_semantics(doc_type, family)
            if E.DOCUMENTED in mapped.accounting_standard_evidence:
                assert documented.accounting_standard is not AccountingStandard.UNKNOWN
                assert family in (F.UNPREFIXED_ACTUAL, F.UNPREFIXED_FORECAST)
                assert documented.document_kind is DocumentKind.FINANCIAL_STATEMENTS
            if E.DOCUMENTED in mapped.statement_basis_evidence:
                assert mapped.statement_basis is not None
                if family in (F.UNPREFIXED_ACTUAL, F.UNPREFIXED_FORECAST):
                    assert documented.statement_basis is CONS                             # 単体の行の接頭辞なしは d2
            if doc_type in PILOT_OBSERVED_NONCONSOLIDATED_DOC_TYPES and family in (F.UNPREFIXED_ACTUAL,
                                                                                  F.UNPREFIXED_FORECAST):
                assert mapped.statement_basis_evidence == (E.OBSERVED_IN_PILOT, E.SUPERVISOR_APPROVED_MAPPING_RULE)
            if E.SUPERVISOR_APPROVED_MAPPING_RULE in mapped.statement_basis_evidence:
                assert doc_type in PILOT_OBSERVED_NONCONSOLIDATED_DOC_TYPES                # 承認は観測した 4 値だけ


# ================================================================ N 決定論 ・A2 の不変


def test_n_the_layer_does_not_reach_into_a2_authority_or_a1() -> None:
    for name in ("observation_semantics_model", "observation_semantics_mapping", "observation_semantics_gate"):
        source = (PACKAGE_DIR / f"{name}.py").read_text(encoding="utf-8")
        assert ".observation_store" not in source and ".identity_store" not in source
        assert ".observation_resolver" not in source and ".identity_resolver" not in source
        assert "ObservationHistory" not in source                                         # 鎖の authority は A2 のまま
    assert not any(hasattr(module, attr) for module in (sm, mapping, gate) for attr in ("append", "store", "write"))
