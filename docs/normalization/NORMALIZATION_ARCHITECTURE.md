# NORMALIZATION_ARCHITECTURE — 正規化層全体設計（Phase 1-D / 2026-08-30）

目的: P1-Cで保存した異種Raw data（RSS2/Atom/RDF/JSON/tank記事）を、OS全体が同じ形式で
利用できる **NORMALIZED EVIDENCE LAYER** へ変換する。

## 1. レイヤー分離（P1-Dの境界）

| レイヤー | 内容 | 所有 |
|---|---|---|
| RAW | 取得した原データ（immutable blob＋RawItem） | ingestion/ |
| PARSED | 構造を読んだtransient（FeedEntry / JSON dict） | ingestion/feed_parser 等 |
| **NORMALIZED** | 共通domain語彙（SourceDocument / Observation） | **normalization/（本層）** |
| INTERPRETED | 意味・因果・投資判断（Fact/Analysis/Forecast） | P1-E以降（本層では禁止） |

**NO AUTOMATIC FACT CLAIMS**: 「日銀、政策金利を引き上げ」というタイトルを取得しても
FactStatementは生成しない。SourceDocumentとして保存するまでが本層の責務
（Fact claim抽出は別ステップでEvidence QA対象）。tankのINTERPRETED系フィールド
（importance/themes/sentiment等）もtank互換normalizerが意図的に取り込まない（テスト強制）。

## 2. パイプラインとモジュール（1機能=1ファイル）

```
RawItem ＋ body(blob)
  → feed_normalizer.normalize_feed_raw_item()      … RSS2/Atom/RDF共通entry→SourceDocument
  → observation_normalizer.normalize_json_observations() … 明示mapping→Observation
  → tank_article_normalizer.normalize_tank_article()     … tank記事dict→SourceDocument
       │ 共通部品: text.py（NFC/空白/entity/fingerprint） dates.py（日付正規化・URL推定）
       │           language.py（BCP-47系） units.py（pct/bps/ratio変換）
       ▼
NormalizationResult { status, documents, observations, issues, event }
  → store.JsonlNormalizedStore（data/vnext/normalized/・append-only）
```

## 3. 決定論（NORMALIZATION MUST BE DETERMINISTIC）

同じRawItem＋同じnormalizer versionから**必ず同じ結果**（ID含む）:

- LLM・乱数・外部検索を一切使わない（コード上依存ゼロ。境界テストで担保）。
- 現在時刻非依存: 日付異常判定（future/too_old）の基準は`RawItem.retrieved_at`。
- ID決定論: SourceDocument ID＝`content_id(raw_item_id, entry_key, normalizer, version)`、
  Observation ID＝`content_id(raw_item_id, entity, metric, as_of, version)`。
- 処理時刻（normalized_at）は**NormalizationEventのみ**が持つ（record contentと
  processing eventの分離——semantic equalityがnormalized_atで崩れない）。
- テスト`test_deterministic_same_input_same_output_including_ids`で機械検証。

## 4. NormalizationResult / Issue（silent correction禁止）

- status: **NORMALIZED**（issueなし）/ **PARTIAL**（出力あり＋issue。例: title有・date不明）/
  **REJECTED**（必須identity不成立で出力ゼロ。**RawItemは消さない**）。
- issue語彙（`ISSUE_CODES`）: missing_title / missing_date / invalid_date / naive_date /
  date_anomaly_future / date_anomaly_too_old / unsupported_format / malformed_entry /
  invalid_numeric / unknown_currency / missing_required_field / encoding_issue / missing_locator。
- issueはNormalizationEventへ構造化保存（entry_ref付き）。黙って補正しない。

## 5. 再処理（REPROCESSING）

normalizer v1→v2の変更時、**raw storeから再normalizationできる**（再取得不要）:
IDにversionが入るためv2出力は新レコードとなり、v1出力は破壊されない（storeは
append-onlyで上書きAPIなし）。テスト`test_reprocessing_v2_creates_new_ids_preserves_v1` /
`test_v1_v2_coexist_without_overwrite`で検証。

## 6. Repository契約

`core/contracts.py`へ追加: SourceDocumentRepository / ObservationRepository /
NormalizationEventRepository。参照実装 `JsonlNormalizedStore` が3つ全て充足
（isinstance機械検証）。将来SQLite/Postgres差し替えでもdomain/normalizer無変更。

## 7. DESIGN CORRECTION 1 対応（runtime credential注入）

`ingestion/auth.py`＋`UrllibTransport(auth_headers_provider=...)` を追加:

```
Persisted FetchRequest（Secretなし・型レベル拒否は維持）
  → CredentialResolver（環境変数から解決。EnvCredentialResolver）
    → Ephemeral Transport Request（Secretはメモリ内のみ）
      → HttpTransport
```

SECRET MUST NEVER BE PERSISTED（serialization/JSONL/RawItem/FetchAttempt/log/
error detailへ流れない——テストで検証）だが、使用は可能。本格credential runtimeは
P1-E以降（枠組みのみ）。
