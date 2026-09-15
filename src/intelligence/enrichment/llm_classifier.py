"""L3 LLM分類層（Phase 2-E・**optional** enrichment layer / provider中立）。

必須条件（監督者指定）の実装:
- LLM output ≠ Fact（生成するのはNewsClassification提案のみ。Fact抽出はしない）
- provenance=LLM・provider/model・prompt schema version・generated_at・confidenceを保持
- 生の構造化応答をaudit（llm_audit.jsonl）へ保存
- **決定論バリデーション**: JSONスキーマ検証・taxonomyに無いlabelはcanonicalへ入れず
  ReviewQueue（LLM_UNKNOWN_LABEL）へ・不正出力はreject（LLM_INVALID_OUTPUT）
- LLM利用不可（is_available()=False）でもData Bank全体は動く（本層をskipするだけ）
- vendor中立: core/contracts.pyのLLMProviderのみに依存（Anthropic/OpenAIを知らない）
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import List, Optional, Tuple

from ..core.contracts import LLMProvider
from ..databank.news_model import (
    ClassificationDimension,
    ClassificationProvenance,
    NewsClassification,
    NewsItem,
)
from .model import ReviewQueueItem, ReviewReason
from .taxonomy import EventTaxonomy, ThemeTaxonomy

#: プロンプト・出力スキーマの版（変更=version上げ。classifier_versionへ記録される）
PROMPT_SCHEMA_VERSION = "1.0.0"

_SYSTEM = (
    "You are a news tagging assistant. You assign labels from a FIXED list. "
    "You never invent labels, never extract facts, never judge market impact."
)

_PROMPT_TEMPLATE = """Classify the news article below.

Allowed theme slugs: {themes}
Allowed event types: {events}

Return ONLY a JSON object of this exact shape (no prose):
{{"themes": [{{"slug": "<allowed slug>", "confidence": <0.0-1.0>}}],
  "event_types": [{{"type": "<allowed type>", "confidence": <0.0-1.0>}}]}}

Use an empty list when nothing applies. Do not use labels outside the allowed lists.

HEADLINE: {headline}
SUMMARY: {summary}
"""


@dataclass(frozen=True, kw_only=True)
class LLMClassifyOutcome:
    available: bool
    proposals: Tuple[NewsClassification, ...] = ()
    review_items: Tuple[ReviewQueueItem, ...] = ()
    audit: Optional[dict] = None
    rejected: bool = False  # 出力全体がスキーマ不正でrejectされた


class LLMThemeEventClassifier:
    """テーマ・イベント種別のLLM提案器（canonical反映はengine側の検証を通してのみ）。"""

    def __init__(
        self,
        provider: LLMProvider,
        theme_taxonomy: ThemeTaxonomy,
        event_taxonomy: EventTaxonomy,
    ) -> None:
        self._provider = provider
        self._themes = theme_taxonomy
        self._events = event_taxonomy

    def classify(self, item: NewsItem, *, now: datetime) -> LLMClassifyOutcome:
        if not self._provider.is_available():
            return LLMClassifyOutcome(available=False)

        prompt = _PROMPT_TEMPLATE.format(
            themes=", ".join(self._themes.slugs()),
            events=", ".join(self._events.type_names()),
            headline=item.headline[:300],
            summary=(item.summary or "")[:600],
        )
        result = self._provider.complete(prompt, system=_SYSTEM, max_tokens=512)
        classifier_name = f"llm_classifier:{result.provider}:{result.model}"
        audit = {
            "news_item_id": item.news_item_id,
            "provider": result.provider,
            "model": result.model,
            "prompt_schema_version": PROMPT_SCHEMA_VERSION,
            "generated_at": now.isoformat(),
            "raw_text": result.text[:4000],
        }

        parsed = self._parse(result.text)
        if parsed is None:
            return LLMClassifyOutcome(
                available=True, rejected=True, audit={**audit, "verdict": "invalid_output"},
                review_items=(ReviewQueueItem(
                    review_id=ReviewQueueItem.make_id(
                        item.news_item_id, "llm_output", "invalid", "llm_invalid_output"),
                    news_item_id=item.news_item_id, dimension="llm_output",
                    candidate_value="invalid", reason=ReviewReason.LLM_INVALID_OUTPUT,
                    classifier_name=classifier_name, created_at=now,
                ),))

        proposals: List[NewsClassification] = []
        reviews: List[ReviewQueueItem] = []
        for section, dimension, allowed, key in (
            ("themes", ClassificationDimension.THEME, set(self._themes.slugs()), "slug"),
            ("event_types", ClassificationDimension.EVENT_TYPE,
             set(self._events.type_names()), "type"),
        ):
            for entry in parsed.get(section, []):
                label = str(entry.get(key, ""))
                confidence = self._confidence(entry.get("confidence"))
                if not label:
                    continue
                if label not in allowed or confidence is None:
                    # 未知label・不正confidenceはcanonicalへ入れない（DATABASE汚染禁止）
                    reviews.append(ReviewQueueItem(
                        review_id=ReviewQueueItem.make_id(
                            item.news_item_id, dimension.value, label,
                            "llm_unknown_label" if label not in allowed
                            else "llm_invalid_output"),
                        news_item_id=item.news_item_id, dimension=dimension.value,
                        candidate_value=label,
                        reason=(ReviewReason.LLM_UNKNOWN_LABEL if label not in allowed
                                else ReviewReason.LLM_INVALID_OUTPUT),
                        classifier_name=classifier_name, created_at=now,
                    ))
                    continue
                proposals.append(NewsClassification(
                    classification_id=NewsClassification.make_id(
                        item.news_item_id, dimension.value, label,
                        f"{classifier_name}:{PROMPT_SCHEMA_VERSION}"),
                    news_item_id=item.news_item_id,
                    dimension=dimension, value=label,
                    provenance=ClassificationProvenance.LLM,
                    classifier_name=classifier_name,
                    classifier_version=PROMPT_SCHEMA_VERSION,
                    created_at=now,
                    confidence=confidence, confidence_type="llm_stated",
                    basis_document_id=item.primary_document_id,
                ))
        return LLMClassifyOutcome(
            available=True, proposals=tuple(proposals), review_items=tuple(reviews),
            audit={**audit, "verdict": "ok", "proposals": len(proposals),
                   "review": len(reviews)})

    # ------------------------------------------------------------- 決定論バリデーション

    @staticmethod
    def _parse(text: str) -> Optional[dict]:
        """応答→dict（厳格。JSON以外の混入は最初の'{'〜最後の'}'のみ許容）。"""
        stripped = text.strip()
        if not stripped:
            return None
        start, end = stripped.find("{"), stripped.rfind("}")
        if start < 0 or end <= start:
            return None
        try:
            data = json.loads(stripped[start:end + 1])
        except json.JSONDecodeError:
            return None
        if not isinstance(data, dict):
            return None
        for key in ("themes", "event_types"):
            value = data.get(key, [])
            if not isinstance(value, list) or not all(isinstance(e, dict) for e in value):
                return None
        return data

    @staticmethod
    def _confidence(raw) -> Optional[Decimal]:
        if raw is None:
            return None
        try:
            value = Decimal(str(raw))
        except InvalidOperation:
            return None
        if not (Decimal("0") <= value <= Decimal("1")):
            return None
        return value
