"""v2.9 Real-Time Freshness / Translation / Source Expansion Upgrade をネット
ワークなしで検証する。

対象: ①英語ニュース翻訳エンジン強化／②Real-Time Update Engine（2段階更新
ボタン）／③Source Expansion（新規collectorの安全な失敗）／④Duplicate/Cross
Source Intelligence（重複ソース統合・重要度補正）／⑤情報取得時刻の見える化。
"""
from datetime import datetime, timezone

from src.analysis import news_ranking
from src.analysis.data_freshness import build_data_freshness_stats
from src.analysis.source_trust import combined_trust_for_sources
from src.analysis.translation import is_english, translate_headlines
from src.collectors import crypto_news, ecb, fed, sec_gov, us_gov_stats, yahoo_finance_us
from src.collectors.news import Headline, dedupe_headlines
from src.report.html_builder import _news_freshness_card, build_html_report
from src.utils import SourceRegistry
from tests.factories import full_bundle, full_market

NOW = datetime(2026, 7, 7, 7, 0, tzinfo=timezone.utc)


# ---------- ① English News Translation Engine ----------

def test_english_headline_detected_japanese_is_not():
    assert is_english("NVIDIA rises as AI GPU demand remains strong")
    assert not is_english("日銀が金融政策を据え置き")
    assert not is_english("")


def test_translation_noop_without_api_key_does_not_raise():
    # ANTHROPIC_API_KEYが無い環境では原文のまま。翻訳呼び出しが例外で
    # レポート生成を止めないことを確認する。
    headlines = [Headline(title="Fed signals rate cut amid inflation concerns", link="x", source="Reuters")]
    count = translate_headlines(headlines)
    assert count == 0
    assert headlines[0].title_ja == ""
    assert headlines[0].is_translated is False
    assert headlines[0].display_title() == headlines[0].title


def test_translated_and_original_both_shown_in_html():
    bundle = full_bundle()
    bundle.news_ranking[0].headline.title_ja = "半導体株が上昇（テスト訳）"
    report = build_html_report(
        report_date=datetime(2026, 7, 7), market=full_market(), sources=SourceRegistry(), analysis=bundle,
    )
    assert "半導体株が上昇（テスト訳）" in report  # 日本語訳が見出しに使われる
    assert "原文:" in report  # 原文も「詳しく」内に残る


def test_japanese_headlines_are_not_translated_targets():
    headlines = [Headline(title="日銀が金融政策を維持", link="x", source="NHK")]
    count = translate_headlines(headlines)
    assert count == 0
    assert headlines[0].title_ja == ""


# ---------- ② Real-Time Update Engine ----------

def test_refresh_button_shows_reload_always_and_regenerate_with_actions_url():
    report_no_url = build_html_report(
        report_date=datetime(2026, 7, 7), market=full_market(), sources=SourceRegistry(),
        analysis=full_bundle(), actions_url="",
    )
    assert "ページを再読み込み" in report_no_url
    assert 'class="regenerate-btn"' not in report_no_url

    url = "https://github.com/example/repo/actions/workflows/daily-market-brief.yml"
    report_with_url = build_html_report(
        report_date=datetime(2026, 7, 7), market=full_market(), sources=SourceRegistry(),
        analysis=full_bundle(), actions_url=url,
    )
    assert 'class="regenerate-btn"' in report_with_url
    assert f'href="{url}"' in report_with_url
    assert 'target="_blank"' in report_with_url
    assert "Run workflow" in report_with_url  # 説明文で操作方法を案内


def test_no_github_token_or_secret_leaks_into_html():
    report = build_html_report(
        report_date=datetime(2026, 7, 7), market=full_market(), sources=SourceRegistry(),
        analysis=full_bundle(), actions_url="https://github.com/example/repo/actions/workflows/daily-market-brief.yml",
    )
    assert "ghp_" not in report
    assert "github_token" not in report.lower()
    assert "ANTHROPIC_API_KEY" not in report


# ---------- ⑤ 情報取得時刻の見える化 ----------

def test_generation_and_source_fetch_timestamps_shown():
    raw = [
        Headline(title="半導体決算A", link="https://e/a", source="テストRSS",
                 published="Mon, 06 Jul 2026 22:00:00 +0000", fetched_at="2026-07-07T07:00:00+00:00"),
    ]
    stats = build_data_freshness_stats(
        generated_at=NOW, raw_headlines=raw, deduped_headlines=raw,
        ranking_items=news_ranking.build_news_ranking(raw, [], {}, []),
        attempted_source_names=[],
    )
    html = _news_freshness_card(stats)
    assert "HTML生成時刻" in html
    assert "市場データ・為替・金利・コモディティ取得時刻" in html
    assert "各ニュースソースの取得時刻" in html
    assert "テストRSS" in html
    assert "情報取得時刻を詳しく見る" in html  # 折りたたみボタン


# ---------- ③ Source Expansion Engine ----------

def test_new_collectors_return_empty_list_on_unreachable_url_without_raising():
    sources = SourceRegistry()
    local_unreachable = [{"name": "テスト到達不能", "url": "http://127.0.0.1:1/does-not-exist.xml"}]
    for fetch_fn in (
        lambda: fed.fetch_fed_headlines(sources, 8, local_unreachable),
        lambda: sec_gov.fetch_sec_headlines(sources, 8, local_unreachable),
        lambda: us_gov_stats.fetch_us_gov_stats_headlines(sources, 8, local_unreachable),
        lambda: ecb.fetch_ecb_headlines(sources, 8, local_unreachable),
        lambda: crypto_news.fetch_crypto_news_headlines(sources, 8, local_unreachable),
        lambda: yahoo_finance_us.fetch_yahoo_finance_us_headlines(sources, 8, local_unreachable),
    ):
        result = fetch_fn()  # 例外を投げず空リストを返す（レポート生成は止まらない）
        assert result == []


def test_new_collector_default_sources_have_valid_shape():
    assert fed.FED_SOURCES[0]["name"] and fed.FED_SOURCES[0]["url"].startswith("https://")
    assert sec_gov.SEC_SOURCES[0]["url"].startswith("https://")
    assert len(us_gov_stats.US_GOV_STATS_SOURCES) == 2
    assert ecb.ECB_SOURCES[0]["url"].startswith("https://")
    assert len(crypto_news.CRYPTO_NEWS_SOURCES) == 2
    assert yahoo_finance_us.YAHOO_FINANCE_US_SOURCES[0]["url"].startswith("https://")


# ---------- ④ Duplicate / Cross Source Intelligence ----------

def test_dedupe_tracks_duplicate_sources_and_count():
    headlines = [
        Headline(title="半導体大手が新工場建設を発表", link="https://a", source="Reuters", reliability=0.9),
        Headline(title="半導体大手が新工場建設を発表", link="https://b", source="Bloomberg", reliability=0.85),
        Headline(title="半導体大手が新工場建設を発表", link="https://c", source="CNBC", reliability=0.8),
    ]
    result = dedupe_headlines(headlines)
    assert len(result) == 1
    kept = result[0]
    assert kept.source == "Reuters"  # 最も信頼度が高いものを採用元にする
    assert kept.source_count == 3
    assert set(kept.duplicate_sources) == {"Bloomberg", "CNBC"}


def test_single_source_headline_has_default_dedupe_fields():
    h = Headline(title="単独ニュース", link="https://x", source="NHK")
    result = dedupe_headlines([h])
    assert result[0].source_count == 1
    assert result[0].duplicate_sources == []


def test_combined_trust_boosts_importance_for_multiple_high_trust_sources():
    single = Headline(title="AI投資拡大についての記事", link="https://a", source="Reuters")
    multi = Headline(
        title="AI投資拡大についての記事（複数社）", link="https://b", source="Reuters",
        duplicate_sources=["Bloomberg", "CNBC"], source_count=3,
    )
    items = news_ranking.build_news_ranking([single, multi], [], {}, [])
    multi_item = next(i for i in items if "複数社" in i.headline.title)
    single_item = next(i for i in items if i.headline.title == "AI投資拡大についての記事")
    assert multi_item.headline.title in multi_item.reason or "社の高信頼情報源" in multi_item.reason
    # 同一条件下では複数高信頼ソース報道のほうがスコアが高い（星の数が同じか多い）
    assert multi_item.stars.count("★") >= single_item.stars.count("★")


def test_combined_trust_for_sources_helper():
    combined = combined_trust_for_sources("Reuters", ["Bloomberg", "CNBC"])
    assert combined.source_count == 3
    assert combined.max_score == 4
    assert combined.combined_score == 5  # 4 + bonus(2社以上+1, 3社以上+1) capped at 5
    assert set(combined.all_sources) == {"Reuters", "Bloomberg", "CNBC"}

    solo = combined_trust_for_sources("株探", [])
    assert solo.source_count == 1
    assert solo.combined_score == solo.max_score  # 単独報道は補正なし


def test_source_trust_shown_for_duplicate_sources_in_html():
    bundle = full_bundle()
    bundle.news_ranking[0].headline.duplicate_sources = ["Bloomberg", "CNBC"]
    bundle.news_ranking[0].headline.source_count = 3
    bundle.news_ranking[0].headline.source = "Reuters"
    report = build_html_report(
        report_date=datetime(2026, 7, 7), market=full_market(), sources=SourceRegistry(), analysis=bundle,
    )
    assert "社が同一ニュースを報道" in report
    assert "Combined Trust" in report


# ---------- E2E ----------

def test_e2e_report_structure_not_broken():
    bundle = full_bundle()
    bundle.news_ranking[0].headline.title_ja = "テスト日本語訳"
    bundle.news_ranking[0].headline.duplicate_sources = ["Bloomberg"]
    bundle.news_ranking[0].headline.source_count = 2
    raw = [
        Headline(title="半導体決算A", link="https://e/a", source="テストRSS",
                 published="Mon, 06 Jul 2026 22:00:00 +0000", fetched_at="2026-07-07T07:00:00+00:00"),
    ]
    stats = build_data_freshness_stats(
        generated_at=NOW, raw_headlines=raw, deduped_headlines=raw,
        ranking_items=news_ranking.build_news_ranking(raw, [], {}, []), attempted_source_names=[],
    )
    report = build_html_report(
        report_date=datetime(2026, 7, 7),
        market=full_market(),
        sources=SourceRegistry(),
        analysis=bundle,
        actions_url="https://github.com/example/repo/actions/workflows/daily-market-brief.yml",
        freshness=stats,
    )
    assert report.strip().startswith("<!DOCTYPE html>")
    assert report.strip().endswith("</html>")
    assert report.count("<div") == report.count("</div>")
    assert report.count("<details") == report.count("</details>")
    assert "Source Trust" in report
    assert "ページを再読み込み" in report
    assert 'class="regenerate-btn"' in report
    assert "HTML生成時刻" in report
