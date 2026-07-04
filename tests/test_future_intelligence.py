"""src/analysis/future_intelligence.py をネットワークなしで検証する。

Future Intelligence Engine（v1.0のグループA、v1.1のTheme Momentum Score /
Early Signal Detection）が、既存シグナル（本日の関連見出し件数・重要ニュース
との一致・durable_themes・causal_rules・恩恵銘柄ロジック）だけから、具体的な
残り年数等を捏造せずに定性的なラベルを導出することを確認する。
"""
from src.analysis import future_intelligence
from src.analysis.models import NewsRankingItem
from src.collectors.market_data import Quote
from src.collectors.news import Headline
from src.report.html_builder import _future_intelligence_html
from src.report.sections import render_future_intelligence

SECTORS = {
    "半導体・電子部品": {"keywords": ["半導体"], "related_tickers": ["8035.T", "6594.T"]},
    "重工業・防衛": {"keywords": ["防衛"], "related_tickers": ["7012.T"]},
}

CAUSAL_RULES = [
    {
        "trigger_keywords": ["半導体投資拡大"],
        "theme": "AI・半導体設備投資",
        "beneficiary_sectors": ["半導体・電子部品"],
        "negative_sectors": [],
        "durable": True,
        "note": "AI関連の設備投資拡大は周辺サプライチェーンへ波及しやすい",
    },
    {
        "trigger_keywords": ["防衛費"],
        "theme": "防衛",
        "beneficiary_sectors": ["重工業・防衛"],
        "negative_sectors": [],
        "durable": True,
        "note": "防衛予算の拡大方針は受注環境改善につながりやすい",
    },
]

CONFIG = {
    "macro_themes": [
        {"label": "AI", "keywords": ["AI", "生成AI"]},
        {"label": "防衛", "keywords": ["防衛", "防衛費"]},
        {"label": "宇宙", "keywords": ["宇宙", "衛星"]},
    ],
    "durable_themes": ["AI", "防衛"],
    "causal_rules": CAUSAL_RULES,
}


class _Quote:
    def __init__(self, symbol, name):
        self.symbol = symbol
        self.name = name


TICKER_LOOKUP = {"8035.T": _Quote("8035.T", "東京エレクトロン"), "7012.T": _Quote("7012.T", "川崎重工業")}


def _headline(title):
    return Headline(title=title, link="https://example.com", source="Test")


def _market_quote(name, price=None, change=None, change_pct=None):
    return Quote(
        name=name, symbol="x", price=price, change=change, change_pct=change_pct, source_label="Test", source_url="u"
    )


def test_megatrends_never_contain_specific_year_counts():
    headlines = [_headline("AI投資拡大が続く"), _headline("生成AIの活用が広がる")]
    bundle = future_intelligence.build_future_intelligence(headlines, CONFIG, SECTORS, TICKER_LOOKUP)

    ai_entry = next(m for m in bundle.megatrends if m.label == "AI")
    assert ai_entry.phase in ("黎明期", "成長初期", "急成長期", "成熟期", "減速期")
    assert ai_entry.continuity in ("高い", "中程度", "限定的")
    # 「残り」「年」という具体的な期間表現を生成しないことを確認する
    assert "残り" not in ai_entry.why_growing
    assert "年後" not in ai_entry.why_growing


def test_durable_theme_with_high_momentum_reaches_top_phase_and_stars():
    headlines = [_headline("AI投資拡大が続く"), _headline("生成AI活用が広がる")]
    bundle = future_intelligence.build_future_intelligence(headlines, CONFIG, SECTORS, TICKER_LOOKUP)

    ai_entry = next(m for m in bundle.megatrends if m.label == "AI")
    assert ai_entry.headline_count == 2
    assert ai_entry.phase == "急成長期"
    assert ai_entry.continuity == "高い"
    assert ai_entry.stars.count("★") == 5


def test_non_durable_theme_with_no_momentum_reaches_lowest_phase():
    bundle = future_intelligence.build_future_intelligence([], CONFIG, SECTORS, TICKER_LOOKUP)

    space_entry = next(m for m in bundle.megatrends if m.label == "宇宙")
    assert space_entry.phase == "減速期"
    assert space_entry.continuity == "限定的"
    assert space_entry.stars.count("★") == 1


def test_industry_momentum_ranks_by_headline_count_and_excludes_zero_hits():
    headlines = [_headline("防衛費増額の議論"), _headline("防衛装備の輸出拡大")]
    bundle = future_intelligence.build_future_intelligence(headlines, CONFIG, SECTORS, TICKER_LOOKUP)

    labels_with_hits = [e.label for e in bundle.industry_momentum]
    assert "防衛" in labels_with_hits
    assert "宇宙" not in labels_with_hits  # 見出しなし


def test_supply_chain_and_jp_stock_impact_reuse_causal_rules():
    headlines = [_headline("防衛費増額の議論が進展")]
    bundle = future_intelligence.build_future_intelligence(headlines, CONFIG, SECTORS, TICKER_LOOKUP)

    defense_chain = next(sc for sc in bundle.supply_chains if sc.theme == "防衛")
    assert "川崎重工業" in defense_chain.chain_text or "7012.T" in defense_chain.chain_text

    defense_impact = next(e for e in bundle.jp_stock_impact if e.theme == "防衛")
    assert "川崎重工業" in defense_impact.beneficiary_names
    assert "区分不明" in defense_impact.cap_note


def test_horizon_groups_place_durable_themes_across_long_horizons():
    bundle = future_intelligence.build_future_intelligence([], CONFIG, SECTORS, TICKER_LOOKUP)

    ten_year = next(hg for hg in bundle.horizon_groups if hg.horizon == "10年")
    half_year = next(hg for hg in bundle.horizon_groups if hg.horizon == "半年")
    assert "AI" in ten_year.themes  # durable_themes該当のため長期にも残る
    assert "AI" not in half_year.themes  # 本日ヒットなしのため短期には含まれない


def test_build_future_intelligence_empty_when_no_macro_themes_configured():
    bundle = future_intelligence.build_future_intelligence([], {"macro_themes": []}, {}, {})
    assert bundle.megatrends == []
    assert bundle.industry_momentum == []
    assert bundle.supply_chains == []
    assert bundle.jp_stock_impact == []
    assert bundle.theme_momentum == []
    assert bundle.early_signals == []
    assert bundle.theme_maturity_notes == []  # macro_themesが空のためテーマ成熟度メモも0件
    assert len(bundle.national_strategy_notes) == 6  # 国家戦略メモは6地域固定で常に生成される


def _news_ranking_item(rank, title):
    return NewsRankingItem(rank=rank, stars="★★★☆☆", headline=_headline(title))


def _executive_summary_item(rank, title):
    from src.analysis.models import ExecutiveSummaryItem

    return ExecutiveSummaryItem(
        rank=rank,
        headline=_headline(title),
        stars="★★★☆☆",
        conclusion="",
        reason="",
        jp_stock_impact="",
        usdjpy_impact="",
        rate_impact="",
        sales_talk="",
    )


def test_momentum_score_combines_headline_density_causal_durable_and_top_news():
    headlines = [_headline("AI投資拡大が続く"), _headline("生成AI活用が広がる")]
    news_ranking_items = [_news_ranking_item(1, "AI投資拡大が続く")]
    bundle = future_intelligence.build_future_intelligence(
        headlines, CONFIG, SECTORS, TICKER_LOOKUP, news_ranking_items=news_ranking_items
    )

    ai_momentum = next(tm for tm in bundle.theme_momentum if tm.label == "AI")
    # headline_count=2 -> 12点、causal_rules該当 +15、durable_themes該当 +15、
    # 重要ニュース一致 +10、関連セクター・関連銘柄あり +15 = 67点（v1.4の重み付け）
    assert ai_momentum.momentum_score == 67
    assert ai_momentum.momentum_label == "加速"
    assert "残り" not in ai_momentum.reason
    # v1.4: 関連セクター・関連銘柄も表示される
    assert ai_momentum.related_sector == "半導体・電子部品"
    assert "東京エレクトロン" in ai_momentum.beneficiary_names


def test_momentum_score_reaches_0_to_100_range_and_reaches_top_label_with_exec_summary_match():
    headlines = [_headline("AI投資拡大が続く"), _headline("生成AI活用が広がる")]
    news_ranking_items = [_news_ranking_item(1, "AI投資拡大が続く")]
    executive_summary_items = [_executive_summary_item(1, "AI投資拡大が続く")]
    bundle = future_intelligence.build_future_intelligence(
        headlines,
        CONFIG,
        SECTORS,
        TICKER_LOOKUP,
        news_ranking_items=news_ranking_items,
        executive_summary_items=executive_summary_items,
    )

    for tm in bundle.theme_momentum:
        assert 0 <= tm.momentum_score <= 100
        assert tm.momentum_label in ("急加速", "加速", "横ばい", "減速")

    ai_momentum = next(tm for tm in bundle.theme_momentum if tm.label == "AI")
    # headline_count=2 -> 12点、causal_rules該当 +15、durable_themes該当 +15、
    # 重要ニュース一致 +10、Executive Summary一致 +15、関連セクター・関連銘柄あり +15 = 82点
    assert ai_momentum.momentum_score == 82
    assert ai_momentum.momentum_label == "急加速"
    assert "Executive Summary" in ai_momentum.reason


def test_momentum_score_is_zero_and_label_slows_down_with_no_signals():
    bundle = future_intelligence.build_future_intelligence([], CONFIG, SECTORS, TICKER_LOOKUP)

    space_momentum = next(tm for tm in bundle.theme_momentum if tm.label == "宇宙")
    assert space_momentum.momentum_score == 0
    assert space_momentum.momentum_label == "減速"
    assert space_momentum.related_sector == ""
    assert space_momentum.beneficiary_names == []


def test_early_signal_detected_for_low_volume_durable_theme_with_supply_chain():
    headlines = [_headline("防衛費増額の議論が進展")]  # 見出し1件のみ
    bundle = future_intelligence.build_future_intelligence(headlines, CONFIG, SECTORS, TICKER_LOOKUP)

    defense_signal = next(es for es in bundle.early_signals if es.label == "防衛")
    assert defense_signal.stars.count("★") == 4  # 基礎3 + durable分1（銘柄1件のため+1は付かない）
    assert "川崎重工業" in defense_signal.beneficiary_names
    assert "重工業・防衛" in defense_signal.related_sector
    # v1.4: 営業で話すポイントが関連セクター・関連銘柄という実データのみから生成される
    assert "重工業・防衛" in defense_signal.sales_talk
    assert "川崎重工業" in defense_signal.sales_talk
    assert "円" not in defense_signal.sales_talk
    assert "%" not in defense_signal.sales_talk


def test_early_signal_not_detected_when_headline_volume_is_high():
    # AIは見出し2件（EARLY_SIGNAL_MAX_HEADLINESの1件を超える）ため、
    # 他の条件を満たしていても初動シグナルには含めない
    headlines = [_headline("AI投資拡大が続く"), _headline("生成AI活用が広がる")]
    bundle = future_intelligence.build_future_intelligence(headlines, CONFIG, SECTORS, TICKER_LOOKUP)

    assert not any(es.label == "AI" for es in bundle.early_signals)


def test_early_signal_not_detected_when_evidence_is_weak():
    # 宇宙は見出しが少なくてもdurable_themes非該当・causal_rules非該当のため、
    # 根拠が弱く初動シグナル扱いにはしない
    headlines = [_headline("宇宙開発の話題")]
    bundle = future_intelligence.build_future_intelligence(headlines, CONFIG, SECTORS, TICKER_LOOKUP)

    assert not any(es.label == "宇宙" for es in bundle.early_signals)


def test_theme_momentum_and_early_signal_appear_in_markdown_and_html_output():
    headlines = [_headline("防衛費増額の議論が進展")]
    bundle = future_intelligence.build_future_intelligence(headlines, CONFIG, SECTORS, TICKER_LOOKUP)

    markdown_text = render_future_intelligence(bundle)
    assert "Theme Momentum Score" in markdown_text
    assert "Early Signal Detection" in markdown_text
    assert "営業で話すポイント" in markdown_text
    assert "関連セクター" in markdown_text

    html_text = _future_intelligence_html(bundle)
    assert "Theme Momentum Score" in html_text
    assert "Early Signal Detection" in html_text
    assert "営業で話すポイント" in html_text


def test_theme_maturity_notes_generate_ai_analysis_when_unregistered_but_signal_exists():
    # theme_maturity_notesキー自体が無くても、durable_themes該当・causal_rules
    # 一致などの既存シグナルがあるテーマは「AI分析」として補完される（v1.3）
    headlines = [_headline("防衛費増額の議論が進展")]
    bundle = future_intelligence.build_future_intelligence(headlines, CONFIG, SECTORS, TICKER_LOOKUP)

    assert len(bundle.theme_maturity_notes) == len(CONFIG["macro_themes"])
    defense_note = next(n for n in bundle.theme_maturity_notes if n.label == "防衛")
    assert defense_note.source_label == "AI分析"
    assert defense_note.basis != ""
    for note_text in (
        defense_note.market_size_note,
        defense_note.adoption_note,
        defense_note.competition_note,
        defense_note.barrier_note,
        defense_note.risk_note,
    ):
        assert note_text.startswith("AI分析")
        # 具体的な市場規模・補助金額等の数値を捏造しないこと
        assert "円" not in note_text
        assert "%" not in note_text


def test_theme_maturity_notes_fall_back_to_insufficient_basis_when_no_signal():
    # 見出し・durable・causal_rules一致・恩恵銘柄のいずれも無いテーマは
    # 「分析材料不足」となり、AIによる推定は行わない（v1.3）
    bundle = future_intelligence.build_future_intelligence([], CONFIG, SECTORS, TICKER_LOOKUP)

    space_note = next(n for n in bundle.theme_maturity_notes if n.label == "宇宙")
    assert space_note.source_label == "分析材料不足"
    assert space_note.market_stage == "分析材料不足"
    assert space_note.basis == ""


def test_theme_maturity_notes_reflect_registered_config_and_leave_others_as_ai_analysis():
    config = dict(CONFIG)
    config["theme_maturity_notes"] = {
        "AI": {
            "market_stage": "急成長期",
            "market_size_note": "データセンター投資と生成AI活用拡大が追い風",
            "adoption_note": "企業導入は拡大中だが、収益化は選別局面",
            "competition_note": "米大手テック企業を中心に競争が激化",
            "barrier_note": "半導体・データ・人材・電力が参入障壁",
            "risk_note": "投資過熱、規制動向、電力供給制約",
        }
    }
    headlines = [_headline("防衛費増額の議論が進展")]
    bundle = future_intelligence.build_future_intelligence(headlines, config, SECTORS, TICKER_LOOKUP)

    ai_note = next(n for n in bundle.theme_maturity_notes if n.label == "AI")
    assert ai_note.source_label == "登録情報"  # 手動登録が最優先される
    assert ai_note.market_stage == "急成長期"
    assert ai_note.risk_note == "投資過熱、規制動向、電力供給制約"

    # 未登録の防衛はcausal_rules一致・durable_themes該当があるためAI分析になる
    defense_note = next(n for n in bundle.theme_maturity_notes if n.label == "防衛")
    assert defense_note.source_label == "AI分析"
    assert defense_note.market_stage != "登録情報"


def test_national_strategy_notes_always_cover_six_fixed_regions_with_ai_analysis():
    bundle = future_intelligence.build_future_intelligence([], CONFIG, SECTORS, TICKER_LOOKUP)

    regions = [n.region for n in bundle.national_strategy_notes]
    assert regions == ["日本", "米国", "中国", "EU", "インド", "中東"]
    for note in bundle.national_strategy_notes:
        # national_focus_areasに対応する登録済macro_themeがある地域はAI分析、
        # 対応するテーマが無い地域（テスト用CONFIGはAI/防衛/宇宙のみ）は
        # 分析材料不足になりうるため、source_labelが両者いずれかであることのみ検証する
        assert note.source_label in ("AI分析", "分析材料不足")
        if note.source_label == "AI分析":
            assert note.policy_note.startswith("AI分析")
            assert "円" not in note.policy_note
        else:
            assert note.policy_note == "分析材料不足"


def test_national_strategy_notes_reflect_registered_config_and_leave_others_as_ai_analysis():
    config = dict(CONFIG)
    config["national_strategy_notes"] = {
        "日本": {
            "focus_areas": ["AI", "半導体", "防衛", "GX"],
            "policy_note": "官民投資・経済安全保障・省力化投資が注目される",
            "regulation_note": "規制緩和と安全保障管理の両面に注意",
            "market_impact_note": "半導体、電力、防衛、省力化関連に波及しやすい",
        }
    }
    bundle = future_intelligence.build_future_intelligence([], config, SECTORS, TICKER_LOOKUP)

    japan_note = next(n for n in bundle.national_strategy_notes if n.region == "日本")
    assert japan_note.source_label == "登録情報"  # 手動登録が最優先される
    assert japan_note.focus_areas == ["AI", "半導体", "防衛", "GX"]
    assert japan_note.policy_note == "官民投資・経済安全保障・省力化投資が注目される"

    # 未登録の米国はnational_focus_areas経由でAI・防衛・宇宙と対応付けられるためAI分析になる
    us_note = next(n for n in bundle.national_strategy_notes if n.region == "米国")
    assert us_note.source_label == "AI分析"
    assert us_note.policy_note != "官民投資・経済安全保障・省力化投資が注目される"


def test_theme_maturity_and_national_strategy_notes_never_fabricate_specific_figures():
    # AI分析であっても、具体的な市場規模・補助金額・政策名等の数値は生成しない
    headlines = [_headline("AI投資拡大が続く"), _headline("生成AI活用が広がる"), _headline("防衛費増額の議論が進展")]
    bundle = future_intelligence.build_future_intelligence(headlines, CONFIG, SECTORS, TICKER_LOOKUP)

    for note in bundle.theme_maturity_notes:
        for text in (note.market_size_note, note.adoption_note, note.competition_note, note.barrier_note, note.risk_note):
            assert "円" not in text
            assert "兆" not in text
            assert "億" not in text
            assert "%" not in text
            assert "残り" not in text

    for note in bundle.national_strategy_notes:
        for text in (note.policy_note, note.regulation_note, note.market_impact_note):
            assert "円" not in text
            assert "兆" not in text
            assert "億" not in text
            assert "%" not in text


def test_ai_analysis_label_appears_in_markdown_and_html_output():
    # 未登録でも既存シグナルからAI分析を生成する場合、Markdown/HTML双方に
    # 「AI分析」ラベルが出力され、断定表現ではないことを確認する（v1.3）
    headlines = [_headline("防衛費増額の議論が進展")]
    bundle = future_intelligence.build_future_intelligence(headlines, CONFIG, SECTORS, TICKER_LOOKUP)

    markdown_text = render_future_intelligence(bundle)
    assert "AI分析" in markdown_text

    html_text = _future_intelligence_html(bundle)
    assert "AI分析" in html_text


_BANNED_CAPITAL_FLOW_PHRASES = (
    "資金が流入している",
    "機関投資家が買っている",
    "海外勢が買っている",
    "億円流入",
)


def test_capital_flow_notes_never_assert_actual_capital_inflow():
    headlines = [_headline("AI投資拡大が続く"), _headline("生成AI活用が広がる")]
    market = {
        "indices": [
            _market_quote("SOX指数（フィラデルフィア半導体指数）", change_pct=3.0),
            _market_quote("ナスダック総合", change_pct=2.5),
            _market_quote("VIX指数（恐怖指数）", price=15.0),
        ],
        "forex": [_market_quote("米ドル/円", change_pct=0.5)],
        "rates": [_market_quote("米10年国債利回り", change=0.02)],
        "commodities": [_market_quote("WTI原油先物", change_pct=1.0), _market_quote("金先物（ゴールド）", change_pct=0.5)],
    }
    bundle = future_intelligence.build_future_intelligence(headlines, CONFIG, SECTORS, TICKER_LOOKUP, market=market)

    assert bundle.capital_flow_notes
    for cf in bundle.capital_flow_notes:
        for text in (cf.reason, cf.sales_talk):
            for phrase in _BANNED_CAPITAL_FLOW_PHRASES:
                assert phrase not in text
            assert "億円" not in text
            assert "兆円" not in text


def test_capital_flow_section_labeled_as_market_signal_based():
    bundle = future_intelligence.build_future_intelligence([], CONFIG, SECTORS, TICKER_LOOKUP)

    markdown_text = render_future_intelligence(bundle)
    assert "世界のお金の流れ（市場シグナルベース）" in markdown_text
    assert "資金の向かいやすさ" in markdown_text

    html_text = _future_intelligence_html(bundle)
    assert "世界のお金の流れ（市場シグナルベース）" in html_text


def test_capital_flow_shows_inflow_leaning_when_signals_are_strong():
    headlines = [_headline("AI投資拡大が続く"), _headline("生成AI活用が広がる")]
    market = {
        "indices": [
            _market_quote("SOX指数（フィラデルフィア半導体指数）", change_pct=4.0),
            _market_quote("ナスダック総合", change_pct=3.0),
        ],
    }
    bundle = future_intelligence.build_future_intelligence(headlines, CONFIG, SECTORS, TICKER_LOOKUP, market=market)

    ai_flow = next(cf for cf in bundle.capital_flow_notes if cf.label == "AI・半導体")
    assert ai_flow.direction_label == "流入しやすい"
    assert "SOX" in ai_flow.reason
    assert ai_flow.sales_talk


def test_capital_flow_shows_outflow_or_insufficient_when_signals_are_weak():
    # SOX・NASDAQが下落し、causal_rules非該当・durable_themes非該当のため
    # Theme Momentum Scoreも低い（"減速"）ことから、AI・半導体は流出しやすい方向になる
    weak_config = {"macro_themes": [{"label": "AI", "keywords": ["AI"]}], "durable_themes": [], "causal_rules": []}
    market = {
        "indices": [
            _market_quote("SOX指数（フィラデルフィア半導体指数）", change_pct=-3.0),
            _market_quote("ナスダック総合", change_pct=-2.0),
        ],
    }
    bundle = future_intelligence.build_future_intelligence([], weak_config, {}, {}, market=market)
    ai_flow = next(cf for cf in bundle.capital_flow_notes if cf.label == "AI・半導体")
    assert ai_flow.direction_label == "流出しやすい"

    # 市場データも判断材料も何も無い場合は「判断材料不足」になる
    empty_config = {"macro_themes": [], "durable_themes": [], "causal_rules": []}
    empty_bundle = future_intelligence.build_future_intelligence([], empty_config, {}, {})
    for cf in empty_bundle.capital_flow_notes:
        assert cf.direction_label == "判断材料不足"


def test_capital_flow_appears_in_markdown_mobile_and_html_output():
    from src.report.mobile_builder import _section_future_intelligence

    headlines = [_headline("防衛費増額の議論が進展")]
    bundle = future_intelligence.build_future_intelligence(headlines, CONFIG, SECTORS, TICKER_LOOKUP)

    markdown_text = render_future_intelligence(bundle)
    assert "世界のお金の流れ" in markdown_text
    for cf in bundle.capital_flow_notes:
        assert cf.label in markdown_text

    html_text = _future_intelligence_html(bundle)
    assert "世界のお金の流れ" in html_text

    mobile_text = _section_future_intelligence(bundle)
    assert "世界のお金の流れ" in mobile_text


def test_theme_diagnosis_confidence_score_is_within_0_to_100():
    headlines = [_headline("AI投資拡大が続く"), _headline("生成AI活用が広がる")]
    news_ranking_items = [_news_ranking_item(1, "AI投資拡大が続く")]
    executive_summary_items = [_executive_summary_item(1, "AI投資拡大が続く")]
    bundle = future_intelligence.build_future_intelligence(
        headlines,
        CONFIG,
        SECTORS,
        TICKER_LOOKUP,
        news_ranking_items=news_ranking_items,
        executive_summary_items=executive_summary_items,
    )

    assert bundle.theme_diagnosis
    for td in bundle.theme_diagnosis:
        assert 0 <= td.confidence_score <= 100

    ai_diagnosis = next(td for td in bundle.theme_diagnosis if td.label == "AI")
    assert ai_diagnosis.confidence_score > 0
    assert ai_diagnosis.confidence_basis


def test_theme_diagnosis_shows_catalyst_and_risk_with_ai_analysis_label():
    headlines = [_headline("AI投資拡大が続く"), _headline("生成AI活用が広がる")]
    bundle = future_intelligence.build_future_intelligence(headlines, CONFIG, SECTORS, TICKER_LOOKUP)

    ai_diagnosis = next(td for td in bundle.theme_diagnosis if td.label == "AI")
    assert ai_diagnosis.catalysts
    assert ai_diagnosis.risks
    # 具体的な数値・補助金額等は生成しない
    for text in ai_diagnosis.catalysts + ai_diagnosis.risks:
        assert "円" not in text
        assert "%" not in text

    markdown_text = render_future_intelligence(bundle)
    assert "Catalyst［AI分析］" in markdown_text
    assert "Risk［AI分析］" in markdown_text
    assert "Confidence" in markdown_text
    assert "Momentum" in markdown_text
    assert "Lifecycle" in markdown_text

    html_text = _future_intelligence_html(bundle)
    assert "Catalyst［AI分析］" in html_text
    assert "Risk［AI分析］" in html_text
    assert "Confidence" in html_text


def test_theme_diagnosis_weak_theme_has_generic_risk_and_low_confidence():
    # 宇宙はcausal_rules非該当・durable_themes非該当・見出しも無いため、
    # 加速要因は「判断材料不足」寄りの内容になり、Confidenceは低めになる
    bundle = future_intelligence.build_future_intelligence([], CONFIG, SECTORS, TICKER_LOOKUP)

    space_diagnosis = next(td for td in bundle.theme_diagnosis if td.label == "宇宙")
    assert space_diagnosis.risks  # 外部環境リスクは常に明記される
    assert space_diagnosis.confidence_score < 50


def test_theme_diagnosis_appears_in_markdown_html_and_mobile_output():
    from src.report.mobile_builder import _section_future_intelligence

    headlines = [_headline("防衛費増額の議論が進展")]
    bundle = future_intelligence.build_future_intelligence(headlines, CONFIG, SECTORS, TICKER_LOOKUP)

    markdown_text = render_future_intelligence(bundle)
    assert "テーマ別診断" in markdown_text
    for td in bundle.theme_diagnosis:
        assert td.label in markdown_text

    html_text = _future_intelligence_html(bundle)
    assert "テーマ別診断" in html_text

    mobile_text = _section_future_intelligence(bundle)
    assert "テーマ別診断" in mobile_text
    assert "Catalyst［AI分析］" in mobile_text
    assert "Risk［AI分析］" in mobile_text


def test_watchlist_intelligence_matches_watchlist_stock_to_theme():
    headlines = [_headline("AI投資拡大が続く"), _headline("生成AI活用が広がる")]
    config = dict(CONFIG)
    config["watchlist"] = {
        "jp_stocks": [{"ticker": "8035.T", "name": "東京エレクトロン"}, {"ticker": "9999.T", "name": "無関係株"}],
        "us_stocks": [],
    }
    bundle = future_intelligence.build_future_intelligence(headlines, config, SECTORS, TICKER_LOOKUP)

    assert bundle.watchlist_intelligence
    tel = next(w for w in bundle.watchlist_intelligence if w.ticker == "8035.T")
    assert "AI" in tel.related_themes
    assert tel.judgment_label in future_intelligence._WATCHLIST_JUDGMENT_LABELS
    assert tel.momentum_score >= 0

    unrelated = next(w for w in bundle.watchlist_intelligence if w.ticker == "9999.T")
    assert unrelated.judgment_label == "判断材料不足"
    assert unrelated.related_themes == []


def test_watchlist_intelligence_shows_judgment_label_and_never_uses_buy_sell_advisory_language():
    headlines = [_headline("AI投資拡大が続く"), _headline("生成AI活用が広がる")]
    config = dict(CONFIG)
    config["watchlist"] = {"jp_stocks": [{"ticker": "8035.T", "name": "東京エレクトロン"}], "us_stocks": []}
    bundle = future_intelligence.build_future_intelligence(headlines, config, SECTORS, TICKER_LOOKUP)

    assert bundle.watchlist_intelligence
    for w in bundle.watchlist_intelligence:
        assert w.judgment_label in future_intelligence._WATCHLIST_JUDGMENT_LABELS
        assert w.judgment_reason
        assert "買い" not in w.judgment_reason
        assert "売り" not in w.judgment_reason
        assert "買え" not in w.judgment_reason
        assert "売れ" not in w.judgment_reason


def test_watchlist_intelligence_appears_in_markdown_html_and_mobile_output():
    from src.report.mobile_builder import _section_future_intelligence

    headlines = [_headline("AI投資拡大が続く"), _headline("生成AI活用が広がる")]
    config = dict(CONFIG)
    config["watchlist"] = {"jp_stocks": [{"ticker": "8035.T", "name": "東京エレクトロン"}], "us_stocks": []}
    bundle = future_intelligence.build_future_intelligence(headlines, config, SECTORS, TICKER_LOOKUP)

    markdown_text = render_future_intelligence(bundle)
    assert "Watchlist Intelligence" in markdown_text
    assert "東京エレクトロン" in markdown_text

    html_text = _future_intelligence_html(bundle)
    assert "Watchlist Intelligence" in html_text

    mobile_text = _section_future_intelligence(bundle)
    assert "Watchlist Intelligence" in mobile_text


def test_theme_diagnosis_shows_related_themes_from_theme_relations_config():
    config = dict(CONFIG)
    config["theme_relations"] = {"AI": ["防衛", "宇宙", "未設定テーマ"], "防衛": ["AI"]}
    bundle = future_intelligence.build_future_intelligence([], config, SECTORS, TICKER_LOOKUP)

    ai_diagnosis = next(td for td in bundle.theme_diagnosis if td.label == "AI")
    assert ai_diagnosis.related_themes == ["防衛", "宇宙"]  # macro_themesに無いテーマは除外される

    defense_diagnosis = next(td for td in bundle.theme_diagnosis if td.label == "防衛")
    assert defense_diagnosis.related_themes == ["AI"]

    space_diagnosis = next(td for td in bundle.theme_diagnosis if td.label == "宇宙")
    assert space_diagnosis.related_themes == []  # theme_relationsに未登録のテーマは空のまま


def test_theme_diagnosis_related_themes_defaults_to_empty_without_config():
    # theme_relationsキー自体が無くても、既存のテーマ診断（Momentum/Lifecycle/
    # Catalyst/Risk/Confidence）は変更なく動作する（後方互換）
    bundle = future_intelligence.build_future_intelligence([], CONFIG, SECTORS, TICKER_LOOKUP)
    for td in bundle.theme_diagnosis:
        assert td.related_themes == []
        assert 0 <= td.confidence_score <= 100
        assert td.momentum_label in ("急加速", "加速", "横ばい", "減速")


def test_theme_diagnosis_related_themes_appear_in_markdown_and_html_output():
    config = dict(CONFIG)
    config["theme_relations"] = {"AI": ["防衛"]}
    headlines = [_headline("防衛費増額の議論が進展")]
    bundle = future_intelligence.build_future_intelligence(headlines, config, SECTORS, TICKER_LOOKUP)

    markdown_text = render_future_intelligence(bundle)
    assert "関連テーマ" in markdown_text

    html_text = _future_intelligence_html(bundle)
    assert "関連テーマ" in html_text


def test_watchlist_intelligence_richer_sector_mapping_reduces_insufficient_data():
    # macro_themes/causal_rulesの紐付け（sectors.related_tickers /
    # causal_rules.beneficiary_sectors）を充実させるほど、Watchlist
    # Intelligenceで「判断材料不足」になる銘柄が減ることを確認する（v1.8）。
    watchlist_stocks = {
        "jp_stocks": [
            {"ticker": "8035.T", "name": "東京エレクトロン"},
            {"ticker": "7012.T", "name": "川崎重工業"},
            {"ticker": "6501.T", "name": "日立製作所"},
        ],
        "us_stocks": [],
    }

    sparse_config = dict(CONFIG)
    sparse_config["watchlist"] = watchlist_stocks
    sparse_bundle = future_intelligence.build_future_intelligence([], sparse_config, SECTORS, TICKER_LOOKUP)
    sparse_insufficient = sum(
        1 for w in sparse_bundle.watchlist_intelligence if w.judgment_label == "判断材料不足"
    )
    assert sparse_insufficient == 1  # 6501.Tは現在のSECTORSには紐付け先が無い

    rich_sectors = dict(SECTORS)
    rich_sectors["電機・電線・素材"] = {"keywords": ["電線", "重電"], "related_tickers": ["6501.T"]}
    rich_causal_rules = [
        {
            "trigger_keywords": ["半導体投資拡大"],
            "theme": "AI・半導体設備投資",
            "beneficiary_sectors": ["半導体・電子部品", "電機・電線・素材"],
            "negative_sectors": [],
            "durable": True,
            "note": "AI関連の設備投資拡大は周辺サプライチェーンへ波及しやすい",
        },
        CAUSAL_RULES[1],
    ]
    rich_config = dict(CONFIG)
    rich_config["watchlist"] = watchlist_stocks
    rich_config["causal_rules"] = rich_causal_rules
    rich_bundle = future_intelligence.build_future_intelligence([], rich_config, rich_sectors, TICKER_LOOKUP)
    rich_insufficient = sum(1 for w in rich_bundle.watchlist_intelligence if w.judgment_label == "判断材料不足")

    assert rich_insufficient < sparse_insufficient
    assert rich_insufficient == 0

    hitachi = next(w for w in rich_bundle.watchlist_intelligence if w.ticker == "6501.T")
    assert "AI" in hitachi.related_themes
    assert hitachi.judgment_label in future_intelligence._WATCHLIST_JUDGMENT_LABELS


def test_v1_9_new_themes_are_recognized_in_theme_diagnosis():
    # v1.9で追加予定の自動車／EV／蓄電池テーマが、既存のmacro_themes/causal_rules
    # と同じ仕組みでテーマ別診断に認識されることを確認する（新規ロジックなし）
    config = dict(CONFIG)
    config["macro_themes"] = CONFIG["macro_themes"] + [
        {"label": "自動車", "keywords": ["自動車", "自動車販売"]},
        {"label": "EV", "keywords": ["EV"]},
        {"label": "蓄電池", "keywords": ["蓄電池"]},
    ]
    config["causal_rules"] = CAUSAL_RULES + [
        {
            "trigger_keywords": ["自動車販売", "EV普及", "車載電池"],
            "theme": "自動車市況・EV・蓄電池",
            "beneficiary_sectors": ["自動車"],
            "negative_sectors": [],
            "durable": True,
            "note": "自動車・EV・蓄電池の生産販売動向は完成車メーカーの業績に直結しやすい",
        }
    ]
    sectors = dict(SECTORS)
    sectors["自動車"] = {"keywords": ["自動車", "EV"], "related_tickers": ["7203.T"]}

    bundle = future_intelligence.build_future_intelligence([], config, sectors, TICKER_LOOKUP)
    labels = {td.label for td in bundle.theme_diagnosis}
    assert {"自動車", "EV", "蓄電池"} <= labels

    ev_diagnosis = next(td for td in bundle.theme_diagnosis if td.label == "EV")
    assert 0 <= ev_diagnosis.confidence_score <= 100
    assert ev_diagnosis.momentum_label in ("急加速", "加速", "横ばい", "減速")


def test_watchlist_intelligence_v1_9_themes_further_reduce_insufficient_data():
    # 自動車・金融関連の紐付けを追加するほど、Watchlist Intelligenceで
    # 「判断材料不足」になる銘柄がさらに減ることを確認する（v1.9）
    watchlist_stocks = {
        "jp_stocks": [
            {"ticker": "8035.T", "name": "東京エレクトロン"},
            {"ticker": "7012.T", "name": "川崎重工業"},
            {"ticker": "7203.T", "name": "トヨタ自動車"},
            {"ticker": "8306.T", "name": "三菱UFJフィナンシャル・グループ"},
        ],
        "us_stocks": [{"ticker": "TSLA", "name": "Tesla"}],
    }

    baseline_config = dict(CONFIG)
    baseline_config["watchlist"] = watchlist_stocks
    baseline_bundle = future_intelligence.build_future_intelligence([], baseline_config, SECTORS, TICKER_LOOKUP)
    baseline_insufficient = sum(
        1 for w in baseline_bundle.watchlist_intelligence if w.judgment_label == "判断材料不足"
    )
    assert baseline_insufficient == 3  # 7203.T・8306.T・TSLAはCONFIG/SECTORSに紐付け先が無い

    expanded_sectors = dict(SECTORS)
    expanded_sectors["自動車"] = {"keywords": ["自動車", "EV"], "related_tickers": ["7203.T", "TSLA"]}
    expanded_sectors["金融"] = {"keywords": ["金融", "銀行"], "related_tickers": ["8306.T"]}

    expanded_config = dict(CONFIG)
    expanded_config["watchlist"] = watchlist_stocks
    expanded_config["macro_themes"] = CONFIG["macro_themes"] + [
        {"label": "自動車", "keywords": ["自動車", "自動車販売"]},
        {"label": "EV", "keywords": ["EV"]},
        {"label": "金融", "keywords": ["金融"]},
    ]
    expanded_config["causal_rules"] = CAUSAL_RULES + [
        {
            "trigger_keywords": ["自動車販売", "EV普及"],
            "theme": "自動車市況・EV",
            "beneficiary_sectors": ["自動車"],
            "negative_sectors": [],
            "durable": True,
            "note": "自動車・EVの生産販売動向は完成車メーカーの業績に直結しやすい",
        },
        {
            "trigger_keywords": ["利上げ"],
            "theme": "金融政策",
            "beneficiary_sectors": ["金融"],
            "negative_sectors": [],
            "durable": False,
            "note": "金利上昇は金融機関の利ざや改善に追い風となりやすい",
        },
    ]
    expanded_bundle = future_intelligence.build_future_intelligence(
        [], expanded_config, expanded_sectors, TICKER_LOOKUP
    )
    expanded_insufficient = sum(
        1 for w in expanded_bundle.watchlist_intelligence if w.judgment_label == "判断材料不足"
    )

    assert expanded_insufficient < baseline_insufficient
    assert expanded_insufficient == 0

    toyota = next(w for w in expanded_bundle.watchlist_intelligence if w.ticker == "7203.T")
    assert "自動車" in toyota.related_themes
    tesla = next(w for w in expanded_bundle.watchlist_intelligence if w.ticker == "TSLA")
    assert "自動車" in tesla.related_themes or "EV" in tesla.related_themes
    mufg = next(w for w in expanded_bundle.watchlist_intelligence if w.ticker == "8306.T")
    assert "金融" in mufg.related_themes


def test_existing_theme_diagnosis_unaffected_by_v1_9_additions():
    # v1.9のテーマ拡張が、既存のAIテーマの診断ロジック（Momentum/Lifecycle/
    # Catalyst/Risk/Confidence）に影響しないことを確認する（後方互換）
    headlines = [_headline("AI投資拡大が続く"), _headline("生成AI活用が広がる")]
    bundle = future_intelligence.build_future_intelligence(headlines, CONFIG, SECTORS, TICKER_LOOKUP)

    ai_diagnosis = next(td for td in bundle.theme_diagnosis if td.label == "AI")
    assert ai_diagnosis.momentum_score == 57
    assert ai_diagnosis.momentum_label == "加速"
    assert ai_diagnosis.phase == "急成長期"
    assert ai_diagnosis.continuity == "高い"


_FORBIDDEN_STOCK_INTELLIGENCE_PHRASES = (
    "目標株価",
    "PER",
    "EPS",
    "買い推奨",
    "売り推奨",
    "期待リターン",
    "強気目標",
    "利益率予想",
)


def test_stock_intelligence_generated_for_matched_watchlist_stock():
    headlines = [_headline("AI投資拡大が続く"), _headline("生成AI活用が広がる")]
    config = dict(CONFIG)
    config["watchlist"] = {"jp_stocks": [{"ticker": "8035.T", "name": "東京エレクトロン"}], "us_stocks": []}
    bundle = future_intelligence.build_future_intelligence(headlines, config, SECTORS, TICKER_LOOKUP)

    assert bundle.stock_intelligence
    tel = next(s for s in bundle.stock_intelligence if s.ticker == "8035.T")
    assert tel.related_themes == ["AI"]
    assert tel.primary_theme == "AI"
    assert tel.judgment_label in future_intelligence._WATCHLIST_JUDGMENT_LABELS

    # Watchlist Intelligenceとの整合性（同じ値をそのまま引き継ぐ）
    watch = next(w for w in bundle.watchlist_intelligence if w.ticker == "8035.T")
    assert tel.momentum_score == watch.momentum_score
    assert tel.momentum_label == watch.momentum_label
    assert tel.confidence_score == watch.confidence_score
    assert tel.judgment_label == watch.judgment_label


def test_stock_intelligence_not_generated_for_unmatched_watchlist_stock():
    # Stock Intelligenceは「Watchlist Intelligenceで一致した銘柄のみ」対象とする
    config = dict(CONFIG)
    config["watchlist"] = {"jp_stocks": [{"ticker": "9999.T", "name": "無関係株"}], "us_stocks": []}
    bundle = future_intelligence.build_future_intelligence([], config, SECTORS, TICKER_LOOKUP)

    assert bundle.stock_intelligence == []
    unmatched = next(w for w in bundle.watchlist_intelligence if w.ticker == "9999.T")
    assert unmatched.judgment_label == "判断材料不足"


def test_stock_intelligence_shows_related_theme_count_and_cross_theme_chain():
    config = dict(CONFIG)
    config["theme_relations"] = {"AI": ["防衛", "宇宙"]}
    config["watchlist"] = {"jp_stocks": [{"ticker": "8035.T", "name": "東京エレクトロン"}], "us_stocks": []}
    headlines = [_headline("AI投資拡大が続く"), _headline("生成AI活用が広がる")]
    bundle = future_intelligence.build_future_intelligence(headlines, config, SECTORS, TICKER_LOOKUP)

    tel = next(s for s in bundle.stock_intelligence if s.ticker == "8035.T")
    assert len(tel.related_themes) == 1  # 関連テーマ数
    assert tel.cross_theme_chain == ["防衛", "宇宙"]  # Cross Theme Mapping（theme_relations）


def test_stock_intelligence_investment_story_uses_only_existing_signals_no_forecast_language():
    headlines = [_headline("AI投資拡大が続く"), _headline("生成AI活用が広がる")]
    config = dict(CONFIG)
    config["watchlist"] = {"jp_stocks": [{"ticker": "8035.T", "name": "東京エレクトロン"}], "us_stocks": []}
    bundle = future_intelligence.build_future_intelligence(headlines, config, SECTORS, TICKER_LOOKUP)

    tel = next(s for s in bundle.stock_intelligence if s.ticker == "8035.T")
    assert tel.investment_story
    assert tel.investment_story[0] == tel.primary_theme
    assert tel.why_long_term
    assert tel.watch_events

    story_text = " ".join(tel.investment_story + [tel.why_long_term] + tel.watch_events)
    for phrase in _FORBIDDEN_STOCK_INTELLIGENCE_PHRASES:
        assert phrase not in story_text
    assert "円" not in story_text
    assert "億" not in story_text


def test_stock_intelligence_appears_in_markdown_html_and_mobile_output():
    from src.report.mobile_builder import _section_future_intelligence

    headlines = [_headline("AI投資拡大が続く"), _headline("生成AI活用が広がる")]
    config = dict(CONFIG)
    config["watchlist"] = {"jp_stocks": [{"ticker": "8035.T", "name": "東京エレクトロン"}], "us_stocks": []}
    bundle = future_intelligence.build_future_intelligence(headlines, config, SECTORS, TICKER_LOOKUP)

    markdown_text = render_future_intelligence(bundle)
    assert "Stock Intelligence" in markdown_text
    assert "東京エレクトロン" in markdown_text
    assert "投資ストーリー" in markdown_text
    assert "なぜ長期で見るのか" in markdown_text
    assert "今後注目するイベント" in markdown_text

    html_text = _future_intelligence_html(bundle)
    assert "Stock Intelligence" in html_text

    mobile_text = _section_future_intelligence(bundle)
    assert "Stock Intelligence" in mobile_text


def test_existing_watchlist_intelligence_unaffected_by_stock_intelligence_addition():
    # v2.0のStock Intelligence追加が既存のWatchlist Intelligenceの
    # 出力内容（judgment_label等）を変えないことを確認する（後方互換）
    headlines = [_headline("防衛費増額の議論が進展")]
    config = dict(CONFIG)
    config["watchlist"] = {"jp_stocks": [{"ticker": "7012.T", "name": "川崎重工業"}], "us_stocks": []}
    bundle = future_intelligence.build_future_intelligence(headlines, config, SECTORS, TICKER_LOOKUP)

    defense_watch = next(w for w in bundle.watchlist_intelligence if w.ticker == "7012.T")
    assert defense_watch.related_themes == ["防衛"]
    assert defense_watch.judgment_label in future_intelligence._WATCHLIST_JUDGMENT_LABELS


# --- v2.1: Information Architecture（5ブロック再構成）の表示確認 ---
# 新しい分析ロジックは追加せず、既存14項目を「Today's Future Signals /
# Theme Intelligence / Industry Intelligence / Stock Intelligence /
# Long-term Strategy」の5ブロックへ再構成しただけであることを確認する。

_FI_BLOCK_NAMES = [
    "Today's Future Signals",
    "Theme Intelligence",
    "Industry Intelligence",
    "Stock Intelligence",
    "Long-term Strategy",
]


def _v21_bundle():
    headlines = [_headline("AI投資拡大が続く"), _headline("防衛費増額の議論が進展")]
    config = dict(CONFIG)
    config["watchlist"] = {"jp_stocks": [{"ticker": "8035.T", "name": "東京エレクトロン"}], "us_stocks": []}
    return future_intelligence.build_future_intelligence(headlines, config, SECTORS, TICKER_LOOKUP)


def test_v2_1_markdown_shows_all_five_blocks_in_order():
    bundle = _v21_bundle()
    markdown_text = render_future_intelligence(bundle)

    positions = [markdown_text.index(name) for name in _FI_BLOCK_NAMES]
    assert positions == sorted(positions)  # 世界→テーマ→業界→銘柄→長期戦略の順

    assert "Future Intelligence 目次" in markdown_text
    assert "今日もっとも重要な変化" in markdown_text
    assert "★★★★★" in markdown_text and "★★★★☆" in markdown_text


def test_v2_1_html_shows_all_five_blocks_as_color_coded_cards():
    bundle = _v21_bundle()
    html_text = _future_intelligence_html(bundle)

    for name in _FI_BLOCK_NAMES:
        assert name in html_text
    for anchor in ["fi-signals", "fi-theme", "fi-industry", "fi-stock", "fi-longterm"]:
        assert f"id='{anchor}'" in html_text
        assert f'href="#{anchor}"' in html_text
    for css_class in [
        "fi-block-signals",
        "fi-block-theme",
        "fi-block-industry",
        "fi-block-stock",
        "fi-block-longterm",
    ]:
        assert css_class in html_text


def test_v2_1_mobile_shows_all_five_blocks_with_bigger_headings_no_collapse():
    from src.report.mobile_builder import _section_future_intelligence

    bundle = _v21_bundle()
    mobile_text = _section_future_intelligence(bundle)

    for name in _FI_BLOCK_NAMES:
        assert f"### " in mobile_text  # 折りたたみではなく見出し（###）を使用
        assert name in mobile_text
    assert "<details" not in mobile_text and "<summary" not in mobile_text  # 折りたたみ禁止
    assert "Future Intelligence 目次" in mobile_text
