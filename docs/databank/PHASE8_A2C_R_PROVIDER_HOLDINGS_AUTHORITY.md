# PHASE 8 / P8-A2C-R — PROVIDER HOLDINGS COVERAGE AUTHORITY（provider の保持 epoch の authority。C1）

P8-OBS60-F1-R の設計（監督: R-B ＋ C1 選定）の後半。世界 ／ 公開の知識の完全性（A2 `ObservationCoverage`）と、provider の bounded な保持
epoch（新 `ProviderHoldingsCoverage`）を**別の authority ・別の journal**に分け、RETROSPECTIVE_PROVIDER_AUTHORITY の epoch の源を後者に
移した gate。F1（record の生成）・A3 の遡及 ・PILOT2B ・実 request は**無い**。

- 基準: P8-EPOCH1R `9a34569f41594d35aa55d8041ad968e4bf75f78b`（凍結。runtime 39）。full pytest の基準 6190 passed ／ 2 skipped。
- 本書は credential ・raw の応答 ・実の値 ・会社名を載せない。例はすべて合成。

---

## 0. 結論

1. **2 つの authority（混ぜない）**
   - `ObservationCoverage`（A2。不変）＝ 世界 ／ 公開の知識の完全性。`complete_through`。STRICT_PIT と `COVERAGE_CONTRADICTION` が読む。
   - `ProviderHoldingsCoverage`（新）＝ bounded な provider の取得（epoch）の保持。`holdings_as_of`（取得 event の `acquired_at` そのもの）。
     遡及の解決だけが読む。`ObservationHistory.coverages` ・STRICT の `_coverage` ・`COVERAGE_CONTRADICTION` ・A3 には決して入らない
     （A2 の store は型で拒む。guard）。`complete_through` ・世界の知識の境界を持たない。
2. **別 journal**: `<data_root>/screener_intelligence/provider_holdings_coverage.jsonl`（追記専用。正準 JSONL ・flush ＋ fsync ・byte 一致は
   REUSED ・同じ id で違う内容 ・同じ取得 ・同じ period_end に違う record は `PROVIDER_HOLDINGS_CONFLICT` ・破損 ／ 非正準 ／ 切断 ／ 物理的な
   重複 ／ 外部の変更は fail closed。修復 ・書き直し ・削除は無い）。検索は id ・参照 ・（主語, period_end）。journal の位置は意味を持たない。
3. **record**: `dataset`（FUNDAMENTAL_DISCLOSURE だけ）・`subject_id`（Issuer）・`period_end`（G3: 1 日。`covers(day)` は一致だけ。区間の
   推定なし）・`holdings_as_of`（aware ・UTC で直列化）・`acquisition_ref`（`jq.acq:`）・`manifest_ref`（`jq.man:`）・`canonical_entry_count`
   （manifest のその period_end の CANONICAL の entry の数。整合の metadata で、それ自体は証拠にしない）・`rules_version`。
   identity は内容 address `p8pvh_<24 hex>`、参照 `jq.pvh:<24 hex>`。全欄が identity に入る。
4. **epoch の選択**（`resolve_retrospective(..., holdings=...)`。保持の像は明示。既定 ・時計 ・A2 の coverage への fallback なし）: 主語 ・
   period_end（＝ query の期間の末日）が一致し `holdings_as_of <= authority_as_of` の record から `holdings_as_of` が最大。無い →
   `OUTSIDE_COVERAGE / NO_PROVIDER_HOLDINGS_EPOCH`（最初の epoch より前は `BEFORE_COVERAGE`）、全部後 → `NOT_YET_KNOWN /
   FUTURE_PROVIDER_HOLDINGS_EPOCH`、同じ瞬間に別の record → `AMBIGUOUS / AMBIGUOUS_PROVIDER_HOLDINGS_EPOCH`。
5. **manifest の結び付き**: `manifests.by_acquisition(acquisition_ref)` がちょうど 1 つ。`manifest.reference == manifest_ref`
   （違う → `MANIFEST_CONFLICT / PROVIDER_HOLDINGS_CONFLICT`）、取得 ・主語の一致、その period_end の CANONICAL の数 ＝ `canonical_entry_count`
   （違う → `MEMBERSHIP_INVALID / CANONICAL_ENTRY_COUNT_MISMATCH`）。
6. **membership**: 期間 ・区分が合う CANONICAL の entry の欄 → 観測 id → A2 の像で検証（主語 ・欄 ・出所 ・期間 ・区分）。同じ鎖の member が
   複数なら鎖の順で最後。後から A2 に入った観測 ・manifest に無い鎖の member ・journal の位置は使わない（A2C のまま）。
7. **不在の authority（監督の決定。EPOCH1R の期間 metadata を使う）**
   - manifest 全体に `period = None` の HELD_SEMANTIC ／ UNSUPPORTED が 1 つでも → 取得全体で汚染。非 member の slot は
     `SEMANTIC_HOLD / UNKNOWN_PERIOD_HELD_ROW_IN_EPOCH`。
   - `period.period_end == P` の HELD_SEMANTIC ／ UNSUPPORTED（区分は問わない。区分 None なら全区分） → P で汚染。非 member の slot は
     `SEMANTIC_HOLD / HELD_ROW_AT_PERIOD`。他の P は影響を受けない。
   - canonical の member は汚染があっても `FOUND`。
   - 汚染が無く、同じ期間 ・区分の CANONICAL の行に欄が無い → `VALUE_ABSENT / FIELD_NOT_REPORTED_IN_EPOCH`。同じ期間 ・区分の
     NOT_REPORTED_ONLY → `VALUE_ABSENT / NOT_REPORTED_ROW_AT_PERIOD`（記載なしは汚染しない）。
   - **`NOT_FOUND`** はそれ以外だけ: 「選んだ COMPLETE な provider の保持 epoch の中で、不在の authority が明示に安全な slot に、一致する
     canonical の観測が無かった」。開示の不在 ・市場の無知 ・provider の歴史的な完全性 ・世界の完全性のどれも意味しない
     （`interpretation = ACCORDING_TO_PROVIDER_HOLDINGS_AT_AUTHORITY_AS_OF_NOT_A_WORLD_KNOWLEDGE_CLAIM`）。
8. **provider の修正 ・再取得 ・訂正**: epoch 1 で保留（P 既知。canonical が無ければ保持 record も無い）→ epoch 1 の authority_as_of では
   `NOT_YET_KNOWN`（record は後の epoch だけ）か、他の canonical があれば `SEMANTIC_HOLD`。epoch 2 で修正 → `FOUND` ／ `VALUE_ABSENT` ／
   清浄なら `NOT_FOUND`。再取得は別の record（holdings_as_of ・取得が違う）だが同じ観測 id に解く。新しい DiscNo は含む epoch からだけ見える。
   epoch 1 の record は不変。
9. **結果の metadata**: `resolution_mode` ・`authority_as_of` ・`coverage_epoch_id`（＝ 選んだ `ProviderHoldingsCoverage.reference`。
   `jq.pvh:`。A2 の coverage の id ではない）・`interpretation`。STRICT の直列化は不変。
10. **A2 ・A3 の孤立**: `ObservationCoverage.subject_id` ・`holdings_as_of` は凍結のまま残す（F1 は書かない）。A2 の model ・resolver ・
    store ・A3 は byte 一致。遡及の resolver は `.coverages` ・`complete_through` を読まない（guard）。
11. **将来の F1**: COMPLETE な取得 ＋ authoritative な manifest から、CANONICAL の entry が 1 つ以上ある period_end ごとに 1 record を
    この journal に書く。期間が None の保留が 1 つでもあれば 0 record。`ObservationCoverage` は書かない。本 gate は生成しない。

---

## 1. 遡及の判定の表（A2C-R）

| 状況 | status / diagnostic |
|---|---|
| 主語 ・period_end の保持 record が無い | `OUTSIDE_COVERAGE / NO_PROVIDER_HOLDINGS_EPOCH`（最初の epoch より前は `BEFORE_COVERAGE`） |
| 全部 `authority_as_of` より後 | `NOT_YET_KNOWN / FUTURE_PROVIDER_HOLDINGS_EPOCH` |
| 同じ `holdings_as_of` の record が複数 | `AMBIGUOUS / AMBIGUOUS_PROVIDER_HOLDINGS_EPOCH` |
| 像の record の型 ／ 主語 ／ dataset が違う | `MANIFEST_CONFLICT / PROVIDER_HOLDINGS_CONFLICT` |
| manifest が無い | `MANIFEST_MISSING / NO_MANIFEST_FOR_ACQUISITION` |
| manifest の参照 ／ 取得 ／ 主語が合わない | `MANIFEST_CONFLICT / PROVIDER_HOLDINGS_CONFLICT ・MANIFEST_ACQUISITION_MISMATCH ・MANIFEST_SUBJECT_MISMATCH` |
| CANONICAL の数が合わない | `MEMBERSHIP_INVALID / CANONICAL_ENTRY_COUNT_MISMATCH` |
| member が像に無い ／ 合わない | `MEMBERSHIP_INVALID / OBSERVATION_*` |
| 期間 None の保留が manifest に在る（非 member の slot） | `SEMANTIC_HOLD / UNKNOWN_PERIOD_HELD_ROW_IN_EPOCH` |
| P の保留が在る（非 member の slot） | `SEMANTIC_HOLD / HELD_ROW_AT_PERIOD` |
| 同じ期間 ・区分の CANONICAL の行に欄が無い（清浄） | `VALUE_ABSENT / FIELD_NOT_REPORTED_IN_EPOCH` |
| 同じ期間 ・区分の NOT_REPORTED_ONLY（清浄） | `VALUE_ABSENT / NOT_REPORTED_ROW_AT_PERIOD` |
| 清浄 ・一致なし | `NOT_FOUND / NO_CANONICAL_MEMBER_FOR_COVERED_SLOT` |
| member あり | `FOUND` |

---

## 2. 次の gate

P8-OBS60-F1（取得 ＋ manifest ＋ A2 → `ProviderHoldingsCoverage` の生成。preflight ・append-only）→ P8-A3-RA → P8-PILOT2B。
