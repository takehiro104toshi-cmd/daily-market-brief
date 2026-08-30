# MARKET_OBSERVATION_TRUST_POLICY — Market観測のtrust意味論v2（Phase 2-F PART E）

## 1. 問題（P2-Dの恒常warning）

market Observationは設計上FactStatementを持たない（RAW/NORMALIZED層の数値記録
であり、INTERPRETED層の主張ではない）。しかしHISTORICAL v1.0.0のsupport次元は
「SUPPORTS linkの実在」を要求するため、**全raw観測がmissing_supporting_evidence_ref
でACCEPT_WITH_WARNINGS**になっていた——観測の実態に合わない評価語彙だった。
監督者指示: 「warningを単純に削除してはならない。Observation固有のtrust semantics
として再設計する」。

## 2. 解決 — provider経路provenance

market観測の信頼は**SUPPORTS linkではなくprovider経路**で立証する:

```
Observation → provider payload（raw blob / RawItem） → provider
            → FetchAttempt（live取得） or import provenance（移行由来）
```

実装:
- `ProviderTrace`（`evidence_qa/assess.py`・frozen）: `provider_id` ＋
  `fetch_attempt_id` | `raw_payload_ref` | `import_provenance` のいずれか1つ以上で
  `.verified`。import由来はdataset fingerprint等を`import_provenance`に載せ、
  MIGRATED_PROVENANCE_SPEC.mdと同じ意味論に乗る。
- 新policy **MARKET_OBSERVATION v1.0.0**（`observation_provider_provenance=True`）:
  support次元をprovider経路で評価。trace verified → PASS
  （reason code `provider_provenance_verified`）。trace欠落 → **WARN
  `missing_provider_trace`**（provenance欠落は引き続き許容しない）。
- 旧policy（HISTORICAL/GENERIC/DAILY_MARKET）は挙動不変
  （`observation_provider_provenance=False`のまま——後方互換）。
- engine結線: `market/backfill.py`がQA時に実FetchAttempt/RawItemから
  ProviderTraceを構築して渡す。SUPPORTS linkは**非必須方向**へ変更（linkが
  在れば従来通り評価に使える）。

## 3. 再評価結果（live run #5実測・NO RETROACTIVE DELETE）

Actions runner上の実データ（raw観測3,432件・12系列）を再評価（::P2F_REASSESS::）:

| | HISTORICAL v1.0.0（旧・保持） | MARKET_OBSERVATION v1.0.0（新規追記） |
|---|---|---|
| ACCEPT | 0 | **3,432** |
| ACCEPT_WITH_WARNINGS | 3,432 | 0 |
| missing_supporting_evidence_ref | 3,432 | **0** |

- 旧assessmentは削除せず併存（`old_assessments_preserved: true`。canonical
  assessments 19,945 = 全観測16,512 ＋ 再評価3,432 ＋ daily QA 1）。
- 別プロセスreopen・index全再構築・latest 12/12一致（::P2D_PERSISTENCE:: ok）。
- backup manifest_20260830T065929Z（21ファイル・46.7MB・verify 0/0/0）。

## 4. 規律

- **fake FetchAttempt / RawItemの捏造は禁止**——traceは実在レコードのIDのみ。
- 評価はappend-only。policy名+版が全assessmentに残り、いつどの規準で
  評価したか機械比較できる。
- trace無し観測がACCEPTになる経路は存在しない（テスト固定:
  `test_trust_policy_v2.py`）。
