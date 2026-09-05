"""Phase 3.75 Mobile / One-Tap Compass Intake のオフラインテスト（ネットワーク・cloud SDK・credential 不使用）。

adapter 抽象 / local adapter / inbox path 設定 / path privacy / stable file / partial transfer / lock /
duplicate（同名・改名）/ rerun / crash recovery / ledger / status / milestone feedback / 非 PDF / 非 Compass /
日付不明 / read-only source / 削除なし / source 不変 / repository 不変 / PDF 非 tracking / offline /
corpus core に cloud SDK なし / setup readiness / manual fallback / end-to-end simulated arrival。
合成 PDF と FakeExtractor は test_compass_corpus.py の helper を再利用する。
"""
from __future__ import annotations

import dataclasses
import importlib.util
import json
import os
import socket
import stat
import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from src.intelligence.corpus.config import CorpusConfig
from src.intelligence.corpus.extraction import FakeExtractor
from src.intelligence.corpus.identity import sha256_file
from src.intelligence.corpus.intake import SOURCE_HISTORICAL_IMPORT, SOURCE_INBOX, SOURCE_MOBILE_UPLOAD
from src.intelligence.corpus.pipeline import ingest_path
from src.intelligence.corpus.store import CorpusStore
from src.intelligence.mobile_intake import adapters, result as res, scheduler, shortcut
from src.intelligence.mobile_intake.config import MobileIntakeConfig, config_from_mapping, load_mobile_intake_config
from src.intelligence.mobile_intake.local_config import (
    ENV_INBOX,
    SRC_ENV,
    SRC_LOCAL_FILE,
    SRC_NONE,
    LocalConfig,
    is_inside_repo,
    load_local_config,
    logical_locator,
    redact_path,
    write_local_config,
)
from src.intelligence.mobile_intake.processor import LEDGER_FILE, InboxProcessor
from src.intelligence.mobile_intake.setup import NOT_READY, PARTIAL, READY, init, inventory_report, readiness, status_report
from src.intelligence.mobile_intake.status import STATUS_JSON, STATUS_TXT, corpus_count, milestone_feedback, read_status

REPO_ROOT = Path(__file__).resolve().parents[2]
_spec = importlib.util.spec_from_file_location("_corpus_helpers", Path(__file__).with_name("test_compass_corpus.py"))
_helpers = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_helpers)
compass_pages, make_pdf, page1 = _helpers.compass_pages, _helpers.make_pdf, _helpers.page1

NOW = datetime(2026, 9, 2, 6, 0, tzinfo=timezone.utc)
CORPUS_CFG = CorpusConfig()
CFG = MobileIntakeConfig(stable_seconds=20, sample_interval_seconds=0.0, unstable_timeout_minutes=30,
                         stale_lock_minutes=15, max_files_per_run=20, time_budget_seconds=120)

DATES = [("2026年6月18日", "18"), ("2026年6月19日", "19"), ("2026年6月22日", "22"), ("2026年6月23日", "23"),
         ("2026年6月24日", "24"), ("2026年6月25日", "25"), ("2026年6月26日", "26"), ("2026年6月29日", "29"),
         ("2026年6月30日", "30"), ("2026年7月1日", "1")]


def age(path: Path, seconds: int = 100) -> Path:
    ts = NOW.timestamp() - seconds
    os.utime(path, (ts, ts))
    return path


def fresh(path: Path) -> Path:
    os.utime(path, (NOW.timestamp(), NOW.timestamp()))
    return path


class LiveFakeExtractor(FakeExtractor):
    """texts dict を **参照** で持つ（後から追加した file 名も見える）。"""

    def __init__(self, texts: dict, version: str) -> None:
        super().__init__({}, version=version)
        self._live = texts

    def page_texts(self, path: Path) -> list:
        return list(self._live.get(str(path), self._live.get(Path(path).name, [])))

    def page_count(self, path: Path) -> int:
        return len(self.page_texts(path))


class Lab:
    """isolated home / inbox / corpus root ＋ LiveFakeExtractor（file 名 → page text）。"""

    def __init__(self, tmp_path: Path, provider: str = adapters.ICLOUD_DRIVE, cfg: MobileIntakeConfig = CFG):
        self.root = tmp_path / "root"
        self.home = tmp_path / "home"
        self.inbox = tmp_path / "inbox"
        self.inbox.mkdir(parents=True)
        self.texts = {}
        self.store = CorpusStore(self.root / "compass_corpus")
        self.local = LocalConfig(home=self.home, inbox_dir=self.inbox, data_root=self.root, provider=provider)
        self.cfg = cfg
        self.extractor = LiveFakeExtractor(self.texts, version=CORPUS_CFG.extractor_version)
        self.proc = InboxProcessor(cfg, self.local, CORPUS_CFG, self.store, self.extractor, sleeper=lambda s: None)

    def seed(self, n: int) -> None:
        for i in range(n):
            name = f"seed{i}.pdf"
            self.texts[name] = compass_pages(date_jp=DATES[i][0], day=DATES[i][1])
            ingest_path(self.store, make_pdf(self.root / "seed" / name, name), config=CORPUS_CFG,
                        extractor=self.extractor, now=NOW, source_type=SOURCE_HISTORICAL_IMPORT)

    def arrive(self, name: str, seed_index: int = 9, *, stable: bool = True, seed: str = "") -> Path:
        self.texts[name] = compass_pages(date_jp=DATES[seed_index][0], day=DATES[seed_index][1])
        p = make_pdf(self.inbox / name, seed or name)
        return age(p) if stable else fresh(p)

    def run(self, minutes: int = 0):
        return self.proc.run_once(NOW + timedelta(minutes=minutes))

    def status_text(self) -> str:
        return (self.home / STATUS_TXT).read_text(encoding="utf-8")

    def close(self) -> None:
        self.store.close()


# ============================================================ adapter abstraction

def test_adapter_evaluation_and_selection():
    table = adapters.evaluation_table()
    assert {r["provider"] for r in table} == set(adapters.PROVIDERS)
    assert adapters.SELECTED_PROVIDER == adapters.ICLOUD_DRIVE
    assert [r for r in table if r["provider"] == adapters.ICLOUD_DRIVE][0]["verdict"] == "SELECTED"
    assert all(r["new_account"] is False and r["credentials_in_repo"] is False for r in table)
    assert "public upload endpoint" in adapters.REJECTED_ALTERNATIVES


def test_sync_folder_adapter_discovers_only_stable_pdf_candidates(tmp_path):
    inbox = tmp_path / "inbox"
    inbox.mkdir()
    (inbox / "_status").mkdir()
    (inbox / "sub").mkdir()
    make_pdf(inbox / "a.pdf", "a")
    (inbox / "b.pdf.icloud").write_bytes(b"x")        # placeholder
    (inbox / "c.pdf").write_bytes(b"")                 # 0 byte
    (inbox / "note.txt").write_text("x")
    (inbox / ".hidden.pdf").write_bytes(b"%PDF-")
    adapter = adapters.SyncFolderAdapter(adapters.ICLOUD_DRIVE, inbox)
    candidates, placeholders = adapter.discover()
    assert [p.name for p in candidates] == ["a.pdf"]
    assert {p.name for p, _ in placeholders} == {"b.pdf.icloud", "c.pdf"}
    assert adapter.describe()["inbox"].endswith("/inbox") and adapter.describe()["exists"]
    assert adapters.default_sync_root(adapters.ICLOUD_DRIVE, {"USERPROFILE": "C:\\Users\\x"}) == Path("C:\\Users\\x") / "iCloudDrive"
    assert adapters.default_inbox_dir(adapters.ONEDRIVE, "Shortcuts/CompassInbox", {"OneDrive": "D:\\OD"}) == Path("D:\\OD") / "Shortcuts" / "CompassInbox"
    assert adapters.default_inbox_dir(adapters.LOCAL_FOLDER, "x", {}) is None


def test_corpus_core_and_intake_have_no_cloud_sdk_or_network_imports():
    bad = []
    for pkg in ("corpus", "mobile_intake"):
        for py in (REPO_ROOT / "src" / "intelligence" / pkg).glob("*.py"):
            text = py.read_text(encoding="utf-8")
            for tok in ("googleapiclient", "pyicloud", "dropbox", "boto3", "onedrivesdk", "import " + "requests",
                        "import " + "urllib", "from " + "urllib", "import " + "socket", "http." + "client"):
                if tok in text:
                    bad.append(f"{pkg}/{py.name}:{tok}")
    assert bad == []


def test_local_adapter_uses_inbox_source_type(tmp_path):
    lab = Lab(tmp_path, provider=adapters.LOCAL_FOLDER)
    assert lab.proc.source_type == SOURCE_INBOX
    icloud = Lab(tmp_path / "b")
    assert icloud.proc.source_type == SOURCE_MOBILE_UPLOAD
    lab.close()
    icloud.close()


# ============================================================ local config / path privacy

def test_inbox_path_resolution_order(tmp_path):
    home = tmp_path / "home"
    cfg = MobileIntakeConfig()
    none = load_local_config(cfg, env={}, home=home)
    assert none.inbox_dir is None and none.sources["inbox_dir"] == SRC_NONE
    write_local_config(home, inbox_dir=tmp_path / "from_file", data_root_dir=tmp_path / "dr", provider="onedrive")
    from_file = load_local_config(cfg, env={}, home=home)
    assert from_file.inbox_dir == tmp_path / "from_file" and from_file.sources["inbox_dir"] == SRC_LOCAL_FILE
    assert from_file.provider == "ONEDRIVE" and from_file.data_root == tmp_path / "dr"
    from_env = load_local_config(cfg, env={ENV_INBOX: str(tmp_path / "from_env"),
                                          "INTELLIGENCE_DATA_ROOT": str(tmp_path / "env_root")}, home=home)
    assert from_env.inbox_dir == tmp_path / "from_env" and from_env.sources["inbox_dir"] == SRC_ENV
    assert from_env.data_root == tmp_path / "env_root"
    assert not (REPO_ROOT / ".compass_intake").exists()
    text = (home / "local_config.json").read_text(encoding="utf-8")
    assert "from_file" in text                                   # 絶対 path は repository 外のファイルにだけ


def test_path_privacy_helpers(tmp_path):
    deep = tmp_path / "Users" / "someone" / "iCloudDrive" / "Shortcuts" / "CompassInbox"
    assert redact_path(deep) == ".../Shortcuts/CompassInbox"
    assert "someone" not in redact_path(deep)
    assert logical_locator(deep / "2026_0902_1.pdf") == "inbox://2026_0902_1.pdf"
    assert is_inside_repo(REPO_ROOT / "config.yaml", REPO_ROOT) and not is_inside_repo(tmp_path, REPO_ROOT)


def test_ledger_and_status_never_contain_full_paths(tmp_path):
    lab = Lab(tmp_path)
    lab.seed(2)
    lab.arrive("2026_0701_1.pdf")
    report = lab.run()
    assert report.inbox == ".../" + tmp_path.name + "/inbox" or report.inbox.endswith("/inbox")
    ledger = (lab.home / LEDGER_FILE).read_text(encoding="utf-8")
    status = (lab.home / STATUS_JSON).read_text(encoding="utf-8")
    assert str(tmp_path) not in ledger and str(tmp_path) not in status
    assert "inbox://2026_0701_1.pdf" in ledger
    lab.close()


# ============================================================ stable file / partial transfer / lock

def test_partial_transfer_waits_then_succeeds(tmp_path):
    lab = Lab(tmp_path)
    lab.seed(1)
    p = lab.arrive("arriving.pdf", stable=False)
    r1 = lab.run()
    assert r1.counts() == {res.WAITING_UNSTABLE: 1} and r1.corpus_after == 1
    assert r1.results[0].reason_code == res.R_UNSTABLE_TRANSFER and not (lab.home / LEDGER_FILE).exists()
    assert "処理待ち" in lab.status_text()
    age(p)
    r2 = lab.run(5)
    assert r2.counts() == {res.SUCCESS: 1} and r2.corpus_after == 2
    assert lab.proc._state()["first_seen"] == {}
    lab.close()


def test_stability_requires_unchanged_size_and_openability(tmp_path, monkeypatch):
    lab = Lab(tmp_path)
    lab.seed(1)
    p = lab.arrive("grow.pdf")
    sizes = iter([(10, NOW.timestamp() - 100), (20, NOW.timestamp() - 100)])
    lab.proc.sampler = lambda path: next(sizes)
    assert lab.run().counts() == {res.WAITING_UNSTABLE: 1}
    lab.proc.sampler = lambda path: (30, NOW.timestamp() - 100)
    monkeypatch.setattr(InboxProcessor, "_openable", staticmethod(lambda path: False))
    assert lab.run(1).counts() == {res.WAITING_UNSTABLE: 1}
    lab.close()


def test_placeholder_is_waiting_not_quarantined(tmp_path):
    lab = Lab(tmp_path)
    lab.seed(1)
    (lab.inbox / "2026_0701_1.pdf.icloud").write_bytes(b"x")
    r = lab.run()
    assert r.placeholders == 1 and r.results[0].result == res.WAITING_UNSTABLE
    assert r.results[0].reason_code == res.R_SYNC_PLACEHOLDER
    lab.close()


def test_unstable_timeout_becomes_failed_with_hint(tmp_path):
    lab = Lab(tmp_path)
    lab.seed(1)
    lab.arrive("stuck.pdf", stable=False)
    lab.proc._first_seen("stuck.pdf", NOW - timedelta(minutes=31))
    r = lab.run()
    assert r.counts() == {res.FAILED: 1} and r.results[0].reason_code == res.R_TIMEOUT_UNSTABLE
    assert "もう一度共有" in r.results[0].hint
    assert (lab.home / LEDGER_FILE).exists()
    lab.close()


def test_live_locks_are_respected_and_stale_locks_recovered(tmp_path):
    lab = Lab(tmp_path)
    lab.seed(1)
    lab.arrive("locked.pdf")
    live = scheduler.acquire_instance_lock(lab.home, 15, NOW)
    r = lab.run()
    assert not r.single_instance_acquired and r.results == []
    scheduler.release_instance_lock(live)
    stale = lab.home / scheduler.INSTANCE_LOCK
    stale.write_text("dead")
    age(stale, 16 * 60)
    lock_dir = lab.home / "locks"
    lock_dir.mkdir()
    file_lock = lock_dir / "locked.pdf.lock"
    file_lock.write_text("dead")
    r2 = lab.run(1)
    assert r2.single_instance_acquired and r2.skipped_locked == 1       # 生きた file lock は尊重
    age(file_lock, 16 * 60)
    r3 = lab.run(2)
    assert r3.counts() == {res.SUCCESS: 1} and not file_lock.exists() and not stale.exists()
    lab.close()


# ============================================================ duplicate / rerun / ledger

def test_duplicate_and_renamed_duplicate_are_harmless(tmp_path):
    lab = Lab(tmp_path)
    lab.seed(9)
    lab.arrive("2026_0701_1.pdf")
    r1 = lab.run()
    assert r1.counts() == {res.SUCCESS: 1} and r1.corpus_after == 10
    lab.texts["2026_0701_1 2.pdf"] = lab.texts["2026_0701_1.pdf"]
    age(make_pdf(lab.inbox / "2026_0701_1 2.pdf", "2026_0701_1.pdf"))       # 同じ bytes・iOS 命名
    r2 = lab.run(5)
    assert r2.counts() == {res.DUPLICATE: 1} and r2.corpus_after == 10
    assert r2.results[0].reason_code == res.R_ALREADY_REGISTERED
    assert "既に登録済み" in lab.status_text() and len(lab.store.documents()) == 10
    r3 = lab.run(10)                                                       # 同名再投入は ledger 済み → skip
    assert r3.skipped_processed == 2 and r3.results == []
    lab.close()


def test_rerun_is_idempotent_and_writes_idle_status(tmp_path):
    lab = Lab(tmp_path)
    lab.seed(2)
    lab.arrive("x.pdf")
    lab.run()
    before = lab.store.canonical_counts()
    r = lab.run(5)
    assert r.results == [] and lab.store.canonical_counts() == before
    assert "新しい羅針盤はありません" in lab.status_text()
    lab.close()


def test_result_ledger_is_machine_readable_without_text(tmp_path):
    lab = Lab(tmp_path)
    lab.seed(1)
    lab.arrive("2026_0701_1.pdf")
    lab.run()
    entries = lab.proc.ledger_entries()
    assert len(entries) == 1
    e = entries[0]
    assert e["result"] == res.SUCCESS and e["ledger_id"].startswith("cml_") and e["sha256"]
    assert set(e) >= {"document_id", "document_date", "received_at", "reason_code", "processing_duration_seconds",
                      "corpus_count_after", "milestone"}
    assert "底堅い" not in json.dumps(e, ensure_ascii=False)
    assert lab.proc.processed_hashes() == {e["sha256"]}
    lab.close()


# ============================================================ status / milestone feedback

def test_status_and_milestone_feedback(tmp_path):
    lab = Lab(tmp_path)
    lab.seed(9)
    assert corpus_count(lab.store) == 9
    lab.arrive("2026_0701_1.pdf")
    r = lab.run()
    text = lab.status_text()
    assert "羅針盤追加成功" in text and "Corpus: 9 → 10" in text
    assert "Milestone 到達: CORPUS_10" in text and "Next: CORPUS_30" in text and "Remaining: 20" in text
    ms = r.results[0].milestone
    assert ms["reached"] == "CORPUS_10" and ms["reached_now"] and ms["remaining"] == 20
    payload = read_status(lab.home)
    assert payload["result"] == res.SUCCESS and payload["corpus_count_after"] == 10
    assert (lab.inbox / "_status" / STATUS_TXT).read_text(encoding="utf-8") == text
    assert milestone_feedback(0, (10, 30))["next"] == "CORPUS_10"
    lab.close()


def test_status_in_inbox_can_be_disabled(tmp_path):
    lab = Lab(tmp_path, cfg=dataclasses.replace(CFG, status_in_inbox=False))
    lab.seed(1)
    lab.arrive("y.pdf")
    lab.run()
    assert (lab.home / STATUS_TXT).exists() and not (lab.inbox / "_status").exists()
    lab.close()


def test_sync_not_available_is_reported_not_crashed(tmp_path):
    lab = Lab(tmp_path)
    lab.local = LocalConfig(home=lab.home, inbox_dir=tmp_path / "missing", data_root=lab.root,
                            provider=adapters.ICLOUD_DRIVE)
    lab.proc = InboxProcessor(CFG, lab.local, CORPUS_CFG, lab.store, lab.extractor, sleeper=lambda s: None)
    r = lab.run()
    assert not r.sync_available and read_status(lab.home)["reason_code"] == res.R_SYNC_NOT_AVAILABLE
    lab.close()


# ============================================================ failure UX

def test_failures_explain_what_to_do(tmp_path):
    lab = Lab(tmp_path)
    lab.seed(1)
    (lab.inbox / "junk.pdf").write_bytes(b"hello")
    age(lab.inbox / "junk.pdf")
    lab.texts["other.pdf"] = ["unrelated " * 60] * 5
    age(make_pdf(lab.inbox / "other.pdf", "other"))
    lab.texts["nodate.pdf"] = [compass_pages()[0].replace("2026年6月18日", "")] + compass_pages()[1:]
    age(make_pdf(lab.inbox / "nodate.pdf", "nodate"))
    r = lab.run()
    by = {x.file: x for x in r.results}
    assert by["junk.pdf"].result == res.FAILED and by["junk.pdf"].reason_code == res.R_NOT_PDF
    assert by["other.pdf"].result == res.QUARANTINED and by["other.pdf"].reason_code == res.R_NOT_COMPASS
    assert by["nodate.pdf"].result == res.QUARANTINED and by["nodate.pdf"].reason_code == res.R_DATE_UNKNOWN
    assert all(x.hint for x in r.results) and "Traceback" not in lab.status_text()
    assert res.reason_from_corpus("QUARANTINED", ["PAGE_COUNT_OUT_OF_RANGE"]) == res.R_NOT_COMPASS
    assert res.reason_from_corpus("FAILED", ["PDF_UNREADABLE", "ValueError"]) == res.R_UNREADABLE_PDF
    lab.close()


# ============================================================ originals / repository / offline

def test_originals_are_kept_and_unmodified_and_corpus_copy_read_only(tmp_path):
    lab = Lab(tmp_path)
    lab.seed(1)
    p = lab.arrive("keep.pdf")
    before = sha256_file(p)
    r = lab.run()
    assert p.exists() and sha256_file(p) == before
    doc = lab.store.document(r.results[0].document_id)
    copy = lab.store.root / doc.storage_locator
    assert copy.exists() and not (copy.stat().st_mode & stat.S_IWUSR)
    assert sorted(x.name for x in lab.inbox.iterdir()) == ["_status", "keep.pdf"]
    lab.close()


def test_no_repository_mutation_and_no_tracked_pdf(tmp_path, monkeypatch):
    monkeypatch.setenv("COMPASS_INTAKE_HOME", str(tmp_path / "h"))
    before = subprocess.run(["git", "status", "--porcelain"], cwd=REPO_ROOT, capture_output=True, text=True).stdout
    lab = Lab(tmp_path)
    lab.seed(1)
    lab.arrive("z.pdf")
    lab.run()
    after = subprocess.run(["git", "status", "--porcelain"], cwd=REPO_ROOT, capture_output=True, text=True).stdout
    assert before == after
    tracked = subprocess.run(["git", "ls-files"], cwd=REPO_ROOT, capture_output=True, text=True).stdout
    assert not [l for l in tracked.splitlines() if l.lower().endswith(".pdf")]
    lab.close()


def test_processor_runs_with_network_disabled(tmp_path, monkeypatch):
    def boom(*a, **k):
        raise AssertionError("network forbidden")

    monkeypatch.setattr(socket, "socket", boom)
    monkeypatch.setattr(socket, "create_connection", boom)
    lab = Lab(tmp_path)
    lab.seed(1)
    lab.arrive("off.pdf")
    assert lab.run().counts() == {res.SUCCESS: 1}
    lab.close()


def test_bounded_by_max_files_and_time_budget(tmp_path, monkeypatch):
    lab = Lab(tmp_path, cfg=dataclasses.replace(CFG, max_files_per_run=1))
    lab.seed(1)
    lab.arrive("a.pdf", 8)
    lab.arrive("b.pdf", 9)
    r1 = lab.run()
    assert r1.bounded_by == "max_files_per_run" and r1.counts() == {res.SUCCESS: 1}
    r2 = lab.run(1)
    assert r2.counts() == {res.SUCCESS: 1} and r2.skipped_processed == 1
    lab2 = Lab(tmp_path / "t", cfg=dataclasses.replace(CFG, time_budget_seconds=5))
    lab2.seed(1)
    lab2.arrive("c.pdf", 8)
    ticks = iter([0.0])                                                    # t0 の後は常に予算超過
    monkeypatch.setattr("src.intelligence.mobile_intake.processor.time.monotonic", lambda: next(ticks, 100.0))
    r3 = lab2.run()
    assert r3.bounded_by == "time_budget_seconds" and r3.results == []
    lab.close()
    lab2.close()


# ============================================================ scheduler / shortcut / setup

def test_windows_scheduler_artifacts_are_bounded_and_user_level(tmp_path):
    cfg = MobileIntakeConfig()
    cmd = scheduler.schtasks_create_command(cfg, tmp_path)
    assert "/SC MINUTE /MO 5" in cmd and '"CompassIntake"' in cmd and "run_intake.cmd" in cmd
    assert "/RU" not in cmd and "/RL HIGHEST" not in cmd                 # 管理者権限不要
    script = scheduler.write_run_script(tmp_path, "C:\\Python\\python.exe", Path("C:\\repo"))
    text = script.read_text(encoding="utf-8")
    assert "cd /d \"C:\\repo\"" in text and "src.intelligence.mobile_intake.processor --once" in text
    design = scheduler.design_summary(cfg)
    assert design["daemon"] is False and design["admin_required"] is False and design["busy_waiting"] is False
    assert scheduler.is_task_registered(cfg, runner=lambda *a, **k: (_ for _ in ()).throw(OSError())) in (None, False)
    assert not (REPO_ROOT / "run_intake.cmd").exists()


def test_shortcut_recipe_and_action_count():
    cfg = MobileIntakeConfig()
    r = shortcut.shortcut_recipe(cfg)
    assert r["name"] == "羅針盤に追加" and r["mobile_action_count"] == 2 and r["installed_verified"] is False
    save = [a for a in r["actions"] if a["action"] == "ファイルを保存"][0]
    assert save["settings"]["保存場所を尋ねる"] == "オフ" and save["settings"]["既存のファイルを上書き"] == "オフ"
    assert r["destination"] == "iCloud Drive/Shortcuts/CompassInbox"
    text = shortcut.build_instructions_ja(cfg)
    assert "共有シートに表示" in text and "既に登録済み" in text and "CompassInbox" in text


def test_setup_readiness_levels(tmp_path, monkeypatch):
    from src.intelligence.mobile_intake import setup as mi_setup

    cfg = MobileIntakeConfig()
    home = tmp_path / "home"
    missing = LocalConfig(home=home, inbox_dir=None, data_root=tmp_path / "root", provider="ICLOUD_DRIVE")
    assert readiness(cfg, missing, repo_root=REPO_ROOT, task_registered=False, env={})["status"] == NOT_READY
    inbox = tmp_path / "sync" / "CompassInbox"
    out = init(cfg, home=home, inbox_dir=inbox, data_root_dir=tmp_path / "root", provider="ICLOUD_DRIVE",
               python_exe="python", repo_root=REPO_ROOT)
    assert out["inbox_created"] is False                                    # 親（同期 root）が無ければ作らない
    (tmp_path / "sync").mkdir()
    out = init(cfg, home=home, inbox_dir=inbox, data_root_dir=tmp_path / "root", provider="ICLOUD_DRIVE",
               python_exe="python", repo_root=REPO_ROOT)
    assert out["inbox_created"] and (inbox / "_status").is_dir() and "schtasks" in out["task_command"]
    local = load_local_config(cfg, env={}, home=home)
    assert local.inbox_dir == inbox and local.data_root == tmp_path / "root"
    partial = readiness(cfg, local, repo_root=REPO_ROOT, task_registered=False, env={})   # 未登録を明示
    assert partial["status"] == PARTIAL and partial["checks"]["inbox_exists"] and partial["checks"]["corpus_reachable"]
    assert partial["checks"]["processor_configured"] is False
    assert any("Task Scheduler" in d for d in partial["diagnostics"])
    ready = readiness(cfg, local, repo_root=REPO_ROOT, task_registered=True, env={})
    assert ready["status"] == READY and ready["checks"]["shortcut_instructions_generated"]
    assert str(tmp_path) not in json.dumps(ready) and "token" not in json.dumps(ready).lower()
    # task_registered=None は「実機の Task Scheduler を自動検出」の意味。テストが実行機の登録状態
    # （Windows の CompassIntake の有無）に左右されないよう、probe を差し替えて 3 状態を決定的に再現する。
    for probe, expected, configured in ((lambda config: None, PARTIAL, None),        # 判定不能（非 Windows）
                                        (lambda config: False, PARTIAL, False),      # 未登録
                                        (lambda config: True, READY, True)):         # 登録済み
        monkeypatch.setattr(mi_setup, "is_task_registered", probe)
        auto = readiness(cfg, local, repo_root=REPO_ROOT, task_registered=None, env={})
        assert (auto["status"], auto["checks"]["processor_configured"]) == (expected, configured)
    monkeypatch.undo()
    with pytest.raises(ValueError):
        init(cfg, home=home, inbox_dir=inbox, data_root_dir=None, provider="DROPBOX", python_exe="python",
             repo_root=REPO_ROOT)


def test_manual_fallback_local_folder_drop(tmp_path):
    lab = Lab(tmp_path, provider=adapters.LOCAL_FOLDER)
    lab.seed(1)
    lab.arrive("dropped_from_usb.pdf")
    r = lab.run()
    assert r.counts() == {res.SUCCESS: 1}
    assert lab.store.document(r.results[0].document_id).source_type == SOURCE_INBOX
    lab.close()


def test_config_section_and_defaults():
    cfg = load_mobile_intake_config(REPO_ROOT / "config.yaml")
    assert cfg.provider == "ICLOUD_DRIVE" and cfg.task_name == "CompassIntake" and cfg.status_in_inbox
    assert config_from_mapping({"max_files_per_run": "0", "stable_samples": 1}).max_files_per_run == 1
    assert config_from_mapping({"stable_samples": 1}).stable_samples == 2
    section = (REPO_ROOT / "config.yaml").read_text(encoding="utf-8").split("mobile_intake:")[1]
    assert "C:\\" not in section and "/Users/" not in section                # 機械固有 path なし


def test_setup_inventory_and_status_reports(tmp_path):
    lab = Lab(tmp_path)
    lab.seed(2)
    lab.arrive("already_in_corpus.pdf", 0, seed="seed0.pdf")            # seed0 と同じ bytes → hash duplicate
    lab.arrive("fresh.pdf", 9)
    lab.arrive("copying.pdf", 8, stable=False)
    (lab.inbox / "pending.pdf.icloud").write_bytes(b"x")
    (lab.inbox / "memo.txt").write_text("x")
    (lab.inbox / "sub").mkdir()
    inv = inventory_report(lab.cfg, lab.local, now_ts=NOW.timestamp())
    assert inv["exists"] and inv["total_items"] == 6 and inv["subfolders"] == 1 and inv["files"] == 5
    assert inv["pdf_candidates"] == 3 and inv["stable"] == 2 and inv["unstable"] == 1 and inv["placeholders"] == 1
    assert inv["non_pdf"] == 1 and inv["non_pdf_names"] == ["memo.txt"]
    assert inv["corpus_documents"] == 2 and inv["hash_duplicates_of_corpus"] == 1 and inv["new_candidates"] == 1
    assert inv["duplicate_names"] == ["already_in_corpus.pdf"] and inv["new_candidate_names"] == ["fresh.pdf"]
    assert str(tmp_path) not in json.dumps(inv, ensure_ascii=False)     # full path なし
    assert sorted(p.name for p in lab.inbox.iterdir()) == ["already_in_corpus.pdf", "copying.pdf", "fresh.pdf",
                                                            "memo.txt", "pending.pdf.icloud", "sub"]   # 読むだけ
    st = status_report(lab.local)
    assert st["corpus"]["exists"] and st["corpus"]["documents"] == 2 and st["corpus"]["milestone"] == "NONE"
    assert st["corpus"]["next_milestone"] == "CORPUS_10" and st["corpus"]["documents_needed"] == 8
    assert st["research"]["exists"] is False
    missing = status_report(LocalConfig(home=lab.home, inbox_dir=None, data_root=tmp_path / "nowhere", provider="ICLOUD_DRIVE"))
    assert missing["corpus"] == {"exists": False, "documents": 0}
    lab.close()


# ============================================================ end-to-end simulated arrival（pilot）

def test_pilot_end_to_end_simulated_arrival(tmp_path, monkeypatch, capsys):
    from src.intelligence.mobile_intake import pilot

    src = tmp_path / "src"
    texts = {}
    for i in range(3):
        name = f"doc{i}.pdf"
        make_pdf(src / name, name)
        texts[name] = compass_pages(date_jp=DATES[i][0], day=DATES[i][1])
    for extra in ("doc2 2.pdf", "revision_same_date.pdf", "stable.pdf", "bounded_a.pdf", "bounded_b.pdf"):
        texts[extra] = texts["doc2.pdf"]
    texts["other_report.pdf"] = ["unrelated " * 60] * 5
    monkeypatch.setattr(pilot, "PypdfExtractor", lambda version: FakeExtractor(texts, version=version))
    monkeypatch.setattr(pilot, "_resave_pdf", lambda s, d: make_pdf(d, d.name + "-resaved"))
    monkeypatch.setattr(pilot, "_blank_pdf", lambda d: make_pdf(d, "blank"))
    monkeypatch.setenv("INTELLIGENCE_DATA_ROOT", str(tmp_path / "prod"))
    rc = pilot.main(["--source", str(src), "--root", str(tmp_path / "pilot_root")])
    out = capsys.readouterr().out
    assert rc == 0
    markers = [m for m in ("P375_INPUT", "P375_ADAPTER", "P375_SETUP", "P375_ARRIVAL_PARTIAL", "P375_ARRIVAL_STABLE",
                           "P375_DUPLICATE", "P375_RERUN", "P375_CRASH_RECOVERY", "P375_FAILURES", "P375_TIMEOUT",
                           "P375_BOUNDED", "P375_SECURITY", "P375_SUMMARY") if f"::{m}::" in out]
    assert len(markers) == 13
    summary = json.loads(out.split("::P375_SUMMARY::")[1].splitlines()[0])
    for key in ("partial_waited", "stable_success", "duplicate_harmless", "rerun_idempotent", "crash_recovered",
                "failures_explained", "timeout_failed", "bounded"):
        assert summary[key], key
    assert summary["real_adapter_validation"] in ("VERIFIED", "ADAPTER_SETUP_REQUIRED")
    security = json.loads(out.split("::P375_SECURITY::")[1].splitlines()[0])
    assert security["source_pdfs_unmodified"] and not security["inbox_originals_deleted"]
    assert not security["full_path_in_ledger_or_status"] and security["network_or_cloud_sdk_imports"] == []
    assert not (tmp_path / "prod" / "compass_corpus").exists()
    assert "底堅い展開を想定する" not in out
