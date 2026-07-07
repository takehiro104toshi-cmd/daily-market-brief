# daily-market-brief

毎朝、公開情報のみを収集し、「なぜそうなっているか」までAIが考察した
朝の戦略レポート（Morning Strategy Report / Market Intelligence System v4）を
Markdownで自動生成するツールです。
**投資助言ではなく、情報整理・考察補助のためのツールです。**

> このリポジトリは市場レポート専用の独立プロジェクトです。他プロジェクトとは
> 完全に分離されており、`daily-market-brief` の内容のみで構成されています。

単なるニュースの並び替えではなく、米国株→金利→為替→日本株→業界→個別株
という因果関係の整理、相場シナリオの確率提示、テーマ・業界・個別株の
ランキングと先行き予測、長期投資候補の選定などを行います。

## 「AI分析」の仕組み（重要）

本ツールが生成する「AI分析」「AI考察」は、次の2段構成です。

1. **ルールベースの機械的分析エンジン（常時有効・追加設定不要）**
   `src/analysis/` 配下の各モジュールが、実データ（前日比・VIX水準・
   ニュース件数など）から透明な数式・テンプレートで考察文を生成します。
   外部APIも追加費用も不要で、この層だけで全30セクションが完成します。
2. **Claude APIによる文章の磨き上げ（任意・オプション）**
   環境変数 `ANTHROPIC_API_KEY` を設定し、`pip install anthropic` すると、
   上記のたたき台を「事実の範囲内でのみ」Claudeが自然な文章に磨き上げます。
   未設定時・API障害時は自動的にルールベースの文言にフォールバックするため、
   これが無くてもツールは完全に動作します。

いずれの場合も、断定的な投資助言（「買うべき」等）は生成しません。
「〜の可能性があります」「〜が意識されやすい状況です」といった仮説的な
表現を用い、事実（実データ）とAI分析（考察）を常に区別して表示します。

### Claude API連携を有効にする場合（任意）

```bash
pip install anthropic
export ANTHROPIC_API_KEY="sk-ant-..."   # ご自身のAnthropicアカウントのAPIキー
python3 main.py
```

GitHub Actionsで使う場合は、リポジトリの Settings → Secrets and variables →
Actions に `ANTHROPIC_API_KEY` を登録し、ワークフローの `env:` に追加してください
（デフォルトのワークフローには含まれていません。追加する場合のみ設定してください）。
利用するモデルは環境変数 `MARKET_BRIEF_LLM_MODEL`（デフォルト: `claude-sonnet-5`）
で変更できます。

## できること

- 主要指数（日経平均、NYダウ、S&P500、ナスダック、SOX、VIX など）・為替・米10年金利・
  原油・金・ビットコイン
- 日経・ロイター・Bloomberg・CNBC・WSJ・MarketWatch・Investing.com・NHK・Yahoo!ニュース
  など公開RSSのニュース見出し、日銀・財務省の新着情報（本文は取得しません）
- TDnet（適時開示情報閲覧サービス）・EDINET（金融庁の公開書類一覧API）
- ウォッチリスト銘柄（日本株・米国株）の決算発表予定
- AI Executive Summary（レポート冒頭・今日最重要ニュース最大3件。結論・理由・日本株への
  影響・ドル円への影響・金利への影響・営業トークを1件ずつ整理）
- 今日の注目5銘柄（日本株5銘柄・米国株5銘柄、コード・企業名・理由・注目材料・短期見通し）
- 今日の相場シナリオ（強気／中立／弱気それぞれの確率・理由・注目指標の3本立て）に加え、
  日経平均・ドル円・米国市場それぞれの強気／中立／弱気シナリオ（AIシナリオ）
- ニュースの重要度ランキング（理由・影響市場・影響業種・営業トークつき、最重要ニュースを1位に固定）
- マーケットインパクト（日経平均・TOPIX・ドル円・長期金利・半導体・銀行・商社・自動車・
  海運・電力・素材・不動産の12対象について、影響度★とプラス/マイナス/中立を一覧表示）
- セクターランキング（本日「強そう／弱そう」をAIが↑/→/↓と理由付きで予測）
- 今日電話すべき顧客（富裕層・NISA・退職金・法人・相続・若年層の6顧客タイプ別に、
  理由・話題・営業トーク例を提案）
- 朝会コメント（30秒・1分・3分の3パターン、そのまま読み上げられる自然な日本語）
- 米国株→金利→為替→日本株→業界→個別株の因果関係を矢印で整理（マクロの大きな流れ1本＋
  個別の短い因果チェーン3〜5本）
- 今日見るべき指標（為替・VIX・米10年・WTI・Gold の現在値・節目ライン・超えたら何が起きやすいか）
- 注目テーマ・注目業界・個別株のランキングと短中期・長期の見立て
- 今日のウォッチリスト（監視銘柄を★評価＋1行理由でさっと確認）
- 保有・監視銘柄の毎朝分析（今日／1週間／1か月／長期／リスク）
- AIが選ぶ長期投資アイデアTOP5
- 営業準備（社長向け一言・富裕層向け話題・初心者向け用語解説・今日の雑談・想定質問Q&A）
- 営業トーク（法人社長向け／個人投資家向け／初心者向け／富裕層向け）
- 営業向けコメント（7オーディエンス別・各約30秒で話せる長さ）と、想定質問と回答例（拡張Q&A）
- 岡三証券営業向けコメント（富裕層・法人・NISA・退職金・相続の5顧客タイプ別、
  各約30秒で話せる長さ。セクション見出しの文字列を書き換えれば任意の支店・チーム名に変更可能）
- 今日の会話ネタ、イベント（今日／今週／今月）、300字以内のAIまとめ
- 収集したすべてのデータについて、出典URLをレポート末尾に記録（情報源別の信頼度スコアに
  もとづき、同一ニュースの重複は自動的に除去されます）
- スマホでもPCを開かず読めるよう、詳細版に「今日の5分要約」ダイジェストを追加し、
  短縮版Markdown（`mobile_market_brief.md`）と、色分けカードUIのHTML版も生成
- HTML版はGitHub Pagesにも自動デプロイされ、URLをブックマークするだけで
  リポジトリを開かずスマホから直接閲覧できます（要・初回設定、詳細は後述）
- 生成後、メール（SMTP）とLINE（Messaging API）へ「今日の結論・重要ニュース3件・
  GitHub Pages URL」を自動通知（両方とも任意設定、未設定でもレポート生成は失敗しません）

出力は `output/YYYY-MM-DD_market_brief.md`（詳細版Markdown）に保存され、同時に同じ内容が
`output/latest_market_brief.md` にも上書き保存されます。スマホ閲覧向けの短縮版
`output/mobile_market_brief.md` と、カードUIのHTML版
（`output/YYYY-MM-DD_market_brief.html` / `output/latest_market_brief.html`）も
毎回あわせて生成されます。

## レポートの構成（Market Intelligence System v4）

冒頭に「📱 今日の5分要約」（今日の結論・重要ニュース3件・注目テーマ3つ・見るべき指数・
営業一言を200〜300文字程度に凝縮）を表示したのち、以下30セクションが続きます。

1. AI Executive Summary（AI分析・今日最重要ニュース最大3件。結論／理由／日本株への影響／
   ドル円への影響／金利への影響／恩恵銘柄／悪影響銘柄／営業トークを1件ずつ表示）★★★★★
2. 岡三ストラテジスト視点（AI分析・「ニュース→岡三ストラテジストならどう見るか→重要テーマ→
   関連セクター→恩恵銘柄→悪影響銘柄→営業で話すポイント→重要度」の順で整理。下記の
   「岡三ストラテジスト視点機能について」を参照）
3. 今日の結論（3行・太字）★★★★★
4. 今日の注目5銘柄（AI分析・日本株5銘柄・米国株5銘柄、コード／企業名／理由／注目材料／短期見通し）
5. 主要指標（事実）
6. 為替・金利（事実）
7. 今日の相場シナリオ（AI分析・強気／中立／弱気それぞれの確率・理由・注目指標）★★★★★
8. 日経平均・ドル円・米国市場 個別シナリオ（AIシナリオ・指標ごとの強気／中立／弱気3シナリオ）
9. 今日の重要ニュースランキング（AI分析・理由／影響市場／影響業種／営業トークつき）
10. マーケットインパクト（AI分析・日経平均／TOPIX／ドル円／長期金利／半導体／銀行／商社／
    自動車／海運／電力／素材／不動産の12対象への影響度★・プラス/マイナス/中立の判定一覧）
11. セクターランキング（AI分析・本日「強そう／弱そう」の予測を↑/→/↓と理由で表示）
12. 今日見るべき指標（為替・VIX・米10年・WTI・Gold の節目ラインと一言コメント）
13. マーケット分析（AI分析・因果関係を矢印↓で整理／個別の因果チェーン3〜5本）
14. テーマ分析（AI分析・ランキング形式、今後1週間／1か月／3か月の見立て）
15. 業界ランキング TOP10（AI分析・追い風／逆風／関連銘柄／営業トーク）
16. 個別株ランキング（AI分析・日本株TOP10／米国株TOP10、短期／中期／長期）
17. 今日のウォッチリスト（★評価＋1行理由の一覧）
18. 保有・監視銘柄分析（AI分析・全銘柄について今日／1週間／1か月／長期／リスク）
19. 長期投資アイデア TOP5（AI分析）
20. 今日電話すべき顧客（AI分析・富裕層／NISA／退職金／法人／相続／若年層の6顧客タイプ別、
    理由／話題／営業トーク例）
21. 営業準備（社長向け一言・富裕層向け話題・初心者向け用語解説・今日の雑談・想定質問）
22. 営業トーク（法人社長向け／個人投資家向け／初心者向け／富裕層向け）
23. 営業向けコメント（AI分析・法人社長／富裕層／個人投資家／NISA初心者／為替関心／
    米国株関心／日本株関心の7オーディエンス別、各約30秒で話せる長さ）
24. 想定質問と回答例（AI分析・日経平均／円安／NVIDIA／注目業種／NISAの5問を含む拡張Q&A）
25. 岡三証券営業向けコメント（AI分析・富裕層／法人／NISA／退職金／相続の5顧客タイプ別、
    各約30秒で話せる長さ。セクション名は例であり、`sections.render_okasan_sales_comments`
    と `builder.py` の見出し文字列を書き換えれば任意の支店・チーム名に変更できます）
26. 朝会コメント（AI分析・30秒／1分／3分の3パターン、朝会でそのまま読み上げられる自然な文章）
27. 今日の会話ネタ（AI分析・3つ）
28. イベント（事実・今日／今週／今月）
29. AIまとめ（AI分析・300文字以内の戦略サマリー）
30. 引用（事実・参照URL一覧）

- 見出し・銘柄には重要度・変化率に応じた★評価を表示します。
- データを取得できなかった項目は空欄にせず「取得不可」と明記し、
  30セクションの構成自体は常に維持されます（一部データが欠けてもレポートは崩れません）。
- 「事実」ラベルは実データ、「AI分析」ラベルはルールベースの機械的考察（Claude磨き上げ含む）
  であることを、レポート冒頭の凡例と各項目で明示しています。
- ③のシナリオ理由と④の因果チェーンは、断定表現を避け「〜の可能性があります」
  「〜と考えられます」で統一しています。

### 岡三ストラテジスト視点機能について

「今日の重要ニュースランキング」の重要度判定と「②岡三ストラテジスト視点」セクションは、
岡三証券 投資戦略部のストラテジストレポート（社内資料）を教材として学習した
「ニュースの評価の仕方・投資アイデアへの変換の仕方」の思考プロセスを、
**一般化したルールベースのロジックとして再現したもの**です。
特定資料の文章を引用・要約したものではなく、資料から読み取った考え方の
「型」（例: 商品価格の変動→川上／川下セクターへの波及→関連銘柄、という
因果連鎖のパターン）を `config.yaml` の `causal_rules` / `durable_themes` に
汎用的なルールとして定義し、公開ニュース見出しに機械的に適用しています。

- **8軸★スコアリング**（`src/analysis/strategist_engine.py`）: ①市場インパクト
  ②継続性 ③営業利用価値 ④日本株影響度 ⑤米国株影響度 ⑥個別株へ展開できるか
  ⑦テーマ株へ展開できるか ⑧今後数週間重要か、の8項目を各1〜5で評価し、
  平均から総合★（1〜5）を算出します。すべて公開見出しの字面とconfig.yamlの
  設定から機械的に導く決定論的なロジックであり、生成AIによる判定ではありません。
- **処理パイプライン**: 各ニュースを「ニュース → 岡三ストラテジストならどう見るか
  →重要テーマ→関連セクター→恩恵銘柄→悪影響銘柄→営業で話すポイント→重要度」の
  順で整理します。恩恵銘柄・悪影響銘柄は `causal_rules` で定義したセクター単位の
  波及関係から、ウォッチリスト銘柄（config.yamlのwatchlist）を解決して表示します。
- **causal_rules の追加・調整方法**: `config.yaml` の `causal_rules:` に
  `trigger_keywords`（発動キーワード）／`theme`／`beneficiary_sectors`（追い風業種）／
  `negative_sectors`（逆風業種）／`durable`（継続性の高いテーマかどうか）／`note`
  （一言解説）を追加すれば、新しい因果チェーンのパターンを増やせます。
- 断定的な投資助言ではなく、あくまで情報整理・話材準備のための考察です
  （「〜の可能性があります」等の非断定的な表現で統一）。

### スマホ向けの読みやすさの工夫（詳細版）

- 冒頭に **「📱 今日の5分要約」** ダイジェストを追加。今日の結論・重要ニュース3件・
  注目テーマ3つ・見るべき指数・営業一言だけを200〜300文字程度に凝縮して表示し、
  詳細を読むかはそのあとで判断できるようにしています。
- 各セクションの間に `---` の区切り線を入れ、スマホで縦スクロールしても
  セクションの切れ目が分かりやすいようにしています。
- 見出しは短く、指標テーブルは列数を絞り（名称／値／前日比／★／出典）、
  出典欄も🔗リンクのみにして横幅が広がりすぎないようにしています。

### mobile_market_brief.md（短縮版Markdown）の構成

詳細版とは別に、スマホで5分以内に読み切れることを目的とした短縮版を生成します。

1. 今日の結論（3行）
2. 岡三ストラテジスト視点（重要ニュース上位2件を、ストラテジスト視点・恩恵／悪影響銘柄で凝縮）
3. 今日の相場シナリオ（強気／中立／弱気の割合と理由）
4. 注目テーマ TOP3（各テーマ3行以内）
5. 注目業界 TOP3（各業界3行以内）
6. 監視銘柄チェック（日本株5銘柄・米国株5銘柄まで、各2行以内）
7. 今日の営業トーク（法人社長向け・個人投資家向け・初心者向けを各1つ）
8. 今日の最重要ポイント（1文）

### HTML版（カードUI・色分け表示）

`output/YYYY-MM-DD_market_brief.html` と `output/latest_market_brief.html` は、
詳細版と同じ内容をスマホ閲覧前提のカードUIで表示するHTML版です。

- 外部CSS・外部JSに依存しない自己完結型の1ファイル（`<style>` をHTML内に埋め込み）。
  GitHub上のプレビューではなく、ダウンロードしてブラウザで開く、または
  GitHub Pages等で配信することを想定しています。
- **Today's Dashboard**（HTML最上部のカードグリッド）: 重要ニュース3件と、
  ドル円・日経平均・NYダウ・NASDAQ・SOX・VIX・米10年債・WTI・金・ビットコインの
  10指標を、開いた瞬間に一覧できるダークテーマのカードで表示します。
- 前日比に応じて **上昇＝緑／下落＝赤／横ばい・データなし＝灰色** のバッジで色分け。
- `viewport` メタタグ設定済みで、スマホ幅でも横スクロールなしで閲覧できます
  （テーブルは `table-layout: fixed` と `word-break` で固定幅にし、横スクロールが発生しません）。
- ページ最上部（5分要約の直後）に**目次カード**を表示し、各セクションへワンタップで
  ジャンプできます（アンカーリンク）。閲覧時に毎回全文をスクロールする必要がなく、
  朝会前に必要なセクションだけをすぐ開けます。
- 最終更新時刻（生成日時）をヘッダーに表示します。
- Markdown版と同じ `AnalysisBundle`（収集済みデータ＋AI分析結果）をそのまま
  再利用しており、HTML側で新たな考察ロジックは持ちません（見せ方だけが異なります）。

## 使用データについての方針

- 使用するのは無料で誰でも閲覧できる公開情報のみです。
- 社外秘資料、有料記事の本文、ログインが必要なサービスのデータは使用しません。
  ニュースはRSSの見出し・リンクのみを扱い、本文はスクレイピングしません。
- 各項目には取得元のURLを記録し、レポート末尾の「引用（参照URL一覧）」にまとめます。
- 「AI分析」は断定的な投資助言ではなく仮説的な考察です。「営業トーク」「営業向けコメント」
  「今日の会話ネタ」も事実紹介の話材にとどめており、投資判断や勧誘目的では使用しないでください。
- 事実とAI分析は常に区別して表示されます（禁止事項の遵守）。

### 情報源一覧

| 情報源 | 用途 | 取得方式・注意点 |
| --- | --- | --- |
| Yahoo!ニュース（経済・トピックス） | ニュース見出し | 公開RSS。動作確認済み。 |
| NHKニュース（経済・総合） | ニュース見出し | 公開RSS。動作確認済み。 |
| 日本経済新聞 電子版 | ニュース見出し | 公開見出しRSS相当への**ベストエフォート**接続（`src/collectors/nikkei.py`）。本文は取得しません。 |
| Bloomberg | ニュース見出し | 公開見出しRSS相当への**ベストエフォート**接続（`src/collectors/bloomberg.py`）。本文は取得しません。 |
| Reuters | ニュース見出し | 公開見出しRSS相当への**ベストエフォート**接続（`src/collectors/reuters.py`）。Yahoo!ニュース経由のロイター配信は動作確認済み。 |
| CNBC | ニュース見出し | 公開見出しRSS相当への**ベストエフォート**接続（`src/collectors/cnbc.py`）。本文は取得しません。 |
| WSJ（The Wall Street Journal） | ニュース見出し | 公開見出しRSS相当への**ベストエフォート**接続（`src/collectors/wsj.py`）。有料記事本文は取得しません。 |
| MarketWatch | ニュース見出し | 公開見出しRSS相当への**ベストエフォート**接続（`src/collectors/marketwatch.py`）。本文は取得しません。 |
| Investing.com | ニュース見出し | 公開見出しRSS相当への**ベストエフォート**接続（`src/collectors/investing.py`）。Bot対策等で不安定な場合があります。 |
| 日本銀行（BOJ） | 新着情報（金融政策関連の公表） | 公開RSS（`https://www.boj.or.jp/rss/whatsnew.rdf`、`src/collectors/boj.py`）。 |
| 財務省（MOF） | 新着情報（為替・財政関連の公表） | 公開RSS（`https://www.mof.go.jp/rss/whatsnew.rdf`、`src/collectors/mof.py`）。 |
| TDnet（適時開示情報閲覧サービス） | 適時開示一覧 | 公開一覧ページ（ログイン不要）。動作確認済み。 |
| EDINET（金融庁 電子開示システム） | 有価証券報告書等の書類一覧 | 公開API（`https://disclosure.edinet-fsa.go.jp/api/v2/documents.json`）。`EDINET_API_KEY`（任意）に対応。 |
| Yahoo Finance（yfinance） | 指数・為替・金利・コモディティ・個別株 | 公開データ。動作確認済み。 |
| Stooq | 上記のフォールバック | yfinance取得失敗時の公開CSVフォールバック。 |
| FRED（Federal Reserve Economic Data） | マクロ指標（米10年-2年金利差・米失業率） | APIキー不要の公開CSVエンドポイント（`src/collectors/macro.py`）。 |
| Trading Economics | マクロ指標カレンダー | 公式サイトのURLを**参照リンクとしてのみ**登録（自動取得は行いません）。 |
| JPX（日本取引所グループ） | 市場統計・開示データ | 公式サイトのURLを**参照リンクとしてのみ**登録（自動取得は行いません）。 |
| 株探（Kabutan） | 個別銘柄情報 | 公式サイトのURLを**参照リンクとしてのみ**登録（自動取得は行いません）。 |
| MINKABU | 個別銘柄情報 | 公式サイトのURLを**参照リンクとしてのみ**登録（自動取得は行いません）。 |
| moomoo証券 | 個別銘柄情報 | 公式サイトのURLを**参照リンクとしてのみ**登録（自動取得は行いません）。 |
| SBI証券 | 証券会社公式情報 | 公式サイトのURLを**参照リンクとしてのみ**登録（自動取得は行いません）。 |
| 楽天証券 | 証券会社公式情報 | 公式サイトのURLを**参照リンクとしてのみ**登録（自動取得は行いません）。 |

**「ベストエフォート」について（重要）:** 日経・Bloomberg・Reuters・CNBC・WSJ・
MarketWatch・Investing.comの直接RSSは、この開発環境（サンドボックス、外部ネットワーク
遮断）では実際の接続確認ができていません。各社は公開RSSの提供方針を変更することがあるため、
本番運用前に一度 `python3 main.py` を実行し、ログにこれらの取得失敗
（`[WARNING] 取得失敗: ...`）が出ていないか確認してください。失敗していてもレポート生成
自体は継続され、該当ニュースが取得できないだけです（該当箇所は他の情報源の見出しで
補われるか、件数が減るだけで、レポート構成は崩れません）。日銀・財務省のRSSは公式に
文書化されたエンドポイント形式ですが、同様にこの環境では接続確認ができていないため、
本番運用前の確認を推奨します。

**「参照リンクのみ」について:** 株探・moomoo証券・JPX・Trading Economics・MINKABU・
SBI証券・楽天証券は、確認済みの公開RSS/APIが存在しない、または利用規約への配慮が必要な
ため、自動取得（スクレイピング）は行わず、公式サイトのURLを出典一覧（24. 引用）に
掲載するのみとしています。これらの情報源由来の見出し・本文がレポートに引用されることは
ありません。

## セットアップ

```bash
git clone https://github.com/takehiro104toshi-cmd/daily-market-brief.git
cd daily-market-brief
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
```

## 初回実行チェックリスト

実運用（毎朝の自動実行）に入る前に、ローカルで一度以下を順番に確認してください。

- [ ] **Pythonバージョン確認**

  ```bash
  python3 --version
  ```

  Python 3.9以上であることを確認してください（本プロジェクトは3.11で動作確認済み）。

- [ ] **仮想環境の作成**

  ```bash
  python3 -m venv .venv
  source .venv/bin/activate   # Windowsは .venv\Scripts\activate
  ```

- [ ] **依存パッケージのインストール**

  ```bash
  pip install -r requirements.txt
  ```

  エラーなく完了することを確認してください。

- [ ] **`python main.py` の実行**

  ```bash
  python3 main.py
  ```

  `[WARNING]` ログが出ても処理は継続します（個別の情報源への接続失敗であり、
  想定内の挙動です）。最後に `[INFO] レポートを保存しました: ...` が
  表示されればレポート生成は成功です。

- [ ] **output生成の確認**

  ```bash
  ls -la output/
  ```

  `YYYY-MM-DD_market_brief.md` / `latest_market_brief.md`（詳細版Markdown）、
  `mobile_market_brief.md`（短縮版Markdown）、
  `YYYY-MM-DD_market_brief.html` / `latest_market_brief.html`（HTML版）の
  5つが生成されていることを確認してください。詳細版は30セクションすべてが存在し、
  データ欠損箇所は空欄ではなく「取得不可」と表示されていること、短縮版は8セクション
  構成になっていること、HTML版はブラウザで開いてカードUIが崩れずに表示されることを
  確認してください。

- [ ] **GitHub Actions有効化の確認**

  1. GitHubリポジトリの「Actions」タブを開き、「Daily Market Brief」ワークフローが
     一覧に表示されていることを確認する。
  2. Settings → Actions → General → "Workflow permissions" が
     **Read and write permissions** になっていることを確認する
     （自動コミット・プッシュに必要）。
  3. 「Daily Market Brief」→「Run workflow」から手動実行し、正常終了することを確認する。
  4. 実行後、`output/` に新しいレポートがコミットされていることを確認する。

すべてにチェックが付けば、実運用（毎朝7:00 JSTの自動実行）を開始できます。

## 実運用での起動方法

### 1. ローカルで手動実行する

```bash
source .venv/bin/activate   # まだ作っていない場合は「セットアップ」を参照
python3 main.py
```

- 必ずリポジトリのルートディレクトリ（`config.yaml` と同じ場所）から実行してください。
  別ディレクトリから実行すると `config.yaml` が見つからずエラーになります。
- 実行ログが標準出力に表示されます。`[WARNING]` は個別の情報源取得に失敗した
  ことを示しますが、処理自体は継続し、最終的にレポートは必ず生成されます。
- 実行が終わると、コンソールに次のような行が出力されます。

  ```
  [INFO] レポートを保存しました: /path/to/daily-market-brief/output/2026-07-01_market_brief.md
  [INFO] 最新レポートを保存しました: /path/to/daily-market-brief/output/latest_market_brief.md
  ```

  このパスが実際に生成されたレポートの場所です。実行のたびに、日付入りのファイルと
  同じ内容の `output/latest_market_brief.md` も上書き生成されるため、日付を気にせず
  常に最新版を確認したい場合はこちらを開いてください。

- レポートの対象日付を指定して生成したい場合は `--date` オプションを使います
  （例: 過去の日付でファイル名だけ揃えて再生成したい場合など）。

  ```bash
  python3 main.py --date 2026-07-01
  ```

  `output/2026-07-01_market_brief.md` として保存されます。
  ※ `--date` はレポートのタイトル・ファイル名に使う日付のみを変更します。
  市場データやニュースは実行した時点の最新情報を取得するため、
  過去日のデータを遡って取得するものではない点にご注意ください。

- 手元で毎朝自動実行したい場合は、cronに登録します（Linux/Mac）。

  ```
  0 7 * * * cd /path/to/daily-market-brief && /path/to/.venv/bin/python main.py >> cron.log 2>&1
  ```

  Windowsの場合はタスクスケジューラで「毎日 7:00」に
  `python main.py`（作業ディレクトリ: リポジトリのルート）を実行するタスクを登録してください。

### 2. GitHub Actionsで毎朝7:00(JST)に自動実行する

リポジトリには `.github/workflows/daily-market-brief.yml` が用意されており、
GitHub上で以下のように動作します。

- **スケジュール:** `cron: "0 22 * * *"`（UTC 22:00 = JST 7:00）に自動実行
- **手動実行:** GitHubの「Actions」タブ → 「Daily Market Brief」→
  「Run workflow」から任意のタイミングで手動実行も可能
- **処理内容:** `pip install -r requirements.txt` → `python main.py` を実行し、
  生成された `output/*.md` / `output/*.html` を自動でコミット・プッシュした上で、
  `latest_market_brief.html` をGitHub Pagesへデプロイ

有効化の確認ポイント:

- ワークフローはリポジトリにpushされていれば自動的に有効です（追加設定は不要）。
- コミット・プッシュを行うため、リポジトリの Settings → Actions → General →
  "Workflow permissions" が **Read and write permissions** になっている必要があります。
  デフォルトでReadのみの場合は変更してください。
- GitHub Pagesへのデプロイには、別途 Settings → Pages の設定が必要です
  （詳細は後述の「5. GitHub Pagesで見る」を参照）。
- 実行結果は GitHub の Actions タブから確認できます。失敗した場合もログに
  原因（どの情報源に接続できなかったか等）が出力されます。

### 3. 生成された output ファイルの確認方法

- 保存先: `output/YYYY-MM-DD_market_brief.md`
  （例: 2026年7月1日分なら `output/2026-07-01_market_brief.md`）
- 実行のたびに `output/latest_market_brief.md` も同じ内容で上書き
  生成されるため、日付を調べなくても常にこのファイルを見れば最新レポートを確認できます。
- ローカル実行の場合は、実行直後にそのままエディタや `cat` で開けます。

  ```bash
  cat output/latest_market_brief.md
  # または日付を指定して
  cat output/$(date +%Y-%m-%d)_market_brief.md
  ```

- GitHub Actions経由の場合は、mainブランチ（またはワークフローの対象ブランチ）に
  自動コミットされるので、GitHub上の `output/` フォルダから直接確認できます。
- レポート内の各データ項目には出典URLが添えられており、末尾の「21. 引用（参照URL一覧）」に
  すべての出典がカテゴリ別にまとめて再掲されます。数値の裏取りをしたい場合は
  このURLを参照してください。
- 情報源への接続に失敗した項目は空欄にはならず、「取得不可」と明記されます
  （レポートの30セクション構成そのものは常に維持されます）。

### 4. スマホから確認する方法（PCを開かずに読みたい場合）

1. スマホに **GitHubアプリ**（iOS/Android）をインストールし、このリポジトリを開きます。
   ブラウザでも `github.com` にアクセスすれば同様に閲覧できます。
2. リポジトリ内の `output/mobile_market_brief.md` を開きます。
   これはスマホ向けの**短縮版**（5分で読み切れる分量）です。今日の結論・相場
   シナリオ・注目テーマ／業界TOP3・監視銘柄チェック・営業トーク・最重要ポイントの
   7項目だけをコンパクトにまとめています。
3. もっと詳しく知りたい場合は `output/latest_market_brief.md`
   （詳細版・全30セクション）を開いてください。詳細版の冒頭にも
   「📱 今日の5分要約」というダイジェストがあるので、スマホでもまず
   そこだけ読めば要点は把握できます。
4. GitHub Actionsが毎朝7:00(JST)に自動更新するため、スマホ側で特別な操作は
   不要です（プルダウンで再読み込みするだけで最新版が表示されます）。
5. リポジトリを開かずURL一本で見たい場合は、次項「5. GitHub Pagesで見る」を
   設定してください。

**使い分けの目安:** `mobile_market_brief.md` = 通勤中などサッと読む短縮版、
`latest_market_brief.md` = じっくり読みたいときの詳細版、
`latest_market_brief.html`（下記GitHub Pages）= ブラウザでカードUIのまま読みたいとき。

### 5. GitHub Pagesで見る（URLをブックマークして直接開く）

`output/latest_market_brief.html`（カードUI・色分け表示のHTML版）は、
GitHub Pagesを使うとリポジトリを開かずにURL1つでスマホから直接閲覧できます。
ワークフローが毎朝、このファイルをGitHub Pagesへ自動デプロイします。

**初回のみ必要な設定（リポジトリの管理者が1回だけ行う）:**

1. GitHubリポジトリの Settings → Pages を開く。
2. "Build and deployment" の **Source** を **GitHub Actions** に設定する
   （「Deploy from a branch」ではなく「GitHub Actions」を選択）。
3. `.github/workflows/daily-market-brief.yml` を一度実行する
   （`workflow_dispatch` で手動実行するか、翌朝7:00の自動実行を待つ）。
4. 実行が成功すると、Settings → Pages に公開URLが表示されます。
   通常は次の形式です。

   ```
   https://<GitHubユーザー名>.github.io/<リポジトリ名>/
   ```

   このリポジトリの場合は次のURLになる想定です。

   ```
   https://takehiro104toshi-cmd.github.io/daily-market-brief/
   ```

   実際のURLはSettings → Pagesの表示でご確認ください。

**注意点:**

- GitHub Pagesは基本的にパブリックリポジトリ向けの無料機能です。プライベート
  リポジトリで使うにはGitHub Pro/Team/Enterprise等、Pagesが利用可能なプランが
  必要です。リポジトリの公開設定によっては、このURLは誰でも閲覧できる状態に
  なる点にご留意ください（本ツールはもともと公開情報のみを扱っているため、
  内容自体に社外秘情報は含まれません）。
- 公開されるのは `output/latest_market_brief.html` の内容だけです
  （ワークフローが実行のたびに `index.html` としてPages専用の一時フォルダへ
  コピーし、それだけをデプロイします）。リポジトリ内の他のファイルは
  一切公開されません。
- 毎朝の自動実行のたびに再デプロイされるため、ブックマークしたURLを開けば
  常に最新のレポートが表示されます。

**他の方法（今回は採用していません）:** GitHub Pagesには「特定ブランチの
`/docs` フォルダを公開する」という方式もあります。この方式は仕組みが
シンプルな反面、`output/latest_market_brief.html` とは別にリポジトリの
ルート直下に `docs/index.html` を常時コミットしておく必要があります。今回は
「毎回GitHub Actionsが一時的に生成してデプロイするだけで、リポジトリの
ファイル構成には何も追加しない」Actionsベースの方式を採用しました。

### 6. 「最新表示に更新」ボタン（アプリ感覚でスマホから開く）

基本運用は次の流れです。

1. 毎朝7:00(JST)にGitHub Actionsがレポートを自動生成する。
2. GitHub Pagesが自動的に更新される。
3. スマホでGitHub Pagesのレポートページを開く。
4. 表示が古い場合は、HTML版（Today's Dashboardのすぐ下）にある
   **「🔄 最新表示に更新」ボタン** をタップしてページを再読み込みする。

このボタンは**ページを再読み込みするだけ**（`javascript:location.reload()`）
のシンプルなボタンで、外部JSには依存しません。GitHub Actionsの実行画面へは
遷移せず、GitHubへのログインやRun workflowの操作も不要です。常時表示されます。

**手動でワークフローを実行したい場合（補足）:** 7:00の自動生成を待たずに
今すぐ最新ニュース・最新マーケットデータで再生成したい場合は、GitHubの
Actionsタブから「Daily Market Brief」ワークフローを開き、「Run workflow」を
手動実行してください（ワークフロー完了後、GitHub Pagesが自動的に再デプロイ
されます）。

## config.yaml の設定

- `watchlist.jp_stocks` / `watchlist.us_stocks`: 個別に追いたい監視銘柄（ティッカーと名称）。
  ウォッチリスト銘柄名に言及したニュースは、重要度ランキング（news_ranking.py）で
  最も高い加点（+3点、他の加点要素より大きい）が付与され、自動的に上位表示されます
  （追加設定は不要です）。
- `indices` / `forex` / `rates` / `commodities`: 取得する指標。`symbol` は yfinance用、
  `stooq_symbol` はyfinance失敗時のフォールバック用（Stooqの公開CSV、省略可）。
  v4では Today's Dashboard向けに `indices` へSOX指数（`^SOX`）、`commodities` へ
  ビットコイン（`BTC-USD`）を追加しています。
- `news_sources`: 見出しを取得する公開RSSのURL一覧（相場関連ニュース）
- `general_news_sources`: 「営業準備」の今日の雑談向けに使う、相場以外の一般ニュースRSS。
  見出しに株・為替・金利などの相場関連キーワードが含まれるものは自動的に除外されます。
- `nikkei_sources` / `bloomberg_sources` / `reuters_sources` / `cnbc_sources` /
  `wsj_sources` / `marketwatch_sources` / `investing_sources` / `boj_sources` /
  `mof_sources`: 各追加情報源のURL上書き設定（省略時は対応する `src/collectors/*.py`
  の既定URLを使用）。本番運用で確認済みのURLに差し替えたい場合や、URLが変更された
  場合の更新に使います。
- `edinet.documents_url` / `fred.csv_url_template` / `fred.series`: EDINET・FRED
  エンドポイントの上書き設定（省略時は対応する `src/collectors/edinet.py` /
  `src/collectors/macro.py` の既定値を使用）。
- `key_levels`: 「今日見るべき指標」の節目ライン設定。`name`（indices/forex/rates/
  commoditiesのnameと一致）、`lines`（節目の値のリスト）、`above_note` / `below_note`
  （現在値がラインを上回っている/下回っている場合の一言）を指定します。
- `tdnet`: TDnet適時開示一覧のURLテンプレートと取得件数・遡り日数
- `themes`: 注目テーマとして抽出するキーワード（ニュース見出しに含まれる回数でランキング表示）
- `sectors`: 注目業界の設定。`keywords`（見出し判定用キーワード）と
  `related_tickers`（`watchlist` 内のティッカーのうち、その業種に関連する銘柄）を持つ
  辞書形式。「業界ランキング」の追い風/逆風判定・関連銘柄表示、
  「個別株ランキング」「保有・監視銘柄分析」「長期投資アイデア」の中長期材料の
  紐付けに使われます。
- `durable_themes`: `themes` のうち、構造的・政策的な背景を持ち単発の材料出尽くしで
  終わりにくいテーマのリスト。「岡三ストラテジスト視点」の8軸★スコアリングで
  「継続性」「今後数週間重要か」の評価を高めるために使われます。
- `causal_rules`: ニュースを関連セクター・恩恵銘柄／悪影響銘柄へ変換する因果チェーンの
  ルール一覧。`trigger_keywords`（発動キーワード）／`theme`（テーマ名）／
  `beneficiary_sectors`・`negative_sectors`（`sectors` のキー名で指定、追い風／逆風業種）／
  `durable`（継続性の高いテーマかどうか）／`note`（一言解説）を指定します。
  「岡三ストラテジスト視点」機能の中核設定です（詳細は前述の
  「岡三ストラテジスト視点機能について」を参照）。
- `macro_events`: FOMC・日銀会合・米CPI・米PPI・米雇用統計・SQ・IPO・決算発表など、
  公開されているマクロイベントのスケジュールを手動で管理するリスト（`date` と `label`）。
  信頼できる公開カレンダーAPI/RSSが確認できていないため、スクレイピングはせず
  ユーザーが把握している公開情報を登録する運用です。「今日のイベント」セクションの
  今日／今週／今月の分類に使われます（`config.yaml` にlabelの記載例をコメントで
  用意しています）。
- `source_reliability`: 情報源別の信頼度スコア（0.0〜1.0）。複数の情報源から
  同じ内容のニュースが配信された場合、重複除去（`dedupe_headlines`）で
  信頼度の高い方を残すために使います。未掲載の情報源は既定値 0.5 が使われます。
- `notifications.email.enabled` / `notifications.line.enabled`: メール・LINE通知の
  ON/OFFスイッチ（`true`/`false`）。`false` にすると、対応する環境変数（Secrets）が
  設定されていても通知を送りません。既定値は両方 `true` です。
- `output.pages_url`: 通知本文に載せるGitHub PagesのURLを明示したい場合に設定します。
  空欄のままなら、GitHub Actions実行時は環境変数 `GITHUB_REPOSITORY`（Actionsが
  自動設定）から `https://<owner>.github.io/<repo>/` を自動的に組み立てます。
- `rashinban.dir` / `rashinban.max_files`: Rashinban Learning Source（v2.6）の
  読み込み設定（下記参照）。

## Rashinban Learning Source（羅針盤を学習ソースにする・v2.6）

岡三「羅針盤」のテキストを `data/rashinban/` に置くだけで、毎朝のGitHub Actions
実行時に自動で読み込まれ、分析の精度向上に**分析フレーム（判断の型）として**
利用されます。**PCもClaude Codeも不要**で、スマホのブラウザだけで更新できます。

### 追加のしかた（GitHub Webでの操作だけで完結）

1. GitHubでこのリポジトリを開く
2. `data/rashinban/latest.md` を開いて鉛筆マーク（Edit）を押す
   （無い場合は `data/rashinban/` で「Add file → Create new file」→ ファイル名 `latest.md`）
3. 羅針盤の本文を貼り付けて「Commit changes」
4. 翌朝のレポートから自動反映（すぐ確認したい場合はActionsから手動実行）

日付つきファイル（例: `2026-07-05_rashinban.md`）を追加していく運用も可能で、
新しい順に最大 `rashinban.max_files` 件（v2.7から既定100件）が読み込まれます。
v2.7では単に読むだけでなく「知識ベース化」します（全ファイルを走査 →
重複する知見を統合 → 複数号で繰り返し登場する重要な知識だけを抽出）。
`latest.md` は常に最新扱いです。対応形式は `.md` / `.txt` のみ（PDF/DOCXは
本文をコピーしてmd/txtに貼り付けてください）。

### 何に使われるか・使われないか

- 抽出はすべてルールベース（AI API不使用）。相場の見方・テーマ選定・銘柄の
  選び方・リスクの見方・時間軸の置き方という「型」だけを短い断片として抽出します。
- 羅針盤が言及している既存 `macro_themes` のテーマ（重点テーマ）に一致する
  ニュース・テーマには、News Ranking（+1の補助加点）／Strategist View／
  Future Intelligence／Investment Thesis／Executive Summary に参照した旨が付きます。
- **本文がレポートへ転載されることはありません。** HTMLには読み込みファイル名・
  日付・抽出フレーム数・使用状況だけを表示します。
- ファイルが1つも無い場合は自動でスキップされ、従来と完全に同じ動作です。

## Smart Intelligence Evolution（v2.8）

「毎日読むレポート」から「毎日学習し続ける投資AI」への進化。既存の分析ロジック
（Momentum・Confidence・Watchlist判定）は維持したまま、以下を追加しています
（HTML版のみ。Markdown版は従来通り）。

- **Investment Journal / Learning History**: 毎日のAI判断（重要ニュース・テーマ・
  シナリオ・Thesis 等）を `data/investment_journal/journal.json` に自動記録し、
  30/90/180日後に実際の市場と機械的に答え合わせ（★評価・的中/外れ）します。
- **Theme Confidence Learning**: テーマ予想を `data/theme_learning/theme_learning.json`
  に蓄積し、30日後の地合いで勝率を学習。勝率で Future Intelligence の Confidence を
  上下限つき（-20〜+10点）で実績補正します（記録が貯まるほど賢くなります）。
- **今日の3大シナリオ**: 強気/中立/弱気を期待値（確率）の高い順に最大3つへ整理。
- **情報ソース信頼度（Source Trust）**: 出典から★1〜5とティア（公式発表／一流
  メディア・IR／主要メディア／一般メディア／参考情報）を判定して表示します。
- **Why Today**: 各重要カードに「なぜ今日見るべきか」を1行で表示します。
- **低重要度記事の折りたたみ**: 重要度×鮮度で初期表示を選別し、★★★☆☆以下・
  48時間超は「詳しく」に折りたたみます（削除はしません）。

上記のうち、学習データ（journal.json / theme_learning.json）は GitHub Actions が
毎朝コミットして永続化します（`data/*/README.md` 参照）。

### 任意のオプション（外部API・自動取得）

- **英語ニュース自動翻訳**: `ANTHROPIC_API_KEY`（Secrets）を設定すると、英語見出しを
  日本語へ自動翻訳し「日本語 → 原文を見る」で表示します。未設定なら原文のまま
  （既存動作に影響なし）。`config.yaml` の `translation.enabled` でON/OFF。
- **経済カレンダー自動取得**: `config.yaml` の `economic_calendar.url` に公開RSS/JSONの
  URLを設定すると、「今週の重要イベント」へ自動で取り込みます（未設定なら
  従来通り `macro_events` の登録分のみ）。信頼できる無償ソースが確定するまでは
  空欄運用を推奨します。

## Real-Time Freshness / Translation / Source Expansion（v2.9）

「自分だけでマーケットを分析・予測し続けるための自己改善型システム」へ向けた、
鮮度・翻訳・情報源の強化です。

### 「最新表示に更新」ボタンの正しい意味

このHTMLはGitHub Pagesという**静的ホスティング**の上で動いています。静的ページは
あらかじめ生成されたHTMLファイルを配るだけの仕組みで、ページを開いた人のブラウザ
上で `python main.py` を実行することはできません（サーバー側の実行環境が無いため）。
そのため、ボタンは2段階になっています。

1. **「ページを再読み込み」** — 常時表示。`location.reload()` でブラウザの
   キャッシュ・表示を更新するだけです。**新しいデータを取得するわけではありません**
   （最後にGitHub Actionsが生成した版を再表示するだけ）。
2. **「最新レポートを生成する（GitHub Actionsを開く）」** — `config.yaml` の
   `output.actions_url`（または環境変数 `ACTIONS_URL`／GitHub Actions実行時は
   `GITHUB_REPOSITORY` から自動算出）が設定されている場合のみ表示されます。
   押すとGitHub ActionsのDaily Market Briefワークフロー画面が**新しいタブ**で
   開きます。そこで「Run workflow」ボタンを押すと、その時点の最新ニュース・
   市場データでレポートが再生成されます。完了後（数分後）、このページで
   「ページを再読み込み」を押すと反映されます。

**セキュリティ上、押した瞬間に自動でActionsを実行する実装はしていません。**
GitHub Token・Secretsは、このHTML・リンク先のいずれにも一切埋め込まれません
（誰でも閲覧できるURLをリンクするだけです）。

### なぜHTMLだけではPythonを実行できないか

GitHub PagesはNode.js/Python等のサーバーサイド実行環境を持たない、純粋な静的
ファイル配信サービスです。ブラウザ側のJavaScriptから直接「サーバー上のスクリプトを
実行する」ことは（安全な認証つきバックエンドが無い限り）できません。将来的に
完全リアルタイム化するには、以下のいずれかが必要です。

- **Cloudflare Worker**: 軽量なサーバーレス関数。GitHub Actions workflow_dispatch
  APIを認証つきで呼び出す中継役として使える（TokenはWorker側のSecretに保管し、
  HTMLには一切出さない）。
- **Vercel Function / AWS Lambda等**: 同様に、認証つきでActions APIを呼び出す
  中継サーバーとして使える。
- **GitHub App**: リポジトリに対して限定的な権限を持つApp登録を行い、
  ユーザーのログインなしで安全にworkflow_dispatchを起動できる仕組みを作れる。

いずれも「HTMLに秘密情報を埋め込まない」設計が前提です。v2.9では、まず安全な
導線（Actions画面を開くだけ）までを実装しています。

### 英語ニュース自動翻訳を有効化する方法

1. GitHubリポジトリの Settings → Secrets and variables → Actions で
   `ANTHROPIC_API_KEY` を設定する
2. `requirements.txt` の `anthropic` 行のコメントを外す（またはActions側で
   `pip install anthropic` されるようにする）
3. 翌朝から、英語見出し（Bloomberg・Reuters・CNBC・WSJ・Fed・SEC等）が自動で
   日本語へ翻訳され、「日本語タイトル → 原文を見る（詳しく内）」の順で表示される

未設定の場合は翻訳されず、原文のまま表示されます（既存動作に影響なし）。
`config.yaml` の `translation.enabled: false` で機能自体を無効化することもできます。

### Source Expansion（情報源の追加方針）

- 使用してよいのは **RSS／公開API／公式JSON・XML／公式IR／公式統計** のみ。
- 有料記事の本文取得、ログイン必須ページの取得、利用規約が不明確なスクレイピングは
  一切行いません。
- v2.9で追加した情報源（実装済み）: Federal Reserve/FOMC・SEC・BLS・EIA・ECB・
  CoinDesk・CoinTelegraph・Yahoo Finance US（いずれも公開RSS、`config.yaml`の
  `source_classification.implemented` を参照）。
- 見送った情報源とその理由は `config.yaml` の `source_classification`
  （`reference_only` / `skipped`）に一覧化しています（例: 半導体各社の
  Newsroomは定型RSSが無くスクレイピングが必要になるため見送り、Seeking Alpha/
  Benzingaは利用規約・Bot対策の不確実性のため見送り、等）。
- 新しい情報源を追加したい場合は、`src/collectors/` に1ファイル追加し、
  `main.py` の追加情報源ループへ1行足すだけで組み込めます（既存collectorと
  同じ形の関数・失敗時は空リストを返す設計を踏襲してください）。

## v3.0 Foundation Completion（翻訳キャッシュ／リアルタイム導線／経済カレンダー）

v2.8/v2.9で入れた骨組みを「本番で使える」状態に仕上げたものです。

### 英文翻訳の有効化と翻訳キャッシュ

- 有効化手順は前節「英語ニュース自動翻訳を有効化する方法」と同じ
  （`ANTHROPIC_API_KEY` Secret ＋ `anthropic` パッケージ）。
- v3.0で **翻訳キャッシュ**（`data/translation_cache/translation_cache.json`）を追加。
  一度翻訳した見出しは保存され、翌日以降は**APIを呼ばずに再利用**します（コスト削減）。
  そのため `ANTHROPIC_API_KEY` が未設定でも、**過去に翻訳済みの見出しは日本語で
  表示**されます。キャッシュはGitHub Actionsが自動コミットして蓄積します。
- HTMLでは日本語訳を優先表示し、「翻訳済み」バッジを付け、原文は各カードの
  「詳しく」内（英語のまま）に保持します。

### 「最新表示に更新」と「最新レポート生成」の違い

- **ページを再読み込み**: 今表示中のレポート（最後に自動生成された版）を再表示するだけ。
  新しいデータは取得しません。
- **最新レポートを生成する**: `output.actions_url` 設定時のみ表示。GitHub Actions画面を
  新しいタブで開き、そこで「Run workflow」を押すと最新データで再生成されます。
  完了後（数分後）に「ページを再読み込み」で反映されます。
- GitHub Pagesは静的サイトのためページ内から自動再生成はできません。GitHub Token・
  Secretsは**HTMLに一切埋め込みません**。将来の完全リアルタイム化（Cloudflare Worker /
  Vercel Function / GitHub App による認証つき中継）に備え、`config.yaml` の `realtime:`
  設定枠を用意しています（`enabled: false` の間は既存動作のまま）。
- News Freshnessカードの「情報取得時刻を詳しく見る」で、HTML生成時刻・市場データ
  取得時刻・各ニュースソースの取得時刻を確認できます。

### 経済カレンダー自動取得

- `config.yaml` の `economic_calendar.sources` に公開RSS/JSON/CSVを列挙すると、
  今週の重要イベントを自動取得し、`macro_events`（手入力）とマージして
  「今週の重要イベント」に反映します。**手入力（macro_events）が優先**され、
  自動取得分は未登録のものだけ追加されます。
- 取得先が未設定・取得失敗・パース失敗でも、`macro_events` のみでレポートは継続します
  （止まりません）。公開ソースのみ・APIキー不要。各イベントにSource・Source Trust・
  取得時刻が表示されます。イベント名から影響対象（米CPI→米金利/ドル円/NASDAQ等）を
  自動補完します。
- 信頼できる無償の経済カレンダーAPIが確定するまでは、`sources` を空にして
  `macro_events` の手入力運用でも十分に機能します。

### Source Expansion / 永続化データ

- 使ってよい情報源: **RSS／公開API／公式JSON・XML／公式IR／公式統計** のみ。
  有料本文・ログイン必須・規約不明なスクレイピングは行いません
  （実装済み/参照のみ/見送りの分類は `config.yaml` の `source_classification`）。
- GitHub Actionsが自動コミットして蓄積する永続データ:
  `data/translation_cache/translation_cache.json`（翻訳）／
  `data/investment_journal/journal.json`（AI判断の答え合わせ）／
  `data/theme_learning/theme_learning.json`（テーマ勝率）。いずれも初回実行で
  自動生成され、手で作る必要はありません（各フォルダのREADME参照）。

## v3.3 Latest Report Generation Button Upgrade（スマホからの再生成導線を改善）

「最新レポートを生成する」ボタンまわりを、スマホからでも迷わず使えるように再設計しました。

### ページ再読み込みとレポート再生成の違い（もう一度）

- **🔄 ページを再読み込み**: 今このスマホ・PCに表示されているHTMLを読み直すだけです。
  **新しいニュース・市場データは一切取得しません**。「さっき生成した最新版が
  ちゃんと表示されているか」を確認する用途です。
- **⚙️ 最新レポートを生成する**: これを押すとGitHub Actionsの実行画面（該当
  ワークフローの直リンク）が新しいタブで開きます。そこで「Run workflow」を押して
  初めて、その時点の最新ニュース・市場データで**新しいレポートが作られます**。
  生成には1〜3分かかり、終わったら元のページに戻って「🔄 ページを再読み込み」を
  押すと新しい内容が反映されます。
- HTML上には「最終生成時刻」と上記の違いの説明が常に表示されます。

### スマホでRun workflowを押す手順

1. 「⚙️ 最新レポートを生成する」をタップし、開いた画面でGitHubにログインする
2. 「Run workflow」をタップする
3. 表示された緑の「Run workflow」ボタンをもう一度タップする
4. 完了まで1〜3分待つ
5. 元のページに戻って「🔄 ページを再読み込み」をタップする

同じ手順はHTML内にも「📱 スマホでの実行手順」として折りたたみ表示されています。

### GitHub Actions画面でRun workflowが見えない場合

- GitHubにログインできているか確認する（未ログインだとボタンが出ないことがあります）
- スマホのブラウザで「デスクトップ用サイトを表示」に切り替えてみる
  （モバイル表示だと一部のボタンが省略される場合があります）
- 公式のGitHubアプリ（iOS/Android）から同じリポジトリ・ワークフローを開いてみる

### actions_urlの設定（v3.3・改善②）

`config.yaml` の `output.actions_url` に、該当ワークフローの実行画面URLを直接
設定できます（設定時はこれが最優先で使われます）。

```yaml
output:
  actions_url: "https://github.com/<owner>/<repo>/actions/workflows/daily-market-brief.yml"
```

未設定の場合は、GitHub Actions実行時に環境変数 `GITHUB_REPOSITORY` から自動的に
同じ形式のURLを組み立てます。ローカル実行時などで上書きしたい場合は環境変数
`ACTIONS_URL` を設定してください（これが最優先）。**いずれも設定されていない場合、
ボタンは消えずに「設定未完了」の説明が表示されます**（何が足りないか分かるように
するため、非表示にはしていません）。

### 完全ワンタップ化には何が必要か

現状の安全な実装は「GitHub Actions画面を開き、ユーザー自身がRun workflowを押す」
ところまでです。ボタン一つで即座にレポートが再生成される「完全ワンタップ化」を
実現するには、以下のいずれかの**認証つき中継バックエンド**が別途必要です。

- **Cloudflare Worker**: 軽量なサーバーレス関数。GitHub Actionsのworkflow_dispatch
  APIを認証つきで呼び出す中継役として使えます。
- **Vercel Function / AWS Lambda等**: 同様に、認証つきでActions APIを呼び出す中継サーバー。
- **GitHub App**: リポジトリに限定的な権限を持つApp登録を行い、ユーザーのログイン
  なしで安全にworkflow_dispatchを起動できる仕組み。

`config.yaml` の `realtime.enabled: true` かつ `realtime.endpoint_url` に上記の
中継先URLを設定すると、HTMLに「🚀 ワンタップで最新生成」ボタンの**枠**が表示されます
（v3.3時点ではバックエンド未実装のため、ボタンは押せない状態で表示されるだけです）。

### なぜGitHub TokenをHTMLに出してはいけないか

GitHub Pagesで公開されるHTMLは**誰でも閲覧できます**。もしGitHubへの書き込み権限を
持つToken（Personal Access Token等）や `ANTHROPIC_API_KEY` のような秘密情報をHTMLの
どこか（テキスト・JavaScript・コメント欄）に埋め込んでしまうと、閲覧した誰もが
それを使って任意のワークフローを実行したり、他のAPIを不正利用できてしまいます。
そのため本システムは、認証が必要な操作（workflow_dispatchの起動など）を**ユーザー
自身がGitHubにログインした状態で手動操作する**形に限定し、秘密情報の類は一切
HTMLへ出力しません（将来の中継バックエンドを使う場合も、秘密情報はバックエンド側の
環境変数・Secretにのみ保管する設計とします）。

## 通知機能（メール・LINE）

レポート生成後、任意で「今日の結論＋重要ニュース3件＋GitHub Pages URL」を
メール（SMTP）とLINE（Messaging API）に自動通知できます。**どちらも未設定のまま
運用してもエラーにはならず**、レポート生成自体は必ず成功します（通知はあくまで
付加機能です）。優先度はメール（設定が簡単・多くの環境で動作）→ LINE の順です。

### メール通知（SMTP）を設定する

以下の環境変数（ローカル実行なら `.bashrc`・`.env` 等、GitHub Actionsなら
Secrets）をすべて設定すると有効になります。1つでも欠けている場合は
自動的にスキップされます。

| 環境変数 | 内容 | 例 |
| --- | --- | --- |
| `SMTP_HOST` | SMTPサーバーのホスト名 | `smtp.gmail.com` |
| `SMTP_PORT` | SMTPポート番号（STARTTLS想定・省略時587） | `587` |
| `SMTP_USER` | SMTP認証のユーザー名 | `you@gmail.com` |
| `SMTP_PASSWORD` | SMTP認証のパスワード | Gmail等は**アプリパスワード**を推奨 |
| `MAIL_TO` | 送信先メールアドレス | `you@example.com` |
| `MAIL_FROM` | 送信元メールアドレス（省略時は`SMTP_USER`を使用） | `you@gmail.com` |

件名は `【Market Brief】YYYY-MM-DD 朝刊`、本文は「今日の結論／重要ニュース3件／
GitHub Pages URL」で構成されます。

### LINE通知（Messaging API）を設定する

LINE Notifyは2025年3月末にサービスを終了したため、後継として案内されている
**LINE Messaging APIのプッシュメッセージ機能**を使用しています（LINE Notifyでは
ありません）。

1. [LINE Developersコンソール](https://developers.line.biz/console/)でMessaging API
   チャネルを作成する。
2. チャネルアクセストークン（長期）を発行する。
3. 通知を受け取りたいLINEアカウント（作成したBot）を友だち追加し、
   そのユーザーID（またはグループID）を控える。
4. 以下の環境変数を設定する。

| 環境変数 | 内容 |
| --- | --- |
| `LINE_CHANNEL_ACCESS_TOKEN` | LINE Developersコンソールで発行したチャネルアクセストークン（長期） |
| `LINE_TO` | 通知を送るユーザーID または グループID |

いずれか一方でも未設定ならLINE通知はスキップされます。

**送信の信頼性について:** 一時的なネットワーク不調に備え、送信失敗時は2秒後に
1回だけ自動的に再送を試みます（`notifiers/line_sender.py`）。それでも失敗した場合は
警告ログを出力してスキップし、レポート生成自体には影響しません。レポート生成が
成功した場合は毎回、GitHub PagesのURLを含む本文でLINE通知が自動送信されます
（GitHub Actions実行時は `Generate market brief` ステップの中で、レポート保存後に
送信されます）。

### GitHub Actions Secretsへの設定方法

GitHub Actions上で自動実行する場合、上記の環境変数はリポジトリの
**Settings → Secrets and variables → Actions → New repository secret** から
1つずつ登録してください。登録すると、ワークフロー（`.github/workflows/daily-market-brief.yml`）
の `env:` に自動的に渡され、`main.py` 実行時に読み込まれます（追加のワークフロー
編集は不要です）。

登録が必要なSecrets一覧（すべて任意設定）:

- `SMTP_HOST` / `SMTP_PORT` / `SMTP_USER` / `SMTP_PASSWORD` / `MAIL_TO` / `MAIL_FROM`（メール通知用）
- `LINE_CHANNEL_ACCESS_TOKEN` / `LINE_TO`（LINE通知用）
- `ANTHROPIC_API_KEY`（Claude APIによる文章磨き上げ用、任意）
- `EDINET_API_KEY`（EDINET書類一覧APIのAPIキーが必要な場合のみ、任意）

いずれも未設定のままで構いません。その場合は該当機能がスキップされるだけで、
レポート生成・GitHub Pages公開は通常どおり動作します。

### notifiers/ の実装状況

- `notifiers/base.py`: 共通インターフェース `Notifier`（`is_configured() -> bool` /
  `send(payload) -> bool`）と、通知内容を表す `NotificationPayload`
  （`title` / `summary` / `report_url`）を定義。
- `notifiers/email_sender.py`: `EmailNotifier`（**実装済み**・SMTP／STARTTLS）
- `notifiers/line_sender.py`: `LineNotifier`（**実装済み**・LINE Messaging API プッシュメッセージ）
- `notifiers/discord_webhook.py` / `slack_webhook.py` / `telegram_bot.py`:
  Discord／Slack／Telegramは**将来拡張用スタブ**（`is_configured()` は常に`False`、
  `send()` を呼ぶと`NotImplementedError`）。現時点では未実装です。

## 将来のPDF化について

現時点ではMarkdown出力のみですが、`src/report/pdf.py` にPDF変換用のフックを用意しています。
`pandoc` がインストールされた環境であれば以下でPDF化できます。

```bash
python3 -m src.report.pdf output/2026-07-01_market_brief.md
```

## テスト

ネットワークアクセスなしで実行できるオフラインテストを用意しています。

```bash
pytest tests/
```

## ディレクトリ構成

```
daily-market-brief/
  main.py                  # エントリーポイント（データ収集→AI分析→レポート生成を統括）
  config.yaml              # 監視銘柄・情報源・節目ライン・マクロイベントの設定
  requirements.txt
  pyproject.toml           # プロジェクトメタデータ・pytest設定
  src/
    utils.py               # 設定読込・HTTP取得・出典URL管理
    collectors/            # 公開情報の収集（事実の取得のみ、考察は行わない）
      market_data.py       # 指数・為替・金利・コモディティ・個別銘柄
      news.py               # 公開RSSニュース見出し（相場ニュース・一般ニュース共通、重複除去・信頼度スコア含む）
      tdnet.py              # TDnet適時開示
      earnings.py           # 決算発表予定
      themes.py             # テーマ・業種キーワードマッチング（追い風/逆風判定含む）
      nikkei.py             # 日経電子版の見出し（ベストエフォートRSS）
      bloomberg.py          # Bloombergの見出し（ベストエフォートRSS）
      reuters.py            # Reutersの見出し（ベストエフォートRSS）
      cnbc.py               # CNBCの見出し（ベストエフォートRSS）
      wsj.py                # WSJの見出し（ベストエフォートRSS）
      marketwatch.py        # MarketWatchの見出し（ベストエフォートRSS）
      investing.py          # Investing.comの見出し（ベストエフォートRSS）
      boj.py                # 日本銀行 新着情報（公開RSS・実装済み）
      mof.py                # 財務省 新着情報（公開RSS・実装済み）
      edinet.py             # EDINET書類一覧API（公開API・実装済み）
      macro.py              # マクロ指標（FRED公開CSV）＋Trading Economics参照リンク
      kabutan.py            # 株探（参照リンクのみ・自動取得なし）
      moomoo.py             # moomoo証券（参照リンクのみ・自動取得なし）
      jpx.py                # JPX日本取引所グループ（参照リンクのみ・自動取得なし）
      minkabu.py            # MINKABU（参照リンクのみ・自動取得なし）
      sbi.py                # SBI証券（参照リンクのみ・自動取得なし）
      rakuten.py            # 楽天証券（参照リンクのみ・自動取得なし）
    analysis/               # 「AI分析」を担うルールベースの考察エンジン一式
      llm_enhancer.py       # Claude API任意連携（ANTHROPIC_API_KEY設定時のみ有効）
      models.py             # 分析結果の共有データクラス（AnalysisBundle 等）
      scenario.py           # 強気/中立/弱気の3シナリオ（確率・理由・注目指標）
      causal_chain.py       # マクロの因果フロー1本＋個別の因果チェーン3〜5本
      news_ranking.py       # ニュースランキング（理由/影響市場/影響業種/営業トークつき、ウォッチリスト銘柄言及を最優先表示）
      strategist_engine.py  # 岡三ストラテジスト視点パイプライン＋8軸★スコアリング（causal_rules/durable_themes駆動）
      executive_summary.py  # AI Executive Summary（今日最重要ニュース最大3件、日本株/ドル円/金利/恩恵・悪影響銘柄への影響）
      market_impact.py      # マーケットインパクト（12対象への影響度★・プラス/マイナス/中立）
      sector_strength.py    # セクターランキング（本日の強弱予測、↑/→/↓＋理由）
      call_priority.py      # 今日電話すべき顧客（富裕層/NISA/退職金/法人/相続/若年層）
      morning_meeting_comment.py # 朝会コメント（30秒/1分/3分の3パターン）
      key_levels.py         # 今日見るべき指標（節目ラインとの比較）
      themes_forecast.py    # テーマ別ランキングと1週間/1か月/3か月の見立て
      sector_ranking.py     # 業界ランキングTOP10
      stock_ranking.py      # 個別株ランキング（日本株/米国株TOP10）
      watchlist_analysis.py # 保有・監視銘柄の毎朝分析（今日/1週間/1か月/長期/リスク）
      watchlist_quicklist.py # 今日のウォッチリスト（★評価＋1行理由）
      long_term_picks.py    # 長期投資アイデアTOP5
      sales_talk.py         # 営業トーク（4種類）
      sales_prep.py         # 営業準備（社長向け一言・富裕層向け話題・用語解説・雑談・Q&A）
      sales_comments.py     # 営業向けコメント（7オーディエンス）と想定質問と回答例（拡張Q&A）
      top_picks.py          # 今日の注目5銘柄（日本株5銘柄・米国株5銘柄、コード/企業名/理由/注目材料/短期見通し）
      instrument_scenarios.py # 日経平均・ドル円・米国市場ごとの強気/中立/弱気シナリオ
      okasan_sales_comments.py # 岡三証券営業向けコメント（富裕層/法人/NISA/退職金/相続）
      chat_topics.py        # 今日の会話ネタ
      events.py             # イベントの今日/今週/今月分類
      ai_summary.py         # 300文字以内のAIまとめ
    report/
      format_utils.py       # 数値整形・★評価・文字数トリムなどの共通ヘルパー
      sections.py            # 各セクションのMarkdown整形関数（builder.pyの肥大化防止）
      builder.py             # 30セクションのMarkdownレポート組み立て（詳細版・組み立て役のみ）
      mobile_builder.py      # 8セクションの短縮版レポート組み立て（スマホ向け）
      html_builder.py        # カードUI・色分け表示・最終更新時刻表示・Today's Dashboard・目次のHTML版レポート組み立て
      pdf.py                 # 将来のPDF化フック
  notifiers/                 # メール・LINE通知（実装済み）＋将来拡張用スタブ
    base.py                  # 共通インターフェース Notifier（is_configured/send）/ NotificationPayload
    email_sender.py          # EmailNotifier（実装済み・SMTP）
    line_sender.py            # LineNotifier（実装済み・LINE Messaging API）
    discord_webhook.py / slack_webhook.py / telegram_bot.py
                              # Discord/Slack/Telegramのスタブ実装（未実装・NotImplementedError）
  tests/
    factories.py             # テスト用フィクスチャ生成（複数テストファイルで共有）
    test_report_builder.py  # 詳細版レポート組み立てのオフラインテスト
    test_mobile_builder.py   # 短縮版レポート組み立てのオフラインテスト
    test_html_builder.py     # HTML版レポート組み立てのオフラインテスト
    test_analysis.py         # AI分析エンジン各モジュールのオフラインテスト
    test_collectors.py       # 追加情報源・重複除去・信頼度スコアのオフラインテスト
    test_notifiers.py        # メール/LINE通知（モック）＋スタブ通知のオフラインテスト
    test_main.py             # --date オプション・latest/mobile/html生成のオフラインテスト
  output/                    # 生成されたレポートの保存先
    YYYY-MM-DD_market_brief.md    # 日付入りレポート（詳細版Markdown）
    latest_market_brief.md        # 最新レポート・詳細版（毎回上書き）
    mobile_market_brief.md        # 最新レポート・スマホ向け短縮版（毎回上書き）
    YYYY-MM-DD_market_brief.html  # 日付入りレポート（HTML版・カードUI）
    latest_market_brief.html      # 最新レポート・HTML版（毎回上書き）
```

## トラブルシューティング

### GitHub Actionsが失敗する

1. Actionsタブ →「Daily Market Brief」→ 失敗した実行を開き、ログを確認します。
   `python3 main.py` の実行ログには、どの情報源への接続に失敗したか
   （`[WARNING] 取得失敗: ...`）が必ず出力されます。多くの場合、個別の情報源の
   一時的な障害であり、レポート自体は生成されます（ワークフロー全体は失敗しません）。
2. ワークフロー自体が失敗（赤いバツ）している場合は、多くは以下のいずれかです。
   - `output/*.md` / `output/*.html` のコミット・プッシュに失敗
     → Settings → Actions → General → "Workflow permissions" が
     **Read and write permissions** になっているか確認してください。
   - 依存パッケージのインストール失敗 → `requirements.txt` の内容とPythonの
     バージョン（3.11想定）を確認してください。
3. 実行結果のサマリー（Job Summary）に、生成されたファイル一覧のチェックリストが
   表示されるので、そこでどこまで成功したかを確認できます。

### GitHub Pagesが更新されない

1. Settings → Pages で **Source が "GitHub Actions"** になっているか確認してください
   （"Deploy from a branch" のままだと自動デプロイされません）。
2. Actionsタブで `deploy-pages` ジョブが成功しているか確認してください。
   `generate-report` ジョブが失敗すると `deploy-pages` も実行されません。
3. ブラウザのキャッシュが残っている場合があるため、スマホ・PCともに
   強制リロード（またはプライベートブラウジングで開く）を試してください。
4. 初回のみ、Pages設定後に一度 `workflow_dispatch` で手動実行するか、
   翌朝の自動実行を待つ必要があります。

### メールが届かない

1. `SMTP_HOST` / `SMTP_PORT` / `SMTP_USER` / `SMTP_PASSWORD` / `MAIL_TO` の
   5つがすべてSecretsに登録されているか確認してください（1つでも欠けると
   自動的にスキップされ、ログに `メール通知はSMTP設定が未完了のためスキップします。`
   と出力されます）。
2. Gmail等、2段階認証を使っているサービスでは、通常のログインパスワードではなく
   **アプリパスワード**が必要です。
3. Actionsのログに `メール通知の送信に失敗しました: ...` という警告が出ている場合は、
   その内容（認証エラー・接続タイムアウト等）を確認し、SMTP設定を見直してください。
   通知が失敗してもレポート生成自体は成功します。
4. `notifications.email.enabled` が `config.yaml` で `false` になっていないか
   確認してください。

### LINEが届かない

1. `LINE_CHANNEL_ACCESS_TOKEN` と `LINE_TO` の両方がSecretsに登録されているか
   確認してください（片方でも欠けるとスキップされます）。
2. 通知を受け取るLINEアカウントが、作成したBotを友だち追加済みか確認してください。
3. `LINE_TO` に設定したユーザーID／グループIDが正しいか（トークンとひも付く
   チャネルのものになっているか）を確認してください。
4. `notifications.line.enabled` が `config.yaml` で `false` になっていないか
   確認してください。

## 免責事項

本ツールが生成するレポートは、無料で公開されている情報を機械的に収集・整理したものです。
内容の正確性・完全性・最新性を保証するものではありません。特定の金融商品の売買を推奨・勧誘
するものではなく、投資助言には該当しません。投資判断は必ずご自身の責任で、一次情報源を
確認の上行ってください。
