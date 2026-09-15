"""Enrichment backfill（Phase 2-E・3,001 NewsItemへの段階適用）。

- 決定論順（news_item_idソート）・段階実行（limit: sample→500→full）
- corpus fingerprint: 対象NewsItem集合（id×primary_document×headline）の決定論hash
  ——run manifestに記録され、何に対するenrichmentだったか監査可能
- 冪等: classification_idが決定論のため再実行は既存分をskipし新規のみ追加
- 失敗はrecords_failedへ計上して続行（黙って落とさない・全体は止めない）
"""
from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from typing import List, Optional, Tuple

from ..core.ids import new_id
from ..databank.news_model import NewsItem
from .engine import EnrichmentEngine
from .llm_classifier import PROMPT_SCHEMA_VERSION
from .model import EnrichmentRun

from .entity_matcher import ENTITY_MATCHER_VERSION
from .event_matcher import EVENT_MATCHER_VERSION, HORIZON_MATCHER_VERSION
from .theme_matcher import THEME_MATCHER_VERSION


def corpus_fingerprint(items: List[NewsItem]) -> str:
    h = hashlib.sha256()
    for item in sorted(items, key=lambda i: i.news_item_id):
        h.update(item.news_item_id.encode())
        h.update(item.primary_document_id.encode())
        h.update(hashlib.sha256(item.headline.encode("utf-8")).digest())
    return h.hexdigest()


class EnrichmentBackfillEngine:
    def __init__(
        self,
        bank,  # JsonlNewsBankStore（iter_news_items）
        engine: EnrichmentEngine,
        index=None,  # SqliteNewsIndex（任意。分類を検索indexへ反映）
    ) -> None:
        self.bank = bank
        self.engine = engine
        self.index = index

    def run(self, *, limit: int = 0, now: Optional[datetime] = None) -> EnrichmentRun:
        started = now or datetime.now(timezone.utc)
        items: List[NewsItem] = sorted(self.bank.iter_news_items(),
                                       key=lambda i: i.news_item_id)
        fingerprint = corpus_fingerprint(items)
        if limit:
            items = items[:limit]

        seen = classified = unclassified = failed = 0
        cls_added = events_added = review_queued = 0
        for item in items:
            seen += 1
            try:
                outcome = self.engine.enrich_item(item, now=started)
            except Exception:  # noqa: BLE001 1件の失敗で全体を止めない（会計へ計上）
                failed += 1
                continue
            cls_added += outcome.classifications_added
            events_added += outcome.events_added
            review_queued += outcome.review_queued
            if self.engine.store.classifications_for(item.news_item_id):
                classified += 1
            else:
                unclassified += 1

        if self.index is not None:
            self.index.index_classifications(list(self.engine.store.iter_classifications()))

        run = EnrichmentRun(
            run_id=new_id("erun", started),
            started_at=started,
            completed_at=datetime.now(timezone.utc),
            corpus_fingerprint=fingerprint,
            entity_catalog_version=self.engine.entities.version,
            theme_taxonomy_version=self.engine.themes.version,
            event_taxonomy_version=self.engine.events.version,
            classifier_versions=(
                f"entity_matcher:{ENTITY_MATCHER_VERSION}",
                f"theme_rule_matcher:{THEME_MATCHER_VERSION}",
                f"event_rule_matcher:{EVENT_MATCHER_VERSION}",
                f"horizon_rule_matcher:{HORIZON_MATCHER_VERSION}",
            ) + ((f"llm_classifier:{PROMPT_SCHEMA_VERSION}",)
                 if self.engine.llm is not None else ()),
            records_seen=seen,
            records_classified=classified,
            records_unclassified=unclassified,
            records_failed=failed,
            classifications_added=cls_added,
            events_added=events_added,
            review_queued=review_queued,
            status="completed",
            limit=limit,
        )
        self.engine.store.add_run(run)
        return run
