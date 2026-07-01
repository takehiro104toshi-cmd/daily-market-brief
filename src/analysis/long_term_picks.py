"""ウォッチリストの中からAIが「今日最も魅力的」と機械的に判定した長期投資候補TOP5を選ぶ。

スコアリング式（ルールベース、投資助言ではない）:
  score = (関連業種の追い風件数 - 逆風件数) * 2
        + (直近の決算発表が近いカタリストとして存在する場合 +0.5)

関連業種が特定できない銘柄はスコア0として扱い、他に候補が無い場合のみ選出される。
"""
from __future__ import annotations

from typing import Dict, List, Optional

from ..collectors.earnings import EarningsEvent
from ..collectors.market_data import Quote
from ..collectors.themes import SectorMatch
from . import llm_enhancer
from .models import LongTermPick

TOP_N = 5


def _sector_for_ticker(ticker: str, sector_matches: List[SectorMatch]) -> Optional[SectorMatch]:
    return next((m for m in sector_matches if ticker in m.related_tickers), None)


def _score(quote: Quote, sector_matches: List[SectorMatch], earnings_by_ticker: Dict[str, EarningsEvent]) -> float:
    sector = _sector_for_ticker(quote.symbol, sector_matches)
    score = 0.0
    if sector is not None:
        score += (len(sector.tailwind) - len(sector.headwind)) * 2
    if quote.symbol in earnings_by_ticker:
        score += 0.5
    return score


def build_long_term_picks(
    jp_quotes: List[Quote],
    us_quotes: List[Quote],
    sector_matches: List[SectorMatch],
    earnings: List[EarningsEvent],
) -> List[LongTermPick]:
    earnings_by_ticker = {e.ticker: e for e in earnings}
    all_quotes = jp_quotes + us_quotes
    if not all_quotes:
        return []

    scored = [(q, _score(q, sector_matches, earnings_by_ticker)) for q in all_quotes]
    scored.sort(key=lambda item: item[1], reverse=True)
    top = scored[:TOP_N]

    picks: List[LongTermPick] = []
    for rank, (quote, score) in enumerate(top, start=1):
        sector = _sector_for_ticker(quote.symbol, sector_matches)
        if sector is not None and len(sector.tailwind) > len(sector.headwind):
            deterministic_text = (
                f"業種「{sector.label}」に追い風のニュース（{len(sector.tailwind)}件）が出ており、"
                f"{quote.name}は同テーマの構造的な成長を享受できる可能性があります。"
            )
        elif sector is not None:
            deterministic_text = (
                f"業種「{sector.label}」の関連銘柄として選出されていますが、"
                "本日時点では追い風・逆風が拮抗しており、慎重な見極めが必要です。"
            )
        else:
            deterministic_text = (
                f"{quote.name}は本日時点で明確な業種シグナルが確認されませんでしたが、"
                "ウォッチリスト銘柄として長期候補に含めています。"
            )

        facts = (
            f"銘柄名: {quote.name}, 業種: {sector.label if sector else '未特定'}, "
            f"業種追い風件数: {len(sector.tailwind) if sector else 0}, "
            f"業種逆風件数: {len(sector.headwind) if sector else 0}, "
            f"決算発表予定の有無: {'あり' if quote.symbol in earnings_by_ticker else 'なし'}"
        )
        reasoning = llm_enhancer.enhance_or_fallback(
            deterministic_text=deterministic_text,
            facts=facts,
            instruction="この銘柄を長期投資候補として選んだ理由を2文以内で説明してください。断定的な推奨は避けてください。",
            max_tokens=200,
        )

        picks.append(LongTermPick(rank=rank, quote=quote, reasoning=reasoning))
    return picks
