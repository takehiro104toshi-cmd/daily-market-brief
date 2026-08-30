"""Enrichment Engine（Phase 2-E・1 NewsItem分のL0〜L3オーケストレーション）。

層分離:
    L0 SOURCE METADATA           … NewsItem既存のentity_refs/theme_refs（SOURCE_EXPLICIT）
    L1 DETERMINISTIC NORMALIZATION… カタログ/taxonomyのalias→正準値（matcher内で適用）
    L2 ENTITY / THEME / EVENT     … 決定論マッチ（ENTITY_DATABASE / RULE_BASED）
    L3 LLM                        … optional（提案→検証→canonical。不可時はskip）
    （L4 USER overrideは override.py。engineは通さない）

規律:
- 全classificationにprovenance/classifier/version/taxonomy_version/evidence（説明可能性）
- 冪等: classification_idは (news_item×dimension×value×classifier:version) の決定論
- append-only: 追加のみ。旧分類の書き換え・削除はしない
- Fact抽出・市場影響・重要度スコアは**生成しない**（DO NOT）
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import List, Optional, Tuple

from ..core.ids import new_id
from ..databank.news_model import (
    ClassificationDimension,
    ClassificationProvenance,
    EntityKind,
    NewsClassification,
    NewsItem,
)
from .catalog import EntityCatalog
from .entity_matcher import ENTITY_MATCHER_VERSION, match_entities
from .event_matcher import (
    EVENT_MATCHER_VERSION,
    HORIZON_MATCHER_VERSION,
    match_event_types,
    match_time_horizon,
)
from .llm_classifier import LLMThemeEventClassifier
from .model import EnrichmentAction, EnrichmentEvent, ReviewQueueItem, ReviewReason
from .store import JsonlEnrichmentStore
from .taxonomy import EventTaxonomy, ThemeTaxonomy
from .theme_matcher import THEME_MATCHER_VERSION, match_themes

SOURCE_IMPORT_VERSION = "1.0.0"

#: EntityKind → SOURCE_EXPLICIT refの分類次元（L0取込用）
_REF_DIMENSION = {
    EntityKind.COUNTRY: ClassificationDimension.COUNTRY,
    EntityKind.COMPANY: ClassificationDimension.COMPANY,
    EntityKind.TICKER: ClassificationDimension.TICKER,
    EntityKind.SECTOR: ClassificationDimension.SECTOR,
    EntityKind.INDUSTRY: ClassificationDimension.INDUSTRY,
    EntityKind.COMMODITY: ClassificationDimension.COMMODITY,
    EntityKind.CURRENCY: ClassificationDimension.CURRENCY,
    EntityKind.CENTRAL_BANK: ClassificationDimension.CENTRAL_BANK,
    EntityKind.INDEX: ClassificationDimension.INDEX,
    EntityKind.GOVERNMENT: ClassificationDimension.GOVERNMENT,
    EntityKind.PERSON: ClassificationDimension.PERSON,
}


@dataclass(frozen=True, kw_only=True)
class ItemEnrichmentOutcome:
    news_item_id: str
    classifications_added: int = 0
    events_added: int = 0
    review_queued: int = 0
    llm_used: bool = False
    llm_rejected: bool = False


class EnrichmentEngine:
    def __init__(
        self,
        store: JsonlEnrichmentStore,
        entity_catalog: EntityCatalog,
        theme_taxonomy: ThemeTaxonomy,
        event_taxonomy: EventTaxonomy,
        llm_classifier: Optional[LLMThemeEventClassifier] = None,  # optional layer
    ) -> None:
        self.store = store
        self.entities = entity_catalog
        self.themes = theme_taxonomy
        self.events = event_taxonomy
        self.llm = llm_classifier

    # ------------------------------------------------------------- 部品

    def _add(self, cls: NewsClassification, *, now: datetime, counters: List[int]) -> None:
        # 冪等: 同一ID（item×dimension×value×classifier:version）は再処理時にskipする。
        # created_atは処理時刻であり同一性に含めない（run跨ぎ再実行の冪等性——
        # store側の衝突ガードは「本当に内容が食い違う」場合のためだけに残す）
        if self.store.get_classification(cls.classification_id) is not None:
            return
        if self.store.add_classification(cls):
            counters[0] += 1
            self.store.add_event(EnrichmentEvent(
                event_id=new_id("enr", now), news_item_id=cls.news_item_id,
                action=EnrichmentAction.ADD_CLASSIFICATION,
                dimension=cls.dimension.value, value=cls.value,
                classification_id=cls.classification_id,
                provenance=cls.provenance.value,
                classifier_name=cls.classifier_name,
                classifier_version=cls.classifier_version,
                created_at=now,
            ))
            counters[1] += 1

    def _make(
        self, item: NewsItem, dimension: ClassificationDimension, value: str, *,
        provenance: ClassificationProvenance, classifier: str, version: str,
        taxonomy_version: str, now: datetime, role: str = "",
        evidence_field: str = "", evidence_text: str = "",
    ) -> NewsClassification:
        return NewsClassification(
            classification_id=NewsClassification.make_id(
                item.news_item_id, dimension.value, value, f"{classifier}:{version}"),
            news_item_id=item.news_item_id, dimension=dimension, value=value,
            provenance=provenance, classifier_name=classifier, classifier_version=version,
            created_at=now, role=role,
            evidence_field=evidence_field, evidence_text=evidence_text[:160],
            taxonomy_version=taxonomy_version,
            basis_document_id=item.primary_document_id,
        )

    # ------------------------------------------------------------- 本体

    def enrich_item(self, item: NewsItem, *, now: datetime) -> ItemEnrichmentOutcome:
        counters = [0, 0]  # [classifications, events]
        review = 0
        fields = {"headline": item.headline, "summary": item.summary or ""}

        # ---- L0: SOURCE METADATA（sourceが明示提供した分類のみ。生成しない） ----
        for ref in item.entity_refs:
            dimension = _REF_DIMENSION.get(ref.kind)
            if dimension is None:
                continue
            self._add(self._make(
                item, dimension, ref.value, provenance=ref.provenance,
                classifier="source_metadata_import", version=SOURCE_IMPORT_VERSION,
                taxonomy_version="", now=now, evidence_field="source_metadata",
            ), now=now, counters=counters)
        for tref in item.theme_refs:
            self._add(self._make(
                item, ClassificationDimension.THEME, tref.theme_label,
                provenance=tref.provenance,
                classifier="source_metadata_import", version=SOURCE_IMPORT_VERSION,
                taxonomy_version="", now=now, evidence_field="source_metadata",
            ), now=now, counters=counters)

        # ---- L2: entity matching（ENTITY_DATABASE・高precision） ----
        outcome = match_entities(self.entities, fields)
        for m in outcome.matches:
            self._add(self._make(
                item, m.dimension, m.value,
                provenance=ClassificationProvenance.ENTITY_DATABASE,
                classifier="entity_matcher", version=ENTITY_MATCHER_VERSION,
                taxonomy_version=self.entities.version, now=now, role="mention",
                evidence_field=m.evidence_field, evidence_text=m.evidence_text,
            ), now=now, counters=counters)
            if m.entity.kind is EntityKind.COMPANY and m.entity.ticker:
                self._add(self._make(
                    item, ClassificationDimension.TICKER, m.entity.ticker,
                    provenance=ClassificationProvenance.ENTITY_DATABASE,
                    classifier="entity_matcher", version=ENTITY_MATCHER_VERSION,
                    taxonomy_version=self.entities.version, now=now, role="mention",
                    evidence_field=m.evidence_field, evidence_text=m.evidence_text,
                ), now=now, counters=counters)
        for entity_id, alias, field_name in outcome.ambiguous_skipped:
            if self.store.add_review_item(ReviewQueueItem(
                review_id=ReviewQueueItem.make_id(
                    item.news_item_id, "company", entity_id, "ambiguous_alias"),
                news_item_id=item.news_item_id, dimension="company",
                candidate_value=entity_id, reason=ReviewReason.AMBIGUOUS_ALIAS,
                evidence_field=field_name, evidence_text=alias,
                classifier_name="entity_matcher", created_at=now,
            )):
                review += 1
        for ticker_text, field_name in outcome.unknown_tickers:
            if self.store.add_review_item(ReviewQueueItem(
                review_id=ReviewQueueItem.make_id(
                    item.news_item_id, "ticker", ticker_text, "unknown_ticker"),
                news_item_id=item.news_item_id, dimension="ticker",
                candidate_value=ticker_text, reason=ReviewReason.UNKNOWN_TICKER,
                evidence_field=field_name, evidence_text=ticker_text,
                classifier_name="entity_matcher", created_at=now,
            )):
                review += 1

        # ---- L2: theme matching（RULE_BASED・多信号） ----
        for tm in match_themes(self.themes, fields):
            # evidenceは代表1信号の実マッチ表記（検証可能なverbatim。全信号は決定論で再導出可能）
            _signal, field_name, matched = tm.signals[0]
            self._add(self._make(
                item, ClassificationDimension.THEME, tm.theme.slug,
                provenance=ClassificationProvenance.RULE_BASED,
                classifier="theme_rule_matcher", version=THEME_MATCHER_VERSION,
                taxonomy_version=self.themes.version, now=now, role=tm.role,
                evidence_field=field_name, evidence_text=matched,
            ), now=now, counters=counters)

        # ---- L2: event type / time horizon（RULE_BASED・高precision） ----
        for em in match_event_types(self.events, fields):
            self._add(self._make(
                item, ClassificationDimension.EVENT_TYPE, em.event_type.type_name,
                provenance=ClassificationProvenance.RULE_BASED,
                classifier="event_rule_matcher", version=EVENT_MATCHER_VERSION,
                taxonomy_version=self.events.version, now=now,
                evidence_field=em.evidence_field, evidence_text=em.evidence_text,
            ), now=now, counters=counters)
        for hm in match_time_horizon(self.events, fields):
            self._add(self._make(
                item, ClassificationDimension.TIME_HORIZON, hm.horizon,
                provenance=ClassificationProvenance.RULE_BASED,
                classifier="horizon_rule_matcher", version=HORIZON_MATCHER_VERSION,
                taxonomy_version=self.events.version, now=now,
                evidence_field=hm.evidence_field, evidence_text=hm.evidence_text,
            ), now=now, counters=counters)

        # ---- L3: LLM（optional。不可・不正時もデータ層は完走） ----
        llm_used = False
        llm_rejected = False
        if self.llm is not None:
            result = self.llm.classify(item, now=now)
            if result.available:
                llm_used = True
                llm_rejected = result.rejected
                if result.audit is not None:
                    self.store.add_llm_audit(result.audit)
                for proposal in result.proposals:
                    self._add(proposal, now=now, counters=counters)
                for review_item in result.review_items:
                    if self.store.add_review_item(review_item):
                        review += 1

        return ItemEnrichmentOutcome(
            news_item_id=item.news_item_id,
            classifications_added=counters[0], events_added=counters[1],
            review_queued=review, llm_used=llm_used, llm_rejected=llm_rejected,
        )
