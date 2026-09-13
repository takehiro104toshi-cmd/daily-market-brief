# END_TO_END_VALIDATION — 実データ一本通し検証結果（Phase 2-A / 2026-08-30）

実行: GitHub Actions run 33286370072（`p2a-e2e-pilot.yml`・2026-08-30 01:44 UTC・
7ソース×各1リクエスト・Secrets不使用・**途中のmockなし**）。
パイプライン: SourceRegistry→SourceEndpoint→UrllibTransport→FetchAttempt→RawItem→
RawStore→FeedParser→Normalizer→SourceDocument→EvidenceAssessment→GateDecision。

## 1. 成功系（5ソース・全てGate到達）

| source | tier | HTTP | body | 文書数 | 正規化 | Gate判定内訳 |
|---|---|---|---|---|---|---|
| boj_whatsnew | 1 | 200 | 15,606B | 46 | NORMALIZED（issue 0） | accept 1 / warn 45 |
| fed_press | 1 | 200 | 14,391B | 20 | NORMALIZED（issue 0） | accept 1 / warn 11 / limited 8 |
| dmb_ecb_press | 1 | 200 | 5,784B | 15 | NORMALIZED（issue 0） | accept 2 / warn 8 / limited 5 |
| nhk_business | 2 | 200 | 59,292B | 86 | NORMALIZED（issue 0） | warn 86 |
| theverge | 2 | 200 | 32,659B | 10 | NORMALIZED（issue 0） | accept 10 |

計: **177 SourceDocument・177 EvidenceAssessment**を実ネットワークから3秒で生成。
異なるtier（1/2）・publisher（中銀2・政府1・公共放送1・専門メディア1）・
言語（en/ja）・地域（JP/US/EU）を包含。判定分布はGENERIC policyの想定通り
（accept=fresh＆完全 / warn=aging等 / limited=フィード内の30日超の旧エントリ）。

## 2. 失敗系（正常なfailure path）

| source | HTTP | 確認事項 |
|---|---|---|
| dmb_boj_whatsnew | **404** | FetchAttemptは記録 / RawItemなし / 正規化なし / **Assessmentなし** |
| bls_latest | **403**（vNext UA拒否） | 同上 |

**NO FALSE EVIDENCE**: fetch失敗・parser失敗・正規化REJECTからACCEPTが生成される
経路は存在しない（実測0件＋integration test `test_no_false_evidence_invariant` が
404/403/timeout/HTML/garbage全ケースで機械的に固定）。

## 3. 実記事のEnd-to-End逆引きtrace（実測ログより転記）

```
assessment qa_01M185EP56XGFVSR0DCQJ3716T
- 判定: accept（policy GENERIC v1.0.0）・根拠:（全次元PASS）
  ↓
document doc_1c5cffb61415667b5648b93a
- title: (BOJ Review) Expanding and Revising the Application of Hedonic
  Quality Adjustment in the Corporate Goods Price Index
- published: 2026-08-28T05:00:00+00:00（quality=source_provided_tz, inferred=False）
- normalizer: feed_entry v1.0.0
  ↓
raw item raw_aba58531fcd2847a45818328
- retrieved_at: 2026-08-30T01:44:56 / 15,606B / sha256 1433e5703b58887f…
  ↓
fetch attempt fetch_01M185ENSBYQMXYP3QANX4V05D
- HTTP 200 / 355ms / retries=0
  ↓
endpoint ep_34b7034b66d6a0275f307c8e（https://www.boj.or.jp/en/rss/whatsnew.xml）
  ↓
source boj_whatsnew（Bank of Japan — What's New）tier1 / CORE / healthy
```

「このニュースはどこから来たのか」に1本のchainで回答できることを実データで確認。

## 4. Phase 1統合の所見（INTEGRATION FINDINGS）

1. **全層が無修正で結合した**: P1-C fetcher・P1-D normalizer・P1-E QAは
   一切の変更なしにpipeline編成だけで動作（層境界設計の妥当性の実証）。
2. fed_pressはvNext UAで2回連続200＋20件パース — Legacy CI恒常失敗が
   クライアント条件であることを重ねて確認（SOURCE_GAPS G4関連）。
3. bls_latest 403はfailure pathの実live検証として機能（UA戦略はSOURCE_GAPS G4）。
4. NHK 86件が全てACCEPT_WITH_WARNINGS＝カタログ済みフィードの古めエントリに
   aging警告が付く挙動。日次運用ではconditional GET（実装済み）により
   2回目以降は304で新規エントリのみが対象になる。
5. 177評価/3秒（ネットワーク込み）— 日次規模（数十ソース）の性能懸念なし。

## 5. 再現方法

`.github/p2a_e2e_trigger` を更新してpush（feature branch限定）。
結果はActionsログの `::E2E_RESULT::` 行と `::E2E_TRACE_BEGIN::` ブロック。
オフライン相当の検証は `tests/intelligence/test_pipeline_e2e.py`（6件）。
