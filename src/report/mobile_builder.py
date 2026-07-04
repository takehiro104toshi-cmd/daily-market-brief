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


TOP_N_STRATEGIST_VIEWS = 2


def _section_strategist_views(views: list) -> str:
    if not views:
        return f"本日算出できるストラテジスト視点がありませんでした（{NOT_AVAILABLE}）。\n"
    lines = []
    for view in views[:TOP_N_STRATEGIST_VIEWS]:
        lines.append(f"**{view.headline.title}** {view.importance_stars}")
        lines.append(first_sentence(view.strategist_take))
        beneficiary = "、".join(view.beneficiary_names) if view.beneficiary_names else "該当なし"
        negative = "、".join(view.negative_names) if view.negative_names else "該当なし"
        lines.append(f"恩恵: {beneficiary} ／ 悪影響: {negative}")
        lines.append("")
    return "\n".join(lines)


TOP_N_MEGATRENDS = 3

FI_BLOCK_TOC = [
    ("Today's Future Signals", "★★★★★"),
    ("Theme Intelligence", "★★★★★"),
    ("Industry Intelligence", "★★★★☆"),
    ("Stock Intelligence", "★★★★★"),
    ("Long-term Strategy", "★★★★☆"),
]


def _fi_top_change_highlight(bundle) -> str:
    """「今日もっとも重要な変化」。新たな分析は行わず、既に算出済みの
    Theme Momentum Scoreが最も高いテーマの理由をそのまま抜粋するだけの
    機械的なハイライト表示（v2.1）。
    """
    if not bundle.theme_momentum:
        return f"本日算出できる変化のハイライトがありませんでした（{NOT_AVAILABLE}）。"
    top = max(bundle.theme_momentum, key=lambda tm: tm.momentum_score)
    return f"**{top.label}**（Momentum {top.momentum_score}/100・{top.momentum_label}）— {first_sentence(top.reason)}"


def _section_future_intelligence(bundle) -> str:
    """Future Intelligence Engineのモバイル短縮表示。

    v2.1: 既存項目の分析ロジック・データは変更せず、「世界→テーマ→業界→銘柄→
    長期戦略」の5ブロック（Information Architecture）へ再構成して表示する。
    折りたたみは使わず、見出し（###）を大きくしてスクロールで読める形にする。
    """
    if not bundle.megatrends:
        return f"本日算出できるテーマがありませんでした（{NOT_AVAILABLE}）。\n"
    ranked = sorted(bundle.megatrends, key=lambda m: m.headline_count, reverse=True)

    lines = ["**Future Intelligence 目次**"]
    for i, (name, stars) in enumerate(FI_BLOCK_TOC):
        prefix = "└" if i == len(FI_BLOCK_TOC) - 1 else "├"
        lines.append(f"{prefix} {name} {stars}")
    lines.append("")

    # ① Today's Future Signals（最重要ブロック・毎朝最初に見る場所）
    lines.append("### 🌍 Today's Future Signals ★★★★★")
    lines.append("今日世界で何が変化したかを、3分で最初に把握するブロックです。")
    lines.append("")
    lines.append(f"今日もっとも重要な変化: {_fi_top_change_highlight(bundle)}")
    for m in ranked[:TOP_N_MEGATRENDS]:
        lines.append(f"**{m.label}** {m.stars}（{m.phase} ／ 継続性: {m.continuity}）")
    if bundle.theme_momentum:
        top_momentum = max(bundle.theme_momentum, key=lambda tm: tm.momentum_score)
        momentum_line = f"Momentum Score上位: {top_momentum.label} {top_momentum.momentum_score}/100（{top_momentum.momentum_label}）"
        if top_momentum.related_sector:
            momentum_line += f"／関連セクター: {top_momentum.related_sector}"
        lines.append(momentum_line)
    if bundle.early_signals:
        top_signal = bundle.early_signals[0]
        lines.append(f"初動シグナル: {'、'.join(es.label for es in bundle.early_signals)}")
        if top_signal.sales_talk:
            lines.append(f"営業トーク例（{top_signal.label}）: {first_sentence(top_signal.sales_talk)}")
    if bundle.capital_flow_notes:
        flow_txt = "／".join(f"{cf.label}:{cf.direction_label}" for cf in bundle.capital_flow_notes)
        lines.append(f"世界のお金の流れ（市場シグナルベース、実際の資金流入額は未取得）: {flow_txt}")
    lines.append("")

    # ② Theme Intelligence（テーマ分析専用）
    lines.append("### 🧭 Theme Intelligence ★★★★★")
    lines.append("個別テーマの成熟度・勢い・強み弱みを深掘りするブロックです。")
    lines.append("")
    available_maturity = [tn for tn in bundle.theme_maturity_notes if tn.source_label != "分析材料不足"]
    if available_maturity:
        top_maturity = available_maturity[0]
        lines.append(f"テーマ成熟度メモ［{top_maturity.source_label}］: {top_maturity.label}（{top_maturity.market_stage}）")
    else:
        lines.append(f"テーマ成熟度メモ: 分析材料不足（{NOT_AVAILABLE}）")
    if bundle.theme_diagnosis:
        top_diagnosis = max(bundle.theme_diagnosis, key=lambda td: td.confidence_score)
        catalyst_txt = top_diagnosis.catalysts[0] if top_diagnosis.catalysts else NOT_AVAILABLE
        risk_txt = top_diagnosis.risks[0] if top_diagnosis.risks else NOT_AVAILABLE
        related_txt = f"／関連テーマ: {'、'.join(top_diagnosis.related_themes)}" if top_diagnosis.related_themes else ""
        lines.append(
            f"テーマ別診断（Confidence上位）: {top_diagnosis.label}"
            f"（Momentum {top_diagnosis.momentum_score}/100・{top_diagnosis.phase}・"
            f"Confidence {top_diagnosis.confidence_score}%）{related_txt}"
        )
        lines.append(f"Catalyst［AI分析］: {catalyst_txt} ／ Risk［AI分析］: {risk_txt}")
    lines.append("")

    # ③ Industry Intelligence（業界分析）
    lines.append("### 🏭 Industry Intelligence ★★★★☆")
    lines.append("業界単位でどこに追い風が吹いているかを整理するブロックです。")
    lines.append("")
    if bundle.industry_momentum:
        top = bundle.industry_momentum[0]
        lines.append(f"注目業界: {top.label}（関連見出し{top.headline_count}件）")
    available_strategy = [ns for ns in bundle.national_strategy_notes if ns.source_label != "分析材料不足"]
    if available_strategy:
        top_strategy = available_strategy[0]
        lines.append(f"国家戦略メモ［{top_strategy.source_label}］: {top_strategy.region}（{first_sentence(top_strategy.policy_note)}）")
    else:
        lines.append(f"国家戦略メモ: 分析材料不足（{NOT_AVAILABLE}）")
    lines.append("")

    # ④ Stock Intelligence（銘柄分析）
    lines.append("### 📈 Stock Intelligence ★★★★★")
    lines.append("監視銘柄を1銘柄ごとの投資判断まで落とし込むブロックです。")
    lines.append("")
    matched_watchlist = [w for w in bundle.watchlist_intelligence if w.related_themes]
    if matched_watchlist:
        top_watch = max(matched_watchlist, key=lambda w: w.confidence_score)
        lines.append(
            f"Watchlist Intelligence（監視銘柄×テーマ診断）: {top_watch.name}（{top_watch.ticker}）"
            f"は「{top_watch.judgment_label}」（断定的な売買判断ではありません）"
        )
    elif bundle.watchlist_intelligence:
        lines.append("Watchlist Intelligence: 本日一致するテーマ診断のある監視銘柄はありませんでした（判断材料不足）")
    if bundle.stock_intelligence:
        top_stock = max(bundle.stock_intelligence, key=lambda s: s.confidence_score)
        lines.append(
            f"Stock Intelligence（{top_stock.name}／{top_stock.ticker}）: "
            f"関連テーマ{len(top_stock.related_themes)}件・現在の判断「{top_stock.judgment_label}」"
        )
        lines.append(f"投資ストーリー: {' → '.join(top_stock.investment_story)}")
    lines.append("")

    # ⑤ Long-term Strategy（長期戦略）
    lines.append("### 📅 Long-term Strategy ★★★★☆")
    lines.append("半年〜10年の時間軸で、どのテーマをどの時間軸で見るべきかを整理するブロックです。")
    lines.append("")
    if bundle.horizon_groups:
        for hg in bundle.horizon_groups:
            themes_txt = "、".join(hg.themes) if hg.themes else "該当なし"
            lines.append(f"{hg.horizon}: {themes_txt}")
    else:
        lines.append(f"長期戦略の分析材料がありませんでした（{NOT_AVAILABLE}）。")

    return "\n".join(lines) + "\n"


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

    # v2.1: 「投資家が毎朝見る順番」＝重要度順に再配置（分析ロジック・表示内容は変更なし）。
    sections = [
        f"# Morning Market Brief Mobile — {date_str}",
        "",
        "> スマホでの閲覧に最適化した短縮版です。詳細は `latest_market_brief.md` をご覧ください。"
        "投資助言ではありません。",
        "",
        "## 1. 今日の結論　★★★★★",
        render_conclusion(market, analysis.scenario),
        "## 2. 岡三ストラテジスト視点　★★★★★",
        _section_strategist_views(analysis.strategist_views),
        "## 3. Future Intelligence Engine　★★★★★",
        _section_future_intelligence(analysis.future_intelligence),
        "## 4. 今日の相場シナリオ　★★★★☆",
        _section2_scenario(analysis.scenario),
        "## 5. 注目テーマ TOP3　★★★★☆",
        _section3_themes(analysis.theme_forecasts),
        "## 6. 注目業界 TOP3　★★★★☆",
        _section4_sectors(analysis.sector_ranking),
        "## 7. 監視銘柄チェック　★★★★☆",
        _section5_watchlist(analysis.stock_ranking),
        "## 8. 今日の営業トーク　★★★☆☆",
        _section6_sales_talk(analysis.sales_talk_bullets),
        "## 9. 今日の最重要ポイント　★★☆☆☆",
        point + "\n",
    ]
    return "\n".join(sections) + "\n"
