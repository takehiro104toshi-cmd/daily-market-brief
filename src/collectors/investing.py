"""Investing.comの公開見出しRSS（ベストエフォート）。

重要な注意（必ず読むこと）:
    Investing.comの本文取得・転載は一切行わない。ここで参照するのは「公開
    されている見出し一覧RSS」のエンドポイントのみであり、この開発環境
    （サンドボックス・外部ネットワーク遮断）では実際の接続確認ができていない
    「ベストエフォート」実装である。Investing.comはRSS提供方針やアクセス制限
    （Bot対策）を変更することがあるため、本番運用前に、URLが現行の公開仕様と
    一致しているか、利用規約に照らして問題ないかを必ず確認すること
    （README「情報源に関する注意」を参照）。
    取得に失敗した場合は空リストを返し、レポート生成全体には影響しない。
"""
from __future__ import annotations

from typing import List, Optional

from ..utils import SourceRegistry
from .news import Headline, fetch_headlines

# ベストエフォート値。本番導入前に必ず実URLを確認すること（README参照）。
INVESTING_SOURCES = [
    {"name": "Investing.com News", "url": "https://www.investing.com/rss/news.rss"},
]

RELIABILITY = {"Investing.com News": 0.6}


def fetch_investing_headlines(
    sources: SourceRegistry, limit: int = 8, news_sources: Optional[list] = None
) -> List[Headline]:
    return fetch_headlines(news_sources if news_sources is not None else INVESTING_SOURCES, sources, limit, reliability_map=RELIABILITY)
