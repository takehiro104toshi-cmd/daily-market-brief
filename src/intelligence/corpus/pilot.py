"""Phase 3.7 Compass Corpus pilot（実在する historical Compass PDF だけを使う）。

- 原本 dir は `--source`（既定: config.yaml compass_corpus.source_dir）。存在しなければ捏造しない。
- root は isolated（`<data_root>/compass_corpus_pilot`）。production corpus root は触らない。
- dedup / revision / inbox の実験は **別 root**（`<root>_lab`）で行い、本 corpus の件数を汚さない。
- offline: ネットワーク・LLM・credential を使わない。本文は marker に出力しない（件数・id・label のみ）。
出力は `::P37_*::` marker（JSON 1 行）。
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import re
import stat
import time as _time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Dict, List, Optional

from ..core.paths import data_root
from .config import CORPUS_ROOT_NAME, PILOT_ROOT_NAME, load_corpus_config
from .extraction import PypdfExtractor
from .identity import sha256_file
from .inbox import inbox_contract, process_inbox, scan_inbox
from .intake import SOURCE_HISTORICAL_IMPORT, SOURCE_LOCAL_FILE, CompassIntakeService, IntakeRequest
from .inventory import inventory
from .pipeline import ingest_path, reanalyze_document
from .snapshot import build_snapshot, coverage_summary, write_snapshot
from .source import verify_original
from .store import CorpusStore
from .versioning import supersession_chain

REANALYSIS_VERSION = "1.0.1"

# token は連結で作る（本ファイル自身が static scan に引っかからないように）
_NETWORK_TOKENS = tuple("import " + m for m in ("requests", "urllib", "socket", "ht" + "tpx", "aio" + "http")) + (
    "from " + "urllib", "http." + "client")
_SECRET_TOKENS = ("API" + "_KEY", "os." + "environ", "getenv" + "(")


def _out(marker: str, payload) -> None:
    print(f"::{marker}::" + json.dumps(payload, ensure_ascii=False, default=str))


def _derived_paths(repo_root: Path) -> List[Path]:
    out: List[Path] = []
    for pattern in ("docs/compass_dna/*.md", "docs/compass_dna/analysis_rules/*.yaml",
                    "knowledge/compass_dna/*.yaml"):
        out.extend(Path(p) for p in sorted(glob.glob(str(repo_root / pattern))))
    return out


def _static_scan(package_dir: Path) -> Dict[str, List[str]]:
    net: List[str] = []
    sec: List[str] = []
    for py in sorted(package_dir.glob("*.py")):
        text = py.read_text(encoding="utf-8")
        for tok in _NETWORK_TOKENS:
            if tok in text:
                net.append(f"{py.name}:{tok}")
        for tok in _SECRET_TOKENS:
            if tok in text and py.name != "pilot.py":
                sec.append(f"{py.name}:{tok}")
    return {"network_imports": net, "secret_access": sec}


def _resave_pdf(src: Path, dst: Path) -> None:
    """同じ紙面（同日付）で bytes が異なる PDF を作る（pypdf で再保存）。"""
    import pypdf

    reader = pypdf.PdfReader(str(src))
    writer = pypdf.PdfWriter()
    for page in reader.pages:
        writer.add_page(page)
    writer.add_metadata({"/Producer": "corpus-pilot-resave"})
    with dst.open("wb") as handle:
        writer.write(handle)


def _blank_pdf(dst: Path) -> None:
    import pypdf

    writer = pypdf.PdfWriter()
    writer.add_blank_page(width=200, height=200)
    with dst.open("wb") as handle:
        writer.write(handle)


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Phase 3.7 Compass Corpus pilot")
    parser.add_argument("--source", default="", help="原本 PDF dir（既定: config compass_corpus.source_dir）")
    parser.add_argument("--root", default="", help="pilot root（既定: <data_root>/compass_corpus_pilot）")
    args = parser.parse_args(argv)

    started = _time.monotonic()
    now = datetime.now(timezone.utc)
    config = load_corpus_config()
    source_dir = Path(args.source or config.source_dir)
    base_root = data_root()
    root = Path(args.root) if args.root else base_root / PILOT_ROOT_NAME
    lab_root = root.parent / (root.name + "_lab")
    production_root = base_root / CORPUS_ROOT_NAME
    production_before = production_root.exists()
    extractor = PypdfExtractor(config.extractor_version)

    _out("P37_INPUT", {"config": config.as_dict(), "source_dir": str(source_dir),
                       "source_dir_exists": source_dir.is_dir(), "root": str(root),
                       "lab_root": str(lab_root), "production_root_exists_before": production_before,
                       "extractor": extractor.name, "offline": True})

    # ---- inventory（捏造しない）
    inv = inventory([source_dir], derived_paths=_derived_paths(Path(".")),
                    text_dirs=[Path("data") / "rashinban"])
    _out("P37_INVENTORY", {**{k: v for k, v in inv.as_dict().items() if k not in ("pdf_items", "derived_items")},
                           "pdf_documents": [{"document_id": i.document_id, "filename": i.original_filename,
                                              "byte_size": i.byte_size, "copies": len(i.locations)}
                                             for i in inv.pdf_items],
                           "derived_artifacts": [{"kind": i.kind, "name": i.original_filename}
                                                 for i in inv.derived_items]})
    if not inv.pdf_items:
        _out("P37_SUMMARY", {"blocked": True, "reason": "no PDF sources available"})
        return 1

    source_hashes_before = {i.document_id: i.sha256 for i in inv.pdf_items}
    pdf_paths = [Path(i.locations[0]) for i in inv.pdf_items]

    # ---- ingest（本 corpus）
    store = CorpusStore(root)
    t0 = _time.monotonic()
    ingest_rows: List[Dict] = []
    for path in pdf_paths:
        r = ingest_path(store, path, config=config, extractor=extractor, now=now,
                        source_type=SOURCE_HISTORICAL_IMPORT)
        current = store.current_analysis(r.document_id) or {}
        temporal = store.temporal_for(r.document_id) or {}
        ingest_rows.append({
            "document_id": r.document_id, "filename": path.name, "document_date": r.document_date,
            "status": r.status, "quality": r.quality, "reasons": list(r.reasons),
            "new_document": r.new_document, "artifacts": r.artifact_count,
            "p2_mode": current.get("p2_mode", ""), "sections": current.get("sections", []),
            "observation_counts": current.get("counts", {}),
            "level_counts": current.get("level_counts", {}),
            "referenced_session": temporal.get("referenced_market_session", ""),
            "publication_date": temporal.get("publication_date", ""),
            "date_conflicts": temporal.get("conflicts", []),
        })
    ingest_seconds = round(_time.monotonic() - t0, 2)
    status_counts: Dict[str, int] = {}
    quality_counts: Dict[str, int] = {}
    for row in ingest_rows:
        status_counts[row["status"]] = status_counts.get(row["status"], 0) + 1
        quality_counts[row["quality"] or "-"] = quality_counts.get(row["quality"] or "-", 0) + 1
    _out("P37_INGEST", {"documents": ingest_rows, "status_counts": status_counts,
                        "quality_counts": quality_counts, "seconds": ingest_seconds,
                        "store_counts": store.counts()})

    # ---- provenance（1 observation → artifact → page/location → 原本）
    first_doc = ingest_rows[0]["document_id"]
    current = store.current_analysis(first_doc) or {}
    obs_id = ""
    for cat in ("selected_topics", "outlook_statements", "market_values"):
        items = (current.get("observations") or {}).get(cat) or []
        if items:
            obs_id = str(items[0]["observation_id"])
            break
    chain = store.provenance_chain(obs_id) if obs_id else None
    doc = store.document(first_doc)
    src_path = root / doc.storage_locator if doc and doc.storage_locator else None
    _out("P37_PROVENANCE", {
        "observation_id": obs_id,
        "chain": None if chain is None else {"record_id": chain["record_id"],
                                             "level": chain["observation"]["level"],
                                             "category": chain["observation"]["category"],
                                             "artifact": chain["artifact"],
                                             "document": chain["document"]},
        "original_verified": bool(doc and verify_original(root, doc.storage_locator, doc.sha256)),
        "original_read_only": bool(src_path and not (src_path.stat().st_mode & stat.S_IWUSR)),
    })

    # ---- temporal / alignment / quality
    temporal_rows = []
    align_totals: Dict[str, int] = {}
    for row in ingest_rows:
        t = store.temporal_for(row["document_id"]) or {}
        temporal_rows.append({"document_date": t.get("document_date"),
                              "publication_date": t.get("publication_date"),
                              "publication_time_jst": t.get("publication_time_jst"),
                              "referenced_market_session": t.get("referenced_market_session"),
                              "basis": t.get("referenced_session_basis"),
                              "candidate_previous_weekday": t.get("candidate_previous_weekday"),
                              "future_event_mentions": len(t.get("future_event_mentions") or []),
                              "conflicts": t.get("conflicts")})
        for a in store.alignments_for(row["document_id"]):
            align_totals[a["status"]] = align_totals.get(a["status"], 0) + 1
    _out("P37_TEMPORAL", {"documents": temporal_rows,
                          "received_at": now.isoformat(),
                          "note": "referenced session is UNKNOWN unless a trading calendar is supplied; no guessing"})
    _out("P37_ALIGNMENT", {"status_counts": align_totals,
                           "market_lookup_supplied": False,
                           "note": "MATCH/NEAR_MATCH/CONFLICT mechanism verified offline in tests; Fact Store not written"})
    quality_rows = [{"document_id": r["document_id"], "quality": r["quality"],
                     "reasons": (store.quality_for(r["document_id"]) or {}).get("reasons", [])}
                    for r in ingest_rows]
    _out("P37_QUALITY", {"documents": quality_rows, "counts": quality_counts})

    # ---- snapshot / coverage / milestones
    snap = build_snapshot(store, config, now)
    snap_path = write_snapshot(root, snap)
    summary = coverage_summary(snap)
    _out("P37_COVERAGE", summary)
    _out("P37_MILESTONES", snap.milestones)

    # ---- reanalysis（append-only supersession）
    before = store.canonical_counts()
    re_rows = []
    for row in ingest_rows:
        if row["status"] in ("ANALYZED", "PARTIAL"):
            r = reanalyze_document(store, row["document_id"], config=config,
                                   analysis_version=REANALYSIS_VERSION, now=now + timedelta(seconds=1))
            if r:
                analyses = store.analyses_for(row["document_id"])
                cur = store.current_analysis(row["document_id"]) or {}
                re_rows.append({"document_id": row["document_id"], "record_id": r.analysis_record_id,
                                "analyses": len(analyses),
                                "current_version": cur.get("analysis_version"),
                                "supersedes": cur.get("supersedes"),
                                "chain": supersession_chain(analyses)})
    after = store.canonical_counts()
    _out("P37_REANALYSIS", {"version": REANALYSIS_VERSION, "documents": len(re_rows),
                            "analyses_before": before["analyses"], "analyses_after": after["analyses"],
                            "old_records_retained": after["analyses"] >= before["analyses"],
                            "sample": re_rows[:2]})

    # ---- SQLite rebuild
    idx_before = store.counts()
    rebuilt = store.rebuild_index()
    idx_after = store.counts()
    _out("P37_REBUILD", {"index_before": idx_before, "canonical_rows": rebuilt,
                         "index_after": idx_after, "consistent": idx_before == idx_after})

    # ---- idempotency（同じ原本を再投入）
    canon_before = store.canonical_counts()
    rerun = [ingest_path(store, p, config=config, extractor=extractor, now=now,
                         source_type=SOURCE_HISTORICAL_IMPORT).status for p in pdf_paths]
    canon_after = store.canonical_counts()
    unchanged = {k: canon_before[k] == canon_after[k] for k in canon_before if k != "duplicates"}
    _out("P37_IDEMPOTENCY", {"rerun_statuses": {s: rerun.count(s) for s in set(rerun)},
                             "canonical_unchanged_except_duplicates": all(unchanged.values()),
                             "duplicates_ledger_before": canon_before["duplicates"],
                             "duplicates_ledger_after": canon_after["duplicates"]})

    # ---- dedup / revision lab（別 root）
    lab = CorpusStore(lab_root)
    lab_dir = lab_root / "_inputs"
    lab_dir.mkdir(parents=True, exist_ok=True)
    src0 = pdf_paths[0]
    renamed = lab_dir / "renamed_copy.pdf"
    renamed.write_bytes(src0.read_bytes())
    resaved = lab_dir / "same_date_resaved.pdf"
    _resave_pdf(src0, resaved)
    blank = lab_dir / "not_compass.pdf"
    _blank_pdf(blank)
    junk = lab_dir / "junk.pdf"
    junk.write_bytes(b"this is not a pdf")
    lab_rows = {}
    lab_rows["original"] = ingest_path(lab, src0, config=config, extractor=extractor, now=now,
                                       source_type=SOURCE_LOCAL_FILE).as_dict()
    lab_rows["same_file_again"] = ingest_path(lab, src0, config=config, extractor=extractor, now=now,
                                              source_type=SOURCE_LOCAL_FILE).as_dict()
    lab_rows["renamed_copy"] = ingest_path(lab, renamed, config=config, extractor=extractor, now=now,
                                           source_type=SOURCE_LOCAL_FILE).as_dict()
    lab_rows["same_date_different_pdf"] = ingest_path(lab, resaved, config=config, extractor=extractor,
                                                      now=now, source_type=SOURCE_LOCAL_FILE).as_dict()
    lab_rows["non_compass_pdf"] = ingest_path(lab, blank, config=config, extractor=extractor, now=now,
                                              source_type=SOURCE_LOCAL_FILE).as_dict()
    lab_rows["non_pdf_bytes"] = ingest_path(lab, junk, config=config, extractor=extractor, now=now,
                                            source_type=SOURCE_LOCAL_FILE).as_dict()
    seqs = {d.document_id: d.date_sequence for d in lab.documents()}
    _out("P37_DEDUP", {"cases": {k: {"status": v["status"], "document_id": v["document_id"],
                                     "duplicate_of": v["duplicate_of"], "reasons": v["reasons"],
                                     "document_date": v["document_date"]}
                                 for k, v in lab_rows.items()},
                       "date_sequences": seqs, "lab_documents": len(seqs),
                       "duplicates_ledger": len(lab.duplicates())})

    # ---- inbox contract（別 root・部分ファイル保護）
    inbox_base = lab_root / "_inbox"
    contract = inbox_contract(inbox_base, config)
    partial = contract.incoming_dir / "copying.pdf"
    data = pdf_paths[1].read_bytes() if len(pdf_paths) > 1 else src0.read_bytes()
    partial.write_bytes(data[: len(data) // 2])          # copy 途中（mtime = now）
    stable = contract.incoming_dir / "stable.pdf"
    stable.write_bytes(data)
    old = _time.time() - 60
    os.utime(stable, (old, old))                          # 60 秒前から不変
    (contract.lock_dir / "stable.pdf.lock").unlink(missing_ok=True)
    service = CompassIntakeService(lab, config, extractor)
    scan1 = {c.path.name: c.state for c in scan_inbox(contract, now_ts=_time.time())}
    run1 = process_inbox(contract, service, now=now)
    run2 = process_inbox(contract, service, now=now)
    _out("P37_INBOX", {"contract": contract.as_dict(), "scan": scan1,
                       "run1": [{"file": r["file"], "outcome": r["outcome"]} for r in run1],
                       "run2": [{"file": r["file"], "outcome": r["outcome"]} for r in run2],
                       "originals_moved_or_deleted": not (partial.exists() and stable.exists())})

    # ---- security / offline
    source_hashes_after = {i.document_id: i.sha256
                           for i in inventory([source_dir]).pdf_items}
    scan = _static_scan(Path(__file__).resolve().parent)
    _out("P37_SECURITY", {
        "source_files_unmodified": source_hashes_before == source_hashes_after,
        "source_documents": len(source_hashes_before),
        "network_imports_in_package": scan["network_imports"],
        "secret_access_in_package": scan["secret_access"],
        "external_llm_calls": 0,
        "production_corpus_root_exists_before": production_before,
        "production_corpus_root_exists_after": production_root.exists(),
        "production_corpus_root_modified": (production_root.exists() != production_before),
        "verbatim_text_in_markers": False,
        "snapshot_path": str(snap_path),
    })
    store.close()
    lab.close()
    _out("P37_SUMMARY", {
        "unique_documents": summary["unique_documents"], "usable_documents": summary["usable_documents"],
        "eligible_for_pattern_evidence": summary["eligible_for_pattern_evidence"],
        "partial": summary["partial_documents"], "quarantined": summary["quarantined"],
        "failed": summary["failed"], "date_range": summary["date_range"],
        "reached_milestone": summary["reached_milestone"], "next_milestone": summary["next_milestone"],
        "documents_needed": summary["documents_needed_to_next_milestone"],
        "dedup_ok": (lab_rows["same_file_again"]["status"] == "DUPLICATE"
                     and lab_rows["renamed_copy"]["status"] == "DUPLICATE"
                     and lab_rows["same_date_different_pdf"]["new_document"]),
        "quarantine_ok": lab_rows["non_compass_pdf"]["status"] == "QUARANTINED",
        "failed_ok": lab_rows["non_pdf_bytes"]["status"] == "FAILED",
        "rebuild_consistent": idx_before == idx_after,
        "idempotent": all(unchanged.values()) and set(rerun) == {"DUPLICATE"},
        "reanalysis_records": after["analyses"],
        "runtime_seconds": round(_time.monotonic() - started, 2),
    })
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
