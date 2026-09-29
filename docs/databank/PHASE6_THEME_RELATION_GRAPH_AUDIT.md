# Phase 6 / P6-B5A — Theme relation graph 読み取り専用 architecture 監査

本書は **設計監査**であり実装ではない。runtime・test・knowledge・config・workflow は一切変更していない。
B4 は `10b44839d0aa33f83b6517552ab8a6b7ed06a3fa` で凍結済みで、本 gate では開かない。

---

## 1. 目的と非目的

**問い**: 永続的な Theme root どうしの間に、どんな関係を表現してよいか。誰がそれを主張してよいか。
どう version 管理するか。どう point-in-time で再構成するか。

**Relation Graph が表さないもの**（いずれも既存の別構造）:

| 別構造 | 既存の所在 | 問い |
|---|---|---|
| ThemeObservation の前後関係 | Foundation `previous_observation_id` | この Theme の状態はどう変わったか |
| Foundation revision chain | Foundation observation chain | 同上 |
| governance supersession | `ThemeGovernanceEvent` / `SUPERSEDED_BY_ROOT` | この root に何が起きたか |
| merge / split lineage | `LineageKind`（MERGED_INTO / MERGE_OF / SPLIT_INTO / SPLIT_FROM / SUPERSEDED_BY / SUCCESSOR_OF） | この root の identity 系譜はどうなっているか |
| evidence attachment | Foundation `EvidenceAttachment` | この Theme を何が支えるか |
| taxonomy 親子 | B4B `parent_slugs`（DAG） | この語彙はどの語彙の下位か |
| entity 関係 | B4B `attributes`（country / sector 参照） | この entity は何に属するか |
| proposal dedup | B3 `DedupReviewProposal` | この候補は既存と同一か |
| Theme → entity の推定 exposure | Foundation `InferredExposureLink` | この Theme はどの entity に触れるか |

Relation Graph が表すのはただ一つ: **Theme A は Theme B と意味論的にどう関係するか**。

## 2. 硬い architecture 境界

Foundation lineage graph と Theme Relation Graph は **素（disjoint）** である。

| | Foundation lineage | Relation Graph |
|---|---|---|
| 問い | この Theme / root / 履歴に何が起きたか | Theme A は Theme B とどう関係するか |
| 辺の意味 | identity 系譜 | 意味論的関係 |
| 生成者 | governance event から resolver が注釈として再構成 | 人間の主張、または出典の主張の記録 |
| authority | Foundation | 別 authority（§3） |

**relation 辺を次の判断に使ってはならない**: 現在の ThemeObservation、有効な Foundation revision、merge / split の結果、
governance 状態、Theme identity、evidence の資格、lifecycle 状態。
**Foundation の predecessor 辺を意味論的 relation として扱ってもならない。**

### 2.1 分離の強制方法（B5B 以降で実装する test）

1. **package 境界**: relation module は Foundation の read-only 面のみ import する。`themes.store` /
   `themes.operations` / `themes.revision` を import しない（既存 boundary test の方式を踏襲）。
2. **逆依存の禁止**: Foundation / B1 / B2 / B3 / B4 のどの module も relation module を import しない
   （既存の「Foundation は theme_intelligence を import しない」test と同型の検査を追加）。
3. **語彙の非混線**: relation の型名に `LineageKind` の値（MERGED_INTO 等）を使わない。source token 検査で固定する。
4. **出力の非混線**: relation view の plain 表現に `observation_id` / `previous_observation_id` / `event_id` を
   含めない（Foundation の record id を relation の意味に使わない）。
5. **store の分離**: relation authority は Foundation の `<data_root>/themes/` を読みも書きもしない。

## 3. relation authority の置き場所

| 案 | 内容 | 長所 | 短所 | 判定 |
|---|---|---|---|---|
| **A. 別の追記専用 authority** | `<data_root>/theme_intelligence/relations.jsonl`（＋ 関連 journal） | Foundation 不変。lineage と分離。撤回・訂正が履歴に残る。B3 と同じ規律を再利用できる | store が 1 つ増える | **推奨** |
| B. Foundation governance の拡張 | governance event 種別を増やす | authority が 1 つ | 語彙 version の変更 ＝ **Foundation の変更**（凍結 phase の再開）。identity 系譜と意味論関係が同じ journal で混線する | REJECT |
| C. repo の knowledge graph | `knowledge/theme_relations/*.yaml` を version 付きで置く | review しやすい。B4B と同じ loader 規律 | 辺ごとの evidence / 主張者 / 時刻 / 撤回履歴を持てない。関係の主張が「code review の成果物」になり、governance record にならない。Theme root id は data_root 側の値なので repo に固定できない | REJECT |
| D. derived のみ | identity core の共有（同一 driver / channel / domain / subject）を毎回再計算して提示 | authority 不要・決定論・即時 | AMPLIFIES / CAUSES のような意味論関係を表現できない | **A の補完として採用**（§15） |

**推奨: A（別の追記専用 relation authority）。** 理由:

1. Theme 間の意味論関係は **主張**であり、主張には主張者・根拠・時刻・撤回可能性が要る。これを持てるのは
   append-only の record authority だけである（C は持てない、D は主張を持たない）。
2. B は凍結済み Foundation の語彙 version 変更を要求する。B4 closeout で確認したとおり、Foundation は
   B4 の全経路を通しても byte 不変である。この性質を relation のために壊すのは対価が大きすぎる。
3. A なら Foundation lineage と relation は物理的に別 file になり、§2 の分離が「設計上の約束」ではなく
   **構造上の事実**になる。
4. D は A の入力（提案の材料）としては有用なので捨てない。ただし derived のまま保持し、authority にしない。

B1 architecture 監査の G-C（typed directed relation record／別 journal）と同じ結論であり、
G-D（derived 構造 relation）を前段として併用する点も一致する。

## 4. relation record の候補 model

### 4.1 二層に分ける（推奨）

Foundation の前例（semantic observation と governance event を分ける）に倣い、**主張** と **行為** を分ける。

**(1) `ThemeRelationAssertion`** — 不変の意味論的主張。

| field | 区分 | 備考 |
|---|---|---|
| `schema_version` | identity | |
| `relation_vocabulary_version` | identity | 型を増やすのは versioned な変更（§5） |
| `assertion_id` | 派生 | `threl_<24 hex>` の content id |
| `source_theme_root_id` | identity | `theme_<ULID>` |
| `target_theme_root_id` | identity | 同上。`source == target` は禁止（§9） |
| `relation_type` | identity | §5 の語彙 |
| `assertion_class` | identity | HUMAN_ASSERTED / SOURCE_ASSERTED のみ（§6） |
| `attributed_source_ref` | identity | SOURCE_ASSERTED のとき「誰が言ったか」。HUMAN は空 |
| `rationale` | identity | 正規化済みの短文。空不可 |
| `evidence_refs` | identity | 関係の根拠となる evidence 参照（§14）。Theme の資格 evidence ではない |
| `previous_assertion_id` | identity | 同じ辺の直前の主張（訂正 chain）。初回は空 |
| `provenance` | audit | actor_class / actor_ref |
| `recorded_at` | audit | 知識時間。世界時間ではない |

- **identity（content id の材料）**: 上表の identity 行。provenance と `recorded_at` は identity 外
  （B3 と同じ規律。同じ主張を別の人が同じ文面で記録しても同一 id になり、冪等に畳まれる）。
- **辺 key（derived）**: `(source_theme_root_id, target_theme_root_id, relation_type, assertion_class, attributed_source_ref)`。
  record id ではない。同じ辺 key を持つ assertion 群が 1 本の chain を成す。
  これが §9 の「relation identity と relation history の区別」の答えである。

**(2) `ThemeRelationGovernanceEvent`** — 主張ではない行為の不変 record。

| field | 備考 |
|---|---|
| `event_id` / `event_type` | RETRACTED / RESTORED |
| `subject_assertion_ids` | 対象の主張 |
| `previous_event_ids` | 対象ごとの直前 terminal event（Foundation と同型） |
| `reverses_event_id` | 取消（RESTORED が RETRACTED を reverse する） |
| `reason` / `actor_class` / `actor_ref` / `recorded_at` | |

### 4.2 単一 record の代替案

`supersedes_relation_id` ＋ record 内の `status`（ACTIVE / RETRACTED）だけで済ませる案もある。

| | 二層（推奨） | 単一 record |
|---|---|---|
| 訂正 | 新 assertion ＋ `previous_assertion_id` | 新 record ＋ `supersedes_relation_id` |
| 撤回 | governance event | `status=RETRACTED` の新 record（主張全体を書き直す） |
| 長所 | Foundation と同型。撤回が主張を複製しない。撤回の取消が自然に書ける | module が 1 つで済む |
| 短所 | record 型が 2 つ | 撤回のたびに主張本文が複製され、「何が主張か」と「何が起きたか」が混ざる |

監督者決定 **B5-D5** に付す。

### 4.3 世界時間（`effective_from` / `effective_to`）

MVP では **持たない**ことを推奨する。理由: 関係が世界のいつ成立したかは通常わからず、知識時間
（`recorded_at`）と世界時間の 2 軸は PIT の test matrix を倍にする。必要になった時点で versioned な拡張として
加える（B5-D6）。

## 5. relation 型の語彙

### 5.1 MVP 推奨

| type | 方向 | 意味 | MVP |
|---|---|---|---|
| `CAUSES` | A → B | A の機構が B の機構を生じさせる | **採用**（最高位の証明責任。§6） |
| `AMPLIFIES` | A → B | A が B の効果の大きさを増す | **採用** |
| `MITIGATES` | A → B | A が B の効果の大きさを減じる | **採用**（AMPLIFIES の符号違い。別型にして符号 field を作らない） |
| `DEPENDS_ON` | A → B | A の成立が B の成立を前提とする | **採用** |
| `CONSTRAINS` | A → B | A が B の実現可能性を狭める | 第 2 段（繰延） |
| `ENABLES` | A → B | A が B の実現可能性を広げる | 第 2 段（繰延） |
| `RELATED_TO` | — | 「何か関係がある」 | **不採用**（下記 5.2） |
| `PARENT_OF` | parent → child | Theme 階層 | **MVP 外**（下記 5.3） |

型を増やすことは `relation_vocabulary_version` の変更であり、B4B knowledge と同じく **versioned な変更**として扱う。
黙って型が増えることはない。

### 5.2 `RELATED_TO` を authority にしない理由

- 意味が無い。方向も符号も根拠も持たないので、反証も撤回も意味を成さない。
- 歴史資産の無向隣接がまさにこの形であり（§20）、co-occurrence を関係に見せる経路そのものである。
- 「関係がありそう」は **提案の材料**であって authority ではない。構造的類似（同一 driver / channel / domain /
  subject）は §15 のとおり derived のまま提示すればよく、record にする必要が無い。
- 語彙に存在させないことが、`RELATED_TO` 爆発に対する最も強い構造的防御になる。

### 5.3 `PARENT_OF` を MVP 外にする理由

Theme 階層は relation とは別の設計問題である。階層は identity・集約・taxonomy との重複・循環禁止を同時に持ち込み、
「親 Theme の evidence は子の evidence か」という Foundation 側の問いを誘発する。MVP の 4 型はいずれも
集約意味論を持たないため、この問いを回避できる。階層が要るなら独立した gate で扱う（B5-D2）。

## 6. 因果安全性（最重要）

### 6.1 assertion class

| class | relation authority に置けるか | 備考 |
|---|---|---|
| `HUMAN_ASSERTED` | **可** | 人間が自分の名前で主張する |
| `SOURCE_ASSERTED` | **可** | 「出典 X が『A が B を生じさせる』と述べた」という **帰属付きの記録**。系が因果を主張しているのではない |
| `RULE_PROPOSED` | **不可**（提案のみ） | relation proposal authority にのみ存在しうる |
| `LLM_PROPOSED` | **不可**（提案のみ） | 同上 |

境界は次の一行に尽きる。

> **出典が「A が B を生じさせる」と述べた** ことの記録は可。
> **系が「A が B を生じさせる」と推論した** ものは、人間が自分の名前で引き受けない限り authority にならない。

SOURCE_ASSERTED の record は「因果が真である」とは主張しない。query view は必ず帰属を伴って提示し、
帰属を落とした平坦な辺として見せてはならない（`FORBIDDEN_CAUSAL_AUTHORITY` の対になる view 側の規律）。

### 6.2 `CAUSES` を作ってはいけない根拠

次はいずれも **単独でも組み合わせでも** `CAUSES` の根拠にならない。

Theme の共起、evidence の重複、entity の重複、taxonomy の重複、リターンの相関、discovery rule の同時発火、
authority を伴わない LLM の「関係がある」という出力、過去の無向グラフの隣接、keyword trigger 表。

これらは **提案の材料**にしかなりえず、提案は辺ではない（§7）。

## 7. proposal と authority

| 案 | 内容 | 判定 |
|---|---|---|
| A. B3 の `ProposalType` を拡張 | RELATION_PROPOSAL を B3 に足す | **REJECT**。B3 は凍結。proposal id の接頭辞・検証・decision の許可表がすべて Theme / Evidence 意味論に結線されている |
| B. 別の `RelationProposal` ＋ 別の relation decision | B5 の authority 内に、B3 と**同じ規律**で独立に持つ | **推奨** |
| C. relation record に `PROPOSED` status を持たせる | 1 つの journal に提案と authority が同居 | **REJECT**。§7 の要件「提案がそれ自体で authoritative な辺になってはならない」を、1 回の query ミスで破れる |

推奨経路:

```
Theme state / change set / lifecycle view / 出典の因果文
  → RelationProposal（RULE_PROPOSED / LLM_PROPOSED / HUMAN 起案）
    → 人間の decision（ACCEPT / REJECT / DEFER）
      → ThemeRelationAssertion（HUMAN_ASSERTED または SOURCE_ASSERTED）
```

**提案は辺ではない。** 提案 journal と assertion journal は別 file にし、graph view は assertion journal しか読まない。

コスト: B3 の decision chain 解決（`supersedes` graph・fork 検出・dangling 検出）と同じ論理を B5 に書き直すことになる。
B3 を触らない対価として受け入れる。将来 B3 を開ける gate があれば、chain resolver を汎用化して共有するのは OPTIONAL。

## 8. 方向性

MVP の 4 型はすべて **有向**であり、主張された方向のみを record する。

- 逆辺は **derived**。`incoming(root_id)` は同じ record 集合を逆引きするだけで、record を複製しない。
- 走査の都合で逆辺を保存しない（同じ主張が 2 行になると、撤回・訂正が 2 箇所必要になる）。
- 対称型は MVP に無い。将来対称型を入れる場合は、2 record ではなく **端点を正規順に並べた 1 record** で表す。
- `A CAUSES B` と `B CAUSES A` はどちらも独立の主張であり、片方から他方を導かない。

## 9. 自己辺・重複辺

- **自己辺**: `source == target` は全型で禁止（`SELF_RELATION`）。意味論的関係は 2 つの Theme の間にしか無い。
- **重複の扱い**:

| 状況 | 扱い |
|---|---|
| 同一 record id ＋ byte 一致 | 冪等（`ALREADY_PRESENT`）。append しない |
| 同一 record id ＋ byte 相違 | `CONFLICT`（fail closed。B3 と同じ） |
| 同一辺 key ＋ 内容相違 ＋ `previous_assertion_id` あり | 訂正。同じ chain の次の主張 |
| 同一辺 key ＋ 内容相違 ＋ `previous_assertion_id` 空が 2 本 | `RELATION_FORK`。当該辺は **UNRESOLVED**。物理順で勝者を選ばない |

relation identity（辺 key）は「どの主張の系列か」を決め、relation history（chain ＋ governance）は
「その系列に何が起きたか」を決める。両者を混同しない。

## 10. 訂正・撤回

不変。in-place 変更は無い。

```
ASSERTED ──(訂正: 新 assertion ＋ previous_assertion_id)──> ASSERTED'
   │
   └──(RETRACTED: governance event)──> RETRACTED ──(RESTORED: reverses)──> ACTIVE
```

- 「latest wins」は作らない。chain の解決は `previous_assertion_id` の graph のみで行い、`recorded_at` や
  物理順では決めない（B3 decision chain と同じ）。
- chain に terminal が 2 つある / start が 2 つある → `RELATION_FORK` → UNRESOLVED。
- predecessor が存在しない → `DANGLING_RELATION_HISTORY` → INVALID_HISTORY。
- 撤回された辺は graph view の既定集合から外れるが、履歴としては残り、PIT で撤回前の cutoff では見える。

## 11. point-in-time

```
resolve_relation_graph(history, cutoff) -> ThemeRelationGraphView
resolve_relation(history, edge_key, cutoff) -> ThemeRelationResolution
```

要件:

1. `recorded_at <= T` の record だけを使う。将来の record は `FUTURE_RELATION` として除外する。
2. 将来の訂正・将来の evidence・将来の Theme root を見ない。
3. 未解決の relation 履歴は **未解決のまま可視**（握り潰さない）。
4. 物理順の勝者を作らない。
5. **両端点の Theme root が T に存在すること**（`root.created_at <= T`）。片方でも無ければその辺は graph に
   入らず、`ENDPOINT_NOT_AVAILABLE_AT_CUTOFF` として診断に残る（黙って落とさない）。

### 11.1 端点にどこまで要求するか

| 端点の状態 | 辺の扱い | 理由 |
|---|---|---|
| root が T より後に作られた | 辺は不可視 ＋ 診断 | 存在しない node への辺は関係ではない |
| root は存在するが観測状態が NO_STATE | **辺は可視**。端点の resolution status を view が併記 | 資格や観測状態を relation の条件にすると §12 の分離が崩れる |
| root が RETIRED | **辺は可視**（§12） | 退役は node の削除ではない |
| root が MERGED / SPLIT された | **辺は端点そのままで可視** ＋ `ENDPOINT_SUPERSEDED` 注記 | 端点の書き換えは §13 で禁止 |
| Theme 側が INVALID_HISTORY / STORE_CORRUPTION | 辺は不可視 ＋ 診断 | 端点の存在自体が確定できない |

要求するのは **root の存在**までで、**観測状態の解決**までは要求しない。これが Theme resolution PIT との
正しい結合点である。

## 12. Theme lifecycle との関係

relation の存在は、次のいずれも **自動的に**引き起こさない。

Theme の活性化、Theme の退役、evidence の資格付与、lifecycle 状態の変更、discovery 状態の変更。

退役した Theme は graph の node として **歴史的に参照可能なまま**残る。退役は「その後に新しい関係を主張しない」
という運用上の帰結を持つだけで、既存の辺を消さない。

強制は import 境界で行う: lifecycle / change / discovery の各 module は relation module を import しない。

## 13. merge / split / 後継

**最重要の禁止事項。**

- Theme A が Theme C に merge されても、既存の `A → B` は **黙って `C → B` にならない**。
- Theme A が C と D に split しても、既存の辺は **自動的に C と D へ複製されない**。
- Foundation lineage が歴史的真実であり続ける。relation 側は端点を書き換えない。

移行が必要なら、それは **新しい主張**である。`C → B` を作りたければ、新しい assertion を人間が起こし、
その rationale で lineage event を参照する。一括移行を自動化する場合でも、辺ごとの人間 review を伴う
独立した gate が要る（B5-D7）。

view は `ENDPOINT_SUPERSEDED`（端点に lineage 後継が存在する）を **注記**してよいが、辺を書き換えてはならない。

## 14. evidence の要求

| assertion class × type | rationale | evidence refs |
|---|---|---|
| SOURCE_ASSERTED × 全型 | 出典の主張の要約（必須） | **必須**（1 件以上。その主張を載せた source document / news item） ＋ `attributed_source_ref` |
| HUMAN_ASSERTED × `CAUSES` | 必須 | **必須**（1 件以上） |
| HUMAN_ASSERTED × `AMPLIFIES` / `MITIGATES` / `DEPENDS_ON` | 必須 | 任意（evidence に基づく主張なら必須） |

欠落時の code: `MISSING_CAUSAL_EVIDENCE`（CAUSES）/ `MISSING_SOURCE_CITATION`（SOURCE_ASSERTED）。

**relation evidence は Theme の資格 evidence ではない。**

- relation の evidence refs は、どの ThemeObservation にも attach されない。
- Foundation の qualification に一切寄与しない。
- source の件数を数えない。独立 source 数を主張しない。強度にも score にもしない（§19）。

## 15. taxonomy / entity との関係

同一 taxonomy・同一 entity・同一 sector・同一 source は、**提案の hint にしかならない**。

| hint kind | 由来 | 出力 |
|---|---|---|
| `SHARED_TAXONOMY` | 両 Theme の taxonomy metadata が重なる | RelationProposal の材料 |
| `SHARED_ENTITY` | subject / domain の typed_reference が重なる | 同上 |
| `SHARED_MECHANISM_COMPONENT` | identity core の driver / channel / domain が一致（B1 監査の G-D） | 同上 |
| `SAME_SUBJECT` | subject の normalized 値が一致 | 同上（dedup 提案とも共用） |

これらは **derived で毎回再計算**し、record にしない。authority にしない。`RELATED_TO` が語彙に無いため、
hint がそのまま辺になる経路は構造的に存在しない。

## 16. discovery との関係

B4 discovery は凍結のまま。本 gate では relation 生成を B4 に足さない。

将来の relation discovery は **B5 の別 sublayer**（仮に B5C）として設計する。

| 許容しうる将来入力 | 禁止される因果入力 |
|---|---|
| `ThemeResolution` | P5 calibration |
| `ThemeChangeSet`（B1） | 価格相関のみ |
| lifecycle view（B2） | MorningBrief |
| taxonomy / entity 正規化（B4B） | MarketSignal |
| 出典の明示的な因果文（SOURCE_ASSERTED の材料） | CompassDraft |
| | 物語的散文 |
| | 過去の theme score |

## 17. graph query 面

純粋な read model `ThemeRelationGraphView` を想定する。

| 操作 | 意味 |
|---|---|
| `resolve_at(cutoff)` | その cutoff の graph を構成する |
| `neighbors(root_id)` | 入出力の両方向の隣接 |
| `outgoing(root_id)` / `incoming(root_id)` | 有向。`incoming` は derived（逆 record は無い） |
| `relations_between(a, b)` | 2 node 間の全辺（型別・assertion class 別） |
| `relations_by_type(type)` | 型で絞る |

**持たないもの**: ranking、centrality、PageRank、recommendation score、「最も重要な Theme」、
任意深さの推移閉包、**推移的に導出した辺**。

特に `A CAUSES B` ＋ `B CAUSES C` から `A CAUSES C` を導いてはならない。因果は推移的とは限らず、
導出した辺は誰の主張でもない。多段の経路を見せる場合は「経路」として見せ、辺として見せない。

走査は記述的であり、順位付けではない。

## 18. 循環の意味論

| 循環 | 判定 | 理由 |
|---|---|---|
| `A DEPENDS_ON B` ＋ `B DEPENDS_ON A` | **表現可能**（`MUTUAL_DEPENDENCY` を注記） | 相互依存は経済的に実在する |
| `A CAUSES B` ＋ `B CAUSES A`（および多段の閉路） | **表現可能**（`CAUSAL_CYCLE` を注記） | 因果フィードバック（再帰性）は実在する。自動で壊れていると判定しない |
| `A AMPLIFIES B` ＋ `B AMPLIFIES A` | 表現可能 | 増幅ループは実在する |
| `A PARENT_OF B` ＋ `B PARENT_OF A` | **無効** | 構造的階層は非循環でなければならない |

MVP の 4 型はいずれも構造的階層ではないため、**MVP に無効な循環は存在しない**。`RELATION_CYCLE_INVALID` は
階層型（`PARENT_OF`）を導入したときに初めて必要になる。これは `PARENT_OF` を MVP から外す判断の副次的な利点である。

注記は診断であって検証失敗ではない。graph の破損と意味論的な循環を混同しない。

## 19. 確信度・強度

**MVP に数値を導入しない。** score / probability / weight / rank / confidence percentage のいずれも持たない。

判断に使えるのは次の categorical 情報だけで十分である。

- `assertion_class`（誰の権威か）
- `attributed_source_ref`（出典の帰属）
- evidence refs の有無
- 撤回されているか
- `relation_type`（型そのものが符号を持つ。AMPLIFIES / MITIGATES）

将来「強度」が必要になった場合でも、計算された score ではなく **人間が付ける順序尺度**として、versioned な
語彙拡張で加える。明示的に繰延（B5-D2 の一部）。

## 20. 歴史資産の監査（読み取り専用）

現 branch に graph 資産は存在しない（`theme_graph.yaml` は現 tree に無い）。以下は既存の凍結済み監査 doc
（B0 / B1 / B4A）に記録された歴史資産の事実に基づく分類である。歴史 branch からの port / merge / cherry-pick は
行っていない。

| 資産 | 事実 | 従来の分類 | **B5A の分類** | 根拠 |
|---|---|---|---|---|
| `knowledge/theme_relations/theme_graph.yaml` | 37 key・114 edge。無向と宣言しつつ非対称 30 件。型・方向・符号・重み・evidence・時刻・provenance なし。定義外 node 8 | B0: B（P6-D seed）／B1: REDESIGN（seed 参照）／B4A: REFERENCE_ONLY | **REFERENCE_ONLY**（辺は port しない。seed にもしない） | 辺の意味が定義されていないため、どの MVP 型にも写像できない。`RELATED_TO` を語彙から外した以上、受け皿も無い。node 語彙は既に B4B の taxonomy ＋ entity catalog が置き換えている |
| 歴史の graph / model code（無向・無型） | 同上の構造を前提 | B1: REJECT | **REJECT** | 方向・型・証拠・時刻・provenance を持たない実装は再設計の役に立たない |
| `knowledge/causal_rules/{market,fx,rates}.yaml` | 見出し trigger → 恩恵 / 逆風 sector | B0: C REFERENCE ONLY | **REJECT**（relation の入力として） | keyword trigger は因果 authority ではない。§6 が禁じる生成経路そのもの。同内容は別目的で現 `config.yaml` に既に存在する |
| 歴史 `themes/__init__.py` の placeholder 文 | 「テーマグラフ…Emerging 検出」 | B0: D | **REJECT** | 現行の層構造と食い違う |

B0 / B1 の「seed として使う」方針からの **変更点**: `theme_graph.yaml` の辺を relation 提案の seed にしない。
理由は §5.2（`RELATED_TO` 不採用）と §6（共起から因果への経路の遮断）に尽きる。監督者決定 **B5-D10** に付す。

機密の観点: 歴史の graph / causal_rules 由来の散文は一切引用していない。本書は node 名も edge も列挙していない。

## 21. package 境界

想定位置は `src/intelligence/theme_intelligence/`（新 package を作らない）。

| module（将来） | 役割 |
|---|---|
| `relation_model.py` | assertion / governance event / 語彙 / 検証 |
| `relation_store.py` | 追記専用 journal（2 つ目の IO module） |
| `relation_resolution.py` | chain 解決と PIT |
| `relation_graph.py` | 純粋な read view |
| `relation_proposal.py` | proposal ＋ decision（§7 の B 案） |

**本 gate では作成しない。**

制約:

- Foundation はこれらを import しない。
- B1 / B2 / B3 / B4 はこれらに依存しない。
- B5 は Foundation の resolution、B1 の change set、B2 の lifecycle view、B4B の knowledge を
  **明示的に authorize された範囲で読んでよい**。
- 既存の import boundary test は package の module 一覧を完全一致で固定しているため、B5B では
  `MODULES` / `ALLOWED_RELATIVE` / `ALLOWED_CLOSURE` / `IO_MODULES` の additive な拡張が必要になる。

## 22. 永続化規律

別 authority を採る場合、最低限 P5 / B3 と同じ規律を満たす。

| 規律 | 内容 |
|---|---|
| 追記専用 | 既存行を書き換えない・削除しない |
| canonical 直列化 | 行は canonical JSON。非 canonical 行は破損 |
| content identity | `threl_<24 hex>` を内容から計算する |
| 厳密な冪等 | 同 id ＋ byte 一致は `ALREADY_PRESENT` |
| 同 id ＋ byte 相違 | `CONFLICT` で fail closed |
| 破損は fail closed | 読み飛ばさない・修復しない |
| single writer | 外部変更は byte 長で検知 |
| 修復しない / 黙って migration しない | |
| 明示 data_root | 既定値を持たない |
| derived index は再構築可能 | index を authority にしない |
| SQLite authority なし | |

配置は `<data_root>/theme_intelligence/` の既存 directory に同居させる（B3 の proposal authority と同じ場所）。
ただし store object は **B3 の `ProposalStore` を拡張せず別実装**とする（B3 は凍結）。

## 23. 公開境界

B5 は **内部専用**である。

GitHub Pages・`/v2`・root UI・Morning Brief・顧客向け出力・通知のいずれにも relation graph を出さない。
将来 P7 が構造化 graph view を消費する場合でも、独立した gate を経た後に限る。

B5B では、`.github` / `scripts` / `config.yaml` / `docs/v2` が relation module を参照しないことを
guard test で固定する（B4 で `theme_intelligence` に対して行ったのと同型）。

## 24. 失敗 / 状態語彙（将来の実装用。本 gate では実装しない）

| code | 層 | 意味 |
|---|---|---|
| `UNKNOWN_THEME_ROOT` | model | 端点が root id の形式でない／履歴に存在しない |
| `SELF_RELATION` | model | `source == target` |
| `INVALID_RELATION_TYPE` | model | 語彙 version に無い型 |
| `INVALID_DIRECTION` | model | 対称型に方向を与えた等 |
| `FORBIDDEN_CAUSAL_AUTHORITY` | model | RULE / LLM が authority 記録を作ろうとした |
| `MISSING_CAUSAL_EVIDENCE` | model | CAUSES に evidence ref が無い |
| `MISSING_SOURCE_CITATION` | model | SOURCE_ASSERTED に帰属 / 出典が無い |
| `DANGLING_RELATION_HISTORY` | resolution | predecessor が存在しない |
| `RELATION_FORK` | resolution | 同一辺 key に start / terminal が複数 |
| `RELATION_CYCLE_INVALID` | resolution | 階層型を導入した場合の循環（MVP では発生しない） |
| `FUTURE_RELATION` | resolution | `recorded_at > cutoff` |
| `ENDPOINT_NOT_AVAILABLE_AT_CUTOFF` | resolution | 端点 root が cutoff に存在しない |
| `ENDPOINT_SUPERSEDED` | view 注記 | 端点に lineage 後継がある（書き換えない） |
| `MUTUAL_DEPENDENCY` / `CAUSAL_CYCLE` | view 注記 | 表現可能な循環 |
| `STORE_CORRUPTION` | store | 非 canonical / 切断 / 重複衝突 |
| `INVALID_HISTORY` | resolution | 構造的に不可能な履歴 |
| `UNRESOLVED` | resolution | fork 等で確定できない |

## 25. 将来の test matrix

| # | 対象 |
|---|---|
| 1〜4 | MVP 4 型それぞれの成立 |
| 5 | 有向意味論（`A → B` ≠ `B → A`） |
| 6 | 逆辺は derived（record が複製されない） |
| 7 | 自己辺の拒否 |
| 8 | 完全重複の冪等 |
| 9 | 同 id ＋ byte 相違の `CONFLICT` |
| 10 | 訂正 chain の解決 |
| 11 | fork の `UNRESOLVED` |
| 12 | dangling predecessor の `INVALID_HISTORY` |
| 13 | 物理順非依存（行順を入れ替えても同一結果） |
| 14 | PIT cutoff（`recorded_at` 等号は可、超過は除外） |
| 15 | 将来 root の端点 → 辺不可視 ＋ 診断 |
| 16 | 退役 root の端点 → 辺は可視 |
| 17 | merge / split で端点が自動移行しない |
| 18 | SOURCE_ASSERTED の出典 / 帰属必須 |
| 19 | HUMAN_ASSERTED の rationale 必須、CAUSES は evidence 必須 |
| 20 | RULE / LLM は authoritative な CAUSES を作れない |
| 21 | 共起だけでは辺を作れない |
| 22 | taxonomy 重複だけでは辺を作れない |
| 23 | entity 重複だけでは辺を作れない |
| 24 | 因果フィードバック閉路が表現可能で注記される |
| 25 | 階層型を入れた場合の循環拒否（MVP では skip） |
| 26 | 決定論的直列化（canonical bytes） |
| 27 | 破損の fail closed |
| 28 | Foundation authority の byte 不変 |
| 29 | P4 / P5 / 公開出力との非結合 |
| 30 | 提案が graph view に現れない |
| 31 | 推移的に導出した辺が存在しない |
| 32 | 撤回済みの辺が既定集合から外れ、撤回前 cutoff では見える |

## 26. 監督者決定事項（10 件）

| id | 論点 | 推奨 | 代替 | tradeoff | Foundation / B3 / B4 の変更 |
|---|---|---|---|---|---|
| **B5-D1** | relation authority の置き場所 | **A**: `<data_root>/theme_intelligence/relations.jsonl`（＋ governance / proposal journal）の別 append-only authority | B: Foundation governance 拡張／C: repo knowledge／D: derived のみ | A は store が 1 つ増えるが Foundation を触らずに済み、lineage との分離が構造的事実になる | **不要** |
| **B5-D2** | MVP の relation 語彙 | **CAUSES / AMPLIFIES / MITIGATES / DEPENDS_ON の 4 型**。`CONSTRAINS` / `ENABLES` は第 2 段へ繰延。`PARENT_OF` は MVP 外。`RELATED_TO` は不採用。型追加は `relation_vocabulary_version` の変更 | 6 型で開始／`RELATED_TO` を含める／`PARENT_OF` を含める | 4 型なら無効循環が存在せず、階層の集約意味論も回避できる。将来の型追加は versioned な変更で安全に行える | 不要 |
| **B5-D3** | 因果 authority の規則 | **HUMAN_ASSERTED と SOURCE_ASSERTED のみが authority。RULE / LLM は提案止まり。SOURCE_ASSERTED は帰属付きの記録であり系の主張ではない。CAUSES は evidence ref 必須** | RULE に限定的な authority を与える | 厳格側に倒すと辺の増えは遅いが、共起 → 因果の経路が構造的に塞がる | 不要 |
| **B5-D4** | proposal の architecture | **B**: B5 内に独立した `RelationProposal` ＋ relation decision を持ち、B3 の *規律* だけを踏襲する | A: B3 の ProposalType 拡張／C: relation record に PROPOSED status | B は chain 解決論理の重複を招くが、B3 凍結を守り、提案が辺になる経路を物理的に断つ | **不要**（A を選ぶ場合のみ B3 変更が必要） |
| **B5-D5** | 訂正 / 撤回の model | **二層**: assertion chain（`previous_assertion_id`）＋ relation governance event（RETRACTED / RESTORED） | 単一 record ＋ `supersedes_relation_id` ＋ status | 二層は record 型が増えるが、Foundation と同型で、撤回が主張本文を複製しない | 不要 |
| **B5-D6** | PIT の端点意味論と時間軸 | **両端点の root が cutoff に存在することを要求する。観測状態の解決までは要求しない。MVP は知識時間（`recorded_at`）のみ。世界時間（`effective_from` / `effective_to`）は繰延** | 端点に RESOLVED を要求／世界時間を MVP に含める | RESOLVED を要求すると資格・観測と結合してしまう。世界時間は PIT の test matrix を倍にする | 不要 |
| **B5-D7** | merge / split の移行方針 | **自動移行なし。端点を書き換えない。view は `ENDPOINT_SUPERSEDED` を注記するのみ。移行は辺ごとの人間 review を伴う独立 gate** | 後継へ自動で付け替える／一括移行 tool を用意する | 自動移行は Foundation lineage の歴史的真実と relation の主張責任を両方壊す | 不要 |
| **B5-D8** | relation の evidence 要求 | **SOURCE_ASSERTED は出典 ＋ 帰属必須。HUMAN_ASSERTED は rationale 必須で、CAUSES は evidence ref も必須。relation evidence は Theme の資格 evidence に寄与しない。source 件数を数えない** | 全型で evidence 必須／全型で任意 | 型ごとに段差を付けることで、最も危険な CAUSES にだけ最高の証明責任を置ける | 不要 |
| **B5-D9** | graph query の範囲 | **記述的な読み取りのみ**（`resolve_at` / `neighbors` / `outgoing` / `incoming` / `relations_between` / `relations_by_type`）。ranking・centrality・推奨・推移的導出辺を持たない | centrality を初期から入れる／推移閉包を提供する | 順位付けを持たないことで、graph が「重要度の主張」に化けるのを防げる | 不要 |
| **B5-D10** | 歴史資産の port 範囲 | **`theme_graph.yaml` は REFERENCE_ONLY。辺を port せず、relation 提案の seed にもしない。`causal_rules` は relation 入力として REJECT** | B0 / B1 の「seed 参照」を維持し、辺を `RELATED_TO` 提案の種にする | seed を捨てると初期の辺が人手起こしになるが、`RELATED_TO` 不採用と整合し、共起 → 因果の経路を残さない | 不要 |

10 件いずれも Foundation / B3 / B4 の変更を必要としない（B5-D4 の代替案 A を選んだ場合のみ B3 変更が必要）。

## 27. 本 gate の成果物

| path | 種別 |
|---|---|
| `docs/databank/PHASE6_THEME_RELATION_GRAPH_AUDIT.md` | 新規（本書） |
| `CHANGELOG.md` | 追記のみ |

src / tests / knowledge / config / workflow / data / docs/v2 / 公開出力はいずれも変更していない。
