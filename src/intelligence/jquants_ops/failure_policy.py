"""Failure / retry policy（Phase 3.6 §20 / §21）。

失敗を統制語彙で区別し、Morning Compass が **正常継続 / DEGRADED / ABSTAIN** のどれかを
判定できる情報を返す。retry は **bounded**（回数・待機とも上限）。
auth / entitlement / schema の失敗は retry しない（retry storm を起こさない）。
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Dict, List, Optional, Sequence, Tuple

from ..market.jquants_v2 import CAUSE_API_VERSION_MISMATCH, CAUSE_PLAN_NOT_ENTITLED
from .registry import ROLE_INTERNALS, ROLE_NONE, ROLE_OPTIONAL, ROLE_REQUIRED

AUTH_FAILURE = "AUTH_FAILURE"
NOT_ENTITLED = "NOT_ENTITLED"
RATE_LIMIT = "RATE_LIMIT"
TIMEOUT = "TIMEOUT"
HTTP_ERROR = "HTTP_ERROR"
SCHEMA_CHANGE = "SCHEMA_CHANGE"
EMPTY_RESPONSE = "EMPTY_RESPONSE"
PARTIAL_DATA = "PARTIAL_DATA"
SESSION_GAP = "SESSION_GAP"
NO_CREDENTIALS = "NO_CREDENTIALS"
OK = "OK"
FAILURE_KINDS = (AUTH_FAILURE, NOT_ENTITLED, RATE_LIMIT, TIMEOUT, HTTP_ERROR, SCHEMA_CHANGE,
                 EMPTY_RESPONSE, PARTIAL_DATA, SESSION_GAP, NO_CREDENTIALS)

#: retry してよい失敗（一時的なもの）。それ以外は retry しない
RETRYABLE = frozenset({RATE_LIMIT, TIMEOUT, HTTP_ERROR})
NEVER_RETRY = frozenset({AUTH_FAILURE, NOT_ENTITLED, SCHEMA_CHANGE, NO_CREDENTIALS})

CONTINUE = "CONTINUE"
DEGRADED = "DEGRADED"
ABSTAIN = "ABSTAIN"


def classify_failure(*, ok: bool, http: int, error_kind: str = "", failure_cause: str = "",
                     rows: int = 0, expected_rows_min: int = 0, error_detail: str = "") -> str:
    """fetch 結果 → failure kind（推測せず、status / error_kind / cause から決める）。"""
    if ok:
        if rows == 0:
            return EMPTY_RESPONSE
        if expected_rows_min and rows < expected_rows_min:
            return PARTIAL_DATA
        return OK
    if error_kind == "no_credentials":
        return NO_CREDENTIALS
    if failure_cause == CAUSE_PLAN_NOT_ENTITLED:
        return NOT_ENTITLED
    if error_kind == "auth_error" or http in (401, 403) or failure_cause == CAUSE_API_VERSION_MISMATCH:
        return AUTH_FAILURE
    if http == 429:
        return RATE_LIMIT
    if error_kind == "connection" and ("timeout" in error_detail.lower()
                                       or "timed out" in error_detail.lower()):
        return TIMEOUT
    if error_kind in ("schema_error", "parse_error"):
        return SCHEMA_CHANGE
    if error_kind == "connection":
        return TIMEOUT if not http else HTTP_ERROR
    return HTTP_ERROR


def morning_impact(role: str, failure: str) -> str:
    """dataset の morning_role × failure → Compass の継続判定。"""
    if failure == OK:
        return CONTINUE
    if role == ROLE_REQUIRED:
        return ABSTAIN
    if role == ROLE_INTERNALS:
        return DEGRADED
    if role == ROLE_OPTIONAL:
        return DEGRADED if failure in (SESSION_GAP, PARTIAL_DATA) else CONTINUE
    return CONTINUE


@dataclass(frozen=True)
class RetryPolicy:
    max_attempts: int = 2
    backoff_seconds: Tuple[int, ...] = (2, 4)

    def as_dict(self) -> Dict[str, object]:
        return {"max_attempts": self.max_attempts, "backoff_seconds": list(self.backoff_seconds),
                "retryable": sorted(RETRYABLE), "never_retry": sorted(NEVER_RETRY),
                "rule": "bounded retry only; no retry storm on auth/entitlement/schema"}


@dataclass
class AttemptLog:
    attempts: List[Dict[str, object]]

    def as_dict(self) -> Dict[str, object]:
        return {"attempts": list(self.attempts), "count": len(self.attempts)}


def fetch_with_retry(fetch: Callable[[], object], *, policy: RetryPolicy,
                     sleeper: Callable[[float], None], expected_rows_min: int = 0,
                     classify: Optional[Callable[[object], str]] = None
                     ) -> Tuple[object, str, AttemptLog]:
    """`fetch()` を bounded retry で実行する。戻り値: (outcome, failure_kind, log)。

    `fetch` は ok / http / error_kind / error_detail / rows を持つ outcome を返すこと。
    """
    log = AttemptLog(attempts=[])
    outcome = None
    kind = HTTP_ERROR
    for attempt in range(1, policy.max_attempts + 1):
        outcome = fetch()
        kind = classify(outcome) if classify else classify_failure(
            ok=getattr(outcome, "ok", False), http=getattr(outcome, "http", 0),
            error_kind=getattr(outcome, "error_kind", ""),
            failure_cause=getattr(outcome, "failure_cause", ""),
            rows=getattr(outcome, "rows", 0), expected_rows_min=expected_rows_min,
            error_detail=getattr(outcome, "error_detail", ""))
        log.attempts.append({"attempt": attempt, "failure": kind,
                             "http": getattr(outcome, "http", 0)})
        if kind == OK or kind not in RETRYABLE or attempt >= policy.max_attempts:
            break
        wait = policy.backoff_seconds[min(attempt - 1, len(policy.backoff_seconds) - 1)] \
            if policy.backoff_seconds else 0
        sleeper(float(wait))
    return outcome, kind, log
