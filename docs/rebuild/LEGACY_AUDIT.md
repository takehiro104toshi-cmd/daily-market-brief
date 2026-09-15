# LEGACY_AUDIT — 旧Daily Market Brief資産の全体監査

Legacy Audit & Greenfield Rebuild Design 成果物（2026-08-29）。
調査方法: リポジトリ全ファイル走査（Python約25,500行・51コミット・全ブランチ）、
main.py/config.yaml/CI workflow精読、src/collectors・src/analysis・src/report・
notifiers・cloudflare・tests・data/date/outputの系統別監査。

---

## 1. Current Architecture（現状の実像）

**「毎日6回、GitHub Actionsで動く単一パイプラインのレポート生成器」**。稼働中（output/は2026-08-29分まで自動コミット済み）。

```
GitHub Actions cron（6スロット＋15分後の回復実行6回、UTC）
  → scripts/resolve_report_schedule.py（cron文字列→slot解決）
  → main.py generate_report()  … 1,088行の逐次オーケストレーター
      ①収集: src/collectors 30モジュール（RSS/yfinance/Stooq/TDnet/EDINET/FRED）
      ②分析: src/analysis 50モジュール（~40エンジンを_safe_callで逐次実行）
      ③集約: AnalysisBundle（43フィールドのgod object、models.pyに59 dataclass）
      ④組版: src/report（Markdown+3,087行のf文字列HTML+mobile版）
      ⑤保存: output/へMD+HTML書き出し → CIがmainへコミット
      ⑥配信: GitHub Pages（latest→index.html）、メール/LINE通知
  外部インフラ: Cloudflare Worker×2（ワンタップ実行relay・Private Insight Vault）、
                別リポジトリ article-intelligence-data-tank（Published Package取得）
```

設計上の一貫した美点（継承すべき思想）:
- **全収集・全分析が`_safe_call`でgraceful degradation**。ネットワーク全滅でも「取得不可」入りの完全なレポートが出る。
- **捏造しない規律**: 欠測は「取得不可」「分析材料不足」と明示。LLMは磨き上げのみ・数値の創作禁止・キー無しで完全動作するフォールバック。
- 後方互換の徹底（デフォルト値付きフィールド追加、スロット未指定時は従来動作）。
- atomic write・二重生成防止・欠損回復・HTML妥当性検証などの運用信頼性工学。

## 2. Historical Purpose（歴史的経緯）

- v1.x〜v4.6までCHANGELOG駆動で増築された「Morning Strategy Report」ツール。読者は本人（営業職）で、営業トーク・お客様向けコメント等のセクションが厚い。
- Investment Intelligence OSの原型となる思想（因果関係・出典・検証・テーマ）は既に萌芽している: SourceRegistry、source_trust（Tier）、investment_journal（答え合わせ）、theme_learning（テーマ勝率）、causal_rules/theme_relations（config内知識）。
- ただし増築の方法が「AnalysisBundleへフィールド追加＋セクション追加＋test_vX_Y.py追加」の一方向で、**アーキテクチャ境界が形成されないまま50エンジンに達した**。

## 3. Coupling（結合の実態）

| 結合 | 実態 | 影響 |
|---|---|---|
| AnalysisBundle神オブジェクト | 43フィールド。44ファイル＋main.pyがmodels.pyをimport。構築後にmutateされ（analysis_confidence等を後代入）、builderが読む | フィールド改名が~45ファイルへ波及。部分再利用の最大障壁 |
| analysis→report逆依存 | **50中33ファイルが`report.format_utils`をimport**（find_quote/stars/fmt_price等）。データアクセサが表示層に居る | analysis層は今のままでは切り出せない |
| analysis→collectors型依存 | 34ファイルがQuote/Headline等の型と一部関数（_normalize_title等の私有関数含む）をimport | 型を共有スキーマ層へ移せば解消可能 |
| main.py配線 | ~40エンジンの呼び出し順・引数の受け渡しがすべてmain.pyにハードコード | パイプライン定義がコードに埋没 |
| 外部リポジトリ結合 | article-intelligence-data-tank（raw.githubusercontent直読み）、Cloudflare Worker×2 | 相手側の変更で無警告デグレード（設計上は安全にフォールバック） |

## 4. Technical Debt（技術的負債の要点）

1. **html_builder.py 3,087行のf文字列HTML**（テンプレートエンジン不使用、CSS330行+JS215行をPython文字列で内包）。1ファイル≒600KBのHTMLを生成。
2. **collectors Family A = 15ファイルの構造コピー**（`{name,url}`表＋RELIABILITY＋1行delegate）。実体は設定であり、コードである必要がない。全15エンドポイントは「実ネットワーク未検証」とdocstring自身が明記。
3. **テストが機能別でなくリリース別**（28ファイル中15がtest_vX_Y命名）。モジュール単位のリファクタ検証が困難。
4. **営業文言クラスタの重複**: sales_comments/okasan_sales_comments/sales_talk/sales_prep/call_priority/morning_meeting_commentの6モジュール~660行が同一入力→同種出力の再スライス。
5. **タクソノミーの二重化**: market_impact.pyがconfig.yamlのsectorsと別の私有セクター辞書を内蔵。
6. **output/ 214MB・392ファイルをgit管理**し1日最大12回コミット（無制限成長。最大のスケーリング負債）。
7. **依存二重管理**: pyproject.tomlとrequirements.txtの手動同期。既に乖離が実現（下記§5-3）。
8. `pdf.py`（pandoc前提・未配線）、`notifiers/line_notify.py`（抽象メソッド未実装でインスタンス化不能・名前衝突）、slack/discord/telegramのNotImplementedスタブ等の死蔵コード。

## 5. Dangerous Assumptions（危険な前提・不整合）

1. **`data`/`date`のtypoがインフラ化**: `src/date/`はsrc/dataのバイト同一の死にコピー（どこからもimportされない）。ルートの`date/`は羅針盤PDF等の実データを持つが、READMEの見出し自身が`# data/rashinban/`。
2. **羅針盤学習機能は不活性**: config.yaml `rashinban.dir: "data/rashinban"` は存在しないディレクトリを指し、loaderは.md/.txtのみ受理するのに実ファイルは`date/rashinban/`のPDF。**設定・形式・場所の三重不一致で一度も機能していない**。
3. **CIでLLM磨き上げは常に無効**: requirements.txtがanthropicを含まない（コメントアウト）ため、SecretsでANTHROPIC_API_KEYを渡していてもフォールバック固定。
4. **セキュリティ**: `cloudflare/private-insight-wrangler.toml`（実KV namespace id入り）と`cloudflare/.wrangler/cache/wrangler-account.json`（Cloudflareアカウントid・メールアドレス入り）が**公開リポジトリにgit管理されている**。.gitignore対象外。※秘密鍵・トークンそのものではないが、公開すべきでない識別子。対処は要ユーザー承認（MIGRATION_PLAN §6）。
5. **Reutersフィードはほぼ確実に死んでいる**（reutersagency.comの当該フィードは提供終了）。economic_calendarはconfigが空で常にno-op（195行が未使用）。無警報で腐る構造（フィード死活の検知・警告なし）。
6. Stooqフォールバックの`change`は当日始値比、yfinance経路は前日終値比——**同名フィールドで意味が異なる**。
7. news.pyはRSS2.0のみ対応でAtomフィードは静かに0件になる。
8. 学習ループの検証が全テーマ・全シナリオを**日経平均のみ**で答え合わせ（theme_learningの勝率は実質「地合い勝率」）。
9. 履歴ページ導線の断絶（schedule_statusの過去レポートリンクが自己アンカー）。EDINET v2はキー必須なのに「キー無しでも動く」前提。SEC UA要件違反リスク。

## 6. Reusable Assets（再利用価値の高い資産）

**A. 知識資産（最高価値・コードより価値が高い）**
- config.yaml内: `causal_rules`（羅針盤思考の一般化ルール）・`theme_relations`（テーマグラフの種）・`macro_themes`・`durable_themes`・`source_reliability`・`sectors`/`themes`辞書・`watchlist`
- `docs/compass_dna/`一式（Phase 0成果物）と`analysis_rules/market_rules.yaml`
- `date/rashinban/`の羅針盤PDF 10冊（研究資料）

**B. 運用インフラ（実戦検証済み）**
- CI workflow（6スロット+回復+並行制御+リトライ+Pages）と`report_schedule.py`＋`scripts/resolve_report_schedule.py`（純ロジック・時刻注入テスト済み）
- Cloudflare Worker×2（トークン隔離設計・暗号化KV）
- `_safe_call`/atomic write/HTML検証等の信頼性パターン

**C. コード（そのまま or adapter付きで再利用可）**
- `src/data/external_intelligence_client.py`（checksum・schema検証・注入可能Transport・最良品質）
- `news.py`のRSSパース＋重複統合、`market_data.py`のyfinance+Stooq二段フォールバック
- `source_trust.py`・`market_regime.py`・`analysis_confidence.py`・`data_freshness.py`（透明な計算・疎結合）
- `llm_enhancer.py`の縮退設計（実装は小さいので思想を継承して書き直しでも可）
- `translation.py`の永続キャッシュ方式
- notifiers（email/line実装分）
- `investment_journal.py`/`theme_learning.py`の**構造**（答え合わせループ。評価ロジックは要再設計）

**D. テスト資産**
- 451件のテストとtests/factories.py。時刻注入・ネットワーク不使用の作法は新系へ移植価値が高い（構成はリリース別→機能別へ再編が必要）。

## 7. Blockers（新設計へ進む上での障害）

1. analysis層のreport層への逆依存（33ファイル）— 切り出し前に共有スキーマ/フォーマッタ層の新設が必要。
2. AnalysisBundle経由の全結線 — 部分置換にはadapter（新Bundle→旧Bundle変換）が必要。
3. 稼働中パイプライン — 毎日12回mainにコミットが走るため、mainへの変更はスロット間の隙間で行い、必ず旧経路を温存する（MIGRATION_PLAN §2）。
4. output/の肥大 — 新設計の前にコミット対象の方針決定が必要（履歴の扱いは要ユーザー承認）。
5. Evidence概念の不在 — FACT/ANALYSIS/FORECASTはデータとして存在せず（報告書の文言のみ）、既存モデルの拡張では到達不能。Phase 1は新規実装が正当。
6. フィード未検証 — 新sources層の最初の仕事は現行15+9ソースの実地死活確認になる。
