"""Pre-backfill inventory＋input fingerprint（Phase 2-C）。

BACKFILL IS A DATA MIGRATION, NOT A FILE COPY:
実行前に入力を実測し（件数を盲信しない）、datasetのfingerprintを固定して
移行途中の入力変化を検出可能にする。入力（legacy shards）はREAD ONLY。
"""
from __future__ import annotations

import hashlib
import json
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Mapping, Tuple


@dataclass(frozen=True, kw_only=True)
class ShardInfo:
    path: str  # dataset root相対
    size_bytes: int
    sha256: str
    records: int
    invalid_lines: int


@dataclass(frozen=True, kw_only=True)
class InputInventory:
    """入力実測（P2-Aの「3,056件」を再計測で検証する）。"""

    dataset_root: str
    shard_count: int
    total_records: int
    invalid_json_lines: int
    date_range: Tuple[str, str]  # (min, max) published_at_utc
    publisher_counts: Mapping[str, int]
    language_counts: Mapping[str, int]
    source_domain_counts: Mapping[str, int]
    missing_field_counts: Mapping[str, int]  # フィールド別欠損数
    date_inferred_count: int
    duplicate_legacy_ids: int
    legacy_annotation_present: int  # INTERPRETED系フィールドを1つ以上持つ記事数
    schema_variants: Mapping[str, int]  # フィールド集合hash別の件数（schemaゆれ検出）
    shards: Tuple[ShardInfo, ...] = field(default=())

    @property
    def input_fingerprint(self) -> str:
        """dataset全体のfingerprint（shard一覧×hash から決定論導出）。"""
        basis = "\x1f".join(f"{s.path}:{s.size_bytes}:{s.sha256}" for s in self.shards)
        return hashlib.sha256(basis.encode("utf-8")).hexdigest()


_CHECK_FIELDS = ("title_original", "canonical_url", "published_at_utc",
                 "fetched_at_utc", "description", "source_name", "language")
_ANNOTATION_FIELDS = ("importance_score", "market_impact_score", "themes",
                      "sentiment", "expected_direction", "event_type")


def build_inventory(dataset_root: Path) -> InputInventory:
    """shard群をREAD ONLYで走査し実測inventoryを作る。"""
    root = Path(dataset_root)
    shards: List[ShardInfo] = []
    publishers: Counter = Counter()
    languages: Counter = Counter()
    domains: Counter = Counter()
    missing: Counter = Counter()
    variants: Counter = Counter()
    ids: Counter = Counter()
    dates: List[str] = []
    total = invalid = inferred = annotated = 0

    for shard_path in sorted(root.rglob("*.jsonl")):
        data = shard_path.read_bytes()
        records = bad = 0
        for line in data.decode("utf-8", errors="replace").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                a = json.loads(line)
            except json.JSONDecodeError:
                bad += 1
                continue
            records += 1
            publishers[a.get("source_name", "")] += 1
            languages[a.get("language", "")] += 1
            domains[a.get("source_domain", "")] += 1
            for f in _CHECK_FIELDS:
                if not a.get(f):
                    missing[f] += 1
            if a.get("date_inferred"):
                inferred += 1
            if any(a.get(f) for f in _ANNOTATION_FIELDS):
                annotated += 1
            if a.get("published_at_utc"):
                dates.append(a["published_at_utc"])
            ids[a.get("article_id", "")] += 1
            variants[hashlib.sha256(
                ",".join(sorted(a.keys())).encode()).hexdigest()[:8]] += 1
        total += records
        invalid += bad
        shards.append(ShardInfo(
            path=str(shard_path.relative_to(root)), size_bytes=len(data),
            sha256=hashlib.sha256(data).hexdigest(), records=records,
            invalid_lines=bad))

    duplicates = sum(c - 1 for i, c in ids.items() if i and c > 1)
    return InputInventory(
        dataset_root=str(root),
        shard_count=len(shards),
        total_records=total,
        invalid_json_lines=invalid,
        date_range=(min(dates)[:19] if dates else "", max(dates)[:19] if dates else ""),
        publisher_counts=dict(publishers),
        language_counts=dict(languages),
        source_domain_counts=dict(domains),
        missing_field_counts=dict(missing),
        date_inferred_count=inferred,
        duplicate_legacy_ids=duplicates,
        legacy_annotation_present=annotated,
        schema_variants=dict(variants),
        shards=tuple(shards),
    )


def iter_records(dataset_root: Path):
    """決定論的順序（shardソート×行順）でlegacy記事を列挙する。

    yield: (record_index, legacy_locator "shard:line", article_dict | None(invalid))
    """
    root = Path(dataset_root)
    index = 0
    for shard_path in sorted(root.rglob("*.jsonl")):
        rel = str(shard_path.relative_to(root))
        with shard_path.open(encoding="utf-8") as f:
            for line_no, line in enumerate(f, 1):
                line = line.strip()
                if not line:
                    continue
                locator = f"{rel}:{line_no}"
                try:
                    yield index, locator, json.loads(line)
                except json.JSONDecodeError:
                    yield index, locator, None
                index += 1
