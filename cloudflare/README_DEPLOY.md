# Rashinban Private Insight Vault — Cloudflare Worker デプロイ手順（詳細版）

このZIPには2つのファイルが入っています。

- `private-insight-worker.js` … Workerの本体コード（このまま使います）
- `private-insight-wrangler.toml.example` … 設定ファイルの雛形（コピーして自分用に書き換えます）

以下は上から順番にPowerShellへコピペしていけば完了する手順です。
「これは何？」を各ステップに書いています。

---

## 事前準備：Node.jsが入っているか確認

PowerShellを開いて（スタートメニューで「PowerShell」と検索）、次を実行します。

```powershell
node -v
```

`v18` 以上のバージョン番号が出ればOKです。
「認識されません」と出た場合は https://nodejs.org/ja からLTS版をインストールしてから続けてください（インストール後はPowerShellを一度閉じて開き直す）。

---

## 手順1：ZIPを展開してフォルダへ移動

エクスプローラーでこのZIPを展開し、`D:\daily-market-brief\cloudflare\` フォルダの中に
2つのファイルをコピーしてください（既存の `private-insight-worker.js` を上書きでも同じ内容です）。

PowerShellで移動します。

```powershell
cd D:\daily-market-brief\cloudflare
```

---

## 手順2：wrangler（Cloudflareのデプロイツール）を入れる

```powershell
npm install -g wrangler
```

数十秒〜数分かかります。終わったら確認：

```powershell
wrangler -v
```

バージョン番号が出ればOKです。

---

## 手順3：Cloudflareアカウントにログイン

```powershell
wrangler login
```

- ブラウザが自動で開きます（開かなければ表示されたURLを手動で開く）。
- Cloudflareのアカウントでログイン（アカウントがなければこの画面で無料作成できます）。
- 「Allow」を押すとブラウザに「成功しました」的な画面が出て、PowerShellに戻れます。

---

## 手順4：データ保存用のKV（保管庫）を作る

```powershell
wrangler kv namespace create INSIGHT_KV
```

実行すると、こんな出力が出ます（idの部分は毎回違う値です）。

```
[[kv_namespaces]]
binding = "INSIGHT_KV"
id = "1a2b3c4d5e6f7890...（英数字の長い文字列）"
```

**この `id = "..."` の中身（クォートの中の文字列だけ）をメモ帳などに控えてください。**
次の手順で使います。

---

## 手順5：設定ファイルを自分用に作る

```powershell
copy private-insight-wrangler.toml.example private-insight-wrangler.toml
notepad private-insight-wrangler.toml
```

メモ帳が開くので、次の行を探して：

```toml
id = "REPLACE_WITH_YOUR_KV_NAMESPACE_ID"
```

`REPLACE_WITH_YOUR_KV_NAMESPACE_ID` の部分だけを、手順4で控えたidに置き換えます。
（クォート `"` は残す。例: `id = "1a2b3c4d5e6f7890..."`）

`ALLOWED_ORIGIN` の行はご自身のGitHub PagesのURLになっているか確認してください
（例: `https://takehiro104toshi-cmd.github.io`）。違う場合は書き換えます。

保存して閉じます（メモ帳の「上書き保存」）。

---

## 手順6：秘密の値（3つ）を設定する

Workerに「合言葉」「認証トークン」「暗号鍵」の3つを安全に登録します。
それぞれ1回ずつ、値を作ってから登録という流れです。

### 6-1. パスフレーズ（合言葉）を決めてハッシュ化する

まず好きな合言葉を決めてください（例：スマホから記事を送るときに毎回入力する言葉。
他人に推測されにくい、ある程度長いフレーズがおすすめです）。

次のコマンドの `"あなたのパスフレーズ"` の部分を実際の合言葉に書き換えて実行します。

```powershell
$p = [Text.Encoding]::UTF8.GetBytes("あなたのパスフレーズ")
$hash = -join([Security.Cryptography.SHA256]::Create().ComputeHash($p) | ForEach-Object { $_.ToString("x2") })
Write-Host $hash
```

英数字64文字が表示されます。これをコピーして、次のコマンドを実行し、
聞かれたら **今表示された64文字の値** を貼り付けてEnterします
（合言葉そのものではなく、ハッシュ化した64文字の方です）。

```powershell
wrangler secret put PASSPHRASE_SHA256 -c private-insight-wrangler.toml
```

> 合言葉そのもの（例：「あなたのパスフレーズ」）は、スマホからレポート画面で
> 転送ボタンを押すときに入力する値として、あなた自身が覚えておいてください。
> （Workerにはハッシュだけを登録するので、合言葉の平文はどこにも保存されません。）

### 6-2. 分析パイプライン用のトークンを作る

```powershell
$bytes = New-Object byte[] 32
[Security.Cryptography.RandomNumberGenerator]::Create().GetBytes($bytes)
$token = [Convert]::ToBase64String($bytes) -replace '[+/=]',''
Write-Host $token
```

表示された文字列をコピーして登録：

```powershell
wrangler secret put INSIGHT_API_TOKEN -c private-insight-wrangler.toml
```

聞かれたら貼り付けてEnter。**この値は後で daily-market-brief と
article-intelligence-data-tank 両方のGitHub Secretsにも同じものを登録するので、
メモ帳に控えておいてください。**

### 6-3. 本文の暗号化キーを作る

```powershell
$bytes32 = New-Object byte[] 32
[Security.Cryptography.RandomNumberGenerator]::Create().GetBytes($bytes32)
$key = [Convert]::ToBase64String($bytes32)
Write-Host $key
```

表示された文字列をコピーして登録：

```powershell
wrangler secret put ENCRYPTION_KEY_B64 -c private-insight-wrangler.toml
```

聞かれたら貼り付けてEnter。

---

## 手順7：デプロイする

```powershell
wrangler deploy -c private-insight-wrangler.toml
```

成功すると、最後にこんな行が出ます。

```
Published private-insight-vault
  https://private-insight-vault.あなたのサブドメイン.workers.dev
```

**このURL（`https://...workers.dev` の部分）を必ずメモ帳に控えてください。**
次の手順2つで使います。

---

## 手順8：daily-market-brief 側に設定を反映する

1. `D:\daily-market-brief\config.yaml` を開き、`private_insight_intake:` の
   `api_url: ""` を次のように書き換えます（末尾に `/api/private-insight` を付ける）。

   ```yaml
   private_insight_intake:
     enabled: true
     api_url: "https://private-insight-vault.あなたのサブドメイン.workers.dev/api/private-insight"
   ```

2. GitHubの `daily-market-brief` リポジトリを開く →
   `Settings` → `Secrets and variables` → `Actions` → `New repository secret`
   - Name: `INSIGHT_API_TOKEN`
   - Value: 手順6-2で控えたトークン

3. `config.yaml` の変更をcommit・push。

---

## 手順9：article-intelligence-data-tank 側に設定を反映する

GitHubの `article-intelligence-data-tank` リポジトリを開く →
`Settings` → `Secrets and variables` → `Actions` → `New repository secret` を3回：

| Name | Value |
|---|---|
| `INSIGHT_API_URL` | `https://private-insight-vault.あなたのサブドメイン.workers.dev/api/private-insight` |
| `INSIGHT_API_TOKEN` | 手順6-2で控えた同じトークン |
| `ANTHROPIC_API_KEY`（任意） | Claudeで分析したい場合のみ。無ければルールベース分析で動きます |

---

## 手順10：動作確認

1. スマホでdaily-market-briefのレポートページを開く。
2. 「🧠 Rashinban Private Insight Vault」カードをタップして開く。
3. 適当な記事本文（テストなら何でも可）を貼り付け、手順6-1の**合言葉（平文）**を入力。
4. 「Data Tankへ転送して分析」を押す。
5. 「保存しました」と表示されればWorkerまで正常に届いています。
6. 管理画面で確認したい場合はブラウザで
   `https://private-insight-vault.あなたのサブドメイン.workers.dev/api/private-insight/admin`
   を開き、合言葉を入力すると一覧が見られます。
7. 分析結果は article-intelligence-data-tank の毎時 :11/:41 のワークフロー実行後に
   反映されます。次にdaily-market-briefのレポートが生成されたタイミングで
   「🔮 Private Research Future Outlook」カードに表示されます。

---

## うまくいかないときは

- `wrangler login` でブラウザが開かない → 表示されたURLをコピーして手動でブラウザに貼り付け。
- `wrangler deploy` でエラー → メッセージをそのままこのチャットに貼ってください。
- 「保存しました」が出ない → まず`api_url`の末尾が`/api/private-insight`になっているか、
  合言葉が手順6-1で決めたものと一致しているかを確認してください。
- 何度もやり直したい場合、Secretは同じコマンドを再実行すれば上書きされます
  （`wrangler secret put ...` をもう一度実行するだけ）。

## 注意

- 未設定のままでも既存レポートは従来どおり動きます（機能は無効のまま）。
- 合言葉・トークンをHTMLやリポジトリのファイルへ書かないでください（Worker Secretのみ）。
- 有料記事の本文は自分専用のprivate資料としてのみ保存されます。媒体の利用規約の
  範囲内でご利用ください。
