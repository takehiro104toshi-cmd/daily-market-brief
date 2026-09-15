"""Compass Evaluation Engine（Phase 3.9.2）— frozen 6 axis → Reference Score → Recommendation。

    Phase 3.8 research artifact（読むだけ）
      → 6 axis（Evidence Strength / Time Stability / Cross-Regime / Consistency / DNA Novelty / Data Quality）
      → Reference Score（secondary。構造的 N/A は weight ごと除外して再正規化）
      → Recommendation（NOT_READY > REJECT > APPROVE > REVIEW > KEEP_REVIEWING、first match wins）
      → derived evaluation store（rebuildable）

境界（Phase 3.9.1 から継承・強化）:
- APPROVE_RECOMMENDED ≠ APPROVED ≠ PROMOTED_TO_DNA。engine は助言するだけで Decision を書かない。
- formal APPROVED は Phase 3.9.1 の CORPUS_100 gate が fail closed で守る。ここは shadow フラグを記録する。
- Reference Score は state transition に使わない（policy が True を拒否する）。
- DNA Novelty は approval 要件ではなく、弱い evidence を救済しない。
- 構造的 NOT_APPLICABLE は「試験が成立しない」ときだけ。証拠不足は NOT_APPLICABLE ではない。
- production DNA / Corpus / Phase 3.8 artifact / decision history は書き換えない。外部 LLM を使わない。
- 出力に PDF 本文・observation text・file path を入れない（id / count / label / version だけ）。

1機能=1ファイル:
    config.py         compass_evaluation / compass_recommendation policy（versioned・digest・fail closed）
    models.py         AxisResult / EvaluationRecord / schema validation / deterministic id / inputs_digest
    contradiction.py  現行 registry から再計算する contradiction 索引（stale queue を信頼しない）
    axes.py           6 axis の frozen classifier
    score.py          Reference Score（N/A 再正規化・NOT_COMPARABLE floor）と review ordering key
    rules.py          recommendation precedence（first match wins）
    store.py          derived evaluation store（atomic replace。append-only の decision store とは別）
    engine.py         orchestration（read-only inputs → evaluate → derived store）
    cli.py            evaluate / evaluate-one / show / summary / list / validate-policy
"""
