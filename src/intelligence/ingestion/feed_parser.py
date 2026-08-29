"""フィードパーサー（Phase 1-C。tank feed_parser.py の純ロジック移植・vNext契約適合）。

対応: RSS 2.0 / Atom / RDF(RSS 1.0)。標準ライブラリ xml.etree のみ（依存を増やさない。
オフラインで決定的にテスト可能——tankの設計判断を継承）。

vNextでの役割は **RawItemの中身から「正規化前のエントリ」を無損失で取り出す** ところまで。
- published等の日時は**文字列のまま**保持する（分類は date_quality、Fact化はP1-D）。
- 未対応・判別不能フォーマットは無理にRSS扱いせず、FeedFormat.UNKNOWNのまま返す。
- malformed item はそのitemだけスキップ、malformed feed は error付き結果（例外を投げない）。
"""
from __future__ import annotations

import html
import re
from dataclasses import dataclass, field
from typing import Optional, Tuple
from urllib.parse import urljoin
from xml.etree import ElementTree as ET

from ..sources.model import FeedFormat
from .transport import charset_from_content_type
from .url_normalize import normalize_url

_TAG_RE = re.compile(r"<[^>]+>")
_WS_RE = re.compile(r"\s+")
_MAX_EXCERPT = 400  # 権利上安全な短い抜粋のみ（本文全文はblobにのみ存在）
_DEFAULT_MAX_ENTRIES = 200  # 1フィードの安全上限（初回の暴発防止。tank §8）

_RSS1_NS = "http://purl.org/rss/1.0/"


# ---------------------------------------------------------------- decode


@dataclass(frozen=True, kw_only=True)
class DecodedBody:
    text: str
    encoding: str  # 実際に使ったencoding
    lossy: bool = False  # errors="replace"へフォールバックした


def decode_body(body: bytes, content_type: str = "") -> DecodedBody:
    """bytes→str。優先順: BOM → HTTP charset → XML宣言 → utf-8等 → utf-8/replace。

    UTF-8固定を禁止（P1-C指示）。最終フォールバックでも例外を投げない
    （raw bytesはblobに保存済みで失われない）。
    """
    for bom, enc in ((b"\xef\xbb\xbf", "utf-8-sig"), (b"\xff\xfe", "utf-16-le"), (b"\xfe\xff", "utf-16-be")):
        if body.startswith(bom):
            try:
                return DecodedBody(text=body.decode(enc), encoding=enc)
            except UnicodeDecodeError:
                break
    http_charset = charset_from_content_type(content_type)
    if http_charset:
        try:
            return DecodedBody(text=body.decode(http_charset), encoding=http_charset)
        except (LookupError, UnicodeDecodeError):
            pass
    m = re.match(rb"<\?xml[^>]*encoding=[\"']([\w\-]+)[\"']", body[:200])
    if m:
        enc = m.group(1).decode("ascii", "ignore").lower()
        try:
            return DecodedBody(text=body.decode(enc), encoding=enc)
        except (LookupError, UnicodeDecodeError):
            pass
    for enc in ("utf-8", "cp1252", "latin-1"):
        try:
            return DecodedBody(text=body.decode(enc), encoding=enc)
        except UnicodeDecodeError:
            continue
    return DecodedBody(text=body.decode("utf-8", errors="replace"), encoding="utf-8", lossy=True)


# ---------------------------------------------------------------- format検出


def detect_format(body: bytes, content_type: str = "") -> FeedFormat:
    """content-type / ルート要素 / signature からフィード形式を検出する。

    判別不能はUNKNOWN（無理にRSS扱いしない——P1-C指示）。
    """
    ct = (content_type or "").lower()
    if "json" in ct.split(";")[0]:
        return FeedFormat.JSON_API
    text = decode_body(body, content_type).text.lstrip()
    if not text:
        return FeedFormat.UNKNOWN
    if text.startswith(("{", "[")):
        return FeedFormat.JSON_API
    try:
        root = ET.fromstring(text)
    except ET.ParseError:
        head = text[:2048].lower()
        if "<!doctype html" in head or "<html" in head:
            return FeedFormat.HTML
        return FeedFormat.UNKNOWN
    name = _localname(root.tag)
    if name == "rss":
        return FeedFormat.RSS2
    if name.lower() == "rdf":
        return FeedFormat.RDF
    if name == "feed":
        return FeedFormat.ATOM
    if name == "html":
        return FeedFormat.HTML
    return FeedFormat.UNKNOWN


# ---------------------------------------------------------------- entry抽出


@dataclass(frozen=True, kw_only=True)
class FeedEntry:
    """正規化前のエントリ（transient）。日時は文字列のまま（date_qualityで分類）。"""

    title: str = ""
    link_original: str = ""  # フィードが供給した元URL（絶対URL化のみ。失わない）
    link_canonical: str = ""  # normalize_url()結果（dedup用。originalの代替ではない）
    guid: str = ""
    published_raw: str = ""  # 供給された公開日時文字列そのまま
    updated_raw: str = ""
    summary_excerpt: str = ""  # 権利上安全な短い抜粋のみ
    raw_xml: str = ""  # エントリ要素のXML表現（無損失の控え）


@dataclass(frozen=True, kw_only=True)
class FeedParseResult:
    format: FeedFormat = FeedFormat.UNKNOWN
    feed_title: str = ""
    entries: Tuple[FeedEntry, ...] = ()
    error: str = ""  # malformed feed等。例外は投げない（structured failure）
    skipped_items: int = 0  # malformed itemのスキップ数（silent failureにしない）


def _localname(tag: str) -> str:
    if tag and tag[0] == "{":
        return tag.rsplit("}", 1)[1]
    return tag or ""


def strip_html(text: Optional[str]) -> str:
    """HTMLタグ除去＋エンティティ復号（tank §2.7実績ロジック）。"""
    if not text:
        return ""
    decoded = html.unescape(text)
    no_tags = _TAG_RE.sub(" ", decoded)
    no_tags = html.unescape(no_tags)
    return _WS_RE.sub(" ", no_tags).strip()


def _first_text(elem, names) -> str:
    for child in list(elem):
        if _localname(child.tag) in names:
            if child.text and child.text.strip():
                return child.text
    return ""


def _entry_from_item(item, source_url: str) -> Optional[FeedEntry]:
    """RSS2 <item> / RDF <item> 共通の抽出（tank _rss_item移植）。"""
    try:
        title = strip_html(_first_text(item, {"title"}))
        link = _first_text(item, {"link"}).strip()
        guid = ""
        for child in list(item):
            if _localname(child.tag) == "guid":
                guid = (child.text or "").strip()
                if not link and guid.startswith("http"):
                    link = guid
        if not guid:
            about = item.get("{http://www.w3.org/1999/02/22-rdf-syntax-ns#}about", "")
            guid = about or link
        link = urljoin(source_url, link) if link else ""
        if not title and not link:
            return None  # malformed item（タイトルもURLも無い）
        return FeedEntry(
            title=title,
            link_original=link,
            link_canonical=normalize_url(link),
            guid=guid,
            published_raw=_first_text(item, {"pubDate", "date", "published"}).strip(),
            updated_raw=_first_text(item, {"updated", "modified"}).strip(),
            summary_excerpt=strip_html(_first_text(item, {"description", "summary", "encoded"}))[:_MAX_EXCERPT],
            raw_xml=ET.tostring(item, encoding="unicode"),
        )
    except Exception:  # noqa: BLE001 1件の破損で全体を止めない
        return None


def _entry_from_atom(entry, source_url: str) -> Optional[FeedEntry]:
    try:
        title = strip_html(_first_text(entry, {"title"}))
        link = ""
        for child in list(entry):
            if _localname(child.tag) == "link":
                rel = child.get("rel", "alternate")
                href = child.get("href", "")
                if href and (rel == "alternate" or not link):
                    link = href
                    if rel == "alternate":
                        break
        link = urljoin(source_url, link) if link else ""
        if not title and not link:
            return None
        return FeedEntry(
            title=title,
            link_original=link,
            link_canonical=normalize_url(link),
            guid=_first_text(entry, {"id"}).strip() or link,
            published_raw=_first_text(entry, {"published", "issued"}).strip(),
            updated_raw=_first_text(entry, {"updated", "modified"}).strip(),
            summary_excerpt=strip_html(_first_text(entry, {"summary", "content", "subtitle"}))[:_MAX_EXCERPT],
            raw_xml=ET.tostring(entry, encoding="unicode"),
        )
    except Exception:  # noqa: BLE001
        return None


def parse_feed(
    body: bytes,
    *,
    content_type: str = "",
    source_url: str = "",
    max_entries: int = _DEFAULT_MAX_ENTRIES,
) -> FeedParseResult:
    """RSS2 / Atom / RDF からエントリを取り出す。JSON/HTML/不明は entries なしで返す。"""
    fmt = detect_format(body, content_type)
    if fmt in (FeedFormat.JSON_API, FeedFormat.HTML, FeedFormat.UNKNOWN):
        error = "" if fmt is FeedFormat.JSON_API else f"not a parseable feed (detected={fmt.value})"
        return FeedParseResult(format=fmt, error=error)

    text = decode_body(body, content_type).text
    try:
        root = ET.fromstring(text)
    except ET.ParseError as exc:
        # 宣言除去の再試行（tank実績: 末尾破損への耐性）
        try:
            root = ET.fromstring(re.sub(r"^\s*<\?xml[^>]*\?>", "", text).strip())
        except ET.ParseError:
            return FeedParseResult(format=fmt, error=f"malformed xml: {str(exc)[:100]}")

    entries: list = []
    skipped = 0
    feed_title = ""

    if fmt is FeedFormat.RSS2:
        container = root
        for child in list(root):
            if _localname(child.tag) == "channel":
                container = child
                break
        feed_title = strip_html(_first_text(container, {"title"}))
        for elem in container.iter():
            if _localname(elem.tag) == "item":
                rec = _entry_from_item(elem, source_url)
                if rec:
                    entries.append(rec)
                else:
                    skipped += 1
                if len(entries) >= max_entries:
                    break
    else:  # ATOM / RDF
        feed_title = strip_html(_first_text(root, {"title"}))
        if fmt is FeedFormat.RDF:
            # RDFではchannel直下のtitleが正（rootの_first_textでは拾えない場合がある）
            for child in list(root):
                if _localname(child.tag) == "channel":
                    feed_title = strip_html(_first_text(child, {"title"})) or feed_title
                    break
        for elem in root.iter():
            name = _localname(elem.tag)
            if name == "entry":
                rec = _entry_from_atom(elem, source_url)
            elif name == "item":
                rec = _entry_from_item(elem, source_url)
            else:
                continue
            if rec:
                entries.append(rec)
            else:
                skipped += 1
            if len(entries) >= max_entries:
                break

    return FeedParseResult(
        format=fmt, feed_title=feed_title, entries=tuple(entries), skipped_items=skipped
    )
