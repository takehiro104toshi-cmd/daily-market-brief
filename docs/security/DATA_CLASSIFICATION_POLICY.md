# DATA_CLASSIFICATION_POLICY — データ分類と取り扱い規則

Rebuild Stage 1.6 制定（2026-08-29）。Investment Intelligence OSプロジェクトの正式ルール。
執行手段: `tests/intelligence/test_confidential_guard.py`（機械検査）＋本ポリシー（運用判断）。

## 1. 分類定義と取り扱いマトリクス

| 分類 | 定義・例 | Git tracking | Public repo | Cloud storage | LLM送信 | ログ出力 | 派生メタデータ |
|---|---|---|---|---|---|---|---|
| **PUBLIC** | 公開情報（公開RSS見出し・公表統計・公開株価・生成レポートの公開部分） | ✔ | ✔ | ✔ | ✔ | ✔ | ✔ |
| **INTERNAL_PROJECT** | プロジェクト内部の設計・知識・コード（docs/、knowledge/、src/） | ✔ | ✔（現行運用） | ✔ | ✔ | ✔ | ✔ |
| **PRIVATE_RESEARCH** | ユーザー個人の研究メモ・Watchlist・行動ログ・予測記録 | ✔（**privateリポジトリのみ**） | ✘ | 承認された保管先のみ | 目的内で可 | 最小限 | ✔ |
| **CONFIDENTIAL_SOURCE** | 第三者の社外秘資料（**羅針盤PDF**、有料記事本文） | **✘** | **✘** | **✘**（暗号化KV等の承認済み経路除く） | **✘（明示承認なしでは禁止）** | **✘**（存在・ファイル名のみ可） | **✔（§3の条件下）** |
| **SECRET** | APIキー・トークン・パスワード・秘密鍵 | **✘** | **✘** | Secret管理機構のみ（GitHub Secrets / Worker Secrets / env） | ✘ | ✘（名前のみ可・値は禁止） | ✘ |

補助分類（識別子。Secretではないが公開不要）:

| 分類 | 例 | 規則 |
|---|---|---|
| **SENSITIVE_IDENTIFIER** | Cloudflareアカウントid・KV namespace id・個人メールアドレス | Git tracking禁止（今回是正）。ログ・レポートへは種別のみ記載し値を書かない |
| **PUBLIC_IDENTIFIER** | GitHubユーザー名・publicリポジトリURL・公開フィードURL | 制限なし |

## 2. SECRET取り扱い規則（SECRET_HANDLING）

1. 供給経路はenv変数（GitHub Actions Secrets → env / Cloudflare Worker Secrets）のみ。
   コード・config・knowledge・ドキュメントへの直書き禁止。
2. **HTTPでの送出はヘッダのみ**。クエリ文字列への鍵の付与は禁止
   （旧tank source_adaptersの教訓。エラーメッセージ経由でログ・publicコミットへ漏れる）。
3. 例外・エラーメッセージは記録前にredaction（URL・ヘッダ値を落とす）。
   例外の**型名のみ**記録する方式（Legacy private_insight_clientの流儀）を標準とする。
4. Secretのrotationはユーザーのみが実施する（Claude Codeは提案までを行い、勝手にrotateしない）。
5. 機械検査: knowledge/へのSecret様文字列混入はテストで検出
   （sk-ant / AKIA / ghp_ / Bearer / Subscription-Key= / appId= / メールアドレス等）。

## 3. 派生データ（Derived Data）の規則

CONFIDENTIAL_SOURCE（羅針盤PDF等）から作ってよいもの／いけないもの:

| 派生物 | 可否 | 例 |
|---|---|---|
| 抽象化された分析ルール・思考パターン | **✔**（INTERNAL_PROJECT扱い） | `knowledge/compass_dna/market_rules.yaml`、ANALYSIS_RULE_CATALOG の一般化ルール |
| 構成・データ分類・統計（non-verbatim） | ✔ | REPORT_STRUCTURE_SPEC、出現回数・日付・ページ番号の参照 |
| 検証結果（SUPPORTED/CONTRADICTED等） | ✔ | Phase 0.5成果物 |
| **長い原文引用** | **✘** | 段落転載・記事全文 |
| **ページ画像・PDF再配布** | **✘** | スクリーンショット、Pages/artifact/外部サービスへの掲出 |
| 短い引用（出典検証に必要な最小限） | 条件付き可 | 数十字以内・INTERNAL文書内のみ・公開出力へは載せない |

既存 `docs/compass_dna/` 一式はこの基準で点検済み: 一般化ルール・構成仕様・最小限の
要約参照で構成されており**適合**（原文の長文転載・画像なし）。

## 4. LLM送信規則

- PUBLIC / INTERNAL_PROJECT: 可。
- PRIVATE_RESEARCH: ユーザー自身の目的の範囲で可。
- **CONFIDENTIAL_SOURCE: 本文・画像のLLM API送信は、ユーザーの明示承認がある場合のみ**
  （承認例: Phase 0でのPDF解析はユーザー指示に基づき実施済み。Phase 0.5も同様の指示を
  承認とみなす。それ以外の自動パイプラインへの組み込みは都度承認）。
- SECRET: いかなる形でも送信禁止。

## 5. 実行時生成データ（Git保存の原則）

vNextでは以下を**Gitへ永久保存しない**（`data/vnext/` は.gitignore済み）:
runtime生成ファイル・履歴DB・キャッシュ・生記事・PRIVATE_RESEARCH。
Legacyの既存 `output/`（214MB）は本ポリシーの遡及適用外とし、cleanupは
`SECURITY_REMEDIATION_PLAN.md` §5 の移行計画による（今回大量削除しない）。
