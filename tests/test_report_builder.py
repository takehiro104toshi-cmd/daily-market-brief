"""ネットワークアクセスなしで Market Intelligence System v4 の report builder を検証する。"""
from datetime import datetime

from src.report.builder import build_report
from src.utils import SourceRegistry
from tests.factories import empty_bundle, full_bundle, full_market

REQUIRED_HEADINGS = [
    "## 1. AI Executive Summary",
    "## 2. 今日の結論",
    "## 3. 今日の注目5銘柄",
    "## 4. 主要指標",
    "## 5. 為替・金利",
    "## 6. 今日の相場シナリオ",
    "## 7. 日経平均・ドル円・米国市場 個別シナリオ",
    "## 8. 今日の重要ニュースランキング",
    "## 9. マーケットインパクト",
    "## 10. セクターランキング",
    "## 11. 今日見るべき指標",
    "## 12. マーケット分析",
    "## 13. テーマ分析",
    "## 14. 業界ランキング TOP10",
    "## 15. 個別株ランキング",
    "## 16. 今日のウォッチリスト",
    "## 17. 保有・監視銘柄分析",
    "## 18. 長期投資アイデア TOP5",
    "## 19. 今日電話すべき顧客",
    "## 20. 営業準備",
    "## 21. 営業トーク",
    "## 22. 営業向けコメント",
    "## 23. 想定質問と回答例",
    "## 24. 岡三証券営業向けコメント",
    "## 25. 朝会コメント",
    "## 26. 今日の会話ネタ",
    "## 27. イベント",
    "## 28. AIまとめ",
    "## 29. 引用",
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

    assert report.startswith("# Market Intelligence System v4 — 朝レポート 2026年07月01日")
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

    # 今日の重要ニュースランキング: 理由・影響市場・影響業種・営業トーク
    assert "影響市場（AI分析）" in report and "影響業種（AI分析）" in report
    assert "営業トーク:" in report

    # AIシナリオ分析: 強気/中立/弱気それぞれの理由・注目指標
    assert "強気シナリオの理由" in report
    assert "中立シナリオの理由" in report
    assert "弱気シナリオの理由" in report
    assert "注目指標" in report

    # 今日見るべき指標
    assert "重要ライン" in report

    # 今日のウォッチリスト
    assert "評価" in report and "理由" in report

    # 営業準備（社長向け一言・富裕層向け話題・初心者向け・雑談・想定質問）
    assert "社長向け一言" in report
    assert "富裕層向け話題" in report
    assert "NISA" in report
    assert "今日の雑談" in report
    assert "想定質問" in report
    assert "Q. ドル円どうなる？" in report

    # 営業向けコメント（7オーディエンス）と想定質問と回答例（拡張Q&A）
    assert "NISA初心者向け" in report
    assert "為替に関心がある顧客向け" in report
    assert "米国株に関心がある顧客向け" in report
    assert "日本株に関心がある顧客向け" in report
    assert "Q. 日経平均はまだ上がりますか？" in report

    # モバイル向けにテーブルの列数を絞っていること（出典はリンクアイコンのみ）
    assert "| 名称 | 値 | 前日比 | ★ | 出典 |" in report
    assert "[🔗]" in report

    # 今日の注目5銘柄（日本株5銘柄・米国株5銘柄、注目材料・短期見通し）
    assert "注目材料（AI分析）" in report and "短期見通し（AI分析）" in report

    # 日経平均・ドル円・米国市場 個別シナリオ（AIシナリオ：強気/中立/弱気）
    assert "### 日経平均" in report
    assert "### ドル円" in report
    assert "### 米国市場" in report
    assert "強気シナリオ:" in report
    assert "中立シナリオ:" in report
    assert "弱気シナリオ:" in report

    # 岡三証券営業向けコメント（富裕層・法人・NISA・退職金・相続）
    assert "富裕層のお客様向け" in report
    assert "法人のお客様向け" in report
    assert "NISAご利用のお客様向け" in report
    assert "退職金のご相談のお客様向け" in report
    assert "相続・資産承継のご相談のお客様向け" in report

    # v4: AI Executive Summary
    assert "日本株への影響（AI分析）" in report
    assert "ドル円への影響（AI分析）" in report
    assert "金利への影響（AI分析）" in report

    # v4: 今日電話すべき顧客（富裕層/NISA/退職金/法人/相続/若年層）
    assert "### 富裕層" in report
    assert "### NISA" in report
    assert "### 退職金" in report
    assert "### 法人" in report
    assert "### 相続" in report
    assert "### 若年層" in report

    # v4: マーケットインパクト（対象／影響度／方向の一覧表）
    assert "| 対象 | 影響度 | 方向 |" in report
    assert "日経平均" in report and "半導体" in report and "不動産" in report

    # v4: セクターランキング（強弱予測、矢印）
    assert "↑" in report or "↓" in report or "→" in report

    # v4: 朝会コメント（30秒/1分/3分）
    assert "30秒バージョン" in report
    assert "1分バージョン" in report
    assert "3分バージョン" in report


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
