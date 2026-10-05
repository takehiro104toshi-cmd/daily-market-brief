"""P8-A2C-R — `ProviderHoldingsCoverage`: bounded な provider の保持 epoch の authority（C1。監督の決定）。

- 何か: 「主語 S について、period_end P の canonical の行を 1 つ以上含む COMPLETE な provider の取得（epoch）を、system が `holdings_as_of`
  の瞬間に保持した」という record。RETROSPECTIVE_PROVIDER_AUTHORITY の epoch の選択の**唯一の源**。
- 何ではないか: 世界 ／ 公開の知識の完全性（A2 `ObservationCoverage` ・`complete_through`）ではない。`ObservationHistory.coverages` ・
  STRICT の `_coverage` ・`COVERAGE_CONTRADICTION` ・A3 には決して入らない。`complete_through` ・世界の知識の境界 ・値 ・名前 ・raw の行 ・
  credential ・HTTP の metadata を持たない。
- 2 つの軸: `period_end` は世界 ／ 会計の期間の日（G3: 1 日。`covers(day)` は `day == period_end` だけ）。`holdings_as_of` は取得 event の
  `acquired_at` そのもの（system の瞬間。aware。UTC で直列化）。混ぜない。時計は読まない。
- 結び付き: `acquisition_ref`（`jq.acq:`）と `manifest_ref`（`jq.man:`）。membership の authority は manifest（EPOCH1 ／ EPOCH1R）で、
  本 record は epoch の選択と結び付きの検査だけ。`canonical_entry_count` は manifest のその period_end の CANONICAL の entry の数
  （整合の metadata。それ自体は証拠にしない）。
- identity: 内容 address `p8pvh_<24 hex>`。参照 `jq.pvh:<24 hex>`。全欄が identity に入る（主語 ・period_end ・holdings_as_of ・取得 ・
  manifest のどれが違っても別の record）。

記録: `docs/databank/PHASE8_A2C_R_PROVIDER_HOLDINGS_AUTHORITY.md`。
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any, Dict, Iterable, Mapping

from .identity_model import CREDENTIAL_MARKERS, canonical_json, is_issuer_id
from .observation_model import CoverageDataset
from ..core.ids import content_id
from ..core.time import from_iso, to_utc_iso

HOLDINGS_SCHEMA_VERSION = "p8_provider_holdings_coverage:0.1.0"
HOLDINGS_RULES_VERSION = "p8_provider_holdings_authority:0.1.0"
HOLDINGS_RECORD_KIND = "PROVIDER_HOLDINGS_COVERAGE"
HOLDINGS_ID_PREFIX = "p8pvh"
REFERENCE_PREFIX = "jq.pvh:"
#: provider の保持 epoch の authority（世界の完全性 ・観測 ・取得 ・membership の authority ではない）
PROVIDER_HOLDINGS_RECORD = "PROVIDER_HOLDINGS_EPOCH_RECORD"
#: G3: period_end 1 日だけを覆う（区間の推定はしない）
COVERAGE_RULE = "EXACT_PERIOD_END"
_ACQ_REF_RE = re.compile(r"^jq\.acq:[0-9a-f]{24}$")
_MAN_REF_RE = re.compile(r"^jq\.man:[0-9a-f]{24}$")
_PVH_REF_RE = re.compile(r"^jq\.pvh:[0-9a-f]{24}$")
_RULE_VERSION_RE = re.compile(r"^[a-z][a-z0-9_]{0,63}:[0-9]+\.[0-9]+\.[0-9]+$")
_MAX_COUNT = 100_000


class HoldingsModelError(ValueError):
    """record の構造 ・語彙 ・値の違反（fail closed）。detail は field 名だけ。"""

    def __init__(self, code: str, detail: str = "") -> None:
        super().__init__(f"{code}: {detail}" if detail else code)
        self.code = code
        self.detail = detail


def _require(condition: bool, code: str, detail: str = "") -> None:
    if not condition:
        raise HoldingsModelError(code, detail)


def _text(value: Any, pattern: "re.Pattern[str]", code: str, field_name: str) -> str:
    _require(isinstance(value, str) and bool(pattern.match(value)), code, field_name)
    lowered = value.lower()
    _require(not any(marker in lowered for marker in CREDENTIAL_MARKERS), "CREDENTIAL_LIKE_TEXT", field_name)
    return value


def _reject_unknown(data: Mapping[str, Any], allowed: Iterable[str], name: str) -> None:
    _require(isinstance(data, Mapping), "INVALID_RECORD", name)
    _require(set(data) <= set(allowed), "UNKNOWN_FIELD", name)
    _require(set(allowed) <= set(data), "MISSING_FIELD", name)


@dataclass(frozen=True, kw_only=True)
class ProviderHoldingsCoverage:
    """1 つの取得 epoch ・1 つの period_end の保持の record（不変 ・内容 address）。"""

    KIND = HOLDINGS_RECORD_KIND
    AUTHORITY_CLASS = PROVIDER_HOLDINGS_RECORD
    dataset: CoverageDataset
    subject_id: str
    period_end: date
    holdings_as_of: datetime
    acquisition_ref: str
    manifest_ref: str
    canonical_entry_count: int
    rules_version: str = HOLDINGS_RULES_VERSION

    def __post_init__(self) -> None:
        _require(isinstance(self.dataset, CoverageDataset), "INVALID_VOCABULARY", "dataset")
        _require(self.dataset is CoverageDataset.FUNDAMENTAL_DISCLOSURE, "DATASET_NOT_ALLOWED", "dataset")
        _require(is_issuer_id(self.subject_id), "INVALID_SUBJECT", "subject_id")
        _require(type(self.period_end) is date, "INVALID_DATE", "period_end")
        _require(isinstance(self.holdings_as_of, datetime) and self.holdings_as_of.tzinfo is not None
                 and self.holdings_as_of.tzinfo.utcoffset(self.holdings_as_of) is not None, "NAIVE_DATETIME",
                 "holdings_as_of")
        _text(self.acquisition_ref, _ACQ_REF_RE, "INVALID_ACQUISITION_REF", "acquisition_ref")
        _text(self.manifest_ref, _MAN_REF_RE, "INVALID_MANIFEST_REF", "manifest_ref")
        _require(type(self.canonical_entry_count) is int and 1 <= self.canonical_entry_count <= _MAX_COUNT,
                 "INVALID_COUNT", "canonical_entry_count")
        _text(self.rules_version, _RULE_VERSION_RE, "INVALID_RULE_VERSION", "rules_version")

    def covers(self, day: date) -> bool:
        """G3: ちょうど period_end の日だけ（区間の推定はしない）。"""
        return day == self.period_end

    def identity_payload(self) -> Dict[str, Any]:
        return {"acquisition_ref": self.acquisition_ref, "canonical_entry_count": self.canonical_entry_count,
                "coverage_rule": COVERAGE_RULE, "dataset": self.dataset.value,
                "holdings_as_of": to_utc_iso(self.holdings_as_of), "manifest_ref": self.manifest_ref,
                "period_end": self.period_end.isoformat(), "record_kind": HOLDINGS_RECORD_KIND,
                "rules_version": self.rules_version, "schema_version": HOLDINGS_SCHEMA_VERSION,
                "subject_id": self.subject_id}

    @property
    def record_id(self) -> str:
        return content_id(HOLDINGS_ID_PREFIX, canonical_json(self.identity_payload()))

    @property
    def reference(self) -> str:
        return holdings_reference(self.record_id)

    def as_dict(self) -> Dict[str, Any]:
        return {**self.identity_payload(), "record_id": self.record_id}

    def canonical_line(self) -> str:
        return canonical_json(self.as_dict()) + "\n"

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "ProviderHoldingsCoverage":
        _reject_unknown(data, ("acquisition_ref", "canonical_entry_count", "coverage_rule", "dataset", "holdings_as_of",
                               "manifest_ref", "period_end", "record_id", "record_kind", "rules_version",
                               "schema_version", "subject_id"), "record")
        _require(data["schema_version"] == HOLDINGS_SCHEMA_VERSION, "SCHEMA_MISMATCH", "schema_version")
        _require(data["record_kind"] == HOLDINGS_RECORD_KIND, "KIND_MISMATCH", "record_kind")
        _require(data["coverage_rule"] == COVERAGE_RULE, "COVERAGE_RULE_MISMATCH", "coverage_rule")
        try:
            dataset = CoverageDataset(data["dataset"])
        except ValueError:
            raise HoldingsModelError("INVALID_VOCABULARY", "dataset") from None
        _require(isinstance(data["period_end"], str) and isinstance(data["holdings_as_of"], str), "INVALID_DATE",
                 "period_end")
        try:
            period_end = date.fromisoformat(data["period_end"])
            holdings_as_of = from_iso(data["holdings_as_of"])
        except ValueError:
            raise HoldingsModelError("INVALID_DATE", "period_end") from None
        _require(period_end.isoformat() == data["period_end"], "INVALID_DATE", "period_end")
        record = cls(dataset=dataset, subject_id=data["subject_id"], period_end=period_end,
                     holdings_as_of=holdings_as_of, acquisition_ref=data["acquisition_ref"],
                     manifest_ref=data["manifest_ref"], canonical_entry_count=data["canonical_entry_count"],
                     rules_version=data["rules_version"])
        _require(record.record_id == data["record_id"], "RECORD_ID_MISMATCH", "record_id")
        return record


def holdings_reference(record_id: Any) -> str:
    _require(isinstance(record_id, str) and record_id.startswith(HOLDINGS_ID_PREFIX + "_")
             and len(record_id) == len(HOLDINGS_ID_PREFIX) + 25, "INVALID_RECORD_ID", "record_id")
    return REFERENCE_PREFIX + record_id[len(HOLDINGS_ID_PREFIX) + 1:]


def is_holdings_reference(value: Any) -> bool:
    return isinstance(value, str) and bool(_PVH_REF_RE.match(value))


def is_provider_holdings_coverage(value: Any) -> bool:
    return isinstance(value, ProviderHoldingsCoverage)


__all__ = ["COVERAGE_RULE", "HOLDINGS_ID_PREFIX", "HOLDINGS_RECORD_KIND", "HOLDINGS_RULES_VERSION",
           "HOLDINGS_SCHEMA_VERSION", "PROVIDER_HOLDINGS_RECORD", "REFERENCE_PREFIX", "HoldingsModelError",
           "ProviderHoldingsCoverage", "holdings_reference", "is_holdings_reference", "is_provider_holdings_coverage"]
