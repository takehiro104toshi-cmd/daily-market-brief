"""Data Freshness & News Quality（v2.3）をネットワークなしで検証する。

・鮮度タイブレーク（同点なら新しい記事が上位）
・Freshness Score計算
・News Freshness Panel／Data Quality／Job Summary／RSS Source Healthの生成
いずれも表示・計測のみの機能であり、重要度スコア等の分析ロジックが
変わっていないことも併せて確認する。
"""
from datetime import datetime, timedelta, timezone

import pytz

from src.analysis import data_freshness as df
from src.analysis import news_ranking
from src.collectors.news import Headline, parse_published_datetime
from src.report.html_builder import build_html_report
from src.utils import SourceRegistry
from tests.factories import full_bundle, full_market

JST = pytz.timezone("Asia/Tokyo")
NOW = JST.localize(datetime(2026, 7, 5, 7, 0))


def _headline(title, link, published):
    return Headline(title=title, link=link, source="テストRSS", published=published)


def _rfc(dt):
    return dt.strftime("%a, %d %b %Y %H:%M:%S %z")


# --- ① 鮮度タイブレーク ---


def test_tiebreak_prefers_newer_article_when_scores_are_equal():
    old = _headline("半導体 決算の記事（古）", "https://e/old", _rfc(NOW - timedelta(days=3)))
    new = _headline("半導体 決算の記事（新）", "https://e/new", _rfc(NOW - timedelta(hours=2)))
    # 意図的に古い記事を先に渡す（従来は出現順で古い記事が1位になっていたケース）
    items = news_ranking.build_news_ranking([old, new], ["半導体"], {}, [])
    assert items[0].headline.link == "https://e/new"
    assert items[1].headline.link == "https://e/old"


def test_tiebreak_does_not_change_score_based_order():
    # スコアが違う場合は従来通りスコア優先（古い高スコア記事が上位のまま＝スコア算出は不変）
    old_high = _headline("半導体 決算 上方修正（古・高スコア）", "https://e/oh", _rfc(NOW - timedelta(days=3)))
    new_low = _headline("半導体の話題（新・低スコア）", "https://e/nl", _rfc(NOW - timedelta(hours=1)))
    items = news_ranking.build_news_ranking([old_high, new_low], ["半導体"], {}, [])
    assert items[0].headline.link == "https://e/oh"


def test_tiebreak_unparseable_published_sorts_last_within_same_score():
    no_date = _headline("半導体 決算の記事（日時なし）", "https://e/nd", "")
    dated = _headline("半導体 決算の記事（日時あり）", "https://e/d", _rfc(NOW - timedelta(days=5)))
    items = news_ranking.build_news_ranking([no_date, dated], ["半導体"], {}, [])
    assert items[0].headline.link == "https://e/d"


# --- ② Freshness Score ---


def test_freshness_score_thresholds():
    assert df.freshness_score(1) == 5
    assert df.freshness_score(23.9) == 5
    assert df.freshness_score(24) == 4
    assert df.freshness_score(47.9) == 4
    assert df.freshness_score(48) == 3
    assert df.freshness_score(72) == 2
    assert df.freshness_score(96) == 1
    assert df.freshness_score(200) == 1
    assert df.freshness_score(None) == 1
    assert df.freshness_stars(1) == "★★★★★"
    assert df.freshness_stars(100) == "★☆☆☆☆"
    assert df.freshness_label(1) == "非常に新しい"
    assert df.freshness_label(50) == "普通"
    assert df.freshness_label(None) == "判断材料不足"


def test_parse_published_datetime_handles_rfc2822_iso_and_garbage():
    assert parse_published_datetime("Sat, 04 Jul 2026 06:00:00 +0900") is not None
    assert parse_published_datetime("2026-07-04T06:00:00+09:00") is not None
    assert parse_published_datetime("") is None
    assert parse_published_datetime("こんにちは") is None


# --- 統計の組み立て ---


def _stats():
    raw = [
        _headline("半導体 決算A", "https://e/a", _rfc(NOW - timedelta(hours=2))),
        _headline("半導体 決算B", "https://e/b", _rfc(NOW - timedelta(hours=34))),
        _headline("重複記事", "https://e/c", _rfc(NOW - timedelta(hours=3))),
        _headline("重複記事", "https://e/c2", _rfc(NOW - timedelta(hours=3))),
    ]
    deduped = raw[:3]
    items = news_ranking.build_news_ranking(deduped, ["半導体"], {}, [])
    return df.build_data_freshness_stats(
        generated_at=NOW,
        raw_headlines=raw,
        deduped_headlines=deduped,
        ranking_items=items,
        attempted_source_names=["死んでいるRSS"],
    )


def test_build_data_freshness_stats_counts_and_ages():
    stats = _stats()
    assert stats.rss_fetched_total == 4
    assert stats.deduped_total == 3
    assert stats.adopted_count == 3
    assert stats.newest_published is not None
    assert abs((NOW - stats.newest_published).total_seconds() / 3600 - 2) < 0.1
    assert stats.oldest_adopted is not None
    assert stats.avg_age_hours is not None and 10 < stats.avg_age_hours < 20  # (2+34+3)/3 = 13時間
    assert stats.top_item_title  # 1位タイトルが入る
    # Source Health: 取得成功したテストRSSと、0件だった死んでいるRSSの両方が並ぶ
    names = {e.name: e for e in stats.source_health}
    assert names["テストRSS"].ok and names["テストRSS"].count == 4
    assert not names["死んでいるRSS"].ok and names["死んでいるRSS"].count == 0


# --- ③ News Freshness Panel／⑥ Data Quality（HTML） ---


def _html(freshness):
    return build_html_report(
        report_date=datetime(2026, 7, 5),
        market=full_market(),
        sources=SourceRegistry(),
        analysis=full_bundle(),
        freshness=freshness,
    )


def test_news_freshness_panel_rendered_in_html():
    html = _html(_stats())
    assert "News Freshness" in html
    assert "最新ニュース日時" in html
    assert "採用記事平均経過時間" in html
    assert "データ鮮度評価" in html
    assert "RSS取得件数" in html


def test_data_quality_section_rendered_below_sources():
    html = _html(_stats())
    assert 'id="data-quality"' in html
    assert "Data Quality" in html
    assert "ニュース取得" in html and "市場データ" in html
    assert "Future Intelligence" in html and "Watchlist" in html
    assert "平均鮮度" in html and "ランキング対象" in html
    # 引用一覧の「下」に配置される
    assert html.index('id="sources"') < html.index('id="data-quality"')


def test_html_without_freshness_keeps_previous_behavior():
    html = _html(None)
    assert "News Freshness" not in html
    assert 'id="data-quality"' not in html


# --- ④ Job Summary／⑤ RSS Source Health ---


def test_job_summary_markdown_contains_required_fields():
    md = df.render_job_summary_markdown(_stats())
    assert "Data Freshness Summary" in md
    assert "RSS取得件数" in md
    assert "重複削除後件数" in md
    assert "ランキング1位の記事日時" in md
    assert "ランキング1位のタイトル" in md
    assert "Executive Summary採用記事日時" in md
    assert "Dashboard採用記事日時" in md
    assert "HTML生成時刻" in md
    assert "データ鮮度評価" in md


def test_source_health_markdown_lists_success_and_failure():
    md = df.render_source_health_markdown(_stats())
    assert "RSS Source Health" in md
    assert "テストRSS" in md and "✅ 成功" in md
    assert "死んでいるRSS" in md and "❌ 取得失敗" in md


def test_write_job_summary_appends_to_github_step_summary(tmp_path, monkeypatch):
    summary_file = tmp_path / "summary.md"
    monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(summary_file))
    df.write_job_summary(_stats())
    content = summary_file.read_text(encoding="utf-8")
    assert "Data Freshness Summary" in content
    assert "RSS Source Health" in content


def test_write_job_summary_with_none_does_not_crash(monkeypatch):
    monkeypatch.delenv("GITHUB_STEP_SUMMARY", raising=False)
    df.write_job_summary(None)  # 例外にならないこと
