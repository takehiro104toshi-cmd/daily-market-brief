# PHASE 8 / P8-A2R — J-QUANTS REAL-DATA SEMANTIC REMEDIATION（公式の仕様の確認 ・設計の記録）

P8-PILOT1 の実の応答で見つかった、凍結した A2 の財務の観測の意味と J-Quants Light `/v2/fins/summary` の間の意味の隔たり
（会計基準 ・連結 ／ 単体 ・予想の修正）を扱う gate。監督指示（2026-09-28）に従い、**実装の前に公式の仕様を確かめる**。

- 基準: P8-PILOT1 `cbf86cc10ec3d9ce9ff9cc3dd731e49ba0d43328`（CLOSED ／ FROZEN）。full pytest の基準 5347 passed ／ 2 skipped。
- 本書は credential ・header ・raw の応答 ・財務の実の値を載せない。J-Quants の API への追加の要求は 0 回。

---

## 0. 結論

1. **公式の文書を 1 ページも読めなかった。** 2026-09-28 に、本 session の network の egress policy が公式の host（`jpx-jquants.com` ・
   `jpx.gitbook.io` ・`www.jpx.co.jp`）への接続を拒否した（shell: proxy が CONNECT に 403 ＝ `connect_rejected`、WebFetch: `EGRESS_BLOCKED`）。
   各 host 1 回ずつの確認で、再試行 ・迂回（mirror ・cache ・検索の要約 ・SDK）はしていない（§2）。
2. したがって §1 の確認の項目は **DOCUMENTED 0 件**。分類は OBSERVED_IN_PILOT ・INFERRED ・UNKNOWN だけ（§4）。
3. A2 の意味の隔たりは PILOT1 の証拠と凍結した A2 の code だけで特定できた（§5）。中心は、**財務の観測の slot の identity
   （主語 ・欄 ・`statement_basis` ・期間）に会計基準が無い**こと。
4. 監督の policy lock（D-P8-A2R-1〜8）の下で、Option A〜D を比べ、**Option D（canonical の意味の metadata の record ＋ provider の
   写しの provenance の record。A2 の record は変えない）** を設計として選んだ（§7 ・§8）。
5. **実装はしていない。** 監督指示 §4「公式の文書が不足し、安全な remediation を決められない場合は実装せず BLOCKER として停止」に
   従う。canonical の語彙（会計基準の enum）と provider の写し（`DocType` の token → canonical）の根拠は公式の文書に依る（§9）。
6. A2 ・A1 ・Phase 4〜7 の runtime は 1 byte も変えていない。変更は本書 ・`CHANGELOG.md` ・Phase 8 の文書の登録と凍結の guard だけ。
7. **P8-OBS-50: BLOCKED_ON_OFFICIAL_SPEC**（§11）。
8. A3 の準備度: 売上成長率 ・営業利益率を含む財務の指標はすべて開始できない（§12）。
9. 判定: **P8_A2R_OFFICIAL_SPEC_BLOCKER**（§18）。

---

## 1. 基準 ・anchor

| 項目 | 値 |
|---|---|
| branch | `claude/investment-intelligence-phase6` |
| 開始の HEAD | `cbf86cc10ec3d9ce9ff9cc3dd731e49ba0d43328`（P8-PILOT1 の凍結。working tree は clean） |
| PILOT1 の report | `cbf86cc` と byte 一致（開始時に確認） |
| P8-A1 の runtime | 凍結 anchor `4162e9c5b934456e528288b99a5908069a2f6624` からの無許可の変更なし（既存の guard で確認） |
| A2 の runtime | `observation_model` ・`observation_resolver` ・`observation_store` は無変更 |
| full pytest の基準 | 5347 passed ／ 2 skipped |

---

## 2. 公式の文書の証拠

| id | page | URL | 本 gate の状態 |
|---|---|---|---|
| S01 | 財務情報（/fins/summary） | https://jpx-jquants.com/ja/spec/fin-summary | DOC_ACCESS_BLOCKED（shell 403 ・WebFetch `EGRESS_BLOCKED`） |
| S02 | 開示書類種別 | https://jpx-jquants.com/ja/spec/fin-summary/typeofdocument | DOC_ACCESS_BLOCKED（同じ host） |
| S07 | 提供データの更新タイミング | https://jpx-jquants.com/ja/spec/data-update | DOC_ACCESS_BLOCKED（同じ host） |
| S09 | V1 から V2 への変更点 | https://jpx-jquants.com/ja/spec/migration-v1-v2 | DOC_ACCESS_BLOCKED（同じ host） |
| S10 | データ内容 ・仕様（Help） | https://jpx-jquants.com/ja/help/data | DOC_ACCESS_BLOCKED（同じ host） |
| S16 | /fins/statements（V1 の文書） | https://jpx.gitbook.io/j-quants-ja/api-reference/statements | DOC_ACCESS_BLOCKED（shell 403） |
| — | JPX の一般の page | https://www.jpx.co.jp/ | DOC_ACCESS_BLOCKED（shell 403） |

到達の記録（2026-09-28。credential なし ・data の path なし）:

| host | shell（curl） | WebFetch |
|---|---|---|
| `jpx-jquants.com` | CONNECT に 403（proxy の記録 `connect_rejected`） | `EGRESS_BLOCKED` |
| `jpx.gitbook.io` | 同上 | 試していない（同じ policy） |
| `www.jpx.co.jp` | 同上 | 試していない（同じ policy） |

使わなかったもの: blog ・Q&A ・wrapper ・SDK ・検索の要約 ・記憶からの仕様。**公式の本文を読めないことを、推測で埋めない。**

---

## 3. PILOT1 の証拠（`cbf86cc` の report の要約。report は変えない）

- 応答は `{"data": [...]}`、1 行 111 欄、値は文字列、欠損は `""` だけ。
- `DocType` の財務諸表の行は `<期間>FinancialStatements_<Consolidated|NonConsolidated>_<JP|IFRS>` の形。予想の修正の行は
  `EarnForecastRevision` ・`DividendForecastRevision` で、連結の区分 ・会計基準の token が無い。
- `NonConsolidated` の行は単体の値を接頭辞の無い欄（`Sales` ・`OP` ・`NP`）に持つ。年度の連結の行は `NC*` に単体の値を同居させる。
- `OP` はあり、`OperatingProfit` は無い。通貨 ・桁を示す欄は無い。
- PILOT1 の証拠は観測で、公式の意味の代わりにしない（D-P8-A2R-8）。

---

## 4. 文書と観測の matrix

分類: DOCUMENTED ／ OBSERVED_IN_PILOT ／ DOCUMENTED_AND_OBSERVED ／ INFERRED ／ UNKNOWN。本 gate は DOCUMENTED を 1 件も付けられない。

### 4.A DocType

| 項目 | 分類 | 証拠 ・残る事 |
|---|---|---|
| 文法（`<期間>FinancialStatements_<区分>_<基準>`） | OBSERVED_IN_PILOT | 観測した 12 通りの形。公式の文法は未読 |
| 値の全集合 | UNKNOWN | 観測は 14 通り。S02 が要る |
| `Consolidated` ／ `NonConsolidated` の意味 | INFERRED | token の名前からの推定。公式の定義は未読 |
| `JP` ／ `IFRS` の意味 | INFERRED | `JP` ＝ 日本の会計基準は推定。他の基準（米国の基準 ・修正国際基準など）の token は UNKNOWN |
| `EarnForecastRevision` | OBSERVED_IN_PILOT | 行の存在と、実績の欄が空。意味は UNKNOWN |
| `DividendForecastRevision` | OBSERVED_IN_PILOT | 同上 |
| 修正の行の会計基準 ・連結の区分 | OBSERVED_IN_PILOT（無いことを観測） | 別の欄で示されるかは UNKNOWN |

### 4.B 期間

| 項目 | 分類 | 証拠 ・残る事 |
|---|---|---|
| `CurPerType` の値 `1Q` `2Q` `3Q` `FY` | OBSERVED_IN_PILOT | 全集合は UNKNOWN |
| 累計か単独か | INFERRED | 全行で `CurPerSt` ＝ `CurFYSt`（累計の幅と整合）。値が累計かは公式の文書が要る |
| `CurPerSt` ／ `CurPerEn` | OBSERVED_IN_PILOT | 両端を含むかは UNKNOWN |
| `CurFYSt` ／ `CurFYEn` | OBSERVED_IN_PILOT | 同上 |

### 4.C 実績の欄

| 項目 | 分類 | 証拠 ・残る事 |
|---|---|---|
| `Sales` | OBSERVED_IN_PILOT | 項目の意味は UNKNOWN |
| `OP` | OBSERVED_IN_PILOT | 空の意味（無い ／ 当てはまらない）は UNKNOWN |
| `OdP` | OBSERVED_IN_PILOT | IFRS の行で全行が空。意味は UNKNOWN |
| `NP` | OBSERVED_IN_PILOT | どの純利益かは UNKNOWN |
| `NC*` | OBSERVED_IN_PILOT | 単体の値と推定（INFERRED）。連結の行の `NC*` の会計基準は UNKNOWN |
| `OperatingProfit` が正式の欄か | UNKNOWN | V2 の実の応答に無い（OBSERVED_IN_PILOT）。V1 の欄名かは S09 ・S16 が要る |
| 連結 ／ 単体の行での欄の意味 | OBSERVED_IN_PILOT | 接頭辞の無い欄の基準は行の `DocType` に従って変わる（観測）。公式の定義は未読 |

### 4.D 予想の欄

| 項目 | 分類 | 証拠 ・残る事 |
|---|---|---|
| `F*` ・`NxF*` ・`*2Q` ・`FNC*` | OBSERVED_IN_PILOT（欄の存在）／ INFERRED（当期 ・翌期 ・上半期 ・単体の意味） | 公式の定義は未読 |
| 修正の行の意味 | UNKNOWN | どの期間の予想を修正したか、連結か単体か |
| 実績と予想の分離 | OBSERVED_IN_PILOT | 欄の名前で分かれる。意味の対応は INFERRED |

### 4.E 開示の identity ／ 時刻

| 項目 | 分類 | 証拠 ・残る事 |
|---|---|---|
| `DiscDate` | OBSERVED_IN_PILOT | 実の公表日かは UNKNOWN（P8-OBS-51） |
| `DiscTime` | OBSERVED_IN_PILOT | 3 つの数字の組。意味は UNKNOWN |
| time zone | UNKNOWN | 印は観測されない |
| DiscTime が無い時の意味 | UNKNOWN | 3 回の標本で空は 0 行 |
| `DiscNo` | OBSERVED_IN_PILOT | 応答の中で一意。範囲 ・安定性は UNKNOWN |
| 公表 ／ 提供の時刻の意味 | UNKNOWN | S07 が要る |

### 4.F 単位

| 項目 | 分類 | 証拠 ・残る事 |
|---|---|---|
| 通貨 | UNKNOWN | 欄は観測されない |
| 桁 | UNKNOWN | 欄は観測されない |
| 数の表現 | OBSERVED_IN_PILOT | 文字列 |
| `DivUnit` | UNKNOWN | 欄は観測、要求 #1 で全行が空 |
| 欠損 ／ 空文字の意味 | UNKNOWN | 表現は `""` だけ（OBSERVED_IN_PILOT） |

---

## 5. 意味の隔たり（凍結した A2 と実の provider）

| id | 隔たり | A2 の現在 | 実の provider（PILOT1） | 帰結 |
|---|---|---|---|---|
| G1 | 会計基準の次元 | `FundamentalActual` ／ `FundamentalForecast` に会計基準の欄が無い。slot の identity（`fundamental_slot_fields`: class ・主語 ・欄 ・`statement_basis` ・期間）にも無い | 行の `DocType` の token に現れる（財務諸表の行だけ） | slot ごとに一本の鎖で、2 つ目の根は `FORK` で拒否される（`ObservationHistory`）。違う会計基準の値（基準の変更の年など）は、同じ slot の `supersedes` の revision としてしか入れず、基準の違いが「訂正」に見える。D-P8-A2R-1 を A2 で表せない |
| G2 | 連結の区分の出所 | `statement_basis` は必須の enum（`CONSOLIDATED` ／ `NON_CONSOLIDATED`）で、「不明」を表せない | 財務諸表の行は `DocType` の token ＋ 欄の `NC` の接頭辞。修正の行は token が無い | 出所が確かめられない行を A2 に写すと、推定で基準を付けることになる。D-P8-A2R-2 ・5 に反する。今は写せない（fail closed）が、UNKNOWN を正規の状態として表す場所が無い |
| G3 | provider の区分の metadata | `ObservationProvenance` は `source_class` ・`source_record_ref` ・`source_field` ・`adjustment_ref` だけ | `DocType` が区分を運ぶ | `DocType` を canonical にしない（D-4）が、写しの根拠として保持する場所が無い |
| G4 | 予想の修正 | `FundamentalForecast` は `statement_basis` と `target_period` が必須 | 修正の行は区分の token が無い。対象の期間の意味は UNKNOWN | 今は写せない（正しい fail closed）。写す規則は公式の文書が要る |
| G5 | 実績と予想の identity | class が別（`FUNDAMENTAL_ACTUAL` ／ `FUNDAMENTAL_FORECAST`） | 欄の名前で分かれる | 隔たりではない（A2 で表せる）。欄の写しは adapter の契約（D-7） |
| G6 | 期間の基準 | `PeriodBasis` ＋ quarter、日付の整合の検査あり | `CurPerType` ＋ 4 つの日付 | A2 で表せる。値の写し（`1Q` → 累計 ・1）は公式の確認が要る（LUV-04 ・05） |
| G7 | 開示の時刻の精度 | `KnowledgeTime`（`TIMESTAMP` ／ `DATE`、`KnowledgeState`） | `DiscDate` ・`DiscTime`（time zone 不明） | A2 で表せる（`DATE` か取得の時刻）。隔たりではない |
| G8 | 出所の欄の provenance | `source_field` がある | 欄は `Sales` ・`NC*` など | 欄の配置を canonical にしない（D-3）。`source_field` で足りる |
| G9 | 単位 ・通貨 | 金額に明示の `Scale` と JPY を要求 | 桁 ・通貨の欄が無い | A2 の隔たりではない（公式の文書の不足）。確認まで金額を写せない |

要点: **A2 の欠陥は G1（会計基準の次元が record と slot の identity に無い）と G2 ／ G3（区分の不明と provider の metadata を
表す場所が無い）**。G4 は写しの規則の不足、G9 は文書の不足で、A2 の欠陥ではない。

---

## 6. 監督の policy lock（本 gate で LOCK。変更しない）

| id | 内容 |
|---|---|
| D-P8-A2R-1 | 会計基準は A2 の観測の意味の一部。A3 で推定 ・補完しない |
| D-P8-A2R-2 | 連結 ／ 単体の基準も A2 の観測の意味の一部 |
| D-P8-A2R-3 | J-Quants の欄の配置（`Sales` ／ `NC*` 等）を canonical の会計の意味にしない。provider の表現と canonical を分ける |
| D-P8-A2R-4 | `DocType` は出所の metadata として保持してよいが、canonical の次元にしない。文書化された写しがある時だけ canonical に写す |
| D-P8-A2R-5 | 修正の行などで会計基準 ・基準が確定しない時、別の行から暗黙に継承しない。UNKNOWN ／ 未解決で fail closed |
| D-P8-A2R-6 | A3 は会計の意味を推定しない。A3 が使えるのは A2 で意味が確定した観測だけ |
| D-P8-A2R-7 | `OperatingProfit` ／ `OP` などの欄の写しは、公式に確かめた写しを経て adapter の契約で解く。名前の類似で推定しない |
| D-P8-A2R-8 | PILOT1 の実の応答は観測の証拠で、公式の意味の代わりではない |

---

## 7. remediation の選択肢

| 観点 | A: 既存の record の拡張 | B: 新しい意味の metadata の record | C: 新しい provider の写し ／ provenance の record | D: hybrid（B ＋ C） |
|---|---|---|---|---|
| 内容 | `FundamentalActual` ／ `Forecast` に会計基準の欄を足し、slot の identity に含める | 観測の record を参照し、canonical の会計基準 ・連結の基準 ・その確定の状態（KNOWN ／ UNKNOWN）を持つ追記専用の record | 観測の record を参照し、provider の `DocType` ・出所の欄 ・写しの規則の版 ・その文書の根拠を持つ追記専用の record | canonical（B）と provider（C）を別の record にする |
| 互換 | 凍結した A2 の record の形 ・`as_dict` ・`from_dict` ・slot の key が変わる。既存の履歴と hash が壊れる | A2 は不変 | A2 は不変 | A2 は不変 |
| PIT | 同じ record の中で扱える | metadata に独自の知識の時刻が要る（観測より前に知り得ない） | 同左 | 同左 |
| 追記専用の履歴 | 形の変更で過去の record の再解釈が要る | 追記だけ。訂正は A1R の形（無効化 ／ 置き換え）に倣える | 同左 | 同左 |
| fail closed | 必須の欄にすると UNKNOWN を表せない。任意にすると既定値の推定になる | UNKNOWN を正規の状態で表せる。metadata の無い観測は A3 に出さない | 写しの根拠の無い行を canonical にしない | 両方 |
| 将来の adapter | adapter が A2 の core に provider の論理を持ち込みやすい | canonical の語彙だけ。provider の論理は無い | provider の論理はここに閉じる（D-3 ・4） | 境界が最も明確 |
| G1 の slot の衝突 | identity に含めるので解ける | slot は変わらないので、同じ slot に違う基準の観測が来たら resolver が `NOT_COMPARABLE` ／ 衝突として止める規則が要る | 解かない | B の規則で止める |
| 変更の大きさ | 凍結の runtime の破壊的な変更 | 新しい module（追加だけ） | 新しい module（追加だけ） | 新しい module 2 つ（追加だけ） |

---

## 8. 選んだ設計（設計だけ。実装していない）

**Option D（hybrid）。** A2 の凍結の runtime を変えず、追加だけで D-P8-A2R-1〜8 を満たす最小の安全な案。

1. **canonical の意味の metadata の record**（B）
   - 参照: A2 の観測の record の id（1 つの観測に 1 つの現在の metadata。訂正は追記の置き換え）。
   - `accounting_standard`: canonical の enum ＋ `UNKNOWN`。**enum の値の集合は本 gate で決めない**（公式の文書で provider が示す基準を
     確かめてから、監督が決める）。
   - `statement_basis`: A2 の `StatementBasis` を再利用 ＋ 確定の状態（KNOWN ／ UNKNOWN）。A2 の観測の `statement_basis` と食い違えば
     reject。
   - 確定の根拠: C の record の参照（根拠の無い KNOWN を作らない）。
   - 知識の時刻: 観測の知識の時刻より前にしない。
2. **provider の写しの provenance の record**（C）
   - `DocType` の文字列 ・出所の欄（`Sales` ／ `NCSales` 等）・写しの規則の id と版 ・その規則の公式の文書の参照（S01 ・S02 の節）。
   - 写しの規則は、公式に文書化された token だけを canonical に写す。文書に無い token ・修正の行は `UNKNOWN`（D-4 ・5）。
3. **A3 への出し方**（A3 は実装しない。契約だけ）
   - A3 が使えるのは、metadata が会計基準 ・連結の基準ともに KNOWN の観測だけ（D-6）。
   - 比べる 2 つの観測で会計基準 ・連結の基準が同じ時だけ比べる。どちらかが UNKNOWN、または違う → `NOT_COMPARABLE`。
   - 同じ slot に違う会計基準の観測がある → 衝突として止める（G1）。
4. **推定の禁止**: 修正の行は別の行の基準を継承しない。`NC*` の会計基準を行の token から継承しない（文書が定めるまで UNKNOWN）。

---

## 9. 実装の要約

**実装していない。** 理由:

- 監督指示 §4 は「公式の確認で十分な根拠が得られ、A2 の意味の欠陥が明確なら」実装を許す。欠陥（G1〜G3）は明確だが、**公式の確認の
  根拠は 0 件**。
- canonical の会計基準の enum の値の集合と、provider の token から canonical への写しは、どちらも公式の文書に依る（D-4 ・7）。
  根拠なしに enum を決めると、後の公式の確認で canonical の語彙を変える必要が出て、追記専用の履歴を壊す恐れがある。
- したがって BLOCKER として停止する（§18）。

監督の判断の選択肢（本 gate では行わない）:

- (a) 公式の host を許可した環境で本 gate をやり直す（推奨）。
- (b) 監督が §13 の checklist の公式の抜粋を確かめて渡す（SV と同じ扱い）。
- (c) provider に依らない canonical の側（B の record の形 ・`UNKNOWN` ・A3 の比較の規則）だけを、enum の値を監督が決めて先に実装する
  ことを認可する。provider の写し（C）は公式の確認まで空のまま。

---

## 10. 互換 ・PIT の分析（選んだ設計について）

| 観点 | 評価 |
|---|---|
| 既存の A2 の record ・履歴 ・test | 不変（追加の module だけ）。既存の slot の key ・hash は変わらない |
| PIT | metadata は独自の知識の時刻を持つ。観測より前に知り得たことにしない。STRICT_KNOWLEDGE の解決で、cutoff に存在しない metadata は UNKNOWN として扱う |
| 追記専用 | metadata ・写しの record は追記だけ。訂正は A1R の無効化 ／ 置き換えの形に倣う |
| fail closed | metadata の無い観測 ・UNKNOWN の観測は A3 に出ない |
| provider の論理の閉じ込め | `DocType` の解釈は C の写しの規則だけ。A2 の core ・B の record は provider を知らない |
| A1 | 変えない（主語の解決は A1 ／ A1R のまま） |
| Phase 4〜7 | 変えない |

---

## 11. P8-OBS-50 の処分

**BLOCKED_ON_OFFICIAL_SPEC。**

- PILOT1 の観測だけでは閉じない（監督指示 §5）。
- 観測で分かった事: 財務諸表の行では、連結の区分と会計基準が `DocType` の別の token として現れる。
- 閉じるのに要る事: `DocType` の文法 ・値の全集合 ・token の意味（S02 ・S01）、修正の行の区分、`NC*` の会計基準。どれも公式の文書が
  要り、本 session では読めない。
- A2 の側の設計（§8）は準備できた。写しの規則は公式の確認の後。

---

## 12. A3 の準備度（A3 は実装しない）

| 指標 | 分類 | 主な理由 |
|---|---|---|
| 売上成長率 | BLOCKED_BY_PROVIDER_MAPPING | 会計基準 ・連結の基準の写し（G1〜G3、D-6）、`Sales` の意味、累計（LUV-05）。加えて桁 ・通貨（LUV-16 ・17）と実の identity の登録 |
| 営業利益率 | BLOCKED_BY_PROVIDER_MAPPING | 同上 ＋ `OP` の空の意味（LUV-08） |
| 純利益率 | BLOCKED_BY_PROVIDER_MAPPING | 同上 ＋ `NP` がどの純利益か |
| EPS 成長率 | BLOCKED_BY_PROVIDER_MAPPING | 同上 ＋ 株式の分割の調整の意味 |
| ROE | BLOCKED_BY_PROVIDER_MAPPING | `Eq` ／ `ShEq` の定義が UNKNOWN（A2 の `EQUITY` は 1 つ） |
| ROA | BLOCKED_BY_PROVIDER_MAPPING | `TA` ・`NP` の意味 ＋ 会計基準 |
| PER | BLOCKED_BY_PROVIDER_MAPPING | EPS の写し ＋ 価格と開示の PIT の揃え |
| PBR | BLOCKED_BY_PROVIDER_MAPPING | `BPS` ／ 純資産の定義 |
| 時価総額 | BLOCKED_BY_UNIT_SEMANTICS | 株数の定義 ・業者の `MktCap` の定義が UNKNOWN（A2.5 の BLOCKED のまま） |
| 価格の return | READY_WITH_RESTRICTIONS | 合成 data の意味論だけ。生値は corporate action を含まない、業者の調整値の定義は UNKNOWN。実データは BLOCKED_BY_IDENTITY（実の identity の未登録） |
| 変動率 | READY_WITH_RESTRICTIONS | 同上 |
| 流動性 | READY_WITH_RESTRICTIONS | A2 の `VOLUME` だけ（売買代金の欄は A2 に無い）。実データは BLOCKED_BY_IDENTITY |

**最初の A3 の候補（売上成長率 ・営業利益率）は安全に開始できない。** D-P8-A2R-6 により、A3 は会計の意味が A2 で確定した観測だけを
使う。その確定の場所（§8）が未実装で、写しの根拠（公式の文書）が無い。

---

## 13. 未解決の事項（公式の文書で確かめる checklist）

| page | 確かめる事 |
|---|---|
| S01 | 欄の一覧と説明（`Sales` ・`OP` ・`OdP` ・`NP` ・`NC*` ・`F*` ・`NxF*` ・`*2Q` ・`DiscDate` ・`DiscTime` ・`DiscNo` ・`DocType` ・`CurPerType` ・4 つの日付）、単位 ・通貨、DiscTime の time zone ・欠損 |
| S02 | `DocType` の値の全集合と文法、連結 ／ 単体 ・会計基準の token の意味、予想の修正の行の区分 |
| S07 | 公表の時刻と提供の時刻の区別 |
| S09 ・S16 | `OperatingProfit`（V1）と `OP`（V2）の対応 |
| S10 | 累計 ／ 単独、空文字の意味、単位 ・桁 |
| 監督の判断 | canonical の会計基準の enum の値の集合、§9 の (a)〜(c) |

規約は INDIVIDUAL_JQUANTS_TERMS_REVIEW_REQUIRED のまま。

---

## 14. 変更したファイル

- `docs/databank/PHASE8_A2R_JQUANTS_SEMANTIC_REMEDIATION.md`【新規】（本書）
- `CHANGELOG.md`（v5.59）
- `tests/intelligence/phase8_runtime_registry.py`: `PHASE8_DOCS` に本書、P8-PILOT1 の凍結の anchor `P8_PILOT1`
- `tests/intelligence/test_screener_intelligence_boundary.py`: 本書の登録と、runtime ・Phase 8 の test ・先行の文書（PILOT1 の report を
  含む）が `P8_PILOT1` と byte 一致する guard
- runtime（A1 ・A2 ・A1R）・config.yaml ・knowledge ・scripts ・workflow ・Pages ・main.py ・Phase 4〜7 ・先行の文書は無変更

---

## 15. test

結果は最終報告に記す（A2 ・A1 ・A1R ・Phase 8 の guard ・Phase 7 ・Phase 6 ・Phase 4 ／ 5 の guard ・full pytest。基準 5347 passed ／ 2 skipped）。

---

## 16. git status

最終報告に記す。

---

## 17. commit ／ push

最終報告に記す。

---

## 18. 次の gate の推奨と判定

```
P8-A2R（本 gate: OFFICIAL_SPEC_BLOCKER。設計は §8 に記録）
  → 公式の文書へのアクセス（どちらか）
      a. 環境の network の設定で jpx-jquants.com（必要なら jpx.gitbook.io）を許可し、本 gate をやり直す（P8-A2R の再実行）
      b. 監督が §13 の checklist の公式の抜粋を確かめて渡す
  → 監督の判断: canonical の会計基準の enum ・§9 (c) の認可の有無
  → P8-A2R の実装（Option D。追加だけ）
  → A3: 売上成長率 ・営業利益率（A2 で意味が確定した観測だけ）
```

**判定: P8_A2R_OFFICIAL_SPEC_BLOCKER**

A3 ・screen ・ranking ・推奨 ・Theme ・実の identity の登録 ・実データの取り込み ・adapter ・J-Quants への追加の要求は行っていない。
