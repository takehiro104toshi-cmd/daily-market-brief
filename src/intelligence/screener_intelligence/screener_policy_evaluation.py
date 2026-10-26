"""P8-B4A — 明示に選んだ方針の authority（B3）→ 凍結 B1 の方針 → 凍結 B2 の評価、の決定論の orchestration（合成 ・private）。

答える問い: 「正確に指名された人が審査した方針で、この文脈の下で、凍結の評価器は何と言うか」だけ。方針を選ばない ・順位にしない ・推奨しない ・
保存しない。

- 方針の選択は明示だけ: 正確な `policy_id` か正確な `(policy_key, version)`（`PolicySelector`。両方 ・どちらも無しは拒む）。latest ・current ・
  active ・default ・最高の版 ・最新の reviewed_at ・自動の発見 ・fallback は無い。正確に解決できなければ fail closed。
- authority の検証: B3 store の integrity（`validate`）→ read-only で開く → 正確な record → 凍結 B3 ・B1 の復元（store が開く時に行う）→ authority
  の分類の完全一致 → 方針の mode ＝ 文脈の mode → 文脈の policy_id ＝ 解決した policy_id。caller が渡す方針の内容は使わない（store が方針の源）。
- 評価は凍結 B2 `evaluate_policy` を呼ぶだけ（式 ・期間の選択 ・authority の写像 ・ALL_OF ・Decimal の比較は複製しない）。
- 失敗は型つき（`PolicyEvaluationError`。store の破損を NOT_EVALUABLE に潰さない。authority の破損は市場 data の欠損ではない）。
- 結果は凍結 B1 の `ScreenerResult`（DERIVED_NON_AUTHORITY_NON_PERSISTENT）。結果の store ・journal ・watchlist は作らない。安全な投影は
  `screener_result_summary`。
記録: `docs/databank/PHASE8_B4A_POLICY_EVALUATION_SAFE_PROJECTION.md`。
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any, Optional

from .screener_criteria_model import CriteriaPolicy, EvaluationContext, ScreenerResult
from .screener_evaluator import EvaluationInputs, ScreenerEvaluationError, evaluate_policy
from .screener_policy_authority_model import HUMAN_REVIEWED_SCREENING_POLICY, PolicyAuthorityRecord
from .screener_policy_authority_store import (IntegrityStatus, PolicyAppendRejected, PolicyAuthorityStore,
                                              PolicyStoreCorrupt, PolicyStoreMissing)

ORCHESTRATION_RULES_VERSION = "p8_screener_policy_evaluation:0.1.0"
#: 選択は明示だけ（latest ・current ・active ・default ・最高の版 ・最新の審査 ・自動の発見 ・fallback は無い）
SELECTION_RULE = "EXPLICIT_POLICY_ID_OR_EXACT_KEY_VERSION_ONLY_NO_AUTOMATIC_SELECTION"


class PolicyEvaluationFailure(str, Enum):
    SELECTOR_INVALID = "SELECTOR_INVALID"
    POLICY_NOT_FOUND = "POLICY_NOT_FOUND"
    KEY_VERSION_NOT_FOUND = "KEY_VERSION_NOT_FOUND"
    STORE_INTEGRITY_FAILURE = "STORE_INTEGRITY_FAILURE"
    AUTHORITY_CORRUPTION = "AUTHORITY_CORRUPTION"
    AUTHORITY_CLASS_MISMATCH = "AUTHORITY_CLASS_MISMATCH"
    AUTHORITY_MODE_MISMATCH = "AUTHORITY_MODE_MISMATCH"
    CONTEXT_POLICY_MISMATCH = "CONTEXT_POLICY_MISMATCH"
    EVALUATOR_CONTRACT_FAILURE = "EVALUATOR_CONTRACT_FAILURE"
    INVALID_INPUT = "INVALID_INPUT"


class PolicyEvaluationError(RuntimeError):
    """orchestration の型つきの失敗（市場 data の欠損ではない。結果の状態には潰さない）。"""

    def __init__(self, failure: PolicyEvaluationFailure, code: str = "", detail: str = "") -> None:
        super().__init__(f"{failure.value}: {code}" if code else failure.value)
        self.failure = failure
        self.code = code or failure.value
        self.detail = detail


def _fail(failure: PolicyEvaluationFailure, code: str = "", detail: str = "") -> None:
    raise PolicyEvaluationError(failure, code, detail)


@dataclass(frozen=True, kw_only=True)
class PolicySelector:
    """正確な選択子: `policy_id` か `(policy_key, version)` のちょうど 1 つ。省略 ・推定 ・既定は無い。"""

    policy_id: Optional[str] = None
    policy_key: Optional[str] = None
    version: Optional[int] = None

    def __post_init__(self) -> None:
        by_id = self.policy_id is not None
        by_key = self.policy_key is not None or self.version is not None
        if by_id == by_key:
            _fail(PolicyEvaluationFailure.SELECTOR_INVALID, "SELECTOR_SHAPE", "exactly one of policy_id or key+version")
        if by_id and (not isinstance(self.policy_id, str) or not self.policy_id.startswith("p8pol_")):
            _fail(PolicyEvaluationFailure.SELECTOR_INVALID, "INVALID_POLICY_ID", "policy_id")
        if by_key and (not isinstance(self.policy_key, str) or self.policy_key == ""
                       or type(self.version) is not int or isinstance(self.version, bool)):
            _fail(PolicyEvaluationFailure.SELECTOR_INVALID, "INVALID_KEY_VERSION", "policy_key/version")

    def as_dict(self) -> dict:
        return {"policy_id": self.policy_id, "policy_key": self.policy_key, "version": self.version}


@dataclass(frozen=True, kw_only=True)
class PolicyEvaluationOutcome:
    """解決した authority record ・凍結の方針 ・private の結果（B1 `ScreenerResult`。保存しない）。"""

    selector: PolicySelector
    record: PolicyAuthorityRecord
    result: ScreenerResult
    rules_version: str = ORCHESTRATION_RULES_VERSION

    @property
    def policy(self) -> CriteriaPolicy:
        return self.record.policy


def open_verified_store(data_root: Any) -> PolicyAuthorityStore:
    """integrity を検査してから read-only で開く。欠落 ・破損は型つきの失敗（NOT_EVALUABLE ではない）。"""
    try:
        report = PolicyAuthorityStore.validate(data_root)
    except PolicyAppendRejected as exc:                                           # DATA_ROOT_REQUIRED
        raise PolicyEvaluationError(PolicyEvaluationFailure.INVALID_INPUT, exc.code, exc.detail) from None
    if report.status is not IntegrityStatus.OK:
        _fail(PolicyEvaluationFailure.STORE_INTEGRITY_FAILURE, report.failure_code, f"line {report.line_number}")
    try:
        return PolicyAuthorityStore.open(data_root, read_only=True)
    except (PolicyStoreMissing, PolicyStoreCorrupt) as exc:                       # validate と open の間の変化
        raise PolicyEvaluationError(PolicyEvaluationFailure.AUTHORITY_CORRUPTION, exc.code, exc.detail) from None


def resolve_policy(store: PolicyAuthorityStore, selector: PolicySelector) -> PolicyAuthorityRecord:
    """正確な解決だけ。見つからなければ型つきの失敗。authority の分類は完全一致を要求する。"""
    if not isinstance(store, PolicyAuthorityStore) or not isinstance(selector, PolicySelector):
        _fail(PolicyEvaluationFailure.INVALID_INPUT, "INVALID_ARGUMENTS", "store/selector")
    if selector.policy_id is not None:
        record = store.get_by_policy_id(selector.policy_id)
        if record is None:
            _fail(PolicyEvaluationFailure.POLICY_NOT_FOUND, "POLICY_NOT_FOUND", "policy_id")
    else:
        record = store.get_by_key_version(selector.policy_key, selector.version)
        if record is None:
            _fail(PolicyEvaluationFailure.KEY_VERSION_NOT_FOUND, "KEY_VERSION_NOT_FOUND", "policy_key/version")
    if record.authority_class != HUMAN_REVIEWED_SCREENING_POLICY:
        _fail(PolicyEvaluationFailure.AUTHORITY_CLASS_MISMATCH, "AUTHORITY_CLASS_MISMATCH", record.authority_class)
    if record.policy.policy_id != record.record_id:                              # 凍結 B3 の不変条件の再確認
        _fail(PolicyEvaluationFailure.AUTHORITY_CORRUPTION, "POLICY_ID_MISMATCH", "record_id")
    return record


def evaluate_selected_policy(data_root: Any, selector: PolicySelector, context: EvaluationContext,
                             inputs: EvaluationInputs) -> PolicyEvaluationOutcome:
    """B3（read-only）→ 正確な方針 → 凍結 B2。方針の内容は store からだけ取る。結果は保存しない。"""
    if not isinstance(selector, PolicySelector):
        _fail(PolicyEvaluationFailure.INVALID_INPUT, "INVALID_SELECTOR", "selector")
    if not isinstance(context, EvaluationContext) or not isinstance(inputs, EvaluationInputs):
        _fail(PolicyEvaluationFailure.INVALID_INPUT, "INVALID_CONTEXT_OR_INPUTS", "context/inputs")
    record = resolve_policy(open_verified_store(data_root), selector)
    policy = record.policy
    if policy.policy_id != context.policy_id:
        _fail(PolicyEvaluationFailure.CONTEXT_POLICY_MISMATCH, "CONTEXT_POLICY_MISMATCH", "context.policy_id")
    if policy.authority_mode is not context.authority_mode:
        _fail(PolicyEvaluationFailure.AUTHORITY_MODE_MISMATCH, "AUTHORITY_MODE_MISMATCH", policy.authority_mode.value)
    try:
        result = evaluate_policy(policy, context, inputs)
    except ScreenerEvaluationError as exc:
        raise PolicyEvaluationError(PolicyEvaluationFailure.EVALUATOR_CONTRACT_FAILURE, exc.code, exc.detail) from None
    return PolicyEvaluationOutcome(selector=selector, record=record, result=result)


__all__ = ["ORCHESTRATION_RULES_VERSION", "SELECTION_RULE", "PolicyEvaluationError", "PolicyEvaluationFailure",
           "PolicyEvaluationOutcome", "PolicySelector", "evaluate_selected_policy", "open_verified_store",
           "resolve_policy"]
