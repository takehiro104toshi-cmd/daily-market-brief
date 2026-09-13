"""過去Compassとの整合チェック（Phase 3-B STEP 30）。

既存の履歴レポート（`output/history/<date>/pre_market.html`）に載っている
**客観的に比較できる数値**の符号と、Context Engineが同じ朝に生成した
`direction` を突き合わせ、`MATCH / PARTIAL / CONFLICT / NOT_AVAILABLE` を報告する。

重要な原則（監督者指示）:
- **人間が書いたCompassの文章を再現するようにruleを最適化しない**。
  ここは「観測」であって「最適化目標」ではない。
- 比較するのは**方向（符号）だけ**。履歴レポートの数値はレガシー収集経路
  （yfinance等）由来で、Market Data Bank（公式ソース）とは取得経路が異なるため、
  大きさの一致を要求しない。
- 比較できない次元（履歴に無い / Contextが無い）は `NOT_AVAILABLE` と正直に報告し、
  一致率の分母から外す。

履歴HTMLは**読み取り専用**（既存レポート生成・GitHub Pagesには一切触れない）。
"""
from __future__ import annotations

import html
import re
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Dict, List, Mapping, Optional, Sequence, Tuple

from .builders import (
    FX_DIRECTION,
    INDEX_DIRECTION,
    NIKKEI,
    RATE_DIRECTION,
    USDJPY,
    UST10Y,
)
from .model import CompassContextSnapshot, ContextItem, Direction

#: config.yaml の既存キー（report_schedule.history_dir）。パスを直書きしない。
CONFIG_SECTION = "report_schedule"
CONFIG_KEY = "history_dir"
DEFAULT_HISTORY_DIR = Path("output") / "history"
#: 比較に使う履歴レポートのスロット（寄り前＝朝のCompass）
SLOT_FILE = "pre_market.html"

#: 履歴レポート内の「前日比サマリー」行のラベル → 比較次元
#: （ラベル直後にコロンが続く表記だけを拾う＝本文中の言及を誤って拾わない）
_NUMERIC_PATTERN = re.compile(
    r"(日経平均|ドル円|米10年金利)\s*[:：]\s*([+-]?\d+(?:\.\d+)?)\s*%")

#: 比較次元 → (履歴ラベル, Contextの (context_type, subject_id))
COMPARABLE_DIMENSIONS: Mapping[str, Tuple[str, Tuple[str, str]]] = {
    "nikkei_direction": ("日経平均", (INDEX_DIRECTION, NIKKEI)),
    "usd_jpy": ("ドル円", (FX_DIRECTION, USDJPY)),
    "us_rates_10y": ("米10年金利", (RATE_DIRECTION, UST10Y)),
}

MATCH = "MATCH"
PARTIAL = "PARTIAL"
CONFLICT = "CONFLICT"
NOT_AVAILABLE = "NOT_AVAILABLE"


def history_dir(config_path: Path = Path("config.yaml")) -> Path:
    """履歴HTMLの保存先（config.yaml優先。読めなければ既定値）。"""
    try:
        import yaml  # 既存依存（PyYAML）

        config = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
        value = (config.get(CONFIG_SECTION) or {}).get(CONFIG_KEY)
        return Path(str(value)) if value else DEFAULT_HISTORY_DIR
    except Exception:  # noqa: BLE001 設定破損でチェックを止めない
        return DEFAULT_HISTORY_DIR


def parse_pre_market_numerics(path: Path) -> Dict[str, Decimal]:
    """履歴レポートから前日比（%）を抽出する。最初の出現のみを採用する。"""
    if not path.is_file():
        return {}
    text = html.unescape(re.sub(r"<[^>]+>", "\n", path.read_text(encoding="utf-8")))
    found: Dict[str, Decimal] = {}
    for label, token in _NUMERIC_PATTERN.findall(text):
        if label in found:
            continue
        try:
            found[label] = Decimal(token)
        except InvalidOperation:      # 数値として読めないものは採用しない
            continue
    return found


def _reported_direction(dimension: str, value: Decimal) -> Direction:
    """履歴レポートの符号 → 統制語彙。**符号のみ**を使う。"""
    if value == 0:
        return Direction.FLAT
    if dimension == "usd_jpy":
        # USDJPYの上昇 = 円安（Context側と同じ写像を使う）
        return Direction.WEAKER if value > 0 else Direction.STRONGER
    return Direction.UP if value > 0 else Direction.DOWN


def _verdict(reported: Direction, produced: Optional[Direction]) -> str:
    if produced is None or produced is Direction.UNKNOWN:
        return NOT_AVAILABLE
    if reported is produced:
        return MATCH
    if Direction.FLAT in (reported, produced):
        return PARTIAL              # 片方だけ「変化なし」＝部分一致
    return CONFLICT


def _item_for(items: Sequence[ContextItem],
              key: Tuple[str, str]) -> Optional[ContextItem]:
    context_type, subject_id = key
    candidates = [i for i in items
                  if i.context_type == context_type
                  and i.subject.subject_id == subject_id]
    if not candidates:
        return None
    # 最新sessionを採る（朝時点で利用できた最新のクローズ）
    return max(candidates, key=lambda i: i.time.session_date)


@dataclass(frozen=True)
class AlignmentResult:
    session_date: str
    report_path: str
    dimensions: Mapping[str, Dict[str, str]]

    def counts(self) -> Dict[str, int]:
        out = {MATCH: 0, PARTIAL: 0, CONFLICT: 0, NOT_AVAILABLE: 0}
        for row in self.dimensions.values():
            out[row["verdict"]] = out.get(row["verdict"], 0) + 1
        return out

    def as_dict(self) -> Dict[str, object]:
        return {"session_date": self.session_date, "report": self.report_path,
                "dimensions": {k: dict(v) for k, v in self.dimensions.items()},
                "counts": self.counts()}


def align_snapshot(snapshot: CompassContextSnapshot, *,
                   base_dir: Optional[Path] = None) -> AlignmentResult:
    """`snapshot.session_date` の朝の履歴レポートとContextの方向を突き合わせる。"""
    root = Path(base_dir) if base_dir is not None else history_dir()
    path = root / snapshot.session_date / SLOT_FILE
    numerics = parse_pre_market_numerics(path)
    rows: Dict[str, Dict[str, str]] = {}
    for dimension, (label, key) in COMPARABLE_DIMENSIONS.items():
        reported_value = numerics.get(label)
        item = _item_for(snapshot.items, key)
        produced = item.direction if item is not None else None
        if reported_value is None:
            rows[dimension] = {
                "verdict": NOT_AVAILABLE, "reason": "report_value_not_found",
                "label": label, "reported_pct": "",
                "reported_direction": "",
                "context_direction": produced.value if produced else "",
                "context_session": item.time.session_date if item else "",
                "context_id": item.context_id if item else ""}
            continue
        reported = _reported_direction(dimension, reported_value)
        verdict = _verdict(reported, produced)
        rows[dimension] = {
            "verdict": verdict,
            "reason": "" if item is not None else "context_not_generated",
            "label": label, "reported_pct": str(reported_value),
            "reported_direction": reported.value,
            "context_direction": produced.value if produced else "",
            "context_magnitude": (str(item.magnitude)
                                  if item is not None and item.magnitude is not None
                                  else ""),
            "context_session": item.time.session_date if item else "",
            "context_id": item.context_id if item else ""}
    return AlignmentResult(session_date=snapshot.session_date,
                           report_path=str(path), dimensions=rows)


def summarize(results: Sequence[AlignmentResult]) -> Dict[str, object]:
    """複数日の結果をまとめる。**比較可能な次元だけ**を分母にする。"""
    totals = {MATCH: 0, PARTIAL: 0, CONFLICT: 0, NOT_AVAILABLE: 0}
    for result in results:
        for verdict, count in result.counts().items():
            totals[verdict] = totals.get(verdict, 0) + count
    comparable = totals[MATCH] + totals[PARTIAL] + totals[CONFLICT]
    return {
        "dates": [r.session_date for r in results],
        "totals": totals, "comparable_dimensions": comparable,
        "match_rate": (f"{totals[MATCH]}/{comparable}" if comparable else "0/0"),
        "note": "方向（符号）のみを比較。履歴レポートの数値はレガシー収集経路由来で"
                "取得経路が異なるため大きさは比較しない。ruleの最適化には使わない。",
    }
