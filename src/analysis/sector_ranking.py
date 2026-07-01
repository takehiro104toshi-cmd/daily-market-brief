"""注目業界をTOP10でランキングし、追い風・逆風・関連銘柄・営業トークを付与する。

ランキングはニュース件数（追い風+逆風+中立の合計）を信号の強さとして
降順に並べる、ルールベースの機械的な処理。
"""
from __future__ import annotations

from typing import Dict, List

from ..collectors.market_data import Quote
from ..collectors.themes import SectorMatch
from ..report.format_utils import count_stars, fmt_change
from .models import SectorRankingEntry

TOP_N = 10


def _sales_talk(match: SectorMatch) -> str:
    if len(match.tailwind) > len(match.headwind):
        return f"「本日は{match.label}に追い風のニュースが目立ちます」"
    if len(match.headwind) > len(match.tailwind):
        return f"「本日は{match.label}に逆風のニュースが目立ちます」"
    return f"「本日の{match.label}関連ニュースは強弱まちまちです」"


def build_sector_ranking(
    sector_matches: List[SectorMatch],
    ticker_lookup: Dict[str, Quote],
) -> List[SectorRankingEntry]:
    if not sector_matches:
        return []

    ranked = sorted(
        sector_matches,
        key=lambda m: len(m.tailwind) + len(m.headwind) + len(m.neutral),
        reverse=True,
    )[:TOP_N]

    entries: List[SectorRankingEntry] = []
    for rank, match in enumerate(ranked, start=1):
        total = len(match.tailwind) + len(match.headwind) + len(match.neutral)
        related = [ticker_lookup[t] for t in match.related_tickers if t in ticker_lookup]
        unresolved = [t for t in match.related_tickers if t not in ticker_lookup]
        entries.append(
            SectorRankingEntry(
                rank=rank,
                label=match.label,
                stars=count_stars(total, max_stars=5),
                tailwind=match.tailwind,
                headwind=match.headwind,
                related=related,
                related_unresolved=unresolved,
                sales_talk=_sales_talk(match),
            )
        )
    return entries
