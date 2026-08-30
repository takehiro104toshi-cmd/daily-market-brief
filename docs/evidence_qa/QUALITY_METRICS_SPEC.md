# QUALITY_METRICS_SPEC — 品質メトリクス・QAレポート仕様（Phase 1-E）

## 1. 集計（report.summarize → QAMetrics）

将来監視（Phase 12 Observability）へ接続する最低限の集計:

| 指標 | 内容 |
|---|---|
| total / accepted / accepted_with_warnings / limited / rejected | Gate判定別件数 |
| issue_counts | reason code別件数。以下を含む監督者指定項目が全て集計可能: missing provenance系（missing_source_id/missing_raw_item/broken chain）・stale（stale_for_policy/stale_for_horizon）・conflicting（conflicting_evidence）・partial normalization（normalization_partial）・unsupported（unsupported_fact） |

集計はEvidenceAssessment列の純関数（決定論・offline）。P1-Eではoffline report生成
まで（スケジューラ・ダッシュボードはPhase 12）。

## 2. 人間可読レポート（report.render_report）

Black Box判定禁止の実装。synthetic fixture群に対し「なぜACCEPT/REJECTになったか」を
Markdownで出力する:

- 冒頭: 判定別サマリ＋issue集計（件数降順）
- レコード別: 判定（日本語ラベル付き）・policy name/version・horizon・
  決定根拠code列・**次元別内訳**（OK/WARN/LIMIT/FAIL＋reason code＋detail）

出力例（テストで検証している要素）:

```
### doc_old — 旧記事
- 判定: **LIMITED_USE（用途限定）**（policy: GENERIC v1.0.0）
- 決定根拠: stale_for_policy
- 次元別:
  - provenance: OK
  - freshness: LIMIT [stale_for_policy] — age=960h horizon=-
  ...
```

## 3. reason code語彙

`evidence_qa/model.py REASON_CODES`（約50コード・固定語彙・増設は追記のみ）。
DimensionResult/QAIssueは未知コードを構築時に拒否する（語彙の無秩序な増殖を防ぐ）。

## 4. 保存とtrace

- 全AssessmentはJsonlAssessmentStore（data/vnext/evidence_qa/assessments.jsonl・
  git非管理・append-only・crash-safe）へ追記。
- 再評価履歴は record_id で時系列取得（assessments_for）。現在有効な判定は
  latest_for（履歴からの導出。上書き保存しない）。
- metrics/レポートはストアの内容からいつでも再生成できる（導出物）。
