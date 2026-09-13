# DATA_BANK_STORAGE_DECISION — 保存戦略の決定（Phase 2-A）

## 1. 調査と結論（役割分離）

| 技術 | 役割 | 理由 |
|---|---|---|
| **JSONL** | **append-only正本**（Raw/normalized/QA/news） | stdlibのみ・人間可読・追記=イミュータブルEvidenceと相性・crash-safe実装済み（P1-C/D/E）・監査容易 |
| **SQLite** | **検索用operational index（正本から常に再構築可能）** | stdlib sqlite3・索引/JOIN・tankで実証済みの「shardsから再構築可能なindex」パターン。スキーマ変更が怖くない（DROP→再構築） |
| Parquet | 分析用bulk履歴（**将来**。Phase 5+のバックテスト/較正） | 列指向・圧縮。pyarrow依存が重いため必要になるまで導入しない |
| Postgres | 将来の同時実行運用（Phase 11+） | Repository契約の裏で差し替え（domain無変更） |

P1-A STORAGE_DECISIONの方針を維持し、Phase 2の検索需要にSQLite索引で応える。

## 2. 規律

1. **正本はJSONL**。SQLiteは導出物であり、消しても正本から`index_*`で再生成できる
   （`SqliteNewsIndex.rebuild()`＋再構築テストで実証）。
2. **domain layerはSQLを書かない**。SQLは`databank/sqlite_index.py`（Repository実装）
   に隔離。query契約（NewsQuery/MarketQuery）はdomain語彙のみ。
   将来Postgres移行時はこのモジュールだけ差し替える。
3. スキーマ変更手順: 索引DROP→正本から再構築（migrationファイル管理をしない）。
   正本JSONLは書き換えない（schema versionはレコード自己申告・未知フィールド無視）。

## 3. QUERY CONTRACTS（P2-Aで固定）

`NewsQuery`: date range（published_at・aware必須）/ publisher / source_id / language /
country / company / ticker / theme / event_type / **trust_decisions**（Gate判定）/ limit。
`MarketQuery`: series_id / instrument_id / metric / as_of range / kinds。

SQLite索引はNewsQueryableを充足し、date/publisher/source/classification/
trust_decisionでの検索をテスト済み（country〜themeの実データはP2-E以降に投入される。
契約と実装経路はP2-Aで検証済み）。高度検索UIは作らない（Phase 11）。

## 4. 配置

- 索引ファイル: `data/vnext/index/`（git非管理）
- 正本: `data/vnext/{raw,normalized,evidence_qa,news}/`（git非管理・append-only）
