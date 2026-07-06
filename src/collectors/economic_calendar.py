"""経済カレンダー自動取得（v2.8・⑤・安全スキャフォールド）。

将来的に「今週の重要イベント」をconfig.yamlの手入力に頼らず自動取得するための
土台。config.yaml の `economic_calendar.url`（公開RSS/JSON）が設定されている
場合のみ取得を試み、取得できたイベントを macro_events と同じ形式
（{date, label, time, region}）で返す。

信頼できる無償の公開ソースが未確定のため、既定ではURL未設定＝取得なし（[]）で
動作し、config.yaml の macro_events がそのまま使われる（フォールバック）。
取得失敗・パース失敗時も例外を伝播させず [] を返すため、既存動作を壊さない。
外部APIキーは要求しない（公開URLのみ）。
"""
from __future__ import annotations

import json
import logging
import re
from datetime import datetime
from typing import List, Optional

from ..utils import SourceRegistry, safe_get

logger = logging.getLogger("market_brief")

_DATE_RE = re.compile(r"(\d{4}-\d{2}-\d{2})")
_TIME_RE = re.compile(r"\b(\d{1,2}:\d{2})\b")


def _parse_json_events(text: str) -> List[dict]:
    """[{date,label,time?,region?}, ...] 形式のJSONを寛容にパースする。"""
    try:
        data = json.loads(text)
    except ValueError:
        return []
    if isinstance(data, dict):
        data = data.get("events", []) or data.get("data", [])
    if not isinstance(data, list):
        return []
    events: List[dict] = []
    for item in data:
        if not isinstance(item, dict):
            continue
        label = item.get("label") or item.get("title") or item.get("event") or ""
        date = item.get("date") or item.get("datetime") or ""
        m = _DATE_RE.search(str(date))
        if not label or not m:
            continue
        tm = item.get("time") or ""
        if not tm:
            tmatch = _TIME_RE.search(str(date))
            tm = tmatch.group(1) if tmatch else ""
        events.append(
            {"date": m.group(1), "label": str(label), "time": str(tm), "region": item.get("region", "")}
        )
    return events


def fetch_economic_calendar(config: dict, sources: SourceRegistry, now: Optional[datetime] = None) -> List[dict]:
    """公開経済カレンダー（URL設定時のみ）を取得し、macro_events形式で返す。

    URL未設定・取得失敗・パース失敗時は [] を返す（config.yamlのmacro_events
    にフォールバック）。取得できた場合は「参考情報」として出典を登録する。
    """
    cal_cfg = config.get("economic_calendar", {}) or {}
    url = cal_cfg.get("url", "")
    if not url:
        return []
    try:
        resp = safe_get(url)
        if resp is None:
            return []
        events = _parse_json_events(resp.text)
        if events:
            sources.add("経済カレンダー（自動取得）", url, "今週の重要イベント")
            logger.info("経済カレンダー自動取得: %d件を取得しました。", len(events))
        return events
    except Exception as exc:  # noqa: BLE001
        logger.warning("経済カレンダーの自動取得に失敗しました（config.yamlの登録分のみ使用）: %s", exc)
        return []


def merge_events(config_events: List[dict], auto_events: List[dict]) -> List[dict]:
    """config登録分と自動取得分を (date,label) で重複除去して結合する。"""
    seen = set()
    merged: List[dict] = []
    for ev in list(config_events or []) + list(auto_events or []):
        key = (str(ev.get("date", "")), str(ev.get("label", "")))
        if key in seen or not key[1]:
            continue
        seen.add(key)
        merged.append(ev)
    return merged
