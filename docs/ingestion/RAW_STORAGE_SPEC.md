# RAW_STORAGE_SPEC — Immutable Raw Store仕様（Phase 1-C）

## 1. レイアウト（metadata と content blob の分離）

```
data/vnext/raw/                     ← git非管理（.gitignoreのdata/vnext/配下）
├── blobs/<hash先頭2桁>/<sha256hex>  ← 生body（content-addressed）
├── raw_items.jsonl                 ← RawItemメタデータ（append-only）
└── fetch_attempts.jsonl            ← FetchAttempt（append-only）
```

- domainオブジェクトへ巨大bodyを埋め込まない（RawItemは `storage_ref` でblobを参照）。
- 日付ディレクトリ案（raw/YYYY/MM/DD/）は不採用: content-addressed構造の方が
  物理dedup・hash検証・冪等と整合する。時系列アクセスはJSONLのretrieved_atが担う。

## 2. 保証と実装

| 要件 | 実装 |
|---|---|
| append-only / immutable | 上書き・削除APIなし。同一URLの内容更新は新RawItem（旧版残存をテスト検証） |
| atomic write | blob: mkstemp→fsync→os.replace（tank cursor.pyパターン）。JSONL: append＋flush＋fsync |
| content hash verification | SHA-256（content_hash）。`verify_blob()`で再計算照合。改竄・破損を検知 |
| duplicate-safe | 同一hash blobは物理1つ（storeが冪等）。RawItem追加は同一ID＋同一内容→冪等スキップ／同一ID＋内容差→ValueError |
| crash-safe | JSONL末尾の書きかけ行は読み飛ばして復帰。件数を`recovered_lines`で申告（silentにしない）。blobのtemp残骸はfinallyで除去 |
| re-open/read | 起動時にJSONLからin-memoryインデックス再構築（**導出**であり二重保存でない） |
| metadata→body lookup | `read_body(item)`。storage_ref=""（原文非保存の明示）はValueError。locatorのroot外参照は拒否 |

## 3. 物理dedupとprovenance

同一content hashのbodyはblob 1つに畳むが、**fetch provenanceは失わない**:
- RawItemは (source_id, locator, content_hash) のcontent-addressed IDなので、
  別source・別URLからの同一内容は**別レコード**として残る。
- FetchAttemptは試行ごとに必ず1レコード（同一内容の再取得でも記録される）。

## 4. Repository境界（core/contracts.py）

- `RawRepository`: store_body / add_raw_item / get_raw_item / read_body / iter_raw_items
- `FetchAttemptRepository`: add_attempt / iter_attempts / attempts_for / latest_conditional

参照実装 `JsonlRawRepository` は両Protocolを充足（テストでisinstance機械検証）。
JSONL正本＋再構築可能索引というP1-A STORAGE_DECISIONの方針を踏襲し、
将来SQLite/Postgresへ差し替えてもdomain/fetcherは無変更。

## 5. ID・hash規約

- FetchAttempt: `fetch_<ULID>`（時刻順）
- RawItem: `raw_<sha256(source_id, locator, content_hash)[:24]>`（content-addressed）
- blob: `sha256hex`そのもの（content-addressed）
- P1-A ids.py の`content_id`/`new_id`と完全整合（同一関数を使用）。
