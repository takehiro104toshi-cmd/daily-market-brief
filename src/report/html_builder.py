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
from datetime import datetime
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
    SalesComments,
    SectorRankingEntry,
    SectorStrengthEntry,
    StockRankingEntry,
    FutureIntelligenceBundle,
    StrategistView,
    ThemeForecast,
    TopPickEntry,
    WatchlistQuickEntry,
)
from ..collectors.market_data import Quote
from ..utils import SourceRegistry
from .format_utils import NOT_AVAILABLE, find_quote, fmt_change_compact, fmt_price

STYLE = """
:root {
  --up: #1a7f37; --up-bg: #e6f4ea;
  --down: #c62828; --down-bg: #fdeaea;
  --flat: #616161; --flat-bg: #eeeeee;
  --card-bg: #ffffff; --page-bg: #f5f6f8; --border: #e0e0e0; --text: #1f2328;
}
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
@media (max-width: 420px) {
  .header h1 { font-size: 1.1rem; }
  .card { padding: 12px; }
}
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


def _card(title: str, body_html: str, extra_class: str = "", anchor: Optional[str] = None) -> str:
    id_attr = f' id="{_esc(anchor)}"' if anchor else ""
    return f'<div class="card {extra_class}"{id_attr}><h2>{_esc(title)}</h2>{body_html}</div>'


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


def _scenario_card(scenario) -> str:
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
    return _card("今日の相場シナリオ", rows + reasons, anchor="scenario")


def _news_ranking_html(items: List[NewsRankingItem]) -> str:
    if not items:
        return f"<p>本日ランキング可能なニュースがありませんでした（{_esc(NOT_AVAILABLE)}）。</p>"
    parts = []
    for item in items:
        marker = " 🏆" if item.is_top_pick else ""
        parts.append(
            f'<div class="row"><span>{item.rank}位{marker} {_esc(item.stars)} '
            f'<a href="{_esc(item.headline.link)}">{_esc(item.headline.title)}</a></span></div>'
            f'<p style="font-size:0.8rem;color:#666;margin:2px 0 8px 0;">'
            f'理由: {_esc(item.reason or NOT_AVAILABLE)} ／ 影響市場: {_esc(item.affected_market or NOT_AVAILABLE)} '
            f"／ 影響業種: {_esc(item.affected_sector or NOT_AVAILABLE)}</p>"
        )
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
    def _render(entries: List[WatchlistQuickEntry]) -> str:
        if not entries:
            return f"<p>データがありません（{_esc(NOT_AVAILABLE)}）。</p>"
        rows = []
        for e in entries:
            cls = _trend_class(e.quote.change_pct)
            rows.append(
                f'<div class="row"><span>{_esc(e.quote.name)}（{_esc(e.quote.symbol)}）</span>'
                f'<span class="badge {cls}">{_esc(e.stars)}</span></div>'
                f'<p style="font-size:0.8rem;color:#666;margin:2px 0 8px 0;">{_esc(e.reason)}</p>'
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


def _dashboard_html(market: dict, analysis: AnalysisBundle) -> str:
    """Today's Dashboard: 重要ニュース3件＋主要指標のカードグリッド（HTML最上部）。"""
    indices = market.get("indices", [])
    forex = market.get("forex", [])
    rates = market.get("rates", [])
    commodities = market.get("commodities", [])

    news_items = analysis.executive_summary[:3] or analysis.news_ranking[:3]
    if news_items:
        news_html = "".join(
            f'<div class="dash-news"><a href="{_esc(item.headline.link)}">{_esc(item.headline.title)}</a></div>'
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
    return _card("Today's Dashboard", body, extra_class="dashboard")


def _executive_summary_html(items: List[ExecutiveSummaryItem]) -> str:
    if not items:
        return f"<p>本日算出できる最重要ニュースがありませんでした（{_esc(NOT_AVAILABLE)}）。</p>"
    parts = []
    for item in items:
        parts.append(
            f"<h3>{item.rank}. {_esc(item.conclusion)} {_esc(item.stars)}</h3>"
            f"<p style='font-size:0.85rem;'>理由: {_esc(item.reason)}</p>"
            f"<p style='font-size:0.82rem;color:#555;'>日本株への影響: {_esc(item.jp_stock_impact)}</p>"
            f"<p style='font-size:0.82rem;color:#555;'>ドル円への影響: {_esc(item.usdjpy_impact)}</p>"
            f"<p style='font-size:0.82rem;color:#555;'>金利への影響: {_esc(item.rate_impact)}</p>"
            f"<p style='font-size:0.82rem;color:#555;'>恩恵銘柄: {_esc(item.beneficiary_stocks or '該当なし')} ／ "
            f"悪影響銘柄: {_esc(item.negative_stocks or '該当なし')}</p>"
            f"<p style='font-size:0.85rem;'><strong>営業トーク:</strong> 「{_esc(item.sales_talk)}」</p>"
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


FI_BLOCK_TOC_HTML = [
    ("fi-signals", "Today's Future Signals", "★★★★★"),
    ("fi-theme", "Theme Intelligence", "★★★★★"),
    ("fi-industry", "Industry Intelligence", "★★★★☆"),
    ("fi-stock", "Stock Intelligence", "★★★★★"),
    ("fi-longterm", "Long-term Strategy", "★★★★☆"),
]


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

    toc_html = "".join(f'<li><a href="#{anchor}">{_esc(title)} {_esc(stars)}</a></li>' for anchor, title, stars in FI_BLOCK_TOC_HTML)
    parts = [
        "<p class='legend'>本セクションは具体的な残り年数・市場規模・補助金額等の断定的な数値は使用せず、"
        "本日の関連ニュース件数と既存の継続性フラグから導いた定性的な考察です。</p>",
        f"<div class='fi-toc'><strong>Future Intelligence 目次</strong><ul>{toc_html}</ul></div>",
    ]

    # ① Today's Future Signals（最重要ブロック・毎朝最初に見る場所）
    parts.append(
        "<div class='fi-block fi-block-signals' id='fi-signals'>"
        "<h3>🌍 Today's Future Signals <span class='fi-stars'>★★★★★</span></h3>"
        "<p class='fi-block-desc'>今日世界で何が変化したかを、3分で最初に把握するブロックです。</p>"
    )
    parts.append("<h4>今日もっとも重要な変化</h4>")
    parts.append(_fi_top_change_highlight_html(bundle))
    parts.append("<h4>世界のメガトレンド</h4>")
    for m in bundle.megatrends:
        parts.append(
            f"<div class='row'><span>{_esc(m.label)} {_esc(m.stars)}</span>"
            f"<span>{_esc(m.phase)} ／ 継続性: {_esc(m.continuity)}</span></div>"
            f"<p style='font-size:0.8rem;color:#666;margin:2px 0 8px 0;'>"
            f"本日の関連見出し: {m.headline_count}件／{_esc(m.why_growing)}</p>"
        )

    parts.append("<h4>Theme Momentum Score</h4>")
    if bundle.theme_momentum:
        for tm in bundle.theme_momentum:
            sector_html = ""
            if tm.related_sector:
                names_txt = "、".join(tm.beneficiary_names) if tm.beneficiary_names else "該当なし"
                sector_html = f"<br>関連セクター: {_esc(tm.related_sector)} ／ 関連銘柄: {_esc(names_txt)}"
            parts.append(
                f"<div class='row'><span>{_esc(tm.label)}</span>"
                f"<span>{tm.momentum_score}/100（{_esc(tm.momentum_label)}）</span></div>"
                f"<p style='font-size:0.8rem;color:#666;margin:2px 0 8px 0;'>{_esc(tm.reason)}{sector_html}</p>"
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
    parts.append("</div>")

    # ② Theme Intelligence（テーマ分析専用）
    parts.append(
        "<div class='fi-block fi-block-theme' id='fi-theme'>"
        "<h3>🧭 Theme Intelligence <span class='fi-stars'>★★★★★</span></h3>"
        "<p class='fi-block-desc'>個別テーマの成熟度・勢い・強み弱みを深掘りするブロックです。</p>"
    )
    parts.append("<h4>テーマ成熟度メモ</h4>")
    parts.append(
        "<p class='legend'>config.yamlへの手動登録があれば「登録情報」として最優先表示、"
        "無ければ既存シグナルからの「AI分析」（断定はしません）、"
        "判断材料が無い場合のみ「分析材料不足」と表示します。</p>"
    )
    for tn in bundle.theme_maturity_notes:
        basis_html = f"<br>判断根拠: {_esc(tn.basis)}" if tn.basis else ""
        parts.append(
            f"<div class='row'><span>{_esc(tn.label)}［{_esc(tn.source_label)}］</span>"
            f"<span>現在フェーズ: {_esc(tn.market_stage)}</span></div>"
            f"<p style='font-size:0.8rem;color:#666;margin:2px 0 8px 0;'>"
            f"市場ステージ: {_esc(tn.market_size_note)}<br>"
            f"普及状況: {_esc(tn.adoption_note)}<br>"
            f"競争環境: {_esc(tn.competition_note)} ／ 参入障壁: {_esc(tn.barrier_note)}<br>"
            f"主なリスク: {_esc(tn.risk_note)}{basis_html}</p>"
        )

    parts.append("<h4>テーマ別診断（Momentum → Lifecycle → Catalyst → Risk → Confidence）</h4>")
    parts.append(
        "<p class='legend'>投資家が世界の変化をいち早く察知し、長期の資産形成・投資判断に"
        "役立てることを目的とした分析です。CatalystとRiskは既存シグナルのみから導いた"
        "「AI分析」であり、断定はしません。Confidenceは「未来が当たる確率」ではなく、"
        "分析根拠の充実度です。</p>"
    )
    for td in bundle.theme_diagnosis:
        catalysts_html = "、".join(_esc(c) for c in td.catalysts)
        risks_html = "、".join(_esc(r) for r in td.risks)
        basis_html = f"<br>根拠: {_esc('、'.join(td.confidence_basis))}" if td.confidence_basis else ""
        related_html = f"<br>関連テーマ: {_esc('、'.join(td.related_themes))}" if td.related_themes else ""
        parts.append(
            f"<h5>{_esc(td.label)}</h5>"
            f"<div class='row'><span>Confidence</span>"
            f"<span>{td.confidence_score}%</span></div>"
            f"<p style='font-size:0.8rem;color:#666;margin:2px 0 8px 0;'>"
            f"Momentum: {td.momentum_score}/100（{_esc(td.momentum_label)}）／"
            f"Lifecycle: {_esc(td.phase)}（継続性: {_esc(td.continuity)}）{related_html}<br>"
            f"Catalyst［AI分析］: {catalysts_html}<br>"
            f"Risk［AI分析］: {risks_html}{basis_html}</p>"
        )
    parts.append("</div>")

    # ③ Industry Intelligence（業界分析）
    parts.append(
        "<div class='fi-block fi-block-industry' id='fi-industry'>"
        "<h3>🏭 Industry Intelligence <span class='fi-stars'>★★★★☆</span></h3>"
        "<p class='fi-block-desc'>業界単位でどこに追い風が吹いているかを整理するブロックです。</p>"
    )
    parts.append("<h4>次に来る業界（本日のモメンタム順）</h4>")
    if bundle.industry_momentum:
        for e in bundle.industry_momentum:
            parts.append(
                f"<p style='font-size:0.85rem;'>{e.rank}. <strong>{_esc(e.label)}</strong>"
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
        + "".join(f"<li>{_esc(m.stars)} <strong>{_esc(m.label)}</strong>（{_esc(m.phase)}）</li>" for m in bundle.megatrends)
        + "</ul>"
    )
    parts.append("</div>")

    # ④ Stock Intelligence（銘柄分析）
    parts.append(
        "<div class='fi-block fi-block-stock' id='fi-stock'>"
        "<h3>📈 Stock Intelligence <span class='fi-stars'>★★★★★</span></h3>"
        "<p class='fi-block-desc'>監視銘柄を1銘柄ごとの投資判断まで落とし込むブロックです。</p>"
    )
    parts.append("<h4>日本株への波及</h4>")
    if bundle.jp_stock_impact:
        for e in bundle.jp_stock_impact:
            parts.append(
                f"<p style='font-size:0.85rem;'><strong>{_esc(e.theme)}:</strong> "
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
    for w in bundle.watchlist_intelligence:
        detail_html = ""
        if w.related_themes:
            catalysts_html = "、".join(_esc(c) for c in w.catalysts)
            risks_html = "、".join(_esc(r) for r in w.risks)
            detail_html = (
                f"関連テーマ: {_esc('、'.join(w.related_themes))}<br>"
                f"Momentum: {w.momentum_score}/100（{_esc(w.momentum_label)}）／"
                f"Lifecycle: {_esc(w.phase)}（継続性: {_esc(w.continuity)}）／"
                f"Confidence: {w.confidence_score}%<br>"
                + (f"Catalyst［AI分析］: {catalysts_html}<br>" if catalysts_html else "")
                + (f"Risk［AI分析］: {risks_html}<br>" if risks_html else "")
            )
        parts.append(
            f"<div class='row'><span>{_esc(w.name)}（{_esc(w.ticker)}）</span><span>{_esc(w.judgment_label)}</span></div>"
            f"<p style='font-size:0.8rem;color:#666;margin:2px 0 8px 0;'>"
            f"{detail_html}判断理由: {_esc(w.judgment_reason)}</p>"
        )

    parts.append("<h4>Stock Intelligence（銘柄別・投資ストーリー）</h4>")
    parts.append(
        "<p class='legend'>Watchlist Intelligenceで一致した銘柄のみを対象に、Future Intelligence "
        "Engineの分析結果を1銘柄ごとの投資判断まで落とし込みます。目標株価・PER/EPS予想・"
        "「買い」「売り」等の推奨・期待リターンは一切生成しません。「なぜ長期で見るのか」"
        "「今後注目するイベント」「投資ストーリー」は、既存シグナルのみから機械的に組み立てた"
        "ものであり、AIによる作文ではありません。</p>"
    )
    for s in bundle.stock_intelligence:
        catalysts_html = "、".join(_esc(c) for c in s.catalysts)
        risks_html = "、".join(_esc(r) for r in s.risks)
        chain_html = (
            f"関連するテーマ: {_esc(' → '.join([s.primary_theme] + s.cross_theme_chain))}<br>"
            if s.cross_theme_chain
            else ""
        )
        parts.append(
            f"<h5>{_esc(s.name)}（{_esc(s.ticker)}）</h5>"
            f"<div class='row'><span>関連テーマ: {_esc('、'.join(s.related_themes))}"
            f"（{len(s.related_themes)}件）</span><span>{_esc(s.judgment_label)}</span></div>"
            f"<p style='font-size:0.8rem;color:#666;margin:2px 0 8px 0;'>"
            f"Momentum: {s.momentum_score}/100（{_esc(s.momentum_label)}）／"
            f"Lifecycle: {_esc(s.phase)}（継続性: {_esc(s.continuity)}）／Confidence: {s.confidence_score}%<br>"
            f"Catalyst［AI分析］: {catalysts_html}<br>"
            f"Risk［AI分析］: {risks_html}<br>"
            f"なぜ長期で見るのか: {_esc(s.why_long_term)}<br>"
            f"今後注目するイベント: {_esc('、'.join(s.watch_events))}<br>"
            f"{chain_html}"
            f"投資ストーリー: {_esc(' → '.join(s.investment_story))}</p>"
        )
    parts.append("</div>")

    # ⑤ Long-term Strategy（長期戦略）
    parts.append(
        "<div class='fi-block fi-block-longterm' id='fi-longterm'>"
        "<h3>📅 Long-term Strategy <span class='fi-stars'>★★★★☆</span></h3>"
        "<p class='fi-block-desc'>半年〜10年の時間軸で、どのテーマをどの時間軸で見るべきかを整理するブロックです。</p>"
    )
    parts.append("<h4>中長期テーマ</h4>")
    for hg in bundle.horizon_groups:
        themes_txt = "、".join(hg.themes) if hg.themes else "該当なし"
        parts.append(f"<p style='font-size:0.85rem;'><strong>{_esc(hg.horizon)}:</strong> {_esc(themes_txt)}</p>")
    parts.append("</div>")

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
) -> str:
    """AnalysisBundle から、スマホ閲覧前提のカードUI HTMLを1ファイルで組み立てる。"""
    date_str = report_date.strftime("%Y年%m月%d日")
    updated_str = report_date.strftime("%Y-%m-%d %H:%M")
    tz_label = report_date.tzname() or "現地時間"

    top_cards = [
        _refresh_button_html(),
        _dashboard_html(market, analysis),
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
        ("executive-summary", "AI Executive Summary ★★★★★", _executive_summary_html(analysis.executive_summary)),
        ("strategist-views", "岡三ストラテジスト視点 ★★★★★", _strategist_views_html(analysis.strategist_views)),
        ("future-intelligence", "Future Intelligence Engine ★★★★★", _future_intelligence_html(analysis.future_intelligence)),
        ("scenario", "今日の相場シナリオ ★★★★☆", None),  # _scenario_card は専用ヘルパーのため下で個別処理
        ("instrument-scenarios", "日経平均・ドル円・米国市場 個別シナリオ ★★★★☆", _instrument_scenarios_html(analysis.instrument_scenarios)),
        ("market-impact", "マーケットインパクト ★★★★☆", _market_impact_html(analysis.market_impact)),
        ("sector-strength", "セクターランキング ★★★★☆", _sector_strength_html(analysis.sector_strength)),
        ("causal-chain", "マーケット分析（因果チェーン） ★★★★☆", _causal_chain_html(analysis.causal_chain_text, analysis.causal_chains)),
        ("indices", "主要指標 ★★★★☆", _quote_table_html(market.get("indices", []) + market.get("commodities", []))),
        ("fx-rates", "為替・金利 ★★★★☆", _quote_table_html(market.get("forex", []) + market.get("rates", []))),
        ("news-ranking", "今日の重要ニュースランキング ★★★★☆", _news_ranking_html(analysis.news_ranking)),
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

    toc_items = "".join(f'<li><a href="#{anchor}">{_esc(title)}</a></li>' for anchor, title, _ in sections)
    toc_card = _card("目次", f"<ul class='toc-list'>{toc_items}</ul>", extra_class="toc")

    rendered_sections = []
    for anchor, title, body_html in sections:
        if anchor == "scenario":
            rendered_sections.append(_scenario_card(analysis.scenario))
        else:
            rendered_sections.append(_card(title, body_html, anchor=anchor))

    body = "".join(top_cards) + toc_card + "".join(rendered_sections)

    return f"""<!DOCTYPE html>
<html lang="ja">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Market Intelligence System v4 — {_esc(date_str)}</title>
<style>{STYLE}</style>
</head>
<body>
<div class="header">
  <h1>Market Intelligence System v4</h1>
  <p>朝レポート {_esc(date_str)}（投資助言ではありません）</p>
  <p class="updated">最終更新: {_esc(updated_str)} ({_esc(tz_label)})</p>
</div>
<div class="container">
{body}
</div>
</body>
</html>
"""
