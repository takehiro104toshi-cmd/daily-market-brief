"""ユーザー向け status と milestone feedback（Phase 3.75 §17 / §19）。frontend は作らない。

- latest_status.txt: 人が読む最新状態（日本語）
- latest_status.json: machine-readable
書き先は機械ローカル home と（設定で）同期フォルダの `_status/`（iPhone の Files app からも見える）。
本文・full path は書かない。
"""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Mapping, Optional, Sequence

from ..corpus.milestones import milestone_status
from ..corpus.status import ANALYZED, PARTIAL
from ..corpus.store import CorpusStore
from .result import DUPLICATE, FAILED, HINTS_JA, QUARANTINED, SUCCESS, WAITING_UNSTABLE, ProcessingResult

STATUS_TXT = "latest_status.txt"
STATUS_JSON = "latest_status.json"


def corpus_count(store: CorpusStore) -> int:
    """usable document 数（ANALYZED / PARTIAL）。quarantined / failed は数えない。"""
    return sum(1 for d in store.documents()
               if store.current_status(d.document_id) in (ANALYZED, PARTIAL))


def milestone_feedback(count: int, thresholds: Sequence[int]) -> Dict[str, object]:
    m = milestone_status(count, thresholds)
    return {"corpus": count, "reached": m.reached, "next": m.next_milestone,
            "remaining": m.documents_needed, "next_threshold": m.next_threshold}


def _milestone_lines(ms: Mapping[str, object]) -> List[str]:
    lines = [f"Corpus: {ms.get('corpus', 0)}"]
    if ms.get("next"):
        lines.append(f"Next: {ms['next']}")
        lines.append(f"Remaining: {ms['remaining']}")
    else:
        lines.append("Next: -（全 milestone 到達）")
    return lines


def render_result_ja(result: ProcessingResult, day: str) -> str:
    ms = dict(result.milestone)
    if result.result == SUCCESS:
        lines = [day, "羅針盤追加成功",
                 f"Corpus: {result.corpus_count_before} → {result.corpus_count_after}"]
        if result.document_date:
            lines.append(f"発行日: {result.document_date}")
        if ms.get("reached") and ms.get("reached") != "NONE" and \
                ms.get("reached_now"):
            lines.append(f"Milestone 到達: {ms['reached']}")
        lines += _milestone_lines(ms)[1:]
        return "\n".join(lines)
    if result.result == DUPLICATE:
        return "\n".join([day, "既に登録済み", f"発行日: {result.document_date}" if result.document_date else "",
                          *_milestone_lines(ms)]).replace("\n\n", "\n")
    if result.result == WAITING_UNSTABLE:
        return "\n".join([day, "処理待ち（転送中）", HINTS_JA.get(result.reason_code, ""),
                          *_milestone_lines(ms)])
    if result.result == QUARANTINED:
        return "\n".join([day, f"追加できません: {result.reason_code}", result.hint, *_milestone_lines(ms)])
    return "\n".join([day, f"失敗: {result.reason_code}", result.hint, *_milestone_lines(ms)])


def render_idle_ja(day: str, ms: Mapping[str, object], pending: int) -> str:
    head = f"処理待ち {pending} 件（転送中）" if pending else "新しい羅針盤はありません"
    return "\n".join([day, head, *_milestone_lines(ms)])


def write_status(dirs: Sequence[Path], text: str, payload: Mapping[str, object]) -> List[Path]:
    written: List[Path] = []
    for d in dirs:
        try:
            d = Path(d)
            d.mkdir(parents=True, exist_ok=True)
            (d / STATUS_TXT).write_text(text + "\n", encoding="utf-8")
            (d / STATUS_JSON).write_text(json.dumps(dict(payload), ensure_ascii=False, indent=1,
                                                    default=str), encoding="utf-8")
            written.append(d / STATUS_TXT)
        except OSError:
            continue
    return written


def read_status(dir_: Path) -> Optional[Dict[str, object]]:
    path = Path(dir_) / STATUS_JSON
    if not path.is_file():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
