"""ネットワークアクセスなしで Rashinban Learning Source（v2.6）を検証する。

- data/rashinban/ が空・存在しなくてもエラーにならない
- .md / .txt を読み込み、複数ファイルから最新を判定できる
- RashinbanKnowledge（分析フレーム）が生成される
- 本文の長文転載が起きない（80文字/件・5件/カテゴリの上限）
- HTMLにはファイル名・日付・フレーム数のみ表示され、本文は載らない
- 羅針盤が無い場合、既存分析（news_ranking等）は従来と完全に同じ動作
"""
from datetime import datetime

from src.analysis.models import RashinbanKnowledge
from src.analysis.news_ranking import build_news_ranking
from src.analysis.rashinban_loader import (
    MAX_PATTERN_CHARS,
    MAX_PATTERNS_PER_CATEGORY,
    _read_rashinban_files,
    build_rashinban_knowledge,
    load_rashinban_learning,
)
from src.collectors.news import Headline
from src.report.html_builder import build_html_report
from src.utils import SourceRegistry
from tests.factories import full_bundle, full_market

SAMPLE_TEXT = """# 羅針盤サンプル
日本株は企業業績の改善を背景に、押し目買いが有効な局面と考える。
半導体セクターはAI投資の恩恵で物色が続きやすいテーマとみる。
バリュエーション面ではPERの割安な銘柄を選定したい。
米金利の高止まりはリスク要因として警戒が必要。
短期は調整も、中期では上昇トレンドを想定する。
"""


def test_missing_or_empty_dir_returns_empty(tmp_path):
    # フォルダ自体が無い
    assert _read_rashinban_files(tmp_path / "not_exist", 3) == []
    # フォルダはあるが空
    empty_dir = tmp_path / "rashinban"
    empty_dir.mkdir()
    assert _read_rashinban_files(empty_dir, 3) == []
    # READMEだけの場合も読み込み対象外
    (empty_dir / "README.md").write_text("説明ファイル", encoding="utf-8")
    assert _read_rashinban_files(empty_dir, 3) == []

    knowledge = load_rashinban_learning({"rashinban": {"dir": str(empty_dir)}})
    assert isinstance(knowledge, RashinbanKnowledge)
    assert not knowledge.has_content()
    assert knowledge.frame_count() == 0


def test_reads_md_and_txt_files(tmp_path):
    (tmp_path / "latest.md").write_text(SAMPLE_TEXT, encoding="utf-8")
    (tmp_path / "memo.txt").write_text("長期では脱炭素テーマに注目。", encoding="utf-8")
    (tmp_path / "note.pdf").write_text("PDFは対象外", encoding="utf-8")

    files = _read_rashinban_files(tmp_path, 3)
    names = [name for name, _ in files]
    assert "latest.md" in names
    assert "memo.txt" in names
    assert "note.pdf" not in names
    # latest.md は常に先頭（最新扱い）
    assert names[0] == "latest.md"


def test_latest_file_selected_from_multiple(tmp_path):
    (tmp_path / "2026-07-01_rashinban.md").write_text("古い号。金利上昇に警戒。", encoding="utf-8")
    (tmp_path / "2026-07-05_rashinban.md").write_text("新しい号。日本株に注目。", encoding="utf-8")
    (tmp_path / "2026-06-20_rashinban.md").write_text("最も古い号。", encoding="utf-8")

    files = _read_rashinban_files(tmp_path, 2)
    names = [name for name, _ in files]
    # 日付降順・max_files=2 で新しい2件のみ
    assert names == ["2026-07-05_rashinban.md", "2026-07-01_rashinban.md"]

    knowledge = build_rashinban_knowledge(files)
    assert knowledge.latest_date == "2026-07-05"


def test_builds_rashinban_knowledge_with_patterns():
    knowledge = build_rashinban_knowledge(
        [("latest.md", SAMPLE_TEXT)],
        macro_theme_labels=["半導体", "宇宙"],
    )
    assert knowledge.has_content()
    assert knowledge.frame_count() > 0
    # 各カテゴリの抽出（相場観・テーマ・銘柄選定・リスク・時間軸）
    assert any("日本株" in p for p in knowledge.market_view_patterns)
    assert any("テーマ" in p or "物色" in p for p in knowledge.theme_patterns)
    assert any("PER" in p or "選定" in p for p in knowledge.stock_selection_patterns)
    assert any("警戒" in p or "リスク" in p for p in knowledge.risk_patterns)
    assert any("短期" in p or "中期" in p for p in knowledge.time_horizon_patterns)
    # 重点テーマ: 本文に登場する既存macro_themeラベルのみ（新テーマは生成しない）
    assert knowledge.emphasized_theme_labels == ["半導体"]


def test_no_long_transcription_limits():
    long_line = "日本株は" + "あ" * 300 + "リスクに警戒。"
    many_lines = "\n".join(f"日本株の見方その{i}は業績相場を想定する。" for i in range(20))
    knowledge = build_rashinban_knowledge([("latest.md", long_line + "\n" + many_lines)])

    for patterns in (
        knowledge.market_view_patterns,
        knowledge.theme_patterns,
        knowledge.stock_selection_patterns,
        knowledge.risk_patterns,
        knowledge.time_horizon_patterns,
    ):
        assert len(patterns) <= MAX_PATTERNS_PER_CATEGORY
        assert all(len(p) <= MAX_PATTERN_CHARS for p in patterns)
    assert len(knowledge.raw_excerpt_summary) <= 120


def test_html_shows_rashinban_section_without_body():
    knowledge = build_rashinban_knowledge([("latest.md", SAMPLE_TEXT)], macro_theme_labels=["半導体"])
    report = build_html_report(
        report_date=datetime(2026, 7, 5),
        market=full_market(),
        sources=SourceRegistry(),
        analysis=full_bundle(),
        rashinban=knowledge,
    )
    assert "Rashinban Learning Source" in report
    assert "latest.md" in report
    assert "分析フレーム" in report
    # 本文（羅針盤の文章そのもの）はHTMLへ転載しない
    assert "押し目買いが有効な局面" not in report
    assert knowledge.raw_excerpt_summary not in report


def test_html_works_without_rashinban():
    report = build_html_report(
        report_date=datetime(2026, 7, 5),
        market=full_market(),
        sources=SourceRegistry(),
        analysis=full_bundle(),
    )
    assert "Rashinban Learning Source" not in report
    assert report.strip().endswith("</html>")

    # 未配置（空のknowledge）の場合はスキップした旨だけを表示する
    report_empty = build_html_report(
        report_date=datetime(2026, 7, 5),
        market=full_market(),
        sources=SourceRegistry(),
        analysis=full_bundle(),
        rashinban=RashinbanKnowledge(),
    )
    assert "Rashinban Learning Source" in report_empty
    assert "未配置" in report_empty


def test_news_ranking_unchanged_without_rashinban_and_boosted_with():
    headlines = [
        Headline(title="小売各社の売上動向まとまる", link="https://example.com/2", source="B"),
        Headline(title="半導体大手が新工場建設を発表", link="https://example.com/1", source="A"),
    ]
    base = build_news_ranking(headlines, themes=[], sectors={}, watchlist_names=[])
    same = build_news_ranking(headlines, themes=[], sectors={}, watchlist_names=[], rashinban=RashinbanKnowledge())
    assert base[0].headline.title == "小売各社の売上動向まとまる"  # 同点は出現順
    assert [i.headline.title for i in base] == [i.headline.title for i in same]
    assert [i.stars for i in base] == [i.stars for i in same]

    knowledge = RashinbanKnowledge(source_files=["latest.md"], emphasized_theme_labels=["半導体"])
    boosted = build_news_ranking(headlines, themes=[], sectors={}, watchlist_names=[], rashinban=knowledge)
    top = boosted[0]
    assert "半導体" in top.headline.title
    assert "羅針盤" in top.reason
