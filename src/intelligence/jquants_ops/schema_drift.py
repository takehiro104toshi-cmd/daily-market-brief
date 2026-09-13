"""Schema drift detection（Phase 3.6 §22）。

J-Quants 応答の項目名を registry の実測項目（P2-H run #1）と比較し、

- unknown field の**追加**（情報。取り込みは継続。registry 更新候補）
- required field の**欠落**（error。1行も取り込まない＝既存 client の schema_error）

を区別する。silent coercion（型や名前の勝手な読み替え）はしない。
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Sequence, Tuple

from ..market.jquants_light_datasets import get_dataset

SCHEMA_OK = "OK"
UNKNOWN_FIELDS_ADDED = "UNKNOWN_FIELDS_ADDED"
REQUIRED_FIELD_MISSING = "REQUIRED_FIELD_MISSING"
OBSERVED_FIELD_MISSING = "OBSERVED_FIELD_MISSING"
NOT_REGISTERED = "NOT_REGISTERED"


@dataclass(frozen=True, kw_only=True)
class SchemaDrift:
    dataset: str
    status: str
    unknown_fields: Tuple[str, ...] = ()
    missing_required: Tuple[str, ...] = ()
    missing_observed: Tuple[str, ...] = ()

    @property
    def blocks_ingest(self) -> bool:
        return self.status == REQUIRED_FIELD_MISSING

    def as_dict(self) -> Dict[str, object]:
        return {"dataset": self.dataset, "status": self.status,
                "unknown_fields": list(self.unknown_fields),
                "missing_required": list(self.missing_required),
                "missing_observed": list(self.missing_observed),
                "blocks_ingest": self.blocks_ingest}


def check_schema(dataset: str, observed_fields: Sequence[str]) -> SchemaDrift:
    spec = get_dataset(dataset)
    if spec is None:
        return SchemaDrift(dataset=dataset, status=NOT_REGISTERED)
    observed = set(observed_fields)
    if not observed:
        return SchemaDrift(dataset=dataset, status=SCHEMA_OK)      # 空応答は別の失敗種別で扱う
    missing_required = tuple(f for f in spec.required_fields if f not in observed)
    known = set(spec.observed_fields) | set(spec.required_fields)
    unknown = tuple(sorted(observed - known)) if known else ()
    missing_observed = tuple(f for f in spec.observed_fields if f not in observed) \
        if spec.observed_fields else ()
    if missing_required:
        status = REQUIRED_FIELD_MISSING
    elif unknown:
        status = UNKNOWN_FIELDS_ADDED
    elif missing_observed:
        status = OBSERVED_FIELD_MISSING
    else:
        status = SCHEMA_OK
    return SchemaDrift(dataset=dataset, status=status, unknown_fields=unknown,
                       missing_required=missing_required, missing_observed=missing_observed)


def drift_report(observations: Dict[str, Sequence[str]]) -> List[Dict[str, object]]:
    return [check_schema(k, v).as_dict() for k, v in observations.items()]
