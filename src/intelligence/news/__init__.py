"""news — News Intelligence Bank（Phase 2）。

- purpose: EvidenceからNews Bank属性（published_at/source/country/ticker/
  industry/theme/summary/importance/confidence等）への構造化と重複統合。
- boundary: 記事の保存はEvidence経由。ここはニュースドメインの索引・統合を担い、
  採点ルール自体はknowledge/のYAMLに置く。
- future responsibility: NewsItemスキーマ確定・NewsRepository実装（P2-4）。
"""
