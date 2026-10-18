"""Phase 13（Market Memory ／ Review State Memory）の runtime の面の登録（test helper。P13-A0 で導入）。

- `P13_BASE` ＝ P12.5 の設計の closeout の記録の commit（P13-A0 の登録はここから足す。A0 の commit 自身ではない ・固定）。
- `PHASE13_RUNTIME` は **P13-A0 では空**。P13 の `src/` の file は 1 つも無い（package も `__init__` も無い）。将来の追加は、監督が承認した
  gate（P13-A1 以後）で `PHASE13_RUNTIME_AUTHORIZATION` に gate ・anchor ・path を登録し、その gate の契約文書に path を書き、
  `test_market_memory_boundary.py` の registry の digest を更新して初めて認められる（registry の tuple に path を足すだけでは guard が落ちる）。
- `is_phase13_addition` が認めるのは登録済みの path の追加（`A` ／ `??`）だけ。修正（M）・未登録の path ・近い名前は認めない。
- 凍結の P7 〜 P12 の test に入れた登録の行は `PHASE13_TEST_REGISTRATION` に完全に列挙し、`only_phase13_registration` で `P13_BASE` との
  差分がそれと完全に一致することを確かめる（P12-A1 の `PHASE12_TEST_REGISTRATION` と同じ様式）。
- **importer の許可は無い**: P13 が凍結の package（personal_intelligence ほか）を import する許可は別の gate（P13-A2a）で、ここには無い。
記録: `docs/databank/PHASE13_A0_RUNTIME_SURFACE_REGISTRATION.md`。
"""
from __future__ import annotations

import difflib
from typing import Mapping, Sequence, Tuple

#: P12.5 の設計の closeout の記録の commit ＝ P13 の登録の base（固定。A0 の commit ではない）
P13_BASE = "aded7ee8621e9abac18d313009444675ab771ae6"
PHASE13_PACKAGE = "src/intelligence/market_memory"
ADDITION_STATUSES = ("A", "??")
#: 登録済みの Phase 13 の runtime（P13-A0: **空**。追加は監督の gate と `PHASE13_RUNTIME_AUTHORIZATION` の登録を要する）
PHASE13_RUNTIME: Tuple[str, ...] = ()
#: runtime の追加の認可（gate の id, その gate が始まる anchor の commit, 認めた path の tuple, 契約文書）。P13-A0 では空。
#: guard: `PHASE13_RUNTIME` の全ての path はちょうど 1 つの認可に現れ、anchor は HEAD の祖先で、path は anchor に存在せず、文書に path が在る
PHASE13_RUNTIME_AUTHORIZATION: Tuple[Tuple[str, str, Tuple[str, ...], str], ...] = ()
PHASE13_TESTS: Tuple[str, ...] = ("tests/intelligence/phase13_runtime_registry.py",
                                  "tests/intelligence/test_market_memory_boundary.py")
PHASE13_DOCS: Tuple[str, ...] = ("docs/databank/PHASE13_A0_RUNTIME_SURFACE_REGISTRATION.md",)
#: P13 の code（将来）に文字としても在ってはならない凍結の package ・module の名前（textual な import の禁止は全て不変）
FORBIDDEN_P13_TOKENS: Tuple[str, ...] = ("screener_intelligence", "watchlist_thesis_intelligence", "personal_intelligence",
                                         "personal_ui", "intelligence.automation", "narrative_intelligence", "synthesis_model",
                                         "theme_intelligence", "jquants", "anthropic", "openai")


def is_phase13_addition(status: str, path: str) -> bool:
    """登録済みの Phase 13 の runtime の追加（A ／ ??）だけ。修正 ・未登録 ・近い名前 ・package の外は認めない。"""
    return status in ADDITION_STATUSES and path in PHASE13_RUNTIME and path.startswith(PHASE13_PACKAGE + "/")


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


#: 凍結の P7 〜 P12 の test に入れた登録（path → (取り除いた行, 加えた行)）。P13-A0 で確定。src の面の集合に `PHASE13_*` を足し、
#: P12 の登録の検査を `P13_BASE` の snapshot に pin し直し、P12 の凍結 ・P12.5 の closeout の src の不変を「登録した P13 の追加だけ」に狭める。
#: importer の test（`*_no_other_code_imports_it`）には触れない
PHASE13_TEST_REGISTRATION: Mapping[str, Tuple[Tuple[str, ...], Tuple[str, ...]]] = {
    'tests/intelligence/phase7_runtime_registry.py': ((
        '                                                   + PHASE9_RUNTIME + PHASE10_RUNTIME + PHASE11_RUNTIME + PHASE12_RUNTIME)',
        '                                                    + PHASE11_RUNTIME + PHASE12_RUNTIME)',
        '            or is_phase12_addition(status, path))                 # P12-A1: 凍結していない Phase 12 の runtime も',
    ), (
        'from tests.intelligence.phase13_runtime_registry import PHASE13_RUNTIME, is_phase13_addition   # P13-A0: Phase 13（登録だけ）',
        '                                                   + PHASE9_RUNTIME + PHASE10_RUNTIME + PHASE11_RUNTIME + PHASE12_RUNTIME',
        '                                                   + PHASE13_RUNTIME)',
        '                                                    + PHASE11_RUNTIME + PHASE12_RUNTIME + PHASE13_RUNTIME)',
        '            or is_phase12_addition(status, path)                  # P12-A1: 凍結していない Phase 12 の runtime も',
        '            or is_phase13_addition(status, path))                 # P13-A0: 登録済みの Phase 13 の追加だけ（A0 では空）',
    )),
    'tests/intelligence/test_narrative_intelligence_boundary.py': ((
        '                       + PHASE10_RUNTIME + PHASE11_RUNTIME + PHASE12_RUNTIME}               # commit ／ index の差',
        '                                            + PHASE11_DOCS + PHASE12_DOCS}',
        '        ("A", path) for path in PHASE8_TESTS + PHASE9_TESTS + PHASE10_TESTS + PHASE11_TESTS + PHASE12_TESTS}',
        '                                              + PHASE9_RUNTIME + PHASE10_RUNTIME + PHASE11_RUNTIME + PHASE12_RUNTIME)',
        '        + PHASE12_RUNTIME}                                                                       # 追加だけ',
        '        + PHASE12_RUNTIME}                                                                       # A4b と P8 〜 P12 の追加だけ',
        '                                                                                  + PHASE11_RUNTIME + PHASE12_RUNTIME}',
    ), (
        'from tests.intelligence.phase13_runtime_registry import PHASE13_DOCS, PHASE13_RUNTIME, PHASE13_TESTS   # P13-A0 の登録（空の runtime）',
        '                       + PHASE10_RUNTIME + PHASE11_RUNTIME + PHASE12_RUNTIME + PHASE13_RUNTIME}   # commit ／ index の差',
        '                                            + PHASE11_DOCS + PHASE12_DOCS + PHASE13_DOCS}',
        '        ("A", path) for path in PHASE8_TESTS + PHASE9_TESTS + PHASE10_TESTS + PHASE11_TESTS + PHASE12_TESTS + PHASE13_TESTS}',
        '                                              + PHASE9_RUNTIME + PHASE10_RUNTIME + PHASE11_RUNTIME + PHASE12_RUNTIME',
        '                                              + PHASE13_RUNTIME)',
        '        + PHASE12_RUNTIME + PHASE13_RUNTIME}                                                     # 追加だけ',
        '        + PHASE12_RUNTIME + PHASE13_RUNTIME}                                                     # A4b と P8 〜 P13 の追加だけ',
        '                                                                                  + PHASE11_RUNTIME + PHASE12_RUNTIME',
        '                                                                                  + PHASE13_RUNTIME}',
    )),
    'tests/intelligence/test_screener_intelligence_boundary.py': ((
        '        ("A", path) for path in PHASE9_TESTS + PHASE10_TESTS + PHASE11_TESTS + PHASE12_TESTS}',
        '                       + PHASE12_RUNTIME}',
        '                       or is_phase12_addition(line[:2].strip(), line[3:]))]',
        '                        ("A", path) for path in PHASE9_DOCS + PHASE10_DOCS + PHASE11_DOCS + PHASE12_DOCS}',
    ), (
        'from tests.intelligence.phase13_runtime_registry import (PHASE13_DOCS, PHASE13_RUNTIME, PHASE13_TESTS,',
        '                                                         is_phase13_addition)   # P13-A0 の登録（空の runtime）',
        '        ("A", path) for path in PHASE9_TESTS + PHASE10_TESTS + PHASE11_TESTS + PHASE12_TESTS + PHASE13_TESTS}',
        '                       + PHASE12_RUNTIME + PHASE13_RUNTIME}',
        '                       or is_phase12_addition(line[:2].strip(), line[3:])',
        '                       or is_phase13_addition(line[:2].strip(), line[3:]))]',
        '                        ("A", path) for path in PHASE9_DOCS + PHASE10_DOCS + PHASE11_DOCS + PHASE12_DOCS + PHASE13_DOCS}',
    )),
    'tests/intelligence/test_watchlist_thesis_boundary.py': ((
        '                                                                           + PHASE12_RUNTIME}',
        '                                                                            + PHASE10_DOCS + PHASE11_DOCS + PHASE12_DOCS}',
        '        ("A", path) for path in PHASE9_TESTS + PHASE10_TESTS + PHASE11_TESTS + PHASE12_TESTS} | {',
    ), (
        'from tests.intelligence.phase13_runtime_registry import PHASE13_DOCS, PHASE13_RUNTIME, PHASE13_TESTS   # P13-A0 の登録（空の runtime）',
        '                                                                           + PHASE12_RUNTIME + PHASE13_RUNTIME}',
        '                                                                            + PHASE10_DOCS + PHASE11_DOCS + PHASE12_DOCS',
        '                                                                            + PHASE13_DOCS}',
        '        ("A", path) for path in PHASE9_TESTS + PHASE10_TESTS + PHASE11_TESTS + PHASE12_TESTS + PHASE13_TESTS} | {',
    )),
    'tests/intelligence/test_personal_intelligence_boundary.py': ((
        '                                                                            + PHASE11_RUNTIME + PHASE12_RUNTIME}',
        '                                                                             + PHASE11_DOCS + PHASE12_DOCS}',
        '        ("A", p) for p in PHASE10_TESTS + PHASE11_TESTS + PHASE12_TESTS} | {("M", p) for p in PHASE10_TEST_REGISTRATION}',
    ), (
        'from tests.intelligence.phase13_runtime_registry import PHASE13_DOCS, PHASE13_RUNTIME, PHASE13_TESTS   # P13-A0 の登録（空の runtime）',
        '                                                                            + PHASE11_RUNTIME + PHASE12_RUNTIME + PHASE13_RUNTIME}',
        '                                                                             + PHASE11_DOCS + PHASE12_DOCS + PHASE13_DOCS}',
        '        ("A", p) for p in PHASE10_TESTS + PHASE11_TESTS + PHASE12_TESTS + PHASE13_TESTS} | {',
        '            ("M", p) for p in PHASE10_TEST_REGISTRATION}',
    )),
    'tests/intelligence/test_personal_ui_boundary.py': ((
        '                                                                            + PHASE12_RUNTIME}',
        '                                                                             + PHASE12_DOCS}',
        '        ("A", p) for p in PHASE11_TESTS + PHASE12_TESTS} | {("M", p) for p in PHASE11_TEST_REGISTRATION}',
    ), (
        'from tests.intelligence.phase13_runtime_registry import PHASE13_DOCS, PHASE13_RUNTIME, PHASE13_TESTS   # P13-A0 の登録（空の runtime）',
        '                                                                            + PHASE12_RUNTIME + PHASE13_RUNTIME}',
        '                                                                             + PHASE12_DOCS + PHASE13_DOCS}',
        '        ("A", p) for p in PHASE11_TESTS + PHASE12_TESTS + PHASE13_TESTS} | {("M", p) for p in PHASE11_TEST_REGISTRATION}',
    )),
    'tests/intelligence/test_automation_boundary.py': ((
        'P13_PACKAGE_DIR = REPO_ROOT / "src/intelligence/market_memory"                        # 存在してはならない（P13 は未着手）',
        '    assert _changes("--cached", "--name-status", P12_BASE, "--", "src") == {("A", p) for p in PHASE12_RUNTIME}',
        '    assert _changes("--cached", "--name-status", P12_BASE, "--", "docs") <= {("A", p) for p in PHASE12_DOCS}',
        '        ("A", p) for p in PHASE12_TESTS} | {("M", p) for p in PHASE12_TEST_REGISTRATION}',
        '        current = (REPO_ROOT / path).read_text(encoding="utf-8")',
        '               if not is_phase12_addition(line[:2].strip(), line[3:])]',
        '    assert _git("diff", "--name-status", P12_VALIDATED_TREE, "HEAD", "--", "src") == ""         # validated tree 以後に src は不変',
        '    assert _git("diff", "--name-status", P12_A6, "HEAD", "--", "src") == ""                 # 設計の gate は src を変えない',
        '    assert _git("status", "--porcelain", "--", "src") == ""',
        '    assert _git("diff", "--name-status", P12_A6, "HEAD", "--", "src") == ""                 # 設計の gate は src を変えない',
        '    assert _git("status", "--porcelain", "--", "src") == ""',
        '    assert _git("diff", "--name-status", P12_A6, "HEAD", "--", "src") == ""                      # P12.5 の全 gate で src は不変',
        '    assert _git("status", "--porcelain", "--", "src") == ""',
        '    assert not P13_PACKAGE_DIR.exists()                                                            # P13 の runtime は存在しない',
        '    assert tracked_now == set(_git("ls-tree", "-r", "--name-only", P12_A6, "src").splitlines())    # src の file の集合は anchor と同じ',
    ), (
        'from tests.intelligence.phase13_runtime_registry import (P13_BASE, PHASE13_DOCS, PHASE13_PACKAGE, PHASE13_RUNTIME, PHASE13_TESTS,',
        '                                                         is_phase13_addition)   # P13-A0 の登録（空の runtime ・importer の許可は無い）',
        'P13_PACKAGE_DIR = REPO_ROOT / PHASE13_PACKAGE                                           # P13-A0: 登録が空の間は存在してはならない',
        'def _assert_src_unchanged_except_registered_p13_additions() -> None:',
        '    """P12 A-track v1 の anchor 以後、src の差は登録済みの Phase 13 の追加（A ・P13-A0 では空）だけ。修正 ・未登録の追加は失敗。"""',
        '    assert _changes("--name-status", P12_A6, "HEAD", "--", "src") <= {("A", p) for p in PHASE13_RUNTIME}',
        '    assert _changes("--cached", "--name-status", P12_A6, "--", "src") <= {("A", p) for p in PHASE13_RUNTIME}',
        '    pending = [line for line in _git("status", "--porcelain", "--", "src").splitlines()',
        '               if not is_phase13_addition(line[:2].strip(), line[3:])]',
        '    assert pending == []',
        '',
        '',
        '    assert _changes("--cached", "--name-status", P12_BASE, "--", "src") == {("A", p) for p in PHASE12_RUNTIME + PHASE13_RUNTIME}',
        '    assert _changes("--cached", "--name-status", P12_BASE, "--", "docs") <= {("A", p) for p in PHASE12_DOCS + PHASE13_DOCS}',
        '        ("A", p) for p in PHASE12_TESTS + PHASE13_TESTS} | {("M", p) for p in PHASE12_TEST_REGISTRATION}',
        '        current = _git("show", f"{P13_BASE}:{path}")             # P12 の登録は P12 の終わりまで（以後の差は P13 の guard が pin）',
        '               if not (is_phase12_addition(line[:2].strip(), line[3:]) or is_phase13_addition(line[:2].strip(), line[3:]))]',
        '    assert _changes("--name-status", P12_VALIDATED_TREE, "HEAD", "--", "src") <= {("A", p) for p in PHASE13_RUNTIME}   # 以後は登録した P13 の追加だけ',
        '    _assert_src_unchanged_except_registered_p13_additions()                                # 設計の gate は src を変えない',
        '    _assert_src_unchanged_except_registered_p13_additions()                                # 設計の gate は src を変えない',
        '    _assert_src_unchanged_except_registered_p13_additions()                                     # P12.5 の全 gate で src は不変',
        '    assert not _git("ls-tree", P12_5_DESIGN_ANCHOR, "--", PHASE13_PACKAGE).strip()                 # 設計の closeout の anchor に P13 の runtime は無かった（歴史の事実）',
        '    assert not _git("ls-tree", P13_BASE, "--", PHASE13_PACKAGE).strip()                           # P13 の登録の base にも無い',
        '    assert PHASE13_RUNTIME or not P13_PACKAGE_DIR.exists()                                        # 登録が空の間は package も無い',
        '    tracked_at_anchor = set(_git("ls-tree", "-r", "--name-only", P12_A6, "src").splitlines())',
        '    assert tracked_at_anchor <= tracked_now and tracked_now - tracked_at_anchor <= set(PHASE13_RUNTIME)   # 以後は登録した P13 の追加だけ',
    )),
}


def only_phase13_registration(path: str, anchored: str, current: str) -> bool:
    """`P13_BASE` と現在の差が、宣言した登録（取り除いた行・加えた行）と完全に一致する（未登録の file は byte 一致）。"""
    declared_removed, declared_added = PHASE13_TEST_REGISTRATION.get(path, ((), ()))
    removed, added = registration_diff(anchored, current)
    return sorted(removed) == sorted(declared_removed) and sorted(added) == sorted(declared_added)


__all__ = ["ADDITION_STATUSES", "FORBIDDEN_P13_TOKENS", "P13_BASE", "PHASE13_DOCS", "PHASE13_PACKAGE", "PHASE13_RUNTIME",
           "PHASE13_RUNTIME_AUTHORIZATION", "PHASE13_TESTS", "PHASE13_TEST_REGISTRATION", "is_phase13_addition",
           "only_phase13_registration", "registration_diff"]
