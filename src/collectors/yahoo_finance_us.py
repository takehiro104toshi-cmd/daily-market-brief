"""Yahoo Finance（米国版）の公開ニュースRSSから見出し・リンクのみを収集する
（v2.9 Source Expansion Engine・③）。

https://finance.yahoo.com/news/rssindex はYahoo Finance USが公開している
ニュースRSSで、米国市場全般のニュースを検知できる。ログイン不要で一般公開
されている。本文は取得せず、見出し・リンクのみを扱う。

注意: この開発環境（サンドボックス・外部ネットワーク遮断）では実際の接続
確認ができていない。本番運用前に一度実行し、正しく取得できるか確認すること
（README「情報源に関する注意」を参照）。取得に失敗した場合は空リストを返し、
レポート生成全体には影響しない。
"""
from __future__ import annotations

from typing import List, Optional

from ..utils import SourceRegistry
from .news import Headline, fetch_headlines

YAHOO_FINANCE_US_SOURCES = [
    {"name": "Yahoo Finance US", "url": "https://finance.yahoo.com/news/rssindex"},
]

RELIABILITY = {"Yahoo Finance US": 0.6}


def fetch_yahoo_finance_us_headlines(
    sources: SourceRegistry, limit: int = 8, news_sources: Optional[list] = None
) -> List[Headline]:
    """news_sources を指定すると、config.yaml の yahoo_finance_us_sources 等で
    上書きできる（テストで到達不能なローカルアドレスに差し替える用途を想定）。
    未指定時は既定URL（YAHOO_FINANCE_US_SOURCES）を使う。"""
    return fetch_headlines(
        news_sources if news_sources is not None else YAHOO_FINANCE_US_SOURCES, sources, limit, reliability_map=RELIABILITY
    )
