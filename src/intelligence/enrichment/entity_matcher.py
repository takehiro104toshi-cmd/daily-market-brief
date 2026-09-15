"""L2 Entity Matching（Phase 2-E・高precision優先）。

FALSE ENTITY LINK IS WORSE THAN MISSED ENTITY LINK:
- safe alias … 単独マッチ可（catalogが固有性を保証した表記のみ）
- context alias … **文脈語の共起が無ければlinkしない**（Apple/Meta/Amazon等）。
  共起なしはReviewQueue候補として記録（黙って捨てない・linkもしない）
- ticker … 明示記法（$NVDA / NASDAQ:NVDA / (7203.T)）のみ。
  裸の大文字語（AI/IT/US/CAT等）は**決してticker扱いしない**（走査すらしない）
- 未知ticker記法 … linkせずReviewQueue候補へ

evidence: マッチした実表記とフィールドを保持（説明可能性）。
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Dict, List, Mapping, Tuple

from ..databank.news_model import ClassificationDimension, EntityKind
from .catalog import EntityCatalog, EntityEntry
from .textmatch import find_term

ENTITY_MATCHER_VERSION = "1.0.0"

#: entity kind → 分類次元（COMPANYはticker次元の追加レコードをengineが併産する）
KIND_TO_DIMENSION = {
    EntityKind.COMPANY: ClassificationDimension.COMPANY,
    EntityKind.COUNTRY: ClassificationDimension.COUNTRY,
    EntityKind.CENTRAL_BANK: ClassificationDimension.CENTRAL_BANK,
    EntityKind.GOVERNMENT: ClassificationDimension.GOVERNMENT,
    EntityKind.PERSON: ClassificationDimension.PERSON,
    EntityKind.INDEX: ClassificationDimension.INDEX,
    EntityKind.COMMODITY: ClassificationDimension.COMMODITY,
    EntityKind.CURRENCY: ClassificationDimension.CURRENCY,
}

#: 明示ticker記法のみ（裸の大文字語は対象外——TICKER SAFETY）
_TICKER_PATTERNS = (
    re.compile(r"\$([A-Z]{1,5})(?![A-Za-z0-9])"),
    re.compile(r"(?:NASDAQ|NYSE|TSE|TYO|KRX|LSE):\s?([A-Z0-9.]{1,8})(?![A-Za-z0-9])"),
    re.compile(r"\((\d{4}\.T)\)"),
)


@dataclass(frozen=True, kw_only=True)
class EntityMatch:
    entity: EntityEntry
    dimension: ClassificationDimension
    value: str  # 分類値（countryはISOコード・他はentity_id）
    matched_via: str  # safe_alias / context_alias / ticker_notation
    evidence_field: str
    evidence_text: str


@dataclass(frozen=True, kw_only=True)
class EntityMatchOutcome:
    matches: Tuple[EntityMatch, ...]
    ambiguous_skipped: Tuple[Tuple[str, str, str], ...]  # (entity_id, alias, field)
    unknown_tickers: Tuple[Tuple[str, str], ...]         # (ticker表記, field)


def _value_for(entity: EntityEntry) -> str:
    if entity.kind is EntityKind.COUNTRY:
        return entity.code  # country次元の値はISOコード（news_model既存例に整合）
    return entity.entity_id


def match_entities(catalog: EntityCatalog, fields: Mapping[str, str]) -> EntityMatchOutcome:
    """fields（例: {"headline": ..., "summary": ...}）→ 高precisionマッチ結果。

    同一entityは最初のマッチ1件に集約（multi-labelは**entity間**で許可）。
    """
    combined = " \n ".join(v for v in fields.values() if v)
    matched: Dict[str, EntityMatch] = {}
    ambiguous: List[Tuple[str, str, str]] = []
    unknown: List[Tuple[str, str]] = []

    # --- 明示ticker記法（最優先: 決定論・最も強い明示シグナル） ---
    for field_name, text in fields.items():
        if not text:
            continue
        for pattern in _TICKER_PATTERNS:
            for m in pattern.finditer(text):
                symbol = m.group(1)
                entity = catalog.by_ticker(symbol)
                if entity is None:
                    unknown.append((m.group(0), field_name))
                    continue
                if entity.entity_id not in matched:
                    matched[entity.entity_id] = EntityMatch(
                        entity=entity, dimension=KIND_TO_DIMENSION[entity.kind],
                        value=_value_for(entity), matched_via="ticker_notation",
                        evidence_field=field_name, evidence_text=m.group(0))

    # --- alias（safe → context の順） ---
    for entity in catalog.entities:
        if entity.entity_id in matched:
            continue
        hit = None
        for field_name, text in fields.items():
            if not text:
                continue
            for alias in entity.aliases_safe:
                found = find_term(text, alias)
                if found:
                    hit = ("safe_alias", field_name, found)
                    break
            if hit:
                break
        if hit is None and entity.aliases_context:
            for field_name, text in fields.items():
                if not text:
                    continue
                for alias in entity.aliases_context:
                    found = find_term(text, alias)
                    if not found:
                        continue
                    # 文脈条件: context_termsのいずれかが記事全体に共起すること
                    if any(find_term(combined, t) for t in entity.context_terms):
                        hit = ("context_alias", field_name, found)
                    else:
                        ambiguous.append((entity.entity_id, alias, field_name))
                    break
                if hit:
                    break
        if hit:
            via, field_name, found = hit
            matched[entity.entity_id] = EntityMatch(
                entity=entity, dimension=KIND_TO_DIMENSION[entity.kind],
                value=_value_for(entity), matched_via=via,
                evidence_field=field_name, evidence_text=found)

    return EntityMatchOutcome(
        matches=tuple(matched.values()),
        ambiguous_skipped=tuple(dict.fromkeys(ambiguous)),
        unknown_tickers=tuple(dict.fromkeys(unknown)),
    )
