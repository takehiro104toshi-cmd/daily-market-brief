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


def _watch_points(market: dict, weekly_events: List[WeeklyEventEntry], future_intelligence) -> List[str]:
    points: List[str] = []
    for e in (weekly_events or [])[:3]:
        cd = getattr(e, "countdown_text", "") or getattr(e, "date_str", "")
        points.append(f"イベント: {e.label}（{cd}）")
    # 常に見るべき定点
    points.append("米10年金利の方向（上昇継続ならグロース株の重荷）")
    points.append("SOX（半導体指数）の強弱（テーマ株の物色の先行指標）")
    points.append("ドル円の水準（輸出採算・海外投資家の日本株評価に影響）")
    # 決算接近（Future Intelligenceが持っていれば注目イベントを流用）
    return points


def _views(market: dict, regime: Optional[MarketRegime]) -> tuple:
    """短期・中期の見立てを条件分岐（if条件）で返す（断定はしない）。"""
    vix = _quote(market, "indices", "VIX")
    vix_price = vix.price if (vix and vix.price is not None) else None
    near = (
        "米金利がさらに上昇しSOXが弱含む場合、グロース株・半導体株には警戒。"
        + ("VIXが20未満で踏みとどまれば、全面リスクオフではなく個別調整に留まる可能性。" if (vix_price is not None and vix_price < 20) else "VIXが高止まりする場合はリスク回避が優勢になりやすい。")
    )
    medium = (
        "AI・半導体など構造テーマのニュースが継続する場合、中長期テーマは残りやすい一方、"
        "短期は選別色（利食い・循環物色）が強まりやすい。金利・決算の確認が重要。"
    )
    return near, medium


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

    near, medium = _views(market, regime)
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
