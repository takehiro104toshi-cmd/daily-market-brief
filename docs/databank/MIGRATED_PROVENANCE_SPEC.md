# MIGRATED_PROVENANCE_SPEC — 移行由来provenance仕様（Phase 2-F PART E）

## 1. 問題（P2-C/P2-Dの恒常warning）

- News: tank移行の3,056文書は原文blob非保存（raw_item_id=""）のため、
  HISTORICAL v1.0で全件 `missing_raw_item` WARN（ACCEPT 0件）。
- 「warningを単純に消す」のは禁止——**provenanceの実態を型で表現**して解決する。

## 2. MIGRATED_PROVENANCEの意味

> live RawItemは無いが、legacy shard / dataset fingerprint / legacy record locator
> までtrace可能

実装: `assess_source_document(..., migrated_trace=True)`（HISTORICAL v1.1.0）。
呼び出し側がtraceの実在を**確認してから**渡す。実データでは:
- LegacyAnnotationの `legacy_shard_locator`＋`legacy_article_id`（3,056/3,056で実在）
- dataset fingerprint `7578425805b32592…`（BackfillRun manifest）

→ provenance次元は `migrated_provenance` reason code付き**PASS**。

## 3. MIGRATED ≠ LIVE FETCH（区別の維持）

- live取得文書: provenance PASS（reason codeなし）＋raw_item_id実在
- 移行由来文書: provenance PASS＋**migrated_provenance** reason code
  ——assessmentを見れば両者は常に機械判別できる（偽装ではない）。
- **fake RawItem / FetchAttemptは引き続き禁止**（何も捏造していない——
  評価語彙を実態に合わせただけ）。
- traceの無い原文欠落は**従来どおりmissing_raw_item WARN**（テスト固定）。

## 4. 再評価結果（実データ・NO RETROACTIVE DELETE）

| | HISTORICAL v1.0.0（旧・保持） | HISTORICAL v1.1.0（新規追記） |
|---|---|---|
| ACCEPT | 0 | **3,008** |
| ACCEPT_WITH_WARNINGS | 3,056（missing_raw_item全件＋tier3 48） | **48**（tier3のみ） |
| missing_raw_item warning | 3,056 | **0** |

- 旧assessmentは削除せず併存（assessments 3,056→6,112件。policy版で機械比較可能）。
- `latest_for(record, policy_name="HISTORICAL")` は最新（v1.1.0）を返し、
  履歴には両版が残る。

## 5. market観測の同型問題

`missing_supporting_evidence_ref` はMARKET_OBSERVATION_TRUST_POLICY.mdで
別途解決（provider経路provenance）。import由来のmarket観測は
`ProviderTrace.import_provenance`（dataset fingerprint等）で同じ意味論に乗る。
