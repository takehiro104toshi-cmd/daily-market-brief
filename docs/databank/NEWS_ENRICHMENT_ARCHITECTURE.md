# NEWS_ENRICHMENT_ARCHITECTURE — News分類・enrichment層（Phase 2-E）

原則:
- **CLASSIFICATION IS NOT FACT** — 「この記事はAIテーマ」という分類と「NVIDIAが売上を
  発表した」というFact claimは別物。P2-EはFact抽出を一切行わない（Fact層はP1-Aのまま）。
- **EVERY ENRICHMENT MUST HAVE PROVENANCE** — 全分類が value / provenance /
  classifier_name / classifier_version / created_at /（該当時）confidence を持つ。
- **FALSE ENTITY LINK IS WORSE THAN MISSED ENTITY LINK** — 曖昧ならlinkしない。

## 1. 層分離（ENRICHMENT LAYERS）

| 層 | 内容 | provenance |
|---|---|---|
| L0 | NewsItem既存metadata（entity_refs/theme_refs・source提供カテゴリ）取込 | SOURCE_EXPLICIT |
| L1 | 表記正規化（alias→正準entity_id/ISOコード/slug。意味推論なし） | （L2の内部） |
| L2 | entity / theme / event type / time horizonの決定論マッチ | ENTITY_DATABASE / RULE_BASED |
| L3 | LLM分類（**optional**。提案→検証→canonical） | LLM |
| L4 | 手動override（優先・履歴保持） | USER |

実装: `src/intelligence/enrichment/`（model / textmatch / catalog / taxonomy /
entity_matcher / theme_matcher / event_matcher / llm_classifier / override /
engine / store / backfill / validation / quality_report——1機能=1ファイル）。

## 2. NO DESTRUCTIVE UPDATE

- NewsItem本体は書き換えない。分類はappend-onlyの別レコード
  （`news/enrichment/classifications.jsonl`）＋EnrichmentEvent監査履歴。
- Article revision・classifier version更新の再分類は**追記**（旧version保持）。
- 「現在有効な分類」は履歴からの**導出**（effective view: USER > SOURCE_EXPLICIT >
  ENTITY_DATABASE > RULE_BASED > LLM、RETRACT/OVERRIDE済みを除外）。

## 3. LLM層の必須条件（実装済み・本phaseでは未使用）

- core `LLMProvider` Protocolのみに依存（Anthropic/OpenAIをdomainへ埋め込まない）
- `is_available()=False`ならskip——**LLMなしでもData Bank全体が動く**
- 出力はJSONスキーマの決定論バリデーション。taxonomy外labelはcanonicalへ入れず
  ReviewQueue（LLM_UNKNOWN_LABEL）、不正出力はreject（LLM_INVALID_OUTPUT）
  ——**NO FREE-FORM DATABASE POLLUTION**
- provider/model/prompt schema version/generated_at/生応答をllm_audit.jsonlへ保存
- confidenceはDecimal 0..1・confidence_type="llm_stated"（決定論のconfidenceと
  雑に統一しない）

## 4. ReviewQueue（黙って捨てない）

canonicalへ入れなかった候補の置き場（冪等・重複積み上げなし）:
ambiguous_alias（文脈条件を満たさなかった曖昧alias）/ unknown_ticker
（明示記法だがカタログ未登録）/ llm_unknown_label / llm_invalid_output。
処理ワークフロー（人間レビュー）はP2-F。

## 5. 検索・時系列foundation

- SqliteNewsIndex（P2-A）の`classifications`テーブルをそのまま利用
  （entity/ticker/country/theme/event_typeでのAND検索・canonicalから全再構築可能）。
- 時系列foundation（Phase 6 Trend Engineの**query契約のみ**）:
  `count_by_dimension_over_time(dimension, granularity=day/week/month)` /
  `count_values(dimension)`。件数取得まで——「AIテーマが加速」等の分析文は生成しない。

## 6. DO NOT（本phaseで作らなかったもの）

Fact extraction / NewsEvent clustering / market impact・importance・sentimentスコア /
Prediction Journal / Theme Map engine / Compass Generator / Morning Brief / frontend /
scheduler。エンジンはbullish/bearish等の値を構造的に生成しない（テスト固定）。
