"""Future Probability（v3.2・改善7）— 未来「予測」ではなく条件分岐（if条件型）で示す。

Future Intelligence を補強する追加エンジン。「もしAかつBなら → C」という
人手で定義したif条件ルールを、本日の公開市場データ（前日比・水準）で機械的に
評価し、条件が満たされている分岐（triggered=True）を「現在この分岐にある」と
示すだけ。生成AIによる将来予測・確率の創作は一切行わない。

各ルールの conditions は人が読める条件文のリスト。triggered は、対応する
市場データが取得でき、かつ全条件が現時点で成立している場合のみ True。
データ欠損時は triggered=False（＝条件を確認できない）として安全側に倒す。
"""
from __future__ import annotations

from typing import Callable, List, Optional, Tuple

from ..report.format_utils import find_quote
from .models import ConditionalScenario


def _chg(market: dict, category: str, keyword: str) -> Optional[float]:
    q = find_quote(market.get(category, []), keyword)
    return q.change_pct if (q and q.change_pct is not None) else None


def _chg_abs(market: dict, category: str, keyword: str) -> Optional[float]:
    q = find_quote(market.get(category, []), keyword)
    return q.change if (q and q.change is not None) else None


def _level(market: dict, category: str, keyword: str) -> Optional[float]:
    q = find_quote(market.get(category, []), keyword)
    return q.price if (q and q.price is not None) else None


# 各ルール: (ラベル, 条件文リスト, 条件評価関数（全成立ならTrue・データ欠損ならNone）, 結論)
def _cond_recession(market: dict) -> Optional[bool]:
    vix = _level(market, "indices", "VIX")
    tnx = _chg_abs(market, "rates", "10年")
    if vix is None or tnx is None:
        return None
    return vix >= 22 and tnx < 0


def _cond_risk_on(market: dict) -> Optional[bool]:
    sp = _chg(market, "indices", "S&P500")
    vix = _level(market, "indices", "VIX")
    if sp is None or vix is None:
        return None
    return sp > 0 and vix < 18


def _cond_yen_weak_export(market: dict) -> Optional[bool]:
    usdjpy = _chg(market, "forex", "米ドル/円")
    tnx = _chg_abs(market, "rates", "10年")
    if usdjpy is None or tnx is None:
        return None
    return usdjpy > 0 and tnx > 0


def _cond_inflation(market: dict) -> Optional[bool]:
    wti = _chg(market, "commodities", "WTI")
    tnx = _chg_abs(market, "rates", "10年")
    if wti is None or tnx is None:
        return None
    return wti >= 1.5 and tnx > 0


def _cond_safe_haven(market: dict) -> Optional[bool]:
    gold = _chg(market, "commodities", "金先物")
    vix = _level(market, "indices", "VIX")
    if gold is None or vix is None:
        return None
    return gold > 0 and vix >= 20


_RULES: List[Tuple[str, List[str], Callable[[dict], Optional[bool]], str]] = [
    ("景気後退懸念シナリオ",
     ["VIXが警戒的な水準（22以上）", "米10年金利が低下"],
     _cond_recession,
     "景気後退・リスク回避が意識されやすい地合い（ディフェンシブ・債券・金が相対的に選好されやすい）。"),
    ("リスクオン継続シナリオ",
     ["S&P500が上昇", "VIXが低水準（18未満）"],
     _cond_risk_on,
     "リスク選好が続きやすい地合い（グロース・ハイテク・半導体が物色されやすい）。"),
    ("円安・輸出優位シナリオ",
     ["ドル円が円安方向（上昇）", "米10年金利が上昇"],
     _cond_yen_weak_export,
     "日米金利差拡大から円安が進みやすく、輸出関連（自動車・半導体）が優位になりやすい。"),
    ("インフレ再燃警戒シナリオ",
     ["WTI原油が上昇（+1.5%以上）", "米10年金利が上昇"],
     _cond_inflation,
     "インフレ再燃が意識され、金利上昇・資源優位・グロース逆風になりやすい。"),
    ("安全資産選好シナリオ",
     ["Goldが上昇", "VIXが高め（20以上）"],
     _cond_safe_haven,
     "安全資産への逃避が意識されやすく、株式には重石となりやすい。"),
]


def build_conditional_scenarios(market: dict) -> List[ConditionalScenario]:
    """if条件ベースの分岐シナリオ一覧を返す（triggeredで現在の分岐を示す）。"""
    market = market or {}
    out: List[ConditionalScenario] = []
    for label, conditions, evaluator, outcome in _RULES:
        result = evaluator(market)
        if result is None:
            triggered = False
            rationale = "判定に必要な市場データが不足しているため、現時点では条件を確認できません（取得不可）。"
        elif result:
            triggered = True
            rationale = "本日の市場データで上記条件がすべて成立しています（現在この分岐にあります）。"
        else:
            triggered = False
            rationale = "本日の市場データでは上記条件は成立していません（この分岐にはありません）。"
        out.append(ConditionalScenario(
            label=label,
            conditions=list(conditions),
            outcome=outcome,
            triggered=triggered,
            rationale=rationale,
        ))
    return out
