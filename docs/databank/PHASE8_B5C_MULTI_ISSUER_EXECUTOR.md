# PHASE 8 / P8-B5C — MULTI-ISSUER PRIVATE EXECUTOR / BOUNDED BATCH + CONTINUATION

凍結の部品をつなぐ **別の private な実行器**（`src/intelligence/jquants_screen_local.py`。package の外 ・本番から import されない）を足す gate。
明示の Universe の authority → 明示の方針の authority → D0 の master → 適格 → 審査済みの identity → 発行体の束ね → 有限の fins の取得 → 取得の
authority → 凍結 B4A の評価 → 凍結 B5B の全結果の集合 → 凍結 B5B の安全な投影。凍結 B4B の runner（`jquants_pilot2_local.py`）は検証の基盤の
まま byte 一致。

- 基準: P8-B5B `474b1d9fc83b414edb4557a9d87ad25c6ffa37c4`（凍結。runtime 53）。full pytest の基準 6588 passed ／ 2 skipped。
- 本 gate は合成の transport の test だけ。実 J-Quants ・private の実 data の root ・実の Universe ／ 方針 ・Phase 9 ・Theme ・新しい指標 ・公開の出力 ・
  順位 ・推奨は無い。

---

## 1. 入力（すべて明示）

| 入力 | 規則 |
|---|---|
| `data_root` | 絶対 ・repo ／ `.git` ／ Actions の外の private root |
| Universe の選択子 | 正確な `universe_id` か正確な `(universe_key, universe_version)`（B5A。ちょうど 1 つ） |
| 方針の選択子 | 正確な `policy_id` か正確な `(policy_key, policy_version)`（凍結 B4A の `PolicySelector`） |
| `d0` | `YYYY-MM-DD`（壁時計の日ではない） |
| `evaluation_as_of` | aware ・D0 の JST の日の中。run の宣言の評価の瞬間 |
| `authority_mode` | v1 は `RETROSPECTIVE_PROVIDER_AUTHORITY` だけ（`STRICT_PIT` は `AUTHORITY_MODE_NOT_SUPPORTED`。方針の mode と一致を要求 ・fallback なし） |
| `acquired_at` | この呼び出しの取得の瞬間（aware ・D0 の中 ・`evaluation_as_of` 以下 ・前の呼び出し以上） |
| `budget_limit` | 1〜8（凍結 `RequestBudget` の上限。迂回しない） |
| `continue_run_id` | 継続のときだけ（`start` ／ `continue` の明示） |

## 2. 明示の authority の解決（provider の仕事の前）

B5A の Universe の store の `validate` → read-only → 正確な record（無い ・破損 ・分類の違いは `UNIVERSE_*`）。B3 の方針は凍結 B4A の
`open_verified_store` ＋ `resolve_policy`（`POLICY_AUTHORITY_UNAVAILABLE`）。authority の store（identity は必須 ・他は無ければ空で作る）の
破損は `AUTHORITY_STORE_UNAVAILABLE`。すべて network の前。

## 3. `ScreenRunSpec` ・`run_id`

spec ＝ Universe の id ・版 ・member（宣言の順）・方針の id ・版 ・mode ・D0 ・評価の瞬間（JST に正規化）・作業の順の規則 ・経路の規則 ・規則の版の束ね
（LIVE1 の適格 ・B4A の orchestration ／ 投影 ・B5A ・B5B の全結果 ／ 投影）・schema ・rules。`run_id = "p8run_" + sha256(canonical_json(spec))[:24]`。
時計 ・batch の番号 ・path ・取得の瞬間に依らない。継続は同じ引数から spec を再計算し、`continue_run_id` と台帳の spec の両方と完全一致しなければ
`RUN_SPEC_MISMATCH`（network の前）。開始は台帳が既にあれば `RUN_ALREADY_STARTED`（継続は明示）。

## 4. 台帳（運用の状態だけ）

`<data_root>/screener_intelligence/screen_runs/<run_id>.jsonl`。追記専用 ・正準の JSON ・event ごとの `digest`（sha256）と `prev_digest` の鎖 ・
`seq` の連番。write → flush → fsync。外部の変更は byte 長で検知。

| event | payload |
|---|---|
| `RUN_STARTED` | spec |
| `INVOCATION_STARTED` | 番号 ・`acquired_at` ・`budget_limit` |
| `MEMBERS_ASSESSED` | member ごとの判定（`NOT_ELIGIBLE` ／ `IDENTITY_UNRESOLVED` ／ `RESOLVED` ・理由の code ・発行体の id）・発行体ごとの取得の経路の code ・snapshot の日（1 run に 1 回） |
| `ISSUER_ATTEMPTED` | 発行体の id ・経路の code ・呼び出し ・request の番号 ・`AUTHORITY_BUILT` ／ `ACQUISITION_FAILED` ・理由の code |
| `INVOCATION_ENDED` | 番号 ・request の件数 ・path ・予算が尽きたか ・master の失敗の code |

台帳は市場 ・Screener ・結果の authority ・P9 の記憶ではない。財務の値 ・provider の生の行 ・会社名を持たない。

**読み込みの検査（fail closed ・修復 ・切り詰め ・上書きしない）**: encoding ・切断 ・JSON ・欄の集合 ・正準の行 ・digest ・鎖 ・`seq` ・`run_id` ・schema ・
遷移（`RUN_STARTED` は 1 行目だけ ・呼び出しの外の event は前提の欠け ・呼び出しの番号の連続 ・`acquired_at` の非減少 ・判定は 1 回で member は spec と
一致 ・発行体の試みは判定の後 ・宣言の順の次の発行体だけ ・1 回だけ）。閉じていない呼び出し（中断）は `LEDGER_OPEN_INVOCATION`（継続しない。
新しい run を明示する）。

## 5. batch ・継続

1 呼び出し ＝ 新しい `RequestBudget(budget_limit ≤ 8)`。master が未判定なら 1 request（1 run に 1 回）。次に、まだ試みていない発行体を経路の
宣言の順（運用だけ ・非意味）に 1 request ずつ。予算が 0 になれば止める（`budget_exhausted`）。仕事が残らない継続は呼び出しを足さない（request 0）。
累計の request は台帳の `INVOCATION_ENDED` の合計（運用の診断だけ。財務の authority ではない）。

## 6. master の request（1 run に 1 回）

D0 の master の snapshot は D0 の中で固定なので、1 回目の呼び出しの判定を台帳に **判定だけ**（member ごとの適格 ・凍結 LIVE1 の理由の code）として
残し、継続は再取得しない。生の応答 ・会社名 ・市場の欄は保存しない（凍結 LIVE1 は memory だけ）。継続は同じ D0 の run だけ（別の日は spec の不一致）。
master の取得の失敗（HTTP 等）は判定を作らず、全 member を `NOT_ATTEMPTED / MASTER_NOT_ASSESSED` とし、次の明示の継続でだけ再取得する（隠れた
retry なし）。

## 7. identity（消費するだけ）

適格な member ごとに凍結 A1 の resolver `resolve(history, IDENTIFIER(JQUANTS_CODE, code), cutoff=evaluation_as_of)`。`FOUND` 以外は
`IDENTITY_UNRESOLVED / IDENTITY_<status>`（D0 の identity coverage ・知られた時刻 ・上場の状態は凍結の resolver が決める）。自動の承認 ・identity の
作成 ・曖昧な一致は無い（ID1 ／ ID2 ／ I1 は import しない）。fins の handoff は凍結 LIVE1 の `verify_identity_for_code`。

## 8. 発行体の束ね ・取得の経路

解決の後、同じ IssuerId に解けた member を 1 つの発行体の評価に束ねる（評価は 1 回 ・主の上場物は選ばない）。fins は code で取得するので、
`ROUTING_RULE = FIRST_DECLARED_MEMBER_RESOLVING_TO_THE_ISSUER_ACQUISITION_ROUTING_ONLY`（主 ・優先 ・最良ではない）。経路の code は台帳に残る。

## 9. 取得の構成（凍結の chain）

1 発行体: `verify_identity_for_code` → `fetch_fins_summary(handoff)`（1 request ・page を追わない）→ 凍結 ACQ0 の event（`bounded_content_digest` ・
`RequestScope.of`。`pagination_key` があれば `PARTIAL_PAGINATED` で authority を作らず `ACQUISITION_FAILED / PAGINATION_NOT_FOLLOWED`）→
凍結 EXE-R（`AdapterContext(issuer_id, acquired_at)`）→ 凍結 EPOCH1R の `build_manifest` ／ `record_manifest` → 凍結 F1 の `execute_provider_holdings`。
F1 の `APPENDED` ・`REUSED` ・`MIXED_APPEND_REUSE` ・`NO_CANONICAL_PERIODS` ・`UNKNOWN_PERIOD_HELD_ROW` は `AUTHORITY_BUILT`（0 epoch は評価で
真に NOT_EVALUABLE）。他は `ACQUISITION_FAILED / HOLDINGS_<status>`。

## 10. 瞬間

取得の瞬間（呼び出しごと ・ACQ0 ・EXE-R ・保持の `holdings_as_of`）と宣言の評価の瞬間（run 全体 ・A3-RA の `authority_as_of` ＝ `identity_valid_at`）を
分ける。取得の瞬間 ≤ 評価の瞬間（後の保持が評価から見えないことを防ぐ）・同じ D0 ・継続で非減少。全発行体の結果は同じ評価の瞬間（凍結 B5B が検査）。

## 11. member の状態の写像（凍結 B5B の 6 つだけ）

| 実行の結果 | member |
|---|---|
| snapshot に無い ・行が曖昧 | `NOT_ELIGIBLE / NOT_IN_MASTER_SNAPSHOT ・MASTER_ROW_AMBIGUOUS` |
| 凍結 LIVE1 で HOLD ／ EXCLUDED | `NOT_ELIGIBLE / <LIVE1 の理由> ・MASTER_<判定>` |
| 審査済みの identity に解けない | `IDENTITY_UNRESOLVED / IDENTITY_<resolver の status>` |
| fins の失敗 ・page ・event ・manifest ・F1 の失敗 ・store の append の拒否 | `ACQUISITION_FAILED / <code>` |
| 取得の authority ができた | `EVALUATED`（発行体の評価に結び付く） |
| 未試行 ・最後の呼び出しが予算で止まった | `BUDGET_DEFERRED / BUDGET_EXHAUSTED` |
| master が未判定 | `NOT_ATTEMPTED / MASTER_NOT_ASSESSED` |
| 未試行 ・その他（予算以外で止まった） | `NOT_ATTEMPTED / NOT_YET_ATTEMPTED` |

運用の失敗 ・財務 data の欠損は NO_MATCH にしない（欠損は凍結 B2 の NOT_EVALUABLE）。

## 12. run 全体の失敗 ／ member の失敗

run 全体（`ScreenRunError`。member の結果に潰さない）: Universe ／ 方針の authority の欠落 ・破損 ・選択子の誤り ・mode の未対応 ／ 不一致 ・spec の
不一致（方針 ・Universe ・D0 ・mode ・評価の瞬間の変更）・台帳の破損 ・閉じていない呼び出し ・瞬間の誤り（日の外 ・評価より後 ・逆行）・authority の
store の破損 ・欠落 ・外部の変更（chain の途中を含む）・凍結 B4A の orchestration の失敗 ・凍結 B5B の組み立ての不変条件。member: §11。

## 13. 全結果 ・安全な投影

呼び出しの終わりに毎回、台帳（運用の状態）＋ authority の store から決定論で組み立てる: `AUTHORITY_BUILT` の発行体ごとに凍結 B4A
`evaluate_selected_policy`（方針の正確な id ・宣言の評価の瞬間）→ 凍結 B4A の投影 → 凍結 B5B `assemble_result_set` → 凍結 B5B
`project_safe_set_summary`。結果の store ・台帳の中の財務の値の複製は無い。CLI の出力は運用の状態（run_id ・呼び出し ・request ・累計 ・完全性）と
凍結 B5B の安全な投影だけ（安全な schema は広げない）。

## 14. 合成の証拠（`tests/intelligence/test_screener_multi_issuer_executor.py`）

- 16 発行体 ＝ 17 request: 呼び出し 1（8: master ＋ 7）PARTIAL → 継続（8）PARTIAL → 継続（1）COMPLETE。member の欠落 ・重複なし ・同じ request
  なし ・master は 1 回 ・宣言の順 ・評価の瞬間は宣言の値 ・終わった run の継続は request 0 で同じ `screen_result_id`。
- 小さい予算（2 ・3）の継続 ・不正な予算（0 ・9 ・文字列 ・bool）は request 0。
- 混合: MATCH ・NO_MATCH ・NOT_EVALUABLE（営業利益の欠損）・NOT_ELIGIBLE（市場の保留 ・snapshot に無い）・IDENTITY_UNRESOLVED ・
  ACQUISITION_FAILED（HTTP 500 ・page）・2 code → 1 発行体（fins は経路の code の 1 回だけ）・途中の呼び出しの予算の延期 → COMPLETE。
- master の失敗 → 全 NOT_ATTEMPTED ・retry なし → 明示の継続で COMPLETE。
- 方針の別の id ・別の版 ・Universe の別の版 ・別の D0 ・評価の瞬間 ・STRICT ・無い方針 ／ Universe ・瞬間の逆行 ・評価より後の取得 ・二重の開始 ・違う
  run_id → すべて request 0 で fail closed。日の外 ・naive ・D0 の形も同じ。
- 台帳: 不正な行 ・切断 ・digest の不一致 ・不可能な遷移 ・同じ発行体の 2 回目 ・前提の欠け ・鎖の断絶 ・非正準 ・閉じていない呼び出し → fail closed
  （修復しない）・元に戻せば継続できる。

## 15. 境界（guard）

- runtime の追加は package の外の runner 1 つ（`PHASE8_B5C_RUNTIME`）。他の runtime 53 ・Phase 8 の test ・先行の文書は P8_B5B anchor と byte 一致
  （B4B の runner ・B5A ・B5B を含む）。
- import は sanctioned の名前だけ（B4B の runner ・B2 の評価関数 ・identity ／ 方針の作成は無い）。時計 ・乱数 ・retry ・sleep ・getattr ・key つきの
  並べ替え ・削除 ・上書き ・順位 ・推奨 ・Theme ・公開 ・LLM は無い。本番の closure に入らない。

## 16. 観察（監督への報告。変更はしない）

- P8-OBS-115: request の経済: N 発行体 ＝ 1（master）＋ N（fins）。呼び出し数 ＝ ⌈(1 ＋ N) ／ 8⌉（予算 8）。master は 1 run に 1 回で、継続は
  再取得しない（判定だけを台帳に残す）。
- P8-OBS-116: 台帳は運用の状態だけ。財務の真実は authority の store にだけあり、全結果は毎回そこから組み立て直す（台帳に値を写さない）。
- P8-OBS-117: 単一の authority の日: 取得 ・評価の瞬間は D0 の中。別の日の継続は spec の不一致で fail closed。複数日は I1 の延期のまま。
- P8-OBS-118: 取得の経路の code は宣言の順の最初の member（主ではない）。同じ発行体の他の code は request を使わない。
- P8-OBS-119: identity の作成は B5C の外（凍結 ID1 ／ ID2 の人の審査）。現在の人の審査の経路は PILOT2 の PREPARE ／ EXECUTE（1 root に 3 code まで ・
  EXECUTE は fins も取得する）だけなので、大きい Universe の identity の受け入れは将来の gate の課題（I1 ・自動化と同じ領域）。
- P8-OBS-120: 宣言の評価の瞬間は最後の取得より後でなければならないので、run の開始時に先の瞬間（例: D0 の夜）を宣言する。途中の PARTIAL の結果は
  その瞬間の「途中の像」で、決定論だが完了の結果ではない（完全性の欄が示す）。
- P8-OBS-121: 中断（閉じていない呼び出し）は修復しない。provider の request が使われた後に台帳の event が残らない可能性があるので、新しい run を
  明示する（累計の件数は人が把握する）。
- P8-OBS-122: v1 の実行器は `HOLD` ・`AUTHORITY_FAILURE` の発行体の状態を通常の経路では作らない（凍結の chain が統合された単一の区分で authority を
  作るため）。凍結 B5B の型は両方を受け、実行器はそれを潰さずに運ぶ。
- P8-OBS-123: 方針 ・Universe の変更は「途中の変更」としてではなく別の run_id として表れる（内容 address）。継続の明示（`continue_run_id`）が
  不一致を network の前に検出する。

## 17. B5D の最小の実 data の検証（推奨。実行しない）

合成の B5C が複数の呼び出しの継続を証明したので、実 data の検証は **最小の request ・人の審査** で実の複数発行体の経路を確かめる:

- 新しい private root ・同じ D0。identity は凍結 PILOT2 の PREPARE ＋ 人の APPROVE ＋ EXECUTE（2 code。request: master 1 ＋ fins 2）。
- Universe ＝ その 2 code（人が審査して B5A に追記）・方針 ＝ 人が書く 1 基準（B3）。
- B5C を `--budget-limit 2` で `start`（master ＋ 1 fins）→ `continue`（1 fins）→ COMPLETE。**予算を小さくしても request の合計は同じ 3**なので、実の
  継続も追加の provider の費用なしで確かめられる。
- 合計の request: PILOT2 3 ＋ B5C 3 ＝ 6。人の審査: identity 2 件 ・Universe 1 件 ・方針 1 件。
- 合格: 2 呼び出し ・累計 3 ・master 1 回 ・全 member が終端 ・COMPLETE ・状態は型つき（MATCH 必須ではない）・安全な投影に code ・発行体 ・値が無い ・
  replay で request 0 ・同じ `screen_result_id`。
