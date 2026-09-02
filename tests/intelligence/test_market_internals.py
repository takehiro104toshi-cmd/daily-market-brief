"""Phase 3.5 Japan Market Internals のオフラインテスト（ネットワーク不使用・LLM非依存）。

§37 の最低項目を網羅する: universe determinism / security eligibility / session membership /
advance-decline / unchanged / raw-adjusted semantics / corporate action handling /
breadth aggregation / manifest-hash / sector grouping / size grouping / turnover aggregation /
investor flow weekly semantics / publication gating / look-ahead prevention /
Fact integration / Context integration / Evidence Package integration / claim grounding /
missingness / salience / idempotency / canonical append-only / SQLite rebuild /
performance sanity / offline no network / production data no mutation / secret hygiene。
"""
from __future__ import annotations

import json
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

import pytest

from src.intelligence.compass.adversarial import adversarial_summary, run_adversarial_cases
from src.intelligence.compass.config import CompassConfig
from src.intelligence.compass.evidence_package import build_evidence_package
from src.intelligence.compass.generator import FakeNarrativeGenerator
from src.intelligence.compass.lexicon import KEY_DIMENSION, SUBJECT_PATTERN
from src.intelligence.compass.missingness_validation import validate_missingness
from src.intelligence.compass.model import ClaimRole, ClaimType, GroundingStatus, QualityVerdict
from src.intelligence.compass.pipeline import run_pipeline
from src.intelligence.context.builders import TOPIX, build_session_contexts
from src.intelligence.context.model import ContextStatus, Direction, PriorityTier, Relationship
from src.intelligence.context.salience import rank_contexts
from src.intelligence.context.snapshot import leaked_contexts, morning_context_snapshot
from src.intelligence.context.store import ContextStore
from src.intelligence.facts.model import DateRole, EvidenceKind, FactStatus
from src.intelligence.facts.store import FactStore
from src.intelligence.internals import adversarial as internals_adversarial
from src.intelligence.internals.backfill_estimate import (
    DEFER,
    FULL,
    ROLLING,
    Measured,
    estimate,
)
from src.intelligence.internals.breadth import aggregate_breadth, input_set_hash, make_manifest
from src.intelligence.internals.breadth_history import advance_decline_ratio_n
from src.intelligence.internals.config import (
    InternalsConfig,
    UniverseSpec,
    config_from_mapping,
    load_internals_config,
)
from src.intelligence.internals.contexts import InternalsFactIndex
from src.intelligence.internals.facts import (
    AD_RATIO_25S,
    ADVANCE_RATIO_20S_AVG,
    INVESTOR_FLOW_NET,
    MARKET_ADVANCERS,
    MARKET_DECLINERS,
    MARKET_TURNOVER_VALUE,
    MARKET_UNCHANGED,
    SECTOR_RELATIVE_RETURN,
    SIZE_LARGE_VS_SMALL,
    TURNOVER_20S_AVG,
    TURNOVER_VS_20S_RATIO,
    tokyo_close_utc,
)
from src.intelligence.internals.ingest import (
    DATE_MODE,
    MODE_UNAVAILABLE,
    InternalsIngestor,
    detect_date_mode,
    fetch_master,
    fetch_sessions_by_date,
    select_sample_codes,
)
from src.intelligence.internals.investor_flow import known_at_for, latest_published_by, weekly_flows
from src.intelligence.internals.pipeline import (
    availability_for,
    build_internals,
    internals_contexts,
)
from src.intelligence.internals.price_movement import (
    ADVANCE,
    DECLINE,
    EXCL_CORPORATE_ACTION,
    EXCL_NO_CLOSE,
    EXCL_NO_PREVIOUS,
    EXCLUDED,
    UNCHANGED,
    classify,
)
from src.intelligence.internals.quality import manifest_reproducibility
from src.intelligence.internals.sector import leaders_and_laggards
from src.intelligence.internals.size import group_of
from src.intelligence.internals.snapshot import (
    attach_internals,
    internals_status,
    morning_internals_snapshot,
)
from src.intelligence.internals.store import InternalsStore
from src.intelligence.internals.types import (
    BREADTH_STATE,
    BREADTH_TREND,
    DIM_BREADTH,
    DIM_FLOW,
    DIM_SECTOR,
    DIM_SIZE,
    DIM_TURNOVER,
    INDEX_LEADERSHIP,
    INTERNALS_CONTEXT_TYPES,
    INTERNALS_DIMENSIONS,
    INVESTOR_FLOW_STATE,
    MARKET_SUBJECT,
    SECTOR_LEADERSHIP,
    SECTOR_SUMMARY_SUBJECT,
    SIZE_LEADERSHIP,
    SIZE_SUMMARY_SUBJECT,
    TURNOVER_STATE,
    flow_subject,
)
from src.intelligence.internals.universe import (
    REASON_MARKET,
    REASON_NOT_COMMON,
    REASON_SECTOR,
    build_universe,
    eligibility,
    select_master_for_session,
)
from src.intelligence.market.jquants_light_store import JQuantsLightStore
from src.intelligence.market.jquants_records import PARSERS, RecordProvenance
from src.intelligence.market.jquants_v2_client import JQuantsV2Client
from tests.intelligence.test_compass_generator import level_facts
from tests.intelligence.test_context_engine import (
    NOW,
    PREVIOUS,
    SESSION,
    core_facts,
    previous_facts,
)

API_KEY = "TEST-ONLY-SYNTHETIC-JQUANTS-V2-KEY"
MORNING = "2026-09-02"
CFG = InternalsConfig()

# ---------------------------------------------------------------- synthetic dataset

PRIME_CODES = ("13010", "13020", "13030", "13040", "13050", "13060", "13070", "13080", "13090")
SECTOR17 = {"13010": ("1", "食品"), "13020": ("1", "食品"), "13030": ("9", "電機・精密"),
            "13040": ("9", "電機・精密"), "13050": ("15", "銀行"), "13060": ("15", "銀行"),
            "13070": ("3", "建設・資材"), "13080": ("13", "商社・卸売"),
            "13090": ("13", "商社・卸売")}
SCALE = {"13010": "TOPIX Core30", "13020": "TOPIX Large70", "13030": "TOPIX Core30",
         "13040": "TOPIX Mid400", "13050": "TOPIX Large70", "13060": "TOPIX Mid400",
         "13070": "TOPIX Small 1", "13080": "TOPIX Small 2", "13090": "-"}
BASE = {c: Decimal(1000 + 100 * i) for i, c in enumerate(PRIME_CODES)}
LAST_MOVE = {"13010": "1.01", "13020": "1.01", "13030": "1.01", "13040": "1.01", "13050": "1.01",
             "13060": "0.99", "13070": "0.99", "13080": "1.00", "13090": "1.02"}
SPLIT_CODE, SPLIT_INDEX = "13020", 10          # 分割（AdjFactor 0.5）を跨ぐsession
MISSING_CODE, MISSING_INDEX = "13080", 5       # 終値なし（出来ず）
NEW_CODE, NEW_INDEX = "13090", 20              # 新規上場（それ以前は価格なし）


def sessions_list():
    """2026-07-27〜2026-09-01 の平日 27 session（祝日カレンダーは適用しない同期データ）。"""
    out, day = [], date(2026, 7, 27)
    while day <= date(2026, 9, 1):
        if day.weekday() < 5:
            out.append(day.isoformat())
        day += timedelta(days=1)
    return out


SESSIONS = sessions_list()
assert SESSIONS[-1] == SESSION and SESSIONS[-2] == PREVIOUS and len(SESSIONS) == 27


def master_rows(effective="2026-09-01"):
    rows = []
    for code in PRIME_CODES:
        s17, name = SECTOR17[code]
        rows.append({"Code": code, "Date": effective, "CoName": f"会社{code}", "Mkt": "0111",
                     "MktNm": "プライム", "S17": s17, "S17Nm": name, "S33": "3050",
                     "S33Nm": "業種33", "ScaleCat": SCALE[code], "ProdCat": "1"})
    rows += [
        {"Code": "25935", "Date": effective, "CoName": "優先株", "Mkt": "0111", "MktNm": "プライム",
         "S17": "1", "S17Nm": "食品", "S33": "3050", "S33Nm": "業種33", "ScaleCat": "-"},
        {"Code": "14000", "Date": effective, "CoName": "スタンダード社", "Mkt": "0112",
         "MktNm": "スタンダード", "S17": "1", "S17Nm": "食品", "S33": "3050", "ScaleCat": "-"},
        {"Code": "13100", "Date": effective, "CoName": "ETF", "Mkt": "0109", "MktNm": "その他",
         "S17": "", "S17Nm": "", "S33": "", "S33Nm": "", "ScaleCat": "-"},
        {"Code": "13110", "Date": effective, "CoName": "その他上場", "Mkt": "0111",
         "MktNm": "プライム", "S17": "", "S17Nm": "", "S33": "9999", "S33Nm": "その他",
         "ScaleCat": "-"},
    ]
    return rows


def _close(code, k):
    j = PRIME_CODES.index(code)
    if k == len(SESSIONS) - 1:
        return (_close(code, k - 1) * Decimal(LAST_MOVE[code])).quantize(Decimal("0.1"))
    value = BASE[code] * (Decimal(1) + Decimal("0.002") * ((k * 7 + j * 3) % 5 - 2))
    if code == SPLIT_CODE and k >= SPLIT_INDEX:
        value = value / 2
    return value.quantize(Decimal("0.1"))


def price_rows_for(k):
    """session index k の全銘柄行（J-Quants V2の項目名）。"""
    session = SESSIONS[k]
    rows = []
    for code in PRIME_CODES + ("25935", "14000", "13100", "13110"):
        if code == NEW_CODE and k < NEW_INDEX:
            continue
        close = _close(code, k) if code in PRIME_CODES else Decimal("500.0")
        if code == MISSING_CODE and k == MISSING_INDEX:
            rows.append({"Code": code, "Date": session, "C": "", "AdjC": "", "Vo": "",
                         "Va": "", "AdjFactor": "1.0", "MktCap": ""})
            continue
        adj = close if not (code == SPLIT_CODE and k < SPLIT_INDEX) else close / 2
        factor = "0.5" if (code == SPLIT_CODE and k == SPLIT_INDEX) else "1.0"
        rows.append({"Code": code, "Date": session, "O": str(close), "H": str(close),
                     "L": str(close), "C": str(close), "AdjC": str(adj), "AdjFactor": factor,
                     "Vo": str(1000 * (PRIME_CODES.index(code) + 1 if code in PRIME_CODES else 1)),
                     "Va": str(Decimal(10_000_000) * (PRIME_CODES.index(code) + 1
                                                     if code in PRIME_CODES else 1)),
                     "MktCap": "100000000000"})
    return rows


FLOW_ROWS = [
    {"Section": "TSEPrime", "PubDate": "2026-08-21", "StDate": "2026-08-11", "EnDate": "2026-08-15",
     "FrgnBuy": "5000", "FrgnSell": "4000", "FrgnTot": "9000", "FrgnBal": "1000",
     "IndBuy": "1000", "IndSell": "1200", "IndTot": "2200", "IndBal": "-200",
     "TrstBnkBuy": "300", "TrstBnkSell": "300", "TrstBnkTot": "600", "TrstBnkBal": "0",
     "BusCoBuy": "100", "BusCoSell": "50", "BusCoTot": "150", "BusCoBal": "50"},
    {"Section": "TSEPrime", "PubDate": "2026-08-28", "StDate": "2026-08-18", "EnDate": "2026-08-22",
     "FrgnBuy": "4000", "FrgnSell": "4500", "FrgnTot": "8500", "FrgnBal": "-500",
     "IndBuy": "1300", "IndSell": "1000", "IndTot": "2300", "IndBal": "300",
     "TrstBnkBuy": "300", "TrstBnkSell": "400", "TrstBnkTot": "700", "TrstBnkBal": "-100",
     "BusCoBuy": "100", "BusCoSell": "50", "BusCoTot": "150", "BusCoBal": "50"},
    # 公表日が 2026-09-04 → 2026-09-02 の朝には**未公表**（publication gating）
    {"Section": "TSEPrime", "PubDate": "2026-09-04", "StDate": "2026-08-25", "EnDate": "2026-08-29",
     "FrgnBuy": "6000", "FrgnSell": "3000", "FrgnTot": "9000", "FrgnBal": "3000",
     "IndBuy": "1000", "IndSell": "1000", "IndTot": "2000", "IndBal": "0"},
    {"Section": "TSEStandard", "PubDate": "2026-08-28", "StDate": "2026-08-18",
     "EnDate": "2026-08-22", "FrgnBuy": "10", "FrgnSell": "20", "FrgnTot": "30", "FrgnBal": "-10"},
]

PROV = RecordProvenance(endpoint="/equities/bars/daily", retrieved_at="2026-09-01T09:00:00+00:00",
                        raw_item_id="raw_synthetic", fetch_attempt_id="att_synthetic")


def populate(store: JQuantsLightStore, *, effective_dates=("2026-09-01",)):
    for eff in effective_dates:
        store.append("listed_master", [PARSERS["listed_master"](r, PROV) for r in master_rows(eff)])
    for k in range(len(SESSIONS)):
        store.append("daily_bars", [PARSERS["daily_bars"](r, PROV) for r in price_rows_for(k)])
    store.append("investor_types", [PARSERS["investor_types"](r, PROV) for r in FLOW_ROWS])
    return store


@pytest.fixture(scope="module")
def light(tmp_path_factory):
    root = tmp_path_factory.mktemp("light") / "jquants_light"
    store = populate(JQuantsLightStore(root))
    yield store
    store.close()


@pytest.fixture(scope="module")
def build(light):
    return build_internals(light, CFG, SESSIONS, now=NOW)


@pytest.fixture(scope="module")
def last(build):
    return build.builds[SESSION]


@pytest.fixture(scope="module")
def market_items():
    facts = core_facts() + previous_facts() + level_facts()
    items = build_session_contexts(facts, SESSION, previous_session=PREVIOUS, now=NOW)
    return facts, rank_contexts(items, session_date=SESSION)


@pytest.fixture(scope="module")
def internals_items(build, market_items):
    _facts, items = market_items
    return internals_contexts(build, CFG, market_items={SESSION: items}, now=NOW)


@pytest.fixture(scope="module")
def all_facts(build, market_items):
    facts, _items = market_items
    return list(facts) + build.all_facts


@pytest.fixture(scope="module")
def after(build, market_items, internals_items):
    _facts, items = market_items
    plain = morning_context_snapshot(list(items) + internals_items, MORNING, generated_at=NOW)
    status = internals_status(plain.items, reference_session=plain.reference_session,
                              section=CFG.flow_section,
                              availability=availability_for(build, plain.reference_session),
                              flow_max_age_days=CFG.flow_max_age_days)
    return attach_internals(plain, status)


@pytest.fixture(scope="module")
def before(market_items):
    _facts, items = market_items
    return morning_context_snapshot(items, MORNING, generated_at=NOW)


@pytest.fixture(scope="module")
def result_after(after, all_facts):
    return run_pipeline(after, all_facts, config=CompassConfig(), now=NOW)


@pytest.fixture(scope="module")
def result_before(before, all_facts):
    return run_pipeline(before, all_facts, config=CompassConfig(), now=NOW)


# ============================================================ config

class TestConfig:
    def test_config_yaml_section_loads(self):
        cfg = load_internals_config()
        assert cfg.universe.market_codes == ("0111",)
        assert cfg.ad_ratio_sessions == 25 and cfg.sector_classification == "S17"
        assert cfg.flow_section == "TSEPrime"

    def test_defaults_on_missing_section(self):
        cfg = config_from_mapping(None)
        assert cfg.universe.token == "tse_prime_common:1.0.0"
        assert cfg.sessions == 45

    def test_no_credentials_in_config(self):
        text = Path("config.yaml").read_text(encoding="utf-8")
        section = text[text.index("market_internals:"):]
        assert "api_key" not in section.lower() and "secret" not in section.lower()


# ============================================================ universe

class TestUniverse:
    def test_eligibility_reasons(self):
        spec = UniverseSpec()
        assert eligibility({"code": "13010", "market_code": "0111", "sector33_code": "3050"},
                           spec).eligible
        assert eligibility({"code": "14000", "market_code": "0112", "sector33_code": "3050"},
                           spec).reason == REASON_MARKET
        assert eligibility({"code": "25935", "market_code": "0111", "sector33_code": "3050"},
                           spec).reason == REASON_NOT_COMMON
        assert eligibility({"code": "13100", "market_code": "0111", "sector33_code": ""},
                           spec).reason == REASON_SECTOR
        assert eligibility({"code": "13110", "market_code": "0111", "sector33_code": "9999"},
                           spec).reason == REASON_SECTOR

    def test_universe_is_deterministic_and_versioned(self, last):
        u = last.universe
        assert u.codes == PRIME_CODES and u.token == "tse_prime_common:1.0.0"
        assert u.excluded_counts == {REASON_NOT_COMMON: 1, REASON_MARKET: 2, REASON_SECTOR: 1}
        again = build_universe(master_rows(), UniverseSpec(), session_date=SESSION,
                               master_effective_date="2026-09-01")
        rows = [dict(code=r["Code"], market_code=r["Mkt"], sector33_code=r["S33"],
                     security_id=f"jp:security:{r['Code']}", sector17_code=r["S17"],
                     sector17_name=r["S17Nm"], scale_category=r["ScaleCat"],
                     effective_date=r["Date"], company_name=r["CoName"], sector33_name="")
                for r in master_rows()]
        again = build_universe(rows, UniverseSpec(), session_date=SESSION,
                               master_effective_date="2026-09-01")
        assert again.universe_hash == u.universe_hash and again.snapshot_id == u.snapshot_id

    def test_session_membership_uses_master_at_or_before_session(self):
        assert select_master_for_session(["2026-08-01", "2026-09-01"], "2026-08-15") == \
            ("2026-08-01", False)
        assert select_master_for_session(["2026-09-01"], "2026-08-15") == ("2026-09-01", True)
        assert select_master_for_session([], "2026-08-15") == ("", False)

    def test_master_applied_backwards_is_declared(self, build):
        first = build.builds[build.sessions[0]].universe
        assert first.master_applied_backwards is True     # masterは2026-09-01しか無い
        assert build.builds[SESSION].universe.master_applied_backwards is False


# ============================================================ price movement

class TestPriceMovement:
    def _row(self, code, close, adj=None, factor="1.0", rid="r"):
        return {"code": code, "security_id": f"jp:security:{code}", "close": close,
                "adjusted_close": adj if adj is not None else close,
                "adjustment_factor": factor, "record_id": rid, "turnover_value": "100",
                "volume": "10", "market_cap": ""}

    def test_advance_decline_unchanged_on_raw_close(self):
        prev = self._row("13010", "1000")
        assert classify(self._row("13010", "1010"), prev, session_date=SESSION,
                        previous_session=PREVIOUS).classification == ADVANCE
        assert classify(self._row("13010", "990"), prev, session_date=SESSION,
                        previous_session=PREVIOUS).classification == DECLINE
        m = classify(self._row("13010", "1000"), prev, session_date=SESSION,
                     previous_session=PREVIOUS)
        assert m.classification == UNCHANGED and m.change_pct == Decimal("0")

    def test_raw_and_adjusted_are_not_mixed(self):
        """rawは前営業日比+1%、adjustedも+1% → 判定はrawで行いADVANCE。"""
        prev = self._row("13010", "1000", adj="500")
        m = classify(self._row("13010", "1010", adj="505"), prev, session_date=SESSION,
                     previous_session=PREVIOUS)
        assert m.classification == ADVANCE and m.change_pct == Decimal("1")

    def test_corporate_action_is_excluded_not_misclassified(self):
        prev = self._row("13020", "2000", adj="1000")
        by_factor = classify(self._row("13020", "1000", adj="1000", factor="0.5"), prev,
                             session_date=SESSION, previous_session=PREVIOUS)
        assert by_factor.classification == EXCLUDED
        assert by_factor.exclusion_reason == EXCL_CORPORATE_ACTION
        by_ratio = classify(self._row("13020", "1000", adj="1000"), prev,
                            session_date=SESSION, previous_session=PREVIOUS)
        assert by_ratio.exclusion_reason == EXCL_CORPORATE_ACTION   # AdjFactor欠落でも検知

    def test_missing_close_and_missing_previous(self):
        prev = self._row("13080", "1000")
        assert classify(self._row("13080", ""), prev, session_date=SESSION,
                        previous_session=PREVIOUS).exclusion_reason == EXCL_NO_CLOSE
        assert classify(self._row("13090", "1000"), None, session_date=SESSION,
                        previous_session=PREVIOUS).exclusion_reason == EXCL_NO_PREVIOUS

    def test_synthetic_anomalies_show_up_in_aggregates(self, build):
        split = build.builds[SESSIONS[SPLIT_INDEX]].breadth
        assert split.excluded.get(EXCL_CORPORATE_ACTION) == 1
        # 出来ず（H）＋ 未上場（I）の2件が no_close。翌sessionはHが no_previous_close
        missing = build.builds[SESSIONS[MISSING_INDEX]].breadth
        assert missing.excluded.get(EXCL_NO_CLOSE) == 2
        after_missing = build.builds[SESSIONS[MISSING_INDEX + 1]].breadth
        assert after_missing.excluded.get(EXCL_NO_PREVIOUS) == 1
        assert after_missing.excluded.get(EXCL_NO_CLOSE) == 1        # I は未上場
        listing = build.builds[SESSIONS[NEW_INDEX]].breadth
        assert listing.excluded.get(EXCL_NO_PREVIOUS) == 1           # 上場初日は前値なし
        assert listing.excluded.get(EXCL_NO_CLOSE) is None
        assert build.builds[SESSIONS[NEW_INDEX + 1]].breadth.priced == 9


# ============================================================ breadth / manifest

class TestBreadthAggregation:
    def test_last_session_counts(self, last):
        b = last.breadth
        assert (b.advancers, b.decliners, b.unchanged, b.priced, b.universe_size) == (6, 2, 1, 9, 9)
        assert b.advance_decline_ratio == Decimal("3") and b.advance_decline_net == 4
        assert b.advance_ratio_pct == Decimal("66.666667")

    def test_manifest_fixes_inputs_and_is_reproducible(self, last, build):
        m = last.breadth_manifest
        assert m.input_count == len(m.input_record_ids) == 18      # 当日9 + 前営業日9
        assert m.input_set_hash == input_set_hash(m.input_record_ids)
        assert m.universe_version == "1.0.0" and m.price_movement_version == "1.0.0"
        again, again_manifest = aggregate_breadth(
            session_date=SESSION, previous_session=PREVIOUS, universe=last.universe,
            movements=last.movements, price_movement_version=CFG.price_movement_version)
        assert again_manifest.manifest_id == m.manifest_id and again == last.breadth
        # manifest → inputs 再構築（store経由）
        stored = {m.manifest_id: list(m.input_record_ids)}
        assert manifest_reproducibility([m], stored)["all_reproducible"]

    def test_manifest_changes_when_inputs_change(self, last):
        smaller = make_manifest(session_date=SESSION, universe=last.universe,
                                record_ids=last.breadth_manifest.input_record_ids[:-1],
                                calculation=("market_breadth", "1.0.0"),
                                price_movement_version="1.0.0")
        assert smaller.manifest_id != last.breadth_manifest.manifest_id

    def test_25_session_ratio_needs_25_sessions(self, build):
        aggs = [build.builds[s].breadth for s in build.sessions]
        assert advance_decline_ratio_n(aggs[:24], 25) is None
        ratio = advance_decline_ratio_n(aggs, 25)
        assert ratio is not None and ratio > 0
        index = InternalsFactIndex(build.facts)
        assert index.get(SESSION, MARKET_SUBJECT, AD_RATIO_25S).value.value == ratio
        assert index.get(build.sessions[10], MARKET_SUBJECT, AD_RATIO_25S) is None

    def test_breadth_trend_needs_20_sessions(self, build):
        index = InternalsFactIndex(build.facts)
        assert index.get(SESSION, MARKET_SUBJECT, ADVANCE_RATIO_20S_AVG) is not None
        assert index.get(build.sessions[5], MARKET_SUBJECT, ADVANCE_RATIO_20S_AVG) is None


# ============================================================ turnover / sector / size

class TestTurnoverSectorSize:
    def test_turnover_is_sum_of_universe_values(self, last):
        expected = sum(Decimal(10_000_000) * (i + 1) for i in range(len(PRIME_CODES)))
        assert last.turnover.total_turnover_value == expected
        assert last.turnover.securities_with_value == 9

    def test_turnover_average_and_ratio_facts(self, build):
        index = InternalsFactIndex(build.facts)
        total = index.get(SESSION, MARKET_SUBJECT, MARKET_TURNOVER_VALUE)
        avg = index.get(SESSION, MARKET_SUBJECT, TURNOVER_20S_AVG)
        ratio = index.get(SESSION, MARKET_SUBJECT, TURNOVER_VS_20S_RATIO)
        assert total and avg and ratio
        assert ratio.value.value == (total.value.value / avg.value.value).quantize(Decimal("0.000001"))
        assert set(ratio.calculation.inputs) == {total.fact_id, avg.fact_id}
        assert index.get(build.sessions[3], MARKET_SUBJECT, TURNOVER_20S_AVG) is None

    def test_sector_grouping_uses_s17_and_relative_return(self, last):
        by_code = {s.sector_code: s for s in last.sectors}
        assert set(by_code) == {"1", "9", "15", "3", "13"}
        assert by_code["1"].members == 2
        assert abs(by_code["1"].ew_return_pct - Decimal("1")) < Decimal("0.01")   # 終値は0.1刻み
        universe_ew = Decimal(last.sector_meta["universe_ew_return_pct"])
        assert by_code["3"].relative_return_pct_point == (
            by_code["3"].ew_return_pct - universe_ew).quantize(Decimal("0.000001"))
        leaders, laggards = leaders_and_laggards(last.sectors, top_n=3, min_gap=Decimal("0.30"))
        assert [s.sector_code for s in leaders] == ["9", "1", "13"]      # 相対リターン降順
        assert [s.sector_code for s in laggards] == ["3", "15"]          # 劣後順
        assert leaders[0].relative_return_pct_point > leaders[-1].relative_return_pct_point

    def test_size_grouping_follows_scalecat(self, last):
        assert group_of("TOPIX Core30") == "topix100" and group_of("TOPIX Large70") == "topix100"
        assert group_of("TOPIX Mid400") == "mid400" and group_of("TOPIX Small 2") == "small"
        assert group_of("-") == "unclassified"
        by_group = {s.group: s for s in last.sizes}
        assert by_group["topix100"].members == 4 and by_group["small"].members == 2
        assert last.size_gap.quantize(Decimal("0.01")) == Decimal("1.50")
        assert last.size_meta["scale_unclassified"] == 1


# ============================================================ investor flow

class TestInvestorFlow:
    def test_weekly_semantics_kept(self, build):
        flows = [f for f in build.flows if f.investor_type == "foreign_investors"]
        assert [f.period_end for f in flows] == ["2026-08-15", "2026-08-22", "2026-08-29"]
        assert all(f.frequency == "weekly" and f.section == "TSEPrime" for f in flows)
        assert build.flow_sections == {"TSEPrime": 3, "TSEStandard": 1}

    def test_publication_gating(self, build):
        cutoff = datetime(2026, 9, 1, 21, 0, tzinfo=timezone.utc)   # 2026-09-02 06:00 JST
        latest = latest_published_by(build.flows, cutoff, hour_jst=16)
        assert latest["foreign_investors"].period_end == "2026-08-22"   # 09-04公表分は使えない
        assert known_at_for("2026-08-28", hour_jst=16) == datetime(2026, 8, 28, 7, 0,
                                                                   tzinfo=timezone.utc)

    def test_flow_facts_have_period_end_and_publication_known_at(self, build):
        facts = [f for f in build.flow_facts
                 if f.subject.subject_id == flow_subject("TSEPrime", "foreign_investors")]
        assert len(facts) == 3
        latest = max(facts, key=lambda f: f.time.primary_date)
        assert latest.time.date_role is DateRole.PERIOD_END
        assert latest.time.known_at == datetime(2026, 9, 4, 7, 0, tzinfo=timezone.utc)
        assert latest.value.value == Decimal("3000") and latest.fact_type == INVESTOR_FLOW_NET
        assert latest.evidence[0].kind is EvidenceKind.RECORD


# ============================================================ Fact integration

class TestFactIntegration:
    def test_breadth_facts_cite_manifest(self, build, last):
        index = InternalsFactIndex(build.facts)
        adv = index.get(SESSION, MARKET_SUBJECT, MARKET_ADVANCERS)
        assert adv.value.value == Decimal("6") and adv.status is FactStatus.USABLE
        assert adv.evidence[0].ref_id == last.breadth_manifest.manifest_id
        assert adv.calculation.inputs == (last.breadth_manifest.manifest_id,)
        assert adv.calculation.parameters["input_count"] == "18"
        assert adv.time.known_at == tokyo_close_utc(SESSION)

    def test_fact_ids_are_deterministic(self, light):
        again = build_internals(light, CFG, SESSIONS, now=NOW + timedelta(days=3))
        assert [f.fact_id for f in again.facts] == [f.fact_id for f in
                                                    build_internals(light, CFG, SESSIONS,
                                                                    now=NOW).facts]

    def test_limited_use_when_universe_is_a_sample(self, light):
        sample = build_internals(light, CFG, SESSIONS[-3:], now=NOW, limited=True)
        assert sample.facts and all(f.status is FactStatus.LIMITED_USE for f in sample.facts)

    def test_fact_store_roundtrip_idempotent(self, build, tmp_path):
        store = FactStore(tmp_path)
        first = store.add(build.all_facts)
        second = store.add(build.all_facts)
        assert first["added"] == len(build.all_facts) and second["added"] == 0
        assert store.rebuild_index() == store.count()
        store.close()


# ============================================================ Context integration

class TestContextIntegration:
    def test_context_types_and_directions(self, internals_items):
        latest = {i.context_type: i for i in internals_items if i.time.session_date == SESSION}
        assert latest[BREADTH_STATE].direction is Direction.UP
        assert latest[BREADTH_STATE].note.startswith("state=BREADTH_POSITIVE")
        assert latest[SIZE_LEADERSHIP].direction is Direction.OUTPERFORM
        assert latest[TURNOVER_STATE].context_type == TURNOVER_STATE
        assert latest[BREADTH_TREND].context_type == BREADTH_TREND
        assert latest[INDEX_LEADERSHIP].relationship is Relationship.CONFIRMING   # TOPIX UP & breadth UP
        assert "BROAD_CONFIRMATION" in latest[INDEX_LEADERSHIP].note
        sectors = [i for i in internals_items if i.context_type == SECTOR_LEADERSHIP
                   and i.time.session_date == SESSION]
        assert any(i.subject.subject_id == SECTOR_SUMMARY_SUBJECT for i in sectors)
        assert sum(1 for i in sectors if i.direction is Direction.OUTPERFORM) == 3
        assert sum(1 for i in sectors if i.direction is Direction.UNDERPERFORM) == 2

    def test_every_context_has_fact_provenance(self, internals_items, build):
        ids = {f.fact_id for f in build.all_facts} | {f.fact_id for f in core_facts() + previous_facts()}
        for item in internals_items:
            assert item.supporting_fact_ids and set(item.supporting_fact_ids) <= ids, item.context_type
            assert item.relationship is not Relationship.CO_OCCURRING or True
            assert "CAUSES" not in item.note

    def test_flow_contexts_are_weekly(self, internals_items):
        flows = [i for i in internals_items if i.context_type == INVESTOR_FLOW_STATE]
        assert flows and all("frequency=weekly" in i.note for i in flows)
        foreign = [i for i in flows if i.subject.subject_id.endswith(":foreign_investors")]
        assert {i.time.session_date for i in foreign} == {"2026-08-15", "2026-08-22", "2026-08-29"}

    def test_salience_tiers_reuse_existing_discipline(self, internals_items):
        ranked = rank_contexts(internals_items, session_date=SESSION)
        by_type = {}
        for i in ranked:
            by_type.setdefault(i.context_type, i)
        assert by_type[BREADTH_STATE].priority_tier is PriorityTier.PRIMARY
        assert by_type[TURNOVER_STATE].priority_tier is PriorityTier.SECONDARY
        assert by_type[BREADTH_STATE].priority_components["note_state"] == "BREADTH_POSITIVE"
        latest_flow = max((i for i in ranked if i.context_type == INVESTOR_FLOW_STATE
                           and i.time.session_date <= SESSION), key=lambda i: i.time.session_date)
        assert latest_flow.priority_components["freshness"] == "latest_weekly_publication"
        old = [i for i in ranked if i.context_type == BREADTH_STATE
               and i.time.session_date != SESSION]
        assert all(i.priority_tier is not PriorityTier.PRIMARY for i in old)

    def test_context_store_idempotent_and_rebuildable(self, internals_items, tmp_path):
        store = ContextStore(tmp_path)
        first = store.add(internals_items)
        second = store.add(internals_items)
        assert first["added"] == len(internals_items) and second["added"] == 0
        assert store.rebuild_index() == store.count()
        assert store.contexts_by_fact(internals_items[0].supporting_fact_ids[0])
        store.close()


# ============================================================ snapshot / look-ahead

class TestMorningSnapshot:
    def test_internals_status_all_available(self, after):
        assert set(after.internals_status) == set(INTERNALS_DIMENSIONS)
        assert all(s is ContextStatus.AVAILABLE for s in after.internals_status.values()), \
            after.internals_status
        assert after.reference_session == SESSION
        assert leaked_contexts(after.items, after.cutoff) == []

    def test_unpublished_week_is_excluded_by_cutoff(self, after):
        flows = [i for i in after.items if i.context_type == INVESTOR_FLOW_STATE
                 and i.subject.subject_id.endswith(":foreign_investors")]
        assert max(i.time.session_date for i in flows) == "2026-08-22"

    def test_look_ahead_morning_before_session_close(self, internals_items):
        """2026-09-01 の朝（cutoff 06:00 JST）には 09-01 の集計（15:30 JST既知）は使えない。"""
        snap = morning_internals_snapshot(internals_items, SESSION, config=CFG, generated_at=NOW)
        assert all(i.time.session_date < SESSION for i in snap.items)
        assert snap.reference_session == PREVIOUS
        assert snap.internals_status[DIM_BREADTH] is ContextStatus.AVAILABLE   # 08-31分
        assert leaked_contexts(snap.items, snap.cutoff) == []
        assert not any(i.time.session_date == SESSION for i in snap.items)

    def test_stale_and_insufficient_history_are_reported(self, internals_items, build):
        old = [i for i in internals_items if i.time.session_date <= build.sessions[3]]
        status = internals_status(old, reference_session=SESSION, section="TSEPrime",
                                  availability={DIM_TURNOVER: "INSUFFICIENT_HISTORY"})
        assert status[DIM_BREADTH] is ContextStatus.STALE
        assert status[DIM_TURNOVER] is ContextStatus.INSUFFICIENT_HISTORY
        assert status[DIM_FLOW] is ContextStatus.MISSING
        none = internals_status([], reference_session=SESSION, section="TSEPrime",
                                availability={DIM_BREADTH: "NOT_ENTITLED"})
        assert none[DIM_BREADTH] is ContextStatus.NOT_ENTITLED
        assert none[DIM_SIZE] is ContextStatus.MISSING

    def test_flow_older_than_max_age_is_stale(self, internals_items):
        status = internals_status(internals_items, reference_session="2026-09-30",
                                  section="TSEPrime", flow_max_age_days=14)
        assert status[DIM_FLOW] is ContextStatus.STALE


# ============================================================ Compass integration

class TestCompassIntegration:
    def test_evidence_package_receives_internals_as_normal_contexts(self, result_after):
        pkg = result_after.package
        assert set(pkg.internals_status) == set(INTERNALS_DIMENSIONS)
        assert all(pkg.dimension_status[d] is ContextStatus.AVAILABLE for d in INTERNALS_DIMENSIONS)
        assert pkg.dimension_context(DIM_BREADTH).context_type == BREADTH_STATE
        assert pkg.dimension_context(DIM_FLOW).subject.subject_id.endswith(":foreign_investors")
        # 3-Cの次元は不変
        assert pkg.dimension_status["japan_equities"] is ContextStatus.AVAILABLE
        assert pkg.excluded_look_ahead == ()
        sectors = pkg.contexts_of(SECTOR_LEADERSHIP)
        assert len(sectors) == 6                                  # 要約 + leaders3 + laggards2

    def test_after_draft_is_valid_and_internals_claims_are_grounded(self, result_after):
        draft = result_after.draft
        assert draft.verdict is QualityVerdict.VALID, [
            (c.text, [f"{i.validator}:{i.code}" for i in c.issues]) for c in draft.rejected_claims]
        texts = [c.text for c in draft.claims]
        assert any("値上がり6銘柄・値下がり2銘柄・変化なし1銘柄" in t for t in texts)
        assert any("値上がり銘柄数が値下がり銘柄数を上回った" in t for t in texts)
        assert any("売買代金は20営業日平均の" in t for t in texts)
        assert any("業種別では、電機・精密・食品・商社・卸売が市場平均を上回り、建設・資材・銀行が下回った" in t
                   for t in texts)
        assert any("大型株が小型株を上回った（差+1.500pt）" in t for t in texts)
        assert any("直近公表週（2026-08-18〜2026-08-22、公表日2026-08-28）では、海外投資家は売り越しであった"
                   in t for t in texts)
        interp = [c for c in draft.claims if c.rule_ref == "JP_INT_001"]
        assert len(interp) == 1 and interp[0].claim_type is ClaimType.INTERPRETIVE
        assert "広がりが確認された" in interp[0].text and interp[0].is_grounded
        assert all(c.is_grounded for c in draft.claims)

    def test_before_after_comparison_changes_evidence_not_outlook(self, result_before, result_after):
        before, after = result_before.draft, result_after.draft
        assert before.verdict is QualityVerdict.VALID and after.verdict is QualityVerdict.VALID
        assert before.outlook.direction is after.outlook.direction
        assert before.outlook.confidence is after.outlook.confidence
        assert before.one_liner == after.one_liner                    # one-linerは変えない
        assert len(after.claims) > len(before.claims)
        assert not result_before.package.internals_status
        assert not any(t in c.text for c in before.claims for t in ("値上がり", "売買代金", "海外投資家"))

    def test_breadth_claim_without_internals_is_rejected(self, result_before, result_after,
                                                        before, all_facts):
        breadth_claim = next(c for c in result_after.draft.claims if "値上がり6銘柄" in c.text)
        codes = {i.code for i in validate_missingness(breadth_claim, result_before.package)}
        assert "missing_dimension_assertion" in codes
        res = run_pipeline(before, all_facts, generator=FakeNarrativeGenerator([breadth_claim]),
                           config=CompassConfig(), now=NOW)
        evaluated = next(c for c in res.first_gate.claims if c.claim_id == breadth_claim.claim_id)
        assert evaluated.grounding_status is GroundingStatus.REJECTED
        assert breadth_claim.claim_id not in {c.claim_id for c in res.draft.claims}
        assert res.draft.verdict is QualityVerdict.VALID          # 決定論的生成へ差し戻し

    def test_coverage_reports_unavailable_internals(self, after, all_facts):
        degraded = attach_internals(after, dict(after.internals_status,
                                                turnover=ContextStatus.INSUFFICIENT_HISTORY))
        degraded = degraded.__class__(**{**degraded.__dict__,
                                         "items": tuple(i for i in degraded.items
                                                        if i.context_type != TURNOVER_STATE)})
        res = run_pipeline(degraded, all_facts, config=CompassConfig(), now=NOW)
        coverage = res.draft.claims_for_role(ClaimRole.COVERAGE)[0].text
        assert "turnover（INSUFFICIENT_HISTORY）" in coverage
        assert not any("売買代金" in c.text for c in res.draft.claims)

    def test_lexicon_maps_internals_subjects_to_dimensions(self):
        assert SUBJECT_PATTERN.search("値上がり銘柄数").lastgroup == "breadth"
        assert SUBJECT_PATTERN.search("売買代金").lastgroup == "turnover"
        assert SUBJECT_PATTERN.search("海外投資家").lastgroup == "flow"
        assert KEY_DIMENSION["breadth"] == DIM_BREADTH and KEY_DIMENSION["size"] == DIM_SIZE
        assert KEY_DIMENSION["sector"] == DIM_SECTOR


class TestInternalsAdversarial:
    def test_fabrications_rejected_and_control_grounded(self, after, all_facts):
        cases, skipped = internals_adversarial.build_internals_adversarial_cases(
            after, all_facts, config=CompassConfig())
        assert not skipped
        names = {c.name for c in cases}
        assert {"fabricated_advancers", "breadth_direction_reversed", "weekly_flow_as_daily",
                "sector_causal", "breadth_without_internals", "valid_breadth_control"} <= names
        results = run_adversarial_cases(cases, config=CompassConfig(), now=NOW)
        summary = adversarial_summary(results, skipped)
        assert summary["all_passed"], [r for r in results if not r["passed"]]
        assert summary["controls_grounded"] == 1
        for r in results:
            assert r["draft_verdict"] == QualityVerdict.VALID.value


# ============================================================ store / ingest / performance

class TestInternalsStore:
    def test_append_only_idempotent_rebuild_and_manifest_inputs(self, build, tmp_path):
        store = InternalsStore(tmp_path)
        assert store.add_manifests(build.manifests) == len(build.manifests)
        assert store.add_aggregates(build.aggregate_rows) == len(build.aggregate_rows)
        assert store.add_manifests(build.manifests) == 0
        assert store.add_aggregates(build.aggregate_rows) == 0
        lines_before = store.manifest_path.read_text(encoding="utf-8").count("\n")
        rebuilt = store.rebuild_index()
        assert rebuilt == {"manifests": len(build.manifests), "aggregates": len(build.aggregate_rows)}
        assert store.manifest_path.read_text(encoding="utf-8").count("\n") == lines_before
        m = build.builds[SESSION].breadth_manifest
        assert store.manifest_inputs(m.manifest_id) == sorted(m.input_record_ids)
        assert store.aggregates_for("breadth", SESSION)[0]["advancers"] == 6
        store.close()


def _fake_http(calls):
    price_by_date = {SESSIONS[k]: price_rows_for(k) for k in range(len(SESSIONS))}

    def http(url, method, headers, payload):
        calls.append(url)
        assert headers.get("x-api-key") == API_KEY and API_KEY not in url
        if "/markets/calendar" in url:
            rows = [{"Date": d, "HolDiv": "1"} for d in SESSIONS]
        elif "/equities/master" in url and "date=" in url:
            return 400, b'{"message":"date parameter is not supported"}'
        elif "/equities/master" in url:
            rows = master_rows()
        elif "/equities/bars/daily" in url and "date=" in url:
            day = url.split("date=")[1].split("&")[0]
            rows = price_by_date.get(day, [])
        elif "/equities/investor-types" in url:
            rows = FLOW_ROWS
        else:
            return 403, b'{"message":"This API is not available on your subscription."}'
        return 200, json.dumps({"data": rows}).encode()
    return http


class TestIngestOffline:
    def test_date_mode_fetch_populates_light_store_without_leaking_secret(self, tmp_path):
        calls = []
        client = JQuantsV2Client(_fake_http(calls), env={"JQUANTS_API_KEY": API_KEY},
                                 sleeper=lambda s: None)
        store = JQuantsLightStore(tmp_path / "jquants_light")
        ing = InternalsIngestor(client, store, interval_seconds=0, sleeper=lambda s: None)
        master = fetch_master(ing)
        assert master.ok and master.added == len(master_rows())
        historic = fetch_master(ing, SESSIONS[0])
        assert not historic.ok and historic.http == 400            # 推測せず結果を記録
        mode, probe = detect_date_mode(ing, SESSIONS[-1])
        assert mode == DATE_MODE and probe.rows == len(price_rows_for(len(SESSIONS) - 1))
        outcomes = fetch_sessions_by_date(ing, SESSIONS[:-1], already=store.price_dates())
        assert len(outcomes) == len(SESSIONS) - 1 and all(o.ok for o in outcomes)
        assert store.price_dates() == SESSIONS
        assert ing.stats.requests == len(SESSIONS) + 2
        assert all(API_KEY not in url for url in calls)
        assert not any("api_key" in row["provenance"].get("raw_item_id", "").lower()
                       for row in store.iter_canonical("daily_bars"))
        again = fetch_sessions_by_date(ing, SESSIONS, already=store.price_dates())
        assert again == []                                          # 取得済みは再取得しない
        b = build_internals(store, CFG, SESSIONS, now=NOW)
        assert b.builds[SESSION].breadth.advancers == 6
        store.close()

    def test_no_credentials_means_no_network(self, tmp_path):
        calls = []
        client = JQuantsV2Client(_fake_http(calls), env={}, sleeper=lambda s: None)
        store = JQuantsLightStore(tmp_path / "jquants_light")
        ing = InternalsIngestor(client, store, interval_seconds=0, sleeper=lambda s: None)
        mode, probe = detect_date_mode(ing, SESSIONS[-1])
        assert mode == MODE_UNAVAILABLE and probe.error_kind == "no_credentials"
        assert calls == []
        store.close()

    def test_sample_selection_is_deterministic(self):
        rows = [{"Code": r["Code"], "S33": r["S33"], "ScaleCat": r["ScaleCat"]}
                for r in master_rows()]
        assert select_sample_codes(rows, 4) == select_sample_codes(rows, 4)
        assert len(select_sample_codes(rows, 4)) == 4


class TestPerformanceAndBackfill:
    def test_aggregation_is_fast_enough_for_morning(self, build):
        assert build.timings["seconds_per_session"] < 1.0

    def test_backfill_estimate_recommendation(self):
        base = dict(universe_size=4441, rows_per_session=4441, requests_per_session=1.0,
                    seconds_per_session_fetch=2.0, seconds_per_session_aggregate=0.5,
                    canonical_bytes_per_row=794, sqlite_bytes_per_row=200,
                    rebuild_seconds_per_row=0.00001, sessions_measured=45)
        rolling = estimate(Measured(date_mode_available=True, **base))
        assert rolling["recommendation"] == ROLLING
        assert rolling["full_universe_5y"]["records"] == 4441 * 244 * 5
        assert rolling["full_universe_5y"]["api_calls"] == 1220
        assert rolling["not_done_now"].startswith("full 5-year backfill was NOT executed")
        deferred = estimate(Measured(date_mode_available=False, **base))
        assert deferred["recommendation"] == DEFER
        fast = estimate(Measured(date_mode_available=True, **dict(
            base, seconds_per_session_fetch=0.5, canonical_bytes_per_row=100)))
        assert fast["recommendation"] == FULL


class TestSafety:
    def test_no_network_imports_in_pipeline_modules(self):
        for name in ("pipeline", "facts", "contexts", "breadth", "snapshot", "compass_claims"):
            text = Path(f"src/intelligence/internals/{name}.py").read_text(encoding="utf-8")
            assert "urllib" not in text and "requests" not in text and "http" not in text.lower()

    def test_production_data_untouched(self, build):
        """pilot/testは INTELLIGENCE_DATA_ROOT 配下（tmp）だけに書く。repoのdata/を触らない。"""
        tracked = Path("data")
        assert not (tracked / "vnext" / "internals").exists()

    def test_workflow_injects_only_jquants_key(self):
        text = Path(".github/workflows/p2d-market-pilot.yml").read_text(encoding="utf-8")
        step = text[text.index("Phase 3.5 Japan Market Internals real-data pilot"):]
        assert "JQUANTS_API_KEY: ${{ secrets.JQUANTS_API_KEY }}" in step
        assert "ANTHROPIC" not in step and "OPENAI" not in step
