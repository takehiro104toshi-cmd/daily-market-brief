# PHASE 13 — A4a: PURE PROJECTION MODEL（counts-only ・決定論 ・fail closed ・I/O 無し）

Review State Memory の検証済みの generation から、Obsidian 向けの counts-only の Markdown の版を **純粋に** 作り、版の公開の状態を
観測した byte だけから分類して次の 1 つの遷移を **提案するだけ** の model（P13-A4a）。filesystem ・vault ・network ・process ・
時計 ・環境 ・資格情報 ・scheduler には触れない。composition root の初期化 ・vault の読み書き ・lock ・stage ／ 公開 ・pointer の置換 ・
中断からの回復の実行は全て P13-A4b（HOLD）。P13-A1 の model（`P13_A1` ＝ `ccfc8e57885fabc5936a39034a9e816c66b2fbbc`）・P13-A2a の adapter
（`P13_A2A` ＝ `12de956637bb1df5fcff8846ba9d7fcb606421a3`）・P13-A3 の Memory Store の 3 file（`P13_A3` ＝
`12dcfb2143527ca44a3e55afa7a2daa9bab2c33d`）は変えない（blob を HEAD ・index ・作業木で pin）。Knowledge Graph ・Evidence Memory ・
AI の叙述は無い。B-track は HOLD ・P14 は未着手。本記録は A4b の実装を承認しない。

| 項目 | 値 |
|---|---|
| runtime（登録 ・認可: gate `P13-A4a` ・anchor ＝ Market Brain の roadmap の記録の commit `5e5f015ecebf64116f9c1721c36d9d41fa9dc1c7`） | `src/intelligence/market_memory/memory_projection.py` |
| import | stdlib `__future__` ・`dataclasses` ・`enum` ・`json` ・`re` ・`typing` と、相対の `.canonical` ・`.memory_generation` ・`.review_state_change` ・`.review_state_sample` だけ（`memory_store` ・`memory_build` ・adapter ・凍結の package は import しない ・P10 の importer の許可は増やさない） |
| 版 | 投影 `p13_memory_projection:0.1.0` ・規則 `p13_projection_rules:0.1.0` ・export の manifest `p13_projection_manifest:0.1.0` ・pointer `p13_projection_pointer:0.1.0` ・intent `p13_projection_intent:0.1.0` ・完了 `p13_projection_completion:0.1.0` ・中止 `p13_projection_abort:0.1.0` |
| 本番 | legacy の production ・P4 の閉包には入らない（`runtime_closure` の外） |

## 1. D1: composition root（Option C）と A0 の証拠の要件の解釈

将来の private な composition root は次の形とする（A4a は作らない ・読まない）:

```
<private_root>/
  .p13-private-root
  memory/        … P13-A3 の Memory Store（不変 ・A3 の layout のまま）
  projection/    … A4 の証拠（export の manifest ・走査 ・intent ・完了 ・中止 ・lock）
```

**決定（記録）**: P13-A0 の「memory root の export の証拠」の要件は、証拠が **private な composition root の中に在り、封じた A3 の子の
store（`memory/`）の外**（`projection/`）に在ることと解釈する。A3 の厳密な layout の検査（未知の entry を拒む）は変えない。A0 ・A3 の
契約は改めない。A4a は root の作成 ・filesystem の実装を含まない。

## 2. 入力: 明示の完全な source の identity（D10）と A4b への引き渡しの契約

- `build_projection_input(verified, *, generation_digest, manifest_digest)`: 完全な 64 hex の generation digest と source の manifest
  digest が **必須**（既定 ・「最新」の暗黙の選択は無い ・略記は拒む）。
- A4a は呼び出し側の `VerifiedGeneration` を **信用しない**: その object から record の byte を作り直し、A3 の
  `verify_generation_records` で純粋に再検証し、明示の digest と一致しなければ fail closed（`SOURCE_DIGEST_MISMATCH` ／
  `SOURCE_UNVERIFIED` ／ `SCHEMA_UNSUPPORTED`）。以後は再検証で作り直した model だけを使う。
- ただしこの再検証は **A3 の store から実際に読んだことの証明ではない**。`SOURCE_ATTESTATION` ＝
  `A4A_RECHECKED_RECORD_BYTES_STORE_READ_NOT_ATTESTED` を入力に記録する（dataclass が在るだけで source の検証とはみなさない）。
- **引き渡しの契約（A4b）**: A4b は同じ呼び出しの中で A3 の公開の読み `MemoryStore.read_generation(<明示の完全な digest>)` を行い、
  `ReadStatus.VERIFIED` の結果の `verified` と、その完全な generation digest ・manifest digest だけを A4a に渡す。publication.json を
  黙って追う ・一覧から選ぶ ・時刻で選ぶことはしない。

## 3. counts-only の Markdown（D3 ・D4）

版は 1 つの folder（名前 ＝ 版の label `p13prj_<24 hex>`）に flat に置く。note の basename は vault の中で一意（版の label を前置）:

| note | 名前 | 内容 |
|---|---|---|
| 版の index | `p13prj_<24>.md` | 投影 ・規則 ・generation ・source の manifest の完全な digest ・generation の label ・adapter ／ view の schema の version ・標本 ／ 区間の件数 ・最初 ／ 最後の標本の cutoff の日 ・標本 ／ 区間の固定の link |
| 標本 | `p13prj_<24>-p13smp_<24>.md` | 見直しの件数 ・個人の安全な投影の 13 の件数 ・P9 の件数 ・承認した分類ごとの件数（0 で埋める）・標本の cutoff の日（内容は標本だけで決まる） |
| 区間 | `p13prj_<24>-p13int_<24>.md` | 隣接する 2 つの標本の端点の差の件数（record の種類 × 変化の種類 ・構造の欄の名前ごと）・2 つの cutoff の日 |
| pointer | `p13-memory.md`（版の folder の外） | 投影 ・export の完全な digest と、版の index への 1 つの固定の link |

- **D3 COUNTS ONLY**: 項目ごとの id（root ・revision ・link）・発行体 ・擬名の hash（項目ごとの変化の digest ・`p13chg_` を含む）・source の生の
  内容 ・著者 ・note ・資格情報 ・source の位置は出さない。A4a は標本の `entries` ・変化の前後の値を読まない（変化は欄の **名前** だけを数える）。
  出す digest は標本 ・generation ・source の manifest ・投影 ・export の **集合の** 完全な digest だけ。人が宣言した窓
  `review_lookahead_days` は件数ではないので出さない。
- **分類**: 承認した構造の分類の code は凍結の P9 の enum の値と完全一致（`APPROVED_CATEGORY_CODES` ・test が凍結の enum と照らす）。
  A1 の model が受ける未知の code（例えば承認していない状態）は投影で `CATEGORY_UNAPPROVED` として fail closed。件数は 0 〜 9999
  （それを超えれば `COUNT_OUT_OF_RANGE` ・5 桁の数を出さない）。
- **D4 DATES ONLY**: 書き出す Markdown に瞬間（cutoff の `at`）は無い。日だけを `sample_cutoff_date` などの名前で出し、固定の文で
  「標本の cutoff の日は標本を取った区切りの日であり、source の known_at ではない」と述べる（標本化を source の可用の時刻と偽らない）。
  区間は「端点の差の件数だけ ・遷移の時刻 ／ 回数ではない ・端点の一致は変化の不在の証明ではない」と述べる。
- 許すもの: 構造の件数 ・承認した分類の code ・日 ・schema ／ 規則の version ・完全な digest ・固定の説明の文 ・生成した note への固定の link。
- 禁じるもの: authority の生の id ・発行体 ／ 証券の詳細 ・自由な文（人 ／ model）・正確な時刻 ・生の news ・外部の URL ・HTML ・埋め込み ・
  plugin が実行する式（Dataview の inline ・Templater ・code block）・private な位置 ・資格情報。

## 4. 検証の 2 つの層（`validate_note`）

1. **byte の規則**: UTF-8 ・BOM 無し ・LF だけ（CR ・tab ・制御文字 ・幅の無い文字 ・方向の制御は拒む）・末尾は改行 1 つ ・上限の大きさ。
2. **private の形の走査**（`PRIVATE_SHAPE_PATTERNS` ・全文）: drive の位置 ・逆斜線 ・斜線（位置 ・URL ・閉じ tag）・時刻つきの瞬間 ・時刻 ・
   5 桁以上の数 ・凍結の id の接頭辞 ・著者の接頭辞 ・API の鍵の header ・provider の名前 ・鍵 ／ 合言葉の語 ・SID ・URL の scheme ・HTML の tag ／
   実体 ・埋め込み ・code ・template ／ 式 ・comment ／ 脚注。凍結の guard の形を文字の class で表す（runtime の source に private の文字列
   そのものは置かない ・凍結の guard の走査は runtime の全文にそのまま掛かる）。
3. **行の文法**: frontmatter は note の種類ごとの鍵の列の完全一致と値の形（固定の version ・種類 ・完全な digest）。本文の行は固定の行 ・
   表の行（欄の名前の allowlist ・承認した code ・0 〜 9999 の整数 ・正しい日 ・真偽 ・完全な digest ・P13 の label ・version の形の cell だけ）・
   固定の形の link の項目 ・空行だけ。それ以外の行は `NOTE_INVALID`。

## 5. identity（D10 ・略記は label だけ）

- **projection digest**（domain `p13.memory_projection_plan.v1`）: 投影の schema ・規則の version ・source の generation digest ・source の
  manifest digest ・authority の class。描画の前に決まる。版の label `p13prj_` はその略記。
- **export digest**（domain `p13.memory_projection_export.v1`）: 版の folder の全 note の名前 ・長さ ・sha256（名前で sort）と計画の
  digest の manifest の正準 digest。`p13exp_` はその略記。同じ計画から別の byte が出れば `MANIFEST_CONFLICT`。
- 区間の identity（domain `p13.memory_projection_interval.v1`）は 2 つの標本の完全な digest から。intent ・完了 ・中止の record は
  それぞれの domain の digest で番地を付ける。
- 完全な digest で照合し、別の完全な digest が同じ略記を持てば `SHORT_ID_COLLISION`。record ・note は正準の byte だけ（往復の一致）。
- 出力は host ・位置 ・壁時計 ・TZ ・作業 directory に依らない（同じ入力は byte 一致）。

## 6. 版の公開（D11）と状態の分類（D6）

D11: 将来の export は **不変の版の folder** と **検証した 1 つの file の pointer** を使う。前の有効な版は **その場に残す**（archive ・
移動 ・削除 ・保持の整理は A4 に無い）。保存の増加は将来の preflight の容量の方針で抑え、上限を超えれば公開を止める（歴史を消さない）。
pointer の置換は Obsidian の表示の不可分な更新の証明ではない。

`classify_publication(observation, *, target=None)` は A4b が読んだ byte（`PublicationObservation`: pointer ・版の folder ・staging ・
manifest ・intent ・完了 ・中止）だけを分類する。I/O ・回復の実行は無い。

| 状態 | 条件 | 提案 | 回復の適格 |
|---|---|---|---|
| `FIRST_PUBLICATION` | 完了した intent も pointer も無い | 対象が在れば `PREPARE_INTENT` ・無ければ `NONE` | `NOT_REQUIRED` |
| `PUBLISHED_VERIFIED`（完了を記録した状態） | 完了した intent の 1 本の鎖 ・pointer ＝ 鎖の頭 ・全ての前の版が在り検証できる | 対象が別なら `PREPARE_INTENT` | `NOT_REQUIRED` |
| `NO_CHANGE` | 対象の export digest ＝ pointer の export digest | `NONE` | `NOT_REQUIRED` |
| `INTENT_PREPARED` | 開いた intent が 1 つ ・その版も staging も無い | 同じ対象が在れば `STAGE_VERSION` ・無ければ HOLD（`TARGET_REQUIRED_FOR_STAGING`） | 対象が在れば `AUTO_CONVERGE_ELIGIBLE` |
| `STAGED_VERIFIED` | staging が manifest と完全一致 | `MOVE_STAGED_TO_VERSION` | `AUTO_CONVERGE_ELIGIBLE` |
| `VERSION_VERIFIED` | 版の folder が完全一致 ・pointer は前の有効な版のまま | `REPLACE_POINTER`（観測した pointer の上だけで置き換える） | `AUTO_CONVERGE_ELIGIBLE` |
| `POINTER_SWITCHED` | pointer ＝ 開いた intent の版 | `RECORD_COMPLETION` | `AUTO_CONVERGE_ELIGIBLE` |
| 中止した操作 | intent に中止の record | 中止した版は残す（保持）・状態は `FIRST_PUBLICATION` ／ `PUBLISHED_VERIFIED` | `NOT_REQUIRED` |
| `FAIL_CLOSED` | 検証できない ・曖昧 ・矛盾 | `HOLD` | `HOLD_FAIL_CLOSED` |

- 自動の収束の候補は、検証済みの intent ・完全な digest で検証した object ・一意の所有と identity ・冪等な次の遷移 ・全ての前の証拠の
  保存が揃う時だけ（`check_recovery_proposal` は観測を分類し直し、提案がちょうど次の遷移の時だけ遷移を返す）。新しい intent の準備は
  回復ではない。
- 提案の action は `NONE` ・`PREPARE_INTENT` ・`STAGE_VERSION` ・`MOVE_STAGED_TO_VERSION` ・`REPLACE_POINTER` ・`RECORD_COMPLETION` ・`HOLD`
  だけ。前の有効な版を archive ・削除 ・移動する action は **存在しない**。全ての遷移は `retained_versions`（観測した全ての版）を手を触れずに
  残し、触るのは開いた intent の新しい版 ・pointer ・追加の証拠だけ。
- 新しい版を準備する間、検証した pointer は前の有効な版を指し続けてよい。pointer の置換の後も前の版は不変で読める（無ければ
  `PREVIOUS_VERSION_MISSING`）。
- **検証済みの intent が無い**: orphan の staging（`ORPHAN_STAGING`）・参照の無い版（`UNREFERENCED_VERSION`）・参照の無い manifest
  （`UNREFERENCED_MANIFEST`）・未知の object（`UNKNOWN_OBJECT`）は自動で移さない（開いた intent が無いことは移動の許可ではない）。
- **fail closed**: 壊れた pointer（`POINTER_INVALID`）・不在（`POINTER_MISSING`）・予期しない先（`POINTER_UNEXPECTED`）・証拠の無い pointer
  （`POINTER_WITHOUT_EVIDENCE`）・manifest の欠落（`MANIFEST_MISSING`）／ 矛盾（`MANIFEST_CONFLICT`）・参照の無い intent
  （`INTENT_REFERENCE_MISSING`）・完了と中止の両方（`CONTRADICTORY_INTENT`）・鎖の破れ（`INTENT_CHAIN_INVALID`）・開いた intent が 2 つ以上
  （`MULTIPLE_OPEN_INTENTS`）・番地の改竄（`EVIDENCE_DIGEST_MISMATCH`）・版の改竄（`VERSION_UNVERIFIED`）・部分の ／ 壊れた staging
  （`STAGING_UNVERIFIED`）・staging と版の両方（`AMBIGUOUS_STAGING_AND_VERSION`）・閉じた intent の staging（`STAGING_OF_CLOSED_INTENT`）・
  既知の版の再公開（`REPUBLICATION_OF_KNOWN_VERSION`）・開いた intent と違う対象（`TARGET_CONFLICTS_WITH_OPEN_INTENT`）・略記の衝突。
- intent ・完了 ・中止の record は完全性を digest で検証する（暗号の認証 ・署名ではない）。

## 7. OPEN ／ HOLD for A4b（A4a で安全を確立できない遷移）

- 部分の ／ 壊れた staging の再開（検証済みの file だけを残して続きを書く）・閉じた intent の staging の扱い（保存の場所 ・人の明示の回復）。
- prepare の中断で残った参照の無い manifest の採用。
- 既知の版への戻し（rollback ・再公開）。
- 壊れた pointer ・壊れた版の保存の手順（A3 の `interrupted/` に相当する場所 ・人の明示の呼び出し）。
- 開いた intent が 2 つ以上 ・略記の衝突の人による解決。
- 容量の上限と preflight の見積もり（超えれば公開を止める）。

## 8. 試験（合成の値だけ）

- `test_market_memory_projection.py`: 承認した分類 ＝ 凍結の P9 の enum ・明示の完全な digest ・偽の `VerifiedGeneration` の拒否 ・counts-only
  （項目の id ・発行体 ・瞬間 ・項目ごとの hash が無い）・入力の順序 ／ TZ ／ 作業 directory に依らない byte 一致 ・golden な digest ・独立の
  再計算 ・manifest ／ record の正準性と版 ・private の形 ・文法 ・分類の拒否 ・件数の上限 ・初回の公開の全ての状態 ・NO_CHANGE ・前の版の保持 ・
  順序に依らない分類 ・中断の再開 ・orphan ・pointer ・intent ・manifest の矛盾 ・略記の衝突 ・archive ／ 削除の不在 ・中止 ・安全でない回復の
  提案の拒否 ・I/O の関数を差し替えても動くこと。
- `test_market_memory_boundary.py`: 認可 ・registry の digest ・A1 ／ A2a ／ A3 の blob の pin（HEAD ・index ・作業木）・import の面 ・
  I/O ・動的実行 ・import の時の副作用の不在 ・項目 ／ 瞬間の属性を読まないこと ・公開の面 ・本記録の guard ・負の control。

## 9. A4b に残す決定（HOLD ・個別の GO を要する）

composition root の初期化 ・private な証拠の filesystem の所有 ・vault の目印の検証 ・Obsidian の plugin の検査 ・export の writer lock ・
filesystem の stage ／ verify ／ publish ・pointer の原子的な置換 ・実際の中断からの回復 ・容量の上限と preflight の見積もり ・Windows の
filesystem の保証 ・本物の Obsidian の vault への到達（合成の一時の場所だけで試す）。
