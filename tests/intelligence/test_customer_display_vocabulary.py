"""顧客向け Morning Brief Markdown の**表示語彙境界**ガード（Phase 4 Presentation A1）。

live /v2 の Morning Brief Markdown に Compass 内部の abstain 詳細
`no_counter_material` がそのまま出ていた（実機 iPhone レビューで確認）。
`render_markdown._unavailable()` が理由の**形**（snake_case）だけを見て表示を
許可していたためで、v4.81 で data 境界に対して塞いだのと同じ
「format を vocabulary と取り違える」欠陥が、1 層上の表示面に残っていた。

本 module はその表示境界だけを拘束する:

A. **実在する内部理由の網羅** —— 昇格済み production 経路から
   `BriefTier*.unavailable_reason` へ到達しうる理由を **AST で実測**し、
   その 1 つ 1 つに明示的な顧客向け日本語が割り当てられていることを要求する。
   `no_counter_material` を 1 件だけ試すのではない。
B. **内部語彙の非露出** —— どの内部 token も顧客向け Markdown に現れない。
   未知の理由は生値を出さず、承認済みの汎用文へ落ちる（fail-closed 表示）。
C. **意味論の不変** —— tier の availability も内部 `unavailable_reason` も
   `MorningBrief.abstain_reason` も変えない。公開 JSON 語彙・artifact 契約・
   /v2 topology・selector / freshness 定数・legacy も変えない。

規律: 決定論的・完全 offline・ネットワーク無し・data root 無し。AST は構文位置
だけを読み、発見した module を実行しない。
"""
from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest

from src.intelligence.compass.model import QualityVerdict
from src.intelligence.reports import render_markdown as rm
from src.intelligence.reports.delivery import (
    PUBLIC_KEYS,
    PUBLIC_SIGNAL_KEYS,
    PUBLIC_UNAVAILABLE_REASONS,
    build_morning_delivery,
    delivery_public_json,
    delivery_public_payload,
)
from src.intelligence.reports.delivery_emit import artifact_names
from src.intelligence.reports.market_signal import SIGNAL_LEVEL_JA, SignalLevel, build_market_signal
from src.intelligence.reports.model import (
    BriefOutlook,
    BriefTier1,
    BriefTier2,
    BriefTier3,
    MorningBrief,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
MORNING_BRIEF = REPO_ROOT / "src" / "intelligence" / "reports" / "morning_brief.py"
COMPASS_DIR = REPO_ROOT / "src" / "intelligence" / "compass"

#: live /v2 に漏れていた当の内部理由。網羅検査が壊れたときの sentinel。
LIVE_LEAKED_REASON = "no_counter_material"

#: A0 で実測された production 到達 13 値（列挙器の独立した突き合わせ用）
MEASURED_REASONS = (
    "draft_not_usable", "empty_evidence_package", "lead_context_not_fresh", "no_claims",
    "no_counter_material", "no_grounded_counter_case", "no_grounded_headline",
    "no_grounded_outlook", "no_grounded_points", "no_grounded_risk", "no_grounded_why",
    "no_lead_context", "one_liner_unavailable",
)

_SNAKE_TOKEN = re.compile(r"[a-z][a-z0-9]*(?:_[a-z0-9]+)+")
_ABSTAIN_SLOTS = frozenset({"abstain", "abstain_reason"})


# ---------------------------------------------------------------- 実測（AST・実行なし）

def _module_constants(tree: ast.Module) -> dict:
    found = {}
    for node in tree.body:
        if (isinstance(node, ast.Assign) and len(node.targets) == 1
                and isinstance(node.targets[0], ast.Name)
                and isinstance(node.value, ast.Constant)
                and isinstance(node.value.value, str) and node.value.value):
            found[node.targets[0].id] = node.value.value
    return found


def _global_constants() -> dict:
    """昇格済み production 面の module 直下 `NAME = "literal"` を一括で集める。"""
    found: dict = {}
    for path in sorted((REPO_ROOT / "src" / "intelligence" / "reports").rglob("*.py")) + \
            sorted(COMPASS_DIR.rglob("*.py")):
        for name, value in _module_constants(ast.parse(path.read_text(encoding="utf-8"))).items():
            found.setdefault(name, value)
    return found


def _resolve(expr: ast.AST, constants: dict, into: set) -> None:
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


def reachable_display_reasons() -> set:
    """顧客向け Markdown の「提示できない理由」に到達しうる内部理由の実測集合。

    2 系統を合わせる:
      1. `morning_brief.py` の `BriefTier*(unavailable_reason=...)` へ直接入る定数
      2. `draft.abstain_reason` 経由で入る Compass の abstain 理由
    """
    constants = _global_constants()
    reasons: set = set()

    tree = ast.parse(MORNING_BRIEF.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
                and node.func.id.startswith("BriefTier")):
            for keyword in node.keywords:
                if keyword.arg == "unavailable_reason":
                    _resolve(keyword.value, constants, reasons)

    for path in sorted(COMPASS_DIR.rglob("*.py")):
        compass_tree = ast.parse(path.read_text(encoding="utf-8"))
        local = _module_constants(compass_tree)
        for node in ast.walk(compass_tree):
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
                            _resolve(value, local, reasons)
                else:
                    _resolve(node.value, local, reasons)
    return reasons


# ---------------------------------------------------------------- fixtures（純データ）

def _brief(*, verdict=QualityVerdict.ABSTAINED, t1="", t2="", t3="",
           tier3_available=False, outlook=None) -> MorningBrief:
    return MorningBrief(
        brief_id="brief_a1_display", session_date="2026-09-16",
        reference_session="2026-09-15", draft_id="draft_a1_display",
        package_id="evpkg_a1_display", verdict=verdict, generator="deterministic",
        abstain_reason=t1,
        tier1=BriefTier1(available=False, unavailable_reason=t1),
        tier2=BriefTier2(available=False, unavailable_reason=t2),
        tier3=BriefTier3(available=tier3_available, outlook=outlook,
                         unavailable_reason=t3))


def _render(reason: str) -> str:
    return rm.render_morning_brief_markdown(_brief(t1=reason, t2=reason, t3=reason))


# ---------------------------------------------------------------- A. 網羅

def test_reason_enumeration_is_not_empty_and_matches_the_measured_set() -> None:
    reasons = reachable_display_reasons()
    assert reasons, "内部理由が 1 つも検出されない（列挙規則が壊れている）"
    assert LIVE_LEAKED_REASON in reasons, sorted(reasons)
    assert sorted(reasons) == sorted(MEASURED_REASONS), sorted(reasons)


def test_every_reachable_internal_reason_has_an_explicit_customer_mapping() -> None:
    """新しい production 到達理由が写像されずに増えたら build を落とす。"""
    unmapped = sorted(r for r in reachable_display_reasons() if r not in rm.REASON_JA)
    assert unmapped == [], unmapped


def test_mapping_values_are_only_the_approved_sentences() -> None:
    approved = {rm.S1_MATERIAL_NOT_ASSEMBLED, rm.S2_COUNTER_MATERIAL,
                rm.S3_GROUNDING_INSUFFICIENT}
    unexpected = sorted({v for v in rm.REASON_JA.values()} - approved)
    assert unexpected == [], unexpected


def test_mapping_has_no_entry_outside_the_measured_reachable_set() -> None:
    stale = sorted(set(rm.REASON_JA) - set(MEASURED_REASONS))
    assert stale == [], stale


# ---------------------------------------------------------------- B. 非露出

def test_live_regression_no_counter_material_renders_customer_japanese() -> None:
    """live /v2 に出ていた当の状態。"""
    rendered = _render(LIVE_LEAKED_REASON)
    assert rm.S2_COUNTER_MATERIAL in rendered
    assert LIVE_LEAKED_REASON not in rendered


def test_no_reachable_internal_reason_reaches_customer_markdown() -> None:
    for reason in sorted(reachable_display_reasons()):
        rendered = _render(reason)
        assert reason not in rendered, reason


def test_no_snake_case_machine_token_appears_in_customer_markdown() -> None:
    """今日の 13 値に限らず、機械語彙らしき token が本文へ出ないこと。"""
    for reason in sorted(reachable_display_reasons()) + ["some_future_internal_reason"]:
        leaked = _SNAKE_TOKEN.findall(_render(reason))
        assert leaked == [], (reason, leaked)


def test_unknown_reason_renders_only_the_generic_safe_message() -> None:
    rendered = _render("some_future_internal_reason")
    assert rm.S4_GENERIC in rendered
    assert "some_future_internal_reason" not in rendered


def test_malformed_or_free_text_reason_is_never_reflected() -> None:
    for malformed in ("Not Snake Case", "内部の自由文エラーメッセージ", "x" * 65,
                      "UPPER_CASE", "path/to/thing", "<traceback>"):
        rendered = _render(malformed)
        assert malformed not in rendered, malformed
        assert rm.S4_GENERIC in rendered, malformed


def test_empty_reason_keeps_the_existing_no_reason_form() -> None:
    rendered = _render("")
    assert rm.UNAVAILABLE in rendered
    assert "理由" not in rendered


# ---------------------------------------------------------------- 意味論の不変

def test_abstained_stays_abstained_and_internal_values_are_untouched() -> None:
    brief = _brief(t1=LIVE_LEAKED_REASON, t2=LIVE_LEAKED_REASON, t3=LIVE_LEAKED_REASON)
    before = brief.as_dict()
    rm.render_morning_brief_markdown(brief)
    assert brief.verdict is QualityVerdict.ABSTAINED
    assert brief.abstain_reason == LIVE_LEAKED_REASON
    assert brief.tier1.available is False and brief.tier2.available is False
    assert brief.tier3.available is False
    for tier in (brief.tier1, brief.tier2, brief.tier3):
        assert tier.unavailable_reason == LIVE_LEAKED_REASON
    assert brief.as_dict() == before          # 入力を書き換えない


def test_no_market_conclusion_is_invented_for_unavailable_tiers() -> None:
    """出せない朝に方向・確度・段階を代わりに述べない。

    見出し語は `**方向**:` のような強調付きの構造行としてだけ現れるため、そちらを
    検査する（承認済み文面に含まれる「一方向に偏った」のような自然文の部分一致を
    誤検知しないため）。
    """
    rendered = _render(LIVE_LEAKED_REASON)
    for phrase in tuple(rm.DIRECTION_JA.values()) + tuple(SIGNAL_LEVEL_JA.values()):
        assert phrase not in rendered, phrase
    for label in (rm.L_DIRECTION, rm.L_CONFIDENCE, rm.L_HORIZON):
        assert f"**{label}**" not in rendered, label


# ---------------------------------------------------------------- 重複抑制

def test_same_reason_across_tiers_is_stated_once_then_shortened() -> None:
    rendered = _render(LIVE_LEAKED_REASON)
    assert rendered.count(rm.S2_COUNTER_MATERIAL) == 1
    assert rendered.count(rm.SHORT_UNAVAILABLE) == 2
    assert LIVE_LEAKED_REASON not in rendered


def test_distinct_reasons_each_get_their_detailed_sentence_once() -> None:
    brief = _brief(t1="no_counter_material", t2="no_grounded_points",
                   t3="no_grounded_outlook")
    rendered = rm.render_morning_brief_markdown(brief)
    assert rendered.count(rm.S2_COUNTER_MATERIAL) == 1
    assert rendered.count(rm.S3_GROUNDING_INSUFFICIENT) == 1   # 2 件目は短縮形
    assert rendered.count(rm.SHORT_UNAVAILABLE) == 1
    for reason in ("no_counter_material", "no_grounded_points", "no_grounded_outlook"):
        assert reason not in rendered


def test_deduplication_is_render_local_and_not_shared_between_calls() -> None:
    first = _render(LIVE_LEAKED_REASON)
    second = _render(LIVE_LEAKED_REASON)
    assert first == second                      # 呼び出し間で状態を持ち越さない


# ---------------------------------------------------------------- 凍結契約の不変

def test_public_unavailable_vocabulary_is_unchanged() -> None:
    assert PUBLIC_UNAVAILABLE_REASONS == (
        "draft_not_usable", "draft_abstained", "tier3_unavailable",
        "no_outlook", "direction_mixed", "direction_uncertain")


def test_public_json_key_contracts_are_unchanged() -> None:
    assert PUBLIC_KEYS == ("schema_version", "delivery_id", "session_date",
                           "reference_session", "brief_id", "signal_id",
                           "markdown_sha256", "markdown_bytes", "signal")
    assert PUBLIC_SIGNAL_KEYS == ("available", "label", "unavailable_reason")
    brief = _brief(t1=LIVE_LEAKED_REASON, t2=LIVE_LEAKED_REASON, t3=LIVE_LEAKED_REASON)
    signal = build_market_signal(brief)
    delivery = build_morning_delivery(brief, signal,
                                      rm.render_morning_brief_markdown(brief))
    payload = delivery_public_payload(delivery)
    assert tuple(payload) == PUBLIC_KEYS
    assert payload["signal"]["unavailable_reason"] == "draft_abstained"
    blob = delivery_public_json(delivery)
    assert LIVE_LEAKED_REASON not in blob


def test_morning_delivery_artifact_contract_is_unchanged() -> None:
    names = artifact_names("2026-09-16")
    assert names == ("2026-09-16_morning_brief.md", "2026-09-16_morning_brief.json",
                     "latest_morning_brief.md", "latest_morning_brief.json")
    assert len(names) == 4


def test_dated_and_latest_artifacts_stay_byte_equal() -> None:
    from src.intelligence.reports.delivery_emit import delivery_artifacts
    brief = _brief(t1=LIVE_LEAKED_REASON, t2=LIVE_LEAKED_REASON, t3=LIVE_LEAKED_REASON)
    signal = build_market_signal(brief)
    markdown = rm.render_morning_brief_markdown(brief)
    artifacts = delivery_artifacts(build_morning_delivery(brief, signal, markdown))
    assert set(artifacts) == set(artifact_names("2026-09-16"))
    assert artifacts["2026-09-16_morning_brief.md"] == artifacts["latest_morning_brief.md"]
    assert artifacts["2026-09-16_morning_brief.json"] == artifacts["latest_morning_brief.json"]


def test_v2_published_topology_is_unchanged() -> None:
    from src.intelligence.reports.pages_parallel import published_names
    names = published_names("2026-09-16")
    assert len(names) == 5
    assert names == tuple(sorted(("2026-09-16_morning_brief.md",
                                  "2026-09-16_morning_brief.json",
                                  "latest_morning_brief.md", "latest_morning_brief.json",
                                  "index.html")))


def test_legacy_renderer_remains_disconnected() -> None:
    for name in ("main.py",):
        assert "render_morning_brief_markdown" not in (REPO_ROOT / name).read_text(
            encoding="utf-8")
    for directory in ("notifiers", "src/analysis"):
        for path in (REPO_ROOT / directory).rglob("*.py"):
            assert "render_morning_brief_markdown" not in path.read_text(encoding="utf-8"), path


def test_selector_trust_and_freshness_constants_are_unchanged() -> None:
    import importlib.util
    import sys
    spec = importlib.util.spec_from_file_location(
        "p43b2c_v2_gate_probe", REPO_ROOT / "scripts" / "p43b2c_v2_gate.py")
    gate = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = gate
    spec.loader.exec_module(gate)
    assert gate.MAX_ARTIFACT_AGE_HOURS == 24
    assert gate.MAX_SESSION_LAG_DAYS == 3
    workflow = (REPO_ROOT / ".github" / "workflows" / "daily-market-brief.yml").read_text(
        encoding="utf-8")
    assert 'P43B2C_TRUST_BASELINE: "29c3beaf0c32c56ab5c4129aee89dbd1e06aec8b"' in workflow


def test_other_display_mappings_remain_exhaustive() -> None:
    from src.intelligence.compass.model import Confidence, OutlookDirection
    from src.intelligence.context.model import ContextStatus
    for mapping, enum in ((rm.DIRECTION_JA, OutlookDirection),
                          (rm.CONFIDENCE_JA, Confidence),
                          (rm.STATUS_JA, ContextStatus),
                          (SIGNAL_LEVEL_JA, SignalLevel)):
        values = [member.value for member in enum]
        assert sorted(mapping) == sorted(values), enum


def test_structured_display_values_still_fail_closed() -> None:
    outlook = BriefOutlook(direction="NOT_A_DIRECTION", confidence="LOW",
                           horizon="next_tokyo_session")
    brief = _brief(verdict=QualityVerdict.VALID, tier3_available=True, outlook=outlook)
    with pytest.raises(rm.UnmappedDisplayValue):
        rm.render_morning_brief_markdown(brief)
