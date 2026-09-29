# PHASE 7 / P7-A1 — NARRATIVE SEMANTICS + PURE MODEL CONTRACT

MODEL ONLY。PIT の組み立て・engine・描画・永続化・LLM・provider・公開出力は実装していない。
module: `src/intelligence/narrative_intelligence/synthesis_model.py`（＋ `__init__.py`）。
test: `tests/intelligence/test_narrative_synthesis_model.py`（matrix A〜AO）・`tests/intelligence/test_narrative_intelligence_boundary.py`
（matrix AP〜AS と Phase 6 の語彙の一致）・`tests/intelligence/phase7_runtime_registry.py`（Phase 7 runtime の登録 helper）。

anchor: P7-A0 freeze `2fe7d0f03c3c8ab2e566508079b788f9e69fcb71`、Phase 6 freeze `5ef313a6a9477f05b4e46756fb8b79c0f0c3d685`。
入る前の基準: 3947 passed / 2 skipped。

**監督判断が必要な事項（実装は推奨どおり。変更は model の語彙の追加・削除だけで済む）**

| id | 事項 | 本 gate の選択 | 理由 |
|---|---|---|---|
| D-P7-A1-1 | 認識 class の数 | **5 つ**（SCENARIO_CONDITION を採用しない） | §5。6 つ目は区別を増やさず、同じ内容の 2 通りの表現と予測への入口を作る |
| D-P7-A1-2 | 解釈の根拠にしてよい governance の位置 | **ACCEPTED だけ** | §7。RETIRED / MERGED / SPLIT / SUPERSEDED は受理を経たとは限らない（Foundation は遷移を制約しない） |
| D-P7-A1-3 | OBSERVED_FACT の evidence | **FACT / OBSERVATION だけ**（時刻の質は RELIABLE / DECLARED） | §5。文書・報道・発言の内容は出典の主張で、事実ではない |
| D-P7-A1-4 | 代替の説明の出所 | **同じ evidence を SUPPORTS として持つ reviewed Theme の並び**だけ | §12。A0 §12 の方針。未審査の提案は延期（§25） |
| D-P7-A1-5 | Phase 6 の凍結 test への登録 | **8 file に test-only の登録**（runtime 変更なし） | §23。Phase 6 の凍結 guard が HEAD の `src` 全体を固定していたため |

---

## 1. 目的

reviewed（L2）Theme について、caller が与えた cutoff の時点で「何が・なぜ・何が変わり・何とつながり・何が根拠で・何が
不確かで・何で崩れるか」を、**自由文を持たない構造化された claim の集合**として表す純 model を定める。後続の A2（PIT の
組み立て）・A3（engine）・A4（描画・変化・適格性）は、この model を作る・読むだけで、意味を足さない。

§3 の 7 つの問いへの構造上の対応:

| 問い | 構造 |
|---|---|
| WHAT | claim kind `STATE`（`THEME_REVIEWED_STATE`） |
| WHY | claim kind `MECHANISM`（`RECORDS_MECHANISM_COMPONENT`）と代替（`ALTERNATIVE_EXPLANATIONS_OF_SHARED_EVIDENCE`） |
| CHANGE | claim kind `CHANGE`（`CHANGED_BETWEEN_CUTOFFS`） |
| RELATIONS | claim kind `RELATION`（`HUMAN_ASSERTED_RELATION`・`SOURCE_ASSERTED_RELATION`） |
| EVIDENCE | claim kind `EVIDENCE`（`EVIDENCE_ATTACHED`・`EVIDENCE_ITEM_OBSERVED`） |
| UNCERTAINTY | 認識 class `UNCERTAINTY`（`IS_UNCERTAIN` ＋ 閉じた code） |
| INVALIDATION | claim kind `INVALIDATION`（`RECORDS_INVALIDATION_CONDITION`・`INVALIDATING_EVIDENCE_ATTACHED`） |

## 2. 非目標

- PIT assembler・Theme store の読み取り・engine・renderer・文章生成・template・日本語の表示文。
- 永続化（journal・file・DB）・運用 metadata（生成時刻・run id）。
- LLM・provider・network・公開出力・通知・P4 の公開経路・P8 との接続。
- 予測・推奨・売買 signal・順位・score・確信度・受益者の判定。
- Phase 6 の runtime の変更（0 行）。P4 / P5 / Production DNA（`market_rules.yaml`・`market_principles.py`）の変更。

## 3. authority の分類

`NarrativeSynthesis` と `NarrativeClaim` は **DERIVED / NON-AUTHORITY / NON-PERSISTENT**。

- fact・Theme・governance の authority ではない。Production DNA・予測・推奨・売買 signal ではない。
- 何も保存しない。同じ入力からいつでも再構成できる派生物（A0 の D-P7-1 の C。journal は初期なし）。
- 凍結文言（test で固定）: `SYNTHESIS_IS_NOT_AUTHORITY` = "a narrative synthesis is a derived, non-authoritative,
  non-persistent reading of reviewed themes; never a fact, theme or governance authority, a prediction, a recommendation
  or a trading signal"。

## 4. 型（kind）

`NarrativeKind` は `THEME_STATE`・`THEME_SET` の 2 つだけ。それ以外（`MARKET_STATE`・`EVIDENCE_LINKED`・`SCENARIO_NARRATIVE`・
`RISK_NARRATIVE`・小文字・空）は `UNKNOWN_NARRATIVE_KIND` で拒否する（fail closed）。

## 5. 認識 class（epistemic class）

監査（§4 の要求: 6 つの区別を保てる最小の集合）:

| 候補 | 採否 | 守る区別 |
|---|---|---|
| OBSERVED_FACT | 採用 | 観測そのもの（evidence item が cutoff までに観測された）。解釈と混ぜない |
| REVIEWED_INTERPRETATION | 採用 | reviewed Theme ／ relation authority に記録された解釈（状態・機構・role・relation・無効化条件） |
| DERIVED_SYNTHESIS | 採用 | 決定論の code が authority から計算したこと（B1 の変化） |
| UNCERTAINTY | 採用 | 閉じた code で示す欠落・争い・仮説のまま |
| ALTERNATIVE_HYPOTHESIS | 採用 | 並べるだけの代替の説明（勝者なし） |
| SCENARIO_CONDITION | **不採用** | 下記 |

SCENARIO_CONDITION を採用しない理由:

1. A1 で条件として現れるのは Theme に記録された**無効化条件**だけで、それは reviewed Theme の解釈（REVIEWED_INTERPRETATION）で
   あり、claim kind `INVALIDATION` と predicate `RECORDS_INVALIDATION_CONDITION` が「条件の記録であって、起きたことではない」を
   構造で表す。無効化 evidence も `INVALIDATING_EVIDENCE_ATTACHED` で「attachment がある」とだけ表す（§13）。
2. 将来の分岐（scenario）は予測であり、A0 §7 で範囲外（SCENARIO_NARRATIVE）。referent が無い class は、同じ内容を 2 通りに
   書ける曖昧さ（identity の重複、§18）と予測への入口だけを作る。
3. 入力に `SCENARIO_CONDITION` が現れたら `EPISTEMIC_CLASS_NOT_ADOPTED` で拒否する（黙って別の class にしない）。採用するなら
   schema version を上げる語彙の追加になる（D-P7-A1-1）。

規則: 事実と解釈を 1 つの claim に混ぜない。数値の確信度・順位を持たない。class は claim の生成時に決まり、格上げ
（解釈 → 事実、仮説 → 解釈）は model に存在しない。OBSERVED_FACT は FACT / OBSERVATION の evidence item だけ（D-P7-A1-3）。

## 6. claim kind

claim kind は「**何について**」、認識 class は「**どう知っているか**」。2 つは別の enum で、値は重ならない（test O）。

`ClaimKind` = STATE / MECHANISM / EVIDENCE / CHANGE / RELATION / INVALIDATION。

許される (class, kind, predicate) の組は次の 12 だけ（`ALLOWED_TRIPLES`。他のすべての組は `EPISTEMIC_CLASS_MISMATCH` か
`CLAIM_KIND_MISMATCH`。318 通りを test で総当たり）:

| predicate | class | kind | ref の形 |
|---|---|---|---|
| THEME_REVIEWED_STATE | REVIEWED_INTERPRETATION | STATE | ThemeObservationRef ×1 |
| RECORDS_MECHANISM_COMPONENT | REVIEWED_INTERPRETATION | MECHANISM | MechanismComponentRef ×1 |
| EVIDENCE_ATTACHED | REVIEWED_INTERPRETATION | EVIDENCE | EvidenceAttachmentRef ×1 |
| EVIDENCE_ITEM_OBSERVED | OBSERVED_FACT | EVIDENCE | EvidenceItemRef ×1（FACT / OBSERVATION） |
| CHANGED_BETWEEN_CUTOFFS | DERIVED_SYNTHESIS | CHANGE | ThemeChangeRef ×1 |
| HUMAN_ASSERTED_RELATION | REVIEWED_INTERPRETATION | RELATION | RelationAssertionRef（HUMAN_ASSERTED）×1 ＋ 両端の ThemeObservationRef ×2 |
| SOURCE_ASSERTED_RELATION | REVIEWED_INTERPRETATION | RELATION | RelationAssertionRef（SOURCE_ASSERTED）×1 ＋ 両端の ThemeObservationRef ×2 |
| RECORDS_INVALIDATION_CONDITION | REVIEWED_INTERPRETATION | INVALIDATION | InvalidationConditionRef ×1 |
| INVALIDATING_EVIDENCE_ATTACHED | REVIEWED_INTERPRETATION | INVALIDATION | InvalidationConditionRef ×1 ＋ INVALIDATES の EvidenceAttachmentRef ×1 |
| ALTERNATIVE_EXPLANATIONS_OF_SHARED_EVIDENCE | ALTERNATIVE_HYPOTHESIS | MECHANISM | Theme ごとに ThemeObservationRef ＋ EvidenceAttachmentRef（2 Theme 以上） |
| IS_UNCERTAIN | UNCERTAINTY | EVIDENCE | code 別（§11） |
| IS_UNCERTAIN | UNCERTAINTY | MECHANISM | code 別（§11） |

## 7. reference model

ref は**型付きの opaque な参照**で、id と閉じた語彙と時刻だけを持つ。store を読まない。path・URL・raw JSON・本文・抜粋・
note・locator を持たない。7 型:

| 型 | field | 意味 |
|---|---|---|
| ThemeObservationRef | root_id, observation_id, governance_position, mechanism_certainty | cutoff で見える reviewed observation。確度 class は表示のための attribution |
| MechanismComponentRef | root_id, observation_id, component_type, component_key | 記録された機構 component |
| InvalidationConditionRef | root_id, observation_id, condition_key | 記録された無効化条件（参照だけ） |
| EvidenceAttachmentRef | root_id, observation_id, ref_id, evidence_kind, consequence_key, role, role_provenance, attached_at, invalidation_condition_key | Theme ↔ evidence の解釈上の結び付き。`attachment_key` = `ref_id#consequence_key`（Foundation と同じ） |
| EvidenceItemRef | ref_id, evidence_kind, evidence_time, time_quality | 観測された evidence item そのもの（Theme との結び付きを持たない） |
| ThemeChangeRef | root_id, from_cutoff, to_cutoff, change_kind, facet, subject_id | B1 の変化の項目（before / after / detail の本文を持たない） |
| RelationAssertionRef | relation_assertion_id, source_root_id, target_root_id, relation_type, assertion_class | B5B の直接の辺 |

形式（Phase 6 と同じ。一致を test で固定）: root `theme_<ULID 26>`、observation `thobs_<24hex>`、relation `threl_<24hex>`、
key `^[a-z0-9][a-z0-9_.:-]{0,63}$`、evidence ref は kind 別の prefix（`fact_`・`obs_`・`doc_`・`news_`・STATEMENT は prefix なし）と
200 文字以内、facet は B1 の FACET_ORDER と `metadata:<FIELD>`。

**reviewed の天井（§8）**: `governance_position` は `REVIEWED_POSITIONS` = (ACCEPTED,) だけ。他の 8 値は `THEME_NOT_REVIEWED`
（D-P7-A1-2）。synthesis 内で参照される Theme はすべて、その synthesis の中に ThemeObservationRef を持たなければならない
（`UNREVIEWED_THEME_REFERENCE`）。

**model に存在しない ref の型**（`PROHIBITED_REF_TYPE`）: THEME_PROPOSAL・EVIDENCE_PROPOSAL・RELATION_PROPOSAL・
PROPOSAL_DECISION・DISCOVERY_HIT（B3 / B4 / B5C の未審査）、MONITORING_FINDING・REVIEW_ITEM_STATE（B6）、LLM_PROPOSAL・
LLM_GENERATION・LLM_OUTPUT（B7）、PREDICTION・EVALUATION・CALIBRATION（P5）、COMPASS_DRAFT・MARKET_SIGNAL（P4 の生成物）、
FORMAL_REVIEW・CORPUS_DOCUMENT・CORPUS_RESEARCH・DECISION・THESIS・SCREENING・PERSONALIZATION・REPLAY（履歴 branch）、RAW_PATH・
URL・RAW_JSON。**延期**（`REF_TYPE_DEFERRED`）: DNA_RULE・P4_FACT・P4_CONTEXT・P4_INTERNALS・THEME_LIMITATION・THEME_LINEAGE・
UNREVIEWED_CONTEXT。

## 8. evidence の role

`EvidenceRole` = SUPPORTS / CONTRADICTS / CONTEXT / INVALIDATES（Foundation の複製）。

- role は ref が運ぶだけで、model は書き換えない。同じ attachment（root・observation・attachment_key）が別の role で引用
  されたら `EVIDENCE_ROLE_RELABELLED`、他の属性（provenance 等）が違えば `REF_INCONSISTENT`。
- 異なる Theme は同じ evidence item に異なる role を持ってよい（それぞれの記録のまま）。
- `role_provenance`（HUMAN / RULE / LLM_PROPOSAL）は常に保持する（A0 §9 規則 6）。
- INVALIDATES ⇔ `invalidation_condition_key` が空でない（`INVALIDATION_CONDITION_REQUIRED`・
  `INVALIDATION_CONDITION_ONLY_FOR_INVALIDATES`）。
- 支持と反証が同じ Theme に引用されたら、CONTESTED_EVIDENCE の不確実性 claim が必須（§11）。

## 9. relation の意味論

- relation claim は **B5B の直接の辺 1 本**（RelationAssertionRef ちょうど 1）と、その両端の reviewed observation だけ。
  2 本以上の辺を 1 つの claim に入れられない（経路・推移辺を作れない。`REF_SHAPE_INVALID`）。
- 端点の組が relation の端点と一致しなければ `RELATION_ENDPOINTS_REQUIRED`。自己 relation は `SELF_RELATION`。
- relation claim は少なくとも 1 端が subject でなければならない（`RELATION_OUTSIDE_SUBJECTS`）。
- 中心性・次数・経路・重要度の語彙と field は存在しない。隠れた因果を作らない（`RelationType` の CAUSES 等は記録された
  assertion の型で、Narrative の主張ではない）。
- **共同の発見・evidence の共有は relation ではない**: 共有 evidence は ALTERNATIVE の claim（kind MECHANISM）にしかならず、
  RELATION の claim は RelationAssertionRef を必須とする。
- 撤回・現役の判定は A2 の責務（ref は cutoff で ACTIVE な辺を指す。§26）。

## 10. SOURCE_ASSERTED

- SOURCE_ASSERTED の assertion は `SOURCE_ASSERTED_RELATION` でしか引用できない。HUMAN_ASSERTED は `HUMAN_ASSERTED_RELATION`
  だけ（`ASSERTION_CLASS_MISMATCH`）。
- class は REVIEWED_INTERPRETATION（出典が主張したことを人間の relation authority が記録した、という解釈）で、
  OBSERVED_FACT にはならない。
- 意味は固定文言 `SOURCE_ASSERTED_MEANING` = "a source asserted this relation; the narrative does not assert it"。
  描画（A4）はこの文言の意味を超えない。

## 11. 不確実性

`UncertaintyCode`（確率ではない。閉じた 5 値）:

| code | kind | ref | 構造の検査 |
|---|---|---|---|
| NO_SUPPORTING_EVIDENCE | EVIDENCE | ThemeObservationRef ×1 | 同じ Theme の SUPPORTS が引用されていたら `UNCERTAINTY_CONTRADICTS_REFS` |
| SINGLE_SOURCE_EVIDENCE | EVIDENCE | ThemeObservationRef ×1 | （B2 の flag から A2 が導く） |
| STALE_EVIDENCE | EVIDENCE | ThemeObservationRef ×1 | （B2 の flag から A2 が導く） |
| CONTESTED_EVIDENCE | EVIDENCE | ThemeObservationRef ×1 ＋ 同じ Theme の SUPPORTS と CONTRADICTS の attachment | role の組が {SUPPORTS, CONTRADICTS} でなければ拒否 |
| MECHANISM_HYPOTHESIZED | MECHANISM | ThemeObservationRef ×1 | 確度が HYPOTHESIZED_MECHANISM でなければ拒否 |

隠さない規則（synthesis の検査）: 支持と反証が並ぶ Theme には CONTESTED_EVIDENCE が必須（`CONTESTED_EVIDENCE_NOT_SURFACED`）。
確度が仮説の Theme の機構を語るなら MECHANISM_HYPOTHESIZED が必須（`HYPOTHESIZED_MECHANISM_NOT_SURFACED`）。
code は IS_UNCERTAIN にだけ必須で、他の predicate には置けない。

## 12. 代替の説明

- `ALTERNATIVE_EXPLANATIONS_OF_SHARED_EVIDENCE`: 同じ evidence item（同じ `ref_id`）を **SUPPORTS** として持つ 2 つ以上の
  reviewed Theme を、Theme ごとに observation と attachment の組で並べる（A0 §12、D-P7-A1-4）。
- 勝者・順位・主役・重みの field は無い。並びは非意味的な集合で、並べ替えても claim id は同じ。
- role は書き換えない: CONTRADICTS 等の attachment は代替にならない（`ALTERNATIVES_REQUIRE_SUPPORTS`）。
- 1 Theme 1 attachment（`ALTERNATIVE_DUPLICATE_THEME`）、共有 evidence（`ALTERNATIVES_REQUIRE_SHARED_EVIDENCE`）、observation と
  attachment の Theme の一致（`ALTERNATIVE_THEMES_MISMATCH`）、少なくとも 1 つが subject（`ALTERNATIVE_OUTSIDE_SUBJECTS`）。
- 未審査の提案を代替として出す lane は延期（§25）。

## 13. 無効化

- 条件と ref だけを表し、評価・実行しない。「無効になった」「反証された」の predicate は存在しない（test S）。
- `RECORDS_INVALIDATION_CONDITION`: reviewed Theme に条件が記録されている。
- `INVALIDATING_EVIDENCE_ATTACHED`: INVALIDATES の attachment が、同じ Theme・observation の同じ条件に向いている
  （`INVALIDATION_EVIDENCE_MISMATCH`）。
- 隠さない規則: INVALIDATES の attachment をどこかで引用したら、その attachment の `INVALIDATING_EVIDENCE_ATTACHED` が必須
  （`INVALIDATION_EVIDENCE_NOT_SURFACED`）。`INVALIDATING_EVIDENCE_ATTACHED` にはその条件の `RECORDS_INVALIDATION_CONDITION` が必須
  （`INVALIDATION_CONDITION_NOT_RECORDED`）。退役は人間の governance（Narrative は決めない）。

## 14. NarrativeClaim

不変の dataclass。field は `epistemic_class`・`claim_kind`・`predicate`・`refs`・`uncertainty_code`・`claim_id`（導出）だけ。
自由文・数値・順位・確信度・生成時刻を持たない。

構築時の検査順: 不採用 class → class・kind・predicate の語彙 → predicate の署名（class・kind）→ 不確実性 code →
refs の型・件数（1〜16）・重複 → predicate 別の ref の形と意味の guard。refs は canonical な順に並べ替える（非意味的な集合の
正規化。重複の除去はしない）。

§22 の guard: OBSERVED_FACT が Theme の解釈だけを引用したら `FACT_CITES_ONLY_INTERPRETATION`。文書・報道・発言は
`FACT_REQUIRES_OBSERVATIONAL_EVIDENCE`、推定の時刻は `FACT_TIME_NOT_ESTABLISHED`。ALTERNATIVE と UNCERTAINTY は OBSERVED_FACT に
なれない（署名の表）。RELATION の claim は relation ref（`RELATION_REF_REQUIRED`）、INVALIDATION の claim は無効化条件の ref
（`INVALIDATION_REF_REQUIRED`）が必須。

## 15. NarrativeSynthesis

field は最小: `kind`・`subject_root_ids`・`cutoff`・`knowledge_pins`・`input_digest`・`claims`・`synthesis_id`（導出）。

- `cutoff`: aware な datetime（caller が与える。暗黙の now / latest なし）。
- `knowledge_pins`: 空でない (name, version) の集合（name `^[a-z][a-z0-9_]{0,63}$`、version `n.n.n`、name は一意、上限 16）。
- `input_digest`: A2 が作る PIT 入力の content id の形（`^[a-z][a-z0-9]{1,15}_[0-9a-f]{24}$`）。
- `claims`: 1〜256、claim id で一意。
- `narrative_key`（property。保存しない）: 型と subject の組だけの content id（同じ問い。cutoff・入力・claim に依らない）。

synthesis の検査（`_check_synthesis`）: PIT（§21）・1 Theme 1 observation・同じ identity の ref の一致（role の書き換え
なし）・reviewed の閉包・subject の範囲（relation と代替以外の claim は subject だけを語る。`CLAIM_OUTSIDE_SUBJECTS`）・
subject ごとの `THEME_REVIEWED_STATE`（`SUBJECT_STATE_REQUIRED`）・事実は subject に attachment された evidence だけ
（`ORPHAN_OBSERVED_FACT`）・§11 と §13 の隠さない規則。

## 16. THEME_STATE

subject はちょうど 1 つの reviewed Theme root（`THEME_STATE_REQUIRES_ONE_SUBJECT`）。他の Theme は relation の端点と代替の
並びにだけ現れ、それらも synthesis の中で reviewed の observation を持つ。

## 17. THEME_SET

subject は 2 つ以上 16 以下の一意な reviewed Theme root（`THEME_SET_REQUIRES_TWO_OR_MORE_SUBJECTS`・`DUPLICATE_SUBJECT`・
`TOO_MANY_SUBJECTS`）。subject は id 順の非意味的な集合で、順位・主役（dominant）・勝者・受益者の field も predicate も無い。
各 subject に `THEME_REVIEWED_STATE` が必須。

## 18. identity

- `claim_id` = `content_id("narclm", canonical_json({schema_version, epistemic_class, claim_kind, predicate, uncertainty_code,
  refs[canonical 順]}))`。
- `synthesis_id` = `content_id("narsyn", canonical_json({schema_version, kind, subject_root_ids[順], cutoff(UTC ISO),
  knowledge_pins[name 順], input_digest, claim_ids[順]}))`。
- 運用 metadata（生成時刻・run id・記録時刻）は field として存在せず、直列化に現れたら `PROHIBITED_FIELD`。したがって
  identity を変えられない。時計・乱数・UUID・ULID（`new_id` / `new_ulid`）を使わない（`content_id` だけ）。
- 非意味的な順序（subject・claim・ref・pin）は id を変えない（test Y）。意味の変化（cutoff・digest・pin・claim）は id を変える
  （test Z）。fuzzy な一致はしない（大小文字・空白・別表記は正規化せず拒否。test AC）。
- 別 process・別 `PYTHONHASHSEED` でも byte 一致（test AB）。

## 19. 順序

| list | 分類 | 扱い |
|---|---|---|
| `NarrativeSynthesis.subject_root_ids` | 非意味的な集合 | id 順に正規化。順位ではない |
| `NarrativeSynthesis.claims` | 非意味的な集合 | claim id 順に正規化。表示順は A4 の責務で、model は持たない |
| `NarrativeClaim.refs` | 非意味的な集合 | ref の canonical JSON 順に正規化 |
| `NarrativeSynthesis.knowledge_pins` | 非意味的な集合 | name 順に正規化 |
| 代替の Theme の並び | 非意味的な集合 | refs の一部として正規化（勝者なし） |

意味的な順序を持つ list は A1 に存在しない（機構の段は `component_type`、変化の窓は from < to の 2 つの field で表す）。
正規化は並べ替えだけで、重複の除去・切り詰めはしない。直列化の復元では非 canonical な順を拒否する（§22）。

## 20. text policy

- A1 の model は**自由文の field を 1 つも持たない**（statement・note・excerpt・locator・title・summary 等は無い）。
- すべての文字列は id か閉じた語彙か有界な token（正規表現で完全一致）: markdown・HTML・URL・path・空白・改行・
  `?key=` の類・backtick は通らない（test AN）。
- 表示の文章（日本語の閉じた template）は A4 の責務で、model の意味（§5・§10・§13）を超えない。

## 21. 検査（validation）

strict・fail closed・黙った修復なし。`NarrativeModelError(code, detail)` の code は安定した語彙で、detail は field 名だけ
（入力値を載せない。test AO）。

- PIT: `attached_at`・`evidence_time`・`to_cutoff` は cutoff 以下（ちょうどは可）。超えたら `REF_AFTER_CUTOFF`。
  `from_cutoff < to_cutoff`（`CHANGE_WINDOW_INVALID`）。naive な時刻は `NAIVE_DATETIME`、datetime 以外は `INVALID_TYPE`。
- 未知の語彙はすべて専用の `UNKNOWN_*`。重複は `DUPLICATE_*`（除去しない）。上限は `*_OUT_OF_BOUNDS` ／ `TOO_MANY_SUBJECTS`
  （切り詰めない）。
- model の instance 以外の claim ／ ref（dict・文字列・path）は `INVALID_CLAIM` ／ `INVALID_REF`。

test matrix: A〜B 正しい型、C〜D 件数、E〜F 順位・確信度なし、G〜I 予測・monitoring・B7 の ref なしと reviewed の天井、
J〜P 認識の guard、Q〜U role の保持・書き換えなし・無効化・争い・代替、V〜W SOURCE_ASSERTED と relation、X〜AC identity と決定論、
AD〜AJ 厳格な検査、AK〜AO 直列化・text policy・機密、AP〜AS 境界。scratch の mutation 15 件（事実 guard・天井・relabel・
争い・PIT・claim id・subject の順・assertion class・canonical・禁止 field・孤立した事実・報道の事実化・仮説の隠蔽・無効化の隠蔽・
reviewed の閉包）はすべて model test で検出された。

## 22. 直列化

- `to_dict()` ／ `to_canonical_json()`: JSON 互換（文字列・list・dict・null だけ。数値なし）。canonical JSON は
  sort_keys・compact separators・ensure_ascii=False（Phase 6 と同じ形）。時刻は UTC の ISO 8601。
- `from_dict()`: 禁止 field（`PROHIBITED_FIELD`）→ 未知 field（`UNKNOWN_FIELD`）→ 欠落（`MISSING_FIELD`）の順に検査。型違い
  （数値・真偽値・null）は `INVALID_TYPE`。schema version の不一致は `UNSUPPORTED_SCHEMA_VERSION`。ref の型の食い違いは
  `REF_TYPE_MISMATCH`。非 canonical な時刻は `NON_CANONICAL_DATETIME`。claim ／ synthesis の id の不一致は `CLAIM_ID_MISMATCH` ／
  `SYNTHESIS_ID_MISMATCH`。再直列化が入力と一致しなければ `NON_CANONICAL_SERIALIZATION`。
- `from_json()`: 重複 key（`DUPLICATE_JSON_KEY`）・不正な JSON（`INVALID_JSON`）・非 canonical な text を拒否。往復は byte 一致
  （test AK）。
- schema version: `narrative_synthesis:0.1.0`・`narrative_claim:0.1.0`。

## 23. import 境界

- runtime の import は標準 library（json・re・dataclasses・datetime・enum・typing）と `core.ids`（`content_id`）・`core.time`
  （`from_iso`・`to_utc_iso`）だけ。runtime closure は `src`・`src.intelligence`・`core`・`core.ids`・`core.time`・本 package だけ
  （test AP）。
- Phase 6 を import しない（Phase 6 completion の凍結 guard が Phase 6 の外からの import を禁じている）。Phase 6 の語彙
  （GovernanceLifecycleState・MechanismCertainty・ComponentType・EvidenceKind・EvidenceRole・ProvenanceClass・
  EvidenceTimeQuality・RelationType・AssertionClass・ChangeKind・FACET_ORDER・ref prefix・id と key の形式）は複製して持ち、
  一致は test が Phase 6 を import して固定する。Phase 6 の fixture が作る reviewed observation の値がそのまま ref に写せることも
  test で確かめた。
- legacy・predictions・P4（compass・reports・facts・context・internals）・P5・provider・notifier・公開・売買の import なし。
  P4 の名前（`NarrativePlan`・`NarrativeGenerator` 等）を使わない。
- 上流（main・`src` の他の package・scripts）は本 package を import しない（test AR）。production bundle の閉包に含まれない
  （test AS）。

**Phase 6 の test への test-only の登録（§35 の報告。runtime 変更 0 行）**: Phase 6 の凍結 guard 8 file は「HEAD までに
`src` 全体が変わっていない」ことを固定していたため、`src` の下に package を足すだけで失敗する。そこで Phase 7 の登録 helper
（`tests/intelligence/phase7_runtime_registry.py`）に**登録した file の追加だけ**を宣言し、各 guard に 1〜2 行を入れた:

| file | 登録 |
|---|---|
| `test_theme_phase6_completion.py` | import ＋ `SURFACE += PHASE7_EXCLUDED_PATHSPECS` |
| `test_theme_llm_closeout.py` | import ＋ `SURFACE += PHASE7_EXCLUDED_PATHSPECS` ＋ B6 の pin を「B7C anchor ＋ 宣言した登録の行だけ」に（2 行） |
| `test_theme_llm_adversarial_e2e.py`・`test_theme_llm_generation.py`・`test_theme_llm_submission.py`・`test_theme_llm_validator.py` | import ＋ `surface += PHASE7_EXCLUDED_PATHSPECS` |
| `test_theme_monitoring_coverage_rerun.py` | import ＋ `RUNTIME_SURFACE += PHASE7_EXCLUDED_PATHSPECS` |
| `test_theme_monitoring_e2e_rerun.py` | import ＋ 登録済みの追加だけを除く 1 行 |

- 除外は git の literal な pathspec で**登録 file の完全 path だけ**。未登録の file（同じ package の別 module を含む）は今までどおり
  失敗する（`extra_probe.py` を stage して 5 つの guard が失敗することを確かめ、probe は削除した）。
- `is_phase7_addition` は A / ?? だけを認め、M / D / R 等・別 path・subdirectory・Phase 6 の path を認めない。
- Phase 7 の guard は、8 file の Phase 6 completion anchor との差分が `PHASE6_TEST_REGISTRATION` の宣言（取り除いた行・加えた行）と
  完全に一致することを確かめる。B7 closeout の B6 pin は同じ helper で「B7C anchor ＋ 宣言した行だけ」を確かめる（登録していない
  pin file は従来どおり byte 一致）。

## 24. security

- 秘密値・credential・API key を持たない・求めない。`api_key`・`token`・`secret` は拒否する field 名の語彙として現れるだけ
  （test AQ）。
- 機密の資料（Compass の PDF・本文・抜粋・locator・note・人間の review 理由）を運ぶ field が無い。直列化に現れたら
  `PROHIBITED_FIELD`（test AO）。
- エラーは入力値を反映しない（canary で確認）。URL・path の定数を持たない。filesystem・network・時計・乱数・動的実行を使わない
  （AST で検査）。machine 固有の path を書かない。

## 25. 延期の項目

| id | 項目 | 次の判断 |
|---|---|---|
| P7-A1-DEF-01 | SCENARIO_CONDITION の採否 | D-P7-A1-1 |
| P7-A1-DEF-02 | RETIRED / MERGED / SPLIT / SUPERSEDED の Theme の narrative（lineage ref を含む） | D-P7-A1-2 と A2 以降 |
| P7-A1-DEF-03 | 未審査の文脈の lane（B3 / B5C の提案・B4 hit・B6 finding の契機） | A0 D-P7-10 / D-P7-11 |
| P7-A1-DEF-04 | DNA の `rule_ref`（opaque な引用） | A0 D-P7-8 |
| P7-A1-DEF-05 | P4 の Fact / Context / Internals の文脈 ref | A0 D-P7-8 |
| P7-A1-DEF-06 | Theme の limitation（DATA_GAP・CONFOUNDER 等）の不確実性 ref | A2 |
| P7-A1-DEF-07 | 入力が無いこと（MISSING_INPUT 系）の不確実性 code | A2（PIT の欠落の表し方と一緒に） |
| P7-A1-DEF-08 | B2 の flag を構造で検証する（SINGLE_SOURCE・STALE） | A2（resolution を読む側で導く） |
| P7-A1-DEF-09 | relation の辺が cutoff で ACTIVE であることの検証 | A2 |
| P7-A1-DEF-10 | 表示順・日本語の template・`display_text` | A4 |
| P7-A1-DEF-11 | NarrativeChange（2 つの synthesis の差） | A4 |
| P7-A1-DEF-12 | 運用 journal | A0 D-P7-13（統合 gate） |
| P7-A1-DEF-13 | P6-DEF-31（B2 文書の REOPENED → ACCEPTED の文言） | A0 D-P7-15（model は ACCEPTED だけを使い、影響しない） |

## 26. A2 への引き継ぎ

A2（PIT assembler）は Phase 6 の read-only 入口（`resolve_at_data_root`・`compare_resolutions` / `detect_changes`・
`derive_lifecycle`・`resolve_relations_at_data_root`・`build_relation_graph_view`）を明示の cutoff と明示の scope で読み、
この model の ref と claim を作る。A2 の義務:

1. subject は caller の明示の要求で決める（暗黙の列挙なし）。subject と参照する Theme は cutoff で lifecycle が ACCEPTED の
   ものだけ。それ以外は ref にしない（model が `THEME_NOT_REVIEWED` で拒否する）。
2. 1 Theme につき cutoff で解決した 1 observation。ThemeObservationRef の確度は observation の `certainty_class` をそのまま写す。
3. attachment は Foundation の値をそのまま写す（role・provenance・`consequence_ref` → `consequence_key`・
   `invalidation_condition_ref` → `invalidation_condition_key`）。書き換え・推定をしない。
4. OBSERVED_FACT は FACT / OBSERVATION で時刻の質が RELIABLE / DECLARED の evidence item だけ。
5. relation は cutoff で ACTIVE な B5B の直接の辺だけ。SOURCE_ASSERTED は SOURCE_ASSERTED_RELATION で。
6. 変化は B1 の項目の kind・facet・subject_id だけを写し、before / after / detail の本文を入れない。
7. B2 の flag から NO_SUPPORTING / SINGLE_SOURCE / STALE を導く。支持と反証・仮説の機構・無効化 evidence は model の隠さない規則が
   強制する。
8. `input_digest` は PIT 入力（cutoff・scope・読んだ authority の digest・knowledge の version）の content id。`knowledge_pins` は
   読んだ語彙と resolver の version。
9. 壊れた authority は synthesis 全体を止める（integrity-before-PIT。黙って空にしない）。
10. Phase 6 を import する A2 の module は Phase 6 completion の凍結 guard（Phase 6 の外からの import の禁止）に当たる。A2 では
    その guard への test-only の登録（本契約 §23 と同じ形）か、監督判断が要る。
11. 新しい runtime file は `phase7_runtime_registry.PHASE7_RUNTIME` への登録が要る（登録しなければ Phase 6 の凍結 guard が失敗する）。
