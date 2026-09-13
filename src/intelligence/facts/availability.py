"""Morning availability と look-ahead防止（Phase 3-A STEP 19/21）。

**LOOK-AHEAD BIAS禁止**: あるTokyo trading session時点のsnapshotへ、
その後に公開された情報を入れない。判定は `Fact.time.known_at`（この事実が
システムから見て既知になった時刻）で行う。

判定はFAIL-CLOSED: `known_at` が無いFactは「その時点で既知だった」と**見なさない**
（分からないものを使えることにしない）。
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Iterable, List, Sequence

from .model import Fact, FactStatus

#: 東京セッションのクローズ（JST）
TOKYO_CLOSE_JST = (15, 30)
#: Morning Compassの想定作成時間帯（JST）
MORNING_WINDOW_JST = (6, 9)

JST = timezone(timedelta(hours=9))


def morning_cutoff(session_date: str, *, hour: int = MORNING_WINDOW_JST[0]) -> datetime:
    """指定営業日の「朝」時点（JST）をUTC awareで返す。

    このcutoffより後に既知になった情報は、その朝のCompassでは使えない。
    """
    year, month, day = (int(p) for p in session_date.split("-"))
    return datetime(year, month, day, hour, 0, tzinfo=JST).astimezone(timezone.utc)


def is_known_by(fact: Fact, cutoff: datetime) -> bool:
    """`cutoff` 時点でこのFactが既知だったか。

    `known_at` が無ければ **False**（未知扱い）——推測で「あったこと」にしない。
    """
    if fact.time.known_at is None:
        return False
    return fact.time.known_at <= cutoff


def available_at(facts: Iterable[Fact], cutoff: datetime) -> List[Fact]:
    """`cutoff` 時点で既知だったFactだけを返す（look-ahead除去）。"""
    return [f for f in facts if is_known_by(f, cutoff)]


def morning_snapshot(
    facts: Iterable[Fact], session_date: str, *, hour: int = MORNING_WINDOW_JST[0],
    include_limited_use: bool = False,
) -> List[Fact]:
    """`session_date` の朝時点で利用可能だったFact集合（STEP 19）。

    - `known_at <= 当日朝cutoff` のFactのみ
    - status が USABLE（`include_limited_use=True` なら LIMITED_USE も）
    - UNUSABLE / SUPERSEDED は含めない
    """
    cutoff = morning_cutoff(session_date, hour=hour)
    allowed = {FactStatus.USABLE}
    if include_limited_use:
        allowed.add(FactStatus.LIMITED_USE)
    return sorted(
        (f for f in facts if f.status in allowed and is_known_by(f, cutoff)),
        key=lambda f: (f.subject.key(), f.fact_type, f.time.primary_date))


def leaked_facts(facts: Sequence[Fact], cutoff: datetime) -> List[Fact]:
    """cutoff以降にしか既知でないのに混入しているFact（テスト・監査用）。"""
    return [f for f in facts if not is_known_by(f, cutoff)]
