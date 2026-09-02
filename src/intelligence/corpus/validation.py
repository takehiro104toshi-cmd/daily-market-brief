"""Corpus 投入前検証（Phase 3.7 §6）。fail-closed: 迷ったら QUARANTINED。

検証項目: valid PDF（magic bytes）/ readable（text layer 抽出可）/ page count 範囲 /
expected document family（family.py）/ document date（temporal.py）。
duplicate は identity（hash）で store 側が判定する（pipeline.py）。
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

from .config import CorpusConfig
from .extraction import TextLayerExtractor
from .family import HIGH, FamilyDecision, detect_family
from .status import FAILED, QUARANTINED, VALIDATED
from .temporal import DocumentDateDecision, extract_document_date

PDF_MAGIC = b"%PDF-"

R_NOT_PDF = "NOT_PDF_BYTES"
R_UNREADABLE = "PDF_UNREADABLE"
R_NO_PAGES = "NO_PAGES"
R_PAGE_COUNT = "PAGE_COUNT_OUT_OF_RANGE"
R_FAMILY = "FAMILY_CONFIDENCE_"
R_DATE_MISSING = "DOCUMENT_DATE_MISSING"
R_DATE_CONFLICT = "DOCUMENT_DATE_CONFLICT_"


@dataclass(frozen=True)
class ValidationResult:
    valid_pdf: bool
    readable: bool
    page_count: int
    family: Optional[FamilyDecision]
    date: Optional[DocumentDateDecision]
    verdict: str                         # VALIDATED / QUARANTINED / FAILED
    reasons: Tuple[str, ...]

    def as_dict(self) -> Dict[str, object]:
        return {"valid_pdf": self.valid_pdf, "readable": self.readable,
                "page_count": self.page_count,
                "family": self.family.as_dict() if self.family else None,
                "date": self.date.as_dict() if self.date else None,
                "verdict": self.verdict, "reasons": list(self.reasons)}


def is_pdf_bytes(head: bytes) -> bool:
    return bytes(head[:5]) == PDF_MAGIC


def validate_document(path: Path, extractor: TextLayerExtractor, config: CorpusConfig
                      ) -> Tuple[ValidationResult, List[str], Dict[str, str]]:
    """→ (result, page_texts, metadata)。読めない場合 page_texts は空。"""
    path = Path(path)
    reasons: List[str] = []
    try:
        with path.open("rb") as handle:
            head = handle.read(8)
    except OSError:
        return ValidationResult(False, False, 0, None, None, FAILED, (R_UNREADABLE,)), [], {}
    if not is_pdf_bytes(head):
        return ValidationResult(False, False, 0, None, None, FAILED, (R_NOT_PDF,)), [], {}
    try:
        page_texts = extractor.page_texts(path)
        metadata = extractor.metadata(path)
    except Exception as exc:  # noqa: BLE001 例外の型名のみ記録（本文・パスを漏らさない）
        return ValidationResult(True, False, 0, None, None, FAILED,
                                (R_UNREADABLE, type(exc).__name__)), [], {}
    page_count = len(page_texts)
    if page_count == 0:
        return ValidationResult(True, False, 0, None, None, FAILED, (R_NO_PAGES,)), [], metadata
    family = detect_family(page_texts, min_markers=config.family_min_markers)
    date = extract_document_date(page_texts[0], metadata)
    verdict = VALIDATED
    if page_count < config.min_pages or page_count > config.max_pages:
        reasons.append(R_PAGE_COUNT)
        verdict = QUARANTINED
    if family.confidence != HIGH:
        reasons.append(R_FAMILY + family.confidence)
        verdict = QUARANTINED
    if not date.document_date:
        reasons.append(R_DATE_MISSING)
        verdict = QUARANTINED
    for conflict in date.conflicts:
        reasons.append(R_DATE_CONFLICT + conflict)   # 記録のみ（本文日付を優先）
    return ValidationResult(True, True, page_count, family, date, verdict, tuple(reasons)), page_texts, metadata
