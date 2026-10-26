# PHASE 7 / P7-A2 — POINT-IN-TIME INPUT ASSEMBLY CONTRACT（SANCTIONED ONE-WAY READ ADAPTER）

A2 は Narrative の**入力材料**だけを作る。`NarrativeSynthesis`・claim・文章・描画・LLM・永続化・authority の変更は無い。
module: `src/intelligence/narrative_intelligence/input_model.py`（純 model）・`pit_assembler.py`（認可された読み取り adapter）。
test: `tests/intelligence/test_narrative_pit_assembler.py`（matrix A〜AX）・`tests/intelligence/test_narrative_intelligence_boundary.py`
（AY〜BH を追加）・`tests/intelligence/phase7_runtime_registry.py`（登録の更新）。

anchor: P7-A1 freeze `a02ad60878054b5846b11acac720fa2811f32505`、P7-A0 freeze `2fe7d0f03c3c8ab2e566508079b788f9e69fcb71`、
Phase 6 freeze `5ef313a6a9477f05b4e46756fb8b79c0f0c3d685`。入る前の基準: 4493 passed / 2 skipped。

**本 gate の設計判断（監督の確認を求める）**

| id | 事項 | 選択 |
|---|---|---|
| D-P7-A2-1 | THEME_STATE の relation | **投影しない**（`relations` は None）。文脈 Theme の範囲を明示する仕組みは延期（§13。指示の「狭い方」） |
| D-P7-A2-2 | freshness policy | **caller の明示入力**（`stale_after_days`、既定値なし）。B2 と同じ扱いで identity に入る（§11） |
| D-P7-A2-3 | knowledge pin | **作らない**。A2 の出力を変える versioned knowledge（YAML）は無い。代わりに読みに使った reader の version を `reader_versions` に束ねる（§17） |
| D-P7-A2-4 | relation authority が無いとき | **fail closed**（`RELATION_AUTHORITY_UNAVAILABLE`）。B5 自身が「authority の欠落」を破損として返すため、空とみなさない（§13） |
| D-P7-A2-5 | Theme authority の読み方 | Foundation store を**1 回だけ**検証して読み、すべての root と cutoff をその history で `resolve` する（§8） |

---

## 1. 目的

caller が明示した型・Theme root・aware な cutoff（と任意の比較 cutoff）について、凍結された Phase 6 の reviewed authority を
PIT で読み、A1 の型付き ref に写した決定論的な `NarrativeInputSnapshot` を作る。A3（synthesis engine）はこれだけを入力にする。

```
caller の要求（型・Theme root・cutoff・policy・任意の比較 cutoff）
  → Phase 6 の read-only API（Foundation store / resolver、B2 lifecycle、B1 change、B5B relation）
  → PIT で解決 → 資格の判定（cutoff で ACCEPTED）→ A1 の ref への投影 → NarrativeInputSnapshot → （将来）A3
```

## 2. authority の分類

`NarrativeInputSnapshot`（と `ThemeInput`・`EvidenceSource`）は **DERIVED / NON-AUTHORITY / NON-PERSISTENT**。

- Narrative ではない（claim を持たない）。Theme・governance・evidence・relation の authority ではない。
- 保存しない。復元 API（`from_dict` / `from_json`）を持たない。`to_canonical_json` は identity と比較のための bytes だけ。
- 型名は `NarrativeSynthesis`・`NarrativePlan`・`NarrativeAuthority` を使わない。
- 凍結文言（test で固定）: `SNAPSHOT_IS_NOT_AUTHORITY` = "a narrative input snapshot is derived, non-authoritative,
  non-persistent input material for a future synthesis; never a narrative, a theme or governance authority, or a stored
  record"。

## 3. caller の契約

`NarrativeInputRequest`（すべて明示。暗黙の「全 Theme」「最新」「現在」「市場全体」「自動発見」「前回の実行」は無い）:

| field | 規則 | 違反 |
|---|---|---|
| `kind` | `THEME_STATE` ／ `THEME_SET`（A1 の `NarrativeKind`） | `INVALID_KIND` |
| `root_ids` | Theme root id の tuple / list。重複なし。id 順に正規化（非意味的な集合） | `INVALID_SCOPE` |
| `cutoff` | aware な datetime | `INVALID_CUTOFF` |
| `stale_after_days` | 1〜3650 の int（bool 不可）。既定値なし | `INVALID_POLICY` |
| `comparison_cutoff` | 省略可。与えるなら aware で `cutoff` より厳密に前 | `INVALID_COMPARISON_CUTOFF` |

`assemble_input_snapshot(*, data_root, request)`: `request` は `NarrativeInputRequest`（`INVALID_REQUEST`）、`data_root` は明示の
root（None・空文字は `INVALID_DATA_ROOT`。既定の root は無い）。

## 4. 範囲（scope）

- THEME_STATE はちょうど 1 root、THEME_SET は 2〜16 root（A1 の `MAX_SUBJECTS`）。
- **列挙しない**: 解決するのは要求された root だけ。snapshot の `root_ids` は要求と一致し、evidence・relation も要求された root の
  ものだけ（test F）。Foundation store は検証のために journal 全体を読むが（§20）、どの Theme を解決するかは caller が決める。
- 「面白い Theme」を選ぶ・補う仕組みは無い（B6 の明示 scope の先例と同じ）。

## 5. 認可された import 境界

監督判断: Phase 6 は凍結。**`src/intelligence/narrative_intelligence/pit_assembler.py` だけ**が、次の Phase 6 の read-only API を
import してよい（完全一致。test BA が module と名前の組を固定する）:

| Phase 6 module | 名前 |
|---|---|
| `themes.store` | `ThemeStore`（`open(read_only=True)` だけ）・`ThemeStoreError`・`ThemeStoreCorrupt`・`ThemeInvalidHistory` |
| `themes.resolver` | `ThemeHistory`・`resolve`・`ResolutionStatus` |
| `theme_intelligence.lifecycle` | `derive_lifecycle` |
| `theme_intelligence.lifecycle_model` | `LifecyclePolicy`・`GovernanceLifecycleState`・`LifecycleViewStatus`・`ThemeLifecycleError` |
| `theme_intelligence.model` | `ChangeSetStatus` |
| `theme_intelligence.change` | `compare_resolutions` |
| `theme_intelligence.relation_store` | `resolve_relations_at_data_root` |
| `theme_intelligence.relation_resolution` | `endpoint_lookup_from_roots`・`EdgeState`・`RelationResolutionStatus` |

依存の向き: Phase 7 A2 adapter → Phase 6 の凍結 read API（許可）。Phase 6 → Phase 7（禁止。test BD）。A1 の `synthesis_model` と
A2 の `input_model` は Phase 6 を import しない（test BB）。adapter は書き込み API（`append_*`・`initialize`・`write*` 等）の属性に
触れず、`open` は `read_only=True` の 1 回だけ（test BA）。

**Phase 6 の test への test-only の登録（§31。Phase 6 runtime の変更 0 行）**:

| file | 目的 |
|---|---|
| `test_theme_phase6_completion.py` | 「Phase 6 の外から Phase 6 を import しない」guard が、登録した importer の**完全な path だけ**を飛ばす（2 行）。登録 helper の import 行に `PHASE7_SANCTIONED_IMPORTERS` を足す（A1 で入れた行の更新） |
| `test_theme_intelligence_import_boundary.py` | 「theme_intelligence を import しない」guard が同じ path だけを飛ばす（import 1 行 ＋ 2 行） |
| `test_theme_import_boundary.py` | 「Foundation（themes）を import しない」guard が同じ path だけを飛ばす（import 1 行 ＋ 2 行） |

- 登録 helper（`phase7_runtime_registry.py`）: `PHASE7_RUNTIME` に `input_model.py`・`pit_assembler.py` を追加、
  `PHASE7_SANCTIONED_IMPORTERS` ＝ (`…/pit_assembler.py`,) と `is_sanctioned_importer`（完全一致）を追加、上の 3 file の登録の
  行を `PHASE6_TEST_REGISTRATION` に宣言。Phase 7 の guard は 10 file の Phase 6 completion anchor との差分が宣言と完全に一致する
  ことを確かめる。
- 未登録の importer は失敗する: 同じ package の第 2 の module が Phase 6 の store を import すると、Phase 7 の guard（package の
  module 一覧・import の許可一覧・未認可 importer の検出）と Phase 6 の 3 つの import guard と Phase 6 completion の凍結 guard が
  失敗する（mutation M15。scratch の clone で確認）。package 全体を認可しない（path の完全一致だけ）。

## 6. Theme の資格

要求 root ごとに、cutoff で Foundation resolver ＋ B2 lifecycle を解決する:

| 状態（cutoff 時点） | 結果 |
|---|---|
| RESOLVED かつ lifecycle の governance が ACCEPTED かつ lifecycle view が AVAILABLE | 資格あり（投影する） |
| root が無い（未知・cutoff より後に作成・宣言だけ） | `ROOT_NOT_FOUND` |
| root はあるが observation が無い（NOT_YET_OBSERVED）・observation の fork（UNRESOLVED）・governance が UNRESOLVED / NOT_AVAILABLE・lifecycle が導けない（correction の遡りに失敗等）・evidence の評価が未解決 | `ROOT_NOT_RESOLVED` |
| UNREVIEWED・REJECTED・RETIRED・MERGED・SPLIT・SUPERSEDED | `ROOT_NOT_ACCEPTED_AT_CUTOFF` |
| authority の破損 ／ 不可能な履歴 | `AUTHORITY_CORRUPTION` ／ `AUTHORITY_INVALID_HISTORY`（全体を止める） |

cutoff より後に作られた root を「未知の root」と同じ `ROOT_NOT_FOUND` にする（未来の存在を漏らさない。test H）。

## 7. 歴史の再構成

現在の状態は過去の再構成に関係しない。T で ACCEPTED だった Theme は、後で退役・合併・分割・後継されても T の ACCEPTED の
状態で再構成される（test K: Foundation の代表 world の Theme A を「受理」「意味の改訂」「遅延 evidence」「退役の取り消し」の
各 checkpoint で組み立てる）。未来の governance は過去へ漏れない（test L）。未来の後継・合併・分割は過去を変えない（test O:
合併の前で止めた world と合併まで進めた world で、合併前の cutoff の snapshot が byte 一致）。

## 8. observation の PIT

- Theme authority は `ThemeStore.open(read_only=True)` で**1 回だけ**開く（5 authority を検証してから載せる）→
  `ThemeHistory.from_store` → root ごと・cutoff ごとに `resolve`。1 回の読みをすべての root と比較 cutoff に使うので、root ごとに
  別の状態を見ることが無い。
- 資格があるのは cutoff で解決した terminal observation だけ。cutoff より後の observation・改訂・後継・合併 / 分割の結果・
  evidence の付与・governance event は snapshot を変えない（test L〜O・AC）。
- integrity-before-PIT: 所有層の検証を迂回しない（JSONL を自前で読み・濾過しない）。未来日付の行でも壊れていれば全体を止める
  （test P）。

## 9. evidence の投影

- 投影するのは resolver の**authoritative な view**（`EvidenceView.visible`: `attached_at <= T` かつ `evidence_time <= T`）だけ。
  時刻の無い CONTEXT（quality MISSING）は view の外で、投影しない（test N）。付与前（`not_yet_attached`）・時刻が cutoff 後の
  ものは id も写さない。
- 1 attachment → A1 の `EvidenceAttachmentRef`: root・observation・`ref_id`・`evidence_kind`・`consequence_key`（←
  `consequence_ref`）・`role`・`role_provenance`・`attached_at`・`invalidation_condition_key`（← `invalidation_condition_ref`）を
  **そのまま**写す。SUPPORTS / CONTRADICTS / CONTEXT / INVALIDATES を書き換えない（test Q〜T）。
- 1 evidence item（`ref_id` ごと）→ A1 の `EvidenceItemRef`（kind・`evidence_time`・`time_quality`）と出所の能力（§10）。同じ
  `ref_id` が Theme ごとに違う記述を持てば `EVIDENCE_ITEM_INCONSISTENT`（推測しない）。
- 写さないもの: `excerpt`・`locator`・`note`・`role_asserted_by`・`source_origin`・`subject_refs`・QA / revision の痕跡・本文。
  A1 の token 形式に合わない値は `REF_NOT_PROJECTABLE`（正規化しない）。

## 10. 出所の能力（source capability）

`SourceCapability` は kind だけから決まり、格上げできない（`EvidenceSource` が不一致を `SOURCE_CAPABILITY_MISMATCH` で拒否）:

| evidence kind | 能力 | A1 での扱い |
|---|---|---|
| FACT・OBSERVATION | `OBSERVATIONAL_RECORD` | OBSERVED_FACT に使える（A1 の事実の天井の内側） |
| SOURCE_DOCUMENT・NEWS_ITEM・STATEMENT（発言） | `SOURCE_CONTENT` | 出典の主張。OBSERVED_FACT にならない（A1 も `FACT_REQUIRES_OBSERVATIONAL_EVIDENCE` で拒否） |

## 11. lifecycle

- B2 `derive_lifecycle` を、PIT の resolution と caller の明示の `LifecyclePolicy(stale_after_days)` で呼ぶ。effective event が
  correction のときの遡りには、cutoff までの governance event だけを渡す（未来の event は渡さない）。
- 投影するのは governance の位置（ACCEPTED。`ThemeObservationRef.governance_position`）と evidence condition の flag の集合
  （`EvidenceConditionFlag`: NO_VISIBLE_EVIDENCE・HAS_CONTEXT_ONLY・HAS_SUPPORT・SINGLE_SOURCE・MULTI_SOURCE・SINGLE_EVIDENCE_DATE・
  MULTI_DATE・QUALIFIES・CONTESTED・INVALIDATION_EVIDENCE_PRESENT・STALE）だけ。
- 件数・最新日付・経過日数・governance の journal・人間の review の理由は写さない。governance の chain・effective / state event・
  取り消し・lineage は id だけを provenance digest に入れる（§19）。
- 無効化 evidence は状態を変えない（flag として示すだけ。test T）。

## 12. 変化と比較 cutoff

- `comparison_cutoff` が**明示されたときだけ**、B1 `compare_resolutions(resolve(Tc), resolve(T))` で変化を投影する。既定の期間・
  「前回の実行」・「昨日から」は無い。省略なら全 Theme の `changes` は **None**（変化なしの空 tuple とは区別する）。
- 各変化は A1 の `ThemeChangeRef`（root・from = Tc・to = T・`change_kind`・`facet`・`subject_id`）。B1 の `before` / `after` /
  `detail` / `related` の本文は写さない。同じ (kind, facet, subject) は 1 つの ref（投影の集合）。
- 比較できない（B1 の change set が UNAVAILABLE・B1 の検査の失敗）ときは `CHANGE_NOT_AVAILABLE`（root ごとの失敗）。比較側の
  cutoff でも resolution は PIT（test AC）。
- 比較 cutoff は identity に入る（test AQ）。reader に `theme_change_model` の version が加わる。

## 13. relation の投影

- **THEME_SET だけ**。B5B `resolve_relations_at_data_root` に、要求集合の root の作成時刻だけを知る `endpoint_lookup_from_roots`
  を渡す（集合の外の端点を持つ辺は B5 が除外する）。
- 投影するのは cutoff で **ACTIVE** な直接の辺で、両端が要求集合の内側のもの → A1 の `RelationAssertionRef`（terminal の
  assertion id・端点・型・assertion class）。撤回済み・未来・集合の外・推移（P→Q→R から P→R）・推測・提案・共同発見の辺は無い
  （test AD〜AG）。
- 集合に触れる未解決の辺は推測せず `RELATION_NOT_RESOLVED`。破損は `AUTHORITY_CORRUPTION`、不可能な履歴は
  `AUTHORITY_INVALID_HISTORY`、authority の欠落（B5 の `AUTHORITY_MISSING`）は `RELATION_AUTHORITY_UNAVAILABLE`（空とみなさない。
  D-P7-A2-4）。B5 の diagnostics（未来の assertion id を含む）は写さない。
- **THEME_STATE は relation を投影しない**（`relations` と `relation_provenance_digest` は None）。関係の相手の Theme を caller が
  明示して認可する「文脈の範囲」の仕組みを A2 では model 化しない（D-P7-A2-1。延期 §25）。THEME_STATE は relation authority を
  読まない（壊れていても THEME_STATE は止まらない。test AX）。

## 14. SOURCE_ASSERTED

- `assertion_class` をそのまま写す（SOURCE_ASSERTED を HUMAN_ASSERTED や客観的な事実に変えない。test AH・M12）。A1 では
  `SOURCE_ASSERTED_RELATION` でしか引用できない（`ASSERTION_CLASS_MISMATCH`）。
- B5 の帰属（`source_attribution.attributed_to`）の文字列・rationale・evidence ref の locator は写さない。辺の identity は terminal
  assertion id が運び、assertion chain と governance chain の id は relation provenance digest に入る。
- 投影するのは B5B の authoritative な assertion の状態だけ。B5C の提案の状態は読まない（§15）。

## 15. 除外する入力

| 入力 | 扱い | 証明 |
|---|---|---|
| B3 の open / deferred の提案と decision | 読まない | 毒入りの journal でも snapshot が byte 一致（test AI）・import の許可一覧（BA）・M7 |
| B4 の discovery hit・提案の材料・knowledge | 読まない（A2 は knowledge root を受け取らない） | 毒入りの knowledge でも同じ（AJ）・許可一覧 |
| B5C の relation 提案 | 読まない | 毒入り（AF）・本物の提案 P→R を足しても P→R は出ない（AF）・M10 |
| B6 の MonitoringFinding・MonitoringRunReport・ReviewItemState | 読まない | 毒入りの review store（AK）・M8 |
| B7 の生成物・validated plan・生成 journal・provenance | 読まない | 毒入りの生成 journal（AL）・M9 |
| 未審査の文脈の lane | A2 には無い（延期） | 型に field が無い |

## 16. P5 と Production DNA

- P5（prediction・evaluation・calibration）は import も入力もしない（毒入りの P5 journal でも同じ。test AM・BE）。
- Production DNA は読まない・解釈しない・`rule_ref` も運ばない（具体的な用途が無い）。Compass・corpus・formal review も読まない。

## 17. knowledge の pin

判断（D-P7-A2-3）: A2 の snapshot を変える **versioned knowledge（YAML）は無い**。Foundation resolver・B2・B1・B5B は taxonomy・
entity catalog・discovery rule・monitoring rule を読まない。機構の語彙の version は observation の中にあり、`observation_id`（content
id）が束ねる。したがって knowledge の pin は作らない（捏造しない）。

代わりに、出力を変える reader の version を `reader_versions` に束ねる（読んだ結果から取る。想定外の名前は
`READER_VERSION_UNSUPPORTED`）: `theme_resolver`・`theme_lifecycle_model`・`theme_lifecycle_policy`（policy の schema）、比較 cutoff が
あれば `theme_change_model`、THEME_SET なら `theme_relation_resolver`。`stale_after_days` も snapshot に入る。

## 18. snapshot の model

`NarrativeInputSnapshot`（不変）:

| field | 内容 |
|---|---|
| `kind` | THEME_STATE ／ THEME_SET |
| `root_ids` | 要求された root（id 順）。資格のある解決済みの Theme と一致する（黙って落とさない） |
| `cutoff` ／ `comparison_cutoff` | aware ／ 省略時 None |
| `themes` | `ThemeInput` の列（root 順）: `observation`（A1 `ThemeObservationRef`）・`components`・`invalidation_conditions`・`attachments`・`evidence_condition_flags`・`changes`（None か tuple）・`provenance_digest` |
| `evidence_sources` | `EvidenceSource`（A1 `EvidenceItemRef` ＋ `SourceCapability`）。attachment が指す item と完全に一致 |
| `relations` ／ `relation_provenance_digest` | THEME_SET だけ（A1 `RelationAssertionRef` の集合）／ THEME_STATE は None |
| `reader_versions` | (name, version) の集合（§17） |
| `stale_after_days` | caller の freshness policy |
| `snapshot_id` | 導出（§19） |

非意味的な集合（root・theme・component・condition・attachment・flag・change・source・relation・reader）はすべて canonical な順に
正規化する。検査の失敗は `INCONSISTENT_INPUT` ほか（fail closed）。文章・score・順位・確信度・path の field は無い（test BH）。

## 19. identity と digest

- `snapshot_id` = `content_id("narinp", canonical_json(payload))`。payload は §18 のすべて（要求の範囲・cutoff・比較 cutoff・投影した
  意味内容・provenance digest・reader の version・policy）。
- Theme の `provenance_digest` = `content_id("narprv", …)`: resolver の version・root・observation id・governance の chain・effective /
  state event・取り消した event・lineage（kind・event・関係 root）・visible な attachment key。**PIT で見えた id だけ**。
- relation の `relation_provenance_digest` = relation resolver の version と、投影した辺の assertion id・assertion chain・governance
  chain。
- Phase 6 は PIT で使える authority digest を公開していない（store の `record_digest` は行の衝突検出用で、cutoff を持たない）。
  そのため PIT で見えた意味の投影から導く（Phase 6 を作り直さない）。
- 依らないもの: data_root の path・mtime・現在時刻・処理順・乱数（test AN〜AS）。同じ PIT 状態なら同じ canonical bytes と id。
  意味の変化（evidence の追加・governance の履歴・policy・cutoff・比較 cutoff）は id を変える（test AP〜AR）。

## 20. 破損と fail closed

| 状況 | code |
|---|---|
| Theme store の検証の失敗（破損した行・切り詰め・書き換えで identity が合わない行。未来日付でも） | `AUTHORITY_CORRUPTION` |
| Foundation の不可能な履歴（store の検証 ／ resolver の INVALID_HISTORY） | `AUTHORITY_INVALID_HISTORY` |
| Theme store が無い（未初期化）・読めない | `AUTHORITY_UNAVAILABLE` |
| relation store の破損 ／ 不可能な履歴 ／ 欠落（THEME_SET） | `AUTHORITY_CORRUPTION` ／ `AUTHORITY_INVALID_HISTORY` ／ `RELATION_AUTHORITY_UNAVAILABLE` |
| 集合に触れる未解決の辺 | `RELATION_NOT_RESOLVED` |

修復・切り詰め・悪い行の読み飛ばし・空への fallback はしない。evidence の role を journal 上で書き換えた行は Foundation の identity
検査で拒否され、投影されない（test AW）。

## 21. 無い root ／ 資格の無い root

- 要求された root は黙って消えない。root ごとの失敗（`ROOT_NOT_FOUND`・`ROOT_NOT_RESOLVED`・`ROOT_NOT_ACCEPTED_AT_CUTOFF`・
  `REF_NOT_PROJECTABLE`・`CHANGE_NOT_AVAILABLE`）はすべての root について集め、`NarrativeInputError` の `failures`（(root, code) の
  列。root 順）で返す。部分的な snapshot は作らない（test J）。
- 範囲・cutoff の誤りは `INVALID_SCOPE`・`INVALID_CUTOFF`・`INVALID_COMPARISON_CUTOFF`・`INVALID_POLICY`・`INVALID_KIND`。
- error の detail は field 名か上流の code だけ。本文・path・人間の文を載せない（test で canary と tmp path を確認）。

## 22. 文章を持たない規則

snapshot は型付きの id・enum・有界な構造化 metadata・canonical な ref だけを持つ。説明の文章・記事の抜粋・出典の本文・人間の
review の注記・subject の表示文・機構の statement・無効化条件の文・relation の rationale・帰属の文字列は入らない（test U: world に
仕込んだ canary の文字列が snapshot のどこにも現れない）。

## 23. 書き込みなし

- A2 は何も書かない（journal・JSONL の追記・SQLite・cache・snapshot の file・data_root の出力なし）。読むのは caller が与えた
  data_root の Phase 6 authority だけ。
- 証明（test AT / AU）: 組み立て（THEME_STATE・比較 cutoff つき THEME_SET・失敗する要求を含む）の前後で data_root の全 file の
  sha256 と file / directory の一覧が一致。未初期化の Theme store・無い relation store を作らない。
- 静的な guard（BF）: adapter と model は書き込み API の属性・`open`・cache を使わない。mutation M14（snapshot の cache を書く）は
  検出される。

## 24. security

- 秘密値・credential・API key を持たない・求めない。network・provider・LLM を使わない（BE）。時計・乱数を使わない（BG）。
- snapshot と error に machine 固有の path を入れない（AS・error の test）。生の LLM 応答・隠れた推論・顧客 / portfolio の data・
  Compass corpus・記事本文を持たない。adapter は Phase 6 の機密になりうる属性（excerpt・note・locator・statement・reason・
  actor_ref・rationale・帰属・subject 等）に触れない（BH。AST で固定）。

## 25. 延期の項目

| id | 項目 |
|---|---|
| P7-A2-DEF-01 | THEME_STATE の文脈 Theme の範囲（関係の相手を caller が明示して認可する仕組み）と、その relation の投影 |
| P7-A2-DEF-02 | 撤回された relation を「撤回の事実」として示す投影（A0 §13） |
| P7-A2-DEF-03 | lineage（MERGE_OF・SUCCESSOR_OF 等）と退役 / 合併 / 分割した Theme の narrative（A1 の P7-A1-DEF-02 と一緒に） |
| P7-A2-DEF-04 | Theme の limitation（DATA_GAP 等）・metadata（LABEL・TAXONOMY）・mapping の投影 |
| P7-A2-DEF-05 | upstream の dereference（現在の状態で PIT ではない。lookup を渡さず NOT_CHECKED のまま） |
| P7-A2-DEF-06 | 未審査の文脈の lane（B3 / B5C / B4 / B6） |
| P7-A2-DEF-07 | A1 の token 形式に合わない STATEMENT の ref id（producer が現れたとき。今は `REF_NOT_PROJECTABLE`） |
| P7-A2-DEF-08 | P4 の Fact / Context / Internals・DNA の `rule_ref` |

current-authority-only の監査（§25 の指示）: 使った API はすべて PIT で再構成できる（store の読み ＋ resolver の cutoff 濾過・
B2 / B1 の純関数・B5B の cutoff 濾過）。PIT で再構成できない入力（B3 / B5C の現在の提案状態・B6 の review 状態・B7 の journal・
upstream の dereference）は snapshot に入れない。

## 26. A3 への引き継ぎ

A3（synthesis engine）は `NarrativeInputSnapshot` だけを入力にし、Phase 6 を読まない（A3 の module は Phase 6 の import を認可されて
いない。認可は `pit_assembler` だけ）。A3 の義務:

1. subject ごとに `THEME_REVIEWED_STATE` を作る（snapshot の Theme は全部 ACCEPTED）。
2. `input_digest` に `snapshot_id`、`knowledge_pins` に `reader_versions` を使う（A1 の形式にそのまま合う。test で A1 の synthesis を
   組めることを確認済み）。
3. OBSERVED_FACT は `OBSERVATIONAL_RECORD` の source だけ。`SOURCE_CONTENT` は解釈（EVIDENCE_ATTACHED）としてだけ引用する。
4. 支持と反証が並ぶ Theme には CONTESTED_EVIDENCE、確度が仮説の機構には MECHANISM_HYPOTHESIZED、INVALIDATES の attachment には
   INVALIDATING_EVIDENCE_ATTACHED と条件の記録を作る（A1 が強制する）。flag（NO_VISIBLE_EVIDENCE・SINGLE_SOURCE・STALE）から
   不確実性 code を導く。
5. relation は snapshot の `relations` だけ（SOURCE_ASSERTED は SOURCE_ASSERTED_RELATION）。THEME_STATE では relation の claim を
   作らない。
6. `changes` が None なら CHANGE の claim を作らない（「変化なし」と言わない）。空 tuple なら変化なし。
7. 順位・主役・勝者・受益者・確信度・予測を作らない。文章・描画は A4。
