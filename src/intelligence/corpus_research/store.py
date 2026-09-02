"""Research store（Phase 3.8）— canonical JSONL append-only、idempotent、rebuild 可能な derived state。

Corpus store（3.7）とは別 root（<data_root>/compass_research）。research artifact には本文を入れない。
`digest()` は timestamps / run id を除いた現行 derived state の content hash（incremental ≈ rebuild の検証用）。
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Dict, Iterator, List, Mapping, Optional, Sequence

from ..core.paths import data_root
from .config import RESEARCH_ROOT_NAME

CANONICAL: Dict[str, tuple] = {
    "structures": ("structures.jsonl", "structure_id"),
    "similarities": ("similarities.jsonl", "similarity_id"),
    "assignments": ("assignments.jsonl", "assignment_id"),
    "patterns": ("patterns.jsonl", "pattern_record_id"),
    "dna_comparisons": ("dna_comparisons.jsonl", "comparison_id"),
    "conflicts": ("conflicts.jsonl", "conflict_id"),
    "benchmarks": ("benchmarks.jsonl", "benchmark_id"),
    "review_queue": ("review_queue.jsonl", "review_id"),
    "runs": ("runs.jsonl", "run_id"),
}
STATE_FILE = "state.json"
SNAPSHOT_FILE = "research_snapshot.json"
REGISTRY_FILE = "pattern_registry.json"
_VOLATILE_KEYS = ("created_at", "run_id", "started_at", "finished_at", "at", "duration_seconds")


def research_root(base: Optional[Path] = None) -> Path:
    return Path(base or data_root()) / RESEARCH_ROOT_NAME


def _strip_volatile(obj):
    if isinstance(obj, dict):
        return {k: _strip_volatile(v) for k, v in sorted(obj.items()) if k not in _VOLATILE_KEYS}
    if isinstance(obj, list):
        return [_strip_volatile(v) for v in obj]
    return obj


class ResearchStore:
    def __init__(self, root: Path) -> None:
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self._rows: Dict[str, List[Dict]] = {}
        self._ids: Dict[str, set] = {}

    # ------------------------------------------------------------- canonical
    def path_of(self, name: str) -> Path:
        return self.root / CANONICAL[name][0]

    def iter_canonical(self, name: str) -> Iterator[Dict]:
        path = self.path_of(name)
        if not path.exists():
            return
        with path.open(encoding="utf-8") as handle:
            for line in handle:
                line = line.strip()
                if line:
                    try:
                        yield json.loads(line)
                    except json.JSONDecodeError:
                        continue

    def rows(self, name: str) -> List[Dict]:
        if name not in self._rows:
            self._rows[name] = list(self.iter_canonical(name))
            key = CANONICAL[name][1]
            self._ids[name] = {str(r.get(key, "")) for r in self._rows[name]}
        return self._rows[name]

    def append(self, name: str, rows: Sequence[Mapping]) -> Dict[str, int]:
        key = CANONICAL[name][1]
        cache = self.rows(name)
        ids = self._ids[name]
        added = skipped = 0
        with self.path_of(name).open("a", encoding="utf-8") as handle:
            for data in rows:
                rid = str(data.get(key, ""))
                if not rid or rid in ids:
                    skipped += 1
                    continue
                d = dict(data)
                handle.write(json.dumps(d, ensure_ascii=False, default=str) + "\n")
                cache.append(d)
                ids.add(rid)
                added += 1
        return {"added": added, "skipped": skipped}

    def counts(self) -> Dict[str, int]:
        return {name: len(self.rows(name)) for name in CANONICAL}

    # ------------------------------------------------------------- state
    def state(self) -> Dict:
        path = self.root / STATE_FILE
        if not path.is_file():
            return {"analyzed": {}}
        try:
            data = json.loads(path.read_text(encoding="utf-8")) or {}
        except (OSError, json.JSONDecodeError):
            data = {}
        data.setdefault("analyzed", {})
        return data

    def save_state(self, data: Mapping) -> None:
        (self.root / STATE_FILE).write_text(json.dumps(dict(data), ensure_ascii=False, indent=1, default=str),
                                            encoding="utf-8")

    # ------------------------------------------------------------- current views
    def current_structures(self, version_key: str) -> Dict[str, Dict]:
        """document → 現行 version set の最新 structure（created_at 最新）。"""
        out: Dict[str, Dict] = {}
        for s in self.rows("structures"):
            if str(s.get("version_key", "")) != version_key:
                continue
            doc = str(s.get("document_id", ""))
            if doc not in out or str(s.get("created_at", "")) >= str(out[doc].get("created_at", "")):
                out[doc] = s
        return out

    def structures_for(self, document_id: str) -> List[Dict]:
        return [s for s in self.rows("structures") if str(s.get("document_id", "")) == document_id]

    def assignments_current(self, pattern_version: str, document_ids: Optional[Sequence[str]] = None) -> List[Dict]:
        docs = set(document_ids) if document_ids is not None else None
        return [a for a in self.rows("assignments") if str(a.get("pattern_version", "")) == pattern_version
                and (docs is None or str(a.get("document_id", "")) in docs)]

    def pattern_records_current(self, pattern_version: str) -> Dict[str, Dict]:
        out: Dict[str, Dict] = {}
        for r in self.rows("patterns"):
            if str(r.get("pattern_version", "")) != pattern_version:
                continue
            out[str(r["pattern_id"])] = r          # append 順 = 時系列。最後が最新
        return out

    def similarities_current(self, version: str) -> List[Dict]:
        return [s for s in self.rows("similarities") if str(s.get("method_version", "")) == version]

    def review_items(self) -> List[Dict]:
        return list(self.rows("review_queue"))

    # ------------------------------------------------------------- equivalence
    def derived_view(self, version_key: str, pattern_version: str, similarity_version: str) -> Dict[str, object]:
        structures = self.current_structures(version_key)
        docs = set(structures)
        return {
            "structures": [_strip_volatile({k: v for k, v in s.items() if k != "structure_id"} | {"structure_id": s["structure_id"]})
                           for _, s in sorted(structures.items())],
            "assignments": sorted((_strip_volatile(a) for a in self.assignments_current(pattern_version)
                                   if str(a.get("document_id")) in docs), key=lambda a: a["assignment_id"]),
            "patterns": sorted((_strip_volatile(r) for r in self.pattern_records_current(pattern_version).values()),
                               key=lambda r: r["pattern_id"]),
            "similarities": sorted((_strip_volatile(s) for s in self.similarities_current(similarity_version)
                                    if s.get("document_a") in docs and s.get("document_b") in docs),
                                   key=lambda s: s["similarity_id"]),
            "dna_comparisons": sorted((_strip_volatile(c) for c in self.rows("dna_comparisons")
                                       if c["pattern_id"] in self.pattern_records_current(pattern_version)),
                                      key=lambda c: c["comparison_id"]),
        }

    def digest(self, version_key: str, pattern_version: str, similarity_version: str) -> str:
        view = self.derived_view(version_key, pattern_version, similarity_version)
        blob = json.dumps(view, ensure_ascii=False, sort_keys=True, default=str)
        return hashlib.sha256(blob.encode("utf-8")).hexdigest()

    def write_json(self, name: str, payload: Mapping) -> Path:
        path = self.root / name
        path.write_text(json.dumps(dict(payload), ensure_ascii=False, indent=1, default=str), encoding="utf-8")
        return path
