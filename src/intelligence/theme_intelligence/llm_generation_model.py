"""P6-B7E — 生成結果と生成監査 record の純 model（OPERATIONAL / AUDIT。非 authority）。

- `GenerationResult`: 生成 1 回の結末（VALIDATED / ABSTAINED / REJECTED_GENERATION / RETRYABLE_FAILURE /
  INTEGRITY_FAILURE）。VALIDATED は「B7B の parse と B7D の決定論的検証を通った」ことだけを意味する
  （`VALIDATED_MEANING`）。score・severity・順位を持たない。
- `LlmGenerationAuditRecord`: 監査 journal の 1 行。replay / 監査に要る metadata だけを持つ。raw prompt・raw response・
  記事本文・推論過程・資格情報・machine path・portfolio・Compass 資料を持たない（raw response は digest だけ）。

identity の境界:

| identity | 材料 | 含めないもの |
|---|---|---|
| request（`thllmreq_`, B7B） | 何を頼んだか | generated_at・provider・model |
| 生成入力（`thllmgin_`） | prompt contract ＋ task contract ＋ request id ＋ visible manifest | 内部対応表・時刻 |
| attempt（`thllmatt_`） | request id ＋ 生成入力 digest ＋ provider / model / 生成設定 ＋ caller の generated_at | 応答・結末 |
| 監査 record（`thllmaud_`） | record の全内容 | — |
| 提案 plan（`thllmplan_`, B7D） | 正規化済みの提案材料 | provider・model・時刻・生成 id |

B7B の `LlmGenerationRecord` は journal の行ではない（B7B の REJECTED_GENERATION は output digest を持てず、B7D の
検証結果・visible digest・生成入力 digest の欄も無いため）。本 record が B7E の journal 行である。
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Dict, Mapping, Optional, Sequence, Tuple

from ..core.ids import content_id
from ..core.time import ensure_aware
from ..themes.model import canonical_json
from .llm_plan_model import LlmValidationResult
from .llm_proposal_model import AbstentionReason, LlmTask

AUDIT_SCHEMA_VERSION = "theme_llm_generation_audit:0.1.0"
AUDIT_ID_PREFIX = "thllmaud"
ATTEMPT_ID_PREFIX = "thllmatt"
MAX_FAILURE_CODES = 16
MAX_PLAN_IDS = 16

#: 凍結文言（contract / test で固定する）
VALIDATED_MEANING = ("validated means the output parsed under the B7B schema and passed the B7D deterministic "
                     "validation; nothing was accepted, submitted, created, attached, asserted, promoted or recommended")
GENERATION_IS_NOT_AUTHORITY = "a generation result and its audit record are operational metadata, never authority"
JOURNAL_IS_NOT_INPUT = "the generation journal is audit only; it is never read into a generation input or into evidence"

_TOKEN_RE = re.compile(r"^[a-z0-9][a-z0-9_.:-]{0,63}$")
_CODE_RE = re.compile(r"^[A-Z][A-Z0-9_]{0,63}$")
_CREDENTIAL_LIKE = ("secret", "password", "passwd", "api_key", "apikey", "bearer", "credential")
DIGEST_PREFIXES: Mapping[str, str] = {
    "request_id": "thllmreq", "manifest_digest": "thllmin", "visible_digest": "thllmvis",
    "generation_input_digest": "thllmgin", "response_digest": "thllmresp", "output_digest": "thllmout",
    "validation_result_id": "thllmval", "attempt_id": ATTEMPT_ID_PREFIX, "audit_id": AUDIT_ID_PREFIX}


class GenerationModelError(ValueError):
    """record / 結果が契約を満たさない（fail closed）。detail に本文・秘密値を入れない。"""

    def __init__(self, code: str, detail: str = "") -> None:
        super().__init__(f"{code}: {detail}" if detail else code)
        self.code = code
        self.detail = detail


def _require(condition: bool, code: str, detail: str = "") -> None:
    if not condition:
        raise GenerationModelError(code, detail)


class GenerationResultOutcome(str, Enum):
    VALIDATED = "VALIDATED"                       # B7B parse ＋ B7D 検証を通った（提案でも受理でもない）
    ABSTAINED = "ABSTAINED"                       # 正しい棄権（成功。plan 0 件）
    REJECTED_GENERATION = "REJECTED_GENERATION"   # LLM の出力が schema / 検証を満たさない（自動 retry しない）
    RETRYABLE_FAILURE = "RETRYABLE_FAILURE"       # provider の一時的な失敗（retry の方針は範囲外）
    INTEGRITY_FAILURE = "INTEGRITY_FAILURE"       # 束縛・記録済み応答・journal の不整合（止まる）


class FailureStage(str, Enum):
    NONE = "NONE"
    BINDING = "BINDING"
    JOURNAL = "JOURNAL"
    PROVIDER = "PROVIDER"
    PARSE = "PARSE"
    VALIDATION = "VALIDATION"


RETRYABLE_PROVIDER_CODES: Tuple[str, ...] = ("PROVIDER_UNAVAILABLE", "PROVIDER_TIMEOUT", "PROVIDER_FAILURE")
INTEGRITY_PROVIDER_CODES: Tuple[str, ...] = ("RECORDED_INPUT_MISMATCH", "PROVIDER_CONTRACT_VIOLATION")
#: B7D の code のうち、LLM の出力ではなく呼び出し側の不整合を表すもの
INTEGRITY_VALIDATION_CODES: Tuple[str, ...] = ("INVALID_INPUT", "REQUEST_MANIFEST_MISMATCH", "KNOWLEDGE_PIN_MISMATCH")
SUCCESS_OUTCOMES: Tuple[GenerationResultOutcome, ...] = (GenerationResultOutcome.VALIDATED,
                                                         GenerationResultOutcome.ABSTAINED)


def classify_failure(stage: FailureStage, code: str) -> GenerationResultOutcome:
    """失敗の段階と code から結末を決める（決定論。表は contract §12）。"""
    if stage in (FailureStage.BINDING, FailureStage.JOURNAL):
        return GenerationResultOutcome.INTEGRITY_FAILURE
    if stage is FailureStage.PROVIDER:
        if code in RETRYABLE_PROVIDER_CODES:
            return GenerationResultOutcome.RETRYABLE_FAILURE
        return GenerationResultOutcome.INTEGRITY_FAILURE
    if stage is FailureStage.VALIDATION and code in INTEGRITY_VALIDATION_CODES:
        return GenerationResultOutcome.INTEGRITY_FAILURE
    _require(stage in (FailureStage.PARSE, FailureStage.VALIDATION), "INVALID_RECORD", "a failure names its stage")
    return GenerationResultOutcome.REJECTED_GENERATION


def _codes(values: object, name: str) -> Tuple[str, ...]:
    _require(isinstance(values, (tuple, list)) and all(isinstance(v, str) and _CODE_RE.match(v) for v in values),
             "INVALID_RECORD", f"{name} are bounded codes")
    codes = tuple(sorted(set(values)))  # type: ignore[arg-type]
    _require(len(codes) <= MAX_FAILURE_CODES, "INVALID_RECORD", f"too many {name}")
    return codes


# ---------------------------------------------------------------- 生成結果


@dataclass(frozen=True, kw_only=True)
class GenerationResult:
    """生成 1 回の結末。VALIDATED / ABSTAINED だけが B7D の検証結果（plan）を持つ。失敗は authority を変えない。"""

    outcome: GenerationResultOutcome
    failure_stage: FailureStage = FailureStage.NONE
    failure_code: str = ""
    failure_codes: Tuple[str, ...] = ()
    validation: Optional[LlmValidationResult] = None

    def __post_init__(self) -> None:
        _require(isinstance(self.outcome, GenerationResultOutcome) and isinstance(self.failure_stage, FailureStage),
                 "INVALID_RESULT", "outcome and stage are enums")
        object.__setattr__(self, "failure_codes", _codes(self.failure_codes, "failure codes"))
        if self.outcome in SUCCESS_OUTCOMES:
            _require(self.failure_stage is FailureStage.NONE and self.failure_code == "" and not self.failure_codes,
                     "INVALID_RESULT", "a successful generation carries no failure")
            _require(isinstance(self.validation, LlmValidationResult), "INVALID_RESULT",
                     "a successful generation carries its B7D validation result")
            abstained = self.validation.outcome.value == "ABSTAINED"  # type: ignore[union-attr]
            _require(abstained == (self.outcome is GenerationResultOutcome.ABSTAINED), "INVALID_RESULT",
                     "VALIDATED holds plans and ABSTAINED holds none")
        else:
            _require(self.validation is None, "INVALID_RESULT", "a failed generation carries no plan")
            _require(bool(_CODE_RE.match(self.failure_code)) and self.failure_code in self.failure_codes,
                     "INVALID_RESULT", "a failure names its code")
            _require(classify_failure(self.failure_stage, self.failure_code) is self.outcome, "INVALID_RESULT",
                     "the outcome does not follow the failure taxonomy")

    @property
    def plans(self) -> tuple:
        return self.validation.plans if self.validation is not None else ()


# ---------------------------------------------------------------- 監査 record（journal の 1 行）


AUDIT_FIELDS: Tuple[str, ...] = (
    "audit_schema_version", "audit_id", "attempt_id", "request_id", "manifest_digest", "visible_digest", "task",
    "cutoff", "generated_at", "prompt_contract_version", "output_schema_version", "knowledge_versions",
    "generation_input_digest", "provider_ref", "model_ref", "generation_config_ref", "outcome", "failure_stage",
    "failure_code", "failure_codes", "response_digest", "output_digest", "validation_result_id", "plan_ids",
    "abstention_reason")


def _token(value: object, name: str, *, required: bool = True) -> str:
    if value == "" and not required:
        return ""
    _require(isinstance(value, str) and bool(_TOKEN_RE.match(str(value))), "INVALID_RECORD",
             f"{name} is not a bounded token")
    lowered = str(value).lower()
    _require(not lowered.startswith("sk-") and not any(word in lowered for word in _CREDENTIAL_LIKE),
             "INVALID_RECORD", f"{name} looks like a credential")
    return str(value)


def _digest(value: object, name: str, *, required: bool) -> str:
    if value == "" and not required:
        return ""
    prefix = DIGEST_PREFIXES[name]
    _require(isinstance(value, str) and bool(re.match(rf"^{prefix}_[0-9a-f]{{24}}$", str(value))), "INVALID_RECORD",
             f"{name} is not a {prefix} digest")
    return str(value)


def _aware(value: object, name: str) -> datetime:
    _require(isinstance(value, datetime), "INVALID_RECORD", f"{name} is a datetime")
    try:
        return ensure_aware(value, name)  # type: ignore[arg-type]
    except ValueError:
        raise GenerationModelError("INVALID_RECORD", f"{name} must be timezone-aware") from None


def _pins(values: object) -> Tuple[Tuple[str, str], ...]:
    _require(isinstance(values, (tuple, list)) and all(isinstance(p, (tuple, list)) and len(p) == 2 for p in values),
             "INVALID_RECORD", "knowledge versions are (name, version) pairs")
    pairs = tuple(sorted((_token(p[0], "knowledge name"), _token(p[1], "knowledge version")) for p in values))  # type: ignore[union-attr]
    _require(len({name for name, _v in pairs}) == len(pairs), "INVALID_RECORD", "a knowledge name is pinned twice")
    return pairs


def attempt_id_of(*, request_id: str, generation_input_digest: str, provider_ref: str, model_ref: str,
                  generation_config_ref: str, generated_at: datetime) -> str:
    """生成の試行の identity。caller が与える generated_at を束縛する（応答・結末は含まない）。"""
    return content_id(ATTEMPT_ID_PREFIX, canonical_json({
        "request_id": request_id, "generation_input_digest": generation_input_digest, "provider_ref": provider_ref,
        "model_ref": model_ref, "generation_config_ref": generation_config_ref, "generated_at": generated_at}))


@dataclass(frozen=True, kw_only=True)
class LlmGenerationAuditRecord:
    """生成監査 journal の 1 行（OPERATIONAL / AUDIT）。evidence として読まれることは無い。"""

    audit_schema_version: str = AUDIT_SCHEMA_VERSION
    audit_id: str
    attempt_id: str
    request_id: str
    manifest_digest: str
    visible_digest: str
    task: LlmTask
    cutoff: datetime
    generated_at: datetime                     # caller が与える（現在時刻を読まない）。可視性の判定には使わない
    prompt_contract_version: str
    output_schema_version: str
    knowledge_versions: Tuple[Tuple[str, str], ...]
    generation_input_digest: str = ""          # BINDING 失敗では空（入力を組まない）
    provider_ref: str
    model_ref: str = ""
    generation_config_ref: str
    outcome: GenerationResultOutcome
    failure_stage: FailureStage = FailureStage.NONE
    failure_code: str = ""
    failure_codes: Tuple[str, ...] = ()
    response_digest: str = ""                  # raw response は保存しない（digest だけ）
    output_digest: str = ""
    validation_result_id: str = ""
    plan_ids: Tuple[str, ...] = ()
    abstention_reason: Optional[AbstentionReason] = None

    def __post_init__(self) -> None:
        _require(self.audit_schema_version == AUDIT_SCHEMA_VERSION, "UNSUPPORTED_SCHEMA_VERSION",
                 "unsupported audit schema version")
        _require(isinstance(self.task, LlmTask) and isinstance(self.outcome, GenerationResultOutcome)
                 and isinstance(self.failure_stage, FailureStage), "INVALID_RECORD", "task, outcome and stage are enums")
        _require(self.abstention_reason is None or isinstance(self.abstention_reason, AbstentionReason),
                 "INVALID_RECORD", "abstention reason is an enum")
        cutoff, generated = _aware(self.cutoff, "cutoff"), _aware(self.generated_at, "generated_at")
        _require(generated >= cutoff, "INVALID_RECORD", "generated_at must not precede the cutoff")
        for name in ("request_id", "manifest_digest", "visible_digest"):
            _digest(getattr(self, name), name, required=True)
        for name in ("generation_input_digest", "response_digest", "output_digest", "validation_result_id"):
            _digest(getattr(self, name), name, required=False)
        for name in ("prompt_contract_version", "output_schema_version", "provider_ref", "generation_config_ref"):
            _token(getattr(self, name), name)
        _token(self.model_ref, "model_ref", required=False)
        object.__setattr__(self, "knowledge_versions", _pins(self.knowledge_versions))
        object.__setattr__(self, "failure_codes", _codes(self.failure_codes, "failure codes"))
        _require(isinstance(self.plan_ids, (tuple, list)) and all(
            isinstance(p, str) and re.match(r"^thllmplan_[0-9a-f]{24}$", p) for p in self.plan_ids)
            and len(self.plan_ids) <= MAX_PLAN_IDS, "INVALID_RECORD", "plan ids are B7D plan ids")
        object.__setattr__(self, "plan_ids", tuple(sorted(set(self.plan_ids))))
        self._check_outcome()
        _require(self.attempt_id == attempt_id_of(
            request_id=self.request_id, generation_input_digest=self.generation_input_digest,
            provider_ref=self.provider_ref, model_ref=self.model_ref, generation_config_ref=self.generation_config_ref,
            generated_at=self.generated_at), "INVALID_RECORD_ID", "attempt_id does not match the attempt")
        _require(self.audit_id == content_id(AUDIT_ID_PREFIX, canonical_json(self.identity_payload())),
                 "INVALID_RECORD_ID", "audit_id does not match the record content")

    def _check_outcome(self) -> None:
        answered, parsed = bool(self.response_digest), bool(self.output_digest)
        validated = bool(self.validation_result_id)
        _require(parsed <= answered, "INVALID_COMBINATION", "an output digest needs a response")
        _require((self.failure_stage is FailureStage.BINDING) == (self.generation_input_digest == ""),
                 "INVALID_COMBINATION", "only a binding failure has no generation input")
        outcome = self.outcome
        if outcome in SUCCESS_OUTCOMES:
            ok = (self.failure_stage is FailureStage.NONE and not self.failure_code and not self.failure_codes
                  and answered and parsed and validated)
            if outcome is GenerationResultOutcome.VALIDATED:
                ok = ok and len(self.plan_ids) >= 1 and self.abstention_reason is None
            else:
                ok = ok and not self.plan_ids and self.abstention_reason is not None
            _require(ok, "INVALID_COMBINATION", f"fields do not fit outcome {outcome.value}")
            return
        _require(self.failure_stage is not FailureStage.NONE and self.failure_code in self.failure_codes
                 and not validated and not self.plan_ids and self.abstention_reason is None, "INVALID_COMBINATION",
                 f"fields do not fit outcome {outcome.value}")
        _require(classify_failure(self.failure_stage, self.failure_code) is outcome, "INVALID_COMBINATION",
                 "the outcome does not follow the failure taxonomy")
        stage = self.failure_stage
        _require(stage is not FailureStage.JOURNAL, "INVALID_COMBINATION", "a journal failure is never recorded")
        if stage in (FailureStage.BINDING, FailureStage.PROVIDER):
            _require(not answered and not parsed, "INVALID_COMBINATION", "no usable response reached the parser")
        elif stage is FailureStage.PARSE:
            _require(answered and not parsed, "INVALID_COMBINATION", "a parse failure has a response and no output")
        else:
            _require(answered and parsed, "INVALID_COMBINATION", "a validation failure has a parsed output")

    def identity_payload(self) -> Dict[str, object]:
        payload = {name: getattr(self, name) for name in AUDIT_FIELDS if name != "audit_id"}
        payload["knowledge_versions"] = [list(pin) for pin in self.knowledge_versions]
        return json.loads(canonical_json(payload))

    def as_dict(self) -> Dict[str, object]:
        return {**self.identity_payload(), "audit_id": self.audit_id}

    @classmethod
    def build(cls, **values) -> "LlmGenerationAuditRecord":
        attempt = attempt_id_of(request_id=values["request_id"],
                                generation_input_digest=values.get("generation_input_digest", ""),
                                provider_ref=values["provider_ref"], model_ref=values.get("model_ref", ""),
                                generation_config_ref=values["generation_config_ref"],
                                generated_at=values["generated_at"])
        shell = object.__new__(cls)
        defaults = {name: getattr(cls, name) for name in AUDIT_FIELDS if hasattr(cls, name)}
        for name, value in {**defaults, **values, "attempt_id": attempt}.items():
            object.__setattr__(shell, name, value)
        object.__setattr__(shell, "knowledge_versions", tuple(tuple(p) for p in values.get("knowledge_versions", ())))
        object.__setattr__(shell, "failure_codes", tuple(sorted(set(values.get("failure_codes", ())))))
        object.__setattr__(shell, "plan_ids", tuple(sorted(set(values.get("plan_ids", ())))))
        try:
            audit = content_id(AUDIT_ID_PREFIX, canonical_json(cls.identity_payload(shell)))
        except (AttributeError, TypeError, ValueError):
            raise GenerationModelError("INVALID_RECORD", "record fields are malformed") from None
        return cls(audit_id=audit, attempt_id=attempt, **values)

    @classmethod
    def from_dict(cls, data: object) -> "LlmGenerationAuditRecord":
        _require(isinstance(data, dict), "INVALID_RECORD", "an audit record is a JSON object")
        payload: Mapping[str, object] = data  # type: ignore[assignment]
        unknown = sorted(set(payload) - set(AUDIT_FIELDS))
        _require(not unknown, "UNKNOWN_FIELD", f"unknown field(s) {unknown}")
        missing = sorted(set(AUDIT_FIELDS) - set(payload))
        _require(not missing, "MISSING_FIELD", f"missing field(s) {missing}")
        _require(payload["audit_schema_version"] == AUDIT_SCHEMA_VERSION, "UNSUPPORTED_SCHEMA_VERSION",
                 "unsupported audit schema version")
        times = {}
        for name in ("cutoff", "generated_at"):
            _require(isinstance(payload[name], str), "INVALID_RECORD", f"{name} is an ISO datetime")
            try:
                times[name] = datetime.fromisoformat(str(payload[name]))
            except ValueError:
                raise GenerationModelError("INVALID_RECORD", f"{name} is not an ISO datetime") from None
        try:
            task = LlmTask(payload["task"])
            outcome = GenerationResultOutcome(payload["outcome"])
            stage = FailureStage(payload["failure_stage"])
            reason = None if payload["abstention_reason"] is None else AbstentionReason(payload["abstention_reason"])
        except (ValueError, TypeError):
            raise GenerationModelError("INVALID_RECORD", "an enum field holds an unknown value") from None
        for name in ("knowledge_versions", "failure_codes", "plan_ids"):
            _require(isinstance(payload[name], list), "INVALID_RECORD", f"{name} is a list")
        values = {name: payload[name] for name in AUDIT_FIELDS}
        values.update(times, task=task, outcome=outcome, failure_stage=stage, abstention_reason=reason,
                      knowledge_versions=tuple(tuple(p) if isinstance(p, list) else p
                                               for p in payload["knowledge_versions"]),  # type: ignore[union-attr]
                      failure_codes=tuple(payload["failure_codes"]), plan_ids=tuple(payload["plan_ids"]))  # type: ignore[arg-type]
        return cls(**values)  # type: ignore[arg-type]


def canonical_audit_line(record: LlmGenerationAuditRecord) -> str:
    """journal に追記する canonical 1 行（`\\n` 終端）。"""
    _require(isinstance(record, LlmGenerationAuditRecord), "INVALID_RECORD", "not a generation audit record")
    return canonical_json(record.as_dict()) + "\n"


def plan_ids_of(result: GenerationResult) -> Sequence[str]:
    return tuple(plan.plan_id for plan in result.plans)


__all__ = ["ATTEMPT_ID_PREFIX", "AUDIT_FIELDS", "AUDIT_ID_PREFIX", "AUDIT_SCHEMA_VERSION", "FailureStage",
           "GENERATION_IS_NOT_AUTHORITY", "GenerationModelError", "GenerationResult", "GenerationResultOutcome",
           "INTEGRITY_PROVIDER_CODES", "INTEGRITY_VALIDATION_CODES", "JOURNAL_IS_NOT_INPUT", "LlmGenerationAuditRecord",
           "RETRYABLE_PROVIDER_CODES", "SUCCESS_OUTCOMES", "VALIDATED_MEANING", "attempt_id_of",
           "canonical_audit_line", "classify_failure", "plan_ids_of"]
