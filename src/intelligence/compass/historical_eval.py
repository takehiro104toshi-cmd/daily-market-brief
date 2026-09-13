"""過去Compassとの評価（Phase 3-C §35 Historical Compass Evaluation）。

生成した CompassDraft を、既存の履歴レポート
（`output/history/<date>/pre_market.html`＝人間／レガシー経路が作った朝のCompass）と
突き合わせ、**観測**として報告する。

比較するもの（客観的に比較できるものだけ）:
- 水準: 履歴レポート冒頭の「ドル円 159.52」「日経平均 66,294.09」と、Evidence Package
  内の `fx_level` / `index_close` Fact → MATCH / DIVERGENT / NOT_AVAILABLE
  （相対差が `historical_level_tolerance_pct` 以内ならMATCH）
- 方向: Phase 3-B の `align_snapshot` をそのまま再利用（MATCH / PARTIAL / CONFLICT）
- 生成側の健全性: draftの引用IDが全てEvidence Package内か、REJECTED claim数、
  look-ahead除外数

重要な原則（監督者指示・3-Bと同じ）:
- **人間が書いたCompassを再現するようにruleを最適化しない**。観測であって目標ではない。
- 履歴レポートの数値はレガシー収集経路（yfinance等）由来で、Market Data Bank
  （公式ソース）と取得経路も時刻も異なる。DIVERGENTは「誤り」ではなく差異の記録。
- 比較できないもの（履歴に無い／Factが無い）は NOT_AVAILABLE と正直に報告する。

履歴HTMLは**読み取り専用**（既存レポート生成・GitHub Pagesには一切触れない）。
"""
from __future__ import annotations

import html
import re
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Dict, Mapping, Optional, Sequence, Tuple

from ..context.builders import NIKKEI, USDJPY
from ..context.compass_alignment import SLOT_FILE, align_snapshot, history_dir
from ..context.snapshot import CompassContextSnapshot
from ..facts.model import Fact
from .evidence_package import EvidencePackage
from .model import CompassDraft, GroundingStatus
from .one_liner import sentence_count

MATCH = "MATCH"
DIVERGENT = "DIVERGENT"
NOT_AVAILABLE = "NOT_AVAILABLE"

#: 履歴レポート冒頭の水準タイル `<b>日経平均</b> 66,294.09 <span class="badge up">+0.25%</span>`
_LEVEL_PATTERN = re.compile(
    r"<b>(日経平均|ドル円)</b>\s*([\d,]+(?:\.\d+)?)"
    r"(?:\s*<span class=\"badge[^\"]*\">\s*([+-]?\d+(?:\.\d+)?)%\s*</span>)?")

#: 比較次元 → (履歴ラベル, subject_id, 水準Fact type)
LEVEL_DIMENSIONS: Mapping[str, Tuple[str, str, str]] = {
    "nikkei_level": ("日経平均", NIKKEI, "index_close"),
    "usd_jpy_level": ("ドル円", USDJPY, "fx_level"),
}


def parse_pre_market_levels(path: Path) -> Dict[str, Dict[str, Optional[Decimal]]]:
    """履歴レポートから水準（と併記の前日比%）を抽出する。最初の出現のみ採用。"""
    if not path.is_file():
        return {}
    text = path.read_text(encoding="utf-8")
    found: Dict[str, Dict[str, Optional[Decimal]]] = {}
    for label, level, pct in _LEVEL_PATTERN.findall(text):
        if label in found:
            continue
        try:
            found[label] = {
                "level": Decimal(html.unescape(level).replace(",", "")),
                "change_pct": Decimal(pct) if pct else None,
            }
        except InvalidOperation:
            continue
    return found


def _relative_diff_pct(reported: Decimal, produced: Decimal) -> Optional[Decimal]:
    if produced == 0:
        return None
    return (abs(reported - produced) / abs(produced) * Decimal(100)).quantize(
        Decimal("0.001"))


def _closest_level_fact(facts: Sequence[Fact], reported: Decimal) -> Optional[Fact]:
    """Package内の水準Factのうち、履歴水準に最も近いもの（session差の記録用）。"""
    best: Optional[Fact] = None
    best_diff: Optional[Decimal] = None
    for f in facts:
        if f.value.value is None:
            continue
        diff = abs(Decimal(str(f.value.value)) - reported)
        if best_diff is None or diff < best_diff:
            best, best_diff = f, diff
    return best


def compare_levels(package: EvidencePackage,
                   levels: Mapping[str, Mapping[str, Optional[Decimal]]], *,
                   tolerance_pct: Decimal) -> Dict[str, Dict[str, str]]:
    """履歴水準 vs Evidence Package の水準Fact（**前営業日終値**）。"""
    rows: Dict[str, Dict[str, str]] = {}
    for dimension, (label, subject_id, fact_type) in LEVEL_DIMENSIONS.items():
        reported = levels.get(label, {}).get("level")
        candidates = [f for f in package.level_facts_for(subject_id)
                      if f.fact_type == fact_type and f.value.value is not None]
        reference = [f for f in candidates
                     if f.time.primary_date == package.reference_session]
        if reported is None or not reference:
            rows[dimension] = {
                "verdict": NOT_AVAILABLE, "label": label,
                "reason": ("report_level_not_found" if reported is None
                           else "reference_level_fact_missing"),
                "reported_level": str(reported) if reported is not None else "",
                "package_level": (str(reference[0].value.value) if reference else ""),
                "fact_id": reference[0].fact_id if reference else "",
                "fact_session": package.reference_session if reference else "",
                "relative_diff_pct": "", "closest_fact_session": ""}
            continue
        produced = Decimal(str(reference[0].value.value))
        diff = _relative_diff_pct(reported, produced)
        verdict = MATCH if diff is not None and diff <= tolerance_pct else DIVERGENT
        closest = _closest_level_fact(candidates, reported)
        rows[dimension] = {
            "verdict": verdict, "label": label, "reason": "",
            "reported_level": str(reported), "package_level": str(produced),
            "fact_id": reference[0].fact_id, "fact_session": package.reference_session,
            "relative_diff_pct": str(diff) if diff is not None else "",
            # 履歴レポートが同日終値で更新されている場合の説明用（最適化には使わない）
            "closest_fact_session": closest.time.primary_date if closest else ""}
    return rows


@dataclass(frozen=True)
class HistoricalEvaluation:
    session_date: str
    report_path: str
    levels: Mapping[str, Dict[str, str]]
    alignment: Mapping[str, object]
    draft: Mapping[str, object]

    def level_counts(self) -> Dict[str, int]:
        out = {MATCH: 0, DIVERGENT: 0, NOT_AVAILABLE: 0}
        for row in self.levels.values():
            out[row["verdict"]] = out.get(row["verdict"], 0) + 1
        return out

    def as_dict(self) -> Dict[str, object]:
        return {"session_date": self.session_date, "report": self.report_path,
                "levels": {k: dict(v) for k, v in self.levels.items()},
                "level_counts": self.level_counts(),
                "alignment": dict(self.alignment), "draft": dict(self.draft)}


def evaluate_draft(snapshot: CompassContextSnapshot, package: EvidencePackage,
                   draft: CompassDraft, *, base_dir: Optional[Path] = None,
                   tolerance_pct: Decimal = Decimal("1.0")) -> HistoricalEvaluation:
    """1 session分の評価。履歴が無ければ全て NOT_AVAILABLE（捏造しない）。"""
    root = Path(base_dir) if base_dir is not None else history_dir()
    path = root / snapshot.session_date / SLOT_FILE
    levels = compare_levels(package, parse_pre_market_levels(path),
                            tolerance_pct=tolerance_pct)
    alignment = align_snapshot(snapshot, base_dir=root)

    package_facts, package_contexts = set(package.fact_ids), set(package.context_ids)
    cited_facts = {i for c in draft.claims for i in c.supporting_fact_ids}
    cited_contexts = {i for c in draft.claims for i in c.supporting_context_ids}
    draft_row: Dict[str, object] = {
        "draft_id": draft.draft_id, "verdict": draft.verdict.value,
        "generator": draft.generator, "generator_fallback": draft.generator_fallback,
        "claims": len(draft.claims),
        "grounded": len(draft.grounded_claims),
        "rejected": len(draft.rejected_claims),
        "warnings": sum(1 for c in draft.claims
                        if c.grounding_status is GroundingStatus.GROUNDED_WITH_WARNINGS),
        "cited_fact_ids": len(cited_facts),
        "cited_fact_ids_outside_package": len(cited_facts - package_facts),
        "cited_context_ids": len(cited_contexts),
        "cited_context_ids_outside_package": len(cited_contexts - package_contexts),
        "all_citations_within_package": (cited_facts <= package_facts
                                         and cited_contexts <= package_contexts),
        "look_ahead_excluded": len(package.excluded_look_ahead),
        "one_liner_sentences": sentence_count(draft.one_liner),
        "outlook_direction": draft.outlook.direction.value if draft.outlook else "",
        "outlook_confidence": draft.outlook.confidence.value if draft.outlook else "",
        "abstain_reason": draft.abstain_reason,
    }
    return HistoricalEvaluation(session_date=snapshot.session_date, report_path=str(path),
                                levels=levels, alignment=alignment.as_dict(),
                                draft=draft_row)


def summarize_evaluations(results: Sequence[HistoricalEvaluation]) -> Dict[str, object]:
    """複数日をまとめる。比較可能な次元だけを分母にする。"""
    totals = {MATCH: 0, DIVERGENT: 0, NOT_AVAILABLE: 0}
    for result in results:
        for verdict, count in result.level_counts().items():
            totals[verdict] = totals.get(verdict, 0) + count
    comparable = totals[MATCH] + totals[DIVERGENT]
    by_verdict: Dict[str, int] = {}
    for result in results:
        v = str(result.draft["verdict"])
        by_verdict[v] = by_verdict.get(v, 0) + 1
    alignment_results = [align for align in (r.alignment for r in results)]
    return {
        "dates": [r.session_date for r in results],
        "level_totals": totals, "comparable_levels": comparable,
        "level_match_rate": f"{totals[MATCH]}/{comparable}" if comparable else "0/0",
        "direction_alignment": _direction_totals(alignment_results),
        "drafts_by_verdict": by_verdict,
        "all_citations_within_package": all(
            bool(r.draft["all_citations_within_package"]) for r in results),
        "rejected_claims_total": sum(int(r.draft["rejected"]) for r in results),
        "look_ahead_excluded_total": sum(int(r.draft["look_ahead_excluded"])
                                         for r in results),
        "note": "履歴Compassは観測対象であり最適化目標ではない。水準はレガシー経路"
                "（yfinance等）由来で取得経路・時刻が異なるため、DIVERGENTは差異の記録。",
    }


def _direction_totals(alignments: Sequence[Mapping[str, object]]) -> Dict[str, object]:
    totals: Dict[str, int] = {}
    for align in alignments:
        for verdict, count in dict(align.get("counts") or {}).items():
            totals[verdict] = totals.get(verdict, 0) + int(count)
    comparable = sum(v for k, v in totals.items() if k != "NOT_AVAILABLE")
    return {"totals": totals,
            "match_rate": (f"{totals.get('MATCH', 0)}/{comparable}" if comparable
                           else "0/0")}


__all__ = [
    "DIVERGENT", "HistoricalEvaluation", "LEVEL_DIMENSIONS", "MATCH", "NOT_AVAILABLE",
    "compare_levels", "evaluate_draft", "parse_pre_market_levels",
    "summarize_evaluations",
]
