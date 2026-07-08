"""Strategic Narrative Engine（v3.5.2）— 朝会3分説明レベルの相場解説を組み立てる。

証券会社のストラテジストが朝会で「今日はなぜこう動いたのか／市場は何を織り込んだのか
／どの材料が一番効いたのか／今後どこを見るか」を3分で説明する——そのレベルの相場解説を、
既に算出済みの各エンジンの結果だけから機械的に組み立てる新エンジン。

利用する既存エンジンのみ:
  Market Regime / Cross Market / News Ranking / News Impact / Future Intelligence /
  Theme Momentum / Market Breadth / Analysis Confidence / Scenario / Watchlist /
  Macro Events(Weekly Events) / Market Data

禁止事項（厳守）: 生成AIによる作文／断定的な将来予測／新規データ取得／存在しない
データの捏造／推測／個別の売買推奨（買うべき/売るべき）。すべて公開データと既存
エンジン結果の機械的な組み合わせ（テンプレート）であり、条件が満たされた分岐のみ出力する。
"""
from __future__ import annotations

from typing import List, Optional

from ..report.format_utils import find_quote, fmt_change_compact
from .models import (
    MarketRegime,
    ScenarioForecast,
    StrategicFactor,
    StrategicNarrative,
    StrategicScenario,
)

# (探索キーワード, 市場カテゴリ, 表示名, rising_supports, 重み)
# rising_supports=True: 上昇は日本株の「下支え」／False: 上昇は「押し下げ」要因。
_DRIVER_SPECS = [
    ("SOX", "indices", "SOX指数（半導体）", True, 1.4),
    ("ナスダック", "indices", "NASDAQ", True, 1.1),
    ("S&P500", "indices", "S&P500", True, 1.0),
    ("ダウ", "indices", "NYダウ", True, 0.8),
    ("10年", "rates", "米10年金利", False, 1.2),
    ("WTI", "commodities", "原油(WTI)", False, 0.6),
    ("米ドル/円", "forex", "ドル円", True, 1.0),
]


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


def _driver_note(keyword: str, chg: float, supports: bool) -> str:
    up = chg >= 0
    if "SOX" in keyword:
        return f"半導体指数の{'上昇' if up else '下落'}。指数寄与の大きい半導体関連に{'買い' if up else '売り'}が波及。"
    if "10年" in keyword:
        return f"米長期金利の{'上昇' if up else '低下'}。高PER（グロース）銘柄の割引率{'上昇' if up else '低下'}要因。"
    if "ナスダック" in keyword or "S&P500" in keyword or "ダウ" in keyword:
        return f"米国株の{'堅調' if up else '軟調'}。東京市場の地合いへ波及。"
    if "WTI" in keyword:
        return f"原油{'高' if up else '安'}。インフレ{'警戒' if up else '一服'}材料。"
    if "米ドル/円" in keyword:
        return f"{'円安' if up else '円高'}進行。輸出採算の{'追い風' if up else '逆風'}。"
    return ""


def _collect_drivers(market: dict):
    """各指標を「押し下げ／下支え」に仕分けし、寄与の大きさ（salience）付きで返す。"""
    downside: List[StrategicFactor] = []
    support: List[StrategicFactor] = []
    ranking: List[StrategicFactor] = []
    for keyword, category, label, rising_supports, weight in _DRIVER_SPECS:
        q = _q(market, category, keyword)
        if q is None or q.change_pct is None:
            continue
        chg = q.change_pct
        salience = abs(chg) * weight
        if salience < 0.15:
            continue  # ほぼ動いていない指標は主因に載せない
        supports = (chg >= 0) if rising_supports else (chg < 0)
        short_label = f"{label} {fmt_change_compact(chg)}"
        factor = StrategicFactor(label=short_label, stars=_stars(salience), score=salience, note=_driver_note(keyword, chg, supports))
        ranking.append(factor)
        (support if supports else downside).append(factor)

    # VIX（水準ベース）: 20以上は押し下げ材料、20未満は下支え材料
    vix = _q(market, "indices", "VIX")
    if vix and vix.price is not None:
        if vix.price >= 20:
            sal = min(4.0, (vix.price - 20) / 5 + 1.0)
            f = StrategicFactor(label=f"VIX {vix.price:g}（警戒圏）", stars=_stars(sal), score=sal, note="投資家心理の警戒。リスク回避が出やすい水準。")
            downside.append(f)
            ranking.append(f)
        else:
            f = StrategicFactor(label=f"VIX {vix.price:g}（20未満）", stars=_stars(1.5), score=1.5, note="投資家心理は落ち着き。全面リスクオフではない。")
            support.append(f)

    downside.sort(key=lambda x: -x.score)
    support.sort(key=lambda x: -x.score)
    ranking.sort(key=lambda x: -x.score)
    return downside, support, ranking


def _dir_word(market: dict) -> str:
    n = _q(market, "indices", "日経")
    if n is None or n.change_pct is None:
        return ""
    return "押し下げ" if n.change_pct < 0 else "押し上げ"


def _effect_phrase(downside: List[StrategicFactor], support: List[StrategicFactor]) -> str:
    lead = (downside or support)
    if not lead:
        return "強弱材料の拮抗"
    label = lead[0].label
    if "SOX" in label or "半導体" in label:
        return "半導体株安" if downside else "半導体株高"
    if "NASDAQ" in label:
        return "米ハイテク安" if downside else "米ハイテク高"
    if "金利" in label:
        return "金利上昇"
    if "原油" in label:
        return "原油高"
    if "ドル円" in label:
        return "円高" if downside else "円安"
    if "VIX" in label:
        return "リスク回避"
    return label


def _one_liner(market: dict, downside, support) -> str:
    dir_word = _dir_word(market)
    effect = _effect_phrase(downside, support)
    # 原因: 金利が動いていれば「金利上昇/低下による」を前置き
    tnx = _q(market, "rates", "10年")
    cause = ""
    if tnx and tnx.change is not None and tnx.change != 0 and effect not in ("金利上昇",):
        cause = "金利上昇による" if tnx.change > 0 else "金利低下による"
    body = f"{cause}{effect}" if cause else effect
    if dir_word:
        return f"本日は{body}が日経平均を{dir_word}た一日でした。"
    return f"本日は{body}が意識された一日でした。"


def _market_psychology(market: dict, news_ranking: list, regime: Optional[MarketRegime], weekly_events: list) -> str:
    tnx = _q(market, "rates", "10年")
    sox = _q(market, "indices", "SOX")
    vix = _q(market, "indices", "VIX")
    ai_news = any(("AI" in getattr(it.headline, "title", "") or "半導体" in getattr(it.headline, "title", "")) for it in (news_ranking or []))
    rates_up = bool(tnx and tnx.change is not None and tnx.change > 0)
    semis_down = bool(sox and sox.change_pct is not None and sox.change_pct < 0)
    earnings_soon = any(("決算" in getattr(e, "label", "") or getattr(e, "category", "") == "決算") for e in (weekly_events or []))

    if rates_up and semis_down and ai_news:
        return "市場はAIの成長性を悲観したのではなく、金利上昇を受けて高PER銘柄の利益確定を優先しました。"
    if vix and vix.price is not None and vix.price >= 25:
        return "市場はリスク回避姿勢を強め、資金を安全資産へ移す動きが優勢でした。"
    if earnings_soon:
        return "市場は決算発表を控え、結果を見極めたい様子見姿勢を強めています。"
    if regime is not None and regime.regime == "Risk On":
        return "市場はリスク選好を維持し、押し目を拾う姿勢がみられました。"
    if regime is not None and regime.regime == "Risk Off":
        return "市場はリスク回避に傾き、値がさ・高PER銘柄を中心に持ち高調整が優先されました。"
    return "市場は強弱材料が拮抗し、方向感を欠く様子見が優勢でした。"


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


def _nikkei_causation(market: dict) -> List[str]:
    """⑦ 日経→寄与度→業種→背景→海外→マクロ の順で「原因」まで遡る。"""
    nodes: List[str] = []
    n = _q(market, "indices", "日経")
    if n and n.change_pct is not None:
        nodes.append(f"日経平均 {fmt_change_compact(n.change_pct)}（結果）")
    sox = _q(market, "indices", "SOX")
    if sox and sox.change_pct is not None:
        d = "下落" if sox.change_pct < 0 else "上昇"
        nodes.append(f"寄与度の大きい半導体・値がさ株の{d}が指数を左右")
        nodes.append(f"業種では半導体・電子部品が{'軟調' if sox.change_pct < 0 else '堅調'}")
    tnx = _q(market, "rates", "10年")
    usdjpy = _q(market, "forex", "米ドル/円")
    bg = []
    if tnx and tnx.change is not None:
        bg.append(f"米長期金利の{'上昇' if tnx.change > 0 else '低下'}")
    if usdjpy and usdjpy.change_pct is not None:
        bg.append(f"{'円安' if usdjpy.change_pct >= 0 else '円高'}")
    if bg:
        nodes.append("背景に" + "と".join(bg))
    nasdaq = _q(market, "indices", "ナスダック")
    us = nasdaq if (nasdaq and nasdaq.change_pct is not None) else _q(market, "indices", "ダウ")
    if us and us.change_pct is not None:
        nodes.append(f"海外市場では米ハイテク（{us.name}）が{'軟調' if us.change_pct < 0 else '堅調'}")
    if tnx and tnx.change is not None:
        nodes.append(f"マクロではFRBの利下げ期待が{'後退' if tnx.change > 0 else '高まり'}")
    return nodes


def _cross_market_prose(market: dict) -> str:
    tnx = _q(market, "rates", "10年")
    usdjpy = _q(market, "forex", "米ドル/円")
    sox = _q(market, "indices", "SOX")
    rates_up = bool(tnx and tnx.change is not None and tnx.change > 0)
    yen_weak = bool(usdjpy and usdjpy.change_pct is not None and usdjpy.change_pct >= 0)
    semis_down = bool(sox and sox.change_pct is not None and sox.change_pct < 0)

    if rates_up and yen_weak and semis_down:
        return (
            "米長期金利の上昇を受けてドル買いが進み、円安となりました。"
            "通常であれば円安は輸出株の追い風ですが、今回は米半導体株（SOX）の急落が波及し、"
            "半導体株への売りが優勢となったため、円安の追い風効果を打ち消しました。"
        )
    parts = []
    if tnx and tnx.change is not None:
        parts.append(f"米長期金利は{'上昇' if tnx.change > 0 else '低下'}し、")
    if usdjpy and usdjpy.change_pct is not None:
        parts.append(f"為替は{'円安' if usdjpy.change_pct >= 0 else '円高'}方向に動きました。")
    if sox and sox.change_pct is not None:
        parts.append(f"米半導体株（SOX）は{fmt_change_compact(sox.change_pct)}となり、日本の半導体関連の値動きに影響しました。")
    return "".join(parts) if parts else "海外市場と国内市場の連動材料は限定的でした（取得できた範囲）。"


def _scenarios(scenario: Optional[ScenarioForecast]) -> List[StrategicScenario]:
    """⑥ 今後のシナリオA/B/C。確率ラベルはScenario Engineの配分から機械的に付与。"""
    bull = neutral = bear = 33
    if scenario is not None:
        bull, neutral, bear = scenario.bull_pct, scenario.neutral_pct, scenario.bear_pct
    # 3つの確率を高/中/低に写像
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


def _watch_terms(market: dict, weekly_events: list, future_intelligence) -> List[str]:
    terms: List[str] = []
    if _q(market, "indices", "SOX") is not None:
        terms.append("SOX指数の反発")
    if _q(market, "rates", "10年") is not None:
        terms.append("米10年金利の方向")
    for e in (weekly_events or [])[:1]:
        terms.append(f"{getattr(e, 'label', '')}")
    if not terms:
        terms.append("米国株と為替の方向")
    return [t for t in terms if t][:3]


def _sales_30sec(market: dict, downside, support, watch: List[str]) -> str:
    effect = _effect_phrase(downside, support)
    n = _q(market, "indices", "日経")
    nk = ""
    if n and n.change_pct is not None:
        nk = f"日経平均も{fmt_change_compact(n.change_pct)}{'下落' if n.change_pct < 0 else '上昇'}しました。"
    usdjpy = _q(market, "forex", "米ドル/円")
    fx = ""
    if usdjpy and usdjpy.change_pct is not None:
        fx = "円安は追い風でしたが、" if usdjpy.change_pct >= 0 else "円高が重荷となり、"
    watch_txt = "と".join(watch[:2]) if watch else "米国株と為替"
    return f"今日は{effect}が中心でした。{fx}指数寄与度の大きい半導体株の値動きが影響し、{nk}今後は{watch_txt}がポイントです。"


def _strategist_summary(market: dict, one_liner: str, psychology: str, causal_chain: List[str],
                        ranking: List[StrategicFactor], support: List[StrategicFactor], watch: List[str]) -> str:
    top = ranking[0].label if ranking else "複数材料"
    top_note = ranking[0].note if ranking else ""
    sup = support[0].label if support else "特筆材料なし"
    bg = causal_chain[0] if causal_chain else "複数の材料が拮抗"
    watch_txt = "、".join(watch) if watch else "米国株・為替・金利"
    return (
        f"{one_liner}背景には{bg}があり、{psychology}"
        f"最も効いた材料は{top}で、{top_note}一方で{sup}が下支えとなりました。"
        f"今後は{watch_txt}を確認したい局面です。"
        "（本コメントは公開データと既存の分析エンジンの機械的な組み合わせであり、"
        "断定的な予測・個別の売買推奨ではありません。）"
    )


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
    """既存エンジンの結果だけから、朝会3分説明レベルの相場解説を組み立てる。"""
    market = market or {}
    downside, support, ranking = _collect_drivers(market)

    one_liner = _one_liner(market, downside, support)
    psychology = _market_psychology(market, news_ranking or [], regime, weekly_events or [])
    causal = _causal_chain(market)
    watch = _watch_terms(market, weekly_events or [], future_intelligence)

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
        one_liner=one_liner,
        market_psychology=psychology,
        causal_chain=causal,
        driver_ranking=ranking[:3],
        downside_factors=downside,
        support_factors=support,
        scenarios=_scenarios(scenario),
        nikkei_causation=_nikkei_causation(market),
        cross_market_prose=_cross_market_prose(market),
        sales_30sec=_sales_30sec(market, downside, support, watch),
        strategist_summary=_strategist_summary(market, one_liner, psychology, causal, ranking, support, watch),
        reused_engines=reused,
    )
