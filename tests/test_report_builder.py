"""ネットワークアクセスなしで Market Intelligence System v4 の report builder を検証する。"""
from datetime import datetime

from src.report.builder import build_report
from src.utils import SourceRegistry
from tests.factories import empty_bundle, full_bundle, full_market

REQUIRED_HEADINGS = [
    "## 1. 今日の結論",
    "## 2. AI Executive Summary",
    "## 3. 岡三ストラテジスト視点",
    "## 4. Future Intelligence Engine",
    "## 5. 今日の相場シナリオ",
    "## 6. 日経平均・ドル円・米国市場 個別シナリオ",
    "## 7. マーケットインパクト",
    "## 8. セクターランキング",
    "## 9. マーケット分析",
    "## 10. 主要指標",
    "## 11. 為替・金利",
    "## 12. 今日の重要ニュースランキング",
    "## 13. 今日見るべき指標",
    "## 14. テーマ分析",
    "## 15. 業界ランキング TOP10",
    "## 16. 個別株ランキング",
    "## 17. 今日の注目5銘柄",
    "## 18. 今日のウォッチリスト",
    "## 19. 保有・監視銘柄分析",
    "## 20. 長期投資アイデア TOP5",
    "## 21. 今日電話すべき顧客",
    "## 22. 営業準備",
    "## 23. 営業トーク",
    "## 24. 営業向けコメント",
    "## 25. 岡三証券営業向けコメント",
    "## 26. 朝会コメント",
    "## 27. 今日の会話ネタ",
    "## 28. 想定質問と回答例",
    "## 29. イベント",
    "## 30. AIまとめ",
    "## 31. 引用",
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


def test_v2_1_toc_and_section_order_follow_investor_priority():
    # v2.1: 目次・セクション順序を「投資家が毎朝見る順番」（重要度順）へ再構成。
    # 今日の結論→AI Executive Summary→岡三ストラテジスト視点→
    # Future Intelligence Engineの順で並ぶことを確認する（表示内容・分析ロジックは不変）。
    report = build_report(
        report_date=datetime(2026, 7, 1),
        market=full_market(),
        sources=SourceRegistry(),
        analysis=full_bundle(),
    )

    assert "## 目次" in report
    assert "1. 今日の結論 ★★★★★" in report
    assert "2. AI Executive Summary ★★★★★" in report
    assert "3. 岡三ストラテジスト視点 ★★★★★" in report
    assert "4. Future Intelligence Engine ★★★★★" in report

    pos_conclusion = report.index("## 1. 今日の結論")
    pos_exec_summary = report.index("## 2. AI Executive Summary")
    pos_strategist = report.index("## 3. 岡三ストラテジスト視点")
    pos_future_intel = report.index("## 4. Future Intelligence Engine")
    pos_scenario = report.index("## 5. 今日の相場シナリオ")
    assert pos_conclusion < pos_exec_summary < pos_strategist < pos_future_intel < pos_scenario


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
