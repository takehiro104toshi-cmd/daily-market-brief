# PHASE 6 FOUNDATION DECISIONS（Theme・土台 / port / 境界の凍結事項）

本書は **Phase 6（Theme）の P6-A0.5 gate** の記録である。P6-A0（Theme Foundation Audit、
`P6_A0_THEME_FOUNDATION_AUDIT_COMPLETE`、監督者受理済み）の実測に基づき、監督者決定 F-1〜F-10 と
D0（歴史資産の port 方針）の解決を凍結する。本書は設計事項であり、変更は監督者の決定による。
実装（ThemeRecord / ThemeStore / discovery / lifecycle / graph / LLM）は含まない。作成日 2026-09-19。

- 前提 Phase: Phase 5（`PHASE_5_COMPLETE / CLOSED / FROZEN`、anchor `edbd0f203fd2b96a5dbfff921ccf0ba584cbef88`）。
  P4 / P5 の凍結境界（`PHASE5_ENTRY_CONTRACT.md` §1・§9、`PHASE5_COMPLETION_AUDIT.md` §14）を継承する。
- 開発 branch: `claude/investment-intelligence-phase5`（production main `15739707…` 系譜の curated bundle）。
- 参照 branch: `claude/investment-intelligence-phase0-rvdplu`（Phase 0〜4 の歴史記録。**参照のみ**）。

---

## 0. 受理された P6-A0 の結論（要約）

- 実装済み Theme 層は存在しない。歴史 branch の `src/intelligence/themes/` は docstring のみの placeholder。
- 現 branch は curated production bundle であり、歴史 branch の研究 / 統治 subsystem（corpus /
  corpus_research / enrichment engine / decision / formal_review / replay 等）、theme taxonomy・graph・
  entity catalog・causal_rules の knowledge、約 100 本の設計 doc、intelligence test 93 本を持たない。
- 現 branch の Fact / Context / Market は point-in-time primitive（`known_at` / `as_of` / `primary_date` ＋
  `date_role` / `cutoff`、look-ahead 除去、決定論 id、`revision_of`）が強い。Fact は数値（市場・財務）のみ。
- 永続化 precedent は 3 世代（Fact / Context / Compass store ＝ JSONL ＋ SQLite・破損行 skip、
  ArticleIdentity ＝ event-sourced、P5 ＝ 厳密 append-only・fail closed・single writer）。
- `EvidencePackage` は Compass 専用の session-budgeted package（A0 判定 B、下位 primitive は C）。
- BLOCKER なし。設計判断は D0〜D22 として列挙された。

---

## 1. 監督者決定 F-1〜F-10（凍結）

| # | 決定 |
|---|---|
| **F-1 開発土台** | Phase 6 は `claude/investment-intelligence-phase5` 上で続ける。歴史 branch を merge / rebase しない。歴史 subsystem を wholesale で cherry-pick しない。歴史資産は後続 gate が選択的 port を明示認可するまで**参照資料**。理由: 現 branch は production-safe bundle であり、研究・統治・機密・Windows 固有・歴史 runtime 依存を誤って復活させない |
| **F-2 架構上の位置** | Theme は**新しい内部 intelligence 層**。依存方向は 下位 evidence / data → Theme → 将来の内部 Theme intelligence → 将来の Phase 7 Narrative。Theme は当初 CompassDraft / CompassOutlook / NarrativePlan / MorningBrief / MarketSignal / PredictionRecord / EvaluationRecord / CalibrationReport / 顧客 rendering / 公開 `/v2` / legacy report 出力に依存しない。凍結 P4 / P5 module は Theme を import しない。Theme → Compass 統合なし、Compass → Theme authority 移転なし、P5 → Theme feedback なし。将来の接続は別 gate |
| **F-3 作業定義** | Theme ＝「複数の観測を時間を通じて結び、その支持・反証・変化を点時刻で再構成できる、持続的で evidence に裏付けられた市場 / 投資の仮説・機構」。keyword・news tag・sector・ticker 群・Morning Brief 区分・散文 narrative・予測・推奨・Compass rule の**いずれでもない**。Theme は構造化のまま保つ。可読 narrative は主として Phase 7 |
| **F-4 MVP 順序** | 土台を discovery より先に証明する: ①Theme identity ②evidence 付与 ③支持 vs 反証 ④不変履歴 ⑤点時刻再構成 ⑥決定論的 change 表現。その後に自動 discovery / lifecycle / graph / LLM 補助 / Morning Brief 消費 / 顧客提示。**永続化と履歴の正しさが土台**であり discovery は土台ではない |
| **F-5 evidence authority 原則** | RAW / OBSERVATIONAL evidence と DERIVED / INTERPRETIVE context を区別する。primary 候補: Fact、market Observation、SourceDocument / NewsItem、provenance が十分な factual Statement。derived 候補（後日）: ContextItem、derived market / internals 解釈。ContextItem を黙って primary と同等にしない。evidence contract は明示的な kind / authority class を保持する（enum 名は未凍結）。Compass 出力・MorningBrief・Prediction / Evaluation / Calibration は Theme evidence authority ではない |
| **F-6 EvidencePackage** | Compass `EvidencePackage` を Theme evidence container として再利用しない。再利用してよいのは下位原則（不変 evidence 参照・content-address identity・cutoff / known-at 規律・明示的除外・provenance・fail-closed 検証）のみ |
| **F-7 履歴原則** | 黙った履歴書換えを禁止。可変 Theme row・lineage 無しの latest-wins・repo commit される可変 learning JSON・上書き型 Theme state を使わない。旧 state / 履歴・訂正・evidence 追加・反証・点時刻再構成を保持する。revision / event model の確定は P6-A2 / A3 |
| **F-8 永続化の品質下限** | Theme authority の永続化は **P5 append-only journal の規律以上**: append-only authority、canonical 直列化、厳密冪等、同一 identity の内容差は fail closed、破損 fail closed、data_root 明示、repo 永続化なし、当初 single-writer、再構築可能な derived index は可。本 gate では store を実装しない |
| **F-9 legacy theme learning** | `data/theme_learning/theme_learning.json` / `src/analysis/theme_learning.py` は Phase 6 の永続化・学習の precedent ではない（legacy 挙動のみ）。上書き / 勝率 / confidence feedback 設計を port しない |
| **F-10 較正の分離** | Phase 5 較正結果は Theme の昇格 / 降格 / confidence / lifecycle / evidence / graph / Compass DNA を変更しない。Phase 6 に自動 performance-feedback loop は無い |

---

## 2. D0 の解決 — 歴史資産の port 方針

### 2.1 中心判断

**Phase 6 の土台（identity / evidence 参照 / 支持・反証 / 不変履歴 / 点時刻再構成 / change 観測）は、
歴史 Phase 0〜4 の runtime source file を 1 本も import せずに、現 branch の primitive ＋ 新規に隔離した
Theme model で正しく構築できる。**

根拠（現 branch に存在する primitive）:

| 必要能力 | 現 branch の primitive |
|---|---|
| 決定論 identity | `core.ids.content_id(prefix, *parts)`（sha256 先頭 24 hex）、P4 / P5 の canonical JSON 慣行（`sort_keys` / compact / `ensure_ascii=False`） |
| 時刻規律 | `core.time.ensure_aware` / `to_utc_iso`、Fact `known_at` / `as_of` / `primary_date`・`date_role`、Observation `as_of` / `trading_date` / `revision_of`、SourceDocument `published_at` / `retrieved_at` / `date_quality` |
| 参照可能な primary evidence 型 | `facts.model.Fact`（`fact_id`、`FactEvidenceRef`）、`market.model.Observation`（`observation_id`、`series_id`）、`sources.model.SourceDocument`（`source_document_id`、`content_hash`、`revision_of`）、`databank.news_model.NewsItem`（`news_item_id`、`article_id`）、`evidence.model.Statement` / `EvidenceRelation`（SUPPORTS / CONTRADICTS / DERIVED_FROM / CONTEXT の語彙） |
| 履歴 / 永続化の設計 precedent | P5 `prediction_store` / `evaluation_store`（append-only・canonical 行冪等・fail closed・single writer・supersession は新行）、P5-3A resolver（曖昧は UNRESOLVED、推測しない）、`databank.article_store`（event-sourced ＋ replay）、Fact / Context の `revision_of` ＋ 再構築可能 index |
| テスト fixture | 上記 model の frozen dataclass constructor はすべて現 branch にあり、producer 無しで不変 fixture を作れる（P5 が凍結 builder だけで E2E を組んだのと同じ流儀） |

したがって **A（PORT REQUIRED BEFORE FOUNDATION）は空集合**である。P6-A1 / A2 / A3 は現 branch のみで進める。

### 2.2 歴史資産の分類

凡例: 依存 = 歴史 branch 上の import。機密 = §6 の実測。判定 A / B / C / D。

| 資産 | 元の目的 | 依存 | authority | 機密 / 結合 risk | 意味論の有用性 | code port | idea / spec 再利用 | 判定・時期 |
|---|---|---|---|---|---|---|---|---|
| `knowledge/enrichment/theme_taxonomy.yaml`（30 slug、parent / related、多信号規則、v1.0.0） | 記事分類語彙 | なし | knowledge（Phase 2-E） | なし（公開語彙） | discovery vocabulary / 任意分類として有用。**identity にはしない** | 後日可（YAML） | ○ | **B PORT LATER**（P6-B discovery / Family D。taxonomy 採否決定後） |
| `knowledge/theme_relations/themes.yaml`（label ＋ keywords ＋ en_aliases） | legacy config の移設 | なし | Stage 1 copy | なし | seed label として参考。keyword 判定は Theme evidence ではない | 後日可 | ○ | **B**（P6-B。seed 候補としてのみ） |
| `knowledge/theme_relations/theme_graph.yaml`（無向隣接、supplementary_nodes 8、「方向・重みは Phase 6」） | Theme Map 初期グラフ | なし | Stage 1 copy | なし | node 集合の種。edge 意味論は未定義（無向・無版） | 後日可（再型付け前提） | ○ | **B**（P6-D graph。edge type 決定後に seed として） |
| `knowledge/entities/core_entities.yaml` ＋ `docs/databank/ENTITY_CATALOG_SPEC.md` | entity catalog（alias 安全度 3 段、country / sector は属性） | なし | knowledge（Phase 2-E） | なし（公開企業名・ticker） | entity linkage に有用。Theme identity には不要 | 後日可 | ○ | **B**（entity linkage gate。spec は今から C 参照） |
| `knowledge/causal_rules/{market,fx,rates}.yaml` | 見出し trigger → 恩恵 / 逆風 sector | なし | Stage 1 copy（`config.yaml causal_rules` と同内容。現 branch の config に既存） | なし（「原文引用ではない」と明記） | keyword trigger は Theme evidence にならない。edge 仮説の種になりうるが再 evidence 必須 | 不要（現 config に同内容） | △ | **C REFERENCE ONLY** |
| `enrichment/theme_matcher.py`（strong / weak signal、exclude、`ThemeMatch.strength/role`） | L2 rule 分類 | なし | Phase 2-E | なし | 決定論 discovery の precedent | 後日可（純関数） | ○ | **B**（P6-B。taxonomy と同時） |
| `enrichment/taxonomy.py`（ThemeTaxonomy / EventTaxonomy loader） | YAML loader | yaml | Phase 2-E | なし | taxonomy 採用時に有用 | 後日可 | ○ | **B**（P6-B） |
| `enrichment/llm_classifier.py` | L3 LLM 提案（固定 slug からのみ、`rejected`、audit） | `core.contracts.LLMProvider`、`databank.news_model` | Phase 2-E（optional） | vendor 中立、鍵なし | 「LLM は candidate を出すだけ・canonical に直接入れない」境界の precedent | 不要（NewsClassification 結合） | ○（境界 pattern） | **C**（LLM 補助 gate で pattern を再表現） |
| `enrichment/store.py` / `override.py` | 分類 JSONL ＋ event 監査、USER override / RETRACT、effective view | `core`、`databank.news_model` | Phase 2-E | 破損行 skip（F-8 未満） | 「撤回は削除でなく event」「override は履歴保持」の precedent | 不可（F-8 未満・別 model 結合） | ○ | **C** |
| `facts/news_builder.py`（`document_published` Fact、101 行） | SourceDocument → Fact | `facts.model` のみ | Phase 3-A | なし | F-5 により SourceDocument / NewsItem を直接 primary evidence にできるため、Fact 化は必須でない | 後日可（低 risk） | ○ | **B**（evidence producer gate。必要と判明した場合のみ） |
| `evidence/jsonl_store.py`（Statement / Link / Document / Observation JSONL） | Evidence 参照実装 store | `core.serialization`、`market.model`、`sources.model` | Phase 1-A | 破損行 skip・registry 直列化（F-8 未満） | Statement 永続化を選ぶ場合の参照。そのままの port は F-8 に反する | 不可（再設計） | ○ | **C**（Family B / C で Statement 永続化を選べば新設計） |
| `corpus_research/lifecycle.py`（OBSERVED → … → STRONG_PATTERN_CANDIDATE、`SupportProfile`、limitations 必須） | 誌面 pattern の lifecycle | なし（閾値は歴史 `config compass_research`） | Phase 3.8 研究 | なし | 「件数だけで昇格しない」「limitations 必須」「regime 多様性 / span」は Theme lifecycle の直接 precedent | 不要（P6-C で再表現） | ○ | **C**（Family D / P6-C） |
| `corpus_research/patterns.py` | pattern identity / assignment | なし | 研究 | なし | components の canonical 化は identity 設計の参考 | 不要 | △ | **C** |
| `corpus_research/review_queue.py`（`NEW_THEME_CATEGORY` 等、auto approval なし） | 監督者 review queue | なし | 研究 | なし | 「新 category は人間 review」の precedent | 不要 | ○ | **C** |
| `corpus_research/risk_model.py`（COUNTERARGUMENT / INVALIDATION_CONDITION …） | 誌面 risk 分類 | `corpus.structured_record`（**機密 corpus subsystem**） | 研究 | corpus 結合 | risk / 反証の語彙は参考 | **不可** | ○（語彙） | **D DO NOT PORT**（語彙のみ C） |
| `corpus_research/why_model.py`（co-occurrence ≠ causality） | 誌面 WHY 分類 | `corpus.structured_record` | 研究 | corpus 結合 | 原則は Theme graph に必須 | **不可** | ○（原則） | **D**（原則のみ C） |
| `corpus_research/regime.py`（MarketConnector、regime_key） | 誌面と市場 regime の整合 | `corpus.coverage/temporal`、`market.jquants_light_store`（遅延 import） | 研究 | corpus ＋ light store 結合 | regime_key の発想は参考 | **不可** | △ | **D** |
| `decision/**`（10 file: states KEEP_REVIEWING / APPROVED / REJECTED / REOPENED / SUPERSEDED / RETIRED、`promotion_status`、hash chain store、human-only、reason 必須） | pattern の人間承認 | `corpus_research.store`、`core.paths` | governance（Phase 3.9.1） | hash chain（P5 N-3 が避けた方式）、研究 corpus 結合 | 「auto approval なし・human-only・reason 必須・promotion は別 gate」は原則として継承 | **不可** | ○（原則） | **D**（原則のみ C） |
| `formal_review/**`（21 file: packet digest、two-stage confirmation、advisory 語禁止、progression、Windows real-data validation） | 初回 formal DNA review | `decision`、`evaluation`、`shadow_review`、`replay`、`corpus`、`corpus_research` | governance（Phase 3.9.5） | 5 subsystem 結合、PDF 名 / path の遮断 logic（Windows 実データ検証由来） | 「two-stage confirm」「packet を digest で束ねる」「助言語を出さない」は参考 | **不可** | ○（原則） | **D**（原則のみ C） |
| `docs/compass_dna/THEME_DISCOVERY_RULES.md` | 羅針盤の Theme 展開方法論 | — | Phase 0 doc | **§1 / §3 は機密 Compass 各号（6/18〜7/1）由来の named company chain と号・頁の引用を含む** | §2（需要起点 → 制約 → 技術 → 供給網 → 実データ確認 → risk）・§5（Emerging 信号類型）・§6（禁止事項）の**原則**は有用 | — | ○（原則を抽象化して。named chain・号引用は転記しない） | **C REFERENCE ONLY（機密注意）** |
| `docs/databank/THEME_TAXONOMY_SPEC.md` | taxonomy 仕様 | — | Phase 2-E doc | なし | 階層 foundation・変更管理（slug 意味変更禁止）は参考 | — | ○ | **C**（taxonomy 採用時に B） |
| 歴史 `src/intelligence/themes/__init__.py` | Phase 6 placeholder（「テーマグラフ…Emerging 検出」） | — | — | なし | F-3 / F-4 の順序（土台 → discovery）と**食い違う**枠組み | **不可** | × | **D**（package 作成時に新しい docstring を書く） |
| legacy `data/theme_learning/theme_learning.json` / `src/analysis/theme_learning.py`（現 branch に存在） | 勝率 feedback | legacy | legacy | repo 追跡の可変 JSON | なし（F-9） | 不可 | × | **D**（F-9。現状のまま触れない） |

### 2.3 port 方針（凍結）

1. **A ＝ 空**。P6-A1 / A2 / A3 は歴史 runtime file を import せず、現 branch primitive ＋ 新規 Theme model で定義する。
2. **B** の port は、それを必要とする gate（P6-B discovery、P6-D graph、entity linkage、evidence producer）が
   **個別に認可**したときに、file 単位で、依存と機密を再点検して行う。wholesale merge / cherry-pick は行わない。
3. **C** は仕様・原則として本書と後続 contract に**抽象化して**書き写す。code・原文・号 / 頁引用・named chain は転記しない。
4. **D** は port しない。原則（no auto approval / human-only / reason 必須 / co-occurrence ≠ causality / limitations 必須）
   だけを C として継承する。
5. port する場合も F-8（append-only・fail closed）を下回る store 実装（破損行 skip、registry 直列化）は
   そのまま採用せず再設計する。

---

## 3. 文書 / ニュース evidence の gap（§4）

| 問い | 答え |
|---|---|
| P6-A1 / A2 は producer（news_builder / evidence jsonl_store）無しで evidence contract を定義できるか | **できる**。contract は「参照（kind ＋ id ＋ 時点 ＋ role ＋ provenance）」であり、参照先の実在検証は解決（resolver）の関心事として明示分離できる（P5-3A が dangling を診断 status にしたのと同じ） |
| テストは不変 model fixture で始められるか | **できる**。`Fact` / `Observation` / `SourceDocument` / `NewsItem` / `Statement` の frozen constructor は現 branch にあり、P5 と同様 builder だけで E2E を組める |
| 実際の文書由来 evidence 経路に最低限必要な component | **SourceDocument 参照であれば追加 port は不要**。現 branch に `normalization.feed_normalizer` / `tank_article_normalizer` → `JsonlNormalizedStore.add_documents`、`databank.identity_runtime`（NewsItem 構築）が存在する。Fact 型の文書 evidence が必要と判明した場合のみ `facts/news_builder.py`（B）。Statement 永続化を選ぶ場合は F-8 準拠の新設計（C） |
| SourceDocument / NewsItem は Statement 永続化無しで evidence 参照として十分か | **十分**（`source_document_id` 内容住所、`published_at` ＋ `date_quality` ＋ `published_inferred`、`retrieved_at`、`source_id` / `source_tier`、`content_hash`、`revision_of`、`canonical_locator`）。文単位の主張（Statement）が必要になるのは Family B の判断 |
| news_builder を今 port すると土台を旧 pipeline に結合するか | **する**。F-5 により文書を直接 primary evidence にできるため、今は不要 |

決定: **FOUNDATION CONTRACT FIRST. REAL DOCUMENT PRODUCER LATER.**

## 4. entity gap（§5）

Theme identity と Theme → entity linkage は分離する。土台は entity catalog を必要としない（identity は evidence と
lineage から決まり、entity は evidence が持つ `subject_id` / `series_id` / `security_id` / `EntityReference` を
参照するに留まる）。entity catalog（`core_entities.yaml` ＋ spec）は **B PORT LATER**（entity linkage gate）。
directly evidenced exposure と inferred beneficiary / loser の区別（A0 §29）は Family B の決定事項として残す。

## 5. taxonomy gap（§6）

| 案 | 新興 Theme | dedup | 安定 identity | 階層 | 人間 review |
|---|---|---|---|---|---|
| A. taxonomy slug ＝ Theme identity | 新 slug 追加まで表現不能（発見の遅れ） | slug で強制（粗い） | slug 意味変更禁止に依存 | taxonomy の parent に固定 | slug 追加が review 対象 |
| B. 独立 identity ＋ 任意の taxonomy 分類 | 可能（分類は後付け） | identity とは別に resolver が必要 | evidence / lineage で定義 | 分類側に任せられる | Theme と分類の両方 |
| C. taxonomy は discovery 語彙のみ | 可能 | B と同じ | B と同じ | 語彙側のみ | B と同じ |

決定: **土台は B（独立 identity）を前提に設計し、taxonomy は C（discovery 語彙）として P6-B で採否を決める。**
Theme identity を taxonomy slug と同一にしない（監督者 bias と一致。repository に反対の強い証拠は無い）。
taxonomy 意味論は凍結しない。

## 6. 歴史 lifecycle / governance（§7）

runtime 依存にしない。model の選択的 port も行わない。**仕様参照のみ**で、次の原則を Family A / D の contract に
抽象化して継承する: auto approval なし、limitations 必須、evidence 件数だけでは不十分（多様性・期間）、
co-occurrence ≠ causality、曖昧 / 新 category は人間 review、撤回・訂正は削除でなく履歴に残す、
助言語を出さない。歴史 `decision` / `formal_review` は 5 subsystem に結合し、hash chain と Windows 実データ検証を
含むため、全体 import は不可。原則だけで実現可能であることは、P5 が同じ原則を独自 module で満たした実績が示す。

---

## 7. Phase 6 package 境界（将来。本 gate では作成しない）

- 予定 package: `src/intelligence/themes/`（`tests/intelligence/test_p43b2c_production_bundle.py` の
  `EXCLUDED_PACKAGES` に既に列挙済み → production runtime closure から機械的に排除される）。
- **許可する import（狭く。module 単位）**: `core.ids`、`core.time`、（必要なら）`core.types` の定数、
  `facts.model`、`market.model`、`sources.model`、`databank.news_model`、`evidence.model`。
  `context.model` は「DERIVED / INTERPRETIVE evidence」として後続 gate が明示認可した場合のみ。
- **禁止**: `compass.*`、`reports.*`、`predictions.*`、`internals.*`（`compass_claims` を含む）、
  `context.builders / salience / snapshot / store`、`market.store / providers / jquants_* / backfill / pilot_runner`、
  `ingestion.*`、`normalization.*`、`databank.backfill / article_store / identity_*`、network、
  `src.analysis` / `src.report` / `src.collectors` / `src.data` / `notifiers`、顧客 rendering、公開 artifact。
- package 全体の import で済ませず、model module に限定する。凍結 P4 / P5 module は `themes` を import しない。

## 8. evidence authority 境界（F-5 の具体化。enum 名は未凍結）

| class | 候補 | Theme での扱い |
|---|---|---|
| PRIMARY / OBSERVATIONAL | Fact（USABLE / LIMITED_USE と qa_decision を保持）、market Observation（raw / derived を区別）、SourceDocument / NewsItem、provenance 十分な factual Statement | 支持 / 反証の evidence になりうる |
| DERIVED / INTERPRETIVE | ContextItem、internals 解釈 | 明示 class 付きの文脈として後日認可されるまで付与しない。primary と同等に数えない |
| NOT EVIDENCE AUTHORITY | CompassDraft / Outlook / Plan / claim、MorningBrief / MarketSignal、PredictionRecord / EvaluationRecord / CalibrationReport、legacy config theme / causal_rules、LLM 出力 | 参照 provenance にはなりえても Theme の根拠にしない |

各 evidence 参照は少なくとも「kind / class、参照 id、evidence 自身の時点（known_at / as_of / published_at）、
付与時点、role（支持 / 反証 / 文脈 等）、provenance」を持つ（field 名は P6-A2）。

## 9. 土台 MVP の contract 目標（class 名は未凍結）

```
Theme lineage root（安定・evidence が変わっても同一性を保つ）
  ↓
不変の Theme observation / revision record（content-address、root と前任を参照）
  ↓
evidence 参照（primary kind、id、evidence 時点、付与時点、provenance）
  ↓
支持 / 反証 role（反証 0 を隠さない）
  ↓
append-only 履歴（F-8。訂正は新 record、旧 record 保持）
  ↓
点時刻再構成（付与時点 ≤ T かつ evidence 時点 ≤ T の集合として決定論的に再構成）
  ↓
決定論的 change 観測（2 時点の再構成差分: 追加 / 反証 / 訂正 の列挙。scoring なし）
```

MVP が**除外**するもの: 自動 Theme discovery、LLM、lifecycle scoring / state promotion、Theme graph、
entity beneficiary 推定、ticker 推奨、Morning Brief、Compass、P5 較正、顧客 / 公開出力、network /
runtime scheduling、taxonomy 依存、legacy theme learning。

---

## 10. 非目標（Phase 6 全体・F-1〜F-10 由来）

歴史 branch の merge / rebase / wholesale port、P4 / P5 の再開・変更、MarketSignal / PredictionRecord /
EvaluationRecord / 較正 metric / Compass DNA / TOPIX 閾値 / confidence 意味論の変更、Theme ↔ Compass /
Theme ↔ DNA / P5 → Theme の feedback、顧客出力 / `/v2` / workflow / runtime 統合の変更、Phase 5 deferred
（runtime capture / 評価 scheduling / 較正 persistence・UI）と Phase 4 deferred（通知 / root cutover）の吸収、
H0 security の混在。

## 11. 未解決決定の再編（P6-A1 / A2 / A3 以降）

| family | gate | 決定 |
|---|---|---|
| **A SEMANTICS / AUTHORITY** | P6-A1 | D1 Theme の形式定義（F-3 を schema へ）／D2 Theme vs Narrative／D3 Theme vs Context／D4 Theme vs Compass（(a) 独立下流 / (b) 並列。(c) は不可）／D16 human review / governance の重さ |
| **B IDENTITY / EVIDENCE** | P6-A2 | D5 evidence authority（許可 kind と class）／D6 identity model（A0 §13 の C / D / 組合せ、root id 付与規則、fork / merge）／D9 支持 / 反証 model（role 語彙、missing evidence）／D15 entity linkage 境界（directly evidenced vs inferred）／D19 市場確認 series の対応表の所在／D17 の evidence 側時点（evidence 時点と付与時点の二重化） |
| **C HISTORY / PERSISTENCE** | P6-A3 | D7 revision / event model（A0 §26 の B / C / D）／D8 append-only authority と derived index（F-8）／D17 の再構成規則（cutoff 意味論、決定論 replay） |
| **D LATER INTELLIGENCE** | P6-B 以降 | D10 graph 表現／D11 lifecycle／D12 discovery 方式／D13 dedup／D14 granularity / hierarchy／D18 Morning Brief 消費境界／D21 legacy config theme 節・theme_learning の扱い／D22 Phase 7 出力契約／taxonomy 採否（§5） |
| （engineering hygiene・family 外） | P6-A2 / A3 | D20 現 branch の test gap → §12 の最小 guard 方針で扱う |

D0 は本書で解決済み。

## 12. 最小 guard 方針（現 branch の test gap、§13）

- Theme 土台が実際に消費する primitive: `core.ids.content_id`、`core.time`、`facts.model`、`market.model`、
  `sources.model`、`databank.news_model`、`evidence.model`。現 branch でこれらを直接検査する unit test は
  無い（P5 テストが `market.model.Observation` と `content_id` 形式を間接的に固定している）。
- 方針: 歴史 test 93 本（`test_fact_layer` 920 行、`test_context_engine` 813 行、`test_compass_generator`
  1,057 行 等）を wholesale 復元しない。`themes` package を作る gate（P6-A2 / A3）で、
  (1) themes の import 境界 test（P5 の `ALLOWED_CLOSURE` 方式。許可 module 集合と禁止 package）、
  (2) 消費 primitive の contract test（`content_id` 形式、aware datetime 強制、Fact / Observation /
  SourceDocument の constructor 不変条件のうち Theme が依存するものだけ。目安 50〜100 行）、
  (3) 既存 production bundle guard（`themes` 排除）の維持、を最小構成とする。
- 分類: 必要（後日・再表現）＝ fact identity / availability cutoff / observation aware・revision の数点；
  無関係 ＝ context / compass / internals / market provider の test；重複 ＝ `test_import_boundary` /
  `test_legacy_isolation` の legacy import 禁止（現 branch では `src/intelligence/__init__.py` が
  「機械検査」と述べているが対応 test は無い → themes 作成時の境界 test に vNext → legacy 禁止を含める）；
  歴史 subsystem 依存 ＝ corpus / research / decision / formal_review / replay 系 test（対象外）。

## 13. 機密 / security の port 点検（§14）

| 資産 | 所見 |
|---|---|
| knowledge yaml（taxonomy / themes / theme_graph / entities / causal_rules） | 秘密・machine path・PDF・Windows 依存なし。企業名 / ticker は公開情報。causal_rules は「原文引用ではない」と明記され、同内容が現 branch の `config.yaml` に既存 |
| `THEME_DISCOVERY_RULES.md` | **機密 Compass 各号（2026-06-18〜07-01）由来の named company chain と号 / 頁引用**を含む（§1 発火点実例、§3 連鎖マップ）。参照のみ。production branch へ doc として再追跡しない。原則（§2 / §5 / §6）は抽象化して継承 |
| `THEME_TAXONOMY_SPEC.md` / `ENTITY_CATALOG_SPEC.md` | 秘密・path なし（tank 歴史 corpus の件数言及のみ） |
| enrichment 5 file | `LLMProvider` 境界のみ（vendor 中立、鍵なし）。store は「Secret を含めない」audit 方針。破損行 skip は F-8 未満 |
| `facts/news_builder.py` / `evidence/jsonl_store.py` | 秘密なし。jsonl_store は registry 直列化・破損行 skip（F-8 未満） |
| corpus_research 6 file | `risk_model` / `why_model` / `regime` は `corpus.*`（機密 corpus subsystem）に結合、`regime` は light store を遅延 import。`lifecycle` / `patterns` / `review_queue` は import なし |
| `decision/**` / `formal_review/**` | 秘密・絶対 path なし。hash chain store、`formal_review/pilot.py` / `validation.py` に PDF 名・`\\` path の遮断 logic（Windows 実データ検証由来）。5 subsystem 結合 |
| 歴史 themes placeholder | 問題なし（ただし枠組みが F-3 / F-4 と不一致） |
| repo 追跡の可変 runtime data | 現 branch の `data/theme_learning/theme_learning.json`（legacy、F-9 で precedent 外。本 gate では触れない） |

本 gate で sanitize / port は行っていない。

## 14. 本 gate の状態

- D0: **解決**（A ＝ 空。歴史 runtime source の import 無しで土台を構築する）。
- 変更: 本書の新規作成と `CHANGELOG.md` のみ。runtime source・test・package・knowledge・workflow は無変更。
- 次 gate: **P6-A1 Theme Semantics ＋ Authority Contract**（Family A）。本書は P6-A1 の入力である。
- P6-A1 の結果: Family A（D1 / D2 / D3 / D4 / D16）は `PHASE6_THEME_SEMANTICS_AUTHORITY_CONTRACT.md` で凍結
  （`P6_A1_THEME_SEMANTICS_AUTHORITY_FROZEN`）。本書 §11 の Family A 行は解決済み。次 gate は P6-A2（Family B）。
- P6-A2 の結果: Family B（D5 / D6 / D9 / D15 / D19 / D17 evidence 側）は `PHASE6_THEME_IDENTITY_EVIDENCE_CONTRACT.md`
  で凍結（`P6_A2_THEME_IDENTITY_EVIDENCE_CONTRACT_FROZEN`）。本書 §11 の Family B 行は解決済み。D17 の再構成側と
  D7 / D8 は Family C に残る。次 gate は P6-A3（Family C: persistence ＋ revision contract）。
- P6-A3 の結果: Family C（D7 / D8 / D17 全体）は `PHASE6_THEME_PERSISTENCE_REVISION_CONTRACT.md` で凍結
  （`P6_A3_THEME_PERSISTENCE_REVISION_CONTRACT_FROZEN`）。本書 §11 の Family C 行は解決済み。契約 gate（A0〜A3）は
  完了。次 gate は P6-A4a Theme model（`src/intelligence/themes/` の model module のみ。§7 の import 制限）。
