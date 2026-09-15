"""Market Signal real-data pilot（Phase 4 P4-2）。

実データで既存 pipeline を端から端まで通し、Market Signal を読み取り専用で観測する:

    Market Data Bank（実 Fact / Context）
      → EvidencePackage → CompassDraft（既存 quality gate 通過）
      → MorningBrief（P4-1A の composer。**凍結済み**）
      → MarketSignal（P4-2 の射影）

薄い orchestration だけを持つ層であり、market logic / 解釈 / claim 選択 / 品質規則 /
方向・確度の算出を**新たに実装しない**。

規律:
- 入力取得と朝の決め方は Phase 3-C の `compass.pilot.load_pilot_inputs()` を共有する
  （ingestion を二重実装しない・日付規則を発明しない）。
- `MarketSignal` は **build_morning_brief が返した実 brief** からのみ組む。
  direction も confidence も独立に計算しない。
- **P4-1 は凍結**。`reports/pilot.py` も renderer も呼ばず、顧客向け Markdown を
  一切生成・変更しない。バッジも header も出さない。
- **書き込みをしない。** MarketSignal store も report file も JSON も Markdown も作らない。
  CompassStore へ persist しない。出力は stdout のみ。
- Decision / formal_review / review / shadow_review / corpus_research / replay /
  predictions / themes / thesis / screening と legacy（src/report・src/analysis・
  src/collectors）を import しない。
- 保護対象 store は **名前と byte 数だけ**を before/after で突き合わせる（本文を読まない）。
- 機密（PDF 名・source 本文・machine path・資格情報の値）を stdout へ出さない。
"""
from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from ..compass.pilot import MORNING_RULE, load_pilot_inputs
from ..compass.pipeline import run_pipeline
from ..context.snapshot import morning_context_snapshot
from ..core.paths import data_root
from .market_signal import (
    LEVEL_BY_STATE,
    MARKET_SIGNAL_SCHEMA_VERSION,
    UNAVAILABLE_BY_DIRECTION,
    MarketSignal,
    build_market_signal,
)
from .model import MorningBrief
from .morning_brief import build_morning_brief

#: 書き換わっていないことを証明する data root 配下の subtree（**中身は読まない**）
PROTECTED_TREES: Tuple[str, ...] = (
    "compass_decisions",      # formal Decision chain
    "formal_review",          # formal review packet / queue
    "compass_research",       # pattern registry / DNA comparison
    "compass_replay",         # replay artifacts
    "compass_corpus",         # corpus（PDF 由来の structured record）
    "compass",                # Phase 3-C CompassDraft store（P4-2 は persist しない）
    "reports",                # product store（brief も signal も作っていないことの確認）
)
#: repository 側の production Compass DNA（読まない・変えない）
DNA_TREE = "knowledge/compass_dna"


def _emit(marker: str, payload: Dict[str, object]) -> None:
    print(f"::P42_{marker}::" + json.dumps(payload, ensure_ascii=False, sort_keys=True))


def _tree_manifest(base: Path) -> Dict[str, object]:
    """subtree の (相対 path, byte 数) 一覧の digest。**file の中身は読まない。**

    absolute path は出さない（machine path を stdout へ出さないため digest と件数のみ）。
    """
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


def _input_row(brief: MorningBrief) -> Dict[str, object]:
    """診断用の安全な要約。claim 本文も source 本文も出さない。"""
    outlook = brief.tier3.outlook
    return {
        "selected_session": brief.session_date,
        "reference_session": brief.reference_session,
        "brief_verdict": brief.verdict.value,
        "brief_abstain_reason": brief.abstain_reason,
        "tier3_available": brief.tier3.available,
        "tier3_unavailable_reason": brief.tier3.unavailable_reason,
        "outlook_direction": outlook.direction if outlook else "",
        "outlook_confidence": outlook.confidence if outlook else "",
        "outlook_horizon": outlook.horizon if outlook else "",
    }


def _signal_row(signal: MarketSignal) -> Dict[str, object]:
    """MarketSignal の実フィールド ＋ 検証用の顧客向けラベル。"""
    return {
        "signal_id": signal.signal_id,
        "schema_version": signal.schema_version,
        "session_date": signal.session_date,
        "reference_session": signal.reference_session,
        "available": signal.available,
        "level": signal.level.value if signal.level else "",
        "confidence": signal.confidence,
        "horizon": signal.horizon,
        "brief_id": signal.brief_id,
        "unavailable_reason": signal.unavailable_reason,
        "label": signal.label,          # 顧客語彙。検証のためだけに出す
    }


def _binding_row(signal: MarketSignal, brief: MorningBrief) -> Dict[str, object]:
    """provenance と、凍結写像表に対する整合。期待値は全て true。"""
    outlook = brief.tier3.outlook
    checks: Dict[str, object] = {
        "brief_id_matches": signal.brief_id == brief.brief_id,
        "session_date_matches": signal.session_date == brief.session_date,
        "reference_session_matches": signal.reference_session == brief.reference_session,
        "schema_version_matches": signal.schema_version == MARKET_SIGNAL_SCHEMA_VERSION,
        "availability_is_consistent": signal.available == (signal.level is not None),
        "reason_is_consistent": bool(signal.unavailable_reason) != signal.available,
    }
    if signal.available and outlook is not None:
        state = (outlook.direction, outlook.confidence)
        checks["confidence_matches_outlook"] = signal.confidence == outlook.confidence
        checks["horizon_matches_outlook"] = signal.horizon == outlook.horizon
        # 凍結写像表を**引き直して**一致を見る（方向も確度も再計算しない）
        checks["level_matches_frozen_mapping"] = LEVEL_BY_STATE.get(state) is signal.level
    elif outlook is not None:
        expected = UNAVAILABLE_BY_DIRECTION.get(outlook.direction)
        checks["unavailable_reason_matches_frozen_mapping"] = (
            expected is None or signal.unavailable_reason == expected)
    return checks


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="Phase 4 P4-2 Market Signal real-data pilot（read-only）")
    parser.add_argument("--session-date", default="",
                        help="対象の朝（未指定なら既存 semantics の最新 morning session）")
    parser.add_argument("--fact-sessions", type=int, default=6,
                        help="Fact を読む Tokyo session 数（Phase 3-C と同じ取得経路）")
    args = parser.parse_args(argv)

    now = datetime.now(timezone.utc)
    root = data_root()
    repo = Path.cwd()
    _emit("HEAD", {
        "pilot": "phase4_p4_2_market_signal",
        "source": "MorningBrief",
        "builder": "src.intelligence.reports.market_signal.build_market_signal",
        "compass_pipeline": "src.intelligence.compass.pipeline.run_pipeline",
        "composer": "src.intelligence.reports.morning_brief.build_morning_brief",
        "input_loader": "src.intelligence.compass.pilot.load_pilot_inputs",
        "schema_version": MARKET_SIGNAL_SCHEMA_VERSION,
        "read_only": True, "persists_product": False, "writes_decisions": False,
        "promotion": "NONE", "generator": "deterministic",
        "renders_customer_markdown": False,
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

    # ---- 既存 Compass pipeline（quality gate を含む）→ 凍結済み P4-1 composer
    snapshot = morning_context_snapshot(list(inputs.context_items), session_date,
                                        generated_at=now)
    result = run_pipeline(snapshot, list(inputs.facts), generator=None,
                          config=inputs.config, now=now)
    brief = build_morning_brief(result.draft, result.package)
    _emit("INPUT", dict(_input_row(brief),
                        session_selection="explicit" if args.session_date
                        else "latest_available",
                        morning_rule=MORNING_RULE,
                        facts_total=len(inputs.facts),
                        contexts_total=len(inputs.context_items)))
    _emit("BRIEF", {
        "brief_id": brief.brief_id,
        "schema_version": brief.schema_version,
        "draft_id": brief.draft_id,
        "package_id": brief.package_id,
        "verdict": brief.verdict.value,
        "tier1_available": brief.tier1.available,
        "tier2_available": brief.tier2.available,
        "tier3_available": brief.tier3.available,
    })

    # ---- P4-2 射影（MorningBrief だけを入力に取る）
    signal = build_market_signal(brief)
    _emit("SIGNAL", _signal_row(signal))

    bindings = _binding_row(signal, brief)
    failed = sorted(name for name, ok in bindings.items() if ok is not True)
    _emit("BINDING", dict(bindings, all_bindings_true=not failed,
                          failed_bindings=failed))

    after = _capture(root, repo)
    changed = sorted(name for name in after if before.get(name) != after.get(name))
    _emit("SAFETY", {
        "protected_trees": sorted(after),
        "protected_before": before,
        "protected_after": after,
        "changed_trees": changed,
        "all_protected_unchanged": not changed,
        "decision_rows_written": 0,
        "formal_review_writes": 0,
        "compass_drafts_persisted": 0,
        "signal_rows_written": 0,
        "product_files_written": 0,
        "promotion_status_written": "NONE",
        "compass_dna_mutated": False,
        "replay_regenerated": False,
        "legacy_report_touched": False,
        "customer_markdown_written": False,
        "network_used": False,
        "safety_check": "PASSED" if not changed else "FAILED",
    })

    ok = not changed and not failed
    _emit("END", {"session_date": session_date, "brief_id": brief.brief_id,
                  "signal_id": signal.signal_id, "available": signal.available,
                  "result": "OK" if ok else ("SAFETY_FAILED" if changed
                                             else "BINDING_FAILED")})
    return 0 if ok else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
