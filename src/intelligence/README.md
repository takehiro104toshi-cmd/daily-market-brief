# src/intelligence/ — vNext パッケージマップ

Rebuild Stage 1（2026-08-29）で作成。各サブパッケージの責務・境界は各`__init__.py`の
docstringに記載（それが正）。実装はPhase 1以降。ここではcoreの契約と骨格のみを持つ。

| package | 担当Phase | 一言 |
|---|---|---|
| core/ | 全Phase | 共有ドメイン型（types.py）と抽象契約（contracts.py）。実装なし |
| sources/ | 1 | 外部からの取得のみ（RSS/API/公式）。解釈しない |
| evidence/ | 1 | 文単位のFACT/ANALYSIS/FORECAST化と出典管理 |
| market/ | 2 | 市場時系列（CORE/SUPPORT/CONTEXT）と派生指標 |
| news/ | 2 | 構造化ニュース（News Bank）と重複統合 |
| entities/ | 2 | 企業・コード・業種・テーマの名寄せ |
| themes/ | 6 | テーマグラフとEmerging検出 |
| predictions/ | 5 | 予測の記録・答え合わせ・較正 |
| thesis/ | 9 | Watchlist×投資仮説の追跡 |
| screening/ | 8 | 長期候補スクリーニング |
| reports/ | 3-4 | Compass Generator / Morning Brief組版 |
| personalization/ | 10 | 興味学習と「今日読むべきニュース」選定 |

Legacyへのimportは禁止（`src/intelligence/__init__.py`と境界テスト参照）。
知識資産は `knowledge/`、生成データは `data/`（vNext分はgit非管理方針）に置く。
