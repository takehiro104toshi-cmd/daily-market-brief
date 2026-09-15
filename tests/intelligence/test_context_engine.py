"""Phase 3-B Compass Context Engine のオフラインテスト（ネットワーク不使用・LLM非依存）。

監督者指定の最低テスト項目を網羅する:
deterministic context ID / idempotency / revision / fact provenance /
multi-fact provenance / same-session comparison / known_at gating /
morning cutoff / look-ahead prevention / missing・stale・conflicted・limited-use /
Nikkei-TOPIX comparison / NT ratio / UST curve / USDJPY yen direction /
event proximity / salience determinism / ranking stability /
snapshot completeness status / canonical append-only / SQLite rebuild /
incremental generation / query。
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from pathlib import Path

from src.intelligence.context.compass_alignment import (
    align_snapshot,
    history_dir,
    parse_pre_market_numerics,
    summarize,
)
from src.intelligence.context.builders import (
    CROSS_ASSET_COOCCURRENCE,
    CURVE_SHAPE,
    EVENT_PROXIMITY,
    FX_DIRECTION,
    INDEX_DIRECTION,
    JGB10Y,
    NIKKEI,
    NT_RATIO_STATE,
    NT_SUBJECT,
    RATE_DIRECTION,
    RELATIVE_PERFORMANCE,
    TOPIX,
    TREND_VS_MA,
    USDJPY,
    UST2Y,
    UST10Y,
    CURVE_SUBJECT,
    build_session_contexts,
)
from src.intelligence.context.model import (
    CONTEXT_SCHEMA_VERSION,
    ContextItem,
    ContextStatus,
    ContextSubject,
    ContextTimeContext,
    Direction,
    MAGNITUDE_CATEGORIES_ENABLED,
    PriorityTier,
    Relationship,
    direction_of,
    flat_band_for,
    make_context_id,
)
from src.intelligence.context.salience import (
    SALIENCE_RULE_VERSION,
    high_priority,
    rank_contexts,
)
from src.intelligence.context.snapshot import (
    build_market_state,
    is_available_at,
    leaked_contexts,
    morning_context_snapshot,
)
from src.intelligence.context.store import ContextStore
from src.intelligence.facts.model import (
    ConflictState,
    DateRole,
    EvidenceKind,
    Fact,
    FactEvidenceRef,
    FactStatus,
    FactSubject,
    FactTimeContext,
    FactValue,
)

SESSION = "2026-09-01"
PREVIOUS = "2026-08-31"
NOW = datetime(2026, 9, 1, 12, tzinfo=timezone.utc)
#: 前営業日クローズ（JST 15:30 = UTC 06:30）→ 当日朝(JST 6:00)には既知
KNOWN_PREV = datetime(2026, 8, 31, 6, 30, tzinfo=timezone.utc)
KNOWN_SESSION = datetime(2026, 9, 1, 6, 30, tzinfo=timezone.utc)


def fact(fact_type, subject_id, value, *, session=SESSION, unit="pct",
         known_at=KNOWN_PREV, fid=None, status=FactStatus.USABLE,
         qa="accept", conflict=ConflictState.UNKNOWN):
    return Fact(
        fact_id=fid or f"fact_{fact_type}_{subject_id[:14]}_{session}_{value}",
        fact_type=fact_type,
        subject=FactSubject(subject_type="series", subject_id=subject_id),
        value=FactValue(value=Decimal(str(value)) if value is not None else None,
                        unit=unit),
        time=FactTimeContext(primary_date=session, date_role=DateRole.TRADING_DATE,
                             known_at=known_at),
        evidence=(FactEvidenceRef(kind=EvidenceKind.OBSERVATION,
                                  ref_id=f"obs_{subject_id[:10]}_{session}"),),
        status=status, qa_decision=qa, conflict_state=conflict)


def core_facts(session=SESSION, known_at=KNOWN_PREV):
    """Morning Compassの中核次元が揃った標準セット。"""
    return [
        fact("index_change_pct", TOPIX, "1.20", session=session, known_at=known_at),
        fact("index_change_pct", NIKKEI, "0.80", session=session, known_at=known_at),
        fact("distance_from_ma25_pct", TOPIX, "2.55", session=session, known_at=known_at),
        fact("return_5session_pct", TOPIX, "3.00", session=session, known_at=known_at),
        fact("return_5session_pct", NIKKEI, "1.50", session=session, known_at=known_at),
        fact("return_20session_pct", TOPIX, "5.00", session=session, known_at=known_at),
        fact("return_20session_pct", NIKKEI, "4.00", session=session, known_at=known_at),
        fact("nt_ratio", NT_SUBJECT, "15.95", session=session, unit="x",
             known_at=known_at),
        fact("yield_change", JGB10Y, "0.020", session=session, unit="pct_point",
             known_at=known_at),
        fact("yield_change", UST2Y, "-0.030", session=session, unit="pct_point",
             known_at=known_at),
        fact("yield_change", UST10Y, "0.040", session=session, unit="pct_point",
             known_at=known_at),
        fact("yield_spread", CURVE_SUBJECT, "0.41", session=session,
             unit="pct_point", known_at=known_at),
        fact("fx_change_pct", USDJPY, "0.35", session=session, known_at=known_at),
    ]


def previous_facts():
    return [
        fact("nt_ratio", NT_SUBJECT, "16.05", session=PREVIOUS, unit="x"),
        fact("yield_spread", CURVE_SUBJECT, "0.35", session=PREVIOUS,
             unit="pct_point"),
    ]


def build(session=SESSION, extra=(), previous=True, event_facts=()):
    facts = core_facts(session) + (list(previous_facts()) if previous else [])
    facts += list(extra)
    return build_session_contexts(facts, session, previous_session=PREVIOUS,
                                  event_facts=event_facts, now=NOW)


def by_type(items):
    out = {}
    for item in items:
        out.setdefault(item.context_type, []).append(item)
    return out


# ============================================================ id / determinism

class TestDeterministicContextId:
    def test_same_inputs_give_same_id(self):
        assert [i.context_id for i in build()] == [i.context_id for i in build()]

    def test_id_ignores_processing_time(self):
        a = build_session_contexts(core_facts(), SESSION, previous_session=PREVIOUS,
                                   now=NOW)
        b = build_session_contexts(core_facts(), SESSION, previous_session=PREVIOUS,
                                   now=NOW + timedelta(days=5))
        assert [i.context_id for i in a] == [i.context_id for i in b]

    def test_different_supporting_facts_give_different_id(self):
        def topix_direction(items):
            found = [i for i in by_type(items)[INDEX_DIRECTION]
                     if i.subject.subject_id == TOPIX]
            assert len(found) == 1
            return found[0]

        base = topix_direction(build())
        changed = build_session_contexts(
            [f for f in core_facts() if f.fact_type != "index_change_pct"]
            + [fact("index_change_pct", TOPIX, "9.99"),
               fact("index_change_pct", NIKKEI, "0.80")],
            SESSION, previous_session=PREVIOUS, now=NOW)
        # TOPIXのFactだけを差し替えたので、TOPIX側のcontext_idは変わり、
        # 変更していない日経平均側のcontext_idは変わらない。
        assert topix_direction(changed).context_id != base.context_id
        nikkei_ids = {i.context_id for i in by_type(build())[INDEX_DIRECTION]
                      if i.subject.subject_id == NIKKEI}
        assert nikkei_ids == {i.context_id
                              for i in by_type(changed)[INDEX_DIRECTION]
                              if i.subject.subject_id == NIKKEI}

    def test_ids_are_unique_within_a_session(self):
        items = build()
        assert len({i.context_id for i in items}) == len(items)

    def test_rule_version_is_recorded(self):
        for item in build():
            assert item.rule.endswith(":1.0.0")


# ============================================================ context types

class TestMarketTrendContext:
    def test_index_direction_uses_change_fact(self):
        item = by_type(build())[INDEX_DIRECTION][0]
        assert item.direction in (Direction.UP, Direction.DOWN, Direction.FLAT)
        assert item.magnitude_unit == "pct"
        assert item.supporting_fact_ids

    def test_above_ma_references_existing_derived_fact(self):
        """25DMA乖離は既存Factを参照し、Contextで再計算しない。"""
        item = by_type(build())[TREND_VS_MA][0]
        assert item.direction is Direction.ABOVE
        assert item.magnitude == Decimal("2.55")
        assert "参照" in item.note

    def test_below_ma_when_negative(self):
        facts = [f for f in core_facts() if f.fact_type != "distance_from_ma25_pct"]
        facts.append(fact("distance_from_ma25_pct", TOPIX, "-1.20"))
        items = build_session_contexts(facts, SESSION, now=NOW)
        assert by_type(items)[TREND_VS_MA][0].direction is Direction.BELOW


class TestNikkeiTopixAndNtContext:
    def test_relative_performance_topix_outperform(self):
        items = by_type(build())[RELATIVE_PERFORMANCE]
        assert len(items) == 2                     # 5セッション・20セッション
        for item in items:
            assert item.direction is Direction.OUTPERFORM
            assert len(item.supporting_fact_ids) == 2   # 両方のFactを保持
            assert item.subject.related_subject_ids == (NIKKEI, TOPIX)

    def test_relative_performance_underperform(self):
        facts = [f for f in core_facts()
                 if f.fact_type != "return_5session_pct"]
        facts += [fact("return_5session_pct", TOPIX, "1.00"),
                  fact("return_5session_pct", NIKKEI, "2.00")]
        items = [i for i in build_session_contexts(facts, SESSION, now=NOW)
                 if i.context_type == RELATIVE_PERFORMANCE
                 and i.time.session_count == 5]
        assert items[0].direction is Direction.UNDERPERFORM

    def test_missing_one_side_produces_no_comparison(self):
        facts = [f for f in core_facts()
                 if not (f.fact_type == "return_20session_pct"
                         and f.subject.subject_id == NIKKEI)]
        items = build_session_contexts(facts, SESSION, now=NOW)
        got = [i for i in items if i.context_type == RELATIVE_PERFORMANCE
               and i.time.session_count == 20]
        assert got == []                            # 片側欠落なら作らない

    def test_nt_ratio_direction_from_previous_session(self):
        item = by_type(build())[NT_RATIO_STATE][0]
        assert item.direction is Direction.DOWN     # 16.05 → 15.95
        assert item.magnitude == Decimal("-0.10")
        assert len(item.supporting_fact_ids) == 2

    def test_nt_ratio_without_previous_is_unknown_direction(self):
        items = build_session_contexts(core_facts(), SESSION, now=NOW)
        item = by_type(items)[NT_RATIO_STATE][0]
        assert item.direction is Direction.UNKNOWN
        assert item.magnitude is None


class TestRateAndCurveContext:
    def test_rate_directions(self):
        items = {i.subject.subject_id: i for i in by_type(build())[RATE_DIRECTION]}
        assert items[JGB10Y].direction is Direction.UP
        assert items[UST2Y].direction is Direction.DOWN
        assert items[UST10Y].direction is Direction.UP
        assert items[JGB10Y].magnitude_unit == "pct_point"

    def test_rate_flat_band_uses_reporting_precision(self):
        """公表精度（0.001 pct）未満はFLAT——恣意的な閾値は導入していない。"""
        assert flat_band_for("pct_point") == Decimal("0.001")
        assert flat_band_for("pct") == Decimal(0)      # 正当化できないので0
        assert direction_of(Decimal("0.0005"), unit="pct_point") is Direction.FLAT
        assert direction_of(Decimal("0.002"), unit="pct_point") is Direction.UP

    def test_curve_steepening(self):
        item = by_type(build())[CURVE_SHAPE][0]
        assert item.direction is Direction.STEEPENING     # 0.35 → 0.41
        assert item.magnitude == Decimal("0.06")

    def test_curve_flattening(self):
        facts = core_facts() + [
            fact("nt_ratio", NT_SUBJECT, "16.05", session=PREVIOUS, unit="x"),
            fact("yield_spread", CURVE_SUBJECT, "0.55", session=PREVIOUS,
                 unit="pct_point")]
        items = build_session_contexts(facts, SESSION, previous_session=PREVIOUS,
                                       now=NOW)
        assert by_type(items)[CURVE_SHAPE][0].direction is Direction.FLATTENING

    def test_curve_needs_previous_session(self):
        items = build_session_contexts(core_facts(), SESSION, now=NOW)
        assert CURVE_SHAPE not in by_type(items)


class TestFxContext:
    def test_usdjpy_up_means_yen_weaker(self):
        item = by_type(build())[FX_DIRECTION][0]
        assert item.direction is Direction.WEAKER
        assert "円安" in item.note

    def test_usdjpy_down_means_yen_stronger(self):
        facts = [f for f in core_facts() if f.fact_type != "fx_change_pct"]
        facts.append(fact("fx_change_pct", USDJPY, "-0.40"))
        items = build_session_contexts(facts, SESSION, now=NOW)
        assert by_type(items)[FX_DIRECTION][0].direction is Direction.STRONGER


class TestCrossAssetContext:
    def test_records_co_occurrence_not_causality(self):
        item = by_type(build())[CROSS_ASSET_COOCCURRENCE][0]
        assert item.relationship is Relationship.CO_OCCURRING
        assert "因果は主張しない" in item.note
        assert not hasattr(Relationship, "CAUSES")

    def test_needs_at_least_two_series(self):
        facts = [fact("index_change_pct", TOPIX, "1.20")]
        items = build_session_contexts(facts, SESSION, now=NOW)
        assert CROSS_ASSET_COOCCURRENCE not in by_type(items)


class TestEventContext:
    def _event(self, date_str, known_at=KNOWN_PREV):
        return Fact(
            fact_id=f"fact_ern_{date_str}", fact_type="earnings_schedule",
            subject=FactSubject(subject_type="security",
                                subject_id="jp:security:72030"),
            value=FactValue(text_value="2027Q2"),
            time=FactTimeContext(primary_date=date_str, date_role=DateRole.EVENT_DATE,
                                 known_at=known_at),
            evidence=(FactEvidenceRef(kind=EvidenceKind.RECORD, ref_id="ern_1"),))

    def test_days_until_event(self):
        items = build(event_facts=[self._event("2026-09-08")])
        event = by_type(items)[EVENT_PROXIMITY][0]
        assert event.magnitude == Decimal(7)
        assert event.magnitude_unit == "days"
        assert "event_date=2026-09-08" in event.note

    def test_past_events_are_skipped(self):
        items = build(event_facts=[self._event("2026-08-01")])
        assert EVENT_PROXIMITY not in by_type(items)

    def test_far_events_are_skipped(self):
        items = build(event_facts=[self._event("2027-06-01")])
        assert EVENT_PROXIMITY not in by_type(items)


# ============================================================ quality / status

class TestQualityPropagation:
    def test_limited_use_fact_marks_context(self):
        facts = [f for f in core_facts() if f.fact_type != "fx_change_pct"]
        facts.append(fact("fx_change_pct", USDJPY, "0.35",
                          status=FactStatus.LIMITED_USE, qa="limited_use"))
        items = build_session_contexts(facts, SESSION, now=NOW)
        item = by_type(items)[FX_DIRECTION][0]
        assert item.status is ContextStatus.LIMITED_USE
        assert item.quality == "limited_use"

    def test_conflicted_fact_marks_context(self):
        facts = [f for f in core_facts() if f.fact_type != "fx_change_pct"]
        facts.append(fact("fx_change_pct", USDJPY, "0.35",
                          conflict=ConflictState.CONFLICT))
        items = build_session_contexts(facts, SESSION, now=NOW)
        assert by_type(items)[FX_DIRECTION][0].status is ContextStatus.CONFLICTED

    def test_unusable_facts_are_ignored(self):
        unusable = Fact(
            fact_id="fact_unusable", fact_type="fx_change_pct",
            subject=FactSubject(subject_type="series", subject_id=USDJPY),
            value=FactValue(unit="pct"),
            time=FactTimeContext(primary_date=SESSION,
                                 date_role=DateRole.TRADING_DATE),
            status=FactStatus.UNUSABLE)
        facts = [f for f in core_facts() if f.fact_type != "fx_change_pct"]
        items = build_session_contexts(facts + [unusable], SESSION, now=NOW)
        assert FX_DIRECTION not in by_type(items)


# ============================================================ salience

class TestSalience:
    def test_core_dimensions_are_primary(self):
        ranked = rank_contexts(build(), session_date=SESSION)
        primary_types = {i.context_type for i in high_priority(ranked)}
        assert {INDEX_DIRECTION, RELATIVE_PERFORMANCE, NT_RATIO_STATE,
                RATE_DIRECTION, CURVE_SHAPE, FX_DIRECTION} <= primary_types

    def test_ranking_is_deterministic(self):
        first = [i.context_id for i in rank_contexts(build(), session_date=SESSION)]
        second = [i.context_id for i in rank_contexts(build(), session_date=SESSION)]
        assert first == second

    def test_components_are_explainable(self):
        item = rank_contexts(build(), session_date=SESSION)[0]
        assert item.priority_rule_version == SALIENCE_RULE_VERSION
        for key in ("base_tier", "final_tier", "freshness", "status",
                    "direction", "supporting_facts"):
            assert key in item.priority_components

    def test_stale_session_is_demoted(self):
        items = build_session_contexts(core_facts(session=PREVIOUS), PREVIOUS,
                                       now=NOW)
        ranked = rank_contexts(items, session_date=SESSION)   # 別sessionとして評価
        assert all(i.priority_tier is not PriorityTier.PRIMARY for i in ranked)
        assert all(i.priority_components["freshness"] == "older_session"
                   for i in ranked)

    def test_limited_use_is_demoted(self):
        facts = [f for f in core_facts() if f.fact_type != "fx_change_pct"]
        facts.append(fact("fx_change_pct", USDJPY, "0.35",
                          status=FactStatus.LIMITED_USE, qa="limited_use"))
        items = build_session_contexts(facts, SESSION, now=NOW)
        fx = [i for i in rank_contexts(items, session_date=SESSION)
              if i.context_type == FX_DIRECTION][0]
        assert fx.priority_tier is PriorityTier.SECONDARY

    def test_no_opaque_numeric_score(self):
        """0-100の疑似精度スコアを持たない（tierとcomponentsのみ）。"""
        item = rank_contexts(build(), session_date=SESSION)[0]
        assert not hasattr(item, "score")
        assert isinstance(item.priority_tier, PriorityTier)

    def test_magnitude_categories_are_deferred(self):
        assert MAGNITUDE_CATEGORIES_ENABLED is False


# ============================================================ snapshot / look-ahead

class TestMorningSnapshot:
    def test_snapshot_contains_only_known_contexts(self):
        items = build()
        snapshot = morning_context_snapshot(items, SESSION)
        assert snapshot.items
        assert leaked_contexts(snapshot.items, snapshot.cutoff) == []

    def test_context_from_same_day_close_is_excluded(self):
        """当日クローズのFactは当日朝には既知でない。"""
        items = build_session_contexts(core_facts(known_at=KNOWN_SESSION), SESSION,
                                       now=NOW)
        snapshot = morning_context_snapshot(items, SESSION)
        assert snapshot.items == ()

    def test_context_requires_all_supporting_facts_known(self):
        """支持Factが1つでも未知ならContextは利用不可。"""
        facts = [f for f in core_facts() if f.fact_type != "return_5session_pct"]
        facts += [fact("return_5session_pct", TOPIX, "3.00", known_at=KNOWN_PREV),
                  fact("return_5session_pct", NIKKEI, "1.50",
                       known_at=KNOWN_SESSION)]     # 片方だけ遅い
        items = build_session_contexts(facts, SESSION, now=NOW)
        rel = [i for i in items if i.context_type == RELATIVE_PERFORMANCE
               and i.time.session_count == 5][0]
        assert not is_available_at(rel, morning_context_snapshot(
            items, SESSION).cutoff)

    def test_context_without_known_at_is_unavailable(self):
        item = ContextItem(
            context_id="ctx_x", context_type=INDEX_DIRECTION,
            subject=ContextSubject(subject_type="series", subject_id=TOPIX),
            time=ContextTimeContext(session_date=SESSION),
            supporting_fact_ids=("fact_1",))
        snapshot = morning_context_snapshot([item], SESSION)
        assert snapshot.items == ()                # FAIL-CLOSED

    def test_market_state_vector(self):
        snapshot = morning_context_snapshot(build(), SESSION)
        state = snapshot.market_state.as_dict()
        assert state["japan_equities"] == "UP"
        assert state["nikkei_vs_topix"] == "OUTPERFORM"
        assert state["nt_ratio"] == "DOWN"
        assert state["japan_rates"] == "UP"
        assert state["us_rates_2y"] == "DOWN"
        assert state["us_rates_10y"] == "UP"
        assert state["us_curve"] == "STEEPENING"
        assert state["usd_jpy"] == "WEAKER"

    def test_missing_dimensions_are_reported_not_hidden(self):
        facts = [f for f in core_facts()
                 if f.subject.subject_id not in (USDJPY, CURVE_SUBJECT)]
        items = build_session_contexts(facts, SESSION, previous_session=PREVIOUS,
                                       now=NOW)
        snapshot = morning_context_snapshot(items, SESSION)
        assert "usd_jpy" in snapshot.missing_dimensions
        assert "us_curve" in snapshot.missing_dimensions
        assert snapshot.market_state.as_dict()["usd_jpy"] == "UNKNOWN"
        assert snapshot.dimension_status["usd_jpy"] is ContextStatus.MISSING

    def test_no_regime_classifier(self):
        """RISK_ON等の解釈分類を作らない。"""
        state = build_market_state(build()).as_dict()
        assert "RISK_ON" not in json.dumps(state)
        assert "RISK_OFF" not in json.dumps(state)

    def test_snapshot_has_no_narrative_text(self):
        data = morning_context_snapshot(build(), SESSION).as_dict()
        assert "narrative" not in data and "text" not in data
        for banned in ("bullish", "bearish", "buy", "sell", "推奨"):
            assert banned not in json.dumps(data, ensure_ascii=False).lower()

    # ---- 実運用の朝（当日クローズは未知、前営業日が最新）で成立するか
    def _two_session_items(self):
        """前々営業日と前営業日のContext（どちらも当日朝には既知）。"""
        older = build_session_contexts(
            core_facts(session="2026-08-28",
                       known_at=datetime(2026, 8, 28, 6, 30, tzinfo=timezone.utc)),
            "2026-08-28", previous_session="2026-08-27", now=NOW)
        newer = build_session_contexts(
            core_facts(session=PREVIOUS, known_at=KNOWN_PREV),
            PREVIOUS, previous_session="2026-08-28", now=NOW)
        return older + newer

    def test_reference_session_is_latest_available_not_snapshot_date(self):
        snapshot = morning_context_snapshot(self._two_session_items(), SESSION)
        assert snapshot.session_date == SESSION
        assert snapshot.reference_session == PREVIOUS   # 当日クローズは未知

    def test_latest_available_session_stays_primary(self):
        """前営業日クローズは朝時点の最新であり、暦日が違うだけで降格しない。"""
        snapshot = morning_context_snapshot(self._two_session_items(), SESSION)
        primary = [i for i in snapshot.items
                   if i.priority_tier is PriorityTier.PRIMARY]
        assert primary
        assert {i.time.session_date for i in primary} == {PREVIOUS}

    def test_market_state_uses_latest_session_per_dimension(self):
        """同じ次元に複数sessionがあるとき、並び順ではなく最新sessionを採る。"""
        items = self._two_session_items()
        state = build_market_state(list(reversed(items)), reference_session=PREVIOUS)
        assert state.status_dict()["japan_equities"] == "AVAILABLE"

    def test_dimension_only_available_from_older_session_is_stale(self):
        items = self._two_session_items()
        items = [i for i in items
                 if not (i.time.session_date == PREVIOUS
                         and i.context_type == FX_DIRECTION)]
        snapshot = morning_context_snapshot(items, SESSION)
        assert snapshot.dimension_status["usd_jpy"] is ContextStatus.STALE
        assert "usd_jpy" not in snapshot.missing_dimensions   # 欠落ではない


# ============================================================ store

@pytest.fixture()
def store(tmp_path):
    s = ContextStore(tmp_path)
    yield s
    s.close()


class TestContextStore:
    def test_add_is_idempotent(self, store):
        items = rank_contexts(build(), session_date=SESSION)
        first = store.add(items)
        second = store.add(items)
        assert first["added"] == len(items)
        assert second["added"] == 0 and second["skipped"] == len(items)

    def test_canonical_is_append_only(self, store):
        store.add(rank_contexts(build(), session_date=SESSION))
        rows = [json.loads(l) for l in
                store.canonical_path.read_text(encoding="utf-8").splitlines() if l]
        assert rows and all(r["schema_version"] == CONTEXT_SCHEMA_VERSION
                            for r in rows)

    def test_revision_supersedes_but_keeps_history(self, store):
        store.add(rank_contexts(build(), session_date=SESSION))
        facts = [f for f in core_facts() if f.fact_type != "index_change_pct"]
        facts += [fact("index_change_pct", TOPIX, "-1.00"),
                  fact("index_change_pct", NIKKEI, "0.80")]
        revised = rank_contexts(
            build_session_contexts(facts + previous_facts(), SESSION,
                                   previous_session=PREVIOUS, now=NOW),
            session_date=SESSION)
        result = store.add(revised)
        assert result["superseded"] >= 1
        alive = {(r["context_type"], r["subject_id"]): r
                 for r in store.contexts_for_session(SESSION)}
        assert alive[(INDEX_DIRECTION, TOPIX)]["direction"] == "DOWN"
        directions = {r["direction"] for r in store.iter_canonical()
                      if r["context_type"] == INDEX_DIRECTION
                      and r["subject_id"] == TOPIX}
        assert {"UP", "DOWN"} <= directions      # 旧Contextはcanonicalに残る

    def test_sqlite_rebuilds_from_canonical(self, store):
        store.add(rank_contexts(build(), session_date=SESSION))
        before = store.count()
        assert store.rebuild_index() == before
        assert store.count() == before

    def test_rebuild_restores_supersession(self, store):
        store.add(rank_contexts(build(), session_date=SESSION))
        facts = [f for f in core_facts() if f.fact_type != "index_change_pct"]
        facts += [fact("index_change_pct", TOPIX, "-1.00"),
                  fact("index_change_pct", NIKKEI, "0.80")]
        store.add(rank_contexts(
            build_session_contexts(facts + previous_facts(), SESSION,
                                   previous_session=PREVIOUS, now=NOW),
            session_date=SESSION))
        store.rebuild_index()
        alive = {(r["context_type"], r["subject_id"]): r
                 for r in store.contexts_for_session(SESSION)}
        assert alive[(INDEX_DIRECTION, TOPIX)]["direction"] == "DOWN"

    def test_queries(self, store):
        items = rank_contexts(build(event_facts=[]), session_date=SESSION)
        store.add(items)
        assert store.contexts_for_session(SESSION)
        assert store.latest_context_by_type(INDEX_DIRECTION, TOPIX)
        assert store.contexts_by_subject(TOPIX)
        assert store.high_priority_contexts(SESSION)
        sample = items[0]
        assert store.contexts_by_fact(sample.supporting_fact_ids[0])
        assert store.supporting_facts(sample.context_id) == list(
            sample.supporting_fact_ids)

    def test_divergence_query(self, store):
        store.add(rank_contexts(build(), session_date=SESSION))
        assert store.divergences(SESSION)          # TOPIX outperform = DIVERGING

    def test_does_not_duplicate_fact_store(self, store):
        """Fact本体を複製せず、fact_id参照だけを持つ。"""
        store.add(rank_contexts(build(), session_date=SESSION))
        row = store.contexts_for_session(SESSION)[0]
        assert "value" not in row.keys()
        assert "evidence_json" not in row.keys()

    def test_incremental_across_sessions(self, store):
        store.add(rank_contexts(build(), session_date=SESSION))
        before = store.count()
        other = rank_contexts(
            build_session_contexts(core_facts(session=PREVIOUS), PREVIOUS, now=NOW),
            session_date=PREVIOUS)
        result = store.add(other)
        assert result["added"] > 0 and store.count() > before


# ============================================================ 過去Compass整合（STEP 30）

class TestCompassAlignment:
    def _report(self, tmp_path, session_date, body):
        directory = tmp_path / session_date
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / "pre_market.html"
        path.write_text(f"<html><body><p>{body}</p></body></html>",
                        encoding="utf-8")
        return path

    def _snapshot(self, **kwargs):
        items = build_session_contexts(core_facts(session=PREVIOUS,
                                                  known_at=KNOWN_PREV),
                                       PREVIOUS, previous_session="2026-08-28",
                                       now=NOW)
        return morning_context_snapshot(items, SESSION)

    def test_parses_only_the_summary_line_values(self, tmp_path):
        path = self._report(
            tmp_path, SESSION,
            "日経平均を押し下げ（-9.99%）&#12288;"
            "日経平均: +0.25% ／ ドル円: +0.17% ／ 米10年金利: -0.30%")
        values = parse_pre_market_numerics(path)
        assert values["日経平均"] == Decimal("0.25")     # 本文中の言及を拾わない
        assert values["ドル円"] == Decimal("0.17")
        assert values["米10年金利"] == Decimal("-0.30")

    def test_missing_report_is_not_available_not_a_failure(self, tmp_path):
        result = align_snapshot(self._snapshot(), base_dir=tmp_path)
        assert {r["verdict"] for r in result.dimensions.values()} == {"NOT_AVAILABLE"}
        assert result.counts()["NOT_AVAILABLE"] == 3

    def test_matching_directions(self, tmp_path):
        # core_facts: 日経+0.80 / ドル円+0.35(円安) / UST10Y +0.040
        self._report(tmp_path, SESSION,
                     "日経平均: +0.25% ／ ドル円: +0.17% ／ 米10年金利: +0.17%")
        result = align_snapshot(self._snapshot(), base_dir=tmp_path)
        assert result.counts()["MATCH"] == 3
        assert result.dimensions["usd_jpy"]["reported_direction"] == "WEAKER"

    def test_opposite_direction_is_conflict_not_silently_dropped(self, tmp_path):
        self._report(tmp_path, SESSION,
                     "日経平均: -0.25% ／ ドル円: -0.17% ／ 米10年金利: -0.17%")
        result = align_snapshot(self._snapshot(), base_dir=tmp_path)
        assert result.counts()["CONFLICT"] == 3
        assert result.dimensions["nikkei_direction"]["context_direction"] == "UP"

    def test_flat_on_one_side_is_partial(self, tmp_path):
        self._report(tmp_path, SESSION,
                     "日経平均: 0.00% ／ ドル円: +0.17% ／ 米10年金利: +0.17%")
        result = align_snapshot(self._snapshot(), base_dir=tmp_path)
        assert result.dimensions["nikkei_direction"]["verdict"] == "PARTIAL"

    def test_summary_counts_only_comparable_dimensions(self, tmp_path):
        self._report(tmp_path, SESSION, "日経平均: +0.25%")
        result = align_snapshot(self._snapshot(), base_dir=tmp_path)
        summary = summarize([result])
        assert summary["comparable_dimensions"] == 1     # 分母に不明分を入れない
        assert summary["match_rate"] == "1/1"

    def test_alignment_reports_only_direction_never_tunes_magnitude(self, tmp_path):
        """大きさの一致は要求しない（数値は記録するが判定に使わない）。"""
        self._report(tmp_path, SESSION, "日経平均: +9.99%")
        result = align_snapshot(self._snapshot(), base_dir=tmp_path)
        row = result.dimensions["nikkei_direction"]
        assert row["verdict"] == "MATCH"
        assert row["reported_pct"] == "9.99" and row["context_magnitude"] == "0.80"

    def test_history_dir_comes_from_config(self, tmp_path):
        config = tmp_path / "config.yaml"
        config.write_text("report_schedule:\n  history_dir: \"output/history\"\n",
                          encoding="utf-8")
        assert history_dir(config) == Path("output") / "history"


# ============================================================ pilot end-to-end (offline)

class TestContextPilotEndToEndOffline:
    """pilot本体を合成Data Bankで通す（live runを使わず実行時エラーを検知する）。"""

    def _seed_market_bank(self, tmp_path):
        from datetime import date as _date
        from src.intelligence.core.paths import market_bank_root
        from src.intelligence.market.ingest import as_of_for
        from src.intelligence.market.model import Observation, ObservationKind
        from src.intelligence.market.series_catalog import load_catalog
        from src.intelligence.market.store import MarketBankStore

        days, cursor = [], _date(2026, 9, 1)
        while len(days) < 30:
            if cursor.weekday() < 5:
                days.append(cursor.isoformat())
            cursor -= timedelta(days=1)
        days.sort()

        catalog = load_catalog(Path("knowledge/market_series/core_series.yaml"))
        store = MarketBankStore(market_bank_root(tmp_path))
        observations = []
        for tag, series_id, base in (("topix", TOPIX, 2700), ("nikkei", NIKKEI, 39000),
                                     ("jgb10y", JGB10Y, 2), ("usdjpy", USDJPY, 150),
                                     ("ust2y", UST2Y, 4), ("ust10y", UST10Y, 5)):
            spec = catalog.get(series_id)
            if spec is None:
                continue
            for i, day in enumerate(days):
                observations.append(Observation(
                    observation_id=f"obs_{tag}_{day}",
                    entity_id=spec.series.instrument_id, metric=spec.series.metric,
                    value=Decimal(base + i), unit=spec.unit,
                    as_of=as_of_for(spec, day), kind=ObservationKind.RAW,
                    series_id=series_id, trading_date=day, source_id="test"))
        store.add_observations(observations)
        store.close()
        return days

    def test_pilot_runs_and_emits_markers(self, tmp_path, monkeypatch, capsys):
        from src.intelligence.context import pilot

        monkeypatch.setenv("INTELLIGENCE_DATA_ROOT", str(tmp_path))
        self._seed_market_bank(tmp_path)
        assert pilot.main(["--sessions", "3"]) == 0
        out = capsys.readouterr().out
        for marker in ("::P3B_INPUT::", "::P3B_CONTEXTS::", "::P3B_SNAPSHOT::",
                       "::P3B_TOP::", "::P3B_ALIGNMENT::", "::P3B_QUERY::"):
            assert marker in out, marker

        contexts = json.loads(out.split("::P3B_CONTEXTS::")[1].splitlines()[0])
        assert contexts["contexts_total"] > 0
        assert contexts["duplicate_context_ids"] == 0
        assert contexts["missing_provenance"] == 0
        assert contexts["rebuild_match"] is True
        assert len(contexts["per_session"]) >= 2      # 複数session

        snapshot = json.loads(out.split("::P3B_SNAPSHOT::")[1].splitlines()[0])
        assert snapshot["look_ahead_total_leaks"] == 0
        assert snapshot["same_or_future_session_total"] == 0
        assert any(s["contexts_available"] > 0 for s in snapshot["sessions"])

        top = json.loads(out.split("::P3B_TOP::")[1].splitlines()[0])
        assert top["top_contexts"] and top["priority_components_sample"]

    def test_pilot_skips_cleanly_without_market_bank(self, tmp_path, monkeypatch,
                                                    capsys):
        from src.intelligence.context import pilot

        monkeypatch.setenv("INTELLIGENCE_DATA_ROOT", str(tmp_path))
        assert pilot.main([]) == 0
        assert "::P3B_PILOT_SKIP::" in capsys.readouterr().out

    def test_pilot_is_idempotent_across_runs(self, tmp_path, monkeypatch, capsys):
        from src.intelligence.context import pilot

        monkeypatch.setenv("INTELLIGENCE_DATA_ROOT", str(tmp_path))
        self._seed_market_bank(tmp_path)
        pilot.main(["--sessions", "2"])
        first = json.loads(
            capsys.readouterr().out.split("::P3B_CONTEXTS::")[1].splitlines()[0])
        pilot.main(["--sessions", "2"])
        second = json.loads(
            capsys.readouterr().out.split("::P3B_CONTEXTS::")[1].splitlines()[0])
        assert second["store_added_first"] == 0
        assert second["canonical_rows"] == first["canonical_rows"]

    def test_pilot_output_has_no_narrative_or_recommendation(self, tmp_path,
                                                             monkeypatch, capsys):
        from src.intelligence.context import pilot

        monkeypatch.setenv("INTELLIGENCE_DATA_ROOT", str(tmp_path))
        self._seed_market_bank(tmp_path)
        pilot.main(["--sessions", "2"])
        out = capsys.readouterr().out.lower()
        for banned in ("bullish", "bearish", "risk_on", "risk_off", "推奨", "買い推奨"):
            assert banned not in out
