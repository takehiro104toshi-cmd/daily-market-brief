"""P8-EXE — 合成の provider の行から Phase 8 の authority への、最初の安全な実行の境界（safe append executor）。

信頼の境界（監督の決定 D5 ・EXE §2）:
- 入力は **元の行**（`FinancialSummaryRow` ／ Mapping）＋ caller の文脈（`AdapterContext`）＋ 明示の private な `data_root` だけ。
- 実行のたびに凍結の ADP0（`adapt_financial_summary_row`）を**再実行**し、append する record を自分で組み立て直す。caller が渡す
  `AdapterResult` ・`AppendPlan` ・注記 ・正準の観測 ・provider の identity ・`supersedes` ・指標を authority として信用しない
  （API にそれらを受ける引数は無い。`prior_adapter_result` は任意の cross-check で、再導出と一致しなければ REJECTED ・書かない）。

書く先は 3 つだけ: 凍結の A2 `ObservationStore`、ST1 `SemanticMetadataStore`、ST1 `HeldObservationStore`。identity ・指標 ・Theme ・
Narrative ・Production DNA ・Pages ・legacy ・raw の応答 ・adapter の結果の journal には書かない。executor の journal も無い。

順序（EXE §7）: A. 行の**全欄**を前検査（1 つでも決定論の失敗があれば 0 書き込み）→ 欄ごとに B. 写しの provenance → 注記 →
C. A2 の観測 → D. 結果。journal をまたぐ transaction は無いので、1 つの authority に書いた後の失敗は `PARTIAL_FAILURE`
（rollback ・削除 ・上書きは無い。後の再実行は byte 一致の再利用で収束する）。孤児の注記は `SEMANTIC_METADATA_RECORD` のままで、
参照する A2 の観測が存在するときだけ意味を持つ。

revision（EXE §10）: 凍結の A2 の履歴から slot の鎖の末尾を再導出し、`supersedes` を自分で決める。同じ provider の revision（参照 ＝
digest）は再利用、内容の違う訂正は新しい不変の revision。P8-EXE-R: 同じ自然 key で digest だけが違う provider 側の変更は、知識を
取得の時刻（`AdapterContext.acquired_at`。無ければ `REJECTED / PROVIDER_REVISION_ACQUISITION_TIME_REQUIRED`）にして append し、
過去の STRICT な PIT の答えを書き換えない。会計基準の違いは鎖に入れない（P8-OBS-57。A2R の `plan_append` が
HOLD → 保留）。時計 ・乱数 ・UUID ・network ・LLM ・float は無い。

記録: `docs/databank/PHASE8_EXE_SAFE_APPEND_EXECUTOR.md`。
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, List, Optional, Tuple

from .held_observation_model import HeldObservation, HeldObservationModelError, HeldReason
from .held_observation_store import HeldObservationStore, HeldStoreCorrupt, HeldStoreError, HeldStoreMissing
from .identity_model import SourceClass
from .jquants_adapter_model import (AdapterContext, AdapterInputError, AdapterResult, AdapterStatus,
                                    FinancialSummaryRow, ProviderRecordIdentity)
from .jquants_execution_model import (EXECUTION_RULES_VERSION, AuthorityWrites, ExecutionOutcome, ExecutionReason,
                                      ExecutionResult, FieldDisposition, FieldExecution, WriteState,
                                      ordered_execution_reasons)
from .jquants_financial_summary_adapter import adapt_financial_summary_row
from .observation_model import (FundamentalActual, KnowledgeTime, ObservationHistoryError, ObservationModelError,
                                ValueState)
from .observation_semantics_gate import AppendEligibility, plan_append
from .observation_semantics_mapping import DOCTYPE_MAPPING_VERSION, derive_observation_semantics
from .observation_semantics_model import FieldFamily, ObservationSemantics, SchemaFamily, SemanticMappingProvenance
from .observation_store import (ObservationAuthorityMissing, ObservationStore, ObservationStoreCorrupt,
                                ObservationStoreError)
from .semantic_metadata_store import (SemanticMetadataCorrupt, SemanticMetadataJournalError, SemanticMetadataMissing,
                                      SemanticMetadataStore, SemanticMetadataStoreError)

_STORE_ERRORS = (ObservationStoreError, SemanticMetadataStoreError, HeldStoreError, OSError)


class _Abort(Exception):
    """書く前に決まった拒否（理由 ・code だけ。provider の値は持たない）。"""

    def __init__(self, reason: ExecutionReason, code: str = "") -> None:
        super().__init__(reason.value)
        self.reason = reason
        self.code = code


@dataclass(frozen=True)
class _Stores:
    observations: ObservationStore
    semantics: SemanticMetadataStore
    held: HeldObservationStore


@dataclass(frozen=True)
class _FieldPlan:
    """前検査を通った 1 欄の計画（append か再利用か記載なし）。"""

    provider_field: str
    observation: Optional[FundamentalActual]
    semantics: Optional[ObservationSemantics]
    provenance: Optional[SemanticMappingProvenance]

    @property
    def field(self):
        return self.observation.field


def _error_code(exc: BaseException) -> str:
    code = exc.__dict__.get("code", "") if not isinstance(exc, OSError) else "OS_ERROR"
    return code if isinstance(code, str) and code.isupper() else "STORE_ERROR"


def _open_stores(data_root: Any) -> _Stores:
    try:
        observations = ObservationStore.open(data_root)
        semantics = SemanticMetadataStore.open(data_root)
        held = HeldObservationStore.open(data_root)
    except (ObservationAuthorityMissing, SemanticMetadataMissing, HeldStoreMissing) as exc:
        raise _Abort(ExecutionReason.STORE_MISSING, _error_code(exc)) from None
    except (ObservationStoreCorrupt, SemanticMetadataCorrupt, HeldStoreCorrupt) as exc:
        raise _Abort(ExecutionReason.CORRUPT_STORE, _error_code(exc)) from None
    except _STORE_ERRORS as exc:
        raise _Abort(ExecutionReason.PRECHECK_FAILED, _error_code(exc)) from None
    return _Stores(observations, semantics, held)


def _held_record(fresh: AdapterResult, context: AdapterContext, reasons: Tuple[HeldReason, ...],
                 basis: Any) -> HeldObservation:
    """executor が見つけた保留（identity ・鎖の意味）の ST1 record。ADP0 の HOLD はその record をそのまま使う。"""
    identity = fresh.provider_record
    reference = identity.reference() or f"jq.fins_summary:unreferenceable:{identity.digest[:24]}"
    return HeldObservation(provider=SourceClass.JQUANTS, schema_family=SchemaFamily.JQUANTS_V2_FINS_SUMMARY,
                           provider_record_ref=reference, provider_record_digest=identity.digest, reasons=reasons,
                           mapping_rule_version=DOCTYPE_MAPPING_VERSION, rules_version=EXECUTION_RULES_VERSION,
                           issuer_id=context.issuer_id, attempted_statement_basis=basis,
                           observed_at=context.acquired_at)


def _hold(stores: _Stores, fresh: AdapterResult, held: HeldObservation, reason: ExecutionReason) -> ExecutionResult:
    """保留の store にだけ書く（A2 ・注記には書かない）。同じ record は再利用。"""
    try:
        appended = stores.held.append(held)
    except _STORE_ERRORS as exc:
        return _rejected(fresh.provider_record, (ExecutionReason.STORE_WRITE_FAILED,), _error_code(exc))
    reused = appended.status.value != "APPENDED"
    writes = AuthorityWrites(held_reused=held.record_id) if reused else AuthorityWrites(held_appended=held.record_id)
    return ExecutionResult(outcome=ExecutionOutcome.HELD, reasons=ordered_execution_reasons((reason,)),
                           provider_record=fresh.provider_record, issuer_id=held.issuer_id, writes=writes,
                           held_reasons=held.reasons, held_record_id=held.record_id,
                           mapping_rule_version=DOCTYPE_MAPPING_VERSION)


def _rejected(provider_record: Optional[ProviderRecordIdentity], reasons: Tuple[ExecutionReason, ...],
              code: str = "", issuer_id: str = "") -> ExecutionResult:
    return ExecutionResult(outcome=ExecutionOutcome.REJECTED, reasons=ordered_execution_reasons(reasons),
                           provider_record=provider_record, issuer_id=issuer_id, failure_code=code,
                           mapping_rule_version=DOCTYPE_MAPPING_VERSION)


def _natural_key_ref(reference: str) -> str:
    """provider の参照 `jq.fins_summary:<Code>.<DiscNo>.<DocType>:<digest24>` から digest を除いた自然 key の部分。"""
    head, separator, _ = reference.rpartition(":")
    return head if separator and not head.endswith("unreferenceable") else ""


def _plan_field(stores: _Stores, provider_field: str, root: FundamentalActual, doc_type: str,
                acquired_at: Any = None) -> _FieldPlan:
    """1 欄の計画。凍結の A2 の履歴から鎖の末尾を再導出し、provider の参照で replay を見つけ、前検査する。

    P8-EXE-R: 同じ provider の自然 key（Code ・DiscDate ・DiscTime ・DiscNo ・DocType）で内容（digest）だけが違う行は provider 側の
    変更であり、その安全な知識の境界は **取得の時刻 `acquired_at`**（世界の開示時刻ではない。無ければ fail closed）。初見の行 ・
    新しい DiscNo の訂正は従来どおり TDnet の開示日時を知識にする。
    """
    if root.value.state is ValueState.NOT_REPORTED:
        return _FieldPlan(provider_field, root, None, None)
    chain = stores.observations.history.chains.get(root.slot_key, [])
    reference = root.provenance.source_record_ref
    same_revision = [record for record in chain if record.provenance.source_record_ref == reference]
    if same_revision:                                                            # 同じ provider の revision → 再利用
        existing = same_revision[-1]                                             # 参照は digest を含む → 内容 ・開示日時は同じ
        if (existing.value, existing.provenance) != (root.value, root.provenance):   # 知識は EXE-R で取得の時刻になり得る
            raise _Abort(ExecutionReason.OBSERVATION_CONFLICT, "PROVIDER_REVISION_CONTENT_DIFFERS")
        semantics, provenance = derive_observation_semantics(existing.record_id, doc_type,
                                                             FieldFamily.UNPREFIXED_ACTUAL)
        stored = stores.semantics.semantics_for(existing.record_id)
        stored_provenance = stores.semantics.provenance_for(existing.record_id)
        if stored is not None and stored.record_id != semantics.record_id:
            raise _Abort(ExecutionReason.SEMANTIC_CONFLICT, "SEMANTICS_CONFLICT")
        if stored_provenance is not None and stored_provenance.record_id != provenance.record_id:
            raise _Abort(ExecutionReason.SEMANTIC_CONFLICT, "PROVENANCE_CONFLICT")
        return _FieldPlan(provider_field, existing, semantics, provenance)      # append は byte 一致で収束する
    head = chain[-1] if chain else None
    natural_key = _natural_key_ref(reference)
    modified = [record for record in chain                                       # 同じ自然 key ・違う digest（provider 側の変更）
                if natural_key and _natural_key_ref(record.provenance.source_record_ref) == natural_key
                and record.knowledge == root.knowledge]
    knowledge = root.knowledge
    if modified:
        if acquired_at is None:                                                  # 取得の時刻が無ければ開示時刻に落とさない
            raise _Abort(ExecutionReason.PRECHECK_FAILED, "PROVIDER_REVISION_ACQUISITION_TIME_REQUIRED")
        knowledge = KnowledgeTime.exact(acquired_at)                             # 保守的な system の知識の境界
    try:
        record = FundamentalActual(subject=root.subject, field=root.field, statement_basis=root.statement_basis,
                                   period=root.period, value=root.value, knowledge=knowledge,
                                   provenance=root.provenance, supersedes=head.record_id if head else "")
    except ObservationModelError as exc:
        raise _Abort(ExecutionReason.PRECHECK_FAILED, exc.code) from None
    semantics, provenance = derive_observation_semantics(record.record_id, doc_type, FieldFamily.UNPREFIXED_ACTUAL)
    head_semantics = stores.semantics.semantics_for(head.record_id) if head else None
    if head is not None and head_semantics is None:
        raise _Abort(ExecutionReason.PRECHECK_FAILED, "CHAIN_HEAD_SEMANTICS_MISSING")
    plan = plan_append(record, semantics, head, head_semantics)
    if plan.eligibility is not AppendEligibility.ELIGIBLE:                       # 例: 会計基準 ・区分の不連続（OBS-57）
        raise _Abort(ExecutionReason.SEMANTIC_CHAIN_HOLD, plan.reasons[0].value)
    try:
        stores.observations.history.check(record)
    except ObservationHistoryError as exc:
        raise _Abort(ExecutionReason.OBSERVATION_CONFLICT, exc.code) from None
    stored = stores.semantics.semantics_for(record.record_id)
    if stored is not None and stored.record_id != semantics.record_id:
        raise _Abort(ExecutionReason.SEMANTIC_CONFLICT, "SEMANTICS_CONFLICT")
    try:
        stores.semantics.journal.check(provenance)
    except SemanticMetadataJournalError as exc:
        raise _Abort(ExecutionReason.SEMANTIC_CONFLICT, exc.code) from None
    return _FieldPlan(provider_field, record, semantics, provenance)


def _not_reported(plan: _FieldPlan) -> FieldExecution:
    return FieldExecution(provider_field=plan.provider_field, field=plan.field,
                          disposition=FieldDisposition.NOT_REPORTED, provenance_write=WriteState.NOT_REQUIRED,
                          semantics_write=WriteState.NOT_REQUIRED, observation_write=WriteState.NOT_REQUIRED)


def _not_attempted(plan: _FieldPlan) -> FieldExecution:
    return FieldExecution(provider_field=plan.provider_field, field=plan.field,
                          disposition=FieldDisposition.NOT_ATTEMPTED)


class _Writer:
    """欄ごとに provenance → 注記 → 観測の順に書く。書いた id を authority ごとに記録する。"""

    def __init__(self, stores: _Stores) -> None:
        self.stores = stores
        self.semantic_appended: List[str] = []
        self.semantic_reused: List[str] = []
        self.observations_appended: List[str] = []
        self.observations_reused: List[str] = []

    def _semantic(self, record: Any) -> WriteState:
        result = self.stores.semantics.append(record)
        if result.status.value == "APPENDED":
            self.semantic_appended.append(result.record_id)
            return WriteState.APPENDED
        self.semantic_reused.append(result.record_id)
        return WriteState.REUSED

    def _observation(self, record: FundamentalActual) -> WriteState:
        result = self.stores.observations.append(record)
        if result.status.value == "APPENDED":
            self.observations_appended.append(result.record_id)
            return WriteState.APPENDED
        self.observations_reused.append(result.record_id)
        return WriteState.REUSED

    def execute_field(self, plan: _FieldPlan) -> FieldExecution:
        states = {"provenance_write": WriteState.NOT_ATTEMPTED, "semantics_write": WriteState.NOT_ATTEMPTED,
                  "observation_write": WriteState.NOT_ATTEMPTED}
        ids = {"observation_id": plan.observation.record_id, "supersedes": plan.observation.supersedes,
               "provenance_id": plan.provenance.record_id, "semantics_id": plan.semantics.record_id}
        try:
            states["provenance_write"] = self._semantic(plan.provenance)
            states["semantics_write"] = self._semantic(plan.semantics)
            states["observation_write"] = self._observation(plan.observation)
        except _STORE_ERRORS as exc:
            failed = next(name for name, state in states.items() if state is WriteState.NOT_ATTEMPTED)
            states[failed] = WriteState.FAILED
            return FieldExecution(provider_field=plan.provider_field, field=plan.field,
                                  disposition=FieldDisposition.FAILED, failure_code=_error_code(exc), **ids, **states)
        appended = WriteState.APPENDED in states.values()
        return FieldExecution(provider_field=plan.provider_field, field=plan.field,
                              disposition=FieldDisposition.APPENDED if appended else FieldDisposition.REUSED,
                              **ids, **states)

    def writes(self) -> AuthorityWrites:
        return AuthorityWrites(semantic_metadata_appended=tuple(self.semantic_appended),
                               semantic_metadata_reused=tuple(self.semantic_reused),
                               observations_appended=tuple(self.observations_appended),
                               observations_reused=tuple(self.observations_reused))


def _execute_eligible(stores: _Stores, fresh: AdapterResult, context: AdapterContext,
                      doc_type: str) -> ExecutionResult:
    material = fresh.eligible
    if material.issuer_id not in stores.observations.history.identity.issuers:   # 凍結の A1 の下で解決しない
        held = _held_record(fresh, context, (HeldReason.IDENTITY_UNRESOLVED,), material.observations[0].statement_basis)
        return _hold(stores, fresh, held, ExecutionReason.IDENTITY_UNRESOLVED)
    try:                                                                         # A. 全欄の前検査（0 書き込み）
        plans = tuple(_plan_field(stores, observation.provenance.source_field, observation, doc_type,
                                  context.acquired_at)
                      for observation in material.observations)
        for store in (stores.observations, stores.semantics, stores.held):
            store.verify_unchanged()
    except _Abort as abort:
        if abort.reason is ExecutionReason.SEMANTIC_CHAIN_HOLD:
            held = _held_record(fresh, context, (HeldReason.SEMANTIC_CHAIN_CONFLICT,),
                                material.observations[0].statement_basis)
            return _hold(stores, fresh, held, abort.reason)
        return _rejected(fresh.provider_record, (abort.reason,), abort.code, material.issuer_id)
    except _STORE_ERRORS as exc:
        return _rejected(fresh.provider_record, (ExecutionReason.PRECHECK_FAILED,), _error_code(exc),
                         material.issuer_id)
    except HeldObservationModelError as exc:
        return _rejected(fresh.provider_record, (ExecutionReason.PRECHECK_FAILED,), exc.code, material.issuer_id)
    writer = _Writer(stores)
    executed: List[FieldExecution] = []
    failed = False
    for plan in plans:                                                           # B ・C. 欄ごとに注記 → 観測
        if plan.semantics is None:
            executed.append(_not_reported(plan))
        elif failed:
            executed.append(_not_attempted(plan))
        else:
            outcome = writer.execute_field(plan)
            failed = outcome.disposition is FieldDisposition.FAILED
            executed.append(outcome)
    writes = writer.writes()
    fields = tuple(executed)
    dispositions = {f.disposition for f in fields}
    if failed:
        code = next(f.failure_code for f in fields if f.disposition is FieldDisposition.FAILED)
        if writes.any_appended:
            reasons = (ExecutionReason.PARTIAL_WRITE, ExecutionReason.STORE_WRITE_FAILED)
            return ExecutionResult(outcome=ExecutionOutcome.PARTIAL_FAILURE, reasons=ordered_execution_reasons(reasons),
                                   provider_record=fresh.provider_record, issuer_id=material.issuer_id,
                                   fields=fields, writes=writes, failure_code=code,
                                   mapping_rule_version=DOCTYPE_MAPPING_VERSION)
        return ExecutionResult(outcome=ExecutionOutcome.REJECTED, reasons=(ExecutionReason.STORE_WRITE_FAILED,),
                               provider_record=fresh.provider_record, issuer_id=material.issuer_id, fields=fields,
                               writes=writes, failure_code=code, mapping_rule_version=DOCTYPE_MAPPING_VERSION)
    if dispositions == {FieldDisposition.NOT_REPORTED}:
        outcome = ExecutionOutcome.NO_REPORTED_FIELDS
    elif writes.any_appended:
        outcome = ExecutionOutcome.APPENDED
    else:
        outcome = ExecutionOutcome.REUSED
    return ExecutionResult(outcome=outcome, reasons=(), provider_record=fresh.provider_record,
                           issuer_id=material.issuer_id, fields=fields, writes=writes,
                           mapping_rule_version=DOCTYPE_MAPPING_VERSION)


def execute_financial_summary_row(row: Any, context: Any, data_root: Any, *,
                                  prior_adapter_result: Any = None) -> ExecutionResult:
    """行 1 つを、実行時に再導出した適格の下でだけ authority へ append する。書く先は A2 ・注記 ・保留の 3 store だけ。"""
    if data_root is None or str(data_root).strip() == "":
        return _rejected(None, (ExecutionReason.INVALID_INPUT,), "DATA_ROOT_REQUIRED")
    if not isinstance(context, AdapterContext):
        return _rejected(None, (ExecutionReason.INVALID_INPUT,), "INVALID_CONTEXT")
    if prior_adapter_result is not None and not isinstance(prior_adapter_result, AdapterResult):
        return _rejected(None, (ExecutionReason.INVALID_INPUT,), "INVALID_PRIOR_RESULT")
    try:
        parsed = row if isinstance(row, FinancialSummaryRow) else FinancialSummaryRow.from_provider_mapping(row)
        fresh = adapt_financial_summary_row(parsed, context)                     # 実行時の再導出（唯一の真）
    except AdapterInputError as exc:
        return _rejected(None, (ExecutionReason.INVALID_INPUT,), exc.code)
    if prior_adapter_result is not None and prior_adapter_result.as_dict() != fresh.as_dict():
        return _rejected(fresh.provider_record, (ExecutionReason.PRIOR_RESULT_MISMATCH,), "PRIOR_RESULT_MISMATCH")
    try:
        stores = _open_stores(data_root)
    except _Abort as abort:
        return _rejected(fresh.provider_record, (abort.reason,), abort.code)
    if fresh.status is AdapterStatus.HOLD:
        return _hold(stores, fresh, fresh.held, ExecutionReason.ADAPTER_HELD)
    return _execute_eligible(stores, fresh, context, parsed.DocType)


__all__ = ["execute_financial_summary_row"]
