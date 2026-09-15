# HUMAN_REVIEW_WORKFLOW — 人間レビューワークフロー（Phase 2-F PART B）

原則: THE DATA BANK MUST BE EXPLAINABLE, CORRECTABLE, AND REBUILDABLE。
実装: `src/intelligence/review/`（model / store / intake / service / cli）。

## 1. Review対象（7種・実データ実測88件）

| review_type | 供給元 | 実測 |
|---|---|---|
| identity_candidate | P2-B/C CANDIDATE（mergeされなかった曖昧候補） | 25 |
| ambiguous_alias | 文脈条件未達の曖昧entity alias（Apple/Fed等） | 58 |
| unknown_ticker | 明示ticker記法・カタログ未登録（NASDAQ:SNDK等） | 5 |
| llm_unknown_label | taxonomy外のLLM label | 0（LLM未使用） |
| enrichment_uncertain | LLM不正出力等の保留 | 0 |
| revision_syndication | revision/syndication関係の証明不能ケース | 0（55件全て決定論分類済み） |
| source_mapping | LEGACY_UNKNOWN_SOURCE | 0（P2-C exact_name 42/42の帰結） |

intakeは冪等（review_idは対象から決定論導出・decision済みitemを上書きしない）。

## 2. ReviewItemモデル

review_id / record_id / record_type / review_type / reason_codes /
candidate_values / **evidence_refs**（根拠となるevent・classification・抜粋）/
created_at / status / resolution / resolved_at / resolved_by / notes。

status: **OPEN / APPROVED / REJECTED / RESOLVED / DEFERRED**。
statusの更新は`review_items.jsonl`への**新version追記**（append-log latest-wins。
旧versionはログに残る——履歴削除は構造的に不可能）。

## 3. Decision（append-only・manual優先）

ReviewDecisionRecord: decision_id / review_id / decision / decided_by（`user:<name>`
形式を型で強制）/ decided_at / params / **applied_effects**（発行したevent・
classification ID——何がどう変わったか追跡可能）/ notes。

decision種はreview_typeごとに`ALLOWED_DECISIONS`で制限（誤適用の構造防止）:

| decision | 効果 |
|---|---|
| MERGE | ArticleへMANUAL_MERGEイベント（actor=user:→**algorithm判定より優先**、P2-B機構） |
| MARK_REVISION / MARK_SYNDICATED | 同・manualイベント |
| KEEP_SEPARATE | 記録のみ（現状維持の明示） |
| LINK_ENTITY | enrichmentへUSER分類（effective viewで最優先） |
| REJECT_ENTITY | 記録のみ（linkしない判断の明示） |
| ADD_ALIAS | 決定を記録し**カタログ更新を人間タスク化**（versioned知識資産をコードから自動書換えしない） |
| CLASSIFY | USER分類の付与 |
| RETRACT_CLASSIFICATION | RETRACTイベント（レコードは残る） |
| DEFER | status=DEFERRED |

## 4. 操作面（NO UI REQUIRED）

```
python -m src.intelligence.review.cli list [--status open] [--type ...]
python -m src.intelligence.review.cli show <review_id>
python -m src.intelligence.review.cli decide <review_id> merge --by takehiro \
    --param target_article_id=art_xxx --notes "同一発表の続報"
```
将来のPWAはCLIではなく**ReviewService**（同一契約）を呼ぶ。

## 5. クエリ統合

review itemsはSQLite索引（review_itemsテーブル）へ反映され、
`NewsQuery(review_status="open", theme="ai")` のような複合検索が可能
（実corpus実測: open×ai=5件）。

## 6. 運用上の規律

- 実データへの**架空のhuman decisionは投入しない**（本phaseはintakeと機構検証まで。
  実decisionはユーザーの作業として残る——open 88件）。
- decision適用に失敗した場合（未知target等）はValueError——decision記録ごと
  失敗し、中途半端な状態を作らない。
