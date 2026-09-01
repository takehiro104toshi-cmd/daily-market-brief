"""Fact domain model（Phase 3-A STEP 4/5/6/12/15/20）。

**FACT ≠ INTERPRETATION ≠ OUTLOOK ≠ RECOMMENDATION**。
本モジュールが表すのは「機械的に確認できる事実」だけ。解釈・見通し・推奨は持たない。

既存modelとの責務分担（Phase 3用だからと同一概念を再定義しない）:
- `market.model.Observation` … 系列の**観測値**（raw/derived）。Fact Layerの入力。
- `evidence.model.FactStatement` … **文章としての**事実言明（`text`を持ち、
  EvidenceLinkで出典に結びつく）。Phase 1-Aの資産で、本モジュールは置き換えない。
- 本モジュールの `Fact` … Compassが計算・比較に使う**定量的なatomic fact**
  （subject × fact_type × 時点 → 値）。文章ではない。text由来のFactは
  `FactEvidenceRef` で文書・言明・該当箇所へ遡れるようにする（citation-ready）。

規律:
- **決定論的ID**: 同じGround Truthからは何度作っても同じ `fact_id`。
- **provenance必須**: 全Factが少なくとも1つのevidence refを持つ。derivedは入力fact/
  observation IDを保持する。「LLMがそう言った」はprovenanceにしない。
- **値はDecimal**（float非経由）。欠測はNone——0や前値で埋めない。
- **as-of意味論**を混同しない（event / trading / publication / retrieved / as_of）。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from enum import Enum
from typing import Dict, Mapping, Optional, Tuple

from ..core.ids import content_id
from ..core.time import ensure_aware, ensure_aware_or_none

#: Fact Layerのschema版数（0.x間は前方互換: 未知フィールドは無視）
FACT_SCHEMA_VERSION = "0.1.0"


class FactStatus(str, Enum):
    """Factの利用可否（FAIL-CLOSED: 疑わしいものをusableにしない）。"""

    USABLE = "usable"                # 通常利用可
    LIMITED_USE = "limited_use"      # 出所の品質が限定的（利用側で明示的に判断する）
    UNUSABLE = "unusable"            # 生成条件を満たさない（値を持たない）
    SUPERSEDED = "superseded"        # 後続revisionに置き換えられた


class ConflictState(str, Enum):
    """同一Fact候補が複数sourceから来たときの状態（勝手に片方を正解にしない）。"""

    AGREE = "agree"
    CONFLICT = "conflict"
    STALE = "stale"
    SUPERSEDED = "superseded"
    UNKNOWN = "unknown"


class DateRole(str, Enum):
    """Fact typeごとに「どの日付が意味を持つか」を明示する（STEP 20）。"""

    TRADING_DATE = "trading_date"        # 取引日（東京/米国セッション）
    EVENT_DATE = "event_date"            # 出来事の発生・効力発生日
    PUBLICATION_DATE = "publication_date"  # 公表日
    PERIOD_END = "period_end"            # 対象期間の末日（週次・四半期等）


class EvidenceKind(str, Enum):
    """Factの根拠の種類。"""

    OBSERVATION = "observation"      # market Observation
    DOCUMENT = "document"            # 記事・開示文書
    STATEMENT = "statement"          # FactStatement等の言明
    RECORD = "record"                # J-Quants構造化レコード
    FACT = "fact"                    # 他のFact（derivedの入力）


@dataclass(frozen=True, kw_only=True)
class FactSubject:
    """Factの主体（何についての事実か）。

    series/entity/securityを**同一視しない**。系列の事実（TOPIX終値）と
    銘柄の事実（7203の決算予定）は別のsubject種別として扱う。
    """

    subject_type: str          # "series" / "entity" / "security" / "market"
    subject_id: str            # 例: "index:topix.close.closing.tokyo" / "jp:security:72030"
    display_name: str = ""

    def key(self) -> str:
        return f"{self.subject_type}:{self.subject_id}"

    def __post_init__(self) -> None:
        if not self.subject_type or not self.subject_id:
            raise ValueError("FactSubject requires subject_type and subject_id")


@dataclass(frozen=True, kw_only=True)
class FactValue:
    """Factの値。**欠測はNone**（0で埋めない）。floatは持たない。"""

    value: Optional[Decimal] = None
    unit: str = ""
    currency: str = ""
    text_value: str = ""       # 数値でない事実（イベント名・区分等）

    def __post_init__(self) -> None:
        if self.value is not None and not isinstance(self.value, Decimal):
            raise TypeError("FactValue.value must be Decimal (float is rejected)")
        if self.value is None and not self.text_value:
            # 値なしFactは許すが、その場合statusはUNUSABLEであるべき（builderが保証）
            pass

    @property
    def has_value(self) -> bool:
        return self.value is not None or bool(self.text_value)


@dataclass(frozen=True, kw_only=True)
class FactTimeContext:
    """Factの時間軸（**混同禁止**の日付群）。

    - `primary_date` … このFact typeにとって意味を持つ日付（`date_role`が種別を示す）
    - `as_of` … 値が指す時点（aware datetime）
    - `known_at` … **この事実がシステムから見て既知になった時刻**。
      Morning availability / look-ahead防止はこれで判定する。
    """

    primary_date: str                       # ISO日付
    date_role: DateRole
    as_of: Optional[datetime] = None
    known_at: Optional[datetime] = None
    period_start: str = ""
    period_end: str = ""
    session_count: int = 0                  # N-session計算に使ったセッション数

    def __post_init__(self) -> None:
        if not self.primary_date:
            raise ValueError("FactTimeContext requires primary_date")
        ensure_aware_or_none(self.as_of, "FactTimeContext.as_of")
        ensure_aware_or_none(self.known_at, "FactTimeContext.known_at")


@dataclass(frozen=True, kw_only=True)
class FactEvidenceRef:
    """Factの根拠1件（citation-ready）。

    text由来のFactは `excerpt_start`/`excerpt_end`（正規化本文中の位置）または
    `locator` で「記事のどこが根拠なのか」まで辿れるようにする。
    """

    kind: EvidenceKind
    ref_id: str                  # observation_id / document_id / statement_id / record_id
    locator: str = ""            # 章・フィールド名等（**credentialを含むURLは保存しない**）
    excerpt: str = ""            # 根拠箇所の抜粋（要約ではなく原文）
    excerpt_start: int = -1
    excerpt_end: int = -1
    qa_decision: str = ""        # 由来evidenceのQA判定（accept / limited_use 等）

    def __post_init__(self) -> None:
        if not self.ref_id:
            raise ValueError("FactEvidenceRef requires ref_id")

    def as_dict(self) -> Dict[str, object]:
        return {
            "kind": self.kind.value, "ref_id": self.ref_id, "locator": self.locator,
            "excerpt": self.excerpt, "excerpt_start": self.excerpt_start,
            "excerpt_end": self.excerpt_end, "qa_decision": self.qa_decision,
        }


@dataclass(frozen=True, kw_only=True)
class FactCalculation:
    """derived Factの計算メタ（STEP 12。計算変更時に旧Factと区別できるようにする）。"""

    name: str                    # 例: "return_pct"
    version: str                 # 例: "1.0.0"
    inputs: Tuple[str, ...] = ()  # 入力のobservation_id / fact_id
    parameters: Mapping[str, str] = field(default_factory=dict)

    @property
    def method(self) -> str:
        return f"{self.name}:{self.version}"

    def __post_init__(self) -> None:
        if not self.name or not self.version:
            raise ValueError("FactCalculation requires name and version")


@dataclass(frozen=True, kw_only=True)
class Fact:
    """検証済みatomic fact。

    `fact_id` は **決定論的**（subject × fact_type × 時点 × 計算 × 値 から導出）。
    同一Ground Truthから何度生成しても同じIDになり、値が変われば別IDになるため、
    `revision_of` で履歴を辿れる（過去Factを消さない）。
    """

    fact_id: str
    fact_type: str
    subject: FactSubject
    value: FactValue
    time: FactTimeContext
    evidence: Tuple[FactEvidenceRef, ...] = ()
    calculation: Optional[FactCalculation] = None
    status: FactStatus = FactStatus.USABLE
    conflict_state: ConflictState = ConflictState.UNKNOWN
    conflicting_fact_ids: Tuple[str, ...] = ()
    source_ids: Tuple[str, ...] = ()          # 供給元（"jquants" / "mof_japan" 等）
    qa_decision: str = ""                     # 代表QA判定（最も弱いもの）
    revision_of: str = ""
    created_at: Optional[datetime] = None
    schema_version: str = FACT_SCHEMA_VERSION
    note: str = ""

    def __post_init__(self) -> None:
        if not self.fact_id:
            raise ValueError("fact_id is required")
        if not self.fact_type:
            raise ValueError("fact_type is required")
        ensure_aware_or_none(self.created_at, "Fact.created_at")
        if self.status is FactStatus.USABLE and not self.evidence:
            # provenance無しのFactをusableにしない（FAIL-CLOSED）
            raise ValueError("usable Fact requires at least one evidence ref")
        if self.status is FactStatus.USABLE and not self.value.has_value:
            raise ValueError("usable Fact requires a value")

    @property
    def is_derived(self) -> bool:
        return self.calculation is not None

    @property
    def input_ids(self) -> Tuple[str, ...]:
        return self.calculation.inputs if self.calculation else ()

    def as_dict(self) -> Dict[str, object]:
        return {
            "fact_id": self.fact_id,
            "fact_type": self.fact_type,
            "subject_type": self.subject.subject_type,
            "subject_id": self.subject.subject_id,
            "display_name": self.subject.display_name,
            "value": str(self.value.value) if self.value.value is not None else "",
            "text_value": self.value.text_value,
            "unit": self.value.unit,
            "currency": self.value.currency,
            "primary_date": self.time.primary_date,
            "date_role": self.time.date_role.value,
            "as_of": self.time.as_of.isoformat() if self.time.as_of else "",
            "known_at": self.time.known_at.isoformat() if self.time.known_at else "",
            "period_start": self.time.period_start,
            "period_end": self.time.period_end,
            "session_count": self.time.session_count,
            "calculation_method": self.calculation.method if self.calculation else "",
            "calculation_inputs": list(self.input_ids),
            "calculation_parameters": dict(self.calculation.parameters)
                                      if self.calculation else {},
            "evidence": [e.as_dict() for e in self.evidence],
            "status": self.status.value,
            "conflict_state": self.conflict_state.value,
            "conflicting_fact_ids": list(self.conflicting_fact_ids),
            "source_ids": list(self.source_ids),
            "qa_decision": self.qa_decision,
            "revision_of": self.revision_of,
            "created_at": self.created_at.isoformat() if self.created_at else "",
            "schema_version": self.schema_version,
            "note": self.note,
        }


def make_fact_id(
    *,
    fact_type: str,
    subject: FactSubject,
    primary_date: str,
    value_token: str,
    calculation_method: str = "",
) -> str:
    """**決定論的**なfact_id（同一Ground Truth → 同一ID）。

    `created_at` や取得時刻は**含めない**（処理時刻でIDが変わらないようにする）。
    値を含めるため、値が変われば別IDになり `revision_of` で履歴を辿れる。
    """
    return content_id("fact", fact_type, subject.key(), primary_date,
                      calculation_method, value_token)


def value_token(value: Optional[Decimal], text_value: str = "") -> str:
    """ID生成用の値トークン（Decimalの正規表現を固定して安定させる）。"""
    if value is not None:
        return format(value.normalize(), "f")
    return text_value
