"""P1 ヘッダー表（固定 10 列）と P2 指数表からの EXTRACTED_VALUE（MARKET_DATA_TAXONOMY 準拠）。

値は **羅針盤が掲載した数値** であり market truth ではない（alignment.py で突き合わせる）。
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Dict, List, Optional, Sequence, Tuple

#: (key, change_kind)。change_kind: pct / deviation_pct / diff_trillion_yen / diff_pt / diff_yen
HEADER_COLUMNS: Tuple[Tuple[str, str], ...] = (
    ("nikkei225_close", "pct"),
    ("nikkei225_ma25", "deviation_pct"),
    ("topix_close", "pct"),
    ("prime_turnover_trillion_yen", "diff_trillion_yen"),
    ("dow_close", "pct"),
    ("sp500_close", "pct"),
    ("nasdaq_close", "pct"),
    ("jgb10y_yield", "diff_pt"),
    ("ust10y_yield", "diff_pt"),
    ("usd_jpy", "diff_yen"),
)

#: P2 その他指数 / V/G（level, 前日比%, 年初来%）
SECONDARY_ROWS: Tuple[Tuple[str, str], ...] = (
    ("ラッセル2000", "russell2000_close"),
    ("SOX", "sox_close"),
    ("VIX", "vix_close"),
    ("MOVE", "move_close"),
    ("TOPIXバリュー", "topix_value_close"),
    ("TOPIXグロース", "topix_growth_close"),
)

STATUS_COMPLETE = "COMPLETE"
STATUS_PARTIAL = "PARTIAL"
STATUS_MISSING = "MISSING"

_CLOSED = {"closed", "close"}
_NUM = re.compile(r"^[+\-]?[\d,]+(?:\.\d+)?%?$")


@dataclass(frozen=True)
class HeaderValue:
    key: str
    level: Optional[Decimal]
    change: Optional[Decimal]
    change_kind: str
    closed: bool
    page: int
    line_level: int         # 終値行の行番号（非空行、1-based）
    line_change: int

    def as_dict(self) -> Dict[str, object]:
        return {"key": self.key, "level": None if self.level is None else str(self.level),
                "change": None if self.change is None else str(self.change),
                "change_kind": self.change_kind, "closed": self.closed, "page": self.page,
                "line_level": self.line_level, "line_change": self.line_change}


def _to_decimal(token: str) -> Optional[Decimal]:
    t = token.strip().replace(",", "").rstrip("%")
    if not t or t.lower() in _CLOSED:
        return None
    try:
        return Decimal(t)
    except InvalidOperation:
        return None


def _tokens(line: str) -> List[str]:
    return [t for t in re.split(r"\s+", line.strip()) if t]


def parse_header_table(page1_text: str) -> Tuple[List[HeaderValue], str]:
    """「終値 …」「前日比 …」の 2 行（各 10 token）を列定義へ割り当てる。"""
    lines = [l.strip() for l in (page1_text or "").splitlines() if l.strip()]
    level_line = change_line = ""
    level_no = change_no = 0
    for no, line in enumerate(lines, start=1):
        if not level_line and line.startswith("終値"):
            level_line, level_no = line, no
        elif not change_line and line.startswith("前日比"):
            change_line, change_no = line, no
    if not level_line or not change_line:
        return [], STATUS_MISSING
    levels = _tokens(level_line)[1:]
    changes = _tokens(change_line)[1:]
    if len(levels) < len(HEADER_COLUMNS) or len(changes) < len(HEADER_COLUMNS):
        levels_status = STATUS_PARTIAL
    else:
        levels_status = STATUS_COMPLETE
    values: List[HeaderValue] = []
    for idx, (key, kind) in enumerate(HEADER_COLUMNS):
        lv = levels[idx] if idx < len(levels) else ""
        ch = changes[idx] if idx < len(changes) else ""
        closed = lv.lower() in _CLOSED or ch.lower() in _CLOSED
        values.append(HeaderValue(key=key, level=_to_decimal(lv), change=_to_decimal(ch),
                                  change_kind=kind, closed=closed, page=1,
                                  line_level=level_no, line_change=change_no))
    if levels_status == STATUS_COMPLETE and any(
            v.level is None and not v.closed for v in values):
        levels_status = STATUS_PARTIAL
    return values, levels_status


def parse_secondary_table(page2_text: str) -> List[HeaderValue]:
    """P2 の「ラッセル2000 2,917.98 -0.72 +17.57 TOPIXバリュー …」等の行から level / 前日比% を取る。"""
    lines = [l.strip() for l in (page2_text or "").splitlines() if l.strip()]
    out: List[HeaderValue] = []
    for no, line in enumerate(lines, start=1):
        toks = _tokens(line)
        i = 0
        while i < len(toks):
            name = toks[i]
            key = next((k for label, k in SECONDARY_ROWS if label == name), "")
            if not key:
                i += 1
                continue
            nxt = toks[i + 1] if i + 1 < len(toks) else ""
            if nxt.lower() in _CLOSED:
                out.append(HeaderValue(key=key, level=None, change=None, change_kind="pct",
                                       closed=True, page=2, line_level=no, line_change=no))
                i += 2
                continue
            level = _to_decimal(nxt) if _NUM.match(nxt or "") else None
            chg_tok = toks[i + 2] if i + 2 < len(toks) else ""
            change = _to_decimal(chg_tok) if _NUM.match(chg_tok or "") else None
            out.append(HeaderValue(key=key, level=level, change=change, change_kind="pct",
                                   closed=False, page=2, line_level=no, line_change=no))
            i += 4 if change is not None else 2
    return out


def value_map(values: Sequence[HeaderValue]) -> Dict[str, HeaderValue]:
    return {v.key: v for v in values}
