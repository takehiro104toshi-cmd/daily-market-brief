"""Identity判定モデル（Phase 2-B）。単一scoreにしない（signal別内訳を必ず保持）。"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from enum import Enum
from typing import Tuple

from ..core.types import SCHEMA_VERSION


class IdentityDecisionKind(str, Enum):
    EXACT_MATCH = "exact_match"    # 完全一致（同一文書の再取得等）→ 既存Articleへ
    AUTO_MERGE = "auto_merge"      # 多signal高確信の準重複 → 既存Articleへ（保守的）
    REVISION = "revision"          # 同一記事の内容更新 → 既存Articleへ（revision chain）
    SYNDICATED = "syndicated"      # 転載（同一内容×別publisher）→ 既存Articleへ（role付き）
    CANDIDATE = "candidate"        # 曖昧候補 → **mergeしない**（人間/後段の判断待ち）
    DISTINCT = "distinct"          # 別記事 → 新Article


#: mergeを伴う判定（CANDIDATEは絶対に含めない）
MERGING_DECISIONS = frozenset({
    IdentityDecisionKind.EXACT_MATCH,
    IdentityDecisionKind.AUTO_MERGE,
    IdentityDecisionKind.REVISION,
    IdentityDecisionKind.SYNDICATED,
})

#: signal語彙
SIGNAL_CODES = (
    "same_canonical_url", "same_guid_same_source", "same_fingerprint",
    "same_content_hash", "title_similarity_high", "summary_similarity_high",
    "published_time_close", "same_publisher", "same_duplicate_group",
    "different_fingerprint", "guid_cross_source_ignored", "published_time_far",
    "title_similarity_low", "summary_unavailable", "numeric_token_mismatch",
)


@dataclass(frozen=True, kw_only=True)
class IdentityDecision:
    """文書1件 vs 既存Article群 の判定結果（監査可能・Black Box禁止）。"""

    decision: IdentityDecisionKind
    document_id: str
    matched_article_id: str = ""  # merge系判定のとき必須
    confidence: Decimal = Decimal("0")  # 0..1（補助値。判断の正はsignals）
    matched_signals: Tuple[str, ...] = ()
    failed_signals: Tuple[str, ...] = ()
    reason_codes: Tuple[str, ...] = ()
    algorithm_version: str = ""
    schema_version: str = SCHEMA_VERSION

    def __post_init__(self) -> None:
        if not self.document_id:
            raise ValueError("document_id is required")
        if not self.algorithm_version:
            raise ValueError("algorithm_version is required（再現・再校正のtrace）")
        if self.decision in MERGING_DECISIONS and not self.matched_article_id:
            raise ValueError(f"{self.decision.value} requires matched_article_id")
        if self.decision is IdentityDecisionKind.CANDIDATE and False:
            pass  # CANDIDATEはmatched_article_id任意（候補先の記録は許す）
        for code in self.matched_signals + self.failed_signals:
            if code not in SIGNAL_CODES:
                raise ValueError(f"unknown signal code: {code}")
        if not isinstance(self.confidence, Decimal):
            raise TypeError("confidence must be Decimal")
