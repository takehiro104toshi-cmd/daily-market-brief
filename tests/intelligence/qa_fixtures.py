"""Evidence QA（Phase 1-E）synthetic fixtureビルダー。

自由文からのFact抽出は禁止のため、Trust Gate検証用のFact等は全てここで
明示的に合成する（監督者指定のfixtureリスト対応）。
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Optional, Tuple

from src.intelligence.core.types import Direction, Horizon, SourceTier, VerificationState
from src.intelligence.evidence.model import (
    AnalysisStatement,
    EvidenceLink,
    EvidenceRelation,
    FactStatement,
    ForecastMetadata,
    ForecastStatement,
)
from src.intelligence.evidence_qa.model import SourceInfo
from src.intelligence.market.model import Observation, ObservationKind
from src.intelligence.sources.model import SourceDocument

#: 評価基準時刻（決定論: 全テストで固定）
REF = datetime(2026, 8, 30, 12, 0, tzinfo=timezone.utc)


def make_doc(
    doc_id: str = "doc_tier1_fresh",
    *,
    source_id: str = "boj_whatsnew",
    tier: SourceTier = SourceTier.TIER1,
    published_age_hours: Optional[float] = 6,
    date_quality: str = "source_provided_tz",
    published_inferred: bool = False,
    content_hash: str = "ab" * 32,
    fingerprint: str = "f1" * 32,
    raw_item_id: str = "raw_item_1",
    revision_of: Optional[str] = None,
    normalizer_version: str = "1.0.0",
) -> SourceDocument:
    published = (REF - timedelta(hours=published_age_hours)
                 if published_age_hours is not None else None)
    return SourceDocument(
        source_document_id=doc_id,
        source_id=source_id,
        source_tier=tier,
        title="日銀が政策金利を維持",
        locator="https://www.example.jp/announcements/a1",
        canonical_locator="https://example.jp/announcements/a1",
        retrieved_at=REF - timedelta(hours=1),
        published_at=published,
        published_raw=published.isoformat() if published else "",
        date_quality=date_quality if published is not None else "missing",
        published_inferred=published_inferred,
        publisher="Bank of Japan",
        language="ja",
        content_hash=content_hash,
        raw_item_id=raw_item_id,
        content_fingerprint=fingerprint,
        normalizer_name="feed_entry",
        normalizer_version=normalizer_version,
        revision_of=revision_of,
        media_type="application/rss+xml",
    )


def make_source_info(
    source_id: str = "boj_whatsnew",
    *,
    tier: SourceTier = SourceTier.TIER1,
    investment_value: str = "MARKET_CRITICAL",
    health_state: str = "healthy",
    usage_status: str = "public_feed",
    duplicate_group: str = "",
) -> SourceInfo:
    return SourceInfo(source_id=source_id, tier=tier, investment_value=investment_value,
                      health_state=health_state, usage_status=usage_status,
                      duplicate_group=duplicate_group)


def make_observation(
    obs_id: str = "obs_valid_raw",
    *,
    value: Optional[Decimal] = Decimal("147.25"),
    unit: str = "jpy_per_usd",
    currency: str = "JPY",
    metric: str = "rate",
    as_of_age_hours: float = 2,
    kind: ObservationKind = ObservationKind.RAW,
    inputs: Tuple[str, ...] = (),
    calculation_method: str = "api_field",
    source_id: str = "synthetic_market",
    source_document_id: str = "doc_market_1",
) -> Observation:
    return Observation(
        observation_id=obs_id,
        entity_id="fx:USDJPY",
        metric=metric,
        value=value,
        unit=unit,
        currency=currency,
        as_of=REF - timedelta(hours=as_of_age_hours),
        kind=kind,
        calculation_method=calculation_method,
        inputs=inputs,
        source_id=source_id,
        source_document_id=source_document_id,
    )


def make_fact(
    fact_id: str = "fact_1",
    *,
    verification: VerificationState = VerificationState.UNVERIFIED,
    event_age_hours: Optional[float] = 6,
) -> FactStatement:
    return FactStatement(
        statement_id=fact_id,
        text="日銀は2026年8月28日の会合で政策金利を維持した",
        created_at=REF - timedelta(hours=1),
        event_time=(REF - timedelta(hours=event_age_hours)
                    if event_age_hours is not None else None),
        verification=verification,
    )


def make_link(
    link_id: str,
    claim_id: str,
    evidence_id: str,
    relation: EvidenceRelation = EvidenceRelation.SUPPORTS,
) -> EvidenceLink:
    return EvidenceLink(link_id=link_id, claim_id=claim_id, evidence_id=evidence_id,
                        relation=relation, created_at=REF - timedelta(hours=1))


def make_analysis(
    analysis_id: str = "ana_1", *, inputs: Tuple[str, ...] = ("fact_1",)
) -> AnalysisStatement:
    return AnalysisStatement(
        statement_id=analysis_id,
        text="政策維持は円安圧力の持続を示唆する",
        created_at=REF - timedelta(hours=1),
        inputs=inputs,
        rule_id="CR_FX_001",
        agent="rule_engine",
    )


def make_forecast(
    forecast_id: str = "fcst_1", *, supporting: Tuple[str, ...] = ("fact_1",)
) -> ForecastStatement:
    return ForecastStatement(
        statement_id=forecast_id,
        text="USDJPYは1週間で146〜149のレンジを想定",
        created_at=REF - timedelta(hours=1),
        forecast=ForecastMetadata(
            target="fx:USDJPY",
            direction=Direction.RANGE,
            horizon=Horizon.ONE_WEEK,
            confidence=2,
            generated_at=REF - timedelta(hours=1),
            predictor="rule_engine",
            supporting_evidence=supporting,
            invalidation_conditions=("FOMCサプライズ利下げ",),
            target_low=Decimal("146"),
            target_high=Decimal("149"),
        ),
    )
