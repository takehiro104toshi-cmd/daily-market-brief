# CHANGELOG

このファイルは `CLAUDE.md` の運用プロトコルに従い、`## vX.Y` 形式で
「追加／改善／修正」を追記していく。本ファイルの記録は今回の更新から開始する
（それ以前の機能一覧・構成は `README.md` を参照）。

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
