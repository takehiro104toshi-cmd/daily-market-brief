"""Theme change set model（P6-B1）— 2 時点の再構成差分の不変 record。authority ではなく journal に保存しない。

- `ThemeChangeSet` は frozen dataclass。同一入力（before / after resolution）から常に等価な値が得られる。
- 語彙（`ChangeKind`）は「何が変わったか」だけを表す。lifecycle / 強弱 / 方向 / score の語は含めない。
- knowledge 軸（Theme subsystem がいつ知ったか）と evidence-time 軸（evidence が指す時点）を別 field で持つ。
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Optional, Tuple

from ..themes.resolver import ResolutionStatus

CHANGE_SCHEMA_VERSION = "theme_change_set:0.1.0"
CHANGE_MODEL_VERSION = "theme_change_model:0.1.0"
#: 比較できる resolver version（Foundation A4c）。異なる version の resolution は fail closed。
SUPPORTED_RESOLVER_VERSION = "theme_resolver:0.1.0"


class ChangeKind(str, Enum):
    """変化の語彙。順序は change set 内の並び順にも使う（決定論）。"""

    ROOT_APPEARED = "ROOT_APPEARED"                        # T1 に RootRecord が無く T2 にある
    ROOT_BECAME_OBSERVED = "ROOT_BECAME_OBSERVED"          # T1 に eligible observation が無く T2 にある
    OBSERVATION_REVISED = "OBSERVATION_REVISED"            # resolved observation の id が変わった
    SEMANTIC_FIELD_CHANGED = "SEMANTIC_FIELD_CHANGED"      # subject / mechanism.* / certainty_class / scope / limitations / …
    EVIDENCE_ADDED = "EVIDENCE_ADDED"                      # T2 の visible evidence に新しい attachment
    EVIDENCE_CARRIED = "EVIDENCE_CARRIED"                  # 結果 root 側: origin event の配分で carry された既存 evidence
    EVIDENCE_DROPPED = "EVIDENCE_DROPPED"                  # T1 の visible evidence が T2 の current observation に無い
    EVIDENCE_ROLE_CHANGED = "EVIDENCE_ROLE_CHANGED"        # 同一 attachment（決定論的に対応づく）の role が変わった
    EVIDENCE_REF_REVISED = "EVIDENCE_REF_REVISED"          # 上流 revision への付け替え（revision_of_at_attachment）
    EVIDENCE_ATTRIBUTE_CHANGED = "EVIDENCE_ATTRIBUTE_CHANGED"  # 同一 key・同一 role で他 field が変わった
    NEW_SOURCE_ORIGIN = "NEW_SOURCE_ORIGIN"                # counted independent origin group が増えた
    NEW_EVIDENCE_DATE = "NEW_EVIDENCE_DATE"                # counted evidence date set が増えた
    SOURCE_ORIGIN_LOST = "SOURCE_ORIGIN_LOST"              # counted independent origin group が減った（evidence drop 等）
    EVIDENCE_DATE_LOST = "EVIDENCE_DATE_LOST"              # counted evidence date set から日付が消えた
    QUALIFICATION_CHANGED = "QUALIFICATION_CHANGED"        # A2 §19 の判定が変わった（昇格ではない）
    CONTRADICTION_APPEARED = "CONTRADICTION_APPEARED"
    CONTRADICTION_CLEARED = "CONTRADICTION_CLEARED"        # T2 の current view に反証 evidence が無い（反証が消えた意味ではない）
    INVALIDATION_APPEARED = "INVALIDATION_APPEARED"
    INVALIDATION_CLEARED = "INVALIDATION_CLEARED"          # 同上
    GOVERNANCE_CHANGED = "GOVERNANCE_CHANGED"
    METADATA_CHANGED = "METADATA_CHANGED"
    MAPPING_CHANGED = "MAPPING_CHANGED"
    LINEAGE_CHANGED = "LINEAGE_CHANGED"
    PENDING_APPEARED = "PENDING_APPEARED"
    PENDING_CLEARED = "PENDING_CLEARED"
    SEMANTIC_BECAME_UNRESOLVED = "SEMANTIC_BECAME_UNRESOLVED"
    SEMANTIC_BECAME_RESOLVED = "SEMANTIC_BECAME_RESOLVED"
    FACET_BECAME_UNRESOLVED = "FACET_BECAME_UNRESOLVED"
    FACET_BECAME_RESOLVED = "FACET_BECAME_RESOLVED"
    DEREFERENCE_CHANGED = "DEREFERENCE_CHANGED"            # 上流 dereference 状態の変化（canonical の変化ではない）


class ChangeSetStatus(str, Enum):
    COMPUTED = "COMPUTED"
    UNAVAILABLE = "UNAVAILABLE"     # before / after のいずれかが INVALID_HISTORY / STORE_CORRUPTION


class EvidenceTimeRelation(str, Enum):
    """evidence が指す時点と比較 window (T1, T2] の関係（evidence-time 軸）。"""

    DATED_WITHIN_WINDOW = "DATED_WITHIN_WINDOW"    # T1 < evidence_time <= T2
    DATED_BEFORE_WINDOW = "DATED_BEFORE_WINDOW"    # evidence_time <= T1（過去の evidence が window 内に知られた）
    UNDATED = "UNDATED"                            # evidence_time_quality MISSING（CONTEXT のみ。資格外）


#: change set 内の facet 並び順（決定論。値は語彙ではなく順序）
FACET_ORDER: Tuple[str, ...] = ("root", "observation", "evidence", "derived", "governance", "metadata", "mapping",
                                "lineage", "pending", "dereference")


class ThemeChangeError(Exception):
    """入力契約違反（fail closed）。history の失敗は例外ではなく UNAVAILABLE な change set で返す。"""

    def __init__(self, code: str, message: str = "") -> None:
        self.code = code
        super().__init__(f"{code}: {message}" if message else code)


@dataclass(frozen=True)
class Change:
    kind: ChangeKind
    facet: str                      # FACET_ORDER の値。metadata は "metadata:<FIELD>"
    subject_id: str                 # attachment_key / observation_id / event_id / field 名 / date / ref_id …
    before: str = ""                # 変更前の値（canonical 文字列。無ければ空）
    after: str = ""
    detail: str = ""
    related: Tuple[str, ...] = ()


@dataclass(frozen=True)
class ChangeDiagnostic:
    code: str
    detail: str = ""
    related: Tuple[str, ...] = ()


@dataclass(frozen=True)
class EvidenceKnowledge:
    """knowledge 軸: window 内に Theme subsystem が「知った」evidence（attached_at 順）。"""

    attachment_key: str
    attached_at: datetime
    kind: ChangeKind                # EVIDENCE_ADDED / EVIDENCE_CARRIED / EVIDENCE_ROLE_CHANGED / EVIDENCE_REF_REVISED


@dataclass(frozen=True)
class EvidenceTiming:
    """evidence-time 軸: window 内に visible になった evidence が指す時点。"""

    attachment_key: str
    evidence_time: Optional[datetime]
    evidence_date: str
    relation: EvidenceTimeRelation


@dataclass(frozen=True)
class KnowledgeAxis:
    evidence: Tuple[EvidenceKnowledge, ...] = ()
    observation_recorded_at: Optional[datetime] = None            # T2 の resolved observation（変わった場合）
    mappings_recorded_at: Tuple[Tuple[str, datetime], ...] = ()   # 新たに terminal になった mapping の recorded_at


@dataclass(frozen=True)
class EvidenceTimeAxis:
    evidence: Tuple[EvidenceTiming, ...] = ()
    new_evidence_dates: Tuple[str, ...] = ()
    dated_within_window: int = 0
    dated_before_window: int = 0
    undated: int = 0


@dataclass(frozen=True)
class ThemeChangeSet:
    schema_version: str
    change_model_version: str
    resolver_version: str
    root_id: str
    from_cutoff: datetime
    to_cutoff: datetime
    status: ChangeSetStatus
    from_status: ResolutionStatus
    to_status: ResolutionStatus
    from_observation_id: str
    to_observation_id: str
    changes: Tuple[Change, ...]
    knowledge_axis: KnowledgeAxis
    evidence_time_axis: EvidenceTimeAxis
    diagnostics: Tuple[ChangeDiagnostic, ...]

    @property
    def is_empty(self) -> bool:
        return self.status is ChangeSetStatus.COMPUTED and not self.changes

    def kinds(self) -> Tuple[ChangeKind, ...]:
        return tuple(c.kind for c in self.changes)

    def of_kind(self, kind: ChangeKind) -> Tuple[Change, ...]:
        return tuple(c for c in self.changes if c.kind is kind)


__all__ = [
    "CHANGE_SCHEMA_VERSION", "CHANGE_MODEL_VERSION", "SUPPORTED_RESOLVER_VERSION", "FACET_ORDER",
    "ChangeKind", "ChangeSetStatus", "EvidenceTimeRelation", "ThemeChangeError", "Change", "ChangeDiagnostic",
    "EvidenceKnowledge", "EvidenceTiming", "KnowledgeAxis", "EvidenceTimeAxis", "ThemeChangeSet",
]
