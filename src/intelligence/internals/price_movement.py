"""Price movement definition（Phase 3.5 §7）。

advance / decline の判定は **生終値（C）どうし**:

    current raw close  vs  previous trading-session raw close

- raw と adjusted を混同しない。比較は raw のみ、adjusted は corporate action の
  検知にだけ使う。
- corporate action: 当日の `adjustment_factor` が 1 でない、または raw と adjusted の
  騰落率が食い違う（分割・併合を跨いでいる）場合は**判定しない**
  （`corporate_action` として除外し件数を残す。誤った方向を数えない）。
- 前営業日に有効な終値が無い銘柄（新規上場・売買停止等）は `no_previous_close` として除外。
- 当日の終値が無い（出来ず等）銘柄は `no_close` として除外。
- 判定は「前営業日」限定（さらに前へ遡らない。定義を曖昧にしない）。
"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Dict, Mapping, Optional

PRICE_MOVEMENT_RULE = "price_movement"
QUANT = Decimal("0.000001")
#: raw騰落率と調整後騰落率の許容差（相対）。超えればcorporate actionを跨いだと判定
ADJUSTMENT_MISMATCH_TOLERANCE = Decimal("0.0001")

ADVANCE = "ADVANCE"
DECLINE = "DECLINE"
UNCHANGED = "UNCHANGED"
EXCLUDED = "EXCLUDED"

EXCL_NO_CLOSE = "no_close"
EXCL_NO_PREVIOUS = "no_previous_close"
EXCL_CORPORATE_ACTION = "corporate_action"
EXCL_INVALID = "invalid_price"


def _decimal(token) -> Optional[Decimal]:
    if token is None:
        return None
    text = str(token).strip()
    if not text:
        return None
    try:
        return Decimal(text)
    except (InvalidOperation, ValueError):
        return None


def _get(row: Mapping, key: str):
    try:
        return row[key]
    except (KeyError, IndexError):
        return None


@dataclass(frozen=True, kw_only=True)
class Movement:
    code: str
    security_id: str
    session_date: str
    previous_session: str
    close: Optional[Decimal]
    previous_close: Optional[Decimal]
    change_pct: Optional[Decimal]
    classification: str                  # ADVANCE / DECLINE / UNCHANGED / EXCLUDED
    exclusion_reason: str = ""
    record_id: str = ""
    previous_record_id: str = ""
    turnover_value: Optional[Decimal] = None
    volume: Optional[Decimal] = None
    market_cap: Optional[Decimal] = None

    @property
    def counted(self) -> bool:
        return self.classification in (ADVANCE, DECLINE, UNCHANGED)


def classify(current: Mapping, previous: Optional[Mapping], *, session_date: str,
             previous_session: str) -> Movement:
    """1銘柄の当日/前営業日recordから Movement を決める（決定論的）。"""
    code = str(_get(current, "code") or "")
    security_id = str(_get(current, "security_id") or f"jp:security:{code}")
    close = _decimal(_get(current, "close"))
    turnover = _decimal(_get(current, "turnover_value"))
    volume = _decimal(_get(current, "volume"))
    market_cap = _decimal(_get(current, "market_cap"))
    record_id = str(_get(current, "record_id") or "")
    base = dict(code=code, security_id=security_id, session_date=session_date,
                previous_session=previous_session, record_id=record_id,
                turnover_value=turnover, volume=volume, market_cap=market_cap)
    if close is None:
        return Movement(**base, close=None, previous_close=None, change_pct=None,
                        classification=EXCLUDED, exclusion_reason=EXCL_NO_CLOSE)
    if close <= 0:
        return Movement(**base, close=close, previous_close=None, change_pct=None,
                        classification=EXCLUDED, exclusion_reason=EXCL_INVALID)
    previous_close = _decimal(_get(previous, "close")) if previous is not None else None
    previous_record_id = str(_get(previous, "record_id") or "") if previous is not None else ""
    if previous_close is None or previous_close <= 0:
        return Movement(**base, close=close, previous_close=previous_close, change_pct=None,
                        classification=EXCLUDED, exclusion_reason=EXCL_NO_PREVIOUS,
                        previous_record_id=previous_record_id)
    # ---- corporate action guard（raw比較が成立しない日は判定しない）
    factor = _decimal(_get(current, "adjustment_factor"))
    if factor is not None and factor != 1:
        return Movement(**base, close=close, previous_close=previous_close, change_pct=None,
                        classification=EXCLUDED, exclusion_reason=EXCL_CORPORATE_ACTION,
                        previous_record_id=previous_record_id)
    adj_now = _decimal(_get(current, "adjusted_close"))
    adj_prev = _decimal(_get(previous, "adjusted_close")) if previous is not None else None
    if adj_now is not None and adj_prev not in (None, Decimal(0)) and adj_prev > 0:
        raw_ratio = close / previous_close
        adj_ratio = adj_now / adj_prev
        if abs(raw_ratio - adj_ratio) > ADJUSTMENT_MISMATCH_TOLERANCE * raw_ratio:
            return Movement(**base, close=close, previous_close=previous_close,
                            change_pct=None, classification=EXCLUDED,
                            exclusion_reason=EXCL_CORPORATE_ACTION,
                            previous_record_id=previous_record_id)
    change = ((close / previous_close) - Decimal(1)) * Decimal(100)
    change = change.quantize(QUANT)
    if close > previous_close:
        classification = ADVANCE
    elif close < previous_close:
        classification = DECLINE
    else:
        classification = UNCHANGED
    return Movement(**base, close=close, previous_close=previous_close, change_pct=change,
                    classification=classification, previous_record_id=previous_record_id)


def classify_session(current_rows: Mapping[str, Mapping], previous_rows: Mapping[str, Mapping],
                     codes, *, session_date: str, previous_session: str
                     ) -> Dict[str, Movement]:
    """universe codes について当日/前営業日のrecordを突き合わせる（無い銘柄は除外扱い）。"""
    out: Dict[str, Movement] = {}
    for code in codes:
        current = current_rows.get(code)
        previous = previous_rows.get(code)
        if current is None:
            out[code] = Movement(
                code=code, security_id=f"jp:security:{code}", session_date=session_date,
                previous_session=previous_session, close=None, previous_close=None,
                change_pct=None, classification=EXCLUDED, exclusion_reason=EXCL_NO_CLOSE)
            continue
        out[code] = classify(current, previous, session_date=session_date,
                             previous_session=previous_session)
    return out
