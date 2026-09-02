"""Bounded inbox processor（Phase 3.75 §10–§14）。

    discover → stability check → lock → IntakeRequest → CompassIntakeService.submit()
    → result ledger → status → release lock

Corpus のロジックは複製しない（validation / dedup / analysis は Phase 3.7 の intake が行う）。
- 転送中（size 変化 / mtime が新しい / open 不可 / placeholder）は **WAITING_UNSTABLE**。
  timeout（config unstable_timeout_minutes）を超えたときだけ FAILED(TIMEOUT_UNSTABLE)。
- 同一 hash は DUPLICATE（無害）。ledger 済み hash は再処理しない。
- bounded: max_files_per_run / time_budget_seconds / single-instance lock。busy wait なし。
- 原本を削除・移動しない。log / status に full path を出さない。
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Callable, Dict, List, Optional, Set, Tuple

from ..corpus.config import CorpusConfig, load_corpus_config
from ..corpus.extraction import ExtractorUnavailable, PypdfExtractor, TextLayerExtractor, ensure_extractor_available
from ..corpus.identity import sha256_file
from ..corpus.inbox import is_stable, sample_file
from ..corpus.intake import ACCEPTED, SOURCE_INBOX, SOURCE_MOBILE_UPLOAD, CompassIntakeService, IntakeRequest
from ..corpus.store import CorpusStore, corpus_root
from .adapters import LOCAL_FOLDER, SyncFolderAdapter
from .config import MobileIntakeConfig, load_mobile_intake_config
from .local_config import LocalConfig, load_local_config, logical_locator, redact_path
from .result import (
    DUPLICATE,
    FAILED,
    HINTS_JA,
    QUARANTINED,
    R_EXTRACTOR_UNAVAILABLE,
    R_INTERNAL_ERROR,
    R_LOCKED,
    R_SYNC_NOT_AVAILABLE,
    R_SYNC_PLACEHOLDER,
    R_TIMEOUT_UNSTABLE,
    R_UNSTABLE_TRANSFER,
    SUCCESS,
    WAITING_UNSTABLE,
    ProcessingResult,
    reason_from_corpus,
)
from .scheduler import acquire_instance_lock, release_instance_lock
from .status import corpus_count, milestone_feedback, render_idle_ja, render_result_ja, write_status

STATE_FILE = "state.json"
LEDGER_FILE = "intake_ledger.jsonl"
LOCK_DIR = "locks"
FINAL_RESULTS = (SUCCESS, DUPLICATE, QUARANTINED, FAILED)

Sampler = Callable[[Path], Tuple[int, float]]
Sleeper = Callable[[float], None]


@dataclass
class ProcessorReport:
    started_at: str
    provider: str
    inbox: str                                   # redacted
    sync_available: bool = True
    single_instance_acquired: bool = True
    candidates: int = 0
    placeholders: int = 0
    skipped_processed: int = 0
    skipped_locked: int = 0
    corpus_before: int = 0
    corpus_after: int = 0
    bounded_by: str = ""
    duration_seconds: float = 0.0
    environment_error: str = ""                  # EXTRACTOR_UNAVAILABLE 等。Corpus / ledger には何も書いていない
    status_written: List[str] = field(default_factory=list)
    results: List[ProcessingResult] = field(default_factory=list)

    def counts(self) -> Dict[str, int]:
        out: Dict[str, int] = {}
        for r in self.results:
            out[r.result] = out.get(r.result, 0) + 1
        return out

    def as_dict(self) -> Dict[str, object]:
        return {"started_at": self.started_at, "provider": self.provider, "inbox": self.inbox,
                "sync_available": self.sync_available,
                "single_instance_acquired": self.single_instance_acquired,
                "candidates": self.candidates, "placeholders": self.placeholders,
                "skipped_processed": self.skipped_processed, "skipped_locked": self.skipped_locked,
                "corpus_before": self.corpus_before, "corpus_after": self.corpus_after,
                "bounded_by": self.bounded_by, "duration_seconds": round(self.duration_seconds, 3),
                "environment_error": self.environment_error,
                "status_written": list(self.status_written), "counts": self.counts(),
                "results": [r.as_dict() for r in self.results]}


class InboxProcessor:
    def __init__(self, config: MobileIntakeConfig, local: LocalConfig, corpus_config: CorpusConfig,
                 store: CorpusStore, extractor: TextLayerExtractor, *,
                 sampler: Sampler = sample_file, sleeper: Sleeper = time.sleep,
                 now_fn: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
                 post_ingest: Optional[Callable[[str], Dict[str, object]]] = None) -> None:
        self.config = config
        self.post_ingest = post_ingest          # Phase 3.8 event boundary（SUCCESS 後に呼ぶ。失敗しても ingestion は不変）
        self.local = local
        self.corpus_config = corpus_config
        self.store = store
        self.service = CompassIntakeService(store, corpus_config, extractor,
                                            recover_environment_failures=config.recover_environment_failures)
        self.sampler = sampler
        self.sleeper = sleeper
        self.now_fn = now_fn
        self.home = Path(local.home)
        self.home.mkdir(parents=True, exist_ok=True)
        self.adapter = SyncFolderAdapter(local.provider, Path(local.inbox_dir) if local.inbox_dir else Path(""),
                                         config.status_dir_name)
        self.source_type = SOURCE_INBOX if local.provider == LOCAL_FOLDER else SOURCE_MOBILE_UPLOAD

    # ------------------------------------------------------------- state / ledger
    @property
    def state_path(self) -> Path:
        return self.home / STATE_FILE

    @property
    def ledger_path(self) -> Path:
        return self.home / LEDGER_FILE

    def _state(self) -> Dict[str, Dict[str, str]]:
        if not self.state_path.is_file():
            return {"first_seen": {}}
        try:
            data = json.loads(self.state_path.read_text(encoding="utf-8")) or {}
        except (OSError, json.JSONDecodeError):
            data = {}
        data.setdefault("first_seen", {})
        return data

    def _save_state(self, data: Dict) -> None:
        self.state_path.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")

    def _first_seen(self, name: str, now: datetime) -> datetime:
        data = self._state()
        seen = data["first_seen"].get(name)
        if seen:
            try:
                return datetime.fromisoformat(seen)
            except ValueError:
                pass
        data["first_seen"][name] = now.isoformat()
        self._save_state(data)
        return now

    def _forget(self, name: str) -> None:
        data = self._state()
        if name in data["first_seen"]:
            del data["first_seen"][name]
            self._save_state(data)

    def processed_hashes(self) -> Set[str]:
        """ledger で最終結果が付いた hash。"""
        return {sha for sha, _ in self.processed_keys()}

    def processed_keys(self) -> Set[Tuple[str, str]]:
        """(sha256, file) — **同じファイル名で同じ bytes** だけを再処理しない。
        別名で届いた同一 bytes は intake に渡し DUPLICATE として **ユーザーに見せる**（§13）。"""
        out: Set[Tuple[str, str]] = set()
        if not self.ledger_path.is_file():
            return out
        with self.ledger_path.open(encoding="utf-8") as handle:
            for line in handle:
                line = line.strip()
                if not line:
                    continue
                try:
                    d = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if d.get("result") in FINAL_RESULTS and d.get("sha256"):
                    out.add((str(d["sha256"]), str(d.get("file", ""))))
        return out

    def ledger_entries(self) -> List[Dict]:
        if not self.ledger_path.is_file():
            return []
        out = []
        for line in self.ledger_path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                try:
                    out.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
        return out

    def _ledger(self, result: ProcessingResult, now: datetime) -> None:
        entry = result.as_dict()
        entry["ledger_id"] = "cml_" + hashlib.sha1(
            f"{result.sha256}|{result.file}|{now.isoformat()}|{result.result}".encode("utf-8")).hexdigest()[:16]
        entry["at"] = now.isoformat()
        entry["locator"] = logical_locator(Path(result.file))
        with self.ledger_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(entry, ensure_ascii=False, default=str) + "\n")

    # ------------------------------------------------------------- per-file lock（crash recovery）
    def _file_lock(self, path: Path, now: datetime) -> Optional[Path]:
        lock_dir = self.home / LOCK_DIR
        lock_dir.mkdir(parents=True, exist_ok=True)
        lock = lock_dir / (path.name + ".lock")
        if lock.exists():
            try:
                age = now.timestamp() - lock.stat().st_mtime
            except OSError:
                age = 0
            if age > self.config.stale_lock_minutes * 60:
                try:
                    lock.unlink()                         # crash の残骸を回収（intake は idempotent）
                except OSError:
                    return None
            else:
                return None
        try:
            fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError:
            return None
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(now.isoformat())
        return lock

    @staticmethod
    def _openable(path: Path) -> bool:
        try:
            with path.open("rb") as handle:
                handle.read(8)
            return True
        except OSError:                                  # 同期クライアントが書き込み中（Windows で PermissionError）
            return False

    def _stable(self, path: Path, now: datetime) -> bool:
        try:
            samples = [self.sampler(path)]
            for _ in range(self.config.stable_samples - 1):
                if self.config.sample_interval_seconds > 0:
                    self.sleeper(self.config.sample_interval_seconds)
                samples.append(self.sampler(path))
        except OSError:
            return False
        return is_stable(samples, now.timestamp(), self.config.stable_seconds) and self._openable(path)

    # ------------------------------------------------------------- run
    def _status_dirs(self) -> List[Path]:
        dirs = [self.home]
        if self.config.status_in_inbox and self.local.inbox_dir:
            dirs.append(Path(self.local.inbox_dir) / self.config.status_dir_name)
        return dirs

    def _result(self, result: str, path: Path, reason: str, *, now: datetime, sha: str = "",
                document_id: str = "", document_date: str = "", before: int, after: int,
                duration: float, quality: str = "", milestone: Optional[Dict] = None) -> ProcessingResult:
        return ProcessingResult(
            result=result, file=path.name, sha256=sha, document_id=document_id,
            document_date=document_date, received_at=now.isoformat(), reason_code=reason,
            hint=HINTS_JA.get(reason, ""), processing_duration_seconds=duration,
            corpus_count_before=before, corpus_count_after=after,
            milestone=milestone or milestone_feedback(after, self.corpus_config.milestones),
            quality=quality)

    def run_once(self, now: Optional[datetime] = None) -> ProcessorReport:
        now = now or self.now_fn()
        if now.tzinfo is None:
            now = now.replace(tzinfo=timezone.utc)
        t0 = time.monotonic()
        day = now.astimezone(timezone(timedelta(hours=9))).date().isoformat()
        report = ProcessorReport(started_at=now.isoformat(), provider=self.local.provider,
                                 inbox=redact_path(self.local.inbox_dir) if self.local.inbox_dir else "")
        before = corpus_count(self.store)
        report.corpus_before = before
        report.corpus_after = before
        ms = milestone_feedback(before, self.corpus_config.milestones)
        if self.local.inbox_dir is None or not self.adapter.exists():
            report.sync_available = False
            text = "\n".join([day, "Inbox に到達できません", HINTS_JA[R_SYNC_NOT_AVAILABLE]])
            report.status_written = [redact_path(p) for p in write_status(
                [self.home], text, {"result": FAILED, "reason_code": R_SYNC_NOT_AVAILABLE,
                                    "at": now.isoformat(), "milestone": ms})]
            report.duration_seconds = time.monotonic() - t0
            return report

        try:
            ensure_extractor_available(self.service.extractor)      # precondition gate: ファイルを 1 件も触る前に止める
        except ExtractorUnavailable as exc:
            report.environment_error = f"{R_EXTRACTOR_UNAVAILABLE}:{exc}"
            text = "\n".join([day, "環境エラー: PDF 抽出ライブラリ未インストール", HINTS_JA[R_EXTRACTOR_UNAVAILABLE]])
            report.status_written = [redact_path(p) for p in write_status(
                self._status_dirs(), text, {"result": FAILED, "reason_code": R_EXTRACTOR_UNAVAILABLE,
                                            "hint": HINTS_JA[R_EXTRACTOR_UNAVAILABLE], "at": now.isoformat(),
                                            "milestone": ms, "corpus_written": False})]
            report.duration_seconds = time.monotonic() - t0
            return report
        instance = acquire_instance_lock(self.home, self.config.stale_lock_minutes, now)
        if instance is None:
            report.single_instance_acquired = False
            report.duration_seconds = time.monotonic() - t0
            return report
        try:
            candidates, placeholders = self.adapter.discover()
            report.candidates = len(candidates)
            report.placeholders = len(placeholders)
            processed = self.processed_keys()
            handled = 0
            pending = 0
            for path, reason in placeholders:
                pending += 1
                report.results.append(self._result(WAITING_UNSTABLE, path, R_SYNC_PLACEHOLDER, now=now,
                                                   before=before, after=report.corpus_after, duration=0.0))
            for path in candidates:
                if handled >= self.config.max_files_per_run:
                    report.bounded_by = "max_files_per_run"
                    break
                if time.monotonic() - t0 > self.config.time_budget_seconds:
                    report.bounded_by = "time_budget_seconds"
                    break
                if not self._stable(path, now):
                    first = self._first_seen(path.name, now)
                    if now - first > timedelta(minutes=self.config.unstable_timeout_minutes):
                        res = self._result(FAILED, path, R_TIMEOUT_UNSTABLE, now=now, before=before,
                                           after=report.corpus_after, duration=0.0)
                        self._ledger(res, now)
                        self._forget(path.name)
                        report.results.append(res)
                        handled += 1
                    else:
                        pending += 1
                        report.results.append(self._result(WAITING_UNSTABLE, path, R_UNSTABLE_TRANSFER,
                                                           now=now, before=before,
                                                           after=report.corpus_after, duration=0.0))
                    continue
                sha = sha256_file(path)
                if (sha, path.name) in processed:
                    report.skipped_processed += 1
                    self._forget(path.name)
                    continue
                lock = self._file_lock(path, now)
                if lock is None:
                    report.skipped_locked += 1
                    report.results.append(self._result(WAITING_UNSTABLE, path, R_LOCKED, now=now,
                                                       before=before, after=report.corpus_after,
                                                       duration=0.0, sha=sha))
                    continue
                t1 = time.monotonic()
                try:
                    outcome = self.service.submit(IntakeRequest(
                        path=path, original_filename=path.name, source_type=self.source_type,
                        received_at=now, channel=self.local.provider.lower()))
                    after = corpus_count(self.store)
                    if outcome.status == ACCEPTED:
                        result = SUCCESS
                    elif outcome.status in (DUPLICATE, QUARANTINED, FAILED):
                        result = outcome.status
                    else:
                        result = FAILED
                    reason = reason_from_corpus(outcome.status if outcome.status != ACCEPTED else SUCCESS,
                                                outcome.reasons)
                    doc = self.store.document(outcome.document_id) if outcome.document_id else None
                    milestone = milestone_feedback(after, self.corpus_config.milestones)
                    milestone["reached_now"] = bool(
                        milestone_feedback(before, self.corpus_config.milestones)["reached"] != milestone["reached"])
                    res = self._result(result, path, reason, now=now, sha=sha,
                                       document_id=outcome.document_id,
                                       document_date=doc.document_date if doc else "",
                                       before=before, after=after, duration=time.monotonic() - t1,
                                       quality=outcome.quality, milestone=milestone)
                    report.corpus_after = after
                    before = after
                except ExtractorUnavailable as exc:                 # environment failure: ledger に FAILED を書かず停止
                    report.environment_error = f"{R_EXTRACTOR_UNAVAILABLE}:{exc}"
                    res = None
                except Exception as exc:  # noqa: BLE001 型名のみ（本文・path を出さない）
                    res = self._result(FAILED, path, R_INTERNAL_ERROR, now=now, sha=sha, before=before,
                                       after=report.corpus_after, duration=time.monotonic() - t1)
                    res = ProcessingResult(**{**res.__dict__, "hint": f"{HINTS_JA[R_INTERNAL_ERROR]} ({type(exc).__name__})"})
                finally:
                    try:
                        lock.unlink()
                    except OSError:
                        pass
                if res is None:
                    break
                if self.post_ingest is not None and res.result == SUCCESS and res.document_id:
                    try:
                        research = self.post_ingest(res.document_id)
                    except Exception as exc:  # noqa: BLE001 研究側の失敗は Corpus 結果を変えない
                        research = {"corpus": "CORPUS_SUCCESS", "research": "RESEARCH_ANALYSIS_FAILED",
                                    "error_type": type(exc).__name__}
                    res = ProcessingResult(**{**res.__dict__, "research": dict(research or {})})
                self._ledger(res, now)
                self._forget(path.name)
                processed.add((sha, path.name))
                report.results.append(res)
                handled += 1

            final = [r for r in report.results if r.result in FINAL_RESULTS]
            if final:
                last = final[-1]
                text = render_result_ja(last, day)
                payload = {**last.as_dict(), "at": now.isoformat(), "pending": pending}
            else:
                ms = milestone_feedback(report.corpus_after, self.corpus_config.milestones)
                text = render_idle_ja(day, ms, pending)
                payload = {"result": WAITING_UNSTABLE if pending else "IDLE", "pending": pending,
                           "at": now.isoformat(), "milestone": ms, "corpus_count_after": report.corpus_after}
            report.status_written = [redact_path(p) for p in write_status(self._status_dirs(), text, payload)]
        finally:
            release_instance_lock(instance)
        report.duration_seconds = time.monotonic() - t0
        return report


def build_processor(*, inbox: Optional[str] = None, data_root_dir: Optional[str] = None,
                    home: Optional[str] = None, env=None) -> InboxProcessor:
    config = load_mobile_intake_config()
    corpus_config = load_corpus_config()
    environ = dict(os.environ if env is None else env)
    if inbox:
        environ["COMPASS_INBOX_DIR"] = inbox
    if data_root_dir:
        environ["INTELLIGENCE_DATA_ROOT"] = data_root_dir
    local = load_local_config(config, env=environ, home=Path(home) if home else None)
    store = CorpusStore(corpus_root(local.data_root))
    hook = None
    if config.trigger_research:
        from ..corpus_research.intake_hook import make_post_ingest_hook   # lazy: adapter は research を知らない

        hook = make_post_ingest_hook(local.data_root)
    return InboxProcessor(config, local, corpus_config, store, PypdfExtractor(corpus_config.extractor_version),
                          post_ingest=hook)


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Compass mobile intake processor (bounded single run)")
    parser.add_argument("--once", action="store_true", default=True, help="1 回だけ処理（既定）")
    parser.add_argument("--inbox", default="", help="Inbox dir の上書き（通常は env / local config）")
    parser.add_argument("--data-root", default="", help="INTELLIGENCE_DATA_ROOT の上書き")
    parser.add_argument("--home", default="", help="機械ローカル home の上書き")
    parser.add_argument("--json", action="store_true", help="report を JSON で出力")
    args = parser.parse_args(argv)
    proc = build_processor(inbox=args.inbox or None, data_root_dir=args.data_root or None,
                           home=args.home or None)
    try:
        report = proc.run_once()
    finally:
        proc.store.close()
    if args.json:
        print(json.dumps(report.as_dict(), ensure_ascii=False, default=str))
    else:
        counts = report.counts()
        print(f"[compass-intake] inbox={report.inbox} sync={report.sync_available} "
              f"candidates={report.candidates} results={counts} corpus={report.corpus_before}->{report.corpus_after}")
    if report.environment_error:
        print(f"[compass-intake] ENVIRONMENT FAILURE: {report.environment_error} — nothing written to the corpus")
        return 2
    return 0 if report.sync_available else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
