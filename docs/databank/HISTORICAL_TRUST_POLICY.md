# HISTORICAL_TRUST_POLICY — 歴史データ用Trust Policy（Phase 2-B追加承認）

## 1. 目的

古い記事を「今日の材料」としてではなく**歴史データ**として利用可能にする。
P2-C tank backfill（3,056記事・2026-06〜07）およびPhase 5+のバックテスト・
テーマ史分析の前提。

## 2. 定義（evidence_qa/policy.py HISTORICAL_V1）

| パラメータ | 値 | 効果 |
|---|---|---|
| fresh_hours / stale_hours | 実質無限（100年） | **古さそのものを理由にWARN/LIMITEDを発生させない** |
| published_unknown | WARN | 日付不明は警告のまま（GENERIC同等） |
| superseded | WARN | 旧版も歴史として利用可（警告付き） |
| その他全Gate | GENERICと同一 | **provenance / integrity / normalization / conflict / retraction は維持** |

## 3. CONTEXT-DEPENDENT TRUST（実証済み）

**HISTORICAL ACCEPT ≠ DAILY_MARKET ACCEPT。** 同一文書が文脈で異なる判定になる:

| 文書 | HISTORICAL | GENERIC | DAILY_MARKET |
|---|---|---|---|
| 6週間前のBOJ文書（provenance完備） | **ACCEPT** | LIMITED_USE | LIMITED_USE |
| 3年前の文書 | ACCEPT（freshness=PASS） | LIMITED_USE | LIMITED_USE |
| provenance欠落 | REJECT | REJECT | REJECT |
| 明示retracted | REJECT | REJECT | REJECT |
| superseded旧版 | ACCEPT_WITH_WARNINGS | ACCEPT_WITH_WARNINGS | LIMITED_USE |

（全行 `tests/intelligence/test_historical_policy.py` で機械検証）

## 4. 運用規律

- HISTORICALは**蓄積・分析文脈専用**。Morning Brief等の当日判断には
  DAILY_MARKETを使う（policy名がAssessmentに記録されるため用途混同は監査可能）。
- P1-E POLICY VERSIONING準拠: 変更は新version追加＋再評価（旧assessment不変）。
- P2-C backfillではHISTORICAL policyでのQAを標準とする（TANK_BACKFILL_DRY_RUN §1で
  GENERIC下の全件LIMITED_USEを確認済み——本policyがその解）。
