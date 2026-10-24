"""P13-A1 — 標本の間の変化（`ReviewStateChange`）の純粋な model。

P12.5-A2 §7.2 の意味: 2 つの標本 T1 < T2 の **端点の差**だけを記録する。「(T1, T2] の区間のどこかで変わった」以上を主張しない
（正確な transition の瞬間 ・回数 ・経路は無い）。同じ端点の状態は記録を生まない ＝ 「端点が一致」であり「間に変化が無かった」ことの
証明ではない（`ENDPOINT_MATCH_IS_NOT_PROOF_OF_NO_CHANGE`）。view の identity ・規則の version が違う標本は比べない。
"""
from __future__ import annotations

from dataclasses import dataclass, fields
from enum import Enum
from typing import Any, Dict, Mapping, Optional, Tuple

from .canonical import (CanonicalError, assert_no_short_id_collision, canonical_json, domain_digest, is_digest, require_fields,
                        short_id)
from .review_state_sample import (STRUCTURAL_FIELDS, RecordKind, ReviewStateError, ReviewStateSample, SampleCutoff,
                                  SourceViewIdentity)

CHANGE_SCHEMA_VERSION = "p13_review_state_change:0.1.0"
CHANGE_DOMAIN = "p13.review_state_change.v1"
CHANGE_ID_PREFIX = "p13chg_"
INTERPRETATION = "ENDPOINT_DIFFERENCE_WITHIN_HALF_OPEN_INTERVAL_NOT_A_TRANSITION_TIME_NOT_A_TRANSITION_COUNT"
ENDPOINT_MATCH_IS_NOT_PROOF_OF_NO_CHANGE = "IDENTICAL_ENDPOINTS_YIELD_NO_RECORD_AND_DO_NOT_PROVE_ABSENCE_OF_INTERVENING_REVISIONS"
CanonicalScalar = Any   # str ・bool ・None（構造の欄の正準値）


class ChangeKind(str, Enum):
    APPEARED = "APPEARED"
    DISAPPEARED = "DISAPPEARED"
    CHANGED = "CHANGED"


def _require(condition: bool, code: str, detail: str = "") -> None:
    if not condition:
        raise ReviewStateError(code, detail)


def _scalar(value: Any, code: str) -> CanonicalScalar:
    _require(value is None or isinstance(value, (str, bool)), code, "FIELD_VALUE")
    return value


@dataclass(frozen=True, kw_only=True)
class ReviewStateChange:
    """(after_cutoff, through_cutoff] の区間での 1 record の端点の差。"""

    after_cutoff: SampleCutoff
    through_cutoff: SampleCutoff
    from_sample_digest: str
    to_sample_digest: str
    record_kind: RecordKind
    p9_root_id: str
    kind: ChangeKind
    changed_fields: Tuple[Tuple[str, CanonicalScalar, CanonicalScalar], ...]
    interpretation: str = INTERPRETATION
    schema_version: str = CHANGE_SCHEMA_VERSION

    def __post_init__(self) -> None:
        _require(isinstance(self.after_cutoff, SampleCutoff) and isinstance(self.through_cutoff, SampleCutoff), "CHANGE_INVALID", "CUTOFFS")
        _require(self.after_cutoff.at < self.through_cutoff.at, "CUTOFF_ORDER_INVALID", "INTERVAL")
        _require(is_digest(self.from_sample_digest) and is_digest(self.to_sample_digest), "CHANGE_INVALID", "SAMPLE_DIGESTS")
        _require(self.from_sample_digest != self.to_sample_digest, "CHANGE_INVALID", "SAME_SAMPLE")
        object.__setattr__(self, "record_kind", RecordKind(self.record_kind.value if isinstance(self.record_kind, Enum) else self.record_kind))
        object.__setattr__(self, "kind", ChangeKind(self.kind.value if isinstance(self.kind, Enum) else self.kind))
        _require(isinstance(self.p9_root_id, str) and self.p9_root_id != "", "CHANGE_INVALID", "ROOT_ID")
        _require(self.interpretation == INTERPRETATION and self.schema_version == CHANGE_SCHEMA_VERSION, "CHANGE_INVALID", "CLASS")
        _require(isinstance(self.changed_fields, tuple), "CHANGE_INVALID", "CHANGED_FIELDS")
        names = []
        for item in self.changed_fields:
            _require(isinstance(item, tuple) and len(item) == 3, "CHANGE_INVALID", "CHANGED_FIELD_SHAPE")
            name, before, after = item
            _require(name in STRUCTURAL_FIELDS, "CHANGE_INVALID", "NON_STRUCTURAL_FIELD")      # 文 ・時刻 ・telemetry の欄は無い
            _scalar(before, "CHANGE_INVALID")
            _scalar(after, "CHANGE_INVALID")
            _require(before != after, "CHANGE_INVALID", "NO_DIFFERENCE")
            names.append(name)
        _require(names == sorted(names) and len(set(names)) == len(names), "CHANGE_INVALID", "CHANGED_FIELD_ORDER")
        if self.kind is ChangeKind.CHANGED:
            _require(bool(self.changed_fields), "CHANGE_INVALID", "CHANGED_WITHOUT_FIELDS")
        else:
            _require(not self.changed_fields, "CHANGE_INVALID", "FIELDS_ON_APPEARANCE")

    def content(self) -> Dict[str, Any]:
        return {"schema_version": self.schema_version, "after_cutoff": self.after_cutoff.content(),
                "through_cutoff": self.through_cutoff.content(), "from_sample_digest": self.from_sample_digest,
                "to_sample_digest": self.to_sample_digest, "record_kind": self.record_kind.value, "p9_root_id": self.p9_root_id,
                "kind": self.kind.value, "changed_fields": [[n, b, a] for n, b, a in self.changed_fields],
                "interpretation": self.interpretation}

    @property
    def change_digest(self) -> str:
        return domain_digest(CHANGE_DOMAIN, self.content())

    @property
    def change_id(self) -> str:
        return short_id(CHANGE_ID_PREFIX, self.change_digest)

    def to_json(self) -> str:
        return canonical_json(self.content())

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "ReviewStateChange":
        fields_ = require_fields(data, frozenset(f.name for f in fields(cls)), "ReviewStateChange")
        return cls(after_cutoff=SampleCutoff.from_dict(fields_["after_cutoff"]), through_cutoff=SampleCutoff.from_dict(fields_["through_cutoff"]),
                   from_sample_digest=fields_["from_sample_digest"], to_sample_digest=fields_["to_sample_digest"],
                   record_kind=fields_["record_kind"], p9_root_id=fields_["p9_root_id"], kind=fields_["kind"],
                   changed_fields=tuple((n, b, a) for n, b, a in fields_["changed_fields"]),
                   interpretation=fields_["interpretation"], schema_version=fields_["schema_version"])


def check_comparable(earlier: ReviewStateSample, later: ReviewStateSample) -> None:
    """比べられる 2 標本か: 同じ view の identity ・同じ規則の version ・厳密に増加する `at`。満たさなければ比べない。"""
    _require(isinstance(earlier, ReviewStateSample) and isinstance(later, ReviewStateSample), "CHANGE_INVALID", "SAMPLES")
    _require(earlier.view_identity == later.view_identity, "VIEW_IDENTITY_MISMATCH")
    _require(earlier.rules_version == later.rules_version and earlier.schema_version == later.schema_version, "RULES_VERSION_MISMATCH")
    _require(earlier.cutoff.at < later.cutoff.at, "CUTOFF_ORDER_INVALID", "NOT_STRICTLY_INCREASING")
    assert_no_short_id_collision(((earlier.sample_id, earlier.sample_digest), (later.sample_id, later.sample_digest)))


def detect_changes(earlier: ReviewStateSample, later: ReviewStateSample) -> Tuple[ReviewStateChange, ...]:
    """端点の差だけ: APPEARED ／ DISAPPEARED ／ CHANGED。同じ状態の record は記録を生まない（変化の不在の証明ではない）。"""
    check_comparable(earlier, later)
    before = {e.key: e for e in earlier.entries}
    after = {e.key: e for e in later.entries}
    common = dict(after_cutoff=earlier.cutoff, through_cutoff=later.cutoff, from_sample_digest=earlier.sample_digest,
                  to_sample_digest=later.sample_digest)
    changes = []
    for key in sorted(set(before) | set(after)):
        kind_value, root_id = key
        if key not in before:
            changes.append(ReviewStateChange(record_kind=kind_value, p9_root_id=root_id, kind=ChangeKind.APPEARED, changed_fields=(), **common))
        elif key not in after:
            changes.append(ReviewStateChange(record_kind=kind_value, p9_root_id=root_id, kind=ChangeKind.DISAPPEARED, changed_fields=(), **common))
        else:
            old, new = before[key].structural_values(), after[key].structural_values()
            diff = tuple((name, old[name], new[name]) for name in sorted(STRUCTURAL_FIELDS) if old[name] != new[name])
            if diff:
                changes.append(ReviewStateChange(record_kind=kind_value, p9_root_id=root_id, kind=ChangeKind.CHANGED, changed_fields=diff, **common))
    result = tuple(changes)
    assert_no_short_id_collision((c.change_id, c.change_digest) for c in result)
    return result


def detect_changes_over(samples: Tuple[ReviewStateSample, ...]) -> Tuple[ReviewStateChange, ...]:
    """隣接する標本の組ごとの変化（標本は `at` で厳密に増加していること）。"""
    _require(isinstance(samples, tuple) and len(samples) >= 2, "CHANGE_INVALID", "NEED_TWO_SAMPLES")
    collected: list = []
    for earlier, later in zip(samples, samples[1:]):
        collected.extend(detect_changes(earlier, later))
    assert_no_short_id_collision((c.change_id, c.change_digest) for c in collected)
    return tuple(collected)


__all__ = ["CHANGE_DOMAIN", "CHANGE_ID_PREFIX", "CHANGE_SCHEMA_VERSION", "ChangeKind", "ENDPOINT_MATCH_IS_NOT_PROOF_OF_NO_CHANGE",
           "INTERPRETATION", "ReviewStateChange", "check_comparable", "detect_changes", "detect_changes_over"]
