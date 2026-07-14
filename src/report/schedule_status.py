"""本日の自動生成状況カード（v4.x）— 6スロットの生成状態を HTML カードで表示する。

report_schedule.build_status_context() が組み立てた表示コンテキスト（辞書）だけを受け取り、
HTML 文字列を返す純粋関数。データが無ければ空文字（既存 HTML への影響なし）。
JST 表示。状態: success/running/pending/failed/recovered/stale/skipped。
"""
from __future__ import annotations

import html
from typing import Optional

_STATUS_MARK = {
    "success": ("✅", "生成済み"),
    "recovered": ("✅", "回復生成済み"),
    "running": ("⏳", "生成中"),
    "pending": ("⏳", "待機中"),
    "failed": ("❌", "失敗"),
    "stale": ("⚠️", "処理停止の可能性"),
    "skipped": ("⏭️", "スキップ"),
}

_TRIGGER_LABEL = {
    "schedule": "自動実行",
    "recovery": "回復実行",
    "manual": "手動実行",
    "one_tap": "ワンタップ実行",
    "unknown": "実行",
}


def _esc(text) -> str:
    return html.escape(str(text if text is not None else ""))


def render_schedule_status_card(ctx: Optional[dict]) -> str:
    """生成状況カードの HTML を返す。ctx が None/空なら空文字。"""
    if not ctx or not ctx.get("rows"):
        return ""

    rows_html = []
    for r in ctx["rows"]:
        mark, word = _STATUS_MARK.get(r["status"], ("⏳", "待機中"))
        gen = f"　{_esc(word)} {_esc(r['generated_hm'])}" if r.get("generated_hm") else f"　{_esc(word)}"
        rows_html.append(
            f'<div class="sched-row sched-{_esc(r["status"])}">'
            f'<span class="sched-mark">{mark}</span>'
            f'<span class="sched-time">{_esc(r["time"])}</span>'
            f'<span class="sched-label">{_esc(r["label"])}</span>'
            f'<span class="sched-state">{gen}</span>'
            f"</div>"
        )

    # 現在表示中のレポート
    current_html = ""
    cur = ctx.get("current")
    if cur:
        trig = _TRIGGER_LABEL.get(cur.get("trigger_type", ""), "")
        if cur.get("is_recovery_run"):
            trig = _TRIGGER_LABEL["recovery"]
        gen_at = _esc(cur.get("generated_at", ""))
        current_html = (
            '<p class="sched-current"><strong>現在表示中：</strong>'
            f'{_esc(cur.get("time",""))} {_esc(cur.get("label",""))}'
            + (f'<br>生成日時：{gen_at}' if gen_at else "")
            + (f'<br>実行種別：{_esc(trig)}' if trig else "")
            + "</p>"
        )

    # 欠損・失敗の警告（予定時刻を過ぎたスロットのみ）
    warn_html = ""
    overdue = ctx.get("overdue") or []
    if overdue:
        off = ctx.get("recovery_offset_minutes", 15)
        items = "".join(
            f'<li>⚠️ {_esc(o["time"])} {_esc(o["label"])}は生成されていません。'
            f'次回の回復処理：予定時刻の約{_esc(off)}分後</li>'
            for o in overdue
        )
        warn_html = f'<ul class="sched-warn">{items}</ul>'

    detail = (
        f'<div class="sched-list">{"".join(rows_html)}</div>'
        f"{warn_html}"
    )

    return (
        '<div class="card sched-card no-filter" id="report-schedule">'
        '<h2>本日のレポート生成状況</h2>'
        f'<p class="td-sub">{_esc(ctx.get("date",""))}（JST） 現在 {_esc(ctx.get("now_hm",""))} 時点</p>'
        f"{current_html}"
        "<details><summary>6回の生成状況を表示</summary>"
        f"{detail}"
        '<p class="legend">状態はJST表示。予定時刻より前のスロットは「待機中」です。'
        'GitHub Actions側の失敗は次回の正常生成時に反映されます。'
        '<a href="#report-schedule">本日の過去レポートは history/ 配下に保存されます。</a></p>'
        "</details>"
        "</div>"
    )
