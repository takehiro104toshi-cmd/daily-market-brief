"""Japan Market Internals（Phase 3.5）。

日本株市場の「指数の値」だけでなく**市場内部で何が起きているか**（騰落銘柄数・
売買代金・業種／規模別の相対パフォーマンス・投資部門別フロー・指数の主導構造）を
Evidence-Groundedに観測可能にする層。

DATA(J-Quants Light daily bars / master / investor-types)
  → aggregation（universe版・calculation版・manifestで再現可能）
  → FACT（Phase 3-A Fact Layerへ正規接続。別のFact概念を作らない）
  → CONTEXT（Phase 3-B Context Engineへ接続。因果を主張しない）
  → Morning Snapshot（market_internals 次元の充足状況）
  → Compass Evidence Package（通常Contextとして受け取る。Generatorは既存validator経路）

規律: 因果説明をしない／週次データを日次として語らない／取得できないものを推測しない／
Standard・Premium限定データを迂回取得しない／恣意的なscoreを作らない。
"""
