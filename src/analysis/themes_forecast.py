"""注目テーマをランキングし、各テーマの「今強い理由」と短中期の見立てを生成する。

テーマごとの文言はルールベースのテンプレート（あらかじめ用意した
一般的な市場観点の言い回し）に、実際の見出し件数（モメンタム）を
組み合わせて生成する「機械的な考察」であり、将来を保証するものではない。
ANTHROPIC_API_KEY が設定されている場合は、Claudeがこのたたき台を
事実（見出し件数・テーマ名）の範囲内で磨き上げる。
"""
from __future__ import annotations

from typing import Dict, List

from ..collectors.news import Headline
from ..report.format_utils import count_stars
from . import llm_enhancer
from .models import ThemeForecast

# テーマ名ごとの一般的な考察テンプレート（既知テーマのみ）。
# 未知のテーマは _GENERIC_TEMPLATE にフォールバックする。
_TEMPLATES: Dict[str, Dict[str, str]] = {
    "半導体": {
        "why_now": "{momentum}半導体関連の報道が続いており、AI・データセンター需要を背景とした投資マネーの物色が意識されています。",
        "outlook_1w": "決算や受注動向のヘッドラインに一喜一憂しやすく、値動きが荒くなる可能性があります。",
        "outlook_1m": "AI向け設備投資のニュースが続けば物色の中心であり続ける可能性があります。",
        "outlook_3m": "需給サイクル次第では調整局面を挟みつつも、構造的なテーマとして意識され続ける可能性があります。",
    },
    "生成AI": {
        "why_now": "{momentum}生成AI関連の報道が出ており、関連投資・提携のニュースが物色の材料になっています。",
        "outlook_1w": "大手企業の新製品・提携発表が相場のきっかけになりやすい状況です。",
        "outlook_1m": "投資計画の具体化が進めば関連銘柄への資金流入が続く可能性があります。",
        "outlook_3m": "中長期の構造的テーマとして意識され続ける可能性がありますが、期待先行による変動にも留意が必要です。",
    },
    "AI": {
        "why_now": "{momentum}AI関連ニュースが出ており、生成AI・半導体テーマと合わせて注目されやすい状況です。",
        "outlook_1w": "関連企業の発表がテーマ全体のセンチメントを左右しやすい状況です。",
        "outlook_1m": "投資計画・規制動向次第でテーマの持続性が左右される可能性があります。",
        "outlook_3m": "構造的な成長テーマとして意識され続ける可能性があります。",
    },
    "円安": {
        "why_now": "{momentum}円安に関する報道が出ており、輸出関連企業の収益期待が意識されやすい状況です。",
        "outlook_1w": "日銀・米金融当局者の発言で為替が振れやすく、関連株の値動きも連動しやすい状況です。",
        "outlook_1m": "金利差を巡る観測が続く限り、同様の地合いが続く可能性があります。",
        "outlook_3m": "金融政策の方向性次第でテーマの持続性が変わる可能性があります。",
    },
    "円高": {
        "why_now": "{momentum}円高に関する報道が出ており、輸出関連企業の収益への懸念が意識されやすい状況です。",
        "outlook_1w": "為替の振れに応じて輸出関連株が神経質な値動きになりやすい状況です。",
        "outlook_1m": "金利差の縮小観測が続けば、同様の警戒感が続く可能性があります。",
        "outlook_3m": "内需関連への物色シフトが意識される可能性があります。",
    },
    "インバウンド": {
        "why_now": "{momentum}インバウンド関連の報道が出ており、観光・小売関連企業への注目が集まりやすい状況です。",
        "outlook_1w": "為替動向や訪日客数の統計発表がきっかけになりやすい状況です。",
        "outlook_1m": "季節要因や為替次第で関連消費動向のニュースが続く可能性があります。",
        "outlook_3m": "構造的な需要として意識され続ける可能性がありますが、政策変更などのリスクにも留意が必要です。",
    },
    "防衛": {
        "why_now": "{momentum}防衛関連の報道が出ており、防衛予算・地政学リスクを背景とした関連株への関心が意識されています。",
        "outlook_1w": "地政学ニュースの続報が値動きのきっかけになりやすい状況です。",
        "outlook_1m": "予算編成や政策方針のニュース次第でテーマの持続性が左右される可能性があります。",
        "outlook_3m": "防衛費増額の方向性が続く限り、構造的なテーマとして意識され続ける可能性があります。",
    },
    "資源": {
        "why_now": "{momentum}資源関連の報道が出ており、商品市況や地政学要因を背景とした関連株への関心が意識されています。",
        "outlook_1w": "原油・資源価格の変動が直接的な材料になりやすい状況です。",
        "outlook_1m": "需給動向や地政学リスク次第でテーマの持続性が変わる可能性があります。",
        "outlook_3m": "資源価格サイクル次第で、構造的な物色対象であり続けるかどうかが左右される可能性があります。",
    },
    "電力": {
        "why_now": "{momentum}電力関連の報道が出ており、データセンター向け電力需要の拡大などが意識されています。",
        "outlook_1w": "電力需給や設備投資に関する続報が材料になりやすい状況です。",
        "outlook_1m": "データセンター投資の進捗次第で関連株への関心が続く可能性があります。",
        "outlook_3m": "電力インフラ増強という構造的テーマとして意識され続ける可能性があります。",
    },
    "EV": {
        "why_now": "{momentum}EV関連の報道が出ており、自動車各社の戦略転換への関心が意識されています。",
        "outlook_1w": "各社の販売台数・戦略発表が値動きのきっかけになりやすい状況です。",
        "outlook_1m": "需要動向や補助金政策のニュース次第でテーマの持続性が変わる可能性があります。",
        "outlook_3m": "業界再編や技術動向次第で、構造的なテーマとしての位置づけが変わる可能性があります。",
    },
    "インフレ": {
        "why_now": "{momentum}インフレに関する報道が出ており、金融政策見通しへの影響が意識されています。",
        "outlook_1w": "物価指標の発表が相場全体のボラティリティ要因になりやすい状況です。",
        "outlook_1m": "中央銀行の政策スタンス次第でテーマの持続性が変わる可能性があります。",
        "outlook_3m": "インフレ動向は金融政策全体を左右するため、引き続き主要テーマであり続ける可能性があります。",
    },
    "利上げ": {
        "why_now": "{momentum}利上げに関する報道が出ており、金融株や金利敏感株への関心が意識されています。",
        "outlook_1w": "中央銀行関係者の発言が相場の振れ要因になりやすい状況です。",
        "outlook_1m": "次回会合までの経済指標次第でテーマの持続性が変わる可能性があります。",
        "outlook_3m": "金融政策サイクルの転換点として、引き続き注目される可能性があります。",
    },
    "利下げ": {
        "why_now": "{momentum}利下げに関する報道が出ており、成長株や不動産関連株への関心が意識されています。",
        "outlook_1w": "中央銀行関係者の発言が相場の振れ要因になりやすい状況です。",
        "outlook_1m": "経済指標次第で利下げ観測の強弱が変わり、テーマの持続性に影響する可能性があります。",
        "outlook_3m": "金融政策サイクルの転換点として、引き続き注目される可能性があります。",
    },
    "電線": {
        "why_now": "{momentum}電線関連の報道が出ており、データセンター・電力インフラ投資拡大を背景とした需要増加が意識されています。",
        "outlook_1w": "受注動向や増産に関する続報が材料になりやすい状況です。",
        "outlook_1m": "データセンター投資の進捗次第で関連株への関心が続く可能性があります。",
        "outlook_3m": "インフラ投資拡大という構造的テーマとして意識され続ける可能性があります。",
    },
    "データセンター": {
        "why_now": "{momentum}データセンター関連の報道が出ており、AI需要拡大を背景とした設備投資への関心が意識されています。",
        "outlook_1w": "大手クラウド事業者の投資計画発表が材料になりやすい状況です。",
        "outlook_1m": "設備投資計画の具体化が進めば関連銘柄への関心が続く可能性があります。",
        "outlook_3m": "AI基盤投資という構造的テーマとして意識され続ける可能性があります。",
    },
}

_GENERIC_TEMPLATE = {
    "why_now": "{momentum}「{label}」関連の報道が出ています。",
    "outlook_1w": "続報の有無が短期的な値動きの材料になりやすい状況です。",
    "outlook_1m": "関連ニュースの頻度が今後も高い状態が続くか注視が必要です。",
    "outlook_3m": "一過性の話題か構造的なテーマかは、今後のニュースの継続性次第と考えられます。",
}


def _momentum_word(count: int) -> str:
    if count >= 5:
        return "特に"
    if count >= 3:
        return "継続的に"
    return "本日一部"


def build_theme_forecasts(theme_matches: List, themes_headlines_limit: int = 5) -> List[ThemeForecast]:
    if not theme_matches:
        return []

    ranked = sorted(theme_matches, key=lambda m: len(m.headlines), reverse=True)
    forecasts: List[ThemeForecast] = []
    for rank, match in enumerate(ranked, start=1):
        count = len(match.headlines)
        template = _TEMPLATES.get(match.label, _GENERIC_TEMPLATE)
        momentum = _momentum_word(count)

        why_now = template["why_now"].format(momentum=momentum, label=match.label)
        outlook_1w = template["outlook_1w"]
        outlook_1m = template["outlook_1m"]
        outlook_3m = template["outlook_3m"]

        facts = f"テーマ名: {match.label}, 本日の関連見出し件数: {count}件"
        why_now = llm_enhancer.enhance_or_fallback(
            deterministic_text=why_now,
            facts=facts,
            instruction="このテーマが「今なぜ強いか」を1〜2文で説明してください。",
            max_tokens=200,
        )

        forecasts.append(
            ThemeForecast(
                rank=rank,
                label=match.label,
                stars=count_stars(count, max_stars=5),
                why_now=why_now,
                outlook_1w=outlook_1w,
                outlook_1m=outlook_1m,
                outlook_3m=outlook_3m,
                headlines=match.headlines[:themes_headlines_limit],
            )
        )
    return forecasts
