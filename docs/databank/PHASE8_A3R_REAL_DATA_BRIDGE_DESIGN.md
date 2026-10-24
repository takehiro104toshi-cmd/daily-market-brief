# PHASE 8 / P8-A3R — REAL-DATA BRIDGE FOUNDATION AUDIT & DESIGN

凍結した Phase 8 の pipeline（A1 identity → A2 観測 ／ PIT → A2R 会計の意味 → A3A ／ A3B 指標）に、**実の J-Quants Light の data
を初めて安全に流すために何が要るか**を監査 ・設計する gate。監督の決定（P8-A3B ＝ PASS ／ CLOSED ／ FROZEN `d8845f2`、`metric_model` の
4 行は承認済みで A3B の凍結の一部）に従う。**設計 ・監査だけ。runtime の変更 ・adapter ・store ・executor ・identity の登録 ・実データの
pilot ・J-Quants の data API への要求は無い。**

- 基準: P8-A3B `d8845f2b063f15dc8629245ec276019d6314cf7a`（凍結）。full pytest の基準 5545 passed ／ 2 skipped。
- 出所: 公式の J-Quants の文書だけ（`jpx-jquants.com`。2026-09-28 取得。利用規約の FAQ `ja/help/usage`、上場銘柄一覧 `ja/spec/eq-master`、
  財務情報 `ja/spec/fin-summary`、提供データの更新タイミング `ja/spec/data-update`）と、repo の HEAD の code ・先行の Phase 8 の文書。
  credential ・raw の応答 ・財務の実の値は載せない。
- 分類: **DOCUMENTED**（公式の本文）／ **OBSERVED_IN_PILOT** ／ **INFERRED** ／ **UNKNOWN** ／ **REQUIRES_HUMAN_CONFIRMATION**。

---

## 0. 結論

1. **利用規約の境界が最初の blocker**（§12）。公式 FAQ は「個人の私的利用に限る」「取得した data そのものを閲覧できる形で配布 ・共有
   しない」「本人だけが閲覧できる保存なら可」「解約 ・downgrade 後は data ・複製 ・元 data を復元できる派生物を削除」「分析結果を継続
   反復して第三者に提供 ・配信する行為は私的利用に当たらない」と定める（DOCUMENTED）。本 repository は **public** で、GitHub Pages に
   毎朝の brief を**継続して公開**する project である。したがって (a) raw ・値 ・派生の record を git ・Pages ・Actions の log に一切
   置かない（設計で強制）、(b) **J-Quants 由来の指標を公開物に載せてよいか**は文書からは決まらない → **REQUIRES_HUMAN_CONFIRMATION**
   （D6 ・D7）。法的な結論は出さない。
2. 既存の J-Quants の code は、credential の解決 ・秘密の scrub ・content address の raw store が**wrapper つきで再利用でき**、legacy の
   normalizer ・canonical store ・Fact builder は **P8 に使えない**（先勝ちの上書き ・欠損の潰し ・固定の 15:30。§3）。
3. identity の bootstrap は **機械の候補 ＋ 人の一括の審査 ＋ 例外の個別審査**（A2.5 の案 D を具体化。§4）。J-Quants は登録の出所に
   なれない（凍結の A1: `ISSUER_REGISTRATION` ／ `SECURITY_REGISTRATION` は取引所 ・発行体の開示 ・人の審査だけ）。provider の code を
   canonical の id にしない。anchor は一括の中で一度だけ割り当て、data から計算し直さない。D0 より前の identity を作らない。
4. provider の record の identity は **自然 key（Code ・DiscDate ・DiscTime ・DiscNo ・DocType）＋ 正準の行の digest**（§5）。DiscNo だけを
   鍵にしない（公式は昇順 ・訂正は新しい DiscNo と定めるが、全域の安定は定めない）。訂正は別の record。上書きしない。
5. 知識の時刻は **2 軸を分ける**（§6）: A2 の `KnowledgeTime` ＝ TDnet の開示日時（JST。DOCUMENTED）、provider の提供 ／ 取得の時刻は
   取り込みの event の record に別に持つ。同一視しない。`now` ・15:30 を作らない。
6. 4 欄の写し（`Sales` ・`OP` ・`NP` ・`TA` → `REVENUE` ・`OPERATING_INCOME` ・`NET_INCOME` ・`TOTAL_ASSETS`）は A2R 再実行の DOCUMENTED の
   意味で決まる（§7）。通貨は **JPY を安全に立てられない行は HOLD**（§8。FX 換算 ・名前からの推定なし）。
7. 注記の store ・HOLD の store ・append の executor の設計（§9〜§11）。executor は渡された plan を信用せず全部を再導出する。
8. 最初の実データの pilot（§13）は 1〜3 発行体 ・API 要求は最大 8 回 ・raw は memory だけ ・保存は private の data root だけ。
   **実行しない**。
9. 監督の決定 D1〜D8（§16）。実装の順（§17）。
10. 判定: **P8_A3R_REAL_DATA_BRIDGE_DESIGN_COMPLETE / READY_FOR_SUPERVISOR_REVIEW**（§18）。runtime は無変更。

---

## 1. 開始の状態

| 項目 | 値 |
|---|---|
| branch | `claude/investment-intelligence-phase6` |
| 開始の HEAD | `d8845f2b063f15dc8629245ec276019d6314cf7a`（期待どおり。working tree は clean） |
| 凍結の anchor | A1 `4162e9c` ／ A2 `b686b00` ／ A2R `4d3540c` ／ A3A `84c2d52`（`fundamental_metrics.py`）／ A3B `d8845f2`（16 module）と byte 一致 |
| `metric_model` の登録の差分 | `84c2d52` との差分は承認済みの 4 行（`NET_MARGIN` ・`ROA_POINT_IN_TIME` ・`NET_INCOME` ・`TOTAL_ASSETS`）だけ |
| full pytest の基準 | 5545 passed ／ 2 skipped |

---

## 2. 現在の architecture（凍結。変えない）

```
A1  identity_model / identity_store / identity_resolver            Issuer ／ Security の identity（追記専用 ・PIT）
A1R identity_correction_* / identity_remediation_resolver          訂正 ・遡及の解決（RETROSPECTIVE_AUTHORITY ・版の固定）
A2  observation_model / observation_store / observation_resolver   観測 ・revision の鎖 ・coverage ・PIT の解決
A2R observation_semantics_model / _mapping / _gate                 会計基準 ・連結の区分の注記 ・DocType の表引き ・互換 ・AppendPlan
A3A metric_model / fundamental_metrics                             売上成長率 ・営業利益率
A3B fundamental_metrics_extended                                   純利益率 ・ROA（時点の分母）
```

橋は provider の data を**これらの契約に合わせる**。契約を provider の都合に合わせない。

---

## 3. 既存 repo の再利用の監査

| 部品 | 場所 | 分類 | 理由 |
|---|---|---|---|
| credential の解決 ・秘密の scrub（`Secret` ・`CredentialResolution` ・`scrub` ・`JQuantsV2CredentialResolver` ・`scrub_response_text`） | `market/jquants_v2.py`（`jquants_topix` の基礎部品） | **REQUIRES_WRAPPER** | 環境変数 `JQUANTS_API_KEY` の runtime injection と scrub の規律は良い。Cloud の環境では proxy が header を付け、変数が無い（PILOT1）→ 「credential を読めない mode」を wrapper で足す。値は読まない ・log しない ・保存しない |
| V2 の汎用 client（path ＋ params ＋ pagination ＋ entitlement、fail closed） | `market/jquants_v2_client.py` | **REQUIRES_WRAPPER** | transport は再利用できる。ただし raw snapshot に要る **応答の本文の bytes と受信の時刻**を返さない（JSON に parse した行だけ）→ 本文を先に content address する wrapper が要る。`parse_float=str` の parse は raw の後 |
| Light の dataset の registry（entitlement ・endpoint ・default params `code=72030`） | `market/jquants_light_datasets.py` | **HISTORICAL_ONLY** | 2026-09-01 の実測の記録。意味の authority ではない（欄名は V2 の実測。公式の一覧は A2R 再実行で確定） |
| 構造化 record ・normalizer | `market/jquants_records.py` | **UNSAFE_FOR_P8** | null ・key なし ・空文字を潰す（P8-OBS-26）、接頭辞の無い欄 ＝ 連結と決め打ち（PILOT1 で否定）、Company ／ security は分けるが A1 ではない |
| canonical JSONL ＋ SQLite の store | `market/jquants_light_store.py` | **UNSAFE_FOR_P8** | 自然 key の先勝ちで業者の改訂を捨てる ・索引が canonical と食い違う ・破損行を黙って飛ばす ・`latest_*` が PIT でない（P8-OBS-25 ・2）。authority にしない ・移行しない |
| raw store（content address の blob ・追記専用 JSONL ・atomic ・hash 照合） | `ingestion/raw_store.py`（`JsonlRawRepository`） | **REQUIRES_WRAPPER** | 仕組みは要件（§10 ・§12）に合う。ただし raw の保存は **D6 の確認まで無効**。既定の場所は `data/vnext/`（.gitignore 済み） |
| Fact builder（`_known_at` ＝ 開示日の 15:30 JST 固定） | `facts/jquants_builder.py` | **UNSAFE_FOR_P8** | P8-OBS-1 の原因。P3 の Fact 層は P8 の authority ではない |
| TOPIX の provider ・research の取得 ・Phase 5 の calibration | `market/jquants_v2.py`（TOPIX 部分）・`predictions/topix_*` | **OUT_OF_SCOPE** | 指数 ・Phase 5。P8 は TOPIX を使わない |
| Light の pilot ・pilot runner | `market/p2h_light_pilot.py` ・`market/pilot_runner.py` | **HISTORICAL_ONLY** | P2-H の実証 script。data root へ書く。P8 の pilot はこれを呼ばない |
| 取引カレンダー | `market/tokyo_calendar.py` | **OUT_OF_SCOPE**（本 gate） | 参照の観測の gate（P8-OBS-28）で改めて評価 |
| data root の解決（`INTELLIGENCE_DATA_ROOT` ・`config.yaml` ・既定 `data/vnext`） | `core/paths.py` | **SAFE_TO_REUSE** | P8 の store は明示の `data_root` を受ける（既定を読まない）。既定の場所は git の外 |
| 内容 address の id（`content_id`）・時刻の直列化 | `core/ids.py` ・`core/time.py` | **SAFE_TO_REUSE** | A1 ・A2 ・A2R ・A3 が既に使う |
| A1 ・A1R ・A2 ・A2R ・A3A ・A3B の runtime と store | `screener_intelligence/` | **SAFE_TO_REUSE**（凍結の authority） | 橋はこれらの API だけを呼ぶ（`IdentityStore.append` ・`ObservationStore.append` ・`resolve` ・`derive_observation_semantics` ・`plan_append`） |
| P8 の文書（LV1 ・PILOT1 ・A2R 再実行 ・A2R-IMPL） | `docs/databank/PHASE8_*` | **SAFE_TO_REUSE**（意味の authority の記録） | DOCUMENTED ／ OBSERVED の分類をそのまま継ぐ |
| 過去の master の snapshot | repo に無い（legacy の store が data root に持ち得る） | **HISTORICAL_ONLY** | 取得時刻 ・完全性が P8 の要件で検証されていない。A1 の coverage の根拠にしない |
| corporate action の扱い | 無い（P8-OBS-24） | — | 本 gate の 4 指標は分割の影響を受けない（金額 ・総資産）。EPS 系は BLOCKED のまま |
| 運用 journal（`data/investment_journal/journal.json`） | P4 | **OUT_OF_SCOPE** | pytest の副作用の対象。P8 は触れない |
| review の identity ledger | `review/identity_ledger.py` | **OUT_OF_SCOPE** | 別の領域（narrative の entity）。A1 ではない |
| 利用規約 ・保存期間の文書 | repo に無い（P8-V §12 が「raw の保存を認めない」と記録） | — | 本書 §12 が最初の記録 |
| 実の J-Quants の値 ・応答の commit | `data/` を検索: **無し** | — | 清浄。この状態を設計で保つ |

legacy の stock の論理は「既にある」ことを理由に使わない。

---

## 4. identity の bootstrap の設計（D1）

### 4.1 入力（公式）

`/v2/equities/master?date=D`（DOCUMENTED。`ja/spec/eq-master`）: `Date`（情報適用年月日）・`Code`（5 桁。4 桁で問い合わせると末尾 `0`
＝ 普通株）・`CoName` ・`CoNameEn` ・業種 ・規模 ・`Mkt` ・貸借区分。**上場日 ・上場廃止日 ・廃止銘柄の一覧 ・code の変更 ・商号変更 ・
合併の前身 ／ 後継の対応は提供しない**（DOCUMENTED）。過去日の snapshot はその日に上場していた銘柄を返し、廃止後の日付は空。5 桁目 `0` が
普通株（DOCUMENTED。FAQ）。

### 4.2 手順（機械の候補 → 人の審査 → A1 の authority）

| 段 | 内容 | 出所の class | 自動化 |
|---|---|---|---|
| B1 候補の生成 | snapshot D0 の全行から、決定論の規則で候補の一覧（manifest）を作る: 5 桁目 `0` の code ごとに **1 Security ＋ 1 Issuer** の候補。同じ先頭 4 桁を共有する code ・5 桁目 ≠ `0` ・英字を含む code ・`Mkt` が例外的な行は「例外」に分ける。manifest は正準 JSON ＋ sha256（code の一覧は private の data root にだけ置く。repo には件数と digest だけ） | 機械（J-Quants の snapshot から） | 可 |
| B2 一括の審査 | 人が規則と例外の一覧を確かめ、manifest の digest に署名する（審査の理由の本文は repo に置かない） | 人 | **HUMAN_REVIEW** |
| B3 登録 | `IssuerRegistration` ・`SecurityRegistration(COMMON_EQUITY)` を `HUMAN_REVIEWED`、`source_record_ref = review:p8boot1.<digest の先頭 24 hex>`、`known_at` ＝ 審査の受理の時刻（system の知識）で追記。anchor は `p8boot1:iss.<Code>` ／ `p8boot1:sec.<Code>`（一括の id ＋ 種類 ＋ その時の code。**anchor は不変の token で、後で code が変わっても id は変わらない**。data から計算し直さない。P8-OBS-29） | HUMAN_REVIEWED | 審査の後は機械 |
| B4 識別子 | `IdentifierAssignment(JQUANTS_CODE, value=Code, effective_from=D0)` ・`DisplayName(CoName: JA ／ CoNameEn: EN, effective_from=D0)` を `JQUANTS` の出所で追記（A1 はこれらに J-Quants を認める） | JQUANTS | 可 |
| B5 上場 ・coverage | `ListingStart(TSE, effective_from=D0)` と `Coverage(JP_LISTED_EQUITY_IDENTITY, effective_from=D0, effective_to=D0 ＋ 1 日)` を `JQUANTS` で追記。**D0 より前は表さない**（「少なくとも D0 から上場」は A1 に無い。P8-OBS-6。D0 より前の問い合わせは `BEFORE_COVERAGE` ／ `NOT_ACTIVE`） | JQUANTS | 可 |
| B6 例外 | 同じ先頭 4 桁の複数の code（1 発行体の複数の上場物か）・優先株 ・英字の code ・`Mkt` の例外 → 登録しない。人が個別に審査した物だけ後の一括で登録 | 人 | **HUMAN_REVIEW ／ FAIL_CLOSED** |

### 4.3 変化への対応

| 事象 | J-Quants で分かる事（DOCUMENTED） | 設計 |
|---|---|---|
| code の変更 | 日次 snapshot の差分だけ（旧 code が消え新 code が現れる）。対応表なし | 自動で結ばない。**FAIL_CLOSED**: 新 code は B6 の例外として保留。人が継続を確かめたら A1R の訂正（`SUPERSEDE_RECORD`）と `IdentifierAssignment`（`HUMAN_REVIEWED`。継続の出所は人 ・取引所 ・発行体だけ） |
| 社名の変更 | `CoName` の変化 | 新しい `DisplayName(effective_from=変化を観測した snapshot の日)` を `JQUANTS` で追記（同じ社名 ＝ 同じ Issuer としない） |
| 上場廃止 | 行が消える。廃止日 ・理由は無い（JPX の web の一覧を参照するよう案内） | 自動で `ListingEnd` を書かない（A1 は取り消せない）。**HUMAN_REVIEW**: 消えた code を保留の一覧に出し、人が確かめて `ListingEnd(DELISTED, effective_to=消えた snapshot の日)` を `HUMAN_REVIEWED` で追記 |
| 再上場 | 分からない | 既定は新しい Security（別の一括の anchor `p8boot<n>:sec.<Code>`）。継続は人の審査だけ |
| 1 発行体の複数の上場物 | 発行体の識別子なし | B6。束ねは人の審査 |
| 過去の coverage の不足 | Light は master の過去日を 5 年分返すが、その忠実さ ・深さは未検証 | **D0 より前の identity を作らない**。過去の財務の観測（D0 より前の期間）は、D0 で登録した Issuer の観測として A2 に入れられる（A2 の resolver は財務の主語に `FOUND` ／ `NOT_ACTIVE_AT_CUTOFF` を認める）。cutoff が登録の `known_at` より前の解決は A1R の `RETROSPECTIVE_AUTHORITY`（版の固定）でだけ行う |
| effective_from ／ to と system の時刻 | — | 有効時間は snapshot の `Date`、system の知識は `known_at` ＝ 審査の受理 ／ 取り込みの時刻。混ぜない（P8-OBS-18） |

### 4.4 自動化の境界（まとめ）

自動: 候補の生成 ・識別子 ・表示名 ・上場（D0 から）・coverage。**人**: 登録の受理 ・例外 ・code の変更 ・廃止 ・再上場 ・統合。
**FAIL_CLOSED**: 審査の無い登録 ・D0 より前 ・同名からの束ね ・provider の code を id にすること。

---

## 5. provider の record の identity（`/v2/fins/summary`）

| 要素 | 根拠 |
|---|---|
| 自然 key ＝ (`Code`, `DiscDate`, `DiscTime`, `DiscNo`, `DocType`) | `DiscNo` は開示番号で応答は昇順、訂正は新しい `DiscNo`（DOCUMENTED）。**ただし全域 ・全期間の一意 ・安定は文書に無い**（UNKNOWN）→ `DiscNo` 単独を鍵にしない。開示の順序は `DiscDate` ・`DiscTime` で判定（DOCUMENTED） |
| 本文の digest ＝ 行の正準 JSON（key を整列 ・値は文字列のまま ・空文字を残す）の sha256 | 業者の不備の修正は上書きで版番号 ・ETag が無い（DOCUMENTED。P8-OBS-54）→ 同じ自然 key で digest が違えば業者側の改訂 |
| `source_record_ref` ＝ `jq.fins_summary:<Code>.<DiscNo>.<DocType>:<digest の先頭 24 hex>` | A2 の参照の形（英数と `._:#-`、160 文字まで）に収まる（最長の DocType でも約 120 文字）。`DiscDate` ・`DiscTime` は provenance の別の欄ではなく A2 の `KnowledgeTime` になる |
| 冪等 | 同じ自然 key ・同じ digest → 何もしない |
| 業者側の改訂 | 同じ自然 key ・違う digest → 既存の record を上書きしない。新しい A2 の revision（`supersedes` ＝ 前の record、知識 ＝ **取得の時刻**、provenance に `PROVIDER_REVISION` の印）。A2 の `NON_MONOTONIC_KNOWLEDGE` ／ 同じ日の `DATE` の訂正は保留（P8-OBS-30） |
| 発行体の訂正開示 | 新しい `DiscNo` の別の行（DOCUMENTED）→ 同じ slot の新しい revision（知識 ＝ その行の開示日時）。元の行は残る |
| 鍵の欠け ・想定外の文字 | 保留（他の鍵へ落とさない） |

---

## 6. 知識の時刻の写し（2 軸）

| 軸 | 意味 | どこに持つ | 値 |
|---|---|---|---|
| 世界で知り得た時刻 | TDnet で開示が公開された時刻（DOCUMENTED: `DiscDate` ・`DiscTime` ＝ TDnet の開示日 ・時刻、JST） | A2 の `KnowledgeTime` | `TIMESTAMP(DiscDate DiscTime, JST)`。`DiscTime` が空 → `DATE(DiscDate)`。`DiscDate` が不正 → HOLD。固定の時刻を作らない |
| provider から取得できた時刻 | J-Quants の API がその record を返した時刻（Light は日次の反映。18:00 ／ 24:30 頃は目安で約束ではない。DOCUMENTED） | 取り込みの event の record（§9 ・§10 の `retrieved_at`、UTC）と A2 の `ObservationCoverage.complete_through` | 取得の時刻そのもの。**A2 の知識にしない** |

- 2 軸を同一視しない。「J-Quants Light の利用者がいつ知り得たか」を要する分析（backtest の遅れの方針）は A2 の外の後の gate で、
  取り込みの event から作る。
- coverage の宣言（fail closed）: snapshot を取得した JST の日を T とすると、`complete_through` ＝ T の 00:00 JST（前日までの開示は
  24:30 頃の確報で反映済み、を安全側に丸める）。取得が T の 03:00 JST より前なら T − 1 の 00:00。当日の開示は宣言しない。
- 後から取った record に開示日時を知識として付けてよい根拠: 各 record は開示時点の値を保ち、訂正は別の `DiscNo`（DOCUMENTED）。
  業者側の修正だけが例外で、§5 の digest で検知して知識 ＝ 取得の時刻の revision にする。→ **D8**。

---

## 7. 4 欄の canonical の写し（承認済みの 4 指標に要る分だけ）

| provider の欄 | canonical | 意味の authority | 単位 ・桁 | 通貨 | 会計基準 | 連結の区分 | 期間 | 欠損 |
|---|---|---|---|---|---|---|---|---|
| `Sales` | `REVENUE` | 売上高（DOCUMENTED）。期首からの累計（DOCUMENTED） | 円 ・`Scale.ONE`（DOCUMENTED: 換算 ・丸めなし） | §8 | `DocType` の表引き（A2R-IMPL） | `Consolidated` の行 → `CONSOLIDATED`（DOCUMENTED）；PILOT1 で観測した `NonConsolidated_JP` 4 値 → `NON_CONSOLIDATED`（OBSERVED_IN_PILOT ＋ 監督 d2）；他は UNKNOWN → HOLD | §7.1 | `""` → `NOT_REPORTED`（DOCUMENTED: 記載なし） |
| `OP` | `OPERATING_INCOME` | 営業利益（DOCUMENTED）。累計 | 同上 | 同上 | 同上 | 同上 | 同上 | 同上（記載しない発行体あり） |
| `NP` | `NET_INCOME` | 当期純利益 ＝ 親会社株主に帰属（DOCUMENTED）。累計 | 同上 | 同上 | 同上 | 同上 | 同上 | 同上 |
| `TA` | `TOTAL_ASSETS` | 総資産（DOCUMENTED）。期末の残高は INFERRED（A3B で明示） | 同上 | 同上 | 同上 | 同上 | 同上 | 同上 |

- `NC*` の欄（`NCSales` 等）は連結の区分が DOCUMENTED でも会計基準が UNKNOWN（A2R-IMPL）→ 本 pilot では観測を作らず HOLD。
- 値は JSON の文字列 → A2 の `canonical_decimal`。数でない token（`-` 等）→ HOLD（`VALUE_UNPARSEABLE`）。0 は値。
- 予想の修正の行 ・REIT ・`Foreign` ・表に無い `DocType` → 4 指標の入力にならない → 観測を作らず HOLD（`DOC_TYPE_*`）。
- `OdP` ・`F*` ・`NxF*` ・配当 ・株数 ・CF ・EPS ・持分は本 gate の範囲外（写さない）。

### 7.1 期間の写し（A2 の `ReportingPeriod`）

| `CurPerType` ・日付 | A2 |
|---|---|
| `FY` かつ `CurPerSt == CurFYSt` かつ `CurPerEn == CurFYEn` | `FISCAL_YEAR` |
| `1Q` ／ `2Q` ／ `3Q` かつ `CurPerSt == CurFYSt` かつ `CurPerEn < CurFYEn` | `CUMULATIVE_YEAR_TO_DATE`（quarter 1 ／ 2 ／ 3）。累計は DOCUMENTED |
| `4Q` ・`5Q` ・`OtherPeriod` の `DocType` ・日付が上と食い違う ・年度が 550 日を超える | HOLD（`PERIOD_UNSUPPORTED`）。単独の四半期を作らない |

---

## 8. 通貨 ・外国の発行体の方針（D4）

事実: `/fins/summary` に通貨の欄は無い。金額は円単位（DOCUMENTED）。ただし `/fins/details` の公式の文書は、ある発行体（銘柄コード
62690）が 2022 年 2 月以降 米ドルで表示すると記す（DOCUMENTED。summary への波及は UNKNOWN。P8-OBS-53）。

| 案 | 内容 | 適格 | HOLD | 評価 |
|---|---|---|---|---|
| A. 円の既定 ＋ 公式に記された除外 | `DocType` の基準が `JP` ・`US` ・`IFRS` ・`JMIS` の財務諸表の行は `Currency.JPY`。公式の文書が非円の表示を記す発行体（現在 1 件）と、人が確かめて足した発行体は除外の一覧（private）で HOLD。`Foreign` は HOLD | 除外にない国内の基準の行 | 除外 ・`Foreign` | 実用的。公式の記述だけで除外を作り、名前 ・所在地から推定しない。**未知の非円の発行体を取りこぼす危険が残る**（公式が全件を挙げる保証は無い） |
| B. `JP_GAAP` の行だけ円 | 日本基準の行だけ `JPY`。IFRS ・US ・JMIS は通貨が立つまで HOLD | JP_GAAP | それ以外 | 最も保守的な実用案。既知の非円の事例（IFRS の発行体）を構造で避ける。IFRS の発行体（大型株に多い）が全部 HOLD になる |
| C. 通貨の欄が来るまで全部 HOLD | — | なし | 全部 | 実データが流れない |
| D. `/fins/details` で行ごとに通貨を確かめる | details の通貨の表示で判定 | 確かめた行 | 他 | Light は `/fins/details` を取得できない（DOCUMENTED: Premium だけ）→ 不可 |

**推奨: B を最初の pilot に、A を 2 段目に。** pilot の発行体を `JP_GAAP` に限れば D4 の決定を待たずに始められる。FX 換算はしない。
名前 ・所在地からの推定はしない。「全部 JPY」と黙って仮定しない。

---

## 9. 意味の注記の store（P8-OBS-56。D2）

| 項目 | 設計 |
|---|---|
| 名前 ・場所 | `observation_semantics_store`（新 module。A2R の record をそのまま使う）。`<data_root>/<P8 の dir>/semantics.jsonl` ＋ `semantic_mapping.jsonl`（A1 ・A2 の store と同じ形: 追記専用 JSONL ・`canonical_line` ・fsync ・読み戻しで全行を検証 ・破損は fail closed） |
| 参照 | `ObservationSemantics.observation_id` ＝ A2 の観測の record id（内容 address なので A2 に追記する**前**に決まる）。`mapping_provenance_id` ＝ provenance の record id |
| 不変 ・追記専用 | 上書き ・削除の API を持たない。同じ record id → 何もしない（冪等） |
| 衝突 | 同じ `observation_id` に**内容の違う**注記 → `SEMANTICS_CONFLICT` で拒む（黙って置き換えない）。正しい方への訂正は、A1R と同じ形の明示の訂正 record（後の gate。本 gate では設計しない）でだけ |
| PIT | 注記は provider の行（`DocType`）と写しの規則の版から決定論で導ける**派生の record**。世界の知識を足さない（`DocType` は観測と同じ開示の行にある）。解決 ・指標は「caller が固定した規則の版の注記」を使う。規則の版が上がった時は新しい注記を**追記**し、古い版の注記は残す（再生は版で固定） |
| 可変の enrichment | 無い。値は enum と id だけ |
| authority の class | **`SEMANTIC_METADATA_RECORD`（provider の写しの運用上の authority）**。観測の authority（A2）でも投資の authority でもない。A3 は注記なしに観測を使わない（D-P8-A2R-6）が、注記が観測の値を変えることは無い |
| 保存の境界 | 注記自体は J-Quants の値を含まない（enum ・id ・`DocType` の文字列だけ）。ただし provenance の `doc_type` は provider の data の一部 → private の data root にだけ置く（§12） |

---

## 10. HOLD の store（D3）

| 項目 | 設計 |
|---|---|
| 名前 | `HeldObservation`（中立の語。severity ・順位 ・警報の意味を持たない） |
| 何を持つか | provider ・schema の family ・`provider_record_ref`（§5）・試みた canonical の欄 ・試みた区分 ・写せた範囲の期間 ・知識の時刻（写せたなら）・**理由の code の tuple**（閉じた語彙。A2R の `HoldReason` ＋ adapter の code: `IDENTITY_UNRESOLVED` ・`CURRENCY_NOT_ESTABLISHED` ・`PERIOD_UNSUPPORTED` ・`VALUE_UNPARSEABLE` ・`KNOWLEDGE_TIME_INVALID` ・`DOC_TYPE_UNRECOGNIZED` ・`DOC_TYPE_OUT_OF_SCOPE` ・`PROVIDER_REVISION_UNRESOLVED` ・`TERMS_BOUNDARY`）・規則の版（写し ・gate ・adapter）・`retrieved_at` |
| 値 | 写せた候補の値（正準の文字列）は持つが、**raw の行の本文は持たない**（D6 の前は raw を保存しない） |
| identity | 内容 address（`p8hld_`）: provider_record_ref ・欄 ・区分 ・理由 ・規則の版から。同じ id → 冪等 |
| 追記専用 | 削除 ・上書き ・自動の昇格は無い。保留の解除は「新しい規則の版 ・新しい identity ・人の審査の後に executor を**再実行**して ELIGIBLE の plan が出ること」で、held の record は残る（後の gate で `HeldObservationResolution` の参照 record を足せる） |
| 再試行 | 「通るまで再試行」の loop を持たない。再実行は明示の run |
| authority の class | **運用の record（`OPERATIONAL_HOLD_RECORD`）**。authority ではない。A2 ・A1 に入らない。指標 ・screen は読まない |
| 保存の境界 | J-Quants 由来の値を含む → private の data root だけ（§12） |

---

## 11. append の executor（D5）

```
入力: provider の record（memory 内の行 ＋ 取得の event）, data_root, 規則の版（identity の一括 ・写し ・gate ・adapter）, 任意の AppendPlan
手順（すべて fail closed。渡された plan は cross-check にだけ使い、信用しない）:
 1. identity: Code → IdentifierAssignment(JQUANTS_CODE) → Security → Issuer を A1 の resolver で解く（cutoff ＝ 取得の時刻。STRICT）。
    無い ・曖昧 ・複数 → HOLD(IDENTITY_UNRESOLVED)
 2. 写し: §5 の record identity、§6 の知識の時刻、§7 の欄 ・期間 ・値、§8 の通貨 → 候補の FundamentalActual を作る（A2 の model が検査）
 3. 注記: derive_observation_semantics(record_id, DocType, family) → ObservationSemantics ＋ provenance（A2R-IMPL）
 4. 鎖の先頭: A2 の history から同じ slot の鎖の末尾と、その注記を注記 store から取る
 5. plan: plan_append(候補, 注記, 先頭, 先頭の注記)（A2R-IMPL）。渡された plan があれば内容が一致することを確かめ、違えば拒む
 6. ELIGIBLE なら: 注記 store に注記 ＋ provenance を追記 → A2 の ObservationStore.append（凍結の検査がそのまま働く）→ 取り込みの event
    HOLD なら: HeldObservation を追記。A2 に触れない
 7. 結果は型つき（ELIGIBLE_APPENDED ／ ALREADY_PRESENT ／ HELD ／ REFUSED）。例外で終わらない
```

- 順序の理由: 注記は観測の内容 id を指す派生 record なので、観測より先に書いても害が無い（観測の無い注記は無視される）。逆順だと
  観測だけが authority に入る瞬間ができる。
- 冪等: すべて内容 address。再実行で増えない。
- 再検証の範囲は spec のとおり: identity ・写し ・注記 ・互換 ・PIT ・slot ・鎖の先頭 ・`supersedes` ・通貨。A2 の `append` の検査
  （分岐 ・知識の逆行 ・coverage）を迂回しない。
- 実装しない（本 gate）。

---

## 12. 利用規約 ・保存の境界（公式 FAQ `ja/help/usage`。2026-09-28）

| 事項 | 公式の記述の要旨 | 分類 | 本 project への帰結 |
|---|---|---|---|
| 利用の主体 | 個人の私的利用に限る。法人 ・第三者配信 ・data を使った app の提供は営利 ・非営利を問わず不可 | DOCUMENTED | 個人の契約 ・個人の環境で使う |
| 私的利用の範囲 | 自身の投資分析 ・ポートフォリオ管理。**分析結果を継続反復して第三者に提供 ・配信する行為は私的利用に当たらない** | DOCUMENTED | 本 project は GitHub Pages に毎朝の brief を継続して公開する。**J-Quants 由来の指標 ・観測を公開物（Pages ・報告 ・通知）に載せてよいかは文書からは決まらない** → REQUIRES_HUMAN_CONFIRMATION |
| 生 data の配布 | 取得した data そのものを閲覧できる形で配布 ・共有しない。分析結果（chart ・report）の共有は可、ただし継続反復は不可 | DOCUMENTED | **public な repository に raw ・値 ・派生の record を commit しない**（Actions の artifact ・log も同じ）。設計で強制（store は data root だけ、`data/vnext` は .gitignore） |
| 保存 | 本人だけが閲覧できる状態なら、本人が管理する外部 cloud への保存も可。数 ・場所の指定は無い。access 制御 ・暗号化は本人の責任 | DOCUMENTED | private の data root（Cloud の session の ephemeral な disk か本人の環境）。保存の期間の上限は無い（UNKNOWN ではなく「指定なし」） |
| 解約 ・downgrade | 取得した data ・複製 ・元 data を復元できる派生物を削除。復元できない派生物（学習済み model の重み等）は公開しない限り削除不要 | DOCUMENTED | A2 の観測（値そのもの）・raw ・HOLD の record は「元 data を復元できる」側 → 解約時に削除の手順が要る。指標の値は境界が曖昧 → REQUIRES_HUMAN_CONFIRMATION |
| 生成 AI への入力 | 4 条件（自身の分析 ・学習に二次利用されない設定 ・第三者が閲覧できない ・生成結果を配信 ・公開しない）を満たせば可 | DOCUMENTED | 本 project の narrative は Claude API を使い、生成物を公開する → J-Quants の data を LLM の入力に**使わない**限り無関係。Phase 8 は LLM を使わない（設計で保つ）。将来の Theme ・narrative との接続は REQUIRES_HUMAN_CONFIRMATION |
| cache ・保持の期限 | 明示の記述なし | UNKNOWN（解約時の削除だけが DOCUMENTED） | 最小の保持 ・削除できる構成 |
| 再配布の例外 ・派生 data の定義 | 「元 data を復元できるか」を基準に本人が判断。項目ごとの個別の可否判定は provider は行わない | DOCUMENTED | 判断は本人（監督）。法的な結論は本書で出さない |
| credential | （規約ではなく運用）API key は header だけ。読まない ・log しない ・保存しない | 既存の規律 | 継続 |

**第一の実データの adapter は、保存の境界（D6）が決まるまで raw の応答の本文を保存しない。**保存する派生の record（A1 ・A2 ・注記 ・
HOLD ・取り込みの event）も private の data root だけで、repo ・Pages ・log に出さない。

---

## 13. 最初の実データの pilot の設計（実行しない。D7）

| 項目 | 設計 |
|---|---|
| 発行体の選び方 | 投資の魅力ではなく**技術的な適合**だけ。snapshot D0 から決定論の filter: 普通株（5 桁目 `0`）・`Mkt` が主要な区分 ・`S33` が金融（銀行 ・保険 ・証券。`Sales` ・`OP` の形式が違う）でない ・Light の窓（5 年）の `/fins/summary` の財務諸表の行がすべて `*_Consolidated_JP`（**通貨の決定 D4 を待たずに済む**）・`4Q` ／ `5Q` ／ `OtherPeriod` が無い ・年度が 3 月末 ・除外の一覧に無い。条件を満たす code を**昇順に**取り、先頭の 1〜3 件。名前 ・code は報告に載せず、件数 ・状態だけ |
| API の要求の上限 | **8 回**: master 1 回（`?date=D0`）＋ 候補の確認の `/fins/summary?code=` を最大 3 件 ＋ pagination の続きを最大 4 回。超えたら停止 |
| memory に置いてよい raw | 応答の本文（bytes）と parse した行。run の終わりに破棄 |
| 保存してよい物 | A1 の record（審査済みの一括）・A2 の観測 ・注記 ・provenance ・HeldObservation ・取り込みの event（endpoint ・秘密でない引数 ・件数 ・HTTP status ・時刻 ・本文の sha256。**本文は無し**）。すべて private の data root |
| 保存してはならない物 | raw の本文（D6 まで）・credential ・header ・code の一覧 ・社名 ・値を含む報告。repo ・Pages ・Actions の log ・artifact に何も出さない |
| 流れ | master → B1〜B5（人の審査を挟む。pilot の run は審査済みの一括を前提）→ `/fins/summary` → §5 ・§6 ・§7 ・§8 → 候補の観測 → 注記 → plan → executor（§11）→ A2 ・注記 store ・HOLD store → A3A ／ A3B の 4 指標（cutoff を 2 つ: 元の値 ・訂正の後） |
| 合否 | §14 の基準をすべて満たす。1 つでも満たさなければ FAIL（HOLD の件数は FAIL の理由にしない。HOLD が authority に入れば FAIL） |
| 報告 | 件数 ・status ・理由の code の分布 ・指標が `VALUE` になった件数 ・再生の一致だけ。値 ・code ・社名は載せない |

---

## 14. 実データの成功の基準（後の pilot の客観の基準）

1. identity: 選んだ code が A1 で曖昧なく Security → Issuer に解ける。D0 より前の identity を推定していない（`BEFORE_COVERAGE` で止まる）。
2. 4 欄が決定論で写る（同じ入力 → byte 一致の record id）。
3. 会計基準 ・連結の区分がともに KNOWN（注記）。UNKNOWN の行は HOLD にある。
4. 通貨が適格（D4 の規則）。HOLD の行は A2 に無い。
5. A2 の知識の時刻 ＝ TDnet の開示日時（JST）。取得の時刻は event にだけある。
6. 訂正 ・業者側の改訂は別の revision で、元の record は不変。
7. 注記が store にあり、観測 id と一致し、衝突が無い。
8. HOLD の record が 1 件も A2 に入っていない（A2 の全 record に対応する注記が KNOWN）。
9. A3A ／ A3B の 4 指標が `VALUE` か型つきの非値で、2 回の run で `as_dict()` が一致。
10. 後の訂正の cutoff で値が変わっても、元の cutoff の結果は再実行で同一。
11. credential が stdout ・stderr ・log ・store ・報告に無い（既存の scrub の検査 ＋ 全出力の grep）。
12. raw の本文が disk に無い（D6 まで）。git の status が clean。

---

## 15. 所見の登録の更新

| id | 所見 | 前 | 今 | 根拠 |
|---|---|---|---|---|
| P8-OBS-12 | 実の Issuer ／ Security の登録の手順 | BLOCKED_PENDING_IDENTITY_POLICY | **BLOCKED_PENDING_IDENTITY_POLICY**（設計は §4。D1 の決定で解除） | 設計があるだけでは閉じない |
| P8-OBS-17 | 知識の時刻が真の公表時刻かを store は検証できない | BLOCKED_PENDING_ADAPTER | **BLOCKED_PENDING_ADAPTER**（§5 の digest ＋ §6 の 2 軸で規則は確定。D8） | adapter の実装と実データで確かめる |
| P8-OBS-18 | identity の知識の時刻の食い違い | STRUCTURALLY_ADDRESSED | STRUCTURALLY_ADDRESSED（変更なし。§4.3 で bootstrap に適用） | — |
| P8-OBS-23 | 株数の意味 | BLOCKED_PENDING_OFFICIAL_VERIFICATION | **NON_BLOCKING_DEFERRED**（本 gate の 4 指標に不要。時価総額 ・EPS 系の gate で再開） | 範囲の外 |
| P8-OBS-27 | A2 の欄が J-Quants より狭い（`EQUITY` ・株数） | BLOCKED_PENDING_OFFICIAL_VERIFICATION | **NON_BLOCKING_DEFERRED**（4 指標に不要。ROE ・時価総額で A2X が要る） | 範囲の外 |
| P8-OBS-29 | bootstrap の authority の穴 ・anchor | STRUCTURALLY_ADDRESSED（A1R） | STRUCTURALLY_ADDRESSED（§4.2 の anchor の規則 `p8boot<n>:<kind>.<Code>` で具体化） | 実行は D1 の後 |
| P8-OBS-50 | 会計基準の次元 | STRUCTURALLY_ADDRESSED（A2R-IMPL） | STRUCTURALLY_ADDRESSED（**BLOCKED_PENDING_REAL_DATA** で CLOSED へ） | 実データで注記が付いて初めて閉じる |
| P8-OBS-53 | 通貨の欄なし ・非円の発行体 | BLOCKED_PENDING_ADAPTER | **BLOCKED_PENDING_IDENTITY_POLICY** 相当の監督の決定（D4） | 方針の選択 |
| P8-OBS-54 | 業者側の上書き修正 ・版なし | BLOCKED_PENDING_ADAPTER | BLOCKED_PENDING_ADAPTER（§5 の規則で設計済み） | 実装で確かめる |
| P8-OBS-56 | 注記 ・保留の store | BLOCKED_PENDING_ADAPTER | BLOCKED_PENDING_ADAPTER（§9 ・§10 で設計済み。D2 ・D3） | 実装は次の gate |
| P8-OBS-57 | 基準の変更の後の鎖 | CLOSED（A3A） | CLOSED（変更なし） | — |
| P8-OBS-58【新】 | 利用規約: 継続反復の第三者への提供は私的利用でない。本 project は継続して公開する | — | **BLOCKED_PENDING_TERMS_CONFIRMATION** | §12。D6 ・D7 |
| P8-OBS-59【新】 | 解約 ・downgrade 時の削除の義務（元 data を復元できる派生物） | — | BLOCKED_PENDING_TERMS_CONFIRMATION | 削除の手順の設計が要る |
| P8-OBS-60【新】 | 既存の V2 client は raw の bytes ・受信の時刻を返さない | — | BLOCKED_PENDING_ADAPTER | wrapper（§3） |

---

## 16. 監督の決定の packet

| id | 問い | 選択肢 | 推奨 |
|---|---|---|---|
| **D1** identity の bootstrap の方針 | 実の登録の出所と手順 | (a) §4.2 の機械の候補 ＋ 人の一括の審査（`HUMAN_REVIEWED`）；(b) 全件を人が個別に審査；(c) 別の authority（EDINET code ・法人番号）を先に A1 に足す | **(a)**。普通株 ・単一の上場物から。例外は個別 |
| **D2** 注記 store の authority の class | 何として扱うか | (a) `SEMANTIC_METADATA_RECORD` ＝ provider の写しの運用上の authority（観測 ・投資の authority ではない）；(b) 派生 record（保存せず毎回導出） | **(a)**。保存しないと「どの版の規則で解いたか」が再生できない |
| **D3** HOLD store の authority の class | 同上 | (a) 運用の record（authority ではない ・自動昇格なし）；(b) 保存しない（log だけ） | **(a)**。監査と再実行に要る |
| **D4** 通貨の適格 | §8 | A ／ B ／ C | **B を pilot、A を 2 段目** |
| **D5** executor の再検証 | 渡された plan の扱い | (a) 全部を再導出し、plan は cross-check（不一致は拒否）；(b) plan を信用 | **(a)** |
| **D6** raw の保存の境界 | raw の本文を保存するか ・どこに ・いつまで | (a) 保存しない（取り込みの event に sha256 だけ）；(b) private の data root に content address で保存し解約で削除；(c) 規約の確認まで保留 | **(a) を pilot**。(b) は P8-OBS-58 ・59 の確認の後 |
| **D7** 最初の pilot の範囲 | §13 | (a) 1〜3 発行体 ・JP_GAAP ・連結 ・3 月期 ・8 要求；(b) より広く | **(a)**。ただし **P8-OBS-58 の確認（J-Quants 由来の物を公開物に載せない、または載せてよい範囲）が pilot の前提** |
| **D8** 後から取得した record の知識の時刻 | §6 | (a) TDnet の開示日時（DOCUMENTED の不変性に依る）＋ 業者側の改訂は digest で検知して取得の時刻；(b) 常に取得の時刻 | **(a)**。(b) は過去の cutoff の分析を不可能にする |

決定なしに進めない（governance の選択を黙って決めない）。

---

## 17. 実装の順（提案。各 gate は合成 data で test し、実データは最後）

```
P8-A3R（本 gate: 設計）→ 監督の決定 D1〜D8 ＋ P8-OBS-58 ・59 の確認
  → P8-ST1  注記 store ・HOLD store（§9 ・§10。追記専用 JSONL。合成 data）
  → P8-ADP0 provider の record の identity ・取り込みの event ・知識の時刻の写し ・4 欄 ・期間 ・通貨の規則（純関数。合成の行）
  → P8-EXE  append の executor（§11。合成の行 → A2 ・注記 ・HOLD。plan の cross-check）
  → P8-ID1  bootstrap の候補の生成 ＋ 審査 manifest（合成の snapshot）→ 人の審査の手順
  → P8-PILOT2 実データの E2E（§13。審査済みの一括 ・8 要求 ・raw は memory ・§14 の基準）
```

各 gate で A1 ・A2 ・A2R ・A3A ・A3B は byte 一致のまま。

---

## 18. 検証 ・変更 ・判定

- 変更: 本書【新規】・`CHANGELOG.md`（v5.64）・`tests/intelligence/phase8_runtime_registry.py`（本書の登録 ・anchor `P8_A3B`）・
  `tests/intelligence/test_screener_intelligence_boundary.py`（本書の登録と、16 module ・6 test ・先行の 14 文書が `P8_A3B` と byte 一致する
  guard）。runtime ・config ・workflow ・Pages ・main.py は無変更。
- 検証の結果は最終報告に記す（基準 5545 passed ／ 2 skipped ＋ guard 1 件）。

**判定: P8_A3R_REAL_DATA_BRIDGE_DESIGN_COMPLETE / READY_FOR_SUPERVISOR_REVIEW**

adapter ・注記 store ・HOLD store ・executor ・identity の登録 ・実データの pilot ・追加の指標 ・screen ・ranking ・推奨 ・Theme ・
Phase 9 は行っていない。J-Quants の data API への要求は 0 回。
