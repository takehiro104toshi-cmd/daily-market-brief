# CHANGELOG

このファイルは `CLAUDE.md` の運用プロトコルに従い、`## vX.Y` 形式で
「追加／改善／修正」を追記していく。本ファイルの記録は今回の更新から開始する
（それ以前の機能一覧・構成は `README.md` を参照）。

## v2.9 (2026-07-07) — Real-Time Freshness / Translation / Source Expansion Upgrade

「毎日読むレポート」から「岡三証券退職後も自分だけでマーケットを分析・予測し
続けるための自己改善型システム」へ。既存の分析ロジックは変更せず、翻訳・
リアルタイム性・情報源・重複統合を強化。

Phase 0（実装前調査）分類:
- A（安全に実装）: ①翻訳エンジン強化 ②2段階更新ボタン＋取得時刻表示
  ③公式RSS群の追加 ④重複ソース統合・重要度補正 ⑤情報取得時刻の見える化
- B（GitHub Actionsでのみ実データ検証可）: 新規collector（Fed/SEC/BLS/EIA/
  ECB/CoinDesk/CoinTelegraph/Yahoo Finance US）の実際のRSS取得、
  ANTHROPIC_API_KEYがある場合の実翻訳（この開発環境はネットワーク遮断・
  APIキー未設定のため。no-op経路・グレースフルフェイルは検証済み）
- C（今回は見送り）: Seeking Alpha/Benzinga（利用規約・Bot対策リスク）、
  半導体各社Newsroom・AI各社Blog（定型RSSが無くスクレイピングが必要）、
  US Treasury/BoE/IMF/World Bank/OECD/Nasdaq公式（RSS構成の確証が低い）
  — 詳細はconfig.yamlの`source_classification`とREADMEを参照

追加・改善
・①English News Translation Engine強化: Headlineに`duplicate_sources`等と
  並び`is_translated`（title_jaの有無から導出するプロパティ）を追加。翻訳
  プロンプトを金融用語重視・100文字目安・専門用語補足（EPS/CPI/FOMC/
  guidance/yield/rate cut等）へ更新。Today's Dashboardの見出し表示を
  `display_title()`（日本語訳）+ネイティブtitle属性（原文・ホバー表示）へ修正。
  ANTHROPIC_API_KEY未設定・失敗時は原文のまま（既存動作に影響なし）
・②Real-Time Update Engine: 「最新表示に更新」を2段階ボタンへ再設計。
  「ページを再読み込み」（常時表示・location.reloadのみ）と「最新レポートを
  生成する（GitHub Actionsを開く）」（actions_url設定時のみ・新しいタブで
  Run workflow画面を開くだけ・自動実行はしない・GitHub Token/Secretsは
  一切埋め込まない）。News Freshnessカードに「情報取得時刻を詳しく見る」を
  追加し、HTML生成時刻・市場データ取得時刻・各ニュースソースの取得時刻
  （SourceHealthEntryにfetched_at追加）を表示
・③Source Expansion Engine: 新規collector 6本（fed.py/sec_gov.py/
  us_gov_stats.py/ecb.py/crypto_news.py/yahoo_finance_us.py）を追加。
  公開RSSのみ使用し、既存collectorと同じ「失敗時は空リストを返す」設計を
  踏襲（main.pyの追加情報源ループに追加するだけで、失敗してもレポート生成は
  止まらない）。config.yamlに情報源の実装状況（implemented/reference_only/
  skipped）を分類・明記
・④Duplicate/Cross Source Intelligence: dedupe_headlinesが同一ニュースを
  配信していた他の情報源名（duplicate_sources）と配信元総数（source_count）
  を記録するよう拡張（重複が無ければ従来通りsource_count=1）。
  news_ranking.pyで2社以上・信頼度★4以上の重複報道に+1〜+2の補正を追加
  （新しい評価基準の創作ではなく既存Source Trustスコアの集計）。
  source_trust.pyにcombined_trust_for_sources()を追加し、HTMLへ
  「○社が同一ニュースを報道／Combined Trust」を表示。Source Trustの
  ティア判定にSEC/BLS/BEA/EIA/ECB/BoE/Barron's/CoinDesk/CoinTelegraph等を追加

変更ファイル
・src/collectors/: news.py（duplicate_sources/source_count/is_translated）、
  fed.py・sec_gov.py・us_gov_stats.py・ecb.py・crypto_news.py・
  yahoo_finance_us.py（すべて新規）
・src/analysis/: source_trust.py（combined_trust_for_sources追加・ティア拡張）、
  news_ranking.py（重複ソース補正）、data_freshness.py（fetched_at追加）、
  translation.py（プロンプト更新）
・src/report/html_builder.py（2段階更新ボタン・情報取得時刻・重複表示・
  Dashboard翻訳表示）
・main.py（新規collector配線）、config.yaml（新規ソース設定・分類・reliability）
・tests/test_v2_9_realtime_translation_sources.py（新規・15件）、
  tests/test_html_builder.py（更新ボタン仕様変更に伴う2件更新）

pytest
244 passed（既存229維持＋v2.9で15件追加）

## v2.8 (2026-07-06) — Smart Intelligence Evolution

「毎日読むレポート」から「毎日学習し続ける投資AI」へ。既存の分析ロジック
（Momentum・Confidence・Watchlist判定）の設計は維持し、学習・信頼度・優先度の
仕組みを追加。HTMLのみ変更（Markdown版は維持）。外部ライブラリ追加なし。

追加（学習）
・Investment Journal（①）: 新規 src/analysis/investment_journal.py。毎日のAI判断
  （重要ニュース・テーマ・シナリオ・Thesis・Regime・Money Flow・Top Picks・
  Confidence・重要イベント＋参照価格）を data/investment_journal/journal.json へ
  追記し、30/90/180日後に現在の市場と機械的に答え合わせ（★評価・的中/外れ）。
  新セクション「Learning History」を追加。市場データが無い環境では評価はスキップ
・Theme Confidence Learning（②）: 新規 src/analysis/theme_learning.py。テーマ予想を
  data/theme_learning/theme_learning.json へ蓄積し、30日後の地合いで勝率・平均
  リターン・平均継続日数を集計。勝率で Future Intelligence の Confidence を上下限
  つき（-20〜+10）実績補正（build_future_intelligenceにtheme_win_rates引数を追加。
  未指定なら従来通り）。新セクション「Theme Confidence Learning」を追加

改善（要約・信頼度・優先度）
・Scenario Engine v2（③）: 新規 src/analysis/scenario_v2.py。強気/中立/弱気を
  期待値（確率）の高い順に最大3つへ整理し①②③で表示。発生条件・恩恵/悪影響
  セクター・注目銘柄・因果関係・時間軸は「詳しく」で展開。新セクション
  「今日の3大シナリオ（期待値順）」を追加
・情報ソース信頼度（⑥）: 新規 src/analysis/source_trust.py。出典名から★1〜5と
  ティア（公式発表/一流メディア・IR/主要メディア/一般メディア/参考情報）を判定し、
  ニュース・Executive Summaryの各カードに Source Trust バッジ＋理由を表示
・Why Today（⑦）: 新規 src/analysis/why_today.py。既存データのみから「なぜ今日
  見るべきか」を1〜2行で生成し、対象カードの先頭に表示（新予測はしない・長文禁止）
・低重要度記事の折りたたみ（⑧⑨）: ニュースは重要度×鮮度で初期表示を選別
  （★★★★☆以上／24時間以内かつ★★★☆☆以上／1位は必ず表示）。★★★☆☆以下・
  48時間超は details に折りたたむ（削除しない）
・英語ニュース自動翻訳（④・安全スキャフォールド）: 新規 src/analysis/translation.py。
  ANTHROPIC_API_KEYがある時のみ英語見出しを日本語訳し「日本語→原文を見る」で表示。
  キー未設定・失敗時は原文のまま（Headlineにtitle_ja/display_title()を追加）
・Weekly Event 自動取得（⑤・安全スキャフォールド）: 新規
  src/collectors/economic_calendar.py。economic_calendar.url設定時のみ公開カレンダーを
  取得しconfig.yamlのmacro_eventsとマージ。未設定・失敗時は従来通りconfigのみ使用

変更ファイル
・src/analysis/: investment_journal.py / theme_learning.py / scenario_v2.py /
  source_trust.py / why_today.py / translation.py（すべて新規）、models.py・
  future_intelligence.py（既存・後方互換で拡張）
・src/collectors/: economic_calendar.py（新規）、news.py（Headlineにtitle_ja追加）
・src/report/html_builder.py（新セクション・Source Trust・Why Today・折りたたみ）
・main.py / config.yaml / .github/workflows/daily-market-brief.yml（JSON永続化）
・tests/test_v2_8_smart.py（新規・20件）、tests/test_v2_7_upgrade.py（折りたたみ仕様更新）
・data/investment_journal/README.md・data/theme_learning/README.md（新規）

pytest
229 passed（既存209維持＋v2.8で20件追加）

注意（この環境での検証範囲）
・④翻訳・⑤自動取得はネットワーク/APIキーが必要なため、開発環境では実データ検証
  不可（no-op経路とHTML表示は検証済み。GitHub Actions側で有効化される）。
  それ以外の①②③⑥⑦⑧⑨は実データ経路込みで検証済み

## v2.7 (2026-07-06) — Market Intelligence Knowledge Upgrade ＋ Weekly Event Impact Calendar

「毎朝ニュースを読むシステム」から「世界の変化を理解し長期投資判断を支援する
AIストラテジスト」への強化。分析ロジックの設計（Momentum・Confidence・
Watchlist判定・FIの計算）は変更せず、知識品質・鮮度・情報密度・可読性を改善。

追加・改善
・羅針盤Knowledge強化（①）: 「新しい順に3件読む」→「最大100件から知識を構築」
  する知識ベース方式へ。全ファイル走査→重複統合（正規化キー）→重要度
  （複数号での繰り返し登場数＋キーワード密度）順に重要な知識だけ抽出。
  カテゴリを拡張（景気循環・金融政策・金利・為替・半導体・AI・企業分析）し、
  philosophy_patterns（投資哲学・利益確定・リスク規律）を新設。
  本文転載禁止の制限（80文字/件・5件/カテゴリ・抜粋120文字）は不変
・ニュース鮮度最優先（②）: news_rankingに鮮度軸を追加。24時間以内は+2加点、
  48時間超は-4の大幅減点。ただしFOMC・日銀・決算・国家戦略・雇用統計・CPI等
  「影響期間の長いイベント」は例外として減点しない（鮮度×影響期間の両立）。
  日時不明記事は加減点なし。既存8軸の算出方法は不変
・情報密度（③）: ニュースランキングは重要5件のみ通常表示（6位以下は折りたたみ）。
  FIのメガトレンド／Theme Momentum／成熟度メモ／テーマ別診断／Investment
  Thesisは重要度順（見出し件数・スコア・Confidence）に上位8件のみ通常表示し、
  残りは「残りN件を表示」で展開（選別は表示のみ。計算は全件のまま）
・要約表示＋詳しくボタン（④⑤⑦）: 各カード・各項目を「2〜4行の要約→
  『詳しく』（HTML標準details/summary・外部JS不要）」の3分UIへ。
  Executive Summary／ニュースランキング／Watchlist／FI診断・成熟度／
  Watchlist・Stock Intelligence／Investment Thesisに適用
・重要度表示（⑥）: 全セクションカードの見出しに「重要度◯◯」（★×20の
  100点満点換算）バッジを追加
・FI再構成（⑧）: 冒頭に「結論→重要ポイント3つ→詳しくは各ブロック」の
  結論ボックスを追加（既存シグナルの転記のみ・新分析なし）
・Investment Thesis再構成（⑨）: 各テーマを「結論→理由3つ→詳しく」へ
・Watchlist再構成（⑩）: 銘柄ごとに一行要約→詳しくへ
・Weekly Event Impact Calendar（追加依頼）: 新セクション「今週の重要イベント・
  経済指標」。config.yamlのmacro_events＋決算発表予定から今日〜7日後の
  イベントだけを「近い順→重要度順」で表示。カウントダウン（本日21:30／
  あと1日 5時間／あと3日、日本時間）・★と重要度・国/地域・影響対象・
  想定される影響（条件付き整理のみ）・詳しく（なぜ重要か/見るべきポイント/
  関連テーマ）付き。macro_eventsに任意のtime("21:30")を登録すると時間まで
  表示。データが無い日は「直近1週間の重要イベントは登録されていません」。
  新規外部APIなし（新規 src/analysis/weekly_events.py＋WeeklyEventEntry）
・HTML版のみ対象（⑪）。Markdown/モバイル版は変更なし

変更ファイル
・src/analysis/rashinban_loader.py / models.py / news_ranking.py /
  weekly_events.py（新規） / src/report/html_builder.py / main.py / config.yaml
・tests/test_v2_7_upgrade.py（新規） / tests/test_weekly_events.py（新規） /
  tests/test_html_builder.py（セクション追加に伴う範囲修正1件）

pytest
209 passed（既存維持＋v2.7で19件追加）

## v2.6 (2026-07-05) — Rashinban Learning Source System v1.0

追加（岡三「羅針盤」を、コード更新なしで毎日の分析精度向上に使える学習ソースにする）

・Rashinban Loader（①）: 新規 `src/analysis/rashinban_loader.py`。
  `data/rashinban/` の .md/.txt を新しい順に最大3件（config可変）読み込み、
  latest.md→ファイル名日付（YYYY-MM-DD）降順で最新を判定。READMEは対象外。
  フォルダが無い・空でもエラーにならず空のまま動作
・RashinbanKnowledge（②）: models.py に追加（source_files／latest_date／
  相場観・テーマ・銘柄選定・リスク・時間軸の5パターン＋raw_excerpt_summary＋
  emphasized_theme_labels）。frame_count()／has_content() 付き
・型の抽出（③）: すべてルールベース（AI API不使用）のキーワード分類。
  本文転載防止のため 1件80文字・カテゴリ5件・抜粋120文字に制限。
  重点テーマは既存 macro_themes ラベルとの照合のみ（新テーマ生成なし）
・分析への接続（④）: 羅針盤がある場合のみ、重点テーマ一致分に
  News Ranking=+1の補助加点＋理由追記／Strategist View・Executive Summary=
  参照した旨の一文／Future Intelligence=Theme Momentum理由追記・
  Investment Thesis監視指標追加。無い場合は従来と完全に同一動作
  （既存スコアリング・判定ロジックの設計は不変）
・HTML表示（⑤）: 「Rashinban Learning Source」小カードを追加。
  読み込みファイル名・最新日付・抽出フレーム数・使用状況のみ表示し、
  本文・抜粋は一切表示しない（未配置時はスキップした旨を表示）
・自動読み込み（⑥）: GitHub Actionsはmain.py実行時に data/rashinban/ を
  自動で読むため、workflowの変更なし（latest.md の差し替えだけで反映）
・運用手順（⑦）: `data/rashinban/README.md` 新規＋READMEに
  「GitHub Webだけで追加する手順」（PC・Claude Code不要）を追記
・config.yaml: `rashinban:`（dir／max_files）を追加
・tests/test_rashinban_loader.py 新規（空フォルダ／md・txt読込／最新判定／
  Knowledge生成／HTML表示／長文転載なし／羅針盤なしで従来動作、の8観点）

対象外（v1.0の割り切り）
・PDF/DOCXの解析はしない（md/txtへ変換して置く運用）
・羅針盤本文のレポート転載・長文引用はしない（分析フレームとしてのみ利用）

## v2.5 (2026-07-05) — Market Brief UI/UX & Freshness Upgrade

追加・改善（HTML版のみ。分析ロジック・Momentum・Confidence・Watchlist判定は不変。
外部JS/CSSライブラリなし・素のJavaScriptのみ。Markdown/モバイル版は変更なし）

・ニュース鮮度の表示（①）: 重要ニュースランキング・AI Executive Summary・
  Today's Dashboardの各ニュースに、投稿日時・約何時間前か・鮮度バッジ
  （最新≦6h=赤／24時間以内=緑／48時間以内=オレンジ／古い=グレー／
  日時不明=グレー）を色分き表示。順位ロジックは変更なし
  （鮮度タイブレークはv2.3で導入済み。日付不明記事が不利になる挙動も同様）
・トップメニューグリッド（②③）: レポート上部にDashboard／Executive Summary／
  Future Intelligence／重要ニュース／Watchlist／Stock Intelligence／
  世界のお金／Data Quality／営業メモへの9ボタンをAppMedia風グリッドで配置
・目次リンクを新しいタブで開く（④）: 全目次リンクにtarget="_blank"
  rel="noopener"を付与（リンク先は同一HTML内アンカー）
・セクションカード強化（⑤）: 各カードに「ひとこと説明」（主要9セクション）・
  開く/閉じる（▾/▸）・コピー（既存）・お気に入り（☆/★）を追加
・お気に入り機能（⑥）: ☆で登録→★、★で確実に解除→☆。localStorage
  （mkt_favs）に保存し再読み込み後も維持。表示オプション内に一覧を表示し、
  解除すると一覧からも消える。0件時は「お気に入りはありません」。
  Playwright実機検証で登録→解除→再登録→再読込維持を確認済み
・フローティング操作ボタン（⑦）: 右下に ☰目次／★お気に入り／↑TOP の3ボタン
・簡易検索＋タグUI（⑧）: キーワード入力でセクションタイトル・本文を検索し
  一致しないカードを非表示。クリアボタン・0件メッセージ付き。
  タグ（AI/半導体/電力/防衛/EV/金利/為替/消費）タップで即絞り込み
・表示オプション改善（⑨）: 既存4項目に「お気に入りのみ表示」を追加
  （localStorage保存）

変更ファイル
・src/report/html_builder.py
・tests/test_html_builder.py

pytest
182 passed

コミット
（下記参照）

## v2.4 (2026-07-05) — Investment Thesis Engine v2.0

追加（Future Intelligence Engineへの統合のみ。既存の分析ロジック・スコアリング・
判定・新しいAPIの追加はなし。営業利用ではなく自分自身の長期資産形成・投資判断を
最優先目的とする）

・Investment Thesis（テーマ別・長期投資仮説）: macro_themeごとに以下10項目の
  投資仮説を生成し、Long-term Strategyブロック（Markdown/HTML/モバイル）へ
  Confidence（分析根拠の充実度）の高い順に表示
  - 現在何が起きているか: Theme Momentum Scoreのreason（本日のシグナル説明）を転記
  - 今後起こりそうな変化［AI分析］: テーマ別診断のCatalyst先頭を非断定的に
    言い換えるのみ（Catalystが判断材料不足の場合は正直に分析材料不足と表示）
  - 恩恵を受ける業界: causal_rules.beneficiary_sectors
  - 恩恵企業: 既存の恩恵銘柄ロジック（beneficiary_sectors→related_tickers）の結果
  - 二次的恩恵企業: theme_relations（Cross Theme Mapping）で1段階隣接する
    テーマの恩恵企業
  - まだ注目されにくい企業: theme_relationsで2段階離れたテーマの恩恵企業
    （因果チェーン上、直接の恩恵銘柄として言及されにくい銘柄。新たな銘柄推定ではない）
  - 投資期間: 既存の中長期テーマ割り付け（半年/1年/3年/5年/10年）をそのまま転記
  - 監視指標: Theme Momentum Scoreの推移・関連ニュース件数＋既存のテーマ→
    イベント対応表（半導体市況・金利動向等）からの機械的な列挙
  - 崩れる条件［AI分析］: テーマ別診断のRisk（失速要因）を転記
  - 投資仮説まとめ: Stock Intelligenceと同じinvestment_storyロジックによる
    時系列の因果チェーン（テーマ→Catalyst→関連テーマへの波及→非断定的な結び）
・すべて既存シグナル（Theme Momentum・Lifecycle・Catalyst・Risk・Confidence・
  causal_rules・theme_relations）の転記・機械的な組み合わせのみで構成。
  目標株価・PER/EPS予想・「買い」「売り」等の推奨・期待リターンは一切生成しない
・InvestmentThesisEntry dataclass＋FutureIntelligenceBundle.investment_theses
  フィールドを追加（デフォルト値付きのため既存の呼び出し箇所に影響なし）

変更ファイル
・src/analysis/models.py
・src/analysis/future_intelligence.py
・src/report/sections.py
・src/report/html_builder.py
・src/report/mobile_builder.py
・tests/test_future_intelligence.py

pytest
175 passed

コミット
（下記参照）

## v2.3 (2026-07-05) — Data Freshness & News Quality v2.0

追加・改善（鮮度タイブレーク＋可視化＋ログ強化のみ。重要度スコアの算出・
Momentum・Confidence・Watchlist判定・Executive Summaryの設計は一切変更なし）

・News Rankingの鮮度タイブレーク（最優先）: 順位決定を
  「スコア → 記事日時（pubDate）の新しい順 → 取得順」へ変更。
  スコア自体は不変のため、スコア差がある場合の順位は従来と完全に同じ。
  同点の場合のみ、新しい記事が古い記事より上位になる
  （従来は取得順のみで、数日前の高スコア記事が毎日1位に再選出され続ける
  根本原因になっていた——前回のRoot Cause Investigation v2で実証済み）。
  日時を解析できない記事は同点内の最後尾に回す。
・News Freshness Score: 各記事の経過時間から★1〜5を内部算出
  （24h未満★5／48h未満★4／72h未満★3／96h未満★2／それ以上★1）。
  表示専用でランキングには影響しない。
・News Freshnessカード（HTML版・レポート上部）: 最新ニュース日時／最も古い
  採用記事日時／採用記事平均経過時間／採用記事件数／RSS取得件数／
  ランキング対象件数／レポート生成日時／データ鮮度評価（★＋ラベル）
・Data Qualityセクション（HTML版・引用一覧の下）: ニュース取得★／市場データ★／
  Future Intelligence★／Watchlist★（いずれも取得できた割合からの機械的評価）
  ＋更新日時・最新ニュース・平均鮮度・情報源数・ランキング対象件数
・GitHub Actions Job Summaryへ「Data Freshness Summary」を追加:
  RSS取得件数／重複削除後件数／ランキング1位の記事日時・タイトル／
  Executive Summary・Dashboard採用記事日時／HTML生成時刻／鮮度評価
・同じくJob Summaryへ「RSS Source Health」を追加: 情報源ごとに
  成功／取得失敗（0件）・件数・最新記事日時を一覧表示。
  ローカル実行時も同内容をINFOログへ出力（取得失敗が初めて可視化される）
・実装は新設の src/analysis/data_freshness.py に集約（読み取り専用の計測
  レイヤー。将来の鮮度加点・情報源信頼度・速報フラグはここへ追加できる構造）

変更ファイル
・src/analysis/data_freshness.py（新規）
・src/analysis/news_ranking.py
・src/collectors/news.py
・src/report/html_builder.py
・main.py
・tests/test_data_freshness.py（新規）

pytest
168 passed

コミット
（下記参照）

## v2.2 (2026-07-04)

追加・改善（UI・操作性のみ。分析ロジック・スコアリング・Future Intelligence／
Watchlist Intelligence／Stock Intelligenceの判定には一切変更を加えていない）

・Today's Action（HTML／Markdown／モバイル共通）: Future Intelligence Engine
  の最上部に、その日確認すべき事項を3〜5件表示。既存のTheme Momentum Score
  最上位テーマ・ドル円レートの有無・本日のイベント・業界モメンタム最上位・
  「決算」を含む既存ニュース見出しの有無だけから機械的に組み立てる
  （`format_utils.todays_action_items()`。新しい予測・分析は行わない）

・HTML版 UI改善
  - 画面右下に常時表示の「↑ TOP」ボタンを追加（Today's Dashboardへスムーズ
    スクロール。`scroll-behavior: smooth`のみ、追加JSなし）
  - 各セクション末尾に「← 前」「次 →」のワンタップ移動ボタンを追加
  - Future Intelligenceの5大ブロック（Today's Future Signals／Theme
    Intelligence／Industry Intelligence／Stock Intelligence／Long-term
    Strategy）を`<details>/<summary>`による開閉式に変更
    （デフォルトはToday's Future Signalsのみ展開、他は折りたたみ。追加JS不要）
  - 既存のMomentum Score・Confidence Scoreが80以上のテーマにのみ「NEW」
    バッジを表示（新しいスコア算出ロジックではなく、既存スコアへの機械的な
    閾値判定のみ）
  - 目次・Future Intelligenceの重要度★表示を★の数に応じて色分け
    （★5=赤／★4=オレンジ／★3=青／★2以下=グレー）
  - 各セクション右上に📋コピー ボタンを追加（そのセクションのテキストのみを
    クリップボードにコピー）
  - Future Intelligence内のテーマ名・銘柄名について、Theme Intelligence／
    Stock Intelligenceの該当項目が存在する場合のみジャンプリンク化
    （既存のtheme_diagnosis.label／stock_intelligence.tickerとの一致判定の
    みで、新たな関連付けロジックは追加していない）
  - Today's Dashboardの主要指標を画面上部に小さく残す
    sticky（position: sticky）ミニバーを追加
  - モバイル向けにボタン・タップ領域のサイズを拡大

・HTML版 表示オプションパネル（レポート上部に新規カード）
  - コンパクト表示 / 詳細表示切替（コンパクト時は各セクションの詳細説明
    文・凡例のみを非表示にし、見出し・数値・★評価等の要点は残す）
  - 営業セクション一括非表示（営業準備／営業トーク／営業向けコメント／
    岡三証券営業向けコメント／朝会コメント／想定質問と回答例）
  - Future Intelligenceの全ブロック一括開閉ボタン
  - ライト／ダークモード切替（CSS変数の上書きのみ。既存の色分け配色は
    そのまま維持）
  - 上記4設定はlocalStorageに保存し、次回表示時も維持する
  - 外部ライブラリ・フレームワークは使用せず、素のJavaScriptのみで実装

・Markdown版・モバイル版はTable of Contents/表示内容そのものは変更せず、
  Today's Actionの追加のみ反映（表示オプション・折りたたみ等のUI操作は
  HTML版のみ対応）

変更ファイル
・src/report/format_utils.py
・src/report/sections.py
・src/report/html_builder.py
・src/report/mobile_builder.py
・src/report/builder.py
・tests/test_future_intelligence.py
・tests/test_html_builder.py
・tests/test_report_builder.py
・tests/test_mobile_builder.py

pytest
155 passed

コミット
（下記参照）

## v2.1 (2026-07-04)

追加・改善（情報設計・UIのみ。新しい分析ロジック・スコアリング・判定は追加していない）
・Future Intelligence Engine v2.1: 既存14項目（世界のメガトレンド／Theme
  Momentum Score／Early Signal Detection／世界のお金の流れ／テーマ成熟度
  メモ／テーマ別診断／次に来る業界／サプライチェーン分析／国家戦略メモ／
  Future Map／日本株への波及／Watchlist Intelligence／Stock Intelligence／
  中長期テーマ）を「世界→テーマ→業界→銘柄→長期戦略」の5ブロック
  （Information Architecture）へ再構成
  - ① Today's Future Signals ★★★★★（世界のメガトレンド／Theme Momentum
    Score／Early Signal Detection／世界のお金の流れ／今日もっとも重要な
    変化＝既存Theme Momentum Score最上位の理由をそのまま抜粋するハイライト）
  - ② Theme Intelligence ★★★★★（テーマ成熟度メモ／テーマ別診断＝
    Momentum→Lifecycle→Catalyst→Risk→Confidence→関連テーマ）
  - ③ Industry Intelligence ★★★★☆（次に来る業界／サプライチェーン分析／
    国家戦略メモ／Future Map）
  - ④ Stock Intelligence ★★★★★（日本株への波及／Watchlist Intelligence／
    Stock Intelligence＝銘柄別投資ストーリー）
  - ⑤ Long-term Strategy ★★★★☆（中長期テーマ＝半年〜10年の時間軸）
  - 各ブロック冒頭に「このブロックで分かること」を1〜2行で表示、重要度★を
    表示、Future Intelligence専用の内部目次を追加
  - HTML版: 各大ブロックをカード化し、Today's Future Signals=青／Theme
    Intelligence=紫／Industry Intelligence=緑／Stock Intelligence=
    オレンジ／Long-term Strategy=ゴールドに色分け。目次から各ブロックへ
    ジャンプ可能
  - モバイル版: 折りたたみは使わず、見出し（###）を大きくしてスクロール
    で読める形に変更（内容は既存の条件付きハイライトのまま。Long-term
    Strategyのみ既存bundle.horizon_groupsを新たに表示に追加）
・レポート全体の目次を「投資家が毎朝見る順番」＝重要度順に再構成
  （今日の結論→AI Executive Summary→岡三ストラテジスト視点→Future
  Intelligence Engine→今日の相場シナリオ→…の順）。Future Intelligence
  Engineは全体目次では1項目のみ表示し、内部の5ブロック専用目次を別途持つ。
  HTML・Markdown・モバイルの3形式すべてで同じ順序・重要度★表示に統一
・Markdown版に目次（`## 目次`）を新規追加（HTML版は既存の目次カードの並びを
  変更、モバイル版はセクション番号を並び替え）

これにより、毎朝「上から順番に読むだけ」で世界情勢→マーケット→テーマ→
業界→銘柄→投資判断へ自然につながる構成になった。分析ロジック・
スコアリング・各セクションの表示内容そのものは一切変更していない。

変更ファイル
・src/report/sections.py
・src/report/html_builder.py
・src/report/mobile_builder.py
・src/report/builder.py
・tests/test_future_intelligence.py
・tests/test_report_builder.py
・tests/test_html_builder.py
・tests/test_mobile_builder.py

pytest
142 passed

コミット
（下記参照）

## v2.0 (2026-07-04)

追加
・Future Intelligence Engine v2.0: 「Stock Intelligence」を追加（既存の
  Future Intelligence Engineセクション内に追加。Watchlist Intelligenceで
  一致した銘柄のみを対象）
  - 表示項目: 銘柄名・ティッカー・関連テーマ・関連テーマ数・Momentum・
    Lifecycle・Catalyst・Risk・Confidence・現在の判断（注目継続／押し目待ち
    ／過熱警戒／材料待ち／判断材料不足。既存のWatchlist Intelligenceの
    判定ルールをそのまま流用し整合性を維持）
  - 新規項目①なぜ長期で見るのか: テーマ名・Catalyst・Lifecycle・Momentum
    のみから機械的に組み立てた定性文
  - 新規項目②今後注目するイベント: 決算・設備投資動向に加え、関連テーマ
    （半導体市況・電力需給・金利動向・為替動向等）から機械的に導出。
    AIによる新たな予測はしない
  - 新規項目③注意すべきリスク: 既存Riskを複数テーマ分まとめて拡張表示
  - 新規項目④関連するテーマ: config.yamlのtheme_relations（Cross Theme
    Mapping）をそのまま利用
  - 新規項目⑤投資ストーリー: テーマ名→Catalyst→関連テーマへの波及→
    非断定的な結び、という時系列の因果チェーンのみで構成。目標株価・
    PER/EPS予想・「買い」「売り」等の推奨・期待リターンは一切生成しない
  - Markdown・モバイル版・HTML版すべてに反映（既存のFuture Intelligence
    Engineセクション内。他のセクション構成・既存のWatchlist Intelligence
    のロジックは変更していない）

これにより、Future Intelligence → Watchlist Intelligence → Stock
Intelligence まで一気通貫で分析できるようになった
（世界の変化→テーマ→企業→長期投資ストーリー）。

変更ファイル
・src/analysis/models.py
・src/analysis/future_intelligence.py
・src/report/sections.py
・src/report/html_builder.py
・src/report/mobile_builder.py
・tests/test_future_intelligence.py

pytest
136 passed

コミット
（下記参照）

## v1.16 (2026-07-04)

追加
・Future Intelligence Engine v1.9: Macro Themeを17拡張し、Watchlist
  Intelligenceの一致率をさらに向上（新しい分析ロジックは追加せず、
  macro_themes／causal_rules／sectors／theme_relationsの辞書拡張のみ）
  - 追加テーマ: 自動車／EV／蓄電池／金融／金利／為替／消費／人材／広告／
    SaaS／スマートフォン／クラウド／決済／旅行／住宅／建設／インバウンド
    （物流は既存テーマのため、causal_rulesのみ追加して強化）
  - 単純な業種分類ではなく「投資テーマとの経済的な因果関係」を優先して
    紐付け（例: 自動車→EV→蓄電池→半導体・電力・資源、金利→金融→為替、
    AI→クラウド→データセンター→電力）
  - config.yamlのtheme_relationsを拡張し、テーマ別診断の「関連テーマ」
    表示を強化
  - Markdown・モバイル版・HTML版すべてに反映（既存のFuture Intelligence
    Engineセクション内。他のセクション構成・既存の診断ロジックは変更して
    いない）

Watchlist Intelligence改善効果（手元のconfig.yamlで実測、監視銘柄30件）
  - 追加前（v1.8時点）: 判断材料不足 6件 ／ 一致率 24/30（80%）
    （未一致: トヨタ自動車・三菱UFJ・リクルート・デンソー・Apple・Tesla）
  - 追加後（v1.9）: 判断材料不足 0件 ／ 一致率 30/30（100%）
    （例: トヨタ自動車→自動車・EV・蓄電池・為替・消費、
    三菱UFJ→金融・金利・決済、Apple/リクルート→AI・半導体・人材・広告・
    SaaS・スマートフォン・クラウド・決済、Tesla→自動車・EV・蓄電池・為替・消費）

変更ファイル
・config.yaml
・tests/test_future_intelligence.py

pytest
130 passed

コミット
（下記参照）

## v1.15 (2026-07-04)

改善
・Future Intelligence Engine v1.8: Watchlist Intelligenceの精度向上
  （新しい分析ロジックは追加せず、辞書・マッピングの充実のみ）
  - config.yamlのsectors（related_tickers）・causal_rules
    （beneficiary_sectors）を、「投資テーマとの経済的な因果関係」を優先して
    拡充。例: AI関連の設備投資拡大は、半導体（東京エレクトロン等）だけで
    なく、データセンター運営主体（NTT・Microsoft・Amazon等）、電力設備・
    電気工事（きんでん・日立製作所）、電線・素材（古河電工・住友電工等）
    まで、単純な業種分類ではなくサプライチェーン・設備投資の因果関係で
    紐付けた
  - config.yamlに theme_relations（テーマ同士の対応付け。人手による参考
    情報でAIによる生成ではない）を新設し、テーマ別診断に「関連テーマ」
    （例: AI→半導体・電力・サイバーセキュリティ・自動運転・量子）を追加
  - Watchlist Intelligenceで「判断材料不足」になる銘柄をテスト環境で
    実際に削減できることを確認（テストで検証）
  - Markdown・モバイル版・HTML版すべてに「関連テーマ」を反映（既存の
    Future Intelligence Engineセクション内。他のセクション構成・既存の
    診断ロジックは変更していない）

変更ファイル
・config.yaml
・src/analysis/models.py
・src/analysis/future_intelligence.py
・src/report/sections.py
・src/report/html_builder.py
・src/report/mobile_builder.py
・tests/test_future_intelligence.py

pytest
127 passed

コミット
（下記参照）

## v1.14 (2026-07-04)

追加
・Future Intelligence Engine v1.7: 「Watchlist Intelligence（監視銘柄×
  テーマ診断）」を追加（既存のFuture Intelligence Engineセクション内に
  小見出しとして追加）
  - config.yamlのwatchlist銘柄（jp_stocks/us_stocks）と、v1.6のテーマ別
    診断（Momentum・Lifecycle・Catalyst・Risk・Confidence）を、既存の
    causal_rules恩恵銘柄ロジック（テーマ→beneficiary_sectors→
    related_tickers）だけを使って照合し、長期の資産形成・投資判断のために
    「今見るべき銘柄」を整理する。営業利用ではなく自分自身の投資判断を
    最優先目的とする
  - 表示項目: 銘柄名・ティッカー・関連テーマ・Momentum・Lifecycle・
    Catalyst・Risk・Confidence・現在の判断ラベル・判断理由
  - 判断ラベルは「注目継続／押し目待ち／過熱警戒／材料待ち／判断材料不足」
    のみを使用し、「買い」「売り」等の断定的な売買助言は一切行わない
  - Markdown・モバイル版・HTML版すべてに反映（既存のFuture Intelligence
    Engineセクション内。他のセクション構成は変更していない）

変更ファイル
・src/analysis/models.py
・src/analysis/future_intelligence.py
・src/report/sections.py
・src/report/html_builder.py
・src/report/mobile_builder.py
・tests/test_future_intelligence.py

pytest
123 passed

コミット
（下記参照）

## v1.13 (2026-07-04)

追加
・Future Intelligence Engine v1.6:「テーマ別診断（Momentum→Lifecycle→
  Catalyst→Risk→Confidence）」を追加（既存のFuture Intelligence Engine
  セクション内に小見出しとして追加）
  - 本システムの最優先目的を「営業ツール」ではなく「世界の変化をいち早く
    察知し、長期の資産形成・投資判断に役立てる未来分析システム」と位置づけ、
    macro_themeごとにMomentum→Lifecycle（フェーズ・継続性）→Catalyst
    （加速要因）→Risk（失速要因）→Confidence（分析根拠の充実度）の順で表示
  - Catalyst（加速要因）・Risk（失速要因）は、ニュース・Executive Summary・
    Theme Momentum・Early Signal・causal_rules・durable_themes・
    サプライチェーン（恩恵銘柄）・国家戦略メモ・世界のお金の流れという
    既存シグナルのみから機械的に導いた「AI分析」であることを明記し、
    具体的な数値・政策名・企業業績の断定はしない
  - Confidence Score（0〜100）は「未来が当たる確率」ではなく、上記シグナル
    のうち実際に確認できたものの数（＝分析根拠の充実度）を表すことを明記
  - Markdown・モバイル版・HTML版すべてに反映（既存のFuture Intelligence
    Engineセクション内。他のセクション構成は変更していない）

変更ファイル
・src/analysis/models.py
・src/analysis/future_intelligence.py
・src/report/sections.py
・src/report/html_builder.py
・src/report/mobile_builder.py
・tests/test_future_intelligence.py

pytest
120 passed

コミット
（下記参照）

## v1.12 (2026-07-04)

追加
・Future Intelligence Engine v1.5:「世界のお金の流れ（市場シグナルベース）」を
  安全な縮小版として追加（既存のFuture Intelligence Engineセクション内に
  小見出しとして追加）
  - 実際の機関投資家ポジション・資金流入額は取得していないため、具体的な
    資金フローは断定しない旨を冒頭に明記（「実際の資金流入額ではなく、
    公開市場データとニューステーマから見た資金の向かいやすさです」）
  - 公開市場データ（日経平均・TOPIX・NASDAQ・SOX・VIX・米10年金利・
    ドル円・WTI・金）とTheme Momentum Score・Early Signal Detection・
    Sector Ranking・causal_rules・durable_themesという既存シグナルのみ
    から、「AI・半導体」「金融・銀行」「防衛・電力・インフラ」「内需・消費」
    「コモディティ・資源」の5テーマについて、資金方向ラベル（流入しやすい／
    中立／流出しやすい／判断材料不足）・理由・関連テーマ・関連セクター・
    営業で話すポイントを機械的に算出
  - リスクオン/オフ・グロース優位/バリュー優位の参考情報も、VIX指数・
    NASDAQ対TOPIXという既存の市場データのみから算出し、文脈情報として付記
  - 「資金が流入している」「機関投資家が買っている」「海外勢が買っている」
    「◯億円流入」等の断定・捏造表現は一切使わず、「資金が向かいやすい」
    「物色されやすい」「市場シグナル上は追い風」等の非断定表現に統一
  - Markdown・モバイル版・HTML版すべてに反映（既存のFuture Intelligence
    Engineセクション内。他のセクション構成は変更していない）

変更ファイル
・main.py
・src/analysis/models.py
・src/analysis/future_intelligence.py
・src/report/sections.py
・src/report/html_builder.py
・src/report/mobile_builder.py
・tests/test_future_intelligence.py

pytest
116 passed

コミット
（下記参照）

## v1.11 (2026-07-04)

改善
・Future Intelligence Engine v1.4: Theme Momentum Score・Early Signal Detectionの
  判定材料を拡張
  - Theme Momentum Score: 本日の関連見出し件数・重要ニュースとの一致・
    causal_rules該当・durable_themes該当に加えて、Executive Summary
    （executive_summary.pyが算出した本日最重要ニュース）との一致、および
    既存のcausal_rules恩恵銘柄ロジックから導ける関連セクター・関連銘柄の
    有無という既存シグナルを追加（0〜100点への配分を6シグナル分に再配分）。
    理由欄には、世界のメガトレンド評価（★・フェーズ）を文脈として明記する。
    関連セクター・関連銘柄も新たに表示する
  - Early Signal Detection: 判定条件（見出しが少ない・causal_rules該当・
    durable_themes該当・恩恵銘柄が解決できる）は変更せず、恩恵銘柄が
    解決できるという既存条件を「営業利用価値がある」ことの根拠として明記した
    うえで、関連セクター・関連銘柄という実データのみから機械的に組み立てた
    「営業で話すポイント」を追加
  - いずれも具体的な市場規模・件数以外の断定的な数値は生成しない
  - Markdown・モバイル版・HTML版すべてに反映（既存のFuture Intelligence
    Engineセクション内。他のセクション構成は変更していない）

変更ファイル
・main.py
・src/analysis/models.py
・src/analysis/future_intelligence.py
・src/report/sections.py
・src/report/mobile_builder.py
・src/report/html_builder.py
・tests/test_future_intelligence.py

pytest
111 passed

コミット
（下記参照）

## v1.10 (2026-07-04)

改善
・Future Intelligence Engine v1.3: 「テーマ成熟度メモ」「国家戦略メモ」を
  「未登録」中心の表示から、既存シグナルからのAI分析を優先表示する方式に改善
  - 表示の優先順位: ① `config.yaml` への手動登録があれば最優先で「登録情報」
    として表示 → ② 手動登録が無くても、本日の関連見出し件数・durable_themes
    該当・causal_rules該当・恩恵銘柄という既存シグナルがあれば、そこから
    導いたルールベースの定性的な「AI分析」を表示 → ③ 判断材料となる信号が
    何も無い場合のみ「分析材料不足」と表示（「未登録」だけで終わる表示を削減）
  - 国家戦略メモは、国・地域とmacro_themesの重点分野を対応付けた人手による
    参考情報（`NATIONAL_FOCUS_AREAS`。AIが生成したものではない）を追加し、
    未登録の国・地域でも本日のテーマ動向からAI分析を導けるようにした
  - いずれの表示も「登録情報」「AI分析」「分析材料不足」のラベルと判断根拠
    （どの既存シグナルから導いたか）を明記し、具体的な市場規模・補助金額・
    政策名・法案名は一切生成しない（「〜と考えられます」等の非断定表現に統一）
  - Markdown・モバイル版・HTML版すべてに反映（既存のFuture Intelligence
    Engineセクション内。他のセクション構成は変更していない）

変更ファイル
・src/analysis/models.py
・src/analysis/future_intelligence.py
・src/report/sections.py
・src/report/mobile_builder.py
・src/report/html_builder.py
・tests/test_future_intelligence.py

pytest
108 passed

コミット
（下記参照）

## v1.9 (2026-07-04)

追加
・Future Intelligence Engine v1.2: 「テーマ成熟度メモ」「国家戦略メモ」を追加
  （既存のFuture Intelligence Engineセクション内に小見出しとして追加）
  - テーマ成熟度メモ: `config.yaml` の `theme_maturity_notes`（macro_themes
    の各テーマについて、市場ステージ／市場規模メモ／普及状況メモ／
    競争環境メモ／参入障壁メモ／リスクメモを手動登録）をそのまま表示。
    AIによる市場規模・普及率等の生成・推定は一切行わない
  - 国家戦略メモ: `config.yaml` の `national_strategy_notes`（日本／米国／
    中国／EU／インド／中東の6地域固定で、重点分野・政策メモ・規制メモ・
    市場影響メモを手動登録）をそのまま表示。AIによる補助金額・政策内容の
    生成・推定は一切行わない
  - いずれも未登録のテーマ・国・項目は「未登録」と明記する
  - `config.yaml` には空の `theme_maturity_notes: {}` / `national_strategy_notes: {}`
    と、コメントアウトされた記入例のみを追加（デフォルトはすべて「未登録」）

変更ファイル
・config.yaml
・src/analysis/models.py
・src/analysis/future_intelligence.py
・src/report/sections.py
・src/report/mobile_builder.py
・src/report/html_builder.py
・tests/test_future_intelligence.py

pytest
105 passed

コミット
（下記参照）

## v1.8 (2026-07-04)

追加
・Future Intelligence Engine v1.1: Theme Momentum Score と Early Signal
  Detection を追加（既存のFuture Intelligence Engineセクション内に小見出しとして追加）
  - Theme Momentum Score: 各macro_themeについて、本日の関連見出し密度・
    本日の重要ニュース（news_ranking）との一致・causal_rules該当・
    durable_themes該当という既存シグナルのみから0〜100の定性スコアを算出。
    前日比・週次比較は行わない（履歴データを保持していないため）。
    急加速／加速／横ばい／減速の4段階ラベルと理由を付与
  - Early Signal Detection: 本日の見出し件数はまだ少ない（1件以下）ものの、
    causal_rules該当・durable_themes該当・恩恵銘柄が解決できる、という
    条件をすべて満たすテーマを「初動シグナル」として抽出（★・理由・
    関連セクター・代表的な関連銘柄を表示）
・詳細版・モバイル版・HTML版すべてに反映（既存のFuture Intelligence Engine
  セクション内。他のセクション構成は変更していない）

変更ファイル
・src/analysis/models.py
・src/analysis/future_intelligence.py
・main.py
・src/report/sections.py
・src/report/mobile_builder.py
・src/report/html_builder.py
・tests/test_future_intelligence.py

pytest
101 passed

コミット
（下記参照）

## v1.7 (2026-07-04)

追加
・Future Intelligence Engine v1.0（グループAのみ）を新設。世界の長期テーマ
  （config.yaml `macro_themes`。AI/半導体/電力/GX/DX/防衛/宇宙/量子/核融合/
  ロボット/医療/バイオ/サイバーセキュリティ/水インフラ/物流/資源/食料/
  人口減少/高齢化/自動運転の20テーマ）を、既存の
  `durable_themes`・`causal_rules`・本日の関連見出し件数・恩恵銘柄ロジックの
  みから定性的に評価する新モジュール `src/analysis/future_intelligence.py`
  - 世界のメガトレンド（★・フェーズ［黎明期/成長初期/急成長期/成熟期/減速期］・
    継続性［高い/中程度/限定的］・なぜ伸びるか）
  - 次に来る業界ランキング（本日のモメンタム順）
  - サプライチェーン分析（causal_rulesの因果チェーンを再利用）
  - 中長期テーマ（半年/1年/3年/5年/10年への定性的な割り付け）
  - 日本株への波及（恩恵銘柄。大型/中小型は区分不明として明記）
  - Future Map（テーマ一覧）
  - 詳細版・モバイル版・HTML版すべてに「Future Intelligence Engine」として
    1セクションにまとめて追加（既存セクション番号は変更せず末尾に追加）
・具体的な残り年数・市場規模・補助金額等は一切生成しない（実データの裏付けが
  ない数値は使わない方針を徹底）。テーマ成熟度・国家戦略分析・世界のお金の
  流れはv1.1以降に見送り（設計提案書のグループB/Cに該当）

変更ファイル
・config.yaml
・main.py
・src/analysis/models.py
・src/analysis/future_intelligence.py【新規】
・src/report/builder.py
・src/report/sections.py
・src/report/mobile_builder.py
・src/report/html_builder.py
・tests/test_future_intelligence.py【新規】
・tests/test_report_builder.py
・tests/test_mobile_builder.py
・tests/test_html_builder.py

pytest
97 passed

コミット
（下記参照）

## v1.6 (2026-07-04)

改善
・HTML上部の「最新情報に更新」ボタンの仕様を変更。GitHub Actionsの
  workflow_dispatch実行ページへ遷移する方式から、`javascript:location.reload()`
  によるページ再読み込みのみのボタン（「🔄 最新表示に更新」）へ変更。
  外部JS不要・常時表示（`actions_url`の有無に依存しない）
・毎朝の自動生成・自動デプロイを基本運用とし、手動でのワークフロー実行は
  README上で補足的な案内に位置づけ直した

修正
・（なし）

判断: `config.yaml` の `output.actions_url` と `main.py` の
`_resolve_actions_url()` は削除せず残した。html_builder.py側では
未使用になったが、main.pyからbuild_html_reportへの`actions_url`引数は
削除するとmain.py・config.yamlの2ファイルに追加の変更が必要になり、
現時点で機能上のメリットがない削除のために変更範囲を広げるのは
「最小差分」の方針に反すると判断したため。将来この設定を使う機能
（例: 別ボタンでのActions画面誘導を復活させる等）を追加する際に
そのまま再利用できる。

変更ファイル
・src/report/html_builder.py
・tests/test_html_builder.py
・README.md

pytest
90 passed

コミット
（下記参照）

## v1.5 (2026-07-04)

修正
・`deploy-pages` ジョブの `actions/deploy-pages@v4` ステップから
  `timeout: 1200000 / error_count: 10 / reporting_interval: 10000` の指定を削除。
  `timeout` の許容上限（60000ミリ秒）を超えていたため警告が出ており、
  デプロイ失敗（`エラー：展開に失敗しました。後で再挑戦してください。`）と
  合わせて発生していた。既定動作（アクション側のデフォルト設定）に戻すことで解消
・`generate-report` ジョブ、`deploy-pages` ジョブの `timeout-minutes: 20`、
  GitHub Pages の Source/Environment 設定は変更していない

変更ファイル
・.github/workflows/daily-market-brief.yml

pytest
91 passed

コミット
（下記参照）

## v1.4 (2026-07-04)

修正
・`build_html_report()` に `actions_url` キーワード引数が定義されておらず、
  GitHub Actions実行時に `got an unexpected keyword argument 'actions_url'`
  という警告が出ていた不整合を修正。`actions_url: Optional[str] = None` を
  明示的に追加し、`main.py` からの呼び出しと整合させた
・`actions_url` が `None`（または空文字）の場合は「最新情報に更新」ボタンを
  表示しない挙動を維持（既存ロジックのまま、型ヒントのみ明確化）

変更ファイル
・src/report/html_builder.py
・tests/test_html_builder.py

pytest
91 passed

コミット
（下記参照）

## v1.3 (2026-07-04)

追加
・HTMLレポート（Today's Dashboardのすぐ下）に「🔄 最新情報に更新」ボタンを追加。
  押すとGitHub Actions「Daily Market Brief」ワークフローの実行ページへ遷移し、
  そこで「Run workflow」を押せば最新ニュース・最新データでレポートを再生成できる
・`config.yaml` の `output.actions_url`（環境変数 `ACTIONS_URL` でも上書き可）で
  ボタンのリンク先を明示できるように設定を追加。未設定時は
  `GITHUB_REPOSITORY` から自動組み立て、どちらも無ければボタン自体を非表示

変更ファイル
・main.py
・src/report/html_builder.py
・config.yaml
・tests/test_html_builder.py
・README.md

pytest
90 passed

コミット
（下記参照）

## v1.2 (2026-07-04)

改善
・`CLAUDE.md` に「設計原則」（ディレクトリ構成／システム設計／ファイル名／
  設定ファイル構成／ワークフロー／GitHub Actions・Pages／ニュース評価ロジック／
  スコアリングロジック／営業思想／ストラテジスト思想／UIデザイン／出力フォーマット
  はChatGPT（監督者）が決定し、Claude Codeは提案のみ行う）を追加
・「リファクタリング」ルール（依頼のない限りリネーム・ファイル移動・関数統合・
  大規模整理・不要コード削除を禁止）を追加

変更ファイル
・CLAUDE.md

pytest
89 passed（コード変更なし。既存スイートに影響なし）

コミット
（下記参照）

## v1.1 (2026-07-04)

改善
・`CLAUDE.md` を、ユーザー提示の15項目「更新ポリシー」を最上位ルールとして
  明記する形に更新（リポジトリ全体を書き換えない／変更ファイルのみ提出／
  ZIPは依頼時のみ／フォルダ構成・Git構成・GitHub Pages/Actions/Secretsは
  依頼がない限り変更しない、等）

変更ファイル
・CLAUDE.md

pytest
（コード変更なしのため実行対象なし。既存89件のスイートに影響なし）

コミット
（下記参照）

## v1.0 (2026-07-04)

追加
・岡三証券の内部ストラテジストレポート（「グローバル投資の羅針盤」5号分）から
  学習した「ニュース評価・投資アイデア変換」の思考プロセスを一般化し、
  `src/analysis/strategist_engine.py` として実装
・8軸★スコアリング（市場インパクト／継続性／営業利用価値／日本株影響度／
  米国株影響度／個別株へ展開できるか／テーマ株へ展開できるか／今後数週間重要か）
・「ニュース→岡三ストラテジストならどう見るか→重要テーマ→関連セクター→
  恩恵銘柄→悪影響銘柄→営業で話すポイント→重要度」パイプラインと、
  レポート新セクション「岡三ストラテジスト視点」（詳細版・モバイル版・HTML版）
・`config.yaml` に `causal_rules`（因果チェーンルール）・`durable_themes`
  （継続性の高いテーマ一覧）を追加

改善
・`news_ranking.py` の重要度スコアに、因果チェーン該当・継続性の高いテーマ
  該当の加点を追加（既存スコアリングへの後方互換は維持）
・`executive_summary.py` に恩恵銘柄／悪影響銘柄／ストラテジスト視点の
  一言まとめを追加

変更ファイル
・config.yaml
・main.py
・src/analysis/executive_summary.py
・src/analysis/models.py
・src/analysis/news_ranking.py
・src/analysis/strategist_engine.py【新規】
・src/report/builder.py
・src/report/html_builder.py
・src/report/mobile_builder.py
・src/report/sections.py
・tests/test_mobile_builder.py
・tests/test_report_builder.py
・tests/test_strategist_engine.py【新規】
・README.md
・CLAUDE.md【新規】
・CHANGELOG.md【新規】

pytest
89 passed

コミット
6834f70
