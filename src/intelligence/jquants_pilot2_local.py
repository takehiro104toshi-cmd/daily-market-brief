"""P8-PILOT2A — 本人の環境でだけ動かす、2 段の PILOT2 runner（prepare → 人の審査 → execute）。

この module は本番の runtime から import されない（guard）。cron ・workflow ・背景の実行は無い。実の J-Quants への実行は監督の承認の後の
PILOT2 で、本人の private ／ local な環境でだけ authorize される（凍結 LIVE0 ・LIVE2）。凍結の層（LIVE2 transport ・LIVE1 client ／ 適格 ／
予算 ・ID1 ・ID2 ・A1 ・ADP0 ・EXE ・A3A ／ A3B）をそのまま呼び、意味を複製しない。

段 1 `prepare`: master の取得（request 1）→ LIVE1 の適格 → 要求した code だけを選ぶ → 凍結 ID1 の提案 → **人の審査の packet** と
**判断の template** を private の data root に書いて **止まる**。fins ・ID2 ・A1 ・A2 ・指標には触れない。自動の承認は無い。
段 2 `execute`: packet と人の判断（APPROVE ／ REJECT ／ DEFER ＋ aware な `accepted_at`）を読み、凍結 ID1 を再導出して digest を照合し、
凍結 ID2 で登録 → A1 で identity を確認 → 登録できた承認済みの発行体だけ fins を取得（request 2〜）→ 凍結 ADP0 ・EXE → 凍結 A3 の 4 指標
（値は保存しない）→ **安全な要約**（会社名 ・code ・財務の値 ・raw ・journal の内容を含まない）を書く。

request の予算は 2 段を通して最大 8（`budget_state.json` に回数と path だけを保存。reset しない。9 回目は transport に届かない）。
raw の応答は保存しない。data root は repo ・`.git` ・GitHub の workspace の中を拒む。journal の削除 ・修復はしない（再実行は凍結の
ID2 ・EXE の再利用で収束する）。

記録: `docs/databank/PHASE8_PILOT2A_LOCAL_RUNNER.md`。

P8-PILOT2B（監督の決定 D-P2B-1〜5）: `execute --acquired-at <aware ISO8601>` を渡した時だけ、fins の handoff から凍結 ACQ0 の取得 event
（COMPLETE ／ PARTIAL_PAGINATED）→ 凍結 EXE（`AdapterContext.acquired_at` ＝ その瞬間。EXE-R の知識の規則は EXE が決める）→ 凍結 EPOCH1R の
manifest → 凍結 F1 の保持 record → 凍結 A3-RA の 4 指標（`authority_as_of` ＝ `identity_valid_at` ＝ `acquired_at`）を composition する。
runner は時計を読まない ・式を持たない ・値を書かない。`--acquired-at` を省けば PILOT2A の経路のまま（取得の authority は作らない）。
記録: `docs/databank/PHASE8_PILOT2B_PRIVATE_RETROSPECTIVE_E2E.md`。
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Tuple

from .jquants_local_transport import DEFAULT_CREDENTIAL_ENV, LocalHttpsTransport
from .screener_intelligence.acquisition_event_model import (AcquisitionEvent, AcquisitionModelError, AcquisitionStatus,
                                                            RequestScope, bounded_content_digest)
from .screener_intelligence.acquisition_event_store import AcquisitionEventStore, AcquisitionStoreError
from .screener_intelligence.acquisition_manifest_builder import ManifestOutcome, build_manifest, record_manifest
from .screener_intelligence.acquisition_manifest_store import ManifestStore, ManifestStoreError
from .screener_intelligence.fundamental_metrics import operating_margin, revenue_growth
from .screener_intelligence.fundamental_metrics_extended import net_margin, roa_point_in_time
from .screener_intelligence.held_observation_store import HeldObservationStore
from .screener_intelligence.identity_bootstrap import BootstrapPlanError, propose_bootstrap, review_manifest
from .screener_intelligence.identity_correction_model import CorrectionHistory
from .screener_intelligence.identity_model import SourceClass
from .screener_intelligence.identity_bootstrap_model import (BootstrapBatch, BootstrapInputError, MasterRow,
                                                             ProposalReview, ReviewDisposition)
from .screener_intelligence.identity_registration_executor import execute_identity_registration
from .screener_intelligence.identity_registration_model import RegistrationOutcome, WriteState
from .screener_intelligence.identity_store import IdentityStore, IdentityStoreError
from .screener_intelligence.jquants_adapter_model import AdapterContext
from .screener_intelligence.jquants_execution_model import ExecutionOutcome
from .screener_intelligence.jquants_financial_summary_executor import execute_financial_summary_row
from .screener_intelligence.jquants_live_client import JQuantsLiveClient, verify_identity_for_code
from .screener_intelligence.jquants_live_model import (FINS_SUMMARY_PATH, PILOT_MAX_REQUESTS, LiveInputError,
                                                       MasterEligibility, RequestBudget, Transport)
from .screener_intelligence.jquants_master_ingress import id1_rows
from .screener_intelligence.metric_model import MetricKind
from .screener_intelligence.observation_model import FundamentalActual, PeriodBasis, StatementBasis
from .screener_intelligence.observation_semantics_model import ObservationSemantics
from .screener_intelligence.observation_store import ObservationStore, ObservationStoreError
from .screener_intelligence.provider_holdings_executor import HoldingsExecutionStatus, execute_provider_holdings
from .screener_intelligence.provider_holdings_store import HoldingsStoreError, ProviderHoldingsStore
from .screener_intelligence.retrospective_metric_resolver import (RESOLUTION_MODE, RetrospectiveMetricStatus,
                                                                  resolve_retrospective_metric)
from .screener_intelligence.screener_criteria_model import EvaluationContext, ScreenerModelError
from .screener_intelligence.screener_evaluator import EvaluationInputs
from .screener_intelligence.screener_policy_evaluation import (PolicyEvaluationError, PolicySelector,
                                                               evaluate_selected_policy, open_verified_store,
                                                               resolve_policy)
from .screener_intelligence.screener_result_summary import project_safe_summary
from .screener_intelligence.semantic_metadata_store import SemanticMetadataStore, SemanticMetadataStoreError
from .screener_intelligence.held_observation_store import HeldStoreError

PILOT_RULES_VERSION = "p8_pilot2_local_runner:0.1.0"
PACKET_SCHEMA = "p8_pilot2_review_packet:0.1.0"
DECISION_SCHEMA = "p8_pilot2_human_decision:0.1.0"
BUDGET_SCHEMA = "p8_pilot2_budget_state:0.1.0"
SUMMARY_SCHEMA = "p8_pilot2_safe_summary:0.1.0"
PILOT_DIRNAME = "pilot2"
PACKET_FILENAME = "review_packet.json"
DECISION_TEMPLATE_FILENAME = "decision_template.json"
DECISION_FILENAME = "decision.json"
BUDGET_FILENAME = "budget_state.json"
SUMMARY_FILENAME = "safe_summary.json"
#: PILOT2B: 取得の authority の要約の schema ・acquired_at の resume の結び付き（hash だけ。code ・値は無い）
AUTHORITY_SCHEMA = "p8_pilot2b_acquisition_authority:0.1.0"
ACQUISITION_STATE_SCHEMA = "p8_pilot2b_acquisition_state:0.1.0"
ACQUISITION_STATE_FILENAME = "acquisition_state.json"
#: B4B: 安全な要約の Screener の節（明示の選択子が無ければ NOT_REQUESTED のまま。結果は derived で保存しない）
SCREENER_SECTION_SCHEMA = "p8_pilot2b_screener_section:0.1.0"
SCREENER_SECTION_STATES: Tuple[str, ...] = ("NOT_REQUESTED", "REQUESTED", "FAILED")
RETROSPECTIVE_METRICS: Tuple[MetricKind, ...] = (MetricKind.REVENUE_GROWTH, MetricKind.OPERATING_MARGIN,
                                                 MetricKind.NET_MARGIN, MetricKind.ROA_POINT_IN_TIME)
#: A3 が支える target の期間の種類（単独の四半期 ・4Q ・OtherPeriod は無い）
SUPPORTED_TARGET_BASES: Tuple[PeriodBasis, ...] = (PeriodBasis.FISCAL_YEAR, PeriodBasis.CUMULATIVE_YEAR_TO_DATE)
#: 凍結 A3 の期間の関係の理由（売上成長率の comparable な prior の判定は凍結 A3-RA の結果の理由で読む。式は持たない）
PERIOD_RELATION_CODES: Tuple[str, ...] = ("PERIOD_BASIS_UNSUPPORTED", "FISCAL_YEAR_IRREGULAR", "PERIOD_BASIS_MISMATCH",
                                          "PERIOD_QUARTER_DIFFERS", "PERIOD_NOT_ADJACENT")
_AUTHORITY_FAILURES = (RetrospectiveMetricStatus.AUTHORITY_FAILURE, RetrospectiveMetricStatus.AMBIGUOUS_AUTHORITY,
                       RetrospectiveMetricStatus.INVALID_INPUT)
SUPPORTED_MARKETS: Tuple[str, ...] = ("0111", "0112", "0113")
DEFAULT_BATCH_ID = "p8boot1"
MAX_TARGET_CODES = 3
PILOT_BASIS = StatementBasis.CONSOLIDATED
_CODE_RE = re.compile(r"^[0-9]{4}0$")
_DATE_RE = re.compile(r"^[0-9]{4}-[0-9]{2}-[0-9]{2}$")
_REPO_ROOT = Path(__file__).resolve().parents[2]


class PilotError(ValueError):
    """runner の拒否（fail closed）。code と field 名だけ。値 ・本文 ・path の全文は運ばない。"""

    def __init__(self, code: str, detail: str = "") -> None:
        super().__init__(f"{code}: {detail}" if detail else code)
        self.code = code
        self.detail = detail


def _require(condition: bool, code: str, detail: str = "") -> None:
    if not condition:
        raise PilotError(code, detail)


# ---------------------------------------------------------------- private data root


def validate_data_root(value: Any) -> Path:
    """明示の private な data root。repo ・`.git` ・GitHub の workspace ・Actions の中は拒む。"""
    _require(isinstance(value, (str, Path)) and str(value).strip() != "", "DATA_ROOT_REQUIRED", "data_root")
    root = Path(value).expanduser()
    _require(root.is_absolute(), "DATA_ROOT_NOT_ABSOLUTE", "data_root")
    resolved = root.resolve()
    _require(".git" not in resolved.parts, "DATA_ROOT_INSIDE_GIT", "data_root")
    _require(_REPO_ROOT not in resolved.parents and resolved != _REPO_ROOT, "DATA_ROOT_INSIDE_REPO", "data_root")
    _require(os.environ.get("GITHUB_ACTIONS", "") == "", "GITHUB_ACTIONS_NOT_ALLOWED", "environment")
    workspace = os.environ.get("GITHUB_WORKSPACE", "")
    if workspace:
        ws = Path(workspace).resolve()
        _require(ws not in resolved.parents and resolved != ws, "DATA_ROOT_INSIDE_WORKSPACE", "data_root")
    return resolved


def _pilot_dir(root: Path) -> Path:
    return root / PILOT_DIRNAME


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")


def _read_json(path: Path, code: str) -> Dict[str, Any]:
    _require(path.is_file(), code, path.name)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except ValueError:
        raise PilotError(code, path.name) from None
    _require(isinstance(data, dict), code, path.name)
    return data


# ---------------------------------------------------------------- request budget（2 段を通して 8）


def _load_budget(root: Path, pilot_id: str) -> RequestBudget:
    path = _pilot_dir(root) / BUDGET_FILENAME
    budget = RequestBudget(PILOT_MAX_REQUESTS)
    if path.is_file():
        state = _read_json(path, "BUDGET_STATE_UNREADABLE")
        _require(state.get("schema") == BUDGET_SCHEMA and state.get("pilot_id") == pilot_id, "BUDGET_STATE_MISMATCH",
                 "pilot_id")
        paths = state.get("paths")
        _require(isinstance(paths, list) and len(paths) == state.get("used"), "BUDGET_STATE_MISMATCH", "paths")
        for used_path in paths:                                                  # 使った回数を再現する（reset しない）
            budget.reserve(used_path)
    return budget


def _save_budget(root: Path, pilot_id: str, budget: RequestBudget) -> None:
    _write_json(_pilot_dir(root) / BUDGET_FILENAME, {"schema": BUDGET_SCHEMA, "pilot_id": pilot_id, **budget.as_dict()})


# ---------------------------------------------------------------- 入力の検査


def _check_codes(codes: Any) -> Tuple[str, ...]:
    _require(isinstance(codes, (list, tuple)) and 1 <= len(codes) <= MAX_TARGET_CODES, "TARGET_COUNT_INVALID", "codes")
    for code in codes:
        _require(isinstance(code, str) and bool(_CODE_RE.match(code)), "TARGET_CODE_INVALID", "codes")
    _require(len(set(codes)) == len(codes), "TARGET_CODE_DUPLICATE", "codes")
    return tuple(codes)


def _check_d0(value: Any) -> date:
    _require(isinstance(value, str) and bool(_DATE_RE.match(value)), "D0_INVALID", "d0")
    try:
        parsed = date.fromisoformat(value)
    except ValueError:
        raise PilotError("D0_INVALID", "d0") from None
    _require(parsed.isoformat() == value, "D0_INVALID", "d0")
    return parsed


def _pilot_id(d0: date, codes: Tuple[str, ...]) -> str:
    digest = hashlib.sha256(json.dumps([d0.isoformat(), sorted(codes)]).encode("utf-8")).hexdigest()
    return f"p8pilot2_{d0.isoformat().replace('-', '')}_{digest[:8]}"


def _checklist(result: Any) -> Dict[str, bool]:
    return {"code_is_five_digit_common_equity": bool(_CODE_RE.match(result.code)),
            "market_supported": result.market in SUPPORTED_MARKETS,
            "product_category_is_domestic_equity": result.product_category == "011",
            "name_present": result.id1_row is not None and result.id1_row.CoName != "",
            "eligible_for_id1": result.eligibility is MasterEligibility.ELIGIBLE_FOR_ID1}


# ---------------------------------------------------------------- 段 1: prepare


def prepare(*, d0: Any, codes: Any, data_root: Any, transport: Any, batch_id: str = DEFAULT_BATCH_ID) -> Dict[str, Any]:
    """master を 1 回取得し、要求した code の適格 ・ID1 の提案を人の審査の packet に書いて止まる。fins ・ID2 ・A1 ・A2 には触れない。"""
    root = validate_data_root(data_root)
    day = _check_d0(d0)
    targets = _check_codes(codes)
    _require(isinstance(transport, Transport), "TRANSPORT_INVALID", "transport")
    pilot_id = _pilot_id(day, targets)
    _require(not (_pilot_dir(root) / PACKET_FILENAME).is_file(), "PACKET_ALREADY_EXISTS", PACKET_FILENAME)
    budget = _load_budget(root, pilot_id)
    client = JQuantsLiveClient(transport, budget)
    try:
        fetch = client.fetch_master(day.isoformat())
    finally:
        _save_budget(root, pilot_id, budget)                                     # 失敗した request も数える
    by_code = {result.code: result for result in fetch.results}
    entries: List[Dict[str, Any]] = []
    eligible_rows: List[MasterRow] = []
    for code in targets:
        result = by_code.get(code)
        if result is None:
            entries.append({"code": code, "eligibility": "NOT_RETURNED", "reasons": ["TARGET_NOT_IN_SNAPSHOT"],
                            "market": "", "product_category": "", "name_ja": "", "name_en": "", "checklist": {}})
            continue
        entry = {"code": code, "eligibility": result.eligibility.value, "reasons": [r.value for r in result.reasons],
                 "market": result.market, "product_category": result.product_category,
                 "name_ja": result.id1_row.CoName if result.id1_row else "",
                 "name_en": result.id1_row.CoNameEn if result.id1_row else "", "checklist": _checklist(result)}
        entries.append(entry)
        if result.eligibility is MasterEligibility.ELIGIBLE_FOR_ID1:
            eligible_rows.append(result.id1_row)
    batch = BootstrapBatch(batch_id=batch_id, d0=day, supported_markets=SUPPORTED_MARKETS)
    manifest = propose_bootstrap(eligible_rows, batch)                            # 凍結 ID1（A1 の状態は execute で）
    proposals = {p.code: p for p in manifest.proposals}
    for entry in entries:
        proposal = proposals.get(entry["code"])
        if proposal is not None:
            entry.update({"proposal_id": proposal.proposal_id, "proposal_digest": proposal.digest,
                          "issuer_anchor": proposal.issuer_anchor, "security_anchor": proposal.security_anchor,
                          "issuer_id": proposal.issuer_id, "security_id": proposal.security_id})
    packet = {"schema": PACKET_SCHEMA, "pilot_id": pilot_id, "d0": day.isoformat(), "batch_id": batch_id,
              "supported_markets": list(SUPPORTED_MARKETS), "manifest_digest": manifest.manifest_digest,
              "targets": entries, "id1_rows": [row.supported_values() for row in manifest_rows(eligible_rows)],
              "review_items": [item.as_dict() for item in manifest.review_items],
              "rules_version": PILOT_RULES_VERSION}
    _write_json(_pilot_dir(root) / PACKET_FILENAME, packet)
    template = {"schema": DECISION_SCHEMA, "pilot_id": pilot_id, "manifest_digest": manifest.manifest_digest,
                "accepted_at": "", "decisions": [{"code": p.code, "proposal_id": p.proposal_id,
                                                  "proposal_digest": p.digest, "disposition": ""}
                                                 for p in manifest.proposals]}
    _write_json(_pilot_dir(root) / DECISION_TEMPLATE_FILENAME, template)
    counts = _count(e["eligibility"] for e in entries)
    return {"schema": SUMMARY_SCHEMA, "stage": "PREPARE", "state": "HUMAN_REVIEW_REQUIRED", "pilot_id": pilot_id,
            "d0": day.isoformat(), "target_count": len(targets), "eligibility_counts": counts,
            "proposal_count": len(manifest.proposals), "manifest_digest": manifest.manifest_digest,
            "request": budget.as_dict(), "packet_file": PACKET_FILENAME,
            "decision_template_file": DECISION_TEMPLATE_FILENAME,
            "rules_version": PILOT_RULES_VERSION}


def manifest_rows(rows: List[MasterRow]) -> List[MasterRow]:
    return sorted(rows, key=lambda r: r.Code)


def _count(values) -> Dict[str, int]:
    counts: Dict[str, int] = {}
    for value in values:
        counts[value] = counts.get(value, 0) + 1
    return counts


# ---------------------------------------------------------------- 人の判断


def _parse_accepted_at(value: Any) -> datetime:
    _require(isinstance(value, str) and value.strip() != "", "ACCEPTED_AT_MISSING", "accepted_at")
    try:
        parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError:
        raise PilotError("ACCEPTED_AT_INVALID", "accepted_at") from None
    _require(parsed.tzinfo is not None and parsed.tzinfo.utcoffset(parsed) is not None, "ACCEPTED_AT_NAIVE",
             "accepted_at")
    return parsed


def _load_decision(root: Path, packet: Mapping[str, Any], decision_path: Optional[Path]) -> Tuple[List[ProposalReview],
                                                                                                 datetime]:
    path = decision_path or (_pilot_dir(root) / DECISION_FILENAME)
    decision = _read_json(path, "DECISION_MISSING")
    _require(decision.get("schema") == DECISION_SCHEMA, "DECISION_SCHEMA_INVALID", "schema")
    _require(decision.get("pilot_id") == packet["pilot_id"], "DECISION_PILOT_MISMATCH", "pilot_id")
    _require(decision.get("manifest_digest") == packet["manifest_digest"], "DECISION_MANIFEST_STALE",
             "manifest_digest")
    items = decision.get("decisions")
    _require(isinstance(items, list), "DECISION_INVALID", "decisions")
    known = {t.get("proposal_id"): t for t in packet["targets"] if t.get("proposal_id")}
    reviews: List[ProposalReview] = []
    has_approve = False
    for item in items:
        _require(isinstance(item, dict), "DECISION_INVALID", "decisions")
        target = known.get(item.get("proposal_id"))
        _require(target is not None, "DECISION_PROPOSAL_UNKNOWN", "proposal_id")
        _require(item.get("proposal_digest") == target["proposal_digest"], "DECISION_PROPOSAL_STALE",
                 "proposal_digest")
        raw_disposition = item.get("disposition")
        _require(isinstance(raw_disposition, str) and raw_disposition in ("APPROVE", "REJECT", "DEFER"),
                 "DECISION_DISPOSITION_MISSING", "disposition")                  # 空 ・"yes" ・既定の承認は無い
        disposition = ReviewDisposition(raw_disposition)
        has_approve = has_approve or disposition is ReviewDisposition.APPROVE
        reviews.append(ProposalReview(proposal_id=target["proposal_id"], proposal_digest=target["proposal_digest"],
                                      disposition=disposition))
    _require(len({r.proposal_id for r in reviews}) == len(reviews), "DECISION_DUPLICATE", "proposal_id")
    accepted_at = _parse_accepted_at(decision.get("accepted_at")) if (has_approve or reviews) else None
    _require(accepted_at is not None, "ACCEPTED_AT_MISSING", "accepted_at")
    return reviews, accepted_at


# ---------------------------------------------------------------- 段 2: execute


def _ensure_stores(root: Path, *, authority: bool = False) -> None:
    """凍結の 4 store（PILOT2B では取得 event ・manifest ・保持の 3 store も）を作る（無ければ空で）。既にあれば触れない。"""
    IdentityStore.initialize(root)
    ObservationStore.initialize(root)
    SemanticMetadataStore.initialize(root)
    HeldObservationStore.initialize(root)
    if authority:
        AcquisitionEventStore.initialize(root)
        ManifestStore.initialize(root)
        ProviderHoldingsStore.initialize(root)


_STORE_OPENERS = (("identity", IdentityStore.open), ("observation", ObservationStore.open),
                  ("semantic_metadata", SemanticMetadataStore.open), ("held", HeldObservationStore.open))
_AUTHORITY_STORE_OPENERS = (("acquisition_events", AcquisitionEventStore.open), ("manifests", ManifestStore.open),
                            ("provider_holdings", ProviderHoldingsStore.open))
_STORE_ERRORS = (IdentityStoreError, ObservationStoreError, SemanticMetadataStoreError, HeldStoreError,
                 AcquisitionStoreError, ManifestStoreError, HoldingsStoreError)


def _store_integrity(root: Path, *, authority: bool = False) -> Dict[str, str]:
    """store の状態: `OK` ／ `MISSING`（まだ無い。作ってよい）／ `CORRUPT_<code>`（書かない ・修復しない）。"""
    status: Dict[str, str] = {}
    for name, opener in _STORE_OPENERS + (_AUTHORITY_STORE_OPENERS if authority else ()):
        try:
            opener(root, read_only=True)
            status[name] = "OK"
        except _STORE_ERRORS as exc:
            missing = exc.code in ("AUTHORITY_MISSING", "STORE_MISSING", "IDENTITY_AUTHORITY_MISSING")
            status[name] = "MISSING" if missing else (f"CORRUPT_{exc.code}" if exc.code.isupper() else "CORRUPT")
    return status


def _metrics_for(root: Path, issuer_id: str) -> Dict[str, Any]:
    """凍結 A3 の 4 指標の status と理由の code だけ（値は返さない ・保存しない）。cutoff は data から（時計なし）。"""
    history = ObservationStore.open(root, read_only=True).history
    journal = SemanticMetadataStore.open(root, read_only=True).journal
    semantics = {r.observation_id: r for r in journal.records if isinstance(r, ObservationSemantics)}
    records = [r for r in history.records if isinstance(r, FundamentalActual) and r.subject == issuer_id
               and r.statement_basis is PILOT_BASIS]
    fiscal_years = sorted({r.period for r in records if r.period.basis is PeriodBasis.FISCAL_YEAR},
                          key=lambda p: p.period_end)
    if not fiscal_years:
        return {name: {"status": "UNAVAILABLE", "reasons": ["NO_FISCAL_YEAR_OBSERVATION"]}
                for name in ("REVENUE_GROWTH", "OPERATING_MARGIN", "NET_MARGIN", "ROA_POINT_IN_TIME")}
    target = fiscal_years[-1]
    known = [max(r.knowledge.certain_by for r in records)]
    registration = IdentityStore.open(root, read_only=True).history.issuers.get(issuer_id)
    if registration is not None:
        known.append(registration.known_at)                                     # identity が知られた後でだけ解ける（PIT）
    cutoff = max(known) + timedelta(seconds=1)
    prior = [p for p in fiscal_years if p.fiscal_year_end == target.fiscal_year_start - timedelta(days=1)]
    common = {"history": history, "issuer_id": issuer_id, "statement_basis": PILOT_BASIS, "cutoff": cutoff,
              "semantics": semantics}
    out: Dict[str, Any] = {}
    if prior:
        result = revenue_growth(target_period=target, comparison_period=prior[-1], **common)
        out["REVENUE_GROWTH"] = _metric_status(result)
    else:
        out["REVENUE_GROWTH"] = {"status": "INSUFFICIENT_DATA", "reasons": ["NO_PRIOR_FISCAL_YEAR"]}
    out["OPERATING_MARGIN"] = _metric_status(operating_margin(period=target, **common))
    out["NET_MARGIN"] = _metric_status(net_margin(period=target, **common))
    out["ROA_POINT_IN_TIME"] = _metric_status(roa_point_in_time(fiscal_year=target, **common))
    return out


def _metric_status(result: Any) -> Dict[str, Any]:
    return {"status": result.status.value, "reasons": sorted({f"{r.leg.value}:{r.code.value}" for r in result.reasons})}


def _overall(summary: Mapping[str, Any]) -> str:
    id2 = summary["id2"]
    fins = summary["fins"]
    exe = summary["exe_outcomes"]
    integrity_ok = all(v == "OK" for v in summary["store_integrity"].values())
    registered = id2["bundles"].get("APPENDED", 0) + id2["bundles"].get("REUSED", 0)
    persisted = exe.get("APPENDED", 0) + exe.get("REUSED", 0)
    if not integrity_ok or id2["outcome"] in ("REJECTED", "PARTIAL_FAILURE") or summary["decision_counts"].get(
            "APPROVE", 0) == 0 or registered == 0:
        return "PILOT_FAIL"
    if (summary["identity_verification"]["failed"] == 0 and fins["success"] >= 1 and persisted >= 1
            and fins["failed"] == 0 and fins["skipped_budget"] == 0
            and exe.get("PARTIAL_FAILURE", 0) == 0 and exe.get("REJECTED", 0) == 0
            and summary["request"]["used"] <= PILOT_MAX_REQUESTS):
        return "PILOT_PASS"
    return "PILOT_PARTIAL"


def execute(*, data_root: Any, transport: Any, decision_path: Any = None, acquired_at: Any = None,
            screener_policy_id: Any = None, screener_policy_key: Any = None,
            screener_policy_version: Any = None) -> Dict[str, Any]:
    """人の判断の後: ID1 の再導出 → ID2 → A1 の確認 → fins → ADP0 ・EXE → A3 の status → 安全な要約。
    `acquired_at`（PILOT2B）を渡すと、fins の後に凍結 ACQ0 → EXE(acquired_at) → manifest → F1 → A3-RA の chain を加える。
    `screener_policy_id` か `screener_policy_key` ＋ `screener_policy_version`（B4B。明示だけ ・PILOT2B の時だけ）を渡すと、
    chain の後に凍結 B4A（B3 の正確な方針 → 凍結 B2）を呼び、安全な投影だけを要約の `screener` の節に足す。"""
    root = validate_data_root(data_root)
    _require(isinstance(transport, Transport), "TRANSPORT_INVALID", "transport")
    acquisition_instant = _parse_acquired_at(acquired_at) if acquired_at is not None else None
    selector = _screener_selector(screener_policy_id, screener_policy_key, screener_policy_version)
    if selector is not None:                                                     # network の前に fail closed（方針が源）
        _require(acquisition_instant is not None, "SCREENER_REQUIRES_ACQUIRED_AT", "acquired_at")
        _screener_policy_or_fail(root, selector)
    packet = _read_json(_pilot_dir(root) / PACKET_FILENAME, "PACKET_MISSING")
    _require(packet.get("schema") == PACKET_SCHEMA, "PACKET_SCHEMA_INVALID", "schema")
    pilot_id = packet["pilot_id"]
    day = _check_d0(packet["d0"])
    reviews, accepted_at = _load_decision(root, packet, Path(decision_path) if decision_path else None)
    if acquisition_instant is not None:                                          # network の前に（取得は審査の後）
        _require(accepted_at <= acquisition_instant, "ACQUIRED_AT_BEFORE_ACCEPTED_AT", "acquired_at")
    try:
        rows = [MasterRow.from_provider_mapping(item) for item in packet["id1_rows"]]
        batch = BootstrapBatch(batch_id=packet["batch_id"], d0=day,
                               supported_markets=tuple(packet["supported_markets"]))
        manifest = propose_bootstrap(rows, batch)                                # 凍結 ID1 の再導出
        _require(manifest.manifest_digest == packet["manifest_digest"], "PACKET_MANIFEST_STALE", "manifest_digest")
        reviewed = review_manifest(manifest, reviews, accepted_at=accepted_at)
    except (BootstrapInputError, BootstrapPlanError) as exc:
        raise PilotError("REVIEW_BINDING_INVALID", exc.code) from None
    decision_counts = _count(r.disposition.value for r in reviews)
    authority = acquisition_instant is not None
    integrity = _store_integrity(root, authority=authority)                      # 作る前に見る（破損なら触れない）
    if all(v in ("OK", "MISSING") for v in integrity.values()):
        _ensure_stores(root, authority=authority)
        integrity = _store_integrity(root, authority=authority)
    summary: Dict[str, Any] = {
        "schema": SUMMARY_SCHEMA, "stage": "EXECUTE", "pilot_id": pilot_id, "d0": day.isoformat(),
        "target_count": len(packet["targets"]),
        "eligibility_counts": _count(t["eligibility"] for t in packet["targets"]),
        "decision_counts": decision_counts,
        "id2": {"outcome": "NOT_ATTEMPTED", "reasons": [], "bundles": {}, "failure_code": ""},
        "digests": {"manifest": manifest.manifest_digest, "reviewed": reviewed.reviewed_digest, "plan": ""},
        "identity_verification": {"ok": 0, "failed": 0, "reasons": []},
        "fins": {"success": 0, "failed": 0, "skipped_budget": 0, "reasons": [], "rows": 0, "pagination_seen": 0},
        "exe_outcomes": {}, "exe_reasons": {}, "held_reasons": {}, "metrics": [],
        "acquisition_authority": {"schema": AUTHORITY_SCHEMA, "state": "NOT_REQUESTED", "acquired_at": None,
                                  "issuers": []},
        "screener": _screener_section(selector),
        "rules_version": PILOT_RULES_VERSION}
    if authority:
        summary["acquisition_authority"].update({"state": "REQUESTED", "acquired_at": _iso(acquisition_instant)})
    budget = _load_budget(root, pilot_id)
    acquisition_state = _load_acquisition_state(root, pilot_id) if authority else None
    if any(v.startswith("CORRUPT") for v in integrity.values()):                 # 破損: 書かない ・呼ばない ・修復しない
        summary.update({"request": budget.as_dict(), "store_integrity": integrity,
                        "state": "PILOT_FAILED" if authority else "PILOT_FAIL"})
        _write_json(_pilot_dir(root) / SUMMARY_FILENAME, summary)
        return summary
    registration = execute_identity_registration(rows, batch, reviewed, root)   # 凍結 ID2（A1 にだけ書く）
    summary["id2"] = {"outcome": registration.outcome.value, "reasons": [r.value for r in registration.reasons],
                      "bundles": _count(b.state.value for b in registration.bundles),
                      "failure_code": registration.failure_code}
    summary["digests"]["plan"] = registration.plan_digest
    client = JQuantsLiveClient(transport, budget)
    approved_codes = {r.proposal_id for r in reviews if r.disposition is ReviewDisposition.APPROVE}
    registered = [b for b in registration.bundles
                  if b.proposal_id in approved_codes and b.state in (WriteState.APPENDED, WriteState.REUSED)]
    exe_outcomes: Dict[str, int] = {}
    exe_reasons: Dict[str, int] = {}
    held_reasons: Dict[str, int] = {}
    for bundle in registered:
        try:
            handoff = verify_identity_for_code(IdentityStore.open(root, read_only=True).history, bundle.code)
            summary["identity_verification"]["ok"] += 1
        except LiveInputError as exc:
            summary["identity_verification"]["failed"] += 1
            summary["identity_verification"]["reasons"].append(exc.code)
            continue                                                             # identity が無ければ fins を発しない
        if budget.remaining == 0:
            summary["fins"]["skipped_budget"] += 1
            summary["fins"]["reasons"].append("BUDGET_EXHAUSTED")
            continue
        try:
            fins = client.fetch_fins_summary(handoff)
        except LiveInputError as exc:
            summary["fins"]["failed"] += 1
            summary["fins"]["reasons"].append(exc.code)
            _save_budget(root, pilot_id, budget)
            continue
        _save_budget(root, pilot_id, budget)
        summary["fins"]["success"] += 1
        summary["fins"]["rows"] += len(fins.rows)
        summary["fins"]["pagination_seen"] += 1 if fins.pagination_key else 0
        if authority:                                              # PILOT2B: ACQ0 → EXE → manifest → F1 → A3-RA
            rows = [row.supported_values() for row in fins.rows]
            summary["acquisition_authority"]["issuers"].append(
                _authority_chain(root, handoff, rows, fins.pagination_key, acquisition_instant, acquisition_state,
                                 exe_outcomes, exe_reasons, held_reasons))
            if selector is not None:                                             # B4B: chain の後 ・凍結 B4A だけ ・保存しない
                summary["screener"]["issuers"].append(
                    _screener_evaluation(root, handoff.issuer_id, acquisition_instant, selector, summary["screener"]))
        else:
            for row in fins.rows:                                                # 凍結 ADP0 ＋ EXE（A2 ・注記 ・保留）
                result = execute_financial_summary_row(row, AdapterContext(issuer_id=handoff.issuer_id), root)
                exe_outcomes[result.outcome.value] = exe_outcomes.get(result.outcome.value, 0) + 1
                for reason in result.reasons:
                    exe_reasons[reason.value] = exe_reasons.get(reason.value, 0) + 1
                for reason in result.held_reasons:
                    held_reasons[reason.value] = held_reasons.get(reason.value, 0) + 1
        summary["metrics"].append(_metrics_for(root, handoff.issuer_id))         # STRICT の status（値は入れない）
    summary["exe_outcomes"], summary["exe_reasons"], summary["held_reasons"] = exe_outcomes, exe_reasons, held_reasons
    summary["request"] = budget.as_dict()
    summary["store_integrity"] = _store_integrity(root, authority=authority)
    summary["state"] = _overall_pilot2b(summary) if authority else _overall(summary)
    if summary["screener"]["state"] == "FAILED":                                 # orchestration の失敗は fail closed
        summary["state"] = "PILOT_FAILED"
    _write_json(_pilot_dir(root) / SUMMARY_FILENAME, summary)
    return summary


# ---------------------------------------------------------------- B4B: 明示の方針 → 凍結 B4A（B3 → B2）→ 安全な投影


def _screener_selector(policy_id: Any, policy_key: Any, policy_version: Any) -> Optional[PolicySelector]:
    """明示の選択子だけ（既定 ・latest ・current ・自動の発見は無い）。3 つとも無ければ Screener は要求されない。"""
    if policy_id is None and policy_key is None and policy_version is None:
        return None
    try:
        if policy_id is not None:
            _require(policy_key is None and policy_version is None, "SCREENER_SELECTOR_INVALID", "one selector")
            return PolicySelector(policy_id=policy_id)
        return PolicySelector(policy_key=policy_key, version=policy_version)
    except PolicyEvaluationError as exc:
        raise PilotError("SCREENER_SELECTOR_INVALID", exc.code) from None


def _screener_policy_or_fail(root: Path, selector: PolicySelector) -> None:
    """network の前の fail closed: B3 store の integrity → 正確な方針。無い ・破損は PilotError（要約は書かない ・request は出さない）。"""
    try:
        resolve_policy(open_verified_store(root), selector)
    except PolicyEvaluationError as exc:
        raise PilotError("SCREENER_POLICY_UNAVAILABLE", f"{exc.failure.value}:{exc.code}") from None


def _screener_section(selector: Optional[PolicySelector]) -> Dict[str, Any]:
    kind = None if selector is None else ("POLICY_ID" if selector.policy_id is not None else "KEY_VERSION")
    return {"schema": SCREENER_SECTION_SCHEMA, "state": "NOT_REQUESTED" if selector is None else "REQUESTED",
            "selector_kind": kind, "issuers": [], "failure_code": ""}


def _screener_evaluation(root: Path, issuer_id: str, acquired_at: datetime, selector: PolicySelector,
                         section: Dict[str, Any]) -> Dict[str, Any]:
    """1 発行体: 文脈の軸は PILOT2B と同じ（`evaluation_as_of` ＝ `identity_valid_at` ＝ acquired_at。mode は方針から）。
    凍結 B4A が B3（read-only）→ 凍結 B2 を orchestration し、安全な投影だけを残す。失敗は節を FAILED にする（結果の状態とは別）。"""
    try:
        record = resolve_policy(open_verified_store(root), selector)
        context = EvaluationContext(subject_id=issuer_id, evaluation_as_of=acquired_at, identity_valid_at=acquired_at,
                                    authority_mode=record.policy.authority_mode, policy_id=record.policy.policy_id)
        inputs = EvaluationInputs(history=ObservationStore.open(root, read_only=True).history,
                                  semantics=_semantics_lookup(root),
                                  holdings=ProviderHoldingsStore.open(root, read_only=True),
                                  manifests=ManifestStore.open(root, read_only=True),
                                  corrections=CorrectionHistory(IdentityStore.open(root, read_only=True).history))
        outcome = evaluate_selected_policy(root, selector, context, inputs)
    except PolicyEvaluationError as exc:
        section["state"], section["failure_code"] = "FAILED", exc.failure.value
        return {"summary": None, "failure_code": exc.code}
    except ScreenerModelError as exc:
        section["state"], section["failure_code"] = "FAILED", "CONTEXT_INVALID"
        return {"summary": None, "failure_code": exc.code}
    return {"summary": project_safe_summary(outcome.result).as_dict(), "failure_code": ""}


# ---------------------------------------------------------------- PILOT2B: 取得の authority の chain（ACQ0 → … → A3-RA）


def _parse_acquired_at(value: Any) -> datetime:
    """`--acquired-at`: 人が明示に渡す aware な取得の瞬間（D-P2B-1）。既定 ・時計 ・補完は無い。"""
    _require(isinstance(value, str) and value.strip() != "", "ACQUIRED_AT_MISSING", "acquired_at")
    try:
        parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError:
        raise PilotError("ACQUIRED_AT_INVALID", "acquired_at") from None
    _require(parsed.tzinfo is not None and parsed.tzinfo.utcoffset(parsed) is not None, "ACQUIRED_AT_NAIVE",
             "acquired_at")
    return parsed


def _iso(value: datetime) -> str:
    return value.isoformat()


def _load_acquisition_state(root: Path, pilot_id: str) -> Dict[str, Any]:
    path = _pilot_dir(root) / ACQUISITION_STATE_FILENAME
    if not path.is_file():
        return {"schema": ACQUISITION_STATE_SCHEMA, "pilot_id": pilot_id, "bindings": {}}
    state = _read_json(path, "ACQUISITION_STATE_UNREADABLE")
    _require(state.get("schema") == ACQUISITION_STATE_SCHEMA and state.get("pilot_id") == pilot_id,
             "ACQUISITION_STATE_MISMATCH", "pilot_id")
    _require(isinstance(state.get("bindings"), dict), "ACQUISITION_STATE_MISMATCH", "bindings")
    return state


def _save_acquisition_state(root: Path, state: Mapping[str, Any]) -> None:
    _write_json(_pilot_dir(root) / ACQUISITION_STATE_FILENAME, state)


def _scope_key(scope: RequestScope) -> str:
    """範囲（endpoint ＋ code）の hash。要約 ・state に code を書かないための不透明な key。"""
    return hashlib.sha256(json.dumps(scope.as_dict(), sort_keys=True).encode("utf-8")).hexdigest()[:24]


def _acquisition_event(code: str, rows: List[Dict[str, str]], pagination_key: str,
                       acquired_at: datetime) -> AcquisitionEvent:
    """凍結 ACQ0 の event（digest ・row_count は凍結 helper。page は追わない: key があれば PARTIAL_PAGINATED）。"""
    content = bounded_content_digest(FINS_SUMMARY_PATH, rows)
    status = AcquisitionStatus.PARTIAL_PAGINATED if pagination_key else AcquisitionStatus.COMPLETE
    return AcquisitionEvent(provider=SourceClass.JQUANTS, scope=RequestScope.of(FINS_SUMMARY_PATH, {"code": code}),
                            acquired_at=acquired_at, status=status, row_count=content.row_count,
                            pagination_key_present=bool(pagination_key), pages_followed=1,
                            content_digest=content.digest, failure_code="")


def _semantics_lookup(root: Path) -> Dict[str, ObservationSemantics]:
    journal = SemanticMetadataStore.open(root, read_only=True).journal
    return {r.observation_id: r for r in journal.records if isinstance(r, ObservationSemantics)}


def _target_candidates(root: Path, issuer_id: str, authority: datetime) -> Dict[date, set]:
    """保持 record（`holdings_as_of <= authority`）＋ 結び付いた manifest の CANONICAL の期間 → period_end ごとの候補の期間の集合。
    journal ・provider の行 ・file の順は使わない（期間の意味だけ）。"""
    holdings = ProviderHoldingsStore.open(root, read_only=True)
    manifests = ManifestStore.open(root, read_only=True)
    candidates: Dict[date, set] = {}
    for record in holdings.for_subject(issuer_id):
        if record.holdings_as_of > authority:
            continue
        manifest = manifests.by_acquisition(record.acquisition_ref)
        if manifest is None:
            continue                                                             # authority の失敗は A3-RA が報告する
        for entry in manifest.entries:
            if entry.disposition.value == "CANONICAL" and entry.period is not None \
                    and entry.period.period_end == record.period_end and entry.statement_basis is PILOT_BASIS:
                candidates.setdefault(record.period_end, set()).add(entry.period)
    return candidates


def _select_target(candidates: Mapping[date, set], bases: Tuple[PeriodBasis, ...]) -> Tuple[Any, str]:
    """period_end の降順で最初の、支える期間の種類の候補。同じ period_end に意味の違う期間が複数なら曖昧（選ばない）。"""
    for period_end in sorted(candidates, reverse=True):
        supported = {p for p in candidates[period_end] if p.basis in bases}
        if not supported:
            continue
        if len(supported) > 1:
            return None, "TARGET_AMBIGUOUS"
        return next(iter(supported)), ""
    return None, "NO_SUPPORTED_TARGET"


def _unavailable(metric: MetricKind, code: str) -> Dict[str, Any]:
    return {"metric": metric.value, "target_available": False, "outer_status": "UNAVAILABLE", "has_value": False,
            "resolution_mode": RESOLUTION_MODE, "diagnostic_codes": [code], "observation_id_count": 0,
            "epoch_ref_count": 0}


def _metric_entry(metric: MetricKind, result: Any) -> Dict[str, Any]:
    """安全な metadata だけ（値 ・観測 id ・参照そのものは書かない）。"""
    codes = set(result.diagnostics)
    if result.metric_result is not None:
        codes |= {r.as_text() for r in result.metric_result.reasons}
    return {"metric": metric.value, "target_available": True, "outer_status": result.status.value,
            "has_value": result.value is not None, "resolution_mode": result.resolution_mode,
            "diagnostic_codes": sorted(codes), "observation_id_count": len(result.observation_ids),
            "epoch_ref_count": len(result.coverage_epoch_ids)}


def _retrospective_metrics(root: Path, issuer_id: str, acquired_at: datetime) -> List[Dict[str, Any]]:
    """凍結 A3-RA を 4 指標に呼ぶ。authority_as_of ＝ identity_valid_at ＝ acquired_at（D-P2B-2）。値は要約に入れない。"""
    candidates = _target_candidates(root, issuer_id, acquired_at)
    history = ObservationStore.open(root, read_only=True).history
    common = dict(subject_id=issuer_id, statement_basis=PILOT_BASIS, authority_as_of=acquired_at,
                  identity_valid_at=acquired_at, manifests=ManifestStore.open(root, read_only=True),
                  corrections=CorrectionHistory(IdentityStore.open(root, read_only=True).history),
                  holdings=ProviderHoldingsStore.open(root, read_only=True), semantics=_semantics_lookup(root))
    out: List[Dict[str, Any]] = []
    for metric in RETROSPECTIVE_METRICS:
        bases = (PeriodBasis.FISCAL_YEAR,) if metric is MetricKind.ROA_POINT_IN_TIME else SUPPORTED_TARGET_BASES
        if metric is MetricKind.REVENUE_GROWTH:
            out.append(_revenue_growth_entry(history, candidates, common))
            continue
        target, code = _select_target(candidates, bases)
        if target is None:
            out.append(_unavailable(metric, code))
            continue
        result = resolve_retrospective_metric(metric, history, target_period=target, **common)
        out.append(_metric_entry(metric, result))
    return out


def _revenue_growth_entry(history: Any, candidates: Mapping[date, set], common: Mapping[str, Any]) -> Dict[str, Any]:
    """target を period_end の降順に見て、凍結 A3 の期間の関係が comparable な prior を持つ最初の候補（prior も保持 record を持つ）。"""
    metric = MetricKind.REVENUE_GROWTH
    ends = sorted(candidates, reverse=True)
    for end in ends:
        supported = {p for p in candidates[end] if p.basis in SUPPORTED_TARGET_BASES}
        if not supported:
            continue
        if len(supported) > 1:
            return _unavailable(metric, "TARGET_AMBIGUOUS")
        target = next(iter(supported))
        for prior_end in ends:
            if prior_end >= end:
                continue
            priors = {p for p in candidates[prior_end] if p.basis in SUPPORTED_TARGET_BASES}
            if len(priors) != 1:
                continue
            result = resolve_retrospective_metric(metric, history, target_period=target,
                                                  comparison_period=next(iter(priors)), **common)
            inner = result.metric_result
            reasons = {r.code.value for r in inner.reasons} if inner is not None else set()
            if reasons & set(PERIOD_RELATION_CODES):
                continue                                                         # 凍結の関係が comparable と言わない
            return _metric_entry(metric, result)
    return _unavailable(metric, "NO_COMPARABLE_PRIOR_PERIOD" if any(
        p.basis in SUPPORTED_TARGET_BASES for ps in candidates.values() for p in ps) else "NO_SUPPORTED_TARGET")


def _authority_chain(root: Path, handoff: Any, rows: List[Dict[str, str]], pagination_key: str,
                     acquired_at: datetime, state: Dict[str, Any], exe_outcomes: Dict[str, int],
                     exe_reasons: Dict[str, int], held_reasons: Dict[str, int]) -> Dict[str, Any]:
    """1 発行体の chain。各段は凍結の層をそのまま呼び、結果の status だけを要約に残す。"""
    entry: Dict[str, Any] = {"acquisition": {"status": "", "reused": False, "row_count": len(rows)},
                             "manifest": {"status": "NOT_ATTEMPTED"},
                             "f1": {"status": "NOT_ATTEMPTED", "appended_count": 0, "reused_count": 0},
                             "holdings_epoch_count": 0, "retrospective_metrics": [], "failure_code": ""}
    try:
        event = _acquisition_event(handoff.code, rows, pagination_key, acquired_at)
    except AcquisitionModelError as exc:
        entry["acquisition"]["status"] = "INVALID"
        entry["failure_code"] = exc.code
        return entry
    key = _scope_key(event.scope)
    binding = state["bindings"].get(key)
    if binding is not None and binding.get("content_digest") == event.content_digest \
            and not binding.get("completed", False) and binding.get("acquired_at") != _iso(acquired_at):
        entry["acquisition"]["status"] = "RESUME_MISMATCH"                        # 途中の取得は同じ acquired_at で再開する
        entry["failure_code"] = "ACQUIRED_AT_RESUME_MISMATCH"
        return entry
    try:
        appended = AcquisitionEventStore.open(root).append(event)
    except AcquisitionStoreError as exc:
        entry["acquisition"]["status"] = "STORE_FAILURE"
        entry["failure_code"] = exc.code
        return entry
    entry["acquisition"]["status"] = event.status.value
    entry["acquisition"]["reused"] = appended.status.value == "REUSED"
    state["bindings"][key] = {"content_digest": event.content_digest, "acquired_at": _iso(acquired_at),
                              "event_reference": event.reference, "completed": False}
    _save_acquisition_state(root, state)
    if event.status is not AcquisitionStatus.COMPLETE:                          # page は追わない ・authority は作らない
        state["bindings"][key]["completed"] = True
        _save_acquisition_state(root, state)
        return entry
    results = []
    for row in rows:                                                             # 凍結 EXE（知識の規則は EXE-R が決める）
        result = execute_financial_summary_row(row, AdapterContext(issuer_id=handoff.issuer_id,
                                                                   acquired_at=acquired_at), root)
        results.append(result)
        exe_outcomes[result.outcome.value] = exe_outcomes.get(result.outcome.value, 0) + 1
        for reason in result.reasons:
            exe_reasons[reason.value] = exe_reasons.get(reason.value, 0) + 1
        for reason in result.held_reasons:
            held_reasons[reason.value] = held_reasons.get(reason.value, 0) + 1
    built = build_manifest(event=event, rows=rows, results=results,
                           history=ObservationStore.open(root, read_only=True).history,
                           held_view=HeldObservationStore.open(root, read_only=True), subject_id=handoff.issuer_id)
    if built.outcome is ManifestOutcome.BUILT:
        built = record_manifest(built, ManifestStore.open(root))
    entry["manifest"]["status"] = built.outcome.value
    if built.outcome not in (ManifestOutcome.APPENDED, ManifestOutcome.REUSED):
        entry["failure_code"] = built.failure_code
        return entry
    holdings = execute_provider_holdings(event=event, manifests=ManifestStore.open(root, read_only=True),
                                         history=ObservationStore.open(root, read_only=True).history,
                                         store=ProviderHoldingsStore.open(root))
    entry["f1"] = {"status": holdings.status.value, "appended_count": len(holdings.appended),
                   "reused_count": len(holdings.reused)}
    entry["holdings_epoch_count"] = len(ProviderHoldingsStore.open(root, read_only=True).for_subject(handoff.issuer_id))
    if holdings.status in (HoldingsExecutionStatus.APPENDED, HoldingsExecutionStatus.REUSED,
                           HoldingsExecutionStatus.MIXED_APPEND_REUSE, HoldingsExecutionStatus.NO_CANONICAL_PERIODS,
                           HoldingsExecutionStatus.UNKNOWN_PERIOD_HELD_ROW):
        if holdings.authoritative:
            entry["retrospective_metrics"] = _retrospective_metrics(root, handoff.issuer_id, acquired_at)
        else:                                                                    # 0 epoch: authority を捏造しない
            entry["retrospective_metrics"] = [_unavailable(m, holdings.status.value) for m in RETROSPECTIVE_METRICS]
        state["bindings"][key]["completed"] = True
        _save_acquisition_state(root, state)
    else:
        entry["failure_code"] = holdings.failure_code
    return entry


def _overall_pilot2b(summary: Mapping[str, Any]) -> str:
    """監督が固定した PILOT2B の状態（PASS ／ HOLD ／ PARTIAL ／ FAILED）。PILOT2A の判定を土台にする。"""
    base = _overall(summary)
    authority = summary["acquisition_authority"]
    issuers = authority["issuers"]
    if base == "PILOT_FAIL" or any(v.startswith("CORRUPT") for v in summary["store_integrity"].values()):
        return "PILOT_FAILED"
    statuses = [m["outer_status"] for i in issuers for m in i["retrospective_metrics"]]
    f1 = [i["f1"]["status"] for i in issuers]
    if any(i["failure_code"] for i in issuers) or any(s in {x.value for x in _AUTHORITY_FAILURES} for s in statuses) \
            or any(i["manifest"]["status"] not in ("APPENDED", "REUSED", "NOT_ATTEMPTED") for i in issuers) \
            or any(s in ("PRECHECK_FAILED", "STORE_FAILURE") for s in f1):
        return "PILOT_FAILED"
    if any(s == "UNKNOWN_PERIOD_HELD_ROW" for s in f1):
        return "PILOT_HOLD"
    if (any(i["acquisition"]["status"] == "PARTIAL_PAGINATED" for i in issuers)
            or any(s == "NO_CANONICAL_PERIODS" for s in f1) or base == "PILOT_PARTIAL" or not issuers):
        return "PILOT_PARTIAL"
    return "PILOT_PASS"


# ---------------------------------------------------------------- CLI（本人の環境でだけ）


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="p8_pilot2_local", description="P8 PILOT2 local runner (private use only)")
    sub = parser.add_subparsers(dest="command", required=True)
    prep = sub.add_parser("prepare", help="fetch master once, write the human review packet, stop")
    prep.add_argument("--d0", required=True)
    prep.add_argument("--codes", required=True, nargs="+")
    prep.add_argument("--data-root", required=True)
    prep.add_argument("--batch-id", default=DEFAULT_BATCH_ID)
    prep.add_argument("--credential-env", default=DEFAULT_CREDENTIAL_ENV)
    run = sub.add_parser("execute", help="apply the human decision: ID2, A1 check, fins, ADP0, EXE, A3 status")
    run.add_argument("--data-root", required=True)
    run.add_argument("--decision", default=None)
    run.add_argument("--acquired-at", default=None, help="PILOT2B: explicit timezone-aware acquisition instant")
    run.add_argument("--screener-policy-id", default=None, help="B4B: exact policy_id of a human-reviewed policy")
    run.add_argument("--screener-policy-key", default=None, help="B4B: exact policy_key (needs the version)")
    run.add_argument("--screener-policy-version", default=None, type=int, help="B4B: exact explicit policy version")
    run.add_argument("--credential-env", default=DEFAULT_CREDENTIAL_ENV)
    return parser


def main(argv: Optional[List[str]] = None) -> int:
    args = _parser().parse_args(argv)
    if not (os.environ.get(args.credential_env) or "").strip():                 # network の前に。値は読むだけで出さない
        failure = {"state": "FAILED", "code": "CREDENTIAL_MISSING", "detail": "credential_env"}
        sys.stdout.write(json.dumps(failure) + "\n")
        return 2
    transport = LocalHttpsTransport(credential_env=args.credential_env)
    try:
        if args.command == "prepare":
            result = prepare(d0=args.d0, codes=args.codes, data_root=args.data_root, transport=transport,
                             batch_id=args.batch_id)
        else:
            result = execute(data_root=args.data_root, transport=transport, decision_path=args.decision,
                             acquired_at=args.acquired_at, screener_policy_id=args.screener_policy_id,
                             screener_policy_key=args.screener_policy_key,
                             screener_policy_version=args.screener_policy_version)
    except (PilotError, LiveInputError) as exc:
        sys.stdout.write(json.dumps({"state": "FAILED", "code": exc.code, "detail": exc.detail}) + "\n")
        return 2
    sys.stdout.write(json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2) + "\n")   # 安全な要約だけ
    return 0


if __name__ == "__main__":                                                       # pragma: no cover
    raise SystemExit(main())
