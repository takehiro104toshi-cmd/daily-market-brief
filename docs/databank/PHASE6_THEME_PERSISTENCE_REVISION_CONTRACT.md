# Phase 6 — Theme Persistence ＋ Revision Contract（P6-A3 / Family C）

**状態: FROZEN（P6-A3）。** 本書は Phase 6 Theme 層の **履歴 model（D7）・永続化 authority と writer model（D8）・
点時刻再構成（D17 全体）** を凍結する概念契約である。runtime source・test・package・knowledge・workflow は本 gate で
変更しない。ThemeStore / `src/intelligence/themes/` / discovery / lifecycle / graph / LLM は実装しない。
次の実装 gate が **永続化意味論を再開せずに** model / store / resolver を作れる精度を目標とする。

上流（凍結済み。再開しない）:

- `PHASE6_FOUNDATION_DECISIONS.md`（A0.5。F-1〜F-10、package 境界、evidence authority 境界）
- `PHASE6_THEME_SEMANTICS_AUTHORITY_CONTRACT.md`（A1。定義・Q1〜Q8・class・L0〜L3・governance Option B・不変条件 1〜25）
- `PHASE6_THEME_IDENTITY_EVIDENCE_CONTRACT.md`（A2。二層 identity、observation 内容分類、evidence 参照、二重時点、
  独立性、役割、機構、fingerprint、entity 連結、mapping Option C、revision 境界、不変条件 26〜60）
- 凍結 anchor: `5274c6f1b12b344c469e8ca09dea5d8ec1033f8b`

語彙（enum 値・状態名・reason code）は本書で凍結する。field 名・file 名は「推奨」であり、実装 gate は意味を変えずに
確定してよい。

---

## 1. 前例の監査（本 gate で読み取り確認したもの）

| 前例 | 確認した性質 | Theme への継承 |
|---|---|---|
| **P5 store**（`predictions/prediction_store.py`、`evaluation_store.py`） | 追記専用（open mode `"a"` のみ）、canonical 1 行 → write → flush → fsync、同一 id ＋ byte 一致 ＝ 冪等 no-op、同一 id ＋ 差異 ＝ Conflict（fail closed）、load 時の reason code（INVALID_ENCODING / TRUNCATED_FINAL_LINE / BLANK_LINE / MALFORMED_JSON / NOT_AN_OBJECT / INVALID_RECORD / NON_CANONICAL_LINE / PHYSICAL_DUPLICATE_IDENTICAL / PHYSICAL_DUPLICATE_CONFLICTING / DANGLING_SUPERSESSION / INCOMPATIBLE_SUPERSESSION）、前任は **物理的に先行**必須、append 前の byte 長検査 → `ConcurrentModificationDetected`、`data_root` は明示必須（既定なし）、validate-before-append（自己 round-trip 検証） | **全面継承**（本書の floor） |
| **P5 resolver**（`calibration_contract.resolve_active_evaluation`） | supersession graph のみで解決。DUPLICATE_ID / NO_EVALUATION / SUBJECT_MISMATCH / DANGLING / FORK / MULTIPLE_TERMINALS / CYCLE / RESOLVED。走査順は id sort（決定論のためであり選択には使わない）。created_at・物理順を使わない | **全面継承**（chain resolver の雛形） |
| **Fact / Context / Compass / market store** | canonical JSONL ＋ 再構築可能 SQLite。**破損行は `continue` で黙って読み飛ばす**。revision は新行 ＋ `revision_of`、旧 record は index 上で SUPERSEDED | SQLite ＝ derived の構造のみ継承。破損 skip は **floor 未満**（継承しない） |
| **ArticleIdentity**（`databank/article_store.py`） | event-sourced JSONL ＋ replay。CREATE / ADD_DOCUMENT / MARK_REVISION / MARK_SYNDICATED / SET_PRIMARY / MANUAL_SPLIT / MANUAL_MERGE、actor 必須、`merged_into` state（survivor 方式）。破損行 skip | 「merge / split は明示 event、actor 必須」の精神のみ継承。survivor 方式と破損 skip は継承しない |
| **歴史 Decision store**（phase0 `decision/store.py`。参照のみ） | sequence 連番 ＋ `previous_record_hash → record_hash` の hash chain、validate-before-append、fail closed | 継承しない（§2.3）。A0.5 で port 対象外（D） |
| **legacy theme_learning** | 可変上書き | 前例としない（F-8） |
| **`core.paths.data_root`** | env → config → 既定 `data/vnext`（repository 相対、gitignored） | Theme は **既定を使わない**（P5 と同じく明示必須。§8） |

---

## 2. D7 — 履歴 model

### 2.1 選択肢

| 選択肢 | 評価 |
|---|---|
| A Fact / Context 型（追記 ＋ `revision_of` ＋ derived SQLite state） | revision は表せるが、破損 skip・SQLite の「現在状態」が事実上の authority になっている。governance / metadata の履歴を持たない |
| B ArticleIdentity 型（単一 event stream ＋ replay） | 履歴は完全だが、意味論的 snapshot が存在せず「T 時点の Theme」は replay の副産物になる。evidence 集合を含む状態を event の畳み込みでしか得られず、fork / 曖昧の検出が弱い |
| C P5 型（不変 record ＋ supersedes graph ＋ 曖昧検出） | 意味論的 snapshot と曖昧検出に最適。ただし governance 行為（受理・引退・merge・split）は semantic snapshot ではない |
| D 歴史 Decision 型（hash chain） | 単一 writer・非敵対 threat model では tamper evidence の追加価値が無く、複数 authority file と sequence 連番が両立しない |
| E legacy 可変上書き | 禁止（F-8） |

### 2.2 採用: HYBRID（監督者選好）

- **ThemeObservation chain**（C 型）: 意味論的 snapshot（semantic content ＋ evidence attachment 集合）の不変・内容住所 record。
  root ごとに一本の supersession chain。
- **ThemeGovernanceEvent stream**（追記専用）: semantic observation ではない行為（受理 / 却下 / 引退 / 再開 / merge / split /
  root-breaking successor / 訂正承認 / event 取消）。root ごとの chain。
- **ThemeMetadataRecord**（追記専用）: label / description / taxonomy / alias の履歴（(root, field) ごとの chain）。
- **ThemeRootRecord**（不変・作成事実のみ。§4）と **ThemeSeriesMapping**（A2 §14 Option C の永続化先。§3）。
- **derived 点時刻状態**は canonical record からの純関数（§13）。SQLite は derived のみ（§20）。

### 2.3 なぜ latest-wins / 可変行 / 単一巨大 event stream / hash chain より安全か

- **latest-wins** は「最後に書かれたもの」を意味論に昇格させる。fork・時計ずれ・journal の連結で黙って結果が変わる。
  本 model は predecessor 関係だけで terminal を決め、曖昧を UNRESOLVED として返す（P5 精神）。
- **可変行** は過去の bytes を書き換え、「T 時点で何が信じられていたか」を失う。本 model は訂正も新 record（§15）。
- **単一巨大 event stream** は semantic revision・governance・metadata を 1 本に混ぜ、metadata 変更が semantic revision に
  見える（A2 §16 METADATA_ONLY の分離が崩れる）。関心ごとに authority を分け、各 chain を独立に解決する。
- **hash chain** は不要: observation id は content-addressed で `previous_observation_id` を含むため、**semantic content の
  chain は id 自体が hash-link**である（各 id は前任 id に、前任 id は前任内容に commit する）。governance / metadata
  record も同型。加えて P5 の byte 冪等・physical duplicate 検出・byte 長検査がある。単一 writer・非敵対の threat model
  で、行全体の tamper evidence と sequence 連番を導入する repository 上の根拠は無い。**新 hash chain は導入しない。**

---

## 3. canonical authority

| authority（推奨 file） | record | 1 行の identity | chain |
|---|---|---|---|
| `<data_root>/themes/theme_roots.jsonl` | ThemeRootRecord | `root_id`（生成。`theme_<ULID>`） | なし（不変・単発） |
| `<data_root>/themes/theme_observations.jsonl` | ThemeObservation | `observation_id`（content-addressed `thobs_`） | root ごとに `previous_observation_id` |
| `<data_root>/themes/theme_governance.jsonl` | ThemeGovernanceEvent | `event_id`（content-addressed `thgov_`） | subject root ごとに `previous_event_ids` |
| `<data_root>/themes/theme_metadata.jsonl` | ThemeMetadataRecord | `metadata_id`（content-addressed `thmeta_`） | (root, field) ごとに `previous_metadata_id` |
| `<data_root>/themes/theme_series_mappings.jsonl` | ThemeSeriesMapping | `mapping_id`（content-addressed `thmap_`） | mapping ごとに `supersedes_mapping_id` |

5 つは **別 authority**（別 file・別 record 型）だが、**1 つの store object・1 つの writer** が所有する（§8）。
load 順は固定: roots → observations → governance → metadata → mappings（後の authority は先の authority の id を参照できる。
例外は governance の `result_roots`。§9）。

**root creation は genesis observation で代表させない。** 理由: root id は不透明な生成 id であり、その作成 provenance
（誰が・どの方法で・いつ）は semantic observation の内容ではない。genesis observation に混ぜると (a) A2 の
IDENTITY / SEMANTIC と PROVENANCE の分離が崩れ、(b) observation append 時の「root は存在するか」という参照検査の
対象が無くなり、(c) merge / split の結果 root の由来（origin event）を置く場所が無い。

---

## 4. ThemeRootRecord

| field（推奨） | 内容 |
|---|---|
| `root_id` | 生成 id（A2 §3） |
| `created_at` | 監査時刻（aware UTC。§14） |
| `creation_method` | CANDIDATE（通常作成）/ MERGE_RESULT / SPLIT_RESULT / SUCCESSOR_RESULT |
| `creator_class` | RULE / HUMAN / LLM_PROPOSAL |
| `creation_provenance` | rule id＋version / actor 参照（仮名）/ model・prompt 参照 |
| `origin_event_id` | MERGE_RESULT / SPLIT_RESULT / SUCCESSOR_RESULT のとき必須（宣言 event。§9）。CANDIDATE では空 |
| `genesis_observation_id` | この root の genesis observation の id（**作成時に確定**。§4.1） |
| `schema_version` | `theme_root:<semver>` |

**含めない**: 現在の label / lifecycle / evidence 件数 / class / taxonomy / reviewed 状態 / 最新 observation pointer。
`current_*` 系 field は一切持たない。RootRecord は **作成事実のみ**であり、Theme の状態を表さない。

### 4.1 root と genesis の関係（論理的対）

- 通常作成は 1 つの論理操作 ＝ (1) root id 生成 → (2) genesis observation の semantic content を確定し `observation_id`
  を計算 → (3) RootRecord（`genesis_observation_id` を含む）を append → (4) genesis observation を append。
- RootRecord が genesis id を **先に固定**するため、(a) 1 root に genesis は構築上 1 つ（別 id の「genesis」は
  GENESIS_MISMATCH ＝ INVALID_HISTORY）、(b) (3) と (4) の間で crash しても「root はあるが genesis がまだ無い」という
  状態は **明示の PENDING_GENESIS**（§9）であり、同じ操作の再実行が content id によって冪等に完了する。
- genesis observation の `previous_observation_id` は空。root record が無い observation は INVALID_HISTORY
  （append 時は ROOT_NOT_FOUND で拒否）。
- **orphan の扱い**: root without genesis ＝ NO_STATE（診断 PENDING_GENESIS。valid・未完了）。genesis without root ＝
  INVALID_HISTORY（store 全体が fail closed。writer の順序保証を迂回した証拠）。

---

## 5. ThemeObservation chain

| field（推奨） | 内容 |
|---|---|
| `observation_id` | content-addressed（A2 §4 の IDENTITY / SEMANTIC のみが材料） |
| `root_id` | 既存 root（append 時に検査） |
| `previous_observation_id` | genesis は空。それ以外は **厳密に 1 つ** |
| semantic payload | A2 §4（主題・機構・class・scope・limitations・invalidation conditions・INFERRED entity link・語彙 version） |
| evidence attachment snapshot | A2 §6 の全 field を各 attachment が保持（値の複製なし） |
| provenance | writer class / actor 参照 / `reason` / 関連 `governance_event_id` / `dropped_attachments`（§15） |
| `recorded_at` | 監査時刻（§14） |
| `schema_version`、`mechanism_vocabulary_version` | 明示 |

chain 規則（P5 型 graph safety）:

1. 非 genesis observation の predecessor は **厳密に 1 つ**。
2. predecessor は同じ authority 内に **物理的に先行して存在**しなければならない（前方参照は DANGLING ＝ INVALID_HISTORY）。
3. predecessor は **同じ root** に属すること（WRONG_ROOT_PREDECESSOR ＝ INVALID_HISTORY）。observation revision は
   identity 境界を跨がない（§19）。
4. `recorded_at` は chain に沿って **非減少**（NON_MONOTONIC_RECORDED_AT ＝ INVALID_HISTORY）。これにより「T で子は
   eligible だが親は eligible でない」状態が構造的に存在しない。
5. **fork** ＝ 1 つの predecessor に 2 つ以上の子。writer は fork を生む append を **拒否**する（NON_TERMINAL_PREDECESSOR。
   単一 writer は terminal を知っている）。それでも file 上に fork が存在する場合（writer 迂回・journal 連結）、
   resolver は当該 root を **UNRESOLVED(FORK)** とし、他の root には影響しない。created_at・物理順で解決しない。
6. 「前の状態に戻す」は fork ではなく **revert** ＝ terminal を predecessor とし semantic content が過去の observation と
   等しい新 observation（`previous_observation_id` が異なるため id は別）。
7. cycle は INVALID_HISTORY（content-addressed id と物理先行規則により構築上不可能だが resolver は検査する）。
8. **latest-wins は存在しない。** terminal は predecessor 関係のみで決まる。

---

## 6. canonical bytes に含める内容

| 分類（A2 §4） | canonical 行に含む | content id に含む |
|---|---|---|
| IDENTITY / SEMANTIC（evidence attachment 集合を含む） | **含む** | **含む** |
| PROVENANCE（writer class・actor 参照・reason・governance ref・dropped_attachments） | **含む**（semantic state の解釈に必要。記録しなければ「なぜこの revision か」が失われる） | 含まない |
| AUDIT（`recorded_at`） | **含む** | 含まない |
| DERIVED（identity_core / semantic fingerprint、資格判定、source / temporal diversity、DIRECTLY_EVIDENCED link、DUPLICATE_CANDIDATE、terminal / current 状態、governance / metadata の現在値） | **含まない**（再計算のみ。§20 の index が保持してもよいが authority ではない） | 含まない |

帰結: 同一 semantic content を別の `recorded_at` / provenance で再 append すると **同一 id ＋ 異 bytes ＝ CONFLICT**
（P5 と同じ）。したがって論理操作は append 前に **id で存在確認**し、既存なら完了済みとして扱う（crash 後の再実行は
新しい時計で走っても冪等）。生 append の冪等は byte 一致のみ。

fingerprint は canonical に置かない。A2 §12.3 の「保持値と再計算値の不一致は fail closed」は §20 の derived index に
適用される（index が壊れていれば index を捨てる。canonical には影響しない）。

---

## 7. append の冪等 / conflict / 検証（validate-before-append）

| 状況 | 挙動 | code |
|---|---|---|
| 既知 id ＋ canonical 行 byte 一致 | 冪等 no-op（`ALREADY_PRESENT`、書込みなし） | — |
| 既知 id ＋ bytes 差異 | **CONFLICT**（fail closed。差異 field を報告） | CONFLICT |
| observation の root が roots に無い | 拒否 | ROOT_NOT_FOUND |
| genesis（previous 空）だが id が root の `genesis_observation_id` と異なる | 拒否 | GENESIS_MISMATCH |
| predecessor が未知 | 拒否 | DANGLING_PREDECESSOR |
| predecessor が別 root | 拒否 | WRONG_ROOT_PREDECESSOR |
| predecessor が terminal でない | 拒否 | NON_TERMINAL_PREDECESSOR |
| `recorded_at` が predecessor より前 | 拒否 | NON_MONOTONIC_RECORDED_AT |
| `recorded_at` が root `created_at` より前 | 拒否 | OBSERVATION_BEFORE_ROOT |
| attachment の `attached_at` が root `created_at` より前、または observation `recorded_at` より後 | 拒否 | ATTACHED_AT_OUT_OF_RANGE |
| attachment の `evidence_time > attached_at` | 拒否 | EVIDENCE_AFTER_ATTACHMENT |
| attachment の quality MISSING で role ≠ CONTEXT | 拒否 | MISSING_EVIDENCE_TIME |
| attachment の authority class が NOT_THEME_EVIDENCE / DERIVED_INTERPRETIVE（Phase 6）/ PROPOSAL_ONLY | 拒否 | PROHIBITED_EVIDENCE_CLASS |
| attachment の kind が未知 / 禁止（CONTEXT_ITEM を含む） | 拒否 | PROHIBITED_EVIDENCE_KIND |
| identity core が predecessor と異なる（driver / channel / domain / subject の置換） | 拒否（NEW_ROOT_REQUIRED。§19 の経路へ） | IDENTITY_CORE_CHANGED |
| 同一 root_id の RootRecord 再 append（byte 一致） | 冪等 no-op | — |
| 同一 root_id ＋ bytes 差異 | CONFLICT | CONFLICT |
| record が自身の canonical round-trip を通らない | 拒否 | NON_CANONICAL_RECORD |
| locator に userinfo / credential 様 token、semantic field に drive letter path | 拒否 | PROHIBITED_CONTENT |

load 時: 非 UTF-8、終端改行の無い最終行、空行、非 JSON、非 object、schema 違反、非 canonical、physical duplicate
（同一 / 矛盾）は **STORE_CORRUPTION**（行番号 ＋ reason code）。**黙って読み飛ばさない。自動修復しない。truncate
しない。既存行を書き換えない。**

---

## 8. D8 — store / writer model

- **authority ＝ 追記専用 JSONL**（5 file）。open mode は `"a"` のみ。上書き・truncate・rename・削除・rewrite の経路を
  持たない。1 行 → write → flush → `os.fsync()`（P5）。`newline="\n"`、UTF-8、canonical JSON
  （`sort_keys=True, separators=(",",":"), ensure_ascii=False`）。
- **`data_root` は明示必須**（constructor 引数。空 / 未指定は ValueError）。`core.paths.data_root` の既定
  （repository 相対 `data/vnext`）へ **fallback しない**。repository 配下の path を既定にしない。test は `tmp_path`。
- **live Theme JSONL を git に track しない**。自動 commit しない。`data/theme_learning`（tracked・legacy）は使用禁止。
- **SINGLE_WRITER**: 1 process・1 store object が 5 authority すべてを所有する。複数 process・複数 writer・分散 lock・
  並行 append・cross-file transaction の安全性は **保証しない**（主張もしない）。
- **改変検知**: file ごとに load / 最終 append 時の byte 長を記憶し、append 前に比較。差異 → `ConcurrentModificationDetected`
  （fail closed。自動 reload ＋ retry しない）。置換・truncate・外部追記を実務上検知する。
- fsync / lock の細部は非意味論の実装判断。lock を導入しても「単一 writer」以上を主張しない。
- 5 authority の writer は **独立 writer ではなく 1 writer**。理由: §9 の append 順序を 1 つの code path が保証するため。

---

## 9. cross-file の原子性

選択: **2（append 順序 ＋ fail closed する明示の未完了状態）**。atomic transaction 機構も、authority としての SQLite も
導入しない。derived SQLite は canonical を修復しない。設計原則: **「宣言が先、完了が後。宣言は完了の id を固定する。
未完了は明示状態であり、意図不明の orphan を作らない。」**

| 論理操作 | append 順序 | 途中 crash の状態 | 回復 |
|---|---|---|---|
| 通常 root 作成 | RootRecord（genesis id 固定）→ genesis observation | root のみ ＝ **PENDING_GENESIS**（NO_STATE、valid） | 同じ操作を再実行。observation id が一致するもののみ完了できる（冪等） |
| 同一 root の revision | observation 1 行 | なし（単一行） | — |
| governance（単一 root、result root 無し） | event 1 行 | なし | — |
| MERGE / SPLIT / SUCCESSOR | governance event（`result_roots` の id と evidence 配分を宣言）→ 結果 RootRecord（`origin_event_id`）→ 結果 genesis observation | event のみ／一部 root のみ ＝ **PENDING_EVENT**（subject root の状態は event 前のまま真。結果 root は存在すれば semantic 解決可、governance 上は PENDING_ORIGIN） | 同じ操作を再実行。event が id を固定しているため冪等 |
| metadata 変更 | metadata 1 行 | なし | — |
| mapping 変更 | mapping 1 行 | なし | — |

- 参照検査: observation → root、governance → subject roots / related observations / previous events、metadata → root、
  mapping → root / observation は **既存**でなければならない（append 時に拒否、load 時に INVALID_HISTORY）。
  **唯一の前方参照**は governance event の `result_roots`（宣言）であり、これは PENDING として明示的に扱う。
- PENDING は時間で自動解消・自動 rollback しない。人間 / 再実行が完了させるか、明示の EVENT_REVERSED で取り消す。

---

## 10. governance event stream

| field（推奨） | 内容 | id に含む |
|---|---|---|
| `event_id` | content-addressed | — |
| `event_type` | §10.1 | 含む |
| `subject_roots` | 対象 root（既存必須） | 含む |
| `result_roots` | MERGE / SPLIT / SUCCESSOR の結果 root id（宣言。§9） | 含む |
| `related_observations` | 承認対象の observation id 等（既存必須） | 含む |
| `previous_event_ids` | subject root ごとの直前 terminal event（root に event が無ければ空） | 含む |
| `reverses_event_id` | EVENT_REVERSED のとき必須 | 含む |
| `evidence_allocation` | MERGE / SPLIT / SUCCESSOR の attachment 配分（(source observation, attachment key) → result root） | 含む |
| `reason` | 必須（HUMAN では非空） | 含む |
| `actor_class` / `actor_ref` | RULE / HUMAN / LLM_PROPOSAL ＋ 参照 | actor_class のみ含む |
| `recorded_at` | 監査時刻 | 含まない |
| `schema_version`、`governance_vocabulary_version` | 明示 | 含む |

### 10.1 event 種別（Phase 6 最小集合。lifecycle の状態名は P6-C が所有し、追加は語彙 version で行う）

CANDIDATE_ACCEPTED（L1 → L2）／CANDIDATE_REJECTED／RETIRED／REOPENED／MERGE／SPLIT／SUPERSEDED_BY_ROOT（§19）／
ROLE_CORRECTION_APPROVED／CERTAINTY_CHANGE_APPROVED／METADATA_CORRECTION_APPROVED／EVENT_REVERSED。

- 通常の root 作成は governance event を持たない（RootRecord が A2 §16 #23 の永続化先）。
- governance event は observation を削除・改変しない。semantic 変更を伴う承認（ROLE_CORRECTION / CERTAINTY_CHANGE）は
  対応する新 observation を `related_observations` で指す（observation 側は `governance_event_id` で指し返す。
  順序: observation → event）。
- HUMAN の actor は仮名 / 役割 id。個人識別情報・理由の自由記述以外の機微を持たない。
- 歴史 Decision subsystem は再利用しない（原則のみ: auto approval なし、reason 必須、撤回は履歴、削除なし）。

---

## 11. governance 状態の解決

- root ごとに **event chain** を成す: root に関する最初の event は `previous_event_ids[root]` が空、以後は直前 terminal
  を指す。MERGE / SPLIT のように複数 subject root を持つ event は各 subject root の terminal を指し、各 root の chain は
  その event に合流する。結果 root の chain は宣言 event を起点とする（RootRecord の `origin_event_id`）。
- writer は terminal でない event を predecessor とする append を拒否する（NON_TERMINAL_PREDECESSOR）。
- resolver（T 固定）: `recorded_at <= T` の event を集め、root ごとに chain を解決。唯一の terminal → その event_type
  が governance 状態を決める（状態名の意味づけは P6-C）。EVENT_REVERSED が terminal なら、取り消された event の直前の
  状態が有効（取消の連鎖は chain を辿って計算する）。
- **競合する terminal が明示関係なしに複数** → UNRESOLVED(GOVERNANCE_FORK / GOVERNANCE_MULTIPLE_TERMINALS)。
  「最後の物理行」「最新 created_at」で選ばない。意図を推測しない。
- event が無い root は NO_GOVERNANCE（valid: 未 review の候補）。PENDING_EVENT は governance 状態に PENDING flag を付ける
  （subject root の有効状態は event 前のまま）。

---

## 12. metadata 履歴

採用: **A — 追記専用 ThemeMetadataRecord**（可変 lookup table D は禁止）。

| field（推奨） | 内容 | id に含む |
|---|---|---|
| `metadata_id` | content-addressed | — |
| `root_id` | 既存必須 | 含む |
| `field` | LABEL / DESCRIPTION / TAXONOMY / ALIAS（語彙 version 付き） | 含む |
| `value` | 単一値 field は文字列、集合 field（TAXONOMY / ALIAS）は **その field の全集合 snapshot**（差分ではない） | 含む |
| `previous_metadata_id` | 同じ (root, field) の直前 terminal（初回は空） | 含む |
| `provenance_class` / `provenance_ref` / `reason` | RULE / HUMAN / LLM_PROPOSAL | class のみ含む |
| `governance_event_id` | reviewed Theme の訂正承認（任意） | 含む |
| `recorded_at` | 監査時刻 | 含まない |

- metadata 変更は **semantic observation を生まない**（observation id・fingerprint・identity core は不変）。
- 点時刻: `recorded_at <= T` の record を (root, field) ごとに chain 解決。唯一の terminal → 値。record なし →
  NO_METADATA（valid）。複数 terminal / fork → その field のみ UNRESOLVED（他の field・semantic 状態・governance は影響
  を受けない）。
- writer は非 terminal predecessor を拒否する。LLM_PROPOSAL の label は provisional（表示は実装層の判断、authority ではない）。

---

## 13. D17 — 点時刻再構成（純関数）

入力: `root_id`、cutoff `T`（aware UTC）、5 authority の parse 済み record（bytes から決定論的に得る）。
出力: `ReconstructedThemeState` ＋ facet ごとの status。**全体 status ＝ semantic facet の status**。governance / metadata /
mapping は独立の status を持ち、潰さない。

| status | 意味 |
|---|---|
| **RESOLVED** | 唯一の terminal observation が T で決まる |
| **NO_STATE** | root が未知、root が T 以後に作成、genesis が T 以後（PENDING_GENESIS を含む） |
| **UNRESOLVED** | record は個々に valid だが chain が曖昧（FORK / MULTIPLE_TERMINALS） |
| **INVALID_HISTORY** | 構造不変条件の違反（§23）。store は load 時に fail closed するため通常ここには到達しないが resolver も検査する |
| **STORE_CORRUPTION** | bytes / 行が読めない（load 段階） |

算法:

1. **root**: RootRecord が無い → NO_STATE(UNKNOWN_ROOT)。`created_at > T` → NO_STATE(ROOT_AFTER_CUTOFF)。
2. **eligible observations** E ＝ 当該 root の observation で `recorded_at <= T`。E が空 → NO_STATE(GENESIS_PENDING または
   NOT_YET_OBSERVED)。
3. **chain 解決（E 内のみ）**: genesis が E に無く他があれば INVALID_HISTORY（§5 規則 4 により起こりえない）。各 non-genesis
   の predecessor が E に無ければ INVALID_HISTORY(DANGLING)。1 predecessor に 2 子 → UNRESOLVED(FORK)。terminal が 2 つ以上
   → UNRESOLVED(MULTIPLE_TERMINALS)。cycle → INVALID_HISTORY。唯一の terminal ＝ O_T。
4. **evidence view**: O_T の attachment のうち **`evidence_time <= T` かつ `attached_at <= T`** のものだけを含める。
   quality MISSING（evidence_time 無し）の CONTEXT attachment は view に含めず `context_without_time` として別報告。
   除外件数と理由を診断に載せる（§5 規則 4 と §7 により構造上は全件該当するが、resolver は独立に検査する）。
5. **governance**: §11 を T で独立に解決（RESOLVED / NO_GOVERNANCE / UNRESOLVED / PENDING flag）。
6. **metadata**: §12 を (root, field) ごとに T で独立に解決。
7. **mapping**: mapping record で `recorded_at <= T`、`supersedes_mapping_id` chain の terminal 集合。曖昧は mapping facet
   のみ UNRESOLVED。
8. **T 以後の record は一切影響しない**: T 以後に append された fork・merge・split・metadata・mapping は T の結果を変えない
   （不変条件 84）。
9. **derived 値**（fingerprint、資格判定、diversity、DIRECTLY_EVIDENCED link、DUPLICATE_CANDIDATE、上流 dereference 状態）は
   出力に **再計算して**付ける。canonical から読まない。

規則: 走査順は id sort（決定論のため。選択には使わない）。現在時刻を呼ばない。network・Compass・Brief・P5・LLM・
可変 legacy config を参照しない。「T より前に知られていた evidence を T より後の observation が含む」場合、その evidence は
T に **現れない**（知識の存在 ≠ Theme system への付与）。

---

## 14. recorded_at の意味論

| 時刻 | 所在 | 意味 |
|---|---|---|
| root `created_at` | RootRecord | root 作成の監査時刻 |
| observation `recorded_at` | ThemeObservation | observation 記録の監査時刻 |
| evidence `attached_at` | attachment（A2） | 付与決定の時刻（provenance）。`root.created_at <= attached_at <= observation.recorded_at` |
| evidence `evidence_time` | attachment（A2） | evidence 自身の時点（semantic）。監査時刻ではない |
| governance `recorded_at` | ThemeGovernanceEvent | event 記録の監査時刻 |
| metadata `recorded_at` | ThemeMetadataRecord | 同上 |
| mapping `recorded_at` | ThemeSeriesMapping | 同上 |

- すべての監査時刻は **aware UTC**（`core.time.ensure_aware` / `to_utc_iso`）。naive は拒否。
- 監査時刻に event の意味論的日付（session 日・公表日）を入れない。
- 純再構成は現在時刻を呼ばない。runtime 作成は **時計を注入**する（test は固定時計）。
- 各 chain に沿って非減少（§5 規則 4、governance / metadata / mapping も同じ）。file 全体の時刻単調性は要求しない
  （resolver は file 順を使わない）。

---

## 15. revision と correction

| 用語 | 定義 |
|---|---|
| **REVISION** | 同一 root の新 semantic observation（terminal を predecessor とする） |
| **CORRECTION** | 「以前の解釈 / metadata / 役割付与が誤っていた」ことを説明する **新しい不変 record / event**。旧 bytes は不変。T より前の cutoff は誤りを含む当時の状態を返し続ける |

| 訂正例 | 永続化 |
|---|---|
| evidence 役割 SUPPORTS → CONTRADICTS | 新 ThemeObservation（当該 attachment を置換。旧 role は前 observation に残る）＋ reviewed なら ROLE_CORRECTION_APPROVED |
| 誤った entity link（INFERRED） | 新 ThemeObservation。subject entity なら §19 |
| label の typo | 新 ThemeMetadataRecord（reviewed なら METADATA_CORRECTION_APPROVED を伴ってよい） |
| 誤った taxonomy | 新 ThemeMetadataRecord（集合 snapshot） |
| 機構確度 class の訂正 | 新 ThemeObservation ＋ reviewed なら CERTAINTY_CHANGE_APPROVED |
| 後で無効と判明した evidence ref | 新 ThemeObservation が attachment を除く。provenance `dropped_attachments`（ref_id ＋ 理由）に記録。旧 observation は参照を保持 |
| 誤って記録された governance event | EVENT_REVERSED（reverses_event_id ＋ reason） |
| 誤った mapping | 新 ThemeSeriesMapping（`supersedes_mapping_id`） |

A2 §16 の分類と永続化先: METADATA_ONLY → ThemeMetadataRecord（#21 mapping は ThemeSeriesMapping）；
SAME_ROOT_NEW_OBSERVATION → ThemeObservation（reviewed の承認は governance event を併記）；NEW_ROOT_REQUIRED →
SUPERSEDED_BY_ROOT event ＋ 結果 RootRecord ＋ genesis（§19）；GOVERNANCE_EVENT → governance stream（#23 root 作成は
RootRecord）。**A2 の全分類に永続化先がある。**

---

## 16. 上流 evidence の改訂・撤回

上流 evidence item（Fact / Observation / SourceDocument / NewsItem / Statement）が後に revise・supersede・UNUSABLE 化・
撤回・重複 / 転載判明した場合:

- 歴史 ThemeObservation は **当時の revision 固有 `ref_id` を参照し続ける**。書き換えない。
- 役割を新 revision へ **自動で移さない**。新 ThemeObservation が明示的に新 `ref_id` を付与する（`revision_of_at_attachment`
  に旧 id、新 `attached_at`）。旧 attachment は残してもよいし `dropped_attachments` で除いてもよい。
- derived resolver は上流 store を **参照できる場合に限り**警告を付ける: UPSTREAM_SUPERSEDED / UPSTREAM_UNUSABLE /
  UPSTREAM_DUPLICATE_ORIGIN / UPSTREAM_NOT_FOUND。参照できない場合は `dereference = NOT_ATTEMPTED / UNAVAILABLE` として
  **再構成結果と分けて**報告する。再構成自体は attachment snapshot（A2 §6 の必須 field）だけで完結する。
- 上流の変化を理由に Theme 履歴を書き換えることはない。

---

## 17. merge

採用: **B — 新しい merged root を作る**（監督者選好。ArticleIdentity の survivor 方式 `merged_into` は「片方の lineage が
他方を吸収した」ように見え、両 source の対称な履歴を保てないため採らない）。

| 要件 | 実現 |
|---|---|
| 旧 root は addressable | RootRecord・observation chain はそのまま。governance chain の terminal が MERGE |
| 旧 observation を書き換えない | 追記のみ |
| 新 canonical root identity は明示 | MERGE event の `result_roots` ＝ 新 root 1 つ。RootRecord `creation_method = MERGE_RESULT`、`origin_event_id` |
| evidence provenance を消さない | 新 genesis の attachment は `carried_from`（source observation id）・元 `attached_at`・元 role provenance を保持 |
| evidence を自動複製しない | MERGE event の `evidence_allocation` に **明示列挙**した attachment のみ carry。genesis の attachment 集合は配分の部分集合でなければ拒否 |
| merge 前の T は merge 前の root を返す | event / 新 root / 新 genesis はすべて `recorded_at > T` |
| merge 後は関係を露出 | source root の governance ＝ MERGE（result root 付き）。新 root の governance chain 起点 ＝ MERGE event |
| fingerprint 一致で自動 merge しない | MERGE は HUMAN actor の event のみ（RULE / LLM_PROPOSAL は提案 record を作れるが MERGE event を書けない） |

新 root の semantic content（主題・機構・class・scope…）は merge 判断者が宣言する（自動合成しない）。順序と crash 回復は §9。

---

## 18. split

| 要件 | 実現 |
|---|---|
| 元 root は歴史として残る | 削除なし。governance terminal が SPLIT |
| 子 root は明示 | SPLIT event の `result_roots`（≥ 2）。RootRecord `creation_method = SPLIT_RESULT` |
| split event が source と children を結ぶ | `subject_roots = [source]`、`result_roots = children` |
| evidence 配分は明示 | `evidence_allocation` が attachment ごとに宛先 child を列挙。**同じ attachment を複数 child に配る場合も child ごとに明示列挙**（黙った複製なし） |
| split 前の T は元 root を返す | 同上 |
| split 後は関係を露出 | 元 root の governance ＝ SPLIT（children 付き）。各 child の governance 起点 ＝ SPLIT event |
| 元 root の非活性化は明示 governance のみ | SPLIT event 自体が terminal。lifecycle 名は P6-C |

---

## 19. root-breaking な機構変更（successor 関係）

A2 §2.3 / §16 のとおり driver / channel / subject / domain の置換は NEW_ROOT_REQUIRED。旧 root と新 root の関係:

| 関係 | 永続化 | 区別 |
|---|---|---|
| 独立した新 Theme | RootRecord（CANDIDATE）のみ | governance 関係なし |
| **semantic break による successor** | `SUPERSEDED_BY_ROOT` event（`subject_roots=[old]`、`result_roots=[new]`、reason）→ RootRecord（`SUCCESSOR_RESULT`、`origin_event_id`）→ genesis | 旧 root の governance terminal ＝ SUPERSEDED_BY_ROOT |
| split | SPLIT event | result ≥ 2 |
| merge | MERGE event | subject ≥ 2 |

- observation revision で identity 境界を跨ぐことは append で拒否される（IDENTITY_CORE_CHANGED / WRONG_ROOT_PREDECESSOR）。
- successor への evidence carry は `evidence_allocation` で明示（帰結が変わるため役割は再評価対象。carry した attachment は
  `carried_from` を保持）。
- successor 関係は lineage の **注釈**であり、旧 root の semantic 状態を変えない。

---

## 20. derived SQLite index

**認可: YES。ただし再構築専用。** 本 gate では実装しない。

| 責務（候補） |
|---|
| root lookup、creation_method / origin_event による検索 |
| observation の predecessor / child graph、root ごとの terminal 候補 |
| T 指定の eligible record 抽出（recorded_at / attached_at / evidence_time の索引） |
| evidence 逆引き（ref_id / source origin → root / observation） |
| metadata・governance・mapping の lookup |
| fingerprint（identity core / semantic）による DUPLICATE_CANDIDATE lookup |

規則: JSONL が唯一の authority；SQLite は canonical を **決して修復しない**；削除・再構築自由；index の状態が意味論を
決めない（resolver は parse 済み JSONL だけで完結し、index は加速のみ）；index は build 時の各 JSONL の byte 長 / hash を
記録し、不一致なら **stale として捨てる**（canonical を疑わない）；index 内の保持 fingerprint と再計算の不一致は index の
不良として index を捨てる。

---

## 21. rebuild / replay の決定論

同一の canonical bytes（5 file）から、**root graph・observation graph・governance graph・metadata 履歴・mapping 履歴・
derived fingerprint・任意の (root, T) の再構成結果**が byte 単位で同一に得られること。

rebuild が要求してはならないもの: network、現在時刻、Compass、MorningBrief、MarketSignal、P5 journal、LLM、可変 legacy
config、derived SQLite、上流 evidence 本体。

上流 evidence 本体が無い場合でも、A2 §6 の attachment snapshot（kind / class / ref_id / origin / evidence_time ＋ basis ＋
quality / attached_at / role / provenance / QA snapshot）から Theme 履歴は完全に再構成できる。dereference の可否は
§16 の別 status として報告する（再構成 status と混ぜない）。

---

## 22. schema versioning

- 5 record 型はそれぞれ明示の `schema_version`（例 `theme_root:0.1.0`、`theme_observation:0.1.0`、`theme_governance:0.1.0`、
  `theme_metadata:0.1.0`、`theme_series_mapping:0.1.0`）を持つ。語彙 version（`mechanism_vocabulary_version`、
  `governance_vocabulary_version`、`metadata_field_vocabulary_version`）は別 field。
- 未知 / 未対応の schema_version は load 時に **UNSUPPORTED_SCHEMA_VERSION**（STORE_CORRUPTION 区分。読めない）。
- **歴史 canonical record の黙った migration は禁止。** migration が必要になれば、新 version の record / artifact を別に
  作るか、別途認可された migration gate で行う。in-place 書換えは経路として存在しない。本 gate では実装しない。

---

## 23. 失敗状態（4 区分。1 つの error に潰さない）

| 区分 | 意味 | 影響範囲 |
|---|---|---|
| **STORE_CORRUPTION** | bytes / 行が読めない・非 canonical・physical duplicate・未対応 version | store 全体 load 失敗（fail closed） |
| **INVALID_HISTORY** | parse はできるが構造不変条件に違反 | store 全体 load 失敗（writer の保証が破れた証拠） |
| **UNRESOLVED_VALID_HISTORY** | record は valid だが chain が曖昧 | 当該 root（または facet）のみ UNRESOLVED |
| **NO_STATE** | 該当時点に状態が無い（valid） | 当該 root のみ |

| ケース | 区分 | code |
|---|---|---|
| 非 UTF-8 / 終端改行なし / 空行 / 非 JSON / 非 object | STORE_CORRUPTION | INVALID_ENCODING / TRUNCATED_FINAL_LINE / BLANK_LINE / MALFORMED_JSON / NOT_AN_OBJECT |
| schema 違反 / 非 canonical 行 | STORE_CORRUPTION | INVALID_RECORD / NON_CANONICAL_LINE |
| 未知 schema version | STORE_CORRUPTION | UNSUPPORTED_SCHEMA_VERSION |
| 同一 id の物理重複（同一 / 矛盾） | STORE_CORRUPTION | PHYSICAL_DUPLICATE_IDENTICAL / PHYSICAL_DUPLICATE_CONFLICTING |
| 同一 id ＋ 異 bytes の append | （append 拒否） | CONFLICT |
| predecessor 不在 / 前方参照 | INVALID_HISTORY | DANGLING_PREDECESSOR |
| predecessor が別 root | INVALID_HISTORY | WRONG_ROOT_PREDECESSOR |
| genesis id が root の宣言と不一致 / 2 つ目の genesis | INVALID_HISTORY | GENESIS_MISMATCH |
| cycle | INVALID_HISTORY | CYCLE |
| root record 不在の observation | INVALID_HISTORY | ROOT_NOT_FOUND |
| observation が root 作成より前 / chain 内で時刻逆行 | INVALID_HISTORY | OBSERVATION_BEFORE_ROOT / NON_MONOTONIC_RECORDED_AT |
| attached_at が root 作成前・observation 記録後 | INVALID_HISTORY | ATTACHED_AT_OUT_OF_RANGE |
| evidence_time > attached_at | INVALID_HISTORY | EVIDENCE_AFTER_ATTACHMENT |
| governance の subject / related / previous 参照不在 | INVALID_HISTORY | GOVERNANCE_REFERENCE_MISSING |
| merge / split の形式不良（subject 数・result 数・配分の宛先不在・配分外 attachment を持つ genesis） | INVALID_HISTORY | MALFORMED_MERGE / MALFORMED_SPLIT / ALLOCATION_VIOLATION |
| metadata predecessor 不在 / 別 root / 別 field | INVALID_HISTORY | METADATA_PREDECESSOR_MISSING |
| 禁止 evidence class / kind、MISSING 時点の非 CONTEXT | INVALID_HISTORY | PROHIBITED_EVIDENCE_CLASS / PROHIBITED_EVIDENCE_KIND / MISSING_EVIDENCE_TIME |
| identity core が chain 内で変化 | INVALID_HISTORY | IDENTITY_CORE_CHANGED |
| observation fork / 複数 terminal | UNRESOLVED_VALID_HISTORY | FORK / MULTIPLE_TERMINALS |
| governance の競合 terminal | UNRESOLVED_VALID_HISTORY | GOVERNANCE_FORK / GOVERNANCE_MULTIPLE_TERMINALS |
| metadata の曖昧 terminal | UNRESOLVED_VALID_HISTORY | METADATA_FORK / METADATA_MULTIPLE_TERMINALS（当該 field のみ） |
| mapping の曖昧 terminal | UNRESOLVED_VALID_HISTORY | MAPPING_FORK（mapping facet のみ） |
| 未知 root / T が root 作成前 / genesis 未記録 | NO_STATE | UNKNOWN_ROOT / ROOT_AFTER_CUTOFF / GENESIS_PENDING |
| result root 未完了の governance event | （valid、flag） | PENDING_EVENT / PENDING_ORIGIN |
| append 前の byte 長不一致 | （append 拒否） | CONCURRENT_MODIFICATION |

---

## 24. 単一 writer / 並行性

- **MVP の保証は SINGLE_WRITER のみ。** 複数 process 安全性・分散 lock・並行 append・transactional cross-file write は
  主張しない。
- 改変検知（byte 長）で検出できた場合は fail closed（§8）。検出できない競合は保証外であり、そのことを文書化する。
- 複数 writer 対応は別 gate（認可されるまで設計しない）。

---

## 25. repository / security 境界

- canonical Theme journal は明示 `data_root` 配下 `themes/` に置く。repository 相対の既定・fallback を持たない。
- 自動 commit なし。live Theme JSONL・SQLite を track しない（`data/vnext/` は gitignored。`data/theme_learning` は使用しない）。
- credential を含む URL・userinfo 付き locator は append で拒否（PROHIBITED_CONTENT）。
- Compass corpus（CONFIDENTIAL_SOURCE）は evidence kind に存在しない（A2 §5 NOT_THEME_EVIDENCE）ため構造的に Theme
  record へ入らない。excerpt は権利上安全な短い抜粋のみ（A2 §6）。
- evidence 参照は canonical id（fact_id / observation_id / source_document_id / news_item_id / statement_id）で行い、
  private raw content を複製しない。
- Windows / 機械固有 path を semantic field・locator に入れない（PROHIBITED_CONTENT）。
- H0 security remediation は本書の範囲外（別管理のまま）。

---

## 26. 永続化不変条件（A1 / A2 の 1〜60 に続く番号）

61. canonical 履歴（5 authority）は追記専用であり、上書き・truncate・rename・削除・rewrite の経路を持たない。
62. 記録済み observation の bytes は変化しない。
63. metadata 変更は semantic observation revision を生まない。
64. semantic revision は predecessor を上書きせず、新 observation として追加される。
65. 点時刻状態は cutoff 以後の record を一切用いない。
66. T より前に知られていたが T より後に付与された evidence は T の状態に現れない。
67. T より前に付与されたが evidence_time が T より後の evidence は T の状態に現れない。
68. fork は file 順で解決されない。
69. fork は timestamp だけで解決されない。
70. 破損行は黙って読み飛ばされず、行番号と reason code を伴って fail closed する。
71. 同一 id ＋ 異 bytes は fail closed（append は CONFLICT、load は PHYSICAL_DUPLICATE_CONFLICTING）。
72. merge は旧 root・旧 observation・旧 governance 履歴を保持する。
73. split は元 root を保持する。
74. 上流 evidence の改訂・撤回は Theme 履歴を書き換えない。
75. correction は新しい履歴（observation / metadata / event）を作る。
76. SQLite は derived のみであり、canonical を修復せず、削除・再構築できる。
77. rebuild は network・現在時刻・Compass・Brief・P5・LLM・可変 legacy config を必要としない。
78. canonical data は repository の外（明示 data_root）にあり、既定 fallback を持たない。
79. MVP の writer 保証は SINGLE_WRITER のみである。
80. governance の曖昧は UNRESOLVED として明示され、推測で解決されない。
81. metadata の曖昧は当該 field の UNRESOLVED として明示される。
82. latest-wins resolver は存在しない（observation / governance / metadata / mapping のいずれにも）。
83. root-breaking な semantic 変更は別 root を作り、observation revision で表現されない。
84. T 以後の merge / split / successor / 訂正は T の再構成結果を変えない。
85. index の削除・再構築は canonical の結果を変えない。
86. 1 root に genesis observation は厳密に 1 つであり、RootRecord がその id を作成時に固定する。
87. observation・governance・metadata・mapping の各 chain に沿って recorded_at は非減少である。
88. attachment の attached_at は root created_at 以上、当該 attachment を初めて含む observation の recorded_at 以下である。
89. observation の predecessor は同じ root・同じ authority 内に物理的に先行して存在する。
90. governance event は observation を削除・改変せず、semantic 変更を伴う承認は対応する新 observation を指す。
91. 結果 root（merge / split / successor）は宣言 event を origin として持ち、宣言なしに存在しない。
92. 未完了の論理操作（PENDING_GENESIS / PENDING_EVENT）は明示状態であり、自動 rollback・自動補完・時間経過による解消は無い。
93. 再構成は純関数であり、同一 bytes・同一 (root, T) に対し同一の出力を返す。
94. RootRecord は current_* field を持たず、Theme の現在状態を表さない。
95. DERIVED 値は canonical 行に含まれず、再計算のみで得られる。
96. 歴史 canonical record の in-place migration は経路として存在しない。
97. STORE_CORRUPTION / INVALID_HISTORY / UNRESOLVED_VALID_HISTORY / NO_STATE は区別され、1 つの error に潰されない。

---

## 27. A3 → 実装境界（推奨順序）

監査上の複雑さ（5 authority・4 chain・cross-file 順序・多 facet resolver）から、単一 gate ではなく **4 分割**を推奨する。

| gate | 実装してよいもの | してはならないもの |
|---|---|---|
| **P6-A4a Theme model** | 5 record 型（frozen dataclass）、canonical 直列化 / 逆直列化、content id、A2 の attachment 検証、identity core / semantic fingerprint（純関数）、schema / 語彙 version 定数、`src/intelligence/themes/` の作成（model module のみ。Foundation §7 の import 制限） | store・resolver・discovery・lifecycle・graph・LLM・Compass / Reports / P5 参照 |
| **P6-A4b Theme canonical store** | 5 authority の append / load、§7 の検証、CONFLICT / corruption / INVALID_HISTORY 区分、byte 長検査、§9 の論理操作（作成 / revision / governance / metadata / mapping / merge / split / successor）の順序と PENDING 状態 | derived SQLite、resolver、lifecycle 名 |
| **P6-A4c point-in-time resolver** | §13 の純関数、facet 別 status、診断、上流 dereference（任意・分離）、DUPLICATE_CANDIDATE の derived 提示 | 自動 merge、lifecycle 遷移、Brief 出力 |
| **P6-A4d E2E** | fork / merge / split / successor / correction / 遅延付与 / 上流改訂 / crash 途中状態 / journal 連結 を含む world、replay 決定論、不変条件 1〜97 の test 対応表、production bundle guard の再確認 | production 経路への接続 |

derived SQLite index は A4d の後（resolver が JSONL だけで証明されてから）。lifecycle（P6-C）・discovery / dedup /
graph（P6-B）はその後。

---

## 28. 残件（Family B / C / D）

- **C（本書で解決）**: D7、D8、D17 全体。残るのは実装 gate の field 名確定のみ。
- **B（A2 で解決済み）**: 追加なし。Statement producer・entity catalog・Fact.known_at quality は上流の提案事項。
- **D（P6-B 以降）**: D10 graph、D11 lifecycle 状態名（governance 語彙 version の追加として）、D12 discovery、D13 dedup
  heuristics、D14 粒度、D18 Brief 消費、D21 legacy、D22 Phase 7 契約、taxonomy 採否、機構語彙の初期集合、複数 writer。

## 29. 次 gate

**P6-A4a Theme model**（§27）。本書と A1 / A2 が入力である。

---

## 30. 実装状態（P6-A4a。契約の意味論は変更していない）

P6-A4a で **純 model 層のみ**を実装した（store / JSONL IO / resolver / SQLite / discovery / lifecycle / graph / LLM は未実装）。

| 項目 | 実装 |
|---|---|
| package | `src/intelligence/themes/`（`__init__.py` / `model.py` / `fingerprint.py` / `qualification.py` / `revision.py`）。import は `core.ids` / `core.time` のみ（closure 9 module）。production bundle の EXCLUDED_PACKAGES に含まれる |
| schema version | `theme_root:0.1.0` / `theme_observation:0.1.0` / `theme_governance:0.1.0` / `theme_metadata:0.1.0` / `theme_series_mapping:0.1.0`。語彙 version: `mechanism_vocabulary:0.1.0` / `governance_vocabulary:0.1.0` / `metadata_field_vocabulary:0.1.0` |
| id prefix | root `theme_<ULID>`（生成。`new_root_id` のみが生成 primitive）／`thobs_` / `thgov_` / `thmeta_` / `thmap_` ＝ `core.ids.content_id(prefix, canonical_json(identity_payload))`（sha256 先頭 24 hex）／行 digest `thdigest_`（root_id とは別） |
| observation_id の材料 | `schema_version, mechanism_vocabulary_version, root_id, previous_observation_id, subject, mechanism, certainty_class, scope, limitations, invalidation_conditions, inferred_links, attachments`（A2 §4 IDENTITY / SEMANTIC。provenance / recorded_at / DERIVED を含まない） |
| event_id の材料 | `schema_version, governance_vocabulary_version, event_type, subject_roots, result_roots, related_observations, previous_event_ids, reverses_event_id, evidence_allocation, reason, actor_class`（actor_ref / recorded_at を含まない） |
| metadata_id の材料 | `schema_version, metadata_field_vocabulary_version, root_id, field, value, previous_metadata_id, provenance_class, governance_event_id` |
| mapping_id の材料 | `schema_version, root_id, consequence_ref, series_ref, mapping_role, expected_relation, valid_from, supersedes_mapping_id, provenance_class` |
| canonical 直列化 | P5 と同じ `json.dumps(sort_keys=True, separators=(",",":"), ensure_ascii=False)`、datetime は UTC ISO、Enum は value、集合的 field は構築時に canonical sort（順序独立を test で証明）。`canonical_line(record)` ＝ 行 ＋ `\n` |
| fingerprint | `fingerprint.identity_core_fingerprint`（`thcore_`）/ `semantic_fingerprint`（`thsem_`）。record に保存しない（DERIVED） |
| 資格判定 | `qualification.evaluate_qualification`（QUALIFIES_SEMANTICALLY / THEME_CANDIDATE_POSSIBLE / DOES_NOT_QUALIFY ＋ 診断。score なし）、`source_origin_groups` / `independent_origin_count` / `evidence_date_set` / `has_source_diversity` / `has_temporal_diversity` / `directly_evidenced_links` |
| revision helper | `revision.revise_observation` / `attach_evidence`（同一 root、identity core 不変を検査、時計注入、永続化なし） |
| model 検証 code（A3 §7 / §23 と整合） | NAIVE_DATETIME / INVALID_ROOT_ID / INVALID_RECORD_ID / INVALID_VOCABULARY / UNSUPPORTED_SCHEMA_VERSION / EVIDENCE_AFTER_ATTACHMENT / MISSING_EVIDENCE_TIME / PROHIBITED_EVIDENCE_CLASS / PROHIBITED_EVIDENCE_KIND / REF_ID_KIND_MISMATCH / INVALID_MECHANISM / MISSING_OBSERVABLE_CONSEQUENCE / MISSING_INVALIDATION_CONDITION / MISSING_SCOPE / DUPLICATE_KEY / DUPLICATE_ATTACHMENT / DANGLING_CONSEQUENCE_REF / DANGLING_INVALIDATION_REF / DANGLING_SOURCE_CLAIM / MISSING_SOURCE_CAUSAL_CLAIM / UNSUPPORTED_CERTAINTY_CLASS / ATTACHED_AT_OUT_OF_RANGE / IDENTITY_CORE_CHANGED / NON_MONOTONIC_RECORDED_AT / MALFORMED_MERGE / MALFORMED_SPLIT / MALFORMED_SUCCESSOR / MALFORMED_REVERSAL / MALFORMED_GOVERNANCE_EVENT / ALLOCATION_VIOLATION / INVALID_ROLE_COMBINATION / MISSING_PROVENANCE / MISSING_REASON / PROHIBITED_CONTENT / NOT_NORMALIZED / UNKNOWN_FIELDS / IDENTITY_MISMATCH / NON_CANONICAL_RECORD |

実装判断（契約の意味論を変えない範囲。field 名は A3 の推奨名を採用）:

- 機構語彙の初期集合（`MECHANISM_CATEGORIES`。component 型ごとに 7〜10 語 ＋ `OTHER`。企業名・銘柄名を含まない）を
  `mechanism_vocabulary:0.1.0` として同梱した。拡張は語彙 version の更新で行う（A2 §11 の shape 凍結に従う）。
- attachment に `evidence_date`（YYYY-MM-DD。temporal diversity の単位。MISSING では空）と `subject_refs`
  （evidence の subject entity の snapshot。DIRECTLY_EVIDENCED link の再計算材料）を持たせた。
- attachment の authority class は PRIMARY_OBSERVATIONAL のみ受理（A3 §7）。kind ごとの `evidence_time_basis` /
  `evidence_time_quality` の許容表と `ref_id` prefix（`fact_` / `obs_` / `doc_` / `news_`）を検査する。
- governance event の actor_class は Phase 6 では HUMAN のみ受理（A1 §16 の「自動 system がしてはならないこと」に該当
  する行為だけが event 種別であるため）。RULE / LLM_PROPOSAL は提案であり event を書けない。
- metadata の `value` は常に tuple（単一値 field は要素 1、集合 field は全集合 snapshot）。
- ThemeSubject / normalized_statement / ScopeToken.value は **正規化済み**（NFKC・casefold・空白圧縮）であることを要求
  し、黙って書き換えない（`normalize_text` を呼び出し側が使う）。
- INFERRED_EXPOSURE_LINK の `uncertainty` は HYPOTHESIZED / PARTIALLY_EVIDENCED / SOURCE_ASSERTED の class（数値でない）。
- Q4 の判定のため PERIOD_FRAME token をちょうど 1 つ要求し、予約値 `single_session` / `single_event` は保持できるが
  資格判定で DOES_NOT_QUALIFY になる。
- root id の生成（`new_root_id`）だけが乱数 / 時刻を使う。validator・fingerprint・資格判定は純関数。

次 gate（A4a 時点）: P6-A4b Theme canonical store（§27）。

## 31. 実装状態（P6-A4b canonical store。契約の意味論は変更していない）

| 項目 | 実装 |
|---|---|
| module | `src/intelligence/themes/store.py`（`ThemeStore`。5 authority の唯一の所有者）、`src/intelligence/themes/operations.py`（宣言先行の論理操作 plan / execute）。import は `core.ids` / `core.time` ＋ stdlib（json / os / pathlib）。closure 11 module |
| authority path | `<data_root>/themes/theme_roots.jsonl` / `theme_observations.jsonl` / `theme_governance.jsonl` / `theme_metadata.jsonl` / `theme_series_mappings.jsonl`。load 順 roots → observations → governance → metadata → mappings。`data_root` は明示必須（`core.paths` / repository 相対 fallback / `data/theme_learning` を使わない） |
| 初期化 / load | `ThemeStore.initialize(data_root)` だけが dir と 5 つの空 file を作る（明示の書込み。冪等）。`ThemeStore.open(data_root, read_only=False)` は file を作らず・書かず・修復しない（未初期化 ＝ NOT_INITIALIZED、authority 欠落 ＝ STORE_CORRUPTION/AUTHORITY_MISSING）。`ThemeStore.audit(data_root)` は read-only（件数・byte 長・PENDING・診断） |
| append | open mode `"a"` のみ、A4a `canonical_line` の bytes、write → flush → fsync。validate-before-append（自己 round-trip、履歴検査、byte 長検査）の後に 1 行 |
| 冪等 / conflict | 同一 id ＋ byte 一致 ＝ ALREADY_PRESENT（書かない）。同一 id ＋ bytes 差異 ＝ ThemeConflict（provenance / recorded_at だけの差でも。差分 field を報告） |
| canonical byte 検証 | load 時に parse → model → `canonical_line(record)` が保存 bytes と一致しなければ NON_CANONICAL_LINE（整形・key 順・空白の別表現を受理しない） |
| 改変検知 | file ごとに load / 最終 append 時の byte 長を記憶し、append 前に 5 file を検査。増減いずれも ConcurrentModificationDetected（lock ではない。明示の `reload()` だけが外部変化を取り込む） |
| writer 保証 | `WRITER_GUARANTEE = "SINGLE_WRITER"`。複数 process・並行 append・cross-file transaction は保証しない。1 store object が 5 file を所有（file 別の独立 writer を作る API は無い。constructor は factory 経由のみ） |
| root / genesis | RootRecord は genesis id を宣言して先に append 可（PENDING_GENESIS）。genesis は `observation_id == root.genesis_observation_id`（GENESIS_MISMATCH）、`recorded_at >= root.created_at`（OBSERVATION_BEFORE_ROOT）、root 不在は ROOT_NOT_FOUND |
| predecessor | 物理的に先行・同一 root・recorded_at 非減少・**物理 terminal からのみ**（NON_TERMINAL_PREDECESSOR ＝ fork を生む append の拒否）。file 上の既存 fork は選ばず `diagnostics()`（FORK）に載せ、その root への append は FORKED_ROOT で拒否 |
| attachment | `root.created_at <= attached_at <= observation.recorded_at`、`evidence_time <= attached_at`。例外は origin event の配分どおり byte 同一で carry された attachment（元 attached_at を保持するため root 作成前でよい） |
| governance | subject root・related record（subject root 所属、承認対象より後）・previous event（物理 terminal、root に関与）・reverses_event（同一 subject roots）の物理存在を検査。root に履歴があるのに previous を欠く event は MISSING_PREVIOUS_EVENT。result root は **存在してはならない**（RESULT_ROOT_ALREADY_EXISTS。宣言が先）、他 event との重複宣言は RESULT_ROOT_REDECLARED。配分は subject root の stored observation の実在 attachment のみ、同一 key を 2 source から同一 result へ配分不可 |
| metadata / mapping | root 実在、predecessor 実在・同一 root（metadata は同一 field）、recorded_at 非減少、物理 terminal から。metadata は履歴があれば previous 必須（MISSING_PREVIOUS_METADATA）。mapping の consequence_ref は当該 root の stored observation が宣言する key（MAPPING_CONSEQUENCE_UNKNOWN） |
| 宣言先行 | `operations.plan_candidate / execute_candidate`（RootRecord → genesis）、`plan_merge / plan_split / plan_successor / execute_declaration`（event → 結果 RootRecord → 結果 genesis、複数 child は child ごとに root → genesis）。plan は全 id を事前確定（root id は呼び出し側が `new_root_id` で生成、他は content id）、同じ入力から同じ record。`previous_event_ids` は最初の試行前に `terminal_previous_events` で一度だけ取得し再試行でも同じ値を渡す（crash 後に取り直すと別 event になり RESULT_ROOT_REDECLARED で拒否される） |
| PENDING | `pending()`: PENDING_GENESIS（RootRecord あり・宣言 genesis なし）/ PENDING_EVENT（宣言 event あり・result root か genesis が未完。欠落 id を列挙）。load は補完も修復もしない。同じ plan の再実行が冪等に完了する |
| carried evidence | lineage は宣言 event の `evidence_allocation`（(source observation, attachment_key) → result root。event id の材料）が保持し、結果 genesis の attachment は source attachment と **byte 同一**でなければ ALLOCATION_VIOLATION（元 attached_at / role provenance / evidence 時点を保持）。genesis の attachment は配分の部分集合のみ（暗黙 carry なし、自動全複製なし）。attachment 自体に `carried_from` field は持たせない（A4a の canonical bytes / golden vector を変えないため。lineage は event 側で完全に再構成できる） |
| 失敗区分 | STORE_CORRUPTION（ThemeStoreCorrupt: AUTHORITY_MISSING / INVALID_ENCODING / TRUNCATED_FINAL_LINE / BLANK_LINE / MALFORMED_JSON / NOT_AN_OBJECT / INVALID_RECORD / UNSUPPORTED_SCHEMA_VERSION / NON_CANONICAL_LINE / PHYSICAL_DUPLICATE_IDENTICAL / PHYSICAL_DUPLICATE_CONFLICTING）／INVALID_HISTORY（ThemeInvalidHistory。load 時）と APPEND_REJECTED（ThemeAppendRejected。append 時）が共有する code: ROOT_NOT_FOUND / GENESIS_MISMATCH / DANGLING_PREDECESSOR / WRONG_ROOT_PREDECESSOR / NON_TERMINAL_PREDECESSOR / NON_MONOTONIC_RECORDED_AT / OBSERVATION_BEFORE_ROOT / ATTACHED_AT_OUT_OF_RANGE / FORKED_ROOT / ORIGIN_EVENT_MISSING / ORIGIN_EVENT_MISMATCH / RESULT_ROOT_NOT_DECLARED / RESULT_ROOT_DECLARED_ELSEWHERE / RESULT_ROOT_ALREADY_EXISTS / RESULT_ROOT_REDECLARED / GOVERNANCE_REFERENCE_MISSING / MISSING_PREVIOUS_EVENT / MALFORMED_REVERSAL / ALLOCATION_VIOLATION / METADATA_PREDECESSOR_MISSING / MISSING_PREVIOUS_METADATA / MAPPING_PREDECESSOR_MISSING / MAPPING_CONSEQUENCE_UNKNOWN / NON_CANONICAL_RECORD / INVALID_TYPE／CONFLICT（ThemeConflict）／CONCURRENT_MODIFICATION／NOT_INITIALIZED／READ_ONLY。PENDING と fork 診断は例外ではない |
| load の 2 pass | 固定順で 1 行ずつ parse ＋ 同一 file / 先行 authority への参照を検査（intra）、全 authority 読込後に後続 authority への参照（root の origin event、observation の carried 配分、event の result root 整合）を検査（cross）。append 時は両方を即時に検査 |
| A4c へ | 点時刻再構成、governance / metadata / mapping の terminal 選択と UNRESOLVED 判定、EVENT_REVERSED の意味論、上流 dereference、DUPLICATE_CANDIDATE の提示。A4b は生 record の exact lookup と物理 terminal（`physical_terminal_*`）だけを提供する |

次 gate（A4b 時点）: P6-A4c Theme point-in-time resolver（§27）。

## 32. 実装状態（P6-A4c point-in-time resolver。契約の意味論は変更していない）

branch: A4c 以降は `claude/investment-intelligence-phase6`（A4b anchor `6b4bc86909c0f1101d898b31f0c518cc7daa46fd` から分岐。
phase5 branch は同 anchor で不変）。

| 項目 | 実装 |
|---|---|
| module | `src/intelligence/themes/resolver.py`（`theme_resolver:0.1.0`）。import は `core.time` ＋ themes の model / fingerprint / qualification / store（read-only API のみ）。closure 12 module |
| 入力 | `ThemeHistory`（5 authority の in-memory record 集合。順序は無意味）。`ThemeHistory.from_store(store)` は `canonical_lines` から復元、`resolve_from_store` / `resolve_at_data_root`（read-only open）は書かない・reload しない |
| API | `resolve(history, root_id, cutoff, dereference=None)`、`resolve_from_store(store, …)`、`resolve_at_data_root(data_root, …)`。current / latest / active / state_at 等の便宜 API は無い |
| cutoff | aware 必須（naive は NAIVE_DATETIME）。root `created_at <= T`、observation / governance / metadata `recorded_at <= T`、mapping `recorded_at <= T` かつ `valid_from <= T`、attachment `evidence_time <= T` かつ `attached_at <= T`。T 後の record は結果にも診断にも現れない |
| status | `ResolutionStatus` RESOLVED / NO_STATE / UNRESOLVED / INVALID_HISTORY / STORE_CORRUPTION（統合しない）。facet は `GovernanceStatus`（RESOLVED / NO_GOVERNANCE / UNRESOLVED / NOT_EVALUATED）、`MetadataStatus`（… NO_METADATA …）、`MappingStatus`（… NO_MAPPING …）。STORE_CORRUPTION / INVALID_HISTORY は `resolve_at_data_root` が store の fail closed を status として返す（facet は NOT_EVALUATED） |
| observation | root 内 eligible observation だけで predecessor graph を再構成。唯一 terminal ＝ RESOLVED、0 件 ＝ NO_STATE（NOT_YET_OBSERVED）、fork / 複数 terminal / 複数 start ＝ UNRESOLVED（診断 FORK / MULTIPLE_TERMINALS / MULTIPLE_STARTS）、genesis 不一致・宣言 genesis 不可視・dangling・別 root predecessor・cycle ＝ INVALID_HISTORY。recorded_at 最大・物理順は使わない |
| evidence view | terminal observation の attachment のうち両時点 ≤ T のみ `visible`。`not_yet_attached`（attached_at > T）、`evidence_after_cutoff`（evidence_time > T。model 上は不可能だが独立検査）、`context_without_time`（quality MISSING の CONTEXT。authoritative view 外）を分離 |
| governance | root ごとの eligible event chain（subject event は `previous_event_ids[root]`、宣言 event は start）。唯一 terminal ＝ RESOLVED、fork / 複数 start ＝ 当該 facet のみ UNRESOLVED、無し ＝ NO_GOVERNANCE。EVENT_REVERSED は履歴を残したまま `in_force(e) = not any(in_force(r) for r in reversals_of[e])` で畳み込み、効力を持つ最後の非取消 event を `effective_event_id / effective_event_type` に返す（取消の取消も扱う）。lifecycle 状態名は導入しない |
| lineage | eligible な MERGE / SPLIT / SUPERSEDED_BY_ROOT から MERGED_INTO / MERGE_OF / SPLIT_INTO / SPLIT_FROM / SUPERSEDED_BY / SUCCESSOR_OF を注釈として返す。旧 root の semantic observation は書き換えない |
| metadata | (root, field) ごとに独立解決（LABEL / DESCRIPTION / TAXONOMY / ALIAS の 4 facet を常に返す）。無し ＝ NO_METADATA、fork ＝ その field だけ UNRESOLVED |
| mapping | eligible mapping の supersession chain。並行 chain（別 series）は正当で terminal 集合を返す。同一 predecessor を 2 つ以上が supersede ＝ facet のみ UNRESOLVED。predecessor が未だ有効でない（valid_from > T）場合は start 扱い（診断 PREDECESSOR_NOT_YET_ELIGIBLE） |
| PENDING | `pending`: PENDING_GENESIS（root は T で存在、宣言 genesis が T で不可視）、PENDING_EVENT（宣言 event は T で可視、result root または genesis が T で不可視。result root 側の解決でも返す）。修復・補完しない。後日の完了 record が T より後なら過去の結果は変わらない |
| carried evidence | result root の attachment のうち origin event の配分に一致し source attachment と byte 同一のものを `CarriedEvidence(attachment_key, source_observation_id, source_root_id, origin_event_id)` として再構成（A4b と同じ authority。attachment schema に carried_from を追加しない） |
| DERIVED | fingerprint（A4a `identity_core_fingerprint` / `semantic_fingerprint`）、資格判定（A4a の `counted_attachments` / `exclusion_diagnostics` / `independent_origin_count` / `evidence_date_set` / `period_frame` を **visible attachment だけ**に適用。`evaluate_qualification` と同じ合成）、DIRECTLY_EVIDENCED link、contradiction / invalidation flag。canonical に保存しない |
| dereference | `UpstreamLookup = Callable[[EvidenceAttachment], DereferenceStatus]` を caller が供給（既定 NOT_CHECKED）。NOT_CHECKED / AVAILABLE / NOT_FOUND / SUPERSEDED / UNUSABLE / DUPLICATE_ORIGIN。resolver は何も取りに行かず、結果は canonical 再構成と別 field |
| 決定論 | 同一 record 集合・root_id・cutoff → 同一 `ThemeResolution`（frozen dataclass 等価）。入力順の shuffle・disk からの再読込で不変（test） |
| 純粋性 | write / repair / reload / 時計 / 乱数 / network / SQLite / Compass / Brief / P5 / legacy config なし（boundary test で token 検査、read-only open のみ） |
| A4d へ | E2E world（fork / merge / split / successor / correction / 遅延付与 / 上流改訂 / crash / journal 連結）、replay 決定論、不変条件 1〜97 の test 対応表、derived SQLite index は A4d 以降 |

次 gate: **P6-A4d Theme foundation E2E**（§27）。

## 33. 検証状態（P6-A4d E2E。契約の意味論は変更していない。runtime は無変更）

A1〜A4c を canonical journal（5 authority）だけで連結し、代表 world・時間旅行・再起動・byte replay・入力順
shuffle・future leakage・crash / PENDING・fork 隔離・correction / revision・merge / split / successor・上流改訂・
derived 非保存・破損 fail closed を E2E で検証した。不変条件 1〜97 の対応表は
`docs/databank/PHASE6_THEME_FOUNDATION_INVARIANT_MATRIX.md`。

| 項目 | 状態 |
|---|---|
| 検証 module | `tests/intelligence/theme_foundation_fixtures.py`、`test_theme_foundation_e2e.py`、`test_theme_foundation_replay.py`、`test_theme_foundation_failures.py`（47 passed ＋ 5 strict xfail） |
| 凍結 runtime | `model / fingerprint / qualification / revision / store / operations / resolver` は A4c 時点から diff 0 |
| 判定 | **BLOCKER_FOUND**（freeze 宣言なし）。契約は変更しない。test は弱めない。workaround しない |
| A4D-1 | store が identity core の置換を同一 root の revision として受理する（本契約 §7 の IDENTITY_CORE_CHANGED、§23 の INVALID_HISTORY が store / resolver で未実装。純 helper `revise_observation` のみ拒否）。最小修正候補: `store._validate_observation_chain` の非 genesis 分岐と resolver `_resolve` に `identity_core_fingerprint` 比較を追加。影響: store.py / resolver.py のみ、canonical bytes・id 不変 |
| A4D-2 | METADATA_CORRECTION_APPROVED（related record が metadata id）を append した store が再 open できない（§3 の固定 load 順 roots → observations → governance → metadata により、governance の intra pass で GOVERNANCE_REFERENCE_MISSING）。最小修正候補: 当該 related record 検査を cross pass `_validate_event_results` へ移す。影響: store.py のみ、append 時挙動不変 |
| A4D-3 | 宣言済みだが RootRecord 未作成の result root を解決すると UNKNOWN_ROOT のみで PENDING_EVENT / lineage が付かず、後日の RootRecord が同じ T の診断を変える（§13 の非遡及、A4c §32 の「result root 側でも PENDING_EVENT」に反する。state facet は不変）。最小修正候補: resolver `_resolve` の root 不在分岐でも T で eligible な宣言 event を集めて PENDING_EVENT ＋ lineage を付ける。影響: resolver.py のみ、診断のみ変化 |
| 証明済み（抜粋） | 全 checkpoint の state facet は後段 stage で不変、byte replay は bytes・id・結果を再現、shuffle 不変、別 process 再読込一致、crash 段階は PENDING として可視で修復されない、fork は当該 facet のみ UNRESOLVED、破損 5 態様は resolver 入口で STORE_CORRUPTION / INVALID_HISTORY、derived 値は JSONL に無い |
| DEFERRED | 23（企業固有 thesis は Theme 定義の外）、76（SQLite は derived のみ）、85（index の削除 / 再構築は canonical の結果を変えない）は後続 gate |

次 gate: **BLOCKER 修正 gate（A4D-1 / A4D-2 / A4D-3。store.py / resolver.py の最小修正 ＋ 当該 xfail の解除）**。
修正後に A4d の freeze 判定を再実行する。
