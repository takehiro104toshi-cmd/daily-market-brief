# PHASE 13 — A4b: OBSIDIAN PROJECTION EXPORT（filesystem ・vault への版の公開 ・private な証拠 ・2 つの writer lock）

P13-A4b は、A3 の検証済みの Review State Memory の generation を、A4a1 の後継の純粋な契約（`projection_contract.py`）に従って人が用意した
Obsidian の vault の `generated/` に counts-only の版として公開する filesystem の層である。合成の一時 root ・合成の vault だけで試験した
（本物の private な root ・vault には触れない）。network ・資格情報 ・scheduler ・公開の面（Pages ・PWA ・Morning Brief）・LLM は無い。
本記録は P13-A5（Windows の実機の検証）を承認しない。B-track は HOLD ・P14 は未着手。

| 項目 | 値 |
|---|---|
| gate ・anchor | `P13-A4b` ・`P13_A4A1` ＝ `5181f59e6c639d72eeba37067fa66a4d82d27a38`（直前に受理した HEAD） |
| runtime | `src/intelligence/market_memory/projection_store.py`（A4b で filesystem の I/O を持つ唯一の module）・`src/intelligence/market_memory/projection_build.py`（orchestration だけ ・filesystem の呼び出しは無い） |
| 凍結の pin | A4a1 の `projection_contract.py`（`P13_A4A1`）・A4a の `memory_projection.py`（`P13_A4A`）・A3 の 3 file（`P13_A3` ＝ `12dcfb2143527ca44a3e55afa7a2daa9bab2c33d`）・A2a（`P13_A2A` ＝ `12de956637bb1df5fcff8846ba9d7fcb606421a3`）・A1（`P13_A1` ＝ `ccfc8e57885fabc5936a39034a9e816c66b2fbbc`）を HEAD ・index ・作業木で pin する |
| 消費する契約 | A4a1 の後継だけ（A4b の 2 file は 0.1.0 の model を import しない ・呼ばない ・名前も書かない）。A3 は公開の API（`open_memory_store` ・`read_publication` ・`read_generation` ・`initialize_memory_root`）と公開の定数だけ |
| 版 | lock `p13_projection_lock:0.1.0` ・composition root の目印 `p13_private_root:0.1.0` ・vault の目印 `p13_vault_root:0.1.0` ・走査 `p13_projection_scan:0.1.0` ・走査の規則 `p13_projection_scan_rules:0.1.0` ・source の読み `p13_projection_source_read:0.1.0` ・失敗 `p13_projection_failure:0.1.0`（note ・規則 ・pointer ・manifest ・binding ・intent ・完了は A4a1 の 0.2.0） |

## 1. composition root（Option C）と所有

```
<private_root>/                 明示の初期化 initialize_private_root だけが作る（既存 ・空でない root は拒む ・途中の失敗は残す）
  .p13-private-root             目印（schema の version と root の class だけ ・path ・時刻 ・host は無い）
  memory/                       A3 の memory root（A3 の initialize_memory_root が作る ・A3 だけが書く ・A4b は読みも A3 の公開の API だけ）
  projection/                   A4b だけが書く
    bundles/<intent digest>/    intent.json ・public_export.json ・binding.json ・scan.json ・source.json（1 回の rename で現れる）
    bindings/<binding digest>/  binding.json ・scan.json ・source.json（公開が同じ時の追加の private な binding）
    completions/<digest>.json   完了の record
    failures/<digest>.json      FAILED の証拠
    staging/                    作業中の bundle（bundle.<d>.partial ・binding.<d>.partial）・record の一時 file（completion.<d>.tmp ・failure.<d>.tmp）
    locks/export.lock           private な writer lock
```

- 開く時と全ての書き込みの前に: 2 つの root の identity（`st_dev` ・`st_ino`）・目印の完全一致 ・最上位の entry の完全一致（目印 ・`memory` ・
  `projection`）・`projection/` の layout の完全一致 ・全ての祖先が symlink ／ junction ／ reparse point でない実在の directory であること。
- composition root ・vault ・呼び出し側が渡した保護の root ・この code の repository は互いに重ならない（文字の形 ・realpath ・file の
  identity の祖先 ↔ 自身。最善の努力 ・TOCTOU ・別名は P13-A5）。`PROJECTION_ROOT` ・`VAULT_ROOT` ・`CODE_REPOSITORY` は予約した label。
- A3 の store は A4b の `projection/` と vault を保護の root として渡して開く（A3 の検査で memory root がそれらと重ならないことも確かめる）。
- A3 の root の重複の検査は A3 の private な helper を import せず A4b に複製した（A3 の許しを広げない）。A3 の公開の定数（同期の名前 ・目印 ・
  mode）は再利用する。

## 2. vault の構造（人の目印 ・`generated/` の中だけ）

```
<vault>/
  .p13-vault-root               人が置く目印（exact byte ・vault_root_marker_bytes ・code は作らない ・照合するだけ）
  .obsidian/                    人の設定（core-plugins.json ・community-plugins.json ・app.json の 3 つの有界の読みだけ）
  generated/                    人が作る（A4b は vault の中でここ以外に作らない ・書かない）
    p13-memory.md               pointer（一時 file の os.replace だけで替える）
    p13pvn_<24>/                不変の版（決して移さない ・上書きしない ・archive しない ・消さない）
    .p13-staging/               開いた intent の staging（p13pvn_<24>/）と pointer の一時 file（p13-memory.<export digest>.tmp）
    .p13-interrupted/           人の明示の保存（p13pvn_<24>.<NNN>.interrupted ・中身は大きさだけを数える）
    .p13-export.lock            vault の writer lock
```

- **人の note は読まない ・一覧しない**: vault の root は一覧しない。読むのは目印と 3 つの設定 file だけ、lstat は決まった名前だけ（`.git` ・
  同期の目印 ・`.obsidian` ・`generated`）。`workspace.json` ・`plugins/*/data.json` は読まない。
- `generated/` の未知の entry（Obsidian が作った note ・OS の metadata ・同期の競合の複製 ・大小だけ違う名前 ・ASCII 以外の名前）・symlink ・
  hard link（`st_nlink` が 1 でない file）は fail closed（UNKNOWN_ENTRY ／ UNSAFE_ENTRY）。
- **拒む vault**: 祖先 ・vault の root の `.git`（git の作業木）・既知の同期 folder の名前 ・祖先 ／ root の同期の目印 ・祖先の `.obsidian`
  （入れ子の vault）・Obsidian の同期 ／ 公開の core plugin ・既知の note を書き換える ／ 外へ送る ／ AI の community plugin ・
  `alwaysUpdateLinks` が真。設定 file が無い ・読めない ・JSON でない ・形が違う ・大き過ぎる ・symlink なら PLUGIN_STATE_UNVERIFIED で拒む。
  **検出は網羅ではない**（未知の同期 ・後からの同期 ・一覧に無い plugin は防げない ・plugin の id は暫定で P13-A5 で実物と照らす）。
- **bare な note の名前の衝突（v1 の限界）**: 生成した link は A4a1 の文法で `[[p13pvn_<24>]]` ・`[[p13pvn_<24>-s001]]` の bare な名前だけ
  （folder を含む link は禁止の形）。`generated/` の中の名前は内容から導いた label で一意だが、vault の他の場所に同じ名前の note が在ると
  Obsidian がどちらを開くかは Obsidian の振る舞い（P13-A5 で検証）。A4b は人の note を読まないので衝突を検査しない。**衝突の無い
  Obsidian の navigation は主張しない**。運用の規則: 生成した note を vault の他の場所へ複製しない（違反の影響は navigation だけで、
  生成した byte ・証拠 ・分類は変わらない）。

## 3. A3 の VERIFIED の source の読み（同じ lock の下の同じ操作）

1. 呼び出し側は完全な generation digest と source の manifest digest を明示する（既定 ・「最新」の選択は無い ・入力の誤りは例外）。
2. 2 つの writer lock を取った後に `open_memory_store` → `read_publication` が `ReadStatus.VERIFIED` ・`PUBLICATION_VERIFIED` で、
   **v1 では要求した generation ／ manifest が A3 の検証済みの公開と一致する**こと（公開を暗黙の選択に使わない ・一致だけを要する ・
   違えば SOURCE_NOT_PUBLISHED_GENERATION）→ `read_generation` が VERIFIED ・`GENERATION_VERIFIED` ・同じ 2 つの digest → A3 の staging が
   無いこと（SOURCE_STAGING_PRESENT）。
3. `build_projection_target(verified, generation_digest=…, manifest_digest=…)` が byte から再び検証し、public な版（公開の欄だけ）と
   private な `PrivateBinding` を作る。
4. **証明の分担**: A4a1 の binding の `source_attestation` は A4a1 が証明しない範囲（`A4A1_RECHECKED_RECORD_BYTES_STORE_READ_NOT_ATTESTED`）
   のまま変えない。A4b は自分の private な証拠 `source.json`（`SOURCE_READ_ATTESTATION` ＝
   `A4B_A3_PUBLIC_READ_VERIFIED_UNDER_EXPORT_LOCKS_NOT_ATOMIC_WITH_A3_WRITES`）に、lock の下の同じ操作で A3 の公開の API が VERIFIED を返した
   ことと binding の完全な digest を記録する。A3 の writer lock は取らないので A3 の書き込みとの不可分ではない（A3 の generation は不変）。
5. A3 の store の root ・generation の byte は A4b の store が読まない ・書かない（試験で記録した操作に memory の中は無い）。

## 4. 公開の取引（A4a1 の状態機械をそのまま実行する）

各回: 観測（下の I5 の検証）→ `classify_publication(observation, target=…)` → 次の 1 つの遷移だけを書く。

| A4a1 の action | A4b の書き込み | 書いた後に期待する状態 |
|---|---|---|
| PREPARE_INTENT（回復が要らない時だけ） | `staging/bundle.<intent>.partial/` に 5 record（public な manifest ・binding ・intent は A4a1 の byte ・scan.json ・source.json）→ 読み戻し → 1 回の rename で `bundles/<intent>/` | INTENT_PREPARED |
| STAGE_VERSION | `.p13-staging/<label>/` に全ての note を排他の作成 ・fsync ・読み戻し | STAGED_VERIFIED |
| CONTINUE_STAGING | 足りない note だけを排他の作成（在る file の集合が `existing_notes` と完全一致の時だけ ・在る file は触らない） | STAGED_VERIFIED |
| MOVE_STAGED_TO_VERSION | 置き換えない移動（POSIX は排他の予約 mkdir の後の rename ・在れば拒む） | VERSION_VERIFIED |
| REPLACE_POINTER | 一時 file を作り読み戻し → pointer が `expected_pointer` のままを確かめ → `os.replace` → 読み戻し | POINTER_SWITCHED |
| RECORD_COMPLETION | `staging/completion.<d>.tmp` → 読み戻し → 不在を確かめた 1 回の rename | NO_CHANGE（記録済み） |
| RECORD_PRIVATE_BINDING | `bindings/<binding>/`（binding ・scan ・source）を同じ方法で | NO_CHANGE（記録済み） |

- 自動の遷移は書く直前に `check_recovery_proposal` を通す。PREPARE_INTENT ／ RECORD_PRIVATE_BINDING は回復の適格が NOT_REQUIRED で提案が
  ちょうどその遷移の時だけ。
- 書く前に遷移の後の観測を純粋に予測して分類し、期待の状態でなければ（FAIL_CLOSED を含む）書かない。書いた後は **disk から観測し直し、
  予測した観測と byte で完全一致しなければ FAILED**（記憶の中の結果を仮定しない）。
- **NO_CHANGE**: 公開が同じで新しい private な binding が未記録なら RECORD_PRIVATE_BINDING を書いてから NO_CHANGE。記録できなければ
  **成功の NO_CHANGE を返さない**（FAILED ・次の回で記録する）。記録の後は lock の作成と解放以外は何も書かない。
- 前の有効な版 ・証拠を消す ・移す ・上書きする ・archive する操作は無い。結果は固定の code ・public な digest ・label だけ。

## 5. 2 つの writer lock

- private（`projection/locks/export.lock`）→ vault（`generated/.p13-export.lock`）の順に O_CREAT|O_EXCL ・binary ・symlink を辿らない ・
  mode 0600。byte は schema ・範囲（`PRIVATE_PROJECTION` ／ `VAULT_EXPORT`）・操作（`PUBLISH` ／ `PRESERVE`）だけ（pid ・時刻 ・host ・user ・
  path は無い）。所有は作成した file の identity と byte の完全一致で、2 つを独立に確かめる。
- 全ての書き込みの前に両方の所有と 2 つの root を確かめ直す（失敗は LOCK_OWNERSHIP_UNVERIFIED ・FAILED）。解放は vault → private の順に
  それぞれ所有を検証した時だけ消す（検証できなければ残す ・消せなければ LOCK_RELEASE_FAILED）。
- 2 つ目が取れなければ（VAULT_LOCK_PRESENT）所有を検証した 1 つ目だけを解放する。stale の推定 ・年齢 ・奪取 ・自動の除去は無い。残った
  lock は人の手順（**設計だけ ・実行できる除去は無い** ・P13-A5 で検証）でだけ除く。
- 2 つの private な root が同じ vault を使う時: 同時なら vault の lock が直列にする（負けた側は書かずに拒む）。順番なら他の root の版 ・
  pointer ・staging を採らない（UNREFERENCED_VERSION ／ POINTER_WITHOUT_EVIDENCE ／ ORPHAN_STAGING の HOLD）。

## 6. 回復（A4a1 の契約の action だけ ・新しい回復の action は無い）

| 観測 | A4a1 の分類 | A4b |
|---|---|---|
| byte 一致の部分の staging（空を含む） | STAGING_PARTIAL_VERIFIED | 自動の CONTINUE_STAGING（足りない file の排他の作成だけ） |
| 完全な staging ・検証した版 ・切り替えた pointer | STAGED_VERIFIED ・VERSION_VERIFIED ・POINTER_SWITCHED | 自動の MOVE ・REPLACE ・COMPLETE |
| 対象の byte の厳密な接頭で切れた note | STAGING_TORN | HELD（EXPLICIT_PRESERVATION_REQUIRED）→ 人の明示の `preserve_projection_staging(PRESERVE_STAGING)` |
| 完全な staging ＋ 開いた intent の空の版の予約（POSIX の移動の途中） | VERSION_RESERVED_EMPTY | HELD → 明示の `PRESERVE_EMPTY_RESERVATION`（空 ・未公開 ・pointer の外 ・開いた intent の label を A4a1 が証明 ・A4b は移す直前に空を確かめる） |
| 改竄 ・未知の名前 ・区別できない staging | FAIL_CLOSED（STAGING_TAMPERED ・STAGING_FOREIGN_ENTRY ・STAGING_UNVERIFIED） | HOLD（保存の対象でもない） |
| pointer ・公開した版の改竄 ／ 削除 | FAIL_CLOSED（POINTER_INVALID ・POINTER_MISSING ・VERSION_UNVERIFIED ・PREVIOUS_VERSION_MISSING） | HOLD（修復 ・再公開はしない） |
| 切れた ・壊れた commit 済みの証拠 | FAIL_CLOSED（RECORD_CORRUPT ・EVIDENCE_DIGEST_MISMATCH ・MANIFEST_MISSING） | HOLD |

- 明示の保存は `check_preservation_proposal` が認めた 1 つだけを、2 つの lock の下で `.p13-interrupted/` の空いた番号へ置き換えない移動で
  移す（消さない ・自動では呼ばれない ・公開は続けない ・保存の後の観測が予測と byte で一致することを確かめる）。前の有効な版は決して対象に
  ならない。
- **I5（観測の外の管理の object）**: bundle ・binding の bundle ・失敗の record は分類の前に厳密に検証する（record の集合 ・正準の byte ・
  digest と名前 ・intent → manifest → binding の結び付き ・scan の完全な被覆 ・source の読みと binding の一致 ・重複）。作業中の残りは、次の
  遷移が同じ名前で書く決定論の byte と完全一致する時だけ続きに使い、それ以外は書かない回も含めて HOLD（EVIDENCE_STAGING_RESIDUE ／
  VAULT_STAGING_RESIDUE ／ STAGING_CONFLICT）。
- **FAILED の証拠の 3 つの区別**:

  | 観測 | 扱い |
  |---|---|
  | 確定した `failures/<digest>.json`（鍵の完全一致 ・固定の段 ・安全な code ・正準の byte ・digest と名前の一致） | 検証した履歴として保つ（消さない ・上書きしない ・壊れていれば FAILURE_EVIDENCE_INVALID の HOLD） |
  | 今の lock の下の操作が作った一時 file（`write_record` の中だけ ・作成した file の identity と byte を確定の直前に確かめる） | 確かめられた時だけ 1 回の rename で確定（替わっていれば STAGING_CONFLICT ・rename しない ・残す） |
  | 残った ・曖昧な `staging/failure.<digest>.tmp`（途中で切れた ・書き終えたが確定していない ・未知の byte ・byte が同じものも） | **FAIL CLOSED**: 公開 ・明示の保存は EVIDENCE_STAGING_RESIDUE の HOLD ・新しい FAILED の証拠もその横には書かない（`FAILURE_NOT_RECORDED`）・続きに使わない ・消さない ・移さない ・分類を迂回しない（結果の `failure_residue` に数える） |

  確定の rename の後に止まった時は記録が確定していても確かめられないので `FAILURE_NOT_RECORDED` を返す（記録済みとは言わない）。残りは
  記録した人の手順（設計だけ）でだけ除く。
- **限界（人の手順 ・設計だけ）**: 管理の file（lock ・private な bundle の record ・完了の一時 file ・pointer の一時 file）を作ってから
  全て書く前に止まると、決定論の byte と違う残りが残る。A4a1 にこれを移す action は無く、A4b は新しい回復の action を足さないので HOLD の
  まま残り、記録した人の手順で root の外へ移すまで続かない（vault の note の中断は CONTINUE か明示の保存で収束する）。
- **限界（開いた intent の対象）**: 開いた intent の対象と違う generation を要求すると TARGET_CONFLICTS_WITH_OPEN_INTENT の HOLD。A3 の公開が
  先へ進んで元の generation を要求できない時は、A4a1 の中止の record（`abort_for`）を書く action が無いので HOLD のまま残る（中止は将来の
  別の gate）。

## 7. private な証拠

- **bundle**: 1 回の rename で全て揃って現れる（intent と manifest ・binding ・走査 ・source の読みが別々に在る状態は無い）。完了 ・失敗の
  record は一時 file の後に不在を確かめた 1 回の rename（A3 の試行の証拠と同じ ・空の予約を証拠として残さない ・TOCTOU は残る）。
- **走査の証拠（scan.json ・必須）**（P12.5-A0 §6.3「検査した pattern と件数」）:

  | 欄 | 内容 |
  |---|---|
  | `scan_rules_version` ・`scan_rules_digest` | `p13_projection_scan_rules:0.1.0` と、規則の version ・A4a1 の規則の version ・承認した全ての pattern の識別子と正規表現（表の順）の domain digest（`p13.projection_scan_rules.v1`） |
  | `projection_rules_version` ・`procedure` | A4a1 の `p13_projection_rules:0.2.0` ・`A4A1_VALIDATE_PUBLIC_NOTE_BYTES_PRIVATE_SHAPES_GRAMMAR_POSITIVE_HEX` |
  | `patterns` | 承認した全ての 18 の pattern の識別子（表の順） |
  | `pattern_counts` | pattern ごとの検出の件数（全ての被覆した file の当たりの数の和） |
  | `files` ・`file_count` | 版の全ての note と pointer の名前 ・長さ ・sha256 ・その file の検出の件数（出力の全ての file の digest の被覆） |
  | `detected_count` ・`result` | 件数の和と決定論の結果（0 なら PASSED ・それ以外は DETECTED ＝ PASSED の record は決して作らない） |
  | `public_version_digest` ・`public_export_digest` ・`authority_class` | public な identity だけ |

  当たった文字列 ・正規表現の出力 ・path ・資格情報 ・telemetry は無い。決定論の identity は `scan_record_digest`（`p13.projection_scan.v1`）。
  **pattern の表**: 承認した表は凍結の A4a の表で、A4a1 が再利用する走査器 `scan_private_shapes` がそれを使う。A4b は凍結の module を import
  しないので `SCAN_PATTERNS` に写しを持ち、boundary の guard が凍結の表との完全一致（識別子 ・正規表現 ・順）と規則の digest の再計算を
  pin する。実行の時は file ごとに写しの当たりの集合と承認した走査器の結果を照らし、違えば SCAN_RULES_DRIFT で止まる（不一致の写しは
  使わない）。1 つでも当たれば PASSED の record を作らず、FAILED の証拠（段 SCAN ・当たった pattern の識別子だけ）を残す。全ての file は
  A4a1 の `validate_public_note` も通る。**毎回の観測で走査の証拠を完全に再検証する**: 規則の version ／ digest の今の表との一致 ・全ての
  識別子と順 ・全ての件数 0 ・manifest と pointer の完全な被覆 ・PASSED ・余分な欄が無いこと（1 つでも違えば SCAN_EVIDENCE_INVALID の HOLD）。
- **source の読みの証拠（source.json）**: binding の digest ・private な generation ／ manifest の完全な digest ・A3 が返した状態と code ・
  要求が公開と一致したこと ・証明の範囲（3 節）。
- **FAILED の証拠（failures/）**: 2 つの lock の所有と composition root を確かめて書ける時だけ（vault には触れない）。操作 ・固定の段 ・code ・
  安全な detail（大文字の code の形だけ）・要求した 2 つの digest ・public な export の digest。例外の文 ・時刻 ・path は無いので同じ失敗は
  同じ byte（重複しない）。lock ・root ・容量 ・空き容量が確かめられない時 ・残った FAILED の一時 file が在る時は書かずに
  `FAILURE_NOT_RECORDED` を返す（6 節の 3 つの区別）。
- 証拠は消さない ・上書きしない（同じ byte の再記録は `EVIDENCE_ALREADY_RECORDED` ・違えば EVIDENCE_CONFLICT）。

## 8. 容量

- 暫定の最大: 保持する版 64 ・vault の export の領域 256 MiB ・private な証拠 64 MiB ・A4a1 の観測の object 4096 ・volume ごとの空きの余白
  512 MiB。呼び出し側は狭めるだけ（緩めれば LIMIT_LOOSENED）。
- 勘定: 観測した実際の合計（版 ・staging ・中断の保存 ・lock ・pointer ・全ての証拠 ・作業中の残り ・file と directory を 4 KiB の単位に切り上げ）
  ＋ 遷移から取引の終わりまでの頂点（staging の directory ・label の directory ・note ・移動の予約 ・pointer の一時 file ／ bundle ・完了 ・
  失敗の予備）。object は A4a1 の数え方（folder は 1 ＋ note の数 ・証拠は 1 つずつ）で次の公開は n ＋ 5。後の段の「観測 ＋ 必要」は
  PREPARE で確かめた値を超えない。
- 空きは `shutil.disk_usage`（`_free_bytes` だけ）で、同じ volume なら 2 つの必要の和 ＋ 余白 1 つ。取れない ・形が違えば CAPACITY_UNVERIFIED
  で拒む。超えれば何も書く前に CAPACITY_EXCEEDED（履歴は消さない ・自動の掃除は無い）。

## 9. filesystem の authority（boundary の guard が pin する）

- `projection_store.py` だけが `os` ・`stat` ・`shutil` を import する（2 つ目の狭い許し ・A3 の許しは不変）。`os` の危険な呼び出しは関数で
  pin: `open`（`_create_file` ・`_read_file` ・`_fsync_directory`）・`write`（`_write_all`）・`mkdir`（`_make_directory` ・
  `_move_without_replacing`）・`rename`（`_move_without_replacing` ・`write_evidence_bundle` ・`write_record`）・`replace`（`replace_pointer`）・
  `unlink`（`_unlink_if_owned` だけ ・呼ぶのは lock の `release` だけ）・`stat`（`_identities`）・`listdir`（`_entries` ・1 つの directory ・上限）。
  `shutil` は `disk_usage` だけ（`_free_bytes`）。一般の削除 ・rmdir ・rmtree ・truncate ・shell ・無制限の走査は無い。
- `projection_build.py` は `os` ・`stat` ・`shutil` ・`pathlib` ・`io` を持たず、store と lock の公開の method ・A3 の公開の読み ・A4a1 の公開の面
  （A4a1 が承認した再利用の走査器 `scan_private_shapes` を含む）だけを使う。stdlib の `re` は走査の写しの compile だけ。

## 10. 試験（合成の値だけ）

- `test_market_memory_projection_store.py`: 明示の初期化 ・途中の失敗を残す ・root の形 ・人の目印 ／ `.obsidian` ／ `generated` ・plugin の
  状態 ・git ／ 同期 ／ 入れ子の vault ・重なり ・symlink ／ reparse ・2 つの lock（順序 ・2 つ目の失敗 ・所有の喪失 ・解放の失敗 ・2 つの
  private な root の thread の競合）・未知 ／ hard link ／ 大小の別名 ・中断の保存は大きさだけ ・bundle ／ record ／ staging ／ 移動 ／ pointer ／
  保存の primitive ・FAILED の一時 file を採らず自分が作って所有を確かめた一時 file だけを確定すること ・空き容量 ・記録した操作が
  `projection/` と `generated/` の外に書かず人の note を一覧しないこと ・A3 の root に触れないこと。
- `test_market_memory_projection_build.py`: 最初 ／ 2 つ目 ／ 3 つ目の公開と前の版の byte ・mtime の保持 ・vault の byte に private な digest の
  16 hex の窓が無いこと ・NO_CHANGE の再生 ・公開が同じ generation の binding の記録と記録の失敗 ・root ／ 作業の directory ／ timezone を変えた
  byte 一致の再生 ・A3 の handoff ・入力 ・**全ての書き込みの操作の前 ／ 後 ／ 途中で切れた失敗と回復の中の 2 つ目の失敗**（前の版 ・証拠は
  不変 ・参照と byte 一致に収束 ・明示の保存 ・人の手順の模擬）・部分の継続 ・切れ ／ 改竄 ／ 未知 ・空の予約 ・作業中の残り ・pointer の
  一時 file ・lock の所有の喪失 ・2 つの private な root ・容量の境界（1 つ下 ・ちょうど ・1 つ上）・中断の保存の勘定 ・空き容量の不明 ／ 失敗 ・
  改竄の HOLD ・FAILED の証拠 ・人の file の隔離 ・結果に位置 ／ private な digest が無いこと ・**R1**: 承認した全ての pattern の識別子と件数 ・
  規則の digest の凍結の表からの再計算 ・被覆 ・固定の identity ・欠けた ／ 変えた ／ 並べ替えた識別子 ・0 でない ／ 偽の件数 ・欠けた ／ 変えた
  被覆 ・規則の version ／ digest の drift ・結果 ・余分な欄 ・写しと承認した走査器の不一致 ・当たった時に PASSED を作らないこと ・**R2**: 確定した
  FAILED の証拠の保持 ・一時 file の作成の前 ／ 書く途中 ／ 確定の前 ／ 確定の後の中断 ・未知 ／ byte が同じ残りを採らないこと ・残りが在る間の
  公開 ／ 保存 ／ 新しい失敗の記録の停止 ・履歴を掃除しないこと。

## 11. Windows ・P13-A5 の限界（未検証 ・主張しない）

NTFS の rename ・`os.replace` の共有違反（Obsidian ・indexer ・Defender）・directory の fsync が無効 ・ACL の privacy ・junction ／ mount point ／
OneDrive の placeholder の reparse ・8.3 の短い名前 ・大小を区別しない volume ・ADS ・末尾の点 ／ 空白 ・MAX_PATH ・`st_nlink` ・quota の下の
`shutil.disk_usage` ・Obsidian の dot folder の扱いと link の解決 ・plugin の実物の id ・中断の実機の試験 ・残った lock の人の手順。検査と
操作の間の TOCTOU は stdlib では閉じない。実際の vault への公開 ・公開した出力の人による編集 ／ 削除の回復（HOLD のまま）は無い。公開する
件数 ・日付そのものからの推論は防がない（A4a1 の限界）。本記録は A4b の commit ・P13-A5 を承認しない。
