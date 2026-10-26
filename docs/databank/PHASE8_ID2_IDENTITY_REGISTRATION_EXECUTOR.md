# PHASE 8 / P8-ID2 — HUMAN-APPROVED IDENTITY REGISTRATION EXECUTOR（凍結 A1 への登録の、明示の実行の境界）

P8-ID1（PASS ／ FROZEN `6b5f0e6`）の機械の提案 ・人の審査 manifest ・登録 plan を、**正確な人の authorization の下でだけ**凍結 A1 の
`IdentityStore` へ append する executor を実装した gate。合成の master の行だけ。live の J-Quants request ・実データの bootstrap は無い。

- 基準: P8-ID1 `6b5f0e6795357109f2cf3b12339f9f7a93ceaf77`（凍結。runtime 25 module）。full pytest の基準 5793 passed ／ 2 skipped。
- 本書は credential ・raw の応答 ・実の code の一覧を載せない。

---

## 0. 結論

1. 追加した runtime は 2 module: `identity_registration_model`（結果の型 ・閉じた理由）、`identity_registration_executor`
   （`execute_identity_registration(rows, batch, reviewed, data_root, *, prior_plan=None)`）。先行の 25 module は byte 一致。
   A1 ・ID1 は無変更（A1 は実行を安全に支えた。`P8_A1_IDENTITY_MODEL_BLOCKER` は無い）。
2. **信頼の境界**: 入力は元の合成の master の行 ＋ `BootstrapBatch`（D0）＋ 人の `ReviewedManifest` ＋ 明示の `data_root`。実行のたびに
   凍結 ID1 を再実行し（manifest の digest が人の審査と一致することを確かめ）、審査の結びつきを検証し、plan を作り直す。caller の
   `RegistrationPlan` は任意の cross-check だけ（不一致 → `REJECTED / PRIOR_PLAN_MISMATCH`。0 書き込み）。
3. **人の authorization**: reviewer `HUMAN` の `APPROVE` だけが登録を authorize する。REJECT ・DEFER ・未審査 → `NO_AUTHORIZED_ITEMS`
   （書かない）。古い審査 ・digest の不一致 → `REJECTED`。自動 ・既定の承認は無い。
4. **`accepted_at`** は人の審査の受理の時刻（審査の event の metadata）。caller が審査のときに明示に渡し、ID2 は作らず ・実行の時刻で
   置き換えず ・再検証を通して保つ（A1 の `known_at` になる）。provider の有効時間でも D0 でもない。時計を読まない。
5. **A1 の現在の状態の再検証**（書く直前）: Issuer ／ Security の anchor と id、`JQUANTS_CODE` の結びつき、Issuer↔Security の関係、
   表示名、上場、coverage、重複 ／ 再利用、衝突する既存の identity、退役した code、終わった上場（§5）。
6. 書く先は A1 の `IdentityStore` だけ。書く順は A1 の不変条件が要る順（§6）。前検査で衝突が 1 つでもあれば **0 書き込み**。
7. 途中の失敗は `PARTIAL_FAILURE`（rollback ・削除 ・上書きは無い）。再実行は A1 を読み直し、byte 一致の再利用で収束し、最終の状態は一度で
   書いた状態と byte 一致する（test）。正確な replay は `REUSED`。
8. **D0 の coverage `[D0, D0＋1 日)` は bootstrap の snapshot ／ 一括の coverage だけ**。「1 日だけ存在した」「1 日で上場が終わった」では
   ない。`ListingEnd` ・退役 ・継続の coverage を自動で作らない（§8。regression test）。
9. code の変更 ・廃止 ／ 再上場 ・複数の上場物 ・合併 ／ 分割 ・同名 ・曖昧な関係は自動で決めない（§10）。市場区分は凍結 ID1 の合成の
   値だけ（§11）。P8-OBS-58 ・59: **BLOCKED_PENDING_TERMS_CONFIRMATION**（§12）。
10. 判定: **P8_ID2_IDENTITY_REGISTRATION_EXECUTOR_VALIDATED / READY_FOR_SUPERVISOR_REVIEW**（§14）。

---

## 1. 開始の状態

| 項目 | 値 |
|---|---|
| branch | `claude/investment-intelligence-phase6` |
| 開始の HEAD | `6b5f0e6795357109f2cf3b12339f9f7a93ceaf77`（期待どおり。working tree は clean） |
| 凍結の anchor | A1 `4162e9c` ／ A1R `e6a750f` ／ A2 `b686b00` ／ A2R `4d3540c` ／ A3A `84c2d52` ／ A3B `d8845f2` ／ A3R `f1c4a4e` ／ ST1 `e831996` ／ ADP0 `a2ccc1c` ／ EXE `5ec466b` ／ ID1 `6b5f0e6` と byte 一致 |
| full pytest の基準 | 5793 passed ／ 2 skipped |

---

## 2. 変更の範囲（不変の宣言）

| 対象 | 状態 |
|---|---|
| `src/intelligence/screener_intelligence/identity_registration_model.py` | **新規** |
| `src/intelligence/screener_intelligence/identity_registration_executor.py` | **新規** |
| `tests/intelligence/test_screener_identity_registration.py` | **新規**（21 test） |
| `tests/intelligence/phase8_runtime_registry.py` ・`test_screener_intelligence_boundary.py` | ID2 の登録 ・ID1 の anchor の guard |
| 先行の 25 module ・Phase 8 の test 10 file ・先行の記録 19 | **byte 一致**（guard `test_id2_*`） |
| `main.py` ・Pages ・config ・workflow ・Secrets ・legacy ・P4/P5 ・P6 ・P7 ・Production DNA | 変更なし |

---

## 3. authority の境界 ・人の authorization

| 規則 | 内容 |
|---|---|
| 入力 | `rows`（合成の master の行）・`batch`（`BootstrapBatch`。D0 ・支える市場）・`reviewed`（`ReviewedManifest`）・`data_root`（明示。空 → `INVALID_INPUT`） |
| 受けない | `RegistrationPlan` を authority として（`prior_plan` は cross-check だけ）・ID1 が plan を作った時の A1 の状態 ・機械の承認 |
| authorize | `reviewer_class == HUMAN` かつ `disposition == APPROVE` の提案だけ（`ReviewedManifest` は model が HUMAN 以外を拒む） |
| 拒否 | REJECT ・DEFER ・未審査 → `NO_AUTHORIZED_ITEMS`；古い審査（別の提案 ・変わった内容）→ `REVIEW_BINDING_INVALID`；manifest の変化 → `MANIFEST_DIGEST_MISMATCH` |
| 結果 | `DERIVED_NON_AUTHORITY_NON_PERSISTENT`（record ではない。保存しない） |

人が審査する manifest は **機械の manifest（`propose_bootstrap(rows, batch)`。A1 の状態を入れない）**。A1 の状態に依る扱い（再利用 ・
衝突）は ID2 が実行時に決める（ID1 の `existing` つきの manifest は下見のためで、実行の digest には使わない）。

---

## 4. 実行時の再検証 ・前検査

1. 凍結 ID1 `propose_bootstrap(rows, batch)` を再実行 → manifest。
2. `reviewed.manifest_digest == manifest.manifest_digest` を確認。
3. `plan_registration(manifest, reviewed)` で審査の結びつき（提案の digest）を検証し plan を作り直す。
4. `prior_plan` があれば `as_dict()` の完全一致を確認（不一致 → REJECTED ・0 書き込み）。
5. 承認された束が無ければ `NO_AUTHORIZED_ITEMS`（store を開かない）。
6. A1 の `IdentityStore.open(data_root)`（無い → `STORE_MISSING`、破損 → `CORRUPT_STORE`。作らない）。
7. plan の**全 record** を A1 の現在の履歴に照らす（§5）。memory 内の scratch 履歴に順に足して凍結の不変条件も検査。`verify_unchanged`。
8. 1 つでも衝突があれば **0 書き込み**。

---

## 5. A1 の現在の状態との照合（record ごと）

| 状態 | 扱い | 理由 |
|---|---|---|
| byte 一致の record が既にある | **再利用**（append しない） | — |
| 同じ anchor（＝ 同じ id）の Issuer が登録済み（出所 ・`known_at` は違ってよい。登録は A1 が HUMAN_REVIEWED 等に限る） | **再利用**（既存の record id を報告） | — |
| 同じ anchor の Security が同じ Issuer で登録済み | **再利用** | — |
| 同じ anchor の Security が別の Issuer に | 衝突 | `ISSUER_SECURITY_RELATION_CONFLICT` |
| code が同じ Security に有効に結ばれている | **再利用** | — |
| code が別の Security に有効に結ばれている | 衝突 | `CODE_BOUND_TO_OTHER_IDENTITY` |
| code の割り当てが退役している（継続の曖昧さ） | 衝突 | `RETIRED_CODE_AMBIGUITY` |
| 同じ主語 ・種類 ・言語 ・D0 に同じ名前 ／ 別の名前 | **再利用** ／ 衝突 | — ／ `DISPLAY_NAME_CONFLICT` |
| その Security に同じ D0 の上場 ／ 別の開始の上場 | **再利用** ／ 衝突 | — ／ `LISTING_CONFLICT` |
| その Security の上場が終わっている | 衝突 | `LISTING_ENDED` |
| 同じ scope ・同じ区間の coverage が既にある | **再利用**（既存の id を報告） | — |
| 同じ scope で区間が重なり違う coverage | 衝突 | `COVERAGE_CONFLICT` |
| `accepted_at` が A1 の最後の `known_at` より前 | 衝突 | `KNOWN_AT_NOT_MONOTONIC` |
| 他の A1 の不変条件 | 衝突 | `AUTHORITY_RULE_VIOLATION`（A1 の code を `failure_code` に） |

再利用は「同じ identity の事実が A1 に既にある」ことで、identity を運ぶ内容（anchor ・id ・code ・Security ・値 ・有効時間）が一致する
ときだけ。出所 ・`known_at` の違いは事実の違いではない（A1 が登録の出所を人 ・取引所 ・発行体に限る）。自動の修復 ・統合 ・上書きは無い。
`ISSUER_CONFLICT` ・`SECURITY_CONFLICT` ・`IDENTIFIER_CONFLICT` は A1 の不変条件（`REGISTRATION_CONFLICT` ・`UNKNOWN_*` ・
`CONFLICTING_ASSIGNMENT`）が拒んだときの写し。

---

## 6. A1 の書く順

束（承認された 1 提案）ごとに:
`IssuerRegistration` → `SecurityRegistration`（Issuer が先に要る: `UNKNOWN_ISSUER`）→ `IdentifierAssignment`（Security が先に要る:
`UNKNOWN_SECURITY`）→ `DisplayName`（Issuer JA ・Security JA ・Issuer EN。主語が先に要る）→ `ListingStart`（Security が先に要る）。
全束の後に一括の `Coverage`（参照先なし。最後に置くことで、途中の失敗の後の再実行が coverage を先に立ててしまわない）。
`known_at` はすべて `accepted_at` で非減少。A1 を変えずにこの順で不変条件を満たす。

---

## 7. 冪等 ・再利用 ・部分失敗

- 正確な replay（同じ行 ・batch ・審査）→ `REUSED`（A1 に重複なし。store を開き直しても同じ）。行の順序は結果に影響しない。
- 1 つ以上 append した後の失敗 → `PARTIAL_FAILURE`（`STORE_WRITE_FAILED` ＋ `PARTIAL_WRITE`）。`bundles` に record ごとの
  `APPENDED` ／ `FAILED` ／ `NOT_ATTEMPTED`、`writes.appended` に成功した id。削除 ・rollback ・上書きは無い。
- 再実行: 既存の record は `REUSED`、残りは `APPENDED` → `APPENDED`。最終の journal は一度で書いた journal と byte 一致（test）。
- 何も書く前の失敗 → `REJECTED / STORE_WRITE_FAILED`。

---

## 8. D0 ・coverage の意味（監督の明確化）

ID1 ／ ID2 の `Coverage(JP_LISTED_EQUITY_IDENTITY, [D0, D0＋1 日))` は **bootstrap の snapshot ／ 一括の coverage** で、authority が
「この区間の identity の像は完全だ」と宣言するもの。**会社 ・Security が 1 日だけ存在した、上場が 1 日で終わった、という意味ではない**。
登録の後の A1 には `ListingEnd` ・`IdentifierRetirement` ・継続の coverage は無い。凍結 A1 の resolver は D0 で `FOUND`、D0 より前で
`BEFORE_COVERAGE`、D0＋1 日以後で `NOT_YET_KNOWN`（「無い」でも「廃止」でもない: その日の像はまだ宣言されていない）を返す。
過去 ・未来の identity の有効性の延長には別の authority の証拠（後の snapshot の coverage ・人の確認）が要る。ID2 は延長しない。

## 9. 遡及の境界

D0 より前の identity の履歴を作らない。D0 より前の期間の財務の観測は凍結 A1R の遡及の解決の方針だけで扱う。ID2 に backfill は無い。

## 10. 複雑な場合（自動の実行から除外）

code の変更 ・廃止 ／ 再上場 ・複数の上場物 ・合併 ／ 分割 ・同名 ・曖昧な Issuer ／ Security の関係は ID1 で提案にならず
（HUMAN_REVIEW_REQUIRED ／ CONFLICT）、ID2 では A1 の現在の状態との照合で `RETIRED_CODE_AMBIGUITY` ・`LISTING_ENDED` ・
`CODE_BOUND_TO_OTHER_IDENTITY` ・`ISSUER_SECURITY_RELATION_CONFLICT` として拒否される。単純な bootstrap の APPROVE は、別の複雑な継続の
主張を黙って authorize しない（承認は提案の digest に結びつき、A1 の状態が変われば衝突になる）。

## 11. 市場区分（S04）の制限

ID2 は市場区分を広げない。凍結 ID1 の方針（caller が明示に渡す支える一覧。test は合成の値）をそのまま使う。公式 S04 の市場区分 code の
写しは、live の bootstrap の前の別の provider mapping の決定。推定しない。

## 12. raw ・terms ・OBS-58/59

raw の master の行は保持 ・直列化しない。合成の行だけ。network ・live の J-Quants なし。公開の出力なし。
P8-OBS-58 ・59: **BLOCKED_PENDING_TERMS_CONFIRMATION**（変更なし）。

## 13. live の bootstrap ／ PILOT2 の前に残る事

1. OBS-58 ・59 の terms の確認 → live の master ・fins の取得 client（raw は memory だけ）。
2. 公式 S04 の市場区分の写しの決定（支える一覧）。
3. 実の snapshot に対する人の審査の運用（manifest の受け渡し ・`accepted_at` の記録 ・審査の記録の保管場所）。
4. 廃止 ・code の変更 ・再上場の人の手順（A1R の訂正 ・`ListingEnd` ・`IdentifierRetirement`）。
5. 後の snapshot の coverage の延長の方針（identity の有効性の証拠）。

## 14. 判定

**P8_ID2_IDENTITY_REGISTRATION_EXECUTOR_VALIDATED / READY_FOR_SUPERVISOR_REVIEW**
