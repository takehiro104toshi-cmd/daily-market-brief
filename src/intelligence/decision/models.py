"""Decision record / evidence snapshot（Phase 3.9.1）— schema-versioned, strongly validated, deterministic。

record は append-only store の 1 行。persist 後に編集しない。source PDF text は決して入れない
（evidence は id / count / label / version だけ）。
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field, fields
from typing import Any, Dict, List, Mapping, Optional, Tuple

from .policy import DECISION_STATES

SCHEMA_VERSION = "1.0.0"
EVIDENCE_SCHEMA_VERSION = "1.0.0"

ACTOR_HUMAN = "HUMAN"
ACTOR_SYSTEM = "SYSTEM"
ACTOR_TYPES: Tuple[str, ...] = (ACTOR_HUMAN, ACTOR_SYSTEM)

MODE_SHADOW = "SHADOW"          # corpus < formal_review_min_corpus: formal APPROVED 不可
MODE_FORMAL = "FORMAL"          # corpus >= formal_review_min_corpus: human APPROVED が技術的に可能
REVIEW_MODES: Tuple[str, ...] = (MODE_SHADOW, MODE_FORMAL)

#: promotion は decision とは別次元。3.9.1 が生成できるのは NOT_PROMOTED のみ（promotion 実装なし）。
NOT_PROMOTED = "NOT_PROMOTED"
DNA_CANDIDATE = "DNA_CANDIDATE"
PROMOTED_TO_DNA = "PROMOTED_TO_DNA"
PROMOTION_STATUSES: Tuple[str, ...] = (NOT_PROMOTED, DNA_CANDIDATE, PROMOTED_TO_DNA)
PHASE_3_9_1_PROMOTION_STATUSES: Tuple[str, ...] = (NOT_PROMOTED,)

MAX_REASON_CHARS = 2000
MAX_NOTES_CHARS = 2000
MAX_METADATA_KEYS = 20
MAX_METADATA_VALUE_CHARS = 500
MAX_SUPPORTING_DOC_IDS = 20
FORBIDDEN_EVIDENCE_KEYS = ("text", "source_text", "page_text", "body", "raw", "statement")


def canonical_json(obj: Any) -> str:
    return json.dumps(obj, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)


def sha256_hex(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


# ------------------------------------------------------------------ evidence snapshot
@dataclass(frozen=True)
class EvidenceSnapshot:
    """decision 時点の evidence（compact・deterministic・no text）。"""
    pattern_id: str
    pattern_found: bool
    pattern_type: str = ""
    pattern_status: str = ""                  # Phase 3.8 research status（decision state とは別概念）
    pattern_record_id: str = ""
    support_count: Optional[int] = None
    eligible_support: Optional[int] = None
    regime_count: Optional[int] = None
    span_days: Optional[int] = None
    date_range: Tuple[str, str] = ("", "")
    valid_ratio: str = ""
    evidence_categories: Tuple[str, ...] = ()
    theme: str = ""
    outlook: Tuple[str, ...] = ()
    risk: str = ""
    supporting_document_count: int = 0
    supporting_document_ids: Tuple[str, ...] = ()   # 先頭 MAX_SUPPORTING_DOC_IDS 件（hash id のみ）
    evidence_reference_count: int = 0
    dna_classification: str = ""
    dna_best_rule_id: str = ""
    conflict_count: int = 0
    conflict_rule_ids: Tuple[str, ...] = ()
    limitations: Tuple[str, ...] = ()
    research_snapshot_id: str = ""
    research_generated_at: str = ""
    analyzer_versions: Mapping[str, str] = field(default_factory=dict)
    research_corpus_count: Optional[int] = None
    research_eligible_count: Optional[int] = None
    evidence_schema_version: str = EVIDENCE_SCHEMA_VERSION

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
    def from_dict(cls, data: Mapping[str, Any]) -> "EvidenceSnapshot":
        d = dict(data)
        kw: Dict[str, Any] = {}
        for f in fields(cls):
            if f.name not in d:
                continue
            v = d[f.name]
            if f.name == "date_range":
                v = tuple(str(x) for x in (v or ["", ""]))[:2]
                v = (v + ("", ""))[:2]
            elif f.name in ("evidence_categories", "outlook", "supporting_document_ids", "conflict_rule_ids", "limitations"):
                v = tuple(str(x) for x in (v or []))
            elif f.name == "analyzer_versions":
                v = {str(k): str(x) for k, x in dict(v or {}).items()}
            kw[f.name] = v
        return cls(**kw)

    def digest(self) -> str:
        return sha256_hex(canonical_json(self.as_dict()))[:16]


# ------------------------------------------------------------------ decision record
@dataclass(frozen=True)
class DecisionRecord:
    decision_id: str
    pattern_id: str
    decision_type: str
    reason: str
    actor: str
    actor_type: str
    decided_at: str                            # ISO-8601 UTC（id には含めない）
    policy_version: str
    policy_digest: str
    review_mode: str                           # SHADOW / FORMAL（decision 時点）
    corpus_size: int                           # eligible_for_pattern_evidence（canonical metric）
    corpus_documents: int
    corpus_usable: int
    corpus_milestone: str
    previous_state: str                        # "" = 履歴なし
    previous_decision_id: str
    evidence: Mapping[str, Any]                # EvidenceSnapshot.as_dict()
    evidence_digest: str
    supersedes_decision_id: str = ""
    reopens_decision_id: str = ""
    promotion_status: str = NOT_PROMOTED
    notes: str = ""
    metadata: Mapping[str, str] = field(default_factory=dict)
    idempotency_key: str = ""
    schema_version: str = SCHEMA_VERSION
    sequence: int = 0                          # store が append 時に付与（1 始まり・連番）
    previous_record_hash: str = ""             # 直前 row の record_hash（chain）
    record_hash: str = ""                      # 本 row の hash（record_hash を除く全 field）

    def as_dict(self) -> Dict[str, Any]:
        out: Dict[str, Any] = {}
        for f in fields(self):
            v = getattr(self, f.name)
            if isinstance(v, Mapping):
                v = dict(v)
            out[f.name] = v
        return out

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "DecisionRecord":
        names = {f.name for f in fields(cls)}
        kw = {k: v for k, v in dict(data).items() if k in names}
        kw["evidence"] = dict(kw.get("evidence") or {})
        kw["metadata"] = {str(k): str(v) for k, v in dict(kw.get("metadata") or {}).items()}
        return cls(**kw)


def decision_id_for(*, pattern_id: str, decision_type: str, reason: str, actor: str, actor_type: str,
                    policy_version: str, previous_decision_id: str, idempotency_key: str = "",
                    schema_version: str = SCHEMA_VERSION) -> str:
    """deterministic id。timestamp を含めない → 同じ head に対する同一内容の retry は同じ id（store が重複 append を拒否）。
    head（previous_decision_id）が変われば同一内容でも別 id（後日の同じ判断は別 event として残る）。"""
    seed = canonical_json({"pattern_id": pattern_id, "decision_type": decision_type, "reason": reason.strip(),
                           "actor": actor.strip(), "actor_type": actor_type, "policy_version": policy_version,
                           "previous_decision_id": previous_decision_id, "idempotency_key": idempotency_key,
                           "schema_version": schema_version})
    return "cdc_" + sha256_hex(seed)[:16]


def record_hash_for(row: Mapping[str, Any]) -> str:
    body = {k: v for k, v in dict(row).items() if k != "record_hash"}
    return sha256_hex(canonical_json(body))


def _is_int(v: Any) -> bool:
    return isinstance(v, int) and not isinstance(v, bool)


def validate_evidence(ev: Mapping[str, Any]) -> List[str]:
    errors: List[str] = []
    if not isinstance(ev, Mapping):
        return ["EVIDENCE_NOT_OBJECT"]
    for key in FORBIDDEN_EVIDENCE_KEYS:
        if key in ev:
            errors.append(f"EVIDENCE_FORBIDDEN_KEY:{key}")
    if str(ev.get("evidence_schema_version", "")) != EVIDENCE_SCHEMA_VERSION:
        errors.append("EVIDENCE_SCHEMA_VERSION_MISMATCH")
    if not str(ev.get("pattern_id", "")):
        errors.append("EVIDENCE_PATTERN_ID_MISSING")
    if not isinstance(ev.get("pattern_found"), bool):
        errors.append("EVIDENCE_PATTERN_FOUND_NOT_BOOL")
    return errors


def validate_record(row: Mapping[str, Any], *, allow_unsealed: bool = False) -> List[str]:
    """schema-level validation（error code の list。空 = valid）。allow_unsealed: sequence / hash 付与前の proposed row。"""
    errors: List[str] = []
    if not isinstance(row, Mapping):
        return ["RECORD_NOT_OBJECT"]
    required = {f.name for f in fields(DecisionRecord)}
    missing = sorted(required - set(row.keys()))
    if missing:
        errors.append("MISSING_FIELDS:" + ",".join(missing))
        return errors
    if str(row["schema_version"]) != SCHEMA_VERSION:
        errors.append("SCHEMA_VERSION_MISMATCH")
    if not str(row["decision_id"]).startswith("cdc_") or len(str(row["decision_id"])) != 20:
        errors.append("DECISION_ID_FORMAT")
    if not str(row["pattern_id"]).strip():
        errors.append("PATTERN_ID_MISSING")
    if row["decision_type"] not in DECISION_STATES:
        errors.append("DECISION_TYPE_UNKNOWN")
    if not isinstance(row["reason"], str) or len(row["reason"]) > MAX_REASON_CHARS:
        errors.append("REASON_INVALID")
    elif not row["reason"].strip():
        errors.append("REASON_EMPTY")                      # schema 1.0.0: 全 decision に非空 reason（policy v1 と同じ保守性）
    if not str(row["actor"]).strip():
        errors.append("ACTOR_MISSING")
    if row["actor_type"] not in ACTOR_TYPES:
        errors.append("ACTOR_TYPE_UNKNOWN")
    elif row["actor_type"] != ACTOR_HUMAN:
        errors.append("ACTOR_TYPE_NOT_HUMAN_IN_3_9_1")     # schema 1.0.0: SYSTEM 発の decision row は store にも入らない
    if not str(row["decided_at"]).strip():
        errors.append("DECIDED_AT_MISSING")
    if not str(row["policy_version"]).strip() or not str(row["policy_digest"]).strip():
        errors.append("POLICY_VERSION_MISSING")
    if row["review_mode"] not in REVIEW_MODES:
        errors.append("REVIEW_MODE_UNKNOWN")
    for key in ("corpus_size", "corpus_documents", "corpus_usable"):
        if not _is_int(row[key]) or row[key] < 0:
            errors.append(f"{key.upper()}_INVALID")
    if row["previous_state"] not in ("",) + DECISION_STATES:
        errors.append("PREVIOUS_STATE_UNKNOWN")
    if row["promotion_status"] not in PHASE_3_9_1_PROMOTION_STATUSES:
        errors.append("PROMOTION_STATUS_NOT_ALLOWED_IN_3_9_1")
    if not isinstance(row["notes"], str) or len(row["notes"]) > MAX_NOTES_CHARS:
        errors.append("NOTES_INVALID")
    md = row["metadata"]
    if not isinstance(md, Mapping) or len(md) > MAX_METADATA_KEYS or any(
            not isinstance(k, str) or not isinstance(v, str) or len(v) > MAX_METADATA_VALUE_CHARS for k, v in md.items()):
        errors.append("METADATA_INVALID")
    errors.extend(validate_evidence(row["evidence"]))
    if not str(row["evidence_digest"]):
        errors.append("EVIDENCE_DIGEST_MISSING")
    if not allow_unsealed:
        if not _is_int(row["sequence"]) or row["sequence"] < 1:
            errors.append("SEQUENCE_INVALID")
        if not str(row["record_hash"]):
            errors.append("RECORD_HASH_MISSING")
        elif record_hash_for(row) != row["record_hash"]:
            errors.append("RECORD_HASH_MISMATCH")
    return errors
