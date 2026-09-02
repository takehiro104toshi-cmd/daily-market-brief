"""Extraction boundary（Phase 3.7 §8 / §9）。

PDF source と extracted text を分離する。artifact は
extractor_version / source_document_id / page / location / kind / quality / created_at を持つ。
- text layer があればそれを優先。**OCR は default で行わない**（`ocr_derived=False` 固定。
  将来 OCR fallback を足す場合は別 extractor として ocr_derived=True を記録する）。
- 抽出できなかった内容を推測しない（EMPTY / LOW_TEXT をそのまま記録）。
"""
from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Mapping, Optional, Protocol, Sequence, Tuple

# artifact kind
KIND_BANNER = "BANNER"        # 社外秘・配布禁止バナー
KIND_HEADING = "HEADING"      # section 見出し・【】サブ見出し
KIND_BULLET = "BULLET"        # ● 3行ボレット
KIND_TABLE_ROW = "TABLE_ROW"  # 数値行（終値 / 前日比 / 指数表）
KIND_FOOTNOTE = "FOOTNOTE"    # 出所：… 作成：…
KIND_TEXT = "TEXT"            # 本文行

# page quality
PAGE_OK = "OK"
PAGE_LOW_TEXT = "LOW_TEXT"
PAGE_EMPTY = "EMPTY"

EXTRACTOR_PYPDF = "pypdf_text_layer"

_BANNER_TOKENS = ("お客様への配布は厳禁", "社外秘（岡三証券社内限")
_HEADING_RE = re.compile(r"^(【.+】|▼.+|.*(相場見通し|投資戦略|投資アイデア|注目の日本株|物色動向|主な株価・市況関連指数|要人発言).*)$")
_TABLE_RE = re.compile(r"^(終値|前日比)\s|^[^\d]{1,24}\s[\d,]+\.\d+\s[+\-][\d.]+|CLOSED|Closed")
_FOOTNOTE_RE = re.compile(r"^(出所[:：]|作成[:：]|※)")


class TextLayerExtractor(Protocol):
    name: str
    version: str

    def page_texts(self, path: Path) -> List[str]: ...

    def metadata(self, path: Path) -> Dict[str, str]: ...

    def page_count(self, path: Path) -> int: ...


class PypdfExtractor:
    """pypdf の text layer 抽出（OCR なし）。"""

    name = EXTRACTOR_PYPDF

    def __init__(self, version: str = "pypdf_text_layer:1.0.0") -> None:
        self.version = version

    def _reader(self, path: Path):
        import pypdf  # 既存依存

        return pypdf.PdfReader(str(path))

    def page_texts(self, path: Path) -> List[str]:
        reader = self._reader(path)
        return [(page.extract_text() or "") for page in reader.pages]

    def metadata(self, path: Path) -> Dict[str, str]:
        reader = self._reader(path)
        meta = reader.metadata or {}
        return {str(k): str(v) for k, v in dict(meta).items()}

    def page_count(self, path: Path) -> int:
        return len(self._reader(path).pages)


class FakeExtractor:
    """テスト用: path → page texts を注入する（PDF を読まない）。"""

    name = "fake_text_layer"

    def __init__(self, texts: Mapping[str, Sequence[str]], version: str = "fake:1.0.0",
                 metadata: Optional[Mapping[str, Mapping[str, str]]] = None) -> None:
        self._texts = {str(k): list(v) for k, v in texts.items()}
        self._meta = {str(k): dict(v) for k, v in (metadata or {}).items()}
        self.version = version

    def page_texts(self, path: Path) -> List[str]:
        return list(self._texts.get(str(path), self._texts.get(Path(path).name, [])))

    def metadata(self, path: Path) -> Dict[str, str]:
        return dict(self._meta.get(str(path), self._meta.get(Path(path).name, {})))

    def page_count(self, path: Path) -> int:
        return len(self.page_texts(path))


@dataclass(frozen=True)
class ExtractionArtifact:
    artifact_id: str
    document_id: str
    extractor_name: str
    extractor_version: str
    page: int                 # 1-based
    block_index: int          # page 内通番
    line_start: int           # 1-based（page 内の非空行番号）
    line_end: int
    kind: str
    text: str
    quality: str              # page quality（OK / LOW_TEXT / EMPTY）
    ocr_derived: bool
    created_at: str

    def as_dict(self) -> Dict[str, object]:
        return {"artifact_id": self.artifact_id, "document_id": self.document_id,
                "extractor_name": self.extractor_name, "extractor_version": self.extractor_version,
                "page": self.page, "block_index": self.block_index,
                "line_start": self.line_start, "line_end": self.line_end,
                "kind": self.kind, "text": self.text, "quality": self.quality,
                "ocr_derived": self.ocr_derived, "created_at": self.created_at}


@dataclass(frozen=True)
class ExtractionSummary:
    extraction_id: str
    document_id: str
    extractor_name: str
    extractor_version: str
    page_count: int
    chars_per_page: Tuple[int, ...]
    page_quality: Tuple[str, ...]
    text_layer_present: bool
    ocr_attempted: bool
    artifact_count: int
    created_at: str

    def as_dict(self) -> Dict[str, object]:
        return {"extraction_id": self.extraction_id, "document_id": self.document_id,
                "extractor_name": self.extractor_name, "extractor_version": self.extractor_version,
                "page_count": self.page_count, "chars_per_page": list(self.chars_per_page),
                "page_quality": list(self.page_quality),
                "text_layer_present": self.text_layer_present, "ocr_attempted": self.ocr_attempted,
                "artifact_count": self.artifact_count, "created_at": self.created_at}


def extraction_id_for(document_id: str, extractor_version: str) -> str:
    return "cxe_" + hashlib.sha1(f"{document_id}|{extractor_version}".encode("utf-8")).hexdigest()[:16]


def artifact_id_for(document_id: str, extractor_version: str, page: int, block_index: int) -> str:
    seed = f"{document_id}|{extractor_version}|{page}|{block_index}"
    return "cxa_" + hashlib.sha1(seed.encode("utf-8")).hexdigest()[:16]


def classify_line(line: str) -> str:
    s = line.strip()
    if any(tok in s for tok in _BANNER_TOKENS):
        return KIND_BANNER
    if s.startswith("●"):
        return KIND_BULLET
    if _FOOTNOTE_RE.match(s):
        return KIND_FOOTNOTE
    if _TABLE_RE.search(s):
        return KIND_TABLE_ROW
    if _HEADING_RE.match(s) and len(s) <= 40:
        return KIND_HEADING
    return KIND_TEXT


def page_quality(chars: int, min_chars: int) -> str:
    if chars <= 0:
        return PAGE_EMPTY
    if chars < min_chars:
        return PAGE_LOW_TEXT
    return PAGE_OK


def extract_artifacts(document_id: str, page_texts: Sequence[str], *, extractor_name: str,
                      extractor_version: str, min_chars_per_page: int, created_at: datetime,
                      ocr_derived: bool = False) -> Tuple[ExtractionSummary, List[ExtractionArtifact]]:
    """page text → 行単位 artifact（連続する本文行は 1 block にまとめる）。"""
    artifacts: List[ExtractionArtifact] = []
    chars: List[int] = []
    qualities: List[str] = []
    stamp = created_at.isoformat()
    for page_no, text in enumerate(page_texts, start=1):
        text = text or ""
        chars.append(len(text))
        quality = page_quality(len(text), min_chars_per_page)
        qualities.append(quality)
        lines = [l.strip() for l in text.splitlines() if l.strip()]
        block_index = 0
        buffer: List[str] = []
        buffer_start = 0

        def flush(end_line: int) -> None:
            nonlocal block_index, buffer, buffer_start
            if not buffer:
                return
            artifacts.append(ExtractionArtifact(
                artifact_id=artifact_id_for(document_id, extractor_version, page_no, block_index),
                document_id=document_id, extractor_name=extractor_name,
                extractor_version=extractor_version, page=page_no, block_index=block_index,
                line_start=buffer_start, line_end=end_line, kind=KIND_TEXT,
                text="".join(buffer), quality=quality, ocr_derived=ocr_derived,
                created_at=stamp))
            block_index += 1
            buffer = []

        for line_no, line in enumerate(lines, start=1):
            kind = classify_line(line)
            if kind == KIND_TEXT:
                if not buffer:
                    buffer_start = line_no
                buffer.append(line)
                continue
            flush(line_no - 1)
            artifacts.append(ExtractionArtifact(
                artifact_id=artifact_id_for(document_id, extractor_version, page_no, block_index),
                document_id=document_id, extractor_name=extractor_name,
                extractor_version=extractor_version, page=page_no, block_index=block_index,
                line_start=line_no, line_end=line_no, kind=kind, text=line, quality=quality,
                ocr_derived=ocr_derived, created_at=stamp))
            block_index += 1
        flush(len(lines))
    summary = ExtractionSummary(
        extraction_id=extraction_id_for(document_id, extractor_version), document_id=document_id,
        extractor_name=extractor_name, extractor_version=extractor_version,
        page_count=len(page_texts), chars_per_page=tuple(chars), page_quality=tuple(qualities),
        text_layer_present=any(q == PAGE_OK for q in qualities), ocr_attempted=False,
        artifact_count=len(artifacts), created_at=stamp)
    return summary, artifacts
