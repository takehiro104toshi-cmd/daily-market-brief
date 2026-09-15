"""Enrichment整合性検証（Phase 2-E）。検知・報告のみ（自動修復しない）。

検査項目（監督者指定の最低限）:
    orphan_classification / unknown_taxonomy_value / unknown_entity_value /
    invalid_classifier_version / duplicate_enrichment / override_conflict /
    revision_linkage_broken / invalid_confidence / llm_unknown_label_in_canonical /
    evidence_span_mismatch
"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Dict, List, Optional, Set, Tuple

from ..databank.news_model import ClassificationDimension, ClassificationProvenance
from .catalog import EntityCatalog
from .model import EnrichmentAction
from .store import JsonlEnrichmentStore
from .taxonomy import EventTaxonomy, ThemeTaxonomy, TIME_HORIZONS

#: entity系次元（値がentity catalog由来であるべき次元。ENTITY_DATABASE provenance時）
_ENTITY_DIMENSIONS = {
    ClassificationDimension.COMPANY, ClassificationDimension.CENTRAL_BANK,
    ClassificationDimension.GOVERNMENT, ClassificationDimension.PERSON,
    ClassificationDimension.INDEX, ClassificationDimension.COMMODITY,
    ClassificationDimension.CURRENCY,
}


@dataclass(frozen=True, kw_only=True)
class ValidationIssue:
    check: str
    record_id: str
    detail: str = ""


def validate_enrichment(
    store: JsonlEnrichmentStore,
    *,
    news_item_ids: Set[str],
    entity_catalog: EntityCatalog,
    theme_taxonomy: ThemeTaxonomy,
    event_taxonomy: EventTaxonomy,
    news_items_by_id: Optional[Dict] = None,  # evidence span検証用（無ければskip）
    document_ids: Optional[Set[str]] = None,  # revision linkage検証用（無ければskip）
) -> Tuple[ValidationIssue, ...]:
    issues: List[ValidationIssue] = []
    theme_slugs = set(theme_taxonomy.slugs())
    event_types = set(event_taxonomy.type_names())
    entity_ids = {e.entity_id for e in entity_catalog.entities}
    country_codes = {e.code for e in entity_catalog.entities if e.code}
    tickers = {e.ticker for e in entity_catalog.entities if e.ticker}
    seen_keys: Dict[Tuple, str] = {}

    for c in store.iter_classifications():
        rid = c.classification_id
        if c.news_item_id not in news_item_ids:
            issues.append(ValidationIssue(check="orphan_classification", record_id=rid,
                                          detail=c.news_item_id))
        machine = c.provenance in (ClassificationProvenance.RULE_BASED,
                                   ClassificationProvenance.ENTITY_DATABASE,
                                   ClassificationProvenance.LLM)
        if machine:
            if c.dimension is ClassificationDimension.THEME and c.value not in theme_slugs:
                check = ("llm_unknown_label_in_canonical"
                         if c.provenance is ClassificationProvenance.LLM
                         else "unknown_taxonomy_value")
                issues.append(ValidationIssue(check=check, record_id=rid, detail=c.value))
            if c.dimension is ClassificationDimension.EVENT_TYPE and c.value not in event_types:
                check = ("llm_unknown_label_in_canonical"
                         if c.provenance is ClassificationProvenance.LLM
                         else "unknown_taxonomy_value")
                issues.append(ValidationIssue(check=check, record_id=rid, detail=c.value))
            if c.dimension is ClassificationDimension.TIME_HORIZON and c.value not in TIME_HORIZONS:
                issues.append(ValidationIssue(check="unknown_taxonomy_value", record_id=rid,
                                              detail=c.value))
            if c.provenance is ClassificationProvenance.ENTITY_DATABASE:
                if c.dimension in _ENTITY_DIMENSIONS and c.value not in entity_ids:
                    issues.append(ValidationIssue(check="unknown_entity_value", record_id=rid,
                                                  detail=c.value))
                if c.dimension is ClassificationDimension.COUNTRY and c.value not in country_codes:
                    issues.append(ValidationIssue(check="unknown_entity_value", record_id=rid,
                                                  detail=c.value))
                if c.dimension is ClassificationDimension.TICKER and c.value not in tickers:
                    issues.append(ValidationIssue(check="unknown_entity_value", record_id=rid,
                                                  detail=c.value))
        if not c.classifier_version:
            issues.append(ValidationIssue(check="invalid_classifier_version", record_id=rid))
        if c.confidence is not None and not (Decimal("0") <= c.confidence <= Decimal("1")):
            issues.append(ValidationIssue(check="invalid_confidence", record_id=rid,
                                          detail=str(c.confidence)))
        key = (c.news_item_id, c.dimension.value, c.value,
               c.classifier_name, c.classifier_version)
        if key in seen_keys:
            issues.append(ValidationIssue(check="duplicate_enrichment", record_id=rid,
                                          detail=seen_keys[key]))
        else:
            seen_keys[key] = rid
        if document_ids is not None and c.basis_document_id \
                and c.basis_document_id not in document_ids:
            issues.append(ValidationIssue(check="revision_linkage_broken", record_id=rid,
                                          detail=c.basis_document_id))
        if news_items_by_id is not None and c.evidence_text \
                and c.evidence_field in ("headline", "summary"):
            item = news_items_by_id.get(c.news_item_id)
            if item is not None:
                text = item.headline if c.evidence_field == "headline" else (item.summary or "")
                if c.evidence_text.lower() not in text.lower():
                    issues.append(ValidationIssue(check="evidence_span_mismatch", record_id=rid,
                                                  detail=f"{c.evidence_field}:{c.evidence_text[:40]}"))

    # イベント整合（override/retractの参照先実在・USER同士のconflict）
    known_cls = {c.classification_id for c in store.iter_classifications()}
    user_values: Dict[Tuple[str, str], Set[str]] = {}
    for e in store.iter_events():
        if e.action in (EnrichmentAction.OVERRIDE, EnrichmentAction.RETRACT):
            if e.previous_classification_id not in known_cls:
                issues.append(ValidationIssue(check="override_conflict", record_id=e.event_id,
                                              detail="unknown previous_classification"))
    retracted = store.retracted_ids()
    for c in store.iter_classifications():
        if c.provenance is ClassificationProvenance.USER \
                and c.classification_id not in retracted:
            user_values.setdefault((c.news_item_id, c.dimension.value), set()).add(c.value)
    for (item_id, dimension), values in user_values.items():
        if dimension in ("event_type", "time_horizon") and len(values) > 1:
            issues.append(ValidationIssue(
                check="override_conflict", record_id=item_id,
                detail=f"{dimension}: 競合するUSER分類 {sorted(values)}"))

    return tuple(issues)
