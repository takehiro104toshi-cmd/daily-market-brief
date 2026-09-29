# Phase 6 — Theme Change Detection Contract（P6-B1）

状態: **実装済み**（`src/intelligence/theme_intelligence/model.py` / `change.py`、`theme_change_set:0.1.0` /
`theme_change_model:0.1.0`）。Foundation（`src/intelligence/themes/`、anchor `12847bf`）は無変更。
上位決定: P6-B0 監査（`PHASE6_THEME_INTELLIGENCE_ARCHITECTURE_AUDIT.md`）と監督者決定 D-B1〜D-B8。

## 1. 目的と authority 境界

- 問い: 「root_id について、T1 に Theme subsystem が正当に知り得た状態と、T2 に知り得た状態の間で **何が変わったか**」。
- 入力は Foundation resolver の `ThemeResolution` 2 つ（before ＝ T1、after ＝ T2）。出力は `ThemeChangeSet`。
- **ChangeSet は authority ではない。** canonical 5 authority を読むだけで書かない。journal に保存せず content id も持たない。
  同じ入力から常に再計算できる derived 値である。
- Foundation resolver / store の意味論を再実装しない。eligibility・chain 解決・facet 独立・PENDING・carried・DERIVED・
  dereference はすべて resolver の結果をそのまま比較する。
- B1 は prediction / scoring / lifecycle / recommendation / narrative / discovery ではない。ChangeSet に score・順位・
  重み・方向・強弱・昇格は存在しない。
- 依存方向: `theme_intelligence` → `themes`（model / qualification / resolver の pure・read-only surface のみ）。
  Foundation は `theme_intelligence` を import しない（test で固定）。production runtime closure に含まれない。

## 2. 語彙（`ChangeKind`）

| kind | 意味 | facet |
|---|---|---|
| ROOT_APPEARED | T1 に RootRecord が無く（未知 / 未作成）T2 にある | root |
| ROOT_BECAME_OBSERVED | T1 に eligible observation が無く（NO_STATE）T2 にある（RESOLVED または UNRESOLVED） | root |
| OBSERVATION_REVISED | resolved observation の id が変わった（related ＝ 旧 id、before / after ＝ recorded_at） | observation |
| SEMANTIC_FIELD_CHANGED | subject / mechanism.drivers / .channels / .domains / .consequences / certainty_class / scope / limitations / invalidation_conditions / inferred_links の canonical 値が変わった（subject_id ＝ field 名） | observation |
| EVIDENCE_ADDED | T2 の visible evidence に新しい attachment_key | evidence |
| EVIDENCE_CARRIED | 結果 root 側で、origin event の配分により carry された既存 evidence が T2 に visible（EVIDENCE_ADDED とも LINEAGE_CHANGED とも区別） | evidence |
| EVIDENCE_DROPPED | T1 の visible evidence が T2 の current observation に無い（detail ＝ `dropped_attachments` の理由） | evidence |
| EVIDENCE_ROLE_CHANGED | 決定論的に対応づく同一 evidence の role が変わった（§4） | evidence |
| EVIDENCE_REF_REVISED | 上流 revision への付け替え（`revision_of_at_attachment` が旧 ref_id を指す 1:1 対応） | evidence |
| EVIDENCE_ATTRIBUTE_CHANGED | 同一 key・同一 role で他 field（provenance / QA snapshot / note 等）が変わった | evidence |
| NEW_SOURCE_ORIGIN / SOURCE_ORIGIN_LOST | counted independent origin group 数が増えた / 減った | derived |
| NEW_EVIDENCE_DATE / EVIDENCE_DATE_LOST | counted evidence date 集合に日付が加わった / 消えた（subject_id ＝ 日付） | derived |
| QUALIFICATION_CHANGED | A2 §19 の判定（DOES_NOT_QUALIFY / THEME_CANDIDATE_POSSIBLE / QUALIFIES_SEMANTICALLY）が変わった。両方向。昇格ではない | derived |
| CONTRADICTION_APPEARED / CONTRADICTION_CLEARED | `has_contradicting_evidence` false → true / true → false | derived |
| INVALIDATION_APPEARED / INVALIDATION_CLEARED | `has_invalidating_evidence` false → true / true → false | derived |
| GOVERNANCE_CHANGED | effective event / terminal event / reversal 集合のいずれかが変わった（detail に何が変わったか） | governance |
| METADATA_CHANGED | (record_id, value) が変わった。facet ＝ `metadata:<LABEL / DESCRIPTION / TAXONOMY / ALIAS>` | metadata |
| MAPPING_CHANGED | terminal mapping id 集合が変わった（related ＝ 追加 id、detail ＝ superseded id） | mapping |
| LINEAGE_CHANGED | lineage 注釈（MERGED_INTO / MERGE_OF / SPLIT_* / SUPERSEDED_BY / SUCCESSOR_OF）が加わった | lineage |
| PENDING_APPEARED / PENDING_CLEARED | (kind, subject, missing) の PENDING 診断が現れた / 消えた | pending |
| SEMANTIC_BECAME_UNRESOLVED / SEMANTIC_BECAME_RESOLVED | semantic facet の UNRESOLVED 出入り | observation |
| FACET_BECAME_UNRESOLVED / FACET_BECAME_RESOLVED | governance / metadata:<FIELD> / mapping facet の UNRESOLVED 出入り | 当該 facet |
| DEREFERENCE_CHANGED | 上流 dereference 状態の変化（canonical の変化ではない） | dereference |

禁止語（語彙にも source にも無い。test で固定）: EMERGING / ACCELERATING / MATURE / WEAKENING / STRONG / WEAK / BULLISH /
BEARISH / WINNING / LOSING / DORMANT / ESTABLISHED / PROMOTED / score / rank / weight / confidence。

## 3. 二つの時間軸

| 軸 | 意味 | ChangeSet での所在 |
|---|---|---|
| **knowledge 軸** | Theme subsystem が **いつ知ったか**（attached_at / observation・governance・metadata・mapping の recorded_at） | `changes` 全体（T1 の知識と T2 の知識の差そのもの）＋ `knowledge_axis`（window 内に知った evidence の attached_at、T2 observation の recorded_at、新 terminal mapping の recorded_at） |
| **evidence-time 軸** | evidence が指す **現実世界の時点**（evidence_time / evidence_date） | `evidence_time_axis`（window 内に visible になった evidence を DATED_WITHIN_WINDOW（T1 < evidence_time ≤ T2）/ DATED_BEFORE_WINDOW（evidence_time ≤ T1）/ UNDATED（quality MISSING）に分類、新 counted date 集合） |

例: evidence_time ＝ 9/10、attached_at ＝ 9/12、T1 ＝ 9/11、T2 ＝ 9/13 → `changes` に EVIDENCE_ADDED（knowledge 軸: 9/12 に
知った）、`evidence_time_axis` に DATED_BEFORE_WINDOW（9/10 の evidence が後から知識に入った）。T1 ＝ 9/11 の解決には
現れない（resolver が `not_yet_attached` に分離する）。role 訂正は新しい evidence ではないため evidence-time 軸に載せない。

## 4. evidence の対応（matching）

1. 基本 identity は `attachment_key`（`ref_id#consequence_ref`）。同一 key で role が違えば EVIDENCE_ROLE_CHANGED、role が
   同じで他 field が違えば EVIDENCE_ATTRIBUTE_CHANGED。
2. key が変わる置換は、次の **決定論的 1:1 対応**が取れるときだけ対応づける:
   - 追加側の `revision_of_at_attachment` が削除側の `ref_id` を指し、`consequence_ref` が同じ削除候補がちょうど 1 件 →
     EVIDENCE_REF_REVISED。
   - 同一 `ref_id` の追加が 1 件・削除が 1 件で role が異なる → EVIDENCE_ROLE_CHANGED（detail "consequence_ref changed"）。
3. 候補が複数ある・role が同じで consequence だけ違う等、曖昧な場合は **推測せず** EVIDENCE_ADDED ＋ EVIDENCE_DROPPED のまま。
4. carried evidence（`after.carried` の key）は結果 root 側では EVIDENCE_CARRIED。lineage の変化（LINEAGE_CHANGED）とは別。
5. dereference の変化（AVAILABLE → SUPERSEDED 等）は EVIDENCE_DROPPED にしない。canonical evidence は残る（§9）。

## 5. source / date diversity

- Foundation `DerivedView.qualification`（A4a の保守的 helper: union-find による origin group、日付集合）の値を比較する。
  B1 は origin grouping を再定義せず、attachment 件数の増加と diversity の増加を区別する。
- NEW_SOURCE_ORIGIN ＝ `independent_origins` が増えた（before / after に件数）。同一 origin からの追加 evidence は
  EVIDENCE_ADDED だけで NEW_SOURCE_ORIGIN にならない。
- NEW_EVIDENCE_DATE ＝ `evidence_dates` 集合に加わった日付ごとに 1 件。既に数えられた日付の別 origin は NEW_SOURCE_ORIGIN
  だけで NEW_EVIDENCE_DATE にならない。
- 減少（evidence drop 等）は SOURCE_ORIGIN_LOST / EVIDENCE_DATE_LOST。

## 6. qualification

`qualification.status` の遷移を QUALIFICATION_CHANGED（before / after に値）で表す。両方向。これは A2 §19 の述語の変化であり
lifecycle の昇格 / 降格ではない（detail に明記）。score を作らない。NO_STATE からの初回観測は before ＝ 空文字。

## 7. contradiction / invalidation

- `has_contradicting_evidence` / `has_invalidating_evidence` の false → true を *_APPEARED、true → false を *_CLEARED。
- **CLEARED の意味**: T2 の resolved current observation の visible view に当該 role の evidence が無いことだけを示す。
  「反証された事実が消えた」「反証が否定された」ではない。旧 observation と旧 attachment は canonical 履歴に残る
  （detail に同文を載せる）。

## 8. facet の独立

governance / metadata（field ごと）/ mapping / lineage / pending は独立に比較し、1 facet の変化や UNRESOLVED を他 facet に
伝播させない。

| facet | 比較対象 |
|---|---|
| governance | status（UNRESOLVED 出入り）、effective_event_id / type、terminal_event_id、reversed_event_ids。NOT_EVALUATED ↔ NO_GOVERNANCE は空同士で変化なし |
| metadata | LABEL / DESCRIPTION / TAXONOMY / ALIAS ごとに (record_id, value)。facet 名 `metadata:<FIELD>` |
| mapping | terminal mapping id 集合と status。追加 id の recorded_at を knowledge 軸へ |
| lineage | (kind, event_id, related_roots) 集合 |
| pending | (kind, subject_id, missing) 集合。missing の変化は CLEARED ＋ APPEARED の組で表す |

## 9. UNRESOLVED / NO_STATE / dereference

- RESOLVED → UNRESOLVED: SEMANTIC_BECAME_UNRESOLVED（related ＝ T2 の診断 kind）。observation / evidence / derived の差分は
  **作らない**（診断 SEMANTIC_UNRESOLVED_AT_T2）。観測不能を「変化なし」にしない。
- UNRESOLVED → RESOLVED: SEMANTIC_BECAME_RESOLVED。evidence / derived の baseline が無いので差分は作らない
  （診断 EVIDENCE_BASELINE_UNAVAILABLE）。
- UNRESOLVED → UNRESOLVED: 診断 SEMANTIC_UNRESOLVED_BOTH。
- NO_STATE: failure ではない。RootRecord 不在 → 存在で ROOT_APPEARED、eligible observation 0 → 有りで ROOT_BECAME_OBSERVED
  （1 window で両方起こりうる）。NO_STATE → RESOLVED では T2 の view を空の baseline と比較する（genesis の evidence は
  EVIDENCE_ADDED / EVIDENCE_CARRIED、qualification は空 → 値、flag は false → 値）。PENDING の変化は併記する。
- 宣言済み・未作成の result root（Foundation A4d.1）: NO_STATE のまま LINEAGE_CHANGED（MERGE_OF 等）と PENDING_APPEARED が
  現れ、root 作成で ROOT_APPEARED、genesis で ROOT_BECAME_OBSERVED ＋ EVIDENCE_CARRIED。
- dereference: before / after 双方に存在する ref_id の status が違うときだけ DEREFERENCE_CHANGED。caller 供給の lookup
  （`dereference_before` / `dereference_after`）が違えばそれが差として現れる。canonical の変化と混ぜない。

## 10. failure 意味論

| 入力 | 挙動 |
|---|---|
| `before.cutoff > after.cutoff` | `ThemeChangeError("CUTOFF_ORDER")`（fail closed。等しい T は許可 → 空 ChangeSet） |
| `before.root_id != after.root_id` | `ThemeChangeError("ROOT_MISMATCH")` |
| resolver_version が両者で異なる、または `theme_resolver:0.1.0` 以外 | `ThemeChangeError("RESOLVER_VERSION_INCOMPATIBLE")` |
| いずれかが INVALID_HISTORY / STORE_CORRUPTION | 例外ではなく `status = UNAVAILABLE`、`changes = ()`、診断 BEFORE_/AFTER_UNAVAILABLE（related ＝ 元の診断 kind）。通常の変化として扱わない |
| NO_STATE / UNRESOLVED | failure ではない（COMPUTED） |

## 11. 決定論

同一 (before, after) → 等価な `ThemeChangeSet`（frozen dataclass。`==` / hash 可）。`changes` は
(facet 順, kind 順, subject_id, before, after, related) で整列。history の入力順（shuffle）・再読込・別 store 経路に依らない。
現在時刻・乱数・IO・network・SQLite を使わない（source token guard）。時計の注入も不要（caller が T1 / T2 を渡す）。

## 12. 除外（B1 でしないこと）

lifecycle 状態名、discovery / proposal、dedup、relation graph、taxonomy / entity catalog、monitoring runner / scheduling、
derived index、LLM、journal 保存、content id、Foundation 語彙変更（D-B7）、Compass / Brief / P5 / 公開出力への接続、
`directly_evidenced_links` の差分（後続で必要なら ENTITY_LINK_CHANGED を追加）。

## 13. API

```
compare_resolutions(before: ThemeResolution, after: ThemeResolution) -> ThemeChangeSet     # 主 authority
detect_changes(history: ThemeHistory, root_id, from_cutoff, to_cutoff, *,
               dereference_before=None, dereference_after=None) -> ThemeChangeSet          # resolve を 2 回呼ぶ wrapper
```

`ThemeChangeSet(schema_version, change_model_version, resolver_version, root_id, from_cutoff, to_cutoff, status,
from_status, to_status, from_observation_id, to_observation_id, changes, knowledge_axis, evidence_time_axis, diagnostics)`、
`Change(kind, facet, subject_id, before, after, detail, related)`、`KnowledgeAxis(evidence, observation_recorded_at,
mappings_recorded_at)`、`EvidenceTimeAxis(evidence, new_evidence_dates, dated_within_window, dated_before_window, undated)`。
store IO の wrapper は持たない（必要なら caller が `resolve_at_data_root` の結果を `compare_resolutions` へ渡す）。

## 14. tests

`tests/intelligence/test_theme_change.py`（matrix 1〜42。A4d 代表 world ＋ 合成 ThemeHistory）、
`tests/intelligence/test_theme_intelligence_import_boundary.py`（40〜44: 語彙 / score / IO・時計・乱数 / import 境界 /
production closure / Foundation からの非参照）。Foundation の boundary test は「他 package は themes を import しない」の
対象から `theme_intelligence`（D-B1 で許可された層）だけを除外する。

## 15. versioning

`CHANGE_SCHEMA_VERSION = theme_change_set:0.1.0`（field 集合）、`CHANGE_MODEL_VERSION = theme_change_model:0.1.0`
（比較規則・語彙）。語彙の追加は model version、field の追加は schema version を上げる。`SUPPORTED_RESOLVER_VERSION`
は Foundation resolver と 1:1 に固定し、resolver version が変われば本 module も明示的に更新する（黙った互換を主張しない）。
ChangeSet は保存しないため migration は無い。
