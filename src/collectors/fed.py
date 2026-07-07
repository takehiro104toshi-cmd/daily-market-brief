"""米連邦準備制度理事会（FRB/Fed）の公開プレスリリースRSSから見出し・リンクのみを
収集する（v2.9 Source Expansion Engine・③）。

https://www.federalreserve.gov/feeds/press_all.xml はFRBが公開している
プレスリリース全体のRSSで、FOMC声明・金融政策関連の公表を検知できる。
ログイン不要で一般公開されている。本文は取得せず、見出し・リンクのみを扱う。

注意: この開発環境（サンドボックス・外部ネットワーク遮断）では実際の接続
確認ができていない（既存のBOJ/MOF等の海外collectorと同様の制約）。本番運用前に
一度実行し、正しく取得できるか確認すること（README「情報源に関する注意」を参照）。
取得に失敗した場合は空リストを返し、レポート生成全体には影響しない。
"""
from __future__ import annotations

from typing import List, Optional

from ..utils import SourceRegistry
from .news import Headline, fetch_headlines

FED_SOURCES = [
    {"name": "Federal Reserve Press Releases", "url": "https://www.federalreserve.gov/feeds/press_all.xml"},
]

RELIABILITY = {"Federal Reserve Press Releases": 0.97}


def fetch_fed_headlines(
    sources: SourceRegistry, limit: int = 8, news_sources: Optional[list] = None
) -> List[Headline]:
    """news_sources を指定すると、config.yaml の fed_sources 等で上書きできる
    （テストで到達不能なローカルアドレスに差し替える用途を想定）。未指定時は
    既定URL（FED_SOURCES）を使う。"""
    return fetch_headlines(news_sources if news_sources is not None else FED_SOURCES, sources, limit, reliability_map=RELIABILITY)
