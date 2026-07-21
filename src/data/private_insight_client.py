"""Rashinban Private Insight Vault — 派生情報の取得クライアント（daily-market-brief側）。

Cloudflare Worker（非公開KV）からallowlist済みの派生情報（Published Private
Insight Summary）だけを取得する薄いクライアント。記事本文はWorker側の機械専用API
にしか存在せず、このクライアントが叩く /derived には構造的に含まれない。

安全設計:
  - api_url（config）または INSIGHT_API_TOKEN（環境変数）が未設定なら、
    ネットワークへ一切アクセスせず disabled を返す（既存動作に影響なし）
  - 取得失敗・タイムアウトでもレポート生成は止めない（unavailableを返すだけ）
  - トークンはGitHub Actions SecretsからのみJob環境変数へ渡す。HTMLへは出さない
"""
from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
from typing import Callable, Optional, Tuple

_JST = timezone(timedelta(hours=9))


def _default_transport(url: str, token: str, timeout: int) -> dict:
    import requests

    resp = requests.get(url, headers={"Authorization": f"Bearer {token}"}, timeout=timeout)
    resp.raise_for_status()
    return resp.json()


def fetch_derived_summaries(
    config: dict,
    transport: Optional[Callable] = None,
    now: Optional[datetime] = None,
) -> Tuple[list, dict]:
    """派生情報一覧を取得する。戻り値: (summaries, status)。

    status.state: disabled / ok / unavailable
    """
    cfg = (config or {}).get("private_insight_intake", {}) or {}
    api_url = (cfg.get("api_url") or "").rstrip("/")
    token = os.environ.get("INSIGHT_API_TOKEN", "")
    now = now or datetime.now(timezone.utc)

    if not cfg.get("enabled", True) or not api_url or not token:
        return [], {"state": "disabled", "reason": "not_configured", "fetched_at": now.isoformat()}

    timeout = int(cfg.get("timeout_seconds", 20))
    call = transport or _default_transport
    try:
        data = call(f"{api_url}/derived", token, timeout)
        items = data.get("items", []) if isinstance(data, dict) else []
        return items, {"state": "ok", "count": len(items), "fetched_at": now.isoformat()}
    except Exception as exc:  # noqa: BLE001 取得失敗でレポートを止めない
        return [], {"state": "unavailable", "reason": type(exc).__name__, "fetched_at": now.isoformat()}


def count_recent(summaries: list, now: Optional[datetime] = None, days: int = 7) -> Tuple[int, int]:
    """(今日保存件数, 直近days日保存件数) をsubmitted_atから数える。"""
    now = (now or datetime.now(timezone.utc)).astimezone(_JST)
    today = new_week = 0
    cutoff = now - timedelta(days=days)
    for s in summaries:
        ts = (s.get("submitted_at") or "")[:19]
        try:
            dt = datetime.fromisoformat(ts)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=_JST)
        except ValueError:
            continue
        if dt.date() == now.date():
            today += 1
        if dt >= cutoff:
            new_week += 1
    return today, new_week
