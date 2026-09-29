"""P7-A4b — 日本語の決定論の template の registry（`narrative_renderer_ja` 0.1.0。静的で監査できる表）。

- A4a の規則（`rule_id`）と、その claim の閉じた属性（不確実性 code）ごとに template がちょうど 1 つある。
  推測で文言を選ぶ汎用の fallback は無い。表に無い組み合わせ・label の無い enum 値は `UNSUPPORTED_TEMPLATE`。
- 各 template は、どの認識 class のために書いたかを宣言する（別の class の claim には使えない）。
  REVIEWED_INTERPRETATION は「整理されています」／ SOURCE_ASSERTED は「出典は…主張しています」で解釈 ／ 出典の主張と
  分かる形にする。OBSERVED_FACT は「存在します」だけで、因果・評価の語を持たない。
- 差し込む値は、固定の label（enum → 日本語）・テーマの中立な label（root id の末尾）・A1 の key の token・UTC の時刻だけ。
  外の知識・記事の本文・欠けた事実の補完・推論が要る言い換えは無い。
- 重要度・確率・予測・推奨・確信度・順位・強弱・改善 ／ 悪化の語は無い（test で固定）。
- 見出しの順は読みやすさのための提示の順で、重要度の順位ではない。
- canonical な出力を変える文言の変更は、`RENDERER_VERSION` を上げる（test が registry の digest を version ごとに固定する）。

契約: `docs/databank/PHASE7_NARRATIVE_DETERMINISTIC_RENDERER_CONTRACT.md`。
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Mapping, Tuple

from .rendered_model import RENDERER_NAME, RENDERER_VERSION, NarrativeRenderError


@dataclass(frozen=True)
class Template:
    """1 つの template: A4a の規則 ＋ 変種 → 宣言した認識 class の文型（差し込む field は固定）。"""
    template_id: str
    rule_id: str
    variant: str
    epistemic_class: str
    fields: Tuple[str, ...]
    pattern: str


RI, UN, OF, DS, AH = ("REVIEWED_INTERPRETATION", "UNCERTAINTY", "OBSERVED_FACT", "DERIVED_SYNTHESIS",
                      "ALTERNATIVE_HYPOTHESIS")

TEMPLATES: Tuple[Template, ...] = (
    Template("T01_STATE", "P01_STATE", "", RI, ("theme",),
             "{theme}は、レビュー済みのテーマとして整理されています。"),
    Template("T02_MECHANISM_COMPONENT", "P02_MECHANISM_COMPONENT", "", RI, ("theme", "component", "key"),
             "{theme}では、機構の{component}として「{key}」が整理されています。"),
    Template("T03_SUPPORTS", "P03_SUPPORTS", "", RI, ("theme", "evidence"),
             "{theme}の見方を支持する材料として、{evidence}が整理されています。"),
    Template("T04_CONTEXT", "P04_CONTEXT", "", RI, ("theme", "evidence"),
             "{theme}に関する文脈の材料として、{evidence}が整理されています。"),
    Template("T05_CONTRADICTS", "P05_CONTRADICTS", "", RI, ("theme", "evidence"),
             "一方、{theme}の見方と矛盾する材料として、{evidence}が整理されています。"),
    Template("T06_INVALIDATES", "P06_INVALIDATES", "", RI, ("theme", "condition", "evidence"),
             "{theme}の無効化条件「{condition}」に関係する材料として、{evidence}が整理されています。"),
    Template("T07_OBSERVED_FACT", "P07_OBSERVED_FACT", "", OF, ("time", "evidence", "quality"),
             "{time}時点の{evidence}が存在します（時刻の扱い: {quality}）。"),
    Template("T08_INVALIDATION_CONDITION", "P08_INVALIDATION_CONDITION", "", RI, ("theme", "condition"),
             "{theme}の解釈が成り立たなくなる条件として、「{condition}」が整理されています。"),
    Template("T09_INVALIDATING_EVIDENCE", "P09_INVALIDATING_EVIDENCE", "", RI, ("theme", "condition", "evidence"),
             "{theme}の無効化条件「{condition}」には、関係する材料（{evidence}）が結び付けられていると整理されています。"
             "これはテーマの状態を変えるものではありません。"),
    Template("T10_NO_SUPPORTING_EVIDENCE", "P10_UNCERTAINTY", "NO_SUPPORTING_EVIDENCE", UN, ("theme",),
             "{theme}については、見方を支持する材料が確認されていません。"),
    Template("T11_SINGLE_SOURCE_EVIDENCE", "P10_UNCERTAINTY", "SINGLE_SOURCE_EVIDENCE", UN, ("theme",),
             "{theme}の材料は、単一の出所によるものです。"),
    Template("T12_STALE_EVIDENCE", "P10_UNCERTAINTY", "STALE_EVIDENCE", UN, ("theme",),
             "{theme}の材料は、定められた鮮度の期間より古いものです。"),
    Template("T13_CONTESTED_EVIDENCE", "P10_UNCERTAINTY", "CONTESTED_EVIDENCE", UN, ("theme",),
             "{theme}には、支持する材料と矛盾する材料が併存しています。"),
    Template("T14_MECHANISM_HYPOTHESIZED", "P10_UNCERTAINTY", "MECHANISM_HYPOTHESIZED", UN, ("theme",),
             "{theme}の機構は、仮説の段階として整理されています。"),
    Template("T15_CHANGE", "P11_CHANGE", "", DS, ("theme", "start", "end", "change"),
             "{theme}について、{start}と{end}の比較から「{change}」という構造上の変化が導かれています。"),
    Template("T16_HUMAN_ASSERTED_RELATION", "P12_HUMAN_ASSERTED_RELATION", "", RI, ("source", "target", "relation"),
             "{source}が{target}{relation}という関係が、レビュー済みの解釈として整理されています。"),
    Template("T17_SOURCE_ASSERTED_RELATION", "P13_SOURCE_ASSERTED_RELATION", "", RI, ("source", "target", "relation"),
             "出典は、{source}が{target}{relation}という関係を主張しています。"
             "これは出典による主張であり、この説明が主張する関係ではありません。"),
    Template("T18_ALTERNATIVES", "P14_ALTERNATIVES", "", AH, ("evidence", "themes"),
             "同じ材料（{evidence}）について、{themes}のレビュー済みの説明が並列に記録されています（順不同）。"),
)
TEMPLATE_IDS: Tuple[str, ...] = tuple(template.template_id for template in TEMPLATES)

#: 固定の日本語の見出し（構造の label。claim を持たない。順は A4a の提示の順で、重要度ではない）
SECTION_HEADINGS: Tuple[Tuple[str, str], ...] = (
    ("STATE", "テーマの状態"), ("MECHANISM", "機構"), ("EVIDENCE", "材料"), ("CONTRADICTION", "矛盾する材料"),
    ("INVALIDATION", "無効化の条件と材料"), ("UNCERTAINTY", "不確実性"), ("CHANGE", "比較時点との構造上の変化"),
    ("RELATION", "テーマ間の関係"), ("ALTERNATIVES", "並列する別の説明"))
DIFF_HEADINGS: Tuple[Tuple[str, str], ...] = (
    ("ADDED", "追加された説明要素"), ("REMOVED", "なくなった説明要素"), ("UNCHANGED", "変わらず存在する説明要素"))
TITLE_THEME_STATE = "{theme}についての整理"
TITLE_THEME_SET = "複数のテーマについての整理（順不同）"
DIFF_TITLE = "{start}時点から{end}時点までの説明要素の差分"
#: テーマの中立な label（root id の末尾 8 文字。順位を示さない）
THEME_LABEL = "テーマ〈{suffix}〉"

#: 閉じた enum → 日本語の label（表に無い値は UNSUPPORTED_TEMPLATE）
COMPONENT_LABELS: Tuple[Tuple[str, str], ...] = (
    ("DRIVER", "駆動要因"), ("TRANSMISSION_CHANNEL", "波及経路"), ("AFFECTED_DOMAIN", "影響を受ける領域"),
    ("EXPECTED_OBSERVABLE_CONSEQUENCE", "観測が見込まれる帰結"))
EVIDENCE_KIND_LABELS: Tuple[Tuple[str, str], ...] = (
    ("FACT", "事実の記録"), ("OBSERVATION", "観測の記録"), ("SOURCE_DOCUMENT", "文書"), ("NEWS_ITEM", "報道"),
    ("STATEMENT", "発言"))
TIME_QUALITY_LABELS: Tuple[Tuple[str, str], ...] = (("RELIABLE", "信頼できる時刻"), ("DECLARED", "申告された時刻"))
RELATION_LABELS: Tuple[Tuple[str, str], ...] = (
    ("CAUSES", "を引き起こす"), ("AMPLIFIES", "を増幅する"), ("MITIGATES", "を緩和する"), ("DEPENDS_ON", "に依存する"))
CHANGE_KIND_LABELS: Tuple[Tuple[str, str], ...] = (
    ("ROOT_APPEARED", "テーマの出現"), ("ROOT_BECAME_OBSERVED", "テーマの観測記録の出現"),
    ("OBSERVATION_REVISED", "観測記録の改訂"), ("SEMANTIC_FIELD_CHANGED", "意味の項目の変更"),
    ("EVIDENCE_ADDED", "材料の追加"), ("EVIDENCE_CARRIED", "材料の引き継ぎ"), ("EVIDENCE_DROPPED", "材料の除外"),
    ("EVIDENCE_ROLE_CHANGED", "材料の役割の変更"), ("EVIDENCE_REF_REVISED", "材料の参照の改訂"),
    ("EVIDENCE_ATTRIBUTE_CHANGED", "材料の属性の変更"), ("NEW_SOURCE_ORIGIN", "新しい出所の出現"),
    ("NEW_EVIDENCE_DATE", "新しい材料の日付の出現"), ("SOURCE_ORIGIN_LOST", "出所の消失"),
    ("EVIDENCE_DATE_LOST", "材料の日付の消失"), ("QUALIFICATION_CHANGED", "限定条件の変更"),
    ("CONTRADICTION_APPEARED", "矛盾する材料の出現"), ("CONTRADICTION_CLEARED", "矛盾する材料の消失"),
    ("INVALIDATION_APPEARED", "無効化に関係する材料の出現"), ("INVALIDATION_CLEARED", "無効化に関係する材料の消失"),
    ("GOVERNANCE_CHANGED", "レビューの状態の変更"), ("METADATA_CHANGED", "付帯情報の変更"),
    ("MAPPING_CHANGED", "対応付けの変更"), ("LINEAGE_CHANGED", "系譜の変更"),
    ("PENDING_APPEARED", "保留中の項目の出現"), ("PENDING_CLEARED", "保留中の項目の消失"),
    ("SEMANTIC_BECAME_UNRESOLVED", "意味の項目の未確定化"), ("SEMANTIC_BECAME_RESOLVED", "意味の項目の確定"),
    ("FACET_BECAME_UNRESOLVED", "側面の未確定化"), ("FACET_BECAME_RESOLVED", "側面の確定"),
    ("DEREFERENCE_CHANGED", "参照先の解決の変更"))


def _unsupported(detail: str) -> None:
    raise NarrativeRenderError("UNSUPPORTED_TEMPLATE", detail)


def template_for(rule_id: str, variant: str) -> Template:
    """A4a の規則と変種に対応する template（ちょうど 1 つ。無ければ fail closed）。"""
    matches = [template for template in TEMPLATES if (template.rule_id, template.variant) == (rule_id, variant)]
    if len(matches) != 1:
        _unsupported(rule_id)
    return matches[0]


def label_for(table: Tuple[Tuple[str, str], ...], value: str, name: str) -> str:
    matches = [label for key, label in table if key == value]
    if len(matches) != 1:
        _unsupported(name)
    return matches[0]


def fill(template: Template, values: Mapping[str, str]) -> str:
    """template に値を差し込む（field の集合が宣言と完全一致しなければ fail closed）。"""
    if set(values) != set(template.fields):
        _unsupported(template.template_id)
    return template.pattern.format(**values)


def registry_payload() -> Dict[str, Any]:
    """監査用の registry の全体（test が version ごとに digest を固定する）。"""
    return {"renderer": {"name": RENDERER_NAME, "version": RENDERER_VERSION},
            "templates": [{"template_id": t.template_id, "rule_id": t.rule_id, "variant": t.variant,
                           "epistemic_class": t.epistemic_class, "fields": list(t.fields), "pattern": t.pattern}
                          for t in TEMPLATES],
            "section_headings": [list(pair) for pair in SECTION_HEADINGS],
            "diff_headings": [list(pair) for pair in DIFF_HEADINGS],
            "titles": [TITLE_THEME_STATE, TITLE_THEME_SET, DIFF_TITLE, THEME_LABEL],
            "labels": {"component": [list(p) for p in COMPONENT_LABELS],
                       "evidence_kind": [list(p) for p in EVIDENCE_KIND_LABELS],
                       "time_quality": [list(p) for p in TIME_QUALITY_LABELS],
                       "relation": [list(p) for p in RELATION_LABELS],
                       "change_kind": [list(p) for p in CHANGE_KIND_LABELS]}}


__all__ = ["CHANGE_KIND_LABELS", "COMPONENT_LABELS", "DIFF_HEADINGS", "DIFF_TITLE", "EVIDENCE_KIND_LABELS",
           "RELATION_LABELS", "SECTION_HEADINGS", "TEMPLATES", "TEMPLATE_IDS", "THEME_LABEL", "TIME_QUALITY_LABELS",
           "TITLE_THEME_SET", "TITLE_THEME_STATE", "Template", "fill", "label_for", "registry_payload",
           "template_for"]
