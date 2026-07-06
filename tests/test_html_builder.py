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


def test_v2_1_toc_reordered_by_investor_priority_with_stars():
    # v2.1: 目次を「投資家が毎朝見る順番」（重要度順）へ再構成。
    # AI Executive Summary → 岡三ストラテジスト視点 → Future Intelligence Engine の順に
    # 並び、各項目に重要度★が表示されることを確認する（分析ロジック・内容は不変）。
    report = build_html_report(
        report_date=datetime(2026, 7, 1),
        market=full_market(),
        sources=SourceRegistry(),
        analysis=full_bundle(),
    )

    pos_exec_summary = report.index('id="executive-summary"')
    pos_strategist = report.index('id="strategist-views"')
    pos_future_intel = report.index('id="future-intelligence"')
    pos_scenario = report.index('id="scenario"')
    assert pos_exec_summary < pos_strategist < pos_future_intel < pos_scenario

    toc_start = report.index("目次")
    toc_end = report.index("</ul>", toc_start)
    toc_html = report[toc_start:toc_end]
    assert "AI Executive Summary" in toc_html and "★★★★★" in toc_html
    assert "Future Intelligence Engine" in toc_html
    assert "今日の相場シナリオ" in toc_html and "★★★★☆" in toc_html
    # Future Intelligence Engineは目次では1項目のみ（内部5ブロックの専用目次はセクション内）
    assert toc_html.count("Future Intelligence Engine") == 1


def _build_report():
    from tests.test_future_intelligence import _v21_bundle

    bundle = full_bundle()
    bundle.future_intelligence = _v21_bundle()  # full_bundle()はFuture Intelligenceを空のまま返すため補う
    return build_html_report(
        report_date=datetime(2026, 7, 1),
        market=full_market(),
        sources=SourceRegistry(),
        analysis=bundle,
    )


def test_v2_2_back_to_top_button_present():
    report = _build_report()
    assert 'class="back-to-top"' in report
    assert 'href="#dashboard-top"' in report
    assert 'id="dashboard-top"' in report
    assert "scroll-behavior: smooth" in report


def test_v2_2_prev_next_nav_between_sections():
    report = _build_report()
    assert "section-nav" in report
    assert "← 前" in report
    assert "次 →" in report
    # 最初のセクション（AI Executive Summary）は「前」を持たない
    # （v2.7で直後に「今週の重要イベント」セクションが追加されたため、
    # 判定範囲はExecutive Summaryカードの範囲＝次カードの開始位置まで）
    exec_start = report.index('id="executive-summary"')
    next_card_start = report.index('id="weekly-events"')
    first_section_html = report[exec_start:next_card_start]
    assert "← 前" not in first_section_html
    assert "次 →" in first_section_html


def test_v2_2_copy_button_present_on_cards():
    report = _build_report()
    assert report.count('class="copy-btn"') > 10
    assert "function copySection" in report


def test_v2_2_future_intelligence_blocks_are_collapsible_details():
    report = _build_report()
    assert "<details class='fi-block fi-block-signals' id='fi-signals' open>" in report
    assert "<details class='fi-block fi-block-theme' id='fi-theme'>" in report
    assert "<summary>" in report


def test_v2_2_todays_action_box_present():
    report = _build_report()
    assert "todays-action" in report
    assert "Today's Action" in report


def test_v2_2_sticky_dashboard_and_options_panel_present():
    report = _build_report()
    assert "sticky-dashboard" in report
    assert "表示オプション" in report
    assert "id='opt-compact'" in report
    assert "id='opt-hide-sales'" in report
    assert "id='opt-dark'" in report
    assert "id='opt-fi-toggle'" in report
    assert "localStorage" in report
    assert 'data-theme="dark"' in report  # ダークモード用CSS変数の切り替え


def test_v2_2_sales_sections_marked_for_hide_toggle():
    report = _build_report()
    for anchor in [
        "sales-prep",
        "sales-talk",
        "sales-comments",
        "okasan-sales-comments",
        "morning-meeting-comment",
        "expanded-qa",
    ]:
        section_start = report.index(f'id="{anchor}"')
        # 該当セクションのdiv開始タグにsales-sectionクラスが含まれる
        div_start = report.rindex("<div class=", 0, section_start)
        assert "sales-section" in report[div_start:section_start]
    # 目次自体・非対象セクションはhide-salesの対象外
    call_priorities_start = report.index('id="call-priorities"')
    div_start = report.rindex("<div class=", 0, call_priorities_start)
    assert "sales-section" not in report[div_start:call_priorities_start]


# --- v2.5: UI/UX & Freshness Upgrade（スマホ最優先のカードUI・お気に入り・検索） ---


def test_v2_5_toc_links_open_in_new_tab():
    report = _build_report()
    toc_start = report.index("<ul class='toc-list'>")  # CSS定義ではなく目次本体から探す
    toc_end = report.index("</ul>", toc_start)
    toc_html = report[toc_start:toc_end]
    # 目次の全リンクが新しいタブで開く
    assert toc_html.count('target="_blank"') == toc_html.count("<a ")
    assert 'rel="noopener"' in toc_html


def test_v2_5_favorites_can_register_and_unregister():
    report = _build_report()
    # 各カード右上の☆ボタン（data-card=アンカー）
    assert 'class="fav-btn" data-card="executive-summary"' in report
    assert report.count('class="fav-btn"') > 10
    # JSに登録（push）と解除（splice）の両方が存在し、確実にトグルできる
    assert "function toggleFav" in report
    assert "favs.push(id)" in report
    assert "favs.splice(idx, 1)" in report
    # localStorageへ保存し、再読み込み時に復元する
    assert "localStorage.setItem('mkt_favs'" in report
    assert "applyFavStates()" in report
    # 0件時の表示と一覧
    assert "お気に入りはありません" in report
    assert "id='fav-list'" in report
    assert "id='opt-favs-only'" in report  # お気に入りのみ表示オプション


def test_v2_5_floating_nav_buttons():
    report = _build_report()
    assert 'class="float-nav"' in report
    assert 'class="back-to-top"' in report and 'href="#dashboard-top"' in report  # ↑TOP（既存機能維持）
    assert 'href="#toc"' in report  # ☰ 目次
    assert 'href="#display-options"' in report  # ★ お気に入り


def test_v2_5_news_freshness_badge_and_panel():
    import pytz

    from tests.test_future_intelligence import _v21_bundle

    bundle = full_bundle()
    bundle.future_intelligence = _v21_bundle()
    bundle.news_ranking[0].headline.published = "Sun, 05 Jul 2026 05:30:00 +0900"
    report = build_html_report(
        report_date=pytz.timezone("Asia/Tokyo").localize(datetime(2026, 7, 5, 7, 0)),
        market=full_market(),
        sources=SourceRegistry(),
        analysis=bundle,
    )
    # ニュースごとの鮮度バッジ（投稿日時・何時間前・鮮度ラベル）
    assert "fresh-badge" in report
    assert "投稿: 07/05 05:30" in report
    assert "時間前" in report
    assert "最新" in report
    # 日時不明の記事は「日時不明」と正直に表示（捏造しない）
    assert "fresh-unknown" in report
    # 既存のNews Freshnessパネルも維持されている（freshness指定時のみ表示のv2.3仕様どおり）
    from src.analysis.data_freshness import DataFreshnessStats

    report_with_stats = build_html_report(
        report_date=datetime(2026, 7, 5),
        market=full_market(),
        sources=SourceRegistry(),
        analysis=full_bundle(),
        freshness=DataFreshnessStats(generated_at=datetime(2026, 7, 5, 7, 0)),
    )
    assert "News Freshness（データ鮮度）" in report_with_stats
    assert 'id="news-freshness"' in report_with_stats  # メニューグリッドから飛べるアンカー


def test_v2_5_search_ui_and_menu_grid():
    report = _build_report()
    # 簡易検索: 入力・クリア・0件メッセージ
    assert 'id="search-input"' in report
    assert "クリア" in report and "clearSearch" in report
    assert "function filterCards" in report
    assert "一致するセクションがありません" in report
    # タグUI
    for tag in ["AI", "半導体", "電力", "防衛", "EV", "金利", "為替", "消費"]:
        assert f'onclick="applyTag(this)">{tag}</button>' in report
    # トップメニューグリッド（主要セクションへのジャンプ）
    assert 'class="menu-grid"' in report
    for href in ["#dashboard-top", "#executive-summary", "#future-intelligence", "#news-ranking", "#data-quality"]:
        assert f'class="menu-btn" href="{href}"' in report


def test_v2_5_card_collapse_and_descriptions():
    report = _build_report()
    assert "function toggleCard" in report
    assert 'class="collapse-btn"' in report
    assert 'class="card-body"' in report
    # ひとこと説明（主要セクション）
    assert "今日最重要のニュース最大3件とその影響を要約します。" in report
    assert "世界→テーマ→業界→銘柄→長期戦略を一気通貫で分析します。" in report


def test_v2_5_existing_html_structure_not_broken():
    report = _build_report()
    # 既存機能の維持: div対応・コピー・表示オプション・sticky・TOC順序
    assert report.count("<div") == report.count("</div>")
    assert report.count('class="copy-btn"') > 10
    assert "id='opt-compact'" in report and "id='opt-dark'" in report
    assert "sticky-dashboard" in report
    assert report.index('id="executive-summary"') < report.index('id="future-intelligence"')
