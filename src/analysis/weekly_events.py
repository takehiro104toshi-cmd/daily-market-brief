"""Weekly Event Impact Calendar（v2.7）— 今週の重要イベント・経済指標。

直近1週間（今日〜7日後）に予定されているイベントを、日数・時刻・重要度・
影響対象つきで見える化する。「今週どのイベント前後で相場が動きやすいか」を
把握し、自分自身の長期資産形成・投資判断に役立てることを最優先目的とする。

データ源はconfig.yamlのmacro_events（ユーザー管理の登録情報）と
決算発表予定（公開情報）のみ。新しい外部APIは追加しない（将来拡張）。
重要度・影響対象・想定される影響は、イベント名キーワードと人手による
対応表（_EVENT_RULES）の照合結果であり、AIによる新たな予測ではない。
予定が無い場合は無理に生成せず、空リストを返す（表示側で
「直近1週間の重要イベントは登録されていません」と表示する）。
"""
from __future__ import annotations

import re
from datetime import datetime
from typing import List, Optional

from ..collectors.earnings import EarningsEvent
from ..report.format_utils import stars
from .models import WeeklyEventEntry
from .source_trust import trust_for_source

WEEK_DAYS = 7
DEFAULT_STARS = 3

_TIME_RE = re.compile(r"^(\d{1,2}):(\d{2})$")

# イベント名キーワード → 重要度・影響対象・想定される影響の人手対応表（登録情報）。
# 「〜なら…」という条件付きの整理のみで、どちらに転ぶかの予測はしない。
_EVENT_RULES = [
    {
        "keywords": ("FOMC", "米連邦公開市場委員会", "政策金利"),
        "region": "米国", "category": "金融政策", "stars": 5,
        "targets": ["米金利", "ドル円", "米国株", "日本株", "グロース株"],
        "expected_impact": "タカ派なら米金利上昇・ドル高・グロース株に逆風、ハト派なら利下げ期待で株高要因になりやすいと考えられます。",
        "why": "世界の金利の起点となる米国の政策金利を決める会合で、株式・為替・債券すべてに波及するためです。",
        "watch_points": ["政策金利の変更有無", "声明文・ドットチャートの変化", "議長会見のトーン"],
        "themes": ["金融政策", "金利"],
    },
    {
        "keywords": ("日銀", "金融政策決定会合"),
        "region": "日本", "category": "金融政策", "stars": 5,
        "targets": ["日経平均", "TOPIX", "ドル円", "銀行", "不動産"],
        "expected_impact": "利上げ・引き締め方向なら円高・銀行株に追い風/不動産に逆風、現状維持なら円安基調の継続要因になりやすいと考えられます。",
        "why": "円金利と為替の方向を決める日本市場最大級のイベントで、銀行・不動産など金利敏感株に直結するためです。",
        "watch_points": ["政策金利・長期金利操作の変更", "総裁会見", "国債買い入れ方針"],
        "themes": ["金融政策", "金利"],
    },
    {
        "keywords": ("雇用統計",),
        "region": "米国", "category": "経済指標", "stars": 5,
        "targets": ["米金利", "ドル円", "米国株", "NASDAQ"],
        "expected_impact": "雇用が強ければ利下げ観測後退で金利上昇・ドル高、弱ければ景気減速懸念と利下げ期待が交錯しやすいと考えられます。",
        "why": "FRBの利下げ判断を左右する最重要の月次指標のためです。",
        "watch_points": ["非農業部門雇用者数", "失業率", "平均時給の伸び"],
        "themes": ["金融政策", "金利"],
    },
    {
        "keywords": ("CPI", "消費者物価"),
        "region": "米国", "category": "経済指標", "stars": 5,
        "targets": ["米金利", "ドル円", "NASDAQ", "半導体", "グロース株"],
        "expected_impact": "インフレ再加速なら米金利上昇・ドル高・グロース株に逆風、鈍化なら利下げ期待で株高要因になりやすいと考えられます。",
        "why": "インフレの方向がFRBの金融政策を直接左右するためです。",
        "watch_points": ["総合・コアの前月比/前年比", "住居費の伸び", "市場予想との乖離"],
        "themes": ["金融政策", "金利"],
    },
    {
        "keywords": ("PPI", "生産者物価"),
        "region": "米国", "category": "経済指標", "stars": 4,
        "targets": ["米金利", "ドル円", "米国株"],
        "expected_impact": "川上のインフレ圧力が強ければCPIへの波及が意識され、金利上昇要因になりやすいと考えられます。",
        "why": "企業段階の物価で、CPIに先行しやすい指標のためです。",
        "watch_points": ["コアPPIの伸び", "CPIとの整合性"],
        "themes": ["金融政策", "金利"],
    },
    {
        "keywords": ("ISM",),
        "region": "米国", "category": "経済指標", "stars": 4,
        "targets": ["米国株", "米金利", "景気敏感株"],
        "expected_impact": "50割れが続けば景気減速懸念、改善すれば景気敏感株の見直しにつながりやすいと考えられます。",
        "why": "米国の製造業・サービス業の体感景気をいち早く示す指標のためです。",
        "watch_points": ["50（好不況の分岐）との位置関係", "新規受注・雇用の内訳"],
        "themes": ["景気循環"],
    },
    {
        "keywords": ("小売売上高",),
        "region": "米国", "category": "経済指標", "stars": 4,
        "targets": ["米国株", "消費", "米金利"],
        "expected_impact": "個人消費が強ければ景気底堅さとインフレ持続が同時に意識されやすいと考えられます。",
        "why": "米GDPの約7割を占める個人消費の勢いを示すためです。",
        "watch_points": ["前月比の伸び", "コントロールグループ"],
        "themes": ["景気循環"],
    },
    {
        "keywords": ("GDP",),
        "region": "米国", "category": "経済指標", "stars": 4,
        "targets": ["米国株", "米金利", "ドル円"],
        "expected_impact": "予想を上回れば景気楽観・金利上昇、下回れば減速懸念が意識されやすいと考えられます。",
        "why": "景気全体の方向を確認する基礎指標のためです。",
        "watch_points": ["前期比年率", "個人消費・設備投資の内訳"],
        "themes": ["景気循環"],
    },
    {
        "keywords": ("SQ", "特別清算指数"),
        "region": "日本", "category": "需給", "stars": 4,
        "targets": ["日経平均", "TOPIX", "先物・オプション"],
        "expected_impact": "先物・オプションの清算に伴い、寄り付き前後で値動きが荒くなりやすいと考えられます。",
        "why": "デリバティブ清算に伴う機械的な売買が集中し、短期の需給が大きく動く日だからです。",
        "watch_points": ["SQ値と日経平均の位置関係", "寄り付きの出来高"],
        "themes": [],
    },
    {
        "keywords": ("IPO", "新規上場"),
        "region": "日本", "category": "需給", "stars": 3,
        "targets": ["新興株", "グロース市場"],
        "expected_impact": "大型IPOは新興株の資金がIPOへ向かい、既存新興株の需給が緩みやすいと考えられます。",
        "why": "市場の資金配分（需給）が変わるイベントのためです。",
        "watch_points": ["初値の強さ", "公開規模"],
        "themes": [],
    },
    {
        "keywords": ("決算",),
        "region": "日本/米国", "category": "決算", "stars": 4,
        "targets": ["個別株", "関連セクター"],
        "expected_impact": "結果とガイダンス次第で、当該銘柄だけでなく同業種・サプライチェーン全体へ波及しやすいと考えられます。",
        "why": "業績の実額とガイダンスが、テーマの持続力を検証する材料になるためです。",
        "watch_points": ["ガイダンスの上方/下方修正", "市場予想との乖離", "同業他社への読み替え"],
        "themes": [],
    },
    {
        "keywords": ("要人発言", "議長", "総裁講演"),
        "region": "日米", "category": "金融政策", "stars": 3,
        "targets": ["ドル円", "米金利", "日本株"],
        "expected_impact": "金融政策の先行きに関する発言があれば、金利・為替が短時間で動きやすいと考えられます。",
        "why": "政策変更のヒントが事前に示されることがあるためです。",
        "watch_points": ["利下げ/利上げへの言及", "経済認識の変化"],
        "themes": ["金融政策"],
    },
]

_DEFAULT_RULE = {
    "region": "—", "category": "イベント", "stars": DEFAULT_STARS,
    "targets": ["市場全体"],
    "expected_impact": "結果次第で関連市場の変動要因になる可能性があります（詳細は公開情報をご確認ください）。",
    "why": "config.yamlに登録された注目イベントです。",
    "watch_points": ["結果と市場予想との乖離"],
    "themes": [],
}


def _match_rule(label: str) -> dict:
    for rule in _EVENT_RULES:
        if any(kw in label for kw in rule["keywords"]):
            return rule
    return _DEFAULT_RULE


def _parse_date(date_str: str) -> Optional[datetime]:
    try:
        return datetime.strptime(str(date_str).strip()[:10], "%Y-%m-%d")
    except (ValueError, TypeError):
        return None


def _countdown_text(days_until: int, time_str: str, now: datetime, event_date: datetime) -> str:
    """日本時間基準のカウントダウン表示（「本日21:30」「あと1日 5時間」「あと3日」）。

    時刻が登録されていない場合は日数のみ（「あと何時間」は推測しない）。
    """
    if time_str:
        m = _TIME_RE.match(time_str)
        if m:
            event_dt = event_date.replace(hour=int(m.group(1)), minute=int(m.group(2)), tzinfo=now.tzinfo)
            delta_hours = max(0, int((event_dt - now).total_seconds() // 3600))
            if days_until <= 0:
                return f"本日{time_str}（あと{delta_hours}時間）"
            days = delta_hours // 24
            hours = delta_hours % 24
            return f"あと{days}日 {hours}時間（{time_str}）"
    if days_until <= 0:
        return "本日"
    if days_until == 1:
        return "あと1日（明日）"
    return f"あと{days_until}日"


def _build_entry(
    label: str,
    date_str: str,
    time_str: str,
    now: datetime,
    category_override: str = "",
    source: str = "登録情報",
    fetched_at: str = "",
) -> Optional[WeeklyEventEntry]:
    event_date = _parse_date(date_str)
    if event_date is None:
        return None
    days_until = (event_date.date() - now.date()).days
    if days_until < 0 or days_until > WEEK_DAYS:
        return None  # 過去イベント・1週間より先は表示しない
    rule = _match_rule(label)
    star_count = rule["stars"]
    # v3.0（③）: Source Trust。自動取得は情報源名から★判定、登録情報（手入力）は
    # ユーザー自身の管理情報として★★★★★扱い。
    source_stars = stars(5, max_stars=5) if source == "登録情報" else trust_for_source(source).stars
    return WeeklyEventEntry(
        label=label,
        date_str=date_str,
        time_str=time_str,
        region=rule["region"],
        category=category_override or rule["category"],
        stars=stars(star_count, max_stars=5),
        importance=star_count * 20,
        days_until=days_until,
        countdown_text=_countdown_text(days_until, time_str, now, event_date),
        impact_targets=list(rule["targets"]),
        expected_impact=rule["expected_impact"],
        why_important=rule["why"],
        watch_points=list(rule["watch_points"]),
        related_themes=list(rule["themes"]),
        source=source,
        source_stars=source_stars,
        fetched_at=fetched_at,
    )


def build_weekly_event_calendar(
    now: datetime,
    macro_events: List[dict],
    earnings_events: Optional[List[EarningsEvent]] = None,
) -> List[WeeklyEventEntry]:
    """直近1週間（今日〜7日後）のイベントを「近い順→重要度順」で返す。

    macro_eventsの各エントリは date / label に加えて、任意で time（"21:30"等、
    日本時間）を登録できる。timeがあれば「あと◯日 ◯時間」まで表示する。
    """
    entries: List[WeeklyEventEntry] = []
    for event in macro_events or []:
        label = event.get("label", "")
        if not label:
            continue
        # v3.0（③）: 自動取得イベントは source/fetched_at を持つ。手入力は「登録情報」。
        entry = _build_entry(
            label,
            event.get("date", ""),
            str(event.get("time", "") or ""),
            now,
            source=event.get("source", "") or "登録情報",
            fetched_at=str(event.get("fetched_at", "") or ""),
        )
        if entry:
            entries.append(entry)

    for e in earnings_events or []:
        if not e.date:
            continue
        entry = _build_entry(f"{e.name}（{e.ticker}）決算発表", str(e.date), "", now, category_override="決算")
        if entry:
            entries.append(entry)

    # 近い順（days_until昇順）→ 同日内は重要度の高い順 → ラベル順（安定化）
    entries.sort(key=lambda x: (x.days_until, -x.importance, x.label))
    return entries
