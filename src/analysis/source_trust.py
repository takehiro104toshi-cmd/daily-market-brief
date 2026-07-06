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
        ["frb", "frb", "fed", "fomc", "日銀", "boj", "財務省", "mof", "内閣府", "経産省",
         "白書", "white house", "sec", "tdnet", "edinet", "決算短信", "適時開示", "ir",
         "統計", "official", "gov"],
        5, "公式発表",
        "公式・一次情報（当局／企業IR／開示）のため、信頼性が最も高い区分です。",
    ),
    (
        ["reuters", "ロイター", "bloomberg", "ブルームバーグ", "日経", "nikkei", "wsj",
         "wall street", "cnbc", "marketwatch", "financial times", "ft"],
        4, "一流メディア・IR",
        "一流の経済専門メディア配信のため、速報性・信頼性が高い区分です。",
    ),
    (
        ["nhk", "yahoo", "ヤフー", "株探", "kabutan", "moomoo", "investing", "みんかぶ",
         "minkabu", "sbi", "楽天", "rakuten"],
        3, "主要メディア",
        "主要な情報サービス配信のため、参考度は中程度の区分です。",
    ),
]

_DEFAULT = (2, "一般メディア", "一般的な情報源のため、内容は他情報と併せてご確認ください。")
_UNKNOWN = (1, "参考情報", "出典が特定できないため、参考情報として扱ってください。")


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
