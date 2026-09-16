"""Raw Ingestion（Phase 1-C）。

パイプライン（God Fetcher禁止・各段を1ファイルで分離）:

    SourceEndpoint
      → FetchRequest（transport.py が構築規約を持つ）
        → HttpTransport（Protocol。実装: UrllibTransport / テスト用スタブ）
          → FetchResponse
            → fetcher.Fetcher（retry・conditional GET・redirect記録・redaction）
              → FetchAttempt（取得試行の時系列記録。RawItemが生まれない試行も残す）
              → RawItem ＋ blob（raw_store.py: immutable・atomic・content-addressed）
            → feed_parser（RSS2/Atom/RDF/JSON検出。Factへは変換しない）

原則:
- RAW DATA IS IMMUTABLE（上書きしない。同一URLの内容更新は新RawItemとして積む）
- Secret値はどこにも保存しない（URLはredact、禁止ヘッダはFetchRequestが拒否）
- HTTPライブラリへの直接依存はtransport実装1箇所のみ（domain/parser/storeは非依存）
"""
