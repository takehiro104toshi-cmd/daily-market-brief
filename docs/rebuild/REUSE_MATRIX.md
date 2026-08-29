# REUSE_MATRIX — 資産別の再利用判定

Legacy Audit & Greenfield Rebuild Design 成果物（2026-08-29）。
判定基準は「Investment Intelligence OS最終ロードマップへの適合」であり、既存互換ではない。

分類: **REUSE**（ほぼそのまま）/ **PARTIAL_REUSE**（adapter・ロジック移植・データのみ等）/
**REBUILD**（新規設計で置換）/ **REMOVE_LATER**（新系稼働後に隔離・削除）/ **UNKNOWN**（要検証）。
再利用形態: as-is / adapter / logic-only / test-only / data-only / discard。
Risk = 移行リスク（その資産を移す/捨てる際の危険度）。

---

## 1. 知識・データ資産

| Path | 分類 | 用途/理由 | 依存・結合 | 品質 | テスト | ロードマップ関連 | Risk | 推奨アクション |
|---|---|---|---|---|---|---|---|---|
| config.yaml `causal_rules`/`theme_relations`/`macro_themes`/`durable_themes` | **REUSE** (data-only) | 羅針盤思考を一般化した因果・テーマ知識。Theme Map/ルール評価器の種 | config読み込みのみ | 高（出所コメント付き） | 間接的 | Phase 3/6中核 | 低 | `knowledge/`配下のYAMLへ移設し、Phase 0のrule schemaと統一 |
| config.yaml `source_reliability`/`source_classification` | **REUSE** (data-only) | ソース信頼度の初期値 | 同上 | 中 | 間接的 | Phase 1 Tier管理 | 低 | `knowledge/source_tiers.yaml`へ正規化（Tier1-3へ変換） |
| config.yaml `sectors`/`themes`/`watchlist`/`key_levels` | **REUSE** (data-only) | 銘柄・業種・テーマ辞書。entity resolverの種 | 同上 | 中 | 間接的 | Phase 2/9 | 低 | `knowledge/`へ移設 |
| docs/compass_dna/ 一式 | **REUSE** (as-is) | Phase 0成果物。新設計の仕様根拠 | なし | — | — | 全Phase | なし | 維持 |
| date/rashinban/*.pdf | **REUSE** (data-only) | 研究資料（社外秘・要非公開注意） | なし | — | — | Phase 0.5 | 低 | 将来`research/source_docs/compass/`へ移動（要承認） |
| data/investment_journal/, data/theme_learning/ | PARTIAL_REUSE (data-only) | 実績データ約2ヵ月分 | 旧スキーマ | 中 | あり | Phase 5 | 低 | 新Prediction Journalへはスキーマ変換の上で取り込み判断 |
| data/report_runs/ | REUSE (as-is) | スロット実行記録 | report_schedule | 高 | あり | Phase 12 | 低 | 当面継続使用 |
| output/（214MB） | **REMOVE_LATER** | 生成物のgit管理は最大の肥大要因 | CI・Pages | — | — | — | **高**（履歴・Pages導線に影響） | 方針決定が必要: 保持数上限/別ブランチ/artifact化。**大量削除・履歴書き換えは要ユーザー承認** |

## 2. 収集層（src/collectors ほか）

| Path | 分類 | 用途/理由 | 依存・結合 | 品質 | テスト | ロードマップ関連 | Risk | 推奨アクション |
|---|---|---|---|---|---|---|---|---|
| news.py | **PARTIAL_REUSE** (logic-only) | RSSパース・重複統合・Headlineモデル。リポジトリ最良級 | utils.safe_get | 高 | あり | Phase 1 | 低 | パース＋dedupeを新sources層へ移植。Atom対応・raw保存を追加 |
| Family A 15ファイル（nikkei/bloomberg/reuters/cnbc/wsj/marketwatch/investing/boj/mof/fed/ecb/sec_gov/us_gov_stats/crypto_news/yahoo_finance_us） | **REBUILD** | 実体は設定の複製。全URL実地未検証・Reutersは死亡濃厚 | news.py委譲のみ | 低（コピー） | 形式的 | Phase 1 | 低 | URL+Tier表を`knowledge/source_feeds.yaml`へ抽出しコードは新fetcher1本に統合。**移行時に全URL死活確認** |
| Family B 6ファイル（kabutan/minkabu/moomoo/rakuten/sbi/jpx） | REMOVE_LATER | 参照リンク登録のみ・データ取得なし | SourceRegistry | — | 形式的 | 低 | なし | 新系ではreference表（data）に置換 |
| market_data.py | **PARTIAL_REUSE** (adapter) | yfinance+Stooq二段フォールバックは実用資産 | yfinance/pandas | 中〜高 | あり | Phase 2 | 中（change定義不一致バグ持ち） | market storeのfetch部として流用。change定義を統一し、取得時刻メタデータを追加 |
| tdnet.py | UNKNOWN | 唯一のHTMLスクレイパー。最脆弱（位置指定セル・1ページ目のみ） | BeautifulSoup | 低 | あり | Phase 2 | 中 | 新系採用前に実地検証。公式代替（API/CSV）調査を優先 |
| edinet.py | PARTIAL_REUSE (logic-only) | EDINET v2 API。キー必須前提へ修正要 | EDINET_API_KEY | 中 | あり | Phase 2/8 | 低 | 財務データ層（P8-1）の起点として改修流用 |
| macro.py | PARTIAL_REUSE (logic-only) | FRED CSV取得。系列がハードコード | なし | 中 | あり | Phase 2 | 低 | 系列リストをknowledge/configへ、値をfloat化 |
| earnings.py | PARTIAL_REUSE | yfinance決算日取得 | yfinance | 中 | あり | Phase 9 | 低 | 流用可 |
| economic_calendar.py | UNKNOWN | 195行が現状no-op（config空） | なし | 中 | あり | Phase 2 | 低 | 実ソース確定後に採否判断。それまで凍結 |
| themes.py | PARTIAL_REUSE (logic-only) | キーワードマッチ。感情判定は日本語のみ | Headline型 | 中 | あり | Phase 2/6 | 低 | マッチャは流用、感情辞書は英語対応へ拡張 |
| utils.py（safe_get/SourceRegistry/load_config） | PARTIAL_REUSE | HTTP原始関数と出典登録 | requests | 中 | あり | Phase 1 | 低 | 新fetcher基盤に吸収（timestamp付きSourceRefへ拡張） |
| src/data/external_intelligence_client.py | **REUSE** (as-is) | checksum・schema検証・注入可能Transport。最良品質 | 別リポジトリ | 高 | あり | Phase 2 | 低 | そのまま新sources層へ移設 |
| src/data/private_insight_client.py | REUSE (as-is) | Cloudflare Vault連携 | Worker/Token | 高 | あり | Phase 2/10 | 低 | 継続使用 |
| **src/date/**（全体） | **REMOVE_LATER** | src/dataのバイト同一死にコピー・被import 0 | なし | — | なし | なし | なし | 新系稼働を待たず削除可能な唯一の候補（それでも削除は要承認） |

## 3. 分析層（src/analysis）

| Path | 分類 | 用途/理由 | 依存・結合 | 品質 | テスト | ロードマップ関連 | Risk | 推奨アクション |
|---|---|---|---|---|---|---|---|---|
| models.py（59 dataclass/AnalysisBundle） | **REBUILD** | 神オブジェクト。44ファイル結合の根 | 全層 | 中 | あり | — | **高** | 新系はEvidence/Bundle分割スキーマ。移行期はadapterで旧Bundleへ変換 |
| source_trust.py | **REUSE** (logic-only) | Tierルックアップ＋複数ソース加点。純関数 | なし | 高 | あり | **Phase 1中核** | 低 | 部分文字列マッチの誤爆修正の上で移植 |
| market_regime.py | **REUSE** (logic-only) | 透明な重み付きレジーム判定。層内最良 | format_utils | 高 | あり | Phase 3 | 低 | 重みをknowledge/へ外出しして移植 |
| analysis_confidence.py | REUSE (logic-only) | データ品質→確信度の機械算出 | AnalysisBundle依存 | 高 | あり | Phase 3/観測 | 低 | 入力を4引数に絞って移植 |
| data_freshness.py | REUSE (logic-only) | 鮮度・ソース死活統計 | collectors型 | 高 | あり | **observability中核** | 低 | future-date採点バグ修正の上で移植 |
| news_ranking.py / news_impact.py / strategist_engine.py | **PARTIAL_REUSE** (logic-only) | 加点方式スコアラーは健全（★飽和・固定文言は難） | rashinban/tank結合 | 中〜高 | あり | Phase 2/3 | 中 | スコア軸をルールYAML化して再実装。文言生成は捨てる |
| investment_journal.py / theme_learning.py | **PARTIAL_REUSE** (logic-only) | 唯一の答え合わせループ。ただし評価が日経のみ | market dict | 中 | あり | **Phase 5中核** | 中 | 記録・評価枠組みを継承し、検証条件を予測対象別に再設計 |
| rashinban_loader.py | PARTIAL_REUSE | 抽出器として健全だが機能は不活性（三重不一致） | config | 高 | あり | Phase 0.5/1 | 低 | 新research層でPDF→テキスト化と組み合わせ再生 |
| market_breadth.py | PARTIAL_REUSE | proxy明示のbreadth骨格 | Quote型 | 中 | あり | Phase 2/3 | 低 | 実A/Dデータ接続を前提に骨格流用 |
| causal_chain.py | PARTIAL_REUSE | 長鎖（実数値注入）は流用可、短鎖テンプレは捨て | format_utils | 中 | あり | Phase 3/7 | 低 | ルール評価器の出力表現として長鎖のみ移植 |
| theme_rotation.py | PARTIAL_REUSE | 関係グラフ×モメンタムの回転検出 | theme_relations | 中 | あり | Phase 6 | 低 | momentum入力を実計測値に差し替えて流用 |
| future_intelligence.py（1,548行） | **REBUILD** | 2つの採点関数以外は条件→定型文の集積 | 多数 | 低〜中 | あり | Phase 6/7 | 中 | _momentum_score/_confidence_scoreのみlogic移植。残りはTheme Map/Narrativeで新規置換 |
| scenario.py / scenario_v2.py / future_probability.py / instrument_scenarios.py | PARTIAL_REUSE | 確率提示の枠組みのみ | format_utils | 中 | あり | Phase 3/5 | 低 | 予測はEvidence化（horizon/検証条件付き）して再実装 |
| market_narrative.py / strategic_narrative.py / executive_summary.py / ai_summary.py / why_today.py | **REBUILD** | 定型文合成。新系ではLLM Writer＋Evidence参照で置換 | Bundle | 中 | あり | Phase 3/4 | 低 | 構成（何を先に言うか）だけ仕様として吸収 |
| 営業文言クラスタ6モジュール（sales_comments/okasan_sales_comments/sales_talk/sales_prep/call_priority/morning_meeting_comment） | **REBUILD**（統合） | 同一入力の再スライス~660行 | Bundle | 低 | あり | Phase 4（お客様向け一言） | 低 | 「audience×長さ」パラメータ1関数へ統合再設計 |
| sector_ranking.py / sector_strength.py / market_impact.py / stock_ranking.py / top_picks.py / long_term_picks.py / watchlist_* | PARTIAL_REUSE | 採点ロジックの一部のみ | config二重辞書 | 中 | あり | Phase 8/9 | 低 | セクター辞書を単一ソース化して必要分のみ移植 |
| translation.py | REUSE (as-is) | 永続キャッシュ付き翻訳 | anthropic任意 | 高 | あり | Phase 1/2 | 低 | 継続使用 |
| llm_enhancer.py | PARTIAL_REUSE (logic-only) | 縮退設計の手本。実装は86行 | anthropic | 高 | あり | Phase 3 LLM Writer | 低 | 思想継承で新Writerを書く（client再利用・現行SDK作法へ更新） |
| report_schedule.py | **REUSE** (as-is) | 6スロット・二重防止・回復の純ロジック | pytz | 高 | 充実 | **Phase 12中核** | 低 | `app/scheduler/`へ移設のみ |
| external_intelligence.py | REUSE (adapter) | Data Tank連携bundle | client | 高 | あり | Phase 2 | 低 | 継続使用 |
| weekly_events.py / events.py / anomaly.py / cross_market.py / key_levels.py / chat_topics.py | PARTIAL_REUSE〜REBUILD | イベント整形・異常検知等 | Bundle | 中 | あり | Phase 3 | 低 | 個別にlogic吸収 |

## 4. 出力・配信・運用層

| Path | 分類 | 用途/理由 | 依存・結合 | 品質 | テスト | ロードマップ関連 | Risk | 推奨アクション |
|---|---|---|---|---|---|---|---|---|
| report/html_builder.py（3,087行） | **REBUILD** | f文字列HTML。PWA（Phase 11）で置換 | Bundle全域 | 低〜中 | あり | Phase 11 | 中（現行UIの生命線） | 新系稼働まで凍結維持→PWA移行後にREMOVE_LATER。カードUI・ダークテーマ等のUI仕様のみ吸収 |
| report/builder.py / sections.py / mobile_builder.py | REBUILD | 31セクションMarkdown組版 | Bundle | 中 | あり | Phase 3/4 | 低 | セクション順序仕様（docstring）だけ新組版へ継承 |
| report/format_utils.py | PARTIAL_REUSE | フォーマッタ＋NOT_AVAILABLE規約 | 33ファイルから被import | 中 | あり | 共通 | 中 | 新共有スキーマ層へ移設（find_quoteはデータ層へ） |
| report/pdf.py | REMOVE_LATER | pandoc前提・未配線 | なし | 低 | なし | なし | なし | 隔離対象 |
| notifiers/email_sender.py, line_sender.py | **REUSE** (as-is) | 実装済み・テスト済み通知 | SMTP/LINE Secrets | 高 | あり | Phase 4/12 | 低 | `app/notifiers/`へ移設 |
| notifiers/line_notify.py | REMOVE_LATER | 抽象未実装・インスタンス化不能・名前衝突 | なし | 死 | なし | なし | なし | 削除候補（要承認） |
| notifiers/slack/discord/telegram | REMOVE_LATER | NotImplementedスタブ | なし | — | 形式的 | 低 | 必要になった時に新規実装 |
| .github/workflows/daily-market-brief.yml | **REUSE** (adapter) | 12cron・並行制御・リトライ・Pages配備。実戦検証済み | Secrets/Pages | 高 | — | **Phase 12中核** | **高**（生きている本番） | 新パイプラインをstepとして追加する形で拡張（置換しない）。変更は要承認 |
| scripts/resolve_report_schedule.py | REUSE (as-is) | cron→slot解決 | report_schedule | 高 | あり | Phase 12 | 低 | 継続使用 |
| cloudflare/ worker 2本 | **REUSE** (as-is) | トークン隔離・暗号化KVの外部インフラ | Worker Secrets | 高 | — | Phase 10/11/12 | 中（デプロイは手動） | 継続使用。**追跡済みのwrangler.toml実id・.wrangler/cacheの扱いは要ユーザー承認**（LEGACY_AUDIT §5-4） |
| tests/（451件） | **PARTIAL_REUSE** (test-only) | ネットワーク不使用・時刻注入の作法 | 旧モジュール | 中〜高 | — | 全Phase | 低 | 旧系凍結中は全維持。新系はtests/unit等へ機能別で新設し、旧テストは対応機能の置換完了時に随伴移植/退役 |
| README.md（1,233行）/ CHANGELOG.md | PARTIAL_REUSE | 運用手順（Pages/Secrets/Worker設定）は貴重 | — | — | — | — | 低 | 運用手順を`docs/ops/`へ抽出。本文はlegacy文書として凍結 |

## 5. 集計（分類サマリー）

対象56項目（モジュール群・資産群単位）:

- REUSE: 13（as-is 8 / logic-only 4 / data-only 5 と重複計上あり）
- PARTIAL_REUSE: 22
- REBUILD: 9（ただしコード行数では最大: models/html_builder/future_intelligence/営業クラスタ等）
- REMOVE_LATER: 8
- UNKNOWN: 2（tdnet, economic_calendar — 実地検証待ち）

行数ベースの概算（src+notifiers+scripts ≒ 18,300行、テスト除く）:
- そのまま〜adapterで生存: 約20%（クライアント・スケジューラ・通知・翻訳・純関数計算群）
- ロジック/データのみ移植（書き直しを伴う）: 約35%
- 新規設計で置換（表示層・定型文層・神オブジェクト）: 約45%

**知識資産（config内ルール・DNA文書・PDF・実績データ）はほぼ100%再利用**であり、これがこのリポジトリの本当の価値である。
