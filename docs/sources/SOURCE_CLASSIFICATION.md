# SOURCE_CLASSIFICATION — ソース分類（Phase 1-B / 2026-08-29）

3軸を混同しない: **格（tier/category）** × **投資価値（investment_value）** ×
**取得役割（role）**。健全性（current_health）はこの3軸と独立の観測導出値。

## 1. カテゴリ → Tier 対応（機械導出・テスト強制）

| SourceCategory | 対応source_class | Tier | 件数 |
|---|---|---|---|
| PRIMARY_OFFICIAL | primary_official / regulator / statistics_agency / exchange / international_institution | 1 | 39 |
| HIGH_QUALITY_SECONDARY | major_news / specialist_media | 2 | 42 |
| GENERAL_SECONDARY | aggregator | 3 | 5 |
| MARKET_DATA_PROVIDER | （フィードカタログ内は該当なし。yfinance/Stooq/FREDは `reference_only` 管理でPhase 2のmarket store担当） | 2 | 0 |
| OTHER | — | 3 | 0 |

## 2. 投資価値（investment_value）

判定基準（明示テーブル `gen_v3.py`＝再現可能。未掲載はMEDIUM）:

- **MARKET_CRITICAL（12）**: 金融政策・主要統計・財政の一次発信。
  Fed / BOJ×2 / ECB×2 / MOF×2 / BLS×2 / 総務省統計局 / 米財務省 / e-Stat
- **HIGH（33）**: 相場直結の報道・規制当局・法定開示・準主要中銀。
  Bloomberg / CNBC×2 / WSJ / MarketWatch×3 / Yahoo Finance / 日経 / NHK経済 /
  Yahoo経済 / SEC / EDGAR×4 / EDINET / FSA / JPX / BOE / RBA / IMF / Census /
  BEA / ONS / EIA / 官邸 / METI / 内閣府 / ロイター系×2 / uk_gov ほか
- **MEDIUM（37）**: 文脈情報（一般報道・専門メディア・業界誌）
- **LOW（4）**: allafrica_headlines / mercopress / lightreading / greenbiz

## 3. 取得役割（role）の決定規則

適用順:

1. state=DEAD → **DISABLE**
2. 重複グループのshadow（同一コンテンツ系統の非primary） → **DISABLE**（replacement_source=primary）
3. MARKET_CRITICAL → **CORE**（ただしAUTH_REQUIREDはキー設定まで**SUPPORT**）
4. HIGH → **SUPPORT**
5. MEDIUM → **CONTEXT**
6. LOW → HEALTHYなら**CONTEXT**、非HEALTHYなら**DISABLE**

結果: **CORE 7 / SUPPORT 30 / CONTEXT 37 / DISABLE 12**

### CORE（7）＝日次ブリーフの必須ソース

| id | tier | 現在状態 | 備考 |
|---|---|---|---|
| fed_press | 1 | degraded | UA疑い。P1-Cで適正UA接続を最優先検証 |
| boj_whatsnew | 1 | unverified | EN版（tank実績36記事）。JP RDF版はshadow |
| dmb_ecb_press | 1 | healthy | CI 14/14配信。ECB系のprimary |
| mof_whatsnew | 1 | degraded | RDF非対応疑い。P1-C RDFアダプタで検証 |
| bls_latest | 1 | healthy | CI 14/14配信。BLS系のprimary |
| us_treasury | 1 | unverified | P1-C初回検証必須 |
| jp_stat_release | 1 | unverified | P1-C初回検証必須 |

（estat_macroはMARKET_CRITICALだがAUTH_REQUIREDのためSUPPORT。キー設定後にCORE昇格候補）

## 4. 重複グループ（7グループ・同一発行者/同一コンテンツ系統）

| group | primary（取得する） | shadow等（DISABLE） | 備考 |
|---|---|---|---|
| boj | boj_whatsnew（EN・tank実績36） | dmb_boj_whatsnew（JP RDF・degraded） | 同一発信の言語違い |
| mof | mof_whatsnew（CI対象） | jp_mof_press（unverified） | |
| ecb | dmb_ecb_press（press.xml・healthy） | ecb_press（press.html・tank実績16） | 同一プレス系統 |
| bls | bls_latest（healthy・上位集約） | us_bls（news_release個別） | |
| marketwatch | dmb_marketwatch_top（healthy） | marketwatch_top（dowjones.io版） | marketwatch_market（別系統・SUPPORT）も同グループでdedup対象 |
| reuters | —（両方DEAD） | reuters_business / yahoo_jp_reuters | 代替: yahoo_finance_us_all等 |
| cnbc | 両方取得（Top News / Investingの別系統） | なし | dedupはPhase 2エンジン |

規則: **1グループにCOREは高々1件**（テスト強制）。shadowのreplacement_sourceは
同グループのprimaryを指す。

## 5. パーサー形式インベントリ（P1-Cアダプタ計画の入力）

wire実証済みの証拠がある形式のみ具体値、未実証は `unknown`:

| declared_format | 件数 | 根拠 / P1-Cアダプタ |
|---|---|---|
| rss2 | 21 | CI 14/14配信（LegacyのRSS2系パーサーで解釈できている）＋v2明示rss。→ **RSS2アダプタ（最優先）** |
| atom | 7 | uk_gov / jp_meti_release / theverge / us_edgar_8k・10q・10k・6k。→ **Atomアダプタ（旧系の欠陥解消。EDGAR系が依存）** |
| rdf | 3 | nikkei（DEAD）/ dmb_boj_whatsnew / mof_whatsnew。→ **RDF(RSS1.0)アダプタ（CORE mof系の復旧に必要）** |
| json_api | 2 | edinet_disclosures / estat_macro。→ **JSON APIアダプタ（キー設定後）** |
| html | 0 | （カタログ内なし。kabutan等スクレイピング系は `skipped` 方針記録のまま） |
| unknown | 53 | tank auto検出のみでwire未実証。P1-C初回接続時に `health_check.classify_format` で実測確定 |

## 6. 使用区分・認証

- `usage_status`: public_feed 84 / api_terms 2（EDINET・e-Stat）
- `auth_type`: none 84 / api_key_query 2（**禁止予定の記録用**。P1-C実装時は
  ヘッダー渡し可否を確認し、不可の場合もキーはログ・エラー文字列へ出さない
  — tank T7の教訓、docs/security/DATA_CLASSIFICATION_POLICY.md準拠）
