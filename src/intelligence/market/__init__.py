"""market — 市場データバンク（Phase 2）。

- purpose: CORE/SUPPORT/CONTEXT指標（docs/compass_dna/MARKET_DATA_TAXONOMY.md）の
  時系列保存と、派生指標（25日/200日MA乖離・SOX相関・breadth・V/G比）の計算。
- boundary: 値の捏造をしない（欠測はNone）。unit/calc_methodをデータに内包する。
  Legacy market_data.py（yfinance+Stooq）はadapter経由でfetch部のみ再利用予定。
- future responsibility: MarketRepository実装、派生指標エンジン（P2-1〜P2-3）。
"""
