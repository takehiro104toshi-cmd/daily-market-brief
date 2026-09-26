"""P6-B4B — Entity catalog の version 指定 loader と純 resolution API。

- `load_entity_catalog_version(path, *, expected_version, cutoff)`: expected_version 完全一致・published_at ≤ cutoff・
  digest 一致でのみ `EntityCatalogSnapshot` を返す。「latest」解決・fallback・現在時刻はない。
- `resolve_entity_token(snapshot, token, *, context=None, as_of=None)`: EXACT_ID / EXACT_SAFE_ALIAS / CONTEXT_ALIAS /
  AMBIGUOUS / UNKNOWN / INACTIVE / SUPERSEDED。context alias は context_terms の決定論的一致（正規化 token の集合交差）が
  無ければ解決しない。複数 entity が残れば AMBIGUOUS（先頭を選ばない、順位付けしない）。as_of は世界時間の有効性判定
  （旧 cutoff では旧 identity を保つ。後継への自動付け替えはしない）。
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Optional, Sequence, Tuple

from .entity_model import ENTITY_CATALOG_SCHEMA_VERSION, EntityCatalogSnapshot, EntityRecord
from .knowledge_loader import (KnowledgeError, SnapshotEnvelope, check_digest, check_version_and_cutoff, content_digest,
                               knowledge_path, normalize_token, read_snapshot_envelope)

ENTITY_CATALOG_KNOWLEDGE_KIND = "entity_catalog"
ENTITY_CATALOG_VERSION_KEY = "catalog_version"
ENTITY_CATALOG_RECORDS_KEY = "entities"


# ---------------------------------------------------------------- loading


def entity_catalog_path(knowledge_root: Path, version: str) -> Path:
    return knowledge_path(knowledge_root, ENTITY_CATALOG_KNOWLEDGE_KIND, version)


def _snapshot_from_envelope(envelope: SnapshotEnvelope, *, digest: str) -> EntityCatalogSnapshot:
    entities = tuple(EntityRecord.from_plain(record, where=f"{envelope.document_name}.entities[{index}]")
                     for index, record in enumerate(envelope.records))
    return EntityCatalogSnapshot(schema_version=envelope.schema_version, catalog_version=envelope.version,
                                 published_at=envelope.published_at, content_digest=digest, entities=entities)


def compute_entity_catalog_digest(path: Path) -> str:
    """authoring 補助: 構造検証を全て行ったうえで semantic digest を返す（宣言 digest との比較だけを行わない）。"""
    envelope = read_snapshot_envelope(path, schema_version=ENTITY_CATALOG_SCHEMA_VERSION,
                                      version_key=ENTITY_CATALOG_VERSION_KEY, records_key=ENTITY_CATALOG_RECORDS_KEY,
                                      allow_missing_digest=True)
    snapshot = _snapshot_from_envelope(envelope, digest="0" * 64)
    return content_digest(snapshot.semantic_payload())


def load_entity_catalog_version(path: Path, *, expected_version: str, cutoff: datetime) -> EntityCatalogSnapshot:
    envelope = read_snapshot_envelope(path, schema_version=ENTITY_CATALOG_SCHEMA_VERSION,
                                      version_key=ENTITY_CATALOG_VERSION_KEY, records_key=ENTITY_CATALOG_RECORDS_KEY)
    check_version_and_cutoff(envelope, expected_version=expected_version, cutoff=cutoff)
    snapshot = _snapshot_from_envelope(envelope, digest=envelope.content_digest)
    check_digest(envelope, content_digest(snapshot.semantic_payload()))
    return snapshot


# ---------------------------------------------------------------- resolution（純）


class EntityResolutionStatus(str, Enum):
    EXACT_ID = "EXACT_ID"
    EXACT_SAFE_ALIAS = "EXACT_SAFE_ALIAS"
    CONTEXT_ALIAS = "CONTEXT_ALIAS"
    AMBIGUOUS = "AMBIGUOUS"
    UNKNOWN = "UNKNOWN"
    INACTIVE = "INACTIVE"            # 一致したが as_of で有効期間外（後継なし）、または catalog 上 retired
    SUPERSEDED = "SUPERSEDED"        # 一致したが as_of ≥ valid_to で後継 entity がある（自動付け替えはしない）


@dataclass(frozen=True, kw_only=True)
class EntityResolution:
    status: EntityResolutionStatus
    token: str
    normalized_token: str
    entity_id: str = ""
    matched_by: str = ""                  # "id" / "safe_alias" / "context_alias"
    matched_context_terms: Tuple[str, ...] = ()
    candidates: Tuple[str, ...] = ()      # AMBIGUOUS のときの候補 id（id 順。順位ではない）
    superseded_by: Tuple[str, ...] = ()
    diagnostics: Tuple[str, ...] = ()


def _as_of_day(as_of: object) -> Optional[date]:
    if as_of is None:
        return None
    if isinstance(as_of, datetime):
        if as_of.tzinfo is None or as_of.utcoffset() is None:
            raise KnowledgeError("INVALID_AS_OF", "as_of datetime must be aware")
        return as_of.astimezone(timezone.utc).date()
    if isinstance(as_of, date):
        return as_of
    raise KnowledgeError("INVALID_AS_OF", "as_of must be a date or an aware datetime")


def _normalized_context(context: Optional[Sequence[str]]) -> Tuple[str, ...]:
    if context is None:
        return ()
    if isinstance(context, str) or not all(isinstance(c, str) for c in context):
        raise KnowledgeError("INVALID_TYPE", "context must be a sequence of str surfaces (not a single str)")
    return tuple(sorted({normalize_token(c) for c in context} - {""}))


def _finish(snapshot: EntityCatalogSnapshot, entity: EntityRecord, *, token: str, normalized: str, matched_by: str,
            matched_terms: Tuple[str, ...], day: Optional[date]) -> EntityResolution:
    base = dict(token=token, normalized_token=normalized, entity_id=entity.entity_id, matched_by=matched_by,
                matched_context_terms=matched_terms)
    if entity.is_retired:
        return EntityResolution(status=EntityResolutionStatus.INACTIVE, diagnostics=(f"RETIRED_IN:{entity.retired_in_version}",),
                                superseded_by=entity.superseded_by, **base)
    if day is not None and not entity.in_force_on(day):
        if entity.superseded_by and entity.valid_to is not None and day >= entity.valid_to:
            return EntityResolution(status=EntityResolutionStatus.SUPERSEDED, superseded_by=entity.superseded_by,
                                    diagnostics=(f"VALID_TO:{entity.valid_to.isoformat()}",), **base)
        reason = (f"VALID_FROM:{entity.valid_from.isoformat()}" if entity.valid_from is not None and day < entity.valid_from
                  else f"VALID_TO:{entity.valid_to.isoformat()}" if entity.valid_to is not None else "OUT_OF_RANGE")
        return EntityResolution(status=EntityResolutionStatus.INACTIVE, diagnostics=(reason,), **base)
    status = {"id": EntityResolutionStatus.EXACT_ID, "safe_alias": EntityResolutionStatus.EXACT_SAFE_ALIAS,
              "context_alias": EntityResolutionStatus.CONTEXT_ALIAS}[matched_by]
    return EntityResolution(status=status, **base)


def resolve_entity_token(snapshot: EntityCatalogSnapshot, token: str, *, context: Optional[Sequence[str]] = None,
                         as_of: Optional[object] = None) -> EntityResolution:
    if not isinstance(token, str):
        raise KnowledgeError("INVALID_TYPE", "token must be a str")
    normalized = normalize_token(token)
    day = _as_of_day(as_of)
    context_tokens = _normalized_context(context)
    if normalized == "":
        return EntityResolution(status=EntityResolutionStatus.UNKNOWN, token=token, normalized_token=normalized,
                                diagnostics=("EMPTY_TOKEN",))
    exact = snapshot.entity(normalized)
    if exact is not None:
        return _finish(snapshot, exact, token=token, normalized=normalized, matched_by="id", matched_terms=(), day=day)
    safe_owner = snapshot.safe_alias_owner(normalized)
    if safe_owner is not None:
        entity = snapshot.entity(safe_owner)
        assert entity is not None
        return _finish(snapshot, entity, token=token, normalized=normalized, matched_by="safe_alias", matched_terms=(), day=day)
    owners = snapshot.context_alias_owners(normalized)
    if not owners:
        return EntityResolution(status=EntityResolutionStatus.UNKNOWN, token=token, normalized_token=normalized)
    if not context_tokens:
        return EntityResolution(status=EntityResolutionStatus.UNKNOWN, token=token, normalized_token=normalized,
                                diagnostics=("CONTEXT_REQUIRED",))
    hits = []
    for owner in owners:
        entity = snapshot.entity(owner)
        assert entity is not None
        matched = tuple(t for t in entity.normalized_context_terms() if t in context_tokens)
        if matched:
            hits.append((owner, matched))
    if not hits:
        return EntityResolution(status=EntityResolutionStatus.UNKNOWN, token=token, normalized_token=normalized,
                                diagnostics=("CONTEXT_NOT_MATCHED",))
    if len(hits) > 1:
        return EntityResolution(status=EntityResolutionStatus.AMBIGUOUS, token=token, normalized_token=normalized,
                                candidates=tuple(sorted(owner for owner, _ in hits)), diagnostics=("MULTIPLE_CONTEXT_OWNERS",))
    owner, matched = hits[0]
    entity = snapshot.entity(owner)
    assert entity is not None
    return _finish(snapshot, entity, token=token, normalized=normalized, matched_by="context_alias", matched_terms=matched, day=day)
