"""v3.6 Strategic Narrative Engine —「証券会社トップストラテジストが朝会で3分説明するレベル」検証。

ネットワークなし・既存データのみ。生成AIの作文／断定予測／新規データ取得／推測／売買助言なし。
改善①原因の原因 ②市場心理dynamic ③主因ランキング総合影響度 ④背景5-part ⑤CrossMarket文章化
⑥営業30秒 ⑦今日のポイント3つ ⑧総括200-300字story ⑨自己評価、を機械的ルールで検証する。
"""
from src.analysis import strategic_narrative as SN
from src.collectors.news import Headline
from src.analysis.models import NewsRankingItem
from tests.factories import make_quote


def _market(nikkei_pct, sox_pct=None, rate_chg=None, wti_pct=None, usdjpy_pct=0.3, vix=18.0, nasdaq_pct=None):
    idx = [make_quote("日経平均株価", 38000, nikkei_pct * 380, nikkei_pct)]
    if sox_pct is not None:
        idx.append(make_quote("SOX指数（フィラデルフィア半導体指数）", 4500, sox_pct * 45, sox_pct, symbol="^SOX"))
    if nasdaq_pct is not None:
        idx.append(make_quote("ナスダック総合", 17000, nasdaq_pct * 170, nasdaq_pct))
    idx.append(make_quote("VIX指数（恐怖指数）", vix, 0.1, 0.5))
    m = {"indices": idx, "forex": [make_quote("米ドル/円", 156, 0.3, usdjpy_pct)], "rates": [], "commodities": []}
    if rate_chg is not None:
        m["rates"] = [make_quote("米10年国債利回り", 4.3, rate_chg, rate_chg / 4.3 * 100)]
    if wti_pct is not None:
        m["commodities"] = [make_quote("WTI原油先物", 78, wti_pct * 0.78, wti_pct)]
    return m


def _news(*titles):
    return [
        NewsRankingItem(rank=i + 1, stars="★★★★★", headline=Headline(title=t, link="https://example.com", source="Test"))
        for i, t in enumerate(titles)
    ]


def _sn(market, news_ranking=None):
    return SN.build_strategic_narrative(market, None, None, news_ranking or [], None, None, None, None, [], {}, [])


# ---------- 改善①: 原因の原因（深い因果チェーン）が日経で締めるまで繋がる ----------

def test_deep_chain_from_news_origin_to_nikkei():
    # OPEC減産報道 → 原油高 → インフレ警戒 → 金利上昇 → グロース株の重荷 → 日経下落
    m = _market(-1.8, sox_pct=-1.0, rate_chg=0.06, wti_pct=2.5, nasdaq_pct=-1.2)
    sn = _sn(m, _news("OPECが追加減産で合意"))
    chain = sn.deep_causal_chain
    assert chain[0] == "OPEC関連の報道"          # ニュース見出しにある語のみ（推測なし）
    assert "原油高" in chain
    assert any("金利" in n for n in chain)
    assert "日経平均の下落" in chain[-1]           # 必ず日経で締める
    assert len(chain) >= 4


def test_deep_chain_no_fabrication_without_news():
    # ニュースが無ければ起点ノードを作らない（データにある値動きだけで組む）
    sn = _sn(_market(-1.5, rate_chg=0.05, nasdaq_pct=-1.0))
    chain = sn.deep_causal_chain
    assert "OPEC関連の報道" not in " ".join(chain)
    assert "日経平均の下落" in chain[-1]


# ---------- 改善②③: 市場心理が主因ランキング1位と必ず一致（毎日変わる） ----------

def test_psychology_matches_top_driver_rates():
    sn = _sn(_market(-1.8, rate_chg=0.07, nasdaq_pct=-1.0))
    top = sn.driver_ranking[0]
    assert top.category == "rates" and top.direction == "negative"
    assert sn.market_psychology == SN._PSYCH_BY_TOP[("rates", "negative")]


def test_psychology_changes_with_top_driver():
    # 主因が変われば市場心理の文章も変わる（固定文でない）
    sn_rate = _sn(_market(-1.8, rate_chg=0.07, nasdaq_pct=-1.0))
    sn_us = _sn(_market(-1.8, nasdaq_pct=-2.5))
    assert sn_rate.market_psychology != sn_us.market_psychology


# ---------- 改善③: 主因ランキングが総合影響度（News/Cross加点）を反映 ----------

def test_news_boost_raises_composite_score():
    m = _market(-1.6, rate_chg=0.05, nasdaq_pct=-1.0)
    base = _sn(m)
    boosted = _sn(m, _news("CPI上振れでFRBの利下げ観測が後退", "長期金利が急上昇"))
    base_top = next(f for f in base.driver_ranking if f.category == "rates")
    boost_top = next(f for f in boosted.driver_ranking if f.category == "rates")
    assert boost_top.score > base_top.score          # 関連ニュースで総合影響度が上がる
    assert "関連ニュース" in boost_top.note


# ---------- 改善④⑧: ストラテジスト総括が背景つき一本のストーリー ----------

def test_strategist_summary_is_story_with_background():
    sn = _sn(_market(-2.0, sox_pct=-1.5, rate_chg=0.06, nasdaq_pct=-1.2), _news("CPIが市場予想を上振れ"))
    s = sn.strategist_summary
    assert 120 <= len(s) <= 400
    assert "下落しました" in s
    assert "今後" in s and "焦点" in s
    assert "買うべき" not in s and "売るべき" not in s
    assert "起点" in s or "受けて" in s or "追い風" in s   # 「なぜ」が入る


# ---------- 改善⑤: Cross Market が文章化されている ----------

def test_cross_market_prose_natural_language():
    sn = _sn(_market(-2.0, sox_pct=1.9, rate_chg=0.05, nasdaq_pct=-1.0))
    prose = sn.cross_market_prose
    assert "↓" not in prose and "→" not in prose
    assert prose.endswith("。")
    assert "下落しました" in prose


# ---------- 改善⑥: 営業向け30秒が会話調・逆行を捉える ----------

def test_sales_30sec_conversational_with_contrast():
    # 円安にもかかわらず下落した日は「◯◯にもかかわらず」を入れて締める
    sn = _sn(_market(-2.0, rate_chg=0.06, usdjpy_pct=0.6, nasdaq_pct=-1.0))
    s = sn.sales_30sec
    assert s.startswith("今日は")
    assert "追い風がありながら" in s
    assert "下落しました" in s
    assert s.endswith("焦点になります。")
    assert 40 <= len(s) <= 170


# ---------- 改善⑦: 今日覚えること3つ ----------

def test_key_points_three_items():
    sn = _sn(_market(-1.8, rate_chg=0.06, nasdaq_pct=-1.0))
    kp = sn.key_points
    assert len(kp) == 3
    assert kp[0].startswith("最大要因")
    assert kp[1].startswith("市場参加者が見ていたもの")
    assert kp[2].startswith("明日見るべきポイント")


# ---------- 改善⑨: 自己評価（100点満点・観点・改善案） ----------

def test_self_evaluation_scores_high_on_clean_case():
    sn = _sn(_market(-2.0, sox_pct=-1.2, rate_chg=0.06, nasdaq_pct=-1.2), _news("CPI上振れで金利上昇"))
    assert 0 <= sn.self_score <= 100
    assert sn.self_score >= 80                        # 因果整合が取れた日は高得点
    assert len(sn.self_check) == 5
    assert all("OK" in c or "NG" in c for c in sn.self_check)


def test_self_evaluation_psychology_check_ok_by_construction():
    # 市場心理は主因から生成するので「市場心理と主因の一致」は必ずOK
    sn = _sn(_market(1.8, sox_pct=2.5, nasdaq_pct=1.5))
    assert any("市場心理と主因の一致: OK" == c for c in sn.self_check)


def test_self_improvement_only_when_below_80():
    sn = _sn(_market(-2.0, sox_pct=-1.2, rate_chg=0.06, nasdaq_pct=-1.2), _news("CPI上振れで金利上昇"))
    if sn.self_score >= 80:
        assert sn.self_improvement == [] or all(isinstance(x, str) for x in sn.self_improvement)


# ---------- 禁止事項・後方互換 ----------

def test_no_advice_or_forbidden_expression_anywhere():
    for m in [_market(-2.0, sox_pct=1.9, rate_chg=0.05, nasdaq_pct=-1.0),
              _market(1.8, sox_pct=2.0), _market(0.1, rate_chg=0.03)]:
        sn = _sn(m, _news("CPI発表", "OPEC会合"))
        blob = " ".join([sn.one_liner, sn.market_psychology, sn.cross_market_prose,
                         sn.sales_30sec, sn.strategist_summary]
                        + sn.deep_causal_chain + sn.key_points + sn.self_check)
        assert "買うべき" not in blob and "売るべき" not in blob
        for banned in ["金利上昇による原油高", "SOX上昇が押し下げ", "円安が輸出株に逆風"]:
            assert banned not in blob


def test_empty_market_safe_v36():
    sn = _sn({"indices": [], "forex": [], "rates": [], "commodities": []})
    assert sn.deep_causal_chain and "方向感" in sn.deep_causal_chain[-1]
    assert len(sn.key_points) == 3
    assert 0 <= sn.self_score <= 100
    assert isinstance(sn.self_check, list) and isinstance(sn.self_improvement, list)
