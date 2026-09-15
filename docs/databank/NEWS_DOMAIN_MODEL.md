# NEWS_DOMAIN_MODEL — News Bankドメインモデル（Phase 2-A）

## 1. identity階層（SourceDocument ≠ Article ≠ News Event）

| 概念 | 単位 | 所有 |
|---|---|---|
| SourceDocument | 1媒体×1取得×1正規化の文書 | P1-D（既存） |
| **ArticleIdentity** | 「同じ記事」の束（Reuters原文＋Yahoo転載＋別媒体転載） | **P2-A新設（モデルのみ）** |
| News Event | 「同じ出来事」の束（複数Articleを跨ぐ） | Phase 2後半以降（未実装） |

ArticleIdentity: article_id（`art_<sha256[:24]>`・代表キーから決定論導出）/
member_document_ids（≥1）/ canonical_url / representative_title / first_published_at /
**identity_basis**（exact_canonical_url / exact_guid / exact_fingerprint / manual —
束の根拠を必ず記録）。semantic clustering本体はP2-B（未実装）。

## 2. God NewsItem禁止の分割

```
NewsItem（記事索引・metadataのみ）
 ├─ NewsDocumentLink ──→ SourceDocument（PRIMARY / SYNDICATED / UPDATE）
 ├─ NewsClassification（分類1件=1レコード）
 ├─ NewsScore（スコア1件=1レコード）
 └─ LegacyAnnotation（tank旧INTERPRETED値の隔離）
```

NewsItemが持つのはmetadataのみ: headline / published_at / publisher / source_id /
language / canonical_url / summary（source提供のみ）/ guid / author（source明示のみ）/
entity_refs / theme_refs。**importance・theme・sentiment等のフィールドを持たない**
ことをテストで機械強制（分類・スコアの埋め込み禁止）。

## 3. CLASSIFICATION PROVENANCE（valueと出所の分離）

NewsClassification / NewsScore は必ず保持する:
- dimension（country/company/industry/sector/theme/event_type/time_horizon）または
  score_type（importance/market_impact/novelty/long_term_importance/user_relevance）
- value（NewsScoreはDecimal・float拒否）
- **provenance**: SOURCE_EXPLICIT / RULE_BASED / ENTITY_DATABASE / LLM / USER
- classifier/scorer name＋version・created_at

将来「theme=AI」と付いても「どこから来た分類か」が失われない。
**P2-Aでは自動score生成・LLM分類は未実装**（モデルのみ。EntityReferenceは
LLM provenanceでの構築を型レベルで拒否——推測taggingの侵入防止）。

## 4. FACT vs NEWS METADATA

headlineやpublisherはSourceDocument由来の**metadata**。
「売上が20%増えた」等のclaimは**Fact層**（P1-A Statement＋P1-E QA）。
P2-AではFact抽出をしない。NewsItemはFactStatementを内包しない。

## 5. LegacyAnnotation（tank INTERPRETED値の隔離）

tankのimportance_score / market_impact_score / urgency_score / structural_score /
sentiment / expected_direction / themes / event_type / primary_category は
`LegacyAnnotation`（値は文字列で凍結・note="not ground truth"）として隔離。
**新classification systemのGround Truthにしない**（NewsClassification/NewsScoreへ
自動変換しない）。dry runで8キーの隔離を実証。
