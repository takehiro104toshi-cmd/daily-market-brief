# PHASE 7 / P7-A3 — DETERMINISTIC NARRATIVE SYNTHESIS ENGINE CONTRACT（STRUCTURED CLAIMS ONLY / NO PROSE / NO LLM）

A3 は A2 の `NarrativeInputSnapshot` から A1 の `NarrativeSynthesis` を作る**純関数**だけを持つ。文章・描画・LLM・provider・
永続化・authority の変更は無い。
module: `src/intelligence/narrative_intelligence/synthesis_engine.py`。
test: `tests/intelligence/test_narrative_synthesis_engine.py`（matrix A〜BN）・`tests/intelligence/test_narrative_intelligence_boundary.py`
（A3 の import 許可一覧・runtime closure・A2 の byte 凍結・未登録 runtime の検出を追加）・`tests/intelligence/phase7_runtime_registry.py`
（`synthesis_engine.py` を登録）。

anchor: P7-A2 freeze `2dfd85c757d96b3b546f6723f88d70b94a191f97`、P7-A1 freeze `a02ad60878054b5846b11acac720fa2811f32505`、
P7-A0 freeze `2fe7d0f03c3c8ab2e566508079b788f9e69fcb71`、Phase 6 freeze `5ef313a6a9477f05b4e46756fb8b79c0f0c3d685`。
入る前の基準: 4592 passed / 2 skipped。

**本 gate の設計判断（監督の確認を求める）**

| id | 事項 | 選択 |
|---|---|---|
| D-P7-A3-1 | CONTEXT の見せ方 | A1 の `EVIDENCE_ATTACHED` は role を ref に持つので、CONTEXT の attachment も **role CONTEXT のまま** claim にする（SUPPORTS にしない。A1 を変えない）（§12） |
| D-P7-A3-2 | 代替の説明 | A1 の既定どおり、**同じ `ref_id` を SUPPORTS として持つ 2 つ以上の subject Theme** があるときだけ（THEME_SET だけ。完全一致。類似・推測なし）（§15） |
| D-P7-A3-3 | 規則表の version | A1 の既存の `knowledge_pins` に `("narrative_synthesis_rules", "0.1.0")` を足す（A1 の field を増やさない）（§22） |
| D-P7-A3-4 | snapshot の provenance | A1 の既存の `input_digest` ＝ A2 の `snapshot_id`（§22） |
| D-P7-A3-5 | NO_SUPPORTING_EVIDENCE の抑止 | B2 の NO_VISIBLE_EVIDENCE があっても、SUPPORTS の attachment が 1 つでも投影されていれば作らない（A1 が矛盾として拒否する組み合わせ。数えられない支持は B2 の判断で、A3 は決めない）（§14） |

A1 ／ A2 の変更は不要だった（`P7_A1_REMEDIATION_REQUIRED` ／ `P7_A2_REMEDIATION_REQUIRED` の条件に当たらない）。

---

## 1. 目的

「この PIT snapshot**だけ**から、どの構造化された説明の claim が正当化されるか」に答える。答えないもの（凍結文言
`SYNTHESIS_ENGINE_DOES_NOT_ANSWER`）: 読み手への書き方・最も重要な Theme・次に何が起きるか・何を買うか・どの説明が勝つか。

```
NarrativeInputSnapshot（A2・凍結）→ 再検証 → 規則表（R01〜R14）→ 収束（同じ claim id）→ NarrativeSynthesis（A1・凍結）
```

## 2. authority ／ 非 authority

出力は A1 の `NarrativeSynthesis` で、A1 の分類（DERIVED / NON-AUTHORITY / NON-PERSISTENT）をそのまま持つ。A3 は Theme・
observation・attachment・governance event・relation assertion・提案・decision・monitoring review・Production DNA を書かず、変えず、
bridge を実行しない（test BI）。

## 3. 純関数の境界

- 入力は A2 の snapshot だけ（`synthesize(snapshot)` の引数は 1 つ。test Y）。store・Phase 6・filesystem・時計・乱数・network を
  使わない。`pit_assembler` を呼ばない。
- 実行時の証明: `open` ／ `os.open` ／ `socket` を失敗させても同じ出力（BA / BB / BG）、`time` ／ `random` ／ `secrets` ／ `uuid` を
  失敗させても同じ出力（BH）、data_root を消した後も同じ snapshot から同じ出力（Y）、5 回の実行で data_root・repo・入力の bytes が
  変わらない（BB / BI）、別 process・別 hash seed で byte 一致（C）。

## 4. 入力の再検証

型付きの snapshot を盲信しない（`revalidate`）:

1. `NarrativeInputSnapshot` でなければ `INVALID_SNAPSHOT`。
2. kind が THEME_STATE / THEME_SET でなければ `UNSUPPORTED_KIND`。
3. 入力 schema（`narrative_input_snapshot:0.1.0`）と reader の version（`SUPPORTED_READER_VERSIONS`）が既知でなければ
   `UNSUPPORTED_SNAPSHOT_VERSION`。
4. すべての入れ子の object の型と属性の集合が dataclass の field と完全一致（後から足された `confidence` 等を拒否）。
5. すべての ref を A1 の `ref_from_dict(to_dict())` で作り直し（A1 の全検査）、`ThemeInput`・`EvidenceSource`・snapshot を A2 の
   constructor で作り直す（件数・cutoff・relation の範囲・出所の能力・PIT の検査）。
6. 作り直した snapshot の `snapshot_id` と canonical bytes が元と一致すること。
7. B2 の flag と投影した attachment の、Phase 6 で必ず成り立つ関係（CONTESTED ⇔ CONTRADICTS がある、
   INVALIDATION_EVIDENCE_PRESENT ⇔ INVALIDATES がある、HAS_SUPPORT ⇒ SUPPORTS がある、NO_VISIBLE_EVIDENCE と HAS_SUPPORT は両立
   しない、HAS_CONTEXT_ONLY ⇒ NO_VISIBLE_EVIDENCE かつ attachment がある、SINGLE / MULTI の組は両立しない）。

3 以外の違反はすべて `SNAPSHOT_INTEGRITY_FAILURE`（detail は上流の code か型名だけ）。改ざんの test: id（AR）・role（AS。enum の
差し替えも生の文字列も）・出所の能力（AT）・relation の class と端点・足された属性（AU）・kind と件数（AV）・version（AW）。

## 5. 規則表

`RULES`（静的・`narrative_synthesis_rules` 0.1.0）。重み・score・閾値は無い。各規則の (class, kind, predicate) は A1 の
`ALLOWED_TRIPLES` の内側（test で固定）:

| rule | 入力の形 | class | kind | predicate（code） | ref | 抑止 |
|---|---|---|---|---|---|---|
| R01 | Theme ごと | REVIEWED_INTERPRETATION | STATE | THEME_REVIEWED_STATE | observation | なし |
| R02 | 記録された機構 component ごと | REVIEWED_INTERPRETATION | MECHANISM | RECORDS_MECHANISM_COMPONENT | component | なし |
| R03 | 確度が HYPOTHESIZED_MECHANISM で component がある Theme | UNCERTAINTY | MECHANISM | IS_UNCERTAIN（MECHANISM_HYPOTHESIZED） | observation | component なし |
| R04 | attachment ごと（どの role でも） | REVIEWED_INTERPRETATION | EVIDENCE | EVIDENCE_ATTACHED | attachment（role そのまま） | なし |
| R05 | SUPPORTS と CONTRADICTS の両方がある Theme | UNCERTAINTY | EVIDENCE | IS_UNCERTAIN（CONTESTED_EVIDENCE） | observation ＋ すべての SUPPORTS / CONTRADICTS | 片方が無い |
| R06 | flag NO_VISIBLE_EVIDENCE | UNCERTAINTY | EVIDENCE | IS_UNCERTAIN（NO_SUPPORTING_EVIDENCE） | observation | SUPPORTS が投影されている |
| R07 | flag SINGLE_SOURCE | UNCERTAINTY | EVIDENCE | IS_UNCERTAIN（SINGLE_SOURCE_EVIDENCE） | observation | なし |
| R08 | flag STALE | UNCERTAINTY | EVIDENCE | IS_UNCERTAIN（STALE_EVIDENCE） | observation | なし |
| R09 | 記録された無効化条件ごと | REVIEWED_INTERPRETATION | INVALIDATION | RECORDS_INVALIDATION_CONDITION | condition | なし |
| R10 | INVALIDATES の attachment ごと | REVIEWED_INTERPRETATION | INVALIDATION | INVALIDATING_EVIDENCE_ATTACHED | condition ＋ attachment | なし |
| R11 | 能力 OBSERVATIONAL_RECORD で時刻が確立した evidence source ごと | OBSERVED_FACT | EVIDENCE | EVIDENCE_ITEM_OBSERVED | evidence item（内容なし） | SOURCE_CONTENT・時刻が未確立 |
| R12 | 投影された B1 の変化ごと（比較 cutoff があるときだけ） | DERIVED_SYNTHESIS | CHANGE | CHANGED_BETWEEN_CUTOFFS | change | changes が None |
| R13 | 投影された B5B の relation ごと（THEME_SET だけ） | REVIEWED_INTERPRETATION | RELATION | HUMAN_ASSERTED_RELATION ／ SOURCE_ASSERTED_RELATION（assertion class で決まる） | relation ＋ 両端の observation | THEME_STATE |
| R14 | 1 つの `ref_id` を SUPPORTS として持つ 2 つ以上の subject Theme（THEME_SET だけ） | ALTERNATIVE_HYPOTHESIS | MECHANISM | ALTERNATIVE_EXPLANATIONS_OF_SHARED_EVIDENCE | Theme ごとに observation ＋ その SUPPORTS（最小の attachment key） | Theme が 2 未満 |

生成された claim は、その規則の宣言した (class, kind) と一致しなければ `MODEL_CONTRACT_MISMATCH`（engine の自己検査）。test AY は
規則表を engine とは独立に書き下し、7 通りの snapshot で「生成された claim の集合 ＝ 正当化される claim の集合」（埋め草も欠落も
無い）を確かめる。

## 6. THEME_STATE

中心の Theme は 1 つ。R01〜R12 だけ（relation・代替は作らない。A2 の THEME_STATE は relation を持たない）。Theme の
解釈・機構・支持・反証・無効化・不確実性・（比較 cutoff があれば）変化を評価する。

## 7. THEME_SET

要求された各 Theme を**順位なしに同じ規則で** synthesize する（集合に入っても Theme ごとの claim は THEME_STATE と同じ id。test AF）。
集合をまたぐ claim は R13（明示の relation）と R14（明示の共有 SUPPORTS）だけ。主役の選定・順位・複数 Theme の統合・evidence の
重なりからの共通原因の推測・共起からの relation・推移の relation は無い（AE〜AH）。

## 8. 解釈

R01 は Theme ごとに 1 つの REVIEWED_INTERPRETATION（observation の ref。governance は ACCEPTED のまま）。解釈を OBSERVED_FACT に
しない（evidence item の ref は OBSERVED_FACT の claim だけに現れる。test F）。確度を強めない（G）。

## 9. 機構

R02 は記録された component ごとに 1 claim（1 ref）。component 同士を結ぶ claim・新しい因果の辺は無い（H）。確度の天井は
observation の ref が運び（attribution）、仮説のままなら R03 が不確実性として示す（A1 が強制）。

## 10. SUPPORTS

R04 で role SUPPORTS のまま示す。証明にしない（predicate は「記録された attachment」）。1 つの evidence item が複数の Theme を支える
のは、snapshot にそれぞれの attachment があるときだけ（R14 もその完全一致だけ）。

## 11. CONTRADICTS

R04 で必ず示し、支持と並ぶときは R05（CONTESTED_EVIDENCE）で両方の attachment を引用する。差し引き・勝ち負け・net の値は無い
（K / L）。

## 12. CONTEXT

判断（D-P7-A3-1）: A1 の `EVIDENCE_ATTACHED` は role を問わない（role は ref の中）ので、CONTEXT の attachment も R04 で
**role CONTEXT のまま**見せる。SUPPORTS にはならず、R05 の支持にも R14 の共有支持にも数えない（M）。A1 は変えない。

## 13. INVALIDATES

R10 が INVALIDATES の attachment と、それが指す記録された条件を 1 つの claim で示し、R09 が条件そのものを示す（条件と
「INVALIDATES として付与された evidence」を区別する）。A3 は Theme を退役させず、governance を変えず、条件が客観的に満たされたとは
言わない（N / O）。

## 14. 不確実性

構造化された入力の条件だけから作る: R03（仮説の機構）・R05（支持と反証）・R06（B2 の NO_VISIBLE_EVIDENCE ＝ 数えられる evidence が
無い。SUPPORTS が投影されていれば抑止。D-P7-A3-5）・R07（B2 の SINGLE_SOURCE）・R08（B2 の STALE。caller の policy）。「疎に
見える」ことからは作らない。確率・確信度の値は無い（AI / AJ）。HAS_CONTEXT_ONLY・MULTI_SOURCE・MULTI_DATE・QUALIFIES など強さに
読める flag は claim にしない。

## 15. 代替の説明

R14（D-P7-A3-2）: THEME_SET で、1 つの `ref_id` が 2 つ以上の subject Theme に SUPPORTS として付与されているときだけ。`ref_id` の
完全一致だけで、類似度・埋め込み・意味の推測は使わない。Theme の並びは canonical（勝者・優先はない。AK）。THEME_STATE・共有が
無い・CONTEXT / CONTRADICTS だけの共有では作らない（AL）。A3 は共有を「共通の原因」とも relation とも言わない（AH）。

## 16. 変化

A2 の `changes` が None（比較 cutoff なし）なら変化の claim は作らない。空 tuple（変化なし）でも作らない。明示の B1 の変化は 1 対 1 で
R12（V / W）。現在の状態だけから「新しい・加速・弱まる・強まる・現れる・消えつつある」を推測しない（X）。momentum の値は無い。

## 17. relation

THEME_SET の A2 の relation 投影だけから R13 を作る。1 辺 → 1 claim。上流の relation 型（CAUSES / AMPLIFIES / MITIGATES /
DEPENDS_ON）はすべて向きを持つので、逆向きの claim は作らない。推移閉包・推測した辺は無い（Z〜AC）。

## 18. SOURCE_ASSERTED

assertion class が SOURCE_ASSERTED の relation は `SOURCE_ASSERTED_RELATION`（REVIEWED_INTERPRETATION）だけになる。客観的な
relation・観測事実・審査済みの因果の真実にならない（A1 の固定文言 `SOURCE_ASSERTED_MEANING`）。B5 の検証を重ねたり上書きしたり
しない（AD）。

## 19. 観測事実の天井

R11 は出所の能力 OBSERVATIONAL_RECORD（FACT・OBSERVATION）で時刻が確立した item だけ。文書・報道・発言（SPEECH ＝ STATEMENT）は
世界の事実にならない（P〜T）。claim が主張するのは「その記録が cutoff までに観測された」ことだけで、記録の**内容**の命題を作らない
（ref だけから内容を発明しない。U）。

## 20. 収束（重複の除去）

同じ claim id の claim は 1 つに収束する（A1 の id）。同じ id で中身が違えば `CLAIM_CONFLICT`（AM / AN）。A1 が claim 同士の
食い違い（role の書き換え・同じ ref の内容の違い・observation の食い違い・不確実性と ref の矛盾・重複）として拒否した場合も
`CLAIM_CONFLICT`。異なる claim を曖昧に合わせない。

## 21. 順序

出力の順序は A1 の canonical な順（claim id 順・subject id 順・ref の canonical 順）。生成の順を重要度に使わない。宣言済みの
非意味的な並び（Theme・component・attachment・flag・source・relation・reader・要求 root）を入れ替えても claim・canonical bytes・
synthesis id は同じ（D / AO）。

## 22. identity と provenance

- `NarrativeSynthesis` は A1 の constructor だけで作る（id の算法を再実装・上書きしない。AP）。同じ snapshot → 同じ synthesis。
- snapshot の provenance: A1 の `input_digest` ＝ A2 の `snapshot_id`（D-P7-A3-4）。
- 規則表の version: A1 の `knowledge_pins` ＝ snapshot の `reader_versions` ＋ `("narrative_synthesis_rules", RULESET_VERSION)`
  （D-P7-A3-3）。規則の意味を変えたら version を上げ、synthesis id が変わる（AQ: version だけを変えると claim は同じで id が変わる）。
- 時計・乱数の metadata は無い。A1 に新しい field は足していない。

## 23. 失敗

| code | 意味 |
|---|---|
| `INVALID_SNAPSHOT` | snapshot ではない入力 |
| `UNSUPPORTED_SNAPSHOT_VERSION` | 未知の入力 schema ／ reader version |
| `UNSUPPORTED_KIND` | THEME_STATE / THEME_SET 以外の kind |
| `SNAPSHOT_INTEGRITY_FAILURE` | 改ざん・再検証の失敗（§4） |
| `CLAIM_CONFLICT` | 同じ id の違う claim ／ A1 が食い違いとして拒否 |
| `NO_JUSTIFIED_CLAIMS` | claim が 1 つも正当化されない（埋め草を作らない） |
| `MODEL_CONTRACT_MISMATCH` | 規則の宣言と生成の不一致 ／ A1 のその他の拒否（ref の上限 16 を超える場合を含む） |

A1 は claim 0 の synthesis を許さない（`CLAIM_COUNT_OUT_OF_BOUNDS`）。正当な snapshot は ACCEPTED の Theme を 1 つ以上持つので
R01 が必ず 1 つ以上の claim を作るが、規則が何も作らない場合は A1 を弱めず `NO_JUSTIFIED_CLAIMS` で止める（AX）。error は本文・
path・例外の文を運ばない。

## 24. 自己学習しない

A3 の出力は将来の規則に影響しない。勝率・採用率・過去の成功・calibration の feedback・過去の Narrative の人気・click を入力に
持たない。規則表は静的な code（tuple）で、module の状態は実行で変わらない（`global` なし・module の値は実行の前後で同じ。
実行順を入れ替えても同じ。BJ）。

## 25. security ／ import 境界

- import は `.input_model`・`.synthesis_model`・標準 library（`dataclasses`・`typing`）だけ（`PHASE7_RUNTIME` に登録。test の許可
  一覧・runtime closure で固定）。`pit_assembler`・Phase 6・P5・legacy・provider / network・公開 / 通知 / 売買 / portfolio は import
  しない（BC〜BG）。A2 の Phase 6 への認可（`PHASE7_SANCTIONED_IMPORTERS` ＝ `pit_assembler.py` だけ）は広げていない。
- 未登録の Phase 7 runtime は検出される（BN）。A1 の runtime は `a02ad60`、A2 の runtime は `2dfd85c`、Phase 6 の runtime は
  `5ef313a` と byte 一致（BK / BL / BM）。
- 秘密値・path・生の LLM 応答・本文・人間の文を持たない。出力の文字列はすべて id・enum・時刻・version の token（AZ）。
- scratch の clone で mutation M1〜M15（解釈の事実化・反証の削除・CONTEXT / INVALIDATES の SUPPORTS 化・確度の強化・比較なしの
  変化・推移の relation・SOURCE_ASSERTED の客観化・Theme の順位付け・確信度の pin・ref だけからの事実・pit_assembler / Phase 6 store
  の import・時計の identity・前回の実行の影響・乱数の並び）をすべて検出。

## 26. A4 への引き継ぎ

A4（描画・変化・適格性）は A3 の `NarrativeSynthesis` だけを入力にする:

1. 文章は claim の (class, kind, predicate, code) ごとの閉じた template から作り、claim の意味（A1 §5・§10・§13 の固定文言）を
   超えない。OBSERVED_FACT は「記録が観測された」、REVIEWED_INTERPRETATION は「reviewed Theme が記録している」、
   SOURCE_ASSERTED は「出典が主張している」、ALTERNATIVE_HYPOTHESIS は「並べるだけ」、UNCERTAINTY は code の閉じた文。
2. 表示の順は A4 が決める（A3 の claim id 順は重要度ではない）。順位・主役・勝者・確信度を作らない。
3. `input_digest`（snapshot id）と `knowledge_pins`（reader と規則表の version）を表示の provenance に使う。
4. NarrativeChange（2 つの synthesis の差）は A4 で、A1 の claim id の集合の差として作る（A3 の規則表の version が違う synthesis の
   比較は扱わない）。
5. 延期（P7-A3-DEF）: 代替の説明の追加の出所（未審査の提案・機構の比較）・relation の撤回の表示・THEME_STATE の文脈 Theme・
   limitation / metadata の不確実性・ref の上限 16 を超える CONTESTED ／ 代替（現在は `MODEL_CONTRACT_MISMATCH` で止まる）。
