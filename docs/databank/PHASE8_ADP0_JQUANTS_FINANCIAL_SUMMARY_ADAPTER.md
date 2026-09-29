# PHASE 8 / P8-ADP0 — PURE J-QUANTS FINANCIAL SUMMARY ADAPTER（純 adapter。書かない ・呼ばない）

P8-A3R の設計（§4〜§8）・P8-ST1 の運用 store に続き、**合成の `/v2/fins/summary` の行を A2 ／ A2R ／ ST1 の凍結の record の型へ写す
純 adapter** だけを実装した gate。監督の決定 D1〜D8（P8-A3R ＝ PASS ／ FROZEN `f1c4a4e`、P8-ST1 ＝ PASS ／ FROZEN `e831996`）に従う。
J-Quants への live の request ・API client ・executor ・store への append ・identity の登録 ・実データの pilot は**無い**。

- 基準: P8-ST1 `e831996094ba035bbfa0574c639d40faff888096`（凍結。runtime 19 module）。full pytest の基準 5602 passed ／ 2 skipped。
- 本書は credential ・raw の応答 ・財務の実の値を載せない。行の例はすべて合成（架空の code ・開示番号 ・金額）。

---

## 0. 結論

1. 追加した runtime は 2 module: `jquants_adapter_model`（厳密な入力 ・provider の record の identity ・文脈 ・結果の型）、
   `jquants_financial_summary_adapter`（写しの関数 `adapt_financial_summary_row`）。A1 ・A2 ・A1R ・A2R ・A3A ・A3B ・ST1 の 19 module は
   byte 一致。
2. 結果の authority: **`DERIVED_NON_AUTHORITY_NON_PERSISTENT`**。結果は record ではなく（`record_id` ・`canonical_line` は無い）、
   保存されず、EXE（後の gate）は本結果を信用せず authority の入力 ・文脈から写しと適格を再実行する（D5）。
3. 入力は厳密（§3）。公式に列挙された 111 欄のうち 14 欄だけを文字列のまま読む。14 欄の欠落 ・文字列でない値 ・公式の一覧に無い key
   （schema のずれ）・credential に見える文字は **`AdapterInputError`（HOLD ではなく拒否）**。公式の他の欄は捨てて保持しない。
4. provider の record の identity は自然 key（Code ・DiscDate ・DiscTime ・DiscNo ・DocType）＋ 14 欄の正準 JSON の sha256（§4）。
   `DiscNo` だけでは identity にならない（別の code が同じ DiscNo を持てる）。同じ自然 key で内容が違えば**別の revision**（上書きしない）。
5. 知識の時刻は公式の `DiscDate` ＋ `DiscTime`（TDnet の開示日時 ・JST）だけ（§5）。`DiscTime` が空なら `DATE`。取得の時刻は別の軸で、
   知識にならない。時計を読まない。
6. 期間は `FY` ・累計の `1Q` ／ `2Q` ／ `3Q` だけ（§6）。`4Q` ・`5Q` ・`OtherPeriod` ・日付の不整合 → HOLD。年率化 ・補間 ・TTM ・
   単独四半期の導出は無い。
7. DocType は凍結の A2R `map_row_semantics` の写しだけを使う（adapter は DocType を自分で解釈しない。§7）。
8. **pilot の適格（D4）は JP_GAAP だけ**（通貨 JPY を立てられる唯一の場合）。IFRS ・US_GAAP ・JMIS は `ACCOUNTING_STANDARD_UNSUPPORTED`
   ＋ `CURRENCY_UNKNOWN` で HOLD。これは**一時的な pilot の方針**で、基準が無効という主張でも J-Quants の一般の意味でもない（§8）。
9. 4 欄 `Sales` → `REVENUE`、`OP` → `OPERATING_INCOME`、`NP` → `NET_INCOME`、`TA` → `TOTAL_ASSETS`。空文字 → `NOT_REPORTED` の観測
   （0 にしない）。厳密な 10 進の構文だけ（§9）。
10. identity は caller の文脈（解決済みの A1 の `issuer_id`）だけ。無い ・形が違う → `IDENTITY_UNRESOLVED`。Code から作らない（§10）。
11. 理由が 1 つでもあれば**行ごと HOLD**（凍結の ST1 `HeldObservation` を作るだけ。append しない）。無ければ ELIGIBLE（凍結の A2 の
    `FundamentalActual` 4 件（根の形）＋ A2R の注記 ・provenance 4 組）。
12. P8-OBS-58 ・59: **BLOCKED_PENDING_TERMS_CONFIRMATION** のまま（§12）。ADP0 は live の request をしない。
13. 判定: **P8_ADP0_JQUANTS_ADAPTER_VALIDATED / READY_FOR_SUPERVISOR_REVIEW**（§14）。

---

## 1. 開始の状態

| 項目 | 値 |
|---|---|
| branch | `claude/investment-intelligence-phase6` |
| 開始の HEAD | `e831996094ba035bbfa0574c639d40faff888096`（期待どおり。working tree は clean） |
| 凍結の anchor | A1 `4162e9c` ／ A1R `e6a750f` ／ A2 `b686b00` ／ A2R `4d3540c` ／ A3A `84c2d52` ／ A3B `d8845f2` ／ A3R `f1c4a4e` ／ ST1 `e831996` と byte 一致 |
| full pytest の基準 | 5602 passed ／ 2 skipped |
| network | 使わない（J-Quants への request なし。公式の文書の再取得なし。P8-A2R 再実行の DOCUMENTED の事実を再利用） |

---

## 2. 変更の範囲（不変の宣言）

| 対象 | 状態 |
|---|---|
| `src/intelligence/screener_intelligence/jquants_adapter_model.py` | **新規**（入力 ・identity ・文脈 ・結果の型） |
| `src/intelligence/screener_intelligence/jquants_financial_summary_adapter.py` | **新規**（写しの関数） |
| `tests/intelligence/test_screener_jquants_adapter.py` | **新規**（matrix A〜H。80 test） |
| `tests/intelligence/phase8_runtime_registry.py` ・`test_screener_intelligence_boundary.py` | ADP0 の登録 ・ST1 の anchor の guard の追加 |
| A1 ・A1R ・A2 ・A2R ・A3A ・A3B ・ST1 の 19 module ・先行の Phase 8 の test 7 file ・先行の記録 16 | **byte 一致**（guard `test_adp0_*`） |
| `main.py` ・Pages ・config ・workflow ・Secrets ・legacy の株 ・ニュース ・Morning Brief | 変更なし |
| store（A1 ・A2 ・A1R ・注記 ・保留）・filesystem ・network ・時計 ・乱数 ・UUID ・LLM | adapter は触れない（import の境界 ・AST の guard） |

---

## 3. 入力の契約（`FinancialSummaryRow`）

| 規則 | 内容 |
|---|---|
| 読む欄（14） | `Code` `DiscDate` `DiscTime` `DiscNo` `DocType` `CurPerType` `CurPerSt` `CurPerEn` `CurFYSt` `CurFYEn` `Sales` `OP` `NP` `TA` |
| 必須 | 14 欄すべて。欠けると `AdapterInputError("PROVIDER_FIELD_MISSING")` |
| 型 | すべて文字列（公式: 111 欄は文字列）。他の型は `PROVIDER_VALUE_NOT_TEXT` |
| 境界 | 64 文字まで ・制御文字なし（`PROVIDER_VALUE_OUT_OF_BOUNDS`）。credential の印を含む文字は `CREDENTIAL_LIKE_TEXT` |
| 他の公式の欄（97） | 受け付けるが**捨てる**（`OdP` ・`EPS` ・`ROE` ・予想 ・配当 ・NC 系 …）。model に欄が無く、digest にも入らない |
| 公式の一覧に無い key | `PROVIDER_FIELD_UNKNOWN`（schema のずれ ・応答の形の変化を黙って通さない） |
| Mapping でない入力 | `PROVIDER_ROW_NOT_MAPPING` |

`OFFICIAL_FINS_SUMMARY_FIELDS`（111）は P8-A2R 再実行 §5.1 の公式の欄の一覧の写し（拒否の判定にだけ使う。`ROE` などの派生の欄は
読まない）。

---

## 4. provider の record の identity

| 要素 | 内容 |
|---|---|
| 自然 key | `(Code, DiscDate, DiscTime, DiscNo, DocType)` |
| digest | 14 欄の正準 JSON（key を整列 ・値は文字列のまま ・空文字を残す）の sha256（64 hex）。key の順に依らない |
| 参照 | `jq.fins_summary:<Code>.<DiscNo>.<DocType>:<digest の先頭 24>`（A2 の `source_record_ref` ・ST1 の `provider_record_ref`） |
| 参照できない token | `Code` ／ `DiscNo` ／ `DocType` が `[A-Za-z0-9_-]{1,64}` でない → 参照 None → HOLD `MAPPING_UNSUPPORTED`（正規化しない） |
| DiscNo だけ | 不十分（別の code の同じ DiscNo は別の record。test B） |
| 訂正の行 | 公式: 訂正は新しい DiscNo で上書きしない。同じ自然 key で digest が違えば別の revision（ADP0 は選ばない ・上書きしない） |

---

## 5. 知識の時刻

| 入力 | 結果 |
|---|---|
| `DiscDate` `YYYY-MM-DD` ＋ `DiscTime` `H:MM:SS` ／ `HH:MM:SS` | `KnowledgeTime.exact(datetime(..., tzinfo=JST))`（`TIMESTAMP`） |
| `DiscDate` ＋ `DiscTime == ""` | `KnowledgeTime.date_only`（`DATE`。時刻を作らない） |
| 不正な日付 ・時刻（区切り ・範囲 ・空白 ・2 月 30 日 …） | HOLD `KNOWLEDGE_TIME_INVALID` |
| 開示が期末より前 ・当日（A2 `ACTUAL_KNOWN_BEFORE_PERIOD_END`） | HOLD `KNOWLEDGE_TIME_INVALID` |
| 文脈の `acquired_at` | `HeldObservation.observed_at` にだけ入る（運用の時刻）。知識に**ならない**。naive は拒否 |

---

## 6. 期間

| `CurPerType` | 条件 | 結果 |
|---|---|---|
| `FY` | `CurPerSt == CurFYSt` かつ `CurPerEn == CurFYEn` | `FISCAL_YEAR` |
| `1Q` ／ `2Q` ／ `3Q` | `CurPerSt == CurFYSt` かつ `CurPerEn < CurFYEn` | `CUMULATIVE_YEAR_TO_DATE`（quarter 1 ／ 2 ／ 3。公式: 累計） |
| `4Q` ・`5Q` ・`OtherPeriod` ・他 | — | HOLD `PERIOD_UNSUPPORTED` |
| 日付の不整合 ・不正 ・A2 の `ReportingPeriod` の拒否（550 日超 など） | — | HOLD `PERIOD_UNSUPPORTED` |

`SINGLE_QUARTER` は作らない。年率化 ・補間 ・TTM の語は adapter の実行部に無い（test D）。

---

## 7. 意味（凍結の A2R の再利用）

`map_row_semantics(DocType, FieldFamily.UNPREFIXED_ACTUAL)` の結果だけを使う。adapter の実行部に文字列の分解（split ・endswith …）・
`IFRS` などの基準名は無い（test E）。

| A2R の結果 | HOLD の理由 |
|---|---|
| `document_kind == UNRECOGNIZED`（表に無い ・大文字小文字の違い） | `DOCTYPE_UNRECOGNIZED` |
| `document_kind` が財務諸表でない（REIT ・予想の修正） | `DOCTYPE_OUT_OF_SCOPE` |
| `accounting_standard == UNKNOWN`（Foreign ・REIT …） | `ACCOUNTING_STANDARD_UNKNOWN` ＋ `CURRENCY_UNKNOWN` |
| `statement_basis is None`（NonConsolidated の IFRS ／ Foreign ／ OtherPeriod …） | `STATEMENT_BASIS_UNKNOWN` |

d2（NonConsolidated）は凍結のまま: 承認済みの `{1Q,2Q,3Q,FY}FinancialStatements_NonConsolidated_JP` だけ `NON_CONSOLIDATED`
（evidence `OBSERVED_IN_PILOT` ＋ `SUPERVISOR_APPROVED_MAPPING_RULE`）。他の NonConsolidated は広げない。

---

## 8. 通貨 ・pilot の適格（監督の決定 D4）

| 基準 | 結果 |
|---|---|
| `JP_GAAP` | 通貨 `JPY` ・`Scale.ONE`（公式: 円 ・scaling なし）→ 適格 |
| `IFRS` ／ `US_GAAP` ／ `JMIS` | HOLD `ACCOUNTING_STANDARD_UNSUPPORTED` ＋ `CURRENCY_UNKNOWN` |
| `UNKNOWN` | HOLD `ACCOUNTING_STANDARD_UNKNOWN` ＋ `CURRENCY_UNKNOWN` |

`PILOT_ELIGIBLE_STANDARDS = (JP_GAAP,)` は**一時的な pilot の方針**。IFRS 等が無効 ・劣るという主張ではなく、通貨を安全に立てられる
範囲を pilot で狭めたもの。FX 換算 ・名前 ／ 国 ／ code からの通貨の推定はしない。基準の間の橋渡しはしない（P8-OBS-57）。

---

## 9. 値

| 入力 | 結果 |
|---|---|
| `""` | `ObservationValue.absent(MONETARY_AMOUNT, NOT_REPORTED)`（観測は作る。0 にしない） |
| `^-?(0|[1-9][0-9]*)(\.[0-9]+)?$` に合う | `ObservationValue.present(MONETARY_AMOUNT, canonical_decimal, JPY, ONE)` |
| 空白 ・`+` ・桁区切り ・指数 ・NaN ・Infinity ・先頭の 0 ・全角 ・単位 ・`1.` ・`.5` | HOLD `VALUE_UNPARSEABLE`（正規化しない） |

---

## 10. identity の境界

- `AdapterContext.issuer_id` が `is_issuer_id` を満たさない（空 ・Code ・別の形）→ HOLD `IDENTITY_UNRESOLVED`。
- adapter は `derive_issuer_id` ・`IssuerRegistration` ・identity の store ・resolver を import しない（boundary の閾）。
- 解決済みの identity は HOLD の record にも載せる（`issuer_id`。無ければ空）。`security_id` は ADP0 では常に空。

---

## 11. 結果の形（`AdapterResult`）

| 欄 | 内容 |
|---|---|
| `status` | `ELIGIBLE` ／ `HOLD` |
| `provider_record` | 自然 key ・digest ・参照（§4） |
| `reasons` | ST1 の `HeldReason` を `ordered_reasons` で整列（ELIGIBLE は空） |
| `eligible` | `EligibleMaterial`: `issuer_id` ・`knowledge` ・`period` ・`observations`（`FundamentalActual` × 4。`supersedes=""`）・`annotations`（(`ObservationSemantics`, `SemanticMappingProvenance`) × 4） |
| `held` | ST1 の `HeldObservation`（`reasons` は結果と同一。append しない） |
| `mapping_rule_version` ・`rules_version` | `p8_jquants_v2_fins_summary_doctype:0.1.0` ・`p8_jquants_fins_summary_adapter:0.1.0` |
| `authority_class` | `DERIVED_NON_AUTHORITY_NON_PERSISTENT` |

`raw` ・`payload` ・`row` ・`response_body` ・`api_response` の欄は無い。`as_dict()` に元の行の欄の key は出ない（自然 key の 5 値と
provenance の `source_field` 名だけ）。結果は frozen ・決定論（同じ行 ＋ 文脈 → 等しい結果）。

---

## 12. 条件 ・境界 ・P8-OBS-58 ／ 59

- live の J-Quants API request ・client ・retry ・pagination は ADP0 に無い（EXE ／ pilot の gate で、OBS-58 の解決後）。
- raw の応答は memory だけ（D6）: adapter は元の行を保持せず、test の行は合成。
- J-Quants 由来の出力は Pages ・公開の Morning Brief ・公開の artifact ・第三者へ出ない（D7）。ADP0 の結果は memory だけ。
- P8-OBS-58 ・59: **BLOCKED_PENDING_TERMS_CONFIRMATION**（変更なし）。

---

## 13. 検証

| 項目 | 結果 |
|---|---|
| `test_screener_jquants_adapter.py`（matrix A〜H） | 80 passed |
| boundary ・registry の guard（ADP0 の登録 ・ST1 の anchor の byte 一致 ・sanctioned import ・語彙） | passed |
| full pytest | §14 の報告（本文の最終報告） |

---

## 14. 判定

**P8_ADP0_JQUANTS_ADAPTER_VALIDATED / READY_FOR_SUPERVISOR_REVIEW**

ADP0 の後は STOP（EXE ・pilot ・live の request は監督の次の gate）。
