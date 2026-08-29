"""言明（Statement）とEvidence関係のドメインモデル（Phase 1-A / schema 0.2.0）。

Evidence First Architectureの中核:
- FACT / ANALYSIS / FORECAST を**別クラス**として分離する（God Statement禁止。
  各種別に必要なフィールド・不変条件だけを持たせる）。
- Claim ↔ Evidence は many-to-many（EvidenceLink）。1つのFactを複数文書が支える／
  1つの文書が複数Factを支える、の両方を表現する。
- FACTはEvidence（SUPPORTSリンク）を原則必要とし、無いものは機械的に
  UNSUPPORTED と判定できる（evidence/invariants.py）。AI生成文を自動でFACT扱いしない。
- 矛盾は削除しない: SUPPORTSとCONTRADICTSが併存したら CONFLICTING として保持する。

言明の一次provenanceも「フィールドではなくEvidenceLink」で表現する
（抽出元文書へのSUPPORTSリンクを抽出時に必ず作る）。Observationだけは構造化抽出の
性質上 source_document_id を直接持つ（非対称性の理由はEVIDENCE_DOMAIN_MODEL.md §5）。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from enum import Enum
from typing import ClassVar, Optional, Tuple

from ..core.time import ensure_aware, ensure_aware_or_none
from ..core.types import (
    SCHEMA_VERSION,
    Direction,
    Horizon,
    StatementType,
    VerificationState,
    validate_confidence,
)


class Attribution(str, Enum):
    """FACTの出所の直接性。伝聞（「〜と伝わる」「一部報道」）を種別でなく属性で表す。"""

    DIRECT = "direct"      # 情報源自身の発表・確認済み報道
    REPORTED = "reported"  # 伝聞・二次報道（語尾で減衰させて表示する対象）


class EvidenceRelation(str, Enum):
    SUPPORTS = "supports"          # evidenceがclaimを支持する
    CONTRADICTS = "contradicts"    # evidenceがclaimと矛盾する
    DERIVED_FROM = "derived_from"  # claimがevidenceから導出された（分析の入力）
    CONTEXT = "context"            # 背景情報（支持でも矛盾でもない）


@dataclass(frozen=True, kw_only=True)
class _StatementBase:
    """全言明の共通フィールド。直接は使わずFact/Analysis/Forecastを使う。"""

    statement_type: ClassVar[StatementType]

    statement_id: str
    text: str
    created_at: datetime  # 本システムがこの言明を記録/生成した時刻
    language: str = "ja"
    entities: Tuple[str, ...] = field(default=())  # entity_id参照（解決はPhase 2）
    themes: Tuple[str, ...] = field(default=())
    event_time: Optional[datetime] = None  # 言明が指す出来事の発生時刻
    valid_from: Optional[datetime] = None
    valid_until: Optional[datetime] = None
    verification: VerificationState = VerificationState.UNVERIFIED
    schema_version: str = SCHEMA_VERSION

    def __post_init__(self) -> None:
        if not self.statement_id:
            raise ValueError("statement_id is required")
        if not self.text:
            raise ValueError("text is required")
        ensure_aware(self.created_at, f"{type(self).__name__}.created_at")
        ensure_aware_or_none(self.event_time, "event_time")
        ensure_aware_or_none(self.valid_from, "valid_from")
        ensure_aware_or_none(self.valid_until, "valid_until")


@dataclass(frozen=True, kw_only=True)
class FactStatement(_StatementBase):
    """事実の言明。SUPPORTSリンク（出典文書/観測）を原則必要とする。"""

    statement_type: ClassVar[StatementType] = StatementType.FACT

    attribution: Attribution = Attribution.DIRECT


@dataclass(frozen=True, kw_only=True)
class AnalysisStatement(_StatementBase):
    """分析の言明。入力Evidence・使用ルール・生成agent・生成時刻へ遡れることを型で強制。

    例: fact(米金利上昇) --[rule JP_US_001]--> analysis(高PERグロースのvaluation圧力)
    """

    statement_type: ClassVar[StatementType] = StatementType.ANALYSIS

    inputs: Tuple[str, ...] = field(default=())  # 入力のstatement_id / observation_id（必須≥1）
    rule_id: str = ""  # knowledge/のルールID（例: JP_US_001, CR_RATE_HIKE_001）。必須
    agent: str = ""  # 生成主体（"rule_engine" / モデル名等の実行metadata文字列）。必須

    def __post_init__(self) -> None:
        super().__post_init__()
        if not self.inputs:
            raise ValueError("AnalysisStatement requires inputs (trace to evidence)")
        if not self.rule_id:
            raise ValueError("AnalysisStatement requires rule_id (trace to knowledge rule)")
        if not self.agent:
            raise ValueError("AnalysisStatement requires agent (who generated it)")


@dataclass(frozen=True, kw_only=True)
class ForecastMetadata:
    """予測の検証可能性を担保するメタデータ（Prediction Journal / Phase 5の入力形式）。"""

    target: str  # 予測対象のentity/metric参照（例: "index:nikkei225", "fx:usdjpy"）
    direction: Direction
    horizon: Horizon
    confidence: int  # 0..5（FACT_ANALYSIS_FORECAST_SPEC §3。将来calibration対象）
    generated_at: datetime
    predictor: str  # 予測主体（"rule_engine" / "会社計画" / "市場予想" / モデル名等）
    supporting_evidence: Tuple[str, ...] = field(default=())  # 根拠のid（必須≥1）
    counter_points: Tuple[str, ...] = field(default=())  # 反対材料（id or 記述。生成層で必須化）
    invalidation_conditions: Tuple[str, ...] = field(default=())  # 無効化条件（必須≥1）
    target_low: Optional[Decimal] = None  # レンジ予測の下限（例: 為替159円）
    target_high: Optional[Decimal] = None
    evaluate_by: Optional[datetime] = None  # 答え合わせ予定時点（Phase 5が使用）

    def __post_init__(self) -> None:
        if not self.target:
            raise ValueError("ForecastMetadata.target is required")
        validate_confidence(self.confidence)
        ensure_aware(self.generated_at, "ForecastMetadata.generated_at")
        ensure_aware_or_none(self.evaluate_by, "ForecastMetadata.evaluate_by")
        if not self.predictor:
            raise ValueError("ForecastMetadata.predictor is required")
        if not self.supporting_evidence:
            raise ValueError("ForecastMetadata requires supporting_evidence (>=1)")
        if not self.invalidation_conditions:
            raise ValueError("ForecastMetadata requires invalidation_conditions (>=1)")
        for name in ("target_low", "target_high"):
            v = getattr(self, name)
            if v is not None and not isinstance(v, Decimal):
                raise TypeError(f"{name} must be Decimal or None (float禁止)")


@dataclass(frozen=True, kw_only=True)
class ForecastStatement(_StatementBase):
    """予測の言明。ForecastMetadata必須（型レベルで強制）。"""

    statement_type: ClassVar[StatementType] = StatementType.FORECAST

    forecast: Optional[ForecastMetadata] = None  # kw_only都合でOptional宣言・実際は必須

    def __post_init__(self) -> None:
        super().__post_init__()
        if self.forecast is None:
            raise ValueError("ForecastStatement requires ForecastMetadata")


# 型注釈用の総称（isinstance検査にも使える）
Statement = _StatementBase


@dataclass(frozen=True, kw_only=True)
class EvidenceLink:
    """Claim（statement）とEvidence（document/observation/statement）のmany-to-many関係。"""

    link_id: str  # link_<ULID>
    claim_id: str  # statement_id
    evidence_id: str  # source_document_id / observation_id / statement_id
    relation: EvidenceRelation
    created_at: datetime
    note: str = ""
    schema_version: str = SCHEMA_VERSION

    def __post_init__(self) -> None:
        if not self.link_id:
            raise ValueError("link_id is required")
        if not self.claim_id:
            raise ValueError("claim_id is required")
        if not self.evidence_id:
            raise ValueError("evidence_id is required")
        if self.claim_id == self.evidence_id:
            raise ValueError("claim cannot evidence itself")
        ensure_aware(self.created_at, "EvidenceLink.created_at")
