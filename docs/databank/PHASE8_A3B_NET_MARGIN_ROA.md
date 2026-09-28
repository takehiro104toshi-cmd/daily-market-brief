# PHASE 8 / P8-A3B — NET MARGIN + ROA（時点の分母）

凍結した P8-A3A（`84c2d52`。売上成長率 ・営業利益率の architecture）を再利用し、**純利益率と ROA（時点の分母）だけ**を足す gate。
監督の決定（P8-A3A ＝ PASS ／ CLOSED ／ FROZEN、GO → P8-A3B）に従う。競合する指標の枠組み ・resolver ・結果の model は作らない。

- 基準: P8-A3A `84c2d52f59d573d6f558f64fbbd1589fe97ecf24`（凍結）、P8-A2R-IMPL `4d3540c`、P8-A2 `b686b00`、P8-A1 `4162e9c`。
  full pytest の基準 5518 passed ／ 2 skipped。
- 本書は credential ・raw の応答 ・財務の実の値を載せない。J-Quants の data API への要求は 0 回。LLM は使わない。

---

## 0. 結論

1. 追加した runtime は 1 module `fundamental_metrics_extended`（`net_margin` ・`roa_point_in_time`）。A3A の脚の解決 ・A2R の互換 ・
   Decimal の比 ・結果の組み立て（`fundamental_metrics` の実装）をそのまま import して使う。`fundamental_metrics.py` は byte 一致。
2. **A3A の `metric_model` に enum の 4 行だけを足した**（`MetricKind.NET_MARGIN` ・`ROA_POINT_IN_TIME`、`MetricLeg.NET_INCOME` ・
   `TOTAL_ASSETS`）。理由: `MetricResult` は `metric` が `MetricKind` の member でなければ拒み、Python の Enum は member を持つと継承で
   拡張できないので、A3B の指標は結果の model を変えずには表せない（具体的な不足）。status ・理由の code ・規則 ・既存 member の順は
   変えていない。境界の guard が「差分はこの 4 行だけ」を anchor と比べて固定する（§9）。
3. 純利益率 = 当期純利益（A2 `NET_INCOME` ＝ 公式 `NP`: 親会社株主に帰属する当期純利益。DOCUMENTED）／ 売上。営業利益 ・経常利益で
   代用しない。年度と累計（累計の期間の利益率）を支える。
4. **ROA は時点の分母**: 年度の当期純利益 ／ その年度の総資産（A2 `TOTAL_ASSETS` ＝ 公式 `TA`: 総資産。DOCUMENTED。A2 の data_date は
   年度末）。平均の総資産は作らない。名前 `ROA_POINT_IN_TIME` がそれを示す。年度だけ。
5. 基準 ・区分が違う ・UNKNOWN → fail closed（A2R の gate。基準の変更は不連続。P8-OBS-57）。PIT は A2 の resolver。
6. 判定: **P8_A3B_NET_MARGIN_ROA_VALIDATED / READY_FOR_SUPERVISOR_REVIEW**（§13）。

---

## 1. 開始の状態

| 項目 | 値 |
|---|---|
| branch | `claude/investment-intelligence-phase6` |
| 開始の HEAD | `84c2d52f59d573d6f558f64fbbd1589fe97ecf24`（期待どおり。working tree は clean） |
| A1 ／ A2 ／ A2R ／ A3A の凍結 | `4162e9c` ／ `b686b00` ／ `4d3540c` ／ `84c2d52` と byte 一致（開始時に確認。15 module） |
| full pytest の基準 | 5518 passed ／ 2 skipped |

---

## 2. architecture の選択

| 選択 | 理由 |
|---|---|
| 追加の module `fundamental_metrics_extended.py` | A3A の `fundamental_metrics.py` は凍結（byte 一致が要る）。拡張は別 module で、A3A の脚の解決（`_resolve_leg`）・互換（`_compatibility`）・比（`_ratio_minus`）・結果（`_result`）・入力の検査 ・期間の label ・年度の規則性を import して再利用する（競合する実装を作らない。test D で `def _resolve_leg` 等が無いことを確かめる） |
| `metric_model` の enum の 4 行の追加 | §0-2 の不足。他に手は無い（別の結果の model は禁止。Enum の継承は不可）。差分は registry に宣言し guard が固定 |
| 共通の手順 `_same_period_ratio` | 同じ期間の 2 脚の比（A3A の営業利益率と同じ手順）。純利益率と ROA はこれの引数の違いだけ |

authority: 結果は `DERIVED_NON_AUTHORITY_NON_PERSISTENT`（推奨 ・score ・順位 ・screen ・Theme ・watchlist ・Production DNA では
ない）。保存 ・LLM ・network ・時計 ・`now` ／ `latest` の既定は無い。

---

## 3. 純利益率（`net_margin`）

| 項目 | 内容 |
|---|---|
| 式 | `NET_INCOME ／ REVENUE`（同じ期間 ・同じ発行体 ・同じ基準 ・同じ区分） |
| 分子 | A2 `NET_INCOME`（公式 `NP` ＝ 親会社株主に帰属する当期純利益。非支配株主持分を含む合計ではない。DOCUMENTED） |
| 代用の禁止 | 営業利益 ・経常利益 ・他の利益を使わない（`OPERATING_INCOME` の観測しか無ければ `NET_INCOME:NOT_FOUND`） |
| 期間 | 年度（`FISCAL_YEAR`）と年度の初めからの累計（`CUMULATIVE_YEAR_TO_DATE` quarter 1〜3。label で累計と示す。単独の四半期と呼ばない） |
| 拒む期間 | 単独の四半期（`PERIOD_BASIS_UNSUPPORTED`）、不規則な長さの年度（`FISCAL_YEAR_IRREGULAR`）。4Q ・5Q ・OtherPeriod は A2 に写らず届かない |
| 分母 | 売上 ＝ 0 → `UNDEFINED(DENOMINATOR_ZERO)`、売上 ＜ 0 → `UNDEFINED(DENOMINATOR_NEGATIVE)` |
| 符号 | 純利益が負なら負の利益率（有効な値） |
| 値 | Decimal ・6 桁 ・偶数丸め ・正準の文字列（A3A と同じ） |

## 4. ROA（時点の分母。`roa_point_in_time`）

| 項目 | 内容 |
|---|---|
| 式 | `ROA_POINT_IN_TIME = 年度の NET_INCOME ／ その年度の TOTAL_ASSETS` |
| 分母 | A2 `TOTAL_ASSETS`（公式 `TA` ＝ 総資産。DOCUMENTED）。年度の観測の data_date は年度末。**期末の残高であることは貸借対照表の
  性質と A2 の期間の付き方からの INFERRED**（公式の欄の説明は「総資産」だけ）。結果の名前と本書がこれを明示する |
| 平均の総資産を使わない理由 | (期首 ＋ 期末) ／ 2 は 2 つの年度の観測を跨ぐ合成で、両方の観測の適格 ・PIT ・基準の一致と、平均の定義の明示の契約が要る。
  P8-A3B にはその契約が無い。前の年度の総資産は読まない（test B で `ta23` が入力に無いことを確かめる） |
| 期間 | **年度だけ**。累計 ・単独の四半期 → `PERIOD_BASIS_UNSUPPORTED`（解決の前に止まる）。不規則な年度 → `FISCAL_YEAR_IRREGULAR` |
| 分母の符号 | 総資産 ＝ 0 → `UNDEFINED(DENOMINATOR_ZERO)`、＜ 0 → `UNDEFINED(DENOMINATOR_NEGATIVE)` |
| 符号 | 純利益が負なら負の ROA |
| 年率化 ・TTM | 無い（年度の値どうしなので不要） |

canonical の入力の十分性: `NET_INCOME` ・`TOTAL_ASSETS` は A2 の閉じた語彙（Issuer ・MONETARY_AMOUNT ・期間つき）、A2R 再実行で
`NP` ・`TA` の公式の意味が DOCUMENTED。ROA を止める不足は無い（期末の残高の INFERRED は名前で明示し、平均を作らないことで安全側）。

---

## 5. 共通の適格（A3A と同じ）

入力の型 → `INVALID_INPUT`；A2 の `resolve` が `FOUND` でない → resolver の status の理由（`INSUFFICIENT_DATA` ／
`INSUFFICIENT_TIME_PRECISION`）；注記なし → `SEMANTICS_MISSING`；注記の不一致 → `SEMANTICS_MISMATCH`；値なし → `VALUE_ABSENT`；
基準 ・区分 UNKNOWN → `ACCOUNTING_STANDARD_UNKNOWN` ・`STATEMENT_BASIS_UNKNOWN`；脚の間で違う → `ACCOUNTING_STANDARD_DIFFERS` ・
`STATEMENT_BASIS_DIFFERS`（`NOT_COMPARABLE`）。脚の名前は `REVENUE` ・`NET_INCOME` ・`TOTAL_ASSETS` ・`PAIR`。

## 6. PIT ・revision

- cutoff は caller が明示（aware）。各脚は凍結した A2 の `resolve` で解く（A3A の `_resolve_leg` を経て）。
- 訂正は過去の結果を変えない（test A ・B: 元の cutoff で元の値、訂正の後の cutoff で訂正の値、元の cutoff を再び → 同じ結果。訂正の
  record を史料から外しても同じ）。
- 未来の観測は `NOT_FOUND`。日付だけの知識に日の途中の cutoff → `INSUFFICIENT_TIME_PRECISION`（時刻を作らない）。

## 7. 会計基準の不連続

基準が違えば `NOT_COMPARABLE(ACCOUNTING_STANDARD_DIFFERS)`（JP↔IFRS ・JP↔US を両指標で test）。橋渡しの authority は無い（P8-OBS-57）。

---

## 8. 結果 ・理由の語彙の変更

| 変更 | 内容 |
|---|---|
| `MetricKind` | ＋ `NET_MARGIN` ・`ROA_POINT_IN_TIME`（既存の 2 つの後ろ） |
| `MetricLeg` | ＋ `NET_INCOME` ・`TOTAL_ASSETS`（既存の 5 つの後ろ。理由の並びで既存の脚の順は変わらない） |
| `MetricStatus` ・`ReasonCode` ・`STATUS_FOR_CODE` ・強さの順 ・`MetricResult` | 変更なし（code は 29 のまま） |

## 9. 凍結の証明

- `fundamental_metrics.py` と A1 ・A2 ・A1R ・A2R の 13 module は `84c2d52` と byte 一致。
- `metric_model.py` は `84c2d52` との差分が `PHASE8_A3B_METRIC_MODEL_REGISTRATION` の 4 行の追加だけ（`registration_diff` で比べる
  guard）。取り除いた行は 0。
- Phase 6 ・7 ・4 ／ 5 ・Production DNA ・main.py ・Pages ・config ・workflow は無変更（既存の guard）。

---

## 10. test（`tests/intelligence/test_screener_fundamental_metrics_extended.py`。すべて合成 data）

| 群 | 内容 |
|---|---|
| A 純利益率 | 正 ・負 ・0 の純利益、売上 0 ・負（`UNDEFINED`）、売上 ・純利益の欠損 ・MISSING の値 ・期間の不一致、営業利益で代用しない、基準 ・区分の違い ・注記の不一致 ・UNKNOWN ・修正の行 ・注記なし、未来の観測 ・訂正の cutoff の安定、日付だけの知識の日の途中の cutoff、累計の label ・単独の四半期 ・不規則な年度の拒否、Decimal の決定論 ・桁、型つきの INVALID_INPUT |
| B ROA | 正（年度末の総資産。前の年度の総資産は入力に無い）・負 ・0 の純利益、総資産 0 ・負、欠損 ・年度の不一致、年度以外の拒否（累計 ・単独 ・不規則）、基準 ・区分の違い ・注記の不一致 ・UNKNOWN、未来 ・訂正の安定 ・日の途中の cutoff、Decimal の決定論 ・平均の総資産ではない |
| C model | `MetricKind` ・`MetricLeg` の増分だけ、code は 29、既存の順は不変 |
| D architecture | float ・IO ・時計 ・network ・LLM ・評価 ・代用（OdP ・営業利益）・平均の禁止、A3A の再利用 ・競合する実装なし |

境界の guard の追加: 1 module の import の許可 ・閉包 ・指名の import（A3A の実装の名前を含む）、A3A の anchor `84c2d52` の byte
一致（14 module ・5 test ・13 文書）と `metric_model` の差分の固定、先行の層が A3B を知らない、評価の語の禁止（`roa` は指標名として許す）。

---

## 11. 変更したファイル

- `src/intelligence/screener_intelligence/fundamental_metrics_extended.py`【新規】
- `src/intelligence/screener_intelligence/metric_model.py`（enum の 4 行の追加だけ。§0-2）
- `tests/intelligence/test_screener_fundamental_metrics_extended.py`【新規】
- `docs/databank/PHASE8_A3B_NET_MARGIN_ROA.md`【新規】（本書）
- `tests/intelligence/phase8_runtime_registry.py`（module ・test ・本書の登録、`PHASE8_A3B_RUNTIME`、anchor `P8_A3A`、
  `PHASE8_A3B_METRIC_MODEL_REGISTRATION`）
- `tests/intelligence/test_screener_intelligence_boundary.py`（A3B の境界 ・指名の import ・A3A の凍結の guard、先行の guard の除外）
- `CHANGELOG.md`（v5.63）
- `fundamental_metrics.py` ・A1 ・A2 ・A1R ・A2R ・config.yaml ・knowledge ・scripts ・workflow ・Pages ・main.py ・Phase 4〜7 ・先行の文書は無変更

---

## 12. 支えない指標と残る blocker

| 指標 | 状態 |
|---|---|
| EPS 成長率 ・PER ・PBR | BLOCKED_BY_UNIT_SEMANTICS（配当 ・EPS は分割の遡及調整なし。corporate action の参照の観測が要る） |
| ROE | BLOCKED_BY_PROVIDER_MAPPING（A2 の `EQUITY` は 1 つで、`Eq`（純資産）と `ShEq`（自己資本）の区別が無い。P8-OBS-27） |
| 時価総額 | BLOCKED_BY_PROVIDER_MAPPING（`SHARES_OUTSTANDING` の定義。P8-OBS-23 ・27） |
| 価格の return ・変動率 ・流動性 | 市場の観測の指標。別の sub-gate |
| 平均の総資産の ROA ・TTM ・年率化 | 明示の契約が無い |

実データまでの blocker（変更なし）: 実の identity の登録、adapter（行 → A2 の観測 ＋ A2R の注記 ＋ plan → append）、注記 ・HOLD の
store、非円の表示の発行体の保留、利用規約。

```
P8-A3B（本 gate: VALIDATED）
  → 監督の review（`metric_model` の 4 行の受け入れを含む）
  → 次の候補: (a) adapter ／ 注記 store の設計（実データの前。identity の登録の方針を含む）
             (b) 市場の観測の指標（価格の return ・変動率 ・流動性。合成 data）
```

## 13. 判定

**P8_A3B_NET_MARGIN_ROA_VALIDATED / READY_FOR_SUPERVISOR_REVIEW**

EPS 成長率 ・ROE ・PER ・PBR ・時価総額 ・価格の指標 ・screen ・ranking ・推奨 ・Theme ・adapter ・実の identity ・Phase 9 は行っていない。
