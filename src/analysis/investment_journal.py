"""Investment Journal（v2.8・①）— 毎日のAI判断を記録し、後日答え合わせする。

data/investment_journal/journal.json に毎日1エントリを追記（同一日付は上書き）。
記録内容: 日付・重要ニュース・重要テーマ・Today's Scenario・Investment Thesis・
Market Regime・Money Flow・Top Picks・Confidence・重要イベント、および後日の
比較用に主要指標の参照価格。

30/90/180日後、現在の市場データ（GitHub Actions実行時に取得）と記録時の参照
価格を比較し、「AI判断 → 実際」を機械的に答え合わせして★評価と理由を付ける。
評価はルールベースであり、AIが新たな予測を生成するものではない。市場データを
取得できない環境（オフライン）では評価は「評価待ち」のまま安全に保持される。
"""
from __future__ import annotations

import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

from ..report.format_utils import find_quote, stars
from .models import LearningHistoryEntry

logger = logging.getLogger("market_brief")

DEFAULT_DIR = "data/investment_journal"
JOURNAL_FILENAME = "journal.json"
EVAL_HORIZONS = [30, 90, 180]
# 参照価格を記録する主要指標（記録時と後日の比較に使う）
_REF_INSTRUMENTS = ["日経平均", "TOPIX", "米ドル/円", "NYダウ", "ナスダック"]
HISTORY_DISPLAY_LIMIT = 20


def _journal_path(base_dir) -> Path:
    return Path(base_dir) / JOURNAL_FILENAME


def _load(base_dir) -> List[dict]:
    path = _journal_path(base_dir)
    if not path.is_file():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, list) else []
    except (OSError, ValueError) as exc:
        logger.warning("Investment Journalの読み込みに失敗しました（空として扱います）: %s", exc)
        return []


def _save(base_dir, entries: List[dict]) -> None:
    path = _journal_path(base_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(entries, ensure_ascii=False, indent=2), encoding="utf-8")


def _market_refs(market: dict) -> Dict[str, float]:
    refs: Dict[str, float] = {}
    all_quotes = (
        (market or {}).get("indices", [])
        + (market or {}).get("forex", [])
        + (market or {}).get("rates", [])
    )
    for name in _REF_INSTRUMENTS:
        q = find_quote(all_quotes, name)
        if q is not None and q.price is not None:
            refs[name] = float(q.price)
    return refs


def build_snapshot(date_str: str, analysis, market: dict) -> dict:
    """その日のAI判断のスナップショット（dict）を組み立てる。"""
    fi = analysis.future_intelligence
    scenario = analysis.scenario
    dominant = max(
        [("bull", scenario.bull_pct), ("neutral", scenario.neutral_pct), ("bear", scenario.bear_pct)],
        key=lambda x: x[1],
    )[0]
    top_thesis = fi.investment_theses[0] if fi.investment_theses else None
    return {
        "date": date_str,
        "top_news": [i.headline.title for i in analysis.news_ranking[:3]],
        "top_themes": [tm.label for tm in fi.theme_momentum[:3]],
        "scenario": {
            "bull": scenario.bull_pct,
            "neutral": scenario.neutral_pct,
            "bear": scenario.bear_pct,
            "dominant": dominant,
        },
        "investment_thesis": [t.label for t in fi.investment_theses[:3]],
        "market_regime": fi.capital_flow_market_mood or "分析材料不足",
        "money_flow": [cf.label for cf in fi.capital_flow_notes[:3]],
        "top_picks": [p.quote.name for p in analysis.long_term_picks[:3]],
        "confidence": top_thesis.confidence_score if top_thesis else 0,
        "weekly_events": [e.label for e in analysis.weekly_events[:5]],
        "market_ref": _market_refs(market),
        "evaluations": {},  # {"30": {...}} を後日埋める
    }


def record_daily_journal(base_dir, date_str: str, snapshot: dict) -> None:
    """journal.jsonへ追記する（同一日付は上書き）。"""
    entries = _load(base_dir)
    entries = [e for e in entries if e.get("date") != date_str]
    entries.append(snapshot)
    entries.sort(key=lambda e: e.get("date", ""))
    _save(base_dir, entries)
    logger.info("Investment Journal: %s のAI判断を記録しました（累計%d日分）。", date_str, len(entries))


def _days_between(old: str, new: str) -> Optional[int]:
    try:
        d_old = datetime.strptime(old[:10], "%Y-%m-%d").date()
        d_new = datetime.strptime(new[:10], "%Y-%m-%d").date()
        return (d_new - d_old).days
    except (ValueError, TypeError):
        return None


def _evaluate_entry(entry: dict, current_refs: Dict[str, float], horizon: int) -> Optional[dict]:
    """記録時の参照価格と現在価格を比較し、支配的シナリオの当否を判定する。"""
    ref = entry.get("market_ref", {})
    nikkei_ref = ref.get("日経平均")
    nikkei_now = current_refs.get("日経平均")
    if not nikkei_ref or not nikkei_now:
        return None  # 比較材料が無ければ評価しない（推測で埋めない）
    change_pct = (nikkei_now - nikkei_ref) / nikkei_ref * 100
    dominant = entry.get("scenario", {}).get("dominant", "neutral")

    if dominant == "bull":
        expected = "上昇"
        hit = change_pct >= 2
        partial = 0 <= change_pct < 2
    elif dominant == "bear":
        expected = "下落"
        hit = change_pct <= -2
        partial = -2 < change_pct <= 0
    else:
        expected = "横ばい"
        hit = abs(change_pct) < 3
        partial = 3 <= abs(change_pct) < 6

    if hit:
        score, status = 5, "的中"
    elif partial:
        score, status = 3, "部分的中"
    else:
        score, status = 1, "外れ"
    actual = "上昇" if change_pct >= 2 else ("下落" if change_pct <= -2 else "横ばい")
    note = (
        f"記録時のシナリオ（{expected}想定・{dominant}優勢）に対し、"
        f"日経平均は{horizon}日で{change_pct:+.1f}%（実際は{actual}）でした。"
    )
    return {"stars": stars(score, max_stars=5), "status": status, "note": note, "change_pct": round(change_pct, 1)}


def evaluate_journal(base_dir, market: dict, now: datetime) -> None:
    """30/90/180日が経過したエントリを、現在の市場データと比較して評価する。"""
    entries = _load(base_dir)
    if not entries:
        return
    current_refs = _market_refs(market)
    if "日経平均" not in current_refs:
        logger.info("Investment Journal: 現在の市場データが不足のため答え合わせはスキップします。")
        return
    now_str = now.strftime("%Y-%m-%d")
    changed = False
    for entry in entries:
        elapsed = _days_between(entry.get("date", ""), now_str)
        if elapsed is None:
            continue
        for horizon in EVAL_HORIZONS:
            key = str(horizon)
            if elapsed >= horizon and key not in entry.get("evaluations", {}):
                result = _evaluate_entry(entry, current_refs, horizon)
                if result is not None:
                    entry.setdefault("evaluations", {})[key] = result
                    changed = True
    if changed:
        _save(base_dir, entries)
        logger.info("Investment Journal: 経過したAI判断の答え合わせを更新しました。")


def build_learning_history(base_dir, now: datetime, limit: int = HISTORY_DISPLAY_LIMIT) -> List[LearningHistoryEntry]:
    """Learning Historyセクション用に、新しい順で過去エントリを整形して返す。"""
    entries = _load(base_dir)
    now_str = now.strftime("%Y-%m-%d")
    history: List[LearningHistoryEntry] = []
    for entry in sorted(entries, key=lambda e: e.get("date", ""), reverse=True)[:limit]:
        evals = entry.get("evaluations", {})
        # 最も長い到達済みホライズンの評価を表示（無ければ評価待ち）
        best = None
        for horizon in sorted(EVAL_HORIZONS, reverse=True):
            if str(horizon) in evals:
                best = (horizon, evals[str(horizon)])
                break
        scenario = entry.get("scenario", {})
        scenario_summary = f"強気{scenario.get('bull', 0)}%／中立{scenario.get('neutral', 0)}%／弱気{scenario.get('bear', 0)}%"
        he = LearningHistoryEntry(
            date=entry.get("date", ""),
            headline=(entry.get("top_news") or [""])[0],
            theme=(entry.get("top_themes") or [""])[0],
            scenario_summary=scenario_summary,
            days_elapsed=_days_between(entry.get("date", ""), now_str) or 0,
        )
        if best is not None:
            horizon, result = best
            he.evaluated = True
            he.evaluation_horizon = horizon
            he.evaluation_stars = result.get("stars", "")
            he.evaluation_status = result.get("status", "評価待ち")
            he.evaluation_note = result.get("note", "")
        history.append(he)
    return history
