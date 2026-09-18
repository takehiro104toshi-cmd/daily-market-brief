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

### 5.2 P5-1C で確定した P4 → PredictionRecord の source 境界と対応表（`prediction_ingest.py`）

**P5-1C は P4 意味論を写す。評価も再計算もしない（COPY, DO NOT ANALYZE）。**
§5 / §5.1 の分類と N-1〜N-6 を変えない。

権威となる P4 意味論 source（調査結果）:

```
reports/delivery_pilot.main():
    result = run_pipeline(...)                      # PipelineResult(draft, package, ...)
    brief  = build_morning_brief(result.draft, result.package)
    signal = build_market_signal(brief)
```

MorningBrief と MarketSignal が**両方揃うのはこの in-process 境界だけ**である。P4 は
`persists_canonical_intelligence: False` で、`brief.as_dict()` / `signal.as_dict()` を内部
artifact に書かない。公開 `/v2` JSON は level / confidence / horizon を含まず、pilot の
stdout row は表示 `label` を含み confidence / horizon を欠く。従って P5-1C の入力は
**in-process の凍結オブジェクト**（MorningBrief・MarketSignal・CompassDraft・EvidencePackage）
であり、公開 JSON・顧客 Markdown / HTML・表示ラベル・通知 payload・Pages artifact を source に
しない（逆写像 parser を持たない）。安定した offline artifact は現状存在しないため CLI /
file format を発明せず、runtime / artifact への handoff は後続の認可 gate に属する。

| PredictionRecord field | P4 source | 種別 |
|---|---|---|
| `session_date` / `reference_session` | `MorningBrief`（signal / draft / package と一致を要求） | 直接コピー |
| `available` / `level` / `confidence` / `horizon` / `unavailable_reason` | `MarketSignal` をそのまま（正規化しない） | 直接コピー |
| `brief_id` / `package_id` / `draft_id` | `MorningBrief` | 直接コピー |
| `signal_id` | `MarketSignal` | 直接コピー |
| `morning_brief_schema_version` / `market_signal_schema_version` | 各 object の `schema_version`（未対応版は fail closed。migrate しない） | 直接コピー |
| `recorded_at` | `CompassDraft.generated_at`（P4 生成時刻。`run_pipeline(now=…)` が必ず設定する。無ければ拒否し、ingestion 時刻で代用しない） | 不変 source object 経由 |
| `cutoff` | `EvidencePackage.cutoff`（look-ahead 境界。aware 必須） | 不変 source object 経由 |
| `principle_refs` | `MorningBrief.tier3.principle_refs` | 直接コピー |
| `market_principle_version` | `MorningBrief.points` の非空 `market_principle_version`（高々 1 種。複数混在は矛盾として拒否。無ければ空） | 直接コピー |
| `outlook_rule_version` | `CompassDraft.outlook.rule_version`（outlook 無しは空） | 不変 source object 経由 |
| `origin` | 呼び出し側が `PredictionOrigin` を明示（既定値・推定なし） | 呼び出し側指定 |

回復不能な field は**無い**（BLOCKER なし）。

cross-object 整合（すべて fail closed・修復しない・「最新」を使わない・日付だけで結合しない）:
`signal.brief_id == brief.brief_id`、`draft.draft_id == brief.draft_id`、
`package.package_id == brief.package_id == draft.package_id`、signal / draft / package の
`session_date` / `reference_session` が brief と一致、brief_id / signal_id の content-address
再検証、schema 版、`draft.verdict` / `draft.generator` の一致、`brief.tier3.outlook` と
`draft.outlook` の direction / confidence / horizon の一致。

state のコピー: `available == true` は level / confidence / horizon をそのまま
（NEUTRAL_RANGE は available のまま、棄権ではない）。`available == false` も journal に載せる
（coverage から消さない）。`direction_mixed` / `direction_uncertain` は P4 が保持する
confidence / horizon をそのまま写し、他の unavailable は両方空のまま。unavailable を
NEUTRAL_RANGE にしない。

依存境界: `compass.evidence_package` を import しない（その closure は context.snapshot →
context.builders / facts へ広がる）。EvidencePackage は `package_id / session_date /
reference_session / cutoff` の 4 属性だけを Protocol で受け、真正性は brief / draft との
id・session 一致で担保する。`build_market_signal` / `build_morning_brief` / `run_pipeline` /
市場観測 / TOPIX / 取引カレンダー / J-Quants / EvaluationRecord / `topix_neutral_band` /
較正 / network / git / 公開・配信 module を参照しない。

store との相互作用: 凍結 `PredictionStore.append` をそのまま使う（`APPENDED` /
`ALREADY_PRESENT`。`PredictionConflict` は握り潰さず伝播）。

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

### 8.1 P5-1B で確定した journal の storage 契約（`prediction_store.py`）

上の §8 と N-1〜N-6 を変えない。P5-1B が確定した具体を記録する。

- **JSONL が唯一の権威。** `<data_root>/predictions/predictions.jsonl`。in-memory index は
  開くたび／`reload()` で JSONL から全再構築する導出物。P5-1B は SQLite index を作らない
  （作る場合も §8 のとおり再構築可能な導出物にとどめる）。
- **data_root は呼び出し側が明示する。** `core.paths` の既定値・環境変数・config へ fallback
  しない。repository path・production root・research root をコードに持たない。読むだけでは
  ディレクトリを作らず、初回 append で親ディレクトリを作る。Git 操作・network を持たない。
- **journal 直列化**（identity 直列化とは別の関心事）: `PredictionRecord.as_dict()` を
  key 昇順・`separators=(",", ":")`・`ensure_ascii=False`・UTF-8・`\n` 終端の 1 行にする。
  表示文字列・machine path・secret は schema 上存在しない。
- **append 意味論**:

  | 状態 | 結果 |
  |---|---|
  | 未知 `prediction_id` | 1 行だけ追記 → `APPENDED`（`wrote_line = true`） |
  | 既知 id ＋ canonical 行が byte 一致 | 書かない → `ALREADY_PRESENT`（`wrote_line = false`） |
  | 既知 id ＋ いずれかの field が異なる（provenance / audit を含む） | `PredictionConflict`（fail closed。merge・更新・2 行目追記をしない） |

  N-1 により provenance / audit は id に入らない。従って **同じ id は冪等の十分条件ではなく**、
  保存済み canonical 行との完全一致を要求する。
- **物理重複**: journal に同じ `prediction_id` の行が 2 つあれば、内容が同一でも権威 load は
  `PHYSICAL_DUPLICATE_IDENTICAL` / `PHYSICAL_DUPLICATE_CONFLICTING` で失敗する（append API が
  冪等である以上、物理重複は履歴 / 手動の破損を意味する）。既存 store（compass / ledger）は
  set で黙って畳むが、Phase 5 はその慣行を継承しない（§8「黙って読み飛ばさない」）。
- **load の fail closed**: 不正 JSON / 空行 / 非 object / 未知 field / schema 違反 /
  偽造・失効 id / 非 canonical 行 / 終端改行の無い最終行 / 非 UTF-8 は
  `PredictionJournalCorrupt`（行番号・理由コード付き）。黙って skip・dedup・修復・
  migration-on-read・mutation-on-read をしない。破損 journal から部分結果を返さない。
- **書き込み規律**: 親ディレクトリ作成 → `open("a", encoding="utf-8", newline="\n")` →
  1 行 1 write → `flush()` → `os.fsync()`。既存 store（identity_ledger / normalization /
  raw_store）と同じ最小規律。hash chain / transaction / lock service を持ち込まない（N-3）。
- **SINGLE WRITER**: 同時書き込みの直列化は未対応。開いてから（または最後の append から）
  journal の byte 長が変わっていれば append 前に `ConcurrentModificationDetected` で
  fail closed する（検知であって排他ではない）。runtime 同時実行は別の認可 gate。
- **point-in-time**: 追記後の行は渡した PredictionRecord そのもの。後の provenance 変更は
  行を更新しない。新 schema 版は自身の contract で新しい行を追記する。
  「最新が勝つ」「1 日 1 行」を持たない。LIVE / REPLAY・同一 session の複数予測は共存する。

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

---

## 13. P5-1 完了検証（P5-1D）

P5-1A（PredictionRecord）・P5-1B（PredictionStore）・P5-1C（prediction_ingest）を 1 つの系として
OFFLINE で検証した（`tests/intelligence/test_prediction_journal_e2e.py`。隔離 root のみ、
P4 自身の凍結 builder で作った合成オブジェクトのみ、実データ・network・Windows 作業なし）。

| 検証項目 | 結果 |
|---|---|
| E2E 経路 | 凍結 P4 意味論（MorningBrief ＋ MarketSignal ＋ CompassDraft ＋ EvidencePackage）→ `ingest_prediction` → PredictionRecord → `PredictionStore.append` → `predictions.jsonl` → **新しい store による権威 reload** → 元と同一の PredictionRecord（prediction_id・provenance・audit すべて一致、journal bytes は canonical のまま） |
| state coverage | available 方向・available NEUTRAL_RANGE・unavailable（direction_mixed / draft_abstained）× LIVE / REPLAY の 8 通りが再起動後も同じ state のまま。NEUTRAL_RANGE は available、unavailable は unavailable、`unavailable_reason` と P4 由来の confidence / horizon が保存される。8 通りの id はすべて相異なる |
| 複数記録 / 再起動 | 3 session・同一 session の別意味論・REPLAY を含む journal が、再起動後も物理順・件数・`get` の一致を保ち、date-based overwrite が起きない。in-memory state を捨て JSONL だけから再構築した後、正確な再投入は `ALREADY_PRESENT`、新規は `APPENDED` |
| 冪等性 | 同じ source object ＋ 同じ origin ＋ 同じ audit / provenance を **ingestion 境界から** 再投入 → `ALREADY_PRESENT`、bytes 不変（再起動後も同じ） |
| conflict の fail closed | 同じ prediction_id で provenance（別 projection → brief_id / signal_id）または audit（recorded_at / cutoff / outlook_rule_version）が異なる再投入 → `PredictionConflict`。bytes 不変・権威 reload 成功・元の記録無傷・2 行目なし |
| 破損の fail closed | 正常 journal の隔離コピーに対し、不正 JSON / 終端切れ / 偽造 id / 物理重複（同一・矛盾）/ 非 canonical 行 → 新しい store は `PredictionJournalCorrupt`。修復・skip・部分 load なし |
| single-writer 境界 | 別 writer が追記した後の古い index からの append は `ConcurrentModificationDetected`。lock は追加していない。**P5-1 は SINGLE WRITER のまま**であり、runtime での直列化は後続 gate |
| point-in-time | reload 後の `recorded_at == CompassDraft.generated_at`、`cutoff == EvidencePackage.cutoff`、principle_refs / market_principle_version / outlook_rule_version / 4 つの id が source と一致。検証実行時刻は identity にも保存 audit にも入らない |
| 依存独立 | P5-1 三 module の runtime import closure は 13 module（`compass.model` / `core.ids` / `core.time` / `reports.model` / `reports.market_signal` / `predictions.*`）のみ。J-Quants / network / market store / TOPIX / 取引カレンダー / `topix_neutral_band` / EvaluationRecord / 較正 / Pages・公開 renderer / 通知 / git / legacy `investment_journal` に到達しない。P4 本番 entrypoint の closure に `predictions` は現れない（`EXCLUDED_PACKAGES`） |

完了監査（読み取りのみ）: PredictionRecord の field / state 規則、PredictionStore の等価 / conflict
規則、prediction_ingest の source 対応、本書 §5 / §5.1 / §5.2 / §8 / §8.1 の間に矛盾は無い。
§7「rerun: prediction_id 既知なら冪等」は §8.1「canonical 行の完全一致で冪等、差があれば
conflict」により精密化されており矛盾しない。§3「CompassDraft を予測の権威として読まない」は
P5-1C が draft を audit metadata（generated_at / outlook.rule_version）と整合検査にのみ使い、
予測意味論は MarketSignal からだけ写すことで満たされている。P4 の `outlook_horizon` は
config.yaml に override が無く既定 `next_tokyo_session` であり、`KNOWN_HORIZONS` と一致する。
outcome / 評価との結合は無い。

**P5-1 status: CLOSED / FROZEN（監督者受理待ち）。** P5-2 以降は着手していない。

---

## 14. P5-2A EvaluationRecord schema ＋ outcome contract（`evaluation_record.py`）

N-1〜N-6 を変えない。P5-2A が凍結したのは**評価 object だけ**であり、store（P5-2B）・TOPIX /
カレンダー参照・return 計算・自動評価・較正・正誤判定は含まない。

- **目的**: PredictionRecord は「予測時に系が何と言ったか」、EvaluationRecord は「その不変の予測に
  ついて、検証済み outcome / 証拠 context のもとで後からなされた評価」。outcome が届いても
  PredictionRecord は変更せず、可変の評価 field を付けない。`prediction_id` で参照し複製しない。
- **target / horizon（N-4 / N-5）**: TOPIX（`index:topix.close.closing.tokyo`）のみ。
  `reference_session` の close → `session_date` の close の 1 検証済み東京取引 session
  close-to-close。open-to-close・intraday・翌々 session・暦日・weekday 演算は表現しない。
- **realized_return（N-2）**: `close(session_date) / close(reference_session) − 1` を Decimal で
  保持（float 不可・分類前に丸めない・連続値を必ず保存）。canonical 直列化は context 非依存で
  末尾ゼロだけを落とした指数なしの平文十進（`0.0100`→`0.01`、`-0`→`0`、`1E-7`→`0.0000001`、
  NaN / Infinity 拒否、桁を落とさない）。`from_dict` は非 canonical 文字列を拒否する。
- **分類 `topix_neutral_band:1.0.0`**: `UP: r > +0.003` / `RANGE: −0.003 <= r <= +0.003`（閉区間）/
  `DOWN: r < −0.003`。比較は Decimal。**N-2 の表で `NEUTRAL_RANGE` と書かれた realized の区分は
  記録上 `RANGE` で表す**（予測 level の `NEUTRAL_RANGE` と語彙を分けるため。境界・意味は不変）。
  予測 level（5 値）と realized outcome（3 値）は別概念であり、正誤 / hit / miss / accuracy /
  score / direction_correct は本 record に存在しない（後続の較正 gate が定義する）。
- **status**: `EVALUATED`（検証済み証拠が揃い、連続 return ＋ 分類を表現できる）/ `DEFERRED`
  （予測は存在するが権威ある評価を現時点で完了できない）。DEFERRED は RANGE でも不正解でも
  零 return でも「予測が unavailable」でもない。deferred を黙って除外しない。
  EVALUATED: realized_return・realized_outcome・reference_close・target_close・
  session_verification 必須、defer_reason 無し、outcome は return の分類と一致。
  DEFERRED: return / outcome 無し、defer_reason 必須。矛盾は fail closed。
- **defer_reason（6 値・snake_case）**: `calendar_unverified` / `reference_session_unverified`
  （N-5 の (a)(b) を立証できない）/ `reference_close_unavailable` / `target_close_unavailable` /
  `observation_invalid` / `source_unsupported`。
- **予測 availability と outcome evaluability は別**: unavailable な予測も TOPIX の outcome を
  持ちうる。棄権を理由に DEFERRED にせず、棄権の正誤も決めない（`available` を複製しない）。
- **session 検証の証拠（§10 / §11-1）**: `SessionVerification`（既存 `CalendarValidation` と同じ
  実測検証の要約: `calendar_source_id` / `trading_divisions` / `checked_dates` / `agreements` /
  `disagreement_count` ＋ `verified_session` / `verified_previous_session`）。EVALUATED では
  `validated`（checked > 0・食い違い 0）かつ `verified_session == session_date` かつ
  `verified_previous_session == reference_session` を要求。schema は `reference_session <
  session_date` のみを見て、隣接性はこの証拠で担保する。
- **provenance / audit**: `reference_close` / `target_close`（Decimal canonical）/
  `reference_observation_id` / `target_observation_id`（market `Observation.observation_id`）/
  `source_id` / `market_schema_version` / `session_verification`。`created_at` は評価時刻の
  audit metadata で identity に入らない（呼び出し側が明示。module は現在時刻を読まない）。
  顧客表示文字列・PredictionRecord の複製・巨大な evidence blob は持たない。
- **identity（field 分類）**:

  | 分類 | field |
  |---|---|
  | A. identity 入力（hash に含める） | `schema_version`（`evaluation_record:0.1.0`）、`prediction_id`、`target`、`reference_session`、`session_date`、`classification_version`、`status`、`realized_return`（canonical）、`realized_outcome`、`defer_reason`、`supersedes_evaluation_id` |
  | B. provenance（hash 外） | `reference_close`、`target_close`、`reference_observation_id`、`target_observation_id`、`source_id`、`market_schema_version`、`session_verification` |
  | C. audit（hash 外） | `created_at` |
  | D. 導出（保存しない） | identity payload、canonical 文字列、`is_deferred`、`is_correction` |
  | E. 存在しない | hit / miss / correct / accuracy / score / win / loss / direction_correct、予測 level・confidence・available・origin の複製、label / display_text / delivery_id / Markdown / HTML / path |

  `evaluation_id = "eval_" + SHA-256(A の 11 key を昇順・compact・UTF-8 で直列化)[:24]`
  （`core.ids.content_id`。新しい hash chain ではない ＝ N-3）。`created_at` や provenance を
  変えても同じ id、意味論のどれか 1 つを変えれば別 id。同値の Decimal 表現（`0.01` / `0.0100`）
  は同じ id。LIVE / REPLAY は `prediction_id` が既に区別するため第二の origin を持たない。
- **訂正 / supersession（§7）**: 歴史的 EvaluationRecord は書き換えない。市場データの訂正は
  `supersedes_evaluation_id` で前の評価を参照する**新しい** EvaluationRecord（新しい id）で表す。
  原評価は supersedes 無し。`supersedes_evaluation_id` は identity に含める（同じ数値へ再評価
  されても訂正は必ず新しい id を得る。参照は `Observation.revision_of` と同じ provenance link）。
  自己 supersession・不正な id 形式は拒否。「最新が勝つ」の判定と chain 走査は store /
  analytics（後続 gate）に属し、record model には無い。
- **3 つの版概念**: `prediction_record:0.1.0`（予測 record schema）/ `evaluation_record:0.1.0`
  （評価 record schema）/ `topix_neutral_band:1.0.0`（realized outcome 分類規則）は別物。
- **依存境界**: import は `core.ids` / `core.time` / `prediction_record`（`PREDICTION_ID_PREFIX`
  のみ）と stdlib。market store / TOPIX 取得 / tokyo_calendar / J-Quants / PredictionStore /
  較正 / P4 pipeline / 公開 renderer / 通知 / legacy journal を参照しない。network も
  filesystem 書き込みも無い。

---

## 15. P5-2B 追記専用 evaluation journal / store（`evaluation_store.py`）

N-1〜N-6・§14（EvaluationRecord）を変えない。P5-2B は**永続化層だけ**であり、評価 engine・
PredictionRecord → EvaluationRecord の自動化・TOPIX / カレンダー / J-Quants 参照・return 計算・
較正・「現在の評価」の解決・runtime 統合は含まない。

- **`evaluations.jsonl` が唯一の権威。** `<data_root>/predictions/evaluations.jsonl`。
  predictions.jsonl（PredictionStore）とは**別の**追記専用の権威で、EvaluationStore は
  predictions.jsonl を開かず、PredictionStore を import せず、PredictionRecord を変更も補強も
  しない（参照は `prediction_id` のみ。参照先の存在確認は後続の評価 engine / E2E 境界の責務）。
- **data_root は呼び出し側が明示**（既定・環境変数・config・production / research root への
  fallback なし）。読むだけではディレクトリもファイルも作らない。
- **append / 冪等 / conflict**（P5-1B §8.1 と同じ規律）: 未知 `evaluation_id` → 1 行追記
  `APPENDED` / 既知 id ＋ canonical 行 byte 一致 → `ALREADY_PRESENT`（書かない）/ 既知 id ＋
  いずれかの field 差（provenance・created_at・observation id・closes・session 検証を含む）→
  `EvaluationConflict`（fail closed。merge・更新・DEFERRED の EVALUATED への書き換え・
  2 行目追記なし）。同じ id だけでは冪等の十分条件ではない。
- **supersession は append であって update ではない。** 訂正 record は
  `supersedes_evaluation_id` を持つ新しい物理行として追記され、前の行は物理的にも論理的にも
  変更されない（inactive mark・可変 status なし）。数値・outcome・closes・status の変化は
  要求しない（同じ数値への訂正も正当な履歴）。DEFERRED → EVALUATED / EVALUATED → EVALUATED /
  DEFERRED → DEFERRED の履歴を許す。
- **前任存在規則**: append 時・権威 load 時ともに、前任 record が**同じ journal に物理的に先行して
  存在**しなければならない（dangling / forward reference は `SupersessionRejected` /
  `DANGLING_SUPERSESSION`）。後方参照しか許さないため cycle は成立しない。
- **同一 subject 規則**: 前任と `prediction_id` / `target` / `reference_session` /
  `session_date` / `classification_version` が一致しなければならない
  （`INCOMPATIBLE_SUPERSESSION`）。supersession を汎用 link にしない。
- **物理順が歴史**: `iter_records()` は物理行順。session / created_at / id で並べ替えず、
  latest / current / resolve / evaluated_only / by_outcome の API を持たない。
- **journal 直列化**: `EvaluationRecord.as_dict()` を key 昇順・compact・UTF-8・`\n` 終端の
  1 行に。Decimal は §14 の canonical 表現のまま（再丸め・再分類・outcome 再計算をしない）。
  権威 load は `EvaluationRecord.from_dict()` を通る。
- **load の fail closed**（理由コード 11 種）: 非 UTF-8 / 終端切れ / 空行 / 不正 JSON / 非 object /
  schema 違反・偽造 id・未知 field / 非 canonical 行 / 物理重複（同一・矛盾）/ dangling
  supersession / subject 不一致 supersession → `EvaluationJournalCorrupt`。skip・修復・dedup・
  reorder・migration-on-read・部分 load なし。
- **書き込み規律**: 初回 append でのみ親 dir 作成 → `open("a", newline="\n")` → 1 write →
  `flush` → `fsync`。truncate / replace / rename / unlink / repository commit / hash chain /
  transaction なし。
- **SINGLE WRITER**: 外部要因で journal の byte 長が変わっていれば append 前に
  `ConcurrentModificationDetected` で fail closed（検知であり排他ではない）。`reload()` で
  権威から再構築。runtime での直列化は後続 gate。

