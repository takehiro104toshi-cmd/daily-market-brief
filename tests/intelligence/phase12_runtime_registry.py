"""Phase 12（自動化 ・運用の authority）の登録済み runtime ・test ・文書の完全な一覧（P12-A1 〜 A4）。

- `P12_BASE` ＝ Phase 11 の凍結の記録の commit。P12-A1 はここから足す。
- 凍結の Phase 7 ／ 8 ／ 9 ／ 10 ／ 11 の test に入れた登録の行は `PHASE12_TEST_REGISTRATION` に完全に列挙し、Phase 12 の guard
  （`test_automation_boundary.py`）が `P12_BASE` との差分の完全一致を pin する（test だけの狭い再開。runtime は不変）。
- P12-A1 の runtime は純粋な domain ／ state の層だけ: scheduler ・subprocess ・server ・socket ・network ・資格情報 ・file の
  書き込みは無い。A1 の 11 file は `P12_A1` の commit と object 一致（A2 以後も不変）。
- P12-A2 の runtime は決定論の local orchestrator: 凍結の P11 の read の面（adapter ・UI model ・loopback server）だけを
  `SANCTIONED_P12_P11_IMPORTERS` の file が import する。file ごとに許す stdlib は `SANCTIONED_P12_EXTRA_STDLIB`（git の読み取り ・
  private root の file ・loopback の probe ・network の拒否の guard）。A2 の 10 file は `P12_A2` の commit と object 一致（A3 以後も不変）。
- P12-A3 の runtime は運用の commit の層: live の追記専用 ledger ＋ head checkpoint ・status の projection ・schedule ／ calendar の
  authority の file I/O ・crash の分類 ・1 run の transaction ・人の手の CLI。凍結の phase は import しない（A2 を経由する）。
  A3 の file は `P12_A3` の commit と object 一致。ただし A4 が登録して再開した 2 file（`PHASE12_A3_REOPENED_IN_A4`: transaction に
  lock ・直列化 ・cancel ・注入点を入れ、CLI に retry ・回復の命令を足す）だけは A4 の commit が新しい基準。
- P12-A4 の runtime は lock ・process の探り ・ledger の commit の直列化 ・注入点 ・cancel ・回復 ・retry。network ・資格情報 ・scheduler は無い。
"""
from __future__ import annotations

import difflib
from typing import Mapping, Sequence, Set, Tuple

#: P12 の基準（P11 の凍結の記録の commit）
P12_BASE = "080d42aa3dad8bfc5ef82400beb6e2c62a873126"
#: P12-A1 の runtime の commit（A1 の 11 file は以後も object 一致。意味 ／ runtime の凍結 anchor ではない）
P12_A1 = "dd922c3eebd67de2ac273ba66e82e493d814e701"
#: P12-A2 の runtime の commit（A2 の 10 file は以後も object 一致。凍結 anchor ではない）
P12_A2 = "bd0007d3b6684a1e4640a723010e197432939f95"
#: P12-A3 の runtime の commit（A3 の file は以後も object 一致。A4 が再開した 2 file を除く）
P12_A3 = "66139db86e06130d7504a279b3d5ee820fd76b24"
PHASE12_PACKAGE = "src/intelligence/automation"
#: P12-A1 で足した runtime（schedule の authority ・計画 ・run の identity ・状態機械 ・失敗 code ・step の結果 ・ledger の record ・
#: status の projection。純粋な model と関数だけ）
PHASE12_A1_RUNTIME: Tuple[str, ...] = tuple(f"{PHASE12_PACKAGE}/{name}.py" for name in (
    "__init__", "canonical", "failure_codes", "holiday_calendar", "ledger_model", "run_identity", "run_planning",
    "run_state", "schedule_model", "status_projection", "step_result"))
#: P12-A2 で足した runtime（決定論の local orchestrator: 前提条件 ・source の manifest ・P11 の snapshot ・loopback の readiness ・
#: 原子的な finalize ・実行の要求 ／ 結果 ・network の拒否。scheduler ・Task Scheduler ・J-Quants ・資格情報 ・公開は無い）
PHASE12_A2_RUNTIME: Tuple[str, ...] = tuple(f"{PHASE12_PACKAGE}/{name}.py" for name in (
    "execution_request", "execution_result", "finalization", "frozen_anchors", "network_deny", "preconditions",
    "run_executor", "server_readiness", "snapshot_orchestrator", "source_manifests"))
#: P12-A3 で足した runtime（運用の commit の層: 原子的な file ・head checkpoint ・live ledger ・status ・authority I/O ・crash の分類 ・
#: transaction ・人の手の CLI。scheduler ・background ・network ・資格情報は無い）
PHASE12_A3_RUNTIME: Tuple[str, ...] = tuple(f"{PHASE12_PACKAGE}/{name}.py" for name in (
    "atomic_files", "calendar_authority", "crash_classification", "head_checkpoint", "ledger_store", "run_cli",
    "run_transaction", "schedule_authority", "status_store"))
#: A4 が明示に再開した A3 の file（lock ・直列化 ・cancel ・注入点を transaction に ・retry ／ 回復の命令を CLI に ・回復済みの終端を
#: 孤児から除く 1 条件を分類に。他の A3 の file は不変）
PHASE12_A3_REOPENED_IN_A4: Tuple[str, ...] = (f"{PHASE12_PACKAGE}/crash_classification.py", f"{PHASE12_PACKAGE}/run_cli.py",
                                              f"{PHASE12_PACKAGE}/run_transaction.py")
#: P12-A4 で足した runtime（運用の lock ・process の探り ・ledger の commit の直列化 ・失敗の注入点 ・協調的な cancel ・回復 ・retry）
PHASE12_A4_RUNTIME: Tuple[str, ...] = tuple(f"{PHASE12_PACKAGE}/{name}.py" for name in (
    "cancel_authority", "injection", "ledger_commit", "operational_lock", "process_probe", "recovery", "retry"))
PHASE12_RUNTIME: Tuple[str, ...] = tuple(sorted(PHASE12_A1_RUNTIME + PHASE12_A2_RUNTIME + PHASE12_A3_RUNTIME + PHASE12_A4_RUNTIME))
PHASE12_TESTS: Tuple[str, ...] = ("tests/intelligence/phase12_runtime_registry.py",
                                  "tests/intelligence/test_automation_boundary.py",
                                  "tests/intelligence/test_automation_executor.py",
                                  "tests/intelligence/test_automation_ledger.py",
                                  "tests/intelligence/test_automation_ledger_store.py",
                                  "tests/intelligence/test_automation_locks.py",
                                  "tests/intelligence/test_automation_models.py",
                                  "tests/intelligence/test_automation_preconditions.py",
                                  "tests/intelligence/test_automation_recovery.py",
                                  "tests/intelligence/test_automation_transaction.py")
PHASE12_DOCS: Tuple[str, ...] = ("docs/databank/PHASE12_A1_SCHEDULE_RUN_STATE_MODEL.md",
                                 "docs/databank/PHASE12_A2_DETERMINISTIC_ORCHESTRATOR.md",
                                 "docs/databank/PHASE12_A3_OPERATIONAL_COMMIT_LAYER.md",
                                 "docs/databank/PHASE12_A4_LOCK_RETRY_RECOVERY.md")
ADDITION_STATUSES = ("A", "??")
#: 各 runtime の相対 import の module の集合（完全一致。package の外 ・凍結の phase への import は無い）
SANCTIONED_P12_MODULES: Mapping[str, Set[str]] = {
    f"{PHASE12_PACKAGE}/__init__.py": set(),
    f"{PHASE12_PACKAGE}/canonical.py": {".failure_codes"},
    f"{PHASE12_PACKAGE}/failure_codes.py": set(),
    f"{PHASE12_PACKAGE}/holiday_calendar.py": {".canonical", ".failure_codes", ".schedule_model"},
    f"{PHASE12_PACKAGE}/ledger_model.py": {".canonical", ".failure_codes", ".run_identity", ".run_planning", ".run_state",
                                           ".step_result"},
    f"{PHASE12_PACKAGE}/run_identity.py": {".canonical", ".failure_codes", ".run_planning", ".schedule_model"},
    f"{PHASE12_PACKAGE}/run_planning.py": {".canonical", ".failure_codes", ".holiday_calendar", ".run_state",
                                           ".schedule_model"},
    f"{PHASE12_PACKAGE}/run_state.py": {".failure_codes"},
    f"{PHASE12_PACKAGE}/schedule_model.py": {".canonical", ".failure_codes"},
    f"{PHASE12_PACKAGE}/status_projection.py": {".canonical", ".failure_codes", ".ledger_model", ".run_state",
                                                ".step_result"},
    f"{PHASE12_PACKAGE}/step_result.py": {".canonical", ".failure_codes"},
    # ---- P12-A2
    f"{PHASE12_PACKAGE}/execution_request.py": {".canonical", ".failure_codes", ".run_identity", ".run_planning",
                                                ".schedule_model"},
    f"{PHASE12_PACKAGE}/execution_result.py": {".canonical", ".failure_codes", ".step_result"},
    f"{PHASE12_PACKAGE}/finalization.py": {".canonical", ".failure_codes"},
    f"{PHASE12_PACKAGE}/frozen_anchors.py": {".canonical"},
    f"{PHASE12_PACKAGE}/network_deny.py": {".failure_codes"},
    f"{PHASE12_PACKAGE}/preconditions.py": {".execution_request", ".failure_codes", ".frozen_anchors", ".network_deny"},
    f"{PHASE12_PACKAGE}/run_executor.py": {".canonical", ".execution_request", ".execution_result", ".failure_codes",
                                           ".finalization", ".frozen_anchors", ".network_deny", ".preconditions",
                                           ".server_readiness", ".snapshot_orchestrator", ".source_manifests", ".step_result"},
    f"{PHASE12_PACKAGE}/server_readiness.py": {"..personal_ui.local_server", ".execution_request", ".failure_codes",
                                               ".frozen_anchors", ".preconditions"},
    f"{PHASE12_PACKAGE}/snapshot_orchestrator.py": {"..personal_ui.p10_read_adapter", "..personal_ui.ui_model", ".canonical",
                                                    ".execution_request", ".failure_codes", ".frozen_anchors", ".preconditions"},
    f"{PHASE12_PACKAGE}/source_manifests.py": {".canonical", ".failure_codes"},
    # ---- P12-A3
    f"{PHASE12_PACKAGE}/atomic_files.py": {".failure_codes"},
    f"{PHASE12_PACKAGE}/calendar_authority.py": {".atomic_files", ".failure_codes", ".holiday_calendar", ".schedule_authority",
                                                 ".schedule_model"},
    f"{PHASE12_PACKAGE}/crash_classification.py": {".finalization", ".head_checkpoint", ".ledger_store", ".run_state", ".status_store"},
    f"{PHASE12_PACKAGE}/head_checkpoint.py": {".canonical", ".failure_codes", ".ledger_model"},
    f"{PHASE12_PACKAGE}/ledger_store.py": {".atomic_files", ".failure_codes", ".head_checkpoint", ".ledger_model", ".run_state"},
    f"{PHASE12_PACKAGE}/run_cli.py": {".calendar_authority", ".cancel_authority", ".execution_request", ".failure_codes",
                                      ".holiday_calendar", ".ledger_store", ".preconditions", ".process_probe", ".recovery", ".retry",
                                      ".run_transaction", ".schedule_authority", ".schedule_model"},
    f"{PHASE12_PACKAGE}/run_transaction.py": {".atomic_files", ".cancel_authority", ".canonical", ".crash_classification",
                                              ".execution_request", ".execution_result", ".failure_codes", ".finalization", ".injection",
                                              ".ledger_commit", ".ledger_model", ".ledger_store", ".network_deny", ".operational_lock",
                                              ".preconditions", ".process_probe", ".run_executor", ".run_state", ".status_store"},
    # ---- P12-A4
    f"{PHASE12_PACKAGE}/cancel_authority.py": {".atomic_files", ".canonical", ".failure_codes", ".schedule_authority"},
    f"{PHASE12_PACKAGE}/injection.py": {".failure_codes"},
    f"{PHASE12_PACKAGE}/ledger_commit.py": {".failure_codes", ".injection", ".ledger_model", ".ledger_store", ".operational_lock",
                                            ".process_probe"},
    f"{PHASE12_PACKAGE}/operational_lock.py": {".atomic_files", ".canonical", ".failure_codes", ".ledger_store", ".process_probe",
                                               ".run_state"},
    f"{PHASE12_PACKAGE}/process_probe.py": set(),
    f"{PHASE12_PACKAGE}/recovery.py": {".atomic_files", ".canonical", ".crash_classification", ".execution_request", ".failure_codes",
                                       ".finalization", ".ledger_commit", ".ledger_model", ".ledger_store", ".operational_lock",
                                       ".preconditions", ".process_probe", ".run_state", ".run_transaction", ".status_store"},
    f"{PHASE12_PACKAGE}/retry.py": {".execution_request", ".failure_codes", ".ledger_store", ".operational_lock", ".preconditions",
                                    ".process_probe", ".run_state", ".run_transaction"},
    f"{PHASE12_PACKAGE}/schedule_authority.py": {".atomic_files", ".failure_codes", ".schedule_model"},
    f"{PHASE12_PACKAGE}/status_store.py": {".atomic_files", ".canonical", ".failure_codes", ".ledger_store", ".status_projection"},
}
#: 凍結の Phase 11 の read の面を import してよい P12 の file（完全な path → module → 名前。完全一致）。P10 ・P9 ・P8 は直接触れない
SANCTIONED_P12_P11_IMPORTERS: Mapping[str, Mapping[str, Set[str]]] = {
    f"{PHASE12_PACKAGE}/snapshot_orchestrator.py": {
        "..personal_ui.p10_read_adapter": {"ADAPTER_RULES_VERSION", "read_ui_model"},
        "..personal_ui.ui_model": {"UiModel", "UiReadError", "ui_model_json_bytes"}},
    f"{PHASE12_PACKAGE}/server_readiness.py": {
        "..personal_ui.local_server": {"LOOPBACK_BIND", "STATUS_BYTES", "VERSION_BYTES", "LocalServer", "ServerStartupError"}},
}
#: P12 の runtime に許す stdlib（純粋な model: 時計 ・OS ・path ・socket ・subprocess ・乱数は無い）
SANCTIONED_P12_STDLIB: Set[str] = {"__future__", "dataclasses", "datetime", "enum", "hashlib", "json", "re", "typing"}
#: A2 の file ごとに足して許す stdlib（git の読み取り ・private root の file ・loopback の probe ・network の拒否の guard だけ）
SANCTIONED_P12_EXTRA_STDLIB: Mapping[str, Set[str]] = {
    f"{PHASE12_PACKAGE}/finalization.py": {"os", "pathlib"},
    f"{PHASE12_PACKAGE}/network_deny.py": {"socket", "sys"},
    f"{PHASE12_PACKAGE}/preconditions.py": {"os", "pathlib", "subprocess"},
    f"{PHASE12_PACKAGE}/server_readiness.py": {"http.client"},
    f"{PHASE12_PACKAGE}/source_manifests.py": {"pathlib"},
    # ---- P12-A3（private root の file ・人の手の CLI の引数 ・標準出力 ・telemetry の時計）
    f"{PHASE12_PACKAGE}/atomic_files.py": {"os", "pathlib"},
    f"{PHASE12_PACKAGE}/calendar_authority.py": {"pathlib"},
    f"{PHASE12_PACKAGE}/crash_classification.py": {"pathlib"},
    f"{PHASE12_PACKAGE}/ledger_store.py": {"pathlib"},
    f"{PHASE12_PACKAGE}/run_cli.py": {"argparse", "os", "sys"},
    f"{PHASE12_PACKAGE}/schedule_authority.py": {"pathlib"},
    f"{PHASE12_PACKAGE}/status_store.py": {"pathlib"},
    # ---- P12-A4（lock の file ・process の探り ・有界の待ち ・.partial の rename）
    f"{PHASE12_PACKAGE}/ledger_commit.py": {"time"},
    f"{PHASE12_PACKAGE}/operational_lock.py": {"os", "pathlib"},
    f"{PHASE12_PACKAGE}/process_probe.py": {"os", "subprocess", "sys"},
    f"{PHASE12_PACKAGE}/recovery.py": {"os", "pathlib"},
    f"{PHASE12_PACKAGE}/cancel_authority.py": {"pathlib"},
}
#: Phase 12 が import してはならない module の部品（凍結の phase ・J-Quants ・公開 ・通知 ・network ・process ・OS ・LLM）
FORBIDDEN_P12_IMPORT_PARTS: Tuple[str, ...] = (
    "personal_ui", "personal_intelligence", "watchlist_thesis_intelligence", "screener_intelligence",
    "narrative_intelligence", "theme_intelligence", "themes", "jquants", "report", "notifier", "requests", "urllib",
    "http", "socket", "ssl", "subprocess", "sched", "threading", "multiprocessing", "asyncio", "anthropic", "openai",
    "llm", "pages", "predictions", "analysis", "compass", "os", "pathlib", "sys", "io", "random", "time", "uuid",
    "zoneinfo", "tempfile", "shutil", "logging", "winreg", "ctypes", "signal")
#: 凍結の Phase 7 〜 11 の test に入れた登録（path → (取り除いた行, 加えた行)）。P12-A1 で確定 ・PRE-P12-A2 で P11 の browser の
#: test の harness の安定化（同期の待ちだけ ・runtime 不変）を test だけの再開として登録
PHASE12_TEST_REGISTRATION: Mapping[str, Tuple[Tuple[str, ...], Tuple[str, ...]]] = {
    'tests/intelligence/phase7_runtime_registry.py': ((
        '                                                   + PHASE9_RUNTIME + PHASE10_RUNTIME + PHASE11_RUNTIME)',
        '                                                    + PHASE11_RUNTIME)',
        '            or is_phase11_addition(status, path))                 # P11-A3: 凍結していない Phase 11 の runtime の修正（M）も',
    ), (
        'from tests.intelligence.phase12_runtime_registry import PHASE12_RUNTIME, is_phase12_addition   # P12-A1: Phase 12',
        '                                                   + PHASE9_RUNTIME + PHASE10_RUNTIME + PHASE11_RUNTIME + PHASE12_RUNTIME)',
        '                                                    + PHASE11_RUNTIME + PHASE12_RUNTIME)',
        '            or is_phase11_addition(status, path)                  # P11-A3: 凍結していない Phase 11 の runtime の修正（M）も',
        '            or is_phase12_addition(status, path))                 # P12-A1: 凍結していない Phase 12 の runtime も',
    )),
    'tests/intelligence/test_narrative_intelligence_boundary.py': ((
        '                       + PHASE10_RUNTIME + PHASE11_RUNTIME}                                 # commit ／ index の差',
        '                                            + PHASE11_DOCS}',
        '        ("A", path) for path in PHASE8_TESTS + PHASE9_TESTS + PHASE10_TESTS + PHASE11_TESTS}',
        '                                              + PHASE9_RUNTIME + PHASE10_RUNTIME + PHASE11_RUNTIME)',
        '        ("A", path) for path in PHASE8_RUNTIME + PHASE9_RUNTIME + PHASE10_RUNTIME + PHASE11_RUNTIME}   # 追加だけ',
        '        ("A", path) for path in PHASE8_RUNTIME + PHASE9_RUNTIME + PHASE10_RUNTIME + PHASE11_RUNTIME}   # A4b と P8 〜 P11 の追加だけ',
        '                                                                                  + PHASE11_RUNTIME}',
    ), (
        'from tests.intelligence.phase12_runtime_registry import PHASE12_DOCS, PHASE12_RUNTIME, PHASE12_TESTS   # P12-A1 の登録',
        '                       + PHASE10_RUNTIME + PHASE11_RUNTIME + PHASE12_RUNTIME}               # commit ／ index の差',
        '                                            + PHASE11_DOCS + PHASE12_DOCS}',
        '        ("A", path) for path in PHASE8_TESTS + PHASE9_TESTS + PHASE10_TESTS + PHASE11_TESTS + PHASE12_TESTS}',
        '                                              + PHASE9_RUNTIME + PHASE10_RUNTIME + PHASE11_RUNTIME + PHASE12_RUNTIME)',
        '        ("A", path) for path in PHASE8_RUNTIME + PHASE9_RUNTIME + PHASE10_RUNTIME + PHASE11_RUNTIME',
        '        + PHASE12_RUNTIME}                                                                       # 追加だけ',
        '        ("A", path) for path in PHASE8_RUNTIME + PHASE9_RUNTIME + PHASE10_RUNTIME + PHASE11_RUNTIME',
        '        + PHASE12_RUNTIME}                                                                       # A4b と P8 〜 P12 の追加だけ',
        '                                                                                  + PHASE11_RUNTIME + PHASE12_RUNTIME}',
    )),
    'tests/intelligence/test_screener_intelligence_boundary.py': ((
        '        ("A", path) for path in PHASE9_TESTS + PHASE10_TESTS + PHASE11_TESTS}',
        '    assert changes == {("A", path) for path in PHASE8_RUNTIME + PHASE9_RUNTIME + PHASE10_RUNTIME + PHASE11_RUNTIME}',
        '                       or is_phase11_addition(line[:2].strip(), line[3:]))]',
        '                        ("A", path) for path in PHASE9_DOCS + PHASE10_DOCS + PHASE11_DOCS}',
    ), (
        'from tests.intelligence.phase12_runtime_registry import (PHASE12_DOCS, PHASE12_RUNTIME, PHASE12_TESTS,',
        '                                                         is_phase12_addition)   # P12 の登録',
        '        ("A", path) for path in PHASE9_TESTS + PHASE10_TESTS + PHASE11_TESTS + PHASE12_TESTS}',
        '    assert changes == {("A", path) for path in PHASE8_RUNTIME + PHASE9_RUNTIME + PHASE10_RUNTIME + PHASE11_RUNTIME',
        '                       + PHASE12_RUNTIME}',
        '                       or is_phase11_addition(line[:2].strip(), line[3:])',
        '                       or is_phase12_addition(line[:2].strip(), line[3:]))]',
        '                        ("A", path) for path in PHASE9_DOCS + PHASE10_DOCS + PHASE11_DOCS + PHASE12_DOCS}',
    )),
    'tests/intelligence/test_watchlist_thesis_boundary.py': ((
        '                                                                           + PHASE10_RUNTIME + PHASE11_RUNTIME}',
        '                                                                            + PHASE10_DOCS + PHASE11_DOCS}',
        '        ("A", path) for path in PHASE9_TESTS + PHASE10_TESTS + PHASE11_TESTS} | {',
    ), (
        'from tests.intelligence.phase12_runtime_registry import PHASE12_DOCS, PHASE12_RUNTIME, PHASE12_TESTS   # P12 の登録',
        '                                                                           + PHASE10_RUNTIME + PHASE11_RUNTIME',
        '                                                                           + PHASE12_RUNTIME}',
        '                                                                            + PHASE10_DOCS + PHASE11_DOCS + PHASE12_DOCS}',
        '        ("A", path) for path in PHASE9_TESTS + PHASE10_TESTS + PHASE11_TESTS + PHASE12_TESTS} | {',
    )),
    'tests/intelligence/test_personal_intelligence_boundary.py': ((
        '                                                                            + PHASE11_RUNTIME}',
        '                                                                             + PHASE11_DOCS}',
        '        ("A", p) for p in PHASE10_TESTS + PHASE11_TESTS} | {("M", p) for p in PHASE10_TEST_REGISTRATION}',
    ), (
        'from tests.intelligence.phase12_runtime_registry import PHASE12_DOCS, PHASE12_RUNTIME, PHASE12_TESTS   # P12 の登録',
        '                                                                            + PHASE11_RUNTIME + PHASE12_RUNTIME}',
        '                                                                             + PHASE11_DOCS + PHASE12_DOCS}',
        '        ("A", p) for p in PHASE10_TESTS + PHASE11_TESTS + PHASE12_TESTS} | {("M", p) for p in PHASE10_TEST_REGISTRATION}',
    )),
    'tests/intelligence/test_personal_ui_browser_hardening.py': ((
        '            page.click("#load")',
        '            page.wait_for_function("() => document.getElementById(\'message\').textContent.includes(\'RESPONSE_INVALID\')")',
        '        page.click("#load")',
        '        page.wait_for_function("() => document.getElementById(\'message\').textContent.includes(\'RESPONSE_INVALID\')")',
    ), (
        '',
        '',
        'def _load_and_wait_for_rejection(page, code: str = "RESPONSE_INVALID") -> None:',
        '    """今回の送信に属する拒否だけを待つ（P11 harness の安定化。runtime は不変）。',
        '',
        '    app.js の `load` は click と同期に `#message` を隠し、文は残す。「見えていて code を含む」は今回の応答の `fail` でだけ成り立ち、',
        '    前の iteration の隠れた RESPONSE_INVALID の文では成り立たない。`expect_response` が今回の /api/view の応答の到着を結ぶ。"""',
        '    with page.expect_response(VIEW_RE):',
        '        page.click("#load")',
        '    page.wait_for_function("code => { const m = document.getElementById(\'message\'); "',
        '                           "return !m.hidden && m.textContent.includes(code); }", arg=code)',
        '            _load_and_wait_for_rejection(page)                                             # 今回の応答の拒否を待つ（古い文は不可）',
        '        _load_and_wait_for_rejection(page)',
    )),
    'tests/intelligence/test_personal_ui_boundary.py': ((
        '    assert _changes("--cached", "--name-status", P11_BASE, "--", "src") == {("A", p) for p in PHASE11_RUNTIME}',
        '    assert _changes("--cached", "--name-status", P11_BASE, "--", "docs") <= {("A", p) for p in PHASE11_DOCS}',
        '        ("A", p) for p in PHASE11_TESTS} | {("M", p) for p in PHASE11_TEST_REGISTRATION}',
        '        current = (REPO_ROOT / path).read_text(encoding="utf-8")',
        '        if PACKAGE_DIR in path.parents:',
    ), (
        'from tests.intelligence.phase12_runtime_registry import (P12_BASE, PHASE12_DOCS, PHASE12_PACKAGE, PHASE12_RUNTIME,',
        '                                                         PHASE12_TESTS)   # P12 の登録',
        'P12_PACKAGE_DIR = REPO_ROOT / PHASE12_PACKAGE      # P12-A2: automation の P11 の importer は P12 の guard が完全一致で pin',
        '    assert _changes("--cached", "--name-status", P11_BASE, "--", "src") == {("A", p) for p in PHASE11_RUNTIME',
        '                                                                            + PHASE12_RUNTIME}',
        '    assert _changes("--cached", "--name-status", P11_BASE, "--", "docs") <= {("A", p) for p in PHASE11_DOCS',
        '                                                                             + PHASE12_DOCS}',
        '        ("A", p) for p in PHASE11_TESTS + PHASE12_TESTS} | {("M", p) for p in PHASE11_TEST_REGISTRATION}',
        '        current = _git("show", f"{P12_BASE}:{path}")             # P11 の登録は P11 の終わりまで（以後の差は P12 の guard が pin）',
        '        if PACKAGE_DIR in path.parents or P12_PACKAGE_DIR in path.parents:',
    )),
}


def is_phase12_addition(status: str, path: str) -> bool:
    """Phase 12 の runtime の変化か。Phase 12 は凍結していないので、A1 以外の登録済み runtime は gate の中の修正（M）も受ける
    （A1 の runtime の不変は `test_automation_boundary.py` が別に守る）。"""
    if status in ADDITION_STATUSES and path in PHASE12_RUNTIME:
        return True
    return status == "M" and path in PHASE12_RUNTIME and path not in PHASE12_A1_RUNTIME


def registration_diff(anchored: str, current: str) -> Tuple[Sequence[str], Sequence[str]]:
    """anchor と現在の行の差（取り除かれた行, 加えられた行）。順序は出現順。"""
    old, new = anchored.split("\n"), current.split("\n")
    removed, added = [], []
    for tag, i1, i2, j1, j2 in difflib.SequenceMatcher(None, old, new, autojunk=False).get_opcodes():
        if tag in ("replace", "delete"):
            removed.extend(old[i1:i2])
        if tag in ("replace", "insert"):
            added.extend(new[j1:j2])
    return removed, added


def only_phase12_registration(path: str, anchored: str, current: str) -> bool:
    """`P12_BASE` と現在の差が、宣言した登録（取り除いた行・加えた行）と完全に一致する（未登録の file は byte 一致）。"""
    declared_removed, declared_added = PHASE12_TEST_REGISTRATION.get(path, ((), ()))
    removed, added = registration_diff(anchored, current)
    return sorted(removed) == sorted(declared_removed) and sorted(added) == sorted(declared_added)


__all__ = ["ADDITION_STATUSES", "FORBIDDEN_P12_IMPORT_PARTS", "P12_A1", "P12_A2", "P12_A3", "P12_BASE", "PHASE12_A1_RUNTIME",
           "PHASE12_A2_RUNTIME", "PHASE12_A3_REOPENED_IN_A4", "PHASE12_A3_RUNTIME", "PHASE12_A4_RUNTIME",
           "PHASE12_DOCS", "PHASE12_PACKAGE", "PHASE12_RUNTIME", "PHASE12_TESTS", "PHASE12_TEST_REGISTRATION",
           "SANCTIONED_P12_EXTRA_STDLIB", "SANCTIONED_P12_MODULES", "SANCTIONED_P12_P11_IMPORTERS", "SANCTIONED_P12_STDLIB",
           "is_phase12_addition", "only_phase12_registration", "registration_diff"]
