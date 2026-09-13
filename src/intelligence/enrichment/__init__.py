"""News Enrichment層（Phase 2-E）。

原則:
- CLASSIFICATION IS NOT FACT（分類はFact claimではない。Fact抽出は行わない）
- EVERY ENRICHMENT MUST HAVE PROVENANCE（value/provenance/classifier/version/時刻）
- FALSE ENTITY LINK IS WORSE THAN MISSED ENTITY LINK（高precision優先）
"""
