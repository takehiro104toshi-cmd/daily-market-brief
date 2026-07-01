#!/usr/bin/env python3
"""日本株・米国株・為替・金利の朝レポートを作成するエントリーポイント。

公開情報のみを収集し、Markdown形式で output/ 配下に保存する。
投資助言ではなく、情報整理のためのツール。

使い方:
    python main.py                    # 実行時点の日付でレポートを生成
    python main.py --date 2026-07-01  # レポートの対象日付を指定して生成
"""
from __future__ import annotations

import argparse
import logging
from datetime import datetime, time
from pathlib import Path
from typing import Optional

import pytz

from src.analysis import (
    ai_summary,
    causal_chain,
    chat_topics,
    events,
    key_levels,
    llm_enhancer,
    long_term_picks,
    news_ranking,
    sales_prep,
    scenario,
    sector_ranking,
    stock_ranking,
    themes_forecast,
    watchlist_analysis,
    watchlist_quicklist,
)
from src.analysis.models import AnalysisBundle, SalesTalkBullets
from src.analysis.sales_talk import build_sales_talk_bullets, render_sales_talk_markdown
from src.collectors import earnings, market_data, news, tdnet, themes
from src.report.builder import build_report
from src.report.format_utils import ticker_lookup as build_ticker_lookup
from src.report.html_builder import build_html_report
from src.report.mobile_builder import build_mobile_report
from src.utils import SourceRegistry, load_config, setup_logging

logger = logging.getLogger("market_brief")

BASE_DIR = Path(__file__).resolve().parent
LATEST_FILENAME = "latest_market_brief.md"
MOBILE_FILENAME = "mobile_market_brief.md"
LATEST_HTML_FILENAME = "latest_market_brief.html"


def _safe_call(name: str, func, default):
    """1つの収集処理が失敗してもレポート全体の生成は止めない。"""
    try:
        return func()
    except Exception as exc:  # noqa: BLE001
        logger.warning("%s の収集中にエラーが発生しました: %s", name, exc)
        return default


def parse_args(argv: Optional[list] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="日本株・米国株・為替・金利の朝レポートを生成する（公開情報のみ使用・投資助言ではありません）",
    )
    parser.add_argument(
        "--date",
        type=str,
        default=None,
        metavar="YYYY-MM-DD",
        help=(
            "レポートの対象日付とファイル名（YYYY-MM-DD_market_brief.md）に使う日付。"
            "省略時は実行時点の日付を使用します。"
            "※ 市場データ・ニュース自体は実行時点の最新情報を取得します（過去日への遡り取得ではありません）。"
        ),
    )
    parser.add_argument(
        "--config",
        type=str,
        default="config.yaml",
        help="設定ファイルのパス（デフォルト: config.yaml）",
    )
    return parser.parse_args(argv)


def _resolve_report_datetime(tz: pytz.BaseTzInfo, date_str: Optional[str]) -> datetime:
    if date_str is None:
        return datetime.now(tz)
    try:
        parsed_date = datetime.strptime(date_str, "%Y-%m-%d").date()
    except ValueError as exc:
        raise SystemExit(f"--date は YYYY-MM-DD 形式で指定してください（入力値: {date_str}）") from exc
    return tz.localize(datetime.combine(parsed_date, time(7, 0)))


def generate_report(config_path: str = "config.yaml", date_str: Optional[str] = None) -> Path:
    setup_logging()
    config = load_config(config_path)
    tz = pytz.timezone(config.get("output", {}).get("timezone", "Asia/Tokyo"))
    now = _resolve_report_datetime(tz, date_str)
    if date_str:
        logger.info("--date 指定により、レポート対象日を %s として生成します。", now.strftime("%Y-%m-%d"))

    sources = SourceRegistry()

    logger.info("主要指標・為替・金利・コモディティを取得しています...")
    market = _safe_call(
        "market_overview",
        lambda: market_data.fetch_market_overview(config, sources),
        {"indices": [], "forex": [], "rates": [], "commodities": []},
    )

    logger.info("ウォッチリスト銘柄の株価を取得しています...")
    watchlist_quotes = _safe_call(
        "watchlist_quotes",
        lambda: market_data.fetch_watchlist_quotes(config, sources),
        {"jp_stocks": [], "us_stocks": []},
    )

    logger.info("公開ニュース見出しを取得しています...")
    limit = config.get("output", {}).get("headlines_per_source", 8)
    headlines = _safe_call(
        "news",
        lambda: news.fetch_headlines(config.get("news_sources", []), sources, limit),
        [],
    )

    logger.info("一般ニュース見出し（今日の雑談用）を取得しています...")
    general_headlines = _safe_call(
        "general_news",
        lambda: news.fetch_headlines(config.get("general_news_sources", []), sources, limit),
        [],
    )

    logger.info("TDnet適時開示情報を取得しています...")
    disclosures = _safe_call(
        "tdnet",
        lambda: tdnet.fetch_disclosures(config, sources, start_date=now.date()),
        [],
    )

    logger.info("決算発表予定を取得しています...")
    earnings_events = _safe_call(
        "earnings",
        lambda: earnings.fetch_earnings_calendar(config, sources),
        [],
    )

    theme_matches = _safe_call(
        "themes",
        lambda: themes.match_themes(headlines, config.get("themes", [])),
        [],
    )
    sector_matches = _safe_call(
        "sectors",
        lambda: themes.match_sectors(headlines, config.get("sectors", {})),
        [],
    )

    if llm_enhancer.is_available():
        logger.info("Claude APIによるAI分析の文章磨き上げ: 有効")
    else:
        logger.info("Claude APIによるAI分析の文章磨き上げ: 無効（ルールベースの考察のみ使用します）")

    logger.info("AI分析（ルールベースの機械的考察）を計算しています...")
    jp_quotes = watchlist_quotes.get("jp_stocks", [])
    us_quotes = watchlist_quotes.get("us_stocks", [])
    lookup = build_ticker_lookup(watchlist_quotes)
    watchlist_names = [q.name for q in jp_quotes + us_quotes]

    scenario_forecast = _safe_call(
        "scenario", lambda: scenario.build_scenario(market, sector_matches),
        scenario.ScenarioForecast(34, 33, 33, "データ不足のため暫定値です（取得不可）。"),
    )
    news_ranking_items = _safe_call(
        "news_ranking",
        lambda: news_ranking.build_news_ranking(headlines, config.get("themes", []), config.get("sectors", {}), watchlist_names),
        [],
    )
    causal_chain_text = _safe_call(
        "causal_chain",
        lambda: causal_chain.build_causal_chain(market, sector_matches, lookup),
        "データ不足のため因果関係を整理できませんでした（取得不可）。",
    )
    theme_forecasts = _safe_call(
        "themes_forecast", lambda: themes_forecast.build_theme_forecasts(theme_matches), []
    )
    sector_ranking_entries = _safe_call(
        "sector_ranking", lambda: sector_ranking.build_sector_ranking(sector_matches, lookup), []
    )
    stock_ranking_result = _safe_call(
        "stock_ranking",
        lambda: stock_ranking.build_stock_ranking(jp_quotes, us_quotes, headlines, sector_matches),
        {"jp": [], "us": []},
    )
    watchlist_analysis_result = _safe_call(
        "watchlist_analysis",
        lambda: watchlist_analysis.build_watchlist_analysis(
            jp_quotes, us_quotes, headlines, sector_matches, earnings_events, now
        ),
        {"jp": [], "us": []},
    )
    long_term_picks_result = _safe_call(
        "long_term_picks",
        lambda: long_term_picks.build_long_term_picks(jp_quotes, us_quotes, sector_matches, earnings_events),
        [],
    )
    sales_talk_bullets = _safe_call(
        "sales_talk",
        lambda: build_sales_talk_bullets(market, theme_matches, sector_matches, jp_quotes),
        SalesTalkBullets(),
    )
    sales_talk_text = _safe_call(
        "sales_talk_render",
        lambda: render_sales_talk_markdown(sales_talk_bullets),
        "本日は営業トークを生成できませんでした（取得不可）。",
    )
    chat_topics_result = _safe_call(
        "chat_topics", lambda: chat_topics.build_chat_topics(market, theme_matches, headlines), []
    )
    events_breakdown = _safe_call(
        "events",
        lambda: events.build_events_breakdown(earnings_events, disclosures, config.get("macro_events", []), now),
        events.EventsBreakdown(),
    )
    ai_summary_text = _safe_call(
        "ai_summary",
        lambda: ai_summary.build_ai_summary(scenario_forecast, theme_matches, sector_matches),
        "本日は主要データを十分に取得できなかったため、AIまとめを生成できませんでした（取得不可）。",
    )
    causal_chains_result = _safe_call(
        "causal_chains",
        lambda: causal_chain.build_causal_chains(market, sector_matches, theme_matches, lookup),
        [],
    )
    key_levels_result = _safe_call(
        "key_levels", lambda: key_levels.build_key_levels(market, config), []
    )
    watchlist_quicklist_result = _safe_call(
        "watchlist_quicklist",
        lambda: watchlist_quicklist.build_watchlist_quicklist(jp_quotes, us_quotes, headlines, sector_matches),
        {"jp": [], "us": []},
    )
    sales_prep_result = _safe_call(
        "sales_prep",
        lambda: sales_prep.build_sales_prep(
            market, scenario_forecast, theme_matches, sector_matches, stock_ranking_result, general_headlines
        ),
        sales_prep.SalesPrep(),
    )

    analysis_bundle = AnalysisBundle(
        scenario=scenario_forecast,
        news_ranking=news_ranking_items,
        causal_chain_text=causal_chain_text,
        causal_chains=causal_chains_result,
        theme_forecasts=theme_forecasts,
        sector_ranking=sector_ranking_entries,
        stock_ranking=stock_ranking_result,
        watchlist_analysis=watchlist_analysis_result,
        watchlist_quicklist=watchlist_quicklist_result,
        long_term_picks=long_term_picks_result,
        sales_talk_bullets=sales_talk_bullets,
        sales_talk_text=sales_talk_text,
        sales_prep=sales_prep_result,
        key_levels=key_levels_result,
        chat_topics=chat_topics_result,
        events=events_breakdown,
        ai_summary_text=ai_summary_text,
    )

    logger.info("Markdownレポートを生成しています...")
    report_md = build_report(
        report_date=now,
        market=market,
        sources=sources,
        analysis=analysis_bundle,
    )
    mobile_md = _safe_call(
        "mobile_report",
        lambda: build_mobile_report(report_date=now, market=market, analysis=analysis_bundle),
        f"# Morning Market Brief Mobile\n\nモバイル版レポートの生成に失敗しました（取得不可）。\n",
    )
    html_report = _safe_call(
        "html_report",
        lambda: build_html_report(report_date=now, market=market, sources=sources, analysis=analysis_bundle),
        "<html><body><p>HTML版レポートの生成に失敗しました（取得不可）。</p></body></html>",
    )

    output_dir = BASE_DIR / config.get("output", {}).get("dir", "output")
    output_dir.mkdir(parents=True, exist_ok=True)

    out_path = output_dir / f"{now.strftime('%Y-%m-%d')}_market_brief.md"
    out_path.write_text(report_md, encoding="utf-8")
    logger.info("レポートを保存しました: %s", out_path)

    latest_path = output_dir / LATEST_FILENAME
    latest_path.write_text(report_md, encoding="utf-8")
    logger.info("最新レポートを保存しました: %s", latest_path)

    mobile_path = output_dir / MOBILE_FILENAME
    mobile_path.write_text(mobile_md, encoding="utf-8")
    logger.info("モバイル版レポートを保存しました: %s", mobile_path)

    html_out_path = output_dir / f"{now.strftime('%Y-%m-%d')}_market_brief.html"
    html_out_path.write_text(html_report, encoding="utf-8")
    logger.info("HTML版レポートを保存しました: %s", html_out_path)

    latest_html_path = output_dir / LATEST_HTML_FILENAME
    latest_html_path.write_text(html_report, encoding="utf-8")
    logger.info("最新HTML版レポートを保存しました: %s", latest_html_path)

    return out_path


if __name__ == "__main__":
    args = parse_args()
    generate_report(config_path=args.config, date_str=args.date)
