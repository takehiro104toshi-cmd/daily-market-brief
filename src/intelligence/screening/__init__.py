"""screening — Long-Term Stock Screener（Phase 8）。

- purpose: Financial Quality × Structural Trend の複合スコアで5-10年保有候補を探索。
- boundary: 単なるPER/PBRスクリーナーにしない。テーマ適合はthemes層、財務は
  entities層の財務IDに基づく取得層から受け取る。
- future responsibility: スコアリング・自然文検索（P8-1〜P8-3）。
"""
