# REBUILD_ROADMAP — Phase 0〜12 の新アーキテクチャ前提タスク分解

Legacy Audit & Greenfield Rebuild Design 成果物（2026-08-29）。
Phase順序は現行ロードマップを維持する（変更しない）。順序に関する提案は末尾の
「PROPOSALS」に分離した（承認があるまで適用しない）。

各タスクの詳細設計は `TARGET_ARCHITECTURE.md`、移行手順は `MIGRATION_PLAN.md` を参照。
規模感: S=半日以内 / M=1〜3日 / L=1週間級（Claude Codeセッション基準の目安）。

---

## Phase 0 — Compass DNA（完了・維持タスクのみ）

- [x] DNA仕様7文書＋market_rules.yaml（済: `docs/compass_dna/`）
- [ ] P0-1 (S) 8月羅針盤PDF追加後のOut-of-Sample検証（Phase 0.5、BLOCKED解除待ち）
- [ ] P0-2 (S) 検証結果に基づく rule への scope（STRUCTURAL/EDITORIAL_PATTERN/SAMPLE_SPECIFIC）付与

## Phase 1 — Source / Evidence Engine

新規実装（`src/intelligence/sources/`, `src/intelligence/evidence/`）:

- [ ] P1-1 (M) スキーマ確定: `RawDocument` / `SourceMeta(tier)` / `EvidenceRecord`（TARGET_ARCHITECTURE §4）。pydantic等は使わずdataclass＋JSONで開始
- [ ] P1-2 (M) `sources/base.py`: fetcher基盤（UA・timeout・retry・fetched_at記録・raw body保存）。旧`safe_get`の後継＋**生レスポンス保存**（旧系の「原文へ遡れない」欠陥の解消）
- [ ] P1-3 (S) ソース定義のデータ化: 旧collectors Family A（15ファイルの実質コピー）を1つの `knowledge/source_feeds.yaml`（url, tier, reliability, lang, format）へ集約
- [ ] P1-4 (M) RSS/Atomパーサー: 旧`news.py`のロジック移植＋**Atom対応**（旧系はRSS2.0のみで Atomは無視される欠陥あり）＋重複統合ロジック移植
- [ ] P1-5 (M) Evidence化パイプライン: 見出し/本文→文単位→statement_type付与（ルール＋LLM補助、LLM無しでも動くフォールバック必須）
- [ ] P1-6 (S) Tier管理: config内source_reliabilityを `knowledge/source_tiers.yaml` へ移し、Tier1/2/3へ正規化
- [ ] P1-7 (M) fixtureテスト基盤: 保存済みフィードでの取得〜Evidence化のゴールデンテスト
- [ ] P1-8 (S) 死活監視: フィード別取得成功率の記録（observabilityの種。旧系は無警報で腐る欠陥あり）

Phase 1完了条件: 実フィード数本からEvidenceRecord(JSONL)が毎日生成され、全FACTが出典・retrieved_atへ遡れる。

## Phase 2 — Market / News Data Bank

- [ ] P2-1 (M) market store: CORE10指標＋SUPPORT系列の日次時系列保存（Parquet/JSONL）。取得は旧`market_data.py`（yfinance+Stooq）をadapter越しに再利用
- [ ] P2-2 (S) 旧系の欠陥修正: Stooqフォールバックの change 定義不一致（前日比 vs 当日始値比）をどちらかへ統一
- [ ] P2-3 (M) 派生指標エンジン: 25日/200日MA乖離・SOX相関・V/G比などをmarket storeから計算（Compass DNA MARKET_DATA_TAXONOMY準拠）
- [ ] P2-4 (M) news store: EvidenceRecordからNews Bank属性（published_at/source/country/ticker/industry/theme/summary/importance/confidence…）への構造化
- [ ] P2-5 (M) entity resolver: watchlist・銘柄コード・業種・テーマの名寄せ辞書（現config sectors/themes/macro_themesを`knowledge/`へ移設して種にする）
- [ ] P2-6 (S) 保存境界のRepositoryインターフェース化（将来のDB差し替え口）

## Phase 3 — Compass Generator

- [ ] P3-1 (M) ルール評価器: `knowledge/analysis_rules/*.yaml`（Phase 0スキーマ）をmarket store/news storeに対して評価し、発火ルール＋根拠Evidenceを出す
- [ ] P3-2 (M) 日次見通し合成: 発火ルール→方向＋メカニズム＋無効化条件（Compass DNA §7の決定木）
- [ ] P3-3 (M) セクション組版: REPORT_STRUCTURE_SPEC準拠の日次資料（日本株/米株/為替/テーマ/銘柄）
- [ ] P3-4 (M) LLM Writer: Evidence ID参照付き文章化＋confidenceラダー語尾制御＋ルールベースフォールバック（旧llm_enhancerの思想を継承・実装は新規）
- [ ] P3-5 (S) スナップショットテスト（Bundle fixture→出力）

## Phase 4 — Morning Brief

- [ ] P4-1 (M) 30秒版/3分版/詳細版の3段組版（「今日のお客様向け一言」「今日のポイント」「相場の見通し＋なぜ」）
- [ ] P4-2 (S) Market Signal（強気〜弱気5段階）をルール評価結果から算出
- [ ] P4-3 (S) 配信: 既存Pages/通知経路への接続（旧notifiers再利用）

## Phase 5 — Prediction Journal

- [ ] P5-1 (M) FORECAST記録: 予測を検証条件・検証日・horizon付きで保存（旧investment_journal/theme_learningのロジックを参考に新スキーマで再実装。旧データはアーカイブとして保持）
- [ ] P5-2 (M) 自動答え合わせ: 翌営業日にmarket storeと突合→的中/不的中/理由フィールド
- [ ] P5-3 (M) 較正統計: 分野別精度・confidence calibrationレポート

## Phase 6 — Theme Map

- [ ] P6-1 (M) テーマグラフ構築: `knowledge/theme_relations.yaml`（現configから移設）＋Compass DNAの連鎖マップを初期グラフ化
- [ ] P6-2 (M) テーマ計測: ニュース量・増加率・企業言及・（後日）設備投資・政策支援
- [ ] P6-3 (M) Emerging Theme検出: THEME_DISCOVERY_RULES §5のシグナル実装
- [ ] P6-4 (S) 旧theme_rotation/theme_learningからの実績データ移行判断

## Phase 7 — Narrative Intelligence

- [ ] P7-1 (L) News Bank＋Theme Graphからストーリー記事生成（現在→変化→原因→ボトルネック→受益1次/2次/3次→リスク）。全段落にEvidence参照

## Phase 8 — Long-Term Stock Screener

- [ ] P8-1 (L) 財務データ取得層（新規。yfinance/EDINETから財務諸表）
- [ ] P8-2 (M) Financial Score × Structural Trend Score
- [ ] P8-3 (M) 自然文検索（テーマグラフ経由）

## Phase 9 — Watchlist + Thesis Tracker

- [ ] P9-1 (M) Watchlist管理（Today/1W/Long Termの3軸評価。旧watchlist_analysisの発想を新データ基盤で再実装）
- [ ] P9-2 (M) Thesis登録＋ニュース/決算によるStrengthened/Unchanged/Watch/Weakened評価

## Phase 10 — Personal Intelligence

- [ ] P10-1 (M) 行動ログ（閲覧・保存・深掘り・検索）収集の仕組み（PWA側と連携）
- [ ] P10-2 (M) 「今日読むべき5本」選定エンジン

## Phase 11 — Mobile App / PWA

- [ ] P11-1 (L) `app/web/` PWA骨格（静的JSON API読込、Homeカード構成はCORE FEATURES L準拠）
- [ ] P11-2 (M) 旧HTMLレポート（html_builder 3,087行）からの導線移行・並走
- [ ] P11-3 (S) 通知（Push）検討

## Phase 12 — Automation

- [ ] P12-1 (M) スケジューラ統合: 旧report_schedule（6スロット＋回復）の仕組みを新パイプラインへ接続
- [ ] P12-2 (M) Observabilityダッシュボード（取得成功率・鮮度・予測精度）
- [ ] P12-3 (M) 旧パイプライン停止→`src/legacy/`隔離→清掃（承認必須・NO BIG-BANG DELETE）

---

## PROPOSALS（順序・構成の変更提案。承認まで適用しない）

1. **P2-1（market store）をPhase 1と並行着手する提案**: Prediction Journal以降すべてが市場時系列を必要とし、蓄積は早いほど価値がある。Phase順序は変えず「Phase 1期間中にP2-1のデータ蓄積だけ先行開始する」形を推奨。
2. **Phase 4の一部前倒し提案**: 現行システムが既に毎朝動いているため、Phase 3完了を待たずに「新Evidence基盤で作るMorning Brief最小版」を現行レポートに1カードとして埋め込み、新旧の品質比較を早期に始める（MIGRATION_PLAN §4のStrangler方式）。
3. **Phase 8の財務データ層はPhase 2で口だけ用意する提案**: entity resolverに財務ID（EDINETコード等）を最初から持たせると後の手戻りが消える。
