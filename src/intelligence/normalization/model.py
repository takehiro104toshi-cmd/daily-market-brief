"""Normalizationドメインモデル（Phase 1-D）。

- NormalizationIssue … structured issue（silent correction禁止の受け皿）
- NormalizationEvent … 処理イベント（永続）。normalized_at等の処理時刻は**ここだけ**が
  持ち、SourceDocument/Observationのsemantic equalityへ影響しない（record content と
  processing event の分離——監督者指示）。
- NormalizationResult … 1回のnormalize呼び出しの結果（transient）
- derive_source_document_id … RawItem×entry×normalizer versionから決定論的にID導出
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Tuple

from ..core.ids import content_id
from ..core.time import ensure_aware
from ..core.types import SCHEMA_VERSION


class NormalizationStatus(str, Enum):
    NORMALIZED = "normalized"  # 完全に正規化できた
    PARTIAL = "partial"        # 出力はあるがissueあり（例: title有・date不明）
    REJECTED = "rejected"      # 必須identityを満たせず出力ゼロ（RawItemは消さない）


#: issueコード語彙（機械可読。増設は追記のみ）
ISSUE_CODES = (
    "missing_title",
    "missing_date",
    "invalid_date",
    "naive_date",            # tz欠落（勝手にtimezoneを確定しない）
    "date_anomaly_future",
    "date_anomaly_too_old",
    "unsupported_format",
    "malformed_entry",
    "invalid_numeric",
    "unknown_currency",
    "missing_required_field",
    "encoding_issue",
    "missing_locator",
)


@dataclass(frozen=True, kw_only=True)
class NormalizationIssue:
    """structured issue（silent correction禁止）。"""

    code: str
    entry_ref: str = ""  # 対象entry（guid/link/index等）
    detail: str = ""

    def __post_init__(self) -> None:
        if self.code not in ISSUE_CODES:
            raise ValueError(f"unknown issue code: {self.code}")


@dataclass(frozen=True, kw_only=True)
class NormalizationEvent:
    """正規化処理1回分の永続記録（append-only）。

    処理時刻（normalized_at）はこのイベントのみが持つ。SourceDocument/Observationは
    同一入力＋同一versionで常に同一内容になる（決定論の機械検証対象）。
    """

    event_id: str  # norm_<ULID>
    raw_item_id: str
    normalizer_name: str
    normalizer_version: str
    normalized_at: datetime
    status: NormalizationStatus
    issues: Tuple[NormalizationIssue, ...] = ()
    produced_document_ids: Tuple[str, ...] = ()
    produced_observation_ids: Tuple[str, ...] = ()
    note: str = ""
    schema_version: str = SCHEMA_VERSION

    def __post_init__(self) -> None:
        if not self.event_id:
            raise ValueError("event_id is required")
        if not self.raw_item_id:
            raise ValueError("raw_item_id is required")
        if not self.normalizer_name or not self.normalizer_version:
            raise ValueError("normalizer_name/version are required (再処理のtrace)")
        ensure_aware(self.normalized_at, "NormalizationEvent.normalized_at")


@dataclass(frozen=True, kw_only=True)
class NormalizationResult:
    """normalize 1回分の結果（transient。永続はstore側でdocuments/observations/eventへ）。"""

    status: NormalizationStatus
    documents: Tuple = ()      # SourceDocument
    observations: Tuple = ()   # Observation
    issues: Tuple[NormalizationIssue, ...] = ()
    event: NormalizationEvent | None = None


def derive_source_document_id(
    raw_item_id: str, entry_key: str, normalizer_name: str, normalizer_version: str
) -> str:
    """SourceDocument identityの決定論的導出。

    identity階層の区別（P1-D設計判断・docs/normalization/SOURCE_DOCUMENT_SPEC.md）:
    - RawItem identity      … 取得物の内容（content-addressed）
    - **SourceDocument identity … 正規化出力の単位（RawItem×entry×normalizer version）**
    - Article identity      … 記事としての同一性（Phase 2で解決。ここでは未解決でよい）
    - Canonical URL identity … dedup補助（provenanceの代替ではない）

    normalizer versionを含めることで、v1→v2再処理は**新IDの新レコード**になり
    旧出力を破壊しない（reprocessing要件）。
    """
    return content_id("doc", raw_item_id, entry_key, normalizer_name, normalizer_version)
