"""Market Regime Engine（v3.2・改善1）— 毎朝の地合いを機械的に総合判定する。

VIX・米10年債・NASDAQ・S&P500・SOX・ドル指数・ドル円・WTI・Gold・Bitcoin
などの公開市場データ（前日比・水準）だけから、現在が Risk On / Risk Off /
Neutral のどれかを判定し、さらに 0〜100 の Risk Score を算出する。

生成AIの推測は使わない。各指標について「上昇＝リスクオンか／リスクオフか」を
人手で定義した符号付きの寄与に変換し、重み付き平均を 0〜100 に写像するだけの
透明なスコアリング。データが取れない指標はスキップし、評価に使えた指標数も返す
（データ欠損の把握用）。閾値・重み・符号はすべて本ファイル冒頭に定数化する。
"""
from __future__ import annotations

from typing import List, Optional

from ..report.format_utils import find_quote
from .models import MarketRegime, RegimeSignal

# 各指標の (探索キーワード, 市場カテゴリ, 重み, 向き, 表示名)。
# 向き +1 = 「上昇するとリスクオン」、-1 = 「上昇するとリスクオフ」。
# VIX は水準ベースで別処理するため、この表とは別に扱う。
_CHANGE_SIGNALS = [
    # (keyword, category, weight, direction, label)
    ("S&P500", "indices", 1.4, +1, "S&P500"),
    ("ナスダック", "indices", 1.2, +1, "NASDAQ"),
    ("SOX", "indices", 1.0, +1, "SOX（半導体）"),
    ("ダウ", "indices", 1.0, +1, "NYダウ"),
    ("ドル指数", "indices", 0.8, -1, "ドル指数（DXY）"),
    ("米ドル/円", "forex", 0.6, +1, "ドル円（円安=リスクオン）"),
    ("10年", "rates", 0.6, -1, "米10年金利（上昇=リスクオフ寄り）"),
    ("WTI", "commodities", 0.4, +1, "WTI原油"),
    ("金先物", "commodities", 0.6, -1, "Gold（上昇=リスクオフ）"),
    ("ビットコイン", "commodities", 0.5, +1, "Bitcoin"),
]

# change_pct をこの値で割って [-1, +1] にクランプする（1指標あたりの寄与上限）。
_CHANGE_SCALE = 2.0
# VIX 水準 → リスクオン(+)/オフ(-) の寄与（重みは _VIX_WEIGHT）。
_VIX_WEIGHT = 1.6
# Risk Score の判定閾値。
RISK_ON_THRESHOLD = 60
RISK_OFF_THRESHOLD = 40


def _clamp(value: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, value))


def _vix_contribution(vix_price: Optional[float]) -> Optional[float]:
    """VIX 水準を [-1, +1] の寄与に変換（低い=リスクオン+、高い=リスクオフ-）。"""
    if vix_price is None:
        return None
    if vix_price < 15:
        return 1.0
    if vix_price < 20:
        return 0.5
    if vix_price < 25:
        return -0.5
    if vix_price < 30:
        return -0.8
    return -1.0


def build_market_regime(market: dict) -> MarketRegime:
    """市場データから地合い（Risk On/Off/Neutral）と Risk Score(0〜100) を算出する。"""
    market = market or {}
    signals: List[RegimeSignal] = []
    weighted_sum = 0.0
    weight_total = 0.0

    # VIX（水準ベース）
    vix = find_quote(market.get("indices", []), "VIX")
    vix_c = _vix_contribution(vix.price if vix else None)
    if vix_c is not None:
        weighted_sum += vix_c * _VIX_WEIGHT
        weight_total += _VIX_WEIGHT
        note = "低水準（リスクオン寄り）" if vix_c > 0 else "警戒的な水準（リスクオフ寄り）"
        signals.append(RegimeSignal(name="VIX指数", value=vix.price if vix else None, contribution=round(vix_c * _VIX_WEIGHT, 3), note=note))

    # 前日比ベースの各指標
    for keyword, category, weight, direction, label in _CHANGE_SIGNALS:
        q = find_quote(market.get(category, []), keyword)
        if q is None or q.change_pct is None:
            continue
        raw = _clamp(q.change_pct / _CHANGE_SCALE, -1.0, 1.0) * direction
        weighted_sum += raw * weight
        weight_total += weight
        tone = "リスクオンに寄与" if raw > 0 else ("リスクオフに寄与" if raw < 0 else "中立")
        signals.append(RegimeSignal(name=label, value=q.change_pct, contribution=round(raw * weight, 3), note=f"前日比{q.change_pct:+.2f}%（{tone}）"))

    if weight_total == 0:
        return MarketRegime(
            regime="判定不能",
            stance="Neutral",
            risk_score=50,
            summary="地合い判定に必要な市場データを取得できませんでした（取得不可）。",
            signals=signals,
            evaluated_count=0,
        )

    avg = weighted_sum / weight_total          # [-1, +1]
    risk_score = int(round((avg + 1.0) / 2.0 * 100))
    risk_score = max(0, min(100, risk_score))

    if risk_score >= RISK_ON_THRESHOLD:
        regime, stance = "Risk On", "Bullish"
    elif risk_score <= RISK_OFF_THRESHOLD:
        regime, stance = "Risk Off", "Bearish"
    else:
        regime, stance = "Neutral", "Neutral"

    # 寄与の大きい指標を要約に添える（絶対値上位2件）
    top = sorted(signals, key=lambda s: -abs(s.contribution))[:2]
    top_txt = "、".join(s.name for s in top) if top else "主要指標"
    summary = (
        f"本日の地合いは Risk Score {risk_score}/100（{regime}）。"
        f"主に {top_txt} の動きが寄与しています。"
        "（公開市場データの前日比・水準からの機械的な総合評価であり、投資助言ではありません）"
    )

    return MarketRegime(
        regime=regime,
        stance=stance,
        risk_score=risk_score,
        summary=summary,
        signals=signals,
        evaluated_count=len([s for s in signals]),
    )
