"""Phase 4 P4-2 Market Signal のテスト。

検証済み `MorningBrief` → 5 段階の方向シグナルという**決定論的射影**であることを見る:

    承認済み写像（UPWARD_BIAS/DOWNWARD_BIAS × HIGH/MEDIUM/LOW, RANGE_BOUND × LOW）/
    MIXED・UNCERTAIN は段階にしない（確度に依存しない）/
    承認外の構造状態は fail closed / 内容アドレス ID の同一性 /
    助言語彙を持たない / P4-1 凍結物を一切変えない。

実パイプライン由来の `MorningBrief` は `test_compass_generator` の fixture から作り、
Compass の試験一式は複製しない。
"""
from __future__ import annotations

import ast
from dataclasses import replace
from pathlib import Path

import pytest

from src.intelligence.compass.config import CompassConfig
from src.intelligence.compass.model import Confidence, OutlookDirection, QualityVerdict
from src.intelligence.compass.pipeline import run_pipeline
from src.intelligence.reports.market_signal import (
    LEVEL_BY_STATE,
    MARKET_SIGNAL_SCHEMA_VERSION,
    R_DIRECTION_MIXED,
    R_DIRECTION_UNCERTAIN,
    R_DRAFT_ABSTAINED,
    R_DRAFT_NOT_USABLE,
    R_NO_OUTLOOK,
    R_TIER3_UNAVAILABLE,
    SIGNAL_LEVEL_JA,
    UNAVAILABLE_BY_DIRECTION,
    MarketSignal,
    SignalLevel,
    UnmappedSignalState,
    build_market_signal,
    canonical_signal,
    make_signal_id,
    signal_label,
    signal_payload,
)
from src.intelligence.reports.model import (
    MORNING_BRIEF_SCHEMA_VERSION,
    BriefOutlook,
    BriefTier1,
    BriefTier2,
    BriefTier3,
    MorningBrief,
)
from src.intelligence.reports.morning_brief import build_morning_brief
from src.intelligence.reports.render_markdown import render_morning_brief_markdown
from tests.intelligence.test_compass_generator import (
    NOW,
    base_facts,
    snapshot_for,
    stale_lead_facts,
)

SIGNAL_SRC = Path("src/intelligence/reports/market_signal.py")

#: 助言・推奨・スコア語（射影が足していないこと）
ADVICE_TOKENS = ("推奨", "買い", "売り", "目標株価", "ターゲット", "妙味", "押し目",
                 "すべきです", "おすすめ", "スタンス", "確率", "期待リターン")
#: 顧客向けラベルに出てはならない内部語彙
INTERNAL_TOKENS = ("UPWARD_BIAS", "DOWNWARD_BIAS", "RANGE_BOUND", "MIXED", "UNCERTAIN",
                   "HIGH", "MEDIUM", "LOW", "next_tokyo_session", "JP_", "Evidence Package",
                   "UPWARD_LEAN", "DOWNWARD_LEAN", "NEUTRAL_RANGE", "signal_", "brief_",
                   "+2", "+1", "-1", "-2")


# ---------------------------------------------------------------- helpers / fixtures

def _brief(*, direction: str = "UPWARD_BIAS", confidence: str = "HIGH",
           horizon: str = "next_tokyo_session",
           verdict: QualityVerdict = QualityVerdict.VALID,
           tier3_available: bool = True, outlook: object = ...,
           tier3_reason: str = "", abstain_reason: str = "",
           brief_id: str = "brief_fixture", session_date: str = "2026-09-15",
           reference_session: str = "2026-09-14") -> MorningBrief:
    """観測された実データ形をなぞった最小の MorningBrief。"""
    if outlook is ...:
        outlook = BriefOutlook(direction=direction, confidence=confidence, horizon=horizon)
    return MorningBrief(
        brief_id=brief_id, session_date=session_date, reference_session=reference_session,
        draft_id="compass_fixture", package_id="evpkg_fixture", verdict=verdict,
        generator="deterministic", abstain_reason=abstain_reason,
        tier1=BriefTier1(available=True, text="t", display_text="t"),
        tier2=BriefTier2(available=True),
        tier3=BriefTier3(available=tier3_available, outlook=outlook,
                         unavailable_reason=tier3_reason),
        schema_version=MORNING_BRIEF_SCHEMA_VERSION)


@pytest.fixture(scope="module")
def pipeline_normal():
    result = run_pipeline(snapshot_for(base_facts()), base_facts(), config=CompassConfig(),
                          now=NOW)
    return build_morning_brief(result.draft, result.package), result


@pytest.fixture(scope="module")
def pipeline_degraded():
    facts = stale_lead_facts(base_facts())
    result = run_pipeline(snapshot_for(facts), facts, config=CompassConfig(), now=NOW)
    return build_morning_brief(result.draft, result.package), result


# ---------------------------------------------------------------- approved mapping

class TestApprovedMapping:
    """承認済み写像（1–7）。"""

    @pytest.mark.parametrize("confidence", ["HIGH", "MEDIUM"])
    def test_upward_bias_strong_maps_to_upward_lean(self, confidence):
        signal = build_market_signal(_brief(direction="UPWARD_BIAS", confidence=confidence))
        assert signal.available is True
        assert signal.level is SignalLevel.UPWARD_LEAN
        assert signal.confidence == confidence          # 区別は構造として残る

    def test_upward_bias_low_maps_to_slight_upward_lean(self):
        signal = build_market_signal(_brief(direction="UPWARD_BIAS", confidence="LOW"))
        assert signal.level is SignalLevel.SLIGHT_UPWARD_LEAN

    @pytest.mark.parametrize("confidence", ["HIGH", "MEDIUM"])
    def test_downward_bias_strong_maps_to_downward_lean(self, confidence):
        signal = build_market_signal(_brief(direction="DOWNWARD_BIAS", confidence=confidence))
        assert signal.level is SignalLevel.DOWNWARD_LEAN
        assert signal.confidence == confidence

    def test_downward_bias_low_maps_to_slight_downward_lean(self):
        signal = build_market_signal(_brief(direction="DOWNWARD_BIAS", confidence="LOW"))
        assert signal.level is SignalLevel.SLIGHT_DOWNWARD_LEAN

    def test_range_bound_low_maps_to_neutral_range(self):
        signal = build_market_signal(_brief(direction="RANGE_BOUND", confidence="LOW"))
        assert signal.level is SignalLevel.NEUTRAL_RANGE
        assert signal.available is True

    def test_range_bound_is_the_only_direction_reaching_neutral(self):
        neutral = {d for (d, _c), lv in LEVEL_BY_STATE.items()
                   if lv is SignalLevel.NEUTRAL_RANGE}
        assert neutral == {OutlookDirection.RANGE_BOUND.value}

    def test_available_signal_carries_horizon(self):
        signal = build_market_signal(_brief(horizon="next_tokyo_session"))
        assert signal.horizon == "next_tokyo_session"


# ---------------------------------------------------------------- mixed / uncertain

class TestMixedAndUncertainAreNotNeutral:
    """D-3: 拮抗・不明は中立ではない（8–11）。確度に依存しない。"""

    @pytest.mark.parametrize("confidence", ["LOW", "MEDIUM", "HIGH"])
    def test_mixed_is_unavailable_for_every_confidence(self, confidence):
        signal = build_market_signal(_brief(direction="MIXED", confidence=confidence))
        assert signal.available is False
        assert signal.level is None
        assert signal.unavailable_reason == R_DIRECTION_MIXED

    @pytest.mark.parametrize("confidence", ["LOW", "MEDIUM", "HIGH"])
    def test_uncertain_is_unavailable_for_every_confidence(self, confidence):
        signal = build_market_signal(_brief(direction="UNCERTAIN", confidence=confidence))
        assert signal.available is False
        assert signal.level is None
        assert signal.unavailable_reason == R_DIRECTION_UNCERTAIN

    def test_mixed_and_uncertain_never_reach_neutral_range(self):
        for direction in ("MIXED", "UNCERTAIN"):
            for confidence in ("LOW", "MEDIUM", "HIGH"):
                signal = build_market_signal(_brief(direction=direction,
                                                    confidence=confidence))
                assert signal.level is not SignalLevel.NEUTRAL_RANGE

    def test_direction_decides_before_confidence_is_consulted(self):
        """確度が変わっただけで raise しない（将来の確度変更に対して安全）。"""
        assert set(UNAVAILABLE_BY_DIRECTION) == {OutlookDirection.MIXED.value,
                                                 OutlookDirection.UNCERTAIN.value}
        for direction in UNAVAILABLE_BY_DIRECTION:
            for confidence in (c.value for c in Confidence):
                build_market_signal(_brief(direction=direction, confidence=confidence))

    def test_unavailable_mixed_still_keeps_confidence_and_horizon(self):
        signal = build_market_signal(_brief(direction="MIXED", confidence="MEDIUM"))
        assert signal.confidence == "MEDIUM" and signal.horizon == "next_tokyo_session"


# ---------------------------------------------------------------- fail closed

class TestFailClosed:
    """承認外の構造状態は段階を作らず止まる（12, 17–19）。"""

    @pytest.mark.parametrize("confidence", ["HIGH", "MEDIUM"])
    def test_range_bound_with_strong_confidence_fails_closed(self, confidence):
        with pytest.raises(UnmappedSignalState):
            build_market_signal(_brief(direction="RANGE_BOUND", confidence=confidence))

    @pytest.mark.parametrize("direction", ["SIDEWAYS", "UPWARD", "upward_bias", ""])
    def test_unknown_direction_fails_closed(self, direction):
        with pytest.raises(UnmappedSignalState):
            build_market_signal(_brief(direction=direction, confidence="HIGH"))

    @pytest.mark.parametrize("confidence", ["VERY_HIGH", "high", "3", ""])
    def test_unknown_confidence_fails_closed(self, confidence):
        with pytest.raises(UnmappedSignalState):
            build_market_signal(_brief(direction="UPWARD_BIAS", confidence=confidence))

    def test_unknown_signal_level_label_fails_closed(self):
        with pytest.raises(UnmappedSignalState):
            signal_label("SIDEWAYS_LEAN")

    def test_available_signal_without_level_fails_closed(self):
        payload = signal_payload(schema_version=MARKET_SIGNAL_SCHEMA_VERSION,
                                 session_date="2026-09-15", reference_session="2026-09-14",
                                 available=True, level=None, confidence="HIGH",
                                 horizon="next_tokyo_session", brief_id="brief_x",
                                 unavailable_reason="")
        with pytest.raises(UnmappedSignalState):
            MarketSignal(signal_id=make_signal_id(payload), session_date="2026-09-15",
                         reference_session="2026-09-14", available=True, level=None,
                         confidence="HIGH", horizon="next_tokyo_session", brief_id="brief_x")

    @pytest.mark.parametrize("reason", ["", "Draft Not Usable", "理由あり", "a" * 65])
    def test_invalid_unavailable_reason_fails_closed(self, reason):
        with pytest.raises(UnmappedSignalState):
            MarketSignal(signal_id="signal_x", session_date="2026-09-15",
                         reference_session="2026-09-14", available=False, level=None,
                         brief_id="brief_x", unavailable_reason=reason)

    def test_unavailable_signal_with_level_fails_closed(self):
        with pytest.raises(UnmappedSignalState):
            MarketSignal(signal_id="signal_x", session_date="2026-09-15",
                         reference_session="2026-09-14", available=False,
                         level=SignalLevel.UPWARD_LEAN, brief_id="brief_x",
                         unavailable_reason=R_NO_OUTLOOK)

    def test_no_silent_fallback_level_in_source(self):
        src = SIGNAL_SRC.read_text(encoding="utf-8")
        body = src.split("LEVEL_BY_STATE")[-1]
        assert ".get((" not in body and "or SignalLevel" not in body


# ---------------------------------------------------------------- completeness

class TestVocabularyCompleteness:
    """列挙の網羅（13–16）。"""

    def test_every_outlook_direction_is_explicitly_handled(self):
        mapped = {d for (d, _c) in LEVEL_BY_STATE}
        handled = mapped | set(UNAVAILABLE_BY_DIRECTION)
        assert handled == {d.value for d in OutlookDirection}

    def test_every_confidence_value_is_explicitly_handled(self):
        used = {c for (_d, c) in LEVEL_BY_STATE}
        assert used == {c.value for c in Confidence}

    def test_all_five_levels_are_reachable(self):
        reached = {build_market_signal(_brief(direction=d, confidence=c)).level
                   for (d, c) in LEVEL_BY_STATE}
        assert reached == set(SignalLevel)
        assert len(SignalLevel) == 5

    def test_label_mapping_is_exact_and_complete(self):
        assert set(SIGNAL_LEVEL_JA) == {lv.value for lv in SignalLevel}
        assert SIGNAL_LEVEL_JA == {
            "UPWARD_LEAN": "上昇寄り",
            "SLIGHT_UPWARD_LEAN": "やや上昇寄り",
            "NEUTRAL_RANGE": "中立（レンジ）",
            "SLIGHT_DOWNWARD_LEAN": "やや下落寄り",
            "DOWNWARD_LEAN": "下落寄り",
        }

    def test_mapping_table_has_no_unapproved_entry(self):
        assert set(LEVEL_BY_STATE) == {
            ("UPWARD_BIAS", "HIGH"), ("UPWARD_BIAS", "MEDIUM"), ("UPWARD_BIAS", "LOW"),
            ("DOWNWARD_BIAS", "HIGH"), ("DOWNWARD_BIAS", "MEDIUM"), ("DOWNWARD_BIAS", "LOW"),
            ("RANGE_BOUND", "LOW"),
        }


# ---------------------------------------------------------------- verdict / degraded

class TestUnavailablePolicy:
    """verdict と劣化（20–27）。"""

    @pytest.mark.parametrize("verdict", [QualityVerdict.VALID,
                                         QualityVerdict.VALID_WITH_WARNINGS])
    def test_usable_verdicts_produce_a_level(self, verdict):
        assert build_market_signal(_brief(verdict=verdict)).available is True

    def test_abstained_is_unavailable(self):
        signal = build_market_signal(_brief(verdict=QualityVerdict.ABSTAINED))
        assert signal.available is False and signal.unavailable_reason == R_DRAFT_ABSTAINED

    def test_rejected_is_unavailable(self):
        signal = build_market_signal(_brief(verdict=QualityVerdict.REJECTED))
        assert signal.available is False and signal.unavailable_reason == R_DRAFT_NOT_USABLE

    def test_abstain_reason_is_inherited_when_machine_readable(self):
        signal = build_market_signal(_brief(verdict=QualityVerdict.ABSTAINED,
                                            abstain_reason="insufficient_context"))
        assert signal.unavailable_reason == "insufficient_context"

    def test_free_text_abstain_reason_is_not_carried(self):
        signal = build_market_signal(_brief(verdict=QualityVerdict.ABSTAINED,
                                            abstain_reason="根拠が足りません"))
        assert signal.unavailable_reason == R_DRAFT_ABSTAINED

    def test_tier3_unavailable_inherits_safe_reason(self):
        signal = build_market_signal(_brief(tier3_available=False, outlook=None,
                                            tier3_reason="no_grounded_counter_case"))
        assert signal.available is False
        assert signal.unavailable_reason == "no_grounded_counter_case"

    def test_tier3_unavailable_without_reason_uses_fallback(self):
        signal = build_market_signal(_brief(tier3_available=False, outlook=None))
        assert signal.unavailable_reason == R_TIER3_UNAVAILABLE

    def test_missing_outlook_is_unavailable(self):
        signal = build_market_signal(_brief(outlook=None))
        assert signal.available is False and signal.unavailable_reason == R_NO_OUTLOOK

    def test_degradation_is_not_double_counted(self, pipeline_normal, pipeline_degraded):
        """劣化次元は Compass 側で既に confidence / availability へ反映済み。"""
        for brief, _result in (pipeline_normal, pipeline_degraded):
            signal = build_market_signal(brief)
            if brief.tier3.available and brief.tier3.outlook is not None:
                state = (brief.tier3.outlook.direction, brief.tier3.outlook.confidence)
                if state in LEVEL_BY_STATE:
                    assert signal.level is LEVEL_BY_STATE[state]

    def test_dimension_fields_do_not_enter_the_signal(self):
        """missing / unreliable dimensions は signal の入力にならない。"""
        base = _brief()
        widened = replace(base, tier2=replace(
            base.tier2, missing_dimensions=("japan_rates",),
            unreliable_dimensions=("usd_jpy", "nt_ratio"),
            dimension_status={"japan_rates": "MISSING", "usd_jpy": "STALE",
                              "nt_ratio": "STALE"}))
        assert build_market_signal(base) == build_market_signal(widened)

    def test_unavailable_signal_has_no_customer_label(self):
        assert build_market_signal(_brief(direction="MIXED", confidence="LOW")).label == ""


# ---------------------------------------------------------------- identity

class TestDeterminismAndIdentity:
    """同一性（28–31, 48）。"""

    def test_same_input_same_object(self):
        assert build_market_signal(_brief()) == build_market_signal(_brief())

    def test_same_input_same_signal_id(self):
        assert build_market_signal(_brief()).signal_id == build_market_signal(_brief()).signal_id

    def test_signal_id_uses_the_shared_prefix(self):
        signal_id = build_market_signal(_brief()).signal_id
        assert signal_id.startswith("signal_") and len(signal_id) == len("signal_") + 24

    @pytest.mark.parametrize("field,value", [
        ("session_date", "2026-09-16"),
        ("reference_session", "2026-09-11"),
        ("brief_id", "brief_other"),
    ])
    def test_changed_identity_field_changes_signal_id(self, field, value):
        base = build_market_signal(_brief())
        other = build_market_signal(_brief(**{field: value}))
        assert other.signal_id != base.signal_id

    def test_changed_level_changes_signal_id(self):
        a = build_market_signal(_brief(direction="UPWARD_BIAS", confidence="HIGH"))
        b = build_market_signal(_brief(direction="UPWARD_BIAS", confidence="LOW"))
        assert a.signal_id != b.signal_id

    def test_confidence_is_part_of_identity(self):
        a = build_market_signal(_brief(direction="UPWARD_BIAS", confidence="HIGH"))
        b = build_market_signal(_brief(direction="UPWARD_BIAS", confidence="MEDIUM"))
        assert a.level is b.level and a.signal_id != b.signal_id

    def test_japanese_label_is_excluded_from_identity(self):
        signal = build_market_signal(_brief())
        payload = signal_payload(
            schema_version=signal.schema_version, session_date=signal.session_date,
            reference_session=signal.reference_session, available=signal.available,
            level=signal.level, confidence=signal.confidence, horizon=signal.horizon,
            brief_id=signal.brief_id, unavailable_reason=signal.unavailable_reason)
        canonical = canonical_signal(payload)
        for label in SIGNAL_LEVEL_JA.values():
            assert label not in canonical
        assert make_signal_id(payload) == signal.signal_id

    def test_canonical_form_is_key_ordered_and_compact(self):
        canonical = canonical_signal(signal_payload(
            schema_version="0.1.0", session_date="2026-09-15",
            reference_session="2026-09-14", available=True,
            level=SignalLevel.UPWARD_LEAN, confidence="HIGH",
            horizon="next_tokyo_session", brief_id="brief_x", unavailable_reason=""))
        assert canonical.startswith('{"available":true,')
        assert ", " not in canonical

    def test_identity_payload_has_exactly_the_approved_fields(self):
        payload = signal_payload(
            schema_version="0.1.0", session_date="s", reference_session="r",
            available=False, level=None, confidence="", horizon="",
            brief_id="brief_x", unavailable_reason=R_NO_OUTLOOK)
        assert set(payload) == {"schema_version", "session_date", "reference_session",
                                "available", "level", "confidence", "horizon",
                                "brief_id", "unavailable_reason"}
        assert "signal_id" not in payload

    def test_no_time_or_path_dependence_in_source(self):
        src = SIGNAL_SRC.read_text(encoding="utf-8")
        for forbidden in ("datetime", "time.", "random", "uuid", "os.", "getenv",
                          "environ", "socket", "gethostname", "getpid", "Path("):
            assert forbidden not in src, forbidden


# ---------------------------------------------------------------- provenance / binding

class TestProvenanceBinding:
    """provenance（32–34）。"""

    def test_brief_id_binding_is_preserved(self, pipeline_normal):
        brief = pipeline_normal[0]
        assert build_market_signal(brief).brief_id == brief.brief_id

    def test_sessions_are_preserved(self, pipeline_normal):
        brief = pipeline_normal[0]
        signal = build_market_signal(brief)
        assert signal.session_date == brief.session_date
        assert signal.reference_session == brief.reference_session

    def test_no_draft_or_package_id_on_the_model(self):
        signal = build_market_signal(_brief())
        assert not hasattr(signal, "draft_id") and not hasattr(signal, "package_id")
        assert "compass_fixture" not in canonical_signal(signal.as_dict())
        assert "evpkg_fixture" not in canonical_signal(signal.as_dict())

    def test_morning_brief_is_not_mutated(self, pipeline_normal):
        brief = pipeline_normal[0]
        before = brief.as_dict()
        build_market_signal(brief)
        assert brief.as_dict() == before

    def test_compass_draft_is_not_mutated(self, pipeline_normal):
        brief, result = pipeline_normal
        before = [c.as_dict() for c in result.draft.claims]
        build_market_signal(brief)
        assert [c.as_dict() for c in result.draft.claims] == before


# ---------------------------------------------------------------- P4-1 freeze

class TestP41FreezeIsPreserved:
    """P4-1 凍結（35–36）。"""

    def test_markdown_is_byte_identical_before_and_after_signal_build(self, pipeline_normal):
        brief = pipeline_normal[0]
        before = render_morning_brief_markdown(brief)
        build_market_signal(brief)
        assert render_morning_brief_markdown(brief) == before

    def test_brief_id_is_unchanged_by_signal_build(self, pipeline_normal):
        brief = pipeline_normal[0]
        before = brief.brief_id
        build_market_signal(brief)
        assert brief.brief_id == before

    def test_morning_brief_schema_stays_020(self):
        assert MORNING_BRIEF_SCHEMA_VERSION == "0.2.0"

    def test_market_signal_schema_is_010(self):
        assert MARKET_SIGNAL_SCHEMA_VERSION == "0.1.0"
        assert build_market_signal(_brief()).schema_version == "0.1.0"

    def test_p41_modules_do_not_reference_market_signal(self):
        for name in ("model.py", "morning_brief.py", "render_markdown.py", "pilot.py"):
            src = (Path("src/intelligence/reports") / name).read_text(encoding="utf-8")
            assert "market_signal" not in src, name
            assert "MarketSignal" not in src, name

    def test_dependency_is_one_way(self):
        """MarketSignal → MorningBrief のみ。逆向きは無い。"""
        src = SIGNAL_SRC.read_text(encoding="utf-8")
        assert "from .model import" in src
        for name in ("model.py", "morning_brief.py", "render_markdown.py"):
            other = (Path("src/intelligence/reports") / name).read_text(encoding="utf-8")
            assert "market_signal" not in other


# ---------------------------------------------------------------- language safety

class TestNoAdviceLanguage:
    """助言語彙を持たない（37–38）。"""

    def test_labels_contain_no_advice_language(self):
        blob = "".join(SIGNAL_LEVEL_JA.values())
        for advice in ADVICE_TOKENS:
            assert advice not in blob, advice

    def test_source_contains_no_recommendation_vocabulary(self):
        src = SIGNAL_SRC.read_text(encoding="utf-8")
        for advice in ("強気", "弱気", "bullish", "bearish", "buy", "sell",
                       "target_price", "expected_return", "probability"):
            assert advice not in src, advice

    def test_customer_labels_expose_no_internal_vocabulary(self):
        for label in SIGNAL_LEVEL_JA.values():
            for internal in INTERNAL_TOKENS:
                assert internal not in label, (label, internal)

    def test_customer_labels_expose_no_score(self):
        for label in SIGNAL_LEVEL_JA.values():
            assert not any(ch.isdigit() for ch in label), label
            assert "+" not in label and "%" not in label

    def test_level_enum_carries_no_ordinal_value(self):
        for level in SignalLevel:
            assert level.value == level.name
            assert not any(ch.isdigit() for ch in level.value)


# ---------------------------------------------------------------- isolation

class TestIsolation:
    """境界（39–47）。"""

    def _tops(self) -> set:
        tops = set()
        for node in ast.walk(ast.parse(SIGNAL_SRC.read_text(encoding="utf-8"))):
            if isinstance(node, ast.ImportFrom) and node.module:
                tops.add(node.module.lstrip(".").split(".")[0])
            elif isinstance(node, ast.Import):
                for alias in node.names:
                    tops.add(alias.name.split(".")[0])
        return tops

    def test_no_governance_imports(self):
        forbidden = {"decision", "formal_review", "review", "shadow_review",
                     "corpus", "corpus_research", "replay", "evaluation"}
        assert not self._tops() & forbidden

    def test_no_legacy_imports(self):
        forbidden = {"report", "analysis", "collectors"}
        src = SIGNAL_SRC.read_text(encoding="utf-8")
        for legacy in forbidden:
            assert f"src.{legacy}" not in src
        assert not self._tops() & forbidden

    def test_no_phase5_imports(self):
        forbidden = {"predictions", "themes", "thesis", "screening", "personalization"}
        assert not self._tops() & forbidden

    def test_no_article_tank_integration(self):
        src = SIGNAL_SRC.read_text(encoding="utf-8")
        for name in ("article-intelligence-data-tank", "external_intelligence", "tank"):
            assert name not in src, name

    def test_no_llm_imports(self):
        src = SIGNAL_SRC.read_text(encoding="utf-8")
        for name in ("llm", "anthropic", "openai"):
            assert name not in src, name

    def test_imports_stay_inside_the_allowed_layers(self):
        allowed = {"__future__", "json", "re", "dataclasses", "enum", "typing",
                   "compass", "core", "model"}
        assert self._tops() <= allowed, self._tops() - allowed

    def test_no_io_or_persistence_or_network(self):
        src = SIGNAL_SRC.read_text(encoding="utf-8")
        for name in ("open(", "Path(", "requests", "urllib", "socket", "http",
                     "sqlite3", "data_root", "store", "write_text", "json.dump("):
            assert name not in src, name

    def test_module_has_no_confidential_reference(self):
        src = SIGNAL_SRC.read_text(encoding="utf-8")
        for name in ("rashinban", "source_docs", ".pdf", "C:\\", "/Users/", "api_key"):
            assert name not in src, name

    def test_public_api_is_minimal(self):
        module = __import__("src.intelligence.reports.market_signal",
                            fromlist=["market_signal"])
        public = {n for n in dir(module) if not n.startswith("_")}
        expected = {
            "MARKET_SIGNAL_SCHEMA_VERSION", "SIGNAL_LEVEL_JA", "LEVEL_BY_STATE",
            "UNAVAILABLE_BY_DIRECTION", "SignalLevel", "MarketSignal",
            "UnmappedSignalState", "build_market_signal", "signal_label",
            "signal_payload", "canonical_signal", "make_signal_id",
            "R_DRAFT_NOT_USABLE", "R_DRAFT_ABSTAINED", "R_TIER3_UNAVAILABLE",
            "R_NO_OUTLOOK", "R_DIRECTION_MIXED", "R_DIRECTION_UNCERTAIN",
            # 再 export される型（import 由来）
            "Confidence", "OutlookDirection", "QualityVerdict", "MorningBrief",
            "USABLE_VERDICTS", "content_id", "annotations",
            "Dict", "Mapping", "Optional", "dataclass", "Enum", "json", "re",
        }
        assert public <= expected, public - expected


# ---------------------------------------------------------------- real pipeline

class TestAgainstRealPipelineOutput:
    def test_normal_brief_produces_a_consistent_signal(self, pipeline_normal):
        brief = pipeline_normal[0]
        signal = build_market_signal(brief)
        assert signal.brief_id == brief.brief_id
        if signal.available:
            assert signal.level in set(SignalLevel)
            assert signal.label in SIGNAL_LEVEL_JA.values()
        else:
            assert signal.level is None and signal.unavailable_reason

    def test_degraded_brief_produces_a_consistent_signal(self, pipeline_degraded):
        brief = pipeline_degraded[0]
        signal = build_market_signal(brief)
        assert (signal.available is True) == (signal.level is not None)

    def test_repeated_build_is_idempotent(self, pipeline_normal):
        brief = pipeline_normal[0]
        first = build_market_signal(brief)
        assert first == build_market_signal(brief) == build_market_signal(brief)
