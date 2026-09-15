"""Phase 3.5 pre-flight: Phase 3-C 言語安全性の targeted regression。

A. Investment Interpretation（追い風／逆風）は **Fact ではなく経験則（Compass DNA）**
   に基づく: claim が rule_ref / interpretation_type / market_principle_version を持ち、
   principle validator が「一般論のFact化」「未登録の経験則」「根拠外Contextへの流用」を
   拒否する。
B. confidence → 言語強度 が機械的に整合する: OUTLOOK 文は HIGH=見込まれる /
   MEDIUM=可能性がある / LOW=余地がある で結ばれ、食い違えば REJECTED。
"""
from __future__ import annotations

from datetime import datetime, timezone

import pytest

from src.intelligence.compass.config import CompassConfig
from src.intelligence.compass.confidence_validation import validate_confidence
from src.intelligence.compass.generator import DeterministicNarrativeGenerator, new_claim
from src.intelligence.compass.language_rules import OUTLOOK_FORMS, validate_language
from src.intelligence.compass.lexicon import (
    OUTLOOK_PHRASES,
    STRENGTH_LEXICON,
    asserted_strength,
    outlook_phrase,
)
from src.intelligence.compass.market_principles import (
    MARKET_PRINCIPLE,
    MARKET_PRINCIPLE_VERSION,
    PRINCIPLES,
    catalog_rule_ids,
    is_registered,
)
from src.intelligence.compass.model import (
    ClaimRole,
    ClaimType,
    Confidence,
    GroundingStatus,
    OutlookDirection,
    QualityVerdict,
)
from src.intelligence.compass.one_liner import validate_one_liner
from src.intelligence.compass.outlook import asserted_bias
from src.intelligence.compass.pipeline import run_pipeline
from src.intelligence.compass.principle_validation import validate_principles
from src.intelligence.compass.quality_gate import evaluate_claim
from src.intelligence.context.builders import INDEX_DIRECTION, RATE_DIRECTION, TOPIX, UST10Y
from tests.intelligence.test_compass_generator import (
    MORNING,
    base_facts,
    claim,
    level_facts,
    snapshot_for,
)
from tests.intelligence.test_context_engine import NOW, fact

pytestmark = pytest.mark.filterwarnings("ignore")


@pytest.fixture(scope="module")
def facts():
    return base_facts()


@pytest.fixture(scope="module")
def result(facts):
    return run_pipeline(snapshot_for(facts), facts, config=CompassConfig(), now=NOW)


# ============================================================ A. principle registry

class TestMarketPrincipleRegistry:
    def test_every_registered_principle_exists_in_compass_dna_catalog(self):
        catalog = set(catalog_rule_ids())
        assert catalog, "knowledge/compass_dna/market_rules.yaml が読めること"
        missing = [pid for pid in PRINCIPLES if pid not in catalog]
        assert not missing, missing

    def test_version_matches_catalog(self):
        import yaml
        data = yaml.safe_load(open("knowledge/compass_dna/market_rules.yaml", encoding="utf-8"))
        assert MARKET_PRINCIPLE_VERSION.endswith(str(data["version"]))

    def test_outlook_rule_refs_are_registered(self, result):
        refs = {imp.rule_ref for imp in result.implications.values() if imp.rule_ref}
        assert refs and all(is_registered(r) for r in refs), refs

    def test_generated_interpretations_carry_principle_fields(self, result):
        for c in result.draft.claims:
            if c.claim_type in (ClaimType.INTERPRETIVE, ClaimType.RISK) and "経験則" in c.text:
                assert is_registered(c.rule_ref), c.text
                assert c.interpretation_type == MARKET_PRINCIPLE
                assert c.market_principle_version == MARKET_PRINCIPLE_VERSION
            if c.claim_type is ClaimType.FACTUAL:
                assert c.rule_ref == "" and c.interpretation_type == ""

    def test_risk_claim_headwind_is_interpretation_not_fact(self, result):
        """live one-liner例「米10年利回りの上昇は株式にとって逆風とみられる」の由来を固定する。"""
        risks = [c for c in result.draft.claims_for_role(ClaimRole.RISK) if "逆風" in c.text]
        assert risks
        risk = risks[0]
        assert risk.claim_type is ClaimType.RISK and risk.rule_ref == "JP_US_001"
        ctx = result.package.context(risk.supporting_context_ids[0])
        assert ctx.context_type == RATE_DIRECTION and ctx.subject.subject_id == UST10Y
        # 一般論を暗黙Factにしていない: 引用Factは金利変化の観測Factだけ
        assert all(result.package.fact(f).fact_type == "yield_change"
                   for f in risk.supporting_fact_ids)
        assert "とみられる" in risk.text and not [
            i for i in validate_language(risk) if i.code == "unsupported_causal_claim"]


class TestPrincipleValidator:
    def test_interpretation_without_principle_is_warned(self, result):
        topix = result.package.context_for(INDEX_DIRECTION, TOPIX)
        c = claim(ClaimRole.WHY, ClaimType.INTERPRETIVE,
                  "TOPIXは上昇したことが観測され、株式にとって追い風とみられる。",
                  topix.supporting_fact_ids, [topix.context_id])
        issues = validate_principles(c, result.package)
        assert [i.code for i in issues] == ["interpretation_without_principle"]
        evaluated = evaluate_claim(c, result.package, result.outlook, CompassConfig())
        assert evaluated.grounding_status is GroundingStatus.GROUNDED_WITH_WARNINGS

    def test_unknown_principle_is_rejected(self, result):
        topix = result.package.context_for(INDEX_DIRECTION, TOPIX)
        c = new_claim(session_date=MORNING, role=ClaimRole.WHY, claim_type=ClaimType.INTERPRETIVE,
                      text="根拠（経験則 JP_ZZZ_999）: 上昇は追い風とみられる。",
                      fact_ids=topix.supporting_fact_ids, context_ids=[topix.context_id],
                      generator="fake", order=1, rule_ref="JP_ZZZ_999")
        codes = {i.code for i in validate_principles(c, result.package)}
        assert "unknown_market_principle" in codes
        assert evaluate_claim(c, result.package, result.outlook, CompassConfig()
                              ).grounding_status is GroundingStatus.REJECTED

    def test_principle_applied_to_wrong_context_is_rejected(self, result):
        topix = result.package.context_for(INDEX_DIRECTION, TOPIX)
        c = new_claim(session_date=MORNING, role=ClaimRole.WHY, claim_type=ClaimType.INTERPRETIVE,
                      text="根拠（経験則 JP_US_001）: TOPIXの上昇は逆風とみられる。",
                      fact_ids=topix.supporting_fact_ids, context_ids=[topix.context_id],
                      generator="fake", order=1, rule_ref="JP_US_001")
        assert "principle_context_mismatch" in {
            i.code for i in validate_principles(c, result.package)}

    def test_factual_claim_may_not_carry_a_principle(self, result):
        topix = result.package.context_for(INDEX_DIRECTION, TOPIX)
        c = new_claim(session_date=MORNING, role=ClaimRole.HEADLINE, claim_type=ClaimType.FACTUAL,
                      text="TOPIXは前日比+1.20%の上昇となった。",
                      fact_ids=topix.supporting_fact_ids, context_ids=[topix.context_id],
                      generator="fake", order=1, rule_ref="JP_DIR_001")
        assert [i.code for i in validate_principles(c, result.package)] == ["factual_with_principle"]

    def test_text_tag_is_read_when_structured_field_is_absent(self, result):
        """LLM出力が構造化 rule_ref を落としても（経験則 XX）タグで検証できる。"""
        ust = result.package.context_for(RATE_DIRECTION, UST10Y)
        c = claim(ClaimRole.RISK, ClaimType.RISK,
                  "反対材料（経験則 JP_US_001）: 米10年国債利回りの上昇は逆風とみられる。",
                  ust.supporting_fact_ids, [ust.context_id])
        assert validate_principles(c, result.package) == []


# ============================================================ B. confidence ↔ language strength

class TestConfidenceLanguageCoupling:
    @pytest.mark.parametrize("key", sorted(OUTLOOK_PHRASES, key=lambda k: (k[0].value, k[1].value)))
    def test_phrase_table_is_mechanically_consistent(self, key):
        direction, confidence = key
        phrase = outlook_phrase(direction, confidence)
        assert asserted_strength(phrase) is confidence, phrase
        assert asserted_bias(phrase) is direction, phrase
        assert any(form in phrase for form in OUTLOOK_FORMS)

    def test_strength_lexicon_covers_every_confidence(self):
        assert {c for _w, c in STRENGTH_LEXICON} == set(Confidence)

    def test_generated_outlook_matches_confidence(self, result):
        outlook = result.draft.claims_for_role(ClaimRole.OUTLOOK)[0]
        assert asserted_strength(outlook.text) is result.outlook.confidence
        assert result.outlook.confidence is Confidence.MEDIUM
        assert "可能性がある" in outlook.text and "見込まれる" not in outlook.text
        assert validate_confidence(outlook, result.outlook) == []

    @pytest.mark.parametrize("text,code", [
        ("次の東京セッションは堅調な展開が見込まれる（確度: 中）。", "confidence_language_mismatch"),
        ("次の東京セッションは堅調な展開となろう（確度: 中）。", "confidence_language_mismatch"),
        ("次の東京セッションは方向感が限定的ながら上値を試す余地がある。", "confidence_language_mismatch"),
        ("次の東京セッションは堅調である。", "confidence_language_missing"),
    ])
    def test_mismatched_strength_is_rejected(self, result, text, code):
        topix = result.package.context_for(INDEX_DIRECTION, TOPIX)
        c = claim(ClaimRole.OUTLOOK, ClaimType.OUTLOOK, text, (), [topix.context_id])
        assert [i.code for i in validate_confidence(c, result.outlook)] == [code]
        assert evaluate_claim(c, result.package, result.outlook, CompassConfig()
                              ).grounding_status is GroundingStatus.REJECTED

    def test_low_confidence_uses_weak_language(self):
        """支持材料1件・反対材料1件 → LOW。「堅調な展開」の強い断定を出さない。"""
        facts = [fact("index_change_pct", TOPIX, "0.62"),
                 fact("yield_change", UST10Y, "0.040", unit="pct_point")] + level_facts()
        res = run_pipeline(snapshot_for(facts), facts, config=CompassConfig(), now=NOW)
        assert res.draft.verdict is QualityVerdict.VALID
        assert res.outlook.direction is OutlookDirection.UPWARD_BIAS
        assert res.outlook.confidence is Confidence.LOW
        outlook = res.draft.claims_for_role(ClaimRole.OUTLOOK)[0].text
        assert "余地がある" in outlook and "方向感が限定的" in outlook
        assert "堅調な展開" not in outlook and "となろう" not in outlook
        assert asserted_strength(outlook) is Confidence.LOW
        assert "余地がある" in res.draft.one_liner
        assert validate_one_liner(res.draft.one_liner, CompassConfig()) == []

    def test_deterministic_generator_never_emits_stronger_than_confidence(self, result):
        gen = DeterministicNarrativeGenerator()
        for confidence in Confidence:
            outlook = type(result.outlook)(
                direction=result.outlook.direction, confidence=confidence,
                horizon=result.outlook.horizon,
                supporting_context_ids=result.outlook.supporting_context_ids,
                counter_context_ids=result.outlook.counter_context_ids,
                invalidation_conditions=result.outlook.invalidation_conditions)
            claims = gen.generate(result.package, result.plan, outlook, result.implications)
            text = next(c.text for c in claims if c.claim_role is ClaimRole.OUTLOOK)
            assert asserted_strength(text) is confidence, text
            assert asserted_bias(text) is result.outlook.direction


class TestPreflightDoesNotAlterHistoricalEvidence:
    def test_phase3c_spec_still_records_live_run_19(self):
        text = open("docs/databank/COMPASS_GENERATOR_SPEC.md", encoding="utf-8").read()
        assert "actions/runs/33566763923" in text
        assert "compass_f267ad4239e278f209be0ad7" in text
