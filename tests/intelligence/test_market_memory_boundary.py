"""P13-A0 — Phase 13（Market Memory ／ Review State Memory）の runtime の面の登録の guard。

- `PHASE13_RUNTIME` は空 ・P13 の package は存在しない（今 ・`P13_BASE` ・P12.5 の設計の closeout の anchor のどれにも）。
- `P13_BASE` 以後に変わったのは登録した P13 の test ・文書と、凍結の P7 〜 P12 の test への宣言した登録の行だけ（完全一致で pin）。
- 凍結の P8 〜 P12 の runtime の blob ・P12.5 の設計の契約の blob は anchor と object 一致。
- registry の drift は digest で止める: `PHASE13_RUNTIME` ・認可 ・test ・文書の集合の正準 digest が本 file の定数と一致しなければ落ちる
  （runtime の追加は registry と本 file と gate の文書の 3 つを同時に ・監督の gate で変える）。
- importer の許可は無い: textual な import の禁止（P8 〜 P12 の package 名）は不変で、本 file はそれを緩めない。
- negative control: 未登録の path ・修正 ・近い名前 ・未宣言の登録の行 ・禁止の token は落ちる。
"""
from __future__ import annotations

import ast
import hashlib
import json
import re
import subprocess
from pathlib import Path

import pytest

from tests.intelligence.phase8_runtime_registry import P8_B5C, PHASE8_RUNTIME
from tests.intelligence.phase9_runtime_registry import P9_A5, PHASE9_RUNTIME
from tests.intelligence.phase10_runtime_registry import P10_A4, PHASE10_RUNTIME
from tests.intelligence.phase11_runtime_registry import P11_A5, PHASE11_RUNTIME
from tests.intelligence.phase12_runtime_registry import (P12_5_DESIGN_ANCHOR, P12_A6, P12_VALIDATED_TREE, PHASE12_5_FROZEN_CONTRACTS,
                                                         PHASE12_RUNTIME)
from tests.intelligence.phase13_runtime_registry import (ADDITION_STATUSES, FORBIDDEN_P13_TOKENS, P13_BASE, PHASE13_A1_RUNTIME, PHASE13_DOCS,
                                                         PHASE13_PACKAGE, PHASE13_RUNTIME, PHASE13_RUNTIME_AUTHORIZATION,
                                                         PHASE13_TESTS, PHASE13_TEST_REGISTRATION, is_phase13_addition,
                                                         only_phase13_registration, registration_diff)
from tests.intelligence.test_automation_boundary import FORBIDDEN_NAMES, FORBIDDEN_WORDS
from tests.intelligence.test_p43b2c_production_bundle import runtime_closure

REPO_ROOT = Path(__file__).resolve().parents[2]
PACKAGE_DIR = REPO_ROOT / PHASE13_PACKAGE
A0_DOC = "docs/databank/PHASE13_A0_RUNTIME_SURFACE_REGISTRATION.md"
A1_DOC = "docs/databank/PHASE13_A1_REVIEW_STATE_MODEL.md"
P13_A0 = "4d464c30e4598d2ad5a0cee5a34ac366414fbde3"   # P13-A0 の commit ＝ A1 の認可の anchor
#: P13 の runtime が import してよい stdlib（file ごと ・完全一致）。file ・OS ・時計 ・環境 ・process ・socket ・乱数は無い
SANCTIONED_P13_STDLIB = {"__future__", "dataclasses", "datetime", "enum", "hashlib", "json", "re", "typing"}
SANCTIONED_P13_MODULES = {"src/intelligence/market_memory/__init__.py": set(), "src/intelligence/market_memory/canonical.py": set(),
                          "src/intelligence/market_memory/review_state_sample.py": {".canonical"},
                          "src/intelligence/market_memory/review_state_change.py": {".canonical", ".review_state_sample"}}
#: registry の正準 digest（P13-A0 で確定。runtime ・認可 ・test ・文書 ・package ・base の集合。drift はここで止まる）
P13_REGISTRY_DIGEST = "e2975c2b05a58a49afc2910c1080146457bd91d8293f92c16e3575cb4f7dd6d8"
REGISTERED_FROZEN_TESTS = ("tests/intelligence/phase7_runtime_registry.py", "tests/intelligence/test_narrative_intelligence_boundary.py",
                           "tests/intelligence/test_screener_intelligence_boundary.py", "tests/intelligence/test_watchlist_thesis_boundary.py",
                           "tests/intelligence/test_personal_intelligence_boundary.py", "tests/intelligence/test_personal_ui_boundary.py",
                           "tests/intelligence/test_automation_boundary.py")
UNTOUCHED_REGISTRIES = ("tests/intelligence/phase8_runtime_registry.py", "tests/intelligence/phase9_runtime_registry.py",
                        "tests/intelligence/phase10_runtime_registry.py", "tests/intelligence/phase11_runtime_registry.py",
                        "tests/intelligence/phase12_runtime_registry.py")
FROZEN_SURFACE = ("knowledge", "config.yaml", ".github", "scripts", "docs/pages", "main.py", "requirements.txt",
                  "pyproject.toml", "cloudflare", "notifiers", "src/report")
#: P13 の文書 ・code に在ってはならない private の形（P12 の guard と同じ）
PRIVATE_PATTERNS = (r"[A-Za-z]:\\", r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}", r"\b\d{5}\b", r"p9wat_", r"p9ths_", r"p8iss_", r"p10prf_",
                    r"p10att_", r"human:", r"x-api-key", r"api\.jquants", r"S-1-5-\d", r"C:\\Users", r"JQUANTS_")


def _git(*args: str) -> str:
    return subprocess.run(["git", *args], cwd=REPO_ROOT, capture_output=True, text=True, check=True).stdout


def _changes(*args: str) -> set:
    return {tuple(line.split("\t")) for line in _git("diff", *args).splitlines()}


def _blobs(revision: str, paths) -> dict:
    out = _git("ls-tree", revision, "--", *paths)
    return {line.split("\t", 1)[1]: line.split()[2] for line in out.splitlines()}


def _registry_digest() -> str:
    payload = {"runtime": list(PHASE13_RUNTIME),
               "authorization": [[gate, anchor, list(paths), doc] for gate, anchor, paths, doc in PHASE13_RUNTIME_AUTHORIZATION],
               "tests": list(PHASE13_TESTS), "docs": list(PHASE13_DOCS), "package": PHASE13_PACKAGE, "base": P13_BASE}
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(("p13.registry.v1\0" + canonical).encode("utf-8")).hexdigest()


def _forbidden_tokens_in(text: str):
    return [token for token in FORBIDDEN_P13_TOKENS if token in text]


# ================================================ registry ・drift ・認可


def test_p13_a0_registry_is_exactly_the_reviewed_registration_and_runtime_is_empty() -> None:
    assert P13_BASE == "aded7ee8621e9abac18d313009444675ab771ae6"                                  # 固定の base（A0 の commit ではない）
    assert _git("merge-base", "--is-ancestor", P13_BASE, "HEAD") == ""
    assert PHASE13_RUNTIME == tuple(sorted(PHASE13_A1_RUNTIME)) and len(PHASE13_RUNTIME) == 4        # P13-A1: 純粋な model の 4 file
    assert PHASE13_RUNTIME_AUTHORIZATION == (("P13-A1", P13_A0, PHASE13_A1_RUNTIME, A1_DOC),)
    assert set(SANCTIONED_P13_MODULES) == set(PHASE13_RUNTIME)
    assert PHASE13_PACKAGE == "src/intelligence/market_memory" and ADDITION_STATUSES == ("A", "??")
    assert PHASE13_TESTS == ("tests/intelligence/phase13_runtime_registry.py", "tests/intelligence/test_market_memory_boundary.py",
                             "tests/intelligence/test_market_memory_model.py")
    assert PHASE13_DOCS == (A0_DOC, A1_DOC)
    assert _registry_digest() == P13_REGISTRY_DIGEST                                               # drift は digest で止まる
    for path in (*PHASE13_TESTS, *PHASE13_DOCS):
        assert (REPO_ROOT / path).is_file(), path
        assert not _git("ls-tree", P13_BASE, "--", path).strip(), path                              # 全て base の後に足した
    assert set(PHASE13_TEST_REGISTRATION) == set(REGISTERED_FROZEN_TESTS)


def test_p13_a0_every_future_runtime_path_must_be_bound_to_a_reviewed_gate_and_anchor() -> None:
    """runtime の追加の認可の規則（A0 では空集合に対して成り立つ）。tuple に path を足すだけでは通らない。"""
    authorized = {}
    for gate, anchor, paths, doc in PHASE13_RUNTIME_AUTHORIZATION:
        assert re.fullmatch(r"P13-A[0-9]+[a-z]?", gate), gate
        assert re.fullmatch(r"[0-9a-f]{40}", anchor) and _git("merge-base", "--is-ancestor", anchor, "HEAD") == "", gate
        assert doc in PHASE13_DOCS and (REPO_ROOT / doc).is_file(), gate
        text = (REPO_ROOT / doc).read_text(encoding="utf-8")
        for path in paths:
            assert path.startswith(PHASE13_PACKAGE + "/") and path.endswith(".py"), path
            assert not _git("ls-tree", anchor, "--", path).strip(), path                           # anchor にはまだ無い
            assert path in text, (gate, path)                                                       # gate の契約に path が在る
            assert path not in authorized, path                                                     # ちょうど 1 つの認可
            authorized[path] = gate
    assert set(PHASE13_RUNTIME) == set(authorized)                                                  # 認可の無い runtime は無い
    assert PHASE13_RUNTIME == tuple(sorted(PHASE13_RUNTIME))
    for path in PHASE13_RUNTIME:
        assert is_phase13_addition("A", path) and is_phase13_addition("??", path)
        assert not is_phase13_addition("M", path)                                                   # 修正は決して認めない
        assert not _git("ls-tree", P13_BASE, "--", path).strip()                                    # base には無い


# ================================================ src の面 ・凍結の test の狭い再開


def test_p13_a0_since_the_base_only_registered_phase13_files_and_declared_registration_changed() -> None:
    registered = {("A", p) for p in PHASE13_RUNTIME}
    assert _changes("--name-status", P13_BASE, "HEAD", "--", "src") <= registered                    # commit 済みの差は登録の追加だけ
    staged = _changes("--cached", "--name-status", P13_BASE, "--", "src")
    pending = {("A", line[3:]) for line in _git("status", "--porcelain", "--", "src").splitlines() if line[:2].strip() in ADDITION_STATUSES}
    assert staged <= registered and pending <= registered
    assert staged | pending == registered                                                           # 登録した file は全て在る（index か作業木）
    assert _git("diff", "--cached", "--name-status", P13_BASE, "--", *FROZEN_SURFACE) == ""
    assert _changes("--cached", "--name-status", P13_BASE, "--", "docs") <= {("A", p) for p in PHASE13_DOCS}
    assert _changes("--cached", "--name-status", P13_BASE, "--", "tests") <= {
        ("A", p) for p in PHASE13_TESTS} | {("M", p) for p in PHASE13_TEST_REGISTRATION}
    for path in PHASE13_TEST_REGISTRATION:                                                          # 凍結の P7 〜 P12 の test の狭い再開
        anchored = _git("show", f"{P13_BASE}:{path}")
        current = (REPO_ROOT / path).read_text(encoding="utf-8")
        assert only_phase13_registration(path, anchored, current), path
        assert not only_phase13_registration(path, anchored, current + "assert True\n"), path       # 未登録の追加
        assert not only_phase13_registration(path, anchored, anchored), path                         # 登録の欠落
        removed, added = PHASE13_TEST_REGISTRATION[path]
        assert added and all("is_outside_production" not in line and "no_other_code_imports" not in line for line in added), path
        assert all("SANCTIONED_P13" not in line for line in added), path                            # importer の許可は無い（P13-A2a）
    for registry in UNTOUCHED_REGISTRIES:
        assert _git("diff", "--name-status", P13_BASE, "--", registry) == "", registry               # 前の phase の registry は不変
    pending = [line for line in _git("status", "--porcelain", "--", "src").splitlines()
               if not is_phase13_addition(line[:2].strip(), line[3:])]
    assert pending == []


def test_p13_the_package_holds_exactly_the_registered_files_and_was_absent_at_the_historical_anchors() -> None:
    for revision in (P13_BASE, P13_A0, P12_5_DESIGN_ANCHOR, P12_A6, P12_VALIDATED_TREE):            # 歴史の事実: 登録の前に P13 は無かった
        assert not _git("ls-tree", revision, "--", PHASE13_PACKAGE).strip(), revision
    assert PACKAGE_DIR.is_dir()
    assert {p.name for p in PACKAGE_DIR.iterdir() if p.name != "__pycache__"} == {Path(p).name for p in PHASE13_RUNTIME}
    assert all(p.startswith(PHASE13_PACKAGE + "/") and p.endswith(".py") for p in PHASE13_RUNTIME)
    tracked_now = set(_git("ls-tree", "-r", "--name-only", "HEAD", "src").splitlines())
    tracked_base = set(_git("ls-tree", "-r", "--name-only", P13_BASE, "src").splitlines())
    assert tracked_base <= tracked_now and tracked_now - tracked_base <= set(PHASE13_RUNTIME)       # 以後は登録した P13 の追加だけ
    assert not any("market_memory" in module for module in runtime_closure())                      # 本番の閉包の外


# ================================================ 凍結の blob ・設計の契約


def test_p13_a0_frozen_runtime_and_design_contracts_are_object_identical_to_their_anchors() -> None:
    for anchor, runtime in ((P12_A6, PHASE12_RUNTIME), (P12_VALIDATED_TREE, PHASE12_RUNTIME), (P11_A5, PHASE11_RUNTIME),
                            (P10_A4, PHASE10_RUNTIME), (P9_A5, PHASE9_RUNTIME), (P8_B5C, PHASE8_RUNTIME)):
        anchored, head = _blobs(anchor, runtime), _blobs("HEAD", runtime)
        assert len(anchored) == len(runtime) and anchored == head, anchor
    anchored, head = _blobs(P12_5_DESIGN_ANCHOR, PHASE12_5_FROZEN_CONTRACTS), _blobs("HEAD", PHASE12_5_FROZEN_CONTRACTS)
    assert len(anchored) == len(PHASE12_5_FROZEN_CONTRACTS) and anchored == head
    assert _changes("--name-status", P12_A6, "HEAD", "--", "src") <= {("A", p) for p in PHASE13_RUNTIME}   # 登録した P13 の追加だけ


# ================================================ 文書 ・negative control


def test_p13_a0_the_registration_record_is_design_only_and_holds_no_private_values() -> None:
    text = (REPO_ROOT / A0_DOC).read_text(encoding="utf-8")
    for needle in ("P13-A0", "runtime surface registration", "PHASE13_RUNTIME", "空", P13_BASE, "P13_BASE", "PHASE13_TEST_REGISTRATION",
                   "only_phase13_registration", "PHASE13_RUNTIME_AUTHORIZATION", "digest", "importer の許可は無い", "P13-A2a",
                   "package は存在しない", "P12_5_DESIGN_ANCHOR", "修正は決して認めない", "negative control", "Review State Memory",
                   "P13-A1", "実装ではない", "B-track は HOLD"):
        assert needle in text, needle
    for banned in ("P13 は完了", "P13-A1 は完了", "Phase 13 は完了", "import を許可した", "署名済み", "最新の", "推奨する銘柄",
                   "D:\\", "0.0.0.0", "http://", "https://"):
        assert banned not in text, banned
    assert not re.search(r"\b(?:is|are|was|were|been)\s+(?:digitally\s+|cryptographically\s+)?signed\b", text, re.IGNORECASE)
    for pattern in PRIVATE_PATTERNS:
        assert not re.search(pattern, text), pattern


def _imports(path: Path):
    relative, absolute = {}, set()
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.ImportFrom) and node.level:
            relative.setdefault("." * node.level + (node.module or ""), set()).update(a.name for a in node.names)
        elif isinstance(node, ast.ImportFrom):
            absolute.add(node.module)
        elif isinstance(node, ast.Import):
            absolute.update(a.name for a in node.names)
    return relative, absolute


def test_p13_a1_runtime_imports_are_stdlib_only_and_never_reach_frozen_phases() -> None:
    for path in PHASE13_RUNTIME:
        relative, absolute = _imports(REPO_ROOT / path)
        assert absolute <= SANCTIONED_P13_STDLIB, (path, absolute - SANCTIONED_P13_STDLIB)
        assert set(relative) == SANCTIONED_P13_MODULES[path], (path, set(relative))
        assert not any(m.startswith("..") for m in relative), path                                  # 凍結の phase への import は無い
        text = (REPO_ROOT / path).read_text(encoding="utf-8")
        assert _forbidden_tokens_in(text) == [], path
        for pattern in PRIVATE_PATTERNS:
            assert not re.search(pattern, text), (path, pattern)
        assert "__main__" not in text and "import os" not in text and "import sys" not in text, path


def test_p13_a1_runtime_never_touches_files_env_clock_process_or_network_and_has_no_investment_vocabulary() -> None:
    for path in PHASE13_RUNTIME:
        tree = ast.parse((REPO_ROOT / path).read_text(encoding="utf-8"))
        identifiers = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Name):
                assert node.id not in FORBIDDEN_NAMES, (path, node.id)
                identifiers.add(node.id)
            elif isinstance(node, ast.Attribute):
                assert node.attr not in FORBIDDEN_NAMES, (path, node.attr)
                identifiers.add(node.attr)
            elif isinstance(node, ast.arg):
                identifiers.add(node.arg)
            elif isinstance(node, (ast.FunctionDef, ast.ClassDef)):
                identifiers.add(node.name)
            elif isinstance(node, ast.ExceptHandler):
                assert node.type is not None, (path, "bare except")
                names = {node.type.id} if isinstance(node.type, ast.Name) else {e.id for e in getattr(node.type, "elts", ()) if isinstance(e, ast.Name)}
                assert not names & {"Exception", "BaseException"}, (path, "broad except")
        words = set()
        for name in identifiers:
            words |= {w.lower() for w in re.findall(r"[A-Z]?[a-z]+|[A-Z]+(?![a-z])", name)}
        assert not words & FORBIDDEN_WORDS, (path, words & FORBIDDEN_WORDS)


def test_p13_a1_the_model_record_is_design_and_runtime_consistent_and_holds_no_private_values() -> None:
    text = (REPO_ROOT / A1_DOC).read_text(encoding="utf-8")
    for needle in ("P13-A1", "Review State Memory", "p13smp_", "p13chg_", "SampleCutoff", "SourceViewIdentity", "ReviewStateEntry",
                   "ReviewStateCounts", "ReviewStateSample", "ReviewStateChange", "SampleEvidence", "SampleOutcome", "StalenessLabel",
                   "PitState", "known_at", "reviewed_at", "捏造しない", "端点の差", "変化の不在", "MISSING", "INTEGRITY_FAILURE",
                   "空の標本", "telemetry", "SHORT_ID_COLLISION", "合成の入力", "凍結の package を import しない", "P13-A2a",
                   "importer の許可は無い", "store ・永続化 ・manifest は無い", P13_A0, *[Path(p).name for p in PHASE13_RUNTIME]):
        assert needle in text, needle
    for banned in ("P13 は完了", "Phase 13 は完了", "import を許可した", "署名済み", "最新の", "推奨する銘柄", "D:\\", "0.0.0.0", "http://", "https://"):
        assert banned not in text, banned
    assert not re.search(r"\b(?:is|are|was|were|been)\s+(?:digitally\s+|cryptographically\s+)?signed\b", text, re.IGNORECASE)
    for pattern in PRIVATE_PATTERNS:
        assert not re.search(pattern, text), pattern
    from src.intelligence.market_memory.review_state_change import CHANGE_ID_PREFIX, CHANGE_SCHEMA_VERSION
    from src.intelligence.market_memory.review_state_sample import SAMPLE_ID_PREFIX, SAMPLE_SCHEMA_VERSION
    assert SAMPLE_ID_PREFIX == "p13smp_" and CHANGE_ID_PREFIX == "p13chg_"
    assert SAMPLE_SCHEMA_VERSION in text and CHANGE_SCHEMA_VERSION in text


def test_p13_a0_negative_controls_reject_unregistered_paths_modifications_near_misses_and_drift() -> None:
    for status in ("A", "??", "M", "D", "R"):
        assert not is_phase13_addition(status, f"{PHASE13_PACKAGE}/review_state_store.py")         # 未登録
        assert not is_phase13_addition(status, f"{PHASE13_PACKAGE}/p10_read_adapter.py")           # A2a の adapter はまだ無い
        assert not is_phase13_addition(status, "src/intelligence/market_memory2/model.py")           # 近い名前
        assert not is_phase13_addition(status, "src/intelligence/market_memory_model.py")
        assert not is_phase13_addition(status, PHASE12_RUNTIME[0])                                   # 凍結の runtime
        assert not is_phase13_addition(status, PHASE11_RUNTIME[0])
        assert not is_phase13_addition(status, "tests/intelligence/phase13_runtime_registry.py")
    anchored = "a\nb\n"
    assert registration_diff(anchored, anchored) == ([], [])
    assert registration_diff(anchored, "a\nX\nb\n") == ([], ["X"])
    assert registration_diff(anchored, "a\n") == (["b"], [])
    assert not only_phase13_registration("tests/intelligence/not_registered.py", anchored, anchored + "c\n")
    assert only_phase13_registration("tests/intelligence/not_registered.py", anchored, anchored)
    path = REGISTERED_FROZEN_TESTS[0]
    anchored = _git("show", f"{P13_BASE}:{path}")
    current = (REPO_ROOT / path).read_text(encoding="utf-8")
    removed, added = PHASE13_TEST_REGISTRATION[path]
    assert not only_phase13_registration(path, anchored, current.replace(added[0], added[0] + " "))   # 登録の行の改変
    assert not only_phase13_registration(path, anchored, current.replace(added[-1] + "\n", "", 1))     # 登録の行の欠落
    assert not only_phase13_registration(path, anchored, current + "\nPHASE7_RUNTIME = ()\n")        # 未登録の追加
    tampered = {"runtime": ["src/intelligence/market_memory/model.py"], "authorization": [], "tests": list(PHASE13_TESTS),
                "docs": list(PHASE13_DOCS), "package": PHASE13_PACKAGE, "base": P13_BASE}
    canonical = json.dumps(tampered, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    assert hashlib.sha256(("p13.registry.v1\0" + canonical).encode("utf-8")).hexdigest() != P13_REGISTRY_DIGEST   # tuple だけ足すと落ちる
    for token in FORBIDDEN_P13_TOKENS:
        assert _forbidden_tokens_in(f"from ..{token} import x") == [token] or token in _forbidden_tokens_in(f"import {token}")
    assert _forbidden_tokens_in("from dataclasses import dataclass") == []
    for path in PHASE13_RUNTIME:                                                                     # A0 では空（将来の P13 の code の走査）
        text = (REPO_ROOT / path).read_text(encoding="utf-8")
        assert _forbidden_tokens_in(text) == [], path
    with pytest.raises(AssertionError):
        assert _forbidden_tokens_in("from ..personal_intelligence.review_view import read_personal_review") == []
