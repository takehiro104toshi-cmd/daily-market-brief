"""経済カレンダー自動取得（v3.0・③）— 公開ソースから今週の重要イベントを取得する。

config.yaml の `economic_calendar.sources`（公開RSS/JSON/CSVのリスト）を読み、
取得できたイベントを macro_events と同じ形式（{date, label, time, region,
source, source_url, fetched_at}）へ正規化して返す。取得先が無い・取得失敗・
パース失敗時は空リストを返し、config.yaml の macro_events にフォールバックする
（レポート生成は止まらない）。

方針:
- 公式・公開ソースのみ（RSS/JSON/CSV）。有料本文・ログイン必須・規約不明な
  HTMLスクレイピングはしない。APIキーは必須化しない（公開URLのみ）。
- v2.8の `economic_calendar.url`（単一JSON）も後方互換で受け付ける。
- 直近7日以内かどうかの絞り込みは呼び出し側（weekly_events）が行う。
"""
from __future__ import annotations

import csv
import io
import json
import logging
import re
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from typing import List, Optional

from ..utils import SourceRegistry, safe_get

logger = logging.getLogger("market_brief")

_DATE_RE = re.compile(r"(\d{4}-\d{2}-\d{2})")
_TIME_RE = re.compile(r"\b(\d{1,2}:\d{2})\b")
# RFC 2822日付（RSSのpubDate等）から日付を拾う簡易マップ
_MONTHS = {m: i for i, m in enumerate(
    ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"], start=1)}


def _now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def _extract_date(text: str) -> str:
    """文字列から YYYY-MM-DD を取り出す。RFC2822形式（例: '05 Jul 2026'）も拾う。"""
    m = _DATE_RE.search(text or "")
    if m:
        return m.group(1)
    rm = re.search(r"(\d{1,2})\s+([A-Z][a-z]{2})\s+(\d{4})", text or "")
    if rm:
        day, mon, year = rm.group(1), rm.group(2), rm.group(3)
        if mon in _MONTHS:
            return f"{year}-{_MONTHS[mon]:02d}-{int(day):02d}"
    return ""


def _normalize(label: str, date_raw: str, time_raw: str, region: str, source: str, source_url: str, fetched_at: str) -> Optional[dict]:
    date = _extract_date(str(date_raw))
    if not label or not date:
        return None
    tm = ""
    tmatch = _TIME_RE.search(str(time_raw) or str(date_raw))
    if tmatch:
        tm = tmatch.group(1)
    return {
        "date": date, "label": str(label).strip(), "time": tm, "region": region or "",
        "source": source, "source_url": source_url, "fetched_at": fetched_at,
    }


def _parse_json_events(text: str, source: str, source_url: str, fetched_at: str) -> List[dict]:
    """[{date,label,time?,region?}, ...] 形式のJSONを寛容にパースする。"""
    try:
        data = json.loads(text)
    except ValueError:
        return []
    if isinstance(data, dict):
        data = data.get("events") or data.get("data") or []
    if not isinstance(data, list):
        return []
    events = []
    for item in data:
        if not isinstance(item, dict):
            continue
        label = item.get("label") or item.get("title") or item.get("event") or ""
        date = item.get("date") or item.get("datetime") or ""
        ev = _normalize(label, date, item.get("time", ""), item.get("region", ""), source, source_url, fetched_at)
        if ev:
            events.append(ev)
    return events


def _parse_rss_events(text: str, source: str, source_url: str, fetched_at: str) -> List[dict]:
    """RSS/Atomの<item>から title と pubDate を拾ってイベント化する。"""
    try:
        root = ET.fromstring(text)
    except ET.ParseError:
        return []
    events = []
    for item in root.findall(".//item"):
        title_el = item.find("title")
        pub_el = item.find("pubDate")
        if title_el is None:
            continue
        label = (title_el.text or "").strip()
        date_raw = (pub_el.text or "").strip() if pub_el is not None else ""
        ev = _normalize(label, date_raw, date_raw, "", source, source_url, fetched_at)
        if ev:
            events.append(ev)
    return events


def _parse_csv_events(text: str, source: str, source_url: str, fetched_at: str) -> List[dict]:
    """CSV（date,label[,time][,region] のヘッダ付き）をパースする。"""
    events = []
    try:
        reader = csv.DictReader(io.StringIO(text))
        for row in reader:
            lower = {(k or "").strip().lower(): (v or "") for k, v in row.items()}
            label = lower.get("label") or lower.get("event") or lower.get("title") or ""
            date = lower.get("date") or lower.get("datetime") or ""
            ev = _normalize(label, date, lower.get("time", ""), lower.get("region", ""), source, source_url, fetched_at)
            if ev:
                events.append(ev)
    except (csv.Error, ValueError):
        return []
    return events


def _fetch_one(src: dict, sources: SourceRegistry) -> List[dict]:
    """1ソース分を取得・パースする。失敗時は空リスト（例外を伝播させない）。"""
    url = src.get("url", "")
    name = src.get("name", "経済カレンダー")
    kind = (src.get("type", "") or "").lower()
    if not url:
        return []
    try:
        resp = safe_get(url)
        if resp is None:
            return []
        fetched_at = _now_iso()
        text = resp.text
        if kind == "json" or url.endswith(".json"):
            events = _parse_json_events(text, name, url, fetched_at)
        elif kind == "csv" or url.endswith(".csv"):
            events = _parse_csv_events(text, name, url, fetched_at)
        elif kind == "rss" or url.endswith((".xml", ".rss", ".rdf")):
            events = _parse_rss_events(text, name, url, fetched_at)
        else:
            # 種別未指定: JSON→RSS→CSVの順に試す
            events = (
                _parse_json_events(text, name, url, fetched_at)
                or _parse_rss_events(text, name, url, fetched_at)
                or _parse_csv_events(text, name, url, fetched_at)
            )
        if events:
            sources.add(name, url, "今週の重要イベント（自動取得）")
            logger.info("経済カレンダー自動取得: %s から%d件を取得しました。", name, len(events))
        return events
    except Exception as exc:  # noqa: BLE001
        logger.warning("経済カレンダーの自動取得に失敗しました（%s・config登録分のみ使用）: %s", name, exc)
        return []


def fetch_economic_calendar(config: dict, sources: SourceRegistry, now: Optional[datetime] = None) -> List[dict]:
    """公開経済カレンダー（sources設定時のみ）を取得し、macro_events形式で返す。

    config.yamlの `economic_calendar.sources`（[{name,url,type}, ...]）を順に取得。
    後方互換として `economic_calendar.url`（単一JSON）も受け付ける。
    取得先が無い・全て失敗した場合は [] を返す（macro_eventsにフォールバック）。
    """
    cal_cfg = config.get("economic_calendar", {}) or {}
    src_list = list(cal_cfg.get("sources", []) or [])
    legacy_url = cal_cfg.get("url", "")
    if legacy_url:
        src_list.append({"name": "経済カレンダー（自動取得）", "url": legacy_url, "type": ""})
    if not src_list:
        return []
    all_events: List[dict] = []
    for src in src_list:
        all_events.extend(_fetch_one(src, sources))
    return all_events


def merge_events(config_events: List[dict], auto_events: List[dict]) -> List[dict]:
    """config登録分と自動取得分を (date,label) で重複除去して結合する。

    config登録分（手入力）を優先して残し、自動取得分は未登録のもののみ追加する。
    """
    seen = set()
    merged: List[dict] = []
    for ev in list(config_events or []) + list(auto_events or []):
        key = (str(ev.get("date", "")), str(ev.get("label", "")))
        if key in seen or not key[1]:
            continue
        seen.add(key)
        merged.append(ev)
    return merged
