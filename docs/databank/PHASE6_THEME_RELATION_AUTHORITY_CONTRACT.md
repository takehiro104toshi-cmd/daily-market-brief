# Phase 6 / P6-B5B — Theme relation authority 契約

Theme root どうしの意味論的関係を記録する **別 authority** の契約。B5A architecture 監査の決定
（B5-D1〜D10）を実装に凍結したもの。関係の **提案** 層（B5C 以降）・関係の自動生成・graph の順位付けは
本 gate に存在しない。

---

## 1. authority

| authority | file | 内容 |
|---|---|---|
| assertion | `<data_root>/theme_intelligence/relation_assertions.jsonl` | 不変の意味論的主張と、その訂正 chain |
| governance | `<data_root>/theme_intelligence/relation_governance.jsonl` | 主張そのものではない行為（RETRACTED / RESTORED） |

2 authority のみ。SQLite は無い。derived index は store 内の再構築可能な写像だけで、authority ではない。

Foundation `<data_root>/themes/` と B3 の proposal authority は読みも書きもしない。Theme root を所有せず、
`ThemeRootRecord` を複製しない。root id を参照するだけである。

## 2. schema と version

| 定数 | 値 |
|---|---|
| `RELATION_ASSERTION_SCHEMA_VERSION` | `theme_relation_assertion:0.1.0` |
| `RELATION_GOVERNANCE_SCHEMA_VERSION` | `theme_relation_governance:0.1.0` |
| `RELATION_VOCAB_VERSION` | `theme_relation_vocabulary:0.1.0` |
| `RELATION_RESOLVER_VERSION` | `theme_relation_resolver:0.1.0` |
| `RELATION_GRAPH_VIEW_VERSION` | `theme_relation_graph:0.1.0` |

record id は content address。assertion は `threl_<24 hex>`、governance event は `thrgov_<24 hex>`。
乱数 identity は無い。

**version 方針**: 関係型・主張 class・identity payload の構成を変えることは
`RELATION_VOCAB_VERSION` / schema version の変更であり、別 version の record として扱う。既存 version の
意味を後から変えない。version を上げずに型を増やすことはできない。

## 3. assertion model

```
ThemeRelationAssertion
  schema_version            identity
  relation_vocab_version    identity
  relation_assertion_id     derived（identity payload の content id）
  source_theme_root_id      identity
  target_theme_root_id      identity
  relation_type             identity
  assertion_class           identity
  source_attribution        identity（SOURCE_ASSERTED のみ。HUMAN は None）
  rationale                 identity
  evidence_refs             identity（canonical 順に整列）
  previous_assertion_id     identity
  provenance                audit（identity 外。canonical bytes には入る）
  recorded_at               audit（identity 外。canonical bytes には入る）
```

- **identity payload**: 上の identity 行のみ。`provenance` と `recorded_at` を含まない。
  同じ主張を別の人が別の時刻に記録しても同じ id になり、store で冪等に畳まれる。
- **canonical bytes**: `canonical_json(record.as_dict()) + "\n"`。`provenance` と `recorded_at` を含む。
  したがって「同 id・異 bytes」は起こりうる（記録者や時刻だけが違う）。これは CONFLICT として fail closed する。
- **検証**: root id 形式、自己辺の禁止、語彙、class ごとの必須項目、evidence の重複禁止、
  `evidence_time <= recorded_at`、credential 付き URL と machine 固有 path の禁止。

## 4. edge key

```
edge_key = source_theme_root_id | target_theme_root_id | relation_type | assertion_class | attribution_key
```

- `attribution_key` は SOURCE_ASSERTED のとき `normalize_text(attributed_to)`、HUMAN_ASSERTED のとき空。
- **derived であり authority record id ではない。** 1 つの意味論的関係の履歴に属する assertion 群をまとめる。
- 同じ辺 key の assertion は 1 本の chain を成す。辺 key が違えば別の履歴である。
- 逆向き（`B|A|...`）は別の辺 key であり、別の主張である。

## 5. 関係語彙（B5-D2）

`CAUSES` / `AMPLIFIES` / `MITIGATES` / `DEPENDS_ON` の 4 型ちょうど。すべて **有向**。

`RELATED_TO` / `PARENT_OF` / `CONSTRAINS` / `ENABLES` / `OTHER` は **存在しない**。
逆辺の便宜 record を自動生成しない。`source == target` は `SELF_RELATION`。

## 6. 主張 class と因果安全性（B5-D3 / B5-D8）

`HUMAN_ASSERTED` / `SOURCE_ASSERTED` の 2 つちょうど。`RULE_ASSERTED` / `LLM_ASSERTED` に相当する値は
**enum に存在しない**。さらに `RelationProvenance.actor_class` は `HUMAN` 固定で、RULE / LLM_PROPOSAL は
`FORBIDDEN_ASSERTION_AUTHORITY` で拒否される。rule や LLM が authority 主張を作る経路は構造的に無い。

| class | 必須 |
|---|---|
| `HUMAN_ASSERTED` | 記録者（`actor_ref`）と `rationale`。`source_attribution` は禁止 |
| `SOURCE_ASSERTED` | `source_attribution.attributed_to`、`rationale`、evidence 参照 1 件以上 |
| `CAUSES`（両 class） | evidence 参照 1 件以上 |

**凍結する文言**:

- `SOURCE_ASSERTED_MEANING = "the cited source asserted this relation"`
- `SOURCE_ASSERTED_NON_MEANING = "the system verified this relation as causal truth"`

出典の帰属から因果の真偽を推論しない。

## 7. evidence 参照

```
RelationEvidenceRef
  evidence_kind   Foundation の EvidenceKind 語彙
  ref_id          kind ごとの接頭辞検査つき
  source_origin   Foundation の SourceOrigin
  evidence_time   任意（あれば recorded_at 以前）
  locator         任意
  attribution     任意（その面での帰属）
```

- **関係の主張だけを支える。** Theme の資格判定に一切寄与しない。
- 本文を複製しない。source 件数を数えない。独立性 score を持たない。qualification を計算しない。
- `CAUSES` は 1 件以上必須。`AMPLIFIES` / `MITIGATES` / `DEPENDS_ON` は HUMAN_ASSERTED なら
  rationale があれば 0 件でもよい。SOURCE_ASSERTED は型に依らず 1 件以上必須（帰属の保全のため）。

## 8. assertion 訂正 chain

```
A0（previous_assertion_id = ""）→ A1（previous = A0）→ A2（previous = A1）
```

**append 時の規律**（store）:

| 状況 | 結果 |
|---|---|
| 辺に履歴が無く `previous` が空 | 受理（genesis） |
| 辺に履歴があるのに `previous` が空 | `EDGE_ALREADY_STARTED` |
| `previous` が store に無い | `MISSING_PREDECESSOR` |
| `previous` が別の辺の record | `PREDECESSOR_WRONG_EDGE` |
| `previous` に既に後続がある | `NOT_TERMINAL_PREDECESSOR`（分岐 append を許さない） |
| `recorded_at` が predecessor より前 | `NON_MONOTONIC_RECORDED_AT` |

**読み込み時（既に書かれた履歴）の解決**:

| 構造 | status | 診断 |
|---|---|---|
| 一意な start と一意な terminal | `RESOLVED` | — |
| 同じ predecessor に複数の後続 | `UNRESOLVED` | `RELATION_FORK` |
| start が複数 | `UNRESOLVED` | `MULTIPLE_STARTS` |
| predecessor が同じ辺に無く、他の辺に在る | `INVALID_HISTORY` | `PREDECESSOR_WRONG_EDGE` |
| predecessor がどこにも無い | `INVALID_HISTORY` | `DANGLING_PREDECESSOR` |
| start が無い / 閉路 / 到達できない record | `INVALID_HISTORY` | `CYCLE` |
| `recorded_at` が chain に沿って減る | `INVALID_HISTORY` | `NON_MONOTONIC_RECORDED_AT` |

**latest wins は無い。** chain は predecessor graph だけで解く。`recorded_at` も物理順も勝者を決めない。

## 9. governance model

```
ThemeRelationGovernanceEvent
  schema_version / event_id / event_type / edge_key / subject_assertion_id
  previous_event_id / reason / provenance / recorded_at
```

- event 型は `RETRACTED` / `RESTORED` ちょうど。ACCEPT / REJECT / MERGE / SPLIT は存在しない。
- 対象は **1 つの辺の履歴**。`edge_key` と `subject_assertion_id` の両方を持ち、subject はその辺の
  assertion でなければならない（`INVALID_GOVERNANCE_TARGET`）。
- 列は **RETRACTED から始まり、RETRACTED と RESTORED が交互**（`INVALID_GOVERNANCE_SEQUENCE`）。
- `RETRACTED` は「履歴には残るが現在の graph では active でない」。`RESTORED` は「再び active」。
  **どちらも履歴を削除しない。** 撤回を assertion の改訂として表すことはできない。
- governance chain も predecessor graph だけで解き、fork / 複数 start は `UNRESOLVED`、
  dangling / 閉路 / 非単調は `INVALID_HISTORY`。物理順の勝者は無い。

## 10. store の規律

追記専用 / canonical 行のみ / 厳密な schema 検証 / 往復検証 / content id 照合 /
同 id ＋ byte 一致は冪等（`ALREADY_PRESENT`）/ 同 id ＋ byte 相違は `CONFLICT` /
破損は fail closed（読み飛ばさない・修復しない・migration しない）/ 明示 `data_root`（既定値なし）/
single writer（外部変更は byte 長で検知）/ `write → flush → fsync` / read-only open / 現在時刻を読まない /
network を使わない。

破損理由: `AUTHORITY_MISSING` / `INVALID_ENCODING` / `TRUNCATED_FINAL_LINE` / `BLANK_LINE` / `MALFORMED_JSON` /
`NOT_AN_OBJECT` / `INVALID_RECORD` / `UNSUPPORTED_SCHEMA_VERSION` / `NON_CANONICAL_LINE` / `WRONG_AUTHORITY` /
`PHYSICAL_DUPLICATE_IDENTICAL` / `PHYSICAL_DUPLICATE_CONFLICTING`。

API: `initialize` / `open(read_only=)` / `append_assertion` / `append_event` / `reload` / `counts` /
`canonical_lines` / `assertions` / `governance_events` / `get_assertion` / `edge_keys` / `verify_unchanged`。
Foundation の `append_*` 名前空間とは意図的に別名にしている。

## 11. point-in-time

```
resolve_relation_graph(assertions, governance_events, *, cutoff, endpoint_lookup) -> ThemeRelationResolution
```

純関数。filesystem / network / 現在時刻を使わない。

- `recorded_at <= T` の assertion / governance event だけを見る。超過は `FUTURE_RELATION` /
  `FUTURE_GOVERNANCE` として診断に残す。
- `evidence_time <= recorded_at` が model 段階で保証されるため、evidence が cutoff より後に知られることはない。
- **両端点の Theme root が T までに存在していなければならない**（B5-D6）。満たさない辺は graph に入らず、
  `ENDPOINT_NOT_AVAILABLE_AT_CUTOFF:<state>` として excluded に残る。
- **ThemeObservation の解決は要求しない。**
- 物理順の勝者を作らない。入力順を入れ替えても結果は同一。

store 経由の便宜 API `resolve_relations_at_data_root(data_root, *, cutoff, endpoint_lookup)` は、
破損を例外ではなく `STORE_CORRUPTION` / `INVALID_HISTORY` の status として返す。

## 12. 端点 contract

```
EndpointLookup = Callable[[root_id, cutoff], EndpointState]
```

`EndpointState`: `EXISTS_AT_CUTOFF` / `NOT_CREATED_YET` / `UNKNOWN_ROOT` / `SUPERSEDED` / `RETIRED`。

- `EXISTS_AT_CUTOFF` / `SUPERSEDED` / `RETIRED` は「その時点に存在した」。退役・後継ありでも
  **歴史的 graph node として残る**。
- Foundation の変更 API を露出しない。`themes.store` を import しない。
- 呼び出し側が read-only の端点証拠から lookup を組み立てる。`endpoint_lookup_from_roots(created_at_by_root,
  retired=, superseded=)` は helper であり、Foundation への結線ではない。
- 端点が `SUPERSEDED` / `RETIRED` のとき、辺に `ENDPOINT_SUPERSEDED:<SOURCE|TARGET>` /
  `ENDPOINT_RETIRED:<SOURCE|TARGET>` の **注記**を付す。端点そのものは書き換えない。

## 13. 解決 status

| status | 意味 |
|---|---|
| `RESOLVED` | 可視な辺が少なくとも 1 つあり、すべて構造的に解決できた |
| `NO_STATE` | 可視な辺が 1 つも無い（未解決も不正も無い） |
| `UNRESOLVED` | fork / 複数 start / 曖昧な governance がある |
| `INVALID_HISTORY` | 構造的に不可能な履歴がある |
| `STORE_CORRUPTION` | store が読めない（store 経由 API のみ） |

優先順位は `INVALID_HISTORY` > `UNRESOLVED` > `NO_STATE` / `RESOLVED`。これらを 1 つに潰さない。

辺ごとの **意味論的状態** `EdgeState` は `ACTIVE` / `RETRACTED` の 2 値で、resolver の失敗 status とは別物である。

## 14. graph view

`build_relation_graph_view(resolution) -> ThemeRelationGraphView`（派生。保存しない）。

| 操作 | 意味 |
|---|---|
| `outgoing(root_id)` | その root を source とする辺 |
| `incoming(root_id)` | その root を target とする辺（逆辺 record は無い。同じ record の逆引き） |
| `neighbors(root_id)` | 入出力の両方向。各件に `Direction.OUTGOING` / `INCOMING` と相手の root を明示 |
| `relations_between(a, b)` | 2 root の間の辺（両向き。各件の source / target で向きを判別） |
| `relations_by_type(type)` | 型で絞る |
| `roots()` | 現れる root（辞書順。重要度ではない） |

- 既定では `ACTIVE` な辺だけを返す。撤回された辺は `retracted` に保持し、`include_retracted=True` でのみ返す。
- **順位付け・score・確信度・中心性・PageRank・重要度・推奨を持たない。**
- **推移的に導出した辺を作らない。** `A CAUSES B` と `B CAUSES C` があっても `A CAUSES C` は現れない。
- 出力順は edge key の辞書順で決定論的。path 問い合わせは B5B に無い。

## 15. 閉路

MVP の 4 型はいずれも構造的階層ではないため、**閉路は妥当**である。

`A DEPENDS_ON B` ＋ `B DEPENDS_ON A`、`A CAUSES B` ＋ `B CAUSES A` はいずれも表現可能で、
`FEEDBACK_LOOP_PRESENT` の **記述的な診断**が付くだけである。閉路を理由に `INVALID_HISTORY` にしない。
`PARENT_OF` が MVP に無いため、階層閉路の検査は実装しない。

## 16. merge / split / 後継（B5-D7）

Theme A が C に merge されても、既存の `A → B` は **`A → B` のまま**である。

- `C → B` を作らない。
- `A → B` を改変しない。
- 関係を複製しない。
- split / 後継も同じ。

view は端点の状態を注記するだけで、端点 root id を書き換えない。移行が要るなら、それは新しい主張であり、
別の gate の対象である。

## 17. 自動 authority の不在（B5-D4）

B5B に `RelationProposal` は無い。したがって次のいずれからも relation assertion は生まれない。

taxonomy の重複、entity の重複、evidence の重複、Theme の共起、価格相関、rule の出力、LLM の出力。

assertion は **明示的な model 入力のみ**である。B3 は変更していない。

## 18. import 境界（§21）

| module | 役割 | 依存 |
|---|---|---|
| `relation_model.py` | record model / 語彙 / identity / canonical 直列化 | stdlib、`core.ids`、`core.time`、`themes.model`（read-only 型） |
| `relation_resolution.py` | chain 解決 / PIT / 端点 contract | stdlib、`relation_model` |
| `relation_graph.py` | 記述的 view | stdlib、`relation_model`、`relation_resolution` |
| `relation_store.py` | 追記専用 store ＋ store 経由の解決 | stdlib（`os` / `pathlib`）、`relation_model`、`relation_resolution` |

禁止: `themes.store` / `themes.operations` / `themes.revision` / `themes.resolver` / `proposal_store` /
`proposal_model` / discovery runtime / taxonomy / entity catalog / evidence bridge / P4 reports /
P5 predictions / network / LLM / 公開 module。

Foundation・B1・B2・B3・B4 のどの module も B5B を import しない（package 内外の双方を test で固定）。

## 19. 失敗語彙

**model**: `INVALID_TYPE` / `INVALID_VOCABULARY` / `UNSUPPORTED_SCHEMA_VERSION` / `UNKNOWN_THEME_ROOT` /
`SELF_RELATION` / `MISSING_FIELD` / `MISSING_SOURCE_ATTRIBUTION` / `ATTRIBUTION_FORBIDDEN` /
`MISSING_SOURCE_CITATION` / `MISSING_CAUSAL_EVIDENCE` / `DUPLICATE_EVIDENCE_REF` / `EVIDENCE_AFTER_RECORD` /
`FORBIDDEN_ASSERTION_AUTHORITY` / `INVALID_RECORD_ID` / `INVALID_EDGE_KEY` / `PROHIBITED_CONTENT` /
`FIELD_TOO_LONG` / `INVALID_TEXT` / `INVALID_TIME` / `UNKNOWN_FIELD` / `INVALID_CUTOFF`

**store**: 上記の破損理由 ＋ `EDGE_ALREADY_STARTED` / `MISSING_PREDECESSOR` / `PREDECESSOR_WRONG_EDGE` /
`NOT_TERMINAL_PREDECESSOR` / `NON_MONOTONIC_RECORDED_AT` / `UNKNOWN_EDGE` / `INVALID_GOVERNANCE_TARGET` /
`INVALID_GOVERNANCE_SEQUENCE` / `READ_ONLY` / `DATA_ROOT_REQUIRED` / `CONFLICT` / `CONCURRENT_MODIFICATION`

**resolution**: `FUTURE_RELATION` / `FUTURE_GOVERNANCE` / `ENDPOINT_NOT_AVAILABLE_AT_CUTOFF` /
`UNKNOWN_EDGE_GOVERNANCE` / `RELATION_FORK` / `MULTIPLE_STARTS` / `DANGLING_PREDECESSOR` /
`PREDECESSOR_WRONG_EDGE` / `CYCLE` / `NON_MONOTONIC_RECORDED_AT` / `INVALID_GOVERNANCE_TARGET` /
`INVALID_GOVERNANCE_SEQUENCE`

**注記（失敗ではない）**: `ENDPOINT_SUPERSEDED` / `ENDPOINT_RETIRED` / `FEEDBACK_LOOP_PRESENT`

## 20. 除外事項（B5B に無いもの）

RelationProposal、関係の discovery、辺の自動生成、LLM、rule による関係推論、順位付け、中心性、PageRank、
推奨、推移的に導出した辺、監視、runner / workflow、公開出力、Foundation の変更、B3 の変更、B4 の変更、
数値の強度 / 確信度、世界時間（`effective_from` / `effective_to`）、`PARENT_OF` / `RELATED_TO` /
`CONSTRAINS` / `ENABLES`。

## 21. test matrix（実装済み）

| 区分 | 範囲 | 件数 |
|---|---|---|
| MODEL | 語彙 4 型 / 未知型の拒否 / rationale / 帰属 / CAUSES の evidence（両 class）/ 自己辺 / content id の決定性 / audit 除外 / 意味変化で別 id / 辺 key | 12 項目 |
| CHAIN | genesis / 訂正 / predecessor 欠落 / 別辺の predecessor / 単調性 / append 分岐の拒否 / 読み込み fork / 複数 start / 物理順非依存 | 9 項目 |
| GOVERNANCE | event なし / 撤回 / 撤回→復帰 / fork / dangling / 物理順非依存 / 撤回は削除ではない / 対象辺の検査 | 8 項目 |
| STORE | initialize / read-only / 冪等 / 衝突 / 不正 JSON / 非 canonical / 未知 schema / 破損 7 種 / 外部変更 / 再読み込み / 修復しない | 11 項目 |
| PIT | cutoff 等号と超過（assertion / governance）/ 端点が未作成 / 未知 root / 退役 / 後継 / observation 不要 | 9 項目 |
| GRAPH | outgoing / incoming / neighbors の向き / between / by type / 逆向きの区別 / 閉路の妥当性 / 推移なし / 決定性 / 撤回辺の扱い | 10 項目 |
| BOUNDARY | 他 authority を触らない / proposal 無し / discovery 無し / 順位付け無し / network・LLM・時計無し / 公開非結合 / 機密 | 7 項目 |

合計 62 件（`test_theme_relation.py` 41 件、`test_theme_relation_store.py` 21 件）。
import 境界は `test_theme_intelligence_import_boundary.py` を additive に拡張して固定している。
