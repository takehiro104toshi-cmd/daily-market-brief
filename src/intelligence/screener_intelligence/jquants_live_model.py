"""P8-LIVE1 — memory だけの J-Quants 取り込み client の model（request の予算 ・transport の抽象 ・合成 transport ・閉じた error）。

規約の authority は凍結の P8-LIVE0（private の pilot だけ ・公開なし ・raw は memory だけ ・LLM に payload を入れない）。本 module はそれを
runtime の形で守る:
- **raw の payload は process の memory だけ**。model は raw を保持せず、error は code と field 名だけを運ぶ（本文 ・URL ・header は入れない）。
- **credential は model に無い**。API key は transport の実装（本 gate には無い）が持つ。model ・client ・error ・metadata に key は現れない。
- **request の予算は caller が持つ**（`RequestBudget`）。PILOT の上限は 8。予算は transport を呼ぶ**前**に消費し、尽きれば `BUDGET_EXHAUSTED`
  で拒む。暗黙の reset ・隠れた retry ・背景の呼び出しは無い。
- **transport の抽象**（`Transport`）: `get(path, params) -> TransportResponse`。本 gate の実装は決定論の
  `SyntheticTransport`（合成の応答）だけ。実 network の実装は LIVE1 に**無く**、PILOT2 の承認の後の gate で足す。
  実の provider の host を呼ぶ code は本 package に無い。

記録: `docs/databank/PHASE8_LIVE1_MEMORY_ONLY_CLIENT.md`。
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, Mapping, Optional, Tuple

from .jquants_adapter_model import DERIVED_NON_AUTHORITY_NON_PERSISTENT

LIVE_RULES_VERSION = "p8_jquants_live:0.1.0"
#: PILOT2 の request の上限（LIVE0 §8。1 predicate: master 1 ＋ fins 発行体ごと 1〜2 ＋ 予備）
PILOT_MAX_REQUESTS = 8
MASTER_PATH = "/v2/equities/master"
FINS_SUMMARY_PATH = "/v2/fins/summary"
#: client が発してよい path（他は拒む）
ALLOWED_PATHS: Tuple[str, ...] = (MASTER_PATH, FINS_SUMMARY_PATH)
#: query に入れてよい key（credential の key ・header は入れない）
ALLOWED_QUERY_KEYS: Tuple[str, ...] = ("code", "date", "pagination_key")
_CODE_CHARS = "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_"
_DETAIL_CHARS = _CODE_CHARS + "abcdefghijklmnopqrstuvwxyz"
_QUERY_VALUE_RE = re.compile(r"^[A-Za-z0-9._:-]{1,128}$")
_CREDENTIAL_KEYS = ("x-api-key", "api_key", "apikey", "authorization", "token", "secret", "password", "bearer")


class LiveInputError(ValueError):
    """入力 ・応答 ・予算の契約の違反（fail closed）。code と field 名だけ（payload ・URL ・header ・credential は運ばない）。"""

    def __init__(self, code: str, detail: str = "") -> None:
        _check_code(code)
        _check_code(detail, allow_empty=True, chars=_DETAIL_CHARS)
        super().__init__(f"{code}: {detail}" if detail else code)
        self.code = code
        self.detail = detail


def _check_code(value: Any, allow_empty: bool = False, chars: str = _CODE_CHARS) -> str:
    """code ・field 名だけ（payload ・URL ・header の文字は通らない）。"""
    if not (isinstance(value, str) and len(value) <= 64 and all(c in chars for c in value)
            and (allow_empty or value != "")):
        raise ValueError("INVALID_CODE")
    return value


def _require(condition: bool, code: str, detail: str = "") -> None:
    if not condition:
        raise LiveInputError(code, detail)


class BudgetExhausted(LiveInputError):
    """予算が尽きた（transport を呼ぶ前に拒む）。"""


# ---------------------------------------------------------------- request の予算（caller が持つ）


class RequestBudget:
    """caller が持つ request の予算。`reserve()` は transport の呼び出しの**前**に 1 消費し、尽きれば `BudgetExhausted`。reset は無い。"""

    def __init__(self, limit: int = PILOT_MAX_REQUESTS) -> None:
        if type(limit) is not int or limit < 1 or limit > PILOT_MAX_REQUESTS:
            raise LiveInputError("INVALID_BUDGET", "limit")
        self._limit = limit
        self._used = 0
        self._paths: Tuple[str, ...] = ()

    @property
    def limit(self) -> int:
        return self._limit

    @property
    def used(self) -> int:
        return self._used

    @property
    def remaining(self) -> int:
        return self._limit - self._used

    @property
    def paths(self) -> Tuple[str, ...]:
        """発した request の path（順）。query ・credential ・host は含まない。"""
        return self._paths

    def reserve(self, path: str) -> int:
        _require(path in ALLOWED_PATHS, "PATH_NOT_ALLOWED", "path")
        if self._used >= self._limit:
            raise BudgetExhausted("BUDGET_EXHAUSTED", "limit")
        self._used += 1
        self._paths = self._paths + (path,)
        return self._used

    def as_dict(self) -> Dict[str, Any]:
        return {"limit": self._limit, "paths": list(self._paths), "remaining": self.remaining, "used": self._used}


# ---------------------------------------------------------------- transport（抽象 ・合成）


@dataclass(frozen=True)
class TransportResponse:
    """transport の応答（status と本文の文字列）。本文は memory だけ。`as_dict` ・`repr` に本文を出さない。"""

    status: int
    body: str = field(repr=False)

    def __post_init__(self) -> None:
        if type(self.status) is not int or not isinstance(self.body, str):
            raise LiveInputError("INVALID_TRANSPORT_RESPONSE", "response")

    def __repr__(self) -> str:                                                   # 本文を出さない
        return f"TransportResponse(status={self.status}, body_length={len(self.body)})"


def canonical_query(params: Mapping[str, str]) -> Tuple[Tuple[str, str], ...]:
    """query の正準の形（key の整列）。許した key ・値の形だけ。credential の key は拒む。"""
    _require(isinstance(params, Mapping), "INVALID_QUERY", "params")
    items = []
    for key, value in params.items():
        _require(isinstance(key, str) and key.lower() not in _CREDENTIAL_KEYS, "CREDENTIAL_IN_QUERY", "params")
        _require(key in ALLOWED_QUERY_KEYS, "QUERY_KEY_NOT_ALLOWED", "params")
        _require(isinstance(value, str) and bool(_QUERY_VALUE_RE.match(value)), "INVALID_QUERY_VALUE", key)
        items.append((key, value))
    return tuple(sorted(items))


class Transport:
    """transport の抽象。`get(path, params)` だけ。credential の扱いは実装の責任で、model ・client には現れない。"""

    def get(self, path: str, params: Mapping[str, str]) -> TransportResponse:
        raise NotImplementedError


class SyntheticTransport(Transport):
    """決定論の合成 transport（test ・dry run）。`(path, 正準の query)` → 応答。無い組は `SYNTHETIC_RESPONSE_MISSING`。network は無い。"""

    def __init__(self, responses: Mapping[Tuple[str, Tuple[Tuple[str, str], ...]], TransportResponse]) -> None:
        _require(isinstance(responses, Mapping), "INVALID_SYNTHETIC_RESPONSES", "responses")
        for (path, query), response in responses.items():
            _require(path in ALLOWED_PATHS and isinstance(query, tuple) and isinstance(response, TransportResponse),
                     "INVALID_SYNTHETIC_RESPONSES", "entry")
        self._responses = dict(responses)
        self._calls: Tuple[Tuple[str, Tuple[Tuple[str, str], ...]], ...] = ()

    @property
    def calls(self) -> Tuple[Tuple[str, Tuple[Tuple[str, str], ...]], ...]:
        return self._calls

    def get(self, path: str, params: Mapping[str, str]) -> TransportResponse:
        key = (path, canonical_query(params))
        self._calls = self._calls + (key,)
        response = self._responses.get(key)
        _require(response is not None, "SYNTHETIC_RESPONSE_MISSING", "path")
        return response


# ---------------------------------------------------------------- master の適格（ID1 の前）


class MasterEligibility(str, Enum):
    ELIGIBLE_FOR_ID1 = "ELIGIBLE_FOR_ID1"
    HOLD = "HOLD"
    EXCLUDED = "EXCLUDED"


class MasterHoldReason(str, Enum):
    FIELD_MISSING = "FIELD_MISSING"
    FIELD_NOT_TEXT = "FIELD_NOT_TEXT"
    CODE_MALFORMED = "CODE_MALFORMED"
    CODE_NOT_COMMON_EQUITY = "CODE_NOT_COMMON_EQUITY"
    MARKET_HOLD = "MARKET_HOLD"
    MARKET_HISTORICAL = "MARKET_HISTORICAL"
    MARKET_UNKNOWN = "MARKET_UNKNOWN"
    PRODUCT_CATEGORY_EXCLUDED = "PRODUCT_CATEGORY_EXCLUDED"
    PRODUCT_CATEGORY_UNKNOWN = "PRODUCT_CATEGORY_UNKNOWN"
    PRODUCT_CATEGORY_MISSING = "PRODUCT_CATEGORY_MISSING"
    PRODUCT_CATEGORY_MALFORMED = "PRODUCT_CATEGORY_MALFORMED"
    ID1_ROW_REJECTED = "ID1_ROW_REJECTED"


_REASON_ORDER = {reason: index for index, reason in enumerate(MasterHoldReason)}


def ordered_master_reasons(reasons: Any) -> Tuple[MasterHoldReason, ...]:
    _require(isinstance(reasons, (tuple, list)) and all(isinstance(r, MasterHoldReason) for r in reasons),
             "INVALID_REASONS", "reasons")
    return tuple(sorted(set(reasons), key=_REASON_ORDER.__getitem__))


@dataclass(frozen=True, kw_only=True)
class MasterEligibilityResult:
    """1 行の適格の結果。ELIGIBLE のときだけ凍結 ID1 の行（5 欄）を持つ。raw の行 ・他の欄は持たない。"""

    code: str
    eligibility: MasterEligibility
    reasons: Tuple[MasterHoldReason, ...]
    market: str
    product_category: str
    id1_row: Optional[Any] = None
    rules_version: str = LIVE_RULES_VERSION
    authority_class: str = DERIVED_NON_AUTHORITY_NON_PERSISTENT

    def __post_init__(self) -> None:
        _require(isinstance(self.code, str) and isinstance(self.market, str) and isinstance(self.product_category, str),
                 "INVALID_RESULT", "text")
        _require(isinstance(self.eligibility, MasterEligibility), "INVALID_RESULT", "eligibility")
        _require(self.reasons == ordered_master_reasons(self.reasons), "INVALID_RESULT", "reasons")
        if self.eligibility is MasterEligibility.ELIGIBLE_FOR_ID1:
            _require(self.reasons == () and self.id1_row is not None, "INVALID_RESULT", "eligible")
        else:
            _require(self.reasons != () and self.id1_row is None, "INVALID_RESULT", "held")

    def as_dict(self) -> Dict[str, Any]:
        return {"authority_class": self.authority_class, "code": self.code, "eligibility": self.eligibility.value,
                "market": self.market, "product_category": self.product_category,
                "reasons": [r.value for r in self.reasons], "rules_version": self.rules_version}


__all__ = ["ALLOWED_PATHS", "ALLOWED_QUERY_KEYS", "FINS_SUMMARY_PATH", "LIVE_RULES_VERSION", "MASTER_PATH",
           "PILOT_MAX_REQUESTS", "BudgetExhausted", "LiveInputError", "MasterEligibility", "MasterEligibilityResult",
           "MasterHoldReason", "RequestBudget", "SyntheticTransport", "Transport", "TransportResponse",
           "canonical_query", "ordered_master_reasons"]
