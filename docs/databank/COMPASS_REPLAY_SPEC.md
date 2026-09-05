# Compass Replay / Simulation 仕様（Phase 3.9.4）

**NOT_PREDICTIVE / NOT_FORMAL_APPROVAL / HUMAN_FEEDBACK_ONLY / IMMUTABLE_INPUT_UNIVERSE / PROVISIONAL_CALIBRATION_ONLY**

Phase 3.9.4 は「corpus が N 件だった時点で、Phase 3.8 → 3.9.2 → 3.9.3 は何を言っていたか」を
**事後的に再構成**し、推奨の安定性（いつ現れ、どれだけ持続し、どれだけ揺れたか）を測る層である。
将来を予測せず、正しさ（accuracy / precision / hit rate）を測らず、formal APPROVED / REJECTED を書かず、
Compass DNA へ promote せず、production の corpus / research / evaluation / shadow review / decision を
一切変更しない。出力は Phase 3.9.5（formal review）への **evidence** に過ぎない。

## 1. 不変の入力宇宙（IMMUTABLE_INPUT_UNIVERSE）

1 run = 以下を run 開始時に固定した宇宙。run 中に live 側で何が起きても run の結果は変わらない。

| 要素 | 捕捉方法 | 同一性 |
|---|---|---|
| corpus snapshot | `sqlite3.Connection.backup()`（`mode=ro` URI で開いた live DB → temp DB）。OS copy は使わない。CompassIntake は停止しない | `corpus_snapshot_digest`（snapshot DB の sha256 先頭 16） |
| context snapshot | `index/context.sqlite3` を ro で読み、`status <> STALE` かつ `session_date <= 捕捉 corpus の最新 document_date` の行を `contexts.jsonl` + `trading_days.json` へ書き出し、以後は一切再読しない | `context_manifest_digest` |
| research version | Phase 3.8 `version_key` | `research_version_key` |
| policy | evaluation / recommendation / shadow_review / replay の 4 digest | manifest に記録 |

Context は本番の regime 意味論（`known_at <= publication cutoff` gate）をそのまま保ち、
全 snapshot が同じ凍結 Context を使う。捕捉範囲の後ろに追加された session 行は digest に影響しない。

## 2. データフロー

```
live corpus DB ──backup()──▶ immutable snapshot ──▶ InputManifest ──▶ canonical ordering
                                                                    │
     prefix(position p) ──▶ ReplayCorpusView(allowed = prefix) ──▶ Phase 3.8 run_incremental（temp research）
                                                                    │
                            temp EvaluationStore ◀── Phase 3.9.2 evaluate_all(dry_run)
                                                                    │
                            ShadowReviewQueueBuilder.build(dry_run=True, 空 event store)
                                                                    │
                            timeline rows / snapshot doc / leakage audit / rebuild equivalence
```

ReplayCorpusView は prefix 外の document へのあらゆる read を `ReplayLeakageDetected` で拒否し、
write API を持たない。Phase 3.8 / 3.9.2 / 3.9.3 の semantics・weights・precedence・ranking・diversity・
cooldown は変更しない（replay は既存 engine を temp root で呼ぶだけ）。PDF は開かない
（artifact に保存済みの抽出テキストだけを使う）。

## 3. 順序（ordering）

| mode | key | 備考 |
|---|---|---|
| `CHRONOLOGICAL`（既定） | `document_date ASC, date_sequence ASC, document_id ASC` | undated は除外し manifest に記録。比率が `max_undated_ratio` を超えたら `ReplayUndatedExceeded`。日付は決して捏造しない |
| `INGESTION`（明示のみ） | `received_at ASC, document_id ASC` | undated も含む |

position = eligible（`quality == VALID`）文書の累積件数。PARTIAL は usable として prefix に含まれるが
position を進めない。duplicate / 非 usable は除外し manifest に理由付きで残す。

## 4. モード

| mode | snapshot 位置 |
|---|---|
| `MILESTONE_REPLAY` | 10 / 30 / 50 / 100 / 200 のうち到達済み + current |
| `TRANSITION_REPLAY` | `transition_resolution`（5）刻み + current。隣接 snapshot 間で recommendation / lifecycle が変化した区間だけ 1 件刻みへ精密化（checkpoint から復元して再前進） |
| `MILESTONE_AND_TRANSITION`（既定） | 上 2 つの和 |
| `FULL_REPLAY` | 1..current 全 eligible 増分。`full_replay_enabled: true` の明示時のみ。既定にはできない（policy validate で拒否） |

milestone 位置では incremental research state と `run_full_rebuild` の結果を `equivalence()` で照合し、
不一致は `ReplayRebuildMismatch` で fail closed。

## 5. 同一性と漏洩ガード

- replay identity = `pattern_id`（Phase 3.8 の内容 hash）。同 run 内で同じ `pattern_id` の
  `components_digest` が食い違えば `ReplayIdentityAmbiguity`（tolerance 0、凍結）。
- 各 snapshot で監査: structure の document ⊆ prefix、supporting document ⊆ prefix、
  supporting date range ⊆ prefix の date range、eligible 件数 == prefix eligible、
  queue の `corpus_context_source == EVALUATION_SNAPSHOT`、production の research / evaluation /
  shadow review root を読まない（AST テスト）。
- 凍結規則上あり得ない推奨（span / months 不足の APPROVE、支持不足の REJECT）は replay 側の欠陥として
  `ReplayLeakageDetected`。
- prefix 閉包テスト: position p の snapshot は「corpus が p で終わっていた世界」と semantic に同一
  （`snapshot_id` だけが run の入力宇宙に束縛されるため異なる）。

## 6. 出力

`<data_root>/compass_replay/latest.json` と `runs/<run_id>/` 配下。すべて derived・atomic 置換。

| file | 内容 |
|---|---|
| `replay_manifest.json` | run_id / run_created_at / mode / ordering / corpus & context snapshot identity / 文書一覧（id, sha256, date, seq, received_at, quality, eligible, status）/ duplicates / excluded / digest 4 種 / research version / captured counts / live corpus at start & end / run 中に新規 intake された件数 |
| `snapshots.jsonl` | position ごとの集計（by_recommendation / by_lifecycle / queue 概要 / research_digest / snapshot_digest / equivalence） |
| `pattern_timelines.jsonl` | pattern × position の行（§7） |
| `transition_events.jsonl` | §8 |
| `summary.json` | stability distribution / pattern_metrics / approve_stress / reject_stress / formal_review_input / Top-8 retrospective / drift / timings |

temp は `<temp>/compass_replay_runs/<run_id>/`（`REPLAY_OWNED_TEMP` marker）。cleanup は marker と
親 path を検証した replay 所有 path だけを削除し、git clean や production path の削除は行わない。
失敗時は temp を保持する。

## 7. timeline row

`run_id, snapshot_id, snapshot_mode, ordering_mode, position, usable_position, latest_document_date,
eligible_documents, usable_documents, milestone, pattern_id, pattern_version, pattern_type,
components_digest, lifecycle_status, support_count, eligible_support, regime_count, span_days,
distinct_calendar_months, pattern_first_seen, recommendation, triggered_rule, blocking_rules,
supporting_rules, axis_states, axis_applicability, axis_reasons, reference_score,
reference_score_comparable, applicable_weight_sum, relative_support_share(+applicability),
dna_classification, dna_conflicts, contradiction{narrow_sibling, narrow_sibling_repeated, document,
document_repeated}, document_qualities, material_digest, queue_section, queue_rank,
evaluation/recommendation/shadow_review/replay policy digest, research_version_key`

queue_section は `MAIN / ADVERSE_OVERFLOW / BACKLOG / NOT_SURFACED`。Phase 3.9.3 の forbidden key
（原文・ページ・ファイル名・path 等）は再利用し、全出力を scan する。

## 8. transition events

`FIRST_OBSERVED / FIRST_NEW_PATTERN_CANDIDATE / FIRST_REVIEW_CANDIDATE / FIRST_STRONG_PATTERN_CANDIDATE /
FIRST_NOT_READY / FIRST_REVIEW_RECOMMENDED / FIRST_APPROVE_RECOMMENDED / FIRST_REJECT_RECOMMENDED /
FIRST_SURFACED_IN_MAIN`（それぞれ 1 pattern につき 1 回）、
`RECOMMENDATION_CHANGED / LIFECYCLE_CHANGED / CONSISTENCY_CHANGED`（隣接 snapshot 間）。
score・cross_regime・quality の変化はイベントにしない。

## 9. 安定性指標と分類（PROVISIONAL）

指標: recommendation_transition_count / recommendation_reversal_count / first_*_position・date /
documents_to_* / time_to_*_days / eligible_documents_in_current_state / state・approve・reject
persistence_ratio / worst_consistency_observed / consistency_ever_low / positions_with_cross_regime_high /
positions_with_time_high / main_appearance_count / first_surfaced_in_main_position。
accuracy / precision / hit rate / forecast quality を名乗る指標は存在しない。

分類（語彙は凍結、閾値は `PROVISIONAL_CALIBRATION_ONLY`、単位は eligible 文書数であり snapshot 数ではない）:
`INSUFFICIENT_HISTORY → OSCILLATING（reversal ≥ 2） → STABLE（現状態の持続 ≥ 15） →
MOSTLY_STABLE（persistence ratio ≥ 0.8） → RECENT_TRANSITION`。
全 metrics に `provisional: true` と閾値を同梱する。実 FULL_REPLAY による較正後に監督者が凍結する。

## 10. APPROVE / REJECT stress

APPROVE: 50 / 75 / 100（以下で最も近い position）/ current の推奨、first approve、
`appeared_only_after_100`、retention、reversions、worst consistency、cross-regime / time HIGH 持続。
REJECT: first material contradiction、first reject、`was_review_before_reject`、driver、recovery、persistence。
どちらも「あり得ない早期」を sanity として fail closed に扱う。

## 11. Shadow queue replay

各 position で **空の event store** を使って queue を再構成する。人間のレビュー回答を捏造しない。
現在の production Top-8 が過去のどの position で MAIN に現れたかを retrospective として出す。

## 12. Phase 3.9.5 handoff

`formal_review_input` は evidence のみ。production の Shadow Review 履歴と Decision 現状態は
READ-ONLY 参照（`ShadowReviewEventStore.for_pattern` / `DecisionStore` + `derive_current_states`）で、
write 可能 API（`DecisionService` 等）は replay package から import しない。

## 13. 決定性と drift

- `replay_policy_digest`（semantic field のみ。`temp_workspace` / `retain_debug_runs` は除外）
- `input_manifest_digest`（文書 identity のみ）/ `snapshot_digest`（rows の semantic 部分）/ `run_digest`
- 生成時刻（`run_created_at`）は id にだけ現れ、digest に入らない。`now` は run_created_at + step 秒で固定。
- run 中の live corpus 増加は無視して manifest に件数だけ記録。捕捉済み文書の identity 変化や
  捕捉範囲内の Context 変化は `ReplayInputMutated`。
- 同じ policy_version で digest が違う run が既に保存されていれば `ReplayPolicyError`。

## 14. 失敗クラス

`ReplayPolicyError, ReplayMixedPolicyDigest, ReplayAnalyzerVersionMissing, ReplayIncompleteSnapshot,
ReplayIdentityCollision, ReplayIdentityAmbiguity, ReplayLeakageDetected, ReplayInputMutated,
ReplayTempCorrupt, ReplayUndatedExceeded, ReplaySnapshotCaptureError, ReplayContextSnapshotError,
ReplayRebuildMismatch`。すべて fail closed（部分出力を書かない）。

## 15. CLI

`python -m src.intelligence.replay.cli [--data-root D] run [--mode M] [--ordering O] [--retain-temp]`
`validate-policy` / `list-runs` / `summary [--run R] [--section S]` / `show <pattern_id> [--run R]`
exit 0 成功 / 1 引数 / 2 policy / 3 ReplayError。`run` 以外は read-only。
