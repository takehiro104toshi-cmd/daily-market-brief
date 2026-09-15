"""J-Quants capability gate（Phase 3.6 §25 — project-wide rule）。

今後の Phase が新しい data requirement を追加するとき、**最初に**この gate を通す。

    入力: CapabilityRequest（必要データ・候補dataset・必要項目・必要履歴）
    出力: CURRENT_PLAN_SUPPORTED / CURRENT_PLAN_UNSUPPORTED / ALREADY_AVAILABLE /
          NEEDS_NEW_ENDPOINT / PLAN_UPGRADE_CANDIDATE / DEFER

判定は registry（実測）だけで行い、推測で AVAILABLE にしない。
現契約で取得できるデータがあるなら別 source を重複実装しない。
Standard / Premium endpoint を迂回しない。plan upgrade は提案止まり（自動実施しない）。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Sequence, Tuple

from .registry import (
    ALREADY_INGESTED,
    ALTERNATIVE_APPROVED_SOURCE,
    AVAILABLE_ON_CURRENT_PLAN,
    DEFERRED,
    NOT_ENTITLED,
    REGISTRY,
    DatasetCapability,
)

CURRENT_PLAN_SUPPORTED = "CURRENT_PLAN_SUPPORTED"
CURRENT_PLAN_UNSUPPORTED = "CURRENT_PLAN_UNSUPPORTED"
ALREADY_AVAILABLE = "ALREADY_AVAILABLE"
NEEDS_NEW_ENDPOINT = "NEEDS_NEW_ENDPOINT"
PLAN_UPGRADE_CANDIDATE_GATE = "PLAN_UPGRADE_CANDIDATE"
DEFER = "DEFER"
GATE_OUTCOMES = (CURRENT_PLAN_SUPPORTED, CURRENT_PLAN_UNSUPPORTED, ALREADY_AVAILABLE,
                 NEEDS_NEW_ENDPOINT, PLAN_UPGRADE_CANDIDATE_GATE, DEFER)

#: 実測で確認済みの履歴深さ（session）。これを超える要求は DEFER（推測で「取れる」と言わない）
VERIFIED_HISTORY_SESSIONS: Dict[str, int] = {
    "daily_bars": 244, "topix": 244, "investor_types": 64, "markets_calendar": 400,
    "listed_master": 46, "fins_summary": 31, "equities_earnings_cal": 1,
}


@dataclass(frozen=True, kw_only=True)
class CapabilityRequest:
    name: str
    description: str
    candidate_datasets: Tuple[str, ...]
    required_fields: Tuple[str, ...] = ()
    history_sessions: int = 0
    requesting_phase: str = ""


@dataclass(frozen=True, kw_only=True)
class GateDecision:
    request: str
    outcome: str
    dataset: str = ""
    reason: str = ""
    checked: Tuple[str, ...] = ()
    next_action: str = ""

    def as_dict(self) -> Dict[str, object]:
        return {"request": self.request, "outcome": self.outcome, "dataset": self.dataset,
                "reason": self.reason, "checked": list(self.checked),
                "next_action": self.next_action}


def _fields_ok(cap: DatasetCapability, required: Sequence[str]) -> Tuple[bool, List[str]]:
    if not required or not cap.observed_fields:
        return True, []
    missing = [f for f in required if f not in cap.observed_fields]
    return not missing, missing


def evaluate_capability(request: CapabilityRequest) -> GateDecision:
    """候補 dataset を順に registry で照合し、最初に確定できる判定を返す。"""
    checked: List[str] = []
    upgrade: Optional[DatasetCapability] = None
    for key in request.candidate_datasets:
        cap = REGISTRY.get(key)
        checked.append(key)
        if cap is None:
            continue
        if cap.strategy_status == ALTERNATIVE_APPROVED_SOURCE:
            return GateDecision(request=request.name, outcome=ALREADY_AVAILABLE, dataset=key,
                                reason="J-Quants Light に無く、承認済み代替 source で取得済み",
                                checked=tuple(checked), next_action="既存 Market Data Bank を使う")
        if cap.entitlement_status == AVAILABLE_ON_CURRENT_PLAN:
            ok, missing = _fields_ok(cap, request.required_fields)
            if not ok:
                return GateDecision(request=request.name, outcome=NEEDS_NEW_ENDPOINT, dataset=key,
                                    reason=f"実測項目に無い field: {','.join(missing)}",
                                    checked=tuple(checked),
                                    next_action="別 endpoint の probe（entitlement を実応答で確認）")
            if request.history_sessions > VERIFIED_HISTORY_SESSIONS.get(key, 0):
                return GateDecision(request=request.name, outcome=DEFER, dataset=key,
                                    reason=f"必要履歴 {request.history_sessions} session は実測済み深さ "
                                           f"{VERIFIED_HISTORY_SESSIONS.get(key, 0)} を超える",
                                    checked=tuple(checked),
                                    next_action="daily incremental の蓄積、または履歴深さの実測後に再判定")
            if cap.strategy_status == ALREADY_INGESTED:
                return GateDecision(request=request.name, outcome=ALREADY_AVAILABLE, dataset=key,
                                    reason="現契約で取得可能かつ canonical store に取り込み済み",
                                    checked=tuple(checked),
                                    next_action=f"{cap.canonical_store} を消費する（重複実装しない）")
            return GateDecision(request=request.name, outcome=CURRENT_PLAN_SUPPORTED, dataset=key,
                                reason="現契約で取得可能（未取り込み）", checked=tuple(checked),
                                next_action="既存 ingest 経路（JQuantsV2Client + light store）へ dataset 追加")
        if cap.entitlement_status == NOT_ENTITLED and upgrade is None:
            upgrade = cap
        if cap.strategy_status == DEFERRED:
            continue
    if upgrade is not None:
        return GateDecision(request=request.name, outcome=PLAN_UPGRADE_CANDIDATE_GATE,
                            dataset=upgrade.dataset,
                            reason=f"{upgrade.endpoint} は {upgrade.plan} 契約が必要（403 実測済み）",
                            checked=tuple(checked),
                            next_action="plan upgrade register へ記載し監督者判断（自動 upgrade しない・迂回しない）")
    if any(k in REGISTRY for k in request.candidate_datasets):
        return GateDecision(request=request.name, outcome=CURRENT_PLAN_UNSUPPORTED,
                            reason="候補 dataset は現契約で利用不可（entitlement 未確定/DEFERRED）",
                            checked=tuple(checked),
                            next_action="DEFER または承認済み代替 source の検討（推測で実装しない）")
    return GateDecision(request=request.name, outcome=NEEDS_NEW_ENDPOINT,
                        reason="registry に候補 dataset が無い", checked=tuple(checked),
                        next_action="entitlement probe（1リクエスト・実応答で判定）→ registry へ追記")


#: J-Quants First 監査: 既存 Phase の data requirement を gate に通した結果（テストで固定）
STANDING_REQUESTS: Tuple[CapabilityRequest, ...] = (
    CapabilityRequest(name="japan_market_breadth", description="東証プライム騰落銘柄数",
                      candidate_datasets=("daily_bars",), required_fields=("Code", "Date", "C"),
                      history_sessions=60, requesting_phase="3.5"),
    CapabilityRequest(name="topix_close", description="TOPIX終値", candidate_datasets=("topix",),
                      history_sessions=25, requesting_phase="3-A"),
    CapabilityRequest(name="nikkei225_close", description="日経平均終値",
                      candidate_datasets=("indices_bars_daily", "nikkei225"),
                      history_sessions=25, requesting_phase="3-A"),
    CapabilityRequest(name="sector_short_ratio", description="業種別空売り比率",
                      candidate_datasets=("markets_short_ratio",), requesting_phase="future"),
    CapabilityRequest(name="fifty_two_week_high_low", description="52週高値・安値",
                      candidate_datasets=("daily_bars",), history_sessions=250,
                      requesting_phase="3.6"),
    CapabilityRequest(name="weekly_investor_flow", description="投資部門別売買（週次）",
                      candidate_datasets=("investor_types",), requesting_phase="3.5"),
    CapabilityRequest(name="usd_jpy_close", description="ドル円", candidate_datasets=("usd_jpy",),
                      requesting_phase="3-A"),
    CapabilityRequest(name="intraday_am_close", description="前場終値",
                      candidate_datasets=("equities_bars_am",), requesting_phase="future"),
)


def standing_audit() -> List[Dict[str, object]]:
    return [evaluate_capability(r).as_dict() for r in STANDING_REQUESTS]
