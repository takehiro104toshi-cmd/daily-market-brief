"""P8-A3-RA — 遡及の provider authority の上の 4 指標（`retrospective_metric_resolver`）の test。

凍結 A3 の式は `fundamental_metrics` の純 helper がそのまま持つ（監督の決定 R1）。本 test は (A) 注記の parity、(B) 4 指標の値、
(C〜F) 失敗の語彙 ・authority の失敗 ・epoch の規律、(G) provider の修正 ・再取得 ・訂正、(H) provenance ・非永続 ・STRICT の孤立を pin する。
すべて合成。network ・時計 ・実データ ・LLM ・raw の応答 ・credential は使わない。
"""
from __future__ import annotations

import ast
from dataclasses import FrozenInstanceError, replace
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pytest

from src.intelligence.screener_intelligence import fundamental_metrics as fm
from src.intelligence.screener_intelligence import retrospective_metric_resolver as rm
from src.intelligence.screener_intelligence.acquisition_manifest_store import ManifestStore
from src.intelligence.screener_intelligence.identity_correction_model import CorrectionHistory
from src.intelligence.screener_intelligence.metric_model import MetricKind, MetricLeg, MetricStatus, ReasonCode
from src.intelligence.screener_intelligence.observation_model import (FundamentalField, ObservationHistory,
                                                                      ObservationModelError, ReportingPeriod,
                                                                      StatementBasis)
from src.intelligence.screener_intelligence.observation_resolver import ObservationQuery, ObservationStatus
from src.intelligence.screener_intelligence.observation_semantics_mapping import derive_observation_semantics
from src.intelligence.screener_intelligence.observation_semantics_model import FieldFamily
from src.intelligence.screener_intelligence.observation_store import ObservationAppendRejected, ObservationStore
from src.intelligence.screener_intelligence.provider_holdings_store import HoldingsAppendRejected, ProviderHoldingsStore
from src.intelligence.screener_intelligence.retrospective_metric_resolver import (RetrospectiveMetricResult,
                                                                                 RetrospectiveMetricStatus,
                                                                                 resolve_retrospective_metric)
from src.intelligence.screener_intelligence.semantic_metadata_store import SemanticMetadataStore
from tests.intelligence.phase8_runtime_registry import PHASE8_PACKAGE
from tests.intelligence.test_prediction_record import executable_source
from tests.intelligence.test_screener_acquisition_manifest import ACQ1, ACQ2, CTX1, CTX2, I1, IDS, built
from tests.intelligence.test_screener_acquisition_manifest import root as manifest_root  # noqa: F401  fixture
from tests.intelligence.test_screener_fundamental_metrics import (C_2025_06, C_2026_06, FY24, LONG_FY, SINGLE_Q2_25,
                                                                   World)
from tests.intelligence.test_screener_jquants_adapter import quarterly, row
from tests.intelligence.test_screener_observation_retrospective import P_FY, history_of, holdings_store
from tests.intelligence.test_screener_provider_holdings_executor import NC_BROKEN, NC_FIXED, acquire, produce
from tests.intelligence.test_screener_provider_holdings_executor import run as run_f1

REPO_ROOT = Path(__file__).resolve().parents[2]
PACKAGE_DIR = REPO_ROOT / PHASE8_PACKAGE
JST = timezone(timedelta(hours=9))
R = RetrospectiveMetricStatus
S = ObservationStatus
K = MetricKind
F = FundamentalField
CONS, NC = StatementBasis.CONSOLIDATED, StatementBasis.NON_CONSOLIDATED
ACQ3 = ACQ2 + timedelta(days=7)
CTX3 = replace(CTX2, acquired_at=ACQ3)
IFRS = "FYFinancialStatements_Consolidated_IFRS"
FOREIGN = "FYFinancialStatements_Consolidated_Foreign"
JP_NONCONS = "FYFinancialStatements_NonConsolidated_JP"
#: 前年度（FY2023）の合成の行。売上 4000 億 → 当年度 5000 億で成長率 0.25
PRIOR_FY = row(CurPerSt="2023-04-01", CurPerEn="2024-03-31", CurFYSt="2023-04-01", CurFYEn="2024-03-31",
               DiscDate="2024-05-13", DiscNo="20240513000001", Sales="400000000000", OP="30000000000",
               NP="20000000000", TA="800000000000")
#: 前年度の 1Q 累計（FY2023 1Q）。売上 1000 億 → 当年度 1Q 累計 5000 億（BASE）で成長率 4
PRIOR_1Q = row(CurPerType="1Q", CurPerSt="2023-04-01", CurPerEn="2023-06-30", CurFYSt="2023-04-01",
               CurFYEn="2024-03-31", DocType="1QFinancialStatements_Consolidated_JP", DiscDate="2023-08-08",
               DiscNo="20230808000001", Sales="100000000000", OP="8000000000", NP="6000000000", TA="700000000000")
CORRECTED = row(DiscNo="20250512000005", DiscDate="2025-05-20", Sales="400000000000")        # 同じ期間の訂正（別 DiscNo）
ZERO_SALES = row(Sales="0")
NEGATIVE_SALES = row(Sales="-5")
_DEFAULT = object()                                                                              # 「省いた」と None を区別する


@pytest.fixture
def root(manifest_root: Path) -> Path:
    ProviderHoldingsStore.initialize(manifest_root)
    return manifest_root


def semantics_of(root: Path) -> dict:
    """A2R の注記の lookup（凍結 A3 と同じ契約: 観測 id → `ObservationSemantics`）。semantic store から読む。"""
    store = SemanticMetadataStore.open(root, read_only=True)
    lookup = {}
    for record in history_of(root).records:
        if record.KIND.value == "FUNDAMENTAL_ACTUAL" and store.semantics_for(record.record_id) is not None:
            lookup[record.record_id] = store.semantics_for(record.record_id)
    return lookup


def period_of(root: Path, manifest, entry: int = 0) -> ReportingPeriod:
    return history_of(root).get(manifest.entries[entry].observation_ids[0]).period


def metric(root: Path, kind: K, target, authority, *, comparison=None, basis=CONS, subject=I1,
           identity_valid_at=None, history=_DEFAULT, manifests=_DEFAULT, corrections=_DEFAULT, holdings=_DEFAULT,
           semantics=_DEFAULT) -> RetrospectiveMetricResult:
    return resolve_retrospective_metric(
        kind, history if history is not _DEFAULT else history_of(root), subject_id=subject, statement_basis=basis,
        target_period=target, comparison_period=comparison, authority_as_of=authority,
        identity_valid_at=identity_valid_at or authority,
        manifests=manifests if manifests is not _DEFAULT else ManifestStore.open(root, read_only=True),
        corrections=corrections if corrections is not _DEFAULT else CorrectionHistory(IDS.history()),
        holdings=holdings if holdings is not _DEFAULT else holdings_store(root),
        semantics=semantics if semantics is not _DEFAULT else semantics_of(root))


def fy_epoch(root: Path, rows=None, context=CTX2):
    """当年度の epoch（既定: BASE の FY ＋ 1Q 累計）。manifest と FY ・1Q の期間を返す。"""
    _, manifest, _ = produce(root, rows if rows is not None else [row(), quarterly("1Q")], context)
    return manifest, period_of(root, manifest, 0)


class Manifests:
    def __init__(self, manifest) -> None:
        self.manifest = manifest

    def by_acquisition(self, reference: str):
        return self.manifest


class SplitEpochs:
    """同じ期間の 2 つの脚に別の epoch を見せる合成の保持の像（fail closed の証明だけに使う）。"""

    def __init__(self, store: ProviderHoldingsStore, first: str, second: str) -> None:
        self.store, self.first, self.second, self.calls = store, first, second, 0

    def for_subject(self, subject_id: str):
        self.calls += 1
        wanted = self.first if (self.calls - 1) // 2 % 2 == 0 else self.second    # resolver ＋ manifest 参照で 2 回 ／ 脚
        return tuple(r for r in self.store.for_subject(subject_id) if r.acquisition_ref == wanted)


def only_inner(result: RetrospectiveMetricResult, outer: R, inner: MetricStatus, *reasons: str) -> None:
    assert result.status is outer and result.value is None and result.metric_result is not None
    assert result.metric_result.status is inner and result.metric_result.value is None
    assert set(reasons) <= {r.as_text() for r in result.metric_result.reasons}, result.metric_result.reasons


def outer_only(result: RetrospectiveMetricResult, outer: R, *legs: tuple) -> None:
    assert result.status is outer and result.value is None and result.metric_result is None
    for leg, status, diagnostic in legs:
        prov = next(p for p in result.legs if p.leg is leg)
        assert prov.status is status and prov.diagnostic == diagnostic, prov


# ================================================================ A 注記の parity（凍結 `_resolve_leg` の resolve の後の部分）


def test_a_annotation_matches_frozen_resolve_leg_for_found_missing_mismatch_and_absent() -> None:
    w = World()
    history, semantics = w.history(), w.semantics()
    cases = [("valid", w.rev24, C_2025_06, semantics),
             ("value absent", w.i2_rev21_missing, C_2025_06, semantics),
             ("semantics missing", w.rev24, C_2025_06, {k: v for k, v in semantics.items() if k != w.rev24.record_id}),
             ("wrong id", w.rev24, C_2025_06, {**semantics, w.rev24.record_id: semantics[w.op24.record_id]}),
             ("not semantics", w.rev24, C_2025_06, {**semantics, w.rev24.record_id: object()}),
             ("basis mismatch", w.rev24_noncons, C_2025_06,
              {**semantics, w.rev24_noncons.record_id: w.semantics({w.rev24_noncons.record_id: "FYFinancialStatements"
                                                                    "_Consolidated_JP"})[w.rev24_noncons.record_id]}),
             ("foreign standard", w.rev24, C_2025_06, w.semantics({w.rev24.record_id: FOREIGN})),
             ("ifrs standard", w.rev24, C_2025_06, w.semantics({w.rev24.record_id: IFRS})),
             ("restated", w.rev24_restated, C_2026_06, semantics)]
    for name, record, cutoff, lookup in cases:
        strict = fm._Leg(MetricLeg.REVENUE)
        fm._resolve_leg(history, strict, ObservationQuery.actual(record.subject, F.REVENUE, record.statement_basis,
                                                                  record.period), cutoff, lookup)
        assert strict.record is not None and strict.record.record_id == record.record_id, name  # 同じ観測が解けた前提
        retro = fm._Leg(MetricLeg.REVENUE)
        rm._annotate(retro, strict.record, lookup)
        assert retro.reasons == strict.reasons, name
        assert retro.semantics == strict.semantics, name
        assert retro.record is strict.record and retro.leg is strict.leg, name
        if strict.semantics is not None:                                                        # 基準 ・区分 ・通貨 ・桁
            assert retro.semantics.accounting_standard is strict.semantics.accounting_standard, name
            assert retro.semantics.statement_basis is strict.semantics.statement_basis, name
            assert retro.record.value.currency is strict.record.value.currency, name
            assert retro.record.value.scale is strict.record.value.scale and retro.record.value.amount == \
                strict.record.value.amount, name
    strict_rev, strict_op = fm._Leg(MetricLeg.REVENUE), fm._Leg(MetricLeg.OPERATING_INCOME)
    retro_rev, retro_op = fm._Leg(MetricLeg.REVENUE), fm._Leg(MetricLeg.OPERATING_INCOME)
    fm._resolve_leg(history, strict_rev, ObservationQuery.actual(I1, F.REVENUE, CONS, FY24), C_2025_06, semantics)
    fm._resolve_leg(history, strict_op, ObservationQuery.actual(I1, F.OPERATING_INCOME, CONS, FY24), C_2025_06,
                    semantics)
    rm._annotate(retro_rev, strict_rev.record, semantics)
    rm._annotate(retro_op, strict_op.record, semantics)
    assert fm._compatibility(retro_rev, retro_op) == fm._compatibility(strict_rev, strict_op) == []
    assert fm._ratio_minus(retro_op.record, retro_rev.record, subtract_one=False) == \
        fm._ratio_minus(strict_op.record, strict_rev.record, subtract_one=False) == ("0.08", [])


# ================================================================ B 4 指標の値（凍結の式 ・遡及の脚）


def test_b_operating_margin_net_margin_and_roa_resolve_through_the_selected_epoch(root: Path) -> None:
    manifest, fy = fy_epoch(root)
    epoch = holdings_store(root).for_slot(I1, P_FY)[0]
    expected = {K.OPERATING_MARGIN: "0.08", K.NET_MARGIN: "0.06", K.ROA_POINT_IN_TIME: "0.033333"}
    for kind, value in expected.items():
        result = metric(root, kind, fy, ACQ2)
        assert result.status is R.VALUE and result.value == value, (kind, result.diagnostics)
        assert result.metric_result.status is MetricStatus.VALUE and result.metric_result.value == value
        assert result.metric_result.metric is kind and result.metric_result.cutoff == ACQ2
        assert result.coverage_epoch_ids == (epoch.reference,) and result.manifest_refs == (manifest.reference,)
        assert len(result.legs) == 2 and all(leg.status is S.FOUND and leg.observation_id for leg in result.legs)
        assert result.resolution_mode == "RETROSPECTIVE_PROVIDER_AUTHORITY" and result.authority_as_of == ACQ2
        assert result.identity_valid_at == ACQ2 and result.diagnostics == ()
        assert set(result.observation_ids) <= set(manifest.observation_ids)
    om = metric(root, K.OPERATING_MARGIN, fy, ACQ2)
    assert [leg.leg for leg in om.legs] == [MetricLeg.REVENUE, MetricLeg.OPERATING_INCOME]
    assert om.metric_result.input_record_ids == om.observation_ids
    assert om.metric_result.period_label.value == "FISCAL_YEAR"


def test_b_revenue_growth_fy_and_cumulative_quarter_use_frozen_period_relation_and_formula(root: Path) -> None:
    _, prior, _ = produce(root, [PRIOR_FY, PRIOR_1Q], CTX1)
    manifest, fy = fy_epoch(root)
    prior_fy, prior_1q = period_of(root, prior, 0), period_of(root, prior, 1)
    q1 = period_of(root, manifest, 1)
    growth = metric(root, K.REVENUE_GROWTH, fy, ACQ2, comparison=prior_fy)
    assert growth.status is R.VALUE and growth.value == "0.25"
    assert growth.metric_result.period_label.value == "FISCAL_YEAR"
    assert growth.metric_result.comparison_period == prior_fy and growth.metric_result.quarter == 0
    quarter = metric(root, K.REVENUE_GROWTH, q1, ACQ2, comparison=prior_1q)
    assert quarter.status is R.VALUE and quarter.value == "4" and quarter.metric_result.quarter == 1
    assert quarter.metric_result.period_label.value == "CUMULATIVE_YEAR_TO_DATE"
    assert [leg.leg for leg in growth.legs] == [MetricLeg.TARGET, MetricLeg.COMPARISON]


def test_b_the_entry_point_accepts_exactly_the_four_frozen_kinds(root: Path) -> None:
    _, fy = fy_epoch(root)
    for bad in ("EPS", "PER", "PBR", "ROE", None, object()):
        with pytest.raises(ObservationModelError) as exc:
            metric(root, bad, fy, ACQ2)
        assert exc.value.code == "UNSUPPORTED_METRIC"
    assert {k.value for k in K} == {"REVENUE_GROWTH", "OPERATING_MARGIN", "NET_MARGIN", "ROA_POINT_IN_TIME"}


# ================================================================ C 凍結の語彙で真に表せる失敗（内側あり）


def test_c_value_absent_is_insufficient_data_and_never_zero(root: Path) -> None:
    manifest, fy = fy_epoch(root, [row(OP="", NP="")])                                          # 売上 ・総資産だけ
    om = metric(root, K.OPERATING_MARGIN, fy, ACQ2)
    only_inner(om, R.INSUFFICIENT_DATA, MetricStatus.INSUFFICIENT_DATA, "OPERATING_INCOME:VALUE_ABSENT")
    assert next(p for p in om.legs if p.leg is MetricLeg.OPERATING_INCOME).status is S.VALUE_ABSENT
    assert next(p for p in om.legs if p.leg is MetricLeg.REVENUE).status is S.FOUND
    assert om.coverage_epoch_ids == (holdings_store(root).for_slot(I1, P_FY)[0].reference,)
    nm = metric(root, K.NET_MARGIN, fy, ACQ2)
    only_inner(nm, R.INSUFFICIENT_DATA, MetricStatus.INSUFFICIENT_DATA, "NET_INCOME:VALUE_ABSENT")


def test_c_true_not_found_outside_coverage_not_yet_known_and_subject_not_resolved_keep_their_codes(root: Path) -> None:
    _, fy = fy_epoch(root)
    not_found = metric(root, K.OPERATING_MARGIN, fy, ACQ2, basis=NC)                             # covered ・一致なし
    only_inner(not_found, R.INSUFFICIENT_DATA, MetricStatus.INSUFFICIENT_DATA, "REVENUE:NOT_FOUND",
               "OPERATING_INCOME:NOT_FOUND")
    assert all(p.diagnostic == "NO_CANONICAL_MEMBER_FOR_COVERED_SLOT" for p in not_found.legs)
    other = replace(fy, fiscal_year_start=date(2025, 4, 1), fiscal_year_end=date(2026, 3, 31),
                    period_start=date(2025, 4, 1), period_end=date(2026, 3, 31))
    outside = metric(root, K.OPERATING_MARGIN, other, ACQ2)
    only_inner(outside, R.INSUFFICIENT_DATA, MetricStatus.INSUFFICIENT_DATA, "REVENUE:OUTSIDE_COVERAGE")
    early = metric(root, K.OPERATING_MARGIN, fy, ACQ1)                                           # record は後の epoch だけ
    only_inner(early, R.INSUFFICIENT_DATA, MetricStatus.INSUFFICIENT_DATA, "REVENUE:NOT_YET_KNOWN")
    assert all(p.diagnostic == "FUTURE_PROVIDER_HOLDINGS_EPOCH" for p in early.legs)
    subject = metric(root, K.OPERATING_MARGIN, fy, ACQ2, identity_valid_at=datetime(2019, 1, 1, tzinfo=JST))
    only_inner(subject, R.INSUFFICIENT_DATA, MetricStatus.INSUFFICIENT_DATA, "REVENUE:SUBJECT_NOT_RESOLVED")
    unknown = metric(root, K.OPERATING_MARGIN, fy, ACQ2, subject="p8iss_" + "0" * 24)
    only_inner(unknown, R.INSUFFICIENT_DATA, MetricStatus.INSUFFICIENT_DATA, "REVENUE:SUBJECT_NOT_RESOLVED")


def test_c_zero_and_negative_denominators_are_undefined_exactly_as_frozen_a3(root: Path) -> None:
    _, fy = fy_epoch(root, [ZERO_SALES])
    zero = metric(root, K.OPERATING_MARGIN, fy, ACQ2)
    only_inner(zero, R.UNDEFINED, MetricStatus.UNDEFINED, "PAIR:DENOMINATOR_ZERO")
    assert zero.legs[0].status is S.FOUND and zero.legs[1].status is S.FOUND                      # 値は在る。0 ではない
    _, _, later = produce(root, [NEGATIVE_SALES], CTX3)
    negative = metric(root, K.NET_MARGIN, fy, ACQ3)
    only_inner(negative, R.UNDEFINED, MetricStatus.UNDEFINED, "PAIR:DENOMINATOR_NEGATIVE")
    assert negative.coverage_epoch_ids != zero.coverage_epoch_ids


def test_c_period_rules_are_frozen_unsupported_irregular_and_missing_or_non_adjacent_comparison(root: Path) -> None:
    _, prior, _ = produce(root, [PRIOR_FY, PRIOR_1Q], CTX1)
    manifest, fy = fy_epoch(root)
    q1, prior_fy, prior_1q = period_of(root, manifest, 1), period_of(root, prior, 0), period_of(root, prior, 1)
    only_inner(metric(root, K.ROA_POINT_IN_TIME, q1, ACQ2), R.NOT_COMPARABLE, MetricStatus.NOT_COMPARABLE,
               "PAIR:PERIOD_BASIS_UNSUPPORTED")                                                   # 四半期の ROA は無い
    only_inner(metric(root, K.OPERATING_MARGIN, SINGLE_Q2_25, ACQ2), R.NOT_COMPARABLE, MetricStatus.NOT_COMPARABLE,
               "PAIR:PERIOD_BASIS_UNSUPPORTED")
    only_inner(metric(root, K.NET_MARGIN, LONG_FY, ACQ2), R.NOT_COMPARABLE, MetricStatus.NOT_COMPARABLE,
               "PAIR:FISCAL_YEAR_IRREGULAR")
    only_inner(metric(root, K.REVENUE_GROWTH, fy, ACQ2, comparison=prior_1q), R.NOT_COMPARABLE,
               MetricStatus.NOT_COMPARABLE, "PAIR:PERIOD_BASIS_MISMATCH")
    two_back = replace(prior_fy, fiscal_year_start=date(2022, 4, 1), fiscal_year_end=date(2023, 3, 31),
                       period_start=date(2022, 4, 1), period_end=date(2023, 3, 31))
    only_inner(metric(root, K.REVENUE_GROWTH, fy, ACQ2, comparison=two_back), R.NOT_COMPARABLE,
               MetricStatus.NOT_COMPARABLE, "PAIR:PERIOD_NOT_ADJACENT")
    missing = metric(root, K.REVENUE_GROWTH, prior_fy, ACQ2, comparison=two_back)                  # 直前の年度の record が無い
    only_inner(missing, R.INSUFFICIENT_DATA, MetricStatus.INSUFFICIENT_DATA, "COMPARISON:BEFORE_COVERAGE")
    assert next(p for p in missing.legs if p.leg is MetricLeg.TARGET).status is S.FOUND
    assert metric(root, K.ROA_POINT_IN_TIME, fy, ACQ2).status is R.VALUE
    assert metric(root, K.OPERATING_MARGIN, q1, ACQ2).status is R.VALUE                            # 累計の利益率は支える


def test_c_accounting_standard_and_basis_rules_are_frozen_obs57(root: Path) -> None:
    _, prior, _ = produce(root, [PRIOR_FY], CTX1)
    manifest, fy = fy_epoch(root, [row(DocType=IFRS)])                                            # 当年度だけ IFRS
    prior_fy = period_of(root, prior, 0)
    differs = metric(root, K.REVENUE_GROWTH, fy, ACQ2, comparison=prior_fy)
    only_inner(differs, R.NOT_COMPARABLE, MetricStatus.NOT_COMPARABLE, "PAIR:ACCOUNTING_STANDARD_DIFFERS")
    assert all(p.status is S.FOUND for p in differs.legs) and len(differs.coverage_epoch_ids) == 2
    semantics = semantics_of(root)
    revenue_id = manifest.entries[0].observation_ids[2]                                            # REVENUE（欄名の順で 3 つ目）
    unknown = {**semantics, revenue_id: derive_observation_semantics(revenue_id, FOREIGN,
                                                                     FieldFamily.UNPREFIXED_ACTUAL)[0]}
    only_inner(metric(root, K.OPERATING_MARGIN, fy, ACQ2, semantics=unknown), R.NOT_COMPARABLE,
               MetricStatus.NOT_COMPARABLE, "REVENUE:ACCOUNTING_STANDARD_UNKNOWN")
    other_basis = {**semantics, revenue_id: derive_observation_semantics(revenue_id, JP_NONCONS,
                                                                         FieldFamily.UNPREFIXED_ACTUAL)[0]}
    only_inner(metric(root, K.OPERATING_MARGIN, fy, ACQ2, semantics=other_basis), R.INVALID_INPUT,
               MetricStatus.INVALID_INPUT, "REVENUE:SEMANTICS_MISMATCH")                           # 注記と観測の区分の不一致
    only_inner(metric(root, K.OPERATING_MARGIN, fy, ACQ2, semantics={}), R.INSUFFICIENT_DATA,
               MetricStatus.INSUFFICIENT_DATA, "REVENUE:SEMANTICS_MISSING", "OPERATING_INCOME:SEMANTICS_MISSING")
    only_inner(metric(root, K.OPERATING_MARGIN, fy, ACQ2, semantics=None), R.INVALID_INPUT, MetricStatus.INVALID_INPUT,
               "PAIR:INVALID_SEMANTICS_LOOKUP")


# ================================================================ D 外側だけが持つ authority の失敗（内側なし）


def test_d_semantic_hold_is_an_outer_hold_without_an_inner_result(root: Path) -> None:
    _, fy = fy_epoch(root, [row(), NC_BROKEN])                                                      # NC は P 既知の保留
    held = metric(root, K.OPERATING_MARGIN, fy, ACQ2, basis=NC)
    outer_only(held, R.SEMANTIC_HOLD, (MetricLeg.REVENUE, S.SEMANTIC_HOLD, "HELD_ROW_AT_PERIOD"),
               (MetricLeg.OPERATING_INCOME, S.SEMANTIC_HOLD, "HELD_ROW_AT_PERIOD"))
    assert held.coverage_epoch_ids == (holdings_store(root).for_slot(I1, P_FY)[0].reference,)
    assert held.diagnostics == ("REVENUE:SEMANTIC_HOLD:HELD_ROW_AT_PERIOD",
                                "OPERATING_INCOME:SEMANTIC_HOLD:HELD_ROW_AT_PERIOD")
    assert metric(root, K.OPERATING_MARGIN, fy, ACQ2).status is R.VALUE                            # 連結の member は値


def test_d_manifest_missing_conflict_and_membership_invalid_are_authority_failures(root: Path) -> None:
    manifest, fy = fy_epoch(root)
    other = built(root, [quarterly("2Q")], CTX3)
    outer_only(metric(root, K.NET_MARGIN, fy, ACQ2, manifests=Manifests(None)), R.AUTHORITY_FAILURE,
               (MetricLeg.REVENUE, S.MANIFEST_MISSING, "NO_MANIFEST_FOR_ACQUISITION"))
    outer_only(metric(root, K.NET_MARGIN, fy, ACQ2, manifests=Manifests(other)), R.AUTHORITY_FAILURE,
               (MetricLeg.REVENUE, S.MANIFEST_CONFLICT, "MANIFEST_ACQUISITION_MISMATCH"))
    empty = ObservationHistory(IDS.history(), [])
    outer_only(metric(root, K.NET_MARGIN, fy, ACQ2, history=empty), R.AUTHORITY_FAILURE,
               (MetricLeg.REVENUE, S.MEMBERSHIP_INVALID, "OBSERVATION_MISSING"))
    failure = metric(root, K.NET_MARGIN, fy, ACQ2, manifests=Manifests(None))
    assert failure.coverage_epoch_ids == (holdings_store(root).for_slot(I1, P_FY)[0].reference,)   # epoch は選べていた
    assert failure.manifest_refs == (manifest.reference,) and failure.observation_ids == ()


def test_d_ambiguous_provider_epoch_and_same_period_epoch_disagreement_fail_closed(root: Path) -> None:
    e1, m1, _ = produce(root, [row()], CTX2)
    e2, m2, _ = produce(root, [row(), quarterly("1Q")], CTX2)                                      # 同じ瞬間の別の取得
    fy = period_of(root, m1)
    ambiguous = metric(root, K.OPERATING_MARGIN, fy, ACQ2)
    outer_only(ambiguous, R.AMBIGUOUS_AUTHORITY, (MetricLeg.REVENUE, S.AMBIGUOUS, "AMBIGUOUS_PROVIDER_HOLDINGS_EPOCH"))
    split = SplitEpochs(holdings_store(root), e1.reference, e2.reference)
    disagreement = metric(root, K.OPERATING_MARGIN, fy, ACQ2, holdings=split)
    assert disagreement.status is R.AMBIGUOUS_AUTHORITY and disagreement.metric_result is None
    assert all(p.status is S.FOUND for p in disagreement.legs) and len(disagreement.coverage_epoch_ids) == 2
    assert disagreement.diagnostics == ("SAME_PERIOD_EPOCH_MISMATCH:2025-03-31",)
    assert rm.SAME_PERIOD_EPOCH_RULE == "ALL_LEGS_OF_ONE_PERIOD_SHARE_ONE_COVERAGE_EPOCH"


def test_d_authority_inputs_are_explicit_and_invalid_ones_fail_as_input_errors(root: Path) -> None:
    _, fy = fy_epoch(root)
    naive = metric(root, K.OPERATING_MARGIN, fy, datetime(2026, 10, 12))
    assert naive.status is R.INVALID_INPUT and naive.metric_result is not None
    assert "PAIR:INVALID_CUTOFF" in {r.as_text() for r in naive.metric_result.reasons}
    assert naive.diagnostics == ("IDENTITY_VALID_AT_REQUIRED",)
    no_corrections = metric(root, K.OPERATING_MARGIN, fy, ACQ2, corrections=None)
    assert no_corrections.status is R.INVALID_INPUT and no_corrections.metric_result is None
    assert no_corrections.diagnostics == ("CORRECTION_AUTHORITY_REQUIRED",) and no_corrections.legs == ()
    assert metric(root, K.OPERATING_MARGIN, fy, ACQ2, holdings=object()).diagnostics == ("HOLDINGS_VIEW_REQUIRED",)
    assert metric(root, K.OPERATING_MARGIN, fy, ACQ2, manifests=object()).diagnostics == ("MANIFEST_VIEW_REQUIRED",)
    later_identity = metric(root, K.OPERATING_MARGIN, fy, ACQ2, identity_valid_at=ACQ3)
    assert later_identity.status is R.INVALID_INPUT and later_identity.metric_result is None
    assert later_identity.legs[0].diagnostic == "RETROSPECTIVE_REQUIRES_LATER_AUTHORITY"
    assert later_identity.legs[0].status is None and later_identity.as_dict()["legs"][0]["status"] is None
    assert later_identity.diagnostics[0] == "REVENUE:INVALID_INPUT:RETROSPECTIVE_REQUIRES_LATER_AUTHORITY"
    assert metric(root, K.OPERATING_MARGIN, fy, ACQ2, history=object()).status is R.INVALID_INPUT
    assert metric(root, K.OPERATING_MARGIN, "FY", ACQ2).metric_result.reasons[0].as_text() == "PAIR:INVALID_PERIOD"


# ================================================================ E 複数の期間の epoch（売上成長率）


def test_e_revenue_growth_legs_may_use_different_epochs_and_both_are_recorded(root: Path) -> None:
    e1, prior, _ = produce(root, [PRIOR_FY], CTX1)
    e2, manifest, _ = produce(root, [row()], CTX2)
    growth = metric(root, K.REVENUE_GROWTH, period_of(root, manifest), ACQ2, comparison=period_of(root, prior))
    assert growth.status is R.VALUE and growth.value == "0.25"
    target, comparison = growth.legs
    assert target.leg is MetricLeg.TARGET and comparison.leg is MetricLeg.COMPARISON
    assert target.coverage_epoch_id != comparison.coverage_epoch_id
    assert holdings_store(root).by_reference(target.coverage_epoch_id).acquisition_ref == e2.reference
    assert holdings_store(root).by_reference(comparison.coverage_epoch_id).acquisition_ref == e1.reference
    assert target.manifest_ref == manifest.reference and comparison.manifest_ref == prior.reference
    assert growth.coverage_epoch_ids == (target.coverage_epoch_id, comparison.coverage_epoch_id)
    assert growth.manifest_refs == (manifest.reference, prior.reference)
    before = metric(root, K.REVENUE_GROWTH, period_of(root, manifest), ACQ1, comparison=period_of(root, prior))
    only_inner(before, R.INSUFFICIENT_DATA, MetricStatus.INSUFFICIENT_DATA, "TARGET:NOT_YET_KNOWN")
    assert next(p for p in before.legs if p.leg is MetricLeg.COMPARISON).status is S.FOUND


# ================================================================ F provider の修正 ・再取得 ・訂正


def test_f_provider_fix_pins_hold_before_and_value_after_the_fix_epoch(root: Path) -> None:
    _, fy = fy_epoch(root, [row(), NC_BROKEN], CTX1)
    before = metric(root, K.OPERATING_MARGIN, fy, ACQ1, basis=NC)
    assert before.status is R.SEMANTIC_HOLD and before.metric_result is None
    produce(root, [row(), NC_FIXED], CTX2)
    after = metric(root, K.OPERATING_MARGIN, fy, ACQ2, basis=NC)
    assert after.status is R.VALUE and after.value == "40000000"                                  # 修正後の単体の行の値
    again = metric(root, K.OPERATING_MARGIN, fy, ACQ1, basis=NC)                                   # 先の結果は再現する
    assert again.as_dict() == before.as_dict() and again.coverage_epoch_ids != after.coverage_epoch_ids
    broken_only, _ = acquire(root, [row(Sales="1,000", DiscNo="20250512000011", CurFYSt="2025-04-01",
                                       CurFYEn="2026-03-31", CurPerSt="2025-04-01", CurPerEn="2026-03-31")], CTX3)
    assert run_f1(root, broken_only).status.value == "NO_CANONICAL_PERIODS"                        # 修正 A: record 無し
    next_fy = replace(fy, fiscal_year_start=date(2025, 4, 1), fiscal_year_end=date(2026, 3, 31),
                      period_start=date(2025, 4, 1), period_end=date(2026, 3, 31))
    only_inner(metric(root, K.OPERATING_MARGIN, next_fy, ACQ3), R.INSUFFICIENT_DATA, MetricStatus.INSUFFICIENT_DATA,
               "REVENUE:OUTSIDE_COVERAGE")


def test_f_reacquisition_keeps_the_value_and_observations_but_changes_the_epoch_provenance(root: Path) -> None:
    _, fy = fy_epoch(root, [row()], CTX1)
    fy_epoch(root, [row()], CTX2)
    first, second = metric(root, K.NET_MARGIN, fy, ACQ1), metric(root, K.NET_MARGIN, fy, ACQ2)
    assert first.value == second.value == "0.06" and first.observation_ids == second.observation_ids
    assert first.coverage_epoch_ids != second.coverage_epoch_ids and first.manifest_refs != second.manifest_refs
    assert first.metric_result.input_record_ids == second.metric_result.input_record_ids
    assert first.as_dict()["metric_result"]["cutoff"] != second.as_dict()["metric_result"]["cutoff"]


def test_f_a_new_discno_correction_is_visible_only_from_the_epoch_whose_manifest_holds_it(root: Path) -> None:
    _, fy = fy_epoch(root, [row()], CTX1)
    _, m2, _ = produce(root, [row(), CORRECTED], CTX2)
    history = history_of(root)
    o1, o2 = m2.entries[0].observation_ids[2], m2.entries[1].observation_ids[2]                     # REVENUE の鎖
    assert history.get(o2).supersedes == o1
    before, after = metric(root, K.OPERATING_MARGIN, fy, ACQ2 - timedelta(seconds=1)), metric(
        root, K.OPERATING_MARGIN, fy, ACQ2)
    assert before.value == "0.08" and o1 in before.observation_ids and o2 not in before.observation_ids
    assert after.value == "0.1" and o2 in after.observation_ids and o1 not in after.observation_ids
    assert before.coverage_epoch_ids != after.coverage_epoch_ids


# ================================================================ G provenance ・結果の形 ・非永続


def test_g_the_result_is_immutable_serializable_and_never_becomes_a_record(root: Path) -> None:
    manifest, fy = fy_epoch(root)
    before = (root / "screener_intelligence" / "provider_holdings_coverage.jsonl").read_bytes()
    result = metric(root, K.ROA_POINT_IN_TIME, fy, ACQ2)
    data = result.as_dict()
    assert set(data) == {"authority_as_of", "authority_class", "comparison_period", "coverage_epoch_ids", "diagnostics",
                         "identity_valid_at", "legs", "manifest_refs", "metric", "metric_result", "observation_ids",
                         "resolution_mode", "rules_version", "statement_basis", "status", "subject_id",
                         "target_period", "value"}
    assert data["authority_class"] == "DERIVED_NON_AUTHORITY_NON_PERSISTENT"
    assert data["resolution_mode"] == "RETROSPECTIVE_PROVIDER_AUTHORITY"
    assert data["rules_version"] == rm.RETROSPECTIVE_METRIC_RULES_VERSION == "p8_retrospective_metrics:0.1.0"
    assert data["authority_as_of"] == data["identity_valid_at"] == "2026-10-12T09:00:00+00:00"
    assert data["value"] == "0.033333" and data["metric_result"]["value"] == "0.033333"
    assert set(data["legs"][0]) == {"coverage_epoch_id", "coverage_record_ids", "diagnostic", "field", "leg",
                                    "manifest_ref", "observation_id", "period_end", "status"}
    assert data["legs"][0]["leg"] == "TOTAL_ASSETS" and data["legs"][1]["leg"] == "NET_INCOME"
    assert data["manifest_refs"] == [manifest.reference]
    with pytest.raises(FrozenInstanceError):
        result.value = "1"                                                                   # type: ignore[misc]
    with pytest.raises(ObservationAppendRejected):
        ObservationStore.open(root).append(result)
    with pytest.raises(HoldingsAppendRejected):
        ProviderHoldingsStore.open(root).append(result)
    assert (root / "screener_intelligence" / "provider_holdings_coverage.jsonl").read_bytes() == before
    assert not hasattr(result, "record_id") and not hasattr(result, "canonical_line")
    text = repr(data)
    assert "500000000000" not in text and "Sales" not in text and "api_key" not in text       # 値 ・raw ・credential なし
    assert metric(root, K.ROA_POINT_IN_TIME, fy, ACQ2).as_dict() == data                              # 決定論


def test_g_module_isolation_no_formula_copy_no_strict_no_clock_no_io_no_float() -> None:
    source = executable_source(PACKAGE_DIR / "retrospective_metric_resolver.py")
    for token in ("_resolve_leg", "resolve(", "Decimal", "ROUND_HALF_EVEN", "quantize", "canonical_decimal", "float",
                  "localcontext", "/ ", "- 1", "REGULAR_FISCAL_YEAR_DAYS", "timedelta", "now(", "today(", "utcnow",
                  "open(", "Path(", "os.", "json", "://", ".coverages", "ObservationCoverage", "complete_through",
                  "store.append", "history.add(", "importlib", "__import__", "getattr", "llm", "prompt"):
        assert token not in source, token
    for token in ("_ratio_minus(", "_compatibility(", "_period_relation(", "_label_for(", "_regular_fiscal_year(",
                  "_input_reasons(", "_result(", "resolve_retrospective("):
        assert token in source, token
    assert source.count("_ratio_minus(") == 1 and source.count("resolve_retrospective(") == 1
    tree = ast.parse((PACKAGE_DIR / "retrospective_metric_resolver.py").read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        assert not (isinstance(node, ast.Name) and node.id in {"open", "Path", "os", "getattr", "time", "sys",
                                                                "float", "round"}), node.id
        assert not isinstance(node, ast.BinOp), ast.dump(node)                                        # 算術は module に無い
    assert set(rm.__all__) == {"RETROSPECTIVE_METRIC_RULES_VERSION", "SAME_PERIOD_EPOCH_RULE", "LegProvenance",
                               "RetrospectiveMetricResult", "RetrospectiveMetricStatus", "net_margin_retrospective",
                               "operating_margin_retrospective", "resolve_retrospective_metric",
                               "revenue_growth_retrospective", "roa_point_in_time_retrospective"}
    assert {s.value for s in R} == {"VALUE", "INVALID_INPUT", "INSUFFICIENT_TIME_PRECISION", "INSUFFICIENT_DATA",
                                    "SEMANTIC_HOLD", "NOT_COMPARABLE", "UNDEFINED", "AUTHORITY_FAILURE",
                                    "AMBIGUOUS_AUTHORITY"}
    assert {c.value for c in ReasonCode} == {c.value for c in ReasonCode} and "SEMANTIC_HOLD" not in {
        c.value for c in ReasonCode}                                                                   # 凍結の語彙は不変
    for path in sorted(PACKAGE_DIR.glob("*.py")):
        if path.stem != "retrospective_metric_resolver":
            assert "retrospective_metric" not in path.read_text(encoding="utf-8"), path.name
    for path in (REPO_ROOT / "src" / "intelligence" / "jquants_pilot2_local.py",
                 REPO_ROOT / "src" / "intelligence" / "jquants_local_transport.py", REPO_ROOT / "main.py"):
        assert "retrospective" not in path.read_text(encoding="utf-8"), path.name                     # 配線は後の gate

