"""Ingest orchestration（Phase 3.7 §0 の流れ）。

PDF → identity → dedup → validation → immutable source → extraction artifact
→ structured record → quality → temporal → alignment → coverage labels → status。
すべて append-only・idempotent。silent failure 禁止（必ず status event）。
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Callable, Dict, List, Mapping, Optional, Sequence, Tuple

from . import status as st
from .alignment import align_values
from .config import CorpusConfig
from .coverage import label_document
from .extraction import TextLayerExtractor, extract_artifacts
from .family import FAMILY_UNKNOWN, LOW
from .header_values import parse_header_table, parse_secondary_table, value_map
from .identity import identity_from_path
from .page_sections import section_summary
from .quality import assess_quality
from .source import MEDIA_TYPE_PDF, SourceDocument, store_original
from .store import CorpusStore
from .structured_record import analyze_document, event_state_from_text
from .temporal import temporal_semantics
from .validation import validate_document


@dataclass(frozen=True)
class IngestResult:
    document_id: str
    status: str
    quality: str
    reasons: Tuple[str, ...]
    duplicate_of: str = ""
    new_document: bool = False
    analysis_record_id: str = ""
    artifact_count: int = 0
    document_date: str = ""

    def as_dict(self) -> Dict[str, object]:
        return {"document_id": self.document_id, "status": self.status, "quality": self.quality,
                "reasons": list(self.reasons), "duplicate_of": self.duplicate_of,
                "new_document": self.new_document,
                "analysis_record_id": self.analysis_record_id,
                "artifact_count": self.artifact_count, "document_date": self.document_date}


def _event(store: CorpusStore, document_id: str, status: str, reason: str, now: datetime,
           version: str = "") -> None:
    seq = store.status_count(document_id)
    store.add_status_event(st.status_event(document_id, status, reason, now, version, sequence=seq))


def _utc(now: datetime) -> datetime:
    return now if now.tzinfo else now.replace(tzinfo=timezone.utc)


def ingest_path(store: CorpusStore, path: Path, *, config: CorpusConfig,
                extractor: TextLayerExtractor, now: datetime, source_type: str,
                original_filename: Optional[str] = None,
                trading_days: Optional[Sequence[str]] = None,
                market_lookup: Optional[Callable[[str, str], Optional[Decimal]]] = None,
                context_labels: Optional[Callable[[str], Mapping[str, str]]] = None
                ) -> IngestResult:
    path = Path(path)
    now = _utc(now)
    ident = identity_from_path(path)
    filename = original_filename or path.name
    existing = store.document(ident.document_id)
    if existing is not None:
        dup_id = "csd_" + hashlib.sha1(
            f"{ident.sha256}|{filename}|{now.isoformat()}".encode("utf-8")).hexdigest()[:16]
        store.add_duplicate({"duplicate_id": dup_id, "sha256": ident.sha256,
                             "original_filename": filename, "received_at": now.isoformat(),
                             "existing_document_id": existing.document_id,
                             "source_type": source_type})
        return IngestResult(existing.document_id, st.DUPLICATE, "",
                            ("SAME_HASH_ALREADY_IN_CORPUS",), duplicate_of=existing.document_id,
                            document_date=existing.document_date)

    result, page_texts, metadata = validate_document(path, extractor, config)
    if result.verdict == st.FAILED:
        store.add_document(SourceDocument(
            document_id=ident.document_id, sha256=ident.sha256, original_filename=filename,
            source_type=source_type, received_at=now.isoformat(), document_date="",
            date_sequence=0, page_count=result.page_count, byte_size=ident.byte_size,
            media_type=MEDIA_TYPE_PDF, storage_locator="", family=FAMILY_UNKNOWN,
            family_confidence=LOW))
        _event(store, ident.document_id, st.RECEIVED, "bytes received", now)
        _event(store, ident.document_id, st.FAILED, ",".join(result.reasons), now)
        return IngestResult(ident.document_id, st.FAILED, "", result.reasons, new_document=True)

    doc_date = result.date.document_date if result.date else ""
    locator = store_original(store.root, path, ident.document_id, ident.sha256)
    doc = SourceDocument(
        document_id=ident.document_id, sha256=ident.sha256, original_filename=filename,
        source_type=source_type, received_at=now.isoformat(), document_date=doc_date,
        date_sequence=store.next_date_sequence(doc_date) if doc_date else 0,
        page_count=result.page_count, byte_size=ident.byte_size, media_type=MEDIA_TYPE_PDF,
        storage_locator=locator, family=result.family.family if result.family else FAMILY_UNKNOWN,
        family_confidence=result.family.confidence if result.family else LOW,
        publication_date=(result.date.metadata_date if result.date else ""))
    store.add_document(doc)
    _event(store, doc.document_id, st.RECEIVED, "bytes received", now)
    if result.verdict == st.QUARANTINED:
        _event(store, doc.document_id, st.QUARANTINED, ",".join(result.reasons), now,
               version=config.family_markers_version)
        return IngestResult(doc.document_id, st.QUARANTINED, "", result.reasons, new_document=True,
                            document_date=doc_date)
    _event(store, doc.document_id, st.VALIDATED, ",".join(result.reasons) or "ok", now,
           version=config.family_markers_version)
    _event(store, doc.document_id, st.EXTRACTION_READY, "source stored", now)

    summary, artifacts = extract_artifacts(
        doc.document_id, page_texts, extractor_name=extractor.name,
        extractor_version=config.extractor_version, min_chars_per_page=config.min_chars_per_page,
        created_at=now)
    store.add_extraction(summary, artifacts)
    _event(store, doc.document_id, st.EXTRACTED, f"artifacts={len(artifacts)}", now,
           version=config.extractor_version)

    outcome = _analyze(store, doc, page_texts, metadata, artifacts, summary.page_quality,
                       config=config, now=now, analysis_version=config.analysis_version,
                       trading_days=trading_days, market_lookup=market_lookup,
                       context_labels=context_labels, supersedes="")
    return IngestResult(doc.document_id, outcome["status"], outcome["quality"], result.reasons,
                        new_document=True, analysis_record_id=outcome["record_id"],
                        artifact_count=len(artifacts), document_date=doc_date)


def _analyze(store: CorpusStore, doc: SourceDocument, page_texts: Sequence[str],
             metadata: Mapping[str, str], artifacts, page_quality: Sequence[str], *,
             config: CorpusConfig, now: datetime, analysis_version: str,
             trading_days, market_lookup, context_labels, supersedes: str) -> Dict[str, str]:
    header_values, header_status = parse_header_table(page_texts[0] if page_texts else "")
    secondary = parse_secondary_table(page_texts[1] if len(page_texts) > 1 else "")
    sections = section_summary(page_texts)
    record = analyze_document(
        document_id=doc.document_id, document_date=doc.document_date, artifacts=artifacts,
        header_values=header_values, secondary_values=secondary,
        sections=list(sections["sections"]), p2_mode=str(sections["p2_mode"]), config=config,
        created_at=now, analysis_version=analysis_version, supersedes=supersedes)
    store.add_analysis(record)

    quality = assess_quality(
        doc.document_id, family_confidence=doc.family_confidence, page_quality=page_quality,
        header_status=header_status, secondary_count=len(secondary),
        analysis_version=analysis_version, extractor_version=config.extractor_version,
        created_at=now)
    store.add_quality(quality)

    temporal = temporal_semantics(
        doc.document_date, received_at=now, metadata=metadata, trading_days=trading_days,
        body_texts=page_texts[:2])
    tdict = temporal.as_dict()
    tdict["temporal_id"] = "cst_" + hashlib.sha1(
        f"{doc.document_id}|{analysis_version}".encode("utf-8")).hexdigest()[:16]
    tdict["document_id"] = doc.document_id
    store.add_temporal(tdict)

    alignments = align_values(
        document_id=doc.document_id, header_values=header_values,
        session=temporal.referenced_market_session, lookup=market_lookup,
        tolerance_pct=config.alignment_tolerance_pct, created_at=now,
        analysis_version=analysis_version)
    store.add_alignments(alignments)

    ctx = None
    if context_labels is not None and temporal.referenced_market_session not in ("", "UNKNOWN"):
        try:
            ctx = context_labels(temporal.referenced_market_session)
        except Exception:  # noqa: BLE001 Context が引けなければ EXTRACTED / UNKNOWN へ落とす
            ctx = None
    keyword_text = "".join(page_texts[:2])
    labels = label_document(
        document_id=doc.document_id, document_date=doc.document_date,
        header=value_map(header_values), secondary=value_map(secondary),
        event_state_text_label=event_state_from_text(keyword_text),
        analysis_version=analysis_version, created_at=now, context_labels=ctx)
    store.add_coverage(labels)

    final = st.ANALYZED if quality.quality == "VALID" else st.PARTIAL
    _event(store, doc.document_id, final, f"quality={quality.quality}", now,
           version=analysis_version)
    return {"status": final, "quality": quality.quality, "record_id": record.record_id}


def reanalyze_document(store: CorpusStore, document_id: str, *, config: CorpusConfig,
                       analysis_version: str, now: datetime,
                       trading_days: Optional[Sequence[str]] = None,
                       market_lookup=None, context_labels=None) -> Optional[IngestResult]:
    """保存済み artifact から新 analysis version で再解析する（原本・旧 record は不変）。"""
    doc = store.document(document_id)
    if doc is None or store.current_status(document_id) not in st.TERMINAL_FOR_ANALYSIS:
        return None
    now = _utc(now)
    rows = store.artifacts_for(document_id, config.extractor_version)
    from .extraction import ExtractionArtifact

    artifacts = [ExtractionArtifact(
        artifact_id=r["artifact_id"], document_id=document_id, extractor_name="",
        extractor_version=r["extractor_version"], page=int(r["page"]),
        block_index=int(r["block_index"]), line_start=int(r["line_start"]),
        line_end=int(r["line_end"]), kind=r["kind"], text=r["text"], quality=r["quality"],
        ocr_derived=bool(r["ocr_derived"]), created_at="") for r in rows]
    page_texts = _page_texts_from_artifacts(artifacts, doc.page_count)
    extraction = store.extraction_for(document_id, config.extractor_version) or {}
    page_quality = list(extraction.get("page_quality") or ["OK"] * doc.page_count)
    current = store.current_analysis(document_id)
    supersedes = str(current.get("record_id", "")) if current else ""
    outcome = _analyze(store, doc, page_texts, {}, artifacts, page_quality, config=config, now=now,
                       analysis_version=analysis_version, trading_days=trading_days,
                       market_lookup=market_lookup, context_labels=context_labels,
                       supersedes=supersedes)
    return IngestResult(document_id, outcome["status"], outcome["quality"], (), new_document=False,
                        analysis_record_id=outcome["record_id"], artifact_count=len(artifacts),
                        document_date=doc.document_date)


def _page_texts_from_artifacts(artifacts, page_count: int) -> List[str]:
    """artifact（行順）から page text を復元する（header 表の再解析用）。"""
    pages: Dict[int, List[str]] = {}
    for a in sorted(artifacts, key=lambda x: (x.page, x.block_index)):
        pages.setdefault(a.page, []).append(a.text)
    return ["\n".join(pages.get(p, [])) for p in range(1, max(page_count, max(pages) if pages else 0) + 1)]
