# CHANGELOG

このファイルは `CLAUDE.md` の運用プロトコルに従い、`## vX.Y` 形式で
「追加／改善／修正」を追記していく。本ファイルの記録は今回の更新から開始する
（それ以前の機能一覧・構成は `README.md` を参照）。

## v4.36 (2026-09-02) — Phase 3.6: J-Quants Production Data Strategy

J-Quants Light を pilot data source から **production-grade incremental market data source** へ
昇格させる運用設計。新しい分析機能は追加しない。**J-Quants First** を project-wide rule として
導入（CLAUDE.md / `docs/databank/JQUANTS_FIRST_RULE.md`）。Standard / Premium endpoint を迂回せず、
plan upgrade を自動実施せず、canonical は append-only（rolling ≠ 削除）。

### 追加

- `src/intelligence/jquants_ops/`【新規】（1機能=1ファイル）:
  - `registry.py`: capability registry（dataset / endpoint / plan / entitlement / strategy /
    frequency class / publication semantics / historical depth / pagination / request pattern /
    canonical store / consumers / morning role / fallback / last_live_verified_at。
    P2-H run #1/#3・Phase 3.5 run #20 の live evidence に基づく。既知の 403 は再 probe しない）。
  - `capability_gate.py`: J-Quants First gate（CURRENT_PLAN_SUPPORTED / CURRENT_PLAN_UNSUPPORTED /
    ALREADY_AVAILABLE / NEEDS_NEW_ENDPOINT / PLAN_UPGRADE_CANDIDATE / DEFER）＋既存 Phase の監査。
  - `plan_upgrade_register.py`: NOT_ENTITLED dataset の用途・必要プラン・優先度・回避策・価値
    （markets_short_ratio のみ P2 候補。他は LIGHT_SUFFICIENT / NOT_NEEDED）。
  - `morning_contract.py`: 朝の cutoff 時点で dataset ごとに「前営業日／公表済み週／snapshot／公表済み予定」
    のどれであるべきかを明示。
  - `rolling_window.py`: seed 70 / active 60 / buffer 10 / max window 25 を分離。
    25 ちょうどの設計を validate で拒否。retention は append-only。
  - `session_gap.py`: CURRENT / MISSING_SESSION / PARTIAL_SESSION / STALE / FUTURE_DATA / CALENDAR_UNKNOWN。
  - `incremental.py`: gap → plan（NOOP / DAILY / REPAIR / SEED / BLOCKED）→ 欠落だけ取得（bounded retry）
    → 冪等 append → affected rolling metrics only 再計算。
  - `master_refresh.py`: date 指定 snapshot（週1回＋イベント時）・diff（added / removed / market /
    S17 / S33 / ScaleCat）・KNOWN_LIMITATION_HISTORICAL_UNIVERSE。
  - `corporate_actions.py` / `weekly_flow.py` / `financial_summary.py` / `earnings_calendar.py` /
    `topix_strategy.py`: production contract（生終値判定・週次差分・event-driven fins・予定の revision・
    TOPIX 差分＋Nikkei alignment）。
  - `storage_budget.py` / `request_budget.py`: store 別の日次／月次／年次増分、scenario 別 request 数。
  - `failure_policy.py`: AUTH_FAILURE / NOT_ENTITLED / RATE_LIMIT / TIMEOUT / HTTP_ERROR /
    SCHEMA_CHANGE / EMPTY_RESPONSE / PARTIAL_DATA / SESSION_GAP、impact（CONTINUE / DEGRADED / ABSTAIN）、
    bounded retry（最大2試行・auth/entitlement/schema は retry しない）。
  - `schema_drift.py`: unknown field 追加と required field 欠落を区別。
  - `health.py` / `readiness.py`: dataset health snapshot と READY / READY_WITH_WARNINGS / DEGRADED /
    NOT_READY（required / internals / optional）。
  - `fifty_two_week.py`: 52週高値安値 = IMPLEMENT_LATER（daily incremental で蓄積。5年 backfill なし）。
  - `pilot.py`: isolated root で seed（意図的欠落）→ repair → daily → rerun → master diff →
    weekly flow → health / readiness → morning simulation を実測（`::P36_*::`）。
- `config.yaml`: `jquants_ops` セクション。`CLAUDE.md`: J-Quants First ルール。
- `docs/databank/JQUANTS_FIRST_RULE.md`【新規】、`docs/databank/JQUANTS_PRODUCTION_DATA_STRATEGY.md`【新規】。
- `.github/workflows/p2d-market-pilot.yml`: Phase 3.6 step 追加（JQUANTS_API_KEY のみ）。
- オフラインテスト 47 件追加（`tests/intelligence/test_jquants_ops.py`【新規】）。
- live evidence（p2d-market-pilot run #21、231.8 s）: seed 29 session / 40 request → repair
  （MISSING_SESSION 2 → REPAIR 2 request、gap CURRENT）→ daily（STALE 1 → DAILY 1 request、6.84 s）
  → rerun NOOP 0 request（idempotent）。master snapshot 8 本・diff 36 変更、fins date mode AVAILABLE、
  readiness READY_WITH_WARNINGS（earnings_cal MISSING）、morning simulation 4 朝 look-ahead 0、
  合計 45 request。詳細は `docs/databank/JQUANTS_PRODUCTION_DATA_STRATEGY.md` §11 / §14。

### 改善

- なし（既存モジュールは変更していない。3.5 の ingest / pipeline を再利用）。

### 修正

- なし。

## v4.35 (2026-09-02) — Phase 3.5: Japan Market Internals Foundation

日本株市場の「指数の値」だけでなく**市場内部で何が起きているか**（騰落銘柄数・売買代金・
業種／規模別の相対パフォーマンス・投資部門別フロー・指数の主導構造）を
Evidence-Grounded に観測可能にする層。Compass Generator（3-C）は大規模改修せず、
Evidence Package が internals Context を通常Contextとして受け取る最小接続に留めた。
因果説明をしない／週次を日次として語らない／Standard・Premium限定データを迂回しない／
全銘柄×5年backfillはしない（見積りのみ）。

### 追加

- `src/intelligence/internals/`【新規】（1機能=1ファイル）:
  - `types.py` / `config.py`: 統制語彙・次元・subject id・`config.yaml: market_internals`
    （universe / 価格変化定義 / 閾値をすべて version 付きで保持）。
  - `universe.py`: 東証プライム普通株 universe（`tse_prime_common:1.0.0`。Mkt=0111・
    5桁コード末尾0・業種未設定を除外）。session 以前で最新の master を使い、無ければ
    遡及適用を `master_applied_backwards` として明示（survivorship の LIMITATION）。
  - `price_movement.py`: **生終値 vs 前営業日生終値**。当日 AdjFactor≠1 または raw/adjusted
    の騰落率不一致は `corporate_action` として判定しない（誤方向を数えない）。
  - `breadth.py`: 騰落集計 ＋ **aggregation manifest**（manifest_id / input_count /
    input_set_hash / universe_version / calculation_version / input_record_ids）。
    数千件の入力を manifest から再構築できる。
  - `turnover.py` / `sector.py`（S17・等ウェイト・市場平均との差・leaders/laggards）/
    `size.py`（ScaleCat: TOPIX 100 / Mid400 / Small を source 定義のまま）/
    `breadth_history.py`（25日騰落レシオ＝Σ値上がり/Σ値下がり×100、5 vs 20 セッション trend）。
  - `investor_flow.py`: 週次 investor-types。published_date から known_at（publication gating）、
    primary_date = period_end。「本日は外国人が…」を書けない構造。
  - `facts.py` / `contexts.py` / `snapshot.py`: Phase 3-A Fact model・3-B Context model へ正規接続。
    `breadth_state` / `breadth_trend` / `turnover_state` / `sector_leadership` /
    `size_leadership` / `investor_flow_state` / `index_leadership`
    （NIKKEI_LED / TOPIX_LED × BROAD_CONFIRMATION / NARROW_LEADERSHIP）。
    Morning snapshot へ `internals_status`（AVAILABLE / MISSING / STALE /
    INSUFFICIENT_HISTORY / NOT_ENTITLED）。
  - `compass_claims.py`: 決定論的 generator への最小接続（FACTUAL 銘柄数 / RELATIONAL 上回った /
    INTERPRETIVE 広がり＝**JP_INT_001** 参照 / 売買代金 / 業種 / 規模 / 直近公表週の海外投資家）。
  - `adversarial.py`: 捏造銘柄数・逆方向・週次を日次・業種の因果・internals無しでの断定 → 必ずREJECT。
  - `store.py`（manifests / aggregates: JSONL append-only ＋ 再構築可能SQLite）、
    `ingest.py`（J-Quants Light **date指定** 1 session=1リクエスト。可否は実応答で判定し、
    使えなければ code指定 sample → LIMITED_USE）、`quality.py`、`backfill_estimate.py`、
    `pipeline.py`、`pilot.py`（`::P35_*::` marker）。
- Phase 3-C pre-flight（language safety）:
  - `compass/market_principles.py`【新規】: 経験則 registry（Compass DNA rule_id）。
    claim に `rule_ref / interpretation_type / market_principle_version` を構造化
    （Investment Interpretation を Fact から分離。FACTUAL は空）。
  - `compass/principle_validation.py`【新規】: `interpretation_without_principle`（warning）/
    `unknown_market_principle` / `principle_context_mismatch` / `factual_with_principle`。
  - `compass/confidence_validation.py`【新規】＋ `lexicon.OUTLOOK_PHRASES`:
    HIGH=見込まれる / MEDIUM=可能性がある / LOW=余地がある を機械的に固定し、
    食い違えば `confidence_language_mismatch`。
  - `language_rules`: `weekly_flow_as_daily`（投資家＋本日/今日）を error。
    「買い越し／売り越し」は助言語彙から除外。
- `.github/workflows/p2d-market-pilot.yml`: Phase 3.5 step 追加（JQUANTS_API_KEY のみ
  runtime injection）。timeout 15→25分（`LIVE_RUN_CLOSEOUT_PROTOCOL.md` の表を更新）。
- `docs/databank/MARKET_INTERNALS_SPEC.md`【新規】（仕様＋live evidence）。
  live実測（p2d-market-pilot run #20）: date指定取得 46 session × 4,441行（1 session=1リクエスト）、
  universe 1,555銘柄、Fact 4,123 / Context 535、manifest 再現性 90/90、look-ahead leaks 0、
  Compass BEFORE/AFTER 5 mornings 全て VALID（outlook・one-liner 不変、internals claims 35/35 grounded）、
  adversarial 6/6、backfill 推奨 ROLLING_WINDOW（5年backfillは未実行）。
- オフラインテスト 88 件追加（`tests/intelligence/test_market_internals.py`【新規】54 件、
  `tests/intelligence/test_compass_language_safety.py`【新規】34 件）。

### 改善

- `context/model.py`: `ContextStatus.NOT_ENTITLED`、`CompassContextSnapshot.internals_status`
  （既定は空。3-B の挙動は不変）。
- `context/salience.py`（1.1.0）: internals 型の tier（breadth_state / index_leadership =
  PRIMARY、他 = SECONDARY）、週次公表の鮮度規則、note の説明キーを components へ。
- `compass/evidence_package.py`（1.1.0）: internals 次元の代表Context固定・`internals_status`
  併合。業種 leaders/laggards は要約と一緒に固定。
- `compass/lexicon.py` / `direction_validation.py` / `missingness_validation.py`:
  internals 主語（値上がり銘柄・売買代金・業種別・大型株・海外投資家）の方向／欠落検証。
- `compass/generator.py`: OUTLOOK 文を confidence 別の強度表現へ。WHY / RISK に rule_ref。
- `market/jquants_light_store.py`: `prices_on` / `security_effective_dates` /
  `securities_effective` / `investor_flows_published_by` を追加（既存queryは不変）。

### 修正

- なし。

## v4.34 (2026-09-01) — Phase 3-C: Evidence-Grounded Compass Generator

Fact Layer（3-A）＋ Context Engine（3-B）で確認された情報**だけ**を根拠に、
Morning Compassとして利用可能なgrounded narrativeを生成する層。
**LLM MAY WRITE. LLM MAY NOT INVENT.** 生成物は全てvalidator／quality gateを通り、
合否を決めるのはgeneratorではなくvalidatorである。実データpilotは決定論的generatorのみ
（LLM provider未接続・secret未注入・新しいAPI keyを要求しない）。

### 追加

- `src/intelligence/compass/`【新規】（1機能=1ファイル・既存コード不変）:
  - `model.py`: ClaimType（FACTUAL / RELATIONAL / INTERPRETIVE / OUTLOOK / RISK）と
    ClaimRole（HEADLINE / WHAT_HAPPENED / WHY / OUTLOOK / RISK / COVERAGE）を分離し、
    claim毎に fact_id / context_id の引用を必須化。推奨語彙（buy/sell/target）は存在しない。
  - `evidence_package.py`: Morning Snapshot → generatorに渡してよい根拠集合。
    look-ahead FAIL-CLOSED・evidence budget（tier別上限）・missingness保持・
    Factを複製しない。`prompt_payload()` はwhitelistフィールドのみ（note/excerpt/locator不可）。
  - `outlook.py`: Compass DNA（JP_DIR_001 / JP_US_001 / JP_FX_001 / JP_INT_003 /
    JP_DIR_004）による決定論的含意分類・方向・確度ladder・無効化条件・反対材料常設。
  - `narrative_plan.py`: lead / support / counter / coverage / prohibited を IDと統制語彙だけで決定。
    反対材料0・leadが古い・根拠無しはabstain（捏造しない）。
  - `generator.py`: DeterministicNarrativeGenerator（既定）／ LLMNarrativeGenerator
    （既存 `LLMProvider` 境界・出力はuntrusted・provider未設定ならフォールバック）／
    FakeNarrativeGenerator（adversarial用）。
  - `grounding.py` / `numeric_validation.py` / `direction_validation.py` /
    `temporal_validation.py` / `missingness_validation.py` / `language_rules.py`:
    引用チェーン・数値・方向・時制／look-ahead・欠落次元・因果断定／助言／数値目標／
    prompt injection marker の各validator。
  - `quality_gate.py` / `one_liner.py` / `pipeline.py`: 全validator適用 → verdict
    （VALID / VALID_WITH_WARNINGS / REJECTED / ABSTAINED）→ repair → 2〜4文one-liner →
    content-addressed CompassDraft。
  - `store.py`: canonical JSONL append-only ＋ 再構築可能SQLite（idempotent by draft_id）。
  - `historical_eval.py`: 過去Compass（`output/history/<date>/pre_market.html`・読み取りのみ）
    との水準／方向の**観測**比較（rule最適化はしない）。
  - `adversarial.py` / `pilot.py`: 13 adversarial case と実データpilot
    （`::P3C_*::` closeout marker・secret値は出力しない）。
- `config.yaml`: `compass_generator` セクション（budget / tolerance / max_rejected_ratio /
  min_counter_contexts / one_liner_sentences / near_event_days / llm上限 / horizon）。
- `.github/workflows/p2d-market-pilot.yml`: Phase 3-B pilotの後に Phase 3-C pilot step を追加
  （決定論的generator・secret注入なし・履歴HTMLは読み取りのみ）。
  live実測（run #19）: 5営業日全て VALID、rejected 0、look-ahead除外 0、
  adversarial 13/13、store idempotent／再構築一致、llm_calls 0、credential出力 0。
- `docs/databank/COMPASS_GENERATOR_SPEC.md`【新規】（仕様＋live evidence）。
- オフラインテスト80件追加（`tests/intelligence/test_compass_generator.py`【新規】:
  config / evidence package / outlook / plan / claim model / generator / validators /
  gate / one-liner / golden / adversarial / LLM boundary / persistence / historical /
  security / end-to-end）。

### 改善

- なし（既存モジュールは変更していない）。

### 修正

- なし。

## v4.33 (2026-09-01) — Phase 3-B: Compass Context Engine

Phase 3-AのFactを、Morning Compassが使える**structured investment context**へ
変換する層。ロードマップ訂正のとおり3-Bは**Context Engineであって
Generatorではない**——自然言語Compassの生成は行わない（3-Cの責務）。
生成経路は**完全に決定論的でLLMを一切使わない**。

### 追加

- `context/model.py`【新規】: Direction（統制語彙）/ Relationship /
  ContextItem / MarketState / CompassContextSnapshot / `make_context_id`。
  **`Relationship`に`CAUSES`を定義しない**（因果を実装上表現できない）。
  flat bandは**正当化できるunitだけ**（金利pct_pointの0.001＝公表最小刻み）に定義し、
  指数・為替は厳密な符号で判定。大きさの区分（SMALL/MODERATE/LARGE）は
  根拠が無いため**導入しない**（`MAGNITUDE_CATEGORIES_ENABLED = False`）。
- `context/builders.py`【新規】: index_direction / index_trend_vs_ma25 /
  relative_performance / nt_ratio_state / rate_direction / us_curve_shape /
  fx_direction / cross_asset_cooccurrence / event_proximity。
  既存derived Factは**参照**して再計算しない。比較は**同一session**のFact同士のみ。
  入力が欠ければContextを作らない。**USDJPY UP = 円安 / DOWN = 円高**を明文化。
- `context/salience.py`【新規】: 説明可能なtier（PRIMARY/SECONDARY/BACKGROUND）と
  決定論的ranking。**LLMに重要度を決めさせない／0-100スコアを作らない**。
  品質・鮮度による**降格のみ**（昇格しない）。判定要素は`priority_components`へ全保存。
- `context/snapshot.py`【新規】: 朝（JST 6:00）のcontext snapshotと
  look-ahead防止（**全支持Factが既知**でなければ利用不可＝FAIL-CLOSED）、
  market state vector（**RISK_ON等の解釈分類を作らない**）と次元ごとの充足状況。
- `context/store.py`【新規】: canonical JSONL append-only ＋ 再構築可能なSQLite ＋
  query（session / type / subject / **fact_id逆引き** / high priority /
  divergence / event）。**Factを複製せずID参照だけを持つ**。
- `context/compass_alignment.py`【新規】: 過去Compass（`output/history/<date>/
  pre_market.html`）の前日比サマリーの**符号**とContextの方向を突き合わせ、
  MATCH / PARTIAL / CONFLICT / NOT_AVAILABLE を報告（履歴HTMLは読み取りのみ）。
  比較できない次元は分母から外す。**人間の文章を再現するようruleを最適化しない**。
- `context/pilot.py`【新規】: 実データpilot（複数session生成・朝snapshot・
  look-ahead検査・上位Context・冪等性・SQLite再構築・query・過去Compass整合）。
  live実測（p2d-market-pilot run #18）: 5営業日・165 Fact → 48 Context、
  重複0 / provenance欠落0 / 冪等 / SQLite再構築一致、**look-ahead leak 0**。
- `docs/databank/LIVE_RUN_CLOSEOUT_PROTOCOL.md`【新規】＋
  `tests/intelligence/test_live_run_closeout.py`【新規】: live runの完了待機を
  `trigger → bounded polling → completed detection → evidence retrieval` に固定。
  待機上限は対象workflowの `timeout-minutes` から決め、**無期限待機を禁止**する。
  「応答が取れない」を「未完了」と誤判定しないことを明記（今回の待機shell滞留の
  直接原因）。closeout対象workflowが上限を宣言していることをテストで固定する
  （本番 `daily-market-brief.yml` は対象外・未変更——CLAUDE.mdルール15）。
- `.github/workflows/p2d-market-pilot.yml`: Phase 3-A pilotの後に
  Phase 3-B pilotを追加（新規fetchなし。既存のTOPIX V2経路は不変）。
- `docs/databank/CONTEXT_ENGINE_SPEC.md`【新規】。
- オフラインテスト68件追加（`tests/intelligence/test_context_engine.py`【新規】）。

### 改善

- `context/snapshot.py`: 朝のsnapshotは**当日クローズを知り得ない**ため、
  鮮度の基準を「cutoff時点で利用できた最新session」(`reference_session`)とした。
  前営業日クローズが暦日違いだけで降格されない。同じ次元に複数sessionがある場合は
  並び順ではなく**最新session**を採用し、それより古いものは`STALE`として報告する。

### 修正

- `facts/model.py` / `facts/store.py` / `facts/jquants_builder.py`:
  Phase 3-B pre-flightの**実データ**pilotで検出した`duplicate_fact_ids: 26`を修正。
  Factのidentityに`identity_discriminator`を追加し、同一銘柄・同一開示日の
  複数指標（売上高・営業利益…）が互いをSUPERSEDEしないようにした（回帰テスト6件追加）。

## v4.32 (2026-09-01) — Phase 3-A: Evidence-Grounded Fact Layer

Data Bankの観測・記事evidence・J-Quants構造化データを、Morning Compassが安全に
使える**atomic fact**へ変換する層。**FACT ≠ INTERPRETATION ≠ OUTLOOK ≠
RECOMMENDATION** ——ここで作るのはFACTだけで、文章生成・見通し・推奨は含まない。

### 追加

- `facts/model.py`【新規】: Fact / FactSubject / FactValue / FactTimeContext /
  FactEvidenceRef / FactCalculation。**決定論的fact_id**（処理時刻を含めず、
  値が変われば別ID→`revision_of`で履歴追跡）。usable Factはprovenanceと値が必須、
  値は**Decimal限定**（floatは型で拒否）。
- `facts/calculations.py`【新規】: return_pct / change_abs / moving_average /
  distance_from_ma_pct / nt_ratio / yield_spread を `name:version` で登録。
  入力不足はNoneを返し、**forward fill・0補完・近傍日代用をしない**。
- `facts/market_builder.py`【新規】: **session-aware**（暦日ではなく観測セッションで
  数える）。25本未満の移動平均・21本未満の20営業日リターンは生成しない。
  各セッション時点のFactを作る `build_history_facts` も提供。
- `facts/availability.py`【新規】: morning cutoff（JST 6:00）とlook-ahead防止。
  `known_at` が無いFactは「既知だった」と**見なさない**（FAIL-CLOSED）。
- `facts/conflict.py`【新規】: AGREE / CONFLICT / STALE / SUPERSEDED / UNKNOWN。
  値が割れたら**両方保持**し勝手に勝者を決めない（arbitration engineは作らない）。
- `facts/store.py`【新規】: canonical JSONL append-only ＋ **再構築可能**なSQLite ＋
  query（latest / by date / range / entity / series / **evidence source** /
  **derived inputs** / conflicted）。
- `facts/jquants_builder.py`【新規】: 実績値と会社予想値を**別fact_type**で分離。
  security master・日次価格・カレンダー・週次需給はFactへ複製しない。
- `facts/news_builder.py`【新規】: **LLM要約をFactにしない**。文書メタデータ由来の
  `document_published` のみを**citation-ready**（excerpt span付き）で生成。
- `facts/pilot.py`【新規】＋ `docs/databank/FACT_LAYER_SPEC.md`【新規】。
- オフラインテスト77件追加。

### 改善

- **P2-H pilot summaryの曖昧さを解消**（Phase 3 pre-flight hygiene）:
  `datasets_attempted` を `non_sample_datasets_attempted` /
  `sample_dataset_families_attempted` / `market_bank_datasets_validated` /
  `total_dataset_families_validated` へ分解。**historical run #3の出力は改竄せず**、
  current code側の意味を明確化した。

### QA / provenance規律

- `reject` 判定のevidenceから**production Factを作らない**。`limited_use` は
  `LIMITED_USE` として明示し、morning snapshotから既定で除外する。
- 全Factが Observation / RawItem / FetchAttempt まで辿れる。derived factは
  入力observation_id / fact_id を保持する。**「LLMがそう言った」をprovenanceにしない**。

### 実測（live pilot run #17・2026-09-01・実データ）

- 入力: Nikkei 267 / TOPIX 268 / JGB10Y 267 / UST2Y_par 275 / UST10Y_par 275 /
  USDJPY 285セッション、QA判定 22,325件
- 生成 **165 facts / 14 fact types / 5 Tokyo sessions**。provenance 165/165、
  derived with inputs 135、canonical 165 → **SQLite再構築165（一致）**
- **Compass数値replay**: TOPIX 4181.86（2026-09-01）・25DMA 4077.95・乖離+2.548094%、
  日経 66311.93・25DMA 65700.638・乖離+0.930420%、JGB10Y 2.943、UST2Y_par 4.34、
  UST10Y_par 4.75、ドル円 160.122、**NT倍率 15.954596**、**米10-2年 0.410000**。
  NT倍率とスプレッドは**Market Data Bank側の派生値と完全一致**（独立経路での再現）
- **look-ahead防止**: 5セッションのmorning snapshotで
  21 / 54 / 87 / 125 / 153 facts が利用可能、**leak 0件**・
  全セッションで未来日付なし（各朝のsnapshotは前営業日までのFactのみ）
- data quality: 重複fact_id **0** / provenance欠落 **0** / derived入力欠落 **0** /
  conflict 0

### 境界（実装していないもの）

natural-language Compass generation / LLM market outlook / 投資推奨 /
theme inference / market narrative / causal inference / Market Internals分析 /
breadth engine / screener / company scoring / portfolio / MCP / frontend / scheduler。

## v4.31 (2026-09-01) — Phase 2-H: J-Quants Light Core Data Foundation

P2-Gで実証したJ-Quants V2接続を、**TOPIX専用provider**から
**再利用可能なLight Core Data Foundation**へ昇格。取得可能だから実装するのではなく、
**どのInvestment Intelligence機能で使うか説明できるdatasetだけ**を採用した
（MINIMAL / REUSABLE / AUDITABLE / FAIL-CLOSED）。

entitlement・endpoint・項目名はすべて **live実測**（probe run #1 / pilot run #3・
2026-09-01）。公式ドキュメントからの類推でAVAILABLE扱いしたものは無い。

### 追加

- `jquants_v2_client.py`【新規】: 任意path＋params＋pagination＋entitlement判定の
  汎用取得経路。credential解決・scrub・原因分類・HTTPは既存 `jquants_v2` を
  **importして再利用**し、live実証済みのTOPIX providerには**一切触れない**。
- `jquants_light_datasets.py`【新規】: dataset registry。REQUIRED 6 / USEFUL 1 /
  DEFER 7。NOT_ENTITLED 6件も証拠として保持（**迂回実装しない**）。
- `jquants_records.py`【新規】: God Objectを作らず6種へ分離——SecurityMaster /
  DailyPrice / FinancialSummary / EarningsSchedule / TradingCalendar /
  InvestorTypeFlow。全recordが provenance（source / provider / api_version=v2 /
  endpoint / retrieved_at / raw参照 / normalizer version）を保持。
- `jquants_light_store.py`【新規】: canonical JSONL（append-only・冪等）＋
  **再構築可能**なSQLite＋query（code / 社名 / 価格履歴 / 最新価格 / 財務 /
  最新会社予想 / 決算予定 / カレンダー範囲 / 需給期間）。
- `tokyo_calendar.py`【新規】: latest completed Tokyo session の最小判定。
- `p2h_light_probe.py`【新規】/ `p2h_light_pilot.py`【新規】/
  `p2h-jquants-light.yml`【新規】: entitlement/schema discovery と small live pilot。
- docs 2件【新規】: `JQUANTS_LIGHT_CAPABILITY_MATRIX.md` /
  `JQUANTS_LIGHT_CORE_ARCHITECTURE.md`。
- オフラインテスト66件追加。

### 改善

- **TOPIX freshnessが代理指標だけに依存しなくなった**（P2-G.2の残課題）:
  `evaluate_topix_freshness()` に `calendar_session` を追加し、公式取引カレンダー
  基準で判定できるようにした。**未指定なら従来どおり参照系列（日経平均）で判定**
  ——既定の挙動は不変でP2-G.2のlive実証結果を壊さない。

### 修正

- `p2h_light_pilot._store_raw` が `RawItem` を誤ったモジュールから取り込んでいた
  （live run #2 で ImportError）。`sources.model` へ修正し、`_store_raw` と
  pilot本体をオフラインで通す回帰テストを追加。

### identity規律（潰さないもの）

- Company（企業） ≠ **listed security（上場銘柄）**——security recordは
  company entityのidentityを張らない（既存Entity Catalogの責務を侵さない）。
- **生close ≠ 調整後close**（C / AdjC を別フィールド＋AdjFactor保持。
  total returnはsourceに無いので作らない）。
- 実績 ≠ 会社予想 ≠ 翌期予想（Sales / FSales / NxFSales を分離）。
- **公表日 ≠ 対象期間**（investor flowはPubDateとStDate/EnDateを分離・週次を明示）。
- **TOPIXはMarket Data Bankが所有**し、light storeへは保存しない（二重の真実を作らない）。

### 実測（live pilot run #3・2026-09-01）

- listed_master **4,441銘柄** / daily_bars 代表8銘柄×**244セッション**
  （2025-09-01〜2026-09-01・計1,952行）/ fins_summary 200件 /
  markets_calendar 401件 / investor_types 68件（64期間・週次）
- **TOPIX regression PASS**: HTTP 200・項目 `C/Date/H/L/O` がP2-G.2実測と一致・
  light storeへ書き込みゼロ
- **取引カレンダー区分を実測検証**: TOPIX観測日と21件照合し**21一致・不一致0**
  → `HolDiv=1` のみ営業日として採用（`0` `3` は営業日扱いしない）。
  `latest_completed_session=2026-09-01` がTOPIX最新日と一致
- **persistence PASS**: SQLiteをcanonicalのみから再構築し全dataset件数一致
- **data quality**: 重複record_id **0件** / raw provenance欠落 **0件**（全6 dataset）
- **scale見積り**: 794 bytes/価格1行 → 全銘柄×5年で約 **5,418,020行 ≒ 4.3 GB**・
  約4,441リクエスト。pilotは21リクエスト/16.9秒
- **full-universe backfillは実施していない**（P2-Hの対象外）

### 境界（実装していないもの）

Phase 3 / Fact extraction / Compass Generator / Market Internals analysis /
breadth / anomaly detector / 投資推奨 / screener / company scoring / MCP /
frontend / scheduler / Standard・Premium限定機能の迂回実装。

## v4.30 (2026-09-01) — PROJECT-WIDE RETROACTIVE AUDIT（既存状態の棚卸しと不整合の解消）

プロジェクト開始時点から現在までの全実装・全Phaseを対象に、**現在のリポジトリを
Ground Truth**として実装／テスト／live evidence／catalog／health／workflow／
documentation／CHANGELOG／Git historyを横断照合した。新Phase・新機能の実装は行わない。

### 修正

- **テストが実ネットワークへ出ていた（test isolation違反・重大）**:
  `main.py` は各collectorへ `config.get("<name>_sources")` を渡し、キーが無いと
  collector側の**既定URL（実サイト）**へフォールバックする。v2.9で追加された
  `fed` / `sec` / `us_gov_stats` / `ecb` / `crypto_news` / `yahoo_finance_us` が
  テスト用configに追随しておらず、「ネットワークなしで検証する」と明記された
  テストが毎回実サイトへ接続していた（1回の全体実行で103接続を実測）。
  テスト用configで全キーを空にして解消（**production semanticsは無変更**）。
  full suiteの実行時間も約60秒→約27秒へ短縮。
- **テストが追跡対象の実データを書き換えていた**:
  `investment_journal.dir` 等を指定しないと既定のリポジトリ配下
  `data/investment_journal/` へ書き込むため、`tests/test_main.py` /
  `tests/test_v4_schedule_main.py` の実行で `journal.json` の `top_news` が
  空配列に上書きされていた。出力先をtmpへ隔離して解消。
- **legacy V1 providerのTypeError**: `jquants_topix.py` の `no_symbol` 分岐で
  `**base` と `url=` が二重指定になりTypeErrorを送出していた（V2側は修正済み）。
  GAPとして正常に返すよう最小修正。

### 改善

- **legacy/probeコードの隔離明示**: J-Quants **V1**（2026-06-01終了）モジュールへ
  LEGACY/SUPERSEDEDバナーを追加。調査用プローブ3件
  （`p2g_probe` / `p2g1_auth_probe` / `p2g2_v2_discovery`）へ
  HISTORICAL PROBEバナーを追加。**削除はしない**（当時の実測を再現・参照するため）。
- **workflowの記述と実態の一致**: `p2d-market-pilot.yml` のヘッダが
  「Secrets不使用」のままだったため、`JQUANTS_API_KEY` のみをruntime injectionする
  現状を明記。
- **stale documentationの解消**（歴史は上書きせず注記・追記で明確化）:
  `CRITICAL_MARKET_SOURCE_GAP_CLOSURE.md`（G10がPARTIALLY_RESOLVEDのまま）へ
  現況バナーと §6 closeoutを追加、`PHASE2_ACCEPTANCE_REPORT.md` へ現況注記、
  `DATA_BANK_HEALTH_SPEC.md` へ状態導出表と §5 現況を追加、
  `MARKET_SOURCE_MAPPING.md` のsymbol対応表を現行カタログへ更新、
  `MARKET_DATA_QUALITY.md` の「データなし3系列」をHISTORICAL RECORD化、
  `MARKET_SERIES_CATALOG_SPEC.md` からカタログ版数の焼き込みを除去。

### 追加（リグレッションガード。テストのみ・production変更なし）

- `test_secret_hygiene.py`【新規】: 追跡ファイル全体を対象に、プロバイダ発行キー
  形式のリテラルと**credentialを載せたURL**を検出（値は検出時も出力しない）。
  V2 providerがAPI Keyをヘッダでのみ送りURL/body/error_detailへ残さないことも固定。
- `test_legacy_isolation.py`【新規】: V1 providerとprobeモジュールが
  production path・workflowから到達不能であること、pilot workflowが注入する
  secretが `JQUANTS_API_KEY` **のみ**であること、docsがcatalogと矛盾しないこと、
  V1を現行APIとして記載したdocsが無いことを固定。
- `test_derived_provenance_audit.py`【新規】: run #15の実測形（TOPIXだけ1営業日
  新しい）でNT倍率を**forward-fillしない**ことを両方向で固定。provenance
  （入力2件のobservation_id＋calculation_method）・Decimal・ゼロ除算・欠測も固定。
- `test_jquants_v2.py`: G10のacceptance criteriaを機械検証（25DMA閾値・
  遅延データはRESOLVEDにしない・履歴不足はRESOLVEDにしない・
  live source validationとlocal data availabilityの区別）。
- `test_main.py`: collectorキーの網羅性と、レポート生成がリポジトリ配下
  `data/` を書き換えないことを固定。

### 監査結果（修正不要と確認した領域）

- Git history: revert・hotfix・意図しない巻き戻しなし（480 commits・linear）。
- secret混入: 追跡ファイル・Git history・workflowいずれにも実値なし。
  workflowはsecretをechoしていない。
- catalog↔implementation: provider集合・preferred_source・api_version・
  probe/enabledが一致。
- health/gap/gate: G10/G11を含む全gapが実データから機械導出され、
  live source validationとlocal data availabilityが別次元で扱われている。
- 派生データ: NT倍率・spreadとも同一trading_dateのみで生成し、
  片側欠落日を補完しない。provenanceは全行で完全。
- TODO/FIXME/XXX/HACK: `src/` `tests/` `main.py` に0件。
- vNextコードにbare except / except-passなし（fail-openなし）。

## v4.29 (2026-09-01) — Phase 2-G.2 closeout: TOPIX V2 live取得実証（G10 RESOLVED）

### 改善

- カタログ1.2.1: TOPIXを `probe: false` へ（live実証済み）。これにより
  data bank healthのcritical gap判定が実データ由来で RESOLVED を導出する。

### 実測（live pilot run #15・Light plan投入後）

- **V2 authenticated fetch: HTTP 200**。`auth_method_validated: api_key_header`
  が**初めて非空**になった（data endpointの200をもってのみ「検証済み」と宣言する
  規律の帰結）。API Keyはヘッダのみで送信し、URL・raw payload・FetchAttempt・
  ログ・例外のいずれにも秘密は出ていない。
- 応答schema実測: top keys `["data"]` / row fields `["C","Date","H","L","O"]`
  ——事前に一次情報で確認したV2仕様と**完全一致**（推測変換なし）。
- TOPIX identity: `index:topix.close.closing.tokyo`。ETF（1306.T）・先物・
  近似指数の代用なし。
- historical **268営業日**（2025-07-28〜2026-09-01）・25DMA可能・unit `index`。
- latest trading date **2026-09-01**・close `4181.86`・
  as_of `2026-09-01T06:30:00+00:00`（15:30 JST）。
- freshness **CURRENT_USABLE**（`gap_sessions: 0` / `lag_days: 0`。基準系列
  日経平均の最新2026-08-31に対しTOPIXは同一以上のセッション）。Morning Compass
  当日入力として**利用可**。
- QA: **`MARKET_OBSERVATION:accept` 268件**（issue 0）。
- 永続化: canonical 22,289観測＝別プロセスでのindex再構築22,289・
  `recovered_lines: 0`・latest一致16/16・backup verify 0/0/0。
- NT倍率 **266行**（latest 2026-08-31 = `15.954596 x`・input 2件の
  observation_id＋`calculation_method: nt_ratio:1.0.0`）。TOPIXが2026-09-01まで
  あるのに対し基準の日経平均が2026-08-31までのため、片側欠落の2026-09-01は
  **生成していない**（同一trading_dateのみ・捏造しない）。
- 併走系列も成功: JGB10Y 267行（〜2026-08-31・2.943 pct）／UST2Y_par 275行
  （4.34 pct）／UST10Y_par 275行（4.75 pct）／official spread 275行
  （0.41 pct_point）。Treasury dedupはFetchAttempt 1件・RawItem共有を維持。
- **G10 = RESOLVED**（`live_authenticated_fetch` / `history_ge_25dma` /
  `current_session_available` / `matches_reference_tokyo_session`）。

## v4.28 (2026-08-30) — Phase 2-G.2: J-Quants V1→V2 migration（TOPIX経路）

### 追加

- `src/intelligence/market/jquants_v2.py`【新規】: **V2専用**のTOPIX provider。
  Base URL `https://api.jquants.com/v2`・TOPIX専用パス
  `/indices/bars/daily/topix`・応答 `{"data": [...], "pagination_key": ...}`・
  V2短縮項目名（`O`/`H`/`L`/`C`、`Date`は不変）に対応。
- `JQuantsV2CredentialResolver`: 認証は**API Keyをリクエストヘッダで送る方式**
  （V1のtoken交換は廃止）。`JQUANTS_API_KEY` **のみ**受理し、V1のenv名
  （MAIL / PASSWORD / REFRESH_TOKEN / ID_TOKEN）は**V2では受理しない**
  ——旧仕様をV2の既定へ持ち込まないことをテストで固定。
- 原因分類 `classify_v2_failure()`: `api_version_mismatch` /
  `plan_not_entitled` / `credential_rejected` を応答messageから機械分類する。
- `ProviderInfo.api_version`（既定は空・後方互換）とカタログ
  `providers.jquants.api_version: v2`。
- テスト34件追加（`tests/intelligence/test_jquants_v2.py`【新規】）。

### 改善

- **PLAN_CAPABILITY**: entitlement次元のみ VERIFIED（TOPIX四本値は
  **Lightプラン以上**・更新は毎営業日16:30頃JST——公式クイックスタートV2）。
  プラン別の遅延日数・履歴範囲は依然 **UNVERIFIED**（実取得結果で確定する）。
- 秘密安全の強化: 応答本文をエラー診断へ載せる前に**部分一致でも遮断**し、
  API Gatewayが返す SHA-256/Base64 ダイジェストのエコーも除去する。
  API Keyはヘッダのみで送り、永続化されるURLへ載せない。
- workflowをV2 pilotのみへ整理（EOL済みV1を現行候補として叩き続けない）。
- カタログ1.2.0（endpoint_templateをV2専用パスへ）。series identity
  `index:topix.close.closing.tokyo` と NO PROXY SUBSTITUTION 原則は不変。

### 修正

- **run #7〜#12の403の再分類**: J-Quants V1は2026-06-01に終了しており、
  当時のV1エンドポイントへのアクセスは `legacy_v1_endpoint` /
  `api_version_mismatch` を主要原因候補とする（credential不正と断定しない）。
  過去の実測記録はappend-onlyで保全し、`TOPIX_SOURCE_DECISION.md` §7で
  解釈のみを訂正した。
- `g10_state()` が版数不整合を `auth_failure` として報告しないよう分岐を追加。
- V2 providerで、jquantsのsymbolを持たない系列を渡すと
  `ProviderFetchResult` のキーワード重複でTypeErrorになる不具合を修正
  （`no_symbol` のGAPとして正常に返す。回帰テスト追加）。

### 実測（live pilot run #14・2026-08-30）

- **V2 endpoint到達・契約識別まで成立**: `GET /v2/indices/bars/daily/topix` は
  HTTP 403だが応答は *"This API is not available on your subscription. If you
  want more data, please check other plans: …"*。V1時代の内容のない
  `{"message":"Forbidden"}` とは異なり、**サーバがサブスクリプションを特定した
  うえでの権限拒否**である——endpoint・API版数・API Keyの搬送方式は正しい。
- G10 = **BLOCKED**（`access_level_insufficient` / `plan_not_entitled`）。
  残る障害は**プラン権限のみ**で、TOPIX四本値は**Lightプラン以上**が条件
  （公式ドキュメントとlive応答の2系統で一致）。
- `auth_method_validated` は**空のまま**（data endpointの200を得ていないため、
  認証方式を「実APIで検証済み」とは宣言しない）。
- TOPIX raw 0行 → freshness `NO_DATA`・NT倍率0行（片側だけで生成しない）。
- 併走系列は無変更で成功: JGB10Y 265行（〜2026-08-27・2.897 pct）／
  UST2Y_par 274行（〜2026-08-28・4.34 pct）／UST10Y_par 274行（4.73 pct）／
  official spread 274行（0.39 pct_point）。Treasury dedupは
  FetchAttempt 1件・RawItem共有を維持。
- 永続化検証 PASS（canonical 20,689観測＝index再構築一致・recovered_lines 0）。

## v4.27 (2026-08-30) — Phase 2-G.1: API Key認証方式の実測判定とTOPIX authenticated pilot

### 追加

- `p2g1_auth_probe.py`【新規】: 投入credentialがどの搬送方式で通るかを実APIで
  判定するプローブ（秘密値・token値は一切出力しない）。
- `METHOD_API_KEY`: `JQUANTS_API_KEY` を型宣言のないcredentialとして受理し、
  搬送方式を**上限2回**で判定（refreshToken交換 → Bearer直挿し）。成功した
  方式のみ `mechanism_validated` に記録（未成功は空のまま断定しない）。
- テスト9件追加（計1,184 passed）。

### 修正

- `_default_http`が非2xxをHTTPErrorとして送出しており、403がnegotiationを
  素通りして生の例外文字列になっていた（run #11実測）。ステータスとして返す
  よう修正し、構造化診断
  （`api_key_mechanism_not_accepted:<方式>:http_<code>`）が出るようにした。

### 実測（run #10〜#12）

- **投入されたJQUANTS_API_KEYは5搬送方式すべてで HTTP 403**（refreshtoken
  クエリ/body・Bearer・x-api-key・Authorization生値）。公式docsはJS描画・
  OpenAPIは403のため仕様本文も機械取得できず → **API Keyが現行の正式な
  認証方式であることは確認できていない**（旧方式の推測適用もしない）。
- TOPIX STEP 1-8: auth_error → 履歴0・NO_DATA・NT倍率0 →
  **G10 = BLOCKED（auth_failure）**。API Key値は一切出力していない。
- Treasury dedup継続確認: FetchAttempt 1件・両par系列が同一RawItem/Attempt共有・
  spread 274行・persistence 20,689観測一致・backup verify 0/0/0。

## v4.26 (2026-08-30) — Phase 2-G.1 レビュー反映: Treasury dedup / PLAN_CAPABILITY訂正

監督者レビュー（P2G1_TOPIX_CLOSEOUT_ACCEPTED）の指摘反映。TOPIXのcredential
待ち状態は変更なし（追加のnetwork retryは行っていない）。

### 追加

- **MINI TASK A（Treasury curve fetch dedup）**: ONE SOURCE DOCUMENT MAY
  PRODUCE MULTIPLE OBSERVATIONS。同一年CSVを系列ごとに再取得せず、1 run中は
  年ごと1回だけ取得してrun-localキャッシュから配る。再利用時は
  `served_from_cache` を立て、storeは新規FetchAttemptを記録せず
  **同一RawItem・同一FetchAttempt**を共有する（起きていない取得を記録しない）。
  series identityは非マージ（UST2Y_par ≠ UST10Y_par。observation_id・列・値・
  単位は独立）。payload単位で**1回だけ**再試行（run #8のtimeout対処）。
  **live実測（run #9）**: treasury FetchAttempt記録 2→**1**・両系列が同一
  RawItem/FetchAttemptを共有・run #8でfailedだったUST10Y_parが**success 274行**
  へ回復・official spread 274行復帰。requested 16 = success 15 + gap 1 +
  **failed 0**。
- G10結果状態に **C: access_level_insufficient** / **D: auth_failure** を追加
  （fetch失敗理由をreason codeへ写像）。
- `auth_method_validated`: **実APIのdata endpointが200を返した方式のみ**を
  検証済みとして記録（解決できた方式をsupportedと断定しない）。
- テスト26件追加（計1,175 passed）。

### 修正

- **PLAN_CAPABILITY = UNVERIFIED**（監督者訂正）: 「Free=12週遅延 /
  Light以上=当日利用可」等のJ-Quantsプラン能力をsystem ground truthとして
  固定していた記述を、コード（access要件レポート）・カタログ・docsから撤回。
  実credentialでの取得結果、または取得可能な公式documentation evidenceで
  確定する。必要access tierの断定は保留し、判定は実測のfreshness verdictで行う。

### 改善

- NT倍率: TOPIXが遅延している期間は「current」として使わない旨をpilot出力へ明示。

## v4.25 (2026-08-30) — Phase 2-G.1: TOPIX Credentialed Live Closeout

対象はTOPIX（G10）のみ。原則: **DO NOT LIE ABOUT FRESHNESS**（API接続成功と
履歴取得と当日利用可否を区別する）＋**NO PROXY FALLBACK**。
live実測: run #8（success 14 / gap 1 / failed 1・raw 3,971・derived 15,128・
persistence 19,099観測一致・backup verify 0/0/0）。

### 追加

- credential resolver契約 `JQuantsCredentialResolver`＋`EnvCredentialResolver`:
  id_token / refresh_token / mail_password を優先順に解決し、方式名と由来env名
  **のみ**を報告。J-Quantsの認証仕様変更（token/API key方式等）はresolverの
  差し替えで吸収する（env名を恒久仕様と仮定しない）。
- credential safety: `Secret`型でrepr/str封鎖・全error_detailのscrub・
  認証応答の非永続・locator/raw payloadへの秘密非混入。credential未設定時は
  **ネットワークを1回も叩かず**正常停止（TOPIX_CREDENTIAL_MISSING）。
- schema/identity guard `validate_topix_payload`: 銘柄コード・NAV・限月・
  清算値等を含む応答を`identity_mismatch`で拒否（ETF NAV/先物を1行も
  取り込まない）。
- `src/intelligence/market/topix_freshness.py`【新規】: 当日利用可否を
  **同一東京セッションの実データ基準**で判定（休日カレンダーを推測しない）。
  CURRENT_USABLE / DELAYED_NOT_CURRENT / NO_DATA＋lag_days・gap_sessions。
  G10状態遷移（RESOLVED / HISTORICAL_RESOLVED_CURRENT_BLOCKED /
  PARTIALLY_RESOLVED / BLOCKED）＋reason code必須。access要件レポート
  （必要tier・観測遅延をユーザー判断事項として提示）。
- pilot `::P2G1_TOPIX::` STEP1-8マーカー（秘密を一切出力しない）＋
  J-Quants認証仕様の実API応答プローブ。
- テスト40件追加（計1,149 passed）。

### 改善

- health.py: G10をfreshness込みで機械判定（`SOURCE_VALIDATED_DATA_NOT_LOCAL`
  状態を追加。live実証済みだがcanonicalが本rootに無い場合の正直な申告）。
- workflowのcredential注入を4変数（ID_TOKEN/REFRESH_TOKEN/MAIL/PASSWORD）へ
  拡張——repository secretsのみ・値はGit/configへ保存しない。

### 修正

- なし（TOPIX以外の系列・既存挙動は変更していない）。
  ※run #8で `rates:UST10Y_par` がtimeoutでfailed（run #7は成功）。
  同一年ファイルの重複取得が一因と見られるが、P2-G.1の範囲外のため
  **提案のみ**（CRITICAL_MARKET_SOURCE_GAP_CLOSURE.md §5.1）。

## v4.24 (2026-08-30) — Phase 2-G: Critical Market Source Gap Closure

原則: **NO PROXY SUBSTITUTION**（TOPIX→ETF・JGB10Y→別年限/入札・UST2Y→
別概念yieldの代用禁止）。対象はTOPIX/JGB10Y/UST2Yの3系列のみ。
live実測: probe run #6（source調査）＋run #7（requested 16 = success 15 +
gap 1 + failed 0・raw 4,245・derived 16,444・persistence/backup全green）。

### 追加

- `src/intelligence/market/treasury_curve.py`【新規】: 米財務省Daily Treasury
  Par Yield Curve provider（年別CSV・複数年は連結申告・fair-access UA実測）。
  official par yieldは市場実勢index（^TNX型）と**別概念**のため
  `rates:UST2Y_par` / `rates:UST10Y_par` の新seriesとして接続——
  live実測 各274行（2025-07-28〜2026-08-28・latest 4.34 / 4.73 pct・
  as_of 15:30 ET）。既存^TNX系列は無変更で併存。
- `src/intelligence/market/mof_jgb.py`【新規】: 財務省国債金利情報provider
  （jgbcm_all＋当月jgbcm の2ファイル実測構成・Shift_JIS・和暦→ISO決定論変換・
  constant maturity 15時クローズ）→ JGB10Y series——live実測 265行
  （〜2026-08-27・latest 2.897 pct・as_of 15:00 JST）。
- `src/intelligence/market/jquants_topix.py`【新規】: J-Quants（JPX公式系API）
  TOPIX provider（指数値そのもの・ETF/先物代用なし・credentialは環境変数
  runtime injectionのみ・parse_float=strでfloat非経由・token非永続）。
  credential未投入のためlive取得は正直なgap（no_credentials）——
  ユーザーのJ-Quants登録＋repo secrets投入後に同pilotで自動実証。
- `src/intelligence/market/p2g_probe.py`【新規】: 公式ソース実測調査プローブ。
- official spread `rates:UST10Y_par_UST2Y_par.spread.derived_metric`——
  live 274行生成（latest 0.390000 pct_point・calculation provenance付き。
  ^TNX×official parの概念混合spreadは生成しない）。NT倍率は定義済み
  （TOPIXデータ待ち・入力なしでは出力しない）。
- `docs/databank/`【新規3ファイル】: CRITICAL_MARKET_SOURCE_GAP_CLOSURE /
  OFFICIAL_RATE_SERIES_SPEC / TOPIX_SOURCE_DECISION。
- テスト38件追加（計1,109 passed）。

### 改善

- カタログ1.1.0: PRIMARY_OFFICIAL providers（treasury_gov/mof_japan/jquants・
  Tier1）追加・live実証済み3系列のprobe解除・旧UST2Y（市場実勢・実績ゼロ）は
  identity定義のみへ（official値を混入しない）。
- health.py: critical gapsの解決状態をカタログ＋ローカル実データから機械導出
  （G11=RESOLVED・G10=PARTIALLY_RESOLVED。TOPIX未解決の間phase3はBLOCKED）。
- pilot_runnerへ::P2G_GAPS::マーカー・ProviderFetchResult.media_type追加。

### 修正

- なし（既存系列・既存挙動の変更なし）。

## v4.23 (2026-08-30) — Phase 2-F: Data Bank QA / Query / Human Review

原則: THE DATA BANK MUST BE EXPLAINABLE, CORRECTABLE, AND REBUILDABLE。
Phase 2最終統合ゲート。**zero unknown loss機械証明**（会計恒等式
2,976+25+55=3,056）・P2-C/P2-D持ち越しwarningの意味論的解決（捏造・削除なし）・
Phase 3が使う統一読み出し契約まで。分析エンジンは未実装（DO NOT遵守）。

### 追加

- `src/intelligence/review/`【新規7ファイル】: Human Reviewワークフロー
  （ReviewItem/ReviewDecisionRecord append-only・ALLOWED_DECISIONS型制限・
  decided_by=user:強制・manual優先適用・intake冪等・CLI。実データ88件 open——
  架空のhuman decisionは投入しない）＋Identity Decision Ledger（CANDIDATE 25件へ
  confidence/シグナル/algorithm版永続・post_hoc derivation明示・migration-safe）
  ＋Revision/Syndication role精緻化（same_publisher_update 53・
  cross_feed_same_article 2・UNKNOWN 0——DO NOT GUESS）。
- MIGRATED_PROVENANCE（HISTORICAL v1.1.0）: legacy shard/fingerprintへtrace
  可能な移行由来文書はmigrated_provenance PASS。実データ3,056件再評価
  ACCEPT 0→3,008・missing_raw_item 3,056→0（旧評価保持・6,112件併存）。
- Market Observation trust v2（MARKET_OBSERVATION v1.0.0＋ProviderTrace）:
  provider経路provenanceで評価、SUPPORTS link非必須方向へ。live run #5で
  raw 3,432件再評価 ACCEPT 0→3,432・missing_supporting_evidence_ref 3,432→0
  （旧評価保持・trace欠落はWARN維持）。
- 統一クエリ層: NewsQuery entity/classification_provenance/review_status・
  MarketQuery複合（trading_date範囲/source/QA判定/current_only/latest_session）・
  review_items索引・publisher時系列集計（OBSERVED COUNTのみ）。
- Cross-domain foundation: TradingWindow（JST朝窓・東京セッション・実データ
  導出の前米国セッション・event窓）＋fetch_window_slice（同一window取得のみ・
  causal分析なし・UTC暦日join禁止）。
- DataBankHealthReport（HEALTHY/DEGRADED/BLOCKED＋reason codes・
  critical source gaps（TOPIX/JGB10Y/UST2Y）を常時表示）・Phase 2統合
  reconciliation（重複ID/orphan/恒等式/QA被覆/schema版/SQLite一致の機械検査）。
- backup/restore演習テスト（manifest→copy→1byte破壊検知→復元→SQLite再構築→
  クエリ等価）・Phase 2全層統合トレーステスト。
- `docs/databank/`【新規8ファイル】: HUMAN_REVIEW_WORKFLOW /
  MIGRATED_PROVENANCE_SPEC / MARKET_OBSERVATION_TRUST_POLICY /
  UNIFIED_QUERY_SPEC / DATA_BANK_HEALTH_SPEC / PHASE2_RECONCILIATION /
  SCHEMA_INVENTORY / PHASE2_ACCEPTANCE_REPORT（8本）。
- テスト52件追加（計1,071 passed）。

### 改善

- SqliteNewsIndex: entity横断検索・review status結合・親ディレクトリ自動作成。
- SqliteMarketIndex: search_market複合検索（revision解決・最新セッション）。

### 修正

- なし（既存挙動の変更なし。旧trust policyの評価結果は全て保持）。

## v4.22 (2026-08-30) — Phase 2-E: News Classification / Metadata Enrichment

原則: CLASSIFICATION IS NOT FACT / EVERY ENRICHMENT MUST HAVE PROVENANCE /
FALSE ENTITY LINK IS WORSE THAN MISSED ENTITY LINK。
**full 3,001 NewsItemへのenrichment backfill完了**: 分類3,592件（entity 2,192・
rule 1,400）・validation 0 issues・冪等再実行0追加・review queue 63件保存・
校正fixture全次元precision/recall 1.000・実corpusクエリsmoke成功。
Fact抽出・市場影響・重要度スコアは未生成（DO NOT遵守）。P2-F未着手。

### 追加

- `knowledge/entities/core_entities.yaml`【新規】: Entity Catalog v1.0.0
  （80 entities。alias安全3段階: safe／context必須（Apple/Meta/Amazon/Fed等）／
  ticker明示記法限定——AI/IT/US/CAT等の裸大文字語の誤link構造排除。
  case-sensitive marker（=Fed等）で動詞fed・果物apple誤爆を実測校正）。
- `knowledge/enrichment/theme_taxonomy.yaml`【新規】: 30テーマ（既存
  theme_relations/themes.yaml監査＋監督者指定17テーマ）。slug・parent/related
  階層foundation・strong/weak多信号規則（weak単独タグ禁止）・exclude・
  tank slug対応（legacy比較専用）。
- `knowledge/enrichment/event_types.yaml`【新規】: 16イベント種別＋高precision
  フレーズ規則（OTHER自動判定なし）＋time horizon高確信規則。
- `src/intelligence/enrichment/`【新規14ファイル】: L0-L4層分離engine・
  決定論matcher群（evidence span保持）・provider中立LLM層（optional・
  スキーマ検証・未知label→review queue・不正reject・audit）・USER override
  （優先・履歴保持）・append-only store（effective view導出）・
  backfill（corpus fingerprint・段階実行・冪等）・validation 10種・品質レポート。
- NewsClassification拡張（0.x非破壊: confidence/confidence_type/role/
  evidence_field/evidence_text/taxonomy_version/basis_document_id）・
  ClassificationDimension/EntityKind拡張・SqliteNewsIndexへ時系列集計foundation
  （count_by_dimension_over_time / count_values——件数取得まで）。
- tests: +88件（matcher安全則30・engine/LLM/store/override 25・validation/
  backfill/quality 25ほか・校正fixture 30件。**1,019 passed**）。
- docs/databank: NEWS_ENRICHMENT_ARCHITECTURE / ENTITY_CATALOG_SPEC /
  THEME_TAXONOMY_SPEC / EVENT_TYPE_TAXONOMY / CLASSIFICATION_PROVENANCE_SPEC /
  NEWS_ENRICHMENT_BACKFILL_REPORT / NEWS_ENRICHMENT_QUALITY。

### 改善

- 実corpus初回実行で発見した冪等バグ（run跨ぎのcreated_at差によるID衝突）を
  semantic equality原則に沿って修正（クリーン再実行でfailed 0を確認）。
- 校正初回測定のevent誤爆2件（"surges"単独・"new chip"）を規則側で修正し
  fixture precision 1.000へ。

## v4.21 (2026-08-30) — Phase 2-D: Market Data Bank

原則: A NUMBER WITHOUT IDENTITY AND CONTEXT IS NOT MARKET DATA。
**live pilot成功**（Actions run #4）: 12系列×約13ヶ月の日足を実取得——raw 3,432＋
派生13,080=canonical 16,512件・QA全件・**別プロセス永続化検証gate通過**
（fresh process再オープン・index全再構築・latest 12/12一致）・backup manifest検証OK。
データ本体はGit非管理（Data BankはGitリポジトリではない）。P2-E未着手（禁止遵守）。

### 追加

- `knowledge/market_series/core_series.yaml`【新規】: MarketSeries正式カタログ
  v1.0.0（19系列。series_id規約検証・指数/ETF/先物・spot/fixingの非混同・
  yield=pct固定・session/as_of_policy・provider種別 PRIMARY_OFFICIAL vs
  MARKET_DATA_PROVIDER・派生定義・enabled/probe/GAP意味論）＋
  `src/intelligence/market/series_catalog.py`【新規】loader/validator。
- `src/intelligence/market/providers.py`【新規】: MarketDataProvider Protocol＋
  **yfinance一次**（legacy本番構成再現・provider_normalized=true・float供給を
  provider_float_transitとして全件申告）＋**Stooqフォールバック**（生CSV保存・
  legacy UA再利用・非CSV応答の診断snippet）。
- `src/intelligence/market/ingest.py`【新規】: 決定論正規化（stringトークン→
  Decimal直接・trading_date/as_of分離のセッションモデル・欠測非補完・
  週末/未来/重複の検知のみ・content-addressed ID・revision_of・source切替記録）。
- `src/intelligence/market/derived.py`【新規】: 派生基盤（return_1d/5d・25DMA・
  乖離率・金利スプレッド・NT倍率。inputs＋calculation_method:version必須・
  Decimal 6桁ROUND_HALF_EVEN固定・欠測非補間）。
- `src/intelligence/market/store.py`【新規】: MarketBankStore（JSONL canonical＋
  SqliteMarketIndex。latest_trading_session / latest_as_of / latest_revision_for /
  revision_chainの**latest意味論明示**・改定解決・decision結合クエリ・全再構築）。
- `src/intelligence/market/backfill.py`【新規】: provider chainエンジン（fallback
  発動の必須記録・全試行FetchAttempt永続・run manifest MarketBackfillRun・
  GAP/FAILED区分・冪等・HISTORICAL QA・依存伝播付き派生QA）。
- `src/intelligence/core/paths.py`【新規】＋config.yaml `vnext.data_root`:
  INTELLIGENCE_DATA_ROOT環境変数→config→既定の解決（絶対パス固定なし）。
- `src/intelligence/core/backup.py`【新規】: backup manifest基盤（file inventory×
  sha256×schema version・verify照合）。
- `src/intelligence/market/persistence_check.py`【新規】: 別プロセス永続化検証
  （canonical読み戻し・index空から再構築・latest照合）＋
  `pilot_runner.py`【新規】＋`quality_report.py`【新規】＋
  `.github/workflows/p2d-market-pilot.yml`【新規】＋trigger。
- Observation.trading_date追加（0.x非破壊）・SCHEMA_VERSION 0.4.0。
- tests: +95件（catalog/identity安全・provider・ingest・derived・store/latest・
  backfill/fallback・persistence subprocess・quality・trace描画。**931 passed**）。
- docs/databank: MARKET_SERIES_CATALOG_SPEC / MARKET_INGESTION_ARCHITECTURE /
  MARKET_STORAGE_AND_PERSISTENCE / MARKET_SOURCE_MAPPING /
  MARKET_BACKFILL_REPORT / MARKET_DATA_QUALITY。SOURCE_GAPSへG9〜G12追記。

### 改善

- live実測でprovider実態を確定: StooqのhistoryエンドポイントはIP制限で
  Actionsランナーから不達（HTML制限ページ）→ legacyの本番実績構成
  （yfinance一次）へ整合。TOPIXは1306.T ETFを指数へ流用せず正直にGAP化。

### 修正

- 同一内容再取得時のRawItem ID衝突（初回provenance保持・試行のみ追記へ）。
- pilot trace描画のQAIssue属性名誤り（オフライン回帰テスト追加）。

## v4.20 (2026-08-30) — Phase 2-C: Historical Tank Backfill

tank 3,056記事のvNext正式移行（BACKFILL IS A DATA MIGRATION, NOT A FILE COPY）。
**full実行完了**: 3,056/3,056 success・会計完全一致・REVISION 55統合検出・
CANDIDATE 25 queue保存・validation 0 issues。データ本体はGit非管理
（data/vnext/databank/）。P2-D未着手・新解釈生成ゼロ（禁止遵守）。

### 追加

- `databank/backfill_inventory.py`: 実測inventory（件数・分布・欠損・重複ID・
  invalid JSON・schema variants）＋input fingerprint（shard×sha256）＋決定論的
  record列挙。
- `databank/identity_blocking.py`: 候補生成のBlockingIndex（exact key＋
  title prefix/日付×sourceバケット。**総当たりO(n²)禁止**への回答。3,056件で
  メモリ58MB・二次劣化なし）。IdentityRuntimeへ統合＋resume用preload。
- `databank/backfill.py`: BackfillRun manifest（fingerprint・version群・会計・
  checkpoint）/ RejectRecord ledger（黙って捨てない）/ JsonlNewsBankStore
  （news_items=追記ログ最新正・legacy_annotations・reject_ledger・backfill_runs）/
  BackfillEngine（chunk 250・checkpoint/resume・冪等・source mapping
  exact_name 42/42実測・LEGACY_UNKNOWN安全表現・FetchAttempt捏造なし）/ reconcile。
- tests: +14件（backfill 10: inventory/fingerprint/run会計/reject ledger/
  legacy隔離/unknown source/冪等再実行/crash→resume同値ほか・blocking 4、
  計835 passed）。
- `docs/databank/`: HISTORICAL_BACKFILL_ARCHITECTURE / BACKFILL_RUN_SPEC /
  TANK_BACKFILL_REPORT / HISTORICAL_DATA_QUALITY / BACKFILL_RECONCILIATION。

### 改善

- 実運用発見: **同一canonical URLの更新版55組を検出・統合**（tankは正規化前URLで
  別レコード扱い——URL正規化＋fingerprintの実データ価値を実証）。CANDIDATE 25件は
  P2-B校正が予言したハザード族（FERC通番8・Yahoo定型7・ECBカレンダー等）で全て非merge。

## v4.19 (2026-08-30) — Phase 2-B: Article Identity / Dedup / Revision

Article Identity Layer。最上位原則 **FALSE MERGE IS WORSE THAN MISSED MERGE**
（高precision・保守的threshold・曖昧なら別Article）。LLM embedding不使用・
NewsEvent clustering未着手・full backfill未実施（禁止遵守）。

### 追加

- `databank/identity_signals.py`: 文字3-gram Jaccard＋SequenceMatcherの**min合成**
  類似度（ja/en両対応・tokenizer非依存）・title_key・時刻近接・**数字トークンガード**
  （実tank分析: 高類似別記事の上位=ECB 2027/2028・日付連載・通番が全て数字違い）。
- `databank/identity_decision.py`: EXACT_MATCH/AUTO_MERGE/REVISION/SYNDICATED/
  CANDIDATE（merge禁止）/DISTINCT＋matched/failed signals・confidence・
  algorithm_version（単一score禁止）。
- `databank/identity_resolver.py`: 4段階判定。安全規則: GUIDはsource-local・
  same URL+changed content=REVISION・title類似単独merge禁止・**summary（内容証拠）
  なしではfingerprint一致でもmergeしない**・数字集合不一致でAUTO_MERGE禁止。
- `databank/article_store.py`: event-sourced Article store（CREATE/ADD_DOCUMENT/
  MARK_REVISION/MARK_SYNDICATED/SET_PRIMARY/**MANUAL_SPLIT/MANUAL_MERGE**。
  append-only・replay導出・manual優先で誤merge修正可能・履歴不滅）。
- `databank/identity_runtime.py`: SourceDocument→Article→NewsItemのruntime接続・
  primary選定（非転載→先行公開→tier。「Tier高=原文」と仮定しない）・
  NewsDocumentLink role付与。
- `databank/identity_report.py`: metrics＋merge監査レポート（why merged明示）。
- `evidence_qa/policy.py`: **HISTORICAL v1.0.0**追加（古さ自体で制限しない・
  他Gate維持。HISTORICAL ACCEPT≠DAILY ACCEPTのcontext-dependent trust実証）。
- validation拡張: revision cycle・重複member・primary∈members検査。
- calibration: labeled fixture 29ペア（実tankハザード＋合成）＋実tank title-only
  ハザード40ペア＋実60記事runtime。**false merge 0・recall 12/12**。
  校正での設計修正2件（title-only fingerprint exact廃止・threshold 0.85）。
- tests: +38件（resolver/signals 12・calibration 6・store 8・runtime 7・
  historical 5、計821 passed）。
- `docs/databank/`: ARTICLE_IDENTITY_SPEC / DEDUP_STRATEGY /
  REVISION_SYNDICATION_POLICY / IDENTITY_CALIBRATION_REPORT / HISTORICAL_TRUST_POLICY。

## v4.18 (2026-08-30) — Phase 2-A: End-to-End Pilot + Data Bank Domain Schema

Phase 1完了承認を受けたPhase 2初段。(1) Phase 1全層の実データ一本通し検証、
(2) Market/News Data Bankの正式domain schema設計。P2-B semantic dedup・
full backfill・LLM分類・自動scoringは未着手（禁止遵守）。

### 追加

- `src/intelligence/pipeline/`: e2e.py（Registry→Fetch→Raw→Normalize→QA→Gateの
  実編成。mockなし・注入はtransportのみ・**NO FALSE EVIDENCE**を構造で保証）、
  trace.py（Assessment→Document→Raw→Attempt→Endpoint→Sourceの逆引きtrace・
  human-readable）、e2e_runner.py（Actions実行・少数source・bulk禁止）。
- `src/intelligence/databank/`: news_model.py（ArticleIdentity/NewsItem/
  NewsDocumentLink/NewsClassification/NewsScore/EntityReference/ThemeReference/
  LegacyAnnotation。SourceDocument≠Article≠News Event分離・God NewsItem禁止・
  classification provenance分離・LLM推測tagging型レベル拒否）、market_model.py
  （MarketSeries・ObservationType・series_id導出規約。spot/Tokyo close/NY close
  を別series強制）、validation.py（投入前gate 9検査項目）、query.py
  （NewsQuery/MarketQuery契約）、sqlite_index.py（再構築可能SQLite索引・
  domain層SQL禁止の隔離実装）。
- `Observation.series_id`（0.x非破壊）・`SCHEMA_VERSION 0.3.0`
  （migration戦略: docs/databank/DATA_BANK_ARCHITECTURE.md §5）。
- contracts: NewsRepository正式化（NewsItem型へ置換）・ArticleIdentityRepository追加。
- `.github/workflows/p2a-e2e-pilot.yml`: 実E2E pilot（feature branch限定・
  Secrets不使用・7ソース各1リクエスト）。
- tests: +29件（pipeline統合6・news model 8・market model 6・validation/query 9）。
- `docs/databank/`: ARCHITECTURE / NEWS_DOMAIN_MODEL / MARKET_DATA_MODEL /
  STORAGE_DECISION / TANK_BACKFILL_DRY_RUN / END_TO_END_VALIDATION（実測後追記）。

### 改善

- tank backfill dry run実施（20件・9 publishers・ja/en）: 20/20正規化成功・
  validation 0件・LegacyAnnotation隔離実証。Article identityシグナル全3,056件実測
  （canonical URL 100%ユニーク・cross-domain衝突0＝tank取込時dedup済みと確定）。

## v4.17 (2026-08-30) — Phase 1-E: Evidence QA / Trust Gate

「存在する情報 ≠ 信頼できるEvidence」。Normalized層の出力を分析利用可能な
Evidenceへ昇格させる品質関門。**13次元の独立評価**（単一scoreへ潰さない）＋
ACCEPT / ACCEPT_WITH_WARNINGS / LIMITED_USE / REJECT のGate判定。
LLMによるFact抽出は未実装（SCOPE CORRECTION遵守。検証はsynthetic fixture）。

### 追加

- `src/intelligence/evidence_qa/`（新パッケージ×7）: model.py（QADimension 13次元/
  DimensionResult/QAIssue/GateDecision/EvidenceAssessment/SourceInfo・reason code
  語彙約50固定）、policy.py（TrustPolicy name＋version・GENERIC/DAILY_MARKET v1・
  version上書き拒否registry）、dimensions.py（純関数評価器: provenance/source品質/
  死活と文書有効性の分離/freshness＋horizon/日付品質/hash完全性/改定・撤回（明示
  evidenceのみ）/転載検知/数値sanity（NaN・不可能負値・異常%・通貨不整合。補正なし）/
  正規化品質/利用権利）、gate.py（FAIL→REJECT等の明示合成規則）、assess.py
  （record種別別評価＋依存伝播: 上流REJECT→下流LIMITED（自動削除しない）・
  corroboration独立性=転載10件≠独立10source）、store.py（append-only assessment
  履歴・latest_for導出）、report.py（品質メトリクス集計＋人間可読レポート。
  Black Box判定禁止）。
- `core/contracts.py`: EvidenceAssessmentRepository Protocol追加。
- `tests/intelligence/`: qa_fixtures.py（監督者指定synthetic fixture一式）＋
  QAテスト49件（documents 17/statements 12/observation 11/policy・store・report 9）。
- `docs/evidence_qa/`: EVIDENCE_QA_ARCHITECTURE / TRUST_POLICY_SPEC /
  EVIDENCE_GATE_RULES / CONFLICT_REVISION_POLICY / QUALITY_METRICS_SPEC。

## v4.16 (2026-08-30) — Phase 1-D: Normalization & Evidence Creation

異種Raw data（RSS2/Atom/RDF/JSON/tank記事）を共通domain語彙へ変換する
NORMALIZED EVIDENCE LAYER。RAW/PARSED/NORMALIZED/INTERPRETEDの層分離を確立し、
**正規化は完全決定論**（LLM・現在時刻・乱数・外部検索へ非依存。処理時刻は
NormalizationEventのみが保持）。自由文Fact生成はP1-E対象のため未実装（禁止遵守）。

### 追加

- `src/intelligence/normalization/`（新パッケージ・1機能=1ファイル×9）:
  model.py（NormalizationStatus/Issue/Event/Result・決定論的doc ID導出）、
  text.py（NFC・entity・空白のみ。意味変更/翻訳禁止・content_fingerprint）、
  dates.py（published_raw/parsed/inferred/quality分離・URL日付の決定論推定・
  基準時刻=retrieved_atで現在時刻非依存・unknown許容）、language.py（BCP-47系・
  不明はund）、units.py（pct/bps/ratio明示変換・unit無視同一視の拒否）、
  feed_normalizer.py（RSS2/Atom/RDF共通entry→SourceDocument・決定論的revision判定）、
  observation_normalizer.py（JsonProviderSpec宣言mapping・parse_float=Decimal・
  raw/derived区別・決定論的obs ID）、store.py（data/vnext/normalized/ JSONL・
  append-only・冪等・crash-safe）、tank_article_normalizer.py（tank記事互換。
  INTERPRETED系フィールドは意図的に不採用）。
- `src/intelligence/ingestion/auth.py`＋UrllibTransport注入フック
  （監督者DESIGN CORRECTION 1: SECRET MUST NEVER BE PERSISTED≠NEVER BE USED。
  ephemeralヘッダのみ・永続経路ゼロをテストで検証）。
- `src/intelligence/sources/model.py`: SourceDocumentへP1-D正規化フィールド10件を
  0.x非破壊追加（canonical_locator/guid/published_raw/date_quality/published_inferred
  /published_inferred_from/content_fingerprint/media_type/normalizer_name/version）。
- `core/contracts.py`: SourceDocumentRepository / ObservationRepository /
  NormalizationEventRepository Protocol追加。
- `tests/intelligence/`: normalization系＋auth 53件（text/lang 7・dates 9・
  feed_normalizer 11・observation/units 13・store 5・tank互換 5（実shard sample検証
  含む・clone不在環境ではskip）・auth 3）。
- `docs/normalization/`: ARCHITECTURE / SOURCE_DOCUMENT_SPEC / DATE_NORMALIZATION_SPEC /
  OBSERVATION_NORMALIZATION_SPEC / NORMALIZATION_INVARIANTS（N1〜N17）。
- `docs/sources/SOURCE_GAPS.md`: SOURCE_GAP/CONNECTIVITY TRACK（G1〜G8。
  P1-D以降のblockerにしない別管理）。

## v4.15 (2026-08-30) — Phase 1-C: Raw Ingestion

外部Sourceの取得情報を「改変・要約・AI解釈する前のRAW SOURCE EVIDENCE」として
安全・再現可能・追跡可能に保存する層。**RAW DATA IS IMMUTABLE**（同一URLの内容更新は
新RawItemとして積み、旧版を消さない）。P1-D正規化・Fact抽出・LLM処理は未着手。

### 追加

- `src/intelligence/ingestion/`（新パッケージ・God Fetcher禁止の8分割）:
  model.py（FetchRequest/FetchResponse/FetchAttempt。資格情報ヘッダを型レベル拒否）、
  transport.py（HttpTransport Protocol＋stdlib urllib実装・redirect chain記録・
  エラー分類・redact_url）、fetcher.py（retry方針: timeout/5xx/429のみ・Retry-After尊重・
  指数backoff・最大3試行、conditional GET=Attempt列からの導出、source isolation）、
  raw_store.py（content-addressed blob＋JSONL。atomic write・冪等・crash-safe・
  hash検証。RawRepository/FetchAttemptRepository充足）、feed_parser.py（tank移植＋
  RDF対応追加。RSS2/Atom/RDF/JSON/HTML検出・正規化前entry無損失抽出・encoding多段解決）、
  url_normalize.py（tank移植。original URL必須保持）、date_quality.py（source提供/
  naive/欠損の分類のみ。補正しない）、dedup.py（exact hash/canonical URL/GUIDのみ）、
  live_validation.py（監督者指定11ソースの最小live検証。Actions実行用）。
- `src/intelligence/sources/model.py`: RawItemへendpoint_id/encoding/fetch_attempt_id
  追加、SourceEndpointへendpoint_id（content-addressed自動導出）追加（0.x非破壊）。
- `core/contracts.py`: RawRepository / FetchAttemptRepository Protocol追加。
- `.github/workflows/p1c-live-validation.yml`: feature branch限定・triggerファイル
  更新時のみ・contents:read・Secrets不使用の最小live検証（監督者承認のlive validation
  gates対応。Legacy本番workflowとGitHub Pagesは無変更）。
- `tests/intelligence/`: ingestion系テスト65件（model 7/raw_store 7/feed_parser 20/
  fetcher 13/url_normalize 5/date_quality 5/dedup 4/live_validation 4）。
  すべて注入transportによる完全オフライン。
- `docs/ingestion/`: RAW_INGESTION_ARCHITECTURE / FETCHER_CONTRACT /
  RAW_STORAGE_SPEC / PARSER_ADAPTER_SPEC / LIVE_VALIDATION_REPORT。

### 改善

- **最小live validation実施**（GitHub Actions runner・監督者承認gates・計14リクエスト・
  Secrets不使用）: CORE実接続確認 boj_whatsnew/dmb_ecb_press=HEALTHY、theverge=Atom実証、
  fed_press=本体稼働確定（Legacy CI失敗はクライアント条件=UAと確定）。
- `source_feeds.yaml` **v3.0.1**: live実測13ソースのcurrent_healthを更新
  （healthy 20/degraded 1/dead 8/unverified 55/auth 2、CORE 7→5）。歴史レイヤー不変。

### 修正

- live実測によるDEAD確定5件を反映: dmb_boj_whatsnew・mof_whatsnew・jp_mof_press
  （**MOF公式RSS全滅＝一次情報空白**）・jp_stat_release・uk_gov（各replacement明示）。

## v4.14 (2026-08-29) — Phase 1-B: Source Registry & Health Audit

全86ソースの実用性監査。**HISTORICALLY_OBSERVED ≠ CURRENTLY_HEALTHY** の分離を
カタログ構造とテストで機械強制。Legacy挙動無変更・P1-C ingestion未着手・
bulk取得/LLM呼出/DB runtimeなし。

### 追加

- `src/intelligence/sources/model.py` 拡張: SourceCategory / HealthState / AuthType /
  FeedFormat / UsageStatus enum＋`SourceEndpoint`（取得口）/`SourceHealthObservation`
  （死活観測の時系列レコード・tz-aware必須・Secret保持不能）。God object化を回避し
  Source（identity）と分離。serialization登録済み。
- `src/intelligence/sources/health_check.py`: transport注入式の死活チェッカー
  （判定表: HEALTHY/DEGRADED/AUTH_REQUIRED/RATE_LIMITED/MOVED/DEAD/UNVERIFIED、
  形式判定 classify_format、鮮度抽出、現在状態の導出）。開発環境はegress遮断のため
  live実行不能だが、ネットワークのある環境でそのまま実行可能な形で提供。
- `docs/sources/`: SOURCE_REGISTRY_SPEC / SOURCE_HEALTH_AUDIT（86ソース監査結果:
  HEALTHY18・DEGRADED3・AUTH2・DEAD3・UNVERIFIED60）/ SOURCE_CLASSIFICATION
  （tier×投資価値×役割の3軸、CORE7・重複7グループ、P1-Cアダプタ形式一覧）/
  SOURCE_FAILURE_POLICY（役割別障害時挙動の設計。実装はP1-C以降）。
- `tests/intelligence/`: test_health_check.py（22件・全状態オフライン検証）＋
  test_source_registry.py（12件・カタログ整合性/歴史・現在分離/CORE要件/重複/
  Secretなし/roundtrip）。

### 改善

- `knowledge/source_reliability/source_feeds.yaml` を **v3.0.0** へ再構成:
  endpoint / historical（tank実績を隔離保持）/ recent_ci（Legacy CI日次レポート
  14日実測 2026-08-16..29）/ current_health（導出値・根拠method付き）/
  investment_value / role / duplicate_group の層構造。86ソース・実績データは
  欠落なく引き継ぎ。CI実測により恒常失敗6ソースを確定（DEAD3・DEGRADED3）。

### 修正

- `source_feeds.yaml` の `marketwatch_market` URLをLegacy collectors実体
  （realtimeheadlines）へ訂正（旧値はurl_corrected_fromで保持）。

## v4.13 (2026-08-29) — Phase 1-A: Evidence Schema & Provenance（vNext schema 0.2.0）

Phase 1認可を受けたP1-A実装。Evidence First Architectureの正式ドメインモデルを構築
（Stage 1.7の履歴rewriteはMAINTENANCE TRACKへ分離・成果物保持）。
Legacy挙動無変更・P1-B未着手・live取得/LLM呼出/DB runtimeなし。

### 追加

- `src/intelligence/core/`: time.py（tz-aware強制・時刻5種の分離）、ids.py（ULID＋
  content-addressed＋slugの使い分け）、serialization.py（`_type`タグ付きJSON往復・
  Decimal文字列化・float全面拒否）、types.py 0.2.0（VerificationState/Direction新設、
  旧EvidenceRecord等を廃止しドメインへ再配置）、contracts.py更新（新型対応・UTC暦日契約）。
- `src/intelligence/sources/model.py`: Source / RawItem / SourceDocument
  （content-addressed ID・tierスナップショット・revision_of）。
- `src/intelligence/market/model.py`: Observation（Decimal必須・raw/derived・
  派生inputs provenance・改定は新レコード）。
- `src/intelligence/evidence/`: model.py（Fact/Analysis/ForecastStatement分離・
  ForecastMetadata・EvidenceLink many-to-many）、invariants.py（UNSUPPORTED検出・
  CONFLICTING導出・分析トレース）、jsonl_store.py（参照実装ストア・重複ID規約）。
- `tests/intelligence/`: evidence_fixtures.py（指示の10 syntheticケース＋因果チェーン）＋
  新テスト70件（domain 25/serialization 38/store 7）・contracts書換8件・境界検査を
  vNext全域ベンダー中立へ拡張。**総計553 passed**（Legacy 451＋vNext 102）。
- `docs/evidence/`: EVIDENCE_DOMAIN_MODEL / PROVENANCE_MODEL / EVIDENCE_INVARIANTS /
  STORAGE_DECISION（JSONL正本＋再構築可能SQLite索引の方針）。

## v4.12 (2026-08-29) — Rebuild Stage 1.7: Confidential History Remediation（準備完了・push保留）

承認A〜Dに基づく履歴除去の実行段。PRE-FLIGHT→原本安全確認（3系統MD5一致）→
ローカルmirror/bundleバックアップ→DRY RUN（444コミット保持・対象12パスのみ除去・
featureブランチツリーはバイト同一・rewrite後クローンで492 passed）まで完了。
**force pushのみ実行環境の権限ブロックにより保留**（迂回せず停止。再開手段を文書化）。

### 追加

- `docs/security/HISTORY_REMEDIATION_EXECUTION.md`（新規）: 実行記録・EXECUTION GATE
  停止事由・再開手段・rewrite後ブランチ戦略・コラボレータ影響・組織ガバナンス注記。
- `docs/security/POST_REWRITE_VERIFICATION.md`（新規）: フレッシュクローン検証手順・
  GitHub残存リスク（dangling object/キャッシュ/Support依頼の要否）・フォローアップ。
- `docs/security/history_rewrite.sh`（新規）: 検証つきrewrite実行スクリプト
  （フレッシュミラー→filter-repo→検証→レース検査→force push→リモート検証。冪等）。

### 改善

- `.github/workflows/daily-market-brief.yml`: **Security Guardステップを追加**（承認D。
  機密ファイルがtrackingされた場合、レポート生成前にworkflowを失敗させる。
  発効はmigration merge後）。
- `docs/security/SECURITY_REMEDIATION_PLAN.md`: 承認事項A〜Eの決定・実施状態を反映。
- `docs/security/GIT_HISTORY_EXPOSURE_AUDIT.md`: DRY RUN結果とリモート未反映状態を追記。

## v4.11 (2026-08-29) — Rebuild Stage 1.6: Security & Data Governance Remediation

監督指示（SECURITY_GATE）に基づく是正。履歴書き換え・rotation・大量削除は未実施
（計画のみ作成し承認待ち）。Legacy本番の実行時挙動は無変更。

### 追加

- `docs/security/DATA_CLASSIFICATION_POLICY.md`（新規）: PUBLIC〜SECRETの5分類＋
  SENSITIVE_IDENTIFIER。Git/公開/クラウド/LLM送信/ログ/派生データの可否マトリクスと
  Secret取り扱い規則（ヘッダ認証必須・redaction・クエリ文字列禁止）。
- `docs/security/CONFIDENTIAL_RESEARCH_POLICY.md`（新規）: 羅針盤PDF等
  CONFIDENTIAL_SOURCEの正式ルール（public repo/Pages/外部アップロード禁止・
  LLM送信は明示承認制・派生は抽象化物のみGit可）と8月PDF受け入れ手順。
- `docs/security/GIT_HISTORY_EXPOSURE_AUDIT.md`（新規）: 完全履歴437コミットの実測監査。
  PDFは単一コミット`128f4b9`で追加・タグ/リリース/LFS/Pages/Actions artifactへの混入なし。
  **Secretパターン履歴スキャン2,368blob=0件、tank側キー値流出=0件（ROTATION不要）**。
  ※shallowクローン起因の「51コミット」誤認を訂正。
- `docs/security/SECURITY_REMEDIATION_PLAN.md`（新規）: filter-repo手順・Private化代替案・
  output/ cleanup計画・承認待ち事項A〜E。
- `tests/intelligence/test_confidential_guard.py`（新規5件）: tracked PDFゼロ検査・
  research配下README限定・check-ignore実地検証・識別子ファイル非tracking・
  vNextコードの機密パス参照禁止（strict・Legacy例外なし）。

### 改善

- `.gitignore`: `date/rashinban/*.pdf`・Cloudflare識別子2ファイルを保護対象に追加。
- 羅針盤PDF 10冊を`research/source_docs/compass/`へ複製（MD5検証済み・git非管理）の上、
  `date/rashinban/*.pdf`と識別子2ファイルの**Git trackingを解除**
  （ディスク上のファイル・履歴内blobは保持。履歴除去は承認待ち）。
- `date/rashinban/README.md`: セキュリティ通知と復元手順を追記。
- `tests/intelligence/test_knowledge_assets.py`: Secret検査パターンに
  Subscription-Key=/appId=（クエリ文字列鍵）を追加。

## v4.10 (2026-08-29) — Rebuild Stage 1.5: 2旧プロジェクト横断監査と選択的移行

article-intelligence-data-tank（GitHub public・READ ONLYクローン）とdaily-market-briefを
横断監査し、資産の取捨選択（REUSE/MIGRATE/REWRITE/REFERENCE_ONLY/ARCHIVE/DISCARD）を確定。
安全な知識資産のみvNextへ移行した。Legacy本番・tankリポジトリはともに無変更。

### 追加

- `docs/rebuild/CROSS_REPO_ASSET_AUDIT.md`（新規）: tank全26モジュール監査
  （記事モデル約70フィールド・feed_parser優位・**CLI起動不能バグで5週間停止中**等の
  重大所見T1-T7）、dmbとの重複能力比較とCanonical決定、セキュリティ所見。
- `docs/rebuild/ASSET_SELECTION_MATRIX.md`（新規）: 約70資産群の横断分類。
  Phase 1-2コード母体=tank系、市場データ/スケジューラ/配信=dmb系、知識正本=knowledge/。
- `docs/rebuild/HISTORICAL_DATA_INVENTORY.md`（新規）: 過去データ全実測
  （tank記事3,056件 2026-06-22..07-22、dmbレポート59日分、journal 5件、theme_learning 0件等）。
- `docs/rebuild/VNEXT_RECONCILIATION.md`（新規）: Stage 1基盤のKEEP/CHANGE/ADD/
  REMOVE_LATER再評価。core契約・パッケージ構成はKEEP確定。
- `docs/rebuild/RASHINBAN_INVENTORY.md`（新規）: 羅針盤PDFのファイルシステム実測棚卸し
  （6月9冊＋7月1冊=10冊・全てpublicリポジトリにtracked、**8月分0冊**→Phase 0.5継続BLOCKED。
  public露出の解消は要承認事項として整理）。
- `research/source_docs/compass/README.md`（新規）: 8月PDFの安全な受け渡し手順
  （PDF本体は.gitignoreで保護しコミット不能に）。

### 改善

- `knowledge/source_reliability/source_feeds.yaml` v2.0.0: tank `config/sources.yaml`
  （70ソース・source_class/country/trust_score等）を正として統合、dmb固有16件を追加
  （計86件）。tank記事ストア実測により**42ソースをverified化**（観測記事数付き）。
- `knowledge/theme_relations/themes.yaml` v1.1.0: tankテーマ語彙45スラッグとの対応表
  （en_aliases 25件・unmapped 20件）を追加。
- `tests/intelligence/`: en_aliases整合テスト追加・URL検査をhttp(s)許容へ（35→36件）。
- `.gitignore`: `research/source_docs/` 配下を保護（README除く）。

## v4.9 (2026-08-29) — Rebuild Stage 1: vNext骨格＋知識移設（Investment Intelligence OS）

監督承認（LEGACY_AUDIT_APPROVED / GREENFIELD_REBUILD_AUTHORIZED）を受け、
Legacyとは独立した新開発本線 vNext の骨格と知識資産を作成した。
**Legacy本番（main.py・AnalysisBundle・html_builder・CI・Pages・config.yaml）は無変更**。
Phase 1（Source / Evidence Engine）の本格実装は未着手。

### 追加

- `src/intelligence/`（新規）: vNext中核パッケージ。core/types.py（ドメイン型:
  SourceTier/StatementType/Horizon/SourceMeta/ForecastAttributes/EvidenceRecord/
  MarketObservation/LLMResult）、core/contracts.py（Protocol契約: Clock/LLMProvider/
  EvidenceRepository/MarketRepository/NewsRepository/KnowledgeRepository。実装なし・
  LLMはベンダー中立）、および12ドメインパッケージ（責務docstring付き）。
- `knowledge/`（新規）: 旧config.yamlからCOPY+NORMALIZEした知識資産。
  causal_rules（market/rates/fx、全18ルールにID・confidence付与）、
  theme_relations（themes 29件＋durable 7件、theme_graph 37ノード）、
  source_reliability（source_tiers 23件、source_feeds 24本＋方針記録）、
  compass_dna/market_rules.yaml（正本を移設。docs側は凍結注記のみ）。
- `tests/intelligence/`（新規35件）: knowledge YAML検証（パース・メタデータ・
  ルールID横断一意・グラフ参照整合・Tier整合・Secret混入なし）、import境界の
  AST検査（vNext→Legacy禁止・core→ベンダーSDK禁止）、core契約テスト
  （FACT/FORECAST分離の型強制・Protocol実装可能性）。
- `docs/rebuild/STAGE1_VNEXT_FOUNDATION.md`（新規）: 実施記録・正規化判断・リスク。

### 改善

- `.gitignore`: vNext実行時データ `data/vnext/` を非git管理に（Legacy既存パスへ影響なし）。
- `docs/rebuild/MIGRATION_PLAN.md`: Stage 1実施記録を追記。
- `docs/compass_dna/analysis_rules/market_rules.yaml`: 正本移設の凍結注記を追記（内容不変）。

## v4.8 (2026-08-29) — Legacy Audit & Greenfield Rebuild Design（Investment Intelligence OS）

Investment Intelligence OSの方針変更（Brownfield Audit → Selective Migration →
Greenfield Rebuild）に伴い、リポジトリ全資産（Python約25,500行・collectors 30/
analysis 50/report 4系・CI・Pages・Cloudflare・tests 451件・データ資産）を監査し、
再利用判定と新アーキテクチャ・移行計画を設計した（ドキュメントのみの追加。
既存コード・設定・CI・Pagesは無変更）。

### 追加

- `docs/rebuild/LEGACY_AUDIT.md`（新規）: 現状アーキテクチャ・結合・技術的負債・
  危険な前提（src/date死にコピー、羅針盤学習の三重不一致、requirements.txtの
  anthropic欠落、公開リポジトリ内のCloudflare識別子追跡等）・再利用資産・障害の監査。
- `docs/rebuild/REUSE_MATRIX.md`（新規）: 56資産のREUSE/PARTIAL_REUSE/REBUILD/
  REMOVE_LATER/UNKNOWN判定（理由・依存・品質・リスク・推奨アクション付き）。
- `docs/rebuild/TARGET_ARCHITECTURE.md`（新規）: Sources→Evidence→Data Bank→
  Analysis→Reports→API→PWAのデータフロー、14サブシステムの疎結合設計、
  新ディレクトリレイアウト案、FACT/ANALYSIS/FORECASTのデータ所有権規約。
- `docs/rebuild/MIGRATION_PLAN.md`（新規）: 稼働中パイプラインを壊さない
  Strangler方式の5段階移行計画・ロールバック手順・要承認事項一覧。
- `docs/rebuild/REBUILD_ROADMAP.md`（新規）: Phase 0〜12の新アーキテクチャ前提
  タスク分解（Phase順序は不変更・変更案はproposalとして分離）。

## v4.7 (2026-08-28) — Phase 0: Compass DNA解析（Investment Intelligence OS）

Investment Intelligence OS計画のPhase 0として、`date/rashinban/` の
「グローバル投資の羅針盤」10冊（2026/06/18〜07/01・55ページ）を全ページ解析し、
紙面構造・データ分類・分析ルール・テーマ展開・FACT/ANALYSIS/FORECAST分離規約を
リバースエンジニアリングした（ドキュメントのみの追加。既存コード・設定・CIは無変更）。

### 追加

- `docs/compass_dna/COMPASS_DNA_SPEC_v1.md`（新規）: 統合仕様17セクション。
- `docs/compass_dna/MARKET_DATA_TAXONOMY.md`（新規）: CORE/SUPPORT/CONTEXTデータ分類。
- `docs/compass_dna/ANALYSIS_RULE_CATALOG.md`（新規）: 分析ルールカタログ
  （confidence: CONFIRMED/LIKELY/HYPOTHESIS、出典日付・ページ付き）。
- `docs/compass_dna/THEME_DISCOVERY_RULES.md`（新規）: テーマ発火点7類型・展開手順・産業連鎖マップ。
- `docs/compass_dna/REPORT_STRUCTURE_SPEC.md`（新規）: 紙面構造・曜日ローテーション仕様。
- `docs/compass_dna/FACT_ANALYSIS_FORECAST_SPEC.md`（新規）: 三分類の言語仕様とEvidence Engine要件。
- `docs/compass_dna/PHASE0_FINDINGS.md`（新規）: 主要発見10件・欠落ソース報告・Phase 1への示唆。
- `docs/compass_dna/analysis_rules/market_rules.yaml`（新規）: ルールの機械可読サンプル（schema v0.1）。

## v4.6 (2026-07-20) — Rashinban Private Insight Vault（private記事の転送・入力UI・Future Outlook）

レポート画面から気になった記事本文を貼り付けてData Tankの非公開領域へ転送し、
AI分析（要約・所感・因果・市場影響・シナリオ形式の未来予測・検証条件）の
派生情報だけをレポートへ反映する機能。両リポジトリはPublicのため、本文は
Cloudflare Worker + KV（非公開・AES-GCM暗号化）にのみ保存し、GitHub Pages・
公開リポジトリ・公開JSONへは構造的に出ない設計（allowlist方式）。

### 追加

- `cloudflare/private-insight-worker.js`（新規・既存trigger-report-workerとは別モジュール）:
  Private Intake API。POST /intake（保存）、GET /status・/list、POST /delete・/memo・
  /reanalyze（人間向け・X-Insight-Keyパスフレーズ認証）、GET /queue・POST /analysis・
  GET /derived（機械向け・Bearer認証）、GET /admin（認証付き管理画面）。
  本文はAES-GCM暗号化してKVへ保存。レート制限・ハッシュ重複検知つき。
  Secrets（パスフレーズハッシュ・トークン・暗号鍵）はWorker Secretのみで、HTMLへは埋め込まない。
- `cloudflare/private-insight-wrangler.toml.example`: KV binding・Secrets設定手順。
- `src/data/private_insight_client.py`（新規）: 派生情報の取得クライアント。
  `config.private_insight_intake.api_url` とSecrets `INSIGHT_API_TOKEN` の両方が
  揃わない限り**完全に無効**（ネットワークアクセスなし）。失敗時はunavailableを返し
  例外を投げない（レポート生成は止まらない）。
- `src/report/html_builder.py`: 「🧠 Rashinban Private Insight Vault」入力カード
  （本文textarea＋パスフレーズpassword欄＋転送ボタン。送信失敗時は本文を画面に保持、
  成功時のみクリア。localStorage下書き保存）と「🔮 Private Research Future Outlook」
  カード（シナリオ・確認指標・次回検証日・AI所感。取得失敗時は注記のみ表示で
  レポート本体は通常生成）を追加。
- `src/analysis/models.py`: `PrivateInsightOutlook` dataclassと
  `AnalysisBundle.private_insight_outlook`（デフォルトNoneで後方互換）。
- `main.py`: `_safe_call`経由で派生情報取得を配線（失敗してもレポート継続）。
- `config.yaml`: `private_insight_intake:` ブロック（enabled/api_url/max_body_chars等。
  api_url空文字がデフォルト＝機能オフ）。
- `.github/workflows/daily-market-brief.yml`: `INSIGHT_API_TOKEN` Secretのenv渡しを追加。
- `tests/test_private_insight_vault.py`（新規11件）: クライアントの
  disabled/ok/unavailable、入力カードのSecret非埋め込み、Outlookカード、
  フルレポート互換を検証。

### pytest

451 passed（既存440＋新規11）。

## v4.5 (2026-07-20) — 通信社系接頭辞をまたぐ重複ニュースの排除

ライブ運用のレポートで、同一記事を別媒体が配信し片方だけに "Analysis:" が付く
ケース（例:「Could AI chip boom make ASML…」と「Analysis:Could AI chip boom
make ASML…」）が重複排除をすり抜け、Executive Summary・重要ニュースランキング・
岡三ストラテジスト視点に同じニュースが2件並んでいた。見出し正規化に通信社系
接頭辞の除去を追加して解消した。

### 変更

- `src/collectors/news.py`: `_normalize_title`の先頭処理に`_strip_wire_prefix`を追加。
  Analysis / Exclusive / Breaking / Factbox / Explainer / Column / Insight /
  Timeline / Opinion / Feature / UPDATE N- / WRAPUP N- / RPT / REFILE /
  Live markets / Live / Graphic、および日本語（速報／独自／焦点／コラム／特集／
  解説／分析）の接頭辞を1回だけ剥がしてから正規化する。剥がすと空になる異常
  見出しは元のまま扱い、誤統合を防ぐ。この正規化はニュース収集の重複排除と
  Data Tankシグナルのタイトル照合の両方で共通に使われるため、Tank由来・
  既存RSS由来をまたぐ重複にも一貫して効く。
- `tests/test_collectors.py`: Analysis接頭辞・UPDATE/日本語接頭辞をまたぐ統合、
  接頭辞のみ見出しの非空保証を検証するテストを3件追加。

### pytest

440 passed（既存437＋新規3）。

## v4.4 (2026-07-20) — 情報の整理＋コンパクト表示の最適化

ライブ運用のレポートで確認された表示ノイズ（主要因への無関係な単発記事の混入・
テーマ集計最上位のuncategorized 614件）を整理し、コンパクト表示を「重要度の低い
カードだけを自動で畳む」動作に最適化した（重要なものは常に見える）。

### 変更

- `src/report/html_builder.py`（①情報整理）:
  - `_ext_intel_cluster_list_html`: importanceが0かつ関連記事1件のエントリ
    （スコア未計算の旧データ・単発の無関係記事）を表示から除外。有意なエントリが
    無ければ見出しごと非表示。
  - `_ext_intel_theme_summary_html`: "uncategorized"を表示から除外
    （Tank側v0.5.0でも集計から除外するが、旧Packageへの防御として表示側でも弾く）。
- `src/report/html_builder.py`（②コンパクト表示の最適化）:
  - `_card`: 重要度（★×20）を`data-imp`属性としてカードへ付与
    （★の無いトップサマリー＝相場総括・Today's Decision等には付与しない）。
  - コンパクト表示ON時、重要度60以下のカードを自動で折りたたむ
    （80〜100と★無しカードは開いたまま＝重要なものは常に表示）。自動で畳んだ
    カードはOFF時に開き直す（元から畳んである営業メモ等はそのまま）。畳まれた
    カードも▾ボタンで個別に開ける。
  - コンパクト表示中はカード説明文（card-desc）も非表示にして情報密度を上げる。
- `tests/test_v4_external_intelligence.py`: ノイズ除去・uncategorized除外・
  data-imp属性・コンパクト折りたたみスクリプトの存在を検証するテストを4件追加。

### 関連: Article Intelligence Data Tank v0.5.0（別リポジトリ）

主要因のimportance全0.00の根本原因（記事スコア未計算）はTank側v0.5.0で修正。
詳細は当該プロジェクトのCHANGELOGを参照。

### pytest

437 passed（既存433＋新規4）。

## v4.3 (2026-07-20) — Tankの市場反応スコアをニュースランキング・ストラテジスト採点へ統合

Data Tank側は各記事について「どのイベントクラスタに属するか」「そのイベントで
実際に市場が動いたか（market_reactions）」「市場影響度スコア」まで計測済みだが、
これまでbrief側の採点（重要ニュースランキングの★・岡三ストラテジスト視点の8軸）には
一切使われていなかった。本バージョンで、この計測済みシグナルを採点へ機械的に
転記する（brief側での再計算・生成はしない。Tank未接続時は従来と完全に同じ採点）。

### 変更

- `src/analysis/external_intelligence.py`: `build_tank_signal_lookup()`を追加。
  hot_articles を「タイトル正規化キー（news._normalize_title と同一）→
  has_market_reaction / in_global_drivers / market_impact_score / importance_score」の
  ルックアップへ変換する。既存の重複判定と同じ正規化を使うため、Tank由来でも
  既存RSS由来でも「同じニュース」なら同じキーで引ける。
- `src/analysis/news_ranking.py`: `build_news_ranking(..., tank_signals=None)`を追加。
  一致した見出しへ「実際の市場反応が確認済み: +3（Market Reaction First）／
  主要因クラスタ該当: +2／市場影響度スコア0.6以上: +1」を加点し、理由文にも明記。
- `src/analysis/strategist_engine.py`: `score_headline_8axis(..., tank_signal=None)`・
  `build_strategist_views(..., tank_signals=None)`を追加。8軸の「市場インパクト」を
  市場反応確認済み+2／主要因該当・高影響度+1し、確認済みの場合はストラテジストの
  見方に「相場への影響が既に現れている可能性」の一文を補足（他の7軸は不変）。
- `main.py`: `build_tank_signal_lookup`を`_safe_call`で呼び、news_ranking・
  strategist_engine の両方へ`tank_signals`を配線。取得失敗時は空dict＝従来動作。

### pytest

433 passed（既存427＋新規6）。

## v4.2 (2026-07-20) — Data Tankの精査済み結果（主要因・リスク・テーマ集計）を表示

Data Tank側は既に記事のクラスタリング・市場反応評価・重要度スコアリングまで
済ませた`global_drivers`（Market Reaction First順の主要因）・`risk_radar`・
`theme_summary`を配信パッケージに含めている。これまではExternal Intelligenceカードに
件数しか表示していなかったが、この精査済みの中身（タイトル・関連記事数・
importance・関連国）を実際に読み取って表示するようにした。daily-market-brief側で
再計算・再ランキングは行わず、Data Tank側の結果をそのまま表示する（重複計算をしない）。

### 変更

- `src/report/html_builder.py`: `_ext_intel_cluster_list_html()` /
  `_ext_intel_theme_summary_html()`を追加。External Intelligenceカードに
  「Data Tank発の主要因」「Data Tank発のリスクレーダー」「Data Tank発のテーマ集計」の
  3リストを追加表示（各上位5〜8件。Tank側のランキング順をそのまま使用）。
  bundleがNone、またはリストが空の場合は何も追加表示しない（既存動作に影響なし）。
- `tests/test_v4_external_intelligence.py`: 上記3リストの表示内容・空リスト時の
  非表示・bundle=None時の空文字返却を検証するテストを3件追加。

### pytest

427 passed（既存424＋新規3）。

## v4.1 (2026-07-20) — External Intelligence 段階的接続（hot_articlesをニュースパイプラインへ合流）

v4.x で追加したConsumer Client（取得・表示のみ）を一歩進め、Data Tankの
`hot_articles`（allowlist済みの公開ビュー）を既存のニュース収集パイプラインへ
実際に合流させた。大規模リファクタリングは行わず、既存の`news.dedupe_headlines`
（タイトル正規化ベースの重複排除）へそのまま乗せる形で接続している。

### 変更

- `src/analysis/external_intelligence.py`: `hot_articles_to_headlines()`を追加。
  Data Tankのhot_articles（title/url/source/published_at/source_trust）を
  既存の`Headline`（`src/collectors/news.py`）へ変換する。`source_trust`
  （0.0〜1.0）をそのまま`reliability`として引き継ぐため、既存RSSと同じ
  ニュースをData Tankも配信していた場合は信頼度の高い方へ自動的に統合される。
  本文（public_excerpt等）はHeadlineに保持フィールドが無いため引き継がない
  （構造的に本文が混入しない）。
- `main.py`: Data Tankの取得・bundle化を既存ニュース収集の直前へ移動し、
  変換したHeadlineを`raw_headlines`（重複除去前）へ合流させた（重複取得は
  行わない・取得失敗時は空リストのままで既存動作に影響なし）。
- `src/report/html_builder.py`: 「External Intelligence（Data Tank連携）」カードの
  説明文を、実際の接続状況に合わせて更新（「参考情報として表示するのみ」→
  「重要ニュースランキング・テーマ分析等へ合流」）。
- `tests/test_v4_external_intelligence.py`: `hot_articles_to_headlines`の
  フィールド変換・欠損データのスキップ・信頼度デフォルト値、および既存
  `dedupe_headlines`との統合（重複ニュースの統合・非重複ニュースの共存）を
  検証するテストを5件追加。

### pytest

424 passed（既存419＋新規5）。

## v4.x (2026-07-17) — External Data Foundation（Article Intelligence Data Tank連携・Consumer Client）

別リポジトリ・別プロジェクトとして新規作成した Article Intelligence Data Tank
（数千〜数万件のニュース記事を取得・分析し、軽量なPublished Intelligence Package
だけを配信する独立基盤）から、Market Intelligence System 側が**軽量なConsumer
Client**だけを追加して接続できるようにした。既存Engineの分析ロジックは一切変更せず、
AnalysisBundleへの追加接続（保持のみ）に留める。Data Tank未設定・障害時も
レポート生成は通常通り継続する（完全な後方互換）。

### 追加

- `src/data/external_intelligence_client.py`【新規】: ExternalIntelligenceClient。
  manifest取得→package取得→gzip展開→checksum検証→schema検証→cache保存→
  timeout/retry→stale判定→fallback、を行う薄いクライアント。manifest_url/
  package_url未設定なら即座にdisabled（ネットワークアクセスなし）。
- `src/analysis/external_intelligence.py`【新規】: package/statusから
  `ExternalIntelligenceBundle`を組み立てる（Market Intelligence側で件数上限を
  再度防御的にキャップ）。
- `src/analysis/models.py`: `ExternalIntelligenceBundle`データクラス追加、
  `AnalysisBundle.external_intelligence`（デフォルトNone・後方互換）を追加。
- `src/report/html_builder.py`: 「External Intelligence（Data Tank連携）」カードを
  追加（取得状況のみ表示・記事本体は転載しない。bundle未設定/Noneなら空文字＝
  従来通り）。
- `config.yaml`: `external_intelligence`ブロック（enabled/manifest_url/package_url/
  timeout_seconds/retry_count/latest_minutes/warning_minutes/stale_minutes/
  cache_enabled/cache_dir/fallback_to_cache/fallback_to_legacy_news）を追加。
  URL空欄の間は完全に無効化され、既存動作に一切影響しない。
- `main.py`: `ExternalIntelligenceClient`の呼び出しを`_safe_call`で追加し、
  `analysis_bundle.external_intelligence`へ格納するのみ（既存Engineの入力には
  まだ使わない・将来の段階的接続の基盤）。
- `tests/test_v4_external_intelligence.py`【新規】: manifest/package取得・
  checksum/schema検証・latest/warning/stale判定・timeout/retry・cache更新/
  fallback・legacy fallback・URL未設定時の後方互換・Data Quality表示・
  件数上限・既存pytest互換など16件。

### 関連: Article Intelligence Data Tank（別リポジトリ・別納品物）

`article-intelligence-data-tank/` として独立プロジェクトを新規作成（本リポジトリの
配下ではない）。記事取得・正規化・重複排除・分類・イベント統合・市場影響分析・
永続保存・配信パッケージ生成を担う。詳細は当該プロジェクトの README.md /
CHANGELOG.md を参照。

### pytest

419 passed（既存403＋新規16）。

## v4.x (2026-07-14) — Six Daily Report Schedule & Reliability Upgrade（1日6回・信頼性運用）

レポートをJST基準で1日6回（07:30/09:10/11:30/12:40/15:40/17:20）自動生成する信頼性運用の
基盤を追加。通常6回＋各15分後の欠損回復チェック6回をGitHub Actionsに設定し、実行記録・
二重生成防止・自動再試行・欠損回復・履歴保存・生成状況HTML表示を実装。既存の手動実行・
Cloudflare Workerワンタップ・GitHub Pages公開・既存レポート生成は一切壊さない。

Phase 0（既存構造の調査）
- schedule cron はUTC・単発（"0 22 * * *"）。main.py は output.timezone(Asia/Tokyo)で now を
  算出。build_html_report はトップカード群を組み立て、latest_market_brief.html を output/ へ出力し、
  workflow が pages-site/index.html へコピーして GitHub Pages 公開。Cloudflare Worker は inputs 無しで
  workflow_dispatch する（→ 追加 inputs は全て default 必須）。

追加（新規ファイル）
・src/analysis/report_schedule.py【新規】— JST/UTC変換、通常/回復cron生成、cron→(slot_id,mode)対応、
  直前slot解決、実行記録(data/report_runs/YYYY-MM-DD.json)のatomic読み書き、二重生成防止・stale判定、
  HTML用スロット状態算出。純粋ロジック（副作用は記録の読み書きのみ）。
・src/report/schedule_status.py【新規】— 「本日のレポート生成状況」カード（6スロット・現在表示中・
  欠損警告）をHTML化する純粋関数。データ無しなら空文字。
・scripts/resolve_report_schedule.py【新規】— GitHub Actionsでcron文字列/dispatch入力から
  (slot_id,mode,trigger_type,force,recovery)を解決しGITHUB_OUTPUTへ書く。巨大シェルif文を回避。
・tests/test_v4_report_schedule.py / tests/test_v4_schedule_main.py【新規】— §19のテスト31件。

改善（既存ファイル・最小差分・後方互換）
・main.py — CLI引数 --report-slot/--trigger-type/--force/--recovery を追加（省略時は従来の臨時生成で
  スケジュール管理に一切関与しない＝完全な後方互換）。スロット指定時のみ: 二重生成防止判定→
  runningで記録開始→生成→HTML妥当性チェック→最新indexをatomic更新（不正時は前回版を維持）→
  履歴HTML保存→success/failedを生成メタデータ付きで記録。生成状況カードのコンテキストをHTMLへ渡す。
・src/report/html_builder.py — build_html_report に schedule 引数（省略可）を追加し、トップに
  生成状況カードを描画（未指定なら空文字＝従来通り）。カード用CSSを追加。
・config.yaml — report_schedule ブロック（enabled/timezone/run_on_weekends/run_on_japanese_holidays/
  archive_reports/recovery_enabled/max_retry_count/retry_wait_seconds/stale_after_minutes/
  recovery_offset_minutes/runs_dir/history_dir/slots×6）を追加。
・.github/workflows/daily-market-brief.yml — 通常6cron＋回復6cronを設定。workflow_dispatch に
  report_slot(choice,default auto)/force/recovery(default false) を追加（inputs無しdispatchでも動作）。
  concurrencyでslot単位に直列化(cancel-in-progress:false)。slot解決ステップ→最大2回の自動再試行→
  自動生成ファイルのみcommit(force pushなし・pull --rebaseで競合回避)→履歴もpages-siteへ同梱。

制約遵守
・新規ニュース取得・新しい外部API・生成AI文章生成・World/Geopolitical Engine・大規模UI再設計・
  分析ロジックのリファクタは一切なし。Secret/Tokenはログ・HTML・JSへ出さない。
・JST基準を厳守（cron時刻からJST日付を推測しない）。

テスト: 403 passed（既存372＋新規31）。

## v3.6 (2026-07-09) — Strategic Narrative Engine「朝会3分・トップストラテジスト級」化

v3.5.3で方向整合は取れたが、Market Narrativeを「証券会社トップストラテジストが朝会で3分説明する
レベル」に引き上げる。新Engine（Strategic Narrative）のみを強化し、既存Engineは変更しない。
新しいニュース取得・新しいAPI・生成AIによる推測・断定的な将来予測・個別売買助言は一切行わず、
既存の算出済みエンジン結果だけを機械的に組み替える。既存データのみ・後方互換・最小差分・pytest全通過。

Phase 0分類
- A（既存で十分・再利用）: Market Data / Market Regime / Cross Market / News Ranking /
  News Impact / Future Intelligence / Theme Momentum / Scenario / Market Breadth /
  Analysis Confidence / Macro Events(Weekly Events) / Watchlist。
- B（少し直せば使える＝今回）: strategic_narrative.py（市場心理・主因ランキング・総括・
  30秒・因果チェーン・自己評価を強化）と html_builder.py の描画。
- C（新規追加）: StrategicNarrative に deep_causal_chain / key_points / self_score /
  self_check / self_improvement フィールドを追加。
- D（やらない）: 生成AI作文／新規データ取得・新API／個別寄与額の捏造／既存Engine変更／大規模リファクタ。

改善内容（①〜⑨）
・① 原因の原因まで遡る因果チェーン `deep_causal_chain`（ニュース→原油→インフレ→金利→バリュエーション
  →為替→セクター→日経）。取得データで裏付く節・ニュース見出しにある語だけを繋ぐ（推測禁止）。
・② 今日の市場心理を主因ランキング1位のcategory/directionから毎日自動生成（固定文を廃止・主因と必ず一致）。
・③ 主因ランキングを「総合影響度」で決定＝値動き×重み＋News Ranking/Impactの関連件数・最大Impact
  ＋Cross Market登場（`_news_boost`/`_cross_boost`）。★も総合影響度から付与、noteに関連ニュース件数。
・④⑧ ストラテジスト総括を「①何が起きたか②なぜ③何を織り込んだか④想定と違った点⑤明日確認」の
  5部構成・一本のストーリーに（200〜300字目安・テンプレ羅列を排除）。
・⑤ Cross Marketを文章化（何が勝ち何が負けたかを自然文で・矢印羅列でない）。
・⑥ 営業向け30秒を会話調へ（「◯◯にもかかわらず下落」等の逆行を検出し「今後は〜が焦点になります」で締める）。
・⑦ 今日覚えること3つ `key_points`（最大要因／市場参加者が見ていたもの／明日見るべき点）を可視化。
・⑨ ルールベースの自己評価 `self_score`(100点満点)・`self_check`(5観点OK/NG)・`self_improvement`
  (80点未満の改善案)。観点=市場心理と主因の一致／因果チェーンの連続性／背景説明／営業30秒の実用性／ストーリー性。
・HTML描画: 【今日覚えること（3つ）】を可視ブロック追加、詳細に【市場が織り込んだ流れ（原因の原因まで）】と
  【分析セルフチェック（自己評価 N/100）】を追加。strategic_narrative が None の場合は従来表示にフォールバック。

テスト
- 追加: tests/test_v3_6_strategist_grade.py（14件）— 深い因果チェーン／心理と主因の一致・可変性／
  総合影響度加点／5部構成総括／Cross Market文章化／営業30秒の逆行検出／key_points3件／自己評価／
  禁止表現・売買助言なし／空データ安全。
- 既存: v3.5.2/v3.5.3の文言依存アサーション（「ポイント」→「焦点」等）をv3.6の文言へ更新。
- 結果: 372 passed。

## v3.5.3 (2026-07-08) — Strategic Narrative Engine Accuracy Fix（主因・因果・材料分類の矛盾解消）

v3.5.2で文章の形は良くなったが、主因判定・因果・材料分類に矛盾（日経下落なのにSOX上昇を
主因扱い等）が出ていた問題を修正。UIではなく分析ロジックを直し、「市場参加者が何を嫌気し、
何を支えにした結果、日経平均がどう動いたか」が分かる分析へ。既存データのみ・後方互換・最小差分。

Phase 0分類
- A（既存で十分）: Market Regime / Cross Market / News Ranking / News Impact /
  Future Intelligence / Scenario / Weekly Events / Analysis Confidence / Watchlist /
  Market Breadth / Theme Momentum / anomalies（判定材料は揃っている）。
- B（少し直せば使える＝今回）: strategic_narrative.py の材料分類・主因選定・テンプレート
  （形はあるが方向整合が取れていなかった）。
- C（新規追加）: StrategicFactor に direction / category を追加（方向を一意化）。
- D（やらない）: 生成AI作文／新規データ取得／個別銘柄の寄与額の捏造／大規模リファクタ。

修正内容（改善①〜⑬）
・① 日経平均の方向を先に判定（<=-0.5%下落 / >=+0.5%上昇 / それ以外は横ばい）。
・② 各材料を「日経平均にとって」positive/negative/neutral へ分類（金利↑=negative、SOX↑=
  positive、原油↑=negative、円安=positive、VIX20未満=positive/以上=negative 等）。categoryも付与。
・③ 主因ランキングは日経の方向と一致する材料だけから作る（下落日はnegativeのみ／上昇日は
  positiveのみ／横ばいは両方を寄与順）。→ 日経下落日にSOX上昇が主因に入らない。
・④ 押し下げ材料と下支え材料の重複を排除（directionが一意なので同一materialは片方だけ）。テスト追加。
・⑤ 不自然な因果表現を禁止し、安全なテンプレートに統一（「米金利上昇は高PER株の重荷」
  「原油高はインフレ警戒材料」「SOX上昇は半導体の下支え」等）。禁止表現テスト追加。
・⑥ 本日の一言を方向＋主因から生成（下落日「〜が重荷となり、日経平均は下落しました」／上昇日
  「〜が支えとなり、上昇」／横ばい「〜が交錯し、方向感に乏しい」）。
・⑦ 市場心理を金利/NASDAQ・SOX/原油/VIX/決算/AIニュースから、日経方向に最も説明力のある形で選定。
・⑧ 「なぜ日経は動いたか」を段落ロジック化（結果→背景（同方向材料）→一方で（逆方向材料は
  下支え/重荷だが打ち消せず/優勢に））。
・⑨ Cross Marketを力関係で説明（どちらの材料が勝ったか。SOX上昇でも日経下落なら「SOXは支えだが
  金利上昇・米国株安の影響が上回った」と明記）。
・⑩ ストラテジスト総括200〜300字（方向／主因／逆方向材料／市場心理／今後の見るポイント）。
・⑪ 営業向け30秒説明も方向整合（SOX上昇を重荷扱いしない）。
・⑫ 出力構成を整理（一言→市場心理→なぜ動いたか→主因ランキング→押し下げ/下支え→Cross Market
  →シナリオ→総括→30秒→詳細）。
・⑬ テスト追加（下落日SOX上昇=下支え・主因除外／金利上昇=押し下げ／上昇日SOX上昇=押し上げ／
  上昇日原油高=重荷／横ばい交錯／重複なし／禁止表現なし／総括の主因が方向一致／30秒の矛盾なし）。

StrategicFactor に direction / category を追加（デフォルト付き・後方互換）。既存テスト全通過。

## v3.5.2 (2026-07-08) — Strategic Narrative Engine（朝会3分説明レベルへ）

Market Narrative を「材料の羅列」から「証券会社ストラテジストが朝会で3分説明する
レベル」へ引き上げるための新エンジン。UIではなく分析ロジックを追加。既存エンジンを
壊さず、その算出済み結果だけを再利用する（生成AI・断定予測・新規データ取得・捏造・
推測・売買助言は一切なし）。

新規エンジン: src/analysis/strategic_narrative.py（StrategicNarrative / StrategicFactor /
StrategicScenario を models.py に追加）。Market Narrative カードはこのエンジンの出力を
表示するだけ（strategic_narrative未指定なら従来の6部構成にフォールバック＝後方互換）。

改善①〜⑩
・① 「何が起きたか」ではなく「市場が何を織り込んだ結果こう動いたか」を因果で組み立て
  （例: FRB利下げ期待の後退→長期金利上昇→高PER銘柄の割引率上昇→AI半導体に利益確定売り→
  指数寄与度の高い半導体株が日経平均を押し下げ）。金利の方向から機械的に分岐。
・② 【本日の一言】（20〜40字）を先頭に。主因＋日経の方向を一文で。
・③ 【今日の市場心理】をニュース・VIX・金利・Scenario・Market Regime から機械判定。
・④ 【本日の主因ランキング】①②③（寄与度＝|変化率|×重み で順位付け・★＋1行理由）。
・⑤ 【相場を押し下げた材料】【下支えした材料】に分離し、優先度★付きで降順表示。
・⑥ 今後を条件分岐ではなくシナリオA/B/C化（Scenario Engineの配分から確率ラベル高/中/低）。
・⑦ 【なぜ日経平均はこうなったか】を専用ブロック化（日経→寄与度→業種→背景→海外→マクロ
  の順で「原因」まで遡る）。
・⑧ Cross Market を↓羅列ではなく自然な文章に（例: 米金利上昇→ドル買い→円安、通常は輸出株
  の追い風だが今回はSOX急落が円安効果を打ち消した…）。
・⑨ 【営業向け30秒説明】を追加（お客様への第一声テンプレート）。
・⑩ 【ストラテジスト総括】200〜300字（背景・市場心理・一番効いた材料・今後の見るポイントを
  一連の流れで説明）。

再利用した既存エンジン: Market Regime / Cross Market / News Ranking / News Impact /
Future Intelligence / Theme Momentum / Market Breadth / Analysis Confidence / Scenario /
Watchlist / Macro Events(Weekly Events) / Market Data。AnalysisBundle に strategic_narrative
を追加し main.py で配線。既存テストは全通過、pytest追加。

注記: 個別銘柄の「寄与度」の実データ（構成比・寄与額）は取得していないため、SOX等の
セクター指数の動きから定性的に「指数寄与度の大きい半導体・値がさ株」と表現する（具体的な
寄与額・銘柄別数値は捏造しない）。

## v3.5.1 (2026-07-08) — Market Narrative 可読性改善（初心者でも一読で「なぜ」が分かる）

v3.5で新設した相場総括を「材料の羅列」から「初心者でも一読で今日の相場がなぜ動いたか
分かる文章」へ再構成した。分析データは既存のまま（捏造なし・売買助言なし）で、
見せ方と文章構成のみ改善。

追加・改善（src/analysis/market_narrative.py・models.MarketNarrativeSummary・html_builder.py）
・① 今日の結論を冒頭に1〜2文で（例:「本日は『半導体主導のリスクオフ寄り』の相場。
  米金利上昇と半導体株安を背景に、日経平均は下落しました。VIXは20未満で全面的な
  パニックではありません。」）。主因（半導体/金利/為替主導）＋日経の方向＋VIXニュアンスを機械生成。
・② 「なぜ日経平均は動いたか」を米国株→金利→為替→（半導体セクター）→日経 の順で
  ↓チェーン表示。取得できたデータのみで、帰結は必ず日経で締める。
・③ 悪材料 と ④ 支えになる材料 を明確に分離（金利上昇・SOX安・NASDAQ安・原油高＝悪材料／
  円安・VIX20未満・金利低下・テーマ継続・決算イベント＝支援材料）。
・⑤ 今後見るべきポイントを具体的な条件分岐に（SOXが反発するか／米10年金利が◯%台で
  定着するか／VIXが20を超えるか／円安が輸出株を支えるか／今週の決算で見方が変わるか）。
  金利水準は実データの現在値を使用。
・⑥ 見立てを 短期／中期／長期 の3本立てに（各3行以内・断定せず条件分岐・売買助言なし）。
・重複していた「何が起きたか」「主要変化」「主因の詳細」「波及チェーン」「示唆」は
  「詳しく」に集約し、初期表示は①〜⑥に絞って短く。
・MarketNarrativeSummary に conclusion / nikkei_chain / negative_factors /
  supportive_factors / long_term_view を追加（既存フィールドは維持・後方互換）。

やらないこと（継続）: 生成AIの作文／断定的将来予測／個別の売買推奨（買うべき/売るべき）／
取得していないデータの捏造／既存の分析ロジック・エンジンの書き換え。

## v3.5 (2026-07-07) — Market Narrative & Section Pruning Upgrade（相場総括の新設・構成整理）

情報を大量に並べるツールから「今日の相場がなぜ動いたか・背景・今後の見方」を端的に
深掘りできる分析ツールへ寄せた版。最上部に相場総括を新設し、営業系・重複セクションを
整理して「朝3分で本質」を優先した。分析ロジックは変更せず、既存エンジンの算出済み
結果を組み合わせるだけ（生成AI作文・断定的将来予測・売買助言は行わない）。

Phase 0分類:
- A（既存で十分使える）: Market Regime／Cross Market／Future Intelligence／
  Executive Summary／Analysis Confidence／Weekly Events／異常値検知（総括の素材が既に揃っている）。
- B（少し改善すれば使える）: シナリオ系の重複整理（個別シナリオを折りたたみ）／
  営業系のグループ化（既にcard-collapsed済み→「営業メモ」見出しで集約）。
- C（今回新規追加）: Market Narrative Summary（本日の相場総括）＝新規モジュール＋最上部カード。
- D（今回はやらない・据え置き）: セクションの物理的な全並べ替え（既存のprev/next・目次・
  Data Qualityは引用の下、というナビゲーションテストを壊さないため見送り。「本質を上に」は
  最上部の相場総括＋Today's Decisionで担保）／営業系の完全削除（まず営業メモに集約・段階的に）。

追加・改善
・改善1/2 Market Narrative（src/analysis/market_narrative.py 新規＋models.MarketNarrativeSummary）:
  市場データ・重要ニュース・Market Regime・Cross Market・Future Intelligence・Weekly Events・
  異常値・Analysis Confidence だけから、①今日を一言で（headline）②何が起きたか③なぜ動いたか
  ④背景⑤波及チェーン⑥これから見るべき点⑦今後の見立て（短期/中期・条件分岐）⑧リスク
  ⑨投資判断への示唆（短期/中期/長期/注意・売買助言なし）⑩Analysis Confidence⑪根拠、を機械的に整理。
  HTML最上部（Today's Decision・Dashboardより上）に「📝 本日の相場総括」カードを新設し、
  背景・見立て・リスクは「詳しく」に折りたたみ。main.pyで配線・AnalysisBundleに格納。
・改善3 役割整理: Today's Decisionは「3分の判断カード」、Market Narrativeは「なぜの深掘り」。
  総括の背景説明はNarrative側に集約し、Today's Decisionは短い判断カードのまま維持。
・改善5 シナリオ整理: 「今日の3大シナリオ（期待値順）」を主軸とし、「日経平均・ドル円・米国市場
  個別シナリオ」は重複回避のため初期は「詳しく」に折りたたみ（内容・算出は不変）。
・改善4/9 営業メモ統合: 営業支援系（今日電話すべき顧客／営業準備／営業トーク／営業向けコメント
  ／岡三証券営業向けコメント／朝会コメント／会話ネタ／想定質問）の直前に「営業メモ」見出しを
  追加して1グループに集約。各カードは初期折りたたみ（v3.1）＋「営業セクションを非表示」トグルは維持。
  メニュー最上段に「本日の相場総括」を追加し重要度順の入口に。

（既に実装済みで継続）: Future Intelligenceの初期短縮（fi-conclusion＋FI_SUMMARY_COUNT折りたたみ・v2.7）／
Watchlistの今日見るべき5銘柄（Today's Decision・v3.1）／引用の要約＋全URL折りたたみ（v3.1）。

やらないこと（v3.5で厳守）
・売買助言（「買うべき」「売るべき」等の個別推奨）／事実と分析の混同／取得していないデータの捏造／
  既存の分析ロジック・エンジンの書き換え／派手なUI化。

## v3.4 (2026-07-07) — One-Tap Report Generation（Cloudflare Worker中継でワンタップ生成）

GitHub Actions画面を経由せず、スマホから1タップで workflow_dispatch を起動できる
ようにした版。GitHub Token・Secrets・PATはHTML/JS/GitHub Pagesに絶対に出さず、
Cloudflare Worker等の認証つき中継バックエンドを介して安全に実行する設計。

追加・改善
・Cloudflare Worker（cloudflare/trigger-report-worker.js 新規）: POST /trigger で
  GitHub Actions の workflow_dispatch API を叩く中継役。GITHUB_TOKEN はWorkerの
  Secret（env）からのみ参照し、コードに直書きしない・レスポンス/ログにも出さない。
  必要な変数: GITHUB_TOKEN(Secret)/GITHUB_OWNER/GITHUB_REPO/GITHUB_WORKFLOW_FILE/
  ALLOWED_ORIGIN/WORKFLOW_REF。CORSは ALLOWED_ORIGIN（既定 GitHub PagesのURL）のみ許可。
  成功時 {ok:true,message:"workflow dispatched"}、失敗時 {ok:false,error:...}（要約のみ）。
・cloudflare/README.md・cloudflare/wrangler.toml.example 新規: Worker のデプロイ手順・
  Secret設定・必要なGitHub Token権限（Fine-grained: Actions R/W・Contents R/W、対象repo限定）。
・HTML（src/report/html_builder.py）: `_one_tap_regenerate_html` を機能化。realtime.enabled=true
  かつ endpoint_url 設定時のみ「🚀 ワンタップで最新レポート生成」ボタンを表示。押下でJS（SCRIPT）が
  endpoint_url へPOSTし、成功なら「生成を開始しました。1〜3分後にページを再読み込み」、失敗なら
  エラー表示、連打防止で60秒間ボタン無効化。エンドポイントURLは data-endpoint に持たせ、
  Token・Secretはボタン・JS・HTMLに一切埋め込まない。
・config.yaml: realtime 設定枠を one_tap 対応に更新（enabled/provider/endpoint_url/mode＋
  Cloudflare Worker設定例をコメントで追記）。既定は enabled:false（従来通りボタン非表示）。
・既存の安全導線（🔄ページ再読み込み／⚙️GitHub Actionsを開く／📱スマホ手順）は
  Worker未設定時のフォールバックとして残置。
・README: Cloudflare Workerでのワンタップ生成の仕組み・TokenをHTMLに入れてはいけない理由・
  Worker Secretの設定方法・必要なGitHub Token権限・config.yaml設定例・トラブルシューティングを追記。

やらないこと（v3.4で厳守）
・GitHub Token/Secrets/PATをHTML・JS・GitHub Pagesへ出すこと。
・認証なしAPIでのworkflow_dispatch／誰でも勝手に実行できる実装。
・許可Origin以外からのWorker実行（CORSで拒否）。

## v3.3 (2026-07-07) — Latest Report Generation Button Upgrade（スマホからの再生成導線を改善）

「最新レポートを生成する」ボタンまわりのUXのみを改善した版。分析ロジック・
HTMLの他セクションは変更していない。GitHub Token・Secretsの類は引き続き
HTMLへ一切出さない（既存のセキュリティ方針を厳守）。

追加・改善
・改善1 ボタンUI再設計（src/report/html_builder.py `_refresh_button_html` 他）:
  ①🔄ページを再読み込み（常時表示・従来通り）②⚙️最新レポートを生成する
  （actions_url設定時のみリンク表示。未設定時は非表示ではなく「設定未完了」を
  表示し、何が足りないか分かるようにした）③📱スマホでの実行手順（details/summaryで
  常時提供。ログイン→Run workflow→緑ボタン→1〜3分待機→再読み込み、の5手順）。
・改善2 Actions画面へのリンク精度向上（main.py `_resolve_actions_url`）: 優先順位を
  「環境変数ACTIONS_URL（明示上書き）＞config.yaml output.actions_url（設定時最優先）
  ＞GITHUB_REPOSITORYからの自動推定＞空文字」に変更。config.yamlのactions_urlに
  実際のワークフロー直リンクを設定済み。
・改善3 生成状態の説明（`_generation_status_html` 新規）: 最終生成時刻・
  「このページは最後に生成されたレポート」であること・「再読み込みだけでは新規
  データ取得されない」ことをボタン付近に常時表示。
・改善4 将来のワンタップ生成枠（`_one_tap_regenerate_html` 新規、`build_html_report`
  に `realtime` 引数を追加）: `realtime.enabled=true` かつ `endpoint_url` 設定時のみ
  「🚀 ワンタップで最新生成」ボタンの枠を表示（バックエンド未実装のため常に押せない
  状態）。無効時・未指定時は従来通り何も表示しない。main.pyから
  `config.get("realtime", {})` を渡すよう配線。
・改善5 セキュリティ: GitHub Token・Secrets・認証情報の類を新規追加分にも一切含めない
  （既存のno-leakテストに加え、v3.3の新規テストでも "token" 文字列の非存在を確認）。
・改善6 README更新: ページ再読み込みとレポート再生成の違い・スマホでRun workflowを
  押す手順・Run workflowが見えない場合の対処（ログイン確認/デスクトップ表示切替/
  GitHubアプリ利用）・完全ワンタップ化に必要なもの（Cloudflare Worker/Vercel
  Function/GitHub App）・GitHub TokenをHTMLに出してはいけない理由を追記。

やらないこと（v3.3で厳守）
・GitHub Token・Personal Access Token・Secretsの類をHTML/JSへ埋め込むこと。
・認証なしでworkflow_dispatchを実行できる実装（誰でも押せるワンタップ自動実行）。
・分析ロジック・他セクションのHTML/CSSの変更（ボタンまわりのみに限定）。

## v3.2 (2026-07-07) — Analysis Accuracy Upgrade（分析精度・ニュース重要度・未来予測・市場判断の強化）

UI改善ではなく「分析精度」の底上げに特化した版。HTML/CSS/UIは一切変更せず、
分析エンジンのみを追加・強化した。すべて公開市場データと既存の算出済みシグナル
だけから機械的に算出し、生成AIの推測は使わない。既存エンジン（scenario/
causal_chain/news_ranking/source_trust 等）は変更せず、結果を後付けで拡張、
または新規エンジンとして並列に追加する形で後方互換を維持している。

Phase 0分類:
- A（既存で十分使える）: Source Trust（★1〜5の階層は既にあり）／Duplicate/Cross
  Source Intelligence（source_count・combined_trust は算出済み）／Theme Momentum
  Score／既存の因果チェーン（短い3〜5本）。
- B（少し改善すれば使える）: 情報源の階層→Tier1〜4ラベルへ写像（改善4）／
  ニュース重要度★→100点満点化（改善3）／Weekly Eventにコンセンサス等の入れ物追加（改善6）。
- C（今回新規追加）: Market Regime Engine（改善1）／Cross Market多段波及（改善2）／
  Future Probability条件分岐（改善7）／Theme Rotation（改善8）／Market Breadth（改善9）／
  Analysis Confidence（改善10）。
- D（今回はやらない）: HTML/CSS/UI改善（明示的に禁止）／実際の資金フロー額・
  値上がり値下がり全銘柄数の取得（未提供データの捏造はしない・構造のみ）／
  生成AIによる将来予測の断定。

追加・強化（分析エンジンのみ・すべて AnalysisBundle に格納。表示は次版以降）
・改善1 Market Regime Engine（src/analysis/market_regime.py 新規）: VIX・米10年債・
  NASDAQ・S&P500・SOX・ドル指数(DXY)・ドル円・WTI・Gold・Bitcoin の前日比/水準から、
  Risk On / Risk Off / Neutral を判定し Risk Score(0〜100) を算出。各指標の寄与
  （符号・重み）を定数化した透明なスコアリング。データ欠損指標はスキップし評価数も返す。
  config.yaml に ドル指数(DXY) を追加。
・改善2 Cross Market Analysis（src/analysis/cross_market.py 新規）: 既存の因果チェーンは
  変更せず、米金利↑→ドル高→円安→日本輸出株→半導体→設備投資→電力→電線 のような
  多段の波及を、条件成立時のみ機械的に組み立てる。config.yaml の cross_market_rules（任意）で
  追加ルールも定義可能。
・改善3 News Impact Score（src/analysis/news_impact.py 新規）: 既存の★ランキングは不変。
  市場影響・テーマ継続性・一次情報(Tier1)・複数ソース一致・日本株/米国株/指数/為替/金利影響・
  セクター波及・話題性・鮮度の加点表から Impact Score(0〜100) と内訳を後付け付与
  （NewsRankingItem に impact_score / impact_breakdown を追加）。
・改善4 Source Tier（source_trust.py に追加）: 既存の信頼度スコア(1〜5)を Tier1（公式・
  一次情報）〜Tier4（一般・参考）へ写像。Tier1はImpact Scoreで重く評価。
・改善5 Duplicate Intelligence（news_impact.py）: 3社以上が同一ニュースを報じていれば
  Major Story と判定（NewsRankingItem.is_major_story）。count_major_stories で件数集計。
・改善6 Macro Intelligence（構造のみ）: WeeklyEventEntry に consensus/previous/forecast/
  actual/surprise の入れ物を追加（今回は構造だけ。値があれば転記、無ければ空＝従来表示）。
・改善7 Future Probability（src/analysis/future_probability.py 新規）: 未来予測ではなく
  「もしAかつBなら→C」のif条件型。景気後退懸念/リスクオン継続/円安輸出優位/インフレ再燃/
  安全資産選好の各分岐を本日の市場データで評価し triggered を立てる。生成AIの推測なし。
・改善8 Theme Rotation（src/analysis/theme_rotation.py 新規）: Theme Momentum Score と
  theme_relations（人手の隣接関係）から、AI→半導体→電力… のテーマ間資金移動の
  「向かいやすさ」を推定（断定はしない）。
・改善9 Market Breadth（src/analysis/market_breadth.py 新規）: 取得済み指数・コモディティ・
  ウォッチリストの前日比プラス/マイナス数から Breadth Score(0〜100) を算出。東証全銘柄の
  騰落ではない代用値であることを is_proxy=True と basis で明示（将来の全銘柄データに拡張可能な構造）。
・改善10 Analysis Confidence（src/analysis/analysis_confidence.py 新規）: 旧「AI Confidence」に
  代わり、取得ソース数・公式(Tier1)情報数・重複報道数・鮮度・データ欠損・分析可能項目数から
  レポート全体の分析根拠の充実度(0〜100)を機械的に算出（将来の的中確率ではない）。

やらないこと（v3.2で厳守）
・HTML/CSS/UIの変更（html_builder.py 等は一切触っていない）。
・既存分析ロジック（scenario/causal_chain/news_ranking/source_trust本体）の書き換え。
・未提供データ（実資金フロー額・全銘柄の値上がり値下がり数・将来予測の確率）の捏造。

## v3.1 (2026-07-07) — UX / Decision Quality Upgrade（結論ファースト・翻訳警告・異常値検知）

「情報は多いが投資の“結論”が埋もれる」を解消し、朝3分でその日の判断に辿り着ける
Personal Market Intelligence OS へ寄せた版。既存の分析ロジック・ランキング・
各エンジンの計算結果は一切変更せず、HTMLの「見せ方」と表示用の機械的サマリー・
品質チェックのみを追加した（リファクタリング・既存UI破壊なし）。

追加・改善
・改善1 Today's Decision カード: HTML最上部（Dashboardより上）に「今日の投資判断
  ・3分サマリー」カードを新設。今日の市場判断（リスクオン／オフ／中立）・重要テーマTOP3
  ・今日見るべき銘柄TOP5・警戒ポイントTOP3・今週の重要イベント・AI Confidence・データ鮮度
  ・翻訳ステータスを各1〜2行で提示。新しい予測は行わず、各エンジンが算出済みの最上位
  シグナルを機械的に転記するだけ（市場判断は既存シナリオ確率のbull/bear差から判定）。
  トップメニューにも 🎯 Today's Decision を追加。
・改善2 翻訳バグの見える化: 英語見出しに日本語訳があればHTMLで日本語を優先表示
  （display_title・「翻訳済み」バッジ・原文は保持、v3.0から継続）。加えて、未翻訳の
  英語記事が残る場合は Today's Decision と Data Quality に「翻訳API未設定のため英文の
  まま表示（未翻訳N件）」と明示（ANTHROPIC_API_KEY未設定を llm_enhancer.is_available で判定）。
・改善3 異常値検知（src/analysis/anomaly.py 新規）: 日経±5%・主要指数±5%・ドル円±2%・
  米10年±15%の前日比、および水準の妥当レンジ（桁違いの検知）を機械的にチェックし、
  「異常値なし／要確認」＋該当項目を列挙。原因の断定・自動補正はせず、人が確認する
  ためのフラグのみ（分析ロジック・ランキングには不関与）。
・改善5 今日見るべき銘柄: Today's Decision の「今日見るべき銘柄TOP5」をウォッチリスト
  （無ければ注目5銘柄）から機械的に抽出。
・改善6 営業系セクションの初期折りたたみ: 営業準備／営業トーク／営業向けコメント／
  岡三営業コメント／朝会コメント／想定質問（sales-section）と 今日電話すべき顧客／会話ネタを
  初期状態で card-collapsed に。投資判断に必要なセクションを上に、営業メモは畳んで下部に。
  既存の「営業セクションを非表示」トグルはそのまま維持。
・改善7 引用（情報源）の圧縮: 初期表示は要約（情報源数・カテゴリ数・公式ソース数・
  海外ソース数・主要ソースTOP10）のみとし、参照URLの全一覧は「詳しく」に折りたたみ
  （全URLは従来通り保持）。
・改善8 Data Quality 拡充: 翻訳API状態・経済カレンダー取得状態（自動取得／登録情報の内訳）
  ・異常値チェック・取得失敗ソース・市場データ取得時刻・RSS取得件数を追加表示。

やらないこと（v3.1でも継続）
・Token/SecretsをHTMLへ出す／有料・ログイン必須情報の取得／規約不明スクレイピング／
  既存分析ロジックの大改造・既存UI破壊。
・セクションの物理的な全並べ替えは、既存のナビゲーション（prev/next・目次・
  Data Qualityは引用の下）テストを壊さないため見送り、「結論ファースト」は最上部の
  Today's Decision カードで担保した。

## v3.0 (2026-07-07) — Foundation Completion（翻訳キャッシュ／リアルタイム導線／経済カレンダー）

v2.8/v2.9の骨組みを「本番で使える」状態に仕上げた版。既存の分析ロジックは変更せず、
翻訳の永続化・更新導線・経済指標の自動収集を完成させた。

Phase 0分類:
- A（実装済み）: 翻訳エンジン本体・2段階更新ボタン・source health/fetched_at・
  Weekly Eventの重要度/影響対象/カウントダウン
- B（骨組みのみ→今回完成）: 翻訳キャッシュ（毎回API・永続化なし）／
  economic_calendar（単一URL JSONのみ・source未記録）／Weekly EventのSource表示なし
- C（今回実装）: 翻訳キャッシュ永続化・翻訳UI強化・realtime設定枠・
  economic_calendarのsources(rss/json/csv)対応・Weekly EventのSource/取得時刻表示・
  workflow永続化・README
- D（やらない）: Token/SecretsをHTMLへ・完全自動workflow_dispatch（Token必要）・
  有料/ログイン/規約不明スクレイピング

追加・改善
・①English Translation Engine完成: 翻訳キャッシュを永続化
  （data/translation_cache/translation_cache.json）。原文タイトルをキーに日本語訳を
  保存し、翌日以降はAPIを呼ばず再利用。ANTHROPIC_API_KEY未設定でも過去に翻訳済みの
  見出しは日本語表示。翻訳失敗（空文字）はキャッシュに残さずリトライ可能。キャッシュ
  破損時も空として継続。HTMLは日本語訳を優先表示＋「翻訳済み」バッジ＋原文を「詳しく」に保持
  （News Ranking/Executive Summary/Dashboardで翻訳タイトル優先）
・②Real-Time Update Engine完成: config.yamlに realtime 設定枠
  （enabled/provider/endpoint_url/mode）を追加。将来のCloudflare Worker等による完全
  リアルタイム化に備えつつ、enabled=falseの間は既存動作のまま・Token/SecretsはHTMLへ
  一切出さない。取得時刻表示（HTML生成/市場データ/各ソース）はv2.9のNews Freshness詳細を継続
・③Economic Indicator Auto Collection完成: economic_calendar.pyを本実装。
  economic_calendar.sources（[{name,url,type(rss/json/csv)}]）を順に取得・正規化し、
  macro_events（手入力優先）とマージ・重複除去。取得失敗時はmacro_eventsのみで継続。
  RFC2822日付にも対応。WeeklyEventEntryにsource/source_stars/fetched_atを追加し、
  Weekly EventにSource・Source Trust・取得時刻を表示（影響対象は既存の自動補完を継続）
・⑤GitHub Actions永続化: translation_cache.jsonをコミット対象に追加
  （journal.json/theme_learning.jsonに追加）。data/translation_cache/README.md を新規追加

変更ファイル
・src/analysis/translation.py（永続キャッシュ）・executive_summary.py（display_title優先）・
  weekly_events.py（source/fetched_at）・models.py（WeeklyEventEntry拡張）
・src/collectors/economic_calendar.py（rss/json/csv対応・source記録）
・src/report/html_builder.py（翻訳済みバッジ・Weekly EventのSource/取得時刻表示）
・main.py（翻訳キャッシュ配線）・config.yaml（translation.cache_dir/realtime/
  economic_calendar.sources）・.github/workflows/daily-market-brief.yml（キャッシュ永続化）
・README.md / CHANGELOG.md / data/translation_cache/README.md（新規）
・tests/test_v3_0_foundation.py（新規・17件）

pytest
261 passed（既存244維持＋v3.0で17件追加）

## v2.9 (2026-07-07) — Real-Time Freshness / Translation / Source Expansion Upgrade

「毎日読むレポート」から「岡三証券退職後も自分だけでマーケットを分析・予測し
続けるための自己改善型システム」へ。既存の分析ロジックは変更せず、翻訳・
リアルタイム性・情報源・重複統合を強化。

Phase 0（実装前調査）分類:
- A（安全に実装）: ①翻訳エンジン強化 ②2段階更新ボタン＋取得時刻表示
  ③公式RSS群の追加 ④重複ソース統合・重要度補正 ⑤情報取得時刻の見える化
- B（GitHub Actionsでのみ実データ検証可）: 新規collector（Fed/SEC/BLS/EIA/
  ECB/CoinDesk/CoinTelegraph/Yahoo Finance US）の実際のRSS取得、
  ANTHROPIC_API_KEYがある場合の実翻訳（この開発環境はネットワーク遮断・
  APIキー未設定のため。no-op経路・グレースフルフェイルは検証済み）
- C（今回は見送り）: Seeking Alpha/Benzinga（利用規約・Bot対策リスク）、
  半導体各社Newsroom・AI各社Blog（定型RSSが無くスクレイピングが必要）、
  US Treasury/BoE/IMF/World Bank/OECD/Nasdaq公式（RSS構成の確証が低い）
  — 詳細はconfig.yamlの`source_classification`とREADMEを参照

追加・改善
・①English News Translation Engine強化: Headlineに`duplicate_sources`等と
  並び`is_translated`（title_jaの有無から導出するプロパティ）を追加。翻訳
  プロンプトを金融用語重視・100文字目安・専門用語補足（EPS/CPI/FOMC/
  guidance/yield/rate cut等）へ更新。Today's Dashboardの見出し表示を
  `display_title()`（日本語訳）+ネイティブtitle属性（原文・ホバー表示）へ修正。
  ANTHROPIC_API_KEY未設定・失敗時は原文のまま（既存動作に影響なし）
・②Real-Time Update Engine: 「最新表示に更新」を2段階ボタンへ再設計。
  「ページを再読み込み」（常時表示・location.reloadのみ）と「最新レポートを
  生成する（GitHub Actionsを開く）」（actions_url設定時のみ・新しいタブで
  Run workflow画面を開くだけ・自動実行はしない・GitHub Token/Secretsは
  一切埋め込まない）。News Freshnessカードに「情報取得時刻を詳しく見る」を
  追加し、HTML生成時刻・市場データ取得時刻・各ニュースソースの取得時刻
  （SourceHealthEntryにfetched_at追加）を表示
・③Source Expansion Engine: 新規collector 6本（fed.py/sec_gov.py/
  us_gov_stats.py/ecb.py/crypto_news.py/yahoo_finance_us.py）を追加。
  公開RSSのみ使用し、既存collectorと同じ「失敗時は空リストを返す」設計を
  踏襲（main.pyの追加情報源ループに追加するだけで、失敗してもレポート生成は
  止まらない）。config.yamlに情報源の実装状況（implemented/reference_only/
  skipped）を分類・明記
・④Duplicate/Cross Source Intelligence: dedupe_headlinesが同一ニュースを
  配信していた他の情報源名（duplicate_sources）と配信元総数（source_count）
  を記録するよう拡張（重複が無ければ従来通りsource_count=1）。
  news_ranking.pyで2社以上・信頼度★4以上の重複報道に+1〜+2の補正を追加
  （新しい評価基準の創作ではなく既存Source Trustスコアの集計）。
  source_trust.pyにcombined_trust_for_sources()を追加し、HTMLへ
  「○社が同一ニュースを報道／Combined Trust」を表示。Source Trustの
  ティア判定にSEC/BLS/BEA/EIA/ECB/BoE/Barron's/CoinDesk/CoinTelegraph等を追加

変更ファイル
・src/collectors/: news.py（duplicate_sources/source_count/is_translated）、
  fed.py・sec_gov.py・us_gov_stats.py・ecb.py・crypto_news.py・
  yahoo_finance_us.py（すべて新規）
・src/analysis/: source_trust.py（combined_trust_for_sources追加・ティア拡張）、
  news_ranking.py（重複ソース補正）、data_freshness.py（fetched_at追加）、
  translation.py（プロンプト更新）
・src/report/html_builder.py（2段階更新ボタン・情報取得時刻・重複表示・
  Dashboard翻訳表示）
・main.py（新規collector配線）、config.yaml（新規ソース設定・分類・reliability）
・tests/test_v2_9_realtime_translation_sources.py（新規・15件）、
  tests/test_html_builder.py（更新ボタン仕様変更に伴う2件更新）

pytest
244 passed（既存229維持＋v2.9で15件追加）

## v2.8 (2026-07-06) — Smart Intelligence Evolution

「毎日読むレポート」から「毎日学習し続ける投資AI」へ。既存の分析ロジック
（Momentum・Confidence・Watchlist判定）の設計は維持し、学習・信頼度・優先度の
仕組みを追加。HTMLのみ変更（Markdown版は維持）。外部ライブラリ追加なし。

追加（学習）
・Investment Journal（①）: 新規 src/analysis/investment_journal.py。毎日のAI判断
  （重要ニュース・テーマ・シナリオ・Thesis・Regime・Money Flow・Top Picks・
  Confidence・重要イベント＋参照価格）を data/investment_journal/journal.json へ
  追記し、30/90/180日後に現在の市場と機械的に答え合わせ（★評価・的中/外れ）。
  新セクション「Learning History」を追加。市場データが無い環境では評価はスキップ
・Theme Confidence Learning（②）: 新規 src/analysis/theme_learning.py。テーマ予想を
  data/theme_learning/theme_learning.json へ蓄積し、30日後の地合いで勝率・平均
  リターン・平均継続日数を集計。勝率で Future Intelligence の Confidence を上下限
  つき（-20〜+10）実績補正（build_future_intelligenceにtheme_win_rates引数を追加。
  未指定なら従来通り）。新セクション「Theme Confidence Learning」を追加

改善（要約・信頼度・優先度）
・Scenario Engine v2（③）: 新規 src/analysis/scenario_v2.py。強気/中立/弱気を
  期待値（確率）の高い順に最大3つへ整理し①②③で表示。発生条件・恩恵/悪影響
  セクター・注目銘柄・因果関係・時間軸は「詳しく」で展開。新セクション
  「今日の3大シナリオ（期待値順）」を追加
・情報ソース信頼度（⑥）: 新規 src/analysis/source_trust.py。出典名から★1〜5と
  ティア（公式発表/一流メディア・IR/主要メディア/一般メディア/参考情報）を判定し、
  ニュース・Executive Summaryの各カードに Source Trust バッジ＋理由を表示
・Why Today（⑦）: 新規 src/analysis/why_today.py。既存データのみから「なぜ今日
  見るべきか」を1〜2行で生成し、対象カードの先頭に表示（新予測はしない・長文禁止）
・低重要度記事の折りたたみ（⑧⑨）: ニュースは重要度×鮮度で初期表示を選別
  （★★★★☆以上／24時間以内かつ★★★☆☆以上／1位は必ず表示）。★★★☆☆以下・
  48時間超は details に折りたたむ（削除しない）
・英語ニュース自動翻訳（④・安全スキャフォールド）: 新規 src/analysis/translation.py。
  ANTHROPIC_API_KEYがある時のみ英語見出しを日本語訳し「日本語→原文を見る」で表示。
  キー未設定・失敗時は原文のまま（Headlineにtitle_ja/display_title()を追加）
・Weekly Event 自動取得（⑤・安全スキャフォールド）: 新規
  src/collectors/economic_calendar.py。economic_calendar.url設定時のみ公開カレンダーを
  取得しconfig.yamlのmacro_eventsとマージ。未設定・失敗時は従来通りconfigのみ使用

変更ファイル
・src/analysis/: investment_journal.py / theme_learning.py / scenario_v2.py /
  source_trust.py / why_today.py / translation.py（すべて新規）、models.py・
  future_intelligence.py（既存・後方互換で拡張）
・src/collectors/: economic_calendar.py（新規）、news.py（Headlineにtitle_ja追加）
・src/report/html_builder.py（新セクション・Source Trust・Why Today・折りたたみ）
・main.py / config.yaml / .github/workflows/daily-market-brief.yml（JSON永続化）
・tests/test_v2_8_smart.py（新規・20件）、tests/test_v2_7_upgrade.py（折りたたみ仕様更新）
・data/investment_journal/README.md・data/theme_learning/README.md（新規）

pytest
229 passed（既存209維持＋v2.8で20件追加）

注意（この環境での検証範囲）
・④翻訳・⑤自動取得はネットワーク/APIキーが必要なため、開発環境では実データ検証
  不可（no-op経路とHTML表示は検証済み。GitHub Actions側で有効化される）。
  それ以外の①②③⑥⑦⑧⑨は実データ経路込みで検証済み

## v2.7 (2026-07-06) — Market Intelligence Knowledge Upgrade ＋ Weekly Event Impact Calendar

「毎朝ニュースを読むシステム」から「世界の変化を理解し長期投資判断を支援する
AIストラテジスト」への強化。分析ロジックの設計（Momentum・Confidence・
Watchlist判定・FIの計算）は変更せず、知識品質・鮮度・情報密度・可読性を改善。

追加・改善
・羅針盤Knowledge強化（①）: 「新しい順に3件読む」→「最大100件から知識を構築」
  する知識ベース方式へ。全ファイル走査→重複統合（正規化キー）→重要度
  （複数号での繰り返し登場数＋キーワード密度）順に重要な知識だけ抽出。
  カテゴリを拡張（景気循環・金融政策・金利・為替・半導体・AI・企業分析）し、
  philosophy_patterns（投資哲学・利益確定・リスク規律）を新設。
  本文転載禁止の制限（80文字/件・5件/カテゴリ・抜粋120文字）は不変
・ニュース鮮度最優先（②）: news_rankingに鮮度軸を追加。24時間以内は+2加点、
  48時間超は-4の大幅減点。ただしFOMC・日銀・決算・国家戦略・雇用統計・CPI等
  「影響期間の長いイベント」は例外として減点しない（鮮度×影響期間の両立）。
  日時不明記事は加減点なし。既存8軸の算出方法は不変
・情報密度（③）: ニュースランキングは重要5件のみ通常表示（6位以下は折りたたみ）。
  FIのメガトレンド／Theme Momentum／成熟度メモ／テーマ別診断／Investment
  Thesisは重要度順（見出し件数・スコア・Confidence）に上位8件のみ通常表示し、
  残りは「残りN件を表示」で展開（選別は表示のみ。計算は全件のまま）
・要約表示＋詳しくボタン（④⑤⑦）: 各カード・各項目を「2〜4行の要約→
  『詳しく』（HTML標準details/summary・外部JS不要）」の3分UIへ。
  Executive Summary／ニュースランキング／Watchlist／FI診断・成熟度／
  Watchlist・Stock Intelligence／Investment Thesisに適用
・重要度表示（⑥）: 全セクションカードの見出しに「重要度◯◯」（★×20の
  100点満点換算）バッジを追加
・FI再構成（⑧）: 冒頭に「結論→重要ポイント3つ→詳しくは各ブロック」の
  結論ボックスを追加（既存シグナルの転記のみ・新分析なし）
・Investment Thesis再構成（⑨）: 各テーマを「結論→理由3つ→詳しく」へ
・Watchlist再構成（⑩）: 銘柄ごとに一行要約→詳しくへ
・Weekly Event Impact Calendar（追加依頼）: 新セクション「今週の重要イベント・
  経済指標」。config.yamlのmacro_events＋決算発表予定から今日〜7日後の
  イベントだけを「近い順→重要度順」で表示。カウントダウン（本日21:30／
  あと1日 5時間／あと3日、日本時間）・★と重要度・国/地域・影響対象・
  想定される影響（条件付き整理のみ）・詳しく（なぜ重要か/見るべきポイント/
  関連テーマ）付き。macro_eventsに任意のtime("21:30")を登録すると時間まで
  表示。データが無い日は「直近1週間の重要イベントは登録されていません」。
  新規外部APIなし（新規 src/analysis/weekly_events.py＋WeeklyEventEntry）
・HTML版のみ対象（⑪）。Markdown/モバイル版は変更なし

変更ファイル
・src/analysis/rashinban_loader.py / models.py / news_ranking.py /
  weekly_events.py（新規） / src/report/html_builder.py / main.py / config.yaml
・tests/test_v2_7_upgrade.py（新規） / tests/test_weekly_events.py（新規） /
  tests/test_html_builder.py（セクション追加に伴う範囲修正1件）

pytest
209 passed（既存維持＋v2.7で19件追加）

## v2.6 (2026-07-05) — Rashinban Learning Source System v1.0

追加（岡三「羅針盤」を、コード更新なしで毎日の分析精度向上に使える学習ソースにする）

・Rashinban Loader（①）: 新規 `src/analysis/rashinban_loader.py`。
  `data/rashinban/` の .md/.txt を新しい順に最大3件（config可変）読み込み、
  latest.md→ファイル名日付（YYYY-MM-DD）降順で最新を判定。READMEは対象外。
  フォルダが無い・空でもエラーにならず空のまま動作
・RashinbanKnowledge（②）: models.py に追加（source_files／latest_date／
  相場観・テーマ・銘柄選定・リスク・時間軸の5パターン＋raw_excerpt_summary＋
  emphasized_theme_labels）。frame_count()／has_content() 付き
・型の抽出（③）: すべてルールベース（AI API不使用）のキーワード分類。
  本文転載防止のため 1件80文字・カテゴリ5件・抜粋120文字に制限。
  重点テーマは既存 macro_themes ラベルとの照合のみ（新テーマ生成なし）
・分析への接続（④）: 羅針盤がある場合のみ、重点テーマ一致分に
  News Ranking=+1の補助加点＋理由追記／Strategist View・Executive Summary=
  参照した旨の一文／Future Intelligence=Theme Momentum理由追記・
  Investment Thesis監視指標追加。無い場合は従来と完全に同一動作
  （既存スコアリング・判定ロジックの設計は不変）
・HTML表示（⑤）: 「Rashinban Learning Source」小カードを追加。
  読み込みファイル名・最新日付・抽出フレーム数・使用状況のみ表示し、
  本文・抜粋は一切表示しない（未配置時はスキップした旨を表示）
・自動読み込み（⑥）: GitHub Actionsはmain.py実行時に data/rashinban/ を
  自動で読むため、workflowの変更なし（latest.md の差し替えだけで反映）
・運用手順（⑦）: `data/rashinban/README.md` 新規＋READMEに
  「GitHub Webだけで追加する手順」（PC・Claude Code不要）を追記
・config.yaml: `rashinban:`（dir／max_files）を追加
・tests/test_rashinban_loader.py 新規（空フォルダ／md・txt読込／最新判定／
  Knowledge生成／HTML表示／長文転載なし／羅針盤なしで従来動作、の8観点）

対象外（v1.0の割り切り）
・PDF/DOCXの解析はしない（md/txtへ変換して置く運用）
・羅針盤本文のレポート転載・長文引用はしない（分析フレームとしてのみ利用）

## v2.5 (2026-07-05) — Market Brief UI/UX & Freshness Upgrade

追加・改善（HTML版のみ。分析ロジック・Momentum・Confidence・Watchlist判定は不変。
外部JS/CSSライブラリなし・素のJavaScriptのみ。Markdown/モバイル版は変更なし）

・ニュース鮮度の表示（①）: 重要ニュースランキング・AI Executive Summary・
  Today's Dashboardの各ニュースに、投稿日時・約何時間前か・鮮度バッジ
  （最新≦6h=赤／24時間以内=緑／48時間以内=オレンジ／古い=グレー／
  日時不明=グレー）を色分き表示。順位ロジックは変更なし
  （鮮度タイブレークはv2.3で導入済み。日付不明記事が不利になる挙動も同様）
・トップメニューグリッド（②③）: レポート上部にDashboard／Executive Summary／
  Future Intelligence／重要ニュース／Watchlist／Stock Intelligence／
  世界のお金／Data Quality／営業メモへの9ボタンをAppMedia風グリッドで配置
・目次リンクを新しいタブで開く（④）: 全目次リンクにtarget="_blank"
  rel="noopener"を付与（リンク先は同一HTML内アンカー）
・セクションカード強化（⑤）: 各カードに「ひとこと説明」（主要9セクション）・
  開く/閉じる（▾/▸）・コピー（既存）・お気に入り（☆/★）を追加
・お気に入り機能（⑥）: ☆で登録→★、★で確実に解除→☆。localStorage
  （mkt_favs）に保存し再読み込み後も維持。表示オプション内に一覧を表示し、
  解除すると一覧からも消える。0件時は「お気に入りはありません」。
  Playwright実機検証で登録→解除→再登録→再読込維持を確認済み
・フローティング操作ボタン（⑦）: 右下に ☰目次／★お気に入り／↑TOP の3ボタン
・簡易検索＋タグUI（⑧）: キーワード入力でセクションタイトル・本文を検索し
  一致しないカードを非表示。クリアボタン・0件メッセージ付き。
  タグ（AI/半導体/電力/防衛/EV/金利/為替/消費）タップで即絞り込み
・表示オプション改善（⑨）: 既存4項目に「お気に入りのみ表示」を追加
  （localStorage保存）

変更ファイル
・src/report/html_builder.py
・tests/test_html_builder.py

pytest
182 passed

コミット
（下記参照）

## v2.4 (2026-07-05) — Investment Thesis Engine v2.0

追加（Future Intelligence Engineへの統合のみ。既存の分析ロジック・スコアリング・
判定・新しいAPIの追加はなし。営業利用ではなく自分自身の長期資産形成・投資判断を
最優先目的とする）

・Investment Thesis（テーマ別・長期投資仮説）: macro_themeごとに以下10項目の
  投資仮説を生成し、Long-term Strategyブロック（Markdown/HTML/モバイル）へ
  Confidence（分析根拠の充実度）の高い順に表示
  - 現在何が起きているか: Theme Momentum Scoreのreason（本日のシグナル説明）を転記
  - 今後起こりそうな変化［AI分析］: テーマ別診断のCatalyst先頭を非断定的に
    言い換えるのみ（Catalystが判断材料不足の場合は正直に分析材料不足と表示）
  - 恩恵を受ける業界: causal_rules.beneficiary_sectors
  - 恩恵企業: 既存の恩恵銘柄ロジック（beneficiary_sectors→related_tickers）の結果
  - 二次的恩恵企業: theme_relations（Cross Theme Mapping）で1段階隣接する
    テーマの恩恵企業
  - まだ注目されにくい企業: theme_relationsで2段階離れたテーマの恩恵企業
    （因果チェーン上、直接の恩恵銘柄として言及されにくい銘柄。新たな銘柄推定ではない）
  - 投資期間: 既存の中長期テーマ割り付け（半年/1年/3年/5年/10年）をそのまま転記
  - 監視指標: Theme Momentum Scoreの推移・関連ニュース件数＋既存のテーマ→
    イベント対応表（半導体市況・金利動向等）からの機械的な列挙
  - 崩れる条件［AI分析］: テーマ別診断のRisk（失速要因）を転記
  - 投資仮説まとめ: Stock Intelligenceと同じinvestment_storyロジックによる
    時系列の因果チェーン（テーマ→Catalyst→関連テーマへの波及→非断定的な結び）
・すべて既存シグナル（Theme Momentum・Lifecycle・Catalyst・Risk・Confidence・
  causal_rules・theme_relations）の転記・機械的な組み合わせのみで構成。
  目標株価・PER/EPS予想・「買い」「売り」等の推奨・期待リターンは一切生成しない
・InvestmentThesisEntry dataclass＋FutureIntelligenceBundle.investment_theses
  フィールドを追加（デフォルト値付きのため既存の呼び出し箇所に影響なし）

変更ファイル
・src/analysis/models.py
・src/analysis/future_intelligence.py
・src/report/sections.py
・src/report/html_builder.py
・src/report/mobile_builder.py
・tests/test_future_intelligence.py

pytest
175 passed

コミット
（下記参照）

## v2.3 (2026-07-05) — Data Freshness & News Quality v2.0

追加・改善（鮮度タイブレーク＋可視化＋ログ強化のみ。重要度スコアの算出・
Momentum・Confidence・Watchlist判定・Executive Summaryの設計は一切変更なし）

・News Rankingの鮮度タイブレーク（最優先）: 順位決定を
  「スコア → 記事日時（pubDate）の新しい順 → 取得順」へ変更。
  スコア自体は不変のため、スコア差がある場合の順位は従来と完全に同じ。
  同点の場合のみ、新しい記事が古い記事より上位になる
  （従来は取得順のみで、数日前の高スコア記事が毎日1位に再選出され続ける
  根本原因になっていた——前回のRoot Cause Investigation v2で実証済み）。
  日時を解析できない記事は同点内の最後尾に回す。
・News Freshness Score: 各記事の経過時間から★1〜5を内部算出
  （24h未満★5／48h未満★4／72h未満★3／96h未満★2／それ以上★1）。
  表示専用でランキングには影響しない。
・News Freshnessカード（HTML版・レポート上部）: 最新ニュース日時／最も古い
  採用記事日時／採用記事平均経過時間／採用記事件数／RSS取得件数／
  ランキング対象件数／レポート生成日時／データ鮮度評価（★＋ラベル）
・Data Qualityセクション（HTML版・引用一覧の下）: ニュース取得★／市場データ★／
  Future Intelligence★／Watchlist★（いずれも取得できた割合からの機械的評価）
  ＋更新日時・最新ニュース・平均鮮度・情報源数・ランキング対象件数
・GitHub Actions Job Summaryへ「Data Freshness Summary」を追加:
  RSS取得件数／重複削除後件数／ランキング1位の記事日時・タイトル／
  Executive Summary・Dashboard採用記事日時／HTML生成時刻／鮮度評価
・同じくJob Summaryへ「RSS Source Health」を追加: 情報源ごとに
  成功／取得失敗（0件）・件数・最新記事日時を一覧表示。
  ローカル実行時も同内容をINFOログへ出力（取得失敗が初めて可視化される）
・実装は新設の src/analysis/data_freshness.py に集約（読み取り専用の計測
  レイヤー。将来の鮮度加点・情報源信頼度・速報フラグはここへ追加できる構造）

変更ファイル
・src/analysis/data_freshness.py（新規）
・src/analysis/news_ranking.py
・src/collectors/news.py
・src/report/html_builder.py
・main.py
・tests/test_data_freshness.py（新規）

pytest
168 passed

コミット
（下記参照）

## v2.2 (2026-07-04)

追加・改善（UI・操作性のみ。分析ロジック・スコアリング・Future Intelligence／
Watchlist Intelligence／Stock Intelligenceの判定には一切変更を加えていない）

・Today's Action（HTML／Markdown／モバイル共通）: Future Intelligence Engine
  の最上部に、その日確認すべき事項を3〜5件表示。既存のTheme Momentum Score
  最上位テーマ・ドル円レートの有無・本日のイベント・業界モメンタム最上位・
  「決算」を含む既存ニュース見出しの有無だけから機械的に組み立てる
  （`format_utils.todays_action_items()`。新しい予測・分析は行わない）

・HTML版 UI改善
  - 画面右下に常時表示の「↑ TOP」ボタンを追加（Today's Dashboardへスムーズ
    スクロール。`scroll-behavior: smooth`のみ、追加JSなし）
  - 各セクション末尾に「← 前」「次 →」のワンタップ移動ボタンを追加
  - Future Intelligenceの5大ブロック（Today's Future Signals／Theme
    Intelligence／Industry Intelligence／Stock Intelligence／Long-term
    Strategy）を`<details>/<summary>`による開閉式に変更
    （デフォルトはToday's Future Signalsのみ展開、他は折りたたみ。追加JS不要）
  - 既存のMomentum Score・Confidence Scoreが80以上のテーマにのみ「NEW」
    バッジを表示（新しいスコア算出ロジックではなく、既存スコアへの機械的な
    閾値判定のみ）
  - 目次・Future Intelligenceの重要度★表示を★の数に応じて色分け
    （★5=赤／★4=オレンジ／★3=青／★2以下=グレー）
  - 各セクション右上に📋コピー ボタンを追加（そのセクションのテキストのみを
    クリップボードにコピー）
  - Future Intelligence内のテーマ名・銘柄名について、Theme Intelligence／
    Stock Intelligenceの該当項目が存在する場合のみジャンプリンク化
    （既存のtheme_diagnosis.label／stock_intelligence.tickerとの一致判定の
    みで、新たな関連付けロジックは追加していない）
  - Today's Dashboardの主要指標を画面上部に小さく残す
    sticky（position: sticky）ミニバーを追加
  - モバイル向けにボタン・タップ領域のサイズを拡大

・HTML版 表示オプションパネル（レポート上部に新規カード）
  - コンパクト表示 / 詳細表示切替（コンパクト時は各セクションの詳細説明
    文・凡例のみを非表示にし、見出し・数値・★評価等の要点は残す）
  - 営業セクション一括非表示（営業準備／営業トーク／営業向けコメント／
    岡三証券営業向けコメント／朝会コメント／想定質問と回答例）
  - Future Intelligenceの全ブロック一括開閉ボタン
  - ライト／ダークモード切替（CSS変数の上書きのみ。既存の色分け配色は
    そのまま維持）
  - 上記4設定はlocalStorageに保存し、次回表示時も維持する
  - 外部ライブラリ・フレームワークは使用せず、素のJavaScriptのみで実装

・Markdown版・モバイル版はTable of Contents/表示内容そのものは変更せず、
  Today's Actionの追加のみ反映（表示オプション・折りたたみ等のUI操作は
  HTML版のみ対応）

変更ファイル
・src/report/format_utils.py
・src/report/sections.py
・src/report/html_builder.py
・src/report/mobile_builder.py
・src/report/builder.py
・tests/test_future_intelligence.py
・tests/test_html_builder.py
・tests/test_report_builder.py
・tests/test_mobile_builder.py

pytest
155 passed

コミット
（下記参照）

## v2.1 (2026-07-04)

追加・改善（情報設計・UIのみ。新しい分析ロジック・スコアリング・判定は追加していない）
・Future Intelligence Engine v2.1: 既存14項目（世界のメガトレンド／Theme
  Momentum Score／Early Signal Detection／世界のお金の流れ／テーマ成熟度
  メモ／テーマ別診断／次に来る業界／サプライチェーン分析／国家戦略メモ／
  Future Map／日本株への波及／Watchlist Intelligence／Stock Intelligence／
  中長期テーマ）を「世界→テーマ→業界→銘柄→長期戦略」の5ブロック
  （Information Architecture）へ再構成
  - ① Today's Future Signals ★★★★★（世界のメガトレンド／Theme Momentum
    Score／Early Signal Detection／世界のお金の流れ／今日もっとも重要な
    変化＝既存Theme Momentum Score最上位の理由をそのまま抜粋するハイライト）
  - ② Theme Intelligence ★★★★★（テーマ成熟度メモ／テーマ別診断＝
    Momentum→Lifecycle→Catalyst→Risk→Confidence→関連テーマ）
  - ③ Industry Intelligence ★★★★☆（次に来る業界／サプライチェーン分析／
    国家戦略メモ／Future Map）
  - ④ Stock Intelligence ★★★★★（日本株への波及／Watchlist Intelligence／
    Stock Intelligence＝銘柄別投資ストーリー）
  - ⑤ Long-term Strategy ★★★★☆（中長期テーマ＝半年〜10年の時間軸）
  - 各ブロック冒頭に「このブロックで分かること」を1〜2行で表示、重要度★を
    表示、Future Intelligence専用の内部目次を追加
  - HTML版: 各大ブロックをカード化し、Today's Future Signals=青／Theme
    Intelligence=紫／Industry Intelligence=緑／Stock Intelligence=
    オレンジ／Long-term Strategy=ゴールドに色分け。目次から各ブロックへ
    ジャンプ可能
  - モバイル版: 折りたたみは使わず、見出し（###）を大きくしてスクロール
    で読める形に変更（内容は既存の条件付きハイライトのまま。Long-term
    Strategyのみ既存bundle.horizon_groupsを新たに表示に追加）
・レポート全体の目次を「投資家が毎朝見る順番」＝重要度順に再構成
  （今日の結論→AI Executive Summary→岡三ストラテジスト視点→Future
  Intelligence Engine→今日の相場シナリオ→…の順）。Future Intelligence
  Engineは全体目次では1項目のみ表示し、内部の5ブロック専用目次を別途持つ。
  HTML・Markdown・モバイルの3形式すべてで同じ順序・重要度★表示に統一
・Markdown版に目次（`## 目次`）を新規追加（HTML版は既存の目次カードの並びを
  変更、モバイル版はセクション番号を並び替え）

これにより、毎朝「上から順番に読むだけ」で世界情勢→マーケット→テーマ→
業界→銘柄→投資判断へ自然につながる構成になった。分析ロジック・
スコアリング・各セクションの表示内容そのものは一切変更していない。

変更ファイル
・src/report/sections.py
・src/report/html_builder.py
・src/report/mobile_builder.py
・src/report/builder.py
・tests/test_future_intelligence.py
・tests/test_report_builder.py
・tests/test_html_builder.py
・tests/test_mobile_builder.py

pytest
142 passed

コミット
（下記参照）

## v2.0 (2026-07-04)

追加
・Future Intelligence Engine v2.0: 「Stock Intelligence」を追加（既存の
  Future Intelligence Engineセクション内に追加。Watchlist Intelligenceで
  一致した銘柄のみを対象）
  - 表示項目: 銘柄名・ティッカー・関連テーマ・関連テーマ数・Momentum・
    Lifecycle・Catalyst・Risk・Confidence・現在の判断（注目継続／押し目待ち
    ／過熱警戒／材料待ち／判断材料不足。既存のWatchlist Intelligenceの
    判定ルールをそのまま流用し整合性を維持）
  - 新規項目①なぜ長期で見るのか: テーマ名・Catalyst・Lifecycle・Momentum
    のみから機械的に組み立てた定性文
  - 新規項目②今後注目するイベント: 決算・設備投資動向に加え、関連テーマ
    （半導体市況・電力需給・金利動向・為替動向等）から機械的に導出。
    AIによる新たな予測はしない
  - 新規項目③注意すべきリスク: 既存Riskを複数テーマ分まとめて拡張表示
  - 新規項目④関連するテーマ: config.yamlのtheme_relations（Cross Theme
    Mapping）をそのまま利用
  - 新規項目⑤投資ストーリー: テーマ名→Catalyst→関連テーマへの波及→
    非断定的な結び、という時系列の因果チェーンのみで構成。目標株価・
    PER/EPS予想・「買い」「売り」等の推奨・期待リターンは一切生成しない
  - Markdown・モバイル版・HTML版すべてに反映（既存のFuture Intelligence
    Engineセクション内。他のセクション構成・既存のWatchlist Intelligence
    のロジックは変更していない）

これにより、Future Intelligence → Watchlist Intelligence → Stock
Intelligence まで一気通貫で分析できるようになった
（世界の変化→テーマ→企業→長期投資ストーリー）。

変更ファイル
・src/analysis/models.py
・src/analysis/future_intelligence.py
・src/report/sections.py
・src/report/html_builder.py
・src/report/mobile_builder.py
・tests/test_future_intelligence.py

pytest
136 passed

コミット
（下記参照）

## v1.16 (2026-07-04)

追加
・Future Intelligence Engine v1.9: Macro Themeを17拡張し、Watchlist
  Intelligenceの一致率をさらに向上（新しい分析ロジックは追加せず、
  macro_themes／causal_rules／sectors／theme_relationsの辞書拡張のみ）
  - 追加テーマ: 自動車／EV／蓄電池／金融／金利／為替／消費／人材／広告／
    SaaS／スマートフォン／クラウド／決済／旅行／住宅／建設／インバウンド
    （物流は既存テーマのため、causal_rulesのみ追加して強化）
  - 単純な業種分類ではなく「投資テーマとの経済的な因果関係」を優先して
    紐付け（例: 自動車→EV→蓄電池→半導体・電力・資源、金利→金融→為替、
    AI→クラウド→データセンター→電力）
  - config.yamlのtheme_relationsを拡張し、テーマ別診断の「関連テーマ」
    表示を強化
  - Markdown・モバイル版・HTML版すべてに反映（既存のFuture Intelligence
    Engineセクション内。他のセクション構成・既存の診断ロジックは変更して
    いない）

Watchlist Intelligence改善効果（手元のconfig.yamlで実測、監視銘柄30件）
  - 追加前（v1.8時点）: 判断材料不足 6件 ／ 一致率 24/30（80%）
    （未一致: トヨタ自動車・三菱UFJ・リクルート・デンソー・Apple・Tesla）
  - 追加後（v1.9）: 判断材料不足 0件 ／ 一致率 30/30（100%）
    （例: トヨタ自動車→自動車・EV・蓄電池・為替・消費、
    三菱UFJ→金融・金利・決済、Apple/リクルート→AI・半導体・人材・広告・
    SaaS・スマートフォン・クラウド・決済、Tesla→自動車・EV・蓄電池・為替・消費）

変更ファイル
・config.yaml
・tests/test_future_intelligence.py

pytest
130 passed

コミット
（下記参照）

## v1.15 (2026-07-04)

改善
・Future Intelligence Engine v1.8: Watchlist Intelligenceの精度向上
  （新しい分析ロジックは追加せず、辞書・マッピングの充実のみ）
  - config.yamlのsectors（related_tickers）・causal_rules
    （beneficiary_sectors）を、「投資テーマとの経済的な因果関係」を優先して
    拡充。例: AI関連の設備投資拡大は、半導体（東京エレクトロン等）だけで
    なく、データセンター運営主体（NTT・Microsoft・Amazon等）、電力設備・
    電気工事（きんでん・日立製作所）、電線・素材（古河電工・住友電工等）
    まで、単純な業種分類ではなくサプライチェーン・設備投資の因果関係で
    紐付けた
  - config.yamlに theme_relations（テーマ同士の対応付け。人手による参考
    情報でAIによる生成ではない）を新設し、テーマ別診断に「関連テーマ」
    （例: AI→半導体・電力・サイバーセキュリティ・自動運転・量子）を追加
  - Watchlist Intelligenceで「判断材料不足」になる銘柄をテスト環境で
    実際に削減できることを確認（テストで検証）
  - Markdown・モバイル版・HTML版すべてに「関連テーマ」を反映（既存の
    Future Intelligence Engineセクション内。他のセクション構成・既存の
    診断ロジックは変更していない）

変更ファイル
・config.yaml
・src/analysis/models.py
・src/analysis/future_intelligence.py
・src/report/sections.py
・src/report/html_builder.py
・src/report/mobile_builder.py
・tests/test_future_intelligence.py

pytest
127 passed

コミット
（下記参照）

## v1.14 (2026-07-04)

追加
・Future Intelligence Engine v1.7: 「Watchlist Intelligence（監視銘柄×
  テーマ診断）」を追加（既存のFuture Intelligence Engineセクション内に
  小見出しとして追加）
  - config.yamlのwatchlist銘柄（jp_stocks/us_stocks）と、v1.6のテーマ別
    診断（Momentum・Lifecycle・Catalyst・Risk・Confidence）を、既存の
    causal_rules恩恵銘柄ロジック（テーマ→beneficiary_sectors→
    related_tickers）だけを使って照合し、長期の資産形成・投資判断のために
    「今見るべき銘柄」を整理する。営業利用ではなく自分自身の投資判断を
    最優先目的とする
  - 表示項目: 銘柄名・ティッカー・関連テーマ・Momentum・Lifecycle・
    Catalyst・Risk・Confidence・現在の判断ラベル・判断理由
  - 判断ラベルは「注目継続／押し目待ち／過熱警戒／材料待ち／判断材料不足」
    のみを使用し、「買い」「売り」等の断定的な売買助言は一切行わない
  - Markdown・モバイル版・HTML版すべてに反映（既存のFuture Intelligence
    Engineセクション内。他のセクション構成は変更していない）

変更ファイル
・src/analysis/models.py
・src/analysis/future_intelligence.py
・src/report/sections.py
・src/report/html_builder.py
・src/report/mobile_builder.py
・tests/test_future_intelligence.py

pytest
123 passed

コミット
（下記参照）

## v1.13 (2026-07-04)

追加
・Future Intelligence Engine v1.6:「テーマ別診断（Momentum→Lifecycle→
  Catalyst→Risk→Confidence）」を追加（既存のFuture Intelligence Engine
  セクション内に小見出しとして追加）
  - 本システムの最優先目的を「営業ツール」ではなく「世界の変化をいち早く
    察知し、長期の資産形成・投資判断に役立てる未来分析システム」と位置づけ、
    macro_themeごとにMomentum→Lifecycle（フェーズ・継続性）→Catalyst
    （加速要因）→Risk（失速要因）→Confidence（分析根拠の充実度）の順で表示
  - Catalyst（加速要因）・Risk（失速要因）は、ニュース・Executive Summary・
    Theme Momentum・Early Signal・causal_rules・durable_themes・
    サプライチェーン（恩恵銘柄）・国家戦略メモ・世界のお金の流れという
    既存シグナルのみから機械的に導いた「AI分析」であることを明記し、
    具体的な数値・政策名・企業業績の断定はしない
  - Confidence Score（0〜100）は「未来が当たる確率」ではなく、上記シグナル
    のうち実際に確認できたものの数（＝分析根拠の充実度）を表すことを明記
  - Markdown・モバイル版・HTML版すべてに反映（既存のFuture Intelligence
    Engineセクション内。他のセクション構成は変更していない）

変更ファイル
・src/analysis/models.py
・src/analysis/future_intelligence.py
・src/report/sections.py
・src/report/html_builder.py
・src/report/mobile_builder.py
・tests/test_future_intelligence.py

pytest
120 passed

コミット
（下記参照）

## v1.12 (2026-07-04)

追加
・Future Intelligence Engine v1.5:「世界のお金の流れ（市場シグナルベース）」を
  安全な縮小版として追加（既存のFuture Intelligence Engineセクション内に
  小見出しとして追加）
  - 実際の機関投資家ポジション・資金流入額は取得していないため、具体的な
    資金フローは断定しない旨を冒頭に明記（「実際の資金流入額ではなく、
    公開市場データとニューステーマから見た資金の向かいやすさです」）
  - 公開市場データ（日経平均・TOPIX・NASDAQ・SOX・VIX・米10年金利・
    ドル円・WTI・金）とTheme Momentum Score・Early Signal Detection・
    Sector Ranking・causal_rules・durable_themesという既存シグナルのみ
    から、「AI・半導体」「金融・銀行」「防衛・電力・インフラ」「内需・消費」
    「コモディティ・資源」の5テーマについて、資金方向ラベル（流入しやすい／
    中立／流出しやすい／判断材料不足）・理由・関連テーマ・関連セクター・
    営業で話すポイントを機械的に算出
  - リスクオン/オフ・グロース優位/バリュー優位の参考情報も、VIX指数・
    NASDAQ対TOPIXという既存の市場データのみから算出し、文脈情報として付記
  - 「資金が流入している」「機関投資家が買っている」「海外勢が買っている」
    「◯億円流入」等の断定・捏造表現は一切使わず、「資金が向かいやすい」
    「物色されやすい」「市場シグナル上は追い風」等の非断定表現に統一
  - Markdown・モバイル版・HTML版すべてに反映（既存のFuture Intelligence
    Engineセクション内。他のセクション構成は変更していない）

変更ファイル
・main.py
・src/analysis/models.py
・src/analysis/future_intelligence.py
・src/report/sections.py
・src/report/html_builder.py
・src/report/mobile_builder.py
・tests/test_future_intelligence.py

pytest
116 passed

コミット
（下記参照）

## v1.11 (2026-07-04)

改善
・Future Intelligence Engine v1.4: Theme Momentum Score・Early Signal Detectionの
  判定材料を拡張
  - Theme Momentum Score: 本日の関連見出し件数・重要ニュースとの一致・
    causal_rules該当・durable_themes該当に加えて、Executive Summary
    （executive_summary.pyが算出した本日最重要ニュース）との一致、および
    既存のcausal_rules恩恵銘柄ロジックから導ける関連セクター・関連銘柄の
    有無という既存シグナルを追加（0〜100点への配分を6シグナル分に再配分）。
    理由欄には、世界のメガトレンド評価（★・フェーズ）を文脈として明記する。
    関連セクター・関連銘柄も新たに表示する
  - Early Signal Detection: 判定条件（見出しが少ない・causal_rules該当・
    durable_themes該当・恩恵銘柄が解決できる）は変更せず、恩恵銘柄が
    解決できるという既存条件を「営業利用価値がある」ことの根拠として明記した
    うえで、関連セクター・関連銘柄という実データのみから機械的に組み立てた
    「営業で話すポイント」を追加
  - いずれも具体的な市場規模・件数以外の断定的な数値は生成しない
  - Markdown・モバイル版・HTML版すべてに反映（既存のFuture Intelligence
    Engineセクション内。他のセクション構成は変更していない）

変更ファイル
・main.py
・src/analysis/models.py
・src/analysis/future_intelligence.py
・src/report/sections.py
・src/report/mobile_builder.py
・src/report/html_builder.py
・tests/test_future_intelligence.py

pytest
111 passed

コミット
（下記参照）

## v1.10 (2026-07-04)

改善
・Future Intelligence Engine v1.3: 「テーマ成熟度メモ」「国家戦略メモ」を
  「未登録」中心の表示から、既存シグナルからのAI分析を優先表示する方式に改善
  - 表示の優先順位: ① `config.yaml` への手動登録があれば最優先で「登録情報」
    として表示 → ② 手動登録が無くても、本日の関連見出し件数・durable_themes
    該当・causal_rules該当・恩恵銘柄という既存シグナルがあれば、そこから
    導いたルールベースの定性的な「AI分析」を表示 → ③ 判断材料となる信号が
    何も無い場合のみ「分析材料不足」と表示（「未登録」だけで終わる表示を削減）
  - 国家戦略メモは、国・地域とmacro_themesの重点分野を対応付けた人手による
    参考情報（`NATIONAL_FOCUS_AREAS`。AIが生成したものではない）を追加し、
    未登録の国・地域でも本日のテーマ動向からAI分析を導けるようにした
  - いずれの表示も「登録情報」「AI分析」「分析材料不足」のラベルと判断根拠
    （どの既存シグナルから導いたか）を明記し、具体的な市場規模・補助金額・
    政策名・法案名は一切生成しない（「〜と考えられます」等の非断定表現に統一）
  - Markdown・モバイル版・HTML版すべてに反映（既存のFuture Intelligence
    Engineセクション内。他のセクション構成は変更していない）

変更ファイル
・src/analysis/models.py
・src/analysis/future_intelligence.py
・src/report/sections.py
・src/report/mobile_builder.py
・src/report/html_builder.py
・tests/test_future_intelligence.py

pytest
108 passed

コミット
（下記参照）

## v1.9 (2026-07-04)

追加
・Future Intelligence Engine v1.2: 「テーマ成熟度メモ」「国家戦略メモ」を追加
  （既存のFuture Intelligence Engineセクション内に小見出しとして追加）
  - テーマ成熟度メモ: `config.yaml` の `theme_maturity_notes`（macro_themes
    の各テーマについて、市場ステージ／市場規模メモ／普及状況メモ／
    競争環境メモ／参入障壁メモ／リスクメモを手動登録）をそのまま表示。
    AIによる市場規模・普及率等の生成・推定は一切行わない
  - 国家戦略メモ: `config.yaml` の `national_strategy_notes`（日本／米国／
    中国／EU／インド／中東の6地域固定で、重点分野・政策メモ・規制メモ・
    市場影響メモを手動登録）をそのまま表示。AIによる補助金額・政策内容の
    生成・推定は一切行わない
  - いずれも未登録のテーマ・国・項目は「未登録」と明記する
  - `config.yaml` には空の `theme_maturity_notes: {}` / `national_strategy_notes: {}`
    と、コメントアウトされた記入例のみを追加（デフォルトはすべて「未登録」）

変更ファイル
・config.yaml
・src/analysis/models.py
・src/analysis/future_intelligence.py
・src/report/sections.py
・src/report/mobile_builder.py
・src/report/html_builder.py
・tests/test_future_intelligence.py

pytest
105 passed

コミット
（下記参照）

## v1.8 (2026-07-04)

追加
・Future Intelligence Engine v1.1: Theme Momentum Score と Early Signal
  Detection を追加（既存のFuture Intelligence Engineセクション内に小見出しとして追加）
  - Theme Momentum Score: 各macro_themeについて、本日の関連見出し密度・
    本日の重要ニュース（news_ranking）との一致・causal_rules該当・
    durable_themes該当という既存シグナルのみから0〜100の定性スコアを算出。
    前日比・週次比較は行わない（履歴データを保持していないため）。
    急加速／加速／横ばい／減速の4段階ラベルと理由を付与
  - Early Signal Detection: 本日の見出し件数はまだ少ない（1件以下）ものの、
    causal_rules該当・durable_themes該当・恩恵銘柄が解決できる、という
    条件をすべて満たすテーマを「初動シグナル」として抽出（★・理由・
    関連セクター・代表的な関連銘柄を表示）
・詳細版・モバイル版・HTML版すべてに反映（既存のFuture Intelligence Engine
  セクション内。他のセクション構成は変更していない）

変更ファイル
・src/analysis/models.py
・src/analysis/future_intelligence.py
・main.py
・src/report/sections.py
・src/report/mobile_builder.py
・src/report/html_builder.py
・tests/test_future_intelligence.py

pytest
101 passed

コミット
（下記参照）

## v1.7 (2026-07-04)

追加
・Future Intelligence Engine v1.0（グループAのみ）を新設。世界の長期テーマ
  （config.yaml `macro_themes`。AI/半導体/電力/GX/DX/防衛/宇宙/量子/核融合/
  ロボット/医療/バイオ/サイバーセキュリティ/水インフラ/物流/資源/食料/
  人口減少/高齢化/自動運転の20テーマ）を、既存の
  `durable_themes`・`causal_rules`・本日の関連見出し件数・恩恵銘柄ロジックの
  みから定性的に評価する新モジュール `src/analysis/future_intelligence.py`
  - 世界のメガトレンド（★・フェーズ［黎明期/成長初期/急成長期/成熟期/減速期］・
    継続性［高い/中程度/限定的］・なぜ伸びるか）
  - 次に来る業界ランキング（本日のモメンタム順）
  - サプライチェーン分析（causal_rulesの因果チェーンを再利用）
  - 中長期テーマ（半年/1年/3年/5年/10年への定性的な割り付け）
  - 日本株への波及（恩恵銘柄。大型/中小型は区分不明として明記）
  - Future Map（テーマ一覧）
  - 詳細版・モバイル版・HTML版すべてに「Future Intelligence Engine」として
    1セクションにまとめて追加（既存セクション番号は変更せず末尾に追加）
・具体的な残り年数・市場規模・補助金額等は一切生成しない（実データの裏付けが
  ない数値は使わない方針を徹底）。テーマ成熟度・国家戦略分析・世界のお金の
  流れはv1.1以降に見送り（設計提案書のグループB/Cに該当）

変更ファイル
・config.yaml
・main.py
・src/analysis/models.py
・src/analysis/future_intelligence.py【新規】
・src/report/builder.py
・src/report/sections.py
・src/report/mobile_builder.py
・src/report/html_builder.py
・tests/test_future_intelligence.py【新規】
・tests/test_report_builder.py
・tests/test_mobile_builder.py
・tests/test_html_builder.py

pytest
97 passed

コミット
（下記参照）

## v1.6 (2026-07-04)

改善
・HTML上部の「最新情報に更新」ボタンの仕様を変更。GitHub Actionsの
  workflow_dispatch実行ページへ遷移する方式から、`javascript:location.reload()`
  によるページ再読み込みのみのボタン（「🔄 最新表示に更新」）へ変更。
  外部JS不要・常時表示（`actions_url`の有無に依存しない）
・毎朝の自動生成・自動デプロイを基本運用とし、手動でのワークフロー実行は
  README上で補足的な案内に位置づけ直した

修正
・（なし）

判断: `config.yaml` の `output.actions_url` と `main.py` の
`_resolve_actions_url()` は削除せず残した。html_builder.py側では
未使用になったが、main.pyからbuild_html_reportへの`actions_url`引数は
削除するとmain.py・config.yamlの2ファイルに追加の変更が必要になり、
現時点で機能上のメリットがない削除のために変更範囲を広げるのは
「最小差分」の方針に反すると判断したため。将来この設定を使う機能
（例: 別ボタンでのActions画面誘導を復活させる等）を追加する際に
そのまま再利用できる。

変更ファイル
・src/report/html_builder.py
・tests/test_html_builder.py
・README.md

pytest
90 passed

コミット
（下記参照）

## v1.5 (2026-07-04)

修正
・`deploy-pages` ジョブの `actions/deploy-pages@v4` ステップから
  `timeout: 1200000 / error_count: 10 / reporting_interval: 10000` の指定を削除。
  `timeout` の許容上限（60000ミリ秒）を超えていたため警告が出ており、
  デプロイ失敗（`エラー：展開に失敗しました。後で再挑戦してください。`）と
  合わせて発生していた。既定動作（アクション側のデフォルト設定）に戻すことで解消
・`generate-report` ジョブ、`deploy-pages` ジョブの `timeout-minutes: 20`、
  GitHub Pages の Source/Environment 設定は変更していない

変更ファイル
・.github/workflows/daily-market-brief.yml

pytest
91 passed

コミット
（下記参照）

## v1.4 (2026-07-04)

修正
・`build_html_report()` に `actions_url` キーワード引数が定義されておらず、
  GitHub Actions実行時に `got an unexpected keyword argument 'actions_url'`
  という警告が出ていた不整合を修正。`actions_url: Optional[str] = None` を
  明示的に追加し、`main.py` からの呼び出しと整合させた
・`actions_url` が `None`（または空文字）の場合は「最新情報に更新」ボタンを
  表示しない挙動を維持（既存ロジックのまま、型ヒントのみ明確化）

変更ファイル
・src/report/html_builder.py
・tests/test_html_builder.py

pytest
91 passed

コミット
（下記参照）

## v1.3 (2026-07-04)

追加
・HTMLレポート（Today's Dashboardのすぐ下）に「🔄 最新情報に更新」ボタンを追加。
  押すとGitHub Actions「Daily Market Brief」ワークフローの実行ページへ遷移し、
  そこで「Run workflow」を押せば最新ニュース・最新データでレポートを再生成できる
・`config.yaml` の `output.actions_url`（環境変数 `ACTIONS_URL` でも上書き可）で
  ボタンのリンク先を明示できるように設定を追加。未設定時は
  `GITHUB_REPOSITORY` から自動組み立て、どちらも無ければボタン自体を非表示

変更ファイル
・main.py
・src/report/html_builder.py
・config.yaml
・tests/test_html_builder.py
・README.md

pytest
90 passed

コミット
（下記参照）

## v1.2 (2026-07-04)

改善
・`CLAUDE.md` に「設計原則」（ディレクトリ構成／システム設計／ファイル名／
  設定ファイル構成／ワークフロー／GitHub Actions・Pages／ニュース評価ロジック／
  スコアリングロジック／営業思想／ストラテジスト思想／UIデザイン／出力フォーマット
  はChatGPT（監督者）が決定し、Claude Codeは提案のみ行う）を追加
・「リファクタリング」ルール（依頼のない限りリネーム・ファイル移動・関数統合・
  大規模整理・不要コード削除を禁止）を追加

変更ファイル
・CLAUDE.md

pytest
89 passed（コード変更なし。既存スイートに影響なし）

コミット
（下記参照）

## v1.1 (2026-07-04)

改善
・`CLAUDE.md` を、ユーザー提示の15項目「更新ポリシー」を最上位ルールとして
  明記する形に更新（リポジトリ全体を書き換えない／変更ファイルのみ提出／
  ZIPは依頼時のみ／フォルダ構成・Git構成・GitHub Pages/Actions/Secretsは
  依頼がない限り変更しない、等）

変更ファイル
・CLAUDE.md

pytest
（コード変更なしのため実行対象なし。既存89件のスイートに影響なし）

コミット
（下記参照）

## v1.0 (2026-07-04)

追加
・岡三証券の内部ストラテジストレポート（「グローバル投資の羅針盤」5号分）から
  学習した「ニュース評価・投資アイデア変換」の思考プロセスを一般化し、
  `src/analysis/strategist_engine.py` として実装
・8軸★スコアリング（市場インパクト／継続性／営業利用価値／日本株影響度／
  米国株影響度／個別株へ展開できるか／テーマ株へ展開できるか／今後数週間重要か）
・「ニュース→岡三ストラテジストならどう見るか→重要テーマ→関連セクター→
  恩恵銘柄→悪影響銘柄→営業で話すポイント→重要度」パイプラインと、
  レポート新セクション「岡三ストラテジスト視点」（詳細版・モバイル版・HTML版）
・`config.yaml` に `causal_rules`（因果チェーンルール）・`durable_themes`
  （継続性の高いテーマ一覧）を追加

改善
・`news_ranking.py` の重要度スコアに、因果チェーン該当・継続性の高いテーマ
  該当の加点を追加（既存スコアリングへの後方互換は維持）
・`executive_summary.py` に恩恵銘柄／悪影響銘柄／ストラテジスト視点の
  一言まとめを追加

変更ファイル
・config.yaml
・main.py
・src/analysis/executive_summary.py
・src/analysis/models.py
・src/analysis/news_ranking.py
・src/analysis/strategist_engine.py【新規】
・src/report/builder.py
・src/report/html_builder.py
・src/report/mobile_builder.py
・src/report/sections.py
・tests/test_mobile_builder.py
・tests/test_report_builder.py
・tests/test_strategist_engine.py【新規】
・README.md
・CLAUDE.md【新規】
・CHANGELOG.md【新規】

pytest
89 passed

コミット
6834f70
