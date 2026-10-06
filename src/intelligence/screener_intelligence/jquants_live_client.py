"""P8-LIVE1 — memory だけの J-Quants 取り込み client（master → LIVE1 の適格 → ID1 へ、identity の後にだけ fins → ADP0 へ）。

順序（LIVE0 §7 ・§8）: master の取得 → LIVE1 の適格 → 凍結 ID1 の提案 → 人の審査（`accepted_at`）→ 凍結 ID2 の登録 → A1 の identity の
確認 → **その後だけ** fins の取得 ・handoff → 凍結 ADP0 → 凍結 EXE。財務の取り込みは identity の登録に先行できない: `fetch_fins_summary`
は凍結 A1 の履歴から作った `IdentityHandoff`（code → 有効な `JQUANTS_CODE` の割り当て → Security → Issuer）を要求する。

契約:
- 予算は caller が持つ `RequestBudget`。transport を呼ぶ**前**に消費。9 回目は transport に届かない。retry ・pagination の自動追随は無い
  （fins の `pagination_key` は返すだけ。次の request は caller が予算の中で明示に発する）。
- raw の応答は memory だけ。client は本文を保持せず、結果には bounded な型（`MasterEligibilityResult` ・凍結 ADP0 の
  `FinancialSummaryRow`）だけが入る。error は code だけ。
- credential は client に無い（transport の責任）。query に credential の key は入れない（model が拒む）。
- 実 network の transport は本 gate に無い。実の provider の host を呼ぶ code は本 package に無い。

記録: `docs/databank/PHASE8_LIVE1_MEMORY_ONLY_CLIENT.md`。
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any, Dict, List, Tuple

from .identity_model import IdentifierScheme, IdentityHistory, is_issuer_id, is_security_id
from .jquants_adapter_model import AdapterInputError, FinancialSummaryRow
from .jquants_live_model import (FINS_SUMMARY_PATH, LIVE_RULES_VERSION, MASTER_PATH, LiveInputError,
                                 MasterEligibilityResult, RequestBudget, Transport, TransportResponse)
from .jquants_master_ingress import assess_master_payload

_DATE_RE = re.compile(r"^[0-9]{4}-[0-9]{2}-[0-9]{2}$")
_CODE_RE = re.compile(r"^[0-9A-Z]{5}$")
_PAGINATION_RE = re.compile(r"^[A-Za-z0-9._:-]{1,128}$")
MAX_FINS_ROWS = 2000


def _require(condition: bool, code: str, detail: str = "") -> None:
    if not condition:
        raise LiveInputError(code, detail)


@dataclass(frozen=True, kw_only=True)
class MasterFetch:
    """master の取得の結果（bounded）。raw は無い。"""

    snapshot_date: str
    results: Tuple[MasterEligibilityResult, ...]
    request_index: int
    rules_version: str = LIVE_RULES_VERSION

    def as_dict(self) -> Dict[str, Any]:
        return {"request_index": self.request_index, "results": [r.as_dict() for r in self.results],
                "rules_version": self.rules_version, "snapshot_date": self.snapshot_date}


@dataclass(frozen=True, kw_only=True)
class IdentityHandoff:
    """fins の取得の前提: 凍結 A1 の履歴で code が有効な Security → Issuer に解けたこと。`verify_identity_for_code` で作る。"""

    code: str
    security_id: str
    issuer_id: str

    def __post_init__(self) -> None:
        _require(isinstance(self.code, str) and bool(_CODE_RE.match(self.code)), "INVALID_HANDOFF", "code")
        _require(is_security_id(self.security_id) and is_issuer_id(self.issuer_id), "INVALID_HANDOFF", "ids")


def verify_identity_for_code(history: Any, code: str) -> IdentityHandoff:
    """凍結 A1 の履歴（検証済み）で code → 有効な `JQUANTS_CODE` の割り当て → Security → Issuer を確かめる。無ければ拒む（登録しない）。"""
    _require(isinstance(history, IdentityHistory), "INVALID_HISTORY", "history")
    _require(isinstance(code, str) and bool(_CODE_RE.match(code)), "INVALID_CODE", "code")
    matches = [assignment for rid, assignment in history.assignments.items()
               if assignment.scheme is IdentifierScheme.JQUANTS_CODE and assignment.value == code
               and rid not in history.retirements]
    _require(len(matches) != 0, "IDENTITY_NOT_REGISTERED", "code")
    _require(len(matches) == 1, "IDENTITY_AMBIGUOUS", "code")
    security = history.securities.get(matches[0].security_id)
    _require(security is not None, "IDENTITY_NOT_REGISTERED", "security_id")
    _require(security.issuer_id in history.issuers, "IDENTITY_NOT_REGISTERED", "issuer_id")
    return IdentityHandoff(code=code, security_id=security.security_id, issuer_id=security.issuer_id)


@dataclass(frozen=True, kw_only=True)
class FinsHandoff:
    """fins の取得の結果: 凍結 ADP0 が受ける行（14 欄）だけ ＋ 次の page の key（自動で追わない）。raw は無い。"""

    identity: IdentityHandoff
    rows: Tuple[FinancialSummaryRow, ...]
    pagination_key: str
    request_index: int
    rules_version: str = LIVE_RULES_VERSION

    def as_dict(self) -> Dict[str, Any]:
        return {"code": self.identity.code, "issuer_id": self.identity.issuer_id,
                "pagination_key_present": self.pagination_key != "", "request_index": self.request_index,
                "row_count": len(self.rows), "rules_version": self.rules_version}


def parse_fins_summary_payload(body: str, code: str) -> Tuple[Tuple[FinancialSummaryRow, ...], str]:
    """応答の本文 → 凍結 ADP0 の `FinancialSummaryRow` の tuple ＋ pagination key。code が違う行 ・形の違いは拒む（code だけの error）。"""
    _require(isinstance(body, str), "PAYLOAD_NOT_TEXT", "body")
    try:
        data = json.loads(body)
    except ValueError:
        raise LiveInputError("PAYLOAD_NOT_JSON", "body") from None
    _require(isinstance(data, dict) and set(data) <= {"data", "pagination_key"}, "PAYLOAD_UNKNOWN_KEY", "body")
    rows = data.get("data")
    _require(isinstance(rows, list) and len(rows) <= MAX_FINS_ROWS, "PAYLOAD_DATA_NOT_LIST", "data")
    pagination = data.get("pagination_key", "")
    _require(isinstance(pagination, str) and (pagination == "" or bool(_PAGINATION_RE.match(pagination))),
             "INVALID_PAGINATION_KEY", "pagination_key")
    parsed: List[FinancialSummaryRow] = []
    for row in rows:
        _require(isinstance(row, dict), "ROW_NOT_OBJECT", "data")
        try:
            record = FinancialSummaryRow.from_provider_mapping(row)                # 14 欄だけ。他の 97 欄は捨てる
        except AdapterInputError as exc:
            raise LiveInputError("FINS_ROW_REJECTED", exc.code) from None
        _require(record.Code == code, "FINS_ROW_CODE_MISMATCH", "Code")
        parsed.append(record)
    return tuple(parsed), pagination


class JQuantsLiveClient:
    """memory だけの client。transport と予算は caller が渡す。credential ・URL ・raw を持たない。"""

    def __init__(self, transport: Any, budget: Any) -> None:
        _require(isinstance(transport, Transport), "INVALID_TRANSPORT", "transport")
        _require(isinstance(budget, RequestBudget), "INVALID_BUDGET", "budget")
        self._transport = transport
        self._budget = budget

    @property
    def budget(self) -> RequestBudget:
        return self._budget

    def _get(self, path: str, params: Dict[str, str]) -> Tuple[TransportResponse, int]:
        index = self._budget.reserve(path)                                       # transport の前に予算を消費
        response = self._transport.get(path, params)
        _require(isinstance(response, TransportResponse), "INVALID_TRANSPORT_RESPONSE", "response")
        _require(response.status == 200, f"HTTP_STATUS_{response.status}" if 100 <= response.status <= 599
                 else "HTTP_STATUS_INVALID", "status")
        return response, index

    def fetch_master(self, snapshot_date: str) -> MasterFetch:
        """`/v2/equities/master?date=D0` → 行ごとの適格（raw は捨てる）。"""
        _require(isinstance(snapshot_date, str) and bool(_DATE_RE.match(snapshot_date)), "INVALID_DATE", "date")
        response, index = self._get(MASTER_PATH, {"date": snapshot_date})
        results = assess_master_payload(response.body)
        return MasterFetch(snapshot_date=snapshot_date, results=results, request_index=index)

    def fetch_fins_summary(self, identity: Any, pagination_key: str = "") -> FinsHandoff:
        """`/v2/fins/summary?code=<Code>` → 凍結 ADP0 の行。identity の handoff（A1 で確かめた）が無ければ発しない。"""
        _require(isinstance(identity, IdentityHandoff), "IDENTITY_HANDOFF_REQUIRED", "identity")
        _require(isinstance(pagination_key, str)
                 and (pagination_key == "" or bool(_PAGINATION_RE.match(pagination_key))),
                 "INVALID_PAGINATION_KEY", "pagination_key")
        params = {"code": identity.code}
        if pagination_key:
            params["pagination_key"] = pagination_key
        response, index = self._get(FINS_SUMMARY_PATH, params)
        rows, next_key = parse_fins_summary_payload(response.body, identity.code)
        return FinsHandoff(identity=identity, rows=rows, pagination_key=next_key, request_index=index)


__all__ = ["MAX_FINS_ROWS", "FinsHandoff", "IdentityHandoff", "JQuantsLiveClient", "MasterFetch",
           "parse_fins_summary_payload", "verify_identity_for_code"]
