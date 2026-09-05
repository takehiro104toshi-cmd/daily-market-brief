"""Compass Corpus 設定（config.yaml `compass_corpus`）。

CLAUDE.md ルール 8: 設定値は config.yaml に置き、コードへ埋め込まない。
credential は扱わない（Phase 3.7 は offline-first）。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from pathlib import Path
from typing import Any, Dict, Mapping, Optional, Tuple

CONFIG_SECTION = "compass_corpus"

#: Corpus root（<data_root>/compass_corpus）
CORPUS_ROOT_NAME = "compass_corpus"
#: pilot 用 isolated root（production root を触らない）
PILOT_ROOT_NAME = "compass_corpus_pilot"


@dataclass(frozen=True)
class CorpusConfig:
    source_dir: str = ""                       # 承認済み local research area（config で指定。コード非依存）
    inbox_dir: str = ""                        # Phase 3.75 local inbox（未使用・contract のみ）
    document_family: str = "okasan_global_investment_compass"
    family_markers_version: str = "1.0.0"
    family_min_markers: int = 5                # HIGH 判定に必要な page-1 marker 数
    min_pages: int = 3
    max_pages: int = 12
    min_chars_per_page: int = 200              # text layer が薄いページ → LOW_TEXT
    extractor_version: str = "pypdf_text_layer:1.0.0"
    analysis_version: str = "1.0.0"
    coverage_thresholds_version: str = "1.0.0"
    coverage_min_docs_per_label: int = 3       # well_represented の最低本数
    milestones: Tuple[int, ...] = (10, 30, 50, 100, 200)
    inbox_stable_seconds: int = 5
    inbox_stable_samples: int = 2
    alignment_tolerance_pct: Decimal = Decimal("0.05")
    max_statement_chars: int = 200
    max_observations_per_category: int = 40

    def as_dict(self) -> Dict[str, Any]:
        return {
            "source_dir": self.source_dir, "inbox_dir": self.inbox_dir,
            "document_family": self.document_family,
            "family_markers_version": self.family_markers_version,
            "family_min_markers": self.family_min_markers,
            "min_pages": self.min_pages, "max_pages": self.max_pages,
            "min_chars_per_page": self.min_chars_per_page,
            "extractor_version": self.extractor_version,
            "analysis_version": self.analysis_version,
            "coverage_thresholds_version": self.coverage_thresholds_version,
            "coverage_min_docs_per_label": self.coverage_min_docs_per_label,
            "milestones": list(self.milestones),
            "inbox_stable_seconds": self.inbox_stable_seconds,
            "inbox_stable_samples": self.inbox_stable_samples,
            "alignment_tolerance_pct": str(self.alignment_tolerance_pct),
            "max_statement_chars": self.max_statement_chars,
            "max_observations_per_category": self.max_observations_per_category,
        }


def config_from_mapping(section: Optional[Mapping[str, Any]]) -> CorpusConfig:
    s = dict(section or {})
    base = CorpusConfig()

    def _int(key: str, default: int) -> int:
        try:
            return int(s.get(key, default))
        except (TypeError, ValueError):
            return default

    milestones = s.get("milestones") or list(base.milestones)
    try:
        milestones_t = tuple(sorted({int(m) for m in milestones}))
    except (TypeError, ValueError):
        milestones_t = base.milestones
    try:
        tol = Decimal(str(s.get("alignment_tolerance_pct", base.alignment_tolerance_pct)))
    except Exception:  # noqa: BLE001 設定破損で corpus 層を止めない
        tol = base.alignment_tolerance_pct
    return CorpusConfig(
        source_dir=str(s.get("source_dir", base.source_dir) or ""),
        inbox_dir=str(s.get("inbox_dir", base.inbox_dir) or ""),
        document_family=str(s.get("document_family", base.document_family)),
        family_markers_version=str(s.get("family_markers_version", base.family_markers_version)),
        family_min_markers=_int("family_min_markers", base.family_min_markers),
        min_pages=_int("min_pages", base.min_pages),
        max_pages=_int("max_pages", base.max_pages),
        min_chars_per_page=_int("min_chars_per_page", base.min_chars_per_page),
        extractor_version=str(s.get("extractor_version", base.extractor_version)),
        analysis_version=str(s.get("analysis_version", base.analysis_version)),
        coverage_thresholds_version=str(s.get("coverage_thresholds_version",
                                             base.coverage_thresholds_version)),
        coverage_min_docs_per_label=_int("coverage_min_docs_per_label",
                                         base.coverage_min_docs_per_label),
        milestones=milestones_t or base.milestones,
        inbox_stable_seconds=_int("inbox_stable_seconds", base.inbox_stable_seconds),
        inbox_stable_samples=_int("inbox_stable_samples", base.inbox_stable_samples),
        alignment_tolerance_pct=tol,
        max_statement_chars=_int("max_statement_chars", base.max_statement_chars),
        max_observations_per_category=_int("max_observations_per_category",
                                           base.max_observations_per_category),
    )


def load_corpus_config(config_path: Path = Path("config.yaml")) -> CorpusConfig:
    """config.yaml の `compass_corpus` を読む（無ければ既定値）。"""
    section: Mapping[str, Any] = {}
    if config_path.is_file():
        try:
            import yaml  # 既存依存（PyYAML）

            raw = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
            section = raw.get(CONFIG_SECTION) or {}
        except Exception:  # noqa: BLE001
            section = {}
    return config_from_mapping(section)
