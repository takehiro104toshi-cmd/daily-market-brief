"""sources — 外部情報の取得層（Phase 1）。

- purpose: RSS/API/公式発表/PDF等からの取得のみを担う。解釈・採点はしない。
  取得物はraw body・URL・retrieved_at・SourceTier付きで下流（evidence）へ渡す。
- boundary: ネットワークに触れてよいのはvNextでこの層だけ。knowledge/の
  source_feeds.yaml / source_tiers.yaml をカタログとして読む。Legacy collectorsは
  importしない（news.pyのRSSパース・重複統合ロジックはPhase 1でここへ「移植」する）。
- future responsibility: fetcher基盤（UA/timeout/retry/raw保存）、Atom対応パーサー、
  フィード死活の記録（P1-2/P1-4/P1-8）。
"""
