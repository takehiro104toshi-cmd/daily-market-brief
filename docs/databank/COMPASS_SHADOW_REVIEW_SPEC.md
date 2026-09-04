# Compass Shadow Review 仕様（Phase 3.9.3）

**SHADOW MODE / NOT_PREDICTIVE / NOT_FORMAL_APPROVAL / HUMAN_FEEDBACK_ONLY / CORPUS_100_FORMAL_GATE**

Phase 3.9.2 は「engine が何を推奨するか」を答える。Phase 3.9.3 は推奨を**再分類せず**、
「今日、人間が何をレビューすべきか」だけを答える。

この層は formal APPROVED / REJECTED を書かず、Compass DNA へ promote せず、Phase 3.8 research
artifact・Phase 3.9.2 evaluation record・Phase 3.9.1 decision history のいずれも変更しない。
formal approval は CORPUS_100 到達後に Phase 3.9.1 の gate を通じてのみ可能で、Shadow Review の
outcome がそれへ自動変換されることは決してない。

## 1. 入出力

| 種別 | 対象 | 権限 |
|---|---|---|
| 入力 | `<data_root>/compass_evaluation/`（Phase 3.9.2 record） | read-only |
| 入力 | `<data_root>/compass_research/`（lifecycle・supporting document date・components） | read-only |
| 入力 | `config.yaml` `compass_shadow_review` | read-only |
| 出力 | `<data_root>/compass_shadow_review/review_events.jsonl` | **append-only・不変・人間由来** |
| 出力 | `<data_root>/compass_shadow_review/queue.json` | derived・atomic 置換 |
| 出力 | `<data_root>/compass_shadow_review/summary.json` | derived・atomic 置換 |
| 出力 | `<data_root>/compass_shadow_review/current_reviews.json` | derived・atomic 置換 |

`compass_decisions/` と `knowledge/compass_dna/` へは、どの経路からも書かない。

## 2. queue の構造

```
MAIN              top_n = 8。REJECT_RECOMMENDED → APPROVE_RECOMMENDED → REVIEW_RECOMMENDED
ADVERSE_OVERFLOW  REJECT が top_n を超えた分（捨てない・隠さない）
BACKLOG           main に載らなかった escalated（件数と型内訳を必ず表示）
WATCH             KEEP_REVIEWING の別枠。v1 は watch_n = 0 なので既定で空
```

`NOT_READY` は queue に入れない（applicable core axis < 2 で判断材料が無い）。
`KEEP_REVIEWING` は main queue に入らない。

## 3. 順位（同一 Recommendation state 内）

Phase 3.9.2 の `score.ordering_key()` を基底に、tie-break を 2 段足すだけ。frozen code は変更しない。

```
1. applicable core の HIGH 本数 DESC     ← 質的 state が第一
2. Reference Score DESC                  ← comparable のときのみ（NOT_COMPARABLE は最下位）
3. relative_support_share DESC           ← Phase 3.9.2 の applicability に従う
4. eligible_support DESC
5. span_days DESC
6. pattern_id ASC
```

Reference Score は state を決めず、再提示も駆動しない（§6）。

## 4. 型分散

`REJECT_RECOMMENDED` / `APPROVE_RECOMMENDED` は分散を完全 bypass する。`REVIEW_RECOMMENDED` のみ
pattern type の round-robin（+ `type_caps` の backstop）。型の訪問順は「その型の先頭要素の質」で決め、
同質なら config の `type_order` で決定化する。

## 5. review card

6 axis（state / applicability / reason）、Reference Score（comparable のときのみ数値）、evidence
数値、DNA 関係、矛盾シグナル、`sibling_group_id`（表示のみ）、triggered/supporting/blocking rule、
governance（shadow_mode・gate・corpus）、review 履歴、supporting document の **ISO 日付**。

本文・page text・path・ファイル名・title は保存も表示もしない。`FORBIDDEN_KEYS` を**再帰的に**検査し、
1 つでも見つかれば fail closed で書き込みを拒否する。

## 6. material change（再提示）

```
含める : recommendation / axis_states / axis_applicability / eligible_support /
         distinct_2d_cells / contradiction / lifecycle / evaluation_policy_digest /
         recommendation_policy_digest
除外   : reference_score / relative_support_share / span_days / confirmed_3d_cells / 経過時間
```

`material_digest`（canonical JSON の sha256 先頭 16 桁）が前回レビュー時と異なることだけが再提示の
トリガ。config に `reference_score` を混ぜようとすると起動時に拒否される。

## 7. cooldown

| outcome | cooldown |
|---|---|
| AGREE | 30 日 |
| UNCLEAR | 14 日 |
| DUPLICATE_OR_OVERLAPPING / NOT_ACTIONABLE | 90 日 |
| DISAGREE / NEEDS_MORE_EVIDENCE | **0 = MATERIAL_CHANGE_ONLY** |
| REJECT_RECOMMENDED（上限） | `adverse_cooldown_cap` = 7 日 |

**0 は「cooldown 無し」ではない。**「時間経過では二度と戻さない」を意味する。人間が明確に否定した
ものを日数だけで再提示しないための設計であり、証拠が増えれば material change として自動的に戻る。

## 8. outcome と理由要件

```
AGREE                     note 任意
DISAGREE                  理由必須（10 文字以上）
NEEDS_MORE_EVIDENCE       構造化必須（MORE_DOCUMENTS / MORE_REGIMES / LONGER_SPAN / BETTER_QUALITY）
UNCLEAR                   理由必須
DUPLICATE_OR_OVERLAPPING  理由必須 + related_pattern_id 必須（自分自身は不可）
NOT_ACTIONABLE            理由必須
```

`AGREE` は「推奨状態に同意する」であり formal APPROVED ではない。REJECT_RECOMMENDED への `AGREE` は
「否定レビューが妥当」であって formal REJECTED ではない。outcome 語彙は Decision state・
Recommendation state・Phase 3.8 review queue の `OPEN` のいずれとも交差しない（起動時に検証）。

## 9. event store

`review_events.jsonl` は append-only。`sequence` 連番と `previous_record_hash` の chain を持ち、
読み込み時に検証して壊れていれば fail closed。同一内容の再送は同じ `shadow_review_id` になり冪等
no-op、同じ id で内容が違う行は `CONFLICTING_DUPLICATE` で拒否する。削除・上書き・切り詰めの API を
持たない。`reviewer_type` は `HUMAN` 固定で、`SYSTEM` は拒否される（自動レビュー不可）。

## 10. CLI

```
build [--dry-run]   derived 3 ファイルを atomic 置換（--dry-run は完全 read-only）
record              人間レビューを 1 件 append（唯一の history write）
summary / list / show / history / validate-policy / validate-events   すべて read-only
```

formal Decision を書く command も、DNA へ promote する command も存在しない。

## 11. 較正指標（予測精度ではない）

`summary.json` の `calibration_metrics`。`review_agreement_rate` / `human_disagreement_rate` /
`disagreement_rate_by_recommendation` / `disagreement_rate_by_triggered_rule` /
`disagreement_rate_by_pattern_type` / `needs_more_evidence_rate` / `unclear_rate` /
`not_actionable_rate` / `duplicate_rate` / `re_review_rate` / `recommendation_change_after_review` /
`time_to_first_escalation` / `queue_type_distribution` / `queue_coverage` /
`adverse_disagreement_rate` / `adverse_overflow_count`。

データが無い指標は `null` または `NOT_AVAILABLE` を返し、値を捏造しない
（`time_to_first_escalation` は escalate 時刻が未記録のため v1 では常に `NOT_AVAILABLE`）。

## 12. policy

`config.yaml` `compass_shadow_review`（`policy_version` + content digest）。同一 version で内容が
変われば `ShadowReviewPolicyError` で fail closed。`auto_decision_write` / `auto_promotion` の true、
`allowed_reviewer_types` への `SYSTEM`、`state_priority` への `NOT_READY` / `KEEP_REVIEWING`、
`material_change_fields` への score 系、outcome 語彙の衝突は、いずれも起動時に拒否する。
