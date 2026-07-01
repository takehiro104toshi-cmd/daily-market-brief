"""公開RSSフィードからニュース見出しとリンクのみを収集する。

本文（有料記事含む）は取得しない。見出し・リンク・配信元・日時のみを扱う。
"""
from __future__ import annotations

import logging
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from typing import List

from ..utils import SourceRegistry, safe_get

logger = logging.getLogger("market_brief")


@dataclass
class Headline:
    title: str
    link: str
    source: str
    published: str = ""


def _parse_rss(xml_text: str, source_name: str, limit: int) -> List[Headline]:
    headlines: List[Headline] = []
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError as exc:
        logger.warning("RSS解析失敗 (%s): %s", source_name, exc)
        return headlines

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
            )
        )
    return headlines


def fetch_headlines(
    news_sources: list,
    sources: SourceRegistry,
    limit_per_source: int = 8,
) -> List[Headline]:
    all_headlines: List[Headline] = []
    for src in news_sources:
        resp = safe_get(src["url"])
        if resp is None:
            continue
        headlines = _parse_rss(resp.text, src["name"], limit_per_source)
        for h in headlines:
            sources.add(src["name"], h.link, "ニュース見出し")
        all_headlines.extend(headlines)
    return all_headlines
