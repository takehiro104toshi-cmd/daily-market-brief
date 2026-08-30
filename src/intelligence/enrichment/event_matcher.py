"""L2 Event Type / Time Horizon判定（Phase 2-E・rule-based高precision）。

- event type: フレーズ規則1ヒットで判定（フレーズ自体をイベント固有性の高いものに
  限定してprecision確保）。exclude_terms共起で抑止。multi-label許可。
  規則に合致しない記事は**未分類のまま**（OTHERで埋めない）。
- time horizon: 高確信規則のみ（"by 2030"等の明示的な時間表現。**部分一致**で照合——
  年号prefix等のため単語境界を要求しない）。合致しなければ付けない（UNKNOWN扱い）。
- これは「記事が報じる出来事の種類」の分類であり、市場影響・重要度の判定ではない。
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import List, Mapping, Tuple

from .taxonomy import EventTaxonomy, EventTypeDef
from .textmatch import find_term

EVENT_MATCHER_VERSION = "1.0.0"
HORIZON_MATCHER_VERSION = "1.0.0"


@dataclass(frozen=True, kw_only=True)
class EventMatch:
    event_type: EventTypeDef
    evidence_field: str
    evidence_text: str


@dataclass(frozen=True, kw_only=True)
class HorizonMatch:
    horizon: str
    evidence_field: str
    evidence_text: str


def match_event_types(taxonomy: EventTaxonomy, fields: Mapping[str, str]) -> Tuple[EventMatch, ...]:
    combined = " \n ".join(v for v in fields.values() if v)
    out: List[EventMatch] = []
    for event in taxonomy.event_types:
        if not event.phrases:
            continue  # OTHER等: rule自動判定なし
        if any(find_term(combined, t) for t in event.exclude_terms):
            continue
        for field_name, text in fields.items():
            if not text:
                continue
            hit = None
            for phrase in event.phrases:
                found = find_term(text, phrase)
                if found:
                    hit = EventMatch(event_type=event, evidence_field=field_name,
                                     evidence_text=found)
                    break
            if hit:
                out.append(hit)
                break
    return tuple(out)


def match_time_horizon(taxonomy: EventTaxonomy, fields: Mapping[str, str]) -> Tuple[HorizonMatch, ...]:
    for rule in taxonomy.horizon_rules:
        for field_name, text in fields.items():
            if not text:
                continue
            lowered = text.lower()
            for pattern in rule.patterns:
                if pattern.lower() in lowered:
                    return (HorizonMatch(horizon=rule.horizon, evidence_field=field_name,
                                         evidence_text=pattern),)
    return ()
