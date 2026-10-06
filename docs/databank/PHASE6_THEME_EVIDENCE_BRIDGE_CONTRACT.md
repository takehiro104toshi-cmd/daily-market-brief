# Phase 6 / P6-B4E — ACCEPTED evidence candidate → Foundation attachment plan

受理済みの `EvidenceCandidateProposal` から、後で Foundation の `EvidenceAttachment` を組み立てるために必要な
材料を確定させる **計画境界** の契約。実行境界ではない。

---

## 1. 権限（authority）の原則

提案の受理（ACCEPT）は **計画の作成を authorize する** だけであり、それ自体は Foundation authority を変えない。

本 gate が返す `EvidenceAttachmentPlan` は次の **いずれでもない**。

- Theme evidence authority
- `ThemeObservation`
- Theme revision
- governance record
- 真実性の証明
- 資格判定（qualification）の結果

Foundation への実行は、後続の明示的な gate に属する。

## 2. 対象（target）の規則

`EvidenceCandidateProposal` は root_id か proposal_id のどちらかを対象にできるが、B4E が橋渡しできるのは
**明示された Foundation root_id のみ**。

- `target_root_id` が空（`target_proposal_id` のみ、または対象なし） → `TARGET_NOT_FOUNDATION_ROOT`
- THEME_CANDIDATE proposal を root へ解決しない。
- taxonomy / entity / fingerprint / dedup / 類似度 / 既存 Theme から root を推測しない。

## 3. API

```python
plan_evidence_attachment_from_accepted_proposal(
    proposal,
    decisions,
    *,
    target_resolution,
    created_at,
    consequence_ref=None,
    invalidation_ref=None,
) -> EvidenceAttachmentPlan
```

store 引数・data root・現在時刻を取らない。`target_resolution` は呼び出し側が供給する（read-only）。

## 4. 受理の判定

- proposal type は `EVIDENCE_CANDIDATE` でなければならない → 他は `INVALID_PROPOSAL_TYPE`
- active decision が `ACCEPT` に解決しなければならない → それ以外は `PROPOSAL_NOT_ACCEPTED`（detail に derived status）

決定の解決は **B3 の `resolve_active_decision` / `derive_proposal_status` をそのまま使う**。latest-wins を再実装しない。
chain は `supersedes_decision_id` の graph で決まり、`recorded_at` や物理順では決まらない。

計画を作れない状態: 決定なし（OPEN）、DEFER（OPEN_DEFERRED）、REJECT（REJECTED）、NOT_DUPLICATE
（CLOSED_NOT_DUPLICATE）、fork / 複数 start（OPEN_UNRESOLVED）、dangling predecessor / cycle（INVALID_DECISION_HISTORY）。
REJECT を supersede した ACCEPT は受理として扱う。

## 5. 対象 resolution の検証

- `target_resolution.root_id == proposal.target_root_id` → 不一致は `TARGET_ROOT_MISMATCH`
- `status` は `RESOLVED` でなければならない → `NO_STATE` / `UNRESOLVED` / `INVALID_HISTORY` / `STORE_CORRUPTION` は
  `TARGET_NOT_RESOLVED`（detail に status）
- 観測状態（`observation`）が存在しなければならない → 無ければ `TARGET_NOT_RESOLVED`
- Foundation 型でなければ `INVALID_TYPE`

`ThemeStore` は読まない。

## 6. 役割（role）

`proposal.proposed_role` をそのまま使う。B4E が橋渡ししてよいのは **SUPPORTS / CONTEXT** のみ。

- CONTEXT を SUPPORTS へ昇格させない。
- CONTRADICTS / INVALIDATES を作らない。B3 model 上は許される役割でも、bridge 方針の外なら
  `FORBIDDEN_BRIDGE_ROLE` で fail closed。
- 時刻品質が `MISSING` の evidence は CONTEXT にしか付与できない（Foundation A2 §7）。SUPPORTS なら
  `ROLE_REQUIRES_EVIDENCE_TIME`。

## 7. 役割の provenance

plan の `role_provenance` は常に **HUMAN**。人間が明示的に ACCEPT したからである。RULE を最終的な役割 authority
として残さない。`role_asserted_by` は受理決定の `actor_ref`。

提案の出自は別に保持する（`ProposalOrigin`）。

| 保持先 | 意味 |
|---|---|
| `role_provenance` / `role_asserted_by` | 受け入れられた役割の authority（人間） |
| `proposal.proposer_class` / `proposer_ref` / `rule_version` | 提案の出自（例: discovery rule） |
| `proposal.provenance_reason` / `candidate_reason` | 提案側の理由（rule 非依存の canonical reason を含む） |
| `decision.*` | 受理そのものの governance fact |

**提案の出自と、受け入れられた役割の authority は別物である。**

## 8. plan の field

| field | 由来 |
|---|---|
| `target_root_id` / `target_resolver_version` / `target_cutoff` / `target_observation_id` | 対象 resolution |
| `evidence_kind` / `ref_id` / `source_origin` / `evidence_time` / `evidence_time_basis` / `evidence_time_quality` / `evidence_date` | 提案のまま |
| `authority_class` | `PRIMARY_OBSERVATIONAL` 固定（Foundation が attachment に許す唯一の class） |
| `role` | 提案のまま |
| `role_provenance` / `role_asserted_by` | HUMAN / 受理者 |
| `attached_at` | 呼び出し側の `created_at` |
| `consequence_ref` | 呼び出し側が明示（SUPPORTS のみ） |
| `invalidation_condition_ref` | 常に空 |
| `limited_use` | 時刻品質が `INFERRED` のとき True（Foundation A2 §7 の要求から決定論的に導く） |
| `locator` / `note` | audit metadata（下記 §14） |
| `proposal` / `decision` | provenance snapshot |

evidence 本体（記事本文 / 市場値 / 抜粋）は複製しない。

## 9. attached_at

`attached_at = created_at`（呼び出し側が供給）。要求:

- aware な datetime → naive / 非 datetime は `INVALID_CREATED_AT`
- `created_at >= proposal.created_at` → `CREATED_BEFORE_PROPOSAL`
- `created_at >= decision.recorded_at` → `CREATED_BEFORE_DECISION`
- `evidence_time` があるとき `created_at >= evidence_time` → `CREATED_BEFORE_EVIDENCE_TIME`

いずれも等号は許可。現在時刻は読まない。

## 10. consequence ref

SUPPORTS では **必須**であり、対象 resolution の現在の観測の consequence 集合に実在しなければならない。

- 未指定 / 空 → `CONSEQUENCE_REF_REQUIRED`
- 実在しない → `UNKNOWN_CONSEQUENCE_REF`
- 「先頭の consequence を自動採用」しない。discovery rule から推測しない。あいまい一致をしない。

CONTEXT では **禁止**。指定されていれば `CONSEQUENCE_REF_FORBIDDEN`。

## 11. invalidation ref

B4E は INVALIDATES を橋渡ししない。`invalidation_ref` は常に `None` でなければならず、空文字を含め何か与えられた
時点で `INVALIDATION_REF_FORBIDDEN`。将来の矛盾 / 無効化の橋渡しは別の設計課題として残す。

## 12. 重複 attachment

plan を返す前に、対象 resolution の現在の evidence を検査する。同じ Foundation attachment key
（`ref_id#consequence_ref`）が既にあれば `ATTACHMENT_ALREADY_PRESENT` で fail closed する。

黙って plan を返さない。この層では冪等成功として扱わない（実行の冪等性は後続 gate の責務）。
検査集合は保守的に、観測の `attachments` と、可視 evidence / 時刻欠落 context の和をとる。

## 13. 参照の保存

`evidence_kind` / `ref_id` / `source_origin` / `evidence_time` / `evidence_time_basis` / `evidence_time_quality` /
`evidence_date` は提案と完全に同一。参照を辿って書き換えない。後継 source へ差し替えない。origin を畳まない。
source の独立性を主張しない。

## 14. locator / note

`locator` は提案のまま audit metadata として保持する。

`note` は Foundation の制約に従う。Foundation は `role_provenance = HUMAN` の attachment に
理由（`note`）を要求する（A2 §6）。したがって plan の `note` は次の順で決定論的に決める。

1. `proposal.note`（提案者が理由を書いていればそれ）
2. 無ければ受理決定の `reason`（人間が受理時に書いた理由）

いずれも既存の governance / proposal 記録の文言であり、新たな文章を生成しない。提案側の元の値は
`proposal.proposal_note` / `proposal.proposal_locator` に verbatim で残す。

Foundation の attachment identity（`attachment_key` = `ref_id#consequence_ref`）は locator / note を含まない。
Foundation の identity を再設計しない。

## 15. plan model

`EvidenceAttachmentPlan` は frozen dataclass。content id を持たない（journal identity を作らない）。
派生した ephemeral な出力であり、永続化しない。test / 監査のために決定論的な `to_plain()` と
`canonical_line()` を公開する。

## 16. 資格判定の副作用なし

B4E は QUALIFIES / 独立 source 数 / evidence 日付数 / CONTESTED / INVALIDATED / lifecycle 状態 / change set を
計算しない。これらは将来 revision が生まれた後の Foundation / B1 / B2 の責務である。計画の作成だけでは何も変わらない。

## 17. 実行なし

次の呼び出し・import を禁止する。

`ThemeStore` の追記 API、`themes.operations`、revision を作る helper、`new_root_id`、`append_observation`、
`append_governance`、`append_metadata`、`append_mapping`。B4E に `execute_*` API は存在しない。

## 18. proposal authority の不変性

bridge は decision を追記せず、supersede せず、proposal を変更せず、「消費済み」の印を付けず、消費状態を書かない。
ACCEPT は proposal authority における不変の governance fact のまま残る。後で attach されたかどうかは B3 に保存しない
（将来の監視は Foundation の履歴から導出できる）。

## 19. 決定性

同じ proposal・同じ decision graph・同じ `target_resolution`・同じ `created_at`・同じ `consequence_ref` は
完全に等しい plan を返す。decision の物理順を入れ替えても graph の意味が同じなら結果は同じ。
filesystem 順・時計・乱数を使わない。

## 20. 失敗コード一覧

| code | 条件 |
|---|---|
| `INVALID_PROPOSAL_TYPE` | EVIDENCE_CANDIDATE でない |
| `PROPOSAL_NOT_ACCEPTED` | active decision が ACCEPT に解決しない |
| `TARGET_NOT_FOUNDATION_ROOT` | 明示された root_id が無い |
| `TARGET_ROOT_MISMATCH` | resolution の root が提案の対象と違う |
| `TARGET_NOT_RESOLVED` | RESOLVED でない / 観測状態が無い |
| `INVALID_TYPE` | 引数の型が違う |
| `FORBIDDEN_BRIDGE_ROLE` | SUPPORTS / CONTEXT 以外 |
| `ROLE_REQUIRES_EVIDENCE_TIME` | 時刻欠落 evidence を CONTEXT 以外で付けようとした |
| `CONSEQUENCE_REF_REQUIRED` | SUPPORTS で consequence 未指定 |
| `UNKNOWN_CONSEQUENCE_REF` | 指定 consequence が対象に無い |
| `CONSEQUENCE_REF_FORBIDDEN` | CONTEXT に consequence 指定 |
| `INVALIDATION_REF_FORBIDDEN` | invalidation ref が与えられた |
| `ATTACHMENT_ALREADY_PRESENT` | 同じ attachment key が既に存在 |
| `INVALID_CREATED_AT` | naive / 非 datetime |
| `CREATED_BEFORE_PROPOSAL` / `CREATED_BEFORE_DECISION` / `CREATED_BEFORE_EVIDENCE_TIME` | 時刻の前後関係 |

## 21. import 境界

許可: `proposal_model` / `proposal_resolution` / Foundation の read-only model・resolution 型 / 標準ライブラリ /
Theme Intelligence で既に使われている canonical 直列化。

禁止: `proposal_store` / `themes.store` / `themes.operations` / discovery runtime / lifecycle / change /
predictions / reports / network / LLM / filesystem。Foundation は B4E を import しない。

## 22. 限界と留意点

1. 対象は既存の解決済み root に限る。新 Theme の genesis は本 gate の範囲外。
2. `consequence_ref` は呼び出し側（人間または上位 UI）が選ぶ。bridge は選ばない。
3. plan は永続化されないため、同じ plan を二度作ることは自由であり、実行側が冪等性を持つ必要がある。
4. 矛盾 / 無効化 evidence の橋渡しは未設計。
5. `limited_use` は Foundation の制約から決定論的に導いた唯一の派生値である。

## 23. supervisor 決定が必要な事項

| id | 論点 |
|---|---|
| D-B4E-1 | HUMAN role authority が要求する `note` の決定方式（提案 note → 受理理由の順）でよいか |
| D-B4E-2 | 重複 attachment を fail closed にしたが、上位 UI が「既に付与済み」を区別したい場合に、例外ではなく明示的な結果値へ変える必要があるか |
| D-B4E-3 | plan を永続化する journal（誰がいつ計画したか）を将来持つか。B4E では持たない |
| D-B4E-4 | CONTRADICTS / INVALIDATES の橋渡しを別 gate で設計する時期 |
