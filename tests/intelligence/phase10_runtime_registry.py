"""Phase 10（Personal Intelligence）の登録済み runtime ・test ・文書の完全な一覧（P10-A1 〜 A4）。

- 凍結の Phase 7 ／ 8 ／ 9 の test に入れた登録の行は `PHASE10_TEST_REGISTRATION` に完全に列挙し、Phase 10 の guard
  （`test_personal_intelligence_boundary.py`）が `P10_BASE` との差分の完全一致を pin する（test だけの狭い再開。runtime は不変）。
- 凍結の Phase 9 を import してよい Phase 10 の file は `SANCTIONED_P10_P9_IMPORTERS`（完全な path → import の面）だけ。
"""
from __future__ import annotations

import difflib
from typing import Mapping, Sequence, Set, Tuple

#: P10 の基準（P9 の凍結の記録の commit。P10-A1 はここから足す）
P10_BASE = "3bfc76c6b2f76f613bb50710e6e7eb976a642326"
PHASE10_PACKAGE = "src/intelligence/personal_intelligence"
#: P10-A1 で足した runtime（凍結の Phase 9 の read-only の adapter だけ。本番から import されない）
PHASE10_A1_RUNTIME: Tuple[str, ...] = tuple(f"{PHASE10_PACKAGE}/{name}.py" for name in ("__init__", "p9_view"))
#: P10-A2 で足した runtime（Personal Profile ／ Attention の純な意味の model だけ。入出力 ・store ・実行器なし）
PHASE10_A2_RUNTIME: Tuple[str, ...] = tuple(f"{PHASE10_PACKAGE}/{name}.py" for name in (
    "attention_model", "cross_rules", "profile_model", "revision_model"))
#: P10-A3 で足した runtime（Personal Profile ／ Attention の private な追記専用の authority の store だけ）
PHASE10_A3_RUNTIME: Tuple[str, ...] = tuple(f"{PHASE10_PACKAGE}/{name}.py" for name in (
    "attention_store", "authority_stores", "profile_store", "serialization", "store_io"))
#: P10-A4 で足した runtime（人の決定の実行器 ・P9 の参照の検査 ・個人の見直しの view ・安全な投影 ・private な local の CLI）
PHASE10_A4_RUNTIME: Tuple[str, ...] = tuple(f"{PHASE10_PACKAGE}/{name}.py" for name in (
    "admin_init", "decisions", "executor", "local_cli", "personal_projection", "review_view"))
PHASE10_RUNTIME: Tuple[str, ...] = tuple(sorted(PHASE10_A1_RUNTIME + PHASE10_A2_RUNTIME + PHASE10_A3_RUNTIME
                                                + PHASE10_A4_RUNTIME))
PHASE10_TESTS: Tuple[str, ...] = ("tests/intelligence/phase10_runtime_registry.py",
                                  "tests/intelligence/test_personal_intelligence_boundary.py",
                                  "tests/intelligence/test_personal_intelligence_p9_view.py",
                                  "tests/intelligence/test_personal_intelligence_semantics.py",
                                  "tests/intelligence/test_personal_intelligence_stores.py",
                                  "tests/intelligence/test_personal_intelligence_executor.py",
                                  "tests/intelligence/test_personal_intelligence_review_view.py",
                                  "tests/intelligence/test_personal_intelligence_cli.py")
PHASE10_DOCS: Tuple[str, ...] = ("docs/databank/PHASE10_A1_P9_READONLY_ADAPTER.md",
                                 "docs/databank/PHASE10_A2_PROFILE_ATTENTION_SEMANTICS.md",
                                 "docs/databank/PHASE10_A3_PROFILE_ATTENTION_STORES.md",
                                 "docs/databank/PHASE10_A4_EXECUTOR_REVIEW_VIEW.md")
ADDITION_STATUSES = ("A", "??")
#: 凍結の Phase 9 を import してよい Phase 10 の file（完全な path）と、その import の面（module → 名前。完全一致）
P10_P9_VIEW = f"{PHASE10_PACKAGE}/p9_view.py"
SANCTIONED_P10_P9_IMPORTS: Mapping[str, Set[str]] = {
    "..watchlist_thesis_intelligence.cross_rules": {"check_world"},
    "..watchlist_thesis_intelligence.projection": {"safe_projection"},
    "..watchlist_thesis_intelligence.revision_model": {"SemanticModelError"},
    "..watchlist_thesis_intelligence.store_io": {"AuthorityStoreError"},
    "..watchlist_thesis_intelligence.thesis_store": {"ThesisStore"},
    "..watchlist_thesis_intelligence.watch_store": {"WatchlistStore"},
}
SANCTIONED_P10_P9_IMPORTERS: Mapping[str, Mapping[str, Set[str]]] = {P10_P9_VIEW: SANCTIONED_P10_P9_IMPORTS}
#: P10-A2 の純な model の import の面（path → 相対 import の module の集合。完全一致）。package の外は `..core` の id ・時刻の
#: 補助だけ（名前も完全一致）。Phase 9 ・P8 ・`p9_view` は import しない
SANCTIONED_P10_A2_MODULES: Mapping[str, Set[str]] = {
    f"{PHASE10_PACKAGE}/revision_model.py": {"..core.ids", "..core.time"},
    f"{PHASE10_PACKAGE}/profile_model.py": {".revision_model"},
    f"{PHASE10_PACKAGE}/attention_model.py": {".revision_model"},
    f"{PHASE10_PACKAGE}/cross_rules.py": {".attention_model", ".profile_model", ".revision_model"},
}
SANCTIONED_P10_CORE_IMPORTS: Mapping[str, Set[str]] = {"..core.ids": {"content_id"}, "..core.time": {"to_utc_iso"}}
#: P10-A3 の store の import の面（path → 相対 import の module の集合。完全一致 ・package の中だけ）
P10_STORE_IO = f"{PHASE10_PACKAGE}/store_io.py"
P10_AUTHORITY_STORES = f"{PHASE10_PACKAGE}/authority_stores.py"
SANCTIONED_P10_A3_MODULES: Mapping[str, Set[str]] = {
    f"{PHASE10_PACKAGE}/serialization.py": {".attention_model", ".profile_model", ".revision_model"},
    P10_STORE_IO: {".revision_model"},
    f"{PHASE10_PACKAGE}/profile_store.py": {".cross_rules", ".profile_model", ".serialization", ".store_io"},
    f"{PHASE10_PACKAGE}/attention_store.py": {".attention_model", ".cross_rules", ".serialization", ".store_io"},
    P10_AUTHORITY_STORES: {".attention_model", ".attention_store", ".cross_rules", ".profile_model", ".profile_store",
                           ".revision_model", ".store_io"},
}
#: P10-A4 の import の面（path → 相対 import の module の集合。完全一致 ・package の中だけ）
P10_EXECUTOR = f"{PHASE10_PACKAGE}/executor.py"
P10_REVIEW_VIEW = f"{PHASE10_PACKAGE}/review_view.py"
P10_ADMIN_INIT = f"{PHASE10_PACKAGE}/admin_init.py"
P10_LOCAL_CLI = f"{PHASE10_PACKAGE}/local_cli.py"
SANCTIONED_P10_A4_MODULES: Mapping[str, Set[str]] = {
    f"{PHASE10_PACKAGE}/decisions.py": {".attention_model"},
    P10_EXECUTOR: {".attention_model", ".authority_stores", ".cross_rules", ".decisions", ".p9_view", ".profile_model",
                   ".revision_model", ".store_io"},
    P10_REVIEW_VIEW: {".attention_model", ".attention_store", ".cross_rules", ".p9_view", ".profile_model",
                      ".profile_store", ".revision_model", ".store_io"},
    f"{PHASE10_PACKAGE}/personal_projection.py": {".review_view"},
    P10_ADMIN_INIT: {".authority_stores", ".store_io"},
    P10_LOCAL_CLI: {".admin_init", ".decisions", ".executor", ".personal_projection", ".review_view"},
}
#: A1 の adapter（`p9_view`）を使ってよい Phase 10 の file（完全一致）。P9 の情報はこの経路だけ
SANCTIONED_P10_P9_VIEW_IMPORTERS: Mapping[str, Set[str]] = {
    P10_EXECUTOR: {"P9ViewError", "read_p9_private_snapshot"},
    P10_REVIEW_VIEW: {"P9ViewError", "read_p9_private_snapshot"},
}
#: 物理的な書き込み ・初期化の私的な関数（store_io）を import してよい file（完全一致 ・coordinator だけ）
SANCTIONED_P10_PRIVATE_WRITER_IMPORTS: Mapping[str, Set[str]] = {P10_AUTHORITY_STORES: {"_append_line",
                                                                                       "_initialize_files"}}
#: 凍結の Phase 7 ／ 8 ／ 9 の test に入れた登録（path → (取り除いた行, 加えた行)）。行は改行を含まない。P10-A1 で確定する
PHASE10_TEST_REGISTRATION: Mapping[str, Tuple[Tuple[str, ...], Tuple[str, ...]]] = {
    'tests/intelligence/phase7_runtime_registry.py': ((
        '                                                   + PHASE9_RUNTIME)',
        '    return status in ADDITION_STATUSES and path in PHASE7_RUNTIME + PHASE8_RUNTIME + PHASE9_RUNTIME',
    ), (
        'from tests.intelligence.phase10_runtime_registry import PHASE10_RUNTIME   # P10-A1: Phase 10 の登録済み runtime（完全一致）',
        '                                                   + PHASE9_RUNTIME + PHASE10_RUNTIME)',
        '    return status in ADDITION_STATUSES and path in PHASE7_RUNTIME + PHASE8_RUNTIME + PHASE9_RUNTIME + PHASE10_RUNTIME',
    )),
    'tests/intelligence/test_narrative_intelligence_boundary.py': ((
        '    assert changes == {("A", path) for path in PHASE7_RUNTIME + PHASE8_RUNTIME + PHASE9_RUNTIME}   # commit ／ index の差',
        '                       ("A", P8_A0_DOC)} | {("A", path) for path in PHASE8_DOCS + PHASE9_DOCS}',
        '        ("A", path) for path in PHASE8_TESTS + PHASE9_TESTS}',
        '                                              + PHASE9_RUNTIME)',
        '        ("A", path) for path in PHASE8_RUNTIME + PHASE9_RUNTIME}                          # 追加だけ',
        '        ("A", path) for path in PHASE8_RUNTIME + PHASE9_RUNTIME}                          # A4b と P8 ・P9 の追加だけ',
        '                                                                                  + PHASE9_RUNTIME}',
    ), (
        'from tests.intelligence.phase10_runtime_registry import PHASE10_DOCS, PHASE10_RUNTIME, PHASE10_TESTS   # P10-A1 の登録',
        '    assert changes == {("A", path) for path in PHASE7_RUNTIME + PHASE8_RUNTIME + PHASE9_RUNTIME',
        '                       + PHASE10_RUNTIME}                                                   # commit ／ index の差',
        '                       ("A", P8_A0_DOC)} | {("A", path) for path in PHASE8_DOCS + PHASE9_DOCS + PHASE10_DOCS}',
        '        ("A", path) for path in PHASE8_TESTS + PHASE9_TESTS + PHASE10_TESTS}',
        '                                              + PHASE9_RUNTIME + PHASE10_RUNTIME)',
        '        ("A", path) for path in PHASE8_RUNTIME + PHASE9_RUNTIME + PHASE10_RUNTIME}        # 追加だけ',
        '        ("A", path) for path in PHASE8_RUNTIME + PHASE9_RUNTIME + PHASE10_RUNTIME}        # A4b と P8 ・P9 ・P10 の追加だけ',
        '                                                                                  + PHASE9_RUNTIME + PHASE10_RUNTIME}',
    )),
    'tests/intelligence/test_screener_intelligence_boundary.py': ((
        '        ("A", path) for path in PHASE9_TESTS}',
        '    assert changes == {("A", path) for path in PHASE8_RUNTIME + PHASE9_RUNTIME}',
        '               if not (is_phase8_addition(line[:2].strip(), line[3:]) or is_phase9_addition(line[:2].strip(), line[3:]))]',
        '                        ("A", path) for path in PHASE9_DOCS}',
    ), (
        'from tests.intelligence.phase10_runtime_registry import (PHASE10_DOCS, PHASE10_RUNTIME, PHASE10_TESTS,',
        '                                                         is_phase10_addition)   # P10 の登録',
        '        ("A", path) for path in PHASE9_TESTS + PHASE10_TESTS}',
        '    assert changes == {("A", path) for path in PHASE8_RUNTIME + PHASE9_RUNTIME + PHASE10_RUNTIME}',
        '               if not (is_phase8_addition(line[:2].strip(), line[3:]) or is_phase9_addition(line[:2].strip(), line[3:])',
        '                       or is_phase10_addition(line[:2].strip(), line[3:]))]',
        '                        ("A", path) for path in PHASE9_DOCS + PHASE10_DOCS}',
    )),
    'tests/intelligence/test_watchlist_thesis_boundary.py': ((
        '    assert _changes("--cached", "--name-status", P9_BASE, "--", "src") == {("A", path) for path in PHASE9_RUNTIME}',
        '    assert _changes("--cached", "--name-status", P9_BASE, "--", "docs") <= {("A", path) for path in PHASE9_DOCS}',
        '        ("A", path) for path in PHASE9_TESTS} | {("M", path) for path in PHASE9_TEST_REGISTRATION}',
        '        current = (REPO_ROOT / path).read_text(encoding="utf-8")',
    ), (
        'from tests.intelligence.phase10_runtime_registry import (P10_BASE, PHASE10_DOCS, PHASE10_RUNTIME, PHASE10_TESTS,',
        '                                                         SANCTIONED_P10_P9_IMPORTERS)   # P10 の登録',
        '    assert _changes("--cached", "--name-status", P9_BASE, "--", "src") == {("A", path) for path in PHASE9_RUNTIME',
        '                                                                           + PHASE10_RUNTIME}',
        '    assert _changes("--cached", "--name-status", P9_BASE, "--", "docs") <= {("A", path) for path in PHASE9_DOCS',
        '                                                                            + PHASE10_DOCS}',
        '        ("A", path) for path in PHASE9_TESTS + PHASE10_TESTS} | {("M", path) for path in PHASE9_TEST_REGISTRATION}',
        '        current = _git("show", f"{P10_BASE}:{path}")             # P9 の登録は P9 の終わりまで（以後の差は P10 の guard が pin）',
        '            continue',
        '        if path.relative_to(REPO_ROOT).as_posix() in SANCTIONED_P10_P9_IMPORTERS:  # P10: read-only の importer だけ（面は完全一致）',
        '            assert _imports(path)[0] == SANCTIONED_P10_P9_IMPORTERS[path.relative_to(REPO_ROOT).as_posix()]',
    )),
}


def is_phase10_addition(status: str, path: str) -> bool:
    return status in ADDITION_STATUSES and path in PHASE10_RUNTIME


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


def only_phase10_registration(path: str, anchored: str, current: str) -> bool:
    """`P10_BASE` と現在の差が、宣言した登録（取り除いた行・加えた行）と完全に一致する（未登録の file は byte 一致）。"""
    declared_removed, declared_added = PHASE10_TEST_REGISTRATION.get(path, ((), ()))
    removed, added = registration_diff(anchored, current)
    return sorted(removed) == sorted(declared_removed) and sorted(added) == sorted(declared_added)


__all__ = ["ADDITION_STATUSES", "P10_BASE", "P10_P9_VIEW", "PHASE10_A1_RUNTIME", "PHASE10_A2_RUNTIME", "PHASE10_DOCS",
           "PHASE10_A3_RUNTIME", "PHASE10_PACKAGE", "PHASE10_RUNTIME", "PHASE10_TESTS", "PHASE10_TEST_REGISTRATION",
           "P10_ADMIN_INIT", "P10_AUTHORITY_STORES", "P10_EXECUTOR", "P10_LOCAL_CLI", "P10_REVIEW_VIEW", "P10_STORE_IO",
           "PHASE10_A4_RUNTIME", "SANCTIONED_P10_A2_MODULES", "SANCTIONED_P10_A3_MODULES", "SANCTIONED_P10_A4_MODULES",
           "SANCTIONED_P10_P9_VIEW_IMPORTERS",
           "SANCTIONED_P10_CORE_IMPORTS", "SANCTIONED_P10_P9_IMPORTERS", "SANCTIONED_P10_PRIVATE_WRITER_IMPORTS",
           "SANCTIONED_P10_P9_IMPORTS", "is_phase10_addition", "only_phase10_registration", "registration_diff"]
