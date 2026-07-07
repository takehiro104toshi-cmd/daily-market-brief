"""米証券取引委員会（SEC）の公開プレスリリースRSSから見出し・リンクのみを
収集する（v2.9 Source Expansion Engine・③）。

https://www.sec.gov/news/pressreleases.rss はSECが公開しているプレスリリース
RSSで、規制・エンフォースメント・制度変更等の公表を検知できる。ログイン不要で
一般公開されている。本文は取得せず、見出し・リンクのみを扱う。

注意: この開発環境（サンドボックス・外部ネットワーク遮断）では実際の接続
確認ができていない。本番運用前に一度実行し、正しく取得できるか確認すること
（README「情報源に関する注意」を参照）。取得に失敗した場合は空リストを返し、
レポート生成全体には影響しない。
"""
from __future__ import annotations

from typing import List, Optional

from ..utils import SourceRegistry
from .news import Headline, fetch_headlines

SEC_SOURCES = [
    {"name": "SEC Press Releases", "url": "https://www.sec.gov/news/pressreleases.rss"},
]

RELIABILITY = {"SEC Press Releases": 0.97}


def fetch_sec_headlines(
    sources: SourceRegistry, limit: int = 8, news_sources: Optional[list] = None
) -> List[Headline]:
    """news_sources を指定すると、config.yaml の sec_sources 等で上書きできる
    （テストで到達不能なローカルアドレスに差し替える用途を想定）。未指定時は
    既定URL（SEC_SOURCES）を使う。"""
    return fetch_headlines(news_sources if news_sources is not None else SEC_SOURCES, sources, limit, reliability_map=RELIABILITY)
