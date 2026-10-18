# Phase 12 P12-A3 — Operational commit layer ＋ manual CLI（ledger が commit の authority）

本文書は P12-A3 の狭い contract である。**Phase 12 の凍結ではない**。

- 基準: P12-A2 の commit `bd0007d3b6684a1e4640a723010e197432939f95`（A2 の 10 file ・A1 の 11 file は A3 以後も object 一致 ・guard が pin）
- P11 の意味 ／ runtime の凍結 anchor（不変）: `43c0b856d41efed397de213a1a06178c5e97ab10`
- A3 の runtime（`src/intelligence/automation/`、1 file ＝ 1 責務）:

| file | 責務 |
|---|---|
| `atomic_files` | 一時 file ＋ fsync ＋ `os.replace` の原子的な置換 ・LF の読み ・追記専用の 1 行の追記 |
| `head_checkpoint` | `ledger/head.json`（record_count ・head_digest ・ledger_version）とその分類 |
| `ledger_store` | live の追記専用 ledger（`ledger/ledger.jsonl`）: 検証 → head で追記 → checkpoint の置換 |
| `status_store` | 検証済みの ledger から `status/status.json` を原子的に再生成 ・古さの分類 |
| `schedule_authority` ／ `calendar_authority` | 運用の schedule ／ 休日 calendar の authority の正準な file I/O（人だけが書く） |
| `crash_classification` | crash の窓の決定論の分類（読むだけ） |
| `run_transaction` | 1 run の運用の transaction（A2 → finalize → ledger の commit → status） |
| `run_cli` | 人の手の CLI（`python -m src.intelligence.automation.run_cli`） |

## 1. ledger が commit の authority（運用の成功の定義）

run が運用上 **SUCCEEDED** なのは、検証に通る commit 済みの ledger の record が SUCCEEDED と言う時だけである。run の directory ・
snapshot ・digests.json ・status.json の存在だけでは成功を立てられない。**status.json は authority ではない**（常に再生成できる ・
消しても authority は失われない）。**run の directory は authority ではない**（ledger の record の無い finalize は
`ORPHANED_FINALIZATION`）。ledger は運用の実行の authority であり、市場 ・source の authority ではない（A1 の原則のまま）。

## 2. Live ledger writer

`LedgerStore(p12_root)`: `ledger/ledger.jsonl`（正準 UTF-8 LF JSONL ・1 行 1 record ・A1 `LedgerRecord`）。
- `open_verified()`: 行を正準として解析（A1 `parse_records`）・鎖を検証（A1 `verify_chain`）・checkpoint を分類。不正は
  `LEDGER_INVALID:<detail>`（`RECORD_NOT_JSON` ・`RECORD_DIGEST_MISMATCH` ・`SEQUENCE_BREAK` ・`CHAIN_BREAK` ・`TAIL_TRUNCATED` ・
  `CHECKPOINT_MISMATCH` ・`CHECKPOINT_MALFORMED` ・`CHECKPOINT_STALE` ・`LEDGER_NOT_LF`）。修復 ・切り捨て ・並べ替え ・書き換えはしない。
- `append(record)`: 直前に再検証し、record の sequence ・previous_record_digest が検証済みの head と一致することを要求（`APPEND_NOT_AT_HEAD`）、
  遷移の合法性を鎖で確かめ、1 行を追記（flush ・fsync ・directory の fsync）、checkpoint を原子的に置換、追記後に再検証した状態を返す。
- 鎖 ＋ checkpoint は改変 ・切り捨ての検出と一貫性だけ（**認証ではない**。両方の file を書き換えられる攻撃者には無力）。

## 3. Head checkpoint（P12-OBS-002 の解消）

`ledger/head.json` ＝ `{schema_version, ledger_version, record_count, head_digest}`。commit 済みの ledger から導き、原子的に置換する。
開く時に照合: count ＝ record 数 かつ digest ＝ head → `CHECKPOINT_OK`。count ＜ record 数 かつ digest ＝ その位置の record →
`CHECKPOINT_STALE`（ledger に正しい新しい尾 ＝ 窓 B）。count ＞ record 数 → `LEDGER_INVALID:TAIL_TRUNCATED`。digest の不一致 →
`LEDGER_INVALID:CHECKPOINT_MISMATCH`。**無い checkpoint**: ledger が空なら fresh（OK）、record があれば `CHECKPOINT_STALE`。遅れた
checkpoint の間、writer は追記を拒む（`LEDGER_INVALID:CHECKPOINT_STALE`。追いつかせるのは A4 の回復）。
これは偶然の divergence ・尾の切り捨ての検出であり、暗号学的な安全ではない。

## 4. Transaction の順（commit point）

```
1. LEDGER_VERIFIED     ledger ＋ checkpoint の検証 ・資格情報の不在 ・重複の分類（ここまで何も書かない）
2. PLANNED_RECORDED    record（→ PLANNED）を追記 ＋ checkpoint
3. RUNNING_RECORDED    record（PLANNED → RUNNING）を追記 ＋ checkpoint
4. EXECUTED            A2 execute_run（成功なら run の directory は原子的に finalize ＝ FINALIZED_PENDING_LEDGER）
5. TERMINAL_RECORDED   record（RUNNING → SUCCEEDED ／ FAILED ・step の結果 ・artifact の digest ・failure code）を追記 ＋ fsync ＋ checkpoint
6. LEDGER_REVERIFIED   file から読み直して鎖 ・checkpoint ・run の状態を再検証（head ＝ 今の record ・状態 ＝ 終端）
7. STATUS_PROJECTED    status.json を原子的に再生成
8. 戻り                SUCCEEDED（6 が SUCCEEDED を言う時だけ）／ FAILED（code）
```

**commit point は 5 の追記の fsync**。6 が通らなければ SUCCEEDED は返さない。7 の失敗は run の成否を変えない（status は authority でない）。
A2 が失敗した run も FAILED の record として commit する（証拠）。例外（process の死）は捕らえない。

## 5. Crash の窓と証拠（A4 が回復。A3 は区別できる証拠だけを残す）

| 窓 | 位置 | 証拠 | 分類（`classify_run`） |
|---|---|---|---|
| A | 4 と 5 の間 | final の directory が在り、ledger の最後が RUNNING | `ORPHANED_FINALIZATION` |
| B | 5 の追記と checkpoint の置換の間 | ledger に正しい尾 ・checkpoint が遅れ | `LEDGER_COMMITTED_CHECKPOINT_STALE` |
| C | 5 ／ 6 と 7 の間 | ledger と checkpoint は一致 ・status が無い ・古い | `STATUS_STALE` |
| D | 7 の後 ・CLI の戻りの前 | 全て一致 | `COMMITTED` |

他の分類: `NOT_STARTED` ・`IN_FLIGHT`（PLANNED ／ RUNNING で directory 無し）・`PARTIAL_PRESENT`（`.partial` ・A4 に予約）・
`FINAL_MISSING`（SUCCEEDED なのに directory が無い）。ledger 自体が不正なら `LEDGER_INVALID:<detail>`。どの状態も証拠を壊さない。

## 6. 重複の振る舞い（実行の前 ・何も書かない）

同じ run_id が ledger で SUCCEEDED → `ALREADY_SUCCEEDED`。final が在って成功の record が無い → `ORPHANED_FINALIZATION`（上書きしない）。
`.partial` が在る → `DUPLICATE_INVOCATION:PARTIAL_EXISTS`（A4 の分類に予約）。ledger で開いている（PLANNED ／ RUNNING）→
`DUPLICATE_INVOCATION:RUN_OPEN`。終端（FAILED ほか）→ `DUPLICATE_INVOCATION:RUN_TERMINAL`（retry は新しい attempt ＝ 新しい run）。

## 7. Status projection（authority ではない）

`write_status` は検証済みの ledger の状態から A1 の純粋な `project_status` を作り、ledger の head（record_count ・head_digest）と
telemetry（generated_at）を添えた正準 JSON を原子的に置換する。`classify_status`: head が ledger と違う ・無い ・壊れている →
`STATUS_STALE`。不正な ledger からは作らない（caller が検証済みの状態を渡す）。安全な欄だけ（path ・private な名前 ・文 ・payload 無し）。

## 8. 人の手の CLI（`run_cli`）

```
python -m src.intelligence.automation.run_cli run --request-file <正準な実行の要求の JSON> --private-root R --p9-root P9 --p10-root P10 --repo-root REPO --runtime-root RT
python -m src.intelligence.automation.run_cli write-schedule --file <schedule.json> --private-root R
python -m src.intelligence.automation.run_cli write-calendar --file <holiday_calendar.json> --private-root R
python -m src.intelligence.automation.run_cli classify --run-id <run_id> --private-root R
```

- PIT の欄は要求の file から来る（暗黙の scheduled_for は無い）。`datetime.now` は telemetry（recorded_at ・generated_at）だけで、
  identity ・PIT ・artifact の byte に影響しない。
- 要求の operator は `human` でなければ `SCHEMA_INVALID:OPERATOR_NOT_HUMAN`。資格情報の変数が在れば orchestration の前に
  `RUN_FAILED CODE=CREDENTIAL_PRESENT`（値は保持しない: 環境は名前 → 有無の写しで渡す）。
- stdout は `REPORT:` の行だけ: `RUN_ID=` ・`STEP <code> <status>` ・`STAGE <stage>` ・`LEDGER_COMMIT_OK RECORDS= HEAD=` ・
  `STATUS_PROJECTION_OK` ・`RUN_SUCCEEDED` ／ `RUN_FAILED CODE=<safe code>`。path ・private な値 ・例外の文は出ない。
  exit code 0 ＝ SUCCEEDED ・1 ＝ FAILED ・2 ＝ 使い方。

## 9. Schedule ／ calendar の authority の file I/O

`authority/schedule.json` ・`authority/holiday_calendar.json`（正準 JSON ・明示の版 ・content_digest を読む時に照合 ・暗黙の既定なし）。
書くのは人だけ（`operator="human"`。自動化の runtime は読むだけ）。既存の版の置換は明示: schedule は `supersedes` ＝ 旧の digest と
version の増加を要求し、旧の byte を `authority/history/` に残してから原子的に置換する。calendar は version の増加と履歴の保存。
schedule_id ／ calendar_id の変更は拒む。読みで `HolidayCalendarReference` との不一致は `CALENDAR_UNAVAILABLE:CALENDAR_REF_MISMATCH`。
network から取らない ・自動更新しない。

## 10. A4 に残すこと

crash の窓 A ／ B ／ C の能動的な回復（ORPHANED_FINALIZATION の record の追記 ・checkpoint の追いつき ・status の再生成）・`.partial` の
孤児の分類と処理 ・lock（同時実行の排除）・retry の自動化 ・idempotency の層。A3 は証拠を残し fail closed にするだけ。

## 11. scheduler が無い理由

A2 の finalize は `FINALIZED_PENDING_LEDGER` で終わる。ledger の commit の層（A3）と回復の層（A4）が無いまま scheduler が無人で run を
作れば、ledger の無い finalize 済みの directory（孤児）が溜まり、運用の成功の定義が崩れる。だから順を A3 ＝ commit ・A4 ＝ 回復 ・
A5 ＝ Task Scheduler に改めた。A3 の CLI は人の手だけ ・background ・network ・資格情報 ・J-Quants ・GitHub ・通知は無い。

## 12. 観察 ・debt（A3）

- P12-OBS-008: 同じ run_id の同時実行は lock が無いので A3 では排除されない（A4 の lock）。
- P12-OBS-009: 窓 B の後の追記は fail closed（`CHECKPOINT_STALE`）。追いつきは A4。
- 次は **P12-A4**（監督の GO の後）。
