"""CoinDesk / CoinTelegraphの公開RSSから見出し・リンクのみを収集する
（v2.9 Source Expansion Engine・③）。

- https://www.coindesk.com/arc/outboundfeeds/rss/
- https://cointelegraph.com/rss

いずれも一般公開されているRSSで、ログイン不要。本文は取得せず、見出し・
リンクのみを扱う。暗号資産関連ニュースをテーマ分析・マーケットインパクトの
参考情報として利用する。

注意: この開発環境（サンドボックス・外部ネットワーク遮断）では実際の接続
確認ができていない。本番運用前に一度実行し、正しく取得できるか確認すること
（README「情報源に関する注意」を参照）。取得に失敗した場合は空リストを返し、
レポート生成全体には影響しない。
"""
from __future__ import annotations

from typing import List, Optional

from ..utils import SourceRegistry
from .news import Headline, fetch_headlines

CRYPTO_NEWS_SOURCES = [
    {"name": "CoinDesk", "url": "https://www.coindesk.com/arc/outboundfeeds/rss/"},
    {"name": "CoinTelegraph", "url": "https://cointelegraph.com/rss"},
]

RELIABILITY = {
    "CoinDesk": 0.6,
    "CoinTelegraph": 0.6,
}


def fetch_crypto_news_headlines(
    sources: SourceRegistry, limit: int = 8, news_sources: Optional[list] = None
) -> List[Headline]:
    """news_sources を指定すると、config.yaml の crypto_news_sources 等で
    上書きできる（テストで到達不能なローカルアドレスに差し替える用途を想定）。
    未指定時は既定URL（CRYPTO_NEWS_SOURCES）を使う。"""
    return fetch_headlines(
        news_sources if news_sources is not None else CRYPTO_NEWS_SOURCES, sources, limit, reliability_map=RELIABILITY
    )
