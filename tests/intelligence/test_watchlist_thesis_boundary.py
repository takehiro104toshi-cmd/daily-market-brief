"""P9-A1 〜 A4 — Phase 9（Watchlist / Thesis Intelligence）の境界の guard。

- registry の完全一致 ・P9_BASE 以後の面は登録した P9 の追加だけ ・凍結の P7 ／ P8 の test の差分は宣言した登録の行だけ。
- P8 runtime は凍結 anchor `P8_B5C` と byte 一致 ・P7 runtime は P9_BASE と不変。
- import の面は凍結の P8 の再構成の部品の完全一致だけ。P5 ・`src.analysis` ・`src.report` ・通知 ・公開 ・PWA ・LLM ・HTTP ・P8 の書き込み ・
  実行の経路を import しない。transport を作らない ・store の `open` は `read_only=True` だけ ・書き込み ・環境変数 ・時計なし。
- 順位 ・点数 ・推奨の語なし ・production runtime closure の外 ・他の package から import されない ・既存の公開の watchlist に触れない。
- A2: 意味の model は package の中 ・core の id ／ 時刻だけを import する ・authority の revision を作る code（自動の遷移）は無い ・
  識別子に順位 ／ 推奨 ／ 売買の語なし（自由文の普通の語は検閲しない）。
- A3: 書き込みは `store_io` だけ（`open("ab")` ・write ・flush ・fsync ・mkdir）。削除 ・上書き ・切り詰め ・改名なし。P8 の store は
  `read_only=True` でだけ開き、P9 の store は P9 の store の型でだけ開く。store は P8 ・`p8_handoff` を import しない。
- A4: authority の revision を作るのは実行器だけ（直列化は復元だけ）・`append_watch` ／ `append_thesis` を呼ぶのは実行器だけ ・
  凍結の P8 の importer は `p8_handoff` ・`p8_identity` の 2 file だけ（面は完全一致 ・read-only）・local の入口は標準出力にだけ書く。
"""
from __future__ import annotations

import ast
import re
import subprocess
from pathlib import Path

import pytest

from tests.intelligence.phase7_runtime_registry import PHASE7_RUNTIME
from tests.intelligence.phase8_runtime_registry import P8_B5C, PHASE8_RUNTIME
from tests.intelligence.phase9_runtime_registry import (P9_A5, P9_BASE, P9_HANDOFF, PHASE9_A1_RUNTIME, PHASE9_A2_RUNTIME,
                                                        PHASE9_A3_RUNTIME, PHASE9_A4_RUNTIME, PHASE9_DOCS,
                                                        SANCTIONED_P9_P8_IMPORTERS,
                                                        PHASE9_PACKAGE, PHASE9_RUNTIME, PHASE9_TEST_REGISTRATION,
                                                        PHASE9_TESTS, SANCTIONED_P9_A1_IMPORTS,
                                                        only_phase9_registration)
from tests.intelligence.phase10_runtime_registry import (P10_BASE, PHASE10_DOCS, PHASE10_RUNTIME, PHASE10_TESTS,
                                                         SANCTIONED_P10_P9_IMPORTERS)   # P10 の登録
from tests.intelligence.phase11_runtime_registry import PHASE11_DOCS, PHASE11_RUNTIME, PHASE11_TESTS   # P11 の登録
from tests.intelligence.phase12_runtime_registry import PHASE12_DOCS, PHASE12_RUNTIME, PHASE12_TESTS   # P12 の登録
from tests.intelligence.test_p43b2c_production_bundle import runtime_closure
from tests.intelligence.test_prediction_record import executable_source

REPO_ROOT = Path(__file__).resolve().parents[2]
PACKAGE_DIR = REPO_ROOT / PHASE9_PACKAGE
CONTRACT_DOC = "docs/databank/PHASE9_A1_P8_HANDOFF_CONTRACT.md"
A2_DOC = "docs/databank/PHASE9_A2_WATCHLIST_THESIS_SEMANTICS.md"
A3_DOC = "docs/databank/PHASE9_A3_AUTHORITY_STORES.md"
#: 唯一の書き込みの module と、そこで許す書き込みの操作
IO_MODULE = "store_io"
IO_ALLOWED = {"mkdir", "write", "flush", "fsync"}
#: P9 の store の型（`.open(` の受け手として許す）
P9_STORE_OPENERS = {"WatchlistStore", "ThesisStore", "AuthorityStores", "cls"}
#: P9 の module ごとの package 内 ／ core の import の module（完全一致）。P8 は `p8_handoff` だけが import する
SANCTIONED_INTERNAL_MODULES = {
    "__init__": set(), "private_root": set(),
    "revision_model": {"..core.ids", "..core.time"},
    "watch_model": {".revision_model"},
    "thesis_model": {".revision_model"},
    "proposal_model": {".p8_handoff", ".revision_model", ".thesis_model", ".watch_model"},
    "cross_rules": {".revision_model", ".thesis_model", ".watch_model"},
    "serialization": {".revision_model", ".thesis_model", ".watch_model"},
    "store_io": {".private_root", ".revision_model"},
    "watch_store": {".revision_model", ".serialization", ".store_io", ".watch_model"},
    "thesis_store": {".serialization", ".store_io", ".thesis_model"},
    "authority_stores": {".cross_rules", ".revision_model", ".store_io", ".thesis_model", ".thesis_store",
                         ".watch_model", ".watch_store"},
    "decision_model": {".revision_model", ".thesis_model", ".watch_model"},
    "executor": {".authority_stores", ".cross_rules", ".decision_model", ".p8_handoff", ".p8_identity",
                 ".private_root", ".proposal_model", ".revision_model", ".thesis_model", ".watch_model"},
    "projection": {".proposal_model", ".revision_model"},
    "local_cli": {".authority_stores", ".decision_model", ".executor", ".projection", ".revision_model",
                  ".store_io"},
}
#: P9 の中の P8 の入口（`p8_handoff` ・`p8_identity`）から module ごとに import してよい名前（完全一致）
P8_INGRESS_NAMES = {
    "proposal_model": {".p8_handoff": {"P8RunHandoff"}},
    "executor": {".p8_handoff": {"HandoffError", "reconstruct_bound"},
                 ".p8_identity": {"IssuerRecordError", "confirm_reviewed_issuer_record"}},
}
#: 唯一の authority の作成（実行器）と復元（直列化）
AUTHORITY_CONSTRUCTORS = {"executor", "serialization"}
SANCTIONED_CORE_NAMES = {"..core.ids": {"content_id"}, "..core.time": {"to_utc_iso"}}
#: authority の revision の型（runtime の code は作らない ・caller ＝ 人の入力の経路だけ）
AUTHORITY_TYPES = {"WatchEntryRevision", "ThesisRevision"}
#: P9_BASE 以後に変わってはいけない面（data は journal の副作用があるので除く）
FROZEN_SURFACE = ("knowledge", "config.yaml", ".github", "scripts", "docs/pages", "docs/v2", "main.py",
                  "requirements.txt", "pyproject.toml")
#: 外部の import として許す標準 library（module の完全一致）
STDLIB_IMPORTS = {"__future__", "dataclasses", "datetime", "enum", "hashlib", "json", "os", "os.path", "pathlib", "re",
                  "typing"}
#: module ごとに追加で許す標準 library（local の入口だけが引数 ・標準出力を使う）
EXTRA_STDLIB = {"local_cli": {"argparse", "sys"}}
FORBIDDEN_MODULE_PARTS = ("predictions", "analysis", "report", "notifier", "compass", "pages", "pwa", "llm", "anthropic",
                          "openai", "http", "urllib", "requests", "socket", "ssl", "subprocess", "jquants_local_transport",
                          "jquants_live", "jquants_pilot2_local", "theme", "narrative")   # 時計 ・乱数は標準 library の完全一致で除く
FORBIDDEN_NAMES = {"execute_screen", "main", "_store_integrity", "LocalHttpsTransport", "JQuantsLiveClient", "LedgerWriter",
                   "_create_ledger", "initialize", "append", "write_text", "write_bytes", "mkdir", "unlink", "rmtree",
                   "remove", "rename", "touch", "environ", "getenv", "urlopen", "getattr", "setattr", "eval", "exec",
                   "sleep", "now", "today", "utcnow", "open", "print", "input", "truncate", "write", "fsync", "flush",
                   "rmdir", "chmod", "symlink_to", "link_to", "system", "popen"}
#: A3 の store が P9 の store の型の作成 ／ 開くことに使ってよい名前（P8 の store の initialize は使わない ・p8_handoff の guard）
A3_STORE_NAMES = {"initialize", "open"}
#: 識別子（名前 ・属性 ・引数 ・定義 ・欄）の語（構造の guard。文字列の定数 ・自由文は対象外）。"watchlist" は namespace の名
FORBIDDEN_WORDS = {"rank", "ranking", "score", "scoring", "recommend", "recommendation", "buy", "sell", "portfolio",
                   "allocation", "target", "conviction", "priority", "weight", "rating", "preference", "holding",
                   "position", "trade", "instruction", "llm", "prompt", "morning", "cron", "schedule",
                   "latest", "promote", "overdue"}     # 自動の昇格の動詞（名詞の PROMOTION_CANDIDATE は L0 の提案の種類）


def _git(*args: str) -> str:
    return subprocess.run(["git", *args], cwd=REPO_ROOT, capture_output=True, text=True, check=True).stdout


def _changes(*args: str) -> set:
    return {tuple(line.split("\t")) for line in _git("diff", *args).splitlines()}


def _imports(path: Path):
    tree = ast.parse(path.read_text(encoding="utf-8"))
    relative, absolute = {}, set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.level:
            relative.setdefault("." * node.level + node.module, set()).update(a.name for a in node.names)
        elif isinstance(node, ast.ImportFrom):
            absolute.add(node.module)
        elif isinstance(node, ast.Import):
            absolute.update(a.name for a in node.names)
    return relative, absolute


# ================================================ registry ・面 ・凍結の P7 ／ P8 の test の登録


def test_p9_a1_the_registry_is_exact_and_disjoint_from_earlier_phases() -> None:
    assert subprocess.run(["git", "merge-base", "--is-ancestor", P9_BASE, "HEAD"], cwd=REPO_ROOT).returncode == 0
    assert PHASE9_RUNTIME == tuple(sorted(PHASE9_A1_RUNTIME + PHASE9_A2_RUNTIME + PHASE9_A3_RUNTIME
                                          + PHASE9_A4_RUNTIME))
    assert len(PHASE9_RUNTIME) == 18
    assert {p.name for p in PACKAGE_DIR.iterdir() if p.name != "__pycache__"} == {Path(p).name for p in PHASE9_RUNTIME}
    assert P9_HANDOFF in PHASE9_RUNTIME
    for path in (*PHASE9_RUNTIME, *PHASE9_TESTS, *PHASE9_DOCS):
        assert (REPO_ROOT / path).is_file(), path
    assert not set(PHASE9_RUNTIME) & (set(PHASE8_RUNTIME) | set(PHASE7_RUNTIME))
    assert not any(_git("ls-tree", P9_BASE, "--", path).strip() for path in (*PHASE9_RUNTIME, *PHASE9_TESTS,
                                                                             *PHASE9_DOCS))


def test_p9_a1_since_the_base_only_the_registered_phase9_files_and_declared_registration_changed() -> None:
    assert _changes("--cached", "--name-status", P9_BASE, "--", "src") == {("A", path) for path in PHASE9_RUNTIME
                                                                           + PHASE10_RUNTIME + PHASE11_RUNTIME
                                                                           + PHASE12_RUNTIME}
    assert _git("diff", "--cached", "--name-status", P9_BASE, "--", *FROZEN_SURFACE) == ""
    assert _changes("--cached", "--name-status", P9_BASE, "--", "docs") <= {("A", path) for path in PHASE9_DOCS
                                                                            + PHASE10_DOCS + PHASE11_DOCS + PHASE12_DOCS}
    assert _changes("--cached", "--name-status", P9_BASE, "--", "tests") <= {
        ("A", path) for path in PHASE9_TESTS + PHASE10_TESTS + PHASE11_TESTS + PHASE12_TESTS} | {
            ("M", path) for path in PHASE9_TEST_REGISTRATION}
    for path in PHASE9_TEST_REGISTRATION:                                             # 凍結の P7 ／ P8 の test の狭い再開
        anchored = _git("show", f"{P9_BASE}:{path}")
        current = _git("show", f"{P10_BASE}:{path}")             # P9 の登録は P9 の終わりまで（以後の差は P10 の guard が pin）
        assert only_phase9_registration(path, anchored, current), path
        assert not only_phase9_registration(path, anchored, current + "assert True\n")  # 未登録の追加
        assert not only_phase9_registration(path, anchored, anchored)                  # 登録の欠落
    assert set(PHASE9_TEST_REGISTRATION) == {"tests/intelligence/phase7_runtime_registry.py",
                                             "tests/intelligence/test_narrative_intelligence_boundary.py",
                                             "tests/intelligence/test_screener_intelligence_boundary.py"}
    assert "tests/intelligence/phase8_runtime_registry.py" not in PHASE9_TEST_REGISTRATION   # P8 の registry は不変


def test_p9_a1_phase8_runtime_is_byte_identical_to_the_freeze_anchor_and_phase7_is_untouched() -> None:
    assert P8_B5C == "0a32d86bd80d0f9a0b9f4cecbd7c961a93dfa15f" and len(PHASE8_RUNTIME) == 54
    for path in PHASE8_RUNTIME:
        assert _git("show", f"{P8_B5C}:{path}") == (REPO_ROOT / path).read_text(encoding="utf-8"), path
    assert _git("diff", "--name-status", P8_B5C, "--", *PHASE8_RUNTIME) == ""
    assert _git("diff", "--name-status", P9_BASE, "--", *PHASE7_RUNTIME, *PHASE8_RUNTIME) == ""
    assert _git("status", "--porcelain", "--", *PHASE7_RUNTIME, *PHASE8_RUNTIME) == ""


# ================================================ import の面 ・書き込み ・network ・語彙


@pytest.mark.parametrize("path", PHASE9_RUNTIME)
def test_p9_a1_imports_are_exactly_the_sanctioned_frozen_reconstruction_surfaces(path: str) -> None:
    relative, absolute = _imports(REPO_ROOT / path)
    allowed_stdlib = STDLIB_IMPORTS | EXTRA_STDLIB.get(Path(path).stem, set())
    assert absolute <= allowed_stdlib, absolute - allowed_stdlib
    stem = Path(path).stem
    if path in SANCTIONED_P9_P8_IMPORTERS:                                              # p8_handoff ・p8_identity だけ
        assert relative == SANCTIONED_P9_P8_IMPORTERS[path]
    else:
        assert set(relative) == SANCTIONED_INTERNAL_MODULES[stem], set(relative)
        assert not any("screener_intelligence" in m or "jquants" in m for m in relative)   # P8 は入口の 2 file だけ
        for module, names in relative.items():
            if module in SANCTIONED_CORE_NAMES:
                assert names == SANCTIONED_CORE_NAMES[module]
        for module in (".p8_handoff", ".p8_identity"):
            if module in relative:
                assert relative[module] == P8_INGRESS_NAMES[stem][module], (stem, module)
    if path.endswith("__init__.py"):
        assert relative == {} and absolute == set()                                     # docstring だけ
    for module in (*relative, *absolute):
        assert not any(part in module for part in FORBIDDEN_MODULE_PARTS), module
    assert not any(n.startswith("_") for names in relative.values() for n in names)     # private な P8 の名前なし


@pytest.mark.parametrize("path", PHASE9_RUNTIME)
def test_p9_a1_never_executes_writes_reads_credentials_or_opens_stores_for_writing(path: str) -> None:
    tree = ast.parse((REPO_ROOT / path).read_text(encoding="utf-8"))
    stem = Path(path).stem
    allowed = (IO_ALLOWED if stem == IO_MODULE else set()) | (A3_STORE_NAMES if path in PHASE9_A3_RUNTIME else set()) \
        | ({"write"} if stem == "local_cli" else set())                                  # 標準出力だけ（下で検査）
    for node in ast.walk(tree):
        assert not (isinstance(node, ast.Name) and node.id in FORBIDDEN_NAMES), node.id
        assert not (isinstance(node, ast.Attribute) and node.attr in FORBIDDEN_NAMES - {"open"} - allowed), node.attr
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "open":
            receiver = node.func.value
            if path in SANCTIONED_P9_P8_IMPORTERS:                                       # 凍結の P8 の store
                assert any(k.arg == "read_only" and isinstance(k.value, ast.Constant) and k.value.value is True
                           for k in node.keywords), "P8 store.open must be read_only=True"
            elif stem == IO_MODULE and not (isinstance(receiver, ast.Name) and receiver.id in P9_STORE_OPENERS):
                assert [a.value for a in node.args if isinstance(a, ast.Constant)] == ["ab"], "append-only open"
            else:
                assert isinstance(receiver, ast.Name) and receiver.id in P9_STORE_OPENERS, "only P9 store types"
        if stem != IO_MODULE and isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) \
                and node.func.attr == "write":
            assert ast.unparse(node.func.value) == "sys.stdout", "only stdout may be written outside store_io"
        assert not (isinstance(node, ast.ExceptHandler) and (node.type is None or (
            isinstance(node.type, ast.Name) and node.type.id in ("Exception", "BaseException")))), "broad except"
    relative, _ = _imports(REPO_ROOT / path)
    imported = {name for names in relative.values() for name in names}
    words = set()
    for node in ast.walk(tree):
        names = []
        if isinstance(node, ast.Name):
            names = [node.id]
        elif isinstance(node, ast.Attribute):
            names = [node.attr]
        elif isinstance(node, ast.arg):
            names = [node.arg]
        elif isinstance(node, ast.keyword) and node.arg:
            names = [node.arg]
        elif isinstance(node, (ast.FunctionDef, ast.ClassDef)):
            names = [node.name]
        for name in names:
            if name not in imported:                                                    # 凍結の P8 の名前は対象外
                words |= {w.lower() for w in re.findall(r"[A-Z]?[a-z]+|[A-Z]+(?![a-z])|[0-9]+", name)}
    assert not words & FORBIDDEN_WORDS, words & FORBIDDEN_WORDS
    lowered = {n.id.lower() for n in ast.walk(tree) if isinstance(n, ast.Name)} | {
        n.attr.lower() for n in ast.walk(tree) if isinstance(n, ast.Attribute)} | {
        n.arg.lower() for n in ast.walk(tree) if isinstance(n, ast.arg)}
    for compound in ("expected_return", "expectedreturn", "target_price", "position_size", "expected_value"):
        assert not any(compound in name for name in lowered), compound
    source = executable_source(REPO_ROOT / path)
    for token in ("JQUANTS_API_KEY", "x-api-key", "api.jquants.com", "://", "config.yaml", "docs/pages", "docs/v2"):
        assert token not in source, token


def test_p9_a1_is_outside_production_and_no_other_code_imports_it() -> None:
    assert not any("watchlist_thesis_intelligence" in module for module in runtime_closure())
    for path in [REPO_ROOT / "main.py", *sorted((REPO_ROOT / "src").rglob("*.py")),
                 *sorted((REPO_ROOT / "scripts").rglob("*.py"))]:
        if not path.exists() or PACKAGE_DIR in path.parents:
            continue
        if path.relative_to(REPO_ROOT).as_posix() in SANCTIONED_P10_P9_IMPORTERS:  # P10: read-only の importer だけ（面は完全一致）
            assert _imports(path)[0] == SANCTIONED_P10_P9_IMPORTERS[path.relative_to(REPO_ROOT).as_posix()]
            continue
        assert "watchlist_thesis_intelligence" not in path.read_text(encoding="utf-8", errors="replace"), path
    for legacy in ("src/analysis/models.py", "src/report/sections.py"):                 # 既存の公開の watchlist は不変
        assert _git("diff", "--name-status", P9_BASE, "--", legacy) == ""


def test_p9_a1_the_handoff_contract_records_the_required_clauses() -> None:
    text = (REPO_ROOT / CONTRACT_DOC).read_text(encoding="utf-8")
    for clause in ("P8 `ScreenResultSet` ≠ P9 Watchlist の項目 ≠ P9 Thesis ≠ 推奨 ≠ 売買の指示", "read-only",
                   "J-Quants の request は要らない", "`JQUANTS_API_KEY` は要らない", "COMPLETE の run だけ",
                   "P8_RUN_OPEN_INVOCATION", "P8_RUN_NOT_COMPLETE", "`run_id` と消費した `screen_result_id` の両方",
                   "P8_RESULT_DRIFT", "ONE_P8_RUN_PER_PRIVATE_ROOT_PER_D0", "Phase 9 の凍結ではない",
                   "watchlist_thesis_intelligence", "0a32d86bd80d0f9a0b9f4cecbd7c961a93dfa15f"):
        assert clause in text, clause


@pytest.mark.parametrize("path", PHASE9_A2_RUNTIME)
def test_p9_a2_no_runtime_code_creates_authority_revisions_or_transitions_automatically(path: str) -> None:
    tree = ast.parse((REPO_ROOT / path).read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            func = node.func
            name = func.id if isinstance(func, ast.Name) else func.attr if isinstance(func, ast.Attribute) else ""
            assert name not in AUTHORITY_TYPES | {"replace"}, name                       # authority は人の入力だけ
    for name in ("datetime.now", "date.today", "time.time", "utcnow"):
        assert name not in (REPO_ROOT / path).read_text(encoding="utf-8"), name


def test_p9_a2_the_semantic_contract_records_the_required_clauses() -> None:
    text = (REPO_ROOT / A2_DOC).read_text(encoding="utf-8")
    for clause in ("ACTIVE", "PAUSED", "REMOVED", "CHALLENGED", "INVALIDATED", "RETIRED", "p9wat", "p9wrv", "p9ths",
                   "p9trv", "p9prp", "p9inv", "P8_SCREEN_RESULT", "HUMAN_NOTE", "MANUAL", "P8_PROPOSAL", "human:",
                   "reviewed_at <= T", "A3", "Phase 9 の凍結ではない"):
        assert clause in text, clause


def test_p9_a3_only_store_io_writes_and_the_stores_never_touch_phase8() -> None:
    for path in PHASE9_RUNTIME:
        stem = Path(path).stem
        relative, absolute = _imports(REPO_ROOT / path)
        if path in PHASE9_A3_RUNTIME:
            assert ".p8_handoff" not in relative and not any("screener" in m or "jquants" in m for m in relative)
        if stem != IO_MODULE:
            assert "os" not in absolute and "hashlib" not in absolute, path               # fsync ・digest は store_io だけ
            source = (REPO_ROOT / path).read_text(encoding="utf-8")
            assert ".fsync(" not in source and '"ab"' not in source, path
            assert source.count(".write(") == source.count("sys.stdout.write("), path         # 標準出力だけ


def test_p9_a3_the_store_contract_records_the_required_clauses() -> None:
    text = (REPO_ROOT / A3_DOC).read_text(encoding="utf-8")
    for clause in ("watchlist_authority.jsonl", "thesis_authority.jsonl", "APPENDED", "REUSED", "fsync",
                   "CONCURRENT_MODIFICATION", "STORE_CORRUPTION", "APPEND_REJECTED", "CHAIN_HEAD_MISMATCH",
                   "check_world", "reviewed_at <= T", "A4", "A1 の発行体の存在", "Phase 9 の凍結ではない"):
        assert clause in text, clause


def _calls(tree: ast.AST):
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            func = node.func
            yield node, func.id if isinstance(func, ast.Name) else func.attr if isinstance(func, ast.Attribute) else ""


@pytest.mark.parametrize("path", PHASE9_RUNTIME)
def test_p9_a4_only_the_executor_creates_authority_and_only_it_appends(path: str) -> None:
    stem = Path(path).stem
    tree = ast.parse((REPO_ROOT / path).read_text(encoding="utf-8"))
    for node, name in _calls(tree):
        passed = {a.id for a in node.args if isinstance(a, ast.Name)}
        if name in AUTHORITY_TYPES or (name in ("_build", "replace") and passed & AUTHORITY_TYPES):
            assert stem in AUTHORITY_CONSTRUCTORS, (stem, name)                           # 作成は実行器 ・復元は直列化
        if name in ("append_watch", "append_thesis"):
            assert stem == "executor", stem                                               # 唯一の追記の呼び手
        if name == "_append_line":
            assert stem == "authority_stores", stem
        if name in ("watch_from_dict", "thesis_from_dict"):
            assert stem in ("watch_store", "thesis_store", "serialization"), stem
        if name in ("reconstruct_bound", "confirm_reviewed_issuer_record"):
            assert stem in ("executor", "p8_handoff", "p8_identity"), stem
    if stem in ("proposal_model", "projection", "local_cli", "decision_model", "cross_rules"):
        assert not any(name in ("append_watch", "append_thesis", "_append_line") for _, name in _calls(tree))


def test_p9_a4_the_executor_contract_records_the_required_clauses() -> None:
    text = (REPO_ROOT / "docs/databank/PHASE9_A4_HUMAN_DECISION_EXECUTOR.md").read_text(encoding="utf-8")
    for clause in ("WATCH_CREATE_FROM_PROPOSAL", "WATCH_CREATE_MANUAL", "THESIS_TRANSITION", "reconstruct_bound",
                   "PROPOSAL_DIGEST_MISMATCH", "P8_RESULT_DRIFT", "PROPOSAL_ISSUER_ABSENT",
                   "NOT_A_LISTING_OR_COVERAGE_CLAIM", "STALE_AUTHORITY_HEAD", "REUSED", "expected_head_revision_id",
                   "AuthorityStores", "as_of_date", "dry-run", "A5", "Phase 9 の凍結ではない"):
        assert clause in text, clause


# ================================================ P9 凍結の記録（P9-FREEZE-RECORD: 文書 ・registry ・guard だけ。runtime の意味は変えない）

FREEZE_DOC = "docs/databank/PHASE9_FINAL_FREEZE.md"
#: 凍結の記録に置かない private な値の形（実の id ・code ・瞬間 ・root ・著者 ・A5 の理由の文）
PRIVATE_PATTERNS = (r"p8(run|srs|iss|sec|pol|uni)_[0-9a-f]{6,}", r"p9(wat|wrv|ths|trv|prp|inv)_[0-9a-f]{6,}",
                    r"\b[0-9]{4}0\b", r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}", r"[A-Za-z]:\\", r"_private\b",
                    r"human:[A-Za-z0-9]", r"validation only: exercises")


def test_p9_freeze_the_18_registered_runtime_files_are_byte_identical_to_the_a5_freeze_anchor() -> None:
    assert P9_A5 == "4c1970174f678245b569fdbb812a8a6ced52410b"
    assert subprocess.run(["git", "merge-base", "--is-ancestor", P9_A5, "HEAD"], cwd=REPO_ROOT).returncode == 0
    assert len(PHASE9_RUNTIME) == 18 and len(set(PHASE9_RUNTIME)) == 18
    anchored = {path for path in _git("ls-tree", "-r", "--name-only", P9_A5, "--", PHASE9_PACKAGE).splitlines()
                if path.endswith(".py")}
    assert anchored == set(PHASE9_RUNTIME)                                          # anchor の package ＝ 登録の 18
    for path in PHASE9_RUNTIME:
        assert _git("ls-tree", P9_A5, "--", path).strip(), path                     # anchor に在る
        assert _git("show", f"{P9_A5}:{path}") == (REPO_ROOT / path).read_text(encoding="utf-8"), path
    assert _git("diff", "--name-status", P9_A5, "--", *PHASE9_RUNTIME) == ""
    assert _git("status", "--porcelain", "--", *PHASE9_RUNTIME) == ""
    assert not _git("ls-tree", P9_A5, "--", FREEZE_DOC).strip()                    # 記録は anchor の後（新しい anchor ではない）
    text = (REPO_ROOT / FREEZE_DOC).read_text(encoding="utf-8")
    assert "COMPLETE / CLOSED / FROZEN" in text and P9_A5 in text
    for pattern in PRIVATE_PATTERNS:
        assert not re.search(pattern, text), pattern                               # private な値を記録しない
