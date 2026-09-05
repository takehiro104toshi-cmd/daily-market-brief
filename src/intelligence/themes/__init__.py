"""themes — Theme Map（Phase 6）。

- purpose: テーマグラフ（knowledge/theme_relations/ が初期グラフ）の管理と、
  ニュース量・増加率・企業言及からのEmerging Theme検出。
- boundary: グラフ定義（知識）はknowledge/、計測値（データ）はdata/。この層は計算のみ。
- future responsibility: グラフ探索・テーマ計測・Emerging検出
  （docs/compass_dna/THEME_DISCOVERY_RULES.md §5のシグナル実装）。
"""
