"""P10-A1 〜 A4 — Phase 10（Personal Intelligence）の境界の guard。

- registry の完全一致 ・P10_BASE 以後の面は登録した P10 の追加だけ ・凍結の P7 ／ P8 ／ P9 の test の差分は宣言した登録の行だけ。
- P9 runtime は凍結 anchor `P9_A5` と ・P8 runtime は `P8_B5C` と byte 一致 ・P7 runtime は P10_BASE と不変。
- `p9_view` の import の面は凍結 P9 の read-only の部品の完全一致だけ（`AuthorityStores` ・実行器 ・local の入口 ・P8 ・J-Quants ・
  network ・LLM ・P5 ・公開の出力は無い）。書き込み ・作成 ・環境変数 ・時計なし。store は P9 の read-only の型の `open` だけ。
- production runtime closure の外 ・他の package から import されない ・識別子に順位 ／ 推奨 ／ 売買の語なし。
- A2 の純な model は package の中と `..core` の id ・時刻の補助だけを import する（Phase 9 ・P8 ・`p9_view` ・file の入出力なし）。
- A3 の store: 物理的な書き込み（open ・write ・flush ・fsync ・mkdir）は `store_io` だけ（追記 ・排他の作成の mode だけ）。私的な
  書き込み ／ 初期化の関数を import するのは coordinator だけ。個々の store に追記 ・初期化の API は無い。
- A4: 新しい authority の revision を作るのは実行器だけ（直列化は永続の記録の復元だけ）・追記の経路を呼ぶのも実行器だけ ・
  初期化を呼ぶのは管理の初期化だけ ・`p9_view` を使うのは実行器と見直しの view だけ ・CLI の書き込みは標準出力の stream だけ。
"""
from __future__ import annotations

import ast
import re
import subprocess
from pathlib import Path

from tests.intelligence.phase7_runtime_registry import PHASE7_RUNTIME
from tests.intelligence.phase8_runtime_registry import P8_B5C, PHASE8_RUNTIME
from tests.intelligence.phase9_runtime_registry import P9_A5, PHASE9_RUNTIME
from tests.intelligence.phase10_runtime_registry import (P10_A4, P10_ADMIN_INIT, P10_AUTHORITY_STORES, P10_BASE,
                                                         P10_EXECUTOR, P10_VALIDATED_TREE,
                                                         P10_LOCAL_CLI, P10_P9_VIEW, P10_REVIEW_VIEW, P10_STORE_IO,
                                                         PHASE10_A1_RUNTIME, PHASE10_A2_RUNTIME, PHASE10_A3_RUNTIME,
                                                         PHASE10_A4_RUNTIME, SANCTIONED_P10_A4_MODULES,
                                                         SANCTIONED_P10_P9_VIEW_IMPORTERS,
                                                         PHASE10_DOCS, PHASE10_PACKAGE, PHASE10_RUNTIME,
                                                         PHASE10_TEST_REGISTRATION, PHASE10_TESTS,
                                                         SANCTIONED_P10_A2_MODULES, SANCTIONED_P10_A3_MODULES,
                                                         SANCTIONED_P10_CORE_IMPORTS,
                                                         SANCTIONED_P10_PRIVATE_WRITER_IMPORTS,
                                                         SANCTIONED_P10_P9_IMPORTERS, SANCTIONED_P10_P9_IMPORTS,
                                                         only_phase10_registration)
from tests.intelligence.phase11_runtime_registry import (P11_BASE, PHASE11_DOCS, PHASE11_RUNTIME, PHASE11_TESTS,
                                                         SANCTIONED_P11_P10_IMPORTERS)   # P11 の登録
from tests.intelligence.phase12_runtime_registry import PHASE12_DOCS, PHASE12_RUNTIME, PHASE12_TESTS   # P12 の登録
from tests.intelligence.phase13_runtime_registry import PHASE13_DOCS, PHASE13_RUNTIME, PHASE13_TESTS   # P13-A0 の登録（空の runtime）
from tests.intelligence.test_p43b2c_production_bundle import runtime_closure

REPO_ROOT = Path(__file__).resolve().parents[2]
PACKAGE_DIR = REPO_ROOT / PHASE10_PACKAGE
CONTRACT_DOC = "docs/databank/PHASE10_A1_P9_READONLY_ADAPTER.md"
A2_CONTRACT_DOC = "docs/databank/PHASE10_A2_PROFILE_ATTENTION_SEMANTICS.md"
A3_CONTRACT_DOC = "docs/databank/PHASE10_A3_PROFILE_ATTENTION_STORES.md"
A4_CONTRACT_DOC = "docs/databank/PHASE10_A4_EXECUTOR_REVIEW_VIEW.md"
FREEZE_DOC = "docs/databank/PHASE10_FINAL_FREEZE.md"
#: 凍結の記録に書いてはならない private な値の形（P9 ／ P10 の id の接頭辞 ・発行体 ・5 桁の code ・著者 ・瞬間 ・Windows の path ・
#: A5 の validation の profile の文）。集計の件数は許す
FREEZE_DOC_PRIVATE_PATTERNS = (r"p9wat_", r"p9ths_", r"p9wrv_", r"p9trv_", r"p8iss_", r"p10prf_", r"p10prv_", r"p10att_",
                               r"p10arv_", r"\b[0-9]{5}\b", r"human:", r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}",
                               r"[A-Za-z]:\\", r"p9_a5_private", r"p10_a5_private", r"p10_a5_work",
                               r"A5 validation-only profile", r"No personal or financial content")
FROZEN_SURFACE = ("knowledge", "config.yaml", ".github", "scripts", "docs/pages", "docs/v2", "main.py",
                  "requirements.txt", "pyproject.toml")
STDLIB_IMPORTS = {"__future__", "dataclasses", "datetime", "enum", "json", "re", "typing"}
#: file ごとの追加の stdlib（store_io: sha256 ・fsync ・path ／ 管理の初期化: path ／ CLI: 引数 ・標準出力 ・decision の file）
EXTRA_STDLIB = {P10_STORE_IO: {"hashlib", "os", "pathlib"}, P10_ADMIN_INIT: {"pathlib"},
                P10_LOCAL_CLI: {"argparse", "pathlib", "sys"}}
FORBIDDEN_MODULE_PARTS = ("screener_intelligence", "jquants", "predictions", "analysis", "report", "notifier",
                          "compass", "pages", "pwa", "llm", "anthropic", "openai", "http", "urllib", "requests",
                          "socket", "ssl", "subprocess", "authority_stores", "executor", "local_cli", "decision_model",
                          "p8_handoff", "p8_identity", "theme", "narrative")
FORBIDDEN_NAMES = {"AuthorityStores", "initialize", "_append_line", "append_watch", "append_thesis", "append",
                   "write", "write_text", "write_bytes", "mkdir", "unlink", "rmtree", "remove", "rename", "touch",
                   "truncate", "environ", "getenv", "now", "today", "utcnow", "print", "input", "sleep", "getattr",
                   "setattr", "eval", "exec", "fsync", "flush", "system", "popen"}
FORBIDDEN_WORDS = {"rank", "ranking", "score", "scoring", "recommend", "recommendation", "buy", "sell", "portfolio",
                   "allocation", "conviction", "priority", "weight", "rating", "position", "trade",
                   "instruction", "llm", "prompt", "latest", "current", "automation", "schedule", "cron",
                   "holding", "holdings", "rebalance", "suitability", "urgency", "importance", "return", "returns"}
#: 単語では禁止しない語（「対象」の `target`）の複合の禁止
FORBIDDEN_COMPOUNDS = ("target_price", "target_return", "target_weight", "price_target", "expected_return",
                       "risk_score", "risk_category", "position_size")
P9_STORE_OPENERS = {"WatchlistStore", "ThesisStore"}
#: `.open(...)` の規則（file → 受け手の名前の集合 ／ store_io は mode の文字列）。他の file に `.open` は無い
OPEN_RECEIVERS = {P10_P9_VIEW: P9_STORE_OPENERS, P10_AUTHORITY_STORES: {"ProfileStore", "AttentionStore", "cls"},
                  P10_EXECUTOR: {"PersonalAuthorityStores"}, P10_ADMIN_INIT: {"PersonalAuthorityStores"},
                  P10_REVIEW_VIEW: {"ProfileStore", "AttentionStore"}}
STORE_IO_OPEN_MODES = {"ab", "xb"}                                                # 追記 ・排他の作成だけ（切り詰め ・上書きなし）
#: 禁止の名前のうち file ごとに許すもの（store_io の物理的な書き込み ・coordinator の私的な追記の呼び出し）
NAME_ALLOWANCES = {P10_STORE_IO: {"write", "flush", "fsync", "mkdir"}, P10_AUTHORITY_STORES: {"_append_line"},
                   P10_ADMIN_INIT: {"initialize"}, P10_LOCAL_CLI: {"write"}}


def _git(*args: str) -> str:
    """git の出力を UTF-8 で厳密に復号する（`text=True` は locale の符号化 ＝ Windows の cp932 等で復号し、UTF-8 の
    blob の `git show` が `UnicodeDecodeError` になる ・P10-A5 の Windows の preflight）。改行は universal newline。"""
    return subprocess.run(["git", *args], cwd=REPO_ROOT, capture_output=True, encoding="utf-8", errors="strict",
                          check=True).stdout


def _blob_ids(anchor: str, paths) -> tuple:
    """(anchor の git の object の id, worktree の file を git の checkout の正規化（autocrlf ・attributes）で hash した id)。
    checkout の改行の変換だけを除き、内容の byte の違いは全て検出する。"""
    anchored = tuple(_git("rev-parse", *(f"{anchor}:{path}" for path in paths)).split())
    current = tuple(_git("hash-object", "--", *paths).split())
    return anchored, current


def _changes(*args: str) -> set:
    return {tuple(line.split("\t")) for line in _git("diff", *args).splitlines()}


def _imports(path: Path):
    relative, absolute = {}, set()
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.ImportFrom) and node.level:
            relative.setdefault("." * node.level + node.module, set()).update(a.name for a in node.names)
        elif isinstance(node, ast.ImportFrom):
            absolute.add(node.module)
        elif isinstance(node, ast.Import):
            absolute.update(a.name for a in node.names)
    return relative, absolute


# ================================================ registry ・面 ・凍結の test の登録


def test_p10_a1_the_registry_is_exact_and_disjoint_from_earlier_phases() -> None:
    assert P10_BASE == "3bfc76c6b2f76f613bb50710e6e7eb976a642326"
    assert subprocess.run(["git", "merge-base", "--is-ancestor", P10_BASE, "HEAD"], cwd=REPO_ROOT).returncode == 0
    assert PHASE10_A1_RUNTIME == (f"{PHASE10_PACKAGE}/__init__.py", P10_P9_VIEW)
    assert PHASE10_A2_RUNTIME == tuple(f"{PHASE10_PACKAGE}/{name}.py" for name in (
        "attention_model", "cross_rules", "profile_model", "revision_model"))
    assert PHASE10_A3_RUNTIME == tuple(f"{PHASE10_PACKAGE}/{name}.py" for name in (
        "attention_store", "authority_stores", "profile_store", "serialization", "store_io"))
    assert PHASE10_A4_RUNTIME == tuple(f"{PHASE10_PACKAGE}/{name}.py" for name in (
        "admin_init", "decisions", "executor", "local_cli", "personal_projection", "review_view"))
    assert PHASE10_RUNTIME == tuple(sorted(PHASE10_A1_RUNTIME + PHASE10_A2_RUNTIME + PHASE10_A3_RUNTIME
                                           + PHASE10_A4_RUNTIME))
    assert {p.name for p in PACKAGE_DIR.iterdir() if p.name != "__pycache__"} == {Path(p).name for p in PHASE10_RUNTIME}
    for path in (*PHASE10_RUNTIME, *PHASE10_TESTS, *PHASE10_DOCS):
        assert (REPO_ROOT / path).is_file(), path
    assert not set(PHASE10_RUNTIME) & (set(PHASE9_RUNTIME) | set(PHASE8_RUNTIME) | set(PHASE7_RUNTIME))
    assert not any(_git("ls-tree", P10_BASE, "--", p).strip() for p in (*PHASE10_RUNTIME, *PHASE10_TESTS,
                                                                       *PHASE10_DOCS))
    assert set(SANCTIONED_P10_P9_IMPORTERS) == {P10_P9_VIEW}                       # Phase 9 の importer は 1 file だけ


def test_p10_a1_since_the_base_only_registered_phase10_files_and_declared_registration_changed() -> None:
    assert _changes("--cached", "--name-status", P10_BASE, "--", "src") == {("A", p) for p in PHASE10_RUNTIME
                                                                            + PHASE11_RUNTIME + PHASE12_RUNTIME + PHASE13_RUNTIME}
    assert _git("diff", "--cached", "--name-status", P10_BASE, "--", *FROZEN_SURFACE) == ""
    assert _changes("--cached", "--name-status", P10_BASE, "--", "docs") <= {("A", p) for p in PHASE10_DOCS
                                                                             + PHASE11_DOCS + PHASE12_DOCS + PHASE13_DOCS}
    assert _changes("--cached", "--name-status", P10_BASE, "--", "tests") <= {
        ("A", p) for p in PHASE10_TESTS + PHASE11_TESTS + PHASE12_TESTS + PHASE13_TESTS} | {
            ("M", p) for p in PHASE10_TEST_REGISTRATION}
    assert set(PHASE10_TEST_REGISTRATION) == {"tests/intelligence/phase7_runtime_registry.py",
                                              "tests/intelligence/test_narrative_intelligence_boundary.py",
                                              "tests/intelligence/test_screener_intelligence_boundary.py",
                                              "tests/intelligence/test_watchlist_thesis_boundary.py"}
    for path in PHASE10_TEST_REGISTRATION:                                            # 凍結の P7 ／ P8 ／ P9 の test の狭い再開
        anchored = _git("show", f"{P10_BASE}:{path}")
        current = _git("show", f"{P11_BASE}:{path}")             # P10 の登録は P10 の終わりまで（以後の差は P11 の guard が pin）
        assert only_phase10_registration(path, anchored, current), path
        assert not only_phase10_registration(path, anchored, current + "assert True\n")
        assert not only_phase10_registration(path, anchored, anchored)
    for registry in ("tests/intelligence/phase8_runtime_registry.py", "tests/intelligence/phase9_runtime_registry.py"):
        assert _git("diff", "--name-status", P10_BASE, "--", registry) == "", registry   # P8 ／ P9 の registry は不変


def test_p10_a1_earlier_phase_runtime_is_byte_identical_to_its_freeze_anchor() -> None:
    assert P9_A5 == "4c1970174f678245b569fdbb812a8a6ced52410b" and len(PHASE9_RUNTIME) == 18
    for anchor, runtime in ((P9_A5, PHASE9_RUNTIME), (P8_B5C, PHASE8_RUNTIME)):     # git の object の id の一致
        anchored, current = _blob_ids(anchor, runtime)
        assert len(anchored) == len(current) == len(runtime)
        assert [p for p, a, c in zip(runtime, anchored, current) if a != c] == []
    assert _git("diff", "--name-status", P10_BASE, "--", *PHASE7_RUNTIME, *PHASE8_RUNTIME, *PHASE9_RUNTIME) == ""
    assert _git("status", "--porcelain", "--", *PHASE7_RUNTIME, *PHASE8_RUNTIME, *PHASE9_RUNTIME) == ""


# ================================================ import の面 ・書き込み ・語彙


def test_p10_a1_imports_are_exactly_the_sanctioned_read_only_phase9_surfaces() -> None:
    for path in PHASE10_RUNTIME:
        relative, absolute = _imports(REPO_ROOT / path)
        allowed = STDLIB_IMPORTS | EXTRA_STDLIB.get(path, set())
        assert absolute <= allowed, absolute - allowed
        if path == P10_P9_VIEW:
            assert relative == SANCTIONED_P10_P9_IMPORTS
        elif path in SANCTIONED_P10_A2_MODULES:                                         # A2: package の中と core の補助だけ
            assert set(relative) == SANCTIONED_P10_A2_MODULES[path], path
            for module, names in relative.items():
                assert module.startswith(".") and not module.startswith("..") or (
                    names == SANCTIONED_P10_CORE_IMPORTS[module]), (path, module)
                assert module != ".p9_view", path                                         # A2 は P9 を読まない
        elif path in SANCTIONED_P10_A3_MODULES or path in SANCTIONED_P10_A4_MODULES:     # A3 ・A4: package の中だけ
            assert set(relative) == {**SANCTIONED_P10_A3_MODULES, **SANCTIONED_P10_A4_MODULES}[path], path
            assert all(m.startswith(".") and not m.startswith("..") for m in relative), path
            if ".p9_view" in relative:                                                   # A1 の adapter の使い手
                assert relative[".p9_view"] == SANCTIONED_P10_P9_VIEW_IMPORTERS[path], path
        else:
            assert path == f"{PHASE10_PACKAGE}/__init__.py" and relative == {} and absolute == set()   # docstring だけ
        for module in (*[m for m in relative if m.startswith("..")], *absolute):     # package の外（中は上で完全一致）
            assert not any(part in module for part in FORBIDDEN_MODULE_PARTS), module
        private = {n for names in relative.values() for n in names if n.startswith("_")}
        assert private == SANCTIONED_P10_PRIVATE_WRITER_IMPORTS.get(path, set()), (path, private)
        if private:
            assert relative[".store_io"] >= private


def test_p10_a1_the_adapter_never_writes_creates_reads_credentials_or_uses_write_capable_p9_objects() -> None:
    for path in PHASE10_RUNTIME:
        tree = ast.parse((REPO_ROOT / path).read_text(encoding="utf-8"))
        words = set()
        banned = FORBIDDEN_NAMES - NAME_ALLOWANCES.get(path, set())                   # `.open` は下の受け手 ／ mode の規則
        for node in ast.walk(tree):
            assert not (isinstance(node, ast.Name) and node.id in banned | {"open"}), (path, node.id)
            assert not (isinstance(node, ast.Attribute) and node.attr in banned), (path, node.attr)
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "open":
                if path == P10_STORE_IO:                                                  # 追記 ・排他の作成の mode だけ
                    assert len(node.args) == 1 and not node.keywords and isinstance(node.args[0], ast.Constant) \
                        and node.args[0].value in STORE_IO_OPEN_MODES, "open mode"
                else:
                    assert isinstance(node.func.value, ast.Name) and \
                        node.func.value.id in OPEN_RECEIVERS.get(path, set()), (path, "open")
                    assert len(node.args) == 1 and not node.keywords, "open(root) only"
            assert not (isinstance(node, ast.ExceptHandler) and (node.type is None or (
                isinstance(node.type, ast.Name) and node.type.id in ("Exception", "BaseException")))), "broad except"
            names = [node.id] if isinstance(node, ast.Name) else [node.attr] if isinstance(node, ast.Attribute) else \
                [node.arg] if isinstance(node, ast.arg) else [node.name] if isinstance(
                    node, (ast.FunctionDef, ast.ClassDef)) else []
            for name in names:
                words |= {w.lower() for w in re.findall(r"[A-Z]?[a-z]+|[A-Z]+(?![a-z])", name)}
        assert not words & FORBIDDEN_WORDS, words & FORBIDDEN_WORDS
        identifiers = {n.lower() for n in (_identifiers(tree))}
        for compound in FORBIDDEN_COMPOUNDS:
            assert not any(compound in name for name in identifiers), compound
        source = (REPO_ROOT / path).read_text(encoding="utf-8")
        for token in ("JQUANTS_API_KEY", "x-api-key", "api.jquants.com", "://", "config.yaml", "watchlist:"):
            assert token not in source, token


def test_p10_a1_is_outside_production_and_no_other_code_imports_it() -> None:
    assert not any("personal_intelligence" in module for module in runtime_closure())
    for path in [REPO_ROOT / "main.py", *sorted((REPO_ROOT / "src").rglob("*.py")),
                 *sorted((REPO_ROOT / "scripts").rglob("*.py"))]:
        if not path.exists() or PACKAGE_DIR in path.parents:
            continue
        if path.relative_to(REPO_ROOT).as_posix() in SANCTIONED_P11_P10_IMPORTERS:  # P11: governed な read の importer だけ
            cross = {m: n for m, n in _imports(path)[0].items() if m.startswith("..")}
            assert cross == SANCTIONED_P11_P10_IMPORTERS[path.relative_to(REPO_ROOT).as_posix()]   # 面は完全一致
            continue
        assert "personal_intelligence" not in path.read_text(encoding="utf-8", errors="replace"), path


def _identifiers(tree: ast.AST) -> set:
    found = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Name):
            found.add(node.id)
        elif isinstance(node, ast.Attribute):
            found.add(node.attr)
        elif isinstance(node, ast.arg):
            found.add(node.arg)
        elif isinstance(node, (ast.FunctionDef, ast.ClassDef)):
            found.add(node.name)
    return found


def test_p10_a2_the_pure_models_have_no_io_store_executor_clock_or_phase9_surface() -> None:
    assert set(SANCTIONED_P10_A2_MODULES) == set(PHASE10_A2_RUNTIME)
    for path in PHASE10_A2_RUNTIME:
        source = (REPO_ROOT / path).read_text(encoding="utf-8")
        identifiers = _identifiers(ast.parse(source))
        for name in ("Path", "pathlib", "os", "io", "open", "read_text", "read_bytes", "initialize", "append",
                     "store", "Store", "executor", "execute", "p9_view", "read_p9_safe_view",
                     "read_p9_private_snapshot", "now", "today", "random", "uuid", "time_ns"):
            assert name not in identifiers, (path, name)
        for token in ("watchlist_thesis_intelligence", "screener_intelligence", "narrative_intelligence"):
            assert token not in source, (path, token)


def test_p10_a1_the_contract_records_the_required_clauses() -> None:
    text = (REPO_ROOT / CONTRACT_DOC).read_text(encoding="utf-8")
    for clause in ("P9-OBS-019", "AuthorityStores", "read_p9_safe_view", "read_p9_private_snapshot", "check_world",
                   "P9_WORLD_INVALID", "P9_STORE_UNAVAILABLE", "P10_BASE", "3bfc76c6b2f76f613bb50710e6e7eb976a642326",
                   "PHASE10_TEST_REGISTRATION", "FOCUS", "Phase 10 の凍結ではない"):
        assert clause in text, clause


def test_p10_a2_the_contract_records_the_required_clauses() -> None:
    text = (REPO_ROOT / A2_CONTRACT_DOC).read_text(encoding="utf-8")
    for clause in ("PersonalProfileRevision", "AttentionRevision", "check_personal_world", "FOCUS", "MUTE", "CLEARED",
                   "RETIRED", "REVIEW_LOOKAHEAD_MAX_DAYS", "observed_p9_revision_id", "A4", "store",
                   "Phase 10 の凍結ではない", "P10-OBS-017"):
        assert clause in text, clause


def test_p10_a3_only_store_io_writes_and_only_the_coordinator_can_append_or_initialize() -> None:
    from src.intelligence.personal_intelligence import store_io
    from src.intelligence.personal_intelligence.attention_store import AttentionStore
    from src.intelligence.personal_intelligence.authority_stores import PersonalAuthorityStores
    from src.intelligence.personal_intelligence.profile_store import ProfileStore

    assert set(SANCTIONED_P10_A3_MODULES) == set(PHASE10_A3_RUNTIME)
    for path in PHASE10_RUNTIME:                                                    # 物理的な書き込みは store_io だけ
        tree = ast.parse((REPO_ROOT / path).read_text(encoding="utf-8"))
        attrs = {n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute)}
        writes = attrs & {"write", "flush", "fsync", "mkdir", "read_bytes", "stat", "chmod", "replace", "rmdir",
                          "symlink_to", "link_to", "hardlink_to", "write_text", "write_bytes"}
        allowed = {P10_STORE_IO: {"write", "flush", "fsync", "mkdir", "read_bytes", "stat"},
                   P10_LOCAL_CLI: {"write", "read_bytes"}}.get(path, set())              # CLI: 標準出力 ・decision の file
        assert writes <= allowed, (path, writes)
        defined = {n.name for n in ast.walk(tree) if isinstance(n, (ast.FunctionDef, ast.ClassDef))}
        if path != P10_STORE_IO:
            assert not {"_append_line", "_initialize_files"} & defined, path
    assert set(store_io.__all__) == {"ATTENTION_FILENAME", "AUTHORITY_FILENAMES", "AppendResult", "AppendStatus",
                                     "AuthorityFile", "PERSONAL_DIRNAME", "PROFILE_FILENAME", "PersonalStoreError",
                                     "STORE_SCHEMA_VERSION", "StoreFailureCategory", "fail"}
    for store in (store_io.AuthorityFile, ProfileStore, AttentionStore):            # 個々の store に追記 ・初期化は無い
        public = {name for name in dir(store) if not name.startswith("_")}
        assert public == {"FILENAME", "KIND", "all_revisions", "chain", "line_for", "line_of", "open", "revalidate",
                          "revision", "revision_at_seq", "roots", "same_directory", "state_at", "states_at",
                          "verify_unchanged"}, public
    public = {name for name in dir(PersonalAuthorityStores) if not name.startswith("_")}
    assert public == {"append_attention_revision", "append_profile_revision", "attention", "initialize", "open",
                      "profile"}, public


def test_p10_a3_the_contract_records_the_required_clauses() -> None:
    text = (REPO_ROOT / A3_CONTRACT_DOC).read_text(encoding="utf-8")
    for clause in ("PersonalAuthorityStores", "append_profile_revision", "append_attention_revision",
                   "profile_authority.jsonl", "attention_authority.jsonl", "personal_intelligence/", "_append_line",
                   "CONCURRENT_MODIFICATION", "REUSED", "CHAIN_HEAD_MISMATCH", "REVISION_CONFLICT", "fsync",
                   "check_personal_world", "A4", "Phase 10 の凍結ではない", "P10-OBS-025"):
        assert clause in text, clause


def test_p10_a4_only_the_executor_constructs_or_appends_authority_and_only_admin_init_initializes() -> None:
    assert set(SANCTIONED_P10_A4_MODULES) == set(PHASE10_A4_RUNTIME)
    constructors = {"PersonalProfileRevision", "AttentionRevision", "derive_profile_id", "derive_attention_id",
                    "replace"}
    for path in PHASE10_A3_RUNTIME + PHASE10_A4_RUNTIME:
        tree = ast.parse((REPO_ROOT / path).read_text(encoding="utf-8"))
        calls = {(n.func.id if isinstance(n.func, ast.Name) else n.func.attr) for n in ast.walk(tree)
                 if isinstance(n, ast.Call) and isinstance(n.func, (ast.Name, ast.Attribute))}
        attrs = {n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute)}
        made = calls & constructors
        if path == P10_EXECUTOR:
            assert made == constructors - {"replace"}, made                                # 新しい authority は実行器だけ
        elif path == f"{PHASE10_PACKAGE}/serialization.py":
            assert made == {"PersonalProfileRevision", "AttentionRevision"}, made          # 永続の記録の復元だけ
        else:
            assert not made, (path, made)
        appends = attrs & {"append_profile_revision", "append_attention_revision"}
        assert not appends or path == P10_EXECUTOR, (path, appends)                       # 追記の経路は実行器だけ
        assert "initialize" not in attrs or path == P10_ADMIN_INIT, path                   # 初期化は管理の操作だけ
    for path in PHASE10_RUNTIME:                                                        # P9 の情報は A1 の adapter だけ
        relative, _ = _imports(REPO_ROOT / path)
        assert (".p9_view" in relative) == (path in SANCTIONED_P10_P9_VIEW_IMPORTERS), path
    cli = (REPO_ROOT / P10_LOCAL_CLI).read_text(encoding="utf-8")
    tree = ast.parse(cli)
    writes = [n for n in ast.walk(tree) if isinstance(n, ast.Attribute) and n.attr == "write"]
    assert len(writes) == 1 and isinstance(writes[0].value, ast.Name) and writes[0].value.id == "stream"
    for token in ("environ", "getenv", "default=", "now(", "today("):
        assert token not in cli, token


def test_p10_a4_the_contract_records_the_required_clauses() -> None:
    text = (REPO_ROOT / A4_CONTRACT_DOC).read_text(encoding="utf-8")
    for clause in ("apply_decision", "dry_run_decision", "read_personal_review", "personal_safe_projection",
                   "init_personal_root", "PARTIAL_LAYOUT", "STALE_AUTHORITY_HEAD", "P9_TARGET_ABSENT",
                   "P9_TARGET_KIND_MISMATCH", "P9_REVISION_STALE_OR_MISMATCH", "UNENCODABLE_TEXT",
                   "read_p9_private_snapshot", "EXCLUDED_BY_PROFILE", "FOCUS", "NORMAL", "MUTE", "A5",
                   "Phase 10 の凍結ではない", "P10-OBS-033"):
        assert clause in text, clause


def test_p10_windows_portability_git_guards_are_locale_and_checkout_newline_independent(tmp_path: Path) -> None:
    """P10-A5 の Windows の preflight の回帰: locale が UTF-8 でない Python（Windows の cp932 等）と CRLF の checkout。"""
    anchor_path = PHASE9_RUNTIME[0]
    raw = subprocess.run(["git", "show", f"{P9_A5}:{anchor_path}"], cwd=REPO_ROOT, capture_output=True,
                         check=True).stdout
    assert any(byte >= 0x80 for byte in raw)                                          # 非 ASCII（日本語）の blob
    assert _git("show", f"{P9_A5}:{anchor_path}") == raw.decode("utf-8").replace("\r\n", "\n")
    with __import__("pytest").raises(UnicodeDecodeError):
        raw.decode("cp932")                                                            # Windows の locale の既定では読めない
    # 同じ 2 つの guard を UTF-8 mode でない Python（ASCII の locale）で走らせる（Windows の条件の再現）
    env = {k: v for k, v in __import__("os").environ.items() if k not in ("PYTHONUTF8", "LC_ALL", "LC_CTYPE", "LANG")}
    env.update(PYTHONUTF8="0", LC_ALL="C", PYTHONIOENCODING="utf-8")
    node = "tests/intelligence/test_personal_intelligence_boundary.py::"
    result = subprocess.run([__import__("sys").executable, "-m", "pytest", "-q", "-p", "no:cacheprovider",
                             node + "test_p10_a1_since_the_base_only_registered_phase10_files_and_declared_registration_changed",
                             node + "test_p10_a1_earlier_phase_runtime_is_byte_identical_to_its_freeze_anchor"],
                            cwd=REPO_ROOT, env=env, capture_output=True, check=False)
    assert result.returncode == 0, result.stdout.decode("utf-8", "replace")[-2000:]
    # CRLF の checkout は git の正規化で同じ object（意味の byte の一致）・内容の 1 byte の違い ／ 正規化なしの CR は検出する
    crlf = tmp_path / "crlf_copy.py"
    crlf.write_bytes(raw.replace(b"\n", b"\r\n"))
    anchored = _git("rev-parse", f"{P9_A5}:{anchor_path}").strip()

    def hashed(path: Path, autocrlf: str) -> str:
        return _git("-c", f"core.autocrlf={autocrlf}", "hash-object", f"--path={anchor_path}", str(path)).strip()

    assert hashed(crlf, "true") == anchored                                            # Windows の checkout の変換だけ
    assert hashed(crlf, "false") != anchored                                           # 正規化なしの CR は違い
    changed = tmp_path / "changed_copy.py"
    changed.write_bytes(raw.replace(b"\n", b"\r\n") + b"# changed\r\n")
    assert hashed(changed, "true") != anchored                                         # 意味の違いは検出


# ================================================ 凍結の記録（P10-FREEZE-RECORD。記録の commit は新しい anchor ではない）


def _is_ancestor(older: str, newer: str) -> bool:
    return subprocess.run(["git", "merge-base", "--is-ancestor", older, newer], cwd=REPO_ROOT).returncode == 0


def test_p10_freeze_the_17_registered_runtime_files_are_object_identical_to_the_anchor_and_the_validated_tree() -> None:
    assert P10_A4 == "1a7b9a26c8ee6a2b86a30e88c224a737565ce979"
    assert P10_VALIDATED_TREE == "e46bbae85167ab3dbcb70285f214a066ec01781e"
    assert _is_ancestor(P10_A4, "HEAD") and _is_ancestor(P10_VALIDATED_TREE, "HEAD")
    assert _is_ancestor(P10_A4, P10_VALIDATED_TREE) and P10_A4 != P10_VALIDATED_TREE
    assert len(PHASE10_RUNTIME) == 17 and len(set(PHASE10_RUNTIME)) == 17
    anchored_package = {path for path in _git("ls-tree", "-r", "--name-only", P10_A4, "--", PHASE10_PACKAGE).splitlines()
                        if path.endswith(".py")}
    assert anchored_package == set(PHASE10_RUNTIME)                                   # anchor の package ＝ 登録の 17
    for path in PHASE10_RUNTIME:
        assert _git("ls-tree", P10_A4, "--", path).strip(), path                      # anchor に在る
    at_anchor, in_worktree = _blob_ids(P10_A4, PHASE10_RUNTIME)                       # git の object の id（locale ・改行に依らない）
    at_validated, _ = _blob_ids(P10_VALIDATED_TREE, PHASE10_RUNTIME)
    in_index = tuple(_git("rev-parse", *(f":{path}" for path in PHASE10_RUNTIME)).split())
    assert len(at_anchor) == len(at_validated) == len(in_worktree) == len(in_index) == 17
    assert at_anchor == at_validated, "runtime blob differs between P10_A4 and P10_VALIDATED_TREE"
    assert at_anchor == in_index, "runtime blob differs between P10_A4 and the index"
    assert at_anchor == in_worktree, "runtime blob differs between P10_A4 and the worktree"
    # anchor 以後に Phase 10 の src runtime は変わっていない（commit ・index ・worktree）。validated tree は test と CHANGELOG だけ
    assert _git("diff", "--name-status", P10_A4, "HEAD", "--", PHASE10_PACKAGE) == ""     # Phase 10 の src runtime は不変
    assert _git("diff", "--cached", "--name-status", P10_A4, "--", PHASE10_PACKAGE) == ""
    assert _git("status", "--porcelain", "--", *PHASE10_RUNTIME) == ""
    assert set(_git("diff", "--name-only", P10_A4, P10_VALIDATED_TREE).splitlines()) == {
        "CHANGELOG.md", "tests/intelligence/test_personal_intelligence_boundary.py"}
    # 凍結の記録は anchor ・validated tree の後に足された（記録の commit は新しい anchor ではない）
    assert FREEZE_DOC in PHASE10_DOCS
    assert not _git("ls-tree", P10_A4, "--", FREEZE_DOC).strip()
    assert not _git("ls-tree", P10_VALIDATED_TREE, "--", FREEZE_DOC).strip()
    text = (REPO_ROOT / FREEZE_DOC).read_text(encoding="utf-8")
    for clause in ("COMPLETE / CLOSED / FROZEN", P10_A4, P10_VALIDATED_TREE, "17", "A5_PASS", "P10_FINAL_AUDIT_PASS",
                   "P10-OBS-054", "Phase 10.1", "Phase 11"):
        assert clause in text, clause


def test_p10_freeze_the_record_holds_no_private_validation_values() -> None:
    text = (REPO_ROOT / FREEZE_DOC).read_text(encoding="utf-8")
    for pattern in FREEZE_DOC_PRIVATE_PATTERNS:
        assert not re.search(pattern, text), pattern
    for sample in ("p9wat_" + "0" * 24, "p10prf_" + "0" * 24, "human:reviewer", "2026-01-01T09:00", "D:\\x", "72030",
                   "A5 validation-only profile."):
        assert any(re.search(pattern, sample) for pattern in FREEZE_DOC_PRIVATE_PATTERNS), sample   # 形は実際に検出する
    assert re.search(r"\b\d{1,4}\b", text)                                               # 集計の件数は許す
