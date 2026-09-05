# PHASE2_RECONCILIATION — Phase 2全record種の会計検証（Phase 2-F PART A / 2026-08-30）

実装: `src/intelligence/databank/phase2_audit.py`（`build_phase2_reconciliation`）。
目的: **「どこかで何件消えたか不明」= ZERO UNKNOWN LOSS の機械証明**。

## 1. News Bank（実data root実測）

```
tank入力（P2-C inventory・fingerprint 7578425805b32592…）    3,056
= News SourceDocuments                                      3,056
= LegacyAnnotations                                         3,056（doc 1:1）
= identity判定 distinct 2,976 + candidate 25 + revision 55  3,056 ✅（恒等式）
Articles = NewsItems = distinct + candidate                 3,001 ✅
EvidenceAssessments  6,112 = HISTORICAL v1.0×3,056 ＋ v1.1×3,056
                     （再評価は追記——NO RETROACTIVE DELETE）✅
Classifications      3,592（全てitems内へ解決・orphan 0）✅
Enrichment ReviewQueue 63 / Identity Candidates 25 / Revisions 55
  → Review層へ88件intake（=25+58+5。冪等・重複なし）✅
Identity Decision Ledger 25（candidate全件・post_hoc derivation明示）✅
Revision Roles 55 = same_publisher_update 53 + cross_feed_same_article 2 ✅
recovered_lines（全store）                                   0 ✅
duplicate ID                                                 0 ✅
SQLite index（news_items 3,001・classifications 3,592）= canonical ✅
```

**issues: []・zero_unknown_loss: true**（機械判定）。

## 2. Market Bank

market canonicalはlive pilot（Actions runner）上に構築される（本data rootには
未蓄積——healthがmarket_bank_not_localとして正直に申告）。runner上の会計は
run manifest＋pilot markersで検証済み:
```
requested 15 = success 12 + gap 3 + failed 0
canonical 16,512 = raw 3,432 + derived 13,080
QA assessments = 全observation（+再評価分は追記）
別プロセスreopen・index全再構築・latest 12/12一致
```
（run #4/#5実測。詳細: MARKET_BACKFILL_REPORT.md / MARKET_OBSERVATION_TRUST_POLICY.md）

## 3. schema versions

canonicalに共存する版: **0.3.0**（P2-C書込み時点のレコード）＋**0.4.0**（P2-D以降）。
0.x前方互換規約（未知フィールド無視・додefault補完）により全レコード読取可能
——SCHEMA_INVENTORY.md参照。

## 4. 検査項目（毎回機械実行）

record counts / duplicate IDs / orphan references（classifications→items・
annotations→docs・items→primary docs）/ identity会計恒等式 / QA coverage /
source provenance欠落 / schema versions / SQLite vs canonical / market同型検査。
検知のみ（自動修復しない）。合成データでの破壊注入テストで各検知を固定済み。
