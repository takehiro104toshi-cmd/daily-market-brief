"""数値Observation正規化（Phase 1-D）。JSON APIのprovider別mapping枠組み。

規律:
- **明示schemaからのみ生成**（意味推測による数値抽出は禁止）。mappingは
  JsonProviderSpec（宣言的なフィールドパス）で与える。
- 金融値はDecimal（json解析時点で parse_float=Decimal。floatを経由しない）。
- raw（APIが直接提供）とderived（本システム計算）を区別。derivedは
  input_observation_ids＋calculation_method必須（P1-A Observationが型で強制）。
- 決定論: observation_idはcontent-addressed（同一入力＋同一version→同一ID）。
- EDINET/e-Stat等の本格business mappingはP1-E以降。ここではframeworkと
  synthetic providerでの実証まで。
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import List, Optional, Protocol, Tuple, runtime_checkable

from ..core.ids import content_id, new_id
from ..market.model import Observation, ObservationKind
from ..sources.model import RawItem
from .model import (
    NormalizationEvent,
    NormalizationIssue,
    NormalizationResult,
    NormalizationStatus,
)

NORMALIZER_NAME = "json_observation"
NORMALIZER_VERSION = "1.0.0"

#: 通貨コードの妥当性（ISO 4217の主要通貨。増設は追記）
KNOWN_CURRENCIES = frozenset({
    "JPY", "USD", "EUR", "GBP", "CNY", "CHF", "AUD", "CAD", "KRW", "INR", "HKD", "SGD",
})


@dataclass(frozen=True, kw_only=True)
class ObservationFieldSpec:
    """JSON payload中の1数値フィールド → Observation のmapping宣言。"""

    value_path: str  # ドット区切りパス（例: "data.usdjpy.rate"）
    entity_id: str   # 例: "fx:USDJPY"
    metric: str      # 例: "rate"
    unit: str        # units.py語彙 or "index"/"jpy"等
    currency: str = ""
    as_of_path: str = ""  # tz付きISO8601のパス（spec.default_as_of_pathへフォールバック）
    required: bool = True


@dataclass(frozen=True, kw_only=True)
class JsonProviderSpec:
    """provider別mapping（明示schema。推測しない）。"""

    provider: str  # 例: "synthetic_market_v1"
    fields: Tuple[ObservationFieldSpec, ...]
    default_as_of_path: str = ""


@runtime_checkable
class JsonRecordNormalizer(Protocol):
    """provider固有JSON正規化の抽象（将来のEDINET/e-Stat adapterの口）。"""

    def normalize(self, raw_item: RawItem, body: bytes) -> NormalizationResult:  # pragma: no cover
        ...


def _lookup(payload, path: str):
    cur = payload
    for part in path.split("."):
        if not isinstance(cur, dict) or part not in cur:
            return None
        cur = cur[part]
    return cur


def _as_decimal(value) -> Optional[Decimal]:
    if isinstance(value, Decimal):
        return value
    if isinstance(value, bool):  # boolはintのsubclass——数値として受けない
        return None
    if isinstance(value, int):
        return Decimal(value)
    if isinstance(value, str):
        try:
            return Decimal(value.strip())
        except (InvalidOperation, ValueError):
            return None
    return None  # floatはparse_float=Decimalにより到達しない


def _as_aware(value) -> Optional[datetime]:
    if not isinstance(value, str):
        return None
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return dt if dt.tzinfo is not None else None  # naiveは採用しない


def observation_identity(
    raw_item_id: str, entity_id: str, metric: str, as_of_iso: str, version: str
) -> str:
    """決定論的observation_id（同一入力＋同一version→同一ID。再現可能性要件）。"""
    return content_id("obs", raw_item_id, entity_id, metric, as_of_iso, version)


def normalize_json_observations(
    raw_item: RawItem,
    body: bytes,
    spec: JsonProviderSpec,
    *,
    source_document_id: str = "",
    normalizer_version: str = NORMALIZER_VERSION,
    now: Optional[datetime] = None,
) -> NormalizationResult:
    """明示mappingに従いJSONからRAW Observationを生成する。例外を投げない。"""
    issues: List[NormalizationIssue] = []
    observations: List[Observation] = []

    try:
        payload = json.loads(body.decode("utf-8"), parse_float=Decimal)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        issues.append(NormalizationIssue(code="unsupported_format", detail=str(exc)[:120]))
        payload = None

    if isinstance(payload, dict):
        for f in spec.fields:
            ref = f"{f.entity_id}:{f.metric}"
            value = _as_decimal(_lookup(payload, f.value_path))
            if value is None:
                raw_val = _lookup(payload, f.value_path)
                code = "missing_required_field" if raw_val is None else "invalid_numeric"
                if raw_val is None and not f.required:
                    continue  # 任意フィールドの欠損はissueにしない
                issues.append(NormalizationIssue(
                    code=code, entry_ref=ref,
                    detail="" if raw_val is None else str(raw_val)[:40]))
                continue
            if f.currency and f.currency not in KNOWN_CURRENCIES:
                issues.append(NormalizationIssue(
                    code="unknown_currency", entry_ref=ref, detail=f.currency))
                continue
            as_of = _as_aware(_lookup(payload, f.as_of_path or spec.default_as_of_path))
            if as_of is None:
                # retrieved_atを黙って代入しない（日付規律はObservationでも同じ）
                issues.append(NormalizationIssue(
                    code="missing_required_field", entry_ref=ref, detail="as_of (tz-aware)"))
                continue
            as_of_iso = as_of.astimezone(timezone.utc).isoformat()
            observations.append(Observation(
                observation_id=observation_identity(
                    raw_item.raw_item_id, f.entity_id, f.metric, as_of_iso,
                    normalizer_version),
                entity_id=f.entity_id,
                metric=f.metric,
                value=value,
                unit=f.unit,
                currency=f.currency,
                as_of=as_of,
                kind=ObservationKind.RAW,
                calculation_method=f"api_field:{spec.provider}:{f.value_path}",
                source_id=raw_item.source_id,
                source_document_id=source_document_id,
            ))
    elif payload is not None:
        issues.append(NormalizationIssue(
            code="unsupported_format", detail="JSON root must be an object"))

    if not observations:
        status = NormalizationStatus.REJECTED
    elif issues:
        status = NormalizationStatus.PARTIAL
    else:
        status = NormalizationStatus.NORMALIZED

    normalized_at = now or datetime.now(timezone.utc)
    event = NormalizationEvent(
        event_id=new_id("norm", normalized_at),
        raw_item_id=raw_item.raw_item_id,
        normalizer_name=f"{NORMALIZER_NAME}:{spec.provider}",
        normalizer_version=normalizer_version,
        normalized_at=normalized_at,
        status=status,
        issues=tuple(issues),
        produced_observation_ids=tuple(o.observation_id for o in observations),
    )
    return NormalizationResult(
        status=status, observations=tuple(observations), issues=tuple(issues), event=event
    )


def derived_observation(
    *,
    entity_id: str,
    metric: str,
    value: Decimal,
    unit: str,
    as_of: datetime,
    inputs: Tuple[str, ...],
    calculation_method: str,
    normalizer_version: str = NORMALIZER_VERSION,
    currency: str = "",
) -> Observation:
    """DERIVED observationの決定論的生成（inputs・calculation_method必須はP1-A型が強制）。"""
    as_of_iso = as_of.astimezone(timezone.utc).isoformat()
    return Observation(
        observation_id=observation_identity(
            "derived", entity_id, metric, as_of_iso, normalizer_version),
        entity_id=entity_id,
        metric=metric,
        value=value,
        unit=unit,
        currency=currency,
        as_of=as_of,
        kind=ObservationKind.DERIVED,
        calculation_method=calculation_method,
        inputs=inputs,
    )
