"""日本経済新聞 電子版の公開見出しRSS（ベストエフォート）。

重要な注意（必ず読むこと）:
    日本経済新聞は有料会員限定の記事本文がほとんどのため、本文の取得・転載は
    一切行わない。ここで参照するのは「公開されている見出し一覧RSS相当」の
    エンドポイントのみであり、この開発環境（サンドボックス・外部ネットワーク
    遮断）では実際の接続確認ができていない「ベストエフォート」実装である。
    本番運用前に、URLが現行の公開仕様と一致しているか、利用規約に照らして
    問題ないかを必ず確認すること（README「情報源に関する注意」を参照）。
    取得に失敗した場合は空リストを返し、レポート生成全体には影響しない。
"""
from __future__ import annotations

from typing import List, Optional

from ..utils import SourceRegistry
from .news import Headline, fetch_headlines

# ベストエフォート値。本番導入前に必ず実URLを確認すること（README参照）。
NIKKEI_SOURCES = [
    {"name": "日本経済新聞 電子版(見出し)", "url": "https://www.nikkei.com/rss/index.rdf"},
]

RELIABILITY = {"日本経済新聞 電子版(見出し)": 0.9}


def fetch_nikkei_headlines(
    sources: SourceRegistry, limit: int = 8, news_sources: Optional[list] = None
) -> List[Headline]:
    """news_sources を指定すると、config.yaml の nikkei_sources 等で上書きできる
    （テストで到達不能なローカルアドレスに差し替える用途を想定）。未指定時は
    ベストエフォートの既定URL（NIKKEI_SOURCES）を使う。"""
    return fetch_headlines(news_sources if news_sources is not None else NIKKEI_SOURCES, sources, limit, reliability_map=RELIABILITY)
