"""feed_parser（Phase 1-C）: RSS2 / Atom / RDF / malformed / encoding / 形式検出。"""
from __future__ import annotations

import pytest

from src.intelligence.ingestion.feed_parser import (
    decode_body,
    detect_format,
    parse_feed,
    strip_html,
)
from src.intelligence.sources.model import FeedFormat

RSS2 = """<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0"><channel><title>Example News</title>
<item>
  <title>Fed &amp; markets</title>
  <link>https://www.example.org/articles/1?utm_source=rss&amp;id=9</link>
  <guid isPermaLink="false">tag:example.org,2026:1</guid>
  <pubDate>Fri, 28 Aug 2026 09:00:00 +0000</pubDate>
  <description><![CDATA[<b>Bold</b> summary here]]></description>
</item>
<item><title>No link item</title></item>
</channel></rss>"""

ATOM = """<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom"><title>Example Atom</title>
<entry>
  <title>8-K filing</title>
  <id>urn:example:entry-1</id>
  <link rel="alternate" href="https://www.example.org/filing/1"/>
  <link rel="self" href="https://www.example.org/self"/>
  <published>2026-08-28T10:30:00Z</published>
  <updated>2026-08-28T11:00:00Z</updated>
  <summary>Summary text</summary>
</entry></feed>"""

RDF = """<?xml version="1.0" encoding="UTF-8"?>
<rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#"
         xmlns="http://purl.org/rss/1.0/" xmlns:dc="http://purl.org/dc/elements/1.1/">
<channel rdf:about="https://www.example.jp/rss"><title>財務省新着</title></channel>
<item rdf:about="https://www.example.jp/news/2">
  <title>国債入札結果</title>
  <link>https://www.example.jp/news/2</link>
  <dc:date>2026-08-29T01:00:00+09:00</dc:date>
</item>
</rdf:RDF>"""


def test_rss2_extracts_all_fields_without_loss() -> None:
    result = parse_feed(RSS2.encode(), source_url="https://example.org/feed.xml")
    assert result.format is FeedFormat.RSS2
    assert result.feed_title == "Example News"
    assert len(result.entries) == 2 and result.skipped_items == 0
    e = result.entries[0]
    assert e.title == "Fed & markets"
    # original / canonical を両方保持（originalを失わない）
    assert e.link_original == "https://www.example.org/articles/1?utm_source=rss&id=9"
    assert e.link_canonical == "https://example.org/articles/1?id=9"
    assert e.guid == "tag:example.org,2026:1"
    assert e.published_raw == "Fri, 28 Aug 2026 09:00:00 +0000"  # 文字列のまま（Fact化しない）
    assert e.summary_excerpt == "Bold summary here"
    assert "<title>" in e.raw_xml  # 無損失の控え


def test_atom_extracts_entry() -> None:
    result = parse_feed(ATOM.encode())
    assert result.format is FeedFormat.ATOM
    assert result.feed_title == "Example Atom"
    e = result.entries[0]
    assert e.title == "8-K filing"
    assert e.link_original == "https://www.example.org/filing/1"  # rel=alternate優先
    assert e.guid == "urn:example:entry-1"
    assert e.published_raw == "2026-08-28T10:30:00Z"
    assert e.updated_raw == "2026-08-28T11:00:00Z"


def test_rdf_extracts_item_with_dc_date() -> None:
    result = parse_feed(RDF.encode())
    assert result.format is FeedFormat.RDF
    assert result.feed_title == "財務省新着"
    e = result.entries[0]
    assert e.title == "国債入札結果"
    assert e.published_raw == "2026-08-29T01:00:00+09:00"
    assert e.guid == "https://www.example.jp/news/2"


def test_malformed_xml_is_structured_failure_not_exception() -> None:
    result = parse_feed(b"<rss><channel><item><title>broken")
    assert result.entries == ()
    assert result.error.startswith("malformed xml") or "not a parseable feed" in result.error


def test_malformed_item_skipped_and_counted() -> None:
    rss = RSS2.replace("<item><title>No link item</title></item>",
                       "<item><description>only desc</description></item>")
    result = parse_feed(rss.encode())
    assert len(result.entries) == 1
    assert result.skipped_items == 1  # silent failureにしない


@pytest.mark.parametrize(
    "body, content_type, expected",
    [
        (RSS2.encode(), "application/rss+xml", FeedFormat.RSS2),
        (ATOM.encode(), "", FeedFormat.ATOM),
        (RDF.encode(), "", FeedFormat.RDF),
        (b'{"results": []}', "application/json", FeedFormat.JSON_API),
        (b'{"results": []}', "", FeedFormat.JSON_API),
        (b"<!DOCTYPE html><html><body>x</body></html>", "text/html", FeedFormat.HTML),
        (b"plain text, not a feed", "", FeedFormat.UNKNOWN),
        (b"", "", FeedFormat.UNKNOWN),
    ],
)
def test_detect_format(body: bytes, content_type: str, expected: FeedFormat) -> None:
    assert detect_format(body, content_type) is expected


def test_unknown_format_is_not_forced_into_rss() -> None:
    result = parse_feed(b"::totally not xml::")
    assert result.format is FeedFormat.UNKNOWN
    assert result.entries == () and result.error


def test_encoding_non_utf8_via_xml_declaration() -> None:
    xml = '<?xml version="1.0" encoding="shift_jis"?><rss version="2.0"><channel>' \
          "<title>日本語フィード</title><item><title>円相場</title>" \
          "<link>https://example.jp/1</link></item></channel></rss>"
    body = xml.encode("shift_jis")
    decoded = decode_body(body)
    assert decoded.encoding == "shift_jis" and not decoded.lossy
    result = parse_feed(body)
    assert result.feed_title == "日本語フィード"
    assert result.entries[0].title == "円相場"


def test_encoding_http_charset_beats_fallback() -> None:
    body = "título".encode("latin-1")
    decoded = decode_body(body, "text/xml; charset=ISO-8859-1")
    assert decoded.text == "título" and decoded.encoding == "iso-8859-1"


def test_encoding_bom_utf8() -> None:
    body = b"\xef\xbb\xbf" + RSS2.encode()
    assert parse_feed(body).format is FeedFormat.RSS2


def test_encoding_never_raises_and_flags_lossy() -> None:
    decoded = decode_body(b"\xff\xfe\x00broken\x9d")
    assert isinstance(decoded.text, str)  # 例外なし（raw bytesはblob側に無傷で残る）


def test_strip_html_handles_encoded_tags() -> None:
    assert strip_html("&lt;b&gt;bold&lt;/b&gt; &amp; more") == "bold & more"


def test_max_entries_cap() -> None:
    items = "".join(
        f"<item><title>t{i}</title><link>https://e.org/{i}</link></item>" for i in range(50)
    )
    rss = f'<rss version="2.0"><channel><title>big</title>{items}</channel></rss>'
    result = parse_feed(rss.encode(), max_entries=10)
    assert len(result.entries) == 10  # 初回の暴発防止（bulk化けしない）
