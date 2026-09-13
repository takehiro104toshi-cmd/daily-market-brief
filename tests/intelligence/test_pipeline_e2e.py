"""E2Eパイプライン統合テスト（Phase 2-A）。

途中をmockしない: 注入はHttpTransportのみで、RawStore/Parser/Normalizer/QA/Gateは
全て実物が動く。NO FALSE EVIDENCE原則を機械的に固定する。
"""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from src.intelligence.evidence_qa.model import GateDecision
from src.intelligence.evidence_qa.policy import GENERIC_V1
from src.intelligence.ingestion.model import FetchResponse
from src.intelligence.pipeline.e2e import Pipeline
from src.intelligence.pipeline.trace import build_trace, render_trace

NOW = datetime(2026, 8, 30, 12, 0, tzinfo=timezone.utc)

CATALOG_FEED = {
    "id": "boj_whatsnew",
    "name": "Bank of Japan — What's New (English)",
    "tier": 1,
    "lang": "en",
    "role": "CORE",
    "investment_value": "MARKET_CRITICAL",
    "endpoint": {"url": "https://www.example.jp/en/rss/whatsnew.xml",
                 "declared_format": "rss2", "usage_status": "public_feed"},
    "current_health": {"state": "healthy", "checked_at": "2026-08-29"},
}

RSS_BODY = (
    '<?xml version="1.0"?><rss version="2.0"><channel><title>BOJ</title>'
    "<item><title>Statement on Monetary Policy</title>"
    "<link>https://www.example.jp/en/mopo/2026/k260829a</link>"
    "<guid>boj:k260829a</guid>"
    "<pubDate>Sat, 29 Aug 2026 12:00:00 +0900</pubDate></item>"
    "</channel></rss>"
).encode()


class OneShot:
    def __init__(self, response: FetchResponse):
        self._response = response

    def send(self, request, *, timeout: float = 20.0) -> FetchResponse:
        return self._response


def ok_response(body: bytes = RSS_BODY, **kw) -> FetchResponse:
    d = dict(status_code=200, final_url=CATALOG_FEED["endpoint"]["url"],
             content_type="application/rss+xml", body=body, retrieved_at=NOW)
    d.update(kw)
    return FetchResponse(**d)


def run(tmp_path: Path, response: FetchResponse):
    pipeline = Pipeline(tmp_path, OneShot(response), GENERIC_V1,
                        clock=lambda: NOW, sleeper=lambda _s: None)
    return pipeline, pipeline.run_source(CATALOG_FEED)


def test_success_path_reaches_gate_with_accept(tmp_path: Path) -> None:
    """実パイプライン一本通し: Fetch→Raw→Parse→Normalize→QA→ACCEPT。"""
    pipeline, result = run(tmp_path, ok_response())
    assert result.stage_reached == "evidence_qa"
    assert result.fetch_outcome.raw_item is not None
    assert result.normalization.status.value == "normalized"
    assert len(result.assessments) == 1
    assert result.assessments[0].decision is GateDecision.ACCEPT
    # 各ストアへ実際に永続化されている
    assert len(list(pipeline.raw.iter_raw_items())) == 1
    assert len(list(pipeline.normalized.iter_documents())) == 1
    assert len(list(pipeline.qa.iter_assessments())) == 1


def test_provenance_trace_end_to_end(tmp_path: Path) -> None:
    """最終Assessmentから Source まで逆引きできる（human-readable trace）。"""
    pipeline, result = run(tmp_path, ok_response())
    trace = build_trace(result.assessments[0], normalized_store=pipeline.normalized,
                        raw_repository=pipeline.raw,
                        catalog_by_id={"boj_whatsnew": CATALOG_FEED})
    assert trace.complete
    assert trace.document.raw_item_id == trace.raw_item.raw_item_id
    assert trace.raw_item.fetch_attempt_id == trace.fetch_attempt.attempt_id
    text = render_trace(trace)
    for expected in ("assessment", "document", "raw item", "fetch attempt",
                     "endpoint", "source", "Statement on Monetary Policy", "boj_whatsnew"):
        assert expected in text


def test_failure_path_404_leaves_attempt_only(tmp_path: Path) -> None:
    """404: FetchAttemptは残る / RawItem・Document・Assessmentは作られない。"""
    pipeline, result = run(tmp_path, FetchResponse(status_code=404, retrieved_at=NOW))
    assert result.stage_reached == "fetch_only"
    assert len(list(pipeline.raw.iter_attempts())) == 1
    assert list(pipeline.raw.iter_raw_items()) == []
    assert list(pipeline.normalized.iter_documents()) == []
    assert list(pipeline.qa.iter_assessments()) == []


def test_failure_path_timeout(tmp_path: Path) -> None:
    pipeline, result = run(tmp_path, FetchResponse(
        status_code=0, error_kind="timeout", error_detail="timed out", retrieved_at=NOW))
    assert result.stage_reached == "fetch_only"
    attempt = list(pipeline.raw.iter_attempts())[0]
    assert attempt.error_kind == "timeout"
    assert list(pipeline.qa.iter_assessments()) == []


def test_malformed_body_yields_no_assessment(tmp_path: Path) -> None:
    """parser失敗: Rawは残る（再処理可能）がEvidence層には何も入らない。"""
    pipeline, result = run(tmp_path, ok_response(body=b"::not a feed at all::"))
    assert result.stage_reached == "normalization_rejected"
    assert len(list(pipeline.raw.iter_raw_items())) == 1  # rawは保存（再処理可能性）
    assert list(pipeline.normalized.iter_documents()) == []
    assert list(pipeline.qa.iter_assessments()) == []
    assert len(list(pipeline.normalized.iter_events())) == 1  # REJECTEDイベントは記録


def test_no_false_evidence_invariant(tmp_path: Path) -> None:
    """NO FALSE EVIDENCE: fetch失敗/parser失敗/正規化REJECTからACCEPTが生まれない。"""
    failure_responses = (
        FetchResponse(status_code=404, retrieved_at=NOW),
        FetchResponse(status_code=403, retrieved_at=NOW),
        FetchResponse(status_code=0, error_kind="timeout", retrieved_at=NOW),
        ok_response(body=b"<html><body>error page</body></html>",
                    content_type="text/html"),
        ok_response(body=b"::garbage::"),
    )
    for i, response in enumerate(failure_responses):
        pipeline, result = run(tmp_path / str(i), response)
        accepted = [a for a in pipeline.qa.iter_assessments()
                    if a.decision in (GateDecision.ACCEPT,
                                      GateDecision.ACCEPT_WITH_WARNINGS)]
        assert accepted == [], f"false evidence from failure case {i}"
        assert result.assessments == ()
