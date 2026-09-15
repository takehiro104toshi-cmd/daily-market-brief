"""Phase 4 P4-3a: Morning Delivery real-data pilot のテスト。

実 pipeline（seed 済みの隔離 data root）で端から端まで通し、次を見る:
- **この run の brief / signal / Markdown からのみ配信物を組んでいること**
- **書き出し先は明示指定必須**（リポジトリの `output/v2/` へ黙って落ちない）
- **隔離 sandbox に 4 file ちょうど**、保護 subtree は不変
- **公開 JSON が凍結契約どおり**で、内部語彙が 1 つも漏れていないこと
- **境界**（legacy / notifier / governance / Phase 5 / 外部記事基盤 / 生成モデル）

packaging / emitter の意味論 87 件は複製しない。ここは経路の検証。
"""
from __future__ import annotations

import ast
import hashlib
import json
from pathlib import Path

import pytest

from src.intelligence.reports import delivery_pilot
from src.intelligence.reports.delivery import PUBLIC_KEYS, PUBLIC_SIGNAL_KEYS
from src.intelligence.reports.delivery_emit import (
    LATEST_JSON,
    LATEST_MARKDOWN,
    artifact_names,
)
from src.intelligence.reports.delivery_pilot import (
    OUTPUT_ROOT_ENV,
    DeliveryOutputNotConfigured,
    resolve_output_dir,
)
from src.intelligence.reports.market_signal import SIGNAL_LEVEL_JA
from src.intelligence.reports.model import MORNING_BRIEF_SCHEMA_VERSION
from tests.intelligence.test_context_engine import TestContextPilotEndToEndOffline

PILOT = Path("src/intelligence/reports/delivery_pilot.py")
REPORTS_DIR = Path("src/intelligence/reports")

FORBIDDEN_GOVERNANCE = ("decision", "formal_review", "review", "shadow_review",
                        "corpus", "corpus_research", "replay", "evaluation")
FORBIDDEN_LEGACY = ("report", "analysis", "collectors")
FORBIDDEN_PHASE5 = ("predictions", "themes", "thesis", "screening", "personalization")

MARKERS = ("HEAD", "INPUT", "BRIEF", "SIGNAL", "DELIVERY", "ARTIFACTS",
           "BINDING", "SAFETY", "END")

#: 公開 JSON に現れてはならない内部語彙（実バイト列に対する走査）
LEAK_TOKENS = (
    "draft_id", "package_id", "claim_id", "fact_id", "ctx_id", "rule_ref",
    "principle_refs", "compass_", "evpkg_",
    "UPWARD_BIAS", "DOWNWARD_BIAS", "RANGE_BOUND", "MIXED", "UNCERTAIN",
    "HIGH", "MEDIUM", "LOW", "next_tokyo_session", "JP_",
    "nikkei_vs_topix", "nt_ratio", "japan_rates", "usd_jpy", "japan_equities",
    "us_rates_2y", "us_rates_10y", "us_curve", "breadth", "turnover",
    "無効化条件", "根拠:", "反対材料:", "対象範囲:", "前営業日", "終値",
    "decision_id", "cdc_", "record_hash", "packet_id", "candidate_id",
    "KEEP_REVIEWING", "NOT_PROMOTED", "replay_run_id",
    "/home/", "/tmp/", "C:\\", "api_key", "sk-",
)
#: 顧客面に出てはならない助言語（`%` は Markdown の相場データとして正当なので除外）
ADVICE_TOKENS = ("強気", "弱気", "買い", "売り", "推奨", "おすすめ",
                 "目標株価", "ターゲット", "妙味", "押し目", "確率")


# ---------------------------------------------------------------- helpers

def _seed(root: Path) -> None:
    TestContextPilotEndToEndOffline()._seed_market_bank(root)


def _tops(path: Path) -> set:
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


@pytest.fixture
def sandbox(tmp_path, monkeypatch):
    out = tmp_path / "p43_delivery_output" / "v2"
    monkeypatch.setenv(OUTPUT_ROOT_ENV, str(out))
    return out


def _run(capsys, argv=()) -> tuple:
    assert delivery_pilot.main(list(argv)) == 0
    out = capsys.readouterr().out
    markers = {}
    for name in MARKERS:
        head = f"::P43_{name}::"
        assert head in out, head
        markers[name] = json.loads(out.split(head)[1].splitlines()[0])
    return out, markers


# ---------------------------------------------------------------- output policy

class TestOutputRootPolicy:
    """39, 40。"""

    def test_missing_output_dir_fails_closed(self):
        with pytest.raises(DeliveryOutputNotConfigured):
            resolve_output_dir("", env={})

    def test_blank_output_dir_fails_closed(self):
        with pytest.raises(DeliveryOutputNotConfigured):
            resolve_output_dir("   ", env={OUTPUT_ROOT_ENV: "  "})

    def test_env_and_flag_are_both_honoured(self, tmp_path):
        assert resolve_output_dir("", env={OUTPUT_ROOT_ENV: str(tmp_path)}) == tmp_path
        assert resolve_output_dir(str(tmp_path), env={}) == tmp_path

    def test_pilot_main_fails_closed_without_output_root(self, seeded, monkeypatch):
        monkeypatch.delenv(OUTPUT_ROOT_ENV, raising=False)
        with pytest.raises(DeliveryOutputNotConfigured):
            delivery_pilot.main([])

    def test_pilot_never_writes_the_repository_output_v2(self, seeded, sandbox, capsys):
        """既定出力先へ落ちないこと（実行後もリポジトリ側は存在しない）。"""
        _run(capsys)
        assert not (Path("output") / "v2").exists()

    def test_source_does_not_use_the_default_output_dir(self):
        src = PILOT.read_text(encoding="utf-8")
        assert "DEFAULT_OUTPUT_DIR" not in src


# ---------------------------------------------------------------- end to end

class TestEndToEndOnRealPipeline:
    """1, 2, 37。"""

    def test_all_markers_are_emitted(self, seeded, sandbox, capsys):
        _out, markers = _run(capsys)
        assert set(markers) == set(MARKERS)

    def test_head_declares_the_contract(self, seeded, sandbox, capsys):
        _out, markers = _run(capsys)
        head = markers["HEAD"]
        assert head["pilot"] == "phase4_p4_3a_morning_delivery"
        assert head["schema_version"] == "0.1.0"
        assert head["read_only_intelligence"] is True
        assert head["writes_delivery_artifacts"] is True
        assert head["persists_canonical_intelligence"] is False
        assert head["writes_decisions"] is False
        assert head["promotion"] == "NONE"
        assert head["formats"] == ["MARKDOWN", "JSON"]
        assert head["source"] == "MorningBrief + MarketSignal + frozen Markdown"
        assert head["builder"] == "src.intelligence.reports.delivery.build_morning_delivery"
        assert head["emitter"] == "src.intelligence.reports.delivery_emit"

    def test_end_reports_ok(self, seeded, sandbox, capsys):
        _out, markers = _run(capsys)
        assert markers["END"]["result"] == "OK"
        assert markers["END"]["artifacts"] == 4
        assert markers["END"]["delivery_id"] == markers["DELIVERY"]["delivery_id"]

    def test_repeated_run_is_deterministic(self, seeded, sandbox, capsys):
        _first, a = _run(capsys)
        _second, b = _run(capsys)
        assert a["DELIVERY"] == b["DELIVERY"]
        assert a["ARTIFACTS"] == b["ARTIFACTS"]
        assert a["BRIEF"] == b["BRIEF"] and a["SIGNAL"] == b["SIGNAL"]

    def test_unavailable_signal_path_is_still_consistent(self, seeded, sandbox, capsys):
        """live signal が available でなくても配信物は成立し、方向を作らない。"""
        _out, markers = _run(capsys)
        signal = markers["SIGNAL"]
        payload = json.loads((sandbox / LATEST_JSON).read_text(encoding="utf-8"))
        if signal["available"]:
            assert payload["signal"]["label"] == signal["label"]
            assert payload["signal"]["label"] in SIGNAL_LEVEL_JA.values()
        else:
            assert payload["signal"]["label"] == ""
            assert payload["signal"]["unavailable_reason"]

    def test_pilot_skips_cleanly_without_a_market_bank(self, tmp_path, monkeypatch,
                                                      capsys):
        monkeypatch.setenv("INTELLIGENCE_DATA_ROOT", str(tmp_path / "empty"))
        monkeypatch.setenv(OUTPUT_ROOT_ENV, str(tmp_path / "out" / "v2"))
        assert delivery_pilot.main([]) == 0
        out = capsys.readouterr().out
        assert "::P43_PILOT_SKIP::" in out and "market_bank_not_local" in out


# ---------------------------------------------------------------- binding

class TestBindingChain:
    """3–6。"""

    def test_all_bindings_are_true(self, seeded, sandbox, capsys):
        _out, markers = _run(capsys)
        binding = markers["BINDING"]
        assert binding["all_bindings_true"] is True
        assert binding["failed_bindings"] == []
        for name, value in binding.items():
            if name not in ("all_bindings_true", "failed_bindings"):
                assert value is True, name

    def test_brief_binding(self, seeded, sandbox, capsys):
        _out, markers = _run(capsys)
        assert markers["DELIVERY"]["brief_id"] == markers["BRIEF"]["brief_id"]
        assert markers["DELIVERY"]["session_date"] == markers["BRIEF"]["session_date"]
        assert (markers["DELIVERY"]["reference_session"]
                == markers["BRIEF"]["reference_session"])

    def test_signal_binding(self, seeded, sandbox, capsys):
        _out, markers = _run(capsys)
        assert markers["DELIVERY"]["signal_id"] == markers["SIGNAL"]["signal_id"]
        assert markers["SIGNAL"]["brief_id"] == markers["BRIEF"]["brief_id"]

    def test_delivery_id_binding_reaches_the_artifact(self, seeded, sandbox, capsys):
        _out, markers = _run(capsys)
        payload = json.loads((sandbox / LATEST_JSON).read_text(encoding="utf-8"))
        assert payload["delivery_id"] == markers["DELIVERY"]["delivery_id"]
        assert payload["brief_id"] == markers["BRIEF"]["brief_id"]
        assert payload["signal_id"] == markers["SIGNAL"]["signal_id"]


# ---------------------------------------------------------------- artifacts

class TestArtifacts:
    """7–10, 24–26。"""

    def test_exactly_the_four_approved_artifacts(self, seeded, sandbox, capsys):
        _out, markers = _run(capsys)
        session = markers["DELIVERY"]["session_date"]
        assert {p.name for p in sandbox.iterdir()} == set(artifact_names(session))
        assert markers["ARTIFACTS"]["written"] == 4
        assert markers["ARTIFACTS"]["expected"] == 4
        assert markers["ARTIFACTS"]["unexpected_files"] == []

    def test_no_fifth_artifact(self, seeded, sandbox, capsys):
        _run(capsys)
        assert len(list(sandbox.iterdir())) == 4

    def test_artifact_checks_all_pass(self, seeded, sandbox, capsys):
        _out, markers = _run(capsys)
        for name, ok in markers["ARTIFACTS"]["checks"].items():
            assert ok is True, name

    def test_dated_and_latest_markdown_are_equal(self, seeded, sandbox, capsys):
        _out, markers = _run(capsys)
        session = markers["DELIVERY"]["session_date"]
        assert ((sandbox / f"{session}_morning_brief.md").read_bytes()
                == (sandbox / LATEST_MARKDOWN).read_bytes())

    def test_dated_and_latest_json_are_equal(self, seeded, sandbox, capsys):
        _out, markers = _run(capsys)
        session = markers["DELIVERY"]["session_date"]
        assert ((sandbox / f"{session}_morning_brief.json").read_bytes()
                == (sandbox / LATEST_JSON).read_bytes())

    def test_markdown_bytes_match_the_delivery(self, seeded, sandbox, capsys):
        _out, markers = _run(capsys)
        blob = (sandbox / LATEST_MARKDOWN).read_bytes()
        assert len(blob) == markers["DELIVERY"]["markdown_bytes"]
        assert hashlib.sha256(blob).hexdigest() == markers["DELIVERY"]["markdown_sha256"]

    def test_no_market_signal_header_in_markdown(self, seeded, sandbox, capsys):
        """凍結 Markdown に signal 見出しが挿入されていないこと。"""
        _out, markers = _run(capsys)
        text = (sandbox / LATEST_MARKDOWN).read_text(encoding="utf-8")
        assert text.startswith("# モーニングブリーフ")
        for label in SIGNAL_LEVEL_JA.values():
            assert label not in text, label
        assert "delivery_" not in text and "signal_" not in text

    def test_no_html_sqlite_jsonl_or_index(self, seeded, sandbox, capsys):
        _run(capsys)
        for path in sandbox.rglob("*"):
            assert path.suffix not in (".html", ".sqlite3", ".jsonl", ".db"), path
        assert not (sandbox / "index").exists()

    def test_no_temp_residue(self, seeded, sandbox, capsys):
        _run(capsys)
        assert not [p for p in sandbox.iterdir() if p.name.startswith(".")]
        assert not [p for p in sandbox.iterdir() if p.suffix == ".part"]


# ---------------------------------------------------------------- public JSON

class TestPublicJsonArtifact:
    """11–14。"""

    def test_exact_public_key_sets(self, seeded, sandbox, capsys):
        _out, markers = _run(capsys)
        payload = json.loads((sandbox / LATEST_JSON).read_text(encoding="utf-8"))
        # artifact は sort_keys=True。key 順ではなく集合が契約（宣言順は packaging 側で検証）
        assert set(payload) == set(PUBLIC_KEYS)
        assert set(payload["signal"]) == set(PUBLIC_SIGNAL_KEYS)
        assert markers["ARTIFACTS"]["public_top_level_keys"] == sorted(PUBLIC_KEYS)
        assert markers["ARTIFACTS"]["public_signal_keys"] == sorted(PUBLIC_SIGNAL_KEYS)

    def test_public_json_leak_sweep_on_real_bytes(self, seeded, sandbox, capsys):
        _run(capsys)
        for name in (LATEST_JSON,):
            blob = (sandbox / name).read_text(encoding="utf-8")
            for leak in LEAK_TOKENS:
                assert leak not in blob, (name, leak)

    def test_no_advice_language_in_the_public_label(self, seeded, sandbox, capsys):
        _run(capsys)
        payload = json.loads((sandbox / LATEST_JSON).read_text(encoding="utf-8"))
        label = payload["signal"]["label"]
        for advice in ADVICE_TOKENS:
            assert advice not in label, advice
        assert label == "" or label in SIGNAL_LEVEL_JA.values()

    def test_frozen_markdown_carries_no_advice_language(self, seeded, sandbox, capsys):
        """`%` は相場データとして正当なので対象外（助言語のみ検査）。"""
        _run(capsys)
        text = (sandbox / LATEST_MARKDOWN).read_text(encoding="utf-8")
        for advice in ADVICE_TOKENS:
            assert advice not in text, advice


# ---------------------------------------------------------------- safety

class TestSafety:
    """15–23。"""

    def test_protected_trees_unchanged(self, seeded, sandbox, capsys):
        _out, markers = _run(capsys)
        safety = markers["SAFETY"]
        assert safety["protected_changed_trees"] == []
        assert safety["all_protected_unchanged"] is True
        assert safety["protected_before"] == safety["protected_after"]
        assert safety["safety_check"] == "PASSED"

    def test_delivery_sandbox_counters(self, seeded, sandbox, capsys):
        _out, markers = _run(capsys)
        safety = markers["SAFETY"]
        assert safety["delivery_files_written"] == 4
        assert safety["delivery_files_expected"] == 4
        assert safety["unexpected_delivery_files"] == []

    def test_no_legacy_pages_or_notifier_effect(self, seeded, sandbox, capsys):
        _out, markers = _run(capsys)
        safety = markers["SAFETY"]
        assert safety["legacy_output_touched"] is False
        assert safety["pages_touched"] is False
        assert safety["notifier_invoked"] is False

    def test_governance_and_store_counters_are_zero(self, seeded, sandbox, capsys):
        _out, markers = _run(capsys)
        safety = markers["SAFETY"]
        for name in ("decision_rows_written", "formal_review_writes",
                     "compass_drafts_persisted"):
            assert safety[name] == 0, name
        for name in ("compass_dna_mutated", "replay_regenerated",
                     "canonical_store_written", "network_used"):
            assert safety[name] is False, name

    def test_every_required_tree_is_protected(self, seeded, sandbox, capsys):
        _out, markers = _run(capsys)
        required = {"compass", "compass_decisions", "formal_review", "compass_research",
                    "compass_replay", "compass_corpus", "knowledge/compass_dna", "reports"}
        assert required <= set(markers["SAFETY"]["protected_trees"])

    def test_data_root_is_not_written(self, seeded, sandbox, capsys):
        before = {p.relative_to(seeded).as_posix(): p.stat().st_size
                  for p in seeded.rglob("*") if p.is_file()}
        _run(capsys)
        after = {p.relative_to(seeded).as_posix(): p.stat().st_size
                 for p in seeded.rglob("*") if p.is_file()}
        assert after == before

    def test_unexpected_file_fails_validation(self, seeded, sandbox, capsys):
        """sandbox に想定外の file があれば非ゼロで落ちる。"""
        sandbox.mkdir(parents=True, exist_ok=True)
        (sandbox / "rogue.txt").write_text("x", encoding="utf-8")
        assert delivery_pilot.main([]) == 1
        out = capsys.readouterr().out
        safety = json.loads(out.split("::P43_SAFETY::")[1].splitlines()[0])
        assert safety["unexpected_delivery_files"] == ["rogue.txt"]
        assert safety["safety_check"] == "FAILED"
        assert json.loads(out.split("::P43_END::")[1].splitlines()[0])["result"] == \
            "ARTIFACT_FAILED"

    def test_protected_tree_change_fails_validation(self, seeded, sandbox, monkeypatch,
                                                    capsys):
        real = delivery_pilot._capture
        calls = {"n": 0}

        def fake(root, repo):
            calls["n"] += 1
            snapshot = real(root, repo)
            if calls["n"] > 1:
                snapshot["compass"] = dict(snapshot["compass"], files=99, digest="dead")
            return snapshot

        monkeypatch.setattr(delivery_pilot, "_capture", fake)
        assert delivery_pilot.main([]) == 1
        out = capsys.readouterr().out
        safety = json.loads(out.split("::P43_SAFETY::")[1].splitlines()[0])
        assert safety["protected_changed_trees"] == ["compass"]
        assert safety["all_protected_unchanged"] is False
        assert safety["safety_check"] == "FAILED"
        assert json.loads(out.split("::P43_END::")[1].splitlines()[0])["result"] == \
            "SAFETY_FAILED"

    def test_emitter_error_surfaces(self, seeded, sandbox, monkeypatch):
        """書き出し失敗を握りつぶさない。"""
        def boom(delivery, *, output_dir):
            raise OSError("disk full")

        monkeypatch.setattr(delivery_pilot, "emit_morning_delivery", boom)
        with pytest.raises(OSError):
            delivery_pilot.main([])


# ---------------------------------------------------------------- confidentiality

class TestConfidentiality:
    """36。"""

    def test_stdout_leaks_no_path_or_credential(self, seeded, sandbox, capsys,
                                                monkeypatch):
        monkeypatch.setenv("JQUANTS_API_KEY", "sk-SENTINEL-must-not-print")
        out, _markers = _run(capsys)
        assert str(seeded) not in out
        assert str(sandbox) not in out
        assert "sk-SENTINEL-must-not-print" not in out
        for name in ("C:\\", "/Users/", "/home/", "/tmp/", "runner", ".pdf",
                     "source_docs", "rashinban", "p43_delivery_output"):
            assert name not in out, name

    def test_stdout_carries_no_markdown_body_or_claim_text(self, seeded, sandbox,
                                                           capsys):
        out, _markers = _run(capsys)
        for name in ("モーニングブリーフ", "30秒版", "3分版", "詳細版",
                     "前営業日", "終値", "無効化条件", "根拠:", "反対材料:"):
            assert name not in out, name

    def test_stdout_carries_no_governance_record(self, seeded, sandbox, capsys):
        out, _markers = _run(capsys)
        for name in ("decision_id", "cdc_", "record_hash", "packet_id", "candidate_id",
                     "KEEP_REVIEWING", "NOT_PROMOTED", "replay_run_id"):
            assert name not in out, name

    def test_content_addressed_ids_are_allowed(self, seeded, sandbox, capsys):
        _out, markers = _run(capsys)
        assert markers["DELIVERY"]["delivery_id"].startswith("delivery_")
        assert markers["BRIEF"]["brief_id"].startswith("brief_")
        assert markers["SIGNAL"]["signal_id"].startswith("signal_")

    def test_artifact_rows_use_logical_names_only(self, seeded, sandbox, capsys):
        _out, markers = _run(capsys)
        for row in markers["ARTIFACTS"]["artifacts"]:
            assert "/" not in row["name"] and "\\" not in row["name"]
            assert row["name"] in artifact_names(markers["DELIVERY"]["session_date"])


# ---------------------------------------------------------------- boundaries

class TestBoundaries:
    """27–35。"""

    def test_no_governance_imports(self):
        assert not _tops(PILOT) & set(FORBIDDEN_GOVERNANCE)

    def test_no_legacy_or_notifier_imports(self):
        src = PILOT.read_text(encoding="utf-8")
        for legacy in ("src.report", "src.analysis", "src.collectors", "src.data",
                       "src.date", "notifiers", "scripts", "main"):
            assert f"import {legacy}" not in src, legacy
            assert f"from {legacy}" not in src, legacy
        assert not _tops(PILOT) & set(FORBIDDEN_LEGACY)
        assert "notifiers" not in _tops(PILOT)

    def test_no_phase5_imports(self):
        assert not _tops(PILOT) & set(FORBIDDEN_PHASE5)

    def test_no_article_tank_or_llm_imports(self):
        src = PILOT.read_text(encoding="utf-8")
        for name in ("article-intelligence-data-tank", "external_intelligence",
                     "llm", "anthropic", "openai"):
            assert name not in src, name

    def test_no_network_or_store_engine(self):
        assert not _tops(PILOT) & {"requests", "urllib", "socket", "http", "ssl",
                                   "sqlite3"}

    def test_imports_stay_inside_the_allowed_layers(self):
        allowed = {"__future__", "argparse", "hashlib", "json", "os", "datetime",
                   "pathlib", "typing", "compass", "context", "core", "delivery",
                   "delivery_emit", "market_signal", "model", "morning_brief",
                   "render_markdown"}
        assert _tops(PILOT) <= allowed, _tops(PILOT) - allowed

    def test_frozen_modules_do_not_reference_the_pilot(self):
        for name in ("model.py", "morning_brief.py", "render_markdown.py", "pilot.py",
                     "market_signal.py", "market_signal_pilot.py", "delivery.py",
                     "delivery_emit.py"):
            src = (REPORTS_DIR / name).read_text(encoding="utf-8")
            assert "delivery_pilot" not in src, name

    def test_p4_1_and_p4_2_pilots_are_untouched(self):
        for name in ("pilot.py", "market_signal_pilot.py"):
            src = (REPORTS_DIR / name).read_text(encoding="utf-8")
            assert "MorningDelivery" not in src, name
            assert "delivery" not in src, name

    def test_p4_1_p4_2_schema_versions_unchanged(self):
        from src.intelligence.reports.market_signal import MARKET_SIGNAL_SCHEMA_VERSION
        assert MORNING_BRIEF_SCHEMA_VERSION == "0.2.0"
        assert MARKET_SIGNAL_SCHEMA_VERSION == "0.1.0"

    def test_pilot_does_not_reimplement_packaging_or_rendering(self):
        """公開関数を再利用し、束ね方も組版も自前で書かない。"""
        src = PILOT.read_text(encoding="utf-8")
        assert "build_morning_delivery" in src and "emit_morning_delivery" in src
        assert "render_morning_brief_markdown" in src and "build_market_signal" in src
        for reimplemented in ("def build_morning_delivery", "def emit_morning_delivery",
                              "def render_morning_brief_markdown",
                              "def build_market_signal", "def build_morning_brief",
                              "def delivery_public_payload"):
            assert reimplemented not in src, reimplemented
