"""P8-B5C — 複数発行体の private な screen の実行器（有限の batch ・決定論の継続の台帳）。本人の環境でだけ実行する。

凍結の部品をつなぐだけ（意味は変えない）:
明示の Universe の authority（B5A）→ 明示の方針の authority（B3）→ D0 の master の取得（LIVE1。1 run に 1 回）→ 適格（凍結 LIVE1 の判定）→
審査済みの identity（凍結 A1 の resolver。評価の瞬間で）→ 発行体の束ね → 有限の fins の取得（1 発行体 ＝ 1 request）→ 取得の authority
（凍結 ACQ0 → EXE-R → EPOCH1R の manifest → F1 の保持）→ 凍結 B4A の評価 → 凍結 B5B の全結果の集合 → 凍結 B5B の安全な投影。

守る意味:
- 入力はすべて明示: private の data_root ・Universe の正確な選択子 ・方針の正確な選択子 ・D0 ・評価の瞬間（aware ・D0 の JST の日の中）・
  authority mode（v1 は RETROSPECTIVE_PROVIDER_AUTHORITY だけ）・この呼び出しの取得の瞬間（aware ・D0 の日の中 ・評価の瞬間以下 ・前の呼び出し
  以上）・予算（凍結の ≤ 8）。latest ・既定 ・時計 ・暗黙の日 ・暗黙の mode は無い。
- run の identity: `ScreenRunSpec`（Universe ・方針の id と版 ・member ・mode ・D0 ・評価の瞬間 ・規則の版）の内容 address `run_id`。継続は
  同じ引数から同じ `run_id` を再計算し、台帳の spec と完全一致しなければ network の前に fail closed。
- 台帳は運用の状態だけ（市場 ・Screener ・結果の authority ・P9 の記憶ではない）。追記専用 ・hash の鎖 ・修復しない。財務の値 ・provider の生の
  行 ・会社名は持たない（member の適格の判定と理由の code ・発行体の id ・取得の結果の状態 ・request の件数だけ）。
- 順は Universe の宣言の順（運用だけ ・非意味）。取得の経路の code は、発行体に解けた最初の member の code（主 ・優先 ・最良ではない）。
- 結果は凍結 B5B の型で毎回組み立てる（authority の store ＋ 台帳から決定論）。結果の store は無い。出力は凍結 B5B の安全な投影と運用の状態だけ。
- 隠れた retry ・page の追随 ・予算の迂回 ・identity の自動の作成 ・順位 ・推奨 ・公開の出力は無い。
記録: `docs/databank/PHASE8_B5C_MULTI_ISSUER_EXECUTOR.md`。
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Tuple

from .jquants_local_transport import DEFAULT_CREDENTIAL_ENV, LocalHttpsTransport
from .screener_intelligence.acquisition_event_model import (AcquisitionEvent, AcquisitionModelError,
                                                            AcquisitionStatus, RequestScope, bounded_content_digest)
from .screener_intelligence.acquisition_event_store import AcquisitionEventStore, AcquisitionStoreError
from .screener_intelligence.acquisition_manifest_builder import ManifestOutcome, build_manifest, record_manifest
from .screener_intelligence.acquisition_manifest_store import ManifestStore, ManifestStoreError
from .screener_intelligence.held_observation_store import HeldObservationStore, HeldStoreError
from .screener_intelligence.identity_bootstrap_model import day_start_jst
from .screener_intelligence.identity_correction_model import CorrectionHistory
from .screener_intelligence.identity_model import IdentifierScheme, SourceClass, canonical_json
from .screener_intelligence.identity_resolver import IdentityQuery, QueryKind, ResolutionStatus, resolve
from .screener_intelligence.identity_store import IdentityStore, IdentityStoreError
from .screener_intelligence.jquants_adapter_model import AdapterContext
from .screener_intelligence.jquants_financial_summary_executor import execute_financial_summary_row
from .screener_intelligence.jquants_live_client import JQuantsLiveClient, verify_identity_for_code
from .screener_intelligence.jquants_live_model import (FINS_SUMMARY_PATH, LIVE_RULES_VERSION, PILOT_MAX_REQUESTS,
                                                       LiveInputError, MasterEligibility, RequestBudget, Transport)
from .screener_intelligence.observation_semantics_model import ObservationSemantics
from .screener_intelligence.observation_store import ObservationStore, ObservationStoreError
from .screener_intelligence.provider_holdings_executor import HoldingsExecutionStatus, execute_provider_holdings
from .screener_intelligence.provider_holdings_store import HoldingsStoreError, ProviderHoldingsStore
from .screener_intelligence.screener_criteria_model import EvaluationContext, ScreenerAuthorityMode
from .screener_intelligence.screener_evaluator import EvaluationInputs
from .screener_intelligence.screener_policy_evaluation import (ORCHESTRATION_RULES_VERSION, PolicyEvaluationError,
                                                               PolicySelector, evaluate_selected_policy,
                                                               open_verified_store, resolve_policy)
from .screener_intelligence.screener_result_set import (RESULT_SET_RULES_VERSION, RESULT_SET_SCHEMA_VERSION,
                                                        IssuerResult, MemberOutcome, MemberOutcomeKind,
                                                        ResultSetError, ScreenResultSet, assemble_result_set)
from .screener_intelligence.screener_result_set_projection import (SET_SUMMARY_RULES_VERSION, SafeScreenSetSummary,
                                                                   project_safe_set_summary)
from .screener_intelligence.screener_result_summary import SUMMARY_RULES_VERSION, project_safe_summary
from .screener_intelligence.screener_universe_model import UNIVERSE_RULES_VERSION, UniverseAuthorityRecord
from .screener_intelligence.screener_universe_store import IntegrityStatus, UniverseAuthorityStore
from .screener_intelligence.semantic_metadata_store import SemanticMetadataStore, SemanticMetadataStoreError

RUN_SCHEMA_VERSION = "p8_screen_run:0.1.0"
RUN_RULES_VERSION = "p8_screen_run:0.1.0"
LEDGER_SCHEMA_VERSION = "p8_screen_run_ledger:0.1.0"
RUN_ID_PREFIX = "p8run"
LEDGER_DIRNAME = "screen_runs"
#: v1 の実行器が受ける authority mode（凍結 B2 ／ B4A の 2 つのうち、実 provider で真に評価できる 1 つだけ）
SUPPORTED_AUTHORITY_MODES: Tuple[ScreenerAuthorityMode, ...] = (ScreenerAuthorityMode.RETROSPECTIVE_PROVIDER_AUTHORITY,)
#: 次の仕事の順（運用だけ ・非意味）と取得の経路の規則（主 ・優先 ・最良ではない）
WORK_ORDER_RULE = "UNIVERSE_DECLARED_ORDER_OPERATIONAL_NON_SEMANTIC"
ROUTING_RULE = "FIRST_DECLARED_MEMBER_RESOLVING_TO_THE_ISSUER_ACQUISITION_ROUTING_ONLY"
EVENT_KINDS: Tuple[str, ...] = ("RUN_STARTED", "INVOCATION_STARTED", "MEMBERS_ASSESSED", "ISSUER_ATTEMPTED",
                                "INVOCATION_ENDED")
#: 発行体の取得の結果（台帳の運用の状態）
AUTHORITY_BUILT = "AUTHORITY_BUILT"
ACQUISITION_FAILED = "ACQUISITION_FAILED"
_BUILT_STATUSES = (HoldingsExecutionStatus.APPENDED, HoldingsExecutionStatus.REUSED,
                   HoldingsExecutionStatus.MIXED_APPEND_REUSE, HoldingsExecutionStatus.NO_CANONICAL_PERIODS,
                   HoldingsExecutionStatus.UNKNOWN_PERIOD_HELD_ROW)
_STORE_ERRORS = (IdentityStoreError, ObservationStoreError, SemanticMetadataStoreError, HeldStoreError,
                 AcquisitionStoreError, ManifestStoreError, HoldingsStoreError)
#: store の失敗のうち run 全体を無効にするもの（authority の破損 ・欠落 ・外部の変更）。他は発行体の取得の失敗
_WHOLE_RUN_CATEGORIES = ("STORE_CORRUPTION", "STORE_MISSING", "AUTHORITY_MISSING", "CONCURRENT_MODIFICATION")
_REPO_ROOT = Path(__file__).resolve().parents[2]


class ScreenRunError(ValueError):
    """run 全体の失敗（authority の破損 ・選択子 ・spec の不一致 ・台帳の破損 ・日の境界）。member の結果には潰さない。"""

    def __init__(self, code: str, detail: str = "") -> None:
        super().__init__(f"{code}: {detail}" if detail else code)
        self.code = code
        self.detail = detail


def _require(condition: bool, code: str, detail: str = "") -> None:
    if not condition:
        raise ScreenRunError(code, detail)


def _iso(value: datetime) -> str:
    return value.isoformat()


def _aware(value: Any, field_name: str) -> datetime:
    if isinstance(value, str):
        try:
            value = datetime.fromisoformat(value.strip())
        except ValueError:
            raise ScreenRunError("INSTANT_INVALID", field_name) from None
    _require(isinstance(value, datetime) and value.tzinfo is not None and value.tzinfo.utcoffset(value) is not None,
             "INSTANT_NAIVE_OR_MISSING", field_name)
    return value


def _day(value: Any) -> date:
    if isinstance(value, str):
        try:
            value = date.fromisoformat(value.strip())
        except ValueError:
            raise ScreenRunError("D0_INVALID", "d0") from None
    _require(type(value) is date, "D0_INVALID", "d0")
    return value


def _in_day(instant: datetime, day: date) -> bool:
    start = day_start_jst(day)
    return start <= instant < start + timedelta(days=1)


def validate_data_root(value: Any) -> Path:
    """明示の private な data root（絶対 ・repo ／ `.git` ／ Actions の外）。"""
    _require(isinstance(value, (str, Path)) and str(value).strip() != "", "DATA_ROOT_REQUIRED", "data_root")
    root = Path(value).expanduser()
    _require(root.is_absolute(), "DATA_ROOT_NOT_ABSOLUTE", "data_root")
    resolved = root.resolve()
    _require(".git" not in resolved.parts, "DATA_ROOT_INSIDE_GIT", "data_root")
    _require(_REPO_ROOT not in resolved.parents and resolved != _REPO_ROOT, "DATA_ROOT_INSIDE_REPO", "data_root")
    _require(os.environ.get("GITHUB_ACTIONS", "") == "", "GITHUB_ACTIONS_NOT_ALLOWED", "environment")
    return resolved


# ---------------------------------------------------------------- run の spec ・identity


@dataclass(frozen=True, kw_only=True)
class ScreenRunSpec:
    """1 つの screen の run の不変の束ね。`run_id` は内容 address（時計 ・path ・batch の番号に依らない）。"""

    universe_id: str
    universe_version: int
    universe_members: Tuple[str, ...]
    policy_id: str
    policy_version: int
    authority_mode: ScreenerAuthorityMode
    authority_day: date
    evaluation_as_of: datetime

    def __post_init__(self) -> None:
        _require(self.authority_mode in SUPPORTED_AUTHORITY_MODES, "AUTHORITY_MODE_NOT_SUPPORTED",
                 self.authority_mode.value)
        _require(_in_day(self.evaluation_as_of, self.authority_day), "EVALUATION_OUTSIDE_AUTHORITY_DAY",
                 "evaluation_as_of")

    def as_dict(self) -> Dict[str, Any]:
        return {"authority_day": self.authority_day.isoformat(), "authority_mode": self.authority_mode.value,
                "bindings": {"eligibility_rules_version": LIVE_RULES_VERSION,
                             "orchestration_rules_version": ORCHESTRATION_RULES_VERSION,
                             "result_set_rules_version": RESULT_SET_RULES_VERSION,
                             "result_set_schema_version": RESULT_SET_SCHEMA_VERSION,
                             "set_summary_rules_version": SET_SUMMARY_RULES_VERSION,
                             "summary_rules_version": SUMMARY_RULES_VERSION,
                             "universe_rules_version": UNIVERSE_RULES_VERSION},
                "evaluation_as_of": self.evaluation_as_of.astimezone(day_start_jst(self.authority_day).tzinfo)
                .isoformat(), "policy_id": self.policy_id, "policy_version": self.policy_version,
                "routing_rule": ROUTING_RULE, "rules_version": RUN_RULES_VERSION,
                "schema_version": RUN_SCHEMA_VERSION, "universe_id": self.universe_id,
                "universe_members": list(self.universe_members), "universe_version": self.universe_version,
                "work_order_rule": WORK_ORDER_RULE}

    @property
    def run_id(self) -> str:
        digest = hashlib.sha256(canonical_json(self.as_dict()).encode("utf-8")).hexdigest()
        return f"{RUN_ID_PREFIX}_{digest[:24]}"


# ---------------------------------------------------------------- 台帳（追記専用 ・hash の鎖 ・修復しない）


def ledger_path(root: Path, run_id: str) -> Path:
    return root / "screener_intelligence" / LEDGER_DIRNAME / f"{run_id}.jsonl"


def _event_digest(event: Mapping[str, Any]) -> str:
    body = {key: value for key, value in event.items() if key != "digest"}
    return hashlib.sha256(canonical_json(body).encode("utf-8")).hexdigest()


@dataclass
class LedgerState:
    """台帳から再構成した運用の状態（不変条件を検査済み）。"""

    spec: Dict[str, Any]
    events: List[Dict[str, Any]]
    invocations: List[Dict[str, Any]]
    open_invocation: Optional[int]
    assessed: Optional[Dict[str, Any]]
    attempts: Dict[str, Dict[str, Any]]
    last_digest: str
    size: int

    @property
    def cumulative_requests(self) -> int:
        return sum(inv["requests_used"] for inv in self.invocations if inv.get("requests_used") is not None)

    @property
    def last_acquired_at(self) -> Optional[datetime]:
        return datetime.fromisoformat(self.invocations[-1]["acquired_at"]) if self.invocations else None

    @property
    def last_exhausted(self) -> bool:
        return bool(self.invocations) and bool(self.invocations[-1].get("budget_exhausted"))


def _corrupt(code: str, line: int) -> ScreenRunError:
    return ScreenRunError(f"LEDGER_{code}", f"line {line}")


def load_ledger(path: Path, run_id: str) -> LedgerState:
    """全行を検査して状態を再構成する（形 ・digest ・鎖 ・順の番号 ・遷移）。違えば fail closed（修復 ・切り詰め ・上書きしない）。"""
    _require(path.is_file(), "LEDGER_MISSING", "run_id")
    data = path.read_bytes()
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        raise _corrupt("INVALID_ENCODING", 0) from None
    if text and not text.endswith("\n"):
        raise _corrupt("TRUNCATED_FINAL_LINE", text.count("\n") + 1)
    state = LedgerState(spec={}, events=[], invocations=[], open_invocation=None, assessed=None, attempts={},
                        last_digest="", size=len(data))
    for number, body in enumerate(text.split("\n")[:-1] if text else (), 1):
        try:
            event = json.loads(body)
        except ValueError:
            raise _corrupt("INVALID_RECORD", number) from None
        if not isinstance(event, dict) or set(event) != {"digest", "event", "payload", "prev_digest", "run_id",
                                                           "schema_version", "seq"}:
            raise _corrupt("INVALID_RECORD", number)
        if canonical_json(event) != body:
            raise _corrupt("NON_CANONICAL_LINE", number)
        if event["digest"] != _event_digest(event):
            raise _corrupt("DIGEST_MISMATCH", number)
        if event["prev_digest"] != state.last_digest or event["seq"] != number or event["run_id"] != run_id \
                or event["schema_version"] != LEDGER_SCHEMA_VERSION or event["event"] not in EVENT_KINDS:
            raise _corrupt("CHAIN_BROKEN", number)
        _apply(state, event, number)
        state.events.append(event)
        state.last_digest = event["digest"]
    _require(state.spec != {}, "LEDGER_EMPTY", "run_id")
    return state


def _apply(state: LedgerState, event: Mapping[str, Any], number: int) -> None:
    """1 つの event の遷移の検査（不可能な遷移 ・欠けた前提の event は fail closed）。"""
    kind, payload = event["event"], event["payload"]
    if kind == "RUN_STARTED":
        if number != 1 or not isinstance(payload, dict) or "spec" not in payload:
            raise _corrupt("IMPOSSIBLE_TRANSITION", number)
        state.spec = payload["spec"]
        return
    if not state.spec:
        raise _corrupt("MISSING_PRIOR_EVENT", number)
    if kind == "INVOCATION_STARTED":
        if state.open_invocation is not None or payload.get("invocation") != len(state.invocations) + 1:
            raise _corrupt("IMPOSSIBLE_TRANSITION", number)
        acquired = datetime.fromisoformat(payload["acquired_at"])
        if state.last_acquired_at is not None and acquired < state.last_acquired_at:
            raise _corrupt("IMPOSSIBLE_TRANSITION", number)
        state.invocations.append(dict(payload))
        state.open_invocation = payload["invocation"]
        return
    if state.open_invocation is None:
        raise _corrupt("MISSING_PRIOR_EVENT", number)                            # 呼び出しの外の event
    if kind == "MEMBERS_ASSESSED":
        members = [m.get("code") for m in payload.get("members", [])]
        if state.assessed is not None or members != state.spec["universe_members"]:
            raise _corrupt("IMPOSSIBLE_TRANSITION", number)
        state.assessed = dict(payload)
        return
    if kind == "ISSUER_ATTEMPTED":
        if state.assessed is None:
            raise _corrupt("MISSING_PRIOR_EVENT", number)
        routes = [r["issuer_id"] for r in state.assessed["routes"]]
        issuer_id = payload.get("issuer_id")
        pending = [i for i in routes if i not in state.attempts]
        if not pending or issuer_id != pending[0] or payload.get("invocation") != state.open_invocation \
                or payload.get("status") not in (AUTHORITY_BUILT, ACQUISITION_FAILED):
            raise _corrupt("IMPOSSIBLE_TRANSITION", number)                      # 宣言の順の次の発行体だけ ・1 回だけ
        state.attempts[issuer_id] = dict(payload)
        return
    if payload.get("invocation") != state.open_invocation or not isinstance(payload.get("requests_used"), int):
        raise _corrupt("IMPOSSIBLE_TRANSITION", number)                          # INVOCATION_ENDED
    state.invocations[-1].update(payload)
    state.open_invocation = None


class LedgerWriter:
    """追記だけ（write → flush → fsync）。外部の変更は byte 長で検知する。上書き ・削除 ・修復は無い。"""

    def __init__(self, path: Path, state: LedgerState) -> None:
        self.path, self.state = path, state

    def append(self, kind: str, payload: Mapping[str, Any]) -> None:
        _require(self.path.stat().st_size == self.state.size, "LEDGER_CONCURRENT_MODIFICATION", "ledger")
        event = {"event": kind, "payload": dict(payload), "prev_digest": self.state.last_digest,
                 "run_id": self.path.stem, "schema_version": LEDGER_SCHEMA_VERSION, "seq": len(self.state.events) + 1}
        event["digest"] = _event_digest(event)
        _apply(self.state, event, event["seq"])
        line = (canonical_json(event) + "\n").encode("utf-8")
        with self.path.open("ab") as handle:
            handle.write(line)
            handle.flush()
            os.fsync(handle.fileno())
        self.state.events.append(event)
        self.state.last_digest = event["digest"]
        self.state.size += len(line)


def _create_ledger(path: Path, spec: ScreenRunSpec) -> LedgerWriter:
    _require(not path.exists(), "RUN_ALREADY_STARTED", "run_id")                # 継続は `continue` で明示する
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("ab"):
        pass
    state = LedgerState(spec={}, events=[], invocations=[], open_invocation=None, assessed=None, attempts={},
                        last_digest="", size=0)
    writer = LedgerWriter(path, state)
    writer.append("RUN_STARTED", {"spec": spec.as_dict()})
    return writer


# ---------------------------------------------------------------- 明示の authority の解決（provider の仕事の前）


def resolve_universe(root: Path, *, universe_id: Optional[str], universe_key: Optional[str],
                     universe_version: Optional[int]) -> UniverseAuthorityRecord:
    by_id = universe_id is not None
    by_key = universe_key is not None or universe_version is not None
    _require(by_id != by_key, "UNIVERSE_SELECTOR_INVALID", "exactly one of universe_id or key+version")
    _require(not by_key or (isinstance(universe_key, str) and type(universe_version) is int),
             "UNIVERSE_SELECTOR_INVALID", "key+version")
    report = UniverseAuthorityStore.validate(root)
    _require(report.status is IntegrityStatus.OK, "UNIVERSE_AUTHORITY_UNAVAILABLE", report.failure_code)
    store = UniverseAuthorityStore.open(root, read_only=True)
    record = store.get_by_universe_id(universe_id) if by_id else store.get_by_key_version(universe_key,
                                                                                            universe_version)
    _require(record is not None, "UNIVERSE_NOT_FOUND", "selector")
    return record


def resolve_run_policy(root: Path, selector: PolicySelector) -> Any:
    try:
        return resolve_policy(open_verified_store(root), selector)
    except PolicyEvaluationError as exc:
        raise ScreenRunError("POLICY_AUTHORITY_UNAVAILABLE", f"{exc.failure.value}:{exc.code}") from None


def _store_integrity(root: Path) -> None:
    """authority の store を検査し（破損は network の前に fail closed）、無い運用の store だけを空で作る。identity は必須。"""
    for name, opener in (("identity", IdentityStore.open), ("observation", ObservationStore.open),
                         ("semantic_metadata", SemanticMetadataStore.open), ("held", HeldObservationStore.open),
                         ("acquisition_events", AcquisitionEventStore.open), ("manifests", ManifestStore.open),
                         ("provider_holdings", ProviderHoldingsStore.open)):
        try:
            opener(root, read_only=True)
        except _STORE_ERRORS as exc:
            missing = exc.code in ("AUTHORITY_MISSING", "STORE_MISSING", "IDENTITY_AUTHORITY_MISSING")
            _require(missing and name != "identity", "AUTHORITY_STORE_UNAVAILABLE", f"{name}:{exc.code}")
    ObservationStore.initialize(root)
    SemanticMetadataStore.initialize(root)
    HeldObservationStore.initialize(root)
    AcquisitionEventStore.initialize(root)
    ManifestStore.initialize(root)
    ProviderHoldingsStore.initialize(root)


# ---------------------------------------------------------------- 1 呼び出しの仕事


def _assess_members(spec: ScreenRunSpec, master: Any, root: Path) -> Dict[str, Any]:
    """master の判定（凍結 LIVE1）と審査済みの identity（凍結 A1 の resolver。評価の瞬間）。値 ・名前は持たない。"""
    by_code: Dict[str, List[Any]] = {}
    for result in master.results:
        by_code.setdefault(result.code, []).append(result)
    history = IdentityStore.open(root, read_only=True).history
    members, routes, seen = [], [], set()
    for code in spec.universe_members:
        rows = by_code.get(code, [])
        if len(rows) != 1:
            members.append({"code": code, "issuer_id": None, "kind": MemberOutcomeKind.NOT_ELIGIBLE.value,
                            "reason_codes": ["NOT_IN_MASTER_SNAPSHOT" if not rows else "MASTER_ROW_AMBIGUOUS"]})
            continue
        if rows[0].eligibility is not MasterEligibility.ELIGIBLE_FOR_ID1:
            reasons = sorted({r.value for r in rows[0].reasons} | {f"MASTER_{rows[0].eligibility.value}"})
            members.append({"code": code, "issuer_id": None, "kind": MemberOutcomeKind.NOT_ELIGIBLE.value,
                            "reason_codes": reasons})
            continue
        found = resolve(history, IdentityQuery(kind=QueryKind.IDENTIFIER, scheme=IdentifierScheme.JQUANTS_CODE,
                                               value=code), cutoff=spec.evaluation_as_of)
        if found.status is not ResolutionStatus.FOUND or found.security is None:
            members.append({"code": code, "issuer_id": None, "kind": MemberOutcomeKind.IDENTITY_UNRESOLVED.value,
                            "reason_codes": [f"IDENTITY_{found.status.value}"]})
            continue
        issuer_id = found.security.issuer_id
        members.append({"code": code, "issuer_id": issuer_id, "kind": "RESOLVED", "reason_codes": []})
        if issuer_id not in seen:                                                # 取得の経路だけ（主ではない）
            seen.add(issuer_id)
            routes.append({"issuer_id": issuer_id, "route_code": code})
    return {"members": members, "routes": routes, "snapshot_date": spec.authority_day.isoformat()}


def _acquire_issuer(root: Path, client: JQuantsLiveClient, route: Mapping[str, str], acquired_at: datetime,
                    invocation: int) -> Dict[str, Any]:
    """1 発行体: 1 つの fins の request → 凍結 ACQ0 → EXE-R → manifest → F1。page は追わない ・retry しない。"""
    attempt = {"invocation": invocation, "issuer_id": route["issuer_id"], "reason_codes": [],
               "route_code": route["route_code"], "status": ACQUISITION_FAILED}
    try:
        handoff = verify_identity_for_code(IdentityStore.open(root, read_only=True).history, route["route_code"])
    except LiveInputError as exc:
        attempt["reason_codes"] = [f"IDENTITY_HANDOFF_{exc.code}"]
        return attempt
    try:
        fins = client.fetch_fins_summary(handoff)
    except LiveInputError as exc:
        attempt["reason_codes"] = [f"FINS_{exc.code}"]
        return attempt
    attempt["request_index"] = fins.request_index
    rows = [row.supported_values() for row in fins.rows]
    try:
        content = bounded_content_digest(FINS_SUMMARY_PATH, rows)
        status = AcquisitionStatus.PARTIAL_PAGINATED if fins.pagination_key else AcquisitionStatus.COMPLETE
        event = AcquisitionEvent(provider=SourceClass.JQUANTS,
                                 scope=RequestScope.of(FINS_SUMMARY_PATH, {"code": route["route_code"]}),
                                 acquired_at=acquired_at, status=status, row_count=content.row_count,
                                 pagination_key_present=bool(fins.pagination_key), pages_followed=1,
                                 content_digest=content.digest, failure_code="")
    except AcquisitionModelError as exc:
        attempt["reason_codes"] = [f"ACQUISITION_{exc.code}"]
        return attempt
    try:
        AcquisitionEventStore.open(root).append(event)
        if event.status is not AcquisitionStatus.COMPLETE:
            attempt["reason_codes"] = ["PAGINATION_NOT_FOLLOWED"]                # 追わない ・authority を作らない
            return attempt
        results = [execute_financial_summary_row(row, AdapterContext(issuer_id=handoff.issuer_id,
                                                                     acquired_at=acquired_at), root) for row in rows]
        built = build_manifest(event=event, rows=rows, results=results,
                               history=ObservationStore.open(root, read_only=True).history,
                               held_view=HeldObservationStore.open(root, read_only=True), subject_id=handoff.issuer_id)
        if built.outcome is ManifestOutcome.BUILT:
            built = record_manifest(built, ManifestStore.open(root))
        if built.outcome not in (ManifestOutcome.APPENDED, ManifestOutcome.REUSED):
            attempt["reason_codes"] = [f"MANIFEST_{built.outcome.value}"]
            return attempt
        holdings = execute_provider_holdings(event=event, manifests=ManifestStore.open(root, read_only=True),
                                             history=ObservationStore.open(root, read_only=True).history,
                                             store=ProviderHoldingsStore.open(root))
    except _STORE_ERRORS as exc:
        _require(exc.category.value not in _WHOLE_RUN_CATEGORIES, "AUTHORITY_STORE_FAILURE", exc.code)
        attempt["reason_codes"] = [f"STORE_{exc.code}"]
        return attempt
    if holdings.status not in _BUILT_STATUSES:
        attempt["reason_codes"] = [f"HOLDINGS_{holdings.status.value}"]
        return attempt
    attempt["status"] = AUTHORITY_BUILT
    attempt["reason_codes"] = [] if holdings.authoritative else [f"HOLDINGS_{holdings.status.value}"]
    return attempt


# ---------------------------------------------------------------- 全結果の組み立て（毎回 ・決定論 ・保存しない）


def _semantics_lookup(root: Path) -> Dict[str, ObservationSemantics]:
    journal = SemanticMetadataStore.open(root, read_only=True).journal
    return {r.observation_id: r for r in journal.records if isinstance(r, ObservationSemantics)}


def assemble(root: Path, spec: ScreenRunSpec, state: LedgerState) -> ScreenResultSet:
    """台帳（運用の状態）＋ authority の store → 凍結 B4A の評価 → 凍結 B5B の全結果。B4A ／ B5B の失敗は run 全体の失敗。"""
    outcomes: Dict[str, MemberOutcome] = {}
    if state.assessed is None:
        for code in spec.universe_members:
            outcomes[code] = MemberOutcome(member_code=code, kind=MemberOutcomeKind.NOT_ATTEMPTED,
                                           reason_codes=("MASTER_NOT_ASSESSED",))
        return _build(spec, outcomes, [])
    selector = PolicySelector(policy_id=spec.policy_id)
    issuer_results: List[IssuerResult] = []
    built = [i for i, a in state.attempts.items() if a["status"] == AUTHORITY_BUILT]
    if built:
        inputs = EvaluationInputs(history=ObservationStore.open(root, read_only=True).history,
                                  semantics=_semantics_lookup(root),
                                  holdings=ProviderHoldingsStore.open(root, read_only=True),
                                  manifests=ManifestStore.open(root, read_only=True),
                                  corrections=CorrectionHistory(IdentityStore.open(root, read_only=True).history))
        for issuer_id in built:
            context = EvaluationContext(subject_id=issuer_id, evaluation_as_of=spec.evaluation_as_of,
                                        identity_valid_at=spec.evaluation_as_of, authority_mode=spec.authority_mode,
                                        policy_id=spec.policy_id)
            try:
                outcome = evaluate_selected_policy(root, selector, context, inputs)
            except PolicyEvaluationError as exc:
                raise ScreenRunError("EVALUATION_ORCHESTRATION_FAILED", f"{exc.failure.value}:{exc.code}") from None
            issuer_results.append(IssuerResult(issuer_id=issuer_id, evaluation=project_safe_summary(outcome.result)))
    for member in state.assessed["members"]:
        code, issuer_id = member["code"], member["issuer_id"]
        if member["kind"] != "RESOLVED":
            outcomes[code] = MemberOutcome(member_code=code, kind=MemberOutcomeKind(member["kind"]),
                                           reason_codes=tuple(sorted(member["reason_codes"])))
            continue
        attempt = state.attempts.get(issuer_id)
        if attempt is None:                                                      # 未終端: 予算の延期 ／ まだ試みていない
            deferred = state.last_exhausted
            outcomes[code] = MemberOutcome(
                member_code=code,
                kind=MemberOutcomeKind.BUDGET_DEFERRED if deferred else MemberOutcomeKind.NOT_ATTEMPTED,
                reason_codes=("BUDGET_EXHAUSTED",) if deferred else ("NOT_YET_ATTEMPTED",))
        elif attempt["status"] == AUTHORITY_BUILT:
            outcomes[code] = MemberOutcome(member_code=code, kind=MemberOutcomeKind.EVALUATED, issuer_id=issuer_id)
        else:
            outcomes[code] = MemberOutcome(member_code=code, kind=MemberOutcomeKind.ACQUISITION_FAILED,
                                           reason_codes=tuple(sorted(attempt["reason_codes"])))
    return _build(spec, outcomes, issuer_results)


def _build(spec: ScreenRunSpec, outcomes: Mapping[str, MemberOutcome], issuers: List[IssuerResult]) -> ScreenResultSet:
    try:
        return assemble_result_set(universe_id=spec.universe_id, universe_version=spec.universe_version,
                                   universe_members=spec.universe_members, policy_id=spec.policy_id,
                                   policy_version=spec.policy_version, authority_mode=spec.authority_mode,
                                   authority_day=spec.authority_day, evaluation_as_of=spec.evaluation_as_of,
                                   member_outcomes=outcomes, issuer_results=issuers)
    except ResultSetError as exc:
        raise ScreenRunError("RESULT_ASSEMBLY_FAILED", exc.code) from None


# ---------------------------------------------------------------- 実行（開始 ／ 継続）


@dataclass(frozen=True)
class ScreenRunOutcome:
    """呼び出しの結果: private の全結果（memory だけ）・凍結 B5B の安全な投影 ・運用の状態。"""

    run_id: str
    result: ScreenResultSet
    safe_summary: SafeScreenSetSummary
    run_status: Dict[str, Any]


def execute_screen(*, data_root: Any, transport: Any, d0: Any, evaluation_as_of: Any, authority_mode: Any,
                   acquired_at: Any, universe_id: Optional[str] = None, universe_key: Optional[str] = None,
                   universe_version: Optional[int] = None, policy_id: Optional[str] = None,
                   policy_key: Optional[str] = None, policy_version: Optional[int] = None,
                   continue_run_id: Optional[str] = None, budget_limit: int = PILOT_MAX_REQUESTS) -> ScreenRunOutcome:
    """開始（`continue_run_id` なし）か継続（同じ引数 ＋ `continue_run_id`）。不一致 ・破損は network の前に fail closed。"""
    root = validate_data_root(data_root)
    _require(isinstance(transport, Transport), "TRANSPORT_INVALID", "transport")
    day = _day(d0)
    evaluation = _aware(evaluation_as_of, "evaluation_as_of")
    acquisition = _aware(acquired_at, "acquired_at")
    try:
        mode = ScreenerAuthorityMode(authority_mode)
    except ValueError:
        raise ScreenRunError("AUTHORITY_MODE_INVALID", "authority_mode") from None
    _require(mode in SUPPORTED_AUTHORITY_MODES, "AUTHORITY_MODE_NOT_SUPPORTED", mode.value)   # 方針より先に（fallback なし）
    _require(_in_day(acquisition, day), "ACQUISITION_OUTSIDE_AUTHORITY_DAY", "acquired_at")
    _require(acquisition <= evaluation, "ACQUISITION_AFTER_EVALUATION_INSTANT", "acquired_at")
    _require(type(budget_limit) is int and 1 <= budget_limit <= PILOT_MAX_REQUESTS, "BUDGET_INVALID", "budget_limit")
    universe = resolve_universe(root, universe_id=universe_id, universe_key=universe_key,
                                universe_version=universe_version)
    try:
        selector = PolicySelector(policy_id=policy_id, policy_key=policy_key, version=policy_version)
    except PolicyEvaluationError as exc:
        raise ScreenRunError("POLICY_SELECTOR_INVALID", exc.code) from None
    policy = resolve_run_policy(root, selector).policy
    _require(policy.authority_mode is mode, "POLICY_AUTHORITY_MODE_MISMATCH", mode.value)
    spec = ScreenRunSpec(universe_id=universe.universe.universe_id, universe_version=universe.version,
                         universe_members=universe.universe.members, policy_id=policy.policy_id,
                         policy_version=policy.version, authority_mode=mode, authority_day=day,
                         evaluation_as_of=evaluation)
    path = ledger_path(root, spec.run_id)
    if continue_run_id is None:
        _store_integrity(root)
        writer = _create_ledger(path, spec)
    else:
        _require(continue_run_id == spec.run_id, "RUN_SPEC_MISMATCH", "run_id")   # Universe ・方針 ・日 ・mode ・瞬間の変更
        state = load_ledger(path, spec.run_id)
        _require(state.spec == spec.as_dict(), "RUN_SPEC_MISMATCH", "spec")
        _require(state.open_invocation is None, "LEDGER_OPEN_INVOCATION", "run_id")   # 中断の後は修復しない
        if state.last_acquired_at is not None:
            _require(acquisition >= state.last_acquired_at, "ACQUISITION_INSTANT_REGRESSED", "acquired_at")
        _store_integrity(root)
        writer = LedgerWriter(path, state)
    state = writer.state
    pending = state.assessed is None or any(r["issuer_id"] not in state.attempts for r in state.assessed["routes"])
    used, exhausted = 0, False
    if pending:
        invocation = len(state.invocations) + 1
        writer.append("INVOCATION_STARTED", {"acquired_at": _iso(acquisition), "budget_limit": budget_limit,
                                             "invocation": invocation})
        budget = RequestBudget(budget_limit)
        client = JQuantsLiveClient(transport, budget)
        master_failure = ""
        if state.assessed is None:                                               # 1 run に 1 回（D0 の snapshot）
            try:
                master = client.fetch_master(day.isoformat())
            except LiveInputError as exc:
                master_failure = exc.code
            else:
                writer.append("MEMBERS_ASSESSED", _assess_members(spec, master, root))
        if state.assessed is not None:
            for route in state.assessed["routes"]:
                if route["issuer_id"] in state.attempts:
                    continue
                if budget.remaining == 0:
                    exhausted = True                                             # 予算は迂回しない ・次の呼び出しへ
                    break
                writer.append("ISSUER_ATTEMPTED", _acquire_issuer(root, client, route, acquisition, invocation))
        used = budget.used
        writer.append("INVOCATION_ENDED", {"budget_exhausted": exhausted, "invocation": invocation,
                                           "master_failure": master_failure, "paths": list(budget.paths),
                                           "requests_used": used})
    result = assemble(root, spec, state)
    status = {"cumulative_requests": state.cumulative_requests, "execution_completeness":
              result.execution_completeness.value, "invocation_count": len(state.invocations),
              "master_assessed": state.assessed is not None, "requests_used": used, "run_id": spec.run_id}
    return ScreenRunOutcome(run_id=spec.run_id, result=result, safe_summary=project_safe_set_summary(result),
                            run_status=status)


# ---------------------------------------------------------------- CLI（本人の環境でだけ）


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="p8_screen_local", description="P8 private multi-issuer screen (local only)")
    parser.add_argument("command", choices=("start", "continue"))
    parser.add_argument("--data-root", required=True)
    parser.add_argument("--d0", required=True)
    parser.add_argument("--evaluation-as-of", required=True, help="explicit aware instant on D0 (JST day)")
    parser.add_argument("--acquired-at", required=True, help="explicit aware instant of this invocation")
    parser.add_argument("--authority-mode", required=True)
    parser.add_argument("--universe-id", default=None)
    parser.add_argument("--universe-key", default=None)
    parser.add_argument("--universe-version", default=None, type=int)
    parser.add_argument("--policy-id", default=None)
    parser.add_argument("--policy-key", default=None)
    parser.add_argument("--policy-version", default=None, type=int)
    parser.add_argument("--run-id", default=None, help="continue: the exact run_id printed by start")
    parser.add_argument("--budget-limit", default=PILOT_MAX_REQUESTS, type=int)
    parser.add_argument("--credential-env", default=DEFAULT_CREDENTIAL_ENV)
    return parser


def main(argv: Optional[List[str]] = None) -> int:
    args = _parser().parse_args(argv)
    if args.command == "continue" and not args.run_id:
        sys.stdout.write(json.dumps({"state": "FAILED", "code": "RUN_ID_REQUIRED", "detail": "run_id"}) + "\n")
        return 2
    if not (os.environ.get(args.credential_env) or "").strip():                 # network の前に。値は読むだけで出さない
        sys.stdout.write(json.dumps({"state": "FAILED", "code": "CREDENTIAL_MISSING", "detail": "credential_env"})
                         + "\n")
        return 2
    try:
        transport = LocalHttpsTransport(credential_env=args.credential_env)
        outcome = execute_screen(data_root=args.data_root, transport=transport,
                                 d0=args.d0, evaluation_as_of=args.evaluation_as_of, acquired_at=args.acquired_at,
                                 authority_mode=args.authority_mode, universe_id=args.universe_id,
                                 universe_key=args.universe_key, universe_version=args.universe_version,
                                 policy_id=args.policy_id, policy_key=args.policy_key,
                                 policy_version=args.policy_version,
                                 continue_run_id=args.run_id if args.command == "continue" else None,
                                 budget_limit=args.budget_limit)
    except (ScreenRunError, LiveInputError) as exc:
        sys.stdout.write(json.dumps({"state": "FAILED", "code": exc.code, "detail": exc.detail}) + "\n")
        return 2
    report = {"run": outcome.run_status, "screen": outcome.safe_summary.as_dict()}   # 安全な投影 ＋ 運用の状態だけ
    sys.stdout.write(json.dumps(report, ensure_ascii=False, sort_keys=True, indent=2) + "\n")
    return 0


if __name__ == "__main__":                                                       # pragma: no cover
    raise SystemExit(main())
