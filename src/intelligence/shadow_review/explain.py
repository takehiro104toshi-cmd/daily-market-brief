"""Why-this-pattern-is-here（Phase 3.9.3）— 決定的テンプレート。LLM も network も使わない。

テンプレートは recommendation ではなく **triggered_rule** に紐づける（規則が増えても文が曖昧に
ならない）。未知の triggered_rule には汎用文を作らず `ExplanationTemplateMissing` で fail loud にする
（黙って曖昧な説明を出すことが、レビュー品質にとって最悪の失敗であるため）。

本文引用は一切しない。埋め込むのは数値と閉じた語彙だけ。
"""
from __future__ import annotations

from typing import Any, Dict, Mapping

from ..evaluation.config import A_CONSISTENCY, A_CROSS, A_STRENGTH, A_TIME
from ..evaluation.rules import R_APPROVE, R_KEEP, R_REJECT, R_REVIEW

TEMPLATE_MISSING_CODE = "EXPLANATION_TEMPLATE_MISSING"


class ExplanationTemplateMissing(LookupError):
    def __init__(self, triggered_rule: str) -> None:
        super().__init__(f"{TEMPLATE_MISSING_CODE}: no deterministic template for {triggered_rule!r}")
        self.code = TEMPLATE_MISSING_CODE
        self.triggered_rule = triggered_rule


#: Evidence Consistency の reason code → 人間向けの矛盾種別（閉じた語彙）
CONTRADICTION_KIND = {
    "SUPPORTING_DOCUMENT_UP_DOWN_CONTRADICTION": "支持文書のあいだで方向が逆",
    "NARROW_SIBLING_CONTRADICTION": "同一 evidence・target の兄弟 pattern と方向が逆",
    "DNA_CONFLICT": "既存 Compass DNA 規則と矛盾",
}
#: blocking rule → 人間向けの不足理由（閉じた語彙）
BLOCKING_PHRASE = {
    "TYPE_NOT_APPROVAL_ELIGIBLE": "この pattern type は v1 では REVIEW 専用",
    "DATA_QUALITY_NOT_HIGH": "支持文書の品質が全件 VALID ではない",
    "APPLICABLE_CORE_AXIS_BELOW_MEDIUM": "評価可能な core 軸に MEDIUM 未満がある",
    "CONSISTENCY_NOT_HIGH": "方向の一貫性が HIGH に届いていない",
    "TIME_STABILITY_NOT_HIGH": "観測期間が承認水準に届いていない",
    "CROSS_REGIME_NOT_HIGH": "複数の市場レジームでの再現が足りない",
    "STRENGTH_BELOW_MEDIUM": "支持文書が少ない",
    "TIME_BELOW_MEDIUM": "観測期間が短い",
    "CONSISTENCY_LOW": "方向の矛盾が検出されている",
    "CONTRADICTION_NOT_REPEATED": "矛盾が反復していない",
    "STRENGTH_NOT_HIGH_FOR_REJECT": "否定判断に足る証拠量がない",
}


def _facts(evaluation: Mapping[str, Any]) -> Dict[str, Any]:
    metrics = dict(evaluation.get("axis_metrics") or {})
    strength = dict(metrics.get(A_STRENGTH) or {})
    quality = dict(metrics.get("data_quality") or {})
    time_ = dict(metrics.get(A_TIME) or {})
    cross = dict(metrics.get(A_CROSS) or {})
    consistency = dict(metrics.get(A_CONSISTENCY) or {})
    support = strength.get("eligible_support", quality.get("eligible_support", 0))
    return {
        "support": int(support or 0),
        "documents": int(quality.get("resolved_supporting_documents", support or 0) or 0),
        "span": int(time_.get("span_days", 0) or 0),
        "months": int(time_.get("distinct_calendar_months", 0) or 0),
        "cells": int(cross.get("distinct_2d_cells", 0) or 0),
        "dna_conflicts": int(consistency.get("dna_conflicts", 0) or 0),
    }


def _contradiction_kind(evaluation: Mapping[str, Any]) -> str:
    reason = str(dict(evaluation.get("axis_reasons") or {}).get(A_CONSISTENCY, ""))
    if reason in CONTRADICTION_KIND:
        return CONTRADICTION_KIND[reason]
    metrics = dict(dict(evaluation.get("axis_metrics") or {}).get(A_CONSISTENCY) or {})
    if int(metrics.get("dna_conflicts", 0) or 0) > 0:
        return CONTRADICTION_KIND["DNA_CONFLICT"]
    return "方向の矛盾"


def _blocking_phrase(evaluation: Mapping[str, Any]) -> str:
    for rule in evaluation.get("blocking_rules") or []:
        if str(rule) in BLOCKING_PHRASE:
            return BLOCKING_PHRASE[str(rule)]
    return "承認条件の一部が未充足"


def _reject(evaluation: Mapping[str, Any]) -> str:
    f = _facts(evaluation)
    return (f"{f['documents']}件の支持文書にわたり反復する矛盾が検出されました"
            f"（{_contradiction_kind(evaluation)}）。証拠は強く（support {f['support']}件・{f['span']}日）、"
            "単発の食い違いではありません。人間による否定レビューを推奨します。")


def _approve(evaluation: Mapping[str, Any], shadow_mode: bool, corpus_size: int, gate: int) -> str:
    f = _facts(evaluation)
    cells = f"{f['cells']}個の市場レジームで観測、" if f["cells"] else ""
    text = (f"{f['support']}件の適格文書で{f['span']}日・{f['months']}か月にわたり再現し、{cells}"
            "矛盾は検出されていません。データ品質は全件 VALID です。")
    if shadow_mode:
        text += f"※これは助言であり承認ではありません（corpus {corpus_size}/{gate}・SHADOW_ONLY）。"
    return text


def _review(evaluation: Mapping[str, Any]) -> str:
    f = _facts(evaluation)
    return (f"{f['support']}件・{f['span']}日で再現していますが、{_blocking_phrase(evaluation)}のため"
            "承認水準には達していません。人間の目視確認を推奨します。")


def _watch(evaluation: Mapping[str, Any], lifecycle: str) -> str:
    f = _facts(evaluation)
    return (f"まだ escalate 水準ではありませんが、{lifecycle or '観測段階'}へ進み "
            f"support が{f['support']}件に増えています。経過観察対象です。（レビュー任意）")


def explain(evaluation: Mapping[str, Any], lifecycle: str = "", shadow_mode: bool = True,
            corpus_size: int = 0, formal_review_min_corpus: int = 100) -> str:
    """triggered_rule から決定的に 1〜2 文を返す。未知なら fail loud。"""
    rule = str(evaluation.get("triggered_rule", ""))
    if rule == R_REJECT:
        return _reject(evaluation)
    if rule == R_APPROVE:
        return _approve(evaluation, shadow_mode, corpus_size, formal_review_min_corpus)
    if rule == R_REVIEW:
        return _review(evaluation)
    if rule == R_KEEP:
        return _watch(evaluation, lifecycle)
    raise ExplanationTemplateMissing(rule)
