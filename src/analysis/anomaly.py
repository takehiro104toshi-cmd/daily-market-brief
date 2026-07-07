"""市場データの異常値検知（v3.1・改善3）— 取得データが妥当かを機械的にチェックする。

「このデータが本当に正しいのか」を朝の確認材料にするための、表示専用の
軽量チェック。分析ロジック・ランキングには一切影響しない。閾値を超えた
変動や、明らかに範囲外の水準を「要確認」として列挙するだけで、原因の断定や
自動補正は行わない（あくまで人が確認するためのフラグ）。
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional

from ..report.format_utils import find_quote

# 前日比の異常閾値（%）。これを超えたら「要確認」フラグを立てる。
NIKKEI_PCT = 5.0
INDEX_PCT = 5.0
FX_PCT = 2.0
RATE_PCT = 15.0  # 金利は%変化ではなく水準変化が大きいので広めに取る
# 水準の妥当レンジ（明らかに桁がおかしい値を検知する保守的な下限・上限）
_SANITY_RANGE = {
    "日経平均": (3000, 100000),
    "米ドル/円": (50, 300),
    "NYダウ": (5000, 100000),
}


@dataclass
class AnomalyEntry:
    name: str
    message: str


def _check_change(quotes, name: str, pct_limit: float, out: List[AnomalyEntry]) -> None:
    q = find_quote(quotes, name)
    if q is None or q.change_pct is None:
        return
    if abs(q.change_pct) >= pct_limit:
        out.append(AnomalyEntry(name, f"{name}が前日比{q.change_pct:+.2f}%と大きく変動（±{pct_limit:.0f}%以上）。取得値の確認を推奨します。"))


def _check_sanity(quotes, name: str, out: List[AnomalyEntry]) -> None:
    q = find_quote(quotes, name)
    if q is None or q.price is None:
        return
    lo, hi = _SANITY_RANGE.get(name, (None, None))
    if lo is not None and not (lo <= q.price <= hi):
        out.append(AnomalyEntry(name, f"{name}の水準（{q.price:g}）が想定レンジ（{lo:g}〜{hi:g}）から外れています。取得値の確認を推奨します。"))


def detect_anomalies(market: dict) -> List[AnomalyEntry]:
    """市場データから異常値の可能性を検知して列挙する（問題なければ空リスト）。"""
    market = market or {}
    indices = market.get("indices", [])
    forex = market.get("forex", [])
    rates = market.get("rates", [])
    out: List[AnomalyEntry] = []

    _check_change(indices, "日経平均", NIKKEI_PCT, out)
    for idx_name in ("NYダウ", "S&P500", "ナスダック"):
        _check_change(indices, idx_name, INDEX_PCT, out)
    _check_change(forex, "米ドル/円", FX_PCT, out)
    _check_change(rates, "10年", RATE_PCT, out)

    for name in _SANITY_RANGE:
        _check_sanity(indices + forex + rates, name, out)

    return out


def anomaly_status_label(anomalies: List[AnomalyEntry]) -> str:
    """異常値チェックの総合ステータス（Data Quality表示用）。"""
    return "要確認" if anomalies else "異常値なし"
