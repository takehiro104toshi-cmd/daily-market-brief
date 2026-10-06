# Phase 6 — Theme Intelligence Architecture Audit（P6-B0）

状態: **P6_B0_THEME_INTELLIGENCE_ARCHITECTURE_AUDIT_COMPLETE / READY_FOR_SUPERVISOR_P6_B_ARCHITECTURE_DECISIONS**。
本書は設計監査であり、runtime を実装しない。Theme Foundation（P6-A1〜A4d.1）は
`P6_THEME_FOUNDATION_COMPLETE / CLOSED / FROZEN`（anchor `12847bf2783330cbd310d24c8310d3bf46469f6a`、branch
`claude/investment-intelligence-phase6`）。凍結 7 file（model / fingerprint / qualification / revision / store / operations /
resolver）・schema・id・語彙・authority file・PIT 意味論・永続化意味論は変更しない。変更が必要な箇所は §21 に
FOUNDATION_CHANGE 候補として列挙するだけで、本 gate では実装も要求もしない。

入力（読み取り専用）: `PHASE6_FOUNDATION_DECISIONS.md`（A0.5）、`PHASE6_THEME_SEMANTICS_AUTHORITY_CONTRACT.md`（A1）、
`PHASE6_THEME_IDENTITY_EVIDENCE_CONTRACT.md`（A2）、`PHASE6_THEME_PERSISTENCE_REVISION_CONTRACT.md`（A3）、
`PHASE6_THEME_FOUNDATION_INVARIANT_MATRIX.md`、`src/intelligence/themes/`、および historical branch
（`claude/investment-intelligence-phase0-rvdplu`）の参考資産 11 件（§16。`git show` による read only。port / merge /
cherry-pick なし。機密 Compass / corpus 内容は転記しない）。

用語: **Foundation** ＝ 凍結 themes package と 5 canonical authority。**Intelligence layer** ＝ その上に置く P6-B の
派生・提案・監視層。**canonical** ＝ Foundation の 5 JSONL。**proposal** ＝ Intelligence layer の append-only 提案
record（authority ではない）。**derived** ＝ canonical から決定論的に再計算でき、保存しても捨ててよいもの。

---

## 1. Executive summary

- Foundation は A0.5 §9 の MVP 7 段のうち ①〜⑤（identity / evidence 付与 / 支持・反証 / 不変履歴 / 点時刻再構成）を
  実装・凍結した。**⑥ 決定論的 change 観測（2 時点の再構成差分）は未実装**であり、これが P6-B の最初の仕事である。
- 推奨実装順序は **F（別の順序）: ① Change Detection（純 diff）→ ② Lifecycle（派生状態 ＋ 既存 governance 語彙）→
  ③ Proposal journal ＋ Dedup 提案 → ④ Taxonomy 語彙（REDESIGN）＋ Entity catalog（PORT）＋ rule-based Discovery 提案 →
  ⑤ Typed directed Graph → ⑥ Monitoring runner ＋ derived index → ⑦ LLM-assisted 提案（任意・最後）**。
  Change Detection が最初である理由: Foundation への追加依存 0、人間 governance 依存 0、LLM 依存 0、誤分類 risk 0、
  新 authority を作らず、lifecycle / monitoring / Phase 7 の全てがこれを入力にする。
- Lifecycle は **2 層**に分ける。**governance 層**（authoritative。既存 11 event 種別だけで表現できる: 候補 / 受理 /
  却下 / 引退 / 再開 / merge / split / successor）と **evidence 層**（derived。資格判定・支持 / 反証 / 無効化 / 多様性 /
  持続 / 新規 evidence の有無から決定論的に計算。authority ではなく保存しない）。「価格が上がった」「予測が当たった」
  「P5 較正」は lifecycle の入力にしない。
- Graph は Foundation の lineage 関係（MERGE_OF / SPLIT_FROM / SUCCESSOR_OF ＝ identity 系譜）とは **別 graph** とし、
  typed・directed・certainty class 付き・provenance 付き・append-only・PIT 解決可能な relation record で表す。
  co-occurrence からは RELATED_TO（OBSERVED_ASSOCIATION 相当）の**提案**しか作らず、CAUSES は人間宣言または
  EXPLICIT_SOURCE_CAUSAL_CLAIM の attribution のみ。historical の無向隣接はそのまま採用しない（seed 参照のみ）。
- Discovery は **proposal-only**（canonical RootRecord を自動作成しない）を既定とする。rule-based 提案から L1 候補 root
  への実体化は人間の「提案受理」decision で行う。LLM は proposal-only。
- Dedup は merge authority ではなく **review proposal**。exact fingerprint 一致と identity-core 部分一致（同 driver / 同
  channel / 同 domain / 同 subject）だけを決定論的に提示し、fuzzy / embedding は用いない。
- Taxonomy は **REDESIGN**（slug・階層・変更管理規則を discovery 語彙 ＋ METADATA TAXONOMY 値として再設計。keyword 規則は
  canonical に入れない）。Theme identity ≠ taxonomy slug、taxonomy 変更で ThemeObservation id は変わらない（既に構造的に
  保証）。
- Foundation 変更は **推奨経路 ①〜⑥ では不要**。ただし ④ discovery を実運用すると mechanism 語彙（`MECHANISM_CATEGORIES`）
  の拡張が必要になる可能性が高く、現行 model は語彙 version を厳密一致で検査するため、**語彙 version の複数受理**が
  将来の FOUNDATION_CHANGE 候補になる（§21）。本 gate の判定は A（audit complete）であり FOUNDATION_CHANGE_REQUIRED では
  ない。
- 設計 blocker は無い。監督者決定が必要な事項は §25 に列挙した。

---

## 2. Current Foundation capability（凍結済み）

| 能力 | 所在 | P6-B から使える API（read only） |
|---|---|---|
| Theme root（不透明 id、creation_method、origin event） | `model.ThemeRootRecord` | `ThemeStore.get_root`、`ThemeHistory.from_store(store).roots` |
| 不変 semantic observation（主題・機構 4 component・確度 class・scope・limitations・無効化条件・inferred link・attachment・provenance） | `model.ThemeObservation` | `observations_for_root`、`ThemeHistory.observations` |
| evidence attachment（kind / authority class / ref_id / origin / evidence_time ＋ basis ＋ quality / attached_at / role / role provenance / consequence_ref / QA snapshot） | `model.EvidenceAttachment` | observation 経由 |
| identity core / semantic fingerprint（DERIVED） | `fingerprint.py` | `identity_core_fingerprint`、`semantic_fingerprint`、`identity_core_unchanged` |
| 資格判定（Q5 の source / temporal diversity、除外診断、DIRECTLY_EVIDENCED link） | `qualification.py` | `evaluate_qualification`、`source_origin_groups`、`independent_origin_count`、`evidence_date_set`、`directly_evidenced_links` |
| same-root revision / evidence 追加の純 helper | `revision.py` | `revise_observation`、`attach_evidence` |
| 5 authority の append-only store（validate-before-append、fail closed、byte 長検査、PENDING、fork 診断） | `store.py` | `ThemeStore.open(read_only=True)`、`audit`、`counts`、`canonical_lines`、`pending`、`diagnostics` |
| 宣言先行の論理操作（candidate / merge / split / successor、crash 冪等） | `operations.py` | `plan_*` / `execute_*`（**書き手**。P6-B では人間 decision の実行にのみ使う） |
| 点時刻 resolver（facet 別 status、evidence view の 4 分割、governance chain と reversal 畳み込み、lineage 注釈、metadata / mapping facet、PENDING、carried evidence、DERIVED 再計算、上流 dereference の分離） | `resolver.py` | `resolve(history, root_id, T)`、`resolve_from_store`、`resolve_at_data_root` |
| 人間 governance の 11 event 種別（HUMAN actor のみ、reason 必須、EVENT_REVERSED） | `model.GovernanceEventType` | governance facet |
| metadata 4 field（LABEL / DESCRIPTION / TAXONOMY / ALIAS。identity 外） | `model.ThemeMetadataRecord` | metadata facet |
| 市場確認 series の mapping 記録（CONFIRMATION_CANDIDATE / DRIVER_PROXY / DOMAIN_PROXY、期待方向。**評価はしない**） | `model.ThemeSeriesMapping` | mapping facet |

Foundation が**持たないもの**（設計上の意図）: 2 時点差分、lifecycle 状態名、Theme 間 relation、discovery、dedup
heuristics、taxonomy 語彙の実体、entity catalog、derived SQLite index、LLM、監視 runner、Compass / Brief / P5 との接続、
現在時刻、network。

`ThemeResolution` は frozen dataclass で等価比較可能（A4d で完全一致を証明済み）。したがって **2 つの
`ThemeResolution` の構造差分は Foundation を変えずに純関数として定義できる**。

---

## 3. Missing Theme Intelligence capabilities

| # | 欠落能力 | 必要理由 | 依存 |
|---|---|---|---|
| M1 | 2 時点差分（change set） | MVP ⑥。lifecycle / monitoring / Phase 7 の入力 | Foundation のみ |
| M2 | lifecycle view（governance 層 ＋ evidence 層） | 「この Theme は今どういう状態か」を状態名で言えない | M1、資格判定、governance facet |
| M3 | proposal journal（rule / LLM / human 下書きの提案と人間 decision の append-only 記録） | A1 §16 の「system は提案する、人間が決める」を record にする場所が無い | F-8 規律の新 store |
| M4 | dedup 提案（DUPLICATE_CANDIDATE の実体化と variant 分類） | A2 §12.3 は「人間 review」と言うが review 対象を作る機構が無い | fingerprint、M3 |
| M5 | taxonomy 語彙（versioned）と METADATA TAXONOMY 値の運用 | discovery の語彙、分類 metadata | M3 |
| M6 | entity catalog（versioned knowledge）と typed reference の正規化 | subject / component の typed_reference を安定 id にする | knowledge のみ |
| M7 | rule-based discovery 提案 | 候補 Theme を人手以外で起こす | M3、M5、M6、evidence source（SourceDocument / NewsItem / Fact） |
| M8 | Theme 間 typed relation（graph）と PIT 解決 | Phase 7 の順序付け・説明、dedup の親子 / variant 記録 | M3、M4 |
| M9 | monitoring runner（全 root の change report、staleness、要 review 一覧） | 運用 | M1、M2、（M8） |
| M10 | derived SQLite index（A3 §20） | 規模が出たときの加速。意味論を持たない | Foundation のみ |
| M11 | LLM-assisted 提案（機構構造化・label・relation・反証候補） | 任意。proposal-only | M3、M7 |
| M12 | Phase 7 handoff interface（構造化 view の読み出し契約） | Narrative の入力 | M1、M2、M8 |

---

## 4. D10 Graph options

### 4.1 前提

Foundation の lineage（MERGE_OF / MERGED_INTO / SPLIT_FROM / SPLIT_INTO / SUCCESSOR_OF / SUPERSEDED_BY）は **identity
系譜**であり、governance event から resolver が注釈として再構成する。Theme 間の**意味論的関係**（A が B を増幅する等）は
これとは別概念であり、Foundation authority に入れない。

### 4.2 選択肢

| 案 | 内容 | 長所 | 短所 | 判定 |
|---|---|---|---|---|
| G-A 無向隣接（historical `theme_graph.yaml` 型） | label → [label] | 簡単 | 方向・型・証拠・時刻・provenance なし。co-occurrence を因果に見せる | **REJECT**（seed 参照のみ） |
| G-B Foundation lineage に relation を混ぜる | governance event 種別を増やす | authority が 1 つ | 語彙 version 変更 ＝ Foundation 変更。identity 系譜と意味論関係が混線 | REJECT |
| G-C **typed directed relation record（別 journal）** | `ThemeRelation`（from / to / type / certainty class / evidence refs / provenance / recorded_at / valid_from / supersedes）を append-only journal に記録し、PIT で解決 | Foundation 不変。lineage と分離。反証・撤回が履歴に残る。Phase 7 が順序付けに使える | store をもう 1 つ持つ | **採用候補** |
| G-D derived 構造 relation のみ | identity core payload の共有（SHARES_DRIVER / SHARES_CHANNEL / SHARES_DOMAIN / SAME_SUBJECT）を再計算で提示 | authority 不要・決定論・即時 | 意味論関係（AMPLIFIES 等）は表現できない | **G-C の前段として採用**（dedup 提案と共用） |

### 4.3 relation 語彙（候補。監督者決定事項）

| type | 方向 | 成立に必要な provenance | co-occurrence から作ってよいか |
|---|---|---|---|
| CAUSES | from → to | HUMAN 宣言 ＋ evidence ref、または EXPLICIT_SOURCE_CAUSAL_CLAIM の attribution（誰が言ったかの記録） | **否** |
| AMPLIFIES / COUNTERACTS | from → to | HUMAN / RULE（機構 component の符号が明示できる場合）/ LLM_PROPOSAL（提案） | 否 |
| DEPENDS_ON / CONSTRAINS | from → to | 同上 | 否 |
| SUBSTITUTES | 対称（両方向 record） | 同上 | 否 |
| PARENT_OF | parent → child | HUMAN（D14 の階層決定） | 否 |
| SHARES_COMPONENT（DRIVER / CHANNEL / DOMAIN）/ SAME_SUBJECT | 対称 | **DERIVED**（identity core から再計算。record にしない） | 構造一致のみ |
| RELATED_TO | 対称 | OBSERVED_ASSOCIATION 相当。co-occurrence / 同一 source 内の併記から **提案**としてのみ | 提案のみ（relation record にするのは HUMAN decision 後） |

relation にも **certainty class**（HYPOTHESIZED_RELATION / EVIDENCE_SUPPORTED_RELATION / SOURCE_ASSERTED_RELATION /
OBSERVED_ASSOCIATION）を必須にし、件数で class を上げない（A1 §12 と同じ規則）。relation は identity に影響しない
（root / observation id 不変）。撤回・訂正は新 record（`supersedes_relation_id`、`retracts_relation_id`）。

### 4.4 必要性の評価

Graph は Phase 7 Narrative の価値が高い（順序・因果の説明・親子の圧縮）が、reviewed Theme が複数存在して初めて意味を
持つ。**P6-B の前半では不要**であり、dedup の variant 分類（SCOPE_VARIANT / PARENT_CHILD_CANDIDATE）が relation の
最初の供給源になる。順序は §18。

---

## 5. D11 Lifecycle options

### 5.1 何が lifecycle を決めるか（監査結果）

| 決定要因 | 扱い | 根拠 |
|---|---|---|
| human governance（受理 / 却下 / 引退 / 再開 / merge / split / successor） | **authoritative**。governance facet の effective event type | A1 §16、A3 §11 |
| evidence support（SUPPORTS の visible attachment） | evidence 層の入力（件数は状態名にしない） | A1 §4 / §14 |
| contradiction（CONTRADICTS） | evidence 層 flag `CONTESTED` | A2 §9、`has_contradicting_evidence` |
| invalidation（INVALIDATES、無効化条件への対応） | evidence 層 flag `INVALIDATION_EVIDENCE_PRESENT`。**引退は人間** | A1 §14、A2 §15 |
| evidence diversity（independent origin ≥ 2 ∧ 日付 ≥ 2） | 資格判定（QUALIFIES / CANDIDATE_POSSIBLE / DOES_NOT_QUALIFY） | A2 §19 |
| temporal persistence（evidence 日付の span、observation 数） | evidence 層の記述量（`evidence_span_days`、`observation_count`）。閾値で昇格しない | A1 §13（数値閾値を定めない） |
| new evidence velocity（window 内の attached_at 件数） | 記述量 `attachments_in_window`。状態名にしない。`STALE` は「window 内に新規 evidence 付与なし」という**事実**の flag | A0.5 F-7 |
| market confirmation（mapping series の動き） | **P6-B では lifecycle 入力にしない**。mapping は記録のみ。市場観測は PRIMARY evidence として人間 / rule が attachment するときだけ意味を持つ | A2 §14、「価格が上がったから強い」禁止 |
| P5 calibration / prediction 正誤 | **禁止継続** | F-10 |
| LLM 出力 | 提案のみ。lifecycle 入力にしない | A1 §17 |

### 5.2 2 層 lifecycle（推奨）

**governance 層（authoritative。既存語彙で表現。新 event 種別不要）**

| 状態名（候補） | 導出（governance facet） |
|---|---|
| CANDIDATE | NO_GOVERNANCE、または effective event が CANDIDATE_REJECTED 以外で受理前 |
| REVIEWED | effective ＝ CANDIDATE_ACCEPTED / REOPENED（＋ その後の ROLE_CORRECTION / CERTAINTY_CHANGE / METADATA_CORRECTION 承認） |
| REJECTED | effective ＝ CANDIDATE_REJECTED |
| RETIRED | effective ＝ RETIRED |
| MERGED / SPLIT / SUPERSEDED | effective ＝ MERGE / SPLIT / SUPERSEDED_BY_ROOT（terminal lineage） |
| GOVERNANCE_UNRESOLVED | governance facet UNRESOLVED（fork）。潰さない |

**evidence 層（derived。保存しない。`resolve(root, T)` から純関数で計算）**

| flag / 値 | 導出 |
|---|---|
| qualification ∈ {DOES_NOT_QUALIFY, THEME_CANDIDATE_POSSIBLE, QUALIFIES_SEMANTICALLY} | `derived.qualification.status` |
| CONTESTED | `has_contradicting_evidence` |
| INVALIDATION_EVIDENCE_PRESENT | `has_invalidating_evidence` |
| UNEVIDENCED / SINGLE_SOURCE / SINGLE_DATE | 資格診断（NO_COUNTED_EVIDENCE / SINGLE_SOURCE_ORIGIN / SINGLE_EVIDENCE_DATE） |
| STALE(window) | `[T − window, T]` に attached_at を持つ visible attachment が無い（window は config 値） |
| REVISED_RECENTLY(window) | 同 window に observation recorded_at がある |
| independent_origins / evidence_dates / evidence_span_days / observation_count / attachments_in_window | 記述量（score ではない） |

**採用しない語彙**: EMERGING / ESTABLISHED / ACCELERATING / MATURE / WEAKENING / DORMANT を状態名として持たない。これらは
価格・勢い・件数の連想を伴い、A1 §13「数値閾値を定めない」と F-10 に反しやすい。必要なら Phase 7 が evidence 層の
記述量から**表現**として選ぶ（Theme 層は語らない）。INVALIDATED は状態名ではなく「INVALIDATION_EVIDENCE_PRESENT ＋ 人間の
RETIRED（reason に無効化条件 ref）」の組で表す。

### 5.3 選択肢比較

| 案 | 内容 | 判定 |
|---|---|---|
| L-A historical 型（件数・regime 数・span 閾値で候補段階を自動昇格） | `corpus_research/lifecycle.py` 型 | REJECT（件数昇格。ただし「機械は候補上限まで」「limitations 必須」「recompute-not-mutate」の原則は継承） |
| L-B 単一状態機械（新 governance event 種別を追加して人間が状態名を宣言） | INVALIDATED / DORMANT 等を event に | 保留（語彙 version 変更 ＝ Foundation 変更。必要性が示されるまで採らない） |
| L-C **2 層（governance authoritative ＋ evidence derived）** | §5.2 | **採用候補** |

---

## 6. D12 Discovery options

| 方式 | 入力 | 出力 | LLM | 誤分類 risk | 判定 |
|---|---|---|---|---|---|
| rule-based（historical `theme_matcher` 型の strong / weak / exclude 信号） | SourceDocument / NewsItem の見出し・本文 field、Fact | **topic hit**（Theme ではない）→ 「既存 root への evidence 候補」または「新 Theme 候補の trigger」提案 | なし | 低〜中（keyword ＝ 機構ではない。提案止まりなら安全） | 採用（提案のみ） |
| taxonomy-based | taxonomy slug × 既存 root の METADATA TAXONOMY | 分類提案・dedup の補助 | なし | 低 | 採用（語彙採否後） |
| cluster-based（evidence 共有・同一 origin group・同一 typed_reference の共起） | Foundation attachment の origin / subject | 「同じ evidence 群を共有する root 群」「未付与の evidence 群」提案 | なし | 中（co-occurrence を Theme にしない規律が必要） | 採用（構造一致のみ。embedding なし） |
| LLM-assisted | 文書 → 機構の構造化提案（driver / channel / domain / consequence / scope / 無効化条件） | ThemeProposal（LLM_PROPOSAL provenance） | あり | 高（幻覚・因果断定） | 最後（proposal-only、B7） |
| hybrid | rule / cluster で trigger → LLM が構造化 → 人間が受理 | 同上 | あり | 中 | 将来形（B7 以降） |

**Discovery は RootRecord を自動作成してよいか**: **否（既定）**。理由: root は削除できず却下も履歴に残る（A1 不変条件 25）
ため、自動作成は canonical journal を恒久的に汚す。Foundation は RULE creator の候補 root を許すが、P6-B では
「提案 → 人間受理 → `plan_candidate` / `execute_candidate`（HUMAN creator、provenance に proposal id）」を既定とし、
RULE creator による自動実体化は dedup・retire 運用が確立した後に監督者が個別認可する（§25）。

Discovery の出力は **topic hit ≠ Theme** を型で区別する: `EVIDENCE_CANDIDATE`（既存 root への付与候補）と
`THEME_CANDIDATE`（新 root 候補。機構 4 component と scope と無効化条件が**構造化されていなければ**受理不能）。

---

## 7. D13 Dedup options

A2 §12.3 凍結: fingerprint similarity ≠ identity equality、自動 merge 禁止、fuzzy / embedding は Phase 6 で用いない。

| ケース | 検出（決定論） | 提案種別 | 人間の選択肢 |
|---|---|---|---|
| duplicate candidate | `semantic_fingerprint` 一致（異 root） | DUPLICATE_CANDIDATE | MERGE（Foundation event）／ NOT_DUPLICATE（decision 記録）／ PARENT_OF relation |
| overlapping Theme | identity core 一致・consequence / scope 差 | SCOPE_VARIANT | MERGE ／ PARENT_OF ／ 別 Theme と確定 |
| parent / child | scope が包含関係（REGION / INDUSTRY token の包含。PERIOD_FRAME 同一） | PARENT_CHILD_CANDIDATE | PARENT_OF relation ／ 却下 |
| same mechanism different scope | identity core 一致・scope token 集合が非包含 | SCOPE_VARIANT | PARENT_OF（共通親を新 root として人間が作る）／ 別 Theme |
| same subject different mechanism | subject 一致・driver / channel 差 | SUBJECT_VARIANT | RELATED_TO 提案 ／ 何もしない（正当に別 Theme） |
| same mechanism different subject | driver ＋ channel ＋ domain 一致・subject 差 | MECHANISM_VARIANT | RELATED_TO / AMPLIFIES 提案 ／ 何もしない |

規則: dedup 提案は **review proposal**（M3 journal）であり、Foundation に書くのは人間の MERGE / SPLIT decision だけ。
提案は決定論的（同じ canonical bytes → 同じ提案 id）。提案の却下（NOT_DUPLICATE）も記録し、同じ組を再提示しない
（提案 id ＝ content id なので冪等）。component 集合の重なり比率による**順位付け**は「fuzzy」に当たるかの判断を監督者に
委ねる（§25）。既定は exact 一致のみ。

---

## 8. D14 Granularity options

| 問い | 回答（候補） |
|---|---|
| 1 root ＝ 何か | **1 つの機構（driver → channel → domain）＋ 1 つの subject**。scope の精緻化は同 root（A2 §2.3 #5）、driver / channel / subject / domain の置換は別 root（Foundation が強制） |
| 階層 | identity に入れない。PARENT_OF relation record（§4）で表す。親 Theme も機構を持つ本物の Theme でなければならない（機構の無い「傘」は taxonomy node であり Theme ではない: A1 §7） |
| 粗すぎる Theme の検出 | derived 診断: AFFECTED_DOMAIN が MACRO_AGGREGATE のみ ∧ INDUSTRY / REGION token なし → `BROAD_SCOPE`（提示のみ） |
| 細かすぎる Theme の検出 | subject typed_reference が company / ticker 種別 → 企業固有 thesis の疑い `ENTITY_SPECIFIC_SUBJECT`（A1 §18 / 不変条件 23。Phase 9 領域として提示のみ） |
| 同一 subject の複数 Theme | 正当（機構が異なる）。SUBJECT_VARIANT として関係提案 |
| 粒度変更 | scope の狭め / 広げ ＝ 同 root revision。機構の分割 ＝ SPLIT、統合 ＝ MERGE（人間） |

粒度 policy は **review guideline ＋ derived 診断**として持ち、自動で root を作り替えない。

---

## 9. Taxonomy assessment

| 資産 | 判定 | 理由 |
|---|---|---|
| `theme_taxonomy.yaml`（30 slug、浅い parent、strong / weak / exclude 信号、v1.0.0） | **REDESIGN** | slug・階層・変更管理（slug 意味不変、version bump、append-only 再分類）は有用。keyword 信号は識別規則であり Theme 語彙ではないので **discovery 側 knowledge に分離**する。effective date・provenance が無い |
| `themes.yaml`（label ＝ identity、keywords、durable_themes） | **REJECT**（alias / unmapped 表のみ migration 参考） | label を key にする脆さ、taxonomy と重複、durable の hard-code |
| `THEME_TAXONOMY_SPEC.md` | **REFERENCE_ONLY** | 変更管理規則を新 spec に抽象化 |
| 現 branch `config.yaml themes / durable_themes / macro_themes`（legacy topic 語彙。P4 production が使用） | **触れない**（D21） | Theme identity と無関係。Phase 6 は P4 config を変更しない |

新 taxonomy（P6-B4）: `knowledge/themes/theme_taxonomy.yaml`（案）に slug / label / parent / description / version /
status、**信号語は別 file**（`knowledge/themes/discovery_signals.yaml` 案）。運用: root の分類は METADATA TAXONOMY 値
（slug 文字列。metadata record の reason / provenance_ref に taxonomy version）。taxonomy 変更は metadata の新 record で
あり observation id・fingerprint・資格に無関係（A2 §12.2 で除外済み。構造的に保証）。

---

## 10. Entity linkage assessment

| 必要箇所 | 内容 | catalog 依存 |
|---|---|---|
| subject / component の typed_reference 正規化 | discovery 提案で `company:` / `sector:` / `commodity:` 等の安定 id を与える | あり（alias 安全度 3 段） |
| DIRECTLY_EVIDENCED link | Foundation が visible evidence から再計算済み | なし |
| INFERRED_EXPOSURE link | HUMAN / RULE / LLM_PROPOSAL の提案。順位付け・推奨なし | あり（entity id の存在確認） |
| dedup の SAME_SUBJECT | typed_reference の文字列一致に依存 → catalog で alias を吸収 | あり |
| monitoring | entity 別 evidence 集計（記述のみ） | 任意 |

判定: `core_entities.yaml` ＋ `ENTITY_CATALOG_SPEC.md` は **PORT**（id 体系 `<kind>:<slug>`、alias 3 段、load 検証、
unknown identifier → review queue）。ただし **watchlist 結合を切り**、effective date / lifecycle（rename / delist）/
provenance を追加した versioned knowledge として P6-B4 で port する。Foundation の `ThemeEntityKind` は
`databank.news_model.EntityKind` の鏡像なので、catalog の kind もそれに合わせる。企業 ticker 推奨・beneficiary ranking
は Phase 9（P6-B では INFERRED_EXPOSURE の**記録**まで）。

---

## 11. Monitoring / change detection

### 11.1 方式

**優先: `diff(resolve(root, T1), resolve(root, T2))` の純関数（`ThemeChangeSet`）。** canonical を書かない。現在時刻を
呼ばない（T1 / T2 は注入）。`ThemeResolution` は frozen dataclass なので、差分は field 単位で決定論的に列挙できる。

| 差分項目 | 導出 |
|---|---|
| OBSERVATION_REVISED | `observation.observation_id` の変化（chain 上の中間 observation も `history` から列挙） |
| SEMANTIC_FIELD_CHANGED（certainty_class / scope / limitations / invalidation_conditions / consequences / inferred_links） | observation の field 比較（identity core は同 root で不変） |
| EVIDENCE_ADDED / EVIDENCE_DROPPED（role 別） | `evidence.visible` の attachment_key 集合差 ＋ `dropped_attachments` |
| ROLE_CORRECTED | 同 attachment_key で role が変化 |
| NEW_SOURCE_ORIGIN / NEW_EVIDENCE_DATE | `derived.qualification.independent_origins` / `evidence_dates` の差 |
| QUALIFICATION_CHANGED | `qualification.status` の遷移 |
| CONTRADICTION_APPEARED / INVALIDATION_APPEARED | flag の false → true |
| GOVERNANCE_CHANGED | `governance.effective_event_type` / reversed の差 |
| METADATA_CHANGED / MAPPING_CHANGED | facet の record id 差 |
| LINEAGE_CHANGED | lineage 集合差（merge / split / successor 宣言） |
| PENDING_RESOLVED / PENDING_APPEARED | pending 集合差 |
| DEREFERENCE_CHANGED | 別 field（canonical 差分と混ぜない） |

2 つの時間軸を区別する: **knowledge diff**（attached_at / recorded_at ベース: 「T1〜T2 の間に Theme system が知った
こと」）と **evidence-time diff**（evidence_time ベース: 「T1〜T2 の間に世界で起きたこと」）。resolver の `not_yet_attached`
/ `evidence_after_cutoff` がそのまま材料になる。

### 11.2 monitoring runner

全 root について `(T_prev, T_now)` の change set を計算し、`ThemeChangeReport`（derived。data_root 配下の report 出力、
再生成自由）を出す。含める: 変化した root 一覧、要 review 事項（CONTESTED になった、INVALIDATION_EVIDENCE_PRESENT に
なった、PENDING が残っている、STALE、dedup 提案あり）。含めない: score、順位、推奨、価格。runner は Foundation store を
read only で開く。時計は注入（workflow / scheduling は本 gate の範囲外）。

### 11.3 決定論の保証

同一 canonical bytes ＋ 同一 (T1, T2) → 同一 change set（frozen dataclass 等価）。shuffle・再読込・別 process で不変
（A4d の test 流儀を再利用）。

---

## 12. Evidence / support / contradiction evolution

- **evidence ledger view（derived）**: root の全 observation chain を recorded_at 順に辿り、各段で visible attachment を
  role 別に集計（件数・origin 数・日付集合・kind 別）。数値は記述量であり score ではない。
- **evolution ＝ change set の列**: 自然な checkpoint は各 observation の `recorded_at` と各 attachment の `attached_at`。
  この列から「支持が増えた」「反証が現れた」「無効化 evidence が付いた」「source が独立に増えた」を**列挙**する。
- **contradiction は相殺しない**: 支持 n 件 − 反証 m 件のような合成値を作らない。CONTESTED は反証が 1 件でもあれば真。
  反証 0 件は「記録なし」であって確証ではない（A1 §14）。
- **invalidation**: INVALIDATES role ＋ `invalidation_condition_ref` で「どの無効化条件に対応するか」を保持済み。
  evolution はその条件 ref 別に提示する。引退は人間。
- **上流改訂**: dereference（SUPERSEDED / UNUSABLE / NOT_FOUND）は canonical 差分と別欄。上流が変わっても Theme 履歴は
  書き換えない（A3 §16）。要 review 事項として提示するだけ。

---

## 13. Governance requirements（P6-B で新たに人間 decision が必要になるもの）

A1 §16 の authority ladder を維持する（automatic は L1 候補提案まで、human は reviewed / merge / split / retire /
reopen / reviewed の class 変更 / evidence 役割訂正）。P6-B で追加される human-required action:

| action | 記録先 | 備考 |
|---|---|---|
| 提案の受理 / 却下 / 保留（THEME_CANDIDATE、EVIDENCE_CANDIDATE、DUPLICATE、RELATION、LABEL、MECHANISM_REVISION、CONTRADICTION_CANDIDATE） | proposal journal の `ProposalDecision`（HUMAN、reason 必須） | 受理の実体化は Foundation の既存操作（candidate 作成 / attach_evidence / MERGE / metadata）で行う |
| relation の宣言 / 撤回 / certainty 変更 | relation journal（HUMAN。RULE / LLM は提案のみ） | CAUSES は HUMAN または SOURCE_ASSERTED |
| dedup の NOT_DUPLICATE 確定 | ProposalDecision | 同じ組を再提示しない根拠 |
| taxonomy version の採用、entity catalog version の採用、discovery signal set version の採用 | knowledge の version bump ＋ decision 記録 | 機械が version を上げない |
| RULE creator による候補 root の自動実体化の認可（もし行うなら） | 監督者決定（§25） | 既定は不可 |
| lifecycle evidence 層の window 値（STALE 等）の設定 | `config.yaml`（運用規約: 設定値は config.yaml） | 意味論ではなく表示 window |

自動で起きてはならないこと（再確認）: RootRecord の自動作成（既定）、MERGE / SPLIT / RETIRE、class 変更、evidence 役割
訂正、relation の CAUSES 化、lifecycle governance 層の遷移、taxonomy / catalog の version 変更。

---

## 14. LLM boundary

| 許可（proposal-only） | 禁止 |
|---|---|
| 文書からの機構構造化提案（driver / channel / domain / consequence / scope / 無効化条件の**候補**） | evidence の成立（LLM_PROPOSAL role は資格に算入されない。Foundation が強制） |
| label / description 提案（metadata の provenance LLM_PROPOSAL） | RootRecord / governance event の作成（Foundation: governance は HUMAN のみ） |
| relation 提案（RELATED_TO / AMPLIFIES 等。certainty HYPOTHESIZED） | CAUSES の確立、merge の確定、reviewed 状態、lifecycle 遷移 |
| 反証候補・無効化条件候補の提示 | 因果断定、推奨、価格・目標 |
| dedup review の説明文（人間向け補助） | dedup の確定 |

すべての LLM 出力は proposal journal に **LLM_PROPOSAL provenance・model 非依存の provider ref・入力 evidence ref**
付きで残し、canonical に入るのは人間 decision の後だけ。P6-B1〜B6 は LLM を使わない。LLM 実装は B7 で、
`core.contracts.LLMProvider` 境界の precedent（vendor 中立・鍵なし）を再表現する（historical `llm_classifier` は
NewsClassification 結合のため port しない）。

---

## 15. Phase 7 handoff boundary

Theme 層が Phase 7 Narrative に渡すのは **構造化 view のみ**（prose なし・順序付けなし・読者別 framing なし）:

| interface（案） | 内容 |
|---|---|
| `resolve(root, T)` | Foundation そのまま |
| `change_set(root, T1, T2)` | §11 |
| `lifecycle_view(root, T)` | §5.2（governance 層 ＋ evidence 層） |
| `relations_at(T)` / `relations_of(root, T)` | §4（typed directed、certainty 付き） |
| `evidence_ledger(root, T)` | §12 |
| `open_proposals(T)` | 人間 review 待ち（Narrative は「未確定」として扱う） |

禁止（P6-B 全体）: MorningBrief / MarketSignal / P5 / Compass / 公開 `/v2` / Pages / 顧客出力 / 推奨 / BUY-SELL /
目標価格 / portfolio weight。Theme → Compass / Brief の接続は別 gate。Phase 7 は Theme 層の view を読むだけで、Theme 層は
Phase 7 を import しない。

---

## 16. Historical asset classification（read only。runtime は port しない）

| 資産 | 構造（監査所見） | 判定 | 継承するもの |
|---|---|---|---|
| `knowledge/enrichment/theme_taxonomy.yaml` | 30 slug、parent 5 件（深さ ≤ 3）、related は無型隣接、strong / weak / exclude 信号を語彙 file に同居、file version のみ、evidence / 時刻 / provenance なし | **REDESIGN** | slug 不変規則、階層、変更管理。信号語は discovery knowledge へ分離 |
| `knowledge/theme_relations/themes.yaml` | label ＝ identity、keyword 部分一致、durable 一覧、alias 表 | **REJECT** | alias / unmapped 表を migration 参考にのみ |
| `knowledge/theme_relations/theme_graph.yaml` | 37 key・114 edge、無向と宣言しつつ非対称 30 件、型・重み・符号・evidence・時刻なし、定義外 node 8 | **REDESIGN**（seed 参照） | node 集合と edge 候補を RELATED_TO **提案**の seed に。edge 意味論は §4 で再定義 |
| `knowledge/entities/core_entities.yaml` ＋ `ENTITY_CATALOG_SPEC.md` | 80 entity、`<kind>:<slug>` id、alias 3 段（safe / context / explicit）、load 検証、review queue 経路、version を分類 record に記録。effective date / lifecycle / provenance なし。watchlist 結合 | **PORT**（規則と id 体系）/ 文書は REFERENCE | id 体系、alias 安全度、検証、unknown → review。effective date・lifecycle を追加し watchlist 結合を切る |
| `docs/databank/THEME_TAXONOMY_SPEC.md` | 変更管理（version bump、slug 意味不変、append-only 再分類） | **REFERENCE_ONLY** | 変更管理規則 |
| `enrichment/theme_matcher.py` | 純関数、strong 1 件 or weak ≥ 2 件、exclude 抑制、role ＝ 見出し位置、matched surface を provenance に保持、as-of なし | **REDESIGN**（原理は PORT 相当） | 保守的判定規則・信号 provenance。出力を「topic hit 提案」に変え、taxonomy version を pin する |
| `enrichment/taxonomy.py` | YAML loader ＋ 構造検証、event taxonomy と horizon | **REDESIGN** | loader / 検証の規律のみ |
| `corpus_research/lifecycle.py` | 状態 OBSERVED → NEW_PATTERN_CANDIDATE → REVIEW_CANDIDATE → STRONG_PATTERN_CANDIDATE（機械上限）、APPROVED / REJECTED / SUPERSEDED は人間、support / regime / span 閾値、limitations 必須、recompute-not-mutate | **REFERENCE_ONLY** | 「機械は候補上限まで」「limitations 必須」「再計算であって変異ではない」。件数閾値昇格は採らない |
| `corpus_research/patterns.py` | 共起 tuple（state ＋ evidence ＋ outlook）の content-addressed id、version を id に含む、evidence ref 保持、複数粒度の同時割当 | **REFERENCE_ONLY** | version を identity に含める発想（Foundation は既に schema / 語彙 version を id payload に含む）。共起 tuple は採らない |
| `corpus_research/review_queue.py` | kind 別 item、OPEN のみ、auto_approval false、reason ＋ evidence ref、注入時計、決定 record なし | **REDESIGN**（原理は PORT 相当） | 人間専用・理由 ＋ evidence 必須・冪等 id。typed schema と decision record を追加して proposal journal に再表現 |
| `docs/compass_dna/THEME_DISCOVERY_RULES.md` | 機密 Compass 各号由来の named chain を含む | **REFERENCE_ONLY（機密）** | 原則（需要起点 → 制約 → 技術 → 供給網 → 実データ確認 → risk、Emerging 信号類型、禁止事項）を抽象化して discovery guideline に。原文・named chain・号 / 頁は転記しない |

A0.5 §2.2 の判定との差分（本書は推奨であり A0.5 の決定を書き換えない）: `themes.yaml` は B（PORT LATER）→ **REJECT**
（taxonomy REDESIGN に吸収。alias 表のみ参考）、`theme_graph.yaml` は B（P6-D graph の seed）→ **REDESIGN**（seed 参照。
同趣旨）、`core_entities.yaml` は B → **PORT**（同方向。effective date 追加が条件）、`theme_matcher.py` / `taxonomy.py` は
B → **REDESIGN**（原理は継承、出力型を提案に変更）、`lifecycle.py` / `patterns.py` / `review_queue.py` は C と同じ
（原則のみ継承）。

横断所見: historical 資産はいずれも **時刻を持たない**（as-of 不能、version は file 単位）、**evidence ref を持たない**
（entity / taxonomy / graph）、**機構を持たない**。P6-B が継承するのは規律（id 不変、version、人間専用 review、limitations
必須、保守的 matching）であり、model そのものではない。

---

## 17. Dependency graph

```
Foundation（凍結）: model / fingerprint / qualification / revision / store / operations / resolver
   │ read only（ThemeHistory.from_store / resolve / canonical_lines）
   ▼
B1 Change Detection（純 diff）──────────────┐
   │                                          │
   ▼                                          ▼
B2 Lifecycle view（governance 層 ＋ evidence 層）   B6 Monitoring runner（change report）
   │                                          ▲
   ▼                                          │
B3 Proposal journal（append-only、F-8 規律）＋ Dedup 提案（fingerprint / identity core 部分一致）
   │                        │
   ▼                        ▼
B4 Taxonomy 語彙（REDESIGN）＋ Entity catalog（PORT）＋ rule-based Discovery 提案
   │
   ▼
B5 Typed directed Relation graph（relation journal ＋ PIT 解決）──▶ B6
   │
   ▼
B7 LLM-assisted 提案（proposal-only、任意）
   │
   ▼
Phase 7 Narrative（view を読むだけ）
```

Foundation への書き込みは、B3 以降で**人間 decision の実行**として `operations`（candidate / merge / split / successor）
と `attach_evidence` / metadata append を使うときだけ。それ以外の P6-B module は read only。

---

## 18. Recommended implementation order（候補 A〜F の比較）

| 候補 | Foundation 依存 | 他機能依存 | human governance 依存 | evidence authority への影響 | identity への影響 | PIT への影響 | LLM 依存 | 誤分類 risk | Phase 7 価値 |
|---|---|---|---|---|---|---|---|---|---|
| A Lifecycle first | resolver | change 観測が無いと evidence 層が作れない | governance 層は既存 event | なし | なし | なし | なし | 中（状態名の意味づけ） | 高 |
| B Graph first | resolver | reviewed Theme が複数必要、dedup の variant が供給源 | relation 宣言は人間 | なし（relation は evidence ではない） | なし（別 journal） | relation に PIT が必要 | なし（提案は後） | 中（co-occurrence → 因果の誘惑） | 高 |
| C Discovery first | model / operations | taxonomy 語彙・entity catalog・proposal journal・dedup が先に必要 | 提案受理が全部人間に来る | 高（evidence 候補の誤付与 risk） | 高（root 乱立） | なし | 任意 | **高** | 中 |
| D Taxonomy first | なし | 単独では価値が出ない（metadata 値の語彙） | version 採用 | なし | なし（構造的に無関係） | なし | なし | 低 | 低〜中 |
| E Monitoring / Change first | resolver のみ | なし | なし | なし | なし | なし（PIT を使う側） | なし | **なし** | 高（「何が変わったか」） |
| **F 推奨順序** | E → A → dedup / proposal → D ＋ entity ＋ C（提案のみ） → B → runner → LLM | 各段が前段だけに依存 | 段階的に増える | 提案止まりで保護 | 保護 | 保護 | 最後 | 段階的 | 高 |

**推奨: F。** 具体的には B1 Change Detection → B2 Lifecycle → B3 Proposal ＋ Dedup → B4 Taxonomy ＋ Entity ＋ Discovery
（proposal-only）→ B5 Graph → B6 Monitoring runner ＋ derived index → B7 LLM。理由: MVP ⑥ を先に閉じる、authority を
増やす段（B3 / B5）の前に決定論の道具（diff / lifecycle）を揃える、誤分類 risk の高い discovery を proposal-only かつ
dedup 完備後に置く、graph は variant 分類と reviewed Theme の存在を前提にする。

---

## 19. Proposed P6-B subphases

| subphase | 内容 | 新規 file（案。1 機能 ＝ 1 file） | Foundation 変更 | human action |
|---|---|---|---|---|
| **P6-B1 Change Detection** | `ThemeChangeSet` 純関数、knowledge / evidence-time の 2 軸、決定論 test（shuffle / 再読込 / 別 process） | `src/intelligence/theme_intelligence/change.py`、`tests/intelligence/test_theme_change.py` | なし | なし |
| **P6-B2 Lifecycle view** | governance 層 ＋ evidence 層、window は `config.yaml`（`theme_intelligence.lifecycle.stale_window_days` 等） | `theme_intelligence/lifecycle.py`、test | なし | window 値の決定 |
| **P6-B3 Proposal journal ＋ Dedup** | `ThemeProposal` / `ProposalDecision` の append-only journal（`<data_root>/theme_intelligence/theme_proposals.jsonl`、`theme_decisions.jsonl`）、dedup 提案 6 種、受理時の Foundation 操作の橋渡し | `theme_intelligence/proposals.py`、`proposal_store.py`、`dedup.py`、test | なし | 提案 decision |
| **P6-B4 Taxonomy ＋ Entity ＋ Discovery** | taxonomy / signal / entity の versioned knowledge、rule-based topic hit → EVIDENCE_CANDIDATE / THEME_CANDIDATE 提案、typed_reference 正規化 | `knowledge/themes/*.yaml`（新設。既存 knowledge は不変）、`theme_intelligence/taxonomy.py`、`entities.py`、`discovery.py`、test | **語彙拡張が必要なら FOUNDATION_CHANGE 候補**（§21） | version 採用、提案 decision |
| **P6-B5 Relation graph** | `ThemeRelation` journal（`theme_relations.jsonl`）、PIT 解決、lineage との分離、derived SHARES_* | `theme_intelligence/relations.py`、`relation_store.py`、test | なし | relation 宣言 / 撤回 |
| **P6-B6 Monitoring runner ＋ derived index** | 全 root の change report、要 review 一覧、A3 §20 の SQLite index（stale 検知付き） | `theme_intelligence/monitor.py`、`index.py`、test | なし | なし（scheduling は別 gate） |
| **P6-B7 LLM-assisted 提案** | 機構構造化 / label / relation / 反証候補の LLM_PROPOSAL | `theme_intelligence/llm_proposals.py`、test | なし | 提案 decision |

package 境界（案）: `src/intelligence/theme_intelligence/`（名称は監督者決定）。許可 import ＝ `core.ids`、`core.time`、
`themes.model` / `fingerprint` / `qualification` / `revision` / `store`（read-only API と、人間 decision 実行時の
append）/ `operations` / `resolver`、必要なら `sources.model` / `databank.news_model` / `facts.model` の **model のみ**。
禁止 ＝ A0.5 §7 と同じ（compass / reports / predictions / internals / context / market store / ingestion / normalization /
network / legacy）。`EXCLUDED_PACKAGES` に追加して production closure から排除。凍結 P4 / P5 module と `themes` は
`theme_intelligence` を import しない。

---

## 20. Proposed schemas / interfaces（field 名は未凍結。監督者決定の材料）

```
ThemeChangeSet(root_id, t1, t2, resolver_version, change_version,
               status_before, status_after,
               observation_before, observation_after, intermediate_observation_ids,
               semantic_changes: (field, before, after)…,
               evidence_added: (attachment_key, role, evidence_time, attached_at)…,
               evidence_dropped: (attachment_key, reason)…,
               role_corrections: (attachment_key, role_before, role_after)…,
               new_source_origins: int, new_evidence_dates: (date…),
               qualification_before, qualification_after,
               contradiction_appeared: bool, invalidation_appeared: bool,
               governance_before, governance_after, metadata_changes, mapping_changes,
               lineage_added, pending_resolved, pending_appeared,
               dereference_changes)            # canonical 差分と別欄
LifecycleView(root_id, t, governance_state, evidence_flags: frozenset, measures: {…}, window_days, sources: (…))
ThemeProposal(proposal_id = content id "thprop_", kind ∈ {THEME_CANDIDATE, EVIDENCE_CANDIDATE, DUPLICATE_CANDIDATE,
              SCOPE_VARIANT, PARENT_CHILD_CANDIDATE, SUBJECT_VARIANT, MECHANISM_VARIANT, RELATION, LABEL,
              MECHANISM_REVISION, CONTRADICTION_CANDIDATE},
              subject_roots, payload（kind 別。THEME_CANDIDATE は機構 4 component ＋ scope ＋ 無効化条件を構造化）,
              evidence_refs, provenance_class ∈ {RULE, LLM_PROPOSAL, HUMAN}, provenance_ref, rule_version /
              taxonomy_version / catalog_version, recorded_at)
ProposalDecision(decision_id "thdec_", proposal_id, decision ∈ {ACCEPTED, DISMISSED, DEFERRED, NOT_DUPLICATE},
              actor_class = HUMAN, actor_ref, reason, result_refs（作成 root id / event id / metadata id）, recorded_at)
ThemeRelation(relation_id "threl_", from_root, to_root, relation_type, certainty_class, evidence_refs,
              provenance_class, provenance_ref, reason, recorded_at, valid_from,
              supersedes_relation_id, retracts_relation_id)
RelationResolution(t, relations: (…), diagnostics)          # PIT。撤回済みは効力なし、履歴は残す
TaxonomyNode(slug, label, parent, description, status, since_version)   # knowledge。信号語は別 file
EntityRecord(entity_id "<kind>:<slug>", kind, name, aliases_safe, aliases_context, context_terms,
             attributes, valid_from, valid_to, superseded_by, since_version)
```

規律: 全 record は canonical JSON ＋ content id、append-only、CONFLICT / corruption fail closed、data_root 明示、
現在時刻は注入、repo に data を置かない（F-8 と同じ）。Foundation store の code は再利用しない（authority が別）が、
同じ規律を別 module で満たす。

---

## 21. Foundation change requirements

推奨経路 B1〜B6 に **必須の Foundation 変更は無い**。将来の候補（実装しない。監督者決定事項）:

| 候補 | 発生条件 | 影響 |
|---|---|---|
| FC-1 mechanism 語彙の拡張（`MECHANISM_CATEGORIES`）と **語彙 version の複数受理** | B4 discovery で `OTHER` 頼みになる場合。現行 model は `mechanism_vocabulary_version` を**厳密一致**で検査するため、新 version の record を書くと旧 runtime は読めず、旧 record を新 runtime が読むには受理集合が必要 | `model.py`（＋ 語彙 version gate、A3 §22）。id は version を payload に含むので既存 id は不変 |
| FC-2 governance 語彙の追加（例: INVALIDATED、LIFECYCLE_STATE_ASSERTED、RELATION_APPROVED） | L-B（§5.3）を採る場合、または relation 承認を Foundation event にしたい場合 | `model.py` governance 語彙 version。推奨経路では不要（relation は別 journal、無効化は RETIRED ＋ reason） |
| FC-3 attachment / observation への field 追加（例: proposal id の逆参照） | 提案 → 実体化の追跡を canonical に持ちたい場合 | 不要。provenance_ref / reason に proposal id を入れれば追跡できる |
| FC-4 store の一覧 API（全 root id の列挙） | 規模が出たとき | 不要。`ThemeHistory.from_store` / `canonical_lines` で足りる。B6 の index が担う |
| FC-5 metadata TAXONOMY の複数値 | 1 root に複数 slug を付けたい場合 | **不要**。TAXONOMY / ALIAS は set 値（sorted unique の tuple）として Foundation が既に受理する（LABEL / DESCRIPTION は 1 値）。複数 slug は 1 record の値集合で表す |

判定: **FOUNDATION_CHANGE_REQUIRED ではない**。FC-1 は B4 着手時に再評価する。

---

## 22. Risks

| risk | 内容 | 緩和 |
|---|---|---|
| R1 root 乱立 | discovery の自動実体化で却下 root が canonical に蓄積 | proposal-only 既定。実体化は人間 |
| R2 co-occurrence → 因果 | graph / cluster discovery で RELATED_TO が CAUSES に昇格 | relation certainty class ＋ CAUSES は HUMAN / SOURCE_ASSERTED のみ |
| R3 lifecycle の score 化 | evidence 層の記述量が閾値昇格に転用される | 状態名を件数で定義しない。window は表示用 config |
| R4 語彙の硬直 | mechanism 語彙が実データに足りず OTHER が増える | B4 で FC-1 を評価。OTHER は normalized_statement を identity に含めるので識別は維持される |
| R5 二重 authority | proposal / relation journal が Foundation と矛盾 | journal は Foundation を参照するだけ。矛盾は解決時に診断（PROPOSAL_STALE 等） |
| R6 upstream evidence の不在 | 現 branch に Statement producer・文書 evidence 経路の運用が無い | discovery は SourceDocument / NewsItem / Fact の既存 model 参照で足りる（A0.5 §3）。producer は別 gate |
| R7 機密混入 | historical rule 原文・named chain の転記 | §16 の方針。guideline は抽象化のみ。hygiene guard を P6-B test に含める |
| R8 P4 / P5 への波及 | production bundle closure に新 package が混入 | `EXCLUDED_PACKAGES` ＋ boundary test |
| R9 時計依存 | monitoring runner が現在時刻を呼ぶ | 注入のみ。純関数 ＋ runner の分離 |

---

## 23. Blockers

なし。監督者決定待ち事項は §25。

---

## 24. Tests / guards needed later

- B1: change set の決定論（shuffle / 再読込 / 別 process）、A4d world の全 checkpoint 対に対する golden、knowledge /
  evidence-time 軸の分離、dereference 差分の分離。
- B2: governance 層が resolver の governance facet と 1:1、evidence 層が visible evidence だけから計算される、window 変更で
  governance 層が変わらない、価格 / P5 / LLM token の不在（source grep guard）。
- B3: proposal journal の F-8 規律（canonical / 冪等 / CONFLICT / corruption fail closed / byte 長）、提案 id の決定論、
  decision の HUMAN 限定、受理→Foundation 操作の橋渡しが Foundation の検証を迂回しない（既存 test の再利用）。
- B4: taxonomy / catalog の version pin、slug 不変、entity alias 3 段、discovery が RootRecord を書かない、topic hit ≠
  Theme（構造化のない THEME_CANDIDATE を拒否）、機密 token guard。
- B5: relation の PIT（valid_from / recorded_at）、撤回の履歴保持、lineage との分離、CAUSES の provenance 制約、
  co-occurrence からの CAUSES 生成不能。
- B6: report が canonical を書かない、index の stale 検知、rebuild 同値。
- 全体: import boundary（新 package の許可 / 禁止 module、P4 / P5 / themes からの非参照）、production bundle 排除、
  data file の非追跡、hygiene（model 識別子・path・credential・企業名の不在）。

---

## 25. Next gate recommendation

**次 gate: P6-B1 Theme Change Detection**（純 diff、Foundation 無変更、LLM なし、人間 action なし）。着手前に監督者が
決めるべき事項:

1. package 名（`theme_intelligence` 案）と import 境界の確定。
2. lifecycle 2 層の採否と evidence 層 flag の語彙（§5.2）。EMERGING 等の勢い語を採らない方針の確認。
3. discovery の proposal-only 既定（RootRecord 自動作成なし）の確認。
4. relation 語彙と certainty class（§4.3）、graph を別 journal にする方針の確認。
5. dedup で component 集合の重なり比率による順位付けを「fuzzy」とみなすか（既定: exact 一致のみ）。
6. taxonomy REDESIGN の file 配置（`knowledge/themes/`）と信号語の分離、entity catalog PORT の範囲。
7. FC-1（mechanism 語彙拡張と version 複数受理）を B4 前に別 gate として扱うか。
8. Phase 7 handoff interface（§15）の名称確定。

判定: **P6_B0_THEME_INTELLIGENCE_ARCHITECTURE_AUDIT_COMPLETE / READY_FOR_SUPERVISOR_P6_B_ARCHITECTURE_DECISIONS**。
P6-B runtime は実装しない。
