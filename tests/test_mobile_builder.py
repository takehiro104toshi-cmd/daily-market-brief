"""ネットワークアクセスなしで mobile_builder（スマホ向け短縮版）を検証する。"""
from datetime import datetime

from src.report.mobile_builder import build_mobile_report
from tests.factories import empty_bundle, full_bundle, full_market

REQUIRED_HEADINGS = [
    "## 1. 今日の結論",
    "## 2. 岡三ストラテジスト視点",
    "## 3. Future Intelligence Engine",
    "## 4. 今日の相場シナリオ",
    "## 5. 注目テーマ TOP3",
    "## 6. 注目業界 TOP3",
    "## 7. 監視銘柄チェック",
    "## 8. 今日の営業トーク",
    "## 9. 今日の最重要ポイント",
]


def test_mobile_report_has_seven_sections_with_full_data():
    report = build_mobile_report(
        report_date=datetime(2026, 7, 1),
        market=full_market(),
        analysis=full_bundle(),
    )

    assert report.startswith("# Morning Market Brief Mobile — 2026年07月01日")
    for heading in REQUIRED_HEADINGS:
        assert heading in report

    assert "強気 55% ／ 中立 30% ／ 弱気 15%" in report
    assert "トヨタ自動車" in report
    assert "Apple" in report
    # 富裕層向けは含めない（法人社長・個人投資家・初心者の3種類のみ）
    assert "法人社長向けトーク1" in report
    assert "個人投資家向けトーク1" in report
    assert "初心者向けトーク1" in report
    assert "富裕層向けトーク1" not in report
    assert "投資助言ではありません" in report


def test_mobile_report_limits_watchlist_to_five_each():
    from src.analysis.models import StockRankingEntry
    from tests.factories import make_quote

    bundle = full_bundle()
    jp_quotes = [make_quote(f"日本株{i}", 100.0, 1.0, float(i), symbol=f"J{i}") for i in range(8)]
    bundle.stock_ranking = {
        "jp": [StockRankingEntry(rank=i + 1, quote=q, stars="★★★☆☆", short_term="材料。", mid_term="材料。", long_term="材料。") for i, q in enumerate(jp_quotes)],
        "us": [],
    }

    report = build_mobile_report(report_date=datetime(2026, 7, 1), market=full_market(), analysis=bundle)

    for i in range(5):
        assert f"日本株{i}" in report
    for i in range(5, 8):
        assert f"日本株{i}" not in report


def test_mobile_report_handles_missing_data_without_breaking_structure():
    empty_market = {"indices": [], "forex": [], "rates": [], "commodities": []}
    report = build_mobile_report(report_date=datetime(2026, 7, 1), market=empty_market, analysis=empty_bundle())

    assert "取得不可" in report
    for heading in REQUIRED_HEADINGS:
        assert heading in report


def test_v2_1_future_intelligence_engine_moved_to_third_position_with_stars():
    # v2.1: モバイル版も「投資家が毎朝見る順番」へ再構成。今日の結論→
    # 岡三ストラテジスト視点→Future Intelligence Engineの順で並ぶ。
    report = build_mobile_report(report_date=datetime(2026, 7, 1), market=full_market(), analysis=full_bundle())

    pos_conclusion = report.index("## 1. 今日の結論")
    pos_strategist = report.index("## 2. 岡三ストラテジスト視点")
    pos_future_intel = report.index("## 3. Future Intelligence Engine")
    pos_scenario = report.index("## 4. 今日の相場シナリオ")
    assert pos_conclusion < pos_strategist < pos_future_intel < pos_scenario
    assert "★★★★★" in report and "★★★★☆" in report


def test_v2_2_todays_action_appears_atop_future_intelligence():
    # v2.2: Future Intelligence Engineの最上部に「Today's Action」（既存データのみ
    # から機械的に生成した確認事項）を表示することを確認する。
    report = build_mobile_report(report_date=datetime(2026, 7, 1), market=full_market(), analysis=full_bundle())
    fi_start = report.index("## 3. Future Intelligence Engine")
    fi_end = report.index("## 4. 今日の相場シナリオ")
    fi_section = report[fi_start:fi_end]
    assert "Today's Action" in fi_section
