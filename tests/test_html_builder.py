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

    # 「最新表示に更新」ボタンは常時表示（ページ再読み込みのみ、Run workflowへは遷移しない）
    assert 'class="refresh-btn"' in report
    assert "location.reload()" in report
    assert "最新表示に更新" in report
    assert "Run workflow" not in report

    # 新規セクションもHTML側に反映されていること
    assert "今日の重要ニュースランキング" in report
    assert "今日見るべき指標" in report
    assert "今日のウォッチリスト" in report
    assert "営業準備" in report
    assert "営業向けコメント" in report
    assert "想定質問と回答例" in report
    assert "NISA初心者向け" in report
    assert "Q. 日経平均はまだ上がりますか？" in report

    # 最終更新時刻の表示、テーブルが横スクロールしないためのレイアウト
    assert "最終更新" in report
    assert "table-layout: fixed" in report

    # v3: 今日の注目5銘柄、日経平均・ドル円・米国市場の個別シナリオ、岡三証券営業向けコメント
    assert "今日の注目5銘柄" in report
    assert "日経平均・ドル円・米国市場 個別シナリオ" in report
    assert "岡三証券営業向けコメント" in report
    assert "退職金のご相談のお客様向け" in report
    assert "相続・資産承継のご相談のお客様向け" in report

    # v3: 目次カード（TOC）とセクションへのアンカーリンク
    assert "目次" in report
    assert 'id="top-picks"' in report
    assert 'href="#top-picks"' in report
    assert 'id="scenario"' in report

    # v4: Today's Dashboard（最上部・重要ニュース3件＋主要指標カードグリッド）
    assert "Today&#x27;s Dashboard" in report or "Today's Dashboard" in report
    assert "dashboard-grid" in report
    assert ">ドル円<" in report or "ドル円" in report
    assert "NASDAQ" in report
    assert "SOX" in report
    assert "Bitcoin" in report

    # v4: AI Executive Summary
    assert "AI Executive Summary" in report
    assert "日本株への影響" in report and "ドル円への影響" in report and "金利への影響" in report

    # v4: 今日電話すべき顧客
    assert "今日電話すべき顧客" in report
    assert "若年層" in report

    # v4: マーケットインパクト・セクターランキング
    assert "マーケットインパクト" in report
    assert "対象" in report and "影響度" in report
    assert "セクターランキング" in report

    # v4: 朝会コメント
    assert "朝会コメント" in report
    assert "30秒バージョン" in report and "1分バージョン" in report and "3分バージョン" in report

    # Future Intelligence Engine v1.0（グループAのみ）
    assert "Future Intelligence Engine" in report
    assert 'id="future-intelligence"' in report


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


def test_html_report_shows_reload_refresh_button_regardless_of_actions_url():
    # actions_urlを渡しても渡さなくても、常に「ページ再読み込みのみ」のボタンになる
    # （GitHub ActionsのRun workflow画面へは遷移しない）。
    for actions_url in (None, "https://github.com/example/daily-market-brief/actions/workflows/daily-market-brief.yml"):
        report = build_html_report(
            report_date=datetime(2026, 7, 1),
            market=full_market(),
            sources=SourceRegistry(),
            analysis=full_bundle(),
            actions_url=actions_url,
        )

        assert 'class="refresh-btn"' in report
        assert 'href="javascript:location.reload()"' in report
        assert "最新表示に更新" in report
        assert "Run workflow" not in report
        if actions_url:
            assert actions_url not in report
        assert report.count("<div") == report.count("</div>")


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
