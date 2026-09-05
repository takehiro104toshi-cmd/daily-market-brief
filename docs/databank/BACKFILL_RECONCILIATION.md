# BACKFILL_RECONCILIATION — 会計検証（Phase 2-C / run bfr_… 2026-08-30）

## 1. 会計恒等式（record loss不明ゼロ）

```
INPUT（実測inventory）                    3,056
  = records_seen                          3,056
  = success 3,056 + partial 0 + rejected 0 + failed 0   ✅ 完全一致
```

## 2. 段間の数の関係（全て説明可能）

```
INPUT                          3,056
→ NORMALIZED SourceDocument    3,056   （reject 0のため1:1）
→ HISTORICAL QA assessments    3,056   （全document評価・qa_result_missing 0）
→ ARTICLES                     3,001   （= 3,056 − REVISION統合55。
                                         distinct 2,976 + candidate新規 25 = 3,001✓）
→ NEWS ITEMS                   3,001   （Article 1:1・orphanなし）
→ LEGACY ANNOTATIONS           3,056   （document 1:1）
→ REJECT LEDGER                    0
→ CANDIDATE QUEUE                 25   （CREATE event decision_kind=candidateで永続）
```

identity会計: 2,976 (distinct) + 25 (candidate) + 55 (revision merge) = 3,056 ✅

## 3. index照合

canonical news_items 3,001 = SQLite index 3,001 ✅ / ID uniqueness ✅ /
orphan refs 0（full corpus validation・require_qa=True で0 issues）✅

## 4. fingerprint整合

inventory fingerprint = run manifest input_fingerprint（全stage・full一致:
`7578425805b32592…`）——移行中の入力変化なし ✅

## 5. 冪等・resumeの検証（合成データセットでのテスト固定）

- resume再実行: seen 0・canonical不変
- 完全再実行（resume無効）: canonical件数不変（決定論的ID＋冪等add）
- crash（注入）→resume: clean一発実行とcanonical完全一致
