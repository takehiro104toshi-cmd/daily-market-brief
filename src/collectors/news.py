"""公開RSSフィードからニュース見出しとリンクのみを収集する。

本文（有料記事含む）は取得しない。見出し・リンク・配信元・日時のみを扱う。
"""
from __future__ import annotations

import logging
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import datetime, timezone
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


def _now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


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
    """
    best: Dict[str, Headline] = {}
    order: List[str] = []
    for h in headlines:
        key = _normalize_title(h.title)
        if not key:
            continue
        if key not in best:
            best[key] = h
            order.append(key)
        elif h.reliability > best[key].reliability:
            best[key] = h
    return [best[key] for key in order]
