"""Phase 4 P4-1A: Morning Brief 三段 projection のテスト。

検証の軸:
- **決定論**（同じ入力 → 同じ brief / 同じ brief_id、projection が変われば別 ID）
- **射影であって生成ではない**（Tier 1 は one_liner 完全一致、新しい散文を作らない）
- **fail closed**（材料が無ければ tier を落として機械可読な理由を残す）
- **境界**（Decision / formal_review / corpus / replay / legacy を import しない、
  cpt_* を rule_ref として出さない、機密 path / PDF 名を持たない）

Compass の validation suite は複製しない。ここは projection 層だけを見る。
"""
from __future__ import annotations

import ast
import json
from dataclasses import replace
from pathlib import Path

import pytest

from src.intelligence.compass.config import CompassConfig
from src.intelligence.compass.generator import new_claim
from src.intelligence.compass.model import (
    ClaimRole,
    ClaimType,
    GroundingStatus,
    QualityVerdict,
)
from src.intelligence.compass.pipeline import run_pipeline
from src.intelligence.reports.model import (
    MORNING_BRIEF_SCHEMA_VERSION,
    R_DRAFT_NOT_USABLE,
    R_NO_GROUNDED_COUNTER_CASE,
    R_NO_GROUNDED_OUTLOOK,
    R_NO_GROUNDED_POINTS,
    R_ONE_LINER_UNAVAILABLE,
    TIER2_COVERAGE_ROLES,
    TIER2_POINT_ROLES,
    TIER3_ROLES,
)
from src.intelligence.reports.morning_brief import build_morning_brief
from tests.intelligence.test_compass_generator import (
    MORNING,
    NOW,
    base_facts,
    snapshot_for,
    stale_lead_facts,
)

REPORTS_DIR = Path("src/intelligence/reports")

#: P4-1A が触れてはならない package（Phase 4 entry contract §2 / §3）
FORBIDDEN_INTELLIGENCE = (
    "decision", "formal_review", "review", "shadow_review",
    "corpus", "corpus_research", "replay", "evaluation",
)
#: legacy 側（Phase 4 は legacy brief の refactor ではない）
FORBIDDEN_LEGACY = ("report", "analysis", "collectors")


# ---------------------------------------------------------------- fixtures

@pytest.fixture(scope="module")
def facts():
    return base_facts()


@pytest.fixture(scope="module")
def result(facts):
    return run_pipeline(snapshot_for(facts), facts, config=CompassConfig(), now=NOW)


@pytest.fixture(scope="module")
def draft(result):
    return result.draft


@pytest.fixture(scope="module")
def package(result):
    return result.package


@pytest.fixture(scope="module")
def brief(draft, package):
    return build_morning_brief(draft, package)


def _claim(role, ctype, text, *, order=1, grounded=True, rule_ref=""):
    made = new_claim(session_date=MORNING, role=role, claim_type=ctype, text=text,
                     generator="fake", order=order, rule_ref=rule_ref)
    status = GroundingStatus.GROUNDED if grounded else GroundingStatus.REJECTED
    return replace(made, grounding_status=status)


def _imported_top_levels(path: Path):
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            yield node.module.lstrip(".").split(".")[0]
        elif isinstance(node, ast.Import):
            for alias in node.names:
                yield alias.name.split(".")[0]


# ---------------------------------------------------------------- determinism

class TestDeterminism:
    def test_composition_is_deterministic(self, draft, package):
        assert build_morning_brief(draft, package).as_dict() == \
            build_morning_brief(draft, package).as_dict()

    def test_same_input_same_brief_id(self, draft, package):
        assert build_morning_brief(draft, package).brief_id == \
            build_morning_brief(draft, package).brief_id

    def test_changed_projection_changes_brief_id(self, draft, package, brief):
        changed = replace(draft, one_liner=draft.one_liner + "追記。")
        assert build_morning_brief(changed, package).brief_id != brief.brief_id

    def test_brief_id_is_content_addressed_not_time_based(self, draft, package):
        """generated_at を動かしても projection が同じなら ID は変わらない。"""
        from datetime import timedelta
        moved = replace(draft, generated_at=(draft.generated_at or NOW) + timedelta(days=3))
        assert build_morning_brief(moved, package).brief_id == \
            build_morning_brief(draft, package).brief_id

    def test_ordering_is_deterministic(self, brief):
        for group in (brief.tier2.points, brief.tier3.why, brief.tier3.risk):
            keys = [(p.order, p.claim_id) for p in group]
            assert keys == sorted(keys)

    def test_schema_version_stable(self, brief):
        assert brief.schema_version == MORNING_BRIEF_SCHEMA_VERSION == "0.2.0"
        assert brief.as_dict()["schema_version"] == "0.2.0"


# ---------------------------------------------------------------- tier 1

class TestTier1:
    def test_equals_draft_one_liner_exactly(self, draft, brief):
        if draft.one_liner.strip():
            assert brief.tier1.available is True
            assert brief.tier1.text == draft.one_liner
        else:                                     # 空なら出さない（下のテストが担当）
            assert brief.tier1.available is False

    def test_empty_one_liner_emits_no_invented_prose(self, draft, package):
        out = build_morning_brief(replace(draft, one_liner=""), package)
        assert out.tier1.available is False
        assert out.tier1.text == ""
        assert out.tier1.unavailable_reason in (R_ONE_LINER_UNAVAILABLE,
                                                draft.abstain_reason or R_ONE_LINER_UNAVAILABLE)

    def test_whitespace_one_liner_is_not_content(self, draft, package):
        out = build_morning_brief(replace(draft, one_liner="   "), package)
        assert out.tier1.available is False and out.tier1.text == ""


# ---------------------------------------------------------------- tier 2 / tier 3 roles

class TestTierRoles:
    def test_tier2_contains_only_allowed_roles(self, brief):
        assert {p.claim_role for p in brief.tier2.points} <= set(TIER2_POINT_ROLES)
        assert {p.claim_role for p in brief.tier2.coverage} <= set(TIER2_COVERAGE_ROLES)

    def test_tier3_contains_only_allowed_roles(self, brief):
        roles = {p.claim_role for p in
                 brief.tier3.outlook_points + brief.tier3.why + brief.tier3.risk}
        assert roles <= set(TIER3_ROLES)
        assert {p.claim_role for p in brief.tier3.outlook_points} == {ClaimRole.OUTLOOK} \
            or not brief.tier3.outlook_points

    def test_all_projected_points_are_grounded(self, brief):
        assert brief.points, "projection が空では境界を検証できない"
        assert all(p.grounding_status in (GroundingStatus.GROUNDED,
                                          GroundingStatus.GROUNDED_WITH_WARNINGS)
                   for p in brief.points)

    def test_rejected_claims_are_excluded(self, draft, package):
        poison = _claim(ClaimRole.HEADLINE, ClaimType.FACTUAL, "却下された見出し。",
                        order=99, grounded=False)
        out = build_morning_brief(replace(draft, claims=draft.claims + (poison,)), package)
        assert poison.claim_id not in {p.claim_id for p in out.points}
        assert "却下された見出し" not in json.dumps(out.as_dict(), ensure_ascii=False)

    def test_pending_claims_are_excluded(self, draft, package):
        pending = new_claim(session_date=MORNING, role=ClaimRole.WHAT_HAPPENED,
                            claim_type=ClaimType.FACTUAL, text="未検証の文。",
                            generator="fake", order=98)
        assert pending.grounding_status is GroundingStatus.PENDING
        out = build_morning_brief(replace(draft, claims=draft.claims + (pending,)), package)
        assert pending.claim_id not in {p.claim_id for p in out.points}


# ---------------------------------------------------------------- provenance

class TestProvenance:
    def test_brief_traces_back_to_draft_and_package(self, brief, draft, package):
        assert brief.draft_id == draft.draft_id
        assert brief.package_id == draft.package_id == package.package_id
        assert brief.session_date == draft.session_date
        assert brief.reference_session == draft.reference_session
        assert brief.verdict is draft.verdict

    def test_each_point_keeps_claim_provenance(self, brief, draft):
        by_id = {c.claim_id: c for c in draft.claims}
        assert brief.points
        for point in brief.points:
            source = by_id[point.claim_id]
            assert point.text == source.text
            assert point.claim_role is source.claim_role
            assert point.claim_type is source.claim_type
            assert point.supporting_fact_ids == tuple(source.supporting_fact_ids)
            assert point.supporting_context_ids == tuple(source.supporting_context_ids)
            assert point.grounding_status is source.grounding_status

    def test_package_mismatch_is_rejected(self, draft, package):
        with pytest.raises(ValueError):
            build_morning_brief(replace(draft, package_id="pkg_other"), package)


# ---------------------------------------------------------------- missingness / abstain

class TestMissingnessAndAbstain:
    def test_dimension_status_is_preserved_for_listed_dimensions(self, brief, package):
        listed = set(brief.tier2.missing_dimensions) | set(brief.tier2.unreliable_dimensions)
        assert set(brief.tier2.dimension_status) == listed
        for dim, status in brief.tier2.dimension_status.items():
            assert status == package.dimension_status[dim].value

    def test_missing_dimensions_are_preserved(self, brief, package):
        assert brief.tier2.missing_dimensions == tuple(package.missing_dimensions)
        assert brief.tier2.unreliable_dimensions == tuple(package.unreliable_dimensions)

    def test_degraded_input_reports_missing_dimensions(self):
        """実際に次元が欠けた入力で、欠落が黙って消えないこと。"""
        degraded = stale_lead_facts(base_facts())
        res = run_pipeline(snapshot_for(degraded), degraded, config=CompassConfig(), now=NOW)
        out = build_morning_brief(res.draft, res.package)
        assert out.tier2.missing_dimensions          # 空ではない = 欠落が保持されている
        assert out.tier2.missing_dimensions == tuple(res.package.missing_dimensions)
        assert out.tier2.unreliable_dimensions == tuple(res.package.unreliable_dimensions)

    def test_abstained_draft_emits_no_substantive_prose(self, draft, package):
        out = build_morning_brief(
            replace(draft, verdict=QualityVerdict.ABSTAINED, abstain_reason="no_counter_case"),
            package)
        assert out.tier1.available is False and out.tier1.text == ""
        assert out.tier2.available is False and out.tier2.points == ()
        assert out.tier3.available is False and out.tier3.outlook is None
        assert out.tier3.outlook_points == () and out.tier3.why == () and out.tier3.risk == ()
        assert out.tier1.unavailable_reason == "no_counter_case"

    def test_abstained_draft_still_keeps_missingness(self, draft, package):
        out = build_morning_brief(replace(draft, verdict=QualityVerdict.ABSTAINED), package)
        assert out.tier2.missing_dimensions == tuple(package.missing_dimensions)
        assert out.tier2.unavailable_reason in (R_DRAFT_NOT_USABLE, draft.abstain_reason)

    def test_rejected_draft_is_not_usable(self, draft, package):
        out = build_morning_brief(replace(draft, verdict=QualityVerdict.REJECTED), package)
        assert (out.tier1.available, out.tier2.available, out.tier3.available) == \
            (False, False, False)

    def test_no_grounded_points_reports_reason(self, draft, package):
        kept = tuple(c for c in draft.claims
                     if c.claim_role not in (ClaimRole.HEADLINE, ClaimRole.WHAT_HAPPENED))
        out = build_morning_brief(replace(draft, claims=kept), package)
        assert out.tier2.available is False
        assert out.tier2.unavailable_reason == R_NO_GROUNDED_POINTS
        assert out.tier2.points == ()

    def test_outlook_without_counter_case_is_not_emitted(self, draft, package):
        kept = tuple(c for c in draft.claims if c.claim_role is not ClaimRole.RISK)
        out = build_morning_brief(replace(draft, claims=kept), package)
        assert out.tier3.available is False
        assert out.tier3.unavailable_reason == R_NO_GROUNDED_COUNTER_CASE
        assert out.tier3.outlook is None and out.tier3.outlook_points == ()

    def test_no_outlook_claim_reports_reason(self, draft, package):
        kept = tuple(c for c in draft.claims if c.claim_role is not ClaimRole.OUTLOOK)
        out = build_morning_brief(replace(draft, claims=kept), package)
        assert out.tier3.available is False
        assert out.tier3.unavailable_reason == R_NO_GROUNDED_OUTLOOK

    def test_missing_outlook_object_blocks_tier3(self, draft, package):
        out = build_morning_brief(replace(draft, outlook=None), package)
        assert out.tier3.available is False and out.tier3.outlook is None


# ---------------------------------------------------------------- rule_ref boundary

class TestRuleRefBoundary:
    def test_unknown_rule_ref_is_passed_through_not_repaired(self, draft, package):
        odd = _claim(ClaimRole.WHY, ClaimType.INTERPRETIVE, "根拠の文。", order=97,
                     rule_ref="ZZ_UNKNOWN_999")
        out = build_morning_brief(replace(draft, claims=draft.claims + (odd,)), package)
        projected = {p.claim_id: p for p in out.points}
        assert projected[odd.claim_id].rule_ref == "ZZ_UNKNOWN_999"  # 直さない・消さない

    def test_rule_ref_is_never_invented(self, brief, draft):
        by_id = {c.claim_id: c for c in draft.claims}
        for point in brief.points:
            assert point.rule_ref == by_id[point.claim_id].rule_ref
            assert point.market_principle_version == \
                by_id[point.claim_id].market_principle_version

    def test_no_formal_review_pattern_id_is_emitted(self, brief, draft, package):
        blob = json.dumps(brief.as_dict(), ensure_ascii=False)
        for prefix in ("cpt_", "cdc_", "frp_", "cpr_", "crd_", "crp_"):
            assert prefix not in blob
        assert all(not p.rule_ref.startswith("cpt_") for p in brief.points)

    def test_emitted_principle_refs_are_registered_compass_dna(self, brief):
        """出た rule_ref が Compass DNA registry の rule_id であること（authority 境界）。

        composer 側は検証しない（再検証禁止）。ここは projection 結果に対する境界テスト。
        """
        from src.intelligence.compass.market_principles import is_registered
        assert brief.tier3.principle_refs, "rule_ref が 1 つも出ないと境界を検証できない"
        for ref in brief.tier3.principle_refs:
            assert is_registered(ref), ref

    def test_projection_carries_no_decision_layer_fields(self, brief):
        blob = json.dumps(brief.as_dict(), ensure_ascii=False).lower()
        for token in ("decision_id", "decision_type", "promotion_status", "not_promoted",
                      "keep_reviewing", "approve_recommended", "record_hash",
                      "replay_run_id", "packet_id"):
            assert token not in blob


# ---------------------------------------------------------------- isolation guards

class TestIsolation:
    def test_reports_package_imports_no_governance_layer(self):
        for path in sorted(REPORTS_DIR.glob("*.py")):
            tops = set(_imported_top_levels(path))
            assert not tops & set(FORBIDDEN_INTELLIGENCE), (path.name, tops)

    def test_reports_package_imports_no_legacy(self):
        for path in sorted(REPORTS_DIR.glob("*.py")):
            source = path.read_text(encoding="utf-8")
            for legacy in FORBIDDEN_LEGACY:
                assert f"src.{legacy}" not in source, (path.name, legacy)
            tops = set(_imported_top_levels(path))
            assert not tops & set(FORBIDDEN_LEGACY), (path.name, tops)

    def test_reports_package_has_no_confidential_references(self):
        for path in sorted(REPORTS_DIR.glob("*.py")):
            source = path.read_text(encoding="utf-8")
            for token in ("rashinban", "source_docs", ".pdf", "C:\\", "/Users/",
                          "api_key", "secret", "token"):
                assert token not in source, (path.name, token)

    def test_composer_performs_no_io(self):
        """純関数であること: open / Path / requests / store を持ち込まない。"""
        source = (REPORTS_DIR / "morning_brief.py").read_text(encoding="utf-8")
        for token in ("open(", "Path(", "requests", "urllib", "sqlite3",
                      "data_root", "datetime.now", "time.time", "random", "uuid"):
            assert token not in source, token
