"""Theme Confidence Learning（v2.8・②）— テーマ予想を蓄積し勝率を学習する。

data/theme_learning/theme_learning.json に、毎日のテーマ別診断（Momentum・
Confidence・予想方向）を追記。一定日数が経過した予想は、記録時と現在の
日経平均（＝地合いの代理指標）を比較して当否を評価し、テーマごとの
勝率・平均リターン・平均継続日数・成功/失敗条件を集計する。

集計した勝率は Future Intelligence の Confidence を「実績補正」する際に使う
（例: 92 → 実績が良ければ95、悪ければ72）。補正は上下限つきの小さな調整で、
既存のConfidence計算式そのものは変更しない。市場データが無いオフライン環境
では評価はスキップされ、既存動作に影響しない。
"""
from __future__ import annotations

import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

from ..report.format_utils import find_quote
from .models import ThemeLearningStat

logger = logging.getLogger("market_brief")

DEFAULT_DIR = "data/theme_learning"
FILENAME = "theme_learning.json"
EVAL_DAYS = 30           # 予想から何日後に答え合わせするか
MIN_SAMPLES_FOR_ADJUST = 3   # Confidence補正を適用する最低サンプル数
UP_MOMENTUM_THRESHOLD = 50   # この値以上を「上昇（注目継続）」予想とみなす
# Confidence補正の上下限（実績が悪くても下げすぎず、良くても上げすぎない）
ADJUST_MIN = -20
ADJUST_MAX = 10


def _path(base_dir) -> Path:
    return Path(base_dir) / FILENAME


def _load(base_dir) -> dict:
    path = _path(base_dir)
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError) as exc:
        logger.warning("Theme Learningの読み込みに失敗しました（空として扱います）: %s", exc)
        return {}


def _save(base_dir, data: dict) -> None:
    path = _path(base_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def _nikkei(market: dict) -> Optional[float]:
    q = find_quote((market or {}).get("indices", []), "日経平均")
    return float(q.price) if q is not None and q.price is not None else None


def record_theme_predictions(base_dir, date_str: str, theme_diagnosis: List, market: dict) -> None:
    """その日のテーマ別診断を予想として追記する（同一日付は上書き）。"""
    data = _load(base_dir)
    nikkei_ref = _nikkei(market)
    for td in theme_diagnosis:
        rec = data.setdefault(td.label, {"first_seen": date_str, "predictions": []})
        rec["predictions"] = [p for p in rec["predictions"] if p.get("date") != date_str]
        rec["predictions"].append(
            {
                "date": date_str,
                "momentum": td.momentum_score,
                "confidence": td.confidence_score,
                "direction": "up" if td.momentum_score >= UP_MOMENTUM_THRESHOLD else "flat",
                "nikkei_ref": nikkei_ref,
                "evaluated": False,
                "win": None,
                "return_pct": None,
            }
        )
    _save(base_dir, data)
    logger.info("Theme Learning: %s のテーマ予想を記録しました（%dテーマ）。", date_str, len(theme_diagnosis))


def _days_between(old: str, new: str) -> Optional[int]:
    try:
        return (datetime.strptime(new[:10], "%Y-%m-%d").date() - datetime.strptime(old[:10], "%Y-%m-%d").date()).days
    except (ValueError, TypeError):
        return None


def evaluate_theme_learning(base_dir, market: dict, now: datetime) -> None:
    """EVAL_DAYS経過した予想を、日経平均の騰落（地合いの代理）で答え合わせする。"""
    data = _load(base_dir)
    if not data:
        return
    nikkei_now = _nikkei(market)
    if nikkei_now is None:
        logger.info("Theme Learning: 現在の市場データが不足のため答え合わせはスキップします。")
        return
    now_str = now.strftime("%Y-%m-%d")
    changed = False
    for rec in data.values():
        for p in rec.get("predictions", []):
            if p.get("evaluated") or p.get("nikkei_ref") in (None, 0):
                continue
            elapsed = _days_between(p.get("date", ""), now_str)
            if elapsed is None or elapsed < EVAL_DAYS:
                continue
            change_pct = (nikkei_now - p["nikkei_ref"]) / p["nikkei_ref"] * 100
            # 「上昇（注目継続）」予想は地合いが上向けば的中、「flat」は±3%以内で的中
            if p["direction"] == "up":
                win = change_pct >= 2
            else:
                win = abs(change_pct) < 3
            p.update(evaluated=True, win=bool(win), return_pct=round(change_pct, 1), elapsed_days=elapsed)
            changed = True
    if changed:
        _save(base_dir, data)
        logger.info("Theme Learning: 経過したテーマ予想の答え合わせを更新しました。")


def _aggregate(rec: dict) -> dict:
    evaluated = [p for p in rec.get("predictions", []) if p.get("evaluated")]
    samples = len(evaluated)
    wins = sum(1 for p in evaluated if p.get("win"))
    returns = [p["return_pct"] for p in evaluated if p.get("return_pct") is not None]
    durations = [p.get("elapsed_days") for p in evaluated if p.get("elapsed_days")]
    return {
        "samples": samples,
        "wins": wins,
        "win_rate": (wins / samples) if samples else None,
        "avg_return_pct": (sum(returns) / len(returns)) if returns else None,
        "avg_duration_days": (sum(durations) / len(durations)) if durations else None,
    }


def win_rates(base_dir) -> Dict[str, float]:
    """テーマ名 → 勝率（サンプルがMIN_SAMPLES_FOR_ADJUST以上のみ）。Confidence補正用。"""
    data = _load(base_dir)
    result: Dict[str, float] = {}
    for label, rec in data.items():
        agg = _aggregate(rec)
        if agg["samples"] >= MIN_SAMPLES_FOR_ADJUST and agg["win_rate"] is not None:
            result[label] = agg["win_rate"]
    return result


def confidence_adjustment(win_rate: Optional[float]) -> int:
    """勝率からConfidenceの補正値（点）を返す。上下限つきの小さな調整。"""
    if win_rate is None:
        return 0
    nudge = round((win_rate - 0.5) * 40)
    return max(ADJUST_MIN, min(ADJUST_MAX, nudge))


def build_theme_learning_stats(base_dir, limit: int = 12) -> List[ThemeLearningStat]:
    """表示用: サンプルの多い順にテーマ学習の集計を返す。"""
    data = _load(base_dir)
    stats: List[ThemeLearningStat] = []
    for label, rec in data.items():
        agg = _aggregate(rec)
        if agg["samples"] == 0:
            continue
        wr = agg["win_rate"]
        stats.append(
            ThemeLearningStat(
                label=label,
                first_seen=rec.get("first_seen", ""),
                samples=agg["samples"],
                wins=agg["wins"],
                win_rate=wr,
                avg_return_pct=agg["avg_return_pct"],
                avg_duration_days=agg["avg_duration_days"],
                success_condition="地合い改善局面で注目が継続しやすい傾向" if wr and wr >= 0.5 else "",
                failure_condition="地合い悪化局面で失速しやすい傾向" if wr is not None and wr < 0.5 else "",
            )
        )
    stats.sort(key=lambda s: -s.samples)
    return stats[:limit]
