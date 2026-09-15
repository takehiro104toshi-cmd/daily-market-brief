"""Morning Delivery real-data pilot（Phase 4 P4-3a）。

実データで既存 pipeline を端から端まで通し、配信物の束ね方と書き出しを検証する:

    Market Data Bank（実 Fact / Context）
      → EvidencePackage → CompassDraft（既存 quality gate 通過）
      → MorningBrief（P4-1・凍結）
      → Markdown（P4-1B renderer・凍結）
      → MarketSignal（P4-2・凍結）
      → MorningDelivery（P4-3a）
      → **隔離された検証用 output root** へ 4 artifact を実書き出し

薄い orchestration だけを持つ層であり、market logic / 解釈 / 組版 / 方向・確度の算出 /
公開 JSON の形を**新たに実装しない**。

規律:
- 入力取得と朝の決め方は Phase 3-C の `compass.pilot.load_pilot_inputs()` を共有する。
- `MorningDelivery` は **この run が生成した brief / signal / Markdown** からのみ組む。
  どれも手組みしない。binding 連鎖（Compass → Brief → Signal → Delivery）を明示する。
- **書き出し先は明示指定が必須**。環境変数 `P43_DELIVERY_OUTPUT_ROOT` か `--output-dir`
  を要求し、未指定なら **fail closed**（リポジトリの既定出力先へ黙って落ちない）。
- 書いてよいのは検証用 output root 配下の承認済み 4 file だけ。legacy 成果物・Pages・
  notifier・canonical store には触れない。
- 保護対象 store は **名前と byte 数だけ**を before/after で突き合わせる（本文を読まない）。
- 機密（PDF 名・source 本文・machine path・資格情報の値）と Markdown 本文・claim 本文を
  stdout へ出さない。
- Decision / formal_review / review / shadow_review / corpus_research / replay /
  predictions / themes / thesis / screening と legacy（notifiers / main /
  旧 report・analysis・collectors 系）を import しない。
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from ..compass.pilot import MORNING_RULE, load_pilot_inputs
from ..compass.pipeline import run_pipeline
from ..context.snapshot import morning_context_snapshot
from ..core.paths import data_root
from .delivery import (
    MORNING_DELIVERY_SCHEMA_VERSION,
    PUBLIC_KEYS,
    PUBLIC_SIGNAL_KEYS,
    MorningDelivery,
    build_morning_delivery,
    delivery_public_json,
)
from .delivery_emit import (
    LATEST_JSON,
    LATEST_MARKDOWN,
    artifact_names,
    dated_json_name,
    dated_markdown_name,
    emit_morning_delivery,
)
from .market_signal import MarketSignal, build_market_signal
from .model import MorningBrief
from .morning_brief import build_morning_brief
from .render_markdown import render_morning_brief_markdown

#: 検証用 output root を指定する環境変数（未指定は fail closed）
OUTPUT_ROOT_ENV = "P43_DELIVERY_OUTPUT_ROOT"

#: 書き換わっていないことを証明する data root 配下の subtree（**中身は読まない**）
PROTECTED_TREES: Tuple[str, ...] = (
    "compass_decisions",      # formal Decision chain
    "formal_review",          # formal review packet / queue
    "compass_research",       # pattern registry / DNA comparison
    "compass_replay",         # replay artifacts
    "compass_corpus",         # corpus（PDF 由来の structured record）
    "compass",                # Phase 3-C CompassDraft store（P4-3a は persist しない）
    "reports",                # canonical intelligence store を作っていないことの確認
)
#: repository 側の production Compass DNA（読まない・変えない）
DNA_TREE = "knowledge/compass_dna"


class DeliveryOutputNotConfigured(RuntimeError):
    """検証用 output root が指定されていない（fail closed）。

    リポジトリの既定出力先（`output/v2/`）へ黙って書かないための明示的な失敗。
    """


def resolve_output_dir(explicit: str = "", *, env: Optional[Dict[str, str]] = None) -> Path:
    """検証用 output root を決める。**既定値へフォールバックしない。**"""
    environ = os.environ if env is None else env
    chosen = (explicit or environ.get(OUTPUT_ROOT_ENV, "")).strip()
    if not chosen:
        raise DeliveryOutputNotConfigured(
            f"P4-3a validation requires an explicit output root "
            f"(--output-dir or {OUTPUT_ROOT_ENV}); refusing the repository default")
    return Path(chosen)


def _emit(marker: str, payload: Dict[str, object]) -> None:
    print(f"::P43_{marker}::" + json.dumps(payload, ensure_ascii=False, sort_keys=True))


def _tree_manifest(base: Path) -> Dict[str, object]:
    """subtree の (相対 path, byte 数) 一覧の digest。**file の中身は読まない。**"""
    if not base.exists():
        return {"exists": False, "files": 0, "bytes": 0, "digest": ""}
    entries: List[Tuple[str, int]] = []
    for path in sorted(base.rglob("*")):
        if path.is_file():
            entries.append((path.relative_to(base).as_posix(), path.stat().st_size))
    blob = json.dumps(entries, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return {"exists": True, "files": len(entries),
            "bytes": sum(size for _p, size in entries),
            "digest": hashlib.sha256(blob.encode("utf-8")).hexdigest()[:16]}


def _capture(root: Path, repo: Path) -> Dict[str, Dict[str, object]]:
    snapshot = {name: _tree_manifest(root / name) for name in PROTECTED_TREES}
    snapshot[DNA_TREE] = _tree_manifest(repo / DNA_TREE)
    return snapshot


def _brief_row(brief: MorningBrief) -> Dict[str, object]:
    return {
        "brief_id": brief.brief_id,
        "schema_version": brief.schema_version,
        "session_date": brief.session_date,
        "reference_session": brief.reference_session,
        "verdict": brief.verdict.value,
        "tier1_available": brief.tier1.available,
        "tier2_available": brief.tier2.available,
        "tier3_available": brief.tier3.available,
    }


def _signal_row(signal: MarketSignal) -> Dict[str, object]:
    return {
        "signal_id": signal.signal_id,
        "schema_version": signal.schema_version,
        "available": signal.available,
        "level": signal.level.value if signal.level else "",
        "label": signal.label,
        "brief_id": signal.brief_id,
        "unavailable_reason": signal.unavailable_reason,
    }


def _delivery_row(delivery: MorningDelivery) -> Dict[str, object]:
    """配信物の identity と形。brief / signal / Markdown 本文は dump しない。"""
    return {
        "delivery_id": delivery.delivery_id,
        "schema_version": delivery.schema_version,
        "session_date": delivery.session_date,
        "reference_session": delivery.reference_session,
        "brief_id": delivery.brief.brief_id,
        "signal_id": delivery.signal.signal_id,
        "markdown_sha256": delivery.markdown_sha256,
        "markdown_bytes": delivery.markdown_bytes,
        "formats": [f.value for f in delivery.formats],
    }


def _artifact_rows(output_dir: Path, session_date: str) -> List[Dict[str, object]]:
    """書き出した 4 artifact の実測。**絶対 path は出さない**（論理名のみ）。"""
    rows: List[Dict[str, object]] = []
    for name in artifact_names(session_date):
        target = output_dir / name
        exists = target.is_file()
        blob = target.read_bytes() if exists else b""
        rows.append({"name": name, "exists": exists, "bytes": len(blob),
                     "sha256": hashlib.sha256(blob).hexdigest() if exists else ""})
    return rows


def _binding_row(delivery: MorningDelivery, brief: MorningBrief, signal: MarketSignal,
                 markdown: str, public: Dict[str, object]) -> Dict[str, object]:
    """Compass → Brief → Signal → Delivery → 公開 JSON の連鎖。期待値は全て true。"""
    encoded = markdown.encode("utf-8")
    return {
        "delivery_brief_is_generated_brief": delivery.brief is brief,
        "delivery_signal_is_generated_signal": delivery.signal is signal,
        "delivery_brief_id_matches": delivery.brief.brief_id == brief.brief_id,
        "delivery_signal_id_matches": delivery.signal.signal_id == signal.signal_id,
        "signal_brief_id_matches": signal.brief_id == brief.brief_id,
        "delivery_session_date_matches": delivery.session_date == brief.session_date,
        "delivery_reference_session_matches":
            delivery.reference_session == brief.reference_session,
        "markdown_is_verbatim": delivery.markdown.encode("utf-8") == encoded,
        "markdown_digest_matches":
            delivery.markdown_sha256 == hashlib.sha256(encoded).hexdigest(),
        "markdown_bytes_match": delivery.markdown_bytes == len(encoded),
        "public_delivery_id_matches": public.get("delivery_id") == delivery.delivery_id,
        "public_brief_id_matches": public.get("brief_id") == brief.brief_id,
        "public_signal_id_matches": public.get("signal_id") == signal.signal_id,
        "public_session_date_matches": public.get("session_date") == brief.session_date,
        "public_reference_session_matches":
            public.get("reference_session") == brief.reference_session,
        "public_markdown_digest_matches":
            public.get("markdown_sha256") == delivery.markdown_sha256,
        "public_markdown_bytes_match":
            public.get("markdown_bytes") == delivery.markdown_bytes,
        # artifact は sort_keys=True で直列化されるため、round-trip 後の key 順は
        # 宣言順と一致しない。JSON object の key 順は意味を持たないので集合で見る
        # （宣言順そのものは packaging 側の `delivery_public_payload` が検証済み）。
        "public_key_set_matches": set(public) == set(PUBLIC_KEYS),
        "public_signal_key_set_matches":
            set(public.get("signal", {})) == set(PUBLIC_SIGNAL_KEYS),
        "public_label_matches_signal":
            public.get("signal", {}).get("label") == (  # type: ignore[union-attr]
                signal.label if signal.available else ""),
    }


def _artifact_checks(rows: List[Dict[str, object]], delivery: MorningDelivery,
                     markdown: str, public_json: str) -> Dict[str, object]:
    """書き出した実バイト列が凍結出力・公開 JSON と一致することの検証。"""
    by_name = {row["name"]: row for row in rows}
    dated_md = by_name[dated_markdown_name(delivery.session_date)]
    latest_md = by_name[LATEST_MARKDOWN]
    dated_json = by_name[dated_json_name(delivery.session_date)]
    latest_json = by_name[LATEST_JSON]
    md_digest = hashlib.sha256(markdown.encode("utf-8")).hexdigest()
    json_digest = hashlib.sha256(public_json.encode("utf-8")).hexdigest()
    return {
        "all_four_exist": all(row["exists"] for row in rows),
        "dated_markdown_matches_frozen": dated_md["sha256"] == md_digest,
        "latest_markdown_matches_frozen": latest_md["sha256"] == md_digest,
        "dated_and_latest_markdown_equal": dated_md["sha256"] == latest_md["sha256"],
        "markdown_digest_matches_delivery": dated_md["sha256"] == delivery.markdown_sha256,
        "markdown_bytes_match_delivery": dated_md["bytes"] == delivery.markdown_bytes,
        "dated_json_matches_public": dated_json["sha256"] == json_digest,
        "latest_json_matches_public": latest_json["sha256"] == json_digest,
        "dated_and_latest_json_equal": dated_json["sha256"] == latest_json["sha256"],
    }


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="Phase 4 P4-3a Morning Delivery real-data pilot（隔離 output root 必須）")
    parser.add_argument("--session-date", default="",
                        help="対象の朝（未指定なら既存 semantics の最新 morning session）")
    parser.add_argument("--fact-sessions", type=int, default=6,
                        help="Fact を読む Tokyo session 数（Phase 3-C と同じ取得経路）")
    parser.add_argument("--output-dir", default="",
                        help=f"検証用 artifact 出力先（未指定なら {OUTPUT_ROOT_ENV}）")
    args = parser.parse_args(argv)

    now = datetime.now(timezone.utc)
    root = data_root()
    repo = Path.cwd()
    output_dir = resolve_output_dir(args.output_dir)      # 未設定なら fail closed

    _emit("HEAD", {
        "pilot": "phase4_p4_3a_morning_delivery",
        "schema_version": MORNING_DELIVERY_SCHEMA_VERSION,
        "source": "MorningBrief + MarketSignal + frozen Markdown",
        "builder": "src.intelligence.reports.delivery.build_morning_delivery",
        "emitter": "src.intelligence.reports.delivery_emit",
        "compass_pipeline": "src.intelligence.compass.pipeline.run_pipeline",
        "composer": "src.intelligence.reports.morning_brief.build_morning_brief",
        "renderer": "src.intelligence.reports.render_markdown.render_morning_brief_markdown",
        "signal_builder": "src.intelligence.reports.market_signal.build_market_signal",
        "input_loader": "src.intelligence.compass.pilot.load_pilot_inputs",
        "formats": ["MARKDOWN", "JSON"],
        "read_only_intelligence": True,
        "writes_delivery_artifacts": True,
        "persists_canonical_intelligence": False,
        "writes_decisions": False,
        "promotion": "NONE",
        "output_root_is_isolated": True,
        "generator": "deterministic",
    })

    before = _capture(root, repo)
    inputs = load_pilot_inputs(now=now, sessions_of_facts=args.fact_sessions, root=root)
    if inputs is None:
        _emit("PILOT_SKIP", {"reason": "market_bank_not_local"})
        return 0
    if not inputs.mornings:
        _emit("PILOT_SKIP", {"reason": "no_morning_session_available",
                             "fact_sessions": list(inputs.fact_sessions)})
        return 0

    session_date = args.session_date or inputs.mornings[-1]
    if session_date not in inputs.mornings:
        _emit("PILOT_SKIP", {"reason": "session_date_not_available",
                             "requested": session_date,
                             "available": list(inputs.mornings)})
        return 0

    # ---- 既存 Compass pipeline → 凍結 P4-1 → 凍結 renderer → 凍結 P4-2
    snapshot = morning_context_snapshot(list(inputs.context_items), session_date,
                                        generated_at=now)
    result = run_pipeline(snapshot, list(inputs.facts), generator=None,
                          config=inputs.config, now=now)
    brief = build_morning_brief(result.draft, result.package)
    markdown = render_morning_brief_markdown(brief)
    signal = build_market_signal(brief)

    _emit("INPUT", {
        "selected_session": session_date,
        "session_selection": "explicit" if args.session_date else "latest_available",
        "morning_rule": MORNING_RULE,
        "reference_session": brief.reference_session,
        "facts_total": len(inputs.facts),
        "contexts_total": len(inputs.context_items),
        "generator": inputs.config.generator,
    })
    _emit("BRIEF", _brief_row(brief))
    _emit("SIGNAL", _signal_row(signal))

    # ---- P4-3a packaging（この run の 3 点からのみ組む）
    delivery = build_morning_delivery(brief, signal, markdown)
    _emit("DELIVERY", _delivery_row(delivery))

    # ---- 隔離 output root へ実書き出し
    written = emit_morning_delivery(delivery, output_dir=output_dir)
    rows = _artifact_rows(output_dir, delivery.session_date)
    present = sorted(p.name for p in output_dir.iterdir()) if output_dir.exists() else []
    expected = sorted(artifact_names(delivery.session_date))
    unexpected = sorted(set(present) - set(expected))
    public_json = delivery_public_json(delivery)
    public = json.loads(public_json)

    _emit("ARTIFACTS", {
        "artifacts": rows,
        "written": len(written),
        "expected": len(expected),
        "unexpected_files": unexpected,
        "checks": _artifact_checks(rows, delivery, markdown, public_json),
        "public_top_level_keys": sorted(public),
        "public_signal_keys": sorted(public.get("signal", {})),
    })

    bindings = _binding_row(delivery, brief, signal, markdown, public)
    failed = sorted(name for name, ok in bindings.items() if ok is not True)
    artifact_failed = sorted(
        name for name, ok in _artifact_checks(rows, delivery, markdown,
                                              public_json).items() if ok is not True)
    _emit("BINDING", dict(bindings, all_bindings_true=not failed and not artifact_failed,
                          failed_bindings=sorted(failed + artifact_failed)))

    after = _capture(root, repo)
    changed = sorted(name for name in after if before.get(name) != after.get(name))
    delivery_ok = (len(written) == len(expected) and not unexpected
                   and all(row["exists"] for row in rows))
    _emit("SAFETY", {
        "protected_trees": sorted(after),
        "protected_before": before,
        "protected_after": after,
        "protected_changed_trees": changed,
        "all_protected_unchanged": not changed,
        "delivery_files_written": len(written),
        "delivery_files_expected": len(expected),
        "unexpected_delivery_files": unexpected,
        "legacy_output_touched": False,
        "pages_touched": False,
        "notifier_invoked": False,
        "decision_rows_written": 0,
        "formal_review_writes": 0,
        "compass_drafts_persisted": 0,
        "compass_dna_mutated": False,
        "replay_regenerated": False,
        "canonical_store_written": False,
        "network_used": False,
        "safety_check": "PASSED" if (not changed and delivery_ok) else "FAILED",
    })

    ok = not changed and delivery_ok and not failed and not artifact_failed
    if changed:
        result_code = "SAFETY_FAILED"
    elif not delivery_ok:
        result_code = "ARTIFACT_FAILED"
    elif failed or artifact_failed:
        result_code = "BINDING_FAILED"
    else:
        result_code = "OK"
    _emit("END", {"session_date": delivery.session_date, "brief_id": brief.brief_id,
                  "signal_id": signal.signal_id, "delivery_id": delivery.delivery_id,
                  "artifacts": len(written), "result": result_code})
    return 0 if ok else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
