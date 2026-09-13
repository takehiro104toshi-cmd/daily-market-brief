"""Immutable source model（Phase 3.7 §2）。

原本 PDF は Corpus root 配下 `sources/<document_id>.pdf` へ **一度だけ** コピーし read-only にする。
analysis pipeline は原本を書き換えない（検証は hash 再計算）。Git へは入れない（data root 配下）。
"""
from __future__ import annotations

import os
import stat
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Mapping, Optional, Union

from .identity import sha256_file

SOURCES_DIR = "sources"
MEDIA_TYPE_PDF = "application/pdf"
SOURCE_SCHEMA_VERSION = "1.0.0"


@dataclass(frozen=True)
class SourceDocument:
    document_id: str
    sha256: str
    original_filename: str
    source_type: str                 # LOCAL_FILE / HISTORICAL_IMPORT / INBOX / MOBILE_UPLOAD
    received_at: str                 # ISO datetime UTC
    document_date: str               # ISO date（"" if unknown）
    date_sequence: int
    page_count: int
    byte_size: int
    media_type: str
    storage_locator: str             # corpus root 相対（"" = 保存していない）
    family: str
    family_confidence: str
    publication_date: str = ""
    schema_version: str = SOURCE_SCHEMA_VERSION

    def as_dict(self) -> Dict[str, object]:
        return {"document_id": self.document_id, "sha256": self.sha256,
                "original_filename": self.original_filename, "source_type": self.source_type,
                "received_at": self.received_at, "document_date": self.document_date,
                "date_sequence": self.date_sequence, "page_count": self.page_count,
                "byte_size": self.byte_size, "media_type": self.media_type,
                "storage_locator": self.storage_locator, "family": self.family,
                "family_confidence": self.family_confidence,
                "publication_date": self.publication_date,
                "schema_version": self.schema_version}


def source_from_dict(d: Mapping[str, object]) -> SourceDocument:
    return SourceDocument(
        document_id=str(d.get("document_id", "")), sha256=str(d.get("sha256", "")),
        original_filename=str(d.get("original_filename", "")),
        source_type=str(d.get("source_type", "")), received_at=str(d.get("received_at", "")),
        document_date=str(d.get("document_date", "")),
        date_sequence=int(d.get("date_sequence", 0) or 0),
        page_count=int(d.get("page_count", 0) or 0), byte_size=int(d.get("byte_size", 0) or 0),
        media_type=str(d.get("media_type", MEDIA_TYPE_PDF)),
        storage_locator=str(d.get("storage_locator", "")), family=str(d.get("family", "")),
        family_confidence=str(d.get("family_confidence", "")),
        publication_date=str(d.get("publication_date", "")),
        schema_version=str(d.get("schema_version", SOURCE_SCHEMA_VERSION)))


def sources_dir(root: Path) -> Path:
    return Path(root) / SOURCES_DIR


def locator_for(document_id: str) -> str:
    return f"{SOURCES_DIR}/{document_id}.pdf"


class SourceIntegrityError(RuntimeError):
    """原本コピーの hash が identity と一致しない（書き換え・破損）。"""


def store_original(root: Path, source: Union[Path, bytes], document_id: str, sha256: str) -> str:
    """原本を immutable copy として保存し locator を返す。既存なら hash を検証するだけ。"""
    target = Path(root) / locator_for(document_id)
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists():
        if sha256_file(target) != sha256:
            raise SourceIntegrityError(f"stored source hash mismatch for {document_id}")
        return locator_for(document_id)
    data = source if isinstance(source, (bytes, bytearray)) else Path(source).read_bytes()
    tmp = target.with_suffix(".part")
    tmp.write_bytes(data)
    if sha256_file(tmp) != sha256:
        tmp.unlink(missing_ok=True)
        raise SourceIntegrityError(f"copied bytes hash mismatch for {document_id}")
    os.replace(tmp, target)
    try:
        target.chmod(stat.S_IRUSR | stat.S_IRGRP | stat.S_IROTH)
    except OSError:  # 権限変更できない FS でも保存自体は有効
        pass
    return locator_for(document_id)


def verify_original(root: Path, locator: str, sha256: str) -> bool:
    if not locator:
        return False
    path = Path(root) / locator
    return path.is_file() and sha256_file(path) == sha256
