"""P12-A4 — 決定論の失敗の注入点（test だけが使う。本番の既定は何もしない ・乱数は無い）。

`InjectionPoints.fire(point)` は transaction の決まった境界で呼ばれる。test は `RaisingInjection({point: exc_type})` を渡し、その点で
例外を投げさせて process の死を模す。本番は `NO_INJECTION`（全て no-op）。点の名は `POINTS`（完全一致 ・未知の点は誤り）。
"""
from __future__ import annotations

from typing import Callable, Dict, Mapping, Optional, Tuple, Type

from .failure_codes import AutomationError

POINTS: Tuple[str, ...] = ("AFTER_LOCK_ACQUIRED", "AFTER_PLANNED_APPEND", "AFTER_RUNNING_APPEND", "BEFORE_EXECUTION",
                           "AFTER_FINALIZATION", "AFTER_TERMINAL_APPEND", "AFTER_CHECKPOINT", "BEFORE_STATUS_WRITE",
                           "AFTER_STATUS_WRITE", "BEFORE_LOCK_RELEASE")


class InjectionPoints:
    def fire(self, point: str) -> None:
        if point not in POINTS:
            raise AutomationError("SCHEMA_INVALID", "INJECTION_POINT")


class RaisingInjection(InjectionPoints):
    """test: 点 → 投げる例外の型（または呼ぶ関数）。"""

    def __init__(self, plan: Mapping[str, Callable[[], Optional[BaseException]]]) -> None:
        unknown = set(plan) - set(POINTS)
        if unknown:
            raise AutomationError("SCHEMA_INVALID", "INJECTION_POINT")
        self._plan: Dict[str, Callable[[], Optional[BaseException]]] = dict(plan)
        self.fired: list = []

    def fire(self, point: str) -> None:
        super().fire(point)
        self.fired.append(point)
        action = self._plan.get(point)
        if action is not None:
            raised = action()
            if isinstance(raised, BaseException):
                raise raised


def raise_type(exc_type: Type[BaseException]) -> Callable[[], Optional[BaseException]]:
    return lambda: exc_type()


NO_INJECTION = InjectionPoints()

__all__ = ["NO_INJECTION", "POINTS", "InjectionPoints", "RaisingInjection", "raise_type"]
