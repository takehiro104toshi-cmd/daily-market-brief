"""Phase 3.6 J-Quants Production Data Strategy のオフラインテスト（ネットワーク不使用）。

registry / J-Quants First gate / frequency classification / morning contract / rolling window /
gap detection / incremental plan & apply（欠落だけ・冪等・bounded retry）/ master diff /
corporate action policy / weekly flow / financial & earnings strategy / TOPIX alignment /
storage & request budget / failure & retry / schema drift / health / readiness /
52週判断 / morning simulation（look-ahead 0）/ docs & rule presence。
"""
from __future__ import annotations

import json
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

import pytest

from src.intelligence.context.snapshot import leaked_contexts
from src.intelligence.context.store import ContextStore
from src.intelligence.facts.store import FactStore
from src.intelligence.internals.config import InternalsConfig
from src.intelligence.internals.ingest import InternalsIngestor, fetch_daily_bars_by_date
from src.intelligence.internals.pipeline import build_internals, internals_contexts
from src.intelligence.internals.snapshot import morning_internals_snapshot
from src.intelligence.jquants_ops import fifty_two_week
from src.intelligence.jquants_ops.capability_gate import (
    ALREADY_AVAILABLE,
    CURRENT_PLAN_UNSUPPORTED,
    DEFER,
    NEEDS_NEW_ENDPOINT,
    PLAN_UPGRADE_CANDIDATE_GATE,
    CapabilityRequest,
    evaluate_capability,
    standing_audit,
)
from src.intelligence.jquants_ops.config import OpsConfig, config_from_mapping, load_ops_config
from src.intelligence.jquants_ops.corporate_actions import POLICY, corporate_action_report
from src.intelligence.jquants_ops.earnings_calendar import latest_schedule_per_code, plan_earnings_refresh
from src.intelligence.jquants_ops.failure_policy import (
    AUTH_FAILURE,
    EMPTY_RESPONSE,
    NOT_ENTITLED as FAIL_NOT_ENTITLED,
    NO_CREDENTIALS,
    OK,
    PARTIAL_DATA,
    RATE_LIMIT,
    SCHEMA_CHANGE,
    TIMEOUT,
    ABSTAIN,
    CONTINUE,
    DEGRADED as IMPACT_DEGRADED,
    RetryPolicy,
    classify_failure,
    fetch_with_retry,
    morning_impact,
)
from src.intelligence.jquants_ops.financial_summary import plan_financial_refresh
from src.intelligence.jquants_ops.health import FRESH_CURRENT, FRESH_STALE, health_snapshot
from src.intelligence.jquants_ops.incremental import (
    BLOCKED,
    DAILY_UPDATE,
    NOOP,
    REPAIR,
    SEED,
    apply_update,
    plan_update,
    recompute_affected,
)
from src.intelligence.jquants_ops.master_refresh import (
    KNOWN_LIMITATION_HISTORICAL_UNIVERSE,
    diff_master,
    refresh_due,
    snapshot_dates_for_seed,
    strategy as master_strategy,
)
from src.intelligence.jquants_ops.morning_contract import morning_contract
from src.intelligence.jquants_ops.plan_upgrade_register import LIGHT_SUFFICIENT, REGISTER, summary
from src.intelligence.jquants_ops.readiness import (
    DEGRADED,
    NOT_READY,
    READY,
    READY_WITH_WARNINGS,
    morning_readiness,
)
from src.intelligence.jquants_ops.registry import (
    ALREADY_INGESTED,
    ALTERNATIVE_APPROVED_SOURCE,
    AVAILABLE_ON_CURRENT_PLAN,
    FREQUENCY_CLASSES,
    JQUANTS_DATASETS,
    NOT_ENTITLED,
    REGISTRY,
    ROLE_INTERNALS,
    ROLE_OPTIONAL,
    ROLE_REQUIRED,
    STATUS_VOCABULARY,
    frequency_table,
)
from src.intelligence.jquants_ops.request_budget import request_budget
from src.intelligence.jquants_ops.rolling_window import (
    WindowPolicy,
    affected_sessions,
    calculation_sessions,
    policy_from_config,
)
from src.intelligence.jquants_ops.schema_drift import (
    REQUIRED_FIELD_MISSING,
    SCHEMA_OK,
    UNKNOWN_FIELDS_ADDED,
    check_schema,
)
from src.intelligence.jquants_ops.session_gap import (
    CALENDAR_UNKNOWN,
    CURRENT,
    FUTURE_DATA,
    MISSING_SESSION,
    PARTIAL_SESSION,
    STALE,
    detect_gaps,
    expected_sessions_for_window,
)
from src.intelligence.jquants_ops.storage_budget import storage_budget
from src.intelligence.jquants_ops.topix_strategy import same_session_alignment, topix_daily_params
from src.intelligence.jquants_ops.weekly_flow import MODE_CHECK, MODE_SEED, plan_flow_refresh
from src.intelligence.market.jquants_light_datasets import INGESTED_DATASETS
from src.intelligence.market.jquants_light_store import JQuantsLightStore
from src.intelligence.market.jquants_records import PARSERS
from src.intelligence.market.jquants_v2_client import JQuantsV2Client
from tests.intelligence.test_market_internals import (
    API_KEY,
    CFG as INTERNALS_CFG,
    PREVIOUS,
    PROV,
    SESSION,
    SESSIONS,
    _fake_http,
    master_rows,
    populate,
)
from tests.intelligence.test_context_engine import NOW

POLICY = WindowPolicy(seed_sessions=70, active_calculation_sessions=60,
                      safety_buffer_sessions=10, max_metric_window=25)
RETRY = RetryPolicy(max_attempts=2, backoff_seconds=(0, 0))


# ============================================================ registry / gate

class TestRegistry:
    def test_vocabulary_and_fields(self):
        for cap in REGISTRY.values():
            assert cap.entitlement_status in STATUS_VOCABULARY + ("ENTITLEMENT_UNKNOWN",)
            assert cap.strategy_status in STATUS_VOCABULARY
            assert cap.frequency_class in FREQUENCY_CLASSES
            for f in ("endpoint", "plan", "publication_semantics", "historical_depth", "pagination",
                      "request_pattern", "canonical_store", "fallback_policy", "last_live_verified_at"):
                assert getattr(cap, f), f"{cap.dataset}.{f}"

    def test_ingested_datasets_are_registered_with_matching_required_fields(self):
        for spec in INGESTED_DATASETS:
            cap = REGISTRY[spec.key]
            assert cap.strategy_status == ALREADY_INGESTED
            assert cap.entitlement_status == AVAILABLE_ON_CURRENT_PLAN
            assert tuple(spec.required_fields) == cap.required_fields

    def test_not_entitled_entries_carry_403_evidence_and_are_not_reprobed(self):
        for cap in REGISTRY.values():
            if cap.entitlement_status == NOT_ENTITLED and cap.strategy_status != ALTERNATIVE_APPROVED_SOURCE:
                assert "403" in cap.last_live_verified_at, cap.dataset
                assert cap.endpoint.startswith("/")

    def test_frequency_table_covers_all(self):
        table = frequency_table()
        assert set(table) == set(FREQUENCY_CLASSES)
        assert "daily_bars" in table["DAILY"] and "investor_types" in table["WEEKLY"]
        assert "listed_master" in table["REFERENCE"] and "markets_calendar" in table["REFERENCE"]
        assert "fins_summary" in table["EVENT_DRIVEN"] and "equities_earnings_cal" in table["EVENT_DRIVEN"]
        assert "topix" in table["DAILY"]

    def test_morning_roles(self):
        assert REGISTRY["topix"].morning_role == ROLE_REQUIRED
        assert REGISTRY["markets_calendar"].morning_role == ROLE_REQUIRED
        assert REGISTRY["daily_bars"].morning_role == ROLE_INTERNALS
        assert REGISTRY["investor_types"].morning_role == ROLE_OPTIONAL
        assert "fins_summary" in JQUANTS_DATASETS and "nikkei225" not in JQUANTS_DATASETS


class TestCapabilityGate:
    def test_standing_audit_matches_documented_table(self):
        audit = {r["request"]: r["outcome"] for r in standing_audit()}
        assert audit == {
            "japan_market_breadth": ALREADY_AVAILABLE, "topix_close": ALREADY_AVAILABLE,
            "nikkei225_close": ALREADY_AVAILABLE, "sector_short_ratio": PLAN_UPGRADE_CANDIDATE_GATE,
            "fifty_two_week_high_low": DEFER, "weekly_investor_flow": ALREADY_AVAILABLE,
            "usd_jpy_close": ALREADY_AVAILABLE, "intraday_am_close": PLAN_UPGRADE_CANDIDATE_GATE,
        }

    def test_unknown_dataset_needs_probe_not_guess(self):
        d = evaluate_capability(CapabilityRequest(name="x", description="",
                                                  candidate_datasets=("nonexistent",)))
        assert d.outcome == NEEDS_NEW_ENDPOINT

    def test_missing_field_needs_new_endpoint(self):
        d = evaluate_capability(CapabilityRequest(name="x", description="",
                                                  candidate_datasets=("daily_bars",),
                                                  required_fields=("Code", "Dividend")))
        assert d.outcome == NEEDS_NEW_ENDPOINT and "Dividend" in d.reason

    def test_deferred_entitlement_unknown_is_unsupported(self):
        d = evaluate_capability(CapabilityRequest(name="x", description="",
                                                  candidate_datasets=("fins_earnings_date",)))
        assert d.outcome == CURRENT_PLAN_UNSUPPORTED

    def test_plan_upgrade_register_does_not_inflate(self):
        s = summary()
        assert s["upgrade_candidates"] == ["markets_short_ratio"]
        assert "LIGHT_SUFFICIENT" in s["overall"]
        assert any(e.verdict == LIGHT_SUFFICIENT for e in REGISTER)

    def test_rule_is_documented_project_wide(self):
        assert "J-Quants First" in Path("CLAUDE.md").read_text(encoding="utf-8")
        assert Path("docs/databank/JQUANTS_FIRST_RULE.md").is_file()


# ============================================================ contract / window

class TestMorningContract:
    def test_previous_session_and_roles(self):
        c = morning_contract("2026-09-02", SESSIONS)
        assert c.previous_session == SESSION
        assert c.cutoff_utc == "2026-09-01T21:00:00+00:00"
        assert "topix" in c.as_dict()["required"] and "daily_bars" in c.as_dict()["internals"]
        daily = next(i for i in c.items if i.dataset == "daily_bars")
        assert daily.expected_reference == SESSION and not daily.must_be_present
        weekly = next(i for i in c.items if i.dataset == "investor_types")
        assert "published" in weekly.expected_rule and "today" in weekly.expected_rule
        assert all(i.must_be_present == (i.morning_role == ROLE_REQUIRED) for i in c.items)


class TestRollingWindow:
    def test_policy_is_valid_and_separates_windows(self):
        assert POLICY.validate() == []
        assert POLICY.required_sessions == 35 and POLICY.minimum_sessions_for_all_metrics == 26
        assert POLICY.retention_canonical == "canonical_append_only_never_delete"

    def test_exactly_25_is_forbidden(self):
        bad = WindowPolicy(seed_sessions=20, active_calculation_sessions=25,
                           safety_buffer_sessions=0, max_metric_window=25)
        problems = bad.validate()
        assert len(problems) == 3
        assert WindowPolicy(seed_sessions=25, active_calculation_sessions=25,
                            safety_buffer_sessions=0, max_metric_window=25).validate()

    def test_calculation_window_does_not_delete(self):
        stored = [f"2026-01-{i:02d}" for i in range(1, 29)] + SESSIONS
        active = calculation_sessions(stored, WindowPolicy(70, 30, 10, 25))
        assert len(active) == 30 and active[-1] == SESSION and len(stored) > 30

    def test_affected_sessions_look_back_max_window(self):
        start, end = affected_sessions([SESSION], SESSIONS, POLICY)
        assert start == SESSIONS[0] and end == SESSION           # 27 sessions < 26 look-back → 先頭
        start2, _ = affected_sessions([SESSIONS[26]], SESSIONS + ["2026-09-02"], WindowPolicy(70, 60, 10, 2))
        assert start2 == SESSIONS[23]

    def test_config_yaml_section(self):
        cfg = load_ops_config()
        assert policy_from_config(cfg).validate() == []
        assert cfg.retry_max_attempts == 2 and cfg.master_refresh_days == 7
        assert config_from_mapping(None) == OpsConfig()


# ============================================================ gap / incremental

class TestSessionGap:
    def test_states(self):
        rows = {s: 4400 for s in SESSIONS}
        rows[SESSIONS[5]] = 0
        rows[SESSIONS[10]] = 1000                       # partial
        rows["2026-09-03"] = 4400                       # future
        r = detect_gaps(dataset="daily_bars", expected_sessions=SESSIONS, rows_by_session=rows,
                        latest_completed=SESSION)
        by = {s.session_date: s.status for s in r.states}
        assert by[SESSIONS[5]] == MISSING_SESSION and by[SESSIONS[10]] == PARTIAL_SESSION
        assert by[SESSION] == CURRENT and r.future_sessions == ("2026-09-03",)
        assert r.overall == MISSING_SESSION and r.to_fetch == sorted([SESSIONS[5], SESSIONS[10]])
        assert r.expected_rows == 4400

    def test_stale_future_current_unknown(self):
        rows = {s: 4400 for s in SESSIONS[:-1]}
        assert detect_gaps(dataset="d", expected_sessions=SESSIONS, rows_by_session=rows,
                           latest_completed=SESSION).overall == STALE
        full = {s: 4400 for s in SESSIONS}
        assert detect_gaps(dataset="d", expected_sessions=SESSIONS, rows_by_session=full,
                           latest_completed=SESSION).overall == CURRENT
        assert detect_gaps(dataset="d", expected_sessions=SESSIONS, rows_by_session=dict(full, **{"2026-09-03": 1}),
                           latest_completed=SESSION).overall == FUTURE_DATA
        assert detect_gaps(dataset="d", expected_sessions=[], rows_by_session=full,
                           latest_completed=None).overall == CALENDAR_UNKNOWN

    def test_expected_window(self):
        assert expected_sessions_for_window(SESSIONS, SESSION, 5) == SESSIONS[-5:]
        assert expected_sessions_for_window(SESSIONS, PREVIOUS, 3) == SESSIONS[-4:-1]


class TestIncremental:
    def _gap(self, rows, latest=SESSION):
        return detect_gaps(dataset="daily_bars", expected_sessions=SESSIONS, rows_by_session=rows,
                           latest_completed=latest)

    def test_plan_modes(self):
        full = {s: 4400 for s in SESSIONS}
        assert plan_update(self._gap(full), policy=POLICY, expected_sessions=SESSIONS).mode == NOOP
        daily = plan_update(self._gap({s: 4400 for s in SESSIONS[:-1]}), policy=POLICY,
                            expected_sessions=SESSIONS)
        assert daily.mode == DAILY_UPDATE and daily.sessions_to_fetch == (SESSION,) and daily.requests_estimate == 1
        rows = dict(full); rows[SESSIONS[5]] = 0
        repair = plan_update(self._gap(rows), policy=POLICY, expected_sessions=SESSIONS)
        assert repair.mode == REPAIR and repair.sessions_to_fetch == (SESSIONS[5],)
        assert repair.repair_range == (SESSIONS[5], SESSIONS[5])
        seed = plan_update(self._gap({}), policy=POLICY, expected_sessions=SESSIONS, seed_count=10)
        assert seed.mode == SEED and len(seed.sessions_to_fetch) == 10
        blocked = plan_update(detect_gaps(dataset="d", expected_sessions=[], rows_by_session={},
                                          latest_completed=None), policy=POLICY, expected_sessions=[])
        assert blocked.mode == BLOCKED and blocked.requests_estimate == 0

    def test_repair_outside_active_window_is_not_refetched(self):
        rows = {s: 4400 for s in SESSIONS}
        rows[SESSIONS[0]] = 0
        plan = plan_update(self._gap(rows), policy=WindowPolicy(70, 10, 5, 5), expected_sessions=SESSIONS)
        assert plan.mode == NOOP

    def test_apply_fetches_only_missing_and_is_rerun_safe(self, tmp_path):
        calls = []
        client = JQuantsV2Client(_fake_http(calls), env={"JQUANTS_API_KEY": API_KEY}, sleeper=lambda s: None)
        store = JQuantsLightStore(tmp_path / "jquants_light")
        store.append("listed_master", [PARSERS["listed_master"](r, PROV) for r in master_rows()])
        ing = InternalsIngestor(client, store, interval_seconds=0, sleeper=lambda s: None)
        for s in SESSIONS[:-2] + [SESSIONS[-2]]:                   # seed: 最新だけ欠く
            fetch_daily_bars_by_date(ing, s)
        rows = {s: len(store.prices_on(s)) for s in SESSIONS}
        plan = plan_update(self._gap(rows), policy=POLICY, expected_sessions=SESSIONS)
        assert plan.mode == DAILY_UPDATE
        before = ing.stats.requests
        result = apply_update(ing, plan, retry=RETRY, sleeper=lambda s: None)
        assert result.fetched == [SESSION] and result.requests == 1 and result.rows_added > 0
        assert ing.stats.requests - before == 1
        facts, contexts = FactStore(tmp_path), ContextStore(tmp_path)
        rec = recompute_affected(store, new_sessions=[SESSION], policy=POLICY,
                                 internals_config=INTERNALS_CFG, fact_store=facts,
                                 context_store=contexts, now=NOW)
        assert rec.facts_added == rec.facts_built > 0 and rec.contexts_added == rec.contexts_built > 0
        # rerun: 0 リクエスト・重複 0
        rows = {s: len(store.prices_on(s)) for s in SESSIONS}
        plan2 = plan_update(self._gap(rows), policy=POLICY, expected_sessions=SESSIONS)
        assert plan2.mode == NOOP
        result2 = apply_update(ing, plan2, retry=RETRY, sleeper=lambda s: None)
        assert result2.requests == 0
        rec2 = recompute_affected(store, new_sessions=[SESSION], policy=POLICY,
                                  internals_config=INTERNALS_CFG, fact_store=facts,
                                  context_store=contexts, now=NOW)
        assert rec2.facts_added == 0 and rec2.contexts_added == 0 and rec2.facts_skipped == rec2.facts_built
        canonical = sum(1 for _ in store.iter_canonical("daily_bars"))
        assert canonical == store.count("daily_bars")
        assert all(API_KEY not in u for u in calls)
        facts.close(); contexts.close(); store.close()


# ============================================================ failure / retry / schema

class TestFailurePolicy:
    @pytest.mark.parametrize("kw,expected", [
        (dict(ok=True, http=200, rows=10), OK),
        (dict(ok=True, http=200, rows=0), EMPTY_RESPONSE),
        (dict(ok=True, http=200, rows=10, expected_rows_min=100), PARTIAL_DATA),
        (dict(ok=False, http=0, error_kind="no_credentials"), NO_CREDENTIALS),
        (dict(ok=False, http=403, error_kind="auth_error", failure_cause="plan_not_entitled"), FAIL_NOT_ENTITLED),
        (dict(ok=False, http=401, error_kind="auth_error"), AUTH_FAILURE),
        (dict(ok=False, http=429, error_kind="http_error"), RATE_LIMIT),
        (dict(ok=False, http=0, error_kind="connection", error_detail="URLError: timed out"), TIMEOUT),
        (dict(ok=False, http=200, error_kind="schema_error"), SCHEMA_CHANGE),
        (dict(ok=False, http=500, error_kind="http_error"), "HTTP_ERROR"),
    ])
    def test_classification(self, kw, expected):
        assert classify_failure(**kw) == expected

    def test_impact_matrix(self):
        assert morning_impact(ROLE_REQUIRED, AUTH_FAILURE) == ABSTAIN
        assert morning_impact(ROLE_INTERNALS, TIMEOUT) == IMPACT_DEGRADED
        assert morning_impact(ROLE_OPTIONAL, AUTH_FAILURE) == CONTINUE
        assert morning_impact(ROLE_REQUIRED, OK) == CONTINUE

    def test_bounded_retry_only_for_transient(self):
        class O:
            def __init__(self, ok, http, kind=""):
                self.ok, self.http, self.error_kind, self.rows = ok, http, kind, 5
                self.failure_cause, self.error_detail = "", ""
        seq = [O(False, 429, "http_error"), O(True, 200)]
        sleeps = []
        out, kind, log = fetch_with_retry(lambda: seq.pop(0), policy=RetryPolicy(2, (3, 5)),
                                          sleeper=sleeps.append)
        assert kind == OK and len(log.attempts) == 2 and sleeps == [3.0]
        seq = [O(False, 401, "auth_error"), O(True, 200)]
        out, kind, log = fetch_with_retry(lambda: seq.pop(0), policy=RetryPolicy(3, (1,)),
                                          sleeper=lambda s: pytest.fail("must not sleep"))
        assert kind == AUTH_FAILURE and len(log.attempts) == 1          # retry storm なし
        seq = [O(False, 500, "http_error")] * 5
        out, kind, log = fetch_with_retry(lambda: seq.pop(0), policy=RetryPolicy(2, (0,)),
                                          sleeper=lambda s: None)
        assert len(log.attempts) == 2                                    # 上限で停止


class TestSchemaDrift:
    def test_statuses(self):
        base = REGISTRY["daily_bars"].observed_fields
        assert check_schema("daily_bars", base).status == SCHEMA_OK
        d = check_schema("daily_bars", base + ("NewField",))
        assert d.status == UNKNOWN_FIELDS_ADDED and d.unknown_fields == ("NewField",) and not d.blocks_ingest
        m = check_schema("daily_bars", ("Code", "Date"))
        assert m.status == REQUIRED_FIELD_MISSING and m.missing_required == ("C",) and m.blocks_ingest


# ============================================================ master / corporate / flow / events / topix

class TestMasterAndEvents:
    def test_master_diff_detects_changes(self):
        a = [dict(code="1", market_code="0111", sector17_code="1", sector33_code="10", scale_category="TOPIX Core30"),
             dict(code="2", market_code="0111", sector17_code="1", sector33_code="10", scale_category="-")]
        b = [dict(code="1", market_code="0112", sector17_code="2", sector33_code="10", scale_category="TOPIX Large70"),
             dict(code="3", market_code="0111", sector17_code="1", sector33_code="10", scale_category="-")]
        d = diff_master(a, b, from_date="2026-06-26", to_date="2026-09-02")
        assert d.added == ("3",) and d.removed == ("2",)
        assert d.market_changes == (("1", "0111", "0112"),) and d.sector17_changes == (("1", "1", "2"),)
        assert d.scale_changes == (("1", "TOPIX Core30", "TOPIX Large70"),) and d.total_changes == 5
        assert refresh_due(latest_effective_date="2026-08-20", today="2026-09-02", interval_days=7)
        assert not refresh_due(latest_effective_date="2026-09-01", today="2026-09-02", interval_days=7)
        assert snapshot_dates_for_seed(SESSIONS, interval_days=7)[:2] == [SESSIONS[0], SESSIONS[5]]
        assert master_strategy()["limitation"] == KNOWN_LIMITATION_HISTORICAL_UNIVERSE

    def test_corporate_action_policy_and_report(self, tmp_path):
        light = populate(JQuantsLightStore(tmp_path / "jquants_light"))
        build = build_internals(light, INTERNALS_CFG, SESSIONS, now=NOW)
        report = corporate_action_report(build.builds)
        assert report["excluded_total"] == 1 and report["sessions_affected"] == 1
        assert list(report["per_session"].values()) == [["13020"]]
        assert POLICY_KEYS <= set(report["policy"])
        light.close()

    def test_weekly_flow_plan_new_only(self, tmp_path):
        light = JQuantsLightStore(tmp_path / "jquants_light")
        assert plan_flow_refresh(light, today=date(2026, 9, 2), section="TSEPrime")["mode"] == MODE_SEED
        populate(light)
        plan = plan_flow_refresh(light, today=date(2026, 9, 2), section="TSEPrime", lookback_days=14)
        assert plan["mode"] == MODE_CHECK and plan["latest_stored_period_end"] == "2026-08-29"
        assert plan["params"] == {"from": "2026-08-15", "to": "2026-09-02"} and plan["requests"] == 1
        light.close()

    def test_financial_and_earnings_plans(self, tmp_path):
        light = populate(JQuantsLightStore(tmp_path / "jquants_light"))
        light.append("equities_earnings_cal", [PARSERS["equities_earnings_cal"](
            {"Code": "13010", "Date": SESSION, "CoName": "x"}, PROV)])
        plan = plan_financial_refresh(light, previous_session=SESSION, date_mode_available=False)
        assert plan["codes"] == ["13010"] and plan["requests"] == 1
        plan_d = plan_financial_refresh(light, previous_session=SESSION, date_mode_available=True)
        assert plan_d["requests"] == 1 and plan_d["params"] == {"date": SESSION}
        assert plan_earnings_refresh(today=date(2026, 9, 2), days_ahead=90)["params"]["to"] == "2026-12-01"
        rows = [{"code": "1", "announcement_date": "2026-11-05", "provenance": {"retrieved_at": "2026-08-01"}},
                {"code": "1", "announcement_date": "2026-11-06", "provenance": {"retrieved_at": "2026-09-01"}}]
        assert latest_schedule_per_code(rows)["1"]["announcement_date"] == "2026-11-06"
        light.close()

    def test_topix_alignment_and_params(self):
        assert same_session_alignment(SESSIONS, SESSIONS)["aligned"]
        mis = same_session_alignment(SESSIONS, SESSIONS[:-1])
        assert not mis["aligned"] and mis["latest_common_session"] == PREVIOUS
        assert topix_daily_params(SESSION, date(2026, 9, 2)) == {"from": "2026-09-02", "to": "2026-09-02"}


POLICY_KEYS = {"breadth", "returns", "rolling", "adjusted_close", "version"}


# ============================================================ health / readiness / budgets / 52w

class TestHealthAndReadiness:
    def _store(self, tmp_path, with_calendar=True):
        light = populate(JQuantsLightStore(tmp_path / "jquants_light"))
        if with_calendar:
            days = SESSIONS + [(date(2026, 9, 1) + timedelta(days=i)).isoformat() for i in range(1, 70)]
            light.append("markets_calendar", [PARSERS["markets_calendar"]({"Date": d, "HolDiv": "1"}, PROV)
                                              for d in days])
        light.append("equities_earnings_cal", [PARSERS["equities_earnings_cal"](
            {"Code": "13010", "Date": "2026-10-05", "CoName": "x"}, PROV)])
        return light

    def test_ready_when_all_current(self, tmp_path):
        light = self._store(tmp_path)
        now = datetime(2026, 9, 2, 3, 0, tzinfo=timezone.utc)
        health = health_snapshot(light=light, latest_completed=SESSION, now=now, topix_latest=SESSION)
        assert health["daily_bars"].freshness == FRESH_CURRENT
        assert health["investor_types"].freshness == FRESH_CURRENT
        assert health["listed_master"].freshness == FRESH_CURRENT
        assert morning_readiness(health).status == READY
        light.close()

    def test_degraded_and_not_ready(self, tmp_path):
        light = self._store(tmp_path)
        now = datetime(2026, 9, 3, 3, 0, tzinfo=timezone.utc)
        h = health_snapshot(light=light, latest_completed="2026-09-02", now=now, topix_latest="2026-09-02")
        assert h["daily_bars"].freshness == FRESH_STALE
        assert morning_readiness(h).status == DEGRADED
        h2 = health_snapshot(light=light, latest_completed="2026-09-02", now=now, topix_latest=SESSION)
        assert morning_readiness(h2).status == NOT_READY
        h3 = health_snapshot(light=light, latest_completed=SESSION, now=datetime(2026, 9, 20, tzinfo=timezone.utc),
                             topix_latest=SESSION)
        r3 = morning_readiness(h3)
        assert r3.status in (READY_WITH_WARNINGS, DEGRADED)          # 週次flow/master が古い
        light.close()

    def test_budgets(self):
        b = request_budget(POLICY)
        assert b["normal_morning"]["total"] == 4 and b["initial_seed"]["daily_bars"] == 70
        assert b["repair_day"]["daily_bars"] == 3
        s = storage_budget()
        assert s["annual_mb"]["total"] > s["monthly_mb"]["total"] > s["daily_mb"]["total"] > 0
        assert "never deleted" in s["retention"]["canonical"]

    def test_fifty_two_week_decision(self):
        d = fifty_two_week.decision(stored_sessions=60)
        assert d["decision"] == fifty_two_week.IMPLEMENT_LATER
        assert d["missing_sessions_for_one_time_seed"] == 190
        assert "no 5-year backfill" in d["reason"]


class TestMorningSimulation:
    def test_replay_has_no_look_ahead(self, tmp_path):
        light = populate(JQuantsLightStore(tmp_path / "jquants_light"))
        build = build_internals(light, INTERNALS_CFG, SESSIONS, now=NOW)
        items = internals_contexts(build, INTERNALS_CFG, now=NOW)
        for morning in SESSIONS[-3:] + ["2026-09-02"]:
            snap = morning_internals_snapshot(items, morning, config=INTERNALS_CFG, generated_at=NOW)
            assert leaked_contexts(snap.items, snap.cutoff) == []
            assert all(i.time.session_date < morning for i in snap.items)
        light.close()


class TestPilotOffline:
    def test_pilot_runs_offline_and_emits_markers(self, tmp_path, monkeypatch, capsys):
        root = tmp_path / "root" / "jquants_ops_pilot"
        light = populate(JQuantsLightStore(root / "jquants_light"))
        light.append("markets_calendar", [PARSERS["markets_calendar"]({"Date": d, "HolDiv": "1"}, PROV)
                                          for d in SESSIONS])
        light.close()
        monkeypatch.setenv("INTELLIGENCE_DATA_ROOT", str(tmp_path / "root"))
        from src.intelligence.jquants_ops import pilot
        assert pilot.main(["--skip-fetch", "--seed", "20", "--mornings", "3"]) == 0
        out = capsys.readouterr().out
        markers = {line.split("::")[1] for line in out.splitlines() if line.startswith("::P36_")}
        assert {"P36_INPUT", "P36_REGISTRY", "P36_REPAIR", "P36_DAILY", "P36_HEALTH", "P36_READINESS",
                "P36_MORNING_SIM", "P36_STORAGE", "P36_REQUESTS", "P36_SECURITY", "P36_SUMMARY"} <= markers
        summary = json.loads(next(l for l in out.splitlines() if l.startswith("::P36_SUMMARY::")).split("::P36_SUMMARY::")[1])
        assert summary["total_requests"] == 0 and summary["look_ahead_leaks"] == 0
        assert not (Path("data") / "vnext" / "jquants_ops_pilot").exists()
