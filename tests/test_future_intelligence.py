"""src/analysis/future_intelligence.py をネットワークなしで検証する。

Future Intelligence Engine（v1.0のグループA、v1.1のTheme Momentum Score /
Early Signal Detection）が、既存シグナル（本日の関連見出し件数・重要ニュース
との一致・durable_themes・causal_rules・恩恵銘柄ロジック）だけから、具体的な
残り年数等を捏造せずに定性的なラベルを導出することを確認する。
"""
from src.analysis import future_intelligence
from src.analysis.models import NewsRankingItem
from src.collectors.news import Headline

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


def _news_ranking_item(rank, title):
    return NewsRankingItem(rank=rank, stars="★★★☆☆", headline=_headline(title))


def test_momentum_score_combines_headline_density_causal_durable_and_top_news():
    headlines = [_headline("AI投資拡大が続く"), _headline("生成AI活用が広がる")]
    news_ranking_items = [_news_ranking_item(1, "AI投資拡大が続く")]
    bundle = future_intelligence.build_future_intelligence(
        headlines, CONFIG, SECTORS, TICKER_LOOKUP, news_ranking_items=news_ranking_items
    )

    ai_momentum = next(tm for tm in bundle.theme_momentum if tm.label == "AI")
    # headline_count=2 -> 20点、causal_rules該当 +20、durable_themes該当 +15、
    # 重要ニュース一致 +15 = 70点（急加速の閾値）
    assert ai_momentum.momentum_score == 70
    assert ai_momentum.momentum_label == "急加速"
    assert "残り" not in ai_momentum.reason


def test_momentum_score_is_zero_and_label_slows_down_with_no_signals():
    bundle = future_intelligence.build_future_intelligence([], CONFIG, SECTORS, TICKER_LOOKUP)

    space_momentum = next(tm for tm in bundle.theme_momentum if tm.label == "宇宙")
    assert space_momentum.momentum_score == 0
    assert space_momentum.momentum_label == "減速"


def test_early_signal_detected_for_low_volume_durable_theme_with_supply_chain():
    headlines = [_headline("防衛費増額の議論が進展")]  # 見出し1件のみ
    bundle = future_intelligence.build_future_intelligence(headlines, CONFIG, SECTORS, TICKER_LOOKUP)

    defense_signal = next(es for es in bundle.early_signals if es.label == "防衛")
    assert defense_signal.stars.count("★") == 4  # 基礎3 + durable分1（銘柄1件のため+1は付かない）
    assert "川崎重工業" in defense_signal.beneficiary_names
    assert "重工業・防衛" in defense_signal.related_sector


def test_early_signal_not_detected_when_headline_volume_is_high():
    # AIは見出し2件（EARLY_SIGNAL_MAX_HEADLINESの1件を超える）ため、
    # 他の条件を満たしていても初動シグナルには含めない
    headlines = [_headline("AI投資拡大が続く"), _headline("生成AI活用が広がる")]
    bundle = future_intelligence.build_future_intelligence(headlines, CONFIG, SECTORS, TICKER_LOOKUP)

    assert not any(es.label == "AI" for es in bundle.early_signals)
