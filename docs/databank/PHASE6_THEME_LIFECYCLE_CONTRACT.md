# Phase 6 — Theme Lifecycle View Contract（P6-B2）

状態: **実装済み**（`src/intelligence/theme_intelligence/lifecycle_model.py` / `lifecycle.py`、
`theme_lifecycle_view:0.1.0` / `theme_lifecycle_model:0.1.0` / `theme_lifecycle_policy:0.1.0`）。
Foundation（anchor `12847bf`）と B1（anchor `e2d5168`）は無変更。監督者決定 L-1〜L-8 を実装に写した。

## 1. snapshot vs delta

- Lifecycle は **snapshot 意味論**: T 固定の `ThemeResolution` 1 つから再構築できる。
- B1 `ThemeChangeSet` は **delta 意味論**であり、lifecycle を決める authority ではない。`derive_lifecycle` は ChangeSet を
  入力に取らない。「ChangeSet が n 件だから state X」という論理は存在しない。将来の monitoring は
  `Lifecycle(T)` と `ChangeSet(T−1, T)` を並べて使う（B6）。
- view は derived / rebuildable。journal に書かず content id を持たない（L-8）。

## 2. 2 層の分離（L-1 / L-2）

| 層 | 意味 | 入力 |
|---|---|---|
| **GovernanceLifecycleView** | 人間 review / governance 上の位置（唯一の authoritative 層） | Foundation `governance.status` / `effective_event_id` / `effective_event_type` / `lineage` |
| **EvidenceConditionView** | evidence の現在状態の derived flag 集合。承認・昇格・格下げを **意味しない** | Foundation `EvidenceView.visible` と `DerivedView`（qualification・counted keys・origin 数・日付集合・contradiction / invalidation flag） |

evidence 層から governance 状態を変更しない。単一 state machine にしない。

## 3. governance state（LOCK）

| state | 導出 |
|---|---|
| UNREVIEWED | root / semantic は存在するが effective な人間 governance decision が無い（NO_GOVERNANCE、全 event が取り消された、または effective が origin event / correction のみ） |
| ACCEPTED | effective ＝ CANDIDATE_ACCEPTED。REOPENED も受理状態の回復として ACCEPTED（§10 の要確認事項） |
| REJECTED | effective ＝ CANDIDATE_REJECTED |
| RETIRED | effective ＝ RETIRED |
| MERGED | effective ＝ MERGE かつ lineage にこの root の MERGED_INTO（subject 側） |
| SPLIT | effective ＝ SPLIT かつ SPLIT_INTO |
| SUPERSEDED | effective ＝ SUPERSEDED_BY_ROOT かつ SUPERSEDED_BY |
| UNRESOLVED | Foundation governance facet が UNRESOLVED |
| NOT_AVAILABLE | resolution が INVALID_HISTORY / STORE_CORRUPTION、または NO_STATE |

規則:
- **独自 latest-wins をしない。** Foundation resolver の facet だけを使い、矛盾は lifecycle 側で解決しない。
- EVENT_REVERSED は state ではない。resolver が畳み込んだ effective event を使う（取消で前の状態に戻る）。
- ROLE_CORRECTION_APPROVED / CERTAINTY_CHANGE_APPROVED / METADATA_CORRECTION_APPROVED は lifecycle state を変えない。
  これらが effective（terminal）のときは、caller が渡す `governance_events`（read-only の governance record）で
  `governance.chain` を遡り、取消済み・取消 event・訂正 event を飛ばして効力を持つ最後の lifecycle event を用いる
  （`state_event_id` に記録、診断 CORRECTION_TERMINAL_IGNORED）。渡されなければ **推測せず** `ThemeLifecycleError
  (GOVERNANCE_EVENTS_REQUIRED)`。chain の event が欠けていれば GOVERNANCE_EVENTS_INCOMPLETE。
- MERGE / SPLIT / SUPERSEDED_BY_ROOT が effective でも、この root が **result 側**（lineage MERGE_OF / SPLIT_FROM /
  SUCCESSOR_OF）なら、それは origin event であって受理決定ではない → UNREVIEWED ＋ 診断 ORIGIN_EVENT_ONLY
  （§10 の要確認事項）。

## 4. evidence flags（排他ではない）

| flag | 導出（Foundation の値を参照。再 count しない） |
|---|---|
| NO_VISIBLE_EVIDENCE | counted evidence（`qualification.counted_attachment_keys`）が 0 |
| HAS_CONTEXT_ONLY | visible attachment はあるが counted が 0 |
| HAS_SUPPORT | counted に SUPPORTS がある |
| SINGLE_SOURCE / MULTI_SOURCE | `independent_origins` ＝ 1 / ≥ 2 |
| SINGLE_EVIDENCE_DATE / MULTI_DATE | `evidence_dates` の要素数 ＝ 1 / ≥ 2 |
| QUALIFIES | `qualification.status` ＝ QUALIFIES_SEMANTICALLY |
| CONTESTED | `has_contradicting_evidence`（visible current observation に CONTRADICTS が ≥ 1） |
| INVALIDATION_EVIDENCE_PRESENT | `has_invalidating_evidence`（INVALIDATES が ≥ 1） |
| STALE | §5 |

同時成立可（例: MULTI_SOURCE ＋ MULTI_DATE ＋ QUALIFIES ＋ CONTESTED ＋ STALE）。数値は件数（visible / counted / origin /
date）と calendar 日数だけで、score・rank・tier・重みは無い（L-4）。

## 5. freshness policy と STALE 境界（L-6 / L-7）

- `LifecyclePolicy(stale_after_days: int ≥ 1, schema_version = theme_lifecycle_policy:0.1.0)`。
  `default_lifecycle_policy()` ＝ 90 calendar days。`derive_lifecycle` は policy を **明示入力**で受け取り、結果
  （`view.policy`、`evidence.stale_after_days`）に残す。B2 では `config.yaml` に追加しない。
- 判定: counted evidence のうち `evidence_time` を持つ（quality MISSING を除く）ものの最新 `evidence_time` を取り、その
  UTC 日付から `resolution.cutoff` の UTC 日付までの **calendar 日数** `elapsed_calendar_days` が
  `stale_after_days` 以上なら STALE。**89 日 → false、90 日 → true**（時刻ではなく日付の差）。
- future evidence は Foundation が不可視にするので使わない。MISSING の evidence_time は最新候補に使わない。
- dated counted evidence が 0 件なら STALE を付けず、診断 STALE_NOT_EVALUABLE_NO_DATED_EVIDENCE を返す
  （`latest_dated_evidence_time` / `elapsed_calendar_days` は None）。
- **STALE ≠ 弱い / 無効 / 魅力が低い / 価格の勢い。** 「reference cutoff から見て新しい counted evidence が一定期間
  観測されていない」という freshness diagnostic のみ。

## 6. qualification の再利用

`QUALIFIES` は Foundation A2 §19 の述語（source diversity ∧ temporal diversity）への参照であり、B2 独自の qualified
score / confidence / strength / maturity は作らない。`evidence.qualification_status` に Foundation の値をそのまま置く。

## 7. contradiction / invalidation の意味

- CONTESTED は「Theme が偽」ではない。反証 evidence が current view に存在するという事実。
- INVALIDATION_EVIDENCE_PRESENT は自動 RETIRED を意味しない。引退は人間の governance event。evidence 層は governance state
  を変えない（test 20）。

## 8. partial availability / facet isolation

| 条件 | `status` | governance.state | evidence.status |
|---|---|---|---|
| semantic RESOLVED ∧ governance RESOLVED / NO_GOVERNANCE | AVAILABLE | 導出値 | EVALUATED |
| governance UNRESOLVED ∧ semantic RESOLVED | PARTIALLY_AVAILABLE | UNRESOLVED | EVALUATED |
| semantic UNRESOLVED（governance は評価可） | PARTIALLY_AVAILABLE | 導出値 | UNRESOLVED（flag 空、推測しない） |
| NO_STATE（未知 root / 作成前 / genesis 未記録 / 宣言済み未作成） | UNAVAILABLE | NOT_AVAILABLE | NOT_EVALUATED（診断 NO_THEME_STATE、related に resolver 診断と PENDING kind） |
| INVALID_HISTORY / STORE_CORRUPTION | UNAVAILABLE | NOT_AVAILABLE | NOT_EVALUATED（診断 RESOLUTION_UNAVAILABLE） |

metadata / mapping facet の UNRESOLVED は lifecycle の availability に影響しない（B2 は metadata / mapping を使わない）。
NO_STATE と UNRESOLVED は failure ではない（`resolution_status` で区別できる）。

## 9. 除外（B2 でしないこと）

single state machine、EMERGING / ACCELERATING / MATURE / WEAKENING / STRONG / WEAK / HOT / COLD / BULLISH / BEARISH /
WINNING / LOSING / HIGH_CONVICTION / LOW_CONVICTION 等の語（L-3）、件数 score / weighted score / rank / tier（L-4）、
P5 prediction / calibration・価格 return・MarketSignal・MorningBrief・CompassDraft・formal review の入力（L-5）、
journal 書き込み、content id、config.yaml 変更、transition API（B2 MVP では未実装）、B1 ChangeSet の入力。

## 10. 要確認事項（監督者）

1. REOPENED を ACCEPTED（受理状態の回復）として扱う解釈。代替は UNREVIEWED（再受理待ち）。
2. merge / split / successor の **result root** を UNREVIEWED ＋ ORIGIN_EVENT_ONLY とする保守的解釈。代替は
   「宣言 event ＝ 人間決定」として ACCEPTED 相当にする解釈（自動昇格に近いため既定では採らない）。
3. correction が terminal のときの `governance_events` 必須化（Foundation `GovernanceFacet` が chain の event 種別を
   持たないため）。将来 Foundation を変更するなら facet に chain 種別を載せる案がある（本 gate では変更しない）。

## 11. versioning

`theme_lifecycle_view:0.1.0`（field 集合）、`theme_lifecycle_model:0.1.0`（導出規則・語彙）、
`theme_lifecycle_policy:0.1.0`（policy schema）。policy 値は結果に残り、window 変更後も過去 view を同じ policy で
再現できる。resolver version は B1 と同じ `theme_resolver:0.1.0` に固定（不一致は fail closed）。

## 12. import 境界

`lifecycle.py` / `lifecycle_model.py` は `themes.model`（enum / record 型）/ `themes.qualification`（status enum）/
`themes.resolver`（ThemeResolution / facet 型）/ `theme_intelligence.model`（resolver version 定数）だけを import する。
store 書き込み・operations・Compass / MorningBrief / MarketSignal / predictions / calibration / market / legacy /
network / filesystem / 現在時刻 / LLM は無い（boundary test で token 固定）。B1 `change.py` は変更しない。

## 13. tests

`tests/intelligence/test_theme_lifecycle.py`（matrix 1〜37 ＋ 失敗入力）、
`tests/intelligence/test_theme_intelligence_import_boundary.py`（38〜41、45: P5 / 市場 / 時計 / IO token、import 境界、
production closure、Foundation 結果の再 count 禁止）。42〜44・46・47（Foundation / B1 diff 0、P4 / P5 非退行、full
suite、guards）は gate 報告で検証する。
