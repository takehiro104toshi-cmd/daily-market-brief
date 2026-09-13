"""Evaluation record / axis result（Phase 3.9.2）— schema-versioned, deterministic, no source text。

evaluation は **derived**（rebuildable）であり Decision ではない。record には本文・observation text・PDF path を
入れない（id / count / label / version だけ）。`inputs_digest` は axis 入力の content hash で、
同じ入力 + 同じ policy → 同じ recommendation を Phase 3.9.4 replay が検証できるようにする。
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field, fields
from typing import Any, Dict, List, Mapping, Optional, Tuple

from .config import AXES, AXIS_STATES, CORE_AXES, PATTERN_TYPES

SCHEMA_VERSION = "1.0.0"

APPLICABLE = "APPLICABLE"
NOT_APPLICABLE = "NOT_APPLICABLE"
APPLICABILITY = (APPLICABLE, NOT_APPLICABLE)

NOT_READY = "NOT_READY"
KEEP_REVIEWING = "KEEP_REVIEWING"
REVIEW_RECOMMENDED = "REVIEW_RECOMMENDED"
APPROVE_RECOMMENDED = "APPROVE_RECOMMENDED"
REJECT_RECOMMENDED = "REJECT_RECOMMENDED"
RECOMMENDATION_STATES: Tuple[str, ...] = (NOT_READY, REJECT_RECOMMENDED, APPROVE_RECOMMENDED,
                                          REVIEW_RECOMMENDED, KEEP_REVIEWING)

#: すべての結論へ必ず付ける boundary（Phase 3.8 の NOT_PREDICTIVE を引き継ぐ）
BASE_LIMITATIONS: Tuple[str, ...] = (
    "NOT_PREDICTIVE: evaluation measures analytical reconstruction, not forecasting accuracy",
    "RECOMMENDATION_IS_ADVICE: APPROVE_RECOMMENDED is not APPROVED and never promotes to Compass DNA",
)
#: Consistency HIGH の構造的な限界（direction は pattern identity に含まれるため supporting document は必ず一致する）
CONSISTENCY_TAUTOLOGY_LIMITATION = (
    "CONSISTENCY_HIGH_IS_NOT_CORROBORATION: supporting documents share the pattern's stated direction by identity")

#: evidence snapshot に絶対入れない key（Phase 3.9.1 と同じ守り）
FORBIDDEN_KEYS: Tuple[str, ...] = ("text", "source_text", "page_text", "body", "raw", "statement", "path")


def canonical_json(obj: Any) -> str:
    return json.dumps(obj, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)


def sha256_hex(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class AxisResult:
    """1 axis の結果。state は常に LOW/MEDIUM/HIGH（4 番目の state を作らない）。
    applicability は score 用の別次元で、構造的不可能のときだけ NOT_APPLICABLE。"""
    axis: str
    state: str
    applicability: str = APPLICABLE
    reason: str = ""                                  # NOT_APPLICABLE の構造的理由 / state の根拠 code
    metrics: Mapping[str, Any] = field(default_factory=dict)

    @property
    def applicable(self) -> bool:
        return self.applicability == APPLICABLE

    def as_dict(self) -> Dict[str, Any]:
        return {"axis": self.axis, "state": self.state, "applicability": self.applicability,
                "reason": self.reason, "metrics": dict(self.metrics)}


@dataclass(frozen=True)
class EvaluationRecord:
    evaluation_id: str
    pattern_id: str
    pattern_type: str
    pattern_version: str
    evaluated_at: str
    axis_states: Mapping[str, str]
    axis_applicability: Mapping[str, str]
    axis_metrics: Mapping[str, Any]
    axis_reasons: Mapping[str, str]
    reference_score: Optional[float]
    reference_score_comparable: bool
    applicable_axes: Tuple[str, ...]
    applicable_weight_sum: int
    recommendation: str
    triggered_rule: str
    blocking_rules: Tuple[str, ...]
    supporting_rules: Tuple[str, ...]
    evaluation_policy_version: str
    evaluation_policy_digest: str
    recommendation_policy_version: str
    recommendation_policy_digest: str
    shadow_mode: bool
    formal_review_gate_reached: bool
    corpus_size: int
    corpus_milestone: str
    inputs_digest: str
    confirmation_3d: Mapping[str, Any] = field(default_factory=dict)
    relative_support_share: Optional[float] = None
    relative_support_applicability: str = NOT_APPLICABLE
    reopen_signal: Optional[bool] = None
    approved_adverse_signal: Optional[bool] = None
    decision_state: str = ""
    limitations: Tuple[str, ...] = ()
    schema_version: str = SCHEMA_VERSION

    def as_dict(self) -> Dict[str, Any]:
        out: Dict[str, Any] = {}
        for f in fields(self):
            v = getattr(self, f.name)
            if isinstance(v, tuple):
                v = list(v)
            elif isinstance(v, Mapping):
                v = dict(v)
            out[f.name] = v
        return out

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "EvaluationRecord":
        names = {f.name for f in fields(cls)}
        kw = {k: v for k, v in dict(data).items() if k in names}
        for key in ("applicable_axes", "blocking_rules", "supporting_rules", "limitations"):
            kw[key] = tuple(str(x) for x in (kw.get(key) or []))
        for key in ("axis_states", "axis_applicability", "axis_metrics", "axis_reasons", "confirmation_3d"):
            kw[key] = dict(kw.get(key) or {})
        return cls(**kw)


def evaluation_id_for(pattern_id: str, evaluation_policy_digest: str, recommendation_policy_digest: str,
                      inputs_digest: str) -> str:
    """deterministic id: 同じ pattern + 同じ policy + 同じ入力 → 同じ id（replay で照合できる）。"""
    seed = canonical_json({"pattern_id": pattern_id, "evaluation_policy_digest": evaluation_policy_digest,
                           "recommendation_policy_digest": recommendation_policy_digest,
                           "inputs_digest": inputs_digest, "schema_version": SCHEMA_VERSION})
    return "cev_" + sha256_hex(seed)[:16]


def inputs_digest_for(payload: Mapping[str, Any]) -> str:
    """axis 入力だけの hash（timestamp / policy を含めない）。replay 検証の基準。"""
    return sha256_hex(canonical_json(payload))[:16]


def validate_record(row: Mapping[str, Any]) -> List[str]:
    """schema-level validation（error code の list。空 = valid）。"""
    errors: List[str] = []
    if not isinstance(row, Mapping):
        return ["RECORD_NOT_OBJECT"]
    missing = sorted({f.name for f in fields(EvaluationRecord)} - set(row.keys()))
    if missing:
        return ["MISSING_FIELDS:" + ",".join(missing)]
    if str(row["schema_version"]) != SCHEMA_VERSION:
        errors.append("SCHEMA_VERSION_MISMATCH")
    if not str(row["evaluation_id"]).startswith("cev_"):
        errors.append("EVALUATION_ID_FORMAT")
    if not str(row["pattern_id"]).strip():
        errors.append("PATTERN_ID_MISSING")
    if row["pattern_type"] not in PATTERN_TYPES:
        errors.append("PATTERN_TYPE_UNKNOWN")
    if row["recommendation"] not in RECOMMENDATION_STATES:
        errors.append("RECOMMENDATION_UNKNOWN")
    states = dict(row["axis_states"] or {})
    applic = dict(row["axis_applicability"] or {})
    if set(states) != set(AXES):
        errors.append("AXIS_STATES_INCOMPLETE")
    if any(v not in AXIS_STATES for v in states.values()):
        errors.append("AXIS_STATE_UNKNOWN")
    if set(applic) != set(AXES) or any(v not in APPLICABILITY for v in applic.values()):
        errors.append("AXIS_APPLICABILITY_INVALID")
    if not isinstance(row["applicable_weight_sum"], int) or not 0 <= row["applicable_weight_sum"] <= 100:
        errors.append("APPLICABLE_WEIGHT_SUM_INVALID")
    if row["reference_score_comparable"]:
        score = row["reference_score"]
        if not isinstance(score, (int, float)) or not 0 <= float(score) <= 100:
            errors.append("REFERENCE_SCORE_INVALID")
    elif row["reference_score"] is not None:
        errors.append("NOT_COMPARABLE_SCORE_MUST_BE_NULL")
    if not str(row["inputs_digest"]):
        errors.append("INPUTS_DIGEST_MISSING")
    if not str(row["evaluation_policy_digest"]) or not str(row["recommendation_policy_digest"]):
        errors.append("POLICY_DIGEST_MISSING")
    blob = canonical_json(row)
    for key in FORBIDDEN_KEYS:
        if f'"{key}":' in blob:
            errors.append(f"FORBIDDEN_KEY:{key}")
    if row["recommendation"] != NOT_READY and len(row["applicable_axes"]) == 0:
        errors.append("NO_APPLICABLE_AXES")
    core_applicable = sum(1 for a in CORE_AXES if applic.get(a) == APPLICABLE)
    if row["recommendation"] == APPROVE_RECOMMENDED and core_applicable < 2:
        errors.append("APPROVE_WITH_TOO_FEW_CORE_AXES")
    return errors
