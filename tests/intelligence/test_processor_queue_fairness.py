"""Processor queue fairness / scalability（既処理 file の走査で time budget を使い切る starvation の再発防止）。

44 / 120 / 200 known + 1 new（sort 末尾・先頭）/ known-only 再実行で stability sampling 0 /
max_files=20 で >20 新規 / actionable work による time budget 消費 / ledger 後に変更された file は skip しない /
unstable 新規 / placeholder / duplicate・idempotency / Phase 3.8 hook exactly once。
"""
from __future__ import annotations

import dataclasses
import importlib.util
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from src.intelligence.corpus.config import CorpusConfig
from src.intelligence.corpus.extraction import FakeExtractor
from src.intelligence.corpus.intake import SOURCE_HISTORICAL_IMPORT
from src.intelligence.corpus.pipeline import ingest_path
from src.intelligence.corpus.store import CorpusStore
from src.intelligence.mobile_intake import adapters
from src.intelligence.mobile_intake import processor as procmod
from src.intelligence.mobile_intake import result as res
from src.intelligence.mobile_intake.config import MobileIntakeConfig
from src.intelligence.mobile_intake.local_config import LocalConfig
from src.intelligence.mobile_intake.processor import InboxProcessor

_spec = importlib.util.spec_from_file_location("_corpus_helpers", Path(__file__).with_name("test_compass_corpus.py"))
_helpers = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_helpers)
compass_pages, make_pdf = _helpers.compass_pages, _helpers.make_pdf

NOW = datetime(2026, 9, 3, 6, 0, tzinfo=timezone.utc)
CCFG = CorpusConfig()
CFG = MobileIntakeConfig(max_files_per_run=20, sample_interval_seconds=1.0, stable_seconds=20,
                         time_budget_seconds=120, stale_lock_minutes=15)


class LiveFakeExtractor(FakeExtractor):
    def __init__(self, texts: dict, version: str) -> None:
        super().__init__({}, version=version)
        self._live = texts

    def page_texts(self, path: Path) -> list:
        return list(self._live.get(str(path), self._live.get(Path(path).name, [])))

    def page_count(self, path: Path) -> int:
        return len(self.page_texts(path))


def _weekdays(start: datetime, n: int):
    d, out = start, []
    while len(out) < n:
        if d.weekday() < 5:
            out.append(d)
        d += timedelta(days=1)
    return out


class Queue:
    """isolated inbox / corpus / ledger。sleeper は sleep せず回数と秒を記録する。"""

    def __init__(self, tmp_path: Path, cfg: MobileIntakeConfig = CFG):
        self.root = tmp_path / "root"
        self.home = tmp_path / "home"
        self.inbox = tmp_path / "inbox"
        self.inbox.mkdir(parents=True)
        self.texts = {}
        self.extractor = LiveFakeExtractor(self.texts, CCFG.extractor_version)
        self.store = CorpusStore(self.root / "compass_corpus")
        self.sleeps = []
        self.hook_calls = []
        self.local = LocalConfig(home=self.home, inbox_dir=self.inbox, data_root=self.root, provider=adapters.ICLOUD_DRIVE)
        self.proc = InboxProcessor(cfg, self.local, CCFG, self.store, self.extractor,
                                   sleeper=lambda s: self.sleeps.append(s),
                                   post_ingest=lambda doc: self.hook_calls.append(doc) or {"research": "RESEARCH_OK"})

    def age(self, path: Path, seconds: int = 600, *, at: datetime = NOW) -> Path:
        ts = at.timestamp() - seconds                                     # at = 次に run する時刻（0 秒前 = 転送中）
        os.utime(path, (ts, ts))
        return path

    def issue(self, name: str, day: datetime, *, seed: str = "", stable: bool = True,
              at: datetime = NOW) -> Path:
        self.texts[name] = compass_pages(date_jp=f"2026年{day.month}月{day.day}日", day=str(day.day))
        p = make_pdf(self.inbox / name, seed or name)
        return self.age(p, at=at) if stable else self.age(p, 0, at=at)

    def seed_known(self, n: int, start: datetime = datetime(2026, 1, 5)) -> list:
        """n 本を Corpus に取り込み済み（batch_import 済み）かつ ledger に DUPLICATE として final 記録済みにする。"""
        names = []
        for d in _weekdays(start, n):
            name = f"2026_{d.month:02d}{d.day:02d}_1.pdf"
            p = self.issue(name, d)
            ingest_path(self.store, p, config=CCFG, extractor=self.extractor, now=NOW, source_type=SOURCE_HISTORICAL_IMPORT)
            names.append(name)
        warm = dataclasses.replace(self.proc.config, max_files_per_run=10_000, time_budget_seconds=10_000)
        original = self.proc.config
        self.proc.config = warm
        r = self.proc.run_once(NOW)
        self.proc.config = original
        assert r.counts() == {res.DUPLICATE: n} and len(self.proc.processed_keys()) == n
        self.sleeps.clear()
        return names

    def run(self, minutes: int):
        self.sleeps.clear()
        return self.proc.run_once(NOW + timedelta(minutes=minutes))

    def close(self):
        self.store.close()


@pytest.mark.parametrize("known", [44, 120, 200])
def test_known_plus_new_sorted_last_is_processed_next_run(tmp_path, known):
    q = Queue(tmp_path)
    q.seed_known(known)
    idle = q.run(1)
    assert idle.results == [] and idle.skipped_processed == known and idle.stability_checks == 0 and q.sleeps == []
    new = q.issue("zzz_new_last_2026_0903.pdf", datetime(2026, 9, 3))
    r = q.run(5)
    assert r.candidates == known + 1 and r.unknown_candidates == 1 and r.known_candidates == known
    assert r.counts() == {res.SUCCESS: 1} and r.results[0].file == new.name and r.corpus_after == known + 1
    assert r.stability_checks == 1 and r.sleep_seconds == 1.0 and r.bounded_by == ""   # sampling は新規 1 件だけ
    assert q.hook_calls == [r.results[0].document_id]
    again = q.run(10)
    assert again.results == [] and again.skipped_processed == known + 1 and again.stability_checks == 0
    assert len(q.hook_calls) == 1
    q.close()


def test_new_file_sorted_first_is_processed_and_ordered_first(tmp_path):
    q = Queue(tmp_path)
    q.seed_known(44)
    q.issue("000_new_first_2026_0904.pdf", datetime(2026, 9, 4))
    r = q.run(5)
    assert r.counts() == {res.SUCCESS: 1} and r.results[0].file == "000_new_first_2026_0904.pdf"
    assert r.stability_checks == 1 and len(q.hook_calls) == 1
    q.close()


def test_repeated_once_with_only_known_files_is_free_and_unchanged(tmp_path):
    q = Queue(tmp_path)
    q.seed_known(44)
    canon = q.store.canonical_counts()
    ledger = len(q.proc.ledger_entries())
    for i in range(3):
        r = q.run(5 * (i + 1))
        assert r.results == [] and r.skipped_processed == 44 and r.stability_checks == 0 and r.sleep_seconds == 0
    assert q.store.canonical_counts() == canon and len(q.proc.ledger_entries()) == ledger
    assert "新しい羅針盤はありません" in (q.home / "latest_status.txt").read_text(encoding="utf-8")
    q.close()


def test_max_files_bounds_genuinely_new_files(tmp_path):
    q = Queue(tmp_path)
    q.seed_known(44)
    for d in _weekdays(datetime(2026, 9, 1), 25):
        q.issue(f"new_{d.month:02d}{d.day:02d}.pdf", d)
    r1 = q.run(5)
    assert r1.counts() == {res.SUCCESS: 20} and r1.bounded_by == "max_files_per_run" and r1.stability_checks == 20
    r2 = q.run(10)
    assert r2.counts() == {res.SUCCESS: 5} and r2.bounded_by == "" and r2.skipped_processed == 64
    assert len(q.hook_calls) == 25
    q.close()


def test_time_budget_is_consumed_by_actionable_work_only(tmp_path, monkeypatch):
    clock = {"t": 0.0}
    monkeypatch.setattr(procmod.time, "monotonic", lambda: clock["t"])
    q = Queue(tmp_path, cfg=dataclasses.replace(CFG, time_budget_seconds=3))
    q.proc.sleeper = lambda s: clock["t"].__class__ and clock.__setitem__("t", clock["t"] + s)
    q.seed_known(200)
    clock["t"] = 0.0
    idle = q.run(1)
    assert idle.results == [] and idle.skipped_processed == 200 and idle.bounded_by == ""   # 既知 200 件は budget を使わない
    for d in _weekdays(datetime(2026, 9, 1), 6):
        q.issue(f"zzz_new_{d.month:02d}{d.day:02d}.pdf", d)
    clock["t"] = 0.0
    r1 = q.run(5)
    assert r1.bounded_by == "time_budget_seconds" and 1 <= r1.counts().get(res.SUCCESS, 0) < 6
    done = r1.counts()[res.SUCCESS]
    for i in range(5):                                       # bounded runs で残りも必ず処理される
        clock["t"] = 0.0
        r = q.run(10 + i)
        done += r.counts().get(res.SUCCESS, 0)
        if done == 6:
            break
    assert done == 6 and len(q.hook_calls) == 6
    q.close()


def test_known_name_with_changed_bytes_is_not_skipped(tmp_path):
    q = Queue(tmp_path)
    names = q.seed_known(44)
    target = q.inbox / names[0]
    q.texts[names[0]] = compass_pages(date_jp="2026年9月3日", day="3")     # 同名だが別号の bytes へ変更（安定済み）
    make_pdf(target, "changed-bytes")
    q.age(target)
    r = q.run(5)
    assert r.changed_known == 1 and r.stability_checks == 1 and r.counts() == {res.SUCCESS: 1}
    assert r.results[0].file == names[0] and r.corpus_after == 45
    # 変更中（unstable）の既知名は WAITING、skip も submit もしない
    q.texts[names[1]] = compass_pages(date_jp="2026年9月4日", day="4")
    make_pdf(q.inbox / names[1], "copying-bytes")
    q.age(q.inbox / names[1], 0, at=NOW + timedelta(minutes=10))          # run 時刻ちょうど = 転送中
    r2 = q.run(10)
    assert r2.counts() == {res.WAITING_UNSTABLE: 1} and r2.results[0].file == names[1] and r2.changed_known == 1
    q.close()


def test_unstable_new_and_placeholder_are_protected(tmp_path):
    q = Queue(tmp_path)
    q.seed_known(44)
    q.issue("zzz_copying.pdf", datetime(2026, 9, 3), stable=False, at=NOW + timedelta(minutes=5))
    (q.inbox / "zzz_pending.pdf.icloud").write_bytes(b"x")
    r = q.run(5)
    by = {x.file: x for x in r.results}
    assert by["zzz_copying.pdf"].result == res.WAITING_UNSTABLE and by["zzz_copying.pdf"].reason_code == res.R_UNSTABLE_TRANSFER
    assert by["zzz_pending.pdf.icloud"].reason_code == res.R_SYNC_PLACEHOLDER
    assert r.stability_checks == 1 and r.corpus_after == 44 and q.hook_calls == []
    q.age(q.inbox / "zzz_copying.pdf")
    r2 = q.run(10)
    assert r2.counts().get(res.SUCCESS) == 1 and len(q.hook_calls) == 1
    q.close()


def test_duplicate_and_idempotency_semantics_unchanged(tmp_path):
    q = Queue(tmp_path)
    names = q.seed_known(44)
    dup = q.inbox / (Path(names[0]).stem + " 2.pdf")                   # 同一 bytes・別名（iPhone 命名）
    dup.write_bytes((q.inbox / names[0]).read_bytes())
    q.texts[dup.name] = q.texts[names[0]]
    q.age(dup)
    r = q.run(5)
    assert r.counts() == {res.DUPLICATE: 1} and r.results[0].reason_code == res.R_ALREADY_REGISTERED
    assert r.corpus_after == 44 and q.hook_calls == []
    r2 = q.run(10)
    assert r2.results == [] and r2.skipped_processed == 45 and r2.stability_checks == 0
    q.close()
