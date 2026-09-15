# TANK_BACKFILL_REPORT — full backfill実行報告（Phase 2-C / 2026-08-30）

## 1. INPUT INVENTORY（実測——件数を盲信しない）

- shard数 27（2026/06・2026/07配下）・**total 3,056 records**（P2-A計測と一致を再確認）
- invalid JSON行: 0 / duplicate legacy id: 0 / date_inferred: 0
- 言語: en 3,041 / ja 15。publisher 42種（Yahoo Finance 608・SCMP 244・Al Jazeera 236…）
- published範囲: 2026-06-22 〜 2026-07-22
- input fingerprint: `7578425805b32592…`（shard一覧×sha256。全run一致を確認）

## 2. EXECUTION STAGES（段階実行）

| stage | 件数 | 結果 | rec/s | メモリ |
|---|---|---|---|---|
| 1 | 100 | 100 success・会計OK・distinct 99/candidate 1 | 152 | 40MB |
| 2 | 500 | 500 success・会計OK・distinct 492/candidate 8 | 182 | 41MB |
| **full** | **3,056** | **3,056 success・0 partial・0 rejected・0 failed** | 52※ | **58MB** |

※full値はinventory（全shard sha256計算）込み。処理系に二次劣化なし（blocking有効）。

## 3. COUNT RECONCILIATION（完全一致）

```
INPUT seen 3,056 = success 3,056 + partial 0 + rejected 0 + failed 0 → OK
NORMALIZED documents 3,056（migration由来・raw_item_id=""明示）
QA assessments    3,056（HISTORICAL v1.0.0・全件ACCEPT_WITH_WARNINGS）
ARTICLES          3,001 = 3,056 − 55（REVISION統合）
NEWS ITEMS        3,001（Article 1:1）
LEGACY ANNOTATIONS 3,056
REJECT ledger     0 / FAILED 0 / CANDIDATES 25（merge せず新Article化・queue保存）
```
record loss不明ゼロ。identity会計: distinct 2,976＋candidate 25＋revision 55 = 3,056。

## 4. ARTICLE IDENTITY RESULT（初のproduction-like実測）

| decision | 件数 | 内容 |
|---|---|---|
| DISTINCT | 2,976 | 新Article |
| **REVISION** | **55** | **同一canonical URL×内容変化。tankが別レコード保存していた「同一記事の更新版」を本層が検出・統合**（例: BBC「Jobs, benefits and taxes…」→「Jobs, borrowing and taxes…」——URL同一・見出し書換の実更新） |
| CANDIDATE | 25 | mergeせずqueue保存。内訳はP2-B校正が予言したハザード族そのもの: FERC Information Collection 8・Yahoo Finance定型 7・ECBカレンダー 1 等 |
| AUTO_MERGE / SYNDICATED / EXACT | 0 | tank格納コーパスは取込時dedup済み（P2-A分析と整合） |

## 5. MERGE AUDIT（55件全件・Black Box merge禁止)

全55件が signal `same_canonical_url,different_fingerprint`（監査JSON全件保存）。
- 53/55はタイトル自体が書き換わった実質更新・2/55はタイトル同一の本文更新。
- 2/55はsource跨ぎ（bbc_business↔bbc_scienv等・**同一URL**を複数BBCフィードが配信
  →同一記事として正しい統合。roleの精緻化（SYNDICATED扱い）はP2-F検討）。
- 誤結合と判定されるペア: **0件**（全ペアのURL一致を機械確認済み）。

## 6. HISTORICAL QA RESULT

3,056件全て `ACCEPT_WITH_WARNINGS`。warning内訳:
`missing_raw_item` 3,056（原文非保存の正直な申告——捏造しない設計の帰結）・
`tier3_general_source` 48。**古さ由来のLIMITED_USEはゼロ**（HISTORICAL policyが
機能。GENERICでは全件LIMITEDだった——P2-A dry run比較）。REJECT 0。

## 7. CANONICAL STORAGE / SQLITE INDEX

- canonical: `data/vnext/databank/`（normalized/ articles/ evidence_qa/ news/ に
  documents・events・assessments・news_items・legacy_annotations・backfill_runs・
  reject_ledgerを分離保存。**Git非管理**）
- SQLite再構築: **0.09秒**・index 3,001 = canonical 3,001・ID uniqueness OK
- query smoke（実corpus）: 7/1〜7/7範囲 74件 / publisher=BOJ 36件 /
  source=bbc_business 89件 / lang=ja 15件 / trust=accept_with_warnings 3,001件
- full corpus validation gate（require_qa=True）: **0 issues**

## 8. PERFORMANCE

full 58.7秒（inventory込み）・peak 58MB・SQLite rebuild 0.09秒。
blocking indexにより比較は候補集合のみ（3,056件で総当たり比較ゼロ）。
