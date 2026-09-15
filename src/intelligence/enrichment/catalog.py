"""Entity Catalog loader（Phase 2-E / knowledge/entities/core_entities.yaml）。

読み取り・検証のみ（書き込みAPIなし）。entity_idは "<kind>:<slug>" 固定。
alias安全度（safe / context必須）をロード時に構造化し、matcherが従う。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, Mapping, Optional, Tuple

from ..databank.news_model import EntityKind

DEFAULT_ENTITY_CATALOG_PATH = Path("knowledge/entities/core_entities.yaml")


@dataclass(frozen=True, kw_only=True)
class EntityEntry:
    """カタログ1entity分（会社以外もこの共通形へ正規化してロードする）。"""

    entity_id: str
    kind: EntityKind
    name: str
    aliases_safe: Tuple[str, ...] = ()
    aliases_context: Tuple[str, ...] = ()   # 文脈必須alias
    context_terms: Tuple[str, ...] = ()     # aliases_contextマッチ時に要求する共起語
    ticker: str = ""
    exchange: str = ""
    country: str = ""   # entityの属性（domicile）。記事のsubject countryとは別
    sector: str = ""    # 会社→sector mapping（記事→sector分類とは別）
    industry: str = ""
    code: str = ""      # country entityのISOコード等
    note: str = ""

    def __post_init__(self) -> None:
        if not self.entity_id or ":" not in self.entity_id:
            raise ValueError(f"entity_idは '<kind>:<slug>' 形式: {self.entity_id!r}")
        if self.aliases_context and not self.context_terms:
            raise ValueError(f"{self.entity_id}: 文脈必須aliasにはcontext_termsが必要")


@dataclass(frozen=True, kw_only=True)
class EntityCatalog:
    version: str
    entities: Tuple[EntityEntry, ...]
    sectors: Tuple[str, ...] = ()
    industries: Tuple[str, ...] = ()

    def by_id(self, entity_id: str) -> Optional[EntityEntry]:
        return self._id_map().get(entity_id)

    def by_ticker(self, ticker: str) -> Optional[EntityEntry]:
        for e in self.entities:
            if e.ticker and e.ticker == ticker:
                return e
        return None

    def of_kind(self, kind: EntityKind) -> Tuple[EntityEntry, ...]:
        return tuple(e for e in self.entities if e.kind is kind)

    def _id_map(self) -> Dict[str, EntityEntry]:
        return {e.entity_id: e for e in self.entities}


def _entry(kind: EntityKind, item: Mapping, *, alias_key: str = "aliases") -> EntityEntry:
    aliases_safe = tuple(str(a) for a in (item.get("aliases_safe") or item.get(alias_key) or []))
    return EntityEntry(
        entity_id=str(item["entity_id"]),
        kind=kind,
        name=str(item.get("name", "")),
        aliases_safe=aliases_safe,
        aliases_context=tuple(str(a) for a in (item.get("aliases_context") or [])),
        context_terms=tuple(str(a) for a in (item.get("context_terms") or [])),
        ticker=str(item.get("ticker", "") or ""),
        exchange=str(item.get("exchange", "") or ""),
        country=str(item.get("country", "") or ""),
        sector=str(item.get("sector", "") or ""),
        industry=str(item.get("industry", "") or ""),
        code=str(item.get("code", "") or ""),
        note=str(item.get("note", "") or ""),
    )


def load_entity_catalog(path: Path = DEFAULT_ENTITY_CATALOG_PATH) -> EntityCatalog:
    """YAML → 検証済みEntityCatalog（ID重複・sector語彙外はエラー）。"""
    import yaml

    data = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    entities = []
    for kind, section, alias_key in (
        (EntityKind.COMPANY, "companies", "aliases"),
        (EntityKind.COUNTRY, "countries", "aliases"),
        (EntityKind.CENTRAL_BANK, "central_banks", "aliases"),
        (EntityKind.GOVERNMENT, "governments", "aliases"),
        (EntityKind.PERSON, "persons", "aliases"),
        (EntityKind.INDEX, "indices", "aliases"),
        (EntityKind.COMMODITY, "commodities", "aliases"),
        (EntityKind.CURRENCY, "currencies", "aliases"),
    ):
        for item in data.get(section) or []:
            entities.append(_entry(kind, item, alias_key=alias_key))

    seen = set()
    vocab = data.get("sector_vocabulary") or {}
    sectors = tuple(str(s) for s in vocab.get("sectors", []))
    industries = tuple(str(s) for s in vocab.get("industries", []))
    for e in entities:
        if e.entity_id in seen:
            raise ValueError(f"duplicate entity_id: {e.entity_id}")
        seen.add(e.entity_id)
        expected_kind = e.entity_id.split(":", 1)[0]
        if expected_kind != e.kind.value:
            raise ValueError(f"{e.entity_id}: kind不一致（section={e.kind.value}）")
        if e.kind is EntityKind.COMPANY:
            if e.sector and sectors and e.sector not in sectors:
                raise ValueError(f"{e.entity_id}: 未定義sector {e.sector!r}")
            if e.industry and industries and e.industry not in industries:
                raise ValueError(f"{e.entity_id}: 未定義industry {e.industry!r}")
        if e.kind is EntityKind.COUNTRY and not e.code:
            raise ValueError(f"{e.entity_id}: countryはcode必須")

    return EntityCatalog(
        version=str(data.get("version", "")),
        entities=tuple(entities),
        sectors=sectors,
        industries=industries,
    )
