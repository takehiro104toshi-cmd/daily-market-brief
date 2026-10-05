"""P8-B3 — 人が審査した Screener の方針の authority record（凍結 B1 `CriteriaPolicy` を包む最小の追記専用 record）。

答える問い: 「どの正確な方針を ・誰が ・いつ（明示の瞬間）・どの版 ・どの authority mode で審査したか」だけ。
最良の方針 ・最良の閾値 ・魅力 ・買い ・最適化 ・backtest ・P5 からの学習は答えない。record は人の決定を写すだけで、方針を作らない。

- record の identity は凍結 B1 の `CriteriaPolicy.policy_id`（内容 address）。第二の identity は作らない。
- 復元は凍結 B1 の constructor ・validator を通る（`Criterion.from_dict` → `CriteriaPolicy(...)`）。復元した `policy_id` ・
  各 `criterion_id` が保存された値と一致しなければ fail closed。文字列を信じない。
- authority の分類は `HUMAN_REVIEWED_SCREENING_POLICY` だけ: 「人がこの Screener の方針を明示に審査した」の意味。本番の投資の推奨 ・検証済みの
  alpha ・予測の規則 ・Compass DNA ・Theme ・watchlist ・thesis の authority ではない。
- 時計 ・既定の reviewed_at ・既定の path は無い（reviewed_at は B1 が aware を要求する）。
記録: `docs/databank/PHASE8_B3_PRIVATE_POLICY_AUTHORITY_STORE.md`。
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Dict, Mapping, Tuple

from ..core.time import from_iso
from .identity_model import canonical_json
from .screener_criteria_model import (POLICY_SCHEMA_VERSION, CriteriaComposition, CriteriaPolicy, Criterion,
                                      ScreenerAuthorityMode, ScreenerModelError)

POLICY_AUTHORITY_RECORD_KIND = "SCREENER_POLICY_AUTHORITY"
POLICY_AUTHORITY_SCHEMA_VERSION = "p8_screener_policy_authority:0.1.0"
POLICY_AUTHORITY_RULES_VERSION = "p8_screener_policy_authority:0.1.0"
#: 人が明示に審査した Screener の方針（それ以上の意味は無い）
HUMAN_REVIEWED_SCREENING_POLICY = "HUMAN_REVIEWED_SCREENING_POLICY"
#: この authority が意味しないもの（code ・文書 ・test で境界を固定する）
NOT_IMPLIED_BY_AUTHORITY: Tuple[str, ...] = ("PRODUCTION_INVESTMENT_RECOMMENDATION", "VALIDATED_ALPHA",
                                            "PROVEN_PREDICTIVE_RULE", "PRODUCTION_COMPASS_DNA", "THEME_AUTHORITY",
                                            "WATCHLIST_AUTHORITY", "THESIS_AUTHORITY")
#: 版の規則: 版は人の明示の label。append の順 ・reviewed_at の順 ・版の順は互いに保証しない。「現在の方針」の指し手は無い
VERSION_RULE = "EXPLICIT_HUMAN_LABEL_UNIQUE_PER_KEY_NO_SEQUENCE_NO_CURRENT"
_RECORD_FIELDS = frozenset(("record_kind", "schema_version", "rules_version", "authority_class", "policy"))


class PolicyAuthorityModelError(ValueError):
    def __init__(self, code: str, detail: str = "") -> None:
        super().__init__(f"{code}: {detail}" if detail else code)
        self.code = code
        self.detail = detail


def _require(condition: bool, code: str, detail: str = "") -> None:
    if not condition:
        raise PolicyAuthorityModelError(code, detail)


def policy_from_dict(data: Mapping[str, Any]) -> CriteriaPolicy:
    """保存された方針の dict → 凍結 B1 の `CriteriaPolicy`（constructor ・validator を通し、id を再計算して一致を要求する）。"""
    _require(isinstance(data, Mapping), "INVALID_RECORD", "policy")
    _require(data.get("schema_version") == POLICY_SCHEMA_VERSION, "SCHEMA_MISMATCH", "policy.schema_version")
    allowed = {"author_ref", "authority_mode", "composition", "criterion_ids", "criteria", "intent", "policy_id",
               "policy_key", "reviewed_at", "rules_version", "schema_version", "version"}
    _require(set(data) <= allowed, "UNKNOWN_FIELD", "policy")
    _require(all(key in data for key in allowed), "MISSING_FIELD", "policy")
    _require(isinstance(data["criteria"], list) and len(data["criteria"]) >= 1, "INVALID_RECORD", "policy.criteria")
    _require(all(isinstance(item, Mapping) and "criterion_id" in item for item in data["criteria"]), "MISSING_FIELD",
             "policy.criteria.criterion_id")                                        # 保存された id を B1 が検証する
    try:
        criteria = tuple(Criterion.from_dict(item) for item in data["criteria"])      # 凍結 B1 が criterion_id を検証する
        reviewed_at = from_iso(data["reviewed_at"]) if isinstance(data["reviewed_at"], str) else None
        _require(isinstance(reviewed_at, datetime), "INVALID_RECORD", "policy.reviewed_at")
        policy = CriteriaPolicy(policy_key=data["policy_key"], version=data["version"], author_ref=data["author_ref"],
                                reviewed_at=reviewed_at, intent=data["intent"], criteria=criteria,
                                authority_mode=ScreenerAuthorityMode(data["authority_mode"]),
                                composition=CriteriaComposition(data["composition"]),
                                rules_version=data["rules_version"])
    except ScreenerModelError as exc:
        raise PolicyAuthorityModelError("POLICY_INVALID", exc.code) from None
    except (TypeError, ValueError):
        raise PolicyAuthorityModelError("INVALID_RECORD", "policy") from None
    _require(policy.policy_id == data["policy_id"], "POLICY_ID_MISMATCH", "policy_id")
    _require([c.criterion_id for c in criteria] == list(data["criterion_ids"]), "CRITERION_IDS_MISMATCH",
             "criterion_ids")
    return policy


@dataclass(frozen=True, kw_only=True)
class PolicyAuthorityRecord:
    """1 つの人が審査した方針の authority record。identity は `policy.policy_id`。評価 ・順位 ・選択は無い。"""

    policy: CriteriaPolicy
    authority_class: str = HUMAN_REVIEWED_SCREENING_POLICY
    schema_version: str = POLICY_AUTHORITY_SCHEMA_VERSION
    rules_version: str = POLICY_AUTHORITY_RULES_VERSION

    def __post_init__(self) -> None:
        _require(isinstance(self.policy, CriteriaPolicy), "INVALID_POLICY", "policy")
        _require(self.authority_class == HUMAN_REVIEWED_SCREENING_POLICY, "AUTHORITY_CLASS_MISMATCH",
                 "authority_class")
        _require(self.schema_version == POLICY_AUTHORITY_SCHEMA_VERSION, "SCHEMA_MISMATCH", "schema_version")
        _require(self.rules_version == POLICY_AUTHORITY_RULES_VERSION, "RULES_VERSION_MISMATCH", "rules_version")

    @property
    def record_id(self) -> str:
        return self.policy.policy_id

    @property
    def policy_key(self) -> str:
        return self.policy.policy_key

    @property
    def version(self) -> int:
        return self.policy.version

    def as_dict(self) -> Dict[str, Any]:
        return {"authority_class": self.authority_class, "policy": self.policy.as_dict(),
                "record_kind": POLICY_AUTHORITY_RECORD_KIND, "rules_version": self.rules_version,
                "schema_version": self.schema_version}

    def canonical_line(self) -> str:
        return canonical_json(self.as_dict()) + "\n"

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "PolicyAuthorityRecord":
        _require(isinstance(data, Mapping), "INVALID_RECORD", "record")
        _require(set(data) == _RECORD_FIELDS, "UNKNOWN_FIELD" if set(data) - _RECORD_FIELDS else "MISSING_FIELD",
                 "record")
        _require(data["record_kind"] == POLICY_AUTHORITY_RECORD_KIND, "INVALID_RECORD", "record_kind")
        _require(data["schema_version"] == POLICY_AUTHORITY_SCHEMA_VERSION, "SCHEMA_MISMATCH", "schema_version")
        _require(data["rules_version"] == POLICY_AUTHORITY_RULES_VERSION, "RULES_VERSION_MISMATCH", "rules_version")
        _require(data["authority_class"] == HUMAN_REVIEWED_SCREENING_POLICY, "AUTHORITY_CLASS_MISMATCH",
                 "authority_class")
        return cls(policy=policy_from_dict(data["policy"]))


def is_policy_authority_record(value: Any) -> bool:
    return isinstance(value, PolicyAuthorityRecord)


@dataclass(frozen=True, kw_only=True)
class PolicyMetadata:
    """人が選ぶための metadata（閾値 ・基準の内容は含まない）。「現在」「既定」の意味は無い。"""

    policy_id: str
    policy_key: str
    version: int
    author_ref: str
    reviewed_at: datetime
    authority_mode: ScreenerAuthorityMode
    composition: CriteriaComposition
    criterion_count: int

    @classmethod
    def of(cls, record: PolicyAuthorityRecord) -> "PolicyMetadata":
        policy = record.policy
        return cls(policy_id=policy.policy_id, policy_key=policy.policy_key, version=policy.version,
                   author_ref=policy.author_ref, reviewed_at=policy.reviewed_at,
                   authority_mode=policy.authority_mode, composition=policy.composition,
                   criterion_count=len(policy.criteria))


__all__ = ["HUMAN_REVIEWED_SCREENING_POLICY", "NOT_IMPLIED_BY_AUTHORITY", "POLICY_AUTHORITY_RECORD_KIND",
           "POLICY_AUTHORITY_RULES_VERSION", "POLICY_AUTHORITY_SCHEMA_VERSION", "VERSION_RULE",
           "PolicyAuthorityModelError", "PolicyAuthorityRecord", "PolicyMetadata", "is_policy_authority_record",
           "policy_from_dict"]
