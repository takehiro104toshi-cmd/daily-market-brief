"""feed_normalizer（Phase 1-D）: 決定論・provenance・PARTIAL/REJECTED・revision・再処理。"""
from __future__ import annotations

import hashlib
from datetime import datetime, timezone

from src.intelligence.core import serialization
from src.intelligence.core.types import SourceTier
from src.intelligence.normalization.feed_normalizer import (
    NORMALIZER_NAME,
    NORMALIZER_VERSION,
    SourceMeta,
    detect_revision,
    normalize_feed_raw_item,
)
from src.intelligence.normalization.model import NormalizationStatus
from src.intelligence.sources.model import RawItem

serialization.register_domain_types()

NOW = datetime(2026, 8, 30, 12, 0, tzinfo=timezone.utc)
RETRIEVED = datetime(2026, 8, 30, 6, 0, tzinfo=timezone.utc)
META = SourceMeta(source_id="boj_whatsnew", tier=SourceTier.TIER1,
                  publisher="Bank of Japan", default_language="ja")

RSS_JA = """<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0"><channel><title>日銀 新着</title>
<item>
  <title>金融政策決定会合の結果&#65288;8月&#65289;</title>
  <link>https://www.example.jp/announcements/2026/k260828a?utm_source=rss</link>
  <guid>boj:2026:k260828a</guid>
  <pubDate>Fri, 28 Aug 2026 12:00:00 +0900</pubDate>
  <description>政策金利を維持　 詳細は本文</description>
</item>
<item>
  <title>統計データ更新</title>
  <link>https://www.example.jp/stats/2026/08/29/update</link>
  <guid>boj:2026:stats0829</guid>
</item>
</channel></rss>"""


def make_raw_item(body: bytes, source_id: str = "boj_whatsnew") -> RawItem:
    h = hashlib.sha256(body).hexdigest()
    return RawItem(
        raw_item_id=RawItem.make_id(source_id, "https://www.example.jp/rss", h),
        source_id=source_id,
        locator="https://www.example.jp/rss",
        retrieved_at=RETRIEVED,
        media_type="application/rss+xml",
        content_hash=h,
        storage_ref=f"blobs/{h[:2]}/{h}",
        endpoint_id="ep_test",
        fetch_attempt_id="fetch_test",
    )


def normalize(body: bytes = RSS_JA.encode(), **kw):
    return normalize_feed_raw_item(make_raw_item(body), body, META, now=NOW, **kw)


def test_documents_created_with_full_provenance_chain() -> None:
    result = normalize()
    assert len(result.documents) == 2
    doc = result.documents[0]
    # SourceDocument → RawItem → (FetchAttempt/Endpoint/Source) の逆引きチェーン
    raw = make_raw_item(RSS_JA.encode())
    assert doc.raw_item_id == raw.raw_item_id
    assert raw.fetch_attempt_id == "fetch_test"
    assert raw.endpoint_id == "ep_test"
    assert doc.source_id == raw.source_id == "boj_whatsnew"
    assert doc.source_tier is SourceTier.TIER1  # 取得時点スナップショット
    assert doc.retrieved_at == RETRIEVED
    assert doc.normalizer_name == NORMALIZER_NAME
    assert doc.normalizer_version == NORMALIZER_VERSION


def test_entry1_full_normalization() -> None:
    doc = normalize().documents[0]
    assert doc.title == "金融政策決定会合の結果（8月）"  # entity復号＋NFC
    # original URLは失わない。canonicalはtracking除去済みの別フィールド
    assert doc.locator == "https://www.example.jp/announcements/2026/k260828a?utm_source=rss"
    assert doc.canonical_locator == "https://example.jp/announcements/2026/k260828a"
    assert doc.published_at == datetime(2026, 8, 28, 3, 0, tzinfo=timezone.utc)  # JST→UTC
    assert doc.published_raw == "Fri, 28 Aug 2026 12:00:00 +0900"
    assert doc.date_quality == "source_provided_tz"
    assert not doc.published_inferred
    assert doc.language == "ja"
    assert doc.guid == "boj:2026:k260828a"
    assert doc.summary == "政策金利を維持 詳細は本文"


def test_entry2_partial_with_url_inferred_date() -> None:
    result = normalize()
    assert result.status is NormalizationStatus.PARTIAL  # date欠損issueがあるため
    doc = result.documents[1]
    assert doc.published_inferred and doc.published_inferred_from == "url_date"
    assert doc.published_at == datetime(2026, 8, 29, tzinfo=timezone.utc)
    assert doc.date_quality == "missing"  # source供給は無かったという事実を保持
    codes = {i.code for i in result.issues}
    assert "missing_date" in codes


def test_deterministic_same_input_same_output_including_ids() -> None:
    """決定論: 同一RawItem＋同一version → document群が完全一致（ID含む）。"""
    a = normalize()
    b = normalize()
    assert a.documents == b.documents
    assert [serialization.encode(d) for d in a.documents] == \
           [serialization.encode(d) for d in b.documents]
    # 処理時刻はeventのみが持つ（semantic equalityへ影響しない）
    assert a.event.event_id != b.event.event_id or a.event is b.event


def test_reprocessing_v2_creates_new_ids_preserves_v1() -> None:
    v1 = normalize()
    v2 = normalize(normalizer_version="2.0.0")
    ids_v1 = {d.source_document_id for d in v1.documents}
    ids_v2 = {d.source_document_id for d in v2.documents}
    assert ids_v1.isdisjoint(ids_v2)  # v2は新ID（旧outputを破壊的上書きしない）
    assert all(d.normalizer_version == "2.0.0" for d in v2.documents)


def test_rejected_when_no_documents() -> None:
    result = normalize(b"::not a feed::")
    assert result.status is NormalizationStatus.REJECTED
    assert result.documents == ()
    assert any(i.code == "unsupported_format" for i in result.issues)
    assert result.event is not None and result.event.status is NormalizationStatus.REJECTED


def test_missing_title_entry_rejected_with_issue() -> None:
    rss = RSS_JA.replace("<title>統計データ更新</title>", "")
    result = normalize(rss.encode())
    assert len(result.documents) == 1  # titleなしentryは文書化しない
    assert any(i.code == "missing_title" for i in result.issues)


def test_revision_detected_for_same_guid_changed_content() -> None:
    first = normalize().documents[0]
    updated_rss = RSS_JA.replace("政策金利を維持", "政策金利を引き上げ")
    result = normalize_feed_raw_item(
        make_raw_item(updated_rss.encode()), updated_rss.encode(), META,
        existing_documents=(first,), now=NOW)
    updated_doc = result.documents[0]
    assert updated_doc.revision_of == first.source_document_id  # 同一URL更新→新Doc＋revision
    assert updated_doc.source_document_id != first.source_document_id  # 旧Docは残る


def test_no_revision_for_identical_content_or_ambiguity() -> None:
    first = normalize().documents[0]
    # 同一内容の再取得（別RawItem）→ revisionではない
    result = normalize_feed_raw_item(
        make_raw_item(RSS_JA.encode() + b" "),  # bodyを微変化させ別RawItem化
        RSS_JA.encode(), META, existing_documents=(first,), now=NOW)
    assert result.documents[0].revision_of is None
    # 曖昧（同一guidの最新版が2件）→ relationを付けない
    ghost = serialization.decode({**serialization.encode(first),
                                  "source_document_id": "doc_ghost"})
    assert detect_revision((first, ghost), source_id=META.source_id,
                           guid=first.guid, fingerprint="different") is None


def test_same_body_different_source_gets_distinct_documents() -> None:
    body = RSS_JA.encode()
    meta_b = SourceMeta(source_id="mirror_feed", tier=SourceTier.TIER3)
    a = normalize_feed_raw_item(make_raw_item(body), body, META, now=NOW)
    b = normalize_feed_raw_item(
        make_raw_item(body, source_id="mirror_feed"), body, meta_b, now=NOW)
    assert a.documents[0].source_document_id != b.documents[0].source_document_id
    assert a.documents[0].content_fingerprint == b.documents[0].content_fingerprint


def test_serialization_roundtrip_of_documents_and_event() -> None:
    serialization.register_domain_types()
    result = normalize()
    for doc in result.documents:
        assert serialization.decode(serialization.encode(doc)) == doc
    decoded_event = serialization.decode(serialization.encode(result.event))
    assert decoded_event == result.event
    assert decoded_event.issues == result.event.issues
