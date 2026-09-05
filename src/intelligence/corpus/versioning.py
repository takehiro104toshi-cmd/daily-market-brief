"""Versioning / re-analysis / supersession（Phase 3.7 §19–§20）。

Corpus record / extraction / structured analysis / coverage labels はそれぞれ version を持つ。
再解析は **append-only**: 新 record が `supersedes` で旧 record を指す。旧 record は削除しない。
production Compass rule へは何も書かない。
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Dict, List, Mapping, Optional, Sequence, Tuple

CORPUS_SCHEMA_VERSION = "1.0.0"


def version_tuple(version: str) -> Tuple[int, ...]:
    parts: List[int] = []
    for token in str(version or "0").split(":")[-1].split("."):
        digits = "".join(ch for ch in token if ch.isdigit())
        parts.append(int(digits) if digits else 0)
    return tuple(parts)


def analysis_record_id(document_id: str, analysis_version: str) -> str:
    seed = f"{document_id}|analysis|{analysis_version}"
    return "csr_" + hashlib.sha1(seed.encode("utf-8")).hexdigest()[:16]


def coverage_label_id(document_id: str, analysis_version: str, thresholds_version: str) -> str:
    seed = f"{document_id}|coverage|{analysis_version}|{thresholds_version}"
    return "csc_" + hashlib.sha1(seed.encode("utf-8")).hexdigest()[:16]


def current_analysis(records: Sequence[Mapping[str, object]]) -> Optional[Mapping[str, object]]:
    """同一 document の analysis record 群から現行を選ぶ（version 最大 → created_at 最新）。"""
    if not records:
        return None
    return sorted(records, key=lambda r: (version_tuple(str(r.get("analysis_version", ""))),
                                          str(r.get("created_at", ""))))[-1]


def supersession_chain(records: Sequence[Mapping[str, object]]) -> List[str]:
    """現行 record から supersedes を辿った id 列（新 → 旧）。"""
    by_id = {str(r.get("record_id", "")): r for r in records}
    current = current_analysis(records)
    chain: List[str] = []
    seen = set()
    node = current
    while node is not None:
        rid = str(node.get("record_id", ""))
        if not rid or rid in seen:
            break
        chain.append(rid)
        seen.add(rid)
        node = by_id.get(str(node.get("supersedes", "")))
    return chain


@dataclass(frozen=True)
class VersionSet:
    schema_version: str
    extractor_version: str
    analysis_version: str
    coverage_thresholds_version: str
    family_markers_version: str

    def as_dict(self) -> Dict[str, str]:
        return {"schema_version": self.schema_version, "extractor_version": self.extractor_version,
                "analysis_version": self.analysis_version,
                "coverage_thresholds_version": self.coverage_thresholds_version,
                "family_markers_version": self.family_markers_version}
