"""P8-ID2 — 人が承認した identity を凍結 A1 の authority へ登録する、明示の実行の境界（append-only ・再検証つき）。

信頼の境界:
- 入力は **元の合成の master の行 ＋ `BootstrapBatch`（D0）＋ 人の `ReviewedManifest` ＋ 明示の `data_root`**。実行のたびに凍結 ID1 を
  再実行して manifest を作り直し（人が審査した機械の manifest と digest が一致することを確かめ）、審査の結びつきを検証し、
  `RegistrationPlan` を作り直す。caller の `RegistrationPlan` は任意の cross-check だけ（不一致 → `REJECTED / PRIOR_PLAN_MISMATCH`。書かない）。
- 登録を authorize できるのは reviewer `HUMAN` の `APPROVE` だけ。REJECT ・DEFER ・未審査 ・古い審査 ・digest の不一致は登録しない。
- `accepted_at` は人の審査の受理の時刻（審査の event の metadata）。caller が審査のときに明示に渡し、ID2 は作らず ・実行の時刻で置き換えず ・
  再検証を通して保つ。provider の有効時間でも D0 でもない。時計を読まない。

A1 の現在の状態の再検証（書く直前）: Issuer ／ Security の anchor と id、`JQUANTS_CODE` の結びつき、Issuer↔Security の関係、表示名、
上場、coverage、重複 ／ 再利用、衝突する既存の identity、退役した code、終わった上場。ID1 が plan を作った時の A1 の状態に頼らない。

書く先は凍結 A1 の `IdentityStore` だけ。書く順（A1 の不変条件が要る順）: 束ごとに IssuerRegistration → SecurityRegistration →
IdentifierAssignment → DisplayName（Issuer JA ・Security JA ・Issuer EN）→ ListingStart、最後に一括の Coverage。
前検査で決定論の衝突が 1 つでもあれば 0 書き込み。途中の失敗は `PARTIAL_FAILURE`（rollback ・削除 ・上書きは無い。再実行は A1 を読み直し
byte 一致の再利用で収束する）。

記録: `docs/databank/PHASE8_ID2_IDENTITY_REGISTRATION_EXECUTOR.md`。
"""
from __future__ import annotations

from typing import Any, Dict, List, Tuple

from .identity_bootstrap import BootstrapPlanError, plan_registration, propose_bootstrap
from .identity_bootstrap_model import (BootstrapBatch, BootstrapInputError, RegistrationPlan, ReviewedManifest,
                                       ReviewerClass)
from .identity_model import IdentifierScheme, IdentityHistory, IdentityHistoryError, RecordKind
from .identity_registration_model import (REGISTRATION_RULES_VERSION, BundleExecution, RecordWrite,
                                          RegistrationOutcome, RegistrationReason, RegistrationResult,
                                          RegistrationWrites, WriteState, ordered_registration_reasons)
from .identity_store import IdentityAuthorityMissing, IdentityStore, IdentityStoreCorrupt, IdentityStoreError

_STORE_ERRORS = (IdentityStoreError, OSError)
_HISTORY_REASON = {
    "REGISTRATION_CONFLICT": RegistrationReason.ISSUER_CONFLICT, "UNKNOWN_ISSUER": RegistrationReason.SECURITY_CONFLICT,
    "UNKNOWN_SECURITY": RegistrationReason.SECURITY_CONFLICT,
    "CONFLICTING_ASSIGNMENT": RegistrationReason.IDENTIFIER_CONFLICT,
    "CONTINUITY_NOT_AUTHORIZED": RegistrationReason.RETIRED_CODE_AMBIGUITY,
    "CONFLICTING_NAME": RegistrationReason.DISPLAY_NAME_CONFLICT,
    "OVERLAPPING_LISTING": RegistrationReason.LISTING_CONFLICT,
    "NON_MONOTONIC_KNOWN_AT": RegistrationReason.KNOWN_AT_NOT_MONOTONIC}


class _Abort(Exception):
    def __init__(self, reason: RegistrationReason, code: str = "") -> None:
        super().__init__(reason.value)
        self.reason = reason
        self.code = code


def _error_code(exc: BaseException) -> str:
    code = exc.__dict__.get("code", "") if not isinstance(exc, OSError) else "OS_ERROR"
    return code if isinstance(code, str) and code.isupper() else "STORE_ERROR"


def _rejected(reasons: Tuple[RegistrationReason, ...], code: str = "", manifest_digest: str = "",
              reviewed_digest: str = "", plan_digest: str = "") -> RegistrationResult:
    return RegistrationResult(outcome=RegistrationOutcome.REJECTED, reasons=ordered_registration_reasons(reasons),
                              manifest_digest=manifest_digest, reviewed_digest=reviewed_digest,
                              plan_digest=plan_digest, failure_code=code)


def _listing_ended(history: IdentityHistory, security_id: str) -> bool:
    return any(history.listings[rid].security_id == security_id for rid in history.listing_ends)


def _existing_id(history: IdentityHistory, record: Any) -> str:
    """A1 に既にある同じ identity の事実の record id（byte 一致でなくてもよい。出所は違ってよい）。無ければ ""。衝突は `_Abort`。"""
    if history.contains(record.record_id):
        return record.record_id
    kind = record.KIND
    if kind is RecordKind.ISSUER_REGISTRATION:
        existing = history.issuers.get(record.issuer_id)
        return existing.record_id if existing is not None else ""
    if kind is RecordKind.SECURITY_REGISTRATION:
        existing = history.securities.get(record.security_id)
        if existing is None:
            return ""
        if existing.issuer_id != record.issuer_id:
            raise _Abort(RegistrationReason.ISSUER_SECURITY_RELATION_CONFLICT, "SECURITY_LINKED_TO_OTHER_ISSUER")
        return existing.record_id
    if kind is RecordKind.IDENTIFIER_ASSIGNMENT:
        for rid, assignment in history.assignments.items():
            if assignment.scheme is not IdentifierScheme.JQUANTS_CODE or assignment.value != record.value:
                continue
            if rid in history.retirements:
                raise _Abort(RegistrationReason.RETIRED_CODE_AMBIGUITY, "CODE_PREVIOUSLY_RETIRED")
            if assignment.security_id != record.security_id:
                raise _Abort(RegistrationReason.CODE_BOUND_TO_OTHER_IDENTITY, "CODE_BOUND_TO_OTHER_SECURITY")
            return rid
        return ""
    if kind is RecordKind.DISPLAY_NAME:
        for existing in history.names:
            if (existing.subject_id, existing.name_kind, existing.language, existing.effective_from) != (
                    record.subject_id, record.name_kind, record.language, record.effective_from):
                continue
            if existing.value != record.value:
                raise _Abort(RegistrationReason.DISPLAY_NAME_CONFLICT, "OTHER_NAME_AT_SAME_EFFECTIVE_FROM")
            return existing.record_id
        return ""
    if kind is RecordKind.LISTING_START:
        if _listing_ended(history, record.security_id):
            raise _Abort(RegistrationReason.LISTING_ENDED, "LISTING_ENDED_IN_AUTHORITY")
        for existing in history.listings.values():
            if existing.security_id != record.security_id:
                continue
            if existing.effective_from != record.effective_from:
                raise _Abort(RegistrationReason.LISTING_CONFLICT, "OTHER_LISTING_START_FOR_SECURITY")
            return existing.record_id
        return ""
    for coverage in history.coverages:                                           # COVERAGE
        if coverage.scope is not record.scope:
            continue
        if (coverage.effective_from, coverage.effective_to) == (record.effective_from, record.effective_to):
            return coverage.record_id
        if coverage.effective_from < record.effective_to and record.effective_from < coverage.effective_to:
            raise _Abort(RegistrationReason.COVERAGE_CONFLICT, "OVERLAPPING_COVERAGE_WITH_OTHER_INTERVAL")
    return ""


def _preflight(history: IdentityHistory, records: Tuple[Any, ...]) -> Dict[str, str]:
    """全 record を A1 の現在の状態に照らす。planned record_id → 既存の record id（再利用）。新規は凍結の不変条件で検査。"""
    scratch = IdentityHistory(history.records)
    reuse: Dict[str, str] = {}
    for record in records:
        existing = _existing_id(history, record)
        if existing:
            reuse[record.record_id] = existing
            continue
        try:
            scratch.add(record)
        except IdentityHistoryError as exc:
            raise _Abort(_HISTORY_REASON.get(exc.code, RegistrationReason.AUTHORITY_RULE_VIOLATION), exc.code) from None
    return reuse


def _write(store: IdentityStore, record: Any, writes: List[str], reused: List[str]) -> WriteState:
    result = store.append(record)
    if result.status.value == "APPENDED":
        writes.append(result.record_id)
        return WriteState.APPENDED
    reused.append(result.record_id)
    return WriteState.REUSED


def execute_identity_registration(rows: Any, batch: Any, reviewed: Any, data_root: Any, *,
                                  prior_plan: Any = None) -> RegistrationResult:
    """人が承認した提案だけを、実行時の再導出 ・A1 の再検証の下で凍結 A1 の store に append する。"""
    if data_root is None or str(data_root).strip() == "":
        return _rejected((RegistrationReason.INVALID_INPUT,), "DATA_ROOT_REQUIRED")
    if not isinstance(batch, BootstrapBatch):
        return _rejected((RegistrationReason.INVALID_INPUT,), "INVALID_BATCH")
    if not isinstance(reviewed, ReviewedManifest) or reviewed.reviewer_class is not ReviewerClass.HUMAN:
        return _rejected((RegistrationReason.INVALID_INPUT,), "HUMAN_REVIEW_REQUIRED")
    if prior_plan is not None and not isinstance(prior_plan, RegistrationPlan):
        return _rejected((RegistrationReason.INVALID_INPUT,), "INVALID_PRIOR_PLAN")
    try:                                                                         # 1. 凍結 ID1 の再実行（機械の manifest）
        manifest = propose_bootstrap(rows, batch)
    except BootstrapInputError as exc:
        return _rejected((RegistrationReason.INVALID_INPUT,), exc.code)
    if reviewed.manifest_digest != manifest.manifest_digest:                     # 2. 人が審査した manifest と一致するか
        return _rejected((RegistrationReason.MANIFEST_DIGEST_MISMATCH,), "MANIFEST_DIGEST_MISMATCH",
                         manifest.manifest_digest, reviewed.reviewed_digest)
    for review in reviewed.reviews:                                              # 3. 審査の結びつき（提案 ・digest）
        proposal = manifest.proposal(review.proposal_id)
        if proposal is None or proposal.digest != review.proposal_digest:
            return _rejected((RegistrationReason.REVIEW_BINDING_INVALID,), "STALE_REVIEW", manifest.manifest_digest,
                             reviewed.reviewed_digest)
    try:                                                                         # 4. plan の再導出
        plan = plan_registration(manifest, reviewed)
    except BootstrapPlanError as exc:
        reason = RegistrationReason.REVIEW_BINDING_INVALID if exc.code in ("STALE_REVIEW", "REVIEW_TARGET_UNKNOWN") \
            else RegistrationReason.PLAN_REJECTED
        return _rejected((reason,), exc.code, manifest.manifest_digest, reviewed.reviewed_digest)
    digests = (manifest.manifest_digest, reviewed.reviewed_digest, plan.plan_digest)
    if prior_plan is not None and prior_plan.as_dict() != plan.as_dict():        # 5. 任意の cross-check
        return _rejected((RegistrationReason.PRIOR_PLAN_MISMATCH,), "PRIOR_PLAN_MISMATCH", *digests)
    if plan.entries == ():
        return RegistrationResult(outcome=RegistrationOutcome.NO_AUTHORIZED_ITEMS, reasons=(),
                                  manifest_digest=digests[0], reviewed_digest=digests[1], plan_digest=digests[2])
    try:                                                                         # 6. A1 の現在の状態（store の整合）
        store = IdentityStore.open(data_root)
    except IdentityAuthorityMissing as exc:
        return _rejected((RegistrationReason.STORE_MISSING,), _error_code(exc), *digests)
    except IdentityStoreCorrupt as exc:
        return _rejected((RegistrationReason.CORRUPT_STORE,), _error_code(exc), *digests)
    except _STORE_ERRORS as exc:
        return _rejected((RegistrationReason.PRECHECK_FAILED,), _error_code(exc), *digests)
    history = store.history
    try:                                                                         # 7. 全 record の再検証（0 書き込み）
        reuse = _preflight(history, plan.records)
        store.verify_unchanged()
    except _Abort as abort:
        return _rejected((abort.reason,), abort.code, *digests)
    except _STORE_ERRORS as exc:
        return _rejected((RegistrationReason.PRECHECK_FAILED,), _error_code(exc), *digests)
    appended: List[str] = []
    reused: List[str] = []
    bundles: List[BundleExecution] = []
    failure = ""
    for entry in plan.entries:                                                   # 8. 束ごとに A1 の順で append
        record_writes: List[RecordWrite] = []
        for record in entry.records:
            if failure:
                record_writes.append(RecordWrite(record_id=record.record_id, kind=record.KIND,
                                                 state=WriteState.NOT_ATTEMPTED))
                continue
            existing_id = reuse.get(record.record_id, "")
            if existing_id and existing_id != record.record_id:                  # 同じ identity の事実が別の出所で既にある
                reused.append(existing_id)
                record_writes.append(RecordWrite(record_id=existing_id, kind=record.KIND, state=WriteState.REUSED))
                continue
            try:
                state = _write(store, record, appended, reused)
                record_writes.append(RecordWrite(record_id=record.record_id, kind=record.KIND, state=state))
            except _STORE_ERRORS as exc:
                failure = _error_code(exc)
                record_writes.append(RecordWrite(record_id=record.record_id, kind=record.KIND,
                                                 state=WriteState.FAILED, failure_code=failure))
        bundles.append(BundleExecution(proposal_id=entry.proposal_id, code=entry.code, issuer_id=entry.issuer_id,
                                       security_id=entry.security_id, writes=tuple(record_writes)))
    coverage_writes: List[RecordWrite] = []
    for record in plan.coverage:                                                 # 9. 最後に一括の coverage
        if failure:
            coverage_writes.append(RecordWrite(record_id=record.record_id, kind=record.KIND,
                                               state=WriteState.NOT_ATTEMPTED))
            continue
        existing_id = reuse.get(record.record_id, record.record_id)
        if existing_id != record.record_id:
            reused.append(existing_id)
            coverage_writes.append(RecordWrite(record_id=existing_id, kind=record.KIND, state=WriteState.REUSED))
            continue
        try:
            state = _write(store, record, appended, reused)
            coverage_writes.append(RecordWrite(record_id=record.record_id, kind=record.KIND, state=state))
        except _STORE_ERRORS as exc:
            failure = _error_code(exc)
            coverage_writes.append(RecordWrite(record_id=record.record_id, kind=record.KIND, state=WriteState.FAILED,
                                               failure_code=failure))
    writes = RegistrationWrites(appended=tuple(appended), reused=tuple(reused))
    if failure:
        if appended:
            reasons = ordered_registration_reasons((RegistrationReason.STORE_WRITE_FAILED,
                                                    RegistrationReason.PARTIAL_WRITE))
            return RegistrationResult(outcome=RegistrationOutcome.PARTIAL_FAILURE, reasons=reasons,
                                      bundles=tuple(bundles), coverage=tuple(coverage_writes), writes=writes,
                                      manifest_digest=digests[0], reviewed_digest=digests[1],
                                      plan_digest=digests[2], failure_code=failure)
        return RegistrationResult(outcome=RegistrationOutcome.REJECTED,
                                  reasons=(RegistrationReason.STORE_WRITE_FAILED,), bundles=tuple(bundles),
                                  coverage=tuple(coverage_writes), writes=writes,
                                  manifest_digest=digests[0], reviewed_digest=digests[1], plan_digest=digests[2],
                                  failure_code=failure)
    outcome = RegistrationOutcome.APPENDED if appended else RegistrationOutcome.REUSED
    return RegistrationResult(outcome=outcome, reasons=(), bundles=tuple(bundles), coverage=tuple(coverage_writes),
                              writes=writes, manifest_digest=digests[0], reviewed_digest=digests[1],
                              plan_digest=digests[2])


__all__ = ["REGISTRATION_RULES_VERSION", "execute_identity_registration"]
