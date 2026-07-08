"""v3.5.3 Strategic Narrative Engine Accuracy Fix をネットワークなしで検証する。

日経平均の方向と材料の方向を照合し、主因ランキング・押し下げ/下支え材料・因果表現の
矛盾をなくしたことを確認する（改善①〜⑬）。既存データのみ・生成AI/断定/売買助言なし。
"""
from src.analysis import strategic_narrative as SN
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


def _sn(market):
    return SN.build_strategic_narrative(market, None, [], [], None, None, None, None, [], {}, [])


def _labels(factors):
    return [f.label for f in factors]


# ---------- 改善①③: 日経の方向と主因の照合 ----------

def test_down_day_sox_up_is_support_not_driver():
    # 日経-2.11%, SOX+1.94% → SOXは下支え材料。主因ランキングに入れない。
    sn = _sn(_market(-2.11, sox_pct=1.94, rate_chg=0.05, nasdaq_pct=-1.0))
    assert any("SOX" in l for l in _labels(sn.support_factors))
    assert not any("SOX" in l for l in _labels(sn.downside_factors))
    assert not any("SOX" in f.label for f in sn.driver_ranking)
    # 主因は押し下げ材料（negative）だけ
    assert all(f.direction == "negative" for f in sn.driver_ranking)


def test_down_day_rate_up_is_downside_driver():
    sn = _sn(_market(-1.5, rate_chg=0.06))
    assert any("金利" in l for l in _labels(sn.downside_factors))
    assert any("金利" in f.label for f in sn.driver_ranking)


def test_up_day_sox_up_is_upside_driver():
    sn = _sn(_market(1.5, sox_pct=2.0, rate_chg=0.02))
    assert any("SOX" in l for l in _labels(sn.support_factors))
    assert any("SOX" in f.label for f in sn.driver_ranking)
    assert all(f.direction == "positive" for f in sn.driver_ranking)


def test_up_day_oil_high_is_burden_not_driver():
    # 日経+1.5%, 原油+2.2% → 原油高は重荷（downside）。上昇日の主因には入れない。
    sn = _sn(_market(1.5, sox_pct=2.0, wti_pct=2.2, rate_chg=0.01))
    assert any("原油" in l for l in _labels(sn.downside_factors))
    assert not any("原油" in f.label for f in sn.driver_ranking)


def test_flat_day_shows_crossing_materials():
    sn = _sn(_market(0.1, sox_pct=-0.5, rate_chg=0.03))
    assert "交錯" in sn.one_liner
    assert "方向感に乏しい" in " ".join(sn.nikkei_causation)


# ---------- 改善④: 重複禁止 ----------

def test_factor_not_in_both_downside_and_support():
    sn = _sn(_market(-2.0, sox_pct=1.94, rate_chg=0.05, wti_pct=2.0, nasdaq_pct=-1.0))
    down = set(_labels(sn.downside_factors))
    sup = set(_labels(sn.support_factors))
    assert down.isdisjoint(sup)
    # direction は必ず一意
    for f in sn.downside_factors:
        assert f.direction == "negative"
    for f in sn.support_factors:
        assert f.direction == "positive"


# ---------- 改善⑤: 禁止表現が出ない ----------

def test_no_forbidden_causal_expressions():
    blobs = []
    for m in [
        _market(-2.11, sox_pct=1.94, rate_chg=0.05, wti_pct=2.0, nasdaq_pct=-1.0),
        _market(1.5, sox_pct=2.0, rate_chg=0.02, wti_pct=2.2),
        _market(0.1, sox_pct=-0.5, rate_chg=0.03),
    ]:
        sn = _sn(m)
        blobs.append(" ".join(
            [sn.one_liner, sn.market_psychology, sn.cross_market_prose, sn.sales_30sec, sn.strategist_summary]
            + sn.nikkei_causation + [f.note for f in sn.downside_factors + sn.support_factors]
        ))
    blob = " ".join(blobs)
    for banned in ["金利上昇による原油高", "SOX上昇が", "円安が輸出株に逆風", "原油高がグロース株",
                   "VIX20未満がリスクオフ"]:
        assert banned not in blob, banned


# ---------- 改善⑥: 一言が日経方向と主因から ----------

def test_one_liner_matches_direction():
    down = _sn(_market(-1.8, rate_chg=0.05, nasdaq_pct=-1.0))
    assert "重荷" in down.one_liner and "下落しました" in down.one_liner
    up = _sn(_market(1.8, sox_pct=2.0))
    assert "支え" in up.one_liner and "上昇しました" in up.one_liner


# ---------- 改善⑧: なぜ日経は動いたか ----------

def test_nikkei_causation_down_has_background_and_counter():
    sn = _sn(_market(-2.0, sox_pct=1.5, rate_chg=0.05, nasdaq_pct=-1.0))
    joined = " ".join(sn.nikkei_causation)
    assert "日経平均は下落しました" in joined
    assert "背景には" in joined
    assert "打ち消すには至りませんでした" in joined  # 下支えがあったが下落材料が勝った


# ---------- 改善⑩⑪: 総括・30秒の方向整合 ----------

def test_summary_direction_consistent_on_down_day():
    sn = _sn(_market(-2.0, sox_pct=1.9, rate_chg=0.05, nasdaq_pct=-1.0))
    assert "下落しました" in sn.strategist_summary
    # 押し下げ主因（金利）が総括に出る、SOX上昇は「押し下げ主因」として出ない
    assert "米金利上昇" in sn.strategist_summary or "米国株安" in sn.strategist_summary


def test_sales_30sec_no_contradiction_on_down_day():
    sn = _sn(_market(-2.0, sox_pct=1.9, rate_chg=0.05, nasdaq_pct=-1.0))
    s = sn.sales_30sec
    assert "下落しました" in s
    assert "ポイント" in s
    # SOX上昇を「重荷」と書かない
    assert "SOX指数（半導体） +" not in s.split("重荷")[0] if "重荷" in s else True


# ---------- 改善⑬: 売買助言なし・後方互換 ----------

def test_no_buy_sell_advice_anywhere():
    sn = _sn(_market(-2.0, sox_pct=1.9, rate_chg=0.05, nasdaq_pct=-1.0))
    blob = " ".join(
        [sn.one_liner, sn.market_psychology, sn.cross_market_prose, sn.sales_30sec, sn.strategist_summary]
        + sn.nikkei_causation
    )
    assert "買うべき" not in blob and "売るべき" not in blob


def test_empty_market_safe():
    sn = _sn({"indices": [], "forex": [], "rates": [], "commodities": []})
    assert sn.one_liner
    assert isinstance(sn.downside_factors, list) and isinstance(sn.support_factors, list)
