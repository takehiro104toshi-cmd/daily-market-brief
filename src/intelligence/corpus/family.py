"""Document family detection（Phase 3.7 §7）。

「グローバル投資の羅針盤」であることを **filename に依存せず** page-1 の安定した
textual marker で判定する（layout 非依存: 空白を除去した本文に対する部分一致）。
confidence が HIGH でなければ Corpus へ入れない（QUARANTINED, fail-closed）。
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Dict, List, Sequence, Tuple

FAMILY_COMPASS = "okasan_global_investment_compass"
FAMILY_UNKNOWN = "UNKNOWN"

HIGH = "HIGH"
MEDIUM = "MEDIUM"
LOW = "LOW"

MARKERS_VERSION = "1.0.0"

#: (marker_id, 必須か, 検索 token 群（全て含むこと）)。空白除去後の本文に対して照合する。
FAMILY_MARKERS: Tuple[Tuple[str, bool, Tuple[str, ...]], ...] = (
    ("title_compass", True, ("羅針盤",)),
    ("title_global_investment", True, ("グローバル投資の",)),
    ("series_best_ideas", False, ("ストラテジーのベストアイディア",)),
    ("confidential_banner", True, ("社外秘",)),
    ("publisher", False, ("作成：岡三証券",)),
    ("header_footnote", False, ("25日MAの前日比は日経平均との乖離率",)),
    ("header_labels", False, ("日経平均", "TOPIX", "NYダウ", "S&P500", "ナスダック", "ドル円")),
    ("outlook_heading", False, ("日本株相場見通し",)),
)

_WS = re.compile(r"\s+")


def _compact(text: str) -> str:
    return _WS.sub("", text or "")


@dataclass(frozen=True)
class FamilyDecision:
    family: str
    confidence: str
    markers_found: Tuple[str, ...]
    markers_missing: Tuple[str, ...]
    required_missing: Tuple[str, ...]
    markers_version: str = MARKERS_VERSION

    def as_dict(self) -> Dict[str, object]:
        return {"family": self.family, "confidence": self.confidence,
                "markers_found": list(self.markers_found),
                "markers_missing": list(self.markers_missing),
                "required_missing": list(self.required_missing),
                "markers_version": self.markers_version}


def detect_family(page_texts: Sequence[str], *, min_markers: int = 5) -> FamilyDecision:
    """page-1 marker から family / confidence を決める。

    HIGH: 必須 marker 全部 ＋ 合計 >= min_markers。MEDIUM: 必須全部だが数不足。
    LOW: 必須 marker 欠落。HIGH 以外は Corpus 投入不可。"""
    first = _compact(page_texts[0]) if page_texts else ""
    found: List[str] = []
    missing: List[str] = []
    required_missing: List[str] = []
    for marker_id, required, tokens in FAMILY_MARKERS:
        if all(_compact(t) in first for t in tokens):
            found.append(marker_id)
        else:
            missing.append(marker_id)
            if required:
                required_missing.append(marker_id)
    if required_missing:
        confidence, family = LOW, FAMILY_UNKNOWN
    elif len(found) >= min_markers:
        confidence, family = HIGH, FAMILY_COMPASS
    else:
        confidence, family = MEDIUM, FAMILY_COMPASS
    return FamilyDecision(family=family, confidence=confidence, markers_found=tuple(found),
                          markers_missing=tuple(missing),
                          required_missing=tuple(required_missing))
