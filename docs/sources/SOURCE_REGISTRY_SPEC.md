# SOURCE_REGISTRY_SPEC — ソースレジストリ仕様（v3.0.0 / Phase 1-B）

2026-08-29。対象: `knowledge/source_reliability/source_feeds.yaml`（86ソース）と
`src/intelligence/sources/model.py` のPhase 1-B拡張。

## 1. 設計原則

1. **God object禁止**: 情報源を3概念に分離する。
   - `Source` … 情報源のidentity（slug ID・名前・格）— Phase 1-Aから継続
   - `SourceEndpoint` … 取得口の技術属性（URL・形式・認証方式・利用区分）
   - `SourceHealthObservation` … 死活観測の**時系列レコード**（1回の観測=1レコード）
2. **導出値を正とする**（監督者決定）: 「現在の死活状態」は観測列から導出する
   （`health_check.derive_current_state()` = 最新観測）。カタログの `current_health` は
   監査時点（2026-08-29）の導出結果のスナップショットであり、記録には
   `method`（根拠の種別）と `checked_at` を必ず併記する。
3. **HISTORICALLY_OBSERVED ≠ CURRENTLY_HEALTHY**: tank実績（2026-06-22..07-22）は
   `historical` レイヤーに隔離し、現在死活の根拠には使わない
   （テスト `test_historical_evidence_never_justifies_current_health` で機械強制）。
4. **Secretゼロ**: 認証はenum（`auth_type`）での分類記録のみ。キー値・トークン・
   資格情報つきURLはカタログ・観測レコード・本ドキュメント群に一切書かない。

## 2. カタログスキーマ（v3.0.0）

各feedエントリの層構造:

| 層 | フィールド | 内容 |
|---|---|---|
| identity | `id` `name` `lang` `country` `region` `primary_category` `origin` | 情報源の同定。`id` はvNext `Source.source_id` と一致 |
| 分類 | `source_class` `category` `tier` `trust_score` | `category` はSourceCategory enum値。`tier` はcategoryから機械導出（§SOURCE_CLASSIFICATION） |
| endpoint | `endpoint.url` `.declared_format` `.auth_type` `.usage_status` | 取得口。`declared_format` は検証済み証拠がある場合のみ具体値（無ければ `unknown`） |
| historical | `historical.tank_verification` `.tank_enabled` `.articles_observed{count,window}` | tank実績（観測窓 2026-06-22..07-22）。**過去実績の記録専用** |
| recent_ci | `recent_ci.window` `.days_observed` `.days_failed` | Legacy CI日次レポート実測（2026-08-16..29の14日）。CIがfetchしている24ソースのみ持つ |
| current | `current_health.state` `.method` `.checked_at` `.note` | 現在死活の導出結果。`method` が根拠種別 |
| 運用判断 | `investment_value` `role` `duplicate_group` `replacement_source` | 投資価値・取得役割・重複グループ・代替先 |

### 語彙（カタログ内 `vocabulary` ブロックと、Python enumのvalueが一致することをテストで強制）

- `current_health.state`: healthy / degraded / auth_required / rate_limited / moved / dead / unverified（`HealthState`）
- `current_health.method`: live_http / legacy_ci_report / tank_shards / static_analysis / live_check_blocked
- `endpoint.declared_format`: rss2 / atom / rdf / json_api / html / unknown（`FeedFormat`）
- `endpoint.auth_type`: none / api_key_header / api_key_query（禁止予定・記録用）/ bearer / other（`AuthType`）
- `endpoint.usage_status`: public_feed / api_terms / restricted / unknown（`UsageStatus`）
- `investment_value`: MARKET_CRITICAL / HIGH / MEDIUM / LOW
- `role`: CORE / SUPPORT / CONTEXT / DISABLE

## 3. ドメインモデル拡張（schema 0.2.0内の追加。0.x破壊は不使用）

`src/intelligence/sources/model.py` に追加（既存Source/RawItem/SourceDocumentは無変更）:

- enum: `SourceCategory` `HealthState` `AuthType` `FeedFormat` `UsageStatus`
- `SourceEndpoint(source_id, url, protocol, declared_format, auth_type, usage_status)`
  — URLはhttp(s)必須をコンストラクタで検証
- `SourceHealthObservation(health_obs_id, source_id, checked_at, state, http_status,
  final_url, permanent_redirect, content_type, detected_format, etag_present,
  last_modified, latest_item_at, freshness_age_hours, method, note)`
  — `checked_at`/`last_modified`/`latest_item_at` はtz-aware必須。
  `http_status=0` は「リクエスト不成立」。ID prefixは `shealth_`（ULID・時刻順）。
- 両dataclassは `core/serialization.register_domain_types()` に登録済み
  （JSONL永続化・roundtripテスト済み）。

## 4. 健全性履歴の時系列設計

- 観測は**追記のみ**: `SourceHealthObservation` をJSONLへ積む（Phase 1-Aの
  Evidence JSONLと同じパターン。fixture/リポジトリ水準であり、P1-Bでは
  ランタイム収集ジョブは実装しない）。
- 現在状態 = `derive_current_state(observations)`（最新checked_at）。将来、
  「直近N回のうちK回失敗でDEGRADED」等の窓判定へ拡張する場合も導出関数の
  差し替えで済み、保存データは不変。
- キャッシュを持つ場合は derived/cache と明示する（監督者決定③）。

## 5. 死活チェッカー（`src/intelligence/sources/health_check.py`）

- **transport注入式**: `Transport` Protocol（`get(url, timeout) -> FetchResult`）を
  外部から渡す。開発環境はegress遮断のためlive実行不能だが、判定ロジックは
  注入スタブで全状態オフラインテスト済み（`tests/intelligence/test_health_check.py`）。
  GitHub Actions等ネットワークのある環境では、urllib等で `Transport` を実装して
  そのまま実行できる。
- **最小アクセス**: 1フィード=1リクエスト・先頭サンプル（目安8KB）のみ。
  bulk収集・全文取得・バックフィルはしない（P1-C以降の責務）。
- 判定表は SOURCE_HEALTH_AUDIT.md §2 を正とする。

## 6. 変更履歴とv2からの差分

- v2.0.0の86ソース・tank実績・分類メタデータを**欠落なく**引き継ぎ（テストで件数固定）。
- フラットな `url`/`format`/`verification` を `endpoint`/`historical`/`current_health` の
  層構造へ再配置（verification → historical.tank_verification）。
- URL訂正1件: `marketwatch_market` … v2転記の `marketpulse` を、Legacy collectors実体
  （`src/collectors/marketwatch.py`）の `realtimeheadlines` へ訂正
  （`url_corrected_from` で旧値を保持）。
- `reference_only` / `skipped`（v1.0.0由来の方針記録）はv2から無変更で保持。
