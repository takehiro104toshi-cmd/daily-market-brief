"""P6-B7C — LLM 入力 manifest の builder（read-only・point-in-time・fail closed）。

caller が task・cutoff・scope を明示し、builder は既存の PIT 入口だけで上流を読む:

- Theme: Foundation `resolve_at_data_root`（store を検証してから cutoff で解決する。破損は status として返る）
- relation: B5B `resolve_relations_at_data_root`（同上）。scope の Theme 間で cutoff に ACTIVE な関係だけ
- evidence: caller が渡した上流 record を B4 `adapt_inputs` で正規化（cutoff 後に知り得た record は除外）
- monitoring finding: caller が選んだ B6 finding（同じ cutoff のものだけ）

B3 / B5C の提案 authority は読まない（生成に必要な role が無い。check-then-reuse は B7F）。
書き込み・cache・一時 file・現在時刻・乱数・network は無い。解決できないものは黙って捨てず fail closed。
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Dict, List, Mapping, Optional, Sequence, Tuple, Union

from ..themes.model import is_root_id
from ..themes.resolver import ResolutionStatus, resolve_at_data_root
from .discovery_adapter import adapt_inputs
from .entity_model import EntityCatalogSnapshot
from .llm_manifest_model import (TASK_FAMILIES, LlmInputManifest, ManifestError, ManifestFamily, ScopePresence,
                                 assemble_manifest)
from .llm_proposal_model import LlmTask
from .relation_model import EDGE_KEY_SEPARATOR
from .relation_resolution import EdgeState, RelationResolutionStatus, endpoint_lookup_from_roots
from .relation_store import resolve_relations_at_data_root
from .taxonomy_model import TaxonomySnapshot

MANIFEST_BUILDER_VERSION = "theme_llm_manifest_builder:0.1.0"
#: B4 adapter の除外理由のうち「cutoff 時点ではまだ知り得なかった」もの（痕跡を残さず見えないだけ）
PIT_EXCLUSIONS: Tuple[str, ...] = ("AFTER_CUTOFF", "KNOWN_AFTER_CUTOFF")
#: caller が渡した evidence record の同一性を決める属性（上流 model を import せずに読む）
_EVIDENCE_ID_ATTRIBUTES: Tuple[str, ...] = ("news_item_id", "source_document_id", "fact_id", "observation_id")


def _require(condition: bool, code: str, detail: str = "") -> None:
    if not condition:
        raise ManifestError(code, detail)


def _code(exc: Exception) -> str:
    return str(getattr(exc, "code", "") or type(exc).__name__)


@dataclass(frozen=True, kw_only=True)
class LlmManifestScope:
    """caller が明示する範囲。`None` ＝ 渡していない、空 tuple ＝ 空で渡した（区別する）。暗黙の「全部」は無い。"""

    task: LlmTask
    cutoff: datetime
    theme_root_ids: Optional[Tuple[str, ...]] = None
    evidence_inputs: Optional[Tuple[object, ...]] = None
    monitoring_findings: Optional[Tuple[object, ...]] = None

    def __post_init__(self) -> None:
        _require(isinstance(self.task, LlmTask), "INVALID_TASK", "task must be LlmTask")
        _require(isinstance(self.cutoff, datetime), "MISSING_CUTOFF", "an explicit cutoff is required")
        _require(self.cutoff.tzinfo is not None and self.cutoff.utcoffset() is not None, "NAIVE_CUTOFF",
                 "cutoff must be timezone-aware")
        for name in ("theme_root_ids", "evidence_inputs", "monitoring_findings"):
            value = getattr(self, name)
            _require(value is None or isinstance(value, tuple), "INVALID_SCOPE", f"{name} is None or a tuple")

    def supplied(self) -> Mapping[ManifestFamily, Optional[Tuple[object, ...]]]:
        return {ManifestFamily.EVIDENCE: self.evidence_inputs, ManifestFamily.THEME: self.theme_root_ids,
                ManifestFamily.MONITORING: self.monitoring_findings}


def _presence(scope: LlmManifestScope) -> Dict[ManifestFamily, ScopePresence]:
    families = TASK_FAMILIES[scope.task]
    caller_families = set(families.required) | set(families.optional)
    presence: Dict[ManifestFamily, ScopePresence] = {}
    for family, value in scope.supplied().items():
        if family not in caller_families:
            _require(value is None, "FAMILY_NOT_ALLOWED_FOR_TASK", f"{scope.task.value} does not take {family.value}")
            continue
        if family in families.required:
            _require(value is not None, "SCOPE_OMITTED", f"{scope.task.value} needs an explicit {family.value} scope")
        presence[family] = (ScopePresence.NOT_SUPPLIED if value is None else
                            ScopePresence.SUPPLIED_EMPTY if len(value) == 0 else ScopePresence.SUPPLIED)
    return presence


def _check_knowledge(scope: LlmManifestScope, taxonomy: TaxonomySnapshot, entity_catalog: EntityCatalogSnapshot) -> None:
    _require(isinstance(taxonomy, TaxonomySnapshot) and isinstance(entity_catalog, EntityCatalogSnapshot),
             "MISSING_KNOWLEDGE", "pinned taxonomy and entity catalog snapshots are required")
    for name, snapshot in (("taxonomy", taxonomy), ("entity_catalog", entity_catalog)):
        _require(snapshot.published_at <= scope.cutoff, "FUTURE_KNOWLEDGE", f"{name} was published after the cutoff")


def _read_themes(data_root, root_ids: Sequence[str], cutoff: datetime):
    _require(all(isinstance(r, str) and is_root_id(r) for r in root_ids), "INVALID_SCOPE_ENTRY",
             "theme scope holds Theme root ids")
    _require(len(root_ids) == len(set(root_ids)), "DUPLICATE_SCOPE_ENTRY", "a Theme root is named twice")
    themes, created = [], {}
    for root_id in sorted(root_ids):
        try:
            resolution = resolve_at_data_root(data_root, root_id, cutoff)
        except Exception as exc:                                        # store が開けない等。黙って空にしない
            raise ManifestError("THEME_AUTHORITY_UNAVAILABLE", _code(exc)) from None
        _require(resolution.status is ResolutionStatus.RESOLVED and resolution.observation is not None
                 and resolution.root is not None, "THEME_NOT_RESOLVED", resolution.status.value)
        themes.append((root_id, resolution.observation))
        created[root_id] = resolution.root.created_at
    return themes, created


def _read_relations(data_root, cutoff: datetime, created_at_by_root: Mapping[str, datetime]):
    """scope の Theme 間で cutoff に ACTIVE な関係。端点の lifecycle は投影しないため lookup は作成時刻だけで組む。"""
    try:
        resolution = resolve_relations_at_data_root(data_root, cutoff=cutoff,
                                                    endpoint_lookup=endpoint_lookup_from_roots(created_at_by_root))
    except Exception as exc:
        raise ManifestError("RELATION_AUTHORITY_UNAVAILABLE", _code(exc)) from None
    _require(resolution.status in (RelationResolutionStatus.RESOLVED, RelationResolutionStatus.NO_STATE),
             "RELATION_NOT_RESOLVED", resolution.status.value)
    scoped = set(created_at_by_root)
    for edge in resolution.unresolved:                                   # scope に触れる未解決の辺は推測しない
        endpoints = set(edge.edge_key.split(EDGE_KEY_SEPARATOR)[:2])
        _require(not endpoints & scoped, "RELATION_NOT_RESOLVED", edge.status.value)
    return [edge for edge in resolution.edges if edge.edge_state is EdgeState.ACTIVE
            and edge.source_theme_root_id in scoped and edge.target_theme_root_id in scoped]


def _evidence_identity(item: object) -> Tuple[str, ...]:
    """上流 record の同一性（型名 ＋ id）。lineage だけの link は両端の id で識別する。"""
    name = type(item).__name__
    if name == "NewsDocumentLink":
        return (name, str(getattr(item, "news_item_id", "")), str(getattr(item, "source_document_id", "")))
    for attribute in _EVIDENCE_ID_ATTRIBUTES:
        value = getattr(item, attribute, None)
        if isinstance(value, str) and value:
            return (name, value)
    return (name, repr(item))                                            # 非対応の型は adapter が拒否する


def _read_evidence(inputs: Sequence[object], cutoff: datetime, taxonomy: TaxonomySnapshot,
                   entity_catalog: EntityCatalogSnapshot):
    unique: Dict[Tuple[str, ...], object] = {}
    for item in inputs:
        key = _evidence_identity(item)
        if key in unique:                                                  # 同じ record の再掲は同一性で畳む
            _require(unique[key] == item, "CONFLICTING_EVIDENCE_INPUT", "two different records share an id")
            continue
        unique[key] = item
    try:
        adapted = adapt_inputs([unique[k] for k in sorted(unique)], taxonomy=taxonomy, entity_catalog=entity_catalog,
                               cutoff=cutoff)
    except Exception as exc:
        raise ManifestError("EVIDENCE_INPUT_REJECTED", _code(exc)) from None
    for excluded in adapted.excluded:
        _require(excluded.reason in PIT_EXCLUSIONS, "EVIDENCE_INPUT_REJECTED", excluded.reason)
    _require(not any(code.startswith("DUPLICATE_INPUT_ID") for code in adapted.diagnostics),
             "CONFLICTING_EVIDENCE_INPUT", "the adapter saw one id twice")
    return list(adapted.records)


def build_input_manifest(*, data_root: Union[str, "object"], scope: LlmManifestScope, taxonomy: TaxonomySnapshot,
                         entity_catalog: EntityCatalogSnapshot) -> LlmInputManifest:
    """cutoff 時点で LLM に見せてよい data を決定論的に組む。上流を変えない。"""
    _require(isinstance(scope, LlmManifestScope), "INVALID_SCOPE", "scope must be LlmManifestScope")
    presence = _presence(scope)
    _check_knowledge(scope, taxonomy, entity_catalog)
    families = TASK_FAMILIES[scope.task]
    themes: List = []
    created: Dict[str, datetime] = {}
    if ManifestFamily.THEME in presence:
        themes, created = _read_themes(data_root, scope.theme_root_ids or (), scope.cutoff)
    relations = _read_relations(data_root, scope.cutoff, created) if ManifestFamily.RELATION in families.derived else []
    evidence = _read_evidence(scope.evidence_inputs or (), scope.cutoff, taxonomy, entity_catalog)
    return assemble_manifest(
        task=scope.task, cutoff=scope.cutoff, presence=presence,
        knowledge_versions=(("entity_catalog", entity_catalog.catalog_version),
                            ("taxonomy", taxonomy.taxonomy_version)),
        themes=themes, relations=relations, evidence=evidence, entity_lookup=entity_catalog.entity,
        findings=scope.monitoring_findings or ())


__all__ = ["LlmManifestScope", "MANIFEST_BUILDER_VERSION", "PIT_EXCLUSIONS", "build_input_manifest"]
