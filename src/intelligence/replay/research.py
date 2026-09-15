"""Incremental research replay（Phase 3.9.4）— Phase 3.8 `run_incremental` を replay primitive として使う。

空の一時 ResearchStore に canonical 順で文書を足し、prefix が進むたびに incremental 実行する。
0 から rebuild し直すことはしない（O(N³) 回避）。粗い position で research store を checkpoint copy し、
遷移区間の精密化は checkpoint 復元から 1 文書ずつ前進する。milestone では full rebuild と等価性を検証する。
"""
from __future__ import annotations

import shutil
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, Optional, Sequence

from ..corpus.config import CorpusConfig
from ..corpus_research.config import ResearchConfig
from ..corpus_research.engine import ResearchEngine
from ..corpus_research.regime import MarketConnector
from ..corpus_research.store import ResearchStore
from .errors import ReplayIncompleteSnapshot, ReplayRebuildMismatch, ReplayTempCorrupt
from .view import ReplayCorpusView


class ReplayResearchDriver:
    def __init__(self, view: ReplayCorpusView, research_dir: Path, checkpoint_dir: Path,
                 rconfig: ResearchConfig, cconfig: CorpusConfig, connector: MarketConnector,
                 run_created_at: datetime, rules_path: Optional[Path] = None) -> None:
        self.view = view
        self.research_dir = Path(research_dir)
        self.checkpoint_dir = Path(checkpoint_dir)
        self.rconfig = rconfig
        self.cconfig = cconfig
        self.connector = connector
        self.run_created_at = run_created_at
        self.rules_path = rules_path
        self.research_dir.mkdir(parents=True, exist_ok=True)
        self.checkpoint_dir.mkdir(parents=True, exist_ok=True)
        self._store: Optional[ResearchStore] = None
        self._engine: Optional[ResearchEngine] = None
        self.runs = 0
        # run_incremental が step 6 で計算した derived digest。snapshot の research_digest はこれを再利用し、
        # 同じ derived view を position ごとに再 canonicalize しない（値は store.digest() と同一・test で固定）。
        self.last_digest: str = ""
        self.counters: Dict[str, int] = {"run_incremental_calls": 0, "documents_analyzed": 0,
                                         "checkpoints": 0, "restores": 0, "rebuilds": 0}

    # ------------------------------------------------------------- engine lifecycle
    def _reset_engine(self) -> None:
        self._store = ResearchStore(self.research_dir)
        self._engine = ResearchEngine(self.view, self._store, self.rconfig, self.cconfig, self.connector,
                                      rules_path=self.rules_path)

    @property
    def store(self) -> ResearchStore:
        if self._store is None:
            self._reset_engine()
        return self._store  # type: ignore[return-value]

    @property
    def engine(self) -> ResearchEngine:
        if self._engine is None:
            self._reset_engine()
        return self._engine  # type: ignore[return-value]

    def fixed_now(self, step: int) -> datetime:
        """wall clock に依存しない決定的 now（run_created_at + step 秒）。"""
        return self.run_created_at + timedelta(seconds=int(step))

    # ------------------------------------------------------------- forward replay
    def advance(self, document_ids: Sequence[str], step: int) -> Dict[str, object]:
        """prefix を document_ids まで広げ、incremental research を 1 回実行する。"""
        self.view.allow(document_ids)
        report = self.engine.run_incremental(self.fixed_now(step))
        self.runs += 1
        self.counters["run_incremental_calls"] += 1
        self.counters["documents_analyzed"] += len(document_ids)
        self.last_digest = str(report.digest or "")
        if report.errors:
            raise ReplayIncompleteSnapshot(f"research run reported errors: {sorted(report.errors)[:5]}")
        structures = self.store.current_structures(self.rconfig.version_key)
        expected = len(self.view.allowed)
        if len(structures) != expected:
            raise ReplayIncompleteSnapshot(
                f"structures {len(structures)} != usable prefix {expected} (analyzer skipped documents)")
        return report.as_dict()

    # ------------------------------------------------------------- checkpoints
    def checkpoint(self, position: int) -> Path:
        target = self.checkpoint_dir / f"pos_{position:05d}"
        if target.exists():
            shutil.rmtree(target)
        shutil.copytree(self.research_dir, target)
        (target / "ALLOWED.txt").write_text("\n".join(sorted(self.view.allowed)), encoding="utf-8")
        (target / "DIGEST.txt").write_text(self.last_digest, encoding="utf-8")
        self.counters["checkpoints"] += 1
        return target

    def restore(self, position: int) -> None:
        source = self.checkpoint_dir / f"pos_{position:05d}"
        allowed_file = source / "ALLOWED.txt"
        if not source.is_dir() or not allowed_file.is_file():
            raise ReplayTempCorrupt(f"checkpoint for position {position} missing or incomplete")
        shutil.rmtree(self.research_dir)
        shutil.copytree(source, self.research_dir)
        (self.research_dir / "ALLOWED.txt").unlink(missing_ok=True)
        (self.research_dir / "DIGEST.txt").unlink(missing_ok=True)
        allowed = [line for line in allowed_file.read_text(encoding="utf-8").splitlines() if line]
        self.view.restrict(allowed)
        digest_file = source / "DIGEST.txt"
        self.last_digest = digest_file.read_text(encoding="utf-8").strip() if digest_file.is_file() else ""
        self.counters["restores"] += 1
        self._reset_engine()                          # 旧 in-memory cache を捨てる

    def research_digest(self) -> str:
        """現在の research 状態の derived digest（`ResearchStore.digest` と同値）。

        run_incremental が返した digest を再利用する。checkpoint 復元直後など値が無いときだけ再計算する。
        """
        if self.last_digest:
            return self.last_digest
        self.last_digest = self.store.digest(self.rconfig.version_key, self.rconfig.pattern_version,
                                             self.rconfig.similarity_version)
        return self.last_digest

    # ------------------------------------------------------------- equivalence
    def verify_rebuild_equivalence(self, position: int, rebuild_dir: Path, step: int) -> Dict[str, object]:
        """同じ prefix に対する full rebuild と incremental の derived digest を比較する。不一致は fail closed。"""
        rebuild_dir = Path(rebuild_dir)
        if rebuild_dir.exists():
            shutil.rmtree(rebuild_dir)
        rebuilt, report = self.engine.run_full_rebuild(rebuild_dir, self.fixed_now(step))
        self.counters["rebuilds"] += 1
        if report.errors:
            raise ReplayIncompleteSnapshot(f"full rebuild at position {position} reported errors")
        result = self.engine.equivalence(rebuilt)
        if not result.get("equal"):
            raise ReplayRebuildMismatch(
                f"incremental research != full rebuild at eligible position {position}: "
                f"differing sections {result.get('differing_sections')}")
        return {"position": position, **{k: v for k, v in result.items() if k != "differing_sections"}}
