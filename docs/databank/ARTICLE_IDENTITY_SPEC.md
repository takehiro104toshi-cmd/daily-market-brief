# ARTICLE_IDENTITY_SPEC — Article Identity Layer仕様（Phase 2-B / 2026-08-30）

目的: 複数SourceDocumentを「同一記事 / 転載 / 更新版 / 別記事」として安全に識別する。

## 1. CORE SAFETY PRINCIPLE

**FALSE MERGE IS WORSE THAN MISSED MERGE.**
高precision・保守的threshold・曖昧なら別Article。fixture上の目標: false merge = 0
（達成——IDENTITY_CALIBRATION_REPORT.md）。

## 2. レイヤー（混同禁止）

SourceDocument（取得1文書）→ **Article（同一記事のidentity・本仕様）** → NewsEvent
（同一出来事の複数Article cluster・P2-E以降）。

## 3. 判定ステージ（identity_resolver.py）

| STAGE | 内容 | 判定 |
|---|---|---|
| 1 EXACT | canonical URL一致 / source内GUID一致 / content fingerprint一致（**両者にsummaryがある場合のみ**）/ 生entry hash一致 | EXACT_MATCH・REVISION・SYNDICATED |
| 2 NEAR-DUP | 複数signal AND（title≥0.85・summary≥0.80・時刻≤48h・**数字トークン一致**） | AUTO_MERGE |
| 3 AMBIGUOUS | title≥0.70等の部分一致 | CANDIDATE（**絶対にmergeしない**） |
| 4 NO MATCH | — | DISTINCT（新Article） |

### 安全規則（テストで機械固定）

- **GUIDはsource-local**: 別publisher間のGUID一致ではmergeしない（記録のみ）。
- **same URL + changed content = REVISION**（duplicateではない）。
- **title類似単独ではmergeしない**（title 1.0でもsummary証拠なしなら非merge）。
- **summary（内容証拠）が無いペアはSTAGE 2発動不可**——title-onlyのfingerprint一致も
  exact扱いしない（定型見出し対策。実tank40ペアのハザードコーパスで検証）。
- **数字トークンガード**: タイトルの数字集合が異なればAUTO_MERGE禁止
  （実データ由来: ECB 2027/2028・Bloomberg日付連載・FedReg #1/#2/#3が上位ハザード）。
- URL正規化はtracking除去のみ（aggressive path正規化・slug推測・domain書換は禁止。
  original URLは常に保持——P1-C/P1-D規律の継続）。

## 4. IdentityDecision（Black Box禁止）

decision / document_id / matched_article_id / confidence（補助値・Decimal）/
**matched_signals / failed_signals**（語彙固定16種）/ reason_codes /
**algorithm_version**（再現・再校正のtrace）。単一scoreにしない。

## 5. ArticleIdentity（runtime）

article_id（`art_<sha>`決定論）/ member_document_ids / identity_basis /
canonical_url / representative_title。**現在状態はevent replayの導出値**
（ARTICLE STORE参照）。processing timestampはeventのみが持つ（semantic分離）。

## 6. PRIMARY DOCUMENT選定（identity_runtime.select_primary）

優先順: (1)非転載 (2)最先published（原文が先に出るのが通例。**「Tier高=原文」とは
限らない**ため時刻が先） (3)tier (4)ID辞書順。決定根拠（basis文字列）をSET_PRIMARY
eventのnoteへ保持。

## 7. NewsItem runtime

SourceDocument→ArticleIdentity→NewsItem（metadata container）を接続。
**Article=identityオブジェクト、NewsItem=databank表現**——IDは
`news_<sha(article_id)>`で1:1導出だが別型・別名前空間（将来NewsEvent層による
representation再編を阻害しないため完全同義にしない）。NewsDocumentLinkが
PRIMARY/SYNDICATED/UPDATEのroleを持つ。Fact抽出・分類・スコア生成はしない。
