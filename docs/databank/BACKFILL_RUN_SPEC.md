# BACKFILL_RUN_SPEC — BackfillRun・checkpoint・冪等仕様（Phase 2-C）

## 1. BackfillRun manifest（backfill_runs.jsonl・append-only監査履歴）

run_id（bfr_ULID）/ started_at / completed_at / source_dataset /
**input_fingerprint**（shard一覧×size×sha256から決定論導出）/
schema_version_used / normalizer_version / identity_algorithm_version /
trust_policy（"HISTORICAL:1.0.0"）/ records_seen / records_success /
records_partial / records_rejected / records_failed / **checkpoint** / status
（running/completed/crashed）/ limit（段階実行）。

## 2. CHECKPOINT / RESUME

- 入力は決定論的順序（shardソート×行番号）でrecord_indexが振られる。
- checkpointは「次に処理するindex」。crash時もfinallyでmanifestへ記録される。
- resume: `latest_checkpoint(input_fingerprint)`（run履歴からの導出）から再開。
  **fingerprintが異なる入力のcheckpointは使われない**（入力変化の安全弁）。
- crash→resume が clean一発実行と同一のcanonical状態になることをテストで検証。

## 3. IDEMPOTENCY

同一入力×同一schema×同一normalizer×同一identity algorithm×同一policyの再実行で
canonical出力は二重化しない:
- SourceDocument / NewsItem / LegacyAnnotation / ArticleはID決定論＋冪等add
  （同一ID同一内容=skip）。
- EvidenceAssessment / BackfillRunは**意図的にappend**（評価・実行の監査履歴）。
- news_items.jsonlは追記ログ（同一IDの新version追記・replayで最新が正——
  merge進行によるprimary更新のため）。
テスト: resume再実行=seen 0、resume=False完全再実行でもcanonical件数不変。

## 4. ATOMICITY / CHUNK

chunk単位処理（既定250。全件をメモリへ載せない——実測peak 58MB）。
JSONL canonical＝正・SQLite＝再構築可能index（P2-A方針維持）のため、
「record書込済み・index未書込」状態はindex再構築で常に復旧できる。
JSONL末尾破損行はrecovered_lines申告付きで読み飛ばし（全store共通）。

## 5. 再実行手順（REPROCESSING）

```
python -m pytest tests/intelligence -q           # 事前検証
python3 <run_backfill.py相当>                     # 段階: limit=100 → 500 → 0(full)
```
normalizer v2 / identity v2 / policy v2への更新時は、legacy入力を再取得せず
新version群で再backfillする（新IDの新レコード・旧run manifestは監査履歴として残る）。

## 6. REJECT LEDGER（黙って捨てない）

reject_ledger.jsonl: run_id / legacy_locator（shard:行）/ legacy_id /
stage（input/source_mapping/normalization/identity/news_item/unexpected）/
reason_codes / exception_type / detail。legacy入力自体は変更しない。
mandatory（title・fetched_at等のidentity成立要件）とoptional（summary・author等）を
分離し、optional欠損はPARTIALでREJECTしない（テスト検証）。
