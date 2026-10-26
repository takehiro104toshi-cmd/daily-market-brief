"""P7-A4b — 決定論の日本語の描画（A4a の提示 ／ 差分 → 描画済み Narrative。LLM・provider・永続化・公開出力なし）。

規則: 描画は文言を変えてよいが、認識上の意味を変えてはならない（`RENDERING_RULE`）。

- `render_presentation(presentation=..., synthesis=...)`: 何を・どの順で・どの義務で見せるかは A4a の提示だけが決める。
  synthesis は、提示が A4a の `plan_presentation` でその synthesis から**そのまま**作り直せる（canonical bytes と id が一致
  する）ことを確かめる検証と、A4a が許した item の claim の ref（relation の向き・component の型と key・変化の種類・
  evidence の種類・無効化条件の key）を読むためだけに使う。提示に無い claim は読まない（A4a を迂回しない）。
- `render_diff(diff=..., previous=..., current=...)`: 差分が A4a の `diff_syntheses` で作り直せることを確かめ、区分
  （追加 ／ なくなった ／ 変わらず存在する）ごとに同じ template で平文にする。方向の評価の語を足さない。
- 描画は全体（FULL）だけ。一部だけを見せる選択の mode は持たない（REQUIRED の item を落とす経路が無い）。
- 純関数: store・A2・A3 の engine・adapter・Phase 6・filesystem・環境変数・時計・乱数・network・locale を使わない。
  時刻は UTC の数字だけで書く（`strftime` の locale に依存しない）。
- 表に無い組み合わせは `UNSUPPORTED_TEMPLATE`。危険な文字・語は `UNSAFE_TEXT`、上限超過は `RENDER_LIMIT_EXCEEDED`。
  切り詰め・文言の推測・AI の文言への fallback は無い。

契約: `docs/databank/PHASE7_NARRATIVE_DETERMINISTIC_RENDERER_CONTRACT.md`。
"""
from __future__ import annotations

import re
from dataclasses import fields
from datetime import datetime, timezone
from typing import Dict, List, Mapping, Tuple

from ..core.ids import content_id
from .narrative_diff import diff_syntheses
from .presentation_model import (DIFF_CATEGORY_ORDER, NarrativeDiff, NarrativeDiffItem, NarrativePresentation,
                                 NarrativePresentationError, PresentationItem, PresentationSection)
from .presentation_planner import plan_presentation, revalidate_synthesis
from .render_templates_ja import (CHANGE_KIND_LABELS, COMPONENT_LABELS, DIFF_HEADINGS, DIFF_TITLE, EVIDENCE_KIND_LABELS,
                                  RELATION_LABELS, SECTION_HEADINGS, THEME_LABEL, TIME_QUALITY_LABELS,
                                  TITLE_THEME_SET, TITLE_THEME_STATE, fill, label_for, template_for)
from .rendered_model import (MARKER_LENGTH, PRESENTATION_ITEM_ID_PREFIX, NarrativeRenderError, RenderedDiffGroup,
                             RenderedItem, RenderedNarrative, RenderedNarrativeDiff, RenderedSection, check_text)
from .synthesis_model import (EvidenceAttachmentRef, EvidenceItemRef, InvalidationConditionRef, MechanismComponentRef,
                              NarrativeClaim, NarrativeKind, NarrativeSynthesis, RelationAssertionRef, ThemeChangeRef,
                              canonical_json)

#: この renderer が意味を知っている入力（知らない version は fail closed。A4a の値の複製で、一致は test で固定）
SUPPORTED_PRESENTATION_SCHEMA_VERSION = "narrative_presentation:0.1.0"
SUPPORTED_PRESENTATION_RULESET = ("narrative_presentation_rules", "0.1.0")
SUPPORTED_DIFF_SCHEMA_VERSION = "narrative_diff:0.1.0"
SUPPORTED_DIFF_RULESET = ("narrative_diff_rules", "0.1.0")
#: A1 の key の形（template に入る前に作り直して確かめる）
_KEY_RE = re.compile(r"^[a-z0-9][a-z0-9_.:-]{0,63}$")


def _fail(code: str, detail: str = "") -> None:
    raise NarrativeRenderError(code, detail)


def _code(exc: Exception) -> str:
    if isinstance(exc, (NarrativeRenderError, NarrativePresentationError)):
        return exc.code
    return type(exc).__name__


def _exact_fields(value: object, expected_type: type) -> None:
    if type(value) is not expected_type or set(vars(value)) != {f.name for f in fields(expected_type)}:
        _fail("PRESENTATION_INTEGRITY_FAILURE", expected_type.__name__)


# ---------------------------------------------------------------- 入力の再検証（盲信しない）

def _rebuilt_item(item: object) -> PresentationItem:
    _exact_fields(item, PresentationItem)
    rebuilt = PresentationItem(claim_id=item.claim_id, theme_root_ids=item.theme_root_ids,
                               epistemic_class=item.epistemic_class, claim_kind=item.claim_kind,
                               predicate=item.predicate, uncertainty_code=item.uncertainty_code,
                               evidence_role=item.evidence_role, assertion_class=item.assertion_class)
    if rebuilt != item or rebuilt.to_dict() != item.to_dict():                  # section・義務・規則の改ざん
        _fail("PRESENTATION_INTEGRITY_FAILURE", "item")
    return rebuilt


def _trusted_synthesis(synthesis: object) -> NarrativeSynthesis:
    try:
        return revalidate_synthesis(synthesis)                                    # A4a の検証 API（A1 の厳格な復元）
    except NarrativePresentationError as exc:
        code = {"INVALID_SYNTHESIS": "INVALID_PRESENTATION",
                "UNSUPPORTED_SYNTHESIS_VERSION": "UNSUPPORTED_PRESENTATION_VERSION"}.get(exc.code,
                                                                                   "PRESENTATION_INTEGRITY_FAILURE")
        raise NarrativeRenderError(code, exc.code) from None


def _checked_presentation(presentation: object, synthesis: object) -> Tuple[NarrativePresentation, NarrativeSynthesis]:
    """提示を作り直して id と bytes を確かめ、さらに synthesis から A4a で作り直した提示と完全一致することを確かめる。"""
    if type(presentation) is not NarrativePresentation:
        _fail("INVALID_PRESENTATION", "a NarrativePresentation is required")
    try:
        payload = presentation.to_dict()
        version = (payload["schema_version"], (payload["ruleset"]["name"], payload["ruleset"]["version"]))
    except Exception as exc:
        raise NarrativeRenderError("PRESENTATION_INTEGRITY_FAILURE", _code(exc)) from None
    if version != (SUPPORTED_PRESENTATION_SCHEMA_VERSION, SUPPORTED_PRESENTATION_RULESET):
        _fail("UNSUPPORTED_PRESENTATION_VERSION", "presentation schema or ruleset")
    try:
        _exact_fields(presentation, NarrativePresentation)
        sections = []
        for section in presentation.sections:
            _exact_fields(section, PresentationSection)
            sections.append(PresentationSection(section=section.section,
                                                items=tuple(_rebuilt_item(item) for item in section.items)))
        rebuilt = NarrativePresentation(kind=presentation.kind, subject_root_ids=presentation.subject_root_ids,
                                        source_synthesis_id=presentation.source_synthesis_id,
                                        sections=tuple(sections))
        if (rebuilt.presentation_id != presentation.presentation_id
                or rebuilt.to_canonical_json() != presentation.to_canonical_json()):
            _fail("PRESENTATION_INTEGRITY_FAILURE", "presentation identity")
    except NarrativeRenderError:
        raise
    except Exception as exc:                                                     # 改ざんされた値は理由の code だけ
        raise NarrativeRenderError("PRESENTATION_INTEGRITY_FAILURE", _code(exc)) from None
    trusted = _trusted_synthesis(synthesis)
    planned = plan_presentation(trusted)
    if planned.to_canonical_json() != rebuilt.to_canonical_json():               # 欠けた REQUIRED・足された item・別の元
        _fail("PRESENTATION_INTEGRITY_FAILURE", "the presentation is not the A4a plan of this synthesis")
    return rebuilt, trusted


# ---------------------------------------------------------------- 値（label・token・時刻）

def _theme_labels(roots: Tuple[str, ...]) -> Tuple[Tuple[str, str], ...]:
    labels = tuple((root, THEME_LABEL.format(suffix=root[-8:])) for root in sorted(set(roots)))
    if len({label for _, label in labels}) != len(labels):
        _fail("TRACEABILITY_FAILURE", "theme label collision")
    return labels


def _key(value: str) -> str:
    if not _KEY_RE.fullmatch(value):                                              # A1 の制約を作り直して確かめる
        _fail("UNSAFE_TEXT", "key")
    return check_text(value, 64, "key")


def _moment(value: datetime) -> str:
    moment = value.astimezone(timezone.utc)
    return f"{moment.year:04d}-{moment.month:02d}-{moment.day:02d} {moment.hour:02d}:{moment.minute:02d} UTC"


def _only(claim: NarrativeClaim, ref_type: type) -> list:
    refs = [ref for ref in claim.refs if isinstance(ref, ref_type)]
    if not refs:
        _fail("TRACEABILITY_FAILURE", ref_type.__name__)
    return refs


def _material(item: PresentationItem, claim: NarrativeClaim, labels: Mapping[str, str]) -> Tuple[str, Dict[str, str]]:
    """template の変種と差し込む値（A4a が許した claim の ref の、閉じた属性と key だけ）。"""
    rule = item.rule_id
    theme = labels[item.theme_root_ids[0]] if len(item.theme_root_ids) == 1 else ""
    if rule == "P01_STATE":
        return "", {"theme": theme}
    if rule == "P02_MECHANISM_COMPONENT":
        component = _only(claim, MechanismComponentRef)[0]
        return "", {"theme": theme, "component": label_for(COMPONENT_LABELS, component.component_type.value,
                                                           "component"),
                    "key": _key(component.component_key)}
    if rule in ("P03_SUPPORTS", "P04_CONTEXT", "P05_CONTRADICTS", "P06_INVALIDATES"):
        attachment = _only(claim, EvidenceAttachmentRef)[0]
        if attachment.role is not item.evidence_role:
            _fail("TRACEABILITY_FAILURE", "evidence role")
        values = {"theme": theme, "evidence": label_for(EVIDENCE_KIND_LABELS, attachment.evidence_kind.value,
                                                        "evidence")}
        if rule == "P06_INVALIDATES":
            values["condition"] = _key(attachment.invalidation_condition_key)
        return "", values
    if rule == "P07_OBSERVED_FACT":
        record = _only(claim, EvidenceItemRef)[0]
        return "", {"time": _moment(record.evidence_time),
                    "evidence": label_for(EVIDENCE_KIND_LABELS, record.evidence_kind.value, "evidence"),
                    "quality": label_for(TIME_QUALITY_LABELS, record.time_quality.value, "quality")}
    if rule == "P08_INVALIDATION_CONDITION":
        return "", {"theme": theme, "condition": _key(_only(claim, InvalidationConditionRef)[0].condition_key)}
    if rule == "P09_INVALIDATING_EVIDENCE":
        attachment = _only(claim, EvidenceAttachmentRef)[0]
        return "", {"theme": theme, "condition": _key(_only(claim, InvalidationConditionRef)[0].condition_key),
                    "evidence": label_for(EVIDENCE_KIND_LABELS, attachment.evidence_kind.value, "evidence")}
    if rule == "P10_UNCERTAINTY":
        return item.uncertainty_code.value, {"theme": theme}
    if rule == "P11_CHANGE":
        change = _only(claim, ThemeChangeRef)[0]
        return "", {"theme": theme, "start": _moment(change.from_cutoff), "end": _moment(change.to_cutoff),
                    "change": label_for(CHANGE_KIND_LABELS, change.change_kind.value, "change")}
    if rule in ("P12_HUMAN_ASSERTED_RELATION", "P13_SOURCE_ASSERTED_RELATION"):
        relation = _only(claim, RelationAssertionRef)[0]
        if relation.assertion_class is not item.assertion_class:                   # SOURCE_ASSERTED の限定を保つ
            _fail("TRACEABILITY_FAILURE", "assertion class")
        return "", {"source": labels[relation.source_root_id], "target": labels[relation.target_root_id],
                    "relation": label_for(RELATION_LABELS, relation.relation_type.value, "relation")}
    if rule == "P14_ALTERNATIVES":
        kinds = {attachment.evidence_kind.value for attachment in _only(claim, EvidenceAttachmentRef)}
        if len(kinds) != 1:
            _fail("TRACEABILITY_FAILURE", "shared evidence")
        return "", {"evidence": label_for(EVIDENCE_KIND_LABELS, kinds.pop(), "evidence"),
                    "themes": "、".join(labels[root] for root in item.theme_root_ids)}      # 順は root id（順位ではない）
    _fail("UNSUPPORTED_TEMPLATE", rule)
    return "", {}


def _item_id(presentation_id: str, item: PresentationItem) -> str:
    return content_id(PRESENTATION_ITEM_ID_PREFIX, canonical_json({"presentation_id": presentation_id,
                                                                   "item": item.to_dict()}))


def _rendered_item(presentation_id: str, item: PresentationItem, claims: Mapping[str, NarrativeClaim],
                   labels: Mapping[str, str]) -> RenderedItem:
    claim = claims.get(item.claim_id)
    if claim is None or claim.roots() != item.theme_root_ids or claim.predicate is not item.predicate:
        _fail("TRACEABILITY_FAILURE", "claim linkage")
    variant, values = _material(item, claim, labels)
    template = template_for(item.rule_id, variant)
    if template.epistemic_class != item.epistemic_class.value:                    # 解釈の文型を事実に使わない
        _fail("UNSUPPORTED_TEMPLATE", template.template_id)
    return RenderedItem(presentation_item_id=_item_id(presentation_id, item), claim_ids=(item.claim_id,),
                        section=item.section.value, rule_id=item.rule_id, template_id=template.template_id,
                        visibility=item.visibility.value, theme_root_ids=item.theme_root_ids,
                        reference_marker=item.claim_id[7:7 + MARKER_LENGTH], text=fill(template, values))


def _render(build):
    """構築中の A1 ／ A4a 以外の想定外の失敗は、値を含めずに code だけで返す。"""
    try:
        return build()
    except (NarrativeRenderError, NarrativePresentationError) as exc:
        if isinstance(exc, NarrativePresentationError):
            raise NarrativeRenderError("PRESENTATION_INTEGRITY_FAILURE", exc.code) from None
        raise
    except (KeyError, ValueError, IndexError) as exc:
        raise NarrativeRenderError("TRACEABILITY_FAILURE", _code(exc)) from None


# ---------------------------------------------------------------- 提示の描画（FULL だけ）

def render_presentation(*, presentation: NarrativePresentation, synthesis: NarrativeSynthesis) -> RenderedNarrative:
    """A4a の提示 → 日本語の描画済み Narrative（純関数。同じ入力と同じ version → 同じ canonical bytes と id）。"""
    checked, trusted = _checked_presentation(presentation, synthesis)

    def build() -> RenderedNarrative:
        claims = {claim.claim_id: claim for claim in trusted.claims}
        roots = checked.subject_root_ids + tuple(root for item in checked.items() for root in item.theme_root_ids)
        labels = _theme_labels(roots)
        by_root = dict(labels)
        sections = tuple(RenderedSection(section=section.section.value,
                                         heading=label_for(SECTION_HEADINGS, section.section.value, "heading"),
                                         items=tuple(_rendered_item(checked.presentation_id, item, claims, by_root)
                                                     for item in section.items))
                         for section in checked.sections)
        title = (TITLE_THEME_STATE.format(theme=by_root[checked.subject_root_ids[0]])
                 if checked.kind is NarrativeKind.THEME_STATE else TITLE_THEME_SET)
        rendered = RenderedNarrative(kind=checked.kind, presentation_id=checked.presentation_id,
                                     source_synthesis_id=checked.source_synthesis_id,
                                     subject_root_ids=checked.subject_root_ids, theme_labels=labels, title=title,
                                     sections=sections)
        if [item.claim_ids[0] for item in rendered.items()] != list(checked.claim_ids()):
            _fail("TRACEABILITY_FAILURE", "every presentation item is rendered once, in order")   # 何も落とさない
        return rendered
    return _render(build)


# ---------------------------------------------------------------- 差分の描画

def _checked_diff(diff: object, previous: object, current: object):
    if type(diff) is not NarrativeDiff:
        _fail("INVALID_PRESENTATION", "a NarrativeDiff is required")
    try:
        payload = diff.to_dict()
        version = (payload["schema_version"], (payload["ruleset"]["name"], payload["ruleset"]["version"]),
                   (payload["presentation_ruleset"]["name"], payload["presentation_ruleset"]["version"]))
    except Exception as exc:
        raise NarrativeRenderError("PRESENTATION_INTEGRITY_FAILURE", _code(exc)) from None
    if version != (SUPPORTED_DIFF_SCHEMA_VERSION, SUPPORTED_DIFF_RULESET, SUPPORTED_PRESENTATION_RULESET):
        _fail("UNSUPPORTED_PRESENTATION_VERSION", "diff schema or ruleset")
    try:
        _exact_fields(diff, NarrativeDiff)
        entries = []
        for entry in diff.items:
            _exact_fields(entry, NarrativeDiffItem)
            entries.append(NarrativeDiffItem(category=entry.category, item=_rebuilt_item(entry.item)))
        rebuilt = NarrativeDiff(kind=diff.kind, subject_root_ids=diff.subject_root_ids,
                                previous_synthesis_id=diff.previous_synthesis_id,
                                current_synthesis_id=diff.current_synthesis_id, items=tuple(entries))
        if rebuilt.diff_id != diff.diff_id or rebuilt.to_canonical_json() != diff.to_canonical_json():
            _fail("PRESENTATION_INTEGRITY_FAILURE", "diff identity")
    except NarrativeRenderError:
        raise
    except Exception as exc:
        raise NarrativeRenderError("PRESENTATION_INTEGRITY_FAILURE", _code(exc)) from None
    before, after = _trusted_synthesis(previous), _trusted_synthesis(current)
    try:
        expected = diff_syntheses(previous=before, current=after)
    except NarrativePresentationError as exc:
        raise NarrativeRenderError("PRESENTATION_INTEGRITY_FAILURE", exc.code) from None
    if expected.to_canonical_json() != rebuilt.to_canonical_json():
        _fail("PRESENTATION_INTEGRITY_FAILURE", "the diff is not the A4a diff of these syntheses")
    return rebuilt, before, after


def render_diff(*, diff: NarrativeDiff, previous: NarrativeSynthesis,
                current: NarrativeSynthesis) -> RenderedNarrativeDiff:
    """A4a の差分 → 日本語の描画済み差分（区分は構造の差だけ。評価の語を足さない）。"""
    checked, before, after = _checked_diff(diff, previous, current)

    def build() -> RenderedNarrativeDiff:
        presentations = {"previous": plan_presentation(before), "current": plan_presentation(after)}
        claims = {"previous": {c.claim_id: c for c in before.claims}, "current": {c.claim_id: c for c in after.claims}}
        roots = checked.subject_root_ids + tuple(root for entry in checked.items for root in entry.item.theme_root_ids)
        labels = _theme_labels(roots)
        by_root = dict(labels)
        groups: List[RenderedDiffGroup] = []
        for category in DIFF_CATEGORY_ORDER:
            side = "previous" if category.value == "REMOVED" else "current"     # なくなった要素は previous の文言
            items = tuple(_rendered_item(presentations[side].presentation_id, entry.item, claims[side], by_root)
                          for entry in checked.items if entry.category is category)
            if items:
                groups.append(RenderedDiffGroup(category=category.value,
                                                heading=label_for(DIFF_HEADINGS, category.value, "heading"),
                                                items=items))
        rendered = RenderedNarrativeDiff(
            kind=checked.kind, diff_id=checked.diff_id, previous_synthesis_id=checked.previous_synthesis_id,
            current_synthesis_id=checked.current_synthesis_id,
            previous_presentation_id=presentations["previous"].presentation_id,
            current_presentation_id=presentations["current"].presentation_id,
            subject_root_ids=checked.subject_root_ids, theme_labels=labels,
            title=DIFF_TITLE.format(start=_moment(before.cutoff), end=_moment(after.cutoff)), groups=tuple(groups))
        if [item.claim_ids[0] for item in rendered.items()] != [entry.item.claim_id for entry in checked.items]:
            _fail("TRACEABILITY_FAILURE", "every diff item is rendered once, in order")
        return rendered
    return _render(build)


__all__ = ["SUPPORTED_DIFF_RULESET", "SUPPORTED_DIFF_SCHEMA_VERSION", "SUPPORTED_PRESENTATION_RULESET",
           "SUPPORTED_PRESENTATION_SCHEMA_VERSION", "render_diff", "render_presentation"]
