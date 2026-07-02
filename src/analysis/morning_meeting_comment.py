"""「朝会コメント」: 30秒・1分・3分の3パターンを自然な日本語で生成する。

営業員が朝会でそのまま読み上げられるよう、箇条書きではなく一続きの文章として
組み立てる。既存のシナリオ・重要ニュースランキング・テーマ/業種分析の結果を
再利用し、新たな考察ロジックは持たない「まとめ役」に徹する。断定表現は避け、
「〜の可能性があります」等の言い回しに統一する。
"""
from __future__ import annotations

from typing import List

from ..collectors.themes import SectorMatch, ThemeMatch
from ..report.format_utils import truncate_to_chars
from .models import MorningMeetingComment, NewsRankingItem, ScenarioForecast

CHARS_30S = 130
CHARS_1MIN = 300
CHARS_3MIN = 750


def _top_sector(sector_matches: List[SectorMatch]):
    if not sector_matches:
        return None
    return sorted(sector_matches, key=lambda m: len(m.tailwind) - len(m.headwind), reverse=True)[0]


def build_morning_meeting_comment(
    scenario: ScenarioForecast,
    news_ranking_items: List[NewsRankingItem],
    theme_matches: List[ThemeMatch],
    sector_matches: List[SectorMatch],
) -> MorningMeetingComment:
    top_theme = theme_matches[0].label if theme_matches else None
    top_sector = _top_sector(sector_matches)
    top_news = news_ranking_items[0] if news_ranking_items else None

    # 30秒版: 結論＋最重要ニュースのみ
    short_parts = [f"おはようございます。本日の相場は強気{scenario.bull_pct}%、弱気{scenario.bear_pct}%と見立てています。"]
    if top_news is not None:
        short_parts.append(f"最重要ニュースは「{top_news.headline.title}」です。")
    short_parts.append("以上、簡単ですが朝の相場感の共有でした。")
    short_30s = truncate_to_chars("".join(short_parts), CHARS_30S)

    # 1分版: 結論＋シナリオ理由＋重要ニュース上位2件＋注目テーマ
    medium_parts = [
        f"おはようございます。本日の相場は強気{scenario.bull_pct}%・中立{scenario.neutral_pct}%・"
        f"弱気{scenario.bear_pct}%と見立てています。{scenario.reasoning}"
    ]
    for item in news_ranking_items[:2]:
        medium_parts.append(f"注目ニュースとして「{item.headline.title}」が挙げられ、{item.reason}")
    if top_theme:
        medium_parts.append(f"本日のテーマとしては「{top_theme}」が注目されています。")
    medium_parts.append("いずれも情報整理であり、投資助言ではない点にご留意ください。")
    medium_1min = truncate_to_chars("".join(medium_parts), CHARS_1MIN)

    # 3分版: シナリオ詳細（強気/中立/弱気それぞれの理由）＋重要ニュース上位3件＋注目業種＋テーマ
    long_parts = [
        f"おはようございます。本日の朝会コメントをお伝えします。本日の相場シナリオは、"
        f"強気{scenario.bull_pct}%・中立{scenario.neutral_pct}%・弱気{scenario.bear_pct}%です。"
        f"{scenario.reasoning}"
    ]
    if scenario.bull_reason:
        long_parts.append(f"強気シナリオの理由としては、{scenario.bull_reason}")
    if scenario.bear_reason:
        long_parts.append(f"一方で弱気シナリオの理由としては、{scenario.bear_reason}")
    for item in news_ranking_items[:3]:
        long_parts.append(f"注目ニュースとして「{item.headline.title}」があり、{item.reason}")
    if top_sector is not None:
        if len(top_sector.tailwind) > len(top_sector.headwind):
            long_parts.append(f"業種では「{top_sector.label}」に追い風の材料が優勢で、資金流入余地が意識されています。")
        elif len(top_sector.headwind) > len(top_sector.tailwind):
            long_parts.append(f"業種では「{top_sector.label}」に逆風の材料が優勢で、注意が必要な局面です。")
    if top_theme:
        long_parts.append(f"テーマとしては「{top_theme}」が引き続き注目されています。")
    long_parts.append("以上、いずれも公開情報に基づく機械的な考察であり、投資助言ではありません。本日もよろしくお願いいたします。")
    long_3min = truncate_to_chars("".join(long_parts), CHARS_3MIN)

    return MorningMeetingComment(short_30s=short_30s, medium_1min=medium_1min, long_3min=long_3min)
