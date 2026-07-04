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
