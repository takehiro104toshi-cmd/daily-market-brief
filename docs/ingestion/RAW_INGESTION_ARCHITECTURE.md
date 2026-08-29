# RAW_INGESTION_ARCHITECTURE — Raw Ingestion全体設計（Phase 1-C / 2026-08-30）

目的: 外部Sourceから取得した情報を、改変・要約・AI解釈する前の **RAW SOURCE EVIDENCE**
として安全・再現可能・追跡可能に保存する。Fact抽出・正規化・分析・LLM処理は
P1-D以降（本ステージでは実装しない）。

## 1. パイプライン（God Fetcher禁止・1機能=1ファイル）

```
Source（identity・カタログ）
  → SourceEndpoint（取得口。endpoint_id=content-addressed）
    → FetchRequest ──HttpTransport(Protocol)──→ FetchResponse   [transport.py]
      → Fetcher（retry・conditional GET・redaction・編成のみ）  [fetcher.py]
        ├→ FetchAttempt（試行の時系列記録。**常に**生成）        [model.py]
        └→ RawItem ＋ content blob（200時のみ）                 [raw_store.py]
          → feed_parser（RSS2/Atom/RDF検出・entry抽出）          [feed_parser.py]
            ├→ url_normalize（canonical。originalは常時保持）    [url_normalize.py]
            ├→ date_quality（source提供/naive/欠損の分類のみ）   [date_quality.py]
            └→ dedup（exact系のみ）                              [dedup.py]
```

| モジュール | 責務 | 責務外（どこへ） |
|---|---|---|
| transport.py | HTTP 1回分の送受信・redirect chain記録・エラー分類・redact_url | retry判断（fetcher）・保存（store） |
| fetcher.py | retry方針・conditional GET・Attempt/RawItem組み立て | HTTP実装・パース・スケジューラ（Phase 12） |
| raw_store.py | immutable保存・atomic write・hash検証・冪等・読み戻し | 意味解釈 |
| feed_parser.py | 形式検出・正規化前entry抽出（無損失） | Fact化（P1-D）・意味dedup（Phase 2） |
| model.py | FetchRequest/Response/Attemptの型と不変条件 | — |

## 2. CORE PRINCIPLE: RAW DATA IS IMMUTABLE

- 取得した原データは**上書きしない**。同一URLから内容が更新された場合、
  content-addressed ID（`raw_<sha256(source,locator,content_hash)[:24]>`）が変わるため
  **新RawItemとして積まれ、旧versionはそのまま残る**（テストで機械検証）。
- blobはcontent-addressed（`blobs/<h[:2]>/<sha256>`）で物理dedupされるが、
  「どのsourceからいつ取得したか」のprovenanceはRawItem/FetchAttemptが**試行ごとに**保持。
- 削除・変更APIは提供しない（append-only）。

## 3. FetchAttemptの分離（取得試行 ≠ 取得物）

304 / timeout / 403 / 500 ではRawItemが生まれない。取得試行そのものを
`FetchAttempt`（`fetch_<ULID>`・時刻順）として**必ず**時系列保存する:

- 条件付きGETのvalidator（ETag/Last-Modified）は**Attempt列から導出**（二重保存しない
  — P1-B「導出値を正とする」原則と同型）。
- P1-BのSourceHealthObservationとは役割分担: Attempt=取得の生記録、
  HealthObservation=死活判定の記録。後者は前者から導出可能（P1-C live validationで実証）。
- 失敗はstructured failure（error_kind: timeout/dns/tls/connection/protocol/unknown ＋
  detail）。**silent failure禁止**・1ソースの障害でrun全体を落とさない（source isolation）。

## 4. Legacy/tank資産の移植（COPY CONCEPT / MIGRATE PURE LOGIC）

| tank資産 | 移植先 | 移植方法 |
|---|---|---|
| feed_parser.py（RSS2/Atom・stdlib ET・malformed耐性・CDATA/entity・上限） | ingestion/feed_parser.py | 純ロジック移植＋**RDF対応追加**＋vNext型（FeedEntry/FeedParseResult）へ適合。日時のFact化はやめ文字列保持へ変更 |
| fetcher.py（transport注入・条件付きGET・no-retryステータス・source isolation） | ingestion/fetcher.py + transport.py | 概念移植。requests依存を捨てstdlib urllibへ。FetchAttempt記録を新設 |
| cursor.py（ETag/Last-Modified永続・atomic write） | raw_store.py latest_conditional() | cursorファイルを廃し**Attempt列からの導出**へ設計変更（二重保存しない） |
| url_normalize.py | ingestion/url_normalize.py | ほぼそのまま（検証済み純関数）。original_url保持を型で明示 |
| date_quality.py（date_inferred/raw_published_at/anomaly分類） | ingestion/date_quality.py | 概念移植。**補正はしない**設計へ変更（fetched_at採用はP1-Dの明示判断） |
| dedup.py（canonical/content/title hash） | ingestion/dedup.py | exact系（hash/URL/GUID）のみ移植。title_hash系はPhase 2 |
| atomic write（mkstemp→os.replace） | raw_store.py BlobStore | パターン移植 |

tank repository本体はREFERENCE ONLYのまま（無変更を維持）。
Legacy（src/collectors等）へのimportはゼロ（境界テストで機械強制）。

## 5. スコープ外（DO NOT — 未実装の明示）

P1-D正規化・Fact抽出・分析・予測・LLM呼出・semantic dedup・entity解決・
テーマ分類・歴史バックフィル・常駐スケジューラ・Morning Brief・本番DB。
EDINET/e-Statの本格API正規化もP1-D以降（現状はadapter契約とauth注入設計のみ）。
