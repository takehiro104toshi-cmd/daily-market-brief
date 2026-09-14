"""Morning Brief の Markdown 表示（Phase 4 P4-1B）。

`MorningBrief`（P4-1A の projection）**だけ**を入力に、決定論的な Markdown 文字列を作る。
表示層であり、内容を作らない:

- 新しい文を書かない・言い換えない・claim を選び直さない・並べ替えない
- validation を再実行しない・欠落を埋めない・`rule_ref` を直さない
- file / store / data root / network / 時刻 / 乱数 / 環境変数に触れない
- 入力の `MorningBrief` を書き換えない

provenance の扱いは **pattern A**: claim_id / fact_id / context_id / digest の類は
customer-facing Markdown へ出さず、`MorningBrief` 側に残したままにする
（技術 footer も隠し HTML comment も作らない）。

claim 本文（`（経験則 JP_DIR_001）` のような出典表記を含む）は Compass の
quality gate を通過した**承認済みの文**であり、ここでは**そのまま**表示する。
"""
from __future__ import annotations

import re
from typing import List

from .model import BriefPoint, BriefTier2, BriefTier3, MorningBrief

#: 見出し（P4-1 の三段。ここで 4 つ目の分析段を作らない）
H_TITLE = "モーニングブリーフ"
H_TIER1 = "30秒版｜今日のお客様向け一言"
H_TIER2 = "3分版｜今日のポイント"
H_TIER3 = "詳細版｜相場の見通し＋なぜ"
H_COVERAGE = "対象範囲・欠落"
H_WHY = "なぜ"
H_RISK = "反対材料"

#: 欠落次元のラベル（次元名そのものは変換せず、市場観へ読み替えない）
L_MISSING = "欠落した観測次元"
L_UNRELIABLE = "取り扱いに注意が必要な次元"
L_DIRECTION = "方向"
L_CONFIDENCE = "確度"
L_HORIZON = "対象期間"

#: 提示できないときの固定表記（市場コメントを代わりに書かない）
UNAVAILABLE = "（この区分は本日提示できません）"
UNAVAILABLE_WITH_REASON = "（この区分は本日提示できません。理由: {reason}）"

#: 理由として表示してよい形（契約語彙のみ。例外文や自由文は出さない）
_SAFE_REASON = re.compile(r"\A[a-z0-9_]{1,64}\Z")
#: 行頭の `#` は節構造を壊すため escape する（表示文字は変わらない）
_LEADING_HASH = re.compile(r"\A(\s*)#")


def _safe_lines(text: str) -> List[str]:
    """本文を行単位で安全化する。**文字は足さない・削らない・置き換えない。**

    行頭 `#` だけ escape（Markdown 上の見た目は `#` のまま）。
    """
    return [_LEADING_HASH.sub(r"\1\\#", line) for line in text.split("\n")]


def _paragraph(text: str) -> List[str]:
    return _safe_lines(text)


def _bullet(text: str) -> List[str]:
    """箇条書き 1 件。複数行の本文は継続行を字下げして list を壊さない。"""
    lines = _safe_lines(text)
    return [f"- {lines[0]}"] + [f"  {line}" for line in lines[1:]]


def _bullets(points: "tuple[BriefPoint, ...]") -> List[str]:
    out: List[str] = []
    for point in points:
        out.extend(_bullet(point.text))
    return out


def _unavailable(reason: str) -> str:
    """理由は契約語彙のときだけ出す（内部例外文を出さないための fail-closed）。"""
    if reason and _SAFE_REASON.match(reason):
        return UNAVAILABLE_WITH_REASON.format(reason=reason)
    return UNAVAILABLE


def _tier2_block(tier2: BriefTier2) -> List[str]:
    body: List[str] = []
    if tier2.available:
        body.extend(_bullets(tier2.points))
    else:
        body.append(_unavailable(tier2.unavailable_reason))
    coverage: List[str] = []
    coverage.extend(_bullets(tier2.coverage))
    if tier2.missing_dimensions:
        coverage.append(f"- {L_MISSING}: " + "、".join(tier2.missing_dimensions))
    if tier2.unreliable_dimensions:
        coverage.append(f"- {L_UNRELIABLE}: " + "、".join(tier2.unreliable_dimensions))
    if coverage:
        body.extend(["", f"### {H_COVERAGE}", ""] + coverage)
    return body


def _tier3_block(tier3: BriefTier3) -> List[str]:
    if not tier3.available or tier3.outlook is None:
        return [_unavailable(tier3.unavailable_reason)]
    outlook = tier3.outlook
    body: List[str] = [
        f"**{L_DIRECTION}**: {outlook.direction} ／ "
        f"**{L_CONFIDENCE}**: {outlook.confidence} ／ "
        f"**{L_HORIZON}**: {outlook.horizon}",
        "",
    ]
    body.extend(_bullets(tier3.outlook_points))
    if tier3.why:
        body.extend(["", f"### {H_WHY}", ""] + _bullets(tier3.why))
    if tier3.risk:
        body.extend(["", f"### {H_RISK}", ""] + _bullets(tier3.risk))
    return body


def render_morning_brief_markdown(brief: MorningBrief) -> str:
    """`MorningBrief` を Markdown 文字列へ描画する（純関数・同じ brief → 同じ bytes）。"""
    lines: List[str] = [f"# {H_TITLE}（{brief.session_date}）", ""]

    lines.append(f"## {H_TIER1}")
    lines.append("")
    if brief.tier1.available and brief.tier1.text:
        lines.extend(_paragraph(brief.tier1.text))
    else:
        lines.append(_unavailable(brief.tier1.unavailable_reason))
    lines.append("")

    lines.append(f"## {H_TIER2}")
    lines.append("")
    lines.extend(_tier2_block(brief.tier2))
    lines.append("")

    lines.append(f"## {H_TIER3}")
    lines.append("")
    lines.extend(_tier3_block(brief.tier3))

    return "\n".join(lines).rstrip("\n") + "\n"
