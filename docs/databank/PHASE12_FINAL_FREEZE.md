# PHASE 12 — AUTOMATION A-TRACK v1 (NETWORKLESS LOCAL SCHEDULING): COMPLETE / CLOSED / FROZEN

Phase 12 の A-track v1（networkless の local scheduling: schedule の authority ・決定論の orchestrator ・追記専用 ledger ・lock ／ 回復 ・
Windows Task Scheduler の統合）の最終凍結の記録（P12-A7 freeze record）。本文書 ・registry ・guard ・CHANGELOG だけの記録であり、
runtime の意味は変えない。この記録の commit は **新しい anchor ではない**。凍結するのは A-track v1 だけ: Phase 12 全体は CLOSED ではない
（B-track の取得 ・P12.5 ・P13 ・P14 は未着手 ・本記録の範囲の外）。

| 項目 | 値 |
|---|---|
| 状態 | **COMPLETE / CLOSED / FROZEN**（Phase 12 A-track v1 だけ） |
| 意味 ／ runtime の凍結 anchor | `e390cddff9101541d16ba308a15d9ad1df3ca7b7`（registry の `P12_A6`。A6 の lock の writer の修正の commit） |
| A6 の検証を走らせた commit | `3056e25586767fd7b5d8095f016a4d254de5c360`（registry の `P12_VALIDATED_TREE`。test と CHANGELOG だけが anchor と違う） |
| 凍結の範囲 | P12-A1 〜 A5.1 ＋ A6 の 2 つの remediation の runtime（登録済みの runtime 43 file ・Phase 12 の test 11 file ・設計文書 6 file） |
| 実機の検証 | P12-A6 real Windows automation validation（repo の外の helper v6 ・10 stage）: **A6_PASS**（利用者の Windows からの報告） |
| 受理した観察 | P12-OBS-001 〜 P12-OBS-027（010 ・014 は未使用。番号は振り直さない） |
| Phase 11 | COMPLETE / CLOSED / FROZEN のまま（`43c0b856d41efed397de213a1a06178c5e97ab10`。runtime 12 file は object 一致） |
| Phase 10 ／ 9 ／ 8 | COMPLETE / CLOSED / FROZEN のまま（`1a7b9a2…` 17 file ・`4c19701…` 18 file ・`0a32d86…` 54 file は object 一致） |
| 公開の面 | GitHub Pages ・公開の report ・Cloudflare ・notifier ・GitHub Actions ・config は `P12_BASE`（`080d42a…`）以後も不変 |

guard: `tests/intelligence/test_automation_boundary.py` の
`test_p12_freeze_the_43_registered_runtime_files_are_object_identical_to_the_anchor_and_the_validated_tree` と
`test_p12_freeze_the_record_holds_no_private_validation_values`（§9）。

---

## 1. anchor ・validated tree ・本記録の関係

- `P12_A6`（`e390cddff9101541d16ba308a15d9ad1df3ca7b7`）で A-track v1 の runtime は確定した。A1 の 11 file は `P12_A1`（`dd922c3…`）以後、A2 の 10 file は
  `P12_A2`（`bd0007d…`）以後、A3 の file は `P12_A3`（`66139db…`）以後 object 一致（A4 ・A5 ・A6 が登録して再開した `crash_classification` ・
  `run_transaction` ・`run_cli` ・`operational_lock` を除く）。A5 ・A5.1 の 6 file と A4 の file は `P12_A6` で確定した。
- `P12_VALIDATED_TREE`（`3056e25586767fd7b5d8095f016a4d254de5c360`）は Windows の P12-A6 の preflight で落ちた 5 件の test だけを直した commit
  （fixture の byte ・symlink の権限 ・lock の模擬 ・boot marker の契約。runtime は不変）。A6 の 10 stage はこの commit で走った。
  runtime 43 file の git の blob は `P12_A6` と `P12_VALIDATED_TREE` で全て同じ（guard が pin する）。
- 本記録の commit は文書 ・registry の定数 ・guard ・CHANGELOG だけを足す。runtime 43 file の blob は anchor と同じ。
- **repo の HEAD は本記録で動く。** A5 の runtime の pin（`authority/runtime_pin.json`）は無人の実行が受け入れる HEAD を記録するので、本記録の
  後に A-track を無人で走らせるには、人の手の `pin-runtime`（clean な HEAD を pin する唯一の経路）で pin を更新してから `scheduler-install`
  する（P12-OBS-016 ・P12-OBS-027）。本記録は private な root ・pin ・ledger ・schedule には触れない。

## 2. 凍結した範囲（A-track v1 ・runtime 43 file）

- A1（11）: `__init__` ・`canonical` ・`failure_codes` ・`holiday_calendar` ・`ledger_model` ・`run_identity` ・`run_planning` ・`run_state` ・
  `schedule_model` ・`status_projection` ・`step_result` — 純粋な domain ／ state の層。
- A2（10）: `execution_request` ・`execution_result` ・`finalization` ・`frozen_anchors` ・`network_deny` ・`preconditions` ・`run_executor` ・
  `server_readiness` ・`snapshot_orchestrator` ・`source_manifests` — 決定論の local orchestrator（凍結の P11 の read の面だけ）。
- A3（9）: `atomic_files` ・`calendar_authority` ・`crash_classification` ・`head_checkpoint` ・`ledger_store` ・`run_cli` ・`run_transaction` ・
  `schedule_authority` ・`status_store` — 運用の commit の層（ledger が commit の authority）。
- A4（7）: `cancel_authority` ・`injection` ・`ledger_commit` ・`operational_lock` ・`process_probe` ・`recovery` ・`retry`。
- A5 ／ A5.1（6）: `runtime_pin` ・`scheduled_run` ・`scheduler_install` ・`skip_transaction` ・`task_definition` ・`task_scheduler_adapter`。
- A6 の remediation（runtime は `operational_lock` だけ）: lock の descriptor に O_BINARY（Windows の text mode が正準な LF を CRLF に変え、
  strict な parser が全ての lock を LOCK_MALFORMED と判定していた）。parser ・分類 ・解放の意味は不変。

## 3. 不変量（最終凍結で再確認）

NETWORKLESS の A-track（A2 の guard が socket ・DNS を拒む。loopback は P11 の readiness の間だけ。J-Quants ・通知 ・公開 ・cloud は無い）／
決定論の private な workflow（PIT は `scheduled_for` から ・正準 JSON ・hash-chained の ledger ・`selection_clock_at` は入口で 1 回だけ ・
`datetime.now` は telemetry だけ）／ 自律の取引 ・順位 ・推奨 ・配分の語彙は無い（境界の guard）／ P9 ・P10 の authority に書かない
（read-only の manifest ・実機で前後の root が不変）／ daemon ・service は無い（Task Scheduler が CLI の process を起こすだけ）／
無人の回復 ・lock の修復は無い（RECOVERY_REQUIRED で止まる ・`release-lock` ／ `recover-*` ／ `retry` は人の手だけ）／ ledger が運用の実行の
authority（status.json ・run の directory は projection ・証拠）／ 資格情報の変数が在れば起動を拒む ・XML に資格情報 ・password を埋めない ／
Phase 4 〜 11 は凍結のまま（anchor を pin）／ HEAD ≠ pin では走らない ・pull ／ fetch ／ checkout はしない。

## 4. P12-A6 の証拠と出所

出所を 3 つに分ける。**repo で検証できる証拠**: anchor ・validated tree ・43 file の blob の一致（guard）・Phase 12 の test suite（Linux の
baseline は 7011 passed ・2 skipped）・A6 の helper の transfer branch と commit ・helper の SHA256 ・helper の Linux self-test（合成の scheduler で
A6_PASS）。**利用者の Windows からの報告**（この Linux の session からは見えない。REPORT の行と archive は利用者の機械にだけ在る）:
10 stage 全て PASS ・preflight の pytest 585 passed ・1 skipped（symlink の権限）・LOCK_LIVE ・O_EXCL の race 10 回 ・12 task × 17 clause の
XML ／ 実効の契約 PASS（COM_UNAVAILABLE=0）・手動の run ・Task Scheduler から起こした run ・重複の 2 層（process ・scheduler）・RECOVERY_REQUIRED の
方針（stale lock ・provenance 不明の lock ・孤児 ・遅れた checkpoint ・partial）と人の手の回復 ・MISSED ／ NON_BUSINESS_DAY ／ NOT_DUE ／ DISABLED ・
ledger 30 record ・12 task の除去 ・無関係な 204 task は不変 ・P9 ／ P10 の root は不変 ・P11 の anchor は不変 ・validation root の archive ・
最終の `A6_PASS`。**未検証の前提**: §7。

## 5. Windows Task Scheduler の往復の所見（A6 で確定。A5 の契約は不変）

- P12-OBS-020: Task Scheduler は登録した task を再直列化し、既定値の要素（RunLevel の LeastPrivilege ・WakeToRun の false ・
  RunOnlyIfNetworkAvailable の false）を省く。検証は「問い合わせた XML の明示の値」か「省略 ＋ COM の実効の値」のどちらかで通し、矛盾 ・
  証拠の不足は失敗にする（契約の緩和ではない。生成する XML は 3 つとも明示に書く）。
- P12-OBS-021: 実効の設定の authority は Task Scheduler の COM の定義（RunLevel 0 ＝ 最小権限 ・WakeToRun False ・RunOnlyIfNetworkAvailable
  False ・LogonType 3 ＝ InteractiveToken）。COM の property は `MultipleInstances`（enum 2 ＝ IgnoreNew）であり、XML の要素名
  `MultipleInstancesPolicy` とは違う（最初の probe は無い property を読んで空を得た）。
- P12-OBS-022: InteractiveToken の task を登録すると、Windows は現在の対話 user の SID を Principal の UserId として注入する。これは
  Windows が管理する task の identity であり、埋め込んだ資格情報ではない。受け入れるのは現在の対話 user に解決し、SYSTEM ・service の
  identity でない時だけ。
- P12-OBS-023: `MultipleInstancesPolicy=IgnoreNew` は問い合わせた XML に明示のまま要求する（Windows は省かない。省略 ・別の値は失敗）。
- P12-OBS-024: 生成する authority（task の XML）に UserId ・Password ・資格情報 ・user 名は無い。user 名が現れてよいのは interpreter ・
  working directory の path の中だけ（per-user の Python の置き場所）。それ以外に現れれば失敗。
- P12-OBS-025: `schtasks /Query /FO CSV /V` の列名は英語の Windows でだけ確認した（enabled ・last result の読み取り）。非英語の locale では
  status の projection の enabled の数と last result が無くなるが、install ・remove ・所有の判定は影響を受けない（ledger が authority）。
- P12-OBS-026: Windows には boot marker が無い（Linux の `/proc` だけ）。再起動による stale の検出は無く、identity の不一致（LOCK_STALE_PID_REUSED）
  と死んだ process（LOCK_STALE_DEAD）で stale を証明する。provenance が証明できなければ LOCK_UNKNOWN_PROVENANCE（fail closed）。
- P12-OBS-027: 検証した機械の interpreter は venv ではない per-user の Python だった（契約は venv を要求しない。runbook は venv を推奨）。
  文書だけの commit でも HEAD は動くので、無人の運用の前に `pin-runtime` で pin を更新する（P12-OBS-016 の運用上の帰結）。

## 6. 外部 helper v6（凍結の外）

P12-A6 の helper（stdlib だけ ・repo の外 ・transfer 専用 branch `transfer/p12-a6-helper-v6` ・commit `8193c17081d2d55443e285cb9663f9dad43c416f` ・
`a6.py` の SHA256 `a8bb4b41963328446201e11326614cad2214b56625573e18e7eba11ca771f7e8` ・`RUNBOOK.txt` の SHA256
`89ee341dfa076dbe1903d92a743cd0120f13cae56809336eb24074e7168c123b`）は検証の道具であり runtime の凍結の一部ではない（P11-A5 の helper と同じ扱い）。
runtime に import しない ・runtime の branch に merge しない。helper は検証の root にだけ書き、P9 ・P10 は manifest で前後の不変を確かめる。

## 7. 制限 ・未検証の前提

- 実機の証拠は利用者の報告（REPORT の行）であり、repo からは再検証できない（P11 と同じ受け入れ方）。
- `schtasks` の CSV の列名は英語の locale でだけ確認（P12-OBS-025）。
- 再起動による stale の検出は Windows では無い（P12-OBS-026）。
- 省略された既定値の検証は COM（PowerShell）に依る。PowerShell が使えない機械では省略の証拠が無く、検証は失敗側に倒れる。
- 検証した interpreter は venv ではない（P12-OBS-027）。
- 全 test suite は repo 内の 1 つの追跡 file（journal）を書き換える（Phase 12 の外 ・以前からの副作用）。commit の前に対象の file だけを復元する。
- Task Scheduler の sleep ／ wake ・ExecutionTimeLimit の実際の打ち切り ・StartWhenAvailable の遅れた起動は実機で観察していない（契約の値は
  XML ／ COM で確認した）。

## 8. 将来の境界

A-track v1 の外（本記録で凍結しない ・完了とも言わない）: B-track（取得 ・J-Quants ・market data）・P12.5 ・P13 ・P14 ・Market Memory ・通知 ・
公開 ・cloud の scheduler ・自動の回復 ・自動の retry。Phase 12 の runtime の変更は、新しい gate と anchor の再設定が無い限り行わない
（`is_phase12_addition` は凍結後、登録済み file の追加だけを認め、修正 ・未登録の追加は受けない）。

## 9. guard

- `P12_A6` ・`P12_VALIDATED_TREE` が正確 ・`P12_BASE` 〜 `P12_A4` の子孫 ・`P12_A6` → `P12_VALIDATED_TREE` → HEAD の順に祖先。
- 登録済みの runtime はちょうど 43 file ・anchor と validated tree の package の file の集合 ＝ 登録 ・package の directory の file ＝ 登録。
- 43 file の git の blob の id が anchor ・validated tree ・index ・worktree で全て同じ。anchor 以後に package は変わっていない ・validated tree
  以後に `src` は変わっていない。本文書は validated tree の後に足された。
- Phase 12 の runtime の修正（M）・未登録の file の追加は `is_phase12_addition` が受けない。
- 本文書に private な値の形（id の接頭辞 ・発行体 ・5 桁の code ・著者 ・瞬間 ・Windows の path ・SID ・user profile ・slot の時刻 ・資格情報の
  変数名）は無い。
