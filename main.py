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
import os
from datetime import datetime, time
from pathlib import Path
from typing import Optional

import pytz

from src.analysis import (
    ai_summary,
    call_priority,
    causal_chain,
    chat_topics,
    events,
    executive_summary,
    future_intelligence,
    instrument_scenarios,
    key_levels,
    llm_enhancer,
    long_term_picks,
    market_impact,
    morning_meeting_comment,
    news_ranking,
    okasan_sales_comments,
    sales_comments,
    sales_prep,
    scenario,
    sector_ranking,
    sector_strength,
    stock_ranking,
    strategist_engine,
    themes_forecast,
    top_picks,
    watchlist_analysis,
    watchlist_quicklist,
)
from src.analysis.models import AnalysisBundle, SalesTalkBullets
from src.analysis.sales_talk import build_sales_talk_bullets, render_sales_talk_markdown
from src.collectors import (
    bloomberg,
    boj,
    cnbc,
    earnings,
    edinet,
    investing,
    jpx,
    kabutan,
    macro,
    market_data,
    marketwatch,
    minkabu,
    mof,
    moomoo,
    news,
    nikkei,
    rakuten,
    reuters,
    sbi,
    tdnet,
    themes,
    wsj,
)
from src.report.builder import build_report
from src.report.format_utils import ticker_lookup as build_ticker_lookup
from src.report.html_builder import build_html_report
from src.report.mobile_builder import build_mobile_report
from src.utils import SourceRegistry, load_config, setup_logging

from notifiers.base import NotificationPayload
from notifiers.email_sender import EmailNotifier
from notifiers.line_sender import LineNotifier

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


def _resolve_pages_url(config: dict) -> str:
    """通知本文に載せるGitHub PagesのURLを決定する。

    優先順位: 環境変数 PAGES_URL > GITHUB_REPOSITORY（GitHub Actionsが自動設定）から
    標準的な "https://<owner>.github.io/<repo>/" を組み立て > config.yaml の
    output.pages_url > 空文字（取得不可）。
    """
    explicit = os.environ.get("PAGES_URL")
    if explicit:
        return explicit
    repo = os.environ.get("GITHUB_REPOSITORY")
    if repo and "/" in repo:
        owner, name = repo.split("/", 1)
        return f"https://{owner}.github.io/{name}/"
    return config.get("output", {}).get("pages_url", "") or ""


def _resolve_actions_url(config: dict) -> str:
    """HTMLレポートの「最新情報に更新」ボタンから飛ぶ、GitHub Actions workflowページのURL。

    優先順位: 環境変数 ACTIONS_URL > GITHUB_REPOSITORY（GitHub Actionsが自動設定）から
    ".github/workflows/daily-market-brief.yml" 実行ページのURLを組み立て >
    config.yaml の output.actions_url > 空文字（未設定時はボタン自体を表示しない）。
    """
    explicit = os.environ.get("ACTIONS_URL")
    if explicit:
        return explicit
    repo = os.environ.get("GITHUB_REPOSITORY")
    if repo and "/" in repo:
        return f"https://github.com/{repo}/actions/workflows/daily-market-brief.yml"
    return config.get("output", {}).get("actions_url", "") or ""


def _build_notification_summary(market: dict, analysis: AnalysisBundle) -> str:
    """メール・LINE通知の本文（今日の結論＋重要ニュース3件）を組み立てる。"""
    from src.report.sections import render_conclusion

    conclusion_plain = render_conclusion(market, analysis.scenario).replace("**", "").strip()

    news_items = analysis.news_ranking[:3]
    if news_items:
        news_block = "\n".join(f"- {item.headline.title}" for item in news_items)
    else:
        news_block = "本日は重要ニュースを取得できませんでした（取得不可）。"

    return f"{conclusion_plain}\n\n【重要ニュース3件】\n{news_block}"


def _send_notifications(config: dict, now: datetime, market: dict, analysis: AnalysisBundle) -> None:
    """config.yamlのnotifications設定と環境変数に応じて、メール・LINE通知を送る。

    通知の成否に関わらず例外は外に伝播させない
    （通知の失敗でレポート生成全体を失敗させないため）。
    """
    notif_cfg = config.get("notifications", {})
    try:
        payload = NotificationPayload(
            title=f"【Market Brief】{now.strftime('%Y-%m-%d')} 朝刊",
            summary=_build_notification_summary(market, analysis),
            report_url=_resolve_pages_url(config),
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("通知内容の組み立てに失敗しました（通知はスキップします）: %s", exc)
        return

    if notif_cfg.get("email", {}).get("enabled", True):
        try:
            notifier = EmailNotifier()
            if notifier.is_configured():
                notifier.send(payload)
            else:
                logger.info("メール通知: 環境変数（SMTP_HOST等）が未設定のためスキップします。")
        except Exception as exc:  # noqa: BLE001
            logger.warning("メール通知の処理中にエラーが発生しました（無視して継続します）: %s", exc)
    else:
        logger.info("メール通知: config.yamlでenabled: falseのためスキップします。")

    if notif_cfg.get("line", {}).get("enabled", True):
        try:
            notifier = LineNotifier()
            if notifier.is_configured():
                notifier.send(payload)
            else:
                logger.info("LINE通知: 環境変数（LINE_CHANNEL_ACCESS_TOKEN等）が未設定のためスキップします。")
        except Exception as exc:  # noqa: BLE001
            logger.warning("LINE通知の処理中にエラーが発生しました（無視して継続します）: %s", exc)
    else:
        logger.info("LINE通知: config.yamlでenabled: falseのためスキップします。")


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
    reliability_map = config.get("source_reliability", {})
    headlines = _safe_call(
        "news",
        lambda: news.fetch_headlines(config.get("news_sources", []), sources, limit, reliability_map),
        [],
    )

    logger.info("追加の公開情報源（日経・Bloomberg・Reuters・CNBC・WSJ・MarketWatch・Investing等）を取得しています（ベストエフォート）...")
    extra_headlines = []
    for collector_name, fetch_fn in (
        ("nikkei", lambda: nikkei.fetch_nikkei_headlines(sources, limit, config.get("nikkei_sources"))),
        ("bloomberg", lambda: bloomberg.fetch_bloomberg_headlines(sources, limit, config.get("bloomberg_sources"))),
        ("reuters", lambda: reuters.fetch_reuters_headlines(sources, limit, config.get("reuters_sources"))),
        ("cnbc", lambda: cnbc.fetch_cnbc_headlines(sources, limit, config.get("cnbc_sources"))),
        ("wsj", lambda: wsj.fetch_wsj_headlines(sources, limit, config.get("wsj_sources"))),
        ("marketwatch", lambda: marketwatch.fetch_marketwatch_headlines(sources, limit, config.get("marketwatch_sources"))),
        ("investing", lambda: investing.fetch_investing_headlines(sources, limit, config.get("investing_sources"))),
        ("boj", lambda: boj.fetch_boj_headlines(sources, limit, config.get("boj_sources"))),
        ("mof", lambda: mof.fetch_mof_headlines(sources, limit, config.get("mof_sources"))),
    ):
        extra_headlines.extend(_safe_call(collector_name, fetch_fn, []))
    headlines = news.dedupe_headlines(headlines + extra_headlines)

    _safe_call("kabutan_reference", lambda: kabutan.register_reference(sources), None)
    _safe_call("moomoo_reference", lambda: moomoo.register_reference(sources), None)
    _safe_call("jpx_reference", lambda: jpx.register_reference(sources), None)
    _safe_call("minkabu_reference", lambda: minkabu.register_reference(sources), None)
    _safe_call("sbi_reference", lambda: sbi.register_reference(sources), None)
    _safe_call("rakuten_reference", lambda: rakuten.register_reference(sources), None)
    edinet_documents = _safe_call(
        "edinet",
        lambda: edinet.fetch_edinet_documents(
            sources, target_date=now.date(), documents_url=config.get("edinet", {}).get("documents_url")
        ),
        [],
    )
    fred_config = config.get("fred", {})
    macro_data_points = _safe_call(
        "macro",
        lambda: macro.fetch_macro_data(
            sources,
            csv_url_template=fred_config.get("csv_url_template"),
            series_list=fred_config.get("series"),
        ),
        [],
    )
    logger.info(
        "追加情報源の取得結果: 追加見出し%d件（既存分と合わせて重複除去後 合計%d件）、EDINET%d件、マクロ指標%d件",
        len(extra_headlines),
        len(headlines),
        len(edinet_documents),
        len(macro_data_points),
    )

    logger.info("一般ニュース見出し（今日の雑談用）を取得しています...")
    general_headlines = _safe_call(
        "general_news",
        lambda: news.fetch_headlines(config.get("general_news_sources", []), sources, limit, reliability_map),
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
        lambda: news_ranking.build_news_ranking(
            headlines,
            config.get("themes", []),
            config.get("sectors", {}),
            watchlist_names,
            causal_rules=config.get("causal_rules", []),
            durable_themes=config.get("durable_themes", []),
        ),
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
    sales_comments_result = _safe_call(
        "sales_comments",
        lambda: sales_comments.build_sales_comments(
            market, scenario_forecast, theme_matches, sector_matches, jp_quotes, us_quotes
        ),
        sales_comments.SalesComments(),
    )
    expanded_qa_result = _safe_call(
        "expanded_qa",
        lambda: sales_comments.build_expanded_qa(market, scenario_forecast, theme_matches, sector_matches, us_quotes),
        [],
    )
    top_picks_result = _safe_call(
        "top_picks",
        lambda: top_picks.build_top_picks(jp_quotes, us_quotes, headlines, sector_matches),
        {"jp": [], "us": []},
    )
    instrument_scenarios_result = _safe_call(
        "instrument_scenarios",
        lambda: instrument_scenarios.build_instrument_scenarios(market, headlines),
        [],
    )
    okasan_sales_comments_result = _safe_call(
        "okasan_sales_comments",
        lambda: okasan_sales_comments.build_okasan_sales_comments(
            market, scenario_forecast, theme_matches, sector_matches, jp_quotes
        ),
        okasan_sales_comments.OkasanSalesComments(),
    )
    executive_summary_result = _safe_call(
        "executive_summary",
        lambda: executive_summary.build_executive_summary(news_ranking_items, market, sector_matches, lookup),
        [],
    )
    call_priorities_result = _safe_call(
        "call_priorities",
        lambda: call_priority.build_call_priorities(market, scenario_forecast, theme_matches, sector_matches),
        [],
    )
    market_impact_result = _safe_call(
        "market_impact",
        lambda: market_impact.build_market_impact(market, headlines),
        [],
    )
    sector_strength_result = _safe_call(
        "sector_strength",
        lambda: sector_strength.build_sector_strength(sector_matches),
        [],
    )
    morning_meeting_comment_result = _safe_call(
        "morning_meeting_comment",
        lambda: morning_meeting_comment.build_morning_meeting_comment(
            scenario_forecast, news_ranking_items, theme_matches, sector_matches
        ),
        morning_meeting_comment.MorningMeetingComment(),
    )
    strategist_views_result = _safe_call(
        "strategist_views",
        lambda: strategist_engine.build_strategist_views(news_ranking_items, config, lookup),
        [],
    )
    future_intelligence_result = _safe_call(
        "future_intelligence",
        lambda: future_intelligence.build_future_intelligence(
            headlines, config, config.get("sectors", {}), lookup, news_ranking_items
        ),
        future_intelligence.FutureIntelligenceBundle(),
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
        sales_comments=sales_comments_result,
        expanded_qa=expanded_qa_result,
        top_picks=top_picks_result,
        instrument_scenarios=instrument_scenarios_result,
        okasan_sales_comments=okasan_sales_comments_result,
        executive_summary=executive_summary_result,
        call_priorities=call_priorities_result,
        market_impact=market_impact_result,
        sector_strength=sector_strength_result,
        morning_meeting_comment=morning_meeting_comment_result,
        strategist_views=strategist_views_result,
        future_intelligence=future_intelligence_result,
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
        lambda: build_html_report(
            report_date=now,
            market=market,
            sources=sources,
            analysis=analysis_bundle,
            actions_url=_resolve_actions_url(config),
        ),
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

    logger.info("通知（メール・LINE）の送信を確認しています...")
    _send_notifications(config, now, market, analysis_bundle)

    return out_path


if __name__ == "__main__":
    args = parse_args()
    generate_report(config_path=args.config, date_str=args.date)
