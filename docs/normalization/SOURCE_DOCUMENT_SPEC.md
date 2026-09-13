# SOURCE_DOCUMENT_SPEC — SourceDocument生成仕様（Phase 1-D）

P1-A SourceDocumentを実RawItemから生成する。追加フィールドは全て0.x非破壊
（default付き）。

## 1. フィールドとtrace

| フィールド | 由来 | 備考 |
|---|---|---|
| source_document_id | `content_id(raw_item_id, entry_key, normalizer, version)` | 決定論・再現可能 |
| source_id / source_tier | SourceMeta（カタログ） | tierは取得時点スナップショット |
| title | entry.title → normalize_title | NFC・entity復号・空白のみ（翻訳・意味変更禁止） |
| locator | entry.link_original | **originalを絶対に失わない** |
| canonical_locator | entry.link_canonical | dedup補助。provenanceの代替ではない |
| published_at / published_raw / date_quality / published_inferred / published_inferred_from | dates.normalize_published | DATE_NORMALIZATION_SPEC参照 |
| retrieved_at | RawItem.retrieved_at | 取得時刻（公表時刻と混同しない） |
| language | SourceMeta.default_language → normalize_language | BCP-47系。不明は"und" |
| content_hash | sha256(entry.raw_xml) | 由来entryのバイト同一性 |
| content_fingerprint | normalized title+summaryのsha256 | minor markup差分比較用（semantic dedupではない） |
| raw_item_id | RawItem | 空=原文非保存の明示（tank記事等） |
| guid | entry guid / Atom id / rdf:about / tank article_id | revision判定・dedupの鍵 |
| summary | summary_excerpt → normalize_text | 短い抜粋のみ（本文全文は持たない） |
| media_type | RawItem.media_type | |
| revision_of | detect_revision() | §3 |
| normalizer_name / normalizer_version | 生成元 | 再処理のtrace |

## 2. PROVENANCE CHAIN（「このニュースはどこから来たのか」への1本のchain）

```
SourceDocument.raw_item_id → RawItem
RawItem.fetch_attempt_id   → FetchAttempt（いつ・どのHTTP応答から）
RawItem.endpoint_id        → SourceEndpoint（どの取得口から）
RawItem.source_id          → Source（どの情報源から。カタログslug一致）
```
テスト`test_documents_created_with_full_provenance_chain`で逆引きを機械検証。

## 3. identity階層（混同しない）

| identity | 定義 | 解決時期 |
|---|---|---|
| RawItem identity | 取得物の内容（content-addressed） | P1-C済 |
| **SourceDocument identity** | **正規化出力の単位（RawItem×entry×normalizer version）** | **P1-D（本仕様）** |
| Article identity | 記事としての同一性（再取得・別ソース間の名寄せ） | Phase 2（未解決でよい） |
| Canonical URL identity | dedup補助キー | P1-C済（補助のみ） |

versionをIDに含めることで再処理が非破壊になる（v2は新ID）。同一記事が別fetchで
再取得された場合は別SourceDocumentになるが、content_fingerprint / canonical_locator /
guidがPhase 2のArticle統合の材料として保持される。

## 4. REVISION HANDLING（決定論的）

同一publisher/locatorで内容が更新された場合、旧SourceDocumentは削除せず新Documentを作る。
`detect_revision`のルール:

- 同一source_id×同一guid（非空）の既存文書の**最新版がちょうど1件**で、
  content_fingerprintが異なる → その文書をrevision_ofに設定。
- fingerprintが同一（同内容の再配信）→ revisionではない（relationなし）。
- 候補が0件・複数最新（分岐）・guidなし → **曖昧なのでrelationを付けない**。

## 5. tank記事互換（tank_article_normalizer）

tank記事dict→SourceDocument変換を実装し、実shardスキーマの代表sampleで検証済み
（3,056件のfull migrationはPhase 2）。tankのdate_inferred=Trueは
published_inferred=True / inferred_from="tank_fetched_at" として機械可読に引き継ぎ、
raw_published_at（元文字列）を保持。INTERPRETED系フィールドは取り込まない。
