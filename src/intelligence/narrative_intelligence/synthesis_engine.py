"""P7-A3 — 決定論の Narrative synthesis engine（構造化された claim だけ。文章・LLM・永続化なし）。

`synthesize(snapshot)`: A2 の `NarrativeInputSnapshot` → A1 の `NarrativeSynthesis`。純関数。

問い: 「この PIT snapshot だけから、どの構造化された説明の claim が正当化されるか」。答えないもの: 読み手への書き方・最も
重要な Theme・次に何が起きるか・何を買うか・どの説明が勝つか。

規則:
- 入力は A2 の snapshot だけ。store・Phase 6・filesystem・時計・乱数・network を使わない。`pit_assembler` を呼ばない。
- snapshot を盲信しない: 型・形・id を A1 / A2 の constructor で作り直して再検証し、改ざんは fail closed。
- claim は下の規則表（`RULES`、version つき）が定める材料からだけ作る。欠落から claim を作らない（規則が明示する flag を除く）。
  重み・score・順位・確率・勝者・主役・予測・文章は無い。
- 出力は A1 の constructor だけで作る（A1 の id・順序・不変条件をそのまま継ぐ）。snapshot の provenance は A1 の
  `input_digest`（＝ snapshot id）、規則表の version は A1 の `knowledge_pins` に束ねる（A1 を変えない）。
- 過去の出力・採用率・勝率・click など履歴の入力を持たない（規則表は静的な code）。

契約: `docs/databank/PHASE7_NARRATIVE_DETERMINISTIC_SYNTHESIS_CONTRACT.md`。
"""
from __future__ import annotations

from dataclasses import dataclass, fields
from typing import Dict, List, Mapping, Optional, Tuple

from .input_model import (EvidenceConditionFlag, EvidenceSource, NarrativeInputError, NarrativeInputSnapshot,
                          SourceCapability, ThemeInput)
from .synthesis_model import (OBSERVED_FACT_TIME_QUALITIES, AssertionClass, EvidenceAttachmentRef, EvidenceItemRef,
                              EvidenceRole, InvalidationConditionRef, MechanismCertainty, MechanismComponentRef,
                              NarrativeClaim, NarrativeKind, NarrativeModelError, NarrativeSynthesis,
                              RelationAssertionRef, ThemeChangeRef, ThemeObservationRef, ref_from_dict)

#: 規則表の version（A1 の knowledge_pins に束ねる。意味を変えたら上げる）
RULESET_NAME = "narrative_synthesis_rules"
RULESET_VERSION = "0.1.0"
#: この engine が意味を知っている入力（知らない version は fail closed）
SUPPORTED_INPUT_SCHEMA_VERSION = "narrative_input_snapshot:0.1.0"
SUPPORTED_READER_VERSIONS: Mapping[str, str] = {
    "theme_resolver": "0.1.0", "theme_lifecycle_model": "0.1.0", "theme_lifecycle_policy": "0.1.0",
    "theme_change_model": "0.1.0", "theme_relation_resolver": "0.1.0"}
SUPPORTED_KINDS = (NarrativeKind.THEME_STATE, NarrativeKind.THEME_SET)

#: 契約と test で固定する文言
SYNTHESIS_ENGINE_ANSWERS = "which structured explanatory claims this point-in-time snapshot justifies"
SYNTHESIS_ENGINE_DOES_NOT_ANSWER = ("how to write it for a reader, which theme matters most, what happens next, what to "
                                    "buy, or which explanation wins")

FAILURE_CODES = ("INVALID_SNAPSHOT", "UNSUPPORTED_SNAPSHOT_VERSION", "UNSUPPORTED_KIND", "SNAPSHOT_INTEGRITY_FAILURE",
                 "CLAIM_CONFLICT", "NO_JUSTIFIED_CLAIMS", "MODEL_CONTRACT_MISMATCH")
#: A1 が claim の間の食い違いとして拒否する code（それ以外の A1 の拒否は契約の不一致）
_CONFLICT_CODES = ("EVIDENCE_ROLE_RELABELLED", "REF_INCONSISTENT", "OBSERVATION_INCONSISTENT",
                   "UNCERTAINTY_CONTRADICTS_REFS", "DUPLICATE_CLAIM")


class NarrativeSynthesisError(ValueError):
    """synthesis の失敗（fail closed）。code は `FAILURE_CODES`。detail は上流の code か field 名だけ（本文・path なし）。"""

    def __init__(self, code: str, detail: str = "") -> None:
        super().__init__(f"{code}: {detail}" if detail else code)
        self.code = code
        self.detail = detail


def _fail(code: str, detail: str = "") -> None:
    raise NarrativeSynthesisError(code, detail)


def _code(exc: Exception) -> str:
    if isinstance(exc, (NarrativeModelError, NarrativeInputError, NarrativeSynthesisError)):
        return exc.code
    return type(exc).__name__


# ---------------------------------------------------------------- 規則表（静的・version つき）

@dataclass(frozen=True)
class SynthesisRule:
    """1 つの規則: 入力の形 → 出力の (認識 class, claim kind, predicate, 不確実性 code) と ref、抑止の条件。"""
    rule_id: str
    input_shape: str
    epistemic_class: str
    claim_kind: str
    predicate: str
    uncertainty_code: Optional[str]
    required_refs: str
    suppression: str


RULES: Tuple[SynthesisRule, ...] = (
    SynthesisRule("R01_REVIEWED_STATE", "each Theme input", "REVIEWED_INTERPRETATION", "STATE",
                  "THEME_REVIEWED_STATE", None, "the Theme's reviewed observation ref", "none"),
    SynthesisRule("R02_MECHANISM_COMPONENT", "each recorded mechanism component", "REVIEWED_INTERPRETATION",
                  "MECHANISM", "RECORDS_MECHANISM_COMPONENT", None, "the component ref", "none"),
    SynthesisRule("R03_MECHANISM_HYPOTHESIZED", "a Theme whose certainty is HYPOTHESIZED_MECHANISM and that has "
                  "components", "UNCERTAINTY", "MECHANISM", "IS_UNCERTAIN", "MECHANISM_HYPOTHESIZED",
                  "the observation ref", "no component"),
    SynthesisRule("R04_EVIDENCE_ATTACHED", "each attachment in any role (SUPPORTS / CONTRADICTS / CONTEXT / "
                  "INVALIDATES)", "REVIEWED_INTERPRETATION", "EVIDENCE", "EVIDENCE_ATTACHED", None,
                  "the attachment ref (role unchanged)", "none"),
    SynthesisRule("R05_CONTESTED_EVIDENCE", "a Theme with at least one SUPPORTS and one CONTRADICTS attachment",
                  "UNCERTAINTY", "EVIDENCE", "IS_UNCERTAIN", "CONTESTED_EVIDENCE",
                  "the observation ref and every SUPPORTS and CONTRADICTS attachment", "either side missing"),
    SynthesisRule("R06_NO_SUPPORTING_EVIDENCE", "flag NO_VISIBLE_EVIDENCE", "UNCERTAINTY", "EVIDENCE", "IS_UNCERTAIN",
                  "NO_SUPPORTING_EVIDENCE", "the observation ref",
                  "any SUPPORTS attachment is projected (A1 forbids the contradiction)"),
    SynthesisRule("R07_SINGLE_SOURCE_EVIDENCE", "flag SINGLE_SOURCE", "UNCERTAINTY", "EVIDENCE", "IS_UNCERTAIN",
                  "SINGLE_SOURCE_EVIDENCE", "the observation ref", "none"),
    SynthesisRule("R08_STALE_EVIDENCE", "flag STALE", "UNCERTAINTY", "EVIDENCE", "IS_UNCERTAIN", "STALE_EVIDENCE",
                  "the observation ref", "none"),
    SynthesisRule("R09_INVALIDATION_CONDITION", "each recorded invalidation condition", "REVIEWED_INTERPRETATION",
                  "INVALIDATION", "RECORDS_INVALIDATION_CONDITION", None, "the condition ref", "none"),
    SynthesisRule("R10_INVALIDATING_EVIDENCE", "each INVALIDATES attachment", "REVIEWED_INTERPRETATION",
                  "INVALIDATION", "INVALIDATING_EVIDENCE_ATTACHED", None,
                  "the attachment ref and the condition it names", "none"),
    SynthesisRule("R11_OBSERVED_EVIDENCE_ITEM", "each evidence source with capability OBSERVATIONAL_RECORD and an "
                  "established time", "OBSERVED_FACT", "EVIDENCE", "EVIDENCE_ITEM_OBSERVED", None,
                  "the evidence item ref (no content)", "SOURCE_CONTENT capability or unestablished time"),
    SynthesisRule("R12_CHANGE", "each projected B1 change (only with a comparison cutoff)", "DERIVED_SYNTHESIS",
                  "CHANGE", "CHANGED_BETWEEN_CUTOFFS", None, "the change ref", "changes absent (None)"),
    SynthesisRule("R13_RELATION", "each projected B5B relation (THEME_SET only); predicate by its assertion class",
                  "REVIEWED_INTERPRETATION", "RELATION", "HUMAN_ASSERTED_RELATION | SOURCE_ASSERTED_RELATION", None,
                  "the relation ref and both endpoint observation refs", "THEME_STATE (relations absent)"),
    SynthesisRule("R14_ALTERNATIVE_EXPLANATIONS", "one evidence ref_id attached as SUPPORTS to two or more subject "
                  "Themes (THEME_SET only; exact ref_id equality)", "ALTERNATIVE_HYPOTHESIS", "MECHANISM",
                  "ALTERNATIVE_EXPLANATIONS_OF_SHARED_EVIDENCE", None,
                  "per Theme: the observation ref and its SUPPORTS attachment (lowest attachment key)",
                  "fewer than two Themes"),
)
RULE_IDS: Tuple[str, ...] = tuple(rule.rule_id for rule in RULES)
_RULES_BY_ID: Mapping[str, SynthesisRule] = {rule.rule_id: rule for rule in RULES}


def _claim(rule_id: str, refs: Tuple, *, predicate: Optional[str] = None) -> Tuple[str, NarrativeClaim]:
    rule = _RULES_BY_ID[rule_id]
    claim = NarrativeClaim(epistemic_class=rule.epistemic_class, claim_kind=rule.claim_kind,
                           predicate=predicate or rule.predicate, refs=refs, uncertainty_code=rule.uncertainty_code)
    return rule_id, claim


# ---------------------------------------------------------------- 入力の再検証（盲信しない）

def _exact_fields(value: object, expected_type: type) -> None:
    if type(value) is not expected_type:
        _fail("SNAPSHOT_INTEGRITY_FAILURE", expected_type.__name__)
    names = {f.name for f in fields(expected_type)}
    if set(vars(value)) != names:                                      # 後から足された属性（score 等）を拒否
        _fail("SNAPSHOT_INTEGRITY_FAILURE", expected_type.__name__)


def _ref(value: object, expected_type: type):
    _exact_fields(value, expected_type)
    rebuilt = ref_from_dict(value.to_dict())                          # A1 の検査を最初から通し直す
    if type(rebuilt) is not expected_type or rebuilt != value:
        _fail("SNAPSHOT_INTEGRITY_FAILURE", expected_type.__name__)
    return rebuilt


def _theme(theme: object) -> ThemeInput:
    _exact_fields(theme, ThemeInput)
    return ThemeInput(
        observation=_ref(theme.observation, ThemeObservationRef),
        components=tuple(_ref(c, MechanismComponentRef) for c in theme.components),
        invalidation_conditions=tuple(_ref(c, InvalidationConditionRef) for c in theme.invalidation_conditions),
        attachments=tuple(_ref(a, EvidenceAttachmentRef) for a in theme.attachments),
        evidence_condition_flags=tuple(theme.evidence_condition_flags),
        changes=None if theme.changes is None else tuple(_ref(c, ThemeChangeRef) for c in theme.changes),
        provenance_digest=theme.provenance_digest)


def _source(source: object) -> EvidenceSource:
    _exact_fields(source, EvidenceSource)
    return EvidenceSource(item=_ref(source.item, EvidenceItemRef), capability=source.capability)


def _check_flags(theme: ThemeInput) -> None:
    """B2 の flag と投影した attachment の、Phase 6 で必ず成り立つ関係（食い違いは改ざん）。"""
    roles = {a.role for a in theme.attachments}
    flags = set(theme.evidence_condition_flags)
    F = EvidenceConditionFlag
    consistent = ((F.CONTESTED in flags) == (EvidenceRole.CONTRADICTS in roles)
                  and (F.INVALIDATION_EVIDENCE_PRESENT in flags) == (EvidenceRole.INVALIDATES in roles)
                  and (F.HAS_SUPPORT not in flags or EvidenceRole.SUPPORTS in roles)
                  and not {F.NO_VISIBLE_EVIDENCE, F.HAS_SUPPORT} <= flags
                  and (F.HAS_CONTEXT_ONLY not in flags or (F.NO_VISIBLE_EVIDENCE in flags and theme.attachments))
                  and not {F.SINGLE_SOURCE, F.MULTI_SOURCE} <= flags
                  and not {F.SINGLE_EVIDENCE_DATE, F.MULTI_DATE} <= flags)
    if not consistent:
        _fail("SNAPSHOT_INTEGRITY_FAILURE", "evidence condition flags")


def revalidate(snapshot: object) -> NarrativeInputSnapshot:
    """snapshot を A1 / A2 の constructor で作り直し、id と canonical bytes が一致することを確かめる。"""
    if not isinstance(snapshot, NarrativeInputSnapshot):
        _fail("INVALID_SNAPSHOT", "a NarrativeInputSnapshot is required")
    if snapshot.kind not in SUPPORTED_KINDS:
        _fail("UNSUPPORTED_KIND", "kind")
    try:
        schema = snapshot.to_dict()["schema_version"]
    except Exception as exc:
        raise NarrativeSynthesisError("SNAPSHOT_INTEGRITY_FAILURE", _code(exc)) from None
    if schema != SUPPORTED_INPUT_SCHEMA_VERSION:
        _fail("UNSUPPORTED_SNAPSHOT_VERSION", "input schema")
    try:
        _exact_fields(snapshot, NarrativeInputSnapshot)
        for name, version in snapshot.reader_versions:
            if SUPPORTED_READER_VERSIONS.get(name) != version:
                _fail("UNSUPPORTED_SNAPSHOT_VERSION", "reader version")
        rebuilt = NarrativeInputSnapshot(
            kind=snapshot.kind, root_ids=tuple(snapshot.root_ids), cutoff=snapshot.cutoff,
            comparison_cutoff=snapshot.comparison_cutoff, themes=tuple(_theme(t) for t in snapshot.themes),
            evidence_sources=tuple(_source(s) for s in snapshot.evidence_sources),
            relations=None if snapshot.relations is None else tuple(_ref(r, RelationAssertionRef)
                                                                    for r in snapshot.relations),
            relation_provenance_digest=snapshot.relation_provenance_digest,
            reader_versions=tuple(snapshot.reader_versions), stale_after_days=snapshot.stale_after_days)
        if rebuilt.snapshot_id != snapshot.snapshot_id or rebuilt.to_canonical_json() != snapshot.to_canonical_json():
            _fail("SNAPSHOT_INTEGRITY_FAILURE", "snapshot identity")
        for theme in rebuilt.themes:
            _check_flags(theme)
    except NarrativeSynthesisError:
        raise
    except Exception as exc:                                           # 改ざんされた値は理由の code だけを返す
        raise NarrativeSynthesisError("SNAPSHOT_INTEGRITY_FAILURE", _code(exc)) from None
    return rebuilt


# ---------------------------------------------------------------- 規則の適用

def _theme_claims(theme: ThemeInput) -> List[Tuple[str, NarrativeClaim]]:
    obs = theme.observation
    out = [_claim("R01_REVIEWED_STATE", (obs,))]
    out += [_claim("R02_MECHANISM_COMPONENT", (c,)) for c in theme.components]
    if theme.components and obs.mechanism_certainty is MechanismCertainty.HYPOTHESIZED_MECHANISM:
        out.append(_claim("R03_MECHANISM_HYPOTHESIZED", (obs,)))
    out += [_claim("R04_EVIDENCE_ATTACHED", (a,)) for a in theme.attachments]
    supports = [a for a in theme.attachments if a.role is EvidenceRole.SUPPORTS]
    contradicts = [a for a in theme.attachments if a.role is EvidenceRole.CONTRADICTS]
    if supports and contradicts:                                       # 両方を見せる。勝ち負け・差し引きをしない
        out.append(_claim("R05_CONTESTED_EVIDENCE", (obs, *supports, *contradicts)))
    flags = set(theme.evidence_condition_flags)
    if EvidenceConditionFlag.NO_VISIBLE_EVIDENCE in flags and not supports:
        out.append(_claim("R06_NO_SUPPORTING_EVIDENCE", (obs,)))
    if EvidenceConditionFlag.SINGLE_SOURCE in flags:
        out.append(_claim("R07_SINGLE_SOURCE_EVIDENCE", (obs,)))
    if EvidenceConditionFlag.STALE in flags:
        out.append(_claim("R08_STALE_EVIDENCE", (obs,)))
    conditions = {c.condition_key: c for c in theme.invalidation_conditions}
    out += [_claim("R09_INVALIDATION_CONDITION", (c,)) for c in theme.invalidation_conditions]
    out += [_claim("R10_INVALIDATING_EVIDENCE", (conditions[a.invalidation_condition_key], a))
            for a in theme.attachments if a.role is EvidenceRole.INVALIDATES]
    if theme.changes is not None:                                      # 比較 cutoff が無ければ変化の claim は無い
        out += [_claim("R12_CHANGE", (c,)) for c in theme.changes]
    return out


def _observed_items(sources: Tuple[EvidenceSource, ...]) -> List[Tuple[str, NarrativeClaim]]:
    return [_claim("R11_OBSERVED_EVIDENCE_ITEM", (s.item,)) for s in sources
            if s.capability is SourceCapability.OBSERVATIONAL_RECORD
            and s.item.time_quality in OBSERVED_FACT_TIME_QUALITIES]


def _relation_claims(snapshot: NarrativeInputSnapshot) -> List[Tuple[str, NarrativeClaim]]:
    if snapshot.kind is not NarrativeKind.THEME_SET or snapshot.relations is None:
        return []
    observations = {t.root_id: t.observation for t in snapshot.themes}
    out = []
    for relation in snapshot.relations:                                # 1 辺 → 1 claim。逆向き・推移の辺は作らない
        predicate = ("SOURCE_ASSERTED_RELATION" if relation.assertion_class is AssertionClass.SOURCE_ASSERTED
                     else "HUMAN_ASSERTED_RELATION")
        out.append(_claim("R13_RELATION", (relation, observations[relation.source_root_id],
                                           observations[relation.target_root_id]), predicate=predicate))
    return out


def _alternative_claims(snapshot: NarrativeInputSnapshot) -> List[Tuple[str, NarrativeClaim]]:
    if snapshot.kind is not NarrativeKind.THEME_SET:
        return []
    witnesses: Dict[str, Dict[str, Tuple[ThemeObservationRef, EvidenceAttachmentRef]]] = {}
    for theme in snapshot.themes:
        for attachment in theme.attachments:                           # attachment は key 順（最小の key を証拠にする）
            if attachment.role is EvidenceRole.SUPPORTS:
                witnesses.setdefault(attachment.ref_id, {}).setdefault(theme.root_id,
                                                                        (theme.observation, attachment))
    out = []
    for ref_id in sorted(witnesses):                                   # ref_id の完全一致だけ。類似・推測なし
        by_root = witnesses[ref_id]
        if len(by_root) >= 2:
            out.append(_claim("R14_ALTERNATIVE_EXPLANATIONS",
                              tuple(ref for root in sorted(by_root) for ref in by_root[root])))
    return out


def _derive_claims(snapshot: NarrativeInputSnapshot) -> List[Tuple[str, NarrativeClaim]]:
    out: List[Tuple[str, NarrativeClaim]] = []
    for theme in snapshot.themes:
        out += _theme_claims(theme)
    out += _observed_items(snapshot.evidence_sources)
    out += _relation_claims(snapshot)
    out += _alternative_claims(snapshot)
    return out


def _converge(generated: List[Tuple[str, NarrativeClaim]]) -> Tuple[NarrativeClaim, ...]:
    """同じ claim id は 1 つに収束させる。同じ id で中身が違えば fail closed（曖昧に合わせない）。"""
    claims: Dict[str, NarrativeClaim] = {}
    for rule_id, claim in generated:
        rule = _RULES_BY_ID.get(rule_id)
        if rule is None or (claim.epistemic_class.value, claim.claim_kind.value) != (rule.epistemic_class,
                                                                                      rule.claim_kind):
            _fail("MODEL_CONTRACT_MISMATCH", rule_id)
        existing = claims.setdefault(claim.claim_id, claim)
        if existing != claim or existing.to_dict() != claim.to_dict():
            _fail("CLAIM_CONFLICT", claim.claim_id)
    return tuple(claims.values())


def synthesis_from_claims(snapshot: NarrativeInputSnapshot, claims: Tuple[NarrativeClaim, ...]) -> NarrativeSynthesis:
    """再検証済みの snapshot と生成済みの claim から A1 の synthesis を作る（A1 の constructor だけ）。"""
    if not claims:
        _fail("NO_JUSTIFIED_CLAIMS", "no rule produced a claim")        # 埋め草を作らない
    try:
        return NarrativeSynthesis(kind=snapshot.kind, subject_root_ids=snapshot.root_ids, cutoff=snapshot.cutoff,
                                  knowledge_pins=tuple(snapshot.reader_versions) + ((RULESET_NAME, RULESET_VERSION),),
                                  input_digest=snapshot.snapshot_id, claims=claims)
    except NarrativeModelError as exc:
        raise NarrativeSynthesisError("CLAIM_CONFLICT" if exc.code in _CONFLICT_CODES else "MODEL_CONTRACT_MISMATCH",
                                      exc.code) from None


def synthesize(snapshot: NarrativeInputSnapshot) -> NarrativeSynthesis:
    """A2 の snapshot → A1 の synthesis（純関数。同じ snapshot → 同じ canonical bytes と id）。"""
    trusted = revalidate(snapshot)
    try:
        generated = _derive_claims(trusted)
    except NarrativeModelError as exc:
        raise NarrativeSynthesisError("MODEL_CONTRACT_MISMATCH", exc.code) from None
    return synthesis_from_claims(trusted, _converge(generated))


__all__ = ["FAILURE_CODES", "NarrativeSynthesisError", "RULES", "RULESET_NAME", "RULESET_VERSION", "RULE_IDS",
           "SUPPORTED_INPUT_SCHEMA_VERSION", "SUPPORTED_KINDS", "SUPPORTED_READER_VERSIONS",
           "SYNTHESIS_ENGINE_ANSWERS", "SYNTHESIS_ENGINE_DOES_NOT_ANSWER", "SynthesisRule", "revalidate",
           "synthesis_from_claims", "synthesize"]
