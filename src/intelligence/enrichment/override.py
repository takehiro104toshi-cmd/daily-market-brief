"""L4 Manual Override（Phase 2-E）。

- USER provenanceはalgorithm/LLMより優先される（effective viewの優先順位で実現）。
- **履歴は必ず残る**: 旧classificationは削除されず、OVERRIDE/RETRACTイベントが
  append-onlyで積まれる（effective viewから除外されるだけ）。
"""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from ..core.ids import new_id
from ..databank.news_model import (
    ClassificationDimension,
    ClassificationProvenance,
    NewsClassification,
)
from .model import EnrichmentAction, EnrichmentEvent
from .store import JsonlEnrichmentStore

OVERRIDE_CLASSIFIER = "user_override"
OVERRIDE_VERSION = "1.0.0"


def apply_user_override(
    store: JsonlEnrichmentStore,
    *,
    news_item_id: str,
    dimension: ClassificationDimension,
    value: str,
    replaces_classification_id: str = "",
    note: str = "",
    now: datetime,
) -> NewsClassification:
    """USER分類を追加する。replaces指定時は旧分類をeffective viewから除外（履歴保持）。"""
    if replaces_classification_id:
        replaced = store.get_classification(replaces_classification_id)
        if replaced is None:
            raise ValueError(f"unknown classification: {replaces_classification_id}")
        if replaced.news_item_id != news_item_id:
            raise ValueError("override対象が別NewsItemのclassification（conflict）")
    cls = NewsClassification(
        classification_id=NewsClassification.make_id(
            news_item_id, dimension.value, value, f"{OVERRIDE_CLASSIFIER}:{OVERRIDE_VERSION}"),
        news_item_id=news_item_id,
        dimension=dimension,
        value=value,
        provenance=ClassificationProvenance.USER,
        classifier_name=OVERRIDE_CLASSIFIER,
        classifier_version=OVERRIDE_VERSION,
        created_at=now,
    )
    store.add_classification(cls)
    store.add_event(EnrichmentEvent(
        event_id=new_id("enr", now), news_item_id=news_item_id,
        action=(EnrichmentAction.OVERRIDE if replaces_classification_id
                else EnrichmentAction.ADD_CLASSIFICATION),
        dimension=dimension.value, value=value,
        classification_id=cls.classification_id,
        previous_classification_id=replaces_classification_id,
        provenance=ClassificationProvenance.USER.value,
        classifier_name=OVERRIDE_CLASSIFIER, classifier_version=OVERRIDE_VERSION,
        created_at=now, note=note,
    ))
    return cls


def retract_classification(
    store: JsonlEnrichmentStore,
    *,
    classification_id: str,
    note: str,
    now: datetime,
) -> None:
    """誤タグの撤回（USER操作）。レコードは消さずRETRACTイベントで無効化する。"""
    target: Optional[NewsClassification] = store.get_classification(classification_id)
    if target is None:
        raise ValueError(f"unknown classification: {classification_id}")
    store.add_event(EnrichmentEvent(
        event_id=new_id("enr", now), news_item_id=target.news_item_id,
        action=EnrichmentAction.RETRACT,
        dimension=target.dimension.value, value=target.value,
        previous_classification_id=classification_id,
        provenance=ClassificationProvenance.USER.value,
        classifier_name=OVERRIDE_CLASSIFIER, classifier_version=OVERRIDE_VERSION,
        created_at=now, note=note,
    ))
