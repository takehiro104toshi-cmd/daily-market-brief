"""P6-B4B — Theme taxonomy の versioned knowledge model（純 model。YAML を読まない）。

- `TaxonomyNode`: slug（不変 identifier）、label / description（表示）、parent_slugs（DAG、0..N）、aliases（正規化面）、
  since_version / deprecated_in_version / superseded_by（slug lifecycle）、provenance。
- `TaxonomySnapshot`: schema_version / taxonomy_version / published_at / content_digest / nodes。構築時に graph 規則
  （slug 一意、alias 所有の一意、parent 実在、self parent 禁止、cycle 禁止、multi-parent 可、RELATED edge 不在、
  伝播なし、lifecycle 整合）を検証し fail closed。

Taxonomy identity ≠ Theme identity。taxonomy の変更は Foundation の root / observation / fingerprint に影響しない
（METADATA TAXONOMY の値は slug 文字列の集合で、identity payload に含まれない）。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, List, Mapping, Optional, Tuple

from .knowledge_loader import (MAX_NOTE_LEN, MAX_TEXT_LEN, KnowledgeError, KnowledgeProvenance, checked_text, is_digest,
                               is_slug, normalize_token, parse_version, plain_mapping, plain_str, plain_str_list,
                               require_keys, sorted_unique, to_utc_iso)

TAXONOMY_SCHEMA_VERSION = "theme_taxonomy:0.1.0"
NODE_FIELDS = ("slug", "label", "description", "parent_slugs", "aliases", "since_version", "deprecated_in_version",
               "superseded_by", "provenance")
NODE_REQUIRED_FIELDS = ("slug", "label", "description", "since_version", "provenance")
MAX_PARENTS = 8


def _fail(code: str, detail: str = "", *, where: str = "") -> None:
    raise KnowledgeError(code, detail, where=where)


def _require(condition: bool, code: str, detail: str = "", *, where: str = "") -> None:
    if not condition:
        _fail(code, detail, where=where)


def _slug(value: object, where: str) -> str:
    _require(is_slug(value), "INVALID_SLUG", f"{where} must match ^[a-z][a-z0-9_]{{0,63}}$", where=where)
    return str(value)


# ---------------------------------------------------------------- node


@dataclass(frozen=True, kw_only=True)
class TaxonomyNode:
    slug: str
    label: str
    description: str
    parent_slugs: Tuple[str, ...] = ()
    aliases: Tuple[str, ...] = ()
    since_version: str
    deprecated_in_version: str = ""
    superseded_by: Tuple[str, ...] = ()
    provenance: KnowledgeProvenance

    def __post_init__(self) -> None:
        where = f"node[{self.slug!r}]"
        object.__setattr__(self, "slug", _slug(self.slug, f"{where}.slug"))
        object.__setattr__(self, "label", checked_text(self.label, f"{where}.label", max_len=MAX_TEXT_LEN, required=True))
        object.__setattr__(self, "description", checked_text(self.description, f"{where}.description",
                                                             max_len=MAX_NOTE_LEN, required=True))
        parents = tuple(_slug(p, f"{where}.parent_slugs") for p in self.parent_slugs)
        _require(self.slug not in parents, "SELF_PARENT", f"{where} lists itself as a parent", where=where)
        _require(len(parents) <= MAX_PARENTS, "TOO_MANY_PARENTS", f"{where} has more than {MAX_PARENTS} parents", where=where)
        object.__setattr__(self, "parent_slugs", sorted_unique(parents, where=f"{where}.parent_slugs"))
        aliases = tuple(checked_text(a, f"{where}.aliases", max_len=MAX_TEXT_LEN, required=True) for a in self.aliases)
        normalized = [normalize_token(a) for a in aliases]
        _require(all(n != "" for n in normalized), "INVALID_ALIAS", f"{where} has an alias that normalizes to empty", where=where)
        _require(len(set(normalized)) == len(normalized), "ALIAS_DUPLICATE", f"{where} repeats an alias after normalization",
                 where=where)
        _require(normalize_token(self.slug) not in normalized, "ALIAS_EQUALS_SLUG", f"{where} alias equals its own slug",
                 where=where)
        object.__setattr__(self, "aliases", tuple(sorted(aliases, key=normalize_token)))
        since = parse_version(self.since_version, where=f"{where}.since_version")
        _require(isinstance(self.deprecated_in_version, str), "INVALID_TYPE", f"{where}.deprecated_in_version must be a str",
                 where=where)
        if self.deprecated_in_version != "":
            deprecated = parse_version(self.deprecated_in_version, where=f"{where}.deprecated_in_version")
            _require(deprecated >= since, "INVALID_LIFECYCLE", f"{where} deprecated before it was introduced", where=where)
        successors = tuple(_slug(s, f"{where}.superseded_by") for s in self.superseded_by)
        _require(self.slug not in successors, "INVALID_SUPERSESSION", f"{where} supersedes itself", where=where)
        _require(not successors or self.deprecated_in_version != "", "SUPERSESSION_WITHOUT_DEPRECATION",
                 f"{where} names successors but is not deprecated", where=where)
        object.__setattr__(self, "superseded_by", sorted_unique(successors, where=f"{where}.superseded_by"))
        _require(isinstance(self.provenance, KnowledgeProvenance), "INVALID_TYPE", f"{where}.provenance", where=where)

    @property
    def is_deprecated(self) -> bool:
        return self.deprecated_in_version != ""

    def normalized_aliases(self) -> Tuple[str, ...]:
        return tuple(normalize_token(a) for a in self.aliases)

    def semantic_payload(self) -> Dict[str, object]:
        return {
            "slug": self.slug, "label": self.label, "description": self.description,
            "parent_slugs": list(self.parent_slugs), "aliases": list(self.aliases),
            "since_version": self.since_version, "deprecated_in_version": self.deprecated_in_version,
            "superseded_by": list(self.superseded_by), "provenance": self.provenance.to_plain(),
        }

    def to_plain(self) -> Dict[str, object]:
        return self.semantic_payload()

    @classmethod
    def from_plain(cls, data: object, *, where: str) -> "TaxonomyNode":
        mapping = plain_mapping(data, where=where)
        require_keys(mapping, allowed=NODE_FIELDS, required=NODE_REQUIRED_FIELDS, where=where)
        return cls(
            slug=plain_str(mapping, "slug", where=where), label=plain_str(mapping, "label", where=where),
            description=plain_str(mapping, "description", where=where),
            parent_slugs=plain_str_list(mapping, "parent_slugs", where=where),
            aliases=plain_str_list(mapping, "aliases", where=where),
            since_version=plain_str(mapping, "since_version", where=where),
            deprecated_in_version=plain_str(mapping, "deprecated_in_version", where=where, default=""),
            superseded_by=plain_str_list(mapping, "superseded_by", where=where),
            provenance=KnowledgeProvenance.from_plain(mapping["provenance"], where=f"{where}.provenance"),
        )


# ---------------------------------------------------------------- snapshot


@dataclass(frozen=True, kw_only=True)
class TaxonomySnapshot:
    schema_version: str = TAXONOMY_SCHEMA_VERSION
    taxonomy_version: str
    published_at: datetime
    content_digest: str
    nodes: Tuple[TaxonomyNode, ...]
    _by_slug: Mapping[str, TaxonomyNode] = field(init=False, repr=False, compare=False, default_factory=dict)
    _token_owner: Mapping[str, Tuple[str, str]] = field(init=False, repr=False, compare=False, default_factory=dict)

    def __post_init__(self) -> None:
        where = f"taxonomy[{self.taxonomy_version}]"
        _require(self.schema_version == TAXONOMY_SCHEMA_VERSION, "UNSUPPORTED_SCHEMA_VERSION", self.schema_version, where=where)
        version = parse_version(self.taxonomy_version, where=f"{where}.taxonomy_version")
        _require(isinstance(self.published_at, datetime) and self.published_at.tzinfo is not None, "INVALID_DATETIME",
                 f"{where}.published_at must be aware", where=where)
        _require(is_digest(self.content_digest), "INVALID_DIGEST", f"{where}.content_digest", where=where)
        _require(isinstance(self.nodes, tuple) and all(isinstance(n, TaxonomyNode) for n in self.nodes), "INVALID_TYPE",
                 f"{where}.nodes must be TaxonomyNode tuple", where=where)
        nodes = tuple(sorted(self.nodes, key=lambda n: n.slug))
        by_slug: Dict[str, TaxonomyNode] = {}
        for node in nodes:
            _require(node.slug not in by_slug, "DUPLICATE_SLUG", f"slug {node.slug!r} appears twice", where=where)
            by_slug[node.slug] = node
        for node in nodes:
            node_where = f"{where}.node[{node.slug!r}]"
            _require(parse_version(node.since_version, where=node_where) <= version, "FUTURE_NODE",
                     f"{node_where} since_version is after the snapshot version", where=node_where)
            if node.is_deprecated:
                _require(parse_version(node.deprecated_in_version, where=node_where) <= version, "FUTURE_DEPRECATION",
                         f"{node_where} deprecated_in_version is after the snapshot version", where=node_where)
            for parent in node.parent_slugs:
                _require(parent in by_slug, "MISSING_PARENT", f"{node_where} parent {parent!r} does not exist", where=node_where)
                _require(node.is_deprecated or not by_slug[parent].is_deprecated, "DEPRECATED_PARENT",
                         f"{node_where} has deprecated parent {parent!r}", where=node_where)
            for successor in node.superseded_by:
                _require(successor in by_slug, "INVALID_SUPERSESSION", f"{node_where} successor {successor!r} does not exist",
                         where=node_where)
                _require(not by_slug[successor].is_deprecated, "INVALID_SUPERSESSION",
                         f"{node_where} successor {successor!r} is itself deprecated", where=node_where)
        _check_acyclic(by_slug, where)
        owner: Dict[str, Tuple[str, str]] = {}
        for node in nodes:
            tokens = [(normalize_token(node.slug), "slug")] + [(t, "alias") for t in node.normalized_aliases()]
            for token, kind in tokens:
                _require(token not in owner, "ALIAS_COLLISION",
                         f"token {token!r} is owned by both {owner.get(token, ('', ''))[0]!r} and {node.slug!r}", where=where)
                owner[token] = (node.slug, kind)
        object.__setattr__(self, "nodes", nodes)
        object.__setattr__(self, "_by_slug", by_slug)
        object.__setattr__(self, "_token_owner", owner)

    # -- lookup（純。伝播しない）
    def node(self, slug: str) -> Optional[TaxonomyNode]:
        return self._by_slug.get(slug)

    def slugs(self) -> Tuple[str, ...]:
        return tuple(n.slug for n in self.nodes)

    def in_force_slugs(self) -> Tuple[str, ...]:
        """この version で deprecated でない slug。"""
        return tuple(n.slug for n in self.nodes if not n.is_deprecated)

    def token_owner(self, normalized: str) -> Optional[Tuple[str, str]]:
        return self._token_owner.get(normalized)

    def ancestors_of(self, slug: str) -> Tuple[str, ...]:
        """明示的な derived helper（表示 / grouping 用）。resolution / validation は使わない ＝ 自動伝播なし。"""
        _require(slug in self._by_slug, "UNKNOWN_SLUG", slug)
        seen: List[str] = []
        stack = list(self._by_slug[slug].parent_slugs)
        while stack:
            current = stack.pop()
            if current in seen:
                continue
            seen.append(current)
            stack.extend(self._by_slug[current].parent_slugs)
        return tuple(sorted(seen))

    # -- digest
    def semantic_payload(self) -> Dict[str, object]:
        return {
            "schema_version": self.schema_version, "taxonomy_version": self.taxonomy_version,
            "published_at": to_utc_iso(self.published_at),
            "nodes": [n.semantic_payload() for n in self.nodes],
        }


def _check_acyclic(by_slug: Mapping[str, TaxonomyNode], where: str) -> None:
    state: Dict[str, int] = {}          # 0 = unvisited, 1 = on stack, 2 = done

    def visit(slug: str, path: Tuple[str, ...]) -> None:
        mark = state.get(slug, 0)
        if mark == 2:
            return
        _require(mark != 1, "CYCLE", f"parent cycle through {' -> '.join(path + (slug,))}", where=where)
        state[slug] = 1
        for parent in by_slug[slug].parent_slugs:
            visit(parent, path + (slug,))
        state[slug] = 2

    for slug in sorted(by_slug):
        visit(slug, ())
