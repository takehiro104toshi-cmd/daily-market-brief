"""Research analyzer の versions / thresholds（config.yaml `compass_research`）。magic number をコードに埋めない。"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import Any, Dict, Mapping, Optional

CONFIG_SECTION = "compass_research"
RESEARCH_ROOT_NAME = "compass_research"


@dataclass(frozen=True)
class ResearchConfig:
    structure_analyzer_version: str = "1.0.0"
    salience_version: str = "1.0.0"
    link_version: str = "1.0.0"
    why_version: str = "1.0.0"
    outlook_classifier_version: str = "1.0.0"
    risk_classifier_version: str = "1.0.0"
    similarity_version: str = "1.0.0"
    pattern_version: str = "1.0.0"
    lifecycle_thresholds_version: str = "1.0.0"
    benchmark_version: str = "1.0.0"
    dna_rules_path: str = "knowledge/compass_dna/market_rules.yaml"
    similarity_top_k: int = 3
    similarity_min_score: Decimal = Decimal("0.30")
    pattern_evidence_categories: int = 2          # pattern component に使う salient evidence category 数
    new_candidate_support: int = 2
    review_support: int = 3
    review_regimes: int = 2
    review_span_days: int = 30
    strong_support: int = 5
    strong_regimes: int = 3
    strong_span_days: int = 90
    strong_min_valid_ratio: Decimal = Decimal("1.0")
    research_retry_max_attempts: int = 2
    batch_max_files: int = 20
    corpus_size_caveat_below: int = 30            # eligible がこれ未満なら全結論に corpus-size limitation を付ける

    @property
    def version_key(self) -> str:
        return "|".join((self.structure_analyzer_version, self.salience_version, self.link_version,
                         self.why_version, self.outlook_classifier_version,
                         self.risk_classifier_version, self.similarity_version,
                         self.pattern_version, self.lifecycle_thresholds_version,
                         self.benchmark_version))

    def versions(self) -> Dict[str, str]:
        return {"structure_analyzer_version": self.structure_analyzer_version,
                "salience_version": self.salience_version, "link_version": self.link_version,
                "why_version": self.why_version,
                "outlook_classifier_version": self.outlook_classifier_version,
                "risk_classifier_version": self.risk_classifier_version,
                "similarity_version": self.similarity_version,
                "pattern_version": self.pattern_version,
                "lifecycle_thresholds_version": self.lifecycle_thresholds_version,
                "benchmark_version": self.benchmark_version}

    def thresholds(self) -> Dict[str, Any]:
        return {"version": self.lifecycle_thresholds_version,
                "new_candidate": {"support": self.new_candidate_support},
                "review_candidate": {"support": self.review_support, "regimes": self.review_regimes,
                                     "span_days": self.review_span_days},
                "strong_candidate": {"support": self.strong_support, "regimes": self.strong_regimes,
                                     "span_days": self.strong_span_days,
                                     "min_valid_ratio": str(self.strong_min_valid_ratio)},
                "corpus_size_caveat_below": self.corpus_size_caveat_below}

    def as_dict(self) -> Dict[str, Any]:
        return {**self.versions(), "dna_rules_path": self.dna_rules_path,
                "similarity_top_k": self.similarity_top_k,
                "similarity_min_score": str(self.similarity_min_score),
                "pattern_evidence_categories": self.pattern_evidence_categories,
                "thresholds": self.thresholds(),
                "research_retry_max_attempts": self.research_retry_max_attempts,
                "batch_max_files": self.batch_max_files}


def config_from_mapping(section: Optional[Mapping[str, Any]]) -> ResearchConfig:
    s = dict(section or {})
    base = ResearchConfig()

    def _str(key: str, default: str) -> str:
        return str(s.get(key, default) or default)

    def _int(key: str, default: int) -> int:
        try:
            return int(s.get(key, default))
        except (TypeError, ValueError):
            return default

    def _dec(key: str, default: Decimal) -> Decimal:
        try:
            return Decimal(str(s.get(key, default)))
        except Exception:  # noqa: BLE001
            return default

    return ResearchConfig(
        structure_analyzer_version=_str("structure_analyzer_version", base.structure_analyzer_version),
        salience_version=_str("salience_version", base.salience_version),
        link_version=_str("link_version", base.link_version),
        why_version=_str("why_version", base.why_version),
        outlook_classifier_version=_str("outlook_classifier_version", base.outlook_classifier_version),
        risk_classifier_version=_str("risk_classifier_version", base.risk_classifier_version),
        similarity_version=_str("similarity_version", base.similarity_version),
        pattern_version=_str("pattern_version", base.pattern_version),
        lifecycle_thresholds_version=_str("lifecycle_thresholds_version", base.lifecycle_thresholds_version),
        benchmark_version=_str("benchmark_version", base.benchmark_version),
        dna_rules_path=_str("dna_rules_path", base.dna_rules_path),
        similarity_top_k=max(1, _int("similarity_top_k", base.similarity_top_k)),
        similarity_min_score=_dec("similarity_min_score", base.similarity_min_score),
        pattern_evidence_categories=max(1, _int("pattern_evidence_categories", base.pattern_evidence_categories)),
        new_candidate_support=max(2, _int("new_candidate_support", base.new_candidate_support)),
        review_support=_int("review_support", base.review_support),
        review_regimes=_int("review_regimes", base.review_regimes),
        review_span_days=_int("review_span_days", base.review_span_days),
        strong_support=_int("strong_support", base.strong_support),
        strong_regimes=_int("strong_regimes", base.strong_regimes),
        strong_span_days=_int("strong_span_days", base.strong_span_days),
        strong_min_valid_ratio=_dec("strong_min_valid_ratio", base.strong_min_valid_ratio),
        research_retry_max_attempts=max(1, _int("research_retry_max_attempts", base.research_retry_max_attempts)),
        batch_max_files=max(1, _int("batch_max_files", base.batch_max_files)),
        corpus_size_caveat_below=_int("corpus_size_caveat_below", base.corpus_size_caveat_below))


def load_research_config(config_path: Path = Path("config.yaml")) -> ResearchConfig:
    section: Mapping[str, Any] = {}
    if config_path.is_file():
        try:
            import yaml

            raw = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
            section = raw.get(CONFIG_SECTION) or {}
        except Exception:  # noqa: BLE001
            section = {}
    return config_from_mapping(section)
