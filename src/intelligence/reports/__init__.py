"""reports — レポート生成（Phase 3-4）。

- purpose: Compass Generator（日次詳細版）とMorning Brief（30秒/3分/詳細）の組版。
  knowledge/compass_dna/market_rules.yaml のルール評価結果とEvidenceを材料に、
  「事実→原因→影響→見通し→注目」の因果構造で出力する。
- boundary: この層は自分でデータ取得をしない。LLMはEvidence ID参照付きの文章化のみ
  （contracts.LLMProvider経由・ルールベースフォールバック必須）。
- future responsibility: ルール評価器・組版・LLM Writer（P3-1〜P3-5、P4-1〜P4-3）。
"""
