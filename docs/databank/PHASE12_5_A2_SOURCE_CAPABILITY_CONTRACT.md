# PHASE 12.5 — A2: SOURCE CAPABILITY CONTRACT ／ P13 REVIEW STATE MEMORY MVP（設計だけ ・runtime は無い）

P12.5-A1（source capability investigation ＝ PASS）の結果を正式な契約にする。凍結の Phase 8 〜 12 の **実在する read-only の面**を
file ・symbol ・行で目録にし、「呼べる」と「下流が消費を承認されている」を分け、Market Memory の各能力を AVAILABLE ／ LIMITED ／ GATED ／
UNAVAILABLE に分類し、P13 の最初の MVP を **Review State Memory**（市場の観測の記憶ではない）として、既存の P10 の governed な
3 関数だけを入力に定める。本文書は設計だけであり、**P13 の runtime ・adapter ・store ・projector ・private root ・vault は存在しない ・
本 gate は実装を一切承認しない**。importer の登録（§10）も **提案であり本 gate では実装しない**。

| 項目 | 値 |
|---|---|
| 状態 | **DESIGN ONLY（P12.5-A2）**。P12.5-A0（`PHASE12_5_A0_MARKET_MEMORY_ARCHITECTURE.md`）の不変量を変えない ・補う |
| 調査した HEAD | `f205c0c70936748b1078aa0f48098bde148c54a1`（A0 の契約の commit。行番号はこの tree のもの） |
| MVP | **P13 Review State Memory**: 入力は P10 の `read_personal_review` ・`read_p9_safe_view` ・`personal_safe_projection` だけ（＋既存の error 型） |
| MVP の外 | P8 の観測 ・訂正の履歴 ・取得の履歴 ・P9 ／ P10 の revision の鎖 ・P12 の ledger（全て GATED。§12） |
| 凍結 | Phase 4 〜 11 ・Phase 12 A-track v1（`e390cdd…` ・validated `3056e25…`）は不変。本 gate で `src/` は変えない |

guard: `tests/intelligence/test_automation_boundary.py` の `test_p12_5_a2_the_source_capability_contract_is_design_only_and_holds_no_private_values`。
登録: `tests/intelligence/phase12_runtime_registry.py` の `PHASE12_5_DOCS`。

読み方: **[code]** ＝ HEAD の code で確かめた挙動、**[doc]** ＝ 凍結の契約文書の記述、**[proposed]** ＝ 本文書の提案（存在しない）。

---

## 1. 範囲と非主張

- 本 gate の成果物は本文書 ・CHANGELOG ・文書の登録と guard だけ。`src/` ・config ・workflow ・公開の面 ・private root ・scheduled task ・
  凍結の test の importer の一覧は不変。
- 本文書は P13 の code ・package ・root ・vault の存在を主張しない。§10 の import の集合は「将来の gate が登録するなら正確にこれ」という
  **提案**であり、登録そのものは P13-A2a（別の gate）で行う。
- A0 の architecture（hybrid ・DERIVED ・PIT ・export だけ ・分離）を変えない。A0 との関係で確認が要る点は §7.5 ・§14 に明記し、A0 の
  本文は変えない（監督の承認が無い限り）。

## 2. 分類の定義

- **AVAILABLE**: 既に下流の消費が承認 ・pin されている governed な read の面（§4）だけで、明示の aware な cutoff と `as_of_date` の下で、
  出力の全ての欄が A0 §7 の safe surface に収まる形で得られる。
- **LIMITED**: AVAILABLE と同じ面で得られるが、粒度 ・時刻 ・provenance に本質的な制限があり、その制限を item に **明示して**記録しない
  限り使えない（例: 先頭の状態だけ ・source の時刻が無い ・標本の間の変化だけ）。
- **GATED**: 凍結の package の中に callable は実在するが、(a) どの下流にも消費が承認されていない、または (b) 消費には凍結の boundary test の
  狭い再開（importer の登録）と監督の gate が要る、または (c) 出力が safe surface を越える値（財務の値 ・名前 ・provider の code ・自由文 ・
  著者）を含み、redaction の方針の決定が要る。
- **UNAVAILABLE**: 実在する callable でも凍結の契約でも得られない（新しい reader ・新しい authority の面が要る）。本調査の範囲ではこの分類に
  落ちる能力は無い（全て GATED 以上）。ただし P11 の `read_ui_model` は id を捨てるため **記憶の入力としては不適**（§3.4）。

## 3. 読み取り面の目録（HEAD `f205c0c…` の行）[code]

### 3.1 Phase 8 — `src/intelligence/screener_intelligence/`

| callable | 入力 | 出力の粒度 | PIT | provenance | private root |
|---|---|---|---|---|---|
| `observation_resolver.resolve`（行 232）・`resolve_at_data_root`（行 269） | history か `data_root` ・`ObservationQuery`（class ・subject ・field ・basis ・session_date か period ・source_class）・keyword 必須の aware `cutoff` | `ObservationResolution`（行 137）: status FOUND ／ NOT_FOUND ／ NOT_YET_KNOWN ／ AMBIGUOUS ／ INSUFFICIENT_TIME_PRECISION ／ BEFORE_COVERAGE ／ OUTSIDE_COVERAGE ／ AUTHORITY_MISSING ／ STORE_CORRUPTION ／ SUBJECT_NOT_RESOLVED（行 38 〜 48）・`record`（**財務の値を含む**）・`lineage`（supersedes の鎖の id）・`candidates` | 必須 | record id ・`provenance.source_record_ref` ・`supersedes` ・lineage ・coverage の id ・resolver の version | `_at_data_root` は root の jsonl を直接読む |
| `observation_model.KnowledgeTime.state_at`（行 331） | aware cutoff | KNOWN ／ UNKNOWN ／ UNCERTAIN | 必須 | — | memory の中 |
| `identity_resolver.resolve`（行 323）・`resolve_at_data_root`（行 373） | `IdentityQuery` ・`cutoff` | `IdentityResolution`: `SecurityView` ／ `IssuerView` に **表示名 ・provider の識別子の値**を含む（行 116 〜 183） | 必須 | record id | 有 |
| `identity_remediation_resolver.resolve_remediated`（行 222）・`observation_retrospective_resolver.resolve_retrospective`（行 194） | strict の cutoff か `authority_as_of` ＋ `identity_valid_at` ・manifest ・correction ・holdings | 訂正の鎖 ・retrospective の解決（解釈は「世界の知識の主張ではない」） | 必須 | correction の id ・authority の version ・coverage epoch | memory ／ `_at_data_root` |
| `AcquisitionEventStore.open(root, read_only=True)` → `records` ・`get` ・`counts`（store 行 99 〜 200） | root | `AcquisitionEvent`（model 行 193）: provider ・scope ・`acquired_at` ・status COMPLETE ／ PARTIAL_PAGINATED ／ FAILED ／ EMPTY ・row_count ・pagination の有無 ・`content_digest` ・failure_code | **cutoff 無し**（消費側が `acquired_at` で絞る） | content digest ・record id | 有 |
| `ManifestStore.open(...)` → `records` ・`by_acquisition` ・`by_reference`（store 行 100 〜 221） | root | `AcquisitionManifest`（model 行 203）: acquisition_ref ・digest ・subject_id ・**provider の code** ・entries（**code を含む provider_record_ref** ・provider_record_digest ・disposition ・field → 観測 id）。**時刻の欄は無い** | 無し | digest ・ref | 有 |
| `IdentityStore` ・`ObservationStore` ・`HeldObservationStore` ・`ProviderHoldingsStore` ・`SemanticMetadataStore` ・`PolicyAuthorityStore` ・`UniverseAuthorityStore` の `open(read_only=True)` ・`records` ・`get_by_*` ・`list_metadata` | root | 検査済みの record の object そのまま（store は redaction しない） | identity の `known_by(cutoff)` だけ | record id | 有 |

privacy の事実 [code]: `ObservationProvenance` は本文 ・path ・credential を持たない（observation_model 行 458）。解決の結果は
`DERIVED_NON_AUTHORITY_NON_PERSISTENT`（「store に書けない」）。診断は `code:detail:行番号` で path を含まない。しかし `record.value.amount`
は財務の値、identity の view は名前と識別子の値を運び、P8 の中にそれを落とす層は無い。

### 3.2 Phase 9 — `src/intelligence/watchlist_thesis_intelligence/`

- `RevisionStore`（store_io 行 85）: `open`（行 108 ・read-only）・`roots` ・`chain(root_id)`（行 178）・`revision` ・`revision_at_seq` ・
  `state_at(root_id, at)`（行 189）・`states_at(at)`（行 193）・`all_revisions` ・`line_for`。PIT ＝ `reviewed_at <= T` の最大 seq
  （revision_model 行 160 〜 164）。返すのは revision の object そのもので、**私的な自由文**（rationale ・statement ・mechanism ・
  catalysts ・risks ・note ・correction_reason）と **author_ref** を同じ object に含む（watch_model 行 117 〜 138 ・thesis_model 行 149 〜 180）。
  構造の欄: 各 id ・seq ・prev_revision_id ・change_kind ・status ・review_due_on ・reviewed_at ・corrects_revision_id ・provenance の種類。
- `projection.safe_projection(stores, *, at, as_of_date)`（行 73）: 件数だけ。`FORBIDDEN_PROJECTION_FIELDS`（行 23 〜 26）が id ・発行体 ・
  文 ・著者 ・reviewed_at ・run の id ・値を締め出す。`review_due_report`（行 89）は root の id ・revision の id ・日。
- `AuthorityStores`（authority_stores 行 36）は追記の API を持ち、下流の interface として禁止 [doc: P9 freeze §5]。
- `p8_handoff.reconstruct_completed_run` ・`reconstruct_bound`（行 152 ・205）・`p8_identity.confirm_reviewed_issuer_record`（行 47）:
  P9 自身の P8 の読み（run の id に束縛 ・`at` は無い）。

### 3.3 Phase 10 — `src/intelligence/personal_intelligence/`

- `p9_view.read_p9_safe_view(p9_root, *, at, as_of_date) -> P9SafeView`（行 106）: 件数だけ（行 88 〜 103）。
- `p9_view.read_p9_private_snapshot(p9_root, *, at) -> P9PrivateSnapshot`（行 156）: root ごとの `watch_entry_id` ・先頭の `revision_id` ・
  `issuer_id` ・`status` ・`review_due_on` ・`provenance_kind`、Thesis の `thesis_id` ・`revision_id` ・`watch_entry_id` ・`status` ・`review_due_on`。
  「private ・local だけ」[doc: P10-A1 §3.2]。P11 の面から **明示に除外** [doc: P11-A1 行 31]。
- `review_view.read_personal_review(p10_root, p9_root, *, at, as_of_date) -> PersonalReview`（行 121）: **id の粒度**の `ReviewEntry`
  （行 77 〜 89）: `record_kind` ・`p9_root_id` ・`p9_revision_id` ・`issuer_id` ・`linked_watch_entry_id` ・`p9_status` ・`p9_provenance_kind` ・
  `review_due_on` ・`due_class` ・`attention`（FOCUS ／ NORMAL ／ MUTE）・`excluded_by_profile` ・`surface_group`。加えて `as_of_date` ・
  `review_lookahead_days` ・`active_profile_present` ・印の件数。内部で `read_p9_private_snapshot` と `ProfileStore` ／ `AttentionStore` の
  `open` ＋ `states_at(at)` を使う。**P10 の revision の id ・`reviewed_at` ・note ・著者 ・除外の発行体の一覧は返さない**（除外は行ごとの真偽だけ）。
- `personal_projection.personal_safe_projection(review)`（行 37）: 件数だけ。
- `ProfileStore` ・`AttentionStore`（`open` ・`states_at` ・`all_revisions`。store_io 行 154 〜 242）: 私的な note と author_ref を含む revision
  （profile_model 行 80 〜 86）。**外部の importer は存在しない**。

### 3.4 Phase 11 — `src/intelligence/personal_ui/`

- `p10_read_adapter.read_ui_model(p10_root, p9_root, *, at, as_of_date) -> UiModel`（行 105）: 入力は §3.3 の 3 関数と error 型だけ。
  **P9 ／ P10 の id ・発行体 ・link の id を捨てる**（`UiReviewEntry` 行 61 〜 74 は ordinal ・種類 ・状態 ・出所の種類 ・期日 ／ 区分 ・印 ・
  真偽だけ）。決定論の byte ・`source_schema_versions`。記憶の入力としては **不適**（subject の identity が無い）。

### 3.5 Phase 12 — `src/intelligence/automation/`

- `LedgerStore(p12_root).open_verified(allow_stale_checkpoint=False) -> LedgerState`（ledger_store 行 88）: 全 `LedgerRecord`
  （ledger_model 行 40 〜 57: sequence ・previous_record_digest ・run_id ・schedule_id ・slot_id ・scheduled_for ・runtime_anchor ・attempt ・
  operator ・transition_from ／ to（SKIPPED ・回復の operator を含む）・failure_code ・step_results ・artifact_digests ・`recorded_at` は
  telemetry）。`verify_chain`（行 164）・checkpoint の分類。**PIT の引数は無い**（sequence の順 ・意味の時刻は `scheduled_for` だけ）。
- `status_store.read_status`（行 47）: authority ではない生の dict（失敗は None）。`status_projection.project_status(..., as_of=None)`
  （行 71）: `as_of` は鮮度の label だけで cutoff ではない（行 90 〜 92）。
- `run_transaction.read_recorded_request`（行 120）・`schedule_authority.read_schedule_authority`（行 39）・`calendar_authority.read_calendar_authority`
  （行 41）・`runtime_pin.read_runtime_pin`（行 66）・`source_manifests.build_root_manifest(root, "P9" か "P10")`（行 49。private root の全 file を
  hash。safe dict に path は無い）・`snapshot_orchestrator.build_snapshot`（行 66。PIT ＝ `scheduled_for`。P11 の `read_ui_model` 経由）。

## 4. 「呼べる」と「消費を承認されている」の区別

- 凍結の boundary test が import の面を **文字列で ・完全一致で**固定する [code]: `test_bo_no_other_package_imports_phase8`
  （test_screener_intelligence_boundary 行 981 〜 995）は package の外の `src/` ・`scripts/` の file に `screener_intelligence` の文字が在れば
  失敗する（凍結の runner 3 つと `SANCTIONED_P9_P8_IMPORTERS` の完全一致を除く）。`test_p10_a1_is_outside_production_and_no_other_code_imports_it`
  （test_personal_intelligence_boundary 行 237 〜 248）は `personal_intelligence` を `SANCTIONED_P11_P10_IMPORTERS` に対して同様に固定する。
  P9（test_watchlist_thesis_boundary 行 254）・P11（test_personal_ui_boundary 行 244 〜 258）・P12（test_automation_boundary 行 394 〜 402 の
  `test_p12_a1_is_outside_production_and_public_code_and_nothing_else_imports_it`）も、それぞれの package 名を含む他の importer を禁じる。
- 従って **P13 のどの adapter も、何を読むにせよ凍結の package の新しい importer であり、凍結の test の狭い再開（P12 と同じ登録の仕組み:
  `PHASE12_TEST_REGISTRATION` ・`only_phase12_registration`）無しには少なくとも 1 つの凍結の test を落とす**。「呼べるから使う」経路は無い。
- 承認済みの消費の鎖 [code]: P8 → P9（`p8_handoff` ・`p8_identity`: store の class の `open(read_only=True)`）／ P9 → P10（`p9_view.py` だけ:
  `WatchlistStore` ・`ThesisStore` ・`check_world` ・`safe_projection` ・error 2 型。phase10 registry 行 52 〜 60）／ P10 → P11
  （`p10_read_adapter.py` だけ: `read_p9_safe_view` ・`personal_safe_projection` ・`read_personal_review` ＋ `P9ViewError` ・`ReviewViewError`。
  phase11 registry 行 75 〜 80）／ P11 → P12（`snapshot_orchestrator` ・`server_readiness`。phase12 registry 行 175 〜 179）。
- 文書の規則 [doc]: P8 PIT 契約 §18 は A1 の store ／ resolver の API の利用者を P8 内部の 2 module に限る。P8 freeze §5 は P9 の read-only の
  消費だけ。P9 freeze §5 は専用の read-only adapter を要し `AuthorityStores` を禁じる。P10 freeze §7: どの phase も自身の gate 無しに P10 の
  private authority を消費しない。P12-A1 §7 ／ §8 ・A3 §1: ledger は運用の実行の authority、status ・run の directory は projection ／ 証拠。
  P12-OBS-003: 「ledger から要約を作る橋は projection の後の gate」。

## 5. 能力の行列

| 能力 | 分類 | 根拠と制限 |
|---|---|---|
| 発行体の PIT 想起（P8 の観測 ・値） | **GATED** | `observation_resolver.resolve` だけが与える。P8 PIT 契約 §18 が利用者を 2 module に限る。下流で P8 の resolver を import した例は無い（P9 は store だけ。p8_handoff 行 29 〜 39）。`record.value.amount` ・名前 ・code が入るので A0 §7 の方針の決定が要る |
| 発行体の PIT 想起（P9 ／ P10 の状態） | **AVAILABLE（LIMITED）** | `read_personal_review` の行が `issuer_id` ・`p9_root_id` ・`p9_revision_id` ・状態 ・期日の区分 ・印 ・除外の真偽を明示の `at` ・`as_of_date` で返す。P8 の事実 ・文 ・瞬間は無い |
| 観測と訂正の履歴（supersedes の lineage） | **GATED** | `ObservationResolution.lineage` ・`ObservationHistory.chains`（observation_model 行 880）は上の P8 の面の中だけ |
| 取得の履歴（event ・manifest） | **GATED（metadata は safe ・code を除く）** | record は本文 ・値を持たない [code]。しかし `provider_code` と `provider_record_ref` に provider の code が入る（model 行 203 ・109）。cutoff 無し ・manifest に時刻無し。P9 の sanctioned set は P13 に及ばない |
| Watchlist ／ Thesis の revision の履歴（seq ・prev ・reviewed_at ・change_kind ・訂正） | **GATED** | `RevisionStore.chain`（store_io 行 178）だけが返し、同じ object に私的な文が在る。P10 の adapter は意図的に先頭だけ（P10-A1 §3.2）。A0 の決定 3 は gate 無しの richer な interface を禁じる |
| Watchlist ／ Thesis の **時点 T の先頭の状態**と標本の間の変化 | **AVAILABLE（LIMITED）** | `read_personal_review` を明示の瞬間の列で呼べば `p9_revision_id` の変化が見える。`reviewed_at` は出ないので変化の瞬間は **cutoff で区切った区間**にしか置けない（§7） |
| 個人の attention ／ profile の変化 | **LIMITED** | 行ごとの `attention` ・`excluded_by_profile` ・`active_profile_present` ・`review_lookahead_days` ・印の件数（review_view 行 148 〜 167）。P10 の revision の id ・瞬間 ・note ・著者は出ない（正しい）。変化は標本の間だけ |
| run ／ skip ／ 回復の履歴 | **GATED（privacy の risk は低い）** | `LedgerStore.open_verified` が hash-chained の全 record を返す（id ・code ・digest ・瞬間だけ）。P12 の nothing-else-imports の guard（行 394）と P12-OBS-003 が塞ぐ。`read_status` は非 authority |
| 決定論の発行体 ／ Thesis ごとの dossier | **AVAILABLE（LIMITED）** | `read_personal_review` ＋ `read_p9_safe_view` ＋ `personal_safe_projection` を明示の cutoff で合成: identity は `issuer_id` ／ `p9_root_id`、状態 ・期日 ・印、lineage は標本ごとの revision id の列。P8 無しなので観測 ・取得の鮮度は無い |

UNAVAILABLE に落ちる能力は無い。ただし次は **既存の面では ・凍結の test を再開せずには**得られない: P8 の値 ・P9 の revision の鎖 ・P10 の
revision の鎖 ・P12 の ledger。

## 6. P13 MVP ＝ Review State Memory

- **定義**: 人が統治する見直しの状態（Watchlist ／ Thesis の先頭の状態 ・期日の区分 ・attention の印 ・profile による除外 ・件数）を、
  明示の cutoff の列で標本化し、DERIVED ・決定論 ・read-only に記憶して private な Markdown に投影する層。**市場の観測の記憶ではない**:
  P8 の観測 ・値 ・取得 ・訂正の履歴は含まない（§12）。
- **入力は P10 の governed な 3 関数だけ**（P11 が消費し、P11 経由で P12 が本番で消費している面と同一）:
  `read_personal_review(p10_root, p9_root, *, at, as_of_date)` ・`read_p9_safe_view(p9_root, *, at, as_of_date)` ・
  `personal_safe_projection(review)`。必要なら既存の error 型 `ReviewViewError` ・`P9ViewError` だけ（新しい error 型 ・新しい reader は無い）。
  `read_p9_private_snapshot` ・P9 の store ・P10 の store ・P8 ・P11 ・P12 は **使わない**。
- **PIT**: 全ての問いは明示の aware な `at`（UTC に正準化）と `as_of_date`（date）。既定 ・時計 ・「最新」は無い。`at` ・`as_of_date` の
  組ごとに 1 つの標本（§7.1）。
- **許す欄**: `ReviewEntry` ・`PersonalReview` ・`P9SafeView` ・`PersonalSafeProjection` の欄そのまま（enum ・日 ・id ・真偽 ・件数）。
  文 ・著者 ・path ・値 ・code は構造上存在しない。
- **出力**: dossier（発行体 ・Thesis ごと）・標本の列 ・標本の間の変化（§7.2）・件数の推移。順位 ・score ・推奨 ・配分 ・取引 ・目標の
  意味は NON-GOAL として存在しない（A0 §4）。
- **authority**: 全て `authority_class = DERIVED`。P9 ／ P10 ／ P12 の root に書かない。vault から authority への経路は無い。

## 7. PIT と provenance の照合（MVP の data に対する真実の表現）

### 7.1 標本（sample）の意味

- 1 回の呼び出し `(at, as_of_date)` の結果は **「cutoff `at` の時点で有効だった先頭の状態」**であり、それ以上ではない。
- **`reviewed_at` と状態の変化の正確な瞬間は許された view に出ない**（review_view 行 77 〜 89 に無い ・P10-A1 §3.2 が意図的に外す）。
  従って標本は source の `known_at` を **知らない**。知っているのは「`known_at <= at`」という上界だけ。
- **`sampled_at`（P13 が標本を取った壁時計の時刻）は telemetry**であり、識別 ・内容 ・PIT の判定に使わない。`at`（cutoff）と `sampled_at`
  と source の `known_at` は 3 つの別の量であり、どれも他で代用しない。**known_at を作らない**: `at` を known_at と呼び替えることも、
  `sampled_at` を known_at に書くことも禁じる。

### 7.2 標本の間の変化（change）の意味

- 2 つの標本 T1 < T2 で `p9_revision_id`（または印 ・除外 ・状態）が異なれば、記録するのは **「(T1, T2] の区間のどこかで変化した」**という
  **cutoff で区切った観測**であり、正確な transition ではない。変化の瞬間 ・回数 ・経路は主張しない。
- **同じ端点の状態は「間に変化が無かった」ことを証明しない**: T1 と T2 で同じ revision id でも、間に別の revision を経て戻った可能性
  （P9 の訂正 ・一時の TRANSITION）を除外できない。従って「変化なし」は記録せず、「端点が一致」とだけ記録する。
- 標本の列を細かくしても区間は区間のままで、正確な `reviewed_at` にはならない。正確な履歴は GATED（§12 の G5）。

### 7.3 P8 の時刻の語彙の対応（畳み込まない）

| 層 | 語彙 | 意味 |
|---|---|---|
| `KnowledgeTime.state_at(cutoff)`（observation_model 行 331） | KNOWN ／ UNKNOWN ／ UNCERTAIN | 1 つの知識の時刻（精度 TIMESTAMP ／ DATE）と cutoff の関係: 確実に知られていた ／ 確実に知られていなかった ／ 精度不足で言えない |
| `observation_resolver.resolve`（行 38 〜 48） | FOUND ／ NOT_FOUND ／ NOT_YET_KNOWN ／ INSUFFICIENT_TIME_PRECISION ／ AMBIGUOUS ／ BEFORE_COVERAGE ／ OUTSIDE_COVERAGE ／ AUTHORITY_MISSING ／ STORE_CORRUPTION ／ SUBJECT_NOT_RESOLVED | 1 つの問いに対する鎖 ・coverage ・identity を合わせた解決の status |

対応: UNKNOWN（次の revision が cutoff で確実に未知）→ 解決は前の revision か NOT_YET_KNOWN ／ NOT_FOUND。UNCERTAIN（次の revision が
精度不足）→ INSUFFICIENT_TIME_PRECISION。AMBIGUOUS は複数の source の head の衝突で、KnowledgeTime の状態ではない。AUTHORITY_MISSING ／
STORE_CORRUPTION は PIT ではなく store の層。A0 §5.5 は UNKNOWN ／ UNCERTAIN ／ AMBIGUOUS を「P8 の PIT 解決」とまとめて書くが、code では
UNKNOWN ／ UNCERTAIN は `KnowledgeTime` の状態、resolver の status は別の語彙である。本文書はこの 2 層を **別々に**保持する。A0 の表の
表現の明確化は監督の承認を待つ（§14。A0 の本文は変えない）。

### 7.4 状態の区別（A0 §5.5 を MVP で保つ）

| 状態 | MVP での発生 | 扱い |
|---|---|---|
| MISSING | 標本の root に P9 ／ P10 の store が無い（`P10_STORE_UNAVAILABLE` ・`P9_UNAVAILABLE`） | 標本を取らず MISSING の標本の証拠を残す ・推測しない |
| STALE | 人が宣言した窓より標本が古い（前回の標本からの経過） | label だけ ・trigger にしない |
| UNKNOWN ／ UNCERTAIN | MVP では **発生しない**（P9 ／ P10 の PIT は `reviewed_at <= T` の決定的な選択）。P8 を gate した時だけ §7.3 の意味で現れる | 欄は予約し MVP では空 |
| AMBIGUOUS | MVP では **発生しない**（store の不変条件で root ごとに head は 1 つ）。P8 の gate で現れる | 同上 |
| INTEGRITY_FAILURE | view の fail-closed（`P10_WORLD_INVALID` ・`P9_INVALID` ＝ store の破損 ・世界の違反）・標本の再検証の不一致 | build を止める ・黙って再導出しない |

### 7.5 A0 の `MemoryItem` との関係（architecture の確認）

- A0 §5.3 ・§5.4 の `MemoryItem` は **source の `known_at`（精度つき）と source の record の digest** を identity と provenance に要する。
  標本化した P10 の view は **どちらも与えない**（`reviewed_at` 無し ・P10 の revision の id ／ digest 無し。P9 の `p9_revision_id` だけが
  内容由来の id として在る）。
- 従って **`MemoryItem` を標本の data に合わせて弱めない**。代わりに別の DERIVED の型を提案する [proposed]:
  - **`ReviewStateSample`**: `(at, as_of_date)` ・view の `schema_version` の組 ・標本の内容（§6 の欄）・`sampled_at`（telemetry ・identity に
    入れない）・identity ＝ domain つき digest(at ・as_of_date ・schema versions ・正準化した内容)。「cutoff で有効だった状態」以上を主張しない。
  - **`ReviewStateChange`**: 隣接する 2 標本の差（区間 (T1, T2] ・変わった欄 ・両端の revision id）。§7.2 の意味。
  - `MemoryItem` は P8 のように `known_at` と digest を持つ source を gate した時に使う。両者は型で区別し、投影でも区別して表示する。
- これは A0 の不変量に反しない（A0 §1 は field ・API を確定しないと明記 ・A0 §5.1 は telemetry と known_at の分離を要求し、本提案はそれに
  従う）。型の名前 ・id の接頭辞は §14 の決定事項。

### 7.6 標本化した P10 の view の provenance の限界（必須の記録）

各標本 ・変化の record には次を **必ず**記録する:
- source の `known_at` は **無い**（上界 `at` だけ）。
- P10（profile ・attention）の revision の id ・digest は **無い**（view が返さない）。P10 の provenance は view の `schema_version` と入力
  `(at, as_of_date)` と P9 の `p9_revision_id` の組だけ。
- P9 の provenance は `p9_revision_id`（revision の全欄に対する内容由来の id。revision_model 行 58）だけ。seq ・prev ・corrects は無い。
- store の byte の digest（root の manifest）は MVP では **無い**（P12 の `build_root_manifest` は P12 の内部の面。P13 で同種の計算をするか
  は §14 の決定）。
- `sampled_at` は telemetry。

## 8. 識別子の方針（MVP）

- `issuer_id` ・`p9_root_id` ・`p9_revision_id` は private な識別子（P9 の `FORBIDDEN_PROJECTION_FIELDS` が公開の投影から外す）。MVP では
  これらを **private な DERIVED の store の中だけ**に置く。
- **Obsidian ／ Markdown への export で用いる id（生の id か digest の短縮か ・file 名の規則）は本 gate では承認しない**（§14）。
  export の設計は P13-A4 の契約で、A0 §6.3 の規則の下で監督が決める。
- 標本 ・変化の record の identity は domain つき digest（A0 §5.4 の方式）。telemetry を含めない。

## 9. 決定論の合成の世界の受け入れ試験と失敗の様態（P13-A2a 以後の gate で課す。本 gate では走らせない）

1. **決定論**: 同じ P9 ／ P10 の store の byte ・同じ `(at, as_of_date)` → 標本の byte 一致 ・identity 一致。
2. **telemetry の独立**: `sampled_at` ・host ・root の位置を変えても標本の identity ・内容は不変。
3. **PIT の単調**: 合成の鎖で、より早い cutoff がより遅い revision id を返すことは無い。
4. **区間の意味**: T1 と T2 の間に revision を 2 つ進めて戻した合成の世界で、端点が一致しても「変化なし」を記録しない。1 つ進めた世界で
   `ReviewStateChange` の区間が (T1, T2] になり瞬間を主張しない。
5. **known_at を作らない**: 標本 ・変化の直列化に `known_at` ・`reviewed_at` の欄が無い（名前の guard）。
6. **fail-closed**: 無い root ・壊れた store ・世界の違反 → MISSING ／ INTEGRITY_FAILURE の証拠だけで標本は無い ・部分の標本は無い。
7. **入力の厳格**: naive な `at` ・date でない `as_of_date` は拒む（下の層の code をそのまま）。
8. **authority の不変**: 標本化の前後で P9 ／ P10 の root の file の byte が不変（合成の世界で検証）。
9. **語彙 ・private**: 直列化に文 ・著者 ・path ・値 ・code ・5 桁の code ・時刻つきの瞬間（`at` ・`as_of_date` の欄を除く）が無い。
10. **import の面**: §10 の集合と完全一致 ・`read_p9_private_snapshot` ・store の class ・P8 ・P9 ・P11 ・P12 の import は guard で失敗。
11. **networkless ・資格情報**: socket ・DNS ・環境変数の値 ・資格情報の変数が在れば起動を拒む（P12 の試験の再利用）。
12. **status の区別**: MISSING ・STALE ・INTEGRITY_FAILURE を 1 つずつ起こす合成 case で別の欄 ・別の表示になり、INTEGRITY_FAILURE だけが
    build を止める。UNKNOWN ／ UNCERTAIN ／ AMBIGUOUS の欄は MVP で常に空。

## 10. P13-A2a の登録 gate（提案 ・本 gate では実装しない）

- **import の集合（完全一致 ・提案）**: 将来の P13 の adapter の file 1 つだけが、次を import する。
  - `..personal_intelligence.review_view`: `ReviewViewError` ・`read_personal_review`
  - `..personal_intelligence.p9_view`: `P9ViewError` ・`read_p9_safe_view`
  - `..personal_intelligence.personal_projection`: `personal_safe_projection`
  これは P11 の `SANCTIONED_P11_P10_IMPORTS`（phase11 registry 行 75 〜 79）と **同じ集合**であり、新しい symbol は 1 つも無い。
- **登録の仕組み（提案）**: P13 の registry（test 側）に `SANCTIONED_P13_P10_IMPORTERS`（file の path → module → symbol の集合）と
  `PHASE13_TEST_REGISTRATION`（取り除く行 ・加える行の完全一致）を置き、凍結の `test_personal_intelligence_boundary.py` の
  `test_p10_a1_is_outside_production_and_no_other_code_imports_it`（行 237 〜 248）に P13 の importer の分岐を **登録した行だけ**で足す。
  P12 が P7 〜 P11 の test に行った登録（phase12 registry の `PHASE12_TEST_REGISTRATION` ・`only_phase12_registration`）と同じ様式。
- **触れない test**: P8（`screener_intelligence` の文字の禁止）・P9（`watchlist_thesis_intelligence`）・P11（`personal_ui`）・P12
  （`intelligence.automation`）の guard は変えない。P13 の code はこれらの package 名を **文字としても含まない**。
- **negative test（登録の gate が課す）**: P13 の file が上の集合の外を import すれば失敗 ・P13 の package 以外の新しい importer が
  `personal_intelligence` を含めば失敗 ・`read_p9_private_snapshot` ・`ProfileStore` ・`AttentionStore` ・`AuthorityStores` ・P8 の resolver の
  名前が P13 の code に在れば失敗 ・P13 の module に write の API ・`datetime.now` ・socket ・環境変数の読みが在れば失敗 ・P13 が production の
  runtime closure に入れば失敗。
- 本 gate は上の **どれも実装しない**。registry ・凍結の test ・`src/` は不変。

## 11. 残る判断と先送り（監督）

§14 に集約。

## 12. MVP の外（GATED のまま ・将来の gate）

- **G2** P12 の ledger の消費（run ／ skip ／ 回復の履歴）: P12 の nothing-else-imports の guard の狭い再開と P12-OBS-003 の解消。privacy の risk は低い。
- **G3** P8 の取得の証拠（event ・manifest）: P8 の importer の登録 ＋ `provider_code` ／ `provider_record_ref` の redaction（digest だけ）の規則。
- **G4** P8 の観測 ・訂正の想起: P8 PIT 契約 §18 の利用者の一覧の再開 ＋ `value.amount` を記憶に入れるかの決定（A0 §7 は入れない。
  その場合は存在 ・lineage ・status だけ）。
- **G5** P9 の構造の revision の timeline（id ・seq ・reviewed_at ・change_kind ・status ・corrects。文 ・著者は無い）: A0 の決定 3 が現在
  禁じる richer な interface。監督の決定が要る。
- B-track（取得の自動化）は MVP ・G2 のどれにも要らない。G3 は既存の証拠を読むだけ。**B-track は HOLD のまま**。

## 13. 凍結の保護と closeout

- 不変: Phase 4 〜 11 の runtime ・Phase 12 A-track v1 の 43 file ・公開の面 ・config ・workflow ・Secrets ・凍結の test の importer の一覧。
- 本 gate の変更: 本文書 ・CHANGELOG ・文書の登録（`PHASE12_5_DOCS`）と文書の guard だけ。
- closeout の基準: 監督の承認 ・guard と全 suite が緑 ・`src/` の差分が無い ・private の形が文書に無い。これで P12.5-A2 は閉じるが
  P12.5 全体 ・P13 ・P14 は閉じない。
- **P13 の runtime は存在しない**。本 gate は実装を承認しない。次の実装の gate は P13-A1（純粋な model ・合成の入力）→ P13-A2a
  （§10 の登録 ＋ adapter）の順で、それぞれ監督の GO を要する。

## 14. 残る決定（監督）

1. `ReviewStateSample` ／ `ReviewStateChange` の採用と名前 ・id の接頭辞（A0 の `p13mem_` は `MemoryItem` 用。標本の型に別の接頭辞を
   置くか）。
2. A0 §5.5 の表の表現の明確化（UNKNOWN ／ UNCERTAIN ＝ `KnowledgeTime` の状態、resolver の status は別の語彙）。A0 の本文の変更は承認待ち。
3. P13 が P9 ／ P10 の root の file の byte を hash して build の manifest にするか（P12 と同種の計算。意味は読まないが private root の byte を
   読む）。MVP では無し。
4. export での id の扱い（生の id ・digest の短縮 ・file 名）は P13-A4 の契約で決める。本 gate は承認しない。
5. STALE の窓の値 ・標本の cutoff の列の与え方（人が config で宣言する候補の日 ・時刻。P12 の `scheduled_for` を使うなら G2）。
6. G2 〜 G5 の順序と可否。
