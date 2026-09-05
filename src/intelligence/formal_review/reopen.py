"""Reopen eligibility（Phase 3.9.5・凍結）— REJECTED は material change が検出されたときだけ REOPEN_ELIGIBLE。

material change = 現在の material_digest（Phase 3.9.3 の凍結 semantics）が、REJECTED decision の metadata に
記録された material_digest と異なること。corpus 増加のみ・score のみ・経過時間のみでは変わらない（digest の
構造上）。system は REOPEN_ELIGIBLE を表示するだけで、REOPENED_FOR_REVIEW を書くのは人間だけ。
packet binding の無い REJECTED（formal review 外で書かれた行）は検証不能 = 非適格（fail closed）。
"""
from __future__ import annotations

from typing import Any, Dict, Mapping, Optional

from .config import REJECTED

REOPEN_ELIGIBLE = "REOPEN_ELIGIBLE"
REOPEN_NOT_ELIGIBLE = "NOT_ELIGIBLE"
REOPEN_UNVERIFIABLE = "UNVERIFIABLE_NO_PACKET_BINDING"
REOPEN_NOT_REJECTED = "NOT_REJECTED"


def reopen_eligibility(head: Optional[Mapping[str, Any]], current_material_digest: str) -> Dict[str, Any]:
    """head = pattern の最新 DecisionRecord（as_dict）。"""
    if not head or str(head.get("decision_type", "")) != REJECTED:
        return {"eligible": False, "status": REOPEN_NOT_REJECTED, "material_digest_at_rejection": "",
                "current_material_digest": current_material_digest}
    stored = str(dict(head.get("metadata") or {}).get("material_digest", ""))
    if not stored:
        return {"eligible": False, "status": REOPEN_UNVERIFIABLE, "material_digest_at_rejection": "",
                "current_material_digest": current_material_digest}
    changed = stored != current_material_digest
    return {"eligible": changed, "status": REOPEN_ELIGIBLE if changed else REOPEN_NOT_ELIGIBLE,
            "material_digest_at_rejection": stored, "current_material_digest": current_material_digest}
