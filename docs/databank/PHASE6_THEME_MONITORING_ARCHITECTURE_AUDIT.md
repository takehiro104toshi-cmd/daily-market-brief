# PHASE 6 / P6-B6A — THEME MONITORING ARCHITECTURE / DESIGN AUDIT

READ-ONLY / DOCS-ONLY。runtime・test・knowledge・config・workflow・公開出力・既存 doc はいずれも変更していない。
B6B 実装は開始していない。B5 execution gate も作っていない。

判定: **`P6_B6A_MONITORING_ARCHITECTURE_AUDIT_PASS`**

---

## 1. 現行 architecture の再監査（source / docs / tests から独立に確認）

### 1.1 Foundation

- `ThemeRootRecord` / `ThemeObservation` / `EvidenceAttachment` / governance / metadata / series mapping の
  5 authority（`theme_roots` / `theme_observations` / `theme_governance` / `theme_metadata` /
  `theme_series_mappings`.jsonl）。追記専用・不変履歴。
- `resolve_at_data_root(data_root, root_id, cutoff)` が PIT 解決を行う。
  `ResolutionStatus` = RESOLVED / NO_STATE / UNRESOLVED / INVALID_HISTORY / STORE_CORRUPTION。
  facet ごとに GovernanceStatus / MetadataStatus / MappingStatus / DereferenceStatus を持つ。
- `EvidenceRole` = SUPPORTS / CONTRADICTS / CONTEXT / INVALIDATES。
- `LineageKind` = MERGED_INTO / MERGE_OF / SPLIT_INTO / SPLIT_FROM / SUPERSEDED_BY / SUCCESSOR_OF。
- PENDING 状態（declaration-first の途中）を状態として表現できる。
- authority level: Foundation だけが Theme の canonical 状態を持つ。

### 1.2 B1 Change Detection

- `compare_resolutions(before, after) -> ThemeChangeSet`。**純比較。authority ではない。**
- knowledge 軸（`attached_at` / `recorded_at`）と evidence-time 軸（`evidence_time`）を別 field に分離。
- INVALID_HISTORY / STORE_CORRUPTION は通常の変化にせず `ChangeSetStatus.UNAVAILABLE`。
- score / momentum ではない。`NOT_A_PROMOTION = "qualification is the A2 §19 predicate ... not a lifecycle promotion"`
  を定数として凍結している。

### 1.3 B2 Lifecycle

- `derive_lifecycle(resolution, policy=...) -> ThemeLifecycleView`。**derived view であり authority mutation ではない。**
- `GovernanceLifecycleView`（UNREVIEWED / ACCEPTED / REJECTED / RETIRED / MERGED / SPLIT / SUPERSEDED /
  UNRESOLVED / NOT_AVAILABLE）。REOPENED は受理状態の回復として ACCEPTED と同じに扱う。
- `EvidenceConditionView` の `EvidenceConditionFlag`:
  NO_VISIBLE_EVIDENCE / HAS_CONTEXT_ONLY / HAS_SUPPORT / SINGLE_SOURCE / MULTI_SOURCE /
  SINGLE_EVIDENCE_DATE / MULTI_DATE / QUALIFIES / **CONTESTED** / **INVALIDATION_EVIDENCE_PRESENT** / **STALE**。
- correction event（ROLE_CORRECTION_APPROVED 等）は lifecycle 状態を変えない。terminal correction のときは
  caller が渡した governance event で chain を遡り、渡されなければ**推測せず fail closed**。
- `LifecyclePolicy(stale_after_days)` は versioned な明示入力。**現在時刻を読まない**（cutoff との差で判定）。

### 1.4 B3 Proposal / Dedup

- 提案 authority（`proposals.jsonl`）と人間の決定 authority（`proposal_decisions.jsonl`）。
- `ProposalStatus` = OPEN / OPEN_DEFERRED / OPEN_UNRESOLVED / ACCEPTED / REJECTED /
  CLOSED_NOT_DUPLICATE / INVALID_DECISION_HISTORY。
- dedup は exact（semantic fingerprint / identity core）のみ。fuzzy / score / ranking は無い。

### 1.5 B4 Discovery

- 決定論的 discovery。`DiscoveryRunReport` は **"derived / 再構築可能。authority ではない。score / rank / stance を
  持たない"** と docstring で凍結されている。
- `EvidenceCandidateProposal` / `ThemeCandidateProposal` は提案であって Theme ではない。
- 受理された提案も Foundation mutation ではない。`EvidenceAttachmentPlan` は derived / 非 authority。
- **B4 closeout から B6 へ明示的に繰り越された項目**: #3「adapter 入力単位診断の run report 集約」、
  #15「運用 runner と store への追記」。

### 1.6 B5 Relation Graph

- relation assertion / governance authority、提案 / 人間の決定、`SourceClaimVerification`、
  `RelationAssertionPlan`、記述的 graph view（7 method）。
- 推移的 authority なし。graph 由来の authority なし。関係の自動発見なし。
- B5 closeout の繰越 register（§20 で再掲・分類する）。

#### 1.6.1 B5 RR-3 POLICY LOCK の継承

> 将来の `RelationAssertionPlan` → B5B authority の execution gate は、任意の plan object を
> authority 入力として直接信用してはならない。authoritative な提案 ＋ 有効な人間の決定から
> **再導出**するか、**同等の不変条件を完全に再検証**すること。

**本 POLICY LOCK を B6A は明示的に継承する。ただし execution gate 自体は B6 の scope に含めない。**
Monitoring（観測して surface する層）と execution authority（authority を書く層）は別物であり、
同じ gate に同居させない。

---

## 2. B6 Monitoring の存在理由

B6 は cron runner でも logging layer でもない。中心目的は次のとおりである。

> **時間とともに Theme intelligence の状態変化を観測し、人間が review すべき変化・矛盾・陳腐化・不足を、
> authority を勝手に変更せずに surface する層。**

B6 の成功条件は「自動で賢く判断すること」ではなく、
**「人間が review すべき状態を、再現可能・監査可能・fail-closed に発見すること」**である。

### 2.1 6 つの意味論層（混同しない）

| # | 層 | 所有者 | 性質 |
|---|---|---|---|
| 1 | Observation（新しい evidence / fact / proposal が来た） | 上流 ＋ Foundation / B3 / B5C authority | **B6 の外**。B6 は authority を読むだけ |
| 2 | Derived Change（変化が観測された） | B1 ChangeSet / B2 lifecycle view / B4C run report / B5 resolution | **既存**。B6 は再実装しない |
| 3 | Monitoring Condition（review が必要かもしれない状態の定義） | **B6 の versioned knowledge** | 新規。決定論的 predicate |
| 4 | Monitoring Finding（条件が成立したことの決定論的記録） | **B6 の derived** | 新規。**authority ではない** |
| 5 | Review Candidate（人間に提示する対象 ＋ 人間の review 状態） | **B6 の operational** | 新規。**governance authority ではない** |
| 6 | Governance Action（人間の authority decision） | Foundation / B3 / B5C | **B6 の外** |

### 2.2 明文化する非同一性

```
Monitoring Finding  ≠  Governance Action
Review Candidate    ≠  Theme mutation
Review Candidate    ≠  Relation mutation
Review Candidate    ≠  Evidence attachment
Review Candidate    ≠  Prediction
Review Candidate    ≠  Trading signal
Acknowledgement     ≠  Governance decision
Monitoring ruleset  ≠  Investment rule
```

層 4 / 5 から層 6 へ渡る唯一の経路は、**人間が B3 / B5C の提案 ＋ 決定 authority を通ること**である。
B6 はその経路を短絡しない。

---

## 3. 用語に関する監査上の判断 —「Event」を使わない

この codebase では **`Event` はすでに authority を意味する**（`ThemeGovernanceEvent`、
`ThemeRelationGovernanceEvent` はいずれも append-only の authority record）。
derived / 非 authority の monitoring record に `MonitoringEvent` の名を与えると、
命名だけで「B6 が governance authority を持つ」という誤読を生み、§5 が警戒する
「隠れた governance authority」の第一歩になる。

**したがって層 4 の名称として `MonitoringEvent` を推奨しない。`MonitoringFinding` を推奨する。**
（監督者決定 D-B6-1 の一部。名称は監督者が最終決定する）

---

## 4. Monitoring 対象 inventory（「監視できる」と「MVP で実装する」を分離）

| 群 | 条件 | MVP |
|---|---|---|
| **A. Theme evidence** | CONTRADICTS 追加 / INVALIDATES 追加 / SUPPORTS 追加 / CONTEXT 追加 / evidence の陳腐化 / evidence 不在 | 一部（下記） |
| A-1 | ACCEPTED な Theme に CONTRADICTS が存在する | ✅ MVP |
| A-2 | INVALIDATES が存在する | ✅ MVP |
| A-3 | counted evidence が 0（`NO_VISIBLE_EVIDENCE` / `HAS_CONTEXT_ONLY`） | ✅ MVP |
| A-4 | `STALE`（cutoff − 最新 dated evidence ≥ policy 日数） | ✅ MVP |
| A-5 | SUPPORTS 追加そのもの | ❌ 通常運転。review 条件ではない |
| **B. Theme semantic** | B1 ChangeSet の semantic change / observation revision / successor 含意 | |
| B-1 | ACCEPTED な Theme の semantic field が変わった | ✅ MVP |
| B-2 | entity / taxonomy 参照の変化 | ⏸ B6 第 2 段 |
| **C. Lifecycle** | | |
| C-1 | RETIRED / SUPERSEDED な root に新 evidence が付いた | ✅ MVP |
| C-2 | governance 状態と evidence 状態の乖離（ACCEPTED かつ `NO_VISIBLE_EVIDENCE` 等） | ✅ MVP |
| C-3 | REOPENED 後に review 未了 | ⏸ 第 2 段 |
| **D. Proposal** | | |
| D-1 | OPEN 提案が cutoff 基準で長期滞留 | ✅ MVP |
| D-2 | OPEN_DEFERRED が長期滞留 | ✅ MVP |
| D-3 | 決定 chain が UNRESOLVED / INVALID | ✅ MVP（integrity） |
| D-4 | REJECTED 提案が再発見された | ⏸ 第 2 段 |
| D-5 | 収束 / 重複 diagnostics | ⏸ 第 2 段（B5 D3 と関係） |
| **E. Discovery** | | |
| E-1 | 新しい決定論的 discovery hit があるが受理提案が無い | ✅ MVP |
| E-2 | ruleset / taxonomy / catalog version が前回 run から変わった | ✅ MVP |
| E-3 | 同一 rule の反復 hit | ⏸ 第 2 段 |
| E-4 | PIT replay 差分 | ⏸ 第 2 段（B6E gate で扱う） |
| **F. Relation** | | |
| F-1 | active な relation の端点が RETIRED / SUPERSEDED | ✅ MVP |
| F-2 | 撤回済み relation に新しい提案が来た | ✅ MVP |
| F-3 | SOURCE_ASSERTED relation の出典側に CONTRADICTS evidence | ✅ MVP |
| F-4 | 同一 edge に対する対立する関係型の提案 | ⏸ 第 2 段 |
| F-5 | relation governance chain が UNRESOLVED | ✅ MVP（integrity） |
| **G. Integrity** | | |
| G-1 | authority journal の破損 | ✅ MVP |
| G-2 | chain 未解決（fork / cycle / dangling） | ✅ MVP |
| G-3 | 端点欠落 / PIT 解決失敗 | ✅ MVP |
| G-4 | schema / knowledge version の不整合 | ✅ MVP |
| G-5 | 非 canonical record | ✅ MVP |

---

## 5. Vocabulary 提案

```
MonitoringConditionDefinition   versioned knowledge。決定論的 predicate の定義
MonitoringCategory              名義分類（順序を持たない）
MonitoringSubjectKind           何についての findings か（typed 参照）
MonitoringFinding               条件成立の決定論的 derived record（authority ではない）
MonitoringRunReport             1 回の run の derived 要約（B4C DiscoveryRunReport と同型）
ReviewItemState                 人間の review 状態（operational）
ReviewDisposition               人間が付けた処理（operational）
MonitoringRunStatus             COMPLETE / PARTIAL / FAILED
```

### 5.1 `MonitoringCategory`（名義。順序なし）

```
EVIDENCE_CONDITION      evidence の矛盾 / 不足 / 陳腐化
SEMANTIC_CHANGE         Theme の意味が変わった
LIFECYCLE_DIVERGENCE    governance 状態と evidence 状態の乖離
PROPOSAL_BACKLOG        人間の決定待ちが滞留している
DISCOVERY_CONDITION     discovery 側の状態
RELATION_CONDITION      relation 側の状態
INTEGRITY               技術的な健全性（破損 / 未解決 / version 不整合）
```

`INTEGRITY` を他と**別 category に分ける**ことが要点である。
「技術エラー」と「投資 intelligence 上の review condition」を同じ列に混ぜない（§17）。

### 5.2 `MonitoringSubjectKind`

```
THEME_ROOT / THEME_PROPOSAL / EVIDENCE_CANDIDATE / DISCOVERY_RUN /
RELATION_EDGE / RELATION_PROPOSAL / AUTHORITY_JOURNAL
```

### 5.3 severity について — **MVP から外すことを推奨**

| 案 | 評価 |
|---|---|
| **severity を導入しない（推奨）** | 順序尺度が存在しないので score / ranking へ転用されえない。category による routing で運用は足りる。B6 MVP に量の問題はまだ無い |
| LOW / MEDIUM / HIGH を導入 | 「運用優先度だけ」と宣言しても、順序尺度は必ず「Theme の重要度」と読み替えられる。凍結された non-goal（score / rank）への最短経路になる |

導入する場合でも **算出してはならない**。`MonitoringConditionDefinition` に人間が書いた定数として置き、
`review_priority` のような運用語にし、Theme 強度・確信度・価格予測・順位とは無関係であることを
凍結文言で併記すること。**B6A の推奨は「MVP では持たない」**（D-B6-6）。

---

## 6. Authority 分類

| 対象 | 分類 | 理由 |
|---|---|---|
| `MonitoringConditionDefinition`（ruleset） | **KNOWLEDGE（versioned, 人間が authoring）** | B4B / B4C の knowledge YAML と同型 |
| `MonitoringFinding` | **DERIVED（非永続）** | authority ＋ knowledge version ＋ cutoff から完全に再導出できる |
| `MonitoringRunReport` | **DERIVED（任意で operational に追記可）** | B4C `DiscoveryRunReport` と同じ位置づけ |
| `ReviewItemState`（acknowledgement / disposition） | **OPERATIONAL（append-only journal）** | **再導出できない新しい人間入力**。ここだけが永続化を必要とする |
| 人間の governance decision | **AUTHORITY（B6 の外）** | Foundation / B3 / B5C が持つ |
| downstream governance action | **AUTHORITY（B6 の外）** | 同上 |

### 6.1 §5 の 5 問への回答

**A. `MonitoringFinding` を append-only journal にする必要があるか → 不要。**
finding は (authority bytes, knowledge versions, ruleset version, cutoff) の純関数である。
永続化すると、再導出結果と保存値が食い違ったときにどちらが正かという問いが生まれ、
それは事実上 B6 に authority を与えることになる。B4C が run report を
「derived / 再構築可能。authority ではない」と凍結したのと同じ判断である。

**B. `ReviewCandidate` は finding から derived にすべきか → 半分 derived。**
「何を review すべきか」は finding から derived。「人間がそれをどう扱ったか」は derived ではない。
後者だけを `ReviewItemState` として持つ。

**C. acknowledgement は authority か operational state か → OPERATIONAL。**
acknowledgement が記録するのは**「人間がこの finding を見た」**であって、
**「人間が Theme について何かを決めた」ではない**。後者を記録したくなった時点で、
それは B3 / B5C の提案 ＋ 決定 authority を通さなければならない。
この境界を破ると B6 が隠れた governance authority になる。

**D. 同じ condition の repeated alert → identity で解く（§7）。**
finding identity に run 時刻を含めないため、状態が同じなら何度 run しても同じ finding key になる。
acknowledgement はその key に紐づくので、繰り返し提示されない。閾値や抑制ヒューリスティクスは不要。

**E. resolved / reopened の意味を誰が持つか → 系（resolved）と人間（acknowledged）で分ける。**
- **resolved**: 条件がもう成立しない ＝ 次の run で finding が生成されない。**系が持つ derived 事実**。
- **acknowledged / dismissed**: 人間が付ける operational 状態。
- **reopened**: 状態が変わって**別の finding key** が生まれたとき。§7.2 参照。

---

## 7. Identity / dedup

fuzzy dedup / similarity score は禁止。B3 / B5C の
**content-addressed identity ＋ provenance separation** をそのまま継承する。

### 7.1 identity の階層

| 概念 | identity | 含めるもの | 含めないもの |
|---|---|---|---|
| condition | `condition_id`（ruleset の安定名）＋ `ruleset_version` | 定義 | — |
| **finding** | **content id over (condition_id, subject_kind, subject_ref, salient_state)** | 条件・対象・**成立の根拠となった状態の要約** | **run 時刻 / cutoff / 実行者** |
| occurrence | `(finding_key, run_id)` | どの run が見たか | identity を持たない（derived） |
| run | `run_id` = content id over (cutoff, knowledge versions, ruleset version, input digest) | 再現可能な run の座標 | wall clock |
| review item | **`finding_key` そのもの** | — | — |

`salient_state` は「なぜ成立したか」を決める最小の事実（例: 矛盾 evidence の `attachment_key` 集合、
`STALE` を生んだ最新 evidence date と閾値）である。本文や長い引用は入れない（§21）。

### 7.2 「同じ condition が毎日成立する」の扱い

```
状態が同じ      → 同じ finding_key → 同じ open review item（再提示しない）
状態が変わった  → 別の finding_key → 新しい review item（= 実質的な reopen）
条件が消えた    → finding が生成されない（= resolved。人間の操作は不要）
```

`created_at` / run 時刻を semantic identity に混ぜない。これは B5C の
「等価な提案は発見機構と時刻を跨いで同一 id に収束する」と同じ規律である。

### 7.3 B3 / B5C から継承する点

- identity は内容から決まり、provenance（誰が・いつ）は identity の外・canonical bytes の中。
- 収束は設計であって偶然ではない（同じ状態は同じ key に落ちる）。
- **ただし B6 は authority ではないため、B5C の「同 id ＋ 異 bytes → CONFLICT」問題は発生しない。**
  finding を永続化しないからである（§6.1-A）。これは Option C を選ぶ副次的な利点である。

---

## 8. 時間 / PIT

### 8.1 時間軸の棚卸し

| 軸 | 所在 | 意味 |
|---|---|---|
| `evidence_time` | Foundation attachment | evidence が指す時点 |
| `attached_at` | Foundation attachment | 系がいつ結び付けたか |
| `recorded_at` | 各 authority record | 系がいつ知ったか（知識時間） |
| `proposal.created_at` | B3 / B5C | 提案が作られた時点 |
| `decision.recorded_at` | B3 / B5C | 人間が決めた時点 |
| `verified_at` | B5C `SourceClaimVerification` | 人間が出典主張を確認した時点 |
| **knowledge cutoff** | 呼び出し側 | Foundation / B3 / B5 の PIT 解決に使う |
| **monitoring cutoff** | 呼び出し側 | B6 の評価時点。**knowledge cutoff と同一にすることを推奨**（別にすると leakage 面が 2 倍になる） |
| `run.recorded_at` | run report | run の provenance。**identity には入らない** |
| occurrence 時刻 | run report | 同上 |
| acknowledgement 時刻 | `ReviewItemState` | 人間が確認した時点。呼び出し側が渡す |

### 8.2 必須原則

- wall-clock の暗黙 latest **禁止**。`datetime.now()` / `utcnow` を読まない。
- 呼び出し側が渡す aware datetime のみ。
- cutoff は明示。
- **同一入力 ＋ 同一 version ＋ 同一 cutoff = 同一 derived 結果**（決定論的 replay）。
- 未来情報の漏れ禁止（cutoff より後の record は不可視）。

### 8.3 「stale」「long-lived」「recent」の定義

暗黙の現在時刻を読まず、**明示 cutoff との差分**として定義する。

```
STALE(subject, cutoff)       := cutoff − latest_dated_evidence(subject, cutoff) ≥ ruleset.stale_after_days
LONG_LIVED(proposal, cutoff) := cutoff − proposal.created_at            ≥ ruleset.backlog_after_days
RECENT(x, cutoff)            := cutoff − x                             <  ruleset.recent_within_days
```

閾値はすべて versioned ruleset の定数であり、コードに埋め込まない。
B2 の `LifecyclePolicy(stale_after_days)` がすでにこの形であり、B6 はそれを踏襲する。

---

## 9. Monitoring ruleset

### 9.1 形式（実装しない。設計のみ）

```
knowledge/theme_intelligence/monitoring_rules.<version>.yaml
```

rule が持ちうるもの:

```
rule_id / rule_version / status
category                    MonitoringCategory
subject_kind                MonitoringSubjectKind
predicate                   宣言的な決定論的述語（構造化。任意 Python ではない）
required_inputs             どの derived view / authority を必要とするか
thresholds                  日数などの定数
output_condition_id         成立時に生む condition
review_message_template     人間向けの短い定型文（本文を貼らない）
provenance                  誰がいつ authoring したか
```

### 9.2 禁止

任意 Python 式 ／ 記事本文への任意 regex ／ fuzzy 類似 ／ LLM 判断 ／ 確率 ／ 順位付け ／
投資スタンス ／ 価格目標。

### 9.3 B4C discovery ruleset との比較

| 観点 | B4C discovery ruleset | B6 monitoring ruleset |
|---|---|---|
| 入力 | 上流の生 record（NewsItem / Fact / Observation / SourceDocument） | **既存の derived view と authority 解決結果**（B1 / B2 / B3 / B4 / B5） |
| 出力 | 提案（B3 authority の候補） | **finding（authority ではない）** |
| 述語の対象 | text 面の正規化完全一致 ＋ 構造値 | 状態・関係・時間差 |
| версион pin | taxonomy / catalog / ruleset の複合 pin | **同じ pin ＋ 上流 phase の model version** |
| 共通 | 決定論的・versioned・純関数・現在時刻を読まない | 同左 |

**最大の違い**: discovery は「新しい主張候補を作る」、monitoring は「既存の状態を指差す」。
monitoring は新しい主張を一切作らない。

---

## 10. Alert の意味論

B6 が出すものは次の**いずれでもない**。

投資推奨 ／ 売買 signal ／ 予測 ／ Theme 強度 score ／ 確信度 score ／ governance decision。

**「人間の review が必要かもしれない状態を surface する」だけ**である。

### 10.1 通知境界

**B6 MVP は internal monitoring intelligence に留めることを推奨する。**
iPhone 通知 / Pages / public / customer notification は **B6 の scope 外**。

理由: 通知経路を MVP に入れると、(a) 誤検出の影響範囲が人間 1 人の review queue から外部へ広がる、
(b) 通知の有無が暗黙の severity になる、(c) 公開出力との結合が生まれ、
凍結済みの「B5 / B6 は公開出力に結合しない」を壊す。

---

## 11. Contradiction / Invalidation の monitoring

Foundation は SUPPORTS / CONTRADICTS / CONTEXT / INVALIDATES を持ち、
B2 はすでに `CONTESTED` / `INVALIDATION_EVIDENCE_PRESENT` flag を derived view として出している。
**B6 はこれを再計算せず参照する。**

### 11.1 B6 が絶対にしないこと

- Theme を自動 retire しない
- lifecycle を自動変更しない
- relation を自動 retract しない
- governance decision を自動生成しない
- 矛盾の「勝敗」を判定しない

### 11.2 代わりに出すもの（condition 案）

```
CONTRADICTION_EVIDENCE_PRESENT      CONTRADICTS が存在する
INVALIDATION_EVIDENCE_PRESENT       INVALIDATES が存在する
ACCEPTED_THEME_CONTESTED            ACCEPTED かつ CONTESTED（governance と evidence の乖離）
ACCEPTED_THEME_WITHOUT_SUPPORT      ACCEPTED かつ counted evidence が 0
RETIRED_ROOT_RECEIVED_EVIDENCE      RETIRED / SUPERSEDED な root に新しい evidence
```

いずれも `MonitoringCategory.EVIDENCE_CONDITION` または `LIFECYCLE_DIVERGENCE`。
**どれも「この Theme は誤りである」とは言わない。「人間が見るべき状態である」と言うだけである。**

---

## 12. Relation monitoring

B5 を読むが **B5 authority を変更しない**。

| condition 案 | 分類 |
|---|---|
| `RELATION_ENDPOINT_RETIRED` | RELATION_CONDITION |
| `RELATION_ENDPOINT_SUPERSEDED` | RELATION_CONDITION |
| `RELATION_PROPOSAL_CONFLICTS_WITH_ACTIVE_EDGE` | RELATION_CONDITION |
| `RETRACTED_RELATION_HAS_NEW_PROPOSAL` | RELATION_CONDITION |
| `SOURCE_ASSERTED_RELATION_HAS_CONTRADICTING_EVIDENCE` | RELATION_CONDITION |
| `OPPOSING_RELATION_TYPE_PROPOSED` | RELATION_CONDITION（第 2 段） |
| `RELATION_GOVERNANCE_CHAIN_UNRESOLVED` | INTEGRITY |

### 12.1 禁止

- graph traversal から新しい relation を推論しない。
- centrality / pagerank / relation strength score を導入しない。
- 「検出」と「訂正」を分離する。B6 は検出だけを行い、訂正は人間が B5C の提案 ＋ 決定を通して行う。
- **B5 RR-3 POLICY LOCK を継承**: 将来 plan → B5B の execution gate ができても、
  B6 はその gate を起動しない。monitoring から execution への自動経路を作らない。

---

## 13. Proposal / Discovery monitoring

| condition 案 | 分類 |
|---|---|
| `PROPOSAL_OPEN_BEYOND_THRESHOLD` | PROPOSAL_BACKLOG |
| `PROPOSAL_DEFERRED_BEYOND_THRESHOLD` | PROPOSAL_BACKLOG |
| `PROPOSAL_DECISION_CHAIN_UNRESOLVED` | INTEGRITY |
| `DISCOVERY_HIT_WITHOUT_ACCEPTED_PROPOSAL` | DISCOVERY_CONDITION |
| `KNOWLEDGE_VERSION_DRIFT` | DISCOVERY_CONDITION |
| `EVIDENCE_CANDIDATE_NOT_ATTACHED` | DISCOVERY_CONDITION |
| `ACCEPTED_CANDIDATE_NOT_EXECUTED` | DISCOVERY_CONDITION |
| `REJECTED_PROPOSAL_REDISCOVERED` | DISCOVERY_CONDITION（第 2 段） |

### 13.1 禁止

- **受理された提案を自動 execution しない。**
- `EvidenceAttachmentPlan` の存在は Foundation attachment ではない。
  `ACCEPTED_CANDIDATE_NOT_EXECUTED` は「実行されていない」という**観測**であって、実行の指示ではない。

---

## 14. Diagnostics aggregation（B4D から繰越）

B4 closeout 繰越 #3「adapter 入力単位診断の run report 集約」を回収する。

| 種類 | 例 | 行き先 |
|---|---|---|
| **技術的 integrity** | journal 破損 / PIT 解決失敗 / 非 canonical record / schema 不整合 / 端点欠落 | **finding（`INTEGRITY` category）** |
| **未解決の統治** | 決定 chain の fork / cycle / dangling、governance UNRESOLVED | **finding（`INTEGRITY` category）** |
| **run 単位の技術情報** | 入力件数 / 除外件数 / rule 評価件数 / alias 曖昧性 / 抑制された提案 id | **run diagnostics（`MonitoringRunReport` に留める）** |
| **intelligence 上の review condition** | 矛盾 / 陳腐化 / 滞留 / 乖離 | **finding（他の category）** |

**要点**: 「技術エラー」と「投資 intelligence 上の review condition」を混同しない。
両方 finding にはなりうるが、**category が違い、routing が違い、対応する人間の作業が違う**。

### 14.1 fail-closed の monitoring 版（重要）

**authority が読めないことを、条件が成立しないことと同一視してはならない。**

authority が破損している・PIT 解決に失敗した場合、その subject について
「finding が無い」と報告してはならない。`MonitoringRunStatus.PARTIAL` とし、
当該 subject を `INTEGRITY` finding として出し、評価できなかった条件を明示すること。
静かな無検出は monitoring における最悪の失敗様式である。

---

## 15. Operational runner

### 15.1 責務（この範囲まで）

```
authority を読む
  → PIT 解決する（明示 cutoff）
  → 決定論的 monitoring rule を走らせる
  → derived な finding / run report を作る
  → （許可された範囲で）monitoring record を追記する
```

許可される追記は **`ReviewItemState` の operational journal** と、
任意で `MonitoringRunReport` の operational 追記のみ。

### 15.2 default 禁止

Foundation mutation ／ B5 relation mutation ／ governance mutation ／ 提案 ACCEPT ／
evidence attachment の実行 ／ relation assertion の実行 ／ LLM 呼び出し ／ network 呼び出し ／ 公開。

---

## 16. 実データ / shadow 境界

段階を分ける。

```
1. synthetic validation      完全合成 fixture（tmp data root）
2. controlled fixture        代表 world 上での E2E
3. read-only real-data shadow run   実 authority を読むが **一切書かない・一切通知しない**
4. operational internal monitoring  review state の追記を許可。内部のみ
```

**real-data monitoring を行う場合でも、最初は shadow / no-write / no-notification を必須とする。**
合成 test から実世界の precision / recall を主張しない（B5D-RERUN と同じ規律）。

---

## 17. B5 繰越 register の分類

| 項目 | B6 との関係 |
|---|---|
| D3 収束診断語彙（`CONVERGENT_PROPOSAL`） | **B6_RELEVANT_BUT_DEFER**（収束の可視化は monitoring 条件になりうるが MVP 外） |
| D4 `append_or_reuse` store API | **OUTSIDE_B6**（B5C store の API。monitoring とは無関係） |
| D5 co-discovery journal | **B6_RELEVANT_BUT_DEFER**（第 2 段の `REPEATED_DISCOVERY` と関係） |
| RR-1 古い module docstring | **OUTSIDE_B6**（B5C の doc 修正。B6A では触らない） |
| RR-2 例外型の不統一 | **OUTSIDE_B6** |
| RR-3 execution gate POLICY LOCK | **POLICY_LOCKED**。B6A は継承するが gate 自体は scope 外 |
| `RelationAssertionPlan` → B5B execution gate | **OUTSIDE_B6**（独立 gate。monitoring と混同しない） |
| 実世界の relation 精度測定 | **B6_RELEVANT_BUT_DEFER**（§16 の段階 3 以降） |
| 自動 relation 発見 | **OUTSIDE_B6**（B6 non-goal） |
| 意味論 / LLM verifier | **OUTSIDE_B6**（B7） |
| `assertion_locus` 表記規約 | **OPTIONAL** |
| B4-17 ticker 書式例 | **HISTORICAL_ONLY** |
| B5-D2 語彙拡張 | **OUTSIDE_B6** |
| B5-D6 world-time | **B6_RELEVANT_BUT_DEFER**（monitoring は知識時間のみで開始する） |
| B5-D7 migration gate | **OUTSIDE_B6**（ただし F-1 / F-2 が migration の必要性を surface する） |
| B4-3 adapter 診断の集約 | **B6_REQUIRED**（§14 で回収） |
| B4-15 運用 runner と store 追記 | **B6_REQUIRED**（§15 で回収） |

---

## 18. 監督者決定候補

| # | 論点 | 推奨 | 代替 |
|---|---|---|---|
| **D-B6-1** | B6 の authority model | **B6 は authority を持たない。knowledge（ruleset）＋ derived（finding / run report）＋ operational（review state）の 3 層。層 4 の名称は `MonitoringEvent` ではなく `MonitoringFinding`** | `MonitoringEvent` を authority journal にする（隠れた governance authority を生むため非推奨） |
| **D-B6-2** | persistence model | **Option C**: finding は決定論的 derived で永続化しない。`ReviewItemState`（acknowledgement / disposition）だけを operational journal に追記する。`MonitoringRunReport` は derived で、任意に operational 追記 | Option A（run report のみ）／ Option B（event journal ＋ derived report） |
| **D-B6-3** | identity | **finding_key = content id over (condition_id, subject_kind, subject_ref, salient_state)。run 時刻を含めない。review item key = finding_key。状態が変われば別 key（= reopen）** | occurrence ごとに id を振る（alert storm を生む） |
| **D-B6-4** | 時間 / cutoff / PIT | **monitoring cutoff は明示かつ knowledge cutoff と同一。現在時刻を読まない。stale / long-lived は cutoff との差分で定義し、閾値は ruleset 定数** | monitoring 専用 cutoff を別に持つ（leakage 面が増える） |
| **D-B6-5** | versioned ruleset | **持つ。`knowledge/theme_intelligence/monitoring_rules.<version>.yaml`。宣言的述語のみ。任意 Python / regex / LLM を禁止** | rule を Python に埋め込む（version pin と replay が壊れる） |
| **D-B6-6** | severity / priority | **MVP では導入しない。`MonitoringCategory`（名義・順序なし）で routing する** | LOW / MEDIUM / HIGH を導入（score への転用リスク） |
| **D-B6-7** | contradiction / invalidation | **B2 の derived flag を参照して condition を出すだけ。自動 retire / lifecycle 変更 / relation 撤回 / governance 生成を一切しない** | 矛盾の勝敗判定（禁止） |
| **D-B6-8** | relation monitoring の境界 | **B5 authority を読むのみ。graph traversal による推論・centrality・strength score を持たない。検出と訂正を分離** | graph 由来の推論（禁止） |
| **D-B6-9** | diagnostics aggregation | **技術 integrity と intelligence review condition を別 category に分ける。run 単位の技術情報は run report に留める。authority が読めない場合は PARTIAL ＋ INTEGRITY finding とし、静かな無検出を作らない** | 全部 run diagnostics に留める（B4-3 の回収にならない） |
| **D-B6-10** | runner の責務 | **read → PIT 解決 → 決定論的 rule → derived 出力 → 許可された review state 追記、まで。Foundation / B5 / governance / 提案 ACCEPT / attachment 実行 / LLM / network / 公開を default 禁止** | runner に execution を持たせる（禁止） |
| **D-B6-11** | real-data shadow gate | **段階 1〜4 を分け、実データは必ず shadow / no-write / no-notification から開始する** | 直接運用投入 |
| **D-B6-12** | 実装 sequence | **B6B model → B6C engine → B6D review store ＋ runner → B6E 敵対的 gate → B6 closeout**（§21） | monolithic 実装 |
| **D-B6-13** | 通知境界 | **B6 MVP は internal のみ。iPhone / Pages / public / customer notification は scope 外** | MVP に通知を含める |
| **D-B6-14** | 用語 | **層 4 を `MonitoringFinding` と呼ぶ**（`Event` は既存 authority 語彙と衝突する） | `MonitoringEvent`（誤読リスク） |

---

## 19. B6 MVP と non-goals

### 19.1 MVP に含める

- versioned monitoring ruleset（宣言的・決定論的）
- `MonitoringFinding` の決定論的導出（§4 の ✅ 行のみ）
- `MonitoringRunReport`（derived。B4-3 の診断集約を含む）
- `ReviewItemState` の operational journal（acknowledgement / disposition）
- 明示 cutoff ／ 決定論的 replay ／ fail-closed
- 合成 fixture による validation

### 19.2 明示的 non-goals

自動 governance ／ 自動 Theme mutation ／ 自動 relation mutation ／ 自動 evidence attachment ／
予測 ／ 売買 signal ／ scoring・ranking ／ graph centrality ／ LLM semantic verifier ／
公開・顧客通知 ／ Phase 7 Narrative ／ P5 calibration feedback ／ DNA self-learning ／
relation execution gate ／ 自動 relation 発見。

---

## 20. Validation / test plan（B6B 以降。今回は実装しない）

| 群 | 内容 |
|---|---|
| 決定論 | 同一入力 ＋ 同一 version ＋ 同一 cutoff で finding 集合と run report bytes が一致 |
| 順序 | 物理 record 順をシャッフルしても結果が不変（≥ 11 seed） |
| PIT | cutoff 厳密一致で可視 / +1µs で不可視 / 未来 record の漏れなし |
| 重複 occurrence | 同一状態を 2 回 run しても同一 finding_key、review item は 1 件 |
| 反復条件 | 連続 run で再提示されない（acknowledged が効く） |
| resolve → 再発 | 条件消滅で finding 消失、状態変化で**別 key** として再出現 |
| 矛盾 | CONTRADICTS 追加で condition が立つが Theme は不変 |
| 無効化 | INVALIDATES 追加で condition が立つが自動 retire しない |
| 端点 | RETIRED / SUPERSEDED 端点で relation condition が立つ |
| 未解決 chain | fork / cycle / dangling が INTEGRITY finding になる |
| 破損 journal | PARTIAL ＋ INTEGRITY finding。**静かな無検出にならない** |
| version drift | knowledge version 変化が condition になる |
| 陳腐化 | cutoff との差分で判定。現在時刻を読まない |
| 滞留提案 | OPEN / OPEN_DEFERRED の経過を cutoff 基準で判定 |
| 非改変 | Foundation 5 file / B5B 2 file / B3 2 file / B5C 2 file が byte 一致 |
| 自動 governance 不在 | ACCEPT / attachment / assertion / governance が 1 件も発生しない |
| score 不在 | score / rank / probability / prediction の token が 0 |
| network / LLM 不在 | import と実行経路の両方で 0 |
| 合成偽陽性 corpus | 正常運転の状態が condition を立てないこと（**synthetic gate result only**） |
| 実データ shadow gate | 段階 3。no-write / no-notification |

---

## 21. 推奨実装 sequence

| gate | 内容 | 成果物 |
|---|---|---|
| **B6B** | monitoring model（condition definition / finding / run report / review state の不変 record と語彙） | model module ＋ contract doc |
| **B6C** | 決定論的 monitoring engine（純関数。§4 の MVP 条件） | engine module ＋ ruleset YAML |
| **B6D** | review state の operational store ＋ runner（read-only 側の統合） | store ＋ runner module |
| **B6E** | 敵対的 E2E gate（§20 の test matrix） | test ＋ gate doc |
| **B6 closeout** | 完了監査 | closeout doc |
| （別系統） | B5 relation execution gate | **B6 とは別 gate**。RR-3 POLICY LOCK が先に立つ |

---

## 22. 制約と既知の限界

- monitoring は**検出のみ**。条件が立っても、それが本当に review に値するかは人間が判断する。
- 合成 corpus からは実世界の precision / recall を測れない（§16 段階 3 以降が必要）。
- 世界時間（`effective_from` / `effective_to`）は B5-D6 のとおり不在。B6 も知識時間のみで開始する。
- `salient_state` の粒度設計が identity の安定性を左右する。粗すぎれば状態変化を見逃し、
  細かすぎれば毎 run 別 key になる。**B6B で条件ごとに明示的に決めること。**
- ruleset の宣言的述語の表現力は B4C の predicate 設計を参考にするが、
  対象が derived view であるため同一ではない。B6C で設計する。
