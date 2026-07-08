"""Market Narrative（本日の相場総括・v3.5・改善1/2）— なぜ動いたかを機械的にまとめる。

ニュースと市場データ、そして既に算出済みの各エンジンの結果（Market Regime /
Cross Market / Future Intelligence / Executive Summary / Weekly Events / 異常値 /
Analysis Confidence）だけを組み合わせて、「今日の相場が“なぜ”動いたのか」「背景は
何か」「今後どう見ればよいか」を端的に整理する。

生成AIによる作文・断定的な将来予測・売買助言（買うべき/売るべき）は一切行わない。
今後の見立ては if条件（条件分岐）で表現し、取得していないデータは使わない。
"""
from __future__ import annotations

from typing import List, Optional

from ..report.format_utils import find_quote, fmt_change_compact
from .models import (
    AnalysisConfidence,
    CrossMarketChain,
    ExecutiveSummaryItem,
    MarketNarrativeSummary,
    MarketRegime,
    WeeklyEventEntry,
)

# 総括の「何が起きたか」に載せる主要指標（探索キーワード, 市場カテゴリ, 表示名）。
_MOVE_TARGETS = [
    ("日経", "indices", "日経平均"),
    ("ダウ", "indices", "NYダウ"),
    ("S&P500", "indices", "S&P500"),
    ("ナスダック", "indices", "NASDAQ"),
    ("SOX", "indices", "SOX（半導体）"),
    ("VIX", "indices", "VIX"),
    ("米ドル/円", "forex", "ドル円"),
    ("10年", "rates", "米10年金利"),
    ("WTI", "commodities", "原油(WTI)"),
    ("金先物", "commodities", "金(Gold)"),
]


def _quote(market: dict, category: str, keyword: str):
    return find_quote(market.get(category, []), keyword)


def _notable_drivers(market: dict) -> List[str]:
    """headline用に、特に目立った動き（金利上昇・半導体株安・円安・警戒感）を抽出する。"""
    drivers: List[str] = []
    tnx = _quote(market, "rates", "10年")
    if tnx and tnx.change is not None:
        if tnx.change > 0:
            drivers.append("米金利上昇")
        elif tnx.change < 0:
            drivers.append("米金利低下")
    sox = _quote(market, "indices", "SOX")
    if sox and sox.change_pct is not None:
        if sox.change_pct <= -1.0:
            drivers.append("半導体株安")
        elif sox.change_pct >= 1.0:
            drivers.append("半導体株高")
    usdjpy = _quote(market, "forex", "米ドル/円")
    if usdjpy and usdjpy.change_pct is not None:
        if usdjpy.change_pct >= 0.3:
            drivers.append("円安進行")
        elif usdjpy.change_pct <= -0.3:
            drivers.append("円高進行")
    vix = _quote(market, "indices", "VIX")
    if vix and vix.price is not None and vix.price >= 25:
        drivers.append("警戒感の高まり")
    return drivers


def _build_headline(market: dict, regime: Optional[MarketRegime]) -> str:
    tone = "方向感を欠く展開"
    if regime is not None:
        if regime.regime == "Risk On":
            tone = "リスクオン寄りの展開"
        elif regime.regime == "Risk Off":
            tone = "リスクオフ寄りの展開"
        elif regime.regime == "Neutral":
            tone = "中立（ニュートラル）の展開"
    drivers = _notable_drivers(market)[:2]
    if drivers:
        return f"{'と'.join(drivers)}を背景に、{tone}"
    return f"目立った単独材料は乏しく、{tone}"


def _market_move(market: dict) -> List[str]:
    moves: List[str] = []
    for keyword, category, label in _MOVE_TARGETS:
        q = _quote(market, category, keyword)
        if q is None or q.change_pct is None:
            continue
        moves.append(f"{label}: {fmt_change_compact(q.change_pct)}")
    return moves


def _main_causes(
    market: dict,
    news_ranking: list,
    cross_market: List[CrossMarketChain],
    regime: Optional[MarketRegime],
) -> List[str]:
    causes: List[str] = []
    # ① Cross Market の波及（発火した多段チェーンの起点→帰結）
    for ch in cross_market[:2]:
        if ch.nodes:
            causes.append(f"{ch.trigger}：{' → '.join(ch.nodes[:5])}")
    # ② AI/半導体テーマのニュースは多いがSOXが弱い、といった「テーマと株価の乖離」
    ai_news = any(("AI" in it.headline.title or "半導体" in it.headline.title) for it in (news_ranking or []))
    sox = _quote(market, "indices", "SOX")
    if ai_news and sox and sox.change_pct is not None and sox.change_pct <= -1.0:
        causes.append("AI・半導体関連ニュースは多いものの、SOX（半導体指数）は下落しており、テーマ内でも短期的な利食い・警戒感がうかがえます。")
    # ③ Regime の主要寄与（上位2指標）
    if regime is not None and regime.signals:
        top = sorted(regime.signals, key=lambda s: -abs(s.contribution))[:2]
        contrib = "、".join(f"{s.name}（{s.note}）" for s in top)
        if contrib:
            causes.append(f"地合いへの主な寄与: {contrib}")
    if not causes:
        causes.append("本日は明確な単独要因は特定できず、複数の材料が拮抗している状況です（分析材料不足）。")
    return causes


def _background_factors(market: dict, future_intelligence) -> List[str]:
    factors: List[str] = []
    tnx = _quote(market, "rates", "10年")
    if tnx and tnx.change is not None:
        factors.append(f"金利: 米10年金利は{'上昇' if tnx.change > 0 else ('低下' if tnx.change < 0 else '横ばい')}方向。グロース株の割引率に影響しやすい局面。")
    usdjpy = _quote(market, "forex", "米ドル/円")
    if usdjpy and usdjpy.change_pct is not None:
        factors.append(f"為替: ドル円は{'円安' if usdjpy.change_pct >= 0 else '円高'}方向。輸出関連の採算に影響。")
    vix = _quote(market, "indices", "VIX")
    if vix and vix.price is not None:
        factors.append(f"VIX: {vix.price:g}（{'警戒的' if vix.price >= 20 else '落ち着いた'}水準）。リスク許容度の目安。")
    # AI/半導体の勢い（Future Intelligence の Theme Momentum 上位）
    tm = getattr(future_intelligence, "theme_momentum", []) if future_intelligence else []
    if tm:
        top = max(tm, key=lambda t: t.momentum_score)
        factors.append(f"テーマ: 本日最も勢いのあるテーマは「{top.label}」（Momentum {top.momentum_score}/100）。中長期の構造テーマとして意識されやすい。")
    wti = _quote(market, "commodities", "WTI")
    if wti and wti.change_pct is not None and abs(wti.change_pct) >= 1.5:
        factors.append(f"原油: WTIは{fmt_change_compact(wti.change_pct)}。インフレ・資源関連への波及に注意。")
    return factors


def _lead_driver(market: dict) -> str:
    """今日の相場を主導した材料を一言で（半導体主導／金利主導／為替主導など）。"""
    sox = _quote(market, "indices", "SOX")
    tnx = _quote(market, "rates", "10年")
    usdjpy = _quote(market, "forex", "米ドル/円")
    if sox and sox.change_pct is not None and abs(sox.change_pct) >= 1.5:
        return "半導体主導"
    if tnx and tnx.change is not None and tnx.change != 0:
        return "金利主導"
    if usdjpy and usdjpy.change_pct is not None and abs(usdjpy.change_pct) >= 0.5:
        return "為替主導"
    return ""


def _conclusion(market: dict, regime: Optional[MarketRegime]) -> str:
    """① 今日の結論（1〜2文）。何が主因でどちらに動いたかを端的に。"""
    tone = "方向感を欠く"
    if regime is not None:
        tone = {"Risk On": "リスクオン寄り", "Risk Off": "リスクオフ寄り", "Neutral": "中立"}.get(regime.regime, tone)
    lead = _lead_driver(market)
    lead_txt = f"「{lead}の{tone}」" if lead else f"「{tone}」"

    nikkei = _quote(market, "indices", "日経")
    nk_dir = ""
    if nikkei and nikkei.change_pct is not None:
        nk_dir = "上昇" if nikkei.change_pct >= 0 else "下落"
    # 主因（悪材料 or 支援材料のトップ）
    drivers = _notable_drivers(market)
    driver_txt = "と".join(drivers[:2]) if drivers else "複数の材料が拮抗"

    s1 = f"本日は{lead_txt}の相場。"
    if nk_dir:
        s1 += f"{driver_txt}を背景に、日経平均は{nk_dir}しました。"
    else:
        s1 += f"{driver_txt}が意識される展開でした。"
    # ニュアンス（VIX水準）
    vix = _quote(market, "indices", "VIX")
    if vix and vix.price is not None:
        if vix.price < 20:
            s1 += "VIXは20未満で、全面的なパニックではありません。"
        elif vix.price >= 25:
            s1 += "VIXも高水準で、警戒感が強まっています。"
    return s1


def _nikkei_chain(market: dict) -> List[str]:
    """② なぜ日経平均は動いたか（米国株→金利→為替→日本株→セクター→銘柄の順）。"""
    chain: List[str] = []
    # 米国株
    nasdaq = _quote(market, "indices", "ナスダック")
    dji = _quote(market, "indices", "ダウ")
    us = nasdaq if (nasdaq and nasdaq.change_pct is not None) else dji
    if us and us.change_pct is not None:
        chain.append(f"米国株は{'堅調' if us.change_pct >= 0 else '軟調'}（{us.name} {fmt_change_compact(us.change_pct)}）")
    # 金利
    tnx = _quote(market, "rates", "10年")
    if tnx and tnx.change is not None:
        if tnx.change > 0:
            chain.append("米10年金利が上昇→グロース株の割引率上昇で逆風")
        elif tnx.change < 0:
            chain.append("米10年金利が低下→グロース株の割引率低下で追い風")
    # 為替
    usdjpy = _quote(market, "forex", "米ドル/円")
    if usdjpy and usdjpy.change_pct is not None:
        chain.append(f"ドル円は{'円安' if usdjpy.change_pct >= 0 else '円高'}方向（輸出採算に{'追い風' if usdjpy.change_pct >= 0 else '逆風'}）")
    # セクター（SOX）
    sox = _quote(market, "indices", "SOX")
    if sox and sox.change_pct is not None and abs(sox.change_pct) >= 1.0:
        if sox.change_pct < 0:
            chain.append(f"SOX{fmt_change_compact(sox.change_pct)}→日本の半導体関連に売り波及")
        else:
            chain.append(f"SOX{fmt_change_compact(sox.change_pct)}→日本の半導体関連に買い波及")
    # 日本株（帰結）
    nikkei = _quote(market, "indices", "日経")
    if nikkei and nikkei.change_pct is not None:
        chain.append(f"日経平均を{'押し下げ' if nikkei.change_pct < 0 else '押し上げ'}（{fmt_change_compact(nikkei.change_pct)}）")
    return chain


def _negative_factors(market: dict) -> List[str]:
    """③ 悪材料（本日の重荷）。取得できたデータのみ。"""
    out: List[str] = []
    tnx = _quote(market, "rates", "10年")
    if tnx and tnx.change is not None and tnx.change > 0:
        lvl = f"（{tnx.price:g}%前後）" if tnx.price is not None else ""
        out.append(f"米10年金利の上昇{lvl}")
    sox = _quote(market, "indices", "SOX")
    if sox and sox.change_pct is not None and sox.change_pct <= -1.0:
        out.append(f"SOX（半導体指数）安 {fmt_change_compact(sox.change_pct)}")
    nasdaq = _quote(market, "indices", "ナスダック")
    if nasdaq and nasdaq.change_pct is not None and nasdaq.change_pct < 0:
        out.append(f"NASDAQ安 {fmt_change_compact(nasdaq.change_pct)}")
    dji = _quote(market, "indices", "ダウ")
    if dji and dji.change_pct is not None and dji.change_pct < 0:
        out.append(f"NYダウ安 {fmt_change_compact(dji.change_pct)}")
    wti = _quote(market, "commodities", "WTI")
    if wti and wti.change_pct is not None and wti.change_pct >= 1.5:
        out.append("原油高によるインフレ警戒")
    vix = _quote(market, "indices", "VIX")
    if vix and vix.price is not None and vix.price >= 25:
        out.append(f"VIX高水準（{vix.price:g}）")
    return out


def _supportive_factors(market: dict, future_intelligence, weekly_events: List[WeeklyEventEntry]) -> List[str]:
    """④ 支えになる材料。取得できたデータのみ。"""
    out: List[str] = []
    usdjpy = _quote(market, "forex", "米ドル/円")
    if usdjpy and usdjpy.change_pct is not None and usdjpy.change_pct >= 0:
        out.append("ドル円は円安方向（輸出関連の採算を支援）")
    vix = _quote(market, "indices", "VIX")
    if vix and vix.price is not None and vix.price < 20:
        out.append("VIXは20未満（全面リスクオフではない）")
    tnx = _quote(market, "rates", "10年")
    if tnx and tnx.change is not None and tnx.change < 0:
        out.append("米10年金利の低下（グロース株の追い風）")
    tm = getattr(future_intelligence, "theme_momentum", []) if future_intelligence else []
    if tm:
        top = max(tm, key=lambda t: t.momentum_score)
        out.append(f"「{top.label}」テーマは中長期では継続（Momentum {top.momentum_score}/100）")
    if any("決算" in getattr(e, "label", "") or getattr(e, "category", "") == "決算" for e in (weekly_events or [])):
        out.append("決算イベントで個別材料は出やすい")
    if not out:
        out.append("目立った支援材料は確認できませんでした（分析材料の範囲内）")
    return out


def _watch_points(market: dict, weekly_events: List[WeeklyEventEntry], future_intelligence) -> List[str]:
    """⑤ 今後見るべきポイント（具体的な条件分岐で）。"""
    points: List[str] = []
    sox = _quote(market, "indices", "SOX")
    if sox is not None:
        points.append("SOX（半導体指数）が反発するか")
    tnx = _quote(market, "rates", "10年")
    if tnx and tnx.price is not None:
        points.append(f"米10年金利が{tnx.price:g}%台で定着するか")
    else:
        points.append("米10年金利の方向（上昇継続ならグロース株の重荷）")
    vix = _quote(market, "indices", "VIX")
    if vix and vix.price is not None:
        points.append(f"VIXが20を{'超える' if vix.price < 20 else '下回って推移する'}か")
    else:
        points.append("VIXが20を超えるか")
    usdjpy = _quote(market, "forex", "米ドル/円")
    if usdjpy is not None:
        points.append("ドル円の円安が輸出株を支えるか")
    for e in (weekly_events or [])[:2]:
        cd = getattr(e, "countdown_text", "") or getattr(e, "date_str", "")
        points.append(f"{e.label}（{cd}）で見方が変わるか")
    return points[:6]


def _views(market: dict, regime: Optional[MarketRegime], future_intelligence) -> tuple:
    """短期・中期・長期の見立てを条件分岐で返す（断定はしない・各3行以内）。"""
    sox = _quote(market, "indices", "SOX")
    sox_weak = bool(sox and sox.change_pct is not None and sox.change_pct < 0)
    near = (
        "SOXが弱い間は半導体・グロース株は慎重に確認。" if sox_weak
        else "半導体（SOX）の強さが続くかを確認しつつ、過熱には留意。"
    )
    medium = "AI投資テーマは残るが、金利上昇局面では銘柄選別が強まりやすい。"
    long_view = "AI・半導体・電力インフラなどの構造テーマは維持。ただし短期のバリュエーション調整には注意。"
    return near, medium, long_view


def _risk_factors(anomalies, future_intelligence, regime: Optional[MarketRegime]) -> List[str]:
    risks: List[str] = []
    for a in (anomalies or [])[:2]:
        risks.append(f"データ異常の可能性: {a.message}")
    diag = getattr(future_intelligence, "theme_diagnosis", []) if future_intelligence else []
    if diag:
        top = max(diag, key=lambda t: t.confidence_score)
        for r in (top.risks or [])[:2]:
            risks.append(f"{top.label}: {r}")
    if regime is not None and regime.regime == "Risk Off":
        risks.append("地合いがリスクオフ寄りのため、値動きが荒くなりやすい点に注意。")
    if not risks:
        risks.append("本日特筆すべき警戒材料は検知していません（分析材料の範囲内）。")
    return risks[:4]


def _implications(regime: Optional[MarketRegime], future_intelligence) -> List[str]:
    """投資判断への示唆（短期/中期/長期/注意）。売買助言はしない。"""
    diag = getattr(future_intelligence, "theme_diagnosis", []) if future_intelligence else []
    has_durable = any((getattr(t, "continuity", "") in ("高い", "中程度")) for t in diag)
    short_word = "慎重に確認" if (regime is not None and regime.regime == "Risk Off") else "値動きを確認"
    return [
        f"短期: {short_word}（地合い・金利・半導体の強弱を見極める局面）",
        "中期: テーマの継続性を確認（勢いが続くかをニュース件数・イベントで点検）",
        f"長期: {'構造テーマは維持されやすい' if has_durable else '構造テーマの有無を点検'}（単発材料に振らされない）",
        "注意: 金利・半導体・決算・イベント前後の変動",
    ]


def build_market_narrative(
    market: dict,
    news_ranking: list,
    executive_summary: List[ExecutiveSummaryItem],
    future_intelligence,
    regime: Optional[MarketRegime],
    cross_market: Optional[List[CrossMarketChain]],
    analysis_confidence: Optional[AnalysisConfidence],
    weekly_events: Optional[List[WeeklyEventEntry]],
    anomalies: Optional[list],
) -> MarketNarrativeSummary:
    """既存エンジンの結果だけから本日の相場総括を機械的に組み立てる。"""
    market = market or {}
    cross_market = cross_market or []

    cross_nodes: List[str] = []
    for ch in cross_market[:1]:
        if ch.nodes:
            cross_nodes = list(ch.nodes)

    near, medium, long_view = _views(market, regime, future_intelligence)
    conf_txt = ""
    if analysis_confidence is not None:
        conf_txt = f"Analysis Confidence {analysis_confidence.score}/100（{analysis_confidence.grade}・分析根拠の充実度。将来の的中確率ではありません）"

    source_items = ["市場データ", "重要ニュースランキング"]
    if regime is not None:
        source_items.append("Market Regime")
    if cross_market:
        source_items.append("Cross Market")
    if future_intelligence and getattr(future_intelligence, "theme_momentum", []):
        source_items.append("Future Intelligence")
    if weekly_events:
        source_items.append("今週の重要イベント")
    if analysis_confidence is not None:
        source_items.append("Analysis Confidence")

    return MarketNarrativeSummary(
        headline=_build_headline(market, regime),
        conclusion=_conclusion(market, regime),
        nikkei_chain=_nikkei_chain(market),
        negative_factors=_negative_factors(market),
        supportive_factors=_supportive_factors(market, future_intelligence, weekly_events or []),
        long_term_view=long_view,
        market_move=_market_move(market),
        main_causes=_main_causes(market, news_ranking, cross_market, regime),
        background_factors=_background_factors(market, future_intelligence),
        cross_market_chain=cross_nodes,
        watch_points=_watch_points(market, weekly_events or [], future_intelligence),
        near_term_view=near,
        medium_term_view=medium,
        risk_factors=_risk_factors(anomalies, future_intelligence, regime),
        implications=_implications(regime, future_intelligence),
        confidence=conf_txt,
        source_items=source_items,
    )
