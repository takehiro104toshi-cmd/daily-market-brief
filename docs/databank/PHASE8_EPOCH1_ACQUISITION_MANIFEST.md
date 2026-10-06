# PHASE 8 / P8-EPOCH1 — EXPLICIT ACQUISITION MANIFEST AUTHORITY（取得 manifest ＝ 明示の membership authority）

P8-EPOCH0 の設計（監督: E3 選定 ・D-E1〜D-E7 確定）を実装した gate。**1 つの COMPLETE な bounded J-Quants fins 取得につき 1 つの不変の
`AcquisitionManifest`** を、model ・追記専用 store ・純な builder ／ validator として package に足した。配線（PILOT2 ・main）・
subject-scoped coverage（A2C）・F1 coverage ・retrospective resolver ・A3 の adapter ・実 request は**無い**。

- 基準: P8-EXE-R `cc8dcf5ae6235291595c87c34a6af330355a429b`（凍結。runtime 35）。full pytest の基準 6055 passed ／ 2 skipped。
- 本書は credential ・raw の応答 ・実の値 ・会社名を載せない。例はすべて合成。

---

## 0. 結論

1. **何の authority か**: 「provider の取得 epoch E（1 つの COMPLETE な `code=C` の fins 取得）に、どの provider の行が handed off され、
   それぞれが A2 の canonical 観測 ・保留 ・記載なしのどれに写ったか」を、**journal の物理的な位置 ・現在の store の状態 ・時計 ・
   raw の payload に依らず**、決定論で replay できる形で固定する（派生の membership authority。監督の決定 E1）。
2. **位置は authority ではない（E7。永久に不採用）**: A2 ・保留 ・ACQ0 の journal の行の位置 ・順 ・行番号から membership を推定する経路は
   実装しない。store の検索は record id ・参照 ・`acquisition_ref` だけ。manifest の `entry_order` は固定値 `ACQ0_HANDOFF_ORDER_AS_RECEIVED`
   で、`JOURNAL_POSITION` などは `from_dict` が拒む。
3. **責務の分離（E1 ・§3）**: ACQ0 ＝ 取得の証拠（何を ・どの範囲で ・いつ ・完了したか。行の digest）。Manifest ＝ その取得の意味の
   membership（行 → 観測 id ／ 保留 id ／ 記載なし）。A2 ＝ canonical 観測そのもの（値 ・知識 ・鎖）。将来の A2 Coverage ＝ 不在に意味を
   与える宣言。manifest は raw snapshot でも観測でも coverage でもない。
4. **取得への結び付き（§7）**: `AcquisitionEvent` 実物が必須（duck-typed な「同等」は `INVALID_EVENT`）。provider JQUANTS ・endpoint
   `/v2/fins/summary` ・範囲は `code=C` だけ（`date` を含む範囲 ・master は対象外）・status COMPLETE ・`event.content_digest ==
   bounded_content_digest(FINS, rows)`（順も内容）・`row_count == len(rows) == len(results)`。EMPTY ／ FAILED ／ PARTIAL_PAGINATED から
   manifest は作らない（`ACQUISITION_NOT_COMPLETE`）。ACQ0 の status の意味は manifest に複製しない。
5. **行への結び付き（§8）**: handed off された行 1 つ ＝ entry 1 つ。参照は凍結 ADP0 の `ProviderRecordIdentity.reference()` そのもの、
   digest は `canonical_digest()`。参照の重複 ・同じ自然 key で違う digest ・範囲外の code ・参照にできない token は fail closed。
6. **EXE への結び付き（§9）**: 凍結 EXE の `ExecutionResult` を**消費するだけ**（再実行しない）。`provider_record` が行と一致 ・
   APPENDED ／ REUSED の観測 id が A2 の像に在る ・HELD の id が保留の像に在る ・REJECTED ／ PARTIAL_FAILURE ／ identity 未解決 ／ 結果の欠落は
   manifest を阻む（E5）。
7. **知識の metadata（§11）: K2 を選定**。entry は知識を持たない。EXE-R の後は、同じ行の canonical 観測でも知識が開示日時（初見）と取得の
   時刻（provider 側の変更）に分かれ得るので、entry 1 つの `knowledge` は誤解を招く。知識は参照する A2 の観測が持つ（`provider_disclosure_knowledge`
   ・per-field の知識は足さない。最小で正しい表現）。
8. **期間 ・区分（§12）**: CANONICAL の entry だけ、参照する観測から決定論で確かめて持つ（全欄で同じでなければ `ENTRY_INVALID`）。
   HELD ／ UNSUPPORTED ／ NOT_REPORTED_ONLY は `None`（型つきの不在。埋めない）。
9. **entry の順（§14）**: 凍結 ACQ0 の handoff の順。ACQ0 の `content_digest` は `HANDOFF_ORDER_AS_RECEIVED` で行の順を含むので、順は取得の
   内容の契約の一部で、replay で決定論。manifest の id は順と集合の両方を含む。provider identity による整列は使わない（順が違えば digest が
   違う ＝ 別の取得）。
10. **実行の結果の正規化**: entry の `execution_outcome` は `MATERIALIZED`（EXE APPENDED ／ REUSED）・`HELD` ・`NO_REPORTED_FIELDS` の 3 つ。
    「書いた」と「収束した」は実行の事実で membership ではないので区別しない。これにより**同じ取得の replay（EXE が REUSED を返す）が
    同じ manifest（同じ id）に収束**し、store は `REUSED` を返す。disposition との整合は model が強制する。
11. **privacy（§16）**: journal は metadata だけ（取得の参照 ・digest ・subject_id ・provider code ・行の参照 ・digest ・欄 → 観測 id ・
    保留 id ・期間 ・区分 ・規則の版 ・件数）。値 ・会社名 ・raw の行 ・header ・credential の欄は構造上無い。credential の印は model が拒む。
12. **追記専用（§15）**: 正準の行 ・内容 address ・byte 一致は `REUSED` ・同じ `acquisition_ref` に違う manifest は `MANIFEST_CONFLICT`
    （1 取得 ＝ 1 manifest）・同じ id で違う内容は拒否 ・破損 ／ 非正準 ／ 切断 ／ 物理的重複 ／ 取得の重複は fail closed。update ・delete ・
    修復 ・圧縮は無い。write → flush → fsync。
13. **G3 の精緻化（E4）**: 将来の Fundamental Coverage は period_end P について manifest に CANONICAL の entry が 1 つ以上あるときだけ作れる。
    HELD ／ UNSUPPORTED ／ NOT_REPORTED_ONLY だけの期間は不在の authority を作らない。本 gate は coverage を実装しない（guard）。

---

## 1. module（追加のみ。1 機能 ＝ 1 file）

| module | 役割 | import してよい凍結の層 |
|---|---|---|
| `acquisition_manifest_model.py` | `ManifestEntry` ・`AcquisitionManifest` ・`ManifestDisposition` ・`ManifestExecution` ・id ／ 参照 | identity_model（canonical_json ・is_issuer_id ・CREDENTIAL_MARKERS）・observation_model（FundamentalField ・ReportingPeriod ・StatementBasis）・core.ids |
| `acquisition_manifest_store.py` | `<data_root>/screener_intelligence/acquisition_manifests.jsonl` の追記専用 store | acquisition_manifest_model だけ |
| `acquisition_manifest_builder.py` | 純な `build_manifest` ・`record_manifest` ・`ManifestOutcome` ・`ManifestBuildResult` | ACQ0 model ・ADP0 model ・EXE model ・A2 model ・保留 model ・LIVE1 の path 定数 |

凍結の層（A1 ・A1R ・A2 ・A2R ・A3 ・ST1 ・ADP0 ・EXE ・ID1 ・ID2 ・LIVE1 ・LIVE2 ・PILOT2A ・ACQ0 ・I1）は manifest の層を import しない
（guard）。EXE-R の anchor `cc8dcf5` と runtime 35 ・先行の test ・文書は byte 一致（guard `test_epoch1_*`）。凍結 ACQ0 の test の
「先行の層は ACQ0 を知らない」の consumer の除外に `acquisition_manifest_builder` を 1 行で足した（監督の指示 §24: test は通常どおり
変えてよい。差は guard が pin する）。

---

## 2. record model

### 2.1 `AcquisitionManifest`（`record_kind = ACQUISITION_MANIFEST`、`schema_version = p8_acquisition_manifest:0.1.0`）

| 欄 | 意味 |
|---|---|
| `acquisition_ref` | 凍結 ACQ0 の参照 `jq.acq:<24 hex>` |
| `acquisition_content_digest` | その取得の bounded な行の sha256（`bounded_content_digest`） |
| `subject_id` | A1 の issuer id（`p8iss_…`）。A1 に登録済みでなければ builder が拒む |
| `provider_code` | 範囲の `code`（既存の private root の方針の中で許す） |
| `executor_rules_version` ・`mapping_rule_version` | 凍結 EXE の `ExecutionResult.rules_version` ・`mapping_rule_version`（全結果で同じ。新しい版の源を作らない） |
| `manifest_rules_version` | `p8_acquisition_manifest_authority:0.1.0` |
| `entries` | handoff の順の `ManifestEntry` の列 |
| `entry_count` ・`canonical_observation_count` | 件数（`from_dict` が再計算と照合） |
| `entry_order` | 固定値 `ACQ0_HANDOFF_ORDER_AS_RECEIVED` |
| `record_id` ・`reference` | `p8man_<sha256 の 24 hex>`（全欄の正準 JSON）・`jq.man:<同じ 24 hex>` |

不変条件: 参照の重複 ・同じ自然 key の違う digest ・観測 id の重複 ・`provider_code` と違う code の entry は拒む。

### 2.2 `ManifestEntry`

| 欄 | 意味 |
|---|---|
| `provider_record_ref` | 凍結 ADP0 の `jq.fins_summary:<Code>.<DiscNo>.<DocType>:<digest24>` |
| `provider_record_digest` | 行の 14 欄の正準 digest（参照の末尾 24 hex と一致） |
| `disposition` | `CANONICAL` ／ `HELD_SEMANTIC` ／ `NOT_REPORTED_ONLY` ／ `UNSUPPORTED` |
| `execution_outcome` | `MATERIALIZED` ／ `HELD` ／ `NO_REPORTED_FIELDS`（disposition と一対一） |
| `fields` | `FundamentalField → A2 observation record_id`（欄名の順。値は無い） |
| `held_record_id` | ST1 の `p8hld_…`（HELD_SEMANTIC ・UNSUPPORTED だけ） |
| `period` ・`statement_basis` | CANONICAL だけ。参照する観測から確定（他は `null`） |

### 2.3 disposition の不変条件（§6。凍結 EXE の形の監査の結果）

| disposition | 観測 id | 保留 id | 期間 ・区分 | 凍結 EXE の結果 |
|---|---|---|---|---|
| `CANONICAL` | 1 つ以上（記載なしの欄は省く） | 無し | 必須 | `APPENDED` ／ `REUSED`（欄は APPENDED ／ REUSED ／ NOT_REPORTED だけ） |
| `HELD_SEMANTIC` | 無し | 必須 | 無し | `HELD`（会計基準 ・区分 ・通貨 ・鎖の不連続 ・注記の衝突 ・知識の不足 ・provider 変更の衝突） |
| `UNSUPPORTED` | 無し | 必須 | 無し | `HELD`（書類種別の未知 ／ 範囲外 ・期間 ・値 ・時刻の形 ・写像 ・規約の境界） |
| `NOT_REPORTED_ONLY` | 無し | 無し | 無し | `NO_REPORTED_FIELDS` |

監査: 凍結 EXE の HELD は行単位（canonical と保留の混在は無い）。`IDENTITY_UNRESOLVED` の HELD は主語が無いので manifest を阻む
（`EXECUTION_INCOMPLETE`）。語彙は EXE の形に正確に合うので、model を弱めていない。

---

## 3. builder の判定（`build_manifest` → `ManifestBuildResult`）

| 状況 | outcome ・failure code |
|---|---|
| event が `AcquisitionEvent` でない ／ provider ／ endpoint ／ 範囲（`code` だけでない）／ 範囲外の code | `ACQUISITION_MISMATCH` / `INVALID_EVENT` ・`PROVIDER_MISMATCH` ・`ENDPOINT_MISMATCH` ・`SCOPE_NOT_SINGLE_CODE` ・`ROW_OUTSIDE_SCOPE` |
| status が COMPLETE でない | `ACQUISITION_NOT_COMPLETE` / `EMPTY` ・`FAILED` ・`PARTIAL_PAGINATED` |
| 行数 ／ digest が event と違う（順の違いを含む）・凍結 ACQ0 が行を拒む | `ACQUISITION_MISMATCH` / `ROW_COUNT_MISMATCH` ・`CONTENT_DIGEST_MISMATCH` ・`INVALID_ROW` |
| 結果の数が違う ・結果が無い ・REJECTED ・PARTIAL_FAILURE ・identity 未解決 ・CANONICAL に欄が無い | `EXECUTION_INCOMPLETE` |
| 参照の重複 | `DUPLICATE_PROVIDER_ROW` |
| 同じ自然 key ・違う digest が 1 取得に | `PROVIDER_ROWS_INCONSISTENT` |
| 観測 id が A2 の像に無い ・像が `ObservationHistory` でない | `OBSERVATION_MISSING` |
| 保留 id が保留の像に無い | `HELD_RECORD_MISSING` |
| 主語 ・欄 ・出所 ・期間 ／ 区分 ・`provider_record` ・保留 record の参照 ／ 理由 ・規則の版 ・主語の未登録 ・参照にできない行 | `ENTRY_INVALID`（code が場所を示す） |
| 組めた | `BUILT`（manifest を持つ。何も書いていない） |

`record_manifest(built, store)` → `APPENDED` ／ `REUSED` ／ `MANIFEST_CONFLICT` ／ `STORE_FAILURE`。何も authoritative に書けなければ成功を返さない。

---

## 4. 証明（test で固定）

| 証明 | 内容 |
|---|---|
| 再取得（§18） | E1 で行 R → O。E2 で同じ R → EXE REUSED O。manifest は 2 つ（`acquisition_ref` が違う）、どちらも O を member に持ち、O と鎖は不変 |
| provider の修正（§19） | E1 で K/D1 → O1。E2 で K/D2（同じ自然 key ・違う digest。EXE-R で知識 ＝ 取得の時刻）→ O2。manifest1 は O1 だけ、manifest2 は O2 だけ。O1 は A2 に残るが E2 の member ではない。同じ取得に D1 と D2 の両方は `PROVIDER_ROWS_INCONSISTENT` |
| 新しい DiscNo の訂正（§20） | E2 で DiscNo A → O1 REUSED ・DiscNo B → O2。manifest2 は 2 行 ・2 つの membership を持ち、A2 の鎖は O1 → O2 |
| 記載なし ・保留（§17 ・§21） | NOT_REPORTED_ONLY ・HELD_SEMANTIC ・UNSUPPORTED の行は manifest に残り、canonical の membership を作らない（将来の retrospective な解決がこれらの slot を NOT_FOUND にしない根拠） |
| replay | 同じ取得の EXE replay（REUSED）→ 同じ manifest ・store は REUSED。同じ結果からは同じ manifest |
| privacy | journal に値 ・欄名（Sales ・OP ・NP ・TA）・会社名 ・開示日 ・`acquired_at` ・知識 ・credential の印 ・URL は無い |
| 位置の不採用 | store の答えは物理の順に依らない（逆順に書いた store が同じ答え）。`entry_order` の偽装は拒む |

---

## 5. 将来の gate との関係

- **P8-A2C**（subject-scoped `ObservationCoverage` ・`holdings_as_of` ・RETROSPECTIVE_PROVIDER_AUTHORITY の resolver）: epoch E の member は
  manifest の `observation_ids` で明示に決まる（journal の位置 ・`acquired_at` の推定は使わない）。coverage は E4 の規則で CANONICAL の
  period_end だけに作る。
- **P8-OBS60-F1**: fins の取得 event（COMPLETE）＋ manifest → subject-scoped な財務 coverage（公式確認 ・監督決定の後）。
- A3 は STRICT_PIT のまま。retrospective な指標は後で epoch で絞った像を消費する。A3 は変えない。

---

## 6. 次の gate

P8-A2C（監督の決定の後）→ P8-OBS60-F1 → P8-A3-RA → P8-PILOT2B。
