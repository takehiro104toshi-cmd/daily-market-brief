"""Market regime alignment（Phase 3.8 §12–§13）。

客観 regime label は **CONTEXT（Phase 3-B / 3.5、J-Quants 由来）** を優先し、無ければ 3.7 の EXTRACTED_VALUE
（紙面の数値表）、それも無ければ UNKNOWN。本文から捏造しない。
known_at / temporal rule: referenced session は営業日カレンダーから確定し、Context は
document の発行 cutoff（document_date 07:30 JST）より前に known であるものだけ使う（look-ahead 禁止）。
`MarketConnector` は既存 store（Tokyo calendar in J-Quants Light store / ContextStore / MarketBank）へ
**読み取り専用** で接続する。無ければ availability を False で報告する（データを複製しない）。
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from typing import Callable, Dict, List, Mapping, Optional, Sequence, Tuple

from ..corpus.coverage import COVERAGE_DIMENSIONS, SOURCE_CONTEXT, SOURCE_EXTRACTED, SOURCE_UNKNOWN
from ..corpus.temporal import UNKNOWN as SESSION_UNKNOWN
from ..corpus.temporal import resolve_referenced_session

REGIME_VERSION = "1.0.0"

REGIME_DIMENSIONS: Tuple[str, ...] = COVERAGE_DIMENSIONS + ("size_leadership", "flow_state")
#: pattern の market_state component に使う core dims（順序固定）
CORE_REGIME_DIMENSIONS: Tuple[str, ...] = ("equity_direction", "nikkei_vs_topix", "yen_direction",
                                           "japan_rate_direction", "us_rate_direction", "turnover_state",
                                           "breadth_state", "volatility_state", "growth_value_state")

#: Context（context_type, subject_id 一致条件）→ regime dim と direction → label の写像
_CONTEXT_MAP: Tuple[Tuple[str, str, str, Dict[str, str]], ...] = (
    ("index_direction", "index:topix", "equity_direction", {"UP": "UP", "DOWN": "DOWN", "FLAT": "FLAT"}),
    ("relative_performance", "index:nikkei225", "nikkei_vs_topix",
     {"OUTPERFORM": "NIKKEI_OUTPERFORM", "UNDERPERFORM": "TOPIX_OUTPERFORM", "FLAT": "IN_LINE", "MIXED": "IN_LINE"}),
    ("fx_direction", "fx:USDJPY", "yen_direction", {"UP": "YEN_WEAKER", "DOWN": "YEN_STRONGER", "FLAT": "FLAT",
                                                  "WEAKER": "YEN_WEAKER", "STRONGER": "YEN_STRONGER"}),
    ("rate_direction", "rates:JGB10Y", "japan_rate_direction", {"UP": "UP", "DOWN": "DOWN", "FLAT": "FLAT"}),
    ("rate_direction", "rates:UST10Y", "us_rate_direction", {"UP": "UP", "DOWN": "DOWN", "FLAT": "FLAT"}),
    ("breadth_state", "market:tse_prime", "breadth_state", {"UP": "BROAD", "DOWN": "NARROW", "MIXED": "MIXED",
                                                            "ABOVE": "BROAD", "BELOW": "NARROW", "FLAT": "MIXED"}),
    ("turnover_state", "market:tse_prime", "turnover_state", {"UP": "EXPANDING", "DOWN": "CONTRACTING",
                                                              "FLAT": "STABLE", "ABOVE": "EXPANDING", "BELOW": "CONTRACTING"}),
    ("sector_leadership", "sector:s17:leadership", "sector_leadership", {}),
    ("size_leadership", "size:leadership", "size_leadership", {"UP": "LARGE_LEAD", "DOWN": "SMALL_LEAD", "MIXED": "MIXED",
                                                               "OUTPERFORM": "LARGE_LEAD", "UNDERPERFORM": "SMALL_LEAD"}),
    ("investor_flow_state", "flow:", "flow_state", {}),
)


def publication_cutoff_utc(document_date: str) -> Optional[datetime]:
    """document_date 07:30 JST（紙面明記の発行時刻）を UTC で返す。"""
    try:
        d = datetime.fromisoformat(document_date)
    except ValueError:
        return None
    jst = timezone(timedelta(hours=9))
    return d.replace(hour=7, minute=30, tzinfo=jst).astimezone(timezone.utc)


class MarketConnector:
    """既存 store への読み取り専用接続。存在しない store は None（fabricate しない）。"""

    def __init__(self, data_root_dir: Optional[Path] = None, *, trading_days: Optional[Sequence[str]] = None,
                 context_rows: Optional[Callable[[str], Sequence[Mapping]]] = None,
                 market_lookup: Optional[Callable[[str, str], Optional[Decimal]]] = None) -> None:
        self._trading_days = list(trading_days) if trading_days else None
        self._context_rows = context_rows
        self._market_lookup = market_lookup
        self.availability: Dict[str, object] = {"calendar": bool(trading_days), "context": context_rows is not None,
                                                "market_bank": market_lookup is not None, "source": "injected"}
        if data_root_dir is not None:
            self._connect(Path(data_root_dir))

    def _connect(self, root: Path) -> None:
        self.availability["source"] = "data_root"
        try:
            from ..market.p2h_light_pilot import light_root
            from ..market.jquants_light_store import JQuantsLightStore
            from ..market.tokyo_calendar import trading_days as _trading_days

            lroot = light_root(root)
            if (lroot / "index").exists() and self._trading_days is None:
                light = JQuantsLightStore(lroot)
                try:
                    rows = [dict(r) for r in light.calendar_range("1900-01-01", "2999-12-31")]
                finally:
                    light.close()
                days = _trading_days(rows)
                if days:
                    self._trading_days = days
                    self.availability["calendar"] = True
        except Exception:  # noqa: BLE001 store が無い / 壊れている → 利用不可
            self.availability["calendar_error"] = True
        try:
            from ..context.store import ContextStore, context_root

            croot = context_root(root)
            if (croot / "index").exists() and self._context_rows is None:
                store = ContextStore(croot)

                def _rows(session: str, _store=store) -> Sequence[Mapping]:
                    return [dict(r) for r in _store.contexts_for_session(session)]

                self._context_rows = _rows
                self.availability["context"] = True
        except Exception:  # noqa: BLE001
            self.availability["context_error"] = True

    def trading_days(self) -> Optional[List[str]]:
        return list(self._trading_days) if self._trading_days else None

    def referenced_session(self, document_date: str) -> Tuple[str, str]:
        return resolve_referenced_session(document_date, self._trading_days)

    def context_labels(self, session: str, cutoff: Optional[datetime]) -> Dict[str, Dict[str, str]]:
        """session の Context → {dim: {"label", "context_id", "known_at"}}。known_at > cutoff は捨てる。"""
        if self._context_rows is None or not session or session == SESSION_UNKNOWN:
            return {}
        out: Dict[str, Dict[str, str]] = {}
        for row in self._context_rows(session):
            ctype = str(row.get("context_type", ""))
            subject = str(row.get("subject_id", ""))
            known = str(row.get("known_at", "") or "")
            if cutoff is not None:
                try:
                    known_dt = datetime.fromisoformat(known)
                    if known_dt.tzinfo is None:
                        known_dt = known_dt.replace(tzinfo=timezone.utc)
                    if known_dt > cutoff:
                        continue                              # look-ahead 禁止
                except ValueError:
                    continue                                  # known_at 不明 → 使わない
            for want_type, subject_prefix, dim, mapping in _CONTEXT_MAP:
                if ctype != want_type or not subject.startswith(subject_prefix):
                    continue
                if dim in out:
                    continue
                direction = str(row.get("direction", "") or "")
                note = str(row.get("note", "") or "")
                label = mapping.get(direction, "")
                if not label and note.startswith("state="):
                    label = note[len("state="):].split(";")[0]
                if not label:
                    continue
                out[dim] = {"label": label, "context_id": str(row.get("context_id", "")), "known_at": known}
        return out

    def market_value(self, series_id: str, session: str) -> Optional[Decimal]:
        if self._market_lookup is None:
            return None
        try:
            return self._market_lookup(series_id, session)
        except Exception:  # noqa: BLE001
            return None


@dataclass(frozen=True)
class RegimeAlignment:
    document_id: str
    document_date: str
    referenced_session: str
    session_basis: str
    cutoff_utc: str
    labels: Mapping[str, str]
    sources: Mapping[str, str]
    context_ids: Mapping[str, str]
    known_dimensions: int
    context_dimensions: int
    regime_key: str
    alignment_summary: Mapping[str, int]
    comparable_values: int
    look_ahead_rejected: int
    version: str = REGIME_VERSION

    def as_dict(self) -> Dict[str, object]:
        return {"document_id": self.document_id, "document_date": self.document_date,
                "referenced_session": self.referenced_session, "session_basis": self.session_basis,
                "cutoff_utc": self.cutoff_utc, "labels": dict(self.labels), "sources": dict(self.sources),
                "context_ids": dict(self.context_ids), "known_dimensions": self.known_dimensions,
                "context_dimensions": self.context_dimensions, "regime_key": self.regime_key,
                "alignment_summary": dict(self.alignment_summary),
                "comparable_values": self.comparable_values,
                "look_ahead_rejected": self.look_ahead_rejected, "version": self.version}


def regime_key_for(labels: Mapping[str, str], dims: Sequence[str] = CORE_REGIME_DIMENSIONS) -> str:
    parts = [f"{d}={labels[d]}" for d in dims if labels.get(d) and labels[d] != "UNKNOWN"]
    if not parts:
        return "regime:UNKNOWN"
    return "regime:" + hashlib.sha1("|".join(parts).encode("utf-8")).hexdigest()[:12]


def regime_alignment(*, document_id: str, document_date: str, coverage: Optional[Mapping],
                     temporal: Optional[Mapping], alignments: Sequence[Mapping], connector: MarketConnector
                     ) -> RegimeAlignment:
    labels: Dict[str, str] = {}
    sources: Dict[str, str] = {}
    context_ids: Dict[str, str] = {}
    for dim in REGIME_DIMENSIONS:
        lab = (coverage or {}).get("labels", {}).get(dim, "UNKNOWN") if coverage else "UNKNOWN"
        src = (coverage or {}).get("sources", {}).get(dim, SOURCE_UNKNOWN) if coverage else SOURCE_UNKNOWN
        labels[dim], sources[dim] = str(lab or "UNKNOWN"), str(src or SOURCE_UNKNOWN)
    session, basis = connector.referenced_session(document_date)
    if session == SESSION_UNKNOWN and temporal and temporal.get("referenced_market_session") not in ("", None, SESSION_UNKNOWN):
        session, basis = str(temporal["referenced_market_session"]), str(temporal.get("referenced_session_basis", ""))
    cutoff = publication_cutoff_utc(document_date)
    rejected = 0
    ctx = connector.context_labels(session, cutoff) if session != SESSION_UNKNOWN else {}
    if connector._context_rows is not None and session != SESSION_UNKNOWN:
        for row in list(connector._context_rows(session)):                # look-ahead で捨てた Context を数える
            known = str(row.get("known_at", "") or "")
            try:
                known_dt = datetime.fromisoformat(known)
                if known_dt.tzinfo is None:
                    known_dt = known_dt.replace(tzinfo=timezone.utc)
                if cutoff is not None and known_dt > cutoff:
                    rejected += 1
            except ValueError:
                rejected += 1
    for dim, info in ctx.items():
        labels[dim], sources[dim], context_ids[dim] = info["label"], SOURCE_CONTEXT, info["context_id"]
    summary: Dict[str, int] = {}
    for a in alignments:
        summary[str(a.get("status", ""))] = summary.get(str(a.get("status", "")), 0) + 1
    comparable = sum(v for k, v in summary.items() if k in ("MATCH", "NEAR_MATCH", "CONFLICT"))
    known = sum(1 for d in REGIME_DIMENSIONS if labels[d] != "UNKNOWN")
    return RegimeAlignment(
        document_id=document_id, document_date=document_date, referenced_session=session,
        session_basis=basis, cutoff_utc=cutoff.isoformat() if cutoff else "", labels=labels,
        sources=sources, context_ids=context_ids, known_dimensions=known,
        context_dimensions=sum(1 for d in REGIME_DIMENSIONS if sources[d] == SOURCE_CONTEXT),
        regime_key=regime_key_for(labels), alignment_summary=summary,
        comparable_values=comparable, look_ahead_rejected=rejected)
