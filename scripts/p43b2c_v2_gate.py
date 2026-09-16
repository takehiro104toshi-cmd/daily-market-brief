#!/usr/bin/env python3
"""GitHub Actions 用（P4-3b2c）: `/v2` 公開可否の**分類だけ**を行う typed gate。

責務は 1 つだけ——信頼済み selection metadata と凍結 P4-3b2a の検証結果を受け取り、
明示された「いま」に対して次の 4 値のどれかへ分類する:

  PASS               公開してよい
  V2_UNAVAILABLE     公開材料が無い / 古すぎる（safe-skip。legacy は publish する）
  V2_REJECTED        b2a が公開契約違反として拒否した（safe-skip ＋ 可視警告）
  V2_INTERNAL_ERROR  入力が壊れている / b2a の応答が読めない（safe-skip ＋ 可視警告）

鮮度契約（beta 凍結値）:

  artifact age <= 24 時間   … producer artifact の `created_at` と現在 UTC の差
  session lag  <= 3 暦日    … JST 当日と `session_date` の差

**祝日カレンダーを実装しない。** 立会日かどうかは判定せず、上の 2 つの独立した明示上限
だけで押さえる。未来 session の拒否は凍結 b2a の既存責務であり、ここでは再実装しない
（万一通過してきた場合の防御としてだけ見る）。

**やらないこと**: b2a の公開内容検証の複製 / MarketSignal マッピングの複製 /
Compass 内部の参照 / 投資判断 / ネットワーク / リポジトリ書き込み / 時計を読むこと
（「いま」は呼び出し側が明示的に渡す）。

標準ライブラリのみを使う。
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Dict, Optional, Sequence, Tuple

GATE_VERSION = "0.1.0"

#: beta 凍結の鮮度上限（監督者決定。コードへ埋めた値を勝手に変えない）
MAX_ARTIFACT_AGE_HOURS = 24
MAX_SESSION_LAG_DAYS = 3

RESULT_PASS = "PASS"
RESULT_UNAVAILABLE = "V2_UNAVAILABLE"
RESULT_REJECTED = "V2_REJECTED"
RESULT_INTERNAL_ERROR = "V2_INTERNAL_ERROR"
RESULTS = (RESULT_PASS, RESULT_UNAVAILABLE, RESULT_REJECTED, RESULT_INTERNAL_ERROR)

_ISO_DATE = re.compile(r"\A\d{4}-\d{2}-\d{2}\Z")
_MARKER = re.compile(r"::P43B2A_([A-Z_]+)::(\{.*\})\s*$")


def _parse_iso_utc(value: object) -> Optional[datetime]:
    """`2026-09-15T06:52:28Z` 形式だけを受ける（曖昧な形は None）。"""
    if not isinstance(value, str) or not value:
        return None
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return None
    return parsed.astimezone(timezone.utc)


def parse_b2a_markers(text: str) -> Dict[str, Dict]:
    """凍結 b2a の stdout から `::P43B2A_*::` を読む（内容の再検証はしない）。"""
    found: Dict[str, Dict] = {}
    for line in text.splitlines():
        match = _MARKER.search(line.strip())
        if not match:
            continue
        try:
            payload = json.loads(match.group(2))
        except ValueError:
            continue
        if isinstance(payload, dict):
            found[match.group(1)] = payload
    return found


def artifact_age_hours(created_at: object, now_utc: object) -> Optional[float]:
    created = _parse_iso_utc(created_at)
    now = _parse_iso_utc(now_utc)
    if created is None or now is None:
        return None
    return (now - created).total_seconds() / 3600.0


def session_lag_days(session_date: object, jst_today: object) -> Optional[int]:
    if not (isinstance(session_date, str) and _ISO_DATE.match(session_date)):
        return None
    if not (isinstance(jst_today, str) and _ISO_DATE.match(jst_today)):
        return None
    try:
        session = date.fromisoformat(session_date)
        today = date.fromisoformat(jst_today)
    except ValueError:
        return None
    return (today - session).days


def classify(*, selection: Dict, b2a_output: str, now_utc: str,
             jst_today: str) -> Dict[str, object]:
    """4 値のいずれかへ分類し、判断材料をそのまま添えて返す。"""
    verdict: Dict[str, object] = {
        "gate_version": GATE_VERSION, "result": RESULT_INTERNAL_ERROR,
        "reason_code": "UNCLASSIFIED", "reason": "",
        "max_artifact_age_hours": MAX_ARTIFACT_AGE_HOURS,
        "max_session_lag_days": MAX_SESSION_LAG_DAYS,
        "artifact_age_hours": None, "session_lag_days": None,
        "session_date": "", "reference_session": "", "published_names": [],
    }

    def settle(result: str, code: str, reason: str) -> Dict[str, object]:
        verdict.update({"result": result, "reason_code": code, "reason": reason})
        return verdict

    if not isinstance(selection, dict) or not selection:
        return settle(RESULT_INTERNAL_ERROR, "SELECTION_UNUSABLE",
                      "selection metadata is missing or unusable")

    markers = parse_b2a_markers(b2a_output or "")
    end = markers.get("END")
    if markers.get("REJECTED") or (isinstance(end, dict) and end.get("result") == "REJECTED"):
        rejection = markers.get("REJECTED") or {}
        return settle(RESULT_REJECTED, "B2A_REJECTED",
                      str(rejection.get("reason", "frozen b2a rejected the publication")))
    if not isinstance(end, dict) or end.get("result") != "OK":
        return settle(RESULT_INTERNAL_ERROR, "B2A_OUTPUT_UNREADABLE",
                      "frozen b2a did not report a usable terminal result")

    published = markers.get("PUBLISHED") or {}
    names = published.get("names")
    if not isinstance(names, list) or not names:
        return settle(RESULT_INTERNAL_ERROR, "B2A_PUBLISHED_UNREADABLE",
                      "frozen b2a reported no published names")
    verdict["published_names"] = sorted(str(n) for n in names)

    payload = markers.get("INPUT") or {}
    session_date = payload.get("session_date") or end.get("session_date")
    verdict["session_date"] = str(session_date or "")
    verdict["reference_session"] = str(payload.get("reference_session") or "")

    age = artifact_age_hours(selection.get("artifact_created_at"), now_utc)
    verdict["artifact_age_hours"] = None if age is None else round(age, 3)
    if age is None:
        return settle(RESULT_INTERNAL_ERROR, "ARTIFACT_TIME_UNREADABLE",
                      "artifact created_at or the supplied now is unusable")
    if age < 0:
        return settle(RESULT_INTERNAL_ERROR, "ARTIFACT_TIME_IN_FUTURE",
                      "artifact created_at is later than the supplied now")
    if age > MAX_ARTIFACT_AGE_HOURS:
        return settle(RESULT_UNAVAILABLE, "ARTIFACT_TOO_OLD",
                      f"artifact is {age:.1f}h old, limit is {MAX_ARTIFACT_AGE_HOURS}h")

    lag = session_lag_days(session_date, jst_today)
    verdict["session_lag_days"] = lag
    if lag is None:
        return settle(RESULT_INTERNAL_ERROR, "SESSION_DATE_UNREADABLE",
                      "session_date or the supplied JST today is unusable")
    if lag < 0:
        # 凍結 b2a が既に拒否する形。ここへ来たら契約違反として扱う（推測しない）。
        return settle(RESULT_REJECTED, "FUTURE_SESSION",
                      "session_date is later than the supplied JST today")
    if lag > MAX_SESSION_LAG_DAYS:
        return settle(RESULT_UNAVAILABLE, "SESSION_TOO_OLD",
                      f"session is {lag} calendar days behind, limit is "
                      f"{MAX_SESSION_LAG_DAYS}")

    return settle(RESULT_PASS, "OK", "artifact and session are within the freshness contract")


# ---------------------------------------------------------------- CLI

def _emit(marker: str, payload: Dict[str, object]) -> None:
    print(f"::P43B2C_{marker}::" + json.dumps(payload, ensure_ascii=False, sort_keys=True))


def _read_json(path: str) -> Dict:
    try:
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _read_text(path: str) -> str:
    try:
        return Path(path).read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="P4-3b2c: /v2 公開可否の typed gate（分類のみ）")
    parser.add_argument("--selection", default="", help="selector が書いた JSON")
    parser.add_argument("--b2a-output", default="", help="凍結 b2a の stdout を保存した file")
    parser.add_argument("--now-utc", default="", help="現在 UTC（ISO 8601・明示）")
    parser.add_argument("--jst-today", default="", help="JST 当日 YYYY-MM-DD（明示）")
    parser.add_argument("--output", default="", help="判定結果の書き出し先 JSON")
    args = parser.parse_args(argv)

    verdict = classify(selection=_read_json(args.selection),
                       b2a_output=_read_text(args.b2a_output),
                       now_utc=args.now_utc, jst_today=args.jst_today)
    _emit("GATE", verdict)
    if args.output:
        Path(args.output).write_text(json.dumps(verdict, ensure_ascii=False, sort_keys=True),
                                     encoding="utf-8")
    return 0                       # 分類は result に出る。exit code で legacy を落とさない。


if __name__ == "__main__":                                   # pragma: no cover
    sys.exit(main())
