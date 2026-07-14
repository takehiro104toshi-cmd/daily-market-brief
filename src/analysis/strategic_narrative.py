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


# 改善③: 主因の総合影響度を上げる、カテゴリ別ニュースキーワード（News Ranking/Impact用）。
_NEWS_KW = {
    "semiconductor": ["半導体", "SOX", "AI", "エヌビディア", "Nvidia", "NVIDIA", "東京エレクトロン", "GPU"],
    "rates": ["金利", "FRB", "FOMC", "CPI", "PPI", "利上げ", "利下げ", "雇用統計", "国債", "インフレ"],
    "us_equity": ["米国株", "NYダウ", "ダウ", "NASDAQ", "ナスダック", "S&P", "米株"],
    "commodity_oil": ["原油", "OPEC", "WTI", "石油", "ガソリン"],
    "fx": ["円安", "円高", "為替", "ドル円", "ドル/円", "為替介入"],
    "volatility": ["地政学", "リスク回避", "急落", "急騰", "有事", "VIX"],
}


def _news_boost(category: str, news_ranking: list) -> Tuple[float, int, int]:
    """カテゴリに関連するニュース件数・最大Impact Scoreから、主因の総合影響度への加点を返す。
    戻り値: (boost, 関連件数, 最大impact_score)。News Ranking / News Impact の再利用。"""
    kws = _NEWS_KW.get(category, [])
    if not kws or not news_ranking:
        return 0.0, 0, 0
    matched = [it for it in news_ranking if any(kw in getattr(it.headline, "title", "") for kw in kws)]
    count = len(matched)
    max_impact = max((getattr(it, "impact_score", 0) or 0) for it in matched) if matched else 0
    boost = min(2.0, count * 0.6) + (max_impact / 100.0)
    return boost, count, max_impact


def _cross_boost(category: str, cross_market: list) -> float:
    """Cross Market の発火チェーンに当該カテゴリが登場していれば加点（再利用）。"""
    if not cross_market:
        return 0.0
    kw_map = {"semiconductor": "半導体", "rates": "金利", "fx": "円", "commodity_oil": "原油",
              "us_equity": "米", "volatility": "リスク"}
    kw = kw_map.get(category)
    if not kw:
        return 0.0
    for ch in cross_market:
        blob = getattr(ch, "trigger", "") + " ".join(getattr(ch, "nodes", []) or [])
        if kw in blob:
            return 0.7
    return 0.0


def _collect_factors(market: dict, news_ranking: Optional[list] = None,
                     cross_market: Optional[list] = None) -> Tuple[List[StrategicFactor], List[StrategicFactor]]:
    """各指標を direction 付き factor にし、negative（押し下げ）/ positive（下支え）へ
    一意に分類して返す（改善②④）。neutral は両方から除外。

    v3.6（改善③）: 主因の並び順は「値動きの大きさ（指数寄与）× 重み」に加えて、
    News Ranking / News Impact の関連件数・最大Impact、Cross Market への登場を合算した
    総合影響度で決める。★も総合影響度から付与する。"""
    news_ranking = news_ranking or []
    cross_market = cross_market or []
    downside: List[StrategicFactor] = []
    support: List[StrategicFactor] = []

    def _make(display, chg, salience, direction, pkey):
        boost, count, _impact = _news_boost(pkey, news_ranking)
        composite = salience + boost + _cross_boost(pkey, cross_market)
        note = _NOTE.get((pkey, direction), "")
        if count:
            note = (note + f"（関連ニュース{count}件）").strip()
        return StrategicFactor(label=f"{display} {fmt_change_compact(chg)}", stars=_stars(composite),
                               score=composite, note=note, direction=direction, category=pkey)

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
        factor = _make(display, chg, salience, direction, pkey)
        (support if direction == "positive" else downside).append(factor)

    # VIX（水準ベース）
    vix = _q(market, "indices", "VIX")
    if vix and vix.price is not None:
        if vix.price >= 20:
            sal = min(4.0, (vix.price - 20) / 5 + 1.2) + _cross_boost("volatility", cross_market)
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

# 改善②③: 市場心理は「本日の主因（ランキング1位）」の category/direction から決める。
# こうすることで市場心理と主因ランキングが必ず一致する（固定文章ではなく毎日変わる）。
_PSYCH_BY_TOP = {
    ("rates", "negative"): "市場は金利上昇を受けて、高PER・グロース銘柄の利益確定を優先しました。",
    ("rates", "positive"): "市場は金利低下を好感し、グロース株へ資金を戻しました。",
    ("commodity_oil", "negative"): "市場は原油高によるインフレ再燃・金利高止まりを警戒しました。",
    ("commodity_oil", "positive"): "市場は原油安によるインフレ懸念の後退を好感しました。",
    ("semiconductor", "negative"): "市場は半導体株への売りを優先し、値がさ・高PER株の持ち高を軽くしました。",
    ("semiconductor", "positive"): "市場は半導体株高を好感し、値がさ・グロース株へ資金を向けました。",
    ("us_equity", "negative"): "市場は米国株安を嫌気し、東京市場でも持ち高を軽くしました。",
    ("us_equity", "positive"): "市場は米国株高を好感し、景気敏感株へ資金を戻しました。",
    ("fx", "negative"): "市場は円高を受けて、輸出関連株の利益確定を優先しました。",
    ("fx", "positive"): "市場は円安を好感し、輸出関連株を見直しました。",
    ("volatility", "negative"): "市場はリスク回避姿勢を強め、資金を安全資産へ移す動きが優勢でした。",
    ("volatility", "positive"): "市場は落ち着いた投資家心理のもと、押し目を拾う姿勢がみられました。",
}


def _market_psychology(top_factor: Optional[StrategicFactor], nikkei_dir: str,
                       weekly_events: list) -> str:
    """今日の市場心理を、本日の主因（ランキング1位）から生成する（改善②）。

    決算集中は主因が弱いときのみ様子見として上書きする（主因と矛盾させない）。"""
    earnings_soon = any(("決算" in getattr(e, "label", "") or getattr(e, "category", "") == "決算") for e in (weekly_events or []))
    if top_factor is None:
        if earnings_soon:
            return "市場は決算発表を控え、結果を見極めたい様子見姿勢を強めました。"
        return "市場は強弱材料が拮抗し、方向感を欠く様子見が優勢でした。"
    if nikkei_dir == "flat" and earnings_soon:
        return "市場は決算発表を控え、結果を見極めたい様子見姿勢を強めました。"
    return _PSYCH_BY_TOP.get((top_factor.category, top_factor.direction),
                             "市場は強弱材料をにらみ、方向感を探る展開でした。")


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

def _has_cat(factors, category: str) -> bool:
    return any(f.category == category for f in factors)


def _contrast_clause(nikkei_dir: str, downside, support) -> str:
    """「◯◯にもかかわらず」の逆行（想定と違った点）を検出して返す（改善④⑥）。無ければ空。"""
    if nikkei_dir == "down" and _has_cat(support, "fx"):
        return "円安という輸出株の追い風がありながら"
    if nikkei_dir == "down" and _has_cat(support, "semiconductor"):
        return "SOX指数の上昇という支えがありながら"
    if nikkei_dir == "up" and _has_cat(downside, "rates"):
        return "米金利上昇という逆風がありながら"
    if nikkei_dir == "up" and _has_cat(downside, "commodity_oil"):
        return "原油高という重荷がありながら"
    return ""


def _sales_30sec(market: dict, nikkei_dir: str, downside, support, watch: List[str]) -> str:
    """営業向け30秒（改善⑥）。「◯◯にもかかわらず下落」など、お客様に話せる自然な説明。"""
    watch_txt = "と".join(watch[:2]) if watch else "米国株と為替"
    contrast = _contrast_clause(nikkei_dir, downside, support)
    if nikkei_dir == "down":
        cause = "と".join(_lead(downside)) or "売り材料"
        if contrast:
            return (f"今日は{contrast}、日経平均は下落しました。背景は{cause}です。"
                    f"支え材料より{cause}の影響が大きかったという見方です。今後は{watch_txt}が焦点になります。")
        return f"今日は{cause}が重荷となり、日経平均は下落しました。売り材料が勝った形です。今後は{watch_txt}が焦点になります。"
    if nikkei_dir == "up":
        cause = "と".join(_lead(support)) or "買い材料"
        if contrast:
            return (f"今日は{contrast}、日経平均は上昇しました。支えは{cause}です。"
                    f"重荷より{cause}の影響が大きかったという見方です。今後は{watch_txt}が焦点になります。")
        return f"今日は{cause}が支えとなり、日経平均は上昇しました。買い材料が優勢でした。今後は{watch_txt}が焦点になります。"
    return f"今日は強弱材料が交錯し、日経平均は方向感に乏しい展開でした。今後は{watch_txt}が焦点になります。"


# ---------- 改善⑩: ストラテジスト総括 ----------

def _strategist_summary(market: dict, nikkei_dir: str, downside, support,
                        psychology: str, watch: List[str], deep_chain: List[str]) -> str:
    """ストラテジスト総括（改善④⑧）。①何が起きたか②なぜ③市場は何を織り込んだか
    ④想定と違った点⑤明日確認、を「一本のストーリー」でつなぐ（200〜300字目安）。"""
    watch_txt = "、".join(watch) if watch else "米国株・為替・金利"
    # ② なぜ（deep_chain の中盤・原因側を短く）
    why = ""
    for node in deep_chain:
        if "インフレ" in node or "利下げ期待" in node or "金利" in node:
            why = node
            break
    if not why and deep_chain:
        why = deep_chain[0]
    contrast = _contrast_clause(nikkei_dir, downside, support)

    if nikkei_dir == "down":
        lead = "と".join(_lead(downside)) or "複数の売り材料"
        head = f"本日は{lead}が重荷となり、日経平均は下落しました。"
        why_clause = f"{why}が起点となり、高PER株への利益確定売りが優勢となりました。" if why else ""
        contrast_clause = f"{contrast}、下落材料の影響が上回った点は、やや想定より弱い動きでした。" if contrast else ""
    elif nikkei_dir == "up":
        lead = "と".join(_lead(support)) or "複数の買い材料"
        head = f"本日は{lead}が支えとなり、日経平均は上昇しました。"
        why_clause = f"{why}が追い風となり、値がさ・グロース株が買い戻されました。" if why else ""
        contrast_clause = f"{contrast}、上昇材料が優勢となった点は、底堅さを示しました。" if contrast else ""
    else:
        head = "本日は強弱材料が交錯し、日経平均は方向感に乏しい展開でした。"
        why_clause = ""
        contrast_clause = "上下双方の材料が拮抗し、大きな想定外はありませんでした。"

    return (
        f"{head}{why_clause}{psychology}{contrast_clause}"
        f"今後は{watch_txt}の方向性が焦点になります。"
        "（本コメントは公開データと既存の分析エンジンの機械的な組み合わせであり、断定的な予測・個別の売買推奨ではありません。）"
    )


# ---------- 改善①: ニュース→心理→金利→為替→セクター→日経 の深い因果 ----------

def _news_trigger(news_ranking: list) -> str:
    """ニュース見出しから、原因の起点になり得るキーワードを抽出（推測せず見出しにある語のみ）。"""
    triggers = [
        ("OPEC", "OPEC関連の報道"), ("減産", "減産報道"), ("CPI", "CPI（物価指標）の発表"),
        ("雇用統計", "米雇用統計"), ("FOMC", "FOMC関連の報道"), ("FRB", "FRB関連の発言・報道"),
        ("利上げ", "利上げ観測"), ("利下げ", "利下げ観測"), ("地政学", "地政学リスクの報道"),
    ]
    for it in (news_ranking or []):
        title = getattr(it.headline, "title", "")
        for kw, phrase in triggers:
            if kw in title:
                return phrase
    return ""


def _deep_causal_chain(market: dict, news_ranking: list, nikkei_dir: str) -> List[str]:
    """原因の原因まで遡る因果チェーン（改善①）。取得データで裏付く節だけを繋ぐ（推測禁止）。"""
    tnx = _q(market, "rates", "10年")
    wti = _q(market, "commodities", "WTI")
    usdjpy = _q(market, "forex", "米ドル/円")
    sox = _q(market, "indices", "SOX")
    nasdaq = _q(market, "indices", "ナスダック")
    rate_up = bool(tnx and tnx.change is not None and tnx.change > 0)
    rate_down = bool(tnx and tnx.change is not None and tnx.change < 0)
    oil_up = bool(wti and wti.change_pct is not None and wti.change_pct >= 1.5)
    yen_weak = bool(usdjpy and usdjpy.change_pct is not None and usdjpy.change_pct >= 0.2)
    yen_strong = bool(usdjpy and usdjpy.change_pct is not None and usdjpy.change_pct <= -0.2)
    sox_down = bool(sox and sox.change_pct is not None and sox.change_pct <= -1.0)
    sox_up = bool(sox and sox.change_pct is not None and sox.change_pct >= 1.0)
    nasdaq_down = bool(nasdaq and nasdaq.change_pct is not None and nasdaq.change_pct < 0)

    nodes: List[str] = []
    trig = _news_trigger(news_ranking)
    if trig:
        nodes.append(trig)
    if oil_up:
        nodes.append("原油高")
        nodes.append("インフレ再燃への警戒")
    if rate_up:
        if not oil_up:
            nodes.append("FRBの利下げ期待の後退")
        nodes.append("米長期金利の上昇")
        nodes.append("高PER（グロース）株の割引率上昇")
    elif rate_down:
        nodes.append("FRBの利下げ期待の高まり")
        nodes.append("米長期金利の低下")
        nodes.append("高PER（グロース）株の割引率低下")
    if yen_weak:
        nodes.append("日米金利差の意識からドル買い・円安")
    elif yen_strong:
        nodes.append("円高方向で輸出関連に逆風")
    if nasdaq_down or sox_down:
        nodes.append("米ハイテク・半導体株の下落")
    if sox_down:
        nodes.append("日本の半導体関連に売り波及")
    elif sox_up and nikkei_dir != "down":
        nodes.append("日本の半導体関連に買い波及")
    tail = {"down": "日経平均の下落", "up": "日経平均の上昇", "flat": "日経平均は方向感に乏しい展開"}[nikkei_dir]
    nodes.append(tail)
    # 重複除去（順序維持）
    seen = set()
    out = []
    for n in nodes:
        if n not in seen:
            seen.add(n)
            out.append(n)
    return out


# ---------- 改善⑦: 今日覚えること3つ ----------

def _key_points(nikkei_dir: str, ranking: List[StrategicFactor], watch: List[str]) -> List[str]:
    top = ranking[0] if ranking else None
    factor_txt = top.label if top else "強弱材料の交錯"
    seen_map = {
        "rates": "米10年金利の方向", "semiconductor": "半導体株（SOX指数）", "us_equity": "米国株の地合い",
        "fx": "為替（円相場）", "commodity_oil": "原油価格とインフレ", "volatility": "投資家心理（VIX）",
    }
    watching = seen_map.get(top.category, "米国株と為替の方向") if top else "米国株と為替の方向"
    tomorrow = "、".join(watch[:2]) if watch else "米国株と為替の方向"
    dir_word = {"down": "下落", "up": "上昇", "flat": "方向感の乏しさ"}[nikkei_dir]
    return [
        f"最大要因: {factor_txt}（日経平均の{dir_word}に最も効いた）",
        f"市場参加者が見ていたもの: {watching}",
        f"明日見るべきポイント: {tomorrow}",
    ]


# ---------- 改善⑨: 自己評価（ルールベースのセルフチェック） ----------

def _self_evaluation(psychology: str, ranking, deep_chain: List[str], sales_30sec: str,
                     strategist_summary: str) -> Tuple[int, List[str], List[str]]:
    checks: List[str] = []
    improvements: List[str] = []
    score = 0
    # 1) 市場心理が主因と一致（20点）
    top = ranking[0] if ranking else None
    expect = _PSYCH_BY_TOP.get((top.category, top.direction), "") if top else ""
    ok1 = bool(top) and psychology == expect
    if ok1 or (top is None):
        score += 20
        checks.append("市場心理と主因の一致: OK")
    else:
        checks.append("市場心理と主因の一致: NG")
        improvements.append("市場心理を主因ランキング1位のカテゴリから生成し直す。")
    # 2) 因果チェーンが飛んでいないか（20点: 4節以上＋日経で締める）
    ok2 = len(deep_chain) >= 4 and "日経平均" in deep_chain[-1]
    if ok2:
        score += 20
        checks.append("因果チェーンの連続性: OK")
    else:
        checks.append("因果チェーンの連続性: NG")
        improvements.append("ニュース→金利→為替→セクター→日経の中間ノードを補う。")
    # 3) 背景説明があるか（20点: 総括に「なぜ」＋今後）
    ok3 = ("起点" in strategist_summary or "警戒" in strategist_summary or "受けて" in strategist_summary
           or "追い風" in strategist_summary) and "今後" in strategist_summary
    if ok3:
        score += 20
        checks.append("背景説明の有無: OK")
    else:
        checks.append("背景説明の有無: NG")
        improvements.append("総括に『なぜそうなったか』と『明日確認すべき点』を必ず含める。")
    # 4) 営業マンが30秒で説明できるか（20点: 長さと焦点）
    ok4 = 40 <= len(sales_30sec) <= 170 and "焦点" in sales_30sec
    if ok4:
        score += 20
        checks.append("営業30秒の実用性: OK")
    else:
        checks.append("営業30秒の実用性: NG")
        improvements.append("営業説明を40〜170字に収め、今後の焦点を1文で締める。")
    # 5) ニュース要約でなくストーリーになっているか（20点: つなぎ言葉）
    connectives = ["受けて", "一方で", "ため", "優勢", "上回", "考えられます", "起点", "追い風"]
    ok5 = sum(1 for c in connectives if c in strategist_summary) >= 2
    if ok5:
        score += 20
        checks.append("ストーリー性（羅列でない）: OK")
    else:
        checks.append("ストーリー性（羅列でない）: NG")
        improvements.append("材料を接続詞でつなぎ、因果の一本の流れにする。")
    return score, checks, improvements


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
    news_ranking = news_ranking or []
    nikkei_dir, _nk_chg = _nikkei_direction(market)
    # 改善③: News Ranking / News Impact / Cross Market を合算した総合影響度で分類・順位付け
    downside, support = _collect_factors(market, news_ranking, cross_market)

    # 主因ランキング（改善③）: 日経の方向と一致する材料だけから作る
    if nikkei_dir == "down":
        ranking = downside[:3]
    elif nikkei_dir == "up":
        ranking = support[:3]
    else:  # flat: 強弱材料が交錯 → 総合影響度の大きい順に両方から
        ranking = sorted(downside + support, key=lambda x: -x.score)[:3]

    # 改善②: 市場心理は主因（ランキング1位）から生成（主因と必ず一致）
    top_factor = ranking[0] if ranking else None
    psychology = _market_psychology(top_factor, nikkei_dir, weekly_events or [])
    watch = _watch_terms(market, weekly_events or [])
    deep_chain = _deep_causal_chain(market, news_ranking, nikkei_dir)
    key_points = _key_points(nikkei_dir, ranking, watch)

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

    sales = _sales_30sec(market, nikkei_dir, downside, support, watch)
    summary = _strategist_summary(market, nikkei_dir, downside, support, psychology, watch, deep_chain)
    self_score, self_check, self_improve = _self_evaluation(psychology, ranking, deep_chain, sales, summary)

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
        sales_30sec=sales,
        strategist_summary=summary,
        reused_engines=reused,
        deep_causal_chain=deep_chain,
        key_points=key_points,
        self_score=self_score,
        self_check=self_check,
        self_improvement=self_improve,
    )
