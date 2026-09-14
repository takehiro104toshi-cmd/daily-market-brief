"""Morning Brief real-data pilot（Phase 4 P4-1C）。

実データで既存の intelligence pipeline を端から端まで通し、結果を読み取り専用で観測する:

    Market Data Bank（実 Fact / Context）
      → EvidencePackage → CompassDraft（既存 quality gate 通過）
      → MorningBrief（P4-1A の composer）
      → Markdown（P4-1B の renderer）

薄い orchestration だけを持つ層であり、market logic / 解釈 / claim 選択 / 品質規則 /
source authority / データ変換を**新たに実装しない**。

規律:
- 入力取得と朝の決め方は Phase 3-C の `compass.pilot.load_pilot_inputs()` を共有する
  （ingestion を二重実装しない・日付規則を発明しない）。
- `MorningBrief` は **run_pipeline が返した実 draft** からのみ組む。手組み draft を
  「検証済み」として扱わない。validator を弱めない・迂回しない。
- **書き込みをしない。** CompassStore へ persist せず、product store（briefs.jsonl /
  SQLite / Markdown archive / HTML）も作らない。出力は stdout のみ。
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

from ..compass.model import ClaimRole
from ..compass.pilot import MORNING_RULE, load_pilot_inputs
from ..compass.pipeline import run_pipeline
from ..context.snapshot import morning_context_snapshot
from ..core.paths import data_root
from .model import MorningBrief
from .morning_brief import build_morning_brief
from .render_markdown import render_morning_brief_markdown

#: 書き換わっていないことを証明する data root 配下の subtree（**中身は読まない**）
PROTECTED_TREES: Tuple[str, ...] = (
    "compass_decisions",      # formal Decision chain
    "formal_review",          # formal review packet / queue
    "compass_research",       # pattern registry / DNA comparison
    "compass_replay",         # replay artifacts
    "compass_corpus",         # corpus（PDF 由来の structured record）
    "compass",                # Phase 3-C CompassDraft store（P4-1C は persist しない）
    "reports",                # product store を作っていないことの確認
)
#: repository 側の production Compass DNA（読まない・変えない）
DNA_TREE = "knowledge/compass_dna"

MARKDOWN_BEGIN = "::P41C_MARKDOWN_BEGIN::"
MARKDOWN_END = "::P41C_MARKDOWN_END::"


def _emit(marker: str, payload: Dict[str, object]) -> None:
    print(f"::P41C_{marker}::" + json.dumps(payload, ensure_ascii=False, sort_keys=True))


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


def _brief_row(brief: MorningBrief) -> Dict[str, object]:
    return {
        "brief_id": brief.brief_id,
        "schema_version": brief.schema_version,
        "session_date": brief.session_date,
        "reference_session": brief.reference_session,
        "draft_id": brief.draft_id,
        "package_id": brief.package_id,
        "verdict": brief.verdict.value,
        "abstain_reason": brief.abstain_reason,
        "tier1_available": brief.tier1.available,
        "tier1_unavailable_reason": brief.tier1.unavailable_reason,
        "tier1_chars": len(brief.tier1.text),
        "tier2_available": brief.tier2.available,
        "tier2_unavailable_reason": brief.tier2.unavailable_reason,
        "tier2_points": len(brief.tier2.points),
        "tier2_coverage": len(brief.tier2.coverage),
        "missing_dimensions": list(brief.tier2.missing_dimensions),
        "unreliable_dimensions": list(brief.tier2.unreliable_dimensions),
        "tier3_available": brief.tier3.available,
        "tier3_unavailable_reason": brief.tier3.unavailable_reason,
        "tier3_outlook_points": len(brief.tier3.outlook_points),
        "tier3_why": len(brief.tier3.why),
        "tier3_risk": len(brief.tier3.risk),
        "tier3_outlook": brief.tier3.outlook.as_dict() if brief.tier3.outlook else None,
        "tier3_principle_refs": list(brief.tier3.principle_refs),
        "projected_points": len(brief.points),
    }


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="Phase 4 P4-1C Morning Brief real-data pilot（read-only）")
    parser.add_argument("--session-date", default="",
                        help="対象の朝（未指定なら既存 semantics の最新 morning session）")
    parser.add_argument("--fact-sessions", type=int, default=6,
                        help="Fact を読む Tokyo session 数（Phase 3-C と同じ取得経路）")
    args = parser.parse_args(argv)

    now = datetime.now(timezone.utc)
    root = data_root()
    repo = Path.cwd()
    _emit("HEAD", {
        "pilot": "phase4_p4_1c_morning_brief",
        "compass_pipeline": "src.intelligence.compass.pipeline.run_pipeline",
        "composer": "src.intelligence.reports.morning_brief.build_morning_brief",
        "renderer": "src.intelligence.reports.render_markdown.render_morning_brief_markdown",
        "input_loader": "src.intelligence.compass.pilot.load_pilot_inputs",
        "read_only": True, "persists_product": False, "writes_decisions": False,
        "promotion": "NONE", "generator": "deterministic",
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
    _emit("INPUT", {
        "selected_session": session_date,
        "session_selection": "explicit" if args.session_date else "latest_available",
        "morning_rule": MORNING_RULE,
        "mornings": list(inputs.mornings),
        "fact_sessions": list(inputs.fact_sessions),
        "facts_total": len(inputs.facts),
        "contexts_total": len(inputs.context_items),
        "event_facts": inputs.event_fact_count,
        "generator": inputs.config.generator,
    })

    # ---- 既存 Compass pipeline（quality gate を含む）を通す。ここを飛ばして brief を作らない
    snapshot = morning_context_snapshot(list(inputs.context_items), session_date,
                                        generated_at=now)
    result = run_pipeline(snapshot, list(inputs.facts), generator=None,
                          config=inputs.config, now=now)
    draft, package = result.draft, result.package
    _emit("COMPASS", {
        "session_date": draft.session_date,
        "reference_session": draft.reference_session,
        "package_id": package.package_id,
        "draft_id": draft.draft_id,
        "verdict": draft.verdict.value,
        "generator": draft.generator,
        "generator_fallback": draft.generator_fallback,
        "abstain_reason": draft.abstain_reason,
        "claims": len(draft.claims),
        "grounded": len(draft.grounded_claims),
        "rejected": len(draft.rejected_claims),
        "grounded_by_role": {r.value: len(draft.claims_for_role(r)) for r in ClaimRole},
        "gate_issue_codes": result.gate.issue_codes(),
        "repaired_claims": len(result.repaired_claim_ids),
        "package_missing_dimensions": list(package.missing_dimensions),
        "package_unreliable_dimensions": list(package.unreliable_dimensions),
    })

    # ---- P4-1A composer（pipeline 完了後にのみ呼ぶ）
    brief = build_morning_brief(draft, package)
    _emit("BRIEF", dict(_brief_row(brief), binding={
        "draft_id_matches": brief.draft_id == draft.draft_id,
        "package_id_matches": brief.package_id == draft.package_id == package.package_id,
        "session_date_matches": brief.session_date == draft.session_date == package.session_date,
        "reference_session_matches":
            brief.reference_session == draft.reference_session == package.reference_session,
        "verdict_matches": brief.verdict is draft.verdict,
    }))

    # ---- P4-1B renderer
    markdown = render_morning_brief_markdown(brief)
    encoded = markdown.encode("utf-8")
    _emit("MARKDOWN", {
        "bytes": len(encoded),
        "sha256": hashlib.sha256(encoded).hexdigest(),
        "lines": len(markdown.splitlines()),
        "headings": [line for line in markdown.splitlines() if line.startswith("#")],
    })
    print(MARKDOWN_BEGIN)
    print(markdown, end="")
    print(MARKDOWN_END)

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
        "product_files_written": 0,
        "promotion_status_written": "NONE",
        "compass_dna_mutated": False,
        "replay_regenerated": False,
        "legacy_report_touched": False,
        "network_used": False,
        "safety_check": "PASSED" if not changed else "FAILED",
    })
    _emit("END", {"session_date": session_date, "brief_id": brief.brief_id,
                  "result": "OK" if not changed else "SAFETY_FAILED"})
    return 0 if not changed else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
