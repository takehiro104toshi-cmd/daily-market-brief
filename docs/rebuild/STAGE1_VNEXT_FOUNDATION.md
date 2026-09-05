# STAGE1_VNEXT_FOUNDATION — vNext骨格と知識移設の実施記録

Rebuild Stage 1 成果物（2026-08-29）。監督判定 LEGACY_AUDIT_APPROVED /
GREENFIELD_REBUILD_AUTHORIZED を受けて実施。Phase 1本格実装は未着手（意図的）。

---

## 1. Created Structure（作成した構成）

```
src/intelligence/                 vNext中核（Legacy非依存。境界はテストで機械検査）
  __init__.py                     アーキテクチャ宣言・import境界ルール
  README.md                       パッケージマップ（package×Phase対応表）
  core/
    types.py                      共有ドメイン型: SourceTier / StatementType / Horizon /
                                  SourceMeta / ForecastAttributes / EvidenceRecord /
                                  MarketObservation / LLMResult（すべてfrozen・小型）
    contracts.py                  抽象契約(Protocol): Clock / LLMProvider /
                                  EvidenceRepository / MarketRepository /
                                  NewsRepository / KnowledgeRepository（実装なし）
  sources/ evidence/ market/ news/ entities/ themes/
  predictions/ thesis/ screening/ reports/ personalization/
                                  各`__init__.py`にpurpose/boundary/future responsibility
                                  を記載したdocstring-onlyパッケージ（空directoryなし）

knowledge/                        vNext知識資産（旧config.yamlからCOPY+NORMALIZE）
  README.md                       管理規約・メタデータスキーマ・同期ポリシー
  causal_rules/market.yaml        因果ルール14本（商品・セクター・テーマ需要）
  causal_rules/rates.yaml         同2本（金融政策）
  causal_rules/fx.yaml            同2本（為替）
  theme_relations/themes.yaml     テーマ定義29件＋durable_themes 7件
  theme_relations/theme_graph.yaml テーマ隣接グラフ37ノード
  source_reliability/source_tiers.yaml  ソース信頼度23件＋Tier1-3正規化
  source_reliability/source_feeds.yaml  フィードカタログ24本＋参照のみ/見送り方針
  compass_dna/market_rules.yaml   Phase 0分析ルール（正本をここへ移設）

tests/intelligence/               新規テスト35件（詳細§6）
```

タスク候補構成からの意図的な差分（過剰scaffolding回避）:
- `app/web/`・`research/`・`data/raw|normalized|derived/` は**作成しない**。中身が生まれる
  Phase（11・0.5再開・Stage 2）で作る。データ層の方針のみ§7に確定。
- 旧repoに`src/legacy/`も作らない（NO BIG-BANG DELETE。隔離はStage 5・要承認）。

## 2. Architecture Boundaries（境界の定義と強制）

- vNext→Legacy（src.analysis / src.report / src.collectors / src.data / src.date /
  notifiers / main / scripts）のimport**禁止**。`tests/intelligence/test_import_boundary.py`
  がAST走査で機械検査（現状違反0）。
- Legacy→vNextのimportも現状0であることを同テストで確認（Stage 3以降、承認済み
  adapterのみ例外化する）。
- core層はLLMベンダーSDK（anthropic/openai等）をimportしない（テストで強制）。
  `LLMProvider` Protocolにより実装ベンダーは後から差し替え可能。
- **No God Model**: 旧AnalysisBundle相当の万能オブジェクトは定義していない。型は
  ドメイン単位のfrozen dataclass（最大でもEvidenceRecordの9フィールド）。
- FACT/ANALYSIS/FORECAST分離を**型の不変条件**として強制
  （FORECASTはForecastAttributes必須・非FORECASTには付与不可。テストで検証）。

## 3. Migrated Knowledge（移設した知識）

| 移設先 | 旧所在 | 件数 | 備考 |
|---|---|---|---|
| causal_rules/*.yaml | config.yaml `causal_rules` | ルール18本（14+2+2） | 全ルールに一意ID・confidence・statusを付与 |
| theme_relations/themes.yaml | config.yaml `macro_themes`＋`durable_themes` | 29＋7 | 忠実コピー |
| theme_relations/theme_graph.yaml | config.yaml `theme_relations` | 37ノード | supplementary_nodes 8件を明示（§4） |
| source_reliability/source_tiers.yaml | config.yaml `source_reliability`＋collectors RELIABILITY | 23ソース | Tier1-3閾値で正規化 |
| source_reliability/source_feeds.yaml | collectors Family A 15ファイル＋news_sources＋`source_classification` | フィード24本 | 全件verification: unverified（旧系の実態を正直に引き継ぐ）。Reutersはlikely_dead |
| compass_dna/market_rules.yaml | docs/compass_dna/analysis_rules/market_rules.yaml | ルール13本 | 正本を移設。docs側は凍結注記を追記（削除していない） |

**旧config.yamlは無変更**（Legacy本番は従来どおり動作）。同期ポリシーはknowledge/README.md。

## 4. Normalization Decisions（正規化の判断）

1. **ルールID付与**: 旧causal_rulesは無名だったため `CR_<domain>_<n>` 形式のIDを新規付与
   （ファイル横断一意性をテストで担保）。内容（trigger/sectors/note/durable）は忠実コピー。
2. **confidence付与**: 旧データに無かったため、Compass DNA
   ANALYSIS_RULE_CATALOGとの整合と一般性から confirmed/likely を新規判定して付与
   （新規の判断であることをここに明記。レビュー対象）。
3. **セクター語彙は暫定的に旧config `sectors:` キー準拠**: entity resolver（Phase 2）
   導入までの暫定。causal_rules/market.yaml冒頭に注記。
4. **theme_graphの未定義ラベル8件**（クラウド/SaaS/スマートフォン/決済/旅行/住宅/建設/
   インバウンド）: 旧configの忠実コピーに伴うdanglingノード。themes.yamlへ捏造定義を
   追加せず、`supplementary_nodes` として明示（参照整合テストの対象）。
5. **Tier正規化**: reliability≥0.95→Tier1、≥0.75→Tier2、他Tier3。閾値もYAMLに保持し、
   整合をテストで検査。
6. **フィードは全件unverified開始**: 旧collectorsのdocstring自身が未検証と明記していた
   事実を検証状態として保存。Stage 2の死活確認で更新する。
7. **compass_dna正本の移動**: 「Markdown仕様書はdocs/、machine-readableはknowledge/」の
   原則に従い、market_rules.yamlの正本をknowledge/へ。docs側は削除せず凍結注記のみ
   （既存Findingの無断削除をしない）。

## 5. Reused Legacy Assets（今回再利用した旧資産）

Stage 1はコード再利用ではなく**知識の再利用**が主（§3の全件がconfig.yaml/collectors由来）。
コード面の継承は「思想」のみ: 時刻注入テスト（Clock）、縮退設計（LLMProvider.is_available）、
欠測をNoneで表す規律（MarketObservation）、unit/calc_methodのメタデータ化
（Compass DNAヘッダーテーブルの発見の型化）。

## 6. New Tests（新規テスト35件・全通過）

| ファイル | 件数 | 検証内容 |
|---|---|---|
| test_knowledge_assets.py | 14 | 全YAMLパース・必須メタデータ・semver・ルールID横断一意・causal_rules必須フィールド・テーマグラフ参照整合・Tier閾値整合・フィード形状・**Secret/識別子混入なし** |
| test_import_boundary.py | 4 | vNext→Legacy禁止・core→ベンダーSDK禁止・Legacy→vNext不在・全パッケージにdocstring |
| test_core_contracts.py | 17 | EvidenceRecord不変条件（FACT/FORECAST分離）・confidence範囲・immutability・6 Protocolのダミー実装適合・repo roundtrip・欠測None許容 |

Legacyテスト451件は無変更で全通過（計486件）。

## 7. Data Management（データ方針）

- vNextの実行時生成データは `data/vnext/` 配下とし、**.gitignoreで非管理**
  （Stage 1で.gitignoreに追加済み。Legacyの既存 `data/investment_journal` 等の
  CIコミット運用には影響しない）。
- 長期蓄積が必要になった時点（Stage 2）で、Pages artifact / 外部ストレージ等の
  保存先を提案・承認の上で決める。既存 `output/` には今回触れていない。

## 8. Intentionally Not Migrated（意図的に移設しなかったもの）

- config.yamlの**設定**（watchlist/indices/notifications/report_schedule/output等）:
  Legacy本番の動作定義であり、vNextが必要とする時点で必要分のみ再設計する。
- `sectors:` の銘柄マッピング詳細・`key_levels`: entity resolver（Phase 2）の設計と
  同時に移設する方が二度手間にならない。
- `theme_maturity_notes` / `national_strategy_notes`: 現状空`{}`のため移設対象なし。
- Legacyコード（collectors/analysis/report）: REUSE_MATRIXの判定どおりPhase 1以降に
  logic migration。Stage 1でのコード移植は行わない。
- Cloudflare関連識別子・Secrets参照: SECURITY PRINCIPLEにより**一切コピーしない**
  （テストで機械検査）。Legacy側のcleanupは別途承認事項のまま。

## 9. Risks（リスクと監視点）

1. **知識の二重管理**（knowledge/ ⇔ config.yaml）: Stage 3でLegacyがadapter経由で
   knowledge/を読むまで、人手同期ミスがあり得る。→ knowledge/READMEに「knowledge/が正」
   を明記。同期が発生した場合はCHANGELOGに記録。
2. **confidence初期値は新規判断**（§4-2）: 監督者レビューで修正され得る前提のメタデータ。
3. **supplementary_nodes**はテーマ定義の負債（Phase 2/6で正式定義が必要）。
4. **Protocol契約の変更コスト**: Phase 1で契約変更が必要になった場合は「メソッド追加」
   で対応し、シグネチャ変更は設計レビューを経る。
5. pytest実行がLegacyテスト経由で `data/investment_journal/journal.json` を書き換える
   既知の副作用は継続中（コミット前にrestoreする運用。将来Legacyテスト側の修理を提案）。

## 10. Phase 1 Prerequisites（Phase 1着手前に必要なこと）

1. 本Stage 1成果（特に§4の正規化判断とcore契約）の監督者レビュー・承認。
2. `EvidenceRecord`正式スキーマの合意（numbers[]・counter_points等の拡張フィールド、
   TARGET_ARCHITECTURE §4案の採否）。
3. Stage 2で実施するフィード死活確認の実行環境確認（GitHub Actionsからの外部アクセス
   可否・SEC向けUA表記の文言決定）。
4. `data/vnext/`のEvidence保存形式（JSONL案）の確認。
5. （並行可）Phase 0.5: 8月羅針盤PDFの配置→Out-of-Sample検証→compass_dna/
   market_rules.yamlへのscope付与。
