# PHASE 6 / P6-B7F — VALIDATED PLAN → EXISTING PROPOSAL AUTHORITY SUBMISSION CONTRACT

CHECK-THEN-REUSE。decision・Theme の変更・Foundation / B5B への実行・実 LLM・network・API key・公開出力は無い。

| module | 役割 |
|---|---|
| `llm_submission_model.py` | 提出結果の純 model（`SubmissionResult` / `PlanSubmission`・失敗 code・凍結文言。I/O なし） |
| `llm_submission.py` | 提出 bridge（`submit_proposals`。**B7F で唯一の書き込み面**: B3 / B5C の既存 `append_proposal`） |
| `tests/intelligence/test_theme_llm_submission.py` | test matrix A〜BB ＋ 結果 model・秘匿・注入した障害 |

---

## 1. authority 境界

| 対象 | 分類 |
|---|---|
| 入力（B7D の検証済み plan） | NON-AUTHORITY・DERIVED（B7D のまま） |
| 提出結果（`SubmissionResult`） | NON-AUTHORITY・非永続（返り値だけ。journal に書かない） |
| B3 `theme_intelligence/proposals.jsonl` | 既存の L1 proposal authority（**提案を 1 行追記するだけ**） |
| B5C `theme_intelligence/relation_proposals.jsonl` | 既存の L1 relation proposal authority（同上） |

提出は既存の proposal authority に**提案**を置くことだけであり、次のどれでもない（凍結文言
`PROPOSAL_IS_NOT_DECISION` = "a submitted proposal is not a decision, an accepted Theme, an evidence attachment or a
relation assertion"）:

- 提案 ≠ decision（ACCEPT / REJECT / DEFER / NOT_DUPLICATE は人間の後段）
- 提案 ≠ 受理された Theme（ThemeRoot / ThemeObservation を作らない）
- 提案 ≠ evidence attachment（Foundation に付与しない）
- 提案 ≠ relation assertion（B5B に主張を書かない）

新しい authority・新しい提出 journal・新しい proposal type は作らない（D-B7-1 / D-B7-3）。

## 2. 対応する plan type

| B7D plan | 上流 proposal | 提出先（family） | proposer |
|---|---|---|---|
| `ValidatedEvidenceProposalPlan` | B3 `EVIDENCE_CANDIDATE`（`EvidenceCandidateProposal`） | `B3_PROPOSALS` | `ProposerClass.LLM_PROPOSAL` |
| `ValidatedThemeProposalPlan` | B3 `THEME_CANDIDATE`（`ThemeCandidateProposal`） | `B3_PROPOSALS` | `ProposerClass.LLM_PROPOSAL` |
| `ValidatedRelationProposalPlan` | B5C `RELATION_CANDIDATE`（`RelationProposal`） | `B5C_RELATION_PROPOSALS` | `RelationProposerClass.LLM` |

受け付けない入力（すべて `INVALID_SUBMISSION_INPUT`・書き込み 0 件）: raw envelope・provider の応答文字列・B7C manifest・
LLM の文・dict・journal record・B7E の `GenerationRun` / 監査 record・plan 単体・ABSTAINED の検証結果・plan 0 件・
`ValidatedGeneration` 以外の型。VALIDATED 以外の結果は提出に届かない（入力型が B7D の `LlmValidationResult` で、
outcome が `PLANS` のものだけ）。

## 3. pipeline

```
submit_proposals(*, generations, submitted_at, data_root) -> SubmissionResult
  1. 入力の検査          … data_root・生成列・submitted_at（aware）・generation_ref・prompt contract version
  2. 再検証              … plan・入れ子・検証結果を凍結 constructor で組み直し、id の一致を確認（§4）
  3. 上流の再構築        … 凍結済み B3 / B5C constructor → canonical 行 → 凍結 loader で読み直し（§5）
  4. 決定論的な整列      … family → 上流 proposal id → generation_ref → plan id（§11）
  5. authority の読み込み … 必要な family の store だけを既存 constructor で開く（破損は fail closed）
  6. 分類                … 同じ提出の中の重複を畳む → get_proposal で照合（NEW / REUSED / CONFLICT）
  ── ここまでに 1 件でも失敗があれば REJECTED（書き込み 0 件）──
  7. 追記                … NEW だけを 4. の順に append_proposal で 1 行ずつ
  8. 読み直し            … 追記した行を凍結 loader で読み直し、canonical 行の一致を確認
```

## 4. plan の再検証（型だけを信用しない）

提出境界で次をすべて再検査する（`object.__setattr__` による後からの書き換えを想定）:

- 型が B7D の plan 型・検証結果型・`ValidatedGeneration` と**完全一致**（subclass 不可）。
- 宣言済み field 以外の属性を持たない（`UNDECLARED_ATTRIBUTE`）。
- plan を `type(plan).build(**fields)` で組み直す（THEME の `PlannedEvidenceRef` も組み直す）。B7D の検査（schema・
  kind・proposer・provenance / certainty の上限・template・target・relation の assertion class・SOURCE_ASSERTED の
  状態）がここで再び走り、違反は B7D の code のまま `PLAN_INTEGRITY_FAILURE` になる。
- 組み直した plan id と plan の `plan_id` が一致（`PLAN_ID_MISMATCH`）。
- 組み直した plan で検証結果を `LlmValidationResult.build` し、`result_id` が一致（`VALIDATION_RESULT_ID_MISMATCH`）。
  plan を整合的に偽造しても、検証結果 id が plan 集合に束縛されているため検出される。

## 5. 上流 proposal の再構築

- 引数は plan の `upstream_arguments()` だけ（B7D が凍結 constructor の引数として用意した material）。LLM の文・
  manifest・store を読み直さない。
- `EvidenceCandidateProposal.build` / `ThemeCandidateProposal.build` / `RelationProposal.build`（凍結済み。変更なし）で
  組み、canonical 行 → `parse_proposal` / `parse_proposal_record`（凍結 loader）で読み直して byte 一致を確認する
  （`UPSTREAM_ROUND_TRIP`）。上流 constructor の拒否は上流の code のまま `PLAN_INTEGRITY_FAILURE`
  （例: 正規化されていない subject → `NOT_NORMALIZED`）。
- 組んだ proposal の id が plan の `upstream_proposal_id` と一致しなければ `UPSTREAM_ID_MISMATCH`（書き込み 0 件）。
- 読み直した proposal の proposer が LLM のままであること（`LLM_PROPOSAL` / `LLM`）を確認する。

## 6. check-then-reuse

B5 completion audit §10.1（凍結）と B7A §15.3 の運用契約をそのまま実装する:

| 既存 authority | 扱い | 書き込み |
|---|---|---|
| 同じ id が無い | `NEW_PROPOSAL_APPENDED`（既存 `append_proposal` で 1 行） | 1 行 |
| 同じ id・同じ型・同じ意味 identity・canonical 行が byte 一致 | `EXISTING_PROPOSAL_REUSED`（`reuse=EXACT`） | なし |
| 同じ id・同じ型・同じ意味 identity・provenance / created_at だけ違う | `EXISTING_PROPOSAL_REUSED`（`reuse=CONVERGENT`） | なし |
| 同じ id・意味が違う | `PROPOSAL_CONFLICT`（fail closed） | なし |

意味 identity は上流 model の `identity_payload()`（B3 / B5C の id の材料。provenance・created_at・THEME の
`attached_at` を含まない）。provenance だけが違う 2 件目を append すると上流 store の CONFLICT になるため、append の前に
必ず `get_proposal` で引く。記録済み提案を書き換え・上書き・削除・再 id 化・類似重複の追加をしない。

## 7. conflict の意味論

- 上流の意味論（同 id 異 bytes = CONFLICT、同 id 同 bytes = ALREADY_PRESENT）を変えない。B7F は CONFLICT を
  避けるために check-then-reuse を行うのであって、CONFLICT を再利用に読み替えない。
- 同じ id で意味 identity が違う既存提案は、id が content hash なので通常は起こらない（hash の衝突・authority の
  外部改変・上流 identity 規則の変更でのみ起こる）。起きたら `PROPOSAL_CONFLICT` / `EXISTING_CONTENT_DIFFERS` で
  提出全体を止める（test W / AE は store の読み取りを差し替えた障害注入で確認する）。
- 同じ提出の中で同じ id の提案が 2 回現れたとき、意味 identity が同じなら 1 回だけ扱い（2 件目以降は
  `DUPLICATE_IN_SUBMISSION`）、違えば `PROPOSAL_CONFLICT` / `IN_SUBMISSION`（書き込み 0 件）。id だけでは畳まない。

## 8. provenance

既存 field だけを使う（新しい field を足さない）:

| B3 `ProposalProvenance` | B5C `RelationProposalProvenance` | 値 |
|---|---|---|
| `proposer_class` | `proposer_class` | `LLM_PROPOSAL` / `LLM`（固定。HUMAN / RULE / SOURCE へ昇格しない） |
| `proposer_ref` | `proposer_ref` | `generation_ref` ＝ B7E の試行 id（`thllmatt_<24hex>`。caller が渡す） |
| `rule_version` | `rule_version` | prompt contract version（caller が渡す token） |
| `reason` | `note` | `llm generation validated as <thllmval_…>`（B7D の検証結果 id。決定論的な参照文） |

- provider / model / 生成設定の識別子は入れない（B7E 監査 record にだけある。試行 id から辿れる）。
- LLM の rationale は provenance に入れない（B7D plan の `llm_rationale` は提出しない。理由欄は B7D の template 文）。
- provenance は B3 / B5C の id に入らない。provider / model・submitted_at・generation_ref が違っても同じ id に収束する
  （test AK / AL）。

## 9. SOURCE_ASSERTED

- relation plan は `source_claim_status = UNVERIFIED` のまま提出される。B7F は SourceClaimVerification を作らない・
  読まない・受理しない・`accepted_assertion_class` を設定しない。
- 出典付きの関係提案（`source_attribution`）は**提案のまま**で、SOURCE_ASSERTED の主張にはならない。受理・検証・
  主張は B5C の人間 decision と B5 の後段（RR-3 を含む）の責務で、B7F には経路が無い（guard と test P〜R）。
- plan の状態を SOURCE_ASSERTED に書き換えた入力、属性を後から足した入力は再検証で拒否される（test H〜O）。

## 10. 複数 plan の pre-flight

- 1 回の提出は複数の生成（`ValidatedGeneration` の列）と各生成の複数 plan を受け取る。
- 入力の検査・再検証・上流の再構築・authority の読み込み・照合を**すべての plan について**終えてから追記を始める。
  1 件でも失敗があれば何も追記しない（`REJECTED`。test AE / AF）。
- 開く store は提出に含まれる family のものだけ（evidence だけの提出は B5C を開かない）。
- B3 と B5C は別 file なので、これは **ACID ではない**。pre-flight は部分書き込みの機会を減らすだけで、追記中の
  失敗には §12 を適用する。

## 11. 追記の順序

- `FAMILY_ORDER`（B3 → B5C）→ 上流 proposal id → generation_ref → plan id。LLM の候補順・入力の生成順に依らない。
- 同じ内容の提出は、入力の順序によらず byte 一致の authority になる（test AC）。

## 12. 部分書き込みの境界

- 1 件目の追記の前に失敗したら `REJECTED` / `APPEND_FAILURE`（書き込み 0 件）。
- 1 件以上を追記した後に失敗したら `PARTIAL_SUBMISSION`（`failure_detail = APPEND_FAILURE:<上流 code>`）。
  追記済みの行は**巻き戻さない**（authority の履歴を削除・切り詰めしない）。失敗した plan は
  `NOT_SUBMITTED` / `APPEND_FAILURE`、残りは `NOT_SUBMITTED`。
- 同じ入力で再提出すると、追記済みの提案は再利用、残りは新規になって収束する（test AG / AH）。
- 追記後の読み直しで一致しなければ `PARTIAL_SUBMISSION` / `APPEND_FAILURE:POST_APPEND_VERIFICATION`。
- 並行書き込みの lock は無い（単一 writer 前提）。上流 store の size 検査（ConcurrentModification）が外部改変を
  検出したときは `APPEND_FAILURE` 系になる。

## 13. 冪等性

- 1 回目 NEW → 2 回目 REUSED（EXACT）、authority の bytes は不変（test AI / AJ）。
- provider / model・generation_ref・submitted_at の違いは CONVERGENT の再利用に収束し、authority は不変（test B / AK）。
- 時刻・乱数・環境を読まないので、同じ入力・同じ authority からは byte 一致の結果と authority になる（test AU）。

## 14. 結果 model

`SubmissionResult`（`theme_llm_proposal_submission:0.1.0`）:

| field | 内容 |
|---|---|
| `status` | `SUBMITTED` / `REJECTED` / `PARTIAL_SUBMISSION` |
| `actions` | plan ごとの `PlanSubmission`（family → 上流 id → plan id の順） |
| `failure_code` | §15 の code（成功なら空） |
| `failure_detail` | 上流の有界 code だけ（`^[A-Z][A-Z0-9_:]{0,95}$`。本文・秘密値を入れない） |

`PlanSubmission`: `plan_id`・`family`・`upstream_proposal_id`・`action`（NEW_PROPOSAL_APPENDED /
EXISTING_PROPOSAL_REUSED / DUPLICATE_IN_SUBMISSION / NOT_SUBMITTED）・`reuse`（NONE / EXACT / CONVERGENT）・
`line_appended`（authority に 1 行が加わったか ＝ §29 の「write occurred」）・`failure_code`。

不変条件: `line_appended` ⇔ NEW、`reuse ≠ NONE` ⇔ REUSED、failure code は NOT_SUBMITTED だけ、SUBMITTED は失敗・
NOT_SUBMITTED を含まない、REJECTED は追記 0 件、PARTIAL は追記 1 件以上。score・順位・確信度・severity・推奨・
accepted / decision の欄は無い。

## 15. failure の分類

| code | 意味 | 書き込み |
|---|---|---|
| `INVALID_SUBMISSION_INPUT` | 入力の型・欠落（NO_INPUT・NOT_A_VALIDATED_GENERATION・NOT_A_VALIDATION_RESULT・NOT_VALIDATED・NO_PLANS・NOT_A_VALIDATED_PLAN・GENERATION_REF・PROMPT_CONTRACT_VERSION・SUBMITTED_AT_REQUIRED・NAIVE_SUBMITTED_AT・SUBMITTED_BEFORE_CUTOFF・DATA_ROOT_REQUIRED） | 0 |
| `PLAN_INTEGRITY_FAILURE` | 再検証・上流 constructor の拒否（UNDECLARED_ATTRIBUTE・PLAN_ID_MISMATCH・VALIDATION_RESULT_ID_MISMATCH・MALFORMED_*・UPSTREAM_ROUND_TRIP・B7D / 上流の code） | 0 |
| `UPSTREAM_ID_MISMATCH` | 組んだ上流 proposal id ≠ plan の `upstream_proposal_id` | 0 |
| `AUTHORITY_CORRUPTION` | B3 / B5C authority の破損・欠落（上流 store の code: MALFORMED_JSON・BLANK_LINE・AUTHORITY_MISSING 等） | 0 |
| `PROPOSAL_CONFLICT` | 同じ id で意味が違う（EXISTING_CONTENT_DIFFERS・IN_SUBMISSION） | 0 |
| `APPEND_FAILURE` | 1 件目の追記の失敗（上流 store の code） | 0 |
| `PARTIAL_SUBMISSION` | 1 件以上の追記の後の失敗（`APPEND_FAILURE:<code>`） | 1 件以上（巻き戻さない） |

authority は修復しない・作らない（欠落した store を initialize しない）。

## 16. zero-write の場合

次はすべて B3 / B5C を含む data root 全体の hash inventory が不変（test H〜O・V〜Z・AB・AE・AF・AG2）:
入力の拒否・再検証の失敗・id の不一致・authority の破損 / 欠落・pre-flight の conflict・同じ提出の中の矛盾・
1 件目の追記の失敗・全件再利用の提出。

## 17. 生成監査 journal との境界

- B7F は B7E の生成監査 journal を**読まない・書かない**（§22。成否・受理率・model の比較を学習や選別に使わない）。
  B7E の module を import しない。
- `generation_ref` は caller が渡す B7E の試行 id で、B7F は形式（`thllmatt_<24hex>`）だけを検査する。journal に
  その試行が在るかは照合しない（journal を読まないため）。caller の組み立ては §22。
- 再利用（収束）の事実は返り値の `EXISTING_PROPOSAL_REUSED` / `CONVERGENT` にだけ現れ、永続しない（新しい journal を
  作らない。B7A §15.3 の「収束の事実は生成 journal に残す」は、B7E journal が凍結済みのため §21 の deferred）。

## 18. no-decision / no-execution

- decision（B3 `ProposalDecision`・B5C `RelationProposalDecision`）を作らない。decision journal は不変（test AP〜AS）。
- 受理された提案を Foundation（ThemeRoot / ThemeObservation / EvidenceAttachment / GovernanceEvent）・B5B
  （RelationAssertion / relation governance）へ実行しない。bridge（`plan_theme_creation` 等）を import しない。
  提出された THEME 提案は受理されていないので bridge は `NOT_ACCEPTED` で拒否する（test S〜U）。
- B6 review state・monitoring・公開出力・scheduler・通知に触れない。RR-3 は変更しない。

## 19. security

- network・socket・HTTP client・SDK・環境変数・資格情報・keyring・subprocess を参照しない（guard と test AT）。
- 時計・乱数・uuid を読まない（test AU）。時刻は caller の `submitted_at` だけ。
- prompt・raw response・manifest の本文・LLM の rationale を authority・結果・例外文に入れない（test AV・秘匿 test）。
  結果の `failure_detail` は有界 code だけ。
- **PIT**: B7F は**現在の** proposal authority に対してだけ動く。過去時点の replay・backtest に使ってはならない
  （凍結文言 `SUBMISSION_IS_NOT_A_BACKTEST`）。`submitted_at` は検証結果の cutoff 以降であること。

### 時刻の分類（§9）

| 時刻 | 由来 | 用途 | identity |
|---|---|---|---|
| `submitted_at` | caller（aware 必須・cutoff 以降） | B3 / B5C の `created_at`、THEME evidence ref の `attached_at` | **含まれない**（operational） |
| `evidence_time` / `evidence_date` | B7D plan（manifest から複写） | 上流 proposal の材料 | 含まれる（caller は与えない） |
| `cutoff` | B7D 検証結果 | `submitted_at` の下限 | 検証結果 id に含まれる |

## 20. 凍結の連鎖

| anchor | 対象 | 確認 |
|---|---|---|
| B6 `7a8f8a4` | B6 runtime | B6 の pin（新規追加の `llm_*.py` だけを対象外にする述語は不変） |
| B7B `e2aa991` | `llm_proposal_model.py` | byte 比較（test AW〜AZ） |
| B7C `95e04ae` | `llm_manifest_model.py`・`llm_manifest_builder.py` | byte 比較 |
| B7D `c240f68` | `llm_plan_model.py`・`llm_validator.py` | byte 比較 |
| B7E `695227a` | `llm_generation_input.py`・`llm_provider.py`・`llm_generation_model.py`・`llm_generation_journal.py`・`llm_generation.py` | byte 比較 |

- `695227a` 以降の runtime 差分は新規の B7F module 2 つだけ（test BA。変更 `M` は対象外にならない）。
- B3 / B5C の model・store・Foundation / B4 / B5 の runtime は変更していない（store API をそのまま使う）。
- B7E の test（`test_ao`）は「`c240f68` 以降の変更は B7E module と後続 B7 の新規 module だけ」を確認するよう
  `LATER_B7_MODULES` を足した（test 側だけの狭い変更。B7E runtime は不変）。
- §25: B6 は再開しない。anchor ごとの byte pin を維持し、凍結の連鎖全体の再監査は B7 closeout で行う。

## 21. deferred

| # | 内容 | gate |
|---|---|---|
| 1 | 再利用（収束・共同発見）の事実の永続（B7A §15.3。B7E journal は凍結済み・B7F は新 journal を作らない） | 監督判断 |
| 2 | `generation_ref` が B7E journal に記録済みの試行であることの照合（B7F は journal を読まない） | B7G / 監督判断 |
| 3 | 提出先 root の存在確認（B7F は確認しない。B4E / B5C の後段と人間 decision が確認する） | 監督判断 |
| 4 | LLM rationale の B3 / B5C への保存（現在は保存しない。provenance は決定論的な参照文） | 監督判断 |
| 5 | 複数 writer の lock・B3 と B5C をまたぐ原子性（現在は単一 writer・ACID ではない） | 監督判断 |
| 6 | PIT 付きの提出（過去時点の authority に対する提出。現在は禁止） | 監督判断 |
| 7 | B7B `LlmGenerationRecord` の扱い（§23: 凍結のまま残す） | 決定済み（残置） |

## 22. B7G への引き継ぎ

B7G（adversarial E2E）が B7C → B7D → B7E → B7F の連鎖で確認すること:

- caller の組み立て: `run.result.outcome is VALIDATED` かつ `run.journal_status` が `APPENDED` / `ALREADY_PRESENT`
  （生成監査 journal に記録済み）のときだけ
  `ValidatedGeneration(validation=run.result.validation, generation_ref=run.audit_record.attempt_id,
  prompt_contract_version=run.audit_record.prompt_contract_version)` を作る。それ以外の結末は B7F に渡さない
  （渡しても型で拒否される）。
- 幻覚・注入・PIT 違反・漏洩の入力が、B7D で止まり B7F の authority を変えないこと。
- 同じ候補を返す複数の provider / model / 試行が、1 件の提案に収束すること（CONVERGENT）。
- zero authority mutation: decision・Foundation・B5B・B6・生成監査 journal が連鎖全体で不変であること。
- 本書の §21 の deferred と、B7 closeout での凍結連鎖の再監査（§20）。
