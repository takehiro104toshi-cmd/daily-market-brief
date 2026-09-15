"""Phase 4 P4-1B: Morning Brief の Markdown 描画テスト。

検証の軸:
- **決定論**（同じ brief → byte 一致の Markdown）
- **表示であって生成ではない**（本文は verbatim・新しい市場コメントを作らない）
- **fail closed**（提示できない区分を捏造で埋めない）
- **境界**（id を customer prose へ出さない・I/O なし・governance / legacy を import しない）

generator / quality gate のテストは複製しない。ここは描画層だけを見る。
"""
from __future__ import annotations

import ast
from dataclasses import replace
from pathlib import Path

import pytest

from src.intelligence.compass.config import CompassConfig
from src.intelligence.compass.model import QualityVerdict
from src.intelligence.compass.pipeline import run_pipeline
from src.intelligence.reports.model import (
    R_DRAFT_NOT_USABLE,
    R_NO_GROUNDED_COUNTER_CASE,
    R_ONE_LINER_UNAVAILABLE,
    BriefTier1,
    BriefTier2,
    BriefTier3,
    MorningBrief,
)
from src.intelligence.reports.morning_brief import build_morning_brief
from src.intelligence.reports.render_markdown import (
    CONFIDENCE_JA,
    DIMENSION_JA,
    DIRECTION_JA,
    HORIZON_JA,
    STATUS_JA,
    H_COVERAGE,
    H_RISK,
    H_TIER1,
    H_TIER2,
    H_TIER3,
    H_TITLE,
    H_WHY,
    L_MISSING,
    L_UNRELIABLE,
    UNAVAILABLE,
    render_morning_brief_markdown,
)
from tests.intelligence.test_compass_generator import (
    NOW,
    base_facts,
    snapshot_for,
    stale_lead_facts,
)

RENDERER = Path("src/intelligence/reports/render_markdown.py")

FORBIDDEN_INTELLIGENCE = (
    "decision", "formal_review", "review", "shadow_review",
    "corpus", "corpus_research", "replay", "evaluation",
)
FORBIDDEN_LEGACY = ("report", "analysis", "collectors")


# ---------------------------------------------------------------- fixtures

def _brief_from(facts):
    result = run_pipeline(snapshot_for(facts), facts, config=CompassConfig(), now=NOW)
    return build_morning_brief(result.draft, result.package), result


@pytest.fixture(scope="module")
def brief():
    return _brief_from(base_facts())[0]


@pytest.fixture(scope="module")
def markdown(brief):
    return render_morning_brief_markdown(brief)


@pytest.fixture(scope="module")
def degraded_brief():
    return _brief_from(stale_lead_facts(base_facts()))[0]


def _minimal_brief(**overrides) -> MorningBrief:
    """tier が 1 つも出せない最小 brief（描画が安全に成立することを見る）。"""
    base = dict(
        brief_id="brief_minimal", session_date="2026-09-02", reference_session="2026-09-01",
        draft_id="compass_x", package_id="pkg_x", verdict=QualityVerdict.ABSTAINED,
        generator="deterministic", abstain_reason="",
        tier1=BriefTier1(available=False, unavailable_reason=R_ONE_LINER_UNAVAILABLE),
        tier2=BriefTier2(available=False, unavailable_reason=R_DRAFT_NOT_USABLE),
        tier3=BriefTier3(available=False, unavailable_reason=R_DRAFT_NOT_USABLE))
    base.update(overrides)
    return MorningBrief(**base)


def _imported_top_levels(path: Path):
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.ImportFrom) and node.module:
            yield node.module.lstrip(".").split(".")[0]
        elif isinstance(node, ast.Import):
            for alias in node.names:
                yield alias.name.split(".")[0]


def _customer_body(text: str) -> str:
    """customer-facing 本文（見出しを除いた表示テキスト）。"""
    return "\n".join(line for line in text.splitlines() if not line.startswith("#"))


# ---------------------------------------------------------------- determinism

class TestDeterminism:
    def test_byte_identical_for_same_brief(self, brief):
        assert render_morning_brief_markdown(brief) == render_morning_brief_markdown(brief)

    def test_headings_are_deterministic_and_ordered(self, markdown):
        headings = [line for line in markdown.splitlines() if line.startswith("#")]
        assert headings[0] == f"# {H_TITLE}（2026-09-02）"
        h2 = [h for h in headings if h.startswith("## ")]
        assert h2 == [f"## {H_TIER1}", f"## {H_TIER2}", f"## {H_TIER3}"]
        assert all(h.startswith(("# ", "## ", "### ")) for h in headings)

    def test_no_fourth_tier_heading(self, markdown):
        h2 = [line for line in markdown.splitlines() if line.startswith("## ")]
        assert len(h2) == 3
        h3 = {line for line in markdown.splitlines() if line.startswith("### ")}
        assert h3 <= {f"### {H_COVERAGE}", f"### {H_WHY}", f"### {H_RISK}"}

    def test_output_ends_with_single_newline(self, markdown):
        assert markdown.endswith("\n") and not markdown.endswith("\n\n")

    def test_rendering_does_not_mutate_brief(self, brief):
        before = brief.as_dict()
        render_morning_brief_markdown(brief)
        assert brief.as_dict() == before


# ---------------------------------------------------------------- tier 1

class TestTier1:
    def test_display_text_appears_verbatim(self, brief, markdown):
        assert brief.tier1.available and brief.tier1.display_text
        assert brief.tier1.display_text in markdown

    def test_unavailable_emits_no_invented_prose(self, brief):
        out = render_morning_brief_markdown(replace(
            brief, tier1=BriefTier1(available=False,
                                    unavailable_reason=R_ONE_LINER_UNAVAILABLE)))
        assert f"（この区分は本日提示できません。理由: {R_ONE_LINER_UNAVAILABLE}）" in out
        assert brief.tier1.display_text not in out

    def test_unsafe_reason_is_not_exposed(self, brief):
        """契約語彙でない理由（例外文など）は表示しない。"""
        out = render_morning_brief_markdown(replace(
            brief, tier1=BriefTier1(available=False,
                                    unavailable_reason="Traceback: /home/u/x.py line 3")))
        assert UNAVAILABLE in out
        assert "Traceback" not in out and "/home/u/x.py" not in out


# ---------------------------------------------------------------- tier 2

class TestTier2:
    def test_renders_points_in_brief_order(self, brief, markdown):
        assert brief.tier2.points
        positions = [markdown.index(p.display_text) for p in brief.tier2.points]
        assert positions == sorted(positions)

    def test_renders_only_existing_points_and_coverage(self, brief, markdown):
        section = markdown.split(f"## {H_TIER2}")[1].split(f"## {H_TIER3}")[0]
        bullets = [line[2:] for line in section.splitlines() if line.startswith("- ")]
        known = ({p.display_text for p in brief.tier2.points}
                 | {p.display_text for p in brief.tier2.coverage})
        extra = [b for b in bullets if b not in known
                 and not b.startswith((L_MISSING, L_UNRELIABLE))]
        assert extra == [], extra

    def test_coverage_claim_is_rendered(self, brief, markdown):
        for point in brief.tier2.coverage:
            assert point.display_text in markdown

    def test_missing_and_unreliable_dimensions_are_represented(self, degraded_brief):
        """生キーではなく日本語ラベル＋充足状況で出ること。"""
        out = render_morning_brief_markdown(degraded_brief)
        assert degraded_brief.tier2.missing_dimensions
        assert f"### {H_COVERAGE}" in out and L_MISSING in out
        for dim in degraded_brief.tier2.missing_dimensions:
            assert dim not in out                       # 生キーは出さない
            assert DIMENSION_JA[dim] in out             # ラベルは出す
            assert STATUS_JA[degraded_brief.tier2.dimension_status[dim]] in out

    def test_missing_dimension_is_not_turned_into_a_market_view(self, degraded_brief):
        out = render_morning_brief_markdown(degraded_brief)
        line = next(l for l in out.splitlines() if l.startswith(f"- {L_MISSING}"))
        for word in ("上昇", "下落", "堅調", "軟調", "見通し", "とみられる"):
            assert word not in line

    def test_unavailable_tier2_keeps_coverage(self, brief):
        out = render_morning_brief_markdown(replace(
            brief, tier2=BriefTier2(available=False, coverage=brief.tier2.coverage,
                                    missing_dimensions=("usd_jpy",),
                                    dimension_status={"usd_jpy": "STALE"},
                                    unavailable_reason="no_grounded_points")))
        assert "（この区分は本日提示できません。理由: no_grounded_points）" in out
        assert DIMENSION_JA["usd_jpy"] in out and STATUS_JA["STALE"] in out
        assert "usd_jpy" not in out
        for point in brief.tier2.points:
            body = out.split(f"## {H_TIER2}")[1].split(f"## {H_TIER3}")[0]
            assert point.display_text not in body


# ---------------------------------------------------------------- tier 3

class TestTier3:
    def test_renders_outlook_why_and_risk_from_brief_only(self, brief, markdown):
        section = markdown.split(f"## {H_TIER3}")[1]
        assert brief.tier3.outlook is not None
        assert DIRECTION_JA[brief.tier3.outlook.direction] in section
        assert CONFIDENCE_JA[brief.tier3.outlook.confidence] in section
        assert HORIZON_JA[brief.tier3.outlook.horizon] in section
        bullets = [line[2:] for line in section.splitlines() if line.startswith("- ")]
        known = {p.display_text for p in
                 brief.tier3.outlook_points + brief.tier3.why + brief.tier3.risk}
        assert set(bullets) <= known
        assert f"### {H_WHY}" in section and f"### {H_RISK}" in section

    def test_no_advice_or_target_language_is_added(self, markdown):
        for banned in ("推奨", "買い", "売り", "目標株価", "ターゲット", "%の確率"):
            assert banned not in markdown

    def test_unavailable_tier3_does_not_fabricate_outlook(self, brief):
        out = render_morning_brief_markdown(replace(
            brief, tier3=BriefTier3(available=False,
                                    unavailable_reason=R_NO_GROUNDED_COUNTER_CASE)))
        section = out.split(f"## {H_TIER3}")[1]
        assert f"（この区分は本日提示できません。理由: {R_NO_GROUNDED_COUNTER_CASE}）" in section
        assert f"### {H_WHY}" not in section and f"### {H_RISK}" not in section
        for point in brief.tier3.outlook_points + brief.tier3.why + brief.tier3.risk:
            assert point.display_text not in section


# ---------------------------------------------------------------- abstain / minimal

class TestAbstainAndMinimal:
    def test_abstained_brief_has_no_unsupported_commentary(self, brief):
        out = render_morning_brief_markdown(replace(
            brief, verdict=QualityVerdict.ABSTAINED,
            tier1=BriefTier1(available=False, unavailable_reason=R_DRAFT_NOT_USABLE),
            tier2=BriefTier2(available=False, unavailable_reason=R_DRAFT_NOT_USABLE),
            tier3=BriefTier3(available=False, unavailable_reason=R_DRAFT_NOT_USABLE)))
        body = _customer_body(out)
        assert body.count(f"理由: {R_DRAFT_NOT_USABLE}") == 3
        for word in ("上昇", "下落", "堅調", "軟調", "とみられる"):
            assert word not in body

    def test_minimal_brief_renders_safely(self):
        out = render_morning_brief_markdown(_minimal_brief())
        assert out.startswith(f"# {H_TITLE}（2026-09-02）")
        assert out.count("## ") == 3
        assert out.endswith("\n")
        assert f"### {H_COVERAGE}" not in out

    def test_valid_with_warnings_renders_all_tiers(self, degraded_brief):
        assert degraded_brief.verdict is QualityVerdict.VALID_WITH_WARNINGS
        out = render_morning_brief_markdown(degraded_brief)
        assert UNAVAILABLE not in out


# ---------------------------------------------------------------- provenance / safety

class TestProvenanceAndSafety:
    def test_no_internal_ids_in_output(self, brief, markdown):
        for point in brief.points:
            assert point.claim_id not in markdown
            for fid in point.supporting_fact_ids:
                assert fid not in markdown
            for cid in point.supporting_context_ids:
                assert cid not in markdown
        assert brief.draft_id not in markdown
        assert brief.package_id not in markdown
        assert brief.brief_id not in markdown

    def test_no_id_prefix_leaks(self, markdown):
        for prefix in ("cpt_", "cdc_", "frp_", "cpr_", "crd_", "crp_",
                       "ctx_", "fact_", "claim_", "brief_", "compass_", "pkg_"):
            assert prefix not in markdown

    def test_no_local_path_or_source_name_leak(self, markdown):
        for token in ("C:\\", "/home/", "/Users/", ".pdf", "source_docs", "rashinban",
                      "data_root", "INTELLIGENCE_DATA_ROOT"):
            assert token not in markdown

    def test_no_hidden_html_comment_provenance(self, markdown):
        assert "<!--" not in markdown and "-->" not in markdown

    def test_japanese_text_round_trips_exactly(self, brief, markdown):
        for point in brief.points:
            assert point.display_text in markdown, point.claim_id

    def test_leading_hash_in_source_text_cannot_break_sections(self, brief):
        poisoned = replace(brief.tier1, display_text="# 見出しに化ける文。")
        out = render_morning_brief_markdown(replace(brief, tier1=poisoned))
        headings = [line for line in out.splitlines() if line.startswith("#")]
        assert "# 見出しに化ける文。" not in headings
        assert "\\# 見出しに化ける文。" in out
        assert len([h for h in headings if h.startswith("## ")]) == 3


# ---------------------------------------------------------------- isolation

class TestIsolation:
    def test_no_governance_imports(self):
        tops = set(_imported_top_levels(RENDERER))
        assert not tops & set(FORBIDDEN_INTELLIGENCE), tops

    def test_no_legacy_imports(self):
        source = RENDERER.read_text(encoding="utf-8")
        for legacy in FORBIDDEN_LEGACY:
            assert f"src.{legacy}" not in source
        assert not set(_imported_top_levels(RENDERER)) & set(FORBIDDEN_LEGACY)

    def test_renderer_imports_only_model_and_stdlib(self):
        assert set(_imported_top_levels(RENDERER)) <= {"__future__", "re", "typing", "model"}

    def test_renderer_performs_no_io(self):
        source = RENDERER.read_text(encoding="utf-8")
        for token in ("open(", "Path(", "requests", "urllib", "sqlite3", "data_root",
                      "datetime", "time.time", "random", "uuid", "os.environ", "getenv"):
            assert token not in source, token

    def test_renderer_does_not_import_draft_or_package(self):
        """入力は MorningBrief だけ。pipeline へ戻らない。"""
        source = RENDERER.read_text(encoding="utf-8")
        for token in ("CompassDraft", "EvidencePackage", "run_pipeline", "build_morning_brief"):
            assert token not in source, token
