"""P6-B7E — 生成の orchestration（非 authority）。

`run_generation(*, request, manifest, provider, journal=None) -> GenerationRun`

```
prepare_generation（B7C の見える部分 ＋ prompt contract）→ provider.generate（1 回だけ）→ raw response
→ B7B の厳格 parse（修復・code fence 除去・散文からの JSON 抽出をしない）→ B7D の決定論的検証 → 生成結果
```

- provider の呼び出しは生成 1 回につき 1 回。検証を通るまで引き直さない（retry の方針は範囲外）。
- 書いてよいのは生成監査 journal（`LlmGenerationJournal`）だけ。B3 / B5C の提案・decision・Theme・attachment・
  relation assertion・governance には書かない（import もしない）。
- journal が使えなければ生成の前に止まる（INTEGRITY_FAILURE。provider を呼ばない）。記録できなかった生成の plan は返さない。
- journal の内容を生成入力に使わない（自己強化の禁止）。
- 時刻は caller の `request.generated_at` だけ（現在時刻を読まない）。可視性の境界は B7C の cutoff のまま。
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Optional, Tuple

from .llm_generation_input import GenerationInput, GenerationInputError, prepare_generation
from .llm_generation_journal import GenerationJournalError, LlmGenerationJournal
from .llm_generation_model import (FailureStage, GenerationModelError, GenerationResult, GenerationResultOutcome,
                                   LlmGenerationAuditRecord, classify_failure)
from .llm_manifest_model import LlmInputManifest
from .llm_plan_model import LlmValidationError, ValidationOutcome
from .llm_proposal_model import (OUTPUT_SCHEMA_VERSION, LlmGenerationRequest, LlmModelError, parse_generation_output,
                                 response_digest_of)
from .llm_provider import ProviderError, ProviderFailureKind
from .llm_validator import validate_generation

PROVIDER_FAILURE_CODES = {ProviderFailureKind.UNAVAILABLE: "PROVIDER_UNAVAILABLE",
                          ProviderFailureKind.TIMEOUT: "PROVIDER_TIMEOUT",
                          ProviderFailureKind.FAILURE: "PROVIDER_FAILURE",
                          ProviderFailureKind.INPUT_MISMATCH: "RECORDED_INPUT_MISMATCH"}


class JournalStatus(str, Enum):
    NOT_REQUESTED = "NOT_REQUESTED"      # journal を渡されていない
    APPENDED = "APPENDED"
    ALREADY_PRESENT = "ALREADY_PRESENT"  # 同じ attempt の同じ record（冪等）
    NOT_RECORDED = "NOT_RECORDED"        # journal が使えない・衝突した（plan は返さない）


@dataclass(frozen=True)
class GenerationRun:
    result: GenerationResult
    audit_record: Optional[LlmGenerationAuditRecord]
    journal_status: JournalStatus


def _failure(stage: FailureStage, code: str, codes: Tuple[str, ...] = ()) -> GenerationResult:
    return GenerationResult(outcome=classify_failure(stage, code), failure_stage=stage, failure_code=code,
                            failure_codes=tuple(codes) or (code,))


def _unrecorded(stage: FailureStage, code: str) -> GenerationRun:
    return GenerationRun(result=_failure(stage, code), audit_record=None, journal_status=JournalStatus.NOT_RECORDED)


def _call_provider(provider, generation_input: GenerationInput) -> Tuple[Optional[str], Optional[GenerationResult]]:
    """provider を 1 回だけ呼ぶ。失敗は有界な code にする（応答・入力の本文を写さない）。"""
    try:
        raw = provider.generate(generation_input)
    except ProviderError as exc:
        return None, _failure(FailureStage.PROVIDER, PROVIDER_FAILURE_CODES.get(exc.kind, "PROVIDER_CONTRACT_VIOLATION"))
    except Exception:                                                  # provider の契約違反（何が起きても 1 回で止まる）
        return None, _failure(FailureStage.PROVIDER, "PROVIDER_CONTRACT_VIOLATION")
    if not isinstance(raw, str):
        return None, _failure(FailureStage.PROVIDER, "PROVIDER_CONTRACT_VIOLATION")
    return raw, None


def run_generation(*, request: LlmGenerationRequest, manifest: LlmInputManifest, provider,
                   journal: Optional[LlmGenerationJournal] = None) -> GenerationRun:
    """生成 1 回。結果は非 authority で、書き込みは生成監査 journal だけ。"""
    if not isinstance(request, LlmGenerationRequest) or not isinstance(manifest, LlmInputManifest):
        return _unrecorded(FailureStage.BINDING, "INVALID_INPUT")
    if journal is not None:
        if not isinstance(journal, LlmGenerationJournal):
            return _unrecorded(FailureStage.JOURNAL, "JOURNAL_REJECTED")
        try:
            journal.revalidate()                                        # 使えない journal では生成しない
        except GenerationJournalError as exc:
            return _unrecorded(FailureStage.JOURNAL, exc.category.value)
    refs = {}
    for name in ("provider_ref", "model_ref", "generation_config_ref"):
        refs[name] = getattr(provider, name, None)
    if not all(isinstance(value, str) for value in refs.values()) or not callable(getattr(provider, "generate", None)):
        return _unrecorded(FailureStage.PROVIDER, "PROVIDER_CONTRACT_VIOLATION")

    input_digest, response_digest, output_digest = "", "", ""
    validation = None
    try:
        generation_input = prepare_generation(request, manifest)
    except GenerationInputError as exc:
        result = _failure(FailureStage.BINDING, exc.code)
    else:
        input_digest = generation_input.digest()
        raw, result = _call_provider(provider, generation_input)
        if raw is not None:
            response_digest = response_digest_of(raw)                   # raw response は保存しない（digest だけ）
            try:
                envelope = parse_generation_output(raw)                 # 厳格 parse。修復しない
            except LlmModelError as exc:
                result = _failure(FailureStage.PARSE, exc.code)
            else:
                output_digest = envelope.output_digest()
                try:
                    validation = validate_generation(request=request, envelope=envelope, manifest=manifest)
                except LlmValidationError as exc:
                    result = _failure(FailureStage.VALIDATION, exc.code, exc.codes)
                else:
                    outcome = (GenerationResultOutcome.ABSTAINED if validation.outcome is ValidationOutcome.ABSTAINED
                               else GenerationResultOutcome.VALIDATED)
                    result = GenerationResult(outcome=outcome, validation=validation)
    try:
        record = LlmGenerationAuditRecord.build(
            request_id=request.request_id, manifest_digest=request.manifest_digest,
            visible_digest=manifest.visible_digest(), task=request.task, cutoff=request.cutoff,
            generated_at=request.generated_at, prompt_contract_version=request.prompt_contract_version,
            output_schema_version=OUTPUT_SCHEMA_VERSION, knowledge_versions=request.knowledge_versions,
            generation_input_digest=input_digest, provider_ref=refs["provider_ref"], model_ref=refs["model_ref"],
            generation_config_ref=refs["generation_config_ref"], outcome=result.outcome,  # type: ignore[union-attr]
            failure_stage=result.failure_stage, failure_code=result.failure_code,  # type: ignore[union-attr]
            failure_codes=result.failure_codes, response_digest=response_digest,  # type: ignore[union-attr]
            output_digest=output_digest, validation_result_id=validation.result_id if validation else "",
            plan_ids=tuple(plan.plan_id for plan in validation.plans) if validation else (),
            abstention_reason=validation.abstention_reason if validation else None)
    except GenerationModelError:                                        # provider の識別子が監査 record の契約外
        return _unrecorded(FailureStage.PROVIDER, "PROVIDER_CONTRACT_VIOLATION")
    if journal is None:
        return GenerationRun(result=result, audit_record=record,  # type: ignore[arg-type]
                             journal_status=JournalStatus.NOT_REQUESTED)
    try:
        appended = journal.append(record)
    except GenerationJournalError as exc:                              # 記録できない生成の plan は返さない
        return _unrecorded(FailureStage.JOURNAL, exc.category.value)
    return GenerationRun(result=result, audit_record=record,  # type: ignore[arg-type]
                         journal_status=JournalStatus(appended.status.value))


__all__ = ["GenerationRun", "JournalStatus", "PROVIDER_FAILURE_CODES", "run_generation"]
