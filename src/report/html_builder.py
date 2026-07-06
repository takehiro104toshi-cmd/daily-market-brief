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
    QAItem,
    RashinbanKnowledge,
    SalesComments,
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
    collapse_btn = '<button type="button" class="collapse-btn" onclick="toggleCard(this)" aria-label="開く/閉じる">▾</button>'
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


NEWS_RANKING_SUMMARY_COUNT = 5  # v2.7（③）: 通常表示は重要5件のみ（残りは「詳しく」内）


def _news_ranking_item_html(item: NewsRankingItem, now: Optional[datetime] = None) -> str:
    """1件分: 要約（順位・★・見出し・鮮度）＋「詳しく」（理由・影響・銘柄・トーク）。"""
    marker = " 🏆" if item.is_top_pick else ""
    detail = (
        f"<p style='margin:0 0 4px 0;'>理由: {_esc(item.reason or NOT_AVAILABLE)}</p>"
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
        f'<a href="{_esc(item.headline.link)}">{_esc(item.headline.title)}</a></span></div>'
        f'<p style="margin:2px 0 0 0;">{_news_freshness_badge(item.headline.published, now)}</p>'
        + _detail_block(detail)
    )


def _news_ranking_html(items: List[NewsRankingItem], now: Optional[datetime] = None) -> str:
    if not items:
        return f"<p>本日ランキング可能なニュースがありませんでした（{_esc(NOT_AVAILABLE)}）。</p>"
    # v2.7（③④⑤）: 情報量より情報密度。通常表示は重要5件＋各件は要約1行、
    # 詳細（理由・影響・恩恵銘柄・営業トーク）は「詳しく」で展開する。
    parts = [_news_ranking_item_html(item, now) for item in items[:NEWS_RANKING_SUMMARY_COUNT]]
    rest = items[NEWS_RANKING_SUMMARY_COUNT:]
    if rest:
        rest_html = "".join(_news_ranking_item_html(item, now) for item in rest)
        parts.append(_detail_block(rest_html, label=f"{NEWS_RANKING_SUMMARY_COUNT + 1}位以下を表示（{len(rest)}件）"))
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
        news_html = "".join(
            f'<div class="dash-news"><a href="{_esc(item.headline.link)}">{_esc(item.headline.title)}</a>'
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
        detail = (
            f"<p style='margin:0 0 4px 0;'>日本株への影響: {_esc(item.jp_stock_impact)}</p>"
            f"<p style='margin:0 0 4px 0;'>ドル円への影響: {_esc(item.usdjpy_impact)}</p>"
            f"<p style='margin:0 0 4px 0;'>金利への影響: {_esc(item.rate_impact)}</p>"
            f"<p style='margin:0 0 4px 0;'>恩恵銘柄: {_esc(item.beneficiary_stocks or '該当なし')} ／ "
            f"悪影響銘柄: {_esc(item.negative_stocks or '該当なし')}</p>"
            f"<p style='margin:0 0 4px 0;'>ストラテジスト視点: {_esc(item.strategist_view)}</p>"
            f"<p style='margin:0;'><strong>営業トーク:</strong> 「{_esc(item.sales_talk)}」</p>"
        )
        parts.append(
            f"<h3>{item.rank}. {_esc(item.conclusion)} {_esc(item.stars)}</h3>"
            f'<p style="margin:0 0 4px 0;">{_news_freshness_badge(item.headline.published, now)}</p>'
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
        "<p class='legend'>config.yamlのmacro_events（登録情報）と決算発表予定（公開情報）から、"
        "今日〜7日後のイベントだけを表示します。重要度・影響対象は人手による対応表との照合で、"
        "AIによる新たな予測ではありません。日本時間基準です。</p>"
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
        detail = (
            f"<p style='margin:0 0 4px 0;'>なぜ重要か: {_esc(e.why_important)}</p>"
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


def _source_list_html(sources: SourceRegistry) -> str:
    refs = sources.all()
    if not refs:
        return f"<p>記録された出典はありません（{_esc(NOT_AVAILABLE)}）。</p>"
    by_category: dict = {}
    for ref in refs:
        by_category.setdefault(ref.category, []).append(ref)
    parts = []
    for category, items in by_category.items():
        links = "".join(f'<li><a href="{_esc(item.url)}">{_esc(item.label)}</a></li>' for item in items)
        parts.append(f"<h3>{_esc(category)}</h3><ul class='plain'>{links}</ul>")
    return "".join(parts)


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
    return _card("News Freshness（データ鮮度）", rows_html + eval_html, extra_class="digest", anchor="news-freshness")


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


def _data_quality_html(freshness: Optional[DataFreshnessStats], market: dict, analysis: AnalysisBundle) -> str:
    """「Data Quality」セクション（v2.3）。今日のレポートが最新データに基づくかを
    一目で確認するための機械的な可用性・鮮度指標（分析ロジックには不関与）。
    """
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
    ]
    if freshness is not None:
        tz = freshness.generated_at.tzinfo
        avg_txt = f"{freshness.avg_age_hours:.0f}時間" if freshness.avg_age_hours is not None else NOT_AVAILABLE
        rows.extend(
            [
                ("更新日時", _esc(freshness.generated_at.strftime("%H:%M %Z").strip())),
                ("最新ニュース", _esc(_fmt_stats_dt(freshness.newest_published, tz))),
                ("平均鮮度", _esc(avg_txt)),
                ("情報源", _esc(f"{len(freshness.source_health)}")),
                ("ランキング対象", _esc(f"{freshness.deduped_total}件")),
            ]
        )
    rows_html = "".join(f"<div class='row'><span>{_esc(k)}</span><span>{v}</span></div>" for k, v in rows)
    legend = (
        "<p class='legend'>本日のレポートが最新データに基づいているかを確認するための"
        "機械的な指標です（取得できた項目の割合と記事の経過時間から算出。分析内容の評価ではありません）。</p>"
    )
    return legend + rows_html


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


def _refresh_button_html() -> str:
    """「最新表示に更新」ボタン。ページを再読み込みするだけの単純なボタン。

    毎朝のGitHub Actions自動生成・自動デプロイを基本運用とし、GitHub Actionsの
    実行画面へは遷移しない（外部JS不要・HTML内で完結するjavascript:スキーム）。
    常時表示する。
    """
    return (
        '<a class="refresh-btn" href="javascript:location.reload()">'
        "🔄 最新表示に更新</a>"
        '<p class="refresh-note">最新の自動生成済みレポートを再読み込みします</p>'
    )


def build_html_report(
    report_date: datetime,
    market: dict,
    sources: SourceRegistry,
    analysis: AnalysisBundle,
    actions_url: Optional[str] = None,
    freshness: Optional[DataFreshnessStats] = None,
    rashinban: Optional[RashinbanKnowledge] = None,
) -> str:
    """AnalysisBundle から、スマホ閲覧前提のカードUI HTMLを1ファイルで組み立てる。

    freshness（v2.3・省略可）: データ鮮度統計。指定時のみNews Freshnessカードと
    Data Qualityセクションを表示する（未指定でも従来通り動作する）。
    rashinban（v2.6・省略可）: 羅針盤学習ソースの読み込み状況。指定時のみ
    Rashinban Learning Sourceカードを表示する（本文・抜粋は表示しない）。
    """
    date_str = report_date.strftime("%Y年%m月%d日")
    updated_str = report_date.strftime("%Y-%m-%d %H:%M")
    tz_label = report_date.tzname() or "現地時間"

    top_cards = [
        _refresh_button_html(),
        _menu_grid_html(),
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
        ("scenario", "今日の相場シナリオ ★★★★☆", None),  # _scenario_card は専用ヘルパーのため下で個別処理
        ("instrument-scenarios", "日経平均・ドル円・米国市場 個別シナリオ ★★★★☆", _instrument_scenarios_html(analysis.instrument_scenarios)),
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
        ("sources", "引用（参照URL一覧） ★★☆☆☆", _source_list_html(sources)),
    ]
    if freshness is not None:
        # v2.3: 引用一覧の下にData Qualityを追加（freshness指定時のみ表示）
        sections.append(("data-quality", "Data Quality ★★☆☆☆", _data_quality_html(freshness, market, analysis)))

    toc_items = "".join(_toc_item_html(anchor, title) for anchor, title, _ in sections)
    toc_card = _card("目次", f"<ul class='toc-list'>{toc_items}</ul>", extra_class="toc no-filter", anchor="toc")

    rendered_sections = []
    for i, (anchor, title, body_html) in enumerate(sections):
        prev_anchor = sections[i - 1][0] if i > 0 else None
        next_anchor = sections[i + 1][0] if i < len(sections) - 1 else None
        nav_html = _section_nav_html(prev_anchor, next_anchor)
        if anchor == "scenario":
            rendered_sections.append(_scenario_card(analysis.scenario, nav_html=nav_html))
        else:
            extra_class = "sales-section" if anchor in SALES_SECTION_ANCHORS else ""
            rendered_sections.append(_card(title, body_html, extra_class=extra_class, anchor=anchor, nav_html=nav_html))

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
