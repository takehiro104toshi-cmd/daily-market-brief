"""P12-A2 — source（P9 ・P10 の private root）の読み取り専用の決定論の manifest。

- `build_root_manifest(root, source_id)`: root の下の通常の file を相対 path（POSIX）の順に歩き、各 file の大きさと sha256 を取る。
  `content_digest` ＝ domain 付き sha256（同じ byte → 同じ digest ・1 byte の変化 → 違う digest ・歩く順に依らない）。
- 安全な表現（`to_safe_dict`）は source_id ・file_count ・byte_count ・content_digest だけ（path は無い）。private な表現
  （`to_private_dict`）は root 相対の名前と digest（絶対 path ・中身は無い）。P12 の private な run の directory にだけ置く。
- symlink ・特殊な file は fail closed（`ROOT_MISSING:<ID>_UNREADABLE`）。root を書かない ・作らない。
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Tuple

from .canonical import canonical_json, domain_digest
from .failure_codes import AutomationError

MANIFEST_SCHEMA_VERSION = "p12_source_manifest:0.1.0"
MANIFEST_DIGEST_DOMAIN = "p12.source_manifest.v1"
SOURCE_IDS: Tuple[str, ...] = ("P9", "P10")
MAX_MANIFEST_FILES = 100000


@dataclass(frozen=True)
class SourceManifest:
    source_id: str
    file_count: int
    byte_count: int
    content_digest: str
    files: Tuple[Tuple[str, int, str], ...]           # (root 相対の名前, 大きさ, sha256) ・名前の順

    def to_safe_dict(self) -> Dict[str, Any]:
        return {"schema_version": MANIFEST_SCHEMA_VERSION, "source_id": self.source_id, "file_count": self.file_count,
                "byte_count": self.byte_count, "content_digest": self.content_digest}

    def to_private_dict(self) -> Dict[str, Any]:
        return {**self.to_safe_dict(), "files": [{"name": n, "size": s, "sha256": d} for n, s, d in self.files]}

    def to_private_json(self) -> str:
        return canonical_json(self.to_private_dict())


def _manifest_digest(source_id: str, files: Tuple[Tuple[str, int, str], ...]) -> str:
    return domain_digest(MANIFEST_DIGEST_DOMAIN, {"source_id": source_id,
                                                  "files": [{"name": n, "size": s, "sha256": d} for n, s, d in files]})


def build_root_manifest(root: Any, source_id: str) -> SourceManifest:
    if source_id not in SOURCE_IDS:
        raise AutomationError("SCHEMA_INVALID", "SOURCE_ID")
    base = Path(root)
    if not base.is_dir() or base.is_symlink():
        raise AutomationError("ROOT_MISSING", source_id)
    entries = []
    total = 0
    try:
        candidates = sorted(base.rglob("*"), key=lambda p: p.relative_to(base).as_posix())
        for candidate in candidates:
            if candidate.is_symlink():
                raise AutomationError("ROOT_MISSING", f"{source_id}_UNREADABLE")
            if candidate.is_dir():
                continue
            if not candidate.is_file():
                raise AutomationError("ROOT_MISSING", f"{source_id}_UNREADABLE")
            data = candidate.read_bytes()
            total += len(data)
            entries.append((candidate.relative_to(base).as_posix(), len(data), hashlib.sha256(data).hexdigest()))
            if len(entries) > MAX_MANIFEST_FILES:
                raise AutomationError("ROOT_MISSING", f"{source_id}_UNREADABLE")
    except OSError:
        raise AutomationError("ROOT_MISSING", f"{source_id}_UNREADABLE") from None     # OS の文は出さない
    files = tuple(entries)
    return SourceManifest(source_id=source_id, file_count=len(files), byte_count=total,
                          content_digest=_manifest_digest(source_id, files), files=files)


__all__ = ["MANIFEST_DIGEST_DOMAIN", "MANIFEST_SCHEMA_VERSION", "MAX_MANIFEST_FILES", "SOURCE_IDS", "SourceManifest",
           "build_root_manifest"]
