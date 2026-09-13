"""Market Internals の設定読込（Phase 3.5）。

設定値は `config.yaml` の `market_internals:` セクションに置く（CLAUDE.md: config値は
config.yamlへ）。読めなければ**既定値**で動く（fail-safe）。credentialは置かない。
universe / 価格変化定義 / 閾値は全て**version付き**で保持し、Fact / Context の
provenance（calculation parameters）へ載る。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Dict, Mapping, Optional, Tuple

from .types import DEFAULT_FLOW_SECTION, FOREIGN_INVESTORS

CONFIG_SECTION = "market_internals"

DEFAULT_INVESTOR_TYPES: Tuple[str, ...] = (
    FOREIGN_INVESTORS, "individuals", "trust_banks", "business_corporations")


@dataclass(frozen=True)
class UniverseSpec:
    """対象universeの定義（**version化**。変えたら version を上げる）。"""

    id: str = "tse_prime_common"
    version: str = "1.0.0"
    market_codes: Tuple[str, ...] = ("0111",)
    common_stock_code_suffixes: Tuple[str, ...] = ("0",)
    exclude_sector33_codes: Tuple[str, ...] = ("", "9999")

    @property
    def token(self) -> str:
        return f"{self.id}:{self.version}"

    def as_dict(self) -> Dict[str, object]:
        return {"id": self.id, "version": self.version,
                "market_codes": list(self.market_codes),
                "common_stock_code_suffixes": list(self.common_stock_code_suffixes),
                "exclude_sector33_codes": list(self.exclude_sector33_codes)}


@dataclass(frozen=True)
class InternalsConfig:
    universe: UniverseSpec = field(default_factory=UniverseSpec)
    price_movement_version: str = "1.0.0"
    price_movement_basis: str = "raw_close_vs_previous_session_raw_close"
    sessions: int = 45
    sector_classification: str = "S17"
    sector_top_n: int = 3
    sector_min_relative_gap_pct_point: Decimal = Decimal("0.30")
    turnover_flat_band_ratio: Decimal = Decimal("0.10")
    turnover_unusual_ratio: Decimal = Decimal("0.30")
    breadth_trend_threshold_pct_point: Decimal = Decimal("3.0")
    breadth_extreme_advance_ratio_pct: Decimal = Decimal("80.0")
    ad_ratio_sessions: int = 25
    flow_section: str = DEFAULT_FLOW_SECTION
    flow_publication_hour_jst: int = 16
    flow_max_age_days: int = 14
    flow_investor_types: Tuple[str, ...] = DEFAULT_INVESTOR_TYPES
    request_interval_seconds: Decimal = Decimal("0.3")
    fallback_sample_size: int = 30

    def as_dict(self) -> Dict[str, object]:
        return {
            "universe": self.universe.as_dict(),
            "price_movement": {"version": self.price_movement_version,
                               "basis": self.price_movement_basis},
            "sessions": self.sessions,
            "sector_classification": self.sector_classification,
            "sector_top_n": self.sector_top_n,
            "sector_min_relative_gap_pct_point": str(self.sector_min_relative_gap_pct_point),
            "turnover_flat_band_ratio": str(self.turnover_flat_band_ratio),
            "turnover_unusual_ratio": str(self.turnover_unusual_ratio),
            "breadth_trend_threshold_pct_point": str(self.breadth_trend_threshold_pct_point),
            "breadth_extreme_advance_ratio_pct": str(self.breadth_extreme_advance_ratio_pct),
            "ad_ratio_sessions": self.ad_ratio_sessions,
            "investor_flow": {"section": self.flow_section,
                              "publication_hour_jst": self.flow_publication_hour_jst,
                              "max_age_days": self.flow_max_age_days,
                              "investor_types": list(self.flow_investor_types)},
            "request_interval_seconds": str(self.request_interval_seconds),
            "fallback_sample_size": self.fallback_sample_size,
        }


def _decimal(value, default: Decimal) -> Decimal:
    try:
        return Decimal(str(value)) if value is not None else default
    except (InvalidOperation, ValueError):
        return default


def _int(value, default: int) -> int:
    try:
        return int(value) if value is not None else default
    except (TypeError, ValueError):
        return default


def _strs(value, default: Tuple[str, ...]) -> Tuple[str, ...]:
    if value is None:
        return default
    if isinstance(value, (list, tuple)):
        return tuple(str(v) for v in value)
    return (str(value),)


def config_from_mapping(section: Optional[Mapping]) -> InternalsConfig:
    section = dict(section or {})
    uni = dict(section.get("universe") or {})
    base = UniverseSpec()
    universe = UniverseSpec(
        id=str(uni.get("id") or base.id), version=str(uni.get("version") or base.version),
        market_codes=_strs(uni.get("market_codes"), base.market_codes),
        common_stock_code_suffixes=_strs(uni.get("common_stock_code_suffixes"),
                                         base.common_stock_code_suffixes),
        exclude_sector33_codes=_strs(uni.get("exclude_sector33_codes"),
                                     base.exclude_sector33_codes))
    pm = dict(section.get("price_movement") or {})
    flow = dict(section.get("investor_flow") or {})
    d = InternalsConfig()
    return InternalsConfig(
        universe=universe,
        price_movement_version=str(pm.get("version") or d.price_movement_version),
        price_movement_basis=str(pm.get("basis") or d.price_movement_basis),
        sessions=_int(section.get("sessions"), d.sessions),
        sector_classification=str(section.get("sector_classification")
                                  or d.sector_classification),
        sector_top_n=_int(section.get("sector_top_n"), d.sector_top_n),
        sector_min_relative_gap_pct_point=_decimal(
            section.get("sector_min_relative_gap_pct_point"),
            d.sector_min_relative_gap_pct_point),
        turnover_flat_band_ratio=_decimal(section.get("turnover_flat_band_ratio"),
                                          d.turnover_flat_band_ratio),
        turnover_unusual_ratio=_decimal(section.get("turnover_unusual_ratio"),
                                        d.turnover_unusual_ratio),
        breadth_trend_threshold_pct_point=_decimal(
            section.get("breadth_trend_threshold_pct_point"),
            d.breadth_trend_threshold_pct_point),
        breadth_extreme_advance_ratio_pct=_decimal(
            section.get("breadth_extreme_advance_ratio_pct"),
            d.breadth_extreme_advance_ratio_pct),
        ad_ratio_sessions=_int(section.get("ad_ratio_sessions"), d.ad_ratio_sessions),
        flow_section=str(flow.get("section") or d.flow_section),
        flow_publication_hour_jst=_int(flow.get("publication_hour_jst"),
                                       d.flow_publication_hour_jst),
        flow_max_age_days=_int(flow.get("max_age_days"), d.flow_max_age_days),
        flow_investor_types=_strs(flow.get("investor_types"), d.flow_investor_types),
        request_interval_seconds=_decimal(section.get("request_interval_seconds"),
                                          d.request_interval_seconds),
        fallback_sample_size=_int(section.get("fallback_sample_size"),
                                  d.fallback_sample_size))


def load_internals_config(config_path: Path = Path("config.yaml")) -> InternalsConfig:
    """config.yaml優先。読めなければ既定値（credentialは一切読まない）。"""
    try:
        import yaml  # 既存依存（PyYAML）

        data = yaml.safe_load(Path(config_path).read_text(encoding="utf-8")) or {}
        return config_from_mapping(data.get(CONFIG_SECTION))
    except Exception:  # noqa: BLE001 設定破損でpipelineを止めない
        return config_from_mapping(None)
