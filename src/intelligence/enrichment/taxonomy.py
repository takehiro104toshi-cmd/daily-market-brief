"""Theme / Event Type taxonomy loader（Phase 2-E）。

- theme_taxonomy.yaml … slug・階層（parent/related）・多信号マッチ規則・
  既存ja label対応・tank slug対応（legacy比較用）
- event_types.yaml … イベント種別＋高precisionフレーズ規則＋time horizon規則

検証: slug重複・parent実在・related実在・weak-onlyテーマの禁止はしない
（strongなしweakのみのテーマは定義エラー——単独weakでは永遠にタグ付け不能なため）。
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Optional, Tuple

DEFAULT_THEME_TAXONOMY_PATH = Path("knowledge/enrichment/theme_taxonomy.yaml")
DEFAULT_EVENT_TYPES_PATH = Path("knowledge/enrichment/event_types.yaml")

TIME_HORIZONS = ("INTRADAY", "DAYS", "WEEKS", "MONTHS", "YEARS", "UNKNOWN")


@dataclass(frozen=True, kw_only=True)
class ThemeDef:
    slug: str
    ja_label: str = ""
    tank_slugs: Tuple[str, ...] = ()
    parent: str = ""
    related: Tuple[str, ...] = ()
    strong_signals: Tuple[str, ...] = ()
    weak_signals: Tuple[str, ...] = ()
    exclude_terms: Tuple[str, ...] = ()


@dataclass(frozen=True, kw_only=True)
class ThemeTaxonomy:
    version: str
    themes: Tuple[ThemeDef, ...]

    def get(self, slug: str) -> Optional[ThemeDef]:
        for t in self.themes:
            if t.slug == slug:
                return t
        return None

    def slugs(self) -> Tuple[str, ...]:
        return tuple(t.slug for t in self.themes)

    def tank_slug_map(self) -> Dict[str, str]:
        """tank英語slug → 本taxonomy slug（legacy比較用。ground truthではない）。"""
        mapping: Dict[str, str] = {}
        for t in self.themes:
            for tank in t.tank_slugs:
                mapping[tank] = t.slug
        return mapping


@dataclass(frozen=True, kw_only=True)
class EventTypeDef:
    type_name: str
    phrases: Tuple[str, ...] = ()
    exclude_terms: Tuple[str, ...] = ()


@dataclass(frozen=True, kw_only=True)
class HorizonRule:
    horizon: str
    patterns: Tuple[str, ...]


@dataclass(frozen=True, kw_only=True)
class EventTaxonomy:
    version: str
    event_types: Tuple[EventTypeDef, ...]
    horizon_rules: Tuple[HorizonRule, ...] = ()

    def type_names(self) -> Tuple[str, ...]:
        return tuple(e.type_name for e in self.event_types)


def load_theme_taxonomy(path: Path = DEFAULT_THEME_TAXONOMY_PATH) -> ThemeTaxonomy:
    import yaml

    data = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    themes = tuple(
        ThemeDef(
            slug=str(t["slug"]),
            ja_label=str(t.get("ja_label", "") or ""),
            tank_slugs=tuple(str(s) for s in (t.get("tank_slugs") or [])),
            parent=str(t.get("parent") or ""),
            related=tuple(str(s) for s in (t.get("related") or [])),
            strong_signals=tuple(str(s) for s in (t.get("strong_signals") or [])),
            weak_signals=tuple(str(s) for s in (t.get("weak_signals") or [])),
            exclude_terms=tuple(str(s) for s in (t.get("exclude_terms") or [])),
        )
        for t in data.get("themes") or []
    )
    slugs = set()
    for t in themes:
        if t.slug in slugs:
            raise ValueError(f"duplicate theme slug: {t.slug}")
        slugs.add(t.slug)
        if not t.strong_signals:
            raise ValueError(f"{t.slug}: strong_signalsが空（weak単独では永遠にタグ不能）")
    for t in themes:
        if t.parent and t.parent not in slugs:
            raise ValueError(f"{t.slug}: 未定義parent {t.parent!r}")
        for r in t.related:
            if r not in slugs:
                raise ValueError(f"{t.slug}: 未定義related {r!r}")
    return ThemeTaxonomy(version=str(data.get("version", "")), themes=themes)


def load_event_taxonomy(path: Path = DEFAULT_EVENT_TYPES_PATH) -> EventTaxonomy:
    import yaml

    data = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    event_types = tuple(
        EventTypeDef(
            type_name=str(e["type"]),
            phrases=tuple(str(p) for p in (e.get("phrases") or [])),
            exclude_terms=tuple(str(p) for p in (e.get("exclude_terms") or [])),
        )
        for e in data.get("event_types") or []
    )
    names = [e.type_name for e in event_types]
    if len(set(names)) != len(names):
        raise ValueError("duplicate event type")
    horizon_rules = tuple(
        HorizonRule(horizon=str(r["horizon"]),
                    patterns=tuple(str(p) for p in (r.get("patterns") or [])))
        for r in data.get("time_horizon_rules") or []
    )
    for rule in horizon_rules:
        if rule.horizon not in TIME_HORIZONS:
            raise ValueError(f"unknown horizon: {rule.horizon}")
    return EventTaxonomy(
        version=str(data.get("version", "")),
        event_types=event_types,
        horizon_rules=horizon_rules,
    )
