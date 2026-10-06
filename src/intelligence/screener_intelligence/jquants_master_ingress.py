"""P8-LIVE1 — master の応答の厳密な parse と、凍結 ID1 の**前**の適格（`ProdCat` の是正）。

LIVE0 の発見: 凍結 ID1 の入力は `ProdCat`（商品区分）を読まないので、`Mkt` と 5 桁目だけでは外国株券（021）・外国株預託証券（024）を
除外できない。監督の決定: ID1 を変えず、**ID1 の前**で決める。本 module は `ProdCat` を適格の事実として使い、決めた後に ID1 が受ける
5 欄の行（`MasterRow`）だけを渡す。raw の行 ・他の欄は保持しない。

方針（LIVE0 §5。enum を黙って広げない）:
- Code: 5 桁 ・数字 ・5 桁目 `0`（普通株。公式 FAQ）。形が違う → HOLD `CODE_MALFORMED`。5 桁目 ≠ `0` ／ 英字 → HOLD `CODE_NOT_COMMON_EQUITY`。
- Mkt: `0111` ／ `0112` ／ `0113` → 支える。`0105` ／ `0109` → HOLD。再編前の `0101` ／ `0102` ／ `0104` ／ `0106` ／ `0107`
  → HOLD（予期しない）。一覧に無い値 → HOLD `MARKET_UNKNOWN`。
- ProdCat: `011` → 支える（5 桁目 `0` と組で）。`012` ／ `013` ／ `014` ／ `021` ／ `022` ／ `023` ／ `024` → EXCLUDED。一覧に無い ・空 ・形が
  違う → HOLD。名前から種類を推定しない。

記録: `docs/databank/PHASE8_LIVE1_MEMORY_ONLY_CLIENT.md`。
"""
from __future__ import annotations

import json
import re
from typing import Any, Dict, List, Mapping, Tuple

from .identity_bootstrap_model import OFFICIAL_MASTER_FIELDS, BootstrapInputError, MasterRow
from .jquants_live_model import (LiveInputError, MasterEligibility, MasterEligibilityResult, MasterHoldReason,
                                 ordered_master_reasons)

#: 適格に要る欄（ID1 の 5 欄 ＋ `ProdCat`）
ELIGIBILITY_FIELDS: Tuple[str, ...] = ("Date", "Code", "CoName", "CoNameEn", "Mkt", "ProdCat")
SUPPORTED_MARKETS: Tuple[str, ...] = ("0111", "0112", "0113")
HOLD_MARKETS: Tuple[str, ...] = ("0105", "0109")
HISTORICAL_MARKETS: Tuple[str, ...] = ("0101", "0102", "0104", "0106", "0107")
SUPPORTED_PRODUCT_CATEGORIES: Tuple[str, ...] = ("011",)
EXCLUDED_PRODUCT_CATEGORIES: Tuple[str, ...] = ("012", "013", "014", "021", "022", "023", "024")
MAX_MASTER_ROWS = 10000
_CODE_RE = re.compile(r"^[0-9A-Z]{5}$")
_PRODUCT_CATEGORY_RE = re.compile(r"^[0-9]{3}$")
_TEXT_RE = re.compile(r"^[^\x00-\x1f\x7f]{0,120}$")


def _require(condition: bool, code: str, detail: str = "") -> None:
    if not condition:
        raise LiveInputError(code, detail)


def parse_master_payload(body: str) -> Tuple[Mapping[str, str], ...]:
    """応答の本文（memory の文字列）→ 行の Mapping の tuple。形が違えば code だけの error（本文を運ばない）。"""
    _require(isinstance(body, str), "PAYLOAD_NOT_TEXT", "body")
    try:
        data = json.loads(body)
    except ValueError:
        raise LiveInputError("PAYLOAD_NOT_JSON", "body") from None
    _require(isinstance(data, dict), "PAYLOAD_NOT_OBJECT", "body")
    _require(set(data) <= {"data", "pagination_key"}, "PAYLOAD_UNKNOWN_KEY", "body")
    rows = data.get("data")
    _require(isinstance(rows, list), "PAYLOAD_DATA_NOT_LIST", "data")
    _require(len(rows) <= MAX_MASTER_ROWS, "PAYLOAD_TOO_MANY_ROWS", "data")
    parsed: List[Mapping[str, str]] = []
    for row in rows:
        _require(isinstance(row, dict) and all(isinstance(k, str) for k in row), "ROW_NOT_OBJECT", "data")
        _require(set(row) <= set(OFFICIAL_MASTER_FIELDS), "ROW_UNKNOWN_FIELD", "data")
        parsed.append(row)
    return tuple(parsed)


def _text(row: Mapping[str, Any], name: str, reasons: List[MasterHoldReason]) -> str:
    """欄の文字列。無い → FIELD_MISSING（ProdCat は PRODUCT_CATEGORY_MISSING）、文字列でない ／ 境界の外 → FIELD_NOT_TEXT。"""
    if name not in row:
        reasons.append(MasterHoldReason.PRODUCT_CATEGORY_MISSING if name == "ProdCat"
                       else MasterHoldReason.FIELD_MISSING)
        return ""
    value = row[name]
    if not isinstance(value, str) or not _TEXT_RE.match(value):
        reasons.append(MasterHoldReason.FIELD_NOT_TEXT)
        return ""
    return value


def assess_master_row(row: Mapping[str, Any]) -> MasterEligibilityResult:
    """1 行の適格。ELIGIBLE_FOR_ID1 のときだけ凍結 ID1 の `MasterRow`（5 欄）を作って持つ。"""
    _require(isinstance(row, Mapping), "ROW_NOT_OBJECT", "row")
    reasons: List[MasterHoldReason] = []
    values = {name: _text(row, name, reasons) for name in ELIGIBILITY_FIELDS}
    code, market, category = values["Code"], values["Mkt"], values["ProdCat"]
    excluded = False
    if "Code" in row and isinstance(row["Code"], str):
        if not _CODE_RE.match(code):
            reasons.append(MasterHoldReason.CODE_MALFORMED)
        elif not code.isdigit() or code[4] != "0":
            reasons.append(MasterHoldReason.CODE_NOT_COMMON_EQUITY)
    if "Mkt" in row and isinstance(row["Mkt"], str):
        if market in HOLD_MARKETS:
            reasons.append(MasterHoldReason.MARKET_HOLD)
        elif market in HISTORICAL_MARKETS:
            reasons.append(MasterHoldReason.MARKET_HISTORICAL)
        elif market not in SUPPORTED_MARKETS:
            reasons.append(MasterHoldReason.MARKET_UNKNOWN)
    if "ProdCat" in row and isinstance(row["ProdCat"], str):
        if not _PRODUCT_CATEGORY_RE.match(category):
            reasons.append(MasterHoldReason.PRODUCT_CATEGORY_MALFORMED)          # 空 ・桁 ・英字（公式: 欠損なし）
        elif category in EXCLUDED_PRODUCT_CATEGORIES:
            reasons.append(MasterHoldReason.PRODUCT_CATEGORY_EXCLUDED)
            excluded = True
        elif category not in SUPPORTED_PRODUCT_CATEGORIES:
            reasons.append(MasterHoldReason.PRODUCT_CATEGORY_UNKNOWN)
    id1_row = None
    if not reasons:
        try:                                                                     # 決めた後に ID1 の 5 欄だけを作る
            id1_row = MasterRow.from_provider_mapping({name: values[name] for name in ELIGIBILITY_FIELDS
                                                       if name != "ProdCat"})
        except BootstrapInputError:
            reasons.append(MasterHoldReason.ID1_ROW_REJECTED)
    only_excluded = excluded and reasons == [MasterHoldReason.PRODUCT_CATEGORY_EXCLUDED]
    eligibility = MasterEligibility.ELIGIBLE_FOR_ID1 if not reasons else (
        MasterEligibility.EXCLUDED if only_excluded else MasterEligibility.HOLD)
    return MasterEligibilityResult(code=code, eligibility=eligibility, reasons=ordered_master_reasons(reasons),
                                   market=market, product_category=category, id1_row=id1_row)


def assess_master_payload(body: str) -> Tuple[MasterEligibilityResult, ...]:
    """応答の本文 → 行ごとの適格（入力の順）。raw は返さない。"""
    return tuple(assess_master_row(row) for row in parse_master_payload(body))


def id1_rows(results: Tuple[MasterEligibilityResult, ...]) -> Tuple[MasterRow, ...]:
    """ELIGIBLE_FOR_ID1 の行だけ、凍結 ID1 が受ける形（`MasterRow`）で。他は渡さない。"""
    _require(isinstance(results, tuple) and all(isinstance(r, MasterEligibilityResult) for r in results),
             "INVALID_RESULTS", "results")
    return tuple(r.id1_row for r in results if r.eligibility is MasterEligibility.ELIGIBLE_FOR_ID1)


def summarize(results: Tuple[MasterEligibilityResult, ...]) -> Dict[str, int]:
    counts: Dict[str, int] = {}
    for result in results:
        counts[result.eligibility.value] = counts.get(result.eligibility.value, 0) + 1
    return counts


__all__ = ["ELIGIBILITY_FIELDS", "EXCLUDED_PRODUCT_CATEGORIES", "HISTORICAL_MARKETS", "HOLD_MARKETS", "MAX_MASTER_ROWS",
           "SUPPORTED_MARKETS", "SUPPORTED_PRODUCT_CATEGORIES", "assess_master_payload", "assess_master_row",
           "id1_rows", "parse_master_payload", "summarize"]
