"""Enrichment品質・カバレッジ報告（Phase 2-E PART: QUALITY METRICS）。

METRIC LANGUAGE（P2-B以来の規律）:
- fixture precision/recall … ラベル付きfixtureに対する測定（テスト側で算出）
- 実corpusについては **coverage**（何%に分類が付いたか）のみを言う
  ——production precision/recallと呼ばない（人手レビュー無しに正解率は主張できない）

legacy agreement は参考統計（LegacyAnnotationはnot ground truth——自動昇格しない）。
"""
from __future__ import annotations

import ast
from collections import Counter
from typing import Dict, Iterable, List

from ..databank.news_model import ClassificationDimension, NewsItem
from .store import JsonlEnrichmentStore
from .taxonomy import ThemeTaxonomy


def _effective_by_item(store: JsonlEnrichmentStore, items: List[NewsItem]) -> Dict[str, tuple]:
    return {i.news_item_id: store.effective_classifications(i.news_item_id) for i in items}


def build_quality_report(
    store: JsonlEnrichmentStore,
    items: Iterable[NewsItem],
    *,
    theme_taxonomy: ThemeTaxonomy,
    legacy_annotations: Iterable = (),
) -> Dict:
    items = list(items)
    effective = _effective_by_item(store, items)

    def coverage(dimension: ClassificationDimension) -> Dict:
        tagged = [i for i in items
                  if any(c.dimension is dimension for c in effective[i.news_item_id])]
        values = Counter(
            c.value for i in tagged for c in effective[i.news_item_id]
            if c.dimension is dimension)
        return {
            "items_tagged": len(tagged),
            "coverage_pct": round(100 * len(tagged) / len(items), 1) if items else 0,
            "top_values": values.most_common(12),
        }

    unclassified = [i.news_item_id for i in items if not effective[i.news_item_id]]
    theme_counts = Counter(
        sum(1 for c in effective[i.news_item_id]
            if c.dimension is ClassificationDimension.THEME) for i in items)

    by_language: Dict[str, Dict] = {}
    for lang in sorted({i.language for i in items}):
        subset = [i for i in items if i.language == lang]
        tagged = sum(1 for i in subset if effective[i.news_item_id])
        by_language[lang] = {"items": len(subset),
                             "classified_pct": round(100 * tagged / len(subset), 1)}
    publisher_counter = Counter(i.publisher for i in items)
    by_publisher = {}
    for publisher, _n in publisher_counter.most_common(8):
        subset = [i for i in items if i.publisher == publisher]
        tagged = sum(1 for i in subset if effective[i.news_item_id])
        by_publisher[publisher] = {"items": len(subset),
                                   "classified_pct": round(100 * tagged / len(subset), 1)}

    report = {
        "items": len(items),
        "unclassified": len(unclassified),
        "unclassified_pct": round(100 * len(unclassified) / len(items), 1) if items else 0,
        "coverage": {
            "company": coverage(ClassificationDimension.COMPANY),
            "ticker": coverage(ClassificationDimension.TICKER),
            "country": coverage(ClassificationDimension.COUNTRY),
            "theme": coverage(ClassificationDimension.THEME),
            "event_type": coverage(ClassificationDimension.EVENT_TYPE),
            "time_horizon": coverage(ClassificationDimension.TIME_HORIZON),
            "central_bank": coverage(ClassificationDimension.CENTRAL_BANK),
            "index": coverage(ClassificationDimension.INDEX),
            "commodity": coverage(ClassificationDimension.COMMODITY),
        },
        "multi_label_theme_distribution": dict(sorted(theme_counts.items())),
        "review_queue": sum(1 for _ in store.iter_review_queue()),
        "by_language": by_language,
        "by_publisher": by_publisher,
    }
    report["legacy_agreement"] = legacy_theme_agreement(
        store, items, theme_taxonomy=theme_taxonomy, legacy_annotations=legacy_annotations)
    return report


def legacy_theme_agreement(
    store: JsonlEnrichmentStore,
    items: List[NewsItem],
    *,
    theme_taxonomy: ThemeTaxonomy,
    legacy_annotations: Iterable,
) -> Dict:
    """legacy（tank）テーマ vs 新deterministicテーマの一致統計（**参考値**）。

    LegacyAnnotationはnot ground truth——一致率は「傾向の比較研究」であり、
    新分類の正解率でも旧分類の正解率でもない。
    """
    tank_map = theme_taxonomy.tank_slug_map()
    by_doc: Dict[str, List[str]] = {}
    for ann in legacy_annotations:
        pairs = dict(ann.annotations)
        raw = pairs.get("themes", "")
        if not raw:
            continue
        try:
            slugs = [str(s) for s in ast.literal_eval(raw)]
        except (ValueError, SyntaxError):
            continue
        by_doc[ann.target_record_id] = slugs

    compared = agreed = 0
    mappable_docs = 0
    for item in items:
        legacy_slugs = by_doc.get(item.primary_document_id)
        if legacy_slugs is None:
            continue
        mapped = {tank_map[s] for s in legacy_slugs if s in tank_map}
        if not mapped:
            continue
        mappable_docs += 1
        new_themes = {c.value for c in store.effective_classifications(item.news_item_id)
                      if c.dimension is ClassificationDimension.THEME}
        compared += 1
        if mapped & new_themes:
            agreed += 1
    return {
        "note": "legacy is NOT ground truth（参考統計・自動昇格しない）",
        "items_with_mappable_legacy_theme": mappable_docs,
        "any_overlap_agreement": agreed,
        "any_overlap_agreement_pct": round(100 * agreed / compared, 1) if compared else 0,
    }
