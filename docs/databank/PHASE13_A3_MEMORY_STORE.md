# PHASE 13 — A3: PRIVATE MEMORY STORE ／ REBUILD（決定論 ・fail closed ・明示の回復だけ）

Review State Memory の標本と端点の差を、明示の private な memory root に **不変の generation** として保存し、公開の pointer
`publication.json` を原子的に替える store（P13-A3）。P13-A1 の model（`P13_A1` ＝ `ccfc8e57885fabc5936a39034a9e816c66b2fbbc`）と
P13-A2a の adapter（`P13_A2A` ＝ `12de956637bb1df5fcff8846ba9d7fcb606421a3`）は変えない（blob を HEAD ・index ・作業木で pin）。
Markdown ・Obsidian への export は無い（A4）。network ・取得 ・scheduler ・LLM ・自律の判断は無い。B-track は HOLD ・P14 は未着手。

| 項目 | 値 |
|---|---|
| runtime（登録 ・認可: gate `P13-A3` ・anchor `P13_A2A`） | `src/intelligence/market_memory/memory_generation.py` ・`src/intelligence/market_memory/memory_store.py` ・`src/intelligence/market_memory/memory_build.py` |
| 純粋な model | `memory_generation.py`: 計画 ・generation ・manifest ・pointer ・試行の証拠 ・目印 ・lock の byte ・厳密な検証（file の I/O は無い） |
| filesystem の I/O | `memory_store.py` だけ（stdlib `os` ・`stat` ・`re`。P13 の guard の file ごとの許し ・`os` の属性の allowlist） |
| orchestration | `memory_build.py`: A2a の `sample_review_state` と store の狭い面だけ（filesystem の呼び出しは無い ・P10 の importer の許可は増やさない） |
| 版 | store `p13_memory_store:0.1.0` ・規則 `p13_memory_rules:0.1.0` ・generation `p13_memory_generation:0.1.0` ・manifest `p13_memory_manifest:0.1.0` ・pointer `p13_memory_publication:0.1.0` ・試行 `p13_memory_attempt:0.1.0` |

## 1. root と layout

- root は **明示の絶対 path** だけ。既定の場所 ・暗黙の作成は無い。`initialize_memory_root(root, *, protected_roots)` の明示の呼び出しだけが、
  空の directory（または親が在る未作成の名前）に目印 `.p13-memory-root` と固定の layout を作る。既存 ・空でない root は拒む
  （`ROOT_ALREADY_INITIALIZED` ／ `ROOT_NOT_EMPTY`）。`open_memory_store` は作らない（無ければ `MEMORY_ROOT_MISSING`）。
- 重なりの拒否（`ROOT_OVERLAP`）: 呼び出し側が渡す保護の root（P8 〜 P12 の authority ・source ・Obsidian の vault など）と、この code の
  repository の位置（常に保護）。build は P9 ／ P10 の source の root を必ず追加で検査する。**位置を渡されていない root の重なりは検査できず、
  主張しない**（store は検査した label だけを `protected_labels` に出す）。比較は正規化 ・大小の畳み ・`realpath` の文字の形と、file の
  identity（`st_dev` ・`st_ino`）の祖先 ↔ 自身の一致（最善の努力）。
- 祖先の目印: `.git`（`ROOT_INSIDE_WORKING_TREE`）・`.obsidian`（`ROOT_INSIDE_VAULT`）・既知の同期 folder の名前と目印（`ROOT_SYNC_FOLDER`:
  OneDrive ・Dropbox ・iCloud ・Google Drive ・Box ・Nextcloud ・ownCloud ・Syncthing ・Resilio ・Synology ・Tresorit など）。**同期の検出は網羅ではない**:
  未知の同期の仕組み ・後から root を同期の対象にすることは防げない。
- 成分の安全: anchor から root ・file までの全ての成分で symlink ・junction ・reparse point ・file を拒む（`os.lstat` ・Windows では
  `st_file_attributes` の reparse point の bit。host の OS と Python が出す範囲だけ）。相対 ・`..` ・正規化されていない形 ・NUL ・
  Windows の drive 相対 ・ADS ・末尾の点 ／ 空白の別名は `ROOT_INVALID`。
- 重要な操作（lock の取得 ・staging ・generation の rename ・pointer の置換 ・読み）の前に root の identity ・目印 ・layout を再検査する
  （`ROOT_IDENTITY_MISMATCH` ・`MARKER_INVALID` ・`UNAUTHORIZED_ENTRY` ・`LAYOUT_INVALID`）。**検査と操作の間の TOCTOU は stdlib では閉じない**。

```
<root>/
  .p13-memory-root                       目印（store の schema の版と root の class だけ ・path ・時刻 ・host は無い）
  market_memory/
    generations/<generation digest>/     不変の generation（64 hex の名前）
    staging/                             作業中の .partial ・一時 file（在れば書き込みを拒む）
    interrupted/<name>.<NNN>.interrupted 明示の回復が移した物（消さない）
    attempts/<attempt digest>.json       不完全な計画の安全な証拠
    locks/writer.lock                    単一の writer lock
    publication.json                     公開の pointer
```

権限: POSIX では directory `0o700` ・file `0o600` で作る。**POSIX の mode は Windows の ACL の privacy を確立しない**（Windows では継承した
ACL のまま。検証は P13-A5）。

## 2. 3 つの identity（混ぜない）

- **plan digest**: 要求した順序つきの cutoff の計画。A1 の `build_digest`（標本の schema を含む）に、memory の規則の版と記述子
  （adapter の規則 ・変化 ・generation ・store の schema の版）を足す。cutoff は 1 〜 256 個 ・`at` は厳密に増加 ・`as_of_date` は減らない
  （重複 ・逆順は `CUTOFF_ORDER_INVALID` で拒む）。読む前に計算できる。
- **generation digest**（domain `p13.memory_generation.v1` ・略記 `p13gen_`）: 実際に作った正準な結果（計画の cutoff ・view の identity ・
  全ての版 ・plan digest ・標本の完全な digest の列 ・変化の完全な digest の列 ・class）。同じ計画から byte 一致の結果が出れば同じ digest ＝
  **REUSED**（directory を書き直さない）。結果が変われば別の generation になり、古い generation は残る。
- **manifest digest**（domain `p13.memory_manifest.v1`）: generation の directory の manifest 以外の全 file の名前 ・byte 長 ・sha256。
- telemetry（`sampled_at` ・壁時計 ・host ・process ・root の位置 ・file system の metadata）は **どれにも入らず、どこにも保存しない**。
  `SampleEvidence` は作らない。lock の byte も操作 ・計画の digest だけ。

generation の file: `generation.json` ・`changes.jsonl`（`detect_changes_over` の順の正準な行 ・変化が無ければ空）・
`sample.<sample digest>.json`（完全な digest が名前）・`manifest.json`。全て正準 JSON ＋ LF（UTF-8 ・CR は無い ・binary で書く）。

## 3. lock と公開の lifecycle

1. writer lock: `locks/writer.lock` を `O_CREAT | O_EXCL`（Windows は `O_BINARY` も）で作る。既に在れば `WRITER_LOCK_PRESENT`（fail closed）。
   stale の推定 ・自動の奪取 ・自動の削除は無い。**lock の回復 ・奪取の API は無い**: 残った ／ 所有を検証できない lock は、別に承認され検証された
   回復の手順が実装されるまで書き込み（build ・明示の回復を含む）を拒み続ける。P13 は lock を移さない ・消さない（自分が作り所有を検証した
   lock の解放だけ）。
2. 書ける状態: lock の所有 ・root ・目印 ・layout ・staging が空（在れば `STAGING_PRESENT`）・公開の pointer が検証できるか未公開
   （検証できない pointer の上には公開しない ＝ `PUBLICATION_NOT_VERIFIED` で拒み、証拠を保存する）。
3. 標本: 各 cutoff を A2a の adapter で読む。1 つでも SAMPLED でなければ **INCOMPLETE**: `attempts/` に安全な試行の証拠（plan digest ・
   cutoff ・cutoff ごとの状態と固定の code だけ ・標本 ・source の詳細は無い）を 1 度だけ置き、`publication.json` は変えない。INCOMPLETE の
   generation は作らない ・公開しない。
4. stage: `staging/<digest>.partial/` に全 artifact を排他の作成 ・全て書く ・fsync（manifest は最後）→ 読み戻しの byte の照合 →
   `verify_generation_records` の厳密な検証。
5. generation の公開: lock ・root を再検査し、`generations/<digest>` が無いことを確かめて 1 回だけ rename → 読み戻しの検証。
   **rename だけでは公開の成功ではない**。既に在る generation は検証して REUSED にするか、合わなければ `GENERATION_CONFLICT`（上書きしない）。
6. pointer: `staging/` に一時 file を排他で作り読み戻し → `os.replace` で `publication.json` を替える → pointer の正準性 ・参照先の
   generation の全ての検証 ・manifest の digest の一致を読み戻して確かめた時だけ PUBLISHED ／ REUSED。失敗は `POINTER_PUBLICATION_FAILED` ／
   `POINTER_VERIFICATION_FAILED` を返し、操作の後に **実際に読み戻して検証した** pointer の状態（`publication_status`）を報告する
   （古い pointer が有効だと検証せずに主張しない）。
7. lock の解放: 全ての経路で `release()`。作成時の file の identity（`st_dev` ・`st_ino` ・0 は検証できない）と byte の完全一致を確かめた時だけ
   消す（`LOCK_RELEASED`）。確かめられなければ消さず `LOCK_OWNERSHIP_UNVERIFIED`、消せなければ `LOCK_RELEASE_FAILED`（どちらも lock は残り、
   次の writer は `WRITER_LOCK_PRESENT`）。lock は乱数の値 ・process の metadata を持たないので、外部から消された lock の file の identity が
   再利用され、同じ byte の lock が別の writer に作られた場合は区別できない（既知の限界 ・検証と unlink の間の TOCTOU と同じく文書に残す）。

削除の許しは `_unlink_if_owned` の 1 箇所の `unlink` だけで、呼ぶのは lock の解放と、置換に失敗した自分の pointer の一時 file の破棄だけ。
generation ・試行の証拠 ・中断の staging ・公開済みの data は消さない ・上書きしない ・自動で修復しない（guard が AST で pin する）。

## 4. 回復（人の明示の呼び出しだけ ・何も消さない ・既存の entry を置き換えない）

回復は次の 2 つだけ。どちらも writer lock を取得し（既に在れば `WRITER_LOCK_PRESENT` で拒む ・lock を動かさない）、build ・公開の経路からは
呼ばれない（guard が AST で pin する）。結果は固定の code（`PRESERVED` ・`NOTHING_TO_PRESERVE` ・拒否の理由）と移した名前だけ。

- `preserve_interrupted_staging(store)`: staging の全ての entry（`.partial` ・一時 file）を `interrupted/<name>.<NNN>.interrupted` に移す。
  その後の build は通常どおり進む。
- `preserve_publication_pointer(store)`: 状態を層で分け、**確定的に壊れた pointer だけ**を移す:
  - pointer の byte の形が違う ・未知の版、または参照先が確定的に不整合（generation の不在 ・manifest の digest の不一致 ・純粋な検証の失敗）→
    `PRESERVED`（同じ file ・同じ byte が移ったことを file の identity で確かめる。確かめられなければ `PRESERVATION_UNVERIFIED`）。
  - 検証できる pointer → `POINTER_VERIFIED_NOT_PRESERVED`（移さない）。pointer が無い → `NOTHING_TO_PRESERVE`。
  - root ・layout ・I/O の失敗 ・安全でない entry ・読みの最中の変化などの曖昧な状態 → `PUBLICATION_STATE_UNCERTAIN`（何も移さない ・fail closed）。
  - 移した後に自動の修復 ・再公開は無い（状態は NOT_PUBLISHED。公開は別の明示の build だけ）。generation ・試行の証拠には触れない。
- 移動は既存の entry を置き換えない: 空いた番号だけを使い、Windows の `os.rename` は既存の target を置き換えない。POSIX の rename は既存の
  file ・空の directory を黙って置き換えるので、先に target を排他で予約し（空の file は O_EXCL ・directory は mkdir）、所有を確かめた自分の
  空の予約だけを置き換える。予約が他に替わっていれば移さない（予約は残す）。予約と rename の間の TOCTOU は stdlib では閉じない。
- 検証に失敗した generation を移す ・消す API は無い（同じ digest の再公開は `GENERATION_CONFLICT` のまま ・人の調査）。
- 初期化の途中の失敗は、目印が在り layout が欠けた root を残す（`LAYOUT_INVALID` で開けない ・人の確認）。

## 5. 読みの状態と完全性の層

| 状態 | 結果 | code |
|---|---|---|
| root ・目印が無い | MISSING | `MEMORY_ROOT_MISSING` |
| 初期化済みで pointer が無い | NOT_PUBLISHED | `MEMORY_NOT_PUBLISHED` |
| pointer の形が違う ・参照先の generation が無い ・manifest の digest の不一致 | INTEGRITY_FAILURE | `PUBLICATION_POINTER_INCONSISTENT` |
| 参照先の generation の検証の失敗 | INTEGRITY_FAILURE | `MANIFEST_MISMATCH` ・`GENERATION_INCOMPLETE` ・`UNAUTHORIZED_ENTRY` ・`RECORD_CORRUPT` ・`RECORD_DIGEST_MISMATCH` ・`CHANGES_INCONSISTENT` ・`GENERATION_DIGEST_MISMATCH` ・`PLAN_DIGEST_MISMATCH` ・`SHORT_ID_COLLISION` |
| 未知の schema の版 | SCHEMA_UNSUPPORTED | `SCHEMA_UNSUPPORTED` |
| layout の外の entry ・symlink ・reparse point | INTEGRITY_FAILURE | `UNAUTHORIZED_ENTRY` ・`UNSAFE_ENTRY` |
| root の差し替え | INTEGRITY_FAILURE | `ROOT_IDENTITY_MISMATCH` |
| staging の残り | 読みは続く（`staging_present`）・書き込みは拒む | `STAGING_PRESENT` |
| STALE | label だけ（`staleness_of` ・呼び出し側が明示した評価の cutoff と窓 ・時計は無い ・trigger ではない） | — |

- **P13 の record の完全性**: 正準 byte の往復 ・完全な digest の再計算 ・file 名との一致 ・略記 id の衝突の検出。
- **build の完全性**: manifest の file の集合の完全一致（欠落 ・余分）・長さ ・sha256 ・generation ／ plan の digest の再計算 ・標本からの
  変化の再生の一致。
- **P9 ／ P10 の authority の完全性は確立しない**: P13 は governed な reader が読んだ時に検証したことしか知らない。raw の root の byte の
  manifest は読まない ・作らない（監督の将来の決定）。
- **store をまたぐ不可分性は無い**: A2a の 2 回の P9 の読みの一致は不可分な snapshot ではなく、往復（ABA）を除外できない。この限界は
  generation の `source_integrity_class` に記録する。

## 6. Windows の安全と既知の限界（P13-A5 で実機の検証を要する）

- **path の検査は競合に対して安全ではない（not race-proof）**: 祖先 ・symlink ・reparse point ・重なり ・目印 ・root の identity の検査と
  実際の操作の間に、別の process が file system を替えることを stdlib では防げない。検査は fail closed の最善の努力であり、競合の不在の証明ではない。
- **Windows の ACL の privacy は未検証**: POSIX の mode（`0o700` ・`0o600`）は Windows では効かず、継承した ACL のままになる。
- **NTFS の操作は P13-A5 の検証を要する**: junction ・reparse point の拒否 ・rename ／ `os.replace` の意味 ・file の identity は Linux の
  合成の試験では確かめていない。
- NTFS の junction ／ reparse point の拒否（Python 3.11 には `os.path.isjunction` が無い ・`st_file_attributes` に依る）。
- Windows の ACL の privacy（POSIX の mode は効かない）。
- 開いた handle（antivirus ・索引 ・同期の client）による rename ／ `os.replace` の失敗（再試行は無い ・fail closed）。
- 電源断の durability: Windows では directory の fsync ができない。torn な状態は厳密な読みが検出するが、rename の永続は保証されない。
- path の別名と大小の畳み（8.3 の短い名前 ・大小の違い ・UNC）による重なりの検査の回避。
- 深い root の path の長さ（64 hex の名前）。
- 中断した操作からの回復（実機の中断 ・`interrupted/` への保存）。

## 7. 試験（合成の一時 root だけ）

凍結の test の builder（P9 の世界 ・P10 の初期化 ・P10 の executor の決定）で一時 root を作る。本物の private な authority root には触れない ・
本物の Obsidian の vault を作らない ・取得 ・資格情報 ・network は無い。障害は store の module の `os` を差し替える代理で注入する
（artifact の書き込み ・fsync ・rename ・pointer の置換 ・読み戻し ・lock の解放）。

- `test_market_memory_generation.py`: 計画 ・3 つの identity ・REUSED の決定論 ・manifest ・改竄 ・欠落 ・余分 ・未知の版 ・変化の不整合 ・略記 id の衝突。
- `test_market_memory_store.py`: 明示の初期化 ・root の拒否（相対 ・`..` ・symlink ・reparse point の模擬 ・重なり ・同期 ・git ・vault）・
  identity の差し替え ・lock（所有者の解放 ・所有を検証できない lock の保持 ・奪取の不在）・staging ・各段の障害 ・pointer ・回復（検証できる
  pointer は移さない ・曖昧な状態は移さない ・既存の証拠を置き換えない）・削除の無い歴史 ・unlink は lock と pointer の一時 file だけ。
- `test_market_memory_build.py`: 公開 ・厳密な再読 ・REUSED ・結果の変化 ・古い generation の保存 ・標本 ／ 変化の再生 ・P9 ／ P10 の byte と
  mtime の不変 ・実行の環境に依らない正準 byte ・不在 ／ 破損の入力 → INCOMPLETE ・lock の解放の失敗（lock は残り書き込みを拒み続ける）・
  build が回復を呼ばないこと。

## 8. 次（監督の個別の GO を要する）

P13-A4 projection（Obsidian への export だけ）→ P13-A5 実機（Windows）→ P13-A6 freeze。A3 は export は無い。
