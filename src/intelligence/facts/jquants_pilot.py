"""J-Quants Fact builderの**実データ**pilot（Phase 3-B STEP 3 pre-flight）。

Phase 3-A時点ではJ-Quants Fact builderが**offline検証のみ**だった。
P2-Hが既に永続化したcanonical record（security master / financial summary /
earnings schedule）を入力に、

  P2-H canonical record → Fact builder → Fact → provenance → store/query

を実データで実証する。**新規の大量fetchはしない**（既存の永続データを使う）。
light storeが無い環境では正直にskipする（捏造しない）。
"""
from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional

from ..core.paths import data_root
from ..market.jquants_light_store import CANONICAL_FILES, JQuantsLightStore
from ..market.jquants_records import (
    RecordProvenance,
    parse_earnings_schedule,
    parse_financial_summary,
)
from ..market.p2h_light_pilot import light_root
from .jquants_builder import (
    COMPANY_FORECAST_VALUE,
    EARNINGS_SCHEDULE,
    REPORTED_FINANCIAL_VALUE,
    build_earnings_schedule_facts,
    build_financial_facts,
)
from .store import FactStore

#: canonicalへ保存されたdictを、Fact builderが受け取るrecordへ戻すための対応
_REVIVERS = {
    "fins_summary": (parse_financial_summary, {
        "code": "Code", "disclosed_date": "DiscDate", "disclosed_time": "DiscTime",
        "disclosure_number": "DiscNo", "document_type": "DocType",
        "period_type": "CurPerType", "fiscal_year_start": "CurFYSt",
        "fiscal_year_end": "CurFYEn", "period_start": "CurPerSt",
        "period_end": "CurPerEn", "next_fiscal_year_start": "NxtFYSt",
        "next_fiscal_year_end": "NxtFYEn", "net_sales": "Sales",
        "operating_profit": "OP", "ordinary_profit": "OdP", "net_profit": "NP",
        "eps": "EPS", "diluted_eps": "DEPS", "bps": "BPS", "roe": "ROE",
        "total_assets": "TA", "equity": "Eq", "equity_ratio": "EqAR",
        "cash_flow_operating": "CFO", "cash_flow_investing": "CFI",
        "cash_flow_financing": "CFF", "cash_and_equivalents": "CashEq",
        "forecast_net_sales": "FSales", "forecast_operating_profit": "FOP",
        "forecast_ordinary_profit": "FOdP", "forecast_net_profit": "FNP",
        "forecast_eps": "FEPS", "next_forecast_net_sales": "NxFSales",
        "next_forecast_operating_profit": "NxFOP",
        "next_forecast_ordinary_profit": "NxFOdP",
        "next_forecast_net_profit": "NxFNp", "next_forecast_eps": "NxFEPS",
        "retrospective_restatement": "RetroRst",
    }),
    "equities_earnings_cal": (parse_earnings_schedule, {
        "code": "Code", "announcement_date": "Date", "company_name": "CoName",
        "fiscal_quarter": "FQ", "fiscal_year": "FY", "section": "Section",
        "sector_name": "SectorNm",
    }),
}


def _revive(dataset: str, row: Dict):
    """canonical dict → record（保存時の正規化名を source field名へ戻す）。"""
    parser, mapping = _REVIVERS[dataset]
    source_row = {source: row.get(attr, "") for attr, source in mapping.items()}
    provenance_data = row.get("provenance") or {}
    provenance = RecordProvenance(
        source=provenance_data.get("source", "jquants"),
        provider=provenance_data.get("provider", "jquants"),
        api_version=provenance_data.get("api_version", "v2"),
        endpoint=provenance_data.get("endpoint", ""),
        retrieved_at=provenance_data.get("retrieved_at", ""),
        raw_item_id=provenance_data.get("raw_item_id", ""),
        fetch_attempt_id=provenance_data.get("fetch_attempt_id", ""))
    return parser(source_row, provenance)


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="J-Quants Fact builder real-data pilot (Phase 3-B pre-flight)")
    parser.add_argument("--limit", type=int, default=200,
                        help="財務レコードの上限（小規模pilot）")
    args = parser.parse_args(argv)

    root = data_root()
    light = light_root(root)
    canonical = light / "canonical"
    if not (canonical / CANONICAL_FILES["fins_summary"]).exists():
        print("::P3B_JQFACT_SKIP::" + json.dumps(
            {"reason": "jquants_light_canonical_not_found",
             "expected": str(canonical)}, ensure_ascii=False))
        return 0

    store = JQuantsLightStore(light)
    now = datetime.now(timezone.utc)

    fin_rows = list(store.iter_canonical("fins_summary"))[: args.limit]
    ern_rows = list(store.iter_canonical("equities_earnings_cal"))
    fin_records = [r for r in (_revive("fins_summary", row) for row in fin_rows) if r]
    ern_records = [r for r in (_revive("equities_earnings_cal", row) for row in ern_rows) if r]

    facts = build_financial_facts(fin_records, now=now)
    facts += build_earnings_schedule_facts(ern_records, now=now)

    fact_store = FactStore(root)
    first = fact_store.add(facts)
    second = fact_store.add(facts)          # 冪等性を実データで確認
    rebuilt = fact_store.rebuild_index()

    by_type: Dict[str, int] = {}
    for fact in facts:
        by_type[fact.fact_type] = by_type.get(fact.fact_type, 0) + 1

    sample = next((f for f in facts if f.fact_type == REPORTED_FINANCIAL_VALUE), None)
    forecast = next((f for f in facts if f.fact_type == COMPANY_FORECAST_VALUE), None)
    schedule = next((f for f in facts if f.fact_type == EARNINGS_SCHEDULE), None)

    def describe(fact) -> Dict:
        if fact is None:
            return {}
        return {
            "fact_type": fact.fact_type,
            "subject_type": fact.subject.subject_type,
            "security_id": fact.subject.subject_id,
            "value": str(fact.value.value) if fact.value.value is not None else "",
            "text_value": fact.value.text_value,
            "unit": fact.value.unit, "currency": fact.value.currency,
            "primary_date": fact.time.primary_date,
            "date_role": fact.time.date_role.value,
            "period_start": fact.time.period_start,
            "period_end": fact.time.period_end,
            "known_at": fact.time.known_at.isoformat() if fact.time.known_at else "",
            "evidence_kind": fact.evidence[0].kind.value if fact.evidence else "",
            "evidence_ref": fact.evidence[0].ref_id if fact.evidence else "",
            "evidence_locator": fact.evidence[0].locator if fact.evidence else "",
            "fact_id": fact.fact_id, "note": fact.note,
        }

    # raw provenanceが生応答まで到達できるか（RawItem→blob）
    raw_reachable = 0
    raw_ids = {f.evidence[0].ref_id for f in facts if f.evidence}
    known_raw = {i.raw_item_id for i in store.raw.iter_raw_items()}
    canonical_raw = {row.get("provenance", {}).get("raw_item_id", "")
                     for row in fin_rows + ern_rows}
    raw_reachable = len(canonical_raw & known_raw)

    print("::P3B_JQFACT::" + json.dumps({
        "input_financial_records": len(fin_records),
        "input_earnings_records": len(ern_records),
        "facts_generated": len(facts), "by_type": by_type,
        "store_added_first": first["added"], "store_added_second": second["added"],
        "idempotent": second["added"] == 0,
        "canonical_rows": fact_store.count(),
        "rebuilt_from_canonical": rebuilt,
        "rebuild_match": rebuilt == fact_store.count(),
        "distinct_fact_ids": len({f.fact_id for f in facts}),
        "duplicate_fact_ids": len(facts) - len({f.fact_id for f in facts}),
        "missing_provenance": sum(1 for f in facts if not f.evidence),
        "raw_item_ids_resolvable": raw_reachable,
        "distinct_raw_item_ids": len({r for r in canonical_raw if r}),
        "sample_reported": describe(sample),
        "sample_forecast": describe(forecast),
        "sample_schedule": describe(schedule),
        "query_facts_for_security": len(
            fact_store.facts_for_subject(sample.subject.subject_id)) if sample else 0,
        "query_by_evidence": len(
            fact_store.facts_by_evidence(sample.evidence[0].ref_id)) if sample else 0,
    }, ensure_ascii=False))

    store.close()
    fact_store.close()
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
