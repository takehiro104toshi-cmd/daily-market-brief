"""株探（Kabutan）: 参照リンクのみを登録し、本文・見出しの自動取得は行わない。

方針（重要）:
    株探には確認済みの公開RSS/APIが存在しない。利用規約への配慮から、
    ページの自動取得（スクレイピング）は行わず、公式サイトのURLを
    出典一覧に「参照リンク」として登録するのみとする。
    レポート本文には株探由来の見出し・引用は一切含まれない。
"""
from __future__ import annotations

from ..utils import SourceRegistry

REFERENCE_URL = "https://kabutan.jp/"
REFERENCE_LABEL = "株探(公式サイト・参照リンクのみ／自動取得なし)"


def register_reference(sources: SourceRegistry) -> None:
    sources.add(REFERENCE_LABEL, REFERENCE_URL, "参照リンク")
