"""「今日電話すべき顧客」(富裕層/NISA/退職金/法人/相続/若年層の6顧客タイプ)を提案する。

各タイプについて「なぜ今日電話すべきか（理由）」「話題」「営業トーク例」を
ルールベースで生成する。断定表現は使わず、「〜の可能性があります」
「〜が注目されています」等の言い回しに統一する。事実の紹介・情報整理に
とどめ、投資助言（売買の推奨・勧誘）は行わない。
"""
from __future__ import annotations

from typing import List, Optional

from ..collectors.themes import SectorMatch, ThemeMatch
from ..report.format_utils import NOT_AVAILABLE, find_quote
from .models import CallPriorityEntry, ScenarioForecast


def _top_sector(sector_matches: List[SectorMatch]) -> Optional[SectorMatch]:
    if not sector_matches:
        return None
    return sorted(sector_matches, key=lambda m: len(m.tailwind) - len(m.headwind), reverse=True)[0]


def build_call_priorities(
    market: dict,
    scenario: ScenarioForecast,
    theme_matches: List[ThemeMatch],
    sector_matches: List[SectorMatch],
) -> List[CallPriorityEntry]:
    usdjpy = find_quote(market["forex"], "米ドル/円")
    tnx = find_quote(market["rates"], "10年")
    vix = find_quote(market["indices"], "VIX")
    top_theme = theme_matches[0].label if theme_matches else None
    top_sector = _top_sector(sector_matches)

    usdjpy_txt = f"{usdjpy.price:.2f}円" if usdjpy and usdjpy.price is not None else NOT_AVAILABLE
    tnx_txt = f"{tnx.price:.2f}%" if tnx and tnx.price is not None else NOT_AVAILABLE
    vix_level = "やや高め" if (vix and vix.price is not None and vix.price >= 20) else "落ち着いた"

    entries: List[CallPriorityEntry] = []

    entries.append(
        CallPriorityEntry(
            customer_type="富裕層",
            reason=f"為替（米ドル/円{usdjpy_txt}）と米金利（{tnx_txt}）の動きがあり、資産配分の見直し話題として"
                   "お声がけしやすいタイミングと考えられます。",
            topic=f"外貨建て資産・分散投資の状況確認{('、『' + top_theme + '』関連のテーマ') if top_theme else ''}",
            sales_talk="市場環境の変化を踏まえ、資産配分を確認するお時間をいただけますでしょうか。",
        )
    )

    entries.append(
        CallPriorityEntry(
            customer_type="NISA",
            reason=f"市場のボラティリティは{vix_level}水準で、長期・積立の基本方針を再確認いただく"
                   "良いタイミングと考えられます。",
            topic="NISA枠の活用状況、積立設定の見直し",
            sales_talk="短期の値動きに惑わされず、積立方針を一緒に確認させていただけますでしょうか。",
        )
    )

    entries.append(
        CallPriorityEntry(
            customer_type="退職金",
            reason="退職金のご相談は市場動向にかかわらず、生活資金とのバランス確認が重要な局面です。"
                   "落ち着いたタイミングでの情報整理としてお声がけできます。",
            topic="時間分散の考え方、生活資金と運用資金の切り分け",
            sales_talk="退職金の運用方針について、改めて整理するお時間を頂戴できればと思います。",
        )
    )

    entries.append(
        CallPriorityEntry(
            customer_type="法人",
            reason=f"為替（米ドル/円{usdjpy_txt}）・金利（{tnx_txt}）の動きが、資金調達コストや"
                   "輸出入採算に影響しうる局面として注目されています。",
            topic="為替・金利ヘッジの状況、資金計画の確認",
            sales_talk="足元の為替・金利動向を踏まえ、資金計画を確認するお時間をいただけますでしょうか。",
        )
    )

    entries.append(
        CallPriorityEntry(
            customer_type="相続",
            reason="市場動向にかかわらず、資産全体の棚卸しや承継方法の整理をするきっかけとして"
                   "お声がけしやすい局面です。",
            topic="資産全体の棚卸し、承継方法のご相談",
            sales_talk="資産状況を一度整理するお手伝いができればと思い、ご連絡いたしました。",
        )
    )

    entries.append(
        CallPriorityEntry(
            customer_type="若年層",
            reason=f"{('『' + top_theme + '』のような話題性のあるテーマが注目されており、') if top_theme else ''}"
                   "投資を始める・続けるきっかけとして関心を持っていただきやすい局面と考えられます。",
            topic=f"少額投資・積立投資の始め方{('、『' + top_sector.label + '』のような成長テーマ') if top_sector else ''}",
            sales_talk="少額から始められる積立投資について、一度お話しさせていただけますでしょうか。",
        )
    )

    return entries
