"""ドメインオブジェクトのシリアライズ（Phase 1-A）。

方針:
- JSON互換dictへの往復変換（roundtrip）。`_type`タグでクラスを識別する。
- datetime → UTC正規化ISO 8601文字列（tz-aware必須はfrom側で再検証される）
- Decimal → 文字列（精度を落とさない。floatを経由しない）
- Enum → value
- tuple → list（decode時にtupleへ戻す）
- ネストしたdataclass（ForecastMetadata等）→ 再帰
- 標準ライブラリのみ。ストレージ形式（JSONL/SQLite/Parquet）から独立し、
  将来のDB移行でもdomain層を壊さない（docs/evidence/STORAGE_DECISION.md）。
"""
from __future__ import annotations

import dataclasses
from datetime import datetime
from decimal import Decimal
from enum import Enum
from typing import Any, Dict, Mapping, Optional, Type, get_args, get_origin, get_type_hints

from .time import from_iso, to_utc_iso

_REGISTRY: Dict[str, type] = {}


def register(cls: type) -> type:
    """roundtrip対象のdataclassを登録する（クラスデコレータとしても使用可）。"""
    _REGISTRY[cls.__name__] = cls
    return cls


def registered_types() -> Mapping[str, type]:
    return dict(_REGISTRY)


def encode(obj: Any) -> Dict[str, Any]:
    """登録済みdataclass → JSON互換dict（`_type`タグ付き）。"""
    cls = type(obj)
    if cls.__name__ not in _REGISTRY:
        raise TypeError(f"{cls.__name__} is not registered for serialization")
    data: Dict[str, Any] = {"_type": cls.__name__}
    for f in dataclasses.fields(obj):
        data[f.name] = _encode_value(getattr(obj, f.name))
    return data


def _encode_value(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, bool)):
        return value
    if isinstance(value, float):
        raise TypeError("float is not allowed in domain serialization (use Decimal)")
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, datetime):
        return to_utc_iso(value)
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, (tuple, list)):
        return [_encode_value(v) for v in value]
    if dataclasses.is_dataclass(value):
        return encode(value)
    raise TypeError(f"cannot encode value of type {type(value).__name__}")


def decode(data: Mapping[str, Any]) -> Any:
    """encode()の逆変換。`_type`から型を引き、フィールド型注釈に従って復元する。"""
    type_name = data.get("_type")
    if not type_name or type_name not in _REGISTRY:
        raise ValueError(f"unknown or missing _type: {type_name!r}")
    cls = _REGISTRY[type_name]
    hints = get_type_hints(cls)
    kwargs: Dict[str, Any] = {}
    for f in dataclasses.fields(cls):
        if f.name not in data:
            continue  # 未知スキーマ差分は欠落として扱い、defaultに委ねる（0.x前方互換）
        kwargs[f.name] = _decode_value(data[f.name], hints[f.name])
    return cls(**kwargs)


def _decode_value(value: Any, hint: Any) -> Any:
    if value is None:
        return None
    origin = get_origin(hint)
    if origin is not None:
        args = get_args(hint)
        if origin is tuple:
            elem = args[0] if args else str
            return tuple(_decode_value(v, elem) for v in value)
        # Union / Optional: Noneでない最初の型で復元（本モデルの合成はOptional[X]のみ）
        non_none = [a for a in args if a is not type(None)]
        if non_none:
            return _decode_value(value, non_none[0])
        return value
    if isinstance(hint, type):
        if issubclass(hint, datetime):
            return from_iso(value)
        if issubclass(hint, Decimal):
            return Decimal(str(value))
        if issubclass(hint, Enum):
            return hint(value)
        if dataclasses.is_dataclass(hint):
            return decode(value)
        if issubclass(hint, bool):
            return bool(value)
        if issubclass(hint, int):
            return int(value)
        if issubclass(hint, str):
            return str(value)
    return value


def register_domain_types() -> None:
    """全ドメイン型を登録する（import副作用を避けるため明示呼び出し）。"""
    from ..evidence import model as ev
    from ..evidence_qa import model as qa
    from ..ingestion import model as ing
    from ..market import model as mk
    from ..normalization import model as norm
    from ..sources import model as src
    from . import types as core_types

    for cls in (
        src.Source,
        src.RawItem,
        src.SourceDocument,
        src.SourceEndpoint,
        src.SourceHealthObservation,
        ing.FetchAttempt,
        norm.NormalizationIssue,
        norm.NormalizationEvent,
        qa.DimensionResult,
        qa.QAIssue,
        qa.EvidenceAssessment,
        mk.Observation,
        ev.FactStatement,
        ev.AnalysisStatement,
        ev.ForecastStatement,
        ev.ForecastMetadata,
        ev.EvidenceLink,
        core_types.LLMResult,
    ):
        register(cls)


def decode_statement_or_link(data: Mapping[str, Any]) -> Any:
    """JSONLストア用の便宜関数（decodeと同じだが意図を明示）。"""
    return decode(data)
