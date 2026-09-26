# Phase 6 — Deterministic Theme Discovery Contract（P6-B4C）

状態: **P6_B4C_DETERMINISTIC_THEME_DISCOVERY_VALIDATED / READY_FOR_P6_B4D_DISCOVERY_E2E_FALSE_POSITIVE_GATE**。
本書は B4C runtime（`src/intelligence/theme_intelligence/discovery_model.py` / `discovery_predicates.py` / `discovery_rules.py` /
`discovery_adapter.py` / `discovery.py`）と knowledge（`knowledge/theme_intelligence/discovery_rules.<version>.yaml`）の契約を
凍結する。監督者決定 D-B4-4 / 5 / 6 / 7 / 8 / 9（B4C 指示 §0）を前提とする。Foundation（`12847bf`）・B1（`e2d5168`）・
B2（`ce2402a`）・B3（`4808f5e`）・B4B（`c776fff`）の runtime は無変更。

---

## 1. Discovery authority boundary

- **Discovery は提案する。人間が governance する。** 出力は B3 の `EvidenceCandidateProposal` / `ThemeCandidateProposal`
  （と任意の `DedupReviewProposal`）と derived な `DiscoveryRunReport` だけ。Theme root を作らず、Foundation に書かず、
  ProposalStore に書かず、decision を作らず変えず、EvidenceCandidate を自動 promotion せず、score / rank / 順位を持たない。
- rule hit ≠ Theme ≠ 機構の証明 ≠ evidence の成立 ≠ 独立 source。資格判定（source / temporal diversity）は Foundation
  `evaluate_qualification` の単独責務。
- ruleset は **VERSIONED KNOWLEDGE**（B4B taxonomy / entity と同じ authority class）。Foundation authority・evidence authority・
  proposal authority・market rule・Compass DNA のいずれでもない。

## 2. Allowed inputs（D-B4-4）

| 許可 | 条件 |
|---|---|
| `sources.model.SourceDocument` | retrieved_at ≤ cutoff、published_at ≤ cutoff（None は MISSING） |
| `databank.news_model.NewsItem`（＋ `NewsDocumentLink` は lineage のみ） | published_at ≤ cutoff（None は MISSING） |
| `facts.model.Fact` | `status == USABLE` のみ（LIMITED_USE / UNUSABLE / SUPERSEDED は除外）、known_at ≤ cutoff、primary_date が有効 |
| `market.model.Observation` | as_of ≤ cutoff |
| `ThemeResolution`（read-only） | dedup counterpart にのみ使用 |
| pinned `TaxonomySnapshot` / `EntityCatalogSnapshot` / `DiscoveryRuleset` | published_at ≤ cutoff、pin 一致 |
| B3 proposal / decision record | 既存 id 抑制と状態診断にのみ使用 |

非 MVP 入力（Statement / NewsClassification / ContextItem / CompassDraft / MorningBrief / MarketSignal / PredictionRecord /
CalibrationReport / formal・shadow review / narrative / legacy theme score / corpus）は adapter が `UNSUPPORTED_INPUT` として除外し、
module は import しない（boundary test）。

## 3. Adapter（`discovery_adapter.adapt_inputs`）

純関数。upstream model を変更せず、filesystem / network / 現在時刻を使わない。各入力を `DiscoveryInputRecord` に正規化する:
input_kind / input_id（Foundation ref_id 接頭辞 `news_` / `doc_` / `fact_` / `obs_`）/ source_origin / evidence_time ＋ basis ＋
quality / evidence_date / known_at / structured_entity_refs（生の明示参照）/ entity_hits / taxonomy_tokens（構造化 L1。現行 model は
供給しないため通常空）/ taxonomy_hits（L2）/ fact_type / observation_series / source_kind / bounded_text_surfaces / upstream_schema_version
/ adapter_version / diagnostics。

| 入力 | evidence time | 構造化 entity（L1） | text 面（L2） |
|---|---|---|---|
| NewsItem | PUBLISHED_AT / RELIABLE（None → MISSING） | `entity_refs`（kind:value を catalog id として、ticker は TICKER identifier として解決） | headline / summary |
| SourceDocument | PUBLISHED_AT / RELIABLE、`published_inferred` → INFERRED（attachment は limited_use） | なし | title / summary |
| Fact | KNOWN_AT / DECLARED（known_at None → MISSING）、date ＝ primary_date | `subject.subject_id`（exact id または INSTRUMENT_ID identifier） | なし |
| Observation | AS_OF / RELIABLE、date ＝ trading_date | `entity_id`（exact id または INSTRUMENT_ID identifier）、series_id | なし |

同一 input_id の重複は最初の 1 件（`DUPLICATE_INPUT_ID` 診断）。record は input_id 順。

## 4. Source origin semantics

保守的に導く（A2 §8）: NewsItem → `PUBLISHER_ARTICLE` / `article:<article_id>`。SourceDocument → 記事に結び付く（NewsItem の
primary_document_id または NewsDocumentLink）なら同じ `article:<article_id>`、それ以外は改訂 chain の root を辿り TIER1 は
`OFFICIAL_RELEASE` / `release:<source_id>/<content_hash>`、他は `PUBLISHER_ARTICLE` / `document:<content_hash>`。Observation RAW →
`MARKET_SERIES` / `series:<source_id>/<series_id>`（series / source が無ければ UNKNOWN）、DERIVED → `DERIVED` / `derived:<id>`。Fact →
参照先の入力が同一 run にあり origin が 1 つに定まれば **その origin を継承**（lineage に fact id を追加）、それ以外は `DERIVED` /
`derived:<fact_id>`（lineage ＝ evidence ref ＋ calculation inputs）。同一 origin の入力は run report `origin_groups` に列挙されるが、
**hit 件数を独立 source 数とは呼ばない**（THEME 生成時の診断 `EVIDENCE_REFS:n;ORIGIN_KEYS:m;NOT_AN_INDEPENDENCE_CLAIM`）。

## 5. Ruleset / version pins

envelope: `schema_version`（`theme_discovery_rules:0.1.0`）/ `ruleset_version` / `published_at` / `content_digest` /
`taxonomy_version` / `catalog_version` / `rules`。`load_discovery_rules_version(path, *, expected_version, cutoff, taxonomy=None,
entity_catalog=None)` は version 完全一致・published_at ≤ cutoff・digest 一致でのみ返し、taxonomy / catalog を渡すと pin の完全一致
（`TAXONOMY_PIN_MISMATCH` / `CATALOG_PIN_MISMATCH`）と参照検証（§13）を行う。`discover()` も pin と published_at ≤ cutoff を再検査する。
latest 解決・fallback・normalization_version field はない。digest は §13 の B4B と同じ canonical JSON sha256（YAML の順序・書式非依存）。

## 6. Rule model

`DiscoveryRule(rule_id, rule_version, status, input_kinds, taxonomy_refs, entity_refs, predicate, negative_predicates,
aggregate_predicates, output_type, proposed_role, target_root_id, subject_template, mechanism_template, scope_template,
invalidation_template, limitations_template, provenance)`。

- `rule_id` は `^[a-z][a-z0-9_]{0,63}$` で不変、`rule_version` は semver で不変、ruleset 内で rule_id は一意。
- status ACTIVE / DEPRECATED（DEPRECATED は評価されず report にのみ載る）。output_type EVIDENCE_CANDIDATE / THEME_CANDIDATE
  （RELATION_CANDIDATE なし）。proposed_role SUPPORTS / CONTEXT のみ（CONTRADICTS / INVALIDATES は `FORBIDDEN_ROLE`）。
- predicate で使う entity / slug は `entity_refs` / `taxonomy_refs` に宣言されていること（`UNDECLARED_*_REF`）。
- THEME_CANDIDATE rule は subject_template・mechanism_template（drivers / channels / domains 各 ≥ 1、consequences ≥ 1、Foundation
  `MECHANISM_CATEGORIES` 語彙、OTHER は statement 必須）・scope_template（PERIOD_FRAME ちょうど 1 個、single frame 禁止）・
  invalidation_template ≥ 1 を要求し、`target_root_id` を取らない。EVIDENCE rule は template を取らない。
- certainty は authoring できない（field が無い → `UNKNOWN_FIELD`）。固定値 `HYPOTHESIZED_MECHANISM`。

## 7. Predicate vocabulary

入力単位: ALL / ANY / NOT / ENTITY_PRESENT(entity_id) / TAXONOMY_SIGNAL(slug) / FACT_TYPE(fact_type) / OBSERVATION_SERIES(series_id) /
SOURCE_KIND(origin_kind ≠ UNKNOWN) / MIN_DISTINCT(dimension ∈ {ENTITY_ID, TAXONOMY_TOKEN}, min_count)。
rule 単位（`aggregate_predicates`）: MIN_DISTINCT(dimension ∈ {INPUT_ID, EVIDENCE_REF, ENTITY_ID, TAXONOMY_TOKEN}, min_count) を matched
入力集合で数える。件数は述語の充足だけを決め、重み・score にならない。正規表現・fuzzy・embedding 述語は存在しない。入れ子は深さ ≤ 6。

## 8. L1 / L2 boundary（D-B4-5）

- **L1** ＝ 構造化された明示値の完全一致: 明示 entity ref / identifier、Fact.fact_type、Observation.series_id、source kind、構造化
  taxonomy token。
- **L2** ＝ 限定 text 面（NewsItem headline / summary、SourceDocument title / summary）に対する taxonomy slug・alias と entity safe /
  context alias の **正規化完全一致**（`normalize_token` 後、escape 済み literal の境界一致。ASCII は `(?<![a-z0-9])…(?![a-z0-9])`、
  非 ASCII は部分文字列）。同一 surface 内で長い一致 token に含まれる token は捨てる（`japan` ⊂ `bank of japan`。longest alias wins）。
  context alias は同 surface 群に含まれる context_terms を context として B4B resolver に渡す。本文全体・locator・author・URL は
  走査しない。L2 hit は `TaxonomyHit` / `EntityHit`（level・matched_by・surface・field）として record に残る。
- L2 だけの hit は EVIDENCE_CANDIDATE を出せるが THEME_CANDIDATE は出せない（`THEME_CANDIDATE_REQUIRES_L1_HIT`）。
- entity 解決の AMBIGUOUS / UNKNOWN / INACTIVE / SUPERSEDED は hit にならず診断に残る（後継への自動付け替えなし）。taxonomy の親は
  hit にならない（伝播なし）。

## 9. Negative predicates

rule の `negative_predicates` のいずれかが入力に成立すれば、その入力は当該 rule から除外される（`EXCLUDED_BY_NEGATIVE_PREDICATE:<id>`）。
部分点・相殺・「positive が negative を上回る」判定は存在しない。

## 10. Mechanism assembly（D-B4-6）

A template ＋ B binding ＋ C 同一 rule 内集約。

- template（人間 authoring の因果仮説）が driver → channel → domain → observable consequence をすべて供給する。keyword / alias は
  trigger であって機構ではない（機構文字列に alias は入らない）。
- binding は決定論的: `${entity}` ＝ rule.entity_refs の唯一の要素、`${entity.<attr>}` ＝ pinned catalog のその entity の attribute、
  `${series}` ＝ rule の唯一の OBSERVATION_SERIES 述語の series_id。曖昧な binding は load 時 `AMBIGUOUS_BINDING`、未解決属性は
  `UNBOUND_ENTITY_ATTRIBUTE`（ACTIVE rule は fail closed）。
- component key は `driver_n` / `channel_n` / `domain_n` / `consequence_n`。assertion_provenance RULE、provenance_ref は定数
  `discovery:mechanism_template`（rule id / version を含めない: 収束のため）。
- rule を跨いだ機構合成は行わない。別 rule の matched 入力は別 proposal の evidence にしかならない。

## 11. Proposal generation

**EVIDENCE_CANDIDATE**（matched 入力ごとに 1 件）: kind / ref_id / source_origin / evidence_time ＋ basis ＋ quality / evidence_date /
proposed_role / target_root_id（rule literal）/ reason ＝ `normalize_text("discovery evidence candidate {role} {kind}")`（rule 非依存）/
provenance（§12）/ created_at ＝ run_created_at。quality MISSING で role が CONTEXT でない入力は `ROLE_REQUIRES_EVIDENCE_TIME` として出さない。

**THEME_CANDIDATE**（rule ごとに高々 1 件）: 条件 ＝ output_type THEME_CANDIDATE ∧ matched ≥ 1 ∧ 集約 MIN_DISTINCT 充足 ∧ L1 hit ≥ 1 ∧
template 完全 ∧ binding 解決 ∧ evidence ref ≥ 1 ∧ Foundation fingerprint 再計算成功。certainty HYPOTHESIZED_MECHANISM 固定。
evidence_refs は Foundation `EvidenceAttachment`（PRIMARY_OBSERVATIONAL、role ＝ rule.proposed_role、role_provenance RULE、
role_asserted_by ＝ `discovery:mechanism_template`、SUPPORTS は `consequence_ref = consequence_1`、INFERRED は limited_use、
subject_refs ＝ L1 entity の EntityRef、attached_at ＝ run_created_at）。

## 12. Provenance と収束（D-B4-7）

`ProposalProvenance(RULE, proposer_ref="rule:<rule_id>", rule_version=<rule_version>, reason="pins taxonomy=<v> catalog=<v>
ruleset=<v>")`。provenance は B3 identity 外なので、**等価な semantic proposal は rule / rule_version を跨いで同一 proposal_id に収束**
する（evidence 集合まで等しいとき。B3 の identity は evidence_refs を含む）。複数 rule が同 id を出した場合、出力は 1 件（rule_id 順の
最初の provenance）、run report の各 rule に `emitted_proposal_ids` と `converged_proposal_ids` が残る。

## 13. Evidence aggregation（同一 rule 内）

matched 入力を input_id 順に attachment 化し、同 ref_id は 1 件に畳む。同一 origin の複数 ref はそのまま別 attachment として残す
（Foundation が後で origin を数える）が、run report で `ORIGIN_KEYS:m` を併記し独立とは呼ばない。資格判定・件数 score はしない。

## 14. Suppression と B3 decision interaction

生成した proposal_id が `existing_proposals` に存在すれば返さず `suppressed_existing_ids` に記録し、B3 `derive_proposal_status` の結果を
`EXISTING_<STATUS>_PROPOSAL:<id>`（OPEN / OPEN_DEFERRED / OPEN_UNRESOLVED / ACCEPTED / REJECTED / CLOSED_NOT_DUPLICATE /
INVALID_DECISION_HISTORY）として診断に載せる。REJECTED でも識別は変わらないので同じ提案は抑制されたまま（新 id を作らない）。
semantic に異なる提案（例: evidence 集合が違う）は新 id。discovery は decision を作らず変えず reopen しない。

## 15. Dedup interaction

`include_dedup=True`（既定）のとき、新規 THEME_CANDIDATE ごとに B3 `detect_exact_duplicates`（exact semantic / identity-core、
`resolutions` ＝ theme_resolutions、`proposals` ＝ existing ＋ 新規候補、`decisions` ＝ existing_decisions）を呼び、既存 id でない
DEDUP_REVIEW を出力に加える。NOT_DUPLICATE suppression・既存 review の skip は B3 の責務。fuzzy 拡張なし。ProposalStore 非使用。

## 16. Run report（derived。authority ではない）

`DiscoveryRunReport(schema_version, discovery_model_version, adapter_version, cutoff, run_created_at, taxonomy_version, catalog_version,
ruleset_version, input_count, normalized_input_count, excluded_inputs, origin_groups, rule_evaluations, rule_hits, proposal_ids,
suppressed_existing_ids, dedup_review_ids, diagnostics)`。rule ごと: rule_id / rule_version / status / output_type / candidate_input_ids /
matched_input_ids / l1_hit_count / l2_hit_count / negative_exclusions / aggregate_satisfied / emitted_proposal_ids /
converged_proposal_ids / diagnostics。score / rank / confidence / investment stance は含まない（test で JSON を検査）。

## 17. PIT / replay（D-B4-9）

run は `(cutoff, run_created_at, taxonomy, entity_catalog, ruleset)` を明示引数に取る。cutoff / run_created_at は aware、
run_created_at ≥ cutoff（`INVALID_RUN_TIME`）。3 つの knowledge はいずれも published_at ≤ cutoff（`FUTURE_KNOWLEDGE`）。入力は cutoff より
後に知り得たものを除外。同じ入力集合（順序・重複を問わず）と同じ pin → 同じ proposal id 集合と同じ run report（test で固定）。

## 18. Confidentiality

ruleset は本 gate で新規に authoring した generic な構造化 rule のみ（historical rule 原文・named chain・Compass 文言・CONFIRMED・
号 / 頁参照・顧客 watchlist 名称 / ticker・銘柄推奨・受益企業連鎖なし。MVP ruleset は company entity を trigger にしない）。guard test
が config.yaml watchlist との不一致と禁止 token の不在を検査する。public bundle への非混入は production closure test と Pages manifest
の `knowledge` 禁止で担保。

## 19. Imports

B4C module の import: stdlib、B4B（`knowledge_loader` / `taxonomy_model` / `taxonomy` / `entity_model` / `entity_catalog`）、B3
（`proposal_model` / `proposal_resolution` / `dedup`）、Foundation `themes.model`、入力 model module のみ（`facts.model` / `market.model` /
`sources.model` / `databank.news_model` / `core.types`。adapter だけが import し、各 package の `__init__` は何も import しない）。
禁止: proposal_store / proposal_bridge / themes.store / operations / revision / compass / reports / predictions / calibration / legacy /
network / LLM SDK / YAML（B4B loader 経由のみ）/ filesystem 書き込み / 現在時刻 / 乱数。Foundation / B1 / B2 / B3 / B4B は B4C を import しない。

## 20. Exclusions（B4C が実装しないもの）

Theme root 作成、Foundation / ProposalStore 書き込み、自動 ACCEPT、EvidenceCandidate の自動 promotion、EvidenceCandidate → Foundation
attachment bridge（B4E / B3.1）、L3（semantic / LLM / embedding / fuzzy）、RELATION_CANDIDATE、CONTRADICTS / INVALIDATES の自動付与、
本文走査、SQLite、network、config / workflow / public 変更、latest 解決。

## 21. Tests

`tests/intelligence/test_theme_discovery_rules.py`（matrix 1〜14 ＋ 補助）、`test_theme_discovery.py`（15〜68）、
`test_theme_discovery_boundary.py`（74〜79 ＋ 補助）、`test_theme_intelligence_import_boundary.py`（additive: module 列挙・入力 model
module の許可・closure・`source_tier` の lifecycle 語彙除外）、`test_theme_taxonomy_entity_boundary.py`（additive: ruleset file の同居許可）。
69〜73・80・81 は gate 報告で git / full suite により検証。

## 22. Versioning

- `theme_discovery_rules:0.1.0`（ruleset schema）、`theme_discovery:0.1.0`（model）、`theme_discovery_adapter:0.1.0`（adapter）、
  `theme_discovery_run_report:0.1.0`（report）。field 追加は minor bump ＋ loader の受理集合拡張（additive）。
- 提案の semantic identity は B3 schema と Foundation 語彙に従い、discovery model / adapter / rule の version には依存しない
  （`discovery:mechanism_template` 定数）。adapter の正規化規則を変える場合は adapter_version を bump し、B4D で影響を評価する。
- 既知の限界: SUPPORTS evidence は template の第 1 consequence（`consequence_1`）に結びつく（複数 consequence の選択は後続 version）、
  `target_root_id` は rule literal のみ（resolution からの自動決定なし）、L2 の longest-alias-wins は同 surface 内の別出現を数えない。
