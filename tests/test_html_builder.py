"""ネットワークアクセスなしで html_builder（カードUI・スマホ閲覧向けHTML）を検証する。"""
from datetime import datetime

from src.report.html_builder import build_html_report
from src.utils import SourceRegistry
from tests.factories import empty_bundle, full_bundle, full_market


def test_html_report_is_well_formed_and_color_coded():
    sources = SourceRegistry()
    sources.add("Test Source", "https://example.com/test", "主要指標")

    report = build_html_report(
        report_date=datetime(2026, 7, 1),
        market=full_market(),
        sources=sources,
        analysis=full_bundle(),
    )

    assert report.strip().startswith("<!DOCTYPE html>")
    assert report.strip().endswith("</html>")
    assert report.count("<div") == report.count("</div>")
    assert "<style>" in report  # 外部CSS不要（インライン埋め込み）
    assert "viewport" in report  # レスポンシブ対応

    # 上昇＝緑／下落＝赤／横ばい＝灰色の色分け
    assert "badge up" in report
    assert "badge down" in report

    # 投資助言ではない旨の明記
    assert "投資助言ではありません" in report

    # 新規セクションもHTML側に反映されていること
    assert "今日の重要ニュースランキング" in report
    assert "今日見るべき指標" in report
    assert "今日のウォッチリスト" in report
    assert "営業準備" in report


def test_html_report_handles_missing_data_without_breaking_structure():
    empty_market = {"indices": [], "forex": [], "rates": [], "commodities": []}

    report = build_html_report(
        report_date=datetime(2026, 7, 1),
        market=empty_market,
        sources=SourceRegistry(),
        analysis=empty_bundle(),
    )

    assert report.strip().startswith("<!DOCTYPE html>")
    assert report.count("<div") == report.count("</div>")
    assert "取得不可" in report


def test_html_report_escapes_headline_titles_to_avoid_broken_markup():
    bundle = full_bundle()
    bundle.chat_topics = ["<script>alert(1)</script>", "通常の話題"]

    report = build_html_report(
        report_date=datetime(2026, 7, 1),
        market=full_market(),
        sources=SourceRegistry(),
        analysis=bundle,
    )

    assert "<script>alert(1)</script>" not in report
    assert "&lt;script&gt;" in report
