# Compass Evaluation Engine（Phase 3.9.2）

Phase 3.8 の research evidence を、凍結された 6 axis で評価し、Reference Score と Recommendation へ落とす層。
実装は `src/intelligence/evaluation/`（1機能=1ファイル）、設定は `config.yaml: compass_evaluation` /
`compass_recommendation`、テストは `tests/intelligence/test_evaluation_engine.py`（27 件）。

```
Phase 3.8 research artifact（読むだけ）
  → 6 axis（LOW / MEDIUM / HIGH）＋ applicability（APPLICABLE / NOT_APPLICABLE）
  → Reference Score（secondary。構造的 N/A は weight ごと除外して再正規化）
  → Recommendation（NOT_READY > REJECT > APPROVE > REVIEW > KEEP_REVIEWING、first match wins）
  → derived evaluation store（rebuildable。決定的に置換する）
```

## 1. 境界（Phase 3.9.1 から継承・強化）

- `APPROVE_RECOMMENDED` ≠ `APPROVED` ≠ `PROMOTED_TO_DNA`。engine は助言するだけで **Decision を書かない**。
  evaluation package は `DecisionService` / `DecisionRequest` を import しない（AST テストで検証）。
- formal `APPROVED` は Phase 3.9.1 の CORPUS_100 gate が fail closed で守る。本層は shadow フラグを記録するだけ。
- Reference Score は state transition に使わない（`score_use.allowed_for_state_transition: true` は起動時に拒否）。
- DNA Novelty は approval 要件ではなく、弱い evidence を救済しない（`approve.requires_novelty: true` も拒否）。
- production DNA / Corpus / Phase 3.8 artifact / decision history を書き換えない。外部 LLM を使わない。
- 出力に PDF 本文・observation text・file path を入れない（id / count / label / version だけ）。

## 2. 6 axis（frozen）

| axis | LOW | MEDIUM | HIGH | 構造的 NOT_APPLICABLE |
|---|---|---|---|---|
| Evidence Strength | eligible_support = 1 | 2–3 | ≥ 4 | FULL（`support_ranked=false`） |
| Time Stability | span < 14 または month < 2 | span ≥ 14 かつ month ≥ 2 | span ≥ 60 かつ month ≥ 3 | なし |
| Cross-Regime | 2D cell 0–1 | 2 cells | ≥ 3 cells かつ support ≥ 3 かつ span ≥ 30 かつ confirmed ≥ 1 | FULL / STATE_OUTLOOK |
| Evidence Consistency | 矛盾あり | それ以外 | committed 方向 + support ≥ 2 + 矛盾なし + 軟化なし | なし（HIGH は cap されるだけ） |
| DNA Novelty | EXPLAINED、または overlap ≥ 1 + target 一致 + SAME/CONDITIONAL | それ以外の assessable | NEW かつ assessable | evidence または target を欠く型 |
| Data Quality | LIMITED_USE / 未解決 id / valid_ratio < 0.8 / 未対応 version | PARTIAL / valid_ratio < 1.0 / eligible < support / version 混在 | 上記いずれもなし | なし（gate） |

`applicability` は **score 用の別次元** で、4 つ目の axis state ではない（表示は常に LOW/MEDIUM/HIGH）。
構造的不可能（pattern identity が試験そのものを成立させない）のときだけ NOT_APPLICABLE にする。証拠不足は該当しない。

UNKNOWN policy: 必要な regime dimension が UNKNOWN の document は、その signature へ寄与しない。UNKNOWN は regime ではない。
3D（equity + yen + us_rate）は secondary confirmation として記録するだけで、state を上げる力を持たない。

## 3. Contradiction の導出

append-only の review queue membership は stale になり得るため信頼せず、**現行 registry から毎回再計算** する。
Phase 3.8 の queue rule は衝突 group の全 pattern を subject に含める（RANGE / 方向なしの sibling まで）ので、
本層は **自身の direction が UP / DOWN のものだけ** を LOW にする（narrow rule）。
supporting document の UP/DOWN 同居は構造上 non-directional 型でのみ起こり得る（directional 型は identity が方向を固定する）。
DNA relation OPPOSITE で target 不一致は informational only（別の対象についての rule なので矛盾ではない）。

## 4. Reference Score

`Σ(weight × map(state)) / Σ(weight)` を **applicable axis のみ** で計算する（構造的 N/A に減点を課さない）。
weights 30 / 25 / 20 / 15 / 10、mapping LOW 0 / MEDIUM 50 / HIGH 100。
applicability profile: EVIDENCE_OUTLOOK 100、THEME_OUTLOOK 100、EVIDENCE_WHY 90、EVIDENCE_RISK 90、
STATE_OUTLOOK 70、FULL 50。`applicable_weight_sum < 60` は `reference_score = null` /
`reference_score_comparable = false`（薄い score を権威に見せない）。ただしそれは NOT_READY の理由にはしない。
順序付けは `(applicable な HIGH 数, score, relative_support_share)` の順で、qualitative state を第一とする。

## 5. Recommendation（frozen precedence・first match wins）

| state | 条件 |
|---|---|
| NOT_READY | Data Quality LOW / applicable core axis < 2 / 未対応 policy version / 入力を解決できない |
| REJECT_RECOMMENDED | Consistency LOW かつ Strength HIGH かつ Time ≥ MEDIUM かつ **反復した** 矛盾 |
| APPROVE_RECOMMENDED | Data Quality HIGH かつ型が approval 可 かつ applicable core すべて ≥ MEDIUM かつ Consistency HIGH かつ Time HIGH かつ（applicable なら）Cross-Regime HIGH |
| REVIEW_RECOMMENDED | Strength ≥ MEDIUM（applicable なら）かつ Time ≥ MEDIUM かつ Consistency ≠ LOW |
| KEEP_REVIEWING | 無条件 fallback（`blocking_rules` に理由を必ず残す） |

矛盾は再現性に勝つ（REJECT が APPROVE より先）。孤立した 1 件の矛盾では絶対に reject しない
（UP/DOWN 各 2 件以上、または双方 support ≥ 2 の sibling 衝突、または support ≥ 2 の DNA CONFLICT）。
証拠不足・span 不足・新しさ・novelty の低さ・Cross-Regime の低さは REJECT の理由にならない。
outlook-free（EVIDENCE_WHY / EVIDENCE_RISK）は v1 REVIEW_ONLY で、REVIEW と REJECT には到達できるが APPROVE は不可。
FULL は `support_ranked=false` で approval 不可。

## 6. Shadow Mode

`eligible < 100` の間は `shadow_mode=true` / `formal_review_gate_reached=false` を全 record に刻む。
`APPROVE_RECOMMENDED` は shadow でも出す（Phase 3.9.4 replay の材料を残すため）が、`SHADOW_ONLY` limitation を付ける。
formal `APPROVED` は Phase 3.9.1 が別途 fail closed で禁じている。

## 7. Storage

`<data_root>/compass_evaluation/`
- `evaluations.jsonl` … 現行 policy での全 pattern 評価。**毎回決定的に置換**（append-only ではない）。
- `evaluation_snapshot.json` … 集計 read model。

evaluation は derived なので append-only にしない。Decision history の純度を保つため、
`compass_decisions/decisions.jsonl` へは絶対に書かない。書き込みは temp file → `os.replace` の atomic 置換。
`derived_digest()` は timestamps を除いた content hash で、replay 同一性の検証に使う。

## 8. CLI

`python -m src.intelligence.evaluation.cli`
- read（書かない）: `validate-policy` / `summary` / `show --pattern` / `list [--state] [--limit]` / `evaluate-one --pattern`
- mutating（derived store のみ）: `evaluate`（`--dry-run` で完全 read-only、`--decision-signals` で reopen 系を read-only 付与）
- exit: 0 = ok / 1 = 見つからない・未評価 / 2 = policy error または store corruption

## 9. Traceability / replay

各 record は axis states・applicability・metrics・reasons、score と comparability、
recommendation と `triggered_rule` / `blocking_rules` / `supporting_rules`、
evaluation と recommendation の policy version + digest、shadow / gate / corpus、`inputs_digest` を持つ。
`inputs_digest` は axis 入力だけの hash（timestamp と policy を含めない）で、
「同じ入力 + 同じ policy → 同じ recommendation」を Phase 3.9.4 が検証できるようにする。
`evaluation_id` も timestamp を含まない決定的 id。

## 10. Deferred（Phase 3.9.3 以降）

review queue の diversity cap / shadow review UI（3.9.3）、replay framework 本体（3.9.4）、
formal DNA review（3.9.5）、recency decay、support density の active 化、market_alignment corroboration、
outlook linkage、prediction validation。v1 には入れない。
