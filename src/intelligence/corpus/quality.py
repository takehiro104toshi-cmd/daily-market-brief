"""Document quality（Phase 3.7 §18）。品質の低い document を pattern evidence へ無条件投入しない。"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import datetime
from typing import Dict, List, Sequence, Tuple

from .extraction import PAGE_EMPTY, PAGE_LOW_TEXT
from .family import HIGH
from .header_values import STATUS_COMPLETE, STATUS_MISSING, STATUS_PARTIAL

VALID = "VALID"
PARTIAL = "PARTIAL"
LIMITED_USE = "LIMITED_USE"
QUARANTINED = "QUARANTINED"

MIN_SECONDARY_VALUES = 4


@dataclass(frozen=True)
class DocumentQuality:
    quality_id: str
    document_id: str
    quality: str
    reasons: Tuple[str, ...]
    analysis_version: str
    extractor_version: str
    eligible_for_pattern_evidence: bool
    created_at: str

    def as_dict(self) -> Dict[str, object]:
        return {"quality_id": self.quality_id, "document_id": self.document_id,
                "quality": self.quality, "reasons": list(self.reasons),
                "analysis_version": self.analysis_version,
                "extractor_version": self.extractor_version,
                "eligible_for_pattern_evidence": self.eligible_for_pattern_evidence,
                "created_at": self.created_at}


def assess_quality(document_id: str, *, family_confidence: str, page_quality: Sequence[str],
                   header_status: str, secondary_count: int, analysis_version: str,
                   extractor_version: str, created_at: datetime) -> DocumentQuality:
    reasons: List[str] = []
    if family_confidence != HIGH:
        quality = QUARANTINED
        reasons.append(f"family_confidence={family_confidence}")
    else:
        quality = VALID
        if any(q == PAGE_EMPTY for q in page_quality):
            quality = LIMITED_USE
            reasons.append("empty_page")
        if header_status == STATUS_MISSING:
            quality = LIMITED_USE
            reasons.append("header_table_missing")
        if quality == VALID:
            if any(q == PAGE_LOW_TEXT for q in page_quality):
                quality = PARTIAL
                reasons.append("low_text_page")
            if header_status == STATUS_PARTIAL:
                quality = PARTIAL
                reasons.append("header_table_partial")
            if secondary_count < MIN_SECONDARY_VALUES:
                quality = PARTIAL
                reasons.append("secondary_table_incomplete")
    if quality == VALID and header_status != STATUS_COMPLETE:
        quality = PARTIAL
        reasons.append("header_status_" + header_status)
    seed = f"{document_id}|{analysis_version}|{extractor_version}"
    return DocumentQuality(
        quality_id="csq_" + hashlib.sha1(seed.encode("utf-8")).hexdigest()[:16],
        document_id=document_id, quality=quality, reasons=tuple(reasons),
        analysis_version=analysis_version, extractor_version=extractor_version,
        eligible_for_pattern_evidence=(quality == VALID), created_at=created_at.isoformat())
