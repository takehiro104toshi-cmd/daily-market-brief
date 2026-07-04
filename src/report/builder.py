"""Market Intelligence System v4（岡三証券営業員向けAI Morning Assistant）の
朝レポート（Markdown・詳細版）を組み立てる。

このモジュールは「組み立て役」に徹し、各セクションの整形ロジックは
すべて `src/report/sections.py` に委譲する（builder.py の肥大化防止）。

構成（v2.1〜: 「投資家が毎朝見る順番」＝重要度順に再配置。事実とAI分析は明示的に分離）:
  1. 今日の結論（Today's Dashboard相当・3行・太字）★★★★★
  2. AI Executive Summary（今日最重要ニュース最大3件・AI分析）★★★★★
  3. 岡三ストラテジスト視点（AI分析・ニュース→テーマ→セクター→恩恵/悪影響銘柄→営業ポイント→重要度）★★★★★
  4. Future Intelligence Engine（AI分析・世界の長期テーマの定性分析。内部にToday's Future Signals/Theme/Industry/Stock/Long-term Strategyの5ブロック専用目次を持つ）★★★★★
  5. 今日の相場シナリオ（AI分析・強気/中立/弱気の3本立て）★★★★☆
  6. 日経平均・ドル円・米国市場 個別シナリオ（AIシナリオ：強気/中立/弱気）★★★★☆
  7. マーケットインパクト（AI分析・12対象への影響度★・方向）★★★★☆
  8. セクターランキング（AI分析・本日の強弱予測、矢印＋理由）★★★★☆
  9. マーケット分析（AI分析・因果関係を矢印で整理／個別チェーン3〜5本）★★★★☆
  10. 主要指標（事実）★★★★☆
  11. 為替・金利（事実）★★★★☆
  12. 今日の重要ニュースランキング（AI分析・理由/影響市場/影響業種/営業トークつき）★★★★☆
  13. 今日見るべき指標（為替・VIX・米10年・WTI・Gold の節目）★★★★☆
  14. テーマ分析（AI分析・ランキング形式）★★★★☆
  15. 業界ランキング TOP10（AI分析）★★★★☆
  16. 個別株ランキング 日本株TOP10・米国株TOP10（AI分析）★★★★☆
  17. 今日の注目5銘柄（AI分析・日本株5銘柄/米国株5銘柄）★★★★☆
  18. 今日のウォッチリスト（★評価＋1行理由の一覧）★★★★☆
  19. 保有・監視銘柄分析（AI分析）★★★★☆
  20. 長期投資アイデア TOP5（AI分析）★★★★☆
  21. 今日電話すべき顧客（AI分析・富裕層/NISA/退職金/法人/相続/若年層）★★★☆☆
  22. 営業準備（社長向け一言・富裕層向け話題・初心者向け解説・雑談・想定質問）★★★☆☆
  23. 営業トーク（法人社長向け・個人投資家向け・初心者向け・富裕層向け）★★★☆☆
  24. 営業向けコメント（7オーディエンス別・AI分析）★★★☆☆
  25. 岡三証券営業向けコメント（富裕層・法人・NISA・退職金・相続の5顧客タイプ・AI分析）★★★☆☆
  26. 朝会コメント（AI分析・30秒/1分/3分の3パターン）★★★☆☆
  27. 今日の会話ネタ（AI分析）★★★☆☆
  28. 想定質問と回答例（AI分析）★★★☆☆
  29. イベント（今日／今週／今月）（事実）★★★☆☆
  30. AIまとめ（300文字以内）（AI分析）★★☆☆☆
  31. 引用（参照URL一覧）（事実）★★☆☆☆

上記の並び順は「投資家の思考順（毎朝見る順番）」であり、分析ロジック・
スコアリング・各セクションの表示内容そのものには一切変更を加えていない
（v2.1は目次・セクション順序のみの情報設計変更）。

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

# 目次（v2.1: 「投資家が毎朝見る順番」＝重要度順。Future Intelligence Engineは
# ここでは1項目のみ表示し、内部の5ブロック専用目次はセクション側で持つ）
TOC_ENTRIES = [
    ("今日の結論", "★★★★★"),
    ("AI Executive Summary", "★★★★★"),
    ("岡三ストラテジスト視点", "★★★★★"),
    ("Future Intelligence Engine", "★★★★★"),
    ("今日の相場シナリオ", "★★★★☆"),
    ("日経平均・ドル円・米国市場 個別シナリオ", "★★★★☆"),
    ("マーケットインパクト", "★★★★☆"),
    ("セクターランキング", "★★★★☆"),
    ("マーケット分析", "★★★★☆"),
    ("主要指標", "★★★★☆"),
    ("為替・金利", "★★★★☆"),
    ("今日の重要ニュースランキング", "★★★★☆"),
    ("今日見るべき指標", "★★★★☆"),
    ("テーマ分析", "★★★★☆"),
    ("業界ランキング TOP10", "★★★★☆"),
    ("個別株ランキング", "★★★★☆"),
    ("今日の注目5銘柄", "★★★★☆"),
    ("今日のウォッチリスト", "★★★★☆"),
    ("保有・監視銘柄分析", "★★★★☆"),
    ("長期投資アイデア TOP5", "★★★★☆"),
    ("今日電話すべき顧客", "★★★☆☆"),
    ("営業準備", "★★★☆☆"),
    ("営業トーク", "★★★☆☆"),
    ("営業向けコメント", "★★★☆☆"),
    ("岡三証券営業向けコメント", "★★★☆☆"),
    ("朝会コメント", "★★★☆☆"),
    ("今日の会話ネタ", "★★★☆☆"),
    ("想定質問と回答例", "★★★☆☆"),
    ("イベント", "★★★☆☆"),
    ("AIまとめ", "★★☆☆☆"),
    ("引用", "★★☆☆☆"),
]


def _render_toc() -> str:
    lines = ["## 目次", ""]
    lines.extend(f"{i}. {title} {stars}" for i, (title, stars) in enumerate(TOC_ENTRIES, start=1))
    return "\n".join(lines) + "\n"


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
            f"# Market Intelligence System v4 — 朝レポート {date_str}",
            "",
            LEGEND,
            "",
            _render_toc(),
            "",
            sections.render_mobile_digest(market, analysis),
        ]
    )

    # スマホでのスクロール時に区切りが分かりやすいよう、セクション間に --- を挿入する
    # v2.1: 並び順は「投資家が毎朝見る順番」（重要度順）へ再構成。各セクションの
    # 分析ロジック・表示内容そのものは変更していない。
    blocks = [
        "## 1. 今日の結論　★★★★★\n" + sections.render_conclusion(market, analysis.scenario),
        "## 2. AI Executive Summary　★★★★★\n" + sections.render_executive_summary(analysis.executive_summary),
        "## 3. 岡三ストラテジスト視点　★★★★★\n" + sections.render_strategist_views(analysis.strategist_views),
        "## 4. Future Intelligence Engine　★★★★★\n" + sections.render_future_intelligence(analysis.future_intelligence),
        "## 5. 今日の相場シナリオ　★★★★☆\n" + sections.render_scenario(analysis.scenario),
        "## 6. 日経平均・ドル円・米国市場 個別シナリオ　★★★★☆\n" + sections.render_instrument_scenarios(analysis.instrument_scenarios),
        "## 7. マーケットインパクト　★★★★☆\n" + sections.render_market_impact(analysis.market_impact),
        "## 8. セクターランキング　★★★★☆\n" + sections.render_sector_strength(analysis.sector_strength),
        "## 9. マーケット分析　★★★★☆\n" + sections.render_causal_chain(analysis.causal_chain_text, analysis.causal_chains),
        "## 10. 主要指標　★★★★☆\n*事実*\n\n" + quote_table(market["indices"] + market["commodities"]),
        "## 11. 為替・金利　★★★★☆\n*事実*\n\n" + quote_table(market["forex"] + market["rates"]),
        "## 12. 今日の重要ニュースランキング　★★★★☆\n" + sections.render_top_news(analysis.news_ranking),
        "## 13. 今日見るべき指標　★★★★☆\n" + sections.render_key_levels(analysis.key_levels),
        "## 14. テーマ分析　★★★★☆\n" + sections.render_theme_forecasts(analysis.theme_forecasts),
        "## 15. 業界ランキング TOP10　★★★★☆\n" + sections.render_sector_ranking(analysis.sector_ranking),
        "## 16. 個別株ランキング　★★★★☆\n" + sections.render_stock_ranking(analysis.stock_ranking),
        "## 17. 今日の注目5銘柄　★★★★☆\n" + sections.render_top_picks(analysis.top_picks),
        "## 18. 今日のウォッチリスト　★★★★☆\n" + sections.render_watchlist_quicklist(analysis.watchlist_quicklist),
        "## 19. 保有・監視銘柄分析　★★★★☆\n" + sections.render_watchlist_analysis(analysis.watchlist_analysis),
        "## 20. 長期投資アイデア TOP5　★★★★☆\n" + sections.render_long_term_picks(analysis.long_term_picks),
        "## 21. 今日電話すべき顧客　★★★☆☆\n" + sections.render_call_priorities(analysis.call_priorities),
        "## 22. 営業準備　★★★☆☆\n" + sections.render_sales_prep(analysis.sales_prep),
        "## 23. 営業トーク　★★★☆☆\n" + analysis.sales_talk_text,
        "## 24. 営業向けコメント　★★★☆☆\n" + sections.render_sales_comments(analysis.sales_comments),
        "## 25. 岡三証券営業向けコメント　★★★☆☆\n" + sections.render_okasan_sales_comments(analysis.okasan_sales_comments),
        "## 26. 朝会コメント　★★★☆☆\n" + sections.render_morning_meeting_comment(analysis.morning_meeting_comment),
        "## 27. 今日の会話ネタ　★★★☆☆\n" + sections.render_chat_topics(analysis.chat_topics),
        "## 28. 想定質問と回答例　★★★☆☆\n" + sections.render_expanded_qa(analysis.expanded_qa),
        "## 29. イベント　★★★☆☆\n" + sections.render_events(analysis.events),
        "## 30. AIまとめ　★★☆☆☆\n> " + analysis.ai_summary_text + "\n",
        "## 31. 引用　★★☆☆☆\n*事実*\n\n" + sections.render_source_list(sources),
    ]

    return front_matter + MOBILE_SEPARATOR + MOBILE_SEPARATOR.join(blocks) + "\n"
