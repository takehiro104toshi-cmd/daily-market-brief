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

### 4.1 実行戦略（execution metadata・semantic mode とは別）

`replay_mode` は利用者が要求した **semantic** な mode で、評価される position 集合と全出力を決める。
どう実行したかは manifest / summary / result の `execution` に別建てで記録し、`run_digest` には入れない。

| field | 意味 |
|---|---|
| `strategy` | `TRANSITION_REFINEMENT`（粗い pass + 遷移区間を checkpoint 復元で 1 件刻み）/ `FULL_SINGLE_PASS`（FULL_REPLAY）/ `COARSE_ONLY` |
| `planned_coverage` | 粗い pass の結果から exact に決まる精密化計画が、最初の coarse position 以降の全 eligible position を覆うなら `COMPLETE`、それ以外 `PARTIAL`（閾値なし） |
| `refinement_intervals_planned` / `planned_interior_positions` / `planned_snapshot_total` | 計画の内訳 |
| `full_fallback` | `applicable`（COMPLETE か）/ `chosen`（常に false）/ `reason` |
| `work` | `run_incremental_calls` / `documents_analyzed` / `checkpoints` / `restores` / `rebuilds` / `evaluations` |

**FULL fallback を採らない理由（実測）**: replay の実行コストは `run_incremental` の呼び出し回数でほぼ決まり
（1 回の固定コストが batch サイズに依存せず、synthetic 122 eligible で約 1.1 s、Windows 実データ 139 eligible で
約 3.5〜4 s）、その回数は semantic に評価すべき position 数に固定される。精密化区間が全区間に及ぶ場合、
粗い pass + 復元 + 1 件刻み = |positions| 回に対し、単一 pass への切り替えは内側の coarse position ごとに
1 回ずつ余計な `run_incremental` を要し、節約できるのは復元（copytree・数十 ms〜数百 ms）だけである。
したがって「計画が全 position を覆う」ことは検出して記録するが、実行経路は変えない。
最終 coarse position の checkpoint（復元されない）だけは省く。研究状態の digest は `run_incremental` が
返した値を再利用し（`ResearchStore.digest` と同値・test で固定）、position ごとの再 canonicalize を避ける。

Windows 実 FULL_REPLAY で観測された「transition mode が 135 / 139 position を評価した」事象は、463 pattern の
うちどれかが 5 文書ごとに状態を変えるためであり、**semantic な被覆の結果**であって実行の欠陥ではない
（同一 position 集合に対する結果は FULL と一致: CROSS_MODE_CONSISTENCY = true）。
run_incremental の固定コストの主因は Phase 3.8 engine step 7 の per-document similarity list 再構築
（O(N³)）で、これは Phase 3.8 側の performance-only 修正候補として監督者へ提案する（replay からは変更しない）。

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

## 9. 安定性指標と分類（v1 凍結: CALIBRATED_CORPUS_139_V1）

指標: recommendation_transition_count / recommendation_reversal_count / first_*_position・date /
documents_to_* / time_to_*_days / eligible_documents_in_current_state / state・approve・reject
persistence_ratio / worst_consistency_observed / consistency_ever_low / positions_with_cross_regime_high /
positions_with_time_high / main_appearance_count / first_surfaced_in_main_position。
accuracy / precision / hit rate / forecast quality を名乗る指標は存在しない。

分類（語彙・閾値ともに凍結、単位は eligible 文書数であり snapshot 数ではない）:
`INSUFFICIENT_HISTORY → OSCILLATING（reversal ≥ 2） → STABLE（現状態の持続 ≥ 15） →
MOSTLY_STABLE（persistence ratio ≥ 0.8） → RECENT_TRANSITION`。

### 9.1 較正根拠（監督者決定 2026-09-05・policy 1.0.0 → 1.1.0）

provisional 値（15 / 0.8 / 2）を **値を変えずに** v1 として凍結した。根拠は Windows 実データの FULL_REPLAY:

| 観測 | 値 |
|---|---|
| captured eligible / documents / patterns | 139 / 141 / 463 |
| recommendation reversal 0 / 1 / 2+ | 462（99.8%）/ 1（0.2%）/ 0 |
| provisional class | STABLE 407 / MOSTLY_STABLE 1 / OSCILLATING 0 / RECENT_TRANSITION 10 / INSUFFICIENT_HISTORY 45 |
| 現 APPROVE_RECOMMENDED | 10 件・approve_persistence_ratio 1.0・reversal 0（STABLE 5 / RECENT_TRANSITION 5）、first approve 78〜136、6 / 10 が CORPUS_100 以降 |
| 現 REJECT_RECOMMENDED | 6 件・reject_persistence_ratio 1.0・reversal 0・recovery 0、first reject 33〜125 |

0 OSCILLATING は妥当な経験的結果であり、OSCILLATING を作るために閾値を緩めない。
`calibration_state` の変更は policy digest を変えるため policy_version を 1.1.0 へ上げた
（同 version での内容変更は `ReplayPolicyError`）。metrics の `provisional` は false になる。
実 pattern ID は policy / config に一切書かない。

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

- `replay_policy_digest`（semantic field のみ。`temp_workspace` / `retain_debug_runs` / `full_replay_enabled` は除外。FULL の許可は運用フラグで、選ばれた mode は manifest に記録される）
- 固定 snapshot 再 run: `--retain-temp` で保持した run の temp（corpus backup + Context export + marker）を
  `--from-run <run_id>` で再利用すると、production を再捕捉せずに **同じ入力宇宙** を再 replay できる
  （manifest `input_source.kind = RETAINED_SNAPSHOT`）。live intake が進んでいても run_digest は一致しなければならない。
  live 再捕捉どうしは `input_manifest_digest` / `context_manifest_digest` が一致するときだけ比較可能
- `input_manifest_digest`（文書 identity のみ）/ `snapshot_digest`（rows の semantic 部分）/ `run_digest`
- 生成時刻（`run_created_at`）は id にだけ現れ、digest に入らない。`now` は run_created_at + step 秒で固定。
- run 中の live corpus 増加は無視して manifest に件数だけ記録。捕捉済み文書の identity 変化や
  捕捉範囲内の Context 変化は `ReplayInputMutated`。
- 同じ policy_version で digest が違う run が既に保存されていれば `ReplayPolicyError`。
  version を上げた run（1.0.0 → 1.1.0）は許可され、旧 run は旧 digest のまま保存される。
- `execution` metadata（実行戦略・計画・work counter・timings）は run_digest に入らない。

## 14. 失敗クラス

`ReplayPolicyError, ReplayMixedPolicyDigest, ReplayAnalyzerVersionMissing, ReplayIncompleteSnapshot,
ReplayIdentityCollision, ReplayIdentityAmbiguity, ReplayLeakageDetected, ReplayInputMutated,
ReplayTempCorrupt, ReplayUndatedExceeded, ReplaySnapshotCaptureError, ReplayContextSnapshotError,
ReplayRebuildMismatch`。すべて fail closed（部分出力を書かない）。

## 15. CLI

`python -m src.intelligence.replay.cli [--data-root D] run [--mode M] [--ordering O] [--retain-temp]`
`run --retain-temp`（snapshot 保持）/ `run --from-run <run_id>`（保持 snapshot から再 run）/
`run --enable-full-replay`（config.yaml を編集せずに FULL を許可する運用 override）
`validate-policy` / `list-runs` / `summary [--run R] [--section S]` / `show <pattern_id> [--run R]`
`python -m src.intelligence.replay.validation --require-commit <sha> --expect-<policy> <digest>`:
Windows 実機の real-data validation を 1 操作で実行（HEAD / policy / baseline / default ×2 / 決定性 /
FULL 較正 / stress / queue / equivalence / handoff / safety。`::P394_*::` marker、ASCII のみ、fail closed）
exit 0 成功 / 1 引数 / 2 policy / 3 ReplayError。`run` 以外は read-only。
