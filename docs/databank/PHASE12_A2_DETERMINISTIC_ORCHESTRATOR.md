# Phase 12 P12-A2 — Deterministic local orchestrator（networkless ・派生だけ ・成功は ledger の commit だけ）

本文書は P12-A2 の狭い contract である。**Phase 12 の凍結ではない**。

- 基準: P12-A1 の commit `dd922c3eebd67de2ac273ba66e82e493d814e701`（A1 の 11 file は A2 以後も object 一致 ・guard が pin）
- P11 の意味 ／ runtime の凍結 anchor（不変）: `43c0b856d41efed397de213a1a06178c5e97ab10`（runtime 側の宣言 `frozen_anchors.py` と test の
  registry の両方が同じ 12 file の blob を持つ）
- A2 の runtime（`src/intelligence/automation/`、1 file ＝ 1 責務）:

| file | 責務 |
|---|---|
| `execution_request` | 完全に明示の `AutomationExecutionRequest`（PIT の欄は全て caller。A1 の RunIdentity で run_id を再計算） |
| `preconditions` | 決定論の前提条件（順 ・最初の失敗で止まる ・安全な code だけ） |
| `frozen_anchors` | 凍結 P11 の anchor と 12 file の blob ・`git_blob_id` ・P11 runtime の manifest |
| `source_manifests` | P9 ／ P10 root の読み取り専用の manifest（安全な表現に path は無い） |
| `snapshot_orchestrator` | 凍結 P11 の `read_ui_model` → `ui_model_json_bytes` の派生の snapshot（昇格しない） |
| `server_readiness` | 凍結 P11 の `LocalServer` を一時的に loopback で起こして probe → 止める |
| `network_deny` | network の拒否の guard（loopback は readiness の間だけ） |
| `finalization` | `.partial` だけに書き ・照合 ・原子的 rename ・`FINALIZED_PENDING_LEDGER` |
| `execution_result` | 純粋 ・安全な `AutomationExecutionResult`（telemetry は意味の欄の外） |
| `run_executor` | A1 の step の順で 5 step を走らせる orchestrator（失敗 → 以後 SKIPPED） |

## 1. Orchestrator の責務と networkless の保証

`execute_run(request, roots, *, repo_root, runtime_root, environment, policy, clock)`:

PRECONDITIONS → ROOT_MANIFESTS → P11_MODEL_SNAPSHOT → SERVER_READINESS → FINALIZATION（A1 の `STEP_ORDER`）。各 step は
`AutomationStepResult` を 1 つ出す。ある step が失敗すれば、失敗 code を記録し、以後の step は決定論に `SKIPPED`、成功の artifact は
昇格しない（P12 root さえ作らない）。例外は投げず、安全な結果を返す。

- **networkless**: 各 step は自分の `network_guard` の中で走る。guard は `socket.socket.connect` ・`connect_ex` ・`socket.create_connection` ・
  `socket.getaddrinfo`（DNS）を差し替え、宛先が loopback でなければ `INTERRUPTED:NETWORK_DENIED` で止める（`urllib` ・`http.client` も
  その上に乗る）。読み込み済みの J-Quants の client ／ transport の class の構築も止める。loopback を許すのは SERVER_READINESS の間だけ。
  policy に external を許す欄は無い。
- 予約した資格情報（`JQUANTS_API_KEY` ほか `JQUANTS_` の接頭辞）が環境に非空で在れば `CREDENTIAL_PRESENT`（値は比較以外に使わず、
  記録しない）。`datetime.now` ・`selection_clock` は読まない（PIT は要求の欄だけ。telemetry の時計は caller の `clock` 依存）。
- git は読み取りの引数の list だけ（`rev-parse` ・`status --porcelain`）。push ・commit ・checkout ・repo の書き込みは無い。
- Task Scheduler ・scheduler ・持続する server の lifecycle ・browser ・公開 ・LLM は無い。

## 2. 前提条件の model

順: REQUEST_IDENTITY → CREDENTIAL_ABSENT → NETWORK_POLICY → REPO_HEAD → REPO_CLEAN → P11_FROZEN → P9_ROOT → P10_ROOT → P12_ROOT。
code: `SCHEMA_INVALID:<detail>` ・`CREDENTIAL_PRESENT` ・`REPO_HEAD_MISMATCH`（HEAD ≠ 要求の runtime_anchor ・git 不在は
`:GIT_UNAVAILABLE`）・`REPO_NOT_CLEAN`（未追跡も汚れ）・`FROZEN_DRIFT:P11`（worktree の byte の blob ≠ 凍結 anchor の blob）・
`ROOT_MISSING:P9` ／ `:P10`（在って読める directory でない）・`ROOT_MISSING:P12`（明示の root が無く、親も無い）。git の stdout ・
stderr ・path ・例外の文は結果に出ない。

## 3. Source manifest の model

`build_root_manifest(root, source_id)` は root の下の通常の file を相対 path（POSIX）の順に歩き、(名前, 大きさ, sha256) を取る。
`content_digest = sha256("p12.source_manifest.v1" + NUL + canonical_json({source_id, files}))`。同じ byte → 同じ digest ・1 byte の変化
→ 違う digest ・歩く順 ・mtime に依らない。symlink ・特殊な file は fail closed。安全な表現は source_id ・file_count ・byte_count ・
content_digest だけ（path 無し）。private な表現（root 相対の名前と digest ・中身は無い）は P12 の run の directory にだけ置く。
P11 runtime の manifest は anchor と 12 file の blob から導く。

## 4. P11 snapshot の導出

`read_ui_model(p10_root, p9_root, at=scheduled_for, as_of_date=as_of_date)`（P11-A1 の governed な read の面だけ。P10 の store ・P9 の
snapshot は直接触れない）→ `ui_model_json_bytes`。`AutomationSnapshot` の安全な metadata: run_id ・scheduled_for ・as_of_date ・P11 の
runtime anchor ・adapter の版 ・model の schema の版 ・model_digest ・entry_count ・focus_count ・mute_count ・excluded_count ・
unmatched_live_marks。private な body（P11 の UI model の正準な byte）は `snapshot.json` として run の directory にだけ置く。
**派生だけ**: P9 ／ P10 の authority には書かず、**昇格しない**。P11 の型つきの失敗は `SOURCE_INCOMPLETE:<P11 code>`。

## 5. Server readiness

凍結 P11 の `LocalServer.start(p10, p9, bind=127.0.0.1, port=0)` を thread で一時的に起こし、`/health` ・`/version` ・static の shell
（`/app/index.html` の byte の blob ＝ 凍結の blob）・明示の `/api/view`（要求の PIT）を loopback の `http.client` で探り、応答の byte を
P11 の定数 ・snapshot の byte と比べ、finally で `shutdown`。失敗は `STEP_FAILED:<DETAIL>`（`SERVER_<起動の code>` ・`HEALTH_MISMATCH` ・
`API_MODEL_MISMATCH` ・`PROBE_IO`）。報告は code と一致の真偽だけ（port は出さない）。持続する lifecycle は A3。browser は無い。

## 6. 原子的な finalize と FINALIZED_PENDING_LEDGER

`<p12_root>/runs/<run_id>.partial/` だけに書く（`open("xb")` ・flush ・fsync ・読み戻して sha256 を照合）→ `digests.json` を最後に書く
→ directory を fsync → `os.rename` で 1 回だけ `<p12_root>/runs/<run_id>/` に替える → 親を fsync。final が既に在れば
`DUPLICATE_INVOCATION:FINAL_EXISTS`、`.partial` が既に在れば `DUPLICATE_INVOCATION:PARTIAL_EXISTS`（黙って消さない ・上書きしない）。
I/O の失敗は `STEP_FAILED:FINALIZATION_IO`（`.partial` は証拠として残る。回復は A4）。

**rename が済んでも成功ではない**。結果の状態は `FINALIZED_PENDING_LEDGER`。`SUCCEEDED` は ledger の record の commit（後の gate）
でだけ生まれる。ledger の record が無い finalize 済みの directory は A1 の `ORPHANED_FINALIZATION` の対象。A2 の結果（step_results ・
artifact_digests ・failure_code）は A1 の `make_record` の入力にそのまま使える。

## 7. Private な artifact の配置（P12 root は明示に渡す。初期化は root と `runs/` だけ）

```
<p12_root>/runs/<run_id>/
  request.json            正準な実行の要求
  manifests.json          P9 ／ P10 の manifest（root 相対の名前と digest。中身は無い）
  snapshot.json           P11 の UI model の正準な byte（派生 ・非 authority）
  snapshot_metadata.json  snapshot の安全な metadata
  readiness.json          readiness の安全な報告
  evidence.json           finalize 前の step の結果 ・manifest の digest ・P11 runtime の manifest
  digests.json            名前 → sha256（最後に書く）
```

全て UTF-8 ・LF ・正準 JSON ・末尾の改行 1 つ。絶対 path ・資格情報 ・browser の profile ・P9 ／ P10 の authority の生の dump は無い。

## 8. 決定論の保証

同じ要求 ・同じ P9 ／ P10 の byte ・同じ P11 の runtime anchor → 同じ run_id ・同じ manifest の digest ・同じ snapshot の byte と
digest ・同じ安全な結果の意味（`semantic_dict`）・byte 一致の artifact（独立な P12 root 同士）。telemetry（started_at ・completed_at）
だけが違い得る。同じ final の directory への 2 回目の実行は fail closed（上書きしない）。

## 9. 安全 ／ private の分離

安全（結果 ・step の結果 ・manifest の safe 表現 ・snapshot の metadata ・readiness の報告）: id ・code ・digest ・件数 ・瞬間だけ。
private（run の directory）: 要求 ・manifest の相対名 ・UI model の byte。どちらにも path ・private な名前 ・例外の文 ・資格情報は無い。

## 10. A2 がしないこと

自分を schedule しない ・暗黙の市場の時計を読まない ・J-Quants を呼ばない ・資格情報を使わない ・P8 ／ P9 ／ P10 ／ P11 の authority を
変えない ・公開しない ・repo を変えない ・git push しない ・外部の network に出ない ・ledger に書かない（record の入力を整えるだけ）・
持続する server を管理しない ・crash ／ orphan を回復しない（A4）。

## 11. 観察 ・debt（A2）

- P12-OBS-005: Windows では directory の fd の fsync が無い（`_fsync_directory` は黙って飛ばす）。rename の原子性は同じ volume の中だけ。
- P12-OBS-006: 鎖の末尾 ・`.partial` の孤児 ・`ORPHANED_FINALIZATION` の検出と回復は A4。
- P12-OBS-007: readiness は一時的な server（port 0）だけ。持続する lifecycle ・Task Scheduler は A3 以後。
- 次は **P12-A3**（監督の GO の後）。
