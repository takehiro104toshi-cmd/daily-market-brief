"""v2.7（Knowledge Upgrade・鮮度最優先・3分UI）をネットワークなしで検証する。"""
from datetime import datetime, timedelta, timezone

from src.analysis.models import (
    FutureIntelligenceBundle,
    MegatrendEntry,
    RashinbanKnowledge,
    ThemeDiagnosisEntry,
    ThemeMomentumEntry,
)
from src.analysis.news_ranking import build_news_ranking
from src.analysis.rashinban_loader import (
    DEFAULT_MAX_FILES,
    MAX_PATTERNS_PER_CATEGORY,
    _read_rashinban_files,
    build_rashinban_knowledge,
)
from src.collectors.news import Headline
from src.report.html_builder import build_html_report
from src.utils import SourceRegistry
from tests.factories import full_bundle, full_market

NOW = datetime(2026, 7, 6, 7, 0, tzinfo=timezone.utc)


def _rfc2822(dt: datetime) -> str:
    return dt.strftime("%a, %d %b %Y %H:%M:%S +0000")


# ---------- ① 羅針盤 Knowledge（知識ベース化） ----------

def test_knowledge_deduplicates_across_files():
    same_line = "日本株は押し目買いが有効な局面と考える。"
    files = [(f"2026-07-0{i}_rashinban.md", same_line) for i in range(1, 4)]
    knowledge = build_rashinban_knowledge(files)
    # 3ファイルに同じ知見があっても1件に統合される（重複除去）
    assert sum(1 for p in knowledge.market_view_patterns if "押し目買い" in p) == 1


def test_knowledge_ranks_recurring_wisdom_first():
    recurring = "日本株は業績相場への移行を想定する。"
    one_off_lines = "\n".join(f"日本株の個別メモその{i}を確認する。" for i in range(10))
    files = [
        ("2026-07-01_rashinban.md", one_off_lines + "\n" + recurring),
        ("2026-07-02_rashinban.md", recurring),
        ("2026-07-03_rashinban.md", recurring),
    ]
    knowledge = build_rashinban_knowledge(files)
    # 複数号で繰り返し登場する知見（重要な知識）が先頭に来る
    assert knowledge.market_view_patterns[0] == recurring
    assert len(knowledge.market_view_patterns) <= MAX_PATTERNS_PER_CATEGORY


def test_reads_up_to_100_files(tmp_path):
    assert DEFAULT_MAX_FILES == 100
    for i in range(105):
        (tmp_path / f"2026-01-01_no{i:03d}.md").write_text(f"メモ{i}: 長期投資の規律を守る。", encoding="utf-8")
    files = _read_rashinban_files(tmp_path, DEFAULT_MAX_FILES)
    assert len(files) == 100


def test_philosophy_patterns_extracted_and_counted():
    text = "投資哲学として、利益確定の規律を守り長期投資を基本とする。"
    knowledge = build_rashinban_knowledge([("latest.md", text)])
    assert knowledge.philosophy_patterns
    assert knowledge.frame_count() >= len(knowledge.philosophy_patterns)


# ---------- ② ニュース鮮度最優先 ----------

def test_fresh_article_outranks_stale_article():
    fresh = Headline(
        title="新型設備の投資計画を発表", link="https://example.com/f", source="A",
        published=_rfc2822(NOW - timedelta(hours=3)),
    )
    stale = Headline(
        title="新型設備の投資計画を発表（旧報）", link="https://example.com/s", source="B",
        published=_rfc2822(NOW - timedelta(hours=80)),
    )
    items = build_news_ranking([stale, fresh], themes=[], sectors={}, watchlist_names=[], now=NOW)
    assert items[0].headline.link == "https://example.com/f"
    assert "鮮度加点" in items[0].reason
    assert "鮮度を大きく減点" in items[-1].reason


def test_long_impact_event_is_not_penalized_after_48h():
    old_fomc = Headline(
        title="FOMCが政策金利を据え置き", link="https://example.com/fomc", source="A",
        published=_rfc2822(NOW - timedelta(hours=80)),
    )
    old_plain = Headline(
        title="新製品の販売動向まとまる", link="https://example.com/plain", source="B",
        published=_rfc2822(NOW - timedelta(hours=80)),
    )
    items = build_news_ranking([old_plain, old_fomc], themes=[], sectors={}, watchlist_names=[], now=NOW)
    fomc_item = next(i for i in items if "FOMC" in i.headline.title)
    plain_item = next(i for i in items if "販売動向" in i.headline.title)
    # 影響期間の長いイベントは減点されず、通常記事より上位に残る
    assert fomc_item.rank < plain_item.rank
    assert "鮮度減点は適用していません" in fomc_item.reason


def test_unknown_date_articles_get_no_adjustment():
    unknown = Headline(title="日付不明の記事", link="https://example.com/u", source="A")
    items = build_news_ranking([unknown], themes=[], sectors={}, watchlist_names=[], now=NOW)
    assert "鮮度" not in items[0].reason


# ---------- ③〜⑦ 3分で読めるUI ----------

def _build_report(bundle=None):
    return build_html_report(
        report_date=datetime(2026, 7, 6),
        market=full_market(),
        sources=SourceRegistry(),
        analysis=bundle or full_bundle(),
    )


def test_detail_buttons_and_importance_badges_present():
    report = _build_report()
    # 「詳しく」ボタン（アコーディオン）が存在する
    assert "detail-btn" in report
    assert ">詳しく</summary>" in report
    # 重要度（★×20＝100点満点）バッジがカード見出しに付く
    assert "重要度100" in report  # ★★★★★セクション
    assert "重要度80" in report  # ★★★★☆セクション


def test_news_ranking_shows_top5_and_folds_rest():
    from src.analysis.models import NewsRankingItem
    from src.report.html_builder import _news_ranking_html

    items = [
        NewsRankingItem(
            rank=i,
            stars="★★★☆☆",
            headline=Headline(title=f"ニュース{i}", link=f"https://example.com/{i}", source="T"),
            is_top_pick=(i == 1),
            reason="理由",
            affected_market="日本株",
            affected_sector="半導体",
            sales_talk="トーク",
        )
        for i in range(1, 9)
    ]
    html = _news_ranking_html(items)
    assert "6位以下を表示（3件）" in html
    # 各件の理由は「詳しく」内へ移動している
    assert html.count("detail-btn") >= 8


def test_fi_conclusion_and_top8_selection():
    bundle = full_bundle()
    fi = FutureIntelligenceBundle(
        megatrends=[
            MegatrendEntry(label=f"テーマ{i}", stars="★★★☆☆", headline_count=i, why_growing="理由", phase="成長初期", continuity="高い")
            for i in range(12)
        ],
        theme_momentum=[
            ThemeMomentumEntry(label=f"テーマ{i}", momentum_score=i * 8, momentum_label="加速", reason="理由")
            for i in range(12)
        ],
        theme_diagnosis=[
            ThemeDiagnosisEntry(label=f"テーマ{i}", momentum_score=i * 8, momentum_label="加速", phase="成長初期", continuity="高い", confidence_score=i * 8)
            for i in range(12)
        ],
    )
    bundle.future_intelligence = fi
    report = _build_report(bundle)
    # 結論 → 重要ポイント（既存シグナルの転記のみ）
    assert "fi-conclusion" in report
    assert "本日最も勢いのあるテーマは「テーマ11」" in report
    # 上位8件以外は「残りN件を表示」へ折りたたみ
    assert "残り4テーマを表示" in report


def test_watchlist_one_line_summary_with_detail():
    report = _build_report()
    # 評価理由は「詳しく」内へ（more-body内に存在）
    assert "追い風の動きがあります" in report
    idx_reason = report.index("追い風の動きがあります")
    idx_more = report.rindex("more-body", 0, idx_reason)
    assert idx_reason - idx_more < 200  # 理由がmore-body直下にある


def test_html_structure_not_broken():
    report = _build_report()
    assert report.count("<div") == report.count("</div>")
    assert report.count("<details") == report.count("</details>")
    assert report.strip().endswith("</html>")
