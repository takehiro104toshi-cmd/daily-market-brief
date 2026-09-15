# TARGET_ARCHITECTURE — Investment Intelligence OS 目標アーキテクチャ

Legacy Audit & Greenfield Rebuild Design 成果物（2026-08-29）。
前提: 最終ロードマップ Phase 0〜12（CLAUDE.md/タスク指示準拠）、Phase 0 Compass DNA成果物
（`docs/compass_dna/`）、および `docs/rebuild/LEGACY_AUDIT.md` の現状分析。

これは**設計文書**であり、本タスクでは実装しない。

---

## 1. 設計原則

1. **Evidence-first**: すべての下流（レポート・予測・テーマ・銘柄評価）は Evidence Store を経由する。NewsやMarket Dataを直接LLMに投げて文章を出させて終わる経路は禁止。
2. **FACT / ANALYSIS / FORECAST の分離をデータ型で強制**: 文章スタイルでなくスキーマで区別する（`docs/compass_dna/FACT_ANALYSIS_FORECAST_SPEC.md` §5の要件を実装）。
3. **疎結合・独立テスト可能**: 各サブシステムは「入力スキーマ→出力スキーマ」の純関数的な境界を持ち、単体でfixtureテストできる。オーケストレーターは配線のみ。
4. **ルールは宣言的に**: 分析ロジックはコード埋め込みでなく `analysis_rules/*.yaml`（Phase 0のスキーマ）で管理し、エンジンはルールの評価器にする。LLMは「ルール適用結果の文章化」と「抽出・分類」に限定。
5. **旧互換より設計整合**: 旧Daily Market Briefとの後方互換は要件でない。ただし移行期間中は旧パイプラインを併走させる（`MIGRATION_PLAN.md`）。
6. **すべての予測は検証可能に**: FORECASTは記録時点で「検証条件・検証日・horizon」を持ち、Prediction Journalが自動で答え合わせできる形でのみ保存する。

## 2. 全体データフロー

```
            ┌────────────────────────────────────────────────┐
            │                    Scheduler                     │
            │   (GitHub Actions cron → 将来 独立ワーカー)         │
            └───────────────┬────────────────────────────────┘
                            ▼
┌─────────┐   ┌─────────────────────────┐
│ Sources  │──▶│ 1. Source Ingestion      │  RSS/API/公式発表/PDF/手動投入
│ (外部世界) │   │  fetchers + registry     │  出力: RawDocument(source, tier,
└─────────┘   └───────────┬─────────────┘        retrieved_at, url, body)
                            ▼
              ┌─────────────────────────┐
              │ 2. Evidence Engine       │  文単位分解・statement_type付与
              │  fact/analysis/forecast  │  出典・tier・event_date・信頼度
              └───────────┬─────────────┘  出力: EvidenceRecord
                            ▼
      ┌─────────────────────────────────────────┐
      │ 3. Normalized Data Bank                  │
      │  ├ market store (時系列: CORE/SUPPORT/    │
      │  │   CONTEXT指標・派生値: MA乖離/相関/占有率) │
      │  ├ news store (構造化ニュース: published_at,│
      │  │   country, tickers, themes, importance)│
      │  └ entity resolver (企業・ティッカー・       │
      │      業種・テーマの名寄せ)                   │
      └───────────┬─────────────────────────────┘
                    ▼
      ┌─────────────────────────────────────────┐
      │ 4. Analysis Engines（宣言的ルール＋計算）      │
      │  ├ regime / breadth / cross-market        │
      │  ├ rule evaluator (market_rules.yaml)     │
      │  ├ theme graph (Theme Map: ノード=テーマ/    │
      │  │   企業/政策、エッジ=因果・供給網)            │
      │  ├ prediction engine (horizon付きFORECAST) │
      │  ├ thesis tracker (Watchlist×投資仮説)      │
      │  └ screener (長期候補スコアリング)             │
      └───────────┬─────────────────────────────┘
                    ▼
      ┌─────────────────────────────────────────┐
      │ 5. Report Generation                     │
      │  ├ Compass Generator (日次詳細版)           │
      │  ├ Morning Brief (30秒/3分/詳細の3段)        │
      │  └ LLM Writer (Evidence参照付き文章化のみ)    │
      └───────────┬─────────────────────────────┘
                    ▼
      ┌─────────────────────────────────────────┐
      │ 6. Delivery / Personalization            │
      │  ├ API (静的JSON→将来API server)            │
      │  ├ PWA / Mobile frontend                 │
      │  ├ notifier (email/LINE等)                │
      │  └ personalization (閲覧・保存・検索の学習)     │
      └─────────────────────────────────────────┘
                    ▲
      ┌───────────┴─────────────────────────────┐
      │ 7. Feedback Loop                         │
      │  ├ Prediction Journal (予測の自動答え合わせ)   │
      │  └ Observability (取得成功率・鮮度・精度統計)    │
      └─────────────────────────────────────────┘
```

## 3. サブシステム仕様（14要件との対応）

| # | 要件 | モジュール（新レイアウト） | 責務 | 独立テスト方法 |
|---|---|---|---|---|
| 1 | source ingestion | `intelligence/sources/` | 取得のみ。解釈しない。RawDocument＋SourceMeta(tier, retrieved_at)を返す | 保存済みRSS/HTML fixtureに対する取得・パース |
| 2 | evidence | `intelligence/evidence/` | 文単位の statement_type / tier / as_of / confidence 付与、出典逆引き | 入力文→期待タグのゴールデンテスト |
| 3 | market data | `intelligence/market/` | CORE/SUPPORT/CONTEXT時系列の取得・保存・派生指標計算（MA乖離・相関・breadth） | 数値fixtureに対する計算検証 |
| 4 | news | `intelligence/news/` | 構造化ニュース（News Bank属性: published_at/source/country/ticker/industry/theme/summary/importance…）・重複統合 | 見出しfixture→構造化結果 |
| 5 | entity resolution | `intelligence/entities/` | 企業名⇄ティッカー⇄業種⇄テーマの名寄せ辞書＋解決器 | 辞書テーブルテスト |
| 6 | theme graph | `intelligence/themes/` | テーマグラフ（因果・供給網エッジ）、Emerging検出（ニュース量・増加率・言及） | グラフ探索・スコアの単体テスト |
| 7 | prediction | `intelligence/predictions/` | FORECASTの記録・検証条件・答え合わせ・較正統計 | 時計を注入した検証シナリオテスト |
| 8 | thesis | `intelligence/thesis/` | Watchlist銘柄のInvestment Thesis登録とStrengthened/Weakened評価 | thesis+ニュースfixture評価 |
| 9 | screening | `intelligence/screening/` | Financial×Structural Trendスコアの長期候補抽出 | 財務fixtureスコアリング |
| 10 | report generation | `intelligence/reports/` | Compass/Morning Briefの組版。テンプレート＋Evidence参照。LLMは文章化のみ | Bundle fixture→スナップショットテスト |
| 11 | personalization | `intelligence/personalization/` | 興味プロファイル・「今日読むべき5本」選定 | 行動ログfixture→選定結果 |
| 12 | frontend | `app/web/` | PWA（静的JSON読込→将来API） | コンポーネント/E2E（別系） |
| 13 | scheduler | `app/scheduler/` | スロット解決・二重生成防止・欠損回復（旧report_scheduleの後継） | 時刻注入テスト（旧テスト移植） |
| 14 | observability | `intelligence/observability/` | 取得成功率・鮮度・信頼度・予測精度のメトリクス | 統計計算の単体テスト |

## 4. データ所有権と契約（Data Ownership）

- **EvidenceRecord**（Phase 1で確定させる中核スキーマ・案）:
  `id, statement_text, statement_type(fact|fact_unverified|analysis|forecast), source{name,url,tier}, event_date, retrieved_at, entities[], themes[], numbers[{value,unit,as_of,calc_method}], forecast{confidence:0-5, horizon, agent, invalidation_condition} (forecastのみ), counter_points[]`
- **所有権ルール**:
  - Sources層だけが外部ネットワークに触れる。
  - Evidence層だけが statement_type を付与できる。
  - Analysis層はEvidence/Data Bankを読むだけ（書き戻しは新しいEvidence(analysis/forecast)として）。
  - Report層は自分でデータを取得しない（Bundleを受け取るのみ）。
  - LLMはEvidence参照なしの数値・事実を出力してはならない（プロンプト＋出力検証の双方で強制）。
- 旧システムの `SourceRegistry`（出典一覧）はこの縮退版であり、思想は連続している（LEGACY_AUDIT参照）。

## 5. 新ディレクトリレイアウト案

現状リポジトリ（フラットな `src/collectors|analysis|report`＋ルート直下 `notifiers/ data/ date/ output/`）を踏まえた提案:

```
src/
  intelligence/            # 新中核（Phase 1以降ここに実装）
    sources/               # ingestion（旧collectorsの後継。base fetcher + per-source）
    evidence/              # Evidence Engine（Phase 1）
    market/                # market data bank + 派生指標
    news/                  # news bank + 構造化・重複統合
    entities/              # 名寄せ
    themes/                # theme graph / emerging検出
    predictions/           # prediction journal
    thesis/                # thesis tracker
    screening/             # long-term screener
    reports/               # compass generator / morning brief
    personalization/
    observability/
  legacy/                  # 【将来】現行 src/analysis 等の隔離先（今回は移動しない）
app/
  web/                     # PWA（Phase 11）
  scheduler/               # スロット・cron解決（旧scripts/resolve_report_schedule後継）
  notifiers/               # 通知（旧notifiers移設）
data/                      # 実行時状態（journal/theme_learning/report_runs/翻訳cache）
knowledge/                 # 【新設】人手管理の知識資産（YAML）: causal_rules,
                           # theme_relations, source_tiers, analysis_rules
                           # ← 現在config.yamlに同居している知識をここへ分離
research/
  source_docs/compass/     # 羅針盤PDF等の研究資料（現 date/rashinban の後継）
docs/
  compass_dna/             # Phase 0成果物（既存）
  rebuild/                 # 本設計（既存）
tests/
  unit/ integration/ fixtures/   # 現行のtest_vX_Y命名を機能別へ再編
output/                    # 生成物（当面現状維持。将来はPages artifact化して非コミット化を提案）
```

要点:
- `config.yaml` は「設定」（URL・閾値・スケジュール）に純化し、「知識」（causal_rules・theme_relations・macro_themes・source_reliability）は `knowledge/` のバージョン管理されたYAMLへ分離する。Phase 0のmarket_rules.yamlと同じ管理系に乗せる。
- `date/`（`data/`のtypo由来と推定される重複ディレクトリ）は将来 `research/`＋`data/` へ整理する（今回は移動しない。NO BIG-BANG DELETE）。
- 旧 `src/analysis`・`src/report` は新系の稼働確認まで現位置のまま凍結し、置換完了後に `src/legacy/` へ隔離（Phase 12前後）。

## 6. LLMの位置づけ

- 使用箇所: ①Evidence抽出補助（文分解・分類・エンティティ抽出）②翻訳③ルール適用結果の文章化（Compass/Brief）④Narrative生成（Phase 7、Evidence参照付き）。
- 全LLM出力は (a) 参照EvidenceのID列を伴う、(b) ルールベースのフォールバックを持つ（旧システムの2段構成思想を継承）、(c) FORECAST語尾はconfidenceラダーからテンプレート選択。
- モデルは環境変数で切替（現行 `MARKET_BRIEF_LLM_MODEL` の思想を継承）。

## 7. 段階的な物理形態

- **Phase 1〜4**: 現行と同じ「GitHub Actions＋ファイルストア（JSON/JSONL/Parquet）＋静的Pages」で成立させる。DBサーバー・API serverは導入しない（Phase 2のData Bankもまずファイルベース）。
- **Phase 5〜10**: ファイルストアの読み書きをRepositoryインターフェース越しに行い、後からDB（SQLite→必要ならPostgres）へ差し替え可能にする。
- **Phase 11〜12**: 静的JSON APIをPWAが読む形から開始し、必要になった時点でAPI server化。Cloudflare Worker（ワンタップ実行・Private Vault）は既存資産を継続利用。
