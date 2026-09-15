"""Phase 4 P4-3a Morning Delivery emitter のテスト。

`output/v2/` へ並走 artifact を書き出す層だけを見る:

    承認済み 4 file しか書かない / Markdown はバイト単位で凍結出力と一致 /
    atomic 置換（失敗しても既存の正常 artifact を壊さない）/ 冪等 /
    canonical store（JSONL / SQLite / index）を作らない。

pytest は隔離 tmp ディレクトリへ書き、リポジトリの `output/` には触れない。
"""
from __future__ import annotations

import ast
import json
from pathlib import Path

import pytest

from src.intelligence.reports.delivery import (
    build_morning_delivery,
    delivery_public_json,
)
from src.intelligence.reports.delivery_emit import (
    DEFAULT_OUTPUT_DIR,
    DELIVERY_DIRNAME,
    LATEST_JSON,
    LATEST_MARKDOWN,
    artifact_names,
    dated_json_name,
    dated_markdown_name,
    delivery_artifacts,
    emit_morning_delivery,
)
from src.intelligence.reports.market_signal import build_market_signal
from src.intelligence.reports.render_markdown import render_morning_brief_markdown
from tests.intelligence.test_market_signal import _brief as make_brief

EMIT_SRC = Path("src/intelligence/reports/delivery_emit.py")
SESSION = "2026-09-15"


# ---------------------------------------------------------------- helpers

def _delivery(**kwargs):
    brief = make_brief(**kwargs)
    signal = build_market_signal(brief)
    markdown = render_morning_brief_markdown(brief)
    return build_morning_delivery(brief, signal, markdown), markdown


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
def out_dir(tmp_path) -> Path:
    return tmp_path / "output" / DELIVERY_DIRNAME


# ---------------------------------------------------------------- targets

class TestApprovedTargets:
    """31–34, 40, 41。"""

    def test_writes_exactly_the_four_approved_targets(self, out_dir):
        delivery, _md = _delivery()
        written = emit_morning_delivery(delivery, output_dir=out_dir)
        assert {p.name for p in written} == set(artifact_names(SESSION))
        assert {p.name for p in out_dir.iterdir()} == set(artifact_names(SESSION))
        assert len(written) == 4

    def test_approved_names_are_the_documented_four(self):
        assert artifact_names(SESSION) == (
            "2026-09-15_morning_brief.md", "2026-09-15_morning_brief.json",
            "latest_morning_brief.md", "latest_morning_brief.json")
        assert LATEST_MARKDOWN == "latest_morning_brief.md"
        assert LATEST_JSON == "latest_morning_brief.json"
        assert dated_markdown_name(SESSION) == "2026-09-15_morning_brief.md"
        assert dated_json_name(SESSION) == "2026-09-15_morning_brief.json"

    def test_dated_markdown_is_byte_identical_to_frozen_markdown(self, out_dir):
        delivery, markdown = _delivery()
        emit_morning_delivery(delivery, output_dir=out_dir)
        written = (out_dir / dated_markdown_name(SESSION)).read_bytes()
        assert written == markdown.encode("utf-8")

    def test_latest_markdown_is_byte_identical_to_frozen_markdown(self, out_dir):
        delivery, markdown = _delivery()
        emit_morning_delivery(delivery, output_dir=out_dir)
        assert (out_dir / LATEST_MARKDOWN).read_bytes() == markdown.encode("utf-8")

    def test_dated_and_latest_json_are_byte_identical(self, out_dir):
        delivery, _md = _delivery()
        emit_morning_delivery(delivery, output_dir=out_dir)
        dated = (out_dir / dated_json_name(SESSION)).read_bytes()
        latest = (out_dir / LATEST_JSON).read_bytes()
        assert dated == latest == delivery_public_json(delivery).encode("utf-8")

    def test_json_artifact_parses_and_matches_the_public_contract(self, out_dir):
        delivery, _md = _delivery()
        emit_morning_delivery(delivery, output_dir=out_dir)
        payload = json.loads((out_dir / LATEST_JSON).read_text(encoding="utf-8"))
        assert payload["delivery_id"] == delivery.delivery_id
        assert payload["markdown_sha256"] == delivery.markdown_sha256
        assert payload["markdown_bytes"] == len(
            (out_dir / LATEST_MARKDOWN).read_bytes())

    def test_default_output_dir_is_output_v2(self):
        assert DEFAULT_OUTPUT_DIR == Path("output") / "v2"
        assert DELIVERY_DIRNAME == "v2"

    def test_nothing_is_written_outside_the_approved_root(self, tmp_path):
        out = tmp_path / "output" / DELIVERY_DIRNAME
        delivery, _md = _delivery()
        emit_morning_delivery(delivery, output_dir=out)
        produced = {p.relative_to(tmp_path).as_posix()
                    for p in tmp_path.rglob("*") if p.is_file()}
        assert produced == {f"output/{DELIVERY_DIRNAME}/{n}"
                            for n in artifact_names(SESSION)}

    def test_no_store_or_index_is_created(self, out_dir):
        delivery, _md = _delivery()
        emit_morning_delivery(delivery, output_dir=out_dir)
        for path in out_dir.rglob("*"):
            assert path.suffix not in (".sqlite3", ".jsonl", ".db"), path
        assert not (out_dir / "index").exists()
        assert sorted(p.suffix for p in out_dir.iterdir()) == [".json", ".json",
                                                               ".md", ".md"]

    def test_unapproved_artifact_name_fails_closed(self, out_dir, monkeypatch):
        delivery, _md = _delivery()
        monkeypatch.setattr(
            "src.intelligence.reports.delivery_emit.delivery_artifacts",
            lambda d: {"rogue.txt": "x"})
        with pytest.raises(ValueError):
            emit_morning_delivery(delivery, output_dir=out_dir)
        assert not out_dir.exists() or not list(out_dir.iterdir())


# ---------------------------------------------------------------- atomicity

class TestAtomicity:
    """37–39。"""

    def test_existing_target_is_replaced_atomically(self, out_dir):
        delivery, markdown = _delivery()
        emit_morning_delivery(delivery, output_dir=out_dir)
        stale = out_dir / LATEST_MARKDOWN
        stale.write_text("STALE", encoding="utf-8")
        emit_morning_delivery(delivery, output_dir=out_dir)
        assert stale.read_bytes() == markdown.encode("utf-8")

    def test_no_temp_residue_after_success(self, out_dir):
        delivery, _md = _delivery()
        emit_morning_delivery(delivery, output_dir=out_dir)
        assert not [p for p in out_dir.iterdir() if p.name.startswith(".")]
        assert not [p for p in out_dir.iterdir() if p.suffix == ".part"]

    def test_serialization_failure_writes_nothing(self, out_dir, monkeypatch):
        """全バイトを先に用意するので、直列化段階の失敗は 1 file も差し替えない。"""
        delivery, markdown = _delivery()
        emit_morning_delivery(delivery, output_dir=out_dir)
        before = {p.name: p.read_bytes() for p in out_dir.iterdir()}

        def boom(_delivery):
            raise RuntimeError("serialization failed")

        monkeypatch.setattr(
            "src.intelligence.reports.delivery_emit.delivery_artifacts", boom)
        with pytest.raises(RuntimeError):
            emit_morning_delivery(delivery, output_dir=out_dir)
        assert {p.name: p.read_bytes() for p in out_dir.iterdir()} == before

    def test_failed_single_write_leaves_the_previous_artifact_intact(self, out_dir,
                                                                     monkeypatch):
        """置換の途中で落ちても、既存 file は壊れた内容にならない。"""
        delivery, markdown = _delivery()
        emit_morning_delivery(delivery, output_dir=out_dir)
        before = {p.name: p.read_bytes() for p in out_dir.iterdir()}

        real_replace = __import__("os").replace
        calls = {"n": 0}

        def flaky(src, dst):
            calls["n"] += 1
            if calls["n"] == 2:
                raise OSError("replace failed")
            return real_replace(src, dst)

        monkeypatch.setattr("src.intelligence.reports.delivery_emit.os.replace", flaky)
        with pytest.raises(OSError):
            emit_morning_delivery(delivery, output_dir=out_dir)
        after = {p.name: p.read_bytes() for p in out_dir.iterdir()
                 if not p.name.startswith(".")}
        # どの file も「古い正しい内容」か「新しい正しい内容」のいずれか（壊れていない）
        for name, blob in after.items():
            assert blob == before[name]
        assert not [p for p in out_dir.iterdir() if p.suffix == ".part"]

    def test_multi_file_atomicity_boundary_is_documented(self):
        """4 file 一括の原子性は保証しないことを docstring が明言している。"""
        src = EMIT_SRC.read_text(encoding="utf-8")
        assert "os.replace" in src
        assert "4 file 一括の原子性は保証しない" in src


# ---------------------------------------------------------------- idempotence

class TestIdempotence:
    """35, 36。"""

    def test_repeated_emission_is_byte_identical(self, out_dir):
        delivery, _md = _delivery()
        emit_morning_delivery(delivery, output_dir=out_dir)
        first = {p.name: p.read_bytes() for p in out_dir.iterdir()}
        emit_morning_delivery(delivery, output_dir=out_dir)
        assert {p.name: p.read_bytes() for p in out_dir.iterdir()} == first

    def test_artifacts_carry_no_time_or_host_dependent_content(self, out_dir):
        delivery, _md = _delivery()
        emit_morning_delivery(delivery, output_dir=out_dir)
        blob = (out_dir / LATEST_JSON).read_text(encoding="utf-8")
        for name in ("generated_at", "timestamp", "hostname", "pid", "runner",
                     str(out_dir)):
            assert name not in blob, name

    def test_artifact_bytes_are_a_pure_function_of_the_delivery(self, out_dir, tmp_path):
        delivery, _md = _delivery()
        other = tmp_path / "elsewhere" / DELIVERY_DIRNAME
        emit_morning_delivery(delivery, output_dir=out_dir)
        emit_morning_delivery(delivery, output_dir=other)
        for name in artifact_names(SESSION):
            assert (out_dir / name).read_bytes() == (other / name).read_bytes()

    def test_artifacts_helper_prepares_all_bytes_upfront(self):
        delivery, markdown = _delivery()
        artifacts = delivery_artifacts(delivery)
        assert set(artifacts) == set(artifact_names(SESSION))
        assert artifacts[LATEST_MARKDOWN] == markdown
        assert artifacts[dated_markdown_name(SESSION)] == markdown


# ---------------------------------------------------------------- degraded

class TestDegradedStates:
    def test_unavailable_signal_still_emits_all_four(self, out_dir):
        delivery, markdown = _delivery(direction="MIXED")
        emit_morning_delivery(delivery, output_dir=out_dir)
        assert {p.name for p in out_dir.iterdir()} == set(artifact_names(SESSION))
        assert (out_dir / LATEST_MARKDOWN).read_bytes() == markdown.encode("utf-8")
        payload = json.loads((out_dir / LATEST_JSON).read_text(encoding="utf-8"))
        assert payload["signal"] == {"available": False, "label": "",
                                     "unavailable_reason": "direction_mixed"}


# ---------------------------------------------------------------- boundaries

class TestBoundaries:
    """42–52（emitter 側）。"""

    def test_no_legacy_or_notifier_imports(self):
        forbidden = {"notifiers", "main", "scripts", "report", "analysis", "collectors"}
        src = EMIT_SRC.read_text(encoding="utf-8")
        for legacy in ("src.report", "src.analysis", "src.collectors", "src.data",
                       "src.date", "notifiers", "scripts", "main"):
            assert f"import {legacy}" not in src, legacy
            assert f"from {legacy}" not in src, legacy
        assert not _tops(EMIT_SRC) & forbidden

    def test_no_governance_imports(self):
        forbidden = {"decision", "formal_review", "review", "shadow_review",
                     "corpus", "corpus_research", "replay", "evaluation"}
        assert not _tops(EMIT_SRC) & forbidden

    def test_no_phase5_imports(self):
        forbidden = {"predictions", "themes", "thesis", "screening", "personalization"}
        assert not _tops(EMIT_SRC) & forbidden

    def test_no_article_tank_or_llm_imports(self):
        src = EMIT_SRC.read_text(encoding="utf-8")
        for name in ("article-intelligence-data-tank", "external_intelligence",
                     "llm", "anthropic", "openai"):
            assert name not in src, name

    def test_no_network(self):
        assert not _tops(EMIT_SRC) & {"requests", "urllib", "socket", "http", "ssl"}

    def test_no_store_engine_imports(self):
        assert not _tops(EMIT_SRC) & {"sqlite3"}

    def test_no_time_or_random_dependence(self):
        assert not _tops(EMIT_SRC) & {"datetime", "time", "random", "uuid", "secrets"}

    def test_emitter_imports_stay_inside_the_allowed_layers(self):
        allowed = {"__future__", "os", "tempfile", "pathlib", "typing", "delivery"}
        assert _tops(EMIT_SRC) <= allowed, _tops(EMIT_SRC) - allowed

    def test_frozen_modules_do_not_reference_the_emitter(self):
        for name in ("model.py", "morning_brief.py", "render_markdown.py", "pilot.py",
                     "market_signal.py", "market_signal_pilot.py"):
            src = (Path("src/intelligence/reports") / name).read_text(encoding="utf-8")
            assert "delivery_emit" not in src, name

    def test_repository_output_tree_is_untouched_by_tests(self):
        """テストはリポジトリの output/ へ書かない（隔離 tmp のみ）。"""
        assert not (Path("output") / DELIVERY_DIRNAME).exists()
