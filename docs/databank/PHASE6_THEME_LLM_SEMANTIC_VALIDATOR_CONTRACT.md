# PHASE 6 / P6-B7D — DETERMINISTIC SEMANTIC VALIDATOR CONTRACT

GROUNDING / NORMALIZATION / PROPOSAL PLAN ONLY。provider・network・prompt・generation journal・B3 / B5C への提出・書き込みは無い。

| module | 役割 |
|---|---|
| `src/intelligence/theme_intelligence/llm_plan_model.py` | 検証済み提案 plan と検証結果の純 model（provenance lock・identity template・error code） |
| `src/intelligence/theme_intelligence/llm_validator.py` | `validate_generation`（純関数。束縛・grounding・正規化・上流 constructor の試行） |
| `tests/intelligence/test_theme_llm_validator.py` | test matrix A〜AM ＋ 全体拒否・上流 constructor・template・時刻欠落・推移辺・数値 |

流れ: `PIT manifest（B7C）→ 構造化出力（B7B）→ **B7D 意味検証** → 検証済み提案 plan → [B7F] → 既存の B3 / B5C`。
前提: **LLM の出力は信頼しない**。B7D は LLM を呼ばない。

---

## 1. authority の分類

| 対象 | 分類 |
|---|---|
| `ValidatedEvidenceProposalPlan` / `ValidatedThemeProposalPlan` / `ValidatedRelationProposalPlan` | **DERIVED・非 authority・非永続** |
| `LlmValidationResult` | 生成 1 回分の決定論的な検証結果（同上） |

plan は B3 / B5C の提案 authority・Theme / evidence / relation の authority・relation assertion・governance の決定・
人間の確認の**どれでもない**（`PLAN_IS_NOT_AUTHORITY`）。書き込みは一切無い。

## 2. 入力

| 入力 | 使い方 |
|---|---|
| B7B `LlmGenerationRequest` | manifest digest・task・cutoff・出力 schema・knowledge pin の束縛。`generated_at` は上流 constructor の試行時刻だけ |
| B7B `LlmGenerationEnvelope` | 検証対象（構造は B7B が検査済み。B7D は構造に頼らず意味を独立に検査する） |
| B7C `LlmInputManifest` | B7D の「世界」。見えている投影と、visible に入らない内部対応表 |
| B7C 内部対応表（`resolution`） | handle → authority / source ref と material（evidence の時刻・origin 等） |
| knowledge | manifest の pin と、出力 schema が束ねた凍結語彙だけ（§16） |

新しい authority record を探しに行かない。scope を黙って広げない。data root・store・journal を読まない。

## 3. request ↔ manifest の束縛

候補の検証の前に次を確認し、違えば fail closed。

| 検査 | code |
|---|---|
| `request.manifest_digest == manifest.manifest_digest()`（manifest は内容から digest を再計算する） | `REQUEST_MANIFEST_MISMATCH` |
| `request.task == manifest.task` | `TASK_MISMATCH` |
| `request.cutoff == manifest.cutoff` | `REQUEST_MANIFEST_MISMATCH` |
| `request.output_schema_version == envelope.output_schema_version == OUTPUT_SCHEMA_VERSION` | `REQUEST_MANIFEST_MISMATCH` |
| `request.knowledge_versions == manifest.knowledge_versions` | `KNOWLEDGE_PIN_MISMATCH` |

別の manifest に対して生成を検証することは無い。

## 4. grounding

- 候補が使う handle は**すべて** B7C の内部対応表で解決する。無ければ `UNKNOWN_HANDLE`。
- 欄ごとに期待する family と違えば `HANDLE_FAMILY_MISMATCH`。family は handle の prefix ではなく対応表の family で判定する。

| 欄 | family |
|---|---|
| `evidence_handles` | EVIDENCE（MON・Theme・relation は出典 evidence にならない） |
| evidence 候補の `target_handle` / relation の端点 | THEME |
| `component_handle` | SUPPORTS / CONTRADICTS → THEME_CONSEQUENCE、INVALIDATES → THEME_INVALIDATION |
| `context_handles` | MONITORING |
| `subject_entity_handle` / component の `entity_handle` | ENTITY |
| `previous_relation_handle` | RELATION |

- task scope 外の参照は `OUT_OF_SCOPE_REFERENCE`（task が MON を取らない、MON が候補と別の Theme を扱う、entity が引用
  evidence に載っていない）。component が別 Theme のものなら `INVALID_TARGET`。
- LLM は authority id を書く欄を持たない（B7B）。handle 以外の値が handle 欄にあれば構造で拒否される。

## 5. plan model

| plan | 上流 constructor | 材料 |
|---|---|---|
| `ValidatedEvidenceProposalPlan` | B3 `EvidenceCandidateProposal.build` | evidence の kind・ref・origin・時刻・basis・quality・日付（manifest から複写）、role、target root、target component（kind・key）、reason（template） |
| `ValidatedThemeProposalPlan` | B3 `ThemeCandidateProposal.build` | 正規化済みの `ThemeSubject`・`Mechanism`・scope・無効化条件・限定条件、`PlannedEvidenceRef`（attachment の材料。attached_at は B7F）、固定確度 |
| `ValidatedRelationProposalPlan` | B5C `RelationProposal.build` | 端点 root・type・change kind・前 assertion・出典帰属（未確認）・evidence ref・rationale（template） |

各 plan は `upstream_arguments()` で凍結 constructor の引数をそのまま返す（provenance と created_at は B7F が付ける）。

**identity**

- `plan_id`（`thllmplan_`）: 正規化済みの提案材料だけの content id。LLM の説明文・MON 文脈・provider / model・時刻・
  候補の順序を含まない。
- `upstream_proposal_id`: B7D が凍結済みの B3 / B5C constructor にこの材料を通して得た id（試行の provenance は
  `LLM_PROPOSAL` / `LLM` ＋ request id、created_at は `generated_at`）。B3 / B5C の identity は provenance と created_at を
  含まないため、B7F が同じ材料を渡せば**同じ id**になる（test で provenance・時刻を変えて確認）。
- `plan_id` は上流の提案 id を名乗らない（両者は別物）。

`LlmValidationResult`（`thllmval_`）は request id・manifest digest・output digest・task・cutoff・knowledge・outcome・
plan id の列を束ねる。provider / model / `generated_at` は含まない。

## 6. evidence 候補の検証

1. evidence handle（1 件）を解決し、material を manifest から複写する（LLM は時刻・origin を書けない）。
2. target handle を THEME として解決する。
3. role が task に許されていること（EVIDENCE_EXTRACTION: SUPPORTS / CONTEXT、CONTRADICTION_PROPOSAL: CONTRADICTS /
   INVALIDATES）。違えば `INVALID_EVIDENCE_ROLE`。
4. 時刻が MISSING の evidence は CONTEXT だけ（Foundation A2 §7）。違えば `INVALID_EVIDENCE_ROLE`。
5. role ごとの target component（下記）。
6. MON は文脈だけ（§9）。
7. reason を template で作り（§13）、B3 constructor に通す。

B7D は grounding と構造の適合を検証するだけで、**事実の主張が正しいかは判定しない**。

**SUPPORTS / CONTEXT（B4E / Foundation の意味論）**: SUPPORTS と CONTRADICTS は consequence（CQ）、INVALIDATES は無効化
条件（IC）を要し、CONTEXT は component を持たない。component は manifest の handle からだけ導く。欠けていれば
`INVALID_TARGET`、target Theme に候補が複数あって欠けていれば `AMBIGUOUS_TARGET`、別 Theme の component なら
`INVALID_TARGET`。先頭の consequence の自動採用はしない（B4E と同じ）。

**CONTRADICTS / INVALIDATES**: B3 EVIDENCE_CANDIDATE の材料として検証するだけ。Foundation を変えない・attachment を
作らない・Theme を退役させない・governance action にしない。B4E は役割 D を橋渡ししない（凍結）ため、**plan は提案に
とどまる**（test で data root の不変と plan の field 集合を確認）。

## 7. Theme 候補の検証

- 引用 evidence・entity handle を manifest で解決する。entity は**引用 evidence が持つ entity** に限る（§4）。
- 語彙: component category は Foundation の機構語彙（`mechanism_vocabulary:0.1.0`）、scope dimension・expected change・
  limitation category は Foundation の enum。語彙外は `UNSUPPORTED_VOCABULARY`。
- PERIOD_FRAME はちょうど 1 つで、`single_session` / `single_event` ではない（A1 Q4。B4 discovery と同じ）。
- 正規化（§12）の後、Foundation の型（`ThemeSubject`・`MechanismComponent`・`ExpectedConsequence`・`Mechanism`・
  `ScopeToken`・`InvalidationCondition`・`Limitation`）を組み、B3 `ThemeCandidateProposal.build` に通す。
- ThemeRoot を作らない。governance lifecycle を与えない。LLM が書いた provenance を受け付けない（欄が無い）。
- **自由文の主題**: Foundation の `ThemeSubject.normalized_subject` は必須の文であり、THEME 候補は常に主題文を持つ。
  entity handle は任意で、在れば `typed_reference` に entity id を入れる（無ければ空）。主題文は B3 の既存意味論どおり
  identity に入る（言い換えは別候補になる。§13）。
- THEME 候補の evidence は **CONTEXT** として引く（`THEME_EVIDENCE_ROLE`）。B7B の THEME schema は evidence ごとの role も
  consequence ごとの支持も持たないため、SUPPORTS と consequence ref を作らない（捏造しない）。

## 8. relation 候補の検証

- 端点 2 つを THEME として解決し、別 root であること（`INVALID_RELATION_ENDPOINT`）。
- relation type は B5 の語彙（`theme_relation_vocabulary:0.1.0`）。
- 前 relation（訂正）: RELATION として解決し、edge key の端点・type・帰属が候補と一致すること（違えば `INVALID_TARGET`。
  B5C bridge の `PREDECESSOR_WRONG_EDGE` を先に閉じる）。前 assertion id は対応表の terminal assertion id。
- 出典帰属（下記 SOURCE_ASSERTED）: 引用した文章 evidence（NEWS_ITEM / SOURCE_DOCUMENT / STATEMENT）で、origin が PUBLISHER_ARTICLE /
  OFFICIAL_RELEASE のものに限る。`attributed_to` はその evidence の **origin_key**（Foundation A2 §8 の出所 identity）。
  それ以外（市場系列・DERIVED・UNKNOWN）は `INVALID_ATTRIBUTION`。
- 推移的な辺・中心性・順位・自動 assertion を作らない（候補 1 件 → plan 1 件）。
- B5C `RelationProposal.build` に通す（提案者 `LLM`）。

**SOURCE_ASSERTED**: SOURCE_ASSERTED は「引用した出典がその関係を主張した」であり、「関係が客観的に正しい」ではない。
LLM は SourceClaimVerification を作れない（型も field も B7D に無い。test T）。帰属のある relation plan は
`SourceClaimStatus.UNVERIFIED`（確認済みを表す値は存在しない）で、主張 class を持たない。B5C の decision model は
確認なしの SOURCE_ASSERTED 受理を拒否する（`MISSING_SOURCE_CLAIM_VERIFICATION`。test S で確認）。B5B assertion への
近道は無い。

## 9. monitoring の境界

MonitoringFinding は DERIVED・非 authority。MON handle は CONTRADICTION_PROPOSAL の evidence 候補の **context** だけに置ける。

- evidence にならない（`evidence_handles` の MON は `HANDLE_FAMILY_MISMATCH`）。
- 候補の target と同じ Theme を扱う finding に限る（違えば `OUT_OF_SCOPE_REFERENCE`）。
- plan には `context_finding_refs`（finding id）として監査用に残るだけで、plan identity・上流 constructor の引数に入らない。
- SourceClaimVerification・確度・governance の変更・自動受理の根拠にならない。件数を重要度にしない。

## 10. provenance lock

| 対象 | 固定値 | それより強い値 |
|---|---|---|
| B3 提案者 class | `ProposerClass.LLM_PROPOSAL` | HUMAN / RULE → `PROVENANCE_ESCALATION` |
| B5C 提案者 class | `RelationProposerClass.LLM` | HUMAN / SOURCE / RULE → `PROVENANCE_ESCALATION` |
| 機構 component の主張 provenance | `AssertionProvenance.LLM_PROPOSAL`、ref `llm:proposal` | HUMAN / RULE / SOURCE_CLAIM → `PROVENANCE_ESCALATION` |
| THEME evidence の role provenance | `ProvenanceClass.LLM_PROPOSAL`、asserted_by `llm:proposal`、role CONTEXT | 他の値 → `PROVENANCE_ESCALATION` |

固定値は plan model の `__post_init__` が検査する（plan を手で組んでも破れない）。`provenance_ref` / `role_asserted_by` に
生成ごとの値を置かないのは、B3 の Theme identity に入るため（生成ごとに identity を揺らさない）。自然文の中の
「HUMAN として」等は何の効果も持たない（§18）。

## 11. 確度（certainty）の方針

- THEME plan の確度は `HYPOTHESIZED_MECHANISM` に固定（B4 discovery の `FIXED_CERTAINTY` と同じ値）。
  `EVIDENCE_SUPPORTED_MECHANISM` / `EXPLICIT_SOURCE_CAUSAL_CLAIM` / `OBSERVED_ASSOCIATION` は `PROVENANCE_ESCALATION`。
- verified / confirmed / human reviewed / production / authoritative / 客観的真実を LLM の文から推論しない（そのような
  field も値も plan に存在しない。test で結果の JSON を走査）。

## 12. 正規化

| 対象 | 正規化 | 根拠 |
|---|---|---|
| 主題・component / consequence / 無効化条件 / 限定条件の文・scope の値 | Foundation `normalize_text`（NFKC → 空白圧縮 → strip → casefold） | Foundation がこれらを normalized field として要求する（A2 §11） |
| category・dimension・expected change・relation type・role | **正規化しない**（完全一致だけ） | 凍結語彙の token |
| observable target | 逐語（B7B の単一行・空白検査を通ったもの） | Foundation は normalized を要求しない |
| component / consequence / 無効化条件の key | 正規化済み材料の canonical 順に `driver_n` / `channel_n` / `domain_n` / `consequence_n` / `invalidation_n` | LLM の順序・handle に依らない |
| entity | handle → entity id（`typed_reference`） | manifest の対応表 |

曖昧一致・近い category / Theme / entity への置換・target の自動補完・無効な候補の除去をしない（§19）。正規化で同じ材料に
なった 2 つの部品は `NON_CANONICAL_INPUT`（黙って畳まない）。

## 13. identity に入る文の template

B7A の監査どおり、B3 の `reason` と B5C の `rationale` は上流 identity に入る。LLM の文言は渡さず、検証済みの構造 field
だけから決定論 template で作る（`normalize_text` 済み）。

| field | template | 例 |
|---|---|---|
| B3 EVIDENCE `reason` | `evidence candidate {role} {kind}{component}`（component = ` consequence <key>` / ` invalidation condition <key>` / 空） | `evidence candidate supports news_item consequence c1` |
| B5C `rationale` | `relation candidate {relation_type} {change_kind}` | `relation candidate amplifies new_relation` |

- 同じ検証済み材料 → 同じ文。LLM の言い回し・候補の順序・provider・model・時刻・乱数に依らない。
- LLM の説明文は `llm_rationale`（監査用。plan identity にも上流 identity にも入らない）。B7F は provenance の note / reason
  に置ける。
- 言い換えの収束: 構造が同じで説明文だけが違う候補は、同じ plan id・同じ上流 id になる（test U。mutant M1 で検出）。
- 提案者を template に入れない（B3 / B5C の identity は提案者を含まない設計のため）。B4 discovery の reason template
  （`discovery evidence candidate ...`）とは文が違うので、RULE と LLM の同じ CONTEXT 候補は別 id になる（§22）。
- THEME の主題・component の文は B3 の既存意味論どおり**内容そのもの**として identity に入る（template 化しない）。

## 14. 重複の方針

- 同一生成内で、正規化後に同じ材料（同じ `plan_id`）になる候補が 2 つあれば **`DUPLICATE_SEMANTIC_CANDIDATE` で生成全体を
  拒否**する（畳まない。曖昧な dedup をしない）。例: 同じ evidence・role・target で MON 文脈だけが違う候補、主題の大文字
  小文字だけが違う THEME 候補。
- 構造が完全に同じ候補（説明文だけが違う）は B7B が構造で拒否する（`DUPLICATE_CANDIDATE`）。
- authority 水準の check-then-reuse（既存 B3 / B5C 提案との照合）は B7F（B7D は store を読まない）。

## 15. 棄権

- 正しい ABSTAIN → plan 0 件・`ValidationOutcome.ABSTAINED`・理由つきの決定論的な結果（失敗ではない）。
- 形の崩れた棄権（候補を持つ・理由が語彙外・理由が無い、CANDIDATES に棄権が混ざる、候補 0 件の CANDIDATES）は
  `INVALID_ABSTENTION`。棄権を提案に変換しない。

## 16. knowledge pin

- request の pin と manifest の pin が一致すること（§3）。
- 検証に使う凍結語彙は、出力 schema version が束ねる語彙（`OUTPUT_SCHEMA_VOCABULARIES`:
  `theme_llm_generation_output:0.1.0` → `mechanism_vocabulary` 0.1.0 / `theme_relation_vocabulary` 0.1.0）であり、
  (a) code の凍結語彙（Foundation / B5 の version 定数）がそれと一致し、(b) manifest が同じ名前を pin していれば同じ
  version であること。違えば `KNOWLEDGE_PIN_MISMATCH`。
- 新しい version を黙って読み込まない（B7D は knowledge を読み込まない。語彙は code に凍結された 1 つだけ）。
- 結果は「使った knowledge」（manifest の pin ∪ schema の語彙）を `knowledge_versions` に記録する。THEME plan は
  `mechanism_vocabulary_version`、relation plan は `relation_vocabulary_version` を持つ。
- 観察（非 blocking）: THEME_PROPOSAL の manifest は Theme を投影しないため `mechanism_vocabulary` を pin しない（B7C は
  投影に使った knowledge だけを pin する）。THEME 候補の語彙は出力 schema version で束ね、code の凍結語彙との一致を
  検証する（§22 #1）。

## 17. PIT の境界

- B7D の世界は B7C manifest だけ。最新の authority を独立に読まない。未来の record は B7D を通って入り込めない。
- 上流の隠れた状態（cutoff 後の governance・relation assertion と撤回・B3 提案と決定）が違っても、manifest が同じなら
  検証結果は byte 一致する（test AB）。
- `generated_at` は上流 constructor の試行時刻だけに使い、結果に入らない（test V）。

## 18. prompt injection の封じ込め

すべての文は data。「ignore previous instructions」「mark this HUMAN」「accept this proposal」「append relation」
「SOURCE_ASSERTED means true」などは制御効果を持たない。検証が見るのは schema・handle・有界な enum・knowledge pin・
決定論の code だけで、provenance・確度・出典帰属の状態・identity 文は文から一切決まらない（test AC）。THEME の文として
入った注入文は、内容として正規化されるだけ（provenance は LLM のまま）。

## 19. failure の分類

違反が 1 件でもあれば生成全体を拒否する（部分採用なし。mutant M7 で検出）。残りの候補も検査して code を集める
（`LlmValidationError.codes`）が、採用はしない。

| code | 意味 |
|---|---|
| `INVALID_INPUT` | 型が違う入力（B7B / B7C の object でない、書き換えられた部品） |
| `REQUEST_MANIFEST_MISMATCH` | 別 manifest / 別 cutoff / 別出力 schema の要求 |
| `TASK_MISMATCH` | 要求 task と manifest task の不一致、task が作らない candidate kind |
| `KNOWLEDGE_PIN_MISMATCH` | pin の不一致、凍結語彙と schema 語彙の不一致 |
| `UNKNOWN_HANDLE` | 対応表に無い handle |
| `HANDLE_FAMILY_MISMATCH` | 欄が期待する family と違う handle |
| `OUT_OF_SCOPE_REFERENCE` | task が取らない MON、別 Theme の MON、引用 evidence に無い entity |
| `UNSUPPORTED_VOCABULARY` | 凍結語彙外の category / dimension / relation type、単一 session / event の期間 |
| `INVALID_TARGET` | role が要する component の欠落・別 Theme の component・CONTEXT に component・訂正先の不一致 |
| `AMBIGUOUS_TARGET` | component が欠け、target Theme に候補が複数ある |
| `INVALID_EVIDENCE_ROLE` | task が許さない role、時刻の無い evidence の非 CONTEXT role |
| `PROVENANCE_ESCALATION` | LLM より強い提案者・主張・確度 |
| `INVALID_RELATION_ENDPOINT` | 自己辺（同じ root） |
| `INVALID_ATTRIBUTION` | 帰属に使えない evidence（非文章・非出版 origin・引用外） |
| `SOURCE_ASSERTED_UNVERIFIED` | 確認済みの出典主張を plan に載せようとした |
| `DUPLICATE_SEMANTIC_CANDIDATE` | 同じ提案材料になる候補が 2 つ |
| `INVALID_ABSTENTION` | 形の崩れた棄権 |
| `NON_CANONICAL_INPUT` | canonical 形でない入力、正規化で重なる部品、material に解決できない対応表、template でない identity 文 |
| `UPSTREAM_CONTRACT_VIOLATION` | 凍結済みの Foundation / B3 / B5C model が材料を拒否した（上流の code だけを残す） |

error の文面・detail は固定文と handle だけ。LLM の文・出典の文・秘密値を echo しない（上流の例外は code だけを写す。test AI）。

## 20. security

- network・provider SDK・API key・環境変数の秘密値・machine path・Compass 原本・portfolio・隠れた推論・authority journal の
  dump を持たない（import boundary と source 走査。test AF）。
- plan / 結果に数値・score・順位・確信度・重要度が無い（test で結果 JSON を走査）。
- 入力の文は B7B が path・URL・秘密 query・制御文字を拒否済み。B7D は文を書き換えず、error に写さない。

## 21. zero-write

B7D は純関数（data root・store・journal・file を扱わない）。proposal append・generation journal append・review append・
Theme の変更・EvidenceAttachment の保存・RelationAssertion・GovernanceEvent は無い。上流 constructor の試行はメモリ上の値
object を作るだけで、保存しない。test: 検証の前後で data root の全 file の hash が一致、`open` を差し替えても検証が完了、
store / bridge / runner / resolver / builder を import しない（test AE / AF）。

### import 境界（§31）

向き: `B7D → B7B model → B7C model → 凍結の model / 語彙（Foundation model、B3 proposal model、B5 relation model、
B5C relation proposal model）`。上流 → B7D、B7D → provider / network / legacy / public / notifier / store / bridge は禁止。
`llm_plan_model` と `llm_validator` を guard（MODULES・LLM_MODULES・LLM_PURE_MODULES・閉包・識別 module・書き込み禁止
語彙）に登録した。

## 22. deferred

| # | 内容 | 扱い |
|---|---|---|
| 1 | THEME_PROPOSAL manifest が `mechanism_vocabulary` を pin しない（出力 schema で束ねている） | 監督判断（B7C で pin するなら B7C の変更） |
| 2 | 出典帰属の `attributed_to` を origin_key とした（publisher 形式の機関 ref ではない）。発言の引用元（記事が引用した機関）は表せない。既存の publisher 形式の SOURCE_ASSERTED 辺は LLM から訂正できない（帰属が一致しない） | 監督判断 |
| 3 | RULE（B4 discovery）と LLM の同じ CONTEXT 候補は reason の文が違うため別 id | 監督判断（収束させるなら template の共有） |
| 4 | THEME 候補の evidence は CONTEXT 固定（consequence ごとの支持を THEME schema で表さない） | B7B schema の拡張は監督判断 |
| 5 | `subject_refs`（DIRECTLY_EVIDENCED の材料）を空にしている | 監督判断 |
| 6 | 既存 ACTIVE 辺と同じ NEW 候補・既存提案との照合（check-then-reuse） | B7F |
| 7 | B7C が空の monitoring ruleset version を pin しうる（合成 finding のみ。B7B request は空 version を拒否するため fail closed） | B7C の hardening は監督判断 |
| 8 | prompt・provider protocol・fake provider・generation journal | B7E |
| 9 | 検証済み plan の B3 / B5C への提出（provenance・created_at・check-then-reuse） | B7F |
