"""Evidence snapshot builder（Phase 3.9.1）— Phase 3.8 research artifact を **読むだけ** で compact snapshot を作る。

入れるもの: id / count / label / version / digest。入れないもの: 本文・observation text・PDF path。
research root が無い / pattern が registry に無い → pattern_found=False（decision は fail closed で拒否される）。
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, Mapping, Optional

from ..corpus_research.store import SNAPSHOT_FILE, ResearchStore
from .models import MAX_SUPPORTING_DOC_IDS, EvidenceSnapshot


def _read_json(path: Path) -> Dict[str, Any]:
    try:
        return dict(json.loads(path.read_text(encoding="utf-8")) or {})
    except (OSError, ValueError):
        return {}


def build_evidence_snapshot(research_root_dir: Path, pattern_id: str,
                            pattern_version: Optional[str] = None) -> EvidenceSnapshot:
    root = Path(research_root_dir)
    if not root.is_dir() or not (root / "patterns.jsonl").is_file():     # 読み取り専用: root を作らない
        return EvidenceSnapshot(pattern_id=pattern_id, pattern_found=False)
    if pattern_version is None:
        from ..corpus_research.config import load_research_config

        pattern_version = load_research_config().pattern_version
    store = ResearchStore(root)
    rec: Optional[Mapping[str, Any]] = store.pattern_records_current(pattern_version).get(pattern_id)
    if rec is None:
        return EvidenceSnapshot(pattern_id=pattern_id, pattern_found=False)
    comp = dict(rec.get("components") or {})
    dna = [c for c in store.rows("dna_comparisons") if str(c.get("pattern_id")) == pattern_id]
    last_dna = dna[-1] if dna else {}
    conflicts = [c for c in store.rows("conflicts") if str(c.get("pattern_id")) == pattern_id]
    snap = _read_json(root / SNAPSHOT_FILE)
    docs = [str(d) for d in (rec.get("supporting_document_ids") or [])]
    dr = list(rec.get("date_range") or ["", ""])
    return EvidenceSnapshot(
        pattern_id=pattern_id, pattern_found=True,
        pattern_type=str(rec.get("pattern_type") or ""), pattern_status=str(rec.get("status") or ""),
        pattern_record_id=str(rec.get("pattern_record_id") or ""),
        support_count=_int_or_none(rec.get("support_count")), eligible_support=_int_or_none(rec.get("eligible_support")),
        regime_count=_int_or_none(rec.get("regime_count")), span_days=_int_or_none(rec.get("span_days")),
        date_range=(str(dr[0]) if dr else "", str(dr[1]) if len(dr) > 1 else ""),
        valid_ratio=str(rec.get("valid_ratio") or ""),
        evidence_categories=tuple(str(e) for e in (comp.get("evidence") or [])),
        theme=str(comp.get("theme") or ""), outlook=tuple(str(o) for o in (comp.get("outlook") or [])),
        risk=str(comp.get("risk") or ""),
        supporting_document_count=len(docs), supporting_document_ids=tuple(sorted(docs)[:MAX_SUPPORTING_DOC_IDS]),
        evidence_reference_count=len(rec.get("evidence_references") or []),
        dna_classification=str(last_dna.get("classification") or ""),
        dna_best_rule_id=str(last_dna.get("best_rule_id") or ""),
        conflict_count=len(conflicts), conflict_rule_ids=tuple(sorted({str(c.get("rule_id") or "") for c in conflicts})),
        limitations=tuple(str(l) for l in (rec.get("limitations") or [])),
        research_snapshot_id=str(snap.get("snapshot_id") or ""), research_generated_at=str(snap.get("generated_at") or ""),
        analyzer_versions={str(k): str(v) for k, v in dict(snap.get("analyzer_versions") or {}).items()},
        research_corpus_count=_int_or_none(snap.get("corpus_count")),
        research_eligible_count=_int_or_none(snap.get("eligible_count")))


def _int_or_none(value: Any) -> Optional[int]:
    try:
        return int(value) if value is not None and value != "" else None
    except (TypeError, ValueError):
        return None
