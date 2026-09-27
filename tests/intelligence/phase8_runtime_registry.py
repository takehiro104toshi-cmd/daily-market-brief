"""Phase 8 の runtime ／ test ／ 文書の登録（test helper。P8-A1 で導入。D-P8-A0-12）。

Phase 6 ／ Phase 7 の凍結 guard は「runtime surface（`src` ほか）と Phase 7 の文書 ／ test が変わっていない」ことを守る。
Phase 8 の package は `src` の下に**新規追加**されるため、それらの guard から見えなくする範囲をここで一度だけ宣言する。

- 対象は `PHASE8_RUNTIME` に列挙した file だけ（完全一致。glob ・prefix ・subdirectory は対象外にならない）。
- 登録は追加（`git diff --name-status` の A、`git status --porcelain` の A / ??）だけを認める。変更 ・削除 ・改名は認めない。
- Phase 6 の guard は `phase7_runtime_registry` の除外（`PHASE7_EXCLUDED_PATHSPECS` ／ `is_phase7_addition`）を使うので、
  その 2 つだけが本 registry の `PHASE8_RUNTIME` を読む。Phase 6 の test は変えない。
- Phase 7 の test に入れた登録の行は `PHASE7_TEST_REGISTRATION` に完全に列挙し、Phase 8 の guard
  （`test_screener_intelligence_boundary.py`）が P8-A0 の anchor との差と完全一致することを確かめる。
- 以後の Phase 8 の gate は本 file（と Phase 8 の guard）だけを更新し、Phase 6 ／ 7 の test を触らない。
"""
from __future__ import annotations

import difflib
from typing import Mapping, Sequence, Tuple

#: P8-A0 の凍結 anchor（Phase 7 の test への登録の差はここから測る）
P8_A0 = "76ebf0ccf647517df6762f4cc04a319a8207eff0"
#: P8-A1 の凍結 anchor（identity の runtime はここと byte 一致）
P8_A1 = "4162e9c5b934456e528288b99a5908069a2f6624"
PHASE8_PACKAGE = "src/intelligence/screener_intelligence"
#: 登録済みの Phase 8 runtime（P8-A1: __init__ / identity_model / identity_resolver / identity_store、
#: P8-A2: observation_model / observation_resolver / observation_store）
PHASE8_A1_RUNTIME: Tuple[str, ...] = tuple(f"{PHASE8_PACKAGE}/{name}.py" for name in (
    "__init__", "identity_model", "identity_resolver", "identity_store"))
PHASE8_RUNTIME: Tuple[str, ...] = tuple(f"{PHASE8_PACKAGE}/{name}.py" for name in (
    "__init__", "identity_model", "identity_resolver", "identity_store", "observation_model", "observation_resolver",
    "observation_store"))
#: 登録済みの Phase 8 の test（追加だけ）
PHASE8_TESTS: Tuple[str, ...] = ("tests/intelligence/phase8_runtime_registry.py",
                                 "tests/intelligence/test_screener_identity.py",
                                 "tests/intelligence/test_screener_intelligence_boundary.py",
                                 "tests/intelligence/test_screener_observation.py")
#: 登録済みの Phase 8 の文書（追加だけ）
PHASE8_DOCS: Tuple[str, ...] = ("docs/databank/PHASE8_SCREENER_INTELLIGENCE_ARCHITECTURE_AUDIT.md",
                                "docs/databank/PHASE8_ISSUER_SECURITY_IDENTITY_CONTRACT.md",
                                "docs/databank/PHASE8_PIT_OBSERVATION_CONTRACT.md")
ADDITION_STATUSES = ("A", "??")

_TEST_DIR = "tests/intelligence"
#: Phase 7 の test に入れた登録（path → (取り除いた行, 加えた行)）。行は改行を含まない
PHASE7_TEST_REGISTRATION: Mapping[str, Tuple[Tuple[str, ...], Tuple[str, ...]]] = {
    f"{_TEST_DIR}/phase7_runtime_registry.py": ((
        'PHASE7_EXCLUDED_PATHSPECS: Tuple[str, ...] = tuple(f":(exclude,literal){path}" for path in PHASE7_RUNTIME)',
        '    return status in ADDITION_STATUSES and path in PHASE7_RUNTIME',
    ), (
        'from tests.intelligence.phase8_runtime_registry import PHASE8_RUNTIME   # P8-A1: Phase 8 の登録済み runtime（完全一致）',
        '',
        'PHASE7_EXCLUDED_PATHSPECS: Tuple[str, ...] = tuple(f":(exclude,literal){path}" for path in PHASE7_RUNTIME + PHASE8_RUNTIME)',
        '    return status in ADDITION_STATUSES and path in PHASE7_RUNTIME + PHASE8_RUNTIME',
    )),
    f"{_TEST_DIR}/test_narrative_intelligence_boundary.py": ((
        '    assert changes == {("A", path) for path in PHASE7_RUNTIME}                            # commit ／ index の差',
        '                       ("A", P8_A0_DOC)}',
        '    assert changed <= {("M", path) for path in PHASE6_TEST_REGISTRATION} | {("A", path) for path in PHASE7_TESTS}',
        '    assert PHASE7_EXCLUDED_PATHSPECS == tuple(f":(exclude,literal){path}" for path in PHASE7_RUNTIME)',
        '    assert changed <= {("A", f"{PHASE7_PACKAGE}/{name}.py") for name in (*A4A_MODULES, *A4B_MODULES)}  # 追加だけ',
        '    assert changed <= {("A", f"{PHASE7_PACKAGE}/{name}.py") for name in A4B_MODULES}   # A4a の後は A4b の追加だけ',
        '    assert _git("diff", "--name-status", P7_A4B, "--", "src", "knowledge", "config.yaml", ".github", "docs/v2",',
        '                "docs/pages") == ""                                                         # runtime ／ 公開面の変更なし',
    ), (
        'from tests.intelligence.phase8_runtime_registry import PHASE8_DOCS, PHASE8_RUNTIME, PHASE8_TESTS   # P8-A1 の登録',
        '    assert changes == {("A", path) for path in PHASE7_RUNTIME + PHASE8_RUNTIME}           # commit ／ index の差',
        '                       ("A", P8_A0_DOC)} | {("A", path) for path in PHASE8_DOCS}',
        '    assert changed <= {("M", path) for path in PHASE6_TEST_REGISTRATION} | {("A", path) for path in PHASE7_TESTS} | {',
        '        ("A", path) for path in PHASE8_TESTS}',
        '    assert PHASE7_EXCLUDED_PATHSPECS == tuple(f":(exclude,literal){path}" for path in PHASE7_RUNTIME + PHASE8_RUNTIME)',
        '    assert changed <= {("A", f"{PHASE7_PACKAGE}/{name}.py") for name in (*A4A_MODULES, *A4B_MODULES)} | {',
        '        ("A", path) for path in PHASE8_RUNTIME}                                           # 追加だけ',
        '    assert changed <= {("A", f"{PHASE7_PACKAGE}/{name}.py") for name in A4B_MODULES} | {',
        '        ("A", path) for path in PHASE8_RUNTIME}                                           # A4b と P8 の追加だけ',
        '    assert {tuple(line.split("\\t")) for line in _git("diff", "--name-status", P7_A4B, "--", "src", "knowledge",',
        '            "config.yaml", ".github", "docs/v2", "docs/pages").splitlines()} <= {("A", path) for path in PHASE8_RUNTIME}',
    )),
}


def is_phase8_addition(status: str, path: str) -> bool:
    return status in ADDITION_STATUSES and path in PHASE8_RUNTIME


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


def only_phase8_registration(path: str, anchored: str, current: str) -> bool:
    """anchor と現在の差が、宣言した登録（取り除いた行・加えた行）と完全に一致する（未登録の file は byte 一致）。"""
    declared_removed, declared_added = PHASE7_TEST_REGISTRATION.get(path, ((), ()))
    removed, added = registration_diff(anchored, current)
    return sorted(removed) == sorted(declared_removed) and sorted(added) == sorted(declared_added)


__all__ = ["ADDITION_STATUSES", "P8_A0", "P8_A1", "PHASE7_TEST_REGISTRATION", "PHASE8_A1_RUNTIME", "PHASE8_DOCS",
           "PHASE8_PACKAGE", "PHASE8_RUNTIME", "PHASE8_TESTS", "is_phase8_addition", "only_phase8_registration",
           "registration_diff"]
