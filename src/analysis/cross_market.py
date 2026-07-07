"""Cross Market Analysis（v3.2・改善2）— 世界の市場を「繋げて」多段で波及分析する。

既存の causal_chain.py（1本のマクロフロー＋短い3〜5本のチェーン）は変更せず、
より長い連鎖（例: 米金利↑→ドル高→円安→日本輸出株→半導体→設備投資→電力→電線）を
条件成立時のみ機械的に組み立てる追加エンジン。

生成AIの推測は使わない。各ルールは trigger（発火条件）を公開市場データ（前日比・
水準）で評価し、満たされた場合のみ人手で定義した波及ノード列（nodes）を返す。
config.yaml に cross_market_rules があれば追記ルールとして併用できる（無くても動く）。
"""
from __future__ import annotations

from typing import List, Optional

from ..report.format_utils import find_quote
from .models import CrossMarketChain


def _val(market: dict, category: str, keyword: str):
    q = find_quote(market.get(category, []), keyword)
    return q


def _rates_chain(market: dict) -> Optional[CrossMarketChain]:
    tnx = _val(market, "rates", "10年")
    if tnx is None or tnx.change is None:
        return None
    if tnx.change > 0:
        return CrossMarketChain(
            label="米金利上昇の波及",
            trigger=f"米10年金利が前日比{tnx.change:+.3f}上昇",
            nodes=["米金利↑", "日米金利差拡大", "ドル高圧力", "円安方向", "日本の輸出関連株に追い風",
                   "半導体・自動車", "設備投資の増加期待", "電力・インフラ需要", "電線・重電"],
            basis="金利上昇→ドル高→円安→輸出優位という一般的な波及経路（人手定義のテンプレート）。",
        )
    if tnx.change < 0:
        return CrossMarketChain(
            label="米金利低下の波及",
            trigger=f"米10年金利が前日比{tnx.change:+.3f}低下",
            nodes=["米金利↓", "日米金利差縮小", "ドル安圧力", "円高方向", "内需・ディフェンシブに追い風",
                   "小売・食品・通信", "グロース株の割引率低下期待", "半導体・ハイテク"],
            basis="金利低下→ドル安→円高→内需優位／割引率低下という一般的な波及経路。",
        )
    return None


def _vix_chain(market: dict) -> Optional[CrossMarketChain]:
    vix = _val(market, "indices", "VIX")
    if vix is None or vix.price is None:
        return None
    if vix.price >= 25:
        return CrossMarketChain(
            label="リスク回避の波及",
            trigger=f"VIXが{vix.price:.1f}と警戒的な水準",
            nodes=["VIX↑", "リスク回避姿勢の強まり", "株式から債券・金への資金逃避", "グロース・ハイテク軟調",
                   "半導体関連の重い展開", "円買い（安全資産需要）", "輸出株の重石"],
            basis="VIX上昇→リスクオフ→安全資産選好→ハイテク/輸出の重石という一般的な波及。",
        )
    return None


def _semis_chain(market: dict) -> Optional[CrossMarketChain]:
    sox = _val(market, "indices", "SOX")
    if sox is None or sox.change_pct is None:
        return None
    if sox.change_pct >= 1.0:
        return CrossMarketChain(
            label="半導体主導の波及",
            trigger=f"SOX指数が前日比{sox.change_pct:+.2f}%と堅調",
            nodes=["SOX↑", "AI・データセンター投資期待", "半導体製造装置への波及", "電力需要の増加",
                   "発電・送配電インフラ", "電線・素材", "建設・エンジニアリング"],
            basis="半導体高→AI設備投資→電力・インフラ→素材・建設というテーマ連鎖（人手定義）。",
        )
    if sox.change_pct <= -1.5:
        return CrossMarketChain(
            label="半導体調整の波及",
            trigger=f"SOX指数が前日比{sox.change_pct:+.2f}%と軟調",
            nodes=["SOX↓", "ハイテク物色の後退", "グロース株全般の重石", "日経平均のハイテク寄与低下"],
            basis="半導体安→ハイテク物色後退→指数の重石という一般的な波及。",
        )
    return None


def _oil_chain(market: dict) -> Optional[CrossMarketChain]:
    wti = _val(market, "commodities", "WTI")
    if wti is None or wti.change_pct is None:
        return None
    if wti.change_pct >= 2.0:
        return CrossMarketChain(
            label="原油高の波及",
            trigger=f"WTI原油が前日比{wti.change_pct:+.2f}%と上昇",
            nodes=["原油↑", "インフレ再燃懸念", "長期金利の上昇圧力", "資源・エネルギー関連に追い風",
                   "商社・石油", "運輸・素材のコスト増懸念"],
            basis="原油高→インフレ→金利上昇圧力／資源優位・コスト増という一般的な波及。",
        )
    return None


def _config_chains(market: dict, config: Optional[dict]) -> List[CrossMarketChain]:
    """config.yaml の cross_market_rules（任意）から追加ルールを評価する。

    ルール形式（すべて任意）:
      { label, category, keyword, direction: "up"/"down"/"level_gte"/"level_lte",
        threshold, nodes: [...], basis }
    direction が up/down のときは change/change_pct の符号、level_* のときは price を判定に使う。
    """
    rules = (config or {}).get("cross_market_rules") or []
    out: List[CrossMarketChain] = []
    for r in rules:
        if not isinstance(r, dict):
            continue
        q = find_quote(market.get(r.get("category", "indices"), []), r.get("keyword", ""))
        if q is None:
            continue
        direction = r.get("direction", "up")
        threshold = r.get("threshold", 0.0)
        ok = False
        if direction == "up" and q.change_pct is not None:
            ok = q.change_pct >= threshold
        elif direction == "down" and q.change_pct is not None:
            ok = q.change_pct <= -abs(threshold) if threshold else q.change_pct < 0
        elif direction == "level_gte" and q.price is not None:
            ok = q.price >= threshold
        elif direction == "level_lte" and q.price is not None:
            ok = q.price <= threshold
        if ok and r.get("nodes"):
            out.append(CrossMarketChain(
                label=r.get("label", "登録ルールの波及"),
                trigger=r.get("trigger", f"{r.get('keyword','')}が条件を満たしました"),
                nodes=list(r.get("nodes", [])),
                basis=r.get("basis", "config.yaml の cross_market_rules に登録された波及テンプレート。"),
            ))
    return out


def build_cross_market_chains(market: dict, config: Optional[dict] = None, max_chains: int = 6) -> List[CrossMarketChain]:
    """条件が成立した多段の波及チェーンだけを返す（0本もあり得る）。"""
    market = market or {}
    candidates = [
        _rates_chain(market),
        _vix_chain(market),
        _semis_chain(market),
        _oil_chain(market),
    ]
    chains = [c for c in candidates if c]
    chains.extend(_config_chains(market, config))
    return chains[:max_chains]
