"""evidence — Evidence Engine（Phase 1）。本システムの最重要基盤。

- purpose: 取得物を文単位のEvidenceRecordへ変換し、FACT / FACT_UNVERIFIED /
  ANALYSIS / FORECAST を型として付与・保存する。全FACTは出典へ遡れる。
- boundary: statement_typeを付与できるのはこの層だけ。LLMは抽出の補助にのみ
  使用でき、LLM無しでも動くルールベース経路を必ず持つ。
- future responsibility: Evidence化パイプライン（P1-5）、EvidenceRepository実装、
  出典逆引きAPI。仕様: docs/compass_dna/FACT_ANALYSIS_FORECAST_SPEC.md §5。
"""
