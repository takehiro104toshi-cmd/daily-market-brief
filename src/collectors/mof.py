"""財務省の公開「新着情報」RSSから見出し・リンクのみを収集する。

https://www.mof.go.jp/rss/whatsnew.rdf は財務省が公開している新着情報RSSで、
為替介入方針・国債発行計画・財政関連の公表等を検知できる。ログイン不要で
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

MOF_SOURCES = [
    {"name": "財務省 新着情報", "url": "https://www.mof.go.jp/rss/whatsnew.rdf"},
]

RELIABILITY = {"財務省 新着情報": 0.95}


def fetch_mof_headlines(
    sources: SourceRegistry, limit: int = 8, news_sources: Optional[list] = None
) -> List[Headline]:
    """news_sources を指定すると、config.yaml の mof_sources 等で上書きできる
    （テストで到達不能なローカルアドレスに差し替える用途を想定）。未指定時は
    既定URL（MOF_SOURCES）を使う。"""
    return fetch_headlines(news_sources if news_sources is not None else MOF_SOURCES, sources, limit, reliability_map=RELIABILITY)
