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

本文は `BriefPoint.display_text` / `BriefTier1.display_text`（P4-1A projection が作った
customer-safe テキスト）を**そのまま**表示する。逐語 `text` は brief 側に残るが描画しない。

構造化された値（方向・確度・対象期間・次元キー・充足状況）は、**明示的な対応表**だけで
日本語ラベルへ置き換える。対応表に無い値は捏造せず `UnmappedDisplayValue` で fail closed。

「提示できない理由」も同じ規律に従う。内部の機械可読 reason は model 側にそのまま残し、
表示面では `REASON_JA` の**閉じた対応表**だけを通して顧客向け日本語へ写像する。
生の内部語彙は顧客向け Markdown へ出さない（表に無い理由は汎用文へ落とす）。
"""
from __future__ import annotations

import re
from typing import Dict, List, Optional, Set

from .model import BriefPoint, BriefTier2, BriefTier3, MorningBrief


class UnmappedDisplayValue(KeyError):
    """表示対応表に無い構造化値。**推測で表示しない**ための fail-closed 例外。"""

#: 見出し（P4-1 の三段。ここで 4 つ目の分析段を作らない）
H_TITLE = "モーニングブリーフ"
H_TIER1 = "30秒版｜今日のお客様向け一言"
H_TIER2 = "3分版｜今日のポイント"
H_TIER3 = "詳細版｜相場の見通し＋なぜ"
H_COVERAGE = "対象範囲・欠落"
H_WHY = "なぜ"
H_RISK = "反対材料"

#: 欠落・注意項目の見出し語（市場観へは読み替えない。可否だけを述べる）
L_MISSING = "現在確認できていない項目"
L_UNRELIABLE = "取り扱いに注意が必要な項目"
L_DIRECTION = "方向"
L_CONFIDENCE = "確度"
L_HORIZON = "対象期間"

#: 提示できないときの固定表記（市場コメントを代わりに書かない）
UNAVAILABLE = "（この区分は本日提示できません）"
#: 同じ説明を繰り返さないための短い中立表現（2 区分目以降）
SHORT_UNAVAILABLE = "本日はこの区分の提示を見送ります。"

#: 顧客向けの「出せない理由」表現。**承認済みの 4 文だけ**を使い、自由文を作らない。
#: 市場の見立てを代わりに述べないこと（見送る事実だけを述べる）。
S1_MATERIAL_NOT_ASSEMBLED = "本日は判断の材料が十分に揃わなかったため、この区分の提示を見送ります。"
S2_COUNTER_MATERIAL = "本日は反対材料を十分に確認できないため、一方向に偏った見通しの提示は見送ります。"
S3_GROUNDING_INSUFFICIENT = "本日は根拠が確認できた内容が残らなかったため、この区分の提示を見送ります。"
S4_GENERIC = "本日はこの区分を提示できません。"
#: 行頭の `#` は節構造を壊すため escape する（表示文字は変わらない）
_LEADING_HASH = re.compile(r"\A(\s*)#")


# ---------------------------------------------------------------- 表示対応表（明示・完全）
#: OutlookDirection の値 → 顧客向け表現（方向の強弱を足さない）
DIRECTION_JA: Dict[str, str] = {
    "UPWARD_BIAS": "上方向にやや傾く",
    "DOWNWARD_BIAS": "下方向にやや傾く",
    "RANGE_BOUND": "一定の範囲で推移しやすい",
    "MIXED": "強弱が混在する",
    "UNCERTAIN": "方向は定めにくい",
}
#: Confidence の値 → 顧客向け表現
CONFIDENCE_JA: Dict[str, str] = {"HIGH": "高", "MEDIUM": "中", "LOW": "低"}
#: outlook horizon の値 → 顧客向け表現
HORIZON_JA: Dict[str, str] = {"next_tokyo_session": "次の東京市場"}
#: 観測次元キー → 顧客向け表現（market state 8 次元 + market internals 5 次元）
DIMENSION_JA: Dict[str, str] = {
    "japan_equities": "日本株",
    "nikkei_vs_topix": "日経平均とTOPIXの相対動向",
    "nt_ratio": "NT倍率",
    "japan_rates": "国内金利",
    "us_rates_2y": "米2年金利",
    "us_rates_10y": "米10年金利",
    "us_curve": "米国の利回り曲線",
    "usd_jpy": "ドル円",
    "breadth": "値上がり銘柄の広がり",
    "turnover": "売買代金",
    "sector_leadership": "業種の強弱",
    "size_leadership": "大型・小型の強弱",
    "investor_flow": "投資部門別の売買動向",
}
#: ContextStatus の値 → 顧客向け表現（信頼性の意味は変えない）
STATUS_JA: Dict[str, str] = {
    "AVAILABLE": "確認済み",
    "MISSING": "未確認",
    "STALE": "更新遅れ",
    "INSUFFICIENT_HISTORY": "履歴不足",
    "CONFLICTED": "情報が一致しない",
    "LIMITED_USE": "限定的に利用",
    "NOT_ENTITLED": "取得対象外",
}
#: 内部の機械可読 reason → 顧客向け表現（**閉じた対応表**）。
#: 内部語彙（`no_counter_material` など）は `MorningBrief` 側にそのまま残し、
#: 表示面ではここでだけ承認済みの日本語へ写像する。表に無い理由は生値を出さず
#: `S4_GENERIC` へ落とす（表示は fail closed、配信そのものは止めない）。到達しうる
#: 理由が写像漏れのまま増えた場合は test が build を落とす。
REASON_JA: Dict[str, str] = {
    # 材料そのものが揃っていない
    "empty_evidence_package": S1_MATERIAL_NOT_ASSEMBLED,
    "no_lead_context": S1_MATERIAL_NOT_ASSEMBLED,
    "lead_context_not_fresh": S1_MATERIAL_NOT_ASSEMBLED,
    "no_claims": S1_MATERIAL_NOT_ASSEMBLED,
    "draft_not_usable": S1_MATERIAL_NOT_ASSEMBLED,
    # 反対材料が確認できないので一方向に語らない（規律であって不足ではない）
    "no_counter_material": S2_COUNTER_MATERIAL,
    "no_grounded_counter_case": S2_COUNTER_MATERIAL,
    # 候補はあったが根拠付きで残らなかった
    "no_grounded_headline": S3_GROUNDING_INSUFFICIENT,
    "no_grounded_why": S3_GROUNDING_INSUFFICIENT,
    "no_grounded_risk": S3_GROUNDING_INSUFFICIENT,
    "no_grounded_outlook": S3_GROUNDING_INSUFFICIENT,
    "no_grounded_points": S3_GROUNDING_INSUFFICIENT,
    "one_liner_unavailable": S3_GROUNDING_INSUFFICIENT,
}


def _label(mapping: Dict[str, str], value: str, kind: str) -> str:
    """対応表にある値だけを表示する。無ければ fail closed（生値も代替文も出さない）。"""
    try:
        return mapping[value]
    except KeyError:
        raise UnmappedDisplayValue(f"{kind}:{value}") from None


def _dimension_phrase(key: str, status: str) -> str:
    """`日経平均とTOPIXの相対動向（更新遅れ）` の形。status が無ければラベルのみ。"""
    label = _label(DIMENSION_JA, key, "dimension")
    return f"{label}（{_label(STATUS_JA, status, 'status')}）" if status else label


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
        out.extend(_bullet(point.display_text))
    return out


def _unavailable(reason: str, stated: Optional[Set[str]] = None) -> str:
    """出せない区分の表記。**内部語彙は決して顧客面へ出さない。**

    以前は理由の**形**（snake_case）だけを見て表示を許可していたため、Compass 内部の
    abstain 詳細 `no_counter_material` がそのまま公開 /v2 の Markdown に出ていた。
    ここでは `REASON_JA` の閉じた対応表だけを通し、表に無い理由は生値ではなく
    `S4_GENERIC` へ落とす。

    `stated` を渡すと **描画 1 回の中だけ**で重複を抑制する（同じ説明を 3 区分に
    繰り返さない）。2 度目以降は `SHORT_UNAVAILABLE` になる。これは表示だけの処理で、
    tier の可否も内部 `unavailable_reason` も `MorningBrief` も変えない。
    """
    message = UNAVAILABLE if not reason else REASON_JA.get(reason, S4_GENERIC)
    if stated is None:
        return message
    if message in stated:
        return SHORT_UNAVAILABLE
    stated.add(message)
    return message


def _tier2_block(tier2: BriefTier2, stated: Set[str]) -> List[str]:
    body: List[str] = []
    if tier2.available:
        body.extend(_bullets(tier2.points))
    else:
        body.append(_unavailable(tier2.unavailable_reason, stated))
    coverage: List[str] = []
    coverage.extend(_bullets(tier2.coverage))
    status = dict(tier2.dimension_status)
    missing = tuple(tier2.missing_dimensions)
    # unreliable は missing を含む上位集合。同じ項目を 2 行に出さない（表示上の重複のみ除去）
    unreliable = tuple(k for k in tier2.unreliable_dimensions if k not in set(missing))
    for heading, keys in ((L_MISSING, missing), (L_UNRELIABLE, unreliable)):
        if keys:
            coverage.append(f"- {heading}: " + "、".join(
                _dimension_phrase(k, status.get(k, "")) for k in keys))
    if coverage:
        body.extend(["", f"### {H_COVERAGE}", ""] + coverage)
    return body


def _tier3_block(tier3: BriefTier3, stated: Set[str]) -> List[str]:
    if not tier3.available or tier3.outlook is None:
        return [_unavailable(tier3.unavailable_reason, stated)]
    outlook = tier3.outlook
    body: List[str] = [
        f"**{L_DIRECTION}**: {_label(DIRECTION_JA, outlook.direction, 'direction')} ／ "
        f"**{L_CONFIDENCE}**: {_label(CONFIDENCE_JA, outlook.confidence, 'confidence')} ／ "
        f"**{L_HORIZON}**: {_label(HORIZON_JA, outlook.horizon, 'horizon')}",
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
    # 重複抑制は**この描画の中だけ**の局所状態。brief にも module にも持たせない。
    stated: Set[str] = set()
    lines: List[str] = [f"# {H_TITLE}（{brief.session_date}）", ""]

    lines.append(f"## {H_TIER1}")
    lines.append("")
    if brief.tier1.available and brief.tier1.display_text:
        lines.extend(_paragraph(brief.tier1.display_text))
    else:
        lines.append(_unavailable(brief.tier1.unavailable_reason, stated))
    lines.append("")

    lines.append(f"## {H_TIER2}")
    lines.append("")
    lines.extend(_tier2_block(brief.tier2, stated))
    lines.append("")

    lines.append(f"## {H_TIER3}")
    lines.append("")
    lines.extend(_tier3_block(brief.tier3, stated))

    return "\n".join(lines).rstrip("\n") + "\n"
