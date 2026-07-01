"""AIストラテジストとしての「今日の戦略」を300文字以内でまとめる。

決定論的なたたき台を先に組み立て、ANTHROPIC_API_KEY設定時のみ
Claudeによる磨き上げを試みる。いずれの場合も、最終出力は必ず
300文字（全角換算ではなく文字数）以内に収める。
"""
from __future__ import annotations

from typing import List

from ..collectors.themes import SectorMatch, ThemeMatch
from ..report.format_utils import truncate_to_chars
from . import llm_enhancer
from .models import ScenarioForecast

MAX_CHARS = 300


def build_ai_summary(
    scenario: ScenarioForecast,
    theme_matches: List[ThemeMatch],
    sector_matches: List[SectorMatch],
) -> str:
    top_theme = max(theme_matches, key=lambda m: len(m.headlines)).label if theme_matches else None
    top_sector = None
    if sector_matches:
        ranked = sorted(sector_matches, key=lambda m: len(m.tailwind) - len(m.headwind), reverse=True)
        top_sector = ranked[0]

    parts = [
        f"本日の相場は強気{scenario.bull_pct}%・普通{scenario.neutral_pct}%・弱気{scenario.bear_pct}%と見立てています。"
    ]
    if top_sector is not None and len(top_sector.tailwind) > len(top_sector.headwind):
        parts.append(f"「{top_sector.label}」に追い風の材料が優勢で、関連銘柄への資金流入余地があります。")
    elif top_sector is not None:
        parts.append(f"「{top_sector.label}」は追い風・逆風が拮抗しており、方向感を見極める局面です。")
    if top_theme:
        parts.append(f"テーマとしては「{top_theme}」が注目されています。")
    parts.append("いずれも公開情報に基づく機械的な考察であり、投資助言ではない点にご留意ください。")

    deterministic_text = "".join(parts)

    facts = (
        f"強気{scenario.bull_pct}% 普通{scenario.neutral_pct}% 弱気{scenario.bear_pct}%, "
        f"注目テーマ: {top_theme or '該当なし'}, "
        f"注目業種: {top_sector.label if top_sector else '該当なし'}"
    )
    polished = llm_enhancer.enhance_or_fallback(
        deterministic_text=deterministic_text,
        facts=facts,
        instruction="AIストラテジストとして「今日の戦略」を300文字以内の1つの段落で書いてください。断定的な投資助言は避けてください。",
        max_tokens=400,
    )
    return truncate_to_chars(polished, MAX_CHARS)
