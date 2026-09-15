# HISTORICAL_DATA_QUALITY — 歴史コーパス品質報告（Phase 2-C / full 3,056件）

## 1. COVERAGE / MISSINGNESS（入力実測）

| 項目 | 値 |
|---|---|
| title_original欠損 | 0 |
| canonical_url欠損 | 0 |
| published_at欠損 | 0（全件tz付きUTC ISO） |
| fetched_at欠損 | 0 |
| description欠損 | 875（optional——REJECTにしない。summary空のSourceDocumentとして保持） |
| date_inferred | 0 |
| invalid JSON | 0 |
| schema variants | フィールド集合のゆれあり（date_inferred系の有無等）——adapterが吸収 |

## 2. 分布

- **言語**: en 3,041（99.5%）/ ja 15（0.5%）。日本語の歴史データは薄い
  （JP系一次ソースの本格蓄積はP2-D以降の日次運用から）。
- **月別**: 2026-06 77件 / 2026-07 2,979件（観測窓 6/22〜7/22）。
- **publisher上位**: Yahoo Finance 608 / SCMP 244 / Al Jazeera 236 / CNA 203 /
  Bloomberg 147（計42 publisher）。
- **date_quality**: source_provided_tz 3,056/3,056（100%）・published_inferred 0。

## 3. QA RESULT（HISTORICAL v1.0.0）

ACCEPT_WITH_WARNINGS 3,056 / ACCEPT 0 / LIMITED 0 / REJECT 0。
warning理由: missing_raw_item 3,056（migration由来の構造的warning——原文blob非保存の
正直な申告であり品質欠陥ではない）・tier3_general_source 48（aggregator由来）。
**「ACCEPT 0」はwarningの定義による**: 歴史コーパスでprovenance warningが常在するため、
P2-Fでmigration文脈のmissing_raw_item扱い（policy知識化）を検討余地として記録。

## 4. IDENTITY DECISIONS

distinct 2,976 / revision 55 / candidate 25（詳細: TANK_BACKFILL_REPORT §4-5）。
発見: tank内に**同一URL更新版が55組存在**（tankのcanonical_hashは正規化前URLで
別物扱い）。vNextのURL正規化＋fingerprintが実データで価値を実証。

## 5. REJECT / WARNING REASONS

reject 0件（本corpusは全件移行可能だった。合成テストではinvalid JSON・
missing titleがledgerへ正しく落ちることを検証済み）。

## 6. LEGACY ANNOTATION

3,056件を隔離（origin=legacy_tank・not_ground_truth=true）。隔離キー:
importance_score / market_impact_score / urgency_score / structural_score /
sentiment / expected_direction / themes / primary_category ＋
historical provenance（legacy_shard_locator / legacy_article_id /
source_mapping_confidence=exact_name 3,056/3,056）。
**新classificationのGround Truthには使用しない**（P2-E参考情報のみ）。
