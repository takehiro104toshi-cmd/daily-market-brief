"""今日の相場シナリオ（強気・普通・弱気）の確率をルールベースで算出する。

生成AIではなく、以下のような透明なスコアリング式で計算する
「機械的な考察エンジン」であることを明記する。

  net_score = 2.0 * NYダウ変化率(%)
            + 1.5 * S&P500変化率(%)
            + 1.0 * ナスダック変化率(%)
            + VIX水準による加点（低いほど強気）
            + 0.5 * (米ドル/円の変化率の符号)
            - 0.5 * (米10年金利の変化の符号)
            + 0.3 * (業種の追い風数 - 逆風数の合計)

net_score をもとに強気/普通/弱気の3区分へ配分する。
ANTHROPIC_API_KEY が設定されている場合は、Claudeにこのたたき台を
「事実の範囲内」で自然な文章へ磨き上げてもらう（失敗時は自動フォールバック）。
"""
from __future__ import annotations

from typing import List, Optional

from ..collectors.themes import SectorMatch
from ..report.format_utils import find_quote
from . import llm_enhancer
from .models import ScenarioForecast


def _vix_score(vix_price: Optional[float]) -> float:
    if vix_price is None:
        return 0.0
    if vix_price < 15:
        return 1.5
    if vix_price < 20:
        return 0.5
    if vix_price < 25:
        return -1.0
    return -2.5


def _sign(value: Optional[float]) -> float:
    if value is None or value == 0:
        return 0.0
    return 1.0 if value > 0 else -1.0


def _normalize_to_100(bull: float, neutral: float, bear: float) -> tuple:
    total = bull + neutral + bear
    bull_i = round(bull / total * 100)
    neutral_i = round(neutral / total * 100)
    bear_i = 100 - bull_i - neutral_i
    return bull_i, neutral_i, bear_i


def _bull_case(dji, vix, tailwind_total: int, headwind_total: int) -> str:
    """強気シナリオの理由（断定を避け、「可能性があります」で統一）。"""
    parts = []
    if dji and dji.change_pct is not None and dji.change_pct >= 0:
        parts.append("NYダウが底堅く推移していること")
    if vix and vix.price is not None and vix.price < 20:
        parts.append("VIX指数が落ち着いていること")
    if tailwind_total > headwind_total:
        parts.append("業種別の追い風ニュースが優勢であること")
    if not parts:
        parts.append("一部の指標に持ち直しの動きが見られること")
    return "、".join(parts) + "などが続けば、上値を試す展開もあり得ると考えられます。"


def _neutral_case() -> str:
    return "強気・弱気材料が拮抗しており、方向感を欠く展開が続く可能性も考えられます。"


def _bear_case(dji, vix, tailwind_total: int, headwind_total: int) -> str:
    """弱気シナリオの理由（断定を避け、「可能性があります」で統一）。"""
    parts = []
    if dji and dji.change_pct is not None and dji.change_pct < 0:
        parts.append("NYダウが軟調に推移していること")
    if vix and vix.price is not None and vix.price >= 20:
        parts.append("VIX指数が警戒的な水準にあること")
    if headwind_total > tailwind_total:
        parts.append("業種別の逆風ニュースが優勢であること")
    if not parts:
        parts.append("一部に不透明な材料が残っていること")
    return "、".join(parts) + "などを踏まえると、下押しリスクも意識される可能性があります。"


def build_scenario(market: dict, sector_matches: List[SectorMatch]) -> ScenarioForecast:
    dji = find_quote(market["indices"], "ダウ")
    sp500 = find_quote(market["indices"], "S&P500")
    nasdaq = find_quote(market["indices"], "ナスダック")
    vix = find_quote(market["indices"], "VIX")
    usdjpy = find_quote(market["forex"], "米ドル/円")
    tnx = find_quote(market["rates"], "10年")

    have_data = any(
        q is not None and q.change_pct is not None for q in [dji, sp500, nasdaq]
    )

    tailwind_total = sum(len(m.tailwind) for m in sector_matches)
    headwind_total = sum(len(m.headwind) for m in sector_matches)

    dji_component = 2.0 * (dji.change_pct if dji and dji.change_pct is not None else 0.0)
    sp500_component = 1.5 * (sp500.change_pct if sp500 and sp500.change_pct is not None else 0.0)
    nasdaq_component = 1.0 * (nasdaq.change_pct if nasdaq and nasdaq.change_pct is not None else 0.0)
    vix_component = _vix_score(vix.price if vix else None)
    fx_component = 0.5 * _sign(usdjpy.change_pct if usdjpy else None)
    rate_component = -0.5 * _sign(tnx.change if tnx else None)
    sector_component = 0.3 * (tailwind_total - headwind_total)

    net_score = (
        dji_component
        + sp500_component
        + nasdaq_component
        + vix_component
        + fx_component
        + rate_component
        + sector_component
    )

    if not have_data:
        bull_pct, neutral_pct, bear_pct = 30, 40, 30
        reasoning = (
            "米国主要指数のデータを十分に取得できなかったため、強気・普通・弱気の配分は"
            "暫定値です（取得不可）。データが揃い次第、より確度の高い配分に更新されます。"
        )
        not_available_reason = "データ不足のため理由を算出できませんでした（取得不可）。"
        return ScenarioForecast(
            bull_pct,
            neutral_pct,
            bear_pct,
            reasoning,
            bull_reason=not_available_reason,
            neutral_reason=not_available_reason,
            bear_reason=not_available_reason,
            bull_indicator="NYダウ・S&P500",
            neutral_indicator="米10年金利・為替",
            bear_indicator="VIX指数",
        )

    # net_scoreをベースに40/30/30の基準配分から強気・弱気側へシフトさせる
    shift = max(-35.0, min(35.0, net_score * 6))
    bull_raw = 40 + max(shift, 0)
    bear_raw = 30 - min(shift, 0)
    neutral_raw = 100 - bull_raw - bear_raw
    bull_pct, neutral_pct, bear_pct = _normalize_to_100(bull_raw, neutral_raw, bear_raw)

    reasons = []
    if dji and dji.change_pct is not None:
        direction = "上昇" if dji.change_pct >= 0 else "下落"
        reasons.append(f"NYダウが前日比{dji.change_pct:+.2f}%と{direction}したこと")
    if vix and vix.price is not None:
        if vix.price >= 20:
            reasons.append(f"VIX指数が{vix.price:.2f}と警戒的な水準にあること")
        else:
            reasons.append(f"VIX指数が{vix.price:.2f}と落ち着いた水準にあること")
    if tailwind_total or headwind_total:
        if tailwind_total > headwind_total:
            reasons.append(f"業種別ニュースで追い風（{tailwind_total}件）が逆風（{headwind_total}件）を上回っていること")
        elif headwind_total > tailwind_total:
            reasons.append(f"業種別ニュースで逆風（{headwind_total}件）が追い風（{tailwind_total}件）を上回っていること")
    if usdjpy and usdjpy.change_pct is not None:
        direction = "円安" if usdjpy.change_pct >= 0 else "円高"
        reasons.append(f"為替が{direction}方向に動いていること")

    if not reasons:
        reasoning = "主要な材料が乏しく、方向感の判断材料が限られています（取得不可含む）。"
    else:
        reasoning = "、".join(reasons) + "などから、上記の配分が想定されます。"

    deterministic_text = (
        f"強気 {bull_pct}% ／ 普通 {neutral_pct}% ／ 弱気 {bear_pct}%。{reasoning}"
    )

    facts = (
        f"NYダウ変化率: {dji.change_pct if dji else None}%, "
        f"S&P500変化率: {sp500.change_pct if sp500 else None}%, "
        f"ナスダック変化率: {nasdaq.change_pct if nasdaq else None}%, "
        f"VIX水準: {vix.price if vix else None}, "
        f"米ドル/円変化率: {usdjpy.change_pct if usdjpy else None}%, "
        f"米10年金利変化: {tnx.change if tnx else None}, "
        f"業種追い風件数: {tailwind_total}, 業種逆風件数: {headwind_total}, "
        f"算出された配分: 強気{bull_pct}% 普通{neutral_pct}% 弱気{bear_pct}%"
    )
    polished_reasoning = llm_enhancer.enhance_or_fallback(
        deterministic_text=reasoning,
        facts=facts,
        instruction=(
            "強気・普通・弱気の配分（数値は変えない）の理由を2〜3文で説明してください。"
            "数値そのものは出力に含めず、理由の説明文だけを出力してください。"
        ),
        max_tokens=300,
    )

    return ScenarioForecast(
        bull_pct,
        neutral_pct,
        bear_pct,
        polished_reasoning,
        bull_reason=_bull_case(dji, vix, tailwind_total, headwind_total),
        neutral_reason=_neutral_case(),
        bear_reason=_bear_case(dji, vix, tailwind_total, headwind_total),
        bull_indicator="NYダウ・S&P500",
        neutral_indicator="米10年金利・為替（米ドル/円）",
        bear_indicator="VIX指数",
    )
