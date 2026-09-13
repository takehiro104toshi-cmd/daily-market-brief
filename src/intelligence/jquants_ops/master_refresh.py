"""Listed master strategy（Phase 3.6 §10 / §11）。

- effective master snapshot: `/equities/master?date=<YYYY-MM-DD>` で **過去日付の snapshot** を
  取得できる（run #20 実測: date=2026-06-26 → 4,439行）。seed window の開始日と、以後は
  週1回（＋上場/廃止イベント時）の snapshot を canonical（record_id = sec_<code>_<date>）へ
  append-only で蓄積し、session ごとに「session 以前で最新の snapshot」を使う。
- KNOWN_LIMITATION_HISTORICAL_UNIVERSE: snapshot 間（最大7日）の上場・廃止は反映されない。
  rolling 60 session 用途では影響は小さい（run #20: 45 session で構成不変）が、
  推測で membership を補完しない。snapshot が session 以前に無い場合は最古を遡及適用し
  `master_applied_backwards` を明示する。
- 変更検出: added / removed / market / sector(S17/S33) / ScaleCat の差分を機械可読に記録。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Dict, List, Mapping, Optional, Sequence, Tuple

KNOWN_LIMITATION_HISTORICAL_UNIVERSE = "KNOWN_LIMITATION_HISTORICAL_UNIVERSE"
REFRESH_WEEKLY = "WEEKLY"


@dataclass(frozen=True, kw_only=True)
class MasterDiff:
    from_date: str
    to_date: str
    rows_from: int
    rows_to: int
    added: Tuple[str, ...]
    removed: Tuple[str, ...]
    market_changes: Tuple[Tuple[str, str, str], ...]
    sector17_changes: Tuple[Tuple[str, str, str], ...]
    sector33_changes: Tuple[Tuple[str, str, str], ...]
    scale_changes: Tuple[Tuple[str, str, str], ...]

    @property
    def total_changes(self) -> int:
        return (len(self.added) + len(self.removed) + len(self.market_changes)
                + len(self.sector17_changes) + len(self.sector33_changes)
                + len(self.scale_changes))

    def as_dict(self) -> Dict[str, object]:
        def rows(items):
            return [{"code": c, "from": a, "to": b} for c, a, b in items[:20]]
        return {
            "from_date": self.from_date, "to_date": self.to_date,
            "rows_from": self.rows_from, "rows_to": self.rows_to,
            "added": list(self.added[:50]), "added_count": len(self.added),
            "removed": list(self.removed[:50]), "removed_count": len(self.removed),
            "market_changes": rows(self.market_changes),
            "market_change_count": len(self.market_changes),
            "sector17_changes": rows(self.sector17_changes),
            "sector17_change_count": len(self.sector17_changes),
            "sector33_changes": rows(self.sector33_changes),
            "sector33_change_count": len(self.sector33_changes),
            "scale_changes": rows(self.scale_changes),
            "scale_change_count": len(self.scale_changes),
            "total_changes": self.total_changes,
        }


def _get(row: Mapping, key: str) -> str:
    try:
        value = row[key]
    except (KeyError, IndexError):
        return ""
    return "" if value is None else str(value)


def diff_master(rows_from: Sequence[Mapping], rows_to: Sequence[Mapping], *,
                from_date: str = "", to_date: str = "") -> MasterDiff:
    a = {_get(r, "code"): r for r in rows_from if _get(r, "code")}
    b = {_get(r, "code"): r for r in rows_to if _get(r, "code")}
    added = tuple(sorted(set(b) - set(a)))
    removed = tuple(sorted(set(a) - set(b)))
    changes = {"market_code": [], "sector17_code": [], "sector33_code": [], "scale_category": []}
    for code in sorted(set(a) & set(b)):
        for key in changes:
            before, after = _get(a[code], key), _get(b[code], key)
            if before != after:
                changes[key].append((code, before, after))
    return MasterDiff(
        from_date=from_date or (_get(next(iter(rows_from)), "effective_date") if rows_from else ""),
        to_date=to_date or (_get(next(iter(rows_to)), "effective_date") if rows_to else ""),
        rows_from=len(a), rows_to=len(b), added=added, removed=removed,
        market_changes=tuple(changes["market_code"]),
        sector17_changes=tuple(changes["sector17_code"]),
        sector33_changes=tuple(changes["sector33_code"]),
        scale_changes=tuple(changes["scale_category"]))


def refresh_due(*, latest_effective_date: str, today: str, interval_days: int = 7) -> bool:
    if not latest_effective_date:
        return True
    try:
        return (date.fromisoformat(today) - date.fromisoformat(latest_effective_date)).days \
            >= interval_days
    except ValueError:
        return True


def snapshot_dates_for_seed(seed_sessions: Sequence[str], *, interval_days: int = 7) -> List[str]:
    """seed 時に取る master snapshot 日付: 開始日 ＋ interval ごと（最後は今日の snapshot）。"""
    if not seed_sessions:
        return []
    ordered = sorted(seed_sessions)
    out = [ordered[0]]
    last = date.fromisoformat(ordered[0])
    for s in ordered[1:]:
        d = date.fromisoformat(s)
        if (d - last).days >= interval_days:
            out.append(s)
            last = d
    return out


def strategy() -> Dict[str, object]:
    return {
        "effective_master_snapshot": "date-parameter snapshots (verified run #20) appended as "
                                     "sec_<code>_<date>; per session use latest snapshot <= session",
        "refresh_frequency": REFRESH_WEEKLY + " (+ on listing/delisting event, + when a session has "
                                              "no snapshot at or before it)",
        "not_every_morning": True,
        "limitation": KNOWN_LIMITATION_HISTORICAL_UNIVERSE,
        "limitation_detail": "membership changes between snapshots (<= 7 days) are not reflected; "
                             "no guessed membership; backward application is flagged",
        "change_detection": ["added", "removed", "market_code", "sector17_code", "sector33_code",
                             "scale_category"],
    }
