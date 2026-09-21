# Phase 6 / P6-B5C — Theme relation 候補と人間の決定の契約

B5B の relation authority の **直前**に立つ提案・決定層の契約。

```
候補入力 → RelationProposal → 人間の decision → RelationAssertionPlan → 〔将来の実行 gate〕 → ThemeRelationAssertion
```

B5C は `RelationAssertionPlan` で止まる。B5B の authority には一切追記しない。

---

## 1. authority 境界

| 段階 | authority か |
|---|---|
| `RelationProposal` | **いいえ**（候補） |
| ACCEPT（`RelationProposalDecision`） | **いいえ**（受理という governance fact であって関係そのものではない） |
| `RelationAssertionPlan` | **いいえ**（派生。永続化しない） |
| `ThemeRelationAssertion`（B5B） | はい |

B5B に `ThemeRelationAssertion` を append できるのは、将来の明示的な実行 gate だけである。
B5C の module は `relation_store` を import も参照もしない（test で固定）。

## 2. 提案 type

`RELATION_CANDIDATE` の 1 つだけ。`CAUSES` / `AMPLIFIES` / `MITIGATES` / `DEPENDS_ON` ごとに提案種別を増やさない。
`relation_type` は提案の field である。B3 の `ProposalType` は変更していない。

## 3. 提案者 class

`HUMAN` / `SOURCE` / `RULE` / `LLM` の 4 つ。これは **誰が提案したか**であり、**authority の主張 class ではない**。

> `PROPOSER_IS_NOT_AUTHORITY = "a proposer class describes who proposed, not who asserts"`

B5B の authority 主張 class は `HUMAN_ASSERTED` / `SOURCE_ASSERTED` のままで、`RULE_ASSERTED` /
`LLM_ASSERTED` に相当する値は B5B にも B5C にも存在しない。

- RULE の提案 ≠ RULE_ASSERTED の関係
- LLM の提案 ≠ LLM_ASSERTED の関係

## 4. 提案 model

```
RelationProposal
  schema_version              identity
  proposal_type               identity（RELATION_CANDIDATE 固定）
  relation_vocab_version      identity
  proposal_id                 derived（identity payload の content id。threlprop_<24 hex>）
  source_theme_root_id        identity
  target_theme_root_id        identity
  relation_type               identity
  change_kind                 identity（NEW_RELATION / CORRECTION）
  previous_assertion_id       identity（CORRECTION のときのみ非空）
  source_attribution          identity（出典 X の主張 ≠ 出典 Y の主張）
  rationale                   identity
  evidence_refs               identity（canonical 順に整列）
  provenance                  audit（identity 外。canonical bytes には入る）
  created_at                  audit（identity 外。canonical bytes には入る）
```

- 乱数 id は無い。score / 確信度 / 順位 / 確率 / 強度の field は存在しない。
- `source == target` は `SELF_RELATION` で拒否される。**受理 plan に到達することはない。**
- `evidence_time <= created_at` を model 段階で強制する。

## 5. 提案の意味論的 identity

identity は「候補となる主張そのもの」であり、**それを見つけた機構ではない**。したがって提案者 class /
proposer_ref / rule_version / created_at は identity の外にある。

帰結（意図的）:

- 同じ主張を RULE が出しても人間が出しても `proposal_id` は同一になる（収束する）。
- ただし提案者が違えば canonical bytes は違うので、2 件目の append は **CONFLICT** になる。
  これは fail closed であり、黙って上書きしない。先に記録された提案が id を持ち、後続はその提案を使うか、
  意味の違う別の主張を記録する。

出典の帰属は identity に入る。「出典 X が A CAUSES B と述べた」と「出典 Y が A CAUSES B と述べた」は
別の主張だからである。

## 6. 因果安全性

`CAUSES` の候補は HUMAN / SOURCE / RULE / LLM のいずれからも提案できる。

しかし **受理されただけで RULE / LLM の提案が authority の CAUSES になることは無い**。受理は最終的な
主張 authority を明示しなければならず、選べるのは次の 2 つだけである。

| 受理 class | 条件 |
|---|---|
| `HUMAN_ASSERTED` | 受理した人間が自分の名前で主張する。提案者 class は問わない |
| `SOURCE_ASSERTED` | 提案に **出典の帰属と出典 evidence が実在する**場合のみ |

RULE / LLM という提案者 class は、出典の権威の代わりにならない（`FORBIDDEN_SOURCE_AUTHORITY`）。
これを **authority laundering の禁止**と呼ぶ。store と bridge の両方で拒否する。

`CAUSES` の plan は B5B と同じく evidence 参照 1 件以上を必須とする（B5B の制約を弱めない）。

## 7. SOURCE 提案の意味論

SOURCE 提案は「出典が明示的にその関係を述べた」ことを意味する。**系がその関係を真と認めた意味ではない。**

必須:

- `source_attribution.attributed_to`（誰が述べたか）
- evidence 参照 1 件以上（どこで述べたか）
- `rationale`（出典の主張の要約）

`SOURCE_ASSERTED` として受理された場合、帰属をそのまま plan に保つ。帰属を落として「無帰属の因果的真実」に
平坦化しない。B5B の凍結文言をそのまま引き継ぐ。

- `SOURCE_ASSERTED_MEANING = "the cited source asserted this relation"`
- `SOURCE_ASSERTED_NON_MEANING = "the system verified this relation as causal truth"`

## 8. RULE / LLM 提案

提案してよい。次はできない。

自分で ACCEPT する、最終 authority class を選ぶ、B5B に書く、検証済みの因果を主張する、入力に無い evidence を作る。

提案の出自は人間の ACCEPT のあとも plan に残り、監査できる。自動昇格は無い。

## 9. 決定 model

```
RelationProposalDecision
  schema_version / decision_id（threldec_<24 hex>）/ proposal_id
  decision                   ACCEPT / REJECT / DEFER のちょうど 3 つ
  accepted_assertion_class   ACCEPT のときのみ。HUMAN_ASSERTED か SOURCE_ASSERTED
  actor_class                HUMAN 固定
  actor_ref / reason
  supersedes_decision_id
  recorded_at                identity 外
```

- actor は人間だけ。RULE / LLM の actor は `FORBIDDEN_DECISION_AUTHORITY` で拒否される。自動 ACCEPT は無い。
- REJECT / DEFER に `accepted_assertion_class` があれば `ACCEPTED_AUTHORITY_FORBIDDEN`。
- ACCEPT に無ければ `MISSING_ACCEPTED_AUTHORITY`。

## 10. 決定 chain

B3 の governance 規律を **概念として**踏襲する（B3 の authority は再利用も変更もしない）。

追記専用の predecessor graph で解き、`recorded_at` も物理順も勝者を決めない（latest-wins は無い）。

| 構造 | derived status |
|---|---|
| decision 無し | `OPEN` |
| terminal が DEFER | `OPEN_DEFERRED` |
| terminal が ACCEPT | `ACCEPTED` |
| terminal が REJECT | `REJECTED` |
| fork / 複数 start | `OPEN_UNRESOLVED` |
| dangling predecessor / 別 proposal への参照 / 閉路 | `INVALID_DECISION_HISTORY` |

後の人間の決定は前の決定を supersede できる（REJECT → ACCEPT も可）。

## 11. 受理 authority の規則

| 受理 | 許可条件 |
|---|---|
| ACCEPT → `HUMAN_ASSERTED` | HUMAN / SOURCE / RULE / LLM のいずれの提案でも可。HUMAN 主張の要件（rationale、CAUSES の evidence）を満たすこと |
| ACCEPT → `SOURCE_ASSERTED` | 提案に出典の帰属 ＋ 出典 evidence が実在する場合のみ |

`HUMAN_ASSERTED` として受理した場合、plan の `source_attribution` は **None** になる（B5B の
`ATTRIBUTION_FORBIDDEN` に従う）。提案側の帰属は `proposal_origin.proposal_source_attribution` に残る。

## 12. 受理 plan

```
RelationAssertionPlan
  plan_version / relation_vocab_version
  source_theme_root_id / target_theme_root_id / relation_type / assertion_class
  source_attribution / rationale / evidence_refs / previous_assertion_id
  change_kind / edge_key / recorded_at
  source_endpoint / target_endpoint / diagnostics
  proposal_origin / decision_origin
```

- **journal identity を持たない。** `relation_assertion_id` を生成しない。永続化しない。
- B5B の `ThemeRelationAssertion` を組み立てるのに十分な材料をすべて持つ（test で実際に組み立てて確認する）。
- `to_plain()` / `canonical_line()` は決定論的。

## 13. plan の時刻

`recorded_at` は呼び出し側が供給する。現在時刻を読まない。

- aware でなければ `INVALID_RECORDED_AT`
- `>= proposal.created_at` → `PLAN_BEFORE_PROPOSAL`
- `>= decision.recorded_at` → `PLAN_BEFORE_DECISION`
- `>= evidence_time` → `PLAN_BEFORE_EVIDENCE_TIME`

なお model が `evidence_time <= created_at` を強制するため、最後の条件は前 2 条件から **含意される**。
防御的な検査として残してあり、等号境界は許可される。

## 14. 端点

B5C は `ThemeStore` を読まない。呼び出し側が read-only の端点 lookup（B5B の `EndpointLookup`）を渡す。

| 端点状態 | plan |
|---|---|
| `EXISTS_AT_CUTOFF` | 可 |
| `RETIRED` / `SUPERSEDED` | **可**。`ENDPOINT_RETIRED:<SOURCE\|TARGET>` / `ENDPOINT_SUPERSEDED:...` を注記。端点 id は書き換えない |
| `NOT_CREATED_YET` / `UNKNOWN_ROOT` | `ENDPOINT_NOT_AVAILABLE` で fail closed |

歴史的な端点 identity を B5B が支えているため、退役・後継の端点でも plan を許す。

## 15. 新規と訂正

`change_kind` で明示する。似ているからといって predecessor を推測しない。

| change_kind | 規律 |
|---|---|
| `NEW_RELATION` | `previous_assertion_id` は空でなければならない（`PREDECESSOR_FORBIDDEN`） |
| `CORRECTION` | `previous_assertion_id` が必須（`MISSING_PREDECESSOR`）。plan はそれをそのまま保つ |

CORRECTION の plan は、呼び出し側が渡した authority view に対して次を満たさなければならない。

- 対象 assertion が存在する（`PREDECESSOR_NOT_FOUND`）
- 同じ辺の履歴に属する（`PREDECESSOR_WRONG_EDGE`）
- その辺の terminal である（`PREDECESSOR_NOT_TERMINAL`）
- 辺が撤回されていない（`RELATION_RETRACTED_REQUIRES_GOVERNANCE`）

B5C は B5B に append しない。plan を返すだけである。

## 16. 既存 authority との相互作用

呼び出し側は現在の B5B 解決結果（`ResolvedRelation` の列）を渡してよい。

| 状況 | 結果 |
|---|---|
| 同じ辺 key が ACTIVE で、内容も同じ | `RELATION_ALREADY_AUTHORITATIVE`（黙って成功しない） |
| 同じ辺 key が ACTIVE で、内容が違い `NEW_RELATION` | `EDGE_ALREADY_STARTED`（訂正として出し直す） |
| 同じ辺 key が RETRACTED | `RELATION_RETRACTED_REQUIRES_GOVERNANCE`（自動復帰しない） |
| 意味の違う関係（別の辺 key）が存在する | 何も起きない。**自動 merge しない** |
| authority view が渡されない `NEW_RELATION` | plan を作る（照合は呼び出し側の責務） |

## 17. provenance

plan を通して次がすべて残る。

提案の出自（proposal_id / proposer_class / proposer_ref / rule_version / note / 提案 rationale /
提案側の帰属 / change_kind）、決定の出自（decision_id / decision / actor_class / actor_ref / reason /
recorded_at / supersedes）、受理された主張 authority（accepted_assertion_class）。

例: **LLM が提案 → 人間が HUMAN_ASSERTED として受理** は、

```
proposal_origin.proposer_class = LLM
assertion_class                = HUMAN_ASSERTED
```

として監査できる。人間が最初から提案したかのように履歴を書き換えない。

## 18. store

```
<data_root>/theme_intelligence/relation_proposals.jsonl
<data_root>/theme_intelligence/relation_proposal_decisions.jsonl
```

B3 の `ProposalStore` も B5B の `ThemeRelationStore` も再利用しない（pattern のみ踏襲）。

追記専用 / canonical 直列化 / 厳密な検証 / content id 照合 / 同 id ＋ byte 一致は冪等 /
同 id ＋ byte 相違は `CONFLICT` / 破損は fail closed / single writer / 明示 data_root /
`write → flush → fsync` / 外部変更は byte 長で検知 / read-only mode / 修復なし / migration なし /
行の読み飛ばしなし / 現在時刻なし。

決定の追記規律: 対象 proposal が実在すること、chain が分岐しないこと、`SOURCE_ASSERTED` の受理は
提案に帰属と citation がある場合のみ。

## 19. import 境界

| module | 依存 |
|---|---|
| `relation_proposal_model.py` | stdlib、`core.ids`、`core.time`、`themes.model`（read-only 型）、`relation_model` |
| `relation_proposal_resolution.py` | stdlib、`relation_proposal_model` |
| `relation_proposal_bridge.py` | stdlib、`core.time`、`themes.model`、`relation_model`、`relation_resolution`、`relation_proposal_model`、`relation_proposal_resolution` |
| `relation_proposal_store.py` | stdlib（`os` / `pathlib`）、`relation_model`、`relation_proposal_model` |

禁止: `relation_store` の追記 API、`themes.store` / `themes.operations` / `themes.revision`、
B3 `proposal_store` / `proposal_model`、B4 discovery、taxonomy / entity catalog、lifecycle / change、
P5 calibration、network、LLM SDK、公開 module。

先行 phase は B5C を import しない。

## 20. 失敗語彙

**model**: `SELF_RELATION` / `UNKNOWN_THEME_ROOT` / `MISSING_FIELD` / `MISSING_SOURCE_ATTRIBUTION` /
`MISSING_SOURCE_CITATION` / `MISSING_PREDECESSOR` / `PREDECESSOR_FORBIDDEN` / `DUPLICATE_EVIDENCE_REF` /
`EVIDENCE_AFTER_RECORD` / `FORBIDDEN_DECISION_AUTHORITY` / `MISSING_ACCEPTED_AUTHORITY` /
`ACCEPTED_AUTHORITY_FORBIDDEN` / `INVALID_VOCABULARY` / `UNSUPPORTED_SCHEMA_VERSION` / `INVALID_RECORD_ID` /
`UNKNOWN_FIELD` / `PROHIBITED_CONTENT` / `FIELD_TOO_LONG` / `INVALID_TEXT` / `INVALID_TIME` / `INVALID_TYPE`

**store**: 破損 12 種 ＋ `PROPOSAL_NOT_FOUND` / `MISSING_PREDECESSOR` / `WRONG_PROPOSAL_PREDECESSOR` /
`NOT_TERMINAL_PREDECESSOR` / `NON_MONOTONIC_RECORDED_AT` / `FORBIDDEN_SOURCE_AUTHORITY` / `READ_ONLY` /
`DATA_ROOT_REQUIRED` / `CONFLICT` / `CONCURRENT_MODIFICATION`

**bridge**: `INVALID_PROPOSAL_TYPE` / `PROPOSAL_NOT_ACCEPTED` / `MISSING_ACCEPTED_AUTHORITY` /
`FORBIDDEN_SOURCE_AUTHORITY` / `MISSING_CAUSAL_EVIDENCE` / `INVALID_RECORDED_AT` / `PLAN_BEFORE_PROPOSAL` /
`PLAN_BEFORE_DECISION` / `PLAN_BEFORE_EVIDENCE_TIME` / `ENDPOINT_NOT_AVAILABLE` / `PREDECESSOR_NOT_FOUND` /
`PREDECESSOR_WRONG_EDGE` / `PREDECESSOR_NOT_TERMINAL` / `RELATION_RETRACTED_REQUIRES_GOVERNANCE` /
`RELATION_ALREADY_AUTHORITATIVE` / `EDGE_ALREADY_STARTED` / `INVALID_TYPE`

**注記（失敗ではない）**: `ENDPOINT_RETIRED` / `ENDPOINT_SUPERSEDED`

## 21. 除外事項（B5C に無いもの）

relation の自動生成（taxonomy 重複 / entity 重複 / Theme 共起 / B4 discovery / ThemeChangeSet / LLM 呼び出し /
rule engine / 価格相関）、B5B authority への追記、類似度による重複検出、score / 順位 / 確信度、
監視、runner / workflow、公開出力、Foundation / B3 / B4 / B5B の変更。

提案は **明示的な model 入力**としてのみ作られる。test は提案を明示的に構築する。

## 22. version 方針

`RELATION_PROPOSAL_SCHEMA_VERSION` = `theme_relation_proposal:0.1.0`、
`RELATION_DECISION_SCHEMA_VERSION` = `theme_relation_proposal_decision:0.1.0`、
`RELATION_PLAN_VERSION` = `theme_relation_assertion_plan:0.1.0`。

提案 identity の構成・提案者 class・決定 kind・受理できる主張 class を変えることは schema version の変更であり、
既存 version の意味を後から変えない。`relation_vocab_version` は B5B と共有し、関係語彙を増やすのは B5B 側の
version 変更である。

## 23. test matrix（実装済み）

| 区分 | 件数 | 内容 |
|---|---|---|
| MODEL | 11 | 4 提案者 class / 自己辺の拒否 / 4 関係型 / score 不在 / content id / 発見機構に依らない収束 / 帰属と evidence による識別 |
| SOURCE SAFETY | 4 | 帰属必須 / citation 必須 / 要約必須 / 真実を含意しない |
| DECISION | 14 | ACCEPT の 2 class / RULE・LLM の受理 / laundering 拒否 / REJECT / DEFER / supersede / fork / dangling / 閉路 / 物理順非依存 / 非人間 actor の拒否 |
| PLAN | 21 | 受理のみ plan 可 / CAUSES evidence / authority と両 origin の保存 / 端点 4 種 / 時刻 4 種 / 決定性 / authority identity 不在 / B5B assertion の構築可能性 |
| AUTHORITY INTERACTION | 8 | 既に authoritative / 撤回の非自動復帰 / 非 merge / 新規 / 訂正の predecessor 規律 |
| STORE | 12 | initialize / append / 冪等 / 衝突 / 破損 7 種 / 外部変更 / read-only / 再読み込み |
| BOUNDARY | 9 | 他 authority 非書き込み / discovery 不在 / network・LLM・時計不在 / 順位付け不在 / B5B append 不在 / 機密 |

合計 59 件（`test_theme_relation_proposal.py` 40 件、`test_theme_relation_proposal_store.py` 19 件）。
import 境界は `test_theme_intelligence_import_boundary.py` を additive に拡張して固定している。
