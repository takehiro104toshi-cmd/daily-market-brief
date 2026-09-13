# COMPASS_GENERATOR_SPEC — Evidence-Grounded Compass Generator（Phase 3-C / 2026-09-01）

Fact Layer（3-A）＋ Compass Context Engine（3-B）で確認された情報 **だけ** を根拠に、
Morning Compassとして利用可能な **grounded narrative** を生成する層。

> LLM MAY WRITE. LLM MAY NOT INVENT.

## 0. 位置づけ

```
DATA → OBSERVATION → FACT(3-A) → CONTEXT(3-B) → NARRATIVE(3-C) → OUTLOOK → COMPASS
```

Phase 3-Cは初めて自然言語生成を導入するが、**「LLMに相場を自由に考えさせる」Phaseではない**。
generator（決定論的 / LLM / fake）は **Evidence Package と Narrative Plan の範囲内でしか
書けず**、書いたものは全て validator と quality gate を通る。合否を決めるのは generator
ではなく validator である。

| 3-Cで作る | 3-Cで作らない |
|---|---|
| 根拠ID付きの claim（HEADLINE〜COVERAGE） | 根拠の無い文章・相場観 |
| 決定論的 outlook（方向・確度・無効化条件） | 因果断定（「金利上昇が株を押し下げた」） |
| 反対材料（RISK）の常設 | 投資助言（買い/売り/目標株価） |
| 語れない次元の明示（COVERAGE） | 欠落次元についての推測 |
| 顧客向け one-liner（2〜4文） | HTML / GitHub Pages への出力（本Phase対象外） |

## 1. パイプライン（`pipeline.py`）

```
Morning Context Snapshot（3-B）
  → Evidence Package（決定論的・look-ahead FAIL-CLOSED・budget）
  → Outlook（決定論的・fresh AVAILABLE contextのみ）
  → Narrative Plan（決定論的・lead/support/counter/coverage/prohibited）
  → generator（deterministic | LLM boundary | fake）  ※ grounding_status = PENDING
  → Quality gate（grounding / numeric / direction / temporal / missingness / language）
  → repair（REJECTED は provenance として残し、必須role欠落を決定論的に補う）
  → one-liner（2〜4文・validator付き）
  → CompassDraft（content-addressed `draft_id`）
```

- generatorが利用不可（LLM provider未設定等）なら **決定論的生成へフォールバック** し
  `generator_fallback` に理由を残す（例外で止めない・secretを要求しない）。
- 非決定論的generatorの生成物が quality gate で REJECTED（棄却率超過）なら、生成物を
  **丸ごと破棄** して決定論的生成へ置き換える（`generator_output_rejected`）。

## 2. Evidence Package（`evidence_package.py`）

generatorが見られるのは **このpackageだけ**（それ以外の情報は存在しない扱い）。

- **look-ahead禁止**: 支持Factの `known_at` が朝のcutoffを超えるContextは除外し、
  `excluded_look_ahead` に記録する（黙って落とさない）。
- **unusable/missing fact**: 支持Factがpackageに無い・使用不可のContextも除外して記録。
- **evidence budget**（`config.yaml: compass_generator.evidence_budget`）:
  salience tier（PRIMARY→core 8 / SECONDARY→supporting 8 / BACKGROUND→optional 4）。
  超過分は `excluded_over_budget`。各次元の代表Context（`dimension_context_ids`）は
  core に固定して落とさない。
- **missingness保持**: 欠落・STALE・CONFLICTED・LIMITED_USE の次元
  （`unreliable_dimensions`）をpackageに持ち、COVERAGE claim と validator が使う。
- **Factを複製しない**: 参照するFact本体は呼び出し側が `facts` で渡す。
- `prompt_payload()` は **whitelistしたフィールドのみ**（note / excerpt / locator を渡さない）。

## 3. Outlook（`outlook.py`）— 決定論的

Contextを Compass DNA の経験則で **含意**（POSITIVE / NEGATIVE / NEUTRAL）へ分類する。
`rule_ref` は claim の provenance として残る。

| Context | 含意 | rule_ref |
|---|---|---|
| TOPIX 前営業日 UP / DOWN | POSITIVE / NEGATIVE | JP_DIR_001 |
| 米10年利回り UP / DOWN | NEGATIVE / POSITIVE | JP_US_001 |
| USDJPY WEAKER（円安）/ STRONGER | POSITIVE / NEGATIVE | JP_FX_001 |
| MA25乖離（過熱） | NEUTRAL（risk_tag） | JP_INT_003 |
| イベント接近（≤ `near_event_days`） | NEUTRAL（risk_tag） | JP_DIR_004 |

- 根拠に使うのは **fresh**（`session_date == reference_session` かつ次元 AVAILABLE）の
  Contextのみ。古いドル円で「円安が追い風」とは語らない。
- direction: UPWARD_BIAS / DOWNWARD_BIAS / RANGE_BOUND / MIXED / UNCERTAIN（同数なら lead＝TOPIX に従う）。
- confidence ladder（決定論的・要素は `components` に全保存）:
  HIGH = 支持≥3 かつ反対0 かつ core次元欠落0 かつ近接イベント0；
  MEDIUM = 支持≥2 かつ 支持>反対 かつ core欠落≤1 かつ近接イベント0；それ以外 LOW。
- **無効化条件** は支持材料が反転した場合のみ（根拠に無い材料は挙げない）。
- **反対材料** は常設（outlookと逆符号の含意＋risk_tag付き fresh Context）。

## 4. Narrative Plan（`narrative_plan.py`）

何を語ってよいか／いけないかをIDと統制語彙だけで決める（自由文を持たない）。

- lead: `japan_equities` → `usd_jpy` → `us_rates_10y` → `japan_rates` の順で最初の代表Context。
- abstain（生成しない）: `empty_evidence_package` / `no_lead_context` /
  `lead_context_not_fresh`（leadが reference_session より古い） /
  `no_counter_material`（反対材料 < `min_counter_contexts`）。
- prohibited: causal / advice / numeric_target / unsupported_dimension。

## 5. Claim model（`model.py`）

FACT / CONTEXT / INTERPRETATION / OUTLOOK を **混ぜない**。

| claim_type | 文末 | 必須引用 |
|---|---|---|
| FACTUAL | 〜となった / 〜した / 〜であった | fact_id |
| RELATIONAL | 同時性・相対状態（因果ではない） | context_id |
| INTERPRETIVE | 〜とみられる（経験則 rule_ref 付き） | context_id |
| OUTLOOK | 〜となろう（確度: 高/中/低） | context_id |
| RISK | 反対材料 / 無効化条件 | context_id |

claim_role = HEADLINE / WHAT_HAPPENED / WHY / OUTLOOK / RISK / COVERAGE（目標出力 A–F）。
推奨語彙（bullish / bearish / buy / sell / target）は model に存在しない。

## 6. Validators（quality gate が全claimに適用）

| validator | 主な code（error） |
|---|---|
| grounding | citation_missing / fact_citation_missing / context_citation_missing / unknown_fact_id / unknown_context_id / broken_citation_chain / look_ahead_citation |
| numeric | unsupported_number（引用Factに無い数値）／ number_not_in_citations（warning） |
| direction | direction_mismatch / direction_unsupported / outlook_direction_mismatch / outlook_direction_unsupported |
| temporal | future_date / future_fact_date / invalid_date / unsupported_future_reference / unsupported_event_reference / unsupported_event_timing |
| missingness | missing_dimension_assertion / stale_dimension_assertion / conflicted_dimension_assertion / insufficient_history_assertion |
| language | unsupported_causal_claim / advice_language / numeric_target / injection_marker ／ factual_form・outlook_form（warning） |

- gate verdict: VALID / VALID_WITH_WARNINGS / REJECTED（`max_rejected_ratio` 超過）/
  ABSTAINED（根拠付き HEADLINE / WHY / OUTLOOK / RISK が残らない）。
- one-liner は HEADLINE＋OUTLOOK＋RISK から組み、文数（2〜4）・禁止語を再検査。
  失敗すれば `one_liner_unavailable` で ABSTAINED。

## 7. Generator provider boundary（`generator.py`）

- `DeterministicNarrativeGenerator`: テンプレートによる決定論的レンダラー（実データpilotの既定）。
- `LLMNarrativeGenerator`: 既存 `core.contracts.LLMProvider` 境界を通す。
  入力は `build_prompt()` の **構造化JSONのみ**（Evidence Packageはデータであり命令ではない）。
  出力は **untrusted**: JSON以外・未知ID・長すぎる文（`llm_max_claim_chars`）・claim数超過
  （`llm_max_claims`）を落とし、残りも全て validator へ回す。
  provider未設定なら `GeneratorUnavailable("llm_provider_unavailable")` → 決定論的へフォールバック。
- `FakeNarrativeGenerator`: テスト・adversarial検証で任意claimを注入する。
- **新しいAPI keyを要求しない／secretを作らない／別providerへ接続しない**（§27）。
  live pilot は決定論的generatorのみ（`llm_calls = 0`, `network_used = false`）。

## 8. Prompt injection 防御（§33）

- source content（note / excerpt / locator）は generator へ渡さない。
- `INJECTION_PATTERN`（"ignore previous instructions" / 「以前の指示」/「指示を無視」等）を
  含むclaimは `language:injection_marker` で REJECTED。
- LLM出力は構造化claimとしてのみ受け取り、ID・数値・方向・時制を根拠と突き合わせる。

## 9. Persistence（`store.py`）

- canonical: `compass/drafts.jsonl`（append-only・idempotent by `draft_id`）
- operational: `compass/index/compass.sqlite3`（canonicalから再構築可能）
- claim → fact_id / context_id の参照だけを持ち、Fact / Context 本体は複製しない。
- `draft_id` は content-addressed（同じ入力 → 同じID）。

## 10. ファイル構成

```
src/intelligence/compass/
  __init__.py  config.py  model.py  lexicon.py
  evidence_package.py  outlook.py  narrative_plan.py  generator.py
  grounding.py  numeric_validation.py  direction_validation.py
  temporal_validation.py  missingness_validation.py  language_rules.py
  quality_gate.py  one_liner.py  pipeline.py  store.py
  historical_eval.py  adversarial.py  pilot.py
tests/intelligence/test_compass_generator.py（80件）
config.yaml: compass_generator（budget / tolerance / one_liner / llm 上限）
```

## 11. 実データ実測（p2d-market-pilot run #19 / 2026-09-01 22:32-22:38 UTC）

run: https://github.com/takehiro104toshi-cmd/daily-market-brief/actions/runs/33566763923
（conclusion = success。Phase 3-C step 22:37:34–22:38:00 UTC。generator = deterministic、
LLM provider未接続、secret未注入）。

### 入力（`::P3C_INPUT::`）

- sessions: 2026-08-27 / 08-28 / 08-31 / 09-01 / 09-02（fact sessions 08-24..09-01）
- facts_total 198 / contexts_total 75 / event_facts 0

### Evidence Package（`::P3C_PACKAGE::`）

| session | reference | package_id | ctx / facts | core/supp/opt | unreliable | over_budget |
|---|---|---|---|---|---|---|
| 08-27 | 08-26 | evpkg_cc4db7825dfc5f6204d08a84 | 22 / 34 | 10/8/4 | usd_jpy STALE | 5 |
| 08-28 | 08-27 | evpkg_dc85866784b05ff9a4a3617f | 22 / 36 | 10/8/4 | usd_jpy STALE | 18 |
| 08-31 | 08-28 | evpkg_55b8b3a89f18185e1a08c3b4 | 22 / 35 | 10/8/4 | — | 33 |
| 09-01 | 08-31 | evpkg_fb4a3637a5f8fc4a8e74db02 | 22 / 33 | 10/8/4 | usd_jpy STALE | 44 |
| 09-02 | 09-01 | evpkg_d9768f4ef1767d956d4ce578 | 20 / 27 | 8/8/4 | nikkei_vs_topix / nt_ratio / japan_rates / usd_jpy STALE | — |

全sessionで `excluded_look_ahead = 0` / `excluded_unusable_fact = 0` /
`same_or_future_session_contexts = 0`。

### Narrative Plan / Outlook（`::P3C_PLAN::` / `::P3C_OUTLOOK::`）

| session | can_generate | counters | outlook | confidence | rule_refs | missing core |
|---|---|---|---|---|---|---|
| 08-27 | yes | 3 | UPWARD_BIAS | MEDIUM | JP_DIR_001, JP_US_001 | usd_jpy |
| 08-28 | yes | 1 | DOWNWARD_BIAS | MEDIUM | JP_DIR_001, JP_US_001 | usd_jpy |
| 08-31 | yes | 2 | UPWARD_BIAS | MEDIUM | JP_DIR_001, JP_US_001, JP_FX_001 | — |
| 09-01 | yes | 1 | DOWNWARD_BIAS | MEDIUM | JP_DIR_001, JP_US_001 | usd_jpy |
| 09-02 | yes | 1 | UPWARD_BIAS | LOW | JP_DIR_001, JP_US_001 | usd_jpy |

無効化条件は全sessionに存在。near_event_contexts 0。

### Quality gate（`::P3C_GATE::`）

verdicts {VALID: 5} / rejected_total 0 / warnings 0 / all_why_cite_context true /
all_risk_present true。draft: compass_4a04904f7743c1f3c4c16732（15 claims）・
compass_bb390349e076726c605141b6（13）・compass_6caaafd8494ff834981eb503（14）・
compass_3cc1bd141dcc496df476c34e（13）・compass_f267ad4239e278f209be0ad7（8）。

### Claims の例（`::P3C_CLAIMS::` / 2026-09-02の朝）

```
HEADLINE  前営業日（2026-09-01）のTOPIXは前日比+0.62%の上昇となった。終値は4,181.86であった。
WHAT      米2年国債利回りは前日比+0.050ptの上昇となった。／米10年国債利回りは前日比+0.040ptの上昇となった。
          ／米10-2年スプレッドは-0.010ptのフラット化となった。
WHY       根拠（経験則 JP_DIR_001）: TOPIXは前日比+0.62%の上昇となったことが同時に観測され、
          株式にとって追い風とみられる（因果関係は特定しない）。
OUTLOOK   次の東京セッションは堅調な展開となろう（確度: 低）。
          無効化条件: TOPIXが前営業日の方向（UP）と逆に動く場合。
RISK      反対材料（経験則 JP_US_001）: 米10年国債利回りは前日比+0.040ptの上昇となったことは、
          株式にとって逆風とみられる。
COVERAGE  対象範囲: 米国株指数・夜間先物・個別ニュースは本Evidence Packageに含まれない。
          語れない次元: nikkei_vs_topix（STALE）, nt_ratio（STALE）, japan_rates（STALE）, usd_jpy（STALE）。
```

### One-liner（`::P3C_ONE_LINER::`・全て VALID・4文）

- 08-27: 前営業日（2026-08-26）のTOPIXは前日比+0.42%の上昇となった。終値は4,111.02であった。次の東京セッションは堅調な展開となろう（確度: 中）。反対材料: 米10年国債利回りは前日比+0.020ptの上昇となったことは、株式にとって逆風とみられる。
- 08-28: TOPIX +0.15%（4,117.22）→ 軟調（確度: 中）／反対材料: TOPIX上昇は追い風
- 08-31: TOPIX +0.72%（4,146.71）→ 堅調（確度: 中）／反対材料: 米10年利回り +0.060pt は逆風
- 09-01: TOPIX +0.23%（4,156.29）→ 軟調（確度: 中）／反対材料: TOPIX上昇は追い風
- 09-02: TOPIX +0.62%（4,181.86）→ 堅調（確度: 低）／反対材料: 米10年利回り +0.040pt は逆風

### Adversarial（`::P3C_ADVERSARIAL::` / 2026-09-02 の実Evidence Package）

13 cases / 13 passed / rejected_as_expected 12 / controls_grounded 1。

| case | 検出 code |
|---|---|
| nonexistent_topix_value | numeric:unsupported_number |
| reversed_usdjpy | direction:direction_mismatch（＋stale_dimension_assertion） |
| future_earnings | temporal:unsupported_future_reference / unsupported_event_reference |
| unsupported_causal | language:unsupported_causal_claim |
| nonexistent_fact_id | grounding:unknown_fact_id |
| citation_less | grounding:citation_missing |
| missing_dimension_assertion | missingness:missing_dimension_assertion |
| conflicted_data_assertion | missingness:conflicted_dimension_assertion |
| advice_language | language:advice_language |
| numeric_target | language:numeric_target |
| prompt_injection | language:injection_marker |
| outlook_direction_mismatch | direction:outlook_direction_mismatch |
| valid_control | （GROUNDED・fake generator・fallback無し） |

12件の不正claimは全て REJECTED され、draft は `generator_output_rejected` により
決定論的生成へ置き換えられて VALID となった。

### Historical Compass evaluation（`::P3C_HISTORICAL::`）

`output/history/<date>/pre_market.html`（読み取りのみ）との観測比較。

- 水準: comparable 2 / MATCH 2（日経平均 08-27 差0.148% / 08-28 差0.245%）。
  他は NOT_AVAILABLE（履歴に水準無し・ドル円 `fx_level` Fact無し）。
- 方向: MATCH 4 / CONFLICT 2 / NOT_AVAILABLE 9（match_rate 4/6）。
  CONFLICT は 08-27・08-28 の日経平均（履歴は日経、ContextはTOPIX代表で符号差）。
- 生成側: drafts VALID 5 / all_citations_within_package true /
  rejected_claims_total 0 / look_ahead_excluded_total 0。
- 履歴Compassは観測対象であり最適化目標ではない（rule は最適化していない）。

### Store（`::P3C_STORE::`）

drafts 5 / added_first 5 / added_second 0（idempotent）/ canonical_rows 5 /
rebuilt_from_canonical 5（rebuild_match true）/ reproducible_draft_ids true /
claims_citing_first_fact 2。

### Provider / Security（`::P3C_PROVIDER::` / `::P3C_SECURITY::`）

- generator_used [deterministic] / llm_provider_configured false / llm_calls 0 /
  network_used false / fallbacks []
- secret env（JQUANTS_API_KEY / ANTHROPIC_API_KEY / OPENAI_API_KEY）present: 全て false
- secret_values_printed false / credentials_in_drafts false / generator_prompt_used false

## 12. 本Phaseで実装しないもの

- HTML / GitHub Pages への出力（既存レポート生成経路は不変）
- LLM provider の新規接続・API key の要求
- 因果関係の主張・投資助言・数値目標
- 過去Compassを再現するための rule 最適化
