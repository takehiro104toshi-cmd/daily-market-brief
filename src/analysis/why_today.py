"""Why Today（v2.8・⑦）— 各重要カードに「なぜ今日見るべきか」を1行で付ける。

情報量が多くても、今日その項目を見る意味がすぐ分かるようにするための機能。
すべて既存の計算済みデータ（ニュース鮮度・Theme Momentum・テーマ別診断・
Weekly Event・鮮度統計）のみから機械的に1〜2行を生成する。新しい予測は行わず、
長文にはしない（各行はMAX_CHARS文字まで）。該当データが無い項目は生成しない。
"""
from __future__ import annotations

from datetime import datetime
from typing import Dict, Optional

from ..collectors.news import parse_published_datetime

MAX_CHARS = 120


def _age_hours(published: str, now: datetime) -> Optional[float]:
    dt = parse_published_datetime(published)
    if dt is None:
        return None
    return (now - dt).total_seconds() / 3600


def _count_fresh_news(news_ranking, now: datetime) -> int:
    fresh = 0
    for item in news_ranking:
        age = _age_hours(item.headline.published, now)
        if age is not None and age <= 24:
            fresh += 1
    return fresh


def build_why_today(analysis, freshness, weekly_events, now: datetime) -> Dict[str, str]:
    """セクションanchor → 「Why Today」1行 の辞書を返す（該当なしは含めない）。"""
    why: Dict[str, str] = {}

    # AI Executive Summary: 本日最重要ニュースの鮮度に応じて
    if analysis.executive_summary:
        top = analysis.executive_summary[0]
        age = _age_hours(top.headline.published, now)
        if age is not None and age <= 24:
            why["executive-summary"] = "本日最重要のニュースが24時間以内に出ており、相場への影響を最初に確認すべき局面です。"
        else:
            why["executive-summary"] = "本日最重要と判断したニュースの影響を、朝いちばんに把握しておくべき項目です。"

    # 重要ニュースランキング: 24時間以内の重要ニュース件数
    fresh_count = _count_fresh_news(analysis.news_ranking, now)
    if analysis.news_ranking:
        if fresh_count > 0:
            why["news-ranking"] = f"24時間以内の新しい重要ニュースが{fresh_count}件あり、鮮度の高い材料から確認する優先度が高いです。"
        else:
            why["news-ranking"] = "本日は新規性の高いニュースが乏しく、継続テーマの動向確認が中心になる局面です。"

    # Future Intelligence: 最も勢いのあるテーマ
    fi = analysis.future_intelligence
    if fi and fi.theme_momentum:
        top_theme = max(fi.theme_momentum, key=lambda t: t.momentum_score)
        why["future-intelligence"] = (
            f"「{top_theme.label}」のモメンタムが{top_theme.momentum_score}/100と高く、"
            "世界の変化とテーマの確認優先度が高いです。"
        )

    # Weekly Event: 直近の高重要度イベント
    if weekly_events:
        top_event = min(weekly_events, key=lambda e: (e.days_until, -e.importance))
        if top_event.importance >= 80:
            why["weekly-events"] = (
                f"{top_event.countdown_text}に{top_event.label}を控えており、"
                f"{('・'.join(top_event.impact_targets[:3]))}の変動リスクが高まる局面です。"
            )
        else:
            why["weekly-events"] = f"直近で最も近い重要イベントは{top_event.countdown_text}の{top_event.label}です。"

    # News Freshness: 平均鮮度
    if freshness is not None and getattr(freshness, "avg_age_hours", None) is not None:
        why["news-freshness"] = (
            f"採用ニュースの平均経過時間は約{freshness.avg_age_hours:.0f}時間で、"
            "本日のレポートがどれだけ新しい材料に基づくかを確認できます。"
        )

    # Data Quality: 取得状況
    if freshness is not None:
        why["data-quality"] = "本日のレポートが最新データに基づいているかを、取得状況の指標で確認できます。"

    # 長文防止
    return {k: (v[:MAX_CHARS]) for k, v in why.items()}
