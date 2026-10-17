"""P9-A1 — 凍結の Phase 8 の完了した screen の run を read-only で再構成する引き渡し（no-network ・no-credential ・no-write）。

使うのは凍結 B5C の runner の再構成の部品（`load_ledger` ・`ScreenRunSpec` ・`ledger_path` ・`assemble`）と、凍結の store の
read-only の open だけ。B5C の `execute_screen` ／ `continue` ／ `_store_integrity`（store を作る）・transport ・client ・credential は
使わない。評価の意味は凍結 B4A ／ B5B だけが持ち、本 module は複製しない。

1. 明示の P8 root（絶対 ・既存の directory。作らない）と明示の `run_id` を受ける。
2. 台帳を read-only で読み、凍結の検査（digest ・鎖 ・遷移）を通す。spec から `ScreenRunSpec` を再構成し、spec の完全一致と
   `run_id` の一致を要求する（凍結の規則の版が違えば fail closed）。
3. 閉じていない呼び出し ・未判定 ・未試行の発行体（PARTIAL）を拒む。必要な authority の store が全部すでに在ることを read-only の
   open で確かめる（無い store は作らずに fail closed）。Universe ・方針の authority が spec と一致することを確かめる。
4. 凍結 `assemble` → `ScreenResultSet`。実行の完全性が COMPLETE でなければ拒む。`screen_result_id` と最小の不変の metadata を返す。

drift: 台帳は `screen_result_id` を封じない（P9-OBS-002）。P9 は `run_id` と消費した `screen_result_id` の両方に結び付き、
新しい再構成が違えば `P8_RESULT_DRIFT`（`require_binding` ・`reconstruct_bound`）。手順: 1 つの P8 の private root ・D0 に 1 つの run。

Watchlist ／ Thesis の authority ・提案 ・順位 ・点数 ・推奨は無い。契約: `docs/databank/PHASE9_A1_P8_HANDOFF_CONTRACT.md`。
"""
from __future__ import annotations

import os.path
import re
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Any, Dict, Tuple

from ..jquants_screen_local import ScreenRunError, ScreenRunSpec, assemble, ledger_path, load_ledger
from ..screener_intelligence.acquisition_event_store import AcquisitionEventStore, AcquisitionStoreError
from ..screener_intelligence.acquisition_manifest_store import ManifestStore, ManifestStoreError
from ..screener_intelligence.held_observation_store import HeldObservationStore, HeldStoreError
from ..screener_intelligence.identity_store import IdentityStore, IdentityStoreError
from ..screener_intelligence.observation_store import ObservationStore, ObservationStoreError
from ..screener_intelligence.provider_holdings_store import HoldingsStoreError, ProviderHoldingsStore
from ..screener_intelligence.screener_criteria_model import ScreenerAuthorityMode
from ..screener_intelligence.screener_policy_authority_store import PolicyAuthorityStore, PolicyStoreError
from ..screener_intelligence.screener_result_set import ExecutionCompleteness, ResultSetError, ScreenResultSet
from ..screener_intelligence.screener_universe_store import UniverseAuthorityStore, UniverseStoreError
from ..screener_intelligence.semantic_metadata_store import SemanticMetadataStore, SemanticMetadataStoreError

HANDOFF_SCHEMA_VERSION = "p9_p8_handoff:0.1.0"
HANDOFF_RULES_VERSION = "p9_p8_handoff:0.1.0"
#: 引き渡しの意味（P8 の結果は P9 の Watchlist の項目 ・Thesis ・推奨 ・売買の指示ではない）
HANDOFF_CLASS = "READ_ONLY_RECONSTRUCTION_OF_A_COMPLETED_P8_RUN_NOT_A_WATCHLIST_ENTRY_NOT_A_THESIS"
#: 同じ P8 の private root ・D0 に 1 つの run（後の run が同じ評価の瞬間までの保持を足すと再構成が変わり得る。P9-OBS-002）
RUN_PER_ROOT_PROCEDURE = "ONE_P8_RUN_PER_PRIVATE_ROOT_PER_D0"
_RUN_ID_RE = re.compile(r"^p8run_[0-9a-f]{24}$")
_SCREEN_RESULT_ID_RE = re.compile(r"^p8srs_[0-9a-f]{24}$")
#: 再構成が要る凍結の authority の store（read-only の open。無ければ作らずに fail closed）
_REQUIRED_STORES: Tuple[Tuple[str, Any], ...] = (
    ("identity", IdentityStore), ("observation", ObservationStore), ("semantic_metadata", SemanticMetadataStore),
    ("held", HeldObservationStore), ("acquisition_events", AcquisitionEventStore), ("manifests", ManifestStore),
    ("provider_holdings", ProviderHoldingsStore), ("policy", PolicyAuthorityStore), ("universe", UniverseAuthorityStore))
_STORE_ERRORS = (IdentityStoreError, ObservationStoreError, SemanticMetadataStoreError, HeldStoreError,
                 AcquisitionStoreError, ManifestStoreError, HoldingsStoreError, PolicyStoreError, UniverseStoreError)


class HandoffError(ValueError):
    """引き渡しの失敗（fail closed）。P8 の root には何も書かない ・修復しない。"""

    def __init__(self, code: str, detail: str = "") -> None:
        super().__init__(f"{code}: {detail}" if detail else code)
        self.code = code
        self.detail = detail


def _require(condition: bool, code: str, detail: str = "") -> None:
    if not condition:
        raise HandoffError(code, detail)


@dataclass(frozen=True, kw_only=True)
class HandoffMetadata:
    """消費した P8 の run の最小の不変の metadata（P9 が結び付く参照）。財務の値 ・code ・会社名は持たない。"""

    run_id: str
    screen_result_id: str
    universe_id: str
    universe_version: int
    policy_id: str
    policy_version: int
    authority_mode: str
    authority_day: date
    evaluation_as_of: datetime
    member_count: int
    issuer_count: int
    execution_completeness: str
    ledger_event_count: int
    ledger_head_digest: str
    handoff_class: str = HANDOFF_CLASS
    rules_version: str = HANDOFF_RULES_VERSION
    schema_version: str = HANDOFF_SCHEMA_VERSION

    def as_dict(self) -> Dict[str, Any]:
        return {"authority_day": self.authority_day.isoformat(), "authority_mode": self.authority_mode,
                "evaluation_as_of": self.evaluation_as_of.isoformat(),
                "execution_completeness": self.execution_completeness, "handoff_class": self.handoff_class,
                "issuer_count": self.issuer_count, "ledger_event_count": self.ledger_event_count,
                "ledger_head_digest": self.ledger_head_digest, "member_count": self.member_count,
                "policy_id": self.policy_id, "policy_version": self.policy_version,
                "rules_version": self.rules_version, "run_id": self.run_id,
                "schema_version": self.schema_version, "screen_result_id": self.screen_result_id,
                "universe_id": self.universe_id, "universe_version": self.universe_version}


@dataclass(frozen=True, kw_only=True)
class P8RunHandoff:
    """再構成した全結果（凍結 B5B の `ScreenResultSet`）＋ metadata。保存しない（P9 の authority は後の gate）。"""

    result: ScreenResultSet
    metadata: HandoffMetadata

    @property
    def screen_result_id(self) -> str:
        return self.metadata.screen_result_id


def _p8_root(value: Any) -> Path:
    _require(isinstance(value, (str, Path)) and str(value).strip() != "", "P8_ROOT_REQUIRED", "p8_root")
    path = Path(value)
    _require(path.is_absolute(), "P8_ROOT_NOT_ABSOLUTE", "p8_root")
    path = Path(os.path.normpath(str(path)))
    _require(path.is_dir(), "P8_ROOT_MISSING", "p8_root")                       # 作らない
    return path


def _spec_from_ledger(spec: Dict[str, Any]) -> ScreenRunSpec:
    """台帳の spec（dict）→ 凍結 `ScreenRunSpec`。欠けた欄 ・不正な値は fail closed。"""
    try:
        return ScreenRunSpec(universe_id=spec["universe_id"], universe_version=spec["universe_version"],
                             universe_members=tuple(spec["universe_members"]), policy_id=spec["policy_id"],
                             policy_version=spec["policy_version"],
                             authority_mode=ScreenerAuthorityMode(spec["authority_mode"]),
                             authority_day=date.fromisoformat(spec["authority_day"]),
                             evaluation_as_of=datetime.fromisoformat(spec["evaluation_as_of"]))
    except (KeyError, TypeError, ValueError) as exc:
        raise HandoffError("P8_SPEC_MISMATCH", type(exc).__name__) from None


def _opened_stores(root: Path) -> Dict[str, Any]:
    stores: Dict[str, Any] = {}
    for name, store in _REQUIRED_STORES:
        try:
            stores[name] = store.open(root, read_only=True)                      # 無ければ例外（作らない）
        except _STORE_ERRORS as exc:
            missing = exc.category.value in ("STORE_MISSING", "AUTHORITY_MISSING")
            raise HandoffError("P8_STORE_MISSING" if missing else "P8_STORE_UNAVAILABLE",
                               f"{name}:{exc.code}") from None
    return stores


def reconstruct_completed_run(p8_root: Any, run_id: Any) -> P8RunHandoff:
    """完了した P8 の run を read-only で再構成する（network ・transport ・credential ・書き込みは無い）。"""
    root = _p8_root(p8_root)
    _require(isinstance(run_id, str) and bool(_RUN_ID_RE.match(run_id)), "RUN_ID_INVALID", "run_id")
    try:
        state = load_ledger(ledger_path(root, run_id), run_id)                  # 凍結の検査（digest ・鎖 ・遷移）
    except ScreenRunError as exc:
        raise HandoffError("P8_LEDGER_INVALID", exc.code) from None
    spec = _spec_from_ledger(state.spec)
    _require(spec.as_dict() == state.spec, "P8_SPEC_MISMATCH", "spec")
    _require(spec.run_id == run_id, "P8_SPEC_MISMATCH", "run_id")
    _require(state.open_invocation is None, "P8_RUN_OPEN_INVOCATION", "run_id")
    _require(state.assessed is not None, "P8_RUN_NOT_COMPLETE", "master_not_assessed")
    _require(all(route["issuer_id"] in state.attempts for route in state.assessed["routes"]),
             "P8_RUN_NOT_COMPLETE", "issuer_not_attempted")
    stores = _opened_stores(root)
    universe = stores["universe"].get_by_universe_id(spec.universe_id)
    _require(universe is not None and universe.version == spec.universe_version
             and tuple(universe.universe.members) == spec.universe_members, "P8_UNIVERSE_MISMATCH", "universe")
    policy = stores["policy"].get_by_policy_id(spec.policy_id)
    _require(policy is not None and policy.policy.version == spec.policy_version, "P8_POLICY_MISMATCH", "policy")
    try:
        result = assemble(root, spec, state)                                    # 凍結 B4A ／ B5B（評価の意味は複製しない）
    except ScreenRunError as exc:
        raise HandoffError("P8_RECONSTRUCTION_FAILED", exc.code) from None
    except ResultSetError as exc:
        raise HandoffError("P8_RECONSTRUCTION_FAILED", exc.code) from None
    except _STORE_ERRORS as exc:
        raise HandoffError("P8_STORE_UNAVAILABLE", exc.code) from None
    _require(result.execution_completeness is ExecutionCompleteness.COMPLETE, "P8_RUN_NOT_COMPLETE",
             result.execution_completeness.value)
    metadata = HandoffMetadata(run_id=run_id, screen_result_id=result.screen_result_id,
                               universe_id=spec.universe_id, universe_version=spec.universe_version,
                               policy_id=spec.policy_id, policy_version=spec.policy_version,
                               authority_mode=spec.authority_mode.value, authority_day=spec.authority_day,
                               evaluation_as_of=spec.evaluation_as_of, member_count=len(result.member_outcomes),
                               issuer_count=len(result.issuer_results),
                               execution_completeness=result.execution_completeness.value,
                               ledger_event_count=len(state.events), ledger_head_digest=state.last_digest)
    return P8RunHandoff(result=result, metadata=metadata)


def require_binding(handoff: Any, *, run_id: Any, screen_result_id: Any) -> P8RunHandoff:
    """純: 新しい再構成が、P9 が結び付いた `run_id` ・`screen_result_id` と一致することを要求する（違えば P8_RESULT_DRIFT）。"""
    _require(isinstance(handoff, P8RunHandoff), "HANDOFF_INVALID", "handoff")
    _require(isinstance(run_id, str) and bool(_RUN_ID_RE.match(run_id)), "RUN_ID_INVALID", "run_id")
    _require(isinstance(screen_result_id, str) and bool(_SCREEN_RESULT_ID_RE.match(screen_result_id)),
             "SCREEN_RESULT_ID_INVALID", "screen_result_id")
    _require(handoff.metadata.run_id == run_id, "P8_RESULT_DRIFT", "run_id")
    _require(handoff.metadata.screen_result_id == screen_result_id, "P8_RESULT_DRIFT", "screen_result_id")
    return handoff


def reconstruct_bound(p8_root: Any, *, run_id: Any, screen_result_id: Any) -> P8RunHandoff:
    """結び付いた参照で新しく再構成し、一致を要求する（read-only ・違えば P8_RESULT_DRIFT）。"""
    return require_binding(reconstruct_completed_run(p8_root, run_id), run_id=run_id,
                           screen_result_id=screen_result_id)


__all__ = ["HANDOFF_CLASS", "HANDOFF_RULES_VERSION", "HANDOFF_SCHEMA_VERSION", "RUN_PER_ROOT_PROCEDURE",
           "HandoffError", "HandoffMetadata", "P8RunHandoff", "reconstruct_bound", "reconstruct_completed_run",
           "require_binding"]
