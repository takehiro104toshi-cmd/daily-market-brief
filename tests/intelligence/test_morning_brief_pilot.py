"""Phase 4 P4-1C: Morning Brief real-data pilot のテスト。

実 pipeline（seed 済みの隔離 data root）で端から端まで通し、次を見る:
- **実 draft を使っていること**（手組み draft で brief を作らない）
- **P4-1A / P4-1B をそのまま再利用していること**（別 composer / 別 renderer を作らない）
- **読み取り専用**（Decision / formal review / DNA / draft store / product store を書かない）
- **決定論**（診断も Markdown digest も 2 回目と一致）
- **境界**（governance / legacy / Phase 5+ を import しない、機密や machine path を出さない）

pytest は Windows の実データに依存しない（隔離 tmp root を seed して回す）。
"""
from __future__ import annotations

import ast
import hashlib
import json
from dataclasses import replace
from pathlib import Path

import pytest

from src.intelligence.compass.model import QualityVerdict
from src.intelligence.compass.pilot import load_pilot_inputs
from src.intelligence.compass.pipeline import run_pipeline
from src.intelligence.context.snapshot import morning_context_snapshot
from src.intelligence.reports import pilot as brief_pilot
from src.intelligence.reports.morning_brief import build_morning_brief
from src.intelligence.reports.render_markdown import render_morning_brief_markdown
from tests.intelligence.test_context_engine import TestContextPilotEndToEndOffline

PILOT = Path("src/intelligence/reports/pilot.py")

FORBIDDEN_GOVERNANCE = (
    "decision", "formal_review", "review", "shadow_review",
    "corpus", "corpus_research", "replay", "evaluation",
)
FORBIDDEN_LEGACY = ("report", "analysis", "collectors")
FORBIDDEN_PHASE5 = ("predictions", "themes", "thesis", "screening", "personalization")

MARKERS = ("HEAD", "INPUT", "COMPASS", "BRIEF", "MARKDOWN", "SAFETY", "END")


# ---------------------------------------------------------------- helpers

def _seed(root: Path) -> None:
    TestContextPilotEndToEndOffline()._seed_market_bank(root)


def _run(capsys, argv=()) -> tuple[str, dict]:
    assert brief_pilot.main(list(argv)) == 0
    out = capsys.readouterr().out
    markers = {}
    for name in MARKERS:
        token = f"::P41C_{name}::"
        assert token in out, token
        markers[name] = json.loads(out.split(token)[1].splitlines()[0])
    return out, markers


def _markdown_block(out: str) -> str:
    body = out.split(brief_pilot.MARKDOWN_BEGIN + "\n")[1]
    return body.split(brief_pilot.MARKDOWN_END)[0]


def _tree_listing(root: Path) -> set:
    return {p.relative_to(root).as_posix() for p in root.rglob("*") if p.is_file()}


def _imported_top_levels(path: Path):
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.ImportFrom) and node.module:
            yield node.module.lstrip(".").split(".")[0]
        elif isinstance(node, ast.Import):
            for alias in node.names:
                yield alias.name.split(".")[0]


@pytest.fixture
def seeded(tmp_path, monkeypatch):
    monkeypatch.setenv("INTELLIGENCE_DATA_ROOT", str(tmp_path))
    _seed(tmp_path)
    return tmp_path


# ---------------------------------------------------------------- pipeline binding

class TestPipelineBinding:
    def test_pilot_uses_actual_compass_pipeline_output(self, seeded, capsys):
        _out, m = _run(capsys)
        # 同じ入力で pipeline を独立に回し、draft / package が一致することを見る
        inputs = load_pilot_inputs(now=__import__("datetime").datetime.now(
            __import__("datetime").timezone.utc), sessions_of_facts=6, root=seeded)
        snapshot = morning_context_snapshot(list(inputs.context_items),
                                            m["INPUT"]["selected_session"])
        result = run_pipeline(snapshot, list(inputs.facts), generator=None,
                              config=inputs.config)
        assert m["COMPASS"]["draft_id"] == result.draft.draft_id
        assert m["COMPASS"]["package_id"] == result.package.package_id
        assert m["COMPASS"]["verdict"] == result.draft.verdict.value

    def test_brief_ids_bind_to_produced_draft_and_package(self, seeded, capsys):
        _out, m = _run(capsys)
        binding = m["BRIEF"]["binding"]
        assert binding == {"draft_id_matches": True, "package_id_matches": True,
                           "session_date_matches": True,
                           "reference_session_matches": True, "verdict_matches": True}
        assert m["BRIEF"]["draft_id"] == m["COMPASS"]["draft_id"]
        assert m["BRIEF"]["package_id"] == m["COMPASS"]["package_id"]
        assert m["BRIEF"]["verdict"] == m["COMPASS"]["verdict"]

    def test_markdown_equals_rendering_the_produced_brief(self, seeded, capsys):
        out, m = _run(capsys)
        import datetime as _dt
        inputs = load_pilot_inputs(now=_dt.datetime.now(_dt.timezone.utc),
                                   sessions_of_facts=6, root=seeded)
        snapshot = morning_context_snapshot(list(inputs.context_items),
                                            m["INPUT"]["selected_session"])
        result = run_pipeline(snapshot, list(inputs.facts), generator=None,
                              config=inputs.config)
        expected = render_morning_brief_markdown(
            build_morning_brief(result.draft, result.package))
        assert _markdown_block(out) == expected
        assert m["MARKDOWN"]["sha256"] == hashlib.sha256(
            expected.encode("utf-8")).hexdigest()

    def test_composer_is_called_after_the_pipeline(self, seeded, capsys):
        """brief marker は compass marker より後に出る（順序で段階を示す）。"""
        out, _m = _run(capsys)
        assert out.index("::P41C_COMPASS::") < out.index("::P41C_BRIEF::")
        assert out.index("::P41C_BRIEF::") < out.index("::P41C_MARKDOWN::")

    def test_no_hand_built_draft_bypass(self):
        source = PILOT.read_text(encoding="utf-8")
        for token in ("CompassDraft(", "CompassClaim(", "CompassOutlook(",
                      "EvidencePackage(", "QualityVerdict.VALID", "GroundingStatus."):
            assert token not in source, token
        assert "run_pipeline(" in source

    def test_existing_apis_are_reused_not_duplicated(self):
        source = PILOT.read_text(encoding="utf-8")
        assert "build_morning_brief(" in source
        assert "render_morning_brief_markdown(" in source
        assert "load_pilot_inputs(" in source
        tree = ast.parse(source)
        defs = {n.name for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)}
        assert not {"build_morning_brief", "render_morning_brief_markdown"} & defs
        assert "MorningBrief(" not in source        # 別 composer を持たない


# ---------------------------------------------------------------- determinism

class TestDeterminism:
    def test_diagnostics_and_digest_are_stable_across_runs(self, seeded, capsys):
        out1, m1 = _run(capsys)
        out2, m2 = _run(capsys)
        for name in ("INPUT", "COMPASS", "BRIEF", "MARKDOWN"):
            assert m1[name] == m2[name], name
        assert _markdown_block(out1) == _markdown_block(out2)
        assert m1["MARKDOWN"]["sha256"] == m2["MARKDOWN"]["sha256"]

    def test_markdown_block_boundaries_are_stable(self, seeded, capsys):
        out, m = _run(capsys)
        assert out.count(brief_pilot.MARKDOWN_BEGIN) == 1
        assert out.count(brief_pilot.MARKDOWN_END) == 1
        block = _markdown_block(out)
        assert block.startswith("# ") and block.endswith("\n")
        assert m["MARKDOWN"]["bytes"] == len(block.encode("utf-8"))
        assert m["MARKDOWN"]["headings"][0].startswith("# ")

    def test_explicit_session_date_is_honoured(self, seeded, capsys):
        _out, m = _run(capsys)
        target = m["INPUT"]["mornings"][-2]
        _out2, m2 = _run(capsys, ["--session-date", target])
        assert m2["INPUT"]["selected_session"] == target
        assert m2["INPUT"]["session_selection"] == "explicit"
        assert m2["BRIEF"]["session_date"] == target


# ---------------------------------------------------------------- read-only

class TestReadOnly:
    def test_no_file_is_written_under_the_data_root(self, seeded, capsys):
        before = _tree_listing(seeded)
        _run(capsys)
        assert _tree_listing(seeded) == before

    def test_no_decision_or_formal_review_write(self, seeded, capsys):
        _out, m = _run(capsys)
        safety = m["SAFETY"]
        assert safety["all_protected_unchanged"] is True
        assert safety["changed_trees"] == []
        assert safety["decision_rows_written"] == 0
        assert safety["formal_review_writes"] == 0
        assert safety["safety_check"] == "PASSED"
        assert not (seeded / "compass_decisions").exists()

    def test_no_product_persistence(self, seeded, capsys):
        _out, m = _run(capsys)
        assert m["SAFETY"]["compass_drafts_persisted"] == 0
        assert m["SAFETY"]["product_files_written"] == 0
        assert not (seeded / "compass" / "drafts.jsonl").exists()
        assert not (seeded / "reports").exists()
        for name in ("briefs.jsonl", "morning_brief.md", "morning_brief.html"):
            assert not list(seeded.rglob(name))

    def test_no_promotion_and_no_dna_mutation(self, seeded, capsys):
        _out, m = _run(capsys)
        assert m["SAFETY"]["promotion_status_written"] == "NONE"
        assert m["SAFETY"]["compass_dna_mutated"] is False
        assert m["SAFETY"]["replay_regenerated"] is False
        dna = m["SAFETY"]["protected_before"]["knowledge/compass_dna"]
        assert dna == m["SAFETY"]["protected_after"]["knowledge/compass_dna"]
        assert "promote" not in PILOT.read_text(encoding="utf-8")

    def test_head_declares_read_only_contract(self, seeded, capsys):
        _out, m = _run(capsys)
        head = m["HEAD"]
        assert head["read_only"] is True and head["persists_product"] is False
        assert head["writes_decisions"] is False and head["promotion"] == "NONE"


# ---------------------------------------------------------------- degraded paths

class TestDegradedPaths:
    def test_skips_cleanly_without_market_bank(self, tmp_path, monkeypatch, capsys):
        monkeypatch.setenv("INTELLIGENCE_DATA_ROOT", str(tmp_path))
        assert brief_pilot.main([]) == 0
        out = capsys.readouterr().out
        assert "::P41C_PILOT_SKIP::" in out
        assert "::P41C_COMPASS::" not in out and "::P41C_BRIEF::" not in out

    def test_unknown_session_date_skips_without_guessing(self, seeded, capsys):
        assert brief_pilot.main(["--session-date", "1999-01-04"]) == 0
        out = capsys.readouterr().out
        assert "session_date_not_available" in out
        assert "::P41C_BRIEF::" not in out and brief_pilot.MARKDOWN_BEGIN not in out

    def test_missing_and_unreliable_dimensions_are_surfaced(self, seeded, capsys):
        """診断には生キー、customer Markdown には日本語ラベルで出ること（P4-1 presentation）。"""
        from src.intelligence.reports.render_markdown import DIMENSION_JA

        out, m = _run(capsys)
        surfaced = (list(m["BRIEF"]["missing_dimensions"])
                    + list(m["BRIEF"]["unreliable_dimensions"]))
        assert surfaced, "seed が劣化次元を作らないと本テストは無意味"
        assert m["BRIEF"]["unreliable_dimensions"] == \
            m["COMPASS"]["package_unreliable_dimensions"]
        block = _markdown_block(out)
        for dim in surfaced:
            assert dim not in block                 # 生キーは顧客向けに出さない
            assert DIMENSION_JA[dim] in block       # ラベルは出す

    def test_abstained_pipeline_result_is_handled_safely(self, seeded, capsys, monkeypatch):
        """実 pipeline 結果を ABSTAINED に差し替えても、無根拠の散文を出さない。"""
        real = brief_pilot.run_pipeline

        def abstained(*args, **kwargs):
            result = real(*args, **kwargs)
            draft = replace(result.draft, verdict=QualityVerdict.ABSTAINED,
                            abstain_reason="no_counter_case", one_liner="")
            return replace(result, draft=draft)

        monkeypatch.setattr(brief_pilot, "run_pipeline", abstained)
        out, m = _run(capsys)
        assert m["COMPASS"]["verdict"] == "ABSTAINED"
        assert (m["BRIEF"]["tier1_available"], m["BRIEF"]["tier2_available"],
                m["BRIEF"]["tier3_available"]) == (False, False, False)
        block = _markdown_block(out)
        body = "\n".join(l for l in block.splitlines() if not l.startswith("#"))
        for word in ("上昇", "下落", "堅調", "軟調", "とみられる"):
            assert word not in body
        assert m["SAFETY"]["safety_check"] == "PASSED"


# ---------------------------------------------------------------- isolation / leakage

class TestIsolationAndLeakage:
    def test_no_governance_imports(self):
        tops = set(_imported_top_levels(PILOT))
        assert not tops & set(FORBIDDEN_GOVERNANCE), tops

    def test_no_legacy_imports(self):
        source = PILOT.read_text(encoding="utf-8")
        for legacy in FORBIDDEN_LEGACY:
            assert f"src.{legacy}" not in source
        assert not set(_imported_top_levels(PILOT)) & set(FORBIDDEN_LEGACY)

    def test_no_phase5_plus_imports(self):
        tops = set(_imported_top_levels(PILOT))
        assert not tops & set(FORBIDDEN_PHASE5), tops
        source = PILOT.read_text(encoding="utf-8")
        for token in ("market_signal", "MarketSignal", "llm", "anthropic", "openai"):
            assert token not in source, token

    def test_stdout_leaks_no_machine_path_or_source_name(self, seeded, capsys, monkeypatch):
        monkeypatch.setenv("JQUANTS_API_KEY", "sk-SENTINEL-must-not-print")
        out, _m = _run(capsys)
        assert str(seeded) not in out
        assert "sk-SENTINEL-must-not-print" not in out
        for token in ("C:\\", "/Users/", ".pdf", "source_docs", "rashinban",
                      "INTELLIGENCE_DATA_ROOT", "/home/"):
            assert token not in out, token

    def test_markdown_block_carries_no_internal_ids(self, seeded, capsys):
        out, _m = _run(capsys)
        block = _markdown_block(out)
        for prefix in ("cpt_", "cdc_", "frp_", "crp_", "ctx_", "evpkg_", "compass_",
                       "brief_", "claim_"):
            assert prefix not in block, prefix
