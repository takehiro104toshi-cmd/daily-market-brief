# Phase 6 — Theme Proposal Journal ＋ Dedup Review Contract（P6-B3）

状態: **実装済み**（`src/intelligence/theme_intelligence/proposal_model.py` / `proposal_store.py` / `proposal_resolution.py` /
`dedup.py` / `proposal_bridge.py`）。Foundation（anchor `12847bf`）・B1（`e2d5168`）・B2（`ce2402a`）は無変更。
監督者決定 B2-D1〜D3 を前提とし、B3 の LOCK（proposal-only、自動 merge 禁止、score / rank 禁止、HUMAN decision のみ）を実装に写した。

## 1. authority の分離

| authority | 場所 | 書き手 |
|---|---|---|
| Foundation（5 authority） | `<data_root>/themes/*.jsonl` | `ThemeStore`（凍結） |
| **Proposal**（本契約） | `<data_root>/theme_intelligence/proposals.jsonl`、`proposal_decisions.jsonl` | `ProposalStore` |

- **Proposal ≠ Theme。** proposal が存在しても ThemeRootRecord / ThemeObservation / governance event は作られない。
- `ProposalStore` は Foundation JSONL を読みも書きもしない。Foundation store は proposal JSONL を書かない。
  B3 の全 module は `themes.store` / `themes.operations` を import しない（boundary test で固定）。
- B3 自身が Foundation へ自動 write することはない。人間の ACCEPT 後に **不変 plan** を作るだけで、実行は別 gate の caller。

## 2. proposal 種別

| type | 意味 | proposer | 許される decision |
|---|---|---|---|
| THEME_CANDIDATE | A1 / A2 の Theme 定義を満たす構造を持つ候補 | RULE / HUMAN / LLM_PROPOSAL | ACCEPT / REJECT / DEFER |
| EVIDENCE_CANDIDATE | まだ機構へ結びつけられない観測候補 | RULE / HUMAN / LLM_PROPOSAL | ACCEPT / REJECT / DEFER |
| DEDUP_REVIEW | exact 比較で見つかった重複候補の review | RULE のみ | ACCEPT / REJECT / DEFER / NOT_DUPLICATE |

RELATION_CANDIDATE は B5 の対象で B3 には無い。LLM_PROPOSAL は provenance 語彙として予約するだけで、LLM runtime は無い。
`LLM_PROPOSAL ≠ reviewed ≠ evidence ≠ Theme authority`。

## 3. identity（content id）

| record | prefix | identity payload に含む | 含めない（audit-only。bytes には含む） |
|---|---|---|---|
| THEME_CANDIDATE | `thprop_` | schema_version、proposal_type、subject、mechanism、certainty_class、scope、limitations、invalidation_conditions、inferred_links、evidence_refs（attachment snapshot から attached_at を除いたもの） | created_at、provenance、fingerprint（内容から再計算して照合） |
| EVIDENCE_CANDIDATE | `thprop_` | evidence_kind、ref_id、source_origin、evidence_time、basis、quality、evidence_date、proposed_role、target_root_id、target_proposal_id、reason | created_at、provenance、locator、note |
| DEDUP_REVIEW | `thprop_` | subject_proposal_id、counterparts（kind / ref / fingerprint / observation_id）、dedup_class、comparison_basis、dedup_model_version | created_at、provenance |
| ProposalDecision | `thdec_` | proposal_id、decision、actor_class、actor_ref、reason、supersedes_decision_id | recorded_at |

`content_id(prefix, canonical_json(payload))`（Foundation と同じ sha256 先頭 24 hex）。同 id ＋ 同 bytes ＝ 冪等、同 id ＋ 異 bytes ＝
CONFLICT（P5 / A4a と同じ）。集合 field は canonical 順に正規化するので入力順に依らない。

## 4. THEME_CANDIDATE

`ThemeCandidateProposal(proposal_id, schema_version, proposal_type, subject, mechanism, certainty_class, scope, limitations,
invalidation_conditions, inferred_links, evidence_refs, provenance, created_at, semantic_fingerprint, identity_core_fingerprint)`。

- Foundation の value 型（ThemeSubject / Mechanism / ScopeToken / Limitation / InvalidationCondition / InferredExposureLink /
  EvidenceAttachment）を再利用するが、ThemeObservation は保存しない（root_id / observation_id / previous を持たない）。
- 形式要件を proposal 段階で検査: scope に PERIOD_FRAME ちょうど 1、invalidation condition ≥ 1、attachment key 一意、
  SUPPORTS / CONTRADICTS の consequence_ref は機構の consequence key、INVALIDATES の condition ref は条件 key。
- fingerprint は Foundation `fingerprint.py` の純関数を proposal に適用（duck typing。materials が同じなら observation と同じ値
  → exact 比較が成立する）。保持値と再計算値の不一致は fail closed。
- `evidence_refs` の attachment snapshot の `attached_at` は提案時刻（audit）。bridge が Theme 作成時刻に置き換える。

## 5. EVIDENCE_CANDIDATE

`EvidenceCandidateProposal(proposal_id, evidence_kind, ref_id, source_origin, evidence_time, evidence_time_basis,
evidence_time_quality, evidence_date, proposed_role, target_root_id, target_proposal_id, reason, locator, note, provenance,
created_at)`。ref_id は kind の prefix、MISSING quality は evidence_time / date / basis 無し、reason は normalized 短文。
THEME_CANDIDATE への昇格は新 proposal（`target_proposal_id` で関係を表す）で表し、旧 proposal を上書きしない。

## 6. DEDUP_REVIEW

`DedupReviewProposal(proposal_id, subject_proposal_id, counterparts, dedup_class, comparison_basis, dedup_model_version,
provenance(RULE), created_at)`。counterpart は THEME_ROOT（root id ＋ 比較した current observation id）と THEME_PROPOSAL
（proposal id）を区別し、複数可。`comparison_basis`（basis kind ＋ subject 側 fingerprint）と各 counterpart の fingerprint は
exact 一致でなければ record にならない。

## 7. decision 履歴

- `ProposalDecision` は不変・append-only。actor_class は HUMAN のみ（RULE / LLM は decision を書けない）。reason 必須。
- 訂正・再検討は上書きせず `supersedes_decision_id` で新 record（DEFER → ACCEPT、REJECT → ACCEPT の再検討も同じ）。
- store の validate-before-append: proposal 存在、decision 種別が proposal type に許されるか、最初の decision は
  `supersedes = ""`、2 件目以降は terminal を指す（MISSING_PREDECESSOR / NON_TERMINAL_PREDECESSOR）、predecessor は同じ
  proposal（WRONG_PROPOSAL_PREDECESSOR）、recorded_at 非減少。load 時の fork / 複数 start は診断（DECISION_FORK /
  DECISION_MULTIPLE_STARTS）として残し、当該 proposal への append は FORKED_PROPOSAL で拒否。
- MERGE_RECOMMENDED / PARENT_CHILD_CONFIRMED のような decision は無い（Foundation MERGE / B5 relation へ authority が漏れるため）。
  DEDUP_REVIEW への ACCEPT は「重複候補の指摘を受理した」だけで、merge を起こさない。

## 8. active resolver（純関数）

`resolve_active_decision(proposal_id, decisions) -> ProposalDecisionResolution(status, active_decision, chain, diagnostics)`。
predecessor graph だけで解決: 唯一の terminal ＝ RESOLVED、decision 無し ＝ NONE、fork / 複数 start ＝ UNRESOLVED、
dangling / 別 proposal への参照 / cycle ＝ INVALID。recorded_at や物理順で勝者を選ばない。

## 9. derived proposal status

| status | 条件 |
|---|---|
| OPEN | decision 無し |
| OPEN_DEFERRED | active ＝ DEFER |
| OPEN_UNRESOLVED | decision 履歴が fork / 複数 start |
| ACCEPTED / REJECTED | active ＝ ACCEPT / REJECT |
| CLOSED_NOT_DUPLICATE | active ＝ NOT_DUPLICATE（DEDUP_REVIEW のみ） |
| INVALID_DECISION_HISTORY | dangling / cycle（store は load で拒否するので通常は合成入力のみ。「変化なし」に潰さない） |

`derive_open_proposals(proposals, decisions)` は OPEN / OPEN_DEFERRED / OPEN_UNRESOLVED を proposal_id 順に返す。

## 10. exact dedup

`detect_exact_duplicates(subject, *, resolutions, proposals, decisions, created_at, dedup_model_version)`:

- 比較は **semantic fingerprint exact** と **identity core fingerprint exact** のみ。counterpart は RESOLVED な
  `ThemeResolution` の DerivedView（current observation）と、他の THEME_CANDIDATE proposal（自分自身と REJECTED 済みを除く）。
- class は EXACT_SEMANTIC_MATCH（両 fingerprint 一致）と EXACT_IDENTITY_CORE_MATCH（core 一致・semantic 相違）の 2 つだけ。
  SCOPE_VARIANT / SUBJECT_VARIANT / MECHANISM_VARIANT / PARENT_CHILD_CANDIDATE は語彙に予約するだけで生成しない
  （heuristic / fuzzy similarity を導入しない）。
- similarity / confidence / priority score、ranking、nearest、top-N、embedding は無い。複数の exact counterpart は全て列挙し
  （kind / ref の辞書順）、勝者を選ばない。
- Foundation は `ThemeResolution` として渡されるだけ（read-only）。B3 は Foundation を読みも書きもしない。
- 出力は DEDUP_REVIEW proposal（RULE、`rule:theme_dedup_exact`、rule_version ＝ dedup model version）。実際の MERGE は
  Foundation governance の人間操作であり、B3 からは起こらない。

## 11. NOT_DUPLICATE suppression（derived）

同じ subject fingerprint・同じ comparison basis・同じ dedup model version の DEDUP_REVIEW に active な NOT_DUPLICATE が
あれば、その review に含まれる counterpart（kind ＋ ref ＋ fingerprint）は再提示しない。残る counterpart だけで新 review を
作る。subject / counterpart の fingerprint が変わる、または dedup model version が変わると再提示できる。同一 id の review
が既に存在する場合も再提示しない（open のまま）。proposal 履歴は削除しない。

## 12. accept bridge

`plan_theme_creation_from_accepted_proposal(proposal, decisions, *, created_at) -> ThemeCreationPlan`:

- THEME_CANDIDATE のみ。active decision が RESOLVED かつ ACCEPT でなければ BridgeError（NOT_ACCEPTED）。DEFER / REJECT /
  UNRESOLVED / decision 無しは不可。EVIDENCE_CANDIDATE / DEDUP_REVIEW は PROPOSAL_TYPE_NOT_BRIDGEABLE。
- fingerprint の再計算照合、scope / 無効化条件の存在、`created_at >= decision.recorded_at` を検査。
- plan は Foundation `plan_candidate` の材料（subject / mechanism / certainty / scope / limitations / invalidation_conditions /
  inferred_links / attachments（attached_at ＝ created_at）/ genesis provenance（HUMAN、decision 参照）/ creator_class HUMAN /
  creation_provenance ＝ `proposal:<id>;decision:<id>;actor:<ref>`）。**root_id は持たない**（Foundation operation 側で生成）。
- bridge は `execute_candidate` / `ThemeStore.append_*` / `operations.execute_*` を呼ばない。Foundation bytes と proposal
  bytes が不変であることを test で固定。

## 13. 永続化（ProposalStore）

明示 data_root（repository fallback なし）、`initialize`（唯一の file 作成）/ `open(read_only)`、canonical 行のみ append、
write → flush → fsync、byte 長で外部変更を検知（SINGLE_WRITER）、load 順 proposals → decisions、破損（非 UTF-8 / 終端改行なし /
空行 / 非 JSON / 非 object / 無効 record / 未知 schema / 非 canonical / physical duplicate）は STORE_CORRUPTION で fail closed、
履歴として不可能なものは INVALID_HISTORY、読み飛ばし・修復・migration・SQLite は無い。

## 14. 時間

全 datetime は aware UTC（naive は NAIVE_DATETIME）。`created_at` / `recorded_at` は caller 注入。現在時刻を呼ばない。
decision の recorded_at は proposal の created_at 以降、chain に沿って非減少。監視 / scheduling は別 gate。

## 15. import 境界

B3 module は `core.ids` / `core.time` / `themes.model` / `themes.fingerprint` / `themes.resolver`（read model）/ 自 package の
model のみを import する。`themes.store` / `themes.operations` / Compass / reports / predictions / calibration / market / legacy /
network / LLM SDK / 公開・顧客出力は無い。Foundation / B1 / B2 から proposal package への import は 0。production runtime
closure に含まれない。IO は `proposal_store.py` の追記だけ。

## 16. 除外（B3 でしないこと）

自動 merge、RootRecord / observation / governance の作成、Foundation への write、SCOPE / SUBJECT / MECHANISM / PARENT_CHILD の
自動分類、score / rank / top-N / embedding、LLM runtime、RELATION_CANDIDATE、SQLite、config.yaml / workflow / 公開出力の変更、
現在時刻、監視 runner。

## 17. tests

`tests/intelligence/test_theme_proposal.py`（matrix 1〜30、40〜50）、`tests/intelligence/test_theme_dedup.py`（31〜39）、
`tests/intelligence/test_theme_intelligence_import_boundary.py`（55〜59: operations / store 非 import、Foundation 非 write、
root id 非生成、score / embedding token 不在、IO は store のみ、production closure 排除）。51〜54・60・61 は gate 報告で検証。

## 18. versioning

`theme_proposal:0.1.0`（proposal 3 種の schema）、`theme_proposal_decision:0.1.0`、`theme_dedup:0.1.0`（dedup model version。
review の identity に含む）、`theme_creation_plan:0.1.0`（bridge plan）。語彙 / 比較規則の変更は dedup model version、
field 追加は schema version を上げる。既存 record の in-place migration は無い。
