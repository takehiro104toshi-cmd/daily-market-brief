"""P10-A4 — 人の決定の実行器（Phase 10 の production の runtime で新しい authority の revision を作る唯一の場所）。

`apply_decision(decision, *, p10_root, p9_root=None)` ・`dry_run_decision(...)`。流れ（決定ごと ・書くのは最後の 1 行だけ）:
1. 入力の検査（型 ・列挙 ・aware な `reviewed_at` ・人の著者の形 ・**全ての人の文が UTF-8 にできること**）。revision を作る前に行う
   （内容 address の id の計算で `UnicodeEncodeError` を出さない）。違えば `INPUT_REJECTED:<code>`。
2. P10 の store を開く（`PersonalAuthorityStores.open` だけ。初期化 ・作成 ・部分の配置の補修はしない）。
3. 鎖の関係を導く: 作成は A2 の id を導き、更新は `expected_head_revision_id` の revision から seq ＋1 ・prev を導く。
4. 候補が既に同じ行で在れば `REUSED`（正確な再試行）。
5. `expected_head_revision_id` が鎖の今の先頭でなければ `STALE_AUTHORITY_HEAD`（新しい先頭の上に黙って載せない）。
6. Attention は A1 の `read_p9_private_snapshot(p9_root, at=reviewed_at)` だけで P9 を検査: 対象が在る（`P9_TARGET_ABSENT`）・種類が
   一致（`P9_TARGET_KIND_MISMATCH`）・`observed_p9_revision_id` がその時点のその対象の revision と等しい（`P9_REVISION_STALE_OR_MISMATCH`。
   古い非先頭の revision は v1 で受けない）。P9 は書かない。
7. A2 の型の構築（違えば `INPUT_REJECTED:<A2 の code>`）・A3 と同じ鎖 ／ 世界の検査（`AUTHORITY_WORLD_INVALID:<A2 の code>`）。
8. apply だけ: 唯一の追記の経路 `PersonalAuthorityStores` で 1 行（A3 の `CHAIN_HEAD_MISMATCH` → `STALE_AUTHORITY_HEAD` ・
   `CONCURRENT_MODIFICATION` はそのまま）。dry-run は何も書かず `VALID` ／ `WOULD_REUSE` ／ `WOULD_BE_REJECTED` だけを返す。

好みの推測 ・学習 ・機械が作る個人の authority ・自動の置き換えの profile は無い。例外の文は安全な code だけ（文 ・id ・path ・著者なし）。

記録: `docs/databank/PHASE10_A4_EXECUTOR_REVIEW_VIEW.md`。
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Any, Optional, Tuple

from .attention_model import AttentionRevision, AttentionState, AttentionTargetKind, derive_attention_id
from .authority_stores import PersonalAuthorityStores
from .cross_rules import check_personal_world
from .decisions import (AttentionCreate, AttentionRevise, AttentionTransition, ProfileCorrection, ProfileCreate,
                        ProfileRetire, ProfileRevise)
from .p9_view import P9ViewError, read_p9_private_snapshot
from .profile_model import PersonalProfileRevision, ProfileStatus, canonical_excluded_issuer_ids, derive_profile_id
from .revision_model import ChangeKind, PersonalModelError
from .store_io import PersonalStoreError, StoreFailureCategory

EXECUTOR_RULES_VERSION = "p10_executor:0.1.0"
_DECISION_TYPES = (ProfileCreate, ProfileRevise, ProfileCorrection, ProfileRetire, AttentionCreate, AttentionRevise,
                   AttentionTransition)
_PROFILE_UPDATES = (ProfileRevise, ProfileCorrection, ProfileRetire)
_TARGET_SYNTAX_FAILURES = ("INVALID_TARGET_ROOT_ID", "INVALID_OBSERVED_P9_REVISION_ID")


class ExecutionStatus(str, Enum):
    APPENDED = "APPENDED"
    REUSED = "REUSED"


class DryRunStatus(str, Enum):
    VALID = "VALID"
    WOULD_REUSE = "WOULD_REUSE"
    WOULD_BE_REJECTED = "WOULD_BE_REJECTED"


class ExecutionRefusal(RuntimeError):
    """型つきの拒否（書かない）。文は安全な code ・詳細の code だけ。"""

    def __init__(self, code: str, detail: str = "") -> None:
        super().__init__(f"{code}:{detail}" if detail else code)
        self.code = code
        self.detail = detail


@dataclass(frozen=True)
class ExecutionReceipt:
    """private な受領（root ／ revision の id は次の決定の `expected_head_revision_id` に使う。既定の出力には出さない）。"""

    operation: str
    status: ExecutionStatus
    root_id: str
    revision_id: str


@dataclass(frozen=True)
class DryRunResult:
    operation: str
    status: DryRunStatus
    refusal: str = ""


def _refuse(code: str, detail: str = "") -> ExecutionRefusal:
    return ExecutionRefusal(code, detail)


# ---------------------------------------------------------------- 1. 入力の検査（revision を作る前）


def _text(value: Any, name: str) -> str:
    if not isinstance(value, str):
        raise _refuse("INPUT_REJECTED", f"INVALID_TEXT:{name}")
    try:
        value.encode("utf-8")
    except UnicodeEncodeError:
        raise _refuse("INPUT_REJECTED", "UNENCODABLE_TEXT") from None            # 文は返さない
    return value


def _check_input(decision: Any) -> None:
    if type(decision) not in _DECISION_TYPES:
        raise _refuse("INPUT_REJECTED", "UNKNOWN_DECISION")
    if decision.operation != type(decision).__dataclass_fields__["operation"].default:
        raise _refuse("INPUT_REJECTED", "OPERATION_MISMATCH")
    at = decision.reviewed_at
    if not isinstance(at, datetime) or at.tzinfo is None or at.tzinfo.utcoffset(at) is None:
        raise _refuse("INPUT_REJECTED", "INSTANT_NOT_AWARE")
    for name, value in sorted(vars(decision).items()):
        if name in ("reviewed_at", "review_lookahead_days", "target_kind", "state"):
            continue
        if name == "excluded_issuer_ids":
            if not isinstance(value, tuple):
                raise _refuse("INPUT_REJECTED", "INVALID_LIST:excluded_issuer_ids")
            for item in value:
                _text(item, name)
        else:
            _text(value, name)
    if isinstance(decision, (ProfileCreate, ProfileRevise, ProfileCorrection)):
        if type(decision.review_lookahead_days) is not int:
            raise _refuse("INPUT_REJECTED", "INVALID_REVIEW_LOOKAHEAD_DAYS")
    if isinstance(decision, AttentionCreate) and not isinstance(decision.target_kind, AttentionTargetKind):
        raise _refuse("INPUT_REJECTED", "INVALID_TARGET_KIND")
    if isinstance(decision, (AttentionCreate, AttentionTransition)) and not isinstance(decision.state, AttentionState):
        raise _refuse("INPUT_REJECTED", "INVALID_STATE")


# ---------------------------------------------------------------- 2〜5. 鎖の関係 ・候補（A2 の型）


@dataclass(frozen=True)
class _Plan:
    revision: Any
    is_profile: bool
    reuse: bool


def _content(decision: Any) -> dict:
    try:
        excluded = canonical_excluded_issuer_ids(decision.excluded_issuer_ids)
    except PersonalModelError as exc:
        raise _refuse("INPUT_REJECTED", exc.code) from None
    return dict(horizon_note=decision.horizon_note, liquidity_note=decision.liquidity_note,
                risk_context_note=decision.risk_context_note, review_lookahead_days=decision.review_lookahead_days,
                excluded_issuer_ids=excluded, exclusion_reason_note=decision.exclusion_reason_note)


def _expected_head(store: Any, root_id: str, expected: str) -> Tuple[Any, Any]:
    """(人が見た先頭, 今の先頭)。root が無い ／ 人が見た revision がその鎖に無ければ入力の拒否。"""
    if root_id not in store.roots():
        raise _refuse("INPUT_REJECTED", "AUTHORITY_ROOT_NOT_FOUND")
    chain = store.chain(root_id)
    seen = next((r for r in chain if r.revision_id == expected), None)
    if seen is None:
        raise _refuse("INPUT_REJECTED", "EXPECTED_HEAD_NOT_IN_CHAIN")
    return seen, chain[-1]


def _build(build) -> Tuple[Any, str]:
    """A2 の型の構築（失敗の code を返す ・例外は外へ出さない）。"""
    try:
        return build(), ""
    except PersonalModelError as exc:
        return None, exc.code


def _profile_candidate(decision: Any, stores: PersonalAuthorityStores) -> Tuple[Any, str, Any, Any]:
    if isinstance(decision, ProfileCreate):
        content = _content(decision)
        return (*_build(lambda: PersonalProfileRevision(
            profile_id=derive_profile_id(author_ref=decision.author_ref, reviewed_at=decision.reviewed_at), seq=1,
            prev_revision_id="", change_kind=ChangeKind.CREATE, status=ProfileStatus.ACTIVE,
            author_ref=decision.author_ref, reviewed_at=decision.reviewed_at, **content)), None, None)
    seen, head = _expected_head(stores.profile, decision.profile_id, decision.expected_head_revision_id)
    frame = dict(profile_id=decision.profile_id, seq=seen.seq + 1, prev_revision_id=seen.revision_id,
                 author_ref=decision.author_ref, reviewed_at=decision.reviewed_at)
    if isinstance(decision, ProfileRetire):                                       # 内容は変えない ・状態だけ
        content = dict(horizon_note=seen.horizon_note, liquidity_note=seen.liquidity_note,
                       risk_context_note=seen.risk_context_note, review_lookahead_days=seen.review_lookahead_days,
                       excluded_issuer_ids=seen.excluded_issuer_ids, exclusion_reason_note=seen.exclusion_reason_note)
        built = _build(lambda: PersonalProfileRevision(**frame, **content, change_kind=ChangeKind.TRANSITION,
                                                       status=ProfileStatus.RETIRED,
                                                       retirement_reason=decision.retirement_reason))
    elif isinstance(decision, ProfileCorrection):
        content = _content(decision)
        built = _build(lambda: PersonalProfileRevision(**frame, **content, change_kind=ChangeKind.CORRECTION,
                                                       status=ProfileStatus.ACTIVE,
                                                       corrects_revision_id=decision.corrects_revision_id,
                                                       correction_reason=decision.correction_reason))
    else:
        content = _content(decision)
        built = _build(lambda: PersonalProfileRevision(**frame, **content, change_kind=ChangeKind.REVISE,
                                                       status=ProfileStatus.ACTIVE))
    return (*built, seen, head)


def _attention_candidate(decision: Any, stores: PersonalAuthorityStores) -> Tuple[Any, str, Any, Any]:
    if isinstance(decision, AttentionCreate):
        return (*_build(lambda: AttentionRevision(
            attention_id=derive_attention_id(target_kind=decision.target_kind, target_root_id=decision.target_root_id,
                                             author_ref=decision.author_ref, reviewed_at=decision.reviewed_at),
            seq=1, prev_revision_id="", change_kind=ChangeKind.CREATE, target_kind=decision.target_kind,
            target_root_id=decision.target_root_id, observed_p9_revision_id=decision.observed_p9_revision_id,
            state=decision.state, author_ref=decision.author_ref, reviewed_at=decision.reviewed_at)), None, None)
    seen, head = _expected_head(stores.attention, decision.attention_id, decision.expected_head_revision_id)
    kind, state = ((ChangeKind.TRANSITION, decision.state) if isinstance(decision, AttentionTransition)
                   else (ChangeKind.REVISE, seen.state))
    return (*_build(lambda: AttentionRevision(
        attention_id=decision.attention_id, seq=seen.seq + 1, prev_revision_id=seen.revision_id, change_kind=kind,
        target_kind=seen.target_kind, target_root_id=seen.target_root_id,
        observed_p9_revision_id=decision.observed_p9_revision_id, state=state, author_ref=decision.author_ref,
        reviewed_at=decision.reviewed_at)), seen, head)


# ---------------------------------------------------------------- 6. P9 の read-only の検査（A1 の adapter だけ）


def _check_p9(decision: Any, stores: PersonalAuthorityStores, p9_root: Any) -> None:
    if p9_root is None:
        raise _refuse("INPUT_REJECTED", "P9_ROOT_REQUIRED")
    if isinstance(decision, AttentionCreate):
        kind, target = decision.target_kind, decision.target_root_id
    else:
        head = stores.attention.chain(decision.attention_id)[0]
        kind, target = head.target_kind, head.target_root_id
    try:
        snapshot = read_p9_private_snapshot(p9_root, at=decision.reviewed_at)
    except P9ViewError as exc:
        raise _refuse("P9_UNAVAILABLE", exc.code) from None
    visible = {**{w.watch_entry_id: (AttentionTargetKind.P9_WATCH_ENTRY, w.revision_id) for w in snapshot.watch},
               **{t.thesis_id: (AttentionTargetKind.P9_THESIS, t.revision_id) for t in snapshot.thesis}}
    if target not in visible:
        raise _refuse("P9_TARGET_ABSENT")
    found_kind, revision_id = visible[target]
    if found_kind is not kind:
        raise _refuse("P9_TARGET_KIND_MISMATCH")
    if decision.observed_p9_revision_id != revision_id:                          # その時点に見える revision だけ
        raise _refuse("P9_REVISION_STALE_OR_MISMATCH")


# ---------------------------------------------------------------- 7. 計画（apply ／ dry-run 共通 ・書かない）


def _open(p10_root: Any) -> PersonalAuthorityStores:
    try:
        return PersonalAuthorityStores.open(p10_root)                            # 開くだけ（初期化しない）
    except PersonalStoreError as exc:
        raise _refuse("STORE_UNAVAILABLE", f"{exc.category.value}:{exc.code}") from None


def _plan(decision: Any, stores: PersonalAuthorityStores, p9_root: Any) -> _Plan:
    is_profile = isinstance(decision, (ProfileCreate, *_PROFILE_UPDATES))
    candidate, failure, seen, head = (_profile_candidate if is_profile else _attention_candidate)(decision, stores)
    store = stores.profile if is_profile else stores.attention
    if candidate is not None:                                                     # 4. 正確な再試行
        line = _line(store, candidate)
        existing = store.line_for(candidate.revision_id)
        if existing is not None:
            if existing != line:
                raise _refuse("AUTHORITY_CONFLICT")
            return _Plan(candidate, is_profile, True)
    if head is not None and seen.revision_id != head.revision_id:                 # 5. 古い先頭
        raise _refuse("STALE_AUTHORITY_HEAD")
    if candidate is None and failure not in _TARGET_SYNTAX_FAILURES:               # 対象の構文以外の誤りは P9 を読まずに拒む
        raise _refuse("INPUT_REJECTED", failure)
    if not is_profile:
        _check_p9(decision, stores, p9_root)                                      # 6. P9（対象の不在 ・種類の不一致を先に）
    if candidate is None:
        raise _refuse("INPUT_REJECTED", failure)
    profiles = stores.profile.all_revisions() + ((candidate,) if is_profile else ())
    attention = stores.attention.all_revisions() + (() if is_profile else (candidate,))
    try:
        check_personal_world(list(profiles), list(attention))                     # A3 と同じ鎖 ／ 世界の検査
    except PersonalModelError as exc:
        raise _refuse("AUTHORITY_WORLD_INVALID", exc.code) from None
    return _Plan(candidate, is_profile, False)


def _line(store: Any, candidate: Any) -> str:
    try:
        return store.line_of(candidate)
    except PersonalModelError as exc:
        raise _refuse("INPUT_REJECTED", exc.code) from None


# ---------------------------------------------------------------- 公開の 2 つの入口


def apply_decision(decision: Any, *, p10_root: Any, p9_root: Optional[Any] = None) -> ExecutionReceipt:
    """人の決定を検査し、唯一の追記の経路で 1 行を書く（または `REUSED`）。拒否は `ExecutionRefusal`（書かない）。"""
    _check_input(decision)
    stores = _open(p10_root)
    plan = _plan(decision, stores, p9_root)
    if plan.reuse:
        return ExecutionReceipt(decision.operation, ExecutionStatus.REUSED, plan.revision.root_id,
                                plan.revision.revision_id)
    try:
        result = (stores.append_profile_revision if plan.is_profile else stores.append_attention_revision)(
            plan.revision)
    except PersonalStoreError as exc:
        if exc.category is StoreFailureCategory.CONCURRENT_MODIFICATION:
            raise _refuse("CONCURRENT_MODIFICATION") from None
        if exc.code == "CHAIN_HEAD_MISMATCH":
            raise _refuse("STALE_AUTHORITY_HEAD") from None
        if exc.code.startswith("WORLD_INVALID:"):
            raise _refuse("AUTHORITY_WORLD_INVALID", exc.code.split(":", 1)[1]) from None
        raise _refuse("STORE_UNAVAILABLE", f"{exc.category.value}:{exc.code}") from None
    return ExecutionReceipt(decision.operation, ExecutionStatus(result.status.value), plan.revision.root_id,
                            result.revision_id)


def dry_run_decision(decision: Any, *, p10_root: Any, p9_root: Optional[Any] = None) -> DryRunResult:
    """apply と同じ全ての検査（入力 ・P9 ・候補 ・鎖 ／ 世界）を行い、何も書かない ・作らない。"""
    operation = decision.operation if type(decision) in _DECISION_TYPES else ""
    try:
        _check_input(decision)
        plan = _plan(decision, _open(p10_root), p9_root)
    except ExecutionRefusal as exc:
        return DryRunResult(operation, DryRunStatus.WOULD_BE_REJECTED, str(exc))
    return DryRunResult(operation, DryRunStatus.WOULD_REUSE if plan.reuse else DryRunStatus.VALID)


__all__ = ["DryRunResult", "DryRunStatus", "EXECUTOR_RULES_VERSION", "ExecutionReceipt", "ExecutionRefusal",
           "ExecutionStatus", "apply_decision", "dry_run_decision"]
