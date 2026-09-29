"""Phase 8 Screener Intelligence の境界 ／ 凍結の guard（P8-A1 の matrix BA〜BO）。

- BA〜BG: import 境界（module ごとの許可一覧 ・runtime closure）。Phase 6 ／ 7 ・P5 ・legacy ・J-Quants の transport ・
  provider ／ network ・公開 ／ 通知 ／ 売買を import しない。時計 ・乱数 ・動的 code なし。filesystem は store だけ。
- BH〜BJ: screen ・基準 ・候補 ・順位 ・score ・Theme exposure の型 ／ 名前が無い。
- BK〜BO: Phase 7 ／ 6 の凍結、Phase 8 の registry の完全一致、未登録の Phase 8 runtime の検出、他の package からの import なし。
- P8-A2（BY〜CL）: A1 の runtime は `4162e9c` と byte 一致、観測の module は許可一覧どおり（A1 の store ／ resolver の API は
  指名した module が決まった名前だけを使う）、派生指標 ・screen ・順位 ・Theme の型 ／ 語彙が無い。
- P8-A2.5: A1 ／ A2 の runtime と A2 の契約は `b686b00` と byte 一致（監査の文書は registry に登録）。
- P8-V: runtime と A2.5 の監査の文書は `5713a56` と byte 一致（公式の仕様の確認の文書は registry に登録）。
- P8-VR: runtime と A2.5 ・P8-V の文書は `fc91ee1` と byte 一致（確認の是正の文書は registry に登録）。
- P8-A1R: 訂正 ・2 軸の解決の module は許可一覧どおり（A1 の名前は決まったものだけ。A2 を使わない）、A1 ／ A2 の runtime と
  先行の Phase 8 の文書は `7b8d375` と byte 一致。

registry: `tests/intelligence/phase8_runtime_registry.py`。契約: `docs/databank/PHASE8_ISSUER_SECURITY_IDENTITY_CONTRACT.md`。
"""
from __future__ import annotations

import ast
import re
import subprocess
import sys
from pathlib import Path

import pytest

from tests.intelligence.phase7_runtime_registry import (PHASE6_TEST_REGISTRATION, PHASE7_EXCLUDED_PATHSPECS,
                                                        PHASE7_RUNTIME, is_phase7_addition)
from tests.intelligence.phase8_runtime_registry import (ADDITION_STATUSES, P8_A0, P8_A1, P8_A1R, P8_A2, P8_A2_5, P8_V,
                                                        P8_LV1, P8_PILOT1, P8_A2R, P8_A2RI, P8_A2RV, P8_A3A, P8_A3B,
                                                        P8_A3R, P8_ST1, P8_ADP0, P8_EXE, P8_ID1, P8_VR,
                                                        PHASE7_TEST_REGISTRATION, PHASE8_A1R_RUNTIME, PHASE8_A1_RUNTIME,
                                                        PHASE8_A2R_RUNTIME, PHASE8_A2_RUNTIME, PHASE8_A3A_RUNTIME,
                                                        PHASE8_A3B_METRIC_MODEL_REGISTRATION, PHASE8_A3B_RUNTIME,
                                                        PHASE8_ST1_RUNTIME, PHASE8_ADP0_RUNTIME, PHASE8_EXE_RUNTIME,
                                                        PHASE8_ID1_RUNTIME, PHASE8_ID2_RUNTIME, PHASE8_DOCS,
                                                        PHASE8_PACKAGE, PHASE8_RUNTIME, PHASE8_TESTS,
                                                        registration_diff,
                                                        is_phase8_addition, only_phase8_registration)
from tests.intelligence.test_p43b2c_production_bundle import runtime_closure
from tests.intelligence.test_prediction_record import executable_source, imported_modules

REPO_ROOT = Path(__file__).resolve().parents[2]
PACKAGE_DIR = REPO_ROOT / PHASE8_PACKAGE
MODULES = ("__init__", "fundamental_metrics", "fundamental_metrics_extended", "held_observation_model",
           "held_observation_store", "identity_bootstrap", "identity_bootstrap_model", "identity_correction_model",
           "identity_correction_store", "identity_model", "identity_registration_executor",
           "identity_registration_model", "identity_remediation_resolver", "identity_resolver", "identity_store",
           "jquants_adapter_model", "jquants_execution_model", "jquants_financial_summary_adapter",
           "jquants_financial_summary_executor", "metric_model", "observation_model", "observation_resolver",
           "observation_semantics_gate", "observation_semantics_mapping", "observation_semantics_model",
           "observation_store", "semantic_metadata_store")
A1_MODULES = ("__init__", "identity_model", "identity_resolver", "identity_store")
A2_MODULES = ("observation_model", "observation_resolver", "observation_store")
A1R_MODULES = ("identity_correction_model", "identity_correction_store", "identity_remediation_resolver")
A2R_MODULES = ("observation_semantics_gate", "observation_semantics_mapping", "observation_semantics_model")
A3A_MODULES = ("fundamental_metrics", "metric_model")
A3B_MODULES = ("fundamental_metrics_extended",)
ST1_MODULES = ("held_observation_model", "held_observation_store", "semantic_metadata_store")
ADP0_MODULES = ("jquants_adapter_model", "jquants_financial_summary_adapter")
EXE_MODULES = ("jquants_execution_model", "jquants_financial_summary_executor")
ID1_MODULES = ("identity_bootstrap_model", "identity_bootstrap")
ID2_MODULES = ("identity_registration_model", "identity_registration_executor")
#: P8-A2R-IMPL より前に凍結した runtime ・test（LV1 ・PILOT1 ・A2R ・A2RV の anchor はこれらだけを持つ）
PRE_A2R_RUNTIME = tuple(sorted(set(PHASE8_A2_RUNTIME) | set(PHASE8_A1R_RUNTIME)))
#: P8-A3A より前に凍結した runtime（A2RI の anchor はこれらを持つ。A2R の 3 module を含む）
PRE_A3A_RUNTIME = tuple(sorted(set(PRE_A2R_RUNTIME) | set(PHASE8_A2R_RUNTIME)))
A2R_TEST = "tests/intelligence/test_screener_observation_semantics.py"
A3A_TEST = "tests/intelligence/test_screener_fundamental_metrics.py"
A3B_TEST = "tests/intelligence/test_screener_fundamental_metrics_extended.py"
ST1_TEST = "tests/intelligence/test_screener_operational_stores.py"
ADP0_TEST = "tests/intelligence/test_screener_jquants_adapter.py"
EXE_TEST = "tests/intelligence/test_screener_jquants_execution.py"
ID1_TEST = "tests/intelligence/test_screener_identity_bootstrap.py"
ID2_TEST = "tests/intelligence/test_screener_identity_registration.py"
#: 先行の anchor の guard が凍結の対象から外す、後の gate の test
LATER_TESTS = (A2R_TEST, A3A_TEST, A3B_TEST, ST1_TEST, ADP0_TEST, EXE_TEST, ID1_TEST, ID2_TEST)
#: P8-A3B より前に凍結した runtime（A3A の anchor はこれらを持つ。A3A の 2 module を含む）
PRE_A3B_RUNTIME = tuple(sorted(set(PRE_A3A_RUNTIME) | set(PHASE8_A3A_RUNTIME)))
METRIC_MODEL = f"{PHASE8_PACKAGE}/metric_model.py"
#: P8-ST1 より前に凍結した runtime（A3B ・A3R の anchor はこれらを持つ。16 module）
PRE_ST1_RUNTIME = tuple(sorted(set(PRE_A3B_RUNTIME) | set(PHASE8_A3B_RUNTIME)))
#: P8-ADP0 より前に凍結した runtime（ST1 の anchor はこれらを持つ。19 module）
PRE_ADP0_RUNTIME = tuple(sorted(set(PRE_ST1_RUNTIME) | set(PHASE8_ST1_RUNTIME)))
#: P8-EXE より前に凍結した runtime（ADP0 の anchor はこれらを持つ。21 module）
PRE_EXE_RUNTIME = tuple(sorted(set(PRE_ADP0_RUNTIME) | set(PHASE8_ADP0_RUNTIME)))
#: P8-ID1 より前に凍結した runtime（EXE の anchor はこれらを持つ。23 module）
PRE_ID1_RUNTIME = tuple(sorted(set(PRE_EXE_RUNTIME) | set(PHASE8_EXE_RUNTIME)))
#: P8-ID2 より前に凍結した runtime（ID1 の anchor はこれらを持つ。25 module）
PRE_ID2_RUNTIME = tuple(sorted(set(PRE_ID1_RUNTIME) | set(PHASE8_ID1_RUNTIME)))
IO_MODULES = ("identity_store", "observation_store", "identity_correction_store", "semantic_metadata_store",
              "held_observation_store")
PHASE7_FINAL = "c1e95d35026652fb27c637318593fa8688219cf7"
PHASE6_COMPLETION = "5ef313a6a9477f05b4e46756fb8b79c0f0c3d685"
A1_DOC = "docs/databank/PHASE8_ISSUER_SECURITY_IDENTITY_CONTRACT.md"
A2_DOC = "docs/databank/PHASE8_PIT_OBSERVATION_CONTRACT.md"
A2_5_DOC = "docs/databank/PHASE8_JQUANTS_REAL_DATA_MAPPING_AUDIT.md"
V_DOC = "docs/databank/PHASE8_JQUANTS_OFFICIAL_SPEC_VERIFICATION.md"
VR_DOC = "docs/databank/PHASE8_JQUANTS_VERIFICATION_REMEDIATION.md"
A1R_DOC = "docs/databank/PHASE8_IDENTITY_REMEDIATION_CONTRACT.md"
LV1_DOC = "docs/databank/PHASE8_JQUANTS_LIGHT_MINIMUM_FIELD_CONTRACT.md"
PILOT1_DOC = "docs/databank/PHASE8_JQUANTS_LIGHT_PILOT1_REPORT.md"
A2R_DOC = "docs/databank/PHASE8_A2R_JQUANTS_SEMANTIC_REMEDIATION.md"
A2RV_DOC = "docs/databank/PHASE8_A2R_OFFICIAL_SPEC_VERIFICATION.md"
A2RI_DOC = "docs/databank/PHASE8_A2R_IMPLEMENTATION.md"
A3A_DOC = "docs/databank/PHASE8_A3A_FUNDAMENTAL_METRICS.md"
A3B_DOC = "docs/databank/PHASE8_A3B_NET_MARGIN_ROA.md"
A3R_DOC = "docs/databank/PHASE8_A3R_REAL_DATA_BRIDGE_DESIGN.md"
ST1_DOC = "docs/databank/PHASE8_ST1_OPERATIONAL_STORES.md"
ADP0_DOC = "docs/databank/PHASE8_ADP0_JQUANTS_FINANCIAL_SUMMARY_ADAPTER.md"
EXE_DOC = "docs/databank/PHASE8_EXE_SAFE_APPEND_EXECUTOR.md"
ID1_DOC = "docs/databank/PHASE8_ID1_IDENTITY_BOOTSTRAP.md"
ID2_DOC = "docs/databank/PHASE8_ID2_IDENTITY_REGISTRATION_EXECUTOR.md"
LIVE0_DOC = "docs/databank/PHASE8_LIVE0_PRELIVE_AUDIT.md"
PHASE7_DOCS = tuple(f"docs/databank/PHASE7_{name}.md" for name in (
    "NARRATIVE_ARCHITECTURE_AUDIT", "NARRATIVE_SEMANTICS_MODEL_CONTRACT", "NARRATIVE_PIT_INPUT_CONTRACT",
    "NARRATIVE_DETERMINISTIC_SYNTHESIS_CONTRACT", "NARRATIVE_PRESENTATION_DIFF_CONTRACT",
    "NARRATIVE_DETERMINISTIC_RENDERER_CONTRACT", "NARRATIVE_INTELLIGENCE_COMPLETION_AUDIT"))
SURFACE = ("src", "knowledge", "config.yaml", ".github", "scripts", "docs/pages", "docs/v2", "data", "main.py",
           "requirements.txt", "pyproject.toml")

_CORE = {"..core.ids", "..core.time"}
ALLOWED_IMPORTS = {
    "__init__": set(),
    "identity_model": {"__future__", "json", "re", "dataclasses", "datetime", "enum", "typing"} | _CORE,
    "identity_store": {"__future__", "os", "dataclasses", "enum", "pathlib", "typing", ".identity_model"},
    "identity_resolver": {"__future__", "dataclasses", "datetime", "enum", "typing", ".identity_model",
                          ".identity_store", "..core.time"},
    "observation_model": {"__future__", "json", "re", "dataclasses", "datetime", "decimal", "enum", "typing",
                          ".identity_model"} | _CORE,
    "observation_store": {"__future__", "os", "dataclasses", "enum", "pathlib", "typing", ".identity_store",
                          ".observation_model"},
    "observation_resolver": {"__future__", "dataclasses", "datetime", "enum", "typing", ".identity_model",
                             ".identity_resolver", ".observation_model", ".observation_store", "..core.time"},
    "identity_correction_model": {"__future__", "json", "re", "dataclasses", "datetime", "enum", "typing",
                                  ".identity_model"} | _CORE,
    "identity_correction_store": {"__future__", "os", "dataclasses", "enum", "pathlib", "typing",
                                  ".identity_correction_model", ".identity_store"},
    "identity_remediation_resolver": {"__future__", "dataclasses", "datetime", "enum", "typing",
                                      ".identity_correction_model", ".identity_correction_store", ".identity_model",
                                      ".identity_resolver", "..core.time"},
    "observation_semantics_model": {"__future__", "re", "dataclasses", "enum", "typing", ".identity_model",
                                    ".observation_model", "..core.ids"},
    "observation_semantics_mapping": {"__future__", "dataclasses", "typing", ".identity_model", ".observation_model",
                                      ".observation_semantics_model"},
    "observation_semantics_gate": {"__future__", "dataclasses", "enum", "typing", ".observation_model",
                                   ".observation_semantics_model"},
    "metric_model": {"__future__", "dataclasses", "datetime", "enum", "typing", ".observation_model", "..core.time"},
    "fundamental_metrics": {"__future__", "datetime", "decimal", "typing", ".identity_model", ".metric_model",
                            ".observation_model", ".observation_resolver", ".observation_semantics_gate",
                            ".observation_semantics_model"},
    "fundamental_metrics_extended": {"__future__", "typing", ".fundamental_metrics", ".identity_model",
                                     ".metric_model", ".observation_model", ".observation_resolver"},
    "semantic_metadata_store": {"__future__", "json", "os", "dataclasses", "enum", "pathlib", "typing",
                                ".observation_semantics_model"},
    "held_observation_model": {"__future__", "re", "dataclasses", "datetime", "enum", "typing", ".identity_model",
                               ".observation_model", ".observation_semantics_model"} | _CORE,
    "held_observation_store": {"__future__", "json", "os", "dataclasses", "enum", "pathlib", "typing",
                               ".held_observation_model"},
    "jquants_adapter_model": {"__future__", "hashlib", "re", "dataclasses", "datetime", "enum", "typing",
                              ".held_observation_model", ".identity_model", ".observation_model",
                              ".observation_semantics_model"},
    "jquants_financial_summary_adapter": {"__future__", "re", "datetime", "typing", ".held_observation_model",
                                          ".identity_model", ".jquants_adapter_model", ".observation_model",
                                          ".observation_semantics_mapping", ".observation_semantics_model"},
    "jquants_execution_model": {"__future__", "dataclasses", "enum", "typing", ".held_observation_model",
                                ".jquants_adapter_model", ".observation_model"},
    "jquants_financial_summary_executor": {"__future__", "dataclasses", "typing", ".held_observation_model",
                                           ".held_observation_store", ".identity_model", ".jquants_adapter_model",
                                           ".jquants_execution_model", ".jquants_financial_summary_adapter",
                                           ".observation_model", ".observation_semantics_gate",
                                           ".observation_semantics_mapping", ".observation_semantics_model",
                                           ".observation_store", ".semantic_metadata_store"},
    "identity_bootstrap_model": {"__future__", "hashlib", "re", "dataclasses", "datetime", "enum", "typing",
                                 ".identity_model", ".jquants_adapter_model", ".observation_model"},
    "identity_bootstrap": {"__future__", "typing", ".identity_bootstrap_model", ".identity_model"},
    "identity_registration_model": {"__future__", "dataclasses", "enum", "typing", ".identity_model",
                                    ".jquants_adapter_model"},
    "identity_registration_executor": {"__future__", "typing", ".identity_bootstrap", ".identity_bootstrap_model",
                                       ".identity_model", ".identity_registration_model", ".identity_store"},
}
#: A2 が使ってよい A1 の名前（module → 名前。完全一致）。A1 の store ／ resolver の API は指名した module だけが使う
SANCTIONED_A1_IMPORTS = {
    "observation_model": {".identity_model": {"CREDENTIAL_MARKERS", "IdentityHistory", "SourceClass", "SubjectKind",
                                              "canonical_json", "is_issuer_id", "is_security_id"}},
    "observation_store": {".identity_store": {"IdentityAuthorityMissing", "IdentityStoreCorrupt",
                                              "open_identity_history"}},
    "observation_resolver": {".identity_resolver": {"IdentityQuery", "ResolutionStatus", "resolve"},
                             ".identity_model": {"SourceClass", "SubjectKind", "canonical_json", "is_issuer_id",
                                                 "is_security_id"}},
}
#: A1R が使ってよい A1 の名前（module → 名前。完全一致）。A1 の store は訂正の store だけ、A1 の resolver は 2 軸の resolver だけ
SANCTIONED_A1R_IMPORTS = {
    "identity_correction_model": {".identity_model": {"AUTHORITY_RULES_VERSION", "CREDENTIAL_MARKERS", "SCHEMA_VERSION",
                                                      "IdentityHistory", "IdentityHistoryError", "IdentityModelError",
                                                      "RecordKind", "SourceClass", "canonical_json",
                                                      "is_identity_record", "parse_identity_record"}},
    "identity_correction_store": {".identity_store": {"IDENTITY_DIRNAME", "IdentityAuthorityMissing",
                                                      "IdentityStoreCorrupt", "open_identity_history"}},
    "identity_remediation_resolver": {".identity_model": {"RecordKind", "canonical_json"},
                                      ".identity_resolver": {"DERIVED_NON_AUTHORITY_NON_PERSISTENT", "IdentityQuery",
                                                             "IdentityResolution", "QueryKind", "resolve"}},
}
#: A2R-IMPL が使ってよい A1 ／ A2 の名前（module → 名前。完全一致）。A2 の store ・resolver ・履歴は使わない（A2 の authority は不変）
SANCTIONED_A2R_IMPORTS = {
    "observation_semantics_model": {".identity_model": {"CREDENTIAL_MARKERS", "SourceClass", "canonical_json"},
                                    ".observation_model": {"StatementBasis"}},
    "observation_semantics_mapping": {".identity_model": {"SourceClass"}, ".observation_model": {"StatementBasis"}},
    "observation_semantics_gate": {".observation_model": {"FundamentalActual", "FundamentalForecast"}},
}
#: A3A が使ってよい A1 ／ A2 ／ A2R の名前（module → 名前。完全一致）。revision の選択は A2 の `resolve` だけ、互換は A2R の gate だけ。
#: store ・履歴の内部（chains ・coverages）・A1R は使わない
SANCTIONED_A3A_IMPORTS = {
    "metric_model": {".observation_model": {"ReportingPeriod", "StatementBasis"}},
    "fundamental_metrics": {".identity_model": {"SourceClass", "is_issuer_id"},
                            ".observation_model": {"FundamentalField", "ObservationHistory", "PeriodBasis",
                                                   "ReportingPeriod", "Scale", "StatementBasis", "ValueState",
                                                   "canonical_decimal"},
                            ".observation_resolver": {"ObservationQuery", "ObservationStatus", "resolve"},
                            ".observation_semantics_gate": {"CompatibilityReason", "CompatibilityVerdict",
                                                            "decide_compatibility"},
                            ".observation_semantics_model": {"ObservationSemantics"}},
}
#: A3B が使ってよい名前（module → 名前。完全一致）。脚の解決 ・互換 ・比 ・結果の組み立ては A3A の実装をそのまま使う
SANCTIONED_A3B_IMPORTS = {
    "fundamental_metrics_extended": {".fundamental_metrics": {"_Leg", "_compatibility", "_input_reasons", "_label_for",
                                                              "_ratio_minus", "_regular_fiscal_year", "_resolve_leg",
                                                              "_result"},
                                     ".identity_model": {"SourceClass"},
                                     ".metric_model": {"MetricKind", "MetricLeg", "MetricReason", "MetricResult",
                                                       "ReasonCode"},
                                     ".observation_model": {"FundamentalField", "PeriodBasis"},
                                     ".observation_resolver": {"ObservationQuery"}},
}
#: ST1 が使ってよい A1 ／ A2 ／ A2R の名前（module → 名前。完全一致）。store ・resolver ・履歴 ・指標は使わない（authority の分離）
SANCTIONED_ST1_IMPORTS = {
    "semantic_metadata_store": {".observation_semantics_model": {"MAPPING_PROVENANCE_RECORD_KIND",
                                                                 "SEMANTIC_METADATA_RECORD", "SEMANTICS_RECORD_KIND",
                                                                 "ObservationSemantics", "SemanticMappingProvenance",
                                                                 "SemanticsModelError"}},
    "held_observation_model": {".identity_model": {"CREDENTIAL_MARKERS", "SourceClass", "canonical_json",
                                                   "is_issuer_id", "is_security_id"},
                               ".observation_model": {"FundamentalField", "StatementBasis"},
                               ".observation_semantics_model": {"SchemaFamily"}},
    "held_observation_store": {".held_observation_model": {"HELD_RECORD_KIND", "OPERATIONAL_HOLD_RECORD",
                                                           "HeldObservation", "HeldObservationModelError",
                                                           "is_held_observation"}},
}
#: ADP0 が使ってよい名前（module → 名前。完全一致）。A2 の record ・A2R の写しの authority ・ST1 の record の型だけ。
#: store ・resolver ・指標 ・A1 の登録 ・id の導出は使わない
SANCTIONED_ADP0_IMPORTS = {
    "jquants_adapter_model": {".held_observation_model": {"HeldObservation", "HeldReason"},
                              ".identity_model": {"CREDENTIAL_MARKERS", "canonical_json"},
                              ".observation_model": {"FundamentalActual", "KnowledgeTime", "ReportingPeriod"},
                              ".observation_semantics_model": {"ObservationSemantics", "SemanticMappingProvenance"}},
    "jquants_financial_summary_adapter": {
        ".held_observation_model": {"HeldObservation", "HeldReason", "ordered_reasons"},
        ".identity_model": {"SourceClass", "is_issuer_id"},
        ".jquants_adapter_model": {"ADAPTER_RULES_VERSION", "AdapterContext", "AdapterInputError", "AdapterResult",
                                   "AdapterStatus", "EligibleMaterial", "FinancialSummaryRow",
                                   "ProviderRecordIdentity"},
        ".observation_model": {"TOKYO", "Currency", "FundamentalActual", "FundamentalField", "KnowledgeTime",
                               "Measure", "ObservationModelError", "ObservationProvenance", "ObservationValue",
                               "PeriodBasis", "ReportingPeriod", "Scale", "StatementBasis", "ValueState"},
        ".observation_semantics_mapping": {"DOCTYPE_MAPPING_VERSION", "derive_observation_semantics",
                                           "map_row_semantics"},
        ".observation_semantics_model": {"AccountingStandard", "DocumentKind", "FieldFamily", "SchemaFamily"}},
}
#: EXE が使ってよい名前（module → 名前。完全一致）。書く先は A2 ・注記 ・保留の 3 store だけ。identity の store ・resolver ・登録 ・
#: 指標 ・observation_resolver は使わない
SANCTIONED_EXE_IMPORTS = {
    "jquants_execution_model": {".held_observation_model": {"HeldReason"},
                                ".jquants_adapter_model": {"DERIVED_NON_AUTHORITY_NON_PERSISTENT",
                                                           "ProviderRecordIdentity"},
                                ".observation_model": {"FundamentalField"}},
    "jquants_financial_summary_executor": {
        ".held_observation_model": {"HeldObservation", "HeldObservationModelError", "HeldReason"},
        ".held_observation_store": {"HeldObservationStore", "HeldStoreCorrupt", "HeldStoreError", "HeldStoreMissing"},
        ".identity_model": {"SourceClass"},
        ".jquants_adapter_model": {"AdapterContext", "AdapterInputError", "AdapterResult", "AdapterStatus",
                                   "FinancialSummaryRow", "ProviderRecordIdentity"},
        ".jquants_execution_model": {"EXECUTION_RULES_VERSION", "AuthorityWrites", "ExecutionOutcome",
                                     "ExecutionReason", "ExecutionResult", "FieldDisposition", "FieldExecution",
                                     "WriteState", "ordered_execution_reasons"},
        ".jquants_financial_summary_adapter": {"adapt_financial_summary_row"},
        ".observation_model": {"FundamentalActual", "ObservationHistoryError", "ObservationModelError", "ValueState"},
        ".observation_semantics_gate": {"AppendEligibility", "plan_append"},
        ".observation_semantics_mapping": {"DOCTYPE_MAPPING_VERSION", "derive_observation_semantics"},
        ".observation_semantics_model": {"FieldFamily", "ObservationSemantics", "SchemaFamily",
                                         "SemanticMappingProvenance"},
        ".observation_store": {"ObservationAuthorityMissing", "ObservationStore", "ObservationStoreCorrupt",
                               "ObservationStoreError"},
        ".semantic_metadata_store": {"SemanticMetadataCorrupt", "SemanticMetadataJournalError",
                                     "SemanticMetadataMissing", "SemanticMetadataStore",
                                     "SemanticMetadataStoreError"}},
}
#: ID1 が使ってよい名前（module → 名前。完全一致）。凍結 A1 の model（record の型 ・id の導出 ・履歴の検査）だけ。store ・resolver ・
#: executor ・A2 ・注記 ・保留は使わない
SANCTIONED_ID1_IMPORTS = {
    "identity_bootstrap_model": {".identity_model": {"CREDENTIAL_MARKERS", "IDENTIFIER_PATTERNS", "IdentifierScheme",
                                                     "IssueClass", "canonical_json", "derive_issuer_id",
                                                     "derive_security_id", "is_issuer_id", "is_security_id"},
                                 ".jquants_adapter_model": {"DERIVED_NON_AUTHORITY_NON_PERSISTENT"},
                                 ".observation_model": {"TOKYO"}},
    "identity_bootstrap": {
        ".identity_bootstrap_model": {"BootstrapBatch", "BootstrapInputError", "BootstrapManifest", "BootstrapReason",
                                      "IdentityProposal", "MasterRow", "PlanSkipReason", "PlannedRegistration",
                                      "ProposalDisposition", "ProposalReview", "RegistrationPlan",
                                      "ReviewDisposition", "ReviewItem", "ReviewedManifest",
                                      "ordered_bootstrap_reasons"},
        ".identity_model": {"Coverage", "CoverageScope", "DisplayName", "IDENTIFIER_PATTERNS", "IdentifierAssignment",
                            "IdentifierScheme", "IdentityHistory", "IdentityHistoryError", "IdentityModelError",
                            "IssueClass", "IssuerRegistration", "ListingStart", "ListingVenue", "NameKind",
                            "NameLanguage", "SecurityRegistration", "SourceClass", "SourceProvenance", "SubjectKind",
                            "derive_issuer_id", "derive_security_id"}},
}
#: ID2 が使ってよい名前（module → 名前。完全一致）。書く先は A1 の `IdentityStore` だけ。resolver ・A2 ・注記 ・保留 ・EXE は使わない
SANCTIONED_ID2_IMPORTS = {
    "identity_registration_model": {".identity_model": {"RecordKind"},
                                    ".jquants_adapter_model": {"DERIVED_NON_AUTHORITY_NON_PERSISTENT"}},
    "identity_registration_executor": {
        ".identity_bootstrap": {"BootstrapPlanError", "plan_registration", "propose_bootstrap"},
        ".identity_bootstrap_model": {"BootstrapBatch", "BootstrapInputError", "RegistrationPlan", "ReviewedManifest",
                                      "ReviewerClass"},
        ".identity_model": {"IdentifierScheme", "IdentityHistory", "IdentityHistoryError", "RecordKind"},
        ".identity_registration_model": {"REGISTRATION_RULES_VERSION", "BundleExecution", "RecordWrite",
                                         "RegistrationOutcome", "RegistrationReason", "RegistrationResult",
                                         "RegistrationWrites", "WriteState", "ordered_registration_reasons"},
        ".identity_store": {"IdentityAuthorityMissing", "IdentityStore", "IdentityStoreCorrupt",
                            "IdentityStoreError"}},
}
ALLOWED_CLOSURE = {"src", "src.intelligence", "src.intelligence.core", "src.intelligence.core.ids",
                   "src.intelligence.core.time", "src.intelligence.screener_intelligence"}
EXPECTED_INTERNAL = {"__init__": set(), "identity_model": set(), "identity_store": {"identity_model"},
                     "identity_resolver": {"identity_model", "identity_store"},
                     "observation_model": {"identity_model"},
                     "observation_store": {"identity_model", "identity_store", "observation_model"},
                     "observation_resolver": {"identity_model", "identity_store", "identity_resolver",
                                              "observation_model", "observation_store"},
                     "identity_correction_model": {"identity_model"},
                     "identity_correction_store": {"identity_model", "identity_store", "identity_correction_model"},
                     "identity_remediation_resolver": {"identity_model", "identity_store", "identity_resolver",
                                                       "identity_correction_model", "identity_correction_store"},
                     "observation_semantics_model": {"identity_model", "observation_model"},
                     "observation_semantics_mapping": {"identity_model", "observation_model",
                                                       "observation_semantics_model"},
                     "observation_semantics_gate": {"identity_model", "observation_model",
                                                    "observation_semantics_model"},
                     "metric_model": {"identity_model", "observation_model"},
                     "fundamental_metrics": {"identity_model", "identity_store", "identity_resolver",
                                             "observation_model", "observation_store", "observation_resolver",
                                             "observation_semantics_model", "observation_semantics_gate",
                                             "metric_model"},
                     "fundamental_metrics_extended": {"identity_model", "identity_store", "identity_resolver",
                                                      "observation_model", "observation_store", "observation_resolver",
                                                      "observation_semantics_model", "observation_semantics_gate",
                                                      "metric_model", "fundamental_metrics"},
                     "semantic_metadata_store": {"identity_model", "observation_model", "observation_semantics_model"},
                     "held_observation_model": {"identity_model", "observation_model", "observation_semantics_model"},
                     "held_observation_store": {"identity_model", "observation_model", "observation_semantics_model",
                                                "held_observation_model"},
                     "jquants_adapter_model": {"identity_model", "observation_model", "observation_semantics_model",
                                               "held_observation_model"},
                     "jquants_financial_summary_adapter": {"identity_model", "observation_model",
                                                           "observation_semantics_model",
                                                           "observation_semantics_mapping", "held_observation_model",
                                                           "jquants_adapter_model"},
                     "jquants_execution_model": {"identity_model", "observation_model", "observation_semantics_model",
                                                 "held_observation_model", "jquants_adapter_model"},
                     "jquants_financial_summary_executor": {"identity_model", "identity_store", "observation_model",
                                                            "observation_store", "observation_semantics_model",
                                                            "observation_semantics_mapping",
                                                            "observation_semantics_gate", "held_observation_model",
                                                            "held_observation_store", "semantic_metadata_store",
                                                            "jquants_adapter_model", "jquants_execution_model",
                                                            "jquants_financial_summary_adapter"},
                     "identity_bootstrap_model": {"identity_model", "observation_model", "observation_semantics_model",
                                                  "held_observation_model", "jquants_adapter_model"},
                     "identity_bootstrap": {"identity_model", "observation_model", "observation_semantics_model",
                                            "held_observation_model", "jquants_adapter_model",
                                            "identity_bootstrap_model"},
                     "identity_registration_model": {"identity_model", "observation_model",
                                                     "observation_semantics_model", "held_observation_model",
                                                     "jquants_adapter_model"},
                     "identity_registration_executor": {"identity_model", "identity_store", "observation_model",
                                                        "observation_semantics_model", "held_observation_model",
                                                        "jquants_adapter_model", "identity_bootstrap_model",
                                                        "identity_bootstrap", "identity_registration_model"}}


def _git(*args: str) -> str:
    return subprocess.run(["git", *args], cwd=REPO_ROOT, capture_output=True, text=True, check=True).stdout


def _sources():
    return [(path.stem, path) for path in sorted(PACKAGE_DIR.glob("*.py"))]


# ================================================================ BA〜BG import 境界


@pytest.mark.parametrize("name,path", _sources())
def test_ba_to_bg_modules_import_only_their_allowed_modules(name: str, path: Path) -> None:
    assert imported_modules(path) <= ALLOWED_IMPORTS[name], imported_modules(path) - ALLOWED_IMPORTS[name]


@pytest.mark.parametrize("module", MODULES)
def test_ba_to_bg_the_runtime_closure_is_core_and_this_package_only(module: str) -> None:
    target = "src.intelligence.screener_intelligence" + ("" if module == "__init__" else f".{module}")
    code = f"import sys\nimport {target}\nprint('\\n'.join(sorted(sys.modules)))\n"
    proc = subprocess.run([sys.executable, "-c", code], cwd=REPO_ROOT, capture_output=True, text=True, check=True,
                          env={"PYTHONPATH": str(REPO_ROOT), "PATH": ""})
    loaded = set(proc.stdout.split())
    first_party = {m for m in loaded if m.startswith("src")}
    if module == "__init__":                                                         # package は何も import しない
        assert first_party == {"src", "src.intelligence", "src.intelligence.screener_intelligence"}
    else:
        internal = {module} | EXPECTED_INTERNAL[module]
        assert first_party == ALLOWED_CLOSURE | {f"src.intelligence.screener_intelligence.{n}" for n in internal}
    assert not loaded & {"socket", "ssl", "http", "http.client", "urllib.request", "sqlite3", "requests", "httpx",
                         "anthropic", "openai"}                                    # 乱数 ・時計の使用は AST で禁止


FORBIDDEN_MODULE_TOKENS = ("themes", "theme_intelligence", "narrative_intelligence", "predictions", "compass",
                           "reports", "facts", "context", "internals", "market", "jquants", "jquants_ops", "databank",
                           "analysis", "report", "collectors", "notifiers", "delivery", "pages", "public", "evaluation",
                           "calibration", "corpus", "formal_review", "decision", "thesis", "screening",
                           "personalization", "replay", "pipeline", "enrichment", "sources", "ingestion", "provider",
                           "providers", "anthropic", "openai", "requests", "httpx", "urllib", "socket", "sqlite3",
                           "subprocess", "trading", "portfolio", "notification", "llm")


@pytest.mark.parametrize("name,path", _sources())
def test_ba_to_bg_no_phase6_phase7_p5_legacy_jquants_provider_network_or_public_import(name: str, path: Path) -> None:
    for module in imported_modules(path):
        assert not any(token in module.split(".") for token in FORBIDDEN_MODULE_TOKENS), module


FORBIDDEN_NAMES = {"print", "input", "eval", "exec", "compile", "__import__", "getattr", "setattr", "globals",
                   "sys", "subprocess", "socket", "urllib", "requests", "sqlite3", "pickle", "shelve", "random",
                   "secrets", "uuid", "time", "new_id", "new_ulid", "environ", "getenv", "sha256_hex"}
FORBIDDEN_ATTRIBUTES = {"now", "utcnow", "today", "environ", "getenv", "urlopen", "connect", "request", "getmtime",
                        "st_mtime", "st_mtime_ns", "getpid", "urandom"}
IO_NAMES = {"open", "Path", "os"}
IO_ATTRIBUTES = {"write", "write_text", "write_bytes", "read_text", "read_bytes", "mkdir", "unlink", "touch", "rename",
                 "rmdir", "remove", "makedirs", "fsync", "flush", "replace_file", "truncate"}


@pytest.mark.parametrize("name,path", _sources())
def test_ba_to_bg_no_clock_randomness_network_or_dynamic_code_and_io_only_in_the_store(name: str, path: Path) -> None:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.Name):
            assert node.id not in FORBIDDEN_NAMES, (name, node.id)
            if name not in IO_MODULES:
                assert node.id not in IO_NAMES, (name, node.id)
        if isinstance(node, ast.Attribute):
            assert node.attr not in FORBIDDEN_ATTRIBUTES, (name, node.attr)
            if name not in IO_MODULES:
                assert node.attr not in IO_ATTRIBUTES, (name, node.attr)
        if isinstance(node, (ast.Global, ast.Nonlocal)):
            raise AssertionError((name, "module state"))
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            assert "://" not in node.value and "C:\\" not in node.value, (name, node.value)


@pytest.mark.parametrize("store,expected", [
    ("identity_store", {"__init__": {"ab", "mkdir"}, "append": {"ab", "write", "fsync"}}),
    ("observation_store", {"__init__": {"ab"}, "append": {"ab", "write", "fsync"}}),
    ("identity_correction_store", {"__init__": {"ab"}, "append": {"ab", "write", "fsync"}}),
    ("semantic_metadata_store", {"__init__": {"ab", "mkdir"}, "append": {"ab", "write", "fsync"}}),
    ("held_observation_store", {"__init__": {"ab", "mkdir"}, "append": {"ab", "write", "fsync"}})])
def test_ba_to_bg_the_store_writes_only_through_append_and_initialize(store: str, expected: dict) -> None:
    tree = ast.parse((PACKAGE_DIR / f"{store}.py").read_text(encoding="utf-8"))
    writers = {}
    for func in (n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)):
        for node in ast.walk(func):
            if isinstance(node, ast.Constant) and node.value in ("ab", "wb", "w", "a", "r+", "w+", "a+"):
                writers.setdefault(func.name, set()).add(node.value)
            if isinstance(node, ast.Attribute) and node.attr in ("write", "mkdir", "fsync", "write_bytes", "unlink"):
                writers.setdefault(func.name, set()).add(node.attr)
    assert writers == expected
    assert "sqlite" not in executable_source(PACKAGE_DIR / f"{store}.py").lower()


# ================================================================ BH〜BJ screen ・score ・Theme なし


SCREENING_WORDS = ("screen", "criterion", "criteria", "candidate_result", "rank", "score", "rating", "filter",
                   "recommend", "attractive", "target_price", "expected_return", "weight", "buy", "sell", "watchlist",
                   "portfolio", "thesis", "theme", "exposure", "beneficiar", "narrative", "forecast", "price", "fundamental")


@pytest.mark.parametrize("name,path", [(n, p) for n, p in _sources() if n in A1_MODULES + A1R_MODULES])
def test_bh_bi_bj_no_screening_score_rank_or_theme_types(name: str, path: Path) -> None:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    defined = {node.name.lower() for node in ast.walk(tree) if isinstance(node, (ast.FunctionDef, ast.ClassDef))}
    targets = {t.id.lower() for node in ast.walk(tree) if isinstance(node, ast.Assign) for t in node.targets
               if isinstance(t, ast.Name)}
    for word in SCREENING_WORDS:
        assert not any(word in item for item in defined | targets), (name, word)
    source = executable_source(path).lower()
    for token in ("score", "rank", "screening", "recommend", "theme", "exposure", "watchlist", "llm", "prompt"):
        assert token not in source, (name, token)


def test_bh_bi_bj_the_vocabulary_has_no_evaluative_member() -> None:
    from src.intelligence.screener_intelligence import identity_model as m
    from src.intelligence.screener_intelligence import identity_resolver as r
    members = {member.value for enum in (m.RecordKind, m.SourceClass, m.IssueClass, m.IdentifierScheme,
                                         m.RetirementReason, m.SubjectKind, m.NameKind, m.NameLanguage,
                                         m.ListingVenue, m.ListingEndReason, m.CoverageScope, r.ResolutionStatus,
                                         r.QueryKind) for member in enum}
    for word in ("RANK", "SCORE", "BUY", "SELL", "TOP", "BEST", "CANDIDATE", "PASS", "FAIL", "THEME", "EXPOSURE"):
        assert not any(word in value for value in members), word
    resolution_fields = set(r.IdentityResolution.__dataclass_fields__)
    assert not resolution_fields & {"score", "rank", "weight", "recommendation", "record_id"}


# ================================================================ BK〜BL 凍結


def test_bk_phase7_runtime_and_documents_are_byte_identical_to_the_final_anchor() -> None:
    assert subprocess.run(["git", "merge-base", "--is-ancestor", PHASE7_FINAL, "HEAD"], cwd=REPO_ROOT).returncode == 0
    for path in (*PHASE7_RUNTIME, *PHASE7_DOCS):
        assert _git("show", f"{PHASE7_FINAL}:{path}") == (REPO_ROOT / path).read_text(encoding="utf-8"), path
    assert _git("status", "--porcelain", "--", *PHASE7_RUNTIME, *PHASE7_DOCS) == ""


def test_bk_phase7_tests_changed_only_by_the_declared_phase8_registration() -> None:
    assert subprocess.run(["git", "merge-base", "--is-ancestor", P8_A0, "HEAD"], cwd=REPO_ROOT).returncode == 0
    changed = {tuple(line.split("\t")) for line in _git("diff", "--name-status", P8_A0, "--", "tests").splitlines()}
    assert changed <= {("M", path) for path in PHASE7_TEST_REGISTRATION} | {("A", path) for path in PHASE8_TESTS}
    for path in PHASE7_TEST_REGISTRATION:
        anchored = _git("show", f"{P8_A0}:{path}")
        current = (REPO_ROOT / path).read_text(encoding="utf-8")
        assert only_phase8_registration(path, anchored, current), path
        assert not only_phase8_registration(path, anchored, current + "assert True\n")        # 未登録の追加
        assert not only_phase8_registration(path, anchored, anchored)                           # 登録の欠落
    untouched = "tests/intelligence/test_narrative_phase7_e2e.py"
    text = (REPO_ROOT / untouched).read_text(encoding="utf-8")
    assert only_phase8_registration(untouched, text, text)
    assert not only_phase8_registration(untouched, text, text + "\n# edit\n")


def test_bl_phase6_runtime_knowledge_and_tests_are_frozen() -> None:
    namespaces = ("src/intelligence/themes", "src/intelligence/theme_intelligence", "knowledge")
    assert _git("diff", "--name-status", PHASE6_COMPLETION, "--", *namespaces) == ""
    phase6_tests = sorted(PHASE6_TEST_REGISTRATION)
    assert _git("diff", "--name-status", P8_A0, "--", *phase6_tests) == ""                     # Phase 6 の test を触らない


def test_bl_the_runtime_surface_since_a0_is_exactly_the_registered_phase8_runtime() -> None:
    changes = {tuple(line.split("\t")) for line in _git("diff", "--cached", "--name-status", P8_A0, "--",
                                                        *SURFACE).splitlines()}
    assert changes == {("A", path) for path in PHASE8_RUNTIME}
    pending = [line for line in _git("status", "--porcelain", "--", *(p for p in SURFACE if p != "data")).splitlines()
               if not is_phase8_addition(line[:2].strip(), line[3:])]
    assert pending == []
    docs = {tuple(line.split("\t")) for line in _git("diff", "--name-status", P8_A0, "--", "docs").splitlines()}
    assert docs <= {("A", A1_DOC), ("A", A2_DOC), ("A", A2_5_DOC), ("A", V_DOC), ("A", VR_DOC), ("A", A1R_DOC),
                    ("A", LV1_DOC), ("A", PILOT1_DOC),
                    ("A", A2R_DOC), ("A", A2RV_DOC), ("A", A2RI_DOC), ("A", A3A_DOC), ("A", A3B_DOC), ("A", A3R_DOC),
                    ("A", ST1_DOC), ("A", ADP0_DOC), ("A", EXE_DOC), ("A", ID1_DOC),
                    ("A", ID2_DOC), ("A", LIVE0_DOC)}


# ================================================================ BM〜BO registry ・未登録 ・外からの import


def test_bm_the_phase8_registry_is_exact() -> None:
    assert tuple(sorted(stem for stem, _ in _sources())) == MODULES
    assert PHASE8_RUNTIME == tuple(f"{PHASE8_PACKAGE}/{name}.py" for name in MODULES)
    assert {p.name for p in PACKAGE_DIR.iterdir() if p.name != "__pycache__"} == {f"{n}.py" for n in MODULES}
    assert ADDITION_STATUSES == ("A", "??")
    for path in (*PHASE8_TESTS, *PHASE8_DOCS):
        assert (REPO_ROOT / path).is_file(), path
    assert {A1_DOC, A2_DOC, A2_5_DOC, V_DOC, VR_DOC, A1R_DOC, LV1_DOC, PILOT1_DOC, A2R_DOC,
            A2RV_DOC, A2RI_DOC, A3A_DOC, A3B_DOC, A3R_DOC, ST1_DOC, ADP0_DOC, EXE_DOC, ID1_DOC,
            ID2_DOC, LIVE0_DOC} <= set(PHASE8_DOCS)
    assert PHASE8_A1R_RUNTIME == tuple(f"{PHASE8_PACKAGE}/{name}.py" for name in A1R_MODULES)
    assert PHASE8_A2R_RUNTIME == tuple(f"{PHASE8_PACKAGE}/{name}.py" for name in A2R_MODULES)
    assert PHASE8_A3A_RUNTIME == tuple(f"{PHASE8_PACKAGE}/{name}.py" for name in A3A_MODULES)
    assert PHASE8_A3B_RUNTIME == tuple(f"{PHASE8_PACKAGE}/{name}.py" for name in A3B_MODULES)
    assert PHASE8_ST1_RUNTIME == tuple(f"{PHASE8_PACKAGE}/{name}.py" for name in ST1_MODULES)
    assert PHASE8_ADP0_RUNTIME == tuple(f"{PHASE8_PACKAGE}/{name}.py" for name in ADP0_MODULES)
    assert PHASE8_EXE_RUNTIME == tuple(f"{PHASE8_PACKAGE}/{name}.py" for name in EXE_MODULES)
    assert PHASE8_ID1_RUNTIME == tuple(f"{PHASE8_PACKAGE}/{name}.py" for name in ID1_MODULES)
    assert PHASE8_ID2_RUNTIME == tuple(f"{PHASE8_PACKAGE}/{name}.py" for name in ID2_MODULES)
    assert set(PHASE8_RUNTIME) == set(PHASE8_A2_RUNTIME) | set(PHASE8_A1R_RUNTIME) | set(PHASE8_A2R_RUNTIME) | set(
        PHASE8_A3A_RUNTIME) | set(PHASE8_A3B_RUNTIME) | set(PHASE8_ST1_RUNTIME) | set(PHASE8_ADP0_RUNTIME) | set(
        PHASE8_EXE_RUNTIME) | set(PHASE8_ID1_RUNTIME) | set(PHASE8_ID2_RUNTIME)
    assert {A2R_TEST, A3A_TEST, A3B_TEST, ST1_TEST, ADP0_TEST, EXE_TEST, ID1_TEST, ID2_TEST} <= set(PHASE8_TESTS)
    assert PHASE8_A1_RUNTIME == tuple(f"{PHASE8_PACKAGE}/{name}.py" for name in A1_MODULES)
    assert PHASE8_A2_RUNTIME == tuple(f"{PHASE8_PACKAGE}/{name}.py" for name in sorted((*A1_MODULES, *A2_MODULES)))
    assert set(PHASE7_TEST_REGISTRATION) == {"tests/intelligence/phase7_runtime_registry.py",
                                             "tests/intelligence/test_narrative_intelligence_boundary.py"}
    assert not any(p.startswith(("src/intelligence/themes", "src/intelligence/theme_intelligence",
                                 "src/intelligence/narrative_intelligence", "knowledge")) for p in PHASE8_RUNTIME)


def test_bn_an_unregistered_phase8_runtime_is_rejected_by_every_registry_check(tmp_path: Path) -> None:
    fake = f"{PHASE8_PACKAGE}/screen_engine.py"
    for status in ("A", "??"):
        assert not is_phase8_addition(status, fake) and not is_phase7_addition(status, fake)
    assert f":(exclude,literal){fake}" not in PHASE7_EXCLUDED_PATHSPECS
    for path in PHASE8_RUNTIME:
        assert is_phase8_addition("A", path) and is_phase7_addition("??", path)
        assert f":(exclude,literal){path}" in PHASE7_EXCLUDED_PATHSPECS
        for status in ("M", "D", "R", "R100", "C", "T", "U"):
            assert not is_phase8_addition(status, path) and not is_phase7_addition(status, path), status
    for near_miss in (PHASE8_PACKAGE, f"{PHASE8_PACKAGE}/", f"{PHASE8_PACKAGE}/sub/identity_model.py",
                      "src/intelligence/screening/identity_model.py", f"{PHASE8_PACKAGE}/identity_model.pyc"):
        assert not is_phase8_addition("A", near_miss) and not is_phase7_addition("A", near_miss), near_miss
    package = tmp_path / PHASE8_PACKAGE
    package.mkdir(parents=True)
    for _, path in _sources():
        (package / path.name).write_bytes(path.read_bytes())
    (package / "screen_engine.py").write_text('"""not registered."""\n', encoding="utf-8")
    unregistered = sorted(p.relative_to(tmp_path).as_posix() for p in package.glob("*.py")
                          if not is_phase8_addition("A", p.relative_to(tmp_path).as_posix()))
    assert unregistered == [fake]


def test_bo_no_other_package_imports_phase8() -> None:
    offenders = []
    for path in [REPO_ROOT / "main.py", *sorted((REPO_ROOT / "src").rglob("*.py")),
                 *sorted((REPO_ROOT / "scripts").rglob("*.py"))]:
        if not path.exists() or PACKAGE_DIR in path.parents:
            continue
        if "screener_intelligence" in path.read_text(encoding="utf-8", errors="replace"):
            offenders.append(str(path.relative_to(REPO_ROOT)))
    assert offenders == []
    closure = runtime_closure()
    assert closure and not any("screener_intelligence" in module for module in closure)


# ================================================================ P8-A2（BY〜CL）


def test_a2_by_the_a1_runtime_is_byte_identical_to_the_a1_anchor() -> None:
    assert subprocess.run(["git", "merge-base", "--is-ancestor", P8_A1, "HEAD"], cwd=REPO_ROOT).returncode == 0
    for path in PHASE8_A1_RUNTIME:
        assert _git("show", f"{P8_A1}:{path}") == (REPO_ROOT / path).read_text(encoding="utf-8"), path
    assert _git("diff", "--name-status", P8_A1, "--", *PHASE8_A1_RUNTIME, A1_DOC) == ""
    assert _git("status", "--porcelain", "--", *PHASE8_A1_RUNTIME) == ""


def _from_imports(path: Path) -> dict:
    found: dict = {}
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.ImportFrom) and node.module and node.level:
            found.setdefault("." * node.level + node.module, set()).update(alias.name for alias in node.names)
    return found


@pytest.mark.parametrize("name", A2_MODULES)
def test_a2_cc_to_ch_only_the_designated_modules_use_exactly_the_sanctioned_a1_names(name: str) -> None:
    imports = _from_imports(PACKAGE_DIR / f"{name}.py")
    a1_imports = {module: names for module, names in imports.items() if module.startswith(".identity_")}
    assert a1_imports == SANCTIONED_A1_IMPORTS[name]
    for module in A1_MODULES:                                                         # A1 は A2 を知らない
        if module != "__init__":
            assert not any(m.startswith(".observation_") for m in _from_imports(PACKAGE_DIR / f"{module}.py"))


DERIVED_TOKENS = {"roe", "roa", "pbr", "yield", "dividend", "volatility", "return", "returns", "growth", "margin",
                  "ttm", "trailing", "annualized", "ratio", "average", "moving", "indicator", "split", "screen",
                  "criterion", "criteria", "candidate", "rank", "score", "rating", "recommend", "recommendation",
                  "buy", "sell", "theme", "exposure", "narrative", "watchlist", "portfolio", "latest", "current", "now",
                  "llm", "prompt"}


def _words(identifier: str) -> set:
    """識別子を語に分ける（snake_case と CamelCase）。部分一致ではなく語で調べる。"""
    spaced = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", "_", identifier)
    return {word for word in spaced.lower().split("_") if word}


DERIVED_MEMBERS = {"PER", "PBR", "ROE", "ROA", "MARKET_CAP", "TTM", "ANNUALIZED", "GROWTH", "MARGIN", "RETURN",
                   "VOLATILITY", "YIELD", "DIVIDEND", "SCORE", "RANK", "BUY", "SELL", "LATEST", "CURRENT"}


@pytest.mark.parametrize("name", A2_MODULES)
def test_a2_ci_to_cl_no_derived_metric_screening_ranking_theme_or_latest_names(name: str) -> None:
    tree = ast.parse((PACKAGE_DIR / f"{name}.py").read_text(encoding="utf-8"))
    defined = {node.name for node in ast.walk(tree) if isinstance(node, (ast.FunctionDef, ast.ClassDef))}
    targets = {t.id for node in ast.walk(tree) if isinstance(node, (ast.Assign, ast.AnnAssign))
               for t in (node.targets if isinstance(node, ast.Assign) else [node.target]) if isinstance(t, ast.Name)}
    words = set().union(*(_words(item) for item in defined | targets))
    assert not words & DERIVED_TOKENS, (name, words & DERIVED_TOKENS)
    constants = {node.value for node in ast.walk(tree) if isinstance(node, ast.Constant) and isinstance(node.value, str)}
    assert not constants & DERIVED_MEMBERS, constants & DERIVED_MEMBERS
    for clock in ("15:30", "06:30", "15:00", "09:00"):                              # 既定の公表時刻を持たない
        assert clock not in (PACKAGE_DIR / f"{name}.py").read_text(encoding="utf-8"), clock


def test_a2_ci_to_cl_the_observation_vocabulary_has_no_derived_or_evaluative_member() -> None:
    from src.intelligence.screener_intelligence import observation_model as om
    from src.intelligence.screener_intelligence import observation_resolver as orr
    members = {member.value for enum in (om.ObservationClass, om.RecordKind, om.MarketField, om.FundamentalField,
                                         om.PriceBasis, om.StatementBasis, om.PeriodBasis, om.KnowledgePrecision,
                                         om.ValueState, om.Measure, om.Currency, om.Scale, om.CoverageDataset,
                                         orr.ObservationStatus) for member in enum}
    assert not members & DERIVED_MEMBERS
    for word in ("TTM", "TRAILING", "ANNUAL", "ADJUSTMENT_FACTOR", "RATIO", "SCORE", "RANK"):
        assert not any(word in value for value in members), word
    assert set(om.PeriodBasis) == {om.PeriodBasis.FISCAL_YEAR, om.PeriodBasis.SINGLE_QUARTER,
                                   om.PeriodBasis.CUMULATIVE_YEAR_TO_DATE}
    fields = set(orr.ObservationResolution.__dataclass_fields__)
    assert not fields & {"score", "rank", "weight", "recommendation", "record_id", "metric"}


# ================================================================ P8-A2.5（A2 の凍結）


def test_a2_5_the_a1_a2_runtime_and_the_a2_contract_are_byte_identical_to_the_a2_anchor() -> None:
    assert subprocess.run(["git", "merge-base", "--is-ancestor", P8_A2, "HEAD"], cwd=REPO_ROOT).returncode == 0
    for path in (*PHASE8_A2_RUNTIME, A2_DOC):
        assert _git("show", f"{P8_A2}:{path}") == (REPO_ROOT / path).read_text(encoding="utf-8"), path
    assert _git("diff", "--name-status", P8_A2, "--", *PHASE8_A2_RUNTIME, A1_DOC, A2_DOC) == ""
    assert _git("status", "--porcelain", "--", *PHASE8_A2_RUNTIME, A1_DOC, A2_DOC) == ""


# ================================================================ P8-V（A2.5 の凍結）


def test_v_the_runtime_and_the_a2_5_audit_are_byte_identical_to_the_a2_5_anchor() -> None:
    assert subprocess.run(["git", "merge-base", "--is-ancestor", P8_A2_5, "HEAD"], cwd=REPO_ROOT).returncode == 0
    for path in (*PHASE8_A2_RUNTIME, A2_5_DOC):
        assert _git("show", f"{P8_A2_5}:{path}") == (REPO_ROOT / path).read_text(encoding="utf-8"), path
    assert _git("diff", "--name-status", P8_A2_5, "--", *PHASE8_A2_RUNTIME, A1_DOC, A2_DOC, A2_5_DOC) == ""
    assert _git("status", "--porcelain", "--", *PHASE8_A2_RUNTIME, A2_5_DOC) == ""


# ================================================================ P8-VR（P8-V の凍結）


def test_vr_the_runtime_and_the_a2_5_and_v_records_are_byte_identical_to_the_v_anchor() -> None:
    assert subprocess.run(["git", "merge-base", "--is-ancestor", P8_V, "HEAD"], cwd=REPO_ROOT).returncode == 0
    for path in (*PHASE8_A2_RUNTIME, A2_5_DOC, V_DOC):
        assert _git("show", f"{P8_V}:{path}") == (REPO_ROOT / path).read_text(encoding="utf-8"), path
    assert _git("diff", "--name-status", P8_V, "--", *PHASE8_A2_RUNTIME, A1_DOC, A2_DOC, A2_5_DOC, V_DOC) == ""
    assert _git("status", "--porcelain", "--", *PHASE8_A2_RUNTIME, A2_5_DOC, V_DOC) == ""


# ================================================================ P8-A1R（訂正 ・2 軸の解決の境界 ／ 凍結）


def test_a1r_az_bs_a1_a2_runtime_and_prior_phase8_documents_are_byte_identical_to_the_vr_anchor() -> None:
    assert subprocess.run(["git", "merge-base", "--is-ancestor", P8_VR, "HEAD"], cwd=REPO_ROOT).returncode == 0
    prior_docs = (A1_DOC, A2_DOC, A2_5_DOC, V_DOC, VR_DOC)
    for path in (*PHASE8_A2_RUNTIME, *prior_docs):
        assert _git("show", f"{P8_VR}:{path}") == (REPO_ROOT / path).read_text(encoding="utf-8"), path
    assert _git("diff", "--name-status", P8_VR, "--", *PHASE8_A2_RUNTIME, *prior_docs) == ""
    assert _git("status", "--porcelain", "--", *PHASE8_A2_RUNTIME, *prior_docs) == ""


@pytest.mark.parametrize("name", A1R_MODULES)
def test_a1r_the_remediation_modules_use_exactly_the_sanctioned_a1_names_and_never_a2(name: str) -> None:
    imports = _from_imports(PACKAGE_DIR / f"{name}.py")
    a1_imports = {module: names for module, names in imports.items()
                  if module in (".identity_model", ".identity_store", ".identity_resolver")}
    assert a1_imports == SANCTIONED_A1R_IMPORTS[name]
    assert not any(module.startswith(".observation_") for module in imports)             # A2 を使わない
    for module in (*A1_MODULES, *A2_MODULES):                                             # A1 ／ A2 は A1R を知らない
        if module != "__init__":
            used = _from_imports(PACKAGE_DIR / f"{module}.py")
            assert not any(m in (".identity_correction_model", ".identity_correction_store",
                                 ".identity_remediation_resolver") for m in used), module


@pytest.mark.parametrize("name", A1R_MODULES)
def test_a1r_bk_bl_no_derived_metric_screening_ranking_theme_or_latest_names(name: str) -> None:
    tree = ast.parse((PACKAGE_DIR / f"{name}.py").read_text(encoding="utf-8"))
    defined = {node.name for node in ast.walk(tree) if isinstance(node, (ast.FunctionDef, ast.ClassDef))}
    targets = {t.id for node in ast.walk(tree) if isinstance(node, (ast.Assign, ast.AnnAssign))
               for t in (node.targets if isinstance(node, ast.Assign) else [node.target]) if isinstance(t, ast.Name)}
    words = set().union(*(_words(item) for item in defined | targets))
    assert not words & DERIVED_TOKENS, (name, words & DERIVED_TOKENS)
    constants = {node.value for node in ast.walk(tree) if isinstance(node, ast.Constant) and isinstance(node.value, str)}
    assert not constants & DERIVED_MEMBERS, constants & DERIVED_MEMBERS


def test_a1r_the_remediation_vocabulary_has_no_evaluative_merge_or_split_member() -> None:
    from src.intelligence.screener_intelligence import identity_correction_model as cm
    from src.intelligence.screener_intelligence import identity_remediation_resolver as rr
    members = {member.value for enum in (cm.CorrectionAction, cm.CorrectionReason, cm.ReviewerClass,
                                         rr.ResolutionMode, rr.RemediationStatus) for member in enum}
    for word in ("RANK", "SCORE", "BUY", "SELL", "TOP", "BEST", "CANDIDATE", "THEME", "EXPOSURE", "LATEST", "MERGE",
                 "SPLIT", "SPIN"):
        assert not any(word in value for value in members), word
    assert set(cm.CorrectionAction) == {cm.CorrectionAction.INVALIDATE_RECORD, cm.CorrectionAction.SUPERSEDE_RECORD}
    assert set(rr.ResolutionMode) == {rr.ResolutionMode.STRICT_KNOWLEDGE, rr.ResolutionMode.RETROSPECTIVE_AUTHORITY}


# ================================================================ P8-LV1（A1R の凍結）


def test_lv1_the_runtime_phase8_tests_and_prior_documents_are_byte_identical_to_the_a1r_anchor() -> None:
    assert subprocess.run(["git", "merge-base", "--is-ancestor", P8_A1R, "HEAD"], cwd=REPO_ROOT).returncode == 0
    frozen_tests = tuple(path for path in PHASE8_TESTS if path not in (
        "tests/intelligence/phase8_runtime_registry.py", "tests/intelligence/test_screener_intelligence_boundary.py",
        *LATER_TESTS))
    prior_docs = tuple(path for path in PHASE8_DOCS
                       if path not in (LV1_DOC, PILOT1_DOC, A2R_DOC, A2RV_DOC, A2RI_DOC, A3A_DOC, A3B_DOC, A3R_DOC,
                                       ST1_DOC, ADP0_DOC, EXE_DOC, ID1_DOC, ID2_DOC, LIVE0_DOC))
    assert len(frozen_tests) == 3 and len(prior_docs) == 7
    for path in (*PRE_A2R_RUNTIME, *frozen_tests, *prior_docs):
        assert _git("show", f"{P8_A1R}:{path}") == (REPO_ROOT / path).read_text(encoding="utf-8"), path
    assert _git("diff", "--name-status", P8_A1R, "--", *PRE_A2R_RUNTIME, *frozen_tests, *prior_docs) == ""
    assert _git("status", "--porcelain", "--", *PRE_A2R_RUNTIME, *frozen_tests, *prior_docs) == ""


# ================================================================ P8-PILOT1（LV1 の凍結）


def test_pilot1_the_runtime_phase8_tests_and_prior_documents_are_byte_identical_to_the_lv1_anchor() -> None:
    assert subprocess.run(["git", "merge-base", "--is-ancestor", P8_LV1, "HEAD"], cwd=REPO_ROOT).returncode == 0
    frozen_tests = tuple(path for path in PHASE8_TESTS if path not in (
        "tests/intelligence/phase8_runtime_registry.py", "tests/intelligence/test_screener_intelligence_boundary.py",
        *LATER_TESTS))
    prior_docs = tuple(path for path in PHASE8_DOCS
                       if path not in (PILOT1_DOC, A2R_DOC, A2RV_DOC, A2RI_DOC, A3A_DOC, A3B_DOC, A3R_DOC, ST1_DOC,
                                       ADP0_DOC, EXE_DOC, ID1_DOC, ID2_DOC, LIVE0_DOC))
    assert len(frozen_tests) == 3 and len(prior_docs) == 8 and LV1_DOC in prior_docs
    for path in (*PRE_A2R_RUNTIME, *frozen_tests, *prior_docs):
        assert _git("show", f"{P8_LV1}:{path}") == (REPO_ROOT / path).read_text(encoding="utf-8"), path
    assert _git("diff", "--name-status", P8_LV1, "--", *PRE_A2R_RUNTIME, *frozen_tests, *prior_docs) == ""
    assert _git("status", "--porcelain", "--", *PRE_A2R_RUNTIME, *frozen_tests, *prior_docs) == ""


# ================================================================ P8-A2R（PILOT1 の凍結）


def test_a2r_the_runtime_phase8_tests_and_prior_documents_are_byte_identical_to_the_pilot1_anchor() -> None:
    assert subprocess.run(["git", "merge-base", "--is-ancestor", P8_PILOT1, "HEAD"], cwd=REPO_ROOT).returncode == 0
    frozen_tests = tuple(path for path in PHASE8_TESTS if path not in (
        "tests/intelligence/phase8_runtime_registry.py", "tests/intelligence/test_screener_intelligence_boundary.py",
        *LATER_TESTS))
    prior_docs = tuple(path for path in PHASE8_DOCS
                       if path not in (A2R_DOC, A2RV_DOC, A2RI_DOC, A3A_DOC, A3B_DOC, A3R_DOC, ST1_DOC, ADP0_DOC,
                                       EXE_DOC, ID1_DOC, ID2_DOC, LIVE0_DOC))
    assert len(frozen_tests) == 3 and len(prior_docs) == 9 and PILOT1_DOC in prior_docs
    for path in (*PRE_A2R_RUNTIME, *frozen_tests, *prior_docs):
        assert _git("show", f"{P8_PILOT1}:{path}") == (REPO_ROOT / path).read_text(encoding="utf-8"), path
    assert _git("diff", "--name-status", P8_PILOT1, "--", *PRE_A2R_RUNTIME, *frozen_tests, *prior_docs) == ""
    assert _git("status", "--porcelain", "--", *PRE_A2R_RUNTIME, *frozen_tests, *prior_docs) == ""


# ================================================================ P8-A2R の再実行（A2R の凍結）


def test_a2rv_the_runtime_phase8_tests_and_prior_documents_are_byte_identical_to_the_a2r_anchor() -> None:
    assert subprocess.run(["git", "merge-base", "--is-ancestor", P8_A2R, "HEAD"], cwd=REPO_ROOT).returncode == 0
    frozen_tests = tuple(path for path in PHASE8_TESTS if path not in (
        "tests/intelligence/phase8_runtime_registry.py", "tests/intelligence/test_screener_intelligence_boundary.py",
        *LATER_TESTS))
    prior_docs = tuple(path for path in PHASE8_DOCS
                       if path not in (A2RV_DOC, A2RI_DOC, A3A_DOC, A3B_DOC, A3R_DOC, ST1_DOC, ADP0_DOC, EXE_DOC,
                                       ID1_DOC, ID2_DOC, LIVE0_DOC))
    assert len(frozen_tests) == 3 and len(prior_docs) == 10 and {PILOT1_DOC, A2R_DOC} <= set(prior_docs)
    for path in (*PRE_A2R_RUNTIME, *frozen_tests, *prior_docs):
        assert _git("show", f"{P8_A2R}:{path}") == (REPO_ROOT / path).read_text(encoding="utf-8"), path
    assert _git("diff", "--name-status", P8_A2R, "--", *PRE_A2R_RUNTIME, *frozen_tests, *prior_docs) == ""
    assert _git("status", "--porcelain", "--", *PRE_A2R_RUNTIME, *frozen_tests, *prior_docs) == ""


# ================================================================ P8-A2R-IMPL（A2RV の凍結 ・A2R の safety layer の境界）


def test_a2ri_the_pre_a2r_runtime_phase8_tests_and_prior_documents_are_byte_identical_to_the_a2rv_anchor() -> None:
    assert subprocess.run(["git", "merge-base", "--is-ancestor", P8_A2RV, "HEAD"], cwd=REPO_ROOT).returncode == 0
    frozen_tests = tuple(path for path in PHASE8_TESTS if path not in (
        "tests/intelligence/phase8_runtime_registry.py", "tests/intelligence/test_screener_intelligence_boundary.py",
        *LATER_TESTS))
    prior_docs = tuple(path for path in PHASE8_DOCS if path not in (A2RI_DOC, A3A_DOC, A3B_DOC, A3R_DOC, ST1_DOC,
                                                                    ADP0_DOC, EXE_DOC, ID1_DOC, ID2_DOC, LIVE0_DOC))
    assert len(PRE_A2R_RUNTIME) == 10 and len(frozen_tests) == 3 and len(prior_docs) == 11
    assert A2RV_DOC in prior_docs and A2R_DOC in prior_docs and PILOT1_DOC in prior_docs
    for path in (*PRE_A2R_RUNTIME, *frozen_tests, *prior_docs):
        assert _git("show", f"{P8_A2RV}:{path}") == (REPO_ROOT / path).read_text(encoding="utf-8"), path
    assert _git("diff", "--name-status", P8_A2RV, "--", *PRE_A2R_RUNTIME, *frozen_tests, *prior_docs) == ""
    assert _git("status", "--porcelain", "--", *PRE_A2R_RUNTIME, *frozen_tests, *prior_docs) == ""
    assert not any(_git("ls-tree", P8_A2RV, "--", path).strip() for path in (*PHASE8_A2R_RUNTIME, A2R_TEST, A2RI_DOC))


# ================================================================ P8-A3A（A2R-IMPL の凍結 ・指標の層の境界）


def test_a3a_the_pre_a3a_runtime_phase8_tests_and_prior_documents_are_byte_identical_to_the_a2ri_anchor() -> None:
    assert subprocess.run(["git", "merge-base", "--is-ancestor", P8_A2RI, "HEAD"], cwd=REPO_ROOT).returncode == 0
    frozen_tests = tuple(path for path in PHASE8_TESTS if path not in (
        "tests/intelligence/phase8_runtime_registry.py", "tests/intelligence/test_screener_intelligence_boundary.py",
        A3A_TEST, A3B_TEST, ST1_TEST, ADP0_TEST, EXE_TEST, ID1_TEST, ID2_TEST))
    prior_docs = tuple(path for path in PHASE8_DOCS if path not in (A3A_DOC, A3B_DOC, A3R_DOC, ST1_DOC, ADP0_DOC,
                                                                    EXE_DOC, ID1_DOC, ID2_DOC, LIVE0_DOC))
    assert len(PRE_A3A_RUNTIME) == 13 and len(frozen_tests) == 4 and len(prior_docs) == 12
    assert A2R_TEST in frozen_tests and A2RI_DOC in prior_docs
    for path in (*PRE_A3A_RUNTIME, *frozen_tests, *prior_docs):
        assert _git("show", f"{P8_A2RI}:{path}") == (REPO_ROOT / path).read_text(encoding="utf-8"), path
    assert _git("diff", "--name-status", P8_A2RI, "--", *PRE_A3A_RUNTIME, *frozen_tests, *prior_docs) == ""
    assert _git("status", "--porcelain", "--", *PRE_A3A_RUNTIME, *frozen_tests, *prior_docs) == ""
    assert not any(_git("ls-tree", P8_A2RI, "--", path).strip() for path in (*PHASE8_A3A_RUNTIME, A3A_TEST, A3A_DOC))


@pytest.mark.parametrize("name", A3A_MODULES)
def test_a3a_the_metric_modules_use_exactly_the_sanctioned_names_and_no_store_or_a1r(name: str) -> None:
    imports = _from_imports(PACKAGE_DIR / f"{name}.py")
    sanctioned = {module: names for module, names in imports.items()
                  if module in (".identity_model", ".observation_model", ".observation_resolver",
                                ".observation_semantics_gate", ".observation_semantics_model")}
    assert sanctioned == SANCTIONED_A3A_IMPORTS[name]
    assert not any(module in (".identity_store", ".identity_resolver", ".observation_store",
                              ".identity_correction_model", ".identity_correction_store",
                              ".identity_remediation_resolver", ".observation_semantics_mapping")
                   for module in imports)
    for module in (*A1_MODULES, *A2_MODULES, *A1R_MODULES, *A2R_MODULES):            # 先行の層は A3A を知らない
        if module != "__init__":
            used = _from_imports(PACKAGE_DIR / f"{module}.py")
            assert not any(m in (".metric_model", ".fundamental_metrics") for m in used), module


@pytest.mark.parametrize("name", A3A_MODULES + A3B_MODULES)
def test_a3a_no_screening_ranking_scoring_recommendation_theme_or_latest_names(name: str) -> None:
    tree = ast.parse((PACKAGE_DIR / f"{name}.py").read_text(encoding="utf-8"))
    defined = {node.name for node in ast.walk(tree) if isinstance(node, (ast.FunctionDef, ast.ClassDef))}
    targets = {t.id for node in ast.walk(tree) if isinstance(node, (ast.Assign, ast.AnnAssign))
               for t in (node.targets if isinstance(node, ast.Assign) else [node.target]) if isinstance(t, ast.Name)}
    words = set().union(*(_words(item) for item in defined | targets))
    forbidden = DERIVED_TOKENS - {"growth", "margin", "ratio", "roa"}                   # 指標の名前そのものは許す
    assert not words & forbidden, (name, words & forbidden)
    constants = {node.value for node in ast.walk(tree)
                 if isinstance(node, ast.Constant) and isinstance(node.value, str)}
    assert not constants & (DERIVED_MEMBERS - {"GROWTH", "MARGIN"})
    assert not constants & {"REVENUE_GROWTH_RANK", "SCORE", "RANK", "BUY", "SELL", "LATEST", "CURRENT", "TTM"}
    for clock in ("15:30", "06:30", "15:00", "09:00"):
        assert clock not in (PACKAGE_DIR / f"{name}.py").read_text(encoding="utf-8"), clock


def test_a3a_the_metric_vocabulary_is_closed_and_has_no_evaluative_member() -> None:
    from src.intelligence.screener_intelligence import metric_model as mmod
    members = {member.value for enum in (mmod.MetricKind, mmod.MetricStatus, mmod.MetricPeriodLabel, mmod.MetricLeg,
                                         mmod.ReasonCode) for member in enum}
    for word in ("RANK", "SCORE", "BUY", "SELL", "TOP", "BEST", "CANDIDATE", "PASS", "THEME", "EXPOSURE", "LATEST",
                 "CURRENT", "TTM", "ANNUAL", "INFER", "DEFAULT", "RECOMMEND"):
        assert not any(word in value for value in members), word
    assert set(mmod.MetricKind) == {mmod.MetricKind.REVENUE_GROWTH, mmod.MetricKind.OPERATING_MARGIN,
                                    mmod.MetricKind.NET_MARGIN, mmod.MetricKind.ROA_POINT_IN_TIME}
    assert not set(mmod.MetricResult.__dataclass_fields__) & {"score", "rank", "weight", "recommendation", "record_id"}


# ================================================================ P8-A3B（A3A の凍結 ・拡張の指標の境界）


def test_a3b_the_pre_a3b_runtime_phase8_tests_and_prior_documents_are_byte_identical_to_the_a3a_anchor() -> None:
    assert subprocess.run(["git", "merge-base", "--is-ancestor", P8_A3A, "HEAD"], cwd=REPO_ROOT).returncode == 0
    frozen_tests = tuple(path for path in PHASE8_TESTS if path not in (
        "tests/intelligence/phase8_runtime_registry.py", "tests/intelligence/test_screener_intelligence_boundary.py",
        A3B_TEST, ST1_TEST, ADP0_TEST, EXE_TEST, ID1_TEST, ID2_TEST))
    prior_docs = tuple(path for path in PHASE8_DOCS if path not in (A3B_DOC, A3R_DOC, ST1_DOC, ADP0_DOC, EXE_DOC,
                                                                    ID1_DOC, ID2_DOC, LIVE0_DOC))
    byte_identical = tuple(path for path in PRE_A3B_RUNTIME if path != METRIC_MODEL)
    assert len(PRE_A3B_RUNTIME) == 15 and len(byte_identical) == 14 and len(frozen_tests) == 5
    assert len(prior_docs) == 13 and A3A_TEST in frozen_tests and A3A_DOC in prior_docs
    for path in (*byte_identical, *frozen_tests, *prior_docs):
        assert _git("show", f"{P8_A3A}:{path}") == (REPO_ROOT / path).read_text(encoding="utf-8"), path
    assert _git("diff", "--name-status", P8_A3A, "--", *byte_identical, *frozen_tests, *prior_docs) == ""
    assert _git("status", "--porcelain", "--", *PRE_A3B_RUNTIME, *frozen_tests, *prior_docs) == ""
    assert not any(_git("ls-tree", P8_A3A, "--", path).strip() for path in (*PHASE8_A3B_RUNTIME, A3B_TEST, A3B_DOC))


def test_a3b_metric_model_differs_from_the_a3a_anchor_only_by_the_declared_enum_members() -> None:
    anchored = _git("show", f"{P8_A3A}:{METRIC_MODEL}")
    removed, added = registration_diff(anchored, (REPO_ROOT / METRIC_MODEL).read_text(encoding="utf-8"))
    declared_removed, declared_added = PHASE8_A3B_METRIC_MODEL_REGISTRATION
    assert (removed, added) == (list(declared_removed), list(declared_added))
    assert len(added) == 4 and all(line.startswith("    ") and " = " in line for line in added)


@pytest.mark.parametrize("name", A3B_MODULES)
def test_a3b_the_extension_reuses_a3a_and_uses_exactly_the_sanctioned_names(name: str) -> None:
    imports = _from_imports(PACKAGE_DIR / f"{name}.py")
    assert imports == SANCTIONED_A3B_IMPORTS[name]
    assert ".fundamental_metrics" in imports                                                # A3A の再利用（競合なし）
    for module in (*A1_MODULES, *A2_MODULES, *A1R_MODULES, *A2R_MODULES, *A3A_MODULES):    # 先行の層は A3B を知らない
        if module != "__init__":
            used = _from_imports(PACKAGE_DIR / f"{module}.py")
            assert ".fundamental_metrics_extended" not in used, module


@pytest.mark.parametrize("name", A2R_MODULES)
def test_a2ri_the_semantics_modules_use_exactly_the_sanctioned_a1_a2_names_and_never_a1r_store_or_resolver(
        name: str) -> None:
    imports = _from_imports(PACKAGE_DIR / f"{name}.py")
    sanctioned = {module: names for module, names in imports.items()
                  if module in (".identity_model", ".observation_model")}
    assert sanctioned == SANCTIONED_A2R_IMPORTS[name]
    assert not any(module in (".identity_store", ".identity_resolver", ".observation_store", ".observation_resolver",
                              ".identity_correction_model", ".identity_correction_store",
                              ".identity_remediation_resolver") for module in imports)
    for module in (*A1_MODULES, *A2_MODULES, *A1R_MODULES):                             # A1 ／ A2 ／ A1R は A2R を知らない
        if module != "__init__":
            used = _from_imports(PACKAGE_DIR / f"{module}.py")
            assert not any(m.startswith(".observation_semantics_") for m in used), module


@pytest.mark.parametrize("name", A2R_MODULES)
def test_a2ri_no_derived_metric_screening_ranking_theme_or_latest_names(name: str) -> None:
    tree = ast.parse((PACKAGE_DIR / f"{name}.py").read_text(encoding="utf-8"))
    defined = {node.name for node in ast.walk(tree) if isinstance(node, (ast.FunctionDef, ast.ClassDef))}
    targets = {t.id for node in ast.walk(tree) if isinstance(node, (ast.Assign, ast.AnnAssign))
               for t in (node.targets if isinstance(node, ast.Assign) else [node.target]) if isinstance(t, ast.Name)}
    words = set().union(*(_words(item) for item in defined | targets))
    assert not words & DERIVED_TOKENS, (name, words & DERIVED_TOKENS)
    constants = {node.value for node in ast.walk(tree)
                 if isinstance(node, ast.Constant) and isinstance(node.value, str)}
    assert not constants & DERIVED_MEMBERS, constants & DERIVED_MEMBERS
    for clock in ("15:30", "06:30", "15:00", "09:00"):
        assert clock not in (PACKAGE_DIR / f"{name}.py").read_text(encoding="utf-8"), clock


def test_a2ri_the_semantics_vocabulary_is_closed_and_has_no_evaluative_member() -> None:
    from src.intelligence.screener_intelligence import observation_semantics_gate as sg
    from src.intelligence.screener_intelligence import observation_semantics_model as sm
    members = {member.value for enum in (sm.AccountingStandard, sm.SemanticState, sm.SemanticStatus,
                                         sm.SemanticEvidence, sm.SchemaFamily, sm.FieldFamily, sm.DocumentKind,
                                         sg.CompatibilityVerdict, sg.CompatibilityReason, sg.AppendEligibility,
                                         sg.HoldReason) for member in enum}
    assert not members & DERIVED_MEMBERS
    for word in ("RANK", "SCORE", "BUY", "SELL", "TOP", "BEST", "CANDIDATE", "PASS", "THEME", "EXPOSURE", "LATEST",
                 "MERGE", "INFER", "GUESS", "DEFAULT"):
        assert not any(word in value for value in members), word
    assert set(sm.AccountingStandard) == {sm.AccountingStandard.JP_GAAP, sm.AccountingStandard.US_GAAP,
                                          sm.AccountingStandard.IFRS, sm.AccountingStandard.JMIS,
                                          sm.AccountingStandard.UNKNOWN}
    assert set(sg.AppendEligibility) == {sg.AppendEligibility.ELIGIBLE, sg.AppendEligibility.HOLD}
    assert not set(sg.AppendPlan.__dataclass_fields__) & {"score", "rank", "weight", "recommendation", "record_id",
                                                          "metric"}


# ================================================================ P8-A3R（A3B の凍結。設計だけの gate）


def test_a3r_all_phase8_runtime_tests_and_prior_documents_are_byte_identical_to_the_a3b_anchor() -> None:
    assert subprocess.run(["git", "merge-base", "--is-ancestor", P8_A3B, "HEAD"], cwd=REPO_ROOT).returncode == 0
    frozen_tests = tuple(path for path in PHASE8_TESTS if path not in (
        "tests/intelligence/phase8_runtime_registry.py", "tests/intelligence/test_screener_intelligence_boundary.py",
        ST1_TEST, ADP0_TEST, EXE_TEST, ID1_TEST, ID2_TEST))
    prior_docs = tuple(path for path in PHASE8_DOCS if path not in (A3R_DOC, ST1_DOC, ADP0_DOC, EXE_DOC, ID1_DOC,
                                                                    ID2_DOC, LIVE0_DOC))
    assert len(PRE_ST1_RUNTIME) == 16 and len(frozen_tests) == 6 and len(prior_docs) == 14
    for path in (*PRE_ST1_RUNTIME, *frozen_tests, *prior_docs):
        assert _git("show", f"{P8_A3B}:{path}") == (REPO_ROOT / path).read_text(encoding="utf-8"), path
    assert _git("diff", "--name-status", P8_A3B, "--", *PRE_ST1_RUNTIME, *frozen_tests, *prior_docs) == ""
    assert _git("status", "--porcelain", "--", *PRE_ST1_RUNTIME, *frozen_tests, *prior_docs) == ""
    assert not _git("ls-tree", P8_A3B, "--", A3R_DOC).strip()


# ================================================================ P8-ST1（A3R の凍結 ・運用 store の境界）


def test_st1_the_pre_st1_runtime_phase8_tests_and_prior_documents_are_byte_identical_to_the_a3r_anchor() -> None:
    assert subprocess.run(["git", "merge-base", "--is-ancestor", P8_A3R, "HEAD"], cwd=REPO_ROOT).returncode == 0
    frozen_tests = tuple(path for path in PHASE8_TESTS if path not in (
        "tests/intelligence/phase8_runtime_registry.py", "tests/intelligence/test_screener_intelligence_boundary.py",
        ST1_TEST, ADP0_TEST, EXE_TEST, ID1_TEST, ID2_TEST))
    prior_docs = tuple(path for path in PHASE8_DOCS if path not in (ST1_DOC, ADP0_DOC, EXE_DOC, ID1_DOC, ID2_DOC, LIVE0_DOC))
    assert len(PRE_ST1_RUNTIME) == 16 and len(frozen_tests) == 6 and len(prior_docs) == 15 and A3R_DOC in prior_docs
    for path in (*PRE_ST1_RUNTIME, *frozen_tests, *prior_docs):
        assert _git("show", f"{P8_A3R}:{path}") == (REPO_ROOT / path).read_text(encoding="utf-8"), path
    assert _git("diff", "--name-status", P8_A3R, "--", *PRE_ST1_RUNTIME, *frozen_tests, *prior_docs) == ""
    assert _git("status", "--porcelain", "--", *PRE_ST1_RUNTIME, *frozen_tests, *prior_docs) == ""
    assert not any(_git("ls-tree", P8_A3R, "--", path).strip() for path in (*PHASE8_ST1_RUNTIME, ST1_TEST, ST1_DOC))


@pytest.mark.parametrize("name", ST1_MODULES)
def test_st1_the_operational_stores_use_exactly_the_sanctioned_names_and_never_a2_a1_stores_or_metrics(
        name: str) -> None:
    imports = _from_imports(PACKAGE_DIR / f"{name}.py")
    sanctioned = {module: names for module, names in imports.items()
                  if module in (".identity_model", ".observation_model", ".observation_semantics_model",
                                ".held_observation_model")}
    assert sanctioned == SANCTIONED_ST1_IMPORTS[name]
    assert not any(module in (".identity_store", ".identity_resolver", ".observation_store", ".observation_resolver",
                              ".identity_correction_model", ".identity_correction_store",
                              ".identity_remediation_resolver", ".observation_semantics_mapping",
                              ".observation_semantics_gate", ".metric_model", ".fundamental_metrics",
                              ".fundamental_metrics_extended") for module in imports), name
    for module in (*A1_MODULES, *A2_MODULES, *A1R_MODULES, *A2R_MODULES, *A3A_MODULES, *A3B_MODULES):
        if module != "__init__":                                                         # 先行の層は ST1 を知らない
            used = _from_imports(PACKAGE_DIR / f"{module}.py")
            assert not any(m in (".semantic_metadata_store", ".held_observation_model", ".held_observation_store")
                           for m in used), module


@pytest.mark.parametrize("name", ST1_MODULES)
def test_st1_no_derived_metric_screening_ranking_theme_or_latest_names(name: str) -> None:
    tree = ast.parse((PACKAGE_DIR / f"{name}.py").read_text(encoding="utf-8"))
    defined = {node.name for node in ast.walk(tree) if isinstance(node, (ast.FunctionDef, ast.ClassDef))}
    targets = {t.id for node in ast.walk(tree) if isinstance(node, (ast.Assign, ast.AnnAssign))
               for t in (node.targets if isinstance(node, ast.Assign) else [node.target]) if isinstance(t, ast.Name)}
    words = set().union(*(_words(item) for item in defined | targets))
    assert not words & DERIVED_TOKENS, (name, words & DERIVED_TOKENS)
    constants = {node.value for node in ast.walk(tree)
                 if isinstance(node, ast.Constant) and isinstance(node.value, str)}
    assert not constants & DERIVED_MEMBERS, constants & DERIVED_MEMBERS
    for clock in ("15:30", "06:30", "15:00", "09:00"):
        assert clock not in (PACKAGE_DIR / f"{name}.py").read_text(encoding="utf-8"), clock


def test_st1_the_held_vocabulary_is_closed_and_has_no_evaluative_member() -> None:
    from src.intelligence.screener_intelligence import held_observation_model as hom
    members = {member.value for member in hom.HeldReason}
    for word in ("RANK", "SCORE", "BUY", "SELL", "TOP", "BEST", "CANDIDATE", "THEME", "EXPOSURE", "LATEST", "SEVERITY",
                 "PRIORITY", "HIGH", "LOW", "RETRY", "PROMOTE"):
        assert not any(word in value for value in members), word
    assert not set(hom.HeldObservation.__dataclass_fields__) & {"raw", "payload", "response_body", "api_response",
                                                                "severity", "priority", "score", "rank", "record_id"}


# ================================================================ P8-ADP0（ST1 の凍結 ・純 adapter の境界）


def test_adp0_the_pre_adp0_runtime_phase8_tests_and_prior_documents_are_byte_identical_to_the_st1_anchor() -> None:
    assert subprocess.run(["git", "merge-base", "--is-ancestor", P8_ST1, "HEAD"], cwd=REPO_ROOT).returncode == 0
    frozen_tests = tuple(path for path in PHASE8_TESTS if path not in (
        "tests/intelligence/phase8_runtime_registry.py", "tests/intelligence/test_screener_intelligence_boundary.py",
        ADP0_TEST, EXE_TEST, ID1_TEST, ID2_TEST))
    prior_docs = tuple(path for path in PHASE8_DOCS if path not in (ADP0_DOC, EXE_DOC, ID1_DOC, ID2_DOC, LIVE0_DOC))
    assert len(PRE_ADP0_RUNTIME) == 19 and len(frozen_tests) == 7 and len(prior_docs) == 16 and ST1_DOC in prior_docs
    for path in (*PRE_ADP0_RUNTIME, *frozen_tests, *prior_docs):
        assert _git("show", f"{P8_ST1}:{path}") == (REPO_ROOT / path).read_text(encoding="utf-8"), path
    assert _git("diff", "--name-status", P8_ST1, "--", *PRE_ADP0_RUNTIME, *frozen_tests, *prior_docs) == ""
    assert _git("status", "--porcelain", "--", *PRE_ADP0_RUNTIME, *frozen_tests, *prior_docs) == ""
    assert not any(_git("ls-tree", P8_ST1, "--", path).strip() for path in (*PHASE8_ADP0_RUNTIME, ADP0_TEST, ADP0_DOC, EXE_DOC, ID1_DOC, ID2_DOC, LIVE0_DOC))


@pytest.mark.parametrize("name", ADP0_MODULES)
def test_adp0_the_adapter_uses_exactly_the_sanctioned_names_and_no_store_resolver_or_metric(name: str) -> None:
    imports = _from_imports(PACKAGE_DIR / f"{name}.py")
    assert imports == SANCTIONED_ADP0_IMPORTS[name]
    for module in (*A1_MODULES, *A2_MODULES, *A1R_MODULES, *A2R_MODULES, *A3A_MODULES, *A3B_MODULES, *ST1_MODULES):
        if module != "__init__":                                            # 先行の層は ADP0 を知らない
            used = _from_imports(PACKAGE_DIR / f"{module}.py")
            assert not any(m in (".jquants_adapter_model", ".jquants_financial_summary_adapter") for m in used), module


@pytest.mark.parametrize("name", ADP0_MODULES)
def test_adp0_no_derived_metric_screening_ranking_theme_or_latest_names(name: str) -> None:
    tree = ast.parse((PACKAGE_DIR / f"{name}.py").read_text(encoding="utf-8"))
    defined = {node.name for node in ast.walk(tree) if isinstance(node, (ast.FunctionDef, ast.ClassDef))}
    targets = {t.id for node in ast.walk(tree) if isinstance(node, (ast.Assign, ast.AnnAssign))
               for t in (node.targets if isinstance(node, ast.Assign) else [node.target]) if isinstance(t, ast.Name)}
    words = set().union(*(_words(item) for item in defined | targets))
    assert not words & DERIVED_TOKENS, (name, words & DERIVED_TOKENS)
    from src.intelligence.screener_intelligence import jquants_adapter_model as jam
    constants = {node.value for node in ast.walk(tree)
                 if isinstance(node, ast.Constant) and isinstance(node.value, str)}
    official = set(jam.OFFICIAL_FINS_SUMMARY_FIELDS)                # 公式の欄名（ROE など）は拒否の一覧で、読まない
    assert not (constants - official) & DERIVED_MEMBERS, (constants - official) & DERIVED_MEMBERS
    assert not set(jam.SUPPORTED_FIELDS) & DERIVED_MEMBERS
    for clock in ("15:30", "06:30", "15:00", "09:00"):
        assert clock not in (PACKAGE_DIR / f"{name}.py").read_text(encoding="utf-8"), clock


def test_adp0_the_adapter_vocabulary_is_closed_and_has_no_evaluative_member() -> None:
    from src.intelligence.screener_intelligence import jquants_adapter_model as jam
    members = {member.value for member in jam.AdapterStatus}
    assert members == {"ELIGIBLE", "HOLD"}
    assert not set(jam.AdapterResult.__dataclass_fields__) & {"raw", "payload", "row", "response_body", "api_response",
                                                              "score", "rank", "record_id"}
    assert not set(jam.FinancialSummaryRow.__dataclass_fields__) - set(jam.SUPPORTED_FIELDS)


# ================================================================ P8-EXE（ADP0 の凍結 ・executor の境界）


def test_exe_the_pre_exe_runtime_phase8_tests_and_prior_documents_are_byte_identical_to_the_adp0_anchor() -> None:
    assert subprocess.run(["git", "merge-base", "--is-ancestor", P8_ADP0, "HEAD"], cwd=REPO_ROOT).returncode == 0
    frozen_tests = tuple(path for path in PHASE8_TESTS if path not in (
        "tests/intelligence/phase8_runtime_registry.py", "tests/intelligence/test_screener_intelligence_boundary.py",
        EXE_TEST, ID1_TEST, ID2_TEST))
    prior_docs = tuple(path for path in PHASE8_DOCS if path not in (EXE_DOC, ID1_DOC, ID2_DOC, LIVE0_DOC))
    assert len(PRE_EXE_RUNTIME) == 21 and len(frozen_tests) == 8 and len(prior_docs) == 17 and ADP0_DOC in prior_docs
    for path in (*PRE_EXE_RUNTIME, *frozen_tests, *prior_docs):
        assert _git("show", f"{P8_ADP0}:{path}") == (REPO_ROOT / path).read_text(encoding="utf-8"), path
    assert _git("diff", "--name-status", P8_ADP0, "--", *PRE_EXE_RUNTIME, *frozen_tests, *prior_docs) == ""
    assert _git("status", "--porcelain", "--", *PRE_EXE_RUNTIME, *frozen_tests, *prior_docs) == ""
    assert not any(_git("ls-tree", P8_ADP0, "--", path).strip() for path in (*PHASE8_EXE_RUNTIME, EXE_TEST, EXE_DOC, ID1_DOC, ID2_DOC, LIVE0_DOC))


@pytest.mark.parametrize("name", EXE_MODULES)
def test_exe_the_executor_uses_exactly_the_sanctioned_names_and_only_the_three_stores(name: str) -> None:
    imports = _from_imports(PACKAGE_DIR / f"{name}.py")
    assert imports == SANCTIONED_EXE_IMPORTS[name]
    assert not any(m in (".identity_store", ".identity_resolver", ".identity_correction_store",
                         ".identity_remediation_resolver", ".observation_resolver", ".metric_model",
                         ".fundamental_metrics", ".fundamental_metrics_extended") for m in imports)
    for module in (*A1_MODULES, *A2_MODULES, *A1R_MODULES, *A2R_MODULES, *A3A_MODULES, *A3B_MODULES, *ST1_MODULES,
                   *ADP0_MODULES):
        if module != "__init__":                                            # 先行の層は EXE を知らない
            used = _from_imports(PACKAGE_DIR / f"{module}.py")
            assert not any(m in (".jquants_execution_model", ".jquants_financial_summary_executor") for m in used), \
                module


@pytest.mark.parametrize("name", EXE_MODULES)
def test_exe_no_derived_metric_screening_ranking_theme_or_latest_names(name: str) -> None:
    tree = ast.parse((PACKAGE_DIR / f"{name}.py").read_text(encoding="utf-8"))
    defined = {node.name for node in ast.walk(tree) if isinstance(node, (ast.FunctionDef, ast.ClassDef))}
    targets = {t.id for node in ast.walk(tree) if isinstance(node, (ast.Assign, ast.AnnAssign))
               for t in (node.targets if isinstance(node, ast.Assign) else [node.target]) if isinstance(t, ast.Name)}
    words = set().union(*(_words(item) for item in defined | targets))
    assert not words & DERIVED_TOKENS, (name, words & DERIVED_TOKENS)
    constants = {node.value for node in ast.walk(tree)
                 if isinstance(node, ast.Constant) and isinstance(node.value, str)}
    assert not constants & DERIVED_MEMBERS, constants & DERIVED_MEMBERS
    for clock in ("15:30", "06:30", "15:00", "09:00"):
        assert clock not in (PACKAGE_DIR / f"{name}.py").read_text(encoding="utf-8"), clock


def test_exe_the_result_vocabulary_is_closed_and_the_executor_does_not_initialize_or_delete() -> None:
    from src.intelligence.screener_intelligence import jquants_execution_model as jxm
    assert {m.value for m in jxm.ExecutionOutcome} == {"APPENDED", "REUSED", "HELD", "REJECTED", "PARTIAL_FAILURE",
                                                       "NO_REPORTED_FIELDS"}
    assert not set(jxm.ExecutionResult.__dataclass_fields__) & {"raw", "payload", "row", "response_body",
                                                                "api_response", "score", "severity", "rank",
                                                                "record_id"}
    tree = ast.parse((PACKAGE_DIR / "jquants_financial_summary_executor.py").read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute):
            assert node.attr not in {"initialize", "unlink", "rename", "replace", "truncate", "write", "mkdir",
                                     "remove"}, node.attr


# ================================================================ P8-ID1（EXE の凍結 ・identity bootstrap の境界）


def test_id1_the_pre_id1_runtime_phase8_tests_and_prior_documents_are_byte_identical_to_the_exe_anchor() -> None:
    assert subprocess.run(["git", "merge-base", "--is-ancestor", P8_EXE, "HEAD"], cwd=REPO_ROOT).returncode == 0
    frozen_tests = tuple(path for path in PHASE8_TESTS if path not in (
        "tests/intelligence/phase8_runtime_registry.py", "tests/intelligence/test_screener_intelligence_boundary.py",
        ID1_TEST, ID2_TEST))
    prior_docs = tuple(path for path in PHASE8_DOCS if path not in (ID1_DOC, ID2_DOC, LIVE0_DOC))
    assert len(PRE_ID1_RUNTIME) == 23 and len(frozen_tests) == 9 and len(prior_docs) == 18 and EXE_DOC in prior_docs
    for path in (*PRE_ID1_RUNTIME, *frozen_tests, *prior_docs):
        assert _git("show", f"{P8_EXE}:{path}") == (REPO_ROOT / path).read_text(encoding="utf-8"), path
    assert _git("diff", "--name-status", P8_EXE, "--", *PRE_ID1_RUNTIME, *frozen_tests, *prior_docs) == ""
    assert _git("status", "--porcelain", "--", *PRE_ID1_RUNTIME, *frozen_tests, *prior_docs) == ""
    assert not any(_git("ls-tree", P8_EXE, "--", path).strip() for path in (*PHASE8_ID1_RUNTIME, ID1_TEST, ID1_DOC, ID2_DOC, LIVE0_DOC))


@pytest.mark.parametrize("name", ID1_MODULES)
def test_id1_the_bootstrap_uses_exactly_the_sanctioned_a1_model_names_and_no_store(name: str) -> None:
    imports = _from_imports(PACKAGE_DIR / f"{name}.py")
    assert imports == SANCTIONED_ID1_IMPORTS[name]
    assert not any(m in (".identity_store", ".identity_resolver", ".identity_correction_store",
                         ".identity_remediation_resolver", ".observation_store", ".observation_resolver",
                         ".semantic_metadata_store", ".held_observation_store", ".jquants_financial_summary_executor",
                         ".metric_model", ".fundamental_metrics", ".fundamental_metrics_extended") for m in imports)
    for module in (*A1_MODULES, *A2_MODULES, *A1R_MODULES, *A2R_MODULES, *A3A_MODULES, *A3B_MODULES, *ST1_MODULES,
                   *ADP0_MODULES, *EXE_MODULES):
        if module != "__init__":                                            # 先行の層は ID1 を知らない
            used = _from_imports(PACKAGE_DIR / f"{module}.py")
            assert not any(m in (".identity_bootstrap_model", ".identity_bootstrap") for m in used), module


@pytest.mark.parametrize("name", ID1_MODULES)
def test_id1_no_derived_metric_screening_ranking_theme_or_latest_names(name: str) -> None:
    tree = ast.parse((PACKAGE_DIR / f"{name}.py").read_text(encoding="utf-8"))
    defined = {node.name for node in ast.walk(tree) if isinstance(node, (ast.FunctionDef, ast.ClassDef))}
    targets = {t.id for node in ast.walk(tree) if isinstance(node, (ast.Assign, ast.AnnAssign))
               for t in (node.targets if isinstance(node, ast.Assign) else [node.target]) if isinstance(t, ast.Name)}
    words = set().union(*(_words(item) for item in defined | targets))
    assert not words & DERIVED_TOKENS, (name, words & DERIVED_TOKENS)
    constants = {node.value for node in ast.walk(tree)
                 if isinstance(node, ast.Constant) and isinstance(node.value, str)}
    assert not constants & DERIVED_MEMBERS, constants & DERIVED_MEMBERS
    for clock in ("15:30", "06:30", "15:00", "09:00"):
        assert clock not in (PACKAGE_DIR / f"{name}.py").read_text(encoding="utf-8"), clock


def test_id1_the_review_vocabulary_is_closed_and_the_bootstrap_never_appends_to_a_store() -> None:
    from src.intelligence.screener_intelligence import identity_bootstrap_model as jbm
    assert {m.value for m in jbm.ReviewDisposition} == {"APPROVE", "REJECT", "DEFER"}
    assert {m.value for m in jbm.ReviewerClass} == {"HUMAN"}
    assert {m.value for m in jbm.ProposalDisposition} == {"PROPOSED", "HELD", "HUMAN_REVIEW_REQUIRED", "REUSE",
                                                          "CONFLICT"}
    for name in ID1_MODULES:
        tree = ast.parse((PACKAGE_DIR / f"{name}.py").read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Attribute):
                assert node.attr not in {"initialize", "unlink", "rename", "replace", "truncate", "write", "mkdir",
                                         "remove", "open"}, (name, node.attr)
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "append":
                assert isinstance(node.func.value, ast.Name), (name, "store append")


# ================================================================ P8-ID2（ID1 の凍結 ・登録 executor の境界）


def test_id2_the_pre_id2_runtime_phase8_tests_and_prior_documents_are_byte_identical_to_the_id1_anchor() -> None:
    assert subprocess.run(["git", "merge-base", "--is-ancestor", P8_ID1, "HEAD"], cwd=REPO_ROOT).returncode == 0
    frozen_tests = tuple(path for path in PHASE8_TESTS if path not in (
        "tests/intelligence/phase8_runtime_registry.py", "tests/intelligence/test_screener_intelligence_boundary.py",
        ID2_TEST))
    prior_docs = tuple(path for path in PHASE8_DOCS if path not in (ID2_DOC, LIVE0_DOC))
    assert len(PRE_ID2_RUNTIME) == 25 and len(frozen_tests) == 10 and len(prior_docs) == 19 and ID1_DOC in prior_docs
    for path in (*PRE_ID2_RUNTIME, *frozen_tests, *prior_docs):
        assert _git("show", f"{P8_ID1}:{path}") == (REPO_ROOT / path).read_text(encoding="utf-8"), path
    assert _git("diff", "--name-status", P8_ID1, "--", *PRE_ID2_RUNTIME, *frozen_tests, *prior_docs) == ""
    assert _git("status", "--porcelain", "--", *PRE_ID2_RUNTIME, *frozen_tests, *prior_docs) == ""
    assert not any(_git("ls-tree", P8_ID1, "--", path).strip() for path in (*PHASE8_ID2_RUNTIME, ID2_TEST, ID2_DOC, LIVE0_DOC))


@pytest.mark.parametrize("name", ID2_MODULES)
def test_id2_the_executor_uses_exactly_the_sanctioned_names_and_only_the_a1_store(name: str) -> None:
    imports = _from_imports(PACKAGE_DIR / f"{name}.py")
    assert imports == SANCTIONED_ID2_IMPORTS[name]
    assert not any(m in (".identity_resolver", ".identity_correction_store", ".identity_remediation_resolver",
                         ".observation_store", ".observation_resolver", ".semantic_metadata_store",
                         ".held_observation_store", ".jquants_financial_summary_executor", ".metric_model",
                         ".fundamental_metrics", ".fundamental_metrics_extended") for m in imports)
    for module in (*A1_MODULES, *A2_MODULES, *A1R_MODULES, *A2R_MODULES, *A3A_MODULES, *A3B_MODULES, *ST1_MODULES,
                   *ADP0_MODULES, *EXE_MODULES, *ID1_MODULES):
        if module != "__init__":                                            # 先行の層は ID2 を知らない
            used = _from_imports(PACKAGE_DIR / f"{module}.py")
            assert not any(m in (".identity_registration_model", ".identity_registration_executor") for m in used), \
                module


@pytest.mark.parametrize("name", ID2_MODULES)
def test_id2_no_derived_metric_screening_ranking_theme_or_latest_names(name: str) -> None:
    tree = ast.parse((PACKAGE_DIR / f"{name}.py").read_text(encoding="utf-8"))
    defined = {node.name for node in ast.walk(tree) if isinstance(node, (ast.FunctionDef, ast.ClassDef))}
    targets = {t.id for node in ast.walk(tree) if isinstance(node, (ast.Assign, ast.AnnAssign))
               for t in (node.targets if isinstance(node, ast.Assign) else [node.target]) if isinstance(t, ast.Name)}
    words = set().union(*(_words(item) for item in defined | targets))
    assert not words & DERIVED_TOKENS, (name, words & DERIVED_TOKENS)
    constants = {node.value for node in ast.walk(tree)
                 if isinstance(node, ast.Constant) and isinstance(node.value, str)}
    assert not constants & DERIVED_MEMBERS, constants & DERIVED_MEMBERS
    for clock in ("15:30", "06:30", "15:00", "09:00"):
        assert clock not in (PACKAGE_DIR / f"{name}.py").read_text(encoding="utf-8"), clock


def test_id2_the_outcome_vocabulary_is_closed_and_the_executor_never_initializes_or_deletes() -> None:
    from src.intelligence.screener_intelligence import identity_registration_model as jrm
    assert {m.value for m in jrm.RegistrationOutcome} == {"APPENDED", "REUSED", "REJECTED", "PARTIAL_FAILURE",
                                                          "NO_AUTHORIZED_ITEMS"}
    assert not set(jrm.RegistrationResult.__dataclass_fields__) & {"raw", "payload", "row", "score", "severity",
                                                                    "rank", "record_id"}
    tree = ast.parse((PACKAGE_DIR / "identity_registration_executor.py").read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute):
            assert node.attr not in {"initialize", "unlink", "rename", "replace", "truncate", "write", "mkdir",
                                     "remove"}, node.attr
