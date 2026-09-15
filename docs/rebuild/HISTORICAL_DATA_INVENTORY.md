# HISTORICAL_DATA_INVENTORY — 過去データ棚卸し（全件実測）

Rebuild Stage 1.5 成果物（2026-08-29）。record countはすべて**実測値**（推測なし）。
測定対象: `/home/user/daily-market-brief`（作業コピー）および
`/home/user/takehiro104toshi-cmd/article-intelligence-data-tank`（READ ONLYクローン、HEAD=2026-07-22）。

## 1. article-intelligence-data-tank（tank）

| type | date range | record count | format | source | quality | roadmap use |
|---|---|---|---|---|---|---|
| **構造化ニュース記事**（`data/article_store/shards/YYYY/MM/*.jsonl`） | 2026-06-22〜2026-07-22（**27営業日分・欠落5日**: 6/28, 7/4, 7/5, 7/12, 7/23以降） | **3,056件**（6月75件・7月2,981件。日次2〜1,042件、7/20以降ソース拡充で急増） | JSONL（1行=1記事、**60フィールド**のリッチスキーマ） | 45有効ソース（RSS/Atom、公開情報のみ） | スキーマ設計=高。**充足率は不均一**: themes 45語彙で部分付与、primary_categoryは69%（2,116件）がuncategorized、sectors/companies/tickers/event_type/sentimentは**全件空**。言語はEN 3,041/JA 15 | **Phase 2 News Bankの初期コーパス＆スキーマ原型**。Phase 6テーマ計測の検証データ。Phase 7の素材 |
| ソースカーソル（`cursors/source_cursors.json`） | 〜2026-07-22 | 1ファイル | JSON（ETag/Last-Modified） | 増分取得状態 | 高（条件付きGETの実装証跡） | Phase 1 fetcher設計の参考 |
| 実行統計（`statistics/*.json`） | 2026-07-18〜07-22 | **35ファイル**（run単位: fetched/new/duplicates/failed_sources/coverage/index_rebuild等） | JSON | 各ingestion run | 高（Secretなし確認） | Phase 12 observabilityの参考実装データ |
| ストアマニフェスト（`manifests/`） | 同上 | 6ファイル | JSON | 同上 | 高 | 同上 |
| 配信パッケージ（`published/latest/`） | generated_at=2026-07-21T23:32Z | manifest.json＋intelligence_package.json.gz（23.6KB） | JSON＋gzip（checksum・schema_version 1.0・last_known_good機構付き） | 上記記事から選定 | 高 | Phase 2配信境界の参考 |
| private系（`data/private_insights/`＋`article_store/private/`＋`quarantine/`） | — | 計3ファイル（.gitkeep等の骨格のみ） | — | — | 実データなし | — |

**重要な質的所見**: tankのデータ価値は「件数」より（a）60フィールドスキーマ（CLAUDE.mdの
News Bank属性仕様とほぼ一致する実装済みドラフト）、（b）42ソースの**live取得実績**
（どのフィードが実際に動くかの検証データ→source_feeds.yaml v2.0.0へ反映済み）、
（c）1ヵ月の運用統計、にある。**2026-07-22で更新停止**しており、7/23以降の記事は存在しない。

## 2. daily-market-brief（dmb）

| type | date range | record count | format | source | quality | roadmap use |
|---|---|---|---|---|---|---|
| 生成レポートMarkdown（`output/*_market_brief.md`） | 2026-07-02〜2026-08-29 | **59日分** | Markdown | Legacyパイプライン | 完成品（入力データは非保存） | Phase 5較正の弱い参考。Phase 3の対照サンプル |
| 生成レポートHTML（`output/*_market_brief.html`） | 同上 | **59日分**＋history **46日×スロット=270ファイル** | HTML（~600KB/件） | 同上 | 同上（214MBの肥大要因） | 低（ARCHIVE対象） |
| 予測ジャーナル（`data/investment_journal/journal.json`） | 2026-07-01〜2026-07-19 | **5スナップショット**のみ | JSON | Legacy journal機構 | 低（間欠記録。評価は日経平均のみ） | Phase 5設計の反面教師＋最小の実データ |
| テーマ学習（`data/theme_learning/theme_learning.json`） | — | **0件**（空dict） | JSON | Legacy theme learning | 実データなし（機構は動いていたが蓄積ゼロ） | なし（DISCARD可） |
| スロット実行記録（`data/report_runs/*.json`） | 2026-07-15〜2026-08-29 | **46日分** | JSON（slot別status/retry/html_valid） | CI | 高 | Phase 12スケジューラ検証データ |
| 翻訳キャッシュ（`data/translation_cache/`） | — | **存在しない**（CIでanthropic未導入のため一度も生成されず） | — | — | — | なし |
| 羅針盤PDF（`date/rashinban/`） | 2026-06-18〜2026-07-01 | **10冊・55ページ**（8月分なし） | PDF | 岡三証券（社外秘） | 最高（Phase 0の教師データ） | Phase 0/0.5。**public露出の解消が要承認課題**（RASHINBAN_INVENTORY.md） |
| Compass DNAテキスト抽出（scratchpad） | 同上 | 10ファイル | txt | Phase 0作業 | 中（セッション一時領域・非永続） | 必要なら再抽出可能 |

## 3. 横断所見（Canonical判定）

| データ種別 | Canonical | 理由 |
|---|---|---|
| 過去ニュース記事 | **tankの`article_store`**（当面はtankリポジトリ自体を保管庫とし、Phase 2でvNext Data Bankへ取り込み） | dmbは見出しを保存しておらず（生成レポートに埋め込まれ非構造）、tankのみが構造化原本を持つ |
| ソースカタログ | **knowledge/source_reliability/source_feeds.yaml v2.0.0**（Stage 1.5で統合済み） | tank 70＋dmb固有16を統合、42件にlive実績を付与 |
| 過去市場データ | **どちらにも構造化保存なし**（dmbは表示値をHTML内に埋め込むのみ） | Phase 2 market storeは新規蓄積が必須（早期開始推奨の根拠） |
| 過去予測 | dmb journal.json（5件のみ） | Phase 5はほぼゼロからの蓄積になる前提を確定 |
| 過去レポート | dmb output/（59日分） | ARCHIVE（教師ではなく対照） |
| 運用統計 | tank statistics（35 run）＋dmb report_runs（46日） | 双方REFERENCE_ONLY |

## 4. 欠測・リスク

1. tankは**2026-07-22で停止**（最終push）。7/23〜8/29の約5週間のニュースは両システムとも
   構造化保存されていない（dmbレポートHTML内の断片のみ）。→ 再稼働 or vNext Phase 1の
   早期稼働で空白を止めることを推奨。
2. tank分類器の充足率（69% uncategorized・entity系0%）→ 過去分3,056件はPhase 2で
   **再分類（バックフィル）**する前提で扱う。スキーマがある分、再分類は容易。
3. dmbのレポートは入力と出力が分離保存されていないため、再現・検証用データとしては弱い。
