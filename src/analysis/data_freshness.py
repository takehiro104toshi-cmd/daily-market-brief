"""Data Freshness & News Quality（v2.3）— データ鮮度の計測・可視化。

「本当に最新データなのか」「鮮度はどれくらいか」「どの記事を根拠にしているか」を
利用者が毎朝確認できるようにするためのモジュール。

このモジュールは既存の分析ロジック（重要度スコア・Momentum・Confidence・
Watchlist判定等）には一切関与しない。既に取得済みのヘッドライン・ランキング
結果から鮮度の統計を「計測」して表示・ログ出力するだけの読み取り専用レイヤー
であり、将来の拡張（鮮度加点・情報源信頼度・速報フラグ等）はこのモジュールへ
の追加として実装できる構造にしている。
"""
from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import List, Optional

from ..collectors.news import Headline, parse_published_datetime

logger = logging.getLogger("market_brief")

NOT_AVAILABLE = "取得不可"

# Freshness Score（経過時間 → ★）。表示専用でランキングには影響しない。
FRESHNESS_THRESHOLDS_HOURS = [
    (24, 5, "非常に新しい"),
    (48, 4, "良好"),
    (72, 3, "普通"),
    (96, 2, "やや古い"),
]
FRESHNESS_FLOOR = (1, "古い")


@dataclass
class SourceHealthEntry:
    """RSS Source Health（情報源ごとの取得状況）の1行分。"""

    name: str
    ok: bool
    count: int
    newest_published: Optional[datetime] = None
    # v2.9（⑤ 情報取得時刻の見える化）: このソースから見出しを取得した時刻
    # （Headline.fetched_atの最大値）。取得失敗時はNone。
    fetched_at: Optional[datetime] = None


@dataclass
class DataFreshnessStats:
    """レポート1回分のデータ鮮度統計。表示・ログ専用（分析には使わない）。"""

    generated_at: datetime
    rss_fetched_total: int = 0
    deduped_total: int = 0
    adopted_count: int = 0
    newest_published: Optional[datetime] = None
    oldest_adopted: Optional[datetime] = None
    avg_age_hours: Optional[float] = None
    top_item_title: str = ""
    top_item_published: Optional[datetime] = None
    source_health: List[SourceHealthEntry] = field(default_factory=list)


def freshness_score(age_hours: Optional[float]) -> int:
    """経過時間（時間）→ Freshness Score（1〜5）。Noneは最低評価1。"""
    if age_hours is None or age_hours < 0:
        return FRESHNESS_FLOOR[0] if age_hours is None else 5
    for threshold, score, _ in FRESHNESS_THRESHOLDS_HOURS:
        if age_hours < threshold:
            return score
    return FRESHNESS_FLOOR[0]


def freshness_stars(age_hours: Optional[float]) -> str:
    score = freshness_score(age_hours)
    return "★" * score + "☆" * (5 - score)


def freshness_label(age_hours: Optional[float]) -> str:
    if age_hours is None:
        return "判断材料不足"
    if age_hours < 0:
        return FRESHNESS_THRESHOLDS_HOURS[0][2]
    for threshold, _, label in FRESHNESS_THRESHOLDS_HOURS:
        if age_hours < threshold:
            return label
    return FRESHNESS_FLOOR[1]


def headline_age_hours(headline: Headline, now: datetime) -> Optional[float]:
    """記事の経過時間（時間）。pubDateが解析できない場合はNone。"""
    dt = parse_published_datetime(headline.published)
    if dt is None:
        return None
    return (now - dt).total_seconds() / 3600.0


def availability_stars(available: int, total: int) -> str:
    """取得できた割合 → ★（市場データ・Watchlist等の可用性評価に使う機械的な指標）。"""
    if total <= 0:
        return "★☆☆☆☆"
    ratio = available / total
    if ratio >= 0.9:
        score = 5
    elif ratio >= 0.7:
        score = 4
    elif ratio >= 0.5:
        score = 3
    elif ratio > 0:
        score = 2
    else:
        score = 1
    return "★" * score + "☆" * (5 - score)


def build_source_health(
    raw_headlines: List[Headline],
    attempted_source_names: Optional[List[str]] = None,
) -> List[SourceHealthEntry]:
    """重複除去前の全ヘッドラインを情報源名でグルーピングし、取得状況を一覧化する。

    attempted_source_names: 取得を試みたが1件も返らなかった情報源名
    （configのnews_sources名・collector名）。取得失敗として明示する。
    """
    grouped: dict = {}
    for h in raw_headlines:
        entry = grouped.setdefault(h.source, {"count": 0, "newest": None, "fetched_at": None})
        entry["count"] += 1
        dt = parse_published_datetime(h.published)
        if dt is not None and (entry["newest"] is None or dt > entry["newest"]):
            entry["newest"] = dt
        fetched_dt = parse_published_datetime(h.fetched_at) if h.fetched_at else None
        if fetched_dt is not None and (entry["fetched_at"] is None or fetched_dt > entry["fetched_at"]):
            entry["fetched_at"] = fetched_dt

    health = [
        SourceHealthEntry(
            name=name, ok=True, count=info["count"], newest_published=info["newest"], fetched_at=info["fetched_at"]
        )
        for name, info in grouped.items()
    ]
    for name in attempted_source_names or []:
        if name not in grouped:
            health.append(SourceHealthEntry(name=name, ok=False, count=0))
    return health


def build_data_freshness_stats(
    generated_at: datetime,
    raw_headlines: List[Headline],
    deduped_headlines: List[Headline],
    ranking_items: list,
    attempted_source_names: Optional[List[str]] = None,
) -> DataFreshnessStats:
    """取得済みデータからデータ鮮度統計を計測する（分析ロジックへの影響なし）。"""
    if generated_at.tzinfo is None:
        generated_at = generated_at.replace(tzinfo=timezone.utc)

    adopted_dts = []
    for item in ranking_items:
        dt = parse_published_datetime(item.headline.published)
        if dt is not None:
            adopted_dts.append(dt)

    all_dts = [d for d in (parse_published_datetime(h.published) for h in deduped_headlines) if d is not None]

    avg_age = None
    if adopted_dts:
        avg_age = sum((generated_at - d).total_seconds() for d in adopted_dts) / len(adopted_dts) / 3600.0

    top_title = ""
    top_published = None
    if ranking_items:
        top_title = ranking_items[0].headline.title
        top_published = parse_published_datetime(ranking_items[0].headline.published)

    return DataFreshnessStats(
        generated_at=generated_at,
        rss_fetched_total=len(raw_headlines),
        deduped_total=len(deduped_headlines),
        adopted_count=len(ranking_items),
        newest_published=max(all_dts) if all_dts else None,
        oldest_adopted=min(adopted_dts) if adopted_dts else None,
        avg_age_hours=avg_age,
        top_item_title=top_title,
        top_item_published=top_published,
        source_health=build_source_health(raw_headlines, attempted_source_names),
    )


def _fmt_dt(dt: Optional[datetime], tz=None) -> str:
    if dt is None:
        return NOT_AVAILABLE
    if tz is not None:
        dt = dt.astimezone(tz)
    return dt.strftime("%m/%d %H:%M")


def _fmt_hours(hours: Optional[float]) -> str:
    if hours is None:
        return NOT_AVAILABLE
    return f"{hours:.0f}時間"


def render_job_summary_markdown(stats: DataFreshnessStats) -> str:
    """GitHub ActionsのJob Summary向け「Data Freshness Summary」Markdown。"""
    tz = stats.generated_at.tzinfo
    lines = [
        "### Data Freshness Summary",
        "",
        f"- RSS取得件数（重複除去前）: {stats.rss_fetched_total}件",
        f"- 重複削除後件数（ランキング対象）: {stats.deduped_total}件",
        f"- ランキング採用件数: {stats.adopted_count}件",
        f"- ランキング1位の記事日時: {_fmt_dt(stats.top_item_published, tz)}",
        f"- ランキング1位のタイトル: {stats.top_item_title or NOT_AVAILABLE}",
        f"- Executive Summary採用記事日時（=ランキング1位）: {_fmt_dt(stats.top_item_published, tz)}",
        f"- Dashboard採用記事日時（=Executive Summary上位3件）: {_fmt_dt(stats.top_item_published, tz)}",
        f"- 最新ニュース日時: {_fmt_dt(stats.newest_published, tz)}",
        f"- 採用記事平均経過時間: {_fmt_hours(stats.avg_age_hours)}",
        f"- レポート生成日時: {stats.generated_at.strftime('%Y-%m-%d %H:%M')}",
        f"- HTML生成時刻: {datetime.now(tz or timezone.utc).strftime('%Y-%m-%d %H:%M')}",
        f"- データ鮮度評価: {freshness_stars(stats.avg_age_hours)} {freshness_label(stats.avg_age_hours)}",
        "",
    ]
    return "\n".join(lines)


def render_source_health_markdown(stats: DataFreshnessStats) -> str:
    """GitHub ActionsのJob Summary向け「RSS Source Health」Markdown。"""
    tz = stats.generated_at.tzinfo
    lines = [
        "### RSS Source Health",
        "",
        "| 情報源 | 状態 | 件数 | 取得時刻 | 最新記事日時 |",
        "|---|---|---|---|---|",
    ]
    for entry in sorted(stats.source_health, key=lambda e: (-e.count, e.name)):
        status = "✅ 成功" if entry.ok else "❌ 取得失敗（0件）"
        lines.append(
            f"| {entry.name} | {status} | {entry.count}件 | {_fmt_dt(entry.fetched_at, tz)} | "
            f"{_fmt_dt(entry.newest_published, tz)} |"
        )
    if not stats.source_health:
        lines.append(f"| （情報なし） | - | 0件 | {NOT_AVAILABLE} | {NOT_AVAILABLE} |")
    lines.append("")
    return "\n".join(lines)


def write_job_summary(stats: Optional[DataFreshnessStats]) -> None:
    """Data Freshness Summary＋RSS Source Healthをログへ出力し、GitHub Actions
    実行時（GITHUB_STEP_SUMMARY設定時）はJob Summaryへも追記する。
    ローカル実行時はログ出力のみ（ファイルは作らない）。
    """
    if stats is None:
        logger.info("Data Freshness Summary: 統計を算出できませんでした（%s）。", NOT_AVAILABLE)
        return

    summary_md = render_job_summary_markdown(stats)
    health_md = render_source_health_markdown(stats)

    for line in summary_md.splitlines():
        if line.startswith("- "):
            logger.info("Data Freshness %s", line[2:])
    for entry in sorted(stats.source_health, key=lambda e: (-e.count, e.name)):
        logger.info(
            "RSS Source Health: %s %s %d件 最新=%s",
            entry.name,
            "成功" if entry.ok else "取得失敗",
            entry.count,
            _fmt_dt(entry.newest_published, stats.generated_at.tzinfo),
        )

    summary_path = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary_path:
        try:
            with open(summary_path, "a", encoding="utf-8") as f:
                f.write(summary_md + "\n" + health_md + "\n")
        except OSError as exc:
            logger.warning("Job Summaryへの書き込みに失敗しました（無視して継続します）: %s", exc)
