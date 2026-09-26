"""P7-A4a — 決定論の提示の計画（`NarrativeSynthesis` → `NarrativePresentation`。構造だけ。文章・LLM・永続化なし）。

`plan_presentation(synthesis)`: 純関数。A1 の synthesis の claim を、`presentation_model` の静的な規則表で閉じた section と
見せ方の義務（REQUIRED ／ ELIGIBLE）に割り当て、決まった提示の順に並べる。

規則:
- 入力は A1 の synthesis だけ。store・A2 の adapter・A3 の engine・Phase 6・filesystem・時計・乱数・network を使わない。
- synthesis を盲信しない: 型・属性の集合を確かめ、A1 の厳格な復元（canonical JSON → `from_json`）で作り直し、
  synthesis id・claim id・認識 class・claim kind・predicate・ref・knowledge pin の改ざんを fail closed で拒否する。
- 知っている version だけを受ける（A1 の schema と A3 の規則表 `narrative_synthesis_rules` 0.1.0）。A3 を import しない
  （名前と version は複製し、一致は test で固定する）。
- claim 1 つ → item 1 つ。claim を落とさない・足さない・まとめない・意味を変えない（全 claim の対応を検査する）。
- 並びは section の提示の順 → Theme の root id の組 → claim id。score・重要度・Theme の順位を使わない。
- `validate_display_selection`: A4b が見せる claim の選び方の検査。見せる Theme の REQUIRED の item（反証・無効化・
  不確実性・代替）を落とした選び方を拒否する（SUPPORTS だけを見せて反証を黙って隠すことを許さない）。

契約: `docs/databank/PHASE7_NARRATIVE_PRESENTATION_DIFF_CONTRACT.md`。
"""
from __future__ import annotations

from dataclasses import fields
from typing import Iterable, List, Tuple

from .presentation_model import (SECTION_ORDER, NarrativePresentation, NarrativePresentationError, PresentationItem,
                                 PresentationSection, Visibility, item_order_key)
from .synthesis_model import (REF_TYPES, EvidenceAttachmentRef, NarrativeClaim, NarrativeKind, NarrativeModelError,
                              NarrativeSynthesis, Predicate, RelationAssertionRef, RELATION_PREDICATES)

#: この planner が意味を知っている入力（知らない version は fail closed）
SUPPORTED_SYNTHESIS_SCHEMA_VERSION = "narrative_synthesis:0.1.0"
SUPPORTED_CLAIM_SCHEMA_VERSION = "narrative_claim:0.1.0"
#: A3 の規則表（A3 を import しない。名前と version の一致は test で固定する）
SYNTHESIS_RULESET_NAME = "narrative_synthesis_rules"
SUPPORTED_SYNTHESIS_RULESET_VERSIONS: Tuple[str, ...] = ("0.1.0",)
SUPPORTED_KINDS = (NarrativeKind.THEME_STATE, NarrativeKind.THEME_SET)


def _fail(code: str, detail: str = "") -> None:
    raise NarrativePresentationError(code, detail)


def _code(exc: Exception) -> str:
    if isinstance(exc, (NarrativeModelError, NarrativePresentationError)):
        return exc.code
    return type(exc).__name__


def _exact_fields(value: object, expected_type: type) -> None:
    if type(value) is not expected_type:
        _fail("SYNTHESIS_INTEGRITY_FAILURE", expected_type.__name__)
    if set(vars(value)) != {f.name for f in fields(expected_type)}:    # 後から足された属性（score 等）を拒否
        _fail("SYNTHESIS_INTEGRITY_FAILURE", expected_type.__name__)


# ---------------------------------------------------------------- 入力の再検証（盲信しない）

def revalidate_synthesis(synthesis: object) -> NarrativeSynthesis:
    """synthesis を A1 の厳格な復元で作り直し、同じ内容・同じ id であることを確かめる（作り直した方を返す）。"""
    if not isinstance(synthesis, NarrativeSynthesis):
        _fail("INVALID_SYNTHESIS", "a NarrativeSynthesis is required")
    if synthesis.kind not in SUPPORTED_KINDS:
        _fail("UNSUPPORTED_PRESENTATION_KIND", "kind")
    try:
        data = synthesis.to_dict()
        schemas = (data["schema_version"], {claim["schema_version"] for claim in data["claims"]})
    except Exception as exc:
        raise NarrativePresentationError("SYNTHESIS_INTEGRITY_FAILURE", _code(exc)) from None
    if schemas != (SUPPORTED_SYNTHESIS_SCHEMA_VERSION, {SUPPORTED_CLAIM_SCHEMA_VERSION}):
        _fail("UNSUPPORTED_SYNTHESIS_VERSION", "synthesis schema")
    try:
        _exact_fields(synthesis, NarrativeSynthesis)
        for claim in synthesis.claims:
            _exact_fields(claim, NarrativeClaim)
            for ref in claim.refs:
                if type(ref) not in REF_TYPES.values():
                    _fail("SYNTHESIS_INTEGRITY_FAILURE", "ref")
                _exact_fields(ref, type(ref))
        rebuilt = NarrativeSynthesis.from_json(synthesis.to_canonical_json())   # A1 の検査を最初から通し直す
        if rebuilt != synthesis or rebuilt.to_canonical_json() != synthesis.to_canonical_json():
            _fail("SYNTHESIS_INTEGRITY_FAILURE", "synthesis identity")
    except NarrativePresentationError:
        raise
    except Exception as exc:                                               # 改ざんされた値は理由の code だけを返す
        raise NarrativePresentationError("SYNTHESIS_INTEGRITY_FAILURE", _code(exc)) from None
    if dict(rebuilt.knowledge_pins).get(SYNTHESIS_RULESET_NAME) not in SUPPORTED_SYNTHESIS_RULESET_VERSIONS:
        _fail("UNSUPPORTED_SYNTHESIS_VERSION", "synthesis ruleset")
    subjects = set(rebuilt.subject_root_ids)
    if not all(set(claim.roots()) <= subjects for claim in rebuilt.claims):  # 規則表 0.1.0 は subject の外を作らない
        _fail("SYNTHESIS_INTEGRITY_FAILURE", "CLAIM_OUTSIDE_SUBJECTS")
    return rebuilt


# ---------------------------------------------------------------- claim → item → section

def item_for_claim(claim: NarrativeClaim) -> PresentationItem:
    """claim の構造上の属性だけを写す（role と assertion class は ref にあるものをそのまま運ぶ）。"""
    role = None
    assertion = None
    if claim.predicate is Predicate.EVIDENCE_ATTACHED:
        role = [ref for ref in claim.refs if isinstance(ref, EvidenceAttachmentRef)][0].role
    if claim.predicate in RELATION_PREDICATES:
        assertion = [ref for ref in claim.refs if isinstance(ref, RelationAssertionRef)][0].assertion_class
    return PresentationItem(claim_id=claim.claim_id, theme_root_ids=claim.roots(),
                            epistemic_class=claim.epistemic_class, claim_kind=claim.claim_kind,
                            predicate=claim.predicate, uncertainty_code=claim.uncertainty_code, evidence_role=role,
                            assertion_class=assertion)


def plan_presentation(synthesis: NarrativeSynthesis) -> NarrativePresentation:
    """A1 の synthesis → 提示の構造（純関数。同じ synthesis と同じ規則 → 同じ canonical bytes と id）。"""
    trusted = revalidate_synthesis(synthesis)
    items = [item_for_claim(claim) for claim in trusted.claims]
    sections = []
    for section in SECTION_ORDER:                                          # 提示の順（重要度ではない）
        members = sorted((item for item in items if item.section is section), key=item_order_key)
        if members:
            sections.append(PresentationSection(section=section, items=tuple(members)))
    presentation = NarrativePresentation(kind=trusted.kind, subject_root_ids=trusted.subject_root_ids,
                                         source_synthesis_id=trusted.synthesis_id, sections=tuple(sections))
    if sorted(presentation.claim_ids()) != sorted(claim.claim_id for claim in trusted.claims):
        _fail("PRESENTATION_CONFLICT", "every claim is presented exactly once")
    return presentation


# ---------------------------------------------------------------- A4b の選び方の検査（隠さない）

def validate_display_selection(presentation: NarrativePresentation, claim_ids: Iterable[str]) -> None:
    """見せる claim の選び方を検査する。見せる Theme に触れる REQUIRED の item を落とした選び方は拒否する。"""
    if type(presentation) is not NarrativePresentation:
        _fail("PRESENTATION_CONFLICT", "a NarrativePresentation is required")
    selected = set(claim_ids)
    items = {item.claim_id: item for item in presentation.items()}
    if not selected <= set(items):
        _fail("PRESENTATION_CONFLICT", "UNKNOWN_CLAIM")
    shown_roots = {root for claim_id in selected for root in items[claim_id].theme_root_ids}
    dropped: List[str] = [item.claim_id for item in presentation.items()
                          if item.visibility is Visibility.REQUIRED and item.claim_id not in selected
                          and set(item.theme_root_ids) & shown_roots]
    if dropped:
        _fail("PRESENTATION_CONFLICT", "REQUIRED_ITEM_DROPPED")


__all__ = ["SUPPORTED_CLAIM_SCHEMA_VERSION", "SUPPORTED_KINDS", "SUPPORTED_SYNTHESIS_RULESET_VERSIONS",
           "SUPPORTED_SYNTHESIS_SCHEMA_VERSION", "SYNTHESIS_RULESET_NAME", "item_for_claim", "plan_presentation",
           "revalidate_synthesis", "validate_display_selection"]
