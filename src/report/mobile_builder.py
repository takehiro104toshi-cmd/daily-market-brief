"""スマホ閲覧専用の短縮レポート（output/mobile_market_brief.md）を組み立てる。

PCを開かずスマホだけで「5分で読める」ことを目的とした要約版。
詳細版（latest_market_brief.md）と同じ AnalysisBundle から必要な部分だけを
抜粋するため、収集・分析ロジックの重複は発生しない。
"""
from __future__ import annotations

from datetime import datetime

from ..analysis.models import AnalysisBundle
from .format_utils import NOT_AVAILABLE, first_sentence, fmt_change_compact, fmt_price
from .sections import render_conclusion

TOP_N_THEMES = 3
TOP_N_SECTORS = 3
TOP_N_STOCKS = 5


def _section2_scenario(scenario) -> str:
    reason = first_sentence(scenario.reasoning)
    return (
        f"強気 {scenario.bull_pct}% ／ 中立 {scenario.neutral_pct}% ／ 弱気 {scenario.bear_pct}%\n"
        f"{reason}\n"
    )


def _section3_themes(theme_forecasts: list) -> str:
    if not theme_forecasts:
        return f"本日抽出できたテーマはありませんでした（{NOT_AVAILABLE}）。\n"
    marks = ["①", "②", "③"]
    lines = []
    for i, tf in enumerate(theme_forecasts[:TOP_N_THEMES]):
        mark = marks[i] if i < len(marks) else f"{i + 1}."
        lines.append(f"**{mark}{tf.label}** {tf.stars}")
        lines.append(first_sentence(tf.why_now))
        lines.append(f"1週間: {first_sentence(tf.outlook_1w)}")
        lines.append("")
    return "\n".join(lines)


def _section4_sectors(sector_ranking: list) -> str:
    if not sector_ranking:
        return f"本日ランキング可能な業界がありませんでした（{NOT_AVAILABLE}）。\n"
    marks = ["①", "②", "③"]
    lines = []
    for i, entry in enumerate(sector_ranking[:TOP_N_SECTORS]):
        mark = marks[i] if i < len(marks) else f"{i + 1}."
        lines.append(f"**{mark}{entry.label}** {entry.stars}")
        lines.append(f"追い風{len(entry.tailwind)}件 ／ 逆風{len(entry.headwind)}件")
        lines.append(entry.sales_talk)
        lines.append("")
    return "\n".join(lines)


def _stock_line(entry) -> str:
    q = entry.quote
    return (
        f"**{q.name}（{q.symbol}）** {entry.stars} {fmt_price(q.price)} {fmt_change_compact(q.change_pct)}\n"
        f"{first_sentence(entry.short_term)}\n"
    )


def _section5_watchlist(stock_ranking: dict) -> str:
    jp_entries = stock_ranking.get("jp", [])[:TOP_N_STOCKS]
    us_entries = stock_ranking.get("us", [])[:TOP_N_STOCKS]

    lines = ["**日本株:**", ""]
    if jp_entries:
        for e in jp_entries:
            lines.append(_stock_line(e))
    else:
        lines.append(f"データがありません（{NOT_AVAILABLE}）。\n")

    lines.append("**米国株:**")
    lines.append("")
    if us_entries:
        for e in us_entries:
            lines.append(_stock_line(e))
    else:
        lines.append(f"データがありません（{NOT_AVAILABLE}）。\n")

    return "\n".join(lines)


def _section6_sales_talk(bullets) -> str:
    corp = bullets.corporate[0] if bullets.corporate else f"本日は営業トークを生成できませんでした（{NOT_AVAILABLE}）。"
    retail = bullets.retail[0] if bullets.retail else f"本日は営業トークを生成できませんでした（{NOT_AVAILABLE}）。"
    beginner = bullets.beginner[0] if bullets.beginner else f"本日は営業トークを生成できませんでした（{NOT_AVAILABLE}）。"
    return (
        f"- **法人社長向け:** {corp}\n"
        f"- **個人投資家向け:** {retail}\n"
        f"- **初心者向け:** {beginner}\n"
    )


def build_mobile_report(report_date: datetime, market: dict, analysis: AnalysisBundle) -> str:
    date_str = report_date.strftime("%Y年%m月%d日")
    point = first_sentence(analysis.ai_summary_text) or f"本日は主要データが不足しています（{NOT_AVAILABLE}）。"

    sections = [
        f"# Morning Market Brief Mobile — {date_str}",
        "",
        "> スマホでの閲覧に最適化した短縮版です。詳細は `latest_market_brief.md` をご覧ください。"
        "投資助言ではありません。",
        "",
        "## 1. 今日の結論",
        render_conclusion(market, analysis.scenario),
        "## 2. 今日の相場シナリオ",
        _section2_scenario(analysis.scenario),
        "## 3. 注目テーマ TOP3",
        _section3_themes(analysis.theme_forecasts),
        "## 4. 注目業界 TOP3",
        _section4_sectors(analysis.sector_ranking),
        "## 5. 監視銘柄チェック",
        _section5_watchlist(analysis.stock_ranking),
        "## 6. 今日の営業トーク",
        _section6_sales_talk(analysis.sales_talk_bullets),
        "## 7. 今日の最重要ポイント",
        point + "\n",
    ]
    return "\n".join(sections) + "\n"
