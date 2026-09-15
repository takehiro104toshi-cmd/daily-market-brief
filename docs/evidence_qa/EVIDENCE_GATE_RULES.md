# EVIDENCE_GATE_RULES — Gate判定規則（Phase 1-E）

## 1. 判定の合成規則（明示・決定論）

```
いずれかの次元 FAIL  → REJECT
いずれかの次元 LIMIT → LIMITED_USE
いずれかの次元 WARN  → ACCEPT_WITH_WARNINGS
全て PASS / N-A      → ACCEPT
```

decision_reasonsは判定水準を決めた次元のreason codeを列挙（Black Box禁止）。

## 2. 代表例（テストで固定済み）

| ケース | 判定 |
|---|---|
| Tier1・fresh・provenance完備 | ACCEPT |
| 日付不明だがsource健全（GENERIC） | ACCEPT_WITH_WARNINGS |
| 日付不明（DAILY_MARKET） | LIMITED_USE |
| 古い一般記事（30日超） | LIMITED_USE |
| provenance欠落（locator/source_id/content_hashなし） | REJECT |
| blob hash不一致・raw参照切れ | REJECT |
| Evidenceゼロ Fact（UNSUPPORTED） | REJECT |
| 支持＋反証併存 Fact | LIMITED_USE |
| superseded文書（DAILY_MARKET） | LIMITED_USE |
| 明示的RETRACTED | REJECT（監査・歴史用途では保存継続） |
| usage RESTRICTED | ACCEPT_WITH_WARNINGS（trustと権利を混同しない） |

## 3. 次元別の主要規則

- **PROVENANCE**: source_id / content_hash / locator欠落=FAIL。
  raw_item_id空（原文非保存の明示）=WARN（断絶=raw_item_not_foundとは区別）。
  derived observationのinputs欠落=FAIL。
- **SOURCE_QUALITY**: Tier3・LOW価値=WARN。Tier1でもPASS以上にはならない（≠truth）。
- **SOURCE_HEALTH**: 現在deadでも文書はWARN止まり（**文書の有効性と分離**）。
- **FRESHNESS**: policy閾値＋horizon上限。published不明はN/A（DATE_QUALITYが担当）。
- **DATE_QUALITY**: 不明=policy依存（WARN/LIMIT。即REJECTしない）。inferred/naive=WARN。
- **CONTENT_INTEGRITY**: blob hash再計算不一致・raw参照切れ・serialization破損=FAIL。
- **CONFLICT**: 矛盾Evidence併存=LIMIT（**自動FALSE判定しない**。両論保持）。
- **REVISION**: superseded=policy依存（WARN/LIMIT）。retractedは**明示evidenceのみ**でFAIL。
- **DUPLICATION**: fingerprint一致×別source=WARN（転載）。
  corroborationは独立系統数（duplicate_group単位）で数える。
- **OBSERVATION_VALIDITY**: NaN/Inf・不可能な負値=FAIL（**補正はしない**）。
  異常%・通貨不整合・未来as_of=LIMIT。欠測値=WARN（捏造しない）。
- **NORMALIZATION_QUALITY**: REJECTED正規化=FAIL。PARTIAL=WARN（issue内容付き）。
- **USAGE_RIGHTS**: restricted=WARN（内容の正しさとは独立）。

## 4. DEPENDENCY PROPAGATION（自動削除しない）

```
上流 REJECT  → 下流 SUPPORT次元 = LIMIT（dependency_rejected）→ LIMITED_USE
上流 LIMITED → 下流 WARN（dependency_limited）
上流 未評価  → 下流 WARN（dependency_unassessed）
```

適用: Fact（支持Evidence全滅→weak_supporting_evidence）、Analysis（入力Fact）、
Forecast（supporting evidence）、derived Observation（入力Observation）。
下流レコード自体は削除・変更されない（用途制限のみ）。
