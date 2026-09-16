"""内部 abstain 詳細 → 公開 unavailable 理由の**語彙境界ガード**（Phase 4 P4-3b2c）。

production producer run 35081366821 は、Compass 内部の abstain 詳細
`no_counter_material` が MarketSignal を素通りして配信面へ届き、公開 JSON 生成が
`UnmappedDeliveryState: unavailable reason is not publishable` で落ちて失敗した。
市場データ取得も永続化も成功しており、欠陥は **語彙の境界** だけにあった。

本 module はその境界だけを拘束する:

A. **実在する内部理由の網羅** —— 昇格済み Compass 経路から
   `MorningBrief.abstain_reason` へ到達しうる abstain 理由を **AST で実測**し、
   その 1 つ 1 つを**本物の** `build_market_signal()` に通して、結果が
   `PUBLIC_UNAVAILABLE_REASONS` の承認済み値であることを要求する。
   `no_counter_material` を 1 件だけ試すのではない。
B. **公開語彙の閉鎖性** —— 内部 abstain 詳細が公開語彙の新メンバーに
   なっていないこと。公開語彙は凍結された 6 値のままであること。

規律: 決定論的・完全 offline・ネットワーク無し・data root 無し。発見した内部理由の
**文字列だけ**を使い、Compass pipeline を実行しない（AST は構文位置のみを読む）。
`delivery.py` の fail closed（`UnmappedDeliveryState`）は**弱めない**——本 module は
その壁が残っていることを最後の test で明示的に確認する。

構造ガード `test_p43b2c_production_bundle.py` は bundle の**構造**（搬入漏れ・
closure・trust anchor）を見る module であり、意味論的な語彙契約は本 module が持つ。
"""
from __future__ import annotations

import ast
import dataclasses
from pathlib import Path

import pytest

from src.intelligence.compass.model import QualityVerdict
from src.intelligence.reports.delivery import (
    PUBLIC_UNAVAILABLE_REASONS,
    UnmappedDeliveryState,
    build_morning_delivery,
    delivery_public_json,
    delivery_public_payload,
)
from src.intelligence.reports.market_signal import (
    APPROVED_UNAVAILABLE_REASONS,
    R_DIRECTION_MIXED,
    R_DIRECTION_UNCERTAIN,
    R_DRAFT_ABSTAINED,
    R_DRAFT_NOT_USABLE,
    R_NO_OUTLOOK,
    R_TIER3_UNAVAILABLE,
    build_market_signal,
)
from src.intelligence.reports.model import (
    BriefOutlook,
    BriefTier1,
    BriefTier2,
    BriefTier3,
    MorningBrief,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
COMPASS_DIR = REPO_ROOT / "src" / "intelligence" / "compass"

#: 凍結された公開語彙。**この 6 値から増減してはならない**（内部詳細を足さない）。
FROZEN_PUBLIC_UNAVAILABLE_REASONS = (
    "draft_not_usable", "draft_abstained", "tier3_unavailable",
    "no_outlook", "direction_mixed", "direction_uncertain",
)

#: run 35081366821 を落とした当の内部理由。網羅検査が壊れたときの sentinel。
RUN_35081366821_REASON = "no_counter_material"

#: abstain 理由が置かれる構文上のスロット名
_ABSTAIN_SLOTS = frozenset({"abstain", "abstain_reason"})


def _module_constants(tree: ast.Module) -> dict:
    """module 直下の `NAME = "literal"` だけを拾う（動的推論はしない）。"""
    found = {}
    for node in tree.body:
        if (isinstance(node, ast.Assign) and len(node.targets) == 1
                and isinstance(node.targets[0], ast.Name)
                and isinstance(node.value, ast.Constant)
                and isinstance(node.value.value, str)):
            found[node.targets[0].id] = node.value.value
    return found


def _resolve(expr: ast.AST, constants: dict, into: set) -> None:
    """abstain スロットへ入る式から、**新しい理由値**だけを取り出す。

    module 定数 / 文字列定数のみを値とみなす。`x.abstain_reason` のような
    転送や局所変数は「既存値の受け渡し」であり、新しい語彙を作らない。
    """
    if isinstance(expr, ast.Constant):
        if isinstance(expr.value, str) and expr.value:
            into.add(expr.value)
    elif isinstance(expr, ast.Name):
        value = constants.get(expr.id)
        if value:
            into.add(value)
    elif isinstance(expr, ast.IfExp):
        _resolve(expr.body, constants, into)
        _resolve(expr.orelse, constants, into)
    elif isinstance(expr, ast.BoolOp):
        for value in expr.values:
            _resolve(value, constants, into)


def reachable_internal_abstain_reasons() -> set:
    """昇格済み Compass 経路が `abstain_reason` へ入れうる内部理由の実測集合。

    `src/intelligence/compass/` 全体を走査する。本番 closure の**上位集合**なので
    取りこぼしが起きない側に倒れている（余分に混ざっても写像を要求するだけ）。
    """
    reasons: set = set()
    for path in sorted(COMPASS_DIR.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        constants = _module_constants(tree)
        for node in ast.walk(tree):
            if isinstance(node, ast.Assign):
                names = set()
                for target in node.targets:
                    if isinstance(target, ast.Name):
                        names.add(target.id)
                    elif isinstance(target, ast.Tuple):
                        names |= {e.id for e in target.elts if isinstance(e, ast.Name)}
                if not names & _ABSTAIN_SLOTS:
                    continue
                if (isinstance(node.targets[0], ast.Tuple)
                        and isinstance(node.value, ast.Tuple)
                        and len(node.targets[0].elts) == len(node.value.elts)):
                    for target, value in zip(node.targets[0].elts, node.value.elts):
                        if isinstance(target, ast.Name) and target.id in _ABSTAIN_SLOTS:
                            _resolve(value, constants, reasons)
                else:
                    _resolve(node.value, constants, reasons)
            elif isinstance(node, ast.Call):
                for keyword in node.keywords:
                    if keyword.arg == "abstain_reason":
                        _resolve(keyword.value, constants, reasons)
    return reasons


def _abstained_brief(abstain_reason: str) -> MorningBrief:
    """run #3 と同じ形の ABSTAINED brief（offline・決定論的・data root 無し）。"""
    return MorningBrief(
        brief_id="brief_p43b2c_vocabulary_boundary",
        session_date="2026-09-16", reference_session="2026-09-15",
        draft_id="draft_p43b2c_vocabulary_boundary",
        package_id="evpkg_p43b2c_vocabulary_boundary",
        verdict=QualityVerdict.ABSTAINED, generator="deterministic",
        abstain_reason=abstain_reason,
        tier1=BriefTier1(available=False, unavailable_reason=abstain_reason),
        tier2=BriefTier2(available=False, unavailable_reason=abstain_reason),
        tier3=BriefTier3(available=False, unavailable_reason=abstain_reason))


def _usable_brief(*, tier3: BriefTier3) -> MorningBrief:
    """abstain していない brief。tier3 の分岐だけを動かすために使う。"""
    return MorningBrief(
        brief_id="brief_p43b2c_usable", session_date="2026-09-16",
        reference_session="2026-09-15", draft_id="draft_p43b2c_usable",
        package_id="evpkg_p43b2c_usable", verdict=QualityVerdict.VALID,
        generator="deterministic",
        tier1=BriefTier1(available=True, text="x", display_text="x"),
        tier2=BriefTier2(available=True), tier3=tier3)


def _public_reason_for(abstain_reason: str) -> str:
    """**本物の**境界（build_market_signal）を通した公開理由。"""
    return build_market_signal(_abstained_brief(abstain_reason)).unavailable_reason


# --------------------------------------------------------------------------
# B. 公開語彙の閉鎖性
# --------------------------------------------------------------------------

def test_public_unavailable_vocabulary_is_unchanged() -> None:
    """公開語彙は凍結された 6 値のまま（内部詳細で拡張していない）。"""
    assert PUBLIC_UNAVAILABLE_REASONS == FROZEN_PUBLIC_UNAVAILABLE_REASONS


def test_signal_vocabulary_mirrors_the_delivery_public_contract() -> None:
    """MarketSignal 側の承認語彙が配信側の公開契約と同一集合であること。

    依存は一方向（delivery → market_signal）なので market_signal からは
    delivery を import できない。同値性はここで拘束する。
    """
    assert set(APPROVED_UNAVAILABLE_REASONS) == set(PUBLIC_UNAVAILABLE_REASONS)
    assert len(APPROVED_UNAVAILABLE_REASONS) == len(PUBLIC_UNAVAILABLE_REASONS)


def test_no_internal_abstain_reason_is_a_member_of_the_public_vocabulary() -> None:
    """内部 abstain 詳細が公開語彙のメンバーになっていない。"""
    leaked = sorted(r for r in reachable_internal_abstain_reasons()
                    if r in PUBLIC_UNAVAILABLE_REASONS)
    assert leaked == [], leaked


# --------------------------------------------------------------------------
# A. 実在する内部理由の網羅
# --------------------------------------------------------------------------

def test_internal_abstain_reason_enumeration_is_not_empty() -> None:
    """列挙器自体が壊れていないこと（空なら網羅検査が無意味になる）。"""
    reasons = reachable_internal_abstain_reasons()
    assert reasons, "内部 abstain 理由が 1 つも検出されない（列挙規則が壊れている）"
    assert RUN_35081366821_REASON in reasons, sorted(reasons)


def test_run_35081366821_regression_no_counter_material_maps_to_draft_abstained() -> None:
    """run #3 を落とした当の値が承認済み公開理由へ写像される。"""
    assert _public_reason_for(RUN_35081366821_REASON) == R_DRAFT_ABSTAINED


def test_every_reachable_internal_abstain_reason_maps_to_an_approved_public_reason() -> None:
    """実測した内部理由の**すべて**が承認済み公開理由になる（fail closed）。"""
    unmapped = sorted(reason for reason in reachable_internal_abstain_reasons()
                      if _public_reason_for(reason) not in PUBLIC_UNAVAILABLE_REASONS)
    assert unmapped == [], unmapped


def test_every_reachable_internal_abstain_reason_maps_to_draft_abstained() -> None:
    """ABSTAINED 系の公開理由は `draft_abstained` に統一される。"""
    wrong = sorted(reason for reason in reachable_internal_abstain_reasons()
                   if _public_reason_for(reason) != R_DRAFT_ABSTAINED)
    assert wrong == [], wrong


# --------------------------------------------------------------------------
# 負の対照
# --------------------------------------------------------------------------

def test_unknown_but_well_formed_reason_is_not_passed_through() -> None:
    """形は正しいが承認語彙でない値は素通りしない（今回の欠陥そのもの）。"""
    assert _public_reason_for("some_future_internal_reason") == R_DRAFT_ABSTAINED


def test_malformed_reason_falls_back_to_the_approved_reason() -> None:
    for malformed in ("Not Snake Case", "日本語の自由文", "x" * 65, "UPPER_CASE"):
        assert _public_reason_for(malformed) == R_DRAFT_ABSTAINED, malformed


def test_empty_reason_falls_back_to_the_approved_reason() -> None:
    assert _public_reason_for("") == R_DRAFT_ABSTAINED


def test_rejected_verdict_keeps_draft_not_usable() -> None:
    """ABSTAINED でない非 usable verdict は `draft_abstained` へ潰さない。"""
    brief = dataclasses.replace(_abstained_brief(RUN_35081366821_REASON),
                                verdict=QualityVerdict.REJECTED)
    assert build_market_signal(brief).unavailable_reason == R_DRAFT_NOT_USABLE


def test_tier3_unavailable_branch_keeps_its_own_public_reason() -> None:
    """tier3 が無い朝は `tier3_unavailable`（内部詳細も他分岐へも流さない）。"""
    for internal in ("no_grounded_outlook", "no_grounded_counter_case",
                     "one_liner_unavailable", ""):
        brief = _usable_brief(tier3=BriefTier3(available=False,
                                               unavailable_reason=internal))
        assert build_market_signal(brief).unavailable_reason == R_TIER3_UNAVAILABLE, internal


def test_no_outlook_branch_keeps_its_own_public_reason() -> None:
    brief = _usable_brief(tier3=BriefTier3(available=True, outlook=None))
    assert build_market_signal(brief).unavailable_reason == R_NO_OUTLOOK


def test_direction_branches_keep_their_own_public_reasons() -> None:
    for direction, expected in (("MIXED", R_DIRECTION_MIXED),
                                ("UNCERTAIN", R_DIRECTION_UNCERTAIN)):
        brief = _usable_brief(tier3=BriefTier3(
            available=True, outlook=BriefOutlook(direction=direction, confidence="LOW",
                                                 horizon="next_tokyo_session")))
        assert build_market_signal(brief).unavailable_reason == expected, direction


# --------------------------------------------------------------------------
# 配信面（公開 JSON）まで通す
# --------------------------------------------------------------------------

def _run3_delivery():
    brief = _abstained_brief(RUN_35081366821_REASON)
    signal = build_market_signal(brief)
    return build_morning_delivery(brief, signal, "# 本日は方向を出しません\n")


def test_public_payload_and_json_succeed_for_the_run3_abstained_delivery() -> None:
    """run #3 と同じ状態で公開 JSON 生成が通る（例外を出さない）。"""
    delivery = _run3_delivery()
    payload = delivery_public_payload(delivery)
    assert payload["signal"]["available"] is False
    assert payload["signal"]["label"] == ""
    assert payload["signal"]["unavailable_reason"] == R_DRAFT_ABSTAINED
    assert delivery_public_json(delivery)


def test_public_json_carries_draft_abstained_and_not_the_internal_detail() -> None:
    """公開 JSON に承認語彙だけが載り、内部詳細が 1 つも漏れない。"""
    blob = delivery_public_json(_run3_delivery())
    assert R_DRAFT_ABSTAINED in blob
    assert RUN_35081366821_REASON not in blob
    for reason in reachable_internal_abstain_reasons():
        assert reason not in blob, reason


def test_delivery_still_fails_closed_for_an_unapproved_reason_after_the_boundary() -> None:
    """**下流の壁は弱めていない**——境界の後で未承認値を注入すれば今も落ちる。"""
    delivery = _run3_delivery()
    tampered = dataclasses.replace(
        delivery, signal=dataclasses.replace(delivery.signal,
                                             unavailable_reason=RUN_35081366821_REASON))
    with pytest.raises(UnmappedDeliveryState):
        delivery_public_payload(tampered)
    with pytest.raises(UnmappedDeliveryState):
        delivery_public_json(tampered)
