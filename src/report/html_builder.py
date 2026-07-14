"""Market Intelligence System v4 の朝レポートを、スマホ閲覧前提のHTML（カードUI）で組み立てる。

外部CSS・外部JSには依存しない自己完結型のHTMLを1ファイルで生成する
（GitHub上でもローカルでもそのままブラウザで開ける）。

色分けルール:
  - 上昇（前日比プラス） = 緑
  - 下落（前日比マイナス） = 赤
  - 横ばい・データなし = 灰色

Markdown版（builder.py / mobile_builder.py）と同じ AnalysisBundle を
そのまま再利用し、HTML側で新たな考察ロジックは持たない
（見せ方だけを変える「レンダラー」に徹する）。
"""
from __future__ import annotations

import html
import re
from datetime import datetime, timezone
from typing import List, Optional

from ..analysis.models import (
    AnalysisBundle,
    CallPriorityEntry,
    ExecutiveSummaryItem,
    InstrumentScenario,
    KeyLevelEntry,
    MarketImpactEntry,
    MorningMeetingComment,
    NewsRankingItem,
    OkasanSalesComments,
    LearningHistoryEntry,
    QAItem,
    RashinbanKnowledge,
    SalesComments,
    ScenarioV2Entry,
    ThemeLearningStat,
    SectorRankingEntry,
    SectorStrengthEntry,
    StockRankingEntry,
    FutureIntelligenceBundle,
    StrategistView,
    ThemeForecast,
    TopPickEntry,
    WatchlistQuickEntry,
    WeeklyEventEntry,
)
from ..analysis.data_freshness import (
    DataFreshnessStats,
    availability_stars,
    freshness_label,
    freshness_stars,
)
from ..analysis.source_trust import combined_trust_for_sources, trust_for_source
from ..analysis.anomaly import AnomalyEntry, anomaly_status_label, detect_anomalies
from ..collectors.market_data import Quote
from ..collectors.news import parse_published_datetime
from ..utils import SourceRegistry
from .format_utils import NOT_AVAILABLE, find_quote, fmt_change_compact, fmt_price, todays_action_items

STYLE = """
:root {
  --up: #1a7f37; --up-bg: #e6f4ea;
  --down: #c62828; --down-bg: #fdeaea;
  --flat: #616161; --flat-bg: #eeeeee;
  --card-bg: #ffffff; --page-bg: #f5f6f8; --border: #e0e0e0; --text: #1f2328;
}
:root[data-theme="dark"] {
  --card-bg: #1c1f26; --page-bg: #0f1115; --border: #33363d; --text: #e5e7eb;
  --up-bg: #123420; --down-bg: #401414; --flat-bg: #2a2d33;
}
:root[data-theme="dark"] .toc,
:root[data-theme="dark"] .fi-toc,
:root[data-theme="dark"] .todays-action,
:root[data-theme="dark"] .options-card,
:root[data-theme="dark"] .legend,
:root[data-theme="dark"] .digest,
:root[data-theme="dark"] .fi-block-signals,
:root[data-theme="dark"] .fi-block-theme,
:root[data-theme="dark"] .fi-block-industry,
:root[data-theme="dark"] .fi-block-stock,
:root[data-theme="dark"] .fi-block-longterm {
  background: var(--card-bg); color: var(--text); border-color: var(--border);
}
:root[data-theme="dark"] .legend { color: #cbd5e1; }
:root[data-theme="dark"] .fresh-new { background: #3f1d1d; color: #fca5a5; }
:root[data-theme="dark"] .fresh-48 { background: #3d2c12; color: #fbbf24; }
html { scroll-behavior: smooth; }
* { box-sizing: border-box; }
body {
  margin: 0; padding: 0 0 32px 0; background: var(--page-bg); color: var(--text);
  font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", "Hiragino Kaku Gothic ProN", Meiryo, sans-serif;
  line-height: 1.6;
}
.header { background: #1f2937; color: #fff; padding: 20px 16px; }
.header h1 { margin: 0 0 6px 0; font-size: 1.3rem; }
.header p { margin: 0; font-size: 0.85rem; color: #cbd5e1; }
.container { max-width: 720px; margin: 0 auto; padding: 16px; }
.card {
  background: var(--card-bg); border: 1px solid var(--border); border-radius: 12px;
  padding: 14px 16px; margin-bottom: 14px; box-shadow: 0 1px 2px rgba(0,0,0,0.04);
  scroll-margin-top: 12px;
}
.card h2 { font-size: 1.05rem; margin: 0 0 10px 0; }
.card h3 { font-size: 0.95rem; margin: 10px 0 6px 0; }
.toc { background: #f9fafb; }
.toc-list { columns: 2; column-gap: 16px; padding-left: 18px; margin: 4px 0; list-style: none; }
.toc-list li { margin-bottom: 6px; font-size: 0.85rem; break-inside: avoid; }
.toc-list a { text-decoration: none; }
.fi-toc { background: #eef2ff; border-radius: 8px; padding: 10px 14px; margin-bottom: 14px; }
.fi-toc ul { margin: 4px 0; padding-left: 18px; }
.fi-toc a { text-decoration: none; font-size: 0.85rem; }
.fi-block { border-radius: 10px; padding: 12px 14px; margin: 14px 0; border: 1px solid var(--border); scroll-margin-top: 12px; }
.fi-block h4 { font-size: 0.95rem; margin: 12px 0 6px 0; }
.fi-block h5 { font-size: 0.88rem; margin: 8px 0 4px 0; }
.fi-block-desc { font-size: 0.82rem; color: #555; margin: 2px 0 10px 0; }
.fi-stars { font-size: 0.8rem; color: #444; margin-left: 6px; }
.fi-block-signals { background: #eaf2ff; border-color: #b6d4fe; }
.fi-block-theme { background: #f3ecfb; border-color: #d9c2f0; }
.fi-block-industry { background: #eaf7ee; border-color: #b7e4c7; }
.fi-block-stock { background: #fff1e6; border-color: #ffcc99; }
.fi-block-longterm { background: #fdf6e3; border-color: #f0dfa1; }
.todays-action { background: #fff7e6; border: 1px solid #f3d98a; border-radius: 8px; padding: 10px 14px; margin-bottom: 14px; }
.card-head { display: flex; align-items: center; justify-content: space-between; gap: 8px; }
.card-head h2 { margin: 0 0 10px 0; }
.card-actions { display: flex; gap: 2px; align-items: center; flex-shrink: 0; }
.copy-btn {
  border: none; background: transparent; cursor: pointer; font-size: 1rem; line-height: 1;
  padding: 6px 8px; border-radius: 6px; color: #6b7280; flex-shrink: 0;
}
.copy-btn:active { background: var(--flat-bg); }
.fav-btn, .collapse-btn {
  border: none; background: transparent; cursor: pointer; font-size: 1.05rem; line-height: 1;
  padding: 6px 6px; border-radius: 6px; color: #9ca3af; min-width: 34px; min-height: 34px;
}
.fav-btn.fav-on { color: #f59e0b; }
.card-collapsed .card-body { display: none; }
.card-desc { font-size: 0.78rem; color: #6b7280; margin: 0 0 8px 0; }
.menu-card { padding: 10px 12px; }
.menu-grid { display: grid; grid-template-columns: repeat(3, 1fr); gap: 8px; }
.menu-btn {
  display: block; text-align: center; padding: 12px 4px; border-radius: 10px;
  background: var(--flat-bg); color: var(--text); text-decoration: none;
  font-size: 0.78rem; font-weight: 600; border: 1px solid var(--border);
}
.menu-btn:active { background: var(--border); }
.search-box { display: flex; gap: 8px; }
#search-input {
  flex: 1; padding: 10px 12px; border: 1px solid var(--border); border-radius: 8px;
  font-size: 0.9rem; background: var(--card-bg); color: var(--text);
}
.search-clear {
  padding: 10px 14px; border-radius: 8px; border: 1px solid var(--border);
  background: var(--flat-bg); color: var(--text); font-size: 0.82rem; cursor: pointer;
}
.tag-chips { display: flex; flex-wrap: wrap; gap: 6px; margin-top: 8px; }
.tag-chip {
  padding: 7px 12px; border-radius: 999px; border: 1px solid var(--border);
  background: var(--flat-bg); color: var(--text); font-size: 0.78rem; cursor: pointer;
}
.fav-list-block { margin-top: 10px; border-top: 1px solid var(--border); padding-top: 8px; }
.fav-item { display: block; padding: 8px 4px; text-decoration: none; font-size: 0.85rem; }
.fav-empty { font-size: 0.8rem; color: #9ca3af; margin: 4px 0; }
.favorites-only .card:not(.is-fav):not(.no-filter) { display: none; }
.fresh-badge { display: inline-block; padding: 1px 7px; border-radius: 999px; font-size: 0.7rem; font-weight: 700; margin-right: 4px; }
.fresh-new { background: #fde2e2; color: #c62828; }
.fresh-24 { background: var(--up-bg); color: var(--up); }
.fresh-48 { background: #fff3e0; color: #e67e22; }
.fresh-old { background: var(--flat-bg); color: var(--flat); }
.fresh-unknown { background: var(--flat-bg); color: #9ca3af; }
.fresh-time { font-size: 0.72rem; color: #9ca3af; }
.section-nav { display: flex; justify-content: space-between; gap: 8px; margin-top: 14px; }
.section-nav a {
  flex: 1; text-align: center; padding: 10px 8px; border-radius: 8px; text-decoration: none;
  background: var(--flat-bg); color: var(--text); font-size: 0.82rem; font-weight: 600;
}
.section-nav a:only-child { margin-left: auto; }
.float-nav {
  position: fixed; right: 14px; bottom: 18px; z-index: 60;
  display: flex; flex-direction: column; gap: 8px; align-items: center;
}
.float-btn {
  width: 40px; height: 40px; border-radius: 50%; background: #374151; color: #fff;
  display: flex; align-items: center; justify-content: center; font-size: 0.95rem;
  text-decoration: none; box-shadow: 0 2px 6px rgba(0,0,0,0.25);
}
.back-to-top {
  width: 48px; height: 48px;
  border-radius: 50%; background: #2563eb; color: #fff; display: flex; align-items: center;
  justify-content: center; text-align: center; font-size: 0.68rem; line-height: 1.1;
  text-decoration: none; box-shadow: 0 2px 6px rgba(0,0,0,0.25);
}
.sticky-dashboard {
  position: sticky; top: 0; z-index: 55; background: #111827; color: #fff;
  padding: 6px 10px; display: flex; gap: 10px; align-items: center; overflow-x: auto;
  white-space: nowrap; font-size: 0.72rem; box-shadow: 0 2px 4px rgba(0,0,0,0.15);
}
.sticky-tile { display: inline-flex; gap: 4px; align-items: center; flex-shrink: 0; }
.sticky-tile b { color: #cbd5e1; font-weight: 600; }
.sticky-link { color: #93c5fd; text-decoration: none; margin-left: auto; flex-shrink: 0; }
.fi-block summary { cursor: pointer; list-style: none; padding: 2px 0; }
.fi-block summary::-webkit-details-marker { display: none; }
.fi-block summary h3 { display: inline-block; margin: 0; }
.fi-block summary::after { content: '\\25B8'; float: right; color: #666; }
.fi-block[open] > summary::after { content: '\\25BE'; }
.new-badge {
  display: inline-block; background: #c62828; color: #fff; font-size: 0.68rem; font-weight: 700;
  border-radius: 999px; padding: 1px 6px; margin-left: 4px; vertical-align: middle;
}
.stars-5 { color: #c62828; font-weight: 700; }
.stars-4 { color: #e67e22; font-weight: 700; }
.stars-3 { color: #1f6feb; font-weight: 700; }
.stars-2 { color: #757575; font-weight: 700; }
.options-card { background: #f9fafb; }
.options-grid { display: flex; flex-wrap: wrap; gap: 8px 16px; }
.option-toggle { display: flex; align-items: center; gap: 6px; font-size: 0.85rem; }
.option-toggle input { width: 18px; height: 18px; }
.option-btn {
  padding: 8px 14px; border-radius: 8px; border: 1px solid var(--border);
  background: var(--card-bg); color: var(--text); font-size: 0.82rem; cursor: pointer;
}
.compact-mode .legend { display: none; }
.compact-mode p[style*="font-size:0."] { display: none; }
.hide-sales .sales-section { display: none; }
.dashboard { background: #111827; color: #fff; }
.dashboard h2 { color: #fff; }
.dash-news-block { margin-bottom: 10px; }
.dash-news-block h3 { color: #cbd5e1; font-size: 0.85rem; margin: 0 0 6px 0; }
.dash-news a { color: #93c5fd; font-size: 0.85rem; line-height: 1.5; display: block; margin-bottom: 4px; }
.dashboard-grid { display: grid; grid-template-columns: repeat(3, 1fr); gap: 8px; }
.dash-tile { background: #1f2937; border-radius: 8px; padding: 8px; text-align: center; }
.dash-label { font-size: 0.72rem; color: #9ca3af; margin-bottom: 2px; }
.dash-value { font-size: 0.92rem; font-weight: 600; margin-bottom: 4px; }
@media (max-width: 420px) {
  .toc-list { columns: 1; }
  .dashboard-grid { grid-template-columns: repeat(2, 1fr); }
}
.badge { display: inline-block; padding: 2px 8px; border-radius: 999px; font-size: 0.78rem; font-weight: 600; }
.up { color: var(--up); background: var(--up-bg); }
.down { color: var(--down); background: var(--down-bg); }
.flat { color: var(--flat); background: var(--flat-bg); }
table { width: 100%; border-collapse: collapse; font-size: 0.85rem; table-layout: fixed; }
table th, table td {
  text-align: left; padding: 6px 4px; border-bottom: 1px solid var(--border);
  word-break: break-word; overflow-wrap: anywhere;
}
table th { color: #666; font-weight: 600; font-size: 0.78rem; }
.updated { font-size: 0.78rem; color: #9ca3af; margin-top: 4px; }
.row { display: flex; justify-content: space-between; align-items: center; padding: 6px 0; border-bottom: 1px solid var(--border); font-size: 0.9rem; }
.row:last-child { border-bottom: none; }
.legend { font-size: 0.8rem; color: #555; background: #fffbe6; border: 1px solid #f0e2a4; border-radius: 8px; padding: 10px 12px; }
.refresh-btn {
  display: block; text-align: center; margin: 0 0 14px 0; padding: 14px 16px;
  background: #2563eb; color: #fff; border-radius: 10px; font-weight: 600;
  font-size: 0.95rem; text-decoration: none;
}
.refresh-btn:active { background: #1d4ed8; }
.refresh-note { font-size: 0.75rem; color: #6b7280; text-align: center; margin: -8px 0 14px 0; }
/* v2.9（②Real-Time Update Engine）: 「最新レポートを生成する」導線ボタン */
.regenerate-btn {
  display: block; text-align: center; margin: 0 0 14px 0; padding: 12px 16px;
  background: #fff; color: #2563eb; border: 2px solid #2563eb; border-radius: 10px;
  font-weight: 600; font-size: 0.9rem; text-decoration: none;
}
.regenerate-btn:active { background: #eef4ff; }
:root[data-theme="dark"] .regenerate-btn { background: #12161f; }
/* v3.3: 設定未完了メッセージ・生成状態の説明・スマホ手順・将来の即時生成枠 */
.regenerate-pending {
  margin: 0 0 14px 0; padding: 12px 16px; background: #f3f4f6; color: #4b5563;
  border: 2px dashed #9ca3af; border-radius: 10px; font-size: 0.85rem;
}
.generation-status { margin: 0 0 14px 0; }
.mobile-steps {
  margin: 0 0 14px 0; background: #f8fafc; border: 1px solid #e2e8f0;
  border-radius: 10px; padding: 4px 12px;
}
.mobile-steps summary { cursor: pointer; font-weight: 600; padding: 8px 0; font-size: 0.9rem; }
.mobile-steps ol { padding-left: 20px; margin: 4px 0 10px 0; font-size: 0.85rem; }
/* v3.4: Cloudflare Worker中継によるワンタップ生成ボタン（有効時） */
.one-tap-btn {
  display: block; width: 100%; text-align: center; margin: 0 0 4px 0; padding: 14px 16px;
  background: #059669; color: #fff; border: none; border-radius: 10px;
  font-weight: 700; font-size: 0.95rem; cursor: pointer;
}
.one-tap-btn:active { background: #047857; }
.one-tap-btn:disabled { background: #9ca3af; color: #e5e7eb; cursor: not-allowed; }
.one-tap-msg { font-size: 0.8rem; color: #374151; text-align: center; margin: 2px 0 14px 0; }
.one-tap-msg.ok { color: #059669; font-weight: 600; }
.one-tap-msg.err { color: #c62828; font-weight: 600; }
:root[data-theme="dark"] .regenerate-pending { background: #1a1d24; border-color: #4b5563; color: #9ca3af; }
:root[data-theme="dark"] .mobile-steps { background: #171a21; border-color: #2d3340; }
:root[data-theme="dark"] .one-tap-msg { color: #cbd5e1; }
.digest { background: #eef4ff; border: 1px solid #c9dcff; }
ul.plain { padding-left: 18px; margin: 6px 0; }
ul.plain li { margin-bottom: 4px; font-size: 0.9rem; }
.qa dt { font-weight: 600; margin-top: 8px; }
.qa dd { margin: 2px 0 0 0; font-size: 0.88rem; color: #333; }
.chain { font-size: 0.9rem; }
.chain .arrow { text-align: center; color: #888; margin: 2px 0; }
a { color: #1f6feb; }
/* v2.7: 3分で読めるUI（要約＋「詳しく」アコーディオン＋重要度バッジ） */
.imp { display: inline-block; font-size: 0.68rem; font-weight: 600; color: #7c3aed;
  background: #f3e8ff; border-radius: 8px; padding: 1px 7px; margin-left: 6px; vertical-align: middle; }
details.more { margin: 4px 0 10px 0; }
details.more > summary.detail-btn { cursor: pointer; display: inline-block; list-style: none;
  font-size: 0.78rem; font-weight: 600; color: #1f6feb; background: #eef4ff;
  border: 1px solid #c9dcff; border-radius: 12px; padding: 3px 12px; user-select: none; }
details.more > summary.detail-btn::-webkit-details-marker { display: none; }
details.more > summary.detail-btn::before { content: "▸ "; }
details.more[open] > summary.detail-btn::before { content: "▾ "; }
.more-body { font-size: 0.82rem; color: #444; margin-top: 6px; padding: 8px 10px;
  background: #f8f9fb; border-left: 3px solid #c9dcff; border-radius: 4px; }
.fi-conclusion { background: #fffbe8; border: 1px solid #f0e0a0; border-radius: 8px;
  padding: 10px 12px; margin: 8px 0; font-size: 0.9rem; }
.fi-conclusion .imp { margin-left: 0; }
.event-row { border-bottom: 1px dashed var(--border); padding: 6px 0; }
.event-countdown { display: inline-block; font-size: 0.72rem; font-weight: 700; color: #b45309;
  background: #fef3c7; border-radius: 8px; padding: 1px 8px; margin-right: 6px; }
.trust { display: inline-block; font-size: 0.7rem; color: #3730a3; background: #e0e7ff;
  border-radius: 8px; padding: 1px 7px; margin-left: 4px; }
.translated { display: inline-block; font-size: 0.68rem; font-weight: 600; color: #0369a1;
  background: #e0f2fe; border-radius: 8px; padding: 1px 6px; margin-left: 4px; }
:root[data-theme="dark"] .translated { background: #0b2b3d; color: #7dd3fc; }
.why-today { font-size: 0.8rem; color: #0f5132; background: #e7f6ec; border: 1px solid #b7dfc4;
  border-radius: 8px; padding: 6px 10px; margin: 0 0 8px 0; }
.why-today strong { color: #0a3622; }
.todays-decision { border-left: 4px solid #7c3aed; }
.narrative-card { border-left: 4px solid #0d9488; }
.narrative-headline { font-size: 0.82rem; font-weight: 700; margin: 8px 0 2px 0; color: #0f766e; }
.narrative-conclusion { font-size: 0.98rem; font-weight: 600; line-height: 1.55; margin: 0 0 6px 0;
  background: #ecfdf5; border: 1px solid #a7f3d0; border-radius: 8px; padding: 8px 10px; }
.nk-chain { margin: 2px 0 8px 0; }
.nk-node { font-size: 0.85rem; background: #f8fafc; border: 1px solid #e2e8f0; border-radius: 6px;
  padding: 5px 8px; display: inline-block; }
.nk-arrow { text-align: center; color: #14b8a6; font-weight: 700; margin: 1px 0; }
.strategist-summary { font-size: 0.9rem; line-height: 1.6; margin: 0 0 8px 0;
  background: #f0fdfa; border: 1px solid #99f6e4; border-radius: 8px; padding: 8px 10px; }
.sales-30sec { font-size: 0.88rem; line-height: 1.55; margin: 0 0 8px 0;
  background: #fffbeb; border: 1px solid #fde68a; border-radius: 8px; padding: 8px 10px; }
:root[data-theme="dark"] .strategist-summary { background: #0d2b23; border-color: #1c5c48; color: #d1fae5; }
:root[data-theme="dark"] .sales-30sec { background: #2a2410; border-color: #5a4d18; color: #fde68a; }
:root[data-theme="dark"] .narrative-card { border-left-color: #2dd4bf; }
:root[data-theme="dark"] .narrative-headline { color: #5eead4; }
:root[data-theme="dark"] .narrative-conclusion { background: #0d2b23; border-color: #1c5c48; color: #d1fae5; }
:root[data-theme="dark"] .nk-node { background: #171a21; border-color: #2d3340; }
.td-sub { font-size: 0.78rem; color: #666; margin: 2px 0 8px 0; }
.td-head { font-weight: 600; margin: 10px 0 2px 0; }
.dq-warn { font-size: 0.82rem; color: #92400e; background: #fef3c7; border: 1px solid #fcd34d;
  border-radius: 8px; padding: 8px 10px; margin: 0 0 8px 0; }
:root[data-theme="dark"] .todays-decision { border-left-color: #a78bfa; }
:root[data-theme="dark"] .td-sub { color: #9aa4b2; }
:root[data-theme="dark"] .dq-warn { background: #3a2c0f; border-color: #6b5218; color: #fbbf24; }
.learn-hit { color: #1a7f37; font-weight: 600; }
.learn-miss { color: #c62828; font-weight: 600; }
.learn-wait { color: #6b7280; font-weight: 600; }
:root[data-theme="dark"] .trust { background: #2a2f52; color: #c7cdf5; }
:root[data-theme="dark"] .why-today { background: #10281a; border-color: #2f5a3f; color: #a7e0bd; }
:root[data-theme="dark"] .more-body { background: #23262e; color: #cbd2dc; }
:root[data-theme="dark"] details.more > summary.detail-btn { background: #1d2839; }
:root[data-theme="dark"] .fi-conclusion { background: #2b2716; border-color: #5a512a; }
:root[data-theme="dark"] .imp { background: #3b2a55; color: #d8c6f5; }
:root[data-theme="dark"] .event-countdown { background: #453317; color: #f3c877; }
@media (max-width: 420px) {
  .header h1 { font-size: 1.1rem; }
  .card { padding: 12px; }
  .back-to-top { width: 44px; height: 44px; right: 10px; bottom: 14px; }
  .section-nav a { padding: 12px 8px; font-size: 0.8rem; }
  .copy-btn { min-width: 36px; min-height: 36px; }
  .sticky-dashboard { font-size: 0.68rem; padding: 5px 8px; }
  .options-grid { flex-direction: column; gap: 8px; }
}
"""

SCRIPT = """
function toggleCard(btn) {
  var card = btn.closest('.card');
  if (!card) { return; }
  card.classList.toggle('card-collapsed');
  btn.textContent = card.classList.contains('card-collapsed') ? '\\u25B8' : '\\u25BE';
}

function getFavs() {
  try { return JSON.parse(localStorage.getItem('mkt_favs') || '[]'); } catch (e) { return []; }
}
function saveFavs(favs) { localStorage.setItem('mkt_favs', JSON.stringify(favs)); }

function renderFavList() {
  var box = document.getElementById('fav-list');
  if (!box) { return; }
  var favs = getFavs();
  if (!favs.length) {
    box.innerHTML = '<p class="fav-empty">お気に入りはありません</p>';
    return;
  }
  var html = '';
  for (var i = 0; i < favs.length; i++) {
    var card = document.getElementById(favs[i]);
    var title = card ? card.querySelector('h2').textContent : favs[i];
    html += '<a class="fav-item" href="#' + favs[i] + '">\\u2605 ' + title + '</a>';
  }
  box.innerHTML = html;
}

function applyFavStates() {
  var favs = getFavs();
  var btns = document.querySelectorAll('.fav-btn');
  for (var i = 0; i < btns.length; i++) {
    var id = btns[i].getAttribute('data-card');
    var on = favs.indexOf(id) >= 0;
    btns[i].textContent = on ? '\\u2605' : '\\u2606';
    btns[i].classList.toggle('fav-on', on);
    var card = document.getElementById(id);
    if (card) { card.classList.toggle('is-fav', on); }
  }
  renderFavList();
}

function toggleFav(btn) {
  var id = btn.getAttribute('data-card');
  if (!id) { return; }
  var favs = getFavs();
  var idx = favs.indexOf(id);
  if (idx >= 0) {
    favs.splice(idx, 1);  // 登録済みなら確実に解除する
  } else {
    favs.push(id);
  }
  saveFavs(favs);
  applyFavStates();
}

function filterCards() {
  var input = document.getElementById('search-input');
  if (!input) { return; }
  var q = input.value.trim().toLowerCase();
  var cards = document.querySelectorAll('.card:not(.no-filter)');
  var hits = 0;
  for (var i = 0; i < cards.length; i++) {
    var text = (cards[i].innerText || cards[i].textContent || '').toLowerCase();
    var show = !q || text.indexOf(q) >= 0;
    cards[i].style.display = show ? '' : 'none';
    if (show) { hits++; }
  }
  var empty = document.getElementById('search-empty');
  if (empty) { empty.style.display = (q && !hits) ? '' : 'none'; }
}
function applyTag(btn) {
  var input = document.getElementById('search-input');
  if (!input) { return; }
  input.value = btn.textContent.trim();
  filterCards();
}
function clearSearch() {
  var input = document.getElementById('search-input');
  if (!input) { return; }
  input.value = '';
  filterCards();
}

function copySection(btn) {
  var card = btn.closest('.card');
  if (!card) { return; }
  var clone = card.cloneNode(true);
  var toRemove = clone.querySelectorAll('.copy-btn, .section-nav, .fav-btn, .collapse-btn');
  for (var i = 0; i < toRemove.length; i++) { toRemove[i].remove(); }
  var text = (clone.innerText || clone.textContent || '').trim();
  if (navigator.clipboard && navigator.clipboard.writeText) {
    navigator.clipboard.writeText(text);
  }
  var original = btn.textContent;
  btn.textContent = '\\u2705';
  setTimeout(function () { btn.textContent = original; }, 1200);
}

(function () {
  var root = document.documentElement;
  var compactBox = document.getElementById('opt-compact');
  var salesBox = document.getElementById('opt-hide-sales');
  var darkBox = document.getElementById('opt-dark');
  var favsOnlyBox = document.getElementById('opt-favs-only');
  var fiToggleBtn = document.getElementById('opt-fi-toggle');
  applyFavStates();  // ページ再読み込み後もお気に入り状態（☆/★・一覧）を復元する
  if (!compactBox || !salesBox || !darkBox) { return; }

  function apply() {
    document.body.classList.toggle('compact-mode', compactBox.checked);
    document.body.classList.toggle('hide-sales', salesBox.checked);
    document.body.classList.toggle('favorites-only', !!(favsOnlyBox && favsOnlyBox.checked));
    root.setAttribute('data-theme', darkBox.checked ? 'dark' : 'light');
  }

  compactBox.checked = localStorage.getItem('mkt_compact') === '1';
  salesBox.checked = localStorage.getItem('mkt_hideSales') === '1';
  darkBox.checked = localStorage.getItem('mkt_theme') === 'dark';
  if (favsOnlyBox) { favsOnlyBox.checked = localStorage.getItem('mkt_favsOnly') === '1'; }
  apply();

  compactBox.addEventListener('change', function () {
    localStorage.setItem('mkt_compact', compactBox.checked ? '1' : '0');
    apply();
  });
  salesBox.addEventListener('change', function () {
    localStorage.setItem('mkt_hideSales', salesBox.checked ? '1' : '0');
    apply();
  });
  darkBox.addEventListener('change', function () {
    localStorage.setItem('mkt_theme', darkBox.checked ? 'dark' : 'light');
    apply();
  });
  if (favsOnlyBox) {
    favsOnlyBox.addEventListener('change', function () {
      localStorage.setItem('mkt_favsOnly', favsOnlyBox.checked ? '1' : '0');
      apply();
    });
  }
  if (fiToggleBtn) {
    fiToggleBtn.addEventListener('click', function () {
      var blocks = document.querySelectorAll('.fi-block');
      var anyClosed = false;
      for (var i = 0; i < blocks.length; i++) {
        if (!blocks[i].open) { anyClosed = true; break; }
      }
      for (var j = 0; j < blocks.length; j++) { blocks[j].open = anyClosed; }
    });
  }

  // v3.4: ワンタップ生成（Cloudflare Worker等の中継バックエンドへPOST）。
  // エンドポイントURLはボタンのdata-endpointから読む。GitHubの認証情報は
  // このJS・HTMLに一切含まれない（中継バックエンド側の暗号化変数にのみ保管される）。
  var oneTap = document.getElementById('one-tap-btn');
  if (oneTap) {
    oneTap.addEventListener('click', function () {
      var endpoint = oneTap.getAttribute('data-endpoint');
      var msg = document.getElementById('one-tap-msg');
      if (!endpoint) { return; }
      function setMsg(text, cls) {
        if (!msg) { return; }
        msg.textContent = text;
        msg.className = 'one-tap-msg' + (cls ? (' ' + cls) : '');
      }
      oneTap.disabled = true;
      setMsg('生成をリクエストしています…', '');
      fetch(endpoint, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: '{}'
      }).then(function (r) {
        return r.json().catch(function () { return { ok: r.ok }; });
      }).then(function (data) {
        if (data && data.ok) {
          setMsg('生成を開始しました。1〜3分後にページを再読み込みしてください。', 'ok');
        } else {
          var err = (data && data.error) ? ('：' + data.error) : '';
          setMsg('生成リクエストに失敗しました' + err + '。時間をおいて再度お試しください。', 'err');
        }
      }).catch(function () {
        setMsg('生成リクエストに失敗しました（通信エラー）。時間をおいて再度お試しください。', 'err');
      });
      // 連打防止で60秒間ボタンを無効化（成否にかかわらず）。
      setTimeout(function () { oneTap.disabled = false; }, 60000);
    });
  }
})();
"""


def _esc(text: Optional[str]) -> str:
    return html.escape(str(text)) if text is not None else ""


def _trend_class(change_pct: Optional[float]) -> str:
    if change_pct is None:
        return "flat"
    if change_pct > 0:
        return "up"
    if change_pct < 0:
        return "down"
    return "flat"


def _badge(text: str, css_class: str) -> str:
    return f'<span class="badge {css_class}">{_esc(text)}</span>'


def _copy_button_html() -> str:
    return '<button type="button" class="copy-btn" onclick="copySection(this)" aria-label="このセクションをコピー">📋</button>'


# 各セクションカードの「ひとこと説明」（anchor→説明文の人手による対応表・v2.5）
SECTION_DESCRIPTIONS = {
    "dashboard-top": "今日の市場全体を30秒で把握するダッシュボードです。",
    "executive-summary": "今日最重要のニュース最大3件とその影響を要約します。",
    "weekly-events": "今後1週間で相場を動かす可能性のあるイベントをカウントダウンつきで表示します。",
    "scenarios-v2": "期待値（確率）の高い最大3つのシナリオに絞って提示します。",
    "learning-history": "過去のAI判断を30/90/180日後の市場と自動で答え合わせした履歴です。",
    "theme-learning": "テーマ予想の勝率を学習し、Confidenceの実績補正に使います。",
    "strategist-views": "重要ニュースをストラテジスト視点で深掘りします。",
    "future-intelligence": "世界→テーマ→業界→銘柄→長期戦略を一気通貫で分析します。",
    "news-ranking": "本日の重要ニュースを重要度×鮮度で並べたランキングです。",
    "watchlist": "監視銘柄の本日の評価を一覧で確認できます。",
    "news-freshness": "本日のニュースがどれだけ新しいかを確認できます。",
    "data-quality": "今日のレポートが最新データに基づくかを確認できます。",
    "sales-prep": "営業向けの準備メモです（副次用途）。",
}


def _card(
    title: str,
    body_html: str,
    extra_class: str = "",
    anchor: Optional[str] = None,
    nav_html: str = "",
    description: str = "",
) -> str:
    id_attr = f' id="{_esc(anchor)}"' if anchor else ""
    label, stars_txt = _split_title_stars(title)
    # v2.7（⑥）: ★から100点満点の重要度を機械的に換算して併記（★×20点）。
    # 何を先に読むべきかを一目で分かるようにする表示のみの機能。
    imp_html = ""
    if stars_txt:
        importance = min(100, stars_txt.count("★") * 20)
        imp_html = f'<span class="imp">重要度{importance}</span>'
    title_html = _esc(label) + (f" {_stars_span(stars_txt)}{imp_html}" if stars_txt else "")
    # お気に入り（☆⇄★）はアンカーを持つ通常セクションのみ対象（メニュー・目次等のno-filterカードは除く）
    fav_btn = ""
    if anchor and "no-filter" not in extra_class:
        fav_btn = (
            f'<button type="button" class="fav-btn" data-card="{_esc(anchor)}" '
            'onclick="toggleFav(this)" aria-label="お気に入りに追加/解除">☆</button>'
        )
    # v3.1（改善6）: 初期状態で折りたたむカード（card-collapsed）はボタン表示も▸にする
    collapse_glyph = "▸" if "card-collapsed" in extra_class else "▾"
    collapse_btn = f'<button type="button" class="collapse-btn" onclick="toggleCard(this)" aria-label="開く/閉じる">{collapse_glyph}</button>'
    actions_html = f'<div class="card-actions">{fav_btn}{collapse_btn}{_copy_button_html()}</div>'
    head_html = f'<div class="card-head"><h2>{title_html}</h2>{actions_html}</div>'
    desc = description or SECTION_DESCRIPTIONS.get(anchor or "", "")
    desc_html = f'<p class="card-desc">{_esc(desc)}</p>' if desc else ""
    return (
        f'<div class="card {extra_class}"{id_attr}>{head_html}{desc_html}'
        f'<div class="card-body">{body_html}{nav_html}</div></div>'
    )


def _detail_block(detail_html: str, label: str = "詳しく") -> str:
    """「3分で読めるUI」（v2.7）の詳細展開部品。

    通常表示は要約のみとし、押した人だけが背景・理由・因果関係などを読める
    アコーディオン（HTML標準のdetails/summary。外部JS不要）を生成する。
    """
    if not detail_html:
        return ""
    return (
        f"<details class='more'><summary class='detail-btn'>{_esc(label)}</summary>"
        f"<div class='more-body'>{detail_html}</div></details>"
    )


def _quote_row(quote: Quote) -> str:
    cls = _trend_class(quote.change_pct)
    change_txt = fmt_change_compact(quote.change_pct)
    return (
        f'<tr><td>{_esc(quote.name)}</td>'
        f'<td>{_esc(fmt_price(quote.price))}</td>'
        f'<td><span class="badge {cls}">{_esc(change_txt)}</span></td></tr>'
    )


def _quote_table_html(quotes: List[Quote]) -> str:
    if not quotes:
        return f"<p>データがありません（{_esc(NOT_AVAILABLE)}）。</p>"
    rows = "".join(_quote_row(q) for q in quotes)
    return f'<table><tr><th>名称</th><th>値</th><th>前日比</th></tr>{rows}</table>'


def _digest_card(market: dict, analysis: AnalysisBundle) -> str:
    from .sections import render_mobile_digest

    text = render_mobile_digest(market, analysis)
    # render_mobile_digest returns Markdown; ここでは見出しを除いた本文だけをHTML化する
    body_lines = [line for line in text.splitlines() if line.strip() and not line.startswith("##")]
    body_html = "".join(f"<p>{_esc(line)}</p>" for line in body_lines)
    return _card("📱 今日の5分要約", body_html, extra_class="digest")


def _scenario_card(scenario, nav_html: str = "") -> str:
    rows = "".join(
        f'<div class="row"><span>{label}</span><span>{pct}%（注目指標: {_esc(indicator or NOT_AVAILABLE)}）</span></div>'
        for label, pct, indicator in [
            ("強気", scenario.bull_pct, scenario.bull_indicator),
            ("普通（中立）", scenario.neutral_pct, scenario.neutral_indicator),
            ("弱気", scenario.bear_pct, scenario.bear_indicator),
        ]
    )
    reasons = (
        f"<p><strong>総括:</strong> {_esc(scenario.reasoning)}</p>"
        f"<p><strong>強気の理由:</strong> {_esc(scenario.bull_reason or NOT_AVAILABLE)}</p>"
        f"<p><strong>中立の理由:</strong> {_esc(scenario.neutral_reason or NOT_AVAILABLE)}</p>"
        f"<p><strong>弱気の理由:</strong> {_esc(scenario.bear_reason or NOT_AVAILABLE)}</p>"
    )
    return _card("今日の相場シナリオ", rows + reasons, anchor="scenario", nav_html=nav_html)


def _age_hours(published: str, now: Optional[datetime]) -> Optional[float]:
    """記事の経過時間（時間）。日時不明・now未指定はNone。"""
    if now is None:
        return None
    dt = parse_published_datetime(published)
    if dt is None:
        return None
    return (now - dt).total_seconds() / 3600


def _source_trust_inline(source_name: str) -> str:
    """出典名から Source Trust バッジ（★とティア）を小さく表示する（v2.8・⑥）。"""
    t = trust_for_source(source_name)
    return f'<span class="trust">Source Trust {_esc(t.stars)}（{_esc(t.tier)}）</span>'


def _translated_badge(headline) -> str:
    """翻訳済みの見出しに「翻訳済み」バッジを付ける（v3.0・①）。原文は英語のまま。"""
    return '<span class="translated">翻訳済み</span>' if getattr(headline, "title_ja", "") else ""


def _news_ranking_item_html(item: NewsRankingItem, now: Optional[datetime] = None) -> str:
    """1件分: 要約（順位・★・見出し・鮮度・信頼度）＋「詳しく」（理由・影響・銘柄・トーク・原文）。"""
    h = item.headline
    marker = " 🏆" if item.is_top_pick else ""
    trust = trust_for_source(h.source)
    # v2.8（④）: 日本語訳があれば日本語を見出しに、原文は「詳しく」内に格納
    orig_html = f"<p style='margin:0 0 4px 0;'>原文: {_esc(h.title)}</p>" if h.title_ja else ""
    # v2.9（④ Duplicate/Cross Source Intelligence）: 複数ソースが同一ニュースを
    # 配信していた場合、報道社数とCombined Trustを表示する。
    dup_html = ""
    if h.source_count >= 2:
        combined = combined_trust_for_sources(h.source, h.duplicate_sources)
        dup_html = (
            f"<p style='margin:0 0 4px 0;'>{combined.source_count}社が同一ニュースを報道: "
            f"{_esc('、'.join(combined.all_sources))} ／ Combined Trust {_esc(combined.stars)}</p>"
        )
    detail = (
        f"<p style='margin:0 0 4px 0;'>Source Trust: {_esc(trust.stars)}（{_esc(trust.tier)}）— {_esc(trust.reason)}</p>"
        + dup_html
        + orig_html
        + f"<p style='margin:0 0 4px 0;'>理由: {_esc(item.reason or NOT_AVAILABLE)}</p>"
        f"<p style='margin:0 0 4px 0;'>影響市場: {_esc(item.affected_market or NOT_AVAILABLE)} ／ "
        f"影響業種: {_esc(item.affected_sector or NOT_AVAILABLE)}</p>"
        + (
            f"<p style='margin:0 0 4px 0;'>恩恵銘柄: {_esc('、'.join(item.beneficiary_tickers))} ／ "
            f"悪影響銘柄: {_esc('、'.join(item.negative_tickers) or '該当なし')}</p>"
            if item.beneficiary_tickers or item.negative_tickers
            else ""
        )
        + (f"<p style='margin:0;'>営業トーク: 「{_esc(item.sales_talk)}」</p>" if item.sales_talk else "")
    )
    return (
        f'<div class="row"><span>{item.rank}位{marker} {_esc(item.stars)} '
        f'<a href="{_esc(h.link)}">{_esc(h.display_title())}</a>{_translated_badge(h)}</span></div>'
        f'<p style="margin:2px 0 0 0;">{_news_freshness_badge(h.published, now)} {_source_trust_inline(h.source)}</p>'
        + _detail_block(detail)
    )


def _is_primary_news(item: NewsRankingItem, now: Optional[datetime]) -> bool:
    """初期表示すべき重要記事か（v2.8・⑧⑨）。

    ★★★★☆以上、または24時間以内かつ重要度が高い（★★★☆☆以上）記事を
    初期表示。1位は必ず初期表示する。それ以外（★★★☆☆以下・48時間超）は折りたたむ。
    """
    if item.rank == 1:
        return True
    star_count = item.stars.count("★")
    if star_count >= 4:
        return True
    age = _age_hours(item.headline.published, now)
    if age is not None and age <= 24 and star_count >= 3:
        return True
    return False


def _news_ranking_html(items: List[NewsRankingItem], now: Optional[datetime] = None) -> str:
    if not items:
        return f"<p>本日ランキング可能なニュースがありませんでした（{_esc(NOT_AVAILABLE)}）。</p>"
    # v2.8（⑧⑨）: 重要度×鮮度で初期表示を選別。重要な記事だけを開いて表示し、
    # 低重要度・古い記事は details に折りたたむ（削除はしない）。
    primary = [i for i in items if _is_primary_news(i, now)]
    secondary = [i for i in items if not _is_primary_news(i, now)]
    parts = [_news_ranking_item_html(item, now) for item in primary]
    if secondary:
        rest_html = "".join(_news_ranking_item_html(item, now) for item in secondary)
        parts.append(_detail_block(rest_html, label=f"低重要度・古い記事を表示（{len(secondary)}件）"))
    return "".join(parts)


def _key_levels_html(entries: List[KeyLevelEntry]) -> str:
    if not entries:
        return f"<p>本日表示できる指標がありませんでした（{_esc(NOT_AVAILABLE)}）。</p>"
    rows = []
    for entry in entries:
        price_txt = fmt_price(entry.quote.price) if entry.quote else NOT_AVAILABLE
        cls = _trend_class(entry.quote.change_pct) if entry.quote else "flat"
        line_txt = f"{entry.key_line:g}" if entry.key_line is not None else NOT_AVAILABLE
        rows.append(
            f'<div class="row"><span>{_esc(entry.label)} <span class="badge {cls}">{_esc(price_txt)}</span></span>'
            f"<span>節目: {_esc(line_txt)}</span></div>"
            f'<p style="font-size:0.82rem;color:#555;margin:2px 0 8px 0;">{_esc(entry.note)}</p>'
        )
    return "".join(rows)


def _causal_chain_html(causal_chain_text: str, causal_chains: List[str]) -> str:
    def _to_html(chain_text: str) -> str:
        nodes = [n.strip() for n in chain_text.replace("\n\n", "\n").split("\n") if n.strip() and n.strip() != "↓"]
        return '<div class="arrow">↓</div>'.join(f"<div>{_esc(n)}</div>" for n in nodes)

    main_chain = f'<div class="chain">{_to_html(causal_chain_text)}</div>'
    if causal_chains:
        extra = "".join(
            f'<h3>チェーン{i}</h3><div class="chain">{_to_html(c)}</div>' for i, c in enumerate(causal_chains, start=1)
        )
    else:
        extra = f"<p>本日抽出できる個別の因果チェーンはありませんでした（{_esc(NOT_AVAILABLE)}）。</p>"
    return main_chain + extra


def _theme_forecasts_html(theme_forecasts: List[ThemeForecast]) -> str:
    if not theme_forecasts:
        return f"<p>本日抽出できたテーマはありませんでした（{_esc(NOT_AVAILABLE)}）。</p>"
    parts = []
    for tf in theme_forecasts:
        parts.append(
            f"<h3>第{tf.rank}位: {_esc(tf.label)} {_esc(tf.stars)}</h3>"
            f"<ul class='plain'>"
            f"<li>今なぜ強いか: {_esc(tf.why_now)}</li>"
            f"<li>1週間: {_esc(tf.outlook_1w)}</li>"
            f"<li>1か月: {_esc(tf.outlook_1m)}</li>"
            f"<li>3か月: {_esc(tf.outlook_3m)}</li>"
            f"</ul>"
        )
    return "".join(parts)


def _sector_ranking_html(sector_ranking: List[SectorRankingEntry]) -> str:
    if not sector_ranking:
        return f"<p>本日ランキング可能な業界がありませんでした（{_esc(NOT_AVAILABLE)}）。</p>"
    parts = []
    for entry in sector_ranking:
        parts.append(
            f"<h3>第{entry.rank}位: {_esc(entry.label)} {_esc(entry.stars)}</h3>"
            f"<p>追い風{len(entry.tailwind)}件 ／ 逆風{len(entry.headwind)}件</p>"
            f"<p style='font-size:0.85rem;color:#555;'>{_esc(entry.sales_talk)}</p>"
        )
    return "".join(parts)


def _stock_ranking_html(stock_ranking: dict) -> str:
    def _render(entries: List[StockRankingEntry]) -> str:
        if not entries:
            return f"<p>本日ランキング可能な銘柄がありませんでした（{_esc(NOT_AVAILABLE)}）。</p>"
        rows = []
        for e in entries:
            cls = _trend_class(e.quote.change_pct)
            rows.append(
                f'<div class="row"><span>第{e.rank}位 {_esc(e.quote.name)}（{_esc(e.quote.symbol)}）</span>'
                f'<span class="badge {cls}">{_esc(fmt_change_compact(e.quote.change_pct))}</span></div>'
                f'<p style="font-size:0.82rem;color:#555;margin:2px 0 8px 0;">短期: {_esc(e.short_term)}</p>'
            )
        return "".join(rows)

    return f"<h3>日本株TOP10</h3>{_render(stock_ranking.get('jp', []))}<h3>米国株TOP10</h3>{_render(stock_ranking.get('us', []))}"


def _watchlist_quicklist_html(quicklist: dict) -> str:
    # v2.7（⑩）: 銘柄ごとに一行要約（銘柄名・前日比・★）のみ表示し、
    # 評価理由は「詳しく」で展開する（判定ロジックは不変・表示のみ変更）。
    def _render(entries: List[WatchlistQuickEntry]) -> str:
        if not entries:
            return f"<p>データがありません（{_esc(NOT_AVAILABLE)}）。</p>"
        rows = []
        for e in entries:
            cls = _trend_class(e.quote.change_pct)
            rows.append(
                f'<div class="row"><span>{_esc(e.quote.name)}（{_esc(e.quote.symbol)}）'
                f' <span class="badge {cls}">{_esc(fmt_change_compact(e.quote.change_pct))}</span></span>'
                f'<span class="badge {cls}">{_esc(e.stars)}</span></div>'
                + _detail_block(f"<p style='margin:0;'>{_esc(e.reason)}</p>")
            )
        return "".join(rows)

    return f"<h3>日本株</h3>{_render(quicklist.get('jp', []))}<h3>米国株</h3>{_render(quicklist.get('us', []))}"


def _long_term_picks_html(picks) -> str:
    if not picks:
        return f"<p>本日選定可能な長期投資候補がありませんでした（{_esc(NOT_AVAILABLE)}）。</p>"
    parts = ["<p style='font-size:0.8rem;color:#666;'>AIが本日時点の公開情報から機械的に算出した候補です。投資助言ではありません。</p>"]
    for pick in picks:
        parts.append(
            f"<h3>第{pick.rank}位: {_esc(pick.quote.name)}（{_esc(pick.quote.symbol)}）</h3>"
            f"<p style='font-size:0.85rem;'>{_esc(pick.reasoning)}</p>"
        )
    return "".join(parts)


def _sales_prep_html(sales_prep) -> str:
    def _list(items: List[str]) -> str:
        if not items:
            return f"<p>{_esc(NOT_AVAILABLE)}</p>"
        return "<ul class='plain'>" + "".join(f"<li>{_esc(i)}</li>" for i in items) + "</ul>"

    glossary = "".join(f"<li><strong>{_esc(g.term)}:</strong> {_esc(g.explanation)}</li>" for g in sales_prep.beginner_glossary)
    qa = "".join(f"<dt>Q. {_esc(item.question)}</dt><dd>A. {_esc(item.answer)}</dd>" for item in sales_prep.qa)

    return (
        f"<h3>社長向け一言</h3>{_list(sales_prep.ceo_lines)}"
        f"<h3>富裕層向け話題</h3>{_list(sales_prep.wealthy_topics)}"
        f"<h3>初心者向け用語解説</h3><ul class='plain'>{glossary}</ul>"
        f"<h3>今日の雑談</h3>{_list(sales_prep.casual_topics)}"
        f"<h3>想定質問</h3><dl class='qa'>{qa}</dl>"
    )


def _sales_talk_html(bullets) -> str:
    def _list(items: List[str]) -> str:
        if not items:
            return f"<p>{_esc(NOT_AVAILABLE)}</p>"
        return "<ul class='plain'>" + "".join(f"<li>{_esc(i)}</li>" for i in items) + "</ul>"

    return (
        f"<h3>法人社長向け</h3>{_list(bullets.corporate)}"
        f"<h3>個人投資家向け</h3>{_list(bullets.retail)}"
        f"<h3>初心者向け</h3>{_list(bullets.beginner)}"
        f"<h3>富裕層向け</h3>{_list(bullets.wealthy)}"
    )


def _events_html(events) -> str:
    def _list(items: List[str]) -> str:
        if not items:
            return "<p>該当なし</p>"
        return "<ul class='plain'>" + "".join(f"<li>{_esc(i)}</li>" for i in items) + "</ul>"

    return f"<h3>今日</h3>{_list(events.today)}<h3>今週</h3>{_list(events.this_week)}<h3>今月</h3>{_list(events.this_month)}"


def _sales_comments_html(comments: SalesComments) -> str:
    audiences = [
        ("法人社長向け", comments.corporate),
        ("富裕層向け", comments.wealthy),
        ("個人投資家向け", comments.retail),
        ("NISA初心者向け", comments.nisa_beginner),
        ("為替に関心がある顧客向け", comments.fx_interested),
        ("米国株に関心がある顧客向け", comments.us_stock_interested),
        ("日本株に関心がある顧客向け", comments.jp_stock_interested),
    ]
    parts = []
    for label, text in audiences:
        parts.append(f"<h3>{_esc(label)}</h3><p style='font-size:0.88rem;'>{_esc(text or NOT_AVAILABLE)}</p>")
    return "".join(parts)


def _expanded_qa_html(qa_items: List[QAItem]) -> str:
    if not qa_items:
        return f"<p>本日生成できる想定質問がありませんでした（{_esc(NOT_AVAILABLE)}）。</p>"
    dl = "".join(f"<dt>Q. {_esc(item.question)}</dt><dd>A. {_esc(item.answer)}</dd>" for item in qa_items)
    return f"<dl class='qa'>{dl}</dl>"


def _top_picks_html(top_picks: dict) -> str:
    def _render(entries: List[TopPickEntry]) -> str:
        if not entries:
            return f"<p>本日選定可能な注目銘柄がありませんでした（{_esc(NOT_AVAILABLE)}）。</p>"
        rows = []
        for e in entries:
            cls = _trend_class(e.quote.change_pct)
            rows.append(
                f'<div class="row"><span>第{e.rank}位 {_esc(e.quote.name)}（{_esc(e.quote.symbol)}）{_esc(e.stars)}</span>'
                f'<span class="badge {cls}">{_esc(fmt_change_compact(e.quote.change_pct))}</span></div>'
                f'<p style="font-size:0.85rem;color:#555;margin:2px 0 4px 0;">理由: {_esc(e.reason)}</p>'
                f'<p style="font-size:0.8rem;color:#666;margin:0 0 4px 0;">注目材料: {_esc(e.material)}</p>'
                f'<p style="font-size:0.8rem;color:#666;margin:0 0 8px 0;">短期見通し: {_esc(e.short_term)}</p>'
            )
        return "".join(rows)

    return f"<h3>日本株</h3>{_render(top_picks.get('jp', []))}<h3>米国株</h3>{_render(top_picks.get('us', []))}"


def _instrument_scenarios_html(instrument_scenarios: List[InstrumentScenario]) -> str:
    if not instrument_scenarios:
        return f"<p>本日算出できる個別シナリオがありませんでした（{_esc(NOT_AVAILABLE)}）。</p>"
    parts = []
    for s in instrument_scenarios:
        parts.append(
            f"<h3>{_esc(s.label)}</h3>"
            f"<p style='font-size:0.88rem;'>{_esc(s.outlook)}</p>"
            f"<p style='font-size:0.78rem;color:#666;'>注目材料: {_esc(s.key_driver)}</p>"
            f"<p style='font-size:0.8rem;'><strong>強気:</strong> {_esc(s.bull_text or NOT_AVAILABLE)}</p>"
            f"<p style='font-size:0.8rem;'><strong>中立:</strong> {_esc(s.neutral_text or NOT_AVAILABLE)}</p>"
            f"<p style='font-size:0.8rem;'><strong>弱気:</strong> {_esc(s.bear_text or NOT_AVAILABLE)}</p>"
        )
    return "".join(parts)


def _okasan_sales_comments_html(comments: OkasanSalesComments) -> str:
    audiences = [
        ("富裕層のお客様向け", comments.wealthy),
        ("法人のお客様向け", comments.corporate),
        ("NISAご利用のお客様向け", comments.nisa),
        ("退職金のご相談のお客様向け", comments.retirement),
        ("相続・資産承継のご相談のお客様向け", comments.inheritance),
    ]
    parts = []
    for label, text in audiences:
        parts.append(f"<h3>{_esc(label)}</h3><p style='font-size:0.88rem;'>{_esc(text or NOT_AVAILABLE)}</p>")
    return "".join(parts)


def _dashboard_tile(label: str, quote: Optional[Quote]) -> str:
    if quote is None or quote.price is None:
        return (
            f'<div class="dash-tile"><div class="dash-label">{_esc(label)}</div>'
            f'<div class="dash-value">{_esc(NOT_AVAILABLE)}</div></div>'
        )
    cls = _trend_class(quote.change_pct)
    return (
        f'<div class="dash-tile"><div class="dash-label">{_esc(label)}</div>'
        f'<div class="dash-value">{_esc(fmt_price(quote.price))}</div>'
        f'<span class="badge {cls}">{_esc(fmt_change_compact(quote.change_pct))}</span></div>'
    )


def _dashboard_html(market: dict, analysis: AnalysisBundle, now: Optional[datetime] = None) -> str:
    """Today's Dashboard: 重要ニュース3件＋主要指標のカードグリッド（HTML最上部）。"""
    indices = market.get("indices", [])
    forex = market.get("forex", [])
    rates = market.get("rates", [])
    commodities = market.get("commodities", [])

    news_items = analysis.executive_summary[:3] or analysis.news_ranking[:3]
    if news_items:
        # v2.9（①）: 日本語訳があれば表示し、原文はネイティブのtitle属性（ホバー/
        # 長押しで表示）に残す（外部JS不要・「原文も必ず残す」要件を満たす）。
        news_html = "".join(
            f'<div class="dash-news"><a href="{_esc(item.headline.link)}" title="{_esc(item.headline.title)}">'
            f"{_esc(item.headline.display_title())}</a>{_translated_badge(item.headline)}"
            f"{_news_freshness_badge(item.headline.published, now)}</div>"
            for item in news_items
        )
    else:
        news_html = f"<p style='color:#9ca3af;font-size:0.85rem;'>{_esc(NOT_AVAILABLE)}</p>"

    tiles = [
        _dashboard_tile("ドル円", find_quote(forex, "米ドル/円")),
        _dashboard_tile("日経平均", find_quote(indices, "日経")),
        _dashboard_tile("NYダウ", find_quote(indices, "ダウ")),
        _dashboard_tile("NASDAQ", find_quote(indices, "ナスダック")),
        _dashboard_tile("SOX", find_quote(indices, "SOX")),
        _dashboard_tile("VIX", find_quote(indices, "VIX")),
        _dashboard_tile("10年債", find_quote(rates, "10年")),
        _dashboard_tile("WTI", find_quote(commodities, "WTI")),
        _dashboard_tile("金", find_quote(commodities, "金")),
        _dashboard_tile("Bitcoin", find_quote(commodities, "ビットコイン")),
    ]

    body = f'<div class="dash-news-block"><h3>重要ニュース3件</h3>{news_html}</div>' f'<div class="dashboard-grid">{"".join(tiles)}</div>'
    return _card("Today's Dashboard", body, extra_class="dashboard", anchor="dashboard-top")


def _sticky_dashboard_html(market: dict) -> str:
    """スクロール中も画面上部に小さく残す、Today's Dashboardの簡易版。"""
    indices = market.get("indices", [])
    forex = market.get("forex", [])

    def _mini(label: str, quote: Optional[Quote]) -> str:
        if quote is None or quote.price is None:
            return f'<span class="sticky-tile"><b>{_esc(label)}</b> {_esc(NOT_AVAILABLE)}</span>'
        cls = _trend_class(quote.change_pct)
        return (
            f'<span class="sticky-tile"><b>{_esc(label)}</b> {_esc(fmt_price(quote.price))} '
            f'<span class="badge {cls}">{_esc(fmt_change_compact(quote.change_pct))}</span></span>'
        )

    tiles = [
        _mini("ドル円", find_quote(forex, "米ドル/円")),
        _mini("日経平均", find_quote(indices, "日経")),
        _mini("NYダウ", find_quote(indices, "ダウ")),
    ]
    return f'<div class="sticky-dashboard">{"".join(tiles)}<a href="#dashboard-top" class="sticky-link">Dashboard ↑</a></div>'


def _section_nav_html(prev_anchor: Optional[str], next_anchor: Optional[str]) -> str:
    """各大項目の最後に表示する「← 前」「次 →」ワンタップ移動リンク。"""
    prev_html = f'<a class="nav-prev" href="#{_esc(prev_anchor)}">← 前</a>' if prev_anchor else ""
    next_html = f'<a class="nav-next" href="#{_esc(next_anchor)}">次 →</a>' if next_anchor else ""
    if not prev_html and not next_html:
        return ""
    return f'<div class="section-nav">{prev_html}{next_html}</div>'


def _stars_span(stars_text: str) -> str:
    """★の数に応じて色分けする（★5=赤／★4=オレンジ／★3=青／★2以下=グレー）。"""
    count = stars_text.count("★")
    css_class = "stars-5" if count >= 5 else "stars-4" if count == 4 else "stars-3" if count == 3 else "stars-2"
    return f'<span class="{css_class}">{_esc(stars_text)}</span>'


_STARS_SUFFIX_RE = re.compile(r"\s*([★☆]+)$")


def _split_title_stars(title: str) -> tuple:
    """タイトル末尾の「★★★★★」等の重要度表記を切り出す（表示色分け用）。"""
    m = _STARS_SUFFIX_RE.search(title)
    if not m:
        return title, ""
    return title[: m.start()].rstrip(), m.group(1)


def _toc_item_html(anchor: str, title: str) -> str:
    # v2.5: 目次リンクは新しいタブで開く（リンク先は同一HTML内のアンカー）
    label, stars_txt = _split_title_stars(title)
    stars_html = f" {_stars_span(stars_txt)}" if stars_txt else ""
    return f'<li><a href="#{anchor}" target="_blank" rel="noopener">{_esc(label)}{stars_html}</a></li>'


# トップメニューグリッド（v2.5）: 主要セクションへのジャンプボタン
MENU_GRID_ITEMS = [
    ("#market-narrative", "📝 本日の相場総括"),
    ("#todays-decision", "🎯 Today's Decision"),
    ("#dashboard-top", "📊 Dashboard"),
    ("#executive-summary", "📰 Executive Summary"),
    ("#future-intelligence", "🌍 Future Intelligence"),
    ("#news-ranking", "🔥 重要ニュース"),
    ("#watchlist", "👀 Watchlist"),
    ("#fi-stock", "📈 Stock Intelligence"),
    ("#fi-signals", "💹 世界のお金"),
    ("#data-quality", "✅ Data Quality"),
    ("#sales-prep", "📝 営業メモ"),
]


def _menu_grid_html() -> str:
    """レポート上部の主要ナビゲーション（AppMedia風のメニューグリッド・v2.5）。"""
    links = "".join(f'<a class="menu-btn" href="{href}">{_esc(label)}</a>' for href, label in MENU_GRID_ITEMS)
    return f'<div class="card no-filter menu-card"><div class="menu-grid">{links}</div></div>'


SEARCH_TAGS = ["AI", "半導体", "電力", "防衛", "EV", "金利", "為替", "消費"]


def _search_card_html() -> str:
    """簡易検索＋タグUI（v2.5）。セクションタイトル・本文にキーワードが含まれる
    カードだけを表示する。外部ライブラリ不使用・素のJavaScriptのみ。"""
    chips = "".join(f'<button type="button" class="tag-chip" onclick="applyTag(this)">{_esc(t)}</button>' for t in SEARCH_TAGS)
    return (
        '<div class="card no-filter search-card">'
        '<div class="search-box">'
        '<input id="search-input" type="search" placeholder="キーワード検索（セクション本文を含む）" oninput="filterCards()">'
        '<button type="button" class="search-clear" onclick="clearSearch()">クリア</button>'
        "</div>"
        f'<div class="tag-chips">{chips}</div>'
        '<p id="search-empty" class="fav-empty" style="display:none;">一致するセクションがありません</p>'
        "</div>"
    )


def _news_freshness_badge(published: str, now: Optional[datetime]) -> str:
    """ニュース1件ごとの鮮度表示（投稿日時・何時間前か・鮮度ラベル、v2.5）。

    v2.3のFreshness閾値と整合する表示専用バッジで、ランキング順位そのものは
    変更しない（順位への鮮度反映はv2.3のタイブレークで実装済み）。
    """
    dt = parse_published_datetime(published)
    if dt is None or now is None:
        return "<span class='fresh-badge fresh-unknown'>日時不明</span>"
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    hours = max(0.0, (now - dt).total_seconds() / 3600.0)
    time_txt = dt.astimezone(now.tzinfo).strftime("%m/%d %H:%M")
    if hours <= 6:
        cls, label = "fresh-new", "最新"
    elif hours <= 24:
        cls, label = "fresh-24", "24時間以内"
    elif hours <= 48:
        cls, label = "fresh-48", "48時間以内"
    else:
        cls, label = "fresh-old", "古い"
    return (
        f"<span class='fresh-badge {cls}'>{label}</span>"
        f"<span class='fresh-time'>投稿: {_esc(time_txt)}（約{int(hours)}時間前）</span>"
    )


def _options_panel_html() -> str:
    """表示オプション（コンパクト表示／営業セクション非表示／Future Intelligence
    一括開閉／ライト・ダーク切替）。localStorageに保存し次回表示時も維持する。
    分析ロジックには一切関与しない、表示切り替えのみのUIコントロール。
    """
    body = (
        "<div class='options-grid'>"
        "<label class='option-toggle'><input type='checkbox' id='opt-compact'> コンパクト表示</label>"
        "<label class='option-toggle'><input type='checkbox' id='opt-hide-sales'> 営業セクションを非表示</label>"
        "<label class='option-toggle'><input type='checkbox' id='opt-dark'> ダークモード</label>"
        "<label class='option-toggle'><input type='checkbox' id='opt-favs-only'> お気に入りのみ表示</label>"
        "<button type='button' id='opt-fi-toggle' class='option-btn'>Future Intelligenceを全て開閉</button>"
        "</div>"
        "<div class='fav-list-block'><strong>★ お気に入り</strong>"
        "<div id='fav-list'><p class='fav-empty'>お気に入りはありません</p></div></div>"
    )
    return _card("表示オプション", body, extra_class="options-card no-filter", anchor="display-options")


def _slug(text: str) -> str:
    """アンカーID用に空白・スラッシュを置換する（関連リンクのジャンプ先生成用）。"""
    return re.sub(r"[\s/]+", "-", text.strip())


NEW_BADGE_THRESHOLD = 80


def _new_badge(score: int) -> str:
    """既存のMomentum/Confidenceスコアがしきい値以上のときだけ表示するNEWバッジ
    （新たな分析ではなく、既存スコアに対する機械的な閾値判定のみ）。
    """
    return " <span class='new-badge'>NEW</span>" if score >= NEW_BADGE_THRESHOLD else ""


def _executive_summary_html(items: List[ExecutiveSummaryItem], now: Optional[datetime] = None) -> str:
    if not items:
        return f"<p>本日算出できる最重要ニュースがありませんでした（{_esc(NOT_AVAILABLE)}）。</p>"
    # v2.7（④⑤）: 通常表示は結論＋理由（2〜4行）のみ。日本株・ドル円・金利への
    # 影響、恩恵/悪影響銘柄、営業トークは「詳しく」で展開する。
    parts = []
    for item in items:
        trust = trust_for_source(item.headline.source)
        orig_html = f"<p style='margin:0 0 4px 0;'>原文: {_esc(item.headline.title)}</p>" if item.headline.title_ja else ""
        detail = (
            f"<p style='margin:0 0 4px 0;'>Source Trust: {_esc(trust.stars)}（{_esc(trust.tier)}）— {_esc(trust.reason)}</p>"
            + orig_html
            + f"<p style='margin:0 0 4px 0;'>日本株への影響: {_esc(item.jp_stock_impact)}</p>"
            f"<p style='margin:0 0 4px 0;'>ドル円への影響: {_esc(item.usdjpy_impact)}</p>"
            f"<p style='margin:0 0 4px 0;'>金利への影響: {_esc(item.rate_impact)}</p>"
            f"<p style='margin:0 0 4px 0;'>恩恵銘柄: {_esc(item.beneficiary_stocks or '該当なし')} ／ "
            f"悪影響銘柄: {_esc(item.negative_stocks or '該当なし')}</p>"
            f"<p style='margin:0 0 4px 0;'>ストラテジスト視点: {_esc(item.strategist_view)}</p>"
            f"<p style='margin:0;'><strong>営業トーク:</strong> 「{_esc(item.sales_talk)}」</p>"
        )
        parts.append(
            f"<h3>{item.rank}. {_esc(item.conclusion)} {_esc(item.stars)}{_translated_badge(item.headline)}</h3>"
            f'<p style="margin:0 0 4px 0;">{_news_freshness_badge(item.headline.published, now)} {_source_trust_inline(item.headline.source)}</p>'
            f"<p style='font-size:0.85rem;'>理由: {_esc(item.reason)}</p>"
            + _detail_block(detail)
        )
    return "".join(parts)


def _weekly_events_html(entries: List[WeeklyEventEntry]) -> str:
    """「Weekly Event Impact Calendar」（v2.7）。

    直近1週間の重要イベントを「近い順→重要度順」で、カウントダウン・★・
    影響対象つきのカード形式で表示する。通常表示は短く、なぜ重要か・
    マーケットへの影響・見るべきポイント・関連テーマは「詳しく」で展開。
    データが無い場合は無理に生成せず、その旨を表示する。
    """
    if not entries:
        return "<p>直近1週間の重要イベントは登録されていません（config.yamlのmacro_eventsに追加すると表示されます）。</p>"
    parts = [
        "<p class='legend'>config.yamlのmacro_events（登録情報）・経済カレンダー自動取得・"
        "決算発表予定（公開情報）から、今日〜7日後のイベントだけを表示します。重要度・"
        "影響対象は人手による対応表との照合で、AIによる新たな予測ではありません。日本時間基準です。</p>"
    ]
    for e in entries:
        targets_txt = "、".join(e.impact_targets) if e.impact_targets else "市場全体"
        watch_html = (
            "<ul class='plain' style='margin:4px 0;'>" + "".join(f"<li>{_esc(w)}</li>" for w in e.watch_points) + "</ul>"
            if e.watch_points
            else ""
        )
        themes_html = (
            f"<p style='margin:0;'>関連テーマ: {_esc('、'.join(e.related_themes))}</p>" if e.related_themes else ""
        )
        # v3.0（③）: 取得元・Source Trust・取得時刻を表示（自動取得は取得時刻あり）
        fetched_txt = ""
        if e.fetched_at:
            dt = parse_published_datetime(e.fetched_at)
            fetched_txt = f" ／ 取得時刻: {dt.strftime('%m/%d %H:%M') if dt else _esc(e.fetched_at)}"
        source_html = (
            f"<p style='margin:0 0 4px 0;'>Source: {_esc(e.source)}"
            f"{(' ／ Source Trust: ' + _esc(e.source_stars)) if e.source_stars else ''}{fetched_txt}</p>"
        )
        detail = (
            source_html
            + f"<p style='margin:0 0 4px 0;'>なぜ重要か: {_esc(e.why_important)}</p>"
            f"<p style='margin:0 0 4px 0;'>想定される影響: {_esc(e.expected_impact)}</p>"
            + (f"<p style='margin:0 0 4px 0;'>見るべきポイント:</p>{watch_html}" if watch_html else "")
            + themes_html
        )
        time_txt = f" {e.time_str}" if e.time_str else ""
        parts.append(
            "<div class='event-row'>"
            f"<div class='row'><span><span class='event-countdown'>{_esc(e.countdown_text)}</span>"
            f"{_esc(e.label)}</span>"
            f"<span>{_stars_span(e.stars)} <span class='imp'>重要度{e.importance}</span></span></div>"
            f"<p style='font-size:0.78rem;color:#666;margin:2px 0 0 0;'>"
            f"{_esc(e.date_str)}{_esc(time_txt)} ／ {_esc(e.region)} ／ {_esc(e.category)} ／ 影響: {_esc(targets_txt)}</p>"
            + _detail_block(detail)
            + "</div>"
        )
    return "".join(parts)


def _scenarios_v2_html(scenarios: List[ScenarioV2Entry]) -> str:
    """「Scenario Engine v2」（v2.8・③）。期待値の高い最大3シナリオを①②③で表示。

    通常表示は結論（タイトル・確率・★・マーケット影響）だけ短く、発生条件・
    恩恵/悪影響セクター・注目銘柄・因果関係・時間軸・一般的な反応パターンは
    「詳しく」で展開する。
    """
    if not scenarios:
        return f"<p>本日組み立てられるシナリオがありませんでした（{_esc(NOT_AVAILABLE)}）。</p>"
    circled = {1: "①", 2: "②", 3: "③"}
    parts = [
        "<p class='legend'>既存の相場シナリオ（強気/中立/弱気の確率）と業種の追い風・逆風、"
        "ウォッチリスト・因果チェーンのみから、期待値（確率）の高い順に最大3つへ整理したものです。"
        "新たな確率予測・断定的な過去事例は生成していません。</p>"
    ]
    for s in scenarios:
        benefit = "、".join(s.beneficiary_sectors) if s.beneficiary_sectors else "該当なし"
        adverse = "、".join(s.adverse_sectors) if s.adverse_sectors else "該当なし"
        watch = "、".join(s.watch_names) if s.watch_names else "該当なし"
        chain_html = f"<p style='margin:0 0 4px 0;'>因果関係: {_esc(s.causal_chain.replace(chr(10), ' → '))}</p>" if s.causal_chain else ""
        detail = (
            f"<p style='margin:0 0 4px 0;'>発生条件: {_esc(s.trigger_condition)}</p>"
            f"<p style='margin:0 0 4px 0;'>恩恵セクター: {_esc(benefit)}</p>"
            f"<p style='margin:0 0 4px 0;'>悪影響セクター: {_esc(adverse)}</p>"
            f"<p style='margin:0 0 4px 0;'>注目銘柄: {_esc(watch)}</p>"
            + chain_html
            + f"<p style='margin:0 0 4px 0;'>時間軸: {_esc(s.time_horizon)}</p>"
            f"<p style='margin:0;'>一般的な反応パターン: {_esc(s.historical_note)}</p>"
        )
        parts.append(
            f"<h3>{circled.get(s.rank, str(s.rank))} {_esc(s.title)} {_esc(s.stars)}"
            f"<span class='imp'>確率{s.probability}%</span></h3>"
            f"<p style='font-size:0.85rem;margin:2px 0 4px 0;'>マーケット影響: {_esc(s.market_impact)}</p>"
            + _detail_block(detail)
        )
    return "".join(parts)


def _learning_history_html(history: List[LearningHistoryEntry]) -> str:
    """「Learning History」（v2.8・①）。過去のAI判断の答え合わせ結果を表示。"""
    if not history:
        return (
            "<p>まだ答え合わせできる過去の記録がありません。"
            "本機能は毎日のAI判断を記録し、30/90/180日後に実際の市場と自動で比較します"
            "（記録が貯まると、この場所に的中・外れの履歴が表示されます）。</p>"
        )
    parts = [
        "<p class='legend'>毎日のAI判断（重要ニュース・テーマ・シナリオ）を記録し、"
        "30/90/180日後の日経平均と機械的に比較した答え合わせです。評価はルールベースで、"
        "AIが新たな予測を生成するものではありません。</p>"
    ]
    evaluated = [h for h in history if h.evaluated]
    waiting = [h for h in history if not h.evaluated]

    def _row(h: LearningHistoryEntry) -> str:
        cls = {"的中": "learn-hit", "部分的中": "learn-wait", "外れ": "learn-miss"}.get(h.evaluation_status, "learn-wait")
        status_html = (
            f"<span class='{cls}'>{_esc(h.evaluation_stars)} {_esc(h.evaluation_status)}（{h.evaluation_horizon}日後）</span>"
            if h.evaluated
            else f"<span class='learn-wait'>評価待ち（経過{h.days_elapsed}日）</span>"
        )
        detail = (
            f"<p style='margin:0 0 4px 0;'>重要ニュース: {_esc(h.headline or NOT_AVAILABLE)}</p>"
            f"<p style='margin:0 0 4px 0;'>重要テーマ: {_esc(h.theme or NOT_AVAILABLE)}</p>"
            f"<p style='margin:0 0 4px 0;'>シナリオ配分: {_esc(h.scenario_summary)}</p>"
            + (f"<p style='margin:0;'>答え合わせ: {_esc(h.evaluation_note)}</p>" if h.evaluated else "")
        )
        return (
            f"<div class='row'><span>{_esc(h.date)}</span>{status_html}</div>" + _detail_block(detail)
        )

    parts.extend(_row(h) for h in evaluated)
    if waiting:
        parts.append(_detail_block("".join(_row(h) for h in waiting), label=f"評価待ちの記録を表示（{len(waiting)}件）"))
    return "".join(parts)


def _theme_learning_html(stats: List[ThemeLearningStat]) -> str:
    """「Theme Confidence Learning」（v2.8・②）の勝率集計を表示。"""
    if not stats:
        return (
            "<p>まだ学習データが貯まっていません。毎日のテーマ別診断を記録し、"
            "30日後の地合いと比較して勝率・平均リターンを集計します"
            "（記録が貯まると、この場所にテーマ別の勝率が表示されます）。</p>"
        )
    parts = [
        "<p class='legend'>毎日のテーマ予想を蓄積し、30日後の日経平均（地合いの代理指標）と"
        "比較して集計した勝率です。この勝率はFuture IntelligenceのConfidenceを上下限つきで"
        "実績補正するのに使われます。</p>"
    ]
    for s in stats:
        wr = f"{round(s.win_rate * 100)}%" if s.win_rate is not None else NOT_AVAILABLE
        ret = f"{s.avg_return_pct:+.1f}%" if s.avg_return_pct is not None else NOT_AVAILABLE
        dur = f"{s.avg_duration_days:.0f}日" if s.avg_duration_days is not None else NOT_AVAILABLE
        detail = (
            f"<p style='margin:0 0 4px 0;'>初回登場: {_esc(s.first_seen or NOT_AVAILABLE)} ／ サンプル: {s.samples}件（的中{s.wins}件）</p>"
            f"<p style='margin:0 0 4px 0;'>平均リターン（地合い代理）: {_esc(ret)} ／ 平均継続: {_esc(dur)}</p>"
            + (f"<p style='margin:0 0 4px 0;'>成功しやすい条件: {_esc(s.success_condition)}</p>" if s.success_condition else "")
            + (f"<p style='margin:0;'>失敗しやすい条件: {_esc(s.failure_condition)}</p>" if s.failure_condition else "")
        )
        parts.append(
            f"<div class='row'><span>{_esc(s.label)}</span><span>勝率{_esc(wr)}（{s.samples}件）</span></div>"
            + _detail_block(detail)
        )
    return "".join(parts)


def _call_priorities_html(entries: List[CallPriorityEntry]) -> str:
    if not entries:
        return f"<p>本日提案可能な顧客タイプがありませんでした（{_esc(NOT_AVAILABLE)}）。</p>"
    parts = []
    for entry in entries:
        parts.append(
            f"<h3>{_esc(entry.customer_type)}</h3>"
            f"<p style='font-size:0.85rem;'>理由: {_esc(entry.reason)}</p>"
            f"<p style='font-size:0.82rem;color:#555;'>話題: {_esc(entry.topic)}</p>"
            f"<p style='font-size:0.85rem;'>営業トーク例: 「{_esc(entry.sales_talk)}」</p>"
        )
    return "".join(parts)


def _market_impact_html(entries: List[MarketImpactEntry]) -> str:
    if not entries:
        return f"<p>本日算出できるマーケットインパクトがありませんでした（{_esc(NOT_AVAILABLE)}）。</p>"
    rows = "".join(
        f"<tr><td>{_esc(entry.target)}</td><td>{_esc(entry.stars)}</td><td>{_esc(entry.direction)}</td></tr>"
        for entry in entries
    )
    return f"<table><tr><th>対象</th><th>影響度</th><th>方向</th></tr>{rows}</table>"


def _sector_strength_html(entries: List[SectorStrengthEntry]) -> str:
    if not entries:
        return f"<p>本日予測可能な業種がありませんでした（{_esc(NOT_AVAILABLE)}）。</p>"
    rows = "".join(
        f'<div class="row"><span>{_esc(entry.arrow)} {_esc(entry.label)}</span></div>'
        f'<p style="font-size:0.8rem;color:#666;margin:2px 0 8px 0;">{_esc(entry.reason)}</p>'
        for entry in entries
    )
    return rows


def _strategist_views_html(views: List[StrategistView]) -> str:
    if not views:
        return f"<p>本日算出できるストラテジスト視点がありませんでした（{_esc(NOT_AVAILABLE)}）。</p>"
    parts = []
    for i, view in enumerate(views, start=1):
        score_html = ""
        if view.score is not None:
            s = view.score
            score_html = (
                "<p style='font-size:0.78rem;color:#666;'>重要度内訳（8軸）: "
                f"市場インパクト{s.market_impact}／継続性{s.continuity}／営業利用価値{s.sales_value}／"
                f"日本株影響度{s.jp_impact}／米国株影響度{s.us_impact}／個別株展開{s.stock_expansion}／"
                f"テーマ株展開{s.theme_expansion}／今後数週間重要か{s.weeks_ahead}</p>"
            )
        beneficiary = "、".join(view.beneficiary_names) if view.beneficiary_names else "該当なし"
        negative = "、".join(view.negative_names) if view.negative_names else "該当なし"
        parts.append(
            f"<h3>{i}. {_esc(view.headline.title)} {_esc(view.importance_stars)}</h3>"
            f"<p style='font-size:0.85rem;'>岡三ストラテジストならどう見るか: {_esc(view.strategist_take)}</p>"
            f"<p style='font-size:0.82rem;color:#555;'>重要テーマ: {_esc(view.theme)} ／ 関連セクター: {_esc(view.related_sector)}</p>"
            f"<p style='font-size:0.82rem;color:#555;'>恩恵銘柄: {_esc(beneficiary)} ／ 悪影響銘柄: {_esc(negative)}</p>"
            f"<p style='font-size:0.85rem;'><strong>営業で話すポイント:</strong> 「{_esc(view.sales_point)}」</p>"
            f"{score_html}"
        )
    return "".join(parts)


def _morning_meeting_comment_html(comment: MorningMeetingComment) -> str:
    return (
        f"<h3>30秒バージョン</h3><p style='font-size:0.85rem;'>{_esc(comment.short_30s or NOT_AVAILABLE)}</p>"
        f"<h3>1分バージョン</h3><p style='font-size:0.85rem;'>{_esc(comment.medium_1min or NOT_AVAILABLE)}</p>"
        f"<h3>3分バージョン</h3><p style='font-size:0.85rem;'>{_esc(comment.long_3min or NOT_AVAILABLE)}</p>"
    )


# 公式ソースと判定するドメイン断片（公的機関・取引所・中央銀行・当局・一次情報）。
_OFFICIAL_DOMAIN_HINTS = (
    ".go.jp", ".gov", "boj.or.jp", "mof.go.jp", "jpx.co.jp", "fsa.go.jp", "stat.go.jp",
    "federalreserve.gov", "sec.gov", "treasury.gov", "ecb.europa.eu", "edinet", "release.tdnet",
)


def _domain_of(url: str) -> str:
    m = re.search(r"https?://([^/]+)", url or "")
    return m.group(1).lower() if m else ""


def _source_list_html(sources: SourceRegistry) -> str:
    refs = sources.all()
    if not refs:
        return f"<p>記録された出典はありません（{_esc(NOT_AVAILABLE)}）。</p>"
    by_category: dict = {}
    for ref in refs:
        by_category.setdefault(ref.category, []).append(ref)

    # v3.1（改善7）: 初期表示は要約（情報源数・カテゴリ数・公式/海外内訳・主要TOP10）。
    # 全URL一覧は「詳しく」に折りたたむ（従来通り全件を保持）。
    domains = [_domain_of(r.url) for r in refs]
    official = sum(1 for d in domains if any(h in d for h in _OFFICIAL_DOMAIN_HINTS))
    overseas = sum(1 for d in domains if d and not d.endswith(".jp"))
    top10 = "、".join(_esc(r.label) for r in refs[:10])
    summary_rows = [
        ("情報源数", f"{len(refs)}件"),
        ("カテゴリ数", f"{len(by_category)}カテゴリ"),
        ("公式ソース数", f"{official}件"),
        ("海外ソース数", f"{overseas}件"),
    ]
    summary_html = "".join(
        f"<div class='row'><span>{_esc(k)}</span><span>{_esc(v)}</span></div>" for k, v in summary_rows
    )
    summary_html += f"<p class='td-sub'>主要ソースTOP10: {top10}</p>"

    parts = []
    for category, items in by_category.items():
        links = "".join(f'<li><a href="{_esc(item.url)}">{_esc(item.label)}</a></li>' for item in items)
        parts.append(f"<h3>{_esc(category)}</h3><ul class='plain'>{links}</ul>")
    full_list = "".join(parts)
    legend = "<p class='legend'>初期表示は情報源の概要のみです。参照URLの全一覧は「詳しく」で確認できます。</p>"
    return legend + summary_html + _detail_block(full_list, label=f"参照URLの全一覧を表示（{len(refs)}件）")


def _fmt_stats_dt(dt, tz) -> str:
    if dt is None:
        return NOT_AVAILABLE
    if tz is not None:
        dt = dt.astimezone(tz)
    return dt.strftime("%m/%d %H:%M")


def _news_freshness_card(freshness: Optional[DataFreshnessStats]) -> str:
    """「News Freshness」カード（v2.3）。本日のニュースの鮮度を一目で確認する。

    表示専用の計測値であり、ランキング・分析ロジックには一切影響しない。
    """
    if freshness is None:
        return ""
    tz = freshness.generated_at.tzinfo
    avg_txt = f"{freshness.avg_age_hours:.0f}時間" if freshness.avg_age_hours is not None else NOT_AVAILABLE
    rows = [
        ("最新ニュース日時", _fmt_stats_dt(freshness.newest_published, tz)),
        ("最も古い採用記事日時", _fmt_stats_dt(freshness.oldest_adopted, tz)),
        ("採用記事平均経過時間", avg_txt),
        ("採用記事件数", f"{freshness.adopted_count}件"),
        ("RSS取得件数", f"{freshness.rss_fetched_total}件"),
        ("ランキング対象件数", f"{freshness.deduped_total}件"),
        ("レポート生成日時", freshness.generated_at.strftime("%m/%d %H:%M")),
    ]
    rows_html = "".join(f"<div class='row'><span>{_esc(k)}</span><span>{_esc(v)}</span></div>" for k, v in rows)
    eval_html = (
        f"<div class='row'><span>データ鮮度評価</span>"
        f"<span>{_stars_span(freshness_stars(freshness.avg_age_hours))} {_esc(freshness_label(freshness.avg_age_hours))}</span></div>"
    )
    # v2.9（⑤ 情報取得時刻の見える化）: 「このレポートは何時時点の情報か」を
    # 一目で分かるように、HTML生成時刻・市場データ取得時刻（同一バッチ取得のため
    # 生成時刻と同時刻）・各ニュースソースの取得時刻を「詳しく」に表示する。
    generated_txt = freshness.generated_at.strftime("%Y-%m-%d %H:%M")
    timestamps_html = (
        f"<p style='margin:0 0 4px 0;'>HTML生成時刻: {_esc(generated_txt)}</p>"
        f"<p style='margin:0 0 8px 0;'>市場データ・為替・金利・コモディティ取得時刻: {_esc(generated_txt)}"
        "（すべて同一バッチで取得）</p>"
    )
    source_rows = "".join(
        f"<div class='row'><span>{_esc(e.name)}</span>"
        f"<span>{'✅' if e.ok else '❌'} {e.count}件 ／ 取得: {_esc(_fmt_stats_dt(e.fetched_at, tz))}</span></div>"
        for e in sorted(freshness.source_health, key=lambda e: (-e.count, e.name))
    )
    if not source_rows:
        source_rows = f"<p>{_esc(NOT_AVAILABLE)}</p>"
    timestamps_html += "<p style='margin:8px 0 4px 0;font-weight:600;'>各ニュースソースの取得時刻</p>" + source_rows
    return _card(
        "News Freshness（データ鮮度）",
        rows_html + eval_html + _detail_block(timestamps_html, label="情報取得時刻を詳しく見る"),
        extra_class="digest",
        anchor="news-freshness",
    )


def _rashinban_card(rashinban: Optional[RashinbanKnowledge]) -> str:
    """「Rashinban Learning Source」カード（v2.6）。

    data/rashinban/ に置いた岡三「羅針盤」の読み込み状況のみを小さく表示する。
    社内資料の本文・抜粋は公開HTMLへ一切載せない（ファイル名・日付・
    抽出フレーム数・使用状況だけを表示する）。
    """
    if rashinban is None:
        return ""
    if rashinban.has_content():
        rows = [
            ("読み込みファイル", "、".join(rashinban.source_files)),
            ("最新日付", rashinban.latest_date or "日付不明"),
            ("抽出した分析フレーム", f"{rashinban.frame_count()}件"),
            (
                "使用状況",
                f"重点テーマ{len(rashinban.emphasized_theme_labels)}件を分析へ反映"
                if rashinban.emphasized_theme_labels
                else "分析フレームとして参照（重点テーマの一致なし）",
            ),
        ]
        rows_html = "".join(f"<div class='row'><span>{_esc(k)}</span><span>{_esc(v)}</span></div>" for k, v in rows)
        note = (
            "<p class='legend'>羅針盤は本文転載ではなく、分析品質を上げるための"
            "分析フレーム（判断の型）として利用しています。本文・抜粋は表示しません。</p>"
        )
        body = rows_html + note
    else:
        body = (
            "<p class='legend'>data/rashinban/ に羅針盤ファイル（.md/.txt）が未配置のため、"
            "本日は既存の分析ロジックのみで生成しています（羅針盤なしでも通常動作します）。</p>"
        )
    return _card("Rashinban Learning Source（学習ソース）", body, extra_class="digest", anchor="rashinban-learning")


def _translation_status(analysis: AnalysisBundle) -> dict:
    """本日のニュース見出しから、翻訳の状況を機械的に集計する（v3.1・改善2/8）。

    分析ロジックには一切影響しない、表示用のステータス。英語見出しのうち
    日本語訳が付いた件数・付かなかった件数を数えるだけ（API未設定の判定は
    llm_enhancer.is_available()を併用）。
    """
    from ..analysis import translation as _t
    from ..analysis import llm_enhancer as _llm

    seen: dict = {}
    for src in (analysis.news_ranking, analysis.executive_summary):
        for it in src:
            h = getattr(it, "headline", None)
            if h is not None:
                seen[getattr(h, "title", "")] = h
    english = [(t, h) for t, h in seen.items() if _t.is_english(t)]
    untranslated = [h for t, h in english if not getattr(h, "title_ja", "")]
    return {
        "english_total": len(english),
        "untranslated": len(untranslated),
        "translated": len(english) - len(untranslated),
        "api_available": _llm.is_available(),
    }


def _translation_status_text(st: dict) -> str:
    """翻訳ステータスを1行の日本語にする（未翻訳が残る場合は明確に警告）。"""
    if st["english_total"] == 0:
        return "翻訳対象の英語記事なし（翻訳不要）"
    if st["untranslated"] == 0:
        return f"翻訳済み {st['translated']}件（英文原文も保持）"
    if not st["api_available"]:
        return f"翻訳API未設定のため英文のまま表示（未翻訳 {st['untranslated']}件）"
    return f"翻訳APIは設定済みですが未翻訳の記事があります（未翻訳 {st['untranslated']}件）"


def _calendar_status_text(analysis: AnalysisBundle) -> str:
    """経済カレンダーの取得状況（自動取得／登録情報の内訳）。"""
    events = analysis.weekly_events
    if not events:
        return "今週分の登録・自動取得イベントなし"
    auto = sum(1 for e in events if getattr(e, "source", "登録情報") != "登録情報")
    registered = len(events) - auto
    return f"今週{len(events)}件（自動取得{auto}件／登録情報{registered}件）"


def _data_quality_html(
    freshness: Optional[DataFreshnessStats],
    market: dict,
    analysis: AnalysisBundle,
    anomalies: Optional[List[AnomalyEntry]] = None,
    translation_st: Optional[dict] = None,
) -> str:
    """「Data Quality」セクション（v2.3、v3.1で翻訳API状態・経済カレンダー状態・
    異常値チェック・取得失敗ソースを追加）。今日のレポートが最新データに基づくかを
    一目で確認するための機械的な可用性・鮮度指標（分析ロジックには不関与）。
    """
    anomalies = anomalies if anomalies is not None else detect_anomalies(market)
    translation_st = translation_st if translation_st is not None else _translation_status(analysis)
    all_quotes = (
        market.get("indices", []) + market.get("forex", []) + market.get("rates", []) + market.get("commodities", [])
    )
    market_ok = sum(1 for q in all_quotes if q.price is not None)
    fi = analysis.future_intelligence
    fi_ok = sum(1 for xs in (fi.megatrends, fi.theme_momentum, fi.theme_diagnosis) if xs)
    watch_entries = analysis.watchlist_quicklist.get("jp", []) + analysis.watchlist_quicklist.get("us", [])
    watch_ok = sum(1 for e in watch_entries if e.quote.price is not None)

    news_stars_txt = freshness_stars(freshness.avg_age_hours) if freshness else "★☆☆☆☆"
    rows = [
        ("ニュース取得", _stars_span(news_stars_txt)),
        ("市場データ", _stars_span(availability_stars(market_ok, len(all_quotes)))),
        ("Future Intelligence", _stars_span(availability_stars(fi_ok, 3))),
        ("Watchlist", _stars_span(availability_stars(watch_ok, len(watch_entries)))),
        # v3.1（改善8）: 翻訳API状態・経済カレンダー取得状態・異常値チェックを追加
        ("翻訳API状態", _esc(_translation_status_text(translation_st))),
        ("経済カレンダー", _esc(_calendar_status_text(analysis))),
        ("異常値チェック", _esc(anomaly_status_label(anomalies))),
    ]
    if freshness is not None:
        tz = freshness.generated_at.tzinfo
        avg_txt = f"{freshness.avg_age_hours:.0f}時間" if freshness.avg_age_hours is not None else NOT_AVAILABLE
        failed = [e for e in freshness.source_health if not e.ok]
        failed_txt = "、".join(e.name for e in failed) if failed else "なし"
        rows.extend(
            [
                ("更新日時", _esc(freshness.generated_at.strftime("%H:%M %Z").strip())),
                ("最新ニュース", _esc(_fmt_stats_dt(freshness.newest_published, tz))),
                ("市場データ取得時刻", _esc(freshness.generated_at.strftime("%m/%d %H:%M"))),
                ("平均鮮度", _esc(avg_txt)),
                ("情報源", _esc(f"{len(freshness.source_health)}")),
                ("RSS取得件数", _esc(f"{freshness.rss_fetched_total}件")),
                ("ランキング対象", _esc(f"{freshness.deduped_total}件")),
                ("取得失敗ソース", _esc(failed_txt)),
            ]
        )
    rows_html = "".join(f"<div class='row'><span>{_esc(k)}</span><span>{v}</span></div>" for k, v in rows)
    # v3.1（改善2）: 未翻訳の英語記事が残る場合は目立つ警告を出す
    warn_html = ""
    if translation_st["english_total"] and translation_st["untranslated"]:
        warn_html = (
            f"<p class='dq-warn'>⚠️ {_esc(_translation_status_text(translation_st))}。"
            "ANTHROPIC_API_KEY を設定すると日本語訳が付きます（過去に翻訳済みの見出しはキャッシュから日本語表示）。</p>"
        )
    # v3.1（改善3/8）: 異常値の詳細（あれば列挙、なければ「異常値なし」）
    if anomalies:
        anomaly_html = "<p class='dq-warn'>⚠️ 異常値の可能性（取得値の確認を推奨）:</p><ul class='plain'>" + "".join(
            f"<li>{_esc(a.message)}</li>" for a in anomalies
        ) + "</ul>"
    else:
        anomaly_html = "<p class='legend'>異常値チェック: 主要指標・為替・金利に想定範囲外の値はありませんでした（異常値なし）。</p>"
    legend = (
        "<p class='legend'>本日のレポートが最新データに基づいているかを確認するための"
        "機械的な指標です（取得できた項目の割合と記事の経過時間から算出。分析内容の評価ではありません）。</p>"
    )
    return legend + warn_html + rows_html + anomaly_html


FI_BLOCK_TOC_HTML = [
    ("fi-signals", "Today's Future Signals", "★★★★★"),
    ("fi-theme", "Theme Intelligence", "★★★★★"),
    ("fi-industry", "Industry Intelligence", "★★★★☆"),
    ("fi-stock", "Stock Intelligence", "★★★★★"),
    ("fi-longterm", "Long-term Strategy", "★★★★☆"),
]

# 表示オプション「営業セクションを非表示」でまとめて隠す対象（v2.2）。
SALES_SECTION_ANCHORS = {
    "sales-prep",
    "sales-talk",
    "sales-comments",
    "okasan-sales-comments",
    "morning-meeting-comment",
    "expanded-qa",
}

# v3.1（改善6）: 営業系だが sales-section 扱いにしない（既存テスト維持）ものを、
# 初期状態だけ折りたたむ対象。投資判断に必須ではないため畳んで下部に置く。
COLLAPSED_BY_DEFAULT_ANCHORS = {
    "call-priorities",
    "chat-topics",
}


def _todays_action_html(market: dict, analysis: AnalysisBundle) -> str:
    """「Today's Action」。Future Intelligence Engineの最上部に表示する、
    その日確認すべき事項（既存データのみから機械的に生成。新規予測なし）。
    """
    items = todays_action_items(market, analysis)
    if not items:
        return f"<p>本日提示できるToday's Actionがありませんでした（{_esc(NOT_AVAILABLE)}）。</p>"
    lis = "".join(f"<li>{_esc(i)}</li>" for i in items)
    return f"<div class='todays-action'><strong>🎯 Today's Action（今日確認すべきこと）</strong><ul class='plain'>{lis}</ul></div>"


def _fi_top_change_highlight_html(bundle: FutureIntelligenceBundle) -> str:
    """「今日もっとも重要な変化」。新たな分析は行わず、既に算出済みの
    Theme Momentum Scoreが最も高いテーマの理由をそのまま抜粋するだけの
    機械的なハイライト表示（v2.1）。
    """
    if not bundle.theme_momentum:
        return f"<p>本日算出できる変化のハイライトがありませんでした（{_esc(NOT_AVAILABLE)}）。</p>"
    top = max(bundle.theme_momentum, key=lambda tm: tm.momentum_score)
    return (
        f"<p style='font-size:0.85rem;'><strong>{_esc(top.label)}</strong>"
        f"（Momentum {top.momentum_score}/100・{_esc(top.momentum_label)}）— {_esc(top.reason)}</p>"
    )


FI_SUMMARY_COUNT = 8  # v2.7（③⑧）: FI各リストの通常表示件数（残りは「詳しく」内）


def _fi_conclusion_html(bundle: FutureIntelligenceBundle) -> str:
    """FIの冒頭に置く「結論→重要ポイント3つ」（v2.7・⑧）。

    新しい分析は行わず、既存のTheme Momentum・テーマ別診断・世界のお金の流れ
    （いずれも計算済み）から最上位のシグナルを機械的に転記するだけの要約表示。
    """
    points = []
    top_momentum = max(bundle.theme_momentum, key=lambda t: t.momentum_score, default=None)
    if top_momentum:
        points.append(
            f"本日最も勢いのあるテーマは「{_esc(top_momentum.label)}」"
            f"（Momentum {top_momentum.momentum_score}/100・{_esc(top_momentum.momentum_label)}）です。"
        )
    top_diag = max(bundle.theme_diagnosis, key=lambda t: t.confidence_score, default=None)
    if top_diag:
        points.append(
            f"分析根拠が最も充実しているテーマは「{_esc(top_diag.label)}」"
            f"（Confidence {top_diag.confidence_score}%・{_esc(top_diag.phase)}）です。"
        )
    if bundle.early_signals:
        points.append(f"初動シグナルは「{_esc(bundle.early_signals[0].label)}」など{len(bundle.early_signals)}件を検知しています。")
    elif bundle.capital_flow_market_mood:
        points.append(f"市場ムード（参考）: {_esc(bundle.capital_flow_market_mood)}")
    if not points:
        return ""
    conclusion = points[0]
    points_html = "".join(f"<li>{p}</li>" for p in points[:3])
    return (
        "<div class='fi-conclusion'><span class='imp'>結論</span> "
        f"<strong>{conclusion}</strong>"
        f"<ul class='plain' style='margin:6px 0 0 0;'>{points_html}</ul>"
        "<p class='legend' style='margin:6px 0 0 0;'>詳細は下の各ブロックの「詳しく」で確認できます。</p></div>"
    )


def _future_intelligence_html(bundle: FutureIntelligenceBundle) -> str:
    """「Future Intelligence Engine」をレンダリングする。

    具体的な残り年数・市場規模・補助金額等は生成せず、本日の関連見出し件数・
    重要ニュースとの一致・durable_themes・causal_rulesから導いた定性的な
    ラベルのみを表示する。

    v2.1: 既存14項目の分析ロジック・データは一切変更せず、「世界→テーマ→業界→
    銘柄→長期戦略」の5ブロック（Information Architecture）へ再構成して表示する。
    """
    if not bundle.megatrends:
        return f"<p>本日算出できるテーマがありませんでした（{_esc(NOT_AVAILABLE)}）。</p>"

    # 関連リンク（⑨）用の照合セット。新たな関連付けロジックではなく、既存の
    # theme_diagnosis.label／stock_intelligence.ticker と一致する場合のみ
    # ジャンプリンク化する（一致しない場合は通常テキストのまま）。
    theme_anchor_labels = {td.label for td in bundle.theme_diagnosis}
    stock_anchor_tickers = {s.ticker for s in bundle.stock_intelligence}

    def _theme_link(label: str) -> str:
        if label in theme_anchor_labels:
            return f'<a href="#theme-{_esc(_slug(label))}">{_esc(label)}</a>'
        return _esc(label)

    def _stock_link(ticker: str, text: str) -> str:
        if ticker in stock_anchor_tickers:
            return f'<a href="#stock-{_esc(_slug(ticker))}">{_esc(text)}</a>'
        return _esc(text)

    toc_html = "".join(
        f'<li><a href="#{anchor}">{_esc(title)} {_stars_span(stars)}</a></li>' for anchor, title, stars in FI_BLOCK_TOC_HTML
    )
    parts = [
        "<p class='legend'>本セクションは具体的な残り年数・市場規模・補助金額等の断定的な数値は使用せず、"
        "本日の関連ニュース件数と既存の継続性フラグから導いた定性的な考察です。</p>",
        _fi_conclusion_html(bundle),
        f"<div class='fi-toc'><strong>Future Intelligence 目次</strong><ul>{toc_html}</ul></div>",
    ]

    # ① Today's Future Signals（最重要ブロック・毎朝最初に見る場所）
    parts.append(
        "<details class='fi-block fi-block-signals' id='fi-signals' open>"
        f"<summary><h3>🌍 Today's Future Signals {_stars_span('★★★★★')}</h3></summary>"
        "<p class='fi-block-desc'>今日世界で何が変化したかを、3分で最初に把握するブロックです。</p>"
    )
    parts.append("<h4>今日もっとも重要な変化</h4>")
    parts.append(_fi_top_change_highlight_html(bundle))
    parts.append("<h4>世界のメガトレンド</h4>")
    # v2.7（③）: 本日の関連見出し件数の多い順に上位のみ通常表示（重要度で自動選別。
    # 算出ロジックは不変・表示の選別のみ）。残りは「詳しく」で展開。
    megatrends_ranked = sorted(bundle.megatrends, key=lambda m: -m.headline_count)

    def _megatrend_html(m) -> str:
        return (
            f"<div class='row'><span>{_theme_link(m.label)} {_esc(m.stars)}</span>"
            f"<span>{_esc(m.phase)} ／ 継続性: {_esc(m.continuity)}</span></div>"
            f"<p style='font-size:0.8rem;color:#666;margin:2px 0 8px 0;'>"
            f"本日の関連見出し: {m.headline_count}件／{_esc(m.why_growing)}</p>"
        )

    parts.extend(_megatrend_html(m) for m in megatrends_ranked[:FI_SUMMARY_COUNT])
    rest_megatrends = megatrends_ranked[FI_SUMMARY_COUNT:]
    if rest_megatrends:
        parts.append(
            _detail_block("".join(_megatrend_html(m) for m in rest_megatrends), label=f"残り{len(rest_megatrends)}テーマを表示")
        )

    parts.append("<h4>Theme Momentum Score</h4>")
    if bundle.theme_momentum:
        # v2.7（③）: スコアの高い順に上位のみ通常表示（スコア計算は不変）
        momentum_ranked = sorted(bundle.theme_momentum, key=lambda t: -t.momentum_score)

        def _momentum_html(tm) -> str:
            sector_html = ""
            if tm.related_sector:
                names_txt = "、".join(tm.beneficiary_names) if tm.beneficiary_names else "該当なし"
                sector_html = f"<br>関連セクター: {_esc(tm.related_sector)} ／ 関連銘柄: {_esc(names_txt)}"
            return (
                f"<div class='row'><span>{_theme_link(tm.label)}{_new_badge(tm.momentum_score)}</span>"
                f"<span>{tm.momentum_score}/100（{_esc(tm.momentum_label)}）</span></div>"
                f"<p style='font-size:0.8rem;color:#666;margin:2px 0 8px 0;'>{_esc(tm.reason)}{sector_html}</p>"
            )

        parts.extend(_momentum_html(tm) for tm in momentum_ranked[:FI_SUMMARY_COUNT])
        rest_momentum = momentum_ranked[FI_SUMMARY_COUNT:]
        if rest_momentum:
            parts.append(
                _detail_block("".join(_momentum_html(tm) for tm in rest_momentum), label=f"残り{len(rest_momentum)}テーマを表示")
            )
    else:
        parts.append(f"<p>本日算出できるモメンタムスコアがありませんでした（{_esc(NOT_AVAILABLE)}）。</p>")

    parts.append("<h4>Early Signal Detection（初動シグナル）</h4>")
    if bundle.early_signals:
        for es in bundle.early_signals:
            names_txt = "、".join(es.beneficiary_names) if es.beneficiary_names else "該当なし"
            sales_talk_html = f"<br>営業で話すポイント: {_esc(es.sales_talk)}" if es.sales_talk else ""
            parts.append(
                f"<div class='row'><span>{_esc(es.label)} {_esc(es.stars)}</span>"
                f"<span>関連セクター: {_esc(es.related_sector)}</span></div>"
                f"<p style='font-size:0.8rem;color:#666;margin:2px 0 8px 0;'>"
                f"{_esc(es.reason)} ／ 代表的な関連銘柄: {_esc(names_txt)}{sales_talk_html}</p>"
            )
    else:
        parts.append(f"<p>本日該当する初動シグナルはありませんでした（{_esc(NOT_AVAILABLE)}）。</p>")

    parts.append("<h4>世界のお金の流れ（市場シグナルベース）</h4>")
    parts.append(
        "<p class='legend'>実際の資金流入額ではなく、公開市場データとニューステーマから見た"
        "「資金の向かいやすさ」です（機関投資家のポジションや実際の資金フローは取得していません。"
        "断定的な資金フローは表示しません）。</p>"
    )
    if bundle.capital_flow_market_mood:
        parts.append(f"<p style='font-size:0.8rem;color:#666;'>参考情報: {_esc(bundle.capital_flow_market_mood)}</p>")
    for cf in bundle.capital_flow_notes:
        themes_html = f"<br>関連テーマ: {_esc('、'.join(cf.related_themes))}" if cf.related_themes else ""
        sectors_html = f"<br>関連セクター: {_esc('、'.join(cf.related_sectors))}" if cf.related_sectors else ""
        talk_html = f"<br>営業で話すポイント: {_esc(cf.sales_talk)}" if cf.sales_talk else ""
        parts.append(
            f"<div class='row'><span>{_esc(cf.label)}</span><span>{_esc(cf.direction_label)}</span></div>"
            f"<p style='font-size:0.8rem;color:#666;margin:2px 0 8px 0;'>"
            f"{_esc(cf.reason)}{themes_html}{sectors_html}{talk_html}</p>"
        )
    parts.append(_section_nav_html(None, "fi-theme"))
    parts.append("</details>")

    # ② Theme Intelligence（テーマ分析専用）
    parts.append(
        "<details class='fi-block fi-block-theme' id='fi-theme'>"
        f"<summary><h3>🧭 Theme Intelligence {_stars_span('★★★★★')}</h3></summary>"
        "<p class='fi-block-desc'>個別テーマの成熟度・勢い・強み弱みを深掘りするブロックです。</p>"
    )
    parts.append("<h4>テーマ成熟度メモ</h4>")
    parts.append(
        "<p class='legend'>config.yamlへの手動登録があれば「登録情報」として最優先表示、"
        "無ければ既存シグナルからの「AI分析」（断定はしません）、"
        "判断材料が無い場合のみ「分析材料不足」と表示します。</p>"
    )
    # v2.7（④⑤）: 通常表示は「テーマ＋現在フェーズ」の1行のみ。詳細は「詳しく」で展開
    def _maturity_html(tn) -> str:
        basis_html = f"<p style='margin:0;'>判断根拠: {_esc(tn.basis)}</p>" if tn.basis else ""
        detail = (
            f"<p style='margin:0 0 4px 0;'>市場ステージ: {_esc(tn.market_size_note)}</p>"
            f"<p style='margin:0 0 4px 0;'>普及状況: {_esc(tn.adoption_note)}</p>"
            f"<p style='margin:0 0 4px 0;'>競争環境: {_esc(tn.competition_note)} ／ 参入障壁: {_esc(tn.barrier_note)}</p>"
            f"<p style='margin:0 0 4px 0;'>主なリスク: {_esc(tn.risk_note)}</p>" + basis_html
        )
        return (
            f"<div class='row'><span>{_theme_link(tn.label)}［{_esc(tn.source_label)}］</span>"
            f"<span>現在フェーズ: {_esc(tn.market_stage)}</span></div>" + _detail_block(detail)
        )

    parts.extend(_maturity_html(tn) for tn in bundle.theme_maturity_notes[:FI_SUMMARY_COUNT])
    rest_maturity = bundle.theme_maturity_notes[FI_SUMMARY_COUNT:]
    if rest_maturity:
        parts.append(
            _detail_block("".join(_maturity_html(tn) for tn in rest_maturity), label=f"残り{len(rest_maturity)}テーマを表示")
        )

    parts.append("<h4>テーマ別診断（Momentum → Lifecycle → Catalyst → Risk → Confidence）</h4>")
    parts.append(
        "<p class='legend'>投資家が世界の変化をいち早く察知し、長期の資産形成・投資判断に"
        "役立てることを目的とした分析です。CatalystとRiskは既存シグナルのみから導いた"
        "「AI分析」であり、断定はしません。Confidenceは「未来が当たる確率」ではなく、"
        "分析根拠の充実度です。</p>"
    )
    # v2.7（③④⑤）: Confidenceの高い順に上位のみ通常表示し、各テーマは
    # 「1行要約＋詳しく（Catalyst・Risk・根拠・関連テーマ）」で表示する
    diagnosis_ranked = sorted(bundle.theme_diagnosis, key=lambda t: -t.confidence_score)

    def _diagnosis_html(td) -> str:
        catalysts_html = "、".join(_esc(c) for c in td.catalysts)
        risks_html = "、".join(_esc(r) for r in td.risks)
        basis_html = (
            f"<p style='margin:0;'>根拠: {_esc('、'.join(td.confidence_basis))}</p>" if td.confidence_basis else ""
        )
        related_html = (
            f"<p style='margin:0 0 4px 0;'>関連テーマ: {_esc('、'.join(td.related_themes))}</p>" if td.related_themes else ""
        )
        detail = (
            related_html
            + f"<p style='margin:0 0 4px 0;'>Catalyst［AI分析］: {catalysts_html}</p>"
            + f"<p style='margin:0 0 4px 0;'>Risk［AI分析］: {risks_html}</p>"
            + basis_html
        )
        return (
            f"<h5 id='theme-{_esc(_slug(td.label))}'>{_esc(td.label)}{_new_badge(td.confidence_score)}</h5>"
            f"<div class='row'><span>Confidence {td.confidence_score}%</span>"
            f"<span>Momentum {td.momentum_score}/100（{_esc(td.momentum_label)}）／"
            f"{_esc(td.phase)}（継続性: {_esc(td.continuity)}）</span></div>" + _detail_block(detail)
        )

    parts.extend(_diagnosis_html(td) for td in diagnosis_ranked[:FI_SUMMARY_COUNT])
    rest_diagnosis = diagnosis_ranked[FI_SUMMARY_COUNT:]
    if rest_diagnosis:
        parts.append(
            _detail_block("".join(_diagnosis_html(td) for td in rest_diagnosis), label=f"残り{len(rest_diagnosis)}テーマを表示")
        )
    parts.append(_section_nav_html("fi-signals", "fi-industry"))
    parts.append("</details>")

    # ③ Industry Intelligence（業界分析）
    parts.append(
        "<details class='fi-block fi-block-industry' id='fi-industry'>"
        f"<summary><h3>🏭 Industry Intelligence {_stars_span('★★★★☆')}</h3></summary>"
        "<p class='fi-block-desc'>業界単位でどこに追い風が吹いているかを整理するブロックです。</p>"
    )
    parts.append("<h4>次に来る業界（本日のモメンタム順）</h4>")
    if bundle.industry_momentum:
        for e in bundle.industry_momentum:
            parts.append(
                f"<p style='font-size:0.85rem;'>{e.rank}. <strong>{_theme_link(e.label)}</strong>"
                f"（関連見出し{e.headline_count}件）— {_esc(e.reason)}</p>"
            )
    else:
        parts.append(f"<p>本日、モメンタムが確認できるテーマはありませんでした（{_esc(NOT_AVAILABLE)}）。</p>")

    parts.append("<h4>サプライチェーン分析</h4>")
    if bundle.supply_chains:
        parts.append(
            "<ul class='plain'>"
            + "".join(f"<li>{_esc(sc.chain_text)}</li>" for sc in bundle.supply_chains)
            + "</ul>"
        )
    else:
        parts.append(f"<p>本日抽出できるサプライチェーンの連鎖はありませんでした（{_esc(NOT_AVAILABLE)}）。</p>")

    parts.append("<h4>国家戦略メモ</h4>")
    parts.append(
        "<p class='legend'>config.yamlへの手動登録があれば「登録情報」として最優先表示、"
        "無ければ既存シグナルからの「AI分析」（断定はしません）、"
        "判断材料が無い場合のみ「分析材料不足」と表示します。</p>"
    )
    for ns in bundle.national_strategy_notes:
        focus_txt = "、".join(ns.focus_areas) if ns.focus_areas else "分析材料不足"
        basis_html = f"<br>判断根拠: {_esc(ns.basis)}" if ns.basis else ""
        parts.append(
            f"<div class='row'><span>{_esc(ns.region)}［{_esc(ns.source_label)}］</span>"
            f"<span>重点分野: {_esc(focus_txt)}</span></div>"
            f"<p style='font-size:0.8rem;color:#666;margin:2px 0 8px 0;'>"
            f"政策方向: {_esc(ns.policy_note)}<br>"
            f"規制・リスク: {_esc(ns.regulation_note)}<br>"
            f"日本株への波及: {_esc(ns.market_impact_note)}{basis_html}</p>"
        )

    parts.append("<h4>Future Map（テーマ一覧）</h4>")
    parts.append(
        "<ul class='plain'>"
        + "".join(f"<li>{_esc(m.stars)} <strong>{_theme_link(m.label)}</strong>（{_esc(m.phase)}）</li>" for m in bundle.megatrends)
        + "</ul>"
    )
    parts.append(_section_nav_html("fi-theme", "fi-stock"))
    parts.append("</details>")

    # ④ Stock Intelligence（銘柄分析）
    parts.append(
        "<details class='fi-block fi-block-stock' id='fi-stock'>"
        f"<summary><h3>📈 Stock Intelligence {_stars_span('★★★★★')}</h3></summary>"
        "<p class='fi-block-desc'>監視銘柄を1銘柄ごとの投資判断まで落とし込むブロックです。</p>"
    )
    parts.append("<h4>日本株への波及</h4>")
    if bundle.jp_stock_impact:
        for e in bundle.jp_stock_impact:
            parts.append(
                f"<p style='font-size:0.85rem;'><strong>{_theme_link(e.theme)}:</strong> "
                f"{_esc('、'.join(e.beneficiary_names))}（{_esc(e.cap_note)}）</p>"
            )
    else:
        parts.append(f"<p>本日算出できる日本株への波及がありませんでした（{_esc(NOT_AVAILABLE)}）。</p>")

    parts.append("<h4>Watchlist Intelligence（監視銘柄 × テーマ診断）</h4>")
    parts.append(
        "<p class='legend'>config.yamlのwatchlist銘柄と、Future Intelligence Engineのテーマ診断"
        "（Momentum・Lifecycle・Catalyst・Risk・Confidence）を照合した、自分自身の長期の資産形成"
        "・投資判断のための整理です。断定的な売買助言（「買い」「売り」）ではなく、注目継続／"
        "押し目待ち／過熱警戒／材料待ち／判断材料不足という非断定的なラベルのみを使用します。</p>"
    )
    # v2.7（⑩）: 銘柄ごとに「一行要約（銘柄名＋判定ラベル）→詳しく」で表示
    for w in bundle.watchlist_intelligence:
        detail_parts = []
        if w.related_themes:
            catalysts_html = "、".join(_esc(c) for c in w.catalysts)
            risks_html = "、".join(_esc(r) for r in w.risks)
            detail_parts.append(f"<p style='margin:0 0 4px 0;'>関連テーマ: {_esc('、'.join(w.related_themes))}</p>")
            detail_parts.append(
                f"<p style='margin:0 0 4px 0;'>Momentum: {w.momentum_score}/100（{_esc(w.momentum_label)}）／"
                f"Lifecycle: {_esc(w.phase)}（継続性: {_esc(w.continuity)}）／Confidence: {w.confidence_score}%</p>"
            )
            if catalysts_html:
                detail_parts.append(f"<p style='margin:0 0 4px 0;'>Catalyst［AI分析］: {catalysts_html}</p>")
            if risks_html:
                detail_parts.append(f"<p style='margin:0 0 4px 0;'>Risk［AI分析］: {risks_html}</p>")
        detail_parts.append(f"<p style='margin:0;'>判断理由: {_esc(w.judgment_reason)}</p>")
        parts.append(
            f"<div class='row'><span>{_stock_link(w.ticker, f'{w.name}（{w.ticker}）')}</span><span>{_esc(w.judgment_label)}</span></div>"
            + _detail_block("".join(detail_parts))
        )

    parts.append("<h4>Stock Intelligence（銘柄別・投資ストーリー）</h4>")
    parts.append(
        "<p class='legend'>Watchlist Intelligenceで一致した銘柄のみを対象に、Future Intelligence "
        "Engineの分析結果を1銘柄ごとの投資判断まで落とし込みます。目標株価・PER/EPS予想・"
        "「買い」「売り」等の推奨・期待リターンは一切生成しません。「なぜ長期で見るのか」"
        "「今後注目するイベント」「投資ストーリー」は、既存シグナルのみから機械的に組み立てた"
        "ものであり、AIによる作文ではありません。</p>"
    )
    # v2.7（⑩）: 銘柄ごとに「一行要約（銘柄名・判定・Confidence）→詳しく
    # （背景・因果関係・投資ストーリー・リスク・時間軸）」で表示
    for s in bundle.stock_intelligence:
        catalysts_html = "、".join(_esc(c) for c in s.catalysts)
        risks_html = "、".join(_esc(r) for r in s.risks)
        chain_html = (
            f"<p style='margin:0 0 4px 0;'>関連するテーマ: {_esc(' → '.join([s.primary_theme] + s.cross_theme_chain))}</p>"
            if s.cross_theme_chain
            else ""
        )
        detail = (
            f"<p style='margin:0 0 4px 0;'>関連テーマ: {_esc('、'.join(s.related_themes))}（{len(s.related_themes)}件）</p>"
            f"<p style='margin:0 0 4px 0;'>Momentum: {s.momentum_score}/100（{_esc(s.momentum_label)}）／"
            f"Lifecycle: {_esc(s.phase)}（継続性: {_esc(s.continuity)}）</p>"
            f"<p style='margin:0 0 4px 0;'>Catalyst［AI分析］: {catalysts_html}</p>"
            f"<p style='margin:0 0 4px 0;'>Risk［AI分析］: {risks_html}</p>"
            f"<p style='margin:0 0 4px 0;'>なぜ長期で見るのか: {_esc(s.why_long_term)}</p>"
            f"<p style='margin:0 0 4px 0;'>今後注目するイベント: {_esc('、'.join(s.watch_events))}</p>"
            f"{chain_html}"
            f"<p style='margin:0;'>投資ストーリー: {_esc(' → '.join(s.investment_story))}</p>"
        )
        parts.append(
            f"<h5 id='stock-{_esc(_slug(s.ticker))}'>{_esc(s.name)}（{_esc(s.ticker)}）{_new_badge(s.confidence_score)}</h5>"
            f"<div class='row'><span>{_esc(s.judgment_label)}</span>"
            f"<span>Confidence {s.confidence_score}%</span></div>" + _detail_block(detail)
        )
    parts.append(_section_nav_html("fi-industry", "fi-longterm"))
    parts.append("</details>")

    # ⑤ Long-term Strategy（長期戦略）
    parts.append(
        "<details class='fi-block fi-block-longterm' id='fi-longterm'>"
        f"<summary><h3>📅 Long-term Strategy {_stars_span('★★★★☆')}</h3></summary>"
        "<p class='fi-block-desc'>半年〜10年の時間軸で、どのテーマをどの時間軸で見るべきかを整理するブロックです。</p>"
    )
    parts.append("<h4>中長期テーマ</h4>")
    for hg in bundle.horizon_groups:
        themes_txt = "、".join(hg.themes) if hg.themes else "該当なし"
        parts.append(f"<p style='font-size:0.85rem;'><strong>{_esc(hg.horizon)}:</strong> {_esc(themes_txt)}</p>")

    parts.append("<h4>Investment Thesis（テーマ別・長期投資仮説）</h4>")
    parts.append(
        "<p class='legend'>既存シグナル（Theme Momentum・Lifecycle・Catalyst・Risk・"
        "Confidence・causal_rules・theme_relations）のみから機械的に組み立てた長期投資"
        "仮説です。AIによる新たな未来予測・目標株価・売買推奨・期待リターンは一切生成"
        "しません。Confidence（分析根拠の充実度）の高い順に表示します。</p>"
    )
    if bundle.investment_theses:
        # v2.7（⑨）: 各テーマを「結論 → 理由3つ → 詳しく」の3層で表示する
        # （組み立てロジック・Confidence順の並びは不変。表示構成のみ変更）
        def _thesis_html(t) -> str:
            industries_txt = "、".join(t.beneficiary_industries) if t.beneficiary_industries else "分析材料不足"
            names_txt = "、".join(t.beneficiary_names) if t.beneficiary_names else "分析材料不足"
            secondary_txt = "、".join(t.secondary_beneficiary_names) if t.secondary_beneficiary_names else "該当なし"
            less_txt = "、".join(t.less_watched_names) if t.less_watched_names else "該当なし"
            horizons_txt = "・".join(t.horizons) if t.horizons else "分析材料不足"
            conclusion = (
                f"<p style='font-size:0.85rem;margin:2px 0 4px 0;'><span class='imp'>結論</span> "
                f"「{_esc(t.label)}」は{_esc(t.phase or '分析材料不足')}・継続性{_esc(t.continuity or '不明')}のテーマとして、"
                f"{_esc(horizons_txt)}の時間軸で見る仮説です。</p>"
            )
            reasons = (
                "<ul class='plain' style='font-size:0.82rem;'>"
                f"<li>現状: {_esc(t.current_situation)}</li>"
                f"<li>変化［AI分析］: {_esc(t.expected_change)}</li>"
                f"<li>恩恵: {_esc(industries_txt)}（{_esc(names_txt)}）</li>"
                "</ul>"
            )
            detail = (
                f"<p style='margin:0 0 4px 0;'>二次的恩恵企業（関連テーマ経由）: {_esc(secondary_txt)}</p>"
                f"<p style='margin:0 0 4px 0;'>まだ注目されにくい企業（因果チェーン2段階先）: {_esc(less_txt)}</p>"
                f"<p style='margin:0 0 4px 0;'>投資期間: {_esc(horizons_txt)}</p>"
                f"<p style='margin:0 0 4px 0;'>監視指標: {_esc('、'.join(t.watch_indicators))}</p>"
                f"<p style='margin:0 0 4px 0;'>崩れる条件［AI分析］: {_esc('、'.join(t.breakdown_conditions))}</p>"
                f"<p style='margin:0;'>投資仮説まとめ: {_esc(' → '.join(t.thesis_summary))}</p>"
            )
            return (
                f"<h5>{_theme_link(t.label)}{_new_badge(t.confidence_score)}</h5>"
                f"<div class='row'><span>Confidence {t.confidence_score}%</span>"
                f"<span>Momentum {t.momentum_score}/100（{_esc(t.momentum_label)}）</span></div>"
                + conclusion + reasons + _detail_block(detail)
            )

        parts.extend(_thesis_html(t) for t in bundle.investment_theses[:FI_SUMMARY_COUNT])
        rest_theses = bundle.investment_theses[FI_SUMMARY_COUNT:]
        if rest_theses:
            parts.append(
                _detail_block("".join(_thesis_html(t) for t in rest_theses), label=f"残り{len(rest_theses)}テーマを表示")
            )
    else:
        parts.append(f"<p>本日組み立てられる投資仮説がありませんでした（{_esc(NOT_AVAILABLE)}）。</p>")
    parts.append(_section_nav_html("fi-stock", None))
    parts.append("</details>")

    return "".join(parts)


def _generation_status_html(generated_str: str) -> str:
    """「生成状態の説明」（v3.3・改善③）。このページが何であり、再読み込みと
    再生成の違いが何かを、ボタン付近で毎回明示する（表示専用・分析には無関係）。
    """
    return (
        "<div class='generation-status'>"
        f"<p class='refresh-note'>最終生成時刻: {_esc(generated_str)}（このページは最後に生成されたレポートです）</p>"
        "<p class='refresh-note'>「ページを再読み込み」は表示中のHTMLを読み直すだけで、新しいデータは取得しません。"
        "最新ニュース・市場データで再分析するには「最新レポートを生成する」から実行してください。</p>"
        "</div>"
    )


def _mobile_regenerate_steps_html() -> str:
    """「📱 スマホでの実行手順」（v3.3・改善①）。details/summaryで折りたたみ表示する。"""
    steps = (
        "<li>開いた画面でログインする</li>"
        "<li>「Run workflow」をタップする</li>"
        "<li>表示された緑の「Run workflow」ボタンをもう一度タップする</li>"
        "<li>完了まで1〜3分待つ</li>"
        "<li>このページに戻って「ページを再読み込み」をタップする</li>"
    )
    return f"<details class='mobile-steps'><summary>📱 スマホでの実行手順</summary><ol class='plain'>{steps}</ol></details>"


def _one_tap_regenerate_html(endpoint_url: str) -> str:
    """「🚀 ワンタップで最新レポート生成」（v3.4）。realtime.enabled=true かつ
    endpoint_url設定時のみ表示する、Cloudflare Worker等の安全な中継バックエンドを
    叩くボタン。

    ボタンには中継エンドポイントURL（data-endpoint）だけを埋め込む。GitHub Token・
    Secrets・PATの類は一切埋め込まない（認証情報は中継バックエンド側のSecretにのみ
    保管し、HTMLはWorkerのエンドポイントURLを知っているだけ）。押下時の挙動（POST・
    成功/失敗メッセージ・60秒の連打防止）は外部依存のないインラインJS（SCRIPT）側で処理する。
    """
    return (
        f"<button type='button' id='one-tap-btn' class='one-tap-btn' "
        f"data-endpoint='{_esc(endpoint_url)}'>🚀 ワンタップで最新レポート生成</button>"
        "<p class='one-tap-msg' id='one-tap-msg'>"
        "このボタンは中継バックエンド（Cloudflare Worker等）経由でレポート生成を開始します。"
        "GitHubの認証情報（アクセストークン）はこのページに一切含まれていません。</p>"
    )


def _refresh_button_html(actions_url: str = "", realtime: Optional[dict] = None, generated_str: str = "") -> str:
    """「最新表示に更新」導線（v2.9・② Real-Time Update Engine、v3.3で導線を再設計）。

    GitHub Pagesは静的ホスティングのため、ページ内JSだけでmain.pyを実行する
    ことはできない。そのため以下の構成にする。
    ① 「ページを再読み込み」— 常時表示。location.reload()するだけ（外部JS不要）。
    ② 「最新レポートを生成する」— actions_urlが設定されている場合のみリンクとして
      表示（該当workflow実行画面を新しいタブで開くだけ）。未設定時はボタンを消す
      のではなく「設定未完了」の説明を表示する。
    ③ 生成状態の説明（最終生成時刻・再読み込みと再生成の違い）を常時表示。
    ④ 「📱 スマホでの実行手順」を details/summary で常時提供。
    ⑤ realtime.enabled=true かつ endpoint_url 設定時のみ、将来のワンタップ生成枠
      （現状は押せないボタン）を追加表示する。
    いずれの場合も GitHub Token・Secrets・認証情報の類はこのページに一切含めない
    （安全な導線のみ。押した瞬間に自動実行はしない）。
    """
    realtime = realtime or {}
    parts = [
        '<a class="refresh-btn" href="javascript:location.reload()">'
        "🔄 ページを再読み込み</a>"
        '<p class="refresh-note">現在表示中のレポート（最後に自動生成された版）を再読み込みします</p>'
    ]
    if actions_url:
        parts.append(
            f'<a class="regenerate-btn" href="{_esc(actions_url)}" target="_blank" rel="noopener">'
            "⚙️ 最新レポートを生成する</a>"
            '<p class="refresh-note">開いた画面で「Run workflow」を押すと、'
            "その時点の最新ニュース・市場データでレポートが再生成されます。"
            "完了後、このページで「ページを再読み込み」を押すと反映されます。</p>"
        )
    else:
        parts.append(
            "<div class='regenerate-pending'>"
            "⚙️ 最新レポートを生成する（設定未完了）"
            "<p class='refresh-note' style='margin-top:6px;'>config.yaml の output.actions_url が"
            "未設定のため、このページから直接移動できません。設定後に有効になります。</p>"
            "</div>"
        )
    parts.append(_generation_status_html(generated_str))
    parts.append(_mobile_regenerate_steps_html())
    if realtime.get("enabled") and realtime.get("endpoint_url"):
        parts.append(_one_tap_regenerate_html(realtime.get("endpoint_url", "")))
    return "".join(parts)


def _strategic_narrative_html(sn) -> str:
    """「Strategic Narrative Engine」の出力（朝会3分説明レベル）を描画する（v3.5.2）。

    snが未指定なら空文字。既存エンジンの結果だけから機械的に組み立てた解説で、
    断定的な予測・個別の売買推奨は含まない。
    """
    if sn is None:
        return ""

    def _list(items):
        if not items:
            return f"<p class='td-sub'>{_esc(NOT_AVAILABLE)}</p>"
        return "<ul class='plain'>" + "".join(f"<li>{_esc(x)}</li>" for x in items) + "</ul>"

    def _arrow(items):
        if not items:
            return f"<p class='td-sub'>{_esc(NOT_AVAILABLE)}</p>"
        rows = "".join(
            f"<div class='nk-node'>{_esc(x)}</div>" + ("<div class='nk-arrow'>↓</div>" if i < len(items) - 1 else "")
            for i, x in enumerate(items)
        )
        return f"<div class='nk-chain'>{rows}</div>"

    def _factors(items):
        if not items:
            return f"<p class='td-sub'>{_esc(NOT_AVAILABLE)}</p>"
        rows = "".join(
            f"<div class='row'><span>{_stars_span(f.stars)} {_esc(f.label)}</span></div>"
            f"<p class='td-sub'>{_esc(f.note)}</p>" if f.note else
            f"<div class='row'><span>{_stars_span(f.stars)} {_esc(f.label)}</span></div>"
            for f in items
        )
        return rows

    # ② 本日の一言（最重要・箱で強調）
    one_liner = f"<p class='narrative-headline'>【本日の一言】</p><p class='narrative-conclusion'>{_esc(sn.one_liner)}</p>"
    # ③ 今日の市場心理
    psych = f"<p class='td-head'>【今日の市場心理】</p><p class='td-sub'>{_esc(sn.market_psychology)}</p>"
    # ④ 本日の主因ランキング
    ranking_rows = "".join(
        f"<div class='row'><span>{i+1}. {_stars_span(f.stars)} {_esc(f.label)}</span></div>"
        f"<p class='td-sub'>{_esc(f.note)}</p>"
        for i, f in enumerate(sn.driver_ranking)
    ) or f"<p class='td-sub'>{_esc(NOT_AVAILABLE)}</p>"
    ranking = "<p class='td-head'>【本日の主因ランキング】</p>" + ranking_rows
    # ⑤ 押し下げ材料／下支え材料
    factors = (
        "<p class='td-head'>【相場を押し下げた材料】</p>" + _factors(sn.downside_factors)
        + "<p class='td-head'>【下支えした材料】</p>" + _factors(sn.support_factors)
    )
    # ⑥ 今後のシナリオ
    scen_rows = "".join(
        f"<p class='td-head' style='margin-bottom:0;'>{_esc(s.label)}（確率{_esc(s.probability_label)}）</p>"
        + f"<p class='td-sub'>{_esc(' → '.join(s.chain))}</p>"
        for s in sn.scenarios
    ) or f"<p class='td-sub'>{_esc(NOT_AVAILABLE)}</p>"
    scenarios = "<p class='td-head'>【今後のシナリオ】</p>" + scen_rows
    # 改善⑦ 今日覚えること3つ（営業マンが30秒で覚える）
    key_points = ""
    if getattr(sn, "key_points", None):
        key_points = "<p class='td-head'>【今日覚えること（3つ）】</p>" + _list(sn.key_points)
    # ⑩ ストラテジスト総括（箱で強調）
    summary = f"<p class='td-head'>【ストラテジスト総括】</p><p class='strategist-summary'>{_esc(sn.strategist_summary)}</p>"
    # ⑨ 営業向け30秒説明
    sales = f"<p class='td-head'>【営業向け30秒説明】</p><p class='sales-30sec'>{_esc(sn.sales_30sec)}</p>"

    # 詳しく: 織り込んだ流れ（原因の原因まで）・なぜ日経・Cross Market自然文・自己評価・再利用エンジン
    deep = getattr(sn, "deep_causal_chain", None) or sn.causal_chain
    self_html = ""
    if getattr(sn, "self_check", None):
        self_html = (
            f"<p class='td-head'>【分析セルフチェック（自己評価 {getattr(sn, 'self_score', 0)}/100）】</p>"
            + _list(sn.self_check)
            + (("<p class='td-sub'>改善案: " + _esc("／".join(sn.self_improvement)) + "</p>") if getattr(sn, "self_improvement", None) else "")
        )
    detail = (
        "<p class='td-head'>【市場が織り込んだ流れ（原因の原因まで）】</p>" + _arrow(deep)
        + "<p class='td-head'>【なぜ日経平均はこうなったか】</p>" + _arrow(sn.nikkei_causation)
        + "<p class='td-head'>【Cross Market（背景の解説）】</p>"
        + f"<p class='td-sub'>{_esc(sn.cross_market_prose)}</p>"
        + self_html
        + (f"<p class='legend'>再利用した分析エンジン: {_esc('、'.join(sn.reused_engines))}</p>" if sn.reused_engines else "")
    )
    return (
        one_liner + psych + key_points + ranking + factors + scenarios + summary + sales
        + _detail_block(detail, label="市場が織り込んだ流れ・なぜ日経・背景・自己評価を詳しく")
    )


def _market_narrative_html(narrative, strategic=None) -> str:
    """「本日の相場総括（Market Narrative）」カード（v3.5・改善1）。HTML最上部に置く、
    「今日の相場がなぜ動いたか・背景・今後の見方」の深掘り総括。narrativeが未指定なら
    空文字（既存呼び出しに影響しない）。断定・売買助言はせず、条件分岐で見立てを示す。
    """
    if narrative is None and strategic is None:
        return ""

    legend = (
        "<p class='legend'>ニュースと市場データ・既存の各分析エンジンの結果だけを機械的に組み合わせた"
        "「なぜ今日の相場が動いたか」の総括です。生成AIの作文・断定的な将来予測・個別の売買推奨は"
        "行いません。見立ては条件分岐で示します。</p>"
    )

    # v3.5.2: Strategic Narrative Engine の出力（朝会3分説明レベル）を主軸に表示する。
    strat_html = _strategic_narrative_html(strategic)

    six_html = ""
    if narrative is not None:
        def _list(items, cls="plain"):
            if not items:
                return f"<p class='td-sub'>{_esc(NOT_AVAILABLE)}</p>"
            return f"<ul class='{cls}'>" + "".join(f"<li>{_esc(x)}</li>" for x in items) + "</ul>"

        def _chain(items):
            if not items:
                return f"<p class='td-sub'>{_esc(NOT_AVAILABLE)}</p>"
            rows = "".join(
                f"<div class='nk-node'>{_esc(x)}</div>" + ("<div class='nk-arrow'>↓</div>" if i < len(items) - 1 else "")
                for i, x in enumerate(items)
            )
            return f"<div class='nk-chain'>{rows}</div>"

        conclusion = f"<p class='narrative-headline'>① 今日の結論</p><p class='narrative-conclusion'>{_esc(narrative.conclusion or narrative.headline)}</p>"
        nikkei = "<p class='td-head'>② なぜ日経平均は動いたか</p>" + _chain(narrative.nikkei_chain)
        negatives = "<p class='td-head'>③ 悪材料</p>" + _list(narrative.negative_factors)
        supportive = "<p class='td-head'>④ 支えになる材料</p>" + _list(narrative.supportive_factors)
        watch = "<p class='td-head'>⑤ 今後見るべきポイント</p>" + _list(narrative.watch_points)
        views = (
            "<p class='td-head'>⑥ 見立て（条件分岐・断定ではありません）</p>"
            + f"<p class='td-sub'>短期: {_esc(narrative.near_term_view)}</p>"
            + f"<p class='td-sub'>中期: {_esc(narrative.medium_term_view)}</p>"
            + f"<p class='td-sub'>長期: {_esc(narrative.long_term_view)}</p>"
        )
        six_visible = conclusion + nikkei + negatives + supportive + watch + views

        chain_html = ""
        if narrative.cross_market_chain:
            chain_html = "<p class='td-head'>波及チェーン（Cross Market）</p><p class='td-sub'>" + _esc(" → ".join(narrative.cross_market_chain)) + "</p>"
        move_html = (
            "<p class='td-head'>主要指標の変化</p><p class='td-sub'>" + _esc(" ／ ".join(narrative.market_move)) + "</p>"
            if narrative.market_move else ""
        )
        detail_inner = (
            move_html
            + "<p class='td-head'>背景</p>" + _list(narrative.background_factors)
            + chain_html
            + "<p class='td-head'>注意すべきリスク</p>" + _list(narrative.risk_factors)
            + "<p class='td-head'>投資判断への示唆（個別の売買推奨ではありません）</p>" + _list(narrative.implications)
            + (f"<p class='td-sub'>{_esc(narrative.confidence)}</p>" if narrative.confidence else "")
            + (f"<p class='legend'>根拠にした分析: {_esc('、'.join(narrative.source_items))}</p>" if narrative.source_items else "")
        )
        if strategic is not None:
            # Strategic Narrative を主軸にし、6部構成のデータ整理は折りたたみに回す。
            six_html = _detail_block(six_visible + detail_inner, label="データ整理（結論・材料・見立て）を表示")
        else:
            six_html = six_visible + _detail_block(detail_inner, label="主要変化・背景・リスク・示唆を詳しく")

    body = legend + strat_html + six_html
    return _card("📝 本日の相場総括（Market Narrative）", body, extra_class="digest narrative-card", anchor="market-narrative")


def _market_judgment(analysis: AnalysisBundle) -> tuple:
    """今日の市場判断（リスクオン／オフ／中立）を、既存のシナリオ確率のみから
    機械的に判定する（新たな予測は行わない・v3.1・改善1）。戻り値は(ラベル, 一行理由)。
    """
    sc = analysis.scenario
    bull, bear = sc.bull_pct, sc.bear_pct
    mood = analysis.future_intelligence.capital_flow_market_mood
    mood_txt = f"（市場ムード参考: {mood}）" if mood else ""
    if bull - bear >= 15:
        return "リスクオン傾向", f"強気シナリオ{bull}% > 弱気{bear}%{mood_txt}"
    if bear - bull >= 15:
        return "リスクオフ傾向", f"弱気シナリオ{bear}% > 強気{bull}%{mood_txt}"
    return "中立（ニュートラル）", f"強気{bull}%・弱気{bear}%で拮抗{mood_txt}"


def _todays_decision_html(
    market: dict,
    analysis: AnalysisBundle,
    freshness: Optional[DataFreshnessStats],
    anomalies: List[AnomalyEntry],
    translation_st: dict,
) -> str:
    """「Today's Decision」カード（v3.1・改善1）。朝の3分でその日の投資判断を
    掴むためのサマリー。新しい分析は行わず、既に算出済みの各エンジンの
    最上位シグナルを機械的に転記するだけ（各項目1〜2行）。
    """
    fi = analysis.future_intelligence

    # ① 今日の市場判断
    judgment_label, judgment_reason = _market_judgment(analysis)

    # ② 重要テーマTOP3（Theme Momentum Scoreの高い順）
    themes = sorted(fi.theme_momentum, key=lambda t: -t.momentum_score)[:3]
    if themes:
        theme_txt = "、".join(f"{_esc(t.label)}（{t.momentum_score}）" for t in themes)
    else:
        theme_txt = NOT_AVAILABLE

    # ③ 今日見るべき銘柄TOP5（ウォッチリスト→無ければ注目5銘柄）
    watch = (analysis.watchlist_quicklist.get("jp", []) + analysis.watchlist_quicklist.get("us", []))[:5]
    if watch:
        stock_txt = "、".join(f"{_esc(e.quote.name)}" for e in watch)
    else:
        picks = (analysis.top_picks.get("jp", []) + analysis.top_picks.get("us", []))[:5]
        stock_txt = "、".join(f"{_esc(p.quote.name)}" for p in picks) if picks else NOT_AVAILABLE

    # ④ 警戒ポイントTOP3（異常値を最優先→テーマ診断のRisk）
    risks: List[str] = [a.message for a in anomalies]
    for td in sorted(fi.theme_diagnosis, key=lambda t: -t.confidence_score):
        for r in td.risks:
            risks.append(f"{td.label}: {r}")
    risks = risks[:3]
    risk_txt = "".join(f"<li>{_esc(r)}</li>" for r in risks) if risks else f"<li>本日特筆すべき警戒材料は検知していません（{_esc(NOT_AVAILABLE)}）。</li>"

    # ⑤ 今週の重要イベント（直近3件）
    events = analysis.weekly_events[:3]
    if events:
        event_txt = "".join(
            f"<li>{_esc(e.label)}（{_esc(e.countdown_text or e.date_str)}）</li>" for e in events
        )
    else:
        event_txt = f"<li>今週の登録・自動取得イベントはありません（{_esc(NOT_AVAILABLE)}）。</li>"

    # ⑥ AI Confidence（テーマ診断の最大Confidence＝分析根拠の充実度）
    confidences = [td.confidence_score for td in fi.theme_diagnosis]
    conf_txt = f"{max(confidences)}%（分析根拠の充実度。将来の的中確率ではありません）" if confidences else NOT_AVAILABLE

    # ⑦ データ鮮度
    if freshness is not None:
        fresh_txt = f"{_stars_span(freshness_stars(freshness.avg_age_hours))} {_esc(freshness_label(freshness.avg_age_hours))}"
    else:
        fresh_txt = _esc(NOT_AVAILABLE)

    # 翻訳ステータス（改善2の警告もここに小さく出す）
    trans_txt = _esc(_translation_status_text(translation_st))

    rows = (
        f"<div class='row'><span>今日の市場判断</span><span><strong>{_esc(judgment_label)}</strong></span></div>"
        f"<p class='td-sub'>{_esc(judgment_reason)}</p>"
        f"<div class='row'><span>重要テーマTOP3</span><span>{theme_txt}</span></div>"
        f"<div class='row'><span>今日見るべき銘柄TOP5</span><span>{stock_txt}</span></div>"
        f"<div class='row'><span>AI Confidence</span><span>{_esc(conf_txt)}</span></div>"
        f"<div class='row'><span>データ鮮度</span><span>{fresh_txt}</span></div>"
        f"<div class='row'><span>翻訳ステータス</span><span>{trans_txt}</span></div>"
        f"<p class='td-head'>警戒ポイントTOP3</p><ul class='plain'>{risk_txt}</ul>"
        f"<p class='td-head'>今週の重要イベント</p><ul class='plain'>{event_txt}</ul>"
    )
    legend = (
        "<p class='legend'>朝の3分で今日の投資判断を掴むための要約です。各項目は既存の分析エンジンが"
        "算出済みの最上位シグナルを機械的に転記したもので、断定的な売買助言ではありません。"
        "詳細は下の各セクションで確認できます。</p>"
    )
    return _card("🎯 Today's Decision（今日の投資判断・3分サマリー）", legend + rows, extra_class="digest todays-decision", anchor="todays-decision")


def build_html_report(
    report_date: datetime,
    market: dict,
    sources: SourceRegistry,
    analysis: AnalysisBundle,
    actions_url: Optional[str] = None,
    freshness: Optional[DataFreshnessStats] = None,
    rashinban: Optional[RashinbanKnowledge] = None,
    why_today: Optional[Dict[str, str]] = None,
    realtime: Optional[Dict[str, str]] = None,
) -> str:
    """AnalysisBundle から、スマホ閲覧前提のカードUI HTMLを1ファイルで組み立てる。

    freshness（v2.3・省略可）: データ鮮度統計。指定時のみNews Freshnessカードと
    Data Qualityセクションを表示する（未指定でも従来通り動作する）。
    rashinban（v2.6・省略可）: 羅針盤学習ソースの読み込み状況。指定時のみ
    Rashinban Learning Sourceカードを表示する（本文・抜粋は表示しない）。
    why_today（v2.8・省略可）: セクションanchor→「なぜ今日見るべきか」1行の辞書。
    指定時のみ該当カードの先頭にWhy Today行を差し込む（未指定でも従来通り動作）。
    realtime（v3.3導入・v3.4で機能化・省略可）: config.yamlのrealtime設定。
    enabled=trueかつendpoint_url設定時のみ「🚀 ワンタップで最新レポート生成」ボタンを
    表示し、押下でendpoint_url（Cloudflare Worker等の中継バックエンド）へPOSTして
    GitHub Actionsを起動する（未指定・enabled=falseでも従来通り動作。GitHub Token・
    Secretsの類はこのHTML・JSに一切埋め込まず、中継バックエンド側のSecretにのみ保管する）。
    """
    why_today = why_today or {}
    date_str = report_date.strftime("%Y年%m月%d日")
    updated_str = report_date.strftime("%Y-%m-%d %H:%M")
    tz_label = report_date.tzname() or "現地時間"

    # v3.1（改善1/2/3）: 異常値検知・翻訳ステータスを一度だけ算出し、
    # Today's Decision カードと Data Quality の両方で再利用する。
    anomalies = detect_anomalies(market)
    translation_st = _translation_status(analysis)

    top_cards = [
        _refresh_button_html(actions_url or "", realtime=realtime, generated_str=updated_str),
        _menu_grid_html(),
        _market_narrative_html(analysis.market_narrative, getattr(analysis, "strategic_narrative", None)),
        _todays_decision_html(market, analysis, freshness, anomalies, translation_st),
        _dashboard_html(market, analysis, now=report_date),
        _search_card_html(),
        _options_panel_html(),
        _news_freshness_card(freshness),
        _rashinban_card(rashinban),
        _digest_card(market, analysis),
        _card(
            "本レポートについて",
            '<p class="legend">「事実」は公開情報の実データ、「AI分析」はルールベースの機械的な考察です。'
            "生成AIによる断定的な将来予測ではなく、投資助言ではありません。"
            "社外秘資料・有料記事の本文・ログインが必要な情報は使用していません。"
            "データを取得できなかった項目は「取得不可」と明記します。</p>",
        ),
    ]

    # (anchor_id, タイトル, 本文HTML) のリスト。目次カードから各セクションへジャンプできる。
    # v2.1: 「投資家が毎朝見る順番」＝重要度順に再配置（分析ロジック・表示内容は変更なし）。
    sections = [
        ("executive-summary", "AI Executive Summary ★★★★★", _executive_summary_html(analysis.executive_summary, now=report_date)),
        ("weekly-events", "今週の重要イベント・経済指標 ★★★★★", _weekly_events_html(analysis.weekly_events)),
        ("strategist-views", "岡三ストラテジスト視点 ★★★★★", _strategist_views_html(analysis.strategist_views)),
        (
            "future-intelligence",
            "Future Intelligence Engine ★★★★★",
            _todays_action_html(market, analysis) + _future_intelligence_html(analysis.future_intelligence),
        ),
        ("scenarios-v2", "今日の3大シナリオ（期待値順） ★★★★★", _scenarios_v2_html(analysis.scenarios_v2)),
        ("scenario", "今日の相場シナリオ ★★★★☆", None),  # _scenario_card は専用ヘルパーのため下で個別処理
        # v3.5（改善5）: シナリオ系は「今日の3大シナリオ」を主軸とし、個別シナリオは重複を避けて
        # 初期は「詳しく」に折りたたむ（内容・算出は不変・見せ方のみ）。
        (
            "instrument-scenarios",
            "日経平均・ドル円・米国市場 個別シナリオ ★★★★☆",
            "<p class='legend'>「今日の3大シナリオ」と重複しやすいため、個別シナリオは折りたたみ表示です。</p>"
            + _detail_block(_instrument_scenarios_html(analysis.instrument_scenarios), label="個別シナリオを表示"),
        ),
        ("market-impact", "マーケットインパクト ★★★★☆", _market_impact_html(analysis.market_impact)),
        ("sector-strength", "セクターランキング ★★★★☆", _sector_strength_html(analysis.sector_strength)),
        ("causal-chain", "マーケット分析（因果チェーン） ★★★★☆", _causal_chain_html(analysis.causal_chain_text, analysis.causal_chains)),
        ("indices", "主要指標 ★★★★☆", _quote_table_html(market.get("indices", []) + market.get("commodities", []))),
        ("fx-rates", "為替・金利 ★★★★☆", _quote_table_html(market.get("forex", []) + market.get("rates", []))),
        ("news-ranking", "今日の重要ニュースランキング ★★★★☆", _news_ranking_html(analysis.news_ranking, now=report_date)),
        ("key-levels", "今日見るべき指標 ★★★★☆", _key_levels_html(analysis.key_levels)),
        ("themes", "テーマ分析 ★★★★☆", _theme_forecasts_html(analysis.theme_forecasts)),
        ("sector-ranking", "業界ランキング TOP10 ★★★★☆", _sector_ranking_html(analysis.sector_ranking)),
        ("stock-ranking", "個別株ランキング ★★★★☆", _stock_ranking_html(analysis.stock_ranking)),
        ("top-picks", "今日の注目5銘柄 ★★★★☆", _top_picks_html(analysis.top_picks)),
        ("watchlist", "今日のウォッチリスト ★★★★☆", _watchlist_quicklist_html(analysis.watchlist_quicklist)),
        ("long-term-picks", "長期投資アイデア TOP5 ★★★★☆", _long_term_picks_html(analysis.long_term_picks)),
        # v3.5（改善4/9）: ここから下は営業支援用のメモ。投資判断に必須ではないため
        # 「営業メモ」として1グループに集約し、各カードは初期折りたたみ（表示オプションで一括非表示も可）。
        (
            "sales-memo",
            "営業メモ（営業支援・初期折りたたみ） ★★☆☆☆",
            "<p class='legend'>以下は営業支援用のメモ（今日電話すべき顧客／営業準備／営業トーク／"
            "営業向けコメント／岡三証券営業向けコメント／朝会コメント／会話ネタ／想定質問）です。"
            "投資判断そのものには必須ではないため、各カードは初期状態で折りたたんでいます"
            "（表示オプションの「営業セクションを非表示」で一括で隠せます）。</p>",
        ),
        ("call-priorities", "今日電話すべき顧客 ★★★☆☆", _call_priorities_html(analysis.call_priorities)),
        ("sales-prep", "営業準備 ★★★☆☆", _sales_prep_html(analysis.sales_prep)),
        ("sales-talk", "営業トーク ★★★☆☆", _sales_talk_html(analysis.sales_talk_bullets)),
        ("sales-comments", "営業向けコメント ★★★☆☆", _sales_comments_html(analysis.sales_comments)),
        ("okasan-sales-comments", "岡三証券営業向けコメント ★★★☆☆", _okasan_sales_comments_html(analysis.okasan_sales_comments)),
        ("morning-meeting-comment", "朝会コメント ★★★☆☆", _morning_meeting_comment_html(analysis.morning_meeting_comment)),
        (
            "chat-topics",
            "今日の会話ネタ ★★★☆☆",
            "<ul class='plain'>" + "".join(f"<li>{_esc(t)}</li>" for t in analysis.chat_topics) + "</ul>"
            if analysis.chat_topics
            else f"<p>{_esc(NOT_AVAILABLE)}</p>",
        ),
        ("expanded-qa", "想定質問と回答例 ★★★☆☆", _expanded_qa_html(analysis.expanded_qa)),
        ("events", "イベント ★★★☆☆", _events_html(analysis.events)),
        ("ai-summary", "AIまとめ ★★☆☆☆", f"<p>{_esc(analysis.ai_summary_text)}</p>"),
        ("learning-history", "Learning History（AI判断の答え合わせ） ★★★☆☆", _learning_history_html(analysis.learning_history)),
        ("theme-learning", "Theme Confidence Learning（テーマ別勝率） ★★★☆☆", _theme_learning_html(analysis.theme_learning_stats)),
        ("sources", "引用（参照URL一覧） ★★☆☆☆", _source_list_html(sources)),
    ]
    if freshness is not None:
        # v2.3: 引用一覧の下にData Qualityを追加（freshness指定時のみ表示）
        sections.append(
            ("data-quality", "Data Quality ★★☆☆☆", _data_quality_html(freshness, market, analysis, anomalies, translation_st))
        )

    toc_items = "".join(_toc_item_html(anchor, title) for anchor, title, _ in sections)
    toc_card = _card("目次", f"<ul class='toc-list'>{toc_items}</ul>", extra_class="toc no-filter", anchor="toc")

    rendered_sections = []
    for i, (anchor, title, body_html) in enumerate(sections):
        prev_anchor = sections[i - 1][0] if i > 0 else None
        next_anchor = sections[i + 1][0] if i < len(sections) - 1 else None
        nav_html = _section_nav_html(prev_anchor, next_anchor)
        # v2.8（⑦）: 「なぜ今日見るべきか」を該当カードの先頭に差し込む
        why_html = ""
        if why_today.get(anchor):
            why_html = f'<div class="why-today"><strong>Why Today：</strong>{_esc(why_today[anchor])}</div>'
        if anchor == "scenario":
            rendered_sections.append(_scenario_card(analysis.scenario, nav_html=nav_html))
        else:
            # v3.1（改善6）: 営業系セクションは初期状態で折りたたむ（card-collapsed）。
            # 投資判断に必要なセクションを上に、営業メモは畳んで下に置く。
            if anchor in SALES_SECTION_ANCHORS:
                extra_class = "sales-section card-collapsed"
            elif anchor in COLLAPSED_BY_DEFAULT_ANCHORS:
                extra_class = "card-collapsed"
            else:
                extra_class = ""
            rendered_sections.append(
                _card(title, why_html + (body_html or ""), extra_class=extra_class, anchor=anchor, nav_html=nav_html)
            )

    body = "".join(top_cards) + toc_card + "".join(rendered_sections)
    # フローティング操作ボタン（v2.5）: ↑TOP／☰目次／★お気に入り
    back_to_top_html = (
        '<div class="float-nav">'
        '<a href="#toc" class="float-btn" aria-label="目次へ">☰</a>'
        '<a href="#display-options" class="float-btn" aria-label="お気に入り一覧へ">★</a>'
        '<a href="#dashboard-top" class="back-to-top" aria-label="TOPへ戻る">↑<br>TOP</a>'
        "</div>"
    )

    return f"""<!DOCTYPE html>
<html lang="ja">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Market Intelligence System v4 — {_esc(date_str)}</title>
<style>{STYLE}</style>
</head>
<body>
{_sticky_dashboard_html(market)}
<div class="header">
  <h1>Market Intelligence System v4</h1>
  <p>朝レポート {_esc(date_str)}（投資助言ではありません）</p>
  <p class="updated">最終更新: {_esc(updated_str)} ({_esc(tz_label)})</p>
</div>
<div class="container">
{body}
</div>
{back_to_top_html}
<script>{SCRIPT}</script>
</body>
</html>
"""
