# REVISION_SYNDICATION_POLICY — 改定・転載・撤回・手動修正（Phase 2-B）

## 1. REVISION（同一記事の内容更新）

- 判定signal: 同一canonical URL＋fingerprint変化 / 同一source×同一GUID＋fingerprint変化。
  **minor markup差はrevisionにならない**（fingerprintがmarkup差を吸収するため
  同一fingerprint→EXACT_MATCH側）。
- chain: v1→v2→v3 を SourceDocument.revision_of（P1-D）＋Article memberとして保持。
  **旧版削除禁止**・latest revisionは`latest_revisions()`導出（P1-A関数）。
- revision cycleはData Bank validationが検出（`broken_revision_relation`）。

## 2. SYNDICATION（転載）

- 転載はduplicateと**完全同一視しない**: Reuters原文＋Yahoo転載は
  同一Article identity＋`NewsDocumentLink role=SYNDICATED` で表現
  （runtimeテストで実証）。
- 判定: 同一content fingerprint×別publisher（STAGE 1）または
  保守的multi-signal（STAGE 2）。**転載元の推測はしない**（sourceの明示メタデータが
  ある場合のみ将来利用——signal #10予約）。
- primary（原文）選定はARTICLE_IDENTITY_SPEC §6（非転載→先行公開→tier）。

## 3. CORRECTION / RETRACTION

- corrected / updated / retracted はsourceの**明示メタデータがある場合のみ**利用。
- **見出し変化だけでretractionを推測しない**（P1-E規律の継続:
  retracted_idsへの明示登録のみがREJECTを引き起こす）。
- retracted文書もArticle memberとして履歴保存（現在分析用途のGateがREJECTするだけ）。

## 4. MANUAL OVERRIDE（誤merge修正の基盤）

event-sourced storeにより人間の修正が可能:

| event | 効果 |
|---|---|
| MANUAL_SPLIT | 文書をArticleから分離。以後**algorithmはその文書を戻せない**（manual優先） |
| MANUAL_MERGE | Article統合（algorithm判定より優先・対象articleはmanual locked） |

- actor（"user:名前" / "algorithm:version"）で優先制御。manual操作後のarticleは
  algorithm由来の変更を受け付けない（manual_locked）。
- **履歴は全て残る**: eventはappend-onlyで、上書き・削除されない。replayで
  いつでも現在状態を再導出できる（テストで機械検証）。

## 5. ARTICLE STORE（正本＝イベント）

`data/vnext/articles/article_identity_events.jsonl`（git非管理・append-only・
crash-safe）。イベント語彙: CREATE / ADD_DOCUMENT / MARK_REVISION /
MARK_SYNDICATED / SET_PRIMARY / MANUAL_SPLIT / MANUAL_MERGE。
現在状態（ArticleIdentity）は**replayによる導出値**（二重保存しない）。
検索索引はSQLite（news_items.article_id列・再構築可能——P2-A storage decision準拠）。
