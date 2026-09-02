"""Phase 3.7 Compass Corpus Foundation のオフラインテスト（ネットワーク・LLM・credential 不使用）。

identity / hash determinism / duplicate（同名・改名・同日別 PDF）/ PDF validation / family /
quarantine / document date / immutable original / extraction・page provenance / structured record /
observation level 分離 / quality / temporal semantics / market alignment / coverage label・determinism /
milestones / underrepresentation / analysis version・reanalysis・supersession / canonical append-only /
SQLite rebuild / idempotency / CorpusSnapshot / inbox contract / partial file 保護 / offline /
secret hygiene / production data 不変。
合成 PDF（%PDF- magic + FakeExtractor の page text）を使い、機密原本には依存しない。
"""
from __future__ import annotations

import json
import os
import socket
import stat
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

import pytest

from src.intelligence.corpus import alignment, coverage, milestones, status as st
from src.intelligence.corpus.config import CorpusConfig, config_from_mapping, load_corpus_config
from src.intelligence.corpus.extraction import (
    KIND_BULLET,
    KIND_TABLE_ROW,
    KIND_TEXT,
    FakeExtractor,
    extract_artifacts,
)
from src.intelligence.corpus.family import HIGH, LOW, MEDIUM, detect_family
from src.intelligence.corpus.header_values import STATUS_COMPLETE, STATUS_MISSING, parse_header_table, parse_secondary_table, value_map
from src.intelligence.corpus.identity import document_id_for, identity_from_bytes, identity_from_path, sha256_bytes
from src.intelligence.corpus.inbox import (
    OUTCOME_SKIPPED_LOCKED,
    OUTCOME_SKIPPED_NOT_PDF,
    OUTCOME_SKIPPED_PROCESSED,
    OUTCOME_SKIPPED_UNSTABLE,
    OUTCOME_SUCCESS,
    STATE_STABLE,
    STATE_UNSTABLE,
    acquire_lock,
    inbox_contract,
    is_stable,
    process_inbox,
    release_lock,
    scan_inbox,
)
from src.intelligence.corpus.intake import (
    ACCEPTED,
    OUTCOME_REJECTED,
    SOURCE_LOCAL_FILE,
    SOURCE_MOBILE_UPLOAD,
    CompassIntakeService,
    IntakeRequest,
)
from src.intelligence.corpus.inventory import DERIVED_HISTORICAL_ARTIFACT, PDF_SOURCE, inventory
from src.intelligence.corpus.page_sections import GLOBAL_STRATEGY, P1_JP_OUTLOOK, P2_MODE_FX, section_summary
from src.intelligence.corpus.pipeline import ingest_path, reanalyze_document
from src.intelligence.corpus.quality import LIMITED_USE, PARTIAL, VALID, assess_quality
from src.intelligence.corpus.quality import QUARANTINED as Q_QUARANTINED
from src.intelligence.corpus.snapshot import build_snapshot, coverage_summary, write_snapshot
from src.intelligence.corpus.source import SourceIntegrityError, store_original, verify_original
from src.intelligence.corpus.store import CorpusStore
from src.intelligence.corpus.structured_record import (
    ANALYST_INTERPRETATION,
    LEVELS,
    OUTLOOK,
    RISK,
    SOURCE_STATEMENT,
    SYSTEM_DERIVED_LABEL,
    CATEGORIES,
    classify_statement,
    event_state_from_text,
)
from src.intelligence.corpus.temporal import (
    BASIS_CALENDAR,
    BASIS_NO_CALENDAR,
    UNKNOWN,
    extract_document_date,
    resolve_referenced_session,
    temporal_semantics,
)
from src.intelligence.corpus.validation import R_DATE_MISSING, R_NOT_PDF, R_PAGE_COUNT, validate_document
from src.intelligence.corpus.versioning import current_analysis, supersession_chain

NOW = datetime(2026, 9, 2, 6, 0, tzinfo=timezone.utc)
CFG = CorpusConfig()
REPO_ROOT = Path(__file__).resolve().parents[2]
CORPUS_PKG = REPO_ROOT / "src" / "intelligence" / "corpus"

BANNER = "この資料は、社員の皆様への連絡等を目的として作成された資料です。お客様への配布は厳禁といたします｡\n社外秘（岡三証券社内限・関連会社及び友好証券社内限）\n"
LEVELS_ROW = "69,902.25 65,001.82 4,013.23 10.41 51,492.55 7,420.10 26,021.66 2.595 4.489 160.57"
CHANGES_ROW = "+0.72% +7.54% +0.55% -1.49 -0.98% -1.21% -1.34% -0.050 +0.049 +0.14"


def page1(date_jp: str = "2026年6月18日", day: str = "18", levels: str = LEVELS_ROW,
          changes: str = CHANGES_ROW, with_title: bool = True, with_footnote: bool = True) -> str:
    title = "ストラテジーのベストアイディア\nグローバル投資の\n羅針盤\n" if with_title else "ストラテジーのベストアイディア\n"
    foot = (f"作成：岡三証券 日経平均25日MAの前日比は日経平均との乖離率、ﾌﾟﾗｲﾑ売買代金は前日比変化額、"
            f"各種利回り・為替は変化幅 ドル円は東京時間{day}日7時時点（単位：%pt・円）\n") if with_footnote else "作成：岡三証券\n"
    return (BANNER + title + f"{date_jp}（木）7:30\n" + foot +
            "日経平均 日経平均\n25日MA※ TOPIX ﾌﾟﾗｲﾑ売買代金\n（兆円）※ NYダウ S&P500 ナスダック\n日10年国債\n米10年国債\n利回り※ ドル円※\n"
            f"終値 {levels}\n前日比 {changes}\n"
            "本日の日本株相場見通し\n●底堅い展開を想定する\n●米国株高を受けて買いが先行しよう\n●半導体関連に注目したい\n"
            "昨晩の米国株は上昇した。夜間の日経平均先物は前日終値を上回って返ってきた。背景には金利低下があろう。"
            "本日は底堅い展開を想定する。もっとも、利食い売りが重しとなる可能性がある。日銀の金融政策決定会合に注目したい。\n"
            "【半導体関連に注目】\n半導体株の物色の広がりが期待できよう。売買代金上位20位の占有率が60％前後に上昇した。\n"
            "出所：QUICK 作成：岡三証券\n")


def page2(fx: bool = True) -> str:
    left = ("●目先のドル円相場は狭いレンジ内での推移となろう\n目先のドル円相場予想レンジは1ドル＝159～162円\n"
            "目先のドル円相場は1ドル＝160円台の狭いレンジでの推移を見込む。日米金利差が意識されよう。\n") if fx else (
            "●米国株相場は堅調な推移を想定する\n米国株相場は決算を受けて上昇しよう。ハイテク株に注目したい。\n")
    return (BANNER + "グローバル投資戦略 ＆ 要人発言・イベント等の結果\n主な株価・市況関連指数\n" + left +
            "騰落率 終値 前日比\n株価指数 終値 前日比\nその他指数 終値 前日比\n（%） V/G 終値 前日比\n"
            "ラッセル2000 2,917.98 -0.72 +17.57 TOPIXバリュー 5,046.97 +0.41 +19.44\n"
            "SOX 13,477.07 +1.38 +90.27 TOPIXグロース 4,508.89 +0.91 +15.88\n"
            "VIX 18.44 +12.37 +23.34\nMOVE 70.66 +5.02 +10.48\n"
            "FRB議長、利下げを急がない姿勢を示す（6/17）\n出所：各種資料 作成：岡三証券\n")


def page3() -> str:
    return (BANNER + "グローバル投資アイデア\nストラテジスト 入間田\n"
            "AI向け電力需要の拡大を背景に、電力関連銘柄には投資妙味があろう。もっとも、金利上昇は逆風となる可能性がある。"
            "データセンター投資は2027年にかけて拡大が見込まれる。関連銘柄の業績動向に注目したい。\n"
            "出所：各種資料 作成：岡三証券\n")


def page4() -> str:
    return (BANNER + "注目の日本株\n主役銘柄の業績は26/3期に増益が見込まれる。会社計画を上回る受注が続いている。"
            "出所：会社資料 作成：岡三証券 予想は会社計画、5月7日現在\n" + "本文" * 60 + "\n")


def page5() -> str:
    return BANNER + "▼最新資料\n・日本経済の道標\n岡三好配当セレクション\nグローバル投資の道案内 6月号\n" + "案内" * 80 + "\n"


def compass_pages(**kw) -> list:
    return [page1(**kw), page2(), page3(), page4(), page5()]


def make_pdf(path: Path, seed: str = "a") -> Path:
    """%PDF- magic 付きの合成ファイル（text は FakeExtractor が供給）。seed が違えば bytes が違う。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"%PDF-1.4\n%synthetic compass " + seed.encode("utf-8") + b"\n%%EOF\n")
    return path


def make_store(tmp_path: Path) -> CorpusStore:
    return CorpusStore(tmp_path / "corpus")


def fake(texts: dict, meta: dict = None) -> FakeExtractor:
    return FakeExtractor(texts, version=CFG.extractor_version, metadata=meta)


def ingest(store, path, extractor, now=NOW, **kw):
    return ingest_path(store, path, config=CFG, extractor=extractor, now=now,
                       source_type=SOURCE_LOCAL_FILE, **kw)


# ============================================================ identity / dedup

def test_document_identity_is_hash_based_and_deterministic():
    a = identity_from_bytes(b"%PDF-x", "one.pdf")
    b = identity_from_bytes(b"%PDF-x", "renamed.pdf")
    c = identity_from_bytes(b"%PDF-y", "one.pdf")
    assert a.document_id == b.document_id == document_id_for(sha256_bytes(b"%PDF-x"))
    assert a.document_id.startswith("cmp_") and len(a.document_id) == 24
    assert c.document_id != a.document_id
    assert a.original_filename == "one.pdf" and b.original_filename == "renamed.pdf"


def test_hash_determinism_from_path(tmp_path):
    p = make_pdf(tmp_path / "x.pdf", "seed")
    assert identity_from_path(p).sha256 == identity_from_path(p).sha256 == sha256_bytes(p.read_bytes())


def test_same_pdf_same_filename_is_duplicate(tmp_path):
    store = make_store(tmp_path)
    p = make_pdf(tmp_path / "2026_0618_1.pdf")
    ex = fake({"2026_0618_1.pdf": compass_pages()})
    first = ingest(store, p, ex)
    second = ingest(store, p, ex, now=NOW + timedelta(minutes=1))
    assert first.status == st.ANALYZED and first.new_document
    assert second.status == st.DUPLICATE and second.duplicate_of == first.document_id
    assert len(store.documents()) == 1 and len(store.duplicates()) == 1
    store.close()


def test_same_pdf_renamed_is_duplicate(tmp_path):
    store = make_store(tmp_path)
    p = make_pdf(tmp_path / "2026_0618_1.pdf")
    q = tmp_path / "renamed_from_phone.pdf"
    q.write_bytes(p.read_bytes())
    ex = fake({"2026_0618_1.pdf": compass_pages(), "renamed_from_phone.pdf": compass_pages()})
    first = ingest(store, p, ex)
    second = ingest(store, q, ex)
    assert second.status == st.DUPLICATE and second.duplicate_of == first.document_id
    assert store.duplicates()[0]["original_filename"] == "renamed_from_phone.pdf"
    assert len(store.documents()) == 1
    store.close()


def test_same_date_different_pdf_gets_new_identity_and_sequence(tmp_path):
    store = make_store(tmp_path)
    p = make_pdf(tmp_path / "v1.pdf", "v1")
    q = make_pdf(tmp_path / "v2.pdf", "v2")
    ex = fake({"v1.pdf": compass_pages(), "v2.pdf": compass_pages()})
    r1, r2 = ingest(store, p, ex), ingest(store, q, ex)
    assert r1.document_id != r2.document_id and r2.new_document
    docs = {d.document_id: d for d in store.documents()}
    assert docs[r1.document_id].date_sequence == 1 and docs[r2.document_id].date_sequence == 2
    assert docs[r1.document_id].document_date == docs[r2.document_id].document_date == "2026-06-18"
    store.close()


# ============================================================ validation / family / quarantine

def test_non_pdf_bytes_fail_closed_with_status_event(tmp_path):
    store = make_store(tmp_path)
    p = tmp_path / "junk.pdf"
    p.write_bytes(b"not a pdf at all")
    r = ingest(store, p, fake({}))
    assert r.status == st.FAILED and R_NOT_PDF in r.reasons
    assert [e["status"] for e in store.status_history(r.document_id)] == [st.RECEIVED, st.FAILED]
    assert store.document(r.document_id).storage_locator == ""
    store.close()


def test_page_count_out_of_range_is_quarantined(tmp_path):
    store = make_store(tmp_path)
    p = make_pdf(tmp_path / "short.pdf")
    r = ingest(store, p, fake({"short.pdf": [page1(), page2()]}))
    assert r.status == st.QUARANTINED and R_PAGE_COUNT in r.reasons
    store.close()


def test_family_detection_is_marker_based_not_filename():
    assert detect_family(compass_pages()).confidence == HIGH
    low = detect_family(compass_pages(with_title=False))
    assert low.confidence == LOW and "title_compass" in low.required_missing
    medium = detect_family([page1(with_footnote=False).replace("ストラテジーのベストアイディア\n", "")
                           .replace("本日の日本株相場見通し", "見通し")], min_markers=6)
    assert medium.confidence == MEDIUM


def test_non_compass_pdf_is_quarantined_even_with_compass_filename(tmp_path):
    store = make_store(tmp_path)
    p = make_pdf(tmp_path / "2026_0618_1.pdf")
    r = ingest(store, p, fake({"2026_0618_1.pdf": ["別の資料" * 100] * 5}))
    assert r.status == st.QUARANTINED and any(x.startswith("FAMILY_CONFIDENCE_") for x in r.reasons)
    assert store.current_status(r.document_id) == st.QUARANTINED
    assert store.artifacts_for(r.document_id) == [] and store.analyses_for(r.document_id) == []
    quarantined = store.document(r.document_id)
    assert verify_original(store.root, quarantined.storage_locator, quarantined.sha256)   # 原本は保持
    store.close()


def test_compass_pdf_with_odd_filename_is_accepted(tmp_path):
    store = make_store(tmp_path)
    p = make_pdf(tmp_path / "IMG_4432.bin.pdf")
    r = ingest(store, p, fake({"IMG_4432.bin.pdf": compass_pages()}))
    assert r.status == st.ANALYZED and r.document_date == "2026-06-18"
    store.close()


def test_document_date_extraction_and_conflicts():
    ok = extract_document_date(page1(), {"/CreationDate": "D:20260618073200+09'00'"})
    assert ok.document_date == "2026-06-18" and ok.basis == "PAGE1_TEXT" and ok.conflicts == ()
    foot = extract_document_date(page1(day="19"), {})
    assert foot.document_date == "2026-06-18" and "FOOTNOTE_DAY_MISMATCH" in foot.conflicts
    meta = extract_document_date(page1(), {"/CreationDate": "D:20260619070000"})
    assert "METADATA_DATE_MISMATCH" in meta.conflicts and meta.metadata_date == "2026-06-19"
    missing = extract_document_date(page1().replace("2026年6月18日", ""), {})
    assert missing.document_date == ""


def test_missing_document_date_is_quarantined(tmp_path):
    store = make_store(tmp_path)
    p = make_pdf(tmp_path / "nodate.pdf")
    pages = compass_pages()
    pages[0] = pages[0].replace("2026年6月18日", "")
    r = ingest(store, p, fake({"nodate.pdf": pages}))
    assert r.status == st.QUARANTINED and R_DATE_MISSING in r.reasons
    store.close()


# ============================================================ immutable original

def test_original_is_stored_immutable_and_verified(tmp_path):
    store = make_store(tmp_path)
    p = make_pdf(tmp_path / "orig.pdf")
    before = identity_from_path(p).sha256
    r = ingest(store, p, fake({"orig.pdf": compass_pages()}))
    doc = store.document(r.document_id)
    copy = store.root / doc.storage_locator
    assert copy.is_file() and verify_original(store.root, doc.storage_locator, doc.sha256)
    assert not (copy.stat().st_mode & stat.S_IWUSR)
    assert identity_from_path(p).sha256 == before               # 入力ファイル不変
    with pytest.raises(SourceIntegrityError):
        store_original(store.root, p, r.document_id, "0" * 64)  # hash 不一致は拒否
    copy.chmod(0o644)
    copy.write_bytes(b"%PDF-tampered")
    assert not verify_original(store.root, doc.storage_locator, doc.sha256)
    store.close()


# ============================================================ extraction / provenance

def test_extraction_artifacts_carry_provenance_and_no_ocr():
    summary, artifacts = extract_artifacts("cmp_x", compass_pages(), extractor_name="fake",
                                           extractor_version="fake:1.0.0", min_chars_per_page=200,
                                           created_at=NOW)
    assert summary.text_layer_present and not summary.ocr_attempted and summary.page_count == 5
    assert all(a.document_id == "cmp_x" and a.extractor_version == "fake:1.0.0" for a in artifacts)
    assert all(a.line_start >= 1 and a.line_end >= a.line_start and not a.ocr_derived for a in artifacts)
    bullets = [a for a in artifacts if a.kind == KIND_BULLET and a.page == 1]
    assert len(bullets) == 3 and bullets[0].line_start < bullets[1].line_start
    assert any(a.kind == KIND_TABLE_ROW and a.text.startswith("終値") for a in artifacts)
    again = extract_artifacts("cmp_x", compass_pages(), extractor_name="fake",
                              extractor_version="fake:1.0.0", min_chars_per_page=200, created_at=NOW)[1]
    assert [a.artifact_id for a in again] == [a.artifact_id for a in artifacts]   # deterministic


def test_provenance_chain_reaches_page_location_and_original(tmp_path):
    store = make_store(tmp_path)
    p = make_pdf(tmp_path / "prov.pdf")
    r = ingest(store, p, fake({"prov.pdf": compass_pages()}))
    record = store.current_analysis(r.document_id)
    topic = record["observations"]["selected_topics"][0]
    chain = store.provenance_chain(topic["observation_id"])
    assert chain["record_id"] == record["record_id"]
    assert chain["artifact"]["page"] == 1 and chain["artifact"]["kind"] == KIND_BULLET
    assert chain["artifact"]["line_start"] >= 1
    assert chain["document"]["storage_locator"].endswith(".pdf")
    assert verify_original(store.root, chain["document"]["storage_locator"], chain["document"]["sha256"])
    store.close()


# ============================================================ structured record / levels

def test_structured_record_categories_and_values(tmp_path):
    store = make_store(tmp_path)
    p = make_pdf(tmp_path / "rec.pdf")
    r = ingest(store, p, fake({"rec.pdf": compass_pages()}))
    rec = store.current_analysis(r.document_id)
    assert set(rec["observations"]) == set(CATEGORIES)
    assert rec["counts"]["selected_topics"] == 3 and rec["counts"]["main_theme"] == 1
    assert rec["observations"]["main_theme"][0]["text"].startswith("【")
    values = {o["key"]: o["value"] for o in rec["observations"]["market_values"]}
    assert values["nikkei225_close"] == "69902.25" and values["usd_jpy"] == "160.57"
    assert values["vix_close"] == "18.44" and values["topix_growth_close"] == "4508.89"
    assert rec["p2_mode"] == P2_MODE_FX and rec["sections"][0] == P1_JP_OUTLOOK
    assert rec["counts"]["outlook_statements"] >= 2 and rec["counts"]["risk_statements"] >= 1
    assert rec["counts"]["fx_mentions"] >= 1 and rec["counts"]["breadth_mentions"] >= 1
    assert rec["record_id"].startswith("csr_")
    store.close()


def test_observation_levels_are_separated():
    assert classify_statement("本日は底堅い展開を想定する。") == (OUTLOOK, 4)
    assert classify_statement("押し目買いの好機となろう。") == (OUTLOOK, 5)
    assert classify_statement("上値追いには警戒が必要だ。")[0] == RISK
    assert classify_statement("背景には金利低下があろう。")[0] == ANALYST_INTERPRETATION
    assert classify_statement("昨晩の米国株は上昇した。") == (SOURCE_STATEMENT, None)
    assert classify_statement("利益確定売りが出る可能性がある。") == (OUTLOOK, 1)
    assert classify_statement("もっとも、利食い売りが重しとなる可能性がある。") == (RISK, 1)


def test_system_labels_never_masquerade_as_source_text(tmp_path):
    store = make_store(tmp_path)
    p = make_pdf(tmp_path / "lv.pdf")
    r = ingest(store, p, fake({"lv.pdf": compass_pages()}))
    rec = store.current_analysis(r.document_id)
    levels = {o["level"] for cat in rec["observations"].values() for o in cat}
    assert levels <= set(LEVELS) and SYSTEM_DERIVED_LABEL not in levels
    cov = store.coverage_for(r.document_id)
    assert cov["sources"]["equity_direction"] == coverage.SOURCE_EXTRACTED   # label は record 外
    assert event_state_from_text("日銀の会合") == "CENTRAL_BANK"
    store.close()


# ============================================================ quality

def test_quality_grades():
    q = assess_quality("d", family_confidence=HIGH, page_quality=["OK"] * 5, header_status=STATUS_COMPLETE,
                       secondary_count=6, analysis_version="1.0.0", extractor_version="x", created_at=NOW)
    assert q.quality == VALID and q.eligible_for_pattern_evidence
    q = assess_quality("d", family_confidence=HIGH, page_quality=["OK", "LOW_TEXT"], header_status=STATUS_COMPLETE,
                       secondary_count=6, analysis_version="1.0.0", extractor_version="x", created_at=NOW)
    assert q.quality == PARTIAL and not q.eligible_for_pattern_evidence
    q = assess_quality("d", family_confidence=HIGH, page_quality=["OK"], header_status=STATUS_MISSING,
                       secondary_count=6, analysis_version="1.0.0", extractor_version="x", created_at=NOW)
    assert q.quality == LIMITED_USE
    q = assess_quality("d", family_confidence=MEDIUM, page_quality=["OK"], header_status=STATUS_COMPLETE,
                       secondary_count=6, analysis_version="1.0.0", extractor_version="x", created_at=NOW)
    assert q.quality == Q_QUARANTINED


def test_low_text_page_makes_document_partial(tmp_path):
    store = make_store(tmp_path)
    p = make_pdf(tmp_path / "thin.pdf")
    pages = compass_pages()
    pages[3] = BANNER + "注目の日本株\n"     # 200 文字未満
    r = ingest(store, p, fake({"thin.pdf": pages}))
    assert r.status == st.PARTIAL and r.quality == PARTIAL
    assert "low_text_page" in store.quality_for(r.document_id)["reasons"]
    store.close()


# ============================================================ temporal semantics

def test_temporal_semantics_keep_dates_apart():
    days = ["2026-06-15", "2026-06-16", "2026-06-17", "2026-06-18", "2026-06-19", "2026-06-22"]
    t = temporal_semantics("2026-06-18", received_at=NOW,
                           metadata={"/CreationDate": "D:20260618073200+09'00'"}, trading_days=days,
                           body_texts=[page1(), page2()])
    assert t.document_date == "2026-06-18" and t.publication_date == "2026-06-18"
    assert t.publication_time_jst == "07:32:00" and t.received_at.startswith("2026-09-02")
    assert t.referenced_market_session == "2026-06-17" and t.referenced_session_basis == BASIS_CALENDAR
    assert t.future_event_mentions
    # 月曜の号 → 前営業日は金曜（週末を飛ばす）
    assert resolve_referenced_session("2026-06-22", days) == ("2026-06-19", BASIS_CALENDAR)
    # カレンダー無し → 推測せず UNKNOWN（weekday はヒント欄のみ）
    none = temporal_semantics("2026-06-22", received_at=NOW)
    assert none.referenced_market_session == UNKNOWN and none.referenced_session_basis == BASIS_NO_CALENDAR
    assert none.candidate_previous_weekday == "2026-06-19"


# ============================================================ market alignment

def test_market_alignment_statuses_and_no_fact_store_write(tmp_path):
    hv, _ = parse_header_table(page1())
    values = {
        alignment.HEADER_TO_SERIES["nikkei225_close"]: Decimal("69902.25"),   # MATCH
        alignment.HEADER_TO_SERIES["topix_close"]: Decimal("4014.00"),        # NEAR (0.019%)
        alignment.HEADER_TO_SERIES["usd_jpy"]: Decimal("150.00"),             # CONFLICT
    }
    calls = []

    def lookup(series, session):
        calls.append((series, session))
        return values.get(series)

    res = alignment.align_values(document_id="d", header_values=hv, session="2026-06-17", lookup=lookup,
                                 tolerance_pct=Decimal("0.05"), created_at=NOW, analysis_version="1.0.0")
    by_key = {r.key: r.status for r in res}
    assert by_key["nikkei225_close"] == alignment.MATCH
    assert by_key["topix_close"] == alignment.NEAR_MATCH
    assert by_key["usd_jpy"] == alignment.CONFLICT
    assert by_key["jgb10y_yield"] == alignment.NOT_AVAILABLE
    assert all(session == "2026-06-17" for _, session in calls)
    unknown = alignment.align_values(document_id="d", header_values=hv, session=UNKNOWN, lookup=lookup,
                                     tolerance_pct=Decimal("0.05"), created_at=NOW, analysis_version="1.0.0")
    assert {r.status for r in unknown} == {alignment.NOT_COMPARABLE}
    assert not (tmp_path / "facts").exists()   # Fact Store へ何も書かない


def test_alignment_stored_via_pipeline_with_calendar(tmp_path):
    store = make_store(tmp_path)
    p = make_pdf(tmp_path / "al.pdf")
    days = ["2026-06-16", "2026-06-17", "2026-06-18"]
    r = ingest(store, p, fake({"al.pdf": compass_pages()}), trading_days=days,
               market_lookup=lambda s, d: Decimal("69902.25") if s.startswith("index:nikkei225") else None)
    rows = {a["key"]: a for a in store.alignments_for(r.document_id)}
    assert rows["nikkei225_close"]["status"] == alignment.MATCH and rows["nikkei225_close"]["session"] == "2026-06-17"
    assert rows["topix_close"]["status"] == alignment.NOT_AVAILABLE
    store.close()


# ============================================================ coverage

def test_coverage_labels_prefer_context_and_are_deterministic():
    hv, _ = parse_header_table(page1())
    sec = parse_secondary_table(page2())
    kw = dict(document_id="d", document_date="2026-06-18", header=value_map(hv), secondary=value_map(sec),
              event_state_text_label="CENTRAL_BANK", analysis_version="1.0.0", created_at=NOW)
    a = coverage.label_document(**kw)
    b = coverage.label_document(**kw)
    assert a.labels == b.labels and a.label_id == b.label_id
    assert a.labels["equity_direction"] == "UP" and a.sources["equity_direction"] == coverage.SOURCE_EXTRACTED
    assert a.labels["volatility_state"] == "NORMAL"
    assert a.labels["nikkei_vs_topix"] == "IN_LINE"            # +0.72 vs +0.55
    assert a.labels["yen_direction"] == "FLAT"                 # +0.14 < 0.3
    assert a.labels["japan_rate_direction"] == "DOWN" and a.labels["us_rate_direction"] == "UP"
    assert a.labels["turnover_state"] == "CONTRACTING"         # -1.49
    assert a.labels["growth_value_state"] == "GROWTH_LEAD"     # +0.91 vs +0.41 (> 0.3)
    assert a.labels["breadth_state"] == coverage.UNKNOWN and a.sources["breadth_state"] == coverage.SOURCE_UNKNOWN
    assert a.labels["major_event_state"] == "CENTRAL_BANK" and a.sources["major_event_state"] == coverage.SOURCE_TEXT
    c = coverage.label_document(**kw, context_labels={"breadth_state": "BROAD", "equity_direction": "DOWN"})
    assert c.labels["breadth_state"] == "BROAD" and c.sources["breadth_state"] == coverage.SOURCE_CONTEXT
    assert c.labels["equity_direction"] == "DOWN" and c.sources["equity_direction"] == coverage.SOURCE_CONTEXT


def test_coverage_report_flags_underrepresented_and_missing():
    def lab(i, eq):
        return coverage.CoverageLabels(f"l{i}", f"d{i}", "2026-06-18", {"equity_direction": eq},
                                       {"equity_direction": coverage.SOURCE_EXTRACTED}, "1.0.0", "1.0.0", "t")
    labels = [lab(i, "UP") for i in range(3)] + [lab(9, "DOWN")]
    rep = coverage.coverage_report(labels, min_docs_per_label=3)
    eq = rep["dimensions"]["equity_direction"]
    assert eq["well_represented"] == ["UP"] and eq["underrepresented"] == ["DOWN"] and eq["missing"] == ["FLAT"]
    assert "equity_direction=DOWN" in rep["underrepresented_regimes"]
    assert "equity_direction=FLAT" in rep["missing_regimes"]
    assert "breadth_state" in rep["dimensions_fully_unknown"]
    assert rep["labeled_documents"] == 4 and rep["thresholds_version"] == "1.0.0"


def test_milestones():
    m0 = milestones.milestone_status(0)
    assert m0.reached == "NONE" and m0.next_milestone == "CORPUS_10" and m0.documents_needed == 10
    m10 = milestones.milestone_status(10)
    assert m10.reached == "CORPUS_10" and m10.next_milestone == "CORPUS_30" and m10.documents_needed == 20
    m = milestones.milestone_status(250)
    assert m.reached == "CORPUS_200" and m.next_milestone == "" and m.documents_needed == 0
    assert [r["milestone"] for r in m.milestones] == ["CORPUS_10", "CORPUS_30", "CORPUS_50", "CORPUS_100", "CORPUS_200"]


# ============================================================ version / reanalysis / supersession

def test_reanalysis_appends_new_version_and_supersedes(tmp_path):
    store = make_store(tmp_path)
    p = make_pdf(tmp_path / "re.pdf")
    r = ingest(store, p, fake({"re.pdf": compass_pages()}))
    old = store.current_analysis(r.document_id)
    canon_before = store.canonical_counts()
    r2 = reanalyze_document(store, r.document_id, config=CFG, analysis_version="1.1.0", now=NOW + timedelta(days=1))
    assert r2 is not None and r2.analysis_record_id != old["record_id"]
    analyses = store.analyses_for(r.document_id)
    assert len(analyses) == 2 and current_analysis(analyses)["analysis_version"] == "1.1.0"
    assert current_analysis(analyses)["supersedes"] == old["record_id"]
    assert supersession_chain(analyses) == [r2.analysis_record_id, old["record_id"]]
    after = store.canonical_counts()
    assert after["analyses"] == canon_before["analyses"] + 1 and after["documents"] == canon_before["documents"]
    assert verify_original(store.root, store.document(r.document_id).storage_locator, store.document(r.document_id).sha256)
    assert store.current_status(r.document_id) in (st.ANALYZED, st.PARTIAL)
    store.close()


# ============================================================ canonical / rebuild / idempotency

def test_canonical_is_append_only_and_index_rebuilds(tmp_path):
    store = make_store(tmp_path)
    ex = fake({"a.pdf": compass_pages(), "b.pdf": compass_pages(date_jp="2026年6月19日", day="19")})
    ingest(store, make_pdf(tmp_path / "a.pdf", "a"), ex)
    docs_text_1 = store.path_of("documents").read_text(encoding="utf-8")
    ingest(store, make_pdf(tmp_path / "b.pdf", "b"), ex)
    docs_text_2 = store.path_of("documents").read_text(encoding="utf-8")
    assert docs_text_2.startswith(docs_text_1) and docs_text_2.count("\n") == 2
    before = store.counts()
    store.close()
    (tmp_path / "corpus" / "index" / "corpus.sqlite3").unlink()
    fresh = CorpusStore(tmp_path / "corpus")
    assert fresh.counts()["documents"] == 0
    rebuilt = fresh.rebuild_index()
    assert fresh.counts() == before and rebuilt["documents"] == 2 and rebuilt["artifacts"] == before["artifacts"]
    assert fresh.current_status(fresh.documents()[0].document_id) == st.ANALYZED
    fresh.close()


def test_ingest_is_idempotent(tmp_path):
    store = make_store(tmp_path)
    ex = fake({"a.pdf": compass_pages()})
    p = make_pdf(tmp_path / "a.pdf", "a")
    ingest(store, p, ex)
    before = store.canonical_counts()
    ingest(store, p, ex)
    after = store.canonical_counts()
    assert {k: v for k, v in after.items() if k != "duplicates"} == {k: v for k, v in before.items() if k != "duplicates"}
    assert after["duplicates"] == before["duplicates"] + 1
    store.close()


# ============================================================ snapshot

def test_corpus_snapshot_read_model(tmp_path):
    store = make_store(tmp_path)
    ex = fake({"a.pdf": compass_pages(), "b.pdf": compass_pages(date_jp="2026年6月19日", day="19"),
               "q.pdf": ["x" * 300] * 5})
    ingest(store, make_pdf(tmp_path / "a.pdf", "a"), ex)
    ingest(store, make_pdf(tmp_path / "b.pdf", "b"), ex)
    ingest(store, make_pdf(tmp_path / "q.pdf", "q"), ex)
    snap = build_snapshot(store, CFG, NOW)
    assert snap.counts["documents"] == 3 and snap.counts["usable"] == 2 and snap.counts["quarantined"] == 1
    assert snap.date_range == ("2026-06-18", "2026-06-19")
    assert snap.milestones["next_milestone"] == "CORPUS_10" and snap.milestones["documents_needed"] == 8
    assert set(snap.versions) == {"schema_version", "extractor_version", "analysis_version",
                                  "coverage_thresholds_version", "family_markers_version"}
    view = [d for d in snap.documents if d["status"] == st.ANALYZED][0]
    assert view["current_analysis_id"] and view["coverage_labels"]["equity_direction"] == "UP"
    assert view["storage_locator"] and view["sha256"] and view["artifact_count"] > 0
    path = write_snapshot(store.root, snap)
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["snapshot_id"] == snap.snapshot_id
    summary = coverage_summary(snap)
    assert summary["unique_documents"] == 3 and summary["usable_documents"] == 2
    assert "breadth_state" in summary["dimensions_fully_unknown"]
    store.close()


# ============================================================ intake boundary / inbox contract

def test_intake_boundary_rejects_and_accepts(tmp_path):
    store = make_store(tmp_path)
    ex = fake({"phone.pdf": compass_pages()})
    svc = CompassIntakeService(store, CFG, ex)
    p = make_pdf(tmp_path / "phone.pdf")
    bad = svc.submit(IntakeRequest(p, "phone.pdf", "DROPBOX", NOW))
    assert bad.status == OUTCOME_REJECTED
    bad2 = svc.submit(IntakeRequest(p, "phone.jpg", SOURCE_MOBILE_UPLOAD, NOW))
    assert bad2.status == OUTCOME_REJECTED
    ok = svc.submit(IntakeRequest(p, "phone.pdf", SOURCE_MOBILE_UPLOAD, NOW, channel="local"))
    assert ok.status == ACCEPTED and ok.document_id and ok.corpus_status == st.ANALYZED
    dup = svc.submit(IntakeRequest(p, "phone.pdf", SOURCE_MOBILE_UPLOAD, NOW))
    assert dup.status == st.DUPLICATE
    text = (CORPUS_PKG / "intake.py").read_text(encoding="utf-8")
    assert not any(tok in text for tok in ("googleapiclient", "dropbox", "pyicloud", "boto3"))
    store.close()


def test_inbox_contract_protects_partial_files_and_locks(tmp_path):
    store = make_store(tmp_path)
    ex = fake({"stable.pdf": compass_pages(), "copying.pdf": compass_pages()})
    svc = CompassIntakeService(store, CFG, ex)
    contract = inbox_contract(tmp_path / "inbox", CFG)
    stable = make_pdf(contract.incoming_dir / "stable.pdf", "s")
    old = NOW.timestamp() - 60
    os.utime(stable, (old, old))
    copying = make_pdf(contract.incoming_dir / "copying.pdf", "c")   # mtime = 現在
    (contract.incoming_dir / "note.txt").write_text("x")
    states = {c.path.name: c.state for c in scan_inbox(contract, now_ts=NOW.timestamp())}
    assert states["stable.pdf"] == STATE_STABLE and states["copying.pdf"] == STATE_UNSTABLE
    run1 = {r["file"]: r["outcome"] for r in process_inbox(contract, svc, now=NOW)}
    assert run1["stable.pdf"] == OUTCOME_SUCCESS and run1["copying.pdf"] == OUTCOME_SKIPPED_UNSTABLE
    assert run1["note.txt"] == OUTCOME_SKIPPED_NOT_PDF
    assert stable.exists() and copying.exists()                      # 原本を動かさない
    run2 = {r["file"]: r["outcome"] for r in process_inbox(contract, svc, now=NOW)}
    assert run2["stable.pdf"] == OUTCOME_SKIPPED_PROCESSED
    os.utime(copying, (old, old))
    lock = acquire_lock(contract, copying)
    run3 = {r["file"]: r["outcome"] for r in process_inbox(contract, svc, now=NOW)}
    assert run3["copying.pdf"] == OUTCOME_SKIPPED_LOCKED
    release_lock(lock)
    assert acquire_lock(contract, copying) is not None
    assert contract.ledger_path.exists() and contract.as_dict()["moves_or_deletes_originals"] is False
    store.close()


def test_stability_rule():
    assert not is_stable([(10, 100.0)], 200.0, 5)                 # sample 不足
    assert not is_stable([(10, 100.0), (20, 101.0)], 200.0, 5)    # size 変化中
    assert not is_stable([(0, 100.0), (0, 100.0)], 200.0, 5)      # 空ファイル
    assert not is_stable([(10, 198.0), (10, 198.0)], 200.0, 5)    # mtime が新しすぎる
    assert is_stable([(10, 100.0), (10, 100.0)], 200.0, 5)


# ============================================================ inventory

def test_inventory_counts_unique_hashes_and_separates_derived(tmp_path):
    a = tmp_path / "dirA"
    b = tmp_path / "dirB"
    make_pdf(a / "x.pdf", "x")
    make_pdf(b / "x_copy.pdf", "x")
    make_pdf(b / "y.pdf", "y")
    derived = tmp_path / "SPEC.md"
    derived.write_text("# derived", encoding="utf-8")
    inv = inventory([a, b, tmp_path / "missing"], derived_paths=[derived])
    assert inv.unique_pdf_documents == 2 and inv.duplicate_copies == 1
    assert inv.missing_dirs == (str(tmp_path / "missing"),)
    assert {i.kind for i in inv.pdf_items} == {PDF_SOURCE}
    assert inv.derived_items[0].kind == DERIVED_HISTORICAL_ARTIFACT and inv.derived_items[0].document_id == ""
    assert inv.as_dict()["derived_artifacts"] == 1
    empty = inventory([tmp_path / "nothing"])
    assert empty.unique_pdf_documents == 0 and not empty.pdf_items       # 捏造しない


# ============================================================ security / offline / production data

def test_corpus_package_is_offline_and_secret_free():
    bad_net, bad_secret = [], []
    for py in sorted(CORPUS_PKG.glob("*.py")):
        text = py.read_text(encoding="utf-8")
        for tok in ("import requests", "import urllib", "from urllib", "http.client", "import socket", "httpx"):
            if tok in text:
                bad_net.append(f"{py.name}:{tok}")
        for tok in ("API" + "_KEY", "os." + "environ", "getenv" + "("):
            if tok in text:
                bad_secret.append(f"{py.name}:{tok}")
    assert bad_net == [] and bad_secret == []
    cfg_text = (REPO_ROOT / "config.yaml").read_text(encoding="utf-8")
    section = cfg_text[cfg_text.index("compass_corpus:"):]
    assert not any(tok in section for tok in ("sk-", "AKIA", "ghp_", "Bearer", "token"))


def test_ingest_works_with_network_disabled(tmp_path, monkeypatch):
    def boom(*a, **k):
        raise AssertionError("network use forbidden")

    monkeypatch.setattr(socket, "socket", boom)
    monkeypatch.setattr(socket, "create_connection", boom)
    store = make_store(tmp_path)
    r = ingest(store, make_pdf(tmp_path / "off.pdf"), fake({"off.pdf": compass_pages()}))
    assert r.status == st.ANALYZED
    store.close()


def test_production_roots_are_not_touched(tmp_path, monkeypatch):
    monkeypatch.setenv("INTELLIGENCE_DATA_ROOT", str(tmp_path / "prod_root"))
    store = CorpusStore(tmp_path / "isolated")
    ingest(store, make_pdf(tmp_path / "p.pdf"), fake({"p.pdf": compass_pages()}))
    assert not (tmp_path / "prod_root").exists()
    assert not (tmp_path / "isolated" / "facts").exists() and not (tmp_path / "isolated" / "contexts").exists()
    store.close()


def test_confidential_paths_not_in_corpus_code():
    for py in CORPUS_PKG.glob("*.py"):
        text = py.read_text(encoding="utf-8")
        assert "date/" + "rashinban" not in text and "research/" + "source_docs" not in text


def test_config_section_loads():
    cfg = load_corpus_config(REPO_ROOT / "config.yaml")
    assert cfg.source_dir and cfg.milestones == (10, 30, 50, 100, 200)
    assert cfg.analysis_version == "1.0.0" and cfg.alignment_tolerance_pct == Decimal("0.05")
    assert config_from_mapping({"milestones": ["x"], "family_min_markers": "bad"}).milestones == (10, 30, 50, 100, 200)


def test_status_transitions():
    assert st.can_transition("", st.RECEIVED) and st.can_transition(st.RECEIVED, st.QUARANTINED)
    assert st.can_transition(st.EXTRACTED, st.PARTIAL) and not st.can_transition(st.FAILED, st.VALIDATED)
    assert not st.can_transition(st.RECEIVED, st.ANALYZED)


def test_sections_and_header_parsing():
    ss = section_summary(compass_pages())
    assert ss["sections"][:2] == [P1_JP_OUTLOOK, GLOBAL_STRATEGY] and ss["p2_mode"] == P2_MODE_FX
    hv, status = parse_header_table(page1())
    assert status == STATUS_COMPLETE and len(hv) == 10 and hv[3].change == Decimal("-1.49")
    closed, status2 = parse_header_table(page1(levels="1 2 3 4 Closed Closed Closed 2.6 Closed 160",
                                               changes="+1% +2% +3% +4 Closed Closed Closed +0.01 Closed +0.1"))
    assert status2 == STATUS_COMPLETE and closed[4].closed and closed[8].closed and closed[0].level == Decimal("1")
    assert parse_header_table("no table here")[1] == STATUS_MISSING


# ============================================================ pilot（offline smoke）

def test_pilot_runs_offline_on_synthetic_corpus(tmp_path, monkeypatch, capsys):
    from src.intelligence.corpus import pilot

    src = tmp_path / "src"
    texts = {}
    for i, (d, day) in enumerate([("2026年6月18日", "18"), ("2026年6月19日", "19"), ("2026年6月22日", "22")]):
        name = f"doc{i}.pdf"
        make_pdf(src / name, name)
        texts[name] = compass_pages(date_jp=d, day=day)
    texts["renamed_copy.pdf"] = texts["doc0.pdf"]
    texts["same_date_resaved.pdf"] = texts["doc0.pdf"]
    texts["not_compass.pdf"] = ["unrelated " * 60] * 5
    texts["stable.pdf"] = texts["doc1.pdf"]
    texts["copying.pdf"] = texts["doc1.pdf"]
    monkeypatch.setattr(pilot, "PypdfExtractor", lambda version: fake(texts))
    monkeypatch.setattr(pilot, "_resave_pdf", lambda s, d: make_pdf(d, "resaved"))
    monkeypatch.setattr(pilot, "_blank_pdf", lambda d: make_pdf(d, "blank"))
    monkeypatch.setenv("INTELLIGENCE_DATA_ROOT", str(tmp_path / "prod"))
    rc = pilot.main(["--source", str(src), "--root", str(tmp_path / "pilot_root")])
    out = capsys.readouterr().out
    assert rc == 0
    markers = {m for m in ("P37_INPUT", "P37_INVENTORY", "P37_INGEST", "P37_PROVENANCE", "P37_TEMPORAL",
                           "P37_ALIGNMENT", "P37_QUALITY", "P37_COVERAGE", "P37_MILESTONES",
                           "P37_REANALYSIS", "P37_REBUILD", "P37_IDEMPOTENCY", "P37_DEDUP",
                           "P37_INBOX", "P37_SECURITY", "P37_SUMMARY") if f"::{m}::" in out}
    assert len(markers) == 16
    summary = json.loads(out.split("::P37_SUMMARY::")[1].splitlines()[0])
    assert summary["unique_documents"] == 3 and summary["dedup_ok"] and summary["quarantine_ok"]
    assert summary["failed_ok"] and summary["rebuild_consistent"] and summary["idempotent"]
    assert not (tmp_path / "prod" / "compass_corpus").exists()
    for verbatim in ("底堅い展開を想定する", "半導体株の物色"):
        assert verbatim not in out                                # 本文を marker に出さない
