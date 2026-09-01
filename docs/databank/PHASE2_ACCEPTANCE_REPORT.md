# PHASE2_ACCEPTANCE_REPORT — Phase 2受入報告（P2-A〜P2-F / 2026-08-30）

> **現況注記（2026-09-01・P2-G.2 closeout後に追記）**
> 本レポートは **Phase 2-F受理時点（2026-08-30）のHISTORICAL RECORD**。
> 下表「未充足事項」#1 に挙げた **TOPIX / JGB10Y / UST2Y（G10/G11）は
> その後すべてRESOLVED**（P2-G / P2-G.1 / P2-G.2、live pilot run #7・#15）。
> 現在のgap状態は `docs/sources/SOURCE_GAPS.md` と
> `docs/databank/CRITICAL_MARKET_SOURCE_GAP_CLOSURE.md` §6 が正。
> 本文は当時の判断根拠として上書きせず保全する。

Phase 2の目標: **説明可能・訂正可能・再構築可能（EXPLAINABLE / CORRECTABLE /
REBUILDABLE）なNews＋Market Data Bank**。分析（Phase 3以降）はまだ作らない。

## 1. サブフェーズ別成果

### P2-A 取得・正規化基盤
RAW→PARSED→NORMALIZED層分離。Source/RawItem/SourceDocument/FetchAttempt、
JSONL append-only canonical＋blob store＋再構築可能SQLite index、crash-safe読取り
（recovered_lines計測）、content-addressed ID（処理timestamp非含有）。

### P2-B 記事identity
決定論的identity解決（BlockingIndex＋シグナル照合）。ArticleIdentityEvent
append-only・手動イベント（user actor）がアルゴリズム判定に優先。
DISTINCT / CANDIDATE（推測しない） / REVISION の3値。

### P2-C legacyバックフィル＋Evidence QA
tank 3,056文書（dataset fingerprint `7578425805b32592…`）→ 3,001記事。
LegacyAnnotationで legacy shard locator / article id を全件保存（legacyは
ground truthではない・自動昇格しない）。Evidence QA層（HISTORICAL v1.0.0）で
全文書評価。source mapping exact_name 42/42。

### P2-D Market Data Bank
系列カタログ15系列（index≠ETF≠先物のidentity安全・TOPIXへのETF代用拒否）。
trading_date/as_of分離・Decimal文字列保持（float経由はprovider_float_transitで
開示）・revision chain・latest意味論4種。provider: yfinance主＋Stooq fallback
（legacy本番構成を踏襲）。live実測（Actions runner・run #5）:
**requested 15 = success 12 + gap 3 + failed 0 / raw 3,432＋derived 13,080
= canonical 16,512観測**。別プロセス永続化・index全再構築・latest 12/12一致。

### P2-E News分類・enrichment
CLASSIFICATION IS NOT FACT / 全enrichmentにprovenance。entity catalog 80・
theme taxonomy 30・event type 16（versioned知識資産）。alias安全3層（bare
uppercase語をtickerとして走査しない等）。effective view優先順位
USER > SOURCE_EXPLICIT > ENTITY_DATABASE > RULE_BASED > LLM。
実corpus 3,001記事: classifications 3,592・failed 0・冪等。
較正fixture 30件 precision/recall 1.000（**fixture上の値であり本番保証ではない**）。
記事被覆59.5%（ja 15件は金融庁事務連絡でtaxonomy対象外——正直なギャップ）。

### P2-F QA・レビュー・統一クエリ（本phase）
- **Human review**: ReviewItem/Decision append-only・ALLOWED_DECISIONS型制限・
  manual優先適用・CLI。実データintake **88件 open**（identity 25＋曖昧alias 58＋
  未知ticker 5）。架空のhuman decisionは投入していない。
- **Identity Decision Ledger**: CANDIDATE 25件へconfidence/シグナル/algorithm
  版を永続（post_hoc derivation明示・article events無変更のmigration-safe）。
- **Revision/Syndication精緻化**: 55件 = same_publisher_update 53＋
  cross_feed_same_article 2（同一canonical URLで証明）＋UNKNOWN 0。推測なし。
- **MIGRATED_PROVENANCE**（HISTORICAL v1.1.0）: 移行由来3,056文書の再評価
  ACCEPT 0→3,008・missing_raw_item warning 3,056→0（旧評価保持・捏造なし）。
- **Market trust v2**（MARKET_OBSERVATION v1.0.0）: provider経路provenanceで
  raw 3,432件再評価 ACCEPT 0→3,432・missing_supporting_evidence_ref 3,432→0
  （live run #5実測・旧評価保持）。
- **統一クエリ**: News複合（entity/theme/provenance/review status…）・Market複合
  （trading_date範囲/QA判定/revision/latest session）・cross-domain
  TradingWindow（JST朝・東京セッション・実データ導出の前米国セッション。
  UTC暦日join禁止・causal分析なし）・時系列集計（OBSERVED COUNTのみ）。
- **Health / Reconciliation**: state＋reason codes・critical gaps常時表示。
  会計恒等式 2,976＋25＋55＝3,056 ✅ **zero_unknown_loss: true**（機械判定）。
- **Backup/Restore演習**: manifest→copy→破壊検知（1 byte）→復元→SQLite再構築→
  クエリ等価まで自動テストで実証。実rootのmanifest作成・verify 0/0/0
  （runner側はephemeralであり「恒久backup済み」ではない）。
- **統合トレース**: news query→Article→SourceDocument→QA→enrichment→
  window→market観測→SQLite/query の全層貫通テスト（人間可読トレース出力）。

## 2. 会計サマリ（ZERO UNKNOWN LOSS）

```
News : 入力3,056 = documents 3,056 = annotations 3,056
       = distinct 2,976 + candidate 25 + revision 55 ✅
       articles = items = 3,001 / classifications 3,592（orphan 0）
       assessments 6,112（v1.0×3,056＋v1.1×3,056・削除なし）
Market: requested 15 = success 12 + gap 3 + failed 0
       canonical 16,512 = raw 3,432 + derived 13,080
       assessments 19,945（全観測＋再評価3,432＋daily QA 1・削除なし）
```

## 3. 残課題（隠さない）

| # | 課題 | 位置づけ |
|---|---|---|
| 1 | **TOPIX / JGB10Y / UST2Y 欠落**（G10/G11） | **Phase 3 blocker**。ETF・別期間・別概念yieldの代用は禁止（監督者裁定）。代替provider選定はユーザー/監督者判断 |
| 2 | market canonicalがActions runner上のみ（ephemeral） | 恒久保管はProduction phaseの設計事項（healthがDEGRADEDとして常時申告） |
| 3 | open review 88件 | 人間（ユーザー）の作業。機構は完成・実decisionは投入していない |
| 4 | 分類被覆59.5% | ja官庁文書等taxonomy対象外が主因。JP官庁向けtaxonomy拡張は提案のみ（承認待ち） |
| 5 | LLM層（L3）未使用 | key投入=ユーザー判断。validation/audit機構は実装済み |
| 6 | schema 0.x（1.0未凍結） | 意図的（Phase 3要求確定前に凍結しない） |
| 7 | yfinance依存はTier暫定評価 | Protocol差替可能・provider chain実装済み |

## 4. 判定

Phase 2の受入条件（説明可能・訂正可能・再構築可能・件数会計・provenance非妥協）
は全項目で機械検証を通過。テスト1,071件green。

**STATUS: PHASE2F_DATABANK_FINALIZATION_COMPLETE**
（監督者レビュー後に PHASE2_MARKET_NEWS_DATABANK_COMPLETE へ昇格可能）
