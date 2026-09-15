# VNEXT_RECONCILIATION — Stage 1 Foundationの横断監査後再評価

Rebuild Stage 1.5 成果物（2026-08-29）。
Stage 1で作成したvNext Foundation（PROVISIONAL）を、tank横断監査の結果で再評価する。

## 1. KEEP（変更不要と確認できたもの）

| 要素 | 判定根拠 |
|---|---|
| `src/intelligence/` パッケージ構成（12ドメイン） | tankの実装分割（fetch/parse/dedup/classify/store/publish）がsources/evidence/news/の境界と自然に対応。構成変更の必要なし |
| `core/types.py` の設計方針（小型frozen・No God Model） | tank models.pyも同思想（primitives・asdict可能）で相互検証された |
| `core/types.py` StatementType / Horizon / ForecastAttributes | tank private_insightのシナリオ設計（confidence上限・invalidation trigger・review date）と語彙が整合。ForecastAttributes.invalidation_conditionの妥当性が実例で裏付け |
| `core/contracts.py` 6契約（Clock/LLMProvider/4 Repository） | tankのinjectable transport・env駆動LLMという実践と一致。変更不要 |
| import境界テスト・Secretスキャンテスト | tankのT7（Secret-in-URLログ流出経路）を見た後では必須性がむしろ上がった |
| `knowledge/` のCanonical地位 | 三重管理（dmb config/tank config+sources/staleコピー）の解消先として横断監査で確定 |
| causal_rules / theme_graph / compass_dna ルール | tank側に競合資産なし。唯一無二の知識として維持 |
| `data/vnext/` git非管理方針 | tankがdata/をコミットして得た教訓（リポジトリ肥大・T7流出経路）を回避 |

## 2. CHANGE（Stage 1.5で実施した修正）

| 要素 | 変更 | 理由 |
|---|---|---|
| `knowledge/source_reliability/source_feeds.yaml` | v1.0.0（dmb由来24件）→ **v2.0.0（86件統合カタログ）** | tank sources.yaml（70件・richメタデータ）を正とし、dmb固有16件を追加。tank記事実績から**42ソースをverified化**（articles_observed付き）。「全件unverified」だったStage 1状態から大幅前進 |
| `knowledge/theme_relations/themes.yaml` | v1.0.0 → **v1.1.0**: en_aliases（tankスラッグ25件の対応表）＋unmapped_tank_slugs（20件） | tankコーパス3,056件と将来接続するための語彙ブリッジ。曖昧なものは対応付けず明示的にunmapped |
| `tests/intelligence/test_knowledge_assets.py` | URL検査をhttps必須→http(s)許容へ緩和＋en_aliases整合テスト追加（35→36件） | tank由来カタログにhttp 1件が実在するため。aliasesの参照整合を機械検査 |
| dmb `news.py` の扱い | Stage 1判定「Phase 1でMIGRATE」→ **REFERENCE_ONLY へ降格** | tank feed_parser（Atom/RDF対応・13テスト）が上位互換。wire prefix正規化のみtank系へ取り込む |

## 3. ADD（Stage 1.5で追加が確定した設計要素・実装はPhase 1-2）

1. **Phase 2 NewsItemスキーマはtank記事モデル（約70フィールド）を出発点とする**。
   EvidenceRecord（文単位）とNewsItem（記事単位）の関係: NewsItemは記事メタデータ＋
   複数EvidenceRecordへの参照、という2層で設計する（tankは記事単位のみ、Compass DNAは
   文単位を要求——両方必要というのが横断監査の結論）。
2. **date_inferred / raw_published_at の規律**（tank date_quality由来）をEvidence仕様へ
   取り込む: 日時が補正された事実自体をデータとして残す。
3. **取得層の必須要件**（tankの実践＋事故からの教訓）:
   条件付きGET＋cursor、403/404/429非再試行、連絡先入りUA（env注入）、
   **認証はヘッダのみ・エラーログのredaction必須**（T7再発防止）、行単位quarantine（T6教訓）。
4. **テストCIの必須化**: tankはテスト184件を持ちながらCIで回しておらず、起動不能バグ（T1）が
   5週間検知されなかった。vNextはStage 2でCIにpytestステップを追加する（Legacy workflowの
   変更となるため実施時に承認を取る）。
5. `knowledge/prompts/`（プロンプト版管理置き場）をPhase 3着手時に新設し、tank
   private_insightプロンプトを初期資産としてMIGRATEする（今回は非実装）。

## 4. REMOVE_LATER（vNext内で将来整理するもの）

| 要素 | 時期 | 理由 |
|---|---|---|
| `source_tiers.yaml` のフィード由来エントリ | Phase 1でLegacy名前引きが不要になった時 | catalogのtrust_scoreへ一本化（現在はdedupe用の名前→信頼度引きにLegacyが依存するため残置） |
| `source_feeds.yaml` の `reference_only`/`skipped` 方針記録 | Phase 2でソースガバナンス文書へ移す時 | カタログとポリシーの分離 |

## 5. 最終vNextアーキテクチャへの修正案まとめ

TARGET_ARCHITECTURE.md への影響は**軽微**（構成・データフロー・契約は維持）。
変更点は「Phase 1-2の実装母体をtank系コードのMIGRATEで賄う」という実装戦略の具体化のみ。
REBUILD_ROADMAP.md のP1-2/P1-4（fetcher・パーサー新規実装）は「tankからの移植＋修正」へ
読み替える（工数減）。P2-4（NewsItem）はtankスキーマ出発点で確定。
これらはPhase 1計画書作成時に反映する（ロードマップ自体の順序変更はなし）。
