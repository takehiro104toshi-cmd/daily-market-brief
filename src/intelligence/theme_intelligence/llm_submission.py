"""P6-B7F — 検証済み plan → 既存 proposal authority（B3 / B5C）の check-then-reuse 提出 bridge。

`submit_proposals(*, generations, submitted_at, data_root) -> SubmissionResult`

```
B7D 検証結果（validated plan）→ 提出境界での再検証（plan・入れ子・検証結果を凍結 constructor で組み直す）
→ 凍結済みの B3 / B5C constructor で上流 proposal を組む（id が plan の upstream_proposal_id と一致すること）
→ 既存 authority を読み込み検証（破損は fail closed）→ 同じ id を引く
→ 在れば再利用（EXISTING_PROPOSAL_REUSED）／無ければ新規 ／ 同じ id で意味が違えば PROPOSAL_CONFLICT
→ すべての pre-flight が通ったときだけ、新規を決定論的な順序（family → 上流 id）で 1 行ずつ追記
```

- 書いてよいのは B3 の提案 journal と B5C の関係提案 journal だけ（既存の `append_proposal` API）。decision・
  SourceClaimVerification・ThemeRoot・ThemeObservation・EvidenceAttachment・GovernanceEvent・RelationAssertion・
  relation governance・B6 review・生成監査 journal・公開出力には書かない。新しい提出 journal も作らない。
- 提案は decision でも受理でも付与でも主張でもない（`PROPOSAL_IS_NOT_DECISION`）。
- B3 と B5C は別 file なので ACID ではない。pre-flight で部分書き込みを最小化し、追記の途中で失敗したら
  PARTIAL_SUBMISSION を明示する（authority の履歴を削除して巻き戻さない）。
- 時刻は caller の `submitted_at` だけ（現在時刻を読まない）。現在の authority に対してだけ動く（過去時点の replay・
  backtest には使わない。`SUBMISSION_IS_NOT_A_BACKTEST`）。
- 生成監査 journal は読まない（成否・受理率・model の比較を使わない）。provenance は caller が渡す生成の参照だけ。
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, fields
from datetime import datetime
from typing import Dict, List, Optional, Sequence, Tuple, Union

from ..core.time import ensure_aware
from .llm_plan_model import (LLM_PROPOSER_CLASS, LLM_RELATION_PROPOSER_CLASS, PLAN_TYPES, LlmValidationError,
                             LlmValidationResult, PlannedEvidenceRef, ValidatedEvidenceProposalPlan,
                             ValidatedRelationProposalPlan, ValidatedThemeProposalPlan, ValidationOutcome)
from .llm_submission_model import (FAMILY_ORDER, AuthorityFamily, PlanSubmission, ReuseKind, SubmissionAction,
                                   SubmissionResult, SubmissionStatus)
from .proposal_model import (EvidenceCandidateProposal, ProposalModelError, ProposalProvenance, ThemeCandidateProposal,
                             canonical_proposal_line, parse_proposal)
from .proposal_store import ProposalStore, ProposalStoreError
from .relation_proposal_model import (RelationProposal, RelationProposalError, RelationProposalProvenance,
                                      canonical_proposal_record_line, parse_proposal_record)
from .relation_proposal_store import RelationProposalStore, RelationProposalStoreError

GENERATION_REF_RE = re.compile(r"^thllmatt_[0-9a-f]{24}$")         # B7E の試行 id（journal の key）
_TOKEN_RE = re.compile(r"^[a-z0-9][a-z0-9_.:-]{0,63}$")
_CODE_RE = re.compile(r"^[A-Z][A-Z0-9_]{0,63}$")
UPSTREAM_ERRORS = (ProposalModelError, RelationProposalError, ValueError, TypeError, AttributeError, KeyError)
STORE_ERRORS = (ProposalStoreError, RelationProposalStoreError)


@dataclass(frozen=True, kw_only=True)
class ValidatedGeneration:
    """1 生成ぶんの提出単位。`validation` は B7D の検証結果、`generation_ref` は B7E の試行 id（caller が渡す参照）。"""

    validation: LlmValidationResult
    generation_ref: str
    prompt_contract_version: str


class _Refused(Exception):
    def __init__(self, code: str, detail: str = "", plan_id: str = "") -> None:
        super().__init__(code)
        self.code, self.detail, self.plan_id = code, detail, plan_id


def _refuse(condition: bool, code: str, detail: str = "", plan_id: str = "") -> None:
    if not condition:
        raise _Refused(code, detail, plan_id)


def _code_of(exc: Exception, fallback: str) -> str:
    code = str(getattr(exc, "code", "") or "")
    return code if _CODE_RE.match(code) else fallback


@dataclass(frozen=True)
class _Planned:
    family: AuthorityFamily
    plan: object
    proposal: object
    generation_ref: str

    @property
    def upstream_id(self) -> str:
        return self.proposal.proposal_id  # type: ignore[attr-defined]

    def order(self) -> Tuple[int, str, str, str]:
        return (FAMILY_ORDER.index(self.family), self.upstream_id, self.generation_ref, self.plan.plan_id)  # type: ignore[attr-defined]


# ---------------------------------------------------------------- 提出境界での再検証（型だけを信用しない）


def _exact_fields(obj: object) -> Dict[str, object]:
    """dataclass の宣言済み field だけを持つこと（後から足された属性は拒否する）。"""
    names = {f.name for f in fields(obj)}  # type: ignore[arg-type]
    _refuse(set(vars(obj)) == names, "PLAN_INTEGRITY_FAILURE", "UNDECLARED_ATTRIBUTE")
    return {name: getattr(obj, name) for name in names}


def _rebuilt_plan(plan: object) -> object:
    _refuse(type(plan) in tuple(PLAN_TYPES.values()), "INVALID_SUBMISSION_INPUT", "NOT_A_VALIDATED_PLAN")
    values = _exact_fields(plan)
    plan_id = values.pop("plan_id")
    try:
        if isinstance(plan, ValidatedThemeProposalPlan):
            values["evidence_refs"] = tuple(PlannedEvidenceRef(**_exact_fields(ref)) for ref in plan.evidence_refs)
        rebuilt = type(plan).build(**values)  # type: ignore[attr-defined]
    except _Refused:
        raise
    except LlmValidationError as exc:
        raise _Refused("PLAN_INTEGRITY_FAILURE", exc.code, str(plan_id)) from None
    except (TypeError, ValueError, AttributeError, KeyError):
        raise _Refused("PLAN_INTEGRITY_FAILURE", "MALFORMED_PLAN", str(plan_id)) from None
    _refuse(rebuilt.plan_id == plan_id, "PLAN_INTEGRITY_FAILURE", "PLAN_ID_MISMATCH", str(plan_id))
    return rebuilt


def _rebuilt_validation(validation: object) -> Tuple[object, ...]:
    _refuse(type(validation) is LlmValidationResult, "INVALID_SUBMISSION_INPUT", "NOT_A_VALIDATION_RESULT")
    values = _exact_fields(validation)
    result_id = values.pop("result_id")
    _refuse(values.get("outcome") is ValidationOutcome.PLANS, "INVALID_SUBMISSION_INPUT", "NOT_VALIDATED")
    _refuse(isinstance(values.get("plans"), tuple) and len(values["plans"]) >= 1, "INVALID_SUBMISSION_INPUT",
            "NO_PLANS")
    plans = tuple(_rebuilt_plan(plan) for plan in values["plans"])  # type: ignore[union-attr]
    try:
        rebuilt = LlmValidationResult.build(**{**values, "plans": plans})
    except LlmValidationError as exc:
        raise _Refused("PLAN_INTEGRITY_FAILURE", exc.code) from None
    except (TypeError, ValueError, AttributeError, KeyError):
        raise _Refused("PLAN_INTEGRITY_FAILURE", "MALFORMED_VALIDATION_RESULT") from None
    _refuse(rebuilt.result_id == result_id, "PLAN_INTEGRITY_FAILURE", "VALIDATION_RESULT_ID_MISMATCH")
    return rebuilt.plans


# ---------------------------------------------------------------- 凍結済み上流 constructor での再構築


def _construct(plan: object, generation: ValidatedGeneration, validation_id: str, submitted_at: datetime) -> _Planned:
    reference = f"llm generation validated as {validation_id}"
    try:
        if isinstance(plan, ValidatedRelationProposalPlan):
            family = AuthorityFamily.B5C_RELATION_PROPOSALS
            proposal = RelationProposal.build(
                **plan.upstream_arguments(), created_at=submitted_at,
                provenance=RelationProposalProvenance(proposer_class=LLM_RELATION_PROPOSER_CLASS,
                                                      proposer_ref=generation.generation_ref,
                                                      rule_version=generation.prompt_contract_version, note=reference))
            replayed = parse_proposal_record(json.loads(canonical_proposal_record_line(proposal)))
            same = canonical_proposal_record_line(replayed) == canonical_proposal_record_line(proposal)
            lock = replayed.provenance.proposer_class is LLM_RELATION_PROPOSER_CLASS
        else:
            family = AuthorityFamily.B3_PROPOSALS
            provenance = ProposalProvenance(LLM_PROPOSER_CLASS, generation.generation_ref,
                                            rule_version=generation.prompt_contract_version, reason=reference)
            if isinstance(plan, ValidatedEvidenceProposalPlan):
                proposal = EvidenceCandidateProposal.build(**plan.upstream_arguments(), provenance=provenance,
                                                           created_at=submitted_at)
            else:
                proposal = ThemeCandidateProposal.build(**plan.upstream_arguments(submitted_at),  # type: ignore[union-attr]
                                                        provenance=provenance, created_at=submitted_at)
            replayed = parse_proposal(json.loads(canonical_proposal_line(proposal)))   # 凍結 loader で全体を検証
            same = canonical_proposal_line(replayed) == canonical_proposal_line(proposal)
            lock = replayed.provenance.proposer_class is LLM_PROPOSER_CLASS  # type: ignore[union-attr]
    except UPSTREAM_ERRORS as exc:
        raise _Refused("PLAN_INTEGRITY_FAILURE", _code_of(exc, "UPSTREAM_REJECTED"), plan.plan_id) from None  # type: ignore[attr-defined]
    _refuse(same and lock, "PLAN_INTEGRITY_FAILURE", "UPSTREAM_ROUND_TRIP", plan.plan_id)  # type: ignore[attr-defined]
    _refuse(proposal.proposal_id == plan.upstream_proposal_id, "UPSTREAM_ID_MISMATCH", "",  # type: ignore[attr-defined]
            plan.plan_id)  # type: ignore[attr-defined]
    return _Planned(family=family, plan=plan, proposal=replayed, generation_ref=generation.generation_ref)


def _line(planned_or_record, family: AuthorityFamily) -> str:
    proposal = planned_or_record.proposal if isinstance(planned_or_record, _Planned) else planned_or_record
    if family is AuthorityFamily.B5C_RELATION_PROPOSALS:
        return canonical_proposal_record_line(proposal)
    return canonical_proposal_line(proposal)


def _authority(family: AuthorityFamily, data_root, *, read_only: bool):
    try:
        if family is AuthorityFamily.B3_PROPOSALS:
            return ProposalStore(data_root, read_only=read_only)
        return RelationProposalStore(data_root, read_only=read_only)
    except STORE_ERRORS as exc:
        raise _Refused("AUTHORITY_CORRUPTION", _code_of(exc, "AUTHORITY_UNUSABLE")) from None
    except (OSError, UnicodeError):
        raise _Refused("AUTHORITY_CORRUPTION", "AUTHORITY_UNREADABLE") from None


# ---------------------------------------------------------------- 提出


def _refused_result(exc: _Refused, planned: Sequence[_Planned] = ()) -> SubmissionResult:
    actions = tuple(PlanSubmission(plan_id=p.plan.plan_id, family=p.family, upstream_proposal_id=p.upstream_id,  # type: ignore[attr-defined]
                                   action=SubmissionAction.NOT_SUBMITTED,
                                   failure_code=exc.code if p.plan.plan_id == exc.plan_id else "")  # type: ignore[attr-defined]
                    for p in planned)
    detail = exc.detail if _CODE_RE.match(exc.detail or "") else ""
    return SubmissionResult(status=SubmissionStatus.REJECTED, actions=actions, failure_code=exc.code,
                            failure_detail=detail)


def _preflight(generations: Sequence[ValidatedGeneration], submitted_at: object) -> Tuple[List[_Planned], datetime]:
    _refuse(isinstance(generations, (tuple, list)) and len(generations) >= 1, "INVALID_SUBMISSION_INPUT", "NO_INPUT")
    _refuse(isinstance(submitted_at, datetime), "INVALID_SUBMISSION_INPUT", "SUBMITTED_AT_REQUIRED")
    try:
        at = ensure_aware(submitted_at, "submitted_at")  # type: ignore[arg-type]
    except ValueError:
        raise _Refused("INVALID_SUBMISSION_INPUT", "NAIVE_SUBMITTED_AT") from None
    planned: List[_Planned] = []
    for generation in generations:
        _refuse(type(generation) is ValidatedGeneration, "INVALID_SUBMISSION_INPUT", "NOT_A_VALIDATED_GENERATION")
        _exact_fields(generation)
        _refuse(isinstance(generation.generation_ref, str) and bool(GENERATION_REF_RE.match(generation.generation_ref)),
                "INVALID_SUBMISSION_INPUT", "GENERATION_REF")
        _refuse(isinstance(generation.prompt_contract_version, str)
                and bool(_TOKEN_RE.match(generation.prompt_contract_version)), "INVALID_SUBMISSION_INPUT",
                "PROMPT_CONTRACT_VERSION")
        plans = _rebuilt_validation(generation.validation)
        _refuse(at >= generation.validation.cutoff, "INVALID_SUBMISSION_INPUT", "SUBMITTED_BEFORE_CUTOFF")
        for plan in plans:
            planned.append(_construct(plan, generation, generation.validation.result_id, at))
    return sorted(planned, key=_Planned.order), at


def _classify(planned: List[_Planned], stores: Dict[AuthorityFamily, object]
              ) -> Tuple[Dict[int, Tuple[SubmissionAction, ReuseKind]], List[int]]:
    """同じ提出の中の重複を畳み、既存 authority と照合する（書き込まない）。key は決定論的な順序での位置。"""
    decided: Dict[int, Tuple[SubmissionAction, ReuseKind]] = {}
    representatives: Dict[Tuple[AuthorityFamily, str], _Planned] = {}
    new: List[int] = []
    for index, item in enumerate(planned):                            # family → 上流 id → 生成 → plan の順
        key = (item.family, item.upstream_id)
        first = representatives.get(key)
        if first is not None:                                          # 同じ提出の中の同じ提案は 1 回だけ扱う
            _refuse(type(first.proposal) is type(item.proposal)
                    and first.proposal.identity_payload() == item.proposal.identity_payload(),  # type: ignore[attr-defined]
                    "PROPOSAL_CONFLICT", "IN_SUBMISSION", item.plan.plan_id)  # type: ignore[attr-defined]
            decided[index] = (SubmissionAction.DUPLICATE_IN_SUBMISSION, ReuseKind.NONE)
            continue
        representatives[key] = item
        existing = stores[item.family].get_proposal(item.upstream_id)  # type: ignore[attr-defined]
        if existing is None:
            decided[index] = (SubmissionAction.NEW_PROPOSAL_APPENDED, ReuseKind.NONE)
            new.append(index)
            continue
        compatible = (type(existing) is type(item.proposal)
                      and existing.identity_payload() == item.proposal.identity_payload())  # type: ignore[attr-defined]
        _refuse(compatible, "PROPOSAL_CONFLICT", "EXISTING_CONTENT_DIFFERS", item.plan.plan_id)  # type: ignore[attr-defined]
        kind = ReuseKind.EXACT if _line(existing, item.family) == _line(item, item.family) else ReuseKind.CONVERGENT
        decided[index] = (SubmissionAction.EXISTING_PROPOSAL_REUSED, kind)
    return decided, new


def _actions(planned: Sequence[_Planned], decided: Dict[int, Tuple[SubmissionAction, ReuseKind]],
             failed: Optional[int] = None, unwritten: Sequence[int] = ()) -> Tuple[PlanSubmission, ...]:
    out = []
    for index, item in enumerate(planned):
        action, reuse = decided[index]
        code = ""
        if index in unwritten:
            action, reuse = SubmissionAction.NOT_SUBMITTED, ReuseKind.NONE
            code = "APPEND_FAILURE" if index == failed else ""
        out.append(PlanSubmission(plan_id=item.plan.plan_id, family=item.family,  # type: ignore[attr-defined]
                                  upstream_proposal_id=item.upstream_id, action=action, reuse=reuse,
                                  line_appended=action is SubmissionAction.NEW_PROPOSAL_APPENDED, failure_code=code))
    return tuple(out)


def submit_proposals(*, generations: Sequence[ValidatedGeneration], submitted_at: datetime,
                     data_root: Union[str, "object"]) -> SubmissionResult:
    """検証済み plan を既存の proposal authority に提出する（decision・実行はしない）。"""
    planned: List[_Planned] = []
    try:
        _refuse(data_root is not None and str(data_root).strip() != "", "INVALID_SUBMISSION_INPUT", "DATA_ROOT_REQUIRED")
        planned, _at = _preflight(generations, submitted_at)
        families = sorted({item.family for item in planned}, key=FAMILY_ORDER.index)
        stores = {family: _authority(family, data_root, read_only=False) for family in families}
        decided, new = _classify(planned, stores)
    except _Refused as exc:                                           # pre-flight の失敗は書き込み 0 件
        return _refused_result(exc, planned)

    written: List[int] = []
    for position, index in enumerate(new):                            # family → 上流 id の決定論的な順序
        item = planned[index]
        try:
            status = stores[item.family].append_proposal(item.proposal)  # type: ignore[attr-defined]
            _refuse(status.status.value == "APPENDED", "APPEND_FAILURE", "UNEXPECTED_ALREADY_PRESENT")
        except (_Refused, *STORE_ERRORS, OSError) as exc:
            code = exc.detail if isinstance(exc, _Refused) else _code_of(exc, "STORE_FAILURE")
            actions = _actions(planned, decided, index, new[position:])
            if not written:
                return SubmissionResult(status=SubmissionStatus.REJECTED, actions=actions, failure_code="APPEND_FAILURE",
                                        failure_detail=code)
            return SubmissionResult(status=SubmissionStatus.PARTIAL_SUBMISSION, actions=actions,
                                    failure_code="PARTIAL_SUBMISSION", failure_detail=f"APPEND_FAILURE:{code}")
        written.append(index)

    try:                                                              # 追記した行を凍結 loader で読み直して確かめる
        appended = [planned[index] for index in written]
        for family in sorted({item.family for item in appended}, key=FAMILY_ORDER.index):
            check = _authority(family, data_root, read_only=True)
            for item in appended:
                if item.family is family:
                    stored = check.get_proposal(item.upstream_id)  # type: ignore[attr-defined]
                    _refuse(stored is not None and _line(stored, family) == _line(item, family), "APPEND_FAILURE",
                            "POST_APPEND_VERIFICATION")
    except _Refused as exc:
        return SubmissionResult(status=SubmissionStatus.PARTIAL_SUBMISSION, actions=_actions(planned, decided),
                                failure_code="PARTIAL_SUBMISSION", failure_detail=f"APPEND_FAILURE:{exc.detail}")
    return SubmissionResult(status=SubmissionStatus.SUBMITTED, actions=_actions(planned, decided))


__all__ = ["GENERATION_REF_RE", "ValidatedGeneration", "submit_proposals"]
