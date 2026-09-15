"""Deterministic document identity（Phase 3.7 §3）。

- identity は **content hash（sha256）中心**。filename には依存しない。
- 同じ日付に複数 version が存在し得る → `date_sequence`（store が採番、同一日付の何本目か）。
- document_date ≠ received_at（temporal.py が分離して保持する）。
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Union

ID_PREFIX = "cmp_"
ID_HEX_LENGTH = 20

Bytes = Union[bytes, bytearray, memoryview]


def sha256_bytes(data: Bytes) -> str:
    return hashlib.sha256(bytes(data)).hexdigest()


def sha256_file(path: Path, chunk: int = 1 << 20) -> str:
    h = hashlib.sha256()
    with Path(path).open("rb") as handle:
        while True:
            block = handle.read(chunk)
            if not block:
                break
            h.update(block)
    return h.hexdigest()


def document_id_for(sha256: str) -> str:
    """document_id = 'cmp_' + sha256 先頭 20 hex。同一 bytes → 同一 id（filename 無関係）。"""
    if len(sha256) != 64:
        raise ValueError("sha256 hex expected")
    return ID_PREFIX + sha256[:ID_HEX_LENGTH].lower()


@dataclass(frozen=True)
class DocumentIdentity:
    document_id: str
    sha256: str
    byte_size: int
    original_filename: str          # 記録のみ。identity には使わない
    document_date: str = ""         # 検証で確定（temporal.py）
    date_sequence: int = 0          # 同一 document_date 内の通番（store が採番）

    def as_dict(self) -> Dict[str, object]:
        return {"document_id": self.document_id, "sha256": self.sha256,
                "byte_size": self.byte_size, "original_filename": self.original_filename,
                "document_date": self.document_date, "date_sequence": self.date_sequence}


def identity_from_bytes(data: Bytes, original_filename: str) -> DocumentIdentity:
    digest = sha256_bytes(data)
    return DocumentIdentity(document_id=document_id_for(digest), sha256=digest,
                            byte_size=len(bytes(data)), original_filename=original_filename)


def identity_from_path(path: Path) -> DocumentIdentity:
    path = Path(path)
    digest = sha256_file(path)
    return DocumentIdentity(document_id=document_id_for(digest), sha256=digest,
                            byte_size=path.stat().st_size, original_filename=path.name)
