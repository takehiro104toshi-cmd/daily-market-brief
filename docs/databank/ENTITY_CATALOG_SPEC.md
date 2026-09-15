# ENTITY_CATALOG_SPEC — Entity Catalog仕様（Phase 2-E）

正本: `knowledge/entities/core_entities.yaml` v1.0.0（versioned knowledge asset）。
loader/validator: `src/intelligence/enrichment/catalog.py`。

## 1. 規模と方針

80 entities（**巨大な全世界企業DBを作らない**）:
- COMPANY 36 … Compass対象watchlist全銘柄（JP 17・US 13）＋コーパス頻出6
  （OpenAI/Intel/Samsung/BlackRock/日本製鉄/Boeing）
- COUNTRY 18（US/JP/CN/TW/KR/KP/IN/GB/DE/FR/EU/RU/UA/IR/IL/SA/HK/SG。
  EUはblocであることをnoteで明示）
- CENTRAL_BANK 5（Fed/BOJ/ECB/BOE/PBOC）・GOVERNMENT 2・PERSON 3
  （Powell/植田/Trump——最小限）
- INDEX 7（**market catalogのinstrument_idと同一ID**——bank横断の結線点:
  index:nikkei225等）・COMMODITY 5・CURRENCY 4（BTCはcurrency扱いをnote明示）

## 2. alias安全度（COMPANY ALIAS SAFETY / TICKER SAFETY）

| 種別 | 規則 | 例 |
|---|---|---|
| aliases_safe | 単独マッチ可（固有性の高い表記のみ） | NVIDIA・トヨタ・Tokyo Electron |
| aliases_context | **context_termsの共起が必須**。共起なし→linkせずReviewQueueへ | Apple（iPhone/Tim Cook/AAPL…）・Meta（Facebook/Zuckerberg/data center…）・Amazon・Alphabet・Arm・Fed |
| ticker | **明示記法のみ**: `$NVDA` / `NASDAQ:NVDA` / `(7203.T)`。裸の大文字語は走査すらしない | AI/IT/US/CATがtickerに誤爆する経路が構造的に存在しない |

大文字小文字規則（textmatch.py）:
- 全大文字略語（AI/EV/US/NATO…）… 大文字表記そのままの単語境界マッチのみ
- `=`プレフィクス … 明示case-sensitive（`=Fed`は動詞fedへ、`=Trump`は動詞trumpへ、
  `=Apple`は果物appleへ誤爆しない——実測で校正済み）
- その他ASCII … case-insensitive単語境界／日本語 … 部分一致

未知ticker記法（例: NASDAQ:SNDK）はlinkせず`unknown_ticker`としてReviewQueueへ
（実コーパスで5件検出——カタログ拡張の候補リストとして機能）。

## 3. 属性と分類の分離（COUNTRY / SECTOR意味論）

- entityの `country` = **domicile**（会社の属性）・`sector`/`industry` = 会社→業種mapping。
- 記事分類のcountry次元 = **subject country（記事の主題国）**
  （classifier_name=`entity_matcher`・値はISOコード）。publisher国・影響市場とは別概念
  （fieldの意味はCLASSIFICATION_PROVENANCE_SPEC参照）。
- **記事→sector自動分類はP2-Eでは行わない**（会社mention→当該会社のsectorを記事の
  sectorとみなす混同を避ける。sector語彙のみ定義済み——将来の明示ルールで）。

## 4. 検証（load時＋validation）

- entity_id形式 `<kind>:<slug>`・kind一致・ID重複拒否
- 文脈必須aliasはcontext_terms必須（型で強制）
- companyのsector/industryは語彙表と照合・countryはcode必須
- enrichment validationがENTITY_DATABASE由来分類の値をカタログと照合
  （unknown_entity_value検知）

## 5. 変更管理

カタログ変更は`version`を上げる（分類レコードの`taxonomy_version`と
run manifestに使用版が記録され、どの定義での分類か監査可能）。
entity_idの意味変更は禁止（変更は新entity_id）。
