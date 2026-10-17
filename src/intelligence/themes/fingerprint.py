"""機構 fingerprint（A2 §12）— DERIVED の純関数。canonical record には保存しない（A3 §6）。

- identity_core_fingerprint: 主題 ＋ DRIVER / TRANSMISSION_CHANNEL / AFFECTED_DOMAIN の (type, category, typed_reference)
  （category == OTHER のときだけ normalized_statement の正規化 key を加える）。同一 root の chain 内で変化してはならない
  （変化 ＝ NEW_ROOT_REQUIRED。`revision.revise_observation` が検査する）。
- semantic_fingerprint: identity core ＋ 帰結の (category, observable_target, expected_change) ＋ scope token。
  重複候補（DUPLICATE_CANDIDATE）の提示と変更検出に使う。

除外（A2 §12.2）: root_id、label、description、normalized_statement の文言差（category ≠ OTHER）、taxonomy、evidence の
件数 / id、確度 class、confidence、lifecycle、entity link、mapping、timestamps、provenance、audit。

**fingerprint は identity ではない。** 一致しても root を merge しない（人間 review の材料）。fuzzy / embedding は使わない。
"""
from __future__ import annotations

from typing import Dict, List

from ..core.ids import content_id
from .model import (OTHER_CATEGORY, ComponentType, ThemeObservation, canonical_json, normalize_text)

IDENTITY_CORE_PREFIX = "thcore"
SEMANTIC_FINGERPRINT_PREFIX = "thsem"


def _component_key(component) -> List[str]:
    key = [component.component_type.value, component.category, normalize_text(component.typed_reference)]
    if component.category == OTHER_CATEGORY:
        key.append(normalize_text(component.normalized_statement))
    return key


def identity_core_payload(observation: ThemeObservation) -> Dict[str, object]:
    """identity core の材料（順序独立: 全 list を canonical sort）。"""
    components = [_component_key(c) for c in
                  tuple(observation.mechanism.drivers) + tuple(observation.mechanism.channels)
                  + tuple(observation.mechanism.domains)]
    return {
        "subject": [normalize_text(observation.subject.normalized_subject),
                    normalize_text(observation.subject.typed_reference)],
        "components": sorted(components),
    }


def identity_core_fingerprint(observation: ThemeObservation) -> str:
    return content_id(IDENTITY_CORE_PREFIX, canonical_json(identity_core_payload(observation)))


def semantic_payload(observation: ThemeObservation) -> Dict[str, object]:
    payload = identity_core_payload(observation)
    payload["consequences"] = sorted(
        [c.category, normalize_text(c.observable_target), c.expected_change.value]
        for c in observation.mechanism.consequences)
    payload["scope"] = sorted([s.dimension.value, s.value] for s in observation.scope)
    return payload


def semantic_fingerprint(observation: ThemeObservation) -> str:
    return content_id(SEMANTIC_FINGERPRINT_PREFIX, canonical_json(semantic_payload(observation)))


def identity_core_unchanged(previous: ThemeObservation, candidate: ThemeObservation) -> bool:
    """同一 root の revision として許されるか（identity core が不変か）。"""
    return identity_core_fingerprint(previous) == identity_core_fingerprint(candidate)


__all__ = [
    "IDENTITY_CORE_PREFIX", "SEMANTIC_FINGERPRINT_PREFIX", "identity_core_payload", "identity_core_fingerprint",
    "semantic_payload", "semantic_fingerprint", "identity_core_unchanged",
]
