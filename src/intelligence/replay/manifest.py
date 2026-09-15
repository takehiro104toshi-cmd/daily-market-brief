"""Input manifest（Phase 3.9.4）— 凍結 corpus snapshot から run の文書宇宙を確定する。"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from decimal import Decimal
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence

from ..corpus.quality import LIMITED_USE, PARTIAL, QUARANTINED, VALID
from ..corpus.status import ANALYZED, FAILED
from ..corpus.status import PARTIAL as STATUS_PARTIAL
from ..corpus.status import QUARANTINED as STATUS_QUARANTINED
from ..corpus.store import CorpusStore
from .errors import ReplayIdentityCollision

USABLE_QUALITIES = (VALID, PARTIAL)
USABLE_STATUSES = (ANALYZED, STATUS_PARTIAL)

EXCL_NOT_USABLE_QUALITY = "NOT_USABLE_QUALITY"
EXCL_NOT_USABLE_STATUS = "NOT_USABLE_STATUS"
EXCL_UNDATED = "UNDATED_CHRONOLOGICAL"


@dataclass(frozen=True)
class ManifestDocument:
    document_id: str
    sha256: str
    document_date: str
    date_sequence: int
    received_at: str
    quality: str
    eligible: bool
    status: str

    @property
    def usable(self) -> bool:
        return self.quality in USABLE_QUALITIES and self.status in USABLE_STATUSES

    @property
    def undated(self) -> bool:
        return not self.document_date

    def as_dict(self) -> Dict[str, Any]:
        return {"document_id": self.document_id, "sha256": self.sha256, "document_date": self.document_date,
                "date_sequence": self.date_sequence, "received_at": self.received_at,
                "quality": self.quality, "eligible": self.eligible, "status": self.status,
                "usable": self.usable}

    def identity(self) -> Dict[str, Any]:
        """drift 比較に使う identity（時刻や表示情報は含めない）。"""
        return {"sha256": self.sha256, "status": self.status, "quality": self.quality, "eligible": self.eligible,
                "document_date": self.document_date, "date_sequence": self.date_sequence}


@dataclass(frozen=True)
class InputManifest:
    documents: Sequence[ManifestDocument]
    duplicates_summary: Mapping[str, Any]
    excluded: Sequence[Mapping[str, str]]
    input_manifest_digest: str
    captured_eligible: int
    captured_usable: int
    captured_documents: int
    latest_document_date: str
    analysis_versions: Sequence[str] = ()

    def usable_documents(self) -> List[ManifestDocument]:
        return [d for d in self.documents if d.usable]

    def as_dict(self) -> Dict[str, Any]:
        return {"documents": [d.as_dict() for d in self.documents],
                "duplicates_summary": dict(self.duplicates_summary),
                "excluded": [dict(e) for e in self.excluded],
                "input_manifest_digest": self.input_manifest_digest,
                "captured_eligible": self.captured_eligible, "captured_usable": self.captured_usable,
                "captured_documents": self.captured_documents,
                "latest_document_date": self.latest_document_date,
                "analysis_versions": list(self.analysis_versions)}


def manifest_digest(documents: Sequence[ManifestDocument], duplicates_summary: Mapping[str, Any]) -> str:
    view = {"documents": [d.identity() | {"document_id": d.document_id} for d in
                          sorted(documents, key=lambda d: d.document_id)],
            "duplicates": {"count": int(duplicates_summary.get("count", 0)),
                           "sha256": sorted(duplicates_summary.get("sha256", []))}}
    blob = json.dumps(view, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:16]


def build_manifest(snapshot_corpus_root: Path) -> InputManifest:
    """凍結 corpus snapshot を読んで文書宇宙を確定する。production には触れない。"""
    store = CorpusStore(Path(snapshot_corpus_root))
    try:
        docs: List[ManifestDocument] = []
        versions: set = set()
        seen_ids: set = set()
        seen_sha: Dict[str, str] = {}
        for d in store.documents():
            if d.document_id in seen_ids:
                raise ReplayIdentityCollision(f"duplicate document_id in snapshot: {d.document_id}")
            if d.sha256 in seen_sha:
                raise ReplayIdentityCollision(
                    f"two documents share sha256 in snapshot: {seen_sha[d.sha256]} / {d.document_id}")
            seen_ids.add(d.document_id)
            seen_sha[d.sha256] = d.document_id
            quality = store.quality_for(d.document_id) or {}
            current = store.current_analysis(d.document_id) or {}
            if current:
                versions.add(str(current.get("analysis_version", "")))
            docs.append(ManifestDocument(
                document_id=d.document_id, sha256=d.sha256, document_date=str(d.document_date or ""),
                date_sequence=int(d.date_sequence or 0), received_at=str(d.received_at or ""),
                quality=str(quality.get("quality", "")), eligible=bool(quality.get("eligible_for_pattern_evidence")),
                status=str(store.current_status(d.document_id) or "")))
        dups = store.duplicates()
        dup_summary = {"count": len(dups), "sha256": sorted({str(x.get("sha256", "")) for x in dups}),
                       "existing_document_ids": sorted({str(x.get("existing_document_id", "")) for x in dups})}
    finally:
        store.close()
    excluded: List[Dict[str, str]] = []
    for d in docs:
        if d.quality not in USABLE_QUALITIES:
            excluded.append({"document_id": d.document_id, "reason": EXCL_NOT_USABLE_QUALITY, "detail": d.quality})
        elif d.status not in USABLE_STATUSES:
            excluded.append({"document_id": d.document_id, "reason": EXCL_NOT_USABLE_STATUS, "detail": d.status})
    usable = [d for d in docs if d.usable]
    return InputManifest(
        documents=tuple(docs), duplicates_summary=dup_summary, excluded=tuple(excluded),
        input_manifest_digest=manifest_digest(docs, dup_summary),
        captured_eligible=sum(1 for d in usable if d.eligible), captured_usable=len(usable),
        captured_documents=len(docs),
        latest_document_date=max((d.document_date for d in usable if d.document_date), default=""),
        analysis_versions=tuple(sorted(versions)))


def detect_input_mutation(manifest: InputManifest, live: Mapping[str, Mapping[str, Any]]) -> List[Dict[str, Any]]:
    """捕捉済み文書の identity が production で変わっていたら差分を返す（空 = 無変化）。"""
    changes: List[Dict[str, Any]] = []
    for d in manifest.documents:
        now = dict(live.get(d.document_id) or {"missing": True})
        if now.get("missing"):
            changes.append({"document_id": d.document_id, "change": "MISSING_IN_PRODUCTION"})
            continue
        for key in ("sha256", "status", "quality", "eligible", "document_date", "date_sequence"):
            if now.get(key) != d.identity()[key]:
                changes.append({"document_id": d.document_id, "change": key,
                                "captured": d.identity()[key], "live": now.get(key)})
    return changes
