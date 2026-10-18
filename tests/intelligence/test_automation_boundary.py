"""P12-A1 〜 A5 — Phase 12（自動化）の境界の guard。

- registry の完全一致 ・P12_BASE 以後の面は登録した P12 の追加だけ ・凍結の P7 〜 P11 の test の差分は宣言した登録の行だけ。
- A1 の 11 file は `P12_A1` の commit と、A2 の 10 file は `P12_A2` の commit と object 一致。A2 ／ A3 の file が足して使う stdlib（git の読み取り ・private root の file ・loopback の
  probe ・network の拒否の guard）と凍結の P11 の read の面の import は、file ごとの完全一致で pin する。他は A1 と同じ純粋さ:
  時計 ・環境変数の値 ・乱数 ・network ・資格情報 ・free-form な payload ・投資の語彙は無い。CLI ・`__main__` も無い。
- 凍結の Phase 4 〜 11 の runtime は anchor と object 一致（P8 ・P9 ・P10 ・P11）・P12_BASE から不変（src 全体）。
"""
from __future__ import annotations

import ast
import re
import subprocess
from pathlib import Path

from tests.intelligence.phase7_runtime_registry import PHASE7_RUNTIME
from tests.intelligence.phase8_runtime_registry import P8_B5C, PHASE8_RUNTIME
from tests.intelligence.phase9_runtime_registry import P9_A5, PHASE9_RUNTIME
from tests.intelligence.phase10_runtime_registry import P10_A4, PHASE10_RUNTIME
from tests.intelligence.phase11_runtime_registry import P11_A5, PHASE11_RUNTIME
from tests.intelligence.phase12_runtime_registry import (FORBIDDEN_P12_IMPORT_PARTS, P12_A1, P12_A2, P12_A3, P12_A4, P12_A6, P12_BASE,
                                                         P12_VALIDATED_TREE,
                                                         PHASE12_A1_RUNTIME, PHASE12_A2_RUNTIME, PHASE12_A3_REOPENED_IN_A4,
                                                         PHASE12_A3_RUNTIME, PHASE12_A4_REOPENED_IN_A5, PHASE12_A4_REOPENED_IN_A6, PHASE12_A4_RUNTIME,
                                                         PHASE12_A5_RUNTIME,
                                                         PHASE12_DOCS, PHASE12_PACKAGE, PHASE12_RUNTIME,
                                                         PHASE12_TEST_REGISTRATION, PHASE12_TESTS,
                                                         SANCTIONED_P12_EXTRA_STDLIB, SANCTIONED_P12_MODULES,
                                                         SANCTIONED_P12_P11_IMPORTERS, SANCTIONED_P12_STDLIB,
                                                         is_phase12_addition, only_phase12_registration)
from tests.intelligence.test_p43b2c_production_bundle import runtime_closure

REPO_ROOT = Path(__file__).resolve().parents[2]
PACKAGE_DIR = REPO_ROOT / PHASE12_PACKAGE
CONTRACT_DOC = "docs/databank/PHASE12_A1_SCHEDULE_RUN_STATE_MODEL.md"
A2_CONTRACT_DOC = "docs/databank/PHASE12_A2_DETERMINISTIC_ORCHESTRATOR.md"
A3_CONTRACT_DOC = "docs/databank/PHASE12_A3_OPERATIONAL_COMMIT_LAYER.md"
A4_CONTRACT_DOC = "docs/databank/PHASE12_A4_LOCK_RETRY_RECOVERY.md"
A5_CONTRACT_DOC = "docs/databank/PHASE12_A5_WINDOWS_SCHEDULER.md"
P11_FREEZE_DOC = "docs/databank/PHASE11_FINAL_FREEZE.md"
FREEZE_DOC = "docs/databank/PHASE12_FINAL_FREEZE.md"
#: 凍結の記録に在ってはならない private な値の形（A1 の形 ＋ Windows の SID ・user profile の path ・validation の slot の時刻）
FREEZE_DOC_PRIVATE_PATTERNS = (r"S-1-5-\d", r"C:\\Users", r"\\Users\\", r"\b[0-2]\d:[0-5]\d\b", r"JQUANTS_", r"human:")
FROZEN_SURFACE = ("knowledge", "config.yaml", ".github", "scripts", "docs/pages", "main.py", "requirements.txt",
                  "pyproject.toml", "cloudflare", "notifiers", "src/report")
#: runtime が呼んではならない名前（file ・OS ・時計 ・環境 ・process ・socket ・乱数 ・出力）
FORBIDDEN_NAMES = {"open", "write", "write_text", "write_bytes", "read_text", "read_bytes", "mkdir", "unlink", "remove",
                   "rename", "environ", "getenv", "now", "today", "utcnow", "fromtimestamp", "utcfromtimestamp", "print",
                   "input", "sleep", "eval", "exec", "setattr", "random", "urandom", "uuid4", "system", "popen",
                   "Popen", "check_output", "socket", "connect", "bind", "listen", "urlopen", "Thread", "Timer",
                   "fork", "spawn", "getcwd", "chdir", "stat", "glob", "rglob", "iterdir", "exists"}
#: identifier の語（camel ／ snake を割った小文字）で禁じる語彙（投資 ・LLM ・時計の相対語 ・scheduler の実装語）
FORBIDDEN_WORDS = {"rank", "ranking", "score", "scoring", "recommend", "recommendation", "buy", "sell", "portfolio",
                   "allocation", "conviction", "priority", "weight", "rating", "position", "trade", "urgency",
                   "confidence", "return", "returns", "price", "holding", "holdings", "rebalance", "suitability", "llm",
                   "prompt", "latest", "current", "now", "cron", "subprocess", "socket", "thread", "push", "notify",
                   "credential", "secret", "apikey", "token", "jquants", "path", "filename", "payload", "message"}
#: 文書 ・直列化に在ってはならない private な値の形（Windows の path ・時刻つきの瞬間 ・5 桁の code ・id の接頭辞 ・著者）
PRIVATE_PATTERNS = (r"[A-Za-z]:\\", r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}", r"\b\d{5}\b", r"p9wat_", r"p9ths_", r"p8iss_", r"p10prf_",
                    r"p10att_", r"human:", r"x-api-key", r"api\.jquants")
STATIC_STRING_BANS = ("x-api-key", "api.jquants.com", "JQUANTS", "config.yaml", "://", "D:\\", "0.0.0.0", "127.0.0.1",
                      "__main__", "argparse", "sys.argv", "schtasks", "Task Scheduler", "datetime.now", "utcnow", "os.environ")
_P12 = PHASE12_PACKAGE
#: A2 の file ごとの許し（理由を伴う完全一致。A1 の file には無い）
STRING_ALLOWANCES = {f"{_P12}/network_deny.py": {"127.0.0.1"},                       # loopback の allowlist（bind ・接続先ではない）
                     f"{_P12}/preconditions.py": {"JQUANTS"},                         # 予約した資格情報の変数の名前（値は見ない）
                     f"{_P12}/server_readiness.py": {"://"},                          # 自分の loopback の origin の形だけ
                     f"{_P12}/run_cli.py": {"__main__", "argparse", "os.environ", "datetime.now", "Task Scheduler"},   # CLI（telemetry の時計だけ）
                     f"{_P12}/scheduled_run.py": {"Task Scheduler"}, f"{_P12}/scheduler_install.py": {"Task Scheduler"},
                     f"{_P12}/runtime_pin.py": {"Task Scheduler"}, f"{_P12}/skip_transaction.py": {"Task Scheduler"},
                     f"{_P12}/task_definition.py": {"Task Scheduler", "://"},            # A5: XML の名前空間の URI だけ
                     f"{_P12}/task_scheduler_adapter.py": {"Task Scheduler", "schtasks"}}   # A5: 狭い adapter だけが schtasks を呼ぶ
NAME_ALLOWANCES = {f"{_P12}/finalization.py": {"open", "write", "read_bytes", "mkdir", "rename", "exists"},   # .partial の中だけ
                   f"{_P12}/network_deny.py": {"socket", "connect", "setattr"},      # 拒否の guard の差し替え（出る時に戻す）
                   f"{_P12}/preconditions.py": {"exists", "iterdir", "read_bytes"},  # root が在って読めるか ・P11 の blob の再計算
                   f"{_P12}/source_manifests.py": {"read_bytes", "rglob"},            # 読み取り専用の manifest
                   f"{_P12}/atomic_files.py": {"open", "write", "read_bytes", "mkdir", "exists", "unlink"},   # 原子的な置換 ・追記
                   f"{_P12}/crash_classification.py": {"exists"},                     # 証拠を読むだけ
                   f"{_P12}/run_transaction.py": {"exists"},                          # final ／ .partial の有無
                   f"{_P12}/run_cli.py": {"open", "write", "now", "environ"},        # 入力 file ・REPORT の出力 ・telemetry の時計 ・環境の有無の写し
                   f"{_P12}/operational_lock.py": {"open", "write", "unlink", "exists", "mkdir"},   # O_CREAT|O_EXCL の lock ・解放 ・stale/
                   f"{_P12}/process_probe.py": {"open", "system", "run"},            # /proc の読み ・tasklist ／ CIM の問い合わせ
                   f"{_P12}/ledger_commit.py": {"sleep"},                             # 短い ledger lock の有界の待ち
                   f"{_P12}/recovery.py": {"exists", "rename", "read_bytes", "read_text", "iterdir"},   # .partial → .crashed ・artifact の照合
                   f"{_P12}/scheduler_install.py": {"open", "write"},                 # private な scheduler/ の XML
                   f"{_P12}/task_scheduler_adapter.py": {"read_bytes"}}               # test double が XML を読む
WORD_ALLOWANCES = {f"{_P12}/finalization.py": {"path"}, f"{_P12}/network_deny.py": {"socket"},
                   f"{_P12}/preconditions.py": {"path", "subprocess", "credential"}, f"{_P12}/server_readiness.py": {"thread"},
                   f"{_P12}/source_manifests.py": {"path"}, f"{_P12}/atomic_files.py": {"path"},
                   f"{_P12}/calendar_authority.py": {"path"}, f"{_P12}/crash_classification.py": {"path"},
                   f"{_P12}/ledger_store.py": {"path"}, f"{_P12}/schedule_authority.py": {"path"}, f"{_P12}/status_store.py": {"path"},
                   f"{_P12}/run_transaction.py": {"credential"}, f"{_P12}/run_cli.py": {"credential", "now"},
                   f"{_P12}/operational_lock.py": {"path"}, f"{_P12}/process_probe.py": {"subprocess"},
                   f"{_P12}/recovery.py": {"path"}, f"{_P12}/cancel_authority.py": {"path"},
                   f"{_P12}/runtime_pin.py": {"path", "subprocess"}, f"{_P12}/scheduled_run.py": {"credential"},
                   f"{_P12}/scheduler_install.py": {"path"}, f"{_P12}/task_definition.py": {"path"},
                   f"{_P12}/task_scheduler_adapter.py": {"path", "subprocess"}}
BROAD_EXCEPT_ALLOWED = {f"{_P12}/run_executor.py": 1}                                # 想定外 → STEP_FAILED:UNEXPECTED だけ
MAIN_ENTRY_ALLOWED = {f"{_P12}/run_cli.py"}                                           # `python -m` の入口だけ


def _git(*args: str) -> str:
    return subprocess.run(["git", *args], cwd=REPO_ROOT, capture_output=True, encoding="utf-8", errors="strict",
                          check=True).stdout


def _changes(*args: str) -> set:
    return {tuple(line.split("\t")) for line in _git("diff", *args).splitlines()}


def _blob_ids(anchor: str, paths) -> tuple:
    anchored = tuple(_git("rev-parse", *(f"{anchor}:{path}" for path in paths)).split())
    current = tuple(_git("hash-object", "--", *paths).split())
    return anchored, current


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


# ================================================ registry ・面 ・凍結の test の登録


def test_p12_a1_the_registry_is_exact_and_disjoint_from_earlier_phases() -> None:
    assert P12_BASE == "080d42aa3dad8bfc5ef82400beb6e2c62a873126"
    assert subprocess.run(["git", "merge-base", "--is-ancestor", P12_BASE, "HEAD"], cwd=REPO_ROOT).returncode == 0
    assert PHASE12_RUNTIME == tuple(sorted(PHASE12_A1_RUNTIME + PHASE12_A2_RUNTIME + PHASE12_A3_RUNTIME + PHASE12_A4_RUNTIME
                                           + PHASE12_A5_RUNTIME))
    assert len(PHASE12_RUNTIME) == 43 and len(PHASE12_A1_RUNTIME) == 11 and len(PHASE12_A2_RUNTIME) == 10
    assert len(PHASE12_A3_RUNTIME) == 9 and len(PHASE12_A4_RUNTIME) == 7 and len(PHASE12_A5_RUNTIME) == 6
    assert len(set(PHASE12_A1_RUNTIME) | set(PHASE12_A2_RUNTIME) | set(PHASE12_A3_RUNTIME) | set(PHASE12_A4_RUNTIME)
               | set(PHASE12_A5_RUNTIME)) == 43
    assert P12_A1 == "dd922c3eebd67de2ac273ba66e82e493d814e701" and P12_A2 == "bd0007d3b6684a1e4640a723010e197432939f95"
    assert P12_A3 == "66139db86e06130d7504a279b3d5ee820fd76b24" and set(PHASE12_A3_REOPENED_IN_A4) <= set(PHASE12_A3_RUNTIME)
    assert P12_A4 == "dcad07351201ecab44d91acc98740b8833bc3996" and set(PHASE12_A4_REOPENED_IN_A5) <= set(PHASE12_A3_REOPENED_IN_A4)
    a3_pinned = tuple(p for p in PHASE12_A3_RUNTIME if p not in PHASE12_A3_REOPENED_IN_A4)
    assert set(PHASE12_A4_REOPENED_IN_A6) <= set(PHASE12_A4_RUNTIME) and not set(PHASE12_A4_REOPENED_IN_A6) & set(PHASE12_A4_REOPENED_IN_A5)
    a4_pinned = tuple(p for p in PHASE12_A4_RUNTIME + PHASE12_A3_REOPENED_IN_A4
                      if p not in PHASE12_A4_REOPENED_IN_A5 and p not in PHASE12_A4_REOPENED_IN_A6)
    for commit, pinned in ((P12_A1, PHASE12_A1_RUNTIME), (P12_A2, PHASE12_A2_RUNTIME), (P12_A3, a3_pinned), (P12_A4, a4_pinned)):
        assert subprocess.run(["git", "merge-base", "--is-ancestor", commit, "HEAD"], cwd=REPO_ROOT).returncode == 0
        assert _git("diff", "--name-status", commit, "HEAD", "--", *pinned) == ""          # A1 ／ A2 ／ A3 の runtime はその commit のまま
        assert _git("diff", "--cached", "--name-status", commit, "--", *pinned) == ""
        assert _git("status", "--porcelain", "--", *pinned) == ""
    assert set(SANCTIONED_P12_P11_IMPORTERS) <= set(PHASE12_A2_RUNTIME)
    assert set(SANCTIONED_P12_EXTRA_STDLIB) <= (set(PHASE12_A2_RUNTIME) | set(PHASE12_A3_RUNTIME) | set(PHASE12_A4_RUNTIME)
                                                | set(PHASE12_A5_RUNTIME))
    assert _git("diff", "--cached", "--name-status", P12_A3, "--", *PHASE12_A3_REOPENED_IN_A4) != ""   # 再開は実在する（登録どおり）
    assert _git("diff", "--cached", "--name-status", P12_A4, "--", *PHASE12_A4_REOPENED_IN_A5) != ""
    assert _git("diff", "--cached", "--name-status", P12_A4, "--", *PHASE12_A4_REOPENED_IN_A6) != ""   # A6: lock の writer の O_BINARY
    assert all(p.startswith(PHASE12_PACKAGE + "/") and p.endswith(".py") for p in PHASE12_RUNTIME)
    assert {p.name for p in PACKAGE_DIR.iterdir() if p.name != "__pycache__"} == {Path(p).name for p in PHASE12_RUNTIME}
    for path in (*PHASE12_RUNTIME, *PHASE12_TESTS, *PHASE12_DOCS):
        assert (REPO_ROOT / path).is_file(), path
    assert not set(PHASE12_RUNTIME) & (set(PHASE11_RUNTIME) | set(PHASE10_RUNTIME) | set(PHASE9_RUNTIME)
                                       | set(PHASE8_RUNTIME) | set(PHASE7_RUNTIME))
    assert not any(_git("ls-tree", P12_BASE, "--", p).strip() for p in (*PHASE12_RUNTIME, *PHASE12_TESTS, *PHASE12_DOCS))
    assert set(SANCTIONED_P12_MODULES) == set(PHASE12_RUNTIME)
    assert is_phase12_addition("A", PHASE12_RUNTIME[0]) and is_phase12_addition("??", PHASE12_RUNTIME[0])
    assert not is_phase12_addition("M", PHASE12_RUNTIME[0])                                # A1 の runtime の修正は受けない
    assert not is_phase12_addition("A", f"{PHASE12_PACKAGE}/other.py") and not is_phase12_addition("A", PHASE11_RUNTIME[0])


def test_p12_a1_since_the_base_only_registered_phase12_files_and_declared_registration_changed() -> None:
    assert _changes("--cached", "--name-status", P12_BASE, "--", "src") == {("A", p) for p in PHASE12_RUNTIME}
    assert _git("diff", "--cached", "--name-status", P12_BASE, "--", *FROZEN_SURFACE) == ""
    assert _changes("--cached", "--name-status", P12_BASE, "--", "docs") <= {("A", p) for p in PHASE12_DOCS}
    assert _changes("--cached", "--name-status", P12_BASE, "--", "tests") <= {
        ("A", p) for p in PHASE12_TESTS} | {("M", p) for p in PHASE12_TEST_REGISTRATION}
    assert set(PHASE12_TEST_REGISTRATION) == {"tests/intelligence/phase7_runtime_registry.py",
                                              "tests/intelligence/test_narrative_intelligence_boundary.py",
                                              "tests/intelligence/test_screener_intelligence_boundary.py",
                                              "tests/intelligence/test_watchlist_thesis_boundary.py",
                                              "tests/intelligence/test_personal_intelligence_boundary.py",
                                              "tests/intelligence/test_personal_ui_boundary.py",
                                              "tests/intelligence/test_personal_ui_browser_hardening.py"}   # harness の安定化
    for path in PHASE12_TEST_REGISTRATION:                                            # 凍結の P7 〜 P11 の test の狭い再開
        anchored = _git("show", f"{P12_BASE}:{path}")
        current = (REPO_ROOT / path).read_text(encoding="utf-8")
        assert only_phase12_registration(path, anchored, current), path
        assert not only_phase12_registration(path, anchored, current + "assert True\n")
        assert not only_phase12_registration(path, anchored, anchored)
    for registry in ("tests/intelligence/phase8_runtime_registry.py", "tests/intelligence/phase9_runtime_registry.py",
                     "tests/intelligence/phase10_runtime_registry.py", "tests/intelligence/phase11_runtime_registry.py"):
        assert _git("diff", "--name-status", P12_BASE, "--", registry) == "", registry   # 前の phase の registry は不変
    pending = [line for line in _git("status", "--porcelain", "--", "src").splitlines()
               if not is_phase12_addition(line[:2].strip(), line[3:])]
    assert pending == []                                                                  # 作業木に未登録の src の変更なし


def test_p12_a1_frozen_phase4_to_11_runtime_is_object_identical_to_its_anchor_and_unchanged_since_the_base() -> None:
    for anchor, runtime in ((P11_A5, PHASE11_RUNTIME), (P10_A4, PHASE10_RUNTIME), (P9_A5, PHASE9_RUNTIME),
                            (P8_B5C, PHASE8_RUNTIME)):
        anchored, current = _blob_ids(anchor, runtime)
        assert len(anchored) == len(current) == len(runtime)
        assert [p for p, a, c in zip(runtime, anchored, current) if a != c] == []
    assert len(PHASE11_RUNTIME) == 12 and len(PHASE10_RUNTIME) == 17 and len(PHASE9_RUNTIME) == 18 and len(PHASE8_RUNTIME) == 54
    assert P11_A5 == "43c0b856d41efed397de213a1a06178c5e97ab10"
    excluded = [f":(exclude,literal){p}" for p in PHASE12_RUNTIME]
    assert _git("diff", "--name-status", P12_BASE, "--", "src", *excluded) == ""           # Phase 4 〜 11 の src 全体
    assert _git("diff", "--cached", "--name-status", P12_BASE, "--", "src", *excluded) == ""
    assert _git("status", "--porcelain", "--", *PHASE7_RUNTIME, *PHASE8_RUNTIME, *PHASE9_RUNTIME, *PHASE10_RUNTIME,
                *PHASE11_RUNTIME) == ""
    assert _git("diff", "--name-status", P12_BASE, "--", P11_FREEZE_DOC, "docs/databank/PHASE10_FINAL_FREEZE.md") == ""
    assert _git("show", f"{P12_BASE}:{P11_FREEZE_DOC}") == (REPO_ROOT / P11_FREEZE_DOC).read_text(encoding="utf-8")


def test_p12_freeze_the_43_registered_runtime_files_are_object_identical_to_the_anchor_and_the_validated_tree() -> None:
    """P12-A7: Phase 12 A-track v1 の runtime 43 file は anchor `P12_A6` ・Windows の検証を走らせた `P12_VALIDATED_TREE` ・index ・worktree で
    git の object が同じ。記録の commit（本文書）は validated tree の後に足され、anchor ではない。runtime の修正 ・未登録の追加は受けない。"""
    assert P12_A6 == "e390cddff9101541d16ba308a15d9ad1df3ca7b7" and P12_VALIDATED_TREE == "3056e25586767fd7b5d8095f016a4d254de5c360"
    for older in (P12_BASE, P12_A1, P12_A2, P12_A3, P12_A4):
        assert subprocess.run(["git", "merge-base", "--is-ancestor", older, P12_A6], cwd=REPO_ROOT).returncode == 0
    assert subprocess.run(["git", "merge-base", "--is-ancestor", P12_A6, P12_VALIDATED_TREE], cwd=REPO_ROOT).returncode == 0
    assert subprocess.run(["git", "merge-base", "--is-ancestor", P12_VALIDATED_TREE, "HEAD"], cwd=REPO_ROOT).returncode == 0
    assert len(PHASE12_RUNTIME) == 43 and len(set(PHASE12_RUNTIME)) == 43
    for commit in (P12_A6, P12_VALIDATED_TREE):
        assert set(_git("ls-tree", "-r", "--name-only", commit, "--", PHASE12_PACKAGE).splitlines()) == set(PHASE12_RUNTIME), commit
    at_anchor, in_worktree = _blob_ids(P12_A6, PHASE12_RUNTIME)
    at_validated, _ = _blob_ids(P12_VALIDATED_TREE, PHASE12_RUNTIME)
    in_index = tuple(_git("rev-parse", *(f":{path}" for path in PHASE12_RUNTIME)).split())
    assert len(at_anchor) == len(at_validated) == len(in_index) == len(in_worktree) == 43
    assert at_anchor == at_validated, "runtime blob differs between P12_A6 and P12_VALIDATED_TREE"
    assert at_anchor == in_index, "runtime blob differs between P12_A6 and the index"
    assert at_anchor == in_worktree, "runtime blob differs between P12_A6 and the worktree"
    assert _git("diff", "--name-status", P12_A6, "HEAD", "--", PHASE12_PACKAGE) == ""           # anchor 以後に package は不変
    assert _git("diff", "--cached", "--name-status", P12_A6, "--", PHASE12_PACKAGE) == ""
    assert _git("status", "--porcelain", "--", PHASE12_PACKAGE) == ""
    assert _git("diff", "--name-status", P12_VALIDATED_TREE, "HEAD", "--", "src") == ""         # validated tree 以後に src は不変
    assert {p.name for p in PACKAGE_DIR.iterdir() if p.name != "__pycache__"} == {Path(p).name for p in PHASE12_RUNTIME}
    assert all(not is_phase12_addition("M", path) for path in PHASE12_RUNTIME)                  # 凍結: 修正は受けない
    assert not is_phase12_addition("A", f"{PHASE12_PACKAGE}/new_module.py") and not is_phase12_addition("??", f"{PHASE12_PACKAGE}/new_module.py")
    assert FREEZE_DOC in PHASE12_DOCS and not _git("ls-tree", P12_VALIDATED_TREE, "--", FREEZE_DOC).strip()   # 記録は validated tree の後
    text = (REPO_ROOT / FREEZE_DOC).read_text(encoding="utf-8")
    for needle in ("COMPLETE / CLOSED / FROZEN", P12_A6, P12_VALIDATED_TREE, "新しい anchor ではない", "43 file", "A6_PASS",
                   "transfer/p12-a6-helper-v6", "8193c17081d2d55443e285cb9663f9dad43c416f", "a8bb4b41963328446201e11326614cad2214b56625573e18e7eba11ca771f7e8",
                   "89ee341dfa076dbe1903d92a743cd0120f13cae56809336eb24074e7168c123b", "P12-OBS-020", "P12-OBS-027", "MultipleInstances",
                   "InteractiveToken", "pin-runtime", "A-track", "B-track", "P12.5", "凍結しない", "利用者の Windows からの報告",
                   "この Linux の session からは見えない", "資格情報", "O_BINARY", "IgnoreNew"):
        assert needle in text, needle
    for banned in ("P12.5 は完了", "P13 は完了", "Phase 12 は完了", "Phase 12 全体", "signed", "署名済み"):
        assert banned not in text or banned == "Phase 12 全体", banned                         # 「Phase 12 全体は CLOSED ではない」だけ
    assert "Phase 12 全体は CLOSED ではない" in text


def test_p12_freeze_the_record_holds_no_private_validation_values() -> None:
    text = (REPO_ROOT / FREEZE_DOC).read_text(encoding="utf-8")
    for pattern in PRIVATE_PATTERNS + FREEZE_DOC_PRIVATE_PATTERNS:
        assert not re.search(pattern, text), pattern
    for banned in ("D:\\", "0.0.0.0", "C:\\Users", "x-api-key", "api.jquants"):
        assert banned not in text, banned
    for sample in ("S-1-5-21-1", "C:\\Users\\x", "09:00", "JQUANTS_API_KEY", "human:reviewer", "D:\\x", "2026-01-01T09:00", "12345"):
        assert any(re.search(pattern, sample) for pattern in PRIVATE_PATTERNS + FREEZE_DOC_PRIVATE_PATTERNS) or "D:\\" in sample, sample


# ================================================ import ・名前 ・語彙 ・直列化


def test_p12_a1_imports_are_stdlib_only_and_never_reach_frozen_phases_os_clock_network_or_process() -> None:
    for path in PHASE12_RUNTIME:
        relative, absolute = _imports(REPO_ROOT / path)
        allowed_stdlib = SANCTIONED_P12_STDLIB | SANCTIONED_P12_EXTRA_STDLIB.get(path, set())
        assert absolute <= allowed_stdlib, (path, absolute - allowed_stdlib)
        assert set(relative) == SANCTIONED_P12_MODULES[path], (path, set(relative))
        cross = {m: n for m, n in relative.items() if m.startswith("..")}
        assert cross == SANCTIONED_P12_P11_IMPORTERS.get(path, {}), (path, cross)         # 凍結の P11 の read の面だけ ・完全一致
        for module in (*relative, *absolute):
            if module in cross or module in SANCTIONED_P12_EXTRA_STDLIB.get(path, set()):
                continue
            components = set(module.lstrip(".").split("."))
            assert not components & set(FORBIDDEN_P12_IMPORT_PARTS), (path, module)
        assert not any(n.startswith("_") and n != "_require_id" and n != "_require_int" for names in relative.values()
                       for n in names), path
        source = (REPO_ROOT / path).read_text(encoding="utf-8")
        for token in STATIC_STRING_BANS:
            if token in STRING_ALLOWANCES.get(path, set()):
                continue
            assert token not in source, (path, token)
        if path in PHASE12_A1_RUNTIME:
            assert not cross and path not in SANCTIONED_P12_EXTRA_STDLIB and path not in NAME_ALLOWANCES
        if path in PHASE12_A3_RUNTIME or path in PHASE12_A4_RUNTIME or path in PHASE12_A5_RUNTIME:
            assert not cross, path                                                    # A3 〜 A5 は凍結の phase を直接 import しない（A2 経由）
        assert "personal_intelligence" not in source and "watchlist_thesis" not in source and "screener" not in source
        assert "ZoneInfo" not in source and "zoneinfo" not in source                     # 固定 +09:00 だけ（tzdata に依らない）


def test_p12_a1_the_runtime_never_touches_files_env_clock_process_or_network_and_has_no_investment_vocabulary() -> None:
    for path in PHASE12_RUNTIME:
        tree = ast.parse((REPO_ROOT / path).read_text(encoding="utf-8"))
        banned = FORBIDDEN_NAMES - NAME_ALLOWANCES.get(path, set())
        identifiers = set()
        broad = 0
        for node in ast.walk(tree):
            if isinstance(node, ast.Name):
                assert node.id not in banned, (path, node.id)
                identifiers.add(node.id)
            elif isinstance(node, ast.Attribute):
                assert node.attr not in banned, (path, node.attr)
                identifiers.add(node.attr)
            elif isinstance(node, ast.arg):
                identifiers.add(node.arg)
            elif isinstance(node, (ast.FunctionDef, ast.ClassDef)):
                identifiers.add(node.name)
            elif isinstance(node, ast.ExceptHandler):
                assert node.type is not None, (path, "bare except")
                names = {node.type.id} if isinstance(node.type, ast.Name) else {
                    e.id for e in getattr(node.type, "elts", ()) if isinstance(e, ast.Name)}
                broad += bool(names & {"Exception", "BaseException"})
            elif isinstance(node, ast.If) and isinstance(node.test, ast.Compare):
                left = node.test.left
                assert path in MAIN_ENTRY_ALLOWED or not (isinstance(left, ast.Name) and left.id == "__name__"), (path, "__main__")
        assert broad == BROAD_EXCEPT_ALLOWED.get(path, 0), (path, "broad except")
        words = set()
        for name in identifiers:
            words |= {w.lower() for w in re.findall(r"[A-Z]?[a-z]+|[A-Z]+(?![a-z])", name)}
        assert not words & (FORBIDDEN_WORDS - WORD_ALLOWANCES.get(path, set())), (path, words & FORBIDDEN_WORDS)


def test_p12_a1_serialization_of_every_model_is_canonical_and_free_of_paths_payloads_and_private_shapes() -> None:
    from datetime import datetime, timezone
    from src.intelligence.automation.holiday_calendar import HolidayCalendar
    from src.intelligence.automation.ledger_model import make_record
    from src.intelligence.automation.run_identity import AutomationRun
    from src.intelligence.automation.run_planning import plan_run
    from src.intelligence.automation.run_state import RunState
    from src.intelligence.automation.schedule_model import TIMEZONE_V1, AutomationSchedule, ScheduleSlot
    from src.intelligence.automation.status_projection import project_status

    cal = HolidayCalendar(calendar_id="ops-cal", version=1, dates=())
    slot = ScheduleSlot(slot_id="slot-a", local_time="07:30", weekday_mask=("MON", "TUE", "WED", "THU", "FRI"),
                        late_window_seconds=3600, readiness_on_non_business_day=False, enabled=True)
    sched = AutomationSchedule(schedule_id="ops-daily", version=1, timezone=TIMEZONE_V1, enabled=True, slots=(slot,),
                               holiday_calendar_ref=cal.reference(), created_at="2026-01-01T00:00:00Z")
    planned = plan_run(sched, cal, slot_id="slot-a", selection_clock_at=datetime(2026, 1, 4, 22, 45, tzinfo=timezone.utc))
    run = AutomationRun.from_planned(planned, "a" * 40)
    r0 = make_record(None, run, transition_to=RunState.PLANNED, recorded_at="2026-01-04T22:46:00Z")
    status = project_status([r0], runtime_anchor="a" * 40, schedule_id="ops-daily")
    import json
    rendered = [sched.to_json(), cal.to_json(), json.dumps(planned.to_dict()), json.dumps(run.to_dict()), r0.to_json(),
                json.dumps(status.to_dict())]
    for text in rendered:
        assert json.dumps(json.loads(text), sort_keys=True, separators=(",", ":"), ensure_ascii=False) == text or \
            text == json.dumps(json.loads(text))                                          # 正準（to_json）か json.dumps の形
        for pattern in (r"[A-Za-z]:\\", r"/[a-z]+/", r"\b\d{5}\b", r"p9wat_", r"p10prf_", r"human:", r"Traceback"):
            assert not re.search(pattern, text), (pattern, text[:80])
        assert "payload" not in text and "message" not in text and "exception" not in text.lower()


# ================================================ 公開の面 ・文書


def test_p12_a1_is_outside_production_and_public_code_and_nothing_else_imports_it() -> None:
    assert not any("automation" in module for module in runtime_closure())
    code_roots = [REPO_ROOT / "main.py", *sorted((REPO_ROOT / "src").rglob("*.py")), *sorted((REPO_ROOT / "scripts").rglob("*.py"))]
    if (REPO_ROOT / "notifiers").is_dir():
        code_roots += sorted((REPO_ROOT / "notifiers").rglob("*.py"))
    for path in code_roots:
        if PACKAGE_DIR in path.parents:
            continue
        assert "intelligence.automation" not in path.read_text(encoding="utf-8", errors="replace"), path
    for root in (".github", "docs/pages", "cloudflare"):
        if not (REPO_ROOT / root).is_dir():
            continue
        for path in sorted((REPO_ROOT / root).rglob("*")):
            if path.is_file() and path.suffix in (".py", ".yml", ".yaml", ".html", ".js", ".toml", ".md"):
                assert "intelligence/automation" not in path.read_text(encoding="utf-8", errors="replace"), path


def test_p12_a1_the_contract_records_the_required_clauses_and_no_private_values() -> None:
    text = (REPO_ROOT / CONTRACT_DOC).read_text(encoding="utf-8")
    for clause in (P12_BASE, "43c0b856d41efed397de213a1a06178c5e97ab10", "運用の authority", "市場の authority ではない",
                   "実行の証拠", "昇格しない", "projection は authority ではない", "selection_clock_at", "scheduled_for",
                   "started_at", "completed_at", "recorded_at", "hash 鎖", "改変の検出", "認証ではない", "署名ではない",
                   "ORPHANED_FINALIZATION", "黙って消さない", "retry は新しい run", "p12.automation_run.v1", "retry_of",
                   "supersedes", "Asia/Tokyo", "+09:00", "PHASE12_TEST_REGISTRATION", "Phase 12 の凍結ではない",
                   "REPO_NOT_CLEAN", "FROZEN_DRIFT", "SOURCE_INCOMPLETE", "DUPLICATE_INVOCATION", "INTERRUPTED",
                   "scheduler は無い", "subprocess", "P12-A2"):
        assert clause in text, clause
    for pattern in PRIVATE_PATTERNS:
        assert not re.search(pattern, text), pattern
    for banned in ("signed", "署名済み", "D:\\", "0.0.0.0"):
        assert banned not in text, banned


def test_p12_a2_the_contract_records_the_required_clauses_and_no_private_values() -> None:
    text = (REPO_ROOT / A2_CONTRACT_DOC).read_text(encoding="utf-8")
    for clause in (P12_A1, "43c0b856d41efed397de213a1a06178c5e97ab10", "networkless", "FINALIZED_PENDING_LEDGER", "成功ではない",
                   "PRECONDITIONS", "ROOT_MANIFESTS", "P11_MODEL_SNAPSHOT", "SERVER_READINESS", "FINALIZATION", ".partial",
                   "DUPLICATE_INVOCATION", "FROZEN_DRIFT", "REPO_HEAD_MISMATCH", "REPO_NOT_CLEAN", "CREDENTIAL_PRESENT",
                   "NETWORK_DENIED", "read_ui_model", "ui_model_json_bytes", "LocalServer", "昇格しない", "runs/",
                   "digests.json", "selection_clock", "datetime.now", "Task Scheduler", "A2 がしないこと", "P12-A3",
                   "Phase 12 の凍結ではない", "telemetry", "request.json", "snapshot.json", "manifests.json"):
        assert clause in text, clause
    for pattern in PRIVATE_PATTERNS:
        assert not re.search(pattern, text), pattern
    for banned in ("signed", "署名済み", "D:\\", "0.0.0.0"):
        assert banned not in text, banned
    for name in ("execution_request", "execution_result", "finalization", "frozen_anchors", "network_deny", "preconditions",
                 "run_executor", "server_readiness", "snapshot_orchestrator", "source_manifests"):
        assert name in text, name


def test_p12_a3_the_contract_records_the_required_clauses_and_no_private_values() -> None:
    text = (REPO_ROOT / A3_CONTRACT_DOC).read_text(encoding="utf-8")
    for clause in (P12_A2, "43c0b856d41efed397de213a1a06178c5e97ab10", "ledger が commit の authority", "SUCCEEDED", "head.json",
                   "LEDGER_INVALID", "CHECKPOINT_STALE", "ORPHANED_FINALIZATION", "LEDGER_COMMITTED_CHECKPOINT_STALE", "STATUS_STALE",
                   "status.json は authority ではない", "run の directory は authority ではない", "PLANNED_RECORDED", "RUNNING_RECORDED",
                   "TERMINAL_RECORDED", "LEDGER_REVERIFIED", "STATUS_PROJECTED", "ALREADY_SUCCEEDED", "DUPLICATE_INVOCATION",
                   "run_cli", "REPORT:", "RUN_FAILED CODE=", "write-schedule", "write-calendar", "classify", "human", "telemetry",
                   "datetime.now", "A4 に残すこと", "scheduler が無い理由", "認証ではない", "Phase 12 の凍結ではない", "P12-A4"):
        assert clause in text, clause
    for pattern in PRIVATE_PATTERNS:
        assert not re.search(pattern, text), pattern
    for banned in ("signed", "署名済み", "D:\\", "0.0.0.0"):
        assert banned not in text, banned
    for name in ("atomic_files", "calendar_authority", "crash_classification", "head_checkpoint", "ledger_store", "run_cli",
                 "run_transaction", "schedule_authority", "status_store"):
        assert name in text, name


def test_p12_a4_the_contract_records_the_required_clauses_and_no_private_values() -> None:
    text = (REPO_ROOT / A4_CONTRACT_DOC).read_text(encoding="utf-8")
    for clause in (P12_A3, "43c0b856d41efed397de213a1a06178c5e97ab10", "O_CREAT", "O_EXCL", "run の lock", "ledger の lock",
                   "LOCK_LIVE", "LOCK_STALE_DEAD", "LOCK_STALE_PID_REUSED", "LOCK_STALE_REBOOT", "LOCK_STALE_TERMINAL",
                   "LOCK_MALFORMED", "LOCK_UNKNOWN_PROVENANCE", "RUN_ACTIVE", "retry_of", "attempt", "FAILED", "CRASHED",
                   "ORPHANED_FINALIZATION", "LEDGER_COMMITTED_CHECKPOINT_STALE", "STATUS_STALE", "PARTIAL_PRESENT", ".crashed",
                   "repair-checkpoint", "regenerate-status", "recover-orphan", "recover-crashed", "recover-partial", "release-lock",
                   "retry", "cancel", "協調", "Windows", "tasklist", "fsync", "A5 に残すこと", "SUCCEEDED には変えない",
                   "Phase 12 の凍結ではない", "P12-A5", "run_transaction", "run_cli", "認証ではない"):
        assert clause in text, clause
    for pattern in PRIVATE_PATTERNS:
        assert not re.search(pattern, text), pattern
    for banned in ("signed", "署名済み", "D:\\", "0.0.0.0"):
        assert banned not in text, banned
    for name in ("cancel_authority", "injection", "ledger_commit", "operational_lock", "process_probe", "recovery", "retry"):
        assert name in text, name


def test_p12_a5_the_contract_records_the_required_clauses_and_no_private_values() -> None:
    text = (REPO_ROOT / A5_CONTRACT_DOC).read_text(encoding="utf-8")
    for clause in (P12_A4, "43c0b856d41efed397de213a1a06178c5e97ab10", "Task Scheduler", "scheduled-run", "selection_clock_at",
                   "scheduled_for", "NOT_DUE", "MISSED", "late window", "Compass", "P12_OWNED", "InteractiveToken", "LeastPrivilege",
                   "StartWhenAvailable", "IgnoreNew", "WakeToRun", "Tokyo Standard Time", "RECOVERY_REQUIRED", "pin-runtime",
                   "scheduler-install", "scheduler-remove", "scheduler-status", "exit code", "schtasks", "tzutil", "A6", "runbook",
                   "pull", "fetch", "checkout", "daemon", "Phase 12 の凍結ではない", "P12-A6", "run_cli", "認証ではない",
                   "release-lock", "retry しない"):
        assert clause in text, clause
    for pattern in PRIVATE_PATTERNS:
        assert not re.search(pattern, text), pattern
    for banned in ("signed", "署名済み", "D:\\", "0.0.0.0", "C:\\Users"):
        assert banned not in text, banned
    for name in ("runtime_pin", "scheduled_run", "scheduler_install", "skip_transaction", "task_definition", "task_scheduler_adapter"):
        assert name in text, name
    for clause in ("ALREADY_SKIPPED", "PLANNED → SKIPPED", "Task Scheduler の履歴"):                    # A5.1: skip の証拠の方針
        assert clause in text, clause
