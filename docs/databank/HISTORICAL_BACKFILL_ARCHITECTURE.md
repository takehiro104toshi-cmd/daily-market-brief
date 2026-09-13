# HISTORICAL_BACKFILL_ARCHITECTURE — 歴史データ移行設計（Phase 2-C / 2026-08-30）

原則: **BACKFILL IS A DATA MIGRATION, NOT A FILE COPY。**
legacy tankの記事を旧DBコピーとしてではなく、vNext全層（正規化→HISTORICAL QA→
Article Identity→NewsItem→Validation→canonical storage→index）を通して移行する。

## 1. パイプラインとモジュール

```
legacy tank shards（READ ONLY）
  → backfill_inventory.py  実測inventory＋input fingerprint（件数を盲信しない）
  → backfill.py BackfillEngine
      ├ map_legacy_source     … source_name→P1-B Registry（confidence記録・推測なし）
      ├ tank_article_normalizer（P1-D）→ SourceDocument
      ├ LegacyAnnotation隔離   … INTERPRETED値＋historical provenance
      ├ HISTORICAL Evidence QA（P1-E/P2-B policy）
      ├ IdentityRuntime（P2-B）＋identity_blocking.py（総当たり禁止）
      └ NewsItem生成（metadataのみ）
  → canonical JSONL（data/vnext/databank/・git非管理）
  → SQLite index再構築（P2-A方針: 導出物）
```

## 2. IDENTITY SCALING（O(n²)禁止への回答）

`identity_blocking.BlockingIndex`: 候補生成を
exact key（canonical URL / source内GUID / fingerprint / content hash）＋
blocking bucket（title_key先頭12字・(公開日, source)）のindex参照に限定。
無関係文書の候補ゼロ・候補は常にcorpusの真部分集合（テスト検証）。
実測: 3,056件でメモリ58MB・52 rec/s（500件時から劣化なし＝二次爆発なし）。

## 3. PROVENANCE（捏造しない）

- migration由来SourceDocumentは `normalizer_name="tank_article"`＋`raw_item_id=""`
  （原文非保存の明示）で実取得由来と機械的に区別。**FetchAttemptは一切作らない**
  （missing live FetchAttempt ≠ fabricated FetchAttempt——テストで不存在を検証）。
- historical import provenance: LegacyAnnotationへ legacy_shard_locator（shard:行）・
  legacy_article_id・source_mapping_confidence を保持。BackfillRunが
  input_fingerprint（shard一覧×sha256）でdataset全体を固定。

## 4. SOURCE MAPPING

P1-Bカタログはtank configを正に構築したため **name完全一致42/42・3,056/3,056件被覆**
（実測）。不一致時は推測せず `legacy_unknown:<domain>`（LEGACY_UNKNOWN_SOURCE表現・
Tier3・confidence="unmatched"）へ落とす（テストで検証）。

## 5. 新解釈の生成禁止（遵守）

LLM分類・theme推論・sentiment・importance・market impactは一切生成していない。
legacy値はLegacyAnnotation（origin=legacy_tank・not_ground_truth=true）へ隔離のみ。

## 6. 実行環境と永続性

ローカル（開発コンテナ内）で実行。canonical出力は`data/vnext/databank/`
（.gitignore済み——**Gitへhistorical datasetをcommitしない**）。
コンテナはephemeralのため、恒久保存はユーザーローカルでの再実行
（決定論: 同一入力fingerprint＋同一version群→同一出力）または
将来の永続ストレージ接続で行う（RISKSに明記）。再実行コマンドは
BACKFILL_RUN_SPEC.md §5。
