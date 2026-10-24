"""Phase 13（Market Memory ／ Review State Memory）の runtime の面の登録（test helper。P13-A0 で導入）。

- `P13_BASE` ＝ P12.5 の設計の closeout の記録の commit（P13-A0 の登録はここから足す。A0 の commit 自身ではない ・固定）。
- `PHASE13_RUNTIME` は P13-A0 では空だった。P13-A1 で純粋な model の 4 file を `PHASE13_RUNTIME_AUTHORIZATION` と共に登録した。以後の追加は、監督が承認した
  gate（P13-A1 以後）で `PHASE13_RUNTIME_AUTHORIZATION` に gate ・anchor ・path を登録し、その gate の契約文書に path を書き、
  `test_market_memory_boundary.py` の registry の digest を更新して初めて認められる（registry の tuple に path を足すだけでは guard が落ちる）。
- `is_phase13_addition` が認めるのは登録済みの path の追加（`A` ／ `??`）だけ。修正（M）・未登録の path ・近い名前は認めない。
- 凍結の P7 〜 P12 の test に入れた登録の行は `PHASE13_TEST_REGISTRATION` に完全に列挙し、`only_phase13_registration` で `P13_BASE` との
  差分がそれと完全に一致することを確かめる（P12-A1 の `PHASE12_TEST_REGISTRATION` と同じ様式）。
- **importer の許可は P13-A2a の 1 file だけ**: `SANCTIONED_P13_P10_IMPORTERS` の adapter が P10 の governed な 5 つの名前だけを import する
  （P11 と同じ面 ・完全一致）。他の P13 の file ・他の凍結の package の import は無い。A1 の runtime の blob は `P13_A1` に pin する。
- P13-A3 は private な Memory Store ／ Rebuild の 3 file を足す（anchor ＝ `P13_A2A`）。filesystem の I/O は `memory_store.py` だけ
  （`memory_build.py` は adapter と store の面だけを使い、P10 の importer の許可は増やさない）。A2a の adapter の blob は `P13_A2A` に pin する。
- P13-A4a は純粋な Obsidian 投影の model の 1 file を足す（anchor ＝ Market Brain の roadmap の記録の commit）。I/O は無い（filesystem ・
  network ・process ・資格情報 ・scheduler）。A3 の runtime 3 file の blob は `P13_A3` に pin する。P10 の importer の許可は変えない。
- P13-A4a1 は後継の純粋な投影の契約の 1 file を足す（anchor ＝ `P13_A4A`）。public ／ private の identity の分離 ・I/O は無い。A4a の
  runtime の blob は `P13_A4A` に pin する（0.1.0 の model は変えない）。P10 の importer の許可は変えない。
- P13-A4b は Obsidian 投影の export の 2 file を足す（anchor ＝ `P13_A4A1`）。filesystem の I/O は `projection_store.py` だけ（2 つ目の狭く pin
  した許し ・A3 の許しは広げない）・`projection_build.py` は A3 ・A4a1 ・store の公開の面だけの orchestration。A4a1 の runtime の blob は
  `P13_A4A1` に pin する。P10 の importer の許可は変えない。
- P13-A5-0R は Windows の検証の計画の記録を `PHASE13_DOCS` に足すだけ（文書だけ ・runtime ・認可 ・importer の許可は変えない ・実行の承認ではない）。
- P13-A5-T は Windows の特性の記録を `PHASE13_DOCS` に足すだけ（文書だけ ・runtime ・認可 ・importer の許可は変えない ・実行の承認ではない）。
- H0-D1 は Home の情報の契約の記録を `PHASE13_DOCS` に足すだけ（文書だけ ・runtime ・認可 ・importer の許可は変えない ・実装の承認ではない）。
- M0-D1 は mobile の security と access の契約の記録を `PHASE13_DOCS` の最後に足すだけ（文書だけ ・runtime ・認可 ・importer の許可は変えない ・実装の承認ではない）。
記録: `docs/databank/PHASE13_A0_RUNTIME_SURFACE_REGISTRATION.md`。
"""
from __future__ import annotations

import difflib
from typing import Mapping, Sequence, Tuple

#: P12.5 の設計の closeout の記録の commit ＝ P13 の登録の base（固定。A0 の commit ではない）
P13_BASE = "aded7ee8621e9abac18d313009444675ab771ae6"
PHASE13_PACKAGE = "src/intelligence/market_memory"
ADDITION_STATUSES = ("A", "??")
#: 登録済みの Phase 13 の runtime（P13-A1: 純粋な Review State Memory の model 4 file。追加は監督の gate と `PHASE13_RUNTIME_AUTHORIZATION` の登録を要する）
PHASE13_A1_RUNTIME: Tuple[str, ...] = (
    'src/intelligence/market_memory/__init__.py',
    'src/intelligence/market_memory/canonical.py',
    'src/intelligence/market_memory/review_state_change.py',
    'src/intelligence/market_memory/review_state_sample.py',
)
#: P13-A1 の受理した anchor（A1 の runtime 4 file の blob はこの commit のまま ・A2a 以後の修正は認めない）
P13_A1 = "ccfc8e57885fabc5936a39034a9e816c66b2fbbc"
#: P13-A2a: P10 の governed な safe view の adapter（1 file）
PHASE13_A2A_RUNTIME: Tuple[str, ...] = ('src/intelligence/market_memory/governed_review_source.py',)
#: P13-A2a の受理した anchor（adapter の blob はこの commit のまま ・A3 以後の修正は認めない）
P13_A2A = "12de956637bb1df5fcff8846ba9d7fcb606421a3"
#: P13-A3: private な Memory Store ／ Rebuild（純粋な generation の model ・唯一の filesystem の module ・build の orchestration）
PHASE13_A3_RUNTIME: Tuple[str, ...] = (
    'src/intelligence/market_memory/memory_build.py',
    'src/intelligence/market_memory/memory_generation.py',
    'src/intelligence/market_memory/memory_store.py',
)
#: P13-A3 の受理した anchor（Memory Store の runtime 3 file の blob はこの commit のまま ・A4a 以後の修正は認めない）
P13_A3 = "12dcfb2143527ca44a3e55afa7a2daa9bab2c33d"
#: P13-A4a: 純粋な Obsidian 投影の model（counts-only の Markdown ・identity ・公開の状態の分類 ・I/O は無い）
PHASE13_A4A_RUNTIME: Tuple[str, ...] = ('src/intelligence/market_memory/memory_projection.py',)
#: P13-A4a の受理した anchor（0.1.0 の投影の model の blob はこの commit のまま ・A4a1 以後の修正は認めない）
P13_A4A = "bc7f990df2ae8983a27a1d02b1f8a0a1738c5dd1"
#: P13-A4a1: 後継の純粋な投影の契約（public ／ private の identity の分離 ・frontmatter ・中断の staging の継続 ・I/O は無い）
PHASE13_A4A1_RUNTIME: Tuple[str, ...] = ('src/intelligence/market_memory/projection_contract.py',)
#: P13-A4a1 の受理した anchor（後継の投影の契約の blob はこの commit のまま ・A4b 以後の修正は認めない）
P13_A4A1 = "5181f59e6c639d72eeba37067fa66a4d82d27a38"
#: P13-A4b: Obsidian 投影の export（2 つ目の filesystem の module ・orchestration）
PHASE13_A4B_RUNTIME: Tuple[str, ...] = (
    'src/intelligence/market_memory/projection_build.py',
    'src/intelligence/market_memory/projection_store.py',
)
PHASE13_RUNTIME: Tuple[str, ...] = tuple(sorted(PHASE13_A1_RUNTIME + PHASE13_A2A_RUNTIME + PHASE13_A3_RUNTIME + PHASE13_A4A_RUNTIME
                                                + PHASE13_A4A1_RUNTIME + PHASE13_A4B_RUNTIME))
#: runtime の追加の認可（gate の id, その gate が始まる anchor の commit, 認めた path の tuple, 契約文書）。P13-A0 では空。
#: guard: `PHASE13_RUNTIME` の全ての path はちょうど 1 つの認可に現れ、anchor は HEAD の祖先で、path は anchor に存在せず、文書に path が在る
PHASE13_RUNTIME_AUTHORIZATION: Tuple[Tuple[str, str, Tuple[str, ...], str], ...] = (
    ("P13-A1", "4d464c30e4598d2ad5a0cee5a34ac366414fbde3", PHASE13_A1_RUNTIME,   # anchor ＝ P13-A0 の commit（直前に受理した HEAD）
     "docs/databank/PHASE13_A1_REVIEW_STATE_MODEL.md"),
    ("P13-A2a", P13_A1, PHASE13_A2A_RUNTIME,   # anchor ＝ P13-A1 の commit（直前に受理した HEAD）
     "docs/databank/PHASE13_A2A_GOVERNED_P10_ADAPTER.md"),
    ("P13-A3", P13_A2A, PHASE13_A3_RUNTIME,   # anchor ＝ P13-A2a の commit（直前に受理した HEAD）
     "docs/databank/PHASE13_A3_MEMORY_STORE.md"),
    ("P13-A4a", "5e5f015ecebf64116f9c1721c36d9d41fa9dc1c7", PHASE13_A4A_RUNTIME,   # anchor ＝ roadmap の記録の commit（直前に受理した HEAD）
     "docs/databank/PHASE13_A4A_PROJECTION_MODEL.md"),
    ("P13-A4a1", P13_A4A, PHASE13_A4A1_RUNTIME,   # anchor ＝ P13-A4a の commit（直前に受理した HEAD）
     "docs/databank/PHASE13_A4A1_PROJECTION_RECONCILIATION.md"),
    ("P13-A4b", P13_A4A1, PHASE13_A4B_RUNTIME,   # anchor ＝ P13-A4a1 の commit（直前に受理した HEAD）
     "docs/databank/PHASE13_A4B_PROJECTION_EXPORT.md"),
)
PHASE13_TESTS: Tuple[str, ...] = ("tests/intelligence/phase13_runtime_registry.py",
                                  "tests/intelligence/test_market_memory_boundary.py",
                                  "tests/intelligence/test_market_memory_model.py",
                                  "tests/intelligence/test_market_memory_governed_source.py",
                                  "tests/intelligence/test_market_memory_generation.py",
                                  "tests/intelligence/test_market_memory_store.py",
                                  "tests/intelligence/test_market_memory_build.py",
                                  "tests/intelligence/test_market_memory_projection.py",
                                  "tests/intelligence/test_market_memory_projection_contract.py",
                                  "tests/intelligence/test_market_memory_projection_store.py",
                                  "tests/intelligence/test_market_memory_projection_build.py")
PHASE13_DOCS: Tuple[str, ...] = ("docs/databank/PHASE13_A0_RUNTIME_SURFACE_REGISTRATION.md",
                                 "docs/databank/PHASE13_A1_REVIEW_STATE_MODEL.md",
                                 "docs/databank/PHASE13_A2A_GOVERNED_P10_ADAPTER.md",
                                 "docs/databank/PHASE13_A3_MEMORY_STORE.md",
                                 "docs/databank/MARKET_BRAIN_ROADMAP_RECORD.md",   # 長期の roadmap の記録（文書だけ ・実装の承認ではない）
                                 "docs/databank/PHASE13_A4A_PROJECTION_MODEL.md",
                                 "docs/databank/PHASE13_A4A1_PROJECTION_RECONCILIATION.md",
                                 "docs/databank/PHASE13_A4B_PROJECTION_EXPORT.md",
                                 "docs/databank/PHASE13_A5_WINDOWS_VALIDATION_PLAN.md",   # A5-0R: 計画の記録だけ（実行の承認ではない）
                                 "docs/databank/PHASE13_A5T_WINDOWS_CHARACTERIZATION_RECORD.md",   # A5-T: 特性の記録だけ（実行の承認ではない）
                                 "docs/databank/H0_D1_HOME_INFORMATION_CONTRACT.md",   # H0-D1: Home の情報の契約の記録だけ（実装の承認ではない）
                                 "docs/databank/M0_D1_MOBILE_SECURITY_ACCESS_CONTRACT.md")   # M0-D1: mobile の security と access の契約の記録だけ（実装の承認ではない）
#: P13-A2a: P10 の governed な read の面（P11 の `SANCTIONED_P11_P10_IMPORTS` と同じ 5 つの名前 ・完全一致）。store の class ・private な
#: snapshot ・executor は含まない。importer は adapter の 1 file だけ
SANCTIONED_P13_P10_IMPORTS: Mapping[str, frozenset] = {
    "..personal_intelligence.p9_view": frozenset({"P9ViewError", "read_p9_safe_view"}),
    "..personal_intelligence.personal_projection": frozenset({"personal_safe_projection"}),
    "..personal_intelligence.review_view": frozenset({"ReviewViewError", "read_personal_review"}),
}
SANCTIONED_P13_P10_IMPORTERS: Mapping[str, Mapping[str, frozenset]] = {'src/intelligence/market_memory/governed_review_source.py': SANCTIONED_P13_P10_IMPORTS}
#: 凍結の P10 の importer の guard（`test_personal_intelligence_boundary.py`）に P13-A2a が足した行（完全一致 ・この file だけ）
PHASE13_A2A_IMPORTER_LINES: Tuple[str, ...] = (
    'from tests.intelligence.phase13_runtime_registry import SANCTIONED_P13_P10_IMPORTERS   # P13-A2a: governed な read の importer だけ',
    '        if path.relative_to(REPO_ROOT).as_posix() in SANCTIONED_P13_P10_IMPORTERS:  # P13-A2a: governed な read の importer だけ',
    '            cross = {m: n for m, n in _imports(path)[0].items() if m.startswith("..")}',
    '            assert cross == SANCTIONED_P13_P10_IMPORTERS[path.relative_to(REPO_ROOT).as_posix()]   # 面は完全一致',
    '            continue',
)
#: P13 の code（将来）に文字としても在ってはならない凍結の package ・module の名前（textual な import の禁止は全て不変。A2a の adapter だけ
#: `personal_intelligence` を含む）
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
        'from tests.intelligence.phase13_runtime_registry import SANCTIONED_P13_P10_IMPORTERS   # P13-A2a: governed な read の importer だけ',
        '                                                                            + PHASE11_RUNTIME + PHASE12_RUNTIME + PHASE13_RUNTIME}',
        '                                                                             + PHASE11_DOCS + PHASE12_DOCS + PHASE13_DOCS}',
        '        ("A", p) for p in PHASE10_TESTS + PHASE11_TESTS + PHASE12_TESTS + PHASE13_TESTS} | {',
        '            ("M", p) for p in PHASE10_TEST_REGISTRATION}',
        '            continue',
        '        if path.relative_to(REPO_ROOT).as_posix() in SANCTIONED_P13_P10_IMPORTERS:  # P13-A2a: governed な read の importer だけ',
        '            cross = {m: n for m, n in _imports(path)[0].items() if m.startswith("..")}',
        '            assert cross == SANCTIONED_P13_P10_IMPORTERS[path.relative_to(REPO_ROOT).as_posix()]   # 面は完全一致',
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
        '    excluded = [f":(exclude,literal){p}" for p in PHASE12_RUNTIME]',
        '    assert _git("diff", "--name-status", P12_VALIDATED_TREE, "HEAD", "--", "src") == ""         # validated tree 以後に src は不変',
        '    assert _git("diff", "--name-status", P12_A6, "HEAD", "--", "src") == ""                 # 設計の gate は src を変えない',
        '    assert _git("status", "--porcelain", "--", "src") == ""',
        '    assert _git("diff", "--name-status", P12_A6, "HEAD", "--", "src") == ""                 # 設計の gate は src を変えない',
        '    assert _git("status", "--porcelain", "--", "src") == ""',
        '    assert not (REPO_ROOT / "src/intelligence/market_memory").exists()                       # P13 の runtime は存在しない',
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
        '    excluded = [f":(exclude,literal){p}" for p in PHASE12_RUNTIME + PHASE13_RUNTIME]   # P13-A1: 登録した P13 の追加だけを除く（凍結の runtime の修正は不可）',
        '    assert _changes("--name-status", P12_VALIDATED_TREE, "HEAD", "--", "src") <= {("A", p) for p in PHASE13_RUNTIME}   # 以後は登録した P13 の追加だけ',
        '    _assert_src_unchanged_except_registered_p13_additions()                                # 設計の gate は src を変えない',
        '    _assert_src_unchanged_except_registered_p13_additions()                                # 設計の gate は src を変えない',
        '    for revision in (P12_A6, P12_5_DESIGN_ANCHOR, P13_BASE):                                 # A2 の時点に P13 の runtime は無かった（歴史の事実）',
        '        assert not _git("ls-tree", revision, "--", PHASE13_PACKAGE).strip(), revision',
        '    assert PHASE13_RUNTIME or not P13_PACKAGE_DIR.exists()                                   # 現在: 登録が空の間は package も無い',
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


__all__ = ["ADDITION_STATUSES", "FORBIDDEN_P13_TOKENS", "P13_A1", "P13_A2A", "P13_A3", "P13_A4A", "P13_A4A1", "P13_BASE", "PHASE13_A1_RUNTIME",
           "PHASE13_A2A_IMPORTER_LINES", "PHASE13_A2A_RUNTIME", "PHASE13_A3_RUNTIME", "PHASE13_A4A_RUNTIME",
           "PHASE13_A4A1_RUNTIME", "PHASE13_A4B_RUNTIME", "PHASE13_DOCS", "PHASE13_PACKAGE", "PHASE13_RUNTIME",
           "PHASE13_RUNTIME_AUTHORIZATION", "PHASE13_TESTS", "PHASE13_TEST_REGISTRATION", "SANCTIONED_P13_P10_IMPORTERS",
           "SANCTIONED_P13_P10_IMPORTS", "is_phase13_addition",
           "only_phase13_registration", "registration_diff"]
