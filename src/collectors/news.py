"""公開RSSフィードからニュース見出しとリンクのみを収集する。

本文（有料記事含む）は取得しない。見出し・リンク・配信元・日時のみを扱う。
"""
from __future__ import annotations

import logging
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from typing import Dict, List, Optional

from ..utils import SourceRegistry, safe_get

logger = logging.getLogger("market_brief")

DEFAULT_RELIABILITY = 0.5


@dataclass
class Headline:
    title: str
    link: str
    source: str
    published: str = ""
    reliability: float = DEFAULT_RELIABILITY
    fetched_at: str = ""
    # v2.8（④）: 英語見出しの日本語訳（翻訳できた場合のみ設定。既定は空＝原文のみ）
    title_ja: str = ""
    # v2.9（④ Duplicate/Cross Source Intelligence）: 同一ニュースを配信していた
    # 他の情報源名（重複除去時にdedupe_headlinesが記録。既定は空＝重複なし）。
    duplicate_sources: List[str] = field(default_factory=list)
    source_count: int = 1

    def display_title(self) -> str:
        """表示用の見出し。日本語訳があればそれを、無ければ原文を返す。"""
        return self.title_ja or self.title

    @property
    def is_translated(self) -> bool:
        """翻訳済みかどうかを判定するフィールド（v2.9①）。title_jaの有無から導出する。"""
        return bool(self.title_ja)


def _now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def parse_published_datetime(published: str) -> Optional[datetime]:
    """Headline.published（RSSのpubDate、RFC 2822形式）をdatetimeへ変換する。

    解析できない・空の場合はNoneを返す（推測で埋めない）。ISO 8601形式
    （fetched_at等）もフォールバックとして受け付ける。v2.3の鮮度タイブレーク・
    Freshness Score算出で共通利用する。
    """
    if not published:
        return None
    try:
        dt = parsedate_to_datetime(published.strip())
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except (TypeError, ValueError):
        pass
    try:
        dt = datetime.fromisoformat(published.strip())
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except ValueError:
        return None


def _parse_rss(xml_text: str, source_name: str, limit: int, reliability: float) -> List[Headline]:
    headlines: List[Headline] = []
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError as exc:
        logger.warning("RSS解析失敗 (%s): %s", source_name, exc)
        return headlines

    fetched_at = _now_iso()
    for item in root.findall(".//item")[:limit]:
        title_el = item.find("title")
        link_el = item.find("link")
        pub_el = item.find("pubDate")
        if title_el is None or link_el is None:
            continue
        title = (title_el.text or "").strip()
        link = (link_el.text or "").strip()
        if not title or not link:
            continue
        headlines.append(
            Headline(
                title=title,
                link=link,
                source=source_name,
                published=(pub_el.text or "").strip() if pub_el is not None else "",
                reliability=reliability,
                fetched_at=fetched_at,
            )
        )
    return headlines


def fetch_headlines(
    news_sources: list,
    sources: SourceRegistry,
    limit_per_source: int = 8,
    reliability_map: Optional[Dict[str, float]] = None,
) -> List[Headline]:
    """RSS一覧(news_sources)から見出しを収集する。

    reliability_map: 情報源名(name)をキーとした信頼度スコア(0.0〜1.0)。
    未指定の情報源は DEFAULT_RELIABILITY を使う（取得不可時の判定材料にはしない）。
    """
    reliability_map = reliability_map or {}
    all_headlines: List[Headline] = []
    for src in news_sources:
        resp = safe_get(src["url"])
        if resp is None:
            continue
        reliability = reliability_map.get(src["name"], DEFAULT_RELIABILITY)
        headlines = _parse_rss(resp.text, src["name"], limit_per_source, reliability)
        for h in headlines:
            sources.add(src["name"], h.link, "ニュース見出し")
        all_headlines.extend(headlines)
    return all_headlines


def _normalize_title(title: str) -> str:
    """重複判定用に見出しを正規化する（空白・全角/半角記号の揺れを吸収）。"""
    normalized = title.strip().lower()
    normalized = re.sub(r"[\s　]+", "", normalized)
    normalized = re.sub(r"[【】\[\]()（）「」『』\-―ー、。,.!！?？:：]", "", normalized)
    return normalized


def dedupe_headlines(headlines: List[Headline]) -> List[Headline]:
    """同一ニュースの重複を除去する。

    複数の情報源が同じ見出し（正規化後に一致）を配信している場合、
    信頼度スコアが最も高いものを残す（同点の場合は先に出現したものを残す）。

    v2.9（④ Duplicate/Cross Source Intelligence）: 統合時に「他にどの情報源が
    同じニュースを配信していたか」（duplicate_sources）と配信元の総数
    （source_count）を残す。重複が無い場合は従来どおりsource_count=1・
    duplicate_sources=[]のまま（既存動作に影響なし）。分析側（news_ranking等）
    はこの情報を使って複数の高信頼情報源が報じたニュースの重要度を上げられる。
    """
    groups: Dict[str, List[Headline]] = {}
    order: List[str] = []
    for h in headlines:
        key = _normalize_title(h.title)
        if not key:
            continue
        if key not in groups:
            groups[key] = []
            order.append(key)
        groups[key].append(h)

    results = []
    for key in order:
        candidates = groups[key]
        # 信頼度の高い順（同点は先に出現した順）に並べ、先頭を採用元とする
        best = max(candidates, key=lambda h: h.reliability)
        other_sources = []
        for h in candidates:
            if h.source != best.source and h.source not in other_sources:
                other_sources.append(h.source)
        best.duplicate_sources = other_sources
        best.source_count = 1 + len(other_sources)
        results.append(best)
    return results
