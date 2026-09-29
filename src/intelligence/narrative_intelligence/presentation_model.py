"""P7-A4a — Narrative の提示 model と差分 model（構造だけ。派生・非 authority・非永続。自然文を持たない）。

- `NarrativePresentation`: A1 の `NarrativeSynthesis` 1 つの claim を、閉じた section の分類・決まった提示の順・見せ方の
  義務（REQUIRED ／ ELIGIBLE）に並べ直した構造。item は claim ちょうど 1 つに結び付き、claim の意味を足さない。
- `NarrativeDiff`: 明示的に与えた 2 つの synthesis の claim id の集合の差（ADDED ／ REMOVED ／ UNCHANGED だけ）。
  方向の評価（改善・強化・強気）・類似の照合・MODIFIED を持たない。
- 適格（ELIGIBLE）は「後で人に見せてよい」だけを意味する。重要・正しい・確信度が高い・推奨を意味しない。
  REQUIRED は「その Theme の item を 1 つでも見せるなら隠してはならない」（反証・無効化・不確実性・代替）。
- section の順は読みやすさのための提示の順で、重要度の順位ではない。section 内は canonical な identity の順
  （Theme の root id の組 → claim id）。score・順位・重み・確信度・勝者・主役・受益者・推奨・文章の field は無い。
- 並びは constructor が検査する（並べ替えて黙って直さない）。identity は内容から決まる（schema・元の synthesis id・
  規則表の version・構造）。時計・乱数・path・mtime は入らない。
- 保存しない（読み込みの API も持たない）。A4b は synthesis から作り直して id を照合する。

契約: `docs/databank/PHASE7_NARRATIVE_PRESENTATION_DIFF_CONTRACT.md`。
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, Optional, Tuple, Type

from ..core.ids import content_id
from .synthesis_model import (ASSERTION_CLASS_BY_PREDICATE, MAX_SUBJECTS, PREDICATE_SIGNATURES, PROHIBITED_FIELDS,
                              RELATION_PREDICATES, UNCERTAINTY_CLAIM_KIND, AssertionClass, ClaimKind, EpistemicClass,
                              EvidenceRole, NarrativeKind, Predicate, UncertaintyCode, canonical_json)

PRESENTATION_SCHEMA_VERSION = "narrative_presentation:0.1.0"
DIFF_SCHEMA_VERSION = "narrative_diff:0.1.0"
#: 規則表の version（identity に束ねる。A1 / A2 / A3 には保存しない）
PRESENTATION_RULESET_NAME = "narrative_presentation_rules"
PRESENTATION_RULESET_VERSION = "0.1.0"
DIFF_RULESET_NAME = "narrative_diff_rules"
DIFF_RULESET_VERSION = "0.1.0"
PRESENTATION_ID_PREFIX = "narprs"
DIFF_ID_PREFIX = "nardif"

#: 契約と test で固定する文言
AUTHORITY_CLASS = ("DERIVED", "NON_AUTHORITY", "NON_PERSISTENT")
PRESENTATION_IS_NOT_AUTHORITY = ("a narrative presentation or diff is a derived, non-authoritative, non-persistent "
                                 "arrangement of existing synthesis claims; never a new claim, a knowledge authority, "
                                 "a ranking, a recommendation or a trading signal")
PRESENTATION_ANSWERS = ("which structured claims of one synthesis may be displayed, in which closed section and "
                        "presentational order, and which must stay visible")
PRESENTATION_DOES_NOT_ANSWER = ("how to word it, which claim or theme matters most, how the evidence balances, "
                                "how confident to be, or which explanation wins")
SECTION_ORDER_MEANING = "presentational reading order only; not importance, priority or ranking"
DIFF_ANSWERS = "which structured claims were added, removed or unchanged between two explicitly supplied syntheses"
DIFF_DOES_NOT_ANSWER = ("why the market changed, whether a theme improved, whether confidence increased, or whether "
                        "an investment became more attractive")

FAILURE_CODES = ("INVALID_SYNTHESIS", "UNSUPPORTED_SYNTHESIS_VERSION", "SYNTHESIS_INTEGRITY_FAILURE",
                 "UNSUPPORTED_PRESENTATION_KIND", "PRESENTATION_CONFLICT", "INCOMPATIBLE_DIFF_INPUTS")

_ROOT_ID_RE = re.compile(r"^theme_[0-9A-HJKMNP-TV-Z]{26}$")
_CLAIM_ID_RE = re.compile(r"^narclm_[0-9a-f]{24}$")
_SYNTHESIS_ID_RE = re.compile(r"^narsyn_[0-9a-f]{24}$")


class NarrativePresentationError(ValueError):
    """提示・差分の失敗（fail closed）。code は `FAILURE_CODES`。detail は上流の code か field 名だけ（本文・path なし）。"""

    def __init__(self, code: str, detail: str = "") -> None:
        super().__init__(f"{code}: {detail}" if detail else code)
        self.code = code
        self.detail = detail


def _conflict(condition: bool, detail: str) -> None:
    if not condition:
        raise NarrativePresentationError("PRESENTATION_CONFLICT", detail)


def _enum(value: Any, enum_type: Type[Enum], name: str) -> Any:
    if isinstance(value, enum_type):
        return value
    _conflict(isinstance(value, str) and value in {m.value for m in enum_type}, name)
    return enum_type(value)


def _optional_enum(value: Any, enum_type: Type[Enum], name: str) -> Any:
    return None if value is None else _enum(value, enum_type, name)


def _roots(value: Any, name: str) -> Tuple[str, ...]:
    _conflict(isinstance(value, tuple), name)
    _conflict(all(isinstance(root, str) and bool(_ROOT_ID_RE.fullmatch(root)) for root in value), name)
    _conflict(list(value) == sorted(set(value)), name)                    # 非意味的な集合は canonical な順だけ
    return value


def _no_prohibited_keys(payload: Any) -> None:
    """直列化に順位・確信度・予測・推奨・文章・運用 metadata の field が現れないこと（A1 の禁止語彙）。"""
    if isinstance(payload, dict):
        for key, value in payload.items():
            _conflict(key not in PROHIBITED_FIELDS, "prohibited field")
            _no_prohibited_keys(value)
    elif isinstance(payload, list):
        for value in payload:
            _no_prohibited_keys(value)


# ---------------------------------------------------------------- 閉じた語彙

class SectionKind(str, Enum):
    """閉じた section の分類。A1 の claim kind 6 つ + 隠さないために分ける 3 つ（反証・不確実性・代替）。"""
    STATE = "STATE"
    MECHANISM = "MECHANISM"
    EVIDENCE = "EVIDENCE"
    CONTRADICTION = "CONTRADICTION"
    INVALIDATION = "INVALIDATION"
    UNCERTAINTY = "UNCERTAINTY"
    CHANGE = "CHANGE"
    RELATION = "RELATION"
    ALTERNATIVES = "ALTERNATIVES"


#: 提示の順（読みやすさのためだけ。重要度・優先度・順位ではない。`SECTION_ORDER_MEANING`）
SECTION_ORDER: Tuple[SectionKind, ...] = tuple(SectionKind)


class Visibility(str, Enum):
    """見せ方の義務。どちらも重要度・確信度ではない。"""
    REQUIRED = "REQUIRED"      # その Theme の item を 1 つでも見せるなら隠してはならない
    ELIGIBLE = "ELIGIBLE"      # 見せてよい（重要・正しい・推奨を意味しない）


class DiffCategory(str, Enum):
    """構造の差だけ。MODIFIED・改善・悪化・強化・弱化は存在しない。"""
    ADDED = "ADDED"            # current だけにある claim id
    REMOVED = "REMOVED"        # previous だけにある claim id
    UNCHANGED = "UNCHANGED"    # 両方にある claim id


#: 差分の item の提示の順（読みやすさのためだけ。重要度ではない）
DIFF_CATEGORY_ORDER: Tuple[DiffCategory, ...] = tuple(DiffCategory)


# ---------------------------------------------------------------- 提示の規則表（静的・version つき）

@dataclass(frozen=True)
class PresentationRule:
    """1 つの規則: claim の形（predicate と、EVIDENCE_ATTACHED だけは role）→ section と見せ方の義務。"""
    rule_id: str
    predicate: str
    evidence_role: Optional[str]
    section: str
    visibility: str
    reason: str


PRESENTATION_RULES: Tuple[PresentationRule, ...] = (
    PresentationRule("P01_STATE", "THEME_REVIEWED_STATE", None, "STATE", "ELIGIBLE",
                     "the reviewed state of a subject Theme"),
    PresentationRule("P02_MECHANISM_COMPONENT", "RECORDS_MECHANISM_COMPONENT", None, "MECHANISM", "ELIGIBLE",
                     "a recorded mechanism component (certainty caveat is a separate REQUIRED uncertainty)"),
    PresentationRule("P03_SUPPORTS", "EVIDENCE_ATTACHED", "SUPPORTS", "EVIDENCE", "ELIGIBLE",
                     "an attachment in role SUPPORTS"),
    PresentationRule("P04_CONTEXT", "EVIDENCE_ATTACHED", "CONTEXT", "EVIDENCE", "ELIGIBLE",
                     "an attachment in role CONTEXT (kept as CONTEXT; never support)"),
    PresentationRule("P05_CONTRADICTS", "EVIDENCE_ATTACHED", "CONTRADICTS", "CONTRADICTION", "REQUIRED",
                     "an attachment in role CONTRADICTS (separately visible; never netted)"),
    PresentationRule("P06_INVALIDATES", "EVIDENCE_ATTACHED", "INVALIDATES", "INVALIDATION", "REQUIRED",
                     "an attachment in role INVALIDATES"),
    PresentationRule("P07_OBSERVED_FACT", "EVIDENCE_ITEM_OBSERVED", None, "EVIDENCE", "ELIGIBLE",
                     "an observational record with an established time (no content)"),
    PresentationRule("P08_INVALIDATION_CONDITION", "RECORDS_INVALIDATION_CONDITION", None, "INVALIDATION",
                     "REQUIRED", "a recorded invalidation condition"),
    PresentationRule("P09_INVALIDATING_EVIDENCE", "INVALIDATING_EVIDENCE_ATTACHED", None, "INVALIDATION",
                     "REQUIRED", "invalidating evidence and the condition it names"),
    PresentationRule("P10_UNCERTAINTY", "IS_UNCERTAIN", None, "UNCERTAINTY", "REQUIRED",
                     "an explicit uncertainty code (never collapsed into a number)"),
    PresentationRule("P11_CHANGE", "CHANGED_BETWEEN_CUTOFFS", None, "CHANGE", "ELIGIBLE",
                     "an explicit change between cutoffs (no direction)"),
    PresentationRule("P12_HUMAN_ASSERTED_RELATION", "HUMAN_ASSERTED_RELATION", None, "RELATION", "ELIGIBLE",
                     "an explicit relation asserted by a human reviewer (assertion class carried)"),
    PresentationRule("P13_SOURCE_ASSERTED_RELATION", "SOURCE_ASSERTED_RELATION", None, "RELATION", "ELIGIBLE",
                     "an explicit relation a source asserted (assertion class SOURCE_ASSERTED carried)"),
    PresentationRule("P14_ALTERNATIVES", "ALTERNATIVE_EXPLANATIONS_OF_SHARED_EVIDENCE", None, "ALTERNATIVES",
                     "REQUIRED", "parallel, unranked explanations of shared evidence (no preferred one)"),
)
PRESENTATION_RULE_IDS: Tuple[str, ...] = tuple(rule.rule_id for rule in PRESENTATION_RULES)


def rule_for(predicate: Predicate, evidence_role: Optional[EvidenceRole]) -> PresentationRule:
    """claim の形に対応する規則（表に無い形は fail closed）。"""
    role = None if evidence_role is None else evidence_role.value
    matches = [rule for rule in PRESENTATION_RULES if (rule.predicate, rule.evidence_role) == (predicate.value, role)]
    _conflict(len(matches) == 1, "no presentation rule for the claim shape")
    return matches[0]


def item_order_key(item: "PresentationItem") -> Tuple[Tuple[str, ...], str]:
    """section 内の canonical な順（Theme の root id の組 → claim id）。score・重要度を使わない。"""
    return (item.theme_root_ids, item.claim_id)


def diff_item_order_key(entry: "NarrativeDiffItem") -> Tuple[int, int, Tuple[str, ...], str]:
    """差分の canonical な順（区分 → section → Theme の root id の組 → claim id）。提示の順で重要度ではない。"""
    return (DIFF_CATEGORY_ORDER.index(entry.category), SECTION_ORDER.index(entry.item.section),
            entry.item.theme_root_ids, entry.item.claim_id)


# ---------------------------------------------------------------- item ／ section ／ presentation

@dataclass(frozen=True, kw_only=True)
class PresentationItem:
    """claim ちょうど 1 つの提示。claim の構造上の属性だけを写し、section と見せ方の義務は規則表から決まる。"""
    claim_id: str
    theme_root_ids: Tuple[str, ...]
    epistemic_class: EpistemicClass
    claim_kind: ClaimKind
    predicate: Predicate
    uncertainty_code: Optional[UncertaintyCode] = None
    evidence_role: Optional[EvidenceRole] = None
    assertion_class: Optional[AssertionClass] = None
    rule_id: str = field(init=False)
    section: SectionKind = field(init=False)
    visibility: Visibility = field(init=False)

    def __post_init__(self) -> None:
        _conflict(isinstance(self.claim_id, str) and bool(_CLAIM_ID_RE.fullmatch(self.claim_id)), "claim_id")
        roots = _roots(self.theme_root_ids, "theme_root_ids")
        klass = _enum(self.epistemic_class, EpistemicClass, "epistemic_class")
        kind = _enum(self.claim_kind, ClaimKind, "claim_kind")
        predicate = _enum(self.predicate, Predicate, "predicate")
        code = _optional_enum(self.uncertainty_code, UncertaintyCode, "uncertainty_code")
        role = _optional_enum(self.evidence_role, EvidenceRole, "evidence_role")
        assertion = _optional_enum(self.assertion_class, AssertionClass, "assertion_class")
        expected_class, expected_kinds = PREDICATE_SIGNATURES[predicate]
        _conflict(klass is expected_class and kind in expected_kinds, "claim signature")
        _conflict((code is not None) == (predicate is Predicate.IS_UNCERTAIN), "uncertainty_code")
        _conflict(code is None or UNCERTAINTY_CLAIM_KIND[code] is kind, "uncertainty_code")
        _conflict((role is not None) == (predicate is Predicate.EVIDENCE_ATTACHED), "evidence_role")
        _conflict((assertion is not None) == (predicate in RELATION_PREDICATES), "assertion_class")
        _conflict(assertion is None or assertion is ASSERTION_CLASS_BY_PREDICATE[predicate], "assertion_class")
        expected_roots = (0 if predicate is Predicate.EVIDENCE_ITEM_OBSERVED else
                          2 if predicate in RELATION_PREDICATES else None)
        if expected_roots is not None:
            _conflict(len(roots) == expected_roots, "theme_root_ids")
        elif predicate is Predicate.ALTERNATIVE_EXPLANATIONS_OF_SHARED_EVIDENCE:
            _conflict(len(roots) >= 2, "theme_root_ids")
        else:
            _conflict(len(roots) == 1, "theme_root_ids")
        rule = rule_for(predicate, role)
        object.__setattr__(self, "epistemic_class", klass)
        object.__setattr__(self, "claim_kind", kind)
        object.__setattr__(self, "predicate", predicate)
        object.__setattr__(self, "uncertainty_code", code)
        object.__setattr__(self, "evidence_role", role)
        object.__setattr__(self, "assertion_class", assertion)
        object.__setattr__(self, "rule_id", rule.rule_id)
        object.__setattr__(self, "section", SectionKind(rule.section))
        object.__setattr__(self, "visibility", Visibility(rule.visibility))

    def to_dict(self) -> Dict[str, Any]:
        return {"claim_id": self.claim_id, "theme_root_ids": list(self.theme_root_ids),
                "epistemic_class": self.epistemic_class.value, "claim_kind": self.claim_kind.value,
                "predicate": self.predicate.value,
                "uncertainty_code": None if self.uncertainty_code is None else self.uncertainty_code.value,
                "evidence_role": None if self.evidence_role is None else self.evidence_role.value,
                "assertion_class": None if self.assertion_class is None else self.assertion_class.value,
                "rule_id": self.rule_id, "section": self.section.value, "visibility": self.visibility.value}


@dataclass(frozen=True, kw_only=True)
class PresentationSection:
    """1 つの section（空の section は作らない。無いことは「存在しない」という主張ではない）。"""
    section: SectionKind
    items: Tuple[PresentationItem, ...]

    def __post_init__(self) -> None:
        section = _enum(self.section, SectionKind, "section")
        _conflict(isinstance(self.items, tuple) and len(self.items) >= 1, "items")
        _conflict(all(type(item) is PresentationItem for item in self.items), "items")
        _conflict(all(item.section is section for item in self.items), "item outside its section")
        keys = [item_order_key(item) for item in self.items]
        _conflict(keys == sorted(set(keys)), "items are not in canonical order")           # 並べ替えて直さない
        object.__setattr__(self, "section", section)

    def to_dict(self) -> Dict[str, Any]:
        return {"section": self.section.value, "items": [item.to_dict() for item in self.items]}


def _subjects(kind: NarrativeKind, value: Any) -> Tuple[str, ...]:
    subjects = _roots(value, "subject_root_ids")
    if kind is NarrativeKind.THEME_STATE:
        _conflict(len(subjects) == 1, "subject_root_ids")
    else:
        _conflict(2 <= len(subjects) <= MAX_SUBJECTS, "subject_root_ids")
    return subjects


def _synthesis_id(value: Any, name: str) -> str:
    _conflict(isinstance(value, str) and bool(_SYNTHESIS_ID_RE.fullmatch(value)), name)
    return value


@dataclass(frozen=True, kw_only=True)
class NarrativePresentation:
    """1 つの synthesis の提示の構造（派生・非 authority・非永続）。文章を持たない。"""
    kind: NarrativeKind
    subject_root_ids: Tuple[str, ...]
    source_synthesis_id: str
    sections: Tuple[PresentationSection, ...]
    presentation_id: str = field(init=False)

    def __post_init__(self) -> None:
        kind = _enum(self.kind, NarrativeKind, "kind")
        subjects = _subjects(kind, self.subject_root_ids)
        _synthesis_id(self.source_synthesis_id, "source_synthesis_id")
        _conflict(isinstance(self.sections, tuple) and len(self.sections) >= 1, "sections")
        _conflict(all(type(section) is PresentationSection for section in self.sections), "sections")
        order = [SECTION_ORDER.index(section.section) for section in self.sections]
        _conflict(order == sorted(set(order)), "sections are not in the presentational order")
        claim_ids = [item.claim_id for section in self.sections for item in section.items]
        _conflict(len(set(claim_ids)) == len(claim_ids), "a claim is presented twice")
        _conflict(all(set(item.theme_root_ids) <= set(subjects) for section in self.sections
                      for item in section.items), "an item outside the subject Themes")
        object.__setattr__(self, "kind", kind)
        payload = self._identity_payload()
        _no_prohibited_keys(payload)
        object.__setattr__(self, "presentation_id", content_id(PRESENTATION_ID_PREFIX, canonical_json(payload)))

    def _identity_payload(self) -> Dict[str, Any]:
        return {"schema_version": PRESENTATION_SCHEMA_VERSION,
                "ruleset": {"name": PRESENTATION_RULESET_NAME, "version": PRESENTATION_RULESET_VERSION},
                "source_synthesis_id": self.source_synthesis_id, "kind": self.kind.value,
                "subject_root_ids": list(self.subject_root_ids),
                "sections": [section.to_dict() for section in self.sections]}

    def items(self) -> Tuple[PresentationItem, ...]:
        return tuple(item for section in self.sections for item in section.items)

    def claim_ids(self) -> Tuple[str, ...]:
        return tuple(item.claim_id for item in self.items())

    def to_dict(self) -> Dict[str, Any]:
        return dict(self._identity_payload(), presentation_id=self.presentation_id)

    def to_canonical_json(self) -> str:
        return canonical_json(self.to_dict())


# ---------------------------------------------------------------- 差分

@dataclass(frozen=True, kw_only=True)
class NarrativeDiffItem:
    """差分の 1 項目: 区分と、その claim の提示（claim id の完全一致だけで決まる）。"""
    category: DiffCategory
    item: PresentationItem

    def __post_init__(self) -> None:
        object.__setattr__(self, "category", _enum(self.category, DiffCategory, "category"))
        _conflict(type(self.item) is PresentationItem, "item")

    def to_dict(self) -> Dict[str, Any]:
        return {"category": self.category.value, "item": self.item.to_dict()}


@dataclass(frozen=True, kw_only=True)
class NarrativeDiff:
    """明示的に与えた 2 つの synthesis の構造の差（派生・非 authority・非永続）。方向の評価を持たない。"""
    kind: NarrativeKind
    subject_root_ids: Tuple[str, ...]
    previous_synthesis_id: str
    current_synthesis_id: str
    items: Tuple[NarrativeDiffItem, ...]
    diff_id: str = field(init=False)

    def __post_init__(self) -> None:
        kind = _enum(self.kind, NarrativeKind, "kind")
        subjects = _subjects(kind, self.subject_root_ids)
        previous = _synthesis_id(self.previous_synthesis_id, "previous_synthesis_id")
        current = _synthesis_id(self.current_synthesis_id, "current_synthesis_id")
        _conflict(previous != current, "a synthesis is not diffed with itself")
        _conflict(isinstance(self.items, tuple) and len(self.items) >= 1, "items")
        _conflict(all(type(entry) is NarrativeDiffItem for entry in self.items), "items")
        claim_ids = [entry.item.claim_id for entry in self.items]
        _conflict(len(set(claim_ids)) == len(claim_ids), "a claim is listed twice")
        keys = [diff_item_order_key(entry) for entry in self.items]
        _conflict(keys == sorted(keys), "items are not in canonical order")                # 並べ替えて直さない
        _conflict(all(set(entry.item.theme_root_ids) <= set(subjects) for entry in self.items),
                  "an item outside the subject Themes")
        object.__setattr__(self, "kind", kind)
        payload = self._identity_payload()
        _no_prohibited_keys(payload)
        object.__setattr__(self, "diff_id", content_id(DIFF_ID_PREFIX, canonical_json(payload)))

    def _identity_payload(self) -> Dict[str, Any]:
        return {"schema_version": DIFF_SCHEMA_VERSION,
                "ruleset": {"name": DIFF_RULESET_NAME, "version": DIFF_RULESET_VERSION},
                "presentation_ruleset": {"name": PRESENTATION_RULESET_NAME, "version": PRESENTATION_RULESET_VERSION},
                "kind": self.kind.value, "subject_root_ids": list(self.subject_root_ids),
                "previous_synthesis_id": self.previous_synthesis_id,
                "current_synthesis_id": self.current_synthesis_id,
                "items": [entry.to_dict() for entry in self.items]}

    def claim_ids(self, category: DiffCategory) -> Tuple[str, ...]:
        return tuple(entry.item.claim_id for entry in self.items if entry.category is category)

    def to_dict(self) -> Dict[str, Any]:
        return dict(self._identity_payload(), diff_id=self.diff_id)

    def to_canonical_json(self) -> str:
        return canonical_json(self.to_dict())


__all__ = [
    "AUTHORITY_CLASS", "DIFF_ANSWERS", "DIFF_CATEGORY_ORDER", "DIFF_DOES_NOT_ANSWER", "DIFF_ID_PREFIX",
    "DIFF_RULESET_NAME", "DIFF_RULESET_VERSION", "DIFF_SCHEMA_VERSION", "DiffCategory", "FAILURE_CODES",
    "NarrativeDiff", "NarrativeDiffItem", "NarrativePresentation", "NarrativePresentationError",
    "PRESENTATION_ANSWERS", "PRESENTATION_DOES_NOT_ANSWER", "PRESENTATION_ID_PREFIX", "PRESENTATION_IS_NOT_AUTHORITY",
    "PRESENTATION_RULES", "PRESENTATION_RULESET_NAME", "PRESENTATION_RULESET_VERSION", "PRESENTATION_RULE_IDS",
    "PRESENTATION_SCHEMA_VERSION", "PresentationItem", "PresentationRule", "PresentationSection", "SECTION_ORDER",
    "SECTION_ORDER_MEANING", "SectionKind", "Visibility", "diff_item_order_key", "item_order_key", "rule_for",
]
