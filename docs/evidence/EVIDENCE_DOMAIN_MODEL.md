# EVIDENCE_DOMAIN_MODEL — Evidenceドメインモデル（schema 0.2.0）

Phase 1-A 成果物（2026-08-29）。実装: `src/intelligence/`（core / sources / market / evidence）。
schemaは**0.x（experimental）**であり、Phase 1完了までbackward compatibilityを保証しない。
Python 3.10+（`kw_only` dataclass使用。CI/実行環境は3.11）。

## 1. 全体像

```
Source ──┐ (catalog: knowledge/source_feeds.yaml と同一のslug ID)
         ▼
      RawItem ──────────► SourceDocument ─────────────┐
   （生ペイロード記録）   （解釈済み文書メタデータ）      │ EvidenceLink (many-to-many)
   content-addressed      content-addressed            ▼
                               │                 ┌─ FactStatement ──┐
                               │ 直接参照         │  AnalysisStatement │←inputs/rule_id/agent
                               ▼                 │  ForecastStatement │←ForecastMetadata
                          Observation            └──────┬───────────┘
                       （数値観測・Decimal）             │ EvidenceLink(DERIVED_FROM等)
                        raw / derived                   ▼
                        inputs=派生provenance      検証状態の導出（invariants.py）
                                                  UNSUPPORTED / VERIFIED / CONFLICTING
```

## 2. 型一覧（所有パッケージ・God Model禁止の分割）

| 型 | 所在 | ID方式 | 役割 |
|---|---|---|---|
| Source | sources/model.py | slug（カタログ一致） | 情報源カタログ項目 |
| RawItem | sources/model.py | content-addressed `raw_` | 生ペイロードの記録（原文へ遡る最後の砦。非保存はstorage_ref=""で明示） |
| SourceDocument | sources/model.py | content-addressed `doc_` | 公表文書のメタデータ（title/locator/published_at/retrieved_at/language/content_hash/tierスナップショット/revision_of） |
| Observation | market/model.py | ULID `obs_` | 数値観測（Decimal・raw/derived・inputs・revision_of） |
| FactStatement | evidence/model.py | ULID `fact_` | 事実の言明（attribution: DIRECT/REPORTED） |
| AnalysisStatement | evidence/model.py | ULID `ana_` | 分析の言明（inputs≥1・rule_id・agent必須） |
| ForecastStatement | evidence/model.py | ULID `fcst_` | 予測の言明（ForecastMetadata必須） |
| ForecastMetadata | evidence/model.py | （合成） | target/direction/horizon/confidence 0-5/predictor/supporting≥1/counter/invalidation≥1/target_low・high(Decimal)/evaluate_by |
| EvidenceLink | evidence/model.py | ULID `link_` | claim↔evidenceのmany-to-many（SUPPORTS/CONTRADICTS/DERIVED_FROM/CONTEXT） |
| 共有enum等 | core/types.py | — | SourceTier / StatementType / VerificationState / Horizon / Direction / confidence境界 / LLMResult |

## 3. FACT / ANALYSIS / FORECAST 分離の実装

- **別クラス**で分離（God Statement禁止）。共通フィールドは`_StatementBase`
  （statement_id/text/created_at/language/entities/themes/event_time/valid_from/
  valid_until/verification/schema_version）。
- FACT: 出典はフィールドでなく**EvidenceLink**で表現（抽出時に必ずSUPPORTSリンクを作る）。
  リンクゼロのFACTは`invariants.unsupported_facts()`で機械的にUNSUPPORTED判定
  → **AI生成文が自動でFACT扱いされない**。
- ANALYSIS: `inputs`（≥1）・`rule_id`（knowledge/のルールID）・`agent`・`created_at`で
  「どのFactから・どのルールで・誰が・いつ」を型レベル強制。
  `invariants.trace_analysis()`で予測→分析→根のFACTまで再帰トレース可能
  （fixture: Fed利上げ→JP_US_001→グロース圧迫→半導体上値抑制）。
- FORECAST: ForecastMetadata必須。invalidation_conditions≥1・supporting_evidence≥1・
  evaluate_byにより**Phase 5 Prediction Journalが後日自動評価できる形**でのみ存在できる。
  counter_pointsは保存層では任意（生成層=Phase 3で必須化する方針。Compass DNA準拠）。

## 4. Legacy資産との対応（取り込み確認）

| 旧資産 | 対応 |
|---|---|
| tank記事モデル（約70フィールド） | SourceDocument（出所・時刻・hash群）＋FactStatement（title由来の言明・themes/entities）＋Phase 2 NewsItem（記事単位の索引。P2-4で本モデルの上に定義）に分解して受容。tankのcanonical_hash/duplicate_group→content-addressed ID・content_hashが受け皿 |
| tank date_quality（date_inferred/raw_published_at） | P1-Bでの取込予定。SourceDocumentへ`date_inferred`系フィールドを追加予定（0.xのため追加は非破壊） |
| tank private_insightシナリオ（invalidation trigger/review date/confidence上限） | ForecastMetadata.invalidation_conditions / evaluate_by / confidenceに語彙一致 |
| dmb Headline（source/reliability/published/fetched_at） | SourceDocument＋Sourceで表現可能（reliability→カタログtrust_score） |
| dmb market dict / MARKET_DATA_TAXONOMY | Observation（unit/calc_method内包・derived inputs）で全指標型を表現可能 |
| knowledge/ ルールID（CR_*/JP_*） | AnalysisStatement.rule_id / related_compass_ruleで接続 |

## 5. 設計上の非対称（意図的）

- Statementの出典は**リンクのみ**、Observationは`source_document_id`**直接参照**。
  理由: 言明は柔軟な証拠グラフ（複数出典・反証・文脈）が本質。観測は文書からの
  構造化抽出で1対1が常態であり、リンクオブジェクトのオーバーヘッドが利益を上回る。
  観測にも反証・照合が必要になった場合はEvidenceLinkのevidence_idにobservation_idを
  入れられる（既に許容）。

## 6. 検証（synthetic fixtures / tests）

`tests/intelligence/evidence_fixtures.py` に指示された10ケース＋因果チェーン
（BOJ/Fed声明・CPI改定・日米株観測・決算・二次記事・矛盾・裏付けなしAI文）を実装。
テスト実測: domain 25 / serialization 38 / store 7 / contracts 8（vNext計102、
knowledge・境界・Guard含む）。**全553テスト（Legacy 451含む）PASS**。
