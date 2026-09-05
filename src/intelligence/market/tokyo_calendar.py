"""東京セッション判定の最小実装（Phase 2-H STEP 9）。

目的は**latest completed Tokyo session**の決定だけ。calendar subsystemを
過剰設計しない（営業時間・半日立会の細目・先物カレンダー等は作らない）。

P2-G.2の残課題への対応:
TOPIXのfreshness判定は「日経平均の最新セッション」という**代理指標**に依存していた。
J-Quants取引カレンダー（`/markets/calendar`・Light可）が使えるようになったため、
**公式カレンダーからlatest completed sessionを決定できる**ようにする。

FAIL-CLOSED / 推測しない:
- `HolDiv`（休日区分）の**意味はsource側のコード値**であり、ここで断定しない。
  「どの値が営業日か」は実データ（TOPIXの観測日）との突き合わせで検証する
  （`validate_divisions()`）。検証していないコード値は営業日扱いしない。
- カレンダーが無い/検証できない場合は `None` を返し、呼び出し側は
  **従来の参照系列ベース判定へフォールバック**する（勝手に当て推量しない）。
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from typing import Dict, Iterable, List, Mapping, Optional, Sequence, Set, Tuple

#: 実測で「営業日」と確認できたHolDiv値のみを既定に置く。
#: JPX取引カレンダーの区分値は 1=営業日 / 0=非営業日 が広く使われるが、
#: **この既定は `validate_divisions()` の実測検証を通って初めて信頼する**。
DEFAULT_TRADING_DIVISIONS: Tuple[str, ...] = ("1",)
#: 半日立会等、営業日ではあるが立会時間が異なる可能性のある区分（実測で確認するまで空）
HALF_DAY_DIVISIONS: Tuple[str, ...] = ()

#: 東京現物指数のクローズ（JST）。as_of算出はingest側の規約に従うためここでは判定のみ
TOKYO_CLOSE_HOUR_JST = 15
TOKYO_CLOSE_MINUTE_JST = 30


@dataclass(frozen=True, kw_only=True)
class CalendarValidation:
    """カレンダー区分の実測検証結果（推測でなく突き合わせで確定する）。"""

    trading_divisions: Tuple[str, ...]
    checked_dates: int
    agreements: int
    disagreements: Tuple[str, ...]
    observed_divisions: Mapping[str, int]

    @property
    def validated(self) -> bool:
        """1件でも食い違えば未検証扱い（部分的な一致を検証済みにしない）。"""
        return self.checked_dates > 0 and not self.disagreements

    def as_dict(self) -> Dict[str, object]:
        return {
            "trading_divisions": list(self.trading_divisions),
            "checked_dates": self.checked_dates,
            "agreements": self.agreements,
            "disagreements": list(self.disagreements[:10]),
            "disagreement_count": len(self.disagreements),
            "observed_divisions": dict(self.observed_divisions),
            "validated": self.validated,
        }


def trading_days(
    calendar_rows: Iterable[Mapping],
    *,
    trading_divisions: Sequence[str] = DEFAULT_TRADING_DIVISIONS,
) -> List[str]:
    """カレンダー行 → 営業日（ISO日付）の昇順リスト。"""
    allowed = set(trading_divisions)
    days = {
        str(row.get("calendar_date") or row.get("Date") or "")
        for row in calendar_rows
        if str(row.get("holiday_division") or row.get("HolDiv") or "") in allowed
    }
    return sorted(d for d in days if d)


def validate_divisions(
    calendar_rows: Sequence[Mapping],
    observed_trading_dates: Iterable[str],
    *,
    trading_divisions: Sequence[str] = DEFAULT_TRADING_DIVISIONS,
) -> CalendarValidation:
    """区分値の意味を**実データで検証**する。

    観測が存在する日（例: TOPIXに終値がある日）は必ず営業日のはずなので、
    その日のHolDivが `trading_divisions` に含まれるかを突き合わせる。
    1件でも食い違えば `validated=False`（＝カレンダーを信頼して使わない）。
    """
    allowed = set(trading_divisions)
    by_date: Dict[str, str] = {}
    counts: Dict[str, int] = {}
    for row in calendar_rows:
        day = str(row.get("calendar_date") or row.get("Date") or "")
        div = str(row.get("holiday_division") or row.get("HolDiv") or "")
        if day:
            by_date[day] = div
            counts[div] = counts.get(div, 0) + 1

    checked = 0
    agreements = 0
    disagreements: List[str] = []
    for day in sorted(set(observed_trading_dates)):
        if day not in by_date:
            continue                      # カレンダー範囲外は判定材料にしない
        checked += 1
        if by_date[day] in allowed:
            agreements += 1
        else:
            disagreements.append(f"{day}:HolDiv={by_date[day]}")
    return CalendarValidation(
        trading_divisions=tuple(trading_divisions), checked_dates=checked,
        agreements=agreements, disagreements=tuple(disagreements),
        observed_divisions=counts)


def latest_completed_session(
    calendar_rows: Sequence[Mapping],
    *,
    now: datetime,
    trading_divisions: Sequence[str] = DEFAULT_TRADING_DIVISIONS,
) -> Optional[str]:
    """`now`（JST基準の時刻を渡すこと）時点で**終了済み**の直近営業日を返す。

    当日が営業日でもクローズ前なら前営業日を返す（未確定のセッションを
    「完了した」と扱わない——FAIL-CLOSED）。判定できなければNone。
    """
    days = trading_days(calendar_rows, trading_divisions=trading_divisions)
    if not days:
        return None
    today = now.date().isoformat()
    closed_today = (now.hour, now.minute) >= (TOKYO_CLOSE_HOUR_JST,
                                              TOKYO_CLOSE_MINUTE_JST)
    completed = [d for d in days if d < today or (d == today and closed_today)]
    return completed[-1] if completed else None
