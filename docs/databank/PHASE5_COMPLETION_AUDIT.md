# PHASE 5 COMPLETION AUDIT（Prediction Journal・closeout 監査）

本書は Phase 5（Prediction Journal）の**完了監査**の正本である。入口契約は
`PHASE5_ENTRY_CONTRACT.md`（N-1〜N-6 と各 gate の確定事項）、実装は
`src/intelligence/predictions/`、証拠は `tests/intelligence/test_prediction_*` /
`test_evaluation_*` / `test_calibration_*` / `test_phase5_chain_e2e.py`。本書は読み取り監査の
記録であり、実装・意味論を変更しない。監査日 2026-09-19。

## 1. 最終判定

**PHASE_5_COMPLETION_AUDIT_PASS_WITH_NON_BLOCKING_DEFERRED_ITEMS**
**PHASE_5_COMPLETE_READY_FOR_SUPERVISOR_FREEZE**

Phase 5 の凍結 claim（§2 の 12 項目）はすべて offline テストで証明されている。BLOCKER は無い。
残るのは N-6 が意図的に後続 gate へ送った運用項目（§18）だけであり、Phase 5 完了の要件ではない。

## 2. scope

| 区分 | 内容 |
|---|---|
| 監査対象 | P5-1（PredictionRecord / PredictionStore / prediction_ingest / P5-1D）、P5-2（EvaluationRecord / EvaluationStore / evaluation_engine / P5-2D）、P5-3（calibration_contract / calibration_analyzer / P5-3C）、Entry Contract §0〜§21 |
| 証明された claim | ①点時刻の予測を記録 ②予測履歴を追記専用で保存 ③後から TOPIX の realized outcome 証拠を付ける ④DEFERRED / 評価なしを保存 ⑤訂正を supersession で保存 ⑥旧評価を上書きせず保持 ⑦「最新が勝つ」に依らず active evaluation を分析的に解決 ⑧歴史的較正 metric を計算 ⑨棄権と採点対象を分離 ⑩LIVE と REPLAY を分離 ⑪欠測 / unresolved / 小標本の限界を露出 ⑫凍結 record から較正を決定論的に再現 |
| 対象外 | 新機能・runtime 統合・persistence 追加・実 journal 実行・較正 feedback・閾値 / confidence 調整・Phase 6 |

## 3. freeze anchors

| 対象 | anchor | 本監査時の diff |
|---|---|---|
| Phase 4 production baseline（main） | `15739707147f06aa9a2b04bbefa50fa78df6532f` | 0（predictions package 以外） |
| P5-1 | `6c281512c6b8954520d6fb17e27e1831e47b0552` | 0 |
| P5-2 | `40e0e03649dd277da9b8812061a3d2b14b1de2bd` | 0 |
| P5-3A | `7c04e77cd81e3252b533342d11349c4700986f79` | 0 |
| P5-3B | `bef71f0e96a410d5b2b7f274111544a173c1db63` | 0（`__init__.py` docstring の stale 1 行のみ本 gate で更新） |
| P5-3C / P5-3 | `7ea12268558d6a660414c141768e7f7435f43774` | 0 |
| 歴史 branch（Phase 0〜4） | `claude/investment-intelligence-phase0-rvdplu` = `247b85b` | 不変 |

## 4. N-1〜N-6 監査

| 決定 | 検証 | 結果 |
|---|---|---|
| N-1 identity | `IDENTITY_KEYS` は 9 key（available / confidence / horizon / level / origin / reference_session / schema_version / session_date / unavailable_reason）。brief_id / signal_id / package_id / draft_id / recorded_at / cutoff は payload 外 | PASS |
| N-2 classification | `NEUTRAL_BAND = 0.003`、`topix_neutral_band:1.0.0`、`+0.003 → RANGE`・`+0.0030000001 → UP`・`−0.003 → RANGE`・`−0.0030000001 → DOWN`（閉区間）、return は `prec 28 / ROUND_HALF_EVEN` の Decimal で分類前に丸めない、連続値を record に保存 | PASS |
| N-3 integrity | predictions package に prev_hash / chain / decisions.jsonl 結合なし。id は `core.ids.content_id` の content-address のみ | PASS |
| N-4 target | `TARGET_TOPIX = index:topix.close.closing.tokyo`、`SUPPORTED_SOURCE_IDS = ("jquants",)`。P4 production diff 0 | PASS |
| N-5 horizon | engine / record の実行 source に weekday / timedelta / today / now なし。`SessionVerification` は実測カレンダー検証（`validate_divisions` / `trading_days`）を写し、`verified_previous_session == reference_session` を要求。検証不能は `calendar_unverified` / `reference_session_unverified` で DEFER | PASS |
| N-6 runtime / persistence | 純粋 module（record / store / ingest / engine / contract / analyzer）に network / git / environ / `/v2` / pages / delivery 参照なし。journal は `.gitignore` 済み `data/vnext/` 既定で repo に 1 行も追跡されない。P4 production closure は predictions に到達しない | PASS |

補足: 研究 driver `topix_research_acquire.py`（A0.7、J-Quants v2 の 2 endpoint）と測定 runner
`topix_neutral_band_measure.py`（A0.5R、network module 非使用の guard 付き）は N-2 の根拠取得用で
あり、Phase 5 の journal / 評価 / 較正経路には含まれない。

## 5. P5-1 監査（PredictionRecord / PredictionStore / prediction_ingest / P5-1D）

不変 record（frozen dataclass）、identity / provenance / audit の分離（§4 N-1）、NEUTRAL_RANGE は
available（棄権ではない）、unavailable は棄権のまま journal、追記専用 JSONL、canonical 行の byte
一致による厳密冪等（`ALREADY_PRESENT`）、差分は `PredictionConflict`、破損 9 理由は
`PredictionJournalCorrupt`（修復 / skip / 部分 load なし）、`ConcurrentModificationDetected` による
SINGLE WRITER 境界（検知であり排他ではない）、`recorded_at = CompassDraft.generated_at` /
`cutoff = EvidencePackage.cutoff` の点時刻、LIVE / REPLAY の identity 分離、runtime closure 13 module
（market / calendar / evaluation / calibration / network に到達しない）、P4 production entrypoint との
非結合。P5-1D E2E（28 tests）が P4 object → ingest → journal → 権威 reload → 同一 record を証明。
**status: CLOSED / FROZEN。**

## 6. P5-2 監査（EvaluationRecord / EvaluationStore / evaluation_engine / P5-2D）

別の不変 history、TOPIX target のみ、Decimal return、凍結分類、EVALUATED / DEFERRED の分離
（6 defer 理由・凍結優先順位 source_unsupported → calendar_unverified →
reference_session_unverified → observation_invalid → reference_close_unavailable →
target_close_unavailable）、実測カレンダー検証・weekday フォールバックなし、`trading_date` 完全一致の
観測のみ（nearest / fill / 補間なし）、supersession による訂正（append・前任の物理先行・同一 subject）、
「最新 / 現在」API の不在、unavailable 予測も市場 outcome を持てる（engine は `available` を
読まない）、PredictionRecord 不変、SINGLE WRITER 境界、engine に hit / miss / 写像 / 較正なし。
runtime closure 18 module（prediction_store / prediction_ingest / calibration_* を含まない）。
P5-2D E2E（38 tests）が予測 → 証拠 → engine → journal → reload → 訂正 chain を証明。
**status: CLOSED / FROZEN。**

## 7. P5-3 監査（calibration_contract / calibration_analyzer / P5-3C）

観測的 analytics のみ（authority ではない）、`prediction_direction_mapping:1.0.0`（P4
`LEVEL_BY_STATE` 方向成分の逆射影）、supersession graph resolver
`active_evaluation_resolver:1.0.0`（created_at / 物理順で選ばない。fork / 独立 terminal / dangling /
subject 不一致 / 同 id 別内容 / cycle は UNRESOLVED）、AVAILABLE のみの方向 exact match、棄権診断の
分離、DEFERRED / NO_EVALUATION / UNRESOLVED の分離、LIVE / REPLAY 分離（COMBINED なし）、5×3 行列の
保存、confidence 集計は AVAILABLE のみ、連続 return（Decimal）の保存、`sample_disclosure:1.0.0`、
`Denominator` による分母の明示、空 cohort 有効、重複入力 fail closed、決定論的 lineage / 直列化
（float なし）、market / calendar / API / store 非依存（closure 14 module）、入力不変。
P5-3C E2E（41 tests）が代表世界（LIVE 18 / REPLAY 3 / 期間外 2 / 評価 28）で report の明示期待値・
再構築同値・訂正・DEFERRED→EVALUATED・unresolved・棄権・分割・disclosure 境界を証明。
**status: CLOSED / FROZEN。**

## 8. cross-phase chain

```
P4 凍結 object（MorningBrief ＋ MarketSignal ＋ CompassDraft ＋ EvidencePackage）
  → PredictionRecord → predictions.jsonl → 権威 reload            … P5-1D E2E が直接証明
  → EvaluationRecord → evaluations.jsonl → 権威 reload・訂正 chain … P5-2D E2E が直接証明
  → CalibrationReport（決定論・再構築同値）                          … P5-3C E2E が直接証明
  → 上記全 link を 1 本の隔離 root で合成                            … test_phase5_chain_e2e.py が直接証明
```

A. **schema / logic / E2E の合成的完全性: 完了。** 各 link は個別 E2E で直接、全体は closeout の
chain test（P4 object 4 種 → 両 journal → 訂正 1 件 → 両 store の権威 reload → analyzer →
in-memory record からの report と一致・journal bytes 不変・LIVE / REPLAY 非 pool）で直接証明した。

B. **production runtime 統合: 意図的に未着手（N-6）。** 単一の production runtime がこの chain 全体を
実行している事実は**無い**。P4 `delivery_pilot.main()` は PredictionRecord を作らず、評価 scheduler も
存在しない。A と B を混同しないこと。

## 9. persistence model

| 項目 | 状態 |
|---|---|
| 権威 | `<data_root>/predictions/predictions.jsonl` と `<data_root>/predictions/evaluations.jsonl`。別 authority（EvaluationStore は predictions.jsonl を開かない） |
| 追記専用 / 破損 | append のみ（truncate / replace / rename / unlink なし）。破損は fail closed、自動修復・skip・dedup・migration-on-read なし |
| repo persistence | 無し（`data/vnext/` は `.gitignore`。追跡 jsonl / pdf 0 件）。production root / research root への fallback なし（data_root は明示必須） |
| writer | SINGLE WRITER。lock / multi-writer 保証は無い（byte 長変化の検知のみ） |
| 較正 | store / persistence **無し**。CalibrationReport は凍結 record から再構築可能な導出物 |
| index | SQLite 導出 index は未作成（§8 layout の任意項目。必要になれば再構築可能な導出物として別 gate） |

## 10. correction / history model（核心不変条件）

PredictionRecord 不変・EvaluationRecord 不変・訂正 = `supersedes_evaluation_id` を持つ新 record の
append・旧評価は保持・較正は凍結 graph 意味論で terminal active を解決・fork / 曖昧は UNRESOLVED
（推測しない）・訂正後に派生 metric と `active_evaluation_digest` は変わるが歴史 journal と
`cohort_digest` は変わらない。P5-2D（A→B→C の byte 不変）と P5-3C / chain test（訂正前後の report
差分と journal bytes 不変）で証明済み。

## 11. abstention model

`PredictionRecord.available == false` = 棄権。RANGE / wrong / zero-return / DEFERRED の
いずれにも変換されない（P5-1 状態機械、engine は `available` を読まない、`prediction_cohorts` は
ALL / AVAILABLE / ABSTAINED を分ける）。P5-2 は棄権予測にも市場 outcome を付けられる。P5-3 は
方向 exact match から除外し、棄権診断（件数・棄権率・active EVALUATED の outcome / return）に含める。
confidence を保持した棄権（direction_mixed / direction_uncertain）も confidence bucket に入らない。
コード・Entry Contract §6 / §14 / §16 / §18 / §19 に矛盾する記述は無い。

## 12. coverage / missingness model

直交する 3 概念を別 enum で保持し、畳む箇所は無い:
予測 availability（AVAILABLE / ABSTAINED = `PredictionCohort`）、評価 coverage（ACTIVE_EVALUATED /
ACTIVE_DEFERRED / NO_EVALUATION / UNRESOLVED = `EvaluationCoverage`）、realized outcome（UP / RANGE /
DOWN = `RealizedOutcome`）。`classify_realized_return` は availability を参照せず、`CoverageCounts` は
4 bucket の分割を検証し、report は 26 group すべてで分割を保つ（P5-3C）。

## 13. version inventory（権威）

| 版 | 値 | 定義位置 |
|---|---|---|
| prediction_record | `prediction_record:0.1.0` | `prediction_record.py` |
| evaluation_record | `evaluation_record:0.1.0` | `evaluation_record.py` |
| topix_neutral_band（分類） | `topix_neutral_band:1.0.0` | `evaluation_record.py`（N-2） |
| calibration_contract | `calibration_contract:0.1.0` | `calibration_contract.py` |
| prediction_direction_mapping | `prediction_direction_mapping:1.0.0` | `calibration_contract.py` |
| active_evaluation_resolver | `active_evaluation_resolver:1.0.0` | `calibration_contract.py` |
| sample_disclosure | `sample_disclosure:1.0.0` | `calibration_contract.py` |
| calibration_report | `calibration_report:0.1.0` | `calibration_analyzer.py` |
| P4 source（消費） | MorningBrief `0.2.0`、MarketSignal `0.1.0`、market `Observation` `0.4.0`（`core.types.SCHEMA_VERSION`）、TOPIX `source_id = jquants`、カレンダー J-Quants `/markets/calendar`（HolDiv `"1"`） | `prediction_record.py` / `evaluation_engine.py` |
| 研究（N-2 根拠。journal 経路外） | `topix_research_acquisition:0.1.0`、`topix_neutral_band_measurement:0.1.0` | 研究 driver / runner |

code・tests・Entry Contract・`CalibrationReport.as_dict()["versions"]` / lineage で一致。
`evaluation_record:0.0.9` / `evaluation_record:0.2.0` / `prediction_record:0.2.0` /
`topix_neutral_band:1.1.0` / `topix_neutral_band:2.0.0` は tests 内の**否定例**（未対応版の拒否・
identity 感度）としてのみ現れ、src / docs には存在しない。

## 14. dependency boundaries

| 層 | runtime import closure | 到達しないもの |
|---|---|---|
| P5-1 | 13 module（compass.model / core.ids / core.time / reports.model / reports.market_signal / predictions.prediction_*） | market / calendar / evaluation_* / calibration_* / network |
| P5-2 | 18 module（＋ core.types / market.model / market.tokyo_calendar / prediction_record） | prediction_store / prediction_ingest / calibration_* / network |
| P5-3 | 14 module（＋ evaluation_record / prediction_record） | evaluation_engine / prediction_ingest / stores / market.model / tokyo_calendar / network / filesystem |

逆依存なし: P4（predictions 外の src / scripts）→ predictions 参照 0、P5-1 → P5-2 / P5-3 import 0、
P5-2 → P5-3 import 0。P4 production closure（135 module）に predictions は現れず
（`EXCLUDED_PACKAGES`）、`MORNING_DELIVERY_SPEC.md` §14 の「predictions import ゼロ」と一致。

## 15. security / confidentiality

guard 通過（confidential guard 5 / production bundle 27 / public unavailable vocabulary 17 /
customer display vocabulary 24）。Compass PDF・journal（jsonl）の追跡 0 件。secret / API key の追加
なし（研究 driver は runtime injection の環境変数のみ、値は log / 例外 / 保存 payload に出さない）。
Phase 5 code / tests / docs に machine-specific path なし。公開 `/v2`・Pages・root cutover・
workflow / Actions・顧客出力の変更 0（diff 0）。歴史的 H0 security issue は本 gate の対象外（別 track）。

## 16. production non-regression

`git diff 15739707 -- src scripts .github config.yaml knowledge docs/v2 ':(exclude)src/intelligence/predictions'` = 0。
Phase 5 の footprint は `src/intelligence/predictions/`・`tests/intelligence/test_{prediction,evaluation,calibration,phase5_chain,topix_*}*.py`・
`docs/databank/PHASE5_*.md`・`CHANGELOG.md` のみ。顧客向け出力・`output/`・notifiers・cloudflare に変更なし。

## 17. real-data status

**MACHINERY VALIDATED — REAL LIVE HISTORY NOT ACCUMULATED.**

- 本 repo / branch に実 PredictionRecord journal・実 EvaluationRecord journal は存在せず、Phase 5 の
  どの gate も実 journal を作成・読取していない（全テストは `tmp_path` の隔離 root）。
- production は現在 PredictionRecord を自動 capture して**いない**（`delivery_pilot` は P5 を呼ばない）。
- production の評価は自動実行されて**いない**（scheduler 未実装）。
- 現在の CalibrationReport は実運用成績を**表さない**（fixture 上の機構検証のみ）。
- 2026-09-17 までの TOPIX 研究取得（1,223 観測・隔離 research root）は N-2 の閾値凍結のためであり、
  Phase 5 の production 評価 journal ではない。

## 18. deferred items（非 blocker）

| # | 項目 | 分類 |
|---|---|---|
| 1 | production / runtime での PredictionRecord capture（`delivery_pilot` in-process 境界への adapter 接続。別認可 gate） | Phase 5 operationalization |
| 2 | runtime での直列化 / single-writer orchestration（lock・queue） | Phase 5 operationalization |
| 3 | 後続評価の自動 scheduling（東京 close 後の評価 cutoff の運用適用、カレンダー / TOPIX 証拠の供給。Entry Contract §7 の `known_at` は frozen `Observation.as_of` に対応し、engine は clock を持たないため cutoff は scheduler の責務） | Phase 5 operationalization |
| 4 | J-Quants capability の live 再確認（§10。P5-2 gate は API 呼出不可のため未実施。最新の live 証拠は 2026-09-17 の A0.7 取得） | Phase 5 operationalization |
| 5 | 実 prediction / evaluation history の蓄積 | Phase 5 operationalization（時間依存） |
| 6 | 較正 persistence / snapshot（必要になった場合のみ。現状は再構築可能な導出物） | 後続 Phase（任意） |
| 7 | 内部向け較正 presentation / UI（INTERNAL ONLY） | 後続 Phase |
| 8 | 較正 → Compass DNA / 閾値 / confidence への feedback・再調整 | Entry Contract が禁止。監督者の設計決定が無い限り行わない（後続 Phase の設計事項） |
| 9 | SQLite 導出 index（§8 layout の任意項目） | 後続（必要時） |
| 10 | P4 通知 / root cutover（P11-3・P4-3b bridge） | 別 P4 track |
| 11 | 歴史的 H0 security 是正 | 別 security / ops track |

いずれも N-6（offline-first）が意図的に後続へ送った項目であり、Phase 5 の凍結 claim を偽にしない。

## 19. test / guard 結果（2026-09-19）

| 対象 | 件数 |
|---|---|
| P5-1: test_prediction_record / store / ingest / journal_e2e | 145 / 60 / 74 / 28 |
| P5-2: test_evaluation_record / store / engine / e2e | 162 / 53 / 57 / 38 |
| P5-3: test_calibration_contract / analyzer / e2e | 48 / 35 / 41 |
| closeout: test_phase5_chain_e2e | 2 |
| 研究: test_topix_research_acquire / neutral_band_measure | 37 / 26 |
| guards: confidential / production bundle / public unavailable vocab / customer display vocab | 5 / 27 / 17 / 24 |
| **全 suite** | **1330 passed** |

## 20. final blockers

無し。§26 の blocker 条件（履歴の可変・訂正による上書き・未検証 session での outcome 生成・曖昧 active の
推測・棄権の採点・LIVE / REPLAY の既定 pool・較正の market / API 依存・契約と実装の矛盾・P4 変更・
security / 顧客データ露出）はいずれも該当しない。

## 21. next authorized phase

**PHASE 6 — THEME**（監督者が別途 Phase 6 Entry Contract / design gate を発行するまで実装しない）。
