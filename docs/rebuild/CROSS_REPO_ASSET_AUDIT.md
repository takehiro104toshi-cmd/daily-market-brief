# CROSS_REPO_ASSET_AUDIT — 2旧プロジェクト横断監査

Rebuild Stage 1.5 成果物（2026-08-29）。
調査対象（実パス・READ ONLY遵守）:
- **tank** = `/home/user/takehiro104toshi-cmd/article-intelligence-data-tank`
  （GitHub public リポジトリのshallowクローン。HEAD=`72628ac` v0.9.0, 2026-07-22。
  EXTERNAL_USB上のコピーは本リモート環境から観測不能のため、GitHub main を実体として監査。
  USBローカルにのみ存在する差分・未pushファイルは未確認と明記する）
- **dmb** = `/home/user/daily-market-brief`（作業コピー。詳細は既存 `LEGACY_AUDIT.md` を前提）

EXTERNAL_USB探索結果: マウントなし（探索範囲は `RASHINBAN_INVENTORY.md` §1）。

---

## 1. article-intelligence-data-tank 概要

**目的**: ニュース記事の取得・正規化・重複排除・分類・保存と、軽量Published Package配信。
dmbとは「tank=重い保存、dmb=軽い消費」の分業設計。

- 規模: src/tank 26モジュール約3,300行＋テスト23ファイル**184件（全件オフライン・subject命名）**。
  依存はPyYAML/pytz/requests/pytestのみ（保存はstdlib json/sqlite3/gzip）。
- 記事モデル: **約70フィールド**（出典・二重タイムスタンプUTC/JST・date_inferred・分類タグ群・
  重要度/影響/緊急度/構造性スコア・3方式ハッシュdedup・rights管理・schema/parser/classifier version）。
  CLAUDE.mdのNews Bank属性仕様の**実装済みドラフト**に相当。
- 収集: 条件付きGET（ETag/304）＋cursor、並列fetch＋単一writer、per-source障害分離、
  403/404/429非再試行、date_quality補正、quarantine、atomic write。
  **feed_parserはRSS2.0/Atom/RDF全対応・名前空間対応**（dmb側はRSS2.0のみ）。
- 公式APIアダプタ: EDINET v2・e-Stat v3（メタデータのみ・ライブ未検証と明記・21テスト）。
- 分析: 全てルールベース（記事経路にLLMなし）。49カテゴリ分類・重み付きスコア・
  CJKバイグラムJaccardクラスタリング。
- 配信: 5MB上限・checksum・last_known_good保護・全滅時は非公開（前回版維持）。
- CI: 1時間4回のingestワークフロー＋private-insight分析ワークフロー。**pytestを回すCIは無い**。

**重大所見（tank）**:
| # | 所見 | 場所 |
|---|---|---|
| T1 | **HEADでCLIが起動不能**（`all_sources`を代入前参照→UnboundLocalError）。最終成功runは2026-07-21T23:33Z。**以後5週間データ更新が完全停止**しており、dmbのExternal Intelligence連携も実質stale | `scripts/run_ingestion.py:164,167` |
| T2 | `config/config.yaml`（718行）はdmb config.yamlの**stale完全コピー**。どのコードも読まない死蔵＋ソースリスト二重管理の温床 | `config/config.yaml` |
| T3 | source_class正当値リストが2箇所で乖離→regulator等5ソースが`unknown`扱いされ公式比率が過小計測 | `source_config.py:15` vs `source_portfolio.py:17` |
| T4 | 分類の充足率が低い: primary_categoryの**69%がuncategorized**、companies/tickers/sectors/event_type/sentimentは**全件未充足**（フィールドはあるが充足器が無い） | 実測（HISTORICAL_DATA_INVENTORY §1） |
| T5 | クラスタがrun内のみで**永続化されない**／duplicate_group_idが保存されない／market_reactionは常に0（スコアの25%が死んでいる） | `run_ingestion.py:226` ほか |
| T6 | 破損シャードは**シャード単位で**quarantine（1行の破損で当日全記事が読めなくなるサイレント喪失経路） | `storage.py:97` |
| T7 | **APIキーをクエリ文字列に載せる**（EDINET/e-Stat）。例外メッセージがcursor/run statsへ記録され**publicリポジトリへコミットされる**経路が実在（現状は切り詰めで偶然未流出） | `source_adapters.py:156,209` |

## 2. daily-market-brief 概要（差分のみ。全体は`LEGACY_AUDIT.md`）

- EXTERNAL_USB実体は確認不能。本環境の作業コピー（=GitHub mainのCIクローン＋本セッションの
  vNext追加分）で再確認した。**tracked以外の実体ファイルは存在しない**
  （untracked=本セッション成果物のみ、ignored=`__pycache__`等のみ、local-only PDFなし）。
- 羅針盤PDF実測: 6月9冊＋7月1冊=10冊（全てtracked＝**public露出中**）。8月分0冊。
  → `RASHINBAN_INVENTORY.md`
- 過去データ実測: output 59日分、journal 5件、theme_learning **0件**、report_runs 46日分、
  翻訳キャッシュ**未生成**。→ `HISTORICAL_DATA_INVENTORY.md`

## 3. 重複能力の比較（Canonical決定）

| 能力 | tank | dmb | Canonical判定 |
|---|---|---|---|
| RSS/Atomパース | RSS2+Atom+RDF・名前空間対応・13テスト | RSS2のみ（Atomは静かに0件） | **tank feed_parser**（Phase 1でvNextへMIGRATE） |
| 重複排除 | URL正規化＋canonical/content/title 3ハッシュ | タイトル正規化＋wire prefix除去 | **tank方式**＋dmbのwire prefix正規化をポート |
| 増分取得 | ETag/If-Modified-Since＋cursor | なし（毎回全取得） | **tank fetcher** |
| ソースカタログ | 70ソース・richメタデータ・45有効 | 24フィード（15コレクタ＋config） | **knowledge/source_feeds.yaml v2.0.0**（両者統合済み・Stage 1.5実施） |
| ソース信頼度 | trust_score 0-100 | reliability 0-1＋Tier | catalogのtrust_scoreへ一本化（source_tiers.yamlはLegacy名前引き用に残置） |
| 日本語ソース | 弱い（JA記事15件のみ） | 強い（Yahoo/NHK/日経/TDnet/EDINET） | 相互補完。カタログに両方収容済み |
| 分類・テーマ付与 | 49カテゴリ・EN slug 45テーマ（充足率低） | キーワードマッチ（JP） | スキーマはtank・語彙はknowledge/themes.yaml（en_aliases対応表をStage 1.5で作成） |
| 因果ルール・テーマグラフ | なし | causal_rules/theme_relations | **knowledge/**（既にCanonical） |
| 市場データ取得 | なし | yfinance＋Stooq | dmb market_data.py（Phase 2でadapter流用） |
| レポート生成・通知・スケジューラ | なし | あり | dmb側（既存判定どおり） |
| 記事の構造化保存 | **あり（3,056件）** | なし | **tank article_store** |
| LLM分析 | private_insightのみ（fact/解釈/推測分離・confidence上限0.6の良プロンプト） | llm_enhancer（磨き上げのみ） | 両方REFERENCE（Phase 3 Writer設計の参考。プロンプトは下記§7） |

## 4. 固有資産（片方にしかない価値）

- tank固有: 記事コーパス3,056件、feed_parser、fetcher/cursor、url_normalize、date_quality、
  dedup 3ハッシュ、run_stats設計、published packageのLKG機構、EDINET/e-Statアダプタ、
  184オフラインテスト、private_insightの分析プロンプトとscenario出力設計（4シナリオ・
  invalidation trigger・review date——**Phase 5 Prediction Journalの語彙の先行実装**）。
- dmb固有: Compass DNA成果物、causal_rules等の知識、羅針盤PDF、市場データ取得、
  6スロットスケジューラ、通知、レポートUI、Cloudflare Worker×2、v4.xの運用実績。

## 5. 技術的負債（横断）

tank: T1〜T7（§1）。dmb: `LEGACY_AUDIT.md` §4-5のとおり。
横断の追加負債: **設定・ソースリストの三重管理**（dmb config / tank config+sources.yaml /
tank内のstaleコピー）→ Stage 1.5でknowledge/へのCanonical統合により解消方針を確定。

## 6. 価値ある過去データ / 7. 知識資産

→ `HISTORICAL_DATA_INVENTORY.md` / `ASSET_SELECTION_MATRIX.md` §知識・プロンプト。
プロンプト資産の結論: tank `private_insight.py:580-600` の日本語分析プロンプト
（事実/解釈/推測の分離・confidence上限・出典厳格・JSON出力契約）は**MIGRATE**
（Phase 3/5設計時に`knowledge/prompts/`として版管理へ移す。今回はPrompt Engine非実装のため
所在の記録のみ）。dmb `llm_enhancer.py:32-40` の磨き上げ規律プロンプトはREFERENCE_ONLY。

## 8. 再利用可能インフラ（Phase 12まで導入しない・判定のみ）

| 資産 | 判定 |
|---|---|
| dmb 6スロットCI＋report_schedule.py | REUSE CANDIDATE（既存判定維持） |
| tank ingestワークフロー（毎時4回・off-round分・LKG） | REUSE CANDIDATE（Phase 2取得系の雛形） |
| Cloudflare Worker×2 | REUSE CANDIDATE |
| tank `config/config.yaml`（staleコピー） | DISCARD |
| dmb collectors Family A/B | DISCARD（catalog化済み） |

## 9. セキュリティ所見（値は転載しない）

1. tank: コミット済みSecretなし。実メールもなし（テストはexample.com）。
   **中リスク**: APIキーのクエリ文字列使用＋エラーメッセージのpublicコミット経路（T7）。
   修正はtankリポジトリ側の変更となるためREAD ONLY原則により未実施——**vNext Phase 1では
   ヘッダ認証＋ログredactionを必須要件として設計に反映**（VNEXT_RECONCILIATION参照）。
2. dmb: 既報のとおり（Cloudflare識別子ファイルの追跡・要承認のまま）。
3. **羅針盤PDF10冊がpublicリポジトリに露出中**（最重要・要ユーザー判断。RASHINBAN_INVENTORY §3）。
4. vNext/knowledgeへのSecret・識別子の持ち込みなし（テストで機械検査済み）。

## 10. 最終勧告

1. **Phase 1/2の実装母体はtank系設計を正とする**: feed_parser・fetcher・url_normalize・
   dedup・date_quality・storageの各ロジックとそのテストをvNext `sources/`・`evidence/`・
   `news/`へMIGRATEする（dmb collectorsはDISCARD確定）。
2. 記事モデル（tank models.py）を**Phase 2 NewsItemスキーマの出発点**とし、未充足フィールドの
   充足器（entity抽出・sentiment等）をPhase 2の明示タスクにする。
3. tankの運用停止（T1）への対処は2案を併記: (a) 1行修正でtankを応急再稼働（別リポジトリへの
   push権限行使になるため**要承認**）、(b) vNext Phase 1を早期に立ち上げ空白期間を止める。
   推奨は(b)優先＋(a)は承認あれば並行。
4. 知識・カタログのCanonicalは `knowledge/` で確定（Stage 1.5で統合済み）。
5. 羅針盤PDFのprivate化とtank Secret-in-URLの修正を承認事項として監督者へ上申。
