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
    data_freshness,
    events,
    executive_summary,
    future_intelligence,
    instrument_scenarios,
    key_levels,
    llm_enhancer,
    long_term_picks,
    market_impact,
    morning_meeting_comment,
    investment_journal,
    news_ranking,
    okasan_sales_comments,
    rashinban_loader,
    scenario_v2,
    theme_learning,
    translation,
    why_today,
    # v3.2 Analysis Accuracy Upgrade（分析エンジン強化）
    analysis_confidence,
    cross_market,
    future_probability,
    market_breadth,
    market_regime,
    news_impact,
    theme_rotation,
    # v3.5 Market Narrative（本日の相場総括）
    anomaly,
    market_narrative,
    # v3.5.2 Strategic Narrative Engine（朝会3分説明レベル）
    strategic_narrative,
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
    weekly_events,
)
from src.analysis.models import AnalysisBundle, RashinbanKnowledge, SalesTalkBullets
from src.analysis.sales_talk import build_sales_talk_bullets, render_sales_talk_markdown
from src.collectors import (
    bloomberg,
    boj,
    cnbc,
    crypto_news,
    earnings,
    ecb,
    economic_calendar,
    edinet,
    fed,
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
    sec_gov,
    tdnet,
    themes,
    us_gov_stats,
    wsj,
    yahoo_finance_us,
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
    """HTMLレポートの「最新レポートを生成する」ボタンから飛ぶ、該当workflow実行画面の直リンク。

    v3.3（改善②）: 優先順位を config.yaml の output.actions_url 優先へ変更。
    環境変数 ACTIONS_URL（ローカル実行時等の明示的な上書き）> config.yaml の
    output.actions_url（明示設定があれば最優先で採用）> GITHUB_REPOSITORY
    （GitHub Actionsが自動設定する環境変数）から
    "https://github.com/<owner>/<repo>/actions/workflows/daily-market-brief.yml" を
    自動推定 > 空文字（いずれも無ければボタンの代わりに「設定未完了」を表示）。
    """
    explicit = os.environ.get("ACTIONS_URL")
    if explicit:
        return explicit
    configured = config.get("output", {}).get("actions_url", "") or ""
    if configured:
        return configured
    repo = os.environ.get("GITHUB_REPOSITORY")
    if repo and "/" in repo:
        return f"https://github.com/{repo}/actions/workflows/daily-market-brief.yml"
    return ""


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
    # 鮮度統計（v2.3）用: 1件も取得できなかった情報源名を記録する
    failed_source_names = [
        s["name"] for s in config.get("news_sources", []) if not any(h.source == s["name"] for h in headlines)
    ]
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
        # v2.9 Source Expansion Engine（③）: 公式・高信頼ソースと海外マーケット
        # ソースを追加。いずれも公開RSSのみ・失敗時は空リストでレポート生成は継続する。
        ("fed", lambda: fed.fetch_fed_headlines(sources, limit, config.get("fed_sources"))),
        ("sec", lambda: sec_gov.fetch_sec_headlines(sources, limit, config.get("sec_sources"))),
        ("us_gov_stats", lambda: us_gov_stats.fetch_us_gov_stats_headlines(sources, limit, config.get("us_gov_stats_sources"))),
        ("ecb", lambda: ecb.fetch_ecb_headlines(sources, limit, config.get("ecb_sources"))),
        ("crypto_news", lambda: crypto_news.fetch_crypto_news_headlines(sources, limit, config.get("crypto_news_sources"))),
        ("yahoo_finance_us", lambda: yahoo_finance_us.fetch_yahoo_finance_us_headlines(sources, limit, config.get("yahoo_finance_us_sources"))),
    ):
        fetched = _safe_call(collector_name, fetch_fn, [])
        if not fetched:
            failed_source_names.append(collector_name)
        extra_headlines.extend(fetched)
    raw_headlines = headlines + extra_headlines  # 重複除去前の全見出し（鮮度統計用）
    headlines = news.dedupe_headlines(raw_headlines)

    # v2.8/v3.0（①）: 英語見出しの自動翻訳。永続キャッシュ（translation_cache.json）を
    # 使い、過去に翻訳済みの見出しはAPIキー無しでも日本語表示。新規翻訳は
    # ANTHROPIC_API_KEYがある時のみ。未設定・失敗時は原文のまま（既存動作に影響なし）。
    translation_cfg = config.get("translation", {})
    if translation_cfg.get("enabled", True):
        translation_cache_dir = translation_cfg.get("cache_dir", translation.DEFAULT_CACHE_DIR)
        _safe_call(
            "translation",
            lambda: translation.translate_headlines(headlines, cache_dir=translation_cache_dir),
            0,
        )

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

    # v2.6: Rashinban Learning Source（data/rashinban/ に置いた岡三「羅針盤」の
    # md/txtから分析フレームを抽出。ファイルが無ければ空のまま＝既存動作に影響なし）
    macro_theme_labels = [entry.get("label", "") for entry in config.get("macro_themes", [])]
    rashinban_knowledge = _safe_call(
        "rashinban_learning",
        lambda: rashinban_loader.load_rashinban_learning(config, macro_theme_labels),
        RashinbanKnowledge(),
    )

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
            rashinban=rashinban_knowledge,
            now=now,
        ),
        [],
    )
    # v3.2（改善3/4/5）: News Impact Score（0〜100）・Source Tier・Major Story を
    # 既存ランキング結果へ後付けで付与する（並び順・★は変更しない）。
    _safe_call("news_impact", lambda: news_impact.apply_news_impact_scores(news_ranking_items, now), news_ranking_items)
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
    # v2.7/v2.8: Weekly Event Impact Calendar（直近1週間の重要イベント）。
    # config.yamlのmacro_events（登録情報）に、v2.8では経済カレンダーの自動取得分
    # （economic_calendar.url設定時のみ・失敗時は空）をマージして使う。
    auto_events = _safe_call(
        "economic_calendar",
        lambda: economic_calendar.fetch_economic_calendar(config, sources, now),
        [],
    )
    merged_macro_events = economic_calendar.merge_events(config.get("macro_events", []), auto_events)
    weekly_events_result = _safe_call(
        "weekly_events",
        lambda: weekly_events.build_weekly_event_calendar(now, merged_macro_events, earnings_events),
        [],
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
        lambda: executive_summary.build_executive_summary(
            news_ranking_items, market, sector_matches, lookup, rashinban=rashinban_knowledge
        ),
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
        lambda: strategist_engine.build_strategist_views(
            news_ranking_items, config, lookup, rashinban=rashinban_knowledge
        ),
        [],
    )
    # v2.8（②）: Theme Confidence Learning の過去勝率を読み込み、Confidence実績補正に使う
    # （データが無ければ空dict＝補正なし・従来通り）
    theme_learning_dir = config.get("theme_learning", {}).get("dir", theme_learning.DEFAULT_DIR)
    theme_win_rates_map = _safe_call("theme_win_rates", lambda: theme_learning.win_rates(theme_learning_dir), {})
    future_intelligence_result = _safe_call(
        "future_intelligence",
        lambda: future_intelligence.build_future_intelligence(
            headlines,
            config,
            config.get("sectors", {}),
            lookup,
            news_ranking_items,
            executive_summary_result,
            market,
            sector_ranking_entries,
            rashinban=rashinban_knowledge,
            theme_win_rates=theme_win_rates_map,
        ),
        future_intelligence.FutureIntelligenceBundle(),
    )
    # v2.8（③）: Scenario Engine v2（期待値の高い最大3シナリオ）
    scenarios_v2_result = _safe_call(
        "scenarios_v2",
        lambda: scenario_v2.build_scenarios_v2(
            scenario_forecast, sector_matches, watchlist_names, causal_chains_result
        ),
        [],
    )

    # v3.2 Analysis Accuracy Upgrade（分析エンジン強化。いずれも公開市場データ・
    # 既存の算出済みシグナルのみから機械的に算出。生成AIの推測は使わない）。
    market_regime_result = _safe_call("market_regime", lambda: market_regime.build_market_regime(market), None)
    cross_market_result = _safe_call(
        "cross_market", lambda: cross_market.build_cross_market_chains(market, config), []
    )
    conditional_scenarios_result = _safe_call(
        "future_probability", lambda: future_probability.build_conditional_scenarios(market), []
    )
    theme_rotation_result = _safe_call(
        "theme_rotation",
        lambda: theme_rotation.build_theme_rotation(
            future_intelligence_result.theme_momentum, config.get("theme_relations", {})
        ),
        [],
    )
    market_breadth_result = _safe_call(
        "market_breadth", lambda: market_breadth.build_market_breadth(market, list(lookup.values())), None
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
        weekly_events=weekly_events_result,
        scenarios_v2=scenarios_v2_result,
        market_regime=market_regime_result,
        cross_market_chains=cross_market_result,
        conditional_scenarios=conditional_scenarios_result,
        theme_rotation=theme_rotation_result,
        market_breadth=market_breadth_result,
    )

    # v2.8（①②）: Investment Journal / Theme Confidence Learning。
    # 今日のAI判断とテーマ予想を記録し、経過した過去分を現在の市場と答え合わせして
    # Learning History / テーマ別勝率を組み立てる。市場データが無ければ評価はスキップ。
    journal_dir = config.get("investment_journal", {}).get("dir", investment_journal.DEFAULT_DIR)
    date_key = now.strftime("%Y-%m-%d")
    _safe_call(
        "journal_record",
        lambda: investment_journal.record_daily_journal(
            journal_dir, date_key, investment_journal.build_snapshot(date_key, analysis_bundle, market)
        ),
        None,
    )
    _safe_call(
        "theme_learning_record",
        lambda: theme_learning.record_theme_predictions(
            theme_learning_dir, date_key, future_intelligence_result.theme_diagnosis, market
        ),
        None,
    )
    _safe_call("journal_evaluate", lambda: investment_journal.evaluate_journal(journal_dir, market, now), None)
    _safe_call("theme_learning_evaluate", lambda: theme_learning.evaluate_theme_learning(theme_learning_dir, market, now), None)
    analysis_bundle.learning_history = _safe_call(
        "learning_history", lambda: investment_journal.build_learning_history(journal_dir, now), []
    )
    analysis_bundle.theme_learning_stats = _safe_call(
        "theme_learning_stats", lambda: theme_learning.build_theme_learning_stats(theme_learning_dir), []
    )

    # v2.3: データ鮮度統計（計測のみ。分析ロジック・ランキング結果には影響しない）
    freshness_stats = _safe_call(
        "data_freshness",
        lambda: data_freshness.build_data_freshness_stats(
            generated_at=now,
            raw_headlines=raw_headlines,
            deduped_headlines=headlines,
            ranking_items=news_ranking_items,
            attempted_source_names=failed_source_names,
        ),
        None,
    )

    # v3.2（改善10）: Analysis Confidence（旧AI Confidence）。取得ソース数・公式情報数・
    # 重複報道数・鮮度・データ欠損・分析可能項目数という実データのみから機械的に算出。
    analysis_bundle.analysis_confidence = _safe_call(
        "analysis_confidence",
        lambda: analysis_confidence.build_analysis_confidence(
            sources, freshness_stats, market, news_ranking_items, analysis_bundle
        ),
        None,
    )

    # v3.5（改善1/2）: 本日の相場総括（Market Narrative）。既に算出済みの各エンジンの
    # 結果と市場データ・ニュースだけから機械的に組み立てる（生成AI・断定・売買助言なし）。
    analysis_bundle.market_narrative = _safe_call(
        "market_narrative",
        lambda: market_narrative.build_market_narrative(
            market,
            news_ranking_items,
            executive_summary_result,
            future_intelligence_result,
            market_regime_result,
            cross_market_result,
            analysis_bundle.analysis_confidence,
            weekly_events_result,
            anomaly.detect_anomalies(market),
        ),
        None,
    )

    # v3.5.2（改善①〜⑩）: Strategic Narrative Engine。朝会3分説明レベルの相場解説を
    # 既存エンジンの結果だけから組み立てる（生成AI・断定予測・新規取得・捏造なし）。
    analysis_bundle.strategic_narrative = _safe_call(
        "strategic_narrative",
        lambda: strategic_narrative.build_strategic_narrative(
            market,
            market_regime_result,
            cross_market_result,
            news_ranking_items,
            future_intelligence_result,
            market_breadth_result,
            analysis_bundle.analysis_confidence,
            scenario_forecast,
            scenarios_v2_result,
            watchlist_quicklist_result,
            weekly_events_result,
        ),
        None,
    )

    # v2.8（⑦）: 各カードの「なぜ今日見るべきか」を既存データから生成（HTMLのみ使用）
    why_today_map = _safe_call(
        "why_today",
        lambda: why_today.build_why_today(analysis_bundle, freshness_stats, weekly_events_result, now),
        {},
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
            freshness=freshness_stats,
            rashinban=rashinban_knowledge,
            why_today=why_today_map,
            realtime=config.get("realtime", {}),
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

    # v2.3: Data Freshness Summary＋RSS Source Healthをログ（GitHub Actions実行時はJob Summaryにも）出力
    _safe_call("data_freshness_summary", lambda: data_freshness.write_job_summary(freshness_stats), None)

    logger.info("通知（メール・LINE）の送信を確認しています...")
    _send_notifications(config, now, market, analysis_bundle)

    return out_path


if __name__ == "__main__":
    args = parse_args()
    generate_report(config_path=args.config, date_str=args.date)
