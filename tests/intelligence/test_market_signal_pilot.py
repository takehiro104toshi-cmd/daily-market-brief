"""Phase 4 P4-2: Market Signal real-data pilot のテスト。

実 pipeline（seed 済みの隔離 data root）で端から端まで通し、次を見る:
- **実 brief から signal を組んでいること**（方向も確度も独立に計算しない）
- **P4-1 を凍結したまま再利用していること**（renderer を呼ばない・顧客 Markdown を作らない）
- **読み取り専用**（Decision / formal review / DNA / draft store / product store を書かない）
- **決定論**（診断も signal_id も 2 回目と一致）
- **境界**（governance / legacy / Phase 5+ / 外部記事基盤 / 生成モデルを import しない）

Market Signal の意味論 93 件（`test_market_signal.py`）は複製しない。ここは経路の検証。
pytest は Windows の実データに依存しない（隔離 tmp root を seed して回す）。
"""
from __future__ import annotations

import ast
import json
from dataclasses import replace
from pathlib import Path

import pytest

from src.intelligence.compass.model import QualityVerdict
from src.intelligence.reports import market_signal_pilot as signal_pilot
from src.intelligence.reports.market_signal import (
    LEVEL_BY_STATE,
    UNAVAILABLE_BY_DIRECTION,
    SignalLevel,
    build_market_signal,
)
from src.intelligence.reports.model import BriefOutlook
from tests.intelligence.test_context_engine import TestContextPilotEndToEndOffline

PILOT = Path("src/intelligence/reports/market_signal_pilot.py")
P41C_PILOT = Path("src/intelligence/reports/pilot.py")

FORBIDDEN_GOVERNANCE = ("decision", "formal_review", "review", "shadow_review",
                        "corpus", "corpus_research", "replay", "evaluation")
FORBIDDEN_LEGACY = ("report", "analysis", "collectors")
FORBIDDEN_PHASE5 = ("predictions", "themes", "thesis", "screening", "personalization")

MARKERS = ("HEAD", "INPUT", "BRIEF", "SIGNAL", "BINDING", "SAFETY", "END")


# ---------------------------------------------------------------- helpers

def _seed(root: Path) -> None:
    TestContextPilotEndToEndOffline()._seed_market_bank(root)


def _run(capsys, argv=()) -> tuple:
    assert signal_pilot.main(list(argv)) == 0
    out = capsys.readouterr().out
    markers = {}
    for name in MARKERS:
        head = f"::P42_{name}::"
        assert head in out, head
        markers[name] = json.loads(out.split(head)[1].splitlines()[0])
    return out, markers


def _imported_top_levels(path: Path) -> set:
    tops = set()
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.ImportFrom) and node.module:
            tops.add(node.module.lstrip(".").split(".")[0])
        elif isinstance(node, ast.Import):
            for alias in node.names:
                tops.add(alias.name.split(".")[0])
    return tops


@pytest.fixture
def seeded(tmp_path, monkeypatch):
    root = tmp_path / "vnext"
    _seed(root)
    monkeypatch.setenv("INTELLIGENCE_DATA_ROOT", str(root))
    return root


# ---------------------------------------------------------------- end to end

class TestEndToEndOnRealPipeline:
    def test_all_markers_are_emitted(self, seeded, capsys):
        _out, markers = _run(capsys)
        assert set(markers) == set(MARKERS)

    def test_head_declares_the_read_only_contract(self, seeded, capsys):
        _out, markers = _run(capsys)
        head = markers["HEAD"]
        assert head["pilot"] == "phase4_p4_2_market_signal"
        assert head["read_only"] is True
        assert head["persists_product"] is False
        assert head["writes_decisions"] is False
        assert head["promotion"] == "NONE"
        assert head["source"] == "MorningBrief"
        assert head["builder"] == "src.intelligence.reports.market_signal.build_market_signal"
        assert head["schema_version"] == "0.1.0"
        assert head["renders_customer_markdown"] is False

    def test_signal_row_carries_every_model_field(self, seeded, capsys):
        _out, markers = _run(capsys)
        assert set(markers["SIGNAL"]) == {
            "signal_id", "schema_version", "session_date", "reference_session",
            "available", "level", "confidence", "horizon", "brief_id",
            "unavailable_reason", "label"}

    def test_signal_is_built_from_the_emitted_brief(self, seeded, capsys):
        _out, markers = _run(capsys)
        assert markers["SIGNAL"]["brief_id"] == markers["BRIEF"]["brief_id"]
        assert markers["SIGNAL"]["session_date"] == markers["INPUT"]["selected_session"]

    def test_available_signal_matches_the_frozen_mapping(self, seeded, capsys):
        """live データがどの段階でも、凍結写像表と一致していること（段階は pin しない）。"""
        _out, markers = _run(capsys)
        signal, given = markers["SIGNAL"], markers["INPUT"]
        state = (given["outlook_direction"], given["outlook_confidence"])
        if signal["available"]:
            assert LEVEL_BY_STATE[state].value == signal["level"]
            assert signal["confidence"] == given["outlook_confidence"]
            assert signal["horizon"] == given["outlook_horizon"]
        else:
            assert signal["level"] == "" and signal["unavailable_reason"]

    def test_all_bindings_are_true(self, seeded, capsys):
        _out, markers = _run(capsys)
        binding = markers["BINDING"]
        assert binding["all_bindings_true"] is True
        assert binding["failed_bindings"] == []
        for name, value in binding.items():
            if name not in ("all_bindings_true", "failed_bindings"):
                assert value is True, name

    def test_customer_label_is_consistent_with_the_level(self, seeded, capsys):
        _out, markers = _run(capsys)
        signal = markers["SIGNAL"]
        if signal["available"]:
            assert signal["label"] and not signal["label"].isascii()
        else:
            assert signal["label"] == ""

    def test_end_reports_ok(self, seeded, capsys):
        _out, markers = _run(capsys)
        assert markers["END"]["result"] == "OK"
        assert markers["END"]["signal_id"] == markers["SIGNAL"]["signal_id"]

    def test_pilot_skips_cleanly_without_a_market_bank(self, tmp_path, monkeypatch, capsys):
        monkeypatch.setenv("INTELLIGENCE_DATA_ROOT", str(tmp_path / "empty"))
        assert signal_pilot.main([]) == 0
        out = capsys.readouterr().out
        assert "::P42_PILOT_SKIP::" in out
        assert "market_bank_not_local" in out


# ---------------------------------------------------------------- unavailable path

class TestUnavailablePath:
    def test_unavailable_brief_produces_a_structurally_consistent_signal(self):
        """MIXED / tier3 なしなど、段階が出ない日も整合したまま通る。"""
        from src.intelligence.reports.market_signal_pilot import _binding_row
        from tests.intelligence.test_market_signal import _brief as make_brief
        for direction in UNAVAILABLE_BY_DIRECTION:
            brief = make_brief(direction=direction, confidence="LOW")
            signal = build_market_signal(brief)
            binding = _binding_row(signal, brief)
            assert signal.available is False
            assert binding["unavailable_reason_matches_frozen_mapping"] is True
            assert all(v is True for v in binding.values())

    def test_tier3_unavailable_brief_binds_cleanly(self):
        from src.intelligence.reports.market_signal_pilot import _binding_row
        from tests.intelligence.test_market_signal import _brief as make_brief
        brief = make_brief(tier3_available=False, outlook=None,
                           tier3_reason="no_grounded_counter_case")
        signal = build_market_signal(brief)
        assert all(v is True for v in _binding_row(signal, brief).values())

    def test_rejected_verdict_binds_cleanly(self):
        from src.intelligence.reports.market_signal_pilot import _binding_row
        from tests.intelligence.test_market_signal import _brief as make_brief
        brief = make_brief(verdict=QualityVerdict.REJECTED)
        signal = build_market_signal(brief)
        assert signal.available is False
        assert all(v is True for v in _binding_row(signal, brief).values())

    def test_binding_detects_a_broken_mapping(self):
        """写像違反は binding が false を返す（黙って通さない）。"""
        from src.intelligence.reports.market_signal_pilot import _binding_row
        from tests.intelligence.test_market_signal import _brief as make_brief
        brief = make_brief(direction="UPWARD_BIAS", confidence="LOW")
        signal = build_market_signal(brief)
        tampered = replace(signal, level=SignalLevel.DOWNWARD_LEAN)
        assert _binding_row(tampered, brief)["level_matches_frozen_mapping"] is False

    def test_binding_detects_a_broken_provenance(self):
        from src.intelligence.reports.market_signal_pilot import _binding_row
        from tests.intelligence.test_market_signal import _brief as make_brief
        brief = make_brief()
        signal = replace(build_market_signal(brief), brief_id="brief_other")
        assert _binding_row(signal, brief)["brief_id_matches"] is False

    def test_unknown_structural_state_fails_closed(self):
        from tests.intelligence.test_market_signal import _brief as make_brief
        from src.intelligence.reports.market_signal import UnmappedSignalState
        broken = make_brief()
        broken = replace(broken, tier3=replace(
            broken.tier3, outlook=BriefOutlook(direction="SIDEWAYS", confidence="HIGH",
                                               horizon="next_tokyo_session")))
        with pytest.raises(UnmappedSignalState):
            build_market_signal(broken)


# ---------------------------------------------------------------- read-only / safety

class TestReadOnlyAndSafety:
    def test_protected_trees_are_unchanged(self, seeded, capsys):
        _out, markers = _run(capsys)
        safety = markers["SAFETY"]
        assert safety["changed_trees"] == []
        assert safety["all_protected_unchanged"] is True
        assert safety["safety_check"] == "PASSED"
        assert safety["protected_before"] == safety["protected_after"]

    def test_safety_counters_are_all_zero(self, seeded, capsys):
        _out, markers = _run(capsys)
        safety = markers["SAFETY"]
        for name in ("decision_rows_written", "formal_review_writes",
                     "compass_drafts_persisted", "signal_rows_written",
                     "product_files_written"):
            assert safety[name] == 0, name
        assert safety["promotion_status_written"] == "NONE"
        for name in ("compass_dna_mutated", "replay_regenerated",
                     "legacy_report_touched", "customer_markdown_written",
                     "network_used"):
            assert safety[name] is False, name

    def test_every_required_tree_is_protected(self, seeded, capsys):
        _out, markers = _run(capsys)
        required = {"compass", "compass_decisions", "formal_review", "compass_research",
                    "compass_replay", "compass_corpus", "knowledge/compass_dna", "reports"}
        assert required <= set(markers["SAFETY"]["protected_trees"])

    def test_no_file_is_created_under_the_data_root(self, seeded, capsys):
        before = {p.relative_to(seeded).as_posix(): p.stat().st_size
                  for p in seeded.rglob("*") if p.is_file()}
        _run(capsys)
        after = {p.relative_to(seeded).as_posix(): p.stat().st_size
                 for p in seeded.rglob("*") if p.is_file()}
        assert after == before

    def test_no_product_tree_is_created(self, seeded, capsys):
        _run(capsys)
        for name in ("reports", "compass", "compass_decisions", "formal_review"):
            assert not (seeded / name).exists(), name

    def test_failure_is_reported_when_a_protected_tree_changes(self, seeded,
                                                               monkeypatch, capsys):
        """安全確認が壊れたら FAILED を出し、非ゼロで落ちる。"""
        real = signal_pilot._capture
        calls = {"n": 0}

        def fake(root, repo):
            calls["n"] += 1
            snapshot = real(root, repo)
            if calls["n"] > 1:                       # after 側だけ変化させる
                snapshot["compass"] = dict(snapshot["compass"], files=99, digest="dead")
            return snapshot

        monkeypatch.setattr(signal_pilot, "_capture", fake)
        assert signal_pilot.main([]) == 1
        out = capsys.readouterr().out
        safety = json.loads(out.split("::P42_SAFETY::")[1].splitlines()[0])
        assert safety["safety_check"] == "FAILED"
        assert safety["changed_trees"] == ["compass"]
        assert safety["all_protected_unchanged"] is False
        assert json.loads(out.split("::P42_END::")[1].splitlines()[0])["result"] == \
            "SAFETY_FAILED"

    def test_source_declares_no_write_path(self):
        src = PILOT.read_text(encoding="utf-8")
        for name in ("write_text", "write_bytes", "open(", "mkdir", "touch(",
                     "json.dump(", "requests", "urllib", "socket"):
            assert name not in src, name


# ---------------------------------------------------------------- determinism

class TestDeterminism:
    def test_repeated_runs_agree(self, seeded, capsys):
        _first, a = _run(capsys)
        _second, b = _run(capsys)
        assert a["SIGNAL"] == b["SIGNAL"]
        assert a["BINDING"] == b["BINDING"]
        assert a["BRIEF"] == b["BRIEF"]

    def test_same_brief_gives_the_same_signal_id(self, seeded, capsys):
        _first, a = _run(capsys)
        _second, b = _run(capsys)
        assert a["SIGNAL"]["signal_id"] == b["SIGNAL"]["signal_id"]
        assert a["END"]["signal_id"] == b["END"]["signal_id"]


# ---------------------------------------------------------------- P4-1 freeze

class TestP41IsUntouched:
    def test_p41c_pilot_source_is_not_referenced(self):
        src = PILOT.read_text(encoding="utf-8")
        assert "reports.pilot" not in src and "from .pilot" not in src

    def test_renderer_is_never_called(self):
        src = PILOT.read_text(encoding="utf-8")
        assert "render_markdown" not in src
        assert "render_morning_brief_markdown" not in src

    def test_no_customer_markdown_marker_is_emitted(self, seeded, capsys):
        out, _markers = _run(capsys)
        for name in ("::P41C_", "::P42_SIGNAL_BADGE::", "モーニングブリーフ",
                     "30秒版", "3分版", "詳細版"):
            assert name not in out, name

    def test_p41c_pilot_still_forbids_market_signal(self):
        """既存ガードを壊していない（P4-1C pilot に signal は入っていない）。"""
        src = P41C_PILOT.read_text(encoding="utf-8")
        assert "market_signal" not in src and "MarketSignal" not in src

    def test_frozen_p41_sources_have_no_signal_reference(self):
        for name in ("model.py", "morning_brief.py", "render_markdown.py", "pilot.py"):
            src = (Path("src/intelligence/reports") / name).read_text(encoding="utf-8")
            assert "market_signal" not in src, name
            assert "MarketSignal" not in src, name


# ---------------------------------------------------------------- isolation

class TestIsolation:
    def test_no_governance_imports(self):
        assert not _imported_top_levels(PILOT) & set(FORBIDDEN_GOVERNANCE)

    def test_no_legacy_imports(self):
        src = PILOT.read_text(encoding="utf-8")
        for legacy in FORBIDDEN_LEGACY:
            assert f"src.{legacy}" not in src
        assert not _imported_top_levels(PILOT) & set(FORBIDDEN_LEGACY)

    def test_no_phase5_imports(self):
        assert not _imported_top_levels(PILOT) & set(FORBIDDEN_PHASE5)

    def test_no_article_tank_imports(self):
        src = PILOT.read_text(encoding="utf-8")
        for name in ("article-intelligence-data-tank", "external_intelligence", "tank"):
            assert name not in src, name

    def test_no_llm_imports(self):
        src = PILOT.read_text(encoding="utf-8")
        for name in ("llm", "anthropic", "openai"):
            assert name not in src, name

    def test_imports_stay_inside_the_allowed_layers(self):
        allowed = {"__future__", "argparse", "hashlib", "json", "datetime", "pathlib",
                   "typing", "compass", "context", "core", "model", "morning_brief",
                   "market_signal"}
        tops = _imported_top_levels(PILOT)
        assert tops <= allowed, tops - allowed


# ---------------------------------------------------------------- confidentiality

class TestConfidentiality:
    def test_stdout_leaks_no_machine_path_or_source_name(self, seeded, capsys,
                                                         monkeypatch):
        monkeypatch.setenv("JQUANTS_API_KEY", "sk-SENTINEL-must-not-print")
        out, _markers = _run(capsys)
        assert str(seeded) not in out
        assert "sk-SENTINEL-must-not-print" not in out
        for name in ("C:\\", "/Users/", "/home/", ".pdf", "source_docs", "rashinban",
                     "/tmp/", "runner"):
            assert name not in out, name

    def test_stdout_carries_no_governance_record(self, seeded, capsys):
        out, markers = _run(capsys)
        for name in ("decision_id", "cdc_", "record_hash", "packet_id", "candidate_id",
                     "KEEP_REVIEWING", "APPROVE_RECOMMENDED", "NOT_PROMOTED",
                     "replay_run_id", "shadow_review", "formal_review_id"):
            assert name not in out, name
        # promotion は「行っていない」という安全表明としてのみ現れる
        assert markers["SAFETY"]["promotion_status_written"] == "NONE"
        assert markers["HEAD"]["promotion"] == "NONE"
        assert out.count("promotion") == 2

    def test_stdout_carries_no_claim_or_article_text(self, seeded, capsys):
        out, markers = _run(capsys)
        for name in ("前営業日", "終値", "無効化条件", "根拠:", "反対材料:", "対象範囲:"):
            assert name not in out, name
        assert "claims" not in markers["BRIEF"]

    def test_content_addressed_ids_are_allowed(self, seeded, capsys):
        _out, markers = _run(capsys)
        assert markers["SIGNAL"]["signal_id"].startswith("signal_")
        assert markers["BRIEF"]["brief_id"].startswith("brief_")
        assert markers["BRIEF"]["draft_id"].startswith("compass_")
