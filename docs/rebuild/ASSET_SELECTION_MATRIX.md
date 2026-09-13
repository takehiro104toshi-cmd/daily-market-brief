# ASSET_SELECTION_MATRIX — 2旧プロジェクト横断の資産選別

Rebuild Stage 1.5 成果物（2026-08-29）。
分類: **REUSE**（ほぼそのまま）/ **MIGRATE**（データ・ロジックを新形式へ）/
**REWRITE**（思想のみ参考に新規実装）/ **REFERENCE_ONLY**（研究資料として保持）/
**ARCHIVE**（旧資産として保存）/ **DISCARD**（新システムに不要）。
Source: tank = article-intelligence-data-tank / dmb = daily-market-brief。
dmb資産の詳細根拠は `REUSE_MATRIX.md`（Stage 1判定）を継承し、本書で横断視点から上書き確定する。

## 1. データ資産

| Asset | Source | Path | Phase | 分類 | Destination | 理由（Quality/Tests/価値は`HISTORICAL_DATA_INVENTORY.md`実測に基づく） |
|---|---|---|---|---|---|---|
| 記事コーパス3,056件 | tank | data/article_store/shards/ | 2,6,7 | **MIGRATE**（Phase 2で） | vNext Data Bank（取込時に再分類バックフィル） | 唯一の構造化ニュース原本。当面はtankリポジトリを保管庫とし、今回は物理コピーしない（git二重化回避） |
| ソースカーソル・実行統計35件 | tank | cursors/ statistics/ manifests/ | 12 | REFERENCE_ONLY | tankに残置 | 運用設計の証跡 |
| 配信パッケージ＋LKG | tank | published/ | 2 | REFERENCE_ONLY | tankに残置 | 配信境界の参考実装 |
| 羅針盤PDF 10冊 | dmb | date/rashinban/ | 0,0.5 | **REFERENCE_ONLY**（教師データ） | private保管へ移設（要承認。RASHINBAN_INVENTORY §3） | 最高価値・ただしpublic露出中 |
| 生成レポート59日分（md/html） | dmb | output/ | — | ARCHIVE | 現状維持→Stage 5で肥大対策 | 対照サンプル。教師にはならない |
| 予測ジャーナル5件 | dmb | data/investment_journal/ | 5 | MIGRATE（スキーマ変換） | Phase 5初期データ | 少量だが実データ |
| テーマ学習0件 | dmb | data/theme_learning/ | — | **DISCARD** | — | 実測0件（機構は動いたが蓄積なし） |
| report_runs 46日分 | dmb | data/report_runs/ | 12 | REUSE | 現行運用で継続 | スケジューラ実績 |
| stale configコピー | tank | config/config.yaml | — | **DISCARD** | — | dmb configの死んだ複製（何も読まない） |

## 2. コード資産（Phase 1-2実装の母体判定）

| Asset | Source | Path | Phase | 分類 | Destination | 理由 |
|---|---|---|---|---|---|---|
| feed_parser（RSS2/Atom/RDF） | tank | src/tank/feed_parser.py | 1 | **MIGRATE** | intelligence/sources/ | 両プロジェクト最良のパーサ。13テストごと移植 |
| fetcher（条件付きGET・非再試行分類） | tank | src/tank/fetcher.py | 1 | **MIGRATE** | intelligence/sources/ | dmb safe_getの上位互換。UA契約（連絡先env）も踏襲 |
| url_normalize / dedup 3ハッシュ | tank | src/tank/{url_normalize,dedup}.py | 1,2 | **MIGRATE** | intelligence/news/ | dmbのwire prefix除去（news.py）を統合してポート |
| date_quality | tank | src/tank/date_quality.py | 1 | **MIGRATE** | intelligence/evidence/ | published_at異常の補正＋date_inferredはEvidenceの規律に合致 |
| storage（JSONLシャード＋atomic） | tank | src/tank/storage.py | 2 | MIGRATE（要修正） | intelligence/news/ | シャード単位quarantine（T6）を行単位へ修正して移植 |
| index（SQLite横断検索） | tank | src/tank/index.py | 2 | REWRITE | intelligence/news/ | LIKE部分一致の偽陽性（US⊂RUS）を正規化テーブルで解消 |
| ingestion並列オーケストレーション | tank | src/tank/ingestion.py | 1 | REWRITE | intelligence/sources/ | 設計思想（並列fetch＋単一writer・障害分離）を継承し、T1バグ系を清算 |
| classify（49カテゴリ辞書） | tank | src/tank/classify.py | 2 | MIGRATE（辞書はknowledge/へ） | knowledge/＋intelligence/news/ | ロジック単純・辞書が価値。充足率改善はPhase 2タスク |
| scoring / cluster / diversity | tank | src/tank/{scoring,cluster,diversity}.py | 2,6 | REWRITE | intelligence/themes/ ほか | 骨格は良いが市場反応0%・cluster非永続（T5）等の未完成を清算 |
| EDINET/e-Statアダプタ | tank | src/tank/source_adapters.py | 2,8 | MIGRATE（要修正） | intelligence/sources/ | **キーをヘッダへ・エラーredaction必須**（T7）。dmb edinet.pyより高機能 |
| publication＋LKG | tank | src/tank/publication.py | 2 | REFERENCE_ONLY | — | vNextでは配信境界の形が変わる（PWA向け）。LKG思想のみ継承 |
| private_insight | tank | src/tank/private_insight.py | 5,10 | REFERENCE_ONLY | — | プロンプトのみMIGRATE（§4）。Worker連携は現行運用のまま |
| market_reaction / historical | tank | src/tank/{market_reaction,historical}.py | 5 | DISCARD | — | 未配線・未使用（設計意図はPrediction設計時に参照可） |
| dmb collectors Family A/B（21ファイル） | dmb | src/collectors/ | — | **DISCARD**（カタログ化済み） | knowledge/source_feeds.yaml v2.0.0 | Stage 1.5で完全に代替 |
| dmb news.py（パース＋dedupe） | dmb | src/collectors/news.py | 1 | REFERENCE_ONLY（降格） | — | Stage 1判定「MIGRATE」をtank feed_parser優位により変更。wire prefix正規化のみtank系へ取り込む |
| dmb market_data.py（yfinance+Stooq） | dmb | src/collectors/market_data.py | 2 | MIGRATE | intelligence/market/ | 市場データはtankに無くdmbが唯一。change定義の統一が前提（既報） |
| dmb tdnet/edinet/macro/earnings | dmb | src/collectors/ | 2,8,9 | 個別判定維持 | — | `REUSE_MATRIX.md` §2のとおり（edinetはtankアダプタ優先に変更） |
| dmb analysis層の判定 | dmb | src/analysis/ | — | `REUSE_MATRIX.md` §3を維持 | — | 横断監査による変更なし（tankに競合資産なし） |
| dmb report/scheduler/notifiers/CI | dmb | — | 3,4,12 | 同上維持 | — | 同上 |

## 3. テスト資産

| Asset | Source | 分類 | 理由 |
|---|---|---|---|
| tank test_feed_parser.py（13） | tank | **MIGRATE** | エンコーディング・壊れfeed・Atom/RDFの仕様テスト。実装ごと移植 |
| tank test_url_normalize / test_dedup | tank | **MIGRATE** | ID安定性の契約テスト |
| tank test_fetcher.py（10・HTTPステータス行列） | tank | **MIGRATE** | transport注入の作法ごと |
| tank test_source_adapters.py（21） | tank | MIGRATE（修正後の実装に随伴） | EDINET/e-Stat契約テスト |
| tank test_stabilization.py（date quality/LKG） | tank | MIGRATE | tmp_path化の軽微修正あり |
| tank test_source_portfolio / test_private_insight | tank | REFERENCE_ONLY | repo実ファイル・git依存で密結合 |
| tank tests全般の作法（オフライン・注入・subject命名） | tank | REUSE（方針） | vNextテスト規約として既に採用済み |
| dmb tests 451件 | dmb | REUSE（凍結担保として維持）→機能置換時に随伴移植/退役 | Stage 1判定維持 |

## 4. 知識・プロンプト資産

| Asset | Source | 分類 | Destination | 状態 |
|---|---|---|---|---|
| causal_rules / theme_relations / macro_themes | dmb | MIGRATE | knowledge/ | **完了（Stage 1）** |
| Compass DNA機械可読ルール | dmb | MIGRATE | knowledge/compass_dna/ | **完了（Stage 1）** |
| ソースカタログ（tank sources.yaml 70＋dmb 16） | 両方 | **MIGRATE** | knowledge/source_reliability/source_feeds.yaml v2.0.0 | **完了（Stage 1.5）**。42ソースにlive実績付与 |
| tankテーマ語彙45スラッグ | tank | **MIGRATE** | knowledge/theme_relations/themes.yaml v1.1.0（en_aliases＋unmapped） | **完了（Stage 1.5）** |
| tank 49カテゴリ分類辞書 | tank | MIGRATE（Phase 2で） | knowledge/ | 未実施（classify実装の移植と同時に） |
| tank記事スキーマ約70フィールド | tank | **MIGRATE**（仕様として） | Phase 2 NewsItem設計の出発点 | VNEXT_RECONCILIATION §3に反映 |
| private_insight分析プロンプト（事実/解釈/推測分離・confidence≤0.6・JSON契約） | tank | **MIGRATE**（Phase 3/5で`knowledge/prompts/`へ版管理） | 今回は所在記録のみ（`private_insight.py:580-600`） | Prompt Engine非実装のため |
| llm_enhancer磨き上げプロンプト | dmb | REFERENCE_ONLY | — | 規律（数値捏造禁止・断定禁止）はcontracts docstringに反映済み |
| tank scenario出力設計（4シナリオ・invalidation trigger・review date） | tank | REFERENCE_ONLY→Phase 5でREWRITE | predictions/設計 | ForecastAttributesと語彙整合 |

## 5. インフラ（判定のみ・導入はPhase 12まで凍結）

`CROSS_REPO_ASSET_AUDIT.md` §8のとおり:
dmb 6スロットCI/scheduler=REUSE CANDIDATE、tank毎時ingestワークフロー=REUSE CANDIDATE、
Cloudflare Worker×2=REUSE CANDIDATE、tank stale config=DISCARD、pytest無しCI（tank）=
反面教師（vNextはテストCIを必須要件化）。

## 6. 集計

横断で判定した主要資産群 約70項目:
REUSE 9 / MIGRATE 21（うちStage 1.5実施済み3） / REWRITE 5 / REFERENCE_ONLY 14 /
ARCHIVE 2 / DISCARD 8 / 既存判定維持（dmb `REUSE_MATRIX.md`） 11。
**Phase 1-2のコード母体はtank系**、**知識・データ運用の正本はknowledge/**、
**市場データ・スケジューラ・配信はdmb系**という分担が確定。
