# Phase 12 P12-A5 — Windows Task Scheduler integration ＋ unattended hardening

本文書は P12-A5 の狭い contract である。**Phase 12 の凍結ではない**。

- 基準: P12-A4 の commit `dcad07351201ecab44d91acc98740b8833bc3996`（A4 の file は object 一致。A5 が登録して再開した `run_cli` と、A5.1 が
  `preflight` ・`record_request` を公開するために再開した `run_transaction` だけが新しい基準。A1 〜 A3 の pin は変わらない）
- P11 の意味 ／ runtime の凍結 anchor（不変）: `43c0b856d41efed397de213a1a06178c5e97ab10`
- A5 の runtime（`src/intelligence/automation/`）:

| file | 責務 |
|---|---|
| `runtime_pin` | 無人の実行が受け入れる runtime の anchor（`authority/runtime_pin.json`。人が `pin-runtime` で書く） |
| `scheduled_run` | scheduled-run の解決（A1 `plan_run`）・無人の方針 ・exit code の契約 |
| `task_definition` | 決定論の Task Scheduler XML ・名前空間 `\Compass\P12\<schedule_id>\<slot_id>` ・所有の印 `P12_OWNED` |
| `task_scheduler_adapter` | `schtasks` ／ `tzutil` の狭い adapter（引数の list ・timeout ・sanitize）と InMemory の test double |
| `scheduler_install` | install の計画 ・登録 ・P12 所有の task だけの削除 ・安全な status |
| `skip_transaction`（A5.1） | 意味の skip（MISSED ・NON_BUSINESS_DAY）を ledger に PLANNED → SKIPPED で commit する transaction |
| `run_cli`（再開） | `scheduled-run` ・`pin-runtime` ・`scheduler-install` ／ `-remove` ／ `-status` |

## 1. 構成

Task Scheduler → `python -m src.intelligence.automation.run_cli scheduled-run --slot-id <slot> --private-root … --p9-root … --p10-root …
--repo-root … --runtime-root …` → `scheduled_run` の解決 → A3 ／ A4 の transaction（lock ・ledger の commit ・回復の分類）。slot ごとに 1 task。
Task Scheduler は market の意味を持たない: 起こすだけ。enabled ・local_time ・weekday_mask ・late window ・休日 calendar の参照 ・意味の
scheduled_for は全て P12 の schedule authority から来る。長く走る daemon ・service ・cloud の scheduler は無い。

## 2. 時間の規則（A0）

process の入口で `selection_clock_at` を 1 回だけ観測し、どの slot の instance が eligible かを決めるだけに使う（A1 `plan_run`）。
`scheduled_for` は authority から導き、as_of_date ・session_date ・run の identity ・source の選択は全て scheduled_for から。telemetry の時計
（recorded_at ・generated_at）は別で、意味に影響しない。`datetime.now` が PIT ・market の日 ・snapshot の source ・identity を直接決めることは
無い。`--selection-clock-at` は人の診断の明示の上書き（task の定義は渡さない）。

## 3. 窓 ・missed ・睡眠 ・結果の証拠（A5.1 ・監督の lock）

候補は今日と昨日の instance。時計以前の最新の候補が無ければ NOT_DUE（exit 0 ・ledger に書かない: 意味の run ではない）。候補の late window の中
（両端を含む）→ eligible。候補の `scheduled_for + late window` の後 → MISSED: **その instance の PLANNED → SKIPPED を ledger に commit する**
（`skip_transaction` ・failure_code `OUTSIDE_WINDOW:MISSED` ・A2 の実行 ・artifact は無い ・exit 4）。backfill ・近い slot の選択 ・曖昧な推定は
しない。StartWhenAvailable=true で遅れて起きても、まだ意味的に有効かは P12 の late window が決める。睡眠で run を逃せば MISSED として記録される:
scheduled_for を起きた時刻に変えることは無い。

結果 → ledger の方針（v1）: NOT_DUE ・DISABLED ＝ 書かない（authority が証拠）。MISSED ・NON_BUSINESS_DAY（readiness を許さない slot）＝ SKIPPED
の終端を commit。ALREADY_SUCCEEDED ＝ 書かない（既存の SUCCEEDED が authority）。DUPLICATE_ACTIVE ＝ 書かない（RUNNING ＋ lock が証拠）。
RECOVERY_REQUIRED ＝ 書かない（crash の証拠を不変に保つ）。Task Scheduler の履歴は補助の telemetry であり、MISSED ・NON_BUSINESS_DAY の証拠に
P12 は依存しない。status.json だけの偽の skip はしない。

skip の transaction: 1 ledger ＋ checkpoint の検証 ・重複の分類 → 2 run の lock → 3 要求の証拠 → 4 PLANNED → 5 PLANNED → SKIPPED → 6 再検証 →
7 status の再生成 → 8 lock の解放。identity は通常の run と同じ（attempt 1）。同じ instance の 2 度目の起動は記録済みの終端に解決する
（`ALREADY_SKIPPED:<code>` ・同じ exit ・attempt 2 は作らない）。retry の意味は SKIPPED には無い。

## 4. 週末 ・休日

人が書いた休日 calendar の authority だけ（network の lookup は無い）。無い ・参照と違う → fail closed（AUTHORITY_INVALID ・exit 7）。
非営業日は slot の `readiness_on_non_business_day` が真なら A1 の意味で readiness だけの run、偽なら ledger に PLANNED → SKIPPED を commit
（failure_code `NON_BUSINESS_DAY:HOLIDAY` ／ `:WEEKEND` ・exit 0）。schedule は変えない。

## 5. Task の定義（決定論の XML ・UTF-16 ・CRLF）

名前 `\Compass\P12\<schedule_id>\<slot_id>`、Author `P12`、Description に所有の印 `P12_OWNED schedule_digest=…`、URI ＝ 名前。
週の CalendarTrigger（weekday_mask ・local_time ・固定の基準の月曜）。StartBoundary は機械の local time（offset 無し）なので、install は
`tzutil /g` が `Tokyo Standard Time` を返す機械だけを受ける（schedule authority の timezone ＝ Asia/Tokyo）。
Principal: InteractiveToken（利用者が logon している時だけ ・password を保存しない）・LeastPrivilege（昇格なし ・SYSTEM ・Administrator 不要）。
Settings: MultipleInstancesPolicy=IgnoreNew（重複の最終の防御は A4 の lock）・StartWhenAvailable=true ・WakeToRun=false ・
DisallowStartIfOnBatteries=false ・StopIfGoingOnBatteries=false（networkless の軽い処理）・ExecutionTimeLimit=PT30M ・
RunOnlyIfNetworkAvailable=false ・Hidden=false。Exec: Command ＝ install の時に人が渡す Python の interpreter（venv の python.exe を推す）、
Arguments ＝ CLI の引数（path だけ ・private な payload ・資格情報 ・HEAD は無い）、WorkingDirectory ＝ repo。XML は P12 root の
`scheduler/` にだけ置き、安全な出力には task 名と XML の digest しか出さない。

## 6. install ／ remove ／ status（人だけ）

- `pin-runtime --private-root --repo-root`: clean な repo の今の HEAD を pin に書く。文書だけの commit でも HEAD は変わるので、無人の実行を
  続けるには再 pin が要る（v1 の意図: 検証した code だけが走る。task の再 install は要らない: XML は HEAD を持たない）。
- `scheduler-install … --interpreter <python> [--apply]`: 検証済みの schedule authority から全 slot の定義を作り、安全な計画（名前 ・slot ・
  enabled ・digest）を REPORT する。`--apply` が在る時だけ XML を置いて登録する。
- `scheduler-remove --private-root [--apply]`: authority から導いた P12 の名前だけを、query した XML に所有の印が在る時だけ削除する
  （wildcard ・無関係な task は触らない。印の無い同名は NOT_OWNED として残す）。
- `scheduler-status --private-root`: scheduler_installed ・expected_task_count ・installed_task_count ・enabled_task_count ・enabled_slot_count ・
  last_scheduler_result_code ・recovery_required（ledger の分類）。path ・Windows の account ・command line は出ない。非 authority。

## 7. 無人の方針（監督の lock）

scheduler は **自動で**: stale な lock を解放しない ・壊れた lock を直さない ・孤児を回復しない ・遅れた checkpoint を直さない ・partial を
rename しない ・CRASHED ／ FAILED を retry しない。回復が要る状態（不正な ledger ・CHECKPOINT_STALE ・ORPHANED_FINALIZATION ・PARTIAL_EXISTS ・
RUN_OPEN ・RUN_TERMINAL ・LOCK_STALE ・LOCK_UNKNOWN_PROVENANCE ・LOCK_MALFORMED ・前の attempt の存在）では何もせず `RECOVERY_REQUIRED`
（exit 5）で止まり、証拠を触らない。人の手の `release-lock` ・`recover-*` ・`repair-checkpoint` ・`regenerate-status` ・`retry` が要る（A4）。
生きた lock の重複 ・ledger lock の待ちの超過は `DUPLICATE_ACTIVE`（exit 6）。古い status だけなら transaction が最後に再生成するので進む。

## 8. exit code の契約（Task Scheduler は stdout を読まない）

| exit | 意味 |
|---|---|
| 0 | SUCCEEDED、安全な no-op（NOT_DUE ・DISABLED ・ALREADY_SUCCEEDED）、または記録した skip（NON_BUSINESS_DAY） |
| 1 | transaction が FAILED（A2 の step の失敗: repo が汚れている ・凍結の drift ・root 不在 ・readiness の失敗など。ledger に FAILED として記録） |
| 2 | 使い方の誤り |
| 4 | MISSED（late window の外。ledger に SKIPPED を記録済み ・2 度目は ALREADY_SKIPPED） |
| 5 | RECOVERY_REQUIRED |
| 6 | DUPLICATE_ACTIVE（生きた lock ・ledger lock の待ちの超過） |
| 7 | AUTHORITY_INVALID（schedule ・calendar ・pin ・slot） |
| 8 | PRECONDITION_REFUSED（資格情報が在る ・HEAD ≠ pin。transaction の前 ・ledger に書かない） |

routine な SKIPPED は 0（Task Scheduler の「最後の結果」を失敗で汚さない）。REPORT 行で code を区別する。

## 9. 安全な log

stdout は `REPORT:` 行だけ（`SCHEDULED_RUN SLOT= OUTCOME= CODE=` ・`RUN_ID=` ・STEP ・STAGE ・`EXIT=`）。path ・環境の値 ・Windows の user 名 ・
資格情報 ・private な payload ・P9 ／ P10 の内容 ・生の例外 ・command line は出ない。private な診断は P12 root の中だけ。

## 10. repo ／ runtime の pin ・network の無さ

HEAD ≠ pin ・汚れた repo ・凍結の P11 の drift ・P9 ／ P10 root 不在 ・不正な authority では走らない。`git pull` ・`fetch` ・`checkout` ・code の
更新はしない: 自動化は在る code を走らせる。A2 の network の guard はそのまま（DNS ・web ・GitHub ・Windows の cloud の呼び出し ・通知 ・
telemetry は無い。loopback は P11 の readiness だけ）。`JQUANTS_API_KEY` ほか予約した資格情報が在れば exit 8 で止まる。鎖 ・checkpoint は
改変の検出だけ（**認証ではない**）。

## 11. cancel ・強制終了

A4 の協調的な cancel の authority を scheduled-run も尊重する。Task Scheduler の「終了」・process の kill は異常な中断であり、次の起動は
A4 の規則で証拠を分類して RECOVERY_REQUIRED で止まる。

## 12. Windows の前提（A6 の実機で確かめる）

`tzutil /g` ＝ `Tokyo Standard Time`、`schtasks /Create /TN <name> /XML <file> /F` が UTF-16 の XML を受ける、`/Query /TN <name> /XML` と
`/FO CSV /V` の列名（Status ・Last Result ・Scheduled Task State）、InteractiveToken の task が logon 中に起きる、IgnoreNew の重複の扱い、
StartWhenAvailable の遅れた起動、ExecutionTimeLimit の挙動、O_EXCL の lock ・rename ・開いた file の削除の挙動、`tasklist` ／ CIM の
process の問い合わせ、venv の python.exe を Command に置けること。

## 13. A6 の計画（実機 ・人の手。task を手で作らせない）

runbook の概念: (1) `pin-runtime` (2) `scheduler-install`（計画の確認）→ `--apply` (3) `scheduler-status` (4) `scheduled-run` を手で 1 回起こし
exit code と REPORT を確かめる（NOT_DUE ・eligible ・MISSED を `--selection-clock-at` で） (5) Task Scheduler から 1 回起こす（logon 中）
(6) 重複の起動（同じ task を 2 度）→ 1 つだけ commit (7) 強制終了 → 次の起動が RECOVERY_REQUIRED (8) `scheduler-remove --apply`。
A5 の helper は P11-A5 の形（stdlib ・repo の外）を踏襲し、probe の一覧を A6 の gate で確定する。

## 14. 範囲の外

J-Quants ・P12-B1 の取得 ・通知 ・公開 ・cloud の scheduler ・自動の回復 ・自動の retry ・password を保存する task ・SYSTEM ／ 昇格 ・
機械が Tokyo 以外の time zone の運用。

## 15. 観察 ・debt（A5）

- P12-OBS-015: trigger は機械の local time。Tokyo 以外の機械は install で拒む（offset 付きの StartBoundary の挙動は A6 で調べる）。
- P12-OBS-016: 文書だけの commit でも再 pin が要る（意図的 ・v1）。
- P12-OBS-017: scheduler-status の `last_scheduler_result_code` は Task Scheduler の「最後の結果」の生の整数（exit code の契約で読む）。
- P12-OBS-018（A5.1 で解消）: MISSED ・NON_BUSINESS_DAY は ledger に SKIPPED として記録する。NOT_DUE ・DISABLED だけが記録を持たない（意味の run ではない）。
- 次は **P12-A6**（監督の GO の後）。
