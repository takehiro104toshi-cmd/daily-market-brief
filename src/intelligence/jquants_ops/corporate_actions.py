"""Corporate action policy（Phase 3.6 §12）。

Phase 3.5 実測: 45 session で corporate_action 除外 26 件。これを production contract にする。

| 計算 | 使う価格 | corporate action 日の扱い |
|---|---|---|
| breadth（値上がり/値下がり） | 生終値 C vs 前営業日 C | 当日 AdjFactor≠1 または raw/adjusted 騰落率不一致 → **判定しない**（EXCLUDED・件数を残す） |
| returns（業種/規模の等ウェイト） | 同じ Movement.change_pct（raw） | 除外銘柄は平均に入れない（0で埋めない） |
| rolling（売買代金平均・騰落比率平均） | 金額（Va）と件数 | 影響なし（件数は除外済みの集計を使う） |
| adjusted close（AdjC） | 検知にのみ使用 | raw と混ぜない・時系列比較の代替にしない |

corporate action を通常の価格変動として扱わない。方針変更は price_movement_version を上げる。
"""
from __future__ import annotations

from typing import Dict, List, Mapping

from ..internals.price_movement import EXCL_CORPORATE_ACTION

POLICY: Dict[str, str] = {
    "breadth": "raw close vs previous-session raw close; corporate action day => EXCLUDED (counted, not classified)",
    "returns": "equal-weighted mean of raw change_pct over classified securities only",
    "rolling": "value/count based; unaffected (inputs already exclude corporate-action days)",
    "adjusted_close": "detection only (AdjFactor != 1 or raw/adjusted ratio mismatch > 1e-4); never mixed",
    "version": "price_movement:1.0.0",
    "not_treated_as_price_move": "true",
}


def corporate_action_report(builds: Mapping[str, object]) -> Dict[str, object]:
    """SessionBuild（internals.pipeline）から corporate action 除外を session 別に列挙する。"""
    per_session: Dict[str, List[str]] = {}
    for session, build in sorted(builds.items()):
        codes = sorted(code for code, m in build.movements.items()
                       if m.exclusion_reason == EXCL_CORPORATE_ACTION)
        if codes:
            per_session[session] = codes
    total = sum(len(v) for v in per_session.values())
    return {"policy": POLICY, "sessions_affected": len(per_session), "excluded_total": total,
            "per_session": {k: v[:10] for k, v in per_session.items()},
            "max_per_session": max((len(v) for v in per_session.values()), default=0)}
