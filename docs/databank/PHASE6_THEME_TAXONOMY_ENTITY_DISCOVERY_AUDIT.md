# Phase 6 — Theme Taxonomy / Entity / Discovery Architecture Audit（P6-B4A）

状態: **P6_B4A_THEME_TAXONOMY_ENTITY_DISCOVERY_AUDIT_COMPLETE / READY_FOR_SUPERVISOR_B4_DECISIONS**。
本書は read-only の設計監査であり、runtime・test・knowledge・config・workflow を変更しない。

凍結面（本 gate で変更しない）: Theme Foundation（anchor `12847bf2783330cbd310d24c8310d3bf46469f6a`）、B1 Change
Detection（`e2d5168cb9e595478451b2534ae0080a31ac98d5`）、B2 Lifecycle（`ce2402a085523e526b6b8d2be1202e0e2cd74b8b`）、
B3 Proposal ＋ Dedup（`4808f5e7c0d8cf22709f7597edc44fb4bc4bdb4c`）。

入力（読み取り専用）: `PHASE6_FOUNDATION_DECISIONS.md`（A0.5）、A1 / A2 / A3 契約、B0 監査
（`PHASE6_THEME_INTELLIGENCE_ARCHITECTURE_AUDIT.md`）、B1〜B3 契約、`src/intelligence/themes/model.py` の語彙、
`src/intelligence/theme_intelligence/proposal_model.py` の intake surface、現 branch の evidence model
（`sources.model.SourceDocument`、`databank.news_model.NewsItem`、`facts.model.Fact`、`market.model.Observation`、
`evidence.model` の Statement 系）、および historical branch `claude/investment-intelligence-phase0-rvdplu`
（`247b85beaaf9b977281e74d2a85592924602b075`）の参考資産 12 件（§7。`git show` による read only。port / merge /
cherry-pick なし。機密内容は転記しない）。

用語: **Proposal** ＝ B3 の append-only 提案 record（authority ではない）。**Discovery** ＝ 観測された事実から proposal を
決定論的に生成する層。**rule hit** ＝ discovery rule の述語が入力に成立したという事実（Theme でも evidence 成立でもない）。
**pin** ＝ taxonomy / entity catalog / ruleset の version を proposal 生成に固定すること。

---

## 1. 目的と中核原則

問い: 「観測された事実から、どのように Theme 候補を安全に提案するか」。

中核原則（監督指示 §2 を本書の全判断の前提とする）:

- **Discovery の出力は Proposal である。** Theme・evidence の成立・因果の成立・governance の承認・推奨・予測のいずれでもない。
- rule hit ≠ Theme が存在する ≠ 機構が証明された ≠ evidence が因果を支持する。
- **B3 の THEME_CANDIDATE / EVIDENCE_CANDIDATE を唯一の proposal 出力面とする。** 新しい parallel candidate authority
  （独自の候補 journal・topic hit store・score table）を作らない。
- Theme は自動生成しない。root の実体化は B3 の human ACCEPT → bridge plan → 別 gate の実行だけ。
- 件数・score・順位で候補の種別や確度を変えない（A1 §13、F-10、B3 §15）。

---

## 2. 現在の B3 intake surface（監査結果）

B4 が書き込める「口」は B3 の 2 型だけである。その形式要件が discovery の設計制約になる。

| 面 | 構造（B3 凍結） | discovery への含意 |
|---|---|---|
| `ThemeCandidateProposal` | Foundation の Theme 定義そのもの: `ThemeSubject`（normalized_subject ＋ typed_reference）、`Mechanism`（DRIVER / TRANSMISSION_CHANNEL / AFFECTED_DOMAIN 各 ≥ 1 ＋ EXPECTED_OBSERVABLE_CONSEQUENCE ≥ 1、category は `MECHANISM_CATEGORIES` 語彙、OTHER は normalized_statement 必須、各 component に assertion_provenance）、`certainty_class`、scope（PERIOD_FRAME ちょうど 1 個）、limitations、invalidation_conditions ≥ 1、inferred_links、`evidence_refs: Tuple[EvidenceAttachment]`、provenance、created_at、両 fingerprint（再計算一致） | **構造化されていない候補は型として作れない。** keyword hit だけでは THEME_CANDIDATE にならない（B0 §6 の要件が B3 で型に固定済み）。discovery が THEME_CANDIDATE を出すには 4 component ＋ scope ＋ 無効化条件を**人間が事前に author した template** から供給するしかない（§13） |
| `EvidenceCandidateProposal` | evidence_kind（FACT / OBSERVATION / SOURCE_DOCUMENT / NEWS_ITEM / STATEMENT）、ref_id（kind 別 prefix。STATEMENT は prefix 未確定 ""）、`SourceOrigin`、evidence_time ＋ basis ＋ quality、evidence_date、proposed_role、target_root_id / target_proposal_id（どちらも空可 ＝ 未紐付け候補）、reason（normalized）、locator / note、provenance、created_at | rule hit の自然な出力面。**入力 record から `SourceOrigin` と evidence 時点を決定論的に導く adapter が B4 に必要**（§16 / §20）。STATEMENT は producer が無く prefix 未確定のため MVP では出さない |
| `ProposalProvenance` | proposer_class（RULE / HUMAN / LLM_PROPOSAL）、proposer_ref（≤ 200 字）、rule_version（≤ 200 字）、reason（≤ 500 字） | rule_id は proposer_ref、rule version は rule_version に載る（§11）。**taxonomy / catalog の version pin を置く構造化 field は無い**（§11 / §17） |
| identity（content id） | THEME_CANDIDATE: subject / mechanism / certainty / scope / limitations / invalidation / inferred_links / evidence_refs の identity 部分。EVIDENCE_CANDIDATE: kind / ref_id / source_origin / 時点 / role / target / **reason**。いずれも **provenance・created_at・locator・note は identity 外** | (i) 同じ提案を別 rule・別 version・別時刻が出しても **同一 proposal_id** になる（提案は「何を」で識別され「誰が」では識別されない）。(ii) 同 id 異 bytes は `ProposalConflict`（fail closed）なので、**discovery は append 前に既存 id を除外する差分 step を必ず持つ**（B3 dedup が既に採る方式）。(iii) EVIDENCE_CANDIDATE の `reason` は identity に入るため、rule 由来の reason は **決定論的で version 文字列を含まない canonical template** でなければ rule version ごとに別 proposal が増殖する（§11、決定 D-B4-7） |
| 決定・状態 | ACCEPT / REJECT / DEFER（候補 2 型）、NOT_DUPLICATE（DEDUP_REVIEW）。HUMAN のみ。derived status OPEN / OPEN_DEFERRED / OPEN_UNRESOLVED / ACCEPTED / REJECTED / CLOSED_NOT_DUPLICATE | discovery は decision を読むだけ（§15 の相互作用）。決定を書かない |
| dedup | THEME_CANDIDATE に対する exact semantic / identity-core 一致の DEDUP_REVIEW。counterpart から active REJECTED の候補は除外 | discovery が THEME_CANDIDATE を出したあと B3 dedup を**同じ run で**回すのが自然（§15）。REJECTED 候補の variant が再提案された場合は dedup に現れない（limitation、§24） |
| bridge | `plan_theme_creation_from_accepted_proposal`（THEME_CANDIDATE のみ、root_id なし、実行なし） | EVIDENCE_CANDIDATE の bridge は未実装（§14） |

所見: B3 の型は「Theme ではないものを Theme と呼べない」ように既に閉じている。B4 が追加すべきは **入力側の正規化（taxonomy
/ entity / 出所 / 時点）と rule 評価の決定論**であり、出力型の追加ではない。B3 model の変更は MVP に不要（§23）。

---

## 3. Taxonomy 設計

### 3.1 TaxonomyNode（候補 schema。field 名は B4B で凍結）

| field | 内容 | 備考 |
|---|---|---|
| `slug` | 安定 id。`^[a-z][a-z0-9_]{1,63}$`。**意味変更・rename 禁止**（変更 ＝ 新 slug ＋ 旧 slug の deprecation） | historical spec の規則を継承。Foundation METADATA TAXONOMY の値はこの slug 文字列 |
| `label` / `label_ja` / `description` | 表示用。version 間で変更可（identity ではない） | 説明文に source 原文・named chain を書かない（§19） |
| `parent_slugs` | 0 個以上（DAG）。循環禁止。親は同 version で有効な node | §3.3 |
| `aliases` | 表示 / 検索用の別名。**matching 信号ではない** | 信号語は discovery ruleset 側（§10） |
| `since_version` | この node が導入された taxonomy version | PIT は version 単位（§17） |
| `deprecated_in_version` / `superseded_by` | deprecation した version と後継 slug（0 個以上。split は複数、merge は複数 node が同一後継を指す） | 削除はしない |
| `provenance` | `HUMAN` ＋ 承認者 ref（仮名 / role id）＋ reason | 個人識別情報を置かない |

taxonomy file 全体: `taxonomy_version`（semver）、`published_at`（aware UTC。人間の公開時刻）、`history`（過去 version と
published_at の append-only 列）、`nodes`。file は **version 公開後に不変**（次 version は履歴に追記して発行）。

### 3.2 Taxonomy ≠ Theme identity（Foundation との接続）

- 分類は Foundation の **METADATA TAXONOMY**（`ThemeMetadataRecord.field == TAXONOMY`、`value` は sorted unique の
  slug tuple ＝ **複数 slug を 1 record で持てる現行意味論を維持**。FC-5 不要）。
- version pin: metadata record の `provenance_ref` に `taxonomy:<taxonomy_version>` を置き、`reason` に根拠を書く。
  Foundation は taxonomy を知らないので **slug が pinned version で有効かの検証は B4 側の純関数**
  （`validate_taxonomy_value(value, taxonomy_at(version))`）。Foundation 変更なし。
- taxonomy 変更（rename / deprecation / split / merge）は **新 root でも新 ThemeObservation でもない**。metadata は
  observation の identity payload に含まれない（A2 §12.2 / §18、構造的に保証済み）。既存 root の再分類は root ごとの
  新 metadata record（`previous_metadata_id` で連結、HUMAN provenance または governance METADATA_CORRECTION_APPROVED）。
- **B3 には METADATA 提案型が無い**（§3 で 3 型に限定）。したがって B4 MVP では rule による root の taxonomy 付与提案は
  作らない。taxonomy は (a) rule の routing 語彙（rule.taxonomy_refs）、(b) 人間が metadata を書くときの語彙、(c) 監視 /
  一覧の grouping 軸、としてだけ使う。rule-based 再分類提案が必要になれば B3.1 で `METADATA_CANDIDATE` を追加
  （OPTIONAL_FUTURE、§23）。

### 3.3 構造の選択

| 論点 | 選択肢 | 推奨 | 理由 |
|---|---|---|---|
| tree か DAG か | tree（historical: parent 1 個、深さ ≤ 3）／ DAG（multi-parent） | **DAG、multi-parent 可、循環禁止** | `cpo` は `optical_communication` と `data_center` の両方の下位に置きたい類の node が既に historical に存在する。tree にすると恣意的な単一親を強制する |
| 親の伝播 | 自動伝播あり／なし | **なし**（historical と同じ） | root の TAXONOMY 値は明示 slug のみ。祖先は表示 / grouping 時に derived で計算する。伝播を authority に書くと taxonomy 版の変更で metadata の意味が変わる |
| `related` edge | 持つ（historical: 74 edge）／持たない | **持たない** | 無型の隣接は B0 §4 で REJECT。Theme 間関係は B5 relation journal の領域。taxonomy の隣接を discovery の候補拡張に使うと co-occurrence → 因果の経路になる |
| slug rename | in-place 変更／新 slug ＋ deprecation | **新 slug ＋ deprecation（superseded_by）** | historical spec の「slug の意味変更禁止」を継承。過去 metadata 値の再解釈を防ぐ |
| deprecation | 削除／deprecated_in_version | **deprecated_in_version**（削除なし） | 過去 version の PIT 解決に必要 |
| node の split / merge | — | split: 旧 node deprecated、`superseded_by` に複数。merge: 複数 node が同一後継を指す | root の再分類は自動で行わず、要 review 一覧に出すだけ（B6） |
| PIT lookup | version 指定／時刻指定 | **両方。ただし既定なし** | `taxonomy_at(version)` が正本。`taxonomy_as_of(T)` は `history.published_at ≤ T` の最新 version へ解決。引数なしの「latest」API は作らない（§17） |
| version 互換 | — | node の `since_version` / `deprecated_in_version` で version 集合ごとの有効 node を決定論的に導く。loader は version 履歴の単調増加と、deprecated node を親に持つ node の不在を検証して fail closed | |

---

## 4. Taxonomy content の置き場所

| 案 | 内容 | 人間 review | version 履歴 | 再現性 | production bundle 排除 | 機密 risk | 判定 |
|---|---|---|---|---|---|---|---|
| **A** `knowledge/theme_intelligence/theme_taxonomy.yaml` | 語彙を Git 管理の YAML に置く | **PR diff で review できる** | Git 履歴 ＋ file 内 `history` | version pin ＋ file 内容 digest で完全 | production code は `theme_intelligence` を import しない（closure test）。Pages manifest は path 断片 `knowledge` を公開 tree で禁止（`scripts/p43b2c_pages_manifest.py`） | Git tracked ＝ すべての checkout に存在。**内容方針**（抽象 slug のみ。§19）と hygiene guard が必要 | 採用候補（B と組で） |
| **B** versioned code model ＋ YAML | A の YAML を **code 側の versioned model / loader / validator** が読み、schema 検証・PIT 解決・digest 計算を行う | A と同じ | A と同じ ＋ loader が履歴の単調性を検証 | A と同じ ＋ `content_digest` を run report に記録 | A と同じ | A と同じ | **推奨**（A は B の一部。YAML だけでは検証も PIT も無い） |
| **C** data_root authority journal | `<data_root>/theme_intelligence/taxonomy.jsonl` に F-8 規律で追記 | **PR diff が無い**。review は journal 閲覧 tool が必要 | recorded_at で PIT | data_root が無いと再現できない。test は fixture を journal 形式で持つ必要 | repo に data を置かない規律と整合 | repo に語彙が出ない | 不採用（語彙は **knowledge** であって観測ではない。人間が publish する curated 語彙に append-only journal の機械を当てる利点が薄く、review 性を失う） |

推奨: **B（YAML content ＋ versioned code model）**。配置は `knowledge/theme_intelligence/`（新設 directory。既存
`knowledge/compass_dna/`・`knowledge/market_series/` は不変）。file を作るのは B4B。

付帯規則（B4B で契約化）:

1. YAML は authoring 形式。loader は canonical JSON に正規化して `content_digest` を計算し、run report / proposal の
   pin と併記する（同 version 名で内容が変わっていないことを検知）。
2. 公開済み version の in-place 変更禁止。修正は次 version。
3. taxonomy と **discovery ruleset（信号語・述語）は別 file**（`discovery_rules.yaml` 案）。taxonomy は語彙、ruleset は
   識別規則。historical `theme_taxonomy.yaml` が両者を同居させていた点を分離する（B0 §9 と同じ）。
4. entity catalog も同じ規律で `knowledge/theme_intelligence/entity_catalog.yaml`（§5）。
5. ruleset の trigger 語は taxonomy より機密 risk が高い（§19）。ruleset を repo に置くか data_root 配下の private
   knowledge root に置くかは監督者決定（D-B4-1）。推奨は repo（review 可能性を優先）＋ 内容方針 ＋ guard。
6. YAML 依存（PyYAML）は loader module に限定し、boundary test の許可 import に **loader module だけ** 追加する。
   Foundation / B1 / B2 / B3 は YAML を読まない。

---

## 5. Entity catalog 設計

### 5.1 EntityRecord（候補 schema）

| field | 内容 |
|---|---|
| `entity_id` | `<entity_type>:<slug>`（§6） |
| `entity_type` | §5.2 |
| `canonical_name` / `names_ja` | 表示名。version 間で変更可 |
| `aliases_safe` | 単独で match してよい表記（固有性が高い）。**catalog 全体で一意**（衝突 ＝ load error） |
| `aliases_context` ＋ `context_terms` | 一般語衝突する表記。同一 field 群内に context term の共起が無ければ link しない（historical の 3 段安全度を継承） |
| `identifiers` | 種別付き識別子の列: `{scheme: ticker, value: 7203.T, exchange: TSE, valid_from, valid_to}`、`{scheme: instrument_id, value: index:nikkei225}`、`{scheme: country_code, value: JP}` 等。**ticker は identifier であり identity ではない**。明示記法（`$NVDA` / `NASDAQ:NVDA` / `(7203.T)`）のみ走査 |
| `attributes` | domicile country、sector / industry code 等。entity の**属性**であって記事や Theme の分類ではない（historical spec §3 の分離を継承） |
| `valid_from` / `valid_to` | 世界時間での存在期間（設立 / 上場 / 合併消滅）。空 ＝ 不明（**不明は「常に有効」ではない**。rule binding 時に診断） |
| `superseded_by` | 法的同一性が変わったときの後継 entity id（0 個以上） |
| `provenance` | HUMAN ＋ 承認者 ref ＋ reason ＋ 根拠の種別（公的識別子 / 公式サイト / 監督者指定）。**watchlist 由来という理由を書かない**（§19） |
| `since_version` / `deprecated_in_version` | taxonomy と同じ version 単位の有効性 |

catalog file: `catalog_version`、`published_at`、`history`、`entities`、`vocabularies`（sector / industry code 表）。

### 5.2 entity type（適否判定）

Foundation の `EntityRef.kind` は `ThemeEntityKind`（country / company / ticker / sector / industry / commodity /
currency / central_bank / index / government / person。`databank.news_model.EntityKind` の鏡像）で**検証される**。
`InferredExposureLink.entity` はこの kind しか取れない。一方 `ThemeSubject.typed_reference` と `MechanismComponent.
typed_reference` は自由文字列（≤ 200 字）で、`<kind>:<value>` 規約は契約上のもの。

| 監督指示の候補 | 判定 | 理由 |
|---|---|---|
| COMPANY | **採用**（`company`） | Foundation kind あり |
| INDEX | **採用**（`index`） | Foundation kind あり。market catalog の `instrument_id` と id を揃える（historical の結線点を継承） |
| INDUSTRY | **採用**（`industry`）。SECTOR も採用（`sector`） | Foundation kind あり。scope INDUSTRY token の値域にもなる |
| COMMODITY | **採用**（`commodity`） | Foundation kind あり |
| CURRENCY | **採用**（`currency`） | Foundation kind あり |
| COUNTRY_REGION | **COUNTRY として採用**（`country`）。REGION（EU / ASEAN 等の bloc）は **entity ではなく scope REGION token の値** | Foundation kind は `country` のみ。bloc を country entity にすると domicile 属性と衝突する（historical は EU を note で明示していた） |
| TECHNOLOGY | **B4 では entity にしない** | Foundation kind に無い（追加 ＝ 語彙 version 変更 ＝ Foundation 変更）。技術は **taxonomy node**（`cpo`、`optical_communication`）または mechanism DRIVER `TECHNOLOGY_ADOPTION` ＋ normalized_statement で表す。subject typed_reference に `technology:` を置く運用は Foundation の kind 検証外なので**禁止**（identity core に未検証 namespace を入れない） |
| POLICY_PROGRAM | **B4 では entity にしない** | 同上。DRIVER `REGULATION` / `FISCAL_POLICY` / `POLICY_RATE` ＋ normalized_statement、または taxonomy node。政策主体は `government` / `central_bank` entity で表せる |
| （追加）CENTRAL_BANK / GOVERNMENT | **採用** | Foundation kind あり。政策 driver の主体参照に必要 |
| （追加）PERSON | **不採用** | Foundation kind はあるが Theme subject / exposure に人物を置かない（A1 §18 の企業固有 thesis より更に外）。alias の context term としてのみ使う |
| （追加）TICKER | **entity type にしない** | ticker は company の identifier。source 明示の ticker 参照（NewsItem `EntityReference(kind=ticker)`）は L1 で company entity に**解決**する |

判定: **MVP entity type ＝ company / index / sector / industry / commodity / currency / country / central_bank /
government の 9 種**。すべて Foundation kind の部分集合なので FOUNDATION_CHANGE 不要。

### 5.3 catalog の用途（限定）

normalization、alias resolution、Theme subject の typed_reference 正規化、INFERRED_EXPOSURE の entity id 実在検証、
scope token 値域の供給、監視の grouping。**beneficiary ranking / watchlist / BUY 候補生成は禁止**（A1 不変条件 6、Phase 9）。
catalog は「巨大な全世界 DB」を作らない（historical の方針を継承）。entity の追加は **rule / Theme が参照する必要が生じた
とき**に version を上げて行う。

---

## 6. Entity identity

### 6.1 監査所見（最重要）

A2 §12 / §2.3 #12: `ThemeSubject.typed_reference` と DRIVER / CHANNEL / DOMAIN の `typed_reference` は
**identity core fingerprint に含まれる**。したがって discovery が catalog の entity id を typed_reference として書き込むと、
**entity id の変更 ＝ Theme identity core の変更 ＝ NEW_ROOT_REQUIRED** になる。entity identity の安定性は catalog の
都合ではなく Theme identity の前提条件である。同じ理由で、catalog version 間で alias → entity の解決結果が変わると、
同じ現実の Theme が別 identity core を持ち B3 dedup（exact 一致）が見逃す。

### 6.2 選択

| 案 | 内容 | 長所 | 短所 |
|---|---|---|---|
| S 意味 slug | `company:<slug>`、`index:nikkei225` | 読める。YAML review で誤りに気づける。market catalog の instrument_id と揃う（historical PORT 互換）。fingerprint debug が可能 | rename 時に「slug も直したい」誘惑。kind 跨ぎ・地域跨ぎの衝突（同名別法人） |
| O 不透明 id | `ent_<hash or ulid>` | rename 誘惑がない。衝突しない | 人間 authoring で取り違えやすい。YAML diff が読めない。既存 `index:nikkei225` との結線に別表が要る |

推奨: **S を「誕生時のみ意味を持つ不変 token」として採用**。規則:

1. `entity_id` は作成後 **一切 rename しない**。社名変更・ブランド変更・上場市場変更は `canonical_name` / `identifiers` の
   履歴更新であり id 不変。
2. slug は `<kind>:<ascii_slug>` で、slug は catalog 内で kind を跨いでも一意。同名別法人は `_jp` / `_us` 等の接尾で
   誕生時に区別（後から付けない）。
3. **合併 / 統合**: 旧 entity は `valid_to` を持ち `superseded_by` に新 entity（または存続会社）を指す。新 entity は新 id。
   旧 id を参照する Theme subject は Foundation 規則で自動移行しない（identity core 変更）。人間が SUCCESSOR 宣言または
   新 root で対応する。catalog は「entity が消えた」ことを診断として供給するだけ。
4. **分割 / spin-off**: 親 entity 不変。子は新 id。
5. **ticker 変更 / 上場移管**: identifiers の履歴（valid_from / valid_to 付き）。id 不変。
6. **ticker だけを identity にしない**: ticker は identifiers の 1 scheme。ticker → entity の解決は pinned catalog version
   と evidence 時点での有効性を見る。
7. Phase 9（portfolio / watchlist / 銘柄推奨）の問題には踏み込まない。catalog は corporate action の**記録**までで、
   保有・比率・推奨の概念を持たない。

---

## 7. Historical asset 監査（read only。runtime port なし）

B0 §16 の判定を B1〜B3 完了後の現 architecture で再評価した。4 分類: PORT（規則 / 構造 / 内容を新設計に移す。code の
そのままの port はしない）、REDESIGN（原理を継承し model を作り直す）、REFERENCE_ONLY（読むだけ）、REJECT（B4 で使わない）。

| 資産（phase0 anchor） | 監査所見 | B0 判定 | **B4A 判定** | 変更理由 / 継承するもの |
|---|---|---|---|---|
| `knowledge/enrichment/theme_taxonomy.yaml` | 30 slug、parent 5 件（DAG ではなく tree、深さ ≤ 3）、`related` 74 edge、strong / weak / exclude 信号が同居、file version のみ、published_at / provenance / deprecation なし | REDESIGN | **REDESIGN**（slug 集合は seed として PORT） | slug 30 個は抽象的な産業 / 技術 / macro 語で機密性が低い。`related`・`tank_slugs`・信号語は捨て、§3.1 の field を付けて再発行。信号語は ruleset へ |
| `knowledge/theme_relations/themes.yaml` | label ＝ identity、keyword 部分一致、durable 一覧、tank alias 表 | REJECT | **REJECT** | Foundation TAXONOMY は slug なので label 表は不要。keyword は識別規則であって語彙ではない |
| `knowledge/theme_relations/theme_graph.yaml` | 37 node・無向隣接、型 / 方向 / evidence / 時刻なし | REDESIGN（B5 seed） | **REFERENCE_ONLY（B4 では不使用）** | B4 で隣接を候補拡張に使うと co-occurrence → 因果の経路になる。B5 relation の seed 判断は B5 に委ねる |
| `knowledge/entities/core_entities.yaml` | 80 entity（company 36 ＝ watchlist ＋ 頻出 6、country 18、central_bank 5、government 2、person 3、index 7、commodity 5、currency 4）、`<kind>:<slug>` id、alias 3 段、context_terms、sector 語彙表。valid_from / to・superseded_by・provenance なし。**内容は customer watchlist と結合** | PORT | **PORT（id 体系・alias 3 段・検証規則）／ REDESIGN（lifecycle field 追加）／ 内容は再選定** | 構造は継承。内容は watchlist 由来の company 集合をそのまま port せず、rule / Theme が参照する entity から必要最小で再選定（§19）。person 3 件は不採用（§5.2） |
| `docs/databank/ENTITY_CATALOG_SPEC.md` | 「FALSE LINK IS WORSE THAN MISSED LINK」、alias 安全度、明示 ticker 記法、属性と分類の分離、unknown → review、version 記録 | REFERENCE | **REFERENCE_ONLY**（原則は §15 に採録） | 原則を B4B 契約に抽象化して書く。文書自体は port しない |
| `docs/databank/THEME_TAXONOMY_SPEC.md` | version bump、slug 意味不変、matcher version、再分類は追記 | REFERENCE_ONLY | **REFERENCE_ONLY** | §3.3 の変更管理に反映済み |
| `src/intelligence/enrichment/theme_matcher.py` | 純関数。strong 1 件 or **distinct** weak ≥ 2、exclude 抑制、role ＝ 見出し位置、matched surface を provenance に保持、as-of / version pin なし、出力は分類 tag | REDESIGN | **REDESIGN** | 保守則（distinct 信号数、exclude、matched surface provenance）は §10 / §12 の L2 に継承。出力は tag ではなく rule hit → EVIDENCE_CANDIDATE。role（primary / secondary）は採らない（重要度に見える） |
| `src/intelligence/enrichment/taxonomy.py` | YAML loader ＋ 構造検証（slug 重複、未定義 parent / related、strong 無し禁止）、event taxonomy / horizon | REDESIGN | **REDESIGN** | 検証の規律（重複 / 未定義参照 / 「永遠に発火しない rule」の拒否）を継承。event type / time horizon は Theme 語彙ではないので持ち込まない |
| `src/intelligence/corpus_research/review_queue.py` | kind 別 item、OPEN のみ、auto_approval false、reason ＋ evidence ref、決定 record なし | REDESIGN | **REJECT（B3 で実現済み）** | B3 proposal journal ＋ decision が上位互換。B4 で別の review queue を作らない（parallel authority 禁止） |
| `src/intelligence/corpus_research/lifecycle.py` | 件数 / regime / span 閾値で候補段階を自動昇格 | REFERENCE_ONLY | **REJECT** | B2 lifecycle が閉じており、件数昇格は禁止原則。継承すべき「機械は候補上限まで」は B3 / Foundation の型が既に強制 |
| `src/intelligence/corpus_research/patterns.py` | 共起 tuple の content-addressed id | REFERENCE_ONLY | **REJECT** | 共起 tuple を候補にしない。「version を identity に含める」発想は Foundation / B3 が既に実装 |
| `docs/compass_dna/THEME_DISCOVERY_RULES.md` | 機密（Compass 各号由来の named chain・号 / 日付参照・CONFIRMED 表記）。見出し構造のみ確認: 発火点類型 / 展開手順 / 産業連鎖マップ / 質の担保 / Emerging 検出示唆 / 禁止事項 | REFERENCE_ONLY（機密） | **REFERENCE_ONLY（機密。転記禁止）** | 継承するのは**抽象原則のみ**: (a) 発火点は需要 / 制約 / 技術 / 政策のいずれかとして構造化する、(b) 展開は機構（driver → channel → domain）を経る、(c) 実データ確認と risk を必ず伴う、(d) keyword だけで Theme を言わない。原文・named chain・号 / 頁・企業連鎖は taxonomy / ruleset / docs / test fixture のいずれにも書かない（§19 の guard 対象） |

B0 との差分: `theme_graph.yaml` REDESIGN → B4 では REFERENCE_ONLY（B5 判断）、`review_queue.py` REDESIGN → REJECT
（B3 で実現）、`lifecycle.py` / `patterns.py` REFERENCE_ONLY → REJECT（B2 / Foundation で不要化）、`core_entities.yaml`
PORT → 構造 PORT ＋ 内容再選定（watchlist 結合の切断を「条件」から「必須」へ）。他は同じ。

横断所見（B0 と同じ）: historical 資産は時刻・evidence ref・機構を持たない。B4 が継承するのは規律であり model ではない。
wholesale cherry-pick / merge は行わない。

---

## 8. Discovery 入力 authority（固定案）

B4 discovery は **model instance の列を引数に取る純関数**であり、store を開かない（news / market / ingestion の store は
boundary で禁止。入力の取得は B6 runner の責務）。読んでよい型と禁止する型:

| 区分 | 型 | 判定 | 根拠 / 条件 |
|---|---|---|---|
| 許可 | `sources.model.SourceDocument` | **許可** | F-5 primary 候補。fields: source_id / source_tier / title / locator / published_at ＋ date_quality ＋ published_inferred / retrieved_at / publisher / content_hash / content_fingerprint / revision_of / canonical_locator / summary（本文は持たない）。L2 の走査対象は title / summary のみ |
| 許可 | `databank.news_model.NewsItem`（＋ `NewsDocumentLink`） | **許可** | F-5 primary 候補。`entity_refs`（provenance SOURCE_EXPLICIT / ENTITY_DATABASE。LLM は構築時に拒否済み）が L1 の材料。`theme_refs`（legacy label）は使わない |
| 許可 | `facts.model.Fact` | **許可**（`status == USABLE` のみ） | F-5 primary。fact_type ＋ subject ＋ time が L1 述語の材料。conflict_state が UNKNOWN 以外の矛盾 Fact は診断付き |
| 許可 | `market.model.Observation`（RAW / DERIVED） | **許可**（`series_id` / `entity_id` / `as_of` / `revision_of` / `inputs`） | F-5 primary。**価格変化の閾値を述語にしない**（F-10 / A2 §14）。使ってよいのは「系列 X の観測が存在する」「公表 event が起きた」型の事実述語のみ |
| 許可 | `themes.resolver.ThemeResolution`（read-only） | **許可** | 既存 root への EVIDENCE_CANDIDATE の target 決定と、THEME_CANDIDATE の dedup 入力。resolver_version 互換を検査 |
| 許可 | taxonomy（pinned version） | **許可** | rule routing 語彙 |
| 許可 | entity catalog（pinned version） | **許可** | 正規化 |
| 許可 | B3 proposals / decisions（read-only） | **許可** | 既存 id 除外・decision 相互作用（§15） |
| 条件付き | ACCEPT 済み `EvidenceCandidateProposal` | **THEME_CANDIDATE 組立の evidence_refs 材料としてのみ許可** | 「受理された evidence 候補」は evidence の成立ではない。attachment snapshot として再掲するだけで、資格判定は Foundation |
| 保留 | factual `Statement`（`evidence.model.FactStatement`） | **MVP 不採用** | producer が無く Foundation の ref prefix も未確定（`REF_ID_PREFIX_BY_KIND[STATEMENT] == ""`）。producer gate 後に再評価 |
| 保留 | `NewsClassification`（enrichment 出力） | **MVP 不採用** | RULE_BASED / ENTITY_DATABASE 分類は derived。legacy theme label 次元を Theme 語彙に持ち込まない。必要なら L1 の entity 解決の**補助入力**として B4C で個別認可 |
| 禁止 | `compass.model.CompassDraft`、`reports.model.MorningBrief`、`reports.market_signal.MarketSignal` | **禁止** | F-5「Theme evidence authority ではない」。boundary で package ごと禁止 |
| 禁止 | `predictions.*`（PredictionRecord / CalibrationReport / evaluation） | **禁止** | F-10。B1 / B2 と同じ |
| 禁止 | formal_review / shadow_review / decision の候補 | **禁止** | 別 authority。Theme 入力にしない |
| 禁止 | `context.model.ContextItem` | **禁止**（明示認可まで） | A0.5 §7: DERIVED / INTERPRETIVE。F-5 |
| 禁止 | narrative prose（Brief 本文、要約生成物、LLM 出力） | **禁止** | 事実 record ではない |
| 禁止 | legacy theme score（`NewsScore`、`config.yaml` の themes / macro_themes / theme_relations / theme_learning） | **禁止** | P4 production 語彙。D21 |
| 禁止 | `corpus` / `corpus_research`（Compass corpus 由来 record） | **禁止** | 機密 source。Theme 入力にしない |

B0 §6 / F-5 との整合: 一致（primary 4 種 ＋ resolver ＋ knowledge。derived は不採用）。

---

## 9. Discovery 出力（推奨 pipeline）

```
raw observation（SourceDocument / NewsItem / Fact / Observation）
  ↓ evidence_refs adapter（ref_id / SourceOrigin / 時点 / 日付を決定論的に導出。不明は UNKNOWN / MISSING）
rule 評価（pinned taxonomy / catalog / ruleset、cutoff T）
  ↓ rule hit（述語成立の事実。Theme ではない）
EVIDENCE_CANDIDATE proposal（target root あり／なし）        ← rule.output_type == EVIDENCE_CANDIDATE
  ↓ （別 step。自動連鎖しない）
structured mechanism assembly（rule.mechanism_template ＋ evidence binding）
  ↓
THEME_CANDIDATE proposal（certainty ＝ HYPOTHESIZED_MECHANISM 固定）  ← rule.output_type == THEME_CANDIDATE
  ↓ 同 run で B3 dedup（DEDUP_REVIEW）
B3 human decision（ACCEPT / REJECT / DEFER / NOT_DUPLICATE）
  ↓ optional later
bridge plan（B3 `plan_theme_creation_from_accepted_proposal`）→ 別 gate で Foundation 実行
```

- **EVIDENCE_CANDIDATE → THEME_CANDIDATE の自動 promotion は行わない（推奨 default: NO）。** 理由: (i) promotion は
  機構の主張を伴うが、evidence 候補の受理は「この観測を候補として扱ってよい」以上を意味しない、(ii) B3 は promotion を
  新 proposal（target_proposal_id）として表現する設計であり、その新 proposal も human decision を要する、(iii) 自動 promotion
  は「件数が揃ったら Theme」への滑り台になる。
- 新 THEME_CANDIDATE は常に **別 proposal record**。ACCEPT 済み EVIDENCE_CANDIDATE は evidence_refs の attachment
  snapshot として参照されるだけ。
- rule hit が既存 root にも template にも結びつかない場合は **target 無しの EVIDENCE_CANDIDATE**（未紐付け）を出す。
  蓄積の抑制は識別子ベース（同 ref × 同 role × 同 reason は 1 回）と taxonomy slug による grouping で行い、件数上限は
  設けない（件数で意味を変えない）。
- discovery は proposal を **返す**だけで append しない（純関数）。append は呼び出し側（B6 runner、または test）が
  `ProposalStore` で行う。append 前の既存 id 除外は runner の契約。

---

## 10. Discovery rule model（候補 schema）

| field | 内容 | 制約 |
|---|---|---|
| `rule_id` | `^[a-z][a-z0-9_]{1,63}$`。不変 | rename ＝ 新 rule ＋ 旧 rule deprecation |
| `rule_version` | rule 単位の semver。挙動変更で bump | ruleset 全体にも `ruleset_version` |
| `status` | DRAFT / ACTIVE / DEPRECATED（`since_version` / `deprecated_in_version`） | ACTIVE 化・DEPRECATED 化は人間（§18） |
| `input_kinds` | §8 許可集合の部分集合 | 許可外は load error |
| `taxonomy_refs` | pinned taxonomy の slug（有効 node のみ） | routing / grouping。Theme 語彙ではない |
| `entity_refs` | pinned catalog の entity id（有効 entity のみ） | |
| `predicates` | **構造化述語**の論理式。MVP 語彙: `ENTITY_PRESENT(entity_id)`、`TAXONOMY_SIGNAL(slug, tier ∈ {strong, weak})`、`FACT_TYPE(fact_type, subject_entity?)`、`OBSERVATION_SERIES(series_id)`、`SOURCE_KIND(official_release | publisher_article)`、`NOT(...)`、`ALL(...)`、`ANY(...)`、`MIN_DISTINCT(n, ...)` | 閾値・価格変化・件数・score 述語は語彙に無い |
| `negative_predicates` / `exclusion_terms` | 成立を抑止する述語 / 語 | §15 |
| `mechanism_template` | THEME_CANDIDATE 出力 rule のみ必須: DRIVER / CHANNEL / DOMAIN の category ＋ normalized_statement（OTHER 時）＋ typed_reference binding、CONSEQUENCE の observable_target ＋ expected_change。assertion_provenance ＝ RULE、provenance_ref ＝ `rule:<rule_id>@<rule_version>` | **人間が author し rule ACTIVE 化時に review**。keyword から機構を生成しない |
| `scope_template` | REGION / INDUSTRY / ASSET_CLASS token（entity 属性からの binding 可）＋ PERIOD_FRAME（`SINGLE_PERIOD_FRAMES` 禁止） | |
| `invalidation_template` | ≥ 1 | THEME_CANDIDATE 出力 rule のみ |
| `output_type` | EVIDENCE_CANDIDATE / THEME_CANDIDATE | rule ごとに 1 つ |
| `proposed_role` | SUPPORTS / CONTEXT（既定 CONTEXT）。CONTRADICTS / INVALIDATES は人間 role のみ | 反証 / 無効化を機械が主張しない |
| `provenance` | HUMAN author ref、created version、reason、（任意）由来原則の抽象 ref | Compass 号 / 頁 / named chain を書かない |

原則: **rule は candidate generation rule であり、market rule（`knowledge/compass_dna/market_rules.yaml`）でも Compass DNA
rule でもない。** 別 file・別 loader・別 id 空間（`rule:` 接頭）。`market_rules.yaml` / `market_principles.py` は不変。
「keyword だけで Theme mechanism を確定しない」は (a) 述語語彙に keyword 単独の THEME_CANDIDATE 経路が無い、(b) 機構は
template（人間 authoring）からしか来ない、(c) certainty は最下位の HYPOTHESIZED_MECHANISM 固定、の 3 点で構造化する。

---

## 11. Rule versioning と B3 provenance の接続

| 問い | 判定 |
|---|---|
| proposal から rule_id ＋ rule_version を追跡できる必要があるか | **ある**（決定論 replay・rule 変更の影響範囲・false positive の遡及に必須） |
| 現 B3 model で足りるか | **足りる**: `proposer_ref = "rule:<rule_id>"`、`rule_version = "<rule_version>"`。両者は identity 外（§2）なので rule version bump で proposal が増殖しない。**B3_CHANGE_REQUIRED: NO** |
| taxonomy / catalog / ruleset の version pin はどこに置くか | B3 に構造化 field が無い。選択肢: (a) `rule_version` を固定文法の複合 pin `r=<rule_version>;rs=<ruleset_version>;tx=<taxonomy_version>;ec=<catalog_version>`（≤ 200 字、parse 可能、identity 外）、(b) B3.1 で `ProposalProvenance.knowledge_versions` を **追加 field（既定空）**として拡張、(c) derived run report に run ごとの pin を記録し proposal は `provenance.reason` に `run:<run_id>` を持つ。**推奨: MVP は (a) ＋ (c)**（B3 不変・proposal 単体で pin が読める・run report は補助）。(b) は OPTIONAL_FUTURE（決定 D-B4-7） |
| 同一 proposal を複数 rule が出した場合 | proposal_id は同一。最初に append された provenance が残り、以後は既存 id 除外で append されない。**他 rule の hit は run report（derived）にだけ残る**。これを許容するか、rule ごとに別 proposal にするか（reason に rule_id を含める）は決定 D-B4-7。推奨は許容（提案の identity は「何を」であり、rule 間の収束は dedup を不要にする利点） |
| rule の reason 文字列 | EVIDENCE_CANDIDATE では identity に入るため、**canonical template 固定**（例: `discovery:<output_type>:<role>:<target 種別>`）。version・日時・rule_id・自由文を含めない |

---

## 12. Matching level

| level | 内容 | 決定論 | text 依存 | 主な誤り | B4 MVP |
|---|---|---|---|---|---|
| **L1 exact structured** | source / 辞書が **明示**した構造値の一致: NewsItem `entity_refs`（SOURCE_EXPLICIT / ENTITY_DATABASE）、Fact `subject.subject_id` / `fact_type`、Observation `entity_id` / `series_id`、SourceDocument `source_tier` / `source_id` | 完全 | なし | 上流分類の誤り（provenance で追える） | **採用** |
| **L2 alias / taxonomy normalized** | headline / title / summary の限定 field に対する (a) entity alias（safe は単独可、context は context term 共起必須、ticker は明示記法のみ、NFKC ＋ 単語境界 ＋ 全大文字略語は大文字のみ）、(b) taxonomy signal（strong 1 件 or **distinct** weak ≥ 2、exclude 共起で抑止）。matched surface と field を hit provenance に保持 | 完全（同 text → 同 hit） | あり | 一般語衝突・多義語・比喩 | **採用（限定）**: 走査 field は title / headline / summary のみ。本文なし。L2 単独の hit は THEME_CANDIDATE を出さない（EVIDENCE_CANDIDATE まで） |
| **L3 semantic / LLM-assisted** | 埋め込み類似・LLM 抽出 | なし | あり | 幻覚・因果断定 | **不採用（B7 に延期）** |

embedding / fuzzy score / n-gram 類似（記事 `identity_signals` を含む）は MVP に入れない（A2 §12.3）。L2 の「2 信号」は
述語の充足であって score ではない（3 信号でも同じ hit）。

---

## 13. Mechanism assembly

| 案 | 内容 | B4 MVP |
|---|---|---|
| A rule template が 4 component を全部供給 | 人間 authoring の template を hit の binding（entity / scope）で具体化 | **採用** |
| B evidence から一部を埋める | subject typed_reference、scope REGION / INDUSTRY token（catalog 属性）、consequence の observable_target（series_id 等）を hit した record から binding | **採用（binding のみ）**。category や statement を evidence から生成しない |
| C 複数 EvidenceCandidate の組み合わせ | 同一 rule・同一 template の複数 hit を 1 つの THEME_CANDIDATE の evidence_refs に集約 | **限定採用**（同 rule 内の集約のみ）。**rule 跨ぎ・entity 共起からの機構合成は不採用**（co-occurrence → CAUSES 禁止） |
| D HUMAN 補完 | 人間が THEME_CANDIDATE を直接 author（proposer HUMAN） | B3 で既に可能。B4 runtime 不要 |
| E LLM proposal 補完 | LLM_PROPOSAL | **不採用（B7）** |

規則: (1) template の component は assertion_provenance RULE ＋ provenance_ref に rule id@version、(2) certainty_class は
HYPOTHESIZED_MECHANISM 固定（EVIDENCE_SUPPORTED / EXPLICIT_SOURCE_CAUSAL_CLAIM は人間 / SOURCE_CLAIM のみ）、
(3) 語彙に無い category は OTHER ＋ normalized_statement（FC-1 は B4 では発生させない。§23）、(4) evidence_refs の role は
proposed_role（SUPPORTS / CONTEXT）、role_provenance RULE、(5) 資格（SOURCE / TEMPORAL DIVERSITY）を assembly が
主張しない。

---

## 14. EvidenceCandidate bridge

| 案 | 内容 | authority 分離 | auditability | B4 への影響 |
|---|---|---|---|---|
| A B4 に `EvidenceAttachmentPlan` 純 helper | ACCEPT 済み EVIDENCE_CANDIDATE（target_root_id あり）から、Foundation `revision.attach_evidence` 用の plan（root_id、対象 observation_id at T、attachment、provenance に proposal / decision id）を作る。実行なし | 良（B3 bridge と同型） | 良 | B4 の scope が広がる。target observation の PIT 解決と revision 意味論（新 observation を生む）の理解が必要 |
| **B** discovery は EVIDENCE_CANDIDATE 生成まで。attachment bridge は別 gate | B4 は入力→提案に集中 | 良 | 良（proposal に target と decision が残る） | 最小 |
| C EvidenceCandidate を使わず THEME_CANDIDATE の evidence_refs に直接 | 既存 root への付与候補が表現できない（THEME_CANDIDATE は新 root 候補） | 悪（既存 root への evidence 提案が journal に残らない） | 悪（却下履歴が消える） | — |

**推奨: B。** bridge は独立 sub-gate **B4E（または B3.1）**として `plan_evidence_attachment_from_accepted_proposal`
（純関数、実行なし、attach 先 observation は `resolve(root, T)` の observation、`attached_at = T`、provenance に proposal /
decision id）を実装する。B4D（discovery E2E）は bridge 無しでも検証できる。C は不採用。

---

## 15. False positive containment（設計必須項目）

| 項目 | 設計 |
|---|---|
| minimum structured predicates | EVIDENCE_CANDIDATE: L1 述語 1 件 or strong signal 1 件 or distinct weak ≥ 2。THEME_CANDIDATE: 上記に加え **L1 述語 ≥ 1 を必須**（text だけで Theme 候補を出さない） |
| negative predicates | rule 単位の `NOT(...)`。成立時は hit 自体を出さず run report に `SUPPRESSED_BY_NEGATIVE` |
| exclusion terms | taxonomy signal の exclude 共起（historical 継承）。`SUPPRESSED_BY_EXCLUDE` |
| entity ambiguity | context 必須 alias で共起無し → link しない（`AMBIGUOUS_ENTITY` 診断）。推測しない。未知 ticker 記法 → `UNKNOWN_IDENTIFIER` 診断（catalog 拡張候補として人間へ） |
| alias collision | catalog load 時に aliases_safe の全体一意性を検証。衝突 ＝ load error（fail closed）。context alias は複数 entity で共有可だが context term が排他的であることを検証 |
| duplicate source origin | 入力ごとに A2 §8 の規則で `SourceOrigin` を導出（article_id、`NewsDocumentLink` SYNDICATED / UPDATE、`revision_of`、content_hash / content_fingerprint、`IdentityDecisionKind` SYNDICATED / REVISION、`RevisionRole`）。同一 origin の複数 record は **1 つの ref**（NewsItem を代表、member document は lineage_refs）に収束 |
| same article across NewsItem / Statement | Statement は MVP 対象外。NewsItem と member SourceDocument の二重 hit は上記で収束 |
| rule overlap | 同一入力に複数 rule が成立: 同 target・同 role なら同 proposal_id（収束）。異 target なら別 proposal（正当）。run report に `MULTI_RULE_HIT` を記録 |
| taxonomy overlap | multi-label 許容、伝播なし。同 root に複数 slug は 1 metadata record |
| repeated proposal suppression | **identity ベース**: 既存 proposal_id は append しない（B3 store の CONFLICT は最終防衛線）。run report に `SUPPRESSED_EXISTING` |
| accepted / rejected / deferred の相互作用 | EVIDENCE_CANDIDATE: 同 id は状態に関わらず再 append しない（REJECTED は永続的に再提案されない。identity が変わる ＝ 別提案）。THEME_CANDIDATE: 同 fingerprint は同 id。近傍 variant は新 proposal ＋ B3 dedup（ただし REJECTED 候補は counterpart から除外されるため、**却下済み候補の variant は dedup に現れない**。run report に derived の `IDENTITY_CORE_MATCHES_REJECTED` を情報として出す。B3 変更はしない） |
| historical NOT_DUPLICATE | B3 の suppression がそのまま効く（同 basis・同 version）。discovery 側は関与しない |
| 件数 score による自動 Theme 化 | **禁止**。hit 件数・origin 数・日付数は output_type・certainty・role のいずれも変えない。run report の記述量に留める |

---

## 16. Source independence

- Foundation A2 §8 の source independence（lineage の終端 ＝ 元公表主体と元 record）と discovery の matching は別概念。
  **rule hit 数 ≠ independent source origin 数**（同一記事の転載 5 件 ＝ hit 5・origin 1）。
- discovery の evidence_refs adapter は入力ごとに `SourceOrigin` を **保守的に**導出する: NewsItem → `PUBLISHER_ARTICLE` /
  `article:<article_id>`、SourceDocument（記事 member）→ 同上、公式 release 相当 → `OFFICIAL_RELEASE` /
  `release:<source_id>/<doc_id>`、Observation RAW → `MARKET_SERIES` / `series:<source_id>/<series_id>`、Fact / DERIVED →
  `DERIVED` ＋ lineage_refs。判定不能は `UNKNOWN`（Foundation は独立に数えない）。
- proposal 生成時、同一 origin の複数 record は 1 ref に収束（§15）。ただし **独立性の判定は行わない**: 資格判定
  （SOURCE / TEMPORAL DIVERSITY）は human ACCEPT 後に Foundation `evaluate_qualification` が行う。
- run report は「distinct origin key の数」を記述量として出してよいが、proposal の identity・certainty・role に反映しない。

---

## 17. PIT / time

| 時間 | 必要か | 用途 |
|---|---|---|
| knowledge `version`（taxonomy / catalog / ruleset）＋ `published_at` | **必要** | version 単位の有効性（`since_version` / `deprecated_in_version`）。`as_of(T)` は `published_at ≤ T` の最新 version へ解決 |
| entity `valid_from` / `valid_to`（世界時間） | **必要（任意値）** | evidence 時点に存在しない entity への binding を診断 |
| discovery cutoff `T`（caller 注入 ＝ proposal `created_at`） | **必要** | 入力の knowability（`retrieved_at` / `created_at` ≤ T。Foundation の knowledge 軸と同じ）と pin 解決 |
| 入力 record の `published_at` / `as_of` / `trading_date` | **必要** | evidence_time / evidence_date（Foundation の evidence 時間軸） |
| `recorded_at` / `known_at` | proposal は `created_at` が兼ねる。knowledge は `published_at` | 別 field は不要 |

規則: (1) run は `(T, taxonomy_version, catalog_version, ruleset_version)` を**明示引数**に取る。既定値・latest 解決は
API に存在しない。(2) 未来の version・alias・rule は過去 T の run に現れない（version の `published_at > T` は解決不可で
fail closed）。(3) proposal は不変で pin を持つので、後の version 公開が過去 proposal を変えない。(4) 決定論 replay:
同じ入力列・同じ pin・同じ T → 同じ proposal id 集合（順序・process 非依存。A4d / B1 の test 流儀）。(5) B3 dedup の
`dedup_model_version` と同様、evidence_refs adapter にも `adapter_version` を置き、pin と併記する。

---

## 18. Governance 境界

| 人間承認が必要 | 自動化可能 |
|---|---|
| taxonomy version の公開（PR review ＋ `published_at` ＋ 承認者 ref） | 決定論的 rule 評価 |
| entity catalog version の公開 | exact alias 正規化（safe alias、明示 ticker、context 共起） |
| rule の ACTIVE 化 / DEPRECATED 化（version 内の status） | exact dedup 提案（B3） |
| 曖昧 alias の解決（`AMBIGUOUS_ENTITY` / `UNKNOWN_IDENTIFIER` を次 version の catalog 編集で解消。自動 link しない） | proposal 生成（RULE proposer の EVIDENCE_CANDIDATE / THEME_CANDIDATE）と append |
| THEME_CANDIDATE の ACCEPT（B3） | run report（derived）の生成 |
| evidence role の訂正（Foundation governance） | 既存 id 除外・suppression |
| root の taxonomy metadata 付与 / 再分類 | — |

version 公開の記録先: knowledge file の `history`（version、published_at、approver ref、reason）。B3 journal に version
decision 型を追加しない（proposal ではない）。

---

## 19. 機密性

- historical 資産のうち `THEME_DISCOVERY_RULES.md` は機密（Compass 各号由来）。`theme_taxonomy.yaml` の信号語の一部と
  `theme_graph.yaml` も Compass DNA / 旧 config 由来。`core_entities.yaml` の company 集合は **customer watchlist 由来**
  （config.yaml watchlist）で、集合そのものが顧客情報を示唆する。
- 新 taxonomy / catalog / ruleset に持ち込んでよいのは **抽象化された slug・entity id・構造化述語・category** のみ。
  原文・named chain・号 / 日付 / 頁参照・「CONFIRMED」等の Compass 由来表記・企業連鎖の記述は **禁止**。
- ruleset の trigger 語は一般語（産業 / 技術 / 政策の一般名詞）に限る。特定号の見出し表現を写さない。
- guard（B4B / B4C で test 化）: knowledge/theme_intelligence/*.yaml と docs に対し、Compass 参照 token（`羅針盤`、
  `Compass`、`CONFIRMED`）、号 / 日付参照 pattern、PDF file 名 pattern、drive / UNC path、credential 形状、
  `watchlist` 語の不在を検査。既存 hygiene guard（`_check_prohibited_content` 相当）と同じ思想。
- customer / public bundle への非混入: production closure は `theme_intelligence` を含まない（既存 test）。Pages manifest は
  `knowledge` path 断片を公開 tree で禁止（既存）。`knowledge/theme_intelligence/` を workflow が copy しないことを B4B で
  test に追加。

---

## 20. Import / package 境界（B4 runtime 候補）

```
theme_intelligence/
    taxonomy_model.py      TaxonomyNode / Taxonomy（frozen dataclass、version 集合の有効性、PIT 解決の純関数）
    taxonomy.py            YAML loader ＋ 構造検証 ＋ content_digest（IO module）
    entity_model.py        EntityRecord / Identifier / alias 構造（純）
    entity_catalog.py      YAML loader ＋ alias index ＋ 解決（safe / context / 明示 ticker）（loader は IO、解決は純）
    discovery_model.py     rule / predicate / hit / diagnostic / RunParams / DiscoveryRunReport（純）
    discovery_rules.py     ruleset YAML loader ＋ 検証（IO module）
    evidence_refs.py       入力 record → (ref_id, SourceOrigin, evidence_time, basis, quality, date) adapter（純）
    discovery.py           rule 評価 → proposal 生成（純。store を開かない、append しない、現在時刻を呼ばない）
```

依存方向（下位 → 上位）:

```
facts.model / market.model / sources.model / databank.news_model（model のみ）
      ↓
evidence_refs ── themes.model（SourceOrigin / EvidenceAttachment 型）
      ↓
taxonomy / entity（knowledge 正規化）
      ↓
discovery ── themes.resolver（ThemeResolution 型、read）
      ↓
B3 proposal_model（出力型）／ proposal_resolution（decision 状態の読み取り）
```

| 規則 | 内容 |
|---|---|
| B4 → B3 | **本監査は B4 が B3 の `proposal_model` / `proposal_resolution` を import することを承認する**（唯一の出力面。他に方法が無い）。`proposal_store` は純 module から import しない（append は runner） |
| B4 → Foundation | `themes.model`（型）、`themes.fingerprint`（proposal_model 経由）、`themes.resolver`（型）。`themes.store` / `operations` / `revision` は禁止 |
| B4 → 入力 model | `facts.model`、`market.model`、`sources.model`、`databank.news_model` の **model module のみ**（A0.5 §7 の許可 list と一致）。これらの module 自体が production closure を引き込まないことを B4B の closure test で検証 |
| B4 → 第三者 | `yaml` は loader 3 module に限定 |
| 逆方向 | Foundation / B1 / B2 / B3 は B4 module を import しない（既存 boundary test に B4 module 名を追加して検証） |
| production | `theme_intelligence` 全体が production closure 外（既存 test）。`EXCLUDED_PACKAGES` は編集しない |
| 禁止 | compass / reports / predictions / internals / context / corpus / corpus_research / enrichment / ingestion / normalization / market.store / network / 現在時刻 |

boundary test の拡張は **B4B で additive に**行う（本 gate では tests 不変）。

---

## 21. Sub-gate 提案

| gate | 内容 | 成果物 | 依存 |
|---|---|---|---|
| **B4A**（本書） | architecture audit | 本 doc | — |
| **B4B** taxonomy ＋ entity contract & implementation | schema 凍結、`knowledge/theme_intelligence/theme_taxonomy.yaml` / `entity_catalog.yaml` 初版（slug seed 30、entity は必要最小）、loader / validator / PIT / alias 解決、hygiene guard、boundary 拡張 | taxonomy_model / taxonomy / entity_model / entity_catalog、tests、契約 doc | 監督者決定 D-B4-1〜3、9、10 |
| **B4C** deterministic discovery contract & implementation | rule model / predicate 語彙 / evidence_refs adapter / discovery 純関数 / run report、ruleset 初版（少数の template rule）、決定論 test | discovery_model / discovery_rules / evidence_refs / discovery、tests、契約 doc | B4B、決定 D-B4-4〜8 |
| **B4D** discovery E2E ＋ false-positive gate | A4d world ＋ 合成 NewsItem / SourceDocument / Fact / Observation fixture で §15 / §22 の adversarial matrix を通す。B3 dedup / decision との相互作用 | tests のみ（runtime 修正は blocker 手続き） | B4C |
| **B4E**（または B3.1） EvidenceAttachmentPlan bridge | §14 案 B の pure helper | proposal_bridge への additive 追加または新 module、tests | B3 凍結解除の監督者判断 |
| （B6） | runner: 入力取得、append、report 出力、scheduling | 別 phase | B4D |

B4 を一括実装しない。B4E は B4D と独立に順序付け可能。

---

## 22. 将来必要な test（列挙）

Taxonomy: version / PIT（`taxonomy_at` / `taxonomy_as_of`、未来 version 不可視）、slug rename ＝ 新 slug ＋ deprecation、
deprecation 後の値検証失敗、multi-parent DAG と循環拒否、unknown slug の fail closed、future leakage（T より後の
published_at の version を解決しない）、content_digest の一致、公開済み version の改変検知、latest API の不在、
Foundation metadata 値検証（set 値・pin 付き）が Foundation を書かない。

Entity: alias collision の load error、context alias の共起要件、rename で id 不変、identifier 変更（ticker 移管）で id
不変、corporate action（merge → valid_to ＋ superseded_by、split → 新 id）、PIT（valid_to 前後で binding 診断）、
ambiguity fail closed（推測 link なし）、明示 ticker 記法のみ、未知識別子の診断、entity type が Foundation kind の部分集合
（`ThemeEntityKind` との鏡像 test）。

Discovery: exact positive（L1）、exact negative（述語不成立で hit なし）、ambiguous entity（hit なし ＋ 診断）、duplicate
source（同一記事の転載が 1 ref に収束）、overlapping rule（同 proposal_id に収束 / 異 target で別）、repeated proposal
（既存 id 除外、CONFLICT に至らない）、rejected / deferred history（再 append なし、REJECTED variant の情報化）、
no automatic Theme（RootRecord / ThemeObservation / governance が一切書かれない: Foundation authority bytes 不変）、
no causality from co-occurrence（entity 共起だけの入力から THEME_CANDIDATE が出ない）、no score / rank / fuzzy（source
token guard ＋ 出力に数値 score 不在）、rule version provenance（proposer_ref / rule_version / pin の形式）、deterministic
replay（shuffle / 再読込 / 別 process）、future rule no leakage（ruleset version の published_at > T で解決不可）、certainty
固定（HYPOTHESIZED_MECHANISM 以外を rule が出せない）、role 制限（CONTRADICTS / INVALIDATES を rule が出せない）、
STATEMENT 不採用、価格閾値述語の不在、入力 store 非 open、現在時刻非依存、hygiene（Compass token / path / secret /
watchlist 語の不在）、production closure 排除、Foundation / B1 / B2 / B3 からの非参照。

---

## 23. Foundation / B1 / B2 / B3 変更要否

| 対象 | 判定 | 理由 |
|---|---|---|
| **FOUNDATION_CHANGE_REQUIRED** | **NO** | entity type は `ThemeEntityKind` の部分集合で足りる（TECHNOLOGY / POLICY_PROGRAM は taxonomy / mechanism で表す）。METADATA TAXONOMY は set 値で複数 slug 可。typed_reference / metadata の意味論は現行のまま。FC-1（mechanism 語彙拡張 ＋ version 複数受理）は B4 MVP では OTHER ＋ normalized_statement で回避 → **OPTIONAL_FUTURE**（B4D で OTHER 依存度を計測してから再評価） |
| **B1_CHANGE_REQUIRED** | **NO** | discovery は change set を入力にも出力にもしない |
| **B2_CHANGE_REQUIRED** | **NO** | lifecycle は discovery と無関係。B6 で「dedup / 提案あり」を要 review 一覧に出すのは runner 側 |
| **B3_CHANGE_REQUIRED** | **NO（MVP）／ OPTIONAL_FUTURE（B3.1）** | rule_id / rule_version は proposer_ref / rule_version で表現可。knowledge pin は複合 pin ＋ run report で表現可。OPTIONAL_FUTURE の候補: (1) `ProposalProvenance.knowledge_versions`（追加 field、既定空）、(2) `METADATA_CANDIDATE` proposal 型（rule による root 再分類提案が必要になった場合）、(3) EvidenceAttachmentPlan bridge（§14。B4E として実装なら B3 file への additive 追加か新 module かは監督者判断）、(4) dedup counterpart に REJECTED 候補を情報として含める option。いずれも本 gate では変更しない |
| tests / boundary | B4B で additive 拡張（本 gate では不変） | |

---

## 24. Risks / limitations

| # | risk | 緩和 |
|---|---|---|
| R1 identity core への entity id 混入 | catalog の id 変更が NEW_ROOT を誘発 | §6 の不変規則。catalog loader が id の rename を履歴で検知して fail closed |
| R2 L2 text matching の誤検出 | 一般語衝突・比喩 | L2 単独では THEME_CANDIDATE を出さない。context 必須 alias。exclude。走査 field 限定 |
| R3 template 機構の空洞化 | 人間 authoring の template が「keyword に機構の見た目を付ける」道具になる | rule ACTIVE 化を人間承認にする。certainty 最下位固定。THEME_CANDIDATE に L1 述語必須。B4D で「共起だけの入力から候補が出ない」test |
| R4 却下済み候補の variant 再提案 | B3 dedup が REJECTED counterpart を除外 | run report に derived 情報。B3.1 option |
| R5 未紐付け EVIDENCE_CANDIDATE の蓄積 | 要 review 一覧が膨らむ | identity 収束 ＋ taxonomy grouping。件数上限は設けない（件数で意味を変えない）ので運用側の view が要る（B6） |
| R6 knowledge pin の非構造化 | 複合 pin 文字列の parse 依存 | 固定文法 ＋ parser test。B3.1 で構造化 field へ |
| R7 機密混入 | ruleset の trigger 語・taxonomy description に Compass 由来表現 | §19 の内容方針 ＋ guard test ＋ review |
| R8 YAML 依存 | loader が boundary の例外になる | loader 3 module に限定。閉包 test |
| R9 upstream model の変化 | facts / market / sources / databank の model schema 変更 | adapter に `adapter_version`、schema_version 検査、不明 field は診断 |
| R10 Statement 経路の不在 | 文単位の主張が使えない | MVP は文書 / record 単位。producer gate 後に再評価 |

---

## 25. Blockers

なし。

---

## 26. 監督者決定事項（B4B / B4C 前。最大 10 件）

| # | 決定 | 選択肢 | 推奨 |
|---|---|---|---|
| D-B4-1 | taxonomy / entity / ruleset の置き場所 | A YAML のみ／B YAML ＋ versioned code model／C data_root journal。ruleset を repo に置くか private knowledge root に置くか | **B、`knowledge/theme_intelligence/`。ruleset も repo（内容方針 ＋ guard 付き）** |
| D-B4-2 | entity identity と type 集合 | `<kind>:<slug>` 不変 token／不透明 id。type 9 種（Foundation 部分集合）／TECHNOLOGY ・POLICY_PROGRAM を entity に含める（Foundation 変更） | **`<kind>:<slug>` 不変、9 種、TECHNOLOGY / POLICY_PROGRAM は taxonomy / mechanism** |
| D-B4-3 | taxonomy 構造 | tree／DAG。related edge の有無。伝播の有無 | **DAG multi-parent、related なし、伝播なし** |
| D-B4-4 | discovery 入力 authority | §8 の許可 / 保留 / 禁止表の確定。NewsClassification の補助入力認可 | **§8 のとおり。NewsClassification は不採用** |
| D-B4-5 | matching level | L1 のみ／L1 ＋ L2／L3 含む | **L1 ＋ L2（限定）。L3 は B7** |
| D-B4-6 | 自動 promotion と mechanism assembly | promotion NO／YES。assembly A / B / C / D / E の範囲 | **NO。A ＋ B（binding）＋ C（同 rule 内集約のみ）** |
| D-B4-7 | rule 出力 proposal の identity と pin 表現 | reason を rule 非依存 template にして複数 rule を同 id に収束させる／rule ごとに別 proposal。pin は複合文字列 ＋ run report／B3.1 構造化 field | **収束させる。複合 pin ＋ run report。B3.1 は後日** |
| D-B4-8 | EvidenceCandidate bridge | A（B4 内）／B（別 gate B4E）／C（不使用） | **B（B4E）** |
| D-B4-9 | PIT model | version 単位有効性 ＋ published_at による as-of／時刻単位の record 有効性 | **version 単位 ＋ published_at。既定 latest なし** |
| D-B4-10 | historical port の範囲 | taxonomy slug 30 の seed 採用／entity 内容の再選定範囲（watchlist 由来 company の扱い、person 不採用）／信号語の再 authoring | **slug seed 採用、entity は rule / Theme 参照分のみ、person 不採用、信号語は再 authoring（copy しない）** |

---

## 27. 次 gate

**P6-B4B Taxonomy ＋ Entity contract & implementation**（監督者決定 D-B4-1〜3、9、10 の受領後）。B4B は knowledge file
初版・loader / validator / PIT・alias 解決・hygiene guard・boundary の additive 拡張までとし、discovery rule は B4C。

判定: **A. P6_B4A_THEME_TAXONOMY_ENTITY_DISCOVERY_AUDIT_COMPLETE / READY_FOR_SUPERVISOR_B4_DECISIONS**。
B4B には進まない。
