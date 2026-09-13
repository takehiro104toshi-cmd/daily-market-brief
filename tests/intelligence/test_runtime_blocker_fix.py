"""Windows runtime blocker（pypdf 未インストール → 44/44 FAILED）の再発防止テスト。

1 dependency declaration consistency / 2 missing extractor = environment failure（Corpus 0 record・0 event）/
3 setup readiness（extractor 無しでは READY にならない）/ 4 corrupt PDF は document-level failure /
5 environment 由来 FAILED record の gate 付き in-place 再検証 / 6 通常 duplicate は再処理しない /
7 recovered document の Phase 3.8 N+1 semantics / 8 rebuild・incremental 等価性の維持。
"""
from __future__ import annotations

import importlib.util
import json
import os
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from src.intelligence.corpus import status as st
from src.intelligence.corpus.config import CorpusConfig
from src.intelligence.corpus.extraction import ExtractorUnavailable, FakeExtractor, PypdfExtractor, extractor_availability
from src.intelligence.corpus.identity import identity_from_path
from src.intelligence.corpus.intake import SOURCE_HISTORICAL_IMPORT, SOURCE_LOCAL_FILE
from src.intelligence.corpus.pipeline import RECOVERY_NOT_ELIGIBLE, ingest_path, recovery_eligibility
from src.intelligence.corpus.snapshot import build_snapshot
from src.intelligence.corpus.source import SourceDocument, verify_original
from src.intelligence.corpus.store import CorpusStore
from src.intelligence.corpus.validation import is_environment_failure
from src.intelligence.corpus_research.batch_import import batch_import
from src.intelligence.corpus_research.config import ResearchConfig
from src.intelligence.corpus_research.engine import ResearchEngine
from src.intelligence.corpus_research.regime import MarketConnector
from src.intelligence.corpus_research.store import ResearchStore
from src.intelligence.mobile_intake import adapters
from src.intelligence.mobile_intake.config import MobileIntakeConfig, load_mobile_intake_config
from src.intelligence.mobile_intake.local_config import LocalConfig
from src.intelligence.mobile_intake.processor import LEDGER_FILE, InboxProcessor
from src.intelligence.mobile_intake.result import R_EXTRACTOR_UNAVAILABLE
from src.intelligence.mobile_intake.setup import NOT_READY, READY, init, readiness
from src.intelligence.mobile_intake.status import read_status

REPO_ROOT = Path(__file__).resolve().parents[2]
_spec = importlib.util.spec_from_file_location("_corpus_helpers", Path(__file__).with_name("test_compass_corpus.py"))
_helpers = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_helpers)
compass_pages, make_pdf = _helpers.compass_pages, _helpers.make_pdf

NOW = datetime(2026, 9, 3, 6, 0, tzinfo=timezone.utc)
CCFG = CorpusConfig()
DATES = [("2026年6月18日", "18"), ("2026年6月19日", "19"), ("2026年6月22日", "22"), ("2026年6月23日", "23")]
WINDOWS_REASON = "PDF_UNREADABLE,ModuleNotFoundError"       # 実機で観測された reason（44 件）


class LiveFakeExtractor(FakeExtractor):
    def __init__(self, texts: dict, version: str) -> None:
        super().__init__({}, version=version)
        self._live = texts

    def page_texts(self, path: Path) -> list:
        return list(self._live.get(str(path), self._live.get(Path(path).name, [])))

    def page_count(self, path: Path) -> int:
        return len(self.page_texts(path))


class UnavailableExtractor(FakeExtractor):
    """pypdf 欠落時の PypdfExtractor と同じ振る舞い（availability False、page_texts で ExtractorUnavailable）。"""

    name = "pypdf_text_layer"

    def availability(self):
        return {"available": False, "module": "pypdf", "version": "", "error_type": "ModuleNotFoundError"}

    def page_texts(self, path: Path) -> list:
        raise ExtractorUnavailable("pypdf unavailable (ModuleNotFoundError)")

    def metadata(self, path: Path) -> dict:
        raise ExtractorUnavailable("pypdf unavailable (ModuleNotFoundError)")


def _windows_like_failed_record(store: CorpusStore, path: Path, now: datetime) -> str:
    """fail-fast 導入前のコードが Windows で書いた record を忠実に再現する（page_count 0・locator 空・FAILED）。"""
    ident = identity_from_path(path)
    store.add_document(SourceDocument(
        document_id=ident.document_id, sha256=ident.sha256, original_filename=path.name,
        source_type=SOURCE_HISTORICAL_IMPORT, received_at=now.isoformat(), document_date="", date_sequence=0,
        page_count=0, byte_size=ident.byte_size, media_type="application/pdf", storage_locator="",
        family="UNKNOWN", family_confidence="LOW"))
    store.add_status_event(st.status_event(ident.document_id, st.RECEIVED, "bytes received", now, sequence=0))
    store.add_status_event(st.status_event(ident.document_id, st.FAILED, WINDOWS_REASON, now, sequence=1))
    return ident.document_id


def _requirement_names(text: str) -> set:
    names = set()
    for line in text.splitlines():
        line = line.split("#", 1)[0].strip()
        if line:
            names.add(re.split(r"[<>=!~\[ ]", line, 1)[0].lower())
    return names


# ------------------------------------------------------------ 1. dependency declaration

def test_dependency_declarations_include_pypdf_and_stay_in_sync():
    req = _requirement_names((REPO_ROOT / "requirements.txt").read_text(encoding="utf-8")) - {"pytest"}
    pyproject = (REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8")
    block = pyproject.split("dependencies = [", 1)[1].split("]", 1)[0]
    proj = {re.split(r"[<>=!~\[ ]", s.strip().strip('",'), 1)[0].lower() for s in block.strip().splitlines() if s.strip()}
    assert "pypdf" in req and "pypdf" in proj
    assert req == proj, f"requirements.txt と pyproject.toml の依存が不一致: {req ^ proj}"
    info = extractor_availability("pypdf")
    assert info["available"] and int(info["version"].split(".")[0]) >= 4
    assert PypdfExtractor().availability()["available"]


# ------------------------------------------------------------ 2. missing extractor = environment failure

def test_missing_pypdf_is_environment_failure_not_document_failure(tmp_path, monkeypatch):
    monkeypatch.setitem(sys.modules, "pypdf", None)                    # import pypdf → ImportError
    ex = PypdfExtractor(CCFG.extractor_version)
    assert ex.availability() == {"available": False, "module": "pypdf", "version": "", "error_type": "ModuleNotFoundError"}
    store = CorpusStore(tmp_path / "corpus")
    pdf = make_pdf(tmp_path / "issue.pdf", "issue")
    with pytest.raises(ExtractorUnavailable):
        ingest_path(store, pdf, config=CCFG, extractor=ex, now=NOW, source_type=SOURCE_HISTORICAL_IMPORT)
    assert store.counts()["documents"] == 0 and store.counts()["status_events"] == 0
    assert not (tmp_path / "corpus" / "documents.jsonl").exists()
    report = batch_import(tmp_path, store, corpus_config=CCFG, extractor=ex, max_files=10, now=NOW)
    assert report.environment_error.startswith("EXTRACTOR_UNAVAILABLE") and report.processed == 0
    assert report.failed == 0 and store.counts()["documents"] == 0 and store.counts()["status_events"] == 0
    store.close()


def test_processor_stops_before_touching_files_when_extractor_missing(tmp_path):
    inbox = tmp_path / "inbox"
    inbox.mkdir()
    make_pdf(inbox / "issue.pdf", "issue")
    store = CorpusStore(tmp_path / "root" / "compass_corpus")
    local = LocalConfig(home=tmp_path / "home", inbox_dir=inbox, data_root=tmp_path / "root", provider=adapters.ICLOUD_DRIVE)
    proc = InboxProcessor(MobileIntakeConfig(sample_interval_seconds=0.0), local, CCFG, store,
                          UnavailableExtractor({}, version=CCFG.extractor_version), sleeper=lambda s: None)
    report = proc.run_once(NOW)
    assert report.environment_error.startswith(R_EXTRACTOR_UNAVAILABLE) and report.results == []
    assert not (tmp_path / "home" / LEDGER_FILE).exists() and store.counts()["documents"] == 0
    status = read_status(tmp_path / "home")
    assert status["reason_code"] == R_EXTRACTOR_UNAVAILABLE and "pip install" in status["hint"] and status["corpus_written"] is False
    assert "PDF 抽出ライブラリ未インストール" in (tmp_path / "home" / "latest_status.txt").read_text(encoding="utf-8")
    assert (inbox / "issue.pdf").exists()
    store.close()


# ------------------------------------------------------------ 3. setup readiness

def test_readiness_requires_extractor(tmp_path):
    cfg = MobileIntakeConfig()
    home = tmp_path / "home"
    (tmp_path / "sync").mkdir()
    inbox = tmp_path / "sync" / "CompassInbox"
    init(cfg, home=home, inbox_dir=inbox, data_root_dir=tmp_path / "root", provider="ICLOUD_DRIVE",
         python_exe="python", repo_root=REPO_ROOT)
    local = LocalConfig(home=home, inbox_dir=inbox, data_root=tmp_path / "root", provider="ICLOUD_DRIVE")
    missing = readiness(cfg, local, repo_root=REPO_ROOT, task_registered=True, env={},
                        extractor_info={"available": False, "module": "pypdf", "version": "", "error_type": "ModuleNotFoundError"})
    assert missing["status"] == NOT_READY and missing["checks"]["extractor_available"] is False
    assert any("pip install -r requirements.txt" in d for d in missing["diagnostics"])
    ok = readiness(cfg, local, repo_root=REPO_ROOT, task_registered=True, env={},
                   extractor_info={"available": True, "module": "pypdf", "version": "6.0.0", "error_type": ""})
    assert ok["status"] == READY and ok["checks"]["extractor_version"] == "6.0.0"
    real = readiness(cfg, local, repo_root=REPO_ROOT, task_registered=True, env={})
    assert real["checks"]["extractor_available"] is True                  # この環境の実 pypdf


# ------------------------------------------------------------ 4. corrupt PDF stays document-level

def test_corrupt_pdf_is_document_level_failure_and_batch_continues(tmp_path):
    src = tmp_path / "src"
    src.mkdir()
    corrupt = src / "corrupt.pdf"
    corrupt.write_bytes(b"%PDF-1.4\n" + b"\x00garbage" * 200)
    store = CorpusStore(tmp_path / "corpus")
    r = ingest_path(store, corrupt, config=CCFG, extractor=PypdfExtractor(CCFG.extractor_version), now=NOW,
                    source_type=SOURCE_HISTORICAL_IMPORT)
    assert r.status == st.FAILED and r.reasons[0] in ("PDF_UNREADABLE", "NO_PAGES")
    last = store.last_status_event(r.document_id)
    assert not is_environment_failure(last["reason"]) and "ModuleNotFoundError" not in last["reason"]
    assert store.counts()["documents"] == 1 and store.counts()["status_events"] == 2
    report = batch_import(src, store, corpus_config=CCFG, extractor=PypdfExtractor(CCFG.extractor_version),
                          max_files=10, now=NOW)
    assert report.environment_error == "" and report.processed == 1 and report.duplicates == 1
    assert is_environment_failure(WINDOWS_REASON) and not is_environment_failure("NOT_PDF_BYTES")
    store.close()


# ------------------------------------------------------------ 5. environment-origin FAILED recovers in place

def test_environment_failed_record_recovers_in_place_with_audit_trail(tmp_path):
    texts = {"2026_0618_1.pdf": compass_pages()}
    ex = LiveFakeExtractor(texts, CCFG.extractor_version)
    store = CorpusStore(tmp_path / "corpus")
    pdf = make_pdf(tmp_path / "2026_0618_1.pdf", "0618")
    doc_id = _windows_like_failed_record(store, pdf, NOW - timedelta(days=1))
    assert store.current_status(doc_id) == st.FAILED and store.document(doc_id).page_count == 0
    before_snap = build_snapshot(store, CCFG, NOW)
    assert before_snap.counts["failed"] == 1 and before_snap.counts["usable"] == 0
    # gate: 明示 flag なし → 従来どおり DUPLICATE（再処理しない）
    dup = ingest_path(store, pdf, config=CCFG, extractor=ex, now=NOW, source_type=SOURCE_HISTORICAL_IMPORT)
    assert dup.status == st.DUPLICATE and dup.reasons == ("SAME_HASH_ALREADY_IN_CORPUS",)
    assert recovery_eligibility(store, store.document(doc_id), identity_from_path(pdf).sha256, pdf, ex) == (True, "ELIGIBLE")
    # recovery
    rec = ingest_path(store, pdf, config=CCFG, extractor=ex, now=NOW, source_type=SOURCE_HISTORICAL_IMPORT,
                      recover_environment_failures=True)
    assert rec.status == st.ANALYZED and rec.recovered and not rec.new_document and rec.document_id == doc_id
    history = [(e["status"], e["reason"]) for e in store.status_history(doc_id)]
    assert history[:2] == [(st.RECEIVED, "bytes received"), (st.FAILED, WINDOWS_REASON)]
    assert history[2][0] == st.RECEIVED and history[2][1].startswith(st.RECOVERY_REASON_PREFIX)
    assert [h[0] for h in history[3:]] == [st.VALIDATED, st.EXTRACTION_READY, st.EXTRACTED, st.ANALYZED]
    updated = store.document(doc_id)
    assert updated.page_count == 5 and updated.document_date == "2026-06-18" and updated.storage_locator
    assert verify_original(store.root, updated.storage_locator, updated.sha256)
    assert sum(1 for _ in store.iter_canonical("documents")) == 1                    # 元 row は残る（append-only）
    assert sum(1 for _ in store.iter_canonical("document_updates")) == 1
    after_snap = build_snapshot(store, CCFG, NOW)
    assert after_snap.counts["failed"] == 0 and after_snap.counts["usable"] == 1 and after_snap.date_range == ("2026-06-18", "2026-06-18")
    # index rebuild reproduces the recovered row
    counts = store.counts()
    store.rebuild_index()
    assert store.counts() == counts and store.document(doc_id).page_count == 5 and store.current_status(doc_id) == st.ANALYZED
    # idempotent: recovered document is a normal duplicate from now on
    again = ingest_path(store, pdf, config=CCFG, extractor=ex, now=NOW + timedelta(minutes=1),
                        source_type=SOURCE_HISTORICAL_IMPORT, recover_environment_failures=True)
    assert again.status == st.DUPLICATE and f"{RECOVERY_NOT_ELIGIBLE}:STATUS_NOT_FAILED" in again.reasons
    assert st.can_transition(st.FAILED, st.RECEIVED) and not st.can_transition(st.FAILED, st.ANALYZED)
    store.close()


def test_recovery_gate_rejects_non_environment_failures_and_wrong_conditions(tmp_path):
    texts = {"a.pdf": compass_pages(), "b.pdf": compass_pages(date_jp="2026年6月19日", day="19")}
    ex = LiveFakeExtractor(texts, CCFG.extractor_version)
    store = CorpusStore(tmp_path / "corpus")
    # document-level FAILED（NOT_PDF_BYTES）は対象外
    junk = tmp_path / "junk.pdf"
    junk.write_bytes(b"not a pdf")
    ingest_path(store, junk, config=CCFG, extractor=ex, now=NOW, source_type=SOURCE_HISTORICAL_IMPORT)
    r = ingest_path(store, junk, config=CCFG, extractor=ex, now=NOW, source_type=SOURCE_HISTORICAL_IMPORT,
                    recover_environment_failures=True)
    assert r.status == st.DUPLICATE and f"{RECOVERY_NOT_ELIGIBLE}:FAILURE_NOT_ENVIRONMENT_ORIGIN" in r.reasons
    # environment 由来でも extractor がまだ無ければ回復しない
    a = make_pdf(tmp_path / "a.pdf", "a")
    _windows_like_failed_record(store, a, NOW)
    ok, why = recovery_eligibility(store, store.document(identity_from_path(a).document_id), identity_from_path(a).sha256,
                                   a, UnavailableExtractor({}, version="x"))
    assert (ok, why) == (False, "EXTRACTOR_UNAVAILABLE")
    # 原本が読めなければ回復しない
    ok2, why2 = recovery_eligibility(store, store.document(identity_from_path(a).document_id), identity_from_path(a).sha256,
                                     tmp_path / "missing.pdf", ex)
    assert (ok2, why2) == (False, "SOURCE_NOT_READABLE")
    store.close()


# ------------------------------------------------------------ 6. normal duplicate unchanged

def test_valid_document_is_still_duplicate_even_with_recover_flag(tmp_path):
    texts = {"a.pdf": compass_pages()}
    ex = LiveFakeExtractor(texts, CCFG.extractor_version)
    store = CorpusStore(tmp_path / "corpus")
    a = make_pdf(tmp_path / "a.pdf", "a")
    first = ingest_path(store, a, config=CCFG, extractor=ex, now=NOW, source_type=SOURCE_HISTORICAL_IMPORT)
    assert first.status == st.ANALYZED
    before = store.canonical_counts()
    r = ingest_path(store, a, config=CCFG, extractor=ex, now=NOW, source_type=SOURCE_HISTORICAL_IMPORT,
                    recover_environment_failures=True)
    assert r.status == st.DUPLICATE and f"{RECOVERY_NOT_ELIGIBLE}:STATUS_NOT_FAILED" in r.reasons
    after = store.canonical_counts()
    assert {k: v for k, v in after.items() if k != "duplicates"} == {k: v for k, v in before.items() if k != "duplicates"}
    assert after["duplicates"] == before["duplicates"] + 1
    store.close()


# ------------------------------------------------------------ 7/8. research N+1 and equivalence after recovery

def test_recovered_document_is_n_plus_one_for_research_and_rebuild_equivalent(tmp_path):
    texts = {}
    ex = LiveFakeExtractor(texts, CCFG.extractor_version)
    store = CorpusStore(tmp_path / "corpus")
    for i in range(3):
        name = f"doc{i}.pdf"
        texts[name] = compass_pages(date_jp=DATES[i][0], day=DATES[i][1])
        ingest_path(store, make_pdf(tmp_path / name, name), config=CCFG, extractor=ex, now=NOW,
                    source_type=SOURCE_HISTORICAL_IMPORT)
    texts["doc3.pdf"] = compass_pages(date_jp=DATES[3][0], day=DATES[3][1])
    failed_pdf = make_pdf(tmp_path / "doc3.pdf", "doc3")
    _windows_like_failed_record(store, failed_pdf, NOW)
    rcfg = ResearchConfig()
    research = ResearchStore(tmp_path / "research")
    engine = ResearchEngine(store, research, rcfg, CCFG, MarketConnector())
    r1 = engine.run_incremental(NOW)
    assert len(r1.new_documents) == 3                                        # FAILED は研究対象外
    rec = ingest_path(store, failed_pdf, config=CCFG, extractor=ex, now=NOW + timedelta(minutes=1),
                      source_type=SOURCE_HISTORICAL_IMPORT, recover_environment_failures=True)
    assert rec.recovered and rec.status == st.ANALYZED
    r2 = engine.run_incremental(NOW + timedelta(minutes=2))
    assert r2.new_documents == [rec.document_id] and r2.structures_added == 1 and r2.similarities_added == 3
    rebuilt, _ = engine.run_full_rebuild(tmp_path / "rebuild", NOW + timedelta(minutes=3))
    eq = engine.equivalence(rebuilt)
    assert eq["equal"] and eq["structures"] == 4
    store.close()


def test_processor_recovers_only_when_configured(tmp_path):
    texts = {"phone.pdf": compass_pages()}
    ex = LiveFakeExtractor(texts, CCFG.extractor_version)
    inbox = tmp_path / "inbox"
    inbox.mkdir()
    pdf = make_pdf(inbox / "phone.pdf", "phone")
    ts = NOW.timestamp() - 100
    os.utime(pdf, (ts, ts))
    store = CorpusStore(tmp_path / "root" / "compass_corpus")
    _windows_like_failed_record(store, pdf, NOW - timedelta(hours=1))
    local = LocalConfig(home=tmp_path / "home", inbox_dir=inbox, data_root=tmp_path / "root", provider=adapters.LOCAL_FOLDER)
    default = InboxProcessor(MobileIntakeConfig(sample_interval_seconds=0.0), local, CCFG, store, ex, sleeper=lambda s: None)
    r = default.run_once(NOW)
    assert r.results[0].result == "DUPLICATE"                                # 既定では再処理しない
    recovering = InboxProcessor(MobileIntakeConfig(sample_interval_seconds=0.0, recover_environment_failures=True),
                                LocalConfig(home=tmp_path / "home2", inbox_dir=inbox, data_root=tmp_path / "root",
                                            provider=adapters.LOCAL_FOLDER), CCFG, store, ex, sleeper=lambda s: None)
    r2 = recovering.run_once(NOW + timedelta(minutes=1))
    assert r2.results[0].result == "SUCCESS" and store.current_status(r2.results[0].document_id) == st.ANALYZED
    assert load_mobile_intake_config(REPO_ROOT / "config.yaml").recover_environment_failures is False
    store.close()
