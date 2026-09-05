"""Article identity resolver（Phase 2-B）。段階判定・precision最優先。

CORE SAFETY PRINCIPLE: **FALSE MERGE IS WORSE THAN MISSED MERGE**
（別記事の誤統合は、重複記事の残存より危険）。

STAGE 1  EXACT MATCH        … canonical URL / source内GUID / fingerprint / content hash
STAGE 2  HIGH-CONFIDENCE    … 複数signal必須の保守的auto-merge（単一signal禁止）
STAGE 3  AMBIGUOUS          … CANDIDATE（**絶対にmergeしない**）
STAGE 4  NO MATCH           … DISTINCT（新Article）

安全規則:
- GUIDはsource-local identity（publisher跨ぎのGUID一致ではmergeしない）。
- same URL + changed content は duplicate ではなく **REVISION**。
- title類似だけではmergeしない（定型見出し・決算記事の誤結合防止）。
- summary（内容signal）が無い場合、STAGE 2は発動しない（CANDIDATE止まり）。
- thresholdはcalibration fixtureで校正した値（IDENTITY_CALIBRATION_REPORT.md）。
"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Optional, Sequence, Tuple

from ..sources.model import SourceDocument
from .identity_decision import IdentityDecision, IdentityDecisionKind
from .identity_signals import (
    numeric_tokens_differ,
    published_proximity_hours,
    summary_similarity,
    title_similarity,
)
from .news_model import ArticleIdentity

ALGORITHM_VERSION = "1.0.0"


@dataclass(frozen=True, kw_only=True)
class IdentityThresholds:
    """校正可能なthreshold（値の根拠: docs/databank/IDENTITY_CALIBRATION_REPORT.md）。

    校正結果（labeled fixture上でfalse merge=0を満たす保守値）:
    - auto_merge_*: 3条件AND（title・summary・時刻近接）を全て要求
    - candidate_*: merge しない観察候補の下限
    """

    auto_merge_title: float = 0.85  # min(ngram,seq)合成では軽微編集が0.89前後になるため
    auto_merge_summary: float = 0.80
    auto_merge_max_hours: float = 48.0
    candidate_title: float = 0.70
    candidate_max_hours: float = 96.0


DEFAULT_THRESHOLDS = IdentityThresholds()


def _exact_stage(
    doc: SourceDocument, member: SourceDocument
) -> Optional[Tuple[IdentityDecisionKind, Tuple[str, ...], Decimal]]:
    """STAGE 1: exact signal判定。(kind, matched_signals, confidence) or None。"""
    same_fp = bool(doc.content_fingerprint) and doc.content_fingerprint == member.content_fingerprint
    # canonical URL一致
    if doc.canonical_locator and doc.canonical_locator == member.canonical_locator:
        if same_fp:
            return (IdentityDecisionKind.EXACT_MATCH,
                    ("same_canonical_url", "same_fingerprint"), Decimal("1"))
        # same URL + changed content = REVISION（単純duplicateではない）
        return (IdentityDecisionKind.REVISION,
                ("same_canonical_url", "different_fingerprint"), Decimal("0.95"))
    # GUID一致はsource-local限定（cross-sourceでは絶対にmergeしない）
    if doc.guid and doc.guid == member.guid:
        if doc.source_id == member.source_id:
            if same_fp:
                return (IdentityDecisionKind.EXACT_MATCH,
                        ("same_guid_same_source", "same_fingerprint"), Decimal("1"))
            return (IdentityDecisionKind.REVISION,
                    ("same_guid_same_source", "different_fingerprint"), Decimal("0.95"))
        return None  # guid_cross_source: 判定材料にしない（resolverが記録）
    # 完全同一内容（fingerprint/生entry hash）
    # 安全条件: fingerprint一致は**両方にsummary（内容証拠）がある場合のみ**exact扱い。
    # summary空同士のfingerprintはtitleのみのhash＝定型見出しの一致にすぎず、
    # 内容証拠なしのmergeになるため許可しない（title-only一致はsemantic段へ落ちる）。
    fp_has_content = bool(doc.summary.strip()) and bool(member.summary.strip())
    if (same_fp and fp_has_content) or (
        doc.content_hash and doc.content_hash == member.content_hash
    ):
        signals = ("same_fingerprint",) if same_fp else ("same_content_hash",)
        if doc.source_id == member.source_id:
            return (IdentityDecisionKind.EXACT_MATCH, signals, Decimal("1"))
        # 同一内容×別publisher = 転載
        return (IdentityDecisionKind.SYNDICATED, signals, Decimal("0.95"))
    return None


def _best_semantic(
    doc: SourceDocument, member: SourceDocument, thresholds: IdentityThresholds
) -> Tuple[float, float, Optional[float]]:
    t_sim = title_similarity(doc.title, member.title)
    s_sim = summary_similarity(doc.summary, member.summary)
    hours = published_proximity_hours(doc.published_at, member.published_at)
    return t_sim, s_sim, hours


def resolve(
    doc: SourceDocument,
    articles: Sequence[Tuple[ArticleIdentity, Sequence[SourceDocument]]],
    *,
    thresholds: IdentityThresholds = DEFAULT_THRESHOLDS,
) -> IdentityDecision:
    """新規SourceDocument 1件を既存Article群に対して判定する（決定論）。

    articles: (ArticleIdentity, そのmember文書列) の列。
    """
    guid_cross_source_seen = False
    best_candidate: Optional[Tuple[float, ArticleIdentity]] = None

    for article, members in sorted(articles, key=lambda p: p[0].article_id):
        for member in sorted(members, key=lambda d: d.source_document_id):
            if member.source_document_id == doc.source_document_id:
                continue
            # STAGE 1: exact
            exact = _exact_stage(doc, member)
            if exact is not None:
                kind, signals, confidence = exact
                return IdentityDecision(
                    decision=kind, document_id=doc.source_document_id,
                    matched_article_id=article.article_id, confidence=confidence,
                    matched_signals=signals, algorithm_version=ALGORITHM_VERSION,
                    reason_codes=signals)
            if doc.guid and doc.guid == member.guid and doc.source_id != member.source_id:
                guid_cross_source_seen = True

            # STAGE 2: 保守的multi-signal auto-merge（全条件AND）
            t_sim, s_sim, hours = _best_semantic(doc, member, thresholds)
            # 数字トークン不一致ガード（実データ由来: 年号・日付・通番違いの別記事を阻止）
            numeric_guard = numeric_tokens_differ(doc.title, member.title)
            if (
                not numeric_guard
                and t_sim >= thresholds.auto_merge_title
                and s_sim >= thresholds.auto_merge_summary
                and hours is not None
                and hours <= thresholds.auto_merge_max_hours
            ):
                matched = ["title_similarity_high", "summary_similarity_high",
                           "published_time_close"]
                if doc.source_id == member.source_id:
                    matched.append("same_publisher")
                return IdentityDecision(
                    decision=IdentityDecisionKind.AUTO_MERGE,
                    document_id=doc.source_document_id,
                    matched_article_id=article.article_id,
                    confidence=Decimal(str(round(min(t_sim, s_sim), 4))),
                    matched_signals=tuple(matched),
                    algorithm_version=ALGORITHM_VERSION,
                    reason_codes=tuple(matched))

            # STAGE 3候補の追跡（mergeはしない）
            if (
                t_sim >= thresholds.candidate_title
                and (hours is None or hours <= thresholds.candidate_max_hours)
            ):
                if best_candidate is None or t_sim > best_candidate[0]:
                    best_candidate = (t_sim, article)

    if best_candidate is not None:
        t_sim, article = best_candidate
        failed = ["summary_similarity_high"]  # AUTO_MERGE条件に届かなかった側の記録
        if guid_cross_source_seen:
            failed.append("guid_cross_source_ignored")
        return IdentityDecision(
            decision=IdentityDecisionKind.CANDIDATE,
            document_id=doc.source_document_id,
            matched_article_id=article.article_id,  # 候補先の記録のみ（merge禁止）
            confidence=Decimal(str(round(t_sim, 4))),
            matched_signals=("title_similarity_high",) if t_sim >= 0.9 else (),
            failed_signals=tuple(failed),
            reason_codes=("title_similarity_high",) if t_sim >= 0.9 else (),
            algorithm_version=ALGORITHM_VERSION)

    failed = ("guid_cross_source_ignored",) if guid_cross_source_seen else ()
    return IdentityDecision(
        decision=IdentityDecisionKind.DISTINCT,
        document_id=doc.source_document_id,
        failed_signals=failed,
        algorithm_version=ALGORITHM_VERSION)
