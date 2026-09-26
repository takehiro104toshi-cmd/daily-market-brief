"""P6-B4C — 入力 adapter（純関数）。許可された入力 model を `DiscoveryInputRecord` に正規化する。

許可入力（D-B4-4）: `sources.model.SourceDocument`、`databank.news_model.NewsItem`（＋ `NewsDocumentLink` は lineage 情報として
のみ）、`facts.model.Fact`（status USABLE のみ）、`market.model.Observation`。それ以外は UNSUPPORTED_INPUT として除外。

- L1: 明示された構造値（NewsItem.entity_refs、Fact.subject.subject_id、Observation.entity_id / series_id、Fact.fact_type、
  source kind）を pinned entity catalog で正規化する。
- L2: 限定 text 面（NewsItem headline / summary、SourceDocument title / summary）に対する taxonomy slug / alias と entity safe /
  context alias の正規化完全一致（escape 済み literal の境界一致。本文全体の走査はしない）。L2 hit は normalization evidence
  として record に残る。
- source origin は保守的に導く: 同一記事の NewsItem / SourceDocument、Observation とそれから作られた Fact は同じ origin。
  確立できなければ UNKNOWN / DERIVED。独立 source 数は数えない（Foundation qualification の責務）。
- upstream model を変更せず、filesystem / network / 現在時刻を使わない。cutoff より後に知り得た入力は除外する。
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from typing import Dict, List, Mapping, Optional, Sequence, Tuple

from ..core.types import SourceTier
from ..databank.news_model import NewsDocumentLink, NewsItem
from ..facts.model import Fact, FactStatus
from ..market.model import Observation, ObservationKind
from ..sources.model import SourceDocument
from ..themes.model import EvidenceTimeBasis, EvidenceTimeQuality, OriginKind, SourceOrigin
from .discovery_model import (DISCOVERY_ADAPTER_VERSION, AdapterResult, DiscoveryError, DiscoveryInputRecord, EntityHit, ExcludedInput,
                              InputKind, MatchLevel, TaxonomyHit)
from .entity_catalog import EntityResolutionStatus, resolve_entity_token
from .entity_model import EntityCatalogSnapshot, IdentifierType
from .knowledge_loader import normalize_token
from .taxonomy import TaxonomyResolutionStatus, resolve_taxonomy_token
from .taxonomy_model import TaxonomySnapshot

_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_ASCII_RE = re.compile(r"^[\x00-\x7f]+$")


# ---------------------------------------------------------------- alias index（run ごとに 1 回構築。純）


@dataclass(frozen=True)
class _Matcher:
    token: str
    pattern: Optional["re.Pattern[str]"]

    def contained_in(self, surface: str) -> bool:
        return self.pattern.search(surface) is not None if self.pattern is not None else self.token in surface


def _matcher(token: str) -> _Matcher:
    if _ASCII_RE.match(token):
        return _Matcher(token, re.compile(r"(?<![a-z0-9])" + re.escape(token) + r"(?![a-z0-9])"))
    return _Matcher(token, None)


@dataclass(frozen=True)
class AliasIndex:
    taxonomy_tokens: Tuple[_Matcher, ...]
    entity_aliases: Tuple[_Matcher, ...]
    context_terms: Tuple[_Matcher, ...]
    identifiers: Mapping[Tuple[str, str], Tuple[Tuple[str, Optional[date], Optional[date]], ...]] = field(default_factory=dict)

    @classmethod
    def build(cls, taxonomy: TaxonomySnapshot, catalog: EntityCatalogSnapshot) -> "AliasIndex":
        tax_tokens = set()
        for node in taxonomy.nodes:
            tax_tokens.add(normalize_token(node.slug))
            tax_tokens.update(node.normalized_aliases())
        aliases = set()
        terms = set()
        identifiers: Dict[Tuple[str, str], List[Tuple[str, Optional[date], Optional[date]]]] = {}
        for entity in catalog.entities:
            aliases.update(entity.normalized_safe_aliases())
            aliases.update(entity.normalized_context_aliases())
            terms.update(entity.normalized_context_terms())
            for identifier in entity.identifiers:
                key = (identifier.identifier_type.value, normalize_token(identifier.value))
                identifiers.setdefault(key, []).append((entity.entity_id, identifier.valid_from, identifier.valid_to))
        return cls(taxonomy_tokens=tuple(_matcher(t) for t in sorted(tax_tokens)),
                   entity_aliases=tuple(_matcher(t) for t in sorted(aliases)),
                   context_terms=tuple(_matcher(t) for t in sorted(terms)),
                   identifiers={k: tuple(sorted(v)) for k, v in identifiers.items()})


# ---------------------------------------------------------------- helpers


def _utc(value: Optional[datetime]) -> Optional[datetime]:
    if value is None:
        return None
    if value.tzinfo is None or value.utcoffset() is None:
        return None
    return value.astimezone(timezone.utc)


def _date_of(value: Optional[datetime]) -> str:
    return value.astimezone(timezone.utc).date().isoformat() if value is not None else ""


def _iso_date(text: str) -> Optional[date]:
    if not isinstance(text, str) or _DATE_RE.match(text) is None:
        return None
    try:
        return date.fromisoformat(text)
    except ValueError:
        return None


def _within(day: Optional[date], start: Optional[date], end: Optional[date]) -> bool:
    if day is None:                                   # 日付が無い入力は有効期間で絞らない（判定は後段の as_of なし解決と同じ）
        return True
    return (start is None or start <= day) and (end is None or day < end)


class _Ctx:
    """adapter 実行中の共有状態（入力集合に対する index。純: 入力から決定論的に導かれる）。"""

    def __init__(self, taxonomy: TaxonomySnapshot, catalog: EntityCatalogSnapshot, cutoff: datetime) -> None:
        self.taxonomy = taxonomy
        self.catalog = catalog
        self.cutoff = cutoff
        self.index = AliasIndex.build(taxonomy, catalog)
        self.article_by_document: Dict[str, str] = {}
        self.documents: Dict[str, SourceDocument] = {}
        self.origins: Dict[str, SourceOrigin] = {}                # input id → origin（Fact の lineage 収束用）
        self.diagnostics: List[str] = []


def _resolve_entity(ctx: _Ctx, token: str, *, context: Sequence[str], as_of: Optional[date], matched_by: str, surface: str,
                    field_name: str, diagnostics: List[str]) -> Optional[EntityHit]:
    resolution = resolve_entity_token(ctx.catalog, token, context=context, as_of=as_of)
    status = resolution.status
    if status in (EntityResolutionStatus.EXACT_ID, EntityResolutionStatus.EXACT_SAFE_ALIAS, EntityResolutionStatus.CONTEXT_ALIAS):
        level = MatchLevel.L1 if matched_by in ("structured_ref", "identifier") else MatchLevel.L2
        by = matched_by if matched_by in ("structured_ref", "identifier") else resolution.matched_by
        return EntityHit(entity_id=resolution.entity_id, level=level, matched_by=by, surface=surface, field_name=field_name)
    if status is EntityResolutionStatus.AMBIGUOUS:
        diagnostics.append(f"AMBIGUOUS_ENTITY:{normalize_token(token)}:{','.join(resolution.candidates)}")
    elif status is EntityResolutionStatus.SUPERSEDED:
        diagnostics.append(f"SUPERSEDED_ENTITY:{resolution.entity_id}->{','.join(resolution.superseded_by)}")
    elif status is EntityResolutionStatus.INACTIVE:
        diagnostics.append(f"INACTIVE_ENTITY:{resolution.entity_id}")
    return None


def _identifier_hit(ctx: _Ctx, identifier_type: IdentifierType, value: str, *, as_of: Optional[date], surface: str,
                    field_name: str, diagnostics: List[str]) -> Optional[EntityHit]:
    holders = ctx.index.identifiers.get((identifier_type.value, normalize_token(value)), ())
    live = [h for h in holders if _within(as_of, h[1], h[2])] if as_of is not None else list(holders)
    if not live:
        if holders:
            diagnostics.append(f"IDENTIFIER_OUT_OF_VALIDITY:{identifier_type.value}:{normalize_token(value)}")
        else:
            diagnostics.append(f"UNKNOWN_IDENTIFIER:{identifier_type.value}:{normalize_token(value)}")
        return None
    ids = sorted({h[0] for h in live})
    if len(ids) > 1:
        diagnostics.append(f"AMBIGUOUS_IDENTIFIER:{identifier_type.value}:{','.join(ids)}")
        return None
    return _resolve_entity(ctx, ids[0], context=(), as_of=as_of, matched_by="identifier", surface=surface, field_name=field_name,
                           diagnostics=diagnostics)


def _scan_surfaces(ctx: _Ctx, surfaces: Sequence[Tuple[str, str]], *, as_of: Optional[date], diagnostics: List[str]
                   ) -> Tuple[Tuple[TaxonomyHit, ...], Tuple[EntityHit, ...]]:
    """限定 text 面に対する L2 正規化。alias / slug の literal 境界一致 → B4B の純 resolver で状態判定。"""
    normalized = [(name, normalize_token(text)) for name, text in surfaces if text]
    if not normalized:
        return (), ()
    present_terms = tuple(m.token for m in ctx.index.context_terms if any(m.contained_in(s) for _, s in normalized))
    taxonomy_hits: List[TaxonomyHit] = []
    entity_hits: List[EntityHit] = []
    for name, surface in normalized:
        for matcher in _longest_only([m for m in ctx.index.taxonomy_tokens if m.contained_in(surface)]):
            resolution = resolve_taxonomy_token(ctx.taxonomy, matcher.token)
            if resolution.status in (TaxonomyResolutionStatus.EXACT_SLUG, TaxonomyResolutionStatus.EXACT_ALIAS):
                taxonomy_hits.append(TaxonomyHit(slug=resolution.slug, level=MatchLevel.L2, matched_by=resolution.matched_by,
                                                 surface=matcher.token, field_name=name))
            elif resolution.status is TaxonomyResolutionStatus.DEPRECATED:
                diagnostics.append(f"DEPRECATED_TAXONOMY_TOKEN:{resolution.slug}")
        for matcher in _longest_only([m for m in ctx.index.entity_aliases if m.contained_in(surface)]):
            hit = _resolve_entity(ctx, matcher.token, context=present_terms, as_of=as_of, matched_by="alias", surface=matcher.token,
                                  field_name=name, diagnostics=diagnostics)
            if hit is not None:
                entity_hits.append(hit)
    return (tuple(sorted(set(taxonomy_hits), key=lambda h: (h.slug, h.field_name, h.surface))),
            tuple(sorted(set(entity_hits), key=lambda h: (h.entity_id, h.field_name, h.surface))))


def _longest_only(matched: List[_Matcher]) -> List[_Matcher]:
    """同一 surface 内で、より長い一致 token に含まれる token は捨てる（"japan" ⊂ "bank of japan"）。決定論的で保守的。"""
    tokens = [m.token for m in matched]
    return [m for m in matched if not any(m.token != other and m.token in other for other in tokens)]


def _origin_group_key(origin: SourceOrigin) -> str:
    return origin.origin_key if origin.is_known else ""


# ---------------------------------------------------------------- per-kind adapters


def _news_item(ctx: _Ctx, item: NewsItem) -> Tuple[Optional[DiscoveryInputRecord], Optional[str]]:
    diagnostics: List[str] = []
    published = _utc(item.published_at)
    if item.published_at is not None and published is None:
        return None, "NAIVE_PUBLISHED_AT"
    if published is not None and published > ctx.cutoff:
        return None, "AFTER_CUTOFF"
    evidence_date = _date_of(published)
    as_of = _iso_date(evidence_date) if evidence_date else None
    structured: List[Tuple[str, str, str]] = []
    hits: List[EntityHit] = []
    for ref in item.entity_refs:
        kind, value, provenance = str(ref.kind.value), str(ref.value), str(ref.provenance.value)
        structured.append((kind, value, provenance))
        if kind == "ticker":
            hit = _identifier_hit(ctx, IdentifierType.TICKER, value, as_of=as_of, surface=value, field_name="entity_refs", diagnostics=diagnostics)
        else:
            before = len(diagnostics)
            hit = _resolve_entity(ctx, f"{kind}:{normalize_token(value)}", context=(), as_of=as_of, matched_by="structured_ref",
                                  surface=value, field_name="entity_refs", diagnostics=diagnostics)
            if hit is None and len(diagnostics) == before:
                diagnostics.append(f"UNKNOWN_STRUCTURED_REF:{kind}:{normalize_token(value)}")
        if hit is not None:
            hits.append(hit)
    surfaces = tuple(s for s in (("headline", item.headline), ("summary", item.summary)) if s[1])
    taxonomy_hits, alias_hits = _scan_surfaces(ctx, surfaces, as_of=as_of, diagnostics=diagnostics)
    origin = SourceOrigin(origin_kind=OriginKind.PUBLISHER_ARTICLE, origin_key=f"article:{item.article_id}",
                          source_ids=(item.source_id,) if item.source_id else (), publisher=item.publisher,
                          lineage_refs=(item.primary_document_id,))
    quality = EvidenceTimeQuality.RELIABLE if published is not None else EvidenceTimeQuality.MISSING
    record = DiscoveryInputRecord(
        input_kind=InputKind.NEWS_ITEM, input_id=item.news_item_id, source_origin=origin, evidence_time=published,
        evidence_time_basis=EvidenceTimeBasis.PUBLISHED_AT if published is not None else EvidenceTimeBasis.NONE,
        evidence_time_quality=quality, evidence_date=evidence_date, known_at=published,
        structured_entity_refs=tuple(structured), entity_hits=tuple(sorted(set(hits + list(alias_hits)), key=lambda h: (h.entity_id, h.level.value, h.field_name, h.surface))),
        taxonomy_hits=taxonomy_hits, source_kind=origin.origin_kind, bounded_text_surfaces=surfaces,
        upstream_schema_version=str(item.schema_version), diagnostics=tuple(sorted(set(diagnostics))))
    return record, None


def _document_origin(ctx: _Ctx, document: SourceDocument) -> SourceOrigin:
    root = document
    seen = {document.source_document_id}
    while root.revision_of and root.revision_of in ctx.documents and root.revision_of not in seen:
        seen.add(root.revision_of)
        root = ctx.documents[root.revision_of]
    article_id = ctx.article_by_document.get(document.source_document_id) or ctx.article_by_document.get(root.source_document_id)
    lineage = tuple(sorted({document.source_document_id} | ({document.revision_of} if document.revision_of else set())))
    if article_id:
        return SourceOrigin(origin_kind=OriginKind.PUBLISHER_ARTICLE, origin_key=f"article:{article_id}",
                            source_ids=(document.source_id,), publisher=document.publisher, lineage_refs=lineage)
    official = document.source_tier == SourceTier.TIER1
    key = f"release:{document.source_id}/{root.content_hash}" if official else f"document:{root.content_hash}"
    return SourceOrigin(origin_kind=OriginKind.OFFICIAL_RELEASE if official else OriginKind.PUBLISHER_ARTICLE, origin_key=key,
                        source_ids=(document.source_id,), publisher=document.publisher, lineage_refs=lineage)


def _source_document(ctx: _Ctx, document: SourceDocument) -> Tuple[Optional[DiscoveryInputRecord], Optional[str]]:
    diagnostics: List[str] = []
    retrieved = _utc(document.retrieved_at)
    if retrieved is None:
        return None, "NAIVE_RETRIEVED_AT"
    if retrieved > ctx.cutoff:
        return None, "KNOWN_AFTER_CUTOFF"
    published = _utc(document.published_at)
    if document.published_at is not None and published is None:
        return None, "NAIVE_PUBLISHED_AT"
    if published is not None and published > ctx.cutoff:
        return None, "AFTER_CUTOFF"
    evidence_date = _date_of(published)
    as_of = _iso_date(evidence_date) if evidence_date else None
    surfaces = tuple(s for s in (("title", document.title), ("summary", document.summary)) if s[1])
    taxonomy_hits, alias_hits = _scan_surfaces(ctx, surfaces, as_of=as_of, diagnostics=diagnostics)
    origin = _document_origin(ctx, document)
    if published is None:
        quality = EvidenceTimeQuality.MISSING
    else:
        quality = EvidenceTimeQuality.INFERRED if bool(document.published_inferred) else EvidenceTimeQuality.RELIABLE
    record = DiscoveryInputRecord(
        input_kind=InputKind.SOURCE_DOCUMENT, input_id=document.source_document_id, source_origin=origin, evidence_time=published,
        evidence_time_basis=EvidenceTimeBasis.PUBLISHED_AT if published is not None else EvidenceTimeBasis.NONE,
        evidence_time_quality=quality, evidence_date=evidence_date, known_at=retrieved, entity_hits=alias_hits,
        taxonomy_hits=taxonomy_hits, source_kind=origin.origin_kind, bounded_text_surfaces=surfaces,
        upstream_schema_version=str(document.schema_version), diagnostics=tuple(sorted(set(diagnostics))))
    return record, None


def _observation(ctx: _Ctx, observation: Observation) -> Tuple[Optional[DiscoveryInputRecord], Optional[str]]:
    diagnostics: List[str] = []
    as_of_time = _utc(observation.as_of)
    if as_of_time is None:
        return None, "NAIVE_AS_OF"
    if as_of_time > ctx.cutoff:
        return None, "AFTER_CUTOFF"
    evidence_date = observation.trading_date if _iso_date(observation.trading_date) else _date_of(as_of_time)
    as_of = _iso_date(evidence_date)
    hits: List[EntityHit] = []
    hit = _resolve_entity(ctx, observation.entity_id, context=(), as_of=as_of, matched_by="structured_ref", surface=observation.entity_id,
                          field_name="entity_id", diagnostics=diagnostics)
    if hit is None:
        hit = _identifier_hit(ctx, IdentifierType.INSTRUMENT_ID, observation.entity_id, as_of=as_of, surface=observation.entity_id,
                              field_name="entity_id", diagnostics=diagnostics)
    if hit is not None:
        hits.append(hit)
    if observation.kind is ObservationKind.DERIVED:
        origin = SourceOrigin(origin_kind=OriginKind.DERIVED, origin_key=f"derived:{observation.observation_id}",
                              source_ids=(observation.source_id,) if observation.source_id else (), lineage_refs=tuple(observation.inputs))
    elif observation.series_id and observation.source_id:
        origin = SourceOrigin(origin_kind=OriginKind.MARKET_SERIES, origin_key=f"series:{observation.source_id}/{observation.series_id}",
                              source_ids=(observation.source_id,),
                              lineage_refs=(observation.source_document_id,) if observation.source_document_id else ())
    else:
        origin = SourceOrigin(origin_kind=OriginKind.UNKNOWN)
        diagnostics.append("UNKNOWN_ORIGIN:missing series_id or source_id")
    record = DiscoveryInputRecord(
        input_kind=InputKind.OBSERVATION, input_id=observation.observation_id, source_origin=origin, evidence_time=as_of_time,
        evidence_time_basis=EvidenceTimeBasis.AS_OF, evidence_time_quality=EvidenceTimeQuality.RELIABLE, evidence_date=evidence_date,
        known_at=as_of_time, structured_entity_refs=(("entity_id", observation.entity_id, "structured"),), entity_hits=tuple(hits),
        observation_series=observation.series_id, source_kind=origin.origin_kind,
        upstream_schema_version=str(observation.schema_version), diagnostics=tuple(sorted(set(diagnostics))))
    return record, None


def _fact(ctx: _Ctx, fact: Fact) -> Tuple[Optional[DiscoveryInputRecord], Optional[str]]:
    diagnostics: List[str] = []
    if fact.status is not FactStatus.USABLE:
        return None, f"FACT_NOT_USABLE:{fact.status.value}"
    known_at = _utc(fact.time.known_at)
    if fact.time.known_at is not None and known_at is None:
        return None, "NAIVE_KNOWN_AT"
    if known_at is not None and known_at > ctx.cutoff:
        return None, "KNOWN_AFTER_CUTOFF"
    primary = _iso_date(fact.time.primary_date)
    if known_at is not None and primary is None:
        return None, "INVALID_PRIMARY_DATE"
    evidence_date = fact.time.primary_date if (known_at is not None and primary is not None) else ""
    hits: List[EntityHit] = []
    subject_id = str(fact.subject.subject_id)
    hit = _resolve_entity(ctx, subject_id, context=(), as_of=primary, matched_by="structured_ref", surface=subject_id, field_name="subject_id",
                          diagnostics=diagnostics)
    if hit is None:
        hit = _identifier_hit(ctx, IdentifierType.INSTRUMENT_ID, subject_id, as_of=primary, surface=subject_id, field_name="subject_id",
                              diagnostics=diagnostics)
    if hit is not None:
        hits.append(hit)
    ref_ids = tuple(sorted({str(r.ref_id) for r in fact.evidence}))
    upstream = {ctx.origins[r].origin_key for r in ref_ids if r in ctx.origins and ctx.origins[r].is_known}
    if len(upstream) == 1 and all(r in ctx.origins for r in ref_ids):
        base = next(ctx.origins[r] for r in ref_ids)
        origin = SourceOrigin(origin_kind=base.origin_kind, origin_key=base.origin_key, source_ids=base.source_ids, publisher=base.publisher,
                              lineage_refs=tuple(sorted(set(base.lineage_refs) | set(ref_ids) | {fact.fact_id})))
    else:
        calculation_inputs = tuple(fact.calculation.inputs) if fact.calculation is not None else ()
        lineage = tuple(sorted(set(ref_ids) | set(calculation_inputs)))
        origin = SourceOrigin(origin_kind=OriginKind.DERIVED, origin_key=f"derived:{fact.fact_id}", source_ids=tuple(fact.source_ids),
                              lineage_refs=lineage if lineage else (fact.fact_id,))
    quality = EvidenceTimeQuality.DECLARED if known_at is not None else EvidenceTimeQuality.MISSING
    record = DiscoveryInputRecord(
        input_kind=InputKind.FACT, input_id=fact.fact_id, source_origin=origin, evidence_time=known_at,
        evidence_time_basis=EvidenceTimeBasis.KNOWN_AT if known_at is not None else EvidenceTimeBasis.NONE, evidence_time_quality=quality,
        evidence_date=evidence_date, known_at=known_at, structured_entity_refs=((str(fact.subject.subject_type), subject_id, "structured"),),
        entity_hits=tuple(hits), fact_type=str(fact.fact_type), source_kind=origin.origin_kind,
        upstream_schema_version=str(fact.schema_version), diagnostics=tuple(sorted(set(diagnostics))))
    return record, None


# ---------------------------------------------------------------- entry point


def adapt_inputs(inputs: Sequence[object], *, taxonomy: TaxonomySnapshot, entity_catalog: EntityCatalogSnapshot, cutoff: datetime
                 ) -> AdapterResult:
    if not isinstance(cutoff, datetime) or cutoff.tzinfo is None or cutoff.utcoffset() is None:
        raise DiscoveryError("INVALID_CUTOFF", "cutoff must be an aware datetime")
    ctx = _Ctx(taxonomy, entity_catalog, cutoff.astimezone(timezone.utc))
    # pass 1: lineage index（記事 ↔ 文書、文書の改訂）
    for item in inputs:
        if isinstance(item, NewsItem):
            ctx.article_by_document.setdefault(item.primary_document_id, item.article_id)
        elif isinstance(item, NewsDocumentLink):
            ctx.article_by_document.setdefault(item.source_document_id, item.news_item_id)
        elif isinstance(item, SourceDocument):
            ctx.documents.setdefault(item.source_document_id, item)
    # NewsDocumentLink は news_item_id を持つが article_id は NewsItem 側にある: link の news_item_id → article_id を引き直す
    article_of_news = {i.news_item_id: i.article_id for i in inputs if isinstance(i, NewsItem)}
    for document_id, target in list(ctx.article_by_document.items()):
        if target in article_of_news:
            ctx.article_by_document[document_id] = article_of_news[target]
    records: Dict[str, DiscoveryInputRecord] = {}
    excluded: List[ExcludedInput] = []
    # pass 2: Observation / SourceDocument / NewsItem（Fact の lineage 収束はこれらの origin を先に必要とする）
    order = [i for i in inputs if isinstance(i, (Observation, SourceDocument, NewsItem))] + [i for i in inputs if isinstance(i, Fact)]
    others = [i for i in inputs if not isinstance(i, (Observation, SourceDocument, NewsItem, Fact, NewsDocumentLink))]
    for item in others:
        excluded.append(ExcludedInput(input_id=type(item).__name__, reason="UNSUPPORTED_INPUT"))
    for item in order:
        if isinstance(item, NewsItem):
            record, reason = _news_item(ctx, item)
            input_id = item.news_item_id
        elif isinstance(item, SourceDocument):
            record, reason = _source_document(ctx, item)
            input_id = item.source_document_id
        elif isinstance(item, Observation):
            record, reason = _observation(ctx, item)
            input_id = item.observation_id
        else:
            record, reason = _fact(ctx, item)
            input_id = item.fact_id
        if record is None:
            excluded.append(ExcludedInput(input_id=input_id, reason=reason or "EXCLUDED"))
            continue
        if record.input_id in records:
            ctx.diagnostics.append(f"DUPLICATE_INPUT_ID:{record.input_id}")
            continue
        records[record.input_id] = record
        ctx.origins[record.input_id] = record.source_origin
    ordered = tuple(records[k] for k in sorted(records))
    groups: Dict[str, List[str]] = {}
    for record in ordered:
        key = _origin_group_key(record.source_origin)
        if key:
            groups.setdefault(key, []).append(record.input_id)
    origin_groups = tuple((k, tuple(sorted(v))) for k, v in sorted(groups.items()))
    return AdapterResult(records=ordered, excluded=tuple(sorted(excluded, key=lambda e: (e.input_id, e.reason))),
                         origin_groups=origin_groups, diagnostics=tuple(sorted(set(ctx.diagnostics))))


__all__ = ["AliasIndex", "adapt_inputs", "DISCOVERY_ADAPTER_VERSION"]
