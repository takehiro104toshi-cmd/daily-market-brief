"""米国株→金利→為替→日本株→業界→個別株の因果関係を矢印で整理する。

要件により、文章による長い説明ではなく「↓」でつないだ因果チェーンとして
表現する。各ノードの数値は実データ（事実）そのものであり、ノード間の
矢印でつなぐ解釈部分のみが AI分析（ルールベースの考察）にあたる。
"""
from __future__ import annotations

from typing import Dict, List, Optional

from ..collectors.market_data import Quote
from ..collectors.themes import SectorMatch
from ..report.format_utils import fmt_change, fmt_price, find_quote


def _us_equity_node(market: dict) -> str:
    dji = find_quote(market["indices"], "ダウ")
    vix = find_quote(market["indices"], "VIX")
    if dji is None or dji.change_pct is None:
        return "**米国株**: データ取得不可"
    tone = "リスク選好" if dji.change_pct >= 0 else "リスク回避"
    vix_txt = f"{vix.price:.2f}" if (vix and vix.price is not None) else "取得不可"
    return f"**米国株**: NYダウ {fmt_change(dji.change, dji.change_pct)}／VIX {vix_txt}（{tone}の目安）"


def _rate_node(market: dict) -> str:
    tnx = find_quote(market["rates"], "10年")
    if tnx is None or tnx.price is None:
        return "**金利**: データ取得不可"
    if tnx.change is not None and tnx.change > 0:
        note = "緩やかな金利上昇"
    elif tnx.change is not None and tnx.change < 0:
        note = "金利低下"
    else:
        note = "概ね横ばい"
    return f"**金利**: 米10年金利 {fmt_price(tnx.price)}%（前日比{fmt_change(tnx.change, tnx.change_pct)}、{note}）"


def _fx_node(market: dict) -> str:
    usdjpy = find_quote(market["forex"], "米ドル/円")
    if usdjpy is None or usdjpy.price is None:
        return "**為替**: データ取得不可"
    direction = "円安方向" if (usdjpy.change_pct or 0) >= 0 else "円高方向"
    return f"**為替**: 米ドル/円 {fmt_price(usdjpy.price)}円（前日比{fmt_change(usdjpy.change, usdjpy.change_pct)}、{direction}）"


def _jp_equity_node(market: dict) -> str:
    n225 = find_quote(market["indices"], "日経")
    if n225 is None or n225.price is None:
        return "**日本株**: データ取得不可"
    return f"**日本株**: 日経平均 {fmt_price(n225.price)}円（前日比{fmt_change(n225.change, n225.change_pct)}）"


def _sector_node(sector_matches: List[SectorMatch]) -> str:
    if not sector_matches:
        return "**業界**: 該当する業種シグナルは確認されませんでした（取得不可または該当なし）"
    ranked = sorted(sector_matches, key=lambda m: len(m.tailwind) - len(m.headwind), reverse=True)
    tailwind_labels = [m.label for m in ranked if len(m.tailwind) > len(m.headwind)][:2]
    headwind_labels = [m.label for m in ranked if len(m.headwind) > len(m.tailwind)][-2:]
    parts = []
    parts.append(f"追い風: {'、'.join(tailwind_labels) if tailwind_labels else '該当なし'}")
    parts.append(f"逆風: {'、'.join(headwind_labels) if headwind_labels else '該当なし'}")
    return "**業界**: " + "／".join(parts)


def _stock_node(sector_matches: List[SectorMatch], ticker_lookup: Dict[str, Quote]) -> str:
    if not sector_matches:
        return "**個別株**: 追い風業種が確認できないため、波及先の推定はできません（取得不可または該当なし）"
    ranked = sorted(sector_matches, key=lambda m: len(m.tailwind) - len(m.headwind), reverse=True)
    top = ranked[0]
    if len(top.tailwind) <= len(top.headwind):
        return "**個別株**: 本日は明確な追い風業種が確認されず、資金流入の波及シナリオは限定的とみられます"
    names = [ticker_lookup[t].name for t in top.related_tickers if t in ticker_lookup][:3]
    if not names:
        return f"**個別株**: 「{top.label}」に追い風が出ていますが、関連銘柄の価格データが確認できませんでした（取得不可）"
    return f"**個別株**: 「{top.label}」の追い風が{'、'.join(names)}などへ波及する可能性があります"


def build_causal_chain(market: dict, sector_matches: List[SectorMatch], ticker_lookup: Dict[str, Quote]) -> str:
    nodes = [
        _us_equity_node(market),
        _rate_node(market),
        _fx_node(market),
        _jp_equity_node(market),
        _sector_node(sector_matches),
        _stock_node(sector_matches, ticker_lookup),
    ]
    return "\n\n↓\n\n".join(nodes) + "\n"


# ---------------------------------------------------------------------------
# 「④ 因果チェーン」: 原因→影響→影響先を短い矢印チェーンで3〜5本示す。
# 上記 build_causal_chain（1本の大きなマクロフロー）とは別に、
# 個別の因果関係を短く切り出して並列に示すための機能。
# ---------------------------------------------------------------------------


def _chain(*nodes: str) -> str:
    return "\n↓\n".join(nodes)


def _rate_fx_chain(market: dict) -> Optional[str]:
    tnx = find_quote(market["rates"], "10年")
    if tnx is None or tnx.change is None:
        return None
    if tnx.change > 0:
        return _chain("米金利↑", "ドル高圧力", "円安方向", "輸出関連株に追い風", "自動車・精密機器")
    if tnx.change < 0:
        return _chain("米金利↓", "ドル安圧力", "円高方向", "輸入・内需関連株に追い風", "小売・食品")
    return None


def _vix_chain(market: dict) -> Optional[str]:
    vix = find_quote(market["indices"], "VIX")
    if vix is None or vix.price is None:
        return None
    if vix.price >= 20:
        return _chain("VIX上昇", "リスク回避姿勢の強まり", "資金の逃避", "ハイテク・グロース株軟調", "半導体関連")
    return _chain("VIXの落ち着き", "リスク選好姿勢", "資金流入余地", "グロース株堅調", "半導体関連")


def _us_equity_chain(market: dict) -> Optional[str]:
    dji = find_quote(market["indices"], "ダウ")
    if dji is None or dji.change_pct is None:
        return None
    if dji.change_pct >= 0:
        return _chain("NYダウ上昇", "リスク選好の継続", "東京市場の地合い改善期待", "主力株物色", "日経平均")
    return _chain("NYダウ下落", "リスク回避の広がり", "東京市場の重い展開への警戒", "主力株手控え", "日経平均")


def _sector_tailwind_chain(sector_matches: List[SectorMatch], ticker_lookup: Dict[str, Quote]) -> Optional[str]:
    if not sector_matches:
        return None
    ranked = sorted(sector_matches, key=lambda m: len(m.tailwind) - len(m.headwind), reverse=True)
    top = ranked[0]
    if len(top.tailwind) <= len(top.headwind):
        return None
    names = [ticker_lookup[t].name for t in top.related_tickers if t in ticker_lookup][:2]
    target = "、".join(names) if names else f"「{top.label}」関連銘柄"
    return _chain(f"「{top.label}」に追い風ニュース", "投資マネーの物色", "関連銘柄への資金流入", target)


def _theme_momentum_chain(theme_matches: List) -> Optional[str]:
    if not theme_matches:
        return None
    top = max(theme_matches, key=lambda m: len(m.headlines))
    if len(top.headlines) < 2:
        return None
    return _chain(f"「{top.label}」の話題化", "関連ニュースの増加", "個別銘柄への物色波及", "関連セクター全体への広がり")


def build_causal_chains(
    market: dict,
    sector_matches: List[SectorMatch],
    theme_matches: List,
    ticker_lookup: Dict[str, Quote],
    max_chains: int = 5,
) -> List[str]:
    """複数の短い因果チェーン（原因→影響→影響先）を3〜5本生成する。

    データが揃わない場合は該当チェーンを省き、生成可能なものだけを返す
    （0本になり得るが、その場合はレポート側で「取得不可」と明記する）。
    """
    candidates = [
        _rate_fx_chain(market),
        _vix_chain(market),
        _us_equity_chain(market),
        _sector_tailwind_chain(sector_matches, ticker_lookup),
        _theme_momentum_chain(theme_matches),
    ]
    chains = [c for c in candidates if c]
    return chains[:max_chains]
