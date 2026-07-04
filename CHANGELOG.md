# CHANGELOG

このファイルは `CLAUDE.md` の運用プロトコルに従い、`## vX.Y` 形式で
「追加／改善／修正」を追記していく。本ファイルの記録は今回の更新から開始する
（それ以前の機能一覧・構成は `README.md` を参照）。

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
