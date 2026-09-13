"""Article identityシグナル計算（Phase 2-B）。全て決定論・stdlib・LLM/embedding不使用。

方針:
- 各signalは独立に計算し、結合判断はresolver側（単一signalでsemantic mergeしない）。
- 日本語対応: word tokenizerに依存しない**文字n-gram Jaccard**を主軸にする
  （ja/en双方で機能。SequenceMatcher比も併用）。
- title similarityはidentityではない（同型定型見出し・決算記事での誤結合リスク）。
"""
from __future__ import annotations

import re
import unicodedata
from datetime import datetime
from difflib import SequenceMatcher
from typing import Optional, Set

from ..normalization.text import normalize_title

#: 記号・引用符等の表記ゆれを吸収する安全な句読点正規化（意味は変えない）
_PUNCT_RE = re.compile(r"[　\s\-–—―‐・,，.。、:：;；!！?？'\"“”‘’「」『』()（）\[\]【】]+")


def title_key(title: str) -> str:
    """比較用タイトルキー: P1-D正規化＋小文字化＋安全な句読点除去。翻訳・意味変更なし。"""
    t = normalize_title(title)
    t = unicodedata.normalize("NFKC", t).lower()
    return _PUNCT_RE.sub(" ", t).strip()


def _char_ngrams(text: str, n: int = 3) -> Set[str]:
    compact = text.replace(" ", "")
    if len(compact) < n:
        return {compact} if compact else set()
    return {compact[i:i + n] for i in range(len(compact) - n + 1)}


def ngram_jaccard(a: str, b: str, n: int = 3) -> float:
    """文字n-gram Jaccard類似度（0..1）。言語非依存（ja/en両対応）。"""
    ga, gb = _char_ngrams(title_key(a), n), _char_ngrams(title_key(b), n)
    if not ga or not gb:
        return 0.0
    return len(ga & gb) / len(ga | gb)


def sequence_ratio(a: str, b: str) -> float:
    """difflib.SequenceMatcher比（0..1）。n-gramの補助signal。"""
    return SequenceMatcher(None, title_key(a), title_key(b)).ratio()


def title_similarity(a: str, b: str) -> float:
    """タイトル類似度＝n-gram Jaccardと系列比の**小さい方**（保守的合成）。

    どちらか一方だけ高い場合に引きずられない（FALSE MERGE防止側に倒す）。
    """
    return min(ngram_jaccard(a, b), sequence_ratio(a, b))


def summary_similarity(a: str, b: str) -> float:
    """summary抜粋の類似度（同じ合成規則）。両方空なら0（判断材料にしない）。"""
    if not a.strip() or not b.strip():
        return 0.0
    return min(ngram_jaccard(a, b), sequence_ratio(a, b))


def published_proximity_hours(
    a: Optional[datetime], b: Optional[datetime]
) -> Optional[float]:
    """公開時刻の近接（時間）。どちらか不明ならNone（近接を仮定しない）。"""
    if a is None or b is None:
        return None
    return abs((a - b).total_seconds()) / 3600.0


_DIGIT_TOKEN_RE = re.compile(r"\d+")


def numeric_tokens_differ(title_a: str, title_b: str) -> bool:
    """タイトル中の数字トークン集合が異なるか。

    実データ（tank 3,056件）で判明した誤結合ハザードの決定的特徴:
    「ECB calendars 2027/2028」「Oil Market News for July 21/22」
    「Combined Notice of Filings #1/#2/#3」——高類似タイトル別記事の上位は
    **全て数字だけが違う**。ニュース見出しの数字は意味的に重い（年・日付・
    通番・決算値）ため、数字集合の不一致はAUTO_MERGEの阻止条件とする。
    """
    ta = set(_DIGIT_TOKEN_RE.findall(unicodedata.normalize("NFKC", title_a)))
    tb = set(_DIGIT_TOKEN_RE.findall(unicodedata.normalize("NFKC", title_b)))
    return ta != tb
