# PHASE 5 ENTRY CONTRACT（Prediction Journal・監督者凍結事項）

本書は **Phase 5（Prediction Journal）の入口契約**である。Phase 4（Morning Brief）が
`PHASE_4_COMPLETE / CLOSED / FROZEN` となった後、Entry Contract A0 監査・A0.5R 実測・
A1 凍結 gate を経て監督者（ChatGPT）が決定した N-1〜N-6 と、その境界条件を記録する。

本書は設計事項であり、**変更は監督者の決定による**。Claude Code は独自判断で本書を変更しない
（`CLAUDE.md`「設計原則」）。実装は含まない。

- 対象 Phase: Phase 5 = Prediction Journal（P5-1 記録 / P5-2 自動評価 / P5-3 較正統計）。
  Theme Map（6）・Narrative（7）・Screener（8）以降は本書の対象外。
- 前提 Phase: Phase 4（COMPLETE / CLOSED / FROZEN）。Phase 4 の入口契約は
  `PHASE4_ENTRY_CONTRACT.md`（歴史的開発 branch に保存）であり、その class 2〜7 の
  default deny を本書は**そのまま継承**する。
- 開発 branch: `claude/investment-intelligence-phase5`（production main `15739707…` から分岐）。
  歴史的 branch `claude/investment-intelligence-phase0-rvdplu` は Phase 0〜4 の記録として凍結。
- Phase 5 は **INTERNAL ANALYTICS** である（§9）。顧客向け出力・Pages・`/v2`・通知・
  Phase 4 の出力意味論を一切変更しない。

---

## 0. 用語の凍結

| 用語 | 定義 |
|---|---|
| **PredictionRecord** | Phase 4 が**既に生成した** `MorningBrief` / `MarketSignal` の意味論を、過去のその時点の判断として**写すだけ**の不変・追記専用の観測記録。新しい市場判断を含まない |
| **EvaluationRecord** | ある PredictionRecord に対する realized outcome の照合結果。**別レコード**であり PredictionRecord を編集しない |
| **realized_return** | `close(session_date) / close(previous Tokyo trading session) − 1`。Decimal・分類前に丸めない連続値（§2 N-2） |
| **NEUTRAL_RANGE 分類** | realized_return を UP / NEUTRAL_RANGE / DOWN の 3 値へ写す**評価層の規則**（§2 N-2）。realized_return そのものではない |
| **abstention（棄権）** | Phase 4 の `MarketSignal.available == false` の状態。予測試行ではあるが方向予測ではない（§6） |
| **origin** | PredictionRecord の由来。`LIVE`（実運用時点で記録）／`REPLAY`（事後の再生・検証）。混在させない（§7） |
| **DEFER** | 評価に必要な材料（実績・カレンダー検証）が揃わないため EvaluationRecord を**作らない**状態。中立扱いにしない |

---

## 1. 凍結決定 N-1〜N-6

### N-1 PREDICTION IDENTITY

- `prediction_id` は**表示に依存しない prediction semantics** から content-address する。
- `brief_id` / `signal_id` は **provenance reference** として PredictionRecord に保持するが、
  **`prediction_id` の hash payload には含めない**。
- **`delivery_id` を prediction identity に使わない**（`markdown_sha256` / `markdown_bytes` に
  従属し、描画変更で動く。v4.82 で実際に動いた実績がある）。
- 表示 / projection 層の変更が semantic prediction identity を変えてはならない。

根拠（A0 監査で実測）: `MorningBrief.projection_payload` は `tier*.as_dict()` 経由で
`display_text` を含み、`signal_payload` は `brief_id` を含む。したがって P4-1A の
`customer_text()` を将来変更すると `brief_id` → `signal_id` が動く。予測の同一性は
「何を予測したか」で決まるべきで、「どう表示したか」に従属させない。

### N-2 REALIZED OUTCOME CLASSIFICATION（**凍結値**）

- target = **TOPIX**（`index:topix.close.closing.tokyo`）
- realized_return = `close(target_session) / close(previous Tokyo trading session) − 1`
- 算術: **Decimal 互換の決定論的算術。分類前に丸めない。**
- 分類（**NEUTRAL_RANGE の境界は閉区間**）:

```
UP            : return >  +0.30%
NEUTRAL_RANGE : −0.30% <= return <= +0.30%
DOWN          : return <  −0.30%
```

- **threshold は明示的に版管理する。** 本書が凍結する初版の識別子:

```
NEUTRAL_BAND_RULE_VERSION = "topix_neutral_band:1.0.0"
  target                 = index:topix.close.closing.tokyo
  return_definition      = close(session_date) / close(previous Tokyo trading session) - 1
  band_pct               = 0.30   (symmetric, inclusive boundary for NEUTRAL_RANGE)
  arithmetic             = Decimal, unrounded before classification
```

- **凍結原則**:
  - この閾値は **MarketSignal の成績を使わずに**定めた（独立に定義された realized-outcome
    classification であり、精度最適化された閾値ではない）。
  - **歴史的な連続 realized_return は常に保存する。** 将来の scoring / classification の
    版変更は、歴史的 PredictionRecord にも保存済み realized_return にも**書き戻さない**
    （新しい `NEUTRAL_BAND_RULE_VERSION` で新しい EvaluationRecord を追記する）。

### N-3 INTEGRITY

- Phase 5 初期 journal に **新しい hash chain を作らない**。
- 用いるのは: 決定論的 / content-addressed ID、追記専用レコード、既存の backup / manifest
  完全性（`core/backup.py` の sha256 inventory）。
- **第二の transaction-chain system を発明しない**（governance の `decisions.jsonl` chain へも
  結合しない）。

### N-4 TARGET

- Phase 5 の評価対象 = **TOPIX のみ**。
- Phase 4 `MarketSignal` の意味論を**変更しない**。Phase 4 は「TOPIX を lead context とする
  日本株の方向文脈」のままであり、Phase 5 がそれを TOPIX に対して評価する。

### N-5 HORIZON

- **1 東京取引 session の close-to-close outcome**:
  `reference_session` の TOPIX close → `session_date` の TOPIX close。
- **東京取引カレンダーを検証すること**（`tokyo_calendar` の実測検証済み区分 `HolDiv` のみ）。
  **weekday 演算へフォールバックしない。**
- カレンダーを検証できなければ **evaluation = DEFER**。
- 検証項目（凍結決定から導かれる具体条件・監督者確認事項として §11 に列挙）:
  (a) `session_date` が検証済み取引日であること、(b) `reference_session` が `session_date` の
  **直前の**取引 session であること。(b) を満たさない記録は「1 session」の horizon 定義に
  合致しないため DEFER とし、黙って多日 return を 1 日 return として評価しない。

### N-6 RUNTIME / PERSISTENCE

- **P5-1 は OFFLINE から始める。**
- **repository-commit persistence を追加しない**（legacy journal の `git add` 方式を採らない）。
- **公開 `/v2` publication に結合しない。**
- 後続の controlled runtime validation は artifact-based path を使いうるが、**別の認可 gate** が
  必要である。

---

## 2. N-2 の経験的根拠（provenance）

閾値は次の**実データ測定**に基づく。合成データ・legacy journal・yfinance 等の代替 source は
使っていない。

| 項目 | 値 |
|---|---|
| 取得 driver | `src/intelligence/predictions/topix_research_acquire.py`（schema `topix_research_acquisition:0.1.0`、commit `255868a`） |
| 取得 source | J-Quants **v2** `/indices/bars/daily/topix` ＋ `/markets/calendar`（この 2 endpoint のみ） |
| 取得窓 | `2021-09-17`〜`2026-09-17`（**API 自身が返した entitlement 境界**に基づく最大取得可能履歴。10 年要求は `http_400 cause=plan_not_entitled` で安全に失敗し、その forensic root は保存） |
| research root | 隔離 root（basename `topix-neutral-band-2026-entitled`。production data root・リポジトリ外） |
| 取得結果 | `ACQUISITION_OK`、TOPIX 観測 **1,223**、derived `return_1d` **1,222**、`topix_pages = 1`、calendar rows 1,827、13 取得検証すべて true |
| 測定 runner | `src/intelligence/predictions/topix_neutral_band_measure.py`（schema `topix_neutral_band_measurement:0.1.0`、commit `07fb2bb`）— read-only・ネットワーク module 不使用 |
| 測定結果 | `MEASUREMENT_OK`、realized returns **1,222**、coverage `2021-09-17`〜`2026-09-17`、19 検証すべて true |
| percentile method | nearest-rank（`ceil(p/100·N)` 番目・補間なし） |
| \|return\| P25 | **0.299648%** |

±0.30% の分布（N = 1,222）:

| 分類 | 比率 |
|---|---|
| UP | 41.73% |
| NEUTRAL_RANGE | 25.20% |
| DOWN | 33.06% |
| directional（UP + DOWN） | 74.80% |

FULL 年の NEUTRAL_RANGE%（端の 2021 / 2026 は PARTIAL として除外）:

| 年 | NEUTRAL_RANGE% |
|---|---|
| 2022 | 25.00% |
| 2023 | 29.27% |
| 2024 | 24.08% |
| 2025 | 28.81% |
| min / max / spread | 24.08% / 29.27% / **5.19pp** |

**重要**: 上記測定は TOPIX の return 分布だけを見ており、MarketSignal の的中率は
一切参照していない（threshold → accuracy の最適化を禁止した gate の下で実施）。

---

## 3. Phase 5 knowledge / semantic 境界

- Phase 4 `MarketSignal` を**事後的に「取引予測」として再定義しない**。
- `PredictionRecord` は、Phase 4 が既に生成した意味論を写す**不変の観測 journal レコード**である。
- **Phase 5 は第二の市場分析エンジンを作らない。**
- **P5-1 が読むのは、観測を journal するために必要な Phase 4 の `MorningBrief` ＋ `MarketSignal`
  の意味論出力だけ**である。
- P5-1 が**読んではならない**もの:
  - 評価用の市場観測（実績データ）
  - 未来の outcome
  - formal-review Decisions（`decisions.jsonl`）
  - corpus
  - replay
  - `CompassDraft`（予測の権威として）
- **P5-2 だけが評価層**である。
- **P5-3 は観測的な較正 / 分析のみ**である（authority ではない）。
- Compass DNA の自動変更・formal-review pattern の自動昇格・APPROVED-but-NOT_PROMOTED の
  production rule 化・REJECTED / KEEP_REVIEWING の消費は、Phase 4 entry contract のとおり
  **すべて禁止**を継承する。`rule_ref` 別の成績統計は observational analytics であって
  authority ではなく、件数を必ず併記し、`knowledge/` へ書かない。

---

## 4. source 分類（A0 監査の分類を凍結）

| 分類 | 対象 |
|---|---|
| **STABLE_INPUT** | `MarketSignal` の意味論 field（`available` / `level` / `confidence` / `horizon` / `unavailable_reason`）、`MorningBrief`、`session_date`、`reference_session`、prediction semantic identity field |
| **REFERENCE_ONLY** | `MorningDelivery` packaging、`EvidencePackage`（`package_id` / `cutoff` / `excluded_look_ahead` を参照値として記録するのは可・再解釈は不可）、Compass DNA（read-only。`rule_ref` を添えるのは可・書き戻し禁止） |
| **DO_NOT_COUPLE** | `CompassDraft`、`delivery_id`（semantic identity として）、formal Decisions、recommendation queue（`APPROVE_RECOMMENDED` 等）、corpus、replay |

明確化: **`brief_id` / `signal_id` は provenance reference であり、`prediction_id` の
semantic hash 入力ではない**（N-1）。

補足（A0 監査の実測）: 公開 `/v2` JSON には `level` / `confidence` / `horizon` が含まれない
（`PUBLIC_SIGNAL_KEYS` は `available` / `label` / `unavailable_reason` のみ）。したがって
P5-1 は公開 artifact から予測を再構成せず、**producer run 内の `MarketSignal` オブジェクト**
の意味論を入力とする。その実行位置は N-6 のとおり OFFLINE から始め、runtime 同居は別 gate。

---

## 5. PredictionRecord の構成（field 分類の凍結）

| 分類 | field |
|---|---|
| **identity** | `prediction_id`（semantic hash） |
| **provenance reference（hash に含めない）** | `brief_id`、`signal_id`、`package_id`、`draft_id` |
| **prediction semantics（hash に含める）** | `session_date`、`reference_session`、`available`、`level`（生値）、`confidence`、`horizon`、`unavailable_reason`（6 値の生値）、`origin`（LIVE / REPLAY）、prediction schema version |
| **audit metadata（hash に含めない）** | `created_at`、`cutoff`、`principle_refs` / `market_principle_version`、source schema versions（`MORNING_BRIEF_SCHEMA_VERSION` / `MARKET_SIGNAL_SCHEMA_VERSION` / `OUTLOOK_RULE_VERSION`） |
| **display-only（記録しない）** | `signal.label`（日本語表示語）、`delivery_id`、`markdown_sha256`、tier 本文 / `display_text` |

`confidence` は必須である（`HIGH` と `MEDIUM` が同じ `level` へ畳まれるため、confidence が
無いと較正が成立しない）。`created_at` は `prediction_id` の材料にしない（再実行の冪等性）。

具体的 schema・field 名・正規化規則は **P5-1A** で設計する（本書は分類と原則のみ）。

### 5.1 P5-1A で確定した schema と identity（`prediction_record:0.1.0`）

P5-1A（`src/intelligence/predictions/prediction_record.py`）が上表の分類を field 名へ写した
結果を記録する。**上表の分類・N-1〜N-6 を変えない**（明確化のみ）。

| 分類 | field |
|---|---|
| A. identity 入力（**hash に含める**） | `schema_version`（`prediction_record:0.1.0`）、`session_date`、`reference_session`、`origin`（`LIVE` / `REPLAY`）、`available`、`level`、`confidence`、`horizon`、`unavailable_reason` |
| B. provenance（hash に含めない） | `brief_id`、`signal_id`、`package_id`、`draft_id`、`morning_brief_schema_version`、`market_signal_schema_version` |
| C. audit metadata（hash に含めない） | `recorded_at`（上表の `created_at`）、`cutoff`、`principle_refs`、`market_principle_version`、`outlook_rule_version`（P4 `CompassOutlook.rule_version` の写し。outlook を持たない記録では空） |
| D. 導出（保存しない） | identity payload、canonical 文字列、`is_abstention`（`= not available`） |
| E. 存在しない（受け取る引数も無い） | `delivery_id`、`markdown_sha256`、`label` / `display_text` / 本文 / Markdown / HTML、realized outcome、評価状態、`topix_neutral_band` 版、市場観測 |

identity（N-1）の直列化契約:

- payload は A の **9 key だけ**。key 昇順、`json.dumps(sort_keys=True, separators=(",", ":"),
  ensure_ascii=False)`、UTF-8 bytes を SHA-256 し、`prediction_id = "pred_" + 先頭 24 hex`
  （`core.ids.content_id` と同一機構。新しい hash chain ではない ＝ N-3）。
- 欠落は空文字で表し JSON null を使わない。`level` は enum 値文字列（unavailable では `""`）、
  `available` は JSON true/false、`origin` は `LIVE` / `REPLAY`。
- `schema_version` は PredictionRecord 自身の版であり、N-2 の分類版 `topix_neutral_band:1.0.0`
  とは別概念。分類版は EvaluationRecord（P5-2）に属し、PredictionRecord には置かない。

状態機械（P4 `build_market_signal` の写し。矛盾は拒否し正規化しない）:

- `available == true`: `level` ∈ 5 値、`confidence` ∈ 3 値、`horizon` ∈ 既知（現在
  `next_tokyo_session` のみ）、`(level, confidence)` は P4 `LEVEL_BY_STATE` の値域 7 組のみ、
  `unavailable_reason == ""`。
- `available == false`: `level` 無し、`unavailable_reason` ∈ 6 値。`direction_mixed` /
  `direction_uncertain` のときだけ outlook の `confidence` / `horizon` を保持し、それ以外は両方空。

schema-local 検証と verified-calendar 検証の分離: schema は `reference_session < session_date`
（ISO 日付）までを検証する。「直前の**検証済み**東京取引 session であること」（§11-1）は
P5-2 の verified-calendar 境界で検証し、schema は暦を持たず weekday 演算を行わない。

---

## 6. abstention（棄権）の意味論

- Phase 4 が unavailable / abstained を返した signal も **必ず journal する**。
- 棄権は次のいずれにも**なってはならない**:
  - coverage から消える
  - NEUTRAL_RANGE になる
  - 方向予測になる
  - 通常の予測として採点される
- **coverage と棄権率は常に明示する。** 較正統計は最低 3 つの分母を併記する:
  ①全 session ②予測試行（= 全 session）③方向評価可能な予測。②と③の差（棄権率）を隠さない。
- 棄権の理由別内訳（`draft_not_usable` / `draft_abstained` / `tier3_unavailable` /
  `no_outlook` / `direction_mixed` / `direction_uncertain`）を保持し、規律的棄権
  （`direction_mixed`）と材料不足棄権を別集計する。
- `available == true` かつ `level == NEUTRAL_RANGE` は**方向主張**であり棄権ではない。
  N-2 により NEUTRAL_RANGE も方向評価の対象となる（realized が NEUTRAL_RANGE なら的中）。

---

## 7. point-in-time の意味論

| 対象 | 規則 |
|---|---|
| PredictionRecord | **不変・追記専用。** commit 後の更新 API を持たない |
| EvaluationRecord | **別の追記専用レコード。** PredictionRecord を編集しない |
| 遅延 / 欠測 outcome | **DEFER**（EvaluationRecord を作らない。中立扱いしない・補間しない・近傍日で代用しない） |
| 改定された市場データ | **新しい EvaluationRecord が前の評価を supersede する**（前の行は消さない。`Observation.revision_of` と整合） |
| 歴史的 PredictionRecord の書き換え | **決して黙って行わない** |
| 前の EvaluationRecord の書き換え | **決して黙って行わない** |
| live と replay | `origin` で区別し、同じ journal に混在させない。REPLAY 行は既定で較正統計に含めない |
| 評価 cutoff | `session_date` の東京 close 以降にのみ評価可。使う観測は `known_at` を持つものに限る（`known_at` 欠落は使わない） |
| rerun | `prediction_id` 既知なら冪等（追記しない）。同一 session に意味論の異なる予測が現れたら監督者 review |

---

## 8. persistence 契約

推奨初期 layout（凍結）:

```
<data_root>/predictions/predictions.jsonl     canonical・追記専用・不変
<data_root>/predictions/evaluations.jsonl     canonical・追記専用・不変
<data_root>/predictions/index/*.sqlite3       再構築可能な導出物のみ（canonical ではない）
```

- パターンは既存 `compass/store.py` と同じ（canonical JSONL append-only ＋ 再構築可能 SQLite ＋
  content id による冪等 skip）。
- **legacy `src/analysis/investment_journal.py` を Phase 5 journal の権威として使わない**
  （同一日付上書き・単一 JSON 全書き換え・repository commit の方式を継承しない）。
- **same-date overwrite semantics を持たない。**
- 破損 / 部分書き込みは fail closed（黙って読み飛ばさない）。
- `<data_root>` は `data/vnext`（`.gitignore` 済み）を既定とするが、P5-1 offline 段階では
  明示指定 root を要求し、暗黙の production fallback を持たない（研究 driver と同じ規律）。

---

## 9. INTERNAL ONLY 境界

Phase 5 は **INTERNAL ANALYTICS** に留まる。本書の凍結は次を**変更しない**:

- GitHub Pages
- `/v2` 公開 JSON（`PUBLIC_KEYS` 9 / `PUBLIC_SIGNAL_KEYS` 3 / `PUBLIC_UNAVAILABLE_REASONS` 6）
- root publication（legacy root）
- 顧客向け Markdown / HTML
- 通知
- Phase 4 の出力意味論

single Pages deployer・producer unscheduled・trust anchor
（`29c3beaf0c32c56ab5c4129aee89dbd1e06aec8b`）・freshness 契約はすべて不変。

---

## 10. Phase の順序（凍結）

```
Entry Contract 凍結（本書）
  → P5-1A  PredictionRecord schema ＋ 決定論的 identity 設計
  → P5-1B  追記専用 journal / store 実装
  → P5-1C  凍結 P4 MorningBrief ＋ MarketSignal 意味論からの offline ingestion
  → （後続）P5-2  EvaluationRecord / TOPIX realized outcome
  → （後続）P5-3  較正 analytics
```

各段は前段の追記済みレコードのみを入力とする。**先へ飛ばない。** J-Quants capability 評価は
P5-2 実装直前に 1 回 live 再確認する（データ面は `CURRENT_PLAN_SUPPORTED / ALREADY_INGESTED`
で確定済み）。

---

## 11. 監督者確認事項（凍結決定から導いた明確化）

本書の記述のうち、N-1〜N-6 の文言を**補う形で導いた**ものを列挙する。3 点とも P5-1A gate で
監督者が **LOCKED** とした（確認済み。以後は §12 の手続きでのみ改訂する）。

1. **LOCKED** — N-5 検証項目 (b): `reference_session` は `session_date` の**直前の検証済み
   東京取引 session**でなければならない。そうでない記録は DEFER とする（多日 return を
   1 session return として評価しない）。
2. **LOCKED** — N-2 の版識別子文字列 `topix_neutral_band:1.0.0` とその構成要素。
3. **LOCKED** — §6: `available == true` かつ `level == NEUTRAL_RANGE` は棄権ではなく方向評価の
   対象（realized が NEUTRAL_RANGE なら的中）。

---

## 12. 本書の変更手続き

- 本書は監督者の設計決定である。Claude Code は**変更せず提案のみ**行う。
- Phase 5 実装が本書の契約に収まらないと判明した場合、実装を進めずに停止し、改訂提案を出す。
- 本書は Phase 4 コード・Compass DNA・governance record・production data root・workflow を
  一切変更しない（documentation only）。
