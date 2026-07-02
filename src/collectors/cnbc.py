"""CNBCの公開見出しRSS（ベストエフォート）。

重要な注意（必ず読むこと）:
    CNBCの本文取得・転載は一切行わない。ここで参照するのは「公開されている
    見出し一覧RSS」のエンドポイントのみであり、この開発環境（サンドボックス・
    外部ネットワーク遮断）では実際の接続確認ができていない「ベストエフォート」
    実装である。本番運用前に、URLが現行の公開仕様と一致しているか、利用規約に
    照らして問題ないかを必ず確認すること（README「情報源に関する注意」を参照）。
    取得に失敗した場合は空リストを返し、レポート生成全体には影響しない。
"""
from __future__ import annotations

from typing import List, Optional

from ..utils import SourceRegistry
from .news import Headline, fetch_headlines

# ベストエフォート値。本番導入前に必ず実URLを確認すること（README参照）。
CNBC_SOURCES = [
    {"name": "CNBC Top News", "url": "https://www.cnbc.com/id/100003114/device/rss/rss.html"},
    {"name": "CNBC Markets", "url": "https://www.cnbc.com/id/20910258/device/rss/rss.html"},
]

RELIABILITY = {"CNBC Top News": 0.8, "CNBC Markets": 0.8}


def fetch_cnbc_headlines(
    sources: SourceRegistry, limit: int = 8, news_sources: Optional[list] = None
) -> List[Headline]:
    return fetch_headlines(news_sources if news_sources is not None else CNBC_SOURCES, sources, limit, reliability_map=RELIABILITY)
