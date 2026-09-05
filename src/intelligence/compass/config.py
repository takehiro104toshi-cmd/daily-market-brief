"""Compass Generatorの設定読込（Phase 3-C）。

設定値は `config.yaml` の `compass_generator:` セクションに置く（CLAUDE.md:
config値はconfig.yamlへ）。読めない場合は**既定値**で動く（fail-safe）。
credentialはここに置かない（runtime injection only）。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Dict, Mapping, Optional

CONFIG_SECTION = "compass_generator"

DEFAULT_BUDGET: Mapping[str, int] = {"core": 8, "supporting": 8, "optional": 4}


@dataclass(frozen=True)
class CompassConfig:
    generator: str = "deterministic"
    evidence_budget: Mapping[str, int] = field(default_factory=lambda: dict(DEFAULT_BUDGET))
    numeric_tolerance_abs: Decimal = Decimal("0.005")
    historical_level_tolerance_pct: Decimal = Decimal("1.0")
    max_rejected_ratio: Decimal = Decimal("0.5")
    min_counter_contexts: int = 1
    one_liner_min_sentences: int = 2
    one_liner_max_sentences: int = 4
    near_event_days: int = 2
    llm_max_claims: int = 12
    llm_max_claim_chars: int = 200
    llm_max_tokens: int = 1500
    outlook_horizon: str = "next_tokyo_session"

    def as_dict(self) -> Dict[str, object]:
        return {
            "generator": self.generator,
            "evidence_budget": dict(self.evidence_budget),
            "numeric_tolerance_abs": str(self.numeric_tolerance_abs),
            "historical_level_tolerance_pct": str(self.historical_level_tolerance_pct),
            "max_rejected_ratio": str(self.max_rejected_ratio),
            "min_counter_contexts": self.min_counter_contexts,
            "one_liner_sentences": [self.one_liner_min_sentences,
                                    self.one_liner_max_sentences],
            "near_event_days": self.near_event_days,
            "llm_max_claims": self.llm_max_claims,
            "llm_max_claim_chars": self.llm_max_claim_chars,
            "llm_max_tokens": self.llm_max_tokens,
            "outlook_horizon": self.outlook_horizon,
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


def config_from_mapping(section: Optional[Mapping]) -> CompassConfig:
    section = dict(section or {})
    budget = dict(DEFAULT_BUDGET)
    for key, value in (section.get("evidence_budget") or {}).items():
        if key in budget:
            budget[key] = _int(value, budget[key])
    sentences = section.get("one_liner_sentences") or {}
    return CompassConfig(
        generator=str(section.get("generator") or "deterministic"),
        evidence_budget=budget,
        numeric_tolerance_abs=_decimal(section.get("numeric_tolerance_abs"),
                                       Decimal("0.005")),
        historical_level_tolerance_pct=_decimal(
            section.get("historical_level_tolerance_pct"), Decimal("1.0")),
        max_rejected_ratio=_decimal(section.get("max_rejected_ratio"), Decimal("0.5")),
        min_counter_contexts=_int(section.get("min_counter_contexts"), 1),
        one_liner_min_sentences=_int(sentences.get("min"), 2),
        one_liner_max_sentences=_int(sentences.get("max"), 4),
        near_event_days=_int(section.get("near_event_days"), 2),
        llm_max_claims=_int(section.get("llm_max_claims"), 12),
        llm_max_claim_chars=_int(section.get("llm_max_claim_chars"), 200),
        llm_max_tokens=_int(section.get("llm_max_tokens"), 1500),
        outlook_horizon=str(section.get("outlook_horizon") or "next_tokyo_session"),
    )


def load_compass_config(config_path: Path = Path("config.yaml")) -> CompassConfig:
    """config.yaml優先。読めなければ既定値（credentialは一切読まない）。"""
    try:
        import yaml  # 既存依存（PyYAML）

        data = yaml.safe_load(Path(config_path).read_text(encoding="utf-8")) or {}
        return config_from_mapping(data.get(CONFIG_SECTION))
    except Exception:  # noqa: BLE001 設定破損でpipelineを止めない
        return config_from_mapping(None)
