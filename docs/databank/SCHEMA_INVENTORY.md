# SCHEMA_INVENTORY — スキーマ棚卸し（Phase 2-F PART J）

**方針: schema 0.xを維持する。1.0凍結はしない**（Phase 3以降の要求が確定する前に
凍結すると誤った契約を固定するため）。現行 `SCHEMA_VERSION = "0.4.0"`
（`core/types.py`）。

## 1. canonicalに共存する版

| 版 | 書込み時期 | 主な内容 |
|---|---|---|
| 0.3.0 | P2-C backfill時点 | News側レコード（documents/annotations等の初期書込み分） |
| 0.4.0 | P2-D以降 | trading_date追加（Observation）・market/enrichment/review系 |

**前方互換規約（0.x）**: 未知フィールドは無視・欠落フィールドはdataclass
defaultで補完。これにより0.3.0レコードは現行コードでそのまま読める
（reconciliationがschema_versions集合を毎回機械確認——PHASE2_RECONCILIATION.md）。
deprecatedフィールドは現時点で**なし**。破壊的変更（意味の変わる改名・型変更）を
入れる場合はminor版を上げ、旧版読取りを維持する。

## 2. 登録シリアライズ型（40型・`core/serialization.py`）

| 領域 | 型 |
|---|---|
| sources（P2-A） | Source / RawItem / SourceDocument / SourceEndpoint / SourceHealthObservation |
| ingestion（P2-A） | FetchAttempt |
| normalization（P2-A） | NormalizationIssue / NormalizationEvent |
| evidence_qa（P2-C） | DimensionResult / QAIssue / EvidenceAssessment |
| databank news（P2-B/C） | EntityReference / ThemeReference / ArticleIdentity / NewsItem / NewsDocumentLink / NewsClassification / NewsScore / LegacyAnnotation |
| databank identity（P2-B） | ArticleIdentityEvent / IdentityDecision |
| databank backfill（P2-C） | BackfillRun / RejectRecord |
| enrichment（P2-E） | EnrichmentEvent / ReviewQueueItem / EnrichmentRun |
| review（P2-F） | ReviewItem / ReviewDecisionRecord / IdentityLedgerEntry / RevisionRoleRecord |
| market（P2-D） | MarketSeries / Observation / SeriesRunResult / MarketBackfillRun |
| evidence（P2-C） | FactStatement / AnalysisStatement / ForecastStatement / ForecastMetadata / EvidenceLink |
| core | LLMResult |

## 3. ID規約（識別子は不変・内容導出）

- content-addressed（sha256[:24]・処理timestampは同一性に**含めない**）:
  `doc_ / raw_ / obs_ / art_ / news_ / cls_ / lga_ / rvw_ / rvd_ / idl_ / rvr_ / enr_`
- ULID（時系列レコード）: `fetch_ / qa_ / aie_ / bfr_ / mbf_ / erun_`

## 4. 永続化形式

- canonical: **JSONL append-only**（`{"type": ..., "data": ...}`封筒・
  crash-safe読取り・recovered_lines計測）＋blob store（sha256分割配置）
- 派生index: **SQLite**（いつでも全再構築可能。index⇔canonical件数一致を
  reconciliation/healthが常時確認）
- mutable status系（news_items / review_items）はappend-log latest-wins
  ——旧versionはログに残り、履歴削除は構造的に不可能
