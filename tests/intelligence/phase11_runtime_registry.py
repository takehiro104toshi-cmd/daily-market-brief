"""Phase 11（PWA ／ 利用者との対話の面）の登録済み runtime ・test ・文書の完全な一覧（P11-A1 〜 A4）。

- `P11_BASE` ＝ Phase 10 の凍結の記録の commit。P11-A1 はここから足す。
- 凍結の Phase 7 ／ 8 ／ 9 ／ 10 の test に入れた登録の行は `PHASE11_TEST_REGISTRATION` に完全に列挙し、Phase 11 の guard
  （`test_personal_ui_boundary.py`）が `P11_BASE` との差分の完全一致を pin する（test だけの狭い再開。runtime は不変）。
- 凍結の Phase 10 を import してよい Phase 11 の file は `SANCTIONED_P11_P10_IMPORTERS`（完全な path → governed な read の API の面）
  だけ。store ・実行器 ・直列化 ・管理の初期化 ・private な P9 の snapshot は無い。
"""
from __future__ import annotations

import difflib
from typing import Mapping, Sequence, Set, Tuple

#: P11 の基準（P10 の凍結の記録の commit）
P11_BASE = "d01f6bc01fba783e77cc3a623745b8b033883e1a"
#: P11-A1 の runtime の commit（後の phase の guard の登録のため。意味 ／ runtime の凍結 anchor ではない）
P11_A1 = "da806753868da597d50875300064722fd12e4bb8"
#: P11-A2 の runtime の commit（同上。凍結 anchor ではない）
P11_A2 = "3ceb36b3496703c7fad315986e52c49a2c24d71b"
#: P11-A3 の runtime の commit（同上）
P11_A3 = "19686a6f12abfcb1859f84b71acda90015b291c3"
#: Phase 11 v1 の意味 ／ runtime の凍結 anchor（P11-A5 の Windows の移植性の follow-up の commit。P11-A6 で確定）
P11_A5 = "43c0b856d41efed397de213a1a06178c5e97ab10"
PHASE11_PACKAGE = "src/intelligence/personal_ui"
#: P11-A1 で足した runtime（governed な read の adapter と UI model だけ。server ・UI ・SW ・書き込みなし）
PHASE11_A1_RUNTIME: Tuple[str, ...] = tuple(f"{PHASE11_PACKAGE}/{name}.py" for name in (
    "__init__", "p10_read_adapter", "ui_model"))
#: P11-A2 で足した runtime（loopback の local server だけ。browser の UI ・manifest ・SW ・static な file なし）
PHASE11_A2_RUNTIME: Tuple[str, ...] = (f"{PHASE11_PACKAGE}/local_server.py",)
PHASE11_PY_RUNTIME: Tuple[str, ...] = tuple(sorted(PHASE11_A1_RUNTIME + PHASE11_A2_RUNTIME))
#: P11-A3 で足した static な shell（loopback の server が allowlist で配る committed な byte。runtime として登録）
PHASE11_STATIC_DIR = f"{PHASE11_PACKAGE}/static"
P11_STATIC_ASSETS: Tuple[str, ...] = tuple(f"{PHASE11_STATIC_DIR}/{name}" for name in (
    ".gitattributes", "app.css", "app.js", "icon-192.png", "icon-512.png", "index.html", "manifest.webmanifest", "sw.js"))
PHASE11_A3_RUNTIME: Tuple[str, ...] = P11_STATIC_ASSETS
PHASE11_RUNTIME: Tuple[str, ...] = tuple(sorted(PHASE11_PY_RUNTIME + PHASE11_A3_RUNTIME))
#: 経路 → asset（完全な allowlist。server の STATIC_ROUTES と一致）
P11_STATIC_ROUTES: Mapping[str, str] = {
    "/app/": "index.html", "/app/index.html": "index.html", "/app/app.js": "app.js", "/app/app.css": "app.css",
    "/app/manifest.webmanifest": "manifest.webmanifest", "/app/sw.js": "sw.js", "/app/icon-192.png": "icon-192.png",
    "/app/icon-512.png": "icon-512.png"}
#: service worker が precache する経路（sw.js 自身は含まない）。shell の cache の名前は precache の asset の git blob から導く
P11_SHELL_PRECACHE: Tuple[str, ...] = ("/app/", "/app/index.html", "/app/app.js", "/app/app.css",
                                        "/app/manifest.webmanifest", "/app/icon-192.png", "/app/icon-512.png")
P11_SHELL_CACHE_NAME = "p11-shell-2729564d0ff5"
#: static な asset の git blob の id（P11-A3 で確定 ・A4 の硬化で更新。checkout の改行に依らない object の意味）
P11_STATIC_BLOB_IDS: Mapping[str, str] = {
    'src/intelligence/personal_ui/static/.gitattributes': 'fa1385d99a319b43c06f5309d1aae9fdd3adea46',
    'src/intelligence/personal_ui/static/app.css': 'f3db2832edcfdcc02d302a6510b2b6bbbe9d1e05',
    'src/intelligence/personal_ui/static/app.js': '9bf12c66aa36d0131da81f3125715589c30b081d',
    'src/intelligence/personal_ui/static/icon-192.png': '60ea4a088a2fe2c81f4602d33c4290a65d5a035a',
    'src/intelligence/personal_ui/static/icon-512.png': 'b37421a7d8433c8b18e3637c1b00c1bc99a7d953',
    'src/intelligence/personal_ui/static/index.html': '352cfff59abce81a29765f3ce5ced01356e3cd86',
    'src/intelligence/personal_ui/static/manifest.webmanifest': '65372b8dbf4e4badbd6e64f1e71948b1be1a0db5',
    'src/intelligence/personal_ui/static/sw.js': '55ade163c455e3481eeac2a6ae0a6fcc7951b5fb',
}
PHASE11_TESTS: Tuple[str, ...] = ("tests/intelligence/phase11_runtime_registry.py",
                                  "tests/intelligence/test_personal_ui_adapter.py",
                                  "tests/intelligence/test_personal_ui_boundary.py",
                                  "tests/intelligence/test_personal_ui_server.py",
                                  "tests/intelligence/test_personal_ui_static.py",
                                  "tests/intelligence/test_personal_ui_browser.py",
                                  "tests/intelligence/test_personal_ui_hardening.py",
                                  "tests/intelligence/test_personal_ui_browser_hardening.py")
PHASE11_DOCS: Tuple[str, ...] = ("docs/databank/PHASE11_A1_GOVERNED_READ_ADAPTER.md",
                                 "docs/databank/PHASE11_A2_LOOPBACK_SERVER.md",
                                 "docs/databank/PHASE11_A3_STATIC_PWA_SHELL.md",
                                 "docs/databank/PHASE11_A4_PRIVACY_OFFLINE_HARDENING.md",
                                 "docs/databank/PHASE11_FINAL_FREEZE.md")
ADDITION_STATUSES = ("A", "??")
P11_ADAPTER = f"{PHASE11_PACKAGE}/p10_read_adapter.py"
P11_UI_MODEL = f"{PHASE11_PACKAGE}/ui_model.py"
P11_LOCAL_SERVER = f"{PHASE11_PACKAGE}/local_server.py"
#: 凍結 Phase 10 の governed な read の面（module → 名前。完全一致）。adapter 1 file だけが import する
SANCTIONED_P11_P10_IMPORTS: Mapping[str, Set[str]] = {
    "..personal_intelligence.p9_view": {"P9ViewError", "read_p9_safe_view"},
    "..personal_intelligence.personal_projection": {"personal_safe_projection"},
    "..personal_intelligence.review_view": {"ReviewViewError", "read_personal_review"},
}
SANCTIONED_P11_P10_IMPORTERS: Mapping[str, Mapping[str, Set[str]]] = {P11_ADAPTER: SANCTIONED_P11_P10_IMPORTS}
#: 各 runtime の相対 import の module の集合（完全一致）
SANCTIONED_P11_MODULES: Mapping[str, Set[str]] = {
    P11_ADAPTER: set(SANCTIONED_P11_P10_IMPORTS) | {".ui_model"},
    P11_UI_MODEL: set(),
    f"{PHASE11_PACKAGE}/__init__.py": set(),
    P11_LOCAL_SERVER: {".p10_read_adapter", ".ui_model"},                           # A1 の公開の API だけ（P10 ・P9 は直接触れない）
}
#: local server だけに許す stdlib（loopback の server ・引数 ・環境変数の有無 ・標準出力）
SANCTIONED_P11_SERVER_STDLIB: Set[str] = {"argparse", "http.server", "ipaddress", "os", "pathlib", "sys", "threading"}
#: Phase 11 が import してはならない module の部品（凍結の store ・実行器 ・P9 ／ P8 ・J-Quants ・公開 ・通知 ・network ・LLM）
FORBIDDEN_P11_IMPORT_PARTS: Tuple[str, ...] = (
    "profile_store", "attention_store", "authority_stores", "store_io", "serialization", "admin_init", "executor",
    "decisions", "local_cli", "cross_rules", "revision_model", "profile_model", "attention_model",
    "watchlist_thesis_intelligence", "screener_intelligence", "narrative_intelligence", "jquants", "report",
    "notifier", "requests", "urllib", "http", "socket", "ssl", "subprocess", "anthropic", "openai", "llm", "pages",
    "predictions", "analysis", "compass", "os", "pathlib", "sys", "io", "random", "time", "hashlib", "uuid")
#: 凍結の Phase 7 ／ 8 ／ 9 ／ 10 の test に入れた登録（path → (取り除いた行, 加えた行)）。P11-A1 で確定 ・A3 で P7 の helper だけ再開
PHASE11_TEST_REGISTRATION: Mapping[str, Tuple[Tuple[str, ...], Tuple[str, ...]]] = {
    'tests/intelligence/phase7_runtime_registry.py': ((
        '                                                   + PHASE9_RUNTIME + PHASE10_RUNTIME)',
        '    return status in ADDITION_STATUSES and path in PHASE7_RUNTIME + PHASE8_RUNTIME + PHASE9_RUNTIME + PHASE10_RUNTIME',
    ), (
        'from tests.intelligence.phase11_runtime_registry import PHASE11_RUNTIME, is_phase11_addition   # P11-A1 ／ A3: Phase 11',
        '                                                   + PHASE9_RUNTIME + PHASE10_RUNTIME + PHASE11_RUNTIME)',
        '    return (status in ADDITION_STATUSES and path in (PHASE7_RUNTIME + PHASE8_RUNTIME + PHASE9_RUNTIME + PHASE10_RUNTIME',
        '                                                    + PHASE11_RUNTIME)',
        '            or is_phase11_addition(status, path))                 # P11-A3: 凍結していない Phase 11 の runtime の修正（M）も',
    )),
    'tests/intelligence/test_narrative_intelligence_boundary.py': ((
        '                       + PHASE10_RUNTIME}                                                   # commit ／ index の差',
        '                       ("A", P8_A0_DOC)} | {("A", path) for path in PHASE8_DOCS + PHASE9_DOCS + PHASE10_DOCS}',
        '        ("A", path) for path in PHASE8_TESTS + PHASE9_TESTS + PHASE10_TESTS}',
        '                                              + PHASE9_RUNTIME + PHASE10_RUNTIME)',
        '        ("A", path) for path in PHASE8_RUNTIME + PHASE9_RUNTIME + PHASE10_RUNTIME}        # 追加だけ',
        '        ("A", path) for path in PHASE8_RUNTIME + PHASE9_RUNTIME + PHASE10_RUNTIME}        # A4b と P8 ・P9 ・P10 の追加だけ',
        '                                                                                  + PHASE9_RUNTIME + PHASE10_RUNTIME}',
    ), (
        'from tests.intelligence.phase11_runtime_registry import PHASE11_DOCS, PHASE11_RUNTIME, PHASE11_TESTS   # P11-A1 の登録',
        '                       + PHASE10_RUNTIME + PHASE11_RUNTIME}                                 # commit ／ index の差',
        '                       ("A", P8_A0_DOC)} | {("A", path) for path in PHASE8_DOCS + PHASE9_DOCS + PHASE10_DOCS',
        '                                            + PHASE11_DOCS}',
        '        ("A", path) for path in PHASE8_TESTS + PHASE9_TESTS + PHASE10_TESTS + PHASE11_TESTS}',
        '                                              + PHASE9_RUNTIME + PHASE10_RUNTIME + PHASE11_RUNTIME)',
        '        ("A", path) for path in PHASE8_RUNTIME + PHASE9_RUNTIME + PHASE10_RUNTIME + PHASE11_RUNTIME}   # 追加だけ',
        '        ("A", path) for path in PHASE8_RUNTIME + PHASE9_RUNTIME + PHASE10_RUNTIME + PHASE11_RUNTIME}   # A4b と P8 〜 P11 の追加だけ',
        '                                                                                  + PHASE9_RUNTIME + PHASE10_RUNTIME',
        '                                                                                  + PHASE11_RUNTIME}',
    )),
    'tests/intelligence/test_screener_intelligence_boundary.py': ((
        '        ("A", path) for path in PHASE9_TESTS + PHASE10_TESTS}',
        '    assert changes == {("A", path) for path in PHASE8_RUNTIME + PHASE9_RUNTIME + PHASE10_RUNTIME}',
        '                       or is_phase10_addition(line[:2].strip(), line[3:]))]',
        '                        ("A", path) for path in PHASE9_DOCS + PHASE10_DOCS}',
    ), (
        'from tests.intelligence.phase11_runtime_registry import (PHASE11_DOCS, PHASE11_RUNTIME, PHASE11_TESTS,',
        '                                                         is_phase11_addition)   # P11 の登録',
        '        ("A", path) for path in PHASE9_TESTS + PHASE10_TESTS + PHASE11_TESTS}',
        '    assert changes == {("A", path) for path in PHASE8_RUNTIME + PHASE9_RUNTIME + PHASE10_RUNTIME + PHASE11_RUNTIME}',
        '                       or is_phase10_addition(line[:2].strip(), line[3:])',
        '                       or is_phase11_addition(line[:2].strip(), line[3:]))]',
        '                        ("A", path) for path in PHASE9_DOCS + PHASE10_DOCS + PHASE11_DOCS}',
    )),
    'tests/intelligence/test_watchlist_thesis_boundary.py': ((
        '                                                                           + PHASE10_RUNTIME}',
        '                                                                            + PHASE10_DOCS}',
        '        ("A", path) for path in PHASE9_TESTS + PHASE10_TESTS} | {("M", path) for path in PHASE9_TEST_REGISTRATION}',
    ), (
        'from tests.intelligence.phase11_runtime_registry import PHASE11_DOCS, PHASE11_RUNTIME, PHASE11_TESTS   # P11 の登録',
        '                                                                           + PHASE10_RUNTIME + PHASE11_RUNTIME}',
        '                                                                            + PHASE10_DOCS + PHASE11_DOCS}',
        '        ("A", path) for path in PHASE9_TESTS + PHASE10_TESTS + PHASE11_TESTS} | {',
        '            ("M", path) for path in PHASE9_TEST_REGISTRATION}',
    )),
    'tests/intelligence/test_personal_intelligence_boundary.py': ((
        '    assert _changes("--cached", "--name-status", P10_BASE, "--", "src") == {("A", p) for p in PHASE10_RUNTIME}',
        '    assert _changes("--cached", "--name-status", P10_BASE, "--", "docs") <= {("A", p) for p in PHASE10_DOCS}',
        '        ("A", p) for p in PHASE10_TESTS} | {("M", p) for p in PHASE10_TEST_REGISTRATION}',
        '        current = (REPO_ROOT / path).read_text(encoding="utf-8")',
        '    assert _git("diff", "--name-status", P10_A4, "HEAD", "--", "src") == ""',
        '    assert _git("diff", "--cached", "--name-status", P10_A4, "--", "src") == ""',
    ), (
        'from tests.intelligence.phase11_runtime_registry import (P11_BASE, PHASE11_DOCS, PHASE11_RUNTIME, PHASE11_TESTS,',
        '                                                         SANCTIONED_P11_P10_IMPORTERS)   # P11 の登録',
        '    assert _changes("--cached", "--name-status", P10_BASE, "--", "src") == {("A", p) for p in PHASE10_RUNTIME',
        '                                                                            + PHASE11_RUNTIME}',
        '    assert _changes("--cached", "--name-status", P10_BASE, "--", "docs") <= {("A", p) for p in PHASE10_DOCS',
        '                                                                             + PHASE11_DOCS}',
        '        ("A", p) for p in PHASE10_TESTS + PHASE11_TESTS} | {("M", p) for p in PHASE10_TEST_REGISTRATION}',
        '        current = _git("show", f"{P11_BASE}:{path}")             # P10 の登録は P10 の終わりまで（以後の差は P11 の guard が pin）',
        '            continue',
        '        if path.relative_to(REPO_ROOT).as_posix() in SANCTIONED_P11_P10_IMPORTERS:  # P11: governed な read の importer だけ',
        '            cross = {m: n for m, n in _imports(path)[0].items() if m.startswith("..")}',
        '            assert cross == SANCTIONED_P11_P10_IMPORTERS[path.relative_to(REPO_ROOT).as_posix()]   # 面は完全一致',
        '    assert _git("diff", "--name-status", P10_A4, "HEAD", "--", PHASE10_PACKAGE) == ""     # Phase 10 の src runtime は不変',
        '    assert _git("diff", "--cached", "--name-status", P10_A4, "--", PHASE10_PACKAGE) == ""',
    )),
}


def is_phase11_addition(status: str, path: str) -> bool:
    """Phase 11 の runtime の変化か。Phase 11 は凍結していないので、A1 以外の登録済み runtime は gate の中の修正（M）も受ける
    （A1 の不変は `test_personal_ui_boundary.py` が commit ・index ・worktree で別に守る）。"""
    if status in ADDITION_STATUSES and path in PHASE11_RUNTIME:
        return True
    return status == "M" and path in PHASE11_RUNTIME and path not in PHASE11_A1_RUNTIME


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


def only_phase11_registration(path: str, anchored: str, current: str) -> bool:
    """`P11_BASE` と現在の差が、宣言した登録（取り除いた行・加えた行）と完全に一致する（未登録の file は byte 一致）。"""
    declared_removed, declared_added = PHASE11_TEST_REGISTRATION.get(path, ((), ()))
    removed, added = registration_diff(anchored, current)
    return sorted(removed) == sorted(declared_removed) and sorted(added) == sorted(declared_added)


__all__ = ["ADDITION_STATUSES", "FORBIDDEN_P11_IMPORT_PARTS", "P11_A1", "P11_A2", "P11_A3", "P11_A5", "P11_ADAPTER", "P11_BASE",
           "P11_LOCAL_SERVER", "P11_SHELL_CACHE_NAME", "P11_SHELL_PRECACHE", "P11_STATIC_ASSETS", "P11_STATIC_BLOB_IDS",
           "P11_STATIC_ROUTES", "P11_UI_MODEL", "PHASE11_A1_RUNTIME", "PHASE11_A2_RUNTIME", "PHASE11_A3_RUNTIME",
           "PHASE11_DOCS", "PHASE11_PACKAGE", "PHASE11_PY_RUNTIME", "PHASE11_RUNTIME", "PHASE11_STATIC_DIR",
           "PHASE11_TESTS", "PHASE11_TEST_REGISTRATION", "SANCTIONED_P11_MODULES",
           "SANCTIONED_P11_P10_IMPORTERS", "SANCTIONED_P11_SERVER_STDLIB",
           "SANCTIONED_P11_P10_IMPORTS", "is_phase11_addition", "only_phase11_registration", "registration_diff"]
