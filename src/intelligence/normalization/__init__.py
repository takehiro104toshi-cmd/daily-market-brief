"""Normalization & Evidence Creation（Phase 1-D）。

レイヤー分離（本パッケージが扱うのはNORMALIZEDまで）:

    RAW         取得した原データ（ingestion/が所有。immutable）
    PARSED      構造を読み取ったもの（feed_parser等のtransient出力）
    NORMALIZED  共通domain語彙へ変換したもの（SourceDocument / Observation）★ここまで
    INTERPRETED 意味・因果・投資判断（P1-E以降。本パッケージでは禁止）

原則:
- **決定論**: 同じRawItem＋同じnormalizer versionから必ず同じ結果。LLM・現在時刻・
  乱数・外部検索に依存しない（処理時刻はNormalizationEventのみが持ち、
  レコード内容のsemantic equalityへ影響しない）。
- **自由文Fact生成禁止**: 記事タイトルからFactStatementを自動生成しない。
  SourceDocumentとして保存するまでが本層の責務（Fact化はP1-E Evidence QA対象）。
- **Silent correction禁止**: 欠損・異常はstructured issueとして記録する。
  published_at=unknown は正しい結果として許容する。
"""
