"""「今日見るべき指標」を判定する。

config.yaml の `key_levels` に設定された節目ライン（例: 米ドル/円150/155/160円）と
現在値を比較し、最も近いラインと「超えたら何が起きやすいか」の一言をルールベースで
算出する。将来の値動きを断定するものではなく、あくまで一般的に意識されやすい水準の
参考情報である。
"""
from __future__ import annotations

from typing import List, Optional

from ..collectors.market_data import Quote
from ..report.format_utils import NOT_AVAILABLE
from .models import KeyLevelEntry


def _find_exact(quotes: List[Quote], name: str) -> Optional[Quote]:
    return next((q for q in quotes if q.name == name), None)


def build_key_levels(market: dict, config: dict) -> List[KeyLevelEntry]:
    """market の全カテゴリから、config.yaml の key_levels 設定に対応する銘柄を探し、
    現在値・最寄りの節目ライン・一言コメントを算出する。
    """
    all_quotes = (
        market.get("indices", [])
        + market.get("forex", [])
        + market.get("rates", [])
        + market.get("commodities", [])
    )

    entries: List[KeyLevelEntry] = []
    for item in config.get("key_levels", []):
        name = item.get("name", "")
        quote = _find_exact(all_quotes, name)
        lines = item.get("lines", [])

        if quote is None or quote.price is None:
            entries.append(
                KeyLevelEntry(
                    label=name,
                    quote=quote,
                    key_line=None,
                    note=f"データを取得できませんでした（{NOT_AVAILABLE}）。",
                )
            )
            continue

        if not lines:
            entries.append(
                KeyLevelEntry(label=name, quote=quote, key_line=None, note="節目ラインが設定されていません。")
            )
            continue

        nearest = min(lines, key=lambda line: abs(line - quote.price))
        if quote.price >= nearest:
            note = item.get("above_note", "")
        else:
            note = item.get("below_note", "")
        entries.append(KeyLevelEntry(label=name, quote=quote, key_line=nearest, note=note))

    return entries
