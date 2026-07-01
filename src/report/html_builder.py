"""Market Intelligence System v2 の朝レポートを、スマホ閲覧前提のHTML（カードUI）で組み立てる。

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
    KeyLevelEntry,
    NewsRankingItem,
    SectorRankingEntry,
    StockRankingEntry,
    ThemeForecast,
    WatchlistQuickEntry,
)
from ..collectors.market_data import Quote
from ..utils import SourceRegistry
from .format_utils import NOT_AVAILABLE, fmt_change_compact, fmt_price

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
}
.card h2 { font-size: 1.05rem; margin: 0 0 10px 0; }
.card h3 { font-size: 0.95rem; margin: 10px 0 6px 0; }
.badge { display: inline-block; padding: 2px 8px; border-radius: 999px; font-size: 0.78rem; font-weight: 600; }
.up { color: var(--up); background: var(--up-bg); }
.down { color: var(--down); background: var(--down-bg); }
.flat { color: var(--flat); background: var(--flat-bg); }
table { width: 100%; border-collapse: collapse; font-size: 0.85rem; }
table th, table td { text-align: left; padding: 6px 4px; border-bottom: 1px solid var(--border); }
table th { color: #666; font-weight: 600; font-size: 0.78rem; }
.row { display: flex; justify-content: space-between; align-items: center; padding: 6px 0; border-bottom: 1px solid var(--border); font-size: 0.9rem; }
.row:last-child { border-bottom: none; }
.legend { font-size: 0.8rem; color: #555; background: #fffbe6; border: 1px solid #f0e2a4; border-radius: 8px; padding: 10px 12px; }
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


def _card(title: str, body_html: str, extra_class: str = "") -> str:
    return f'<div class="card {extra_class}"><h2>{_esc(title)}</h2>{body_html}</div>'


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
    return _card("今日の相場シナリオ", rows + reasons)


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


def build_html_report(report_date: datetime, market: dict, sources: SourceRegistry, analysis: AnalysisBundle) -> str:
    """AnalysisBundle から、スマホ閲覧前提のカードUI HTMLを1ファイルで組み立てる。"""
    date_str = report_date.strftime("%Y年%m月%d日")

    cards = [
        _digest_card(market, analysis),
        _card(
            "本レポートについて",
            '<p class="legend">「事実」は公開情報の実データ、「AI分析」はルールベースの機械的な考察です。'
            "生成AIによる断定的な将来予測ではなく、投資助言ではありません。"
            "社外秘資料・有料記事の本文・ログインが必要な情報は使用していません。"
            "データを取得できなかった項目は「取得不可」と明記します。</p>",
        ),
        _card("主要指標", _quote_table_html(market.get("indices", []) + market.get("commodities", []))),
        _card("為替・金利", _quote_table_html(market.get("forex", []) + market.get("rates", []))),
        _scenario_card(analysis.scenario),
        _card("今日の重要ニュースランキング", _news_ranking_html(analysis.news_ranking)),
        _card("今日見るべき指標", _key_levels_html(analysis.key_levels)),
        _card("マーケット分析（因果チェーン）", _causal_chain_html(analysis.causal_chain_text, analysis.causal_chains)),
        _card("テーマ分析", _theme_forecasts_html(analysis.theme_forecasts)),
        _card("業界ランキング TOP10", _sector_ranking_html(analysis.sector_ranking)),
        _card("個別株ランキング", _stock_ranking_html(analysis.stock_ranking)),
        _card("今日のウォッチリスト", _watchlist_quicklist_html(analysis.watchlist_quicklist)),
        _card("長期投資アイデア TOP5", _long_term_picks_html(analysis.long_term_picks)),
        _card("営業準備", _sales_prep_html(analysis.sales_prep)),
        _card("営業トーク", _sales_talk_html(analysis.sales_talk_bullets)),
        _card("今日の会話ネタ", "<ul class='plain'>" + "".join(f"<li>{_esc(t)}</li>" for t in analysis.chat_topics) + "</ul>" if analysis.chat_topics else f"<p>{_esc(NOT_AVAILABLE)}</p>"),
        _card("イベント", _events_html(analysis.events)),
        _card("AIまとめ", f"<p>{_esc(analysis.ai_summary_text)}</p>"),
        _card("引用（参照URL一覧）", _source_list_html(sources)),
    ]

    body = "".join(cards)

    return f"""<!DOCTYPE html>
<html lang="ja">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Market Intelligence System v2 — {_esc(date_str)}</title>
<style>{STYLE}</style>
</head>
<body>
<div class="header">
  <h1>Market Intelligence System v2</h1>
  <p>朝レポート {_esc(date_str)}（投資助言ではありません）</p>
</div>
<div class="container">
{body}
</div>
</body>
</html>
"""
