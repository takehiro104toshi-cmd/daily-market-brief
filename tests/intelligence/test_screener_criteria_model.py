"""P8-B1 — Screener v1 の閉じた意味の model（`screener_criteria_model`）の test。

評価 ・保存 ・Theme ・security の投影は無い（B2 以降）。すべて合成の fixture。閾値は model の test のための合成の値で、投資の方針ではない。
境界 ／ 凍結の guard は `test_screener_intelligence_boundary.py`（`test_b1_*`）。
"""
from __future__ import annotations

import ast
import json
from dataclasses import FrozenInstanceError, fields, replace
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

import pytest

from src.intelligence.screener_intelligence import screener_criteria_model as sm
from src.intelligence.screener_intelligence.identity_model import SubjectKind
from src.intelligence.screener_intelligence.metric_model import MetricKind, MetricStatus
from src.intelligence.screener_intelligence.observation_model import PeriodBasis, ReportingPeriod, StatementBasis
from src.intelligence.screener_intelligence.retrospective_metric_resolver import RESOLUTION_MODE
from src.intelligence.screener_intelligence.screener_criteria_model import (CriteriaComposition, CriteriaPolicy,
                                                                           Criterion, CriterionOperator,
                                                                           CriterionResult, CriterionState,
                                                                           DataCompleteness, EvaluationContext,
                                                                           MissingDataPolicy, PeriodRule,
                                                                           ScreenerAuthorityMode, ScreenerDimension,
                                                                           ScreenerModelError, ScreenerResult,
                                                                           ScreenerState, canonical_threshold,
                                                                           completeness_of)
from tests.intelligence.phase8_runtime_registry import PHASE8_PACKAGE
from tests.intelligence.test_prediction_record import executable_source

REPO_ROOT = Path(__file__).resolve().parents[2]
MODULE = REPO_ROOT / PHASE8_PACKAGE / "screener_criteria_model.py"
JST = timezone(timedelta(hours=9))
REVIEWED = datetime(2026, 10, 6, 9, 30, tzinfo=JST)
EVAL = datetime(2026, 10, 6, 18, 0, tzinfo=JST)
ISSUER = "p8iss_" + "0" * 24
RETRO = ScreenerAuthorityMode.RETROSPECTIVE_PROVIDER_AUTHORITY
STRICT = ScreenerAuthorityMode.STRICT_PIT
CONS = StatementBasis.CONSOLIDATED
FY = ReportingPeriod(PeriodBasis.FISCAL_YEAR, date(2024, 4, 1), date(2025, 3, 31), date(2024, 4, 1), date(2025, 3, 31))
PRIOR_FY = ReportingPeriod(PeriodBasis.FISCAL_YEAR, date(2023, 4, 1), date(2024, 3, 31), date(2023, 4, 1),
                           date(2024, 3, 31))
OBS = "p8obs_" + "a" * 24
EPOCH = "jq.pvh:" + "b" * 24
MANIFEST = "jq.man:" + "c" * 24
SYNTHETIC_THRESHOLD = "0.0100"                                                   # 合成の値（投資の閾値ではない）


def criterion(**overrides) -> Criterion:
    base = dict(dimension=ScreenerDimension.FINANCIAL, subject_kind=SubjectKind.ISSUER,
                metric=MetricKind.OPERATING_MARGIN, operator=CriterionOperator.GE, threshold=SYNTHETIC_THRESHOLD,
                period_rule=PeriodRule.NEWEST_FY, authority_mode=RETRO, statement_basis=CONS)
    return Criterion(**{**base, **overrides})


def policy(*criteria, **overrides) -> CriteriaPolicy:
    base = dict(policy_key="synthetic-model-test", version=1, author_ref="human:reviewer-1", reviewed_at=REVIEWED,
                intent="synthetic fixture for the semantic model tests", criteria=criteria or (criterion(),),
                authority_mode=RETRO)
    return CriteriaPolicy(**{**base, **overrides})


def result(c: Criterion, state: CriterionState = CriterionState.MATCH, **overrides) -> CriterionResult:
    valued = state in (CriterionState.MATCH, CriterionState.NO_MATCH)
    base = dict(criterion_id=c.criterion_id, state=state, metric=c.metric, operator=c.operator, threshold=c.threshold,
                threshold_high=c.threshold_high, authority_mode=c.authority_mode, has_value=valued,
                observed_value="0.0200" if valued else None, target_period=FY, observation_ids=(OBS,),
                coverage_epoch_ids=(EPOCH,), manifest_refs=(MANIFEST,), reason_codes=(),
                inner_metric_status=MetricStatus.VALUE if valued else None)
    return CriterionResult(**{**base, **overrides})


def screener(results, state: ScreenerState, *, pol: CriteriaPolicy = None, **overrides) -> ScreenerResult:
    pol = pol or policy()
    base = dict(subject_id=ISSUER, policy_id=pol.policy_id, policy_version=pol.version, evaluation_as_of=EVAL,
                identity_valid_at=EVAL, authority_mode=pol.authority_mode, criterion_results=tuple(results),
                state=state)
    if "completeness" not in overrides:
        base["completeness"] = completeness_of(r.state for r in results)
    return ScreenerResult(**{**base, **overrides})


def rejects(code: str, fn, *args, **kwargs) -> None:
    with pytest.raises(ScreenerModelError) as exc:
        fn(*args, **kwargs)
    assert exc.value.code == code, exc.value.code


# ================================================================ A 閾値の Decimal


def test_a_thresholds_are_canonical_decimal_strings_and_rejections_are_typed() -> None:
    assert canonical_threshold("0.10") == "0.1" and canonical_threshold(" 1.000 ") == "1"
    assert canonical_threshold("-5") == "-5"
    assert canonical_threshold("1E+2") == "100" and canonical_threshold("0.000") == "0"
    for bad, code in ((0.1, "THRESHOLD_NOT_TEXT"), (1, "THRESHOLD_NOT_TEXT"), (True, "THRESHOLD_NOT_TEXT"),
                      (Decimal("1"), "THRESHOLD_NOT_TEXT"), (None, "THRESHOLD_NOT_TEXT"), ("NaN", "INVALID_THRESHOLD"),
                      ("Infinity", "INVALID_THRESHOLD"), ("-inf", "INVALID_THRESHOLD"), ("abc", "INVALID_THRESHOLD"),
                      ("1,000", "INVALID_THRESHOLD"), ("", "INVALID_THRESHOLD"), ("1e400", "INVALID_THRESHOLD")):
        rejects(code, canonical_threshold, bad)
    assert criterion(threshold="0.0100").threshold == "0.01"                                   # 正準化して保存する
    assert criterion(threshold="0.0100").criterion_id == criterion(threshold="0.01").criterion_id


# ================================================================ B Criterion


def test_b_criterion_identity_is_deterministic_and_covers_every_semantic_field() -> None:
    c = criterion()
    assert c.criterion_id == criterion().criterion_id and c.criterion_id.startswith("p8crt_")
    assert len(c.criterion_id) == 30
    assert set(c.identity_payload()) == {"authority_mode", "dimension", "metric", "missing_policy", "operator",
                                         "period_rule", "rules_version", "schema_version", "statement_basis",
                                         "subject_kind", "threshold", "threshold_high"}
    for change in (dict(threshold="0.02"), dict(operator=CriterionOperator.GT), dict(metric=MetricKind.NET_MARGIN),
                   dict(period_rule=PeriodRule.NEWEST_SUPPORTED_FY_OR_CUMULATIVE), dict(authority_mode=STRICT),
                   dict(statement_basis=StatementBasis.NON_CONSOLIDATED)):
        assert criterion(**change).criterion_id != c.criterion_id, change
    again = Criterion.from_dict(c.as_dict())
    assert again == c and again.criterion_id == c.criterion_id
    assert json.dumps(c.as_dict(), sort_keys=True) == json.dumps(criterion().as_dict(), sort_keys=True)
    rejects("ID_MISMATCH", Criterion.from_dict, {**c.as_dict(), "criterion_id": "p8crt_" + "f" * 24})
    rejects("UNKNOWN_FIELD", Criterion.from_dict, {**c.as_dict(), "weight": "1"})
    rejects("SCHEMA_MISMATCH", Criterion.from_dict, {**c.as_dict(), "schema_version": "p8_screener_criterion:9.9.9"})
    with pytest.raises(FrozenInstanceError):
        c.threshold = "1"                                                                      # type: ignore[misc]


def test_b_between_requires_two_ascending_bounds_and_other_operators_exactly_one() -> None:
    both = criterion(operator=CriterionOperator.BETWEEN, threshold="0.01", threshold_high="0.0500")
    assert (both.threshold, both.threshold_high) == ("0.01", "0.05")
    rejects("BETWEEN_REQUIRES_TWO_THRESHOLDS", criterion, operator=CriterionOperator.BETWEEN)
    rejects("BETWEEN_BOUNDS_NOT_ASCENDING", criterion, operator=CriterionOperator.BETWEEN, threshold="0.05",
            threshold_high="0.01")
    rejects("BETWEEN_BOUNDS_NOT_ASCENDING", criterion, operator=CriterionOperator.BETWEEN, threshold="0.05",
            threshold_high="0.050")
    rejects("INVALID_THRESHOLD", criterion, operator=CriterionOperator.BETWEEN, threshold="0.01", threshold_high="NaN")
    for operator in (CriterionOperator.LT, CriterionOperator.LE, CriterionOperator.GT, CriterionOperator.GE):
        rejects("THRESHOLD_HIGH_ONLY_FOR_BETWEEN", criterion, operator=operator, threshold_high="1")
    assert {o.value for o in CriterionOperator} == {"LT", "LE", "GT", "GE", "BETWEEN"}


@pytest.mark.parametrize("metric,allowed", [
    (MetricKind.REVENUE_GROWTH, {PeriodRule.NEWEST_WITH_COMPARABLE_PRIOR}),
    (MetricKind.OPERATING_MARGIN, {PeriodRule.NEWEST_SUPPORTED_FY_OR_CUMULATIVE, PeriodRule.NEWEST_FY}),
    (MetricKind.NET_MARGIN, {PeriodRule.NEWEST_SUPPORTED_FY_OR_CUMULATIVE, PeriodRule.NEWEST_FY}),
    (MetricKind.ROA_POINT_IN_TIME, {PeriodRule.NEWEST_FY})])
def test_b_metric_and_period_rule_compatibility_is_closed(metric: MetricKind, allowed: set) -> None:
    for rule in PeriodRule:
        if rule in allowed:
            assert criterion(metric=metric, period_rule=rule).period_rule is rule
        else:
            rejects("PERIOD_RULE_INCOMPATIBLE_WITH_METRIC", criterion, metric=metric, period_rule=rule)
    assert set(sm.METRIC_PERIOD_RULES) == set(MetricKind) and set(sm.METRIC_PERIOD_RULES[metric]) == allowed
    assert {r.value for r in PeriodRule} == {"NEWEST_SUPPORTED_FY_OR_CUMULATIVE", "NEWEST_FY",
                                             "NEWEST_WITH_COMPARABLE_PRIOR"}


def test_b_financial_criteria_are_issuer_level_and_the_theme_dimension_is_not_constructible() -> None:
    rejects("FINANCIAL_CRITERION_REQUIRES_ISSUER", criterion, subject_kind=SubjectKind.SECURITY)
    rejects("DIMENSION_NOT_CONSTRUCTIBLE_IN_V1", criterion, dimension=ScreenerDimension.THEME_EXPOSURE)
    assert {d.value for d in ScreenerDimension} == {"FINANCIAL", "THEME_EXPOSURE"}                # 予約だけ
    assert sm.CONSTRUCTIBLE_DIMENSIONS == (ScreenerDimension.FINANCIAL,)
    for bad in ("FINANCIAL", None, object()):
        rejects("INVALID_ENUM", criterion, dimension=bad)
    rejects("INVALID_ENUM", criterion, metric="OPERATING_MARGIN")
    rejects("INVALID_ENUM", criterion, authority_mode="RETROSPECTIVE_PROVIDER_AUTHORITY")
    rejects("INVALID_ENUM", criterion, statement_basis="CONSOLIDATED")
    rejects("RULES_VERSION_MISMATCH", criterion, rules_version="p8_screener_semantics:9.9.9")
    assert set(MetricKind) == {MetricKind.REVENUE_GROWTH, MetricKind.OPERATING_MARGIN, MetricKind.NET_MARGIN,
                               MetricKind.ROA_POINT_IN_TIME}                                     # 指標の面は広げない


def test_b_authority_modes_are_exactly_two_and_match_the_frozen_resolver_vocabulary() -> None:
    assert {m.value for m in ScreenerAuthorityMode} == {"STRICT_PIT", "RETROSPECTIVE_PROVIDER_AUTHORITY"}
    assert ScreenerAuthorityMode.RETROSPECTIVE_PROVIDER_AUTHORITY.value == RESOLUTION_MODE
    assert criterion(authority_mode=STRICT).criterion_id != criterion(authority_mode=RETRO).criterion_id
    assert {m.value for m in MissingDataPolicy} == {"NOT_EVALUABLE_IS_NOT_MATCH"} == {sm.MISSING_DATA_RULE}


# ================================================================ C CriteriaPolicy


def test_c_policy_identity_is_deterministic_versioned_and_covers_review_metadata() -> None:
    p = policy()
    assert p.policy_id == policy().policy_id and p.policy_id.startswith("p8pol_") and len(p.policy_id) == 30
    assert set(p.identity_payload()) == {"author_ref", "authority_mode", "composition", "criterion_ids", "intent",
                                         "policy_key", "reviewed_at", "rules_version", "schema_version", "version"}
    for change in (dict(version=2), dict(author_ref="human:reviewer-2"),
                   dict(reviewed_at=REVIEWED + timedelta(hours=1)),
                   dict(intent="another synthetic fixture"), dict(policy_key="synthetic-other"),
                   dict(criteria=(criterion(threshold="0.02"),))):
        assert policy(**change).policy_id != p.policy_id, change
    ordered = policy(criterion(), criterion(metric=MetricKind.NET_MARGIN))
    reordered = policy(criterion(metric=MetricKind.NET_MARGIN), criterion())
    assert ordered.policy_id != reordered.policy_id                                              # 順序は意味を持つ
    assert ordered.as_dict()["criterion_ids"] == [c.criterion_id for c in ordered.criteria]
    assert ordered.as_dict()["reviewed_at"] == "2026-10-06T00:30:00+00:00"
    assert json.dumps(ordered.as_dict(), sort_keys=True) == json.dumps(
        policy(criterion(), criterion(metric=MetricKind.NET_MARGIN)).as_dict(), sort_keys=True)


def test_c_policy_is_all_of_only_single_mode_human_reviewed_and_bounded() -> None:
    assert {c.value for c in CriteriaComposition} == {"ALL_OF"}
    rejects("INVALID_ENUM", policy, composition="ANY_OF")
    rejects("CRITERION_AUTHORITY_MODE_MISMATCH", policy, criterion(authority_mode=STRICT))
    rejects("CRITERION_AUTHORITY_MODE_MISMATCH", policy, criterion(), criterion(authority_mode=STRICT))
    rejects("DUPLICATE_CRITERION", policy, criterion(), criterion())
    rejects("POLICY_REQUIRES_CRITERIA", policy, criteria=())
    rejects("INVALID_CRITERION", policy, criteria=(object(),))
    rejects("NAIVE_OR_MISSING_DATETIME", policy, reviewed_at=datetime(2026, 10, 6, 9, 30))
    rejects("NAIVE_OR_MISSING_DATETIME", policy, reviewed_at="2026-10-06T09:30:00+09:00")
    rejects("INVALID_VERSION", policy, version=0)
    rejects("INVALID_VERSION", policy, version="1")
    rejects("INVALID_TEXT", policy, policy_key="Synthetic Policy")
    rejects("INVALID_TEXT", policy, author_ref="")
    rejects("CREDENTIAL_LIKE_TEXT", policy, author_ref="api_key:abc")
    rejects("INVALID_INTENT", policy, intent="")
    rejects("INVALID_INTENT", policy, intent="x" * 501)
    rejects("INVALID_INTENT", policy, intent="line\nbreak")
    for word in ("buy", "sell", "recommend", "watchlist", "portfolio", "target price", "expected return", "score",
                 "rank", "rating", "best", "推奨", "注目", "おすすめ", "有望", "割安", "上位"):
        rejects("FORBIDDEN_INTENT_VOCABULARY", policy, intent=f"synthetic intent mentioning {word}")
    strict = policy(criterion(authority_mode=STRICT), authority_mode=STRICT)
    assert strict.authority_mode is STRICT and strict.policy_id != policy().policy_id


# ================================================================ D EvaluationContext


def test_d_evaluation_context_requires_explicit_aware_axes_and_an_issuer_subject() -> None:
    p = policy()
    ctx = EvaluationContext(subject_id=ISSUER, evaluation_as_of=EVAL, identity_valid_at=EVAL, authority_mode=RETRO,
                            policy_id=p.policy_id)
    assert ctx.as_dict() == {"authority_mode": "RETROSPECTIVE_PROVIDER_AUTHORITY",
                             "evaluation_as_of": "2026-10-06T09:00:00+00:00",
                             "identity_valid_at": "2026-10-06T09:00:00+00:00", "policy_id": p.policy_id,
                             "rules_version": sm.SCREENER_RULES_VERSION, "subject_id": ISSUER}
    rejects("INVALID_SUBJECT", EvaluationContext, subject_id="p8sec_" + "0" * 24, evaluation_as_of=EVAL,
            identity_valid_at=EVAL, authority_mode=RETRO, policy_id=p.policy_id)
    rejects("NAIVE_OR_MISSING_DATETIME", EvaluationContext, subject_id=ISSUER, evaluation_as_of=datetime(2026, 10, 6),
            identity_valid_at=EVAL, authority_mode=RETRO, policy_id=p.policy_id)
    rejects("IDENTITY_VALID_AT_AFTER_EVALUATION", EvaluationContext, subject_id=ISSUER, evaluation_as_of=EVAL,
            identity_valid_at=EVAL + timedelta(seconds=1), authority_mode=RETRO, policy_id=p.policy_id)
    rejects("INVALID_TEXT", EvaluationContext, subject_id=ISSUER, evaluation_as_of=EVAL, identity_valid_at=EVAL,
            authority_mode=RETRO, policy_id="p8crt_" + "0" * 24)
    rejects("INVALID_ENUM", EvaluationContext, subject_id=ISSUER, evaluation_as_of=EVAL, identity_valid_at=EVAL,
            authority_mode="STRICT_PIT", policy_id=p.policy_id)
    strict_ctx = replace(ctx, authority_mode=STRICT)
    assert strict_ctx.authority_mode is STRICT and strict_ctx.as_dict()["authority_mode"] == "STRICT_PIT"


# ================================================================ E CriterionResult


def test_e_criterion_result_carries_a_value_only_in_valued_states_and_has_no_distance() -> None:
    c = criterion()
    matched = result(c)
    assert matched.has_value and matched.observed_value == "0.02" and matched.state is CriterionState.MATCH
    assert "observed_value" not in matched.as_dict() and matched.as_dict(include_value=True)["observed_value"] == "0.02"
    assert set(matched.as_dict()) == {"authority_mode", "comparison_period", "coverage_epoch_ids", "criterion_id",
                                      "has_value", "inner_metric_status", "manifest_refs", "metric", "observation_ids",
                                      "operator", "reason_codes", "state", "target_period", "threshold",
                                      "threshold_high"}
    assert "threshold_distance" not in set(f.name for f in fields(CriterionResult))
    held = result(c, CriterionState.HOLD, reason_codes=("REVENUE:SEMANTIC_HOLD:HELD_ROW_AT_PERIOD",),
                  observation_ids=(), inner_metric_status=None)
    assert not held.has_value and held.observed_value is None and held.as_dict()["has_value"] is False
    rejects("VALUE_FLAG_INCONSISTENT_WITH_STATE", result, c, CriterionState.HOLD, has_value=True)
    rejects("VALUE_FLAG_INCONSISTENT_WITH_STATE", result, c, CriterionState.MATCH, has_value=False)
    rejects("VALUED_STATE_REQUIRES_OBSERVED_VALUE", result, c, CriterionState.NO_MATCH, observed_value=None)
    rejects("OBSERVED_VALUE_ONLY_WHEN_VALUED", result, c, CriterionState.NOT_EVALUABLE, observed_value="0.02")
    rejects("THRESHOLD_NOT_TEXT", result, c, CriterionState.MATCH, observed_value=0.02)
    rejects("INVALID_THRESHOLD", result, c, CriterionState.MATCH, observed_value="NaN")
    rejects("THRESHOLD_HIGH_ONLY_FOR_BETWEEN", result, c, threshold_high="1")
    rejects("INVALID_REFERENCE", result, c, observation_ids=("obs-1",))
    rejects("INVALID_REFERENCE", result, c, coverage_epoch_ids=("p8pvh_" + "b" * 24,))
    rejects("INVALID_REFERENCE", result, c, manifest_refs=("jq.acq:" + "c" * 24,))
    rejects("DUPLICATE_REFERENCE", result, c, observation_ids=(OBS, OBS))
    rejects("INVALID_REFERENCE", result, c, reason_codes=("lower:case",))
    rejects("REASON_CODES_NOT_SORTED", result, c, CriterionState.NOT_EVALUABLE, observation_ids=(),
            inner_metric_status=None, reason_codes=("REVENUE:NOT_FOUND", "OPERATING_INCOME:NOT_FOUND"))
    rejects("INVALID_PERIOD", result, c, target_period="FY2024")
    rejects("INVALID_TEXT", result, c, criterion_id="p8pol_" + "0" * 24)
    assert {s.value for s in CriterionState} == {"MATCH", "NO_MATCH", "HOLD", "NOT_EVALUABLE", "AUTHORITY_FAILURE"}
    failure = result(c, CriterionState.AUTHORITY_FAILURE, observation_ids=(), coverage_epoch_ids=(), manifest_refs=(),
                     inner_metric_status=None, reason_codes=("REVENUE:AUTHORITY_FAILURE:NO_MANIFEST_FOR_ACQUISITION",))
    assert failure.as_dict()["inner_metric_status"] is None and failure.as_dict()["target_period"]["period_end"]


# ================================================================ F ScreenerResult


def test_f_screener_result_match_means_every_criterion_matched_and_completeness_is_data_only() -> None:
    p = policy(criterion(), criterion(metric=MetricKind.NET_MARGIN))
    a, b = (result(c) for c in p.criteria)
    matched = screener((a, b), ScreenerState.MATCH, pol=p)
    assert matched.is_match and matched.completeness is DataCompleteness.COMPLETE
    assert matched.as_dict()["state"] == "MATCH"
    assert matched.as_dict()["authority_class"] == "DERIVED_NON_AUTHORITY_NON_PERSISTENT"
    assert set(matched.as_dict()) == {"authority_class", "authority_mode", "completeness", "criterion_results",
                                      "evaluation_as_of", "identity_valid_at", "policy_id", "policy_version",
                                      "rules_version", "schema_version", "state", "subject_id"}
    assert "observed_value" not in matched.as_dict()["criterion_results"][0]
    assert matched.as_dict(include_values=True)["criterion_results"][0]["observed_value"] == "0.02"
    no_match = replace(b, state=CriterionState.NO_MATCH)
    rejects("MATCH_REQUIRES_ALL_CRITERIA_MATCH", screener, (a, no_match), ScreenerState.MATCH, pol=p)
    rejects("ALL_CRITERIA_MATCH_REQUIRES_MATCH", screener, (a, b), ScreenerState.NO_MATCH, pol=p)
    assert screener((a, no_match), ScreenerState.NO_MATCH, pol=p).completeness is DataCompleteness.COMPLETE
    held = replace(b, state=CriterionState.HOLD, has_value=False, observed_value=None, inner_metric_status=None)
    partial = screener((a, held), ScreenerState.HOLD, pol=p)
    assert partial.completeness is DataCompleteness.PARTIAL and not partial.is_match
    none = screener((replace(a, state=CriterionState.NOT_EVALUABLE, has_value=False, observed_value=None,
                             inner_metric_status=None), held), ScreenerState.NOT_EVALUABLE, pol=p)
    assert none.completeness is DataCompleteness.NONE
    rejects("COMPLETENESS_INCONSISTENT", screener, (a, held), ScreenerState.HOLD, pol=p,
            completeness=DataCompleteness.COMPLETE)
    assert {c.value for c in DataCompleteness} == {"COMPLETE", "PARTIAL", "NONE"}                # 数ではない
    assert completeness_of([CriterionState.MATCH, CriterionState.NO_MATCH]) is DataCompleteness.COMPLETE
    rejects("INVALID_ENUM", completeness_of, [])
    rejects("INVALID_ENUM", completeness_of, ["MATCH"])
    assert {s.value for s in ScreenerState} == {"MATCH", "NO_MATCH", "HOLD", "NOT_EVALUABLE", "AUTHORITY_FAILURE"}


def test_f_screener_result_requires_consistent_authority_mode_subject_axes_and_unique_criteria() -> None:
    p = policy()
    a = result(p.criteria[0])
    rejects("CRITERION_AUTHORITY_MODE_MISMATCH", screener, (a,), ScreenerState.MATCH, pol=p, authority_mode=STRICT)
    rejects("DUPLICATE_CRITERION", screener, (a, a), ScreenerState.MATCH, pol=p)
    rejects("RESULT_REQUIRES_CRITERIA", screener, (), ScreenerState.NOT_EVALUABLE, pol=p,
            completeness=DataCompleteness.NONE)
    rejects("INVALID_SUBJECT", screener, (a,), ScreenerState.MATCH, pol=p, subject_id="p8sec_" + "0" * 24)
    rejects("IDENTITY_VALID_AT_AFTER_EVALUATION", screener, (a,), ScreenerState.MATCH, pol=p,
            identity_valid_at=EVAL + timedelta(seconds=1))
    rejects("NAIVE_OR_MISSING_DATETIME", screener, (a,), ScreenerState.MATCH, pol=p,
            evaluation_as_of=datetime(2026, 10, 6))
    rejects("INVALID_TEXT", screener, (a,), ScreenerState.MATCH, pol=p, policy_id="p8crt_" + "0" * 24)
    rejects("INVALID_VERSION", screener, (a,), ScreenerState.MATCH, pol=p, policy_version=0)
    rejects("INVALID_AUTHORITY_CLASS", screener, (a,), ScreenerState.MATCH, pol=p, authority_class="AUTHORITY")
    rejects("RULES_VERSION_MISMATCH", screener, (a,), ScreenerState.MATCH, pol=p, rules_version="x:0.0.1")
    with pytest.raises(FrozenInstanceError):
        screener((a,), ScreenerState.MATCH, pol=p).state = ScreenerState.NO_MATCH                 # type: ignore[misc]
    assert screener((a,), ScreenerState.MATCH, pol=p).as_dict() == screener((a,), ScreenerState.MATCH, pol=p).as_dict()


# ================================================================ G 順位 ・推奨の面が無い ・module の形


def test_g_models_have_no_ranking_recommendation_or_distance_surface_and_no_floats() -> None:
    names = sm.model_field_names()
    assert set(names) == {"Criterion", "CriteriaPolicy", "EvaluationContext", "CriterionResult", "ScreenerResult"}
    every = {n for group in names.values() for n in group}
    assert not every & set(sm.FORBIDDEN_RESULT_FIELDS)
    for name in every:
        assert not any(word in name for word in ("score", "rank", "weight", "distance", "rating", "priority",
                                                  "recommend", "buy", "sell", "return", "price", "watchlist",
                                                  "portfolio")), name
    source = executable_source(MODULE)
    for token in ("float(", "isinstance(value, float)", "now(", "today(", "utcnow", "open(", "Path(", "resolve(",
                  "store.append", "average", "ranking", "scoring"):
        assert token not in source, token
    assert source.count("threshold_distance") == 1                                                # 禁止の一覧の中だけ
    tree = ast.parse(MODULE.read_text(encoding="utf-8"))
    assert not any(isinstance(node, ast.BinOp) for node in ast.walk(tree))                        # 算術は無い
    assert not any(isinstance(node, ast.Name) and node.id in {"float", "round", "max", "min"}
                   for node in ast.walk(tree))
    assert not any(isinstance(node, ast.Attribute) and node.attr in sm.FORBIDDEN_RESULT_FIELDS
                   for node in ast.walk(tree))
    assert sm.SCREENER_MATCH_DEFINITION.startswith("ISSUER_SATISFIES_EVERY_CRITERION")
    assert sm.FORBIDDEN_RESULT_FIELDS[0] == "threshold_distance"
    assert set(sm.__all__) >= {"Criterion", "CriteriaPolicy", "EvaluationContext", "CriterionResult", "ScreenerResult",
                               "ScreenerAuthorityMode", "PeriodRule", "CriterionOperator", "CriteriaComposition",
                               "CriterionState", "ScreenerState", "DataCompleteness", "canonical_threshold"}
    for path in sorted((REPO_ROOT / PHASE8_PACKAGE).glob("*.py")):
        if path.stem not in ("screener_criteria_model", "screener_evaluator"):                 # 消費は B2 の評価器だけ
            assert "screener_criteria" not in path.read_text(encoding="utf-8"), path.name       # 凍結の層は知らない
