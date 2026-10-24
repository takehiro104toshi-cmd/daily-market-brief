"""P13-A0 — Phase 13（Market Memory ／ Review State Memory）の runtime の面の登録の guard。

- `PHASE13_RUNTIME` は空 ・P13 の package は存在しない（今 ・`P13_BASE` ・P12.5 の設計の closeout の anchor のどれにも）。
- `P13_BASE` 以後に変わったのは登録した P13 の test ・文書と、凍結の P7 〜 P12 の test への宣言した登録の行だけ（完全一致で pin）。
- 凍結の P8 〜 P12 の runtime の blob ・P12.5 の設計の契約の blob は anchor と object 一致。
- registry の drift は digest で止める: `PHASE13_RUNTIME` ・認可 ・test ・文書の集合の正準 digest が本 file の定数と一致しなければ落ちる
  （runtime の追加は registry と本 file と gate の文書の 3 つを同時に ・監督の gate で変える）。
- importer の許可は P13-A2a の adapter の 1 file だけ（P10 の governed な 5 つの名前 ・完全一致）。他の textual な import の禁止は不変。
- P13-A1 の runtime 4 file の blob は `P13_A1` の commit に pin（HEAD ・index ・作業木）。
- P13-A3: A2a の adapter の blob は `P13_A2A` に pin。filesystem の I/O の許しは `memory_store.py` だけ（stdlib の `os` ・`stat` ・名前 ・語の
  file ごとの許し ・`os` の属性の allowlist）。削除は `_unlink_if_owned` の 1 箇所の `unlink` だけで、呼ぶのは lock の解放と pointer の一時 file の
  破棄だけ（一般の削除 ・rmdir ・rmtree ・truncate は P13 のどこにも無い）。
- P13-A4a: A3 の Memory Store の 3 file の blob は `P13_A3` に pin（A1 ・A2a の pin も維持）。純粋な投影の model `memory_projection.py` は
  I/O を持たない（stdlib ・相対 import の面の完全一致 ・filesystem ／ network ／ process ／ 資格情報 ／ scheduler ・動的実行 ・import の時の
  副作用 ・項目 ／ 瞬間の属性の読みが無い）。P10 の importer の許可は不変。
- P13-A4a1: A4a の 0.1.0 の model の blob は `P13_A4A` に pin（A1 ・A2a ・A3 の pin も維持）。後継の `projection_contract.py` は A4a と同じ
  I/O の禁止に加え、A4a からの再利用の名前の完全一致 ・描画の関数が private な属性を読まないこと ・公開の面の完全一致を pin する。
- P13-A4b: A4a1 の後継の契約の blob は `P13_A4A1` に pin（A1 ・A2a ・A3 ・A4a の pin も維持）。2 つ目の filesystem の許しは
  `projection_store.py` だけ（file ごとの stdlib ・名前 ・語 ・`os` の呼び出しの場所 ・`shutil.disk_usage` の 1 箇所 ・削除は所有した lock の
  解放だけ ・公開の面の完全一致 ・A3 の許しは不変）。`projection_build.py` は filesystem を持たず store ・A3 ・A4a1 の公開の面だけを使う。
  どちらも 0.1.0 の model を import しない。P10 の importer の許可は不変。
- P13-A5-0R: Windows の検証の計画の記録（文書だけ）。必須の W-01 〜 W-20 ・A6 の条件つきの主張の状態 ・実の source の承認の要件 ・
  人の手順の安全の規則を pin し、完了の主張 ・捏造の結果 ・実行の権限 ・拒否の規則の弱化 ・private な形を拒む。
- P13-A5-T: Windows の特性の記録（文書だけ）。受理した T-02 ・T-03 の数 ・証拠の identity ・R1 の 5 つの場合と次の公開の注記 ・
  残る義務の状態を pin し、数の改変 ・R1 の欠落 ／ 再分類 ・A5 ／ A6 の受理の主張 ・凍結の主張 ・T の項目の誤った完了 ・A5-W の実行の
  主張 ・private な形を拒む。
- H0-D1: Home の情報の契約の記録（文書だけ）。6 つの項目の順と上限 ・8 つの状態と表示 ・優先の順 ・表示の集約の方針 ・PIT と取得の規則 ・
  主張の分類 ・等級 ・中立の digest の domain ・§14 の外の禁止の欄 ／ 語を pin し、項目 ／ 状態の改変 ・entry の状態の消去 ・fail closed の
  除去 ・仮説の昇格 ・将来の漏えい ・news の順 ／ 時間の窓の強制 ・S0 の確定 ・実装 ／ 実 data ／ deploy の主張 ・private な形を拒む。
  表示の集約は全ての状態の組で評価し（SUPERSEDED だけの項目は AVAILABLE にならない）、確信の語は表示の文（「」）の中だけで拒み、S0 の語彙の値は持たない。
- M0-D1: mobile の security と access の契約の記録（文書だけ）。脅威 model の 10 行 ・保存の禁止 ・CSP の指令 ・等級ごとの表示 ・閉じた失敗の code ・
  N1 〜 N5 の証拠 ・静的と実行時の保証 ・時刻の形 ・watermark を pin し、CSP の弱化 ・保存 ／ network の API の許可 ・PRIVATE_AUTHORITY ／ NEVER の表示 ・
  認証 ／ token ・hosting ／ deploy ・OS の隔離の主張 ・browser の暗号の主張 ・`Date` の parse ・watermark の欠落 ・S0 の確定 ・実 data の権限 ・
  private な形を拒む。H0-D1 の記録の blob は pin し、H0 の位置の assert は追記に安全な相対の順に置き換える。
- negative control: 未登録の path ・修正 ・近い名前 ・未宣言の登録の行 ・禁止の token ・一般の削除 ・store の外の I/O ・blob の変化 ・
  認可の drift ・公開の面の変更は落ちる。
"""
from __future__ import annotations

import ast
import hashlib
import json
import re
import subprocess
from pathlib import Path

import pytest

from tests.intelligence.phase8_runtime_registry import P8_B5C, PHASE8_RUNTIME
from tests.intelligence.phase9_runtime_registry import P9_A5, PHASE9_RUNTIME
from tests.intelligence.phase10_runtime_registry import P10_A4, PHASE10_RUNTIME
from tests.intelligence.phase11_runtime_registry import P11_A5, PHASE11_RUNTIME
from tests.intelligence.phase12_runtime_registry import (P12_5_DESIGN_ANCHOR, P12_A6, P12_VALIDATED_TREE, PHASE12_5_FROZEN_CONTRACTS,
                                                         PHASE12_RUNTIME)
from tests.intelligence.phase13_runtime_registry import (ADDITION_STATUSES, FORBIDDEN_P13_TOKENS, P13_A1, P13_A2A, P13_A3, P13_A4A,
                                                         P13_A4A1, P13_BASE, PHASE13_A1_RUNTIME, PHASE13_A2A_IMPORTER_LINES,
                                                         PHASE13_A2A_RUNTIME, PHASE13_A3_RUNTIME, PHASE13_A4A_RUNTIME, PHASE13_A4A1_RUNTIME,
                                                         PHASE13_A4B_RUNTIME, PHASE13_DOCS,
                                                         SANCTIONED_P13_P10_IMPORTERS, SANCTIONED_P13_P10_IMPORTS,
                                                         PHASE13_PACKAGE, PHASE13_RUNTIME, PHASE13_RUNTIME_AUTHORIZATION,
                                                         PHASE13_TESTS, PHASE13_TEST_REGISTRATION, is_phase13_addition,
                                                         only_phase13_registration, registration_diff)
from tests.intelligence.test_automation_boundary import FORBIDDEN_NAMES, FORBIDDEN_WORDS
from tests.intelligence.test_p43b2c_production_bundle import runtime_closure

REPO_ROOT = Path(__file__).resolve().parents[2]
PACKAGE_DIR = REPO_ROOT / PHASE13_PACKAGE
A0_DOC = "docs/databank/PHASE13_A0_RUNTIME_SURFACE_REGISTRATION.md"
A1_DOC = "docs/databank/PHASE13_A1_REVIEW_STATE_MODEL.md"
A2A_DOC = "docs/databank/PHASE13_A2A_GOVERNED_P10_ADAPTER.md"
A3_DOC = "docs/databank/PHASE13_A3_MEMORY_STORE.md"
ROADMAP_DOC = "docs/databank/MARKET_BRAIN_ROADMAP_RECORD.md"
A4A_DOC = "docs/databank/PHASE13_A4A_PROJECTION_MODEL.md"
A4A1_DOC = "docs/databank/PHASE13_A4A1_PROJECTION_RECONCILIATION.md"
ADAPTER = "src/intelligence/market_memory/governed_review_source.py"
GENERATION_MODULE = "src/intelligence/market_memory/memory_generation.py"
STORE_MODULE = "src/intelligence/market_memory/memory_store.py"
BUILD_MODULE = "src/intelligence/market_memory/memory_build.py"
PROJECTION_MODULE = "src/intelligence/market_memory/memory_projection.py"
CONTRACT_MODULE = "src/intelligence/market_memory/projection_contract.py"
A4B_DOC = "docs/databank/PHASE13_A4B_PROJECTION_EXPORT.md"
A5_PLAN_DOC = "docs/databank/PHASE13_A5_WINDOWS_VALIDATION_PLAN.md"
A5T_RECORD_DOC = "docs/databank/PHASE13_A5T_WINDOWS_CHARACTERIZATION_RECORD.md"
H0_D1_DOC = "docs/databank/H0_D1_HOME_INFORMATION_CONTRACT.md"
M0_D1_DOC = "docs/databank/M0_D1_MOBILE_SECURITY_ACCESS_CONTRACT.md"
H0_D1_BLOB = "ce5fbce76b30b700c58b619452fbf8f1433c3c81"   # H0-D1 の記録の blob（M0-D1 以後は変えない）
PROJECTION_STORE = "src/intelligence/market_memory/projection_store.py"
PROJECTION_BUILD = "src/intelligence/market_memory/projection_build.py"
P13_ROADMAP = "5e5f015ecebf64116f9c1721c36d9d41fa9dc1c7"   # roadmap の記録の commit ＝ A4a の認可の anchor
P10_IMPORTER_GUARD = "tests/intelligence/test_personal_intelligence_boundary.py"
P13_A0 = "4d464c30e4598d2ad5a0cee5a34ac366414fbde3"   # P13-A0 の commit ＝ A1 の認可の anchor
#: P13 の runtime が import してよい stdlib（file ごと ・完全一致）。file ・OS ・時計 ・環境 ・process ・socket ・乱数は無い
SANCTIONED_P13_STDLIB = {"__future__", "dataclasses", "datetime", "enum", "hashlib", "json", "re", "typing"}
SANCTIONED_P13_MODULES = {"src/intelligence/market_memory/__init__.py": set(), "src/intelligence/market_memory/canonical.py": set(),
                          "src/intelligence/market_memory/review_state_sample.py": {".canonical"},
                          "src/intelligence/market_memory/review_state_change.py": {".canonical", ".review_state_sample"},
                          ADAPTER: {".canonical", ".review_state_sample", *SANCTIONED_P13_P10_IMPORTS},
                          GENERATION_MODULE: {".canonical", ".review_state_change", ".review_state_sample"},
                          STORE_MODULE: {".canonical", ".memory_generation"},
                          BUILD_MODULE: {".governed_review_source", ".memory_generation", ".memory_store", ".review_state_sample"},
                          PROJECTION_MODULE: {".canonical", ".memory_generation", ".review_state_change", ".review_state_sample"},
                          CONTRACT_MODULE: {".canonical", ".memory_generation", ".memory_projection", ".review_state_change",
                                            ".review_state_sample"},
                          PROJECTION_STORE: {".canonical", ".memory_generation", ".memory_store", ".projection_contract"},
                          PROJECTION_BUILD: {".canonical", ".memory_generation", ".memory_store", ".projection_contract", ".projection_store"}}
#: P13-A3: filesystem の I/O を持つ唯一の module（file ごとの許し ・理由を伴う完全一致。他の P13 の file には無い）
#: P13-A4b: 2 つ目の狭い許しは export の store だけ（A3 の store の許しは不変 ・`shutil` は `disk_usage` の 1 箇所だけ）
SANCTIONED_P13_EXTRA_STDLIB = {STORE_MODULE: {"os", "stat"}, PROJECTION_STORE: {"os", "shutil", "stat"}}
P13_NAME_ALLOWANCES = {STORE_MODULE: {"open", "write", "mkdir", "rename", "unlink", "stat"},    # os.open ・os.write ・os.mkdir ・os.rename ・所有した lock ／ 一時 file の unlink ・stat の module ／ os.stat
                       PROJECTION_STORE: {"open", "write", "mkdir", "rename", "unlink", "stat"}}   # 同じ名前 ・unlink は所有した lock だけ
P13_WORD_ALLOWANCES = {STORE_MODULE: {"path"}, PROJECTION_STORE: {"path"}}                      # os.path だけ
#: P13 のどこにも在ってはならない削除 ・切り詰めの名前（store の `_unlink_if_owned` の `unlink` 1 箇所だけが例外）
P13_DELETION_NAMES = {"unlink", "remove", "removedirs", "rmdir", "rmtree", "truncate", "ftruncate", "unlinkat", "rmtree_safe"}
P13_UNLINK_SITES = [("_unlink_if_owned", "unlink")]
P13_UNLINK_CALLERS = {"release", "_publish_pointer"}
SANCTIONED_P13_OS_ATTRIBUTES = {"altsep", "close", "fspath", "fstat", "fsync", "listdir", "lstat", "mkdir", "name", "open", "path",
                                "read", "rename", "replace", "sep", "stat", "stat_result", "unlink", "write", "O_CREAT", "O_EXCL",
                                "O_RDONLY", "O_WRONLY"}
SANCTIONED_P13_OS_PATH_ATTRIBUTES = {"abspath", "commonpath", "dirname", "isabs", "join", "normcase", "normpath", "realpath",
                                     "splitdrive"}
SANCTIONED_P13_OS_GETATTR = {"O_BINARY", "O_NOFOLLOW"}
#: store の `os` の危険な呼び出しの場所（関数の名前 ・完全一致）。unlink は所有した lock ／ 一時 file の 1 箇所 ・os.stat は重なりの identity だけ ・
#: replace は pointer の置換だけ ・rename は generation ／ 試行の公開と置き換えない移動だけ ・mkdir は初期化 ・staging ・移動の予約だけ
P13_OS_CALL_SITES = {"unlink": {"_unlink_if_owned"}, "stat": {"_identities"}, "replace": {"_publish_pointer"},
                     "rename": {"_stage_generation", "record_attempt", "_move_without_replacing"},
                     "mkdir": {"_stage_generation", "initialize_memory_root", "_move_without_replacing"},
                     "open": {"_create_file", "_read_file", "_fsync_directory"}, "write": {"_write_all"}}
#: store の公開の面（関数 ・method ・完全一致）。writer lock を動かす ・奪う ・消す回復は無い
P13_STORE_PUBLIC_FUNCTIONS = {"initialize_memory_root", "open_memory_store", "read_memory", "preserve_interrupted_staging",
                              "preserve_publication_pointer"}
P13_STORE_PUBLIC_METHODS = {"acquire_writer_lock", "check_disjoint", "check_writable", "list_attempts", "list_generations",
                            "protected_labels", "publish_generation", "read_attempt", "read_generation", "read_publication",
                            "record_attempt", "staging_present"}
P13_PRESERVE_CALLERS = {"preserve_interrupted_staging", "preserve_publication_pointer"}
#: P13-A4a: 投影の model の stdlib の面（完全一致 ・`SANCTIONED_P13_STDLIB` より狭い ・hashlib ・datetime も無い）
P13_PROJECTION_STDLIB = {"__future__", "dataclasses", "enum", "json", "re", "typing"}
#: 投影の model に在ってはならない名前（凍結の `FORBIDDEN_NAMES` に加えて: 動的な import ・実行 ・属性の取得 ・I/O ／ 時計の module）
P13_PROJECTION_FORBIDDEN_NAMES = {"__import__", "importlib", "getattr", "globals", "locals", "vars", "compile", "Path", "pathlib", "io", "os",
                                  "shutil", "tempfile", "time", "sched", "asyncio", "threading", "urllib", "http", "requests"}
#: 投影の model が読んではならない属性（項目の id ・期日 ・瞬間 ・telemetry）
P13_PROJECTION_UNREAD_ATTRIBUTES = {"entries", "p9_root_id", "issuer_id", "p9_revision_id", "linked_watch_entry_id", "review_due_on", "at",
                                    "sampled_at", "known_at", "reviewed_at", "structural_values"}
#: 投影の model の module の直下で呼んでよいもの（定数の組み立てだけ ・import の時の副作用は無い）
P13_PROJECTION_MODULE_CALLS = {"compile", "frozenset", "tuple"}
P13_PROJECTION_PUBLIC_FUNCTIONS = {"abort_for", "build_projection_input", "check_recovery_proposal", "classify_publication", "completion_for",
                                   "intent_for", "interval_digest", "parse_abort", "parse_completion", "parse_export_manifest", "parse_intent",
                                   "parse_pointer", "render_pointer", "render_projection", "scan_private_shapes", "validate_note"}
#: P13-A4a1: 後継が凍結の A4a から再利用してよい名前（変わらない純粋な定数 ・固定の文 ・走査 ・error の class だけ ・完全一致）
P13_CONTRACT_A4A_REUSE = {"ABORT_REASONS", "APPROVED_CATEGORY_CODES", "CATEGORY_TABLE", "COUNT_TABLE", "DERIVED_NOTICE", "HEADING_CATEGORIES",
                          "HEADING_FIELDS", "HEADING_IDENTITY", "HEADING_INTERVALS", "HEADING_KINDS", "HEADING_P9", "HEADING_REVIEW",
                          "HEADING_SAMPLES", "INTERVAL_NOTICE", "KIND_TABLE", "MAX_NOTE_BYTES", "MAX_NOTE_LINE_CHARS", "MAX_RENDERED_COUNT",
                          "NO_INTERVALS_LINE", "NOTE_SUFFIX", "POINTER_NOTE_NAME", "POINTER_NOTICE", "TITLE_INDEX", "TITLE_INTERVAL",
                          "TITLE_POINTER", "TITLE_SAMPLE", "VALUE_TABLE", "VERSION_NOTICE", "ProjectionError", "scan_private_shapes"}
P13_CONTRACT_PUBLIC_FUNCTIONS = {"abort_for", "build_projection_target", "check_preservation_proposal", "check_recovery_proposal",
                                 "classify_publication", "completion_for", "intent_for", "note_name", "parse_abort", "parse_completion",
                                 "parse_intent", "parse_pointer", "parse_private_binding", "parse_public_export_manifest",
                                 "parse_public_version", "pointer_slot_identity", "public_note_identity", "public_version_of",
                                 "render_pointer", "render_public_export", "validate_public_note", "verify_public_version"}
#: 後継の描画の関数（public な model だけを受ける）と、そこで読んではならない private な属性
P13_CONTRACT_RENDER_FUNCTIONS = {"_frontmatter", "_render_sample", "_render_interval", "_render_index", "render_public_export",
                                 "_pointer_bytes", "render_pointer"}
P13_CONTRACT_PRIVATE_ATTRIBUTES = {"verified", "generation", "generation_digest", "manifest_digest", "private_generation_digest",
                                   "private_source_manifest_digest", "binding", "binding_digest", "sample_digest", "plan_digest",
                                   "change_digest", "samples", "changes", "cutoff", "counts", "entries", "view_identity"}
#: P13-A4b: export の store の `os` の危険な呼び出しの場所（関数の名前 ・完全一致）。unlink は所有した lock の解放の 1 箇所 ・replace は pointer
#: だけ ・rename は置き換えない移動と証拠の bundle ／ record の 1 回の rename だけ ・mkdir は排他の作成と移動の予約だけ ・listdir は 1 つの
#: directory の有界の一覧だけ
P13_EXPORT_OS_CALL_SITES = {"unlink": {"_unlink_if_owned"}, "stat": {"_identities"}, "replace": {"replace_pointer"},
                            "rename": {"_move_without_replacing", "write_evidence_bundle", "write_record"},
                            "mkdir": {"_make_directory", "_move_without_replacing"},
                            "open": {"_create_file", "_read_file", "_fsync_directory"}, "write": {"_write_all"}, "listdir": {"_entries"}}
P13_EXPORT_UNLINK_SITES = [("_unlink_if_owned", "unlink")]
P13_EXPORT_UNLINK_CALLERS = {"release"}
P13_EXPORT_SHUTIL_SITES = {"disk_usage": {"_free_bytes"}}
P13_EXPORT_STDLIB = {"__future__", "dataclasses", "json", "os", "re", "shutil", "stat", "typing"}
P13_EXPORT_BUILD_STDLIB = {"__future__", "dataclasses", "enum", "json", "re", "typing"}
P13_EXPORT_STORE_FUNCTIONS = {"initialize_private_root", "lock_record", "open_projection_store", "private_root_marker_bytes", "storage_units",
                              "vault_root_marker_bytes"}
P13_EXPORT_STORE_METHODS = {"acquire_locks", "check_locks", "free_space", "memory_location", "move_staged", "preserve", "private_free_space",
                            "projection_location", "protected_labels", "replace_pointer", "snapshot_private", "snapshot_vault", "stage_notes",
                            "vault_location", "write_evidence_bundle", "write_record"}
P13_EXPORT_BUILD_FUNCTIONS = {"failure_record", "preserve_projection_staging", "publish_projection", "scan_record", "scan_record_digest",
                              "scan_rules_digest", "source_record"}
#: build が store ／ lock の object に使う公開の面（完全一致 ・private な method ・`check_locks` の外の再検査の迂回は無い）
P13_EXPORT_BUILD_STORE_USES = {"acquire_locks", "free_space", "memory_location", "move_staged", "preserve", "private_free_space",
                               "projection_location", "replace_pointer", "snapshot_private", "snapshot_vault", "stage_notes", "vault_location",
                               "write_evidence_bundle", "write_record"}
P13_EXPORT_A3_IMPORTS = {PROJECTION_STORE: {"CODE_REPOSITORY_LABEL", "DIRECTORY_MODE", "FILE_MODE", "SYNC_FOLDER_NAMES", "SYNC_FOLDER_PREFIXES",
                                            "SYNC_MARKER_NAMES", "VAULT_MARKERS", "WORKING_TREE_MARKERS", "MemoryStoreError",
                                            "initialize_memory_root"},
                         PROJECTION_BUILD: {"GENERATION_VERIFIED", "PUBLICATION_VERIFIED", "MemoryStoreError", "ReadStatus", "open_memory_store"}}
P13_EXPORT_CONTRACT_IMPORTS = {
    PROJECTION_STORE: {"MAX_EXPORT_FILES", "MAX_NOTE_BYTES", "MAX_OBSERVED_OBJECTS", "POINTER_NOTE_NAME", "PRESERVE_AREA_RESERVATION",
                       "PRESERVE_AREA_STAGING"},
    PROJECTION_BUILD: {"AUTO_CONVERGE_ACTIONS", "CONTRACT_RULES_VERSION", "EVIDENCE_COMPLETION", "EVIDENCE_INTENT", "EVIDENCE_PRIVATE_BINDING",
                       "EVIDENCE_PUBLIC_EXPORT", "EXPLICIT_PRESERVATION_ACTIONS", "MAX_OBSERVED_OBJECTS", "POINTER_NOTE_NAME",
                       "PRESERVE_AREA_RESERVATION", "PRESERVE_AREA_STAGING", "PrivateBinding", "ProjectionError", "ProjectionTarget",
                       "ProposedAction", "PublicationObservation", "PublicationState", "PublicExportManifest", "RecoveryEligibility",
                       "TransitionPlan", "build_projection_target", "check_preservation_proposal", "check_recovery_proposal",
                       "classify_publication", "parse_intent", "parse_private_binding", "parse_public_export_manifest", "render_pointer",
                       "scan_private_shapes", "validate_public_note"}}                      # 走査器は A4a1 が承認した再利用の名前
#: registry の正準 digest（P13-A0 で確定 ・A3 ・roadmap の記録 ・A4a ・A4a1 ・A4b ・A5-0R の計画の記録 ・A5-T の特性の記録 ・H0-D1 の記録 ・M0-D1 の記録で更新。runtime ・認可 ・test ・文書 ・package ・base の集合。drift はここで止まる）
P13_REGISTRY_DIGEST = "9490f8bbfa19ef4b2c76ffdafc1483f832350d65697855a5108f864aa5347c28"
REGISTERED_FROZEN_TESTS = ("tests/intelligence/phase7_runtime_registry.py", "tests/intelligence/test_narrative_intelligence_boundary.py",
                           "tests/intelligence/test_screener_intelligence_boundary.py", "tests/intelligence/test_watchlist_thesis_boundary.py",
                           "tests/intelligence/test_personal_intelligence_boundary.py", "tests/intelligence/test_personal_ui_boundary.py",
                           "tests/intelligence/test_automation_boundary.py")
UNTOUCHED_REGISTRIES = ("tests/intelligence/phase8_runtime_registry.py", "tests/intelligence/phase9_runtime_registry.py",
                        "tests/intelligence/phase10_runtime_registry.py", "tests/intelligence/phase11_runtime_registry.py",
                        "tests/intelligence/phase12_runtime_registry.py")
FROZEN_SURFACE = ("knowledge", "config.yaml", ".github", "scripts", "docs/pages", "main.py", "requirements.txt",
                  "pyproject.toml", "cloudflare", "notifiers", "src/report")
#: P13 の文書 ・code に在ってはならない private の形（P12 の guard と同じ）
PRIVATE_PATTERNS = (r"[A-Za-z]:\\", r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}", r"\b\d{5}\b", r"p9wat_", r"p9ths_", r"p8iss_", r"p10prf_",
                    r"p10att_", r"human:", r"x-api-key", r"api\.jquants", r"S-1-5-\d", r"C:\\Users", r"JQUANTS_")


def _git(*args: str) -> str:
    return subprocess.run(["git", *args], cwd=REPO_ROOT, capture_output=True, text=True, check=True).stdout


def _changes(*args: str) -> set:
    return {tuple(line.split("\t")) for line in _git("diff", *args).splitlines()}


def _blobs(revision: str, paths) -> dict:
    out = _git("ls-tree", revision, "--", *paths)
    return {line.split("\t", 1)[1]: line.split()[2] for line in out.splitlines()}


def _registry_digest() -> str:
    payload = {"runtime": list(PHASE13_RUNTIME),
               "authorization": [[gate, anchor, list(paths), doc] for gate, anchor, paths, doc in PHASE13_RUNTIME_AUTHORIZATION],
               "tests": list(PHASE13_TESTS), "docs": list(PHASE13_DOCS), "package": PHASE13_PACKAGE, "base": P13_BASE}
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(("p13.registry.v1\0" + canonical).encode("utf-8")).hexdigest()


def _forbidden_tokens_in(text: str):
    return [token for token in FORBIDDEN_P13_TOKENS if token in text]


def _allowed_tokens(path: str):
    """P13 の file が含んでよい凍結の package 名（P13-A2a の adapter の `personal_intelligence` だけ）。"""
    return ["personal_intelligence"] if path in SANCTIONED_P13_P10_IMPORTERS else []


def _git_blob_of(data: bytes) -> str:
    """作業木の byte の git の blob の id（`git hash-object` と同じ ・書き込みは無い）。"""
    return hashlib.sha1(b"blob %d\0" % len(data) + data).hexdigest()


# ================================================ registry ・drift ・認可


def test_p13_a0_registry_is_exactly_the_reviewed_registration_and_runtime_is_empty() -> None:
    assert P13_BASE == "aded7ee8621e9abac18d313009444675ab771ae6"                                  # 固定の base（A0 の commit ではない）
    assert _git("merge-base", "--is-ancestor", P13_BASE, "HEAD") == ""
    assert len(PHASE13_A1_RUNTIME) == 4 and PHASE13_A2A_RUNTIME == (ADAPTER,)                       # A1: model 4 file ・A2a: adapter 1 file
    assert PHASE13_A3_RUNTIME == (BUILD_MODULE, GENERATION_MODULE, STORE_MODULE)                      # A3: store ／ rebuild の 3 file
    assert PHASE13_A4A_RUNTIME == (PROJECTION_MODULE,)                                               # A4a: 純粋な投影の model 1 file
    assert PHASE13_A4A1_RUNTIME == (CONTRACT_MODULE,)                                                # A4a1: 後継の純粋な契約 1 file
    assert PHASE13_A4B_RUNTIME == (PROJECTION_BUILD, PROJECTION_STORE)                               # A4b: export の orchestration ・store 2 file
    assert PHASE13_RUNTIME == tuple(sorted(PHASE13_A1_RUNTIME + PHASE13_A2A_RUNTIME + PHASE13_A3_RUNTIME + PHASE13_A4A_RUNTIME
                                           + PHASE13_A4A1_RUNTIME + PHASE13_A4B_RUNTIME))
    assert len(PHASE13_RUNTIME) == 12
    assert P13_A1 == "ccfc8e57885fabc5936a39034a9e816c66b2fbbc"
    assert P13_A2A == "12de956637bb1df5fcff8846ba9d7fcb606421a3"
    assert P13_A3 == "12dcfb2143527ca44a3e55afa7a2daa9bab2c33d"
    assert P13_A4A == "bc7f990df2ae8983a27a1d02b1f8a0a1738c5dd1"
    assert P13_A4A1 == "5181f59e6c639d72eeba37067fa66a4d82d27a38"
    assert PHASE13_RUNTIME_AUTHORIZATION == (("P13-A1", P13_A0, PHASE13_A1_RUNTIME, A1_DOC),
                                             ("P13-A2a", P13_A1, PHASE13_A2A_RUNTIME, A2A_DOC),
                                             ("P13-A3", P13_A2A, PHASE13_A3_RUNTIME, A3_DOC),
                                             ("P13-A4a", P13_ROADMAP, PHASE13_A4A_RUNTIME, A4A_DOC),
                                             ("P13-A4a1", P13_A4A, PHASE13_A4A1_RUNTIME, A4A1_DOC),
                                             ("P13-A4b", P13_A4A1, PHASE13_A4B_RUNTIME, A4B_DOC))
    assert dict(SANCTIONED_P13_P10_IMPORTERS) == {ADAPTER: SANCTIONED_P13_P10_IMPORTS}                # importer は adapter だけ
    assert {m: set(n) for m, n in SANCTIONED_P13_P10_IMPORTS.items()} == {
        "..personal_intelligence.p9_view": {"P9ViewError", "read_p9_safe_view"},
        "..personal_intelligence.personal_projection": {"personal_safe_projection"},
        "..personal_intelligence.review_view": {"ReviewViewError", "read_personal_review"}}               # P11 と同じ 5 つの名前
    assert set(SANCTIONED_P13_MODULES) == set(PHASE13_RUNTIME)
    assert PHASE13_PACKAGE == "src/intelligence/market_memory" and ADDITION_STATUSES == ("A", "??")
    assert PHASE13_TESTS == ("tests/intelligence/phase13_runtime_registry.py", "tests/intelligence/test_market_memory_boundary.py",
                             "tests/intelligence/test_market_memory_model.py", "tests/intelligence/test_market_memory_governed_source.py",
                             "tests/intelligence/test_market_memory_generation.py", "tests/intelligence/test_market_memory_store.py",
                             "tests/intelligence/test_market_memory_build.py", "tests/intelligence/test_market_memory_projection.py",
                             "tests/intelligence/test_market_memory_projection_contract.py",
                             "tests/intelligence/test_market_memory_projection_store.py",
                             "tests/intelligence/test_market_memory_projection_build.py")
    assert PHASE13_DOCS == (A0_DOC, A1_DOC, A2A_DOC, A3_DOC, ROADMAP_DOC, A4A_DOC, A4A1_DOC, A4B_DOC, A5_PLAN_DOC, A5T_RECORD_DOC,
                            H0_D1_DOC, M0_D1_DOC)
    assert set(SANCTIONED_P13_EXTRA_STDLIB) == set(P13_NAME_ALLOWANCES) == set(P13_WORD_ALLOWANCES) == {STORE_MODULE,
                                                                                                         PROJECTION_STORE}   # 許しは 2 つの store だけ
    assert SANCTIONED_P13_EXTRA_STDLIB[STORE_MODULE] == {"os", "stat"}                              # P13-A4b: A3 の許しは広げない
    assert _registry_digest() == P13_REGISTRY_DIGEST                                               # drift は digest で止まる
    for path in (*PHASE13_TESTS, *PHASE13_DOCS):
        assert (REPO_ROOT / path).is_file(), path
        assert not _git("ls-tree", P13_BASE, "--", path).strip(), path                              # 全て base の後に足した
    assert set(PHASE13_TEST_REGISTRATION) == set(REGISTERED_FROZEN_TESTS)


def test_p13_a0_every_future_runtime_path_must_be_bound_to_a_reviewed_gate_and_anchor() -> None:
    """runtime の追加の認可の規則（A0 では空集合に対して成り立つ）。tuple に path を足すだけでは通らない。"""
    authorized = {}
    for gate, anchor, paths, doc in PHASE13_RUNTIME_AUTHORIZATION:
        assert re.fullmatch(r"P13-A[0-9]+[a-z]?[0-9]?", gate), gate                               # P13-A4a1: 小文字の後の 1 桁だけを足す
        assert re.fullmatch(r"[0-9a-f]{40}", anchor) and _git("merge-base", "--is-ancestor", anchor, "HEAD") == "", gate
        assert doc in PHASE13_DOCS and (REPO_ROOT / doc).is_file(), gate
        text = (REPO_ROOT / doc).read_text(encoding="utf-8")
        for path in paths:
            assert path.startswith(PHASE13_PACKAGE + "/") and path.endswith(".py"), path
            assert not _git("ls-tree", anchor, "--", path).strip(), path                           # anchor にはまだ無い
            assert path in text, (gate, path)                                                       # gate の契約に path が在る
            assert path not in authorized, path                                                     # ちょうど 1 つの認可
            authorized[path] = gate
    assert set(PHASE13_RUNTIME) == set(authorized)                                                  # 認可の無い runtime は無い
    assert PHASE13_RUNTIME == tuple(sorted(PHASE13_RUNTIME))
    for path in PHASE13_RUNTIME:
        assert is_phase13_addition("A", path) and is_phase13_addition("??", path)
        assert not is_phase13_addition("M", path)                                                   # 修正は決して認めない
        assert not _git("ls-tree", P13_BASE, "--", path).strip()                                    # base には無い


# ================================================ src の面 ・凍結の test の狭い再開


def test_p13_a0_since_the_base_only_registered_phase13_files_and_declared_registration_changed() -> None:
    registered = {("A", p) for p in PHASE13_RUNTIME}
    assert _changes("--name-status", P13_BASE, "HEAD", "--", "src") <= registered                    # commit 済みの差は登録の追加だけ
    staged = _changes("--cached", "--name-status", P13_BASE, "--", "src")
    pending = {("A", line[3:]) for line in _git("status", "--porcelain", "--", "src").splitlines() if line[:2].strip() in ADDITION_STATUSES}
    assert staged <= registered and pending <= registered
    assert staged | pending == registered                                                           # 登録した file は全て在る（index か作業木）
    assert _git("diff", "--cached", "--name-status", P13_BASE, "--", *FROZEN_SURFACE) == ""
    assert _changes("--cached", "--name-status", P13_BASE, "--", "docs") <= {("A", p) for p in PHASE13_DOCS}
    assert _changes("--cached", "--name-status", P13_BASE, "--", "tests") <= {
        ("A", p) for p in PHASE13_TESTS} | {("M", p) for p in PHASE13_TEST_REGISTRATION}
    for path in PHASE13_TEST_REGISTRATION:                                                          # 凍結の P7 〜 P12 の test の狭い再開
        anchored = _git("show", f"{P13_BASE}:{path}")
        current = (REPO_ROOT / path).read_text(encoding="utf-8")
        assert only_phase13_registration(path, anchored, current), path
        assert not only_phase13_registration(path, anchored, current + "assert True\n"), path       # 未登録の追加
        assert not only_phase13_registration(path, anchored, anchored), path                         # 登録の欠落
        removed, added = PHASE13_TEST_REGISTRATION[path]
        assert added and all("is_outside_production" not in line and "no_other_code_imports" not in line for line in added), path
        importer_lines = [line for line in added if "SANCTIONED_P13" in line]
        if path == P10_IMPORTER_GUARD:                                                               # P13-A2a: P10 の guard の 5 行だけ
            assert set(PHASE13_A2A_IMPORTER_LINES) <= set(added), path
            assert set(importer_lines) <= set(PHASE13_A2A_IMPORTER_LINES), path
        else:
            assert importer_lines == [], path                                                        # 他の凍結の test に importer の許可は無い
    for registry in UNTOUCHED_REGISTRIES:
        assert _git("diff", "--name-status", P13_BASE, "--", registry) == "", registry               # 前の phase の registry は不変
    pending = [line for line in _git("status", "--porcelain", "--", "src").splitlines()
               if not is_phase13_addition(line[:2].strip(), line[3:])]
    assert pending == []


def test_p13_the_package_holds_exactly_the_registered_files_and_was_absent_at_the_historical_anchors() -> None:
    for revision in (P13_BASE, P13_A0, P12_5_DESIGN_ANCHOR, P12_A6, P12_VALIDATED_TREE):            # 歴史の事実: 登録の前に P13 は無かった
        assert not _git("ls-tree", revision, "--", PHASE13_PACKAGE).strip(), revision
    assert PACKAGE_DIR.is_dir()
    assert {p.name for p in PACKAGE_DIR.iterdir() if p.name != "__pycache__"} == {Path(p).name for p in PHASE13_RUNTIME}
    assert all(p.startswith(PHASE13_PACKAGE + "/") and p.endswith(".py") for p in PHASE13_RUNTIME)
    tracked_now = set(_git("ls-tree", "-r", "--name-only", "HEAD", "src").splitlines())
    tracked_base = set(_git("ls-tree", "-r", "--name-only", P13_BASE, "src").splitlines())
    assert tracked_base <= tracked_now and tracked_now - tracked_base <= set(PHASE13_RUNTIME)       # 以後は登録した P13 の追加だけ
    assert not any("market_memory" in module for module in runtime_closure())                      # 本番の閉包の外


# ================================================ 凍結の blob ・設計の契約


def test_p13_a0_frozen_runtime_and_design_contracts_are_object_identical_to_their_anchors() -> None:
    for anchor, runtime in ((P12_A6, PHASE12_RUNTIME), (P12_VALIDATED_TREE, PHASE12_RUNTIME), (P11_A5, PHASE11_RUNTIME),
                            (P10_A4, PHASE10_RUNTIME), (P9_A5, PHASE9_RUNTIME), (P8_B5C, PHASE8_RUNTIME)):
        anchored, head = _blobs(anchor, runtime), _blobs("HEAD", runtime)
        assert len(anchored) == len(runtime) and anchored == head, anchor
    anchored, head = _blobs(P12_5_DESIGN_ANCHOR, PHASE12_5_FROZEN_CONTRACTS), _blobs("HEAD", PHASE12_5_FROZEN_CONTRACTS)
    assert len(anchored) == len(PHASE12_5_FROZEN_CONTRACTS) and anchored == head
    assert _changes("--name-status", P12_A6, "HEAD", "--", "src") <= {("A", p) for p in PHASE13_RUNTIME}   # 登録した P13 の追加だけ


# ================================================ 文書 ・negative control


def test_p13_a0_the_registration_record_is_design_only_and_holds_no_private_values() -> None:
    text = (REPO_ROOT / A0_DOC).read_text(encoding="utf-8")
    for needle in ("P13-A0", "runtime surface registration", "PHASE13_RUNTIME", "空", P13_BASE, "P13_BASE", "PHASE13_TEST_REGISTRATION",
                   "only_phase13_registration", "PHASE13_RUNTIME_AUTHORIZATION", "digest", "importer の許可は無い", "P13-A2a",
                   "package は存在しない", "P12_5_DESIGN_ANCHOR", "修正は決して認めない", "negative control", "Review State Memory",
                   "P13-A1", "実装ではない", "B-track は HOLD"):
        assert needle in text, needle
    for banned in ("P13 は完了", "P13-A1 は完了", "Phase 13 は完了", "import を許可した", "署名済み", "最新の", "推奨する銘柄",
                   "D:\\", "0.0.0.0", "http://", "https://"):
        assert banned not in text, banned
    assert not re.search(r"\b(?:is|are|was|were|been)\s+(?:digitally\s+|cryptographically\s+)?signed\b", text, re.IGNORECASE)
    for pattern in PRIVATE_PATTERNS:
        assert not re.search(pattern, text), pattern


def _imports(path: Path):
    return _imports_text(path.read_text(encoding="utf-8"))


def _imports_text(text: str):
    relative, absolute = {}, set()
    for node in ast.walk(ast.parse(text)):
        if isinstance(node, ast.ImportFrom) and node.level:
            relative.setdefault("." * node.level + (node.module or ""), set()).update(a.name for a in node.names)
        elif isinstance(node, ast.ImportFrom):
            absolute.add(node.module)
        elif isinstance(node, ast.Import):
            absolute.update(a.name for a in node.names)
    return relative, absolute


def _import_violations(path: str, text: str) -> list:
    """stdlib の allowlist（file ごとの追加だけ）・相対 import の完全一致 ・凍結の phase への到達 ・禁止の token ・private の形。"""
    relative, absolute = _imports_text(text)
    allowed = SANCTIONED_P13_STDLIB | SANCTIONED_P13_EXTRA_STDLIB.get(path, set())
    found = [("STDLIB", m) for m in sorted(absolute - allowed)]
    if set(relative) != SANCTIONED_P13_MODULES.get(path, set()):
        found.append(("RELATIVE", tuple(sorted(set(relative) ^ SANCTIONED_P13_MODULES.get(path, set())))))
    cross = {m: n for m, n in relative.items() if m.startswith("..")}
    if cross != {m: set(n) for m, n in SANCTIONED_P13_P10_IMPORTERS.get(path, {}).items()}:   # adapter だけ ・完全一致
        found.append(("CROSS", tuple(sorted(cross))))
    if _forbidden_tokens_in(text) != _allowed_tokens(path):
        found.append(("TOKEN", tuple(_forbidden_tokens_in(text))))
    found += [("PRIVATE", pattern) for pattern in PRIVATE_PATTERNS if re.search(pattern, text)]
    if "__main__" in text or "import sys" in text or ("import os" in text and "os" not in SANCTIONED_P13_EXTRA_STDLIB.get(path, set())):
        found.append(("ENTRY_OR_OS", path))
    return found


def test_p13_a1_runtime_imports_are_stdlib_only_and_never_reach_frozen_phases() -> None:
    for path in PHASE13_RUNTIME:
        assert _import_violations(path, (REPO_ROOT / path).read_text(encoding="utf-8")) == [], path


def _guard_violations(path: str, text: str) -> list:
    """file ・OS ・時計 ・環境 ・process ・network の名前 ・投資 ／ 時計の相対の語彙 ・広い except（store の file ごとの許しだけを引く）。"""
    banned = FORBIDDEN_NAMES - P13_NAME_ALLOWANCES.get(path, set())
    found, identifiers = [], set()
    for node in ast.walk(ast.parse(text)):
        if isinstance(node, ast.Name):
            found += [("NAME", node.id)] if node.id in banned else []
            identifiers.add(node.id)
        elif isinstance(node, ast.Attribute):
            found += [("NAME", node.attr)] if node.attr in banned else []
            identifiers.add(node.attr)
        elif isinstance(node, ast.arg):
            identifiers.add(node.arg)
        elif isinstance(node, (ast.FunctionDef, ast.ClassDef)):
            identifiers.add(node.name)
        elif isinstance(node, ast.ExceptHandler):
            names = set() if node.type is None else {node.type.id} if isinstance(node.type, ast.Name) else {
                e.id for e in getattr(node.type, "elts", ()) if isinstance(e, ast.Name)}
            found += [("EXCEPT", "BROAD")] if node.type is None or names & {"Exception", "BaseException"} else []
    words = set()
    for name in identifiers:
        words |= {w.lower() for w in re.findall(r"[A-Z]?[a-z]+|[A-Z]+(?![a-z])", name)}
    return found + [("WORD", w) for w in sorted(words & (FORBIDDEN_WORDS - P13_WORD_ALLOWANCES.get(path, set())))]


def test_p13_a1_runtime_never_touches_files_env_clock_process_or_network_and_has_no_investment_vocabulary() -> None:
    for path in PHASE13_RUNTIME:
        assert _guard_violations(path, (REPO_ROOT / path).read_text(encoding="utf-8")) == [], path


def test_p13_a1_the_model_record_is_design_and_runtime_consistent_and_holds_no_private_values() -> None:
    text = (REPO_ROOT / A1_DOC).read_text(encoding="utf-8")
    for needle in ("P13-A1", "Review State Memory", "p13smp_", "p13chg_", "SampleCutoff", "SourceViewIdentity", "ReviewStateEntry",
                   "ReviewStateCounts", "ReviewStateSample", "ReviewStateChange", "SampleEvidence", "SampleOutcome", "StalenessLabel",
                   "PitState", "known_at", "reviewed_at", "捏造しない", "端点の差", "変化の不在", "MISSING", "INTEGRITY_FAILURE",
                   "空の標本", "telemetry", "SHORT_ID_COLLISION", "合成の入力", "凍結の package を import しない", "P13-A2a",
                   "importer の許可は無い", "store ・永続化 ・manifest は無い", P13_A0, *[Path(p).name for p in PHASE13_A1_RUNTIME]):
        assert needle in text, needle
    for banned in ("P13 は完了", "Phase 13 は完了", "import を許可した", "署名済み", "最新の", "推奨する銘柄", "D:\\", "0.0.0.0", "http://", "https://"):
        assert banned not in text, banned
    assert not re.search(r"\b(?:is|are|was|were|been)\s+(?:digitally\s+|cryptographically\s+)?signed\b", text, re.IGNORECASE)
    for pattern in PRIVATE_PATTERNS:
        assert not re.search(pattern, text), pattern
    from src.intelligence.market_memory.review_state_change import CHANGE_ID_PREFIX, CHANGE_SCHEMA_VERSION
    from src.intelligence.market_memory.review_state_sample import SAMPLE_ID_PREFIX, SAMPLE_SCHEMA_VERSION
    assert SAMPLE_ID_PREFIX == "p13smp_" and CHANGE_ID_PREFIX == "p13chg_"
    assert SAMPLE_SCHEMA_VERSION in text and CHANGE_SCHEMA_VERSION in text


def test_p13_a0_negative_controls_reject_unregistered_paths_modifications_near_misses_and_drift() -> None:
    for status in ("A", "??", "M", "D", "R"):
        assert not is_phase13_addition(status, f"{PHASE13_PACKAGE}/review_state_store.py")         # 未登録
        assert not is_phase13_addition(status, f"{PHASE13_PACKAGE}/p10_read_adapter.py")           # A2a の adapter はまだ無い
        assert not is_phase13_addition(status, "src/intelligence/market_memory2/model.py")           # 近い名前
        assert not is_phase13_addition(status, "src/intelligence/market_memory_model.py")
        assert not is_phase13_addition(status, PHASE12_RUNTIME[0])                                   # 凍結の runtime
        assert not is_phase13_addition(status, PHASE11_RUNTIME[0])
        assert not is_phase13_addition(status, "tests/intelligence/phase13_runtime_registry.py")
    anchored = "a\nb\n"
    assert registration_diff(anchored, anchored) == ([], [])
    assert registration_diff(anchored, "a\nX\nb\n") == ([], ["X"])
    assert registration_diff(anchored, "a\n") == (["b"], [])
    assert not only_phase13_registration("tests/intelligence/not_registered.py", anchored, anchored + "c\n")
    assert only_phase13_registration("tests/intelligence/not_registered.py", anchored, anchored)
    path = REGISTERED_FROZEN_TESTS[0]
    anchored = _git("show", f"{P13_BASE}:{path}")
    current = (REPO_ROOT / path).read_text(encoding="utf-8")
    removed, added = PHASE13_TEST_REGISTRATION[path]
    assert not only_phase13_registration(path, anchored, current.replace(added[0], added[0] + " "))   # 登録の行の改変
    assert not only_phase13_registration(path, anchored, current.replace(added[-1] + "\n", "", 1))     # 登録の行の欠落
    assert not only_phase13_registration(path, anchored, current + "\nPHASE7_RUNTIME = ()\n")        # 未登録の追加
    tampered = {"runtime": ["src/intelligence/market_memory/model.py"], "authorization": [], "tests": list(PHASE13_TESTS),
                "docs": list(PHASE13_DOCS), "package": PHASE13_PACKAGE, "base": P13_BASE}
    canonical = json.dumps(tampered, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    assert hashlib.sha256(("p13.registry.v1\0" + canonical).encode("utf-8")).hexdigest() != P13_REGISTRY_DIGEST   # tuple だけ足すと落ちる
    for token in FORBIDDEN_P13_TOKENS:
        assert _forbidden_tokens_in(f"from ..{token} import x") == [token] or token in _forbidden_tokens_in(f"import {token}")
    assert _forbidden_tokens_in("from dataclasses import dataclass") == []
    for path in PHASE13_RUNTIME:                                                                     # P13 の code の走査（adapter だけ P10 の名前）
        text = (REPO_ROOT / path).read_text(encoding="utf-8")
        assert _forbidden_tokens_in(text) == _allowed_tokens(path), path
    with pytest.raises(AssertionError):
        assert _forbidden_tokens_in("from ..personal_intelligence.review_view import read_personal_review") == []


# ================================================ P13-A2a: A1 の blob の pin ・importer の負の control ・文書


def test_p13_a2a_the_accepted_a1_runtime_is_object_identical_to_the_a1_anchor_in_head_index_and_worktree() -> None:
    assert _git("merge-base", "--is-ancestor", P13_A1, "HEAD") == ""
    anchored = _blobs(P13_A1, PHASE13_A1_RUNTIME)
    assert set(anchored) == set(PHASE13_A1_RUNTIME)                                                 # 4 file 全てが anchor に在る
    assert _blobs("HEAD", PHASE13_A1_RUNTIME) == anchored                                           # commit 済みの修正は無い
    index = {line.split("\t", 1)[1]: line.split()[1] for line in _git("ls-files", "-s", "--", *PHASE13_A1_RUNTIME).splitlines()}
    assert index == anchored                                                                        # index の修正は無い
    worktree = {path: _git_blob_of((REPO_ROOT / path).read_bytes()) for path in PHASE13_A1_RUNTIME}
    assert worktree == anchored                                                                     # 作業木の修正は無い
    for path in PHASE13_A1_RUNTIME:                                                                 # negative control: 1 byte の変化で一致しない
        assert _git_blob_of((REPO_ROOT / path).read_bytes() + b"#") != anchored[path], path
    assert _git_blob_of(b"") == "e69de29bb2d1d6434b8b29ae775ad8c2e48c5391"                          # git の空 blob と同じ計算


def test_p13_a2a_only_the_adapter_reaches_p10_and_any_other_import_surface_is_rejected() -> None:
    relative, _ = _imports(REPO_ROOT / ADAPTER)
    sanctioned = {m: set(n) for m, n in SANCTIONED_P13_P10_IMPORTS.items()}
    cross = {m: n for m, n in relative.items() if m.startswith("..")}
    assert cross == sanctioned
    for path in PHASE13_A1_RUNTIME:
        assert not any(m.startswith("..") for m in _imports(REPO_ROOT / path)[0]), path            # A1 は凍結の phase に届かない
    variants = (
        {**sanctioned, "..personal_intelligence.p9_view": sanctioned["..personal_intelligence.p9_view"] | {"read_p9_private_snapshot"}},
        {**sanctioned, "..personal_intelligence.profile_store": {"ProfileStore"}},
        {**sanctioned, "..watchlist_thesis_intelligence.watch_store": {"WatchlistStore"}},
        {**sanctioned, "..personal_ui.p10_read_adapter": {"read_ui_model"}},
        {m: n for m, n in sanctioned.items() if m != "..personal_intelligence.personal_projection"},
    )
    for variant in variants:
        assert variant != sanctioned                                                                  # 名前 ・module の追加 ／ 欠落は一致しない
    assert set(SANCTIONED_P13_P10_IMPORTERS) == {ADAPTER}
    assert "src/intelligence/market_memory/review_state_sample.py" not in SANCTIONED_P13_P10_IMPORTERS   # 別の importer は無い
    text = (REPO_ROOT / ADAPTER).read_text(encoding="utf-8")
    assert "outcome_for_source_failure" not in text.split('"""', 2)[2]                              # 生の P10 の code を A1 の写像に渡さない
    assert "SampleEvidence" not in text.split('"""', 2)[2] and "sampled_at" not in text.split('"""', 2)[2]   # telemetry を作らない
    init = REPO_ROOT / PHASE13_PACKAGE / "__init__.py"
    assert _imports(init) == ({}, set()) and "governed_review_source" not in init.read_text(encoding="utf-8")   # __init__ は adapter を出さない
    assert not any("market_memory" in module for module in runtime_closure())


def test_p13_a2a_the_adapter_record_states_the_contract_limits_and_holds_no_private_values() -> None:
    text = (REPO_ROOT / A2A_DOC).read_text(encoding="utf-8")
    for needle in ("P13-A2a", ADAPTER, "sample_review_state", "read_personal_review", "read_p9_safe_view", "personal_safe_projection",
                   "ReviewViewError", "P9ViewError", "SANCTIONED_P13_P10_IMPORTERS", "P13_A1", P13_A1, "MISSING", "INTEGRITY_FAILURE",
                   "P9_STORE_MISSING", "P10_STORE_MISSING", "P9_STORE_CORRUPTION", "P10_STORE_CORRUPTION", "SOURCE_CHANGED_DURING_READ",
                   "SOURCE_INPUT_REJECTED", "SOURCE_READ_UNCLASSIFIED", "VIEW_SCHEMA_UNSUPPORTED", "VIEW_CLASS_UNSUPPORTED",
                   "VIEW_AS_OF_MISMATCH", "ADAPTER_INPUT_INVALID", "outcome_for_source_failure", "ABA", "不可分", "SampleEvidence",
                   "known_at", "reviewed_at", "捏造しない", "合成の一時 root", "importer", "P13-A3", "B-track は HOLD"):
        assert needle in text, needle
    for banned in ("P13 は完了", "Phase 13 は完了", "atomic な snapshot を保証", "署名済み", "最新の", "推奨する銘柄", "D:\\", "0.0.0.0",
                   "http://", "https://"):
        assert banned not in text, banned
    assert not re.search(r"\b(?:is|are|was|were|been)\s+(?:digitally\s+|cryptographically\s+)?signed\b", text, re.IGNORECASE)
    for pattern in PRIVATE_PATTERNS:
        assert not re.search(pattern, text), pattern


# ================================================ P13-A3: A2a の blob の pin ・store だけの I/O ・狭い削除 ・negative control ・文書


def _deletion_sites(text: str) -> list:
    """削除 ・切り詰めの名前の出現を、囲む関数の名前と組で返す（module の直下は `<module>`）。"""
    sites = []

    def visit(node: ast.AST, owner: str) -> None:
        for child in ast.iter_child_nodes(node):
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                visit(child, child.name)
                continue
            name = child.id if isinstance(child, ast.Name) else child.attr if isinstance(child, ast.Attribute) else None
            if name in P13_DELETION_NAMES:
                sites.append((owner, name))
            visit(child, owner)
    visit(ast.parse(text), "<module>")
    return sites


def _callers_of(text: str, function: str) -> set:
    callers = set()
    for node in ast.walk(ast.parse(text)):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name != function:
            if any(isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id == function for n in ast.walk(node)):
                callers.add(node.name)
    return callers


def _os_attribute_violations(text: str) -> list:
    found = []
    for node in ast.walk(ast.parse(text)):
        if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name) and node.value.id == "os":
            found += [] if node.attr in SANCTIONED_P13_OS_ATTRIBUTES else [node.attr]
        elif (isinstance(node, ast.Attribute) and isinstance(node.value, ast.Attribute) and node.value.attr == "path"
              and isinstance(node.value.value, ast.Name) and node.value.value.id == "os"):
            found += [] if node.attr in SANCTIONED_P13_OS_PATH_ATTRIBUTES else ["path." + node.attr]
        elif (isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "getattr" and node.args
              and isinstance(node.args[0], ast.Name) and node.args[0].id == "os"):
            literal = node.args[1].value if len(node.args) > 1 and isinstance(node.args[1], ast.Constant) else None
            found += [] if literal in SANCTIONED_P13_OS_GETATTR else ["getattr"]
    return found


def _os_call_sites(text: str) -> dict:
    """`os.<名前>` の出現を、囲む関数の名前の集合で返す（module の直下は `<module>`）。"""
    sites: dict = {}

    def visit(node: ast.AST, owner: str) -> None:
        for child in ast.iter_child_nodes(node):
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                visit(child, child.name)
                continue
            if isinstance(child, ast.Attribute) and isinstance(child.value, ast.Name) and child.value.id == "os":
                sites.setdefault(child.attr, set()).add(owner)
            visit(child, owner)
    visit(ast.parse(text), "<module>")
    return sites


def _store_surface(text: str) -> tuple:
    tree = ast.parse(text)
    functions = {n.name for n in tree.body if isinstance(n, ast.FunctionDef) and not n.name.startswith("_")}
    store_class = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == "MemoryStore")
    methods = {m.name for m in store_class.body if isinstance(m, ast.FunctionDef) and not m.name.startswith("_")}
    return functions, methods


def _public_surface_violations(name_status: str) -> list:
    """公開 ・凍結の面（Pages ・workflow ・config ・scripts ・main ・報告 ・通知）への変更の行。"""
    return [line for line in name_status.splitlines()
            if any(line.split("\t")[-1] == root or line.split("\t")[-1].startswith(root + "/") for root in FROZEN_SURFACE)]


def test_p13_a3_the_accepted_a2a_adapter_is_object_identical_to_the_a2a_anchor_in_head_index_and_worktree() -> None:
    assert _git("merge-base", "--is-ancestor", P13_A2A, "HEAD") == ""
    for anchor, runtime in ((P13_A2A, PHASE13_A2A_RUNTIME), (P13_A2A, PHASE13_A1_RUNTIME), (P13_A1, PHASE13_A1_RUNTIME)):
        anchored = _blobs(anchor, runtime)
        assert set(anchored) == set(runtime), anchor                                                 # 全てが anchor に在る
        assert _blobs("HEAD", runtime) == anchored, anchor                                           # commit 済みの修正は無い
        index = {line.split("\t", 1)[1]: line.split()[1] for line in _git("ls-files", "-s", "--", *runtime).splitlines()}
        assert index == anchored, anchor                                                             # index の修正は無い
        worktree = {path: _git_blob_of((REPO_ROOT / path).read_bytes()) for path in runtime}
        assert worktree == anchored, anchor                                                          # 作業木の修正は無い
    for path in PHASE13_A3_RUNTIME:
        assert not _git("ls-tree", P13_A2A, "--", path).strip(), path                                # A3 の file は A2a の anchor に無かった


def test_p13_a3_only_the_store_has_filesystem_capabilities_and_deletion_is_confined_to_owned_lock_and_temp_release() -> None:
    for path in PHASE13_RUNTIME:
        text = (REPO_ROOT / path).read_text(encoding="utf-8")
        if path == STORE_MODULE:
            assert _deletion_sites(text) == P13_UNLINK_SITES                                          # unlink は 1 箇所だけ
            assert _callers_of(text, "_unlink_if_owned") == P13_UNLINK_CALLERS                       # lock の解放 ・pointer の一時 file だけ
            body = next(n for n in ast.walk(ast.parse(text)) if isinstance(n, ast.FunctionDef) and n.name == "_unlink_if_owned")
            calls = sorted((n.lineno, n.col_offset, n.func.id) for n in ast.walk(body) if isinstance(n, ast.Call)
                           and isinstance(n.func, ast.Name))
            assert calls[0][2] == "_owned"                                                           # 所有の検証が先（source の順）
            assert _os_attribute_violations(text) == []
            sites = _os_call_sites(text)
            assert {name: sites.get(name, set()) for name in P13_OS_CALL_SITES} == P13_OS_CALL_SITES  # 危険な呼び出しの場所は完全一致
            assert _store_surface(text) == (P13_STORE_PUBLIC_FUNCTIONS, P13_STORE_PUBLIC_METHODS)    # lock の回復 ・奪取の面は無い
            assert _callers_of(text, "preserve_interrupted_staging") == _callers_of(text, "preserve_publication_pointer") == set()
            preserve_callers = {n.name for n in ast.walk(ast.parse(text)) if isinstance(n, ast.FunctionDef) and any(
                isinstance(c, ast.Attribute) and c.attr == "_preserve" for c in ast.walk(n))}
            assert preserve_callers == P13_PRESERVE_CALLERS                                           # 移動は明示の回復の 2 つだけ
            lock_users = {n.name for n in ast.walk(ast.parse(text)) if isinstance(n, ast.FunctionDef) and any(
                isinstance(c, ast.Name) and c.id == "WRITER_LOCK_NAME" for c in ast.walk(n))}
            assert lock_users == {"acquire_writer_lock", "_check_layout_entries"}                    # lock の場所を触るのは取得と layout だけ
        elif path == PROJECTION_STORE:                                                                # P13-A4b: 2 つ目の狭い許し（pin は A4b の test）
            assert _deletion_sites(text) == P13_EXPORT_UNLINK_SITES
            assert _callers_of(text, "_unlink_if_owned") == P13_EXPORT_UNLINK_CALLERS
        else:
            assert _deletion_sites(text) == [], path                                                  # 他の file に削除は無い
            assert "os" not in _imports_text(text)[1] and "stat" not in _imports_text(text)[1], path     # store の外に filesystem は無い
            assert path not in P13_NAME_ALLOWANCES and path not in P13_WORD_ALLOWANCES, path
    build = (REPO_ROOT / BUILD_MODULE).read_text(encoding="utf-8")
    assert "preserve" not in build                                                                  # build は回復を呼ばない
    used = {n.attr for n in ast.walk(ast.parse(build)) if isinstance(n, ast.Attribute) and isinstance(n.value, ast.Name)
            and n.value.id in ("store", "lock")}
    assert used == {"check_disjoint", "acquire_writer_lock", "check_writable", "read_publication", "record_attempt",
                    "publish_generation", "release"}                                                 # build は store の狭い面だけ
    assert not any(name.startswith("_") for name in used)


def test_p13_a3_negative_controls_reject_new_files_modifications_imports_deletion_io_blob_and_registry_drift() -> None:
    for status in ("A", "??", "M"):                                                                   # 未登録の runtime ・既存の修正
        assert not is_phase13_addition(status, f"{PHASE13_PACKAGE}/memory_cleanup.py")
        assert not is_phase13_addition(status, f"{PHASE13_PACKAGE}/obsidian_export.py")
    for path in PHASE13_RUNTIME:
        assert not is_phase13_addition("M", path), path
    store = (REPO_ROOT / STORE_MODULE).read_text(encoding="utf-8")
    build = (REPO_ROOT / BUILD_MODULE).read_text(encoding="utf-8")
    frozen_import = build + "\nfrom ..personal_intelligence.review_view import read_personal_review\n"   # 凍結の import
    kinds = {kind for kind, _ in _import_violations(BUILD_MODULE, frozen_import)}
    assert {"RELATIVE", "CROSS", "TOKEN"} <= kinds
    general_delete = store + "\n\ndef delete_generation(location):\n    os.rmdir(location)\n    os.unlink(location)\n"   # 一般の削除
    assert _deletion_sites(general_delete) != P13_UNLINK_SITES
    assert ("delete_generation", "rmdir") in _deletion_sites(general_delete)
    assert _deletion_sites(store.replace("_owned(location, identity, data)", "True", 1)) == P13_UNLINK_SITES
    assert "shutil" not in SANCTIONED_P13_STDLIB | SANCTIONED_P13_EXTRA_STDLIB[STORE_MODULE]
    assert ("STDLIB", "shutil") in _import_violations(STORE_MODULE, store + "\nimport shutil\n")
    assert sorted(_os_attribute_violations("import os\nos.remove(x)\nos.system(x)\ngetattr(os, 'unlink')\n")) == ["getattr", "remove", "system"]
    io_outside = build + "\nimport os\n\ndef sneak(location):\n    return os.open(location, 0)\n"     # store の外の I/O
    assert ("NAME", "open") in _guard_violations(BUILD_MODULE, io_outside)
    assert ("STDLIB", "os") in _import_violations(BUILD_MODULE, io_outside)
    assert ("NAME", "open") in _guard_violations(GENERATION_MODULE, "def f(x):\n    return open(x)\n")
    assert _guard_violations(STORE_MODULE, "def f(x):\n    return x.exists()\n") == [("NAME", "exists")]   # store の許しも完全一致
    stat_elsewhere = store + "\n\ndef peek(location):\n    return os.stat(location)\n"              # os.stat の場所の拡大
    assert _os_call_sites(stat_elsewhere)["stat"] != P13_OS_CALL_SITES["stat"]
    takeover = store + "\n\ndef preserve_writer_lock(store):\n    return store\n"                  # lock の奪取の面の追加
    assert _store_surface(takeover)[0] != P13_STORE_PUBLIC_FUNCTIONS
    overwrite = store.replace("def _publish_pointer(", "def _publish_pointer_unused(self):\n        os.replace('a', 'b')\n\n    def _publish_pointer(", 1)
    assert _os_call_sites(overwrite)["replace"] != P13_OS_CALL_SITES["replace"]                      # 置換の場所の拡大
    for anchor, runtime in ((P13_A1, PHASE13_A1_RUNTIME), (P13_A2A, PHASE13_A2A_RUNTIME)):          # A1 ・A2a の blob の変化
        anchored = _blobs(anchor, runtime)
        for path in runtime:
            assert _git_blob_of((REPO_ROOT / path).read_bytes() + b"\n") != anchored[path], path
    drifted = (
        [*PHASE13_RUNTIME_AUTHORIZATION[:2], ("P13-A3", P13_A1, PHASE13_A3_RUNTIME, A3_DOC)],         # anchor の drift
        [*PHASE13_RUNTIME_AUTHORIZATION[:2], ("P13-A3", P13_A2A, PHASE13_A3_RUNTIME[:2], A3_DOC)],    # path の欠落
        [*PHASE13_RUNTIME_AUTHORIZATION, ("P13-A3b", P13_A2A, (f"{PHASE13_PACKAGE}/memory_cleanup.py",), A3_DOC)],
    )
    for authorization in drifted:
        payload = {"runtime": list(PHASE13_RUNTIME), "tests": list(PHASE13_TESTS), "docs": list(PHASE13_DOCS), "package": PHASE13_PACKAGE,
                   "base": P13_BASE, "authorization": [[g, a, list(p), d] for g, a, p, d in authorization]}
        canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        assert hashlib.sha256(("p13.registry.v1\0" + canonical).encode("utf-8")).hexdigest() != P13_REGISTRY_DIGEST
    assert _public_surface_violations("M\tdocs/pages/index.html\nA\tsrc/intelligence/market_memory/memory_store.py") == [
        "M\tdocs/pages/index.html"]                                                                  # 公開の面の変更は落ちる
    assert _public_surface_violations("M\t.github/workflows/x.yml\nM\tconfig.yaml") == ["M\t.github/workflows/x.yml", "M\tconfig.yaml"]
    assert _public_surface_violations(_git("diff", "--cached", "--name-status", P13_BASE)) == []      # 実際の差に公開の面は無い
    assert _public_surface_violations(_git("status", "--porcelain").replace(" ", "\t")) == []


def test_p13_a3_the_store_record_states_the_contract_limits_and_holds_no_private_values() -> None:
    text = (REPO_ROOT / A3_DOC).read_text(encoding="utf-8")
    for needle in ("P13-A3", *PHASE13_A3_RUNTIME, "plan digest", "generation digest", "manifest digest", "publication.json", "REUSED",
                   "INCOMPLETE", "attempts/", "writer lock", "O_EXCL", "_unlink_if_owned", "preserve_interrupted_staging",
                   "preserve_publication_pointer", "POINTER_VERIFIED_NOT_PRESERVED", "PUBLICATION_STATE_UNCERTAIN",
                   "lock の回復 ・奪取の API は無い", "置き換えない", "not race-proof", "ACL の privacy は未検証", "NTFS",
                   "rename だけでは公開の成功ではない", "TOCTOU", "junction",
                   "reparse point", "ACL", "P13-A5", "同期", "網羅ではない", "ABA", "不可分", "telemetry", "sampled_at",
                   "P13_A2A", P13_A2A, "P13_A1", "Obsidian", "export は無い", "B-track は HOLD", "MISSING", "INTEGRITY_FAILURE",
                   "SCHEMA_UNSUPPORTED", "NOT_PUBLISHED", "STAGING_PRESENT", "UNAUTHORIZED_ENTRY", "ROOT_IDENTITY_MISMATCH",
                   "WRITER_LOCK_PRESENT", "STALE", "合成の一時 root"):
        assert needle in text, needle
    for banned in ("P13 は完了", "Phase 13 は完了", "完全性を保証する", "不可分を保証する", "全ての同期", "すべての同期", "署名済み",
                   "最新の", "推奨する銘柄", "D:\\", "0.0.0.0", "http://", "https://", "preserve_writer_lock", "race-proof である"):
        assert banned not in text, banned
    assert not re.search(r"\b(?:is|are|was|were|been)\s+(?:digitally\s+|cryptographically\s+)?signed\b", text, re.IGNORECASE)
    for pattern in PRIVATE_PATTERNS:
        assert not re.search(pattern, text), pattern
    from src.intelligence.market_memory.memory_generation import (ATTEMPT_SCHEMA_VERSION, GENERATION_SCHEMA_VERSION,
                                                                  MANIFEST_SCHEMA_VERSION, MEMORY_RULES_VERSION,
                                                                  PUBLICATION_SCHEMA_VERSION, STORE_SCHEMA_VERSION)
    for version in (STORE_SCHEMA_VERSION, MEMORY_RULES_VERSION, GENERATION_SCHEMA_VERSION, MANIFEST_SCHEMA_VERSION,
                    PUBLICATION_SCHEMA_VERSION, ATTEMPT_SCHEMA_VERSION):
        assert version in text, version


# ================================================ Market Brain の roadmap の記録（文書だけ ・実装を承認しない）


def test_the_market_brain_roadmap_record_is_design_only_preserves_the_anchors_and_holds_no_private_values() -> None:
    text = (REPO_ROOT / ROADMAP_DOC).read_text(encoding="utf-8")
    for needle in ("MARKET BRAIN ROADMAP RECORD", "いかなる runtime の実装も承認しない", "いかなる将来の runtime の実装も承認しない",
                   "[VERIFIED CODE]", "[FROZEN CONTRACT]", "[APPROVED VISION]", "[PROPOSED DESIGN]", "[OPEN DECISION]",
                   "public の legacy production", "parked な vNext", "隔離された governed な P5 〜 P13", "将来の private な Market Brain の実行",
                   "SOURCE EVIDENCE", "MEMORY", "KNOWLEDGE GRAPH", "RETRIEVAL", "ANALYSIS", "EVALUATION", "CONTROLLED IMPROVEMENT",
                   "OBSIDIAN PROJECTION", "P13-E", "P13-K", "P13-R", "P14-I", "P14-V", "P14-L", "P12-B0", "L0", "Context Pack",
                   "legacy の `main.py` には自動で取り込まない", "公開の gate なしに", "凍結の P4 は承認なしに再開しない", "類似度 ・共起だけの edge は無い",
                   "MODEL_PROPOSED", "CONTESTED", "as-of の cutoff", "引用の trace", "将来の日付の囮", "循環の自己確認の防止",
                   "承認の無い全文の再現 ・保存はしない", "known_at", "credential custody", "過去の予測は保存する", "先読み無し",
                   "自律の production の規則の変更は無い", "counts-only", "Markdown は system の authority ではない", "決して自動で取り込まない",
                   "theme_learning.py", "変更しない ・無効にしない", "暫定", "期日 ・約束ではない", "P13-A4 の証拠の root",
                   "回復の状態機械", "private ／ public の実行の分離", "P14 の評価と release の統治",
                   P13_A1[:7], P13_A2A[:7], "12dcfb2143527ca44a3e55afa7a2daa9bab2c33d", "0a32d86", "4c19701", "1a7b9a2", "43c0b85", "e390cdd",
                   "2d18133"):
        assert needle in text, needle
    for banned in ("P13 は完了", "Phase 13 は完了", "P14 は完了", "実装を承認する", "実装済みの Knowledge Graph", "推奨する銘柄", "最新の",
                   "署名済み", "D:\\", "0.0.0.0", "http://", "https://"):
        assert banned not in text, banned
    assert not re.search(r"\b(?:is|are|was|were|been)\s+(?:digitally\s+|cryptographically\s+)?signed\b", text, re.IGNORECASE)
    for pattern in PRIVATE_PATTERNS:
        assert not re.search(pattern, text), pattern
    assert _git("merge-base", "--is-ancestor", "12dcfb2143527ca44a3e55afa7a2daa9bab2c33d", "HEAD") == ""   # 記録の基準の HEAD は祖先


# ================================================ P13-A4a: A3 の blob の pin ・純粋な投影の model（I/O 無し）・negative control ・文書


def _projection_violations(text: str, path: str = PROJECTION_MODULE) -> list:
    """P13-A4a ／ A4a1: 投影の model の import の面 ・I/O ／ 動的実行の名前 ・項目 ／ 瞬間の属性の読み ・module の直下の副作用。"""
    tree = ast.parse(text)
    relative, absolute = _imports_text(text)
    found = [("STDLIB", m) for m in sorted(absolute - P13_PROJECTION_STDLIB)]
    found += [("RELATIVE", m) for m in sorted(set(relative) - SANCTIONED_P13_MODULES[path])]
    for node in ast.walk(tree):
        if isinstance(node, ast.Name) and node.id in P13_PROJECTION_FORBIDDEN_NAMES:
            found.append(("NAME", node.id))
        elif isinstance(node, ast.Attribute) and node.attr in P13_PROJECTION_UNREAD_ATTRIBUTES:
            found.append(("ATTRIBUTE", node.attr))
    for index, statement in enumerate(tree.body):
        if isinstance(statement, (ast.Import, ast.ImportFrom, ast.FunctionDef, ast.ClassDef)):
            continue
        if index == 0 and isinstance(statement, ast.Expr) and isinstance(statement.value, ast.Constant):
            continue                                                                                 # module の docstring
        if isinstance(statement, (ast.Assign, ast.AnnAssign)):
            calls = {n.func.attr if isinstance(n.func, ast.Attribute) else n.func.id if isinstance(n.func, ast.Name) else "?"
                     for n in ast.walk(statement) if isinstance(n, ast.Call)}
            found += [("MODULE_CALL", name) for name in sorted(calls - P13_PROJECTION_MODULE_CALLS)]
            continue
        found.append(("MODULE_STATEMENT", type(statement).__name__))
    return found


def test_p13_a4a_the_accepted_a1_a2a_and_a3_runtime_is_object_identical_to_the_anchors_in_head_index_and_worktree() -> None:
    for anchor in (P13_A3, P13_ROADMAP):
        assert _git("merge-base", "--is-ancestor", anchor, "HEAD") == "", anchor
    for anchor, runtime in ((P13_A3, PHASE13_A3_RUNTIME), (P13_ROADMAP, PHASE13_A3_RUNTIME), (P13_A3, PHASE13_A2A_RUNTIME),
                            (P13_A2A, PHASE13_A2A_RUNTIME), (P13_A3, PHASE13_A1_RUNTIME), (P13_A1, PHASE13_A1_RUNTIME)):
        anchored = _blobs(anchor, runtime)
        assert set(anchored) == set(runtime), anchor                                                 # 全てが anchor に在る
        assert _blobs("HEAD", runtime) == anchored, anchor                                           # commit 済みの修正は無い
        index = {line.split("\t", 1)[1]: line.split()[1] for line in _git("ls-files", "-s", "--", *runtime).splitlines()}
        assert index == anchored, anchor                                                             # index の修正は無い
        worktree = {path: _git_blob_of((REPO_ROOT / path).read_bytes()) for path in runtime}
        assert worktree == anchored, anchor                                                          # 作業木の修正は無い
    for revision in (P13_A3, P13_ROADMAP):
        assert not _git("ls-tree", revision, "--", *PHASE13_A4A_RUNTIME).strip(), revision           # A4a の file は anchor に無かった
    added = {("A", p) for p in PHASE13_A4A_RUNTIME + PHASE13_A4A1_RUNTIME + PHASE13_A4B_RUNTIME}   # P13-A4a1 ・A4b: 登録した追加も
    assert _changes("--name-status", P13_A3, "HEAD", "--", "src") <= added                           # A3 以後の src は A4a ・A4a1 ・A4b の追加だけ
    assert _changes("--cached", "--name-status", P13_A3, "--", "src") <= added


def test_p13_a4a_the_projection_model_is_io_free_side_effect_free_and_never_reads_entries_or_instants() -> None:
    text = (REPO_ROOT / PROJECTION_MODULE).read_text(encoding="utf-8")
    assert _projection_violations(text) == []
    assert _import_violations(PROJECTION_MODULE, text) == [] and _guard_violations(PROJECTION_MODULE, text) == []
    relative, absolute = _imports_text(text)
    assert absolute == P13_PROJECTION_STDLIB and P13_PROJECTION_STDLIB < SANCTIONED_P13_STDLIB
    assert set(relative) == SANCTIONED_P13_MODULES[PROJECTION_MODULE]
    assert not {".memory_store", ".memory_build", ".governed_review_source"} & set(relative)        # I/O の module ・adapter に届かない
    assert not any(m.startswith("..") for m in relative)                                             # 凍結の phase に届かない
    assert _deletion_sites(text) == []
    for allowances in (P13_NAME_ALLOWANCES, P13_WORD_ALLOWANCES, SANCTIONED_P13_EXTRA_STDLIB, SANCTIONED_P13_P10_IMPORTERS):
        assert PROJECTION_MODULE not in allowances                                                   # file ごとの許しは無い
    tree = ast.parse(text)
    assert {n.name for n in tree.body if isinstance(n, ast.FunctionDef) and not n.name.startswith("_")} == P13_PROJECTION_PUBLIC_FUNCTIONS
    from src.intelligence.market_memory.memory_projection import ProposedAction
    assert {a.value for a in ProposedAction} == {"NONE", "PREPARE_INTENT", "STAGE_VERSION", "MOVE_STAGED_TO_VERSION", "REPLACE_POINTER",
                                                 "RECORD_COMPLETION", "HOLD"}                       # 前の版を動かす action は無い
    assert not any("market_memory" in module for module in runtime_closure())                      # 本番の閉包の外
    for path in sorted((REPO_ROOT / "src").rglob("*.py")):                                          # 他の code は投影を import しない
        if path.relative_to(REPO_ROOT).as_posix() not in (PROJECTION_MODULE, CONTRACT_MODULE):         # A4a1: 後継だけが再利用する
            assert "memory_projection" not in path.read_text(encoding="utf-8"), path.relative_to(REPO_ROOT).as_posix()
    assert "memory_projection" not in (REPO_ROOT / "main.py").read_text(encoding="utf-8")


def test_p13_a4a_negative_controls_reject_io_dynamic_execution_side_effects_entry_reads_importer_drift_and_blob_mutation() -> None:
    text = (REPO_ROOT / PROJECTION_MODULE).read_text(encoding="utf-8")
    for addition, violation in (("\nimport os\n", ("STDLIB", "os")), ("\nimport pathlib\n", ("STDLIB", "pathlib")),
                                ("\nimport io\n", ("STDLIB", "io")), ("\nimport socket\n", ("STDLIB", "socket")),
                                ("\nimport subprocess\n", ("STDLIB", "subprocess")), ("\nimport hashlib\n", ("STDLIB", "hashlib")),
                                ("\nfrom datetime import datetime\n", ("STDLIB", "datetime")),
                                ("\nfrom .memory_store import MemoryStore\n", ("RELATIVE", ".memory_store")),
                                ("\ndef sneak(x):\n    return __import__(x)\n", ("NAME", "__import__")),
                                ("\ndef sneak(x):\n    return getattr(x, 'y')\n", ("NAME", "getattr")),
                                ("\ndef sneak(x):\n    return compile(x, 'f', 'exec')\n", ("NAME", "compile")),
                                ("\ndef sneak(sample):\n    return sample.entries\n", ("ATTRIBUTE", "entries")),
                                ("\ndef sneak(cut):\n    return cut.at\n", ("ATTRIBUTE", "at")),
                                ("\ndef sneak(entry):\n    return entry.issuer_id\n", ("ATTRIBUTE", "issuer_id")),
                                ("\nSIDE = print('x')\n", ("MODULE_CALL", "print")), ("\nprint('x')\n", ("MODULE_STATEMENT", "Expr")),
                                ("\nfor _x in ():\n    pass\n", ("MODULE_STATEMENT", "For")),
                                ("\nif True:\n    VALUE = 1\n", ("MODULE_STATEMENT", "If"))):
        assert violation in _projection_violations(text + addition), addition
    assert ("NAME", "open") in _guard_violations(PROJECTION_MODULE, text + "\ndef sneak(x):\n    return open(x)\n")   # filesystem
    assert ("NAME", "exists") in _guard_violations(PROJECTION_MODULE, text + "\ndef sneak(x):\n    return x.exists()\n")
    assert ("NAME", "environ") in _guard_violations(PROJECTION_MODULE, text + "\ndef sneak(x):\n    return x.environ\n")   # 資格情報
    assert ("WORD", "cron") in _guard_violations(PROJECTION_MODULE, text + "\ndef cron_job():\n    pass\n")         # scheduler
    assert ("unlink" in {name for _, name in _deletion_sites(text + "\ndef sneak(x):\n    x.unlink()\n")})
    kinds = {kind for kind, _ in _import_violations(PROJECTION_MODULE, text + "\nfrom ..personal_intelligence.review_view import read_personal_review\n")}
    assert {"RELATIVE", "CROSS", "TOKEN"} <= kinds                                                   # 凍結の phase への import
    assert dict(SANCTIONED_P13_P10_IMPORTERS) == {ADAPTER: SANCTIONED_P13_P10_IMPORTS}                # importer の許可は不変（adapter だけ）
    assert {**SANCTIONED_P13_P10_IMPORTERS, PROJECTION_MODULE: SANCTIONED_P13_P10_IMPORTS} != dict(SANCTIONED_P13_P10_IMPORTERS)
    for anchor, runtime in ((P13_A1, PHASE13_A1_RUNTIME), (P13_A2A, PHASE13_A2A_RUNTIME), (P13_A3, PHASE13_A3_RUNTIME)):
        anchored = _blobs(anchor, runtime)
        for path in runtime:
            assert _git_blob_of((REPO_ROOT / path).read_bytes() + b"\n") != anchored[path], path      # 1 byte の変化で pin が外れる
    for status in ("A", "??", "M"):
        assert not is_phase13_addition(status, f"{PHASE13_PACKAGE}/projection_writer.py")             # A4b の writer は未登録
        assert not is_phase13_addition(status, f"{PHASE13_PACKAGE}/obsidian_vault.py")
    assert not is_phase13_addition("M", PROJECTION_MODULE)
    drifted = (
        [*PHASE13_RUNTIME_AUTHORIZATION[:3], ("P13-A4a", P13_A3, PHASE13_A4A_RUNTIME, A4A_DOC)],        # anchor の drift
        [*PHASE13_RUNTIME_AUTHORIZATION[:3], ("P13-A4a", P13_ROADMAP, (), A4A_DOC)],                   # path の欠落
        [*PHASE13_RUNTIME_AUTHORIZATION, ("P13-A4b", P13_ROADMAP, (f"{PHASE13_PACKAGE}/projection_writer.py",), A4A_DOC)],
    )
    for authorization in drifted:
        payload = {"runtime": list(PHASE13_RUNTIME), "tests": list(PHASE13_TESTS), "docs": list(PHASE13_DOCS), "package": PHASE13_PACKAGE,
                   "base": P13_BASE, "authorization": [[g, a, list(p), d] for g, a, p, d in authorization]}
        canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        assert hashlib.sha256(("p13.registry.v1\0" + canonical).encode("utf-8")).hexdigest() != P13_REGISTRY_DIGEST


def test_p13_a4a_the_projection_model_record_states_the_contract_and_holds_no_private_values() -> None:
    text = (REPO_ROOT / A4A_DOC).read_text(encoding="utf-8")
    for needle in ("P13-A4a", PROJECTION_MODULE, "Option C", ".p13-private-root", "memory/", "projection/", "契約は改めない",
                   "封じた A3 の子の", "build_projection_input", "SOURCE_ATTESTATION", "MemoryStore.read_generation", "ReadStatus.VERIFIED",
                   "D1", "D3 COUNTS ONLY", "D4 DATES ONLY", "D6", "D10", "D11", "known_at ではない", "PRIVATE_SHAPE_PATTERNS",
                   "validate_note", "APPROVED_CATEGORY_CODES", "CATEGORY_UNAPPROVED", "COUNT_OUT_OF_RANGE", "projection digest",
                   "export digest", "SHORT_ID_COLLISION", "MANIFEST_CONFLICT", "classify_publication", "check_recovery_proposal",
                   "FIRST_PUBLICATION", "PUBLISHED_VERIFIED", "NO_CHANGE", "INTENT_PREPARED", "STAGED_VERIFIED", "VERSION_VERIFIED",
                   "POINTER_SWITCHED", "FAIL_CLOSED", "AUTO_CONVERGE_ELIGIBLE", "HOLD_FAIL_CLOSED", "**存在しない**",
                   "PREVIOUS_VERSION_MISSING", "ORPHAN_STAGING", "UNREFERENCED_VERSION", "UNREFERENCED_MANIFEST", "POINTER_INVALID",
                   "OPEN ／ HOLD for A4b", "不可分な更新の証明ではない", "暗号の認証 ・署名ではない", "その場に残す", "容量",
                   "P13_A3", P13_A3, "P13_A2A", P13_A2A, "P13_A1", P13_A1, P13_ROADMAP, "本記録は A4b の実装を承認しない", "B-track は HOLD",
                   "runtime_closure", "合成の", "Windows", "Knowledge Graph ・Evidence Memory ・\nAI の叙述は無い"):
        assert needle in text, needle
    for banned in ("P13 は完了", "Phase 13 は完了", "A4 は完了", "A4b は完了", "署名済み", "最新の", "推奨する銘柄", "D:\\", "0.0.0.0",
                   "http://", "https://", "不可分を保証する", "原子的な更新を保証する", "store から読んだことを証明する", "archive する action を"):
        assert banned not in text, banned
    assert not re.search(r"\b(?:is|are|was|were|been)\s+(?:digitally\s+|cryptographically\s+)?signed\b", text, re.IGNORECASE)
    for pattern in PRIVATE_PATTERNS:
        assert not re.search(pattern, text), pattern
    from src.intelligence.market_memory import memory_projection as projection
    for version in (projection.PROJECTION_SCHEMA_VERSION, projection.PROJECTION_RULES_VERSION, projection.EXPORT_MANIFEST_SCHEMA_VERSION,
                    projection.POINTER_SCHEMA_VERSION, projection.INTENT_SCHEMA_VERSION, projection.COMPLETION_SCHEMA_VERSION,
                    projection.ABORT_SCHEMA_VERSION, projection.SOURCE_ATTESTATION, projection.PROJECTION_DOMAIN, projection.EXPORT_DOMAIN,
                    projection.INTERVAL_DOMAIN):
        assert version in text, version


# ================================================ P13-A4a1: A4a の blob の pin ・後継の純粋な契約 ・negative control ・文書


def _a4a_reuse_names(text: str) -> set:
    return {a.name for node in ast.walk(ast.parse(text)) if isinstance(node, ast.ImportFrom) and node.level == 1
            and node.module == "memory_projection" for a in node.names}


def _render_private_reads(text: str) -> list:
    """後継の描画の関数が読む private な属性（public な model だけを受けること）。"""
    found = []
    for node in ast.walk(ast.parse(text)):
        if isinstance(node, ast.FunctionDef) and node.name in P13_CONTRACT_RENDER_FUNCTIONS:
            found += [(node.name, n.attr) for n in ast.walk(node) if isinstance(n, ast.Attribute) and n.attr in P13_CONTRACT_PRIVATE_ATTRIBUTES]
    return found


def test_p13_a4a1_the_accepted_a1_a2a_a3_and_a4a_runtime_is_object_identical_to_the_anchors_in_head_index_and_worktree() -> None:
    assert _git("merge-base", "--is-ancestor", P13_A4A, "HEAD") == ""
    for anchor, runtime in ((P13_A4A, PHASE13_A4A_RUNTIME), (P13_A4A, PHASE13_A3_RUNTIME), (P13_A4A, PHASE13_A2A_RUNTIME),
                            (P13_A4A, PHASE13_A1_RUNTIME), (P13_A3, PHASE13_A3_RUNTIME), (P13_A2A, PHASE13_A2A_RUNTIME),
                            (P13_A1, PHASE13_A1_RUNTIME)):
        anchored = _blobs(anchor, runtime)
        assert set(anchored) == set(runtime), anchor
        assert _blobs("HEAD", runtime) == anchored, anchor                                           # commit 済みの修正は無い
        index = {line.split("\t", 1)[1]: line.split()[1] for line in _git("ls-files", "-s", "--", *runtime).splitlines()}
        assert index == anchored, anchor                                                             # index の修正は無い
        worktree = {path: _git_blob_of((REPO_ROOT / path).read_bytes()) for path in runtime}
        assert worktree == anchored, anchor                                                          # 作業木の修正は無い
    assert _blobs(P13_A4A, PHASE13_A4A_RUNTIME) == {PROJECTION_MODULE: "04bdabf2e24ddb9e8175b941b8980fcf4781fb73"}   # 受理した A4a の blob
    assert not _git("ls-tree", P13_A4A, "--", *PHASE13_A4A1_RUNTIME).strip()                         # 後継は anchor に無かった
    added = {("A", p) for p in PHASE13_A4A1_RUNTIME + PHASE13_A4B_RUNTIME}                         # P13-A4b: 登録した export の追加も
    assert _changes("--name-status", P13_A4A, "HEAD", "--", "src") <= added                          # A4a 以後の src は後継 ・A4b の追加だけ
    assert _changes("--cached", "--name-status", P13_A4A, "--", "src") <= added


def test_p13_a4a1_the_successor_is_io_free_reuses_only_approved_a4a_names_and_never_renders_private_attributes() -> None:
    text = (REPO_ROOT / CONTRACT_MODULE).read_text(encoding="utf-8")
    assert _projection_violations(text, CONTRACT_MODULE) == []
    assert _import_violations(CONTRACT_MODULE, text) == [] and _guard_violations(CONTRACT_MODULE, text) == []
    relative, absolute = _imports_text(text)
    assert absolute == P13_PROJECTION_STDLIB and set(relative) == SANCTIONED_P13_MODULES[CONTRACT_MODULE]
    assert not {".memory_store", ".memory_build", ".governed_review_source"} & set(relative)       # I/O の module ・adapter に届かない
    assert not any(m.startswith("..") for m in relative)
    assert _a4a_reuse_names(text) == P13_CONTRACT_A4A_REUSE                                          # 再利用は承認した名前だけ
    assert not {"render_projection", "validate_note", "classify_publication", "ProjectionInput", "ExportManifest", "IntentRecord",
                "parse_pointer", "render_pointer"} & _a4a_reuse_names(text)                          # 0.1.0 の振る舞いを包まない
    assert _render_private_reads(text) == []                                                         # 描画は public な model だけ
    assert _deletion_sites(text) == []
    for allowances in (P13_NAME_ALLOWANCES, P13_WORD_ALLOWANCES, SANCTIONED_P13_EXTRA_STDLIB, SANCTIONED_P13_P10_IMPORTERS):
        assert CONTRACT_MODULE not in allowances
    tree = ast.parse(text)
    assert {n.name for n in tree.body if isinstance(n, ast.FunctionDef) and not n.name.startswith("_")} == P13_CONTRACT_PUBLIC_FUNCTIONS
    for node in tree.body:                                                                           # public な class に private な欄は無い
        if isinstance(node, ast.ClassDef) and node.name in {"PublicSample", "PublicInterval", "PublicVersion", "PublicFile",
                                                             "PublicExportManifest", "PublicExport"}:
            fields = {t.target.id for t in node.body if isinstance(t, ast.AnnAssign) and isinstance(t.target, ast.Name)}
            assert not {f for f in fields if "private" in f or "generation" in f or "binding" in f or "sample_digest" in f}, node.name
    assert not any("market_memory" in module for module in runtime_closure())
    for path in sorted((REPO_ROOT / "src").rglob("*.py")):                                          # 後継を import するのは A4b の 2 file だけ
        if path.relative_to(REPO_ROOT).as_posix() not in (CONTRACT_MODULE, *PHASE13_A4B_RUNTIME):
            assert "projection_contract" not in path.read_text(encoding="utf-8"), path.relative_to(REPO_ROOT).as_posix()


def test_p13_a4a1_negative_controls_reject_io_extra_reuse_private_rendering_blob_mutation_and_registry_drift() -> None:
    text = (REPO_ROOT / CONTRACT_MODULE).read_text(encoding="utf-8")
    for addition, violation in (("\nimport os\n", ("STDLIB", "os")), ("\nimport hashlib\n", ("STDLIB", "hashlib")),
                                ("\nfrom .memory_store import MemoryStore\n", ("RELATIVE", ".memory_store")),
                                ("\ndef sneak(x):\n    return getattr(x, 'y')\n", ("NAME", "getattr")),
                                ("\ndef sneak(cut):\n    return cut.at\n", ("ATTRIBUTE", "at")),
                                ("\nSIDE = print('x')\n", ("MODULE_CALL", "print"))):
        assert violation in _projection_violations(text + addition, CONTRACT_MODULE), addition
    assert ("NAME", "open") in _guard_violations(CONTRACT_MODULE, text + "\ndef sneak(x):\n    return open(x)\n")
    extra = text.replace("ProjectionError, scan_private_shapes)", "ProjectionError, render_projection, scan_private_shapes)", 1)
    assert extra != text and _a4a_reuse_names(extra) != P13_CONTRACT_A4A_REUSE                       # 0.1.0 の描画の再利用は落ちる
    leaky = text.replace("    digest = version.public_version_digest\n    name = note_name(version.version_label, \"SAMPLE\"",
                         "    digest = version.public_version_digest\n    _x = source.generation_digest\n    name = note_name("
                         "version.version_label, \"SAMPLE\"", 1)
    assert leaky != text and ("_render_sample", "generation_digest") in _render_private_reads(leaky)   # 描画の private な読み
    for anchor, runtime in ((P13_A4A, PHASE13_A4A_RUNTIME), (P13_A3, PHASE13_A3_RUNTIME), (P13_A2A, PHASE13_A2A_RUNTIME),
                            (P13_A1, PHASE13_A1_RUNTIME)):
        anchored = _blobs(anchor, runtime)
        for path in runtime:
            assert _git_blob_of((REPO_ROOT / path).read_bytes() + b"\n") != anchored[path], path
    for status in ("A", "??", "M"):
        assert not is_phase13_addition(status, f"{PHASE13_PACKAGE}/projection_cleanup.py")           # P13-A4b の後も未登録の名前
        assert not is_phase13_addition(status, f"{PHASE13_PACKAGE}/projection_restore.py")
    assert is_phase13_addition("A", PROJECTION_STORE) and not is_phase13_addition("M", PROJECTION_STORE)   # P13-A4b で登録した追加だけ
    assert not is_phase13_addition("M", CONTRACT_MODULE) and not is_phase13_addition("M", PROJECTION_MODULE)
    for gate in ("P13-A4a1", "P13-A4a", "P13-A3"):
        assert re.fullmatch(r"P13-A[0-9]+[a-z]?[0-9]?", gate)
    for gate in ("P13-A4a12", "P13-A4a.1", "P13-A4-1", "P13-A4aa"):
        assert not re.fullmatch(r"P13-A[0-9]+[a-z]?[0-9]?", gate), gate                              # gate の名前の拡張は 1 桁だけ
    assert dict(SANCTIONED_P13_P10_IMPORTERS) == {ADAPTER: SANCTIONED_P13_P10_IMPORTS}
    drifted = (
        [*PHASE13_RUNTIME_AUTHORIZATION[:4], ("P13-A4a1", P13_ROADMAP, PHASE13_A4A1_RUNTIME, A4A1_DOC)],   # anchor の drift
        [*PHASE13_RUNTIME_AUTHORIZATION[:4], ("P13-A4a1", P13_A4A, (), A4A1_DOC)],                       # path の欠落
        [*PHASE13_RUNTIME_AUTHORIZATION, ("P13-A4b", P13_A4A, (f"{PHASE13_PACKAGE}/projection_store.py",), A4A1_DOC)],
    )
    for authorization in drifted:
        payload = {"runtime": list(PHASE13_RUNTIME), "tests": list(PHASE13_TESTS), "docs": list(PHASE13_DOCS), "package": PHASE13_PACKAGE,
                   "base": P13_BASE, "authorization": [[g, a, list(p), d] for g, a, p, d in authorization]}
        canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        assert hashlib.sha256(("p13.registry.v1\0" + canonical).encode("utf-8")).hexdigest() != P13_REGISTRY_DIGEST


def test_p13_a4a1_the_reconciliation_record_states_the_deviations_and_holds_no_private_values() -> None:
    text = (REPO_ROOT / A4A1_DOC).read_text(encoding="utf-8")
    for needle in ("P13-A4a1", CONTRACT_MODULE, "P13_A4A", P13_A4A, "P13_A3", P13_A3, "P13_A2A", P13_A2A, "P13_A1", P13_A1,
                   "generated: \"true\"", "文字の値", "YAML の真偽ではない", "PRIVATE_EVIDENCE_ONLY", "限定した逸脱", "§6.1", "§6.3", "§7",
                   "文字どおりの充足ではない", "将来の調整", "item_id", "build_id", "生成した note", "public な export の build",
                   "Memory Store の build ・計画の identity ではない", "NOT_AVAILABLE", "known_at", "acquisition_time", "as_of",
                   "p13_as_of_basis", "p13pvn_", "p13psm_", "p13piv_", "p13ptr_", "候補の列挙", "hash は秘匿ではない",
                   "digest を介した漏えい", "全ての推論を防ぐものではない", "NO_CHANGE", "RECORD_PRIVATE_BINDING", "provenance",
                   "CONTINUE_STAGING", "PRESERVE_STAGING", "PRESERVE_EMPTY_RESERVATION", "明示の保存だけ", "STAGING_TAMPERED",
                   "STAGING_FOREIGN_ENTRY", "前の有効な版", "0.1.0", "公開に安全だったとは主張しない", "A4b は後継だけ",
                   "A3 の store の読みを証明しない", "秘密 ・暗号 ・乱数の label は無い", "B-track は HOLD", "本記録は A4b の実装を承認しない",
                   "合成の"):
        assert needle in text, needle
    for banned in ("P13 は完了", "Phase 13 は完了", "A4 は完了", "A4b は完了", "署名済み", "最新の", "推奨する銘柄", "D:\\", "0.0.0.0",
                   "http://", "https://", "文字どおりに充足する", "0.1.0 は公開に安全", "全ての推論を防ぐ。"):
        assert banned not in text, banned
    assert not re.search(r"\b(?:is|are|was|were|been)\s+(?:digitally\s+|cryptographically\s+)?signed\b", text, re.IGNORECASE)
    for pattern in PRIVATE_PATTERNS:
        assert not re.search(pattern, text), pattern
    from src.intelligence.market_memory import projection_contract as contract
    for version in (contract.CONTRACT_SCHEMA_VERSION, contract.CONTRACT_RULES_VERSION, contract.POINTER_SCHEMA_VERSION,
                    contract.PUBLIC_EXPORT_SCHEMA_VERSION, contract.BINDING_SCHEMA_VERSION, contract.INTENT_SCHEMA_VERSION,
                    contract.COMPLETION_SCHEMA_VERSION, contract.ABORT_SCHEMA_VERSION, contract.PUBLIC_VERSION_DOMAIN,
                    contract.PUBLIC_NOTE_DOMAIN, contract.PUBLIC_EXPORT_DOMAIN, contract.BINDING_DOMAIN, contract.SOURCE_ATTESTATION,
                    contract.BUILD_BASIS, *contract.AS_OF_BASIS.values()):
        assert version in text, version


# ================================================ P13-A4b: A4a1 の blob の pin ・2 つ目の狭い filesystem の許し ・orchestration ・negative control ・文書


def _module_attribute_sites(text: str, module: str) -> dict:
    """`<module>.<名前>` の出現を、囲む関数の名前の集合で返す（module の直下は `<module>`）。"""
    sites: dict = {}

    def visit(node: ast.AST, owner: str) -> None:
        for child in ast.iter_child_nodes(node):
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                visit(child, child.name)
                continue
            if isinstance(child, ast.Attribute) and isinstance(child.value, ast.Name) and child.value.id == module:
                sites.setdefault(child.attr, set()).add(owner)
            visit(child, owner)
    visit(ast.parse(text), "<module>")
    return sites


def _class_surface(text: str, class_name: str) -> set:
    node = next(n for n in ast.parse(text).body if isinstance(n, ast.ClassDef) and n.name == class_name)
    return {m.name for m in node.body if isinstance(m, ast.FunctionDef) and not m.name.startswith("_")}


def _public_functions(text: str) -> set:
    return {n.name for n in ast.parse(text).body if isinstance(n, ast.FunctionDef) and not n.name.startswith("_")}


def _imported_names(text: str, module: str) -> set:
    return {a.name for node in ast.walk(ast.parse(text)) if isinstance(node, ast.ImportFrom) and node.level == 1
            and node.module == module for a in node.names}


def _object_uses(text: str, name: str) -> set:
    """`<name>.<属性>` ・`self.<name>.<属性>` の属性の集合（build が store ／ lock の object に使う面）。"""
    found = set()
    for node in ast.walk(ast.parse(text)):
        if isinstance(node, ast.Attribute):
            owner = node.value
            if (isinstance(owner, ast.Name) and owner.id == name) or (isinstance(owner, ast.Attribute) and owner.attr == name
                                                                      and isinstance(owner.value, ast.Name) and owner.value.id == "self"):
                found.add(node.attr)
    return found


def _export_store_violations(text: str) -> list:
    """export の store の 2 つ目の狭い許し: stdlib ・相対 import ・A3 ／ A4a1 の名前 ・削除 ・`os` の場所 ・`shutil` の場所 ・公開の面。"""
    relative, absolute = _imports_text(text)
    found = [("STDLIB", m) for m in sorted(absolute ^ P13_EXPORT_STDLIB)]
    found += [("RELATIVE", m) for m in sorted(set(relative) ^ SANCTIONED_P13_MODULES[PROJECTION_STORE])]
    found += [("A3_NAMES", "")] if _imported_names(text, "memory_store") != P13_EXPORT_A3_IMPORTS[PROJECTION_STORE] else []
    found += [("CONTRACT_NAMES", "")] if _imported_names(text, "projection_contract") != P13_EXPORT_CONTRACT_IMPORTS[PROJECTION_STORE] else []
    found += [("DELETION", site) for site in _deletion_sites(text) if site not in P13_EXPORT_UNLINK_SITES]
    found += [("UNLINK_CALLER", c) for c in sorted(_callers_of(text, "_unlink_if_owned") ^ P13_EXPORT_UNLINK_CALLERS)]
    sites = _os_call_sites(text)
    found += [("OS_SITE", name) for name in P13_EXPORT_OS_CALL_SITES if sites.get(name, set()) != P13_EXPORT_OS_CALL_SITES[name]]
    found += [("OS_ATTRIBUTE", name) for name in _os_attribute_violations(text)]
    found += [("SHUTIL", name) for name in sorted(set(_module_attribute_sites(text, "shutil")) - set(P13_EXPORT_SHUTIL_SITES))]
    found += [("SHUTIL_SITE", "disk_usage")] if _module_attribute_sites(text, "shutil").get("disk_usage") != P13_EXPORT_SHUTIL_SITES["disk_usage"] else []
    found += [("SHUTIL_IMPORT", "")] if any(isinstance(n, ast.ImportFrom) and n.module == "shutil" for n in ast.walk(ast.parse(text))) else []
    if _public_functions(text) != P13_EXPORT_STORE_FUNCTIONS or _class_surface(text, "ProjectionStore") != P13_EXPORT_STORE_METHODS:
        found.append(("SURFACE", ""))
    if _class_surface(text, "ExportLock") != {"owned", "release"} or _class_surface(text, "ExportLocks") != {"owned", "release"}:
        found.append(("LOCK_SURFACE", ""))                                                           # 奪取 ・移動 ・強制の解放の面は無い
    return found


def _export_build_violations(text: str) -> list:
    """orchestration だけ: filesystem ・動的実行の名前が無い ・store ／ lock ／ A3 ／ A4a1 の公開の面だけ。"""
    tree = ast.parse(text)
    relative, absolute = _imports_text(text)
    found = [("STDLIB", m) for m in sorted(absolute ^ P13_EXPORT_BUILD_STDLIB)]
    found += [("RELATIVE", m) for m in sorted(set(relative) ^ SANCTIONED_P13_MODULES[PROJECTION_BUILD])]
    found += [("A3_NAMES", "")] if _imported_names(text, "memory_store") != P13_EXPORT_A3_IMPORTS[PROJECTION_BUILD] else []
    found += [("CONTRACT_NAMES", "")] if _imported_names(text, "projection_contract") != P13_EXPORT_CONTRACT_IMPORTS[PROJECTION_BUILD] else []
    for node in ast.walk(tree):
        if isinstance(node, ast.Name) and node.id in P13_PROJECTION_FORBIDDEN_NAMES | {"stat", "eval", "exec"}:
            found.append(("NAME", node.id))
    uses = _object_uses(text, "store")
    found += [("STORE_USE", u) for u in sorted(uses ^ P13_EXPORT_BUILD_STORE_USES)]
    found += [("LOCK_USE", u) for u in sorted(_object_uses(text, "locks") - {"release"})]
    if _public_functions(text) != P13_EXPORT_BUILD_FUNCTIONS:
        found.append(("SURFACE", ""))
    found += [("A3_WRITE", n) for n in ("acquire_writer_lock", "publish_generation", "record_attempt", "preserve_interrupted_staging",
                                        "preserve_publication_pointer") if n in text]
    return found


def test_p13_a4b_the_accepted_a4a1_a4a_a3_a2a_and_a1_runtime_is_object_identical_to_the_anchors_in_head_index_and_worktree() -> None:
    assert _git("merge-base", "--is-ancestor", P13_A4A1, "HEAD") == ""
    for anchor, runtime in ((P13_A4A1, PHASE13_A4A1_RUNTIME), (P13_A4A1, PHASE13_A4A_RUNTIME), (P13_A4A1, PHASE13_A3_RUNTIME),
                            (P13_A4A1, PHASE13_A2A_RUNTIME), (P13_A4A1, PHASE13_A1_RUNTIME), (P13_A4A, PHASE13_A4A_RUNTIME),
                            (P13_A3, PHASE13_A3_RUNTIME), (P13_A2A, PHASE13_A2A_RUNTIME), (P13_A1, PHASE13_A1_RUNTIME)):
        anchored = _blobs(anchor, runtime)
        assert set(anchored) == set(runtime), anchor
        assert _blobs("HEAD", runtime) == anchored, anchor                                           # commit 済みの修正は無い
        index = {line.split("\t", 1)[1]: line.split()[1] for line in _git("ls-files", "-s", "--", *runtime).splitlines()}
        assert index == anchored, anchor                                                             # index の修正は無い
        worktree = {path: _git_blob_of((REPO_ROOT / path).read_bytes()) for path in runtime}
        assert worktree == anchored, anchor                                                          # 作業木の修正は無い
    assert _blobs(P13_A4A1, PHASE13_A4A1_RUNTIME) == {CONTRACT_MODULE: "06066a58e3304df1442d5ea7b903849feb1ac2e4"}   # 受理した A4a1 の blob
    assert _blobs(P13_A4A1, PHASE13_A4A_RUNTIME) == {PROJECTION_MODULE: "04bdabf2e24ddb9e8175b941b8980fcf4781fb73"}  # 受理した A4a の blob
    assert not _git("ls-tree", P13_A4A1, "--", *PHASE13_A4B_RUNTIME).strip()                         # A4b の file は anchor に無かった
    added = {("A", p) for p in PHASE13_A4B_RUNTIME}
    assert _changes("--name-status", P13_A4A1, "HEAD", "--", "src") <= added                         # A4a1 以後の src は A4b の追加だけ
    assert _changes("--cached", "--name-status", P13_A4A1, "--", "src") <= added


def test_p13_a4b_only_the_export_store_holds_the_second_narrow_filesystem_authority() -> None:
    store = (REPO_ROOT / PROJECTION_STORE).read_text(encoding="utf-8")
    assert _export_store_violations(store) == []
    assert _import_violations(PROJECTION_STORE, store) == [] and _guard_violations(PROJECTION_STORE, store) == []
    assert _deletion_sites(store) == P13_EXPORT_UNLINK_SITES                                         # 削除は所有した lock の解放の 1 箇所だけ
    body = next(n for n in ast.walk(ast.parse(store)) if isinstance(n, ast.FunctionDef) and n.name == "_unlink_if_owned")
    calls = sorted((n.lineno, n.col_offset, n.func.id) for n in ast.walk(body) if isinstance(n, ast.Call) and isinstance(n.func, ast.Name))
    assert calls[0][2] == "_owned"                                                                   # 所有の検証が先
    memory_users = {n.name for n in ast.walk(ast.parse(store)) if isinstance(n, ast.FunctionDef) and any(
        isinstance(c, ast.Name) and c.id == "MEMORY_CHILD" for c in ast.walk(n))}
    assert memory_users == {"memory_location", "_verify_private", "initialize_private_root"}         # A3 の root は位置を渡す ・在るかを見るだけ
    literals = {n.value for n in ast.walk(ast.parse(store)) if isinstance(n, ast.Constant) and isinstance(n.value, str)}
    assert not literals & {"notes", "workspace.json", "plugins", "data.json", "archive", "trash", ".trash"}   # 人の note ・plugin の data は名指ししない
    for path in PHASE13_RUNTIME:
        text = (REPO_ROOT / path).read_text(encoding="utf-8")
        if path in (STORE_MODULE, PROJECTION_STORE):
            continue
        assert "os" not in _imports_text(text)[1] and "shutil" not in _imports_text(text)[1] and _deletion_sites(text) == [], path
    assert SANCTIONED_P13_EXTRA_STDLIB[STORE_MODULE] == {"os", "stat"} and P13_OS_CALL_SITES["replace"] == {"_publish_pointer"}   # A3 は不変
    assert "memory_projection" not in store and "memory_projection" not in (REPO_ROOT / PROJECTION_BUILD).read_text(encoding="utf-8")


def test_p13_a4b_the_build_is_orchestration_only_over_the_public_store_a3_and_a4a1_surfaces() -> None:
    build = (REPO_ROOT / PROJECTION_BUILD).read_text(encoding="utf-8")
    assert _export_build_violations(build) == []
    assert _import_violations(PROJECTION_BUILD, build) == [] and _guard_violations(PROJECTION_BUILD, build) == []
    assert _deletion_sites(build) == [] and _os_call_sites(build) == {}
    for allowances in (P13_NAME_ALLOWANCES, P13_WORD_ALLOWANCES, SANCTIONED_P13_EXTRA_STDLIB, SANCTIONED_P13_P10_IMPORTERS):
        assert PROJECTION_BUILD not in allowances                                                     # file ごとの許しは無い
    assert not any(name.startswith("_") for name in _object_uses(build, "store"))                    # store の private な method は使わない
    assert _callers_of(build, "check_recovery_proposal") == {"_checked_plan"}                         # 自動の遷移は全てこの検査を通る
    assert _callers_of(build, "check_preservation_proposal") == {"preserve"}                          # 明示の保存は全てこの検査を通る
    assert _callers_of(build, "_same") == {"publish", "preserve"} and _callers_of(build, "_predict") == {"publish", "preserve"}
    assert dict(SANCTIONED_P13_P10_IMPORTERS) == {ADAPTER: SANCTIONED_P13_P10_IMPORTS}                # importer の許可は不変
    assert not any("market_memory" in module for module in runtime_closure())                      # 本番の閉包の外
    from src.intelligence.market_memory.projection_contract import ProposedAction
    assert {a.value for a in ProposedAction} == {"NONE", "PREPARE_INTENT", "RECORD_PRIVATE_BINDING", "STAGE_VERSION", "CONTINUE_STAGING",
                                                 "MOVE_STAGED_TO_VERSION", "REPLACE_POINTER", "RECORD_COMPLETION", "PRESERVE_STAGING",
                                                 "PRESERVE_EMPTY_RESERVATION", "HOLD"}                # A4b は新しい回復の action を足さない


def test_p13_a4b_the_scan_evidence_uses_exactly_the_frozen_approved_pattern_table_and_scanner() -> None:
    from src.intelligence.market_memory import memory_projection as frozen
    from src.intelligence.market_memory import projection_build as build
    from src.intelligence.market_memory import projection_contract as contract
    assert build.SCAN_PATTERNS == frozen.PRIVATE_SHAPE_PATTERNS and len(build.SCAN_PATTERNS) == 18          # 写しは凍結の表と完全一致（識別子 ・正規表現 ・順）
    assert contract.scan_private_shapes is frozen.scan_private_shapes is build.scan_private_shapes         # 承認した 1 つの走査器
    assert [label for label, _ in build.SCAN_PATTERNS] == [label for label, _ in frozen.PRIVATE_SHAPE_PATTERNS]
    assert build.scan_rules_digest() == hashlib.sha256(("p13.projection_scan_rules.v1\0" + json.dumps(
        {"scan_rules_version": build.SCAN_RULES_VERSION, "projection_rules_version": contract.CONTRACT_RULES_VERSION,
         "patterns": [list(pair) for pair in frozen.PRIVATE_SHAPE_PATTERNS]}, sort_keys=True, separators=(",", ":"),
        ensure_ascii=False)).encode("utf-8")).hexdigest()                                                    # 規則の digest は凍結の表から再計算できる
    altered = (build.SCAN_PATTERNS[0], ("BACKSLASH", r"[/]"), *build.SCAN_PATTERNS[2:])
    assert altered != frozen.PRIVATE_SHAPE_PATTERNS                                                          # negative control: 正規表現の変更
    assert build.SCAN_PATTERNS[:-1] != frozen.PRIVATE_SHAPE_PATTERNS                                         # pattern の欠落
    text = (REPO_ROOT / PROJECTION_BUILD).read_text(encoding="utf-8")
    assert _callers_of(text, "scan_private_shapes") == {"_pattern_counts"}                                  # 実行の時に file ごとに照らす


def test_p13_a4b_negative_controls_reject_widened_io_deletion_bypass_reuse_blob_mutation_and_registry_drift() -> None:
    store = (REPO_ROOT / PROJECTION_STORE).read_text(encoding="utf-8")
    build = (REPO_ROOT / PROJECTION_BUILD).read_text(encoding="utf-8")
    kinds = lambda found: {kind for kind, _ in found}                                               # noqa: E731
    assert "DELETION" in kinds(_export_store_violations(store + "\n\ndef cleanup(location):\n    os.rmdir(location)\n"))
    assert "SHUTIL" in kinds(_export_store_violations(store + "\n\ndef cleanup(location):\n    shutil.rmtree(location)\n"))
    assert "SHUTIL_SITE" in kinds(_export_store_violations(store + "\n\ndef peek(location):\n    return shutil.disk_usage(location)\n"))
    assert "SHUTIL_IMPORT" in kinds(_export_store_violations(store + "\nfrom shutil import copyfile\n"))
    assert "OS_SITE" in kinds(_export_store_violations(store + "\n\ndef overwrite(a, b):\n    os.replace(a, b)\n"))
    assert "OS_SITE" in kinds(_export_store_violations(store + "\n\ndef sneak(a, b):\n    os.rename(a, b)\n"))
    assert "OS_SITE" in kinds(_export_store_violations(store + "\n\ndef walk(a):\n    return os.listdir(a)\n"))
    assert "OS_ATTRIBUTE" in kinds(_export_store_violations(store + "\n\ndef walk(a):\n    return os.walk(a)\n"))
    assert "UNLINK_CALLER" in kinds(_export_store_violations(store + "\n\ndef drop(a, i, d):\n    return _unlink_if_owned(a, i, d)\n"))
    assert "SURFACE" in kinds(_export_store_violations(store + "\n\ndef take_over_lock(store):\n    return store\n"))
    takeover = store.replace("    def owned(self) -> bool:\n        return self._release_code is None",
                             "    def force_release(self) -> None:\n        pass\n\n    def owned(self) -> bool:\n        return self._release_code is None", 1)
    assert takeover != store and "LOCK_SURFACE" in kinds(_export_store_violations(takeover))       # lock の奪取の面
    assert "CONTRACT_NAMES" in kinds(_export_store_violations(store.replace("POINTER_NOTE_NAME, PRESERVE_AREA_RESERVATION,",
                                                                            "POINTER_NOTE_NAME, PRESERVE_AREA_RESERVATION, classify_publication,", 1)))
    assert ("STDLIB", "os") in _export_build_violations(build + "\nimport os\n")                     # build の filesystem
    assert ("STDLIB", "os") in _import_violations(PROJECTION_BUILD, build + "\nimport os\n")
    assert ("NAME", "open") in _guard_violations(PROJECTION_BUILD, build + "\ndef sneak(x):\n    return open(x)\n")
    assert ("STORE_USE", "_generated") in _export_build_violations(build + "\ndef sneak(store):\n    return store._generated()\n")
    assert ("LOCK_USE", "_vault") in _export_build_violations(build + "\ndef sneak(locks):\n    return locks._vault\n")
    assert "RELATIVE" in kinds(_export_build_violations(build + "\nfrom .memory_projection import render_projection\n"))   # 0.1.0 の model
    assert "A3_WRITE" in kinds(_export_build_violations(build + "\ndef sneak(memory):\n    return memory.publish_generation\n"))
    bypass = build.replace("return check_recovery_proposal(observed.observation, action, target=self.target)", "return classification.transition", 1)
    assert bypass != build and _callers_of(bypass, "check_recovery_proposal") != {"_checked_plan"}  # 自動の検査の迂回
    assert ("NAME", "getattr") in _export_build_violations(build + "\ndef sneak(x):\n    return getattr(x, 'y')\n")
    for anchor, runtime in ((P13_A4A1, PHASE13_A4A1_RUNTIME), (P13_A4A, PHASE13_A4A_RUNTIME), (P13_A3, PHASE13_A3_RUNTIME),
                            (P13_A2A, PHASE13_A2A_RUNTIME), (P13_A1, PHASE13_A1_RUNTIME)):
        anchored = _blobs(anchor, runtime)
        for path in runtime:
            assert _git_blob_of((REPO_ROOT / path).read_bytes() + b"\n") != anchored[path], path      # 1 byte の変化で pin が外れる
    for status in ("A", "??", "M"):
        assert not is_phase13_addition(status, f"{PHASE13_PACKAGE}/projection_cleanup.py")           # 未登録の runtime
        assert not is_phase13_addition(status, f"{PHASE13_PACKAGE}/obsidian_vault.py")
    for path in PHASE13_A4B_RUNTIME:
        assert is_phase13_addition("A", path) and not is_phase13_addition("M", path)                  # 修正は決して認めない
    assert {**SANCTIONED_P13_P10_IMPORTERS, PROJECTION_BUILD: SANCTIONED_P13_P10_IMPORTS} != dict(SANCTIONED_P13_P10_IMPORTERS)
    drifted = (
        [*PHASE13_RUNTIME_AUTHORIZATION[:5], ("P13-A4b", P13_A4A, PHASE13_A4B_RUNTIME, A4B_DOC)],          # anchor の drift
        [*PHASE13_RUNTIME_AUTHORIZATION[:5], ("P13-A4b", P13_A4A1, PHASE13_A4B_RUNTIME[:1], A4B_DOC)],     # path の欠落
        [*PHASE13_RUNTIME_AUTHORIZATION, ("P13-A5", P13_A4A1, (f"{PHASE13_PACKAGE}/projection_cleanup.py",), A4B_DOC)],
    )
    for authorization in drifted:
        payload = {"runtime": list(PHASE13_RUNTIME), "tests": list(PHASE13_TESTS), "docs": list(PHASE13_DOCS), "package": PHASE13_PACKAGE,
                   "base": P13_BASE, "authorization": [[g, a, list(p), d] for g, a, p, d in authorization]}
        canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        assert hashlib.sha256(("p13.registry.v1\0" + canonical).encode("utf-8")).hexdigest() != P13_REGISTRY_DIGEST


def test_p13_a4b_the_export_record_states_the_contract_limits_and_holds_no_private_values() -> None:
    text = (REPO_ROOT / A4B_DOC).read_text(encoding="utf-8")
    for needle in ("P13-A4b", PROJECTION_STORE, PROJECTION_BUILD, "P13_A4A1", P13_A4A1, "P13_A4A", "P13_A3", P13_A3, "P13_A2A", P13_A2A,
                   "P13_A1", P13_A1, "Option C", ".p13-private-root", ".p13-vault-root", "generated/", "人が置く", "人の note は読まない",
                   "ReadStatus.VERIFIED", "要求した generation ／ manifest が A3 の検証済みの公開と一致", "SOURCE_READ_ATTESTATION",
                   "A4A1_RECHECKED_RECORD_BYTES_STORE_READ_NOT_ATTESTED", "PrivateBinding", "scan.json", "source.json", "FAILED",
                   "RECORD_PRIVATE_BINDING", "成功の NO_CHANGE を返さない", "CONTINUE_STAGING", "PRESERVE_STAGING", "PRESERVE_EMPTY_RESERVATION",
                   "STAGING_TORN", "VERSION_RESERVED_EMPTY", "STAGING_TAMPERED", "check_recovery_proposal", "check_preservation_proposal",
                   "新しい回復の action", "I5", "2 つの writer lock", "奪取", "設計だけ", "shutil.disk_usage", "_free_bytes", "_unlink_if_owned",
                   "64", "256 MiB", "64 MiB", "4096", "512 MiB", "LIMIT_LOOSENED", "CAPACITY_UNVERIFIED", "CAPACITY_EXCEEDED",
                   "網羅ではない", "alwaysUpdateLinks", "bare な note の名前の衝突", "衝突の無い", "P13-A5", "TOCTOU", "NTFS", "ACL",
                   "TARGET_CONFLICTS_WITH_OPEN_INTENT", "abort_for", "前の有効な版", "合成の", "B-track は HOLD", "推論は防がない",
                   "scan_rules_digest", "pattern_counts", "承認した全ての 18 の pattern の識別子", "SCAN_PATTERNS", "SCAN_RULES_DRIFT",
                   "完全一致（識別子 ・正規表現 ・順）", "毎回の観測で走査の証拠を完全に再検証する", "FAILED の証拠の 3 つの区別", "FAIL CLOSED",
                   "byte が同じものも", "FAILURE_NOT_RECORDED", "記録済みとは言わない"):
        assert needle in text, needle
    for banned in ("P13 は完了", "Phase 13 は完了", "A4 は完了", "A4b は完了", "署名済み", "最新の", "推奨する銘柄", "D:\\", "0.0.0.0",
                   "http://", "https://", "衝突は無い", "同期を防ぐ", "不可分を保証する", "Windows で検証済み", "0.1.0 の model を import する"):
        assert banned not in text, banned
    assert not re.search(r"\b(?:is|are|was|were|been)\s+(?:digitally\s+|cryptographically\s+)?signed\b", text, re.IGNORECASE)
    for pattern in PRIVATE_PATTERNS:
        assert not re.search(pattern, text), pattern
    from src.intelligence.market_memory import projection_build as build
    from src.intelligence.market_memory import projection_store as store
    for version in (store.LOCK_SCHEMA_VERSION, store.PRIVATE_ROOT_SCHEMA_VERSION, store.VAULT_ROOT_SCHEMA_VERSION, build.SCAN_SCHEMA_VERSION,
                    build.SOURCE_READ_SCHEMA_VERSION, build.FAILURE_SCHEMA_VERSION, build.SOURCE_READ_ATTESTATION, build.SCAN_PROCEDURE,
                    build.SCAN_RULES_VERSION, build.SCAN_RULES_DOMAIN, build.SCAN_DOMAIN):
        assert version in text, version


# ================================================ P13-A5-0R: Windows の検証の計画の記録（文書だけ ・実行を承認しない）


A5_W_CASES = tuple(f"W-{n:02d}" for n in range(1, 21))
A5_T_CASES = tuple(f"T-{n:02d}" for n in range(1, 7))
A5_O_CASES = tuple(f"O-{n:02d}" for n in range(1, 7))
#: W の A6 の分類。ここに無い W は BLOCKING のまま（弱めると落ちる）。W-20 は S2（実の source）で決定まで止める
A5_W_NOT_BLOCKING = {"W-04": "RECORD_ONLY", "W-05": "CONDITIONAL", "W-11": "RECORD_ONLY", "W-20": "DECISION_REQUIRED"}
#: A6 の条件つきの主張の状態（別々 ・弱めると落ちる）
A5_A6_CLAIMS = {"C-01": "SYNTHETIC_ONLY", "C-02": "CONDITIONAL", "C-03": "UNSUPPORTED", "C-04": "CONDITIONAL", "C-05": "CONDITIONAL",
                "C-06": "UNSUPPORTED", "C-07": "UNSUPPORTED", "C-08": "UNSUPPORTED", "C-09": "DECISION_REQUIRED", "C-10": "OUT_OF_SCOPE",
                "C-11": "OUT_OF_SCOPE", "C-12": "OUT_OF_SCOPE", "C-13": "UNSUPPORTED", "C-14": "DECISION_REQUIRED"}
A5_REQUIRED = ("本記録は実行を承認しない", "Windows の結果は無い", "Windows の検証は A6 の前", "P12.5 の closeout §5 の 6", "P12.5-A0 §10",
               "f6145ac2902ab95ec20affecb11300d6176b9d5a", "A5-T ・A5-W ・A6 は HOLD", "helper の作成 ・実行は HOLD",
               "実の source の検証の義務は残す", "S2 は所有者の別の承認と privacy の審査まで HOLD", "監督の明示の決定",
               "提案した初期の対象であり検証済みの能力ではない", "受理した POSIX の基準は変えない", "42 の mutation の点", "252 の場合",
               "Windows の mutation の数は UNKNOWN", "期待の数を失敗に合わせて書き換えない", "注入した例外", "実際の process の終了",
               "process の生存は lock から証明できない", "再起動だけでは片付けを承認しない", "lock の byte が lock の record として読める",
               "file の種類が正規の file", "`st_nlink` が 1", "before の manifest", "after の manifest", "介入ごとの明示の承認",
               "quarantine", "（消さない）", "無期限の HOLD", "sha256", "Linux の合成の試験でだけ安全と確かめた",
               "A3 の hard link の振る舞いは未解決の境界の懸念", "無害な例外として受け入れていない", "実の root への書き込み",
               "lock の盲目的な除去", "stale lock の奪取", "自動の片付け", "破壊的な試験", "同期 ・plugin の拒否の規則を弱めること",
               "同期 ・plugin の拒否の規則は弱めない", "product の提案であり既存の契約の検査の免除ではない", "監督の明示の scope の決定",
               "実の vault への export は支持しない", "除外は凍結を自動では認めない", "Market Memory v1 は凍結していない")
A5_BANNED = ("A5_PASS", "A5 PASS", "A5 は PASS", "A5 は完了", "A6 CLOSED", "A6 は CLOSED", "A6 は完了", "Market Memory v1 は凍結した",
             "Market Memory v1 を凍結した", "Windows で検証済み", "実機で検証した", "実機で確認した", "Windows で確認した", "検証に合格した",
             "helper を作成した", "helper を実行した", "実行を承認する", "S2 は承認済み", "拒否を弱める", "拒否を緩める", "拒否を無効にする",
             "同期を許可する", "plugin を許可する", "P13 は完了", "Phase 13 は完了", "最新の", "署名済み", "http://", "https://", "D:\\",
             "0.0.0.0")
A5_BANNED_PATTERNS = (r"\b[A-Z][A-Z0-9_]{2,}=(?:PASS|PASSED|FAIL|FAILED|OK|TRUE|FALSE|YES|NO|\d+)\b",          # 捏造の結果の行
                      r"\b[WTOC]-\d{2}\s*(?:=|:|は)\s*(?:PASS|PASSED|FAIL|合格|成功)",                          # 項目の結果の主張
                      r"(?:A5-0R|A5-T|A5-W|A6|S2|helper)[^\n|]{0,8}=\s*GO\b",                                  # 実行の権限
                      r"\b(?:jq|p\d+)_[a-z0-9]+_(?:private|work)\b", r"\\\\[A-Za-z0-9.-]+\\")                  # private な root ・UNC の host


#: 節ごとに在るべき記述（他の節に同じ語が在っても、その節から消えれば落ちる）
A5_SECTION_REQUIRED = {
    "## 6. 人の回復の手順": ("process の生存は lock から証明できない", "再起動だけでは片付けを承認しない", "lock の byte が lock の record として読める",
                        "file の種類が正規の file", "`st_nlink` が 1", "before の manifest", "after の manifest", "介入ごとの明示の承認",
                        "quarantine", "（消さない）", "lock の盲目的な除去 ・stale lock の奪取は無い", "無期限の HOLD",
                        "Linux の合成の試験でだけ安全と確かめた"),
    "## 7. 実の source と合成の source": ("実の source の検証の義務は残す", "S2 は所有者の別の承認と privacy の審査まで HOLD"),
    "## 8. 任意の Obsidian の track": ("product の提案であり既存の契約の検査の免除ではない", "監督の明示の scope の決定", "実の vault への export は支持しない",
                                  "同期 ・plugin の拒否の規則は弱めない"),
    "## 12. 禁止": ("実の root への書き込み", "lock の盲目的な除去", "stale lock の奪取", "自動の片付け", "破壊的な試験",
                  "同期 ・plugin の拒否の規則を弱めること", "期待の数を失敗に合わせて書き換えること"),
}


def _a5_section(text: str, heading: str) -> str:
    start = text.find("\n" + heading)
    if start < 0:
        return ""
    end = text.find("\n## ", start + 1)
    return text[start:] if end < 0 else text[start:end]


def _a5_rows(text: str, prefix: str) -> dict:
    rows = {}
    for line in text.splitlines():
        match = re.match(r"^\| (" + prefix + r"-\d{2}) \|(.*)\|$", line)
        if match:
            rows.setdefault(match.group(1), []).append([cell.strip() for cell in match.group(2).split("|")])
    return rows


def _a5_plan_violations(text: str) -> list:
    """Windows の検証の計画の記録の違反（空なら適合）。"""
    found = []
    w_rows = _a5_rows(text, "W")
    if tuple(w_rows) != A5_W_CASES or any(len(rows) != 1 for rows in w_rows.values()):
        found.append(("W_CASES", tuple(w_rows)))
    for case, rows in w_rows.items():
        cells = rows[0]
        if len(cells) != 8 or any(not cell or cell in ("—", "-") for cell in cells):
            found.append(("W_CELLS", case))
            continue
        if "§" not in cells[0]:
            found.append(("W_CONTRACT_REF", case))
        if cells[2] != ("S2" if case == "W-20" else "S1"):
            found.append(("W_ENVIRONMENT", case))
        if cells[7] != A5_W_NOT_BLOCKING.get(case, "BLOCKING"):
            found.append(("W_A6_CLASS", case))
    for prefix, cases in (("T", A5_T_CASES), ("O", A5_O_CASES)):
        rows = _a5_rows(text, prefix)
        if tuple(rows) != cases or any(len(r) != 1 or any(not cell for cell in r[0]) for r in rows.values()):
            found.append((prefix + "_CASES", tuple(rows)))
    claims = {case: rows[0][1] if len(rows) == 1 and len(rows[0]) == 3 else None for case, rows in _a5_rows(text, "C").items()}
    if claims != A5_A6_CLAIMS:
        found.append(("A6_CLAIMS", tuple(sorted(set(claims.items()) ^ set(A5_A6_CLAIMS.items())))))
    found += [("MISSING", needle) for needle in A5_REQUIRED if needle not in text]
    for heading, needles in A5_SECTION_REQUIRED.items():
        section = _a5_section(text, heading)
        found += [("SECTION", heading, needle) for needle in needles if needle not in section]
    found += [("BANNED", banned) for banned in A5_BANNED if banned in text]
    found += [("PATTERN", pattern) for pattern in A5_BANNED_PATTERNS + PRIVATE_PATTERNS if re.search(pattern, text)]
    if re.search(r"\b(?:is|are|was|were|been)\s+(?:digitally\s+|cryptographically\s+)?signed\b", text, re.IGNORECASE):
        found.append(("SIGNED", "claim"))
    return found


def test_p13_a5_0r_the_windows_validation_plan_is_a_guarded_documentation_only_record() -> None:
    text = (REPO_ROOT / A5_PLAN_DOC).read_text(encoding="utf-8")
    assert _a5_plan_violations(text) == []
    assert A5_PLAN_DOC in PHASE13_DOCS and PHASE13_DOCS.index(A5T_RECORD_DOC) == PHASE13_DOCS.index(A5_PLAN_DOC) + 1   # 確立した文書の registry で登録（A5-T の記録の直前）
    assert not any(gate.startswith("P13-A5") or gate.startswith("P13-A6") for gate, *_ in PHASE13_RUNTIME_AUTHORIZATION)   # 実行 ・runtime の認可は無い
    assert all(doc != A5_PLAN_DOC for *_, doc in PHASE13_RUNTIME_AUTHORIZATION)
    assert len(PHASE13_RUNTIME) == 12 and not any("cleanup" in p or "recovery" in p or "windows" in p for p in PHASE13_RUNTIME)


def test_p13_a5_0r_negative_controls_reject_weakened_or_fabricated_plans() -> None:
    text = (REPO_ROOT / A5_PLAN_DOC).read_text(encoding="utf-8")
    lines = text.splitlines(keepends=True)
    row = {case: next(line for line in lines if line.startswith(f"| {case} |")) for case in (*A5_W_CASES, "T-03", "C-07")}
    stop_cell = row["W-02"].rstrip("\n").split("|")[8]
    mutated = {
        "missing_case": text.replace(row["W-07"], ""),                                                # 必須の Windows の場合の欠落
        "duplicated_case": text.replace(row["W-07"], row["W-07"] * 2),
        "blocking_weakened": text.replace(row["W-06"], row["W-06"].replace("| BLOCKING |", "| RECORD_ONLY |")),
        "stop_removed": text.replace(row["W-02"], row["W-02"].replace(stop_cell, " — ")),
        "contract_ref_removed": text.replace(row["W-09"], row["W-09"].replace("A3 §6 ・A4b §1 ・§11", "A3 ・A4b")),
        "real_source_downgraded": text.replace(row["W-20"], row["W-20"].replace("| S2 |", "| S1 |")),
        "real_source_unblocked": text.replace(row["W-20"], row["W-20"].replace("| DECISION_REQUIRED |", "| BLOCKING |")),
        "real_source_approval_omitted": text.replace("S2 は所有者の別の承認と privacy の審査まで HOLD", "S2 は後で行う"),
        "portability_case_missing": text.replace(row["T-03"], ""),
        "claim_weakened": text.replace(row["C-07"], row["C-07"].replace("| UNSUPPORTED |", "| CONDITIONAL |")),
        "refusal_weakened": text.replace("同期 ・plugin の拒否の規則は弱めない", "同期 ・plugin の拒否を緩める"),
        "a5_pass_claim": text + "\nA5_PASS\n",
        "a6_closed_claim": text + "\nA6 は CLOSED。\n",
        "fabricated_report_line": text + "\nINO_STABLE=TRUE\n",
        "fabricated_case_result": text + "\nW-01: PASS\n",
        "fabricated_windows_claim": text + "\nNTFS の挙動は Windows で検証済み。\n",
        "execution_authority": text + "\nA5-W = GO\n",
        "helper_authority": text + "\nhelper を実行した。\n",
        "private_path": text + "\n" + "Z:" + "\\p99_a9_private\n",
        "private_root_name": text + "\np99_z9_private\n",
        "private_identifier": text + "\np9wat_0123\n",
        "reboot_authorizes_cleanup": text.replace("再起動だけでは片付けを承認しない", "再起動の後は片付けてよい"),
        "posix_baseline_changed": text.replace("受理した POSIX の基準は変えない", "POSIX の基準は Windows に合わせる"),
        "obsidian_waiver": text.replace("product の提案であり既存の契約の検査の免除ではない", "既存の検査の免除"),
        "hard_link_accepted": text.replace("A3 の hard link の振る舞いは未解決の境界の懸念", "A3 の hard link は無害"),
        "prohibition_removed": text.replace("- lock の盲目的な除去 ・stale lock の奪取 ・自動の片付け ・証拠 ／ 版の削除 ・編集。\n", ""),
        "runbook_lock_rule_removed": text.replace("lock の盲目的な除去 ・stale lock の奪取は無い", "lock は状況に応じて扱う"),
        "runbook_section_missing": text.replace("## 6. 人の回復の手順", "## 6. 回復"),
    }
    for name, candidate in mutated.items():
        assert candidate != text, name
        assert _a5_plan_violations(candidate), name                                                  # どの改変も guard が落とす


# ================================================ P13-A5-T: Windows の特性の記録（文書だけ）


#: 受理した T-02 ・T-03 の数 ・証拠の identity ・主張しないこと（どれが消えても落ちる）
A5T_REQUIRED = ("本記録は実行を承認しない", "P13-A5 は受理していない", "Market Memory v1 は凍結していない",
                "f503e9280f60cce1dc7cc28cc6c39575e1721a1e", "p13a5-t2b-recorder:3", "p13a5-t2c-runner:6",
                "bbc6880fd9524a3f39aee0a1de4f0bde3019785f198141f6dd11212cd4cf3d97",
                "b5b0b12ceae016569a5f284ee2174174053fb83f151b738275e834843b49d398",
                "a93a996c57823182fe8d03f1759517bd95b383479e704f8bbba01af695bdc2cd",
                "9bd75714621bcd0b39f2effe80abd6e942bf394fa34ee73eb2a482410af186e2",
                "d0fb5f5010aa5a211ec2dc53c48ede70977d749ba6e2a4f451897e2ab814b57e",
                "85dab58a6004b9196ad831998abf6c7a1ed77dd52347c81678507463a6819e76",
                "cf2af47b70ba0a50b693d8be1c463305291dab9ae5f3ca02e823311af0dd029f",
                "9e8d408dff076061d716e824912a932bc1186fa99cdf0e4d1d9028a261b51379",
                "593e9e53b1f3ef0817d48d7d249c8bb91334f41494acdcea7c1bcbfd0fe7d04c",
                "Windows の native の mutation の点は 41", "POSIX の予約の `mkdir`", "選んだ場合 246 ・試みた場合 246 ・VALID 246",
                "A=142 ・H=9 ・M=95 ・F=0", "1 つ目の故障は 246 の場合の全てで観測した", "2 つ目の故障は 72 の場合で観測した",
                "12 の場合は確かめた設計どおりの lock の在る拒否で 2 つ目の故障に届かない", "E3 の免除は 12", "必須の manifest は 996",
                "Windows と POSIX の分類の差は 9", "受理した POSIX の基準（42 の点 ・252 の場合）は変えない", "注入した例外だけ",
                "process の中の audit hook は OS の水準の閉じ込めではない", "残りの片付け ・lock の削除はしていない")
#: 監督の必須の R1 の注記（原文）
A5T_R1_NOTE = ("B2-W38, A2-W38, T2-W38, A2-W40 and A2-W41 remain class A under frozen rules, but retain a writer lock.",
               "Data convergence does not imply operational readiness for the next publication.",
               "An authorized human procedure is required to resolve the lock safely.",
               "CLASS_EVIDENCE=VALID certifies evidence validity, not next-publication readiness.",
               "SECOND_FAULT_HANDLED and INVARIANT_AUTO_SINGLE_STEP are reporting-only.",
               "POSIX priors are historical comparisons, not verified native Windows outcomes.")
#: 節ごとに在るべき記述（他の節に同じ語が在っても、その節から消えれば落ちる）
A5T_SECTION_REQUIRED = {
    "## 5. R1 の解釈": (*A5T_R1_NOTE, "凍結の規則の下で class A のままだが、writer lock を保持する",
                      "data の収束は次の公開の運用の準備を意味しない", "lock を安全に解くには、承認された人の手順が要る",
                      "`CLASS_EVIDENCE=VALID` は証拠の妥当性を証し、次の公開の準備を証さない",
                      "`SECOND_FAULT_HANDLED` と `INVARIANT_AUTO_SINGLE_STEP` は報告だけ",
                      "POSIX の先行値は歴史の比較であり、Windows で検証した native の結果ではない",
                      "5 つの場合で次の公開は試していない", "凍結の分類は黙って変えない", "lock は消さない"),
    "## 7. 状態": ("P13-A5 は受理していない", "Market Memory v1 は凍結していない", "本記録は実行を承認しない"),
    "## 9. 禁止と承認の範囲": ("product の機能 ・runtime の振る舞いは変わらない", "lock の削除", "凍結の分類の黙った変更",
                        "監督の別の明示の承認が要る"),
}
#: 群ごとの（場合 ・A ・H ・M ・F）
A5T_GROUPS = {"B1": ("41", "26", "2", "13", "0"), "A1": ("41", "26", "2", "13", "0"), "T1": ("41", "26", "2", "13", "0"),
              "B2": ("41", "20", "0", "21", "0"), "A2": ("41", "24", "3", "14", "0"), "T2": ("41", "20", "0", "21", "0"),
              "計": ("246", "142", "9", "95", "0")}
A5T_R1_CASES = ("B2-W38", "A2-W38", "T2-W38", "A2-W40", "A2-W41")
A5T_POSIX_DIFFS = {"B1-W31": "H→A", "T1-W31": "H→A", "B2-W31": "M→A", "A2-W31": "M→A", "T2-W31": "M→A", "B2-W32": "A→M",
                   "T2-W32": "A→M", "A2-W35": "A→M", "A2-W29": "H→A"}
A5T_STATUS = {"T-01": "OPEN / NOT EVIDENCED", "T-02": "CLOSED", "T-03": "CLOSED", "T-04": "PARTIAL", "T-05": "OPEN", "T-06": "OPEN",
              "A5-W": "NOT FORMALLY EXECUTED", "A6": "HOLD"}
A5T_BANNED = ("A5_PASS", "A5 PASS", "A5 は PASS", "A5 は完了", "P13-A5 を受理した", "P13-A5 は受理した", "P13-A5 は受理済み", "A6 CLOSED",
              "A6 は CLOSED", "A6 は完了", "A6 は PASS", "Market Memory v1 は凍結した", "Market Memory v1 を凍結した",
              "Market Memory v1 は凍結済み", "A5-W を実行した", "A5-W は実行した", "A5-W は完了", "A5-W は PASS", "次の公開の準備ができている",
              "次の公開の準備が整った", "次の公開に支障は無い", "lock を削除した", "lock を消した", "lock を除去した", "実行を承認する",
              "Windows で検証済み", "最新の", "署名済み", "http://", "https://", "D:\\", "0.0.0.0")
A5T_BANNED_PATTERNS = (r"\b(?:T-0\d|A5-W|A6|W-\d{2})\s*(?:=|:|は)\s*(?:PASS|PASSED|CLOSED|ACCEPTED|EXECUTED|合格|完了|受理|実行済み)",  # 完了の主張
                       r"(?:A5-T|A5-W|A6|T-05|T-06|helper|pytest|commit|push)[^\n|]{0,8}=\s*GO\b",                                # 実行の権限
                       r"\b(?:jq|p\d+)_[a-z0-9]+_(?:private|work)\b", r"\\\\[A-Za-z0-9.-]+\\")                                      # private な root ・UNC の host


def _a5t_table(text: str, heading: str, key: str) -> dict:
    rows = {}
    for line in _a5_section(text, heading).splitlines():
        match = re.match(r"^\| (" + key + r") \|(.*)\|$", line)
        if match:
            rows.setdefault(match.group(1), []).append([cell.strip() for cell in match.group(2).split("|")])
    return rows


def _a5t_record_violations(text: str) -> list:
    """Windows の特性の記録の違反（空なら適合）。"""
    found = []
    groups = _a5t_table(text, "## 4. T-03 の結果", r"[BAT][12]|計")
    if {g: tuple(r[0][2:]) if len(r) == 1 and len(r[0]) == 7 else None for g, r in groups.items()} != A5T_GROUPS:
        found.append(("GROUPS", tuple(groups)))
    r1 = _a5t_table(text, "## 5. R1 の解釈", r"[BAT][12]-W\d{2}")
    if tuple(r1) != A5T_R1_CASES or any(len(r) != 1 or len(r[0]) != 3 or r[0][0] != "A" or not r[0][2].endswith("writer lock を保持")
                                         for r in r1.values()):
        found.append(("R1", tuple(r1)))
    diffs = _a5t_table(text, "## 6. Windows と POSIX の分類の差", r"[BAT][12]-W\d{2}")
    if {case: r[0][0] if len(r) == 1 and len(r[0]) == 3 else None for case, r in diffs.items()} != A5T_POSIX_DIFFS:
        found.append(("POSIX_DIFFS", tuple(diffs)))
    status = _a5t_table(text, "## 7. 状態", r"T-0\d|A5-W|A6")
    if {item: r[0][0] if len(r) == 1 and len(r[0]) == 2 and r[0][1] else None for item, r in status.items()} != A5T_STATUS:
        found.append(("STATUS", tuple(status)))
    found += [("MISSING", needle) for needle in A5T_REQUIRED if needle not in text]
    for heading, needles in A5T_SECTION_REQUIRED.items():
        section = _a5_section(text, heading)
        found += [("SECTION", heading, needle) for needle in needles if needle not in section]
    found += [("BANNED", banned) for banned in A5T_BANNED if banned in text]
    found += [("PATTERN", pattern) for pattern in A5T_BANNED_PATTERNS + PRIVATE_PATTERNS if re.search(pattern, text)]
    if re.search(r"\b(?:is|are|was|were|been)\s+(?:digitally\s+|cryptographically\s+)?signed\b", text, re.IGNORECASE):
        found.append(("SIGNED", "claim"))
    return found


def test_p13_a5t_the_windows_characterization_record_is_a_guarded_documentation_only_record() -> None:
    text = (REPO_ROOT / A5T_RECORD_DOC).read_text(encoding="utf-8")
    assert _a5t_record_violations(text) == []
    assert A5T_RECORD_DOC in PHASE13_DOCS and PHASE13_DOCS.index(A5T_RECORD_DOC) == PHASE13_DOCS.index(A5_PLAN_DOC) + 1   # 計画の記録の直後に登録
    assert not any(gate.startswith("P13-A5") or gate.startswith("P13-A6") for gate, *_ in PHASE13_RUNTIME_AUTHORIZATION)   # 実行 ・runtime の認可は無い
    assert all(doc not in (A5_PLAN_DOC, A5T_RECORD_DOC) for *_, doc in PHASE13_RUNTIME_AUTHORIZATION)
    assert len(PHASE13_RUNTIME) == 12 and not any("cleanup" in p or "recovery" in p or "windows" in p for p in PHASE13_RUNTIME)
    rows = [tuple(int(v) for v in counts) for group, counts in A5T_GROUPS.items() if group != "計"]
    assert tuple(sum(column) for column in zip(*rows)) == tuple(int(v) for v in A5T_GROUPS["計"])   # 群の和は総数
    assert all(cases == a + h + m + f for cases, a, h, m, f in rows)                                 # 各群は A ・H ・M ・F で尽きる
    assert len(A5T_R1_CASES) == 5 and len(A5T_POSIX_DIFFS) == 9 and not set(A5T_R1_CASES) & set(A5T_POSIX_DIFFS)


def test_p13_a5t_negative_controls_reject_altered_or_overclaimed_records() -> None:
    text = (REPO_ROOT / A5T_RECORD_DOC).read_text(encoding="utf-8")
    lines = text.splitlines(keepends=True)
    row = {key: next(line for line in lines if line.startswith(f"| {key} |"))
           for key in ("B2", "計", *A5T_R1_CASES, "A2-W29", "T-01", "T-04", "T-05", "T-06", "A5-W", "A6")}
    mutated = {
        "altered_class_totals": text.replace("A=142 ・H=9 ・M=95 ・F=0", "A=143 ・H=9 ・M=94 ・F=0"),            # 数の改変
        "altered_group_row": text.replace(row["B2"], row["B2"].replace("| 20 | 0 | 21 |", "| 21 | 0 | 20 |")),
        "altered_total_row": text.replace(row["計"], row["計"].replace("| 142 |", "| 141 |")),
        "altered_valid_count": text.replace("VALID 246", "VALID 245"),
        "altered_mutation_points": text.replace("Windows の native の mutation の点は 41", "Windows の native の mutation の点は 42"),
        "altered_second_faults": text.replace("2 つ目の故障は 72 の場合で観測した", "2 つ目の故障は 84 の場合で観測した"),
        "altered_e3_exemptions": text.replace("E3 の免除は 12", "E3 の免除は 0"),
        "altered_manifests": text.replace("必須の manifest は 996", "必須の manifest は 984"),
        "altered_difference_count": text.replace("Windows と POSIX の分類の差は 9", "Windows と POSIX の分類の差は 8"),
        "posix_difference_removed": text.replace(row["A2-W29"], ""),
        "posix_reservation_unnoted": text.replace("POSIX の予約の `mkdir`", "POSIX の `mkdir`"),
        "evidence_identity_altered": text.replace("9bd75714621bcd0b", "9bd75714621bcd0c"),
        "r1_case_removed": text.replace(row["A2-W41"], ""),                                            # R1 の欠落 ／ 再分類
        "r1_case_reclassified": text.replace(row["B2-W38"], row["B2-W38"].replace("| A |", "| M |")),
        "r1_lock_dropped": text.replace(row["A2-W40"], row["A2-W40"].replace("vault の writer lock を保持", "lock は無い")),
        "r1_note_case_removed": text.replace("A2-W40 and A2-W41 remain class A", "A2-W40 remain class A"),
        "next_publication_warning_removed": text.replace(
            "Data convergence does not imply operational readiness for the next publication.\n", ""),
        "next_publication_warning_removed_ja": text.replace("data の収束は次の公開の運用の準備を意味しない", "data は収束した"),
        "class_evidence_overclaimed": text.replace("certifies evidence validity, not next-publication readiness",
                                                   "certifies next-publication readiness"),
        "human_procedure_removed": text.replace("An authorized human procedure is required to resolve the lock safely.\n", ""),
        "reporting_only_removed": text.replace("SECOND_FAULT_HANDLED and INVARIANT_AUTO_SINGLE_STEP are reporting-only.\n", ""),
        "posix_prior_promoted": text.replace("POSIX priors are historical comparisons, not verified native Windows outcomes.",
                                             "POSIX priors are verified native Windows outcomes."),
        "readiness_claim": text + "\n次の公開の準備ができている。\n",
        "full_a5_accepted": text.replace("P13-A5 は受理していない", "P13-A5 は受理した"),                  # 受理 ・凍結の偽りの主張
        "full_a5_pass_claim": text + "\nA5 PASS\n",
        "a6_closed_claim": text + "\nA6 は CLOSED。\n",
        "a6_status_closed": text.replace(row["A6"], row["A6"].replace("| HOLD |", "| CLOSED |")),
        "a6_authority": text + "\nA6 = GO\n",
        "market_memory_frozen": text + "\nMarket Memory v1 は凍結した。\n",
        "freeze_disclaimer_removed": text.replace("Market Memory v1 は凍結していない", "Market Memory v1 の凍結は近い"),
        "t01_closed": text.replace(row["T-01"], row["T-01"].replace("| OPEN / NOT EVIDENCED |", "| CLOSED |")),   # 残る T の項目の誤った完了
        "t04_closed": text.replace(row["T-04"], row["T-04"].replace("| PARTIAL |", "| CLOSED |")),
        "t05_closed": text.replace(row["T-05"], row["T-05"].replace("| OPEN |", "| CLOSED |")),
        "t06_closed": text.replace(row["T-06"], row["T-06"].replace("| OPEN |", "| CLOSED |")),
        "open_item_closed_claim": text + "\nT-06 は CLOSED。\n",
        "status_row_removed": text.replace(row["T-05"], ""),
        "a5w_status_executed": text.replace(row["A5-W"], row["A5-W"].replace("| NOT FORMALLY EXECUTED |", "| EXECUTED |")),  # A5-W の実行の主張
        "a5w_executed_claim": text + "\nA5-W を実行した。\n",
        "w_item_result_claim": text + "\nW-13: PASS\n",
        "execution_authority": text + "\nA5-W = GO\n",
        "lock_deleted_claim": text + "\nlock を削除した。\n",
        "section_heading_changed": text.replace("## 5. R1 の解釈", "## 5. R1"),
        "private_path": text + "\n" + "Z:" + "\\p99_a9_private\n",                                     # private な形
        "private_root_name": text + "\np99_z9_private\n",
        "private_identifier": text + "\np9wat_0123\n",
        "private_timestamp": text + "\n" + "2026-10-20" + "T08:25\n",
        "private_bare_number": text + "\n空きは " + "45362" + " MB\n",
        "private_user_profile": text + "\n" + "C:" + "\\Users\\someone\n",
    }
    for name, candidate in mutated.items():
        assert candidate != text, name
        assert _a5t_record_violations(candidate), name                                               # どの改変も guard が落とす


#: H0-D1: Home の情報の契約の記録（文書だけ ・実装の承認ではない）
H0_REQUIRED = ("本記録は実装を承認しない", "9d83b5f268ac4b216210733b0e277c54c6be3ee7", "`home_snapshot:0.2-synthetic`",
               "`home_client:0.2-synthetic`", "`home.snapshot.v0.2`", "`home.client.v0.2`", "合成の data だけ", "H1 は HOLD", "PROVISIONAL(S0)")
#: 節ごとに在るべき記述（他の節に同じ語が在っても、その節から消えれば落ちる）
H0_SECTION_REQUIRED = {
    "## 1. 範囲と主張しないこと": ("合成の data だけ", "実装 ・取得 ・保存 ・公開 ・deploy を承認しない", "S0-D1 が持つ", "PROVISIONAL(S0)"),
    "## 3. 6 つの項目": ("固定の順 ・足さない ・減らさない", "scenario の数 ・条件の判定 ・確信 ・版の遷移は S0-D1 が持ち",
                     "前回 ・予想 ・結果 ・前回の改訂はそれぞれ別の観察であり", "関係のある見出しを最大 3 件",
                     "各 entry は選定の理由（`selection_rationale` の template）・証拠 ・`known_at` ・`acquired_at` ・", "`as_of` での適格 ・出所を持つ",
                     "3 件に満たなければ満たないまま（埋めない）", "選定の algorithm は延期であり、本記録は新しい順 ・一律の時間の窓を",
                     "全文 ・生成した要約は持たない", "scenario に依存する", "並びは分類の順で固定し、序列を付けない",
                     "見通しの identity（series の id ・版の番号 ・版の digest）・`issued_at` ・`supersedes` の参照",
                     "H0 はこれらを参照として運ぶだけで、版の遷移が正しいかを検証 ・確定しない"),
    "## 4. 封筒と schema": ("`synthetic`（常に true）", "`items`（ちょうど 6）", "各 object の key の集合は閉じている",
                         "schema の id と digest の domain は一緒に版を上げる", "古い版の data は古い版の規則で検証する", "版を黙って読み替えない",
                         "build の時刻は snapshot に含めない（identity ・digest の外"),
    "## 5. 項目と entry": ("項目は自分の状態を持たない", "各 entry は元の状態を保つ", "集約は entry の状態を消さない ・書き換えない", "8 つの状態ではない",
                        "`h0_render_policy:0.1`（上から順に最初に当たるもの）", "各単位を 1 回だけ数える", "snapshot が FAILED_CLOSED の時は数を出さない",
                        "entry の状態の集合と `snapshot_status` だけの関数", "時計 ・entry の並び ・端末に依らない（決定論）",
                        "表示できる entry は §7 で値を出す状態だけ", "SUPERSEDED の entry は SUPERSEDED のまま数え、表示できる entry に数えない",
                        "SUPERSEDED だけの項目は AVAILABLE にならない（UNAVAILABLE）", "AVAILABLE の項目の entry は CURRENT か SUPERSEDED だけで、CURRENT が 1 つ以上在る"),
    "## 6. 時刻と PIT": ("build の時刻（telemetry だけ）", "H0 の data の規則", "合成の data の年は 2099", "P8 の `KnowledgeTime` と同じ",
                      "TIMESTAMP は `known_at` ≤ `as_of` で KNOWN、他は UNKNOWN", "DATE は東京の暦日として扱い",
                      "`as_of` 以前なら KNOWN、その日の始まりが `as_of` より後なら UNKNOWN、他は UNCERTAIN", "加えて `acquired_at` ≤ `as_of` を要する",
                      "`as_of` の後に取得したものを含む data は無効",
                      "見通しの版は `issued_at` ≤ `as_of` の時だけ snapshot に入る（時刻の適格だけ。版の遷移が正しいかは PROVISIONAL(S0)）",
                      "後の記録 ・後の観察を過去へ適用しない（将来の観察の漏えいは無い）", "端末の解釈の規則は H1 の規則であり、本記録は定めない"),
    "## 7. 8 つの状態": ("時刻だけから導けるのは UNKNOWN と UNCERTAIN だけ", "宣言の無い窓を参照する data は無効", "状態を畳み込まない",
                      "SUPERSEDED は、後継が `as_of` で §6 の適格を満たす時だけ", "後で出た後継で過去の snapshot の entry を SUPERSEDED にしない（PIT の再構成を保つ）",
                      "後継の適格が UNCERTAIN なら、前の entry も UNCERTAIN（推測しない）", "後継は同じ snapshot の同じ項目の entry として在る。後継の鎖は循環しない。",
                      "参照が解けない ・循環する snapshot は無効",
                      "後継の entry を MISSING（理由 `SUCCESSOR_MISSING`）として置く。後継を作らない ・推測しない ・前の版の値で埋めない",
                      "後継の record が壊れていれば INTEGRITY_FAILURE（snapshot 全体を fail closed）", "項目 1 の現在の見通しは SUPERSEDED でない版だけ",
                      "前の版を代わりに示さない（前の版は lineage と項目 5 でだけ辿れる）"),
    "## 8. 主張の分類": ("`epistemic`（FACT ／ HYPOTHESIS）", "語彙は変えない", "MODEL_PROPOSED は常に HYPOTHESIS",
                      "OUTLOOK ／ RISK ／ INTERPRETIVE は常に HYPOTHESIS", "HYPOTHESIS の入力を持つ導出は HYPOTHESIS", "仮説はその場で事実に昇格しない",
                      "条件の判定と見通しの変化は claim ではない別の記録の型であり、`citations` に入らない"),
    "## 9. 出所と証拠の参照": ("引用（source の鎖）と導出（規則の鎖）は別の欄", "system ・model の出力を証拠に数えない"),
    "## 10. export の等級と privacy": ("PUBLIC_SAFE ・PRIVATE_DERIVED ・PRIVATE_AUTHORITY ・NEVER", "項目 1 〜 6 は PRIVATE_DERIVED",
                                   "NEVER と PRIVATE_AUTHORITY の data は snapshot に在れば無効",
                                   "公開の面（Pages ・公開の report ・Cloudflare）に Home の data を出さない",
                                   "端末で等級ごとに何を表示するかは M0-D1 が定める", "資格情報 ・private な root の位置 ・local の path は snapshot に存在しない"),
    "## 11. 正準化と digest": ("P13 の `canonical_json`", "`domain_digest`", "製品の名前を含めない", "同じ文字列の domain は repository に無い"),
    "## 12. 合成の fixture": ("`synthetic` は true ・id は `syn_` で始まる ・日時は 2099 年", "本記録は fixture を作らない",
                          "本記録の記述は検証器で確かめた fixture ではない"),
    "## 13. 検証の不変量": ("6 つの項目がちょうど 1 回ずつ、固定の順で在る", "INTEGRITY_FAILURE が在れば `snapshot_status` は FAILED_CLOSED",
                        "§14 の禁止の欄 ・語が無い", "SUPERSEDED の entry の後継は同じ snapshot の同じ項目に在り、後継の鎖は循環しない",
                        "AVAILABLE の項目には CURRENT の entry が在る。SUPERSEDED だけの項目は AVAILABLE にならない"),
    "## 14. 禁止": ("根拠の無い確信の語（市場の見通しの表示の文 ・template だけ）: 確実 ・必ず", "本記録では表示の文 ・template を「」で囲んで書く",
                  "本記録の規則と契約の義務の記述は対象外", "否定の 不確実 ・不確かさ は使ってよい"),
    "## 15. S0 に依存する暫定の規則": ("scenario の数と型", "条件の型 ・比較 ・窓 ・条件の判定の状態と遷移", "確信の表し方と規則", "見通しの版の遷移と改訂の理由",
                               "上の規則は S0-D1 が定め、本記録は値を確定しない",
                               "S0-D1 は次の権限を持つ: scenario の意味 ・版の遷移が正しいか ・条件の判定 ・確信の意味 ・基本と代替の決定",
                               "H0 が運ぶのは見通しの identity ・`issued_at` ・`supersedes` の参照だけであり、これらの権限を持たない",
                               "S0 の語彙の値（条件の判定の状態 ・確信の段階 ・基本と代替の印）を本記録は列挙しない"),
    "## 16. 依存と延期": ("H1: 合成の data だけの prototype", "news の選定の algorithm"),
    "## 17. 本記録の承認の範囲": ("本記録は文書 ・registry ・guard だけ", "product の機能 ・runtime の振る舞いは変わらない", "本記録は実装を承認しない",
                            "監督の別の承認を要する"),
}
#: 6 つの項目（順 → 項目 ・kind ・entry の数）。順 ・数 ・上限の改変は落ちる
H0_ITEMS = {"1": ("市場の見通し", "OUTLOOK", "0 〜 1"), "2": ("市場の snapshot（指数 ・金利 ・為替）", "SNAPSHOT", "1 〜 12"),
            "3": ("72 時間以内の予定", "EVENTS", "0 〜 8"), "4": ("重要な news", "NEWS", "0 〜 3"), "5": ("前の見通しからの変化", "CHANGE", "0 〜 1"),
            "6": ("関連する会社 ・theme", "RELATIONS", "0 〜 10")}
#: 8 つの状態（P12.5-A0 §5.5 の順 → 値 ・扱い）
H0_STATES = {"CURRENT": ("出す", "通常"), "SUPERSEDED": ("出さない", "後継を出す ・lineage と項目 5 で辿れる"),
             "MISSING": ("出さない", "欠落の理由を出す ・推測しない"), "STALE": ("出す", "宣言した窓を超えた印 ・trigger にしない"),
             "UNKNOWN": ("出さない", "件数に残す ・固定の枠では値の無い印"), "UNCERTAIN": ("出さない", "件数に残す ・推測しない"),
             "AMBIGUOUS": ("両方の値", "矛盾の印 ・事実の根拠にしない"), "INTEGRITY_FAILURE": ("出さない", "snapshot 全体を fail closed")}
H0_PRECEDENCE = ("INTEGRITY_FAILURE", "MISSING", "UNKNOWN", "UNCERTAIN", "AMBIGUOUS", "SUPERSEDED", "STALE", "CURRENT")
#: 表示の集約の方針（上から順に最初に当たるもの ・entry の状態は消さない ・SUPERSEDED だけの項目は AVAILABLE にならない）
H0_RENDER_POLICY = ("snapshot が FAILED_CLOSED なら SUPPRESSED", "entry が 0 件なら EMPTY",
                    "表示できる entry（CURRENT ・STALE ・AMBIGUOUS）が無ければ UNAVAILABLE",
                    "MISSING ・STALE ・UNKNOWN ・UNCERTAIN ・AMBIGUOUS の entry が 1 つでも在れば PARTIAL", "他は AVAILABLE")
#: 方針の行の文法（文法の外の行は落ちる）と表示の状態の語彙（8 つの状態と重ならない）
H0_RENDER_GRAMMAR = (("FAILED_CLOSED", r"snapshot が FAILED_CLOSED なら (?P<render>[A-Z_]+)"), ("NO_ENTRY", r"entry が 0 件なら (?P<render>[A-Z_]+)"),
                     ("NONE_OF", r"表示できる entry（(?P<states>[A-Z_ ・]+)）が無ければ (?P<render>[A-Z_]+)"),
                     ("ANY_OF", r"(?P<states>[A-Z_ ・]+) の entry が 1 つでも在れば (?P<render>[A-Z_]+)"), ("OTHERWISE", r"他は (?P<render>[A-Z_]+)"))
H0_RENDER_STATES = ("SUPPRESSED", "EMPTY", "UNAVAILABLE", "PARTIAL", "AVAILABLE")
H0_DISPLAYABLE = frozenset(state for state, (shown, _) in H0_STATES.items() if shown != "出さない")   # §7 で値を出す状態
H0_DEGRADED = frozenset(H0_STATES) - {"CURRENT", "SUPERSEDED", "INTEGRITY_FAILURE"}
#: §14 にだけ在ってよい禁止の欄の名前（小文字）と語
H0_FORBIDDEN_FIELDS = ("probability", "odds", "likelihood_pct", "rank", "ranking", "score", "rating", "weight", "target_price", "price_target",
                       "expected_return", "recommendation", "buy", "sell", "hold", "signal", "full_text", "body", "article_text", "llm_summary")
H0_FORBIDDEN_WORDS = ("推奨", "買い", "売り", "目標株価", "確率", "的中率", "勝率", "期待値", "ランキング", "順位", "おすすめ", "注目銘柄", "最新")
#: 根拠の無い確信の語（市場の見通しの表示の文 ・template ＝ 本記録では「」の中だけ。契約の義務の文は対象外 ・不確実 は許す）
H0_CERTAINTY_WORDS = ("確実", "必ず")
H0_CERTAINTY_PATTERN = r"(?<!不)確実|必ず"
#: S0-D1 が持つ語彙の値（本記録は列挙しない）
H0_S0_VOCABULARY = ("PENDING", "OBSERVED_MET", "OBSERVED_NOT_MET", "NOT_OBSERVABLE", "HIGH", "MEDIUM", "LOW", "BASE", "ALT", "ALTERNATIVE",
                    "INITIAL", "PROGRESS", "LATE_OBSERVATION", "SOURCE_CORRECTION")
H0_BANNED = ("実装を承認する", "実装を承認した", "H1 を承認する", "H1 は GO", "実の data を使う", "実の data に接続する", "本番で使う", "deploy を承認する",
             "公開を承認する", "Pages に出す", "新しい順に並べ", "時間以内に限る", "時間に限る", "S0 を確定した", "A6 は完了", "Market Memory v1 は凍結した",
             "署名済み", "http://", "https://")
H0_BANNED_PATTERNS = (r"(?:H0-D1|H1|M0-D1|S0-D1|UI0|A5-W|A6|pytest|commit|push)[^\n|]{0,8}=\s*GO\b",          # 実装 ・実行の権限
                      r"scenario の数は\s*\d",                                                             # S0 の値の確定
                      r"\d\s*[%％]",                                                                      # 数値の見込み
                      r"(?i)rashinban|compass",                                                           # 製品の名前（domain ・schema は中立）
                      r"`(?!home\.(?:snapshot|client)\.v0\.2`)[a-z0-9_.]*home\.[a-z0-9_.]*`",             # 宣言の外の digest の domain
                      r"`(?!home_(?:snapshot|client):0\.2-synthetic`)[a-z0-9_]*home_[a-z_]+:[^`\n]*`",     # 宣言の外の schema
                      r"\b(?:jq|p\d+)_[a-z0-9]+_(?:private|work)\b", r"\\\\[A-Za-z0-9.-]+\\")            # private な root ・UNC の host


def _h0_render_rules(text: str) -> list:
    """§5 の集約の方針の行を (種類, 状態の集合, 表示の状態) に解く（文法の外の行は None）。"""
    rules = []
    for line in _a5_section(text, "## 5. 項目と entry").splitlines():
        if line.startswith("  - "):
            parsed = None
            for kind, pattern in H0_RENDER_GRAMMAR:
                match = re.fullmatch(pattern, line[4:])
                if match:
                    members = match.groupdict().get("states")
                    parsed = (kind, frozenset(s.strip() for s in members.split("・")) if members else frozenset(), match.group("render"))
                    break
            rules.append(parsed)
    return rules


def _h0_render(rules: list, status: str, states: frozenset) -> str:
    """方針を上から順に当て、最初に当たった表示の状態（entry の状態の集合と snapshot の状態だけの関数）。"""
    for kind, members, render in rules:
        if ((kind == "FAILED_CLOSED" and status == "FAILED_CLOSED") or (kind == "NO_ENTRY" and not states)
                or (kind == "NONE_OF" and not states & members) or (kind == "ANY_OF" and states & members) or kind == "OTHERWISE"):
            return render
    return ""


def _h0_render_violations(text: str) -> list:
    """表示の集約の方針を全ての状態の組で評価した振る舞いの違反（SUPERSEDED だけの項目 ・古い版の代用 ・fail closed）。"""
    rules = _h0_render_rules(text)
    if not rules or None in rules or rules[-1][0] != "OTHERWISE":
        return [("RENDER_BEHAVIOR", "grammar")]
    found = set()
    renders = {render for *_, render in rules}
    if not renders <= set(H0_RENDER_STATES) or renders & set(H0_STATES):
        found.add("vocabulary")                                                                      # 8 つの状態を表示の状態に流用しない
    if any(members - set(H0_STATES) for _, members, _ in rules):
        found.add("unknown_state")
    if any(kind == "NONE_OF" and members != H0_DISPLAYABLE for kind, members, _ in rules):
        found.add("displayable")                                                                     # 表示できる entry ＝ §7 で値を出す状態
    ordinary = [state for state in H0_STATES if state != "INTEGRITY_FAILURE"]
    for mask in range(1 << len(ordinary)):
        states = frozenset(state for bit, state in enumerate(ordinary) if mask >> bit & 1)
        if {_h0_render(rules, "FAILED_CLOSED", states), _h0_render(rules, "FAILED_CLOSED", states | {"INTEGRITY_FAILURE"})} != {"SUPPRESSED"}:
            found.add("fail_closed")
        render = _h0_render(rules, "OK", states)
        if not states and render != "EMPTY":
            found.add("empty")
        if states and not states & H0_DISPLAYABLE and render != "UNAVAILABLE":
            found.add("no_displayable_entry")                                                        # SUPERSEDED だけ ・古い版だけは AVAILABLE にならない
        if render == "AVAILABLE" and ("CURRENT" not in states or not states <= {"CURRENT", "SUPERSEDED"}):
            found.add("available_without_current")
        if states & H0_DISPLAYABLE and states & H0_DEGRADED and render != "PARTIAL":
            found.add("degraded_not_partial")
        if "CURRENT" in states and states <= {"CURRENT", "SUPERSEDED"} and render != "AVAILABLE":
            found.add("valid_lineage_not_available")                                                 # 後継の在る正しい lineage は AVAILABLE のまま
    return [("RENDER_BEHAVIOR", reason) for reason in sorted(found)]


def _h0_record_violations(text: str) -> list:
    """Home の情報の契約の記録の違反（空なら適合）。"""
    found = []
    items = _a5t_table(text, "## 3. 6 つの項目", r"\d")
    if tuple(items) != tuple(H0_ITEMS) or any(len(r) != 1 or tuple(r[0]) != H0_ITEMS[k] for k, r in items.items()):
        found.append(("ITEMS", tuple(items)))
    states = _a5t_table(text, "## 7. 8 つの状態", r"[A-Z_]+")
    if tuple(states) != tuple(H0_STATES) or any(len(r) != 1 or tuple(r[0]) != H0_STATES[k] for k, r in states.items()):
        found.append(("STATES", tuple(states)))
    if "優先の順: " + " > ".join(H0_PRECEDENCE) + "。" not in _a5_section(text, "## 7. 8 つの状態"):
        found.append(("PRECEDENCE", "order"))
    policy = tuple(line[4:] for line in _a5_section(text, "## 5. 項目と entry").splitlines() if line.startswith("  - "))
    if policy != H0_RENDER_POLICY:
        found.append(("RENDER_POLICY", policy))
    found += _h0_render_violations(text)
    found += [("MISSING", needle) for needle in H0_REQUIRED if needle not in text]
    for heading, needles in H0_SECTION_REQUIRED.items():
        section = _a5_section(text, heading)
        found += [("SECTION", heading, needle) for needle in needles if needle not in section]
    prohibited = _a5_section(text, "## 14. 禁止")
    found += [("PROHIBITION_LIST", term) for term in (*(f"`{field}`" for field in H0_FORBIDDEN_FIELDS), *H0_FORBIDDEN_WORDS, *H0_CERTAINTY_WORDS)
              if term not in prohibited]
    outside = text.replace(prohibited, "") if prohibited else text                                  # 禁止の語は §14 の外に無い
    found += [("FORBIDDEN_FIELD", field) for field in H0_FORBIDDEN_FIELDS
              if re.search(r"(?<![A-Za-z0-9_])" + re.escape(field) + r"(?![A-Za-z0-9_])", outside)]
    found += [("FORBIDDEN_WORD", word) for word in H0_FORBIDDEN_WORDS if word in outside]
    found += [("CERTAINTY", span) for span in re.findall(r"「([^「」\n]*)」", text) if re.search(H0_CERTAINTY_PATTERN, span)]   # 表示の文 ・template だけ
    found += [("S0_VOCABULARY", word) for word in H0_S0_VOCABULARY if re.search(r"(?<![A-Za-z0-9_])" + word + r"(?![A-Za-z0-9_])", text)]
    found += [("BANNED", banned) for banned in H0_BANNED if banned in text]
    found += [("PATTERN", pattern) for pattern in H0_BANNED_PATTERNS + PRIVATE_PATTERNS if re.search(pattern, text)]
    if re.search(r"\b(?:is|are|was|were|been)\s+(?:digitally\s+|cryptographically\s+)?signed\b", text, re.IGNORECASE):
        found.append(("SIGNED", "claim"))
    return found


def test_h0_d1_home_information_contract_is_a_guarded_documentation_only_record() -> None:
    text = (REPO_ROOT / H0_D1_DOC).read_text(encoding="utf-8")
    assert _h0_record_violations(text) == []
    assert H0_D1_DOC in PHASE13_DOCS and PHASE13_DOCS.index(H0_D1_DOC) == PHASE13_DOCS.index(A5T_RECORD_DOC) + 1   # A5-T の記録の直後に登録（追記に安全）
    assert all(doc != H0_D1_DOC for *_, doc in PHASE13_RUNTIME_AUTHORIZATION)                       # 実装 ・runtime の認可は無い
    assert not any(gate.startswith(("H0", "H1", "M0", "S0", "UI0")) for gate, *_ in PHASE13_RUNTIME_AUTHORIZATION)
    assert len(PHASE13_RUNTIME) == 12 and not any("home" in path for path in PHASE13_RUNTIME)
    for path in PHASE13_RUNTIME:                                                                     # domain ・schema は runtime に無い（先取りの実装なし）
        source = (REPO_ROOT / path).read_text(encoding="utf-8")
        assert not any(name in source for name in ("home.snapshot", "home.client", "home_snapshot", "home_client")), path
    a0 = (REPO_ROOT / PHASE12_5_FROZEN_CONTRACTS[0]).read_text(encoding="utf-8")
    assert tuple(_a5t_table(a0, "### 5.5", r"[A-Z_]+")) == tuple(H0_STATES)                         # P12.5-A0 §5.5 の 8 つの状態と同じ順
    assert set(H0_PRECEDENCE) == set(H0_STATES) and len(H0_PRECEDENCE) == 8
    assert len(H0_ITEMS) == 6 and len({kind for _, kind, _ in H0_ITEMS.values()}) == 6
    assert all(re.search(H0_CERTAINTY_PATTERN, word) for word in H0_CERTAINTY_WORDS) and not re.search(H0_CERTAINTY_PATTERN, "不確実 ・不確かさ")
    assert not set(H0_CERTAINTY_WORDS) & set(H0_FORBIDDEN_WORDS)                                   # 確信の語は表示の文だけの規則
    accepted = {                                                                                     # 正の control: 正当な文は拒まない
        "contract_obligation_must": text + "\n- 本記録の規則は必ず版の番号と一緒に変える。\n",
        "contract_obligation_certain": text + "\n- fixture は確実に pin する。\n",
        "uncertainty_in_prose": text + "\n- 不確実な点は数値にしない。\n",
        "uncertainty_in_display_text": text + "\n- 表示の文の例: 「架空の見通しには不確実な点が在る」。\n",
    }
    for name, candidate in accepted.items():
        assert candidate != text and _h0_record_violations(candidate) == [], name
    rules = _h0_render_rules(text)
    assert [render for *_, render in rules] == list(H0_RENDER_STATES) and H0_DISPLAYABLE == {"CURRENT", "STALE", "AMBIGUOUS"}
    cases = {("OK", ("SUPERSEDED",)): "UNAVAILABLE", ("OK", ("SUPERSEDED", "MISSING")): "UNAVAILABLE",   # 古い版は現在の見通しの代わりにならない
             ("OK", ("SUPERSEDED", "CURRENT")): "AVAILABLE", ("OK", ("SUPERSEDED", "STALE")): "PARTIAL", ("OK", ()): "EMPTY",
             ("OK", ("CURRENT", "UNKNOWN")): "PARTIAL", ("FAILED_CLOSED", ("CURRENT", "INTEGRITY_FAILURE")): "SUPPRESSED"}
    for (status, states), render in cases.items():
        assert _h0_render(rules, status, frozenset(states)) == render, (status, states)


def test_h0_d1_negative_controls_reject_altered_or_overclaimed_contracts() -> None:
    text = (REPO_ROOT / H0_D1_DOC).read_text(encoding="utf-8")
    assert _h0_record_violations(text) == []
    lines = text.splitlines(keepends=True)
    row = {key: next(line for line in lines if line.startswith(f"| {key} |"))
           for key in ("1", "4", "5", "6", "SUPERSEDED", "UNKNOWN", "AMBIGUOUS", "INTEGRITY_FAILURE")}
    mutated = {                                                                                      # 名前 → (拒むべき規則, 改変した記録)
        "item_removed": ("ITEMS", text.replace(row["6"], "")),                                     # 項目の改変
        "item_added": ("ITEMS", text.replace(row["6"], row["6"] + "| 7 | 個人の note | NOTES | 0 〜 5 |\n")),
        "items_swapped": ("ITEMS", text.replace(row["4"] + row["5"], row["5"] + row["4"])),
        "news_limit_raised": ("ITEMS", text.replace(row["4"], row["4"].replace("0 〜 3", "0 〜 5"))),
        "item_kind_renamed": ("ITEMS", text.replace(row["1"], row["1"].replace("OUTLOOK", "FORECAST"))),
        "state_removed": ("STATES", text.replace(row["AMBIGUOUS"], "")),                           # 状態の改変
        "state_display_changed": ("STATES", text.replace(row["UNKNOWN"], row["UNKNOWN"].replace("| 出さない |", "| 出す |"))),
        "integrity_failure_not_fail_closed": ("STATES", text.replace(row["INTEGRITY_FAILURE"], row["INTEGRITY_FAILURE"].replace("snapshot 全体を fail closed", "その entry だけ出さない"))),
        "precedence_changed": ("PRECEDENCE", text.replace("AMBIGUOUS > SUPERSEDED > STALE", "SUPERSEDED > AMBIGUOUS > STALE")),
        "states_conflated": ("SECTION", text.replace("状態を畳み込まない（別の欄 ・別の印で区別する）。", "STALE と UNKNOWN は 1 つの印にまとめる。")),
        "fail_closed_invariant_removed": ("SECTION", text.replace("- INTEGRITY_FAILURE が在れば `snapshot_status` は FAILED_CLOSED。\n", "")),
        "time_only_states_widened": ("SECTION", text.replace("時刻だけから導けるのは UNKNOWN と UNCERTAIN だけ", "時刻だけから STALE も導ける")),
        "entry_state_erased": ("SECTION", text.replace("集約は entry の状態を消さない ・書き換えない。", "集約は entry の状態を項目の状態で置き換える。")),  # 集約
        "item_state_conflated": ("SECTION", text.replace("項目は自分の状態を持たない。", "項目は entry の最悪の状態を自分の状態として持つ。")),
        "aggregation_rule_removed": ("RENDER_POLICY", text.replace("  - MISSING ・STALE ・UNKNOWN ・UNCERTAIN ・AMBIGUOUS の entry が 1 つでも在れば PARTIAL\n", "")),
        "aggregation_order_changed": ("RENDER_POLICY", text.replace("  - snapshot が FAILED_CLOSED なら SUPPRESSED\n  - entry が 0 件なら EMPTY\n", "  - entry が 0 件なら EMPTY\n  - snapshot が FAILED_CLOSED なら SUPPRESSED\n")),
        "render_state_as_data_state": ("SECTION", text.replace("8 つの状態ではない", "8 つの状態の 1 つである")),
        "coverage_double_count": ("SECTION", text.replace("各単位を 1 回だけ数える。", "event とその欄を両方とも重ねて数える。")),
        "grade_rule_weakened": ("SECTION", text.replace("NEVER と PRIVATE_AUTHORITY の data は snapshot に在れば無効。", "NEVER の data は snapshot に在れば無効。")),  # 等級
        "public_exposure_allowed": ("SECTION", text.replace("公開の面（Pages ・公開の report ・Cloudflare）に Home の data を出さない。", "Home の data は Pages に出す。")),
        "grade_vocabulary_changed": ("SECTION", text.replace("PUBLIC_SAFE ・PRIVATE_DERIVED ・PRIVATE_AUTHORITY ・NEVER", "PUBLIC ・PRIVATE")),
        "model_proposed_as_fact": ("SECTION", text.replace("MODEL_PROPOSED は常に HYPOTHESIS。", "MODEL_PROPOSED は検証の後に FACT。")),  # 主張の分類
        "hypothesis_promoted": ("SECTION", text.replace("仮説はその場で事実に昇格しない", "仮説は確かめた時にその場で事実に昇格する")),
        "evaluation_cited": ("SECTION", text.replace("`citations` に入らない", "`citations` に入れてよい")),
        "epistemic_enum_extended": ("SECTION", text.replace("`epistemic`（FACT ／ HYPOTHESIS）", "`epistemic`（FACT ／ DERIVED ／ HYPOTHESIS）")),
        "acquisition_rule_removed": ("SECTION", text.replace("- 加えて `acquired_at` ≤ `as_of` を要する。", "- `acquired_at` は表示だけに使う。")),  # 時刻 ・PIT
        "future_leak_allowed": ("SECTION", text.replace("後の記録 ・後の観察を過去へ適用しない（将来の観察の漏えいは無い）。", "後の観察で過去の snapshot を補う。")),
        "build_time_in_identity": ("SECTION", text.replace("build の時刻は snapshot に含めない（identity ・digest の外。", "build の時刻を snapshot の identity に含める（")),
        "p8_date_semantics_removed": ("SECTION", text.replace("DATE は東京の暦日として扱い", "DATE は UTC の日として扱い")),
        "h1_parsing_rule_merged": ("SECTION", text.replace("端末の解釈の規則は H1 の規則であり、本記録は定めない", "端末の解釈の規則も本記録が定める")),
        "news_newest_first_mandated": ("BANNED", text + "\n見出しは新しい順に並べる。\n"),          # news
        "news_time_window_mandated": ("BANNED", text + "\n見出しは 24 時間以内に限る。\n"),
        "news_rationale_removed": ("SECTION", text.replace("各 entry は選定の理由（`selection_rationale` の template）・証拠 ・", "各 entry は証拠 ・")),
        "news_slots_filled": ("SECTION", text.replace("3 件に満たなければ満たないまま（埋めない）。", "3 件に満たなければ他の見出しで埋める。")),
        "news_full_text": ("FORBIDDEN_FIELD", text.replace("全文 ・生成した要約は持たない。", "`full_text` を持つ。")),
        "s0_finalized": ("SECTION", text.replace("上の規則は S0-D1 が定め、本記録は値を確定しない。", "上の規則は本記録が確定する。")),  # S0
        "s0_count_fixed": ("PATTERN", text + "\nscenario の数は 2 つに確定する。\n"),
        "provisional_markers_removed": ("MISSING", text.replace("PROVISIONAL(S0)", "確定")),
        "s0_owner_replaced": ("SECTION", text.replace("scenario の数 ・条件の判定 ・確信 ・版の遷移は S0-D1 が持ち", "条件の判定 ・確信 ・版の遷移は H0 が持ち")),
        "probability_field": ("FORBIDDEN_FIELD", text + "\n- 項目 1 は `probability` を持つ。\n"),  # 禁止の意味
        "recommendation_word": ("FORBIDDEN_WORD", text + "\n- 表示: 推奨の会社。\n"),
        "price_target_word": ("FORBIDDEN_WORD", text + "\n- 項目 6 に目標株価を出す。\n"),
        "ranking_semantics": ("FORBIDDEN_WORD", text.replace("並びは分類の順で固定し、序列を付けない。", "並びは関連の強さの順位で並べる。")),
        "numeric_score_field": ("FORBIDDEN_FIELD", text + "\n- 各 entry は `score` を持つ。\n"),
        "newest_word": ("FORBIDDEN_WORD", text + "\n- 最新の見出し。\n"),
        "numeric_likelihood": ("PATTERN", text + "\n- base の見込みは 60% 。\n"),
        "prohibition_list_shrunk": ("PROHIBITION_LIST", text.replace("`rank` ・`ranking` ・", "")),
        "prohibition_heading_changed": ("PROHIBITION_LIST", text.replace("## 14. 禁止", "## 14. 補足")),
        "implementation_claim": ("BANNED", text + "\n本記録は実装を承認する。\n"),                  # 権限 ・過大な主張
        "implementation_disclaimer_removed": ("MISSING", text.replace("本記録は実装を承認しない", "本記録は実装の始まり")),
        "h1_authority": ("PATTERN", text + "\nH1 = GO\n"),
        "real_data_claim": ("BANNED", text + "\n実の data に接続する。\n"),
        "deploy_claim": ("BANNED", text + "\ndeploy を承認する。\n"),
        "synthetic_only_removed": ("MISSING", text.replace("合成の data だけ", "data")),
        "schema_changed": ("MISSING", text.replace("`home_snapshot:0.2-synthetic`", "`home_snapshot:0.2`")),  # schema ・domain ・版
        "domain_with_product_name": ("PATTERN", text.replace("| digest の domain | `home.snapshot.v0.2`", "| digest の domain | `rashinban.home.snapshot.v0.2`")),
        "domain_version_changed": ("PATTERN", text.replace("`home.client.v0.2`（投影）", "`home.client.v0.3`（投影）")),
        "silent_version_reinterpretation": ("SECTION", text.replace("版を黙って読み替えない。", "古い版は新しい版として読む。")),
        "closed_keys_removed": ("SECTION", text.replace("各 object の key の集合は閉じている", "各 object は未知の key を持ってよい")),
        "section_heading_changed": ("SECTION", text.replace("## 6. 時刻と PIT", "## 6. 時刻")),
        "private_path": ("PATTERN", text + "\n" + "Z:" + "\\p99_a9_private\n"),                     # private な形
        "private_timestamp": ("PATTERN", text + "\n" + "2099-01-05" + "T07:30\n"),
        "private_bare_number": ("PATTERN", text + "\n値は " + "12345" + "\n"),
        "private_identifier": ("PATTERN", text + "\np9wat_0123\n"),
        "external_link": ("BANNED", text + "\nhttps://example.invalid/news\n"),
        "signed_claim": ("SIGNED", text + "\nThe snapshot is signed.\n"),
        "certainty_in_display_text": ("CERTAINTY", text + "\n- 表示の文の例: 「架空の指数は確実に上がる」。\n"),        # 根拠の無い確信（表示の文だけ）
        "must_in_display_template": ("CERTAINTY", text + "\n- template: 「架空の theme は必ず反発する」。\n"),
        "certainty_beside_uncertainty": ("CERTAINTY", text + "\n- 表示の文の例: 「不確実ではなく確実」。\n"),
        "certainty_rule_removed": ("SECTION", text.replace("根拠の無い確信の語（市場の見通しの表示の文 ・template だけ）: 確実 ・必ず。", "")),
        "uncertainty_word_banned": ("SECTION", text.replace("否定の 不確実 ・不確かさ は使ってよい。", "不確実 も使わない。")),
        "market_word_in_prose_still_rejected": ("FORBIDDEN_WORD", text + "\n- 本記録は注目銘柄を扱わない。\n"),
        "superseded_only_available": ("RENDER_BEHAVIOR", text.replace("  - 表示できる entry（CURRENT ・STALE ・AMBIGUOUS）が無ければ UNAVAILABLE\n", "")),  # SUPERSEDED だけの項目
        "superseded_counted_displayable": ("RENDER_BEHAVIOR", text.replace("表示できる entry（CURRENT ・STALE ・AMBIGUOUS）", "表示できる entry（CURRENT ・STALE ・AMBIGUOUS ・SUPERSEDED）")),
        "unavailable_after_partial": ("RENDER_BEHAVIOR", text.replace("  - 表示できる entry（CURRENT ・STALE ・AMBIGUOUS）が無ければ UNAVAILABLE\n  - MISSING ・STALE ・UNKNOWN ・UNCERTAIN ・AMBIGUOUS の entry が 1 つでも在れば PARTIAL\n", "  - MISSING ・STALE ・UNKNOWN ・UNCERTAIN ・AMBIGUOUS の entry が 1 つでも在れば PARTIAL\n  - 表示できる entry（CURRENT ・STALE ・AMBIGUOUS）が無ければ UNAVAILABLE\n")),
        "render_uses_entry_state": ("RENDER_BEHAVIOR", text.replace("が無ければ UNAVAILABLE", "が無ければ MISSING")),
        "render_rule_unparseable": ("RENDER_BEHAVIOR", text.replace("  - 表示できる entry（CURRENT ・STALE ・AMBIGUOUS）が無ければ UNAVAILABLE\n", "  - 表示できる entry が少なければ UNAVAILABLE\n")),
        "stale_counted_available": ("RENDER_BEHAVIOR", text.replace("  - MISSING ・STALE ・UNKNOWN ・UNCERTAIN ・AMBIGUOUS の entry が", "  - MISSING ・UNKNOWN ・UNCERTAIN ・AMBIGUOUS の entry が")),
        "fail_closed_not_first": ("RENDER_BEHAVIOR", text.replace("  - snapshot が FAILED_CLOSED なら SUPPRESSED\n  - entry が 0 件なら EMPTY\n", "  - entry が 0 件なら EMPTY\n  - snapshot が FAILED_CLOSED なら SUPPRESSED\n")),
        "superseded_display_changed": ("STATES", text.replace(row["SUPERSEDED"], row["SUPERSEDED"].replace("| 出さない |", "| 出す |"))),
        "successor_invented": ("SECTION", text.replace("後継を作らない ・推測しない ・前の版の値で埋めない。", "後継が無ければ前の版を後継として示す。")),
        "missing_successor_not_explicit": ("SECTION", text.replace("後継の entry を MISSING（理由 `SUCCESSOR_MISSING`）として置く。", "後継の entry を省く。")),
        "old_outlook_substitutes": ("SECTION", text.replace("前の版を代わりに示さない（前の版は lineage と項目 5 でだけ辿れる）。", "前の版を代わりに示す。")),
        "pit_supersession_backdated": ("SECTION", text.replace("後で出た後継で過去の snapshot の entry を SUPERSEDED にしない（PIT の再構成を保つ）。", "後の版が出れば過去の snapshot の entry も SUPERSEDED にする。")),
        "successor_cycle_allowed": ("SECTION", text.replace("後継の鎖は循環しない。\n", "後継の鎖は循環してよい。\n")),
        "successor_integrity_not_fail_closed": ("SECTION", text.replace("後継の record が壊れていれば INTEGRITY_FAILURE（snapshot 全体を fail closed）。", "後継の record が壊れていれば前の版を出す。")),
        "nondeterministic_render": ("SECTION", text.replace("時計 ・entry の並び ・端末に依らない（決定論）", "端末の時計で決める")),
        "s0_authority_list_shrunk": ("SECTION", text.replace("・条件の判定 ・確信の意味 ・基本と代替の決定。", "・条件の判定。")),   # S0-D1 の権限
        "h0_validates_transitions": ("SECTION", text.replace("H0 はこれらを参照として運ぶだけで、版の遷移が正しいかを検証 ・確定しない。", "H0 は版の遷移が正しいかを検証する。")),
        "issued_at_rule_overreaches": ("SECTION", text.replace("（時刻の適格だけ。版の遷移が正しいかは PROVISIONAL(S0)）", "（版の遷移の正しさも H0 が決める）")),
        "confidence_scale_defined": ("S0_VOCABULARY", text + "\n- 確信は HIGH ／ MEDIUM ／ LOW の 3 段。\n"),
        "condition_state_defined": ("S0_VOCABULARY", text + "\n- 条件の判定は PENDING から始める。\n"),
        "base_alternative_decided_by_h0": ("S0_VOCABULARY", text + "\n- 基本の scenario は BASE の印で H0 が選ぶ。\n"),
    }
    for name, (rule, candidate) in mutated.items():
        assert candidate != text, name
        assert rule in {violation[0] for violation in _h0_record_violations(candidate)}, name     # 該当の規則が実際に拒む


#: M0-D1: mobile の security と access の契約の記録（文書だけ ・実装の承認ではない）
M0_REQUIRED = ("本記録は実装を承認しない", "69fb4396a797566b2b70f435721892f9e096344f", H0_D1_BLOB, "`home_client:0.2-synthetic`",
               "`home.snapshot.v0.2`", "`home.client.v0.2`", "`h0_render_policy:0.1`", "合成の data だけ", "H1 ・M1 ・deploy は HOLD",
               "OS の水準の隔離を主張しない", "CSP だけで隔離を証明したとは主張しない", "browser は暗号の検証を行わない", "PROVISIONAL(S0)",
               "「合成データ・投資判断に使えない」", "`YYYY-MM-DDTHH:MM:SS+00:00`")
#: 節ごとに在るべき記述（他の節に同じ語が在っても、その節から消えれば落ちる）
M0_SECTION_REQUIRED = {
    "## 1. 範囲と主張しないこと": ("実装 ・browser の実行 ・CDP の client ・fixture の生成 ・hosting ・認証の実装 ・deploy を承認しない", "合成の data だけ",
                         "OS の水準の隔離を主張しない", "CSP だけで隔離を証明したとは主張しない", "browser の中で暗号の検証を行うとは主張しない",
                         "H0-D1 の記録の byte は変えない", "項目ごとの正確な key と上限は H0-D2 が持つ"),
    "## 3. H1 の脅威 model": ("完全に侵害された OS ・browser ・拡張は守る範囲の外", "OS が「強制した」とは言わない"),
    "## 4. 実行の platform": ("`file://` から開く 1 つの file `index.html`", "CSP の hash で覆う", "browser は実行しない",
                         "画像 ・icon ・web font ・manifest ・service worker は無い。install できる PWA ではない", "新しい一時の専用の profile",
                         "実機の iPhone ・Safari ・WebKit は検証しない", "listener ・port ・Host の検査 ・HTTP の cache は無い",
                         "pipe（`--remote-debugging-pipe`）を H1 の設計の優先とする", "feasibility の試験を要し、本記録は検証済みとは主張しない",
                         "debugging port の transport への fallback は監督の別の承認を要する", "native か PWA かの決定は M1 に延期する"),
    "## 5. 認証と資格情報": ("H1 に認証は無い。account ・password ・token ・OAuth ・session は無い", "資格情報の変数が在れば起動を拒む", "M1 の範囲"),
    "## 6. 保存": ("保存の API は静的な走査で禁じ", "空であることを確かめる", "process の memory の消去は保証しない"),
    "## 7. network と CSP": ("`<head>` の最初の要素の `<meta>`", "hash を使う", "x-dns-prefetch-control", "禁止の API（静的な走査で 0 件）",
                         "CSP は page だけを縛り", "flag は browser 自身の通信を失敗させるが、無いことを証明しない", "OS の水準の隔離は無い"),
    "## 8. 等級ごとの表示": ("本記録は等級を足さない ・変えない", "合成の watermark つきの時だけ許し"),
    "## 9. 端末の payload と識別": ("`home_client:0.2-synthetic` だけ", "完全一致で検査し、他の版は拒む", "表示の方針の識別子であり、digest の\n  domain ではない",
                            "完全性の検査は試験の時に行う", "P13 の code を import して使い、複製しない", "browser は暗号の検証を行わない",
                            "検出は試験と blob の pin に委ねる", "NFC であることを検査し、正規化はしない", "runtime の digest の実装を含まない"),
    "## 10. 時刻": ("`YYYY-MM-DDTHH:MM:SS+00:00` だけ", "`Z` の接尾 ・小数の秒 ・空白の区切り ・UTC の offset の欠落 ・0 でない offset ・暦として不正な値 ・2099 年でない",
                 "正規表現と整数の算術だけで行う", "JavaScript の `Date` による parse は使わない", "JST（UTC に 9 時間を足す算術）", "相対の表現（「○分前」）は使わない",
                 "`as_of` の見出しは常に表示する", "報告の順は 形 → 暦 → 年", "文字列でない値は時刻の検査に届かず TYPE_MISMATCH"),
    "## 11. 表示の状態と fail closed": ("5 つ（SUPPRESSED ・EMPTY ・UNAVAILABLE ・PARTIAL ・AVAILABLE）", "本記録は状態を足さない ・\n  方針を変えない",
                               "後継が無ければ MISSING（`SUCCESSOR_MISSING`）", "前の版を\n  代わりに示さない", "検証は描画の前に行う",
                               "§12 の code だけを出し、前の表示と memory の参照を消す。部分の描画は無い", "全ての項目は SUPPRESSED", "古い data を今のものとして見せない",
                               "INTEGRITY_FAILURE の entry が在るのに `snapshot_status` が OK なら STATE_RECOMPUTE_MISMATCH（入力の拒否）",
                               "該当する入力と整合の検証が全て通った後にだけ認める"),
    "## 12. 失敗の code": ("閉じた集合だけ", "値 ・本文 ・path を含まない", "試験の時の失敗であり、端末の code ではない", "本記録の改訂と guard の更新を要する",
                       "A. 入力の不正 ・検証の拒否 25 ・B. 有効な fail closed の結果 1（SNAPSHOT_FAILED_CLOSED）・C. 描画の失敗 1（RENDER_ABORTED）・計 27",
                       "検証の段（1 〜 10）は最初に当たった失敗で止める", "端末は最初に当たった失敗の code を 1 つだけ出す",
                       "契約が定めた欄の順と配列の順で決める（辞書の走査の順 ・browser の\n  振る舞いに依らない）", "試験は診断のために複数の違反を集めてよい",
                       "FAILED_CLOSED の宣言は先の検証の失敗を覆さない", "参照の検査は snapshot の中で閉じる（外部の照会 ・network は無い）",
                       "`SUCCESSOR_MISSING` は有効な MISSING の entry の理由であり、\n  本記録の失敗の code ではない"),
    "## 13. 合成の識別と watermark": ("`syn_fx_` で始まる", "全ての id は `syn_` で始まる", "全ての日時は 2099 年", "pin した許可の一覧に在る",
                              "全ての状態（通常 ・EMPTY ・UNAVAILABLE ・失敗の code の表示）で出す", "他の要素で覆われない"),
    "## 14. browser の証拠": ("`about:blank` の tab に先に attach", "60 秒の idle", "正確な回数は要件にしない。要件は認可の無い試みが 0 であること",
                          "OS の水準の隔離は無く", "profile の削除は監督の明示の承認の後だけ"),
    "## 15. 静的と実行時の保証": ("Safari ・WebKit ・実機の iPhone", "accessibility の自動の検査は使えることを証明しない", "決定論はその browser の版についてだけ"),
    "## 16. H1 の受け入れの契約": ("本 gate では走らせない", "WebRTC の観測は要件にしない", "44×44 CSS px 以上", "4.5:1 以上", "自動の合否ではない"),
    "## 17. 禁止": ("売買の推奨 ・確率 ・順位 ・score ・目標株価 ・おすすめ ・注目銘柄 ・最新", "根拠の無い確信の語（確実 ・必ず）", "不確実 は使ってよい",
                 "OS の水準の隔離の主張 ・CSP だけで隔離を証明したとの主張"),
    "## 18. 境界（H1 ・M1 ・deploy）": ("H1 が主張しないこと", "password は無い", "Pages は使わない", "本記録は deploy を承認しない"),
    "## 19. 延期と依存": ("H0-D2: 項目ごとの正確な key の集合と上限", "PROVISIONAL(S0) のまま", "feasibility の試験の後", "A5-W ・A6 は HOLD のまま"),
    "## 20. 本記録の承認の範囲": ("文書 ・registry ・guard だけ", "P13-A4b の凍結の runtime ・H0-D1 の記録は変わらない", "本記録は実装を承認しない"),
}
#: 脅威 model の 10 行（# → 脅威 ・対処）
M0_THREATS = {
    "1": ("実の data が fixture ・asset に入る", "`synthetic` が true でない ・`syn_` でない id ・架空 ／ 合成 で始まらない label を拒む ・private な形の走査"),
    "2": ("prototype を実の市場の情報と取り違える", "全ての画面に「合成データ・投資判断に使えない」の watermark ・日付は 2099 年"),
    "3": ("誤って公開の面に載る", "公開の面が参照しない専用の path ・boundary の guard ・Pages ・Cloudflare ・artifact に出さない"),
    "4": ("network の利用 ・第三者の読み込み", "CSP の `connect-src 'none'` ・外部の font ・CDN ・analytics は無い ・静的な走査"),
    "5": ("browser に data が残る", "保存と cache の API を禁じる ・一時の profile"),
    "6": ("fixture の文字列による XSS", "閉じた schema ・有界な欄の形 ・template ・`textContent` だけ"),
    "7": ("資格情報", "存在しない ・server を使う場合は資格情報の変数が在れば起動を拒む"),
    "8": ("LAN への露出", "LAN に配らない ・listener は無い（`file://`）"),
    "9": ("禁止の意味が UI に入る", "H0-D1 §14 の禁止の欄 ・語を検証器が拒む"),
    "10": ("H1 を M1 の準備と取り違える", "H1 が主張しないことの明示（§18）"),
}
M0_STORAGE = {"localStorage": "禁止", "sessionStorage": "禁止", "IndexedDB": "禁止", "cookie": "禁止", "Cache Storage": "禁止", "service worker": "禁止",
              "URL ・history の state": "禁止", "memory の変数": "読み込みごとに fixture を読み直す ・失敗で参照を消す"}
M0_CSP = {"default-src": "'none'", "script-src": "'sha256-…'（inline の script の hash だけ）", "style-src": "'sha256-…'（inline の style の hash だけ）",
          "connect-src": "'none'", "img-src": "'none'", "font-src": "'none'", "media-src": "'none'", "object-src": "'none'", "frame-src": "'none'",
          "worker-src": "'none'", "manifest-src": "'none'", "base-uri": "'none'", "form-action": "'none'"}
M0_GRADES = {"PUBLIC_SAFE": "出す", "PRIVATE_DERIVED": "出す ・「非公開表示（合成）」の badge を付ける", "PRIVATE_AUTHORITY": "fixture は無効 ・snapshot 全体を fail closed",
             "NEVER": "fixture は無効 ・snapshot 全体を fail closed"}
#: 端末の失敗の code の閉じた集合（§12 の表と完全一致 ・code → 意味）
M0_ERROR_CODES = {
    "FIXTURE_BLOCK_INVALID": "fixture の block が無い ・JSON として読めない",
    "SCHEMA_VERSION_MISMATCH": "`schema_version` が `home_client:0.2-synthetic` でない",
    "UNKNOWN_KEY": "閉じた key の集合の外の key",
    "MISSING_KEY": "必須の key の欠落",
    "TYPE_MISMATCH": "値の型が契約と違う",
    "BOUND_EXCEEDED": "大きさ ・長さ ・入れ子 ・項目ごとの entry の件数の上限の超過（6 つの項目の数 ・順 ・重複は ITEM_ORDER_INVALID）",
    "NOT_NFC": "文字列が NFC でない",
    "NOT_SYNTHETIC": "`synthetic` が true でない",
    "SYNTHETIC_ID_INVALID": "id が `syn_` で始まらない ・`fixture_id` が `syn_fx_` で始まらない",
    "SYNTHETIC_LABEL_INVALID": "label が 架空 ／ 合成 で始まらない",
    "SYNTHETIC_YEAR_INVALID": "日時が 2099 年でない",
    "TIME_FORMAT_INVALID": "§10 の形でない",
    "TIME_CALENDAR_INVALID": "暦として不正",
    "AFTER_AS_OF": "`acquired_at` または `issued_at` が `as_of` より後",
    "ITEM_ORDER_INVALID": "6 つの項目の数 ・順 ・重複が契約と違う",
    "FORBIDDEN_FIELD": "H0-D1 §14 の禁止の欄",
    "FORBIDDEN_WORD": "H0-D1 §14 の禁止の語 ・表示の文の確信の語",
    "GRADE_FORBIDDEN": "PRIVATE_AUTHORITY ・NEVER の data が在る",
    "GRADE_CEILING_EXCEEDED": "項目の等級の上限を超える",
    "STATE_RECOMPUTE_MISMATCH": "宣言した状態と再計算が違う ・INTEGRITY_FAILURE の entry が在るのに `snapshot_status` が OK",
    "RENDER_STATE_MISMATCH": "宣言した表示の状態と再計算が違う",
    "COVERAGE_MISMATCH": "coverage と再計算が違う",
    "REFERENCE_UNRESOLVED": "後継 ・宣言した鮮度の窓 ・証拠の参照が snapshot の中で解けない",
    "SUCCESSOR_CYCLE": "後継の鎖が循環する",
    "CLAIM_RULE_VIOLATION": "FACT ／ HYPOTHESIS の規則の違反",
    "SNAPSHOT_FAILED_CLOSED": "`snapshot_status` が FAILED_CLOSED（有効な fail closed の結果 ・全ての項目は SUPPRESSED ・入力の拒否ではない）",
    "RENDER_ABORTED": "描画の途中の例外（表示を消して止める）",
}
#: 決定論の検証の順（§12 の番号つきの列挙と完全一致 ・段 1 〜 10 が入力の拒否 25 ・段 11 が有効な fail closed の結果 1 ・段 12 が描画の失敗 1）
M0_VALIDATION_ORDER = (("解析", ("FIXTURE_BLOCK_INVALID",)),
                       ("封筒と構造", ("SCHEMA_VERSION_MISMATCH", "NOT_SYNTHETIC", "UNKNOWN_KEY", "MISSING_KEY", "TYPE_MISMATCH", "BOUND_EXCEEDED", "NOT_NFC")),
                       ("合成の識別", ("SYNTHETIC_ID_INVALID", "SYNTHETIC_LABEL_INVALID")),
                       ("時刻", ("TIME_FORMAT_INVALID", "TIME_CALENDAR_INVALID", "SYNTHETIC_YEAR_INVALID", "AFTER_AS_OF")),
                       ("項目", ("ITEM_ORDER_INVALID",)),
                       ("語彙", ("FORBIDDEN_FIELD", "FORBIDDEN_WORD")),
                       ("等級", ("GRADE_FORBIDDEN", "GRADE_CEILING_EXCEEDED")),
                       ("主張", ("CLAIM_RULE_VIOLATION",)),
                       ("参照", ("REFERENCE_UNRESOLVED", "SUCCESSOR_CYCLE")),
                       ("再計算", ("STATE_RECOMPUTE_MISMATCH", "RENDER_STATE_MISMATCH", "COVERAGE_MISMATCH")),
                       ("有効な fail closed の結果", ("SNAPSHOT_FAILED_CLOSED",)),
                       ("描画", ("RENDER_ABORTED",)))
M0_N_RULES = {
    "N1": "page が始めた全ての request ・navigation ・WebSocket（CDP）は許可の集合 { pin した `file` の URL, `about:blank` } だけ。回数は問わない。他の URL は 0",
    "N2": "失敗した読み込みは 0（失敗も試みである）・WebSocket ・EventSource の接続は 0",
    "N3": "実行の間の CSP 違反の報告は 0。加えて正の control: hash の無い inline の script を 1 つ持つ変種が実行されないこと",
    "N4": "承認された場合だけ NetLog: 非 loopback への成功した接続 0 ・成功した DNS の解決 0。browser 自身の失敗した試みは件数と分類を報告し、隠さない",
    "N5": "`index.html` の静的な走査: §7 の禁止の API ・要素 ・属性 ・URL の形が 0 件",
}
M0_GUARANTEES = {"静的な走査": ("禁止の API ・URL が書かれた code に無い", "実行の時の振る舞い"), "CSP": ("page の中の禁止の source を browser が止める", "browser 自身の通信 ・拡張 ・navigation"),
                 "CDP の観測": ("その browser の版 ・その実行で観測した事実", "全ての code の経路 ・browser の内部の通信"),
                 "DNS ・proxy の flag": ("その browser の process の試みを失敗させる", "試みが無いこと"), "OS の水準の閉じ込め": ("無し", "無し")}
M0_BANNED = ("実装を承認する", "実装を承認した", "H1 を承認する", "H1 は GO", "M1 は GO", "実の data を使う", "実の data に接続する", "本番で使う", "deploy を承認する",
             "hosting を承認する", "公開を承認する", "Pages に出す", "LAN に配る", "認証を実装する", "token を保存する", "password を保存する", "保存を許す", "fetch を許す",
             "network を許す", "OS の水準で隔離", "隔離を証明した。", "隔離は証明済み", "browser が digest を検証", "pipe は検証済み", "検証済みの pipe",
             "S0 を確定した", "A6 は完了", "Market Memory v1 は凍結した", "署名済み", "http://", "https://")
M0_BANNED_PATTERNS = (r"(?:H0-D2|H1|M1|M0-D1|S0-D1|UI0|A5-W|A6|pytest|commit|push)[^\n|]{0,8}=\s*GO\b",   # 実装 ・実行の権限
                      r"'self'|'unsafe-(?:inline|eval)'",                                              # CSP の弱化
                      r"Date\(",                                                                      # JavaScript の Date の parse
                      r"--remote-debugging-port",                                                     # 認可の無い fallback の transport
                      r"scenario の数は\s*\d", r"\d\s*[%％]", r"(?i)rashinban|compass",
                      r"`(?!home\.(?:snapshot|client)\.v0\.2`)[a-z0-9_.]*home\.[a-z0-9_.]*`",
                      r"`(?!home_(?:snapshot|client):0\.2-synthetic`)[a-z0-9_]*home_[a-z_]+:[^`\n]*`",
                      r"\b(?:jq|p\d+)_[a-z0-9]+_(?:private|work)\b", r"\\\\[A-Za-z0-9.-]+\\")


def _m0_record_violations(text: str) -> list:
    """mobile の security と access の契約の記録の違反（空なら適合）。"""
    found = []
    threats = _a5t_table(text, "## 3. H1 の脅威 model", r"\d+")
    if tuple(threats) != tuple(M0_THREATS) or any(len(r) != 1 or tuple(r[0]) != M0_THREATS[k] for k, r in threats.items()):
        found.append(("THREATS", tuple(threats)))
    storage = _a5t_table(text, "## 6. 保存", "|".join(re.escape(k) for k in M0_STORAGE))
    if tuple(storage) != tuple(M0_STORAGE) or any(len(r) != 1 or r[0] != [M0_STORAGE[k]] for k, r in storage.items()):
        found.append(("STORAGE", tuple(storage)))
    csp = _a5t_table(text, "## 7. network と CSP", r"[a-z]+-(?:src|uri|action)")
    if tuple(csp) != tuple(M0_CSP) or any(len(r) != 1 or r[0] != [M0_CSP[k]] for k, r in csp.items()):
        found.append(("CSP", tuple(csp)))
    grades = _a5t_table(text, "## 8. 等級ごとの表示", r"[A-Z_]+")
    if tuple(grades) != tuple(M0_GRADES) or any(len(r) != 1 or r[0] != [M0_GRADES[k]] for k, r in grades.items()):
        found.append(("GRADES", tuple(grades)))
    codes = _a5t_table(text, "## 12. 失敗の code", r"[A-Z_]+")
    if tuple(codes) != tuple(M0_ERROR_CODES) or any(len(r) != 1 or r[0] != [M0_ERROR_CODES[k]] for k, r in codes.items()):
        found.append(("ERROR_CODES", tuple(codes)))
    order = [(m.group(1), m.group(2), tuple(m.group(3).split(" ・")))
             for m in (re.match(r"^  (\d+)\. ([^:]+): (.+)$", line) for line in _a5_section(text, "## 12. 失敗の code").splitlines()) if m]
    if ([int(n) for n, *_ in order] != list(range(1, len(M0_VALIDATION_ORDER) + 1)) or [(label, codes) for _, label, codes in order] != list(M0_VALIDATION_ORDER)
            or sorted(c for *_, cs in order for c in cs) != sorted(M0_ERROR_CODES)):                 # 各 code がちょうど 1 つの段に在る
        found.append(("VALIDATION_ORDER", tuple(order)))
    rules = _a5t_table(text, "## 14. browser の証拠", r"N[1-9]")
    if tuple(rules) != tuple(M0_N_RULES) or any(len(r) != 1 or r[0] != [M0_N_RULES[k]] for k, r in rules.items()):
        found.append(("N_RULES", tuple(rules)))
    guarantees = _a5t_table(text, "## 15. 静的と実行時の保証", "|".join(re.escape(k) for k in M0_GUARANTEES))
    if tuple(guarantees) != tuple(M0_GUARANTEES) or any(len(r) != 1 or tuple(r[0]) != M0_GUARANTEES[k] for k, r in guarantees.items()):
        found.append(("GUARANTEES", tuple(guarantees)))
    found += [("MISSING", needle) for needle in M0_REQUIRED if needle not in text]
    for heading, needles in M0_SECTION_REQUIRED.items():
        section = _a5_section(text, heading)
        found += [("SECTION", heading, needle) for needle in needles if needle not in section]
    prohibited = _a5_section(text, "## 17. 禁止")
    outside = text.replace(prohibited, "") if prohibited else text                                  # 禁止の語は §17 の外に無い
    found += [("FORBIDDEN_FIELD", field) for field in H0_FORBIDDEN_FIELDS
              if re.search(r"(?<![A-Za-z0-9_])" + re.escape(field) + r"(?![A-Za-z0-9_])", outside)]
    found += [("FORBIDDEN_WORD", word) for word in H0_FORBIDDEN_WORDS if word in outside]
    found += [("CERTAINTY", span) for span in re.findall(r"「([^「」\n]*)」", text) if re.search(H0_CERTAINTY_PATTERN, span)]
    found += [("S0_VOCABULARY", word) for word in H0_S0_VOCABULARY if re.search(r"(?<![A-Za-z0-9_])" + word + r"(?![A-Za-z0-9_])", text)]
    found += [("BANNED", banned) for banned in M0_BANNED if banned in text]
    found += [("PATTERN", pattern) for pattern in M0_BANNED_PATTERNS + PRIVATE_PATTERNS if re.search(pattern, text)]
    if re.search(r"\b(?:is|are|was|were|been)\s+(?:digitally\s+|cryptographically\s+)?signed\b", text, re.IGNORECASE):
        found.append(("SIGNED", "claim"))
    return found


def test_m0_d1_mobile_security_access_contract_is_a_guarded_documentation_only_record() -> None:
    text = (REPO_ROOT / M0_D1_DOC).read_text(encoding="utf-8")
    assert _m0_record_violations(text) == []
    assert PHASE13_DOCS[-1] == M0_D1_DOC and PHASE13_DOCS.index(M0_D1_DOC) == PHASE13_DOCS.index(H0_D1_DOC) + 1   # H0-D1 の記録の直後に登録
    assert all(doc not in (H0_D1_DOC, M0_D1_DOC) for *_, doc in PHASE13_RUNTIME_AUTHORIZATION)       # 実装 ・runtime の認可は無い
    assert not any(gate.startswith(("H0", "H1", "M0", "M1", "S0", "UI0")) for gate, *_ in PHASE13_RUNTIME_AUTHORIZATION)
    assert len(PHASE13_RUNTIME) == 12 and not any("home" in path or "mobile" in path for path in PHASE13_RUNTIME)
    assert _git("hash-object", "--", H0_D1_DOC).strip() == H0_D1_BLOB                               # H0-D1 の記録の byte は変えない（作業木 ・HEAD）
    assert _blobs("HEAD", [H0_D1_DOC])[H0_D1_DOC] == H0_D1_BLOB
    assert len(M0_ERROR_CODES) == 27 and all(re.fullmatch(r"[A-Z_]+", code) and meaning for code, meaning in M0_ERROR_CODES.items())
    ordered = [code for _, codes in M0_VALIDATION_ORDER for code in codes]
    assert len(M0_VALIDATION_ORDER) == 12 and len(ordered) == 27 == len(set(ordered)) and set(ordered) == set(M0_ERROR_CODES)   # 各 code はちょうど 1 つの段
    assert sum(len(codes) for _, codes in M0_VALIDATION_ORDER[:10]) == 25                                                        # 入力の拒否 25
    assert M0_VALIDATION_ORDER[10][1] == ("SNAPSHOT_FAILED_CLOSED",) and M0_VALIDATION_ORDER[11][1] == ("RENDER_ABORTED",)       # 有効な結果 1 ・描画 1
    stage = {code: index for index, (_, codes) in enumerate(M0_VALIDATION_ORDER) for code in codes}
    assert stage["TYPE_MISMATCH"] < stage["TIME_FORMAT_INVALID"] and stage["STATE_RECOMPUTE_MISMATCH"] < stage["SNAPSHOT_FAILED_CLOSED"]
    assert ordered.index("TIME_FORMAT_INVALID") < ordered.index("TIME_CALENDAR_INVALID") < ordered.index("SYNTHETIC_YEAR_INVALID")
    assert ordered.index("GRADE_FORBIDDEN") < ordered.index("GRADE_CEILING_EXCEEDED")
    assert set(M0_GRADES) == {"PUBLIC_SAFE", "PRIVATE_DERIVED", "PRIVATE_AUTHORITY", "NEVER"} and len(M0_THREATS) == 10 and len(M0_N_RULES) == 5
    assert all(value == "'none'" for directive, value in M0_CSP.items() if directive not in ("script-src", "style-src"))   # hash 以外は全て none
    accepted = {                                                                                     # 正の control: 正当な限界 ・延期の文は拒まない
        "limitation_statement": text + "\n- 本記録は実機の iPhone での振る舞いを検証しない。\n",
        "deferral_statement": text + "\n- 認証の方式の決定は M1 に延期する。\n",
        "contract_obligation_must": text + "\n- 失敗の code の集合は必ず本記録と一緒に改訂する。\n",
        "uncertainty_in_display_text": text + "\n- 表示の文の例: 「架空の見通しには不確実な点が在る」。\n",
        "observed_not_enforced": text + "\n- 隔離は観測した事実であり、OS が強制したものではない。\n",
        "failed_closed_valid_statement": text + "\n- FAILED_CLOSED の snapshot は有効な fail closed の結果であり、入力の不正ではない。\n",
        "reserved_code_statement": text + "\n- GRADE_CEILING_EXCEEDED は H0-D1 の上限が全て PRIVATE_DERIVED の間は到達しない予約の code である。\n",
    }
    for name, candidate in accepted.items():
        assert candidate != text and _m0_record_violations(candidate) == [], name


def test_m0_d1_negative_controls_reject_weakened_or_overclaimed_contracts() -> None:
    text = (REPO_ROOT / M0_D1_DOC).read_text(encoding="utf-8")
    assert _m0_record_violations(text) == []
    lines = text.splitlines(keepends=True)
    row = {key: next(line for line in lines if line.startswith(f"| {key} |"))
           for key in ("4", "5", "8", "localStorage", "service worker", "connect-src", "script-src", "PRIVATE_AUTHORITY", "NEVER", "N1", "N3",
                       "CDP の観測", "OS の水準の閉じ込め", "NOT_SYNTHETIC", "RENDER_ABORTED", "AFTER_AS_OF", "REFERENCE_UNRESOLVED",
                       "SNAPSHOT_FAILED_CLOSED", "BOUND_EXCEEDED")}
    mutated = {                                                                                      # 名前 → (拒むべき規則, 改変した記録)
        "csp_connect_self": ("CSP", text.replace(row["connect-src"], row["connect-src"].replace("'none'", "'self'"))),   # CSP の弱化 ・外への access
        "csp_unsafe_inline": ("CSP", text.replace(row["script-src"], row["script-src"].replace("'sha256-…'（inline の script の hash だけ）", "'unsafe-inline'"))),
        "csp_directive_removed": ("CSP", text.replace(row["connect-src"], "")),
        "csp_self_anywhere": ("PATTERN", text + "\n- style は 'self' でもよい。\n"),
        "external_url": ("BANNED", text + "\nhttps://example.invalid/fonts\n"),
        "network_allowed": ("BANNED", text + "\n- 読み込みの後の fetch を許す。\n"),
        "threat_network_removed": ("THREATS", text.replace(row["4"], "")),
        "storage_allowed": ("STORAGE", text.replace(row["localStorage"], row["localStorage"].replace("| 禁止 |", "| 許可 |"))),   # 保存の API の許可
        "service_worker_allowed": ("STORAGE", text.replace(row["service worker"], row["service worker"].replace("| 禁止 |", "| shell だけ許可 |"))),
        "storage_row_removed": ("STORAGE", text.replace(row["localStorage"], "")),
        "storage_prose_permits": ("BANNED", text + "\n- 一時の保存を許す。\n"),
        "threat_storage_removed": ("THREATS", text.replace(row["5"], "")),
        "private_authority_displayed": ("GRADES", text.replace(row["PRIVATE_AUTHORITY"], row["PRIVATE_AUTHORITY"].replace("fixture は無効 ・snapshot 全体を fail closed", "出す ・badge を付ける"))),
        "never_displayed": ("GRADES", text.replace(row["NEVER"], row["NEVER"].replace("fixture は無効 ・snapshot 全体を fail closed", "出す"))),
        "grade_row_removed": ("GRADES", text.replace(row["NEVER"], "")),
        "grade_vocabulary_extended": ("GRADES", text.replace(row["NEVER"], row["NEVER"] + "| INTERNAL | 出す |\n")),
        "authentication_in_h1": ("SECTION", text.replace("H1 に認証は無い。account ・password ・token ・OAuth ・session は無い。", "H1 は簡単な password の認証を持つ。")),   # 認証 ・token
        "token_stored": ("BANNED", text + "\n- 端末に token を保存する。\n"),
        "authentication_implemented": ("BANNED", text + "\n- H1 で認証を実装する。\n"),
        "hosting_authorized": ("BANNED", text + "\n- 本記録は hosting を承認する。\n"),                   # hosting ・deploy
        "deploy_authorized": ("BANNED", text + "\n- deploy を承認する。\n"),
        "pages_exposure": ("BANNED", text + "\n- prototype は Pages に出す。\n"),
        "lan_exposure": ("BANNED", text + "\n- 検証のため LAN に配る。\n"),
        "deploy_disclaimer_removed": ("SECTION", text.replace("本記録は deploy を承認しない。", "")),
        "os_isolation_claimed": ("BANNED", text + "\n- 隔離は証明済み。\n"),                             # OS の隔離の主張
        "os_isolation_claimed_2": ("BANNED", text + "\n- browser は OS の水準で隔離される。\n"),
        "os_guarantee_row_claims": ("GUARANTEES", text.replace(row["OS の水準の閉じ込め"], row["OS の水準の閉じ込め"].replace("| 無し | 無し |", "| 全ての通信を止める | 無し |"))),
        "isolation_disclaimer_removed": ("MISSING", text.replace("OS の水準の隔離を主張しない", "OS の水準の隔離を提供する")),
        "csp_proves_isolation": ("MISSING", text.replace("CSP だけで隔離を証明したとは主張しない", "CSP が隔離を証明する")),
        "cdp_observation_overclaimed": ("GUARANTEES", text.replace(row["CDP の観測"], row["CDP の観測"].replace("全ての code の経路 ・browser の内部の通信", "無し"))),
        "browser_crypto_claimed": ("MISSING", text.replace("browser は暗号の検証を行わない", "browser は暗号の検証を行う")),   # browser の暗号の主張
        "browser_digest_verified": ("BANNED", text + "\n- browser が digest を検証する。\n"),
        "date_parsing": ("PATTERN", text + "\n- 時刻は Date(text) で読む。\n"),                        # Date の parse ・時刻の形の drift
        "date_rule_removed": ("SECTION", text.replace("JavaScript の `Date` による parse は使わない。", "")),
        "time_format_drift": ("MISSING", text.replace("`YYYY-MM-DDTHH:MM:SS+00:00`", "`YYYY-MM-DD HH:MM:SS`")),
        "fractional_seconds_allowed": ("SECTION", text.replace("`Z` の接尾 ・小数の秒 ・空白の区切り ・UTC の offset の欠落 ・0 でない offset ・暦として不正な値 ・2099 年でない", "`Z` の接尾 ・空白の区切り ・暦として不正な値")),
        "relative_time_allowed": ("SECTION", text.replace("相対の表現（「○分前」）は使わない。", "相対の表現を使ってよい。")),
        "watermark_removed": ("MISSING", text.replace("「合成データ・投資判断に使えない」", "「合成」")),   # watermark の欠落
        "watermark_not_all_states": ("SECTION", text.replace("全ての状態（通常 ・EMPTY ・UNAVAILABLE ・失敗の code の表示）で出す", "通常の状態で出す")),
        "synthetic_only_removed": ("MISSING", text.replace("合成の data だけ", "data")),
        "threat_real_data_removed": ("THREATS", text.replace("| 1 | 実の data が fixture ・asset に入る |", "| 1 | 実の data を読む |")),
        "certainty_in_display_text": ("CERTAINTY", text + "\n- 表示の文の例: 「架空の指数は確実に上がる」。\n"),   # 根拠の無い確信の語
        "must_in_display_template": ("CERTAINTY", text + "\n- template: 「架空の theme は必ず反発する」。\n"),
        "market_word_in_prose": ("FORBIDDEN_WORD", text + "\n- 本記録は注目銘柄を扱わない。\n"),
        "numeric_likelihood": ("PATTERN", text + "\n- base の見込みは 60% 。\n"),
        "s0_finalized": ("BANNED", text + "\n- S0 を確定した。\n"),                                     # S0 の確定
        "s0_count_fixed": ("PATTERN", text + "\nscenario の数は 2 つに確定する。\n"),
        "s0_vocabulary_defined": ("S0_VOCABULARY", text + "\n- 条件の判定は PENDING から始める。\n"),
        "provisional_removed": ("MISSING", text.replace("PROVISIONAL(S0)", "確定")),
        "real_data_authority": ("BANNED", text + "\n- 実の data に接続する。\n"),                        # 実 data ・実装の権限
        "implementation_claim": ("BANNED", text + "\n本記録は実装を承認する。\n"),
        "implementation_disclaimer_removed": ("MISSING", text.replace("本記録は実装を承認しない", "本記録は実装の始まり")),
        "h1_authority": ("PATTERN", text + "\nH1 = GO\n"),
        "m1_authority": ("PATTERN", text + "\nM1 = GO\n"),
        "pipe_claimed_verified": ("BANNED", text + "\n- pipe は検証済み。\n"),                         # CDP の transport
        "debugging_port_fallback": ("PATTERN", text + "\n- 失敗したら --remote-debugging-port=0 に戻す。\n"),
        "fallback_rule_removed": ("SECTION", text.replace("debugging port の transport への fallback は監督の別の承認を要する。", "")),
        "error_code_added": ("ERROR_CODES", text.replace(row["RENDER_ABORTED"], row["RENDER_ABORTED"] + "| SOFT_WARNING | 警告だけで描く |\n")),   # 閉じた code の集合
        "error_code_removed": ("ERROR_CODES", text.replace(row["NOT_SYNTHETIC"], "")),
        "error_code_renamed": ("ERROR_CODES", text.replace(row["NOT_SYNTHETIC"], row["NOT_SYNTHETIC"].replace("| NOT_SYNTHETIC |", "| NOT_SYNTH |"))),
        "closed_set_statement_removed": ("SECTION", text.replace("端末の検証と描画の失敗の code は次の閉じた集合だけ。", "端末の失敗の code は次のものを含む。")),
        "partial_render_allowed": ("SECTION", text.replace("§12 の code だけを出し、前の表示と memory の参照を消す。部分の描画は無い。", "読めた項目だけを描く。")),
        "render_states_extended": ("SECTION", text.replace("SUPPRESSED ・EMPTY ・UNAVAILABLE ・PARTIAL ・AVAILABLE", "SUPPRESSED ・EMPTY ・UNAVAILABLE ・PARTIAL ・AVAILABLE ・CACHED")),
        "old_version_shown": ("SECTION", text.replace("前の版を\n  代わりに示さない", "前の版を\n  代わりに示す")),
        "n1_exact_count": ("N_RULES", text.replace(row["N1"], row["N1"].replace("回数は問わない。他の URL は 0", "文書の request はちょうど 1 回"))),   # 証拠の規則
        "n3_positive_control_removed": ("N_RULES", text.replace(row["N3"], row["N3"].replace("。加えて正の control: hash の無い inline の script を 1 つ持つ変種が実行されないこと", ""))),
        "n_rule_removed": ("N_RULES", text.replace(row["N3"], "")),
        "idle_window_removed": ("SECTION", text.replace("60 秒の idle", "idle")),
        "profile_auto_cleanup": ("SECTION", text.replace("profile の削除は監督の明示の承認の後だけ", "profile は実行の後に自動で削除する")),
        "h0_blob_pin_removed": ("MISSING", text.replace("ce5fbce76b30b700c58b619452fbf8f1433c3c81", "ce5fbce76b30b700c58b619452fbf8f1433c3c80")),   # H0-D1 ・schema ・domain
        "client_schema_changed": ("MISSING", text.replace("`home_client:0.2-synthetic`", "`home_client:0.3`")),
        "domain_with_product_name": ("PATTERN", text.replace("`home.client.v0.2`（投影）", "`rashinban.home.client.v0.2`（投影）")),
        "render_policy_as_domain": ("SECTION", text.replace("表示の方針の識別子であり、digest の\n  domain ではない", "digest の\n  domain でもある")),
        "exact_schema_implemented": ("SECTION", text.replace("項目ごとの正確な key と上限は H0-D2 が持つ", "項目ごとの正確な key と上限は本記録が定める")),
        "section_heading_changed": ("SECTION", text.replace("## 14. browser の証拠", "## 14. 証拠")),
        "private_path": ("PATTERN", text + "\n" + "Z:" + "\\p99_a9_private\n"),                     # private な形
        "private_timestamp": ("PATTERN", text + "\n" + "2099-01-05" + "T07:30\n"),
        "private_bare_number": ("PATTERN", text + "\n値は " + "12345" + "\n"),
        "private_identifier": ("PATTERN", text + "\np9wat_0123\n"),
        "signed_claim": ("SIGNED", text + "\nThe fixture is signed.\n"),
        "acquired_code_name_restored": ("ERROR_CODES", text.replace(row["AFTER_AS_OF"], row["AFTER_AS_OF"].replace("| AFTER_AS_OF |", "| ACQUIRED_AFTER_AS_OF |"))),   # E2: 改名 ・意味 ・順
        "successor_code_name_restored": ("ERROR_CODES", text.replace(row["REFERENCE_UNRESOLVED"], row["REFERENCE_UNRESOLVED"].replace("| REFERENCE_UNRESOLVED |", "| SUCCESSOR_UNRESOLVED |"))),
        "failed_closed_as_rejection": ("ERROR_CODES", text.replace(row["SNAPSHOT_FAILED_CLOSED"], row["SNAPSHOT_FAILED_CLOSED"].replace("有効な fail closed の結果 ・全ての項目は SUPPRESSED ・入力の拒否ではない", "入力の不正"))),
        "bound_includes_item_count": ("ERROR_CODES", text.replace(row["BOUND_EXCEEDED"], row["BOUND_EXCEEDED"].replace("項目ごとの entry の件数の上限の超過（6 つの項目の数 ・順 ・重複は ITEM_ORDER_INVALID）", "件数の上限の超過"))),
        "time_precedence_swapped": ("VALIDATION_ORDER", text.replace("TIME_FORMAT_INVALID ・TIME_CALENDAR_INVALID ・SYNTHETIC_YEAR_INVALID ・AFTER_AS_OF", "SYNTHETIC_YEAR_INVALID ・TIME_FORMAT_INVALID ・TIME_CALENDAR_INVALID ・AFTER_AS_OF")),
        "grade_precedence_swapped": ("VALIDATION_ORDER", text.replace("GRADE_FORBIDDEN ・GRADE_CEILING_EXCEEDED", "GRADE_CEILING_EXCEEDED ・GRADE_FORBIDDEN")),
        "validation_stage_removed": ("VALIDATION_ORDER", text.replace("  11. 有効な fail closed の結果: SNAPSHOT_FAILED_CLOSED\n", "")),
        "first_failure_rule_removed": ("SECTION", text.replace("端末は最初に当たった失敗の code を 1 つだけ出す。", "端末は全ての失敗の code を出す。")),
        "inconsistent_status_rule_removed": ("SECTION", text.replace("INTEGRITY_FAILURE の entry が在るのに `snapshot_status` が OK なら STATE_RECOMPUTE_MISMATCH（入力の拒否）。", "")),
        "classification_count_altered": ("SECTION", text.replace("検証の拒否 25", "検証の拒否 24")),
    }
    for name, (rule, candidate) in mutated.items():
        assert candidate != text, name
        assert rule in {violation[0] for violation in _m0_record_violations(candidate)}, name     # 該当の規則が実際に拒む
