"""米労働統計局（BLS）・米エネルギー情報局（EIA）の公開統計RSSから
見出し・リンクのみを収集する（v2.9 Source Expansion Engine・③）。

- https://www.bls.gov/feed/bls_latest.rss : BLSの最新統計公表RSS
  （雇用統計・CPI等の発表を検知できる）
- https://www.eia.gov/rss/todayinenergy.xml : EIAの「Today in Energy」RSS
  （エネルギー・原油関連の公開分析記事）

いずれも公式統計機関が一般公開しているRSSで、ログイン不要。本文は取得せず、
見出し・リンクのみを扱う。

注意: この開発環境（サンドボックス・外部ネットワーク遮断）では実際の接続
確認ができていない。本番運用前に一度実行し、正しく取得できるか確認すること
（README「情報源に関する注意」を参照）。取得に失敗した場合は空リストを返し、
レポート生成全体には影響しない。
"""
from __future__ import annotations

from typing import List, Optional

from ..utils import SourceRegistry
from .news import Headline, fetch_headlines

US_GOV_STATS_SOURCES = [
    {"name": "BLS 最新統計", "url": "https://www.bls.gov/feed/bls_latest.rss"},
    {"name": "EIA Today in Energy", "url": "https://www.eia.gov/rss/todayinenergy.xml"},
]

RELIABILITY = {
    "BLS 最新統計": 0.97,
    "EIA Today in Energy": 0.95,
}


def fetch_us_gov_stats_headlines(
    sources: SourceRegistry, limit: int = 8, news_sources: Optional[list] = None
) -> List[Headline]:
    """news_sources を指定すると、config.yaml の us_gov_stats_sources 等で
    上書きできる（テストで到達不能なローカルアドレスに差し替える用途を想定）。
    未指定時は既定URL（US_GOV_STATS_SOURCES）を使う。"""
    return fetch_headlines(
        news_sources if news_sources is not None else US_GOV_STATS_SOURCES, sources, limit, reliability_map=RELIABILITY
    )
