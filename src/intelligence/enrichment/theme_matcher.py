"""L2 Theme Matching（Phase 2-E・rule-based多信号判定）。

安全則:
- strong signal 1つ → タグ付け可（テーマ固有性の高い語句のみをstrongに登録）
- weak signalは**単独では絶対にタグ付けしない**（"power"だけでPowerテーマ確定禁止）。
  同一テーマの相異なるsignalが2つ以上（weak+weak / weak+strong）でのみ成立
- exclude_termsの共起でテーマ抑止（nuclear weapons→原子力(電力)を付けない等）
- role: strong signalがheadlineにあればprimary、それ以外はsecondary
  （primaryの強制はしない——根拠の所在の申告であって重要度判定ではない）
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import List, Mapping, Tuple

from .taxonomy import ThemeDef, ThemeTaxonomy
from .textmatch import find_term

THEME_MATCHER_VERSION = "1.0.0"


@dataclass(frozen=True, kw_only=True)
class ThemeMatch:
    theme: ThemeDef
    strength: str  # "strong" / "multi_weak"
    role: str      # "primary"（strongがheadline） / "secondary"
    signals: Tuple[Tuple[str, str, str], ...]  # (signal語, field, 実マッチ表記)


def match_themes(taxonomy: ThemeTaxonomy, fields: Mapping[str, str]) -> Tuple[ThemeMatch, ...]:
    combined = " \n ".join(v for v in fields.values() if v)
    out: List[ThemeMatch] = []
    for theme in taxonomy.themes:
        if any(find_term(combined, t) for t in theme.exclude_terms):
            continue
        strong_hits: List[Tuple[str, str, str]] = []
        weak_hits: List[Tuple[str, str, str]] = []
        for field_name, text in fields.items():
            if not text:
                continue
            for signal in theme.strong_signals:
                found = find_term(text, signal)
                if found:
                    strong_hits.append((signal, field_name, found))
            for signal in theme.weak_signals:
                found = find_term(text, signal)
                if found:
                    weak_hits.append((signal, field_name, found))
        # 同一signal語の複数field出現は1信号と数える（distinct signal数で判定）
        distinct_strong = {s for s, _f, _m in strong_hits}
        distinct_all = distinct_strong | {s for s, _f, _m in weak_hits}
        if distinct_strong:
            strength = "strong"
        elif len(distinct_all) >= 2:
            strength = "multi_weak"
        else:
            continue  # weak単独→タグ付けしない（missed tagを許容）
        role = "primary" if any(f == "headline" for _s, f, _m in strong_hits) else "secondary"
        evidence = tuple(dict.fromkeys(strong_hits + weak_hits))[:4]
        out.append(ThemeMatch(theme=theme, strength=strength, role=role, signals=evidence))
    return tuple(out)
