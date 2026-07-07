"""英語ニュース自動翻訳（v2.8・④）— 英語見出しを自然な日本語へ翻訳する。

安全なオプション機能として実装する。ANTHROPIC_API_KEY が設定され `anthropic`
パッケージが使える場合のみ、英語と判定した見出しを日本語へ翻訳して
Headline.title_ja に格納する。未設定・失敗時は何もしない（原文のまま）ため、
既存動作を一切壊さない。表示側は title_ja があれば「日本語 → 原文を見る」の
順で見せる（html_builder側で実装）。

金融用語を優先し、Ticker（NVDA等）や略語（EPS→EPS（一株利益）等）は
補足しつつ維持するようプロンプトで指示する。翻訳結果は同一プロセス内で
キャッシュし、同じ見出しへの二重リクエストを避ける。
"""
from __future__ import annotations

import logging
import re
from typing import Dict, List

from . import llm_enhancer

logger = logging.getLogger("market_brief")

# 英語判定: ASCII英字が一定割合以上を占め、日本語（かな・カナ・漢字）をほぼ含まない
_JP_RE = re.compile(r"[ぁ-んァ-ン぀-ヿ一-龯]")
_ASCII_ALPHA_RE = re.compile(r"[A-Za-z]")
MAX_TRANSLATE = 40  # 1回の実行で翻訳する最大件数（コスト・時間の上限）

_TRANSLATE_INSTRUCTION = (
    "次の英語の金融ニュース見出しを、自然な日本語に翻訳してください。"
    "金融用語を正確に訳し、企業名やTicker（例: NVDA）はそのまま残してください。"
    "EPS・CPI・FOMC・guidance・yield・rate cut等の専門用語は「EPS（一株利益）」"
    "のように必要に応じて日本語補足を付けてください。"
    "原文の意味を変えず、煽り表現は使わず、100文字以内を目安にしてください。"
    "訳文のみを1行で出力し、前置き・引用符・原文は含めないでください。"
)

_cache: Dict[str, str] = {}


def is_english(text: str) -> bool:
    """見出しが英語主体かどうかを判定する（日本語を含めば英語扱いしない）。"""
    if not text or _JP_RE.search(text):
        return False
    alpha = len(_ASCII_ALPHA_RE.findall(text))
    return alpha >= 6 and alpha >= len(text) * 0.4


def translate_text(text: str) -> str:
    """1件を翻訳する。翻訳不可（キー未設定・失敗）なら空文字を返す。"""
    if text in _cache:
        return _cache[text]
    result = llm_enhancer.enhance(
        f"【指示】\n{_TRANSLATE_INSTRUCTION}\n\n【英語見出し】\n{text}",
        max_tokens=200,
    )
    translated = (result or "").strip()
    _cache[text] = translated
    return translated


def translate_headlines(headlines: List, enabled: bool = True) -> int:
    """英語見出しを翻訳して Headline.title_ja に格納する。翻訳した件数を返す。

    ANTHROPIC_API_KEY 未設定時（llm_enhancer.is_available()==False）は
    何もせず0を返す（原文のまま。既存動作に影響なし）。
    """
    if not enabled or not llm_enhancer.is_available():
        return 0
    translated_count = 0
    for h in headlines:
        if translated_count >= MAX_TRANSLATE:
            break
        if getattr(h, "title_ja", ""):
            continue
        if not is_english(h.title):
            continue
        ja = translate_text(h.title)
        if ja and ja != h.title:
            h.title_ja = ja
            translated_count += 1
    if translated_count:
        logger.info("英語ニュース自動翻訳: %d件を日本語へ翻訳しました。", translated_count)
    return translated_count
