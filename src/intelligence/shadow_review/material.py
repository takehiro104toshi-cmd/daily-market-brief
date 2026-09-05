"""Material change digest（Phase 3.9.3）— 「前回レビュー時から実質的に変わったか」だけを決める。

含めるのは policy の `material_change_fields` のみ。**Reference Score・relative share・span_days・
3D confirmation・経過時間は構造的に含めない**（score が人間の注意を動かしてはならないという凍結方針を、
再提示の側でも担保する）。config で score を混ぜようとしても policy validate が起動時に拒否する。

digest は canonical JSON の sha256 先頭 16 桁（Phase 3.9.2 / 3.9.3 policy digest と同じ規約）。
"""
from __future__ import annotations

from typing import Any, Dict, Mapping

from ..evaluation.config import A_CONSISTENCY, A_CROSS, A_STRENGTH
from .config import ShadowReviewPolicy
from .models import canonical_json, sha256_hex

DIGEST_LENGTH = 16


def _metrics(row: Mapping[str, Any], axis: str) -> Dict[str, Any]:
    return dict((dict(row.get("axis_metrics") or {}).get(axis) or {}))


def material_payload(evaluation: Mapping[str, Any], lifecycle: str,
                     policy: ShadowReviewPolicy) -> Dict[str, Any]:
    """policy が挙げた field だけを取り出した payload（順序は policy の並び）。"""
    strength = _metrics(evaluation, A_STRENGTH)
    quality = _metrics(evaluation, "data_quality")
    cross = _metrics(evaluation, A_CROSS)
    consistency = _metrics(evaluation, A_CONSISTENCY)
    available: Dict[str, Any] = {
        "recommendation": str(evaluation.get("recommendation", "")),
        "axis_states": dict(evaluation.get("axis_states") or {}),
        "axis_applicability": dict(evaluation.get("axis_applicability") or {}),
        "eligible_support": int(strength.get("eligible_support", quality.get("eligible_support", 0)) or 0),
        "distinct_2d_cells": int(cross.get("distinct_2d_cells", 0) or 0),
        "contradiction": {
            "narrow_sibling": bool(consistency.get("narrow_sibling_contradiction")),
            "narrow_sibling_repeated": bool(consistency.get("narrow_sibling_repeated")),
            "document_contradiction": bool(consistency.get("contradiction")),
            "document_contradiction_repeated": bool(consistency.get("contradiction_repeated")),
            "dna_conflicts": int(consistency.get("dna_conflicts", 0) or 0),
        },
        "lifecycle": str(lifecycle or ""),
        "evaluation_policy_digest": str(evaluation.get("evaluation_policy_digest", "")),
        "recommendation_policy_digest": str(evaluation.get("recommendation_policy_digest", "")),
    }
    return {f: available[f] for f in policy.material_change_fields if f in available}


def material_digest(evaluation: Mapping[str, Any], lifecycle: str, policy: ShadowReviewPolicy) -> str:
    return sha256_hex(canonical_json(material_payload(evaluation, lifecycle, policy)))[:DIGEST_LENGTH]
