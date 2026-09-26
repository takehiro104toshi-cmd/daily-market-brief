"""P7-A4b — 描画済み Narrative の model（日本語の平文 field。派生・非 authority・非永続）。

- `RenderedNarrative` ／ `RenderedSection` ／ `RenderedItem`: A4a の提示を、固定の見出しと決定論の template で日本語の平文に
  した結果。`RenderedNarrativeDiff` ／ `RenderedDiffGroup`: A4a の差分を同じ template で平文にした結果。
- 意味を持つ item は A4a の `PresentationItem` ちょうど 1 つ（`presentation_item_id`）と、その claim id に結び付く。見出し・
  題名は構造の label で、claim を持たない。
- 文字列は plain text だけ（Markdown ／ HTML に依存しない）。許可した文字の集合の外（`<` `>` `&` `[` `(` `/` 制御文字等）・
  URL ／ path ／ journal 名 ／ 秘密の語を含む値は `UNSAFE_TEXT`。長さ・件数の上限を超えたら `RENDER_LIMIT_EXCEEDED`
  （黙って切り詰めない）。
- 言語は日本語だけ（`LANGUAGE = "ja"`。0.1.0 で凍結。多言語化は延期）。
- identity は内容から決まる（schema・描画の規則表の version・言語・元の提示 ／ 差分の id・描画した構造）。時計・乱数・
  path・mtime は入らない。保存しない（読み込みの API も持たない）。

契約: `docs/databank/PHASE7_NARRATIVE_DETERMINISTIC_RENDERER_CONTRACT.md`。
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Dict, Tuple

from ..core.ids import content_id
from .presentation_model import DIFF_CATEGORY_ORDER, PRESENTATION_RULE_IDS, SECTION_ORDER, DiffCategory, SectionKind
from .synthesis_model import PROHIBITED_FIELDS, NarrativeKind, canonical_json

RENDERED_SCHEMA_VERSION = "rendered_narrative:0.1.0"
RENDERED_DIFF_SCHEMA_VERSION = "rendered_narrative_diff:0.1.0"
#: 描画の規則表（template）の version。canonical な出力を変える文言の変更では必ず上げる
RENDERER_NAME = "narrative_renderer_ja"
RENDERER_VERSION = "0.1.0"
#: 0.1.0 は日本語だけ（凍結）
LANGUAGE = "ja"
RENDERED_ID_PREFIX = "narrnd"
RENDERED_DIFF_ID_PREFIX = "narrdf"
PRESENTATION_ITEM_ID_PREFIX = "narpit"

#: 上限（超えたら拒否する。切り詰めない）
MAX_ITEM_TEXT = 400
MAX_HEADING = 40
MAX_TITLE = 80
MAX_RENDERED_ITEMS = 256
MAX_RENDERED_DIFF_ITEMS = 512
MARKER_LENGTH = 8

#: 契約と test で固定する文言
AUTHORITY_CLASS = ("DERIVED", "NON_AUTHORITY", "NON_PERSISTENT")
RENDERING_RULE = "rendering may change wording; rendering may not change epistemic meaning"
HEADING_ORDER_MEANING = "見出しの順は読みやすさのための提示の順で、重要度の順位ではありません"

FAILURE_CODES = ("INVALID_PRESENTATION", "PRESENTATION_INTEGRITY_FAILURE", "UNSUPPORTED_PRESENTATION_VERSION",
                 "UNSUPPORTED_TEMPLATE", "UNSAFE_TEXT", "RENDER_LIMIT_EXCEEDED", "TRACEABILITY_FAILURE")

#: 平文に使ってよい文字（ひらがな・カタカナ・漢字・決まった全角の約物・ASCII の英数字と空白 _ . : -）
_SAFE_TEXT_RE = re.compile("^[぀-ゟ゠-ヿ一-鿿、。〈〉「」【】"
                           "（）［］a-zA-Z0-9 _.:\\-]+$")
#: 値に現れてはならない語（URL・journal の file 名・秘密。小文字で照合する。path と scheme 付きの URL は `/` が文字の
#: 集合の外なので現れ得ない）
UNSAFE_SUBSTRINGS = ("www.", "http", "mailto:", "javascript:", "data:", "file:", ".json", "journal", "api_key", "apikey",
                     "secret", "password", "bearer")
#: 描画の直列化に現れてはならない field（A1 の禁止語彙のうち、平文の field 名 `text` 以外）
RENDER_PROHIBITED_FIELDS = tuple(name for name in PROHIBITED_FIELDS if name != "text")

_CLAIM_ID_RE = re.compile(r"^narclm_[0-9a-f]{24}$")
_ROOT_ID_RE = re.compile(r"^theme_[0-9A-HJKMNP-TV-Z]{26}$")
_ITEM_ID_RE = re.compile(r"^narpit_[0-9a-f]{24}$")
_PRESENTATION_ID_RE = re.compile(r"^narprs_[0-9a-f]{24}$")
_DIFF_ID_RE = re.compile(r"^nardif_[0-9a-f]{24}$")
_SYNTHESIS_ID_RE = re.compile(r"^narsyn_[0-9a-f]{24}$")
_TEMPLATE_ID_RE = re.compile(r"^T[0-9]{2}_[A-Z_]+$")
_THEME_LABEL_RE = re.compile("^テーマ〈[0-9A-Z]{8}〉$")          # テーマ〈XXXXXXXX〉


class NarrativeRenderError(ValueError):
    """描画の失敗（fail closed）。code は `FAILURE_CODES`。detail は上流の code か field 名だけ（本文・path なし）。"""

    def __init__(self, code: str, detail: str = "") -> None:
        super().__init__(f"{code}: {detail}" if detail else code)
        self.code = code
        self.detail = detail


def _require(condition: bool, code: str, detail: str) -> None:
    if not condition:
        raise NarrativeRenderError(code, detail)


def check_text(value: Any, limit: int, name: str) -> str:
    """平文の値の検査（型 → 長さ → 文字の集合 → 危険な語）。直さずに拒否する。"""
    _require(isinstance(value, str) and value != "", "UNSAFE_TEXT", name)
    _require(len(value) <= limit, "RENDER_LIMIT_EXCEEDED", name)
    _require(bool(_SAFE_TEXT_RE.fullmatch(value)), "UNSAFE_TEXT", name)
    lowered = value.lower()
    _require(not any(word in lowered for word in UNSAFE_SUBSTRINGS), "UNSAFE_TEXT", name)
    return value


def _token(value: Any, pattern: "re.Pattern[str]", name: str) -> str:
    _require(isinstance(value, str) and bool(pattern.fullmatch(value)), "TRACEABILITY_FAILURE", name)
    return value


def _roots(value: Any, name: str) -> Tuple[str, ...]:
    _require(isinstance(value, tuple) and all(isinstance(root, str) and bool(_ROOT_ID_RE.fullmatch(root))
                                              for root in value), "TRACEABILITY_FAILURE", name)
    _require(list(value) == sorted(set(value)), "TRACEABILITY_FAILURE", name)
    return value


def _no_prohibited_keys(payload: Any) -> None:
    if isinstance(payload, dict):
        for key, value in payload.items():
            _require(key not in RENDER_PROHIBITED_FIELDS, "TRACEABILITY_FAILURE", "prohibited field")
            _no_prohibited_keys(value)
    elif isinstance(payload, list):
        for value in payload:
            _no_prohibited_keys(value)


def _theme_labels(value: Any, roots: Tuple[str, ...]) -> Tuple[Tuple[str, str], ...]:
    _require(isinstance(value, tuple) and all(isinstance(pair, tuple) and len(pair) == 2 for pair in value),
             "TRACEABILITY_FAILURE", "theme_labels")
    keys = tuple(root for root, _ in value)
    _roots(keys, "theme_labels")
    labels = [label for _, label in value]
    _require(all(isinstance(label, str) and bool(_THEME_LABEL_RE.fullmatch(label)) for label in labels),
             "TRACEABILITY_FAILURE", "theme_labels")
    _require(len(set(labels)) == len(labels), "TRACEABILITY_FAILURE", "theme label collision")
    _require(set(roots) <= set(keys), "TRACEABILITY_FAILURE", "a theme without a label")
    return value


# ---------------------------------------------------------------- item ／ section ／ narrative

@dataclass(frozen=True, kw_only=True)
class RenderedItem:
    """意味を持つ 1 文。A4a の提示 item 1 つ（`presentation_item_id`）と claim id に結び付く。"""
    presentation_item_id: str
    claim_ids: Tuple[str, ...]
    section: str
    rule_id: str
    template_id: str
    visibility: str
    theme_root_ids: Tuple[str, ...]
    reference_marker: str
    text: str

    def __post_init__(self) -> None:
        _token(self.presentation_item_id, _ITEM_ID_RE, "presentation_item_id")
        _require(isinstance(self.claim_ids, tuple) and len(self.claim_ids) == 1, "TRACEABILITY_FAILURE", "claim_ids")
        claim_id = _token(self.claim_ids[0], _CLAIM_ID_RE, "claim_ids")
        _require(self.section in {s.value for s in SectionKind}, "TRACEABILITY_FAILURE", "section")
        _require(self.rule_id in PRESENTATION_RULE_IDS, "TRACEABILITY_FAILURE", "rule_id")
        _token(self.template_id, _TEMPLATE_ID_RE, "template_id")
        _require(self.visibility in ("REQUIRED", "ELIGIBLE"), "TRACEABILITY_FAILURE", "visibility")
        _roots(self.theme_root_ids, "theme_root_ids")
        _require(self.reference_marker == claim_id[7:7 + MARKER_LENGTH], "TRACEABILITY_FAILURE", "reference_marker")
        check_text(self.text, MAX_ITEM_TEXT, "text")

    def to_dict(self) -> Dict[str, Any]:
        return {"presentation_item_id": self.presentation_item_id, "claim_ids": list(self.claim_ids),
                "section": self.section, "rule_id": self.rule_id, "template_id": self.template_id,
                "visibility": self.visibility, "theme_root_ids": list(self.theme_root_ids),
                "reference_marker": self.reference_marker, "text": self.text}

    def line(self) -> str:
        """平文の 1 行（`・` ＋ 文 ＋ 参照の印）。改行・制御文字を含まない。"""
        return check_text(f"・{self.text}［参照 {self.reference_marker}］",
                          MAX_ITEM_TEXT + MAX_HEADING + 16, "line")


def _items_in_order(items: Tuple[RenderedItem, ...]) -> None:
    keys = [(SECTION_ORDER.index(SectionKind(item.section)), item.theme_root_ids, item.claim_ids[0]) for item in items]
    _require(keys == sorted(set(keys)), "TRACEABILITY_FAILURE", "items are not in the presentation order")


@dataclass(frozen=True, kw_only=True)
class RenderedSection:
    """固定の日本語の見出しと、その section の文（空の section は作らない）。"""
    section: str
    heading: str
    items: Tuple[RenderedItem, ...]

    def __post_init__(self) -> None:
        _require(self.section in {s.value for s in SectionKind}, "TRACEABILITY_FAILURE", "section")
        check_text(self.heading, MAX_HEADING, "heading")
        _require(isinstance(self.items, tuple) and len(self.items) >= 1, "TRACEABILITY_FAILURE", "items")
        _require(all(type(item) is RenderedItem and item.section == self.section for item in self.items),
                 "TRACEABILITY_FAILURE", "items")
        _items_in_order(self.items)

    def to_dict(self) -> Dict[str, Any]:
        return {"section": self.section, "heading": self.heading, "items": [item.to_dict() for item in self.items]}


def _kind(value: Any) -> NarrativeKind:
    _require(isinstance(value, NarrativeKind), "TRACEABILITY_FAILURE", "kind")
    return value


def _subjects(kind: NarrativeKind, value: Any) -> Tuple[str, ...]:
    subjects = _roots(value, "subject_root_ids")
    _require(len(subjects) == 1 if kind is NarrativeKind.THEME_STATE else len(subjects) >= 2, "TRACEABILITY_FAILURE",
             "subject_root_ids")
    return subjects


@dataclass(frozen=True, kw_only=True)
class RenderedNarrative:
    """1 つの提示を日本語の平文にした結果（派生・非 authority・非永続）。"""
    kind: NarrativeKind
    presentation_id: str
    source_synthesis_id: str
    subject_root_ids: Tuple[str, ...]
    theme_labels: Tuple[Tuple[str, str], ...]
    title: str
    sections: Tuple[RenderedSection, ...]
    rendered_id: str = field(init=False)

    def __post_init__(self) -> None:
        kind = _kind(self.kind)
        subjects = _subjects(kind, self.subject_root_ids)
        _token(self.presentation_id, _PRESENTATION_ID_RE, "presentation_id")
        _token(self.source_synthesis_id, _SYNTHESIS_ID_RE, "source_synthesis_id")
        check_text(self.title, MAX_TITLE, "title")
        _require(isinstance(self.sections, tuple) and len(self.sections) >= 1, "TRACEABILITY_FAILURE", "sections")
        _require(all(type(section) is RenderedSection for section in self.sections), "TRACEABILITY_FAILURE", "sections")
        order = [SECTION_ORDER.index(SectionKind(section.section)) for section in self.sections]
        _require(order == sorted(set(order)), "TRACEABILITY_FAILURE", "sections are not in the presentational order")
        items = [item for section in self.sections for item in section.items]
        _require(len(items) <= MAX_RENDERED_ITEMS, "RENDER_LIMIT_EXCEEDED", "items")
        _require(len({item.claim_ids[0] for item in items}) == len(items), "TRACEABILITY_FAILURE", "duplicate claim")
        _require(len({item.reference_marker for item in items}) == len(items), "TRACEABILITY_FAILURE",
                 "reference marker collision")
        roots = tuple(sorted(set(subjects) | {root for item in items for root in item.theme_root_ids}))
        _require(set(roots) <= set(subjects), "TRACEABILITY_FAILURE", "an item outside the subject Themes")
        _theme_labels(self.theme_labels, roots)
        payload = self._identity_payload()
        _no_prohibited_keys(payload)
        object.__setattr__(self, "rendered_id", content_id(RENDERED_ID_PREFIX, canonical_json(payload)))

    def _identity_payload(self) -> Dict[str, Any]:
        return {"schema_version": RENDERED_SCHEMA_VERSION,
                "renderer": {"name": RENDERER_NAME, "version": RENDERER_VERSION}, "language": LANGUAGE,
                "kind": self.kind.value, "presentation_id": self.presentation_id,
                "source_synthesis_id": self.source_synthesis_id, "subject_root_ids": list(self.subject_root_ids),
                "theme_labels": [{"root_id": root, "label": label} for root, label in self.theme_labels],
                "title": self.title, "sections": [section.to_dict() for section in self.sections]}

    def items(self) -> Tuple[RenderedItem, ...]:
        return tuple(item for section in self.sections for item in section.items)

    def lines(self) -> Tuple[str, ...]:
        """平文の行の並び（題名 → 【見出し】 → ・文［参照］）。改行文字は含まない。"""
        out = [self.title]
        for section in self.sections:
            out.append(check_text(f"【{section.heading}】", MAX_HEADING + 2, "line"))
            out.extend(item.line() for item in section.items)
        return tuple(out)

    def to_dict(self) -> Dict[str, Any]:
        return dict(self._identity_payload(), rendered_id=self.rendered_id)

    def to_canonical_json(self) -> str:
        return canonical_json(self.to_dict())


# ---------------------------------------------------------------- 差分

@dataclass(frozen=True, kw_only=True)
class RenderedDiffGroup:
    """差分の 1 区分（追加 ／ なくなった ／ 変わらず存在する）の文。評価の語を持たない。"""
    category: str
    heading: str
    items: Tuple[RenderedItem, ...]

    def __post_init__(self) -> None:
        _require(self.category in {c.value for c in DiffCategory}, "TRACEABILITY_FAILURE", "category")
        check_text(self.heading, MAX_HEADING, "heading")
        _require(isinstance(self.items, tuple) and len(self.items) >= 1, "TRACEABILITY_FAILURE", "items")
        _require(all(type(item) is RenderedItem for item in self.items), "TRACEABILITY_FAILURE", "items")
        _items_in_order(self.items)

    def to_dict(self) -> Dict[str, Any]:
        return {"category": self.category, "heading": self.heading, "items": [item.to_dict() for item in self.items]}


@dataclass(frozen=True, kw_only=True)
class RenderedNarrativeDiff:
    """明示的な 2 つの synthesis の構造の差分を日本語の平文にした結果（派生・非 authority・非永続）。"""
    kind: NarrativeKind
    diff_id: str
    previous_synthesis_id: str
    current_synthesis_id: str
    previous_presentation_id: str
    current_presentation_id: str
    subject_root_ids: Tuple[str, ...]
    theme_labels: Tuple[Tuple[str, str], ...]
    title: str
    groups: Tuple[RenderedDiffGroup, ...]
    rendered_diff_id: str = field(init=False)

    def __post_init__(self) -> None:
        kind = _kind(self.kind)
        subjects = _subjects(kind, self.subject_root_ids)
        _token(self.diff_id, _DIFF_ID_RE, "diff_id")
        for name in ("previous_synthesis_id", "current_synthesis_id"):
            _token(self.__dict__[name], _SYNTHESIS_ID_RE, name)
        for name in ("previous_presentation_id", "current_presentation_id"):
            _token(self.__dict__[name], _PRESENTATION_ID_RE, name)
        check_text(self.title, MAX_TITLE, "title")
        _require(isinstance(self.groups, tuple) and len(self.groups) >= 1, "TRACEABILITY_FAILURE", "groups")
        _require(all(type(group) is RenderedDiffGroup for group in self.groups), "TRACEABILITY_FAILURE", "groups")
        order = [DIFF_CATEGORY_ORDER.index(DiffCategory(group.category)) for group in self.groups]
        _require(order == sorted(set(order)), "TRACEABILITY_FAILURE", "groups are not in the presentational order")
        items = [item for group in self.groups for item in group.items]
        _require(len(items) <= MAX_RENDERED_DIFF_ITEMS, "RENDER_LIMIT_EXCEEDED", "items")
        _require(len({item.claim_ids[0] for item in items}) == len(items), "TRACEABILITY_FAILURE", "duplicate claim")
        _require(len({item.reference_marker for item in items}) == len(items), "TRACEABILITY_FAILURE",
                 "reference marker collision")
        roots = tuple(sorted(set(subjects) | {root for item in items for root in item.theme_root_ids}))
        _require(set(roots) <= set(subjects), "TRACEABILITY_FAILURE", "an item outside the subject Themes")
        _theme_labels(self.theme_labels, roots)
        payload = self._identity_payload()
        _no_prohibited_keys(payload)
        object.__setattr__(self, "rendered_diff_id", content_id(RENDERED_DIFF_ID_PREFIX, canonical_json(payload)))

    def _identity_payload(self) -> Dict[str, Any]:
        return {"schema_version": RENDERED_DIFF_SCHEMA_VERSION,
                "renderer": {"name": RENDERER_NAME, "version": RENDERER_VERSION}, "language": LANGUAGE,
                "kind": self.kind.value, "diff_id": self.diff_id, "previous_synthesis_id": self.previous_synthesis_id,
                "current_synthesis_id": self.current_synthesis_id,
                "previous_presentation_id": self.previous_presentation_id,
                "current_presentation_id": self.current_presentation_id,
                "subject_root_ids": list(self.subject_root_ids),
                "theme_labels": [{"root_id": root, "label": label} for root, label in self.theme_labels],
                "title": self.title, "groups": [group.to_dict() for group in self.groups]}

    def items(self) -> Tuple[RenderedItem, ...]:
        return tuple(item for group in self.groups for item in group.items)

    def lines(self) -> Tuple[str, ...]:
        """平文の行の並び（題名 → 【区分】 → ・文［参照］）。改行文字は含まない。"""
        out = [self.title]
        for group in self.groups:
            out.append(check_text(f"【{group.heading}】", MAX_HEADING + 2, "line"))
            out.extend(item.line() for item in group.items)
        return tuple(out)

    def to_dict(self) -> Dict[str, Any]:
        return dict(self._identity_payload(), rendered_diff_id=self.rendered_diff_id)

    def to_canonical_json(self) -> str:
        return canonical_json(self.to_dict())


__all__ = [
    "AUTHORITY_CLASS", "FAILURE_CODES", "HEADING_ORDER_MEANING", "LANGUAGE", "MARKER_LENGTH", "MAX_HEADING",
    "MAX_ITEM_TEXT", "MAX_RENDERED_DIFF_ITEMS", "MAX_RENDERED_ITEMS", "MAX_TITLE", "NarrativeRenderError",
    "PRESENTATION_ITEM_ID_PREFIX", "RENDERED_DIFF_ID_PREFIX", "RENDERED_DIFF_SCHEMA_VERSION", "RENDERED_ID_PREFIX",
    "RENDERED_SCHEMA_VERSION", "RENDERER_NAME", "RENDERER_VERSION", "RENDERING_RULE", "RENDER_PROHIBITED_FIELDS",
    "RenderedDiffGroup", "RenderedItem", "RenderedNarrative", "RenderedNarrativeDiff", "RenderedSection",
    "UNSAFE_SUBSTRINGS", "check_text",
]
