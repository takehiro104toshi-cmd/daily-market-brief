"""TDnet（適時開示情報閲覧サービス）の公開一覧ページから開示情報を取得する。

https://www.release.tdnet.co.jp/inbs/ 配下の日次一覧はログイン不要で
一般公開されているページのみを対象とする。
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date, timedelta
from typing import List, Optional

from bs4 import BeautifulSoup

from ..utils import SourceRegistry, safe_get

logger = logging.getLogger("market_brief")


@dataclass
class Disclosure:
    time: str
    code: str
    company: str
    title: str
    link: str


def _fetch_page(list_url_template: str, target_date: date) -> Optional[BeautifulSoup]:
    url = list_url_template.format(date=target_date.strftime("%Y%m%d"))
    resp = safe_get(url)
    if resp is None:
        return None
    resp.encoding = resp.apparent_encoding or "utf-8"
    return BeautifulSoup(resp.text, "html.parser")


def fetch_disclosures(
    config: dict,
    sources: SourceRegistry,
    start_date: Optional[date] = None,
) -> List[Disclosure]:
    tdnet_cfg = config.get("tdnet", {})
    template = tdnet_cfg.get(
        "list_url_template",
        "https://www.release.tdnet.co.jp/inbs/I_list_001_{date}.html",
    )
    max_items = tdnet_cfg.get("max_items", 20)
    lookback_days = tdnet_cfg.get("lookback_days", 3)

    target = start_date or date.today()
    soup: Optional[BeautifulSoup] = None
    used_date = target

    for _ in range(lookback_days):
        candidate = _fetch_page(template, target)
        rows = candidate.select("table tr") if candidate is not None else []
        if candidate is not None and len(rows) > 1:
            soup = candidate
            used_date = target
            break
        target -= timedelta(days=1)

    if soup is None:
        return []

    disclosures: List[Disclosure] = []
    for row in soup.select("table tr"):
        cells = row.find_all("td")
        if len(cells) < 4:
            continue
        time_txt = cells[0].get_text(strip=True)
        code_txt = cells[1].get_text(strip=True)
        company_txt = cells[2].get_text(strip=True)
        title_cell = cells[3]
        link_el = title_cell.find("a")
        title_txt = title_cell.get_text(strip=True)
        if not title_txt:
            continue
        link = link_el["href"] if link_el and link_el.has_attr("href") else ""
        if link and link.startswith("/"):
            link = "https://www.release.tdnet.co.jp" + link
        disclosures.append(
            Disclosure(time=time_txt, code=code_txt, company=company_txt, title=title_txt, link=link)
        )
        if len(disclosures) >= max_items:
            break

    sources.add(
        "TDnet 適時開示情報",
        template.format(date=used_date.strftime("%Y%m%d")),
        "適時開示",
    )
    return disclosures
