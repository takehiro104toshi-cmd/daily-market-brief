"""Market / News Data Bank（Phase 2-A: domain schema＋基盤のみ）。

原則:
- **SourceDocument ≠ Article ≠ News Event** を分離する（news_model.py）。
  Reuters記事とYahoo転載は別SourceDocumentだが、将来同一Articleへclusterされうる。
  P2-Aではidentity modelの設計まで（semantic clustering本体はP2-B）。
- God NewsItem禁止: classification / score / entity参照は独立レコード。
- classification value と classification **provenance** を分ける
  （SOURCE_EXPLICIT / RULE_BASED / ENTITY_DATABASE / LLM / USER）。
- NewsItem metadataとFactStatementを混同しない（headlineはmetadata、
  「売上が20%増えた」等のclaimはFact層。P2-AではFact抽出しない）。
- tankのINTERPRETED値（importance/theme/sentiment等）は新Truthにせず
  legacy_annotationとして隔離する。
- 自動score生成・LLM分類・semantic dedupはP2-B以降（本パッケージ未実装）。
"""
