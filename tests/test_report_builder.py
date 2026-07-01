"""ネットワークアクセスなしで Market Intelligence System v2 の report builder を検証する。"""
from datetime import datetime

from src.report.builder import build_report
from src.utils import SourceRegistry
from tests.factories import empty_bundle, full_bundle, full_market

REQUIRED_HEADINGS = [
    "## 1. 今日の結論",
    "## 2. 主要指標",
    "## 3. 為替・金利",
    "## 4. 今日の相場シナリオ",
    "## 5. 今日の重要ニュースランキング",
    "## 6. 今日見るべき指標",
    "## 7. マーケット分析",
    "## 8. テーマ分析",
    "## 9. 業界ランキング TOP10",
    "## 10. 個別株ランキング",
    "## 11. 今日のウォッチリスト",
    "## 12. 保有・監視銘柄分析",
    "## 13. 長期投資アイデア TOP5",
    "## 14. 営業準備",
    "## 15. 営業トーク",
    "## 16. 今日の会話ネタ",
    "## 17. イベント",
    "## 18. AIまとめ",
    "## 19. 引用",
]


def test_build_report_with_full_data():
    sources = SourceRegistry()
    sources.add("Test Source", "https://example.com/test", "主要指標")

    report = build_report(
        report_date=datetime(2026, 7, 1),
        market=full_market(),
        sources=sources,
        analysis=full_bundle(),
    )

    assert report.startswith("# Market Intelligence System v2 — 朝レポート 2026年07月01日")
    for heading in REQUIRED_HEADINGS:
        assert heading in report

    assert "📱 今日の5分要約" in report  # 冒頭のモバイル向け5分要約
    assert report.count("\n---\n") >= len(REQUIRED_HEADINGS)  # セクション間の区切り線
    assert "★★★★★" in report  # 今日の結論・今日の相場シナリオのマーカー、TOPニュースの★評価
    assert "🏆AIが本日最重要と判断" in report
    assert "↓" in report  # 因果チェーンの矢印
    assert "チェーン1:" in report and "チェーン2:" in report  # 個別の因果チェーン（3〜5本）
    assert "トヨタ自動車" in report
    assert "投資助言ではありません" in report
    assert "AI分析" in report and "事実" in report  # 事実とAI分析の区別ラベル

    # ② 今日の重要ニュースランキング: 理由・影響市場・影響業種
    assert "影響市場（AI分析）" in report and "影響業種（AI分析）" in report

    # ③ AIシナリオ分析強化: 強気/中立/弱気それぞれの理由・注目指標
    assert "強気シナリオの理由" in report
    assert "中立シナリオの理由" in report
    assert "弱気シナリオの理由" in report
    assert "注目指標" in report

    # ⑤ 今日見るべき指標
    assert "重要ライン" in report

    # ⑥ 今日のウォッチリスト
    assert "評価" in report and "理由" in report

    # ① 営業準備（社長向け一言・富裕層向け話題・初心者向け・雑談・想定質問）
    assert "社長向け一言" in report
    assert "富裕層向け話題" in report
    assert "NISA" in report
    assert "今日の雑談" in report
    assert "想定質問" in report
    assert "Q. ドル円どうなる？" in report

    # モバイル向けにテーブルの列数を絞っていること（出典はリンクアイコンのみ）
    assert "| 名称 | 値 | 前日比 | ★ | 出典 |" in report
    assert "[🔗]" in report


def test_build_report_handles_missing_data():
    empty_market = {"indices": [], "forex": [], "rates": [], "commodities": []}

    report = build_report(
        report_date=datetime(2026, 7, 1),
        market=empty_market,
        sources=SourceRegistry(),
        analysis=empty_bundle(),
    )

    assert "取得不可" in report
    for heading in REQUIRED_HEADINGS:
        assert heading in report
    assert "📱 今日の5分要約" in report
