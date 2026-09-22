# PHASE 6 / P6-B5D — THEME RELATION E2E / AUTHORITY LAUNDERING / 収束 GATE

対象: `src/intelligence/theme_intelligence/relation_*.py`（B5B relation authority ＋ B5C 提案・決定層）。

本 gate は **TEST / DOC ONLY** である。B5B / B5C の runtime は 1 byte も変更していない。
鎖は `RelationProposal` → 人間の決定 → `RelationAssertionPlan` までで止め、
`relation_assertions.jsonl` / `relation_governance.jsonl` へは一切書いていない。

判定: **`P6_B5C_REMEDIATION_REQUIRED`**。理由は §2（SOURCE_ASSERTED の適格判定が意味論的に不足）。
§4 の収束挙動は **A. intentional and operationally safe** と判定した（§4 参照）。

---

## 1. 検証した鎖（§1）

```
RelationProposal            … 候補。authority ではない
  ↓ append（relation_proposals.jsonl）
RelationProposalDecision    … 人間の ACCEPT / REJECT / DEFER。ACCEPT も authority ではない
  ↓ append（relation_proposal_decisions.jsonl）
RelationAssertionPlan       … 純関数の導出。永続化しない。ここで止める
  ↓ 〈本 phase に存在しない実行 gate〉
ThemeRelationAssertion      … B5B authority（B5D では書かない）
```

確認したこと。

- plan は B5B `ThemeRelationAssertion` を組み立てるのに十分な材料を持つ（test で実際に組み立て、`edge_key` の一致を確認）。
  組み立てた assertion は append しない。
- 同一 `data_root` 上に B5B store と B5C store を並べても、B5C の追記は自身の 2 file だけを伸ばす。
- `relation_proposal_bridge` は `relation_store` / `append_assertion` / `append_event` / `ThemeRelationStore` の
  いずれの token も持たない。

---

## 2. SOURCE_ASSERTED の意味論監査（§2） — **BLOCKING**

### 2.1 凍結された意味

```
SOURCE_ASSERTED_MEANING     = "the cited source asserted this relation"
SOURCE_ASSERTED_NON_MEANING = "the system verified this relation as causal truth"
```

すなわち `SOURCE_ASSERTED` は「**指定された source が relation semantics（source → relation_type → target）を
主張し、それを人間が SOURCE_ASSERTED として受理した**」ことの記録である。「citation が存在する」ことではない。

### 2.2 現行 runtime の適格判定

```python
def source_authority_available(proposal: RelationProposal) -> bool:
    return proposal.source_attribution is not None and len(proposal.evidence_refs) >= 1
```

`relation_proposal_store._validate_decision` と `relation_proposal_bridge` の SOURCE_ASSERTED 分岐は、
どちらもこの述語だけを見る。すなわち適格性は **「帰属 field が非 None」かつ「citation が 1 件以上」** の
2 条件の構造的存在のみで決まる。

### 2.3 A / B / C / D / E / F の判定

| case | 状況 | 現行 runtime | 判定 |
|---|---|---|---|
| A | RULE / LLM が出典の主張を抽出し、帰属と citation を保持 → 人間が SOURCE_ASSERTED で受理 | 受理される | 期待どおり |
| B | RULE / LLM が独自推論し、**無関係な出典**の citation を後付け → SOURCE_ASSERTED を試みる | **受理される** | **GAP** |
| B' | citation の `attribution` field が**空**でも SOURCE_ASSERTED を試みる | **受理される** | **GAP** |
| C | citation は在るが、出典は entity / topic に言及しただけで関係を主張していない | **受理される** | **GAP** |
| D | 出典が関係を主張しているが帰属 field が無い | `FORBIDDEN_SOURCE_AUTHORITY` | 期待どおり |
| E | 帰属は在るが citation が 1 件も無い | `FORBIDDEN_SOURCE_AUTHORITY` | 期待どおり |
| F | LLM 提案を人間が HUMAN_ASSERTED として受理（人間の rationale 付き） | 受理・帰属は None・提案者 class は保持 | 期待どおり |

### 2.4 GAP の具体的内容（3 点）

1. **帰属と citation の対応が検査されない。** `source_attribution.attributed_to` が `publisher:example_wire` で、
   唯一の citation の `attribution` が `publisher:other_wire`（別 source）であっても、
   あるいは citation の `attribution` が空文字であっても、適格性は成立する。
   「誰が述べたか」と「どこで述べたか」が同一 source を指す保証が無い。
2. **主張の所在（assertion locus）を記録する field が無い。** `RelationEvidenceRef.locator` は
   contract の無い自由 text であり、「出典のこの箇所で relation semantics を主張した」と
   「出典はこの箇所で両 Theme に言及しただけ」を区別しない。
3. **人間が何を検証したかが record に残らない。** plan / assertion に
   `semantic_basis` / `assertion_locus` / `verified_claim` に相当する field は存在しない。
   したがって case A と case B は、著者が同じ field を埋めた場合 **plan の canonical bytes まで完全に一致する**
   （test `test_b5d_18_case_a_and_case_b_can_produce_byte_identical_plans`）。

### 2.5 判定

現行 B5C contract / model は A と B / C を**構造的に区別できない**。適格性は citation ＋ 帰属の
存在だけで成立する。監督指示のとおり、これをテストで無理に PASS にせず、
**`B5C_REMEDIATION_REQUIRED`** として停止する。B5D では新しい semantic verifier を実装していない。

なお安全側の退避路（case F: HUMAN_ASSERTED として人間が自分の名前で主張する）は健全であり、
`ATTRIBUTION_FORBIDDEN` に従って帰属が plan から落ち、提案者 class は `proposal_origin` に残る。
**遮断されているのは「RULE / LLM が authority の主張 class になること」であって、
「構造だけ整えた提案が SOURCE_ASSERTED になること」は遮断されていない。**

---

## 3. B5C 最終報告 §8 の矛盾の決着（§3）

B5C 最終報告 §8 の 2 文は次のとおりだった。

- (a) 「RULE / LLM の提案でも source attribution と citation を持てば `SOURCE_ASSERTED` になれる」
- (b) 「`FORBIDDEN_SOURCE_AUTHORITY` で拒否する」

**結論: runtime contract の矛盾ではない。報告文の typo でもない。両者は同一述語の 2 分岐である。**

`FORBIDDEN_SOURCE_AUTHORITY` は `source_authority_available(proposal)` が false のときにのみ送出され、
提案者 class は条件に入らない。したがって

- 帰属 ＋ citation が在る → (a) の経路（提案者 class を問わず受理可能）
- どちらかが欠ける → (b) の経路（提案者 class を問わず拒否）

であり、4 提案者 class すべてで述語と結果が一致することを test で固定した
（`test_b5d_26_forbidden_source_authority_fires_iff_the_predicate_is_false`、
`test_b5d_27_store_and_bridge_agree_on_the_predicate_for_every_proposer_class`）。

**報告文の不足は「矛盾」ではなく「述語が構造的であることを明示していなかった」点にある。**
本 gate では doc 側でこれを明確化した（§2）。runtime semantics は変更していない。

---

## 4. 提案収束 matrix（§4） — 判定 **A. intentional and operationally safe**

identity は「候補となる主張そのもの」であり provenance（提案者 class / ref / rule_version / note）と
`created_at` を含まない。canonical bytes は record 全体なのでそれらを含む。

| case | 差異 | `proposal_id` | identity payload | canonical bytes | 2 件目の append | provenance |
|---|---|---|---|---|---|---|
| 1 | proposer_class が違う | 同一 | 同一 | 相違 | `CONFLICT` | 1 件目のものが残る |
| 2 | proposer_ref が違う | 同一 | 同一 | 相違 | `CONFLICT` | 1 件目のものが残る |
| 3 | rule_version が違う | 同一 | 同一 | 相違 | `CONFLICT` | 1 件目のものが残る |
| 4 | citation 集合が実質的に違う | 相違 | 相違 | 相違 | `APPENDED`（別提案） | 両方残る |
| 5 | rationale（意味）が実質的に違う | 相違 | 相違 | 相違 | `APPENDED`（別提案） | 両方残る |
| 補 | `created_at` が違う | 同一 | 同一 | 相違 | `CONFLICT` | 1 件目のものが残る |
| 補 | 完全な byte 一致（決定論的 replay） | 同一 | 同一 | 同一 | `ALREADY_PRESENT`（冪等） | 変化なし |

### 4.1 B4C の収束原則との差異

**identity 規則は同じである。** B3 `ProposalProvenance` も identity 外（audit-only）であり、
B4C は `TEMPLATE_PROVENANCE_REF = "discovery:mechanism_template"` を固定値にして
rule id / version を内容から意図的に排除し、等価な提案が rule を跨いで収束するようにしている。

**差異は producer 層の有無である。**

- **B4C**: 収束は決定論的 discovery run の**内部で畳まれる**。複数 rule が同 id を出した場合、出力は 1 件
  （rule_id 順の最初の provenance）で、収束の事実は派生 run report の
  `emitted_proposal_ids` / `converged_proposal_ids` に残る。さらに既存 proposal に一致すれば
  `suppressed_existing_ids` として返さない。**store は「同 id ＋ 異 bytes」を見ない。**
- **B5C**: 関係の自動発見は contract 上**禁止**されている（§8）ため producer 層が存在しない。
  収束が現れうる場所は store の append だけであり、そこでは `CONFLICT` になる。

### 4.2 判定と根拠

**A. intentional and operationally safe** と判定する。

1. **`CONFLICT` は fail closed であり、laundering を生まない。** 黙って merge しない、
   2 番目の提案者の provenance を 1 番目のものとして記録しない、authority を失わない。
   これは P5 / Foundation / B3 / B5B と同一の規律である。
2. **「2 つの正常な discovery producer が同じ提案を見つける」事象が B5C には構造的に存在しない。**
   B5C は関係の自動発見を持たない（§8 で test 固定）。提案は人間または明示的な 1 回の記録行為で作られる。
   したがって `CONFLICT` は日常的に発生しない。
3. **運用経路が store API 上に既に在る。** `get_proposal(proposal_id)` で記録済みかを確認し、
   在ればそれを使って決定 chain を進める（test `test_b5d_36_the_check_then_reuse_path_avoids_the_conflict_entirely`）。
   意味論的 field は byte 一致なので、失われるのは 2 度目の発見行為の provenance だけである。
4. **決定論的 replay は冪等になる。** `created_at` を入力から導いていれば byte 一致で `ALREADY_PRESENT`。
   現在時刻で埋めた場合に `CONFLICT` になるのは、時刻 source の誤りを検出している正しい挙動である。

ただし次の 2 点を**運用上の不足**として登録する（safety の欠陥ではなく、文書化と診断の不足）。

- (i) 「2 番目の producer は append せず記録済み提案を使う」という check-then-reuse 契約が
  B5C contract doc に書かれていない（B4C には suppression として書かれている）。本 gate の doc で明記した。
- (ii) 収束由来の `CONFLICT` と、record 改変由来の `CONFLICT` が失敗語彙上で区別できない。
  運用者が「2 提案者が一致した」と「誰かが record を書き換えた」を見分けられない。

---

## 5. 決定 graph の敵対的集合（§5）

| 入力 | derived status | plan |
|---|---|---|
| 決定なし | `OPEN` | `PROPOSAL_NOT_ACCEPTED:OPEN` |
| ACCEPT | `ACCEPTED` | 生成 |
| REJECT | `REJECTED` | `PROPOSAL_NOT_ACCEPTED:REJECTED` |
| DEFER | `OPEN_DEFERRED` | `PROPOSAL_NOT_ACCEPTED:OPEN_DEFERRED` |
| REJECT → ACCEPT | `ACCEPTED` | 生成（終端 ACCEPT） |
| DEFER → ACCEPT | `ACCEPTED` | 生成（終端 ACCEPT） |
| ACCEPT → REJECT | `REJECTED` | 拒否（古い ACCEPT は勝たない） |
| fork | `OPEN_UNRESOLVED`（`FORK`） | 拒否 |
| 複数 genesis | `OPEN_UNRESOLVED`（`MULTIPLE_STARTS`） | 拒否 |
| dangling predecessor | `INVALID_DECISION_HISTORY` | 拒否。store は `MISSING_PREDECESSOR` |
| 別 proposal の predecessor | `INVALID_DECISION_HISTORY` | 拒否。store は `WRONG_PROPOSAL_PREDECESSOR` |
| cycle | `INVALID_DECISION_HISTORY`（`CYCLE`） | 拒否 |
| 物理順を混ぜる（11 seed） | 不変 | plan の canonical bytes が不変 |
| chain 外の最新 ACCEPT | `OPEN_UNRESOLVED` | 拒否 |

**latest-wins は無い。** 勝者は `supersedes_decision_id` の graph 終端だけで決まり、`recorded_at` も
物理順も勝者を決めない。content id のため手で cycle を作ることはできず（`INVALID_RECORD_ID`）、
resolver 単体へ duck-typed な循環入力を与えて `CYCLE` を固定した。

---

## 6. 訂正と B5B governance の相互作用（§6）

| 入力 | 結果 |
|---|---|
| 終端 assertion への訂正 | 生成（`previous_assertion_id` と `edge_key` を保持） |
| 未知の assertion への訂正 | `PREDECESSOR_NOT_FOUND` |
| 別 edge の assertion への訂正 | `PREDECESSOR_WRONG_EDGE` |
| 非終端 assertion への訂正 | `PREDECESSOR_NOT_TERMINAL` |
| 既存 authority と同内容の訂正 | `RELATION_ALREADY_AUTHORITATIVE` |
| 開始済み edge への NEW_RELATION（内容が違う） | `EDGE_ALREADY_STARTED` |
| 開始済み edge への NEW_RELATION（内容が同じ） | `RELATION_ALREADY_AUTHORITATIVE` |
| **撤回済み関係 ＋ ACCEPT だけ** | **`RELATION_RETRACTED_REQUIRES_GOVERNANCE`（自動 RESTORE しない）** |
| 復帰済み関係への訂正 | 生成 |
| 端点が SUPERSEDED / RETIRED | 生成（`ENDPOINT_SUPERSEDED:SOURCE` / `ENDPOINT_RETIRED:SOURCE` を注記） |
| 端点が未知 / 未作成 | `ENDPOINT_NOT_AVAILABLE:SOURCE:UNKNOWN_ROOT` / `:NOT_CREATED_YET` |

**撤回された関係は ACCEPT だけで自動 RESTORE されない。** NEW_RELATION でも CORRECTION でも
`RELATION_RETRACTED_REQUIRES_GOVERNANCE` で拒否される。復帰は B5B governance event だけが行う。

---

## 7. 因果安全性の合成 corpus（§7） — **synthetic gate result only**

以下は完全に合成した 14 行の corpus に対する **synthetic gate result only** である。
実世界の precision / recall を主張しない。B5D では NLP 分類器を作っていない。

| # | 根拠 | 帰属 | citation | SOURCE_ASSERTED 構造適格 | contract が保証すること | 人間の査読 |
|---|---|---|---|---|---|---|
| 1 | 両 Theme が同一記事に現れるだけ（純共起） | なし | 0 | 不成立 | 提案は生まれない | 必須 |
| 2 | entity が共通するだけ | なし | 0 | 不成立 | 提案は生まれない | 必須 |
| 3 | taxonomy slug が共通するだけ | なし | 0 | 不成立 | 提案は生まれない | 必須 |
| 4 | 同一 evidence を両 Theme が参照するだけ | なし | 1 | 不成立 | 提案は生まれない | 必須 |
| 5 | 時間的な前後関係だけ | なし | 0 | 不成立 | 提案は生まれない | 必須 |
| 6 | 価格の相関だけ | なし | 0 | 不成立 | 提案は生まれない | 必須 |
| 7 | 見出しが因果的語法だが出典は関係を主張していない | あり | 1 | **成立** | 人間の ACCEPT が必要 | 必須 |
| 8 | 出典が「A は B を引き起こす」と明示 | あり | 1 | 成立 | 人間の ACCEPT が必要 | 必須 |
| 9 | 出典が「A と B は関連する」と述べた | あり | 1 | **成立** | 人間の ACCEPT が必要 | 必須 |
| 10 | 出典が「A は B に寄与しうる」と述べた | あり | 1 | **成立** | 人間の ACCEPT が必要 | 必須 |
| 11 | 出典が「A は B を引き起こさない」と述べた | あり | 1 | **成立** | 人間の ACCEPT が必要 | 必須 |
| 12 | LLM の因果仮説（出典の裏付けなし） | なし | 1 | 不成立 | SOURCE_ASSERTED は構造的に拒否 | 必須 |
| 13 | rule の因果仮説（出典の裏付けなし） | なし | 1 | 不成立 | SOURCE_ASSERTED は構造的に拒否 | 必須 |
| 14 | 人間が自分の名前で因果を主張 | なし | 1 | 不成立 | SOURCE_ASSERTED は構造的に拒否 | 必須 |

### 7.1 保証の境界

**行 7 / 8 / 9 / 10 / 11 は runtime から区別できない。** 「引き起こす」「関連する」「寄与しうる」
「引き起こさない」のいずれを出典が述べたかは record に現れず、5 行すべてで
`source_authority_available` が成立し、plan の field 集合も同一である。
**contract の保証はここで終わり、人間の査読がここから始まる。** これが §2 の GAP の実務的な帰結である。

行 1〜6（純共起 / entity / taxonomy / evidence / 時間 / 相関）は、帰属が無いため
`FORBIDDEN_SOURCE_AUTHORITY` で構造的に SOURCE_ASSERTED に到達できない。
ただし `HUMAN_ASSERTED` としてなら受理でき、そこでは人間が自分の名前で責任を負う。

---

## 8. 自動的な関係発見の不在（§8）

B5B / B5C の 8 module すべてについて、次の token が存在しないことを固定した。

`cooccur` / `co_occur` / `correlat` / `adjacen` / `overlap` / `similar` / `infer_relation` / `discover` /
`propose_relation` / `candidates_from` / `ThemeCandidateProposal` / `DiscoveryRun` / `RunReport` /
`AdapterResult` / `NewsItem` / `Observation` / `SourceDocument` / `Fact`

唯一の除外: `relation_resolution` は**記録済み辺**の cycle 検出に隣接表（`adjacency`）を使う。
これは履歴検査であり発見ではない。

さらに固定したこと。

- B5 module は `discovery` / `adapter` / `taxonomy` / `entity` / `knowledge` / `dedup` / `databank` /
  `facts` / `market` / `sources` / `corpus` のいずれも import しない。
- `RelationProposal.build` の必須引数は
  `source_theme_root_id` / `target_theme_root_id` / `relation_type` / `rationale` / `provenance` / `created_at`。
  corpus から自動で埋まる default は無い。
- package 内に `RelationProposal` を返す関数は 1 つも無い（`build` classmethod だけが構築点）。
- Theme 隣接や B4 `ThemeCandidateProposal` から relation 層へ至る import 経路が無い。

---

## 9. 推移的 authority の不在（§9）

`A CAUSES B` と `B CAUSES C` を B5B authority として記録しても、

- resolution の辺は 2 件のまま（`A CAUSES C` は現れない）。
- `relations_between(A, C)` は空。`neighbors(A)` に C は含まれない。
- graph view に `path` / `reach` / `closure` / `transitive` / `ancestors` / `descendants` / `walk` /
  `traverse` / `depth` に相当する面が無い。公開 method は
  `outgoing` / `incoming` / `neighbors` / `relations_between` / `relations_by_type` / `roots` / `to_plain` の 7 つだけ。
- `A CAUSES C` の plan は、明示的な提案と人間の ACCEPT があって初めて生成される。
  その plan にも独自の citation が必要で、帰属が無ければ `FORBIDDEN_SOURCE_AUTHORITY` で拒否される。

---

## 10. PIT / replay / 決定論（§10）

- plan 時刻は提案・決定時刻と**等しくてよい**。1 マイクロ秒早ければ
  `PLAN_BEFORE_PROPOSAL` / `PLAN_BEFORE_DECISION`。
- 未来の提案を過去に plan できない。未来の端点は `ENDPOINT_NOT_AVAILABLE:TARGET:NOT_CREATED_YET`、
  厳密に同時刻なら `EXISTS_AT_CUTOFF`。歴史的な端点は解決する。
- `PLAN_BEFORE_EVIDENCE_TIME` は防御的分岐として到達しない。model が `evidence_time <= created_at` を、
  bridge が `plan >= created_at` を強制するため（B5C contract §13 と同じ事実を再確認した）。
- 11 seed の決定順シャッフルで、derived status と plan の canonical bytes が不変。
- 提案・決定の canonical bytes は `from_dict` 往復で不変。store を 3 回開き直しても plan bytes が不変。
- B5 runtime 8 module に `.now(` / `utcnow` / `time.time` / `random.` / `secrets.` / `uuid` は無い。

---

## 11. store 破損 / conflict（§11）

| 入力 | 結果 |
|---|---|
| byte 一致の再 append（両 authority） | `ALREADY_PRESENT`。file size は不変 |
| 同 id ＋ 異 bytes | `CONFLICT`。file bytes は不変 |
| 内容を書き換えた行（recorded_at 改変） | `INVALID_RECORD` / `NON_CANONICAL_LINE` |
| 終端子の無い最終行 | `TRUNCATED_FINAL_LINE` |
| JSON でない行 | `MALFORMED_JSON` |
| 未知 schema | `UNSUPPORTED_SCHEMA_VERSION` |
| JSON object でない行 | `NOT_AN_OBJECT` |
| 空行 | `BLANK_LINE` |
| content id の不一致 | `INVALID_RECORD` |
| 外部からの追記 | `CONCURRENT_MODIFICATION`（byte 長で検知） |
| read-only での append | `READ_ONLY` |
| 破損したまま 2 度開く | 2 度とも fail closed。bytes は不変 |
| 空 / 空白の data_root | `DATA_ROOT_REQUIRED` |

`relation_proposal_store` に `migrat` / `repair` / `os.replace` / `truncate(` / `unlink(` の token は無く、
`fsync` は存在する。**黙って修復せず、migration せず、単一 writer である。**

---

## 12. Foundation / B5B authority の非改変（§12）

- Foundation 代表 world（`stop_after="accepted"`）の 5 authority file の生 bytes が、
  B5C の鎖を通す前後で**完全一致**。checkpoint `accepted` における Theme A / B の resolution digest も一致。
- B5B `relation_assertions.jsonl` / `relation_governance.jsonl` の bytes が、鎖と訂正 plan の導出の前後で
  **完全一致**（assertion 1 件 / governance 0 件のまま）。
- 同一 `data_root` 上で伸びた file は `relation_proposals.jsonl` と
  `relation_proposal_decisions.jsonl` の 2 つだけ。

---

## 13. 主張の限界（§13）

- 本 gate の corpus 結果は **synthetic gate result only**。実世界の precision / recall を主張しない。
- confusion matrix は作っていない（作る場合も同じ label を必須とする）。
- §2 の GAP は「構造的に区別できない」ことの記録であり、「区別されている」という保証ではない。
- 本 gate は B5B / B5C の runtime を検証しただけで、実行 gate（plan → B5B authority）は
  まだ存在しないため検証対象に含まれない。

---

## 14. 運用契約の明確化（本 gate で doc 側に追加した内容のみ）

runtime semantics は変更していない。次の 2 点を doc として明文化する。

1. **check-then-reuse**: 2 番目の提案者は `get_proposal(proposal_id)` で記録済みかを確認し、
   在れば append せずその提案を使って決定 chain を進める。意味論的 field は byte 一致であり、
   記録されないのは 2 度目の発見行為の provenance だけである。
2. **`SOURCE_ASSERTED` 適格判定は構造的である**: 帰属 field が非 None かつ citation が 1 件以上、という
   2 条件のみ。出典が relation semantics を主張したかどうかの判断は**人間の査読だけが担う**。
   現行 record model にはその判断を残す field が無い（§2 の GAP）。

---

## 15. 監督者の決定が必要な事項

| # | 事項 | 提案（実装せず） |
|---|---|---|
| B5D-D1 | §2 の GAP をどう閉じるか | (a) `RelationEvidenceRef.attribution` と `source_attribution.attribution_key` の一致を必須にする（構造的・後方互換に注意）／(b) 受理決定に `verified_claim` / `assertion_locus` の必須 field を追加する／(c) `SOURCE_ASSERTED` を凍結し、意味論の検証を別 record 型に委ねる |
| B5D-D2 | GAP を閉じるまでの暫定運用 | `SOURCE_ASSERTED` の受理を一時停止し `HUMAN_ASSERTED` だけを使う運用を許すか |
| B5D-D3 | 収束由来 `CONFLICT` の診断 | 失敗語彙に `CONVERGENT_PROPOSAL`（同 id ＋ provenance のみ相違）を追加して改変由来と区別するか |
| B5D-D4 | check-then-reuse の実装位置 | producer 側の規約に留めるか、store に `append_or_reuse` を追加するか |
| B5D-D5 | 2 度目の発見の記録 | co-discovery を記録する必要があるか（B4C の `converged_proposal_ids` 相当） |
| B5D-D6 | B4A 監査 doc の ticker 例（B4 closeout 繰越 #17） | 凍結 anchor のため未修正。remediation の可否 |

---

## 16. B5D が変更した file

test と doc と CHANGELOG のみ。runtime は無変更。

- `tests/intelligence/test_theme_relation_e2e.py`【新規】
- `tests/intelligence/test_theme_relation_causal_safety.py`【新規】
- `docs/databank/PHASE6_THEME_RELATION_E2E_AUTHORITY_GATE.md`【新規】
- `CHANGELOG.md`

---

## 17. 付録 — P6-B5C-R1 remediation の結果（本 gate の §2 blocker に対する応答）

B5D 判定 `P6_B5C_REMEDIATION_REQUIRED` に対し、P6-B5C-R1 で `SourceClaimVerification` を導入した。
**B5B は無変更。意味論の自動判定は導入していない。**

### 17.1 §2.4 の GAP 3 点の閉じ方

| GAP | R1 での対応 |
|---|---|
| 帰属と citation の対応が検査されない | 確認の帰属が提案の帰属と厳密一致し、かつ**その citation 自身の帰属**も同じ出典を指すことを必須化。citation の帰属が空文字なら不適格（`VERIFICATION_CITATION_ATTRIBUTION_MISMATCH`） |
| 主張の所在を記録する field が無い | `assertion_locus`（必須・非空）と `claim_summary`（必須・非空）を確認 record に追加 |
| 人間が何を検証したかが残らない | 確認は ACCEPT 決定の identity に入り、plan の `verification_origin` に丸ごと保存される |

### 17.2 §2.3 の case 表（R1 後）

| case | 状況 | R1 後の runtime |
|---|---|---|
| A | 出典の主張を抽出し、人間が所在を確認 | 受理（`verification_origin` に所在と要約が残る） |
| B | 無関係な出典の citation を後付け | `VERIFICATION_CITATION_ATTRIBUTION_MISMATCH` |
| B' | citation の帰属が空 | `VERIFICATION_CITATION_ATTRIBUTION_MISMATCH` |
| C | 言及のみの citation | 確認なしでは組み立て不可（`MISSING_SOURCE_CLAIM_VERIFICATION`） |
| D | 帰属なし | `MISSING_SOURCE_ATTRIBUTION` |
| E | citation なし | `MISSING_SOURCE_CITATION` |
| F | LLM 提案 → HUMAN_ASSERTED | 受理（確認は不要。付けると `SOURCE_CLAIM_VERIFICATION_FORBIDDEN`） |
| G | 確認の出典が違う | `VERIFICATION_ATTRIBUTION_MISMATCH` |
| H | 確認の citation が違う | `VERIFICATION_CITATION_MISMATCH` |
| I | 確認の source root が違う | `VERIFICATION_ENDPOINT_MISMATCH` |
| J | 確認の target root が違う | `VERIFICATION_ENDPOINT_MISMATCH` |
| K | 確認の関係型が違う | `VERIFICATION_RELATION_TYPE_MISMATCH` |
| L | 確認者が人間でない | `FORBIDDEN_VERIFICATION_AUTHORITY`（model 段階） |
| M | 確認が決定より後 | `VERIFICATION_AFTER_DECISION`（model 段階） |
| N | 別の意味論の提案へ確認を使い回す | 端点 / 関係型 / 帰属 / citation のいずれかで不一致 |

### 17.3 §7 corpus への影響

行 7 / 9 / 10 / 11（見出しの語法 / 関連 / 可能性 / 否定）は、**いずれも人間の出典主張確認なしには
`SOURCE_ASSERTED` へ到達できなくなった**。系が保証するのは「citation の存在が黙って権威へ昇格しないこと」であり、
「出典が客観的にその関係を証明していること」ではない。この境界は R1 後も変わらない（§17.4）。

### 17.4 残る限界（変わらない）

人間は誤った確認を行いうる。系はそれを検出しない。R1 が閉じたのは
**「構造だけ整えた提案が、人間の明示的な確認なしに `SOURCE_ASSERTED` になる」経路**であって、
「出典が真にその関係を述べている」ことの保証ではない。

### 17.5 §15 の収束判定は据え置き

B5D §4 の判定（A. intentional and operationally safe）は R1 で変更していない。
`CONVERGENT_PROPOSAL` / `append_or_reuse` / co-discovery journal はいずれも未実装のまま繰り越す。
