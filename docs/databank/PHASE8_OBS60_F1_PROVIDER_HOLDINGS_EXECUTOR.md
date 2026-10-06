# PHASE 8 / P8-OBS60-F1 — PROVIDER HOLDINGS COVERAGE EXECUTOR（保持 record の決定論の producer）

P8-OBS60-F1-R の設計（監督: R-B ＋ C1）と P8-EPOCH1R ・P8-A2C-R の後に来る、`ProviderHoldingsCoverage` を**作る**最初の gate。
COMPLETE な取得 event（凍結 ACQ0）＋ その取得の authoritative な manifest（凍結 EPOCH1R）＋ A2 の canonical の像（凍結）から、
period_end ごとに 1 つの保持 record を凍結 `ProviderHoldingsStore` に append する。A3 の遡及 ・PILOT2B の配線 ・実 request ・screening は
**無い**。

- 基準: P8-A2C-R `9833ddbecc5039a206f31d6e2e1f08fa590a384a`（凍結。runtime 41）。full pytest の基準 6243 passed ／ 2 skipped。
- 本書は credential ・raw の応答 ・実の値 ・会社名を載せない。例はすべて合成。

---

## 0. 結論

1. **作るもの ・作らないもの**: 作るのは `ProviderHoldingsCoverage`（A2C-R の model。`p8pvh_` ・`jq.pvh:`）だけ。A2 の
   `ObservationCoverage` ・`ObservationHistory.coverages` ・STRICT の `_coverage` ・`COVERAGE_CONTRADICTION` ・A3 には決して触れない。
   `complete_through` ・世界の知識の境界（max ／ earliest ／ certain_by）・provider の反映時刻を計算しない。時計 ・network ・raw の
   payload ・「最新」の既定は無い。
2. **入口**: `execute_provider_holdings(*, event, manifests, history, store) -> HoldingsExecutionResult`。全部明示（既定 ・fallback なし）。
   `manifests` は `by_acquisition` を持つ像（凍結 `ManifestStore`）、`history` は A2 の `ObservationHistory`、`store` は書ける
   `ProviderHoldingsStore`。
3. **event の authority（§5）**: `AcquisitionEvent` そのもの ・provider JQUANTS ・api `v2` ・endpoint `/v2/fins/summary` ・範囲はちょうど
   `code=C` ・status COMPLETE。EMPTY ／ FAILED ／ PARTIAL_PAGINATED は `ACQUISITION_NOT_COMPLETE`（code は status）、形の不一致は
   `ACQUISITION_MISMATCH`（`INVALID_EVENT` ・`PROVIDER_MISMATCH` ・`API_VERSION_MISMATCH` ・`ENDPOINT_MISMATCH` ・`SCOPE_NOT_SINGLE_CODE`）。
4. **manifest の結び付き（§6）**: `by_acquisition(event.reference)` がちょうど 1 つ（無い → `MANIFEST_MISSING / NO_MANIFEST_FOR_ACQUISITION`。
   推定しない）。`acquisition_ref` ・`acquisition_content_digest` ・`provider_code == C` ・`entry_count == row_count` ・主語（Issuer id で、
   A2 の像の identity に在る）・`manifest_rules_version` ・schema（EPOCH1R `p8_acquisition_manifest:0.2.0`）。違えば `MANIFEST_CONFLICT`
   （`MANIFEST_ACQUISITION_MISMATCH` ・`CONTENT_DIGEST_MISMATCH` ・`PROVIDER_CODE_MISMATCH` ・`ROW_COUNT_MISMATCH` ・`SUBJECT_INVALID` ・
   `MANIFEST_RULES_VERSION_MISMATCH` ・`MANIFEST_SCHEMA_MISMATCH` ・`INVALID_MANIFEST`）。
5. **取得全体の保留（§7。監督の決定）**: `period = None` の HELD_SEMANTIC ／ UNSUPPORTED が 1 つでも → **0 record**（他の period_end にも
   作らない）。`UNKNOWN_PERIOD_HELD_ROW`。
6. **記載なし（§8）**: NOT_REPORTED_ONLY は保留の規則を起こさない。期間 ・区分の無い記載なしは `PRECHECK_FAILED /
   NOT_REPORTED_ENTRY_WITHOUT_PERIOD_OR_BASIS`（捏造しない）。期間を持つ記載なしは汚染せず、数にも入らない。
7. **G3（§9 ・§10 ・§11）**: CANONICAL の entry が 1 つ以上ある period_end P だけに record。無ければ `NO_CANONICAL_PERIODS`（0 record）。
   期間 P が既知の保留 ／ UNSUPPORTED を伴っても P の record は作る（不在の汚染は凍結 A2C-R の resolver が manifest から導く）。
   `canonical_entry_count` ＝ P の CANONICAL の **entry** の数（欄ではない。同じ期間の訂正は 2）。
8. **canonical の観測の preflight（§12）**: 全 CANONICAL の entry の全欄 → 観測 id → A2 の像で `FundamentalActual` が在り、主語 ・欄 ・期間
   （entry と一致）・区分 ・出所（JQUANTS ・`provider_record_ref`）が合う。1 つでも違えば `MEMBERSHIP_INVALID / OBSERVATION_*` で 0 write。
9. **出力 record（§14〜§16）**: `ProviderHoldingsCoverage(FUNDAMENTAL_DISCLOSURE, manifest.subject_id, P, event.acquired_at,
   event.reference, manifest.reference, count, rules_version="p8_provider_holdings_executor:0.1.0")`。`holdings_as_of` ＝
   `event.acquired_at` そのもの（丸め ・補正なし）。順は period_end の昇順（`OUTPUT_ORDER_RULE = "ASCENDING_PERIOD_END"`。manifest の
   entry の順 ・journal の位置に依らない）。
10. **store の preflight と append（§13 ・§17）**: 凍結 store の**公開の読み口だけ**（`verify_unchanged` ・`get` ・`for_slot`）で全 record を
    最初の append の前に確かめる: 同じ id が在れば内容一致（違えば `HOLDINGS_CONTENT_CONFLICT`）、同じ取得 ・同じ period_end に別 id の
    record が在れば `PROVIDER_HOLDINGS_CONFLICT`、外部の変更は `CONCURRENT_MODIFICATION`。すべて `STORE_FAILURE` で 0 write。
    runtime の変更は要らなかった（FROZEN_DEPENDENCY なし）。append は 1 箇所 ・昇順 ・`APPENDED` ／ `REUSED` を集める。rollback は無い
    （preflight の後の append の失敗は書いた分を残し `STORE_FAILURE` で報告する）。
11. **結果（§18）**: `HoldingsExecutionResult`（派生 ・非永続 ・metadata だけ）: `status` ・`subject_id` ・`acquisition_ref` ・`manifest_ref` ・
    `eligible_period_count` ・`appended` ・`reused` ・`failure_code` ・`rules_version`。status は `APPENDED` ／ `REUSED` ／
    `MIXED_APPEND_REUSE` ／ `NO_CANONICAL_PERIODS` ／ `UNKNOWN_PERIOD_HELD_ROW` ／ `PRECHECK_FAILED` ／ `ACQUISITION_NOT_COMPLETE` ／
    `ACQUISITION_MISMATCH` ／ `MANIFEST_MISSING` ／ `MANIFEST_CONFLICT` ／ `MEMBERSHIP_INVALID` ／ `STORE_FAILURE`。値 ・会社名 ・digest ・
    raw の行 ・credential は載らない。
12. **replay ・再取得 ・訂正（§19〜§23）**: 同じ入力の replay は全 record `REUSED`（byte 不変）。再取得は別の取得 ・別の `holdings_as_of` の
    新しい record（最初の record は不変）。provider の修正 A（単体の破損 → epoch 1 は record 無し、epoch 2 で生成）・B（破損の期間だけ
    epoch 1 に無い）・C（P 既知の保留 ＋ canonical → record は作り、非 member は `SEMANTIC_HOLD`）。同じ期間の訂正は 1 record ・count 2。
13. **A2C-R との統合（§24）**: 凍結 `resolve_retrospective` が F1 の record で `FOUND` ・`VALUE_ABSENT` ・`SEMANTIC_HOLD` ・本当の
    `NOT_FOUND` ・`NOT_YET_KNOWN` を返す（test）。
14. **STRICT ・A2 ・A3（§25 ・§27）**: F1 の実行で A2 の observation journal は byte 不変 ・`coverages` は空のまま ・STRICT は
    `OUTSIDE_COVERAGE`（legacy coverage では世界の知識の答えのまま）・provider の修正は EXE で `APPENDED`（矛盾しない）。
15. **凍結 surface（§28）**: 新規は module ・test ・本書だけ。凍結 test の 1 行の consumer の除外（ACQ0 ・EPOCH1 の test）は F1 の guard が
    pin する。runtime 42。A2C-R の anchor `P8_A2C_R` を登録。

---

## 1. 結果の表

| 状況 | status / failure_code |
|---|---|
| 入力の型（像 ・store）が違う | `PRECHECK_FAILED / INVALID_HISTORY ・MANIFEST_VIEW_REQUIRED ・WRITABLE_STORE_REQUIRED` |
| event が COMPLETE でない | `ACQUISITION_NOT_COMPLETE / EMPTY ・FAILED ・PARTIAL_PAGINATED` |
| event の形が違う | `ACQUISITION_MISMATCH / INVALID_EVENT ・PROVIDER_MISMATCH ・API_VERSION_MISMATCH ・ENDPOINT_MISMATCH ・SCOPE_NOT_SINGLE_CODE` |
| manifest が無い | `MANIFEST_MISSING / NO_MANIFEST_FOR_ACQUISITION` |
| manifest が合わない | `MANIFEST_CONFLICT / *_MISMATCH ・SUBJECT_INVALID ・INVALID_MANIFEST` |
| 期間 None の保留 | `UNKNOWN_PERIOD_HELD_ROW`（0 record） |
| 期間 ・区分の無い記載なし | `PRECHECK_FAILED / NOT_REPORTED_ENTRY_WITHOUT_PERIOD_OR_BASIS` |
| CANONICAL の期間が無い | `NO_CANONICAL_PERIODS`（0 record） |
| canonical の観測が像と合わない | `MEMBERSHIP_INVALID / OBSERVATION_*` |
| record の model が拒む | `PRECHECK_FAILED / <model の code>` |
| store の衝突 ・外部の変更 | `STORE_FAILURE / HOLDINGS_CONTENT_CONFLICT ・PROVIDER_HOLDINGS_CONFLICT ・CONCURRENT_MODIFICATION` |
| 全部新しい ／ 全部在る ／ 混在 | `APPENDED` ／ `REUSED` ／ `MIXED_APPEND_REUSE` |

---

## 2. 次の gate

P8-A3-RA（遡及の metric）→ P8-PILOT2B（配線。本人の環境でだけ）。F1 は配線しない。
