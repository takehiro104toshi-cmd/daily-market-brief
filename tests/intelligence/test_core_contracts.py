"""core/contracts.py の契約テスト（schema 0.2.0版）。

Evidence/Marketリポジトリ契約の実体検証は test_evidence_store.py
（JsonlEvidenceStoreが両Protocolを充足）が担う。ここでは残る契約
（Clock / LLMProvider / NewsRepository / KnowledgeRepository）の実装可能性と
provider中立性を検証する。
"""
from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Mapping, Sequence

import pytest

from src.intelligence.core import contracts, types

NOW = datetime(2026, 8, 29, 7, 30, tzinfo=timezone.utc)


class _FixedClock:
    def now(self) -> datetime:
        return NOW


class _NullLLM:
    def is_available(self) -> bool:
        return False

    def complete(self, prompt: str, *, system: str = "", max_tokens: int = 1024) -> types.LLMResult:
        return types.LLMResult(text="", provider="null", model="none")


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


@pytest.mark.parametrize(
    "impl,protocol",
    [
        (_FixedClock(), contracts.Clock),
        (_NullLLM(), contracts.LLMProvider),
        (_MemoryNewsRepo(), contracts.NewsRepository),
        (_StaticKnowledgeRepo(), contracts.KnowledgeRepository),
    ],
)
def test_dummy_satisfies_protocol(impl, protocol) -> None:
    assert isinstance(impl, protocol)


def test_clock_returns_aware_datetime() -> None:
    assert _FixedClock().now().tzinfo is not None


def test_llm_result_is_provider_metadata_only() -> None:
    """provider/modelは実行metadata文字列であり、core domainはSDK型に依存しない。"""
    result = _NullLLM().complete("x")
    assert result.provider == "null"
    assert isinstance(result.model, str)
    assert result.input_evidence_ids == ()


def test_confidence_ladder_bounds() -> None:
    assert types.validate_confidence(0) == 0
    assert types.validate_confidence(5) == 5
    with pytest.raises(ValueError):
        types.validate_confidence(6)


def test_verification_states_cover_spec() -> None:
    values = {s.value for s in types.VerificationState}
    assert values == {
        "unverified", "verified", "conflicting", "stale", "retracted", "unsupported"
    }
