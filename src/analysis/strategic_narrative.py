"""Strategic Narrative Engine（v3.5.2、v3.5.3で精度修正）— 朝会3分説明レベルの相場解説。

証券会社のストラテジストが朝会で「市場参加者が何を嫌気し、何を支えにした結果、日経平均が
どう動いたのか」を3分で説明する——そのレベルの相場解説を、既に算出済みの各エンジンの
結果だけから機械的に組み立てる。

利用する既存エンジンのみ:
  Market Regime / Cross Market / News Ranking / News Impact / Future Intelligence /
  Theme Momentum / Market Breadth / Analysis Confidence / Scenario / Watchlist /
  Macro Events(Weekly Events) / Market Data

v3.5.3の最重要ルール（改善①）: まず日経平均の方向を判定し、各材料を「日経平均にとって」
positive / negative / neutral に分類する。日経の方向と一致する材料だけを「本日の主因」に
選び、逆方向の材料は「下支え／重荷」に回す。同一材料が押し下げ・下支えの両方に出ない。

禁止事項（厳守）: 生成AIの作文／断定的な将来予測／新規データ取得／存在しないデータの捏造／
推測／個別の売買推奨。禁止表現（例:「金利上昇による原油高」「SOX上昇が押し下げ」
「円安が輸出株に逆風」）を出さないよう、テンプレートを方向整合で組む。
"""
from __future__ import annotations

from typing import List, Optional, Tuple

from ..report.format_utils import find_quote, fmt_change_compact
from .models import (
    MarketRegime,
    ScenarioForecast,
    StrategicFactor,
    StrategicNarrative,
    StrategicScenario,
)

# (探索キーワード, 市場カテゴリ, 表示名, category, semantic, 重み)
# semantic は方向判定ルール: risk_asset(上昇=positive) / rate(上昇=negative) /
# oil(上昇=negative) / fx_usdjpy(円安=positive) / gold(上昇=negative寄り)。
_DRIVER_SPECS = [
    ("SOX", "indices", "SOX指数（半導体）", "semiconductor", "risk_asset", 1.4),
    ("ナスダック", "indices", "NASDAQ", "us_equity", "risk_asset", 1.1),
    ("S&P500", "indices", "S&P500", "us_equity", "risk_asset", 1.0),
    ("ダウ", "indices", "NYダウ", "us_equity", "risk_asset", 0.8),
    ("10年", "rates", "米10年金利", "rates", "rate", 1.2),
    ("WTI", "commodities", "原油(WTI)", "commodity", "oil", 0.6),
    ("米ドル/円", "forex", "ドル円", "fx", "fx_usdjpy", 0.9),
    ("金先物", "commodities", "金(Gold)", "commodity", "gold", 0.5),
]

# 1行の説明（改善⑤: 不自然な因果を出さない安全なテンプレート）。(category, direction)→note
_NOTE = {
    ("rates", "negative"): "米金利上昇は、高PER株・グロース株のバリュエーションの重荷。",
    ("rates", "positive"): "米金利低下は、グロース株のバリュエーションを支援。",
    ("semiconductor", "negative"): "SOX下落は、半導体関連・値がさ株への売り波及要因。",
    ("semiconductor", "positive"): "SOX上昇は、半導体関連の下支え材料。",
    ("us_equity", "negative"): "米国株安は、東京市場の地合いを冷やす要因。",
    ("us_equity", "positive"): "米国株高は、東京市場の地合いを支える要因。",
    ("commodity_oil", "negative"): "原油高は、インフレ再燃・金利高止まりへの警戒材料。",
    ("commodity_oil", "positive"): "原油安は、インフレ懸念の後退材料。",
    ("fx", "positive"): "円安は、輸出関連の採算支援材料。",
    ("fx", "negative"): "円高は、輸出関連への逆風材料。",
    ("volatility", "positive"): "VIX20未満は、全面的なパニックではないことを示す下支え材料。",
    ("volatility", "negative"): "VIX警戒圏は、投資家心理の警戒を示す重荷。",
    ("commodity_gold", "negative"): "金の上昇は、リスク回避（安全資産選好）のサイン。",
}

# 一言・総括で使う短句。(category, direction)→短いフレーズ
_LEAD_PHRASE = {
    ("rates", "negative"): "米金利上昇",
    ("rates", "positive"): "米金利低下",
    ("commodity_oil", "negative"): "原油高によるインフレ警戒",
    ("commodity_oil", "positive"): "原油安",
    ("semiconductor", "negative"): "半導体株安",
    ("semiconductor", "positive"): "半導体株高",
    ("us_equity", "negative"): "米国株安",
    ("us_equity", "positive"): "米国株高",
    ("fx", "negative"): "円高",
    ("fx", "positive"): "円安",
    ("volatility", "negative"): "警戒感の高まり",
    ("volatility", "positive"): "落ち着いた投資家心理",
    ("commodity_gold", "negative"): "金上昇（リスク回避）",
}

# 「なぜ日経平均は動いたか」で使う説明句。(category, direction)→説明フレーズ
_CAUSE_PHRASE = {
    ("rates", "negative"): "米金利上昇によるグロース株への逆風",
    ("rates", "positive"): "米金利低下によるグロース株の支援",
    ("commodity_oil", "negative"): "原油高によるインフレ警戒",
    ("commodity_oil", "positive"): "原油安によるインフレ懸念の後退",
    ("semiconductor", "negative"): "半導体関連への売り波及",
    ("semiconductor", "positive"): "SOX指数の上昇による半導体関連の支え",
    ("us_equity", "negative"): "米国株安",
    ("us_equity", "positive"): "米国株高",
    ("fx", "negative"): "円高による輸出関連への逆風",
    ("fx", "positive"): "円安による輸出関連株への支援",
    ("volatility", "negative"): "投資家心理の警戒（VIX上昇）",
    ("volatility", "positive"): "落ち着いた投資家心理（VIX20未満）",
    ("commodity_gold", "negative"): "リスク回避（金の上昇）",
}


def _q(market: dict, category: str, keyword: str):
    return find_quote(market.get(category, []), keyword)


def _stars(salience: float) -> str:
    if salience >= 3.5:
        n = 5
    elif salience >= 2.2:
        n = 4
    elif salience >= 1.3:
        n = 3
    elif salience >= 0.6:
        n = 2
    else:
        n = 1
    return "★" * n + "☆" * (5 - n)


def _note_key(category: str) -> str:
    # 原油・金は同じ category="commodity" だが note/phrase は分ける
    return category


def _direction(semantic: str, chg: float) -> str:
    """材料の変化を「日経平均にとって」の方向へ写像する（改善②）。"""
    if chg == 0:
        return "neutral"
    if semantic == "risk_asset":
        return "positive" if chg > 0 else "negative"
    if semantic == "rate":
        return "negative" if chg > 0 else "positive"
    if semantic == "oil":
        return "negative" if chg > 0 else "positive"
    if semantic == "fx_usdjpy":
        return "positive" if chg > 0 else "negative"   # 円安(上昇)=positive
    if semantic == "gold":
        return "negative" if chg > 0 else "neutral"
    return "neutral"


def _phrase_cat(category: str, semantic: str) -> str:
    """note/phrase 辞書のキー用に、commodity を oil/gold に分ける。"""
    if semantic == "oil":
        return "commodity_oil"
    if semantic == "gold":
        return "commodity_gold"
    return category


def _collect_factors(market: dict) -> Tuple[List[StrategicFactor], List[StrategicFactor]]:
    """各指標を direction 付き factor にし、negative（押し下げ）/ positive（下支え）へ
    一意に分類して返す（改善②④）。neutral は両方から除外。"""
    downside: List[StrategicFactor] = []
    support: List[StrategicFactor] = []
    for keyword, category, display, cat_name, semantic, weight in _DRIVER_SPECS:
        q = _q(market, category, keyword)
        if q is None or q.change_pct is None:
            continue
        chg = q.change_pct
        salience = abs(chg) * weight
        if salience < 0.15:
            continue
        direction = _direction(semantic, chg)
        if direction == "neutral":
            continue
        pkey = _phrase_cat(cat_name, semantic)
        note = _NOTE.get((pkey, direction), "")
        factor = StrategicFactor(
            label=f"{display} {fmt_change_compact(chg)}",
            stars=_stars(salience), score=salience, note=note,
            direction=direction, category=pkey,
        )
        (support if direction == "positive" else downside).append(factor)

    # VIX（水準ベース）
    vix = _q(market, "indices", "VIX")
    if vix and vix.price is not None:
        if vix.price >= 20:
            sal = min(4.0, (vix.price - 20) / 5 + 1.2)
            downside.append(StrategicFactor(label=f"VIX {vix.price:g}（警戒圏）", stars=_stars(sal), score=sal,
                                            note=_NOTE[("volatility", "negative")], direction="negative", category="volatility"))
        else:
            support.append(StrategicFactor(label=f"VIX {vix.price:g}（20未満）", stars=_stars(1.4), score=1.4,
                                           note=_NOTE[("volatility", "positive")], direction="positive", category="volatility"))

    downside.sort(key=lambda x: -x.score)
    support.sort(key=lambda x: -x.score)
    return downside, support


def _nikkei_direction(market: dict) -> Tuple[str, Optional[float]]:
    """日経平均の方向を先に判定（改善①）。down / up / flat。"""
    n = _q(market, "indices", "日経")
    if n is None or n.change_pct is None:
        return "flat", None
    chg = n.change_pct
    if chg <= -0.5:
        return "down", chg
    if chg >= 0.5:
        return "up", chg
    return "flat", chg


def _lead(factors: List[StrategicFactor], n: int = 2) -> List[str]:
    out = []
    for f in factors[:n]:
        out.append(_LEAD_PHRASE.get((f.category, f.direction), f.label))
    return out


def _causes(factors: List[StrategicFactor], n: int = 3) -> List[str]:
    return [_CAUSE_PHRASE.get((f.category, f.direction), f.label) for f in factors[:n]]


# ---------- 改善⑥: 本日の一言 ----------

def _one_liner(nikkei_dir: str, downside, support) -> str:
    if nikkei_dir == "down":
        leads = _lead(downside)
        body = "と".join(leads) if leads else "複数の売り材料"
        return f"本日は{body}が重荷となり、日経平均は下落しました。"
    if nikkei_dir == "up":
        leads = _lead(support)
        body = "と".join(leads) if leads else "複数の買い材料"
        return f"本日は{body}が支えとなり、日経平均は上昇しました。"
    plus = (_lead(support, 1) or ["買い材料"])[0]
    minus = (_lead(downside, 1) or ["売り材料"])[0]
    return f"本日は{plus}と{minus}が交錯し、日経平均は方向感に乏しい展開でした。"


# ---------- 改善⑦: 今日の市場心理 ----------

def _market_psychology(market: dict, news_ranking: list, regime: Optional[MarketRegime],
                       weekly_events: list, nikkei_dir: str) -> str:
    tnx = _q(market, "rates", "10年")
    sox = _q(market, "indices", "SOX")
    nasdaq = _q(market, "indices", "ナスダック")
    wti = _q(market, "commodities", "WTI")
    vix = _q(market, "indices", "VIX")
    ai_news = any(("AI" in getattr(it.headline, "title", "") or "半導体" in getattr(it.headline, "title", "")) for it in (news_ranking or []))
    rates_up = bool(tnx and tnx.change is not None and tnx.change > 0)
    semis_down = bool(sox and sox.change_pct is not None and sox.change_pct < 0)
    nasdaq_down = bool(nasdaq and nasdaq.change_pct is not None and nasdaq.change_pct < 0)
    oil_up = bool(wti and wti.change_pct is not None and wti.change_pct >= 1.5)
    vix_high = bool(vix and vix.price is not None and vix.price >= 20)
    earnings_soon = any(("決算" in getattr(e, "label", "") or getattr(e, "category", "") == "決算") for e in (weekly_events or []))

    if rates_up and (semis_down or nasdaq_down) and ai_news:
        return "市場はAIそのものを悲観したというより、金利上昇を受けて高PER銘柄の利益確定を優先しました。"
    if rates_up and oil_up:
        return "市場はインフレ再燃・金利高止まりを警戒しました。"
    if vix_high:
        return "市場はリスク回避姿勢を強めました。"
    if earnings_soon:
        return "市場は決算発表を控え、結果を見極めたい様子見姿勢を強めました。"
    if ai_news and semis_down:
        return "AIテーマは継続していますが、短期的には半導体・高PER株への選別色が強まりました。"
    if regime is not None and regime.regime == "Risk On":
        return "市場はリスク選好を維持し、押し目を拾う姿勢がみられました。"
    if regime is not None and regime.regime == "Risk Off":
        return "市場はリスク回避に傾き、値がさ・高PER銘柄の持ち高調整を優先しました。"
    return "市場は強弱材料が拮抗し、方向感を欠く様子見が優勢でした。"


# ---------- 改善⑧: なぜ日経平均は動いたか ----------

def _nikkei_causation(nikkei_dir: str, downside, support) -> List[str]:
    neg = _causes(downside, 3)
    pos = _causes(support, 3)
    if nikkei_dir == "down":
        out = ["日経平均は下落しました。"]
        if neg:
            out.append(f"背景には、{'、'.join(neg)}がありました。")
        if pos:
            out.append(f"一方で、{'、'.join(pos)}は下支え材料でしたが、下落材料を打ち消すには至りませんでした。")
        return out
    if nikkei_dir == "up":
        out = ["日経平均は上昇しました。"]
        if pos:
            out.append(f"背景には、{'、'.join(pos)}がありました。")
        if neg:
            out.append(f"一方で、{'、'.join(neg)}は重荷でしたが、上昇材料が優勢となりました。")
        return out
    out = ["日経平均は方向感に乏しい展開でした。"]
    if pos or neg:
        pos_txt = "、".join(pos) if pos else "支え材料"
        neg_txt = "、".join(neg) if neg else "重荷材料"
        out.append(f"{pos_txt}が支えとなる一方、{neg_txt}が重荷となり、強弱材料が交錯しました。")
    return out


# ---------- 改善⑨: Cross Market（力関係） ----------

def _cross_market_prose(market: dict, nikkei_dir: str, downside, support) -> str:
    sox = _q(market, "indices", "SOX")
    sox_up = bool(sox and sox.change_pct is not None and sox.change_pct > 0)
    has_yen_weak = any(f.category == "fx" and f.direction == "positive" for f in support)
    top_neg = _lead(downside, 2)
    top_pos = _lead(support, 2)

    if nikkei_dir == "down":
        if sox_up:
            return ("SOX指数は上昇し半導体関連の支えとなりましたが、日経平均全体では"
                    f"{'や'.join(top_neg) if top_neg else '米金利上昇や米国株安'}の影響が上回り、下落しました。")
        base = "米長期金利の上昇はグロース株の重荷となりました。" if any(f.category == "rates" for f in downside) else ""
        support_clause = "一方で円安は輸出株を支えましたが、" if has_yen_weak else ""
        win = "、".join(top_neg) if top_neg else "米国株安と原油高への警戒"
        return f"{base}{support_clause}本日は{win}が勝り、日経平均は下落しました。"
    if nikkei_dir == "up":
        support_txt = "、".join(top_pos) if top_pos else "米国株高や円安"
        neg_clause = f"一方で{'、'.join(top_neg)}は重荷でしたが、" if top_neg else ""
        return f"{support_txt}が東京市場を支えました。{neg_clause}本日は買い材料が優勢となり、日経平均は上昇しました。"
    return "米国株や為替の支え材料と、金利・原油などの重荷材料が交錯し、日経平均は方向感に乏しい展開となりました。"


# ---------- 改善⑪: 営業向け30秒説明 ----------

def _sales_30sec(market: dict, nikkei_dir: str, downside, support, watch: List[str]) -> str:
    watch_txt = "、".join(watch[:2]) if watch else "米国株と為替"
    if nikkei_dir == "down":
        cause = "と".join(_lead(downside)) or "売り材料"
        sup = "、".join(_lead(support, 2))
        sup_clause = f"{sup}は支えでしたが、" if sup else ""
        return f"今日は{cause}が重荷となり、日経平均は下落しました。{sup_clause}売り材料が勝った形です。今後は{watch_txt}がポイントです。"
    if nikkei_dir == "up":
        cause = "と".join(_lead(support)) or "買い材料"
        neg = "、".join(_lead(downside, 2))
        neg_clause = f"{neg}は重荷でしたが、" if neg else ""
        return f"今日は{cause}が支えとなり、日経平均は上昇しました。{neg_clause}買い材料が優勢でした。今後は{watch_txt}がポイントです。"
    return f"今日は強弱材料が交錯し、日経平均は方向感に乏しい展開でした。今後は{watch_txt}がポイントです。"


# ---------- 改善⑩: ストラテジスト総括 ----------

def _strategist_summary(market: dict, nikkei_dir: str, downside, support,
                        psychology: str, watch: List[str]) -> str:
    watch_txt = "、".join(watch) if watch else "米国株・為替・金利"
    us = _q(market, "indices", "ダウ")
    nasdaq = _q(market, "indices", "ナスダック")
    us_ref = nasdaq if (nasdaq and nasdaq.change_pct is not None) else us

    if nikkei_dir == "down":
        head = f"本日は{'と'.join(_lead(downside)) or '複数の売り材料'}が重荷となり、日経平均は下落しました。"
        us_clause = "米国株が軟調だったことも東京市場の地合いを冷やしました。" if (us_ref and us_ref.change_pct is not None and us_ref.change_pct < 0) else ""
        sup = "、".join(_lead(support, 2))
        counter = f"一方で、{sup}は下支え材料でしたが、下落材料を打ち消すには至りませんでした。" if sup else ""
    elif nikkei_dir == "up":
        head = f"本日は{'と'.join(_lead(support)) or '複数の買い材料'}が支えとなり、日経平均は上昇しました。"
        us_clause = "米国株高も東京市場の地合いを支えました。" if (us_ref and us_ref.change_pct is not None and us_ref.change_pct > 0) else ""
        neg = "、".join(_lead(downside, 2))
        counter = f"一方で、{neg}は重荷でしたが、上昇材料が優勢となりました。" if neg else ""
    else:
        head = "本日は強弱材料が交錯し、日経平均は方向感に乏しい展開でした。"
        us_clause = ""
        counter = f"支え材料と重荷材料（{'、'.join(_lead(support, 1) + _lead(downside, 1))}）が拮抗しました。"
    return (
        f"{head}{us_clause}{counter}市場心理としては、{psychology}"
        f"今後は{watch_txt}を確認したい局面です。"
        "（本コメントは公開データと既存の分析エンジンの機械的な組み合わせであり、断定的な予測・個別の売買推奨ではありません。）"
    )


# ---------- 改善⑥（因果チェーン・金利ベース） ----------

def _causal_chain(market: dict) -> List[str]:
    tnx = _q(market, "rates", "10年")
    sox = _q(market, "indices", "SOX")
    if tnx and tnx.change is not None and tnx.change > 0:
        return [
            "FRBの利下げ期待が後退（米長期金利の上昇）",
            "高PER（グロース）銘柄の割引率が上昇",
            "AI・半導体株に利益確定売り",
            "指数寄与度の高い半導体株が日経平均を押し下げ",
        ]
    if tnx and tnx.change is not None and tnx.change < 0:
        return [
            "FRBの利下げ期待が高まり（米長期金利の低下）",
            "高PER（グロース）銘柄の割引率が低下",
            "AI・半導体株に買い戻し",
            "指数寄与度の高い半導体株が日経平均を押し上げ",
        ]
    if sox and sox.change_pct is not None and sox.change_pct <= -1.0:
        return ["米半導体株（SOX）の下落", "日本の半導体関連に売りが波及", "指数寄与度の高い半導体株が日経平均を押し下げ"]
    if sox and sox.change_pct is not None and sox.change_pct >= 1.0:
        return ["米半導体株（SOX）の上昇", "日本の半導体関連に買いが波及", "指数寄与度の高い半導体株が日経平均を押し上げ"]
    return ["本日は特定の一方向の材料は乏しく、複数の材料が拮抗（分析材料の範囲内）"]


def _scenarios(scenario: Optional[ScenarioForecast]) -> List[StrategicScenario]:
    bull = neutral = bear = 33
    if scenario is not None:
        bull, neutral, bear = scenario.bull_pct, scenario.neutral_pct, scenario.bear_pct
    ranked = sorted([("A", bull), ("B", bear), ("C", neutral)], key=lambda x: -x[1])
    label_map = {}
    for i, (key, _pct) in enumerate(ranked):
        label_map[key] = ["高", "中", "低"][i]
    return [
        StrategicScenario(label="シナリオA（反発）", probability_label=label_map["A"],
                          chain=["SOXが反発", "東京エレクトロンなど半導体関連が反発", "日経平均も反発"]),
        StrategicScenario(label="シナリオB（続落）", probability_label=label_map["B"],
                          chain=["米金利上昇が継続", "半導体・グロース株が続落", "日経平均も続落"]),
        StrategicScenario(label="シナリオC（決算主導）", probability_label=label_map["C"],
                          chain=["決算が市場予想を上回る", "テーマ株物色が再開", "指数は個別材料主導へ"]),
    ]


def _watch_terms(market: dict, weekly_events: list) -> List[str]:
    terms: List[str] = []
    if _q(market, "rates", "10年") is not None:
        terms.append("米10年金利")
    if _q(market, "indices", "SOX") is not None:
        terms.append("SOX指数")
    for e in (weekly_events or [])[:1]:
        lbl = getattr(e, "label", "")
        if lbl:
            terms.append(lbl)
    if not terms:
        terms.append("米国株と為替の方向")
    return terms[:3]


def build_strategic_narrative(
    market: dict,
    regime: Optional[MarketRegime],
    cross_market: Optional[list],
    news_ranking: Optional[list],
    future_intelligence,
    market_breadth,
    analysis_confidence,
    scenario: Optional[ScenarioForecast],
    scenarios_v2: Optional[list],
    watchlist_quicklist: Optional[dict],
    weekly_events: Optional[list],
) -> StrategicNarrative:
    """既存エンジンの結果だけから、朝会3分説明レベルの相場解説を組み立てる。

    v3.5.3: 日経平均の方向を先に判定し、材料を方向整合で分類。主因ランキングは
    日経の方向と一致する材料だけから作り、押し下げ・下支えの重複を排除する。
    """
    market = market or {}
    nikkei_dir, _nk_chg = _nikkei_direction(market)
    downside, support = _collect_factors(market)

    # 主因ランキング（改善③）: 日経の方向と一致する材料だけから作る
    if nikkei_dir == "down":
        ranking = downside[:3]
    elif nikkei_dir == "up":
        ranking = support[:3]
    else:  # flat: 強弱材料が交錯 → 寄与の大きい順に両方から
        ranking = sorted(downside + support, key=lambda x: -x.score)[:3]

    psychology = _market_psychology(market, news_ranking or [], regime, weekly_events or [], nikkei_dir)
    watch = _watch_terms(market, weekly_events or [])

    reused = ["Market Data"]
    if regime is not None:
        reused.append("Market Regime")
    if cross_market:
        reused.append("Cross Market")
    if news_ranking:
        reused.append("News Ranking / News Impact")
    if future_intelligence and getattr(future_intelligence, "theme_momentum", []):
        reused.append("Future Intelligence / Theme Momentum")
    if market_breadth is not None:
        reused.append("Market Breadth")
    if analysis_confidence is not None:
        reused.append("Analysis Confidence")
    if scenario is not None or scenarios_v2:
        reused.append("Scenario")
    if watchlist_quicklist:
        reused.append("Watchlist")
    if weekly_events:
        reused.append("Macro Events")

    return StrategicNarrative(
        one_liner=_one_liner(nikkei_dir, downside, support),
        market_psychology=psychology,
        causal_chain=_causal_chain(market),
        driver_ranking=ranking,
        downside_factors=downside,
        support_factors=support,
        scenarios=_scenarios(scenario),
        nikkei_causation=_nikkei_causation(nikkei_dir, downside, support),
        cross_market_prose=_cross_market_prose(market, nikkei_dir, downside, support),
        sales_30sec=_sales_30sec(market, nikkei_dir, downside, support, watch),
        strategist_summary=_strategist_summary(market, nikkei_dir, downside, support, psychology, watch),
        reused_engines=reused,
    )
