# DATA_BANK_ARCHITECTURE — Market/News Data Bank全体設計（Phase 2-A / 2026-08-30）

Phase 2の目的: Phase 1のSource/Evidence Engineが生む正規化・品質判定済みレコードを
**長期蓄積・検索可能**なData Bankへ組織化する。P2-Aはその基礎（E2E実証＋domain schema）。

## 1. Phase 2分割と本ステージの位置

| ステージ | 内容 | 状態 |
|---|---|---|
| **P2-A** | End-to-End Pilot＋Data Bank Domain Schema | **本ステージ** |
| P2-B | Article Identity / Dedup / Revision | 未着手 |
| P2-C | Historical Tank Backfill（3,056件） | 未着手（dry runのみ実施） |
| P2-D | Market Data Bank | 未着手（domainのみ設計） |
| P2-E | News Classification / Metadata Enrichment | 未着手（schemaのみ設計） |
| P2-F | Data Bank QA / Query Layer | validation gate＋query契約はP2-Aで基礎実装 |

## 2. パッケージ構成

```
src/intelligence/
├── pipeline/          E2E編成（Phase 1全層の一本通し）
│   ├── e2e.py         Registry→Fetch→Raw→Normalize→QA→Gate（mockなし・注入はtransportのみ）
│   ├── trace.py       Assessment→…→Sourceの逆引きtrace（human-readable）
│   └── e2e_runner.py  GitHub Actions実行（少数source・bulk禁止）
└── databank/          Data Bank domain（Phase 2-A: schemaと基盤のみ）
    ├── news_model.py     NewsItem/ArticleIdentity/Link/Classification/Score/LegacyAnnotation
    ├── market_model.py   MarketSeries/ObservationType（series identity規約）
    ├── validation.py     投入前validation gate（9検査項目）
    ├── query.py          NewsQuery/MarketQuery契約
    └── sqlite_index.py   再構築可能なSQLite索引（storage decisionの参照実装）
```

## 3. NO FALSE EVIDENCE（E2Eの最重要不変条件）

fetch失敗・parser失敗・normalization REJECTから **EvidenceAssessment ACCEPTが
生成されることは絶対にない**。パイプライン実装は文書ゼロの時点でQA層へ進まず、
integration test（`test_no_false_evidence_invariant`）が404/403/timeout/HTML/garbage
の全ケースでACCEPTゼロを機械的に固定する。

## 4. レイヤー間参照の原則

- Data Bankレコード（NewsItem等）は**SourceDocumentを参照**し、置換しない
  （provenance chainはPhase 1のまま生き続ける）。
- 分類・スコアは独立レコード（God NewsItem禁止）で、必ずprovenance付き。
- Trust Gate結果（EvidenceAssessment）はrecord_idで横付けされ、
  検索条件（trust_decisions）として使える（sqlite索引実装済み）。

## 5. schema versioning / migration戦略

- SCHEMA_VERSION **0.3.0**（0.3.x = Phase 2-A Data Bank domain追加）。
- 全レコードがschema_versionを自己申告。0.x間の前方互換規約: decode時の
  未知フィールドは無視（0.2.xレコードは0.3.xコードでそのまま読める——追加のみのため）。
- Phase 2中のbreaking changeは許容（0.x）。手順: (1) 新versionへ上げる
  (2) JSONL正本は書き換えない（新レコードのみ新schema）(3) SQLite索引はDROP→再構築
  (4) 意味変更がある場合のみ正本の再生成スクリプトを別途承認を得て実行。
- 1.0.0昇格はPhase 2完了時に判断（以後: 追加=パッチ・意味変更=マイナー・破壊=メジャー）。
