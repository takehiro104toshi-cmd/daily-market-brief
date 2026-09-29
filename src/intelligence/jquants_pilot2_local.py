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
from .screener_intelligence.fundamental_metrics import operating_margin, revenue_growth
from .screener_intelligence.fundamental_metrics_extended import net_margin, roa_point_in_time
from .screener_intelligence.held_observation_store import HeldObservationStore
from .screener_intelligence.identity_bootstrap import BootstrapPlanError, propose_bootstrap, review_manifest
from .screener_intelligence.identity_bootstrap_model import (BootstrapBatch, BootstrapInputError, MasterRow,
                                                             ProposalReview, ReviewDisposition)
from .screener_intelligence.identity_registration_executor import execute_identity_registration
from .screener_intelligence.identity_registration_model import RegistrationOutcome, WriteState
from .screener_intelligence.identity_store import IdentityStore, IdentityStoreError
from .screener_intelligence.jquants_adapter_model import AdapterContext
from .screener_intelligence.jquants_execution_model import ExecutionOutcome
from .screener_intelligence.jquants_financial_summary_executor import execute_financial_summary_row
from .screener_intelligence.jquants_live_client import JQuantsLiveClient, verify_identity_for_code
from .screener_intelligence.jquants_live_model import (PILOT_MAX_REQUESTS, LiveInputError, MasterEligibility,
                                                       RequestBudget, Transport)
from .screener_intelligence.jquants_master_ingress import id1_rows
from .screener_intelligence.observation_model import FundamentalActual, PeriodBasis, StatementBasis
from .screener_intelligence.observation_semantics_model import ObservationSemantics
from .screener_intelligence.observation_store import ObservationStore, ObservationStoreError
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


def _ensure_stores(root: Path) -> None:
    """凍結の 4 store を作る（無ければ空で）。既にあれば触れない。"""
    IdentityStore.initialize(root)
    ObservationStore.initialize(root)
    SemanticMetadataStore.initialize(root)
    HeldObservationStore.initialize(root)


def _store_integrity(root: Path) -> Dict[str, str]:
    """4 store の状態: `OK` ／ `MISSING`（まだ無い。作ってよい）／ `CORRUPT_<code>`（書かない ・修復しない）。"""
    status: Dict[str, str] = {}
    for name, opener in (("identity", IdentityStore.open), ("observation", ObservationStore.open),
                         ("semantic_metadata", SemanticMetadataStore.open), ("held", HeldObservationStore.open)):
        try:
            opener(root, read_only=True)
            status[name] = "OK"
        except (IdentityStoreError, ObservationStoreError, SemanticMetadataStoreError, HeldStoreError) as exc:
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


def execute(*, data_root: Any, transport: Any, decision_path: Any = None) -> Dict[str, Any]:
    """人の判断の後: ID1 の再導出 → ID2 → A1 の確認 → fins → ADP0 ・EXE → A3 の status → 安全な要約。"""
    root = validate_data_root(data_root)
    _require(isinstance(transport, Transport), "TRANSPORT_INVALID", "transport")
    packet = _read_json(_pilot_dir(root) / PACKET_FILENAME, "PACKET_MISSING")
    _require(packet.get("schema") == PACKET_SCHEMA, "PACKET_SCHEMA_INVALID", "schema")
    pilot_id = packet["pilot_id"]
    day = _check_d0(packet["d0"])
    reviews, accepted_at = _load_decision(root, packet, Path(decision_path) if decision_path else None)
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
    integrity = _store_integrity(root)                                           # 作る前に見る（破損なら触れない）
    if all(v in ("OK", "MISSING") for v in integrity.values()):
        _ensure_stores(root)
        integrity = _store_integrity(root)
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
        "rules_version": PILOT_RULES_VERSION}
    budget = _load_budget(root, pilot_id)
    if any(v.startswith("CORRUPT") for v in integrity.values()):                 # 破損: 書かない ・呼ばない ・修復しない
        summary.update({"request": budget.as_dict(), "store_integrity": integrity, "state": "PILOT_FAIL"})
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
        for row in fins.rows:                                                    # 凍結 ADP0 ＋ EXE（A2 ・注記 ・保留）
            result = execute_financial_summary_row(row, AdapterContext(issuer_id=handoff.issuer_id), root)
            exe_outcomes[result.outcome.value] = exe_outcomes.get(result.outcome.value, 0) + 1
            for reason in result.reasons:
                exe_reasons[reason.value] = exe_reasons.get(reason.value, 0) + 1
            for reason in result.held_reasons:
                held_reasons[reason.value] = held_reasons.get(reason.value, 0) + 1
        summary["metrics"].append(_metrics_for(root, handoff.issuer_id))         # 値は入れない
    summary["exe_outcomes"], summary["exe_reasons"], summary["held_reasons"] = exe_outcomes, exe_reasons, held_reasons
    summary["request"] = budget.as_dict()
    summary["store_integrity"] = _store_integrity(root)
    summary["state"] = _overall(summary)
    _write_json(_pilot_dir(root) / SUMMARY_FILENAME, summary)
    return summary


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
            result = execute(data_root=args.data_root, transport=transport, decision_path=args.decision)
    except (PilotError, LiveInputError) as exc:
        sys.stdout.write(json.dumps({"state": "FAILED", "code": exc.code, "detail": exc.detail}) + "\n")
        return 2
    sys.stdout.write(json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2) + "\n")   # 安全な要約だけ
    return 0


if __name__ == "__main__":                                                       # pragma: no cover
    raise SystemExit(main())
