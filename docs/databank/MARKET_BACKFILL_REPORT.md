# MARKET_BACKFILL_REPORT — live pilot＋historical backfill実行報告（Phase 2-D / 2026-08-30）

実行環境: GitHub Actions（p2d-market-pilot run #4・commit 4dad3c6・conclusion **success**）。
run manifest: `mbf_01M18JBZ552E2QEEAFRNPXN1Q8`（backfill_runs.jsonlへ永続）。
要求期間 2025-07-26〜2026-08-30（400暦日≒13ヶ月——目標1年を充足）。
provider chain: **yfinance一次・Stooqフォールバック**（legacy本番構成の再現）。

## 1. 系列別結果（15系列・1系列=1リクエスト・sleep 1s）

| series | symbol | 結果 | records | QA |
|---|---|---|---|---|
| 日経平均 | ^N225 | success | 266 | AWW 266 |
| TOPIX | ^tpx(stooq) | **gap**（G9/G10） | 0 | — |
| NYダウ | ^DJI | success | 275 | AWW 275 |
| S&P500 | ^GSPC | success | 275 | AWW 275 |
| ナスダック総合 | ^IXIC | success | 275 | AWW 275 |
| SOX | ^SOX | success | 275 | AWW 275 |
| VIX | ^VIX | success | 276 | AWW 276 |
| USDJPY | JPY=X | success | 283 | AWW 283 |
| EURUSD | EURUSD=X | success | 283 | AWW 283 |
| JGB10Y | 10jpy.b(stooq) | **gap**（G9/G11） | 0 | — |
| UST2Y | 2usy.b(stooq) | **gap**（G9/G11） | 0 | — |
| UST10Y | ^TNX | success | 275 | AWW 275 |
| WTI先物継続 | CL=F | success | 275 | AWW 275 |
| 金先物継続 | GC=F | success | 275 | AWW 275 |
| BTCUSD | BTC-USD | success | 399 | AWW 399 |

（AWW = accept_with_warnings。gapのfallback_errorsには `stooq:parse_error`
＝HTML制限ページが診断snippet付きで記録され、**silent failureゼロ**）

## 2. 会計

```
requested 15 = success 12 + gap 3 + failed 0            ✅
raw observations added        3,432（全て値あり・欠測行0）
derived observations added   13,080（return_1d/5d・ma25・dist_25dma・
                                     UST10Y-UST2Yspread※・NT倍率※）
canonical合計                16,512 / QA assessments 16,513（+DAILY_MARKET再評価1）
※cross系列（spread/NT）は入力gap（UST2Y・TOPIX欠落）のため今回未出力——
  片側だけで捏造しない設計の帰結（入力が揃い次第自動的に算出される）
```

## 3. LIVE PILOT trace（日経225・end-to-end）

```
fetch_attempt fetch_01M18JBZ55… status=200 → raw csv raw_5503dd88d298a7b3
  (9242B sha256=8fc66911e09ab477… storage=blobs/8f/8fc66911…)
→ obs_9defa6b5652d12d5e7024753: trading_date=2026-08-28 value=66405.5625
  unit=index as_of=2026-08-28T06:30:00Z（15:30 JST） source=yfinance kind=raw
→ qa_01M18JBZ55…: accept_with_warnings HISTORICAL:1.0.0
  issues=[missing_supporting_evidence_ref]（API直取得＝由来文書なしの正直な申告）
→ SQLite index row（latest_trading_session一致）
```

## 4. QA文脈分離の実証（同一観測・2policy）

最新の日経終値（金曜8/28）を土曜朝に評価:
- HISTORICAL:1.0.0 → accept_with_warnings（missing_supporting_evidence_ref）
- DAILY_MARKET:1.0.0 → accept_with_warnings（＋**aging**——「今日の材料」文脈では
  経過時間警告が付く。文脈でtrust判定が変わることの実データ実証・追記保存）

## 5. PERSISTENCE VALIDATION GATE（PART A・別プロセス）

```
fresh_process: true（メモリ非共有のsubprocessでcanonical再オープン）
canonical 16,512読み戻し / recovered_lines 0
SQLite indexを空から全再構築: 16,512（canonical一致）
latest（trading_session基準）12系列照合: mismatch 0 → ok: true ✅
```

## 6. BACKUP基盤

manifest 21ファイル・41,739,042 bytes・schema 0.4.0・sha256 inventory付き。
生成直後のverify: missing 0 / changed 0 / extra 0 ✅

## 7. 冪等・改定（オフライン検証で固定）

- 同一入力の再実行: observations_added 0・QA追記0・canonical不変（テスト固定）
- 値変化: 新Observation＋revision_of（旧値保持）・provider切替は必ず記録
- crash耐性: JSONL末尾破損行recovered_lines申告・index全再構築で復旧

## 8. PERFORMANCE

データ相（fetch→ingest→QA→derived 16,512件）約88秒（sleep 14秒込み）・
persistence検証＋backup含む全体約126秒・Actions job計2分29秒。
