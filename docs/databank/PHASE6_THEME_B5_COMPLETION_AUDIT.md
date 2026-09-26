# PHASE 6 / P6-B5 CLOSEOUT AUDIT — THEME RELATION GRAPH 完了監査

対象: B5A（設計監査）→ B5B（relation authority）→ B5C（提案と人間の決定）→ B5C-R1（SOURCE_ASSERTED remediation）
→ B5D-RERUN（remediation 後の独立再検証）を **1 つの系**として監査する。

本書は READ-ONLY / DOCS-ONLY の成果物である。runtime・test・既存 B5 doc・knowledge・config・workflow・公開出力は
いずれも変更していない。

判定: **`P6_B5_COMPLETION_AUDIT_PASS_WITH_NON_BLOCKING_DEFERRED_ITEMS`**

---

## 1. B5 phase map

| gate | anchor | 成果 | test |
|---|---|---|---|
| B5A | `93d557d` | 読み取り専用の architecture 監査。監督者決定 B5-D1〜D10 を確定 | docs only |
| B5B | `78491c8` | relation authority（assertion / governance / PIT resolver / 記述 view / 追記 store） | 62 |
| B5C | `7baa2a4` | 提案 authority・人間の決定 authority・受理 plan（計画境界） | 75 |
| B5C-R1 | `c1cbe44` | `SourceClaimVerification` による SOURCE_ASSERTED remediation | （上記に含む） |
| B5D | `290f2e2` | 敵対的 E2E gate。SOURCE_ASSERTED の blocker を検出 | 214 |
| B5D-RERUN | `fb4b94c` | remediation 後の独立再検証。blocker CLOSED | 116 |

B5 関連 test 合計 **467**。

---

## 2. Authority map（層を畳まない）

```
A. relation semantics / contract      … 語彙と意味の凍結（B5A 決定 ＋ B5B 定数）
       ↓ 参照のみ
C. RelationProposal authority         … relation_proposals.jsonl（候補。authority ではない）
       ↓ 対象
D. RelationProposalDecision authority … relation_proposal_decisions.jsonl（人間の ACCEPT / REJECT / DEFER）
       ├ E. SourceClaimVerification   … D の record 内に埋め込まれた人間の確認（独立 journal ではない）
       ↓ 純関数の導出
F. RelationAssertionPlan              … 派生。永続化しない。authority ではない
       ↓
G. 実行 gate                          … **未実装**（本 phase に存在しない）
       ↓
B. ThemeRelationAssertion + governance … relation_assertions.jsonl / relation_governance.jsonl
```

### 2.1 明示的に証明した非同一性

| 命題 | 根拠 |
|---|---|
| Proposal ≠ relation authority | 提案 store は B5B の 2 file を読みも書きもしない。提案 append 後も B5B の bytes は不変 |
| ACCEPT ≠ relation authority | 受理しても B5B の assertion 件数は 0 のまま。受理は plan の前提条件にすぎない |
| SourceClaimVerification ≠ relation authority | 決定 record の一部として永続化されるだけで、独立 journal を持たない |
| RelationAssertionPlan ≠ relation authority | `relation_assertion_id` を持たず、`to_plain()` にも現れず、永続化されない |
| B5C は B5B に append しない | B5C の 4 module に `relation_store` / `ThemeRelationStore` / `append_assertion` / `append_event` の token が 1 つも無い |
| RULE / LLM provenance ≠ HUMAN provenance | `proposal_origin.proposer_class` は受理 class に関わらず保存され、HUMAN に書き換わらない |
| SOURCE_ASSERTED ≠ 客観的真実 | `SOURCE_ASSERTED_NON_MEANING` / `SOURCE_CLAIM_VERIFICATION_NON_MEANING` を凍結文言として plan に併記 |

---

## 3. B5A 照合（決定 B5-D1〜D10 と実装）

| 決定 | 内容 | 実装 | 状態 |
|---|---|---|---|
| B5-D1 | relation authority を Foundation と別の append-only store に置く | `<data_root>/theme_intelligence/relation_assertions.jsonl` ＋ `relation_governance.jsonl` | IMPLEMENTED（※1） |
| B5-D2 | 語彙は CAUSES / AMPLIFIES / MITIGATES / DEPENDS_ON の 4 型。`RELATED_TO` 不採用 | `RelationType` の 4 値のみ | IMPLEMENTED |
| B5-D3 | authority 主張 class は HUMAN_ASSERTED / SOURCE_ASSERTED のみ。RULE / LLM は提案止まり。CAUSES は evidence 必須 | `AssertionClass` の 2 値のみ。`EVIDENCE_REQUIRED_TYPES=(CAUSES,)` | IMPLEMENTED（R1 で強化） |
| B5-D4 | B5 内に独立した提案 ＋ 決定を持ち、B3 の規律のみ踏襲 | `relation_proposal_*` の 4 module。B3 は無変更 | IMPLEMENTED |
| B5-D5 | 訂正は assertion chain、撤回は governance event の二層 | `previous_assertion_id` ＋ `RETRACTED` / `RESTORED` | IMPLEMENTED |
| B5-D6 | 両端点 root が cutoff に存在すること。観測解決は要求しない。知識時間のみ | `endpoint_lookup` ＋ `ENDPOINT_PRESENT_STATES`。`effective_from` は不在 | IMPLEMENTED |
| B5-D7 | merge / split の自動移行なし。端点を書き換えない | `ENDPOINT_SUPERSEDED` / `ENDPOINT_RETIRED` の注記のみ | IMPLEMENTED |
| B5-D8 | SOURCE_ASSERTED は出典 ＋ 帰属必須。CAUSES は evidence 必須。source 件数を数えない | model と bridge の両方で強制。件数 field は無い | IMPLEMENTED（R1 で強化） |
| B5-D9 | graph query は記述的な読み取りのみ。ranking / centrality / 推移閉包を持たない | 公開 method は 7 つ（`outgoing` / `incoming` / `neighbors` / `relations_between` / `relations_by_type` / `roots` / `to_plain`） | IMPLEMENTED |
| B5-D10 | `theme_graph.yaml` は REFERENCE_ONLY。辺を port しない。`causal_rules` は入力として REJECT | B5 runtime に `theme_graph` / `causal_rule` の token が 0 件 | IMPLEMENTED |

### 3.1 意図的な逸脱（1 件）

**※1 — B5-D1 の file 名**: B5A は `relations.jsonl（＋ governance / proposal journal）` という形を示していたが、
B5B は `relation_assertions.jsonl` / `relation_governance.jsonl` を、B5C は
`relation_proposals.jsonl` / `relation_proposal_decisions.jsonl` を凍結した。
決定の実質（Foundation と別の append-only store、lineage との構造的分離）は満たしている。
file 名は B5B / B5C の contract doc で確定済みであり、後方互換の問題は無い（live data 無し）。

### 3.2 B5A の安全要件の確認

- relation graph は Foundation lineage と別 store・別 record 型である（Foundation 5 file を読み書きしない）。
- 辺は型付きかつ有向。逆辺 record を作らず、対称型も持たない。
- graph 構造から意味論的 authority が自動で生じない（§9）。
- 相関が因果へ黙って昇格しない（§9 / §11）。
- score / rank / probability / centrality の意味論を持たない。B5 runtime における該当 token は
  **「持たない」と宣言する docstring 4 行のみ**で、実行 code には 1 件も無い。
- 推移的 authority が無い（§9）。
- 公開出力 / P7 との結合が無い（`src/` のうち `theme_intelligence` の外から B5 を import する箇所は 0 件）。
- 高い意味論的 authority は人間が統治する（§8）。

---

## 4. B5B authority 監査（凍結維持）

| 観点 | 実装 |
|---|---|
| assertion identity | content id（`threl_<24hex>`）。provenance と `recorded_at` は identity 外、canonical bytes 内 |
| edge identity | `source|target|relation_type|assertion_class|attribution_key` の 5 segment derived key（record id ではない） |
| assertion class | HUMAN_ASSERTED / SOURCE_ASSERTED の 2 値のみ。RULE / LLM 相当の値は存在しない |
| SOURCE_ASSERTED 意味論 | `"the cited source asserted this relation"`。非意味は `"the system verified this relation as causal truth"` |
| HUMAN_ASSERTED 意味論 | 受理した人間が自分の名前で主張する。`source_attribution` は禁止（`ATTRIBUTION_FORBIDDEN`） |
| evidence 要求 | `CAUSES` は両 class で evidence ref 1 件以上（`MISSING_CAUSAL_EVIDENCE`） |
| 帰属規則 | SOURCE_ASSERTED は帰属必須、HUMAN_ASSERTED は帰属禁止 |
| governance | RETRACTED / RESTORED の event chain。撤回は主張本文を複製せず、履歴を消さない |
| 訂正 | `previous_assertion_id` の chain。終端からのみ継続 |
| PIT | `recorded_at <= cutoff`（等号可、+1µs 除外）。端点 root が cutoff に存在すること |
| 永続化 | 追記専用 JSONL。canonical 行のみ、write→flush→fsync、冪等、CONFLICT、fail closed、修復なし、migration なし、single writer |
| graph view | resolution からの派生。7 method の記述的読み取りのみ |
| 推移辺 | 生成しない |
| ranking / 推論 engine | 持たない |

B5B の 4 runtime file は anchor `78491c8` に対して **diff 0 行**。R1 も本 closeout も B5B に触れていない。

---

## 5. B5C 提案 / 決定 監査

| 観点 | 実装 |
|---|---|
| RelationProposal identity | 候補となる主張そのもの（11 key）。提案者 provenance と `created_at` は identity 外 |
| 提案者 class | HUMAN / SOURCE / RULE / LLM。**誰が提案したか**であり authority の主張 class ではない |
| provenance の保存 | `proposal_origin` に proposer_class / ref / rule_version / note / rationale / 提案側帰属 / change_kind が残る |
| 決定 | ACCEPT / REJECT / DEFER の 3 種。`actor_class` は HUMAN 固定（`FORBIDDEN_DECISION_AUTHORITY`） |
| 決定 chain | `supersedes_decision_id` の graph のみで解決。fork / 複数 genesis → UNRESOLVED、dangling / 別 proposal / cycle → INVALID |
| store | 提案・決定の 2 file。追記専用、B5B とも B3 とも別 file・別 object |
| fail closed | 破損 12 種 ＋ 履歴違反。読み飛ばさず、修復せず、migration しない |
| 訂正意味論 | CORRECTION は終端 assertion からのみ。既存 authority と同内容なら `RELATION_ALREADY_AUTHORITATIVE` |
| 端点意味論 | 呼び出し側の read-only lookup のみが答える。SUPERSEDED / RETIRED は注記して書き換えない |
| 収束 | 同一の主張は同一 `proposal_id`。provenance のみ異なる 2 件目の append は `CONFLICT`（fail closed） |
| 自動 append | 無い。B5B への追記経路が B5C に存在しない |

---

## 6. B5C-R1 — SOURCE_ASSERTED remediation の処理

### 6.1 元の欠陥（B5D が検出）

`SOURCE_ASSERTED` の適格判定が **「帰属 field が非 None」かつ「citation が 1 件以上」** という構造的存在だけで
成立し、**人間が何を確認したかを記録していなかった**。そのため次の 3 つが区別できなかった。

- 出典が関係を明示的に述べた（正当）
- citation が entity / topic に言及しただけ
- 機械の推論に無関係な citation を後付けした

さらに、帰属が指す出典と citation が指す出典の対応も検査されていなかった。

### 6.2 remediation

人間の `SourceClaimVerification` を **ACCEPT 決定に束ねる**。提案ではなく決定に置いたのは、提案は
「何が提案されたか」を、決定は「人間が何を査読し authorize したか」を記録するからである。
人間の査読の後から提案履歴を書き換えない。

### 6.3 最終 contract の束縛（9 軸 ＋ 時刻）

| 軸 | 要求 |
|---|---|
| 出典の帰属 | 提案の帰属と一致（`normalize_text` を両辺に適用したうえでの完全一致） |
| citation の kind / ref | 提案の evidence 集合に実在する 1 件を名指す |
| citation 自身の帰属 | 同じ出典を指す。**空文字は不適格** |
| 主張の所在 | 必須・非空・200 字上限 |
| 主張の要約 | 必須・非空・240 字上限。長文引用を要求しない |
| source root | 提案の source root と一致 |
| target root | 提案の target root と一致 |
| 関係型 | 提案の関係型と一致 |
| 確認者 | `ProvenanceClass.HUMAN` 固定 |
| 確認時刻 | `proposal.created_at <= verified_at <= decision.recorded_at` |

拒否語彙は `SOURCE_ASSERTED_REFUSAL_CODES` の 9 種に閉じ、store と bridge が同一関数を共有する。

### 6.4 意味の凍結

- `SOURCE_CLAIM_VERIFICATION_MEANING = "a person verified that the cited source asserted this relation"`
- `SOURCE_CLAIM_VERIFICATION_NON_MEANING = "a person verified that this relation is objectively true"`
- `CITATION_PRESENCE_IS_NOT_SOURCE_AUTHORITY = "a citation alone never carries source authority"`

**SOURCE_ASSERTED は「引用した出典がその関係を述べたことを、人間が確認した」という意味である。
「その関係が客観的に正しい」という意味ではない。**

---

## 7. B5D-RERUN の結果（独立した remediation 後検証）

| 項目 | 結果 |
|---|---|
| 元 blocker | **CLOSED**。citation の存在だけでも、帰属 ＋ citation だけでも適格にならない |
| 2 つ目の弱い述語 | **存在しない**。`source_asserted_refusal` の呼び出しは store と bridge の 2 箇所のみ。R1 前の `source_authority_available` は `src/` 全体で呼び出し 0 件 |
| A〜N 敵対的 matrix | PASS（bridge と store が同一 code を返す） |
| RULE / LLM 抽出の区別 | PASS（出典裏付き ＋ 人間の確認は許可、citation を貼っただけは拒否） |
| HUMAN_ASSERTED 非退行 | PASS（4 提案者 class すべて。確認は不要、付けると拒否） |
| B5B 互換性 | PASS（凍結 assertion を構築可能。確認 metadata は B5B の field に化けない） |
| authority 非改変 | PASS（Foundation 5 file と B5B 2 file が byte 一致） |
| 合成因果安全性 | PASS — **SYNTHETIC GATE RESULT ONLY**（実世界の precision / recall は主張しない） |
| 推移的推論の不在 | PASS |
| 収束 | 変化なし（A. intentional and operationally safe を維持） |
| store fail closed | PASS（改ざんされた確認 record を含む） |
| 凍結面 | PASS（15 anchor すべて） |

---

## 8. 人間の統治 chain（代表 flow）

| flow | 経路 | 結果 |
|---|---|---|
| FLOW 1 | LLM / RULE 提案 → 人間が HUMAN_ASSERTED で ACCEPT → plan | plan の帰属は None、`verification_origin` も None、提案者 class は保存。**authority append なし** |
| FLOW 2 | SOURCE / RULE / LLM 提案（出典素材あり）→ 人間の `SourceClaimVerification` → 人間が SOURCE_ASSERTED で ACCEPT → plan | plan が帰属と確認 provenance を保持。**authority append なし** |
| FLOW 3 | 提案 → REJECT | plan なし（`PROPOSAL_NOT_ACCEPTED:REJECTED`）。authority なし |
| FLOW 4 | 提案 → DEFER | plan なし（`PROPOSAL_NOT_ACCEPTED:OPEN_DEFERRED`）。authority なし |
| FLOW 5 | 撤回された B5B 関係 → 提案 ACCEPT | **`RELATION_RETRACTED_REQUIRES_GOVERNANCE`。NEW_RELATION でも CORRECTION でも黙って復帰しない**（本監査で実機確認済み） |

いずれの flow でも B5B authority への追記は発生しない。復帰は B5B governance event だけが行う。

---

## 9. 出典 / 因果の安全性 — 保証しないことの明示

B5 は次の**いずれも主張しない**。

| 主張しないこと | 状態 |
|---|---|
| 出典の真実性の検証 | しない。確認するのは帰属と主張の所在のみ |
| 自動的な意味論検証 | しない。NLP / LLM verifier は存在しない |
| 自動的な因果検出 | しない |
| 相関 → 因果 | しない |
| 共起 → 関係 | しない |
| taxonomy 重複 → 関係 | しない |
| entity 重複 → 関係 | しない |
| 時間近接 → 関係 | しない |
| graph 経路 → 関係 | しない |

### 9.1 系の限界（欠陥ではなく仕様）

**人間の確認そのものが誤っている可能性がある。系はそれを検出しない。**

B5 が保証するのは「citation の存在が黙って `SOURCE_ASSERTED` の権威へ昇格しないこと」であって、
「引用した出典が客観的にその関係を証明していること」ではない。これは意図した設計境界であり、
contract の保証はここで終わり、人間の査読がここから始まる。

---

## 10. Identity 監査

| 対象 | identity | 除外されるもの | 備考 |
|---|---|---|---|
| RelationProposal | content id（11 key の payload） | proposer provenance / `created_at` | 発見機構に依らず収束する |
| RelationProposalDecision | content id（確認を含む payload） | `recorded_at` | 確認した所在が違えば別 id |
| SourceClaimVerification | 独立 id を持たない | — | 決定の identity payload に内容として参加する |
| ThemeRelationAssertion | content id | provenance / `recorded_at` | B5B 凍結 |
| edge key | derived（5 segment） | — | record id ではない |
| governance event | content id | provenance / `recorded_at` | B5B 凍結 |
| RelationAssertionPlan | **identity を持たない** | — | authority ではないため |

### 10.1 収束意味論（凍結・D3〜D5 は未実装）

```
同一 proposal identity ＋ 異なる canonical bytes → CONFLICT
同一 proposal identity ＋ 同一 canonical bytes  → ALREADY_PRESENT（冪等）
```

provenance のみが異なる提案（proposer_class / proposer_ref / rule_version / created_at の差）は
同一 `proposal_id` に収束し、2 件目の append は `CONFLICT` で fail closed になる。
B5D §4 の判定（**A. intentional and operationally safe**）を維持する。
運用契約は check-then-reuse（`get_proposal` で確認し、在れば記録済み提案を使う）。

---

## 11. 時間軸 / PIT 監査

| 時間軸 | 所在 | 規律 |
|---|---|---|
| `proposal.created_at` | 提案 record | 呼び出し側が渡す。identity には入らない |
| `evidence_ref.evidence_time` | 提案 / assertion の evidence 参照 | `evidence_time <= created_at`（`EVIDENCE_AFTER_RECORD`） |
| `verification.verified_at` | 決定 record 内の確認 | `created_at <= verified_at <= decision.recorded_at` |
| `decision.recorded_at` | 決定 record | 前任より前に戻れない（`NON_MONOTONIC_RECORDED_AT`） |
| `plan.recorded_at` | 派生 plan | `>= proposal.created_at` かつ `>= decision.recorded_at` |
| B5B `recorded_at` | assertion / governance | 知識時間のみ。世界時間（`effective_from` / `effective_to`）は B5-D6 で繰延 |
| 端点 PIT | `endpoint_lookup` | root が cutoff に存在すること。等号可、+1µs 除外 |

- **現在時刻への依存なし**: B5 runtime 8 module に `.now(` / `utcnow` / `time.time` / `random.` / `secrets.` /
  `uuid` / `monotonic` が 0 件。
- **latest-wins なし**: 決定も assertion chain も `supersedes` graph の終端だけが勝つ。`recorded_at` も
  物理順も勝者を決めない。chain 外の最新 ACCEPT は勝たない。
- 11 seed の順序シャッフルで derived status と plan の canonical bytes が不変。

---

## 12. 永続化 map

### 12.1 永続化される authority（4 file）

| file | 所在 | 層 |
|---|---|---|
| `relation_assertions.jsonl` | `<data_root>/theme_intelligence/` | B（B5B relation authority） |
| `relation_governance.jsonl` | `<data_root>/theme_intelligence/` | B（B5B governance authority） |
| `relation_proposals.jsonl` | `<data_root>/theme_intelligence/` | C（B5C 提案 authority） |
| `relation_proposal_decisions.jsonl` | `<data_root>/theme_intelligence/` | D（B5C 人間の決定 authority） |

Foundation の 5 file（`theme_roots` / `theme_observations` / `theme_governance` / `theme_metadata` /
`theme_series_mappings`）と B3 の 2 file（`proposals` / `proposal_decisions`）は別物であり、B5 は触れない。

### 12.2 派生・非永続（authority ではない）

- `RelationAssertionPlan`（純関数の導出。identity を持たず、file に書かれない）
- graph view（`ThemeRelationGraphView`）
- resolution 結果（`ThemeRelationResolution` / `RelationDecisionResolution`）
- 検証 diagnostics（`FORK` / `CYCLE` / `ENDPOINT_SUPERSEDED` 等）

### 12.3 SourceClaimVerification の位置づけ

**独立した authority journal を持たない。** 人間の決定 record（`relation_proposal_decisions.jsonl`）の
一部としてのみ永続化され、決定の content identity に参加する。確認だけを単独で追記・差し替える経路は無い。

### 12.4 純関数 module の I/O 不在

`relation_model` / `relation_resolution` / `relation_graph` / `relation_proposal_model` /
`relation_proposal_resolution` / `relation_proposal_bridge` の 6 module に `open(` / `.write(` / `Path(` が
**0 件**。I/O を持つのは 2 つの store module のみ。

---

## 13. 依存方向 / import 監査

```
..core.ids / ..core.time / ..themes.model（Foundation の純粋 model）
        ↑                      ↑
  relation_model ──────────────┴──→ relation_resolution ──→ relation_graph
        ↑                                   ↑                     
        │                                   │              relation_store（I/O）
        │                                   │
  relation_proposal_model ──→ relation_proposal_resolution
        ↑            ↑                 ↑
        │            └─────────────────┴──→ relation_proposal_bridge ──→（relation_resolution を型として参照）
        │
  relation_proposal_store（I/O）
```

- **B5C は B5B の model / resolution 型を read-only で参照してよい**。`relation_proposal_bridge` は
  `.relation_model` と `.relation_resolution` を、`relation_proposal_store` は `.relation_model` を import する。
- **B5C は `relation_store` を import しない**（authority append 経路が物理的に存在しない）。本監査で
  4 module すべてについて token 0 件を確認。
- **Foundation は B5 を import しない**（`src/intelligence/themes/` に `theme_intelligence` の参照 0 件）。
- **`theme_intelligence` の外から B5 を import する箇所は `src/` 全体で 0 件**（公開出力 / P7 との結合なし）。
- 循環は無い（上図は DAG）。意味論的 authority の循環経路も無い。

---

## 14. RR-1 / RR-2 / RR-3 の処理

| # | 内容 | 状態 |
|---|---|---|
| **RR-1** | `relation_proposal_store.py` の module docstring に R1 前の文言（「出典の帰属と citation が実在する場合にのみ許す」）が残る。実行経路は `source_asserted_refusal` に一本化済みで挙動は正しい | **NON_BLOCKING_DEFERRED**。本 closeout では runtime を変更しない |
| **RR-2** | naive な時刻文字列の復元経路が、store が fail closed に写像する前に素の `ValueError` を出す。B5C 既存の `from_iso` 規約であり R1 由来ではない | **NON_BLOCKING_DEFERRED**。bypass ではない。closeout で例外型を局所的に揃えない |
| **RR-3** | `RelationAssertionPlan` は値 object で自前の検査を持たない | **POLICY_LOCKED / FUTURE_GATE_REQUIRED**（下記） |

### 14.1 RR-3 — 実行 gate への拘束（POLICY LOCKED）

将来の `RelationAssertionPlan` → B5B 実行 gate は、**渡された任意の `RelationAssertionPlan` object を
authority 入力として信頼してはならない。** 次のいずれかを必ず行うこと。

- **A**: authoritative な `RelationProposal` ＋ 有効な人間の `RelationProposalDecision`
  （SOURCE_ASSERTED のときは `SourceClaimVerification` を含む）から **plan を再導出する**。
- **B**: B5B への append 前に、それら authoritative record に対して**同等の不変条件を完全に再検証する**。

plan object を直接信頼することは**禁止**である。

---

## 15. B5 繰越 register（正本）

| # | 項目 | 状態 |
|---|---|---|
| D3 | 収束専用の診断語彙（例 `CONVERGENT_PROPOSAL`） | NON_BLOCKING_DEFERRED |
| D4 | `append_or_reuse` store API | NON_BLOCKING_DEFERRED |
| D5 | co-discovery / 収束提案 journal | NON_BLOCKING_DEFERRED |
| RR-1 | 古い module docstring | NON_BLOCKING_DEFERRED |
| RR-2 | naive 時刻の例外型の統一 | NON_BLOCKING_DEFERRED |
| RR-3 | 実行 gate は plan object を信頼しない | POLICY_LOCKED / FUTURE_GATE_REQUIRED |
| — | 実行 gate（`RelationAssertionPlan` → B5B append） | FUTURE_GATE_REQUIRED |
| — | 実世界の関係発見 / 因果精度の測定 | FUTURE_GATE_REQUIRED |
| — | 自動的な関係発見 | NOT_IMPLEMENTED / FUTURE_DESIGN |
| — | 意味論 / LLM の出典 verifier | NOT_IMPLEMENTED（B5 closeout に不要） |
| — | `assertion_locus` の表記規約 | OPTIONAL_DEFERRED |
| B4-17 | B4A 監査 doc の ticker 書式例を架空 ticker へ置換 | HISTORICAL_NON_BLOCKING_DEFERRED（凍結 anchor のため未着手） |
| B5-D2 | `CONSTRAINS` / `ENABLES` の語彙追加 | 第 2 段へ繰延（B5A 決定） |
| B5-D6 | 世界時間（`effective_from` / `effective_to`） | 繰延（B5A 決定） |
| B5-D7 | merge / split に伴う辺の移行 gate | 独立 gate へ繰延（B5A 決定） |

本 closeout ではいずれも実装していない。

---

## 16. 機密 / security 監査

| 観点 | 結果 |
|---|---|
| tracked な機密 PDF | 0 件 |
| credential / secret | 0 件 |
| machine-specific な production path | 0 件（該当する正規表現 hit は guard 自身の `_UNC_PATH_RE` 定義のみ） |
| 個人の portfolio data | 0 件 |
| production journal / data file | 0 件。`theme_intelligence` 配下に commit された `.jsonl` は 0 件 |
| model / provider の secret | 0 件 |
| network verifier | 0 件（`requests` / `urllib` / `socket` / `httpx` の import 0 件） |
| 出典本文の流出 | 0 件。`claim_summary` は 240 字上限で長文引用を要求しない |

合成の負例 fixture は許容範囲内である。`https://user:pw@example.invalid/...` や `?api_key=zz` は
IANA 予約 domain `.invalid` 上の明らかな非実在値で、`PROHIBITED_CONTENT` guard が**拒否することを
検査するための入力**である。

---

## 17. 凍結面

15 anchor すべてに対して `src/` ・`config.yaml`・`.github/`・`knowledge/` の **変更 file 0**（新規追加のみ）。

Foundation `12847bf` ／ B1 `e2d5168` ／ B2 `ce2402a` ／ B3 `4808f5e` ／ B4B `c776fff` ／ B4C `f26ed4f` ／
B4D `30b2ef0` ／ B4E `f9f7cc1` ／ B4 freeze `10b4483` ／ B5A `93d557d` ／ B5B `78491c8` ／
B5C-R1 `c1cbe44` ／ B5D-RERUN `fb4b94c` ／ P4 `15739707` ／ P5 `edbd0f2`。

---

## 18. 完了評価

| 完了条件 | 判定 |
|---|---|
| B5A〜D が照合されている | PASS（§3。逸脱 1 件を明示） |
| 元の SOURCE_ASSERTED blocker が閉じている | PASS（§6 / §7） |
| 現時点の blocker が無い | PASS |
| B5B が凍結を維持している | PASS（diff 0 行） |
| 人間の統治が必須である | PASS（§8） |
| RULE / LLM が直接 authority になれない | PASS |
| ACCEPT が relation authority を append しない | PASS（§2.1） |
| plan が authority でない | PASS |
| 自動的な因果推論が無い | PASS（§9） |
| 推移的 authority が無い | PASS |
| score / rank / 予測との結合が無い | PASS（§3.2） |
| PIT が決定論的である | PASS（§11） |
| 永続化境界が明示されている | PASS（§12） |
| 依存方向が清潔である | PASS（§13） |
| RR-1 / RR-2 / RR-3 の処理が記録されている | PASS（§14） |
| 繰越 register が完備している | PASS（§15） |
| 機密 / security 監査が通る | PASS（§16） |
| test / guard が通る | PASS（§19） |
| repository が clean で push 済み | PASS |

---

## 19. test / guard

| 対象 | 件数 |
|---|---|
| B5 relation tests（7 file） | **467 passed** |
| theme-intelligence suite | **2049 passed** |
| import / security / bundle guards | 38 passed |
| full pytest suite | **2500 passed** |

failed 0 / skipped 0 / xfail 0 / xpass 0。

---

## 20. 次の gate への推奨

1. **B5 を凍結**する（監督者判断）。凍結 anchor は本 closeout の commit。
2. **実行 gate（`RelationAssertionPlan` → B5B append）を次の独立 gate** として設計されたい。
   §14.1 の RR-3 POLICY LOCK が設計制約として先に立つ。
3. RR-1 の docstring 修正は、実行 gate の着手前に単独の最小 patch として処理するのが望ましい。
4. D3〜D5 は実行 gate の運用像が固まってから再評価するのが妥当と考える（現時点で安全性の要請は無い）。
