"""Market Intelligence System v2 の朝レポート（Markdown・詳細版）を組み立てる。

このモジュールは「組み立て役」に徹し、各セクションの整形ロジックは
すべて `src/report/sections.py` に委譲する（builder.py の肥大化防止）。

構成（事実とAI分析を明示的に分離）:
  1. 今日の結論（3行・太字）★★★★★
  2. 主要指標（事実）
  3. 為替・金利（事実）
  4. 今日の相場シナリオ（AI分析・強気/中立/弱気の3本立て）★★★★★
  5. 今日の重要ニュースランキング（AI分析・理由/影響市場/影響業種つき）
  6. 今日見るべき指標（為替・VIX・米10年・WTI・Gold の節目）
  7. マーケット分析（AI分析・因果関係を矢印で整理／個別チェーン3〜5本）
  8. テーマ分析（AI分析・ランキング形式）
  9. 業界ランキング TOP10（AI分析）
  10. 個別株ランキング 日本株TOP10・米国株TOP10（AI分析）
  11. 今日のウォッチリスト（★評価＋1行理由の一覧）
  12. 保有・監視銘柄分析（AI分析）
  13. 長期投資アイデア TOP5（AI分析）
  14. 営業準備（社長向け一言・富裕層向け話題・初心者向け解説・雑談・想定質問）
  15. 営業トーク（法人社長向け・個人投資家向け・初心者向け・富裕層向け）
  16. 今日の会話ネタ（AI分析）
  17. イベント（今日／今週／今月）（事実）
  18. AIまとめ（300文字以内）（AI分析）
  19. 引用（参照URL一覧）（事実）

本ツールにおける「AI分析」「AI考察」とは、ルールベース（決定論的な数値
ロジック）による機械的な考察を指す。ANTHROPIC_API_KEYが設定されている
場合のみ、Claudeがそのたたき台を事実の範囲内で自然な文章に磨き上げる
（未設定・失敗時は自動的にルールベースの文言にフォールバックする）。
生成AIによる断定的な将来予測ではなく、投資助言でもない。
"""
from __future__ import annotations

from datetime import datetime

from ..analysis.models import AnalysisBundle
from ..utils import SourceRegistry
from . import sections
from .format_utils import quote_table

LEGEND = (
    "> **本レポートについて:** 「事実」は公開情報の実データ、「AI分析」はルールベースの"
    "機械的な考察（ANTHROPIC_API_KEY設定時はClaudeによる文章の磨き上げを含む）です。"
    "生成AIによる断定的な将来予測ではなく、投資助言ではありません。"
    "社外秘資料・有料記事の本文・ログインが必要な情報は使用していません。"
    "データを取得できなかった項目は空欄にせず「取得不可」と明記します。"
)

MOBILE_SEPARATOR = "\n---\n"


def build_report(
    report_date: datetime,
    market: dict,
    sources: SourceRegistry,
    analysis: AnalysisBundle,
) -> str:
    """AnalysisBundle と実データから、詳細版レポートのMarkdown全文を組み立てる。"""
    date_str = report_date.strftime("%Y年%m月%d日")

    front_matter = "\n".join(
        [
            f"# Market Intelligence System v2 — 朝レポート {date_str}",
            "",
            LEGEND,
            "",
            sections.render_mobile_digest(market, analysis),
        ]
    )

    # スマホでのスクロール時に区切りが分かりやすいよう、セクション間に --- を挿入する
    blocks = [
        "## 1. 今日の結論　★★★★★\n" + sections.render_conclusion(market, analysis.scenario),
        "## 2. 主要指標\n*事実*\n\n" + quote_table(market["indices"] + market["commodities"]),
        "## 3. 為替・金利\n*事実*\n\n" + quote_table(market["forex"] + market["rates"]),
        "## 4. 今日の相場シナリオ　★★★★★\n" + sections.render_scenario(analysis.scenario),
        "## 5. 今日の重要ニュースランキング\n" + sections.render_top_news(analysis.news_ranking),
        "## 6. 今日見るべき指標\n" + sections.render_key_levels(analysis.key_levels),
        "## 7. マーケット分析\n" + sections.render_causal_chain(analysis.causal_chain_text, analysis.causal_chains),
        "## 8. テーマ分析\n" + sections.render_theme_forecasts(analysis.theme_forecasts),
        "## 9. 業界ランキング TOP10\n" + sections.render_sector_ranking(analysis.sector_ranking),
        "## 10. 個別株ランキング\n" + sections.render_stock_ranking(analysis.stock_ranking),
        "## 11. 今日のウォッチリスト\n" + sections.render_watchlist_quicklist(analysis.watchlist_quicklist),
        "## 12. 保有・監視銘柄分析\n" + sections.render_watchlist_analysis(analysis.watchlist_analysis),
        "## 13. 長期投資アイデア TOP5\n" + sections.render_long_term_picks(analysis.long_term_picks),
        "## 14. 営業準備\n" + sections.render_sales_prep(analysis.sales_prep),
        "## 15. 営業トーク\n" + analysis.sales_talk_text,
        "## 16. 今日の会話ネタ\n" + sections.render_chat_topics(analysis.chat_topics),
        "## 17. イベント\n" + sections.render_events(analysis.events),
        "## 18. AIまとめ\n> " + analysis.ai_summary_text + "\n",
        "## 19. 引用\n*事実*\n\n" + sections.render_source_list(sources),
    ]

    return front_matter + MOBILE_SEPARATOR + MOBILE_SEPARATOR.join(blocks) + "\n"
