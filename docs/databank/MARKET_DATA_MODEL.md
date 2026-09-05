# MARKET_DATA_MODEL — Market Bankドメインモデル（Phase 2-A）

## 1. MarketSeries（系列identity）

Observation（P1-A）を長期保存・検索する単位。**hardcodeの巨大一覧は作らない** —
reference model＋決定論的ID規約のみ定め、正規カタログ化はP2-D
（`knowledge/market_series/`予定）。

```
series_id = instrument_id.metric.observation_type[.market_session]
例: index:nikkei225.close.closing.tokyo
    fx:USDJPY.rate.intraday_quote
    rates:UST10Y.yield.closing.ny
    macro:jp_cpi.yoy_pct.economic_statistic
```

`MarketSeries`はseries_idが規約から導出されていることをコンストラクタで強制。
preferred_source_ids（取得優先順・カタログslug）を保持。

## 2. Observation vs Quote（雑に同一視しない）

`ObservationType`: closing / intraday_quote / official_fixing / economic_statistic /
derived_metric。**同じUSDJPYでもspot・Tokyo close・NY closeは別series**
（series_id 3種が相異なることをテストで固定）。

将来のCORE10指標（NIKKEI225/TOPIX/USDJPY/UST10Y/JGB10Y/SP500/NASDAQ/SOX/VIX/
WTI/GOLD等）はこの規約でseries定義される（P2-D）。

## 3. Provenance（P1-A維持＋P2-A追加）

全Observation: source / as_of / retrieved_at系 / unit / calculation_method へtrace可能。
- RAW: source_id必須・calculation_method="api_field:{provider}:{path}"等
- DERIVED: **input observation IDs＋calculation_method必須**（型強制・P1-A維持）
- P2-A追加: `Observation.series_id`（0.x非破壊・既定""）で系列へ紐づけ
- 品質: EvidenceAssessment（P1-E）がobservation_idで横付け（数値sanity・鮮度・依存伝播）

## 4. Decimal / unit（P1-A/P1-D/P1-E方針の継続）

金融値はDecimal（float構築拒否）・unit必須・currency明示・pct/bps/ratioの
明示変換のみ（units.py）。Market Bank固有の追加規則はなし（既存規律が全て適用される）。
