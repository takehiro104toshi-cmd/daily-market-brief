"""core/types.py と core/contracts.py の契約テスト。

- FACT/FORECAST分離の型レベル強制（EvidenceRecordの不変条件）
- ForecastAttributesの確信度レンジ検証
- 最小ダミー実装がProtocolを構造的に満たすこと（契約が実装可能であることの担保）
"""
from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Iterable, Mapping, Sequence

import pytest

from src.intelligence.core import contracts, types


NOW = datetime(2026, 8, 29, 7, 30, tzinfo=timezone.utc)
SRC = types.SourceMeta(name="日本銀行", url="https://www.boj.or.jp/", tier=types.SourceTier.TIER1, retrieved_at=NOW)


def _record(statement_type: types.StatementType, forecast=None) -> types.EvidenceRecord:
    return types.EvidenceRecord(
        id="ev-001",
        statement_text="日銀は政策金利の据え置きを決定した",
        statement_type=statement_type,
        source=SRC,
        retrieved_at=NOW,
        event_date=date(2026, 8, 28),
        forecast=forecast,
    )


class TestEvidenceInvariants:
    def test_fact_record_is_valid(self) -> None:
        rec = _record(types.StatementType.FACT)
        assert rec.source.tier == types.SourceTier.TIER1
        assert rec.forecast is None

    def test_forecast_requires_forecast_attributes(self) -> None:
        with pytest.raises(ValueError):
            _record(types.StatementType.FORECAST)

    def test_non_forecast_must_not_carry_forecast_attributes(self) -> None:
        fa = types.ForecastAttributes(confidence=4, horizon=types.Horizon.ONE_DAY, agent="system")
        with pytest.raises(ValueError):
            _record(types.StatementType.ANALYSIS, forecast=fa)

    def test_valid_forecast_record(self) -> None:
        fa = types.ForecastAttributes(
            confidence=4, horizon=types.Horizon.ONE_DAY, agent="system",
            invalidation_condition="夜間先物が前日終値を1%以上下回った場合",
        )
        rec = _record(types.StatementType.FORECAST, forecast=fa)
        assert rec.forecast is not None and rec.forecast.horizon is types.Horizon.ONE_DAY

    @pytest.mark.parametrize("bad", [-1, 6, 100])
    def test_confidence_range_enforced(self, bad: int) -> None:
        with pytest.raises(ValueError):
            types.ForecastAttributes(confidence=bad, horizon=types.Horizon.LONG, agent="system")

    def test_records_are_immutable(self) -> None:
        rec = _record(types.StatementType.FACT)
        with pytest.raises(Exception):
            rec.statement_text = "改変"  # type: ignore[misc]


# --- 最小ダミー実装（契約が実装可能・注入可能であることの担保） ---

class _FixedClock:
    def now(self) -> datetime:
        return NOW


class _NullLLM:
    def is_available(self) -> bool:
        return False

    def complete(self, prompt: str, *, system: str = "", max_tokens: int = 1024) -> types.LLMResult:
        return types.LLMResult(text="", provider="null", model="none")


class _MemoryEvidenceRepo:
    def __init__(self) -> None:
        self._records: list[types.EvidenceRecord] = []

    def append(self, records: Iterable[types.EvidenceRecord]) -> int:
        added = list(records)
        self._records.extend(added)
        return len(added)

    def for_date(self, day: date) -> Sequence[types.EvidenceRecord]:
        return [r for r in self._records if r.event_date == day]


class _MemoryMarketRepo:
    def __init__(self) -> None:
        self._obs: list[types.MarketObservation] = []

    def record(self, observations: Iterable[types.MarketObservation]) -> int:
        added = list(observations)
        self._obs.extend(added)
        return len(added)

    def series(self, metric_id: str, start: date, end: date) -> Sequence[types.MarketObservation]:
        return [o for o in self._obs if o.metric_id == metric_id and start <= o.as_of.date() <= end]


class _MemoryNewsRepo:
    def save_items(self, items: Sequence[Mapping[str, object]]) -> int:
        return len(items)

    def items_for(self, day: date) -> Sequence[Mapping[str, object]]:
        return []


class _StaticKnowledgeRepo:
    _assets = {"causal_rules.market": {"rules": []}}

    def list_assets(self) -> Sequence[str]:
        return list(self._assets)

    def load(self, asset_id: str) -> Mapping[str, object]:
        return self._assets[asset_id]


class TestProtocolsAreImplementable:
    @pytest.mark.parametrize(
        "impl,protocol",
        [
            (_FixedClock(), contracts.Clock),
            (_NullLLM(), contracts.LLMProvider),
            (_MemoryEvidenceRepo(), contracts.EvidenceRepository),
            (_MemoryMarketRepo(), contracts.MarketRepository),
            (_MemoryNewsRepo(), contracts.NewsRepository),
            (_StaticKnowledgeRepo(), contracts.KnowledgeRepository),
        ],
    )
    def test_dummy_satisfies_protocol(self, impl, protocol) -> None:
        assert isinstance(impl, protocol)

    def test_evidence_repo_roundtrip(self) -> None:
        repo = _MemoryEvidenceRepo()
        rec = _record(types.StatementType.FACT)
        assert repo.append([rec]) == 1
        assert repo.for_date(date(2026, 8, 28)) == [rec]
        assert repo.for_date(date(2026, 8, 29)) == []

    def test_market_repo_roundtrip(self) -> None:
        repo = _MemoryMarketRepo()
        obs = types.MarketObservation(
            metric_id="nikkei225.close", value=69902.25, unit="index", as_of=NOW,
            calc_method="close", source="test",
        )
        assert repo.record([obs]) == 1
        assert repo.series("nikkei225.close", date(2026, 8, 29), date(2026, 8, 29)) == [obs]

    def test_missing_market_value_allowed_as_none(self) -> None:
        """欠測は捏造せずNoneで表現できること（取得不可の原則）。"""
        obs = types.MarketObservation(metric_id="sox.close", value=None, unit="index", as_of=NOW)
        assert obs.value is None
