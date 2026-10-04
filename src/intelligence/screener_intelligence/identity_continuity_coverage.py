"""P8-OBS60-I1 — identity の継続 coverage の authority（監督承認の model I3: 明示の継続 authority）。

取得に成功した master snapshot の日 T について、**既存の人が審査した identity authority（凍結 A1）が新しい snapshot と決定論で
整合すると確かめられたときだけ**、凍結 A1 の `Coverage(JP_LISTED_EQUITY_IDENTITY, [T 00:00 JST, T＋1 日))` を 1 つ append する。

守る意味:
- OBSERVED_AT_T ≠ VALID_FOREVER ・ NO_CONTRARY_RECORD ≠ CONTINUITY ・ SYSTEM_KNOWN_AT ≠ WORLD_VALID_AT。
- 確かめた日だけが coverage。確かめていない日は gap のまま（橋を架けない ・前の coverage から推定しない ・遡って埋めない）。
- 入力は凍結 A1 の履歴 ・凍結 LIVE1 と同じ bounded な master の行 ・凍結 ACQ0 の取得 event（store に在り `COMPLETE` ・master ・
  日が T ・内容の digest が行と一致）・凍結 ID1 の分類だけ。第 2 の identity 分類器を作らない。
- 「関係する登録済み identity」の範囲（§6 の監査の結論）: 凍結 A1 で **有効な（退役していない）`JQUANTS_CODE` の割り当てを持ち、
  上場が終わっていない** Security とその Issuer。これらすべてが凍結 ID1 で `REUSE` に分類されることが条件。退役した code ・終わった
  上場の identity は居なくてよいが、snapshot に現れれば凍結 ID1 が人の審査にする（再上場の疑い）。snapshot にあって A1 に無い code
  （市場の他の銘柄）は範囲の外で、coverage を妨げない（A1 はそれらを `NOT_FOUND` と答える。既存の D0 の coverage と同じ意味）。
  ただし登録済み identity に関わる新しい code（同じ先頭 4 桁 ・anchor が登録済みで code が結ばれていない等）は凍結 ID1 が
  人の審査にし、coverage を妨げる。
- 書くのは A1 の `Coverage` だけ。登録 ・識別子 ・名前 ・上場 ・退役 ・訂正 ・A2 の record は書かず、既存の record を変えない。
- `known_at` ＝ 取得 event の `acquired_at`（遡らせない）。人の審査が D0 の後でも、取得の時点で identity が知られていれば動く。

記録: `docs/databank/PHASE8_OBS60_I1_IDENTITY_CONTINUITY_COVERAGE.md`。
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from enum import Enum
from typing import Any, Dict, List, Mapping, Optional, Tuple

from .acquisition_event_model import AcquisitionModelError, AcquisitionStatus, bounded_content_digest, \
    is_acquisition_reference
from .acquisition_event_store import AcquisitionEventStore, AcquisitionStoreError
from .identity_bootstrap import propose_bootstrap
from .identity_bootstrap_model import BootstrapBatch, BootstrapInputError, ProposalDisposition, day_start_jst
from .identity_model import (Coverage, CoverageScope, IdentifierScheme, IdentityHistory, IdentityModelError,
                             SourceClass, SourceProvenance)
from .identity_store import IdentityAppendRejected, IdentityStore, IdentityStoreError
from .jquants_adapter_model import DERIVED_NON_AUTHORITY_NON_PERSISTENT
from .jquants_live_model import MASTER_PATH, LiveInputError, MasterEligibility
from .jquants_master_ingress import assess_master_row

CONTINUITY_RULES_VERSION = "p8_identity_continuity_coverage:0.1.0"
#: 継続の条件（監督の既定）: 関係する登録済み identity のすべてが凍結 ID1 で REUSE
CONTINUITY_CONDITION = "ALL_RELEVANT_REGISTERED_IDENTITIES_REUSE"


class ContinuityError(ValueError):
    """入力の契約の違反（fail closed）。detail は field 名だけ。"""

    def __init__(self, code: str, detail: str = "") -> None:
        super().__init__(f"{code}: {detail}" if detail else code)
        self.code = code
        self.detail = detail


def _require(condition: bool, code: str, detail: str = "") -> None:
    if not condition:
        raise ContinuityError(code, detail)


class ContinuityOutcome(str, Enum):
    APPENDED = "APPENDED"
    REUSED = "REUSED"
    REVIEW_REQUIRED = "REVIEW_REQUIRED"
    ACQUISITION_NOT_COMPLETE = "ACQUISITION_NOT_COMPLETE"
    ACQUISITION_MISMATCH = "ACQUISITION_MISMATCH"
    IDENTITY_SCOPE_UNRESOLVED = "IDENTITY_SCOPE_UNRESOLVED"
    COVERAGE_CONFLICT = "COVERAGE_CONFLICT"
    STORE_FAILURE = "STORE_FAILURE"


class ContinuityReason(str, Enum):
    EVENT_NOT_FOUND = "EVENT_NOT_FOUND"
    EVENT_PROVIDER_MISMATCH = "EVENT_PROVIDER_MISMATCH"
    EVENT_ENDPOINT_MISMATCH = "EVENT_ENDPOINT_MISMATCH"
    EVENT_DATE_MISMATCH = "EVENT_DATE_MISMATCH"
    ROWS_NOT_BOUNDED = "ROWS_NOT_BOUNDED"
    CONTENT_DIGEST_MISMATCH = "CONTENT_DIGEST_MISMATCH"
    ACQUISITION_EMPTY = "ACQUISITION_EMPTY"
    ACQUISITION_PARTIAL_PAGINATED = "ACQUISITION_PARTIAL_PAGINATED"
    ACQUISITION_FAILED = "ACQUISITION_FAILED"
    NO_ACTIVE_REGISTERED_IDENTITY = "NO_ACTIVE_REGISTERED_IDENTITY"
    CODE_MULTIPLY_BOUND = "CODE_MULTIPLY_BOUND"
    ANCHOR_NOT_BOOTSTRAP = "ANCHOR_NOT_BOOTSTRAP"
    IDENTITY_NOT_KNOWN_BY_ACQUISITION = "IDENTITY_NOT_KNOWN_BY_ACQUISITION"
    AUTHORITY_KNOWN_AFTER_ACQUISITION = "AUTHORITY_KNOWN_AFTER_ACQUISITION"
    CLASSIFICATION_FAILED = "CLASSIFICATION_FAILED"
    CLASSIFICATION_INCOMPLETE = "CLASSIFICATION_INCOMPLETE"
    IDENTITY_CHANGE_SUSPECTED = "IDENTITY_CHANGE_SUSPECTED"
    EXISTING_COVERAGE_DIFFERENT_PROVENANCE = "EXISTING_COVERAGE_DIFFERENT_PROVENANCE"
    STORE_ERROR = "STORE_ERROR"


class ReviewOrigin(str, Enum):
    LIVE1_ELIGIBILITY = "LIVE1_ELIGIBILITY"
    ID1_CLASSIFICATION = "ID1_CLASSIFICATION"


@dataclass(frozen=True, kw_only=True)
class ContinuityReviewItem:
    """人の審査に回す 1 件（凍結 LIVE1 ／ ID1 の型つきの理由をそのまま運ぶ。名前 ・値は持たない）。"""

    code: str
    origin: ReviewOrigin
    disposition: str
    reasons: Tuple[str, ...]
    existing_issuer_id: str = ""
    existing_security_id: str = ""

    def as_dict(self) -> Dict[str, Any]:
        return {"code": self.code, "disposition": self.disposition, "existing_issuer_id": self.existing_issuer_id,
                "existing_security_id": self.existing_security_id, "origin": self.origin.value,
                "reasons": list(self.reasons)}


@dataclass(frozen=True, kw_only=True)
class ContinuityResult:
    """決定論の結果（record ではない。保存しない）。"""

    outcome: ContinuityOutcome
    day: date
    event_reference: str
    reasons: Tuple[ContinuityReason, ...] = ()
    review: Tuple[ContinuityReviewItem, ...] = ()
    coverage_record_id: str = ""
    active_codes: int = 0
    unregistered_codes: int = 0
    failure_code: str = ""
    condition: str = CONTINUITY_CONDITION
    rules_version: str = CONTINUITY_RULES_VERSION
    authority_class: str = DERIVED_NON_AUTHORITY_NON_PERSISTENT

    def as_dict(self) -> Dict[str, Any]:
        return {"active_codes": self.active_codes, "authority_class": self.authority_class,
                "condition": self.condition, "coverage_record_id": self.coverage_record_id,
                "day": self.day.isoformat(), "event_reference": self.event_reference,
                "failure_code": self.failure_code, "outcome": self.outcome.value,
                "reasons": [r.value for r in self.reasons], "review": [item.as_dict() for item in self.review],
                "rules_version": self.rules_version, "unregistered_codes": self.unregistered_codes}


@dataclass(frozen=True)
class _ActiveCode:
    code: str
    security_id: str
    issuer_id: str
    batch_id: str


def _listing_ended(history: IdentityHistory, security_id: str) -> bool:
    return any(history.listings[rid].security_id == security_id for rid in history.listing_ends)


def _batch_of(anchor: str, kind: str, code: str) -> Optional[str]:
    """`<batch>:<kind>.<code>` の anchor から batch id を取り出す（形が違えば None）。"""
    suffix = f":{kind}.{code}"
    if not anchor.endswith(suffix) or len(anchor) <= len(suffix):
        return None
    return anchor[:-len(suffix)]


def coverage_for_day(day: date, event_reference: str, acquired_at: Any) -> Coverage:
    """T の 1 日の A1 `Coverage`（凍結の表現そのまま。provenance は取得 event の参照と `acquired_at`）。"""
    return Coverage(scope=CoverageScope.JP_LISTED_EQUITY_IDENTITY, effective_from=day_start_jst(day),
                    effective_to=day_start_jst(day + timedelta(days=1)),
                    provenance=SourceProvenance(source_class=SourceClass.JQUANTS, source_record_ref=event_reference,
                                                known_at=acquired_at))


def relevant_scope(history: IdentityHistory) -> Tuple[Tuple[_ActiveCode, ...], Tuple[_ActiveCode, ...],
                                                       Tuple[str, ...], Tuple[ContinuityReason, ...]]:
    """(有効な登録済み code, 退役 ／ 上場の終わった code, A1 が結んだことのあるすべての code, 範囲が決まらない理由)。

    凍結 A1 だけから決定論で導く。有効 ＝ 退役していない `JQUANTS_CODE` の割り当てで、上場が終わっていない Security。
    """
    active: Dict[str, List[_ActiveCode]] = {}
    inactive: List[_ActiveCode] = []
    known_codes: List[str] = []
    reasons: List[ContinuityReason] = []
    for record_id, assignment in history.assignments.items():
        if assignment.scheme is not IdentifierScheme.JQUANTS_CODE:
            continue
        if assignment.value not in known_codes:
            known_codes.append(assignment.value)
        security = history.securities.get(assignment.security_id)
        issuer = history.issuers.get(security.issuer_id) if security is not None else None
        batch_id = _batch_of(security.registration_anchor, "sec", assignment.value) if security is not None else None
        issuer_batch = _batch_of(issuer.registration_anchor, "iss", assignment.value) if issuer is not None else None
        is_active = record_id not in history.retirements and not _listing_ended(history, assignment.security_id)
        if batch_id is None or issuer_batch != batch_id:
            if is_active:
                reasons.append(ContinuityReason.ANCHOR_NOT_BOOTSTRAP)
            else:
                inactive.append(_ActiveCode(code=assignment.value, security_id=assignment.security_id,
                                            issuer_id=security.issuer_id if security else "", batch_id=""))
            continue
        entry = _ActiveCode(code=assignment.value, security_id=assignment.security_id, issuer_id=security.issuer_id,
                            batch_id=batch_id)
        if not is_active:
            inactive.append(entry)
            continue
        if assignment.value not in active:
            active[assignment.value] = []
        bound = active[assignment.value]
        bound.append(entry)
    for code in sorted(active):
        if len(active[code]) > 1:
            reasons.append(ContinuityReason.CODE_MULTIPLY_BOUND)
    ordered = tuple(active[code][0] for code in sorted(active) if len(active[code]) == 1)
    unique = []
    for reason in reasons:
        if reason not in unique:
            unique.append(reason)
    return ordered, tuple(inactive), tuple(sorted(known_codes)), tuple(unique)


def _event_checks(event: Any, day: date, rows: Any) -> Tuple[Optional[ContinuityOutcome],
                                                               Tuple[ContinuityReason, ...]]:
    reasons: List[ContinuityReason] = []
    if event.provider is not SourceClass.JQUANTS:
        reasons.append(ContinuityReason.EVENT_PROVIDER_MISMATCH)
    if event.scope.endpoint != MASTER_PATH:
        reasons.append(ContinuityReason.EVENT_ENDPOINT_MISMATCH)
    elif event.scope.params != (("date", day.isoformat()),):
        reasons.append(ContinuityReason.EVENT_DATE_MISMATCH)
    try:
        content = bounded_content_digest(MASTER_PATH, rows)
    except AcquisitionModelError:
        reasons.append(ContinuityReason.ROWS_NOT_BOUNDED)
    else:
        if content.digest != event.content_digest or content.row_count != event.row_count:
            reasons.append(ContinuityReason.CONTENT_DIGEST_MISMATCH)
    if reasons:
        return ContinuityOutcome.ACQUISITION_MISMATCH, tuple(reasons)
    if event.status is not AcquisitionStatus.COMPLETE:
        incomplete = {AcquisitionStatus.EMPTY: ContinuityReason.ACQUISITION_EMPTY,
                      AcquisitionStatus.PARTIAL_PAGINATED: ContinuityReason.ACQUISITION_PARTIAL_PAGINATED,
                      AcquisitionStatus.FAILED: ContinuityReason.ACQUISITION_FAILED}
        return ContinuityOutcome.ACQUISITION_NOT_COMPLETE, (incomplete[event.status],)
    return None, ()


def _item(code: str, origin: ReviewOrigin, disposition: str, reasons: Any, issuer_id: str = "",
          security_id: str = "") -> ContinuityReviewItem:
    return ContinuityReviewItem(code=code, origin=origin, disposition=disposition,
                                reasons=tuple(r.value for r in reasons), existing_issuer_id=issuer_id,
                                existing_security_id=security_id)


def _review_items(history: IdentityHistory, rows: Tuple[Mapping[str, Any], ...], day: date,
                  supported_markets: Tuple[str, ...], active: Tuple[_ActiveCode, ...],
                  inactive: Tuple[_ActiveCode, ...],
                  known_codes: Tuple[str, ...]) -> Tuple[Tuple[ContinuityReviewItem, ...], Tuple[str, ...],
                                                        Tuple[ContinuityReason, ...]]:
    """凍結 LIVE1 の適格（関係する code の行）と凍結 ID1 の分類（batch ごと）→ 審査の項目 ・REUSE で満たされた code ・失敗の理由。"""
    items: List[ContinuityReviewItem] = []
    satisfied: List[str] = []
    registered = set(known_codes)
    for row in rows:                                                         # LIVE1: 関係する code の行の適格
        code = row.get("Code") if isinstance(row, Mapping) else None
        if not isinstance(code, str) or code not in registered:
            continue
        try:
            result = assess_master_row(row)
        except LiveInputError:
            return (), (), (ContinuityReason.CLASSIFICATION_FAILED,)
        if result.eligibility is not MasterEligibility.ELIGIBLE_FOR_ID1:
            items.append(_item(code, ReviewOrigin.LIVE1_ELIGIBILITY, result.eligibility.value, result.reasons))
    by_batch: Dict[str, List[_ActiveCode]] = {}
    for entry in (*active, *inactive):
        if entry.batch_id == "":
            continue
        if entry.batch_id not in by_batch:
            by_batch[entry.batch_id] = []
        members = by_batch[entry.batch_id]
        members.append(entry)
    unbatched = {entry.code for entry in inactive if entry.batch_id == ""}
    if not by_batch and unbatched:                                           # 退役 ／ 終了だけで anchor が読めない → 既定の batch
        by_batch["p8cont"] = []
    active_codes = {entry.code for entry in active}
    absent_seen: List[str] = []
    for batch_id in sorted(by_batch):                                        # ID1: batch ごとに同じ anchor で再導出
        members = by_batch[batch_id]
        member_codes = {m.code for m in members}
        member_securities = {m.security_id for m in members}
        member_issuers = {m.issuer_id for m in members}
        try:
            batch = BootstrapBatch(batch_id=batch_id, d0=day, supported_markets=supported_markets)
            manifest = propose_bootstrap(list(rows), batch, existing=history)
        except (BootstrapInputError, IdentityModelError):
            return (), (), (ContinuityReason.CLASSIFICATION_FAILED,)
        for item in manifest.review_items:
            relevant = (item.code in member_codes or item.existing_security_id in member_securities
                        or item.existing_issuer_id in member_issuers or item.code in unbatched)
            if not relevant:
                continue
            if item.disposition is ProposalDisposition.REUSE and item.code in member_codes & active_codes:
                expected = next(m for m in members if m.code == item.code)
                if item.existing_security_id == expected.security_id and item.existing_issuer_id == expected.issuer_id:
                    satisfied.append(item.code)
                    continue
            if item.code in absent_seen:
                continue
            absent_seen.append(item.code)
            items.append(_item(item.code, ReviewOrigin.ID1_CLASSIFICATION, item.disposition.value, item.reasons,
                              item.existing_issuer_id, item.existing_security_id))
    unique: List[ContinuityReviewItem] = []
    for item in sorted(items, key=lambda i: (i.code, i.origin.value)):
        if item not in unique:
            unique.append(item)
    return tuple(unique), tuple(sorted(set(satisfied))), ()


def execute_identity_continuity(*, data_root: Any, day: Any, rows: Any, event_reference: Any,
                                supported_markets: Any) -> ContinuityResult:
    """T の master snapshot の取得 event と bounded な行から、条件を満たすときだけ A1 の 1 日の `Coverage` を append する。"""
    _require(data_root is not None and str(data_root).strip() != "", "DATA_ROOT_REQUIRED", "data_root")
    _require(type(day) is date, "INVALID_DAY", "day")
    _require(isinstance(rows, (list, tuple)) and all(isinstance(r, Mapping) for r in rows), "INVALID_ROWS", "rows")
    _require(is_acquisition_reference(event_reference), "INVALID_EVENT_REFERENCE", "event_reference")
    _require(isinstance(supported_markets, tuple) and len(supported_markets) > 0
             and all(isinstance(m, str) and m != "" for m in supported_markets), "INVALID_MARKETS",
             "supported_markets")
    rows = tuple(rows)

    def failed(outcome: ContinuityOutcome, reasons: Tuple[ContinuityReason, ...], code: str = "",
               review: Tuple[ContinuityReviewItem, ...] = (), active_count: int = 0,
               unregistered: int = 0) -> ContinuityResult:
        return ContinuityResult(outcome=outcome, day=day, event_reference=event_reference, reasons=reasons,
                                review=review, failure_code=code, active_codes=active_count,
                                unregistered_codes=unregistered)

    try:                                                                     # 1. 取得 event（store が authority）
        events = AcquisitionEventStore.open(data_root, read_only=True)
    except AcquisitionStoreError as exc:
        return failed(ContinuityOutcome.STORE_FAILURE, (ContinuityReason.STORE_ERROR,), exc.code)
    event = next((e for e in events.records() if e.reference == event_reference), None)
    if event is None:
        return failed(ContinuityOutcome.ACQUISITION_MISMATCH, (ContinuityReason.EVENT_NOT_FOUND,))
    outcome, reasons = _event_checks(event, day, rows)
    if outcome is not None:
        return failed(outcome, reasons)

    try:                                                                     # 2. 凍結 A1 の履歴
        store = IdentityStore.open(data_root)
    except IdentityStoreError as exc:
        return failed(ContinuityOutcome.STORE_FAILURE, (ContinuityReason.STORE_ERROR,), exc.code)
    history = store.history
    record = coverage_for_day(day, event.reference, event.acquired_at)
    if history.contains(record.record_id):                                   # 3. 同じ authority の coverage → REUSED
        return ContinuityResult(outcome=ContinuityOutcome.REUSED, day=day, event_reference=event_reference,
                                coverage_record_id=record.record_id)
    for existing in history.coverages:
        if existing.scope is record.scope and existing.effective_from < record.effective_to \
                and record.effective_from < existing.effective_to:
            return failed(ContinuityOutcome.COVERAGE_CONFLICT,
                          (ContinuityReason.EXISTING_COVERAGE_DIFFERENT_PROVENANCE,))

    active, inactive, known_codes, scope_reasons = relevant_scope(history)   # 4. 関係する登録済み identity の範囲
    if scope_reasons:
        return failed(ContinuityOutcome.IDENTITY_SCOPE_UNRESOLVED, scope_reasons, active_count=len(active))
    timing: List[ContinuityReason] = []
    for item in history.records:                                             # 5. 取得の時点で知られていた authority か
        if item.known_at > event.acquired_at:
            reason = ContinuityReason.AUTHORITY_KNOWN_AFTER_ACQUISITION if isinstance(item, Coverage) \
                else ContinuityReason.IDENTITY_NOT_KNOWN_BY_ACQUISITION
            if reason not in timing:
                timing.append(reason)
    if ContinuityReason.IDENTITY_NOT_KNOWN_BY_ACQUISITION in timing:
        timing = [ContinuityReason.IDENTITY_NOT_KNOWN_BY_ACQUISITION]
    if timing:
        return failed(ContinuityOutcome.IDENTITY_SCOPE_UNRESOLVED, tuple(timing), active_count=len(active))

    present = {r.get("Code") for r in rows if isinstance(r.get("Code"), str)}
    unregistered = len(present - set(known_codes))
    review, satisfied, failure = _review_items(history, rows, day, supported_markets, active, inactive,
                                               known_codes)
    if failure:                                                              # 6. 凍結 LIVE1 ・ID1 の分類
        return failed(ContinuityOutcome.IDENTITY_SCOPE_UNRESOLVED, failure, active_count=len(active),
                      unregistered=unregistered)
    if review:
        return failed(ContinuityOutcome.REVIEW_REQUIRED, (ContinuityReason.IDENTITY_CHANGE_SUSPECTED,),
                      review=review, active_count=len(active), unregistered=unregistered)
    if not active:                                                           # 有効な登録済み identity が無い → 宣言しない
        return failed(ContinuityOutcome.IDENTITY_SCOPE_UNRESOLVED, (ContinuityReason.NO_ACTIVE_REGISTERED_IDENTITY,),
                      unregistered=unregistered)
    missing = [entry.code for entry in active if entry.code not in satisfied]
    if missing:
        return failed(ContinuityOutcome.IDENTITY_SCOPE_UNRESOLVED, (ContinuityReason.CLASSIFICATION_INCOMPLETE,),
                      active_count=len(active), unregistered=unregistered)

    try:                                                                     # 7. coverage だけを append
        appended = store.append(record)
    except IdentityAppendRejected as exc:
        return failed(ContinuityOutcome.STORE_FAILURE, (ContinuityReason.STORE_ERROR,), exc.code,
                      active_count=len(active), unregistered=unregistered)
    except IdentityStoreError as exc:
        return failed(ContinuityOutcome.STORE_FAILURE, (ContinuityReason.STORE_ERROR,), exc.code,
                      active_count=len(active), unregistered=unregistered)
    outcome = ContinuityOutcome.APPENDED if appended.status.value == "APPENDED" else ContinuityOutcome.REUSED
    return ContinuityResult(outcome=outcome, day=day, event_reference=event_reference,
                            coverage_record_id=appended.record_id, active_codes=len(active),
                            unregistered_codes=unregistered)


__all__ = ["CONTINUITY_CONDITION", "CONTINUITY_RULES_VERSION", "ContinuityError", "ContinuityOutcome",
           "ContinuityReason", "ContinuityResult", "ContinuityReviewItem", "ReviewOrigin", "coverage_for_day",
           "execute_identity_continuity", "relevant_scope"]
