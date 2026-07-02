"""Reutersの公開見出しRSS（ベストエフォート）。

重要な注意（必ず読むこと）:
    Reutersの本文取得・転載は一切行わない。ここで参照するのは「公開されて
    いる見出し一覧RSS相当」のエンドポイントのみであり、この開発環境
    （サンドボックス・外部ネットワーク遮断）では実際の接続確認ができていない
    「ベストエフォート」実装である。Reutersは過去に公式RSSの提供方針を
    変更した経緯があるため、本番運用前に、URLが現行の公開仕様と一致している
    か、利用規約に照らして問題ないかを必ず確認すること
    （README「情報源に関する注意」を参照）。
    なお、Yahoo!ニュース経由のロイター配信見出し（config.yamlのnews_sources）
    は既存機能として利用可能であり、こちらは動作確認済みである。
    取得に失敗した場合は空リストを返し、レポート生成全体には影響しない。
"""
from __future__ import annotations

from typing import List, Optional

from ..utils import SourceRegistry
from .news import Headline, fetch_headlines

# ベストエフォート値。本番導入前に必ず実URLを確認すること（README参照）。
REUTERS_SOURCES = [
    {"name": "Reuters Business(見出し)", "url": "https://www.reutersagency.com/feed/?best-topics=business-finance"},
]

RELIABILITY = {"Reuters Business(見出し)": 0.85}


def fetch_reuters_headlines(
    sources: SourceRegistry, limit: int = 8, news_sources: Optional[list] = None
) -> List[Headline]:
    """news_sources を指定すると、config.yaml の reuters_sources 等で上書きできる
    （テストで到達不能なローカルアドレスに差し替える用途を想定）。未指定時は
    ベストエフォートの既定URL（REUTERS_SOURCES）を使う。"""
    return fetch_headlines(news_sources if news_sources is not None else REUTERS_SOURCES, sources, limit, reliability_map=RELIABILITY)
