"""Theme Rotation（v3.2・改善8）— テーマからテーマへの資金移動を分析する。

AI→半導体→電力→電線→素材→建設 のような、あるテーマの物色が一巡した後に
隣接テーマへ資金が向かいやすい「ローテーション」を、既存の Theme Momentum Score
（future_intelligence が算出済み）と config.yaml の theme_relations（人手による
テーマ隣接関係）だけから機械的に推定する。

実際の資金フロー額は取得しておらず、断定はしない（「移りやすい」等の非断定表現に
統一）。生成AIの推測は使わず、モメンタム差と隣接関係の突き合わせのみ。
"""
from __future__ import annotations

from typing import Dict, List

from .models import ThemeMomentumEntry, ThemeRotationEntry

# from 側のモメンタム下限（十分に物色されているテーマだけを起点にする）
_FROM_MOMENTUM_FLOOR = 50
# 「資金が移りやすい」と判定するモメンタム差の下限
_ROTATION_GAP = 10


def build_theme_rotation(
    theme_momentum: List[ThemeMomentumEntry],
    theme_relations: Dict[str, List[str]],
    limit: int = 8,
) -> List[ThemeRotationEntry]:
    """テーマ間の資金移動の「向かいやすさ」を推定して列挙する。"""
    theme_relations = theme_relations or {}
    momentum_map = {tm.label: tm.momentum_score for tm in (theme_momentum or [])}
    if not momentum_map:
        return []

    entries: List[ThemeRotationEntry] = []
    seen = set()
    for from_theme, from_m in momentum_map.items():
        if from_m < _FROM_MOMENTUM_FLOOR:
            continue
        for to_theme in theme_relations.get(from_theme, []):
            to_m = momentum_map.get(to_theme)
            if to_m is None:
                continue
            key = (from_theme, to_theme)
            if key in seen:
                continue
            gap = from_m - to_m
            if gap >= _ROTATION_GAP:
                signal = "資金が移りやすい"
                note = (
                    f"「{from_theme}」（勢い{from_m}）の物色が一巡した後、隣接する"
                    f"「{to_theme}」（勢い{to_m}）へ資金が向かいやすい局面と考えられます。"
                )
            elif abs(gap) < _ROTATION_GAP:
                signal = "拮抗"
                note = f"「{from_theme}」と「{to_theme}」の勢いは拮抗しており、資金移動の方向は限定的です。"
            else:
                continue  # 逆方向は to 側を起点にしたときに拾う
            seen.add(key)
            entries.append(ThemeRotationEntry(
                from_theme=from_theme,
                to_theme=to_theme,
                from_momentum=from_m,
                to_momentum=to_m,
                signal=signal,
                note=note,
            ))

    # from 側の勢いが強く、かつモメンタム差が大きい順に並べる
    entries.sort(key=lambda e: (-e.from_momentum, -(e.from_momentum - e.to_momentum)))
    return entries[:limit]
