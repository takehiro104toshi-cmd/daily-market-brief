"""Cross-document comparison と explainable similarity（Phase 3.8 §14–§15）。

feature set の重み付き Jaccard。embedding / LLM は使わない（OPTIONAL_FUTURE_ENHANCEMENT）。
出力: similar_document_ids / similarity_score / shared_features / different_features / method_version。
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass
from decimal import Decimal
from typing import Dict, List, Mapping, Sequence, Set, Tuple

from .regime import CORE_REGIME_DIMENSIONS

SIMILARITY_VERSION = "1.0.0"

FEATURE_WEIGHTS: Dict[str, Decimal] = {
    "regime": Decimal("0.25"), "evidence": Decimal("0.25"), "theme": Decimal("0.15"),
    "why": Decimal("0.10"), "outlook": Decimal("0.15"), "risk": Decimal("0.10"),
}
EVIDENCE_TOP_N = 5


def features(structure: Mapping[str, object]) -> Dict[str, Set[str]]:
    labels = dict(structure.get("market_state") or {})
    regime = {f"{d}={labels[d]}" for d in CORE_REGIME_DIMENSIONS if labels.get(d) and labels[d] != "UNKNOWN"}
    evidence = {str(c["category"]) for c in list(structure.get("selected_evidence") or [])[:EVIDENCE_TOP_N]}
    theme = {str((structure.get("main_theme") or {}).get("category", ""))} - {"", "UNKNOWN", "OTHER"}
    ws = dict(structure.get("why_summary") or {})
    why = {f"why={k}" for k, v in ws.items() if v}
    os_ = dict(structure.get("outlook_summary") or {})
    outlook = set()
    if os_.get("primary_direction") and os_["primary_direction"] != "NOT_STATED":
        outlook.add(f"dir={os_['primary_direction']}")
    if os_.get("primary_horizon") and os_["primary_horizon"] != "NOT_STATED":
        outlook.add(f"horizon={os_['primary_horizon']}")
    if os_.get("primary_target") and os_["primary_target"] != "UNKNOWN":
        outlook.add(f"target={os_['primary_target']}")
    rs = dict((structure.get("risk_summary") or {}).get("counts") or {})
    risk = {f"risk={k}" for k, v in rs.items() if v and k not in ("NOT_RISK",)}
    return {"regime": regime, "evidence": evidence, "theme": theme, "why": why, "outlook": outlook, "risk": risk}


def _jaccard(a: Set[str], b: Set[str]) -> Decimal:
    if not a and not b:
        return Decimal("-1")          # 比較不能（両方空）
    union = a | b
    return Decimal(len(a & b)) / Decimal(len(union)) if union else Decimal("0")


@dataclass(frozen=True)
class SimilarityResult:
    similarity_id: str
    document_a: str
    document_b: str
    score: Decimal
    group_scores: Mapping[str, str]
    shared_features: Tuple[str, ...]
    different_features: Tuple[str, ...]
    method_version: str = SIMILARITY_VERSION

    def as_dict(self) -> Dict[str, object]:
        return {"similarity_id": self.similarity_id, "document_a": self.document_a, "document_b": self.document_b,
                "score": str(self.score), "group_scores": dict(self.group_scores),
                "shared_features": list(self.shared_features), "different_features": list(self.different_features),
                "method_version": self.method_version}


def similarity(a: Mapping[str, object], b: Mapping[str, object]) -> SimilarityResult:
    fa, fb = features(a), features(b)
    total_w = Decimal("0")
    acc = Decimal("0")
    groups: Dict[str, str] = {}
    shared: List[str] = []
    different: List[str] = []
    for g, w in FEATURE_WEIGHTS.items():
        j = _jaccard(fa[g], fb[g])
        if j < 0:
            groups[g] = "n/a"
            continue
        total_w += w
        acc += w * j
        groups[g] = str(j.quantize(Decimal("0.001")))
        shared.extend(sorted(fa[g] & fb[g]))
        different.extend(sorted(fa[g] ^ fb[g]))
    score = (acc / total_w).quantize(Decimal("0.001")) if total_w else Decimal("0")
    ida, idb = sorted([str(a["document_id"]), str(b["document_id"])])
    sid = "crsim_" + hashlib.sha1(f"{ida}|{idb}|{SIMILARITY_VERSION}".encode("utf-8")).hexdigest()[:16]
    return SimilarityResult(similarity_id=sid, document_a=ida, document_b=idb, score=score, group_scores=groups,
                            shared_features=tuple(shared), different_features=tuple(different))


def similar_documents(target_id: str, results: Sequence[SimilarityResult], *, top_k: int,
                      min_score: Decimal) -> List[Dict[str, object]]:
    rows = []
    for r in results:
        if target_id not in (r.document_a, r.document_b):
            continue
        other = r.document_b if r.document_a == target_id else r.document_a
        if r.score >= min_score:
            rows.append({"document_id": other, "similarity_score": str(r.score),
                         "shared_features": list(r.shared_features), "different_features": list(r.different_features),
                         "method_version": r.method_version})
    rows.sort(key=lambda x: (-Decimal(x["similarity_score"]), x["document_id"]))
    return rows[:top_k]
