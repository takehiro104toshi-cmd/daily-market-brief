"""Phase 9（Watchlist / Thesis Intelligence）の登録済み runtime ・test ・文書の完全な一覧（P9-A1）。

- 凍結の Phase 7 ／ 8 の test に入れた登録の行は `PHASE9_TEST_REGISTRATION` に完全に列挙し、Phase 9 の guard
  （`test_watchlist_thesis_boundary.py`）が `P9_BASE` との差分の完全一致を pin する（test だけの狭い再開。runtime は不変）。
- P8 の意味 ／ runtime の凍結 anchor は `P8_B5C`（`0a32d86`）のまま。
"""
from __future__ import annotations

import difflib
from typing import Mapping, Sequence, Set, Tuple

#: P9 の基準（P8 の凍結の記録の commit。P9-A1 はここから足す）
P9_BASE = "471e98de5f90dcbbf4ecae9970745eb896e2b3c5"
PHASE9_PACKAGE = "src/intelligence/watchlist_thesis_intelligence"
#: P9-A1 で足した runtime（package の外の P8 の runner を read-only の再構成の部品として使う。本番から import されない）
PHASE9_A1_RUNTIME: Tuple[str, ...] = tuple(f"{PHASE9_PACKAGE}/{name}.py" for name in (
    "__init__", "p8_handoff", "private_root"))
#: P9-A2 で足した runtime（Watchlist ／ Thesis の意味の model ・L0 の提案 ・revision ・記録をまたぐ不変条件。純 ・保存なし）
PHASE9_A2_RUNTIME: Tuple[str, ...] = tuple(f"{PHASE9_PACKAGE}/{name}.py" for name in (
    "cross_rules", "proposal_model", "revision_model", "thesis_model", "watch_model"))
#: P9-A3 で足した runtime（正準の直列化 ・追記専用の private な authority の store ・記録をまたぐ不変条件の検査つきの追記）
PHASE9_A3_RUNTIME: Tuple[str, ...] = tuple(f"{PHASE9_PACKAGE}/{name}.py" for name in (
    "authority_stores", "serialization", "store_io", "thesis_store", "watch_store"))
#: P9-A4 で足した runtime（人の判断の入力 ・実行器 ・凍結 A1 の発行体の record の read-only の確認 ・安全な投影 ・local の入口）
PHASE9_A4_RUNTIME: Tuple[str, ...] = tuple(f"{PHASE9_PACKAGE}/{name}.py" for name in (
    "decision_model", "executor", "local_cli", "p8_identity", "projection"))
PHASE9_RUNTIME: Tuple[str, ...] = tuple(sorted(PHASE9_A1_RUNTIME + PHASE9_A2_RUNTIME + PHASE9_A3_RUNTIME
                                               + PHASE9_A4_RUNTIME))
PHASE9_TESTS: Tuple[str, ...] = ("tests/intelligence/phase9_runtime_registry.py",
                                 "tests/intelligence/test_watchlist_thesis_boundary.py",
                                 "tests/intelligence/test_watchlist_thesis_handoff.py",
                                 "tests/intelligence/test_watchlist_thesis_executor.py",
                                 "tests/intelligence/test_watchlist_thesis_semantics.py",
                                 "tests/intelligence/test_watchlist_thesis_stores.py")
PHASE9_DOCS: Tuple[str, ...] = ("docs/databank/PHASE9_A1_P8_HANDOFF_CONTRACT.md",
                                "docs/databank/PHASE9_A2_WATCHLIST_THESIS_SEMANTICS.md",
                                "docs/databank/PHASE9_A3_AUTHORITY_STORES.md",
                                "docs/databank/PHASE9_A4_HUMAN_DECISION_EXECUTOR.md")
ADDITION_STATUSES = ("A", "??")
#: 凍結の P8 を import してよい Phase 9 の file（P9-A1 の監督判断。完全な path だけ）と、その import の面（module → 名前。完全一致）
P9_HANDOFF = f"{PHASE9_PACKAGE}/p8_handoff.py"
SANCTIONED_P9_A1_IMPORTS: Mapping[str, Set[str]] = {
    "..jquants_screen_local": {"ScreenRunError", "ScreenRunSpec", "assemble", "ledger_path", "load_ledger"},
    "..screener_intelligence.acquisition_event_store": {"AcquisitionEventStore", "AcquisitionStoreError"},
    "..screener_intelligence.acquisition_manifest_store": {"ManifestStore", "ManifestStoreError"},
    "..screener_intelligence.held_observation_store": {"HeldObservationStore", "HeldStoreError"},
    "..screener_intelligence.identity_store": {"IdentityStore", "IdentityStoreError"},
    "..screener_intelligence.observation_store": {"ObservationStore", "ObservationStoreError"},
    "..screener_intelligence.provider_holdings_store": {"HoldingsStoreError", "ProviderHoldingsStore"},
    "..screener_intelligence.screener_criteria_model": {"ScreenerAuthorityMode"},
    "..screener_intelligence.screener_policy_authority_store": {"PolicyAuthorityStore", "PolicyStoreError"},
    "..screener_intelligence.screener_result_set": {"ExecutionCompleteness", "ResultSetError", "ScreenResultSet"},
    "..screener_intelligence.screener_universe_store": {"UniverseAuthorityStore", "UniverseStoreError"},
    "..screener_intelligence.semantic_metadata_store": {"SemanticMetadataStore", "SemanticMetadataStoreError"},
}
#: P9-A4: MANUAL の出所の発行体の record を read-only で確かめる file と、その import の面（完全一致）
P9_IDENTITY = f"{PHASE9_PACKAGE}/p8_identity.py"
SANCTIONED_P9_A4_IDENTITY_IMPORTS: Mapping[str, Set[str]] = {
    "..screener_intelligence.identity_model": {"SourceClass"},
    "..screener_intelligence.identity_store": {"IdentityStore", "IdentityStoreError"},
}
#: 凍結の P8 を import してよい Phase 9 の file（完全な path → import の面）。P8 の `test_bo` が使う
SANCTIONED_P9_P8_IMPORTERS: Mapping[str, Mapping[str, Set[str]]] = {
    P9_HANDOFF: SANCTIONED_P9_A1_IMPORTS,
    P9_IDENTITY: SANCTIONED_P9_A4_IDENTITY_IMPORTS,
}
#: 凍結の Phase 7 ／ 8 の test に入れた登録（path → (取り除いた行, 加えた行)）。行は改行を含まない。P9-A1 で確定する
PHASE9_TEST_REGISTRATION: Mapping[str, Tuple[Tuple[str, ...], Tuple[str, ...]]] = {
    'tests/intelligence/phase7_runtime_registry.py': ((
        'PHASE7_EXCLUDED_PATHSPECS: Tuple[str, ...] = tuple(f":(exclude,literal){path}" for path in PHASE7_RUNTIME + PHASE8_RUNTIME)',
        '    return status in ADDITION_STATUSES and path in PHASE7_RUNTIME + PHASE8_RUNTIME',
    ), (
        'from tests.intelligence.phase9_runtime_registry import PHASE9_RUNTIME   # P9-A1: Phase 9 の登録済み runtime（完全一致）',
        'PHASE7_EXCLUDED_PATHSPECS: Tuple[str, ...] = tuple(f":(exclude,literal){path}" for path in PHASE7_RUNTIME + PHASE8_RUNTIME',
        '                                                   + PHASE9_RUNTIME)',
        '    return status in ADDITION_STATUSES and path in PHASE7_RUNTIME + PHASE8_RUNTIME + PHASE9_RUNTIME',
    )),
    'tests/intelligence/test_narrative_intelligence_boundary.py': ((
        '    assert changes == {("A", path) for path in PHASE7_RUNTIME + PHASE8_RUNTIME}           # commit ／ index の差',
        '                       ("A", P8_A0_DOC)} | {("A", path) for path in PHASE8_DOCS}',
        '        ("A", path) for path in PHASE8_TESTS}',
        '    assert PHASE7_EXCLUDED_PATHSPECS == tuple(f":(exclude,literal){path}" for path in PHASE7_RUNTIME + PHASE8_RUNTIME)',
        '        ("A", path) for path in PHASE8_RUNTIME}                                           # 追加だけ',
        '        ("A", path) for path in PHASE8_RUNTIME}                                           # A4b と P8 の追加だけ',
        '            "config.yaml", ".github", "docs/v2", "docs/pages").splitlines()} <= {("A", path) for path in PHASE8_RUNTIME}',
    ), (
        'from tests.intelligence.phase9_runtime_registry import PHASE9_DOCS, PHASE9_RUNTIME, PHASE9_TESTS   # P9-A1 の登録',
        '    assert changes == {("A", path) for path in PHASE7_RUNTIME + PHASE8_RUNTIME + PHASE9_RUNTIME}   # commit ／ index の差',
        '                       ("A", P8_A0_DOC)} | {("A", path) for path in PHASE8_DOCS + PHASE9_DOCS}',
        '        ("A", path) for path in PHASE8_TESTS + PHASE9_TESTS}',
        '    assert PHASE7_EXCLUDED_PATHSPECS == tuple(f":(exclude,literal){path}" for path in PHASE7_RUNTIME + PHASE8_RUNTIME',
        '                                              + PHASE9_RUNTIME)',
        '        ("A", path) for path in PHASE8_RUNTIME + PHASE9_RUNTIME}                          # 追加だけ',
        '        ("A", path) for path in PHASE8_RUNTIME + PHASE9_RUNTIME}                          # A4b と P8 ・P9 の追加だけ',
        '            "config.yaml", ".github", "docs/v2", "docs/pages").splitlines()} <= {("A", path) for path in PHASE8_RUNTIME',
        '                                                                                  + PHASE9_RUNTIME}',
    )),
    'tests/intelligence/test_screener_intelligence_boundary.py': ((
        '    assert changed <= {("M", path) for path in PHASE7_TEST_REGISTRATION} | {("A", path) for path in PHASE8_TESTS}',
        '        current = (REPO_ROOT / path).read_text(encoding="utf-8")',
        '    assert changes == {("A", path) for path in PHASE8_RUNTIME}',
        '               if not is_phase8_addition(line[:2].strip(), line[3:])]',
        '                    ("A", F1_DOC), ("A", A3_RA_DOC), ("A", PILOT2B_DOC), ("A", B1_DOC), ("A", B2_DOC), ("A", B3_DOC), ("A", B4A_DOC), ("A", B4B_DOC), ("A", B5A_DOC), ("A", B5B_DOC), ("A", B5C_DOC), ("A", FREEZE_DOC)}',
    ), (
        'from tests.intelligence.phase9_runtime_registry import (P9_BASE, PHASE9_DOCS, PHASE9_RUNTIME, PHASE9_TESTS,',
        '                                                        SANCTIONED_P9_P8_IMPORTERS, is_phase9_addition)   # P9 の登録',
        '    assert changed <= {("M", path) for path in PHASE7_TEST_REGISTRATION} | {("A", path) for path in PHASE8_TESTS} | {',
        '        ("A", path) for path in PHASE9_TESTS}',
        '        current = _git("show", f"{P9_BASE}:{path}")             # P8 の登録は P8 の終わりまで（以後の差は P9 の guard が pin）',
        '    assert changes == {("A", path) for path in PHASE8_RUNTIME + PHASE9_RUNTIME}',
        '               if not (is_phase8_addition(line[:2].strip(), line[3:]) or is_phase9_addition(line[:2].strip(), line[3:]))]',
        '                    ("A", F1_DOC), ("A", A3_RA_DOC), ("A", PILOT2B_DOC), ("A", B1_DOC), ("A", B2_DOC), ("A", B3_DOC), ("A", B4A_DOC), ("A", B4B_DOC), ("A", B5A_DOC), ("A", B5B_DOC), ("A", B5C_DOC), ("A", FREEZE_DOC)} | {',
        '                        ("A", path) for path in PHASE9_DOCS}',
        '            continue',
        '        if path.relative_to(REPO_ROOT).as_posix() in SANCTIONED_P9_P8_IMPORTERS:   # P9: read-only の importer だけ（面は完全一致）',
        '            assert _from_imports(path) == SANCTIONED_P9_P8_IMPORTERS[path.relative_to(REPO_ROOT).as_posix()]',
    )),
}



def is_phase9_addition(status: str, path: str) -> bool:
    return status in ADDITION_STATUSES and path in PHASE9_RUNTIME


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


def only_phase9_registration(path: str, anchored: str, current: str) -> bool:
    """`P9_BASE` と現在の差が、宣言した登録（取り除いた行・加えた行）と完全に一致する（未登録の file は byte 一致）。"""
    declared_removed, declared_added = PHASE9_TEST_REGISTRATION.get(path, ((), ()))
    removed, added = registration_diff(anchored, current)
    return sorted(removed) == sorted(declared_removed) and sorted(added) == sorted(declared_added)


__all__ = ["ADDITION_STATUSES", "P9_HANDOFF", "PHASE9_A2_RUNTIME", "PHASE9_A3_RUNTIME", "PHASE9_A4_RUNTIME", "P9_IDENTITY",
           "SANCTIONED_P9_A4_IDENTITY_IMPORTS", "SANCTIONED_P9_P8_IMPORTERS", "SANCTIONED_P9_A1_IMPORTS", "is_phase9_addition", "only_phase9_registration",
           "registration_diff", "P9_BASE", "PHASE9_A1_RUNTIME", "PHASE9_DOCS", "PHASE9_PACKAGE", "PHASE9_RUNTIME", "PHASE9_TESTS",
           "PHASE9_TEST_REGISTRATION"]
