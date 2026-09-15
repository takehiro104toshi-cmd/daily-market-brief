# GIT_HISTORY_EXPOSURE_AUDIT — Git履歴露出監査（READ ONLY実測）

Rebuild Stage 1.6 成果物（2026-08-29）。
方法: 作業クローンを`--depth=1000`で完全履歴化（`origin/main`=**437コミット**まで取得。
shallowでないことを確認）し、`git log --all --diff-filter=A`・`git rev-list --all --objects`・
blobパターンスキャンで実測。**機密の内容そのものは本書に転載しない**（パス・コミットID・
サイズ・種別のみ）。

> 訂正: Stage 1.5以前の監査で「51コミット・2026-08-20に履歴squash」と記載したのは
> **shallowクローンの見え方による誤認**。実際の履歴は437コミット・PDF追加は2026-07-07。

## 1. Compass PDF（CONFIDENTIAL_SOURCE）の履歴露出

| 項目 | 実測結果 |
|---|---|
| 追加コミット | **`128f4b9`（2026-07-07、message: "Add"）1コミットのみ**。10冊・計約14.6MBを一括追加 |
| 以後の変更/削除/リネーム | なし（当該パスに触れたコミットは追加の1件のみ。`date/rashinban/README.md`のみ`7cc1a0a` 2026-07-06で先行追加） |
| 到達可能なブランチ | `main`・`claude/investment-intelligence-phase0-rvdplu`（ローカル/リモート双方）＝**全ブランチ** |
| タグ / リリース | **なし**（`git tag`空・GitHub Releases/Tags API=空） |
| Git LFS | **不使用**（.gitattributesなし）。PDFは通常blobとして履歴パックに格納 |
| GitHub Pages artifact | **混入なし**。workflowは`output/latest_market_brief.html`と`output/history/`のみを`pages-site/`へコピー（workflow 171-182行）。PDFはコピー対象外 |
| Actions artifact | pages-site（upload-pages-artifact）以外のartifactアップロードなし → **混入なし** |
| Release assets | リリース自体が存在しない → **なし** |
| 生成HTMLからの参照 | 「rashinban」への言及は学習ステータスカードの見出しテキスト1箇所のみ。**PDFへのリンクなし**（HTML内の.pdfリンクは外部ECB資料のみ） |

**結論（露出経路）**: 公開経路は (1) `git clone`／`git fetch`、(2) GitHub Web UI、
(3) `raw.githubusercontent.com` の3つ。Pages・Actions・Releaseは非該当。
現在ツリーからはStage 1.6でtracking解除済みだが、**履歴（コミット`128f4b9`以降の全履歴）
経由では引き続き取得可能**（除去は`SECURITY_REMEDIATION_PLAN.md` §3、要ユーザー承認）。

## 2. Secret/credentialの履歴スキャン

### daily-market-brief（全437コミット・output/とバイナリを除く2,368blobを走査）

検査パターン: Anthropic鍵（sk-ant-）・AWS鍵（AKIA）・GitHub PAT（ghp_等）・
Bearerトークン・秘密鍵ブロック・Slackトークン・Subscription-Key=値・appId=値・
LINE/SMTP資格情報の直書き。

**結果: 全パターン0件**。Secretは一貫してGitHub Secrets→env経由で扱われており、
履歴上のcredential露出は確認されなかった。

### article-intelligence-data-tank（READ ONLY・現行ツリーのdata/published/config走査）

- APIキー値のクエリ文字列露出: **0件**（`Subscription-Key=<値>`・`appId=<値>`パターンなし）
- コミット済みstatistics/cursorsに当該パラメータ名の出現: **0件**
  → Stage 1.5指摘の「T7: Secret-in-URLがエラーログ経由でpublicコミットされ得る経路」は
  **実流出には至っていない**（コードに残る潜在経路。tankはREAD ONLYのため未修正。
  vNext移植時にヘッダ認証＋redactionへ修正することがASSET_SELECTION_MATRIXの移植条件）
- Anthropic鍵・Bearer・実メール: 0件（メールはテスト用example.comのみ）

## 3. 識別子ファイルの分類（値は記載しない）

| ファイル | 内容種別 | 分類 | 判定 |
|---|---|---|---|
| `cloudflare/private-insight-wrangler.toml` | KV namespace id（32hex 1件） | SENSITIVE_IDENTIFIER | credentialではない（悪用にはアカウント認証が別途必要）。**Stage 1.6でtracking解除済み**。履歴には残存 |
| `cloudflare/.wrangler/cache/wrangler-account.json` | Cloudflareアカウントid（32文字）＋アカウント表示名（36文字） | SENSITIVE_IDENTIFIER | 同上。tracking解除済み。履歴には残存 |
| GitHubユーザー名・publicリポジトリURL（両repo各所） | — | PUBLIC_IDENTIFIER | 対応不要 |
| Worker URL（`config.yaml` private_insight_intake.api_url） | workers.devサブドメイン | SENSITIVE_IDENTIFIER（低） | エンドポイントは認証必須設計のため実害小。knowledge/への持込禁止をテストで担保済み。扱いは要判断（残置可） |

## 3.5 Stage 1.7追記（履歴除去の進捗）

- 承認A/Cに基づくfilter-repo除去のDRY RUNが完了（対象12パス・コミット444本保持・
  PDF/識別子objects 0・無関係資産保持・テスト492 passed。
  詳細: `HISTORY_REMEDIATION_EXECUTION.md` §4）。
- **リモート履歴は本書§1の露出状態のまま**（force pushが実行環境の権限ブロックで保留。
  再開手段は同 §5）。push完了後に`POST_REWRITE_VERIFICATION.md`の実測を記入し、
  本書の露出結論を「除去済み（GitHub残存リスク除く）」へ更新する。

## 4. ROTATION判定

**ROTATION_REQUIRED: なし。**
実credential（APIキー・トークン・パスワード）の履歴・publicログへの露出は
両リポジトリとも確認されなかった。識別子（account id / KV id / 表示名）はSecretではなく、
rotationの対象外（KV namespace再作成等は費用対効果が乏しく不要と判断。
最終判断はユーザーに委ねる）。
