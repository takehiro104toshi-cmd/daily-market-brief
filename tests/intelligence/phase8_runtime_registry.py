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
#: P8-A2 の凍結 anchor（identity ・観測の runtime と A2 の契約はここと byte 一致。P8-A2.5 で登録）
P8_A2 = "b686b008fe240eeb115b6c485ac4c5c642ebe2c9"
#: P8-A2.5 の凍結 anchor（runtime と A2.5 の監査の文書はここと byte 一致。P8-V で登録）
P8_A2_5 = "5713a563e218d2b6065090343eeff7dee8f9b568"
#: P8-V の凍結 anchor（runtime と A2.5 ・P8-V の文書はここと byte 一致。P8-VR で登録）
P8_V = "fc91ee17d3ad32bf0ab04b4ea49e2b2c47fa9ba4"
#: P8-VR の凍結 anchor（A1 ／ A2 の runtime と先行の Phase 8 の文書はここと byte 一致。P8-A1R で登録）
P8_VR = "7b8d3757f3cfb0cc80749d36b05aa401ae237b1e"
#: P8-A1R の凍結 anchor（runtime ・Phase 8 の test ・先行の Phase 8 の文書はここと byte 一致。P8-LV1 で登録）
P8_A1R = "e6a750f54dc83e482e649dc65dd0d5131fb9991d"
#: P8-LV1 の凍結 anchor（runtime ・Phase 8 の test ・先行の Phase 8 の文書はここと byte 一致。P8-PILOT1 で登録）
P8_LV1 = "7281d532937f6f68e4b3ecb839506b2616794362"
#: P8-PILOT1 の凍結 anchor（runtime ・Phase 8 の test ・先行の Phase 8 の文書はここと byte 一致。P8-A2R で登録）
P8_PILOT1 = "cbf86cc10ec3d9ce9ff9cc3dd731e49ba0d43328"
#: P8-A2R の凍結 anchor（runtime ・Phase 8 の test ・先行の Phase 8 の文書はここと byte 一致。P8-A2R の再実行で登録）
P8_A2R = "739ece233d7f99ec28da96254f408d3613229f6b"
#: P8-A2R の再実行（公式の仕様の確認）の凍結 anchor（runtime ・Phase 8 の test ・先行の文書はここと byte 一致。P8-A2R-IMPL で登録）
P8_A2RV = "45a516f4886a679063acc2843df2cca321199312"
#: P8-A2R-IMPL の凍結 anchor（A1 ・A2 ・A1R ・A2R の runtime ・Phase 8 の test ・先行の文書はここと byte 一致。P8-A3A で登録）
P8_A2RI = "4d3540cf209b5fb0a99fc6c5e32ba17c35f21ae8"
PHASE8_PACKAGE = "src/intelligence/screener_intelligence"
#: 登録済みの Phase 8 runtime（P8-A1: __init__ / identity_model / identity_resolver / identity_store、
#: P8-A2: observation_model / observation_resolver / observation_store、
#: P8-A1R: identity_correction_model / identity_correction_store / identity_remediation_resolver、
#: P8-A2R-IMPL: observation_semantics_model / observation_semantics_mapping / observation_semantics_gate、
#: P8-A3A: metric_model / fundamental_metrics）
PHASE8_A1_RUNTIME: Tuple[str, ...] = tuple(f"{PHASE8_PACKAGE}/{name}.py" for name in (
    "__init__", "identity_model", "identity_resolver", "identity_store"))
PHASE8_RUNTIME: Tuple[str, ...] = tuple(f"{PHASE8_PACKAGE}/{name}.py" for name in (
    "__init__", "fundamental_metrics", "identity_correction_model", "identity_correction_store", "identity_model",
    "identity_remediation_resolver", "identity_resolver", "identity_store", "metric_model", "observation_model",
    "observation_resolver", "observation_semantics_gate", "observation_semantics_mapping",
    "observation_semantics_model", "observation_store"))
#: P8-A1R で足した runtime（A1 ／ A2 の module は変えない拡張）
PHASE8_A1R_RUNTIME: Tuple[str, ...] = tuple(f"{PHASE8_PACKAGE}/{name}.py" for name in (
    "identity_correction_model", "identity_correction_store", "identity_remediation_resolver"))
#: P8-A2R-IMPL で足した runtime（A1 ／ A2 ／ A1R の module は変えない拡張。A2 の会計の意味の safety layer）
PHASE8_A2R_RUNTIME: Tuple[str, ...] = tuple(f"{PHASE8_PACKAGE}/{name}.py" for name in (
    "observation_semantics_gate", "observation_semantics_mapping", "observation_semantics_model"))
#: P8-A3A で足した runtime（A1 ／ A2 ／ A1R ／ A2R の module は変えない拡張。決定論の財務の指標）
PHASE8_A3A_RUNTIME: Tuple[str, ...] = tuple(f"{PHASE8_PACKAGE}/{name}.py" for name in (
    "fundamental_metrics", "metric_model"))
#: `P8_A2` で凍結した runtime（A1 ＋ A2 の 7 module）
PHASE8_A2_RUNTIME: Tuple[str, ...] = tuple(f"{PHASE8_PACKAGE}/{name}.py" for name in (
    "__init__", "identity_model", "identity_resolver", "identity_store", "observation_model", "observation_resolver",
    "observation_store"))
#: 登録済みの Phase 8 の test（追加だけ）
PHASE8_TESTS: Tuple[str, ...] = ("tests/intelligence/phase8_runtime_registry.py",
                                 "tests/intelligence/test_screener_identity.py",
                                 "tests/intelligence/test_screener_identity_remediation.py",
                                 "tests/intelligence/test_screener_intelligence_boundary.py",
                                 "tests/intelligence/test_screener_observation.py",
                                 "tests/intelligence/test_screener_observation_semantics.py",
                                 "tests/intelligence/test_screener_fundamental_metrics.py")
#: 登録済みの Phase 8 の文書（追加だけ）
PHASE8_DOCS: Tuple[str, ...] = ("docs/databank/PHASE8_SCREENER_INTELLIGENCE_ARCHITECTURE_AUDIT.md",
                                "docs/databank/PHASE8_ISSUER_SECURITY_IDENTITY_CONTRACT.md",
                                "docs/databank/PHASE8_PIT_OBSERVATION_CONTRACT.md",
                                "docs/databank/PHASE8_JQUANTS_REAL_DATA_MAPPING_AUDIT.md",
                                "docs/databank/PHASE8_JQUANTS_OFFICIAL_SPEC_VERIFICATION.md",
                                "docs/databank/PHASE8_JQUANTS_VERIFICATION_REMEDIATION.md",
                                "docs/databank/PHASE8_IDENTITY_REMEDIATION_CONTRACT.md",
                                "docs/databank/PHASE8_JQUANTS_LIGHT_MINIMUM_FIELD_CONTRACT.md",
                                "docs/databank/PHASE8_JQUANTS_LIGHT_PILOT1_REPORT.md",
                                "docs/databank/PHASE8_A2R_JQUANTS_SEMANTIC_REMEDIATION.md",
                                "docs/databank/PHASE8_A2R_OFFICIAL_SPEC_VERIFICATION.md",
                                "docs/databank/PHASE8_A2R_IMPLEMENTATION.md",
                                "docs/databank/PHASE8_A3A_FUNDAMENTAL_METRICS.md")
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


__all__ = ["ADDITION_STATUSES", "P8_A0", "P8_A1", "P8_A1R", "P8_A2", "P8_LV1", "P8_PILOT1", "P8_A2R", "P8_A2RI", "P8_A2RV",
           "P8_A2_5", "P8_V", "P8_VR",
           "PHASE7_TEST_REGISTRATION", "PHASE8_A1R_RUNTIME", "PHASE8_A1_RUNTIME", "PHASE8_A2R_RUNTIME",
           "PHASE8_A2_RUNTIME", "PHASE8_A3A_RUNTIME", "PHASE8_DOCS",
           "PHASE8_PACKAGE", "PHASE8_RUNTIME", "PHASE8_TESTS", "is_phase8_addition", "only_phase8_registration",
           "registration_diff"]
