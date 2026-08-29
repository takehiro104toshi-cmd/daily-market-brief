# MIGRATION_PLAN — 段階移行計画（既存を壊さない）

Legacy Audit & Greenfield Rebuild Design 成果物（2026-08-29）。

大前提:
- **本番が生きている**: GitHub Actionsが毎日最大12回 main へ自動コミットする（07:30〜17:35 JST）。
- **NO BIG-BANG DELETE**: 旧コードの大量削除・移動は行わない。隔離は新系稼働確認後。
- 運用変更: 今後はClaude Codeが edit→test→commit→push まで実施。危険な変更（大規模削除・Secrets変更・本番CI変更・履歴書き換え・デプロイ）は**事前承認必須**。

---

## 1. 移行戦略の骨子 — Strangler Fig（並走置換）

旧パイプラインを止めずに、新中核（`src/intelligence/`）を**横に**建て、
接続点を1つずつ新系へ切り替える。切替のたびに旧経路はフォールバックとして残す
（このリポジトリ自身の `_safe_call`／縮退設計の流儀をそのまま移行にも適用する）。

```
Stage 0  設計確定（本タスク）→ ユーザー・監督者承認
Stage 1  新中核の骨組み＋知識資産の移設（旧系無変更）
Stage 2  新Evidence/Data Bankを「並走生成」（旧レポートは従来通り）
Stage 3  旧レポートに新系産セクションを1枚ずつ差し込み（adapter経由）
Stage 4  新Compass/Briefが主、旧セクションは順次退役
Stage 5  旧コードをsrc/legacy/へ隔離 → 清掃（要承認）
```

## 2. 安全規約（全Stage共通）

1. mainへの変更は必ずfeatureブランチ→pytest全通過→push。CI workflow・config.yamlの本番挙動に触れる変更は事前承認。
2. スロット実行と競合しないよう、CI workflowを変更する場合はスロット間の時間帯に行い、直後のスロットの成功を確認する。
3. 旧テスト451件は**削除せず常時グリーン維持**（旧系凍結の担保）。新系テストは`tests/unit/`等へ追加。
4. 新系の失敗が旧レポート生成を止めない: 新系呼び出しはすべて`_safe_call`相当でラップ。
5. データファイル（data/）のスキーマ変更は追記互換のみ。既存JSONの書き換えはバックアップ併設。

## 3. Stage別の作業内容

### Stage 1 — 骨組みと知識の移設（旧系への影響: ゼロ）
- `src/intelligence/`パッケージ新設（空の骨格＋スキーマ定義）。
- `knowledge/`新設: config.yamlから causal_rules / theme_relations / macro_themes / durable_themes / source_reliability を**コピー**して正規化YAML化（config.yaml側は当面そのまま残す＝旧系は無変更で動き続ける。二重管理期間はknowledge/側を正とし、変更はknowledge/→configへ同期）。
- 旧collectors Family Aの15 URL＋Tierを `knowledge/source_feeds.yaml` へ抽出。
- 対応ロードマップ: P1-1, P1-3, P1-6。

### Stage 2 — 並走生成（旧系への影響: 実行時間の微増のみ）
- 新sources層で実フィード死活確認（Reuters死亡確認・Atom問題の実測を含む）→ フィード表を実態へ更新。
- 新fetcher＋Evidence化をmain.pyの**末尾に追加の1ステップ**として呼び出し（_safe_callラップ・失敗しても旧レポートに影響なし）、`data/evidence/YYYY-MM-DD.jsonl`と`data/market_bank/`を毎日蓄積開始。
- CIコミット対象に上記2ディレクトリを追加（1行追加のみ・要承認対象外の軽微変更として提案→承認後実施）。
- 対応: P1-2, P1-4, P1-5, P1-7, P1-8, P2-1（データ蓄積の先行開始はREBUILD_ROADMAP提案1）。

### Stage 3 — 差し込み置換（adapterパターン）
- `intelligence/adapters/legacy_bundle.py`: 新系出力→旧`AnalysisBundle`フィールドへの変換器。
- 置換順（依存が浅く検証しやすい順）:
  1. data_freshness/analysis_confidence（観測系。新Evidence統計で算出）
  2. news_ranking（新news store＋ルールYAMLで採点、旧スコアラーと数日間並記比較）
  3. market_regime/breadth/cross_market（新market storeの派生指標で算出）
  4. scenario系→新prediction engine（horizon・検証条件付き記録開始＝Phase 5の実データ蓄積開始）
- 各置換は「新旧併記→乖離レビュー→旧を非表示化」の3手で行い、いつでも旧へ戻せる。

### Stage 4 — 新レポートが主役へ
- 新Compass Generator/Morning Briefを別出力（`output/v2/`または新index）として生成・並走。
- Pages導線を新版へ切替（**要承認**）。旧HTMLは`legacy.html`として一定期間残す。
- 通知本文を新Brief 30秒版へ切替。

### Stage 5 — 隔離と清掃（すべて要承認）
- `src/analysis`・`src/report`の退役済みモジュールを`src/legacy/`へ移動、旧テストを`tests/legacy/`へ。
- 死蔵資産の削除: `src/date/`、`notifiers/line_notify.py`、`report/pdf.py`、スタブnotifiers。
- output/肥大対策の実施（§5参照）。

## 4. ロールバック手順

- Stage 2まで: 追加ステップの呼び出し1行を外すだけで完全に旧状態。
- Stage 3: adapterの各差し込みはフラグ（config `rebuild.use_new_<name>: false`）で個別に旧実装へ戻す。
- Stage 4: Pagesのindex切替はワークフローの1行なので、revert1コミットで旧UIへ戻る。

## 5. 別途方針決定が必要な事項（提案付き・要ユーザー承認）

| # | 事項 | 提案 |
|---|---|---|
| 1 | output/ 214MB・毎日最大12コミットの肥大 | 新規分から「flat MD/HTMLは直近N日のみgit管理、履歴はPages artifactのみ」へ変更。過去分の履歴書き換え（filter-repo）は**行わない**（リンク・クローン影響が大きい） |
| 2 | cloudflare/private-insight-wrangler.toml（実KV id）と .wrangler/cache/wrangler-account.json（アカウントid・メール）が公開リポジトリで追跡中 | .gitignoreへ追加＋追跡解除（`git rm --cached`）。KV idの秘匿性は低いが公開不要情報。**過去履歴からの抹消はユーザー判断**（Cloudflare側で困る実害は小さい） |
| 3 | requirements.txtにanthropic欠落（CIでLLM磨き上げが常時無効） | 新系着手時にrequirementsへ追加するか、「ルールベースのみで良い」と明示決定するか選択 |
| 4 | 羅針盤学習機能の三重不一致（dir/format/場所） | 旧機能は修理せず、新research層（Phase 0.5と併せてPDF→テキスト化）で置換 |
| 5 | date/→data/・research/への整理 | Stage 5でリネーム（Git履歴保持のためgit mv）。それまで現状維持 |
| 6 | Secrets追加・変更（新系がLLM/API利用を広げる場合） | 都度事前承認 |

## 6. マイルストーンと完了判定

| Stage | 完了判定 |
|---|---|
| 1 | pytest全通過＋knowledge/一式がレビュー承認済み |
| 2 | 7日間連続でevidence/market_bankが自動蓄積・フィード死活レポートが出る |
| 3 | 置換4系統で新旧乖離レビュー完了・フラグで新系デフォルト化 |
| 4 | 新Briefが7日間連続配信・ユーザー受入OK |
| 5 | legacy隔離後もpytest（新体系）グリーン・Pages正常 |
