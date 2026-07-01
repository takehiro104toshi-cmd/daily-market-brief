"""営業トーク以外でも使える、軽い雑談ネタを3つ生成する。

事実（VIX水準・注目テーマ・見出し）をもとにした、ルールベースの機械的な文言。
"""
from __future__ import annotations

from typing import List

from ..collectors.news import Headline
from ..collectors.themes import ThemeMatch
from ..report.format_utils import find_quote
from . import llm_enhancer

_FALLBACK_TOPICS = [
    "最近の相場全体としては、材料を確認しながら様子を見る場面が多いようです。",
    "きょうは相場の材料が乏しく、静かな一日になっているかもしれません。",
    "こういう日は、次のイベントに向けて情報収集をしておくのも良さそうです。",
]


def build_chat_topics(market: dict, theme_matches: List[ThemeMatch], headlines: List[Headline]) -> List[str]:
    topics: List[str] = []

    vix = find_quote(market["indices"], "VIX")
    if vix and vix.price is not None:
        mood = "落ち着いた雰囲気" if vix.price < 20 else "やや緊張感のある雰囲気"
        topics.append(f"最近の株式市場は{mood}のようですね（VIX指数 {vix.price:.2f}）。")

    if theme_matches:
        top = max(theme_matches, key=lambda m: len(m.headlines))
        topics.append(f"今、「{top.label}」の話題がニュースでよく取り上げられていますね。")

    if headlines:
        topics.append(f"今日は「{headlines[0].title}」というニュースが話題になっています。")

    fallback_iter = iter(_FALLBACK_TOPICS)
    while len(topics) < 3:
        topics.append(next(fallback_iter, _FALLBACK_TOPICS[-1]))

    polished = []
    for topic in topics[:3]:
        polished.append(
            llm_enhancer.enhance_or_fallback(
                deterministic_text=topic,
                facts=topic,
                instruction="このひとことを、雑談として自然に話せる1文に磨き上げてください（営業トークではなく世間話の体裁で）。",
                max_tokens=120,
            )
        )
    return polished
