"""Scenario Engine v2（v2.8・③）— 期待値の高い最大3シナリオに絞って提示する。

既存の build_scenario（ScenarioForecast: 強気/中立/弱気の確率・理由・注目指標）と
既存シグナル（業種の追い風/逆風・ウォッチリスト銘柄・因果チェーン）のみから
機械的に組み立てる。新たな確率予測・目標株価・断定的な過去事例は生成しない。
確率（＝期待値の代理）の高い順に①②③として並べる。
"""
from __future__ import annotations

from typing import Dict, List, Optional

from ..collectors.themes import SectorMatch
from ..report.format_utils import stars
from .models import ScenarioForecast, ScenarioV2Entry

MAX_SCENARIOS = 3


def _stars_for_probability(pct: int) -> str:
    if pct >= 45:
        return stars(5, max_stars=5)
    if pct >= 35:
        return stars(4, max_stars=5)
    if pct >= 25:
        return stars(3, max_stars=5)
    if pct >= 15:
        return stars(2, max_stars=5)
    return stars(1, max_stars=5)


def _top_sectors(sector_matches: List[SectorMatch], key: str, limit: int = 3) -> List[str]:
    """追い風（tailwind）または逆風（headwind）の多い業種名を上位で返す。"""
    scored = [(m.label, len(getattr(m, key))) for m in sector_matches]
    scored = [(label, n) for label, n in scored if n > 0]
    scored.sort(key=lambda x: -x[1])
    return [label for label, _ in scored[:limit]]


def build_scenarios_v2(
    scenario: ScenarioForecast,
    sector_matches: List[SectorMatch],
    watchlist_names: List[str],
    causal_chains: Optional[List[str]] = None,
) -> List[ScenarioV2Entry]:
    """強気/中立/弱気の3分岐を、確率の高い順に最大3シナリオへ整理する。"""
    tail_sectors = _top_sectors(sector_matches, "tailwind")
    head_sectors = _top_sectors(sector_matches, "headwind")
    chains = causal_chains or []
    watch = watchlist_names[:5]

    # (確率, タイトル, 発生条件, マーケット影響, 恩恵, 悪影響, 時間軸, 一般パターン)
    branches = [
        {
            "prob": scenario.bull_pct,
            "title": "リスクオン（上値追い）シナリオ",
            "trigger": scenario.bull_reason,
            "impact": "株高・円安方向に振れやすく、景気敏感株やグロース株に追い風が意識されやすい展開です。",
            "benefit": tail_sectors,
            "adverse": head_sectors,
            "horizon": "短期（数日〜数週間）",
            "hist": "一般に、地合い改善局面では景気敏感株やグロース株が先行しやすい傾向があります（特定の過去日の断定ではありません）。",
            "chain": chains[0] if len(chains) >= 1 else "",
        },
        {
            "prob": scenario.neutral_pct,
            "title": "レンジ継続（方向感待ち）シナリオ",
            "trigger": scenario.neutral_reason,
            "impact": "強弱材料が拮抗し、指数はレンジ内での推移が中心。個別材料株物色が主体になりやすい展開です。",
            "benefit": [],
            "adverse": [],
            "horizon": "短期（数日〜数週間）",
            "hist": "一般に、方向感を欠く局面では決算・イベント通過まで様子見ムードが続きやすい傾向があります。",
            "chain": chains[1] if len(chains) >= 2 else "",
        },
        {
            "prob": scenario.bear_pct,
            "title": "リスクオフ（調整）シナリオ",
            "trigger": scenario.bear_reason,
            "impact": "株安・円高方向に振れやすく、ディフェンシブ・内需への資金退避が意識されやすい展開です。",
            "benefit": [],
            "adverse": tail_sectors,
            "horizon": "短期（数日〜数週間）",
            "hist": "一般に、警戒局面では高PER・輸出関連が調整しやすく、ディフェンシブが相対的に堅い傾向があります。",
            "chain": "",
        },
    ]

    branches.sort(key=lambda b: -b["prob"])
    entries: List[ScenarioV2Entry] = []
    for i, b in enumerate(branches[:MAX_SCENARIOS], start=1):
        entries.append(
            ScenarioV2Entry(
                rank=i,
                title=b["title"],
                probability=b["prob"],
                stars=_stars_for_probability(b["prob"]),
                trigger_condition=b["trigger"] or "本日の材料からは明確な発生条件を特定できませんでした（分析材料不足）。",
                market_impact=b["impact"],
                beneficiary_sectors=b["benefit"],
                adverse_sectors=b["adverse"],
                watch_names=watch,
                causal_chain=b["chain"],
                time_horizon=b["horizon"],
                historical_note=b["hist"],
            )
        )
    return entries
