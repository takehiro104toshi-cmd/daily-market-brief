# MARKET_STORAGE_AND_PERSISTENCE — 永続化決定（Phase 2-D PART A・必須Gate）

## 1. PERSISTENCE DECISION（採用）

**local-first・single-user**:
- canonical = **JSONL append-only**（正。人間可読・crash-safe・追記のみ）
- index = **SQLite**（`market.sqlite3`。canonicalから常に全再構築可能な導出物）
- backup = **manifest照合方式のローカルバックアップ基盤**（§4）

news bank（P2-C）で実証済みのtank由来パターンをそのまま採用し、市場データ固有の
要素（trading_date・改定解決・latest semantics）をindex側スキーマへ追加した。
クラウドDB・常駐サーバは導入しない（single-user・コスト・運用単純性）。

## 2. コード（Git）とデータ（ローカル永続領域）の分離

- **GitリポジトリはData Bankではない**: `data/vnext/` は.gitignore済み。
  観測データの大量履歴コミットは禁止（P2-C決定の継続）。
- Gitが持つのは: コード・スキーマ・カタログ（knowledge/）・レポートdocs・
  小さなテストfixtureのみ。

## 3. DATA ROOT解決（`src/intelligence/core/paths.py`）

優先順位（絶対パスのハードコードなし）:
1. 環境変数 **`INTELLIGENCE_DATA_ROOT`**（最優先——恒久運用ではユーザーの
   永続ディスク/外付け/NASを指す。開発コンテナ・Actionsではtemp領域を指す）
2. `config.yaml` の `vnext.data_root`（CLAUDE.mdルール8準拠のリポジトリ設定）
3. 既定 `data/vnext`（CWD相対・従来ストアと同一）

layout: `<data_root>/databank/market/{raw/, normalized/, evidence_qa/, index/,
backfill_runs.jsonl}`＋`<data_root>/backup/`（manifest）。

**開発コンテナはephemeral**——コンテナ上の既定rootは開発・検証用であり恒久保存
ではない。恒久運用は`INTELLIGENCE_DATA_ROOT`で永続媒体を指し、§4のmanifest検証で
バックアップを照合する（ephemeral上の書込みを「永続化した」と主張しない）。

## 4. バックアップ基盤（`src/intelligence/core/backup.py`——土台のみ）

- `write_backup_manifest(data_root)`: file inventory（相対パス・size・**sha256**）＋
  **schema_version**＋作成時刻のJSON manifest。SQLite indexのchecksumも記録される
  （index破損はcanonicalから再構築で復旧できるが、コピー破損検知に使う）。
- `verify_against_manifest(root, manifest)`: コピー先root vs manifest →
  (missing, changed, extra)。missing/changed空 = 検証OK。extraはコピー後の
  正常な追記と破損を区別するための情報提供。
- 世代管理・自動スケジュールは将来（本フェーズは検証可能なmanifest基盤まで）。

## 5. PERSISTENCE VALIDATION GATE（restart相当の実証）

`src/intelligence/market/persistence_check.py` を**別プロセス**として起動:
1. canonical JSONLのみを読み戻す（書込プロセスのメモリ状態を共有しない）
2. SQLite indexを**空から全再構築**
3. 指定系列のlatest（trading_session基準）が親プロセス結果と一致することを照合

オフラインテスト（test_market_persistence.py）とlive pilot（Actions）の両方で
このgateを通す。indexファイル削除→canonicalから復旧のテストも固定。

## 6. LATEST SEMANTICS（PART I: 「最新」の多義性の明示）

| クエリ | 意味 | 用途 |
|---|---|---|
| `latest_trading_session(series)` | 最新**取引セッション日**の現在有効値（改定解決済み） | 「昨晩の米国終値」——日本の朝でもtrading_dateは前営業日のまま |
| `latest_as_of(series)` | as_of時刻が最新の現在有効値 | 時刻軸での最新（規約差による日跨ぎを区別） |
| `latest_revision_for(series, date)` | ある日の最新改定版 | 改定履歴の解決 |
| `revision_chain(series, date)` | ある日の全版（旧→新） | 改定監査 |
| 「最新に**取得**した」 | indexの責務ではない | run manifest（backfill_runs.jsonl）が保持 |

既定クエリは改定解決済み（current_only=True）。旧値は `current_only=False` で
常に参照可能（消さない）。

## 7. 再構築・復旧の保証

- SQLite index削除 → `rebuild()` でcanonicalから完全復元（テスト固定）。
- JSONL末尾破損行 → recovered_lines申告付き読み飛ばし（全store共通・P1-C以来）。
- blobはcontent-addressed＋atomic write（mkstemp→fsync→os.replace）。
