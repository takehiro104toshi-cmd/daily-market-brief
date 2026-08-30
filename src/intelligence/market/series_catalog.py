"""MarketSeriesカタログのloader/validator（Phase 2-D PART B）。

- カタログの正はYAML（knowledge/market_series/core_series.yaml・versioned config）。
  巨大なPython hardcode一覧は作らない（P2-A方針の実装）。
- series_idは databank/market_model.make_series_id 規約から**必ず**導出される
  ことをload時に検証する（指数/ETF/先物・spot/fixing等の雑な同一視の混入防止）。
- 本モジュールは読み取り・検証のみ（I/Oはload_catalogの1箇所。書き込みAPIなし）。
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Mapping, Optional, Tuple

from ..databank.market_model import MarketSeries, ObservationType, make_series_id

DEFAULT_CATALOG_PATH = Path("knowledge/market_series/core_series.yaml")

AS_OF_POLICIES = ("exchange_close", "day_end_utc")
CALENDARS = ("weekdays", "all_days")


@dataclass(frozen=True, kw_only=True)
class ProviderInfo:
    """データ供給元の種別（PRIMARY_OFFICIAL / MARKET_DATA_PROVIDER / SECONDARY）。"""

    provider_id: str
    source_type: str
    tier: int
    endpoint_template: str = ""
    response_format: str = ""
    provider_normalized: bool = False
    notes: str = ""


@dataclass(frozen=True, kw_only=True)
class SeriesSpec:
    """カタログ1系列分（identity＝MarketSeries＋運用フィールド）。"""

    series: MarketSeries
    display_name: str
    asset_class: str
    timezone: str
    close_time_local: str  # "HH:MM"（exchange_closeのみ必須）
    as_of_policy: str
    calendar: str
    provider_symbols: Tuple[Tuple[str, str], ...]  # (provider_id, symbol)
    preferred_source: str
    fallback_sources: Tuple[str, ...] = ()
    frequency: str = "daily"
    adjustment: str = "unadjusted"
    enabled: bool = True
    probe: bool = False
    role: str = "CORE"
    identity_notes: str = ""

    @property
    def series_id(self) -> str:
        return self.series.series_id

    @property
    def unit(self) -> str:
        return self.series.unit

    @property
    def currency(self) -> str:
        return self.series.currency

    def symbol_for(self, provider_id: str) -> Optional[str]:
        for pid, symbol in self.provider_symbols:
            if pid == provider_id:
                return symbol
        return None

    def __post_init__(self) -> None:
        if self.as_of_policy not in AS_OF_POLICIES:
            raise ValueError(f"{self.series_id}: unknown as_of_policy {self.as_of_policy!r}")
        if self.calendar not in CALENDARS:
            raise ValueError(f"{self.series_id}: unknown calendar {self.calendar!r}")
        if self.as_of_policy == "exchange_close":
            if not self.timezone or not self.close_time_local:
                raise ValueError(
                    f"{self.series_id}: exchange_closeはtimezone/close_time_local必須"
                )
        if self.series.metric == "yield" and self.series.unit != "pct":
            # RATES規約: 4.25% → 4.25（unit pct）。ratio 0.0425系列の混入を型で拒否
            raise ValueError(f"{self.series_id}: yield系列のunitはpct固定（got {self.series.unit}）")
        if self.enabled and self.symbol_for(self.preferred_source) is None:
            raise ValueError(
                f"{self.series_id}: enabled系列はpreferred_source "
                f"{self.preferred_source!r} のsymbolが必要（無いならenabled:false＝GAP）"
            )


@dataclass(frozen=True, kw_only=True)
class PerSeriesDerivation:
    """各base seriesへ適用する汎用派生（return_1d等）。"""

    metric: str
    calculation: str  # "name:version"
    unit: str  # "same_as_base" は baseのunitを引き継ぐ


@dataclass(frozen=True, kw_only=True)
class CrossSeriesDerivation:
    """複数seriesを入力とする派生（金利スプレッド・NT倍率）。"""

    series_id: str
    display_name: str
    inputs: Tuple[str, ...]
    calculation: str
    unit: str


@dataclass(frozen=True, kw_only=True)
class SeriesCatalog:
    catalog_version: str
    providers: Mapping[str, ProviderInfo]
    series: Tuple[SeriesSpec, ...]
    per_series_derivations: Tuple[PerSeriesDerivation, ...] = ()
    cross_series_derivations: Tuple[CrossSeriesDerivation, ...] = ()

    def get(self, series_id: str) -> Optional[SeriesSpec]:
        for spec in self.series:
            if spec.series_id == series_id:
                return spec
        return None

    def enabled_series(self) -> Tuple[SeriesSpec, ...]:
        return tuple(s for s in self.series if s.enabled)


def derived_series_id_for(base: SeriesSpec, metric: str) -> str:
    """汎用派生のseries_id（baseのinstrument/session維持・type=derived_metric）。"""
    return make_series_id(
        base.series.instrument_id, metric,
        ObservationType.DERIVED_METRIC.value, base.series.market_session,
    )


def _build_spec(entry: Mapping, defaults: Mapping) -> SeriesSpec:
    def val(key: str, fallback=""):
        if key in entry:
            return entry[key]
        return defaults.get(key, fallback)

    series = MarketSeries(
        series_id=str(entry["series_id"]),
        instrument_id=str(entry["instrument_id"]),
        metric=str(entry["metric"]),
        observation_type=ObservationType(str(entry["observation_type"])),
        market_session=str(entry.get("session", "")),
        unit=str(entry.get("unit", "")),
        currency=str(entry.get("currency", "") or ""),
        description=str(entry.get("identity_notes", "") or ""),
        preferred_source_ids=(str(val("preferred_source")),) if val("preferred_source") else (),
    )
    symbols = tuple(sorted(
        (str(k), str(v)) for k, v in (entry.get("provider_symbols") or {}).items()
    ))
    return SeriesSpec(
        series=series,
        display_name=str(entry.get("display_name", "")),
        asset_class=str(entry.get("asset_class", "")),
        timezone=str(entry.get("timezone", "")),
        close_time_local=str(entry.get("close_time_local", "") or ""),
        as_of_policy=str(entry.get("as_of_policy", "day_end_utc")),
        calendar=str(entry.get("calendar", "weekdays")),
        provider_symbols=symbols,
        preferred_source=str(val("preferred_source")),
        fallback_sources=tuple(str(s) for s in (val("fallback_sources", []) or [])),
        frequency=str(val("frequency", "daily")),
        adjustment=str(val("adjustment", "unadjusted")),
        enabled=bool(entry.get("enabled", True)),
        probe=bool(entry.get("probe", False)),
        role=str(entry.get("role", "CORE")),
        identity_notes=str(entry.get("identity_notes", "") or ""),
    )


def load_catalog(path: Path = DEFAULT_CATALOG_PATH) -> SeriesCatalog:
    """YAML → 検証済みSeriesCatalog。検証失敗はValueError（黙って通さない）。"""
    import yaml

    data = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    defaults = data.get("defaults") or {}
    providers = {
        str(pid): ProviderInfo(
            provider_id=str(pid),
            source_type=str(p.get("source_type", "")),
            tier=int(p.get("tier", 3)),
            endpoint_template=str(p.get("endpoint_template", "")),
            response_format=str(p.get("response_format", "")),
            provider_normalized=bool(p.get("provider_normalized", False)),
            notes=str(p.get("notes", "") or ""),
        )
        for pid, p in (data.get("providers") or {}).items()
    }

    specs = tuple(_build_spec(e, defaults) for e in (data.get("series") or []))

    seen: Dict[str, str] = {}
    for spec in specs:
        if spec.series_id in seen:
            raise ValueError(f"duplicate series_id in catalog: {spec.series_id}")
        seen[spec.series_id] = spec.display_name
        # series_id規約はMarketSeries.__post_init__が照合済み。providerの実在を検証:
        for pid, _symbol in spec.provider_symbols:
            if pid not in providers:
                raise ValueError(f"{spec.series_id}: unknown provider {pid!r}")
        if spec.enabled and spec.preferred_source not in providers:
            raise ValueError(f"{spec.series_id}: unknown preferred_source {spec.preferred_source!r}")

    deriv = data.get("derivations") or {}
    per_series = tuple(
        PerSeriesDerivation(
            metric=str(d["metric"]), calculation=str(d["calculation"]), unit=str(d["unit"])
        )
        for d in (deriv.get("per_series") or [])
    )
    if len({d.metric for d in per_series}) != len(per_series):
        raise ValueError("duplicate per_series derivation metric")
    cross = tuple(
        CrossSeriesDerivation(
            series_id=str(d["series_id"]),
            display_name=str(d.get("display_name", "")),
            inputs=tuple(str(i) for i in d.get("inputs", [])),
            calculation=str(d["calculation"]),
            unit=str(d["unit"]),
        )
        for d in (deriv.get("cross_series") or [])
    )
    for c in cross:
        if len(c.inputs) < 2:
            raise ValueError(f"{c.series_id}: cross derivationはinputs 2系列以上")
        for input_id in c.inputs:
            if input_id not in seen:
                raise ValueError(f"{c.series_id}: 未定義のinput series {input_id}")

    return SeriesCatalog(
        catalog_version=str(data.get("version", "")),
        providers=providers,
        series=specs,
        per_series_derivations=per_series,
        cross_series_derivations=cross,
    )
