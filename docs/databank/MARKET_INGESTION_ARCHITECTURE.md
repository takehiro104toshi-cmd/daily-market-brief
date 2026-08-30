# MARKET_INGESTION_ARCHITECTURE — 取込アーキテクチャ（Phase 2-D PART C/D/E/F）

## 1. 層構成（provider非依存のdomain）

```
YfinanceDailyHistoryProvider（一次）─┐ providers.py（MarketDataProvider Protocol実装）
StooqDailyHistoryProvider（fallback）┘   1系列=1リクエストで日足履歴を取得
                            ▼
              ProviderFetchResult（transient・stringトークンのまま）
                            │  body=生CSV（stooq）/整形スナップショット（yfinance・
                            │  provider_normalized=true明示）→ BlobStore（raw保存）
                            │  FetchAttempt必ず記録（失敗も。P1-C再利用）
                            ▼
              ingest.build_observations（純関数・決定論）
                            │  Decimal(token)直接・欠測None・改定revision_of
                            ▼
              Evidence QA assess_observation（P1-E再利用・HISTORICAL policy）
                            ▼
              MarketBankStore（JSONL canonical → SQLite index）
                            ▼
              derived.derive_per_series / derive_cross_series（PART F）
```

domain（ingest/store/derived）はStooq・yfinanceを知らない。依存は
`MarketDataProvider` Protocolのみ。**LEGACY REUSE**: provider構成はlegacy
`src/collectors/market_data.py` の本番実績アーキテクチャ（yfinance一次・
Stooqフォールバック）を忠実に再現し、symbolはlegacy `config.yaml` の実績値
（Yahoo: ^N225/^DJI/^GSPC等・Stooq: ^nkx/^dji等）、HTTP/リトライ/redactは
P1-Cの `ingestion/transport.py` をadapter経由で再利用（legacyコードの改変ゼロ）。

## 2. RAW保存（provider応答の生値）

- Stooq history endpointはHTTP応答そのものがCSV——**生のままBlobStoreへ保存**
  （provider_normalized=false。ライブラリ前処理を経ないため「擬似raw」ではない）。
- yfinance等ライブラリ前処理済みproviderを将来追加する場合は
  `ProviderFetchResult.provider_normalized=true` を立てて区別する
  （生HTTPを捏造しない——P2-D DO NOT遵守の型化）。
- 失敗応答（HTTP 404/500・DNS等）もFetchAttemptとして必ず記録（P1-C原則）。
  同一内容の再取得は既存RawItem（初回provenance）を保持し、試行のみ追記。

## 3. Decimal規律（float非経由）

CSVのstringトークン → `Decimal(token)` を**直接**生成。float経由は
serialization層（P1-A）が拒否する。SQLite indexもvalueをTEXTで保持。
検証: `"38975.55"` → `str(value) == "38975.55"`（テスト固定）。

## 4. 欠測（MISSING STAYS MISSING）

- providerに行が無い日 … Observationを作らない（休日/障害/未公表を区別する
  情報が無い以上、区別を捏造しない。coverage差分は品質レポートが報告）。
- 行はあるが値トークンが空/N-A … value=None のObservation＋issue申告。
- **0・前日値・補間での充填は絶対にしない**（derived計算も欠測セッションを
  スキップするのみで補間しない）。

## 5. サニティ（検知のみ・補正しない）

週末日付（weekdays暦系列）・未来trading_date・同日重複行・数値化不能トークンを
issueとして申告。範囲外値（負の価格等）・unit/currency不整合・as_of未来は
Evidence QAの `eval_observation_validity`（P1-E）が検知する。
**「知識でこの価格はおかしいから直す」は構造的に存在しない**（検知→申告のみ）。

## 6. 改定（PART E: REVISION——上書き禁止）

- observation_idは content-addressed（series×trading_date×source×値）。
- 同一(series, trading_date)で値が変わった再取得 → **新Observation＋revision_of**。
  旧値はcanonicalに残り、latest導出はindexの改定解決（superseded除外）が担う。
- 同値の再取得 → 同一ID → 冪等スキップ（canonical追記ゼロ）。

## 7. provider fallback（SILENT SWITCH禁止）

- 各Observationが `source_id` を保持（per-Observation provenance）。
- 既存と異なるproviderの値を取り込む場合:
  同値 → 重複保存せず `source_change_confirmed_equal` 記録のみ。
  異値 → revision＋ `source_changes`（"日付:旧→新"）としてrun結果に記録。
- 品質レポートは系列内の複数provider混在を `fallback_used` として表面化する。
- provider chainはpreferred→fallback順（カタログ宣言）。失敗した試行も
  FetchAttemptとrun manifestのfallback_errorsに必ず残る。
- cross-source diff比較（同一series×同日を複数providerで照合）はStooqが
  使える環境（ローカルIP）で有効化される——**自動上書きは常に禁止**（検知・報告のみ）。

## 8. 派生（PART F: foundation only）

return_1d/5d・ma25・dist_25dma・UST10Y-UST2Yスプレッド・NT倍率のみ
（TAライブラリ化しない）。全derived Observationは inputs（入力observation_id）＋
calculation_method（"name:version"・丸め規約6桁ROUND_HALF_EVENを含む）必須。
依存QA: 入力assessmentのGate結果を `_dependency_dimension` で伝播（P1-E再利用）。
