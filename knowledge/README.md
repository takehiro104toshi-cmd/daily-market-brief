# knowledge/ — Investment Intelligence OS vNext 知識資産

vNext（`src/intelligence/`）が参照する**人手管理の知識資産**を置く。
Rebuild Stage 1（2026-08-29）で旧`config.yaml`から COPY + NORMALIZE で移設した。

## 位置づけと同期ポリシー

- **旧`config.yaml`は削除・変更していない**。Legacy本番（main.py系）は従来どおり
  config.yamlのみを参照して動き続ける。
- 移行期間中の二重管理: 知識の変更は**本ディレクトリを正**とし、Legacy側へ反映が
  必要な場合のみ人手でconfig.yamlへ同期する（`docs/rebuild/MIGRATION_PLAN.md` Stage 1）。
- 生成データ・キャッシュ・実行時状態は置かない（それらは`data/`。知識=人が編集する宣言的資産のみ）。
- Secret・アカウントID・トークン等の識別情報は**一切置かない**。

## ファイル構成（1責務=1ファイル）

```
knowledge/
  causal_rules/        ニュース→業種影響の因果ルール（旧config: causal_rules）
    market.yaml        商品市況・セクター需要・テーマ需要のルール
    rates.yaml         金融政策・金利のルール
    fx.yaml            為替のルール
  theme_relations/     テーマ知識（旧config: macro_themes / durable_themes / theme_relations）
    themes.yaml        テーマ定義（label＋判定キーワード）と長期継続テーマ
    theme_graph.yaml   テーマ間の因果関係グラフ（Theme Map / Phase 6 の種）
  source_reliability/  情報源の信頼度・Tier（旧config: source_reliability ほか）
    source_tiers.yaml  ソース別信頼度とTier1-3正規化
    source_feeds.yaml  フィードカタログ（URL・検証状態。旧collectors 15ファイルから抽出）
  compass_dna/         Compass DNAのmachine-readable資産（Markdown仕様書は docs/compass_dna/）
    market_rules.yaml  Phase 0分析ルール（正本。docs側はPhase 0成果物として凍結）
```

## 共通メタデータスキーマ

各YAMLはトップレベルに以下を持つ:

| key | 必須 | 意味 |
|---|---|---|
| id | ✔ | ファイル識別子（例: `causal_rules.market`） |
| version | ✔ | セマンティックバージョン。内容変更時にインクリメント |
| description | ✔ | 1〜2行の説明 |
| source | ✔ | 出自（lineage）: どこから移設・抽出したか |
| status | ✔ | `active` / `draft` / `deprecated` |

ルール型エントリ（causal_rules・compass_dna）は各ルールに
`id`（ファイル横断で一意）と `confidence`（confirmed/likely/hypothesis）、
`status` を持つ。検証は `tests/intelligence/test_knowledge_assets.py`。

## してはいけないこと

- Legacy本番の挙動を変える目的でconfig.yamlの代わりにここを読み込ませる改修
  （StranglerのStage 3以降で、承認の上adapter経由で行う）
- 機械生成した大量ルールの無審査投入（人が読んでレビューできる粒度を保つ）
