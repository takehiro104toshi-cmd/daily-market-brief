"""日経平均・ドル円・米国市場それぞれの短いシナリオ見立てをルールベースで算出する。

scenario.py の「強気/普通/弱気」全体シナリオとは別に、朝会で個別に触れやすいよう
指標ごとに1つずつ、方向感と根拠を1〜2文で示す。断定は避け「〜の可能性があります」
「〜が注目されています」等の言い回しに統一する。新たな数値取得は行わず、
main.pyから渡される既存の market/news データのみを使う。

v4では、既存の outlook / key_driver（総括的な短い見立て）に加えて、
「AIシナリオ」向けに各指標の強気/中立/弱気3シナリオ（bull_text/neutral_text/
bear_text）も算出する。指標全体のシナリオ（scenario.py）とは独立した、
指標ごとの簡易的な3分岐であり、確率は付与しない（定性的な見立てのみ）。
"""
from __future__ import annotations

from typing import List, Optional

from ..collectors.news import Headline
from ..report.format_utils import NOT_AVAILABLE, find_quote
from .models import InstrumentScenario

NOT_AVAILABLE_OUTLOOK = f"データを十分に取得できなかったため、方向感の判断材料が限られています（{NOT_AVAILABLE}）。"
NOT_AVAILABLE_BRANCH = f"データ不足のため、強気/中立/弱気シナリオを算出できませんでした（{NOT_AVAILABLE}）。"


def _nikkei_scenario(market: dict) -> InstrumentScenario:
    n225 = find_quote(market.get("indices", []), "日経")
    usdjpy = find_quote(market.get("forex", []), "米ドル/円")

    if n225 is None or n225.change_pct is None:
        return InstrumentScenario(
            label="日経平均",
            outlook=NOT_AVAILABLE_OUTLOOK,
            key_driver=NOT_AVAILABLE,
            bull_text=NOT_AVAILABLE_BRANCH,
            neutral_text=NOT_AVAILABLE_BRANCH,
            bear_text=NOT_AVAILABLE_BRANCH,
        )

    parts = []
    if n225.change_pct >= 0:
        parts.append(f"前日は{n225.change_pct:+.2f}%と底堅い動きでした。")
    else:
        parts.append(f"前日は{n225.change_pct:+.2f}%と軟調な動きでした。")

    if usdjpy is not None and usdjpy.change_pct is not None:
        if usdjpy.change_pct >= 0:
            parts.append("為替が円安方向にあり、輸出関連株には追い風となりやすい局面です。")
            driver = "米ドル/円（円安方向）"
        else:
            parts.append("為替が円高方向にあり、輸出関連株には逆風となりやすい局面です。")
            driver = "米ドル/円（円高方向）"
    else:
        parts.append(f"為替データが{NOT_AVAILABLE}のため、為替からの影響は確認できていません。")
        driver = NOT_AVAILABLE

    parts.append("方向感を断定するものではなく、今後の材料次第で変わり得る点にご留意ください。")

    bull_text = "円安基調や好調な米国株を背景に、輸出関連株を中心に上値を試す展開が意識される可能性があります。"
    neutral_text = "強弱材料が拮抗し、明確な方向感が出ないままレンジ内で推移する可能性があります。"
    bear_text = "円高進行や米国株の軟調な地合いを受け、輸出関連株を中心に下押しする可能性があります。"

    return InstrumentScenario(
        label="日経平均",
        outlook="".join(parts),
        key_driver=driver,
        bull_text=bull_text,
        neutral_text=neutral_text,
        bear_text=bear_text,
    )


def _usdjpy_scenario(market: dict, headlines: List[Headline]) -> InstrumentScenario:
    usdjpy = find_quote(market.get("forex", []), "米ドル/円")
    tnx = find_quote(market.get("rates", []), "10年")

    if usdjpy is None or usdjpy.price is None:
        return InstrumentScenario(
            label="ドル円",
            outlook=NOT_AVAILABLE_OUTLOOK,
            key_driver=NOT_AVAILABLE,
            bull_text=NOT_AVAILABLE_BRANCH,
            neutral_text=NOT_AVAILABLE_BRANCH,
            bear_text=NOT_AVAILABLE_BRANCH,
        )

    parts = [f"現在は{usdjpy.price:.2f}円付近で推移しています。"]

    if tnx is not None and tnx.change is not None:
        if tnx.change >= 0:
            parts.append("米金利が上昇方向にあり、日米金利差の観点から円安圧力が意識されやすい局面です。")
            driver = "米10年金利（上昇方向）"
        else:
            parts.append("米金利が低下方向にあり、金利差縮小の観点から円高圧力が意識されやすい局面です。")
            driver = "米10年金利（低下方向）"
    else:
        parts.append(f"米金利データが{NOT_AVAILABLE}のため、金利差からの影響は確認できていません。")
        driver = NOT_AVAILABLE

    boj_related = [h for h in headlines if "日銀" in h.title or "日本銀行" in h.title]
    if boj_related:
        parts.append(f"日銀関連の報道（「{boj_related[0].title}」）が金融政策の思惑として注目されています。")

    parts.append("為替の先行きを断定することはできず、金融政策や金利動向を確認したい局面です。")

    bull_text = "日米金利差の拡大観測が強まれば、円安方向（ドル高）へシフトするシナリオが意識される可能性があります。"
    neutral_text = "金利差・金融政策見通しが拮抗する場合、当面レンジ内で推移するシナリオも考えられます。"
    bear_text = "日銀の金融政策修正観測や米利下げ観測が強まれば、円高方向へシフトするシナリオも意識される可能性があります。"

    return InstrumentScenario(
        label="ドル円",
        outlook="".join(parts),
        key_driver=driver,
        bull_text=bull_text,
        neutral_text=neutral_text,
        bear_text=bear_text,
    )


def _us_market_scenario(market: dict) -> InstrumentScenario:
    dji = find_quote(market.get("indices", []), "ダウ")
    sp500 = find_quote(market.get("indices", []), "S&P500")
    nasdaq = find_quote(market.get("indices", []), "ナスダック")
    vix = find_quote(market.get("indices", []), "VIX")

    have_data = any(q is not None and q.change_pct is not None for q in [dji, sp500, nasdaq])
    if not have_data:
        return InstrumentScenario(
            label="米国市場",
            outlook=NOT_AVAILABLE_OUTLOOK,
            key_driver=NOT_AVAILABLE,
            bull_text=NOT_AVAILABLE_BRANCH,
            neutral_text=NOT_AVAILABLE_BRANCH,
            bear_text=NOT_AVAILABLE_BRANCH,
        )

    parts = []
    ups = sum(1 for q in [dji, sp500, nasdaq] if q is not None and q.change_pct is not None and q.change_pct >= 0)
    downs = sum(1 for q in [dji, sp500, nasdaq] if q is not None and q.change_pct is not None and q.change_pct < 0)

    if ups > downs:
        parts.append("主要3指数のうち上昇した指数が多く、底堅い地合いが意識されやすい状況です。")
    elif downs > ups:
        parts.append("主要3指数のうち下落した指数が多く、リスク回避的な地合いが意識されやすい状況です。")
    else:
        parts.append("主要3指数の方向感がまちまちで、強弱材料が拮抗している状況です。")

    if vix is not None and vix.price is not None:
        if vix.price >= 20:
            parts.append(f"VIX指数は{vix.price:.2f}と警戒的な水準にあり、変動リスクへの注意が必要な局面です。")
            driver = "VIX指数（警戒水準）"
        else:
            parts.append(f"VIX指数は{vix.price:.2f}と落ち着いた水準にあります。")
            driver = "VIX指数（落ち着いた水準）"
    else:
        parts.append(f"VIX指数のデータが{NOT_AVAILABLE}です。")
        driver = "NYダウ・S&P500・ナスダック"

    parts.append("将来の値動きを保証するものではなく、あくまで参考情報としてご確認ください。")

    bull_text = "インフレ鈍化や良好な決算が続けば、主要指数が上値を試す展開が意識される可能性があります。"
    neutral_text = "強弱材料が拮抗する場合、方向感を欠いたレンジ内推移が意識される可能性があります。"
    bear_text = "金利上昇やVIX指数の上昇を伴うリスク回避が強まれば、主要指数が下押しする可能性があります。"

    return InstrumentScenario(
        label="米国市場",
        outlook="".join(parts),
        key_driver=driver,
        bull_text=bull_text,
        neutral_text=neutral_text,
        bear_text=bear_text,
    )


def build_instrument_scenarios(market: dict, headlines: Optional[List[Headline]] = None) -> List[InstrumentScenario]:
    headlines = headlines or []
    return [
        _nikkei_scenario(market),
        _usdjpy_scenario(market, headlines),
        _us_market_scenario(market),
    ]
