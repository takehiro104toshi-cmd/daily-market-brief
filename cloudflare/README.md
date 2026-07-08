# Cloudflare Worker（ワンタップ生成の中継バックエンド・v3.4）

GitHub Pages上のHTMLから「🚀 ワンタップで最新レポート生成」を押すと、この Worker が
GitHub Actions の `workflow_dispatch` を安全に起動します。**GitHub Token は Worker の
Secret にのみ保存**し、HTML・JS・レスポンスには一切出しません。

## 仕組み

```
[スマホのHTML(GitHub Pages)]  --POST /trigger-->  [Cloudflare Worker]  --workflow_dispatch API-->  [GitHub Actions]
        （Tokenを知らない）                         （Tokenをsecretで保持）
```

## セットアップ手順

### 1. GitHub Token を用意する（Fine-grained PAT 推奨）

- GitHub → Settings → Developer settings → Personal access tokens → Fine-grained tokens
- Repository access: **daily-market-brief のみ**
- Permissions:
  - **Actions: Read and write**
  - **Contents: Read and write**
- 生成された `github_pat_...` をコピー（このあと Worker の Secret に入れます。**HTMLやリポジトリには絶対に貼らない**）。

### 2. Worker をデプロイする

Cloudflareダッシュボード（Workers & Pages → Create → Worker）で新規Workerを作り、
`trigger-report-worker.js` の内容を貼り付けてデプロイします。
（wrangler CLIを使う場合は `wrangler.toml.example` を `wrangler.toml` にコピーして
`wrangler deploy`。）

### 3. Secret / 変数を設定する

Worker の Settings → Variables and Secrets で以下を設定します。
`GITHUB_TOKEN` は必ず **Secret（暗号化）** として登録してください。

| 名前 | 種別 | 例 |
|---|---|---|
| `GITHUB_TOKEN` | Secret | github_pat_...（手順1のトークン） |
| `GITHUB_OWNER` | 変数 | takehiro104toshi-cmd |
| `GITHUB_REPO` | 変数 | daily-market-brief |
| `GITHUB_WORKFLOW_FILE` | 変数 | daily-market-brief.yml |
| `ALLOWED_ORIGIN` | 変数 | https://takehiro104toshi-cmd.github.io |
| `WORKFLOW_REF` | 変数（任意） | main |

wrangler CLIなら：
```
wrangler secret put GITHUB_TOKEN
wrangler deploy --var GITHUB_OWNER:takehiro104toshi-cmd \
                --var GITHUB_REPO:daily-market-brief \
                --var GITHUB_WORKFLOW_FILE:daily-market-brief.yml \
                --var ALLOWED_ORIGIN:https://takehiro104toshi-cmd.github.io
```

### 4. config.yaml にエンドポイントURLを設定する

デプロイ後に発行される Worker のURL（例: `https://xxxx.yyyy.workers.dev`）を使い、
リポジトリの `config.yaml` を次のようにします。

```yaml
realtime:
  enabled: true
  provider: "cloudflare_worker"
  endpoint_url: "https://xxxx.yyyy.workers.dev/trigger"
  mode: "one_tap"
```

翌朝の生成（または手動Run workflow）以降、HTMLに「🚀 ワンタップで最新レポート生成」
ボタンが表示され、押すと Worker 経由で生成が始まります。

## API

- `POST /trigger`
  - 成功: `{"ok": true, "message": "workflow dispatched"}`（HTTP 200）
  - 失敗: `{"ok": false, "error": "..."}`（HTTP 4xx/5xx）
- CORSは `ALLOWED_ORIGIN` に一致するOriginのみ許可。

## セキュリティ上の約束

- `GITHUB_TOKEN` はコードに直書きせず、Worker の Secret からのみ参照します。
- Token はレスポンス・エラーメッセージ・ログに一切含めません（GitHubのエラーは要約のみ返却）。
- 許可Origin以外からのリクエストは拒否します。
- HTML/JS/GitHub Pages側には Worker のエンドポイントURLしか置きません（Tokenは置かない）。

## トラブルシューティング

- **ボタンを押しても「authentication failed」**: Tokenの権限（Actions/Contents=Read and write）と
  対象repoスコープを確認。Fine-grained tokenの有効期限切れにも注意。
- **「workflow or repository not found」**: `GITHUB_OWNER` / `GITHUB_REPO` /
  `GITHUB_WORKFLOW_FILE` の綴りを確認（ワークフローファイル名は `.yml` まで）。
- **「invalid ref」**: `WORKFLOW_REF`（既定 main）が実在するブランチか確認。
- **ブラウザのコンソールにCORSエラー**: `ALLOWED_ORIGIN` がGitHub PagesのURLと完全一致
  しているか確認（末尾スラッシュ無し・httpsで）。
- **ボタンが出ない**: `config.yaml` の `realtime.enabled: true` と `endpoint_url` を確認し、
  レポートを再生成（HTMLに反映されるのは次回生成後）。
