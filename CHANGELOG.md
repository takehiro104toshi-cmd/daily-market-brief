# CHANGELOG

このファイルは `CLAUDE.md` の運用プロトコルに従い、`## vX.Y` 形式で
「追加／改善／修正」を追記していく。本ファイルの記録は今回の更新から開始する
（それ以前の機能一覧・構成は `README.md` を参照）。

## v5.28 (2026-09-24) — Phase 6 P6-B6E monitoring E2E / adversarial validation gate

B6A architecture / B6B model / B6C engine / B6D operational layer を **1 系として** 検証した。
**runtime は 1 byte も変更していない**（`git diff 8ef09ab -- src/intelligence/theme_intelligence knowledge/theme_intelligence`
が空であることを test で固定）。閾値調整・condition 追加・identity 変更・review semantics 変更は一切していない。

**判定は BLOCKER_FOUND。** B3 / B5C の提案 record が run cutoff で濾過されず、cutoff より後に記録された
関係提案が過去 cutoff の run で finding を生む。remediation は P6-B6D（runner）の担当であり、本 gate では修正しない。

### 追加 — `tests/intelligence/test_theme_monitoring_e2e.py`【新規】

- §A: B6C の 18 condition すべてに positive / negative fixture（36 件）。category / subject_kind /
  salient_state_kind / cutoff 非依存の finding identity / COMPLETE・PARTIAL 挙動を検証。
- §B: corruption matrix（Foundation / B3 / B5B / B5C / review × malformed / truncated / non-canonical /
  not-an-object / blank / 欠損 / duplicate conflicting / unsupported schema / unknown field）。
  すべて fail closed・PARTIAL・自動修復なし・byte 不変。
- §C: cross-layer E2E（authority journal → resolver → B2 / B3 / B5 derived → adapter → engine → review lookup）。
  合成 world から **17/18 condition** を実 authority 経由で発火。review-state の全生涯（ACK → 消失 → 再出現 →
  同一 finding_id → 自動 reopen しない）と chain 異常 4 種を固定。
- §D: 同一 cutoff の replay 一致、独立 record の物理順 shuffle 11 seed、PIT 境界（cutoff / −1µs）。
- §E: data_root 全 file の inventory 比較による zero-write、authority / knowledge hash 不変、
  finding・run report 非永続、RR-3、hidden authority、source-origin 安全性、security。
- §F: read-only shadow harness の検証と real-data precheck。

### 追加 — `tests/intelligence/theme_monitoring_shadow.py`【新規】

- 実 data_root 用の **READ-ONLY shadow validation harness（1 command）**。
  実行前後の file inventory（sha256）比較で zero-write を証明し、同一 cutoff の 2 回 run を自動比較する。
- review append なし / finding 保存なし / scheduler なし / notification なし / network なし / 現在時刻なし。
- summary は counts・安定 id・diagnostic code・version・hash のみ。本文・note・actor・絶対 path を出さない。
- production entry point ではないため `scripts/` ではなく test helper として置く
  （`.github/` ・`config.yaml` ・`scripts/` が `theme_intelligence` を参照しない既存不変条件を保つ）。

### 追加 — `docs/databank/PHASE6_THEME_MONITORING_E2E_VALIDATION.md`【新規】

18 condition coverage matrix、cross-layer 結果、zero-write 証明、PIT matrix、corruption matrix、
PARTIAL 品質監査、blind-spot 監査（B6D limitation #1）、noise 監査、BLOCKER の再現手順と remediation 提案、
real-data precheck（**REAL_DATA_SHADOW_NOT_RUN**: Theme authority journal がどの環境にも存在しない）、
B6 closeout entry contract。

### 記録 — 検出した BLOCKER（本 gate では修正しない）

- `monitoring_runner._read_proposals()` / `_read_relation_proposals()` が B3 / B5C の record を
  run cutoff で濾過しない。`theme_proposals` / `theme_relation_proposals` の input digest が cutoff に依存せず、
  未来の関係提案が過去 cutoff の run で `RETRACTED_RELATION_HAS_NEW_PROPOSAL` を発火させる。
- Foundation（`resolve_at_data_root`）と B5B（`resolve_relations_at_data_root`）は PIT 正しい。
  B3 / B5C の derive API は cutoff 引数を持たないため、濾過は runner 側の責務である。
- PIT 契約を述べる test 2 件を **strict xfail** として残した（defect に合わせて test を弱めない）。

## v5.27 (2026-09-23) — Phase 6 P6-B6D 運用 review store ＋ read-only monitoring runner

B6B（model）と B6C（engine / ruleset）を **無変更**のまま、monitoring の運用層を追加した。
読むのは authority、書くのは **人間の review 状態だけ**である。
`MonitoringFinding` は保存しない（B6A Option C）。**scheduler / notification / 実データ監視 /
B5 execution gate / B7 は作っていない。** Foundation・B1〜B5 の runtime も無変更
（frozen anchor 14 件すべてに対して `src/` ・`knowledge/` ・`config.yaml` ・workflow の変更 0。新規追加のみ）。

### 追加 — `src/intelligence/theme_intelligence/monitoring_store.py`【新規】

- `<data_root>/theme_intelligence/monitoring_review_states.jsonl` の **追記専用 journal**。
  `append_review_state()` が唯一の書き込み経路で、人間が明示的に行った review だけを通す。
- 明示 `data_root`（空・空白・`~` 始まりは `DATA_ROOT_REQUIRED`）、canonical 行のみ、
  `open('ab')` → flush → `os.fsync`、同 id ＋ byte 一致 ＝ `ALREADY_PRESENT`、同 id ＋ 異 bytes ＝ `CONFLICT`、
  外部変更は byte 長で検知（single writer）。修復・migration・読み飛ばし・現在時刻の参照は無い。
- 破損語彙 12 種（`AUTHORITY_MISSING` / `NON_CANONICAL_LINE` / `UNSUPPORTED_SCHEMA_VERSION` ほか）と
  chain 規律 5 種（`MISSING_PREDECESSOR` / `CROSS_FINDING_PREDECESSOR` / `NOT_TERMINAL_PREDECESSOR` /
  `NON_MONOTONIC_RECORDED_AT` / `INVALID_TYPE`）で fail closed。
- 終端の決定は B6B の `resolve_review_state` だけが行う。store は独自の latest-wins を持たない。

### 追加 — `src/intelligence/theme_intelligence/monitoring_adapter.py`【新規】

- 上流の resolved / derived state（Foundation resolution・B2 lifecycle view・B3 提案 status・
  B5 relation resolution・B5C 提案 status）→ B6C `MonitoringEvaluationInput` の **純写像**。
  B6C limitation #1（snapshot 構築が engine の外にある）を閉じた。
- silent coercion を禁止: `None` を false にしない、`UNRESOLVED` を「存在しない」にしない、
  store 破損を「条件が無い」にしない、未知 root を「不活性」にしない。すべて
  `SubjectAvailability.UNAVAILABLE` ＋ `failure_class` として engine へ渡る。
- 決定論的 `input_digests`（`content_id("thmin", canonical JSON)`）。物理順に依存せず、
  mtime / inode / 絶対 path / 現在時刻を含まない。
- B6B の token 語彙・長さ制限を超える識別子は **捨てず**に `content_id("thmloc", …)` の安定 locator へ畳む。

### 追加 — `src/intelligence/theme_intelligence/monitoring_runner.py`【新規】

- `run_monitoring()`: 明示入力 → version 固定の knowledge 読み込み → authority の read-only 読み取り →
  cutoff 固定の PIT 解決 → adapter → `evaluate_monitoring()` → finding ごとの review 状態解決、という
  orchestration のみ。intelligence semantics を持たない。
- **shadow flag を持たず、構造として read-only**。`append_review_state` を import も参照もしない。
- `MonitoringRunResult`（`runner_version` / `report` / `findings` / `reviews` / `review_status` /
  `diagnostics`）。governance command・実行計画・推奨 action・優先度・severity・投資 signal・予測を持たない。
- `ReviewLookupStatus`（`AVAILABLE` / `NOT_INITIALIZED` / `UNUSABLE`）。review journal が読めないことを
  「誰も review していない」にしない。
- 上流の失敗（store 破損 / `NO_STATE` / governance 未解決 / lifecycle の推測拒否 / 端点不明）は
  空 snapshot にならず、`unevaluated_conditions` ＋ INTEGRITY finding ＋ run status `PARTIAL` として伝播する。

### 追加 — test / docs

- `tests/intelligence/test_theme_monitoring_store.py`【新規】51 件（§24 matrix）。
- `tests/intelligence/test_theme_monitoring_runner.py`【新規】78 件（§25 / §26 matrix。
  synthetic な代表 world ＋ 合成 B3 / B5B / B5C record 上での E2E と、run 前後の journal SHA-256 比較を含む）。
- `docs/databank/PHASE6_THEME_MONITORING_OPERATIONAL_CONTRACT.md`【新規】: 権限境界・永続化方式の決定（A 採用）・
  authority read/write map・store 契約・chain 規律・runner 構成・adapter contract 表・PIT・digest・
  knowledge binding・PARTIAL 伝播・再出現の意味論・非変更の証明・限界・B6E entry contract。

### 改善 — guard（既存 test の追加更新。意図は不変）

- `tests/intelligence/test_theme_intelligence_import_boundary.py`: B6D の 3 module を `MODULES` へ追加し、
  `monitoring_store` / `monitoring_runner` を IO module、`monitoring_adapter` を identity module として登録。
  B6 は B5 の read-only な解決結果を読む下流層であるため、B5 逆方向依存 guard の対象から除外した。
- `tests/intelligence/test_theme_monitoring_model.py` / `test_theme_monitoring_engine.py`:
  「store / runner を作っていない」ことの固定を「monitoring 層は B6B/B6C/B6D の 6 module だけで、
  scheduler / notifier / finding store は存在しない」へ更新した。

## v5.26 (2026-09-23) — Phase 6 P6-B6C 決定論的 monitoring engine ＋ versioned ruleset

B6B の frozen model を用い、read-only な resolved state ＋ 明示 cutoff ＋ versioned ruleset から
`MonitoringFinding` 群と `MonitoringRunReport` を純関数的に導く engine を実装した。
**store / review-state store / runner / scheduler / notification / 実データ監視は作っていない。**
B6B model は無変更。Foundation・B1〜B5 の runtime も無変更（frozen anchor 13 件すべてに対して
`src/` ・`knowledge/` ・`config.yaml` ・workflow の変更 0。新規追加のみ）。

### 追加 — `src/intelligence/theme_intelligence/monitoring_rules.py`【新規】

- `CONDITION_REGISTRY`: B6A MVP（§4 の ✅ 21 行）を **18 condition_id** へ写した凍結対応。
  condition_id → category / subject_kind / salient_state_kind / 閾値要求 を固定し、ruleset は宣言し直せるだけで
  変更できない。18 件すべてが B6B の frozen 14 `SalientStateKind` へ写っている。
- strict loader `load_monitoring_rules_version`: schema version 厳密一致・expected version 完全一致・
  `published_at <= cutoff`・digest 一致・未知 key 拒否・重複 condition 拒否・全 condition 必須・
  registry と異なる分類の拒否・閾値の範囲検査・YAML の緩い型変換の拒否（`"yes"` は bool でない、
  version は str のみ）。`PROHIBITED_RULE_KEYS` 22 種（expression / python / eval / regex / prompt / model /
  weight / score / priority / probability / severity / rank / confidence / stance / target_price ほか）を schema で拒否。
- engine を I/O-free に保つため loader を分離した（`discovery_rules` と同じ分担。YAML の読み取りは
  `knowledge_loader.read_yaml_document` 経由のみ）。

### 追加 — `knowledge/theme_intelligence/monitoring_rules.0.1.0.yaml`【新規】

18 condition の versioned policy。閾値は B6 が所有する提案の滞留日数 2 件（OPEN 60 日 / DEFERRED 30 日）だけで、
**stale の日数は B2 `LifecyclePolicy` が所有するため置いていない。**

### 追加 — `src/intelligence/theme_intelligence/monitoring_engine.py`【新規】

- `evaluate_monitoring(evaluation_input, *, ruleset, recorded_at)` の純 API。
  file / network / 現在時刻 / 乱数 / 環境変数を一切触らない（import は `..core.time` と monitoring の
  2 module と stdlib だけ）。
- 入力は typed で不変な最小 snapshot（`ThemeSnapshot` / `ProposalSnapshot` / `RelationSnapshot` /
  `RelationProposalSnapshot` / `KnowledgeDriftSnapshot` / `AuthorityFailureSnapshot`）。generic dict dump を受けない。
- **上流 derived 意味論を再実装しない**。`CONTESTED` / `STALE` / 端点状態 / chain 解決は B1 / B2 / B4 / B5 の
  結果をそのまま読む。stale の日数計算を engine に二重実装していない（test が token 不在を固定）。
- **判定不能を「条件が偽」にしない**。subject が読めない / B2 policy token が無い / 提案の作成時刻が無い場合は
  `unevaluated_conditions` に入れ、INTEGRITY finding を出し、run status を `PARTIAL` にする。
  静かな COMPLETE ＋ finding 0 になる経路が存在しない。
- 同じ障害は fingerprint が同じなので finding も diagnostics も 1 件に収束する（無制限の重複生成をしない）。
- 出力順は `finding_id` 昇順に固定（**順序に優先度の意味は無い**）。score / 順位 / 確率 / severity /
  予測 / 投資スタンス / 実行命令の語彙を持たない。

### 追加 — tests / docs

- `tests/intelligence/test_theme_monitoring_engine.py`【新規】98 test。ruleset loader の拒否条件、
  18 condition の TRUE / FALSE / UNAVAILABLE、§24 の identity test A〜K（同じ状態は cutoff / ruleset version /
  文言 / 追加参照が変わっても同じ finding、stale と滞留は日々変化しない、矛盾 evidence が増えても同じ）、
  11 seed の順序不変性、合成 false-positive gate（**synthetic gate result only**）、入力非改変、
  file 書き込み不在、時計 / 乱数 / network / LLM 不在、import 境界。
- `docs/databank/PHASE6_THEME_MONITORING_ENGINE_CONTRACT.md`【新規】: module 分割の理由、
  21 行 → 18 condition_id の対応表、ruleset schema と拒否条件、入力 model、上流再実装の不在、
  閾値の所有、evidence / proposal / relation / discovery の意味論、integrity routing と PARTIAL、
  version binding、決定論、B6D への entry contract。

### 改善 — 既存 test の additive 更新（3 件）

- `test_theme_intelligence_import_boundary.py`: `MODULES` へ `monitoring_rules` / `monitoring_engine` を、
  `KNOWLEDGE_PATH_MODULES` へ `monitoring_rules` を、`ALLOWED_RELATIVE` へ `.monitoring_model` /
  `.monitoring_rules` を追加。
- `test_theme_monitoring_model.py`: B6B の 2 assertion が「B6C はまだ無い」ことを主張していたため、
  意図（package 外から model を参照しない／store・runner・scheduler・notifier が無い）を保ったまま更新。
- `test_theme_taxonomy_entity_boundary.py`: knowledge 直下に同居してよい ruleset の pattern へ
  `monitoring_rules.<version>.yaml` を additive に追加（signal / keyword 系 file を拒否する意図は不変）。

## v5.25 (2026-09-23) — Phase 6 P6-B6B monitoring model / vocabulary（model gate）

B6A で凍結した Monitoring architecture を、最小・不変・決定論的な runtime model と語彙に落とした。
**engine / ruleset YAML / condition evaluator / store / runner / notification は作っていない。**
実データ監視もしていない。Foundation・B1〜B5 の runtime は無変更（frozen anchor すべてに対して
`src/` ・`knowledge/` ・`config.yaml` ・workflow の変更 0）。

### 追加 — `src/intelligence/theme_intelligence/monitoring_model.py`【新規】

- **語彙**: `MonitoringCategory`（名義 7 種。順序を持たず severity / priority の意味を持たない）、
  `MonitoringSubjectKind`（閉じた 8 種。`OTHER` / `GENERIC` なし）、`MonitoringRunStatus`（COMPLETE / PARTIAL のみ。
  `FAILED` な report は存在しない）、`ReviewDisposition`（ACKNOWLEDGED / DISMISSED / DEFERRED。
  `RESOLVED` も `APPROVED` / `REJECTED` も無い）。
- **`MonitoringFinding`**: 条件成立の derived record。identity は
  `(schema_version, condition_id, category, subject_kind, subject_ref, salient_state)` の content id で、
  **cutoff / ruleset version / knowledge version / 表示文言 / 参照 / diagnostics を含まない**。
  同じ状態は cutoff や ruleset version が変わっても同じ finding になる。
  条件の意味が変わるときは version を上げず `condition_id` を変える（`CONDITION_ID_IS_SEMANTIC`）。
- **`SalientState`**: 自由な JSON ではなく、`SalientStateKind` 14 種ごとに identity を担う key 集合を凍結した
  typed value object。値は bounded な token 文字列のみで、**数値・時刻・score を構造的に保持できない**。
  そのため「何日 stale か」「滞留何日か」が identity に混入せず、毎日別 finding にならない。
  逆に撤退 root への evidence は 1 件ごとに identity を担う。
  `ALLOWED_CATEGORIES_BY_STATE_KIND` が state kind と category の誤った組み合わせを拒否する。
- **`MonitoringReference`**: 根拠の参照 identity のみ。identity を担わないため、矛盾 evidence が増えても
  finding は同じまま。本文・引用を保持しない。
- **`MonitoringRunReport`**: `run_id` は **cutoff ＋ ruleset version ＋ knowledge version ＋ 入力 digest** の
  content id（finding とは逆に cutoff が identity を担う）。実行時刻と結果は identity 外。
  `COMPLETE` は `unevaluated_conditions` が空であることを要求し、`PARTIAL` は理由を必ず持つ。
  **authority が読めなかった run を「finding 0 件の COMPLETE」にできない。**
- **`ReviewItemState`**: 再導出できない人間入力だけを保持する operational record。actor は HUMAN 固定。
  `recorded_at` は identity 外。`resolve_review_state` が `supersedes` graph だけで終端を解き、
  fork / 複数 genesis / dangling / 別 finding の predecessor / cycle を fail closed にする（latest-wins なし）。
- 現在時刻・乱数・network・storage・LLM を使わない。import は `..core.ids` / `..core.time` /
  `..themes.model` と stdlib だけで、B1〜B5 の runtime module を 1 つも import しない。

### 追加 — tests / docs

- `tests/intelligence/test_theme_monitoring_model.py`【新規】111 test。語彙の厳密一致、不変性、
  canonical round-trip、identity の除外項目、salient state の粒度（stale / 滞留が毎日別 finding にならないこと、
  矛盾 evidence 追加で再 surface しないこと、integrity fingerprint の収束）、run identity、
  silent failure の禁止、review chain の fail-closed、隠れた authority と score 語彙の不在、
  時計 / 乱数 / network / LLM の不在、import 境界、engine / ruleset / store / runner が存在しないこと。
- `docs/databank/PHASE6_THEME_MONITORING_MODEL_CONTRACT.md`【新規】: authority 境界・語彙・identity contract・
  condition family ごとの salient state 表・provenance・run report・integrity・review chain・
  時間 / PIT・直列化・security・隠れた authority の不在・B6C への entry contract。

### 改善 — 既存 test の additive 更新（2 件）

- `test_theme_intelligence_import_boundary.py`: `MODULES` と `IDENTITY_MODULES` へ `monitoring_model` を追加。
- `test_theme_relation_rerun.py`: `test_rr_105` が package の module 総数を 30 と直書きしており、
  B5 の非改変とは無関係な将来の module 追加で壊れる状態だった。B5 の面（`relation*.py` の集合）を見る
  assertion に改め、package 全体の inventory は import boundary guard に委ねた。

## v5.24 (2026-09-23) — Phase 6 P6-B6A Monitoring architecture / design audit（docs のみ）

次工程 B6 Monitoring の architecture を設計・凍結するための READ-ONLY / DOCS-ONLY 監査。
**実装は一切行っていない**（`src/` ・`tests/` ・`knowledge/` ・`config.yaml` ・workflow の diff は
B5 freeze anchor に対して 0）。B6B 実装も B5 execution gate も開始していない。
判定は `P6_B6A_MONITORING_ARCHITECTURE_AUDIT_PASS`。blocker は無い。

### 追加 — `docs/databank/PHASE6_THEME_MONITORING_ARCHITECTURE_AUDIT.md`【新規】

- **既存系の再監査**: Foundation / B1 / B2 / B3 / B4 / B5 を source と docs から独立に確認した。
  とくに B2 の `EvidenceConditionFlag` が `CONTESTED` / `INVALIDATION_EVIDENCE_PRESENT` / `STALE` を
  すでに derived view として出していること、`LifecyclePolicy` が現在時刻を読まず cutoff との差で
  判定していることを確認し、B6 はこれらを**再実装せず参照する**方針とした。
- **6 つの意味論層の分離**: Observation / Derived Change / Monitoring Condition / Monitoring Finding /
  Review Candidate / Governance Action。`Monitoring Finding ≠ Governance Action`、
  `Review Candidate ≠ Theme mutation / Relation mutation / Evidence attachment / Prediction / Trading signal`、
  `Acknowledgement ≠ Governance decision` を明文化した。
- **用語の判断**: 本 codebase で `Event` はすでに authority を意味する（`ThemeGovernanceEvent` /
  `ThemeRelationGovernanceEvent`）。derived record に `MonitoringEvent` の名を与えると
  「隠れた governance authority」の誤読を生むため、`MonitoringFinding` を推奨した。
- **persistence の結論（Option C）**: finding は authority ＋ knowledge version ＋ cutoff の純関数なので
  永続化しない。**再導出できない人間入力（acknowledgement / disposition）だけ**を operational journal に置く。
  finding を永続化しないため B5C の「同 id ＋ 異 bytes → CONFLICT」問題が構造的に発生しない。
- **identity**: `finding_key = content id over (condition_id, subject_kind, subject_ref, salient_state)`。
  run 時刻を identity に混ぜない。同じ状態なら同じ key（再提示されない）、状態が変われば別 key（= reopen）、
  条件が消えれば finding が生成されない（= resolved）。閾値や抑制ヒューリスティクスを持たない。
- **severity を MVP から外すことを推奨**。順序尺度は score / ranking へ転用されるため、
  名義分類の `MonitoringCategory` で routing する。
- **fail-closed の monitoring 版**: authority が読めないことを「条件が成立しない」と同一視しない。
  `PARTIAL` ＋ `INTEGRITY` finding とし、静かな無検出を作らない。
- **contradiction / invalidation**、**relation monitoring**、**proposal / discovery monitoring** の
  condition 案と禁止事項、**diagnostics aggregation**（技術 integrity と intelligence review condition を
  別 category に分離。B4 繰越 #3 を回収）、**operational runner の責務と既定禁止**（B4 繰越 #15 を回収）、
  **real-data shadow 段階**（synthetic → fixture → read-only shadow → internal operational）。
- **監督者決定候補 D-B6-1〜D-B6-14**、**B6 MVP と明示的 non-goals**、**test matrix**、
  **実装 sequence（B6B model → B6C engine → B6D review store ＋ runner → B6E 敵対的 gate → closeout）**。
- **B5 繰越 register の分類**: B6_REQUIRED 2 件（B4 繰越 #3 / #15）、B6_RELEVANT_BUT_DEFER 4 件、
  OUTSIDE_B6 7 件、POLICY_LOCKED 1 件（RR-3）、OPTIONAL 1 件、HISTORICAL_ONLY 1 件。
  **B5 RR-3 POLICY LOCK を明示的に継承**しつつ、execution gate 自体は B6 の scope に含めない
  （Monitoring と execution authority を混同しない）。

## v5.23 (2026-09-22) — Phase 6 P6-B5 closeout audit（docs のみ）

B5A → B5B → B5C → B5C-R1 → B5D-RERUN を 1 つの系として監査した完了監査。**READ-ONLY / DOCS-ONLY** で、
runtime・test・既存 B5 doc・knowledge・config・workflow・公開出力はいずれも無変更。新規 doc と本 CHANGELOG のみ。
判定は `P6_B5_COMPLETION_AUDIT_PASS_WITH_NON_BLOCKING_DEFERRED_ITEMS`。blocker は無い。

### 追加 — `docs/databank/PHASE6_THEME_B5_COMPLETION_AUDIT.md`【新規】

- **authority map**: 意味論 contract / B5B relation authority / B5C 提案 authority / 人間の決定 authority /
  決定に埋め込まれた出典主張確認 / 派生 plan / 未実装の実行 gate を層として分離し、
  「提案 ≠ authority」「ACCEPT ≠ authority」「確認 ≠ authority」「plan ≠ authority」
  「B5C は B5B に append しない」「RULE / LLM の出自 ≠ HUMAN の出自」「SOURCE_ASSERTED ≠ 客観的真実」を明示。
- **B5A 照合**: 監督者決定 B5-D1〜D10 をすべて実装と突き合わせ、意図的な逸脱 1 件（B5-D1 の file 名が
  `relations.jsonl` ではなく `relation_assertions.jsonl` / `relation_governance.jsonl` として確定したこと）を記録。
- **B5B / B5C 監査**、**R1 の欠陥と remediation**、**B5D-RERUN の結果**、
  **人間の統治 flow 5 本**（撤回済み関係が ACCEPT だけで復帰しないことを実機確認）、
  **保証しないことの明示**（出典の真実性 / 自動意味論検証 / 相関から因果 / 共起・taxonomy・entity・時間近接・
  graph 経路から関係）、**identity 監査**、**時間軸 7 種の PIT 監査**、
  **永続化 map**（永続 authority 4 file と派生 4 種を分離。出典主張確認は決定 record の一部であり独立 journal を持たない）、
  **依存方向**（B5C は B5B の model / resolution を read-only 参照するが `relation_store` を import しない。
  Foundation は B5 を import しない。循環なし）。
- **RR-1 / RR-2 を NON_BLOCKING_DEFERRED、RR-3 を POLICY_LOCKED / FUTURE_GATE_REQUIRED** として確定。
  将来の実行 gate は渡された plan object を信頼せず、authoritative な提案と決定から再導出するか同等の
  不変条件を完全に再検証すること。
- **B5 繰越 register の正本**（D3〜D5 / RR-1〜RR-3 / 実行 gate / 実世界精度測定 / 自動発見 / 意味論 verifier /
  所在の表記規約 / B4 繰越 #17 / B5A の語彙・世界時間・移行 gate）。

## v5.22 (2026-09-22) — Phase 6 P6-B5D-RERUN 再検証 gate（test ＋ doc のみ）

B5C-R1 に対して B5D の敵対的 gate を独立に再実行した。**runtime は 1 byte も変更していない**
（`src/` の diff は R1 anchor に対して 0）。B5B・Foundation・B1〜B4・P4・P5・config・workflow・公開出力も無変更。
判定は `P6_B5D_RERUN_VALIDATED`。B5D が示した SOURCE_ASSERTED の authority laundering blocker は
構造的に閉じており、HUMAN_ASSERTED・決定 graph・提案 provenance・PIT 決定性・store の fail closed 挙動・
先行凍結面のいずれにも退行は無い。

### 追加 — `tests/intelligence/test_theme_relation_rerun.py`【新規】

- 受理述語の一意性: 決定の構築 / 解決 / plan 構築 / 直列化と復元 / store load / 適格判定の各 runtime 経路を
  列挙し、2 つ目の弱い述語が無いことを固定。R1 前の `source_authority_available` は `src/` 全体で呼び出し 0 件。
- A〜N matrix を bridge と store の両方で再実行し、正確な失敗 code を固定。
- RULE / LLM 抽出 matrix（出典裏付き ＋ 人間の確認 → 許可、citation を貼っただけ → 拒否）と、
  提案者 class が plan provenance に保存され HUMAN に書き換えられないことの確認。
- 確認の identity と再利用、帰属 / citation の束縛（正規化の境界・publisher 等価推定の不在・
  複数 citation のうち確認された 1 件）、所在 contract、時刻の包含境界と ±1 マイクロ秒、
  決定 graph の不変、HUMAN_ASSERTED の非退行、B5B 互換性、authority 非改変、因果安全性 corpus、
  推移的推論の不在、収束の不変、store の fail closed（改ざんされた確認 record を含む）、
  import / 自動化の境界。116 test。

### 改善 — `docs/databank/`

- `PHASE6_THEME_RELATION_PROPOSAL_CONTRACT.md`: 帰属一致の正確な意味を明記した。
  `normalize_text`（NFKC → 空白圧縮 → strip → casefold）を両辺に適用したうえでの完全一致であり、
  citation・端点・関係型は正規化せず値の完全一致である。
- `PHASE6_THEME_RELATION_E2E_AUTHORITY_GATE.md`: 付録 §18 に再検証の結果と findings を追記。

### findings（いずれも NON-BLOCKING・本 gate では未修正）

- RR-1: `relation_proposal_store.py` の module docstring だけが R1 前の文言のまま。実行経路は正しい。
  本 gate は `src/` を変更できないため、docstring のみの後続修正として申し送る。
- RR-2: 復元経路の naive 時刻が素の `ValueError` になる（既存の `from_iso` 規約。fail closed で bypass ではない）。
- RR-3: `RelationAssertionPlan` は値 object で自前の検査を持たない。将来の実行 gate は渡された plan を
  信頼せず、提案と決定から再導出するか再検査すること。

## v5.21 (2026-09-22) — Phase 6 P6-B5C-R1 出典主張の確認（SOURCE_ASSERTED remediation）

B5D が示した欠陥（`SOURCE_ASSERTED` の適格判定が「帰属 field が非 None ＋ citation 1 件以上」という
構造的存在だけで成立し、「出典がその関係を主張した」ことと「citation が存在する」ことを区別できない）を
閉じる narrow remediation。**意味論を機械が判定する機構は導入していない。** 人間が確認した事実を
record として要求する。B5B relation authority は無変更。Foundation・B1・B2・B3・B4 も無変更。
config・workflow・公開出力・P4・P5 も無変更。提案 identity と store の収束挙動は B5D の判定どおり据え置き。

### 追加 — `src/intelligence/theme_intelligence/relation_proposal_model.py`

- `SourceClaimVerification`: 人間が「引用した出典のこの箇所が、この関係を述べている」と確認した不変 record。
  出典の帰属 / citation（kind ＋ ref id）/ 主張の所在 / 主張の要約 / 両端点 / 関係型 / 確認者 / 確認時刻を
  1 つに束ね、別の出典・別の citation・別の Theme・別の関係型へ使い回せない。確認者は HUMAN 固定。
  汎用の真偽 flag は持たない。長文引用を要求せず、短い所在と要約だけを記録する。
- `source_asserted_refusal(proposal, decision)`: `SOURCE_ASSERTED` 受理の単一述語。store と bridge が共有する。
  `SOURCE_ASSERTED_REFUSAL_CODES` として 9 種の拒否理由を凍結した。
- 凍結文言 `SOURCE_CLAIM_VERIFICATION_MEANING` / `SOURCE_CLAIM_VERIFICATION_NON_MEANING` /
  `CITATION_PRESENCE_IS_NOT_SOURCE_AUTHORITY`。

### 改善 — `relation_proposal_model.py` / `relation_proposal_store.py` / `relation_proposal_bridge.py`

- `RelationProposalDecision` が `source_claim_verification` を持つ。`SOURCE_ASSERTED` の ACCEPT では必須、
  それ以外では禁止。確認時刻は決定時刻を超えられない。確認は決定の identity payload に入るため、
  所在の違う 2 つの ACCEPT が黙って同一視されない。確認は提案ではなく決定に束ねる
  （提案は「何が提案されたか」、決定は「人間が何を authorize したか」）。
- store と bridge の `SOURCE_ASSERTED` 検査を `source_asserted_refusal` へ一本化した。
  従来の `FORBIDDEN_SOURCE_AUTHORITY` は、原因を名指しする 9 種の code に置き換わった。
- `RelationAssertionPlan` に `verification_origin`（`RelationVerificationOrigin`）を追加。
  誰が / どの出典を / どの citation の / どの所在で / どの関係意味論を / いつ確認したか、および
  authorize した決定を監査できる。凍結文言を併記し「客観的真実の検証」とは読ませない。

### 改善 — tests / docs

- `tests/intelligence/test_theme_relation_proposal.py`: 確認 model の matrix 80〜95 を追加（16 test）。
- `tests/intelligence/test_theme_relation_e2e.py`: B5D の case A〜F を R1 の期待値へ更新し、
  不一致 matrix G〜N（確認の出典 / citation / source root / target root / 関係型 / 非人間確認者 /
  決定より後の確認 / 別意味論への使い回し）を追加（31 test）。
- `tests/intelligence/test_theme_relation_causal_safety.py`: corpus 行の拒否 code を R1 に合わせた。
- `docs/databank/PHASE6_THEME_RELATION_PROPOSAL_CONTRACT.md`: §6 / §11 / §20 を更新し、
  付録 §24 に確認 model・配置・identity・意味の境界・B5B 互換性を追記。
- `docs/databank/PHASE6_THEME_RELATION_E2E_AUTHORITY_GATE.md`: §17 に remediation 結果の付録を追記。

### 残る限界

人間は誤った確認を行いうる。系はそれを検出しない。R1 が閉じたのは「構造だけ整えた提案が、人間の明示的な
確認なしに `SOURCE_ASSERTED` になる」経路であって、「出典が真にその関係を述べている」ことの保証ではない。

## v5.20 (2026-09-22) — Phase 6 P6-B5D relation E2E / authority laundering / 収束 gate（test ＋ doc のみ）

B5B relation authority と B5C 提案・決定層の鎖を `RelationAssertionPlan` まで通す敵対的 gate。
**runtime は 1 byte も変更していない**（test / doc / CHANGELOG のみ）。B5B authority への追記は本 gate に存在しない。
Foundation・B1・B2・B3・B4・B5B・B5C の runtime と knowledge、P4・P5、config・workflow・公開出力はいずれも無変更。

判定は `P6_B5C_REMEDIATION_REQUIRED`。`SOURCE_ASSERTED` の適格判定が構造的存在（帰属 field が非 None ＋
citation 1 件以上）だけで成立し、「出典が relation semantics を主張した」ことと「citation が存在する」ことを
区別できないため。詳細と監督者の決定事項は gate doc を参照。

### 追加 — `tests/intelligence/`

- `test_theme_relation_e2e.py`【新規】: 提案 → 人間の決定 → plan の鎖（plan で停止）、
  authority laundering matrix（4 提案者 class × 2 受理 class ＋ case A〜F）、B5C 報告 §8 の述語一致、
  提案収束 matrix（5 case ＋ 冪等 replay ＋ created_at）、決定 graph の敵対的集合（fork / 複数 genesis /
  dangling / 別 proposal / cycle / 11 seed の順序不変性）、訂正と governance の相互作用（撤回済み関係は
  ACCEPT だけで復帰しない）、PIT と決定論、store の破損と conflict、
  Foundation 5 authority ＋ B5B 2 authority の byte 同一性。113 test。
- `test_theme_relation_causal_safety.py`【新規】: 14 行の合成因果 corpus（**synthetic gate result only**）、
  自動的な関係発見の不在、推移的 authority の不在（`A CAUSES B` ＋ `B CAUSES C` から `A CAUSES C` は生まれない）。
  70 test。

### 追加 — `docs/databank/`

- `PHASE6_THEME_RELATION_E2E_AUTHORITY_GATE.md`【新規】: `SOURCE_ASSERTED` の意味論監査（GAP 3 点）、
  B5C 報告 §8 の決着（矛盾ではなく同一述語の 2 分岐）、収束判定（intentional and operationally safe。
  B4C との差異は producer 層の有無であって identity 規則ではない）、因果安全性 corpus、
  運用契約の明確化（check-then-reuse）、監督者の決定事項 B5D-D1〜D6。

## v5.19 (2026-09-21) — Phase 6 P6-B5C relation 候補と人間の決定（contract ＋ implementation）

B5B relation authority の直前に立つ提案・決定層を追加した。提案も ACCEPT も plan も authority ではなく、
B5B への追記は本 gate に存在しない。Foundation・B1・B2・B3・B4・B5B の runtime と knowledge、P4・P5、
config・workflow・公開出力はいずれも無変更。関係の自動生成は実装していない。

### 追加 — `src/intelligence/theme_intelligence/`

- `relation_proposal_model.py`: 不変の `RelationProposal`（提案 type は RELATION_CANDIDATE の 1 つ）と
  `RelationProposalDecision`（ACCEPT / REJECT / DEFER の 3 つ、actor は HUMAN 固定）。提案者 class は
  HUMAN / SOURCE / RULE / LLM で、これは「誰が提案したか」であり authority の主張 class ではない。
  提案 identity は候補となる主張そのもので、発見機構（提案者）と created_at を含まない。出典の帰属は
  意味を変えるため identity に入る。ACCEPT は最終 authority（HUMAN_ASSERTED / SOURCE_ASSERTED）を明示する。
  自己辺は提案段階で拒否する。
- `relation_proposal_resolution.py`: decision chain を predecessor graph だけで解く純関数。latest-wins は無く、
  fork / 複数 start は OPEN_UNRESOLVED、dangling / 別 proposal 参照 / 閉路は INVALID_DECISION_HISTORY。
- `relation_proposal_bridge.py`: 受理済み候補 → 不変の `RelationAssertionPlan`。plan は journal identity を持たず
  永続化しない。SOURCE_ASSERTED は提案に出典の帰属と citation が実在する場合のみ許し、提案者が RULE / LLM で
  あることは出典の権威の代わりにならない（authority laundering の禁止）。CAUSES は evidence 必須。
  端点は呼び出し側の read-only lookup が答え、退役 / 後継でも書き換えない。既存 authority と同内容なら
  RELATION_ALREADY_AUTHORITATIVE、撤回済みなら RELATION_RETRACTED_REQUIRES_GOVERNANCE で fail closed。
  NEW_RELATION と CORRECTION を明示し、訂正の predecessor は推測しない。
- `relation_proposal_store.py`: `relation_proposals.jsonl` と `relation_proposal_decisions.jsonl` の
  2 authority を持つ追記専用 store。冪等 / 衝突 / 破損 fail closed / 修復なし / single writer / 明示 data_root。
  決定の追記時に対象 proposal の実在・chain の非分岐・SOURCE_ASSERTED 受理の資格を検査する。

### 追加 — tests / docs

- `tests/intelligence/test_theme_relation_proposal.py`（40 件）と
  `tests/intelligence/test_theme_relation_proposal_store.py`（19 件）。
- `docs/databank/PHASE6_THEME_RELATION_PROPOSAL_CONTRACT.md`。

### 改善

- `tests/intelligence/test_theme_intelligence_import_boundary.py` を additive に拡張（B5C module の列挙、
  IO / identity module、相対 import の許可、runtime closure、提案層が B5B の追記 API に到達しないことの検査）。

## v5.18 (2026-09-21) — Phase 6 P6-B5B Theme relation authority（contract ＋ implementation）

Theme root どうしの意味論的関係を記録する別 authority を追加した。Foundation・B1・B2・B3・B4 の runtime と
knowledge、P4・P5、config・workflow・公開出力はいずれも無変更。関係の提案層（B5C 以降）・関係の自動生成・
graph の順位付けは実装していない。

### 追加 — `src/intelligence/theme_intelligence/`

- `relation_model.py`: 不変の `ThemeRelationAssertion` と `ThemeRelationGovernanceEvent`。関係語彙は
  CAUSES / AMPLIFIES / MITIGATES / DEPENDS_ON の 4 型ちょうど（すべて有向）。authority になれる主張 class は
  HUMAN_ASSERTED / SOURCE_ASSERTED の 2 つちょうどで、rule / LLM に相当する値を持たず、記録者は HUMAN 固定。
  CAUSES は両 class とも evidence 参照必須。SOURCE_ASSERTED は帰属と citation 必須。自己辺は禁止。
  identity は内容から決まる content id（`threl_` / `thrgov_`）で、provenance と recorded_at は identity の外。
  辺 key は derived で、同じ関係履歴に属する assertion をまとめる。
- `relation_resolution.py`: 純 PIT resolver。chain は predecessor graph だけで解き、fork / 複数 start は
  UNRESOLVED、dangling / 閉路 / 非単調 / 不正な governance 列は INVALID_HISTORY。両端点の Theme root が
  cutoff までに存在することを要求し、ThemeObservation の解決は要求しない。端点判定は呼び出し側が渡す
  read-only lookup が答える（Foundation store を読まない）。
- `relation_graph.py`: 記述的な read view（outgoing / incoming / neighbors / relations_between /
  relations_by_type）。順位付け・score・中心性・推奨を持たず、推移的に導出した辺を作らない。撤回辺は
  既定の active 集合から外れ、明示要求でのみ返る。
- `relation_store.py`: `relation_assertions.jsonl` と `relation_governance.jsonl` の 2 authority を持つ
  追記専用 store。canonical 行のみ・冪等・同 id 異 bytes は CONFLICT・破損は fail closed・修復なし・
  single writer・明示 data_root。分岐 append を許さない。store 経由の解決は破損を status として返す。

### 追加 — tests / docs

- `tests/intelligence/test_theme_relation.py`（41 件）と `tests/intelligence/test_theme_relation_store.py`（21 件）。
- `docs/databank/PHASE6_THEME_RELATION_AUTHORITY_CONTRACT.md`。

### 改善

- `tests/intelligence/test_theme_intelligence_import_boundary.py` を additive に拡張（B5B module の列挙、
  IO / identity module、相対 import の許可、runtime closure、凍結 module が relation authority を
  import しないことの検査）。

## v5.17 (2026-09-21) — Phase 6 P6-B5A Theme relation graph 読み取り専用 architecture 監査（docs のみ）

Theme root どうしの意味論的関係を表す永続 relation graph の architecture を、読み取り専用で設計監査した。
runtime・test・knowledge・config・workflow・data・公開出力はいずれも無変更。graph runtime は実装していない。

### 追加

- `docs/databank/PHASE6_THEME_RELATION_GRAPH_AUDIT.md`: Foundation lineage との素な分離と強制方法、
  relation authority の 4 案比較（別 append-only authority を推奨）、assertion ＋ governance event の
  二層 record model と identity / 辺 key の区別、MVP 語彙 4 型（CAUSES / AMPLIFIES / MITIGATES / DEPENDS_ON。
  RELATED_TO 不採用、PARENT_OF は MVP 外）、因果安全性（出典の主張の記録と系の推論の区別、RULE / LLM は提案止まり）、
  提案 architecture、方向性と derived 逆辺、自己辺 / 重複辺、訂正 / 撤回、PIT の端点意味論、lifecycle 非干渉、
  merge / split の自動移行禁止、evidence 要求、taxonomy / entity は hint のみ、discovery 非拡張、
  記述的 query 面（順位付けなし・推移的導出辺なし）、循環意味論、数値強度の不採用、歴史資産の分類、
  package 境界、永続化規律、公開境界、失敗語彙 17 種、将来 test matrix 32 項目、監督者決定 B5-D1〜D10。

### 検証結果

- 凍結面（Foundation / B1 / B2 / B3 / B4B / B4C / B4D / B4E / P4 / P5）の diff はすべて 0。
- 監督者決定 10 件はいずれも Foundation / B3 / B4 の変更を必要としない。

## v5.16 (2026-09-20) — Phase 6 P6-B4 完了監査（docs のみ）

B4A〜B4E の読み取り専用の完了監査を実施し、結果を 1 本の監査 doc にまとめた。runtime・knowledge・test・config・
workflow・公開出力はいずれも無変更。繰延項目の解消も行っていない。

### 追加

- `docs/databank/PHASE6_THEME_B4_COMPLETION_AUDIT.md`: authority map（versioned knowledge / derived discovery output /
  proposal authority / derived bridge output / Foundation authority）と境界の証明、B4A の D-B4-1〜10 の照合、
  B4D の D-B4D-1〜5 ＋ FC-1 と B4E の D-B4E-1〜4 の確定記録、identity 監査、8 つの時間軸の PIT 監査、
  source origin と独立性の監査、false positive 監査、人間 governance 監査、dedup 監査、knowledge version 監査、
  機密監査、import / 依存監査（循環なし）、永続化監査、繰延項目の canonical 登録簿 17 件、凍結面監査、
  test / guard の件数、完了条件の照合。

### 検証結果

- Foundation authority は discovery → 提案 → 人間 ACCEPT → attachment plan の全段階を通しても byte 単位で不変。
- 逆方向の依存（Foundation / B1 / B2 / B3 / P4 / P5 / 公開 bundle → B4）は 0 件。循環依存なし。
- 凍結面（Foundation / B1 / B2 / B3 runtime / B4B / B4C / B4D / B4E / P4 / P5）の diff はすべて 0。
- 自動の Theme 作成・evidence 付与・decision 追記・勝者選択・順位付けはいずれも実装に存在しない。
- 繰延 17 件を NON_BLOCKING / FUTURE_GATE_REQUIRED / OPTIONAL / POLICY_LOCKED で分類して登録した。

## v5.15 (2026-09-20) — Phase 6 P6-B4E 受理済み evidence 候補 → Foundation attachment plan（計画境界）

人間が ACCEPT した `EvidenceCandidateProposal` から、後で Foundation の `EvidenceAttachment` を組み立てるための
不変 plan を導く純関数を追加した。Foundation への追記・observation の改訂・root 生成・governance event・
proposal / decision 履歴の変更・discovery / lifecycle / 資格判定の実行は一切行わない。Foundation・B1・B2・B3 runtime・
B4B / B4C の runtime と knowledge・B4D の test / docs・P4・P5・config・workflow・公開出力は無変更。

### 追加 — `src/intelligence/theme_intelligence/`

- `evidence_bridge_model.py`: `EvidenceAttachmentPlan`（frozen。content id を持たず永続化しない）、提案の出自
  `ProposalOrigin` と受理の `DecisionOrigin`、`EvidenceBridgeError`、橋渡し可能な役割（SUPPORTS / CONTEXT）、
  役割 authority は HUMAN 固定、authority class は PRIMARY_OBSERVATIONAL 固定。`to_plain()` / `canonical_line()` は決定論的。
- `evidence_bridge.py`: `plan_evidence_attachment_from_accepted_proposal(proposal, decisions, *, target_resolution,
  created_at, consequence_ref=None, invalidation_ref=None)`。B3 の decision chain resolver をそのまま使った受理判定、
  明示 Foundation root のみを対象にする検証、SUPPORTS の consequence ref 必須 ＋ 実在検査、CONTEXT の consequence 禁止、
  invalidation の全面禁止、重複 attachment key の fail closed、時刻の前後関係（等号は許可）、参照 identity の完全保存。

### 追加 — tests / docs

- `tests/intelligence/test_theme_evidence_bridge.py`（40 件）: 実 Foundation world の read-only resolution を対象に、
  受理状態 6 種・proposal type・対象規則・resolution 状態 4 種・consequence / invalidation / 役割・時刻境界・
  重複・保存・provenance・決定性（10 seed の decision 順入れ替え）・無変更（authority bytes / proposal / resolution）・
  source / import 境界を固定する。
- `docs/databank/PHASE6_THEME_EVIDENCE_BRIDGE_CONTRACT.md`。

### 改善

- `tests/intelligence/test_theme_intelligence_import_boundary.py` を additive に拡張（B4E module の列挙・
  `.evidence_bridge_model` の許可・runtime closure・Foundation 実行 API 非参照の検査対象に追加）。

## v5.14 (2026-09-20) — Phase 6 P6-B4D Theme discovery E2E ＋ false-positive gate（検証のみ）

B4C の discovery 層に対する敵対的 E2E gate を追加した。test と docs だけを追加し、runtime（discovery module、taxonomy /
entity catalog / discovery rules の公開 snapshot）・Foundation・B1・B2・B3・B4B・P4・P5・config・workflow・公開出力は無変更。
期待値は `discover()` の出力の snapshot ではなく、契約から独立に authoring した golden fixture である。

### 追加 — tests

- `tests/intelligence/test_theme_discovery_e2e.py`: 35 件の golden case corpus（正例 8、L2 攻撃 6、entity lifecycle 4、
  taxonomy 階層 4、negative predicate 2、source origin 4、PIT 2、機構 firewall 3、MIN_DISTINCT 2）と、
  EvidenceCandidate / ThemeCandidate を別々に数える混同行列（group 別内訳つき）。機構 firewall、矛盾 rule の非仲裁、
  proposal id の収束と分岐、decision 履歴 4 状態の抑制、ThemeResolution との exact dedup、FC-1（Foundation OTHER 使用数）、
  score / rank / 独立 source 主張の不在、成果物の機密 token 検査。
- `tests/intelligence/test_theme_discovery_false_positive.py`: L2 正規化攻撃（別語内の部分文字列、句読点、NFKC、casefold、
  空白、最長一致、alias 反復、URL / author のみ、context alias）、taxonomy 階層（親子非伝播、多親、deprecated slug）、
  entity lifecycle（rename / ticker 変更 / supersession / inactive / ambiguous）、negative predicate stress、
  MIN_DISTINCT 4 次元の stress。
- `tests/intelligence/test_theme_discovery_replay.py`: cutoff 等号は可・1 マイクロ秒超過は除外（入力 4 種 ＋ knowledge 3 種）、
  旧 version に pin した replay、旧 ruleset × 新 knowledge の pin 不一致、10 seed の入力 shuffle・既存 proposal / decision の
  shuffle・knowledge 再読み込みでの proposal id / canonical bytes / run report 一致、run report 順序の canonical 性。

### 追加 — docs

- `docs/databank/PHASE6_THEME_DISCOVERY_E2E_GATE.md`: corpus の構成、golden 期待値の作り方、group 別混同行列、
  L1 / L2 結果、taxonomy 階層・entity lifecycle・source origin・機構 firewall・negative predicate・MIN_DISTINCT の結果、
  proposal id 収束、decision 履歴、dedup、PIT / replay、FC-1、限界、supervisor 決定事項（D-B4D-1〜5）。

### 検証結果

- ThemeCandidate の false positive 0、EvidenceCandidate の false positive 0。
- ThemeCandidate の false negative は 1 件のみで、L2 だけの theme 的文面に対する意図的な fail closed
  （診断 `THEME_CANDIDATE_REQUIRES_L1_HIT`）。
- 生成された THEME_CANDIDATE 9 件はいずれも Foundation の OTHER category を必要としない。
- 数値は合成 corpus 上の契約適合の計数であり、実運用の precision / recall の推定ではない。

## v5.13 (2026-09-20) — Phase 6 P6-B4C deterministic Theme discovery（contract ＋ implementation）

許可された構造化入力（SourceDocument / NewsItem / usable Fact / market Observation）から、B3 の EvidenceCandidateProposal /
ThemeCandidateProposal と derived な DiscoveryRunReport を決定論的に生成する discovery 層を追加した。Theme root を作らず、
Foundation / ProposalStore に書かず、decision を変えず、EvidenceCandidate を自動 promotion せず、fuzzy / LLM / score / rank を
持たない。ruleset は B4B と同じ VERSIONED KNOWLEDGE で taxonomy / catalog version を正確に pin する。
Foundation・B1・B2・B3・B4B runtime・P4・P5・config・workflow・公開出力は無変更。

### 追加 — `src/intelligence/theme_intelligence/`

- `discovery_model.py`: ruleset / rule / predicate / template（subject / mechanism / scope / invalidation / limitation）の純 model と
  検証（rule_id 不変、SUPPORTS / CONTEXT のみ、THEME rule は template 完全 ＋ PERIOD_FRAME 1 個 ＋ invalidation ≥ 1、binding
  `${entity}` / `${entity.<attr>}` / `${series}` の一意性）、`DiscoveryInputRecord`、`RuleEvaluation` / `DiscoveryRunReport` /
  `DiscoveryResult`。certainty は authoring 不可（HYPOTHESIZED_MECHANISM 固定）。
- `discovery_predicates.py`: ALL / ANY / NOT / ENTITY_PRESENT / TAXONOMY_SIGNAL / FACT_TYPE / OBSERVATION_SERIES / SOURCE_KIND /
  MIN_DISTINCT（入力単位と rule 単位）の評価。件数は充足だけを決め、親 slug は数えない。
- `discovery_rules.py`: `load_discovery_rules_version(path, *, expected_version, cutoff, taxonomy, entity_catalog)`（version / cutoff /
  digest / pin 一致 / ACTIVE rule の deprecated taxonomy・retired / superseded entity・未知参照・binding 属性を fail closed）。
- `discovery_adapter.py`: 4 入力 model → 共通 record。L1（明示 entity ref / identifier / fact_type / series / source kind）と L2
  （headline / title / summary に対する alias の正規化完全一致。longest alias wins、本文非走査）。source origin の保守的導出
  （同一記事の NewsItem / SourceDocument / Fact は同じ origin。独立数は数えない）。cutoff 後に知り得た入力・USABLE でない Fact は除外。
- `discovery.py`: `discover(inputs, *, taxonomy, entity_catalog, ruleset, cutoff, run_created_at, existing_proposals, existing_decisions,
  theme_resolutions, include_dedup)`。negative predicate による除外、集約 MIN_DISTINCT、EVIDENCE_CANDIDATE（rule 非依存の canonical
  reason）、THEME_CANDIDATE（L1 hit 必須、template ＋ binding ＋ 同一 rule 内集約）、等価提案の rule 跨ぎ収束、既存 id の抑制と
  decision 状態の診断、B3 exact dedup の任意呼び出し、run report。

### 追加 — knowledge / tests / docs

- `knowledge/theme_intelligence/discovery_rules.0.1.0.yaml`（pins taxonomy 0.2.0 / catalog 0.2.0。L1 entity・L2 alias・FACT_TYPE・
  OBSERVATION の evidence rule、negative ＋ MIN_DISTINCT 付き THEME rule、同 template の収束用 rule、DEPRECATED rule。generic のみ）。
- `tests/intelligence/test_theme_discovery_rules.py`（matrix 1〜14）、`test_theme_discovery.py`（15〜68）、
  `test_theme_discovery_boundary.py`（74〜79）。`test_theme_intelligence_import_boundary.py` と
  `test_theme_taxonomy_entity_boundary.py` を additive に拡張（B4C module の列挙・入力 model module の許可・ruleset file の同居）。
- `docs/databank/PHASE6_THEME_DISCOVERY_CONTRACT.md`。
- full suite 1846 passed（xfail 0 / skip 0）。

## v5.12 (2026-09-20) — Phase 6 P6-B4B Theme taxonomy ＋ entity catalog（versioned knowledge）実装

B4C discovery の前提となる決定論的 normalization knowledge を追加した。taxonomy / entity catalog は **VERSIONED KNOWLEDGE**
（Foundation authority・proposal authority・evidence・governance ではない）で、`knowledge/theme_intelligence/` の不変 YAML
snapshot を明示 version ＋ cutoff ＋ content digest 照合でのみ読む。「latest」loader・現在時刻・書き込み・network はない。
Discovery・rule・proposal 生成・bridge・LLM・graph・monitoring は含まない。Foundation・B1・B2・B3 runtime・P4・P5 は無変更。

### 追加 — `src/intelligence/theme_intelligence/`

- `knowledge_loader.py`: 共通 primitive（`KnowledgeError`、`KnowledgeProvenance`、version 解析、`normalize_token` ＝ NFKC /
  空白圧縮 / casefold、canonical JSON、sha256 content digest、published_at / date 解析）と strict YAML loader（重複 key・
  複数 document・非 mapping を拒否、unknown field / 型不一致は fail closed）、envelope 検証、version / cutoff / digest gate。
- `taxonomy_model.py` / `taxonomy.py`: `TaxonomyNode` / `TaxonomySnapshot`（DAG、multi-parent 可、RELATED edge なし、親の自動
  伝播なし、slug 不変、rename ＝ 新 slug ＋ deprecated_in_version / superseded_by、alias 所有の一意性、cycle 検出）、
  `load_taxonomy_version`、`resolve_taxonomy_token`（EXACT_SLUG / EXACT_ALIAS / DEPRECATED / AMBIGUOUS / UNKNOWN。fuzzy なし）、
  `validate_theme_taxonomy_refs`（Foundation METADATA TAXONOMY 値の純検証。書かない）。
- `entity_model.py` / `entity_catalog.py`: `EntityType` 9 種（Foundation `ThemeEntityKind` へ単射で写像。PERSON / TICKER /
  TECHNOLOGY / POLICY_PROGRAM は語彙外）、`EntityIdentifier`（TICKER / INSTRUMENT_ID / ISO_COUNTRY / ISO_CURRENCY、TICKER のみ
  期間非重複なら再利用可）、`EntityRecord`（`<kind>:<immutable-slug>`、safe / context alias ＋ context_terms、valid_from /
  valid_to、superseded_by、retired_in_version）、`EntityCatalogSnapshot`（alias 所有・shadow・identifier 衝突・lifecycle 検証）、
  `load_entity_catalog_version`、`resolve_entity_token`（EXACT_ID / EXACT_SAFE_ALIAS / CONTEXT_ALIAS / AMBIGUOUS / UNKNOWN /
  INACTIVE / SUPERSEDED。先頭選択・順位付けなし。後継への自動付け替えなし）。

### 追加 — knowledge / tests / docs

- `knowledge/theme_intelligence/theme_taxonomy.0.1.0.yaml` / `0.2.0.yaml`（historical slug 名 8 件の seed、0.2.0 で
  `supply_chain_theme` → `supply_chain` の rename via new slug）、`entity_catalog.0.1.0.yaml` / `0.2.0.yaml`（公開標準 entity
  と架空 MVP fixture company。0.2.0 で rename・ticker 変更・merger を表現）。顧客 watchlist・PERSON・信号語・Compass 文言なし。
- `tests/intelligence/test_theme_taxonomy.py`（matrix 1〜24）、`test_theme_entity.py`（25〜50）、
  `test_theme_taxonomy_entity_boundary.py`（55〜64）、`test_theme_intelligence_import_boundary.py` を additive に拡張。
- `docs/databank/PHASE6_THEME_TAXONOMY_ENTITY_CONTRACT.md`。
- full suite 1782 passed（xfail 0 / skip 0）。

## v5.11 (2026-09-19) — Phase 6 P6-B4A Theme taxonomy / entity / discovery architecture audit（docs only）

B4 runtime を設計する前の read-only 監査。runtime・tests・knowledge・config・workflow は無変更。Foundation・B1・B2・B3 は
凍結のまま（FOUNDATION / B1 / B2 / B3 CHANGE_REQUIRED いずれも NO。B3.1 候補は OPTIONAL_FUTURE として列挙）。

### 追加 — docs

- `docs/databank/PHASE6_THEME_TAXONOMY_ENTITY_DISCOVERY_AUDIT.md`: B3 intake surface の監査（proposal id は provenance を
  含まない ＝ rule 非依存 identity、`reason` は EVIDENCE_CANDIDATE の identity 内、knowledge pin の構造化 field 不在）、
  TaxonomyNode / EntityRecord 案、taxonomy content の置き場所比較（推奨: `knowledge/theme_intelligence/` YAML ＋ versioned code
  model）、entity type は Foundation `ThemeEntityKind` の部分集合 9 種（TECHNOLOGY / POLICY_PROGRAM は taxonomy / mechanism で
  表す）、entity id は `<kind>:<slug>` 不変 token（typed_reference が identity core に入るため）、historical 資産 12 件の
  PORT / REDESIGN / REFERENCE_ONLY / REJECT 再評価、discovery 入力 authority 表、proposal-only の出力 pipeline（自動 promotion
  NO）、rule model、rule versioning（proposer_ref ＋ rule_version で足りる）、matching level（L1 ＋ 限定 L2、L3 は B7）、
  mechanism assembly（template ＋ binding のみ、共起から CAUSES を作らない）、EvidenceCandidate bridge（別 gate B4E 推奨）、
  false positive containment、source independence、PIT / time、governance 境界、機密性、package 境界、sub-gate
  B4B / B4C / B4D / B4E、将来 test、監督者決定 D-B4-1〜10。

## v5.10 (2026-09-19) — Phase 6 P6-B3 Theme proposal journal ＋ dedup review 実装

「Theme 候補」「重複候補」「人間 review decision」を Foundation とは別の append-only proposal authority
（`<data_root>/theme_intelligence/proposals.jsonl` / `proposal_decisions.jsonl`）に記録する層を追加した。Proposal ≠ Theme:
proposal が存在しても ThemeRootRecord / ThemeObservation / governance は作られず、B3 は Foundation へ自動 write しない。
Foundation・B1・B2 runtime・P4・P5 は無変更。config / workflow / 公開出力の変更なし。

### 追加 — `src/intelligence/theme_intelligence/`

- `proposal_model.py`: `ThemeCandidateProposal`（A1 / A2 の Theme 定義を満たす構造。Foundation の純関数で semantic /
  identity core fingerprint を計算し保持値と照合）、`EvidenceCandidateProposal`、`DedupReviewProposal`（RULE のみ、exact class
  のみ）、`ProposalDecision`（HUMAN のみ、ACCEPT / REJECT / DEFER / NOT_DUPLICATE、`supersedes_decision_id`）。content id
  `thprop_` / `thdec_`（created_at / recorded_at / provenance は identity 外）。全 datetime は aware UTC・caller 注入。
- `proposal_store.py`: `ProposalStore`（明示 data_root、追記専用 JSONL、canonical 行、flush ＋ fsync、同 id 同 bytes 冪等 /
  異 bytes CONFLICT、破損 fail closed、byte 長で外部変更検知、read-only、修復 / migration / SQLite なし）。decision chain の
  validate-before-append（proposal 存在、種別別の許可 decision、predecessor の terminal 性、時刻単調性、fork 診断）。
- `proposal_resolution.py`: `resolve_active_decision`（predecessor graph のみ。唯一 terminal ＝ RESOLVED、fork / 複数 start ＝
  UNRESOLVED、dangling / cycle ＝ INVALID、時刻 / 物理順で選ばない）、`derive_proposal_status`（OPEN / OPEN_DEFERRED /
  OPEN_UNRESOLVED / ACCEPTED / REJECTED / CLOSED_NOT_DUPLICATE / INVALID_DECISION_HISTORY）、`derive_open_proposals`。
- `dedup.py`: `detect_exact_duplicates`（semantic fingerprint exact ＋ identity core fingerprint exact のみ。counterpart は
  RESOLVED な ThemeResolution と他の THEME_CANDIDATE。複数 exact は全列挙、score / rank / nearest / embedding なし、
  SCOPE / SUBJECT / MECHANISM / PARENT_CHILD の自動分類なし）。active NOT_DUPLICATE による derived suppression
  （同 subject fingerprint・同 basis・同 dedup model version の同 counterpart は再提示しない。fingerprint / version 変更で再提示）。
- `proposal_bridge.py`: `plan_theme_creation_from_accepted_proposal`（active ACCEPT の THEME_CANDIDATE だけを Foundation
  candidate 作成の材料 `ThemeCreationPlan` にする。root_id を持たず生成せず、`execute_candidate` / `ThemeStore.append_*` を
  呼ばない。plan に proposal id / decision id / actor の provenance）。

### 追加 — tests / docs

- `tests/intelligence/test_theme_proposal.py`（matrix 1〜30・40〜50）、`tests/intelligence/test_theme_dedup.py`（31〜39）。
- `tests/intelligence/test_theme_intelligence_import_boundary.py` を additive に拡張（B3 module の import 境界と closure、
  IO は proposal_store の追記のみ、operations / store 非 import、Foundation 非 write、root id 非生成、score / embedding token 不在）。
- `docs/databank/PHASE6_THEME_PROPOSAL_DEDUP_CONTRACT.md`。
- full suite 1723 passed（xfail 0 / skip 0）。

## v5.09 (2026-09-19) — Phase 6 P6-B2 Theme lifecycle view 実装

Foundation の `ThemeResolution` 1 つから 2 層の lifecycle snapshot（governance 層 ＋ evidence 層）を導く純 derived 層を
`src/intelligence/theme_intelligence/` に追加した（監督者決定 L-1〜L-8）。Foundation 7 file・B1 runtime（`change.py` /
`model.py`）・P4・P5 は無変更。journal・content id・config.yaml・workflow を持たない。B1 ChangeSet は入力にしない
（lifecycle ＝ snapshot、ChangeSet ＝ delta）。

### 追加 — `src/intelligence/theme_intelligence/`

- `lifecycle_model.py`: `GovernanceLifecycleState`（UNREVIEWED / ACCEPTED / REJECTED / RETIRED / MERGED / SPLIT / SUPERSEDED /
  UNRESOLVED / NOT_AVAILABLE）、`EvidenceConditionFlag`（NO_VISIBLE_EVIDENCE / HAS_CONTEXT_ONLY / HAS_SUPPORT / SINGLE_SOURCE /
  MULTI_SOURCE / SINGLE_EVIDENCE_DATE / MULTI_DATE / QUALIFIES / CONTESTED / INVALIDATION_EVIDENCE_PRESENT / STALE）、
  `LifecycleViewStatus`（AVAILABLE / PARTIALLY_AVAILABLE / UNAVAILABLE）、`EvidenceConditionStatus`（EVALUATED / UNRESOLVED /
  NOT_EVALUATED）、`LifecyclePolicy`（`stale_after_days`、既定 90 calendar days、`theme_lifecycle_policy:0.1.0`）、
  `ThemeLifecycleView`（`theme_lifecycle_view:0.1.0` / `theme_lifecycle_model:0.1.0`、policy 値を結果に保持）。
  勢い・方向・投資判断・総合評価・score / rank / tier の語は無い。
- `lifecycle.py`: `derive_lifecycle(resolution, *, policy, governance_events=None)`。governance 層は Foundation の
  `governance.status` / effective event / lineage だけから決める（独自 latest-wins なし。EVENT_REVERSED は resolver の
  畳み込み結果を使う。correction event が terminal のときは渡された governance event で chain を遡り、無ければ fail
  closed。merge / split / successor の result root は origin event だけでは UNREVIEWED）。evidence 層は Foundation の
  `DerivedView` / `EvidenceView` を再 count せず参照。STALE は最新 dated counted evidence の日付から cutoff の日付までの
  calendar 日数が `stale_after_days` 以上（89 日 false / 90 日 true）。dated counted evidence 0 件は STALE を付けず診断
  STALE_NOT_EVALUABLE_NO_DATED_EVIDENCE。NO_STATE / INVALID_HISTORY / STORE_CORRUPTION は UNAVAILABLE、governance または
  semantic の UNRESOLVED は PARTIALLY_AVAILABLE、metadata / mapping の UNRESOLVED は影響なし。

### 追加 — tests / docs

- `tests/intelligence/test_theme_lifecycle.py`（41 test。matrix 1〜37 ＋ 失敗入力）。
- `tests/intelligence/test_theme_intelligence_import_boundary.py` を additive に拡張（lifecycle module の import 境界と
  closure、P5 / 較正 / 価格 / production authority token の不在、Foundation 結果の再 count 禁止）。
- `docs/databank/PHASE6_THEME_LIFECYCLE_CONTRACT.md`（snapshot vs delta、2 層分離、governance state、evidence flag、
  freshness policy と STALE 境界、qualification 再利用、contradiction / invalidation、partial availability、
  NO_STATE / UNRESOLVED、除外、要確認事項、versioning、import 境界、tests）。

## v5.08 (2026-09-19) — Phase 6 P6-B1 Theme change detection 実装

Theme Foundation（凍結、anchor `12847bf`）の上に Theme Intelligence layer `src/intelligence/theme_intelligence/` を新設し、
その最初の module として change detection を実装した。2 つの点時刻再構成 `ThemeResolution(root, T1)` / `(root, T2)` を
比較し「Theme について何が変わったか」を決定論的な `ThemeChangeSet` で表す純 derived 層。authority ではなく journal に
保存しない。Foundation 7 file・P4 production bundle・P5 凍結 source / test は無変更。lifecycle / discovery / dedup /
graph / taxonomy / LLM / monitoring は含まない（監督者決定 D-B2〜D-B8）。

### 追加 — `src/intelligence/theme_intelligence/`

- `__init__.py` / `model.py`: `ThemeChangeSet`（frozen。schema `theme_change_set:0.1.0`、model `theme_change_model:0.1.0`）、
  `Change`、`ChangeKind` 語彙（ROOT_APPEARED / ROOT_BECAME_OBSERVED / OBSERVATION_REVISED / SEMANTIC_FIELD_CHANGED /
  EVIDENCE_ADDED・CARRIED・DROPPED・ROLE_CHANGED・REF_REVISED・ATTRIBUTE_CHANGED / NEW_SOURCE_ORIGIN・SOURCE_ORIGIN_LOST /
  NEW_EVIDENCE_DATE・EVIDENCE_DATE_LOST / QUALIFICATION_CHANGED / CONTRADICTION・INVALIDATION の APPEARED・CLEARED /
  GOVERNANCE・METADATA・MAPPING・LINEAGE_CHANGED / PENDING_APPEARED・CLEARED / SEMANTIC・FACET_BECAME_UNRESOLVED・RESOLVED /
  DEREFERENCE_CHANGED）、knowledge 軸（attached_at / recorded_at）と evidence-time 軸（evidence_time の window 関係）、
  `ChangeSetStatus`（COMPUTED / UNAVAILABLE）、`ThemeChangeError`。lifecycle / 強弱 / 方向 / score の語は無い。
- `change.py`: `compare_resolutions(before, after)`（主 authority）と `detect_changes(history, root_id, T1, T2,
  dereference_before, dereference_after)`（resolver 公開 entry point を 2 回呼ぶ wrapper）。attachment_key 対応、決定論的
  1:1 の role 訂正 / 上流 revision 対応（曖昧なら ADDED / DROPPED のまま）、carried evidence の区別、DerivedView の
  diversity 比較（origin grouping を再定義しない）、facet 独立、UNRESOLVED / NO_STATE / dereference の分離、T1 > T2・root
  不一致・resolver version 不一致は fail closed、INVALID_HISTORY / STORE_CORRUPTION は UNAVAILABLE な結果。

### 追加 — tests / docs

- `tests/intelligence/test_theme_change.py`（43 test。matrix 1〜42 ＋ 上流 revision 対応）、
  `tests/intelligence/test_theme_intelligence_import_boundary.py`（7 test。語彙 / score / IO・時計・乱数 / import 境界 /
  production closure / Foundation からの非参照）。
- `docs/databank/PHASE6_THEME_CHANGE_DETECTION_CONTRACT.md`（authority 境界・語彙・二軸・evidence 対応・diversity・
  qualification・contradiction / invalidation・facet 独立・UNRESOLVED / NO_STATE・dereference・決定論・除外・API・test・
  versioning）。

### 改善

- `tests/intelligence/test_theme_import_boundary.py`: 「他 package は themes を import しない」の走査から、D-B1 で
  Foundation の read-only surface を import してよい `theme_intelligence` だけを除外（その境界は新 boundary test が固定）。
- full suite 1640 passed（xfail 0 / skip 0）。

## v5.07 (2026-09-19) — Phase 6 P6-B0 Theme Intelligence 設計監査（docs only）

Theme Foundation（P6-A1〜A4d.1、anchor `12847bf`）は COMPLETE / CLOSED / FROZEN。その上に置く Theme Intelligence layer
（D10 graph / D11 lifecycle / D12 discovery / D13 dedup / D14 granularity、taxonomy / entity linkage / mechanism 語彙 /
monitoring / 支持・反証の推移 / change detection / human governance / LLM 境界）の設計監査を行った。runtime・test・
knowledge・config・workflow は無変更。historical branch の参考資産 11 件は read only（port / merge / cherry-pick なし）。

### 追加 — docs

- `docs/databank/PHASE6_THEME_INTELLIGENCE_ARCHITECTURE_AUDIT.md`（25 節）: Foundation の現能力と欠落能力、D10〜D14 の
  選択肢比較、taxonomy / entity / monitoring / evidence 推移 / governance / LLM / Phase 7 境界、historical 資産分類
  （PORT / REDESIGN / REFERENCE_ONLY / REJECT）、依存 graph、推奨実装順序（F: Change Detection → Lifecycle → Proposal ＋ Dedup →
  Taxonomy ＋ Entity ＋ Discovery（proposal-only）→ Graph → Monitoring runner ＋ index → LLM）、P6-B subphase 案、schema /
  interface 案、Foundation 変更候補（必須なし。FC-1 mechanism 語彙 version の複数受理は B4 前に再評価）、risk、
  後続 test / guard、次 gate 推奨（P6-B1 Change Detection）。

### 改善

- `docs/databank/PHASE6_FOUNDATION_DECISIONS.md` §14 に Foundation freeze と P6-B0 監査の参照を追記（決定内容は不変）。

## v5.06 (2026-09-19) — Phase 6 P6-A4d.1 Theme foundation BLOCKER 修正

A4d で発見した contract / implementation の不一致 3 件（A4D-1 / A4D-2 / A4D-3）を、`src/intelligence/themes/store.py` と
`resolver.py` だけの最小修正で解消した。model / fingerprint / qualification / revision / operations は無変更。
schema version・語彙 version・canonical payload・既存 id・authority file 名・load 順・既存 journal bytes は不変（migration なし）。
P4 production bundle・P5 凍結 source / test は無変更。

### 修正

- A4D-1: 同一 root 内で identity core（subject / driver / channel / domain）が変わる observation を store が受理していた。
  `store._validate_observation_chain` で predecessor と `identity_core_unchanged` を比較し、append は
  IDENTITY_CORE_CHANGED で拒否、既存 file 内の違反は load で INVALID_HISTORY。resolver も同じ不変条件を検査し
  INVALID_HISTORY を返す（勝者選択・自動 successor 化なし）。semantic 変更は引き続き同一 root の revision。
- A4D-2: METADATA_CORRECTION_APPROVED（related record ＝ metadata）を含む journal が固定 load 順のため再 open できなかった。
  related record 検査を `_validate_event_related` に切り出し、metadata 参照は第 2 pass（cross authority）で検査する。
  load 順・append 時の検査・governance の canonical bytes / id は不変。参照先不在 / 別 root / 時刻逆行は引き続き fail closed。
- A4D-3: 宣言済みだが RootRecord 未作成の result root を解決すると UNKNOWN_ROOT だけで PENDING_EVENT / lineage が付かず、
  後日の RootRecord が過去 T の診断を変えていた。resolver `_resolve` は T で可視な宣言 event を集め、宣言があれば
  NO_STATE ＋ ROOT_AFTER_CUTOFF（related ＝ 宣言 event）＋ PENDING_EVENT ＋ 宣言由来 lineage を返す（root / observation は None、
  未来の RootRecord / genesis を参照しない）。宣言の無い root id は従来どおり UNKNOWN_ROOT。同じ result root の二重宣言は
  RESULT_ROOT_REDECLARED として INVALID_HISTORY。

### 追加 — tests/intelligence

- `test_theme_foundation_remediation.py`（27 test）: A4D-1（driver / channel / domain / subject の append 拒否、semantic
  revision の受理、既存 file の違反の再 open 拒否、synthetic history の INVALID_HISTORY、successor 経路の有効性）、
  A4D-2（append / 再 open / read-only 再 open / audit、参照先不在・別 root・種別違い・時刻逆行の fail closed、bytes 不変）、
  A4D-3（merge / split / successor の未作成 result root の PENDING_EVENT ＋ lineage、完了後の同一 T の完全一致、宣言前 /
  未宣言 root の UNKNOWN_ROOT、宣言前の lineage 非漏洩、二重宣言の INVALID_HISTORY）。

### 改善

- A4d の strict xfail 5 件を通常 test に戻し、assertion を強化（宣言済み result root の診断・pending・lineage の完全一致、
  後段 stage 比較から A4D-3 key の除外を撤去）。`test_declared_result_root_diagnostics_do_not_depend_on_later_root_record`
  は xfail 下で 2 つ目の key が KeyError（stage 取り違え）になっていたため、各 checkpoint を最初に観測できた stage を
  明示して比較するよう修正。
- `docs/databank/PHASE6_THEME_FOUNDATION_INVARIANT_MATRIX.md`: 31 / 65 / 83 を BLOCKED → PROVEN、75 / 92 の注記を更新
  （PROVEN 81 / STRUCTURAL 13 / DEFERRED 3 / BLOCKED 0）。
- `docs/databank/PHASE6_THEME_PERSISTENCE_REVISION_CONTRACT.md` §34 に A4d.1 の修正状態を追記（契約の意味論は変更していない）。
- full suite 1590 passed（xfail 0 / skip 0）。

## v5.05 (2026-09-19) — Phase 6 P6-A4d Theme foundation E2E 検証（BLOCKER_FOUND）

A1〜A4c が canonical journal を通じて 1 つの system として動くことを E2E で検証した gate。runtime source
（`src/intelligence/themes/` の 7 file）は凍結のまま無変更。P4 production bundle・P5 凍結 source / test も無変更。
E2E で contract / implementation の不一致を 3 件発見したため、修正せず strict xfail で再現を固定し
**BLOCKER_FOUND** として停止した（freeze 宣言はしない）。

### 追加 — tests/intelligence

- `theme_foundation_fixtures.py`: 代表 E2E world（Theme A の T0〜T13: root → genesis → 独立 2 源の evidence →
  contradiction → label / taxonomy / mapping → 受理 → semantic revision → 遅延付与 → 上流改訂 → retire → 取消、
  Theme B、Theme A＋B → C の merge を crash 段階込みで記録）、checkpoint 別 snapshot、byte 単位 replay
  （依存順を守る 5 queue 併合）、resolution digest。
- `test_theme_foundation_e2e.py`: 時間旅行 checkpoint（literal 期待値）、再起動 / 再読込（別 process 含む）、
  correction / revision の区別、merge / split / successor、上流改訂（dereference のみ変化）、derived 値の
  非保存、A1 / A2 / A3 traceability。
- `test_theme_foundation_replay.py`: byte 単位 replay の再現、入力順 shuffle の決定論、後段 stage による
  過去 checkpoint の不変、future record matrix、後追い backdated root。
- `test_theme_foundation_failures.py`: candidate / merge / split / successor の crash → PENDING → 再開、
  fork の facet 隔離（observation / governance / label / mapping）、破損 data_root の fail closed
  （malformed / noncanonical / truncated / duplicate conflicting id / authority 欠落）。
- 新規 test は 47 passed ＋ 5 xfailed（strict。BLOCKER の再現）。

### 追加 — docs

- `docs/databank/PHASE6_THEME_FOUNDATION_INVARIANT_MATRIX.md`: 不変条件 1〜97 の layer / test / status 対応表
  （PROVEN 78 / STRUCTURAL 13 / DEFERRED 3 / BLOCKED 3）と BLOCKER 3 件の最小修正候補・影響範囲。

### 改善

- `docs/databank/PHASE6_THEME_PERSISTENCE_REVISION_CONTRACT.md` §33 に A4d の検証状態と BLOCKER を追記
  （契約の意味論は変更していない）。

### 未修正（BLOCKER。次 gate で修正）

- A4D-1: store が identity core の置換を同一 root の revision として受理する（A3 §7 / §23 は IDENTITY_CORE_CHANGED
  を要求）。候補: `store._validate_observation_chain` と resolver `_resolve` に fingerprint 比較を追加。
- A4D-2: METADATA_CORRECTION_APPROVED（metadata id を参照）を含む store が再 open できない（load 順により
  intra pass で GOVERNANCE_REFERENCE_MISSING）。候補: 当該検査を cross pass `_validate_event_results` へ移す。
- A4D-3: 宣言済み・未作成の result root を解決すると UNKNOWN_ROOT のみで PENDING_EVENT / lineage が付かず、
  後日の RootRecord が過去 T の診断を変える。候補: resolver `_resolve` の root 不在分岐にも宣言 event の
  PENDING_EVENT ＋ lineage 注釈を付ける。

## v5.04 (2026-09-19) — Phase 6 P6-A4c Theme point-in-time resolver 実装

A3 §13（D17）の点時刻再構成を実装した。resolver は canonical history の読み取り専用の解釈器であり、authority ではない。
lifecycle / discovery / dedup / graph / LLM / Compass・Brief・P5 連携 / SQLite / 修復 / append は含まない。
A4a / A4b の凍結 file、P4 production bundle、P5 凍結 source / test は無変更。開発 branch を
`claude/investment-intelligence-phase6`（A4b anchor から分岐）へ移行した。

### 追加 — `src/intelligence/themes/resolver.py`

- `resolve(history, root_id, cutoff)` / `resolve_from_store` / `resolve_at_data_root`（read-only）。cutoff は aware 必須。
- eligibility（root created_at / observation・governance・metadata recorded_at / mapping recorded_at ＋ valid_from /
  attachment evidence_time ＋ attached_at のすべて ≤ T）。T 後の record は影響しない。
- status: RESOLVED / NO_STATE / UNRESOLVED / INVALID_HISTORY / STORE_CORRUPTION、facet 別 status
  （NO_GOVERNANCE / NO_METADATA / NO_MAPPING / UNRESOLVED / NOT_EVALUATED）。潰さない。
- observation chain は predecessor graph のみで解決（fork / 複数 terminal ＝ UNRESOLVED、recorded_at 最大・物理順を
  使わない）。evidence view（visible / not_yet_attached / evidence_after_cutoff / context_without_time）。
- governance facet（chain、EVENT_REVERSED の畳み込みで effective event、取消の取消）、lineage 注釈（MERGED_INTO /
  MERGE_OF / SPLIT_INTO / SPLIT_FROM / SUPERSEDED_BY / SUCCESSOR_OF）、metadata field 別 facet、mapping facet
  （並行 chain 正当、fork のみ UNRESOLVED）。facet 間で曖昧を伝播しない。
- PENDING_GENESIS / PENDING_EVENT を T 時点の事実として診断（修復なし、後日完了は遡及しない）。
- carried evidence lineage（origin event の配分 ＋ byte 同一 attachment）、DERIVED（fingerprint / 資格判定 /
  DIRECTLY_EVIDENCED link）を visible evidence だけから A4a 純関数で再計算、caller 供給の upstream dereference。

### 追加 — tests/intelligence

- `test_theme_resolver.py` / `test_theme_resolver_facets.py`（cutoff 境界、遅延付与の非遡及、fork / latest-wins 否定、
  PENDING の保持、決定論と入力順独立、read-only、store failure の boundary、governance / reversal / merge / split /
  successor / metadata / mapping / lineage / dereference / facet 独立）。boundary test を resolver に拡張。

### 改善

- `docs/databank/PHASE6_THEME_PERSISTENCE_REVISION_CONTRACT.md` §32 に resolver の実装状態を追記。

## v5.03 (2026-09-19) — Phase 6 P6-A4b Theme canonical store 実装

A3 の永続化意味論を実装した。resolver / 点時刻状態 / lifecycle / discovery / graph / SQLite / LLM / Compass・P4・P5
連携 / 自動修復 / 歴史 port は含まない。production bundle（P4）・P5 凍結 source / test・A4a golden vector は無変更。

### 追加 — `src/intelligence/themes/store.py` / `operations.py`

- `ThemeStore`: `<data_root>/themes/` の 5 canonical authority（roots / observations / governance / metadata /
  series_mappings）を 1 writer が所有する追記専用 JSONL store。明示 data_root 必須（repository fallback なし）、
  `initialize`（唯一の file 作成）/ `open`（read-only load。作らない・書かない・直さない）/ `audit`。
- append: A4a canonical 行のみ、write → flush → fsync、byte 一致 ＝ 冪等 no-op、同一 id ＋ 異 bytes ＝ ThemeConflict
  （provenance / recorded_at の差でも）。validate-before-append（root / genesis、物理 predecessor・同一 root・
  recorded_at 非減少・物理 terminal、attached_at 範囲、governance の物理参照と result root 宣言、metadata / mapping
  の chain、evidence 配分）。file ごとの byte 長で外部増減を検知（SINGLE_WRITER の検知。lock ではない）。
- load: 非 canonical / 破損 / 未知 schema / id 不一致 / physical duplicate ＝ STORE_CORRUPTION（authority・行番号・
  reason code）、履歴として不可能 ＝ INVALID_HISTORY、file 上の fork ＝ 診断（選ばない・直さない。当該 root への append
  は FORKED_ROOT）。2 pass（同一 file / 先行 authority → 後続 authority 参照）。
- 宣言先行の論理操作: candidate（RootRecord → genesis）、MERGE / SPLIT / SUCCESSOR（event → 結果 root → 結果 genesis）。
  plan は全 id を事前確定し、同じ入力で冪等に再試行できる。PENDING_GENESIS / PENDING_EVENT を `pending()` で明示。
- carried evidence: 宣言 event の `evidence_allocation` が lineage を保持し、結果 genesis の attachment は source と
  byte 同一（元 attached_at / provenance 保持）、配分の部分集合のみ（暗黙 carry なし）。

### 追加 — tests/intelligence

- `test_theme_store.py` / `test_theme_store_corruption.py` / `test_theme_store_operations.py`（初期化・read-only・
  canonical bytes・fsync・冪等 / conflict・破損 11 区分・外部改変・INVALID_HISTORY・fork 診断・chain 規則・
  governance 参照・merge / split / successor の全 crash 境界での PENDING と再試行・配分違反・API 表面）。
- `test_theme_import_boundary.py` を store / operations に拡張（closure 11 module、IO は追記のみ、resolver / 時計 /
  乱数 / SQLite / repository fallback 不在）。

### 改善

- `docs/databank/PHASE6_THEME_PERSISTENCE_REVISION_CONTRACT.md` §31 に store の実装状態（authority path、append /
  冪等 / conflict、writer 保証、改変検知、初期化、PENDING、操作順序、失敗 code 台帳、A4c への繰越）を追記。

## v5.02 (2026-09-19) — Phase 6 P6-A4a Theme 土台 model 実装

Phase 6 Theme の **最初の runtime 実装 gate**。`src/intelligence/themes/` に純 model 層だけを追加した。
store / JSONL IO / resolver / SQLite / discovery / lifecycle / graph / LLM / Compass・Reports・P5 連携 / 歴史 port は
含まない。production bundle（P4）・P5 凍結 source / test は無変更。

### 追加 — `src/intelligence/themes/`（model.py / fingerprint.py / qualification.py / revision.py）

- A3 の 5 canonical record（ThemeRootRecord / ThemeObservation / ThemeGovernanceEvent / ThemeMetadataRecord /
  ThemeSeriesMapping）を frozen dataclass として実装（schema version `*:0.1.0`、fail closed の `ThemeModelError`
  ＋ 機械可読 code、`as_dict` / `from_dict` 往復、未知 field 拒否）。
- A1 / A2 の語彙（機構確度 4 class、authority 4 class、role 4 値、provenance 3 値、component 4 型、evidence kind 5、
  time basis / quality、entity link 3 class、governance event 11 種、metadata field 4、mapping role 3）。
- 構造化された機構（driver / channel / domain / expected observable consequence、語彙 version 付き category、
  typed reference、正規化文、assertion provenance）、主題、scope token、limitation、invalidation condition、
  INFERRED_EXPOSURE link、evidence attachment（二重時点・basis / quality・source origin・role ＋ provenance・
  consequence / invalidation ref・flag・QA snapshot・locator / excerpt）、observation provenance。
- content id: observation / event / metadata / mapping は identity payload だけから `content_id`、root は生成 id
  （`new_root_id`）。canonical 直列化は P5 と同じ canonical JSON、集合的 field は構築時に canonical sort。
- DERIVED 純関数: 二段 fingerprint（identity core / semantic）、source origin group（保守的独立性）、temporal
  diversity、資格判定（A1 Q1〜Q8 ＋ A2 §19。score なし）、DIRECTLY_EVIDENCED link。
- 同一 root revision helper（`revise_observation` / `attach_evidence`。identity core 変化は IDENTITY_CORE_CHANGED）。

### 追加 — tests/intelligence

- `test_theme_model.py` / `test_theme_identity.py`（golden vector 6 本）/ `test_theme_evidence.py` /
  `test_theme_governance_model.py` / `test_theme_import_boundary.py`（closure 9 module、IO / 時計 / 乱数 / store 不在、
  production bundle からの排除、凍結 package からの非参照）。

### 改善

- `docs/databank/PHASE6_THEME_PERSISTENCE_REVISION_CONTRACT.md` §30 に実装状態（schema / id / payload 材料 /
  実装判断）を追記。契約本文は変更していない。

## v5.01 (2026-09-19) — Phase 6 P6-A3 Theme persistence ＋ revision 契約（設計のみ）

Family C（D7 履歴 model / D8 永続化 authority と writer model / D17 点時刻再構成の全体）を凍結した。
**runtime source・test・package・knowledge・workflow の変更は無い。** ThemeStore / `src/intelligence/themes/` /
discovery / lifecycle / graph / LLM は実装していない。歴史 runtime の port なし。新 hash chain は導入しない。

### 追加 — `docs/databank/PHASE6_THEME_PERSISTENCE_REVISION_CONTRACT.md`

- 前例監査（P5 store / resolver を floor として全面継承、Fact / Context / Compass / ArticleIdentity の破損行 skip は
  floor 未満、歴史 Decision の hash chain は不要と判断）。
- D7: HYBRID（不変 ThemeObservation chain ＋ 追記専用 governance event stream ＋ 追記専用 metadata 履歴 ＋ 不変
  RootRecord ＋ version 付き mapping 記録、derived 点時刻状態）。latest-wins / 可変行 / 単一巨大 stream より安全な理由。
- canonical authority 5 本（roots / observations / governance / metadata / series_mappings）と固定 load 順。
  RootRecord は作成事実のみ（`genesis_observation_id` を作成時に固定、current_* 禁止）。root と genesis の論理的対、
  PENDING_GENESIS / orphan の扱い。
- observation chain（predecessor 厳密 1・物理先行・同一 root・recorded_at 非減少・fork を生む append は拒否・file 上の
  fork は当該 root のみ UNRESOLVED・revert は新 observation・latest-wins なし）。canonical bytes の内訳
  （semantic ＋ attachment ＋ provenance ＋ recorded_at を含み、DERIVED は含まない）。
- append 検証表（byte 冪等 / CONFLICT / ROOT_NOT_FOUND / GENESIS_MISMATCH / DANGLING / WRONG_ROOT /
  NON_TERMINAL / 時刻範囲 / 禁止 evidence / IDENTITY_CORE_CHANGED / PROHIBITED_CONTENT）。
- D8: 追記専用 JSONL、明示 data_root（repository fallback なし）、SINGLE_WRITER、1 store が 5 authority を所有、
  byte 長による改変検知。cross-file 原子性は「宣言が先・完了が後・宣言が id を固定・未完了は明示 PENDING」で解決
  （transaction 機構・authority としての SQLite なし）。
- governance event stream（field・最小 event 種別 11・root ごとの event chain）と解決規則（競合 terminal は
  UNRESOLVED、EVENT_REVERSED）。metadata 履歴（Option A、(root, field) chain、集合 field は snapshot、field 単位の
  UNRESOLVED）。
- D17: 点時刻再構成の純関数（RESOLVED / NO_STATE / UNRESOLVED / INVALID_HISTORY / STORE_CORRUPTION、facet 独立、
  evidence は evidence_time ≤ T かつ attached_at ≤ T、T 以後の record は無影響、derived は再計算）。recorded_at の
  意味論（aware UTC、時計注入、chain 単調）。
- revision / correction の区別と訂正例の永続化先、A2 §16 全分類の永続化先対応、上流 evidence 改訂時の不変性、
  merge（Option B 新 root）/ split / successor の永続化、derived SQLite の境界、rebuild 決定論、schema versioning
  （in-place migration 経路なし）、失敗状態 4 区分と code 表、単一 writer、repository / security 境界、
  不変条件 61〜97、実装順序の推奨（A4a model / A4b store / A4c resolver / A4d E2E）。

### 改善

- `PHASE6_THEME_IDENTITY_EVIDENCE_CONTRACT.md` §23、`PHASE6_THEME_SEMANTICS_AUTHORITY_CONTRACT.md` §23、
  `PHASE6_FOUNDATION_DECISIONS.md` §14 に P6-A3 の結果（Family C 解決）を追記。意味論・決定内容は変更していない。

## v5.00 (2026-09-19) — Phase 6 P6-A2 Theme identity ＋ evidence 契約（設計のみ）

Family B（D5 evidence authority / D6 identity model / D9 evidence 役割 / D15 entity 連結境界 / D19 市場確認 mapping /
D17 evidence 側二重時点）を凍結した。**runtime source・test・package・knowledge・workflow の変更は無い。**
ThemeStore / 永続化 / discovery / lifecycle / graph / LLM は実装していない。歴史 runtime の port なし。

### 追加 — `docs/databank/PHASE6_THEME_IDENTITY_EVIDENCE_CONTRACT.md`

- 現行 primitive（Fact / Observation / SourceDocument / NewsItem / Statement）の id 導出・時点 field・lineage field の検証表。
- 二層 identity（不透明な生成 root id ＋ 内容住所の不変 observation）。root 生成は生成 id ＋ 別途 fingerprint を採用
  （内容導出 root は等価候補の構築上の自動 merge を招くため却下）。12 変更の root 影響分類、identity core の置換は
  NEW_ROOT_REQUIRED（fail closed）。
- 不変 observation の内容分類（IDENTITY / SEMANTIC・PROVENANCE・AUDIT・DERIVED。P5 の identity subset ＋ canonical
  JSON ＋ conflict fail closed を継承）。label / description / taxonomy は observation 外の metadata。
- evidence authority class 4 値（PRIMARY_OBSERVATIONAL / DERIVED_INTERPRETIVE / PROPOSAL_ONLY / NOT_THEME_EVIDENCE）と
  19 種以上の kind 分類。Theme は ContextItem 無しで資格を満たせること。
- evidence 参照の field（kind / class / revision 固有 ref_id / source origin / evidence_time（basis・quality）/
  attached_at / role / role provenance / consequence_ref / metadata flag）。値・本文の複製禁止。
- 二重時点 model（EVIDENCE_TIME vs ATTACHED_AT vs AUDIT）。kind ごとの evidence_time 由来（known_at / as_of /
  published_at ＋ date_quality / event_time）。ingestion 時刻の代替禁止、MISSING は fail closed、再構成条件は両時点。
- source 独立性（evidence item / lineage / source origin / independent source origin）、転載・派生・同一 series
  複数日付の扱い、SOURCE DIVERSITY と TEMPORAL DIVERSITY の分離（score なし）。
- 役割 4 値（SUPPORTS / CONTRADICTS / CONTEXT / INVALIDATES）、TRIGGER は metadata、1 attachment 1 role、role
  provenance 3 値（RULE / HUMAN / LLM_PROPOSAL。LLM は資格に算入しない）。
- 構造化された機構（DRIVER / TRANSMISSION_CHANNEL / AFFECTED_DOMAIN / EXPECTED_OBSERVABLE_CONSEQUENCE の型付き
  component ＋ provenance）、確度 class は observation level に 1 つ、二段 fingerprint（identity core / semantic）と
  除外規則、fingerprint ≠ identity・自動 merge なし。
- entity 連結 3 class（DIRECTLY_EVIDENCED / INFERRED_EXPOSURE / TAXONOMIC_ASSOCIATION）、市場確認 mapping は別の
  version 付き記録（Option C）、limitation / invalidation condition / contradicting evidence の区別、revision 境界
  23 例、merge / split の明示 governance、資格判定の再述、例 14、不変条件 26〜60。

### 改善

- `docs/databank/PHASE6_THEME_SEMANTICS_AUTHORITY_CONTRACT.md` §23 と `docs/databank/PHASE6_FOUNDATION_DECISIONS.md`
  §14 に P6-A2 の結果（Family B 解決）を追記。意味論・決定内容は変更していない。

## v4.99 (2026-09-19) — Phase 6 P6-A1 Theme 意味論 ＋ authority 契約（設計のみ）

Family A（D1 Theme の形式意味論 / D2 Theme vs Narrative / D3 Theme vs Context / D4 Theme vs Compass /
D16 人間 governance）を凍結した。**runtime source・test・package・knowledge・workflow の変更は無い。**
ThemeRecord / ThemeStore / discovery / lifecycle / graph / LLM は実装していない。歴史 runtime の port なし。

### 追加 — `docs/databank/PHASE6_THEME_SEMANTICS_AUTHORITY_CONTRACT.md`

- Theme の形式定義（主題 ＋ 機構、機構確度 class の明示、scope、時間を跨ぐ持続性、evidence 参照能力、
  反証可能性、不変履歴、内部知識としての位置）と資格判定（QUALIFIES_SEMANTICALLY / THEME_CANDIDATE_POSSIBLE /
  DOES_NOT_QUALIFY の条件 Q1〜Q8）。
- 「keyword の袋ではない」の凍結、意味論構成要素の分類（REQUIRED / OPTIONAL / LATER / MUST_NOT）、機構の確度
  class（観測された連関 / 仮説 / evidence に支持された機構 / source の明示的因果主張、co-occurrence ≠ causality、
  件数で class を上げない）、持続性の意味論（数値閾値なし、lifecycle と分離）、支持 / 反証 / limitations
  （能力必須、反証 0 件は正当、不在 ≠ 確証、limitations 非空は reviewed の governance 要件）。
- Theme vs Topic / Event / Context（Context は Theme ではなく DERIVED context としてのみ後日消費、Theme は Context
  無しで存在可）/ Narrative（prose は authority ではない、Phase 7）/ Compass（Phase 6 で恒久分離）/ Prediction /
  Recommendation の境界。
- authority 階層 L0〜L3（Phase 6 では L3 production interpretive authority に到達不可）、人間 governance
  Option B（自動候補 ≠ reviewed Theme ≠ Compass authority、自動 system の可 / 不可）、LLM authority 境界、
  粒度の暫定境界（企業固有 thesis は Phase 9）、資格判定表 14 例、意味論的不変条件 25 項、既存 "theme" 語彙
  （ThemeReference / Statement.themes / legacy config）は topic tag であって Theme ではないという衝突監査、
  Family B / C / D の未解決事項。

### 改善 — `docs/databank/PHASE6_FOUNDATION_DECISIONS.md`

- §14 に P6-A1 の結果（Family A 凍結、次 gate P6-A2）を追記。他節は不変。

### 未実施

- P6-A2（Theme Identity ＋ Evidence Contract）以降は着手していない。

## v4.98 (2026-09-19) — Phase 6 P6-A0.5 土台 / port / 境界の決定（設計のみ）

Phase 6（Theme）の P6-A0 監査（受理済み）を受け、監督者決定 F-1〜F-10 と D0（歴史資産の port 方針）を
凍結した。**runtime source・test・package・knowledge・workflow の変更は無い。** ThemeRecord / ThemeStore /
discovery / lifecycle / graph / LLM は実装していない。

### 追加 — `docs/databank/PHASE6_FOUNDATION_DECISIONS.md`

- F-1 開発土台（現 branch 継続、歴史 branch は参照のみ・merge / rebase / wholesale port 禁止）、F-2 架構位置
  （新しい内部層。Compass / Brief / Signal / P5 に依存せず、凍結 module から import されない）、F-3 作業定義、
  F-4 MVP 順序（identity → evidence → 支持 / 反証 → 不変履歴 → 点時刻再構成 → change 表現。discovery は後）、
  F-5 evidence authority（PRIMARY / OBSERVATIONAL と DERIVED / INTERPRETIVE の区別）、F-6 EvidencePackage
  非再利用、F-7 履歴原則、F-8 永続化の品質下限（P5 append-only 規律以上）、F-9 legacy theme learning の
  precedent 除外、F-10 較正の分離。
- D0 解決: **土台に必要な歴史 runtime port は無い**（A ＝ 空）。歴史資産 22 件を A / B / C / D に分類
  （B: taxonomy・themes・theme_graph・entity catalog・theme_matcher・taxonomy loader・news_builder は各 gate の
  個別認可で後日、C: causal_rules・LLM 境界・store / override・evidence jsonl_store・lifecycle / patterns /
  review_queue・THEME_DISCOVERY_RULES（機密注意）・spec 2 本、D: corpus 結合の risk / why / regime、
  decision / formal_review、歴史 placeholder、legacy theme_learning）。
- 文書 evidence gap（contract first / producer later。SourceDocument / NewsItem 参照で十分）、entity gap
  （linkage は identity より後）、taxonomy gap（独立 identity ＋ discovery 語彙。slug ＝ identity にしない）、
  歴史 lifecycle / governance（原則のみ継承）、将来 `themes` package の import 境界（許可 model module と
  禁止 package）、evidence authority 境界、土台 MVP の contract 目標と除外、非目標、D1〜D22 の 4 family 再編、
  最小 guard 方針、機密 / security 点検。

### 未実施

- P6-A1（Theme Semantics ＋ Authority Contract）以降は着手していない。

## v4.97 (2026-09-19) — Phase 5 完了監査 / closeout

Phase 5（Prediction Journal）を 1 つの chain として読み取り監査し、
**PHASE_5_COMPLETION_AUDIT_PASS_WITH_NON_BLOCKING_DEFERRED_ITEMS / PHASE_5_COMPLETE_READY_FOR_SUPERVISOR_FREEZE**
とした。新機能・runtime 統合・persistence・実 journal 実行・較正 feedback・P4 / P5 意味論の変更・
Phase 6 は含まない。

### 追加 — `docs/databank/PHASE5_COMPLETION_AUDIT.md`

- 判定・scope・freeze anchor・N-1〜N-6 監査（全 PASS）・P5-1 / P5-2 / P5-3 監査・cross-phase chain
  （合成的完全性は完了、production runtime 統合は N-6 により未着手）・persistence / 訂正 / 棄権 /
  coverage model・版 inventory・依存境界・security・production 非回帰・実データ status
  （MACHINERY VALIDATED / REAL LIVE HISTORY NOT ACCUMULATED）・deferred 11 項目・テスト結果・
  blocker 無し・次 Phase。

### 追加 — `tests/intelligence/test_phase5_chain_e2e.py`（2 tests）

- 既存の凍結 API と既存 E2E の fixture だけで、P4 凍結 object 4 種 → ingest → predictions.jsonl →
  権威 reload → engine（訂正 1 件込み）→ evaluations.jsonl → 権威 reload → analyzer →
  CalibrationReport を 1 本の隔離 root で合成し、in-memory record からの report と一致・journal bytes
  不変・入力順非依存・LIVE / REPLAY 非 pool を証明（新しい runtime 統合ではない）。

### 改善 — `docs/databank/PHASE5_ENTRY_CONTRACT.md`

- §21「Phase 5 closeout」を追加（P5-1 / P5-2 / P5-3 CLOSED / FROZEN、PHASE 5 COMPLETE —
  supervisor acceptance pending）。§13 / §17 / §19 / §20 の gate 時点 status 文言 4 箇所を
  「時点の記録」と明示する最小修正。N-1〜N-6 は不変。

### 改善 — `src/intelligence/predictions/__init__.py`（docstring のみ）

- 「P5-3C 未実装」の stale 記述を Phase 5 機構検証済み・runtime 運用は別 gate に更新。

### 未実施

- Phase 5 operationalization（runtime capture / 直列化 / 評価 scheduling / 履歴蓄積）・Phase 6 は
  着手していない。

## v4.96 (2026-09-19) — Phase 5 P5-3C 較正 end-to-end OFFLINE 検証

P5-3A（契約）＋ P5-3B（analyzer）を 1 つの分析系として OFFLINE で検証した（VALIDATION のみ。
新機能・runtime 統合・persistence・実 journal 実行・較正 feedback・production tuning は含まない）。
凍結 P5-3A / P5-3B への corrective patch は不要だった。

### 追加 — `tests/intelligence/test_calibration_e2e.py`（41 tests）

- 代表的な意味世界（LIVE available 14 ＋ 棄権 4、REPLAY 3、期間外 2、評価 28: chain・fork・独立
  terminal・DEFERRED→EVALUATED・orphan・foreign）を凍結 builder のみで構築し、
  `analyze_calibration` → `calibration_report:0.1.0` → `as_dict()` → builder / 凍結 `from_dict` からの
  再構築 → 同一 report を証明。
- gate §3〜§19: 件数の真実性（18 / 13 / 23 / 28 / 23 / 5）、coverage 分割 (12,1,2,3)、5×3 行列の明示
  期待値と合計 11 = exact match 分母、一致 6 = 凍結写像で一致する cell の和、level / confidence /
  15 cell の期待値、訂正（A→B で active・行列・return・active digest が変わり cohort digest と履歴は
  不変。A→B→C は入力順に依らず C）、DEFERRED→EVALUATED（分母 10→11）、fork / 独立 terminal の
  UNRESOLVED（分母不参加・shuffle 不変）、棄権 4 種（confidence 保持棄権は bucket 外）、coverage
  分割の全 group 成立、LIVE / REPLAY 分離、disclosure 境界 N = 0/1/9/10/29/30、空 cohort、重複
  fail closed（意味的同一 object 含む）、foreign / cohort 外の影響範囲、8 通り shuffle の byte 一致、
  JSON / Decimal / timestamp なし直列化、入力不変、runtime import closure 14 module、P5-3A / P5-3B /
  本書 §18〜§19 の整合監査。

### 改善 — `docs/databank/PHASE5_ENTRY_CONTRACT.md`

- §20「P5-3 完了検証（P5-3C）」を追加（PASS・監督者 freeze 待ち）。§14〜§19・N-1〜N-6 は不変。

### 未実施

- Phase 5 completion audit / closeout・P5-4・Phase 6 は着手していない。

## v4.95 (2026-09-19) — Phase 5 P5-3B 純粋 OFFLINE 較正 analyzer

P5-3A（FROZEN）の契約を**そのまま適用する**純粋 offline analyzer を追加した。store / filesystem /
network / market / calendar / evaluation_engine に触れず、journal を変更せず、較正を永続化せず、
P4 MarketSignal / Compass DNA / 閾値 / confidence を変更しない。較正は観測的 analytics であり
production authority ではない。

### 追加 — `src/intelligence/predictions/calibration_analyzer.py`

- `analyze_calibration(predictions, evaluations, cohort) -> CalibrationReport`
  （`calibration_report:0.1.0`）。凍結 PredictionRecord / EvaluationRecord の iterable と明示
  `CohortBoundary` だけを受ける純関数（read-only・決定論的）。
- cohort 選択は origin ＋ session_date 閉区間のみ（created_at / 物理位置 / 現在日付を使わない）。
  同一 session の複数 prediction_id は dedupe しない（`prediction_count` ＋ `unique_session_count`）。
- 対応付けは `prediction_id` のみで、予測ごとに凍結 `resolve_active_evaluation()` を呼ぶ
  （第二の resolver・「最新」選択なし）。coverage は ACTIVE_EVALUATED / ACTIVE_DEFERRED /
  NO_EVALUATION / UNRESOLVED の分割（`CoverageCounts` が検証）。UNRESOLVED は件数・診断別件数・
  prediction_id で露出し分母に入らない（率は凍結 `METRIC_DEFINITIONS` に無いため件数のみ）。
- cohort 外の予測・foreign evaluation は metric に影響しない。lineage の record 件数は供給 source
  件数、`associated_evaluation_count` / `foreign_evaluation_count` は report 本体で別途報告。
- report: `versions`・coverage 率・棄権（率 ＋ 棄権予測の outcome / return 診断、方向 exact match
  なし）・方向 exact match（分母 = available かつ active EVALUATED）・overall outcome / Decimal return
  統計・5×3 混同行列（零行可視）・level 別 5 行・confidence 別 3 bucket（AVAILABLE 予測のみ）・
  level × confidence 15 cell。すべての率は凍結 `Rate`（分子・分母・disclosure、生件数を保持）。
- 空 cohort は有効な report。重複 prediction_id / evaluation_id は `CalibrationInputError` で
  fail closed。JSON 化して float を含まない。
- 依存: `calibration_contract` / `evaluation_record` / `prediction_record` / `reports.market_signal`
  と stdlib のみ。

### 追加 — `tests/intelligence/test_calibration_analyzer.py`（35 tests）

- gate §26 の 80 項目（cohort 境界・origin 分離・同一 session 複数予測・prediction_id のみの対応付け・
  ACTIVE_DEFERRED / NO_EVALUATION / UNRESOLVED の分母除外・棄権の除外と保持・exact match の
  分子分母・混同行列の形と合計・level / confidence / level×confidence の固定行と零 bucket・
  棄権 outcome・Decimal return・sample disclosure の閾値・空 cohort・shuffle 決定論・重複 id
  fail closed・orphan / cohort 外評価の除外・訂正での active と digest の変化・created_at / 物理順の
  非使用・read-only・store / engine / market / network 非依存・公開 / 取引語彙不在・lineage 版・
  report 版の明示・全 rate の分子分母露出）。

### 改善 — `docs/databank/PHASE5_ENTRY_CONTRACT.md`

- §19「P5-3B 純粋 OFFLINE 較正 analyzer」を追加。§14〜§18 は不変。

### 改善 — `src/intelligence/predictions/__init__.py`（docstring のみ）

- `calibration_analyzer` を現在の内容に追記し、未実装を P5-3C に更新。

### 改善 — `tests/intelligence/test_prediction_journal_e2e.py` / `test_evaluation_e2e.py`（テストのみ）

- predictions package のファイル一覧に `calibration_analyzer.py` を追加（検査意図は不変）。

### 未実施

- P5-3C（較正 end-to-end offline 検証）以降は着手していない。

## v4.94 (2026-09-19) — Phase 5 P5-3A 較正の分析契約 ＋ metric 仕様

P5-1 / P5-2（CLOSED / FROZEN）の上に、較正の**分析契約だけ**を凍結した（SPECIFICATION FIRST）。
journal を読む analyzer（P5-3B）・persistence・P4 MarketSignal / Compass DNA / 閾値 / confidence
の変更・runtime 統合・公開出力は**含まない**。較正は観測的 analytics であり production authority
ではない。

### 追加 — `src/intelligence/predictions/calibration_contract.py`

- 分析用 5→3 方向写像 `prediction_direction_mapping:1.0.0`（UPWARD_LEAN / SLIGHT_UPWARD_LEAN → UP、
  NEUTRAL_RANGE → RANGE、SLIGHT_DOWNWARD_LEAN / DOWNWARD_LEAN → DOWN）。P4 `LEVEL_BY_STATE` の
  方向成分の逆射影と一致することをテストで証明。保存 record の 5 level は畳まない。
- `directional_exact_match`（歴史的 exact match。確率・将来精度・skill score ではない）。
- active evaluation resolver `active_evaluation_resolver:1.0.0`: supersession graph の意味論で
  terminal 1 つを active に。fork / 独立 terminal 複数 / dangling / subject 不一致 / 同 id 別内容は
  診断付きで除外（`ResolutionStatus`）。created_at と物理順を使わない。
- cohort: `CohortBoundary(origin, start_session, end_session)`（session_date の閉区間、既定なし）、
  `PredictionCohort` ALL / AVAILABLE / ABSTAINED、LIVE / REPLAY 分離（COMBINED なし）、
  同一 session の複数予測を dedupe しない（unique session 件数を併記）。
- coverage `EvaluationCoverage`（ACTIVE_EVALUATED / ACTIVE_DEFERRED / NO_EVALUATION / UNRESOLVED）。
  DEFERRED は outcome の分母に入らない。棄権は採点しない。
- 分母の凍結語彙 `Denominator` と 9 つの `MetricDefinition`（分母を名指し）、`Rate`
  （numerator / denominator / Decimal value / disclosure）。
- `sample_disclosure:1.0.0`（0 NO_DATA / 1–9 INSUFFICIENT_SAMPLE / 10–29 LIMITED_SAMPLE /
  30+ REPORTABLE）。有意性・信頼区間は主張しない。
- `OutcomeCounts` / `summarize_returns`（Decimal・prec 28 固定 context・mean / median / mean_abs /
  min / max・Sharpe / 年率化 / P&L なし）。
- lineage: `content_digest` / `cohort_digest` / `active_evaluation_digest` / `CalibrationLineage`
  （版 4 種 ＋ record 件数 ＋ digest 2 種。hash chain ではない）。
- 依存: PredictionRecord / EvaluationRecord / `core.ids` / `reports.market_signal` と stdlib のみ。

### 追加 — `tests/intelligence/test_calibration_contract.py`（48 tests）

- gate §24 の 60 項目（写像と版・P4 逆射影一致・exact match 定義・棄権 / DEFERRED / 評価なしの
  cohort と分母・resolver の chain / fork / 独立 terminal / dangling / subject 不一致・created_at と
  物理順の非使用・LIVE / REPLAY 分離・5×3 行列・rate の分子分母・level 条件付き Decimal 率・
  confidence・棄権 / coverage・unique session と非 dedupe・cohort 境界・disclosure 閾値・生件数の
  保持・有意性不主張・Decimal / float 非権威・digest の決定論と訂正での変化・不変性・
  Compass DNA / 閾値 / confidence 非調整・market / calendar / engine 非依存・公開 / 取引語彙不在）。

### 改善 — `docs/databank/PHASE5_ENTRY_CONTRACT.md`

- §18「P5-3A 較正の分析契約 ＋ metric 仕様」を追加。N-1〜N-6・§14〜§17 は不変。

### 改善 — `tests/intelligence/test_prediction_journal_e2e.py` / `test_evaluation_e2e.py`（テストのみ）

- predictions package のファイル一覧に `calibration_contract.py` を追加（検査意図は不変）。

### 未実施

- P5-3B（offline 較正 analyzer）以降は着手していない。

## v4.93 (2026-09-18) — Phase 5 P5-2D Evaluation end-to-end OFFLINE 検証（P5-2 完了）

P5-2A / P5-2B / P5-2C を 1 つの系として検証する gate。新機能・runtime 統合・CLI は追加せず、
テストを唯一の検証 artifact とした。P5-2A/B/C に欠陥は見つからず、修正パッチは無い。

### 追加 — `tests/intelligence/test_evaluation_e2e.py`（38 tests）

- happy path A–Q を 1 本の E2E（PredictionRecord → カレンダー証拠 → TOPIX Observation →
  `evaluate_and_append` → EVALUATED / APPENDED → Decimal return と分類の一致 → 物理 1 行 →
  instance 破棄 → 権威 reload → 同一 record / id / provenance → 同じ証拠での再評価
  ALREADY_PRESENT・bytes 不変）。
- outcome state（UP / 境界 RANGE 3 点 / DOWN と各境界のすぐ外側）の reload 後の連続 return 保存、
  予測 state 非依存（方向 / NEUTRAL_RANGE / 棄権）、週末＋祝日 gap のカレンダー証明、
  calendar / previous session の DEFERRED journal、欠落 / 無効 / 未対応 source の DEFERRED journal、
  凍結 defer 優先順位の順序非依存と reload、複数記録 journal の再起動、engine 境界からの冪等、
  created_at / provenance の conflict、A→B→C 訂正 chain、DEFERRED→EVALUATED 履歴、破損 8 種の
  fail closed、process 再起動、predictions.jsonl 非依存（closure 18 module）、point-in-time /
  look-ahead 境界、single-writer 検知、P5-2A/B/C 整合監査、runner / CLI 不在。

### 改善 — `docs/databank/PHASE5_ENTRY_CONTRACT.md`

- §17「P5-2 完了検証（P5-2D）」を追加（検証結果・完了監査・P5-2 status CLOSED / FROZEN
  監督者受理待ち）。N-1〜N-6・§14〜§16 は不変。

### 未実施

- P5-3A（Calibration contract ＋ metrics specification）以降は着手していない。

## v4.92 (2026-09-18) — Phase 5 P5-2C OFFLINE 評価 engine

凍結 PredictionRecord ＋ 東京カレンダー証拠 ＋ TOPIX close 観測 → 凍結 EvaluationRecord を
決定論的に生成する**offline 純関数**を実装した。評価するのは市場 outcome のみで、予測の正誤・
較正・network / J-Quants 取得・runtime 統合・公開出力は**含まない**。P5-1 / P5-2A / P5-2B の
実装・P4・workflow・config は不変。

### 追加 — `src/intelligence/predictions/evaluation_engine.py`

- `evaluate_prediction(prediction, calendar_evidence, market_evidence, *, created_at,
  supersedes_evaluation_id="")` と薄い `evaluate_and_append(store, …)`。
- 入力境界: 凍結 `PredictionRecord`、`CalendarEvidence`（J-Quants カレンダー行 ＋ source id ＋
  区分値）、既存 `market.model.Observation`（TOPIX raw、`trading_date` 完全一致、改定は既存
  `latest_revisions` で解決）。第二の市場 schema を作らない。
- カレンダー検証は既存 `validate_divisions` / `trading_days` を使い、供給された TOPIX 観測の全日付と
  区分値を実測で突き合わせて `SessionVerification` へ写す。weekday 演算・金→月推定なし。
- realized return は `prec 28 / ROUND_HALF_EVEN` 固定 context の Decimal で計算し、分類は P5-2A の
  凍結 helper に委ねる（閾値定数を持たない）。
- 支持 source は `jquants`、schema は `core.types.SCHEMA_VERSION`。reference / target の source と
  schema は一致必須。
- defer 優先順位（凍結）: source_unsupported → calendar_unverified → reference_session_unverified →
  observation_invalid → reference_close_unavailable → target_close_unavailable。証拠 list の順序に
  依存しない。DEFERRED でも通った側の証拠を保持する。
- unavailable / 棄権の予測も証拠が揃えば EVALUATED（棄権を理由に DEFERRED にしない）。
- `created_at` / `supersedes_evaluation_id` は呼び出し側が明示。現在時刻・filesystem・環境変数・
  network・git に触れない。P4 本番 closure から到達不能。

### 追加 — `tests/intelligence/test_evaluation_engine.py`（57 tests）

- gate §21 の 70 項目（EVALUATED・Decimal 算術・境界 5 点・丸め無し・週末＋祝日 gap・weekday
  fallback 不在・calendar / previous session / closes / invalid / source の defer・重複 / 改定・
  nearest / fill / 補間の不在・棄権と NEUTRAL_RANGE の評価・予測 state 非依存・created_at 明示・
  provenance 写し・凍結 target / 版・決定論・優先順位・順序非依存・supersedes 透過・store helper・
  DEFERRED ≠ RANGE・禁止概念・純粋性・P4 非到達・下流専用・source object 不変・矛盾 / NaN・
  ambient decimal context 非依存）。

### 改善 — `docs/databank/PHASE5_ENTRY_CONTRACT.md`

- §16「P5-2C OFFLINE 評価 engine」を追加。N-1〜N-6・§14・§15 は不変。

### 改善 — `tests/intelligence/test_prediction_journal_e2e.py`（テストのみ）

- predictions package のファイル一覧に `evaluation_engine.py` を追加（検査意図は不変）。

### 未実施

- P5-2D（Evaluation end-to-end offline 検証）以降は着手していない。

## v4.91 (2026-09-18) — Phase 5 P5-2B 追記専用 EvaluationStore（evaluations.jsonl）

P5-2A（凍結）の EvaluationRecord の**永続化層だけ**を実装した。評価 engine・PredictionRecord →
EvaluationRecord の自動化・TOPIX / カレンダー / J-Quants 参照・return 計算・較正・「現在の評価」の
解決・runtime 統合・公開出力は**含まない**。P5-1 / P5-2A の実装・P4・workflow・config は不変。

### 追加 — `src/intelligence/predictions/evaluation_store.py`

- `EvaluationStore(data_root)`: `<data_root>/predictions/evaluations.jsonl` を唯一の権威とする
  追記専用 journal（predictions.jsonl とは別の権威。PredictionStore を import せず
  predictions.jsonl を開かない）。読むだけではディレクトリを作らない。
- append 意味論（P5-1B と同じ規律）: 未知 id → `APPENDED`、既知 id ＋ canonical 行 byte 一致 →
  `ALREADY_PRESENT`、既知 id ＋ provenance / created_at を含むいずれかの field 差 →
  `EvaluationConflict`（fail closed）。
- supersession は append であって update ではない: 訂正は `supersedes_evaluation_id` を持つ
  新しい物理行、前の行は不変。前任が同じ journal に物理的に先行して存在し（dangling / forward
  reference は `SupersessionRejected` / `DANGLING_SUPERSESSION`）、`prediction_id` / `target` /
  `reference_session` / `session_date` / `classification_version` が一致すること
  （`INCOMPATIBLE_SUPERSESSION`）を append 時・load 時に要求。数値の変化は要求しない。
  DEFERRED → EVALUATED / EVALUATED → EVALUATED / DEFERRED → DEFERRED の履歴を許す。
- 権威 load は fail closed（理由コード 11 種）。物理順を保存し、latest / current / resolve の
  API を持たない。`open("a", newline="\n")` → 1 write → `flush` → `fsync`。SINGLE WRITER
  （外部変更は `ConcurrentModificationDetected`）。SQLite / hash chain / transaction / network /
  git なし。

### 追加 — `tests/intelligence/test_evaluation_store.py`（53 tests）

- gate §18 の 70 項目（不在 journal・append / 冪等 / conflict・決定論的直列化・reload・物理順・
  共存・A→B→C の supersession chain と prefix bytes・DEFERRED→EVALUATED 等の履歴・同数値訂正・
  dangling / forward / cross-prediction / session / classification 不一致の拒否・自己 supersession・
  破損 10 種・skip / 修復 / migration 不在・latest-wins 不在・prefix 保存・fsync 規律・
  single-writer・caller-controlled root・evaluations.jsonl のみ生成・predictions.jsonl 非アクセス・
  PredictionStore 非 import・禁止依存・JSONL 権威・SQLite / hash chain / transaction 不在・
  EvaluationRecord 権威）。すべて `tmp_path` 隔離。

### 改善 — `docs/databank/PHASE5_ENTRY_CONTRACT.md`

- §15「P5-2B 追記専用 evaluation journal / store」を追加。N-1〜N-6・§14 は不変。

### 改善 — `tests/intelligence/test_prediction_journal_e2e.py`（テストのみ）

- predictions package のファイル一覧に `evaluation_store.py` を追加（検査意図は不変）。

### 未実施

- P5-2C（offline 評価 engine）以降は着手していない。

## v4.90 (2026-09-18) — Phase 5 P5-2A EvaluationRecord schema ＋ outcome contract

P5-1（CLOSED / FROZEN）の上に、**不変の評価記録 object だけ**を凍結した。EvaluationStore /
`evaluations.jsonl`・TOPIX 取得・取引カレンダー照会・return 計算・自動評価・較正・正誤判定・
runtime 統合・公開出力は**含まない**。P5-1 実装・P4・workflow・config は不変。

### 追加 — `src/intelligence/predictions/evaluation_record.py`

- `EvaluationRecord`（frozen）: A identity 入力（`schema_version` = `evaluation_record:0.1.0` /
  `prediction_id` / `target` / `reference_session` / `session_date` / `classification_version` /
  `status` / `realized_return` / `realized_outcome` / `defer_reason` / `supersedes_evaluation_id`）、
  B provenance（closes・observation id・source・schema 版・`SessionVerification`）、
  C audit（`created_at`）。hit / miss / accuracy / score・予測 level の複製・表示文字列は存在しない。
- realized_return は Decimal（float / NaN / Infinity 拒否・丸めない）。`canonical_decimal` は
  context 非依存で末尾ゼロだけを落とす平文十進（`0.0100`→`0.01`、`-0`→`0`、`1E-7`→`0.0000001`、
  40 桁保持）。同値の表現は同じ evaluation_id。`from_dict` は非 canonical 文字列を拒否。
- 分類 `topix_neutral_band:1.0.0`: UP > +0.003 / RANGE −0.003..+0.003（閉区間）/ DOWN < −0.003
  （Decimal 比較）。realized の区分名は予測 level と分けて `RANGE`（境界不変）。
- 状態機械: EVALUATED（return・outcome・closes・検証済み `SessionVerification` 必須、outcome は
  分類と一致）/ DEFERRED（return・outcome 無し、defer_reason 6 値のいずれか必須）。
  DEFERRED は RANGE でも零 return でも「予測 unavailable」でもない。棄権を理由に DEFERRED にしない。
- `SessionVerification`（既存 `CalendarValidation` と同じ実測検証の要約 ＋ 検証済み session /
  直前 session）。EVALUATED では validated かつ session_date / reference_session と一致を要求。
- 訂正は `supersedes_evaluation_id` を持つ新しい record（新 id）。自己 supersession・不正 id 拒否。
  in-place 変更・「最新が勝つ」・chain 走査は無い。
- `created_at` は呼び出し側が明示（identity 外）。module は現在時刻を読まない。
- 依存: `core.ids` / `core.time` / `prediction_record`（prefix 定数）と stdlib のみ。

### 追加 — `tests/intelligence/test_evaluation_record.py`（162 tests）

- gate §20 の 50 項目（境界 ±0.003 の閉区間、Decimal canonical 化 15 パターン、同値表現の
  同一 id、負の零、極小値、float / NaN / Infinity 拒否、prediction_id / target / session 検証、
  EVALUATED / DEFERRED の矛盾拒否、分類不一致拒否、3 版分離、golden id ＋ hashlib 独立再計算、
  created_at / provenance 非依存、意味論依存、supersession、不変性、偽造 id、未知 field、
  round-trip、禁止概念、依存境界、LIVE / REPLAY、棄権と DEFERRED の分離、datetime.now 不在）
  ＋ `SessionVerification` 不変条件・strict parse。

### 改善 — `docs/databank/PHASE5_ENTRY_CONTRACT.md`

- §14「P5-2A EvaluationRecord schema ＋ outcome contract」を追加（目的・target / horizon・
  Decimal・分類・状態機械・defer 理由・session 証拠・provenance・identity 分類・supersession・
  較正との分離・依存境界）。N-1〜N-6 は不変。

### 改善 — `tests/intelligence/test_prediction_journal_e2e.py`（テストのみ）

- P5-1D が固定していた predictions package のファイル一覧に `evaluation_record.py` を加えた
  （「runner / CLI を追加していない」という検査意図は不変）。P5-1 の実装 3 module と専用テストは
  無変更。

### 未実施

- P5-2B（追記専用 evaluation journal / store）以降は着手していない。

## v4.89 (2026-09-18) — Phase 5 P5-1D Prediction Journal end-to-end OFFLINE 検証（P5-1 完了）

P5-1A / P5-1B / P5-1C を 1 つの系として検証する gate。新機能・runtime 統合・CLI は追加せず、
テストを唯一の検証 artifact とした。P5-1A/B/C に欠陥は見つからず、修正パッチは無い。

### 追加 — `tests/intelligence/test_prediction_journal_e2e.py`（28 tests）

- happy path A–L を 1 本の E2E（available / LIVE → APPENDED → 物理 1 行 → instance 破棄 →
  新しい store の権威 reload → 同一 PredictionRecord / 同一 id / provenance・audit 完全一致 →
  canonical bytes → ingestion 境界からの再投入 ALREADY_PRESENT・bytes 不変）。
- state coverage: available 方向 / NEUTRAL_RANGE / direction_mixed / draft_abstained ×
  LIVE / REPLAY の 8 通りが再起動後も同じ state・相異なる id。
- 複数記録 journal（3 session・同一 session の別意味論・REPLAY）の物理順 / 件数 / get の保存と
  date-based overwrite の不在、再起動 → 正確な再投入 ALREADY_PRESENT → 新規 APPENDED → 再 reload。
- ingestion 境界からの冪等性と conflict（provenance / recorded_at / cutoff /
  outlook_rule_version）の fail closed（bytes 不変・reload 成功・元記録無傷）。
- 正常 journal の隔離コピーに対する破損 6 種の fail closed（修復・skip・部分 load なし）。
- single-writer 検知（lock 追加なし）、point-in-time（保存 audit は source 由来で検証時刻を
  含まない）、runtime import closure が 13 module に閉じること、P4 本番 closure から
  `predictions` へ到達しないこと、validation runner / CLI を追加していないこと。

### 改善 — `docs/databank/PHASE5_ENTRY_CONTRACT.md`

- §13「P5-1 完了検証（P5-1D）」を追加（検証結果・完了監査・P5-1 status CLOSED / FROZEN
  監督者受理待ち）。N-1〜N-6 と §5 / §8 系は不変。

### 未実施

- P5-2A（EvaluationRecord schema ＋ outcome contract）以降は着手していない。

## v4.88 (2026-09-18) — Phase 5 P5-1C OFFLINE P4 → PredictionRecord ingestion adapter

P5-1A / P5-1B で凍結した PredictionRecord / PredictionStore へ、**既に生成された** P4 意味論
（MorningBrief ＋ MarketSignal ＋ 生成 context）を**写す**境界だけを実装した
（COPY, DO NOT ANALYZE）。MarketSignal / MorningBrief / outlook の再計算・市場観測 / TOPIX /
取引カレンダー参照・採点・較正・EvaluationRecord・runtime producer 統合・Actions・Pages /
公開出力は**含まない**。本番 runtime closure・Phase 4 コード・workflow・config は不変。

### 追加 — `src/intelligence/predictions/prediction_ingest.py`

- 権威 source の特定: MorningBrief と MarketSignal が両方揃うのは
  `delivery_pilot.main()` の in-process 境界（`build_morning_brief(draft, package)` →
  `build_market_signal(brief)`）だけ。P4 は内部 artifact に両者を書かず、公開 `/v2` JSON は
  level / confidence / horizon を含まない。よって adapter は in-process の凍結オブジェクトを
  入力とし、公開 JSON / Markdown / HTML / 表示ラベル / 通知 payload を source にしない。
  安定した offline artifact が無いため CLI / file format は発明しない（handoff は後続 gate）。
- `validate_sources` / `build_prediction_record` / `ingest_prediction`（A 検証 → B 構築 →
  C 凍結 store append）。`origin` は `PredictionOrigin` の明示必須（既定値・推定なし）。
- field 対応: session は MorningBrief、signal 5 field は MarketSignal をそのまま、
  `recorded_at` は `CompassDraft.generated_at`（P4 生成時刻。無ければ拒否し ingestion 時刻で
  代用しない）、`cutoff` は `EvidencePackage.cutoff`、`principle_refs` は tier3、
  `market_principle_version` は brief.points の非空版（高々 1 種）、`outlook_rule_version` は
  `draft.outlook.rule_version`。回復不能な field は無い。
- cross-object 整合を fail closed: `signal.brief_id == brief.brief_id`、draft / package の id、
  session 一致、brief_id / signal_id の content-address 再検証、schema 版、verdict /
  generator、brief.tier3.outlook と draft.outlook の一致。日付だけで結合しない。
- unavailable も journal に載せ、NEUTRAL_RANGE は available のまま、`direction_mixed` /
  `direction_uncertain` の confidence / horizon は P4 のまま写す。
- `compass.evidence_package` を import せず（closure が context.builders / facts へ広がる）、
  EvidencePackage は 4 属性の Protocol で受ける。`PredictionConflict` は伝播（握り潰さない）。

### 追加 — `tests/intelligence/test_prediction_ingest.py`（74 tests）

- gate §17 の 45 項目（コピー意味論・cross-object 整合・schema 版・origin・truthful
  recorded_at / cutoff / 版・store 相互作用・禁止依存 13 種・権威・非変更・決定論・矛盾状態
  15 パターン）＋ 実 EvidencePackage の受理・source 境界宣言。P4 自身の `make_brief_id` /
  `build_market_signal` で作った本物の frozen object と `tmp_path` 隔離 store だけを使う。

### 改善 — `docs/databank/PHASE5_ENTRY_CONTRACT.md`

- §5.2 を追加（P4 source 境界・field 対応表・cross-object 整合・state コピー・依存境界・
  store 相互作用）。§5 / §5.1 / §8.1 と N-1〜N-6 は不変。

### 未実施

- P5-1D（Prediction Journal end-to-end offline 検証）以降は着手していない。

## v4.87 (2026-09-18) — Phase 5 P5-1B 追記専用 PredictionStore（JSONL journal）

P5-1A（v4.86）で凍結した PredictionRecord の**永続化層だけ**を実装した。P4 出力の
ingestion（P5-1C）・EvaluationRecord / `evaluations.jsonl`・TOPIX / 取引カレンダー評価・
較正・runtime producer・Actions・Pages / 公開出力は**含まない**。本番 runtime closure・
Phase 4 コード・workflow・config は不変。

### 追加 — `src/intelligence/predictions/prediction_store.py`

- `PredictionStore(data_root)`: `<data_root>/predictions/predictions.jsonl` を唯一の権威と
  する追記専用 journal。data_root は呼び出し側が明示（`core.paths` / 環境変数 / config への
  fallback なし）。読むだけではディレクトリを作らない。
- append 意味論: 未知 id → `APPENDED`（1 行追記）、既知 id ＋ canonical 行 byte 一致 →
  `ALREADY_PRESENT`（書かない）、既知 id ＋ provenance / audit を含むいずれかの field 差 →
  `PredictionConflict`（fail closed。merge・更新・2 行目追記なし）。`AppendResult` は
  `wrote_line` と物理行番号を持つ。
- journal 直列化（identity 直列化とは別）: `as_dict()` を key 昇順・compact・UTF-8・`\n`
  終端の 1 行に。
- 権威 load は fail closed: 不正 JSON / 空行 / 非 object / 未知 field / schema 違反 /
  偽造・失効 id / 非 canonical 行 / 終端改行の無い最終行 / 非 UTF-8 / 物理重複（同一内容でも）
  を `PredictionJournalCorrupt`（行番号＋理由コード 9 種）で拒否。skip・dedup・修復・
  migration-on-read をしない。
- 書き込み規律: 親 dir 作成 → `open("a", newline="\n")` → 1 write → `flush` → `fsync`
  （既存 ledger / normalization store と同じ最小規律。hash chain / transaction / lock なし）。
- SINGLE WRITER: 開いてからの byte 長変化を append 前に検知し
  `ConcurrentModificationDetected` で fail closed（検知であり排他ではない）。
- 最小 read API: `iter_records()`（物理行順）/ `get()` / `in` / `len()` / `reload()`。
  日付 key・「最新が勝つ」・dedup を持たない。SQLite / network / git を持たない。

### 追加 — `tests/intelligence/test_prediction_store.py`

- gate §14 の 30 項目（初回 append・冪等・bytes 不変・provenance / audit 差の fail closed・
  同一 session / LIVE-REPLAY 共存・NEUTRAL_RANGE / 棄権の保存・round-trip・破損 8 種・
  追記専用経路・prefix bytes 保存・JSONL 権威・SQLite / network / git 非依存・本番非到達・
  outcome field 不在・single-writer 境界・caller-controlled root・secret / path 非直列化）
  ＋ 空 / 不在 journal・write 規律（fsync 1 回）・result 語彙。すべて `tmp_path` 隔離。

### 改善 — `docs/databank/PHASE5_ENTRY_CONTRACT.md`

- §8.1 を追加（JSONL 権威・append / 冪等 / conflict 意味論・物理重複規則・load の
  fail closed・書き込み規律・single-writer 境界・point-in-time）。§8 と N-1〜N-6 は不変。

### 未実施

- P5-1C（offline P4 → PredictionRecord ingestion）以降は着手していない。

## v4.86 (2026-09-18) — Phase 5 P5-1A PredictionRecord schema ＋ 決定論的 identity

Entry Contract（v4.85）の §11 明確化 3 点を監督者が LOCKED とし、P5-1A として
「1 件の point-in-time 予測観測」の型と identity だけを凍結した。persistence（P5-1B）・
ingestion（P5-1C）・EvaluationRecord / TOPIX 参照（P5-2）・較正（P5-3）・runtime 統合・
公開出力は**含まない**。本番 runtime closure・Phase 4 コード・workflow・Pages・config は不変。

### 追加 — `src/intelligence/predictions/prediction_record.py`

- `PredictionRecord`（frozen dataclass）: field を A identity 入力（`schema_version` /
  `session_date` / `reference_session` / `origin` / `available` / `level` / `confidence` /
  `horizon` / `unavailable_reason`）、B provenance（`brief_id` / `signal_id` / `package_id` /
  `draft_id` / source schema 版）、C audit（`recorded_at` / `cutoff` / `principle_refs` /
  `market_principle_version` / `outlook_rule_version`）に分類。表示文字列・`delivery_id`・
  realized outcome・評価状態・閾値版の field は**存在しない**（受け取る引数も無い）。
- 決定論的 identity（N-1）: A の 9 key だけを key 昇順・compact・UTF-8 の JSON へ直列化し
  SHA-256 先頭 24 hex を `pred_` に付ける（`core.ids.content_id` と同一機構。新 hash chain なし）。
  `brief_id` / `signal_id` / `recorded_at` を変えても同じ ID、意味論のどれか 1 つ
  （LIVE / REPLAY を含む）を変えれば別 ID。
- fail closed: P4 凍結語彙（5 level / 3 confidence / 6 unavailable reason / 既知 horizon）の外、
  P4 が生成しえない `(level, confidence)` 組、available / unavailable の矛盾、
  `reference_session >= session_date`、非 ISO 日付、naive datetime、偽造 `prediction_id`、
  未知 field を `InvalidPredictionRecord` で拒否。正規化・推測をしない。
- schema 版 `prediction_record:0.1.0`（N-2 の分類版 `topix_neutral_band:1.0.0` とは別概念）。
- `as_dict` / `from_dict` の決定論的 round-trip（JSON 互換・secret / 表示文字列を含まない）。
- 依存境界: `compass.model` / `core.ids` / `core.time` / `reports.market_signal` /
  `reports.model` のみ。network / store / calendar / J-Quants / persistence を import しない。

### 追加 — `tests/intelligence/test_prediction_record.py`（145 tests）

- golden canonical 文字列と、hashlib による独立再計算での ID 一致。
- provenance / audit 差分 → 同一 ID、意味論差分（全 level・confidence・reason・origin・
  session）→ 別 ID、payload 水準で `horizon` / `schema_version` も hash に入ること。
- 矛盾状態・語彙外・順序違反・naive datetime・偽造 ID・未知 field・表示 / outcome kwargs の拒否。
- 不変性、round-trip、P4 語彙との整合（`LEVEL_BY_STATE` 値域 7 組、
  `delivery.PUBLIC_UNAVAILABLE_REASONS`、`CompassConfig.outlook_horizon`）、依存境界、
  本番 closure 非到達（`predictions` は `EXCLUDED_PACKAGES`）。

### 改善 — `docs/databank/PHASE5_ENTRY_CONTRACT.md`

- §5.1 を追加（P5-1A の field 対応表・identity 直列化契約・状態機械・schema-local と
  verified-calendar 検証の分離）。§5 の分類と N-1〜N-6 は変更していない。
- §11 の 3 点を **LOCKED** と明記（(1) は「直前の**検証済み**東京取引 session」の文言）。

### 未実施

- P5-1B（追記専用 journal / store）以降は着手していない。

## v4.85 (2026-09-17) — Phase 5 Entry Contract の凍結（documentation only）

Phase 4 の閉幕（`PHASE_4_COMPLETE / CLOSED / FROZEN`）、Phase 5 Entry Contract A0 監査、
A0.7B-R2 の TOPIX 実データ取得（J-Quants v2・2021-09-17〜2026-09-17・観測 1,223 件）、
A0.5R の分布実測（realized returns 1,222 件・19 検証すべて true）を経て、監督者が
N-1〜N-6 を凍結した。本エントリはその**文書化のみ**であり、実装を含まない。

### 追加 — `docs/databank/PHASE5_ENTRY_CONTRACT.md`

- **N-1 identity**: `prediction_id` は表示非依存の prediction semantics から content-address する。
  `brief_id` / `signal_id` は provenance reference として保持するが hash payload に含めない。
  `delivery_id` を identity に使わない。
- **N-2 realized outcome**: target = TOPIX、`close(session) / close(前取引 session) − 1` を
  Decimal で丸めずに分類。`UP > +0.30%` / `NEUTRAL_RANGE −0.30%〜+0.30%（閉区間）` /
  `DOWN < −0.30%`。版識別子 `topix_neutral_band:1.0.0`。経験的根拠（|return| nearest-rank
  P25 = 0.299648%、±0.30% で NEUTRAL_RANGE 25.20%、FULL 年の spread 5.19pp）を provenance
  として記録。**MarketSignal の成績は閾値決定に使っていない。** 歴史的 realized_return は
  版変更で書き戻さない。
- **N-3 integrity**: 新しい hash chain を作らない（content ID ＋ 追記専用 ＋ 既存 backup manifest）。
- **N-4 target**: 評価対象は TOPIX のみ。Phase 4 MarketSignal の意味論は不変。
- **N-5 horizon**: 1 東京取引 session の close-to-close。取引カレンダーを検証し、weekday
  演算へフォールバックしない。検証不能なら DEFER。
- **N-6 runtime**: P5-1 は OFFLINE から。repository-commit persistence を追加せず、公開 `/v2`
  に結合しない。runtime 同居は別の認可 gate。
- source 分類（STABLE_INPUT / REFERENCE_ONLY / DO_NOT_COUPLE）、PredictionRecord の field 分類、
  abstention の意味論（棄権は coverage から消えず・NEUTRAL_RANGE にも方向予測にもならない）、
  point-in-time の意味論（不変・追記専用・DEFER・supersede・live/replay 分離）、persistence
  契約（`<data_root>/predictions/*.jsonl`・legacy journal を権威にしない・同一日付上書きなし）、
  INTERNAL ONLY 境界、Phase の順序（P5-1A → P5-1B → P5-1C → P5-2 → P5-3）を凍結。
- 凍結決定から導いた明確化 3 点を「監督者確認事項」として明示（§11）。

### 未実施

- P5-1A（PredictionRecord schema ＋ identity 設計）以降は着手していない。
- Phase 4 コード・workflow・`config.yaml`・Compass DNA・公開 artifact・production data root は
  いずれも不変。J-Quants 再取得・閾値再測定も行っていない。

## v4.84 (2026-09-17) — Phase 5 TOPIX neutral-band 分布測定 runner（offline・threshold は決めない）

A0.7B-R2 で取得した隔離 research dataset（J-Quants v2 / 2021-09-17〜2026-09-17 /
TOPIX 観測 1,223 件・derived return_1d 1,222 件）を入力に、TOPIX の実現 close-to-close
日次 return 分布と候補 band ごとの UP / RANGE / DOWN 件数を**機械的に数える** runner を
搬入する。監督者決定 N-2（`NEUTRAL_RANGE` band）の材料であり、**threshold の選択・推奨・
最適化は行わない**。

### 追加 — `src/intelligence/predictions/topix_neutral_band_measure.py`

- 入力の権威は research root の `acquisition.json` と canonical `observations.jsonl` だけ。
  J-Quants / legacy journal / MarketSignal / CompassDraft / 公開 `/v2` / 代替 source は読まない。
  ネットワーク module を import しない（runner 自身が実行時に検査する）。
- **research root は読むだけ。** SQLite index を開かず canonical JSONL を直接読む。実行前後で
  root 配下全 file の sha256 が一致することを runner が検証する（`research_root_unmodified`）。
- realized_return = `close(session) / close(previous Tokyo trading session) - 1`（Decimal・
  **分類前に丸めない**）。derived `return_1d` は同じ式・同じ丸めで独立再計算し厳密一致を要求する。
- 分類は `UP: r > +X` / `RANGE: -X <= r <= +X`（**閉区間**）/ `DOWN: r < -X`。正式候補
  ±0.20 / 0.30 / 0.40 / 0.50% と文脈用 ±0.10 / 0.60 / 0.75 / 1.00% を同じ表で出す。
- 分布統計（N / 範囲 / mean / median / 標本 stdev / mean|r| / min / max / |r| の P25・P50・
  P75・P90・P95）。percentile は **nearest-rank**（補間なし）、method 名を出力へ記録する。
- 年別表（端の年は PARTIAL・内側は FULL）と、FULL 年だけの RANGE% min / max / spread。
  記述のみで、年安定性に対する最適化は行わない。
- 取得 marker と実データが食い違えば黙って続けない（件数・範囲・provider・derived 一致・
  合計保存・secret 不在など 19 項目を検証し、1 つでも落ちれば `MEASUREMENT_VALIDATION_FAILED`）。
  監督者承認値は `--expect-*` で明示 pin する（runner が期待値を作らない）。
- 出力は `::P5_TOPIX_NEUTRAL_BAND::{json}` ＋ 人間可読表。絶対 path・credential・
  顧客向け文言・推奨・MarketSignal 成績を含まない。任意の `--output` は research root 外・
  リポジトリ外・未存在 file のみ。
- `tests/intelligence/test_topix_neutral_band_measure.py`（26 tests・決定論的 fixture のみ）。
  境界の閉区間性・丸めない Decimal・nearest-rank・年別 PARTIAL/FULL・件数保存・取得 marker
  不一致と derived 不一致の fail closed・read-only・決定論・production 非依存を固定する。

### 未実施

- threshold の決定・Entry Contract 記述・P5-1 / P5-2・production 連携・Windows 実行は
  いずれも行っていない。Phase 4・workflow・config・production data root は不変。

pytest: 587 passed（production-derived suite 524 ＋ research driver guard 37 ＋ 測定 runner guard 26）

## v4.83 (2026-09-16) — Phase 5 一回限りの TOPIX research acquisition driver（取得はまだ行わない）

Phase 5 の `NEUTRAL_RANGE` band は、リポジトリが意図的に閾値を定義していないため
（`context/model.py`: `MAGNITUDE_CATEGORIES_ENABLED = False`「正当化できる閾値が
現時点のデータからは得られない」）、TOPIX の実データ分布を測ってから監督者が決める。
その測定に必要な実データがこの環境に 1 件も無いため（Market Bank は producer の
`runner.temp` へ毎回ゼロから再構築され永続化されない設計）、**production から完全に
隔離された one-time research dataset** を取得するための driver だけを搬入する。

### 追加 — Phase 5 research acquisition driver（offline 実装のみ）

- `src/intelligence/predictions/topix_research_acquire.py` を追加する。到達してよい
  endpoint は `/v2/indices/bars/daily/topix` と `/v2/markets/calendar` の **2 つだけ**で、
  他 provider（yfinance / stooq / treasury_gov / mof_japan）を 1 つも登録しないため
  構造的に到達できない。`pilot_runner` も呼ばない。
- **第二の J-Quants client を作らない。HTTP も ingest も再実装しない。** 既存の
  `JQuantsV2TopixProvider` / `JQuantsV2Client` / `MarketBankStore` / `ingest` /
  `derive_per_series` / `tokyo_calendar` をそのまま再利用する。
- **暗黙の production fallback を持たない。** `--research-root`（絶対 path）/
  `--start-date` / `--end-date` はすべて必須で、`data_root()` を読まない。
  リポジトリ配下・`data/vnext`・`output`・`docs`・`knowledge`・`.git` は拒否し、
  既存ディレクトリは空のときだけ許可する（非空は `NON_EMPTY_RESEARCH_ROOT`）。
  誤指定はネットワークアクセス前に fail closed。
- **期間を driver 自身が計算しない**（10 年を内部で作らない）。研究条件が実行ログから
  再現できるよう、start / end は常に明示引数で受け取る。
- credential は `JQUANTS_API_KEY` の runtime injection のみ。CLI 引数にも file にも
  log にも URL にも載せない。未設定ならネットワーク 0 回・ディレクトリ作成 0 回で停止する。
- 既存 provider の **20 page 安全上限を変更しない**。上限へ到達したら truncation を
  否定できないため、期間を勝手に短縮も分割もせず
  `RESEARCH_WINDOW_EXCEEDS_EXISTING_PAGINATION_CONTRACT` で停止する。
- 営業日判定は J-Quants 取引カレンダーの**実測検証済み区分だけ**で行う。weekday 演算へ
  フォールバックしない（検証できなければ fail closed）。
- 取得後、成功扱いする前に 13 項目を検証する（観測件数 / 合成 source 混入 /
  provider identity / 重複 trading_date / close 欠測 / 非正 close / カレンダー検証 /
  session gap / weekday fallback / raw close からの独立再計算と derived `return_1d` の
  一致 / secret 漏れ / repository 書き込み / production data root 書き込み）。
  1 つでも失敗すれば `ACQUISITION_VALIDATION_FAILED` とし、測定へ進まない。
- `tests/intelligence/test_topix_research_acquire.py` を追加する（34 tests・すべて
  offline。HTTP は注入した fake のみで実 API を使わない）。production isolation
  （legacy journal / publication / Pages / governance / Compass DNA / workflow /
  producer / `data_root` fallback への非依存）も機械的に固定する。

### 未実施（本エントリは取得を主張しない）

- **J-Quants API へのアクセスは 1 回も行っていない。** 実データ取得・分布測定・
  threshold 決定・Entry Contract の記述・P5-1 / P5-2 実装はいずれも未着手。
- production 面は一切変更していない。workflow・`config.yaml`・trust anchor・
  Compass DNA・Pages・`/v2`・producer スケジュールはすべて不変。`predictions` は
  production runtime closure から到達しない研究 subsystem のままである。

pytest: 558 passed（production-derived suite 524 ＋ 新規 research driver guard 34）

## v4.82 (2026-09-16) — 顧客向け Morning Brief「提示できない理由」の表示語彙修正

実機（iPhone）での表示レビューで、公開 `/v2` の Morning Brief Markdown に Compass
内部の abstain 詳細 `no_counter_material` がそのまま出ていることが確認された。
本エントリはその表示面の是正のみを記録する（意味論・公開 JSON・P4-3b2c 契約は
いずれも変更しない）。

### 修正

- **根本原因**: `render_markdown._unavailable()` が理由の**形**（snake_case）だけを
  見て表示を許可していた。v4.81 で data 境界に対して塞いだのと同じ
  「format を vocabulary と取り違える」欠陥が、1 層上の表示面に残っていた。
- **閉じた表示対応表 `REASON_JA` を追加**。production 経路から
  `BriefTier*.unavailable_reason` へ到達しうる内部理由 **13 値すべて**に、承認済みの
  顧客向け日本語（S1 材料不足 / S2 反対材料の規律 / S3 根拠不足）を明示的に割り当てる。
  値は承認済みの 3 文だけで、自由文も市場の見立ても作らない。
- **未知の理由は生値を出さない**。対応表に無い理由は汎用文
  「本日はこの区分を提示できません。」へ落ちる（表示は fail closed、配信は止めない）。
  到達しうる理由が写像漏れのまま増えた場合は test が build を落とす。
- **重複表示の抑制**。同じ説明が 3 区分に繰り返されないよう、2 度目以降は短い中立表現
  「本日はこの区分の提示を見送ります。」にする。**描画 1 回の中だけの局所状態**で行い、
  tier の可否・内部 `unavailable_reason`・`MorningBrief`・projection は一切変更しない。
- 理由を差し込む表示テンプレートと、表示可否を形だけで判定していた正規表現を削除した
  （同じ誤りを再び招かないため）。方向・確度・対象期間・次元・充足状況の既存対応表と
  `UnmappedDisplayValue` の fail closed はそのまま維持する。
- **意味論は不変**: 同一入力に対する `brief_id` / `signal_id` / `MorningBrief` 意味
  payload / `MarketSignal` 意味 payload / 内部 `unavailable_reason` / 公開 unavailable
  語彙（6 値）/ artifact 4 file 契約 / `/v2` 5 file topology / selector・trust・
  freshness 定数 / legacy 出力は**すべて変更なし**。
- **内容由来で変わるもの**（契約 drift ではない）: 描画後の Markdown bytes、
  `markdown_sha256`、`markdown_bytes`、およびそれらから導出される `delivery_id`。
- P4-3b2c は CLOSED / FROZEN のまま。producer は unscheduled のまま。trust anchor
  （`29c3beaf0c32c56ab5c4129aee89dbd1e06aec8b`）・config・スケジュール・Pages 構成・
  single deployer・workflow はいずれも変更しない。feature branch への同期は行わない。
- 本エントリは P4 Presentation Review の完了を主張しない。公開面への反映は、別途承認
  される新規の producer 実行と自然 consumer 実行を経て初めて確認される。

## v4.81 (2026-09-16) — 公開 unavailable 語彙の境界修正（内部 abstain 詳細の漏れ出し）

production producer の**修正後の再実行** **run 35081366821**
（`workflow_dispatch` / branch=main / head=`9ae0d42` / attempt=1）が失敗した。
本エントリはその是正のみを記録する（trust anchor と P2 契約は変更しない）。

### 修正

- **前回の修正は成功している**。`python -m` 依存の取りこぼし（v4.80）は解消され、
  market data bank live pilot は 10m22s かけて **success**、16/16 系列取得成功、
  `::P2D_PERSISTENCE:: ok=true / fresh_process=true / mismatch []` まで到達した。
  `No module named src.intelligence.market.persistence_check` は再現していない。
- **新しい独立した欠陥**が 2 steps 先で発生した。Morning Delivery producer が
  公開 JSON を組み立てる時点で
  `UnmappedDeliveryState: unavailable reason is not publishable: 'no_counter_material'`
  を送出し exit 1。市場データ側の不具合ではない。
- **根本原因**: `market_signal._safe_reason()` が理由の**形**（snake_case）だけを
  検査していたため、Compass 内部の abstain 詳細（`no_counter_material` など）が
  承認済み fallback へ落ちずに配信面へ素通りしていた。配信側の公開語彙
  `PUBLIC_UNAVAILABLE_REASONS` は 6 値の閉じた契約であり、内部詳細は非公開語彙
  なので fail closed で停止した（配信側の判断は正しい）。
- `_safe_reason()` を**承認語彙による正規化**へ変更。承認語彙でない候補は形が
  妥当でも呼び出し側が指定した承認済み fallback へ決定論的に写像する。実在する
  内部 abstain 理由 **10 値すべて**が `draft_abstained` へ正規化される。
  branch ごとの意味は fallback が保持し、`draft_not_usable` /
  `tier3_unavailable` / `no_outlook` / `direction_mixed` / `direction_uncertain`
  は従来どおり（無関係な状態を 1 つの理由へ潰さない）。
- **公開語彙は不変**。`PUBLIC_UNAVAILABLE_REASONS` に内部詳細を 1 つも追加しない。
  `delivery.py` の fail closed（`UnmappedDeliveryState`）も**弱めない**——境界の
  後で未承認値を注入すれば今も停止することを test で拘束する。
- **語彙境界の専用回帰ガードを新設**（`tests/intelligence/test_public_unavailable_vocabulary.py`）。
  昇格済み Compass 経路から `abstain_reason` へ到達しうる内部理由を AST で実測し、
  その 1 つ 1 つを本物の `build_market_signal()` に通して承認語彙になることを要求する
  （`no_counter_material` を 1 件だけ試すのではない）。構造ガード
  `test_p43b2c_production_bundle.py` は変更しない。
- **trust anchor は不変**（`29c3beaf0c32c56ab5c4129aee89dbd1e06aec8b`）。
  producer workflow・スケジュール・Pages 構成・single deployer・config はいずれも
  変更しない。**producer は unscheduled のまま**。
- 失敗した run 35081366821 は **artifact を 1 件も生成していない**
  （`morning-delivery-v2` なし）。公開も root cutover も発生しておらず、legacy は
  影響を受けていない。
- 本エントリは producer の**復旧を主張しない**。復旧は、別途承認される新規の
  one-shot dispatch が成功して初めて確認される（frozen first-attempt-only により、
  失敗した run の再実行は適格にならない）。

## v4.80 (2026-09-16) — P1 bundle 完全性の修正（`python -m` 依存の取りこぼし）

production producer の初回本番実行 **run 35078193591**
（`workflow_dispatch` / branch=main / head=`ce8d08c` / attempt=1）が失敗した。
本エントリはその是正のみを記録する（trust anchor と P2 契約は変更しない）。

### 修正

- **根本原因**: `src/intelligence/market/pilot_runner.py` は永続化ゲートを
  `python -m src.intelligence.market.persistence_check` として **subprocess 起動**する。
  P1 の runtime allowlist は **import closure**（AST の import / from-import）から
  導出しており、import されないこの依存を取りこぼしていた。結果として
  `src/intelligence/market/persistence_check.py` が production main に存在せず、
  producer は `No module named src.intelligence.market.persistence_check` で
  exit 1 した。市場データ取得自体は 16/16 系列 success・全 fetch HTTP 200 で、
  取得ロジックの不具合ではない。
- `src/intelligence/market/persistence_check.py` を production main へ搬入
  （本番 runtime 面 140 → 141 ファイル）。
- **production bundle guard を拡張**し、`python -m <module>` による明示的な
  module 実行を runtime 依存の完全性検査に含めた。list / tuple literal の要素が
  ちょうど `"-m"` で直後が `src.` で始まる文字列定数のときだけ依存とみなす
  決定的規則で、文字列本文の走査・動的推論・discovered module の実行は行わない。
  認識した target が未搬入なら fail closed。既存の import closure 検査は保持する。
- **trust anchor は不変**（`29c3beaf0c32c56ab5c4129aee89dbd1e06aec8b`）。
  P2 の active-state 契約・producer workflow・スケジュール・Pages 構成・
  single deployer はいずれも変更しない。**producer は unscheduled のまま**。
- 失敗した run は **artifact を 1 件も生成していない**（`morning-delivery-v2` なし）。
  公開も root cutover も発生していない。legacy は影響を受けていない。
- 本エントリは producer の復旧を主張しない。復旧は、別途承認される
  **新規の one-shot dispatch** が成功して初めて確認される
  （frozen first-attempt-only により、失敗した run の再実行は適格にならない）。

## v4.79 (2026-09-16) — P2 P4-3b2c production trust baseline の有効化

P1（v4.78・commit `29c3bea`）で dormant 搬入した P4-3b2c 公開面を、production
trust anchor を設定して**有効化**する。本エントリは **P2 のみ**を記録する
（R0 と P1 は v4.78 に記録済みで、その記述は変更しない）。

### 改善

- **production trust anchor = P1 の SHA `29c3beaf0c32c56ab5c4129aee89dbd1e06aec8b`**。
  本番 workflow の `P43B2C_TRUST_BASELINE` と `config.yaml` の policy mirror
  `production_trust_baseline` が、同一の anchor を指す。
- **本番 guard を P1 dormant-state 不変条件から P2 active-state 不変条件へ明示的に遷移**。
  `test_production_trust_baseline_is_empty` を廃し、
  `test_production_trust_baseline_is_the_approved_anchor`（非空・40 桁 hex・
  検証専用 baseline 拒否・承認 anchor と完全一致）と
  `test_config_trust_baseline_mirrors_the_workflow_anchor`（workflow と config が
  同一 anchor）を置く。「空 or 承認 SHA」という曖昧な不変条件にはしない。
  P1 の dormancy 契約は git 履歴・P1 commit・P1 の live evidence が引き続き記録する。
- **producer は unscheduled のまま**。schedule を持たず、push trigger は feature
  branch に限定され、main 上では自動発火しない。Pages 権限も持たない。
- **本 commit の時点で production-eligible な producer artifact は存在しない**
  （producer は main 上で 1 度も実行されていない）。
- したがって **`/v2` は自動的には現れない**。`/v2` は、信頼できる適格な artifact が
  存在するときにだけ公開される。存在しない間、本番は
  `V2_UNAVAILABLE / NO_TRUSTED_ARTIFACT` を返し legacy のみを publish する。
- **v2 が利用できないとき legacy が引き続き唯一の正**であり、配信は阻害されない。
- **root cutover は行わない**。`/v2` は legacy root の配下へ接ぎ木される設計で、
  Pages の artifact / deploy は従来どおり 1 本ずつ。notifier 挙動も不変。
- rollback は本 commit の revert 1 手。baseline が空へ戻り guard も P1 契約へ
  自動復帰し、`/v2` だけが止まる（R0 と P1 は影響を受けない）。

## v4.78 (2026-09-16) — R0 機密ソース tracking 是正（landed）＋ P1 P4-3b2c dormant promotion

> **版番号に関する開示（重要）**
> v4.7〜v4.77 は **feature branch 上で維持されている開発版エントリ**であり、
> **production main のリリースとして解釈してはならない**。main の CHANGELOG は
> v4.6 の次に本 v4.78 が続く。
> 本 v4.78 エントリが記録するのは、実際に production main へ landed した次の
> **2 件のみ**である。
> 1. R0 セキュリティ是正（SHA `e384bb2`）
> 2. P1 dormant production promotion
> それ以外の feature branch 上の機能は、本エントリでは main へ持ち込まれない。

本エントリは**別々の 2 つの変更**を記録する。両者を 1 つの変更として扱わないこと。

### 修正 — R0（セキュリティ是正・commit `e384bb2`・landed 済み）

- 機密ソースの **forward tracking 是正**。承認済みの CONFIDENTIAL_SOURCE 10 件と
  SENSITIVE_IDENTIFIER 2 件の Git tracking を index-only で解除し、再追加を防ぐ
  `.gitignore` 保護規則を追記した（挿入のみ・16 行）。
- **現在および将来の tracking 露出は解消**した。production main の tracked
  機密ファイルはゼロであり、保護規則により再追加もされない。
- **Git 履歴の露出は未解消**。R0 は履歴を書き換えておらず、過去 commit の blob は
  到達可能なまま残る。履歴側の除去（**H0**）は
  `docs/security/HISTORY_REMEDIATION_EXECUTION.md` §5 の独立した作業として継続中で
  あり、**完了していない**。
- ディスク上の原本は削除していない。ただし当該パスを tracking 中の他クローンでは、
  pull 時に作業ツリーから当該ファイルが消える。

### 追加 — P1（P4-3b2c dormant production promotion）

- Morning Delivery `/v2` の並走公開面を production main へ搬入する。ただし本 commit
  では **dormant（休眠）**であり、公開挙動は一切変わらない。
- `P43B2C_TRUST_BASELINE` は **空文字のまま**。空 baseline のとき selector は
  `V2_INTERNAL_ERROR / CONFIGURATION_INVALID` で安全に skip し exit 0 を返すため、
  legacy の配信は阻害されない。**`/v2` は有効化されない。**
  trust baseline の有効化は将来の独立した変更（**P2**）であり、本 commit には含まれない。
- **legacy が引き続き唯一の正（authoritative）**。root の切り替え（**cutover は行わない**）。
  `/v2` は legacy root の配下へ接ぎ木される設計で、Pages の artifact / deploy は
  従来どおり 1 本だけ。
- 搬入物: `src/intelligence/**` の runtime closure（entry point 3 つから再計算した
  140 ファイル）、`scripts/p43b2c_*.py` の CI utility 4 本、producer / 検証支援 /
  preview の workflow 3 本、`config.yaml` の `pages_parallel_publication` policy
  section、`knowledge/` の参照リソース 2 件、公開用静的アセット 1 件、
  governance ドキュメント 2 件、production guard テスト。
- producer・preview・検証支援の各 workflow は **main 上では発火しない**
  （schedule なし・push trigger は feature branch へ限定・Pages 権限なし）。

## v4.6 (2026-07-20) — Rashinban Private Insight Vault（private記事の転送・入力UI・Future Outlook）

レポート画面から気になった記事本文を貼り付けてData Tankの非公開領域へ転送し、
AI分析（要約・所感・因果・市場影響・シナリオ形式の未来予測・検証条件）の
派生情報だけをレポートへ反映する機能。両リポジトリはPublicのため、本文は
Cloudflare Worker + KV（非公開・AES-GCM暗号化）にのみ保存し、GitHub Pages・
公開リポジトリ・公開JSONへは構造的に出ない設計（allowlist方式）。

### 追加

- `cloudflare/private-insight-worker.js`（新規・既存trigger-report-workerとは別モジュール）:
  Private Intake API。POST /intake（保存）、GET /status・/list、POST /delete・/memo・
  /reanalyze（人間向け・X-Insight-Keyパスフレーズ認証）、GET /queue・POST /analysis・
  GET /derived（機械向け・Bearer認証）、GET /admin（認証付き管理画面）。
  本文はAES-GCM暗号化してKVへ保存。レート制限・ハッシュ重複検知つき。
  Secrets（パスフレーズハッシュ・トークン・暗号鍵）はWorker Secretのみで、HTMLへは埋め込まない。
- `cloudflare/private-insight-wrangler.toml.example`: KV binding・Secrets設定手順。
- `src/data/private_insight_client.py`（新規）: 派生情報の取得クライアント。
  `config.private_insight_intake.api_url` とSecrets `INSIGHT_API_TOKEN` の両方が
  揃わない限り**完全に無効**（ネットワークアクセスなし）。失敗時はunavailableを返し
  例外を投げない（レポート生成は止まらない）。
- `src/report/html_builder.py`: 「🧠 Rashinban Private Insight Vault」入力カード
  （本文textarea＋パスフレーズpassword欄＋転送ボタン。送信失敗時は本文を画面に保持、
  成功時のみクリア。localStorage下書き保存）と「🔮 Private Research Future Outlook」
  カード（シナリオ・確認指標・次回検証日・AI所感。取得失敗時は注記のみ表示で
  レポート本体は通常生成）を追加。
- `src/analysis/models.py`: `PrivateInsightOutlook` dataclassと
  `AnalysisBundle.private_insight_outlook`（デフォルトNoneで後方互換）。
- `main.py`: `_safe_call`経由で派生情報取得を配線（失敗してもレポート継続）。
- `config.yaml`: `private_insight_intake:` ブロック（enabled/api_url/max_body_chars等。
  api_url空文字がデフォルト＝機能オフ）。
- `.github/workflows/daily-market-brief.yml`: `INSIGHT_API_TOKEN` Secretのenv渡しを追加。
- `tests/test_private_insight_vault.py`（新規11件）: クライアントの
  disabled/ok/unavailable、入力カードのSecret非埋め込み、Outlookカード、
  フルレポート互換を検証。

### pytest

451 passed（既存440＋新規11）。

## v4.5 (2026-07-20) — 通信社系接頭辞をまたぐ重複ニュースの排除

ライブ運用のレポートで、同一記事を別媒体が配信し片方だけに "Analysis:" が付く
ケース（例:「Could AI chip boom make ASML…」と「Analysis:Could AI chip boom
make ASML…」）が重複排除をすり抜け、Executive Summary・重要ニュースランキング・
岡三ストラテジスト視点に同じニュースが2件並んでいた。見出し正規化に通信社系
接頭辞の除去を追加して解消した。

### 変更

- `src/collectors/news.py`: `_normalize_title`の先頭処理に`_strip_wire_prefix`を追加。
  Analysis / Exclusive / Breaking / Factbox / Explainer / Column / Insight /
  Timeline / Opinion / Feature / UPDATE N- / WRAPUP N- / RPT / REFILE /
  Live markets / Live / Graphic、および日本語（速報／独自／焦点／コラム／特集／
  解説／分析）の接頭辞を1回だけ剥がしてから正規化する。剥がすと空になる異常
  見出しは元のまま扱い、誤統合を防ぐ。この正規化はニュース収集の重複排除と
  Data Tankシグナルのタイトル照合の両方で共通に使われるため、Tank由来・
  既存RSS由来をまたぐ重複にも一貫して効く。
- `tests/test_collectors.py`: Analysis接頭辞・UPDATE/日本語接頭辞をまたぐ統合、
  接頭辞のみ見出しの非空保証を検証するテストを3件追加。

### pytest

440 passed（既存437＋新規3）。

## v4.4 (2026-07-20) — 情報の整理＋コンパクト表示の最適化

ライブ運用のレポートで確認された表示ノイズ（主要因への無関係な単発記事の混入・
テーマ集計最上位のuncategorized 614件）を整理し、コンパクト表示を「重要度の低い
カードだけを自動で畳む」動作に最適化した（重要なものは常に見える）。

### 変更

- `src/report/html_builder.py`（①情報整理）:
  - `_ext_intel_cluster_list_html`: importanceが0かつ関連記事1件のエントリ
    （スコア未計算の旧データ・単発の無関係記事）を表示から除外。有意なエントリが
    無ければ見出しごと非表示。
  - `_ext_intel_theme_summary_html`: "uncategorized"を表示から除外
    （Tank側v0.5.0でも集計から除外するが、旧Packageへの防御として表示側でも弾く）。
- `src/report/html_builder.py`（②コンパクト表示の最適化）:
  - `_card`: 重要度（★×20）を`data-imp`属性としてカードへ付与
    （★の無いトップサマリー＝相場総括・Today's Decision等には付与しない）。
  - コンパクト表示ON時、重要度60以下のカードを自動で折りたたむ
    （80〜100と★無しカードは開いたまま＝重要なものは常に表示）。自動で畳んだ
    カードはOFF時に開き直す（元から畳んである営業メモ等はそのまま）。畳まれた
    カードも▾ボタンで個別に開ける。
  - コンパクト表示中はカード説明文（card-desc）も非表示にして情報密度を上げる。
- `tests/test_v4_external_intelligence.py`: ノイズ除去・uncategorized除外・
  data-imp属性・コンパクト折りたたみスクリプトの存在を検証するテストを4件追加。

### 関連: Article Intelligence Data Tank v0.5.0（別リポジトリ）

主要因のimportance全0.00の根本原因（記事スコア未計算）はTank側v0.5.0で修正。
詳細は当該プロジェクトのCHANGELOGを参照。

### pytest

437 passed（既存433＋新規4）。

## v4.3 (2026-07-20) — Tankの市場反応スコアをニュースランキング・ストラテジスト採点へ統合

Data Tank側は各記事について「どのイベントクラスタに属するか」「そのイベントで
実際に市場が動いたか（market_reactions）」「市場影響度スコア」まで計測済みだが、
これまでbrief側の採点（重要ニュースランキングの★・岡三ストラテジスト視点の8軸）には
一切使われていなかった。本バージョンで、この計測済みシグナルを採点へ機械的に
転記する（brief側での再計算・生成はしない。Tank未接続時は従来と完全に同じ採点）。

### 変更

- `src/analysis/external_intelligence.py`: `build_tank_signal_lookup()`を追加。
  hot_articles を「タイトル正規化キー（news._normalize_title と同一）→
  has_market_reaction / in_global_drivers / market_impact_score / importance_score」の
  ルックアップへ変換する。既存の重複判定と同じ正規化を使うため、Tank由来でも
  既存RSS由来でも「同じニュース」なら同じキーで引ける。
- `src/analysis/news_ranking.py`: `build_news_ranking(..., tank_signals=None)`を追加。
  一致した見出しへ「実際の市場反応が確認済み: +3（Market Reaction First）／
  主要因クラスタ該当: +2／市場影響度スコア0.6以上: +1」を加点し、理由文にも明記。
- `src/analysis/strategist_engine.py`: `score_headline_8axis(..., tank_signal=None)`・
  `build_strategist_views(..., tank_signals=None)`を追加。8軸の「市場インパクト」を
  市場反応確認済み+2／主要因該当・高影響度+1し、確認済みの場合はストラテジストの
  見方に「相場への影響が既に現れている可能性」の一文を補足（他の7軸は不変）。
- `main.py`: `build_tank_signal_lookup`を`_safe_call`で呼び、news_ranking・
  strategist_engine の両方へ`tank_signals`を配線。取得失敗時は空dict＝従来動作。

### pytest

433 passed（既存427＋新規6）。

## v4.2 (2026-07-20) — Data Tankの精査済み結果（主要因・リスク・テーマ集計）を表示

Data Tank側は既に記事のクラスタリング・市場反応評価・重要度スコアリングまで
済ませた`global_drivers`（Market Reaction First順の主要因）・`risk_radar`・
`theme_summary`を配信パッケージに含めている。これまではExternal Intelligenceカードに
件数しか表示していなかったが、この精査済みの中身（タイトル・関連記事数・
importance・関連国）を実際に読み取って表示するようにした。daily-market-brief側で
再計算・再ランキングは行わず、Data Tank側の結果をそのまま表示する（重複計算をしない）。

### 変更

- `src/report/html_builder.py`: `_ext_intel_cluster_list_html()` /
  `_ext_intel_theme_summary_html()`を追加。External Intelligenceカードに
  「Data Tank発の主要因」「Data Tank発のリスクレーダー」「Data Tank発のテーマ集計」の
  3リストを追加表示（各上位5〜8件。Tank側のランキング順をそのまま使用）。
  bundleがNone、またはリストが空の場合は何も追加表示しない（既存動作に影響なし）。
- `tests/test_v4_external_intelligence.py`: 上記3リストの表示内容・空リスト時の
  非表示・bundle=None時の空文字返却を検証するテストを3件追加。

### pytest

427 passed（既存424＋新規3）。

## v4.1 (2026-07-20) — External Intelligence 段階的接続（hot_articlesをニュースパイプラインへ合流）

v4.x で追加したConsumer Client（取得・表示のみ）を一歩進め、Data Tankの
`hot_articles`（allowlist済みの公開ビュー）を既存のニュース収集パイプラインへ
実際に合流させた。大規模リファクタリングは行わず、既存の`news.dedupe_headlines`
（タイトル正規化ベースの重複排除）へそのまま乗せる形で接続している。

### 変更

- `src/analysis/external_intelligence.py`: `hot_articles_to_headlines()`を追加。
  Data Tankのhot_articles（title/url/source/published_at/source_trust）を
  既存の`Headline`（`src/collectors/news.py`）へ変換する。`source_trust`
  （0.0〜1.0）をそのまま`reliability`として引き継ぐため、既存RSSと同じ
  ニュースをData Tankも配信していた場合は信頼度の高い方へ自動的に統合される。
  本文（public_excerpt等）はHeadlineに保持フィールドが無いため引き継がない
  （構造的に本文が混入しない）。
- `main.py`: Data Tankの取得・bundle化を既存ニュース収集の直前へ移動し、
  変換したHeadlineを`raw_headlines`（重複除去前）へ合流させた（重複取得は
  行わない・取得失敗時は空リストのままで既存動作に影響なし）。
- `src/report/html_builder.py`: 「External Intelligence（Data Tank連携）」カードの
  説明文を、実際の接続状況に合わせて更新（「参考情報として表示するのみ」→
  「重要ニュースランキング・テーマ分析等へ合流」）。
- `tests/test_v4_external_intelligence.py`: `hot_articles_to_headlines`の
  フィールド変換・欠損データのスキップ・信頼度デフォルト値、および既存
  `dedupe_headlines`との統合（重複ニュースの統合・非重複ニュースの共存）を
  検証するテストを5件追加。

### pytest

424 passed（既存419＋新規5）。

## v4.x (2026-07-17) — External Data Foundation（Article Intelligence Data Tank連携・Consumer Client）

別リポジトリ・別プロジェクトとして新規作成した Article Intelligence Data Tank
（数千〜数万件のニュース記事を取得・分析し、軽量なPublished Intelligence Package
だけを配信する独立基盤）から、Market Intelligence System 側が**軽量なConsumer
Client**だけを追加して接続できるようにした。既存Engineの分析ロジックは一切変更せず、
AnalysisBundleへの追加接続（保持のみ）に留める。Data Tank未設定・障害時も
レポート生成は通常通り継続する（完全な後方互換）。

### 追加

- `src/data/external_intelligence_client.py`【新規】: ExternalIntelligenceClient。
  manifest取得→package取得→gzip展開→checksum検証→schema検証→cache保存→
  timeout/retry→stale判定→fallback、を行う薄いクライアント。manifest_url/
  package_url未設定なら即座にdisabled（ネットワークアクセスなし）。
- `src/analysis/external_intelligence.py`【新規】: package/statusから
  `ExternalIntelligenceBundle`を組み立てる（Market Intelligence側で件数上限を
  再度防御的にキャップ）。
- `src/analysis/models.py`: `ExternalIntelligenceBundle`データクラス追加、
  `AnalysisBundle.external_intelligence`（デフォルトNone・後方互換）を追加。
- `src/report/html_builder.py`: 「External Intelligence（Data Tank連携）」カードを
  追加（取得状況のみ表示・記事本体は転載しない。bundle未設定/Noneなら空文字＝
  従来通り）。
- `config.yaml`: `external_intelligence`ブロック（enabled/manifest_url/package_url/
  timeout_seconds/retry_count/latest_minutes/warning_minutes/stale_minutes/
  cache_enabled/cache_dir/fallback_to_cache/fallback_to_legacy_news）を追加。
  URL空欄の間は完全に無効化され、既存動作に一切影響しない。
- `main.py`: `ExternalIntelligenceClient`の呼び出しを`_safe_call`で追加し、
  `analysis_bundle.external_intelligence`へ格納するのみ（既存Engineの入力には
  まだ使わない・将来の段階的接続の基盤）。
- `tests/test_v4_external_intelligence.py`【新規】: manifest/package取得・
  checksum/schema検証・latest/warning/stale判定・timeout/retry・cache更新/
  fallback・legacy fallback・URL未設定時の後方互換・Data Quality表示・
  件数上限・既存pytest互換など16件。

### 関連: Article Intelligence Data Tank（別リポジトリ・別納品物）

`article-intelligence-data-tank/` として独立プロジェクトを新規作成（本リポジトリの
配下ではない）。記事取得・正規化・重複排除・分類・イベント統合・市場影響分析・
永続保存・配信パッケージ生成を担う。詳細は当該プロジェクトの README.md /
CHANGELOG.md を参照。

### pytest

419 passed（既存403＋新規16）。

## v4.x (2026-07-14) — Six Daily Report Schedule & Reliability Upgrade（1日6回・信頼性運用）

レポートをJST基準で1日6回（07:30/09:10/11:30/12:40/15:40/17:20）自動生成する信頼性運用の
基盤を追加。通常6回＋各15分後の欠損回復チェック6回をGitHub Actionsに設定し、実行記録・
二重生成防止・自動再試行・欠損回復・履歴保存・生成状況HTML表示を実装。既存の手動実行・
Cloudflare Workerワンタップ・GitHub Pages公開・既存レポート生成は一切壊さない。

Phase 0（既存構造の調査）
- schedule cron はUTC・単発（"0 22 * * *"）。main.py は output.timezone(Asia/Tokyo)で now を
  算出。build_html_report はトップカード群を組み立て、latest_market_brief.html を output/ へ出力し、
  workflow が pages-site/index.html へコピーして GitHub Pages 公開。Cloudflare Worker は inputs 無しで
  workflow_dispatch する（→ 追加 inputs は全て default 必須）。

追加（新規ファイル）
・src/analysis/report_schedule.py【新規】— JST/UTC変換、通常/回復cron生成、cron→(slot_id,mode)対応、
  直前slot解決、実行記録(data/report_runs/YYYY-MM-DD.json)のatomic読み書き、二重生成防止・stale判定、
  HTML用スロット状態算出。純粋ロジック（副作用は記録の読み書きのみ）。
・src/report/schedule_status.py【新規】— 「本日のレポート生成状況」カード（6スロット・現在表示中・
  欠損警告）をHTML化する純粋関数。データ無しなら空文字。
・scripts/resolve_report_schedule.py【新規】— GitHub Actionsでcron文字列/dispatch入力から
  (slot_id,mode,trigger_type,force,recovery)を解決しGITHUB_OUTPUTへ書く。巨大シェルif文を回避。
・tests/test_v4_report_schedule.py / tests/test_v4_schedule_main.py【新規】— §19のテスト31件。

改善（既存ファイル・最小差分・後方互換）
・main.py — CLI引数 --report-slot/--trigger-type/--force/--recovery を追加（省略時は従来の臨時生成で
  スケジュール管理に一切関与しない＝完全な後方互換）。スロット指定時のみ: 二重生成防止判定→
  runningで記録開始→生成→HTML妥当性チェック→最新indexをatomic更新（不正時は前回版を維持）→
  履歴HTML保存→success/failedを生成メタデータ付きで記録。生成状況カードのコンテキストをHTMLへ渡す。
・src/report/html_builder.py — build_html_report に schedule 引数（省略可）を追加し、トップに
  生成状況カードを描画（未指定なら空文字＝従来通り）。カード用CSSを追加。
・config.yaml — report_schedule ブロック（enabled/timezone/run_on_weekends/run_on_japanese_holidays/
  archive_reports/recovery_enabled/max_retry_count/retry_wait_seconds/stale_after_minutes/
  recovery_offset_minutes/runs_dir/history_dir/slots×6）を追加。
・.github/workflows/daily-market-brief.yml — 通常6cron＋回復6cronを設定。workflow_dispatch に
  report_slot(choice,default auto)/force/recovery(default false) を追加（inputs無しdispatchでも動作）。
  concurrencyでslot単位に直列化(cancel-in-progress:false)。slot解決ステップ→最大2回の自動再試行→
  自動生成ファイルのみcommit(force pushなし・pull --rebaseで競合回避)→履歴もpages-siteへ同梱。

制約遵守
・新規ニュース取得・新しい外部API・生成AI文章生成・World/Geopolitical Engine・大規模UI再設計・
  分析ロジックのリファクタは一切なし。Secret/Tokenはログ・HTML・JSへ出さない。
・JST基準を厳守（cron時刻からJST日付を推測しない）。

テスト: 403 passed（既存372＋新規31）。

## v3.6 (2026-07-09) — Strategic Narrative Engine「朝会3分・トップストラテジスト級」化

v3.5.3で方向整合は取れたが、Market Narrativeを「証券会社トップストラテジストが朝会で3分説明する
レベル」に引き上げる。新Engine（Strategic Narrative）のみを強化し、既存Engineは変更しない。
新しいニュース取得・新しいAPI・生成AIによる推測・断定的な将来予測・個別売買助言は一切行わず、
既存の算出済みエンジン結果だけを機械的に組み替える。既存データのみ・後方互換・最小差分・pytest全通過。

Phase 0分類
- A（既存で十分・再利用）: Market Data / Market Regime / Cross Market / News Ranking /
  News Impact / Future Intelligence / Theme Momentum / Scenario / Market Breadth /
  Analysis Confidence / Macro Events(Weekly Events) / Watchlist。
- B（少し直せば使える＝今回）: strategic_narrative.py（市場心理・主因ランキング・総括・
  30秒・因果チェーン・自己評価を強化）と html_builder.py の描画。
- C（新規追加）: StrategicNarrative に deep_causal_chain / key_points / self_score /
  self_check / self_improvement フィールドを追加。
- D（やらない）: 生成AI作文／新規データ取得・新API／個別寄与額の捏造／既存Engine変更／大規模リファクタ。

改善内容（①〜⑨）
・① 原因の原因まで遡る因果チェーン `deep_causal_chain`（ニュース→原油→インフレ→金利→バリュエーション
  →為替→セクター→日経）。取得データで裏付く節・ニュース見出しにある語だけを繋ぐ（推測禁止）。
・② 今日の市場心理を主因ランキング1位のcategory/directionから毎日自動生成（固定文を廃止・主因と必ず一致）。
・③ 主因ランキングを「総合影響度」で決定＝値動き×重み＋News Ranking/Impactの関連件数・最大Impact
  ＋Cross Market登場（`_news_boost`/`_cross_boost`）。★も総合影響度から付与、noteに関連ニュース件数。
・④⑧ ストラテジスト総括を「①何が起きたか②なぜ③何を織り込んだか④想定と違った点⑤明日確認」の
  5部構成・一本のストーリーに（200〜300字目安・テンプレ羅列を排除）。
・⑤ Cross Marketを文章化（何が勝ち何が負けたかを自然文で・矢印羅列でない）。
・⑥ 営業向け30秒を会話調へ（「◯◯にもかかわらず下落」等の逆行を検出し「今後は〜が焦点になります」で締める）。
・⑦ 今日覚えること3つ `key_points`（最大要因／市場参加者が見ていたもの／明日見るべき点）を可視化。
・⑨ ルールベースの自己評価 `self_score`(100点満点)・`self_check`(5観点OK/NG)・`self_improvement`
  (80点未満の改善案)。観点=市場心理と主因の一致／因果チェーンの連続性／背景説明／営業30秒の実用性／ストーリー性。
・HTML描画: 【今日覚えること（3つ）】を可視ブロック追加、詳細に【市場が織り込んだ流れ（原因の原因まで）】と
  【分析セルフチェック（自己評価 N/100）】を追加。strategic_narrative が None の場合は従来表示にフォールバック。

テスト
- 追加: tests/test_v3_6_strategist_grade.py（14件）— 深い因果チェーン／心理と主因の一致・可変性／
  総合影響度加点／5部構成総括／Cross Market文章化／営業30秒の逆行検出／key_points3件／自己評価／
  禁止表現・売買助言なし／空データ安全。
- 既存: v3.5.2/v3.5.3の文言依存アサーション（「ポイント」→「焦点」等）をv3.6の文言へ更新。
- 結果: 372 passed。

## v3.5.3 (2026-07-08) — Strategic Narrative Engine Accuracy Fix（主因・因果・材料分類の矛盾解消）

v3.5.2で文章の形は良くなったが、主因判定・因果・材料分類に矛盾（日経下落なのにSOX上昇を
主因扱い等）が出ていた問題を修正。UIではなく分析ロジックを直し、「市場参加者が何を嫌気し、
何を支えにした結果、日経平均がどう動いたか」が分かる分析へ。既存データのみ・後方互換・最小差分。

Phase 0分類
- A（既存で十分）: Market Regime / Cross Market / News Ranking / News Impact /
  Future Intelligence / Scenario / Weekly Events / Analysis Confidence / Watchlist /
  Market Breadth / Theme Momentum / anomalies（判定材料は揃っている）。
- B（少し直せば使える＝今回）: strategic_narrative.py の材料分類・主因選定・テンプレート
  （形はあるが方向整合が取れていなかった）。
- C（新規追加）: StrategicFactor に direction / category を追加（方向を一意化）。
- D（やらない）: 生成AI作文／新規データ取得／個別銘柄の寄与額の捏造／大規模リファクタ。

修正内容（改善①〜⑬）
・① 日経平均の方向を先に判定（<=-0.5%下落 / >=+0.5%上昇 / それ以外は横ばい）。
・② 各材料を「日経平均にとって」positive/negative/neutral へ分類（金利↑=negative、SOX↑=
  positive、原油↑=negative、円安=positive、VIX20未満=positive/以上=negative 等）。categoryも付与。
・③ 主因ランキングは日経の方向と一致する材料だけから作る（下落日はnegativeのみ／上昇日は
  positiveのみ／横ばいは両方を寄与順）。→ 日経下落日にSOX上昇が主因に入らない。
・④ 押し下げ材料と下支え材料の重複を排除（directionが一意なので同一materialは片方だけ）。テスト追加。
・⑤ 不自然な因果表現を禁止し、安全なテンプレートに統一（「米金利上昇は高PER株の重荷」
  「原油高はインフレ警戒材料」「SOX上昇は半導体の下支え」等）。禁止表現テスト追加。
・⑥ 本日の一言を方向＋主因から生成（下落日「〜が重荷となり、日経平均は下落しました」／上昇日
  「〜が支えとなり、上昇」／横ばい「〜が交錯し、方向感に乏しい」）。
・⑦ 市場心理を金利/NASDAQ・SOX/原油/VIX/決算/AIニュースから、日経方向に最も説明力のある形で選定。
・⑧ 「なぜ日経は動いたか」を段落ロジック化（結果→背景（同方向材料）→一方で（逆方向材料は
  下支え/重荷だが打ち消せず/優勢に））。
・⑨ Cross Marketを力関係で説明（どちらの材料が勝ったか。SOX上昇でも日経下落なら「SOXは支えだが
  金利上昇・米国株安の影響が上回った」と明記）。
・⑩ ストラテジスト総括200〜300字（方向／主因／逆方向材料／市場心理／今後の見るポイント）。
・⑪ 営業向け30秒説明も方向整合（SOX上昇を重荷扱いしない）。
・⑫ 出力構成を整理（一言→市場心理→なぜ動いたか→主因ランキング→押し下げ/下支え→Cross Market
  →シナリオ→総括→30秒→詳細）。
・⑬ テスト追加（下落日SOX上昇=下支え・主因除外／金利上昇=押し下げ／上昇日SOX上昇=押し上げ／
  上昇日原油高=重荷／横ばい交錯／重複なし／禁止表現なし／総括の主因が方向一致／30秒の矛盾なし）。

StrategicFactor に direction / category を追加（デフォルト付き・後方互換）。既存テスト全通過。

## v3.5.2 (2026-07-08) — Strategic Narrative Engine（朝会3分説明レベルへ）

Market Narrative を「材料の羅列」から「証券会社ストラテジストが朝会で3分説明する
レベル」へ引き上げるための新エンジン。UIではなく分析ロジックを追加。既存エンジンを
壊さず、その算出済み結果だけを再利用する（生成AI・断定予測・新規データ取得・捏造・
推測・売買助言は一切なし）。

新規エンジン: src/analysis/strategic_narrative.py（StrategicNarrative / StrategicFactor /
StrategicScenario を models.py に追加）。Market Narrative カードはこのエンジンの出力を
表示するだけ（strategic_narrative未指定なら従来の6部構成にフォールバック＝後方互換）。

改善①〜⑩
・① 「何が起きたか」ではなく「市場が何を織り込んだ結果こう動いたか」を因果で組み立て
  （例: FRB利下げ期待の後退→長期金利上昇→高PER銘柄の割引率上昇→AI半導体に利益確定売り→
  指数寄与度の高い半導体株が日経平均を押し下げ）。金利の方向から機械的に分岐。
・② 【本日の一言】（20〜40字）を先頭に。主因＋日経の方向を一文で。
・③ 【今日の市場心理】をニュース・VIX・金利・Scenario・Market Regime から機械判定。
・④ 【本日の主因ランキング】①②③（寄与度＝|変化率|×重み で順位付け・★＋1行理由）。
・⑤ 【相場を押し下げた材料】【下支えした材料】に分離し、優先度★付きで降順表示。
・⑥ 今後を条件分岐ではなくシナリオA/B/C化（Scenario Engineの配分から確率ラベル高/中/低）。
・⑦ 【なぜ日経平均はこうなったか】を専用ブロック化（日経→寄与度→業種→背景→海外→マクロ
  の順で「原因」まで遡る）。
・⑧ Cross Market を↓羅列ではなく自然な文章に（例: 米金利上昇→ドル買い→円安、通常は輸出株
  の追い風だが今回はSOX急落が円安効果を打ち消した…）。
・⑨ 【営業向け30秒説明】を追加（お客様への第一声テンプレート）。
・⑩ 【ストラテジスト総括】200〜300字（背景・市場心理・一番効いた材料・今後の見るポイントを
  一連の流れで説明）。

再利用した既存エンジン: Market Regime / Cross Market / News Ranking / News Impact /
Future Intelligence / Theme Momentum / Market Breadth / Analysis Confidence / Scenario /
Watchlist / Macro Events(Weekly Events) / Market Data。AnalysisBundle に strategic_narrative
を追加し main.py で配線。既存テストは全通過、pytest追加。

注記: 個別銘柄の「寄与度」の実データ（構成比・寄与額）は取得していないため、SOX等の
セクター指数の動きから定性的に「指数寄与度の大きい半導体・値がさ株」と表現する（具体的な
寄与額・銘柄別数値は捏造しない）。

## v3.5.1 (2026-07-08) — Market Narrative 可読性改善（初心者でも一読で「なぜ」が分かる）

v3.5で新設した相場総括を「材料の羅列」から「初心者でも一読で今日の相場がなぜ動いたか
分かる文章」へ再構成した。分析データは既存のまま（捏造なし・売買助言なし）で、
見せ方と文章構成のみ改善。

追加・改善（src/analysis/market_narrative.py・models.MarketNarrativeSummary・html_builder.py）
・① 今日の結論を冒頭に1〜2文で（例:「本日は『半導体主導のリスクオフ寄り』の相場。
  米金利上昇と半導体株安を背景に、日経平均は下落しました。VIXは20未満で全面的な
  パニックではありません。」）。主因（半導体/金利/為替主導）＋日経の方向＋VIXニュアンスを機械生成。
・② 「なぜ日経平均は動いたか」を米国株→金利→為替→（半導体セクター）→日経 の順で
  ↓チェーン表示。取得できたデータのみで、帰結は必ず日経で締める。
・③ 悪材料 と ④ 支えになる材料 を明確に分離（金利上昇・SOX安・NASDAQ安・原油高＝悪材料／
  円安・VIX20未満・金利低下・テーマ継続・決算イベント＝支援材料）。
・⑤ 今後見るべきポイントを具体的な条件分岐に（SOXが反発するか／米10年金利が◯%台で
  定着するか／VIXが20を超えるか／円安が輸出株を支えるか／今週の決算で見方が変わるか）。
  金利水準は実データの現在値を使用。
・⑥ 見立てを 短期／中期／長期 の3本立てに（各3行以内・断定せず条件分岐・売買助言なし）。
・重複していた「何が起きたか」「主要変化」「主因の詳細」「波及チェーン」「示唆」は
  「詳しく」に集約し、初期表示は①〜⑥に絞って短く。
・MarketNarrativeSummary に conclusion / nikkei_chain / negative_factors /
  supportive_factors / long_term_view を追加（既存フィールドは維持・後方互換）。

やらないこと（継続）: 生成AIの作文／断定的将来予測／個別の売買推奨（買うべき/売るべき）／
取得していないデータの捏造／既存の分析ロジック・エンジンの書き換え。

## v3.5 (2026-07-07) — Market Narrative & Section Pruning Upgrade（相場総括の新設・構成整理）

情報を大量に並べるツールから「今日の相場がなぜ動いたか・背景・今後の見方」を端的に
深掘りできる分析ツールへ寄せた版。最上部に相場総括を新設し、営業系・重複セクションを
整理して「朝3分で本質」を優先した。分析ロジックは変更せず、既存エンジンの算出済み
結果を組み合わせるだけ（生成AI作文・断定的将来予測・売買助言は行わない）。

Phase 0分類:
- A（既存で十分使える）: Market Regime／Cross Market／Future Intelligence／
  Executive Summary／Analysis Confidence／Weekly Events／異常値検知（総括の素材が既に揃っている）。
- B（少し改善すれば使える）: シナリオ系の重複整理（個別シナリオを折りたたみ）／
  営業系のグループ化（既にcard-collapsed済み→「営業メモ」見出しで集約）。
- C（今回新規追加）: Market Narrative Summary（本日の相場総括）＝新規モジュール＋最上部カード。
- D（今回はやらない・据え置き）: セクションの物理的な全並べ替え（既存のprev/next・目次・
  Data Qualityは引用の下、というナビゲーションテストを壊さないため見送り。「本質を上に」は
  最上部の相場総括＋Today's Decisionで担保）／営業系の完全削除（まず営業メモに集約・段階的に）。

追加・改善
・改善1/2 Market Narrative（src/analysis/market_narrative.py 新規＋models.MarketNarrativeSummary）:
  市場データ・重要ニュース・Market Regime・Cross Market・Future Intelligence・Weekly Events・
  異常値・Analysis Confidence だけから、①今日を一言で（headline）②何が起きたか③なぜ動いたか
  ④背景⑤波及チェーン⑥これから見るべき点⑦今後の見立て（短期/中期・条件分岐）⑧リスク
  ⑨投資判断への示唆（短期/中期/長期/注意・売買助言なし）⑩Analysis Confidence⑪根拠、を機械的に整理。
  HTML最上部（Today's Decision・Dashboardより上）に「📝 本日の相場総括」カードを新設し、
  背景・見立て・リスクは「詳しく」に折りたたみ。main.pyで配線・AnalysisBundleに格納。
・改善3 役割整理: Today's Decisionは「3分の判断カード」、Market Narrativeは「なぜの深掘り」。
  総括の背景説明はNarrative側に集約し、Today's Decisionは短い判断カードのまま維持。
・改善5 シナリオ整理: 「今日の3大シナリオ（期待値順）」を主軸とし、「日経平均・ドル円・米国市場
  個別シナリオ」は重複回避のため初期は「詳しく」に折りたたみ（内容・算出は不変）。
・改善4/9 営業メモ統合: 営業支援系（今日電話すべき顧客／営業準備／営業トーク／営業向けコメント
  ／岡三証券営業向けコメント／朝会コメント／会話ネタ／想定質問）の直前に「営業メモ」見出しを
  追加して1グループに集約。各カードは初期折りたたみ（v3.1）＋「営業セクションを非表示」トグルは維持。
  メニュー最上段に「本日の相場総括」を追加し重要度順の入口に。

（既に実装済みで継続）: Future Intelligenceの初期短縮（fi-conclusion＋FI_SUMMARY_COUNT折りたたみ・v2.7）／
Watchlistの今日見るべき5銘柄（Today's Decision・v3.1）／引用の要約＋全URL折りたたみ（v3.1）。

やらないこと（v3.5で厳守）
・売買助言（「買うべき」「売るべき」等の個別推奨）／事実と分析の混同／取得していないデータの捏造／
  既存の分析ロジック・エンジンの書き換え／派手なUI化。

## v3.4 (2026-07-07) — One-Tap Report Generation（Cloudflare Worker中継でワンタップ生成）

GitHub Actions画面を経由せず、スマホから1タップで workflow_dispatch を起動できる
ようにした版。GitHub Token・Secrets・PATはHTML/JS/GitHub Pagesに絶対に出さず、
Cloudflare Worker等の認証つき中継バックエンドを介して安全に実行する設計。

追加・改善
・Cloudflare Worker（cloudflare/trigger-report-worker.js 新規）: POST /trigger で
  GitHub Actions の workflow_dispatch API を叩く中継役。GITHUB_TOKEN はWorkerの
  Secret（env）からのみ参照し、コードに直書きしない・レスポンス/ログにも出さない。
  必要な変数: GITHUB_TOKEN(Secret)/GITHUB_OWNER/GITHUB_REPO/GITHUB_WORKFLOW_FILE/
  ALLOWED_ORIGIN/WORKFLOW_REF。CORSは ALLOWED_ORIGIN（既定 GitHub PagesのURL）のみ許可。
  成功時 {ok:true,message:"workflow dispatched"}、失敗時 {ok:false,error:...}（要約のみ）。
・cloudflare/README.md・cloudflare/wrangler.toml.example 新規: Worker のデプロイ手順・
  Secret設定・必要なGitHub Token権限（Fine-grained: Actions R/W・Contents R/W、対象repo限定）。
・HTML（src/report/html_builder.py）: `_one_tap_regenerate_html` を機能化。realtime.enabled=true
  かつ endpoint_url 設定時のみ「🚀 ワンタップで最新レポート生成」ボタンを表示。押下でJS（SCRIPT）が
  endpoint_url へPOSTし、成功なら「生成を開始しました。1〜3分後にページを再読み込み」、失敗なら
  エラー表示、連打防止で60秒間ボタン無効化。エンドポイントURLは data-endpoint に持たせ、
  Token・Secretはボタン・JS・HTMLに一切埋め込まない。
・config.yaml: realtime 設定枠を one_tap 対応に更新（enabled/provider/endpoint_url/mode＋
  Cloudflare Worker設定例をコメントで追記）。既定は enabled:false（従来通りボタン非表示）。
・既存の安全導線（🔄ページ再読み込み／⚙️GitHub Actionsを開く／📱スマホ手順）は
  Worker未設定時のフォールバックとして残置。
・README: Cloudflare Workerでのワンタップ生成の仕組み・TokenをHTMLに入れてはいけない理由・
  Worker Secretの設定方法・必要なGitHub Token権限・config.yaml設定例・トラブルシューティングを追記。

やらないこと（v3.4で厳守）
・GitHub Token/Secrets/PATをHTML・JS・GitHub Pagesへ出すこと。
・認証なしAPIでのworkflow_dispatch／誰でも勝手に実行できる実装。
・許可Origin以外からのWorker実行（CORSで拒否）。

## v3.3 (2026-07-07) — Latest Report Generation Button Upgrade（スマホからの再生成導線を改善）

「最新レポートを生成する」ボタンまわりのUXのみを改善した版。分析ロジック・
HTMLの他セクションは変更していない。GitHub Token・Secretsの類は引き続き
HTMLへ一切出さない（既存のセキュリティ方針を厳守）。

追加・改善
・改善1 ボタンUI再設計（src/report/html_builder.py `_refresh_button_html` 他）:
  ①🔄ページを再読み込み（常時表示・従来通り）②⚙️最新レポートを生成する
  （actions_url設定時のみリンク表示。未設定時は非表示ではなく「設定未完了」を
  表示し、何が足りないか分かるようにした）③📱スマホでの実行手順（details/summaryで
  常時提供。ログイン→Run workflow→緑ボタン→1〜3分待機→再読み込み、の5手順）。
・改善2 Actions画面へのリンク精度向上（main.py `_resolve_actions_url`）: 優先順位を
  「環境変数ACTIONS_URL（明示上書き）＞config.yaml output.actions_url（設定時最優先）
  ＞GITHUB_REPOSITORYからの自動推定＞空文字」に変更。config.yamlのactions_urlに
  実際のワークフロー直リンクを設定済み。
・改善3 生成状態の説明（`_generation_status_html` 新規）: 最終生成時刻・
  「このページは最後に生成されたレポート」であること・「再読み込みだけでは新規
  データ取得されない」ことをボタン付近に常時表示。
・改善4 将来のワンタップ生成枠（`_one_tap_regenerate_html` 新規、`build_html_report`
  に `realtime` 引数を追加）: `realtime.enabled=true` かつ `endpoint_url` 設定時のみ
  「🚀 ワンタップで最新生成」ボタンの枠を表示（バックエンド未実装のため常に押せない
  状態）。無効時・未指定時は従来通り何も表示しない。main.pyから
  `config.get("realtime", {})` を渡すよう配線。
・改善5 セキュリティ: GitHub Token・Secrets・認証情報の類を新規追加分にも一切含めない
  （既存のno-leakテストに加え、v3.3の新規テストでも "token" 文字列の非存在を確認）。
・改善6 README更新: ページ再読み込みとレポート再生成の違い・スマホでRun workflowを
  押す手順・Run workflowが見えない場合の対処（ログイン確認/デスクトップ表示切替/
  GitHubアプリ利用）・完全ワンタップ化に必要なもの（Cloudflare Worker/Vercel
  Function/GitHub App）・GitHub TokenをHTMLに出してはいけない理由を追記。

やらないこと（v3.3で厳守）
・GitHub Token・Personal Access Token・Secretsの類をHTML/JSへ埋め込むこと。
・認証なしでworkflow_dispatchを実行できる実装（誰でも押せるワンタップ自動実行）。
・分析ロジック・他セクションのHTML/CSSの変更（ボタンまわりのみに限定）。

## v3.2 (2026-07-07) — Analysis Accuracy Upgrade（分析精度・ニュース重要度・未来予測・市場判断の強化）

UI改善ではなく「分析精度」の底上げに特化した版。HTML/CSS/UIは一切変更せず、
分析エンジンのみを追加・強化した。すべて公開市場データと既存の算出済みシグナル
だけから機械的に算出し、生成AIの推測は使わない。既存エンジン（scenario/
causal_chain/news_ranking/source_trust 等）は変更せず、結果を後付けで拡張、
または新規エンジンとして並列に追加する形で後方互換を維持している。

Phase 0分類:
- A（既存で十分使える）: Source Trust（★1〜5の階層は既にあり）／Duplicate/Cross
  Source Intelligence（source_count・combined_trust は算出済み）／Theme Momentum
  Score／既存の因果チェーン（短い3〜5本）。
- B（少し改善すれば使える）: 情報源の階層→Tier1〜4ラベルへ写像（改善4）／
  ニュース重要度★→100点満点化（改善3）／Weekly Eventにコンセンサス等の入れ物追加（改善6）。
- C（今回新規追加）: Market Regime Engine（改善1）／Cross Market多段波及（改善2）／
  Future Probability条件分岐（改善7）／Theme Rotation（改善8）／Market Breadth（改善9）／
  Analysis Confidence（改善10）。
- D（今回はやらない）: HTML/CSS/UI改善（明示的に禁止）／実際の資金フロー額・
  値上がり値下がり全銘柄数の取得（未提供データの捏造はしない・構造のみ）／
  生成AIによる将来予測の断定。

追加・強化（分析エンジンのみ・すべて AnalysisBundle に格納。表示は次版以降）
・改善1 Market Regime Engine（src/analysis/market_regime.py 新規）: VIX・米10年債・
  NASDAQ・S&P500・SOX・ドル指数(DXY)・ドル円・WTI・Gold・Bitcoin の前日比/水準から、
  Risk On / Risk Off / Neutral を判定し Risk Score(0〜100) を算出。各指標の寄与
  （符号・重み）を定数化した透明なスコアリング。データ欠損指標はスキップし評価数も返す。
  config.yaml に ドル指数(DXY) を追加。
・改善2 Cross Market Analysis（src/analysis/cross_market.py 新規）: 既存の因果チェーンは
  変更せず、米金利↑→ドル高→円安→日本輸出株→半導体→設備投資→電力→電線 のような
  多段の波及を、条件成立時のみ機械的に組み立てる。config.yaml の cross_market_rules（任意）で
  追加ルールも定義可能。
・改善3 News Impact Score（src/analysis/news_impact.py 新規）: 既存の★ランキングは不変。
  市場影響・テーマ継続性・一次情報(Tier1)・複数ソース一致・日本株/米国株/指数/為替/金利影響・
  セクター波及・話題性・鮮度の加点表から Impact Score(0〜100) と内訳を後付け付与
  （NewsRankingItem に impact_score / impact_breakdown を追加）。
・改善4 Source Tier（source_trust.py に追加）: 既存の信頼度スコア(1〜5)を Tier1（公式・
  一次情報）〜Tier4（一般・参考）へ写像。Tier1はImpact Scoreで重く評価。
・改善5 Duplicate Intelligence（news_impact.py）: 3社以上が同一ニュースを報じていれば
  Major Story と判定（NewsRankingItem.is_major_story）。count_major_stories で件数集計。
・改善6 Macro Intelligence（構造のみ）: WeeklyEventEntry に consensus/previous/forecast/
  actual/surprise の入れ物を追加（今回は構造だけ。値があれば転記、無ければ空＝従来表示）。
・改善7 Future Probability（src/analysis/future_probability.py 新規）: 未来予測ではなく
  「もしAかつBなら→C」のif条件型。景気後退懸念/リスクオン継続/円安輸出優位/インフレ再燃/
  安全資産選好の各分岐を本日の市場データで評価し triggered を立てる。生成AIの推測なし。
・改善8 Theme Rotation（src/analysis/theme_rotation.py 新規）: Theme Momentum Score と
  theme_relations（人手の隣接関係）から、AI→半導体→電力… のテーマ間資金移動の
  「向かいやすさ」を推定（断定はしない）。
・改善9 Market Breadth（src/analysis/market_breadth.py 新規）: 取得済み指数・コモディティ・
  ウォッチリストの前日比プラス/マイナス数から Breadth Score(0〜100) を算出。東証全銘柄の
  騰落ではない代用値であることを is_proxy=True と basis で明示（将来の全銘柄データに拡張可能な構造）。
・改善10 Analysis Confidence（src/analysis/analysis_confidence.py 新規）: 旧「AI Confidence」に
  代わり、取得ソース数・公式(Tier1)情報数・重複報道数・鮮度・データ欠損・分析可能項目数から
  レポート全体の分析根拠の充実度(0〜100)を機械的に算出（将来の的中確率ではない）。

やらないこと（v3.2で厳守）
・HTML/CSS/UIの変更（html_builder.py 等は一切触っていない）。
・既存分析ロジック（scenario/causal_chain/news_ranking/source_trust本体）の書き換え。
・未提供データ（実資金フロー額・全銘柄の値上がり値下がり数・将来予測の確率）の捏造。

## v3.1 (2026-07-07) — UX / Decision Quality Upgrade（結論ファースト・翻訳警告・異常値検知）

「情報は多いが投資の“結論”が埋もれる」を解消し、朝3分でその日の判断に辿り着ける
Personal Market Intelligence OS へ寄せた版。既存の分析ロジック・ランキング・
各エンジンの計算結果は一切変更せず、HTMLの「見せ方」と表示用の機械的サマリー・
品質チェックのみを追加した（リファクタリング・既存UI破壊なし）。

追加・改善
・改善1 Today's Decision カード: HTML最上部（Dashboardより上）に「今日の投資判断
  ・3分サマリー」カードを新設。今日の市場判断（リスクオン／オフ／中立）・重要テーマTOP3
  ・今日見るべき銘柄TOP5・警戒ポイントTOP3・今週の重要イベント・AI Confidence・データ鮮度
  ・翻訳ステータスを各1〜2行で提示。新しい予測は行わず、各エンジンが算出済みの最上位
  シグナルを機械的に転記するだけ（市場判断は既存シナリオ確率のbull/bear差から判定）。
  トップメニューにも 🎯 Today's Decision を追加。
・改善2 翻訳バグの見える化: 英語見出しに日本語訳があればHTMLで日本語を優先表示
  （display_title・「翻訳済み」バッジ・原文は保持、v3.0から継続）。加えて、未翻訳の
  英語記事が残る場合は Today's Decision と Data Quality に「翻訳API未設定のため英文の
  まま表示（未翻訳N件）」と明示（ANTHROPIC_API_KEY未設定を llm_enhancer.is_available で判定）。
・改善3 異常値検知（src/analysis/anomaly.py 新規）: 日経±5%・主要指数±5%・ドル円±2%・
  米10年±15%の前日比、および水準の妥当レンジ（桁違いの検知）を機械的にチェックし、
  「異常値なし／要確認」＋該当項目を列挙。原因の断定・自動補正はせず、人が確認する
  ためのフラグのみ（分析ロジック・ランキングには不関与）。
・改善5 今日見るべき銘柄: Today's Decision の「今日見るべき銘柄TOP5」をウォッチリスト
  （無ければ注目5銘柄）から機械的に抽出。
・改善6 営業系セクションの初期折りたたみ: 営業準備／営業トーク／営業向けコメント／
  岡三営業コメント／朝会コメント／想定質問（sales-section）と 今日電話すべき顧客／会話ネタを
  初期状態で card-collapsed に。投資判断に必要なセクションを上に、営業メモは畳んで下部に。
  既存の「営業セクションを非表示」トグルはそのまま維持。
・改善7 引用（情報源）の圧縮: 初期表示は要約（情報源数・カテゴリ数・公式ソース数・
  海外ソース数・主要ソースTOP10）のみとし、参照URLの全一覧は「詳しく」に折りたたみ
  （全URLは従来通り保持）。
・改善8 Data Quality 拡充: 翻訳API状態・経済カレンダー取得状態（自動取得／登録情報の内訳）
  ・異常値チェック・取得失敗ソース・市場データ取得時刻・RSS取得件数を追加表示。

やらないこと（v3.1でも継続）
・Token/SecretsをHTMLへ出す／有料・ログイン必須情報の取得／規約不明スクレイピング／
  既存分析ロジックの大改造・既存UI破壊。
・セクションの物理的な全並べ替えは、既存のナビゲーション（prev/next・目次・
  Data Qualityは引用の下）テストを壊さないため見送り、「結論ファースト」は最上部の
  Today's Decision カードで担保した。

## v3.0 (2026-07-07) — Foundation Completion（翻訳キャッシュ／リアルタイム導線／経済カレンダー）

v2.8/v2.9の骨組みを「本番で使える」状態に仕上げた版。既存の分析ロジックは変更せず、
翻訳の永続化・更新導線・経済指標の自動収集を完成させた。

Phase 0分類:
- A（実装済み）: 翻訳エンジン本体・2段階更新ボタン・source health/fetched_at・
  Weekly Eventの重要度/影響対象/カウントダウン
- B（骨組みのみ→今回完成）: 翻訳キャッシュ（毎回API・永続化なし）／
  economic_calendar（単一URL JSONのみ・source未記録）／Weekly EventのSource表示なし
- C（今回実装）: 翻訳キャッシュ永続化・翻訳UI強化・realtime設定枠・
  economic_calendarのsources(rss/json/csv)対応・Weekly EventのSource/取得時刻表示・
  workflow永続化・README
- D（やらない）: Token/SecretsをHTMLへ・完全自動workflow_dispatch（Token必要）・
  有料/ログイン/規約不明スクレイピング

追加・改善
・①English Translation Engine完成: 翻訳キャッシュを永続化
  （data/translation_cache/translation_cache.json）。原文タイトルをキーに日本語訳を
  保存し、翌日以降はAPIを呼ばず再利用。ANTHROPIC_API_KEY未設定でも過去に翻訳済みの
  見出しは日本語表示。翻訳失敗（空文字）はキャッシュに残さずリトライ可能。キャッシュ
  破損時も空として継続。HTMLは日本語訳を優先表示＋「翻訳済み」バッジ＋原文を「詳しく」に保持
  （News Ranking/Executive Summary/Dashboardで翻訳タイトル優先）
・②Real-Time Update Engine完成: config.yamlに realtime 設定枠
  （enabled/provider/endpoint_url/mode）を追加。将来のCloudflare Worker等による完全
  リアルタイム化に備えつつ、enabled=falseの間は既存動作のまま・Token/SecretsはHTMLへ
  一切出さない。取得時刻表示（HTML生成/市場データ/各ソース）はv2.9のNews Freshness詳細を継続
・③Economic Indicator Auto Collection完成: economic_calendar.pyを本実装。
  economic_calendar.sources（[{name,url,type(rss/json/csv)}]）を順に取得・正規化し、
  macro_events（手入力優先）とマージ・重複除去。取得失敗時はmacro_eventsのみで継続。
  RFC2822日付にも対応。WeeklyEventEntryにsource/source_stars/fetched_atを追加し、
  Weekly EventにSource・Source Trust・取得時刻を表示（影響対象は既存の自動補完を継続）
・⑤GitHub Actions永続化: translation_cache.jsonをコミット対象に追加
  （journal.json/theme_learning.jsonに追加）。data/translation_cache/README.md を新規追加

変更ファイル
・src/analysis/translation.py（永続キャッシュ）・executive_summary.py（display_title優先）・
  weekly_events.py（source/fetched_at）・models.py（WeeklyEventEntry拡張）
・src/collectors/economic_calendar.py（rss/json/csv対応・source記録）
・src/report/html_builder.py（翻訳済みバッジ・Weekly EventのSource/取得時刻表示）
・main.py（翻訳キャッシュ配線）・config.yaml（translation.cache_dir/realtime/
  economic_calendar.sources）・.github/workflows/daily-market-brief.yml（キャッシュ永続化）
・README.md / CHANGELOG.md / data/translation_cache/README.md（新規）
・tests/test_v3_0_foundation.py（新規・17件）

pytest
261 passed（既存244維持＋v3.0で17件追加）

## v2.9 (2026-07-07) — Real-Time Freshness / Translation / Source Expansion Upgrade

「毎日読むレポート」から「岡三証券退職後も自分だけでマーケットを分析・予測し
続けるための自己改善型システム」へ。既存の分析ロジックは変更せず、翻訳・
リアルタイム性・情報源・重複統合を強化。

Phase 0（実装前調査）分類:
- A（安全に実装）: ①翻訳エンジン強化 ②2段階更新ボタン＋取得時刻表示
  ③公式RSS群の追加 ④重複ソース統合・重要度補正 ⑤情報取得時刻の見える化
- B（GitHub Actionsでのみ実データ検証可）: 新規collector（Fed/SEC/BLS/EIA/
  ECB/CoinDesk/CoinTelegraph/Yahoo Finance US）の実際のRSS取得、
  ANTHROPIC_API_KEYがある場合の実翻訳（この開発環境はネットワーク遮断・
  APIキー未設定のため。no-op経路・グレースフルフェイルは検証済み）
- C（今回は見送り）: Seeking Alpha/Benzinga（利用規約・Bot対策リスク）、
  半導体各社Newsroom・AI各社Blog（定型RSSが無くスクレイピングが必要）、
  US Treasury/BoE/IMF/World Bank/OECD/Nasdaq公式（RSS構成の確証が低い）
  — 詳細はconfig.yamlの`source_classification`とREADMEを参照

追加・改善
・①English News Translation Engine強化: Headlineに`duplicate_sources`等と
  並び`is_translated`（title_jaの有無から導出するプロパティ）を追加。翻訳
  プロンプトを金融用語重視・100文字目安・専門用語補足（EPS/CPI/FOMC/
  guidance/yield/rate cut等）へ更新。Today's Dashboardの見出し表示を
  `display_title()`（日本語訳）+ネイティブtitle属性（原文・ホバー表示）へ修正。
  ANTHROPIC_API_KEY未設定・失敗時は原文のまま（既存動作に影響なし）
・②Real-Time Update Engine: 「最新表示に更新」を2段階ボタンへ再設計。
  「ページを再読み込み」（常時表示・location.reloadのみ）と「最新レポートを
  生成する（GitHub Actionsを開く）」（actions_url設定時のみ・新しいタブで
  Run workflow画面を開くだけ・自動実行はしない・GitHub Token/Secretsは
  一切埋め込まない）。News Freshnessカードに「情報取得時刻を詳しく見る」を
  追加し、HTML生成時刻・市場データ取得時刻・各ニュースソースの取得時刻
  （SourceHealthEntryにfetched_at追加）を表示
・③Source Expansion Engine: 新規collector 6本（fed.py/sec_gov.py/
  us_gov_stats.py/ecb.py/crypto_news.py/yahoo_finance_us.py）を追加。
  公開RSSのみ使用し、既存collectorと同じ「失敗時は空リストを返す」設計を
  踏襲（main.pyの追加情報源ループに追加するだけで、失敗してもレポート生成は
  止まらない）。config.yamlに情報源の実装状況（implemented/reference_only/
  skipped）を分類・明記
・④Duplicate/Cross Source Intelligence: dedupe_headlinesが同一ニュースを
  配信していた他の情報源名（duplicate_sources）と配信元総数（source_count）
  を記録するよう拡張（重複が無ければ従来通りsource_count=1）。
  news_ranking.pyで2社以上・信頼度★4以上の重複報道に+1〜+2の補正を追加
  （新しい評価基準の創作ではなく既存Source Trustスコアの集計）。
  source_trust.pyにcombined_trust_for_sources()を追加し、HTMLへ
  「○社が同一ニュースを報道／Combined Trust」を表示。Source Trustの
  ティア判定にSEC/BLS/BEA/EIA/ECB/BoE/Barron's/CoinDesk/CoinTelegraph等を追加

変更ファイル
・src/collectors/: news.py（duplicate_sources/source_count/is_translated）、
  fed.py・sec_gov.py・us_gov_stats.py・ecb.py・crypto_news.py・
  yahoo_finance_us.py（すべて新規）
・src/analysis/: source_trust.py（combined_trust_for_sources追加・ティア拡張）、
  news_ranking.py（重複ソース補正）、data_freshness.py（fetched_at追加）、
  translation.py（プロンプト更新）
・src/report/html_builder.py（2段階更新ボタン・情報取得時刻・重複表示・
  Dashboard翻訳表示）
・main.py（新規collector配線）、config.yaml（新規ソース設定・分類・reliability）
・tests/test_v2_9_realtime_translation_sources.py（新規・15件）、
  tests/test_html_builder.py（更新ボタン仕様変更に伴う2件更新）

pytest
244 passed（既存229維持＋v2.9で15件追加）

## v2.8 (2026-07-06) — Smart Intelligence Evolution

「毎日読むレポート」から「毎日学習し続ける投資AI」へ。既存の分析ロジック
（Momentum・Confidence・Watchlist判定）の設計は維持し、学習・信頼度・優先度の
仕組みを追加。HTMLのみ変更（Markdown版は維持）。外部ライブラリ追加なし。

追加（学習）
・Investment Journal（①）: 新規 src/analysis/investment_journal.py。毎日のAI判断
  （重要ニュース・テーマ・シナリオ・Thesis・Regime・Money Flow・Top Picks・
  Confidence・重要イベント＋参照価格）を data/investment_journal/journal.json へ
  追記し、30/90/180日後に現在の市場と機械的に答え合わせ（★評価・的中/外れ）。
  新セクション「Learning History」を追加。市場データが無い環境では評価はスキップ
・Theme Confidence Learning（②）: 新規 src/analysis/theme_learning.py。テーマ予想を
  data/theme_learning/theme_learning.json へ蓄積し、30日後の地合いで勝率・平均
  リターン・平均継続日数を集計。勝率で Future Intelligence の Confidence を上下限
  つき（-20〜+10）実績補正（build_future_intelligenceにtheme_win_rates引数を追加。
  未指定なら従来通り）。新セクション「Theme Confidence Learning」を追加

改善（要約・信頼度・優先度）
・Scenario Engine v2（③）: 新規 src/analysis/scenario_v2.py。強気/中立/弱気を
  期待値（確率）の高い順に最大3つへ整理し①②③で表示。発生条件・恩恵/悪影響
  セクター・注目銘柄・因果関係・時間軸は「詳しく」で展開。新セクション
  「今日の3大シナリオ（期待値順）」を追加
・情報ソース信頼度（⑥）: 新規 src/analysis/source_trust.py。出典名から★1〜5と
  ティア（公式発表/一流メディア・IR/主要メディア/一般メディア/参考情報）を判定し、
  ニュース・Executive Summaryの各カードに Source Trust バッジ＋理由を表示
・Why Today（⑦）: 新規 src/analysis/why_today.py。既存データのみから「なぜ今日
  見るべきか」を1〜2行で生成し、対象カードの先頭に表示（新予測はしない・長文禁止）
・低重要度記事の折りたたみ（⑧⑨）: ニュースは重要度×鮮度で初期表示を選別
  （★★★★☆以上／24時間以内かつ★★★☆☆以上／1位は必ず表示）。★★★☆☆以下・
  48時間超は details に折りたたむ（削除しない）
・英語ニュース自動翻訳（④・安全スキャフォールド）: 新規 src/analysis/translation.py。
  ANTHROPIC_API_KEYがある時のみ英語見出しを日本語訳し「日本語→原文を見る」で表示。
  キー未設定・失敗時は原文のまま（Headlineにtitle_ja/display_title()を追加）
・Weekly Event 自動取得（⑤・安全スキャフォールド）: 新規
  src/collectors/economic_calendar.py。economic_calendar.url設定時のみ公開カレンダーを
  取得しconfig.yamlのmacro_eventsとマージ。未設定・失敗時は従来通りconfigのみ使用

変更ファイル
・src/analysis/: investment_journal.py / theme_learning.py / scenario_v2.py /
  source_trust.py / why_today.py / translation.py（すべて新規）、models.py・
  future_intelligence.py（既存・後方互換で拡張）
・src/collectors/: economic_calendar.py（新規）、news.py（Headlineにtitle_ja追加）
・src/report/html_builder.py（新セクション・Source Trust・Why Today・折りたたみ）
・main.py / config.yaml / .github/workflows/daily-market-brief.yml（JSON永続化）
・tests/test_v2_8_smart.py（新規・20件）、tests/test_v2_7_upgrade.py（折りたたみ仕様更新）
・data/investment_journal/README.md・data/theme_learning/README.md（新規）

pytest
229 passed（既存209維持＋v2.8で20件追加）

注意（この環境での検証範囲）
・④翻訳・⑤自動取得はネットワーク/APIキーが必要なため、開発環境では実データ検証
  不可（no-op経路とHTML表示は検証済み。GitHub Actions側で有効化される）。
  それ以外の①②③⑥⑦⑧⑨は実データ経路込みで検証済み

## v2.7 (2026-07-06) — Market Intelligence Knowledge Upgrade ＋ Weekly Event Impact Calendar

「毎朝ニュースを読むシステム」から「世界の変化を理解し長期投資判断を支援する
AIストラテジスト」への強化。分析ロジックの設計（Momentum・Confidence・
Watchlist判定・FIの計算）は変更せず、知識品質・鮮度・情報密度・可読性を改善。

追加・改善
・羅針盤Knowledge強化（①）: 「新しい順に3件読む」→「最大100件から知識を構築」
  する知識ベース方式へ。全ファイル走査→重複統合（正規化キー）→重要度
  （複数号での繰り返し登場数＋キーワード密度）順に重要な知識だけ抽出。
  カテゴリを拡張（景気循環・金融政策・金利・為替・半導体・AI・企業分析）し、
  philosophy_patterns（投資哲学・利益確定・リスク規律）を新設。
  本文転載禁止の制限（80文字/件・5件/カテゴリ・抜粋120文字）は不変
・ニュース鮮度最優先（②）: news_rankingに鮮度軸を追加。24時間以内は+2加点、
  48時間超は-4の大幅減点。ただしFOMC・日銀・決算・国家戦略・雇用統計・CPI等
  「影響期間の長いイベント」は例外として減点しない（鮮度×影響期間の両立）。
  日時不明記事は加減点なし。既存8軸の算出方法は不変
・情報密度（③）: ニュースランキングは重要5件のみ通常表示（6位以下は折りたたみ）。
  FIのメガトレンド／Theme Momentum／成熟度メモ／テーマ別診断／Investment
  Thesisは重要度順（見出し件数・スコア・Confidence）に上位8件のみ通常表示し、
  残りは「残りN件を表示」で展開（選別は表示のみ。計算は全件のまま）
・要約表示＋詳しくボタン（④⑤⑦）: 各カード・各項目を「2〜4行の要約→
  『詳しく』（HTML標準details/summary・外部JS不要）」の3分UIへ。
  Executive Summary／ニュースランキング／Watchlist／FI診断・成熟度／
  Watchlist・Stock Intelligence／Investment Thesisに適用
・重要度表示（⑥）: 全セクションカードの見出しに「重要度◯◯」（★×20の
  100点満点換算）バッジを追加
・FI再構成（⑧）: 冒頭に「結論→重要ポイント3つ→詳しくは各ブロック」の
  結論ボックスを追加（既存シグナルの転記のみ・新分析なし）
・Investment Thesis再構成（⑨）: 各テーマを「結論→理由3つ→詳しく」へ
・Watchlist再構成（⑩）: 銘柄ごとに一行要約→詳しくへ
・Weekly Event Impact Calendar（追加依頼）: 新セクション「今週の重要イベント・
  経済指標」。config.yamlのmacro_events＋決算発表予定から今日〜7日後の
  イベントだけを「近い順→重要度順」で表示。カウントダウン（本日21:30／
  あと1日 5時間／あと3日、日本時間）・★と重要度・国/地域・影響対象・
  想定される影響（条件付き整理のみ）・詳しく（なぜ重要か/見るべきポイント/
  関連テーマ）付き。macro_eventsに任意のtime("21:30")を登録すると時間まで
  表示。データが無い日は「直近1週間の重要イベントは登録されていません」。
  新規外部APIなし（新規 src/analysis/weekly_events.py＋WeeklyEventEntry）
・HTML版のみ対象（⑪）。Markdown/モバイル版は変更なし

変更ファイル
・src/analysis/rashinban_loader.py / models.py / news_ranking.py /
  weekly_events.py（新規） / src/report/html_builder.py / main.py / config.yaml
・tests/test_v2_7_upgrade.py（新規） / tests/test_weekly_events.py（新規） /
  tests/test_html_builder.py（セクション追加に伴う範囲修正1件）

pytest
209 passed（既存維持＋v2.7で19件追加）

## v2.6 (2026-07-05) — Rashinban Learning Source System v1.0

追加（岡三「羅針盤」を、コード更新なしで毎日の分析精度向上に使える学習ソースにする）

・Rashinban Loader（①）: 新規 `src/analysis/rashinban_loader.py`。
  `data/rashinban/` の .md/.txt を新しい順に最大3件（config可変）読み込み、
  latest.md→ファイル名日付（YYYY-MM-DD）降順で最新を判定。READMEは対象外。
  フォルダが無い・空でもエラーにならず空のまま動作
・RashinbanKnowledge（②）: models.py に追加（source_files／latest_date／
  相場観・テーマ・銘柄選定・リスク・時間軸の5パターン＋raw_excerpt_summary＋
  emphasized_theme_labels）。frame_count()／has_content() 付き
・型の抽出（③）: すべてルールベース（AI API不使用）のキーワード分類。
  本文転載防止のため 1件80文字・カテゴリ5件・抜粋120文字に制限。
  重点テーマは既存 macro_themes ラベルとの照合のみ（新テーマ生成なし）
・分析への接続（④）: 羅針盤がある場合のみ、重点テーマ一致分に
  News Ranking=+1の補助加点＋理由追記／Strategist View・Executive Summary=
  参照した旨の一文／Future Intelligence=Theme Momentum理由追記・
  Investment Thesis監視指標追加。無い場合は従来と完全に同一動作
  （既存スコアリング・判定ロジックの設計は不変）
・HTML表示（⑤）: 「Rashinban Learning Source」小カードを追加。
  読み込みファイル名・最新日付・抽出フレーム数・使用状況のみ表示し、
  本文・抜粋は一切表示しない（未配置時はスキップした旨を表示）
・自動読み込み（⑥）: GitHub Actionsはmain.py実行時に data/rashinban/ を
  自動で読むため、workflowの変更なし（latest.md の差し替えだけで反映）
・運用手順（⑦）: `data/rashinban/README.md` 新規＋READMEに
  「GitHub Webだけで追加する手順」（PC・Claude Code不要）を追記
・config.yaml: `rashinban:`（dir／max_files）を追加
・tests/test_rashinban_loader.py 新規（空フォルダ／md・txt読込／最新判定／
  Knowledge生成／HTML表示／長文転載なし／羅針盤なしで従来動作、の8観点）

対象外（v1.0の割り切り）
・PDF/DOCXの解析はしない（md/txtへ変換して置く運用）
・羅針盤本文のレポート転載・長文引用はしない（分析フレームとしてのみ利用）

## v2.5 (2026-07-05) — Market Brief UI/UX & Freshness Upgrade

追加・改善（HTML版のみ。分析ロジック・Momentum・Confidence・Watchlist判定は不変。
外部JS/CSSライブラリなし・素のJavaScriptのみ。Markdown/モバイル版は変更なし）

・ニュース鮮度の表示（①）: 重要ニュースランキング・AI Executive Summary・
  Today's Dashboardの各ニュースに、投稿日時・約何時間前か・鮮度バッジ
  （最新≦6h=赤／24時間以内=緑／48時間以内=オレンジ／古い=グレー／
  日時不明=グレー）を色分き表示。順位ロジックは変更なし
  （鮮度タイブレークはv2.3で導入済み。日付不明記事が不利になる挙動も同様）
・トップメニューグリッド（②③）: レポート上部にDashboard／Executive Summary／
  Future Intelligence／重要ニュース／Watchlist／Stock Intelligence／
  世界のお金／Data Quality／営業メモへの9ボタンをAppMedia風グリッドで配置
・目次リンクを新しいタブで開く（④）: 全目次リンクにtarget="_blank"
  rel="noopener"を付与（リンク先は同一HTML内アンカー）
・セクションカード強化（⑤）: 各カードに「ひとこと説明」（主要9セクション）・
  開く/閉じる（▾/▸）・コピー（既存）・お気に入り（☆/★）を追加
・お気に入り機能（⑥）: ☆で登録→★、★で確実に解除→☆。localStorage
  （mkt_favs）に保存し再読み込み後も維持。表示オプション内に一覧を表示し、
  解除すると一覧からも消える。0件時は「お気に入りはありません」。
  Playwright実機検証で登録→解除→再登録→再読込維持を確認済み
・フローティング操作ボタン（⑦）: 右下に ☰目次／★お気に入り／↑TOP の3ボタン
・簡易検索＋タグUI（⑧）: キーワード入力でセクションタイトル・本文を検索し
  一致しないカードを非表示。クリアボタン・0件メッセージ付き。
  タグ（AI/半導体/電力/防衛/EV/金利/為替/消費）タップで即絞り込み
・表示オプション改善（⑨）: 既存4項目に「お気に入りのみ表示」を追加
  （localStorage保存）

変更ファイル
・src/report/html_builder.py
・tests/test_html_builder.py

pytest
182 passed

コミット
（下記参照）

## v2.4 (2026-07-05) — Investment Thesis Engine v2.0

追加（Future Intelligence Engineへの統合のみ。既存の分析ロジック・スコアリング・
判定・新しいAPIの追加はなし。営業利用ではなく自分自身の長期資産形成・投資判断を
最優先目的とする）

・Investment Thesis（テーマ別・長期投資仮説）: macro_themeごとに以下10項目の
  投資仮説を生成し、Long-term Strategyブロック（Markdown/HTML/モバイル）へ
  Confidence（分析根拠の充実度）の高い順に表示
  - 現在何が起きているか: Theme Momentum Scoreのreason（本日のシグナル説明）を転記
  - 今後起こりそうな変化［AI分析］: テーマ別診断のCatalyst先頭を非断定的に
    言い換えるのみ（Catalystが判断材料不足の場合は正直に分析材料不足と表示）
  - 恩恵を受ける業界: causal_rules.beneficiary_sectors
  - 恩恵企業: 既存の恩恵銘柄ロジック（beneficiary_sectors→related_tickers）の結果
  - 二次的恩恵企業: theme_relations（Cross Theme Mapping）で1段階隣接する
    テーマの恩恵企業
  - まだ注目されにくい企業: theme_relationsで2段階離れたテーマの恩恵企業
    （因果チェーン上、直接の恩恵銘柄として言及されにくい銘柄。新たな銘柄推定ではない）
  - 投資期間: 既存の中長期テーマ割り付け（半年/1年/3年/5年/10年）をそのまま転記
  - 監視指標: Theme Momentum Scoreの推移・関連ニュース件数＋既存のテーマ→
    イベント対応表（半導体市況・金利動向等）からの機械的な列挙
  - 崩れる条件［AI分析］: テーマ別診断のRisk（失速要因）を転記
  - 投資仮説まとめ: Stock Intelligenceと同じinvestment_storyロジックによる
    時系列の因果チェーン（テーマ→Catalyst→関連テーマへの波及→非断定的な結び）
・すべて既存シグナル（Theme Momentum・Lifecycle・Catalyst・Risk・Confidence・
  causal_rules・theme_relations）の転記・機械的な組み合わせのみで構成。
  目標株価・PER/EPS予想・「買い」「売り」等の推奨・期待リターンは一切生成しない
・InvestmentThesisEntry dataclass＋FutureIntelligenceBundle.investment_theses
  フィールドを追加（デフォルト値付きのため既存の呼び出し箇所に影響なし）

変更ファイル
・src/analysis/models.py
・src/analysis/future_intelligence.py
・src/report/sections.py
・src/report/html_builder.py
・src/report/mobile_builder.py
・tests/test_future_intelligence.py

pytest
175 passed

コミット
（下記参照）

## v2.3 (2026-07-05) — Data Freshness & News Quality v2.0

追加・改善（鮮度タイブレーク＋可視化＋ログ強化のみ。重要度スコアの算出・
Momentum・Confidence・Watchlist判定・Executive Summaryの設計は一切変更なし）

・News Rankingの鮮度タイブレーク（最優先）: 順位決定を
  「スコア → 記事日時（pubDate）の新しい順 → 取得順」へ変更。
  スコア自体は不変のため、スコア差がある場合の順位は従来と完全に同じ。
  同点の場合のみ、新しい記事が古い記事より上位になる
  （従来は取得順のみで、数日前の高スコア記事が毎日1位に再選出され続ける
  根本原因になっていた——前回のRoot Cause Investigation v2で実証済み）。
  日時を解析できない記事は同点内の最後尾に回す。
・News Freshness Score: 各記事の経過時間から★1〜5を内部算出
  （24h未満★5／48h未満★4／72h未満★3／96h未満★2／それ以上★1）。
  表示専用でランキングには影響しない。
・News Freshnessカード（HTML版・レポート上部）: 最新ニュース日時／最も古い
  採用記事日時／採用記事平均経過時間／採用記事件数／RSS取得件数／
  ランキング対象件数／レポート生成日時／データ鮮度評価（★＋ラベル）
・Data Qualityセクション（HTML版・引用一覧の下）: ニュース取得★／市場データ★／
  Future Intelligence★／Watchlist★（いずれも取得できた割合からの機械的評価）
  ＋更新日時・最新ニュース・平均鮮度・情報源数・ランキング対象件数
・GitHub Actions Job Summaryへ「Data Freshness Summary」を追加:
  RSS取得件数／重複削除後件数／ランキング1位の記事日時・タイトル／
  Executive Summary・Dashboard採用記事日時／HTML生成時刻／鮮度評価
・同じくJob Summaryへ「RSS Source Health」を追加: 情報源ごとに
  成功／取得失敗（0件）・件数・最新記事日時を一覧表示。
  ローカル実行時も同内容をINFOログへ出力（取得失敗が初めて可視化される）
・実装は新設の src/analysis/data_freshness.py に集約（読み取り専用の計測
  レイヤー。将来の鮮度加点・情報源信頼度・速報フラグはここへ追加できる構造）

変更ファイル
・src/analysis/data_freshness.py（新規）
・src/analysis/news_ranking.py
・src/collectors/news.py
・src/report/html_builder.py
・main.py
・tests/test_data_freshness.py（新規）

pytest
168 passed

コミット
（下記参照）

## v2.2 (2026-07-04)

追加・改善（UI・操作性のみ。分析ロジック・スコアリング・Future Intelligence／
Watchlist Intelligence／Stock Intelligenceの判定には一切変更を加えていない）

・Today's Action（HTML／Markdown／モバイル共通）: Future Intelligence Engine
  の最上部に、その日確認すべき事項を3〜5件表示。既存のTheme Momentum Score
  最上位テーマ・ドル円レートの有無・本日のイベント・業界モメンタム最上位・
  「決算」を含む既存ニュース見出しの有無だけから機械的に組み立てる
  （`format_utils.todays_action_items()`。新しい予測・分析は行わない）

・HTML版 UI改善
  - 画面右下に常時表示の「↑ TOP」ボタンを追加（Today's Dashboardへスムーズ
    スクロール。`scroll-behavior: smooth`のみ、追加JSなし）
  - 各セクション末尾に「← 前」「次 →」のワンタップ移動ボタンを追加
  - Future Intelligenceの5大ブロック（Today's Future Signals／Theme
    Intelligence／Industry Intelligence／Stock Intelligence／Long-term
    Strategy）を`<details>/<summary>`による開閉式に変更
    （デフォルトはToday's Future Signalsのみ展開、他は折りたたみ。追加JS不要）
  - 既存のMomentum Score・Confidence Scoreが80以上のテーマにのみ「NEW」
    バッジを表示（新しいスコア算出ロジックではなく、既存スコアへの機械的な
    閾値判定のみ）
  - 目次・Future Intelligenceの重要度★表示を★の数に応じて色分け
    （★5=赤／★4=オレンジ／★3=青／★2以下=グレー）
  - 各セクション右上に📋コピー ボタンを追加（そのセクションのテキストのみを
    クリップボードにコピー）
  - Future Intelligence内のテーマ名・銘柄名について、Theme Intelligence／
    Stock Intelligenceの該当項目が存在する場合のみジャンプリンク化
    （既存のtheme_diagnosis.label／stock_intelligence.tickerとの一致判定の
    みで、新たな関連付けロジックは追加していない）
  - Today's Dashboardの主要指標を画面上部に小さく残す
    sticky（position: sticky）ミニバーを追加
  - モバイル向けにボタン・タップ領域のサイズを拡大

・HTML版 表示オプションパネル（レポート上部に新規カード）
  - コンパクト表示 / 詳細表示切替（コンパクト時は各セクションの詳細説明
    文・凡例のみを非表示にし、見出し・数値・★評価等の要点は残す）
  - 営業セクション一括非表示（営業準備／営業トーク／営業向けコメント／
    岡三証券営業向けコメント／朝会コメント／想定質問と回答例）
  - Future Intelligenceの全ブロック一括開閉ボタン
  - ライト／ダークモード切替（CSS変数の上書きのみ。既存の色分け配色は
    そのまま維持）
  - 上記4設定はlocalStorageに保存し、次回表示時も維持する
  - 外部ライブラリ・フレームワークは使用せず、素のJavaScriptのみで実装

・Markdown版・モバイル版はTable of Contents/表示内容そのものは変更せず、
  Today's Actionの追加のみ反映（表示オプション・折りたたみ等のUI操作は
  HTML版のみ対応）

変更ファイル
・src/report/format_utils.py
・src/report/sections.py
・src/report/html_builder.py
・src/report/mobile_builder.py
・src/report/builder.py
・tests/test_future_intelligence.py
・tests/test_html_builder.py
・tests/test_report_builder.py
・tests/test_mobile_builder.py

pytest
155 passed

コミット
（下記参照）

## v2.1 (2026-07-04)

追加・改善（情報設計・UIのみ。新しい分析ロジック・スコアリング・判定は追加していない）
・Future Intelligence Engine v2.1: 既存14項目（世界のメガトレンド／Theme
  Momentum Score／Early Signal Detection／世界のお金の流れ／テーマ成熟度
  メモ／テーマ別診断／次に来る業界／サプライチェーン分析／国家戦略メモ／
  Future Map／日本株への波及／Watchlist Intelligence／Stock Intelligence／
  中長期テーマ）を「世界→テーマ→業界→銘柄→長期戦略」の5ブロック
  （Information Architecture）へ再構成
  - ① Today's Future Signals ★★★★★（世界のメガトレンド／Theme Momentum
    Score／Early Signal Detection／世界のお金の流れ／今日もっとも重要な
    変化＝既存Theme Momentum Score最上位の理由をそのまま抜粋するハイライト）
  - ② Theme Intelligence ★★★★★（テーマ成熟度メモ／テーマ別診断＝
    Momentum→Lifecycle→Catalyst→Risk→Confidence→関連テーマ）
  - ③ Industry Intelligence ★★★★☆（次に来る業界／サプライチェーン分析／
    国家戦略メモ／Future Map）
  - ④ Stock Intelligence ★★★★★（日本株への波及／Watchlist Intelligence／
    Stock Intelligence＝銘柄別投資ストーリー）
  - ⑤ Long-term Strategy ★★★★☆（中長期テーマ＝半年〜10年の時間軸）
  - 各ブロック冒頭に「このブロックで分かること」を1〜2行で表示、重要度★を
    表示、Future Intelligence専用の内部目次を追加
  - HTML版: 各大ブロックをカード化し、Today's Future Signals=青／Theme
    Intelligence=紫／Industry Intelligence=緑／Stock Intelligence=
    オレンジ／Long-term Strategy=ゴールドに色分け。目次から各ブロックへ
    ジャンプ可能
  - モバイル版: 折りたたみは使わず、見出し（###）を大きくしてスクロール
    で読める形に変更（内容は既存の条件付きハイライトのまま。Long-term
    Strategyのみ既存bundle.horizon_groupsを新たに表示に追加）
・レポート全体の目次を「投資家が毎朝見る順番」＝重要度順に再構成
  （今日の結論→AI Executive Summary→岡三ストラテジスト視点→Future
  Intelligence Engine→今日の相場シナリオ→…の順）。Future Intelligence
  Engineは全体目次では1項目のみ表示し、内部の5ブロック専用目次を別途持つ。
  HTML・Markdown・モバイルの3形式すべてで同じ順序・重要度★表示に統一
・Markdown版に目次（`## 目次`）を新規追加（HTML版は既存の目次カードの並びを
  変更、モバイル版はセクション番号を並び替え）

これにより、毎朝「上から順番に読むだけ」で世界情勢→マーケット→テーマ→
業界→銘柄→投資判断へ自然につながる構成になった。分析ロジック・
スコアリング・各セクションの表示内容そのものは一切変更していない。

変更ファイル
・src/report/sections.py
・src/report/html_builder.py
・src/report/mobile_builder.py
・src/report/builder.py
・tests/test_future_intelligence.py
・tests/test_report_builder.py
・tests/test_html_builder.py
・tests/test_mobile_builder.py

pytest
142 passed

コミット
（下記参照）

## v2.0 (2026-07-04)

追加
・Future Intelligence Engine v2.0: 「Stock Intelligence」を追加（既存の
  Future Intelligence Engineセクション内に追加。Watchlist Intelligenceで
  一致した銘柄のみを対象）
  - 表示項目: 銘柄名・ティッカー・関連テーマ・関連テーマ数・Momentum・
    Lifecycle・Catalyst・Risk・Confidence・現在の判断（注目継続／押し目待ち
    ／過熱警戒／材料待ち／判断材料不足。既存のWatchlist Intelligenceの
    判定ルールをそのまま流用し整合性を維持）
  - 新規項目①なぜ長期で見るのか: テーマ名・Catalyst・Lifecycle・Momentum
    のみから機械的に組み立てた定性文
  - 新規項目②今後注目するイベント: 決算・設備投資動向に加え、関連テーマ
    （半導体市況・電力需給・金利動向・為替動向等）から機械的に導出。
    AIによる新たな予測はしない
  - 新規項目③注意すべきリスク: 既存Riskを複数テーマ分まとめて拡張表示
  - 新規項目④関連するテーマ: config.yamlのtheme_relations（Cross Theme
    Mapping）をそのまま利用
  - 新規項目⑤投資ストーリー: テーマ名→Catalyst→関連テーマへの波及→
    非断定的な結び、という時系列の因果チェーンのみで構成。目標株価・
    PER/EPS予想・「買い」「売り」等の推奨・期待リターンは一切生成しない
  - Markdown・モバイル版・HTML版すべてに反映（既存のFuture Intelligence
    Engineセクション内。他のセクション構成・既存のWatchlist Intelligence
    のロジックは変更していない）

これにより、Future Intelligence → Watchlist Intelligence → Stock
Intelligence まで一気通貫で分析できるようになった
（世界の変化→テーマ→企業→長期投資ストーリー）。

変更ファイル
・src/analysis/models.py
・src/analysis/future_intelligence.py
・src/report/sections.py
・src/report/html_builder.py
・src/report/mobile_builder.py
・tests/test_future_intelligence.py

pytest
136 passed

コミット
（下記参照）

## v1.16 (2026-07-04)

追加
・Future Intelligence Engine v1.9: Macro Themeを17拡張し、Watchlist
  Intelligenceの一致率をさらに向上（新しい分析ロジックは追加せず、
  macro_themes／causal_rules／sectors／theme_relationsの辞書拡張のみ）
  - 追加テーマ: 自動車／EV／蓄電池／金融／金利／為替／消費／人材／広告／
    SaaS／スマートフォン／クラウド／決済／旅行／住宅／建設／インバウンド
    （物流は既存テーマのため、causal_rulesのみ追加して強化）
  - 単純な業種分類ではなく「投資テーマとの経済的な因果関係」を優先して
    紐付け（例: 自動車→EV→蓄電池→半導体・電力・資源、金利→金融→為替、
    AI→クラウド→データセンター→電力）
  - config.yamlのtheme_relationsを拡張し、テーマ別診断の「関連テーマ」
    表示を強化
  - Markdown・モバイル版・HTML版すべてに反映（既存のFuture Intelligence
    Engineセクション内。他のセクション構成・既存の診断ロジックは変更して
    いない）

Watchlist Intelligence改善効果（手元のconfig.yamlで実測、監視銘柄30件）
  - 追加前（v1.8時点）: 判断材料不足 6件 ／ 一致率 24/30（80%）
    （未一致: トヨタ自動車・三菱UFJ・リクルート・デンソー・Apple・Tesla）
  - 追加後（v1.9）: 判断材料不足 0件 ／ 一致率 30/30（100%）
    （例: トヨタ自動車→自動車・EV・蓄電池・為替・消費、
    三菱UFJ→金融・金利・決済、Apple/リクルート→AI・半導体・人材・広告・
    SaaS・スマートフォン・クラウド・決済、Tesla→自動車・EV・蓄電池・為替・消費）

変更ファイル
・config.yaml
・tests/test_future_intelligence.py

pytest
130 passed

コミット
（下記参照）

## v1.15 (2026-07-04)

改善
・Future Intelligence Engine v1.8: Watchlist Intelligenceの精度向上
  （新しい分析ロジックは追加せず、辞書・マッピングの充実のみ）
  - config.yamlのsectors（related_tickers）・causal_rules
    （beneficiary_sectors）を、「投資テーマとの経済的な因果関係」を優先して
    拡充。例: AI関連の設備投資拡大は、半導体（東京エレクトロン等）だけで
    なく、データセンター運営主体（NTT・Microsoft・Amazon等）、電力設備・
    電気工事（きんでん・日立製作所）、電線・素材（古河電工・住友電工等）
    まで、単純な業種分類ではなくサプライチェーン・設備投資の因果関係で
    紐付けた
  - config.yamlに theme_relations（テーマ同士の対応付け。人手による参考
    情報でAIによる生成ではない）を新設し、テーマ別診断に「関連テーマ」
    （例: AI→半導体・電力・サイバーセキュリティ・自動運転・量子）を追加
  - Watchlist Intelligenceで「判断材料不足」になる銘柄をテスト環境で
    実際に削減できることを確認（テストで検証）
  - Markdown・モバイル版・HTML版すべてに「関連テーマ」を反映（既存の
    Future Intelligence Engineセクション内。他のセクション構成・既存の
    診断ロジックは変更していない）

変更ファイル
・config.yaml
・src/analysis/models.py
・src/analysis/future_intelligence.py
・src/report/sections.py
・src/report/html_builder.py
・src/report/mobile_builder.py
・tests/test_future_intelligence.py

pytest
127 passed

コミット
（下記参照）

## v1.14 (2026-07-04)

追加
・Future Intelligence Engine v1.7: 「Watchlist Intelligence（監視銘柄×
  テーマ診断）」を追加（既存のFuture Intelligence Engineセクション内に
  小見出しとして追加）
  - config.yamlのwatchlist銘柄（jp_stocks/us_stocks）と、v1.6のテーマ別
    診断（Momentum・Lifecycle・Catalyst・Risk・Confidence）を、既存の
    causal_rules恩恵銘柄ロジック（テーマ→beneficiary_sectors→
    related_tickers）だけを使って照合し、長期の資産形成・投資判断のために
    「今見るべき銘柄」を整理する。営業利用ではなく自分自身の投資判断を
    最優先目的とする
  - 表示項目: 銘柄名・ティッカー・関連テーマ・Momentum・Lifecycle・
    Catalyst・Risk・Confidence・現在の判断ラベル・判断理由
  - 判断ラベルは「注目継続／押し目待ち／過熱警戒／材料待ち／判断材料不足」
    のみを使用し、「買い」「売り」等の断定的な売買助言は一切行わない
  - Markdown・モバイル版・HTML版すべてに反映（既存のFuture Intelligence
    Engineセクション内。他のセクション構成は変更していない）

変更ファイル
・src/analysis/models.py
・src/analysis/future_intelligence.py
・src/report/sections.py
・src/report/html_builder.py
・src/report/mobile_builder.py
・tests/test_future_intelligence.py

pytest
123 passed

コミット
（下記参照）

## v1.13 (2026-07-04)

追加
・Future Intelligence Engine v1.6:「テーマ別診断（Momentum→Lifecycle→
  Catalyst→Risk→Confidence）」を追加（既存のFuture Intelligence Engine
  セクション内に小見出しとして追加）
  - 本システムの最優先目的を「営業ツール」ではなく「世界の変化をいち早く
    察知し、長期の資産形成・投資判断に役立てる未来分析システム」と位置づけ、
    macro_themeごとにMomentum→Lifecycle（フェーズ・継続性）→Catalyst
    （加速要因）→Risk（失速要因）→Confidence（分析根拠の充実度）の順で表示
  - Catalyst（加速要因）・Risk（失速要因）は、ニュース・Executive Summary・
    Theme Momentum・Early Signal・causal_rules・durable_themes・
    サプライチェーン（恩恵銘柄）・国家戦略メモ・世界のお金の流れという
    既存シグナルのみから機械的に導いた「AI分析」であることを明記し、
    具体的な数値・政策名・企業業績の断定はしない
  - Confidence Score（0〜100）は「未来が当たる確率」ではなく、上記シグナル
    のうち実際に確認できたものの数（＝分析根拠の充実度）を表すことを明記
  - Markdown・モバイル版・HTML版すべてに反映（既存のFuture Intelligence
    Engineセクション内。他のセクション構成は変更していない）

変更ファイル
・src/analysis/models.py
・src/analysis/future_intelligence.py
・src/report/sections.py
・src/report/html_builder.py
・src/report/mobile_builder.py
・tests/test_future_intelligence.py

pytest
120 passed

コミット
（下記参照）

## v1.12 (2026-07-04)

追加
・Future Intelligence Engine v1.5:「世界のお金の流れ（市場シグナルベース）」を
  安全な縮小版として追加（既存のFuture Intelligence Engineセクション内に
  小見出しとして追加）
  - 実際の機関投資家ポジション・資金流入額は取得していないため、具体的な
    資金フローは断定しない旨を冒頭に明記（「実際の資金流入額ではなく、
    公開市場データとニューステーマから見た資金の向かいやすさです」）
  - 公開市場データ（日経平均・TOPIX・NASDAQ・SOX・VIX・米10年金利・
    ドル円・WTI・金）とTheme Momentum Score・Early Signal Detection・
    Sector Ranking・causal_rules・durable_themesという既存シグナルのみ
    から、「AI・半導体」「金融・銀行」「防衛・電力・インフラ」「内需・消費」
    「コモディティ・資源」の5テーマについて、資金方向ラベル（流入しやすい／
    中立／流出しやすい／判断材料不足）・理由・関連テーマ・関連セクター・
    営業で話すポイントを機械的に算出
  - リスクオン/オフ・グロース優位/バリュー優位の参考情報も、VIX指数・
    NASDAQ対TOPIXという既存の市場データのみから算出し、文脈情報として付記
  - 「資金が流入している」「機関投資家が買っている」「海外勢が買っている」
    「◯億円流入」等の断定・捏造表現は一切使わず、「資金が向かいやすい」
    「物色されやすい」「市場シグナル上は追い風」等の非断定表現に統一
  - Markdown・モバイル版・HTML版すべてに反映（既存のFuture Intelligence
    Engineセクション内。他のセクション構成は変更していない）

変更ファイル
・main.py
・src/analysis/models.py
・src/analysis/future_intelligence.py
・src/report/sections.py
・src/report/html_builder.py
・src/report/mobile_builder.py
・tests/test_future_intelligence.py

pytest
116 passed

コミット
（下記参照）

## v1.11 (2026-07-04)

改善
・Future Intelligence Engine v1.4: Theme Momentum Score・Early Signal Detectionの
  判定材料を拡張
  - Theme Momentum Score: 本日の関連見出し件数・重要ニュースとの一致・
    causal_rules該当・durable_themes該当に加えて、Executive Summary
    （executive_summary.pyが算出した本日最重要ニュース）との一致、および
    既存のcausal_rules恩恵銘柄ロジックから導ける関連セクター・関連銘柄の
    有無という既存シグナルを追加（0〜100点への配分を6シグナル分に再配分）。
    理由欄には、世界のメガトレンド評価（★・フェーズ）を文脈として明記する。
    関連セクター・関連銘柄も新たに表示する
  - Early Signal Detection: 判定条件（見出しが少ない・causal_rules該当・
    durable_themes該当・恩恵銘柄が解決できる）は変更せず、恩恵銘柄が
    解決できるという既存条件を「営業利用価値がある」ことの根拠として明記した
    うえで、関連セクター・関連銘柄という実データのみから機械的に組み立てた
    「営業で話すポイント」を追加
  - いずれも具体的な市場規模・件数以外の断定的な数値は生成しない
  - Markdown・モバイル版・HTML版すべてに反映（既存のFuture Intelligence
    Engineセクション内。他のセクション構成は変更していない）

変更ファイル
・main.py
・src/analysis/models.py
・src/analysis/future_intelligence.py
・src/report/sections.py
・src/report/mobile_builder.py
・src/report/html_builder.py
・tests/test_future_intelligence.py

pytest
111 passed

コミット
（下記参照）

## v1.10 (2026-07-04)

改善
・Future Intelligence Engine v1.3: 「テーマ成熟度メモ」「国家戦略メモ」を
  「未登録」中心の表示から、既存シグナルからのAI分析を優先表示する方式に改善
  - 表示の優先順位: ① `config.yaml` への手動登録があれば最優先で「登録情報」
    として表示 → ② 手動登録が無くても、本日の関連見出し件数・durable_themes
    該当・causal_rules該当・恩恵銘柄という既存シグナルがあれば、そこから
    導いたルールベースの定性的な「AI分析」を表示 → ③ 判断材料となる信号が
    何も無い場合のみ「分析材料不足」と表示（「未登録」だけで終わる表示を削減）
  - 国家戦略メモは、国・地域とmacro_themesの重点分野を対応付けた人手による
    参考情報（`NATIONAL_FOCUS_AREAS`。AIが生成したものではない）を追加し、
    未登録の国・地域でも本日のテーマ動向からAI分析を導けるようにした
  - いずれの表示も「登録情報」「AI分析」「分析材料不足」のラベルと判断根拠
    （どの既存シグナルから導いたか）を明記し、具体的な市場規模・補助金額・
    政策名・法案名は一切生成しない（「〜と考えられます」等の非断定表現に統一）
  - Markdown・モバイル版・HTML版すべてに反映（既存のFuture Intelligence
    Engineセクション内。他のセクション構成は変更していない）

変更ファイル
・src/analysis/models.py
・src/analysis/future_intelligence.py
・src/report/sections.py
・src/report/mobile_builder.py
・src/report/html_builder.py
・tests/test_future_intelligence.py

pytest
108 passed

コミット
（下記参照）

## v1.9 (2026-07-04)

追加
・Future Intelligence Engine v1.2: 「テーマ成熟度メモ」「国家戦略メモ」を追加
  （既存のFuture Intelligence Engineセクション内に小見出しとして追加）
  - テーマ成熟度メモ: `config.yaml` の `theme_maturity_notes`（macro_themes
    の各テーマについて、市場ステージ／市場規模メモ／普及状況メモ／
    競争環境メモ／参入障壁メモ／リスクメモを手動登録）をそのまま表示。
    AIによる市場規模・普及率等の生成・推定は一切行わない
  - 国家戦略メモ: `config.yaml` の `national_strategy_notes`（日本／米国／
    中国／EU／インド／中東の6地域固定で、重点分野・政策メモ・規制メモ・
    市場影響メモを手動登録）をそのまま表示。AIによる補助金額・政策内容の
    生成・推定は一切行わない
  - いずれも未登録のテーマ・国・項目は「未登録」と明記する
  - `config.yaml` には空の `theme_maturity_notes: {}` / `national_strategy_notes: {}`
    と、コメントアウトされた記入例のみを追加（デフォルトはすべて「未登録」）

変更ファイル
・config.yaml
・src/analysis/models.py
・src/analysis/future_intelligence.py
・src/report/sections.py
・src/report/mobile_builder.py
・src/report/html_builder.py
・tests/test_future_intelligence.py

pytest
105 passed

コミット
（下記参照）

## v1.8 (2026-07-04)

追加
・Future Intelligence Engine v1.1: Theme Momentum Score と Early Signal
  Detection を追加（既存のFuture Intelligence Engineセクション内に小見出しとして追加）
  - Theme Momentum Score: 各macro_themeについて、本日の関連見出し密度・
    本日の重要ニュース（news_ranking）との一致・causal_rules該当・
    durable_themes該当という既存シグナルのみから0〜100の定性スコアを算出。
    前日比・週次比較は行わない（履歴データを保持していないため）。
    急加速／加速／横ばい／減速の4段階ラベルと理由を付与
  - Early Signal Detection: 本日の見出し件数はまだ少ない（1件以下）ものの、
    causal_rules該当・durable_themes該当・恩恵銘柄が解決できる、という
    条件をすべて満たすテーマを「初動シグナル」として抽出（★・理由・
    関連セクター・代表的な関連銘柄を表示）
・詳細版・モバイル版・HTML版すべてに反映（既存のFuture Intelligence Engine
  セクション内。他のセクション構成は変更していない）

変更ファイル
・src/analysis/models.py
・src/analysis/future_intelligence.py
・main.py
・src/report/sections.py
・src/report/mobile_builder.py
・src/report/html_builder.py
・tests/test_future_intelligence.py

pytest
101 passed

コミット
（下記参照）

## v1.7 (2026-07-04)

追加
・Future Intelligence Engine v1.0（グループAのみ）を新設。世界の長期テーマ
  （config.yaml `macro_themes`。AI/半導体/電力/GX/DX/防衛/宇宙/量子/核融合/
  ロボット/医療/バイオ/サイバーセキュリティ/水インフラ/物流/資源/食料/
  人口減少/高齢化/自動運転の20テーマ）を、既存の
  `durable_themes`・`causal_rules`・本日の関連見出し件数・恩恵銘柄ロジックの
  みから定性的に評価する新モジュール `src/analysis/future_intelligence.py`
  - 世界のメガトレンド（★・フェーズ［黎明期/成長初期/急成長期/成熟期/減速期］・
    継続性［高い/中程度/限定的］・なぜ伸びるか）
  - 次に来る業界ランキング（本日のモメンタム順）
  - サプライチェーン分析（causal_rulesの因果チェーンを再利用）
  - 中長期テーマ（半年/1年/3年/5年/10年への定性的な割り付け）
  - 日本株への波及（恩恵銘柄。大型/中小型は区分不明として明記）
  - Future Map（テーマ一覧）
  - 詳細版・モバイル版・HTML版すべてに「Future Intelligence Engine」として
    1セクションにまとめて追加（既存セクション番号は変更せず末尾に追加）
・具体的な残り年数・市場規模・補助金額等は一切生成しない（実データの裏付けが
  ない数値は使わない方針を徹底）。テーマ成熟度・国家戦略分析・世界のお金の
  流れはv1.1以降に見送り（設計提案書のグループB/Cに該当）

変更ファイル
・config.yaml
・main.py
・src/analysis/models.py
・src/analysis/future_intelligence.py【新規】
・src/report/builder.py
・src/report/sections.py
・src/report/mobile_builder.py
・src/report/html_builder.py
・tests/test_future_intelligence.py【新規】
・tests/test_report_builder.py
・tests/test_mobile_builder.py
・tests/test_html_builder.py

pytest
97 passed

コミット
（下記参照）

## v1.6 (2026-07-04)

改善
・HTML上部の「最新情報に更新」ボタンの仕様を変更。GitHub Actionsの
  workflow_dispatch実行ページへ遷移する方式から、`javascript:location.reload()`
  によるページ再読み込みのみのボタン（「🔄 最新表示に更新」）へ変更。
  外部JS不要・常時表示（`actions_url`の有無に依存しない）
・毎朝の自動生成・自動デプロイを基本運用とし、手動でのワークフロー実行は
  README上で補足的な案内に位置づけ直した

修正
・（なし）

判断: `config.yaml` の `output.actions_url` と `main.py` の
`_resolve_actions_url()` は削除せず残した。html_builder.py側では
未使用になったが、main.pyからbuild_html_reportへの`actions_url`引数は
削除するとmain.py・config.yamlの2ファイルに追加の変更が必要になり、
現時点で機能上のメリットがない削除のために変更範囲を広げるのは
「最小差分」の方針に反すると判断したため。将来この設定を使う機能
（例: 別ボタンでのActions画面誘導を復活させる等）を追加する際に
そのまま再利用できる。

変更ファイル
・src/report/html_builder.py
・tests/test_html_builder.py
・README.md

pytest
90 passed

コミット
（下記参照）

## v1.5 (2026-07-04)

修正
・`deploy-pages` ジョブの `actions/deploy-pages@v4` ステップから
  `timeout: 1200000 / error_count: 10 / reporting_interval: 10000` の指定を削除。
  `timeout` の許容上限（60000ミリ秒）を超えていたため警告が出ており、
  デプロイ失敗（`エラー：展開に失敗しました。後で再挑戦してください。`）と
  合わせて発生していた。既定動作（アクション側のデフォルト設定）に戻すことで解消
・`generate-report` ジョブ、`deploy-pages` ジョブの `timeout-minutes: 20`、
  GitHub Pages の Source/Environment 設定は変更していない

変更ファイル
・.github/workflows/daily-market-brief.yml

pytest
91 passed

コミット
（下記参照）

## v1.4 (2026-07-04)

修正
・`build_html_report()` に `actions_url` キーワード引数が定義されておらず、
  GitHub Actions実行時に `got an unexpected keyword argument 'actions_url'`
  という警告が出ていた不整合を修正。`actions_url: Optional[str] = None` を
  明示的に追加し、`main.py` からの呼び出しと整合させた
・`actions_url` が `None`（または空文字）の場合は「最新情報に更新」ボタンを
  表示しない挙動を維持（既存ロジックのまま、型ヒントのみ明確化）

変更ファイル
・src/report/html_builder.py
・tests/test_html_builder.py

pytest
91 passed

コミット
（下記参照）

## v1.3 (2026-07-04)

追加
・HTMLレポート（Today's Dashboardのすぐ下）に「🔄 最新情報に更新」ボタンを追加。
  押すとGitHub Actions「Daily Market Brief」ワークフローの実行ページへ遷移し、
  そこで「Run workflow」を押せば最新ニュース・最新データでレポートを再生成できる
・`config.yaml` の `output.actions_url`（環境変数 `ACTIONS_URL` でも上書き可）で
  ボタンのリンク先を明示できるように設定を追加。未設定時は
  `GITHUB_REPOSITORY` から自動組み立て、どちらも無ければボタン自体を非表示

変更ファイル
・main.py
・src/report/html_builder.py
・config.yaml
・tests/test_html_builder.py
・README.md

pytest
90 passed

コミット
（下記参照）

## v1.2 (2026-07-04)

改善
・`CLAUDE.md` に「設計原則」（ディレクトリ構成／システム設計／ファイル名／
  設定ファイル構成／ワークフロー／GitHub Actions・Pages／ニュース評価ロジック／
  スコアリングロジック／営業思想／ストラテジスト思想／UIデザイン／出力フォーマット
  はChatGPT（監督者）が決定し、Claude Codeは提案のみ行う）を追加
・「リファクタリング」ルール（依頼のない限りリネーム・ファイル移動・関数統合・
  大規模整理・不要コード削除を禁止）を追加

変更ファイル
・CLAUDE.md

pytest
89 passed（コード変更なし。既存スイートに影響なし）

コミット
（下記参照）

## v1.1 (2026-07-04)

改善
・`CLAUDE.md` を、ユーザー提示の15項目「更新ポリシー」を最上位ルールとして
  明記する形に更新（リポジトリ全体を書き換えない／変更ファイルのみ提出／
  ZIPは依頼時のみ／フォルダ構成・Git構成・GitHub Pages/Actions/Secretsは
  依頼がない限り変更しない、等）

変更ファイル
・CLAUDE.md

pytest
（コード変更なしのため実行対象なし。既存89件のスイートに影響なし）

コミット
（下記参照）

## v1.0 (2026-07-04)

追加
・岡三証券の内部ストラテジストレポート（「グローバル投資の羅針盤」5号分）から
  学習した「ニュース評価・投資アイデア変換」の思考プロセスを一般化し、
  `src/analysis/strategist_engine.py` として実装
・8軸★スコアリング（市場インパクト／継続性／営業利用価値／日本株影響度／
  米国株影響度／個別株へ展開できるか／テーマ株へ展開できるか／今後数週間重要か）
・「ニュース→岡三ストラテジストならどう見るか→重要テーマ→関連セクター→
  恩恵銘柄→悪影響銘柄→営業で話すポイント→重要度」パイプラインと、
  レポート新セクション「岡三ストラテジスト視点」（詳細版・モバイル版・HTML版）
・`config.yaml` に `causal_rules`（因果チェーンルール）・`durable_themes`
  （継続性の高いテーマ一覧）を追加

改善
・`news_ranking.py` の重要度スコアに、因果チェーン該当・継続性の高いテーマ
  該当の加点を追加（既存スコアリングへの後方互換は維持）
・`executive_summary.py` に恩恵銘柄／悪影響銘柄／ストラテジスト視点の
  一言まとめを追加

変更ファイル
・config.yaml
・main.py
・src/analysis/executive_summary.py
・src/analysis/models.py
・src/analysis/news_ranking.py
・src/analysis/strategist_engine.py【新規】
・src/report/builder.py
・src/report/html_builder.py
・src/report/mobile_builder.py
・src/report/sections.py
・tests/test_mobile_builder.py
・tests/test_report_builder.py
・tests/test_strategist_engine.py【新規】
・README.md
・CLAUDE.md【新規】
・CHANGELOG.md【新規】

pytest
89 passed

コミット
6834f70
