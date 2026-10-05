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
#: P8-A3A の凍結 anchor（A1 ・A2 ・A1R ・A2R ・A3A の runtime ・Phase 8 の test ・先行の文書はここと byte 一致。P8-A3B で登録。
#: `metric_model` だけは P8-A3B の enum の 4 行の追加を許す ＝ PHASE8_A3B_METRIC_MODEL_REGISTRATION）
P8_A3A = "84c2d52f59d573d6f558f64fbbd1589fe97ecf24"
#: P8-A3B の凍結 anchor（Phase 8 の runtime 16 module ・Phase 8 の test ・先行の文書はここと byte 一致。P8-A3R で登録）
P8_A3B = "d8845f2b063f15dc8629245ec276019d6314cf7a"
#: P8-A3R の凍結 anchor（runtime 16 module ・Phase 8 の test ・先行の文書はここと byte 一致。P8-ST1 で登録）
P8_A3R = "f1c4a4e86c51b1668b9be41d6ceff06440e29608"
#: P8-ST1 の凍結 anchor（runtime 19 module ・Phase 8 の test ・先行の文書はここと byte 一致。ADP0 で登録）
P8_ST1 = "e831996094ba035bbfa0574c639d40faff888096"
#: P8-ADP0 の凍結 anchor（runtime 21 module ・Phase 8 の test ・先行の文書はここと byte 一致。EXE で登録）
P8_ADP0 = "a2ccc1c30543daee5269ca39a7591a4767376f1d"
#: P8-EXE の凍結 anchor（runtime 23 module ・Phase 8 の test ・先行の文書はここと byte 一致。ID1 で登録）
P8_EXE = "5ec466b773e696d6084533bbf25d252cd09996bb"
#: P8-ID1 の凍結 anchor（runtime 25 module ・Phase 8 の test ・先行の文書はここと byte 一致。ID2 で登録）
P8_ID1 = "6b5f0e6795357109f2cf3b12339f9f7a93ceaf77"
#: P8-LIVE0 の凍結 anchor（P8-ID2 の runtime 27 module ・Phase 8 の test ・先行の文書はここと byte 一致。LIVE1 で登録）
P8_LIVE0 = "17c962385be5641665f4d7904cfc710cbb575569"
#: P8-LIVE1 の凍結 anchor（runtime 30 module ・Phase 8 の test ・先行の文書はここと byte 一致。LIVE2 で登録）
P8_LIVE1 = "7cbc85b66879b2e686ccf16cfafda8b7412a062a"
#: P8-LIVE2 の凍結 anchor（package 30 module ＋ LIVE2 transport ・Phase 8 の test ・先行の文書はここと byte 一致。PILOT2A で登録）
P8_LIVE2 = "476182af12bb583102e1f616316889bcfb8c58b9"
#: P8-PILOT2A の凍結 anchor（package 30 ＋ transport ＋ runner ・Phase 8 の test ・先行の文書はここと byte 一致。ADP0R で登録）
P8_PILOT2A = "6e042732acd52ed6c1c25c9e39688e78844b7589"
#: P8-ADP0R の凍結 anchor（package 30 ＋ transport ＋ runner ・Phase 8 の test ・先行の文書はここと byte 一致。ACQ0 で登録）
P8_ADP0R = "ca3e2e4b64f99cfff3af066cdb8fcfa8d953df2b"
#: P8-ACQ0 の凍結 anchor（package 32 ＋ transport ＋ runner ・Phase 8 の test ・先行の文書はここと byte 一致。OBS60-I1 で登録）
P8_ACQ0 = "b210798cc99cbd503a52a0af190d171675eead3d"
#: P8-OBS60-I1 の凍結 anchor（runtime 35 ・Phase 8 の test ・先行の文書はここと byte 一致。EXE-R で登録）
P8_OBS60_I1 = "9d833b2fe4f359cad00f1bbdfb0943487c8ea10f"
#: P8-EXE-R の凍結 anchor（runtime 35 ・Phase 8 の test ・先行の文書はここと byte 一致。EPOCH1 で登録）
P8_EXE_R = "cc8dcf5ae6235291595c87c34a6af330355a429b"
#: P8-EPOCH1 の凍結 anchor（runtime 38 ・Phase 8 の test ・先行の文書はここと byte 一致。A2C で登録）
P8_EPOCH1 = "f764a11fdfc126fa3425ab4cc5e069fa8f6c0ad2"
#: P8-A2C の凍結 anchor（runtime 39 ・Phase 8 の test ・先行の文書はここと byte 一致。EPOCH1R で登録）
P8_A2C = "0942218b4e5cfb520533e80bd1e2e576af7e8a9c"
#: P8-EPOCH1R の凍結 anchor（runtime 39 ・Phase 8 の test ・先行の文書はここと byte 一致。A2C-R で登録）
P8_EPOCH1R = "9a34569f41594d35aa55d8041ad968e4bf75f78b"
#: P8-A2C-R の凍結 anchor（runtime 41 ・Phase 8 の test ・先行の文書はここと byte 一致。F1 で登録）
P8_A2C_R = "9833ddbecc5039a206f31d6e2e1f08fa590a384a"
#: P8-OBS60-F1 の凍結 anchor（runtime 42 ・Phase 8 の test ・先行の文書はここと byte 一致。A3-RA で登録）
P8_F1 = "2a784a59429121070e32c367533cb30c3d0e02ec"
#: P8-A3-RA の凍結 anchor（runtime 43 ・Phase 8 の test ・先行の文書はここと byte 一致。PILOT2B で登録）
P8_A3_RA = "d424a720cfc20a6259a95c7a74ab9533628547a2"
#: P8-PILOT2B の凍結 anchor（runtime 43 ・Phase 8 の test ・先行の文書はここと byte 一致。B1 で登録）
P8_PILOT2B = "6347588001a8531d60414e10dc2f94e306bdb877"
#: P8-B1 の凍結 anchor（runtime 44 ・Phase 8 の test ・先行の文書はここと byte 一致。B2 で登録）
P8_B1 = "a5df74ccce2153a088dab0b4f193931a12d84f9d"
#: P8-B2 の凍結 anchor（runtime 45 ・Phase 8 の test ・先行の文書はここと byte 一致。B3 で登録）
P8_B2 = "8129e953cc1c8886c782857ff9e8010b639893f9"
PHASE8_PACKAGE = "src/intelligence/screener_intelligence"
#: 登録済みの Phase 8 runtime（P8-A1: __init__ / identity_model / identity_resolver / identity_store、
#: P8-A2: observation_model / observation_resolver / observation_store、
#: P8-A1R: identity_correction_model / identity_correction_store / identity_remediation_resolver、
#: P8-A2R-IMPL: observation_semantics_model / observation_semantics_mapping / observation_semantics_gate、
#: P8-A3A: metric_model / fundamental_metrics、P8-A3B: fundamental_metrics_extended、
#: P8-ST1: semantic_metadata_store / held_observation_model / held_observation_store、
#: P8-ADP0: jquants_adapter_model / jquants_financial_summary_adapter、
#: P8-EXE: jquants_execution_model / jquants_financial_summary_executor、
#: P8-ID1: identity_bootstrap_model / identity_bootstrap、
#: P8-ID2: identity_registration_model / identity_registration_executor、
#: P8-LIVE1: jquants_live_model / jquants_master_ingress / jquants_live_client、
#: P8-LIVE2: src/intelligence/jquants_local_transport（package の外。本人の環境でだけ使う実 HTTPS transport）、
#: P8-PILOT2A: src/intelligence/jquants_pilot2_local（package の外。本人の環境でだけ動かす 2 段の runner））
PHASE8_A1_RUNTIME: Tuple[str, ...] = tuple(f"{PHASE8_PACKAGE}/{name}.py" for name in (
    "__init__", "identity_model", "identity_resolver", "identity_store"))
PHASE8_PACKAGE_RUNTIME: Tuple[str, ...] = tuple(f"{PHASE8_PACKAGE}/{name}.py" for name in (
    "__init__", "acquisition_event_model", "acquisition_event_store", "acquisition_manifest_builder",
    "acquisition_manifest_model", "acquisition_manifest_store", "fundamental_metrics",
    "fundamental_metrics_extended", "held_observation_model",
    "held_observation_store", "identity_bootstrap", "identity_bootstrap_model", "identity_continuity_coverage",
    "identity_correction_model", "identity_correction_store", "identity_model", "identity_registration_executor",
    "identity_registration_model",
    "identity_remediation_resolver", "identity_resolver", "identity_store", "jquants_adapter_model",
    "jquants_execution_model", "jquants_financial_summary_adapter", "jquants_financial_summary_executor",
    "jquants_live_client", "jquants_live_model", "jquants_master_ingress", "metric_model", "observation_model",
    "observation_resolver", "observation_retrospective_resolver", "observation_semantics_gate",
    "observation_semantics_mapping", "observation_semantics_model", "observation_store", "provider_holdings_executor",
    "provider_holdings_model", "provider_holdings_store", "retrospective_metric_resolver", "screener_criteria_model",
    "screener_evaluator", "screener_policy_authority_model", "screener_policy_authority_store",
    "semantic_metadata_store"))
#: P8-LIVE2 で足した runtime（package の外。凍結 LIVE1 の `Transport` の実 HTTPS 実装。本人の環境でだけ実行する）
PHASE8_LIVE2_RUNTIME: Tuple[str, ...] = ("src/intelligence/jquants_local_transport.py",)
#: P8-PILOT2A で足した runtime（package の外。2 段の PILOT2 runner。本番から import されない）
PHASE8_PILOT2A_RUNTIME: Tuple[str, ...] = ("src/intelligence/jquants_pilot2_local.py",)
#: 登録済みの Phase 8 runtime 全体（package の module ＋ package の外の local 実行の module）
PHASE8_RUNTIME: Tuple[str, ...] = tuple(sorted(PHASE8_PACKAGE_RUNTIME + PHASE8_LIVE2_RUNTIME + PHASE8_PILOT2A_RUNTIME))
#: P8-A1R で足した runtime（A1 ／ A2 の module は変えない拡張）
PHASE8_A1R_RUNTIME: Tuple[str, ...] = tuple(f"{PHASE8_PACKAGE}/{name}.py" for name in (
    "identity_correction_model", "identity_correction_store", "identity_remediation_resolver"))
#: P8-A2R-IMPL で足した runtime（A1 ／ A2 ／ A1R の module は変えない拡張。A2 の会計の意味の safety layer）
PHASE8_A2R_RUNTIME: Tuple[str, ...] = tuple(f"{PHASE8_PACKAGE}/{name}.py" for name in (
    "observation_semantics_gate", "observation_semantics_mapping", "observation_semantics_model"))
#: P8-A3A で足した runtime（A1 ／ A2 ／ A1R ／ A2R の module は変えない拡張。決定論の財務の指標）
PHASE8_A3A_RUNTIME: Tuple[str, ...] = tuple(f"{PHASE8_PACKAGE}/{name}.py" for name in (
    "fundamental_metrics", "metric_model"))
#: P8-A3B で足した runtime（A3A の architecture の再利用。純利益率 ・ROA）
PHASE8_A3B_RUNTIME: Tuple[str, ...] = tuple(f"{PHASE8_PACKAGE}/{name}.py" for name in (
    "fundamental_metrics_extended",))
#: P8-A3B が凍結した A3A の `metric_model` に加えた行（取り除いた行, 加えた行）。これ以外の差分は凍結の違反
PHASE8_A3B_METRIC_MODEL_REGISTRATION: Tuple[Tuple[str, ...], Tuple[str, ...]] = ((), (
    '    NET_MARGIN = "NET_MARGIN"',
    '    ROA_POINT_IN_TIME = "ROA_POINT_IN_TIME"',
    '    NET_INCOME = "NET_INCOME"',
    '    TOTAL_ASSETS = "TOTAL_ASSETS"',
))
#: P8-ST1 で足した runtime（注記の運用 store ・保留の観測の model ／ store。A2 ・A1 ・指標には触れない）
PHASE8_ST1_RUNTIME: Tuple[str, ...] = tuple(f"{PHASE8_PACKAGE}/{name}.py" for name in (
    "held_observation_model", "held_observation_store", "semantic_metadata_store"))
#: P8-ADP0 で足した runtime（純 adapter。store ・network ・filesystem に触れない）
PHASE8_ADP0_RUNTIME: Tuple[str, ...] = tuple(f"{PHASE8_PACKAGE}/{name}.py" for name in (
    "jquants_adapter_model", "jquants_financial_summary_adapter"))
#: P8-EXE で足した runtime（安全な append executor。A2 ・注記 ・保留の 3 store にだけ書く）
PHASE8_EXE_RUNTIME: Tuple[str, ...] = tuple(f"{PHASE8_PACKAGE}/{name}.py" for name in (
    "jquants_execution_model", "jquants_financial_summary_executor"))
#: P8-ID1 で足した runtime（identity bootstrap の提案 ・審査 manifest ・登録 plan。純関数。A1 に書かない）
PHASE8_ID1_RUNTIME: Tuple[str, ...] = tuple(f"{PHASE8_PACKAGE}/{name}.py" for name in (
    "identity_bootstrap_model", "identity_bootstrap"))
#: P8-ID2 で足した runtime（人が承認した identity の登録 executor。A1 の store にだけ書く）
PHASE8_ID2_RUNTIME: Tuple[str, ...] = tuple(f"{PHASE8_PACKAGE}/{name}.py" for name in (
    "identity_registration_model", "identity_registration_executor"))
#: P8-ACQ0 で足した runtime（取得 event の証拠の model ・追記専用 store。coverage ・観測 ・identity を作らない）
PHASE8_ACQ0_RUNTIME: Tuple[str, ...] = tuple(f"{PHASE8_PACKAGE}/{name}.py" for name in (
    "acquisition_event_model", "acquisition_event_store"))
#: P8-OBS60-I1 で足した runtime（identity の継続 coverage の authority。A1 の Coverage だけを append）
PHASE8_OBS60_I1_RUNTIME: Tuple[str, ...] = tuple(f"{PHASE8_PACKAGE}/{name}.py" for name in (
    "identity_continuity_coverage",))
#: P8-EPOCH1 で足した runtime（取得 manifest の membership authority: model ・追記専用 store ・純 builder。配線 ・coverage は無い）
PHASE8_EPOCH1_RUNTIME: Tuple[str, ...] = tuple(f"{PHASE8_PACKAGE}/{name}.py" for name in (
    "acquisition_manifest_model", "acquisition_manifest_store", "acquisition_manifest_builder"))
#: P8-A2C で足した runtime（RETROSPECTIVE_PROVIDER_AUTHORITY の解決。A2 の model ・resolver は狭く再開）
PHASE8_A2C_RUNTIME: Tuple[str, ...] = tuple(f"{PHASE8_PACKAGE}/{name}.py" for name in (
    "observation_retrospective_resolver",))
#: P8-A2C-R で足した runtime（provider の保持 epoch の authority: model ・追記専用 store。A2 の coverage とは別の journal）
PHASE8_A2C_R_RUNTIME: Tuple[str, ...] = tuple(f"{PHASE8_PACKAGE}/{name}.py" for name in (
    "provider_holdings_model", "provider_holdings_store"))
#: P8-OBS60-F1 で足した runtime（保持 record の決定論の producer: 取得 ＋ manifest ＋ A2 → 保持 store。A2 の coverage は書かない）
PHASE8_F1_RUNTIME: Tuple[str, ...] = tuple(f"{PHASE8_PACKAGE}/{name}.py" for name in (
    "provider_holdings_executor",))
#: P8-A3-RA で足した runtime（遡及の provider authority の上の 4 指標。凍結 A3 の純 helper を再利用。STRICT A3 は不変）
PHASE8_A3_RA_RUNTIME: Tuple[str, ...] = tuple(f"{PHASE8_PACKAGE}/{name}.py" for name in (
    "retrospective_metric_resolver",))
#: P8-B1 で足した runtime（Screener v1 の閉じた意味の model。評価 ・保存 ・Theme ・security の投影は無い）
PHASE8_B1_RUNTIME: Tuple[str, ...] = tuple(f"{PHASE8_PACKAGE}/{name}.py" for name in (
    "screener_criteria_model",))
#: P8-B2 で足した runtime（凍結 B1 ・A3 ・A3-RA の上の財務の基準の決定論の評価器。式 ・順位 ・保存 ・Theme は無い）
PHASE8_B2_RUNTIME: Tuple[str, ...] = tuple(f"{PHASE8_PACKAGE}/{name}.py" for name in (
    "screener_evaluator",))
#: P8-B3 で足した runtime（人が審査した方針の private authority record ・追記専用 store。評価 ・latest ・Theme は無い）
PHASE8_B3_RUNTIME: Tuple[str, ...] = tuple(f"{PHASE8_PACKAGE}/{name}.py" for name in (
    "screener_policy_authority_model", "screener_policy_authority_store"))
#: P8-LIVE1 で足した runtime（memory だけの取り込み client ・ID1 の前の適格。store ・network に触れない）
PHASE8_LIVE1_RUNTIME: Tuple[str, ...] = tuple(f"{PHASE8_PACKAGE}/{name}.py" for name in (
    "jquants_live_model", "jquants_master_ingress", "jquants_live_client"))
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
                                 "tests/intelligence/test_screener_fundamental_metrics.py",
                                 "tests/intelligence/test_screener_fundamental_metrics_extended.py",
                                 "tests/intelligence/test_screener_operational_stores.py",
                                 "tests/intelligence/test_screener_jquants_adapter.py",
                                 "tests/intelligence/test_screener_jquants_execution.py",
                                 "tests/intelligence/test_screener_identity_bootstrap.py",
                                 "tests/intelligence/test_screener_identity_registration.py",
                                 "tests/intelligence/test_screener_jquants_live.py",
                                 "tests/intelligence/test_screener_jquants_local_transport.py",
                                 "tests/intelligence/test_screener_pilot2_local_runner.py",
                                 "tests/intelligence/test_screener_acquisition_events.py",
                                 "tests/intelligence/test_screener_identity_continuity.py",
                                 "tests/intelligence/test_screener_jquants_execution_revision.py",
                                 "tests/intelligence/test_screener_acquisition_manifest.py",
                                 "tests/intelligence/test_screener_observation_retrospective.py",
                                 "tests/intelligence/test_screener_acquisition_manifest_remediation.py",
                                 "tests/intelligence/test_screener_provider_holdings.py",
                                 "tests/intelligence/test_screener_provider_holdings_executor.py",
                                 "tests/intelligence/test_screener_retrospective_metrics.py",
                                 "tests/intelligence/test_screener_pilot2b_retrospective_runner.py",
                                 "tests/intelligence/test_screener_criteria_model.py",
                                 "tests/intelligence/test_screener_evaluator.py",
                                 "tests/intelligence/test_screener_policy_authority.py")
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
                                "docs/databank/PHASE8_A3A_FUNDAMENTAL_METRICS.md",
                                "docs/databank/PHASE8_A3B_NET_MARGIN_ROA.md",
                                "docs/databank/PHASE8_A3R_REAL_DATA_BRIDGE_DESIGN.md",
                                "docs/databank/PHASE8_ST1_OPERATIONAL_STORES.md",
                                "docs/databank/PHASE8_ADP0_JQUANTS_FINANCIAL_SUMMARY_ADAPTER.md",
                                "docs/databank/PHASE8_EXE_SAFE_APPEND_EXECUTOR.md",
                                "docs/databank/PHASE8_ID1_IDENTITY_BOOTSTRAP.md",
                                "docs/databank/PHASE8_ID2_IDENTITY_REGISTRATION_EXECUTOR.md",
                                "docs/databank/PHASE8_LIVE0_PRELIVE_AUDIT.md",
                                "docs/databank/PHASE8_LIVE1_MEMORY_ONLY_CLIENT.md",
                                "docs/databank/PHASE8_LIVE2_LOCAL_HTTP_TRANSPORT.md",
                                "docs/databank/PHASE8_PILOT2A_LOCAL_RUNNER.md",
                                "docs/databank/PHASE8_ADP0R_MULTI_STANDARD_REMEDIATION.md",
                                "docs/databank/PHASE8_ACQ0_ACQUISITION_EVENT_AUTHORITY.md",
                                "docs/databank/PHASE8_OBS60_I1_IDENTITY_CONTINUITY_COVERAGE.md",
                                "docs/databank/PHASE8_EXE_R_PROVIDER_REVISION_KNOWLEDGE.md",
                                "docs/databank/PHASE8_EPOCH1_ACQUISITION_MANIFEST.md",
                                "docs/databank/PHASE8_A2C_DUAL_TIME_COVERAGE.md",
                                "docs/databank/PHASE8_EPOCH1R_HELD_PERIOD_METADATA.md",
                                "docs/databank/PHASE8_A2C_R_PROVIDER_HOLDINGS_AUTHORITY.md",
                                "docs/databank/PHASE8_OBS60_F1_PROVIDER_HOLDINGS_EXECUTOR.md",
                                "docs/databank/PHASE8_A3_RA_RETROSPECTIVE_METRICS.md",
                                "docs/databank/PHASE8_PILOT2B_PRIVATE_RETROSPECTIVE_E2E.md",
                                "docs/databank/PHASE8_B1_SCREENER_SEMANTIC_MODELS.md",
                                "docs/databank/PHASE8_B2_FINANCIAL_CRITERIA_EVALUATOR.md",
                                "docs/databank/PHASE8_B3_PRIVATE_POLICY_AUTHORITY_STORE.md")
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
           "P8_A2_5", "P8_A3A", "P8_A3B", "P8_A3R", "P8_ST1", "P8_ADP0", "P8_EXE", "P8_ID1", "P8_LIVE0", "P8_LIVE1",
           "P8_LIVE2", "P8_PILOT2A", "P8_ADP0R", "P8_ACQ0", "P8_OBS60_I1", "P8_EXE_R", "P8_EPOCH1", "P8_A2C", "P8_EPOCH1R", "P8_A2C_R", "P8_F1", "P8_A3_RA", "P8_PILOT2B", "P8_B1", "P8_B2", "P8_V",
           "P8_VR",
           "PHASE7_TEST_REGISTRATION", "PHASE8_A1R_RUNTIME", "PHASE8_A1_RUNTIME", "PHASE8_A2R_RUNTIME",
           "PHASE8_A2_RUNTIME", "PHASE8_A3A_RUNTIME", "PHASE8_A3B_METRIC_MODEL_REGISTRATION", "PHASE8_A3B_RUNTIME",
           "PHASE8_ACQ0_RUNTIME", "PHASE8_OBS60_I1_RUNTIME", "PHASE8_EPOCH1_RUNTIME", "PHASE8_A2C_RUNTIME",
           "PHASE8_A2C_R_RUNTIME", "PHASE8_F1_RUNTIME", "PHASE8_A3_RA_RUNTIME", "PHASE8_B1_RUNTIME", "PHASE8_B2_RUNTIME", "PHASE8_B3_RUNTIME",
           "PHASE8_ADP0_RUNTIME",
           "PHASE8_EXE_RUNTIME",
           "PHASE8_ID1_RUNTIME",
           "PHASE8_ID2_RUNTIME",
           "PHASE8_LIVE1_RUNTIME", "PHASE8_LIVE2_RUNTIME", "PHASE8_PILOT2A_RUNTIME", "PHASE8_PACKAGE_RUNTIME",
           "PHASE8_DOCS",
           "PHASE8_ST1_RUNTIME",
           "PHASE8_PACKAGE", "PHASE8_RUNTIME", "PHASE8_TESTS", "is_phase8_addition", "only_phase8_registration",
           "registration_diff"]
