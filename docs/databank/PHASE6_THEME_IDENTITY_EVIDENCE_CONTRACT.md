# Phase 6 — Theme Identity ＋ Evidence Contract（P6-A2 / Family B）

**状態: FROZEN（P6-A2）。** 本書は Phase 6 Theme 層の **identity・不変 observation・evidence 参照・evidence 役割・
evidence authority class・source 独立性・evidence 時点 vs 付与時点・構造化された機構・entity / asset 連結・
市場確認参照** を凍結する概念契約である。runtime source・test・package・knowledge・workflow は本 gate で変更しない。
ThemeStore / 永続化 / discovery / lifecycle / graph / LLM は実装しない（永続化と revision の物理形式は P6-A3）。

上流（凍結済み）:

- `docs/databank/PHASE6_FOUNDATION_DECISIONS.md`（P6-A0.5。F-1〜F-10、D0、package 境界 §7、evidence authority 境界 §8）
- `docs/databank/PHASE6_THEME_SEMANTICS_AUTHORITY_CONTRACT.md`（P6-A1。以下「A1」。定義 8 要件、Q1〜Q8、機構 class、
  authority L0〜L3、governance Option B、不変条件 25 項）
- 凍結 anchor: `6b23ba54f47431f637df8449374eaa807b7c18a8`

本書で解決する決定: **D5**（evidence authority）、**D6**（identity model）、**D9**（evidence 役割）、
**D15**（entity / asset 連結境界）、**D19**（市場確認 mapping の所有）、**D17 の evidence 側**（evidence 時点 vs 付与時点）。
D17 の再構成規則・D7 / D8（revision event / append-only authority）は P6-A3 に残す。

語彙（enum 値）は本書で凍結する。field 名は「推奨名」であり、A3 の永続化契約で最終確定する（意味は変えない）。

---

## 1. 現行 primitive の検証（本 gate で読み取り確認したもの）

identity・時点・lineage に関して本書が依拠する field は、現ブランチの model に **実在する**ことを確認した。

| primitive | id（導出） | evidence 時点になりうる field | lineage / 出所 field | revision |
|---|---|---|---|---|
| `facts.model.Fact` | `fact_id = content_id("fact", fact_type, subject.key(), primary_date, calculation_method, discriminator, value_token)`（値を含む → 値の変化は新 id） | `time.known_at`（`time.as_of`、`time.primary_date` / `date_role` を併存） | `evidence: FactEvidenceRef(kind OBSERVATION/DOCUMENT/STATEMENT/RECORD/FACT, ref_id, locator, excerpt, qa_decision)`、`calculation.inputs`、`source_ids` | `revision_of`、`status SUPERSEDED` |
| `market.model.Observation` | `observation_id_for(...)` ＝ content-addressed（series × trading_date × source × metric × value token） | `as_of`（aware 必須） | `source_id`、`source_document_id`、`series_id`、`inputs`（derived）、`kind RAW/DERIVED` | `revision_of`、`valid_until`、`latest_revisions()` |
| `sources.model.SourceDocument` | `doc_ = content_id(source_id, locator, content_hash)` | `published_at` ＋ `date_quality`（`source_provided_tz` / `source_provided_naive` / `unparsable` / `missing`）＋ `published_inferred` / `published_inferred_from`、`published_raw` | `source_id`、`source_tier`、`publisher`、`raw_item_id`、`content_hash`、`content_fingerprint`、`canonical_locator`、`guid` | `revision_of`、`latest_revisions()` |
| `databank.news_model.NewsItem` / `ArticleIdentity` / `NewsDocumentLink` | `news_ ← article_id ← 代表 key`（決定論） | `NewsItem.published_at`、`ArticleIdentity.first_published_at` | `article_id`、`primary_document_id`、`member_document_ids`、`NewsDocumentLink.role PRIMARY/SYNDICATED/UPDATE`、`source_id`、`publisher` | UPDATE link |
| `evidence.model.FactStatement` / `AnalysisStatement` / `ForecastStatement` | `statement_id`（生成規則は producer 側。現ブランチに producer なし） | `event_time`、`valid_from`（`created_at` は system 時刻） | `attribution DIRECT/REPORTED`、`EvidenceLink(relation SUPPORTS/CONTRADICTS/DERIVED_FROM/CONTEXT)`、`AnalysisStatement.inputs / rule_id / agent` | `valid_until` |
| `context.model.ContextItem` | content-addressed（`supporting_fact_ids` ＋ rule を含む） | snapshot cutoff | `supporting_fact_ids` | — |

独立性判定の前例: `evidence_qa.QADimension.DUPLICATION`（転載 ≠ 独立 source）、`REVISION`、`PROVENANCE`；
`databank.identity_decision.IdentityDecisionKind`（EXACT_MATCH / AUTO_MERGE / REVISION / SYNDICATED / CANDIDATE / DISTINCT）；
`review.revision_roles.RevisionRole`（SAME_PUBLISHER_UPDATE / CROSS_FEED_SAME_ARTICLE / SYNDICATED_COPY / UNKNOWN）。
identity の前例: `core.ids.content_id`（内容住所）と `core.ids.new_id`（ULID）の 2 系統；P5 の identity subset ＋ canonical JSON。

現ブランチで **実際に生成される** evidence: Fact（数値。market / jquants builder）、Observation（market ingest）、
SourceDocument（feed / tank normalizer）、NewsItem（identity runtime）。**Statement は model のみで producer が無い**
（本書は kind を定義するが、付与可能になるのは producer が存在してからである。A2 の blocker ではない）。

---

## 2. D6 — identity model

### 2.1 A0 で挙がった選択肢の監査

| 選択肢 | 前例 | 評価 |
|---|---|---|
| (i) 単一の内容住所 id（ContextItem / Fact 型） | `content_id` | 内容が変われば id が変わるため「evidence を加えるたびに別 Theme」になる。lineage を表せない → **却下** |
| (ii) 単一の生成 id（ULID。EvidenceLink 型） | `new_id` | lineage は表せるが、revision の不変性・内容住所による重複再記録の検出が無い → 単独では **却下** |
| (iii) taxonomy slug | legacy `themes.yaml` | A1 不変条件 16（slug ≠ identity）に反する → **却下** |
| (iv) 人間 slug / label | — | rename のたびに identity が揺れる。label は metadata → **却下**（alias としては可） |
| (v) member 集合を持つ event-sourced identity（ArticleIdentity 型） | `art_` ＋ MANUAL_SPLIT / MANUAL_MERGE | merge / split を明示履歴にする点は継承する。ただし ArticleIdentity は外部の canonical key から id を導出できるが Theme にその key は無い |
| **(vi) 二層 identity** | P5（不変 record ＋ supersession）＋ (v) の governance 履歴 | **採用**（監督者 default） |

### 2.2 採用: 二層 identity

- **Level A — Theme Root（lineage identity）**: 1 つの Theme lineage を指す不透明な安定 id。**evidence の蓄積、
  label / description の変更、lifecycle 状態の変化、scope / 帰結 / limitations の改訂、class の変更を通じて不変。**
- **Level B — Theme Observation（revision identity）**: ある時点での Theme の **完全な意味論的状態の不変 snapshot**。
  内容住所（content-addressed）であり、identity / semantic content が 1 bit でも違えば別 id。同一 root の下で
  `previous_observation_ref` により一本の supersession chain を成す。

root は「何についての lineage か」を内容から再計算できない（§3）。observation は内容から再計算できる（§4）。
**類似 ≠ identity 同一。** fingerprint（§12）が一致しても root が同一であるとは結論しない。

### 2.3 12 の変更の分類（root への影響）

| # | 変更 | root | 備考 |
|---|---|---|---|
| 1 | label rename | 不変 | METADATA_ONLY（§16） |
| 2 | 支持 evidence の追加 | 不変 | 新 observation |
| 3 | 反証 evidence の追加 | 不変 | 新 observation |
| 4 | 機構確度 class の変更 | 不変 | 新 observation（reviewed では governance 事象を伴う） |
| 5 | scope の精緻化（同一機構の内側で狭める / 広げる） | 不変 | 新 observation |
| 6 | 期待される観測可能な帰結の変更（同一の subject / driver / channel / domain の下で） | 不変 | 新 observation。既存 evidence 役割の再点検 flag（DERIVED） |
| 7 | driver の置換 | **新 root 必須** | identity core（§12.1）の変更。旧 root は governance 履歴で SUPERSEDED_BY を持つ |
| 8 | transmission channel の置換 | **新 root 必須** | 同上 |
| 9 | split | **新 root（複数）** | governance 事象。旧 root は消えない |
| 10 | merge | **新 root または存続 root の明示指定** | governance 事象。被 merge root は消えない |
| 11 | taxonomy 再割当 | 不変 | METADATA_ONLY |
| 12 | entity 連結の訂正 | 原則不変 | 新 observation。ただし entity が identity core の subject / typed reference である場合は **新 root 必須** |

「黙った識別子の変化」は禁止: driver / channel / subject / domain の置換を同一 root の新 observation として書くことは
validator が identity core の比較で **拒否**する（判定不能な場合も拒否 ＝ fail closed。人間 decision で NEW_ROOT か
refinement かを確定する）。

---

## 3. Root id の生成

| 選択肢 | 評価 |
|---|---|
| A 生成 id（ULID: `core.ids.new_id`） | 内容と無関係。等価な 2 候補は **別 root** になり、fingerprint 一致は DERIVED index で dedup review に回る。順序は監査上の便宜であり意味を持たない |
| B 初回 canonical fingerprint からの内容導出 | 決定論的だが、**等価な fingerprint を持つ 2 候補が構築上同一 root に衝突する ＝ 自動 merge** となり「等価候補は dedup review へ」に反する。root が「最初の内容」を暗黙に encode し、後の改訂で fingerprint と乖離して誤解を生む |
| C taxonomy slug | A1 不変条件 16 に反する |
| D 人間 slug | rename で揺れる。alias metadata としてのみ |

**決定: A（生成 id）＋ 各 observation に別途 fingerprint を保持する。** root id は `theme_<ULID>` を推奨
（prefix は A3 で確定）。理由: (1) identity を内容から再計算できないことで「fingerprint 一致 ＝ 同一 Theme」の
漏れを構造的に防ぐ、(2) 等価候補は別 root として保持され、fingerprint 一致は **DUPLICATE_CANDIDATE** の DERIVED flag
として人間 review に回る（自動 merge なし。A1 §16）、(3) root は内容を持たないので evidence 蓄積・改訂を通じた不変性が
自明、(4) 再現性は root 作成 record（governance 事象。id を含む）の append-only 履歴から replay で得る（P5 精神）、
(5) ArticleIdentity の決定論 id は外部 canonical key に依存しており Theme には存在しない。

root 作成 record（不変）: `root_id`、`created_at`（監査）、作成 provenance（RULE / HUMAN / LLM_PROPOSAL ＋ actor 参照）、
`note`。genesis observation は **DERIVED**（当該 root で `previous_observation_ref` が空の唯一の observation）。
1 root に genesis は厳密に 1 つ。同じ previous を指す observation が 2 つある（fork）場合は P5-3A resolver の前例に従い
**UNRESOLVED**（決して created_at / 物理順で推測しない。形式化は A3）。

---

## 4. 不変 Theme Observation の内容分類

P5（identity subset ＝ 内容住所、provenance / audit は identity 外、canonical JSON `sort_keys=True,
separators=(",",":"), ensure_ascii=False`）を前例とする。observation id は `thobs_<sha256[:24]>` を推奨し、
**IDENTITY / SEMANTIC CONTENT のみ**から導出する。

| 分類 | 内容 | id に含む |
|---|---|---|
| **IDENTITY / SEMANTIC CONTENT** | `root_ref`、`previous_observation_ref`（genesis は空）、主題（normalized subject ＋ typed reference）、構造化された機構（§11: driver / channel / domain / expected observable consequences）、機構確度 class（A1 §12 の 4 値）、scope（地域 / 産業 / 資産 class / 期間枠の typed token）、limitations（typed item）、invalidation conditions（typed item。§15）、entity links のうち INFERRED_EXPOSURE_LINK（§13）、**evidence attachment 集合**（§6。各要素は kind / class / ref_id / evidence_time / attached_at / role / role provenance / metadata を持つ）、`mechanism_vocabulary_version`、`schema_version` | **含む** |
| **PROVENANCE** | observation を書いた主体（RULE id＋version / HUMAN actor 参照 / LLM_PROPOSAL の model・prompt 参照）、理由 `reason`（reviewed では必須）、対応する governance 事象 ref | 含まない |
| **AUDIT** | `recorded_at`（Theme 層がこの observation を記録した時刻。aware UTC）、書込み経路 | 含まない |
| **DERIVED（再計算可能。保持しても authority ではない）** | `identity_core_fingerprint`、`semantic_fingerprint`（§12）、資格判定（QUALIFIES / CANDIDATE / DOES_NOT）、source diversity / temporal diversity の集合、DIRECTLY_EVIDENCED_LINK（§13）、`has_contradicting_evidence` / `has_invalidating_evidence` flag、DUPLICATE_CANDIDATE flag、genesis 判定 | 含まない |

規則:

- 同一 id で bytes が異なる書込み（provenance / audit のみ違う）は **conflict ＝ fail closed**（P5 の canonical-line
  byte 冪等 ＋ conflict 拒否を継承。黙って skip しない）。同一 bytes は冪等。
- `previous_observation_ref` は identity に含む（P5 EvaluationRecord の `supersedes_evaluation_id` 前例）。
- label / description / alias / taxonomy 分類は observation に **含めない**（§16 METADATA_ONLY。別の append-only
  metadata 記録。形式は A3）。含めると rename が偽の revision を生むか、同一 id で異 bytes の conflict を生むため。
- evidence attachment 集合を observation に含めるのは「Theme の状態 ＝ 一本の supersession chain」を保つためである
  （点時刻の再構成が 1 chain の解決で済む。P5-3A resolver 前例）。attachment の `attached_at` は後続 observation に
  引き継がれても変わらない。
- observation は削除・更新されない。訂正は新 observation。

---

## 5. D5 — evidence authority class

| class | 意味 | Theme 資格（Q5）への算入 |
|---|---|---|
| **PRIMARY_OBSERVATIONAL** | 観測・公表の一次記録（QA 済み） | 算入する |
| **DERIVED_INTERPRETIVE** | 一次記録からの解釈・文脈（session 固有等） | 算入しない。Phase 6 では付与自体を認可しない（後続 gate が明示認可するまで） |
| **PROPOSAL_ONLY** | 機構仮説・役割・label 等の **提案源**。evidence ではない | 算入しない。provenance にはなりうる |
| **NOT_THEME_EVIDENCE** | Theme の根拠になりえない | 付与禁止 |

| kind | class | 備考 |
|---|---|---|
| Fact（`status USABLE`） | PRIMARY_OBSERVATIONAL | `qa_decision` を attachment に snapshot。`calculation` を持つ derived Fact も PRIMARY（決定論計算）だが lineage は入力へ収束（§8） |
| Fact（`LIMITED_USE`） | PRIMARY_OBSERVATIONAL（limited） | 付与可。role SUPPORTS / CONTRADICTS では `limited_use=true` を保持し、資格判定では算入するが reviewed 受理時の人間確認対象 |
| Fact（`UNUSABLE`） | NOT_THEME_EVIDENCE | 付与禁止 |
| Fact（`SUPERSEDED`） | — | 新規付与は最新 revision へ。既存 attachment は履歴として残る（`ref_id` が revision を固定） |
| market Observation（`kind RAW`） | PRIMARY_OBSERVATIONAL | Fact が存在するなら Fact を優先参照（known_at / QA / status を持つため）。直接参照も可 |
| market Observation（`kind DERIVED`） | PRIMARY_OBSERVATIONAL（derived） | lineage は `inputs` へ収束 |
| SourceDocument | PRIMARY_OBSERVATIONAL（**公表の一次記録として**） | 「誰が・いつ・何を公表したか」の evidence。**本文中の主張が事実であることの evidence ではない** |
| NewsItem | PRIMARY_OBSERVATIONAL（記事 identity 単位の公表記録） | lineage は `article_id → member documents` |
| FactStatement（`attribution DIRECT`、provenance link あり） | PRIMARY_OBSERVATIONAL | 現ブランチに producer なし |
| FactStatement（`attribution REPORTED`） | PRIMARY_OBSERVATIONAL（reported） | 独立性は伝聞元の origin に収束 |
| AnalysisStatement | DERIVED_INTERPRETIVE | Phase 6 では付与しない |
| ForecastStatement | NOT_THEME_EVIDENCE | 予測（A1 不変条件 5 / 21）。外部主体が予測を「公表した」事実は SourceDocument / FactStatement として扱う |
| ContextItem | DERIVED_INTERPRETIVE | Phase 6 では付与しない（A0.5 §7） |
| internals 由来の解釈 | DERIVED_INTERPRETIVE | Phase 6 では付与しない |
| CompassClaim / CompassOutlook | NOT_THEME_EVIDENCE | |
| MorningBrief / MarketSignal | NOT_THEME_EVIDENCE | |
| PredictionRecord / EvaluationRecord / CalibrationReport | NOT_THEME_EVIDENCE | P5 は Theme evidence にならない（F-10） |
| legacy theme config（themes / taxonomy / graph yaml） | NOT_THEME_EVIDENCE | taxonomy metadata の語彙にはなりうる（§18） |
| legacy causal_rules | PROPOSAL_ONLY | 機構仮説 / 役割の RULE provenance にはなりうる。port はしない |
| LLM 出力 | PROPOSAL_ONLY | |
| ThemeReference / NewsClassification / Statement.themes | NOT_THEME_EVIDENCE | topic tag（A1 §21）。discovery の手掛かりに留まる |
| RawItem / ArticleIdentity / NewsDocumentLink / EvidenceLink / SourceHealthObservation | 付与対象外 | lineage・独立性判定に用いる provenance 記録 |

**Theme は ContextItem を 1 つも用いずに PRIMARY_OBSERVATIONAL evidence のみで資格を満たせなければならない**
（A1 §9 / 不変条件 17 の evidence 側）。

---

## 6. evidence 参照（値の複製ではなく参照）

attachment は evidence の **参照**であり、値・本文を複製しない（Fact の value、記事本文、Observation の値を持たない）。

| 推奨 field | 内容 | 必須 |
|---|---|---|
| `evidence_kind` | FACT / OBSERVATION / SOURCE_DOCUMENT / NEWS_ITEM / STATEMENT（CONTEXT_ITEM は後続 gate まで不可） | 必須 |
| `authority_class` | §5 の class（付与時点で snapshot。後の規則変更に再構成が依存しないため） | 必須 |
| `ref_id` | `fact_id` / `observation_id` / `source_document_id` / `news_item_id` / `statement_id`。いずれも revision 固有 id であり **参照した revision を固定する** | 必須 |
| `source_origin` | 出所 identity（§8）: `source_ids` / `source_id` ＋ `publisher`、origin lineage key（`article_id`、`series_id`、derived の `inputs`） | 必須（判定不能なら `UNKNOWN_ORIGIN` を明示） |
| `evidence_time` ＋ `evidence_time_basis` ＋ `evidence_time_quality` | §7 | 必須（欠落は §7 の規則） |
| `attached_at` | Theme 層で付与が決定・記録された時刻（aware UTC） | 必須 |
| `role` | §9 | 必須（1 attachment に 1 つ） |
| `role_provenance` ＋ `role_asserted_by` | §10 | 必須 |
| `consequence_ref` | 当該 evidence が関係する expected observable consequence（§11）の component key。INVALIDATES では `invalidation_condition_ref` | SUPPORTS / CONTRADICTS では推奨、EVIDENCE_SUPPORTED への class 変更では必須。INVALIDATES では必須 |
| `is_trigger` / `source_causal_claim` / `limited_use` | metadata flag（§9 / §11 / §5） | 任意 |
| `qa_decision_at_attachment` | Fact.qa_decision / GateDecision の snapshot | Fact / Document では推奨 |
| `revision_of_at_attachment` | 付与時点で `ref_id` が supersede していた旧 id（既知なら） | 任意 |
| `locator` / `excerpt` | 章・field・短い原文抜粋（権利上安全な範囲。credential を含む URL は保存しない。FactEvidenceRef と同じ注意） | 任意。計算に用いない |
| `note` | 短い理由。authority ではない | 任意（HUMAN role では理由必須） |

「この evidence は後に revise された」は DERIVED（参照先の `revision_of` chain から lookup）であり、attachment を
書き換えて表現しない。

---

## 7. D17（evidence 側）— 二重時点 model

| 時点 | 意味 | 由来 |
|---|---|---|
| **EVIDENCE_TIME** | evidence がその内容として指す・知りえた時点 | kind ごとに下表 |
| **ATTACHED_AT** | Theme 層がその evidence を当該 role で付与した時点 | Theme 層 |
| `recorded_at`（AUDIT） | observation が記録された時刻 | Theme 層。EVIDENCE_TIME の代替にならない |

| kind | EVIDENCE_TIME | basis | quality |
|---|---|---|---|
| Fact | `time.known_at` | KNOWN_AT | `None` → MISSING。Fact 層の契約（`is_known_by` は None を False）を継承 |
| Observation | `as_of` | AS_OF | aware 必須なので常に存在（P5 §7 と同じく known_at ≡ as_of の単純化を明示） |
| SourceDocument | `published_at` | PUBLISHED_AT | `date_quality == source_provided_tz` かつ `published_inferred == False` → RELIABLE；`published_inferred == True` → INFERRED；naive / unparsable / missing → MISSING |
| NewsItem | `published_at`（代表文書由来）。`ArticleIdentity.first_published_at` を最早値の参考に | PUBLISHED_AT | 代表文書の quality を継承 |
| FactStatement | `event_time`；無ければ DERIVED_FROM link 先文書の `published_at` | EVENT_TIME / PUBLISHED_AT | `created_at`（system 時刻）は **代替にしない** |

規則:

- **`retrieved_at` / ingestion 時刻 / `created_at` を EVIDENCE_TIME の代替に用いない**（provenance と quality の無い
  時刻は evidence 時点ではない）。
- quality が MISSING の evidence は **SUPPORTS / CONTRADICTS / INVALIDATES で付与できない（fail closed）**。
  CONTEXT としてのみ付与でき、資格判定・temporal diversity に算入しない。INFERRED は付与できるが `limited_use=true`
  を伴い、reviewed 受理時の人間確認対象。
- `evidence_time > attached_at` は拒否（存在する前の evidence を付与できない。未来日付の文書は date 不良）。
- `attached_at <= recorded_at`（当該 attachment を初めて含む observation の記録時刻）。
- **点時刻 T での再構成に evidence が現れる条件: `evidence_time <= T` かつ `attached_at <= T`**（両方）。
  T 時点で「後から付与された古い evidence」を遡って見せない。物理順・行順で判断しない。observation 自体の可視条件
  （`recorded_at <= T`）と chain の解決は A3。
- known_at の basis が Fact 層で検証できない（例: jquants builder の retrieval 時刻 fallback）場合、本層は Fact 層の
  宣言を採用しつつ `evidence_time_quality = DECLARED`（RELIABLE 未満、INFERRED 以上）とする。改善は Fact 層への提案。

---

## 8. source 独立性

| 用語 | 定義 |
|---|---|
| **evidence item** | 付与可能な 1 record（`ref_id` で識別） |
| **evidence lineage** | item から origin へ遡る決定論的連鎖: Fact → `FactEvidenceRef(OBSERVATION/DOCUMENT/...)` → …；derived Fact → `calculation.inputs`；Observation（DERIVED）→ `inputs`；Observation（RAW）→ `source_id` / `source_document_id`；NewsItem → `article_id` → `member_document_ids`；SourceDocument → `raw_item_id` / `source_id` / `publisher`；Statement → `EvidenceLink(DERIVED_FROM)` |
| **source origin** | lineage の終端 ＝ **元の公表 / 記録主体とその元 record**（配信した feed ではない）。市場データでは（供給元 `source_id`、`series_id`）、文書では元 publisher と元 article / release |
| **independent source origin** | 2 つの item の lineage が origin record を共有せず、origin 主体が別組織であり、一方が他方の転載 / 改訂 / 派生であると **記録上示されていない**こと。判定不能 → **独立ではない**（fail closed） |

同一 origin と判定する記録上の signal: 同一 `article_id`；`NewsDocumentLink.role SYNDICATED / UPDATE`；
`IdentityDecisionKind EXACT_MATCH / AUTO_MERGE / REVISION / SYNDICATED`；`RevisionRole SYNDICATED_COPY /
CROSS_FEED_SAME_ARTICLE / SAME_PUBLISHER_UPDATE`；同一 `content_fingerprint` / `content_hash`；`revision_of` chain；
lineage の共有（Observation ↔ その Fact、derived ↔ その inputs、同一 record からの複数 Fact）；QA DUPLICATION の指摘。

| ケース | 独立 origin 数 | 備考 |
|---|---|---|
| 同一記事の 5 feed 転載 | 1 | 5 item・1 origin |
| 公式 release を複数媒体が伝える記事群 | 1（release） | 媒体が独自観測を付加した場合のみ人間判断で別 origin。既定は収束 |
| 同一 SourceDocument が NewsItem と Statement の両方として参照される | 1 | |
| Observation とそれから作られた Fact | 1 | 二重付与は DERIVED で REDUNDANT_REFERENCE flag |
| 複数 Observation から作られた derived Fact | 入力 origin の和集合。入力のいずれとも独立ではない | |
| 同一 record からの複数 Fact（同日 close と volume 等） | 1 | metric 違いは独立ではない |
| 2 つの独立した公式 release（別組織・別 record） | 2 | |
| 公式 release ＋ 独立した市場観測 | 2 | 測定過程が異なる |
| 同一 recurring series の 2 日付 | 1（source）／時点 2 | **TEMPORAL DIVERSITY あり、SOURCE DIVERSITY なし** |

- **SOURCE DIVERSITY** ＝ PRIMARY_OBSERVATIONAL attachment（役割 SUPPORTS / CONTRADICTS / INVALIDATES、quality
  MISSING を除く）の independent source origin が **2 以上**。
- **TEMPORAL DIVERSITY** ＝ 同じ集合の evidence 日付（Fact `primary_date` / Observation `trading_date` / 文書は
  `published_at` の日付）が **2 以上**。同日内の複数時刻は 1 と数える。
- A1 Q5 は **両方**を要求する。いずれも集合の濃度による述語であり、重み・score・閾値調整ではない。

---

## 9. D9 — evidence 役割

| role | 定義 |
|---|---|
| **SUPPORTS** | 機構が予期する観測可能な帰結（または driver の存在）が、当該 scope・時点で観測されたことと整合する evidence |
| **CONTRADICTS** | 機構が予期する帰結が、予期された scope・時点で観測されなかった、または逆の観測がなされた evidence |
| **CONTEXT** | 関連する背景であり、支持でも反証でもない evidence |
| **INVALIDATES** | observation に宣言された invalidation condition（§15）を満たす evidence。`invalidation_condition_ref` 必須 |

- **TRIGGER は role ではなく metadata**（`is_trigger`）。候補生成の契機となった evidence は SUPPORTS または CONTEXT の
  いずれかの role を持ち、加えて trigger flag を持つ。
- **1 attachment に 1 role。** 同一 evidence item は同一 observation 内で（`ref_id`, `consequence_ref`）につき高々
  1 回。role の訂正は新 observation で置換し、旧 role は履歴（前 observation）に残る。
- CONTRADICTS / INVALIDATES が 0 件であることは正当なデータ。**反証の不在 ≠ 確証**（A1 不変条件 15）。
- INVALIDATES の存在は lifecycle を自動で変えない（lifecycle は P6-C）。DERIVED flag として必ず可視化され、
  reviewed Theme では人間 decision の対象になる。
- 本 role enum は `evidence.model.EvidenceRelation`（DERIVED_FROM を持つ）とは別物であり、import して再利用しない
  （語彙は整合させる）。

---

## 10. role の provenance

| provenance | 内容 | 算入 |
|---|---|---|
| **RULE** | 決定論 rule（`rule_id` ＋ version。replay 可能） | 資格判定に算入 |
| **HUMAN** | 人間 decision（actor は役割 / 仮名 id。個人識別情報は保持しない）。理由必須 | 算入 |
| **LLM_PROPOSAL** | model / prompt version 参照付きの提案。**provisional** | **算入しない**。L1 候補にのみ存在可。L2 では HUMAN または RULE に置換済みであること |

- **evidence の authority ≠ role の真偽。** PRIMARY_OBSERVATIONAL な Fact を誤った role で付与しても Fact は
  PRIMARY のままであり、role の正しさは governance の問題。
- LLM は role を **提案**するのみ（A1 §17）。RULE も reviewed Theme の role を黙って変更しない。

---

## 11. 構造化された機構

機構は 4 種の component から成る（各 ≥ 1。consequences は観測可能な target を持つこと）:

| component_type | 意味 | 追加 field |
|---|---|---|
| **DRIVER** | 何が動くか | — |
| **TRANSMISSION_CHANNEL** | どの経路で伝わるか | — |
| **AFFECTED_DOMAIN** | 何に及ぶか（sector / industry / asset class / region / macro aggregate） | — |
| **EXPECTED_OBSERVABLE_CONSEQUENCE** | 何が観測されれば整合 / 不整合か | `observable_target`（typed reference: `series_id` / instrument / Fact subject / 文書種別）、`expected_change`（定性: INCREASE / DECREASE / WIDEN / NARROW / ELEVATED / DEPRESSED / UNSPECIFIED） |

component の共通表現（小さく型付き。prose ではない）:

- `category`: **小さく version 付きの管理語彙**（`mechanism_vocabulary_version`）。未収載は `OTHER`（この場合
  `normalized_statement` が必須）。語彙の初期集合は A3 / P6-B で確定するが、shape（enum ＋ version）は凍結。
- `typed_reference`: 任意。`instrument_id` / `series_id` / `jp:security:<code>` / sector code / country code /
  Fact subject key 等の既存識別子。entity catalog を要求しない。
- `normalized_statement`: 簡潔な正規化文（NFKC・小文字化・空白圧縮。長さ上限は A3）。表示用 prose ではない。
- `assertion_provenance`: HUMAN / RULE / LLM_PROPOSAL / SOURCE_CLAIM（`SOURCE_CLAIM` は evidence 参照必須）。

**確度 class は observation level に 1 つ**（A1 Q2「class が宣言されている」と整合し、component ごとの class 平均や
算術を招かないため）。値は A1 §12.1 の 4 値をそのまま用いる。`EXPLICIT_SOURCE_CAUSAL_CLAIM` は「機構の根拠が
source の明示的因果主張のみである」ことを表す class であり、資格・authority 上 HYPOTHESIZED_MECHANISM より上ではない。
この class では `source_causal_claim=true` の attachment を ≥ 1 持つこと。component level の確度 class は Phase 6 では
導入しない（component level には provenance のみ）。

expected consequence の `expected_change` は Theme を **検証可能にする条件**であって、instrument の価格 target・
評価 horizon 日付・正誤を持たず、P5 に流入しない（A1 不変条件 5）。

---

## 12. 機構 fingerprint

### 12.1 二段の fingerprint（いずれも DERIVED）

| fingerprint | 材料（canonical JSON、sort、NFKC 小文字） | 用途 |
|---|---|---|
| **identity_core_fingerprint** | 主題（normalized subject ＋ typed reference）、DRIVER / TRANSMISSION_CHANNEL / AFFECTED_DOMAIN の各 `(component_type, category, typed_reference)`（`category == OTHER` のときのみ `normalized_statement` の正規化 key を加える） | NEW_ROOT_REQUIRED の検出（§2.3 / §16）。同一 root の chain 内で変化してはならない |
| **semantic_fingerprint** | identity core ＋ EXPECTED_OBSERVABLE_CONSEQUENCE の `(category, observable_target, expected_change)` ＋ scope token | 重複候補の提示（DUPLICATE_CANDIDATE）、変更検出 |

### 12.2 除外

label、description / prose、`normalized_statement` の文言差（category ≠ OTHER のとき）、taxonomy slug、evidence の
件数 / id、確度 class、confidence、lifecycle、entity links、mapping 記録、timestamps、root id、provenance、audit。

### 12.3 規則

- fingerprint は **identity ではない**。異なる root 間の一致は DUPLICATE_CANDIDATE flag → 人間 review。一致で
  merge しない。不一致で「別 Theme」と断定もしない（人間が同一 lineage と判断すれば merge は governance 事象）。
- fuzzy match・embedding・自動 merge は Phase 6 で用いない（記事の `identity_signals` n-gram も Theme には転用しない。
  dedup heuristics は D13 / P6-B）。
- 保持された fingerprint と再計算値の不一致は fail closed（読み手が信用しない）。

---

## 13. D15 — entity / asset 連結境界

| link class | 定義 | 分類（§4） | provenance |
|---|---|---|---|
| **DIRECTLY_EVIDENCED_LINK** | 付与済み PRIMARY evidence の subject（`Fact.subject.subject_id` / `Observation.entity_id` / `NewsItem.entity_refs` の SOURCE_EXPLICIT）として entity が現れる | DERIVED（evidence 集合から再計算） | evidence 参照 |
| **INFERRED_EXPOSURE_LINK** | entity が機構に晒されていると **仮説**される。`exposure_kind`（BENEFICIARY / ADVERSELY_EXPOSED / MIXED / UNSPECIFIED）と `uncertainty`（class。数値でない）を持つ | SEMANTIC CONTENT（identity core 外） | HUMAN / RULE / LLM_PROPOSAL 必須 |
| **TAXONOMIC_ASSOCIATION** | taxonomy / sector 所属による連想のみ | METADATA | taxonomy version |

- entity の識別子は typed reference（`EntityKind` ＋ 値: `instrument_id`、`jp:security:<code>`、sector17 / 33 code、
  country code 等）。entity catalog は前提にしない（後続）。
- INFERRED_EXPOSURE_LINK は **推奨ではない**（BUY / SELL / weight を持たない。A1 不変条件 6）。企業固有 thesis は
  Phase 9。
- legacy の ticker list（themes.yaml 等）は authority ではなく、link の候補提示にとどまる。
- entity link の変更は root を変えない。ただし entity が identity core の subject / typed reference である場合は
  NEW_ROOT_REQUIRED（§2.3 #12）。

---

## 14. D19 — 市場確認 mapping の所有

| 選択肢 | 評価 |
|---|---|
| A 全域 knowledge mapping（`market_rules.yaml` 型） | Compass DNA / knowledge authority と結合し、Theme ごとの version 履歴を持てない → 却下 |
| B observation に埋め込む | mapping の運用変更が偽の semantic revision を生む → 却下 |
| **C 別の version 付き Theme-to-Series mapping 記録** | **採用**（監督者選好） |
| D 完全 derived | 再現・人間 governance ができない → 却下 |

mapping 記録（推奨名 `theme_series_mapping`。不変・append-only・`supersedes` で version 化。形式は A3）:
`root_ref`、対象 `consequence_ref`（任意）、`series_id` / `instrument_id` / Fact subject、`mapping_role`
（CONFIRMATION_CANDIDATE / DRIVER_PROXY / DOMAIN_PROXY）、`expected_relation`（定性）、provenance、`valid_from`、
`recorded_at`、`supersedes`。

規則: mapping は identity でも fingerprint 材料でもない；P5 calibration の入力でも prediction target でもない；
mapping の存在・一致は Theme を **昇格 / 降格させない**；mapping から得た観測は evidence の **候補**であり、通常の
attachment 経路（role ＋ provenance）を経ずに evidence にならない。consequence component の `observable_target`
（意味論: 何が観測されるべきか）と mapping（運用: 我々のどの series で確認するか）は別物である。

---

## 15. limitation / invalidation condition / contradicting evidence

| 概念 | 定義 | 所在 |
|---|---|---|
| **LIMITATION** | Theme 記述自体の既知の弱点・不確実性（適用範囲、データ欠落、交絡要因） | SEMANTIC CONTENT（typed item: category ＋ normalized text） |
| **INVALIDATION CONDITION** | 何が観測されれば Theme が弱まる / 崩れるかの宣言（可能なら typed target 付き） | **SEMANTIC CONTENT（不変 observation に含める。予想どおり yes）**。INVALIDATES attachment が参照する key を持つ |
| **CONTRADICTING EVIDENCE** | role CONTRADICTS で付与された evidence item | evidence attachment 集合 |

invalidation condition が満たされた evidence は INVALIDATES として付与される（evidence ＋ condition ref）。その帰結
（lifecycle）は P6-C。condition の無い Theme は反証不能であり Q6 を満たさない（A1 §12.2）。

---

## 16. revision 境界の予告（A3 の入力）

| # | 変更 | 分類 |
|---|---|---|
| 1 | label rename | METADATA_ONLY |
| 2 | description 編集 | METADATA_ONLY |
| 3 | taxonomy 再割当 | METADATA_ONLY |
| 4 | alias / 表示名の追加 | METADATA_ONLY |
| 5 | SUPPORTS evidence の追加 | SAME_ROOT_NEW_OBSERVATION |
| 6 | CONTRADICTS evidence の追加 | SAME_ROOT_NEW_OBSERVATION |
| 7 | INVALIDATES evidence の追加 | SAME_ROOT_NEW_OBSERVATION（governance へ可視化） |
| 8 | evidence 役割の訂正 | SAME_ROOT_NEW_OBSERVATION（reviewed では GOVERNANCE_EVENT を伴う） |
| 9 | 機構確度 class の変更 | SAME_ROOT_NEW_OBSERVATION（reviewed では GOVERNANCE_EVENT を伴う） |
| 10 | scope の精緻化 | SAME_ROOT_NEW_OBSERVATION |
| 11 | limitation の追加 / 編集 | SAME_ROOT_NEW_OBSERVATION |
| 12 | invalidation condition の追加 / 編集 | SAME_ROOT_NEW_OBSERVATION |
| 13 | expected consequence の追加 / 精緻化（identity core 不変） | SAME_ROOT_NEW_OBSERVATION（evidence 再点検 flag） |
| 14 | driver の置換 | NEW_ROOT_REQUIRED（＋ GOVERNANCE_EVENT: SUPERSEDES 関係） |
| 15 | transmission channel の置換 | NEW_ROOT_REQUIRED |
| 16 | affected domain の置換（refinement でない） | NEW_ROOT_REQUIRED（判定不能は fail closed → 人間 decision） |
| 17 | 主題 / subject の置換 | NEW_ROOT_REQUIRED |
| 18 | split | GOVERNANCE_EVENT（新 root ≥ 2。旧 root 保持） |
| 19 | merge | GOVERNANCE_EVENT（存続 / 新 root を明示。被 merge root 保持） |
| 20 | INFERRED_EXPOSURE_LINK の訂正 | SAME_ROOT_NEW_OBSERVATION（subject entity なら NEW_ROOT_REQUIRED） |
| 21 | 市場確認 mapping の追加 / 置換 | METADATA_ONLY（Theme observation に対して。実体は §14 の別 version 付き記録） |
| 22 | L1 → L2 受理 / 引退 / 再開 | GOVERNANCE_EVENT |
| 23 | root 作成 | GOVERNANCE_EVENT（provenance 付き） |

---

## 17. merge / split

- merge / split は **明示の governance 事象**（理由・対象 root・結果 root・actor provenance・`recorded_at`）であり、
  自動では起きない（fingerprint 一致でも）。
- 被 merge root・split 元 root は削除されず、governance 履歴で MERGED_INTO / SPLIT_INTO 関係を持つ。evidence
  attachment は結果 root の新 observation に **再付与**され（元の `attached_at` と provenance を保持し、`carried_from`
  で由来 observation を指す）、元 root の履歴はそのまま残る。
- ArticleIdentity の MANUAL_SPLIT / MANUAL_MERGE の event-sourced 精神を継承するが、実装は再利用しない。

## 18. taxonomy

taxonomy 分類は **metadata**（METADATA_ONLY）であり identity・fingerprint・資格に関与しない。語彙の採否と歴史
`theme_taxonomy.yaml` の port は P6-B（PORT LATER。A0.5 §5）。

---

## 19. 資格判定の再述（A1 Q5 の evidence 側具体化。数値 score なし）

算入対象 ＝ `authority_class == PRIMARY_OBSERVATIONAL` かつ role ∈ {SUPPORTS, CONTRADICTS, INVALIDATES} かつ
`evidence_time_quality != MISSING` かつ `role_provenance ∈ {RULE, HUMAN}` の attachment。

| 判定 | 条件 |
|---|---|
| **QUALIFIES_SEMANTICALLY** | A1 Q1〜Q4・Q6〜Q8 を満たし、算入対象について **independent source origin ≥ 2** かつ **evidence 日付 ≥ 2** |
| **THEME_CANDIDATE_POSSIBLE** | Q1〜Q3・Q6〜Q8 を満たすが、算入対象が空、または origin が 1、または日付が 1 |
| **DOES_NOT_QUALIFY** | A1 のとおり（機構なし / 単一 event / 予測・推奨・rule・keyword / evidence 参照が原理的に不可能） |

CONTEXT・DERIVED_INTERPRETIVE・PROPOSAL_ONLY・LLM_PROPOSAL role・MISSING 時点は資格に寄与しない。

---

## 20. 例（14）

| # | 例 | origin | 日付 | 判定 / 扱い |
|---|---|---|---|---|
| 1 | 同一記事の 5 feed 転載を SUPPORTS で付与 | 1 | 1 | CANDIDATE。4 件は REDUNDANT_REFERENCE flag（付与自体は可） |
| 2 | 公式 release → SourceDocument ＋ NewsItem ＋ FactStatement の 3 参照 | 1 | 1 | CANDIDATE |
| 3 | TOPIX Observation と、それから作られた Fact の両方を付与 | 1 | 1 | CANDIDATE。REDUNDANT_REFERENCE |
| 4 | 月次 series の 3 か月分の Fact | 1 | 3 | CANDIDATE（temporal のみ）。 |
| 5 | 公式 release（文書）＋ 独立した市場観測（Fact） | 2 | 2（日付が異なる場合） | QUALIFIES（Q1〜Q4・Q6〜Q8 を満たすなら） |
| 6 | 支持 evidence の後に反証 evidence | — | — | 両方保持。class は自動で下がらない。DERIVED `has_contradicting_evidence` |
| 7 | 反証の後に invalidation condition を満たす evidence | — | — | INVALIDATES（condition ref 必須）。lifecycle は P6-C。root 不変 |
| 8 | label rename | — | — | METADATA_ONLY。observation id・fingerprint 不変 |
| 9 | transmission channel の置換 | — | — | NEW_ROOT_REQUIRED。旧 root は SUPERSEDED_BY を持ち履歴に残る |
| 10 | 1 つの Theme を domain 別に split | — | — | GOVERNANCE_EVENT。新 root 2 つ。evidence は由来を保持して再付与 |
| 11 | taxonomy 再割当 | — | — | METADATA_ONLY |
| 12 | 推定受益 entity の連結 | — | — | INFERRED_EXPOSURE_LINK（provenance ＋ uncertainty）。推奨ではない。root 不変 |
| 13 | Fact の subject が entity である直接連結 | — | — | DIRECTLY_EVIDENCED_LINK（DERIVED） |
| 14 | LLM が提案した role | — | — | `role_provenance = LLM_PROPOSAL`。資格に算入しない。L2 では HUMAN / RULE に置換 |

---

## 21. 不変条件（後続 test 用。A1 §20 の 1〜25 に続く番号）

26. Theme identity は二層（root lineage id ＋ 内容住所の不変 observation）である。
27. root id は内容から再計算できない（生成 id）。fingerprint は root とは別に observation ごとに保持する。
28. observation id は IDENTITY / SEMANTIC CONTENT のみから導出し、PROVENANCE / AUDIT / DERIVED を含まない。
29. 同一 observation id で bytes が異なる書込みは conflict（fail closed）。同一 bytes は冪等。
30. root は evidence の蓄積・label / description / taxonomy の変更・class 変更・scope / 帰結 / limitations の改訂を通じて不変。
31. identity core（subject / driver / channel / domain）の置換は同一 root の revision として書けない（NEW_ROOT_REQUIRED）。
32. fingerprint の一致は identity の同一を意味しない。自動 merge は存在しない。
33. merge / split は理由・対象・actor provenance を伴う governance 事象であり、root は削除されない。
34. 1 root に genesis observation は厳密に 1 つ。fork は UNRESOLVED（推測しない）。
35. evidence は参照であり、値・本文を複製しない。
36. すべての attachment は kind・authority class・revision 固有 ref_id・source origin・evidence_time（basis / quality 付き）・attached_at・role・role provenance を持つ。
37. EVIDENCE_TIME と ATTACHED_AT は別であり、いずれも AUDIT の recorded_at・retrieved_at・created_at で代替しない。
38. 点時刻 T の再構成に現れる evidence は `evidence_time <= T` かつ `attached_at <= T` を満たすものに限る。
39. evidence_time が MISSING の evidence は SUPPORTS / CONTRADICTS / INVALIDATES で付与できず、資格に算入しない。
40. `evidence_time > attached_at` の attachment は拒否される。
41. authority class は PRIMARY_OBSERVATIONAL / DERIVED_INTERPRETIVE / PROPOSAL_ONLY / NOT_THEME_EVIDENCE の 4 値であり、資格に算入されるのは PRIMARY_OBSERVATIONAL のみ。
42. Compass / Brief / Signal / Prediction / Evaluation / Calibration / legacy config / LLM 出力は Theme evidence にならない。
43. Theme は ContextItem を用いずに PRIMARY evidence のみで資格を満たせなければならない。
44. 転載・改訂・同一 origin の派生は独立 source origin として数えない。判定不能は独立ではない。
45. 同一 series の複数日付は temporal diversity であって source diversity ではない。Q5 は両方を要求する。
46. 独立性・多様性は集合の濃度による述語であり、重み・score・閾値を持たない。
47. role は SUPPORTS / CONTRADICTS / CONTEXT / INVALIDATES の 4 値。TRIGGER は role ではなく metadata。
48. 1 attachment に role は 1 つ。role の訂正は新 observation であり旧 role は履歴に残る。
49. CONTRADICTS / INVALIDATES が 0 件であることは正当。反証の不在は確証ではない。
50. INVALIDATES は invalidation condition への参照を必須とし、lifecycle を自動で変えない。
51. role provenance は RULE / HUMAN / LLM_PROPOSAL の 3 値。LLM_PROPOSAL は資格に算入せず L2 に存在しない。
52. evidence の authority と role の真偽は独立である。
53. 機構は DRIVER / TRANSMISSION_CHANNEL / AFFECTED_DOMAIN / EXPECTED_OBSERVABLE_CONSEQUENCE の型付き component から成り、prose ではない。
54. 確度 class は observation level に 1 つであり、component level の class・平均・算術は存在しない。
55. expected consequence は価格 target・評価 horizon・正誤を持たず、P5 に流入しない。
56. entity link は DIRECTLY_EVIDENCED / INFERRED_EXPOSURE / TAXONOMIC_ASSOCIATION の 3 class であり、INFERRED は provenance と不確実性を持ち推奨ではない。
57. 市場確認 mapping は別の version 付き記録であり、identity・fingerprint・P5・昇格 / 降格に関与しない。
58. invalidation condition は不変 observation の semantic content に属し、contradicting evidence は attachment 集合に属する。
59. label / description / taxonomy / alias は observation に含まれず、変更は新 observation を生まない。
60. fuzzy match・embedding・自動 dedup は Phase 6 の identity 判定に用いない。

---

## 22. 本 gate の範囲外（残件）

- **A3（Family C）**: 物理 record 形式と field 名の最終確定、append-only authority と derived index、observation
  chain の解決規則（fork / dangling）、governance 事象と metadata 記録の形式、点時刻再構成の全規則（D7 / D8 / D17
  再構成側）、mapping 記録の version 化の実体。
- **B / C / D（P6-B 以降）**: D10 graph、D11 lifecycle、D12 discovery、D13 dedup heuristics、D14 粒度、D18 Brief 消費、
  D21 legacy、D22 Phase 7 契約、taxonomy 採否、機構語彙の初期集合、Statement producer。
- 既知の上流 gap（提案のみ。本 gate では変更しない）: Fact.known_at の basis quality が Fact schema に無い；
  Statement の producer / store が無い；entity catalog が無い。

## 23. 次 gate

**P6-A3 Theme Persistence ＋ Revision Contract**（Family C）。本書は P6-A3 の入力である。
