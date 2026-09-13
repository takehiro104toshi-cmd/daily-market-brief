# CLASSIFICATION_PROVENANCE_SPEC — 分類provenance仕様（Phase 2-E）

原則: **EVERY ENRICHMENT MUST HAVE PROVENANCE**。

## 1. レコード構造（NewsClassification・P2-E拡張後）

必須: classification_id（決定論: item×dimension×value×classifier:version）/
news_item_id / dimension / value / **provenance** / **classifier_name** /
**classifier_version** / created_at。

P2-E追加（0.x非破壊）:
- `confidence`（Decimal 0..1・**confidence_typeとセットでのみ**）＋`confidence_type`
- `role`（primary / secondary / mention——強制しない）
- `evidence_field`＋`evidence_text`（マッチ根拠のフィールドと**verbatim抜粋**。
  全文コピーなし。validationが実テキストとの含有を機械照合——evidence_span_mismatch検知）
- `taxonomy_version`（使用カタログ/taxonomyの版）
- `basis_document_id`（分類時のprimary document——revision連鎖の追跡）

## 2. provenance 5種と優先順位

| provenance | 生成元 | classifier_name例 |
|---|---|---|
| SOURCE_EXPLICIT | source明示提供（カテゴリ欄・ticker欄） | source_metadata_import |
| ENTITY_DATABASE | entity catalogの決定論マッチ | entity_matcher |
| RULE_BASED | taxonomy規則の決定論マッチ | theme_rule_matcher / event_rule_matcher / horizon_rule_matcher |
| LLM | LLM分類（optional・検証済みのみ） | llm_classifier:\<provider\>:\<model\> |
| USER | 手動override | user_override |

effective view優先順位: **USER > SOURCE_EXPLICIT > ENTITY_DATABASE > RULE_BASED > LLM**
（SOURCE_EXPLICITはLLM推定より優先——監督者指定の設計をstore導出で実現）。

## 3. confidenceの意味論（雑に統一しない）

| confidence_type | 意味 | 値 |
|---|---|---|
| （なし） | 決定論マッチ（exact/rule）——確率で表現しない | confidence=None |
| llm_stated | LLM自己申告の確信度 | Decimal 0..1（範囲外はreject） |

決定論分類の「確からしさ」はprovenance・matched_via・evidenceが表す
（1つのスコアへ潰さない）。

## 4. country分類のfield意味論（COUNTRY CLASSIFICATION）

P2-Eのcountry次元 = **article subject country（記事の主題国。本文中の明示mention）**。
publisher country / 企業domicile / market affected は別概念:
- 企業domicile … entity catalogの`country`属性（分類ではない）
- publisher country / market affected … 未実装（実装時は別classifier_nameで区別）

## 5. イベントモデル（append-only監査）

EnrichmentEvent: ADD_CLASSIFICATION / OVERRIDE / RETRACT / REVIEW_QUEUED。
OVERRIDE/RETRACTは`previous_classification_id`必須（履歴保持——旧レコードは消えない）。
manual overrideの競合はvalidation（override_conflict）が検知。

## 6. 冪等・再分類

- classification_idはcreated_at（処理時刻）を含まない——run跨ぎ再実行は冪等skip
  （P2-E実コーパス実行で校正した設計: semantic equalityの原則）。
- classifier/taxonomyのversion更新による再分類は**新レコード追記**（履歴共存。
  effective viewが1代表を導出）。
