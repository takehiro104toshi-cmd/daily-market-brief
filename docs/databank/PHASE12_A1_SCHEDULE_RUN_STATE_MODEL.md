# Phase 12 P12-A1 — Schedule authority ／ run identity ／ state model（純粋な domain の層）

本文書は P12-A1 の狭い contract である。**Phase 12 の凍結ではない**（Phase 12 は A1 から始まる。凍結は後の gate）。

- P12 の基準（P11 の凍結の記録の commit）: `P12_BASE = 080d42aa3dad8bfc5ef82400beb6e2c62a873126`
- P11 の意味 ／ runtime の凍結 anchor（不変）: `43c0b856d41efed397de213a1a06178c5e97ab10`（12 file。object 一致を P12 の guard も確かめる）
- package: `src/intelligence/automation/`（11 file。全て純粋な model と関数）
- registry: `tests/intelligence/phase12_runtime_registry.py`（`PHASE12_RUNTIME` ・`PHASE12_TESTS` ・`PHASE12_DOCS` ・
  `PHASE12_TEST_REGISTRATION`）

## 0. A1 に無いもの（監督の lock）

A1 は domain ／ state の層だけである。**scheduler は無い** ・subprocess の orchestration は無い ・server の起動は無い ・socket は無い ・
Task Scheduler の統合は無い ・network は無い ・資格情報は読まない ・file は書かない（CLI も無い）。stdlib の import は
`dataclasses` ・`datetime` ・`enum` ・`hashlib` ・`json` ・`re` ・`typing` だけ。凍結の Phase 4 〜 11 の package は import しない。
J-Quants ／ P8-B5C の自動化は v1 の後（P12-B1）であり、A1 の model はそれを前提にしない。

## 1. Schedule authority は運用の authority（市場の authority ではない）

`AutomationSchedule` は「いつ runtime を走らせてよいか」を人が宣言したものである。これは**運用の authority** であり、
**市場の authority ではない**: 営業日 ・session の意味 ・市場の時点の意味は、schedule が決めるのではなく、`scheduled_for` と
休日 calendar から導かれる。schedule が何を言おうと、凍結の P8 〜 P11 の意味 ・時点 ・source の選択は変わらない。

| model | 欄 |
|---|---|
| `AutomationSchedule` | `schema_version` ・`schedule_id` ・`version` ・`timezone` ・`enabled` ・`slots` ・`holiday_calendar_ref` ・`created_at` ・`supersedes` ・`content_digest` |
| `ScheduleSlot` | `slot_id` ・`local_time`（`HH:MM`）・`weekday_mask`（正準の順 ・空でない ・既定なし）・`late_window_seconds`（0 以上 ・24 時間未満 ・既定なし）・`readiness_on_non_business_day` ・`enabled` |
| `HolidayCalendarReference` | `calendar_id` ・`version` ・`content_digest` |
| `HolidayCalendar` | `schema_version` ・`calendar_id` ・`version` ・`dates`（`YYYY-MM-DD` ・sort 済み ・重複なし）・`content_digest` |

- timezone は v1 で `Asia/Tokyo` だけ。暗黙の timezone は無い（欠ければ `SCHEMA_INVALID`）。Asia/Tokyo は DST を持たないので
  固定の `+09:00` を名前付きの timezone として使う（tzdata に依らず Windows でも決定論。`zoneinfo` は使わない）。
- 正準 JSON: 鍵の sort ・区切りの空白なし ・`ensure_ascii=False` ・float は拒む。`content_digest` は digest 自身を除いた正準 JSON の
  domain 付き sha256（`"p12.automation_schedule.v1" + NUL + canonical_json`）。**hash-addressed** であって署名ではない。
- 未知の鍵 ・欠けた鍵 ・型の違い ・順の乱れ ・digest の不一致は全て fail closed（`AutomationError("SCHEMA_INVALID", <detail>)`）。
- `schedule_id` は人の鍵（`[a-z][a-z0-9_-]{0,39}`）。版の identity は `content_digest`。`supersedes` は前の版の digest（説明。identity ではない）。
- `created_at` は人が宣言した aware な瞬間（内容の一部）。時計ではない。

## 2. 計画（純粋 ・時計を読まない）

`plan_run(schedule, calendar, *, slot_id, selection_clock_at, operator, prior_runs, attempt)` → `PlannedRun` か `NonRun`。

- **時計の分離**: `selection_clock_at` は caller が渡す、slot の選択に影響してよい唯一の壁時計の観測である。planner は `now()` を
  呼ばない（naive な瞬間は `SELECTION_CLOCK_NOT_AWARE`）。それが決めるのは「どの slot の instance（`scheduled_for`）か」だけ。
- **`scheduled_for` だけ**が `as_of_date`（Tokyo の暦日）・`session_date`（その日以前の直近の営業日）・時点 ・市場の意味を決める。
  `started_at` ・`completed_at` ・`recorded_at` は telemetry であり、identity ・時点 ・source の選択 ・出力に影響しない。
- 窓は `scheduled_for <= selection_clock_at <= scheduled_for + late_window_seconds`（両端を含む）。前日の instance の窓が
  日付を跨ぐ場合も見る。窓の中なら時計の値が違っても結果は同じ。
- 非 run の結果（code だけ）: `DISABLED`（schedule ／ slot）・`OUTSIDE_WINDOW`（窓外 ・`WEEKDAY_NOT_IN_MASK`）・`NON_BUSINESS_DAY`
  （週末 ／ 休日で readiness を許さない slot）・`CALENDAR_UNAVAILABLE`（calendar が無い ・参照と不一致 ・session の日が無い）・
  `SLOT_NOT_FOUND` ・`ALREADY_SUCCEEDED`（caller が前の run の要約を渡した時だけ）。
- 非営業日で `readiness_on_non_business_day` が真なら `readiness_only=True` の run（`session_date` は直近の営業日）。
- attempt は渡された前の run の最大 ＋ 1。古い attempt の再利用は拒む（**retry は新しい run**）。operator は `scheduler` ／ `human`。

## 3. Run identity

```
identity = {schedule_id, slot_id, scheduled_for (UTC ISO), runtime_anchor (git の 40 hex), attempt}
run_id   = sha256("p12.automation_run.v1" + NUL + canonical_json(identity))
```

- 含めない: `started_at` ・`completed_at` ・`selection_clock_at` ・可変の status ・成果物の path。同じ予定を別の operator が別の
  時計で再計算しても同じ `run_id` になる（決定論 ・再計算可能 ・domain を分けた衝突耐性のある digest）。
- `retry_of` ・`supersedes` は **metadata**（identity ではない）。理由: retry_of は同じ `scheduled_for` の前の attempt から導ける
  （identity に入れると run_id が前の run の有無に依存し、独立な再計算で食い違う）。supersedes は人の backfill の結び付きで、
  「何が ・どの code で ・何回目に」予定されたかを変えない。どちらも digest で検証し、自己参照 ・attempt 1 の retry は拒む。

## 4. 状態機械

| from | to（合法） |
|---|---|
| `PLANNED` | `RUNNING` ・`SKIPPED` ・`CANCELLED` ・`CRASHED` |
| `RUNNING` | `SUCCEEDED` ・`FAILED` ・`CANCELLED` ・`CRASHED` ・`ORPHANED_FINALIZATION` |
| 終端（`SUCCEEDED` ・`FAILED` ・`SKIPPED` ・`CANCELLED` ・`CRASHED` ・`ORPHANED_FINALIZATION`） | なし（不変） |

表に無い遷移は `IllegalTransition`（`ILLEGAL_TRANSITION:<FROM>_TO_<TO>`。決定論の domain の誤り）。`FAILED → SUCCEEDED` ・
`CRASHED → SUCCEEDED` は無い。**retry は新しい run**（新しい attempt ・新しい run_id）。

### ORPHANED_FINALIZATION の意味

成果物の directory は finalize されているのに、ledger に対応する成功の record が commit されていない状態。これは**成功ではない**
（status の projection は成功として数えない ・`last_successful_run` にならない ・completeness は無い）。検出したら証拠を残す:
**黙って消さない** ・黙って昇格しない ・黙って修復しない。回復（人の確認 ・新しい run）は後の gate の実装であり、A1 は状態と
code を予約するだけ。

## 5. 安全な失敗 code

予約: `REPO_NOT_CLEAN` ・`REPO_HEAD_MISMATCH` ・`FROZEN_DRIFT` ・`ROOT_MISSING` ・`SCHEMA_INVALID` ・`SOURCE_STALE` ・
`SOURCE_INCOMPLETE` ・`DUPLICATE_INVOCATION` ・`OUTSIDE_WINDOW` ・`NON_BUSINESS_DAY` ・`CALENDAR_UNAVAILABLE` ・`INTERRUPTED` ・
`ORPHANED_FINALIZATION`（＋ A1 の domain の code: `DISABLED` ・`SLOT_NOT_FOUND` ・`ALREADY_SUCCEEDED` ・`CANCELLED` ・
`ILLEGAL_TRANSITION` ・`LEDGER_INVALID` ・`SELECTION_CLOCK_NOT_AWARE` ・`WEEKDAY_NOT_IN_MASK` ・`CREDENTIAL_PRESENT` ・`STEP_FAILED`）。

- 安全な code の形は `[A-Z][A-Z0-9_]{2,63}(:[A-Z][A-Z0-9_]{1,63})?`。`AutomationError` の `str` ・`repr` は code（と安全な detail）だけ。
  private な診断（path ・例外の文 ・値）は `private_detail` 属性に留まり、直列化 ・文 ・repr に出ない。安全でない detail は
  `UNSAFE_DETAIL` に置き換える。`Diagnostic` も同じ（等価性 ・repr は code だけ）。

## 6. Step の結果

`AutomationStepResult{step_code, status, artifact_digest, completeness_code, failure_code}`。step の正準の順は
`PRECONDITIONS → ROOT_MANIFESTS → P11_MODEL_SNAPSHOT → SERVER_READINESS → FINALIZATION`。結果の列はその部分列（重複 ・逆転なし）、
`FAILED` の後は `SKIPPED` だけ。自由な payload ・path ・private な値の欄は無い。

## 7. Ledger は実行の証拠（authority ではない）

`LedgerRecord` は run の遷移 1 つ。欄: `record_version` ・`sequence` ・`previous_record_digest` ・`record_digest` ・run の metadata
（`run_id` ・identity の 5 欄 ・`operator`）・`transition_from` ・`transition_to` ・`status` ・`failure_code` ・`step_results` ・
`artifact_digests` ・`recorded_at`（telemetry）。`record_digest = sha256("p12.ledger_record.v1" + NUL + canonical_json(record))`。

- ledger は **実行の証拠** であって、市場の authority でも source の authority でもない。導いた snapshot（P11 の model など）は ledger に
  record があっても **昇格しない**（凍結の authority の store には書かない）。
- **hash 鎖の保証**: `sequence` は 0 から連続 ・`previous_record_digest` は前の record の digest（最初は 64 桁の 0）・digest の
  再計算の一致 ・run ごとの遷移が状態機械に合うこと ・終端の後に record が無いこと。削除（途中）・挿入 ・並べ替え ・改変は
  `LedgerError("LEDGER_INVALID", <detail>)` で検出する（`SEQUENCE_BREAK` ・`CHAIN_BREAK` ・`RECORD_DIGEST_MISMATCH` ・
  `RUN_AFTER_TERMINAL` ・`TRANSITION_FROM_MISMATCH` ・`RUN_NOT_OPENED`）。
- **非保証**: 鎖は **改変の検出**（tamper-evidence）と一貫性だけを与える。**認証ではない** ・**署名ではない**: file 全体を書き換えて
  鎖を作り直せる者に対する真正性は無い。末尾の切り捨ては鎖だけでは見えない（head の digest を外で照合する。後の gate）。
  用語は canonical ／ hash-addressed ／ hash-chained だけを使う（「署名」を意味する語は使わない）。
- finalize された成果物の directory に対応する commit 済みの成功の record が無ければ、それは成功ではなく `ORPHANED_FINALIZATION`。

## 8. Status projection は authority ではない

`project_status(records, *, runtime_anchor, schedule_id, as_of)` → `StatusProjection{runtime_anchor, schedule_id, record_count,
head_digest, last_successful_run, active_run, last_terminal_run, last_failure_code, staleness_class, source_completeness, health_code}`。

- **projection は authority ではない**: ledger の record から導く読みだけであり、file は書かず、run を作らず、authority を変えない。
- 鎖が不正なら fail closed（`LedgerError`）。anchor ・schedule が record と違えば `ANCHOR_MISMATCH` ／ `SCHEDULE_MISMATCH`。
- `staleness_class` は caller が渡す `as_of`（telemetry）と最後の成功の `scheduled_for` の差（24 時間以内 FRESH ・72 時間以内 AGING ・
  それ以上 STALE ・判定できなければ UNKNOWN）。`as_of` が無ければ UNKNOWN（時計は読まない）。
- health: `OK` ・`RUNNING` ・`FAILED` ・`CRASHED` ・`ORPHANED_FINALIZATION` ・`CANCELLED` ・`SKIPPED` ・`NO_RUNS` ・`ANCHOR_MISMATCH` ・
  `SCHEDULE_MISMATCH`。出す欄は id ・code ・瞬間 ・件数だけ。

## 9. Privacy の保証

直列化（schedule ・calendar ・PlannedRun ・AutomationRun ・LedgerRecord ・StatusProjection）・誤りの文 ・repr に、path ・例外の文 ・
free-form な payload ・資格情報 ・private な root の値は出ない。test は Windows の path ・時刻つきの瞬間以外の private な形 ・
5 桁の code ・id の接頭辞の不在を確かめる。

## 10. 凍結の guard の狭い再開（test だけ）

Phase 12 の file を `src` に足すため、凍結の P7 ／ P8 ／ P9 ／ P10 ／ P11 の guard の "since base" の集合に `PHASE12_RUNTIME` ・
`PHASE12_TESTS` ・`PHASE12_DOCS` を加えた（6 file。行を `PHASE12_TEST_REGISTRATION` に完全に列挙し、`test_automation_boundary.py` が
`P12_BASE` との差分の完全一致を pin する）。P11 の guard の pin の対象は `P12_BASE` の時点に切り替えた（P11 の登録は P11 の終わりまで）。
runtime ・凍結の記録 ・P8 〜 P11 の registry は不変。

## 11. 観察 ・debt（A1）

- P12-OBS-001: Asia/Tokyo を固定 `+09:00` で表す（DST 無し）。timezone の拡張は model の版を上げる。
- P12-OBS-002: 鎖の末尾の切り捨ては鎖だけでは検出できない。head の digest の外部の照合は ledger の live の書き手（後の gate）の責務。
- P12-OBS-003: `ALREADY_SUCCEEDED` は caller が前の run の要約を渡す時だけ出る。ledger から要約を作る橋は projection の後の gate。
- 次は **P12-A2**（監督の GO の後）。
