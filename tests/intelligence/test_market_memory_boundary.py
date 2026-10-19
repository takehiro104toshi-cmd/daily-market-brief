"""P13-A0 — Phase 13（Market Memory ／ Review State Memory）の runtime の面の登録の guard。

- `PHASE13_RUNTIME` は空 ・P13 の package は存在しない（今 ・`P13_BASE` ・P12.5 の設計の closeout の anchor のどれにも）。
- `P13_BASE` 以後に変わったのは登録した P13 の test ・文書と、凍結の P7 〜 P12 の test への宣言した登録の行だけ（完全一致で pin）。
- 凍結の P8 〜 P12 の runtime の blob ・P12.5 の設計の契約の blob は anchor と object 一致。
- registry の drift は digest で止める: `PHASE13_RUNTIME` ・認可 ・test ・文書の集合の正準 digest が本 file の定数と一致しなければ落ちる
  （runtime の追加は registry と本 file と gate の文書の 3 つを同時に ・監督の gate で変える）。
- importer の許可は P13-A2a の adapter の 1 file だけ（P10 の governed な 5 つの名前 ・完全一致）。他の textual な import の禁止は不変。
- P13-A1 の runtime 4 file の blob は `P13_A1` の commit に pin（HEAD ・index ・作業木）。
- P13-A3: A2a の adapter の blob は `P13_A2A` に pin。filesystem の I/O の許しは `memory_store.py` だけ（stdlib の `os` ・`stat` ・名前 ・語の
  file ごとの許し ・`os` の属性の allowlist）。削除は `_unlink_if_owned` の 1 箇所の `unlink` だけで、呼ぶのは lock の解放と pointer の一時 file の
  破棄だけ（一般の削除 ・rmdir ・rmtree ・truncate は P13 のどこにも無い）。
- P13-A4a: A3 の Memory Store の 3 file の blob は `P13_A3` に pin（A1 ・A2a の pin も維持）。純粋な投影の model `memory_projection.py` は
  I/O を持たない（stdlib ・相対 import の面の完全一致 ・filesystem ／ network ／ process ／ 資格情報 ／ scheduler ・動的実行 ・import の時の
  副作用 ・項目 ／ 瞬間の属性の読みが無い）。P10 の importer の許可は不変。
- negative control: 未登録の path ・修正 ・近い名前 ・未宣言の登録の行 ・禁止の token ・一般の削除 ・store の外の I/O ・blob の変化 ・
  認可の drift ・公開の面の変更は落ちる。
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
from tests.intelligence.phase13_runtime_registry import (ADDITION_STATUSES, FORBIDDEN_P13_TOKENS, P13_A1, P13_A2A, P13_A3, P13_BASE,
                                                         PHASE13_A1_RUNTIME, PHASE13_A2A_IMPORTER_LINES, PHASE13_A2A_RUNTIME,
                                                         PHASE13_A3_RUNTIME, PHASE13_A4A_RUNTIME, PHASE13_DOCS,
                                                         SANCTIONED_P13_P10_IMPORTERS, SANCTIONED_P13_P10_IMPORTS,
                                                         PHASE13_PACKAGE, PHASE13_RUNTIME, PHASE13_RUNTIME_AUTHORIZATION,
                                                         PHASE13_TESTS, PHASE13_TEST_REGISTRATION, is_phase13_addition,
                                                         only_phase13_registration, registration_diff)
from tests.intelligence.test_automation_boundary import FORBIDDEN_NAMES, FORBIDDEN_WORDS
from tests.intelligence.test_p43b2c_production_bundle import runtime_closure

REPO_ROOT = Path(__file__).resolve().parents[2]
PACKAGE_DIR = REPO_ROOT / PHASE13_PACKAGE
A0_DOC = "docs/databank/PHASE13_A0_RUNTIME_SURFACE_REGISTRATION.md"
A1_DOC = "docs/databank/PHASE13_A1_REVIEW_STATE_MODEL.md"
A2A_DOC = "docs/databank/PHASE13_A2A_GOVERNED_P10_ADAPTER.md"
A3_DOC = "docs/databank/PHASE13_A3_MEMORY_STORE.md"
ROADMAP_DOC = "docs/databank/MARKET_BRAIN_ROADMAP_RECORD.md"
A4A_DOC = "docs/databank/PHASE13_A4A_PROJECTION_MODEL.md"
ADAPTER = "src/intelligence/market_memory/governed_review_source.py"
GENERATION_MODULE = "src/intelligence/market_memory/memory_generation.py"
STORE_MODULE = "src/intelligence/market_memory/memory_store.py"
BUILD_MODULE = "src/intelligence/market_memory/memory_build.py"
PROJECTION_MODULE = "src/intelligence/market_memory/memory_projection.py"
P13_ROADMAP = "5e5f015ecebf64116f9c1721c36d9d41fa9dc1c7"   # roadmap の記録の commit ＝ A4a の認可の anchor
P10_IMPORTER_GUARD = "tests/intelligence/test_personal_intelligence_boundary.py"
P13_A0 = "4d464c30e4598d2ad5a0cee5a34ac366414fbde3"   # P13-A0 の commit ＝ A1 の認可の anchor
#: P13 の runtime が import してよい stdlib（file ごと ・完全一致）。file ・OS ・時計 ・環境 ・process ・socket ・乱数は無い
SANCTIONED_P13_STDLIB = {"__future__", "dataclasses", "datetime", "enum", "hashlib", "json", "re", "typing"}
SANCTIONED_P13_MODULES = {"src/intelligence/market_memory/__init__.py": set(), "src/intelligence/market_memory/canonical.py": set(),
                          "src/intelligence/market_memory/review_state_sample.py": {".canonical"},
                          "src/intelligence/market_memory/review_state_change.py": {".canonical", ".review_state_sample"},
                          ADAPTER: {".canonical", ".review_state_sample", *SANCTIONED_P13_P10_IMPORTS},
                          GENERATION_MODULE: {".canonical", ".review_state_change", ".review_state_sample"},
                          STORE_MODULE: {".canonical", ".memory_generation"},
                          BUILD_MODULE: {".governed_review_source", ".memory_generation", ".memory_store", ".review_state_sample"},
                          PROJECTION_MODULE: {".canonical", ".memory_generation", ".review_state_change", ".review_state_sample"}}
#: P13-A3: filesystem の I/O を持つ唯一の module（file ごとの許し ・理由を伴う完全一致。他の P13 の file には無い）
SANCTIONED_P13_EXTRA_STDLIB = {STORE_MODULE: {"os", "stat"}}
P13_NAME_ALLOWANCES = {STORE_MODULE: {"open", "write", "mkdir", "rename", "unlink", "stat"}}   # os.open ・os.write ・os.mkdir ・os.rename ・所有した lock ／ 一時 file の unlink ・stat の module ／ os.stat
P13_WORD_ALLOWANCES = {STORE_MODULE: {"path"}}                                                  # os.path だけ
#: P13 のどこにも在ってはならない削除 ・切り詰めの名前（store の `_unlink_if_owned` の `unlink` 1 箇所だけが例外）
P13_DELETION_NAMES = {"unlink", "remove", "removedirs", "rmdir", "rmtree", "truncate", "ftruncate", "unlinkat", "rmtree_safe"}
P13_UNLINK_SITES = [("_unlink_if_owned", "unlink")]
P13_UNLINK_CALLERS = {"release", "_publish_pointer"}
SANCTIONED_P13_OS_ATTRIBUTES = {"altsep", "close", "fspath", "fstat", "fsync", "listdir", "lstat", "mkdir", "name", "open", "path",
                                "read", "rename", "replace", "sep", "stat", "stat_result", "unlink", "write", "O_CREAT", "O_EXCL",
                                "O_RDONLY", "O_WRONLY"}
SANCTIONED_P13_OS_PATH_ATTRIBUTES = {"abspath", "commonpath", "dirname", "isabs", "join", "normcase", "normpath", "realpath",
                                     "splitdrive"}
SANCTIONED_P13_OS_GETATTR = {"O_BINARY", "O_NOFOLLOW"}
#: store の `os` の危険な呼び出しの場所（関数の名前 ・完全一致）。unlink は所有した lock ／ 一時 file の 1 箇所 ・os.stat は重なりの identity だけ ・
#: replace は pointer の置換だけ ・rename は generation ／ 試行の公開と置き換えない移動だけ ・mkdir は初期化 ・staging ・移動の予約だけ
P13_OS_CALL_SITES = {"unlink": {"_unlink_if_owned"}, "stat": {"_identities"}, "replace": {"_publish_pointer"},
                     "rename": {"_stage_generation", "record_attempt", "_move_without_replacing"},
                     "mkdir": {"_stage_generation", "initialize_memory_root", "_move_without_replacing"},
                     "open": {"_create_file", "_read_file", "_fsync_directory"}, "write": {"_write_all"}}
#: store の公開の面（関数 ・method ・完全一致）。writer lock を動かす ・奪う ・消す回復は無い
P13_STORE_PUBLIC_FUNCTIONS = {"initialize_memory_root", "open_memory_store", "read_memory", "preserve_interrupted_staging",
                              "preserve_publication_pointer"}
P13_STORE_PUBLIC_METHODS = {"acquire_writer_lock", "check_disjoint", "check_writable", "list_attempts", "list_generations",
                            "protected_labels", "publish_generation", "read_attempt", "read_generation", "read_publication",
                            "record_attempt", "staging_present"}
P13_PRESERVE_CALLERS = {"preserve_interrupted_staging", "preserve_publication_pointer"}
#: P13-A4a: 投影の model の stdlib の面（完全一致 ・`SANCTIONED_P13_STDLIB` より狭い ・hashlib ・datetime も無い）
P13_PROJECTION_STDLIB = {"__future__", "dataclasses", "enum", "json", "re", "typing"}
#: 投影の model に在ってはならない名前（凍結の `FORBIDDEN_NAMES` に加えて: 動的な import ・実行 ・属性の取得 ・I/O ／ 時計の module）
P13_PROJECTION_FORBIDDEN_NAMES = {"__import__", "importlib", "getattr", "globals", "locals", "vars", "compile", "Path", "pathlib", "io", "os",
                                  "shutil", "tempfile", "time", "sched", "asyncio", "threading", "urllib", "http", "requests"}
#: 投影の model が読んではならない属性（項目の id ・期日 ・瞬間 ・telemetry）
P13_PROJECTION_UNREAD_ATTRIBUTES = {"entries", "p9_root_id", "issuer_id", "p9_revision_id", "linked_watch_entry_id", "review_due_on", "at",
                                    "sampled_at", "known_at", "reviewed_at", "structural_values"}
#: 投影の model の module の直下で呼んでよいもの（定数の組み立てだけ ・import の時の副作用は無い）
P13_PROJECTION_MODULE_CALLS = {"compile", "frozenset", "tuple"}
P13_PROJECTION_PUBLIC_FUNCTIONS = {"abort_for", "build_projection_input", "check_recovery_proposal", "classify_publication", "completion_for",
                                   "intent_for", "interval_digest", "parse_abort", "parse_completion", "parse_export_manifest", "parse_intent",
                                   "parse_pointer", "render_pointer", "render_projection", "scan_private_shapes", "validate_note"}
#: registry の正準 digest（P13-A0 で確定 ・A3 ・roadmap の記録 ・A4a で更新。runtime ・認可 ・test ・文書 ・package ・base の集合。drift はここで止まる）
P13_REGISTRY_DIGEST = "39a548fb163b8c53448d34fff92f04e742879a699b2cada13867579890458fb6"
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


def _allowed_tokens(path: str):
    """P13 の file が含んでよい凍結の package 名（P13-A2a の adapter の `personal_intelligence` だけ）。"""
    return ["personal_intelligence"] if path in SANCTIONED_P13_P10_IMPORTERS else []


def _git_blob_of(data: bytes) -> str:
    """作業木の byte の git の blob の id（`git hash-object` と同じ ・書き込みは無い）。"""
    return hashlib.sha1(b"blob %d\0" % len(data) + data).hexdigest()


# ================================================ registry ・drift ・認可


def test_p13_a0_registry_is_exactly_the_reviewed_registration_and_runtime_is_empty() -> None:
    assert P13_BASE == "aded7ee8621e9abac18d313009444675ab771ae6"                                  # 固定の base（A0 の commit ではない）
    assert _git("merge-base", "--is-ancestor", P13_BASE, "HEAD") == ""
    assert len(PHASE13_A1_RUNTIME) == 4 and PHASE13_A2A_RUNTIME == (ADAPTER,)                       # A1: model 4 file ・A2a: adapter 1 file
    assert PHASE13_A3_RUNTIME == (BUILD_MODULE, GENERATION_MODULE, STORE_MODULE)                      # A3: store ／ rebuild の 3 file
    assert PHASE13_A4A_RUNTIME == (PROJECTION_MODULE,)                                               # A4a: 純粋な投影の model 1 file
    assert PHASE13_RUNTIME == tuple(sorted(PHASE13_A1_RUNTIME + PHASE13_A2A_RUNTIME + PHASE13_A3_RUNTIME + PHASE13_A4A_RUNTIME))
    assert len(PHASE13_RUNTIME) == 9
    assert P13_A1 == "ccfc8e57885fabc5936a39034a9e816c66b2fbbc"
    assert P13_A2A == "12de956637bb1df5fcff8846ba9d7fcb606421a3"
    assert P13_A3 == "12dcfb2143527ca44a3e55afa7a2daa9bab2c33d"
    assert PHASE13_RUNTIME_AUTHORIZATION == (("P13-A1", P13_A0, PHASE13_A1_RUNTIME, A1_DOC),
                                             ("P13-A2a", P13_A1, PHASE13_A2A_RUNTIME, A2A_DOC),
                                             ("P13-A3", P13_A2A, PHASE13_A3_RUNTIME, A3_DOC),
                                             ("P13-A4a", P13_ROADMAP, PHASE13_A4A_RUNTIME, A4A_DOC))
    assert dict(SANCTIONED_P13_P10_IMPORTERS) == {ADAPTER: SANCTIONED_P13_P10_IMPORTS}                # importer は adapter だけ
    assert {m: set(n) for m, n in SANCTIONED_P13_P10_IMPORTS.items()} == {
        "..personal_intelligence.p9_view": {"P9ViewError", "read_p9_safe_view"},
        "..personal_intelligence.personal_projection": {"personal_safe_projection"},
        "..personal_intelligence.review_view": {"ReviewViewError", "read_personal_review"}}               # P11 と同じ 5 つの名前
    assert set(SANCTIONED_P13_MODULES) == set(PHASE13_RUNTIME)
    assert PHASE13_PACKAGE == "src/intelligence/market_memory" and ADDITION_STATUSES == ("A", "??")
    assert PHASE13_TESTS == ("tests/intelligence/phase13_runtime_registry.py", "tests/intelligence/test_market_memory_boundary.py",
                             "tests/intelligence/test_market_memory_model.py", "tests/intelligence/test_market_memory_governed_source.py",
                             "tests/intelligence/test_market_memory_generation.py", "tests/intelligence/test_market_memory_store.py",
                             "tests/intelligence/test_market_memory_build.py", "tests/intelligence/test_market_memory_projection.py")
    assert PHASE13_DOCS == (A0_DOC, A1_DOC, A2A_DOC, A3_DOC, ROADMAP_DOC, A4A_DOC)
    assert set(SANCTIONED_P13_EXTRA_STDLIB) == set(P13_NAME_ALLOWANCES) == set(P13_WORD_ALLOWANCES) == {STORE_MODULE}   # 許しは store だけ
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
        importer_lines = [line for line in added if "SANCTIONED_P13" in line]
        if path == P10_IMPORTER_GUARD:                                                               # P13-A2a: P10 の guard の 5 行だけ
            assert set(PHASE13_A2A_IMPORTER_LINES) <= set(added), path
            assert set(importer_lines) <= set(PHASE13_A2A_IMPORTER_LINES), path
        else:
            assert importer_lines == [], path                                                        # 他の凍結の test に importer の許可は無い
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
    return _imports_text(path.read_text(encoding="utf-8"))


def _imports_text(text: str):
    relative, absolute = {}, set()
    for node in ast.walk(ast.parse(text)):
        if isinstance(node, ast.ImportFrom) and node.level:
            relative.setdefault("." * node.level + (node.module or ""), set()).update(a.name for a in node.names)
        elif isinstance(node, ast.ImportFrom):
            absolute.add(node.module)
        elif isinstance(node, ast.Import):
            absolute.update(a.name for a in node.names)
    return relative, absolute


def _import_violations(path: str, text: str) -> list:
    """stdlib の allowlist（file ごとの追加だけ）・相対 import の完全一致 ・凍結の phase への到達 ・禁止の token ・private の形。"""
    relative, absolute = _imports_text(text)
    allowed = SANCTIONED_P13_STDLIB | SANCTIONED_P13_EXTRA_STDLIB.get(path, set())
    found = [("STDLIB", m) for m in sorted(absolute - allowed)]
    if set(relative) != SANCTIONED_P13_MODULES.get(path, set()):
        found.append(("RELATIVE", tuple(sorted(set(relative) ^ SANCTIONED_P13_MODULES.get(path, set())))))
    cross = {m: n for m, n in relative.items() if m.startswith("..")}
    if cross != {m: set(n) for m, n in SANCTIONED_P13_P10_IMPORTERS.get(path, {}).items()}:   # adapter だけ ・完全一致
        found.append(("CROSS", tuple(sorted(cross))))
    if _forbidden_tokens_in(text) != _allowed_tokens(path):
        found.append(("TOKEN", tuple(_forbidden_tokens_in(text))))
    found += [("PRIVATE", pattern) for pattern in PRIVATE_PATTERNS if re.search(pattern, text)]
    if "__main__" in text or "import sys" in text or ("import os" in text and "os" not in SANCTIONED_P13_EXTRA_STDLIB.get(path, set())):
        found.append(("ENTRY_OR_OS", path))
    return found


def test_p13_a1_runtime_imports_are_stdlib_only_and_never_reach_frozen_phases() -> None:
    for path in PHASE13_RUNTIME:
        assert _import_violations(path, (REPO_ROOT / path).read_text(encoding="utf-8")) == [], path


def _guard_violations(path: str, text: str) -> list:
    """file ・OS ・時計 ・環境 ・process ・network の名前 ・投資 ／ 時計の相対の語彙 ・広い except（store の file ごとの許しだけを引く）。"""
    banned = FORBIDDEN_NAMES - P13_NAME_ALLOWANCES.get(path, set())
    found, identifiers = [], set()
    for node in ast.walk(ast.parse(text)):
        if isinstance(node, ast.Name):
            found += [("NAME", node.id)] if node.id in banned else []
            identifiers.add(node.id)
        elif isinstance(node, ast.Attribute):
            found += [("NAME", node.attr)] if node.attr in banned else []
            identifiers.add(node.attr)
        elif isinstance(node, ast.arg):
            identifiers.add(node.arg)
        elif isinstance(node, (ast.FunctionDef, ast.ClassDef)):
            identifiers.add(node.name)
        elif isinstance(node, ast.ExceptHandler):
            names = set() if node.type is None else {node.type.id} if isinstance(node.type, ast.Name) else {
                e.id for e in getattr(node.type, "elts", ()) if isinstance(e, ast.Name)}
            found += [("EXCEPT", "BROAD")] if node.type is None or names & {"Exception", "BaseException"} else []
    words = set()
    for name in identifiers:
        words |= {w.lower() for w in re.findall(r"[A-Z]?[a-z]+|[A-Z]+(?![a-z])", name)}
    return found + [("WORD", w) for w in sorted(words & (FORBIDDEN_WORDS - P13_WORD_ALLOWANCES.get(path, set())))]


def test_p13_a1_runtime_never_touches_files_env_clock_process_or_network_and_has_no_investment_vocabulary() -> None:
    for path in PHASE13_RUNTIME:
        assert _guard_violations(path, (REPO_ROOT / path).read_text(encoding="utf-8")) == [], path


def test_p13_a1_the_model_record_is_design_and_runtime_consistent_and_holds_no_private_values() -> None:
    text = (REPO_ROOT / A1_DOC).read_text(encoding="utf-8")
    for needle in ("P13-A1", "Review State Memory", "p13smp_", "p13chg_", "SampleCutoff", "SourceViewIdentity", "ReviewStateEntry",
                   "ReviewStateCounts", "ReviewStateSample", "ReviewStateChange", "SampleEvidence", "SampleOutcome", "StalenessLabel",
                   "PitState", "known_at", "reviewed_at", "捏造しない", "端点の差", "変化の不在", "MISSING", "INTEGRITY_FAILURE",
                   "空の標本", "telemetry", "SHORT_ID_COLLISION", "合成の入力", "凍結の package を import しない", "P13-A2a",
                   "importer の許可は無い", "store ・永続化 ・manifest は無い", P13_A0, *[Path(p).name for p in PHASE13_A1_RUNTIME]):
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
    for path in PHASE13_RUNTIME:                                                                     # P13 の code の走査（adapter だけ P10 の名前）
        text = (REPO_ROOT / path).read_text(encoding="utf-8")
        assert _forbidden_tokens_in(text) == _allowed_tokens(path), path
    with pytest.raises(AssertionError):
        assert _forbidden_tokens_in("from ..personal_intelligence.review_view import read_personal_review") == []


# ================================================ P13-A2a: A1 の blob の pin ・importer の負の control ・文書


def test_p13_a2a_the_accepted_a1_runtime_is_object_identical_to_the_a1_anchor_in_head_index_and_worktree() -> None:
    assert _git("merge-base", "--is-ancestor", P13_A1, "HEAD") == ""
    anchored = _blobs(P13_A1, PHASE13_A1_RUNTIME)
    assert set(anchored) == set(PHASE13_A1_RUNTIME)                                                 # 4 file 全てが anchor に在る
    assert _blobs("HEAD", PHASE13_A1_RUNTIME) == anchored                                           # commit 済みの修正は無い
    index = {line.split("\t", 1)[1]: line.split()[1] for line in _git("ls-files", "-s", "--", *PHASE13_A1_RUNTIME).splitlines()}
    assert index == anchored                                                                        # index の修正は無い
    worktree = {path: _git_blob_of((REPO_ROOT / path).read_bytes()) for path in PHASE13_A1_RUNTIME}
    assert worktree == anchored                                                                     # 作業木の修正は無い
    for path in PHASE13_A1_RUNTIME:                                                                 # negative control: 1 byte の変化で一致しない
        assert _git_blob_of((REPO_ROOT / path).read_bytes() + b"#") != anchored[path], path
    assert _git_blob_of(b"") == "e69de29bb2d1d6434b8b29ae775ad8c2e48c5391"                          # git の空 blob と同じ計算


def test_p13_a2a_only_the_adapter_reaches_p10_and_any_other_import_surface_is_rejected() -> None:
    relative, _ = _imports(REPO_ROOT / ADAPTER)
    sanctioned = {m: set(n) for m, n in SANCTIONED_P13_P10_IMPORTS.items()}
    cross = {m: n for m, n in relative.items() if m.startswith("..")}
    assert cross == sanctioned
    for path in PHASE13_A1_RUNTIME:
        assert not any(m.startswith("..") for m in _imports(REPO_ROOT / path)[0]), path            # A1 は凍結の phase に届かない
    variants = (
        {**sanctioned, "..personal_intelligence.p9_view": sanctioned["..personal_intelligence.p9_view"] | {"read_p9_private_snapshot"}},
        {**sanctioned, "..personal_intelligence.profile_store": {"ProfileStore"}},
        {**sanctioned, "..watchlist_thesis_intelligence.watch_store": {"WatchlistStore"}},
        {**sanctioned, "..personal_ui.p10_read_adapter": {"read_ui_model"}},
        {m: n for m, n in sanctioned.items() if m != "..personal_intelligence.personal_projection"},
    )
    for variant in variants:
        assert variant != sanctioned                                                                  # 名前 ・module の追加 ／ 欠落は一致しない
    assert set(SANCTIONED_P13_P10_IMPORTERS) == {ADAPTER}
    assert "src/intelligence/market_memory/review_state_sample.py" not in SANCTIONED_P13_P10_IMPORTERS   # 別の importer は無い
    text = (REPO_ROOT / ADAPTER).read_text(encoding="utf-8")
    assert "outcome_for_source_failure" not in text.split('"""', 2)[2]                              # 生の P10 の code を A1 の写像に渡さない
    assert "SampleEvidence" not in text.split('"""', 2)[2] and "sampled_at" not in text.split('"""', 2)[2]   # telemetry を作らない
    init = REPO_ROOT / PHASE13_PACKAGE / "__init__.py"
    assert _imports(init) == ({}, set()) and "governed_review_source" not in init.read_text(encoding="utf-8")   # __init__ は adapter を出さない
    assert not any("market_memory" in module for module in runtime_closure())


def test_p13_a2a_the_adapter_record_states_the_contract_limits_and_holds_no_private_values() -> None:
    text = (REPO_ROOT / A2A_DOC).read_text(encoding="utf-8")
    for needle in ("P13-A2a", ADAPTER, "sample_review_state", "read_personal_review", "read_p9_safe_view", "personal_safe_projection",
                   "ReviewViewError", "P9ViewError", "SANCTIONED_P13_P10_IMPORTERS", "P13_A1", P13_A1, "MISSING", "INTEGRITY_FAILURE",
                   "P9_STORE_MISSING", "P10_STORE_MISSING", "P9_STORE_CORRUPTION", "P10_STORE_CORRUPTION", "SOURCE_CHANGED_DURING_READ",
                   "SOURCE_INPUT_REJECTED", "SOURCE_READ_UNCLASSIFIED", "VIEW_SCHEMA_UNSUPPORTED", "VIEW_CLASS_UNSUPPORTED",
                   "VIEW_AS_OF_MISMATCH", "ADAPTER_INPUT_INVALID", "outcome_for_source_failure", "ABA", "不可分", "SampleEvidence",
                   "known_at", "reviewed_at", "捏造しない", "合成の一時 root", "importer", "P13-A3", "B-track は HOLD"):
        assert needle in text, needle
    for banned in ("P13 は完了", "Phase 13 は完了", "atomic な snapshot を保証", "署名済み", "最新の", "推奨する銘柄", "D:\\", "0.0.0.0",
                   "http://", "https://"):
        assert banned not in text, banned
    assert not re.search(r"\b(?:is|are|was|were|been)\s+(?:digitally\s+|cryptographically\s+)?signed\b", text, re.IGNORECASE)
    for pattern in PRIVATE_PATTERNS:
        assert not re.search(pattern, text), pattern


# ================================================ P13-A3: A2a の blob の pin ・store だけの I/O ・狭い削除 ・negative control ・文書


def _deletion_sites(text: str) -> list:
    """削除 ・切り詰めの名前の出現を、囲む関数の名前と組で返す（module の直下は `<module>`）。"""
    sites = []

    def visit(node: ast.AST, owner: str) -> None:
        for child in ast.iter_child_nodes(node):
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                visit(child, child.name)
                continue
            name = child.id if isinstance(child, ast.Name) else child.attr if isinstance(child, ast.Attribute) else None
            if name in P13_DELETION_NAMES:
                sites.append((owner, name))
            visit(child, owner)
    visit(ast.parse(text), "<module>")
    return sites


def _callers_of(text: str, function: str) -> set:
    callers = set()
    for node in ast.walk(ast.parse(text)):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name != function:
            if any(isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id == function for n in ast.walk(node)):
                callers.add(node.name)
    return callers


def _os_attribute_violations(text: str) -> list:
    found = []
    for node in ast.walk(ast.parse(text)):
        if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name) and node.value.id == "os":
            found += [] if node.attr in SANCTIONED_P13_OS_ATTRIBUTES else [node.attr]
        elif (isinstance(node, ast.Attribute) and isinstance(node.value, ast.Attribute) and node.value.attr == "path"
              and isinstance(node.value.value, ast.Name) and node.value.value.id == "os"):
            found += [] if node.attr in SANCTIONED_P13_OS_PATH_ATTRIBUTES else ["path." + node.attr]
        elif (isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "getattr" and node.args
              and isinstance(node.args[0], ast.Name) and node.args[0].id == "os"):
            literal = node.args[1].value if len(node.args) > 1 and isinstance(node.args[1], ast.Constant) else None
            found += [] if literal in SANCTIONED_P13_OS_GETATTR else ["getattr"]
    return found


def _os_call_sites(text: str) -> dict:
    """`os.<名前>` の出現を、囲む関数の名前の集合で返す（module の直下は `<module>`）。"""
    sites: dict = {}

    def visit(node: ast.AST, owner: str) -> None:
        for child in ast.iter_child_nodes(node):
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                visit(child, child.name)
                continue
            if isinstance(child, ast.Attribute) and isinstance(child.value, ast.Name) and child.value.id == "os":
                sites.setdefault(child.attr, set()).add(owner)
            visit(child, owner)
    visit(ast.parse(text), "<module>")
    return sites


def _store_surface(text: str) -> tuple:
    tree = ast.parse(text)
    functions = {n.name for n in tree.body if isinstance(n, ast.FunctionDef) and not n.name.startswith("_")}
    store_class = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == "MemoryStore")
    methods = {m.name for m in store_class.body if isinstance(m, ast.FunctionDef) and not m.name.startswith("_")}
    return functions, methods


def _public_surface_violations(name_status: str) -> list:
    """公開 ・凍結の面（Pages ・workflow ・config ・scripts ・main ・報告 ・通知）への変更の行。"""
    return [line for line in name_status.splitlines()
            if any(line.split("\t")[-1] == root or line.split("\t")[-1].startswith(root + "/") for root in FROZEN_SURFACE)]


def test_p13_a3_the_accepted_a2a_adapter_is_object_identical_to_the_a2a_anchor_in_head_index_and_worktree() -> None:
    assert _git("merge-base", "--is-ancestor", P13_A2A, "HEAD") == ""
    for anchor, runtime in ((P13_A2A, PHASE13_A2A_RUNTIME), (P13_A2A, PHASE13_A1_RUNTIME), (P13_A1, PHASE13_A1_RUNTIME)):
        anchored = _blobs(anchor, runtime)
        assert set(anchored) == set(runtime), anchor                                                 # 全てが anchor に在る
        assert _blobs("HEAD", runtime) == anchored, anchor                                           # commit 済みの修正は無い
        index = {line.split("\t", 1)[1]: line.split()[1] for line in _git("ls-files", "-s", "--", *runtime).splitlines()}
        assert index == anchored, anchor                                                             # index の修正は無い
        worktree = {path: _git_blob_of((REPO_ROOT / path).read_bytes()) for path in runtime}
        assert worktree == anchored, anchor                                                          # 作業木の修正は無い
    for path in PHASE13_A3_RUNTIME:
        assert not _git("ls-tree", P13_A2A, "--", path).strip(), path                                # A3 の file は A2a の anchor に無かった


def test_p13_a3_only_the_store_has_filesystem_capabilities_and_deletion_is_confined_to_owned_lock_and_temp_release() -> None:
    for path in PHASE13_RUNTIME:
        text = (REPO_ROOT / path).read_text(encoding="utf-8")
        if path == STORE_MODULE:
            assert _deletion_sites(text) == P13_UNLINK_SITES                                          # unlink は 1 箇所だけ
            assert _callers_of(text, "_unlink_if_owned") == P13_UNLINK_CALLERS                       # lock の解放 ・pointer の一時 file だけ
            body = next(n for n in ast.walk(ast.parse(text)) if isinstance(n, ast.FunctionDef) and n.name == "_unlink_if_owned")
            calls = sorted((n.lineno, n.col_offset, n.func.id) for n in ast.walk(body) if isinstance(n, ast.Call)
                           and isinstance(n.func, ast.Name))
            assert calls[0][2] == "_owned"                                                           # 所有の検証が先（source の順）
            assert _os_attribute_violations(text) == []
            sites = _os_call_sites(text)
            assert {name: sites.get(name, set()) for name in P13_OS_CALL_SITES} == P13_OS_CALL_SITES  # 危険な呼び出しの場所は完全一致
            assert _store_surface(text) == (P13_STORE_PUBLIC_FUNCTIONS, P13_STORE_PUBLIC_METHODS)    # lock の回復 ・奪取の面は無い
            assert _callers_of(text, "preserve_interrupted_staging") == _callers_of(text, "preserve_publication_pointer") == set()
            preserve_callers = {n.name for n in ast.walk(ast.parse(text)) if isinstance(n, ast.FunctionDef) and any(
                isinstance(c, ast.Attribute) and c.attr == "_preserve" for c in ast.walk(n))}
            assert preserve_callers == P13_PRESERVE_CALLERS                                           # 移動は明示の回復の 2 つだけ
            lock_users = {n.name for n in ast.walk(ast.parse(text)) if isinstance(n, ast.FunctionDef) and any(
                isinstance(c, ast.Name) and c.id == "WRITER_LOCK_NAME" for c in ast.walk(n))}
            assert lock_users == {"acquire_writer_lock", "_check_layout_entries"}                    # lock の場所を触るのは取得と layout だけ
        else:
            assert _deletion_sites(text) == [], path                                                  # 他の file に削除は無い
            assert "os" not in _imports_text(text)[1] and "stat" not in _imports_text(text)[1], path     # store の外に filesystem は無い
            assert path not in P13_NAME_ALLOWANCES and path not in P13_WORD_ALLOWANCES, path
    build = (REPO_ROOT / BUILD_MODULE).read_text(encoding="utf-8")
    assert "preserve" not in build                                                                  # build は回復を呼ばない
    used = {n.attr for n in ast.walk(ast.parse(build)) if isinstance(n, ast.Attribute) and isinstance(n.value, ast.Name)
            and n.value.id in ("store", "lock")}
    assert used == {"check_disjoint", "acquire_writer_lock", "check_writable", "read_publication", "record_attempt",
                    "publish_generation", "release"}                                                 # build は store の狭い面だけ
    assert not any(name.startswith("_") for name in used)


def test_p13_a3_negative_controls_reject_new_files_modifications_imports_deletion_io_blob_and_registry_drift() -> None:
    for status in ("A", "??", "M"):                                                                   # 未登録の runtime ・既存の修正
        assert not is_phase13_addition(status, f"{PHASE13_PACKAGE}/memory_cleanup.py")
        assert not is_phase13_addition(status, f"{PHASE13_PACKAGE}/obsidian_export.py")
    for path in PHASE13_RUNTIME:
        assert not is_phase13_addition("M", path), path
    store = (REPO_ROOT / STORE_MODULE).read_text(encoding="utf-8")
    build = (REPO_ROOT / BUILD_MODULE).read_text(encoding="utf-8")
    frozen_import = build + "\nfrom ..personal_intelligence.review_view import read_personal_review\n"   # 凍結の import
    kinds = {kind for kind, _ in _import_violations(BUILD_MODULE, frozen_import)}
    assert {"RELATIVE", "CROSS", "TOKEN"} <= kinds
    general_delete = store + "\n\ndef delete_generation(location):\n    os.rmdir(location)\n    os.unlink(location)\n"   # 一般の削除
    assert _deletion_sites(general_delete) != P13_UNLINK_SITES
    assert ("delete_generation", "rmdir") in _deletion_sites(general_delete)
    assert _deletion_sites(store.replace("_owned(location, identity, data)", "True", 1)) == P13_UNLINK_SITES
    assert "shutil" not in SANCTIONED_P13_STDLIB | SANCTIONED_P13_EXTRA_STDLIB[STORE_MODULE]
    assert ("STDLIB", "shutil") in _import_violations(STORE_MODULE, store + "\nimport shutil\n")
    assert sorted(_os_attribute_violations("import os\nos.remove(x)\nos.system(x)\ngetattr(os, 'unlink')\n")) == ["getattr", "remove", "system"]
    io_outside = build + "\nimport os\n\ndef sneak(location):\n    return os.open(location, 0)\n"     # store の外の I/O
    assert ("NAME", "open") in _guard_violations(BUILD_MODULE, io_outside)
    assert ("STDLIB", "os") in _import_violations(BUILD_MODULE, io_outside)
    assert ("NAME", "open") in _guard_violations(GENERATION_MODULE, "def f(x):\n    return open(x)\n")
    assert _guard_violations(STORE_MODULE, "def f(x):\n    return x.exists()\n") == [("NAME", "exists")]   # store の許しも完全一致
    stat_elsewhere = store + "\n\ndef peek(location):\n    return os.stat(location)\n"              # os.stat の場所の拡大
    assert _os_call_sites(stat_elsewhere)["stat"] != P13_OS_CALL_SITES["stat"]
    takeover = store + "\n\ndef preserve_writer_lock(store):\n    return store\n"                  # lock の奪取の面の追加
    assert _store_surface(takeover)[0] != P13_STORE_PUBLIC_FUNCTIONS
    overwrite = store.replace("def _publish_pointer(", "def _publish_pointer_unused(self):\n        os.replace('a', 'b')\n\n    def _publish_pointer(", 1)
    assert _os_call_sites(overwrite)["replace"] != P13_OS_CALL_SITES["replace"]                      # 置換の場所の拡大
    for anchor, runtime in ((P13_A1, PHASE13_A1_RUNTIME), (P13_A2A, PHASE13_A2A_RUNTIME)):          # A1 ・A2a の blob の変化
        anchored = _blobs(anchor, runtime)
        for path in runtime:
            assert _git_blob_of((REPO_ROOT / path).read_bytes() + b"\n") != anchored[path], path
    drifted = (
        [*PHASE13_RUNTIME_AUTHORIZATION[:2], ("P13-A3", P13_A1, PHASE13_A3_RUNTIME, A3_DOC)],         # anchor の drift
        [*PHASE13_RUNTIME_AUTHORIZATION[:2], ("P13-A3", P13_A2A, PHASE13_A3_RUNTIME[:2], A3_DOC)],    # path の欠落
        [*PHASE13_RUNTIME_AUTHORIZATION, ("P13-A3b", P13_A2A, (f"{PHASE13_PACKAGE}/memory_cleanup.py",), A3_DOC)],
    )
    for authorization in drifted:
        payload = {"runtime": list(PHASE13_RUNTIME), "tests": list(PHASE13_TESTS), "docs": list(PHASE13_DOCS), "package": PHASE13_PACKAGE,
                   "base": P13_BASE, "authorization": [[g, a, list(p), d] for g, a, p, d in authorization]}
        canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        assert hashlib.sha256(("p13.registry.v1\0" + canonical).encode("utf-8")).hexdigest() != P13_REGISTRY_DIGEST
    assert _public_surface_violations("M\tdocs/pages/index.html\nA\tsrc/intelligence/market_memory/memory_store.py") == [
        "M\tdocs/pages/index.html"]                                                                  # 公開の面の変更は落ちる
    assert _public_surface_violations("M\t.github/workflows/x.yml\nM\tconfig.yaml") == ["M\t.github/workflows/x.yml", "M\tconfig.yaml"]
    assert _public_surface_violations(_git("diff", "--cached", "--name-status", P13_BASE)) == []      # 実際の差に公開の面は無い
    assert _public_surface_violations(_git("status", "--porcelain").replace(" ", "\t")) == []


def test_p13_a3_the_store_record_states_the_contract_limits_and_holds_no_private_values() -> None:
    text = (REPO_ROOT / A3_DOC).read_text(encoding="utf-8")
    for needle in ("P13-A3", *PHASE13_A3_RUNTIME, "plan digest", "generation digest", "manifest digest", "publication.json", "REUSED",
                   "INCOMPLETE", "attempts/", "writer lock", "O_EXCL", "_unlink_if_owned", "preserve_interrupted_staging",
                   "preserve_publication_pointer", "POINTER_VERIFIED_NOT_PRESERVED", "PUBLICATION_STATE_UNCERTAIN",
                   "lock の回復 ・奪取の API は無い", "置き換えない", "not race-proof", "ACL の privacy は未検証", "NTFS",
                   "rename だけでは公開の成功ではない", "TOCTOU", "junction",
                   "reparse point", "ACL", "P13-A5", "同期", "網羅ではない", "ABA", "不可分", "telemetry", "sampled_at",
                   "P13_A2A", P13_A2A, "P13_A1", "Obsidian", "export は無い", "B-track は HOLD", "MISSING", "INTEGRITY_FAILURE",
                   "SCHEMA_UNSUPPORTED", "NOT_PUBLISHED", "STAGING_PRESENT", "UNAUTHORIZED_ENTRY", "ROOT_IDENTITY_MISMATCH",
                   "WRITER_LOCK_PRESENT", "STALE", "合成の一時 root"):
        assert needle in text, needle
    for banned in ("P13 は完了", "Phase 13 は完了", "完全性を保証する", "不可分を保証する", "全ての同期", "すべての同期", "署名済み",
                   "最新の", "推奨する銘柄", "D:\\", "0.0.0.0", "http://", "https://", "preserve_writer_lock", "race-proof である"):
        assert banned not in text, banned
    assert not re.search(r"\b(?:is|are|was|were|been)\s+(?:digitally\s+|cryptographically\s+)?signed\b", text, re.IGNORECASE)
    for pattern in PRIVATE_PATTERNS:
        assert not re.search(pattern, text), pattern
    from src.intelligence.market_memory.memory_generation import (ATTEMPT_SCHEMA_VERSION, GENERATION_SCHEMA_VERSION,
                                                                  MANIFEST_SCHEMA_VERSION, MEMORY_RULES_VERSION,
                                                                  PUBLICATION_SCHEMA_VERSION, STORE_SCHEMA_VERSION)
    for version in (STORE_SCHEMA_VERSION, MEMORY_RULES_VERSION, GENERATION_SCHEMA_VERSION, MANIFEST_SCHEMA_VERSION,
                    PUBLICATION_SCHEMA_VERSION, ATTEMPT_SCHEMA_VERSION):
        assert version in text, version


# ================================================ Market Brain の roadmap の記録（文書だけ ・実装を承認しない）


def test_the_market_brain_roadmap_record_is_design_only_preserves_the_anchors_and_holds_no_private_values() -> None:
    text = (REPO_ROOT / ROADMAP_DOC).read_text(encoding="utf-8")
    for needle in ("MARKET BRAIN ROADMAP RECORD", "いかなる runtime の実装も承認しない", "いかなる将来の runtime の実装も承認しない",
                   "[VERIFIED CODE]", "[FROZEN CONTRACT]", "[APPROVED VISION]", "[PROPOSED DESIGN]", "[OPEN DECISION]",
                   "public の legacy production", "parked な vNext", "隔離された governed な P5 〜 P13", "将来の private な Market Brain の実行",
                   "SOURCE EVIDENCE", "MEMORY", "KNOWLEDGE GRAPH", "RETRIEVAL", "ANALYSIS", "EVALUATION", "CONTROLLED IMPROVEMENT",
                   "OBSIDIAN PROJECTION", "P13-E", "P13-K", "P13-R", "P14-I", "P14-V", "P14-L", "P12-B0", "L0", "Context Pack",
                   "legacy の `main.py` には自動で取り込まない", "公開の gate なしに", "凍結の P4 は承認なしに再開しない", "類似度 ・共起だけの edge は無い",
                   "MODEL_PROPOSED", "CONTESTED", "as-of の cutoff", "引用の trace", "将来の日付の囮", "循環の自己確認の防止",
                   "承認の無い全文の再現 ・保存はしない", "known_at", "credential custody", "過去の予測は保存する", "先読み無し",
                   "自律の production の規則の変更は無い", "counts-only", "Markdown は system の authority ではない", "決して自動で取り込まない",
                   "theme_learning.py", "変更しない ・無効にしない", "暫定", "期日 ・約束ではない", "P13-A4 の証拠の root",
                   "回復の状態機械", "private ／ public の実行の分離", "P14 の評価と release の統治",
                   P13_A1[:7], P13_A2A[:7], "12dcfb2143527ca44a3e55afa7a2daa9bab2c33d", "0a32d86", "4c19701", "1a7b9a2", "43c0b85", "e390cdd",
                   "2d18133"):
        assert needle in text, needle
    for banned in ("P13 は完了", "Phase 13 は完了", "P14 は完了", "実装を承認する", "実装済みの Knowledge Graph", "推奨する銘柄", "最新の",
                   "署名済み", "D:\\", "0.0.0.0", "http://", "https://"):
        assert banned not in text, banned
    assert not re.search(r"\b(?:is|are|was|were|been)\s+(?:digitally\s+|cryptographically\s+)?signed\b", text, re.IGNORECASE)
    for pattern in PRIVATE_PATTERNS:
        assert not re.search(pattern, text), pattern
    assert _git("merge-base", "--is-ancestor", "12dcfb2143527ca44a3e55afa7a2daa9bab2c33d", "HEAD") == ""   # 記録の基準の HEAD は祖先


# ================================================ P13-A4a: A3 の blob の pin ・純粋な投影の model（I/O 無し）・negative control ・文書


def _projection_violations(text: str) -> list:
    """P13-A4a: 投影の model の import の面 ・I/O ／ 動的実行の名前 ・項目 ／ 瞬間の属性の読み ・module の直下の副作用。"""
    tree = ast.parse(text)
    relative, absolute = _imports_text(text)
    found = [("STDLIB", m) for m in sorted(absolute - P13_PROJECTION_STDLIB)]
    found += [("RELATIVE", m) for m in sorted(set(relative) - SANCTIONED_P13_MODULES[PROJECTION_MODULE])]
    for node in ast.walk(tree):
        if isinstance(node, ast.Name) and node.id in P13_PROJECTION_FORBIDDEN_NAMES:
            found.append(("NAME", node.id))
        elif isinstance(node, ast.Attribute) and node.attr in P13_PROJECTION_UNREAD_ATTRIBUTES:
            found.append(("ATTRIBUTE", node.attr))
    for index, statement in enumerate(tree.body):
        if isinstance(statement, (ast.Import, ast.ImportFrom, ast.FunctionDef, ast.ClassDef)):
            continue
        if index == 0 and isinstance(statement, ast.Expr) and isinstance(statement.value, ast.Constant):
            continue                                                                                 # module の docstring
        if isinstance(statement, (ast.Assign, ast.AnnAssign)):
            calls = {n.func.attr if isinstance(n.func, ast.Attribute) else n.func.id if isinstance(n.func, ast.Name) else "?"
                     for n in ast.walk(statement) if isinstance(n, ast.Call)}
            found += [("MODULE_CALL", name) for name in sorted(calls - P13_PROJECTION_MODULE_CALLS)]
            continue
        found.append(("MODULE_STATEMENT", type(statement).__name__))
    return found


def test_p13_a4a_the_accepted_a1_a2a_and_a3_runtime_is_object_identical_to_the_anchors_in_head_index_and_worktree() -> None:
    for anchor in (P13_A3, P13_ROADMAP):
        assert _git("merge-base", "--is-ancestor", anchor, "HEAD") == "", anchor
    for anchor, runtime in ((P13_A3, PHASE13_A3_RUNTIME), (P13_ROADMAP, PHASE13_A3_RUNTIME), (P13_A3, PHASE13_A2A_RUNTIME),
                            (P13_A2A, PHASE13_A2A_RUNTIME), (P13_A3, PHASE13_A1_RUNTIME), (P13_A1, PHASE13_A1_RUNTIME)):
        anchored = _blobs(anchor, runtime)
        assert set(anchored) == set(runtime), anchor                                                 # 全てが anchor に在る
        assert _blobs("HEAD", runtime) == anchored, anchor                                           # commit 済みの修正は無い
        index = {line.split("\t", 1)[1]: line.split()[1] for line in _git("ls-files", "-s", "--", *runtime).splitlines()}
        assert index == anchored, anchor                                                             # index の修正は無い
        worktree = {path: _git_blob_of((REPO_ROOT / path).read_bytes()) for path in runtime}
        assert worktree == anchored, anchor                                                          # 作業木の修正は無い
    for revision in (P13_A3, P13_ROADMAP):
        assert not _git("ls-tree", revision, "--", *PHASE13_A4A_RUNTIME).strip(), revision           # A4a の file は anchor に無かった
    added = {("A", p) for p in PHASE13_A4A_RUNTIME}
    assert _changes("--name-status", P13_A3, "HEAD", "--", "src") <= added                           # A3 以後の src は A4a の追加だけ
    assert _changes("--cached", "--name-status", P13_A3, "--", "src") <= added


def test_p13_a4a_the_projection_model_is_io_free_side_effect_free_and_never_reads_entries_or_instants() -> None:
    text = (REPO_ROOT / PROJECTION_MODULE).read_text(encoding="utf-8")
    assert _projection_violations(text) == []
    assert _import_violations(PROJECTION_MODULE, text) == [] and _guard_violations(PROJECTION_MODULE, text) == []
    relative, absolute = _imports_text(text)
    assert absolute == P13_PROJECTION_STDLIB and P13_PROJECTION_STDLIB < SANCTIONED_P13_STDLIB
    assert set(relative) == SANCTIONED_P13_MODULES[PROJECTION_MODULE]
    assert not {".memory_store", ".memory_build", ".governed_review_source"} & set(relative)        # I/O の module ・adapter に届かない
    assert not any(m.startswith("..") for m in relative)                                             # 凍結の phase に届かない
    assert _deletion_sites(text) == []
    for allowances in (P13_NAME_ALLOWANCES, P13_WORD_ALLOWANCES, SANCTIONED_P13_EXTRA_STDLIB, SANCTIONED_P13_P10_IMPORTERS):
        assert PROJECTION_MODULE not in allowances                                                   # file ごとの許しは無い
    tree = ast.parse(text)
    assert {n.name for n in tree.body if isinstance(n, ast.FunctionDef) and not n.name.startswith("_")} == P13_PROJECTION_PUBLIC_FUNCTIONS
    from src.intelligence.market_memory.memory_projection import ProposedAction
    assert {a.value for a in ProposedAction} == {"NONE", "PREPARE_INTENT", "STAGE_VERSION", "MOVE_STAGED_TO_VERSION", "REPLACE_POINTER",
                                                 "RECORD_COMPLETION", "HOLD"}                       # 前の版を動かす action は無い
    assert not any("market_memory" in module for module in runtime_closure())                      # 本番の閉包の外
    for path in sorted((REPO_ROOT / "src").rglob("*.py")):                                          # 他の code は投影を import しない
        if path.relative_to(REPO_ROOT).as_posix() != PROJECTION_MODULE:
            assert "memory_projection" not in path.read_text(encoding="utf-8"), path.relative_to(REPO_ROOT).as_posix()
    assert "memory_projection" not in (REPO_ROOT / "main.py").read_text(encoding="utf-8")


def test_p13_a4a_negative_controls_reject_io_dynamic_execution_side_effects_entry_reads_importer_drift_and_blob_mutation() -> None:
    text = (REPO_ROOT / PROJECTION_MODULE).read_text(encoding="utf-8")
    for addition, violation in (("\nimport os\n", ("STDLIB", "os")), ("\nimport pathlib\n", ("STDLIB", "pathlib")),
                                ("\nimport io\n", ("STDLIB", "io")), ("\nimport socket\n", ("STDLIB", "socket")),
                                ("\nimport subprocess\n", ("STDLIB", "subprocess")), ("\nimport hashlib\n", ("STDLIB", "hashlib")),
                                ("\nfrom datetime import datetime\n", ("STDLIB", "datetime")),
                                ("\nfrom .memory_store import MemoryStore\n", ("RELATIVE", ".memory_store")),
                                ("\ndef sneak(x):\n    return __import__(x)\n", ("NAME", "__import__")),
                                ("\ndef sneak(x):\n    return getattr(x, 'y')\n", ("NAME", "getattr")),
                                ("\ndef sneak(x):\n    return compile(x, 'f', 'exec')\n", ("NAME", "compile")),
                                ("\ndef sneak(sample):\n    return sample.entries\n", ("ATTRIBUTE", "entries")),
                                ("\ndef sneak(cut):\n    return cut.at\n", ("ATTRIBUTE", "at")),
                                ("\ndef sneak(entry):\n    return entry.issuer_id\n", ("ATTRIBUTE", "issuer_id")),
                                ("\nSIDE = print('x')\n", ("MODULE_CALL", "print")), ("\nprint('x')\n", ("MODULE_STATEMENT", "Expr")),
                                ("\nfor _x in ():\n    pass\n", ("MODULE_STATEMENT", "For")),
                                ("\nif True:\n    VALUE = 1\n", ("MODULE_STATEMENT", "If"))):
        assert violation in _projection_violations(text + addition), addition
    assert ("NAME", "open") in _guard_violations(PROJECTION_MODULE, text + "\ndef sneak(x):\n    return open(x)\n")   # filesystem
    assert ("NAME", "exists") in _guard_violations(PROJECTION_MODULE, text + "\ndef sneak(x):\n    return x.exists()\n")
    assert ("NAME", "environ") in _guard_violations(PROJECTION_MODULE, text + "\ndef sneak(x):\n    return x.environ\n")   # 資格情報
    assert ("WORD", "cron") in _guard_violations(PROJECTION_MODULE, text + "\ndef cron_job():\n    pass\n")         # scheduler
    assert ("unlink" in {name for _, name in _deletion_sites(text + "\ndef sneak(x):\n    x.unlink()\n")})
    kinds = {kind for kind, _ in _import_violations(PROJECTION_MODULE, text + "\nfrom ..personal_intelligence.review_view import read_personal_review\n")}
    assert {"RELATIVE", "CROSS", "TOKEN"} <= kinds                                                   # 凍結の phase への import
    assert dict(SANCTIONED_P13_P10_IMPORTERS) == {ADAPTER: SANCTIONED_P13_P10_IMPORTS}                # importer の許可は不変（adapter だけ）
    assert {**SANCTIONED_P13_P10_IMPORTERS, PROJECTION_MODULE: SANCTIONED_P13_P10_IMPORTS} != dict(SANCTIONED_P13_P10_IMPORTERS)
    for anchor, runtime in ((P13_A1, PHASE13_A1_RUNTIME), (P13_A2A, PHASE13_A2A_RUNTIME), (P13_A3, PHASE13_A3_RUNTIME)):
        anchored = _blobs(anchor, runtime)
        for path in runtime:
            assert _git_blob_of((REPO_ROOT / path).read_bytes() + b"\n") != anchored[path], path      # 1 byte の変化で pin が外れる
    for status in ("A", "??", "M"):
        assert not is_phase13_addition(status, f"{PHASE13_PACKAGE}/projection_writer.py")             # A4b の writer は未登録
        assert not is_phase13_addition(status, f"{PHASE13_PACKAGE}/obsidian_vault.py")
    assert not is_phase13_addition("M", PROJECTION_MODULE)
    drifted = (
        [*PHASE13_RUNTIME_AUTHORIZATION[:3], ("P13-A4a", P13_A3, PHASE13_A4A_RUNTIME, A4A_DOC)],        # anchor の drift
        [*PHASE13_RUNTIME_AUTHORIZATION[:3], ("P13-A4a", P13_ROADMAP, (), A4A_DOC)],                   # path の欠落
        [*PHASE13_RUNTIME_AUTHORIZATION, ("P13-A4b", P13_ROADMAP, (f"{PHASE13_PACKAGE}/projection_writer.py",), A4A_DOC)],
    )
    for authorization in drifted:
        payload = {"runtime": list(PHASE13_RUNTIME), "tests": list(PHASE13_TESTS), "docs": list(PHASE13_DOCS), "package": PHASE13_PACKAGE,
                   "base": P13_BASE, "authorization": [[g, a, list(p), d] for g, a, p, d in authorization]}
        canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        assert hashlib.sha256(("p13.registry.v1\0" + canonical).encode("utf-8")).hexdigest() != P13_REGISTRY_DIGEST


def test_p13_a4a_the_projection_model_record_states_the_contract_and_holds_no_private_values() -> None:
    text = (REPO_ROOT / A4A_DOC).read_text(encoding="utf-8")
    for needle in ("P13-A4a", PROJECTION_MODULE, "Option C", ".p13-private-root", "memory/", "projection/", "契約は改めない",
                   "封じた A3 の子の", "build_projection_input", "SOURCE_ATTESTATION", "MemoryStore.read_generation", "ReadStatus.VERIFIED",
                   "D1", "D3 COUNTS ONLY", "D4 DATES ONLY", "D6", "D10", "D11", "known_at ではない", "PRIVATE_SHAPE_PATTERNS",
                   "validate_note", "APPROVED_CATEGORY_CODES", "CATEGORY_UNAPPROVED", "COUNT_OUT_OF_RANGE", "projection digest",
                   "export digest", "SHORT_ID_COLLISION", "MANIFEST_CONFLICT", "classify_publication", "check_recovery_proposal",
                   "FIRST_PUBLICATION", "PUBLISHED_VERIFIED", "NO_CHANGE", "INTENT_PREPARED", "STAGED_VERIFIED", "VERSION_VERIFIED",
                   "POINTER_SWITCHED", "FAIL_CLOSED", "AUTO_CONVERGE_ELIGIBLE", "HOLD_FAIL_CLOSED", "**存在しない**",
                   "PREVIOUS_VERSION_MISSING", "ORPHAN_STAGING", "UNREFERENCED_VERSION", "UNREFERENCED_MANIFEST", "POINTER_INVALID",
                   "OPEN ／ HOLD for A4b", "不可分な更新の証明ではない", "暗号の認証 ・署名ではない", "その場に残す", "容量",
                   "P13_A3", P13_A3, "P13_A2A", P13_A2A, "P13_A1", P13_A1, P13_ROADMAP, "本記録は A4b の実装を承認しない", "B-track は HOLD",
                   "runtime_closure", "合成の", "Windows", "Knowledge Graph ・Evidence Memory ・\nAI の叙述は無い"):
        assert needle in text, needle
    for banned in ("P13 は完了", "Phase 13 は完了", "A4 は完了", "A4b は完了", "署名済み", "最新の", "推奨する銘柄", "D:\\", "0.0.0.0",
                   "http://", "https://", "不可分を保証する", "原子的な更新を保証する", "store から読んだことを証明する", "archive する action を"):
        assert banned not in text, banned
    assert not re.search(r"\b(?:is|are|was|were|been)\s+(?:digitally\s+|cryptographically\s+)?signed\b", text, re.IGNORECASE)
    for pattern in PRIVATE_PATTERNS:
        assert not re.search(pattern, text), pattern
    from src.intelligence.market_memory import memory_projection as projection
    for version in (projection.PROJECTION_SCHEMA_VERSION, projection.PROJECTION_RULES_VERSION, projection.EXPORT_MANIFEST_SCHEMA_VERSION,
                    projection.POINTER_SCHEMA_VERSION, projection.INTENT_SCHEMA_VERSION, projection.COMPLETION_SCHEMA_VERSION,
                    projection.ABORT_SCHEMA_VERSION, projection.SOURCE_ATTESTATION, projection.PROJECTION_DOMAIN, projection.EXPORT_DOMAIN,
                    projection.INTERVAL_DOMAIN):
        assert version in text, version
