# daily-market-brief

毎朝、公開情報のみを収集し、「なぜそうなっているか」までAIが考察した
朝の戦略レポート（Morning Strategy Report / Market Intelligence System v2）を
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
   外部APIも追加費用も不要で、この層だけで全19セクションが完成します。
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

- 主要指数（日経平均、NYダウ、S&P500、ナスダック、VIX など）・為替・米10年金利・原油・金
- 日経・ロイター・NHKなど公開RSSのニュース見出し（本文は取得しません）
- TDnet（適時開示情報閲覧サービス）の公開開示一覧
- ウォッチリスト銘柄（日本株・米国株）の決算発表予定
- 今日の相場シナリオ（強気／中立／弱気それぞれの確率・理由・注目指標の3本立て）
- ニュースの重要度ランキング（理由・影響市場・影響業種つき、最重要ニュースを1位に固定）
- 米国株→金利→為替→日本株→業界→個別株の因果関係を矢印で整理（マクロの大きな流れ1本＋
  個別の短い因果チェーン3〜5本）
- 今日見るべき指標（為替・VIX・米10年・WTI・Gold の現在値・節目ライン・超えたら何が起きやすいか）
- 注目テーマ・注目業界・個別株のランキングと短中期・長期の見立て
- 今日のウォッチリスト（監視銘柄を★評価＋1行理由でさっと確認）
- 保有・監視銘柄の毎朝分析（今日／1週間／1か月／長期）
- AIが選ぶ長期投資アイデアTOP5
- 営業準備（社長向け一言・富裕層向け話題・初心者向け用語解説・今日の雑談・想定質問Q&A）
- 営業トーク（法人社長向け／個人投資家向け／初心者向け／富裕層向け）
- 今日の会話ネタ、イベント（今日／今週／今月）、300字以内のAIまとめ
- 収集したすべてのデータについて、出典URLをレポート末尾に記録
- スマホでもPCを開かず読めるよう、詳細版に「今日の5分要約」ダイジェストを追加し、
  短縮版Markdown（`mobile_market_brief.md`）と、色分けカードUIのHTML版も生成
- HTML版はGitHub Pagesにも自動デプロイされ、URLをブックマークするだけで
  リポジトリを開かずスマホから直接閲覧できます（要・初回設定、詳細は後述）

出力は `output/YYYY-MM-DD_market_brief.md`（詳細版Markdown）に保存され、同時に同じ内容が
`output/latest_market_brief.md` にも上書き保存されます。スマホ閲覧向けの短縮版
`output/mobile_market_brief.md` と、カードUIのHTML版
（`output/YYYY-MM-DD_market_brief.html` / `output/latest_market_brief.html`）も
毎回あわせて生成されます。

## レポートの構成（Market Intelligence System v2）

冒頭に「📱 今日の5分要約」（今日の結論・重要ニュース3件・注目テーマ3つ・見るべき指数・
営業一言を200〜300文字程度に凝縮）を表示したのち、以下19セクションが続きます。

1. 今日の結論（3行・太字）★★★★★
2. 主要指標（事実）
3. 為替・金利（事実）
4. 今日の相場シナリオ（AI分析・強気／中立／弱気それぞれの確率・理由・注目指標）★★★★★
5. 今日の重要ニュースランキング（AI分析・理由／影響市場／影響業種つき）
6. 今日見るべき指標（為替・VIX・米10年・WTI・Gold の節目ラインと一言コメント）
7. マーケット分析（AI分析・因果関係を矢印↓で整理／個別の因果チェーン3〜5本）
8. テーマ分析（AI分析・ランキング形式、今後1週間／1か月／3か月の見立て）
9. 業界ランキング TOP10（AI分析・追い風／逆風／関連銘柄／営業トーク）
10. 個別株ランキング（AI分析・日本株TOP10／米国株TOP10、短期／中期／長期）
11. 今日のウォッチリスト（★評価＋1行理由の一覧）
12. 保有・監視銘柄分析（AI分析・全銘柄について今日／1週間／1か月／長期）
13. 長期投資アイデア TOP5（AI分析）
14. 営業準備（社長向け一言・富裕層向け話題・初心者向け用語解説・今日の雑談・想定質問）
15. 営業トーク（法人社長向け／個人投資家向け／初心者向け／富裕層向け）
16. 今日の会話ネタ（AI分析・3つ）
17. イベント（事実・今日／今週／今月）
18. AIまとめ（AI分析・300文字以内の戦略サマリー）
19. 引用（事実・参照URL一覧）

- 見出し・銘柄には重要度・変化率に応じた★評価を表示します。
- データを取得できなかった項目は空欄にせず「取得不可」と明記し、
  19セクションの構成自体は常に維持されます（一部データが欠けてもレポートは崩れません）。
- 「事実」ラベルは実データ、「AI分析」ラベルはルールベースの機械的考察（Claude磨き上げ含む）
  であることを、レポート冒頭の凡例と各項目で明示しています。
- ③のシナリオ理由と④の因果チェーンは、断定表現を避け「〜の可能性があります」
  「〜と考えられます」で統一しています。

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
2. 今日の相場シナリオ（強気／中立／弱気の割合と理由）
3. 注目テーマ TOP3（各テーマ3行以内）
4. 注目業界 TOP3（各業界3行以内）
5. 監視銘柄チェック（日本株5銘柄・米国株5銘柄まで、各2行以内）
6. 今日の営業トーク（法人社長向け・個人投資家向け・初心者向けを各1つ）
7. 今日の最重要ポイント（1文）

### HTML版（カードUI・色分け表示）

`output/YYYY-MM-DD_market_brief.html` と `output/latest_market_brief.html` は、
詳細版と同じ内容をスマホ閲覧前提のカードUIで表示するHTML版です。

- 外部CSS・外部JSに依存しない自己完結型の1ファイル（`<style>` をHTML内に埋め込み）。
  GitHub上のプレビューではなく、ダウンロードしてブラウザで開く、または
  GitHub Pages等で配信することを想定しています。
- 前日比に応じて **上昇＝緑／下落＝赤／横ばい・データなし＝灰色** のバッジで色分け。
- `viewport` メタタグ設定済みで、スマホ幅でも横スクロールなしで閲覧できます。
- Markdown版と同じ `AnalysisBundle`（収集済みデータ＋AI分析結果）をそのまま
  再利用しており、HTML側で新たな考察ロジックは持ちません（見せ方だけが異なります）。

## 使用データについての方針

- 使用するのは無料で誰でも閲覧できる公開情報のみです。
- 社外秘資料、有料記事の本文、ログインが必要なサービスのデータは使用しません。
  ニュースはRSSの見出し・リンクのみを扱い、本文はスクレイピングしません。
- 各項目には取得元のURLを記録し、レポート末尾の「引用（参照URL一覧）」にまとめます。
- 「AI分析」は断定的な投資助言ではなく仮説的な考察です。「営業トーク」「今日の会話ネタ」も
  事実紹介の話材にとどめており、投資判断や勧誘目的では使用しないでください。
- 事実とAI分析は常に区別して表示されます（禁止事項の遵守）。

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
  5つが生成されていることを確認してください。詳細版は19セクションすべてが存在し、
  データ欠損箇所は空欄ではなく「取得不可」と表示されていること、短縮版は7セクション
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
- レポート内の各データ項目には出典URLが添えられており、末尾の「19. 引用（参照URL一覧）」に
  すべての出典がカテゴリ別にまとめて再掲されます。数値の裏取りをしたい場合は
  このURLを参照してください。
- 情報源への接続に失敗した項目は空欄にはならず、「取得不可」と明記されます
  （レポートの19セクション構成そのものは常に維持されます）。

### 4. スマホから確認する方法（PCを開かずに読みたい場合）

1. スマホに **GitHubアプリ**（iOS/Android）をインストールし、このリポジトリを開きます。
   ブラウザでも `github.com` にアクセスすれば同様に閲覧できます。
2. リポジトリ内の `output/mobile_market_brief.md` を開きます。
   これはスマホ向けの**短縮版**（5分で読み切れる分量）です。今日の結論・相場
   シナリオ・注目テーマ／業界TOP3・監視銘柄チェック・営業トーク・最重要ポイントの
   7項目だけをコンパクトにまとめています。
3. もっと詳しく知りたい場合は `output/latest_market_brief.md`
   （詳細版・全19セクション）を開いてください。詳細版の冒頭にも
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

## config.yaml の設定

- `watchlist.jp_stocks` / `watchlist.us_stocks`: 個別に追いたい監視銘柄（ティッカーと名称）
- `indices` / `forex` / `rates` / `commodities`: 取得する指標。`symbol` は yfinance用、
  `stooq_symbol` はyfinance失敗時のフォールバック用（Stooqの公開CSV）
- `news_sources`: 見出しを取得する公開RSSのURL一覧（相場関連ニュース）
- `general_news_sources`: 「営業準備」の今日の雑談向けに使う、相場以外の一般ニュースRSS。
  見出しに株・為替・金利などの相場関連キーワードが含まれるものは自動的に除外されます。
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
- `macro_events`: FOMC・日銀会合など、公開されているマクロイベントのスケジュールを
  手動で管理するリスト（`date` と `label`）。スクレイピングはせず、ユーザーが
  把握している公開情報を登録する想定です。「イベント」セクションの今週／今月の
  分類に使われます。

## 将来の通知拡張（notifiers/）

`notifiers/` に、将来LINE・Discord・Slack・Telegram・メールへ
レポートの要約を送信できるようにするための**インターフェースのみ**を用意しています。
**具体的な送信処理は未実装**です（`send()` を呼ぶと `NotImplementedError` になります）。

- `notifiers/base.py`: 共通インターフェース `Notifier`（`send(payload) -> bool`）と
  通知内容を表す `NotificationPayload`（`title` / `summary` / `report_url`）を定義。
- `notifiers/line_notify.py`: `LineNotifier`（LINE Notify／Messaging API想定）
- `notifiers/discord_webhook.py`: `DiscordNotifier`（Discord Webhook想定）
- `notifiers/slack_webhook.py`: `SlackNotifier`（Slack Incoming Webhook想定）
- `notifiers/telegram_bot.py`: `TelegramNotifier`（Telegram Bot API想定）
- `notifiers/email_sender.py`: `EmailNotifier`（SMTP想定）

各ファイルのdocstringに実装イメージ（`requests.post(...)` 等）を記載しています。
将来実装する際は、`Notifier` を継承したクラスの `send()` を実装し、
`main.py` から `NotificationPayload(title=..., summary=analysis_bundle.ai_summary_text, ...)`
のように呼び出す想定です。通知先のトークン・Webhook URL等は環境変数や
GitHub Actions Secretsで管理し、公開情報のみを扱う本ツールの方針は維持します。

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
      news.py               # 公開RSSニュース見出し（相場ニュース・一般ニュース共通）
      tdnet.py              # TDnet適時開示
      earnings.py           # 決算発表予定
      themes.py             # テーマ・業種キーワードマッチング（追い風/逆風判定含む）
    analysis/               # 「AI分析」を担うルールベースの考察エンジン一式
      llm_enhancer.py       # Claude API任意連携（ANTHROPIC_API_KEY設定時のみ有効）
      models.py             # 分析結果の共有データクラス（AnalysisBundle 等）
      scenario.py           # 強気/中立/弱気の3シナリオ（確率・理由・注目指標）
      causal_chain.py       # マクロの因果フロー1本＋個別の因果チェーン3〜5本
      news_ranking.py       # ニュースランキング（理由/影響市場/影響業種つき）
      key_levels.py         # 今日見るべき指標（節目ラインとの比較）
      themes_forecast.py    # テーマ別ランキングと1週間/1か月/3か月の見立て
      sector_ranking.py     # 業界ランキングTOP10
      stock_ranking.py      # 個別株ランキング（日本株/米国株TOP10）
      watchlist_analysis.py # 保有・監視銘柄の毎朝分析（今日/1週間/1か月/長期）
      watchlist_quicklist.py # 今日のウォッチリスト（★評価＋1行理由）
      long_term_picks.py    # 長期投資アイデアTOP5
      sales_talk.py         # 営業トーク（4種類）
      sales_prep.py         # 営業準備（社長向け一言・富裕層向け話題・用語解説・雑談・Q&A）
      chat_topics.py        # 今日の会話ネタ
      events.py             # イベントの今日/今週/今月分類
      ai_summary.py         # 300文字以内のAIまとめ
    report/
      format_utils.py       # 数値整形・★評価・文字数トリムなどの共通ヘルパー
      sections.py            # 各セクションのMarkdown整形関数（builder.pyの肥大化防止）
      builder.py             # 19セクションのMarkdownレポート組み立て（詳細版・組み立て役のみ）
      mobile_builder.py      # 7セクションの短縮版レポート組み立て（スマホ向け）
      html_builder.py        # カードUI・色分け表示のHTML版レポート組み立て
      pdf.py                 # 将来のPDF化フック
  notifiers/                 # 将来のLINE/Discord/Slack/Telegram/メール通知拡張用インターフェース
    base.py                  # 共通インターフェース Notifier / NotificationPayload
    line_notify.py / discord_webhook.py / slack_webhook.py / telegram_bot.py / email_sender.py
                              # 各チャネルのスタブ実装（未実装・NotImplementedError）
  tests/
    factories.py             # テスト用フィクスチャ生成（複数テストファイルで共有）
    test_report_builder.py  # 詳細版レポート組み立てのオフラインテスト
    test_mobile_builder.py   # 短縮版レポート組み立てのオフラインテスト
    test_html_builder.py     # HTML版レポート組み立てのオフラインテスト
    test_analysis.py         # AI分析エンジン各モジュールのオフラインテスト
    test_notifiers.py        # notifiers/ インターフェースのオフラインテスト
    test_main.py             # --date オプション・latest/mobile/html生成のオフラインテスト
  output/                    # 生成されたレポートの保存先
    YYYY-MM-DD_market_brief.md    # 日付入りレポート（詳細版Markdown）
    latest_market_brief.md        # 最新レポート・詳細版（毎回上書き）
    mobile_market_brief.md        # 最新レポート・スマホ向け短縮版（毎回上書き）
    YYYY-MM-DD_market_brief.html  # 日付入りレポート（HTML版・カードUI）
    latest_market_brief.html      # 最新レポート・HTML版（毎回上書き）
```

## 免責事項

本ツールが生成するレポートは、無料で公開されている情報を機械的に収集・整理したものです。
内容の正確性・完全性・最新性を保証するものではありません。特定の金融商品の売買を推奨・勧誘
するものではなく、投資助言には該当しません。投資判断は必ずご自身の責任で、一次情報源を
確認の上行ってください。
