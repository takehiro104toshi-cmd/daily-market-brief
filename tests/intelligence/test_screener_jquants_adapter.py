"""P8-ADP0 — J-Quants `/v2/fins/summary` の純 adapter の test matrix A〜H。

境界 ／ 凍結の guard は `test_screener_intelligence_boundary.py`。

すべて合成の行（架空の code ・値 ・開示番号）。live の応答 ・J-Quants ・network ・実データ ・LLM ・時計 ・乱数 ・filesystem は使わない。
A1 ・A2 ・A2R ・A3 ・ST1 の module は変えない。
"""
from __future__ import annotations

import ast
import json
from dataclasses import FrozenInstanceError, fields
from datetime import date, datetime, timezone
from pathlib import Path

import pytest

from src.intelligence.screener_intelligence import jquants_adapter_model as am
from src.intelligence.screener_intelligence import jquants_financial_summary_adapter as fa
from src.intelligence.screener_intelligence.held_observation_model import HeldObservation, HeldReason
from src.intelligence.screener_intelligence.identity_model import SourceClass, is_issuer_id, is_security_id
from src.intelligence.screener_intelligence.jquants_adapter_model import (AdapterContext, AdapterInputError,
                                                                          AdapterResult, AdapterStatus,
                                                                          FinancialSummaryRow,
                                                                          ProviderRecordIdentity)
from src.intelligence.screener_intelligence.jquants_financial_summary_adapter import adapt_financial_summary_row
from src.intelligence.screener_intelligence.observation_model import (TOKYO, FundamentalActual, FundamentalField,
                                                                      KnowledgePrecision, PeriodBasis, Scale,
                                                                      StatementBasis, ValueState)
from src.intelligence.screener_intelligence.observation_semantics_model import AccountingStandard, SemanticStatus
from tests.intelligence.phase8_runtime_registry import PHASE8_PACKAGE
from tests.intelligence.test_prediction_record import executable_source
from tests.intelligence.test_screener_fundamental_metrics import I1
from tests.intelligence.test_screener_observation import at

REPO_ROOT = Path(__file__).resolve().parents[2]
PACKAGE_DIR = REPO_ROOT / PHASE8_PACKAGE
CTX = AdapterContext(issuer_id=I1)
CTX_TIMED = AdapterContext(issuer_id=I1, acquired_at=at(2026, 6, 30, 12))
BASE = {"Code": "00010", "DiscDate": "2025-05-12", "DiscTime": "15:00:00", "DiscNo": "20250512000001",
        "DocType": "FYFinancialStatements_Consolidated_JP", "CurPerType": "FY", "CurPerSt": "2024-04-01",
        "CurPerEn": "2025-03-31", "CurFYSt": "2024-04-01", "CurFYEn": "2025-03-31", "Sales": "500000000000",
        "OP": "40000000000", "NP": "30000000000", "TA": "900000000000"}
Q = {"1Q": ("2024-06-30", "1QFinancialStatements_Consolidated_JP"),
     "2Q": ("2024-09-30", "2QFinancialStatements_Consolidated_JP"),
     "3Q": ("2024-12-31", "3QFinancialStatements_Consolidated_JP")}


def row(**overrides) -> dict:
    return {**BASE, **overrides}


def quarterly(kind: str, **overrides) -> dict:
    end, doc = Q[kind]
    disclosed = {"1Q": "2024-08-08", "2Q": "2024-11-08", "3Q": "2025-02-07"}[kind]
    return {**row(CurPerType=kind, CurPerEn=end, DocType=doc, DiscDate=disclosed), **overrides}


def adapt(mapping, context=CTX) -> AdapterResult:
    return adapt_financial_summary_row(mapping, context)


def reasons(result: AdapterResult) -> list:
    return [r.value for r in result.reasons]


# ================================================================ A 通る行


def test_a_jp_gaap_consolidated_fy_is_eligible_with_all_four_fields() -> None:
    result = adapt(row())
    assert result.status is AdapterStatus.ELIGIBLE and result.reasons == () and result.held is None
    material = result.eligible
    assert material.issuer_id == I1 and material.period.basis is PeriodBasis.FISCAL_YEAR
    assert material.knowledge.precision is KnowledgePrecision.TIMESTAMP
    assert material.knowledge.at == datetime(2025, 5, 12, 15, 0, 0, tzinfo=TOKYO)
    assert [o.field for o in material.observations] == [FundamentalField.REVENUE, FundamentalField.OPERATING_INCOME,
                                                        FundamentalField.NET_INCOME, FundamentalField.TOTAL_ASSETS]
    for observation, provider_field in zip(material.observations, ("Sales", "OP", "NP", "TA")):
        assert isinstance(observation, FundamentalActual) and observation.subject == I1
        assert observation.statement_basis is StatementBasis.CONSOLIDATED and observation.supersedes == ""
        assert observation.value.state is ValueState.VALUE_PRESENT and observation.value.scale is Scale.ONE
        assert observation.value.currency.value == "JPY" and observation.provenance.source_field == provider_field
        assert observation.provenance.source_class is SourceClass.JQUANTS
        assert observation.provenance.source_record_ref == result.provider_record.reference()
    assert material.observations[0].value.amount == "500000000000"
    assert len(material.annotations) == 4
    for (semantics, provenance), observation in zip(material.annotations, material.observations):
        assert semantics.observation_id == observation.record_id and semantics.semantic_status is SemanticStatus.KNOWN
        assert semantics.accounting_standard is AccountingStandard.JP_GAAP
        assert semantics.mapping_provenance_id == provenance.record_id and provenance.doc_type == BASE["DocType"]
    assert result.mapping_rule_version == "p8_jquants_v2_fins_summary_doctype:0.1.0"
    assert result.rules_version == "p8_jquants_fins_summary_adapter:0.1.0"
    assert result.authority_class == "DERIVED_NON_AUTHORITY_NON_PERSISTENT"


def test_a_approved_jp_gaap_nonconsolidated_fy_is_eligible_with_non_consolidated_basis() -> None:
    result = adapt(row(DocType="FYFinancialStatements_NonConsolidated_JP"))
    assert result.status is AdapterStatus.ELIGIBLE
    assert {o.statement_basis for o in result.eligible.observations} == {StatementBasis.NON_CONSOLIDATED}
    semantics, provenance = result.eligible.annotations[0]
    assert semantics.statement_basis is StatementBasis.NON_CONSOLIDATED
    assert [e.value for e in provenance.statement_basis_evidence] == ["OBSERVED_IN_PILOT",
                                                                       "SUPERVISOR_APPROVED_MAPPING_RULE"]


@pytest.mark.parametrize("kind,quarter", [("1Q", 1), ("2Q", 2), ("3Q", 3)])
def test_a_quarterly_rows_are_cumulative_year_to_date_never_standalone(kind: str, quarter: int) -> None:
    result = adapt(quarterly(kind))
    assert result.status is AdapterStatus.ELIGIBLE
    period = result.eligible.period
    assert period.basis is PeriodBasis.CUMULATIVE_YEAR_TO_DATE and period.quarter == quarter
    assert period.period_start == period.fiscal_year_start == date(2024, 4, 1)
    assert "SINGLE_QUARTER" not in json.dumps(result.as_dict())


def test_a_empty_supported_field_is_not_reported_and_zero_is_numeric_zero() -> None:
    result = adapt(row(OP="", TA="0"))
    assert result.status is AdapterStatus.ELIGIBLE
    by_field = {o.field: o for o in result.eligible.observations}
    assert by_field[FundamentalField.OPERATING_INCOME].value.state is ValueState.NOT_REPORTED
    assert by_field[FundamentalField.OPERATING_INCOME].value.amount is None
    assert by_field[FundamentalField.TOTAL_ASSETS].value.state is ValueState.VALUE_PRESENT
    assert by_field[FundamentalField.TOTAL_ASSETS].value.amount == "0"
    assert len(result.eligible.observations) == 4                                          # 空でも観測は作る（0 にしない）


# ================================================================ B provider の record の identity


def test_b_identity_is_deterministic_and_order_independent() -> None:
    first = ProviderRecordIdentity.of(FinancialSummaryRow.from_provider_mapping(row()))
    reordered = dict(reversed(list(row().items())))
    second = ProviderRecordIdentity.of(FinancialSummaryRow.from_provider_mapping(reordered))
    assert first == second and first.digest == second.digest and len(first.digest) == 64
    assert first.natural_key == ("00010", "2025-05-12", "15:00:00", "20250512000001", BASE["DocType"])
    assert first.reference() == f"jq.fins_summary:00010.20250512000001.{BASE['DocType']}:{first.digest[:24]}"
    assert adapt(row()).provider_record == first and adapt(reordered).provider_record == first


def test_b_disc_no_alone_is_not_sufficient_and_changed_content_is_a_new_revision() -> None:
    base = ProviderRecordIdentity.of(FinancialSummaryRow.from_provider_mapping(row()))
    other_code = ProviderRecordIdentity.of(FinancialSummaryRow.from_provider_mapping(row(Code="00020")))
    assert other_code.natural_key[3] == base.natural_key[3] and other_code != base          # 同じ DiscNo ・別の record
    assert other_code.reference() != base.reference()
    corrected = ProviderRecordIdentity.of(FinancialSummaryRow.from_provider_mapping(row(Sales="500000000001")))
    assert corrected.natural_key == base.natural_key and corrected.digest != base.digest    # 同じ自然 key ・別の revision
    assert corrected.reference() != base.reference()
    unrelated = ProviderRecordIdentity.of(FinancialSummaryRow.from_provider_mapping(row(DiscTime="15:00:01")))
    assert unrelated.natural_key != base.natural_key
    with pytest.raises(AdapterInputError):
        ProviderRecordIdentity(natural_key=base.natural_key, digest="ab" * 31)


def test_b_unreferenceable_tokens_are_held_not_normalised() -> None:
    result = adapt(row(DiscNo="2025 0512"))
    assert result.status is AdapterStatus.HOLD and "MAPPING_UNSUPPORTED" in reasons(result)
    assert result.provider_record.reference() is None
    assert result.held.provider_record_ref.startswith("jq.fins_summary:unreferenceable:")


# ================================================================ C 知識の時刻


def test_c_timestamp_is_jst_and_date_only_when_time_is_empty() -> None:
    timed = adapt(row(DiscTime="9:05:00")).eligible.knowledge                               # 1 桁の時も受ける
    assert timed.precision is KnowledgePrecision.TIMESTAMP and timed.at == datetime(2025, 5, 12, 9, 5, tzinfo=TOKYO)
    assert timed.at.utcoffset().total_seconds() == 9 * 3600
    dated = adapt(row(DiscTime="")).eligible.knowledge
    assert dated.precision is KnowledgePrecision.DATE and dated.on == date(2025, 5, 12) and dated.at is None


@pytest.mark.parametrize("field,value", [("DiscDate", "2025/05/12"), ("DiscDate", "20250512"),
                                         ("DiscDate", "2025-02-30"), ("DiscDate", ""), ("DiscDate", "2025-5-12"),
                                         ("DiscTime", "25:00:00"),
                                         ("DiscTime", "15:60:00"), ("DiscTime", "15:00"), ("DiscTime", "3pm"),
                                         ("DiscTime", " 15:00:00")])
def test_c_malformed_date_or_time_is_held_and_no_time_is_invented(field: str, value: str) -> None:
    result = adapt(row(**{field: value}))
    assert result.status is AdapterStatus.HOLD and "KNOWLEDGE_TIME_INVALID" in reasons(result)
    assert result.eligible is None and "15:30" not in json.dumps(result.as_dict())


def test_c_disclosure_before_period_end_is_held_as_invalid_knowledge_time() -> None:
    result = adapt(row(DiscDate="2025-03-31"))                                             # 期末の当日 ＝ 知り得ない
    assert result.status is AdapterStatus.HOLD and reasons(result) == ["KNOWLEDGE_TIME_INVALID"]


def test_c_acquisition_time_is_a_separate_axis_and_never_the_knowledge_time() -> None:
    eligible = adapt(row(), CTX_TIMED)
    assert eligible.eligible.knowledge.at == datetime(2025, 5, 12, 15, 0, tzinfo=TOKYO)   # 取得の時刻ではない
    held = adapt(row(DocType="FYFinancialStatements_Consolidated_Foreign"), CTX_TIMED)
    assert held.held.observed_at == at(2026, 6, 30, 12)                                     # 保留の運用の時刻にだけ
    assert adapt(row(DocType="FYFinancialStatements_Consolidated_Foreign")).held.observed_at is None
    with pytest.raises(AdapterInputError):
        AdapterContext(issuer_id=I1, acquired_at=datetime(2026, 6, 30, 12))                  # naive は拒む


# ================================================================ D 期間


@pytest.mark.parametrize("kind", ["4Q", "5Q", "OtherPeriod", "Q1", "", "fy"])
def test_d_unsupported_period_types_are_held(kind: str) -> None:
    result = adapt(row(CurPerType=kind))
    assert result.status is AdapterStatus.HOLD and "PERIOD_UNSUPPORTED" in reasons(result)


@pytest.mark.parametrize("overrides", [
    {"CurPerEn": "2025-03-30"},                                                             # FY なのに期末が年度末でない
    {"CurPerSt": "2024-07-01"},                                                             # 期首が年度初でない
    {"CurPerType": "1Q", "CurPerEn": "2025-03-31"},                                         # 累計なのに年度末
    {"CurFYSt": "2024-04-01", "CurFYEn": "2026-03-31"},                                     # 2 年の年度（550 日超）
    {"CurFYEn": "2024-03-31"},                                                              # 年度末が年度初より前
    {"CurPerSt": "2024-04-1"}, {"CurFYEn": "2025-13-31"}, {"CurPerEn": ""}])
def test_d_inconsistent_or_malformed_period_dates_are_held(overrides: dict) -> None:
    result = adapt(row(**overrides))
    assert result.status is AdapterStatus.HOLD and "PERIOD_UNSUPPORTED" in reasons(result)


def test_d_no_annualisation_interpolation_or_ttm() -> None:
    source = executable_source(PACKAGE_DIR / "jquants_financial_summary_adapter.py").lower()
    for token in ("annual", "ttm", "trailing", "interpol", "* 4", "/ 4", "standalone", "single_quarter"):
        assert token not in source, token


# ================================================================ E 意味 ・pilot の方針


@pytest.mark.parametrize("doc_type", ["FYFinancialStatements_Consolidated_JP", "FYFinancialStatements_Consolidated_US",
                                      "FYFinancialStatements_Consolidated_IFRS",
                                      "FYFinancialStatements_Consolidated_JMIS"])
def test_e_adp0r_the_four_documented_standards_are_eligible_with_provider_contract_jpy_and_scale_one(doc_type) -> None:
    result = adapt(row(DocType=doc_type))
    assert result.status is AdapterStatus.ELIGIBLE and result.reasons == () and result.held is None
    expected = {"JP": AccountingStandard.JP_GAAP, "US": AccountingStandard.US_GAAP, "IFRS": AccountingStandard.IFRS,
                "JMIS": AccountingStandard.JMIS}[doc_type.rsplit("_", 1)[1]]
    assert len(result.eligible.observations) == 4
    for observation, (semantics, provenance) in zip(result.eligible.observations, result.eligible.annotations):
        assert observation.value.state is ValueState.VALUE_PRESENT
        assert observation.value.currency.value == "JPY" and observation.value.scale is Scale.ONE   # provider の契約の正規化
        assert observation.statement_basis is StatementBasis.CONSOLIDATED
        assert semantics.accounting_standard is expected and semantics.semantic_status is SemanticStatus.KNOWN
        assert provenance.doc_type == doc_type
    assert fa.PILOT_ELIGIBLE_STANDARDS == (AccountingStandard.JP_GAAP, AccountingStandard.US_GAAP,
                                           AccountingStandard.IFRS, AccountingStandard.JMIS)
    assert AccountingStandard.UNKNOWN not in fa.PILOT_ELIGIBLE_STANDARDS and len(fa.PILOT_ELIGIBLE_STANDARDS) == 4


def test_e_adp0r_currency_unknown_is_no_longer_emitted_merely_for_a_documented_non_jp_standard() -> None:
    for doc_type in ("FYFinancialStatements_Consolidated_US", "FYFinancialStatements_Consolidated_IFRS",
                     "FYFinancialStatements_Consolidated_JMIS"):
        held = adapt(row(DocType=doc_type, Sales="1,000"))                       # 他の理由で保留しても通貨 ・基準の理由は無い
        assert reasons(held) == ["VALUE_UNPARSEABLE"]
    non_consolidated = adapt(row(DocType="FYFinancialStatements_NonConsolidated_IFRS"))
    assert reasons(non_consolidated) == ["STATEMENT_BASIS_UNKNOWN"]             # 区分の規則は凍結のまま（d2 の 4 値だけ）
    for undocumented in ("FYFinancialStatements_NonConsolidated_US", "FYFinancialStatements_NonConsolidated_JMIS"):
        assert "DOCTYPE_UNRECOGNIZED" in reasons(adapt(row(DocType=undocumented)))   # 公式の表に無い → fail closed


@pytest.mark.parametrize("doc_type,expected", [
    ("FYFinancialStatements_Consolidated_Foreign", ["ACCOUNTING_STANDARD_UNKNOWN", "CURRENCY_UNKNOWN"]),
    ("FYFinancialStatements_NonConsolidated_Foreign", ["ACCOUNTING_STANDARD_UNKNOWN", "STATEMENT_BASIS_UNKNOWN",
                                                       "CURRENCY_UNKNOWN"]),
    ("OtherPeriodFinancialStatements_NonConsolidated_JP", ["STATEMENT_BASIS_UNKNOWN", "PERIOD_UNSUPPORTED"]),
    ("FYFinancialStatements_Consolidated_REIT", ["ACCOUNTING_STANDARD_UNKNOWN", "STATEMENT_BASIS_UNKNOWN",
                                                 "DOCTYPE_OUT_OF_SCOPE", "CURRENCY_UNKNOWN"]),
    ("EarnForecastRevision", ["ACCOUNTING_STANDARD_UNKNOWN", "STATEMENT_BASIS_UNKNOWN", "DOCTYPE_OUT_OF_SCOPE",
                              "CURRENCY_UNKNOWN"]),
    ("FYFinancialStatements_Consolidated_KOREA", ["ACCOUNTING_STANDARD_UNKNOWN", "STATEMENT_BASIS_UNKNOWN",
                                                  "DOCTYPE_UNRECOGNIZED", "CURRENCY_UNKNOWN"]),
    ("fyfinancialstatements_consolidated_jp", ["ACCOUNTING_STANDARD_UNKNOWN", "STATEMENT_BASIS_UNKNOWN",
                                               "DOCTYPE_UNRECOGNIZED", "CURRENCY_UNKNOWN"])])
def test_e_unknown_standards_and_unrecognised_doctypes_are_held_with_typed_reasons(doc_type, expected) -> None:
    overrides = {"DocType": doc_type}
    if doc_type.startswith("OtherPeriod"):
        overrides["CurPerType"] = "OtherPeriod"
    result = adapt(row(**overrides))
    assert result.status is AdapterStatus.HOLD and reasons(result) == expected
    assert result.held.reasons == result.reasons and result.eligible is None


def test_e_the_adapter_reuses_the_frozen_a2r_mapping_and_never_parses_doctype_itself() -> None:
    source = (PACKAGE_DIR / "jquants_financial_summary_adapter.py").read_text(encoding="utf-8")
    assert "map_row_semantics(" in source and "derive_observation_semantics(" in source
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute):
            assert node.attr not in {"split", "rsplit", "partition", "endswith", "startswith", "find", "lower",
                                     "upper", "strip"}, node.attr
    executable = ast.parse(executable_source(PACKAGE_DIR / "jquants_financial_summary_adapter.py"))
    for node in ast.walk(executable):                                            # DocType の token を文字列で持たない
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            assert not any(token in node.value for token in ("IFRS", "JMIS", "_JP", "_US", "Foreign", "REIT")), \
                node.value
    assert fa.PILOT_ELIGIBLE_STANDARDS == (AccountingStandard.JP_GAAP, AccountingStandard.US_GAAP,
                                           AccountingStandard.IFRS, AccountingStandard.JMIS)


def test_e_unsupported_nonconsolidated_combinations_are_not_broadened() -> None:
    held = adapt(row(DocType="FYFinancialStatements_NonConsolidated_Foreign"))
    assert "STATEMENT_BASIS_UNKNOWN" in reasons(held) and "ACCOUNTING_STANDARD_UNKNOWN" in reasons(held)
    assert adapt(row(DocType="FYFinancialStatements_NonConsolidated_JP")).status is AdapterStatus.ELIGIBLE
    assert adapt(quarterly("1Q", DocType="1QFinancialStatements_NonConsolidated_JP")).status is AdapterStatus.ELIGIBLE


# ================================================================ F identity の境界


def test_f_unresolved_identity_is_held_and_code_never_becomes_an_identity() -> None:
    result = adapt(row(), AdapterContext())
    assert result.status is AdapterStatus.HOLD and reasons(result) == ["IDENTITY_UNRESOLVED"]
    assert result.held.issuer_id == "" and result.held.security_id == ""
    assert not is_issuer_id(BASE["Code"]) and not is_security_id(BASE["Code"])
    for value in ("00010", "p8iss_00010", "iss:00010"):
        held = adapt(row(), AdapterContext(issuer_id=value))
        assert held.status is AdapterStatus.HOLD and "IDENTITY_UNRESOLVED" in reasons(held)
    text = json.dumps(adapt(row()).as_dict())
    assert "p8iss_" in text and BASE["Code"] not in adapt(row()).eligible.issuer_id
    for name in ("jquants_adapter_model", "jquants_financial_summary_adapter"):
        source = (PACKAGE_DIR / f"{name}.py").read_text(encoding="utf-8")
        assert "derive_issuer_id" not in source and "derive_security_id" not in source
        assert "IssuerRegistration" not in source and "SecurityRegistration" not in source
    with pytest.raises(AdapterInputError):
        adapt_financial_summary_row(row(), {"issuer_id": I1})                                # 文脈は型つきだけ


def test_f_resolved_identity_is_carried_into_held_material_when_available() -> None:
    held = adapt(row(DocType="FYFinancialStatements_Consolidated_Foreign"))
    assert held.held.issuer_id == I1 and held.held.attempted_statement_basis is StatementBasis.CONSOLIDATED
    assert held.held.provider_record_digest == held.provider_record.digest
    assert held.held.provider_record_ref == held.provider_record.reference()
    assert isinstance(held.held, HeldObservation) and held.held.record_id.startswith("p8hld_")


# ================================================================ G 値


@pytest.mark.parametrize("text,amount", [("500000000000", "500000000000"), ("-123", "-123"), ("0", "0"),
                                         ("12.50", "12.5"), ("-0.5", "-0.5")])
def test_g_valid_values_are_canonical_decimals(text: str, amount: str) -> None:
    result = adapt(row(NP=text))
    assert result.status is AdapterStatus.ELIGIBLE
    assert result.eligible.observations[2].value.amount == amount


@pytest.mark.parametrize("text", [" 100", "100 ", "1,000", "1e5", "1E5", "NaN", "nan", "Infinity", "-Infinity", "+100",
                                  "--1", "1.", ".5", "01", "１００", "100円", "-", "0x10", "1_000"])
def test_g_malformed_values_are_held_never_normalised(text: str) -> None:
    result = adapt(row(Sales=text))
    assert result.status is AdapterStatus.HOLD and reasons(result) == ["VALUE_UNPARSEABLE"]
    assert result.eligible is None


def test_g_empty_is_distinct_from_zero_and_never_becomes_zero() -> None:
    empty = adapt(row(Sales="")).eligible.observations[0]
    zero = adapt(row(Sales="0")).eligible.observations[0]
    assert empty.value.state is ValueState.NOT_REPORTED and zero.value.amount == "0"
    assert empty.record_id != zero.record_id


# ================================================================ H 入力の契約 ・architecture


def test_h_strict_input_contract() -> None:
    with pytest.raises(AdapterInputError) as info:
        FinancialSummaryRow.from_provider_mapping({**row(), "Payload": "x"})
    assert info.value.code == "PROVIDER_FIELD_UNKNOWN"
    with pytest.raises(AdapterInputError) as info:
        FinancialSummaryRow.from_provider_mapping({k: v for k, v in row().items() if k != "TA"})
    assert info.value.code == "PROVIDER_FIELD_MISSING" and info.value.detail == "TA"
    with pytest.raises(AdapterInputError) as info:
        FinancialSummaryRow.from_provider_mapping(row(Sales=500000000000))
    assert info.value.code == "PROVIDER_VALUE_NOT_TEXT"
    with pytest.raises(AdapterInputError) as info:
        FinancialSummaryRow.from_provider_mapping(row(Sales="x" * 65))
    assert info.value.code == "PROVIDER_VALUE_OUT_OF_BOUNDS"
    with pytest.raises(AdapterInputError):
        FinancialSummaryRow.from_provider_mapping("not a mapping")
    with pytest.raises(AdapterInputError) as info:
        FinancialSummaryRow.from_provider_mapping(row(DocType="apikey"))
    assert info.value.code == "CREDENTIAL_LIKE_TEXT"
    parsed = FinancialSummaryRow.from_provider_mapping({**row(), "NxtFYSt": "2025-04-01", "OdP": "1", "ROE": "0.1"})
    assert set(parsed.supported_values()) == set(am.SUPPORTED_FIELDS) and not hasattr(parsed, "OdP")   # 他の欄は捨てる
    assert len(am.OFFICIAL_FINS_SUMMARY_FIELDS) == 111 and len(set(am.OFFICIAL_FINS_SUMMARY_FIELDS)) == 111
    assert set(am.SUPPORTED_FIELDS) <= set(am.OFFICIAL_FINS_SUMMARY_FIELDS) and len(am.SUPPORTED_FIELDS) == 14


def test_h_result_is_derived_non_persistent_and_carries_no_raw_row() -> None:
    result = adapt(row())
    text = json.dumps(result.as_dict())
    assert not {"raw", "payload", "row", "response_body", "api_response"} & set(result.as_dict())
    assert not {"raw", "payload", "row", "response_body"} & {f.name for f in fields(AdapterResult)}
    without_key = json.dumps({**result.as_dict(), "provider_record": None})
    for provider_field in ("CurFYSt", "CurFYEn", "CurPerSt", "CurPerEn", "CurPerType", "DiscNo", "DiscDate",
                           "DiscTime", "Code", "Sales", "OP", "NP", "TA"):
        assert f'"{provider_field}":' not in without_key, provider_field                    # 元の行は出力に無い（欄の key）
    assert result.as_dict()["provider_record"]["natural_key"]["DiscNo"] == BASE["DiscNo"]     # 自然 key だけ
    assert not hasattr(result, "record_id") and not hasattr(result, "canonical_line")
    with pytest.raises(FrozenInstanceError):
        result.status = AdapterStatus.HOLD                                                  # type: ignore[misc]
    assert result == adapt(row()) and result.as_dict() == adapt(row()).as_dict()            # 決定論
    with pytest.raises(AdapterInputError):
        AdapterResult(status=AdapterStatus.ELIGIBLE, provider_record=result.provider_record,
                      reasons=(HeldReason.CURRENCY_UNKNOWN,), eligible=result.eligible)


@pytest.mark.parametrize("name", ["jquants_adapter_model", "jquants_financial_summary_adapter"])
def test_h_no_store_append_filesystem_network_clock_random_uuid_llm_or_metrics(name: str) -> None:
    path = PACKAGE_DIR / f"{name}.py"
    source = path.read_text(encoding="utf-8")
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            assert node.module not in {"time", "uuid", "random", "secrets", "os", "sys", "socket", "pathlib",
                                       "json", "sqlite3"}, (name, node.module)
            assert not any(token in node.module for token in (
                "store", "resolver", "metric", "fundamental_metrics", "market", "jquants_v2", "ingestion", "themes",
                "narrative", "pages", "reports", "urllib", "requests", "identity_correction")), (name, node.module)
        if isinstance(node, ast.Import):
            assert not any(alias.name in ("os", "sys", "time", "random", "uuid", "socket", "urllib", "pathlib",
                                          "sqlite3", "json") for alias in node.names), name
        if isinstance(node, ast.Name):
            assert node.id not in {"open", "Path", "os", "print", "float", "eval", "exec"}, (name, node.id)
        if isinstance(node, ast.Attribute):
            assert node.attr not in {"now", "utcnow", "today", "append", "write", "urlopen", "uuid4", "random",
                                     "chains", "coverages"}, (name, node.attr)
        if isinstance(node, ast.Constant):
            assert not isinstance(node.value, float)
    lowered = executable_source(path).lower()
    for token in ("screen", "rank", "score", "recommend", "theme", "llm", "prompt", "anthropic", "sqlite",
                  "production", "calibration", "x-api-key", "://", "15:30"):
        assert token not in lowered, (name, token)
    assert "def adapt_financial_summary_row" in source or name == "jquants_adapter_model"
