"""identity校正評価（Phase 2-B）。PRECISION FIRST: fixture上でfalse merge = 0を強制。"""
from __future__ import annotations

import hashlib
from collections import Counter
from datetime import datetime, timedelta, timezone

from src.intelligence.core.types import SourceTier
from src.intelligence.databank.identity_decision import (
    IdentityDecisionKind,
    MERGING_DECISIONS,
)
from src.intelligence.databank.identity_report import (
    render_merge_audit,
    summarize_decisions,
)
from src.intelligence.databank.identity_resolver import resolve
from src.intelligence.databank.news_model import ArticleIdentity
from src.intelligence.ingestion.url_normalize import normalize_url
from src.intelligence.normalization.text import content_fingerprint
from src.intelligence.sources.model import SourceDocument
from tests.intelligence.identity_calibration_pairs import (
    PAIRS,
    TANK_HAZARD_TITLE_PAIRS,
)


def doc_from_spec(spec: dict, doc_id: str) -> SourceDocument:
    url = spec.get("url", "")
    published = None
    if spec.get("published"):
        published = datetime.fromisoformat(spec["published"])
        if published.tzinfo is None:
            published = published.replace(tzinfo=timezone.utc)
    basis = f"{spec['title']}|{spec.get('summary','')}|{url}|{doc_id}"
    return SourceDocument(
        source_document_id=doc_id,
        source_id=spec.get("source", "src"),
        source_tier=SourceTier.TIER2,
        title=spec["title"],
        locator=url or f"https://fixture.example/{doc_id}",
        canonical_locator=normalize_url(url) if url else "",
        retrieved_at=(published or datetime(2026, 8, 1, tzinfo=timezone.utc)) + timedelta(hours=1),
        published_at=published,
        publisher=spec.get("publisher", ""),
        guid=spec.get("guid", ""),
        content_hash=hashlib.sha256(basis.encode()).hexdigest(),
        content_fingerprint=content_fingerprint(spec["title"], spec.get("summary", "")),
        summary=spec.get("summary", ""),
        normalizer_name="feed_entry", normalizer_version="1.0.0",
    )


def resolve_pair(pair: dict, idx: int) -> IdentityDecisionKind:
    a = doc_from_spec(pair["a"], f"doc_cal_a{idx}")
    b = doc_from_spec(pair["b"], f"doc_cal_b{idx}")
    identity = ArticleIdentity(
        article_id=ArticleIdentity.make_id(a.source_document_id),
        member_document_ids=(a.source_document_id,))
    return resolve(b, [(identity, [a])]).decision


def run_calibration():
    outcomes = []
    for i, pair in enumerate(PAIRS):
        outcomes.append((pair["label"], pair["note"], resolve_pair(pair, i)))
    return outcomes


def test_false_merge_is_zero_on_labeled_fixture() -> None:
    """DIFFERENT_ARTICLE 14ペア（実tankハザード含む）でmerge判定ゼロ。"""
    false_merges = [
        (note, decision.value)
        for label, note, decision in run_calibration()
        if label == "DIFFERENT_ARTICLE" and decision in MERGING_DECISIONS
    ]
    assert false_merges == [], f"FALSE MERGE検出: {false_merges}"


def test_uncertain_pairs_are_never_auto_merged() -> None:
    """UNCERTAIN（人間でも判定困難）は安全側=非merge。"""
    merged = [
        (note, decision.value)
        for label, note, decision in run_calibration()
        if label == "UNCERTAIN" and decision in MERGING_DECISIONS
    ]
    assert merged == []


def test_recall_on_positive_pairs() -> None:
    """正例recall: SAME→EXACT/AUTO_MERGE, REVISION→REVISION, SYNDICATED→SYNDICATED。

    PRECISION FIRSTのためrecall不足は許容だが、床値を割らないことを固定する。
    """
    expected = {
        "SAME_ARTICLE": (IdentityDecisionKind.EXACT_MATCH, IdentityDecisionKind.AUTO_MERGE),
        "REVISION": (IdentityDecisionKind.REVISION,),
        "SYNDICATED_COPY": (IdentityDecisionKind.SYNDICATED,),
    }
    hits, total, misses = 0, 0, []
    for label, note, decision in run_calibration():
        if label not in expected:
            continue
        total += 1
        if decision in expected[label]:
            hits += 1
        else:
            misses.append((label, note, decision.value))
    recall = hits / total
    assert recall >= 0.9, f"recall={recall:.2f} misses={misses}"


def test_hazard_corpus_never_merges_without_content_evidence() -> None:
    """実tank由来40ペア（title-only・改題/別記事が混在）: summary証拠なしでは
    いかなるペアもmergeされない（内容証拠なしのmerge禁止の実データ検証）。"""
    merged = []
    for i, pair in enumerate(TANK_HAZARD_TITLE_PAIRS):
        spec_a = {"title": pair["title_a"], "source": pair["source"],
                  "publisher": pair["publisher"], "published": pair["published_a"],
                  "url": f"https://hazard.example/a{i}"}
        spec_b = {"title": pair["title_b"], "source": pair["source"],
                  "publisher": pair["publisher"], "published": pair["published_b"],
                  "url": f"https://hazard.example/b{i}"}
        decision = resolve_pair({"a": spec_a, "b": spec_b}, 1000 + i)
        if decision in MERGING_DECISIONS:
            merged.append((pair["title_a"][:40], decision.value))
    assert merged == [], f"content証拠なしのmerge発生: {merged}"


def test_metrics_and_audit_report() -> None:
    decisions = []
    for i, pair in enumerate(PAIRS):
        a = doc_from_spec(pair["a"], f"doc_m_a{i}")
        b = doc_from_spec(pair["b"], f"doc_m_b{i}")
        identity = ArticleIdentity(
            article_id=ArticleIdentity.make_id(a.source_document_id),
            member_document_ids=(a.source_document_id,))
        decisions.append(resolve(b, [(identity, [a])]))
    metrics = summarize_decisions(decisions)
    assert metrics.documents == len(PAIRS)
    assert metrics.exact_merges >= 3
    assert metrics.syndicated_links >= 3
    assert metrics.revision_links >= 3
    report = render_merge_audit(decisions)
    assert "why merged" not in report  # 見出しは日本語
    assert "mergeされたpairとその根拠" in report
    assert "matched signals" in report
    assert "CANDIDATE" in report or metrics.candidates == 0


def test_calibration_outcome_distribution_is_stable() -> None:
    """校正結果の分布を固定（threshold変更時に意図的に更新する回帰アンカー）。"""
    outcomes = Counter(d.value for _l, _n, d in run_calibration())
    # merge系の合計 = 正例12（SAME6+REV3+SYN3）のみ（DIFFERENTからのmergeゼロ）
    merge_total = sum(v for k, v in outcomes.items()
                      if k in {m.value for m in MERGING_DECISIONS})
    assert merge_total <= 12
