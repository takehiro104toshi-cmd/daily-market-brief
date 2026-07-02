"""JPX（日本取引所グループ）: 参照リンクのみを登録し、詳細データの自動取得は行わない。

方針（重要）:
    JPXの個別統計・開示データページは構成が細かく変わりやすく、確認済みの
    公開RSS/APIが存在しないため、利用規約への配慮からページの自動取得
    （スクレイピング）は行わない。公式サイトのURLを出典一覧に
    「参照リンク」として登録するのみとする。
    レポート本文にはJPX由来の詳細データの引用は一切含まれない。
    なお、TDnet（適時開示情報閲覧サービス）は既存機能として別途、
    公開一覧ページから開示情報を取得している（src/collectors/tdnet.py）。
"""
from __future__ import annotations

from ..utils import SourceRegistry

REFERENCE_URL = "https://www.jpx.co.jp/markets/today/index.html"
REFERENCE_LABEL = "JPX 日本取引所グループ(公式サイト・参照リンクのみ／自動取得なし)"


def register_reference(sources: SourceRegistry) -> None:
    sources.add(REFERENCE_LABEL, REFERENCE_URL, "参照リンク")
