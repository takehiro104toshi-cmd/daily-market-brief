"""Phase 7 の runtime 追加の登録（test helper。P7-A1 で導入）。

Phase 6 の凍結 guard は「HEAD までに runtime surface（`src` ほか）が変わっていない」ことを守る。Phase 7 の package は
`src` の下に**新規追加**されるため、その guard から見えなくする範囲をここで一度だけ宣言する。

- 対象は `PHASE7_RUNTIME` に列挙した file だけ（完全一致。glob・prefix・subdirectory は対象外にならない）。
- `is_phase7_addition` が認めるのは追加（`git diff --name-status` の A、`git status --porcelain` の A / ??）だけ。
- `PHASE7_EXCLUDED_PATHSPECS` は git の literal な除外 pathspec（登録 file の完全 path だけを除く）。
- Phase 6 の namespace（themes / theme_intelligence / knowledge/theme_intelligence）の file は登録できない。
- 登録した file の中身は Phase 7 の guard（`test_narrative_intelligence_boundary.py`）が守る。
- Phase 6 を import してよい Phase 7 の module は `PHASE7_SANCTIONED_IMPORTERS`（P7-A2 の読み取り adapter）だけ。Phase 6 の
  import guard（completion・theme_intelligence・Foundation）はこの完全な path だけを飛ばし、その import の中身は Phase 7 の
  guard が許可一覧で固定する。
- Phase 6 の test に入れた登録の行は `PHASE6_TEST_REGISTRATION` に完全に列挙し、`only_phase7_registration` で anchor との
  差分がそれと完全に一致することを確かめる（登録以外の変更を許さない。B7 closeout の pin と Phase 7 の guard が使う）。
"""
from __future__ import annotations

import difflib
from typing import Mapping, Sequence, Tuple

PHASE7_PACKAGE = "src/intelligence/narrative_intelligence"
#: 登録済みの Phase 7 runtime（P7-A1: __init__ / synthesis_model、P7-A2: input_model / pit_assembler、
#: P7-A3: synthesis_engine、P7-A4a: presentation_model / presentation_planner / narrative_diff、
#: P7-A4b: rendered_model / render_templates_ja / text_renderer）
PHASE7_RUNTIME: Tuple[str, ...] = tuple(f"{PHASE7_PACKAGE}/{name}.py" for name in (
    "__init__", "input_model", "narrative_diff", "pit_assembler", "presentation_model", "presentation_planner",
    "render_templates_ja", "rendered_model", "synthesis_engine", "synthesis_model", "text_renderer"))
ADDITION_STATUSES = ("A", "??")
PHASE7_EXCLUDED_PATHSPECS: Tuple[str, ...] = tuple(f":(exclude,literal){path}" for path in PHASE7_RUNTIME)
#: Phase 6 の read-only API を import してよい Phase 7 の module（P7-A2 の監督判断。完全な path だけ）
PHASE7_SANCTIONED_IMPORTERS: Tuple[str, ...] = (f"{PHASE7_PACKAGE}/pit_assembler.py",)

_IMPORT = "from tests.intelligence.phase7_runtime_registry import {}"
_TEST_DIR = "tests/intelligence"
#: Phase 6 の import guard に入れる、認可された importer だけを飛ばす 2 行（P7-A2）
_SANCTIONED_SKIP = ("        if path.relative_to(REPO_ROOT).as_posix() in PHASE7_SANCTIONED_IMPORTERS:   "
                    "# P7-A2 の認可済み読み取り adapter だけ")
_CONTINUE = "            continue"
#: Phase 6 の test に入れた登録（path → (取り除いた行, 加えた行)）。行は改行を含まない
PHASE6_TEST_REGISTRATION: Mapping[str, Tuple[Tuple[str, ...], Tuple[str, ...]]] = {
    f"{_TEST_DIR}/test_theme_phase6_completion.py": ((), (
        "",
        _IMPORT.format("PHASE7_EXCLUDED_PATHSPECS, PHASE7_SANCTIONED_IMPORTERS"),
        "SURFACE += PHASE7_EXCLUDED_PATHSPECS   # Phase 7 の登録済み runtime だけを除く（phase7_runtime_registry）",
        _SANCTIONED_SKIP, _CONTINUE)),
    f"{_TEST_DIR}/test_theme_intelligence_import_boundary.py": ((), (
        _IMPORT.format("PHASE7_SANCTIONED_IMPORTERS"), _SANCTIONED_SKIP, _CONTINUE)),
    f"{_TEST_DIR}/test_theme_import_boundary.py": ((), (
        _IMPORT.format("PHASE7_SANCTIONED_IMPORTERS"), _SANCTIONED_SKIP, _CONTINUE)),
    f"{_TEST_DIR}/test_theme_llm_closeout.py": ((
        "    assert _git(\"show\", f\"{anchor}:{path}\").stdout == (REPO_ROOT / path).read_text(encoding=\"utf-8\")",
    ), (
        _IMPORT.format("PHASE7_EXCLUDED_PATHSPECS, only_phase7_registration"),
        "SURFACE += PHASE7_EXCLUDED_PATHSPECS   # Phase 7 の登録済み runtime だけを除く（phase7_runtime_registry）",
        "    current = (REPO_ROOT / path).read_text(encoding=\"utf-8\")",
        "    assert only_phase7_registration(path, _git(\"show\", f\"{anchor}:{path}\").stdout, current)")),
    f"{_TEST_DIR}/test_theme_llm_adversarial_e2e.py": ((), (
        _IMPORT.format("PHASE7_EXCLUDED_PATHSPECS"),
        "    surface += PHASE7_EXCLUDED_PATHSPECS                                         # Phase 7 の登録済み runtime")),
    f"{_TEST_DIR}/test_theme_llm_generation.py": ((), (
        _IMPORT.format("PHASE7_EXCLUDED_PATHSPECS"),
        "    surface += PHASE7_EXCLUDED_PATHSPECS                                         # Phase 7 の登録済み runtime")),
    f"{_TEST_DIR}/test_theme_llm_submission.py": ((), (
        _IMPORT.format("PHASE7_EXCLUDED_PATHSPECS"),
        "    surface += PHASE7_EXCLUDED_PATHSPECS                                         # Phase 7 の登録済み runtime")),
    f"{_TEST_DIR}/test_theme_llm_validator.py": ((), (
        _IMPORT.format("PHASE7_EXCLUDED_PATHSPECS"),
        "    surface += PHASE7_EXCLUDED_PATHSPECS                                         # Phase 7 の登録済み runtime")),
    f"{_TEST_DIR}/test_theme_monitoring_coverage_rerun.py": ((), (
        _IMPORT.format("PHASE7_EXCLUDED_PATHSPECS"),
        "RUNTIME_SURFACE += PHASE7_EXCLUDED_PATHSPECS   # Phase 7 の登録済み runtime だけを除く（phase7_runtime_registry）")),
    f"{_TEST_DIR}/test_theme_monitoring_e2e_rerun.py": ((), (
        _IMPORT.format("is_phase7_addition"),
        "    lines = [line for line in lines if not is_phase7_addition(*line.split(\"\\t\", 1))]   # Phase 7 の登録済み追加")),
}


def is_phase7_addition(status: str, path: str) -> bool:
    return status in ADDITION_STATUSES and path in PHASE7_RUNTIME


def is_sanctioned_importer(path: str) -> bool:
    """repo からの相対 path（POSIX）が、Phase 6 を import してよい Phase 7 の module か（完全一致だけ）。"""
    return path in PHASE7_SANCTIONED_IMPORTERS


def only_phase7_registration(path: str, anchored: str, current: str) -> bool:
    """anchor と現在の差が、宣言した登録（取り除いた行・加えた行）と完全に一致する（未登録の file は byte 一致）。"""
    declared_removed, declared_added = PHASE6_TEST_REGISTRATION.get(path, ((), ()))
    removed, added = registration_diff(anchored, current)
    return sorted(removed) == sorted(declared_removed) and sorted(added) == sorted(declared_added)


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


__all__ = ["ADDITION_STATUSES", "PHASE6_TEST_REGISTRATION", "PHASE7_EXCLUDED_PATHSPECS", "PHASE7_PACKAGE",
           "PHASE7_RUNTIME", "PHASE7_SANCTIONED_IMPORTERS", "is_phase7_addition", "is_sanctioned_importer",
           "only_phase7_registration", "registration_diff"]
