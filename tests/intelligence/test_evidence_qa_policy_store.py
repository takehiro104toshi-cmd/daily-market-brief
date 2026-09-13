"""Policy versioning・再評価・QA storage・レポート（Phase 1-E）。"""
from __future__ import annotations

from pathlib import Path

import pytest

from src.intelligence.core import serialization
from src.intelligence.core.contracts import EvidenceAssessmentRepository
from src.intelligence.evidence_qa.assess import assess_source_document, load_source_info
from src.intelligence.evidence_qa.model import DimensionStatus, GateDecision
from src.intelligence.evidence_qa.policy import (
    DAILY_MARKET_V1,
    GENERIC_V1,
    TrustPolicy,
    get_policy,
    register_policy,
)
from src.intelligence.evidence_qa.report import render_report, summarize
from src.intelligence.evidence_qa.store import JsonlAssessmentStore
from tests.intelligence.qa_fixtures import REF, make_doc, make_source_info

serialization.register_domain_types()


def assess(doc, policy=GENERIC_V1):
    return assess_source_document(doc, source_info=make_source_info(), policy=policy,
                                  reference_time=REF)


def test_policy_identity_recorded_in_assessment() -> None:
    a = assess(make_doc())
    assert (a.policy_name, a.policy_version) == ("GENERIC", "1.0.0")


def test_policy_registry_refuses_version_overwrite() -> None:
    with pytest.raises(ValueError):
        register_policy(TrustPolicy(name="GENERIC", version="1.0.0",
                                    fresh_hours=1, stale_hours=2))
    assert get_policy("DAILY_MARKET", "1.0.0") is DAILY_MARKET_V1


def test_reassessment_with_new_policy_version_keeps_history(tmp_path: Path) -> None:
    """v1判定をv2で再評価: 旧assessmentは上書きされず両方残る（QA REPROCESSING）。"""
    strict_v2 = TrustPolicy(name="GENERIC", version="2.0.0-test",
                            fresh_hours=1, stale_hours=2,
                            stale_status=DimensionStatus.LIMIT)
    doc = make_doc(published_age_hours=48)
    v1 = assess(doc, GENERIC_V1)
    v2 = assess(doc, strict_v2)
    assert v1.decision is GateDecision.ACCEPT
    assert v2.decision is GateDecision.LIMITED_USE  # 同じ文書でもpolicy versionで判定が変わる

    store = JsonlAssessmentStore(tmp_path)
    store.add_assessment(v1)
    store.add_assessment(v2)
    history = store.assessments_for(doc.source_document_id)
    assert len(history) == 2  # append-only（上書きなし）
    assert store.latest_for(doc.source_document_id, "GENERIC").policy_version == "2.0.0-test"


def test_store_reopen_and_crash_recovery(tmp_path: Path) -> None:
    store = JsonlAssessmentStore(tmp_path)
    a = assess(make_doc())
    store.add_assessment(a)
    with (tmp_path / "assessments.jsonl").open("a", encoding="utf-8") as f:
        f.write('{"_type": "EvidenceAssessment", "assessment_id": "qa_trunc')
    reopened = JsonlAssessmentStore(tmp_path)
    assert len(list(reopened.iter_assessments())) == 1
    assert reopened.recovered_lines == 1
    got = reopened.latest_for(a.record_id)
    assert got == a  # serialization roundtrip込みで一致


def test_store_satisfies_protocol(tmp_path: Path) -> None:
    assert isinstance(JsonlAssessmentStore(tmp_path), EvidenceAssessmentRepository)


def test_assessment_serialization_roundtrip() -> None:
    a = assess(make_doc(published_age_hours=None))  # issues/horizonなし含む
    decoded = serialization.decode(serialization.encode(a))
    assert decoded == a
    assert decoded.dimensions == a.dimensions
    assert decoded.issues == a.issues


def test_load_source_info_from_catalog_shape() -> None:
    feed = {
        "id": "fed_press", "tier": 1, "investment_value": "MARKET_CRITICAL",
        "endpoint": {"usage_status": "public_feed"},
        "current_health": {"state": "degraded"},
        "duplicate_group": None,
    }
    info = load_source_info(feed)
    assert info.source_id == "fed_press" and info.tier.value == 1
    assert info.health_state == "degraded" and info.duplicate_group == ""


def test_metrics_summarize_counts() -> None:
    assessments = [
        assess(make_doc("doc_ok")),
        assess(make_doc("doc_warn", raw_item_id="")),
        assess(make_doc("doc_old", published_age_hours=24 * 40)),
    ]
    m = summarize(assessments)
    assert m.total == 3
    assert m.accepted == 1 and m.accepted_with_warnings == 1 and m.limited == 1
    assert m.issue_counts["missing_raw_item"] == 1
    assert m.issue_counts["stale_for_policy"] == 1


def test_report_is_human_readable_and_explains_decisions() -> None:
    """Black Box判定禁止: なぜACCEPT/REJECTかがレポートに明示される。"""
    ok = assess(make_doc("doc_ok"))
    old = assess(make_doc("doc_old", published_age_hours=24 * 40))
    text = render_report([ok, old], labels={"doc_ok": "日銀声明", "doc_old": "旧記事"})
    assert "# Evidence QA Report" in text
    assert "ACCEPT（利用可）" in text and "LIMITED_USE（用途限定）" in text
    assert "stale_for_policy" in text  # 判定理由コード
    assert "日銀声明" in text and "旧記事" in text
    assert "freshness" in text  # 次元別内訳
    assert "GENERIC v1.0.0" in text  # policy trace
