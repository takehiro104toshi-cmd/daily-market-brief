# Phase 12 P12-A4 — Lock ／ retry ／ crash recovery ／ idempotency

本文書は P12-A4 の狭い contract である。**Phase 12 の凍結ではない**。

- 基準: P12-A3 の commit `66139db86e06130d7504a279b3d5ee820fd76b24`（A3 の file は object 一致。A4 が登録して再開した `run_transaction` ・
  `run_cli` の 2 file だけが新しい基準。A1 ・A2 の file は不変）
- P11 の意味 ／ runtime の凍結 anchor（不変）: `43c0b856d41efed397de213a1a06178c5e97ab10`
- A4 の runtime（`src/intelligence/automation/`）:

| file | 責務 |
|---|---|
| `operational_lock` | run ごとの lock と ledger の lock（O_CREAT ｜ O_EXCL ・正準な metadata ・分類 ・stale の解放） |
| `process_probe` | process の生存 ・identity ・起動の token（stdlib ・sanitize ・test は StaticProbe） |
| `ledger_commit` | ledger の commit の直列化（lock の中で head を読み直して record を組む ・有界の待ち ・checkpoint の追いつき） |
| `injection` | 決定論の失敗の注入点（test だけ ・本番は no-op ・乱数なし） |
| `cancel_authority` | 協調的な cancel の要求（人だけが書く正準 JSON） |
| `recovery` | 窓 A ／ B ／ C ／ partial ／ crashed の明示の回復と stale な lock の解放 |
| `retry` | retry の要求の再構成（attempt ＋ 1 ・retry_of） |
| `run_transaction`（再開） | lock ・直列化 ・要求の証拠 ・cancel の検査 ・注入点を transaction に入れた |
| `run_cli`（再開） | retry ・cancel ・recover-* ・repair-checkpoint ・regenerate-status ・release-lock の命令 |

## 1. Lock の model（run の lock ＋ 短い ledger の lock）

2 つの候補（A: run ／ slot ごと、B: global な実行の lock）を比べた。ledger は 1 つの追記専用の authority なので commit は直列化が要るが、
実行（A2: manifest ・snapshot ・loopback の readiness）は run ごとに独立である。選んだのは **run の lock ＋ 短い ledger の lock**:
- `locks/run.<run_id>.lock`: 同じ run_id の同時実行を排除する。transaction の間ずっと持つ。
- `locks/ledger.lock`: 1 回の record の commit の間だけ持つ（検証 → 組む → 追記 ＋ fsync → checkpoint → 再検証 → 解放）。
違う run は同時に実行できる（process が別なら A2 の network の guard も干渉しない）。同じ process の中の thread で別の run を同時に走らせる
ことは想定しない（A2 の guard は process 全体の socket を差し替えるため。test は process 間で確かめた）。

lock の内容は安全な metadata だけ: lock_version ・kind ・run_id ・pid ・process_identity（sha256）・boot_marker（sha256）・acquired_at ・
scheduled_for ・attempt。path ・payload ・資格情報 ・command line ・user 名は無い。

## 2. 原子的な取得

`os.open(path, O_CREAT | O_EXCL | O_WRONLY)`。Windows（CreateFile の CREATE_NEW）・POSIX のどちらでも原子的で、存在の検査 → 作成の race は無い。
2 回目の取得は決定論に `DUPLICATE_INVOCATION:RUN_ACTIVE`（run）／ `:LEDGER_LOCKED`（ledger）。所有者は fd を閉じてから unlink する
（Windows は開いたままの file を消せない）。時刻の比較 ・存在だけの検査 ・pid だけの判断はしない。

## 3. Stale な lock の意味（古いだけでは stale ではない）

`classify_lock`（削除しない）:
- `LOCK_ABSENT` ・`LOCK_MALFORMED`（正準でない ・形が違う: 触らない）
- `LOCK_STALE_REBOOT`: lock の boot_marker と今の boot_marker が共に分かり違う（process は確実に居ない）
- `LOCK_STALE_DEAD`: pid が居ない（POSIX は `os.kill(pid, 0)`、Windows は `tasklist` の問い合わせ）
- `LOCK_STALE_TERMINAL`: pid が居ず、ledger でその run は終端（commit 済みの取り残し）
- `LOCK_STALE_PID_REUSED`: pid は居るが identity（Linux は `/proc/<pid>/stat` の starttime、Windows は CIM の CreationDate）が違う
- `LOCK_UNKNOWN_PROVENANCE`: 生存が分からない ・identity を証明できない → **fail closed**（触らない）
- `LOCK_LIVE`: pid が居て identity が一致（終端の run でも生きていれば LIVE: 解放待ち）
stale と証明できた lock だけを人の手の `release-lock` が `locks/stale/` に rename して証拠を残す。transaction は自動では壊さない
（既に在れば `DUPLICATE_INVOCATION:RUN_ACTIVE` ／ `:LOCK_STALE` ／ `:LOCK_UNKNOWN_PROVENANCE`）。process の死（想定外の例外）では lock は
残り、分類が回復を導く。想定内の失敗の戻りでは解放する。

## 4. Ledger の直列化

`LockedLedger.commit(run_id, builder)`: ledger の lock を取り（他 process が持っていれば最大 30 秒 ・50 ms 間隔で待ち、超えれば
`DUPLICATE_INVOCATION:LEDGER_LOCKED`）、**lock の中で** ledger を読み直して鎖を検証し、`builder(head)` で record を組む（previous_record_digest は
実際の commit 済みの head。lock の前に読んだ head は信用しない）、A3 の store で追記 ＋ fsync ＋ checkpoint ＋ 再検証、解放。
2 process が別の run を同時に走らせても sequence は連続し checkpoint は head と一致する（test: process 間 ・thread 間）。
鎖 ＋ checkpoint は改変の検出だけ（**認証ではない**）。

## 5. Retry の model

retry は常に新しい run: 同じ schedule_id ・slot_id ・scheduled_for ・runtime_anchor、attempt ＝ その identity の ledger の最大の attempt ＋ 1、
`retry_of` ＝ 前の run_id。要求は `requests/<run_id>.json` の証拠から再構成する（PIT ・schedule_digest ・session を保つ）。人は attempt を
与えない。許す source: FAILED ・CRASHED ・ORPHANED_FINALIZATION。拒む: SUCCEEDED（ALREADY_SUCCEEDED）・SKIPPED ・CANCELLED（人の承認の
仕組みは v1 に無い → `NOT_RETRYABLE_*`）・開いている run（lock が生きていれば RUN_ACTIVE ・居なければ RUN_OPEN: 先に回復）。前の run の
directory ・record は変えない。

## 6. Crash の回復（分類が先 ・曖昧なら拒む ・証拠を消さない ・P9 ／ P10 ／ P11 は触れない）

| 状態 | 証拠 | 回復 |
|---|---|---|
| ORPHANED_FINALIZATION（窓 A） | final の directory ・ledger の最後が RUNNING | `recover-orphan`: digests.json と file の sha256 ・request.json の run_id を照合 → RUNNING → ORPHANED_FINALIZATION を commit（artifact の digest を添える）。artifact は証拠として残す。**SUCCEEDED には変えない**（保守的）。その後 retry |
| IN_FLIGHT（PLANNED ／ RUNNING ・directory 無し ・lock は居ない） | | `recover-crashed`: → CRASHED（INTERRUPTED）。lock が生きていれば拒む |
| LEDGER_COMMITTED_CHECKPOINT_STALE（窓 B） | 鎖は正しい ・checkpoint が遅れ ・過去の状態と一致 | `repair-checkpoint`: ledger の lock の中で検証 → checkpoint を今の count ／ head に置換 → 再検証。履歴は変えない |
| STATUS_STALE（窓 C） | | `regenerate-status`: 検証済みの ledger から再生成（authority は変わらない） |
| PARTIAL_PRESENT | `.partial` | `recover-partial`: 分類（ACTIVE ＝ lock が生きている → 拒む ・ABANDONED ＝ ledger が開いている ・ORPHAN ＝ ledger に無い ・MALFORMED）→ `<run_id>.crashed` に rename して保全（消さない）。ABANDONED なら CRASHED も commit |
| 残った lock | | `release-lock`: stale と証明できた時だけ `locks/stale/` へ |

CRASHED ＝ artifact の commit の前に process が止まった。ORPHANED_FINALIZATION ＝ artifact は finalize されたが終端の record が無い。証拠で
区別できるので畳まない。

## 7. Idempotency（force は無い）

同じ成功した要求 → ALREADY_SUCCEEDED。生きた lock の同じ run → DUPLICATE_INVOCATION:RUN_ACTIVE。final ＋ 開いた ledger → ORPHANED_FINALIZATION。
遅れた checkpoint → LEDGER_INVALID:CHECKPOINT_STALE（回復が要る ・新しい実行は無い）。古い status だけ → ledger の状態で進む。同じ attempt の
前の FAILED → DUPLICATE_INVOCATION:RUN_TERMINAL（attempt は再利用しない）。retry は次の attempt。上書きは無い。

## 8. 協調的な cancel（A4 で実装）

`authority/cancel/<run_id>.json`（人だけが書く正準 JSON: run_id ・requested_at ・operator ・reason_code）。transaction は PLANNED の後と
RUNNING の後（実行の前が最後）に見て、要求が在れば CANCELLED の終端を commit する。ledger の追記 ・checkpoint の臨界の中では見ない。実行
（A2）が始まった後は見ない（finalize された run の commit を途中で止めない）。kill の意味は無い。壊れた要求は `SCHEMA_INVALID:CANCEL_MALFORMED`。

## 9. 失敗の注入

`InjectionPoints.fire(point)`（本番は no-op）。点: AFTER_LOCK_ACQUIRED ・AFTER_PLANNED_APPEND ・AFTER_RUNNING_APPEND ・BEFORE_EXECUTION ・
AFTER_FINALIZATION ・AFTER_TERMINAL_APPEND ・AFTER_CHECKPOINT ・BEFORE_STATUS_WRITE ・AFTER_STATUS_WRITE ・BEFORE_LOCK_RELEASE。test は
各点で例外を投げて process の死を模し、分類 ・lock の残り ・回復を確かめる（追記と checkpoint の間は A3 の store の monkeypatch）。

## 10. Windows の注意（A6 の実機で確かめる）

- 取得は O_EXCL（CREATE_NEW）で原子的。解放は閉じてから unlink（開いたままの file は消せない ・他 process の生存の信号にもなる）。
- lock の descriptor は O_BINARY も付けて開く（A6 の実機で判明: text mode の descriptor は正準な LF を CRLF に変え、自身の strict な
  parser が `LOCK_MALFORMED` と判定した。直すのは writer だけ。parser は CRLF を許さない）。
- `.partial` → `.crashed` ・lock → `locks/stale/` の rename は同じ volume の中。開いている file を含む directory の rename は失敗し得る
  （`STEP_FAILED:PARTIAL_RENAME_IO` で fail closed）。
- directory の fsync は無い（黙って飛ばす）。
- process の生存は `tasklist /FI "PID eq N" /FO CSV /NH`、identity は PowerShell の CIM `CreationDate`（数字だけに sanitize）。どちらも
  得られなければ `LOCK_UNKNOWN_PROVENANCE`（fail closed）。boot_marker は Windows では無い（再起動の検出は Linux だけ）。
- POSIX の flock は使わない。

## 11. A5 に残すこと

Task Scheduler の登録と無人の起動 ・無人の時の stale な lock ／ 回復の方針（A4 は人の手の命令だけ）・privacy ／ network の硬化の仕上げ。
scheduler が無人で run を作るのは、この commit ・回復の層の上でだけ。

## 12. 観察 ・debt（A4）

- P12-OBS-011: 同じ process の中で複数の run を thread で同時に走らせることは支援しない（A2 の network guard は process 全体）。
- P12-OBS-012: ledger の lock の待ちは 30 秒で諦める（`DUPLICATE_INVOCATION:LEDGER_LOCKED`）。無人の運用での値は A5 で決める。
- P12-OBS-013（A6 の実機で解消）: Windows の生存（`tasklist`）／ identity（CIM の CreationDate）の問い合わせは実機で健全（identity は安定 ・
  None は無し ・最大でも runtime の 15 秒の timeout より十分に短い）。boot marker は無いので再起動の検出は無い（`PHASE12_FINAL_FREEZE.md` P12-OBS-026）。
- P12-OBS-019（A6 の実機 ・解消）: Windows の `os.open` は O_BINARY が無ければ text mode。lock の writer だけがその経路で、全ての lock が
  `LOCK_MALFORMED`（重複は RECOVERY_REQUIRED ・release-lock ／ recover-* は拒む）になっていた。writer に O_BINARY を足し、
  `operational_lock` を A4 の pin から登録して再開（`PHASE12_A4_REOPENED_IN_A6`）。生存 ／ identity の問い合わせは実機で健全を確認。
- 次は **P12-A5**（監督の GO の後）。
