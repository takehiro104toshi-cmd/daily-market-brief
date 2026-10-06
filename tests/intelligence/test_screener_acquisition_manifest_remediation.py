"""P8-EPOCH1R — 保留 ／ 記載なしの manifest entry の期間 ・区分の metadata（R-B）と ADP0 の公開 helper の test。

境界 ／ 凍結の guard は `test_screener_intelligence_boundary.py`。
すべて合成。network ・時計 ・実データ ・LLM ・raw の応答は使わない。F1 ・ProviderHoldingsCoverage ・遡及の解決の変更は無い。
"""
from __future__ import annotations

import ast
import json
import re
from dataclasses import replace
from datetime import date
from pathlib import Path

import pytest

from src.intelligence.screener_intelligence import acquisition_manifest_builder as mb
from src.intelligence.screener_intelligence import acquisition_manifest_model as mm
from src.intelligence.screener_intelligence import jquants_financial_summary_adapter as adapter
from src.intelligence.screener_intelligence.acquisition_manifest_model import (AcquisitionManifest,
                                                                               ManifestDisposition, ManifestEntry,
                                                                               ManifestExecution)
from src.intelligence.screener_intelligence.acquisition_manifest_store import AppendStatus, ManifestStore
from src.intelligence.screener_intelligence.held_observation_store import HeldObservationStore
from src.intelligence.screener_intelligence.jquants_adapter_model import AdapterContext, AdapterInputError
from src.intelligence.screener_intelligence.jquants_financial_summary_adapter import derive_reporting_period
from src.intelligence.screener_intelligence.observation_model import PeriodBasis, ReportingPeriod, StatementBasis
from tests.intelligence.phase8_runtime_registry import PHASE8_PACKAGE
from tests.intelligence.test_prediction_record import executable_source
from tests.intelligence.test_screener_acquisition_manifest import (ACQ1, CTX1, CTX2, I1, KOREA, build, built, execute,
                                                                   fins_event)
from tests.intelligence.test_screener_acquisition_manifest import root as manifest_root  # noqa: F401  fixture
from tests.intelligence.test_screener_jquants_adapter import quarterly, row
from tests.intelligence.test_screener_jquants_execution import FOREIGN

REPO_ROOT = Path(__file__).resolve().parents[2]
PACKAGE_DIR = REPO_ROOT / PHASE8_PACKAGE
D = ManifestDisposition
X = ManifestExecution
CONS = StatementBasis.CONSOLIDATED
FY = ReportingPeriod(PeriodBasis.FISCAL_YEAR, date(2024, 4, 1), date(2025, 3, 31), date(2024, 4, 1), date(2025, 3, 31))
REIT = "FYFinancialStatements_Consolidated_REIT"
OTHER_NC = "OtherPeriodFinancialStatements_NonConsolidated_JP"
IFRS = "FYFinancialStatements_Consolidated_IFRS"


@pytest.fixture
def root(manifest_root: Path) -> Path:
    return manifest_root


def entry_of(root: Path, mapping: dict, context: AdapterContext = CTX1) -> ManifestEntry:
    manifest = built(root, [mapping], context)
    assert manifest.entry_count == 1
    return manifest.entries[0]


# ================================================================ A ADP0 の公開 helper（凍結の導出と同値）


@pytest.mark.parametrize("mapping,expected_end,expected_basis,quarter", [
    (row(), date(2025, 3, 31), PeriodBasis.FISCAL_YEAR, 0),
    (quarterly("1Q"), date(2024, 6, 30), PeriodBasis.CUMULATIVE_YEAR_TO_DATE, 1),
    (quarterly("2Q"), date(2024, 9, 30), PeriodBasis.CUMULATIVE_YEAR_TO_DATE, 2),
    (quarterly("3Q"), date(2024, 12, 31), PeriodBasis.CUMULATIVE_YEAR_TO_DATE, 3)])
def test_a_the_public_helper_equals_the_frozen_period_derivation_for_supported_periods(mapping, expected_end,
                                                                                       expected_basis, quarter) -> None:
    period = derive_reporting_period(mapping)
    assert period == adapter._period(adapter.FinancialSummaryRow.from_provider_mapping(mapping))   # 同値（委譲）
    assert period.period_end == expected_end and period.basis is expected_basis and period.quarter == quarter
    assert derive_reporting_period(adapter.FinancialSummaryRow.from_provider_mapping(mapping)) == period


@pytest.mark.parametrize("mapping", [
    row(CurPerType="4Q"), row(CurPerType="2Q"), row(CurPerSt="2024-05-01"), row(CurPerEn="2025-13-01"),
    row(CurFYEn=""), quarterly("1Q", CurPerEn="2025-03-31"), row(CurPerEn="2025-3-31"), row(CurFYSt="2024/04/01")])
def test_a_the_public_helper_returns_none_exactly_where_the_frozen_derivation_does(mapping) -> None:
    assert derive_reporting_period(mapping) is None
    assert adapter._period(adapter.FinancialSummaryRow.from_provider_mapping(mapping)) is None
    assert adapter.adapt_financial_summary_row(mapping, CTX1).status.value == "HOLD"
    assert "PERIOD_UNSUPPORTED" in [r.value for r in adapter.adapt_financial_summary_row(mapping, CTX1).reasons]


def test_a_the_public_helper_is_pure_and_changes_nothing_else_in_the_adapter() -> None:
    with pytest.raises(AdapterInputError):
        derive_reporting_period({"Code": "00010"})                                           # 契約の違反はそのまま
    for mapping in (row(Sales="1,000"), row(DocType=KOREA), row(DocType=FOREIGN), row(DiscTime="25:00:00")):
        assert derive_reporting_period(mapping) == FY                                        # 保留の理由に依らない
    source = executable_source(PACKAGE_DIR / "jquants_financial_summary_adapter.py")
    helper = source.split("def derive_reporting_period")[1].split("\ndef ")[0]
    assert "return _period(parsed)" in helper and "now(" not in helper and "today(" not in helper
    assert adapter.__all__[-1] == "derive_reporting_period" and len(adapter.__all__) == 5
    tree = ast.parse((PACKAGE_DIR / "jquants_financial_summary_adapter.py").read_text(encoding="utf-8"))
    period_def = next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == "_period")
    assert "SUPPORTED_PERIOD_TYPES" in ast.dump(period_def)                                  # 凍結の算法はそのまま 1 つ


# ================================================================ B model（CANONICAL は不変 ・非 canonical は任意）


def test_b_canonical_invariants_are_unchanged_and_non_canonical_metadata_is_optional() -> None:
    ref = f"jq.fins_summary:00010.20250512000001.FYFinancialStatements_Consolidated_JP:{'a' * 24}"
    with pytest.raises(mm.ManifestModelError) as exc:
        ManifestEntry(provider_record_ref=ref, provider_record_digest="a" * 64, disposition=D.CANONICAL,
                      execution_outcome=X.MATERIALIZED, fields=((mm.FundamentalField.REVENUE, "p8obs_" + "b" * 24),))
    assert exc.value.code == "CANONICAL_REQUIRES_PERIOD"
    held_known = ManifestEntry(provider_record_ref=ref, provider_record_digest="a" * 64, disposition=D.HELD_SEMANTIC,
                               execution_outcome=X.HELD, held_record_id="p8hld_" + "c" * 24, period=FY,
                               statement_basis=CONS)
    held_unknown = replace(held_known, period=None, statement_basis=None)
    unsupported = replace(held_known, disposition=D.UNSUPPORTED, statement_basis=None)
    not_reported = ManifestEntry(provider_record_ref=ref, provider_record_digest="a" * 64,
                                 disposition=D.NOT_REPORTED_ONLY, execution_outcome=X.NO_REPORTED_FIELDS, period=FY,
                                 statement_basis=CONS)
    for entry in (held_known, held_unknown, unsupported, not_reported):
        assert ManifestEntry.from_dict(entry.as_dict()) == entry and entry.fields == ()
    assert held_known.period_known and not held_unknown.period_known and unsupported.period_known
    assert held_known.contaminates_absence and unsupported.contaminates_absence
    assert not not_reported.contaminates_absence and not_reported.period_known
    assert held_unknown.as_dict()["period"] is None and held_unknown.as_dict()["statement_basis"] is None
    assert [d.value for d in D] == ["CANONICAL", "HELD_SEMANTIC", "NOT_REPORTED_ONLY", "UNSUPPORTED"]  # 語彙は不変
    assert mm.MANIFEST_SCHEMA_VERSION == "p8_acquisition_manifest:0.2.0"
    assert mm.MANIFEST_RULES_VERSION == "p8_acquisition_manifest_authority:0.2.0"
    assert mb.BUILDER_RULES_VERSION == "p8_acquisition_manifest_builder:0.2.0"


# ================================================================ C builder（保留の理由ごとの期間 ・区分）


@pytest.mark.parametrize("mapping,disposition,period,basis,reasons", [
    (row(Sales="1,000"), D.UNSUPPORTED, FY, CONS, ["VALUE_UNPARSEABLE"]),
    (row(DocType=KOREA), D.UNSUPPORTED, FY, None, ["ACCOUNTING_STANDARD_UNKNOWN", "STATEMENT_BASIS_UNKNOWN",
                                                   "DOCTYPE_UNRECOGNIZED", "CURRENCY_UNKNOWN"]),
    (row(DocType=REIT), D.UNSUPPORTED, FY, None, ["ACCOUNTING_STANDARD_UNKNOWN", "STATEMENT_BASIS_UNKNOWN",
                                                  "DOCTYPE_OUT_OF_SCOPE", "CURRENCY_UNKNOWN"]),
    (row(CurPerType="4Q"), D.UNSUPPORTED, None, CONS, ["PERIOD_UNSUPPORTED"]),
    (row(CurPerSt="2024-05-01"), D.UNSUPPORTED, None, CONS, ["PERIOD_UNSUPPORTED"]),
    (row(DocType=FOREIGN), D.HELD_SEMANTIC, FY, CONS, ["ACCOUNTING_STANDARD_UNKNOWN", "CURRENCY_UNKNOWN"]),
    (row(DocType=OTHER_NC), D.HELD_SEMANTIC, FY, None, ["STATEMENT_BASIS_UNKNOWN"]),
    (row(DocType=OTHER_NC, CurPerType="4Q"), D.UNSUPPORTED, None, None, ["STATEMENT_BASIS_UNKNOWN",
                                                                         "PERIOD_UNSUPPORTED"]),
    (row(DiscTime="25:00:00"), D.UNSUPPORTED, FY, CONS, ["KNOWLEDGE_TIME_INVALID"]),
    (row(DiscDate="2025-03-01"), D.UNSUPPORTED, FY, CONS, ["KNOWLEDGE_TIME_INVALID"])])
def test_c_held_rows_carry_period_and_basis_exactly_when_frozen_adp0_established_them(root: Path, mapping, disposition,
                                                                                      period, basis, reasons) -> None:
    results = execute(root, [mapping])
    assert results[0].outcome.value == "HELD" and [r.value for r in results[0].held_reasons] == reasons
    entry = entry_of(root, mapping)
    assert entry.disposition is disposition and entry.execution_outcome is X.HELD and entry.fields == ()
    assert entry.period == period and entry.statement_basis is basis
    assert entry.period_known is (period is not None) and entry.contaminates_absence
    held = HeldObservationStore.open(root, read_only=True).get(entry.held_record_id)
    assert held.attempted_statement_basis is basis                                           # 区分は保留 record と同じ源
    assert ("PERIOD_UNSUPPORTED" in reasons) == (period is None)                               # 理由と metadata の整合
    assert ("STATEMENT_BASIS_UNKNOWN" in reasons) == (basis is None)


def test_c_semantic_chain_conflict_hold_keeps_period_and_basis(root: Path) -> None:
    built(root, [row()], CTX1)                                                                 # JP の FY が先
    entry = entry_of(root, row(DocType=IFRS, DiscNo="20250512000002"))                        # 同じ期間に IFRS → 鎖の不連続
    assert entry.disposition is D.HELD_SEMANTIC and entry.period == FY and entry.statement_basis is CONS
    results = execute(root, [row(DocType=IFRS, DiscNo="20250512000002")])
    assert [r.value for r in results[0].held_reasons] == ["SEMANTIC_CHAIN_CONFLICT"]


def test_c_not_reported_only_rows_keep_their_deterministic_period_and_basis(root: Path) -> None:
    empty = row(Sales="", OP="", NP="", TA="")
    results = execute(root, [empty])
    assert results[0].outcome.value == "NO_REPORTED_FIELDS"
    entry = entry_of(root, empty)
    assert entry.disposition is D.NOT_REPORTED_ONLY and entry.period == FY and entry.statement_basis is CONS
    assert entry.period_known and not entry.contaminates_absence and entry.fields == () and entry.held_record_id == ""
    quarter = entry_of(root, quarterly("1Q", Sales="", OP="", NP="", TA=""))
    assert quarter.period.quarter == 1 and quarter.period.period_end == date(2024, 6, 30)


def test_c_metadata_that_contradicts_the_frozen_held_reasons_is_rejected(root: Path) -> None:
    held_row = row(DocType=FOREIGN)
    results = execute(root, [held_row])
    held_store = HeldObservationStore.open(root, read_only=True)
    original = held_store.get(results[0].held_record_id)

    class View:                                                                               # 保留 record の区分を偽る像
        def __init__(self, record):
            self.record = record

        def get(self, record_id):
            return self.record if record_id == original.record_id else None

    forged_basis = replace(original, attempted_statement_basis=None)                        # STATEMENT_BASIS_UNKNOWN 無しで None
    result = build(root, [held_row], results, held=View(forged_basis))
    assert result.outcome.value == "ENTRY_INVALID" and result.failure_code in ("HELD_RECORD_MISMATCH",
                                                                               "HELD_BASIS_INCONSISTENT")
    good = build(root, [held_row], results)
    assert good.outcome.value == "BUILT" and good.manifest.entries[0].period == FY
    unsupported_row = row(CurPerType="4Q")
    results_4q = execute(root, [unsupported_row])
    mismatch = build(root, [row(CurPerType="4Q", DiscNo="20250512000009")], results_4q,
                     event=fins_event([row(CurPerType="4Q", DiscNo="20250512000009")]))
    assert mismatch.outcome.value == "ENTRY_INVALID" and mismatch.failure_code == "PROVIDER_RECORD_MISMATCH"


def test_c_mapping_unsupported_rows_cannot_enter_a_manifest_at_all(root: Path) -> None:
    bad_token = row(DocType="FY.Financial")                                                    # 参照の token の形の外
    results = execute(root, [bad_token])
    assert "MAPPING_UNSUPPORTED" in [r.value for r in results[0].held_reasons]
    assert derive_reporting_period(bad_token) == FY                                            # 期間は導けるが
    result = build(root, [bad_token], results)
    assert result.outcome.value == "ENTRY_INVALID" and result.failure_code == "PROVIDER_REF_UNREFERENCEABLE"


def test_c_unknown_period_is_an_explicit_none_not_a_sentinel(root: Path) -> None:
    entry = entry_of(root, row(CurPerType="4Q"))
    line = built(root, [row(CurPerType="4Q", DiscNo="20250512000002")], CTX2).canonical_line()
    data = json.loads(line)["entries"][0]
    assert entry.period is None and data["period"] is None
    for forbidden in ("2025-03-31", "2026-10", "2025-05-12", "fiscal_year_end"):
        assert forbidden not in json.dumps(data["period"])                                    # 日付の番兵は無い


# ================================================================ D provider の修正 ・id ・store


def test_d_provider_fix_epoch1_held_at_p_and_epoch2_canonical_at_p_are_separate_immutable_manifests(root: Path) -> None:
    broken = row(Sales="1,000")
    e1 = built(root, [broken], CTX1)
    assert [e.disposition for e in e1.entries] == [D.UNSUPPORTED] and e1.entries[0].period == FY
    fixed = row(Sales="1000")                                                                  # provider の修正（内容だけ違う）
    e2 = built(root, [fixed], CTX2)
    assert [e.disposition for e in e2.entries] == [D.CANONICAL] and e2.entries[0].period == FY
    assert e2.canonical_observation_count == 4 and e1.canonical_observation_count == 0
    assert e1.entries[0].provider_record_ref.rpartition(":")[0] == e2.entries[0].provider_record_ref.rpartition(":")[0]
    store = ManifestStore.open(root)
    assert store.append(e1).status is AppendStatus.APPENDED and store.append(e2).status is AppendStatus.APPENDED
    assert store.by_acquisition(e1.acquisition_ref) == e1 and store.by_acquisition(e1.acquisition_ref).entries[0].held_record_id


def test_d_record_ids_are_deterministic_and_held_metadata_participates(root: Path) -> None:
    one = built(root, [row(DocType=FOREIGN)], CTX1)
    again = built(root, [row(DocType=FOREIGN)], CTX1)
    assert one == again and one.record_id == again.record_id
    stripped = replace(one, entries=(replace(one.entries[0], period=None, statement_basis=None),))
    assert stripped.record_id != one.record_id                                                 # metadata は identity の一部
    store = ManifestStore.open(root)
    assert store.append(one).status is AppendStatus.APPENDED and store.append(again).status is AppendStatus.REUSED
    with pytest.raises(Exception) as exc:
        store.append(stripped)                                                                 # 同じ取得 ・違う manifest
    assert getattr(exc.value, "code", "") == "MANIFEST_CONFLICT"
    reopened = ManifestStore.open(root, read_only=True)
    assert reopened.records() == (one,) and reopened.get(one.record_id).entries[0].period == FY
    text = (root / "screener_intelligence" / "acquisition_manifests.jsonl").read_text(encoding="utf-8")
    assert '"schema_version":"p8_acquisition_manifest:0.2.0"' in text
    for forbidden in ("500000000000", "Sales", "合成", "Synth", "apikey", "token", "Bearer", "://", "DiscDate"):
        assert forbidden not in text, forbidden                                               # privacy は変わらない
    assert AcquisitionManifest.from_dict(json.loads(text)) == one


def test_d_no_f1_no_holdings_coverage_no_resolver_change_no_clock() -> None:
    for name in ("acquisition_manifest_model", "acquisition_manifest_builder", "jquants_financial_summary_adapter"):
        lowered = executable_source(PACKAGE_DIR / f"{name}.py").lower()
        for token in ("providerholdings", "holdings_as_of", "complete_through", "coverage(", "resolve_retrospective",
                      "now(", "today(", "utcnow", "urllib", "socket", "://"):
            assert token not in lowered, (name, token)
    assert "derive_reporting_period" in (PACKAGE_DIR / "acquisition_manifest_builder.py").read_text(encoding="utf-8")
    builder = executable_source(PACKAGE_DIR / "acquisition_manifest_builder.py")
    assert re.search(r"(?<![a-z_])_period\(", builder) is None                                  # 私的名は使わない
