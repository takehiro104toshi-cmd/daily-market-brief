"""Supervisor Review Queue（Phase 3.8 §32）。auto approval なし。各 item は理由と evidence 参照を持つ。"""
from __future__ import annotations

import hashlib
from datetime import datetime
from typing import Dict, List, Mapping, Sequence

from .lifecycle import NEW_PATTERN_CANDIDATE, REVIEW_CANDIDATE, STRONG_PATTERN_CANDIDATE

REVIEW_VERSION = "1.0.0"
K_NEW_PATTERN = "NEW_PATTERN"
K_PATTERN_CONFLICT = "PATTERN_CONFLICT"
K_LOW_CONFIDENCE = "LOW_CONFIDENCE_EXTRACTION"
K_UNUSUAL_REGIME = "UNUSUAL_REGIME"
K_NEW_THEME = "NEW_THEME_CATEGORY"
K_DNA_CONFLICT = "DNA_CONFLICT"
KINDS = (K_NEW_PATTERN, K_PATTERN_CONFLICT, K_LOW_CONFIDENCE, K_UNUSUAL_REGIME, K_NEW_THEME, K_DNA_CONFLICT)
OPEN = "OPEN"


def _item(kind: str, subject: str, reason: str, refs: Sequence[str], now: datetime, **extra) -> Dict[str, object]:
    rid = "crq_" + hashlib.sha1(f"{kind}|{subject}|{REVIEW_VERSION}".encode("utf-8")).hexdigest()[:16]
    return {"review_id": rid, "kind": kind, "subject_id": subject, "reason": reason,
            "evidence_refs": list(refs)[:20], "status": OPEN, "requires_supervisor": True,
            "auto_approval": False, "created_at": now.isoformat(), "version": REVIEW_VERSION, **extra}


def build_review_items(*, pattern_records: Mapping[str, Mapping], conflicts: Sequence[Mapping],
                       structures: Mapping[str, Mapping], now: datetime, min_docs_for_unusual: int = 5
                       ) -> List[Dict[str, object]]:
    items: List[Dict[str, object]] = []
    for pid, rec in sorted(pattern_records.items()):
        if rec.get("status") in (NEW_PATTERN_CANDIDATE, REVIEW_CANDIDATE, STRONG_PATTERN_CANDIDATE):
            items.append(_item(K_NEW_PATTERN, pid,
                               f"pattern reached {rec['status']} (support {rec.get('support_count')}, "
                               f"regimes {rec.get('regime_count')}); supervisor decides promotion",
                               rec.get("evidence_references") or [], now, pattern_status=rec.get("status"),
                               limitations=rec.get("limitations") or []))
    # pattern conflict: 同じ evidence + target で outlook direction が反対
    seen_pairs = set()
    by_key: Dict[str, List[Mapping]] = {}
    for pid, rec in pattern_records.items():
        comp = rec.get("components") or {}
        if comp.get("pattern_type") != "EVIDENCE_OUTLOOK":
            continue
        target = next((p for p in comp.get("outlook") or [] if str(p).startswith("target=")), "")
        key = ",".join(comp.get("evidence") or []) + "|" + target
        by_key.setdefault(key, []).append(rec)
    for key, recs in by_key.items():
        dirs = {next((p for p in (r.get("components") or {}).get("outlook") or [] if str(p).startswith("dir=")), "") for r in recs}
        if "dir=UP" in dirs and "dir=DOWN" in dirs:
            subject = "|".join(sorted(str(r["pattern_id"]) for r in recs))
            if subject not in seen_pairs:
                seen_pairs.add(subject)
                items.append(_item(K_PATTERN_CONFLICT, subject,
                                   "same evidence and target lead to opposite outlook directions across documents",
                                   [d for r in recs for d in (r.get("supporting_document_ids") or [])], now))
    for c in conflicts:
        items.append(_item(K_DNA_CONFLICT, str(c.get("conflict_id")),
                           f"corpus pattern {c.get('pattern_id')} conflicts with Compass DNA rule {c.get('rule_id')}; "
                           "neither side judged", c.get("evidence_references") or [], now,
                           rule_id=c.get("rule_id"), pattern_id=c.get("pattern_id")))
    regime_counts: Dict[str, int] = {}
    for s in structures.values():
        key = str((s.get("regime") or {}).get("regime_key", "regime:UNKNOWN"))
        regime_counts[key] = regime_counts.get(key, 0) + 1
    for doc, s in sorted(structures.items()):
        os_ = s.get("outlook_summary") or {}
        if not s.get("outlook") or os_.get("primary_direction") in (None, "", "NOT_STATED"):
            items.append(_item(K_LOW_CONFIDENCE, doc, "no outlook direction could be extracted deterministically",
                               [os_.get("primary_observation_id", "")], now))
        theme = (s.get("main_theme") or {}).get("category", "")
        if theme in ("OTHER", "UNKNOWN"):
            items.append(_item(K_NEW_THEME, doc, "main theme falls outside the controlled category vocabulary",
                               [(s.get("main_theme") or {}).get("source_observation_id", "")], now))
        key = str((s.get("regime") or {}).get("regime_key", "regime:UNKNOWN"))
        if len(structures) >= min_docs_for_unusual and key != "regime:UNKNOWN" and regime_counts.get(key, 0) == 1:
            items.append(_item(K_UNUSUAL_REGIME, doc, "regime signature observed only once in the corpus",
                               [], now, regime_key=key))
    return items
