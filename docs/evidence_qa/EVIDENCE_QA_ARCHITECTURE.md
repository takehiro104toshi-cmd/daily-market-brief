# EVIDENCE_QA_ARCHITECTURE — Evidence QA / Trust Gate全体設計（Phase 1-E / 2026-08-30）

目的: Normalized SourceDocument / Observation（＋Fact/Analysis/Forecast）を
「存在する情報」から「**分析に利用してよいEvidence**」へ昇格させる品質判定層。
Compass Generator / News Bank / Prediction / Theme Engineは利用前にこの関門を通す。

## 1. CORE PRINCIPLE

```
存在する情報   ≠ 信頼できるEvidence
HTTP 200      ≠ 正しい情報
Tier 1        ≠ 常に正しい（source qualityは13次元の1つにすぎない）
複数source一致 ≠ 必ず真（転載10件 ≠ 独立10source）
AI生成        ≠ Fact（SUPPORTSリンクなし→UNSUPPORTED→REJECT）
```

## 2. パイプライン位置とモジュール（God object禁止の分割）

```
Raw → Parsed → Normalized → 【Evidence QA / Trust Gate】→ TRUSTED/USABLE/LIMITED/REJECTED
```

| モジュール | 責務 |
|---|---|
| model.py | QADimension(13) / DimensionStatus / DimensionResult / QAIssue / GateDecision / EvidenceAssessment / SourceInfo |
| policy.py | TrustPolicy（name＋version）・GENERIC/DAILY_MARKET・registry（version上書き禁止） |
| dimensions.py | 次元別評価器（純関数・決定論。基準時刻は注入） |
| gate.py | 次元結果→GateDecision（明示規則）・issue平坦化 |
| assess.py | record種別ごとのオーケストレーション・依存伝播 |
| store.py | append-onlyのassessment永続（data/vnext/evidence_qa/） |
| report.py | 品質メトリクス集計＋人間可読レポート（Black Box禁止） |

## 3. 13 QA次元（単一scoreへ潰さない）

PROVENANCE / SOURCE_QUALITY / SOURCE_HEALTH / FRESHNESS / DATE_QUALITY /
CONTENT_INTEGRITY / CONFLICT / REVISION / DUPLICATION / OBSERVATION_VALIDITY /
SUPPORT / USAGE_RIGHTS / NORMALIZATION_QUALITY。

各次元は PASS / WARN / LIMIT / FAIL / NOT_APPLICABLE ＋ reason codes（語彙固定）を持つ。
「Evidence Score = 82」のような総合値は持たない——後から
「Freshnessの問題かSourceの問題かConflictか」が判別できることを正とする
（補助scoreが必要になったら次元別評価から導出する。逆は不可）。

## 4. 評価対象と適用次元

| record_type | 適用次元 |
|---|---|
| source_document | PROVENANCE / SOURCE_QUALITY / SOURCE_HEALTH / FRESHNESS / DATE_QUALITY / CONTENT_INTEGRITY / REVISION / DUPLICATION / NORMALIZATION_QUALITY / USAGE_RIGHTS |
| observation | PROVENANCE / SOURCE_QUALITY / SOURCE_HEALTH / FRESHNESS(as_of) / OBSERVATION_VALIDITY / USAGE_RIGHTS（＋derivedはSUPPORT=依存伝播） |
| fact | SUPPORT / CONFLICT / DUPLICATION(corroboration独立性) / FRESHNESS(event_time) |
| analysis | PROVENANCE(inputs/rule_id/agent) / SUPPORT(依存伝播) |
| forecast | PROVENANCE / SUPPORT(支持EvidenceのGate結果) |

## 5. 決定論・説明可能性

- 基準時刻（assessed_at=freshness基準）・policy・全入力を引数注入。LLM・乱数なし
  （ベンダー中立importスキャンが evidence_qa/ を自動走査）。
- 全判定が decision_reasons（機械可読）＋ render_report（人間可読・日本語）で説明される。
- EvidenceAssessmentは assessment_id / record_id / record_type / assessed_at /
  policy_name / policy_version / horizon / dimensions / issues / decision /
  decision_reasons を保持（監督者指定フィールド全て）。

## 6. Fact抽出はしない（SCOPE CORRECTION遵守）

P1-Eは品質判定層のみ。自由文ニュースからのLLM Fact大量生成は未実装。
Trust Gateの検証は synthetic FactStatement fixture（tests/intelligence/qa_fixtures.py）
で行った（Fact A=Tier1支持→ACCEPT / Fact B=Evidenceなし→REJECT /
Fact C=支持＋反証→LIMITED_USE を含む監督者指定fixture全種）。
