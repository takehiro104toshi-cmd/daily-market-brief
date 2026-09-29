# PHASE 6 / P6-B7A — LLM PROPOSAL LAYER ARCHITECTURE & CONTRACT AUDIT

DESIGN / AUDIT ONLY。runtime・test・knowledge・config・workflow・scripts は変更していない
（B6 最終 freeze `7a8f8a4` 以降、docs と CHANGELOG 以外の diff 0）。LLM / network call は行っていない。API key は要求していない。

基本原則（監督指示）:

```
LLM PROPOSES.
DETERMINISTIC CODE VALIDATES.
HUMAN DECIDES.
AUTHORITY LAYER RECORDS.
```

本書の field 名・module 名・file 名はすべて **候補**であり、確定は監督者の判断による（§31 の決定表）。

---

## 1. Executive summary

- B7 は **新しい proposal authority を作らない**。LLM の出力は、検証を通ったものだけが既存の B3 proposal authority
  （EVIDENCE_CANDIDATE / THEME_CANDIDATE）と B5C relation proposal authority（RELATION_CANDIDATE）へ、
  既存 store API と既存の人間 decision 経路で渡る。B3 / B5C はすでに LLM 提案者を予約している
  （`ProposerClass.LLM_PROPOSAL`、`RelationProposerClass.LLM`）。
- 既存 authority の手前に、**authority ではない B7 層**を置く: PIT 入力 manifest → 生成 adapter（provider 境界）→
  厳格 parser → 決定論 validator → 提案 plan（append 候補）。生成の記録は proposal authority と分けた
  **生成 journal（監査 record。Theme authority ではない）**に置く案を推す（§18 Option C）。
- 監査で見つかった既存 interface の性質（いずれも prior phase の変更を要しない。B7 側の設計で吸収できる）:
  1. B3 / B5C の proposal identity は provenance と created_at を除いた内容 id。**同内容・別 provenance の 2 件目は
     CONFLICT**（B5 closeout §10.1 の check-then-reuse 契約）。B7 は append 前に既存 id を確認して再利用する。
  2. identity に自由文が入る field がある（EVIDENCE_CANDIDATE の `reason`、RELATION_CANDIDATE の `rationale`）。
     LLM の言い回しの揺れが identity の揺れになるため、B7 は **identity に入る文は決定論 template で作り**、
     LLM の説明文は identity 外の監査 field（`note` / `provenance.note`）へ置く（B4 discovery の `evidence_reason` と同じ先例）。
  3. THEME_CANDIDATE は attachment の `role_provenance` と機構 component の主張 provenance を自由に持てる。
     B7 validator はこれらを **`LLM_PROPOSAL` に固定**し、SOURCE_CLAIM / 出典因果主張 / EVIDENCE_SUPPORTED_MECHANISM を拒否する
     （そうしないと人間 ACCEPT 後の plan に LLM の主張が HUMAN / RULE として流れ込む）。
  4. 既存 guard は module 名の列挙で守られている。B7 module は guard へ明示登録しないと検査の外に出る。
- **B7 の生成は PIT 再現的ではない**（LLM は cutoff 後の世界知識を持ちうる）。入力は PIT で閉じ、出典は manifest に
  限定するが、LLM 出力を過去時点の評価・backtest に使ってはならない。
- 判定案: **A. P6_B7A_ARCHITECTURE_VALIDATED / READY_FOR_P6_B7B**（blocker なし。監督者の決定事項 12 件を §31 に列挙）。

## 2. 既存 interface の監査

### 2.1 B3（proposal authority）

| 項目 | 実装（凍結） | B7 への含意 |
|---|---|---|
| proposal model | `ThemeCandidateProposal` / `EvidenceCandidateProposal` / `DedupReviewProposal`（`proposal_model.py`）。id は `thprop_` 内容 id | B7 は新 type を作らず、この 2 型（THEME / EVIDENCE）を使う |
| identity | provenance・created_at を除く。THEME は subject / mechanism / scope / limitations / invalidation / inferred links / evidence attachment（attached_at 除く）。EVIDENCE は ref・origin・時刻・role・target・**`reason`** | 自由文 `reason` を template 化（§15）。`note` / `locator` は identity 外 |
| provenance | `ProposalProvenance(proposer_class ∈ {RULE, HUMAN, LLM_PROPOSAL}, proposer_ref ≤200, rule_version, reason ≤500)`。`LLM_PROPOSAL` は予約済み | model metadata を provenance に詰めない。`proposer_ref` ＝ 生成 record id、`rule_version` ＝ prompt contract version（§17） |
| store | `<data_root>/theme_intelligence/proposals.jsonl` ＋ `proposal_decisions.jsonl`。同 id 同 bytes ＝ 冪等、同 id 異 bytes ＝ CONFLICT、破損は fail closed | B7 は **check-then-reuse**（§15.3）。store API は変更しない |
| human decision | `ProposalDecision`（ACCEPT / REJECT / DEFER / NOT_DUPLICATE、actor は HUMAN のみ） | B7 は decision を作らない・提案しない |
| dedup review | `DedupReviewProposal` は **RULE 提案者に固定**（`dedup reviews are RULE proposals`）。自動 class は exact fingerprint 一致のみ | LLM は DEDUP_REVIEW を作れない（§23） |
| accepted bridge | `plan_theme_creation_from_accepted_proposal`: ACCEPT 済み THEME だけを不変 plan に変換。**attachment は provenance ごと複写**（attached_at のみ置換） | LLM 由来 attachment の role provenance を `LLM_PROPOSAL` に固定しないと plan に誤った provenance が入る（§10） |

### 2.2 B4（deterministic discovery / evidence bridge / knowledge）

| 項目 | 実装（凍結） | B7 への含意 |
|---|---|---|
| discovery 出力 | `discover()` は B3 proposal の **append 候補**を返すだけ（書かない）。既存 id は返さず（suppression）、新 THEME 候補に B3 exact dedup detector を走らせる | B7 bridge は同じ形（append 候補・suppression・exact dedup）を踏襲する |
| EvidenceCandidate | discovery は role を SUPPORTS / CONTEXT に限定。`reason` は rule を跨いで収束する template（`evidence_reason`） | B7 も template で収束させる |
| ThemeCandidate | certainty は `HYPOTHESIZED_MECHANISM` に固定（D-B4-6）。L1 hit 必須（L2 だけでは作らない） | B7 の THEME も certainty 固定。L3（意味的 matching）は B4 closeout で B7 に繰り延べ済み（B4 #14） |
| EvidenceAttachmentPlan | B4E は ACCEPT 済み EVIDENCE の **SUPPORTS / CONTEXT のみ**を plan 化。`consequence_ref` は plan 作成時に **呼び出し側（人間）が渡す**。CONTRADICTS / INVALIDATES は橋渡ししない | 反証・無効化候補（役割 D）は提案として保存できるが Foundation への橋は無い（§4、B7-DEF-2） |
| taxonomy / entity | versioned knowledge。`TaxonomySnapshot` / `EntityCatalogSnapshot` は version を pin、`published_at > cutoff` は `FUTURE_KNOWLEDGE` | B7 validator は pinned snapshot で slug / entity を解決する。LLM は語彙を増やせない |
| 入力 model | 許可入力は `SourceDocument` / `NewsItem` / `Fact`（USABLE）/ `Observation`。本文は走査せず、限定 text 面（見出し・要約・title）のみ | B7 の既定入力も同じ限定面（§21） |

### 2.3 B5（relation authority / relation proposal）

| 項目 | 実装（凍結） | B7 への含意 |
|---|---|---|
| relation proposal | `RelationProposal`（RELATION_CANDIDATE の 1 型）。提案者 class HUMAN / SOURCE / RULE / **LLM**（authority の主張 class ではない） | B7 は proposer `LLM` で提案する |
| identity | 11 key（端点・type・change kind・前 assertion・**出典帰属**・**`rationale`**・evidence refs）。provenance / created_at を除く | `rationale` を template 化し、LLM の説明は `provenance.note`（≤240、identity 外）へ |
| SourceClaimVerification | SOURCE_ASSERTED で ACCEPT するには人間の確認 record が必須（B5C-R1）。「出典がそう主張した」ことの確認であり、真実性の確認ではない | LLM は確認 record を作れない。LLM が出典帰属を書いても人間確認までは意味を持たない |
| human decision | ACCEPT は最終 assertion class（HUMAN_ASSERTED / SOURCE_ASSERTED）を明示。自動 ACCEPT なし | 変更なし |
| RelationAssertionPlan / RR-3 | plan は値 object。**実行 gate は plan object を信頼せず、authoritative record から再導出または完全再検証する**（POLICY LOCKED）。実行 gate は未実装 | B7 は実行 gate を作らない。B7 の提案も RR-3 の下にある |
| 収束（D3〜D5） | provenance だけ異なる提案は同 id に収束し 2 件目は CONFLICT。`append_or_reuse` API と co-discovery journal は繰延 | B7 は check-then-reuse を bridge で行い、共同発見の事実は B7 の生成 journal に残す（B5 を変えない） |

### 2.4 B7 は新しい proposal authority を作るべきか（比較）

| 案 | 内容 | 評価 |
|---|---|---|
| P1 並行 authority | B7 専用の LLM proposal journal と LLM 専用 decision | **不採用**。同じ候補が 2 つの authority に並び、人間 decision が分裂する。B3 / B5C の human gate・dedup・bridge を再実装することになる |
| P2 既存 authority を直接再利用 | LLM 出力を即 B3 / B5C へ append | **不採用**。検証前の生成物が authority に入り、失敗・棄権・却下された生成が監査できない |
| **P3 既存 authority ＋ authority 手前の B7 層** | 生成・検証・棄権・却下は B7 層（非 authority）で完結し、検証済み候補だけを既存 store へ check-then-reuse で渡す | **推奨**。人間 decision・dedup・bridge・RR-3 はすべて既存のまま |

## 3. authority ceiling

| B7 の出力が到達してよい | 到達してはならない（構造的に経路が無いこと） |
|---|---|
| B7 生成 journal の record（監査） | ThemeRoot 作成・ThemeObservation append・EvidenceAttachment append |
| 検証済みの提案 plan（append 候補、ephemeral） | RelationAssertion append・relation governance event・Theme governance event |
| 明示的な submit 後の B3 / B5C proposal record（L1） | ACCEPT / REJECT / DEFER / NOT_DUPLICATE の decision |
| | production interpretive rule（Compass DNA / MorningBrief / MarketSignal 相当） |
| | 売買・推奨・価格・順位・score |

- L1（proposal candidate）が上限。L1 → L2 は既存の人間 governance（B3 decision → bridge → Foundation operation）だけ。
- L3（production interpretive authority）は B7 から到達不能（Phase 6 では誰にも到達不能。semantics contract §15）。
- 保証の方法: B7 module は Foundation の write API・B5B append API・decision build API・B6 review append API を
  import しない（B7B で guard 化）。submit 経路が呼ぶのは `append_proposal`（B3 / B5C）だけ。

## 4. LLM role taxonomy

| role | INPUT（manifest 内） | OUTPUT | authority | 決定論 validation | human gate | 禁止する近道 |
|---|---|---|---|---|---|---|
| **A** evidence 候補抽出 | evidence record 1〜少数（構造 field ＋ 限定 text 面）、対象 Theme root / THEME 提案 | EVIDENCE_CANDIDATE（SUPPORTS / CONTEXT） | L1（B3） | ref・target が manifest 内、role が許可集合、時刻・origin は **manifest から code が複写**、`reason` は template | B3 decision → B4E plan（consequence は人間が指定） | evidence の直接付与、LLM が時刻・origin を書くこと |
| **B** Theme 候補提案 | evidence records、taxonomy / entity（pinned）、既存 Theme の要約 | THEME_CANDIDATE | L1（B3） | Foundation / B3 model の全検査、certainty 固定、provenance を `LLM_PROPOSAL` に固定、slug / entity は pinned snapshot で解決 | B3 decision → theme creation plan → 別 gate の Foundation operation | root 作成、SOURCE_CLAIM / EXPLICIT_SOURCE_CAUSAL_CLAIM / EVIDENCE_SUPPORTED_MECHANISM |
| **C** relation 候補提案 | cutoff 時点の Theme root 2 つ以上、既存 edge（B5B resolution）、evidence | RELATION_CANDIDATE（proposer `LLM`） | L1（B5C） | 端点・前 assertion・evidence が manifest 内、type が B5 語彙、CAUSES は evidence 必須、撤回済み edge は governance 経路（FLOW 5）、`rationale` は template | B5C decision（SOURCE_ASSERTED は人間の確認 record 必須） | RelationAssertion append、SOURCE_ASSERTED の自動化、推移的推論 |
| **D** 反証・無効化候補 | 既存 Theme（無効化条件・期待 consequence を含む）と evidence | EVIDENCE_CANDIDATE（CONTRADICTS / INVALIDATES） | L1（B3） | A と同じ。対象 condition / consequence は LLM の説明（監査 field）に留め、identity には入れない | B3 decision。**Foundation への橋は現状無い**（B4E は SUPPORTS / CONTEXT のみ） | 反証の自動付与、lifecycle の変更 |
| **E** taxonomy / entity 正規化の示唆 | 限定 text 面、pinned taxonomy / catalog | 既存 slug / entity id への対応付けの示唆のみ | なし（生成 journal の注記） | pinned snapshot に存在する値だけ受理。新語彙は拒否 | 語彙の変更は knowledge の versioned release（人間） | taxonomy / catalog の自動変更 |
| **F** 既存 Theme への関連性示唆 | evidence と既存 Theme | A の EVIDENCE_CANDIDATE（target_root_id 付き） | L1（B3） | A と同じ | A と同じ | 関連度 score / 順位 |
| **G** 人間向け説明文 | 候補と根拠 | 説明文（`note` / `provenance.note` / 生成 journal） | なし | 長さ上限、秘密値・machine path・出典本文の長い逐語転載の拒否 | 読むだけ | 説明文を evidence・identity・authority にすること |
| **H** dedup 補助 | 候補と既存提案・既存 Theme の要約 | 「重複かもしれない」相手の列挙（理由付き） | なし（生成 journal の注記） | 相手 id が manifest 内であること | B3 exact dedup と人間の DEDUP 判断 | similarity score・順位・勝者選択・DEDUP_REVIEW の作成 |

## 5. proposal type の対応

| B7 の候補 | 既存 type | 新 type の要否 |
|---|---|---|
| evidence 候補（A / F） | B3 EVIDENCE_CANDIDATE | 不要 |
| Theme 候補（B） | B3 THEME_CANDIDATE | 不要 |
| relation 候補（C） | B5C RELATION_CANDIDATE（authority は B5C。B3 ではない） | 不要 |
| 反証・無効化候補（D） | B3 EVIDENCE_CANDIDATE（role CONTRADICTS / INVALIDATES） | 不要。ただし対象 condition を構造で持てない（B7-DEF-2） |
| 正規化示唆（E）・dedup 補助（H）・説明（G） | proposal ではない（生成 journal の注記） | 不要 |
| dedup review | B3 DEDUP_REVIEW（RULE 専用） | B7 は作らない |

**結論: B7 は proposal type を 1 つも増やさない。** B3 の予約 dedup class（SCOPE / SUBJECT / MECHANISM / PARENT_CHILD）も
B7 では使わない。

## 6. package boundary

| 案 | 内容 | 評価 |
|---|---|---|
| **K1** theme_intelligence 直下の flat module（`llm_` prefix） | 例: `llm_proposal_model.py` / `llm_input.py` / `llm_validator.py` / `llm_generation.py` / `llm_generation_store.py` / `llm_bridge.py` | **推奨**。B1〜B6 の慣行（1 機能 1 file、flat）と一致し、既存 guard（module 名の列挙）へ明示登録できる。P6-B0 §19 の `theme_intelligence/llm_proposals.py` 案の分割版 |
| K2 subpackage `theme_intelligence/llm_proposals/` | 境界は見やすい | 既存 guard の `glob("*.py")` は subdirectory を見ないため、**登録漏れで検査の外に出る** risk。採るなら guard の拡張が前提 |
| K3 別 top-level package（例 `src/intelligence/theme_llm/`） | 最も強い隔離 | B3 / B5C model・resolution・B4 snapshot を読むため依存は結局 theme_intelligence へ向く。guard を新設する必要がある |

依存方向（全案共通）:

- 許可: B7 → Foundation read（resolver）、B3 / B5C model・resolution・store の read / `append_proposal`、B4 taxonomy / entity snapshot、
  B5B resolution、B6 monitoring model（read のみ）、`core.types`。
- 禁止: Foundation / B1〜B6 → B7（upstream が B7 を import しない。guard 化）。
- **provider 実装（network・SDK）は theme_intelligence に置かない**。B7 は provider の narrow protocol（例 `complete(request) -> response`）
  だけを知り、実装は外から注入される（`core.contracts.LLMProvider` の vendor 中立の先例を再表現）。
- directory 構成・file 名は監督者の決定事項（CLAUDE.md）。本書は推奨のみ。

## 7. input contract

生成は **caller が渡す明示入力だけ**で行う。

| 入力 | 形 | 規則 |
|---|---|---|
| `cutoff` | aware datetime | 必須。現在時刻を読まない |
| `generated_at` | aware datetime（caller 注入） | `generated_at >= cutoff`。監査用で identity に入れない |
| manifest | `LlmInputManifest`（候補名）: 入力 item の列。各 item は opaque な handle（例 `E1` / `T2` / `R3`）、種別、実 id、許可 field だけ | PIT で濾過済み（§16）。canonical 化して digest を取る（input digest） |
| task | 役割（A〜H）と許可 output 種別 | 役割ごとに許可 output 種別は code 側の定数 |
| knowledge pins | taxonomy / catalog / prompt contract / output schema の version | 解決できない version は fail closed。`published_at > cutoff` は `FUTURE_KNOWLEDGE` |

manifest に入れてよい item と field（既定）:

| item | field |
|---|---|
| evidence（Fact / NewsItem / SourceDocument / Observation） | ref_id、種別、source origin の種別と key（URL 全体ではない）、evidence_time / date / basis / quality、fact_type / series、pinned catalog で正規化済みの entity id、限定 text 面（見出し・要約・title、長さ上限付き） |
| Theme（Foundation resolution at cutoff） | root_id、governance state token、subject / mechanism component の文言、scope、無効化条件の key と文言 |
| THEME 提案（B3、PIT 可視） | proposal_id、subject / mechanism の文言（target_proposal_id の候補として） |
| relation（B5B resolution at cutoff） | edge key、type、assertion class、edge state |
| monitoring finding（任意、§25） | condition_id、subject_ref、salient facts、trigger / supporting refs |

入れないもの: decision の結果・受理率・review disposition・finding 件数・score、本文全体、Compass / corpus / formal review / DNA、
portfolio、journal、credential、machine path。

## 8. output schema の概念

LLM が返してよいのは次の **単一 JSON object** だけ（schema は versioned knowledge、B7B で確定）。

```
{
  "output_schema_version": "<pinned>",
  "outcome": "CANDIDATES" | "ABSTAIN",
  "abstention": {"code": "NO_PROPOSAL|INSUFFICIENT_EVIDENCE|AMBIGUOUS|UNSUPPORTED|OUT_OF_SCOPE",
                 "input_handles": ["E1", ...]},                      # outcome = ABSTAIN のときだけ
  "candidates": [                                                     # outcome = CANDIDATES のときだけ（上限件数あり）
    {"candidate_kind": "EVIDENCE_CANDIDATE|THEME_CANDIDATE|RELATION_CANDIDATE",
     "evidence_handles": ["E1", ...],                                # manifest handle のみ。実 id を書かせない
     "target_handle": "T2",                                          # 対象 Theme / 提案 / 端点
     "payload": { ... kind 別の構造 field（語彙は enum / pinned slug / entity id） ... },
     "limitations": ["..."],                                         # 不確かさは段階値でなく限定条件で表す
     "rationale": "<bounded 説明。identity に入らない>"}
  ]
}
```

- **数値の確信度・score・順位・確率を持たない**（既存 guard の禁止語と一致）。不確かさは limitations・無効化条件・棄権 code で表す。
- evidence の時刻・origin・source 種別は LLM に書かせない（manifest から code が複写する）。
- decision・provenance class・governance・lifecycle・assertion class を表す field は schema に存在しない。書けば unknown field で拒否。

## 9. evidence grounding

1. LLM は evidence を **manifest handle** でしか指せない。handle → 実 id の対応は code が持つ。存在しない handle は拒否。
2. manifest 自体が PIT 可視かつ許可 source だけから作られるので、未来の evidence・存在しない evidence は構造的に引用できない。
3. evidence の性質（時刻・origin・kind）は manifest から複写し、LLM の値を使わない。
4. **LLM 自身の文章は evidence にならない**（Foundation: LLM 出力は evidence authority ではない。semantics contract §17）。
   説明文は監査 field にだけ置く。
5. relation の出典帰属は、引用した evidence の origin と一致する場合だけ受理（一致しなければ拒否）。それでも
   SOURCE_ASSERTED にはならず、人間の `SourceClaimVerification` を要する（B5C-R1）。
6. 反証の不在を確証と解釈しない（semantics contract §14）。棄権は正当な出力。

## 10. deterministic validator

入力は「parser が受理した構造」、出力は「B3 / B5C の record を build できる検証済み候補」または coded な拒否理由。
順序（すべて純関数、時計・network・乱数なし）:

1. **envelope**: 単一 object、schema version 一致、unknown field 拒否、件数・長さ上限、`outcome` と中身の整合。
2. **grounding**: 全 handle が manifest 内、role ごとに許可された handle 種別。
3. **vocabulary**: candidate kind が task の許可集合内、relation type / evidence role / scope dimension / component type が
   Foundation・B5 の enum 内、slug / entity id が pinned snapshot に存在。
4. **authority ceiling**: provenance を code が設定（B3 `LLM_PROPOSAL` / B5C `LLM`）。THEME の attachment `role_provenance` と
   機構 component の主張 provenance を `LLM_PROPOSAL` に固定。certainty は `HYPOTHESIZED_MECHANISM` 固定。
   SOURCE_CLAIM・`source_causal_claim`・EXPLICIT_SOURCE_CAUSAL_CLAIM・EVIDENCE_SUPPORTED_MECHANISM は拒否。
5. **model 検査**: 既存の `ThemeCandidateProposal.build` / `EvidenceCandidateProposal.build` / `RelationProposal.build` を通す
   （Foundation / B3 / B5C の不変条件をそのまま使う。再実装しない）。
6. **identity 規律**: identity に入る文（`reason` / `rationale`）は template で code が作る。LLM の説明は `note` /
   `provenance.note` へ（長さ上限・秘密値・machine path・長い逐語転載の拒否）。
7. **PIT**: 候補の evidence_time は manifest から（≤ cutoff）。`created_at` は caller の `generated_at`。

**拒否は全体単位を基本案とする**: envelope・grounding・vocabulary・authority の違反が 1 件でもあれば、その生成全体を
`REJECTED_GENERATION` にし、違反ごとの code を生成 journal に残す（部分受理・黙った修復・切り詰めをしない）。
Compass の LLM 生成器（`parse_llm_claims`）は不正 claim を落として残りを使うが、**その pattern は B7 に持ち込まない**
（authority 手前の層で幻覚の混じった生成を部分採用しない）。

## 11. abstention

- `outcome = ABSTAIN` と code（NO_PROPOSAL / INSUFFICIENT_EVIDENCE / AMBIGUOUS / UNSUPPORTED / OUT_OF_SCOPE）を正当な出力とする。
- 棄権は失敗ではなく、生成 journal に `NO_PROPOSAL` として残る。**空文字・空 object は棄権ではない**（`REJECTED_GENERATION`）。
- prompt contract は「常に何かを提案せよ」を含まない。1 生成あたりの候補数に下限を設けない（上限だけ）。
- 棄権率を最適化対象・評価指標にしない（§16 の自己強化禁止）。

## 12. hallucination containment

| 幻覚 | 決定論的な拒否 |
|---|---|
| unknown entity | pinned `EntityCatalogSnapshot` で解決できない → `UNKNOWN_ENTITY` |
| unknown evidence ref | manifest に無い handle → `UNKNOWN_INPUT_HANDLE`（実 id は書かせないので捏造 id は入口で存在しない） |
| unsupported taxonomy value | pinned `TaxonomySnapshot` に無い slug → `UNKNOWN_TAXONOMY_SLUG` |
| invalid Theme mechanism | Foundation `Mechanism` / B3 THEME の検査（component 型・category・PERIOD_FRAME 1 つ・無効化条件 ≥ 1）→ 既存 code |
| invalid relation type | B5 `RelationType` 外、CAUSES の evidence 欠落 → 既存 code |
| invalid evidence role | role ごとの許可集合外 → `ROLE_NOT_ALLOWED_FOR_TASK` |
| invalid lifecycle assumption | schema に lifecycle field が無い。構造 field に lifecycle / governance 語彙（ACCEPTED / RETIRED / EMERGING 等）が現れたら `LIFECYCLE_CLAIM_IN_OUTPUT` |
| invalid governance claim | decision / provenance class / assertion class を書く field は無い。書けば `AUTHORITY_CLAIM_IN_OUTPUT` |
| 出典の主張の捏造 | 出典帰属が引用 evidence の origin と不一致 → `ATTRIBUTION_MISMATCH`。一致しても人間確認までは SOURCE_ASSERTED にならない |

## 13. prompt injection / 信頼できない文

- source の文（見出し・要約・title・excerpt）は **data** であって命令ではない。input builder は untrusted 文を
  区切り付きの data 欄にだけ入れ、system contract・schema・許可 type・authority ceiling を文から組み立てない。
- **input builder と validator を分ける**。validator は prompt を見ない。prompt が何を言っても、schema・許可 output 種別・
  authority ceiling・human gate は code の定数で決まる（外部の文はこれらを変えられない）。
- 注入の典型（「以前の指示を無視」「system:」「HUMAN として承認」など）が出力に現れた場合の防御は、内容の意味判定ではなく
  **構造の拒否**（unknown field・authority 語彙・許可外 kind）で行う。意味的な注入検出器は置かない（誤検出の責任を持てない）。
- untrusted 文を identity field に写さない（template 化。§15）。説明文への長い逐語転載も拒否する。
- 1 生成に含める item 数を小さく保ち、注入の影響範囲を限定する（§24 batching）。

## 14. non-determinism boundary

```
[決定論]  PIT manifest 構築 → input digest → 生成 request id
[非決定]  provider.complete(request) → raw response            ← ここだけが非決定
[決定論]  response digest → parser → validator → 提案 plan → check-then-reuse → (submit) → B3 / B5C
```

- 同じ request から別の response が出てもよい。**authority の決定論は「どの record が append されたか」の履歴で担保**され、
  生成の再実行で過去の authority は変わらない（append-only・内容 id）。
- 同じ response bytes に対して parser / validator / plan は常に同じ結果を返す（replay 可能）。
- 生成を「通るまで引き直す」ことをしない（§19。選択圧は暗黙の tuning であり幻覚の洗浄になる）。

## 15. identity strategy

### 15.1 提案の identity（既存 authority のまま）

- B3 / B5C の内容 id をそのまま使う。provenance（model・prompt・生成 id）と created_at は identity に入らない。
- **raw text・出力の順序・timestamp・random UUID に依存させない**:
  - 出力順は canonical sort で除去（既存 model が attachment 等を sort 済み）。
  - identity に入る自由文は template（EVIDENCE の `reason`、RELATION の `rationale`）。例: 既存の
    `evidence_reason(role, kind)`（B4）と同じ形の template。LLM の説明は `note` / `provenance.note`。
  - THEME の subject / mechanism の文言は内容そのものなので identity に入る（言い回しが違えば別候補になる）。これは
    B3 の既存意味論であり、B7 は変えない。重複は B3 exact dedup ＋ 人間で扱う（§23）。
- 同じ内容を別の生成・別の model・RULE が提案した場合は **同じ id に収束**する（望ましい）。

### 15.2 生成の identity（B7 層）

| id | 材料 | 含めないもの |
|---|---|---|
| request id（冪等 key） | input digest、task、prompt contract version、output schema version、provider / model 識別子、生成設定 | 時刻・乱数・machine 情報 |
| generation record id | request id ＋ response digest（または response 無しの outcome code） | created_at |

model 識別子は **生成 record にだけ**入り、Theme / 提案の semantic identity には入らない。

### 15.3 収束（check-then-reuse）

bridge は append 前に既存 id を引く。在れば append しない（`EXISTING_PROPOSAL_REUSED`）。provenance だけが違う 2 件目を
append すると CONFLICT になるため（B5 §10.1）。収束の事実は生成 journal に残す（B5 の D3〜D5 を変えずに済む）。

## 16. PIT / time semantics

- `cutoff` と `generated_at` は caller 注入。B7 は時計を読まない。provider が返す時刻は使わない。
- manifest は PIT で作る: Foundation `resolve_at_data_root`、B5B `resolve_relations_at_data_root`、B3 / B5C は
  `created_at` / `recorded_at <= cutoff` で **解決の前に濾過**（B6D-R1 と同じ契約。B6 runner の private helper は使わず、
  B7 側で同じ契約を実装し同じ matrix で test する）。
- knowledge（taxonomy / catalog / prompt contract / schema）は `published_at <= cutoff`。
- **LLM 自身の知識は PIT ではない**。出典は manifest に閉じるが、説明文や候補の着想に cutoff 後の知識が混ざりうる。
  したがって B7 の出力を過去時点の評価・backtest・P5 の予測評価に使ってはならない（B7-DEF-5）。
- 同じ cutoff の再生成は同じ manifest（同じ input digest）になるが、response は同じとは限らない（§14）。

## 17. provenance

| 置き場所 | 内容 |
|---|---|
| 生成 journal（B7） | request id、input digest、manifest の item 参照（evidence / Theme / relation / 提案 / finding の id）、taxonomy / catalog / prompt contract / output schema の version、provider・model 識別子・生成設定、response digest、outcome、拒否 code、得られた候補の proposal id、収束先の既存 id、`generated_at` |
| B3 `ProposalProvenance` | `proposer_class = LLM_PROPOSAL`、`proposer_ref = <generation record id>`、`rule_version = <prompt contract version>`、`reason = <bounded 説明>` |
| B5C `RelationProposalProvenance` | `proposer_class = LLM`、`proposer_ref = <generation record id>`、`rule_version = <prompt contract version>`、`note = <bounded 説明>` |

- system prompt・few-shot・response・自然文の理由は **authority ではない**。保存しても監査 record 以上の意味を持たない。
- 隠れた推論過程（chain-of-thought）の保存を前提にしない。取得も要求しない。
- `created_at` / 生成 id は provenance に置き、semantic identity に入れない。

## 18. persistence options

| 観点 | A: raw 非永続、検証済み提案のみ永続 | B: raw も監査 artifact として永続 | **C: 生成 journal を proposal authority と分離** |
|---|---|---|---|
| security | 最良（raw に混ざる untrusted 文・注入文を残さない） | 最悪（注入文・出典文の逐語が溜まる） | raw を既定で残さなければ A と同等 |
| replay | 不可（検証をやり直せない） | 可 | 検証を通った構造と response digest を残せば validator の replay は可 |
| storage | 最小 | 最大 | 小（digest と構造） |
| 監査 | 失敗・棄権・却下が残らない | すべて残る | outcome・code・収束がすべて残る |
| authority 分離 | 提案だけ | raw が authority の隣に置かれる | 生成 journal は Theme authority ではない監査 record として分離 |

**推奨: C**（`<data_root>/theme_intelligence/` の別 file。append-only・canonical・内容 id・破損 fail closed。B3 / B5C / Foundation /
B6 の file とは別）。raw response は **既定で保存しない**（digest のみ）。raw の保存は、監督者が別途認めた場合に限り、
repo 外・opt-in・保持期限付き・入力として二度と読まない領域に置く（B7-DEF-3）。
生成 journal は **次回の生成入力として読まない**（§ 自己強化の禁止。input builder は生成 journal を import しない）。

B7A では決定しない。実装しない。

## 19. failure taxonomy

| 事象 | 分類 | 生成 journal | 提案 | retry |
|---|---|---|---|---|
| provider unavailable | RETRYABLE_FAILURE | outcome のみ | なし | 上限付き |
| timeout | RETRYABLE_FAILURE | outcome のみ | なし | 上限付き |
| rate limit | RETRYABLE_FAILURE | outcome のみ | なし | 上限付き（backoff） |
| invalid JSON | REJECTED_GENERATION | digest ＋ code | なし | **自動 retry しない** |
| schema mismatch / unknown field | REJECTED_GENERATION | digest ＋ code | なし | しない |
| unknown ref / handle | REJECTED_GENERATION（幻覚） | digest ＋ code | なし | しない |
| unsupported enum / slug / entity | REJECTED_GENERATION | digest ＋ code | なし | しない |
| overlong output | REJECTED_GENERATION（切り詰めない） | digest ＋ code | なし | しない |
| empty output | REJECTED_GENERATION（棄権ではない） | digest ＋ code | なし | しない |
| authority / lifecycle claim in output | REJECTED_GENERATION | digest ＋ code | なし | しない |
| abstention | NO_PROPOSAL（正常） | outcome ＋ code | なし | しない |
| duplicate proposal | EXISTING_PROPOSAL_REUSED（正常） | 収束先 id | append しない | — |
| stale input（submit 時に manifest を再導出すると input digest が変わる） | INTEGRITY_FAILURE | code | submit しない | 生成からやり直し（人間判断） |
| future evidence leakage（manifest に cutoff 後の record が入った） | INTEGRITY_FAILURE（input builder の欠陥） | code | なし | しない（欠陥修正まで停止） |
| authority 破損（manifest 構築時の store 失敗） | INTEGRITY_FAILURE | code | なし | しない |

- REJECTED_GENERATION を自動 retry しないのは、通るまで引き直すと幻覚を選別して通すことになるため。再生成は人間の明示操作。
- 例外 message に秘密値・本文・machine path を入れない（coded error のみ）。

## 20. provider / model boundary

- semantic contract（schema・語彙・authority ceiling・identity）に特定 provider / model 名を入れない。
- provider / model 識別子・prompt contract version・生成設定は **provenance（生成 record）**としてだけ保持する。
- B7 が知るのは narrow な provider protocol だけ。実装（SDK・network・credential）は theme_intelligence の外にあり、
  実 provider の接続は B7 の後段の別 gate（§30、B7-DEF-4）。B7B〜B7G は fake / recorded provider だけで完結する。
- model を替えても既存提案の identity は変わらない（provenance 外）。model の違いは生成 record で区別される。

## 21. data minimization

| 問い | 答え（既定案） |
|---|---|
| 本文全体は必要か | **不要**。B4 と同じ限定 text 面（見出し・要約・title）と構造 field で足りる設計にする。excerpt を使う場合も長さ上限付きの限定面のみ |
| Theme snapshot 全体は必要か | 不要。root id・governance token・subject / mechanism 文言・scope・無効化条件だけ |
| 提案・decision 履歴は必要か | decision の結果・受理率・review disposition は送らない。target 候補としての提案 id と文言だけ |
| 送らないもの | 機密の Compass PDF・corpus・formal review・DNA、portfolio、journal、credential、machine path、URL の query、個人識別情報 |

input builder は許可 model だけを import し（guard 化）、送った field の一覧を manifest として digest に束縛する（何を送ったかが監査できる）。

## 22. Compass / DNA boundary

- B7 の input builder は `compass` / `corpus` / `corpus_research` / `formal_review` / `decision` / Compass DNA
  （`market_rules.yaml` / `market_principles.py`）を import も参照もしない（既存 guard の禁止 token と同じ方針を B7 guard に持つ）。
- APPROVED-but-NOT_PROMOTED を production rule として prompt に混ぜない。REJECTED / KEEP_REVIEWING / 未 review の推奨を
  解釈 authority として渡さない（Phase 4 / 5 entry contract の継承）。
- **Production DNA だけが production interpretive authority** だが、B7 の出力は L1 の内部候補であり解釈 authority を要しない。
  推奨: **B7 の prompt には DNA も含めない**（第二 DNA 化・DNA 依存の Theme 生成を避ける。D-B7-9）。
- prompt contract は versioned knowledge として人間が release し、DNA の文言を含まないことを B7B の guard で固定する。

## 23. B3 dedup との相互作用

- 自動 dedup は B3 の exact detector（semantic / identity-core fingerprint の完全一致）だけ。B7 bridge は discovery と同様に
  新 THEME 候補へ detector を走らせ、DEDUP_REVIEW を RULE 提案として作る（既存 detector の出力であり LLM の判断ではない）。
- LLM の dedup 補助（役割 H）は「重複かもしれない相手」の列挙と理由の注記だけ。similarity score・順位・勝者選択を持たない。
  DEDUP_REVIEW は作れない（RULE 専用）。NOT_DUPLICATE を判断しない。
- 言い換えによる準重複は exact detector を通り抜ける。これは既存の意図した限界であり、人間の review が担う（B7-DEF-6）。

## 24. B5 relation との相互作用

- LLM の relation 候補は B5C の提案（proposer `LLM`）→ 人間 decision → `RelationAssertionPlan` の既存経路だけ。
- SOURCE_ASSERTED の意味を維持: **source asserted relation ≠ objective truth**。LLM は `SourceClaimVerification` を作れず、
  出典帰属は引用 evidence の origin と一致する場合だけ受理する。
- graph は descriptive のまま。PageRank / centrality / 重要度 score / 推移的推論 / 因果確度 score を追加しない。
  LLM に graph 経路から relation を推論させない（B5 §9: graph 経路 → 関係 をしない）。
- 撤回済み edge への候補は FLOW 5（`RELATION_RETRACTED_REQUIRES_GOVERNANCE`）に従う。RR-3 POLICY LOCK は不変。

## 25. B6 monitoring との相互作用

- `MonitoringFinding` は DERIVED・非 authority・非永続。B7 は finding を「人間 / LLM が見るべき観測材料」として manifest に
  入れてよい（condition_id・subject_ref・salient facts・trigger / supporting refs の最小限）。
- finding は **evidence_ref にならない**。provenance として `(run_id, finding_id)` を生成 journal に残すだけ（run report は
  永続化されないため、参照は cutoff・ruleset version と共に残す）。
- finding 件数を重要度にしない。ACK / DISMISS / DEFER を semantic truth にしない（**review disposition は manifest に入れない**）。
- `Finding → LLM → 自動 governance 変更` の経路は作らない。finding から生成を自動起動しない（scheduler なし）。
  どの finding を入れるかは人間 / operator が選ぶ。
- B6 は変更しない。B7 は B6 を import してよい（read model のみ）が、B6 は B7 を import しない。

## 26. security

- API key: repo・config 平文・log・proposal record・生成 journal・例外 message に入れない。runtime injection のみ
  （provider 実装の外側で注入。B7 は key を読まない・受け取らない）。
- network call の境界: provider 実装だけが network に触れる。theme_intelligence の B7 module は network・SDK・環境変数を
  import / 参照しない（B7B で guard 化）。B7A では network call を一切行っていない。
- prompt / raw response を log に出さない（Compass generator の先例: 件数だけを記録）。
- 永続化する文（説明文・拒否 code）に秘密値・machine path・URL の userinfo / 秘密 query が入らないことを検査する
  （B3 model の `_SECRET_QUERY_RE` / path 検査と同じ方針）。

## 27. offline testing

- provider 無しで B7 の大半を test できる構成にする:
  - `FakeProvider`（script した response を返す）、`RecordedProvider`（synthetic fixture の response bytes を返す）、
    `UnavailableProvider`（常に利用不可）。
  - parser / validator / plan / bridge は純関数で、recorded response から決定論的に test する。
- CI は実 LLM API を要求しない。実 provider の test は別 gate で、明示的な opt-in の下でだけ行う。
- 敵対 fixture: 幻覚 handle、未知 slug / entity、注入文を含む見出し、authority 語彙を書く出力、空出力、過長出力、
  JSON 破損、棄権、既存提案と同内容の出力、cutoff 後の record を manifest に紛れ込ませる input 側欠陥。
- fixture はすべて synthetic。実記事本文・Compass・portfolio を fixture にしない。

## 28. public surface の隔離

B7 は internal first。`/v2`・root 出力・GitHub Pages・customer 出力・legacy brief・notification・scheduler に接続しない。
B7 module を production bundle closure に入れない（既存の production bundle guard を維持）。workflow を追加しない。

## 29. deferred items（B7 に持ち込む既知事項）

| id | 内容 | blocking | 扱い |
|---|---|---|---|
| B7-DEF-1 | B3 model は LLM_PROPOSAL 提案の attachment / component provenance を model 側で強制しない（B7 validator が強制する） | No | 多層防御として B3 に不変条件を足すかは監督判断（D-B7-12）。B7F の前に決めるのが望ましい |
| B7-DEF-2 | EVIDENCE_CANDIDATE は対象の consequence / 無効化条件を構造で持てず、B4E は CONTRADICTS / INVALIDATES を橋渡ししない | No | 役割 D は「人間 review 用の提案」まで。Foundation への反証付与は将来の別 gate |
| B7-DEF-3 | raw response の保存方針（既定は非保存） | No | 監督判断（D-B7-7） |
| B7-DEF-4 | 実 provider の接続（credential・network・費用） | No（B7B〜B7G は fake / recorded のみ） | B7 closeout 後の別 gate |
| B7-DEF-5 | LLM の知識は PIT ではない | No | B7 出力を評価・backtest・P5 に使わない（contract で固定） |
| B7-DEF-6 | 言い換えによる準重複は exact dedup を通り抜ける | No | 人間 review。意味的 dedup の authority 化はしない |
| B7-DEF-7 | B5 の D3〜D5（収束診断・`append_or_reuse`・co-discovery journal） | No | B7 は check-then-reuse と生成 journal で吸収し B5 を変えない |
| B7-DEF-8 | RR-1（B5C store の古い docstring） | No | 実行 gate 前の単独 patch（B5 closeout の推奨どおり）。B7 の範囲外 |

## 30. 推奨する B7 の実装順

監督案（B7A → B7B → B7C → B7D → B7E → B7F → closeout）に対し、**入力 manifest の構築を独立 gate にし、実 provider 接続を
B7 の外へ出す**修正案:

| gate | 内容 | 主な成果物（候補） | network |
|---|---|---|---|
| **B7A** | architecture / contract（本書） | docs | なし |
| **B7B** | model / schema: 生成 request / record、output schema、outcome / 拒否 code 語彙、identity、生成 journal の record 型、guard 登録 | `llm_proposal_model.py`、versioned output schema / prompt contract の knowledge、test | なし |
| **B7C** | input manifest builder: PIT 濾過（B6D-R1 と同じ matrix）、data minimization、untrusted 文の data 欄、input digest | `llm_input.py`、test | なし |
| **B7D** | deterministic validator: grounding・語彙・authority ceiling・model 検査・template identity・全体拒否 | `llm_validator.py`、test | なし |
| **B7E** | generation adapter: narrow provider protocol、fake / recorded / unavailable provider、failure taxonomy、retry 方針、生成 journal store | `llm_generation.py`、`llm_generation_store.py`、test | **なし**（実 provider なし） |
| **B7F** | proposal bridge: append 候補、check-then-reuse、B3 exact dedup、明示 submit（B3 / B5C `append_proposal` のみ） | `llm_bridge.py`、test | なし |
| **B7G** | adversarial E2E: 幻覚・注入・PIT・漏洩・収束・zero authority mutation・security | test、docs | なし |
| **B7 closeout** | completion audit | docs | なし |
| （B7 の外） | 実 provider 接続・credential 注入・費用管理・実データ shadow | 別 gate（監督判断） | あり |

## 31. 監督者の決定事項（B7B 着手前）

| # | 決定 | 推奨 |
|---|---|---|
| D-B7-1 | 新 proposal authority を作らず B3 / B5C を再利用する | 採用（§2.4 P3） |
| D-B7-2 | B7 の上限は L1、decision・authority append・root 作成への経路なし | 採用（§3） |
| D-B7-3 | proposal type を増やさない | 採用（§5） |
| D-B7-4 | package 配置 | K1（flat `llm_` module）＋ guard 登録（§6） |
| D-B7-5 | LLM は manifest handle でのみ引用、時刻・origin は code が複写 | 採用（§9） |
| D-B7-6 | 違反時は生成全体を拒否（部分受理・修復なし） | 採用（§10） |
| D-B7-7 | 永続化 | Option C、raw response 既定非保存（§18） |
| D-B7-8 | identity に入る自由文の template 化、LLM 説明は監査 field | 採用（§15） |
| D-B7-9 | prompt に Compass / corpus / formal review / DNA を含めない（Production DNA も含めない） | 採用（§22） |
| D-B7-10 | REJECTED_GENERATION を自動 retry しない | 採用（§19） |
| D-B7-11 | 実 provider 接続を B7 の外の別 gate にする | 採用（§30） |
| D-B7-12 | B3 model に LLM_PROPOSAL 提案の provenance 不変条件を多層防御として足すか | 任意。足す場合は B7F の前に B3 の最小 hardening gate（prior phase 変更）として別に開く |

## 32. blockers

**なし。** 監査した B3 / B4 / B5 / B6 の interface は B7 の設計（P3: 既存 authority ＋ authority 手前の層）を変更なしで受け入れる。
§29 の事項はいずれも non-blocking。

## 33. 判定（案）と HARD STOP

**判定案: A — P6_B7A_ARCHITECTURE_VALIDATED / READY_FOR_P6_B7B**（§31 の決定を監督者が確定することが B7B の前提）。

B7B の実装は開始しない。LLM / network call を行わない。API key を要求しない。B6 を変更しない。B5 execution gate を作らない。
scheduler / notification / public output を作らない。監督者の判断を待つ。
