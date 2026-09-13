# STORAGE_DECISION — 保存方式の比較と決定（Phase 1-A）

2026-08-29。production DBは作らない（P1-A方針）。domain model / repository interface /
serialization を中心に据え、保存方式は差し替え可能な実装詳細として扱う。

## 1. 比較

| 方式 | 長所 | 短所 | 評価 |
|---|---|---|---|
| **JSONL**（追記・1行1レコード） | stdlibのみ・人間可読・git/rsync親和・追記=Evidence不変と相性・tank実績あり | 全読込O(n)・横断検索は別途索引が必要 | **P1-A採用（正本）** |
| SQLite | stdlibのみ・索引/横断検索・tankのindex実績 | スキーマ移行の手間・バイナリでdiff不能 | P1-B〜2で**索引**として併設（正本にはしない。tankと同じ「shardsから再構築可能なindex」パターン） |
| Parquet | 列指向・分析/バックテスト高速・圧縮 | pyarrow依存（重い）・追記に不向き | Phase 5+の分析エクスポート形式として将来採用候補 |
| Postgres等 | 本格運用・同時実行 | 運用コスト。現段階で不要 | Phase 11+で必要になった時、Repository契約の裏で差し替え |

## 2. 決定

1. **正本 = JSONL追記ストア**（`data/vnext/` 配下・git非管理）。参照実装:
   `src/intelligence/evidence/jsonl_store.py`（documents / raw_items / statements /
   links / observations の5ファイル、標準ライブラリのみ、重複ID規約を実装）。
2. **検索索引 = 再構築可能なSQLite**（P1-B以降。正本から常に再生成できるため
   スキーマ変更が怖くない——tankで実証済みのパターン）。
3. **domain層の防衛**: エンジンはcontracts.py のProtocol（EvidenceRepository /
   MarketRepository）のみに依存する。将来Postgres/Parquetへ移行しても
   domainとエンジンは無変更（テストでProtocol充足を機械検証）。
4. **serializationはストレージ非依存**（core/serialization.py）: `_type`タグ付きJSON互換dict。
   datetime=UTC正規化ISO 8601・Decimal=文字列・Enum=value・未知型は拒否。
   0.x間の前方互換: 未知フィールドは無視（decode時にdefaultへ委ねる）。

## 3. schema versionポリシー

- 現在 **0.2.0**（experimental）。全レコードが schema_version を自己申告する。
- Phase 1完了までbackward compatibility非保証。以後はフィールド追加=パッチ、
  意味変更=マイナー、破壊的変更=メジャー（1.0以降）で運用する。
