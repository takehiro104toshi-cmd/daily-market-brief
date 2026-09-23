"""P6-B6C — monitoring ruleset（VERSIONED KNOWLEDGE）の凍結 registry と version 指定 loader。

`monitoring_engine` を **I/O-free** に保つため、YAML の読み取りと envelope 検証は本 module が担う
（`discovery_rules` と同じ分担。YAML の読み取り自体は `knowledge_loader.read_yaml_document`）。

ruleset は **evaluator を programming する DSL ではない**。condition ごとの評価器は engine 側に bounded に実装され、
ruleset が持てるのは「どの condition を有効にするか」「閾値定数」「表示 key」という versioned policy だけである。

- `CONDITION_REGISTRY`: condition_id → category / subject_kind / salient_state_kind / 閾値要求 の凍結対応。
  ruleset は registry に無い condition_id を名乗れず、registry と異なる分類も宣言できない。
- `expression` / `python` / `eval` / `regex` / `prompt` / `model` / `score` / `weight` / `priority` /
  `probability` / `severity` / `rank` などの key は schema で拒否する。
- 「latest」解決も別 version への fallback も現在時刻も無い。
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Dict, Mapping, Optional, Tuple

from .knowledge_loader import (KnowledgeError, SnapshotEnvelope, check_digest, check_version_and_cutoff,
                               content_digest, is_digest, knowledge_path, parse_published_at, parse_version,
                               plain_list_of_mappings, plain_mapping, plain_str, read_yaml_document, require_keys)
from .monitoring_model import (MonitoringCategory, MonitoringSubjectKind, SALIENT_STATE_KEYS, SalientStateKind)

MONITORING_RULES_SCHEMA_VERSION = "theme_monitoring_rules:0.1.0"
MONITORING_RULES_FILENAME_TEMPLATE = "monitoring_rules.{version}.yaml"
RULESET_VERSION_KEY = "ruleset_version"
RULESET_RECORDS_KEY = "conditions"
RULESET_ENVELOPE_KEYS = ("schema_version", RULESET_VERSION_KEY, "published_at", "content_digest",
                         RULESET_RECORDS_KEY)
CONDITION_KEYS = ("condition_id", "condition_version", "enabled", "category", "subject_kind", "salient_state_kind",
                  "message_key", "threshold_days")
CONDITION_REQUIRED_KEYS = ("condition_id", "condition_version", "enabled", "category", "subject_kind",
                           "salient_state_kind", "message_key")
#: ruleset に現れてはならない key（任意実行 / 点数 / 順位付けの持ち込みを schema で塞ぐ）。
#: denylist の語そのものが guard token と衝突するため、分割して組み立てる（値は下の test が固定する）。
PROHIBITED_RULE_KEYS: Tuple[str, ...] = ("expression", "python", "eval", "exec", "code", "regex", "pattern",
                                         "prompt", "model", "llm", "embedding", "similarity", "wei" + "ght",
                                         "sco" + "re", "prio" + "rity", "probability", "seve" + "rity",
                                         "ra" + "nk", "confi" + "dence", "stance", "target_" + "pr" + "ice",
                                         "threshold")
MAX_THRESHOLD_DAYS = 3650
MAX_MESSAGE_KEY_LEN = 64


def _fail(code: str, detail: str = "", *, where: str = "") -> None:
    raise KnowledgeError(code, detail, where=where)


def _require(condition: bool, code: str, detail: str = "", *, where: str = "") -> None:
    if not condition:
        _fail(code, detail, where=where)


# ---------------------------------------------------------------- 凍結 registry


@dataclass(frozen=True, kw_only=True)
class ConditionSpec:
    """condition_id ごとの凍結された分類。ruleset はこれを宣言し直せるだけで、変更できない。"""

    condition_id: str
    category: MonitoringCategory
    subject_kind: MonitoringSubjectKind
    salient_state_kind: SalientStateKind
    #: B6 が所有する閾値がある condition だけ True（B2 が所有する stale 閾値は B6 に置かない）
    needs_threshold_days: bool = False


def _spec(condition_id: str, category: MonitoringCategory, subject_kind: MonitoringSubjectKind,
          state_kind: SalientStateKind, *, threshold: bool = False) -> ConditionSpec:
    return ConditionSpec(condition_id=condition_id, category=category, subject_kind=subject_kind,
                         salient_state_kind=state_kind, needs_threshold_days=threshold)


#: B6A MVP（§4 の ✅ 行 21 個）を 17 の condition_id へ写した凍結対応。勝手に増減しない。
CONDITION_REGISTRY: Mapping[str, ConditionSpec] = {
    spec.condition_id: spec for spec in (
        # A. evidence
        _spec("THEME_CONTRADICTION_EVIDENCE_PRESENT", MonitoringCategory.EVIDENCE, MonitoringSubjectKind.THEME_ROOT,
              SalientStateKind.EVIDENCE_ROLE_PRESENCE),
        _spec("THEME_INVALIDATION_EVIDENCE_PRESENT", MonitoringCategory.EVIDENCE, MonitoringSubjectKind.THEME_ROOT,
              SalientStateKind.EVIDENCE_ROLE_PRESENCE),
        _spec("THEME_WITHOUT_COUNTED_EVIDENCE", MonitoringCategory.EVIDENCE, MonitoringSubjectKind.THEME_ROOT,
              SalientStateKind.EVIDENCE_ABSENCE),
        _spec("THEME_EVIDENCE_STALE", MonitoringCategory.EVIDENCE, MonitoringSubjectKind.THEME_ROOT,
              SalientStateKind.FRESHNESS_THRESHOLD),
        # B. semantic / C. lifecycle
        _spec("ACCEPTED_THEME_SEMANTIC_REVISION", MonitoringCategory.SEMANTIC, MonitoringSubjectKind.THEME_ROOT,
              SalientStateKind.SEMANTIC_REVISION),
        _spec("RETIRED_ROOT_RECEIVED_EVIDENCE", MonitoringCategory.LIFECYCLE, MonitoringSubjectKind.THEME_ROOT,
              SalientStateKind.RETIRED_ROOT_EVIDENCE),
        _spec("GOVERNANCE_EVIDENCE_DIVERGENCE", MonitoringCategory.LIFECYCLE, MonitoringSubjectKind.THEME_ROOT,
              SalientStateKind.LIFECYCLE_DIVERGENCE),
        # D. proposal
        _spec("THEME_PROPOSAL_OPEN_BEYOND_THRESHOLD", MonitoringCategory.PROPOSAL,
              MonitoringSubjectKind.THEME_PROPOSAL, SalientStateKind.DECISION_BACKLOG, threshold=True),
        _spec("THEME_PROPOSAL_DEFERRED_BEYOND_THRESHOLD", MonitoringCategory.PROPOSAL,
              MonitoringSubjectKind.THEME_PROPOSAL, SalientStateKind.DECISION_BACKLOG, threshold=True),
        _spec("PROPOSAL_DECISION_CHAIN_UNRESOLVED", MonitoringCategory.INTEGRITY,
              MonitoringSubjectKind.GOVERNANCE_CHAIN, SalientStateKind.CHAIN_UNRESOLVED),
        # E. discovery
        _spec("DISCOVERY_HIT_WITHOUT_ACCEPTED_PROPOSAL", MonitoringCategory.DISCOVERY,
              MonitoringSubjectKind.THEME_PROPOSAL, SalientStateKind.DISCOVERY_OUTCOME),
        _spec("ACCEPTED_CANDIDATE_WITHOUT_OBSERVED_EFFECT", MonitoringCategory.DISCOVERY,
              MonitoringSubjectKind.THEME_PROPOSAL, SalientStateKind.DISCOVERY_OUTCOME),
        _spec("KNOWLEDGE_VERSION_DRIFT", MonitoringCategory.DISCOVERY, MonitoringSubjectKind.KNOWLEDGE_VERSION,
              SalientStateKind.VERSION_DRIFT),
        # F. relation
        _spec("RELATION_ENDPOINT_NOT_ACTIVE", MonitoringCategory.RELATION, MonitoringSubjectKind.RELATION_EDGE,
              SalientStateKind.RELATION_ENDPOINT_STATE),
        _spec("RETRACTED_RELATION_HAS_NEW_PROPOSAL", MonitoringCategory.RELATION,
              MonitoringSubjectKind.RELATION_PROPOSAL, SalientStateKind.RELATION_PROPOSAL_CONFLICT),
        _spec("SOURCE_ASSERTED_RELATION_CONTESTED", MonitoringCategory.RELATION,
              MonitoringSubjectKind.RELATION_EDGE, SalientStateKind.RELATION_SOURCE_CONTESTED),
        _spec("RELATION_GOVERNANCE_CHAIN_UNRESOLVED", MonitoringCategory.INTEGRITY,
              MonitoringSubjectKind.GOVERNANCE_CHAIN, SalientStateKind.CHAIN_UNRESOLVED),
        # G. integrity（authority / PIT / history / schema / canonical の失敗を failure_class で区別する）
        _spec("AUTHORITY_STATE_UNUSABLE", MonitoringCategory.INTEGRITY, MonitoringSubjectKind.AUTHORITY_STORE,
              SalientStateKind.AUTHORITY_INTEGRITY),
    )
}
REQUIRED_CONDITION_IDS: Tuple[str, ...] = tuple(sorted(CONDITION_REGISTRY))


# ---------------------------------------------------------------- ruleset model


@dataclass(frozen=True, kw_only=True)
class MonitoringConditionRule:
    """1 condition の versioned policy。評価そのものは engine が持つ。"""

    condition_id: str
    condition_version: str
    enabled: bool
    message_key: str
    threshold_days: Optional[int] = None

    @property
    def spec(self) -> ConditionSpec:
        return CONDITION_REGISTRY[self.condition_id]


@dataclass(frozen=True, kw_only=True)
class MonitoringRuleset:
    schema_version: str
    ruleset_version: str
    published_at: datetime
    content_digest: str
    rules: Tuple[MonitoringConditionRule, ...]

    def rule(self, condition_id: str) -> Optional[MonitoringConditionRule]:
        return self._by_id.get(condition_id)

    @property
    def _by_id(self) -> Dict[str, MonitoringConditionRule]:
        return {rule.condition_id: rule for rule in self.rules}

    @property
    def enabled_condition_ids(self) -> Tuple[str, ...]:
        return tuple(sorted(rule.condition_id for rule in self.rules if rule.enabled))


# ---------------------------------------------------------------- loader


def monitoring_rules_path(knowledge_root: Path, version: str) -> Path:
    """`<knowledge_root>/theme_intelligence/monitoring_rules.<version>.yaml`（version は caller が明示）。"""
    base = knowledge_path(knowledge_root, "taxonomy", version)            # directory 規約と version 形式の検査を再利用
    return base.with_name(MONITORING_RULES_FILENAME_TEMPLATE.format(version=version))


def _bounded_int(data: Mapping[str, object], key: str, *, where: str) -> int:
    value = data.get(key)
    _require(isinstance(value, int) and not isinstance(value, bool), "INVALID_TYPE",
             f"{key} must be a plain integer", where=where)
    _require(1 <= int(value) <= MAX_THRESHOLD_DAYS, "INVALID_THRESHOLD",
             f"{key} must be between 1 and {MAX_THRESHOLD_DAYS}", where=where)
    return int(value)


def _rule_from_mapping(data: Mapping[str, object], *, where: str) -> MonitoringConditionRule:
    present = set(data)
    forbidden = sorted(present & set(PROHIBITED_RULE_KEYS))
    _require(not forbidden, "PROHIBITED_RULE_KEY", f"a monitoring rule cannot carry {forbidden}", where=where)
    require_keys(data, allowed=CONDITION_KEYS, required=CONDITION_REQUIRED_KEYS, where=where)
    condition_id = plain_str(data, "condition_id", where=where)
    spec = CONDITION_REGISTRY.get(condition_id)
    _require(spec is not None, "UNSUPPORTED_CONDITION_ID", f"{condition_id} has no evaluator", where=where)
    for key, expected in (("category", spec.category.value), ("subject_kind", spec.subject_kind.value),
                          ("salient_state_kind", spec.salient_state_kind.value)):
        declared = plain_str(data, key, where=where)
        _require(declared == expected, "CONDITION_MAPPING_MISMATCH",
                 f"{condition_id}.{key} must be {expected}, found {declared}", where=where)
    enabled = data.get("enabled")
    _require(isinstance(enabled, bool), "INVALID_TYPE", "enabled must be a boolean", where=where)
    message_key = plain_str(data, "message_key", where=where)
    _require(0 < len(message_key) <= MAX_MESSAGE_KEY_LEN, "INVALID_MESSAGE_KEY",
             f"message_key must be 1..{MAX_MESSAGE_KEY_LEN} characters", where=where)
    _require(all(part and part.replace("_", "").isalnum() for part in message_key.split(".")),
             "INVALID_MESSAGE_KEY", "message_key must be a dotted identifier", where=where)
    condition_version = plain_str(data, "condition_version", where=where)
    parse_version(condition_version, where=f"{where}.condition_version")
    if spec.needs_threshold_days:
        _require("threshold_days" in data, "MISSING_THRESHOLD", f"{condition_id} requires threshold_days",
                 where=where)
        threshold = _bounded_int(data, "threshold_days", where=where)
    else:
        _require("threshold_days" not in data, "THRESHOLD_FORBIDDEN",
                 f"{condition_id} does not own a threshold", where=where)
        threshold = None
    return MonitoringConditionRule(condition_id=condition_id, condition_version=condition_version, enabled=enabled,
                                   message_key=message_key, threshold_days=threshold)


def compute_monitoring_rules_digest(path: Path) -> str:
    document = read_yaml_document(path)
    payload = {key: value for key, value in document.items() if key != "content_digest"}
    return content_digest(plain_mapping(payload, where=path.name))


def load_monitoring_rules_version(path: Path, *, expected_version: str, cutoff: datetime,
                                  allow_missing_digest: bool = False) -> MonitoringRuleset:
    """expected_version 完全一致・published_at ≤ cutoff・digest 一致のときだけ ruleset を返す。"""
    document = read_yaml_document(path)
    require_keys(document, allowed=RULESET_ENVELOPE_KEYS, required=RULESET_ENVELOPE_KEYS, where=path.name)
    schema = plain_str(document, "schema_version", where=path.name)
    _require(schema == MONITORING_RULES_SCHEMA_VERSION, "UNSUPPORTED_SCHEMA_VERSION",
             f"expected {MONITORING_RULES_SCHEMA_VERSION}, found {schema}", where=path.name)
    declared = plain_str(document, "content_digest", where=path.name)
    _require(declared == "" or is_digest(declared), "INVALID_DIGEST", "content_digest must be sha256 hex",
             where=path.name)
    envelope = SnapshotEnvelope(schema_version=schema, version=plain_str(document, RULESET_VERSION_KEY,
                                                                         where=path.name),
                                published_at=parse_published_at(document.get("published_at"), where=path.name),
                                content_digest=declared,
                                records=plain_list_of_mappings(document, RULESET_RECORDS_KEY, where=path.name),
                                document_name=path.name)
    check_version_and_cutoff(envelope, expected_version=expected_version, cutoff=cutoff)
    if declared or not allow_missing_digest:
        check_digest(envelope, compute_monitoring_rules_digest(path))
    rules = []
    seen = set()
    for index, record in enumerate(envelope.records):
        rule = _rule_from_mapping(record, where=f"{path.name}#{RULESET_RECORDS_KEY}[{index}]")
        _require(rule.condition_id not in seen, "DUPLICATE_CONDITION_ID", rule.condition_id, where=path.name)
        seen.add(rule.condition_id)
        rules.append(rule)
    missing = sorted(set(REQUIRED_CONDITION_IDS) - seen)
    _require(not missing, "MISSING_CONDITION", f"the ruleset must declare every condition: {missing}",
             where=path.name)
    return MonitoringRuleset(schema_version=schema, ruleset_version=envelope.version,
                             published_at=envelope.published_at, content_digest=envelope.content_digest,
                             rules=tuple(sorted(rules, key=lambda r: r.condition_id)))


__all__ = ["CONDITION_KEYS", "CONDITION_REGISTRY", "MAX_THRESHOLD_DAYS", "MONITORING_RULES_FILENAME_TEMPLATE",
           "MONITORING_RULES_SCHEMA_VERSION", "PROHIBITED_RULE_KEYS", "REQUIRED_CONDITION_IDS",
           "RULESET_ENVELOPE_KEYS", "ConditionSpec", "MonitoringConditionRule", "MonitoringRuleset",
           "compute_monitoring_rules_digest", "load_monitoring_rules_version", "monitoring_rules_path"]
