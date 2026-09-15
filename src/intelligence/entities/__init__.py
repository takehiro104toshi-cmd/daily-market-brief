"""entities — 名寄せ（Phase 2）。

- purpose: 企業名⇄証券コード/ティッカー⇄業種⇄テーマの解決。
  knowledge/（旧config sectors/themes/watchlist由来）を辞書の種とする。
- boundary: 静的辞書＋決定的ルールを基本とし、曖昧解決の推測は confidence 付きで返す。
- future responsibility: resolver実装・EDINETコード等の財務ID付与（P2-5、Phase 8準備）。
"""
