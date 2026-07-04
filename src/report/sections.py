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
    CallPriorityEntry,
    EventsBreakdown,
    ExecutiveSummaryItem,
    FutureIntelligenceBundle,
    InstrumentScenario,
    KeyLevelEntry,
    LongTermPick,
    MarketImpactEntry,
    MorningMeetingComment,
    NewsRankingItem,
    OkasanSalesComments,
    QAItem,
    SalesComments,
    SalesPrep,
    ScenarioForecast,
    SectorRankingEntry,
    SectorStrengthEntry,
    StockRankingEntry,
    StrategistView,
    ThemeForecast,
    TopPickEntry,
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
    todays_action_items,
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
        lines.append(f"- 営業トーク: 「{item.sales_talk or NOT_AVAILABLE}」")
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


def render_top_picks(top_picks: Dict[str, List[TopPickEntry]]) -> str:
    """朝会でそのまま読み上げられる「今日の注目5銘柄」（日本株5銘柄・米国株5銘柄）。"""
    def _render(entries: List[TopPickEntry]) -> str:
        if not entries:
            return f"本日選定可能な注目銘柄がありませんでした（{NOT_AVAILABLE}）。\n"
        lines = []
        for e in entries:
            lines.append(f"### 第{e.rank}位: {e.quote.name}（{e.quote.symbol}）　{e.stars}")
            lines.append(f"直近値: {fmt_price(e.quote.price)} / 前日比: {fmt_change(e.quote.change, e.quote.change_pct)}（事実）\n")
            lines.append(f"- **理由（AI分析）:** {e.reason}")
            lines.append(f"- **注目材料（AI分析）:** {e.material}")
            lines.append(f"- **短期見通し（AI分析）:** {e.short_term}")
            lines.append("")
        return "\n".join(lines)

    parts = ["**日本株:**", "", _render(top_picks.get("jp", [])), "**米国株:**", "", _render(top_picks.get("us", []))]
    return "\n".join(parts)


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
            lines.append(f"- **リスク（AI分析）:** {e.risk}")
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


def render_sales_comments(comments: SalesComments) -> str:
    """7オーディエンス別の営業向けコメント（各約30秒で話せる長さ）をレンダリングする。"""
    audiences = [
        ("法人社長向け", comments.corporate),
        ("富裕層向け", comments.wealthy),
        ("個人投資家向け", comments.retail),
        ("NISA初心者向け", comments.nisa_beginner),
        ("為替に関心がある顧客向け", comments.fx_interested),
        ("米国株に関心がある顧客向け", comments.us_stock_interested),
        ("日本株に関心がある顧客向け", comments.jp_stock_interested),
    ]
    lines = []
    for label, text in audiences:
        lines.append(f"### {label}")
        lines.append(text if text else f"本日はコメントを生成できませんでした（{NOT_AVAILABLE}）。")
        lines.append("")
    lines.append("（いずれも情報整理を目的としたトーク例であり、断定的な将来予測・投資助言ではありません。）")
    return "\n".join(lines)


def render_expanded_qa(qa_items: List[QAItem]) -> str:
    if not qa_items:
        return f"本日生成できる想定質問がありませんでした（{NOT_AVAILABLE}）。\n"
    lines = []
    for item in qa_items:
        lines.append(f"**Q. {item.question}**")
        lines.append(f"A. {item.answer}")
        lines.append("")
    return "\n".join(lines)


def render_instrument_scenarios(instrument_scenarios: List[InstrumentScenario]) -> str:
    """日経平均・ドル円・米国市場ごとの短いシナリオ見立て（AIシナリオ：強気/中立/弱気）をレンダリングする。"""
    if not instrument_scenarios:
        return f"本日算出できる個別シナリオがありませんでした（{NOT_AVAILABLE}）。\n"
    lines = []
    for s in instrument_scenarios:
        lines.append(f"### {s.label}")
        lines.append(s.outlook)
        lines.append(f"- **注目材料:** {s.key_driver}")
        lines.append(f"- **強気シナリオ:** {s.bull_text or NOT_AVAILABLE}")
        lines.append(f"- **中立シナリオ:** {s.neutral_text or NOT_AVAILABLE}")
        lines.append(f"- **弱気シナリオ:** {s.bear_text or NOT_AVAILABLE}")
        lines.append("")
    return "\n".join(lines)


def render_okasan_sales_comments(comments: OkasanSalesComments) -> str:
    """岡三証券営業向けコメント（富裕層・法人・NISA・退職金・相続の5顧客タイプ）。"""
    audiences = [
        ("富裕層のお客様向け", comments.wealthy),
        ("法人のお客様向け", comments.corporate),
        ("NISAご利用のお客様向け", comments.nisa),
        ("退職金のご相談のお客様向け", comments.retirement),
        ("相続・資産承継のご相談のお客様向け", comments.inheritance),
    ]
    lines = []
    for label, text in audiences:
        lines.append(f"### {label}")
        lines.append(text if text else f"本日はコメントを生成できませんでした（{NOT_AVAILABLE}）。")
        lines.append("")
    lines.append("（いずれも情報整理を目的としたトーク例であり、断定的な将来予測・投資助言ではありません。特定商品の推奨は行いません。）")
    return "\n".join(lines)


def render_executive_summary(items: List[ExecutiveSummaryItem]) -> str:
    """AI Executive Summary（レポート冒頭・今日最重要ニュース最大3件）をレンダリングする。"""
    if not items:
        return f"本日算出できる最重要ニュースがありませんでした（{NOT_AVAILABLE}）。\n"
    lines = []
    for item in items:
        lines.append(f"### {item.rank}. {item.conclusion}　{item.stars}")
        lines.append(f"- **理由（AI分析）:** {item.reason}")
        lines.append(f"- **日本株への影響（AI分析）:** {item.jp_stock_impact}")
        lines.append(f"- **ドル円への影響（AI分析）:** {item.usdjpy_impact}")
        lines.append(f"- **金利への影響（AI分析）:** {item.rate_impact}")
        lines.append(f"- **恩恵銘柄:** {item.beneficiary_stocks or '該当なし'} ／ **悪影響銘柄:** {item.negative_stocks or '該当なし'}")
        lines.append(f"- **営業トーク:** 「{item.sales_talk}」")
        lines.append("")
    return "\n".join(lines)


def render_call_priorities(entries: List[CallPriorityEntry]) -> str:
    """「今日電話すべき顧客」（富裕層/NISA/退職金/法人/相続/若年層）をレンダリングする。"""
    if not entries:
        return f"本日提案可能な顧客タイプがありませんでした（{NOT_AVAILABLE}）。\n"
    lines = []
    for entry in entries:
        lines.append(f"### {entry.customer_type}")
        lines.append(f"- **理由（AI分析）:** {entry.reason}")
        lines.append(f"- **話題（AI分析）:** {entry.topic}")
        lines.append(f"- **営業トーク例:** 「{entry.sales_talk}」")
        lines.append("")
    return "\n".join(lines)


def render_market_impact(entries: List[MarketImpactEntry]) -> str:
    """「マーケットインパクト」（12対象への影響度★・方向）を一覧表示する。"""
    if not entries:
        return f"本日算出できるマーケットインパクトがありませんでした（{NOT_AVAILABLE}）。\n"
    lines = ["| 対象 | 影響度 | 方向 |", "|---|---|---|"]
    for entry in entries:
        lines.append(f"| {entry.target} | {entry.stars} | {entry.direction} |")
    return "\n".join(lines) + "\n"


def render_sector_strength(entries: List[SectorStrengthEntry]) -> str:
    """「セクターランキング」（本日の強弱予測・矢印＋理由）をレンダリングする。"""
    if not entries:
        return f"本日予測可能な業種がありませんでした（{NOT_AVAILABLE}）。\n"
    lines = []
    for entry in entries:
        lines.append(f"- {entry.arrow} **{entry.label}** — {entry.reason}")
    return "\n".join(lines) + "\n"


def render_morning_meeting_comment(comment: MorningMeetingComment) -> str:
    """「朝会コメント」（30秒・1分・3分の3パターン）をレンダリングする。"""
    lines = [
        "### 30秒バージョン",
        comment.short_30s or f"（{NOT_AVAILABLE}）",
        "",
        "### 1分バージョン",
        comment.medium_1min or f"（{NOT_AVAILABLE}）",
        "",
        "### 3分バージョン",
        comment.long_3min or f"（{NOT_AVAILABLE}）",
        "",
    ]
    return "\n".join(lines)


def render_strategist_views(views: List[StrategistView]) -> str:
    """「岡三ストラテジスト視点」をレンダリングする。

    ニュース→岡三ストラテジストならどう見るか→重要テーマ→関連セクター→
    恩恵銘柄→悪影響銘柄→営業で話すポイント→重要度、の順に整理する。
    8軸★スコアの内訳（市場インパクト/継続性/営業利用価値/日本株影響度/
    米国株影響度/個別株へ展開できるか/テーマ株へ展開できるか/
    今後数週間重要か）も明記する。
    """
    if not views:
        return f"本日算出できるストラテジスト視点がありませんでした（{NOT_AVAILABLE}）。\n"
    lines = []
    for i, view in enumerate(views, start=1):
        lines.append(f"### {i}. {view.headline.title}　{view.importance_stars}")
        lines.append(f"- **ニュース:** 「{view.headline.title}」（{view.headline.source}）")
        lines.append(f"- **岡三ストラテジストならどう見るか:** {view.strategist_take}")
        lines.append(f"- **重要テーマ:** {view.theme}")
        lines.append(f"- **関連セクター:** {view.related_sector}")
        lines.append(f"- **恩恵銘柄:** {'、'.join(view.beneficiary_names) if view.beneficiary_names else '該当なし'}")
        lines.append(f"- **悪影響銘柄:** {'、'.join(view.negative_names) if view.negative_names else '該当なし'}")
        lines.append(f"- **営業で話すポイント:** 「{view.sales_point}」")
        if view.score is not None:
            s = view.score
            lines.append(
                "- **重要度内訳（8軸）:** "
                f"市場インパクト{s.market_impact} ／ 継続性{s.continuity} ／ 営業利用価値{s.sales_value} ／ "
                f"日本株影響度{s.jp_impact} ／ 米国株影響度{s.us_impact} ／ "
                f"個別株へ展開できるか{s.stock_expansion} ／ テーマ株へ展開できるか{s.theme_expansion} ／ "
                f"今後数週間重要か{s.weeks_ahead}"
            )
        lines.append("")
    return "\n".join(lines)


def render_todays_action(market: dict, analysis: AnalysisBundle) -> str:
    """「Today's Action」。Future Intelligence Engineの最上部に表示する、
    その日確認すべき事項3〜5件（既存データのみから機械的に生成。新規予測なし）。
    """
    items = todays_action_items(market, analysis)
    if not items:
        return f"本日提示できるToday's Actionがありませんでした（{NOT_AVAILABLE}）。\n\n"
    return "**🎯 Today's Action（今日確認すべきこと）**\n\n" + "\n".join(f"- {i}" for i in items) + "\n\n"


def _fi_top_change_highlight(bundle: FutureIntelligenceBundle) -> str:
    """「今日もっとも重要な変化」。新たな分析は行わず、既に算出済みの
    Theme Momentum Scoreが最も高いテーマの理由をそのまま抜粋するだけの
    機械的なハイライト表示（v2.1）。
    """
    if not bundle.theme_momentum:
        return f"本日算出できる変化のハイライトがありませんでした（{NOT_AVAILABLE}）。"
    top = max(bundle.theme_momentum, key=lambda tm: tm.momentum_score)
    return f"**{top.label}**（Momentum {top.momentum_score}/100・{top.momentum_label}）— {top.reason}"


# Future Intelligence Engine 内の目次（Information Architecture、v2.1）。
# 分析ロジックの変更ではなく、既存の分析結果を「世界→テーマ→業界→銘柄→
# 長期戦略」という投資家の思考順に並べ替えるための表示構成のみを定義する。
FI_BLOCK_TOC = [
    ("Today's Future Signals", "★★★★★"),
    ("Theme Intelligence", "★★★★★"),
    ("Industry Intelligence", "★★★★☆"),
    ("Stock Intelligence", "★★★★★"),
    ("Long-term Strategy", "★★★★☆"),
]


def render_future_intelligence(bundle: FutureIntelligenceBundle) -> str:
    """「Future Intelligence Engine」をレンダリングする（v2.1でInformation
    Architectureを整理）。

    新しい分析ロジックは追加せず、既存の分析結果（世界のメガトレンド／
    Theme Momentum Score／Early Signal Detection／世界のお金の流れ／
    テーマ成熟度メモ／テーマ別診断／次に来る業界／サプライチェーン分析／
    国家戦略メモ／Future Map／日本株への波及／Watchlist Intelligence／
    Stock Intelligence／中長期テーマ）を、「世界→テーマ→業界→銘柄→
    長期戦略」という投資家の思考順に沿って
    Today's Future Signals／Theme Intelligence／Industry Intelligence／
    Stock Intelligence／Long-term Strategy の5ブロックへ整理して表示する。
    具体的な残り年数・市場規模・補助金額・資金流入額・目標株価・
    PER/EPS予想等は生成せず、本日の関連見出し件数・重要ニュースとの一致・
    durable_themes・causal_rules・公開市場データから導いた定性的なラベル、
    または既存シグナルの機械的な組み立て、あるいはconfig.yamlへ手動登録した
    参考情報のそのまま表示のみを行う。
    """
    if not bundle.megatrends:
        return f"本日算出できるテーマがありませんでした（{NOT_AVAILABLE}）。\n"

    lines = [
        "> 本セクションは具体的な残り年数・市場規模・補助金額等の断定的な数値は使用せず、"
        "本日の関連ニュース件数と既存の継続性フラグから導いた定性的な考察です。",
        "",
        "**Future Intelligence 目次**",
    ]
    for name, stars in FI_BLOCK_TOC:
        lines.append(f"- {name} {stars}")
    lines.append("")

    # ① Today's Future Signals ---------------------------------------
    lines.append("### 🌍 Today's Future Signals ★★★★★")
    lines.append("> 今日世界で何が変化したかを、3分で最初に把握するブロックです。")
    lines.append("")

    lines.append("#### 今日もっとも重要な変化")
    lines.append(_fi_top_change_highlight(bundle))
    lines.append("")

    lines.append("#### 世界のメガトレンド")
    for m in bundle.megatrends:
        lines.append(f"- **{m.label}** {m.stars}（フェーズ: {m.phase} ／ 継続性: {m.continuity}）")
        lines.append(f"  本日の関連見出し: {m.headline_count}件／{m.why_growing}")
    lines.append("")

    lines.append("#### Theme Momentum Score")
    if bundle.theme_momentum:
        for tm in bundle.theme_momentum:
            lines.append(f"- **{tm.label}**: {tm.momentum_score}/100（{tm.momentum_label}）— {tm.reason}")
            if tm.related_sector:
                names_txt = "、".join(tm.beneficiary_names) if tm.beneficiary_names else "該当なし"
                lines.append(f"  関連セクター: {tm.related_sector} ／ 関連銘柄: {names_txt}")
    else:
        lines.append(f"本日算出できるモメンタムスコアがありませんでした（{NOT_AVAILABLE}）。")
    lines.append("")

    lines.append("#### Early Signal Detection（初動シグナル）")
    if bundle.early_signals:
        for es in bundle.early_signals:
            names_txt = "、".join(es.beneficiary_names) if es.beneficiary_names else "該当なし"
            lines.append(f"- **{es.label}** {es.stars}（関連セクター: {es.related_sector}）")
            lines.append(f"  {es.reason} ／ 代表的な関連銘柄: {names_txt}")
            if es.sales_talk:
                lines.append(f"  営業で話すポイント: {es.sales_talk}")
    else:
        lines.append(f"本日該当する初動シグナルはありませんでした（{NOT_AVAILABLE}）。")
    lines.append("")

    lines.append("#### 世界のお金の流れ（市場シグナルベース）")
    lines.append(
        "> 実際の資金流入額ではなく、公開市場データとニューステーマから見た「資金の向かいやすさ」です"
        "（機関投資家のポジションや実際の資金フローは取得していません。断定的な資金フローは表示しません）。"
    )
    if bundle.capital_flow_market_mood:
        lines.append(f"参考情報: {bundle.capital_flow_market_mood}")
    for cf in bundle.capital_flow_notes:
        lines.append(f"- **{cf.label}**: {cf.direction_label}")
        lines.append(f"  {cf.reason}")
        if cf.related_themes:
            lines.append(f"  関連テーマ: {'、'.join(cf.related_themes)}")
        if cf.related_sectors:
            lines.append(f"  関連セクター: {'、'.join(cf.related_sectors)}")
        if cf.sales_talk:
            lines.append(f"  営業で話すポイント: {cf.sales_talk}")
    lines.append("")

    # ② Theme Intelligence --------------------------------------------
    lines.append("### 🧭 Theme Intelligence ★★★★★")
    lines.append("> 個別テーマの成熟度・勢い・強み弱みを深掘りするブロックです。")
    lines.append("")

    lines.append("#### テーマ成熟度メモ")
    lines.append(
        "> config.yamlへの手動登録があれば「登録情報」として最優先表示、"
        "無ければ既存シグナルからの「AI分析」（断定はしません）、"
        "判断材料が無い場合のみ「分析材料不足」と表示します。"
    )
    for tn in bundle.theme_maturity_notes:
        lines.append(f"- **{tn.label}**［{tn.source_label}］（現在フェーズ: {tn.market_stage}）")
        lines.append(f"  市場ステージ: {tn.market_size_note}")
        lines.append(f"  普及状況: {tn.adoption_note}")
        lines.append(f"  競争環境: {tn.competition_note} ／ 参入障壁: {tn.barrier_note}")
        lines.append(f"  主なリスク: {tn.risk_note}")
        if tn.basis:
            lines.append(f"  判断根拠: {tn.basis}")
    lines.append("")

    lines.append("#### テーマ別診断（Momentum → Lifecycle → Catalyst → Risk → Confidence）")
    lines.append(
        "> 投資家が世界の変化をいち早く察知し、長期の資産形成・投資判断に役立てることを"
        "目的とした分析です。CatalystとRiskは既存シグナルのみから導いた「AI分析」であり、"
        "断定はしません。Confidenceは「未来が当たる確率」ではなく、分析根拠の充実度です。"
    )
    for td in bundle.theme_diagnosis:
        lines.append(f"##### {td.label}")
        lines.append(f"- Momentum: {td.momentum_score}/100（{td.momentum_label}）")
        lines.append(f"- Lifecycle: {td.phase} ／ 継続性: {td.continuity}")
        if td.related_themes:
            lines.append(f"- 関連テーマ: {'、'.join(td.related_themes)}")
        lines.append(f"- Catalyst［AI分析］: {'／'.join(td.catalysts)}")
        lines.append(f"- Risk［AI分析］: {'／'.join(td.risks)}")
        lines.append(f"- Confidence: {td.confidence_score}%")
        if td.confidence_basis:
            lines.append(f"  根拠: {'、'.join(td.confidence_basis)}")
        lines.append("")

    # ③ Industry Intelligence ------------------------------------------
    lines.append("### 🏭 Industry Intelligence ★★★★☆")
    lines.append("> 業界単位でどこに追い風が吹いているかを整理するブロックです。")
    lines.append("")

    lines.append("#### 次に来る業界（本日のモメンタム順）")
    if bundle.industry_momentum:
        for e in bundle.industry_momentum:
            lines.append(f"{e.rank}. **{e.label}**（関連見出し{e.headline_count}件）— {e.reason}")
    else:
        lines.append(f"本日、モメンタムが確認できるテーマはありませんでした（{NOT_AVAILABLE}）。")
    lines.append("")

    lines.append("#### サプライチェーン分析")
    if bundle.supply_chains:
        for sc in bundle.supply_chains:
            lines.append(f"- {sc.chain_text}")
    else:
        lines.append(f"本日抽出できるサプライチェーンの連鎖はありませんでした（{NOT_AVAILABLE}）。")
    lines.append("")

    lines.append("#### 国家戦略メモ")
    lines.append(
        "> config.yamlへの手動登録があれば「登録情報」として最優先表示、"
        "無ければ既存シグナルからの「AI分析」（断定はしません）、"
        "判断材料が無い場合のみ「分析材料不足」と表示します。"
    )
    for ns in bundle.national_strategy_notes:
        focus_txt = "、".join(ns.focus_areas) if ns.focus_areas else "分析材料不足"
        lines.append(f"- **{ns.region}**［{ns.source_label}］（重点分野: {focus_txt}）")
        lines.append(f"  政策方向: {ns.policy_note}")
        lines.append(f"  規制・リスク: {ns.regulation_note}")
        lines.append(f"  日本株への波及: {ns.market_impact_note}")
        if ns.basis:
            lines.append(f"  判断根拠: {ns.basis}")
    lines.append("")

    lines.append("#### Future Map（テーマ一覧）")
    for m in bundle.megatrends:
        lines.append(f"- {m.stars} **{m.label}**（{m.phase}）")
    lines.append("")

    # ④ Stock Intelligence ----------------------------------------------
    lines.append("### 📈 Stock Intelligence ★★★★★")
    lines.append("> 監視銘柄を1銘柄ごとの投資判断まで落とし込むブロックです。")
    lines.append("")

    lines.append("#### 日本株への波及")
    if bundle.jp_stock_impact:
        for e in bundle.jp_stock_impact:
            lines.append(f"- **{e.theme}:** {'、'.join(e.beneficiary_names)}（{e.cap_note}）")
    else:
        lines.append(f"本日算出できる日本株への波及がありませんでした（{NOT_AVAILABLE}）。")
    lines.append("")

    lines.append("#### Watchlist Intelligence（監視銘柄 × テーマ診断）")
    lines.append(
        "> config.yamlのwatchlist銘柄と、Future Intelligence Engineのテーマ診断"
        "（Momentum・Lifecycle・Catalyst・Risk・Confidence）を照合した、自分自身の"
        "長期の資産形成・投資判断のための整理です。断定的な売買助言（「買い」「売り」）"
        "ではなく、注目継続／押し目待ち／過熱警戒／材料待ち／判断材料不足という"
        "非断定的なラベルのみを使用します。"
    )
    for w in bundle.watchlist_intelligence:
        lines.append(f"- **{w.name}（{w.ticker}）**: {w.judgment_label}")
        if w.related_themes:
            lines.append(f"  関連テーマ: {'、'.join(w.related_themes)}")
            lines.append(f"  Momentum: {w.momentum_score}/100（{w.momentum_label}）／Lifecycle: {w.phase}（継続性: {w.continuity}）／Confidence: {w.confidence_score}%")
            if w.catalysts:
                lines.append(f"  Catalyst［AI分析］: {'／'.join(w.catalysts)}")
            if w.risks:
                lines.append(f"  Risk［AI分析］: {'／'.join(w.risks)}")
        lines.append(f"  判断理由: {w.judgment_reason}")
    lines.append("")

    lines.append("#### Stock Intelligence（銘柄別・投資ストーリー）")
    lines.append(
        "> Watchlist Intelligenceで一致した銘柄のみを対象に、Future Intelligence Engineの"
        "分析結果を1銘柄ごとの投資判断まで落とし込みます。目標株価・PER/EPS予想・"
        "「買い」「売り」等の推奨・期待リターンは一切生成しません。「なぜ長期で見るのか」"
        "「今後注目するイベント」「投資ストーリー」は、既存シグナルのみから機械的に"
        "組み立てたものであり、AIによる作文ではありません。"
    )
    for s in bundle.stock_intelligence:
        lines.append(f"##### {s.name}（{s.ticker}）")
        lines.append(f"- 関連テーマ: {'、'.join(s.related_themes)}（{len(s.related_themes)}件）")
        lines.append(f"- Momentum: {s.momentum_score}/100（{s.momentum_label}）")
        lines.append(f"- Lifecycle: {s.phase} ／ 継続性: {s.continuity}")
        lines.append(f"- Catalyst［AI分析］: {'／'.join(s.catalysts)}")
        lines.append(f"- Risk［AI分析］: {'／'.join(s.risks)}")
        lines.append(f"- Confidence: {s.confidence_score}%")
        lines.append(f"- 現在の判断: {s.judgment_label}")
        lines.append(f"- なぜ長期で見るのか: {s.why_long_term}")
        lines.append(f"- 今後注目するイベント: {'、'.join(s.watch_events)}")
        if s.cross_theme_chain:
            lines.append(f"- 関連するテーマ: {' → '.join([s.primary_theme] + s.cross_theme_chain)}")
        lines.append(f"- 投資ストーリー: {' → '.join(s.investment_story)}")
        lines.append("")

    # ⑤ Long-term Strategy ----------------------------------------------
    lines.append("### 📅 Long-term Strategy ★★★★☆")
    lines.append("> 半年〜10年の時間軸で、どのテーマをどの時間軸で見るべきかを整理するブロックです。")
    lines.append("")

    lines.append("#### 中長期テーマ")
    for hg in bundle.horizon_groups:
        themes_txt = "、".join(hg.themes) if hg.themes else "該当なし"
        lines.append(f"- **{hg.horizon}:** {themes_txt}")
    lines.append("")

    return "\n".join(lines)
