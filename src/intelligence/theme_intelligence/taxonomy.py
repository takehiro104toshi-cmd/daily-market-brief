"""P6-B4B — Theme taxonomy の version 指定 loader と純 normalization API。

- `load_taxonomy_version(path, *, expected_version, cutoff)`: expected_version 完全一致・published_at ≤ cutoff・digest 一致
  でのみ `TaxonomySnapshot` を返す。「latest」解決・別 version への fallback・現在時刻はない。
- `resolve_taxonomy_token(snapshot, token)`: EXACT_SLUG / EXACT_ALIAS / DEPRECATED / AMBIGUOUS / UNKNOWN。fuzzy /
  部分一致 / embedding なし。親へ伝播しない。
- `validate_theme_taxonomy_refs(snapshot, slugs)`: Foundation METADATA TAXONOMY の値（slug 集合）を検証する純 helper。
  ThemeMetadataRecord を書かない。
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Iterable, List, Tuple

from .knowledge_loader import (KnowledgeError, SnapshotEnvelope, check_digest, check_version_and_cutoff, content_digest,
                               knowledge_path, normalize_token, read_snapshot_envelope)
from .taxonomy_model import TAXONOMY_SCHEMA_VERSION, TaxonomyNode, TaxonomySnapshot

TAXONOMY_KNOWLEDGE_KIND = "taxonomy"
TAXONOMY_VERSION_KEY = "taxonomy_version"
TAXONOMY_RECORDS_KEY = "nodes"


# ---------------------------------------------------------------- loading


def taxonomy_path(knowledge_root: Path, version: str) -> Path:
    return knowledge_path(knowledge_root, TAXONOMY_KNOWLEDGE_KIND, version)


def _snapshot_from_envelope(envelope: SnapshotEnvelope, *, digest: str) -> TaxonomySnapshot:
    nodes = tuple(TaxonomyNode.from_plain(record, where=f"{envelope.document_name}.nodes[{index}]")
                  for index, record in enumerate(envelope.records))
    return TaxonomySnapshot(schema_version=envelope.schema_version, taxonomy_version=envelope.version,
                            published_at=envelope.published_at, content_digest=digest, nodes=nodes)


def compute_taxonomy_digest(path: Path) -> str:
    """authoring 補助: 構造検証を全て行ったうえで semantic digest を返す（宣言 digest との比較だけを行わない）。"""
    envelope = read_snapshot_envelope(path, schema_version=TAXONOMY_SCHEMA_VERSION, version_key=TAXONOMY_VERSION_KEY,
                                      records_key=TAXONOMY_RECORDS_KEY, allow_missing_digest=True)
    snapshot = _snapshot_from_envelope(envelope, digest="0" * 64)
    return content_digest(snapshot.semantic_payload())


def load_taxonomy_version(path: Path, *, expected_version: str, cutoff: datetime) -> TaxonomySnapshot:
    envelope = read_snapshot_envelope(path, schema_version=TAXONOMY_SCHEMA_VERSION, version_key=TAXONOMY_VERSION_KEY,
                                      records_key=TAXONOMY_RECORDS_KEY)
    check_version_and_cutoff(envelope, expected_version=expected_version, cutoff=cutoff)
    snapshot = _snapshot_from_envelope(envelope, digest=envelope.content_digest)
    check_digest(envelope, content_digest(snapshot.semantic_payload()))
    return snapshot


# ---------------------------------------------------------------- resolution（純）


class TaxonomyResolutionStatus(str, Enum):
    EXACT_SLUG = "EXACT_SLUG"
    EXACT_ALIAS = "EXACT_ALIAS"
    DEPRECATED = "DEPRECATED"        # slug / alias は一致したが、この version では deprecated（superseded_by を併記）
    AMBIGUOUS = "AMBIGUOUS"          # 構築時検証により通常到達しない（防御的に保持）
    UNKNOWN = "UNKNOWN"


@dataclass(frozen=True, kw_only=True)
class TaxonomyResolution:
    status: TaxonomyResolutionStatus
    token: str
    normalized_token: str
    slug: str = ""
    matched_by: str = ""                       # "slug" / "alias"
    superseded_by: Tuple[str, ...] = ()
    candidates: Tuple[str, ...] = ()
    diagnostics: Tuple[str, ...] = ()


def resolve_taxonomy_token(snapshot: TaxonomySnapshot, token: str) -> TaxonomyResolution:
    if not isinstance(token, str):
        raise KnowledgeError("INVALID_TYPE", "token must be a str")
    normalized = normalize_token(token)
    if normalized == "":
        return TaxonomyResolution(status=TaxonomyResolutionStatus.UNKNOWN, token=token, normalized_token=normalized,
                                  diagnostics=("EMPTY_TOKEN",))
    owner = snapshot.token_owner(normalized)
    if owner is None:
        return TaxonomyResolution(status=TaxonomyResolutionStatus.UNKNOWN, token=token, normalized_token=normalized)
    slug, matched_by = owner
    node = snapshot.node(slug)
    assert node is not None
    if node.is_deprecated:
        return TaxonomyResolution(status=TaxonomyResolutionStatus.DEPRECATED, token=token, normalized_token=normalized,
                                  slug=slug, matched_by=matched_by, superseded_by=node.superseded_by,
                                  diagnostics=(f"DEPRECATED_IN:{node.deprecated_in_version}",))
    status = TaxonomyResolutionStatus.EXACT_SLUG if matched_by == "slug" else TaxonomyResolutionStatus.EXACT_ALIAS
    return TaxonomyResolution(status=status, token=token, normalized_token=normalized, slug=slug, matched_by=matched_by)


# ---------------------------------------------------------------- Foundation METADATA TAXONOMY の値検証（純。書かない）


class TaxonomyRefStatus(str, Enum):
    VALID = "VALID"
    INVALID = "INVALID"


@dataclass(frozen=True, kw_only=True)
class TaxonomyRefValidation:
    status: TaxonomyRefStatus
    taxonomy_version: str
    valid_slugs: Tuple[str, ...]
    unknown_slugs: Tuple[str, ...]
    deprecated_slugs: Tuple[str, ...]
    duplicate_slugs: Tuple[str, ...]
    malformed_values: Tuple[str, ...]
    diagnostics: Tuple[str, ...]


def validate_theme_taxonomy_refs(snapshot: TaxonomySnapshot, taxonomy_slugs: Iterable[str]) -> TaxonomyRefValidation:
    """Foundation `ThemeMetadataRecord(field=TAXONOMY).value` に置く slug 集合が、pinned snapshot で有効かを判定する。

    複数 slug は正当。slug は正確一致のみ（alias は不可: metadata には slug を書く）。deprecated slug は INVALID
    （superseded_by を diagnostics に載せる）。Foundation へは何も書かない。
    """
    values = list(taxonomy_slugs)
    malformed = tuple(sorted({str(v) for v in values if not isinstance(v, str) or v != v.strip() or v == ""}))
    clean = [v for v in values if isinstance(v, str) and v == v.strip() and v != ""]
    seen: List[str] = []
    duplicates: List[str] = []
    for value in clean:
        (duplicates if value in seen else seen).append(value)
    valid: List[str] = []
    unknown: List[str] = []
    deprecated: List[str] = []
    diagnostics: List[str] = []
    for slug in sorted(set(clean)):
        node = snapshot.node(slug)
        if node is None:
            unknown.append(slug)
        elif node.is_deprecated:
            deprecated.append(slug)
            if node.superseded_by:
                diagnostics.append(f"SUPERSEDED:{slug}->{','.join(node.superseded_by)}")
        else:
            valid.append(slug)
    if not clean and not malformed:
        diagnostics.append("EMPTY_VALUE")
    ok = not unknown and not deprecated and not duplicates and not malformed and bool(valid)
    return TaxonomyRefValidation(
        status=TaxonomyRefStatus.VALID if ok else TaxonomyRefStatus.INVALID, taxonomy_version=snapshot.taxonomy_version,
        valid_slugs=tuple(valid), unknown_slugs=tuple(unknown), deprecated_slugs=tuple(deprecated),
        duplicate_slugs=tuple(sorted(set(duplicates))), malformed_values=malformed, diagnostics=tuple(diagnostics))
