"""次元別評価器（Phase 1-E）。全て純関数・決定論（基準時刻は引数で注入）。

各関数は1次元のDimensionResultを返す。総合判定はgate.pyが行う。
「Tier1=truth」とは扱わない——source qualityは13次元のうちの1つにすぎない。
current source healthとdocument validityは**別次元**（昨日取得したBOJ文書は、
今日BOJ endpointが落ちていても無効にならない）。
"""
from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from typing import Optional, Sequence, Tuple

from ..core import serialization
from ..core.types import Horizon, SourceTier
from ..market.model import Observation, ObservationKind
from ..sources.model import SourceDocument
from .model import DimensionResult, DimensionStatus, QADimension, SourceInfo
from .policy import TrustPolicy

#: 負値がありえないmetric（決定論的最小集合。市場値を勝手に補正はしない——検知のみ）
NON_NEGATIVE_METRICS = frozenset({"close", "open", "high", "low", "price", "volume", "index_level"})

#: 比率系unitの正気範囲チェック対象（絶対値がこの上限を超えたらabsurd扱い）
_PCT_ABS_LIMIT = Decimal("1000")   # ±1000%
_BPS_ABS_LIMIT = Decimal("100000")  # ±1000%相当

#: 通貨系とみなすunit（currency欄との整合チェック用）
_CURRENCY_UNITS = frozenset({"jpy", "usd", "eur", "gbp", "jpy_per_usd", "usd_per_eur"})


def _result(dim: QADimension, status: DimensionStatus, codes: Tuple[str, ...] = (),
            detail: str = "") -> DimensionResult:
    return DimensionResult(dimension=dim, status=status, reason_codes=codes, detail=detail)


# ---------------------------------------------------------------- 1. provenance


def eval_document_provenance(doc: SourceDocument) -> DimensionResult:
    codes = []
    if not doc.source_id:
        codes.append("missing_source_id")
    if not doc.content_hash:
        codes.append("missing_content_hash")
    if not doc.locator:
        codes.append("missing_locator")
    if codes:
        return _result(QADimension.PROVENANCE, DimensionStatus.FAIL, tuple(codes))
    warns = []
    if not doc.raw_item_id:
        warns.append("missing_raw_item")  # 原文非保存の明示（tank記事等）。断絶とは区別
    if not doc.normalizer_version:
        warns.append("missing_normalizer_version")
    if warns:
        return _result(QADimension.PROVENANCE, DimensionStatus.WARN, tuple(warns))
    return _result(QADimension.PROVENANCE, DimensionStatus.PASS)


def eval_observation_provenance(obs: Observation) -> DimensionResult:
    if obs.kind is ObservationKind.RAW:
        if not obs.source_id:
            return _result(QADimension.PROVENANCE, DimensionStatus.FAIL,
                           ("missing_source_id",))
        if not obs.source_document_id:
            return _result(QADimension.PROVENANCE, DimensionStatus.WARN,
                           ("missing_supporting_evidence_ref",),
                           "由来文書なしの取得経路（API直等）")
        return _result(QADimension.PROVENANCE, DimensionStatus.PASS)
    # DERIVED: inputs必須はP1-A型が強制するが、防御的に再検査（破損データ対策）
    if not obs.inputs or not obs.calculation_method:
        return _result(QADimension.PROVENANCE, DimensionStatus.FAIL,
                       ("derived_without_inputs",))
    return _result(QADimension.PROVENANCE, DimensionStatus.PASS)


# ---------------------------------------------------------------- 2. source quality


def eval_source_quality(info: SourceInfo) -> DimensionResult:
    codes = []
    if info.tier is SourceTier.TIER3:
        codes.append("tier3_general_source")
    if info.investment_value == "LOW":
        codes.append("low_investment_value")
    if codes:
        return _result(QADimension.SOURCE_QUALITY, DimensionStatus.WARN, tuple(codes))
    return _result(QADimension.SOURCE_QUALITY, DimensionStatus.PASS,
                   detail=f"tier{info.tier.value}（Tier1=truthとは扱わない）")


# ---------------------------------------------------------------- 3. current health


def eval_source_health(info: SourceInfo, policy: TrustPolicy) -> DimensionResult:
    """現在死活。**文書自体の有効性とは分離**（deadでも過去文書はWARN止まり）。"""
    if info.health_state == "dead":
        return _result(QADimension.SOURCE_HEALTH, policy.source_dead_status,
                       ("source_dead_now",), "取得当時の文書自体は無効化しない")
    if info.health_state == "degraded":
        return _result(QADimension.SOURCE_HEALTH, DimensionStatus.PASS,
                       ("source_degraded_now",))
    if info.health_state == "auth_required":
        return _result(QADimension.SOURCE_HEALTH, DimensionStatus.PASS,
                       ("source_auth_required",))
    return _result(QADimension.SOURCE_HEALTH, DimensionStatus.PASS)


# ---------------------------------------------------------------- 4. freshness


def eval_freshness(
    published_at: Optional[datetime],
    policy: TrustPolicy,
    reference_time: datetime,
    horizon: Optional[Horizon] = None,
) -> DimensionResult:
    if published_at is None:
        return _result(QADimension.FRESHNESS, DimensionStatus.NOT_APPLICABLE,
                       detail="published unknown（DATE_QUALITY次元が扱う）")
    age_hours = (reference_time - published_at.astimezone(timezone.utc)).total_seconds() / 3600
    status, code = policy.freshness_status(age_hours)
    codes = [code]
    if not policy.horizon_ok(age_hours, horizon):
        status = DimensionStatus.LIMIT
        codes.append("stale_for_horizon")
    return _result(QADimension.FRESHNESS, status, tuple(codes),
                   detail=f"age={int(age_hours)}h horizon={horizon.value if horizon else '-'}")


# ---------------------------------------------------------------- 5. date quality


def eval_date_quality(doc: SourceDocument, policy: TrustPolicy) -> DimensionResult:
    codes = []
    if doc.published_at is None:
        return _result(QADimension.DATE_QUALITY, policy.published_unknown_status,
                       ("published_unknown",),
                       f"quality={doc.date_quality or 'unknown'}（即REJECTにしない）")
    if doc.published_inferred:
        codes.append("inferred_date")
    if doc.date_quality == "source_provided_naive":
        codes.append("naive_date")
    if codes:
        return _result(QADimension.DATE_QUALITY, DimensionStatus.WARN, tuple(codes))
    return _result(QADimension.DATE_QUALITY, DimensionStatus.PASS)


# ---------------------------------------------------------------- 6. content integrity


def eval_content_integrity(doc: SourceDocument, raw_repository=None) -> DimensionResult:
    if raw_repository is not None and doc.raw_item_id:
        item = raw_repository.get_raw_item(doc.raw_item_id)
        if item is None:
            return _result(QADimension.CONTENT_INTEGRITY, DimensionStatus.FAIL,
                           ("raw_item_not_found",))
        if item.storage_ref and not raw_repository.blobs.verify_blob(item.content_hash):
            return _result(QADimension.CONTENT_INTEGRITY, DimensionStatus.FAIL,
                           ("blob_hash_mismatch",), "raw blobの改竄/破損を検知")
    serialization.register_domain_types()  # 冪等。プロセス状態を「破損」と誤判定しないため
    try:
        if serialization.decode(serialization.encode(doc)) != doc:
            return _result(QADimension.CONTENT_INTEGRITY, DimensionStatus.FAIL,
                           ("serialization_broken",))
    except (TypeError, ValueError):
        return _result(QADimension.CONTENT_INTEGRITY, DimensionStatus.FAIL,
                       ("serialization_broken",))
    if not doc.content_fingerprint:
        return _result(QADimension.CONTENT_INTEGRITY, DimensionStatus.WARN,
                       ("missing_fingerprint",))
    return _result(QADimension.CONTENT_INTEGRITY, DimensionStatus.PASS)


# ---------------------------------------------------------------- 8. revision / retraction


def eval_revision(
    doc: SourceDocument,
    existing_documents: Sequence[SourceDocument],
    policy: TrustPolicy,
    retracted_ids: frozenset = frozenset(),
) -> DimensionResult:
    """SUPERSEDED/RETRACTED。破壊的削除はしない（用途で制限するだけ）。

    retractionは**明示evidence（retracted_ids）がある場合のみ**。推測しない。
    """
    if doc.source_document_id in retracted_ids:
        return _result(QADimension.REVISION, DimensionStatus.FAIL, ("retracted",),
                       "現在分析用途ではREJECT（監査・歴史用途では保存済み）")
    superseded_by = [
        d.source_document_id for d in existing_documents
        if d.revision_of == doc.source_document_id
    ]
    if superseded_by:
        return _result(QADimension.REVISION, policy.superseded_status, ("superseded",),
                       f"最新版: {superseded_by[0]}")
    return _result(QADimension.REVISION, DimensionStatus.PASS)


# ---------------------------------------------------------------- 9. duplication


def eval_duplication(
    doc: SourceDocument, existing_documents: Sequence[SourceDocument]
) -> DimensionResult:
    """転載検知（fingerprint一致×別source）。10転載 ≠ 10独立sourceの基礎。"""
    twins = [
        d for d in existing_documents
        if d.source_document_id != doc.source_document_id
        and d.content_fingerprint
        and d.content_fingerprint == doc.content_fingerprint
        and d.source_id != doc.source_id
    ]
    if twins:
        return _result(QADimension.DUPLICATION, DimensionStatus.WARN,
                       ("syndicated_duplicate",),
                       f"同一内容を{len(twins)}件の別sourceが配信")
    return _result(QADimension.DUPLICATION, DimensionStatus.PASS)


# ---------------------------------------------------------------- 10. observation validity


def eval_observation_validity(
    obs: Observation, policy: TrustPolicy, reference_time: datetime
) -> DimensionResult:
    codes = []
    if obs.value is None:
        codes.append("value_missing")
    else:
        if obs.value.is_nan() or obs.value.is_infinite():
            return _result(QADimension.OBSERVATION_VALIDITY, DimensionStatus.FAIL,
                           ("value_not_finite",))
        if obs.metric in NON_NEGATIVE_METRICS and obs.value < 0:
            return _result(QADimension.OBSERVATION_VALIDITY, DimensionStatus.FAIL,
                           ("negative_impossible_value",),
                           f"{obs.metric}={obs.value}（値の補正はしない。検知のみ）")
        if obs.unit == "pct" and abs(obs.value) > _PCT_ABS_LIMIT:
            codes.append("absurd_percentage")
        if obs.unit == "bps" and abs(obs.value) > _BPS_ABS_LIMIT:
            codes.append("absurd_percentage")
    if not obs.unit:
        codes.append("unknown_unit")
    if obs.currency and obs.unit.lower() in _CURRENCY_UNITS:
        if obs.currency.lower() not in obs.unit.lower():
            codes.append("currency_mismatch")
    if obs.as_of.astimezone(timezone.utc) > reference_time:
        codes.append("as_of_in_future")
    if codes:
        hard = {"absurd_percentage", "currency_mismatch", "as_of_in_future"}
        status = DimensionStatus.LIMIT if hard.intersection(codes) else DimensionStatus.WARN
        return _result(QADimension.OBSERVATION_VALIDITY, status, tuple(codes))
    return _result(QADimension.OBSERVATION_VALIDITY, DimensionStatus.PASS)


# ---------------------------------------------------------------- 12. usage rights


def eval_usage_rights(info: SourceInfo, policy: TrustPolicy) -> DimensionResult:
    """利用条件。**内容の正しさ（trust）と混同しない**独立次元。"""
    if info.usage_status == "restricted":
        return _result(QADimension.USAGE_RIGHTS, policy.usage_restricted_status,
                       ("usage_restricted",))
    return _result(QADimension.USAGE_RIGHTS, DimensionStatus.PASS)


# ---------------------------------------------------------------- 13. normalization quality


def eval_normalization_quality(doc: SourceDocument, events: Sequence) -> DimensionResult:
    """P1-D NormalizationEventの結果を反映。REJECTED正規化はEvidence利用不可。"""
    matching = [
        e for e in events
        if e.raw_item_id == doc.raw_item_id
        and e.normalizer_version == doc.normalizer_version
        and doc.source_document_id in e.produced_document_ids
    ]
    if not matching:
        return _result(QADimension.NORMALIZATION_QUALITY, DimensionStatus.NOT_APPLICABLE,
                       detail="正規化イベント未提供")
    event = matching[0]
    if event.status.value == "rejected":
        return _result(QADimension.NORMALIZATION_QUALITY, DimensionStatus.FAIL,
                       ("normalization_rejected",))
    if event.status.value == "partial":
        detail = ",".join(sorted({i.code for i in event.issues}))
        return _result(QADimension.NORMALIZATION_QUALITY, DimensionStatus.WARN,
                       ("normalization_partial",), detail)
    return _result(QADimension.NORMALIZATION_QUALITY, DimensionStatus.PASS)
