"""P7-A2 — Narrative の point-in-time 入力 snapshot の純 model（派生・非 authority・非永続）。

`NarrativeInputSnapshot` は、caller が明示した型・Theme root・cutoff について、凍結された Phase 6 の reviewed authority を
PIT で読んだ結果を、A1 の型付き ref に写した**入力材料**である。Narrative（`NarrativeSynthesis`）ではなく、claim を持たない。
Theme・governance・evidence の authority ではない。保存しない（直列化は identity のための canonical bytes だけ）。

- 読み取り（Phase 6 の API を使うこと）は `pit_assembler` だけの責務。本 module は Phase 6 を import しない。
- ref は A1 の型（`ThemeObservationRef` ほか）をそのまま使い、A1 の検査（形式・reviewed の天井・INVALIDATES と条件）を継ぐ。
- 自由文・本文・抜粋・人間の review の理由・score・順位・確信度を持たない。
- identity は内容から決まる（`content_id`）。path・mtime・時計・乱数・処理順に依らない。
- 検査は fail closed。黙った修復・切り詰めをしない。

契約: `docs/databank/PHASE7_NARRATIVE_PIT_INPUT_CONTRACT.md`。
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Dict, Mapping, Optional, Tuple

from ..core.ids import content_id
from ..core.time import to_utc_iso
from .synthesis_model import (MAX_SUBJECTS, EvidenceAttachmentRef, EvidenceItemRef, EvidenceKind, EvidenceRole,
                              InvalidationConditionRef, MechanismComponentRef, NarrativeKind, RelationAssertionRef,
                              ThemeChangeRef, ThemeObservationRef, canonical_json)

INPUT_SCHEMA_VERSION = "narrative_input_snapshot:0.1.0"
SNAPSHOT_ID_PREFIX = "narinp"
PROVENANCE_DIGEST_PREFIX = "narprv"
MAX_STALE_AFTER_DAYS = 3650

#: 契約と test で固定する文言
SNAPSHOT_IS_NOT_AUTHORITY = ("a narrative input snapshot is derived, non-authoritative, non-persistent input material "
                             "for a future synthesis; never a narrative, a theme or governance authority, or a stored "
                             "record")

#: 読み取りに使う Phase 6 の reader の名前（version は読んだ結果から取る）
READER_RESOLVER = "theme_resolver"
READER_LIFECYCLE_MODEL = "theme_lifecycle_model"
READER_LIFECYCLE_POLICY = "theme_lifecycle_policy"
READER_CHANGE_MODEL = "theme_change_model"
READER_RELATION_RESOLVER = "theme_relation_resolver"


class NarrativeInputError(ValueError):
    """入力の組み立ての失敗（fail closed）。code は安定した語彙。detail は field 名か上流の code だけで、本文・path を
    載せない。`root_id` は形式を検査した要求 root だけ。`failures` は root ごとの (root_id, code)。"""

    def __init__(self, code: str, detail: str = "", *, root_id: str = "",
                 failures: Tuple[Tuple[str, str], ...] = ()) -> None:
        super().__init__(f"{code}: {detail}" if detail else code)
        self.code = code
        self.detail = detail
        self.root_id = root_id
        self.failures = failures


def _require(condition: bool, code: str, detail: str = "") -> None:
    if not condition:
        raise NarrativeInputError(code, detail)


# ---------------------------------------------------------------- 語彙

class EvidenceConditionFlag(str, Enum):
    """B2 EvidenceConditionFlag の複製（一致は test で固定する）。互いに排他ではない派生 flag。"""
    NO_VISIBLE_EVIDENCE = "NO_VISIBLE_EVIDENCE"
    HAS_CONTEXT_ONLY = "HAS_CONTEXT_ONLY"
    HAS_SUPPORT = "HAS_SUPPORT"
    SINGLE_SOURCE = "SINGLE_SOURCE"
    MULTI_SOURCE = "MULTI_SOURCE"
    SINGLE_EVIDENCE_DATE = "SINGLE_EVIDENCE_DATE"
    MULTI_DATE = "MULTI_DATE"
    QUALIFIES = "QUALIFIES"
    CONTESTED = "CONTESTED"
    INVALIDATION_EVIDENCE_PRESENT = "INVALIDATION_EVIDENCE_PRESENT"
    STALE = "STALE"


class SourceCapability(str, Enum):
    """evidence の出所が何を支えられるか（A1 の事実の天井）。kind だけから決まり、格上げできない。"""
    OBSERVATIONAL_RECORD = "OBSERVATIONAL_RECORD"    # FACT / OBSERVATION: 観測の記録（OBSERVED_FACT に使える）
    SOURCE_CONTENT = "SOURCE_CONTENT"                # SOURCE_DOCUMENT / NEWS_ITEM / STATEMENT: 出典の主張（事実にならない）


SOURCE_CAPABILITY_BY_KIND: Mapping[EvidenceKind, SourceCapability] = {
    EvidenceKind.FACT: SourceCapability.OBSERVATIONAL_RECORD,
    EvidenceKind.OBSERVATION: SourceCapability.OBSERVATIONAL_RECORD,
    EvidenceKind.SOURCE_DOCUMENT: SourceCapability.SOURCE_CONTENT,
    EvidenceKind.NEWS_ITEM: SourceCapability.SOURCE_CONTENT,
    EvidenceKind.STATEMENT: SourceCapability.SOURCE_CONTENT,
}

_ROOT_ID_RE = re.compile(r"^theme_[0-9A-HJKMNP-TV-Z]{26}$")
_DIGEST_RE = re.compile(r"^[a-z][a-z0-9]{1,15}_[0-9a-f]{24}$")
_READER_NAME_RE = re.compile(r"^[a-z][a-z0-9_]{0,63}$")
_READER_VERSION_RE = re.compile(r"^[0-9]{1,4}\.[0-9]{1,4}\.[0-9]{1,4}$")


def _aware(value: Any, code: str, name: str) -> datetime:
    _require(isinstance(value, datetime), code, name)
    _require(value.tzinfo is not None and value.tzinfo.utcoffset(value) is not None, code, name)
    return value


def _enum(value: Any, enum_type: type, code: str, name: str) -> Any:
    if isinstance(value, enum_type):
        return value
    _require(isinstance(value, str) and value in {m.value for m in enum_type}, code, name)
    return enum_type(value)


def _tuple(value: Any, name: str) -> Tuple[Any, ...]:
    _require(isinstance(value, (tuple, list)), "INCONSISTENT_INPUT", name)
    return tuple(value)


def _ref_key(ref: Any) -> str:
    return canonical_json(ref.to_dict())


# ---------------------------------------------------------------- caller request

@dataclass(frozen=True, kw_only=True)
class NarrativeInputRequest:
    """caller の明示の要求。暗黙の「全 Theme」「最新」「現在」「前回」は無い。

    - `root_ids`: 明示の Theme root（非意味的な集合。id 順に正規化。重複は拒否）
    - `cutoff`: aware な時刻（caller が与える）
    - `stale_after_days`: B2 の freshness policy（明示。既定値を持たない）
    - `comparison_cutoff`: 変化を投影するときだけ。aware で cutoff より厳密に前。省略なら変化を投影しない
    """
    kind: NarrativeKind
    root_ids: Tuple[str, ...]
    cutoff: datetime
    stale_after_days: int
    comparison_cutoff: Optional[datetime] = None

    def __post_init__(self) -> None:
        kind = _enum(self.kind, NarrativeKind, "INVALID_KIND", "NarrativeInputRequest.kind")
        _require(isinstance(self.root_ids, (tuple, list)), "INVALID_SCOPE", "root_ids must be an explicit tuple")
        roots = tuple(self.root_ids)
        _require(all(isinstance(r, str) and bool(_ROOT_ID_RE.fullmatch(r)) for r in roots), "INVALID_SCOPE",
                 "root_ids holds Theme root ids")
        _require(len(set(roots)) == len(roots), "INVALID_SCOPE", "a Theme root is named twice")
        if kind is NarrativeKind.THEME_STATE:
            _require(len(roots) == 1, "INVALID_SCOPE", "THEME_STATE takes exactly one Theme root")
        else:
            _require(2 <= len(roots) <= MAX_SUBJECTS, "INVALID_SCOPE", "THEME_SET takes two or more Theme roots")
        cutoff = _aware(self.cutoff, "INVALID_CUTOFF", "cutoff must be an aware datetime")
        _require(not isinstance(self.stale_after_days, bool) and isinstance(self.stale_after_days, int)
                 and 1 <= self.stale_after_days <= MAX_STALE_AFTER_DAYS, "INVALID_POLICY", "stale_after_days")
        if self.comparison_cutoff is not None:
            comparison = _aware(self.comparison_cutoff, "INVALID_COMPARISON_CUTOFF",
                                "comparison_cutoff must be an aware datetime")
            _require(comparison < cutoff, "INVALID_COMPARISON_CUTOFF", "comparison_cutoff must be before the cutoff")
        object.__setattr__(self, "kind", kind)
        object.__setattr__(self, "root_ids", tuple(sorted(roots)))


# ---------------------------------------------------------------- 投影

@dataclass(frozen=True, kw_only=True)
class EvidenceSource:
    """cutoff で見える evidence item と、その出所の能力（kind だけから決まる。格上げなし）。"""
    item: EvidenceItemRef
    capability: SourceCapability

    def __post_init__(self) -> None:
        _require(isinstance(self.item, EvidenceItemRef), "INCONSISTENT_INPUT", "EvidenceSource.item")
        capability = _enum(self.capability, SourceCapability, "INCONSISTENT_INPUT", "EvidenceSource.capability")
        _require(capability is SOURCE_CAPABILITY_BY_KIND[self.item.evidence_kind], "SOURCE_CAPABILITY_MISMATCH",
                 "capability is fixed by the evidence kind")
        object.__setattr__(self, "capability", capability)

    def to_dict(self) -> Dict[str, Any]:
        return {"item": self.item.to_dict(), "capability": self.capability.value}


@dataclass(frozen=True, kw_only=True)
class ThemeInput:
    """1 つの reviewed Theme の cutoff 時点の投影。`changes` は比較 cutoff が無いとき None（空とは区別する）。"""
    observation: ThemeObservationRef
    components: Tuple[MechanismComponentRef, ...]
    invalidation_conditions: Tuple[InvalidationConditionRef, ...]
    attachments: Tuple[EvidenceAttachmentRef, ...]
    evidence_condition_flags: Tuple[EvidenceConditionFlag, ...]
    changes: Optional[Tuple[ThemeChangeRef, ...]]
    provenance_digest: str

    def __post_init__(self) -> None:
        obs = self.observation
        _require(isinstance(obs, ThemeObservationRef), "INCONSISTENT_INPUT", "ThemeInput.observation")
        anchor = (obs.root_id, obs.observation_id)
        components = _tuple(self.components, "ThemeInput.components")
        _require(all(isinstance(c, MechanismComponentRef) and (c.root_id, c.observation_id) == anchor
                     for c in components), "INCONSISTENT_INPUT", "components belong to the observation")
        _require(len({(c.component_type, c.component_key) for c in components}) == len(components),
                 "INCONSISTENT_INPUT", "component keys are unique")
        conditions = _tuple(self.invalidation_conditions, "ThemeInput.invalidation_conditions")
        _require(all(isinstance(c, InvalidationConditionRef) and (c.root_id, c.observation_id) == anchor
                     for c in conditions), "INCONSISTENT_INPUT", "conditions belong to the observation")
        _require(len({c.condition_key for c in conditions}) == len(conditions), "INCONSISTENT_INPUT",
                 "condition keys are unique")
        attachments = _tuple(self.attachments, "ThemeInput.attachments")
        _require(all(isinstance(a, EvidenceAttachmentRef) and (a.root_id, a.observation_id) == anchor
                     for a in attachments), "INCONSISTENT_INPUT", "attachments belong to the observation")
        _require(len({a.attachment_key for a in attachments}) == len(attachments), "INCONSISTENT_INPUT",
                 "attachment keys are unique")
        keys = {c.condition_key for c in conditions}
        _require(all(a.invalidation_condition_key in keys for a in attachments if a.role is EvidenceRole.INVALIDATES),
                 "INCONSISTENT_INPUT", "invalidating evidence points at a recorded condition")
        flags = tuple(_enum(f, EvidenceConditionFlag, "INCONSISTENT_INPUT", "evidence_condition_flags")
                      for f in _tuple(self.evidence_condition_flags, "ThemeInput.evidence_condition_flags"))
        _require(len(set(flags)) == len(flags), "INCONSISTENT_INPUT", "flags are unique")
        changes = None
        if self.changes is not None:
            changes = _tuple(self.changes, "ThemeInput.changes")
            _require(all(isinstance(c, ThemeChangeRef) and c.root_id == obs.root_id for c in changes),
                     "INCONSISTENT_INPUT", "changes belong to the Theme")
            _require(len({_ref_key(c) for c in changes}) == len(changes), "INCONSISTENT_INPUT", "changes are unique")
            changes = tuple(sorted(changes, key=_ref_key))
        _require(isinstance(self.provenance_digest, str) and bool(_DIGEST_RE.fullmatch(self.provenance_digest)),
                 "INCONSISTENT_INPUT", "ThemeInput.provenance_digest")
        object.__setattr__(self, "components", tuple(sorted(components, key=_ref_key)))
        object.__setattr__(self, "invalidation_conditions", tuple(sorted(conditions, key=_ref_key)))
        object.__setattr__(self, "attachments", tuple(sorted(attachments, key=lambda a: a.attachment_key)))
        object.__setattr__(self, "evidence_condition_flags", tuple(sorted(flags, key=lambda f: f.value)))
        object.__setattr__(self, "changes", changes)

    @property
    def root_id(self) -> str:
        return self.observation.root_id

    def to_dict(self) -> Dict[str, Any]:
        return {"observation": self.observation.to_dict(),
                "components": [c.to_dict() for c in self.components],
                "invalidation_conditions": [c.to_dict() for c in self.invalidation_conditions],
                "attachments": [a.to_dict() for a in self.attachments],
                "evidence_condition_flags": [f.value for f in self.evidence_condition_flags],
                "changes": None if self.changes is None else [c.to_dict() for c in self.changes],
                "provenance_digest": self.provenance_digest}


def _reader_versions(value: Any) -> Tuple[Tuple[str, str], ...]:
    pairs = []
    for pair in _tuple(value, "reader_versions"):
        _require(isinstance(pair, (tuple, list)) and len(pair) == 2, "INCONSISTENT_INPUT", "reader_versions")
        name, version = pair
        _require(isinstance(name, str) and bool(_READER_NAME_RE.fullmatch(name)) and isinstance(version, str)
                 and bool(_READER_VERSION_RE.fullmatch(version)), "INCONSISTENT_INPUT", "reader_versions")
        pairs.append((name, version))
    _require(len({name for name, _ in pairs}) == len(pairs), "INCONSISTENT_INPUT", "reader names are unique")
    return tuple(sorted(pairs))


@dataclass(frozen=True, kw_only=True)
class NarrativeInputSnapshot:
    """cutoff 時点の reviewed Theme の入力材料（派生・非 authority・非永続）。

    - `root_ids`: 要求された root（非意味的な集合）。すべて解決できたものだけが snapshot になる（黙って落とさない）
    - `themes`: root ごとの投影（root id 順）
    - `evidence_sources`: attachment が指す evidence item（ref_id ごとに 1 つ。出所の能力つき）
    - `relations`: THEME_SET だけ（要求集合の内側の ACTIVE な B5B の直接の辺）。THEME_STATE は None（投影しない）
    - `reader_versions`: 読みに使った Phase 6 の reader / policy の version（knowledge の pin ではない。契約 §17）
    - `stale_after_days`: B2 の freshness policy（caller の明示入力）
    """
    kind: NarrativeKind
    root_ids: Tuple[str, ...]
    cutoff: datetime
    comparison_cutoff: Optional[datetime]
    themes: Tuple[ThemeInput, ...]
    evidence_sources: Tuple[EvidenceSource, ...]
    relations: Optional[Tuple[RelationAssertionRef, ...]]
    relation_provenance_digest: Optional[str]
    reader_versions: Tuple[Tuple[str, str], ...]
    stale_after_days: int
    snapshot_id: str = field(init=False)

    def __post_init__(self) -> None:
        kind = _enum(self.kind, NarrativeKind, "INVALID_KIND", "NarrativeInputSnapshot.kind")
        roots = _tuple(self.root_ids, "NarrativeInputSnapshot.root_ids")
        _require(all(isinstance(r, str) and bool(_ROOT_ID_RE.fullmatch(r)) for r in roots)
                 and len(set(roots)) == len(roots), "INVALID_SCOPE", "root_ids")
        _require(len(roots) == 1 if kind is NarrativeKind.THEME_STATE else 2 <= len(roots) <= MAX_SUBJECTS,
                 "INVALID_SCOPE", "root cardinality")
        cutoff = _aware(self.cutoff, "INVALID_CUTOFF", "cutoff")
        comparison = self.comparison_cutoff
        if comparison is not None:
            _require(_aware(comparison, "INVALID_COMPARISON_CUTOFF", "comparison_cutoff") < cutoff,
                     "INVALID_COMPARISON_CUTOFF", "comparison_cutoff must be before the cutoff")
        themes = _tuple(self.themes, "NarrativeInputSnapshot.themes")
        _require(all(isinstance(t, ThemeInput) for t in themes), "INCONSISTENT_INPUT", "themes")
        themes = tuple(sorted(themes, key=lambda t: t.root_id))
        _require(tuple(t.root_id for t in themes) == tuple(sorted(roots)), "INCONSISTENT_INPUT",
                 "every requested root has exactly one projection")
        for theme in themes:
            _require((theme.changes is None) == (comparison is None), "INCONSISTENT_INPUT",
                     "changes are projected only with a comparison cutoff")
            _require(all(c.from_cutoff == comparison and c.to_cutoff == cutoff for c in theme.changes or ()),
                     "INCONSISTENT_INPUT", "changes span exactly the requested window")
            _require(all(a.attached_at <= cutoff for a in theme.attachments), "REF_AFTER_CUTOFF", "attachment")
        sources = _tuple(self.evidence_sources, "NarrativeInputSnapshot.evidence_sources")
        _require(all(isinstance(s, EvidenceSource) for s in sources), "INCONSISTENT_INPUT", "evidence_sources")
        by_ref = {s.item.ref_id: s for s in sources}
        _require(len(by_ref) == len(sources), "INCONSISTENT_INPUT", "one evidence source per ref_id")
        attached = {(a.ref_id, a.evidence_kind) for t in themes for a in t.attachments}
        _require({(s.item.ref_id, s.item.evidence_kind) for s in sources} == attached, "INCONSISTENT_INPUT",
                 "evidence sources are exactly the attached items")
        _require(all(s.item.evidence_time <= cutoff for s in sources), "REF_AFTER_CUTOFF", "evidence item")
        relations = self.relations
        if kind is NarrativeKind.THEME_STATE:
            _require(relations is None and self.relation_provenance_digest is None, "INCONSISTENT_INPUT",
                     "THEME_STATE does not project relations")
        else:
            relations = _tuple(relations, "NarrativeInputSnapshot.relations")
            _require(all(isinstance(r, RelationAssertionRef) and set(r.roots()) <= set(roots) for r in relations),
                     "INCONSISTENT_INPUT", "relations stay inside the requested set")
            _require(len({r.relation_assertion_id for r in relations}) == len(relations), "INCONSISTENT_INPUT",
                     "relations are unique")
            relations = tuple(sorted(relations, key=_ref_key))
            _require(isinstance(self.relation_provenance_digest, str)
                     and bool(_DIGEST_RE.fullmatch(self.relation_provenance_digest)), "INCONSISTENT_INPUT",
                     "relation_provenance_digest")
        versions = _reader_versions(self.reader_versions)
        required = {READER_RESOLVER, READER_LIFECYCLE_MODEL, READER_LIFECYCLE_POLICY}
        required |= {READER_CHANGE_MODEL} if comparison is not None else set()
        required |= {READER_RELATION_RESOLVER} if kind is NarrativeKind.THEME_SET else set()
        _require({name for name, _ in versions} == required, "INCONSISTENT_INPUT", "reader_versions")
        _require(not isinstance(self.stale_after_days, bool) and isinstance(self.stale_after_days, int)
                 and 1 <= self.stale_after_days <= MAX_STALE_AFTER_DAYS, "INVALID_POLICY", "stale_after_days")
        object.__setattr__(self, "kind", kind)
        object.__setattr__(self, "root_ids", tuple(sorted(roots)))
        object.__setattr__(self, "themes", themes)
        object.__setattr__(self, "evidence_sources", tuple(sorted(sources, key=lambda s: s.item.ref_id)))
        object.__setattr__(self, "relations", relations)
        object.__setattr__(self, "reader_versions", versions)
        object.__setattr__(self, "snapshot_id", content_id(SNAPSHOT_ID_PREFIX, canonical_json(self._payload())))

    def _payload(self) -> Dict[str, Any]:
        return {"schema_version": INPUT_SCHEMA_VERSION, "kind": self.kind.value, "root_ids": list(self.root_ids),
                "cutoff": to_utc_iso(self.cutoff),
                "comparison_cutoff": None if self.comparison_cutoff is None else to_utc_iso(self.comparison_cutoff),
                "themes": [t.to_dict() for t in self.themes],
                "evidence_sources": [s.to_dict() for s in self.evidence_sources],
                "relations": None if self.relations is None else [r.to_dict() for r in self.relations],
                "relation_provenance_digest": self.relation_provenance_digest,
                "reader_versions": [{"name": n, "version": v} for n, v in self.reader_versions],
                "stale_after_days": self.stale_after_days}

    def theme(self, root_id: str) -> ThemeInput:
        for theme in self.themes:
            if theme.root_id == root_id:
                return theme
        raise NarrativeInputError("UNKNOWN_ROOT", "root is not in the snapshot")

    def to_dict(self) -> Dict[str, Any]:
        return dict(self._payload(), snapshot_id=self.snapshot_id)

    def to_canonical_json(self) -> str:
        """identity と比較のための canonical bytes。保存の形式ではない（復元 API を持たない）。"""
        return canonical_json(self.to_dict())


def provenance_digest(payload: Mapping[str, Any]) -> str:
    """PIT で見えた authority の事実（id の列）だけから作る digest。path・mtime・時計に依らない。"""
    return content_id(PROVENANCE_DIGEST_PREFIX, canonical_json(payload))


__all__ = [
    "EvidenceConditionFlag", "EvidenceSource", "INPUT_SCHEMA_VERSION", "MAX_STALE_AFTER_DAYS", "NarrativeInputError",
    "NarrativeInputRequest", "NarrativeInputSnapshot", "PROVENANCE_DIGEST_PREFIX", "READER_CHANGE_MODEL",
    "READER_LIFECYCLE_MODEL", "READER_LIFECYCLE_POLICY", "READER_RELATION_RESOLVER", "READER_RESOLVER",
    "SNAPSHOT_ID_PREFIX", "SNAPSHOT_IS_NOT_AUTHORITY", "SOURCE_CAPABILITY_BY_KIND", "SourceCapability", "ThemeInput",
    "provenance_digest",
]
