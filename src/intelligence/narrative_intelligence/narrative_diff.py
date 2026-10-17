"""P7-A4a — 決定論の構造の差分（明示的な 2 つの `NarrativeSynthesis` → `NarrativeDiff`。文章・LLM・永続化なし）。

`diff_syntheses(previous=..., current=...)`: 純関数。問いは「明示的に与えた 2 つの synthesis の間で、構造化された
Narrative の中身の何が変わったか」だけ。市場がなぜ変わったか・Theme が良くなったか・確信度が上がったか・投資として
魅力が増したかには答えない。

規則:
- 両方を caller が明示的に渡す（keyword だけ・既定値なし）。前回の実行・昨日・最新の保存物を探さない（store を読まない）。
- 両方を A1 の厳格な復元で再検証する（`presentation_planner.revalidate_synthesis`）。
- 比べられるのは: 同じ型・同じ subject の組（A1 の `narrative_key`）・同じ knowledge pin（reader と A3 の規則表の
  version）・previous の cutoff < current の cutoff。A1 が持つ情報だけを使い、足りない来歴を作らない。
- 区分は claim id の完全一致だけ: 両方 → UNCHANGED、previous だけ → REMOVED、current だけ → ADDED。類似・言い換えの
  照合・embedding・MODIFIED の推測をしない。方向（改善・強化・強気・確信度の変化）に変換しない。
- 並びは区分の提示の順 → section の提示の順 → Theme の root id の組 → claim id（重要度ではない）。

契約: `docs/databank/PHASE7_NARRATIVE_PRESENTATION_DIFF_CONTRACT.md`。
"""
from __future__ import annotations

from typing import Dict

from .presentation_model import (DiffCategory, NarrativeDiff, NarrativeDiffItem, NarrativePresentationError,
                                 PresentationItem, diff_item_order_key)
from .presentation_planner import item_for_claim, revalidate_synthesis
from .synthesis_model import NarrativeSynthesis


def _incompatible(condition: bool, detail: str) -> None:
    if not condition:
        raise NarrativePresentationError("INCOMPATIBLE_DIFF_INPUTS", detail)


def diff_syntheses(*, previous: NarrativeSynthesis, current: NarrativeSynthesis) -> NarrativeDiff:
    """明示的な previous と current の claim id の集合の差（純関数。同じ組 → 同じ canonical bytes と id）。"""
    before = revalidate_synthesis(previous)
    after = revalidate_synthesis(current)
    _incompatible(before.kind is after.kind, "KIND_MISMATCH")
    _incompatible(before.narrative_key == after.narrative_key, "SCOPE_MISMATCH")
    _incompatible(before.knowledge_pins == after.knowledge_pins, "KNOWLEDGE_PINS_MISMATCH")
    _incompatible(before.cutoff < after.cutoff, "CUTOFF_ORDER")
    old: Dict[str, PresentationItem] = {claim.claim_id: item_for_claim(claim) for claim in before.claims}
    new: Dict[str, PresentationItem] = {claim.claim_id: item_for_claim(claim) for claim in after.claims}
    entries = [NarrativeDiffItem(category=DiffCategory.ADDED, item=new[claim_id]) for claim_id in new
               if claim_id not in old]
    entries += [NarrativeDiffItem(category=DiffCategory.REMOVED, item=old[claim_id]) for claim_id in old
                if claim_id not in new]
    for claim_id in new:
        if claim_id in old:
            if old[claim_id] != new[claim_id]:                             # 同じ claim id は同じ内容（A1 の identity）
                raise NarrativePresentationError("PRESENTATION_CONFLICT", "same claim id, different item")
            entries.append(NarrativeDiffItem(category=DiffCategory.UNCHANGED, item=new[claim_id]))
    return NarrativeDiff(kind=after.kind, subject_root_ids=after.subject_root_ids,
                         previous_synthesis_id=before.synthesis_id, current_synthesis_id=after.synthesis_id,
                         items=tuple(sorted(entries, key=diff_item_order_key)))


__all__ = ["diff_syntheses"]
