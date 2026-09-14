"""Phase 4 P4-1 presentation refinement のテスト。

実データ run（Actions 34896447537 / session 2026-09-15）で顧客向け Markdown に出てしまった
内部語彙が、**分析層を変えずに**表示層で除かれていることを見る:

    経験則 ID（JP_*） / "Evidence Package" / 因果注記の内部表現 /
    raw enum（UPWARD_BIAS・LOW・next_tokyo_session） / 次元キー / STALE / 次元一覧の二重掲載

同時に、provenance（claim_id・fact/context ids・rule_ref・版）が **object 側には残る**こと、
CompassDraft が projection で一切変わらないことを確認する。
"""
from __future__ import annotations

import ast
from dataclasses import replace
from pathlib import Path

import pytest

from src.intelligence.compass.config import CompassConfig
from src.intelligence.compass.model import (
    ClaimRole,
    ClaimType,
    Confidence,
    GroundingStatus,
    OutlookDirection,
    QualityVerdict,
)
from src.intelligence.compass.pipeline import run_pipeline
from src.intelligence.context.model import STATE_DIMENSIONS, ContextStatus
from src.intelligence.internals.types import INTERNALS_DIMENSIONS
from src.intelligence.reports.model import (
    MORNING_BRIEF_SCHEMA_VERSION,
    BriefOutlook,
    BriefPoint,
    BriefTier1,
    BriefTier2,
    BriefTier3,
    MorningBrief,
)
from src.intelligence.reports.morning_brief import (
    DISPLAY_REPLACEMENTS,
    build_morning_brief,
    customer_text,
)
from src.intelligence.reports.render_markdown import (
    CONFIDENCE_JA,
    DIMENSION_JA,
    DIRECTION_JA,
    HORIZON_JA,
    STATUS_JA,
    UnmappedDisplayValue,
    render_morning_brief_markdown,
)
from tests.intelligence.test_compass_generator import (
    MORNING,
    NOW,
    base_facts,
    snapshot_for,
    stale_lead_facts,
)

REPORTS_DIR = Path("src/intelligence/reports")

#: 顧客向け Markdown に出てはならない内部トークン（実データ run で観測されたもの）
INTERNAL_TOKENS = (
    "JP_DIR_001", "JP_US_001", "経験則", "Evidence Package", "因果関係は特定しない",
    "UPWARD_BIAS", "DOWNWARD_BIAS", "RANGE_BOUND", "MIXED", "UNCERTAIN",
    "next_tokyo_session", "STALE", "MISSING", "NOT_ENTITLED", "CONFLICTED",
    "nikkei_vs_topix", "nt_ratio", "japan_rates", "usd_jpy", "japan_equities",
    "us_rates_2y", "us_rates_10y", "us_curve", "語れない次元",
)
#: 助言・推奨語（表示層で足していないこと）
ADVICE_TOKENS = ("推奨", "買い", "売り", "目標株価", "ターゲット", "すべきです", "おすすめ")


def _point(role: ClaimRole, ctype: ClaimType, text: str, *, order: int,
           ref: str = "") -> BriefPoint:
    """観測された実データ形の claim を、そのまま projection した BriefPoint。"""
    return BriefPoint(
        claim_id=f"claim_regression_{order}", claim_role=role, claim_type=ctype,
        text=text, display_text=customer_text(text),
        grounding_status=GroundingStatus.GROUNDED, order=order,
        supporting_fact_ids=("fact_regression",), supporting_context_ids=("ctx_regression",),
        rule_ref=ref, interpretation_type="market_principle" if ref else "",
        market_principle_version="compass_dna.market_rules:0.1.0" if ref else "")


def _brief_from(facts):
    result = run_pipeline(snapshot_for(facts), facts, config=CompassConfig(), now=NOW)
    return build_morning_brief(result.draft, result.package), result


@pytest.fixture(scope="module")
def normal():
    return _brief_from(base_facts())


@pytest.fixture(scope="module")
def degraded():
    return _brief_from(stale_lead_facts(base_facts()))


def _markdown(pair) -> str:
    return render_morning_brief_markdown(pair[0])


# ---------------------------------------------------------------- real-data regression

class TestRealDataShapedRegression:
    """Actions run で観測された形（4 次元劣化・UPWARD_BIAS・LOW・next_tokyo_session）。"""

    def _observed_brief(self) -> MorningBrief:
        dims = ("nikkei_vs_topix", "nt_ratio", "japan_rates", "usd_jpy")
        head = _point(ClaimRole.HEADLINE, ClaimType.FACTUAL,
                      "前営業日（2026-09-14）のTOPIXは前日比+0.74%の上昇となった。", order=1)
        cov = _point(ClaimRole.COVERAGE, ClaimType.FACTUAL,
                     "対象範囲: 米国株指数・夜間先物・個別ニュースは本Evidence Packageに含まれない。"
                     "語れない次元: nikkei_vs_topix（STALE）, nt_ratio（STALE）, "
                     "japan_rates（STALE）, usd_jpy（STALE）。", order=2)
        why = _point(ClaimRole.WHY, ClaimType.INTERPRETIVE,
                     "根拠（経験則 JP_DIR_001）: TOPIXは前日比+0.74%の上昇となったことが同時に"
                     "観測され、株式にとって追い風とみられる（因果関係は特定しない）。",
                     order=3, ref="JP_DIR_001")
        risk = _point(ClaimRole.RISK, ClaimType.RISK,
                      "反対材料（経験則 JP_US_001）: 米10年国債利回りは前日比+0.010ptの上昇と"
                      "なったことは、株式にとって逆風とみられる。", order=4, ref="JP_US_001")
        out = _point(ClaimRole.OUTLOOK, ClaimType.OUTLOOK,
                     "次の東京セッションは方向感が限定的ながら上値を試す余地がある（確度: 低）。",
                     order=5)
        return MorningBrief(
            brief_id="brief_regression", session_date="2026-09-15",
            reference_session="2026-09-14", draft_id="compass_regression",
            package_id="evpkg_regression", verdict=QualityVerdict.VALID, generator="deterministic",
            tier1=BriefTier1(available=True, text=head.text,
                             display_text=customer_text(head.text)),
            tier2=BriefTier2(available=True, points=(head,), coverage=(cov,),
                             missing_dimensions=(), unreliable_dimensions=dims,
                             dimension_status={d: "STALE" for d in dims}),
            tier3=BriefTier3(available=True, outlook=BriefOutlook(
                direction="UPWARD_BIAS", confidence="LOW", horizon="next_tokyo_session"),
                outlook_points=(out,), why=(why,), risk=(risk,),
                principle_refs=("JP_DIR_001", "JP_US_001")),
            schema_version=MORNING_BRIEF_SCHEMA_VERSION)

    def test_no_internal_token_reaches_the_customer(self):
        md = render_morning_brief_markdown(self._observed_brief())
        for token in INTERNAL_TOKENS:
            assert token not in md, token

    def test_meaning_is_preserved(self):
        md = render_morning_brief_markdown(self._observed_brief())
        assert "+0.74%" in md and "+0.010pt" in md          # 数値は変えない
        assert "因果関係を示すものではありません" in md        # 注意喚起は残す
        assert "現在の確認対象には含まれない" in md            # 範囲の事実は残す
        assert DIRECTION_JA["UPWARD_BIAS"] in md
        assert CONFIDENCE_JA["LOW"] in md
        assert HORIZON_JA["next_tokyo_session"] in md
        for dim in ("nikkei_vs_topix", "nt_ratio", "japan_rates", "usd_jpy"):
            assert DIMENSION_JA[dim] in md
        assert STATUS_JA["STALE"] in md

    def test_provenance_survives_in_the_object(self):
        brief = self._observed_brief()
        assert brief.tier3.principle_refs == ("JP_DIR_001", "JP_US_001")
        refs = {p.rule_ref for p in brief.tier3.why + brief.tier3.risk}
        assert refs == {"JP_DIR_001", "JP_US_001"}
        assert all(p.claim_id for p in brief.points)
        md = render_morning_brief_markdown(brief)
        for point in brief.points:
            assert point.claim_id not in md

    def test_dimension_list_is_not_printed_twice(self):
        md = render_morning_brief_markdown(self._observed_brief())
        assert md.count(DIMENSION_JA["nt_ratio"]) == 1
        assert md.count(DIMENSION_JA["usd_jpy"]) == 1


# ---------------------------------------------------------------- mapping completeness

class TestDisplayMappingCompleteness:
    def test_every_direction_value_is_mapped(self):
        assert {d.value for d in OutlookDirection} <= set(DIRECTION_JA)

    def test_every_confidence_value_is_mapped(self):
        assert {c.value for c in Confidence} <= set(CONFIDENCE_JA)

    def test_every_context_status_is_mapped(self):
        assert {s.value for s in ContextStatus} <= set(STATUS_JA)

    def test_every_dimension_key_is_mapped(self):
        assert set(STATE_DIMENSIONS) | set(INTERNALS_DIMENSIONS) <= set(DIMENSION_JA)

    def test_configured_horizon_is_mapped(self):
        assert CompassConfig().outlook_horizon in HORIZON_JA

    def test_unknown_values_fail_closed(self, normal):
        brief = normal[0]
        for bad in (BriefOutlook(direction="SIDEWAYS_X", confidence="LOW",
                                 horizon="next_tokyo_session"),
                    BriefOutlook(direction="UPWARD_BIAS", confidence="VERY_HIGH",
                                 horizon="next_tokyo_session"),
                    BriefOutlook(direction="UPWARD_BIAS", confidence="LOW",
                                 horizon="next_year")):
            with pytest.raises(UnmappedDisplayValue):
                render_morning_brief_markdown(
                    replace(brief, tier3=replace(brief.tier3, outlook=bad)))

    def test_unknown_dimension_fails_closed(self, normal):
        brief = normal[0]
        broken = replace(brief.tier2, missing_dimensions=("mystery_dim",),
                         dimension_status={"mystery_dim": "STALE"})
        with pytest.raises(UnmappedDisplayValue):
            render_morning_brief_markdown(replace(brief, tier2=broken))


# ---------------------------------------------------------------- projection behaviour

class TestCustomerTextProjection:
    def test_customer_text_is_deterministic_and_idempotent(self):
        raw = ("根拠（経験則 JP_DIR_001）: TOPIXは上昇したことが同時に観測され、"
               "株式にとって追い風とみられる（因果関係は特定しない）。")
        once = customer_text(raw)
        assert once == customer_text(raw) and once == customer_text(once)
        assert once.startswith("根拠: ") and "JP_DIR_001" not in once

    def test_replacements_are_explicit_constants(self):
        assert ("本Evidence Packageに含まれない", "現在の確認対象には含まれない") in DISPLAY_REPLACEMENTS
        assert ("（因果関係は特定しない）", "（因果関係を示すものではありません）") in DISPLAY_REPLACEMENTS

    def test_raw_text_is_kept_alongside_display_text(self, normal):
        brief, result = normal
        by_id = {c.claim_id: c for c in result.draft.claims}
        assert brief.points
        for point in brief.points:
            assert point.text == by_id[point.claim_id].text        # 逐語は保持
            assert point.display_text == customer_text(point.text)

    def test_projection_does_not_mutate_the_draft(self, normal):
        brief, result = normal
        before = [c.as_dict() for c in result.draft.claims]
        build_morning_brief(result.draft, result.package)
        assert [c.as_dict() for c in result.draft.claims] == before
        assert all("display_text" not in row for row in before)    # draft schema は不変

    def test_same_input_same_markdown(self, normal):
        brief = normal[0]
        assert render_morning_brief_markdown(brief) == render_morning_brief_markdown(brief)


# ---------------------------------------------------------------- pipeline output

class TestAgainstRealPipelineOutput:
    def test_no_internal_token_in_normal_brief(self, normal):
        md = _markdown(normal)
        for token in INTERNAL_TOKENS:
            assert token not in md, token

    def test_no_internal_token_in_degraded_brief(self, degraded):
        md = _markdown(degraded)
        assert degraded[0].tier2.unreliable_dimensions
        for token in INTERNAL_TOKENS:
            assert token not in md, token

    def test_missingness_still_visible(self, degraded):
        md = _markdown(degraded)
        brief = degraded[0]
        shown = set(brief.tier2.missing_dimensions) | set(brief.tier2.unreliable_dimensions)
        assert shown
        for dim in shown:
            assert DIMENSION_JA[dim] in md

    def test_no_advice_language_added(self, normal, degraded):
        for md in (_markdown(normal), _markdown(degraded)):
            for token in ADVICE_TOKENS:
                assert token not in md, token

    def test_abstained_state_remains_safe(self, normal):
        brief = normal[0]
        out = render_morning_brief_markdown(replace(
            brief,
            tier1=BriefTier1(available=False, unavailable_reason="draft_not_usable"),
            tier2=BriefTier2(available=False, unavailable_reason="draft_not_usable"),
            tier3=BriefTier3(available=False, unavailable_reason="draft_not_usable")))
        body = "\n".join(l for l in out.splitlines() if not l.startswith("#"))
        assert body.count("理由: draft_not_usable") == 3
        for token in INTERNAL_TOKENS + ADVICE_TOKENS:
            assert token not in out, token


# ---------------------------------------------------------------- isolation

class TestIsolationStillHolds:
    def test_reports_package_imports_no_governance_or_legacy_or_phase5(self):
        forbidden = {"decision", "formal_review", "review", "shadow_review", "corpus",
                     "corpus_research", "replay", "evaluation", "report", "analysis",
                     "collectors", "predictions", "themes", "thesis", "screening",
                     "personalization"}
        for path in sorted(REPORTS_DIR.glob("*.py")):
            tops = set()
            for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
                if isinstance(node, ast.ImportFrom) and node.module:
                    tops.add(node.module.lstrip(".").split(".")[0])
                elif isinstance(node, ast.Import):
                    for alias in node.names:
                        tops.add(alias.name.split(".")[0])
            assert not tops & forbidden, (path.name, tops & forbidden)
