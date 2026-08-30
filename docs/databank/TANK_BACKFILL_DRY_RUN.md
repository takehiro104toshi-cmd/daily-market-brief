# TANK_BACKFILL_DRY_RUN — tank移行dry run＋Article identityシグナル分析（Phase 2-A / 2026-08-30）

対象: article-intelligence-data-tank記事ストア **3,056記事**（READ ONLY・
2026-06-22..07-22）。**full migrationは未実施**（P2-Cで正式backfill）。

## 1. 代表sample dry run（20件）

選定（quota方式・publisher偏り上限3件/社）: 日本語3（tank内ja全15件から）/
description欠損4 / theme metadata付きEN 5 / 一般EN 8。9 publishers
（BOJ・Fed・Federal Register・EIA・DW・BBC・Japan Times等）。

| 検証項目 | 結果 |
|---|---|
| 正規化（tank_article_normalizer） | **20/20 NORMALIZED**（issueゼロ） |
| Data Bank validation gate | **issues 0件**（duplicate/orphan/datetime/decimal等すべて通過） |
| Evidence QA（GENERIC v1） | **20/20 LIMITED_USE — 全件 `stale_for_policy`** |
| LegacyAnnotation隔離 | 20件生成。隔離キー: importance_score / market_impact_score / urgency_score / structural_score / sentiment / expected_direction / themes / primary_category |

**LIMITED_USE 20/20は正しい挙動**: 6週間前の記事はGENERIC policy（stale>30日）で
現在分析用途に制限される。P2-C backfill時は歴史蓄積が目的のため、
`HISTORICAL`（またはARCHIVE）policy contextの追加を推奨（P1-E registryへ
register_policyで追加可能。P2-C開始時の承認事項）。

tankのdate_inferredレコードは**存在しなかった**（下記シグナル分析: 0件）—
date_inferred引き継ぎ経路自体はfixtureテストで検証済み（test_tank_compatibility）。

## 2. Article identityシグナル分析（全3,056件・実測）

| シグナル | 実測 | 評価 |
|---|---|---|
| canonical_url | 3,056/3,056 存在・**100%ユニーク** | tank内の主キーとして完全。ArticleIdentityのexact_canonical_url basisに採用可 |
| article_id（=canonical_urlハッシュ） | 100%ユニーク | 同上（導出値） |
| content_hash（title+desc正規化） | 100%ユニーク | exact重複ゼロ |
| title_hash | 100%ユニーク・**cross-domain衝突 0グループ** | 転載ペアが存在しない |
| published_at_utc | 3,056/3,056 存在 | 時刻シグナルは常時利用可 |
| date_inferred | 0件 | 観測窓内のフィードは全てtz付き日付を供給していた |

**重要な含意**: tank格納コーパスは**取込時にexact/syndicated dedup済み**
（tank dedup.pyがcanonical/content/title hashで排除した後のデータ）。ゆえに:

1. exact系シグナル（canonical URL/GUID/fingerprint）はP2-Bの**新規取込時**の
   一次判定として有効（P1-D content_fingerprintがminor markup差分も吸収）。
2. tank内の**残存重複はゼロ**なので、P2-C backfillでのArticle束ねは
   「1記事=1 Article」で開始してよい（クラスタリング不要）。
3. cross-publisher転載の検出（同一内容・別文言）はexactシグナルでは不可能と
   実データが示した——P2-Bのsemantic手法が必要な根拠が定量化された。

## 3. P2-C本移行への手順案（承認待ち）

1. HISTORICAL policy追加（stale制限の緩和はbackfill文脈のみ）
2. 3,056件を tank_article_normalizer → validation gate → normalized store へ投入
3. LegacyAnnotationを並行生成（新Truthにしない・参照専用）
4. ArticleIdentity（exact_canonical_url basis・1:1）とNewsItemを生成
5. SQLite索引構築 → NewsQueryでの検索検証
