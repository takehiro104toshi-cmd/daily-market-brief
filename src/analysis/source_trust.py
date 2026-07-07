"""情報ソース信頼度（v2.8・⑥）— 出典名から信頼度（★1〜5）を機械的に判定する。

「この情報をどの程度信頼してよいか」を朝の3分で判断できるよう、出典名を
人手による対応表（_TRUST_TIERS）と照合して★と理由を返すだけの純粋関数。
AIによる新たな評価・予測は行わない。未知の出典は既定で★★☆☆☆（一般メディア）。
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import List, Tuple

from ..report.format_utils import stars


@dataclass
class SourceTrust:
    stars: str          # "★★★★☆"
    score: int          # 1〜5
    tier: str           # 公式発表 / 一流メディア・IR / 主要メディア / 一般メディア / 参考情報
    reason: str


# (キーワード群, スコア, ティア名, 理由) の対応表。上から順に最初に一致したものを採用。
# キーワードは出典名（Headline.source等）に対する部分一致・大文字小文字無視で判定する。
_TRUST_TIERS: List[Tuple[List[str], int, str, str]] = [
    (
        ["frb", "fed", "fomc", "日銀", "boj", "財務省", "mof", "内閣府", "経産省",
         "白書", "white house", "sec", "tdnet", "edinet", "決算短信", "適時開示", "ir",
         "統計", "official", "gov", "bls", "bea", "eia", "us treasury", "treasury",
         "ecb", "bank of england", "boe"],
        5, "公式発表",
        "公式・一次情報（当局／中央銀行／企業IR／開示）のため、信頼性が最も高い区分です。",
    ),
    (
        ["reuters", "ロイター", "bloomberg", "ブルームバーグ", "日経", "nikkei", "wsj",
         "wall street", "cnbc", "marketwatch", "financial times", "ft", "barron"],
        4, "一流メディア・IR",
        "一流の経済専門メディア配信のため、速報性・信頼性が高い区分です。",
    ),
    (
        ["nhk", "yahoo", "ヤフー", "株探", "kabutan", "moomoo", "investing", "みんかぶ",
         "minkabu", "sbi", "楽天", "rakuten", "coindesk", "cointelegraph"],
        3, "主要メディア",
        "主要な情報サービス配信のため、参考度は中程度の区分です。",
    ),
]

_DEFAULT = (2, "一般メディア", "一般的な情報源のため、内容は他情報と併せてご確認ください。")
_UNKNOWN = (1, "参考情報", "出典が特定できないため、参考情報として扱ってください。")


@dataclass
class CombinedTrust:
    """複数ソースが同一ニュースを配信していた場合の統合信頼度（v2.9・④）。"""

    source_count: int
    max_score: int          # 報道した情報源の中で最も高い信頼度スコア
    combined_score: int     # 複数報道による補正込みのスコア（1〜5に丸め）
    all_sources: List[str]
    stars: str


def combined_trust_for_sources(primary_source: str, duplicate_sources: List[str]) -> CombinedTrust:
    """主となる情報源＋重複配信していた他の情報源から統合信頼度を計算する。

    同一ニュースを複数の高信頼情報源が報じている場合、単独報道より確度が
    高いと考えられるため、報道社数に応じて小さな補正（+1〜+2、上限5）を
    最も高い信頼度スコアへ加える。新たな評価基準の創作ではなく、既存の
    Source Trustスコアの機械的な集計にすぎない。
    """
    all_sources = [primary_source] + list(duplicate_sources)
    scores = [trust_for_source(s).score for s in all_sources]
    max_score = max(scores) if scores else 1
    source_count = len(all_sources)
    bonus = 0
    if source_count >= 2:
        bonus += 1
    if source_count >= 3:
        bonus += 1
    combined_score = min(5, max_score + bonus)
    return CombinedTrust(
        source_count=source_count,
        max_score=max_score,
        combined_score=combined_score,
        all_sources=all_sources,
        stars=stars(combined_score, max_stars=5),
    )


def trust_for_source(source_name: str) -> SourceTrust:
    """出典名から信頼度を判定する。空・不明は★☆☆☆☆（参考情報）。"""
    if not source_name or not source_name.strip():
        score, tier, reason = _UNKNOWN
        return SourceTrust(stars=stars(score, max_stars=5), score=score, tier=tier, reason=reason)

    lowered = source_name.lower()
    for keywords, score, tier, reason in _TRUST_TIERS:
        if any(kw in lowered for kw in keywords):
            return SourceTrust(stars=stars(score, max_stars=5), score=score, tier=tier, reason=reason)

    score, tier, reason = _DEFAULT
    return SourceTrust(stars=stars(score, max_stars=5), score=score, tier=tier, reason=reason)
