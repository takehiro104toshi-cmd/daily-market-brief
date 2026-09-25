"""P6-B7C — LLM 入力 manifest の純 model（「cutoff 時点で LLM に何を見せてよかったか」）。

- manifest は DERIVED・非 authority・非永続。上流を変えない。prompt ではなく data である（指示文・役割文・template を持たない）。
- LLM に見える部分（visible）と、handle → authority ref の内部対応表（resolution）を分ける。authority の id は visible に出ない。
- handle は authority ref の辞書順で決定論的に振る（物理順・path・mtime・乱数・時計に依らない）。等価な manifest では同じ handle。
- 投影は明示した field だけ（本文・監査 metadata・review 状態・件数・score を持たない）。
- 同じ投影になる別 record は黙って畳まず fail closed（見分けられない引用を作らない）。
- 本 module は I/O を持たない。上流の解決（Foundation / B5B の PIT resolver、B4 の入力 adapter）は builder が行う。
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

from ..core.ids import content_id
from ..core.time import ensure_aware
from ..themes.model import MECHANISM_VOCABULARY_VERSION, ThemeObservation, canonical_json
from .discovery_model import DiscoveryInputRecord
from .entity_model import EntityRecord
from .llm_proposal_model import MANIFEST_DIGEST_PREFIX, LlmTask
from .monitoring_model import MonitoringCategory, MonitoringFinding, MonitoringSubjectKind
from .relation_model import RELATION_VOCAB_VERSION
from .relation_resolution import EdgeState, ResolvedRelation

MANIFEST_SCHEMA_VERSION = "theme_llm_input_manifest:0.1.0"
VISIBLE_DIGEST_PREFIX = "thllmvis"

#: 件数・長さの上限（超えたら切り詰めず fail closed）
MAX_EVIDENCE_ITEMS = 64
MAX_THEME_ITEMS = 16
MAX_RELATION_ITEMS = 64
MAX_ENTITY_ITEMS = 64
MAX_FINDING_ITEMS = 32
MAX_SURFACE_LEN = 600
MAX_HANDLE_NUMBER = 999

#: 凍結文言（test で固定）
MANIFEST_IS_NOT_AUTHORITY = "an input manifest is a derived view of what the llm may see, never an authority record"
MANIFEST_IS_NOT_A_PROMPT = "an input manifest is data; instructions belong to a later generation gate"


class ManifestError(ValueError):
    """manifest を作れない（fail closed）。code は安定した語彙、detail に本文・秘密値を入れない。"""

    def __init__(self, code: str, detail: str = "") -> None:
        super().__init__(f"{code}: {detail}" if detail else code)
        self.code = code
        self.detail = detail


def _require(condition: bool, code: str, detail: str = "") -> None:
    if not condition:
        raise ManifestError(code, detail)


class ManifestFamily(str, Enum):
    EVIDENCE = "EVIDENCE"         # caller が渡す上流 record（B4 adapter で PIT 濾過）
    THEME = "THEME"               # caller が渡す root id（Foundation PIT resolver）
    MONITORING = "MONITORING"     # caller が選んだ B6 finding（DERIVED・非 authority）
    RELATION = "RELATION"         # scope の Theme 間の B5B relation（PIT resolver から導出）
    ENTITY = "ENTITY"             # evidence が指す entity（pinned catalog から導出）


class ScopePresence(str, Enum):
    SUPPLIED = "SUPPLIED"
    SUPPLIED_EMPTY = "SUPPLIED_EMPTY"
    NOT_SUPPLIED = "NOT_SUPPLIED"


@dataclass(frozen=True)
class TaskFamilies:
    required: Tuple[ManifestFamily, ...]     # caller が必ず渡す（省略は fail closed。空は明示として許す）
    optional: Tuple[ManifestFamily, ...]     # caller が渡してもよい
    derived: Tuple[ManifestFamily, ...]      # builder が導出する


#: task → family（ここに無い family は、その task では渡すことも導出することも禁止）
TASK_FAMILIES: Mapping[LlmTask, TaskFamilies] = {
    LlmTask.EVIDENCE_EXTRACTION: TaskFamilies(required=(ManifestFamily.EVIDENCE, ManifestFamily.THEME),
                                              optional=(), derived=()),
    LlmTask.CONTRADICTION_PROPOSAL: TaskFamilies(required=(ManifestFamily.EVIDENCE, ManifestFamily.THEME),
                                                 optional=(ManifestFamily.MONITORING,), derived=()),
    LlmTask.THEME_PROPOSAL: TaskFamilies(required=(ManifestFamily.EVIDENCE,), optional=(),
                                         derived=(ManifestFamily.ENTITY,)),
    LlmTask.RELATION_PROPOSAL: TaskFamilies(required=(ManifestFamily.EVIDENCE, ManifestFamily.THEME), optional=(),
                                            derived=(ManifestFamily.RELATION,)),
}
#: task ごとに Theme の component（CQ: 期待 consequence / IC: 無効化条件）を handle 化するか
TASK_THEME_COMPONENTS: Mapping[LlmTask, Tuple[str, ...]] = {
    LlmTask.EVIDENCE_EXTRACTION: ("CQ",),
    LlmTask.CONTRADICTION_PROPOSAL: ("CQ", "IC"),
    LlmTask.THEME_PROPOSAL: (),
    LlmTask.RELATION_PROPOSAL: (),
}
#: 文脈として見せてよい B6 condition と、投影してよい salient fact（id・閾値・governance 状態は出さない）
MONITORING_CONTEXT_CONDITIONS: Mapping[str, Tuple[str, ...]] = {
    "THEME_CONTRADICTION_EVIDENCE_PRESENT": ("role",),
    "THEME_INVALIDATION_EVIDENCE_PRESENT": ("role",),
    "THEME_WITHOUT_COUNTED_EVIDENCE": ("absence_kind",),
    "GOVERNANCE_EVIDENCE_DIVERGENCE": ("evidence_condition",),
}

_CONTROL_RE = re.compile(r"[\x00-\x1f\x7f]")
_DRIVE_PATH_RE = re.compile(r"(?:^|[\s\"'(\[])[A-Za-z]:[\\/]")
_UNC_PATH_RE = re.compile(r"\\\\[^\\\s]+\\")
_POSIX_HOME_RE = re.compile(r"(?:^|[\s\"'(\[])/(?:home|Users|root)/")
_URL_SCHEME_RE = re.compile(r"[A-Za-z][A-Za-z0-9+.-]*://")
_SECRET_QUERY_RE = re.compile(r"[?&](?:token|key|api_key|apikey|password|secret|signature|sig)=", re.IGNORECASE)


def _visible_text(value: object, name: str, *, max_len: int = MAX_SURFACE_LEN) -> str:
    """上流の文を LLM に見せる前の検査。書き換えない（切り詰め・改行除去・path 除去をしない）。"""
    _require(isinstance(value, str), "INVALID_TYPE", f"{name} must be text")
    text = str(value)
    _require(len(text) <= max_len, "SURFACE_TOO_LONG", f"{name} exceeds {max_len} characters")
    _require(not _CONTROL_RE.search(text), "INVALID_INPUT_TEXT", f"{name} contains control characters")
    for pattern in (_DRIVE_PATH_RE, _UNC_PATH_RE, _POSIX_HOME_RE, _URL_SCHEME_RE, _SECRET_QUERY_RE):
        _require(not pattern.search(text), "PROHIBITED_CONTENT_IN_INPUT", f"{name} carries a path, URL or secret-like text")
    return text


def version_pin(versioned: str) -> Tuple[str, str]:
    """`name:1.2.3` 形式の語彙 version を (name, version) の pin にする。"""
    name, _, version = versioned.rpartition(":")
    _require(bool(name) and bool(version), "INVALID_VERSION", "a vocabulary version is name:version")
    return name, version


MECHANISM_VOCABULARY_PIN = version_pin(MECHANISM_VOCABULARY_VERSION)
RELATION_VOCABULARY_PIN = version_pin(RELATION_VOCAB_VERSION)


def handle(prefix: str, number: int) -> str:
    _require(1 <= number <= MAX_HANDLE_NUMBER, "MANIFEST_TOO_LARGE", f"{prefix} handles exceed {MAX_HANDLE_NUMBER}")
    return f"{prefix}_{number:03d}"


# ---------------------------------------------------------------- LLM に見える投影（authority の id を持たない）


@dataclass(frozen=True)
class EvidenceView:
    """evidence の最小投影。時刻は日付だけ、origin は種別だけ、文は B4 の限定面（見出し・要約・題名）だけ。"""

    handle: str
    evidence_kind: str
    evidence_date: str
    source_kind: str
    fact_type: str
    observation_series: str
    taxonomy_slugs: Tuple[str, ...]
    entity_handles: Tuple[str, ...]
    text_surfaces: Tuple[Tuple[str, str], ...]


@dataclass(frozen=True)
class ComponentView:
    category: str
    statement: str


@dataclass(frozen=True)
class ConsequenceView:
    handle: str               # CQ（task が要るときだけ。要らなければ空）
    category: str
    observable_target: str
    expected_change: str
    statement: str


@dataclass(frozen=True)
class InvalidationView:
    handle: str               # IC（task が要るときだけ。要らなければ空）
    statement: str
    observable_target: str
    expected_change: str


@dataclass(frozen=True)
class ThemeView:
    """cutoff 時点の Theme の意味だけ。governance 状態・certainty・attachment・limitations・root id は出さない。"""

    handle: str
    subject_statement: str
    drivers: Tuple[ComponentView, ...]
    channels: Tuple[ComponentView, ...]
    domains: Tuple[ComponentView, ...]
    consequences: Tuple[ConsequenceView, ...]
    invalidation_conditions: Tuple[InvalidationView, ...]
    scope: Tuple[Tuple[str, str], ...]


@dataclass(frozen=True)
class RelationView:
    """cutoff 時点で ACTIVE な関係の記述。SOURCE_ASSERTED は「出典がそう主張した」であり真実ではない（class をそのまま写す）。"""

    handle: str
    source_handle: str
    target_handle: str
    relation_type: str
    assertion_class: str


@dataclass(frozen=True)
class EntityView:
    handle: str
    entity_type: str
    canonical_name: str


@dataclass(frozen=True)
class FindingView:
    """B6 finding の文脈投影。DERIVED・非 authority。件数・review 状態・重要度を持たない。"""

    handle: str
    condition_id: str
    subject_handle: str
    facts: Tuple[Tuple[str, str], ...]


# ---------------------------------------------------------------- 内部対応表（LLM に見せない）


@dataclass(frozen=True)
class HandleRef:
    """handle → authority / source ref。B7D の grounding 検証が使う。visible payload には入らない。"""

    handle: str
    family: str
    ref: str
    detail: Tuple[Tuple[str, str], ...] = ()


# ---------------------------------------------------------------- manifest


@dataclass(frozen=True, kw_only=True)
class LlmInputManifest:
    schema_version: str = MANIFEST_SCHEMA_VERSION
    task: LlmTask
    cutoff: datetime
    knowledge_versions: Tuple[Tuple[str, str], ...]
    scope_presence: Tuple[Tuple[str, str], ...]
    evidence: Tuple[EvidenceView, ...] = ()
    themes: Tuple[ThemeView, ...] = ()
    relations: Tuple[RelationView, ...] = ()
    entities: Tuple[EntityView, ...] = ()
    findings: Tuple[FindingView, ...] = ()
    resolution: Tuple[HandleRef, ...] = ()

    def __post_init__(self) -> None:
        _require(self.schema_version == MANIFEST_SCHEMA_VERSION, "UNSUPPORTED_SCHEMA_VERSION", "manifest schema")
        _require(isinstance(self.task, LlmTask), "INVALID_TYPE", "task must be LlmTask")
        _require(isinstance(self.cutoff, datetime), "INVALID_CUTOFF", "cutoff must be a datetime")
        try:
            ensure_aware(self.cutoff, "cutoff")
        except ValueError:
            raise ManifestError("NAIVE_CUTOFF", "cutoff must be timezone-aware") from None
        handles = [ref.handle for ref in self.resolution]
        _require(len(handles) == len(set(handles)), "DUPLICATE_HANDLE", "a handle is assigned twice")
        _require(set(handles) == self.visible_handles(), "HANDLE_TABLE_MISMATCH",
                 "every visible handle resolves and every resolution is visible")

    def visible_handles(self) -> set:
        out = set()
        for item in self.evidence + self.themes + self.relations + self.entities + self.findings:  # type: ignore[operator]
            out.add(item.handle)
        for theme in self.themes:
            out |= {c.handle for c in theme.consequences if c.handle}
            out |= {i.handle for i in theme.invalidation_conditions if i.handle}
        return out

    def visible_payload(self) -> Dict[str, object]:
        """LLM に見せてよい data の全体（authority の id・内部対応表・prompt を含まない）。"""
        return json.loads(canonical_json({
            "schema_version": self.schema_version, "task": self.task.value, "cutoff": self.cutoff,
            "knowledge_versions": [list(pair) for pair in self.knowledge_versions],
            "scope_presence": [list(pair) for pair in self.scope_presence],
            "evidence": self.evidence, "themes": self.themes, "relations": self.relations,
            "entities": self.entities, "findings": self.findings}))

    def visible_json(self) -> str:
        return canonical_json(self.visible_payload())

    def visible_digest(self) -> str:
        return content_id(VISIBLE_DIGEST_PREFIX, self.visible_json())

    def manifest_digest(self) -> str:
        """visible と内部対応表の両方を束縛する（同じ見た目でも別の record を指す manifest は別 digest）。"""
        return content_id(MANIFEST_DIGEST_PREFIX, canonical_json({"visible": self.visible_payload(),
                                                                   "resolution": self.resolution}))

    def resolve(self, name: str) -> HandleRef:
        for ref in self.resolution:
            if ref.handle == name:
                return ref
        raise ManifestError("UNKNOWN_HANDLE", "the handle is not in this manifest")


# ---------------------------------------------------------------- 組み立て（純関数）


def _without_handles(value: object) -> object:
    if isinstance(value, dict):
        return {k: _without_handles(v) for k, v in value.items() if k != "handle"}
    if isinstance(value, list):
        return [_without_handles(v) for v in value]
    return value


def _no_duplicate_projection(views: Sequence[object], family: str) -> None:
    """別 record が同じ投影になる（LLM が handle 以外で見分けられない）なら畳まずに fail closed。"""
    seen = set()
    for view in views:
        body = canonical_json(_without_handles(json.loads(canonical_json(view))))
        _require(body not in seen, "DUPLICATE_PROJECTION", f"two {family} records project to the same visible content")
        seen.add(body)


def _sorted_unique(items: Iterable[object], key, family: str) -> List[object]:
    ordered = sorted(items, key=key)
    keys = [key(item) for item in ordered]
    _require(len(keys) == len(set(keys)), "DUPLICATE_INPUT", f"a {family} ref appears twice")
    return ordered


def _theme_views(task: LlmTask, themes: Sequence[Tuple[str, ThemeObservation]]
                 ) -> Tuple[Tuple[ThemeView, ...], List[HandleRef], Dict[str, str]]:
    components = TASK_THEME_COMPONENTS[task]
    views: List[ThemeView] = []
    refs: List[HandleRef] = []
    by_root: Dict[str, str] = {}
    cq = ic = 0
    for number, (root_id, observation) in enumerate(_sorted_unique(themes, lambda t: t[0], "theme"), start=1):
        _require(isinstance(observation, ThemeObservation), "INVALID_TYPE", "a Theme needs its observation at the cutoff")
        _require(observation.root_id == root_id, "INVALID_INPUT", "the observation belongs to another root")
        th = handle("TH", number)
        by_root[root_id] = th
        refs.append(HandleRef(handle=th, family="THEME", ref=root_id,
                              detail=(("observation_id", observation.observation_id),)))
        mechanism = observation.mechanism
        consequences: List[ConsequenceView] = []
        for component in sorted(mechanism.consequences, key=lambda c: c.component_key):
            name = ""
            if "CQ" in components:
                cq += 1
                name = handle("CQ", cq)
                refs.append(HandleRef(handle=name, family="THEME_CONSEQUENCE", ref=root_id,
                                      detail=(("component_key", component.component_key),)))
            consequences.append(ConsequenceView(
                handle=name, category=component.category,
                observable_target=_visible_text(component.observable_target, "consequence.observable_target"),
                expected_change=component.expected_change.value,
                statement=_visible_text(component.normalized_statement, "consequence.statement")))
        conditions: List[InvalidationView] = []
        for condition in sorted(observation.invalidation_conditions, key=lambda c: c.condition_key):
            name = ""
            if "IC" in components:
                ic += 1
                name = handle("IC", ic)
                refs.append(HandleRef(handle=name, family="THEME_INVALIDATION", ref=root_id,
                                      detail=(("condition_key", condition.condition_key),)))
            conditions.append(InvalidationView(
                handle=name, statement=_visible_text(condition.normalized_statement, "invalidation.statement"),
                observable_target=_visible_text(condition.observable_target, "invalidation.observable_target"),
                expected_change=condition.expected_change.value))

        def part(items) -> Tuple[ComponentView, ...]:
            return tuple(sorted((ComponentView(category=c.category, statement=_visible_text(c.normalized_statement,
                                                                                               "component.statement"))
                                 for c in items), key=canonical_json))

        views.append(ThemeView(
            handle=th, subject_statement=_visible_text(observation.subject.normalized_subject, "subject"),
            drivers=part(mechanism.drivers), channels=part(mechanism.channels), domains=part(mechanism.domains),
            consequences=tuple(consequences), invalidation_conditions=tuple(conditions),
            scope=tuple(sorted((s.dimension.value, _visible_text(s.value, "scope.value")) for s in observation.scope))))
    _require(len(views) <= MAX_THEME_ITEMS, "MANIFEST_TOO_LARGE", "too many Themes")
    _no_duplicate_projection(views, "Theme")
    return tuple(views), refs, by_root


def _relation_views(edges: Sequence[ResolvedRelation], theme_handles: Mapping[str, str]
                    ) -> Tuple[Tuple[RelationView, ...], List[HandleRef]]:
    views: List[RelationView] = []
    refs: List[HandleRef] = []
    for number, edge in enumerate(_sorted_unique(edges, lambda e: e.edge_key, "relation"), start=1):
        _require(isinstance(edge, ResolvedRelation), "INVALID_TYPE", "relations must be resolved B5B edges")
        _require(edge.edge_state is EdgeState.ACTIVE, "INVALID_INPUT", "only active relations are visible")
        _require(edge.source_theme_root_id in theme_handles and edge.target_theme_root_id in theme_handles,
                 "INVALID_INPUT", "a visible relation connects two scoped Themes")
        name = handle("REL", number)
        views.append(RelationView(handle=name, source_handle=theme_handles[edge.source_theme_root_id],
                                  target_handle=theme_handles[edge.target_theme_root_id],
                                  relation_type=edge.relation_type.value, assertion_class=edge.assertion_class.value))
        refs.append(HandleRef(handle=name, family="RELATION", ref=edge.assertion.relation_assertion_id,
                              detail=(("edge_key", edge.edge_key),)))
    _require(len(views) <= MAX_RELATION_ITEMS, "MANIFEST_TOO_LARGE", "too many relations")
    _no_duplicate_projection(views, "relation")
    return tuple(views), refs


def _entity_views(entity_ids: Iterable[str], lookup) -> Tuple[Tuple[EntityView, ...], List[HandleRef], Dict[str, str]]:
    views: List[EntityView] = []
    refs: List[HandleRef] = []
    by_id: Dict[str, str] = {}
    for number, entity_id in enumerate(sorted(set(entity_ids)), start=1):
        record = lookup(entity_id)
        _require(isinstance(record, EntityRecord), "UNKNOWN_ENTITY", "an evidence entity is not in the pinned catalog")
        name = handle("ENT", number)
        by_id[entity_id] = name
        views.append(EntityView(handle=name, entity_type=record.entity_type.value,
                                canonical_name=_visible_text(record.canonical_name, "entity.canonical_name")))
        refs.append(HandleRef(handle=name, family="ENTITY", ref=entity_id))
    _require(len(views) <= MAX_ENTITY_ITEMS, "MANIFEST_TOO_LARGE", "too many entities")
    _no_duplicate_projection(views, "entity")
    return tuple(views), refs, by_id


def _iso(value: Optional[datetime]) -> str:
    return "" if value is None else json.loads(canonical_json(value))


def _evidence_views(records: Sequence[DiscoveryInputRecord], entity_handles: Mapping[str, str], *, with_entities: bool
                    ) -> Tuple[Tuple[EvidenceView, ...], List[HandleRef]]:
    views: List[EvidenceView] = []
    refs: List[HandleRef] = []
    for number, record in enumerate(_sorted_unique(records, lambda r: r.input_id, "evidence"), start=1):
        _require(isinstance(record, DiscoveryInputRecord), "INVALID_TYPE", "evidence must be adapted B4 input records")
        name = handle("EV", number)
        surfaces = tuple(sorted((str(field), _visible_text(text, f"evidence.{field}"))
                                for field, text in record.bounded_text_surfaces))
        views.append(EvidenceView(
            handle=name, evidence_kind=record.evidence_kind.value, evidence_date=record.evidence_date,
            source_kind=record.source_kind.value, fact_type=_visible_text(record.fact_type, "evidence.fact_type"),
            observation_series=_visible_text(record.observation_series, "evidence.observation_series"),
            taxonomy_slugs=record.taxonomy_slugs(),
            entity_handles=tuple(sorted(entity_handles[e] for e in record.entity_ids())) if with_entities else (),
            text_surfaces=surfaces))
        refs.append(HandleRef(handle=name, family="EVIDENCE", ref=record.input_id, detail=(
            ("evidence_kind", record.evidence_kind.value), ("evidence_time", _iso(record.evidence_time)),
            ("evidence_time_basis", record.evidence_time_basis.value),
            ("evidence_time_quality", record.evidence_time_quality.value), ("evidence_date", record.evidence_date),
            ("known_at", _iso(record.known_at)), ("source_origin", canonical_json(record.source_origin)))))
    _require(len(views) <= MAX_EVIDENCE_ITEMS, "MANIFEST_TOO_LARGE", "too many evidence items")
    _no_duplicate_projection(views, "evidence")
    return tuple(views), refs


def _finding_views(findings: Sequence[MonitoringFinding], cutoff: datetime, theme_handles: Mapping[str, str]
                   ) -> Tuple[Tuple[FindingView, ...], List[HandleRef], str]:
    views: List[FindingView] = []
    refs: List[HandleRef] = []
    rulesets = set()
    _require(all(isinstance(f, MonitoringFinding) for f in findings), "INVALID_TYPE",
             "findings must be B6 MonitoringFinding")
    for number, finding in enumerate(_sorted_unique(findings, lambda f: f.finding_id, "finding"), start=1):
        _require(finding.cutoff == cutoff, "FINDING_CUTOFF_MISMATCH", "a finding was derived at another cutoff")
        _require(finding.category is not MonitoringCategory.INTEGRITY, "FINDING_NOT_ALLOWED",
                 "integrity findings are not proposal context")
        allowed = MONITORING_CONTEXT_CONDITIONS.get(finding.condition_id)
        _require(allowed is not None, "FINDING_NOT_ALLOWED", "this condition is not proposal context")
        _require(finding.subject_kind is MonitoringSubjectKind.THEME_ROOT and finding.subject_ref in theme_handles,
                 "FINDING_OUT_OF_SCOPE", "a finding must concern a scoped Theme")
        rulesets.add(finding.ruleset_version)
        facts = dict(finding.salient_state.facts)
        name = handle("MON", number)
        views.append(FindingView(handle=name, condition_id=finding.condition_id,
                                 subject_handle=theme_handles[finding.subject_ref],
                                 facts=tuple(sorted((key, facts[key]) for key in allowed if key in facts))))
        refs.append(HandleRef(handle=name, family="MONITORING", ref=finding.finding_id))
    _require(len(rulesets) <= 1, "MIXED_MONITORING_RULESETS", "findings come from different ruleset versions")
    _require(len(views) <= MAX_FINDING_ITEMS, "MANIFEST_TOO_LARGE", "too many findings")
    _no_duplicate_projection(views, "finding")
    return tuple(views), refs, next(iter(rulesets), "")


def assemble_manifest(*, task: LlmTask, cutoff: datetime, presence: Mapping[ManifestFamily, ScopePresence],
                      knowledge_versions: Sequence[Tuple[str, str]],
                      themes: Sequence[Tuple[str, ThemeObservation]] = (),
                      relations: Sequence[ResolvedRelation] = (),
                      evidence: Sequence[DiscoveryInputRecord] = (),
                      entity_lookup=None,
                      findings: Sequence[MonitoringFinding] = ()) -> LlmInputManifest:
    """解決済みの上流状態から manifest を組む（純）。scope と PIT の判定は builder が済ませている前提。"""
    _require(isinstance(task, LlmTask), "INVALID_TYPE", "task must be LlmTask")
    families = TASK_FAMILIES[task]
    allowed = set(families.required) | set(families.optional) | set(families.derived)
    theme_views, theme_refs, theme_handles = _theme_views(task, themes)
    _require(ManifestFamily.THEME in allowed or not theme_views, "FAMILY_NOT_ALLOWED_FOR_TASK", "Themes")
    relation_views, relation_refs = _relation_views(relations, theme_handles)
    _require(ManifestFamily.RELATION in allowed or not relation_views, "FAMILY_NOT_ALLOWED_FOR_TASK", "relations")
    with_entities = ManifestFamily.ENTITY in allowed
    entity_ids = {e for record in evidence for e in record.entity_ids()} if with_entities else set()
    _require(not entity_ids or entity_lookup is not None, "MISSING_KNOWLEDGE", "entities need the pinned catalog")
    entity_views, entity_refs, entity_handles = _entity_views(entity_ids, entity_lookup)
    evidence_views, evidence_refs = _evidence_views(evidence, entity_handles, with_entities=with_entities)
    finding_views, finding_refs, ruleset_version = _finding_views(findings, cutoff, theme_handles)
    _require(ManifestFamily.MONITORING in allowed or not finding_views, "FAMILY_NOT_ALLOWED_FOR_TASK", "findings")
    pins = dict(knowledge_versions)
    if theme_views:
        pins.setdefault(*MECHANISM_VOCABULARY_PIN)
    if ManifestFamily.RELATION in allowed:
        pins.setdefault(*RELATION_VOCABULARY_PIN)
    if finding_views:
        pins.setdefault("monitoring_rules", ruleset_version)
    return LlmInputManifest(
        task=task, cutoff=cutoff, knowledge_versions=tuple(sorted(pins.items())),
        scope_presence=tuple(sorted((family.value, value.value) for family, value in presence.items())),
        evidence=evidence_views, themes=theme_views, relations=relation_views, entities=entity_views,
        findings=finding_views,
        resolution=tuple(sorted(theme_refs + relation_refs + entity_refs + evidence_refs + finding_refs,
                                key=lambda r: r.handle)))


__all__ = ["ComponentView", "ConsequenceView", "EntityView", "EvidenceView", "FindingView", "HandleRef",
           "InvalidationView", "LlmInputManifest", "MANIFEST_IS_NOT_AUTHORITY", "MANIFEST_IS_NOT_A_PROMPT",
           "MANIFEST_SCHEMA_VERSION", "MAX_EVIDENCE_ITEMS", "MAX_SURFACE_LEN", "MECHANISM_VOCABULARY_PIN",
           "MONITORING_CONTEXT_CONDITIONS", "ManifestError", "ManifestFamily", "RELATION_VOCABULARY_PIN",
           "RelationView", "ScopePresence", "TASK_FAMILIES", "TASK_THEME_COMPONENTS", "TaskFamilies", "ThemeView",
           "VISIBLE_DIGEST_PREFIX", "assemble_manifest", "handle", "version_pin"]
