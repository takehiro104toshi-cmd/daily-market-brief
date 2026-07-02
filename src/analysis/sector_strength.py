"""「セクターランキング」: 本日「強そう／弱そう」をAIが機械的に予測する（矢印＋理由）。

config.yaml の sectors（既存の業種マッチング結果 sector_matches）をそのまま
再利用し、新たな考察ロジックは持たない。追い風件数と逆風件数の差分で
↑（強そう）／→（様子見）／↓（弱そう）を判定し、追い風優勢・逆風優勢の順に
並べ替える（既存の「業界ランキング TOP10」とは表示形式が異なるだけで、
同じ sector_matches データを使う）。
"""
from __future__ import annotations

from typing import List

from ..collectors.themes import SectorMatch
from .models import SectorStrengthEntry

ARROW_UP = "↑"
ARROW_FLAT = "→"
ARROW_DOWN = "↓"


def _arrow_and_reason(sector: SectorMatch) -> tuple:
    diff = len(sector.tailwind) - len(sector.headwind)
    if diff > 0:
        return ARROW_UP, f"追い風ニュースが{len(sector.tailwind)}件と逆風（{len(sector.headwind)}件）を上回っており、強含みが意識されやすい状況です。"
    if diff < 0:
        return ARROW_DOWN, f"逆風ニュースが{len(sector.headwind)}件と追い風（{len(sector.tailwind)}件）を上回っており、弱含みが意識されやすい状況です。"
    if sector.tailwind or sector.headwind:
        return ARROW_FLAT, "追い風・逆風の材料が拮抗しており、方向感を欠く展開が意識されやすい状況です。"
    return ARROW_FLAT, "本日時点で目立った材料は確認されておらず、様子見が意識されやすい状況です。"


def build_sector_strength(sector_matches: List[SectorMatch]) -> List[SectorStrengthEntry]:
    entries = []
    for sector in sector_matches:
        arrow, reason = _arrow_and_reason(sector)
        entries.append(SectorStrengthEntry(label=sector.label, arrow=arrow, reason=reason))

    # 強そう(↑)を上位、弱そう(↓)を下位に、差分の大きい順で並べ替える
    def _sort_key(entry_and_sector):
        entry, sector = entry_and_sector
        return len(sector.tailwind) - len(sector.headwind)

    paired = sorted(zip(entries, sector_matches), key=_sort_key, reverse=True)
    return [entry for entry, _ in paired]
