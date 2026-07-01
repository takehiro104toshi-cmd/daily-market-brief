"""朝レポート（詳細版）の各セクションをMarkdownにレンダリングする関数群。

builder.py が肥大化しないよう、セクションごとの整形ロジックはすべてここに集約する。
builder.py はここで定義された関数を呼び出して並べるだけの「組み立て役」に徹する。
各関数は AnalysisBundle 内のデータ（既に計算済みの値・文言）を受け取り、
Markdown文字列を返すだけの純粋関数であり、新たな考察ロジックは持たない。
"""
from __future__ import annotations

from typing import Dict, List, Optional

from ..analysis.models import (
    AnalysisBundle,
    EventsBreakdown,
    KeyLevelEntry,
    LongTermPick,
    NewsRankingItem,
    SalesPrep,
    ScenarioForecast,
    SectorRankingEntry,
    StockRankingEntry,
    ThemeForecast,
    WatchlistEntry,
    WatchlistQuickEntry,
)
from ..collectors.news import Headline
from ..utils import SourceRegistry
from .format_utils import (
    NOT_AVAILABLE,
    find_quote,
    first_sentence,
    fmt_change,
    fmt_price,
    headline_list,
    quote_table,
    truncate_to_chars,
)

MOBILE_DIGEST_MAX_CHARS = 300


def render_mobile_digest(market: dict, analysis: AnalysisBundle) -> str:
    """スマホで最初に読む「今日の5分要約」（200〜300文字程度）。

    今日の結論・重要ニュース3件・注目テーマ3つ・見るべき指数・営業一言のみを
    凝縮して表示する（詳細は本文の各セクションを参照）。
    """
    conclusion = first_sentence(analysis.ai_summary_text) or f"主要データが不足しています（{NOT_AVAILABLE}）。"

    news_titles = [item.headline.title for item in analysis.news_ranking[:3]]
    news_line = "／".join(news_titles) if news_titles else "該当なし"

    theme_labels = [tf.label for tf in analysis.theme_forecasts[:3]]
    theme_line = "／".join(theme_labels) if theme_labels else "該当なし"

    key_level_parts = []
    for entry in analysis.key_levels[:3]:
        price_txt = fmt_price(entry.quote.price) if entry.quote else NOT_AVAILABLE
        key_level_parts.append(f"{entry.label}{price_txt}")
    key_level_line = "／".join(key_level_parts) if key_level_parts else "該当なし"

    ceo_line = analysis.sales_prep.ceo_lines[0] if analysis.sales_prep.ceo_lines else "該当なし"

    body = (
        f"■今日の結論: {conclusion}\n"
        f"■重要ニュース3件: {news_line}\n"
        f"■注目テーマ3つ: {theme_line}\n"
        f"■見るべき指数: {key_level_line}\n"
        f"■営業一言: {ceo_line}"
    )
    body = truncate_to_chars(body, MOBILE_DIGEST_MAX_CHARS)

    return "## 📱 今日の5分要約\n\n" + body + "\n"


def render_conclusion(market: dict, scenario: ScenarioForecast) -> str:
    dji = find_quote(market["indices"], "ダウ")
    usdjpy = find_quote(market["forex"], "米ドル/円")
    n225 = find_quote(market["indices"], "日経")

    if dji and dji.change_pct is not None:
        direction = "上昇" if dji.change_pct >= 0 else "下落"
        line1 = f"**米国市場はNYダウが前日比{dji.change_pct:+.2f}%と{direction}。今日の相場は強気{scenario.bull_pct}%・弱気{scenario.bear_pct}%とAIは見立てています。**"
    else:
        line1 = f"**米国市場のデータを取得できませんでした（{NOT_AVAILABLE}）。今日の相場は強気{scenario.bull_pct}%・弱気{scenario.bear_pct}%とAIは見立てています。**"

    if usdjpy and usdjpy.price is not None:
        line2 = f"**為替は米ドル/円{usdjpy.price:.2f}円。金利・為替の動きが日本株の方向感を左右しそうです。**"
    else:
        line2 = f"**為替データを取得できませんでした（{NOT_AVAILABLE}）。**"

    if n225 and n225.price is not None:
        line3 = f"**日経平均の直近値は{fmt_price(n225.price)}円（前日比 {fmt_change(n225.change, n225.change_pct)}）。**"
    else:
        line3 = f"**日経平均のデータを取得できませんでした（{NOT_AVAILABLE}）。**"

    return "\n".join([line1, line2, line3]) + "\n"


def render_scenario(scenario: ScenarioForecast) -> str:
    """強気・中立（普通）・弱気の3シナリオを、確率・注目指標・理由まで表示する。"""
    lines = [
        "| シナリオ | 確率 | 注目指標 |",
        "|---|---|---|",
        f"| 強気 | {scenario.bull_pct}% | {scenario.bull_indicator or NOT_AVAILABLE} |",
        f"| 普通（中立） | {scenario.neutral_pct}% | {scenario.neutral_indicator or NOT_AVAILABLE} |",
        f"| 弱気 | {scenario.bear_pct}% | {scenario.bear_indicator or NOT_AVAILABLE} |",
        "",
        f"> **AI分析（総括）:** {scenario.reasoning}",
        "",
        f"**強気シナリオの理由（AI分析）:** {scenario.bull_reason or NOT_AVAILABLE}",
        "",
        f"**中立シナリオの理由（AI分析）:** {scenario.neutral_reason or NOT_AVAILABLE}",
        "",
        f"**弱気シナリオの理由（AI分析）:** {scenario.bear_reason or NOT_AVAILABLE}",
    ]
    return "\n".join(lines) + "\n"


def render_top_news(news_ranking: List[NewsRankingItem]) -> str:
    """② 今日の重要ニュースランキング: 順位・重要度・理由・影響市場・影響業種まで表示する。"""
    if not news_ranking:
        return f"本日ランキング可能なニュースがありませんでした（{NOT_AVAILABLE}）。\n"
    lines = []
    for item in news_ranking:
        marker = " 🏆AIが本日最重要と判断" if item.is_top_pick else ""
        lines.append(
            f"### {item.rank}位 {item.stars} [{item.headline.title}]({item.headline.link}){marker}"
        )
        lines.append(f"- 出典（事実）: {item.headline.source}")
        lines.append(f"- 理由（AI分析）: {item.reason or NOT_AVAILABLE}")
        lines.append(f"- 影響市場（AI分析）: {item.affected_market or NOT_AVAILABLE}")
        lines.append(f"- 影響業種（AI分析）: {item.affected_sector or NOT_AVAILABLE}")
        lines.append("")
    return "\n".join(lines)


def render_causal_chain(causal_chain_text: str, causal_chains: Optional[List[str]] = None) -> str:
    """マーケット分析: マクロの1本の流れに加え、個別の因果チェーンを3〜5本並べる。"""
    parts = [f"*AI分析・因果関係を矢印で整理*\n\n{causal_chain_text}\n"]
    parts.append("**個別の因果チェーン（AI分析）:**\n")
    if causal_chains:
        for i, chain in enumerate(causal_chains, start=1):
            parts.append(f"チェーン{i}:\n\n{chain}\n")
    else:
        parts.append(f"本日抽出できる個別の因果チェーンはありませんでした（{NOT_AVAILABLE}または該当なし）。\n")
    return "\n".join(parts)


def render_key_levels(key_levels: List[KeyLevelEntry]) -> str:
    """⑤ 今日見るべき指標: 現在値・重要ライン・超えたら何が起きやすいかを一言で表示する。"""
    if not key_levels:
        return f"本日表示できる指標がありませんでした（{NOT_AVAILABLE}）。\n"
    lines = ["| 指標 | 現在値 | 重要ライン | 超えたら（AI分析） |", "|---|---|---|---|"]
    for entry in key_levels:
        price_txt = fmt_price(entry.quote.price) if entry.quote else NOT_AVAILABLE
        line_txt = f"{entry.key_line:g}" if entry.key_line is not None else NOT_AVAILABLE
        lines.append(f"| {entry.label} | {price_txt} | {line_txt} | {entry.note} |")
    return "\n".join(lines) + "\n"


def render_watchlist_quicklist(watchlist_quicklist: Dict[str, List[WatchlistQuickEntry]]) -> str:
    """⑥ 今日のウォッチリスト: 日本株・米国株を★評価＋1行理由でさっと確認できる一覧。"""
    def _render(entries: List[WatchlistQuickEntry]) -> str:
        if not entries:
            return f"データがありません（{NOT_AVAILABLE}）。\n"
        lines = ["| 銘柄 | 評価 | 理由 |", "|---|---|---|"]
        for e in entries:
            lines.append(f"| {e.quote.name}（{e.quote.symbol}） | {e.stars} | {e.reason} |")
        return "\n".join(lines) + "\n"

    parts = ["**日本株:**", "", _render(watchlist_quicklist.get("jp", [])), "**米国株:**", "", _render(watchlist_quicklist.get("us", []))]
    return "\n".join(parts)


def render_sales_prep(sales_prep: SalesPrep) -> str:
    """① 営業準備: 社長向け一言・富裕層向け話題・初心者向け用語解説・今日の雑談・想定質問。"""
    lines = ["### 社長向け一言（30秒で話せる内容）", ""]
    if sales_prep.ceo_lines:
        lines.extend(f"- {line}" for line in sales_prep.ceo_lines)
    else:
        lines.append(f"本日生成できる一言がありませんでした（{NOT_AVAILABLE}）。")
    lines.append("")

    lines.append("### 富裕層向け話題")
    lines.append("")
    if sales_prep.wealthy_topics:
        lines.extend(f"- {topic}" for topic in sales_prep.wealthy_topics)
    else:
        lines.append(f"本日生成できる話題がありませんでした（{NOT_AVAILABLE}）。")
    lines.append("")

    lines.append("### 初心者向け（用語解説）")
    lines.append("")
    if sales_prep.beginner_glossary:
        for item in sales_prep.beginner_glossary:
            lines.append(f"- **{item.term}:** {item.explanation}")
    else:
        lines.append(f"本日生成できる用語解説がありませんでした（{NOT_AVAILABLE}）。")
    lines.append("")

    lines.append("### 今日の雑談（相場以外の公開ニュース）")
    lines.append("")
    if sales_prep.casual_topics:
        lines.extend(f"- {topic}" for topic in sales_prep.casual_topics)
    else:
        lines.append(f"本日生成できる雑談ネタがありませんでした（{NOT_AVAILABLE}）。")
    lines.append("")

    lines.append("### 想定質問")
    lines.append("")
    if sales_prep.qa:
        for item in sales_prep.qa:
            lines.append(f"- **Q. {item.question}**")
            lines.append(f"  A. {item.answer}")
    else:
        lines.append(f"本日生成できる想定質問がありませんでした（{NOT_AVAILABLE}）。")
    lines.append("")
    lines.append("（いずれも事実の紹介・一般的な説明にとどめ、断定的な投資助言は行わないでください。）")

    return "\n".join(lines)


def render_theme_forecasts(theme_forecasts: List[ThemeForecast]) -> str:
    if not theme_forecasts:
        return f"本日抽出できたテーマはありませんでした（{NOT_AVAILABLE}）。\n"
    lines = []
    for tf in theme_forecasts:
        lines.append(f"### 第{tf.rank}位: {tf.label}　{tf.stars}")
        lines.append(f"- **今強い理由（AI分析）:** {tf.why_now}")
        lines.append(f"- **今後1週間（AI分析）:** {tf.outlook_1w}")
        lines.append(f"- **今後1か月（AI分析）:** {tf.outlook_1m}")
        lines.append(f"- **今後3か月（AI分析）:** {tf.outlook_3m}")
        lines.append("")
        lines.append("**関連見出し（事実）:**")
        lines.append(headline_list(tf.headlines, limit=5))
    return "\n".join(lines)


def render_sector_ranking(sector_ranking: List[SectorRankingEntry]) -> str:
    if not sector_ranking:
        return f"本日ランキング可能な業界がありませんでした（{NOT_AVAILABLE}）。\n"
    lines = []
    for entry in sector_ranking:
        lines.append(f"### 第{entry.rank}位: {entry.label}　{entry.stars}")
        lines.append("**追い風（事実）:**")
        lines.append(headline_list(entry.tailwind, limit=3) if entry.tailwind else f"該当なし（{NOT_AVAILABLE}または該当ニュースなし）。\n")
        lines.append("**逆風（事実）:**")
        lines.append(headline_list(entry.headwind, limit=3) if entry.headwind else f"該当なし（{NOT_AVAILABLE}または該当ニュースなし）。\n")
        lines.append("**関連銘柄（事実）:**")
        if entry.related or entry.related_unresolved:
            parts = [f"{q.name}（{fmt_change(q.change, q.change_pct)}）" for q in entry.related]
            parts.extend(f"{t}（{NOT_AVAILABLE}）" for t in entry.related_unresolved)
            lines.append("、".join(parts) + "\n")
        else:
            lines.append("設定されている関連銘柄はありません。\n")
        lines.append(f"**営業トーク（AI分析）:** {entry.sales_talk}\n")
    return "\n".join(lines)


def render_stock_ranking(stock_ranking: Dict[str, List[StockRankingEntry]]) -> str:
    def _render(entries: List[StockRankingEntry]) -> str:
        if not entries:
            return f"本日ランキング可能な銘柄がありませんでした（{NOT_AVAILABLE}）。\n"
        lines = []
        for e in entries:
            lines.append(f"### 第{e.rank}位: {e.quote.name}（{e.quote.symbol}）　{e.stars}")
            lines.append(f"直近値: {fmt_price(e.quote.price)} / 前日比: {fmt_change(e.quote.change, e.quote.change_pct)}（事実）\n")
            lines.append(f"- **短期（AI分析）:** {e.short_term}")
            lines.append(f"- **中期（AI分析）:** {e.mid_term}")
            lines.append(f"- **長期（AI分析）:** {e.long_term}")
            lines.append("")
        return "\n".join(lines)

    parts = ["**日本株TOP10:**", "", _render(stock_ranking.get("jp", [])), "**米国株TOP10:**", "", _render(stock_ranking.get("us", []))]
    return "\n".join(parts)


def render_watchlist_analysis(watchlist_analysis: Dict[str, List[WatchlistEntry]]) -> str:
    def _render(entries: List[WatchlistEntry]) -> str:
        if not entries:
            return f"監視銘柄のデータを取得できませんでした（{NOT_AVAILABLE}）。\n"
        lines = []
        for e in entries:
            lines.append(f"### {e.quote.name}（{e.quote.symbol}）")
            lines.append(f"直近値: {fmt_price(e.quote.price)} / 前日比: {fmt_change(e.quote.change, e.quote.change_pct)}（事実）\n")
            lines.append(f"- **今日の材料（AI分析）:** {e.today}")
            lines.append(f"- **今後1週間（AI分析）:** {e.next_week}")
            lines.append(f"- **今後1か月（AI分析）:** {e.next_month}")
            lines.append(f"- **長期評価（AI分析）:** {e.long_term}")
            lines.append("")
        return "\n".join(lines)

    parts = ["**日本株:**", "", _render(watchlist_analysis.get("jp", [])), "**米国株:**", "", _render(watchlist_analysis.get("us", []))]
    return "\n".join(parts)


def render_long_term_picks(long_term_picks: List[LongTermPick]) -> str:
    if not long_term_picks:
        return f"本日選定可能な長期投資候補がありませんでした（{NOT_AVAILABLE}）。\n"
    lines = [
        "> AIが本日時点の公開情報から機械的に算出した候補です。投資助言ではありません。",
        "",
    ]
    for pick in long_term_picks:
        lines.append(f"### 第{pick.rank}位: {pick.quote.name}（{pick.quote.symbol}）")
        lines.append(f"**理由（AI分析）:** {pick.reasoning}\n")
    return "\n".join(lines)


def render_chat_topics(chat_topics: List[str]) -> str:
    if not chat_topics:
        return f"本日生成できる会話ネタがありませんでした（{NOT_AVAILABLE}）。\n"
    return "\n".join(f"{i}. {topic}" for i, topic in enumerate(chat_topics, start=1)) + "\n"


def render_events(events: EventsBreakdown) -> str:
    def _render(items: List[str], empty_msg: str) -> str:
        if not items:
            return empty_msg + "\n"
        return "\n".join(f"- {item}" for item in items) + "\n"

    parts = [
        "**今日:**",
        "",
        _render(events.today, f"本日確認できるイベントはありません（{NOT_AVAILABLE}または該当なし）。"),
        "**今週:**",
        "",
        _render(events.this_week, "今週確認できるイベントはありません（該当なし）。"),
        "**今月:**",
        "",
        _render(events.this_month, "今月確認できるイベントはありません（該当なし）。"),
    ]
    return "\n".join(parts)


def render_source_list(sources: SourceRegistry) -> str:
    refs = sources.all()
    if not refs:
        return f"記録された出典はありません（{NOT_AVAILABLE}）。\n"
    by_category: Dict[str, list] = {}
    for ref in refs:
        by_category.setdefault(ref.category, []).append(ref)

    lines = []
    for category, items in by_category.items():
        lines.append(f"### {category}")
        for item in items:
            lines.append(f"- [{item.label}]({item.url})")
        lines.append("")
    return "\n".join(lines)
