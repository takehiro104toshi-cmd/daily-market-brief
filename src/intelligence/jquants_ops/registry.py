"""J-Quants capability registry（Phase 3.6 §0 / §2 / §3）。

**J-Quants First**: market / company data を必要とする Phase は、まずこの registry で
capability を確認する。entry は P2-H（run #1 / #3）と Phase 3.5（run #20）の
**live evidence** に基づく。既知の 403 endpoint を再 probe し続けない。

分類語彙（project-wide）:
- entitlement_status: AVAILABLE_ON_CURRENT_PLAN / NOT_ENTITLED / ENTITLEMENT_UNKNOWN
- strategy_status   : ALREADY_INGESTED / NEW_ENDPOINT_AVAILABLE / PLAN_UPGRADE_CANDIDATE /
                      ALTERNATIVE_APPROVED_SOURCE / DEFERRED / NOT_REQUIRED
- frequency_class   : DAILY / WEEKLY / EVENT_DRIVEN / REFERENCE / ON_DEMAND
- morning_role      : REQUIRED（無ければ Compass 不可）/ INTERNALS（市場内部次元）/
                      OPTIONAL（無くても Compass 可）/ NONE（朝には使わない）
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Mapping, Tuple

# ---- entitlement
AVAILABLE_ON_CURRENT_PLAN = "AVAILABLE_ON_CURRENT_PLAN"
NOT_ENTITLED = "NOT_ENTITLED"
ENTITLEMENT_UNKNOWN = "ENTITLEMENT_UNKNOWN"
# ---- strategy
ALREADY_INGESTED = "ALREADY_INGESTED"
NEW_ENDPOINT_AVAILABLE = "NEW_ENDPOINT_AVAILABLE"
PLAN_UPGRADE_CANDIDATE = "PLAN_UPGRADE_CANDIDATE"
ALTERNATIVE_APPROVED_SOURCE = "ALTERNATIVE_APPROVED_SOURCE"
DEFERRED = "DEFERRED"
NOT_REQUIRED = "NOT_REQUIRED"
STATUS_VOCABULARY = (AVAILABLE_ON_CURRENT_PLAN, ALREADY_INGESTED, NEW_ENDPOINT_AVAILABLE,
                     NOT_ENTITLED, PLAN_UPGRADE_CANDIDATE, ALTERNATIVE_APPROVED_SOURCE,
                     DEFERRED, NOT_REQUIRED)
# ---- frequency
DAILY = "DAILY"
WEEKLY = "WEEKLY"
EVENT_DRIVEN = "EVENT_DRIVEN"
REFERENCE = "REFERENCE"
ON_DEMAND = "ON_DEMAND"
FREQUENCY_CLASSES = (DAILY, WEEKLY, EVENT_DRIVEN, REFERENCE, ON_DEMAND)
# ---- morning role
ROLE_REQUIRED = "REQUIRED"
ROLE_INTERNALS = "INTERNALS"
ROLE_OPTIONAL = "OPTIONAL"
ROLE_NONE = "NONE"

CURRENT_PLAN = "Light"
RUN20 = "2026-09-02 p2d-market-pilot run #20 (33585035310)"
RUN19 = "2026-09-01 p2d-market-pilot run #19 (33566763923)"
P2H_RUN1 = "2026-09-01 p2h-jquants-light run #1 (entitlement probe)"
P2H_RUN3 = "2026-09-01 p2h-jquants-light run #3 (live pilot)"


@dataclass(frozen=True, kw_only=True)
class DatasetCapability:
    dataset: str
    endpoint: str
    plan: str                                # 取得に必要なプラン（実測 / 公式一覧）
    entitlement_status: str
    strategy_status: str
    frequency_class: str
    publication_semantics: str
    historical_depth: str
    pagination: str
    request_pattern: str
    canonical_store: str
    consumers: Tuple[str, ...]
    morning_role: str
    fallback_policy: str
    last_live_verified_at: str
    refresh_policy: str = ""
    known_at_rule: str = ""
    required_fields: Tuple[str, ...] = ()
    observed_fields: Tuple[str, ...] = ()
    note: str = ""

    @property
    def required_for_morning(self) -> bool:
        return self.morning_role == ROLE_REQUIRED

    def as_dict(self) -> Dict[str, object]:
        return {
            "dataset": self.dataset, "endpoint": self.endpoint, "plan": self.plan,
            "entitlement_status": self.entitlement_status,
            "strategy_status": self.strategy_status,
            "frequency_class": self.frequency_class,
            "publication_semantics": self.publication_semantics,
            "historical_depth": self.historical_depth, "pagination": self.pagination,
            "request_pattern": self.request_pattern, "canonical_store": self.canonical_store,
            "consumers": list(self.consumers), "morning_role": self.morning_role,
            "required_for_morning": self.required_for_morning,
            "fallback_policy": self.fallback_policy,
            "last_live_verified_at": self.last_live_verified_at,
            "refresh_policy": self.refresh_policy, "known_at_rule": self.known_at_rule,
            "required_fields": list(self.required_fields),
            "observed_fields": list(self.observed_fields), "note": self.note,
        }


def _cap(**kwargs) -> DatasetCapability:
    return DatasetCapability(**kwargs)


REGISTRY: Dict[str, DatasetCapability] = {c.dataset: c for c in (
    _cap(dataset="topix", endpoint="/indices/bars/daily/topix", plan="Light",
         entitlement_status=AVAILABLE_ON_CURRENT_PLAN, strategy_status=ALREADY_INGESTED,
         frequency_class=DAILY,
         publication_semantics="前営業日の四本値。J-Quants更新は毎営業日16:30頃JST。"
                               "当日セッションはクローズ後まで存在しない",
         historical_depth="Light: 実測で直近1年以上（P2-G.2/P2-H）",
         pagination="from/to レンジ・1 page（30日で1 page実測）",
         request_pattern="from=<latest_stored+1>&to=<today>（差分のみ。1リクエスト）",
         canonical_store="databank/market/normalized/observations.jsonl（Market Data Bank所有）",
         consumers=("facts.market_builder", "context.builders(index_direction/nt_ratio)",
                    "compass"),
         morning_role=ROLE_REQUIRED,
         fallback_policy="代替なし（NO PROXY SUBSTITUTION: ETF/先物で代用しない）。"
                         "欠ければ japan_equities MISSING → Compass ABSTAIN/COVERAGE",
         last_live_verified_at=RUN20 + " step 'market data bank live pilot'",
         refresh_policy="毎朝1回（差分）。Nikkei（legacy approved source）と同一session整合を確認",
         known_at_rule="session 15:30 JST（as_of=exchange close）",
         required_fields=("Date", "C"), observed_fields=("C", "Date", "H", "L", "O"),
         note="既存 jquants_v2.JQuantsV2TopixProvider を変更しない"),
    _cap(dataset="markets_calendar", endpoint="/markets/calendar", plan="Free/Light",
         entitlement_status=AVAILABLE_ON_CURRENT_PLAN, strategy_status=ALREADY_INGESTED,
         frequency_class=REFERENCE,
         publication_semantics="暦日ごとの HolDiv（営業日区分）。将来日も含む参照表",
         historical_depth="実測 2025-07-28〜2026-09-01（401暦日）＋将来分",
         pagination="from/to レンジ・1 page（150日で1 page）",
         request_pattern="from=<today-150d>&to=<today+60d>（週1回。gap検出で不足なら再取得）",
         canonical_store="jquants_light/canonical/trading_calendar.jsonl",
         consumers=("tokyo_calendar.latest_completed_session", "session_gap", "morning_contract"),
         morning_role=ROLE_REQUIRED,
         fallback_policy="参照系列（Nikkei/TOPIX観測日）から latest session を推定"
                         "（topix_freshness の従来経路）→ CALENDAR_UNKNOWN として報告",
         last_live_verified_at=RUN20,
         refresh_policy="週1回（月曜朝）＋ expected session が計算できない場合",
         known_at_rule="参照データ（時点性なし）。HolDiv=1 のみ営業日（P2-H 21/21 実測検証）",
         required_fields=("Date", "HolDiv"), observed_fields=("Date", "HolDiv")),
    _cap(dataset="daily_bars", endpoint="/equities/bars/daily", plan="Free/Light",
         entitlement_status=AVAILABLE_ON_CURRENT_PLAN, strategy_status=ALREADY_INGESTED,
         frequency_class=DAILY,
         publication_semantics="前営業日クローズ後（夕方）に当該sessionの全銘柄が揃う。"
                               "date指定で1 session全銘柄（4,441行）",
         historical_depth="Light: 実測 244 sessions/年（2025-09-01〜2026-09-01）。"
                          "2026-06-26〜09-01 を date 指定で取得済み（run #20）",
         pagination="date指定: 1 page（4,441行・約1.2MB）/ code指定: 1 page（244行）",
         request_pattern="date=<session>（1 session=1リクエスト）。repair は欠落 session のみ。"
                         "銘柄単位の補修は code+from+to",
         canonical_store="jquants_light/canonical/daily_prices.jsonl",
         consumers=("internals.breadth", "internals.turnover", "internals.sector",
                    "internals.size", "internals.breadth_history"),
         morning_role=ROLE_INTERNALS,
         fallback_policy="代替なし。欠ければ internals 5次元 MISSING/STALE → Compass は "
                         "COVERAGE で明示し継続（DEGRADED）",
         last_live_verified_at=RUN20 + " (46 sessions, 204,319 rows, 4.77s/session)",
         refresh_policy="毎朝: latest completed session のうち未保存分のみ（通常1リクエスト）",
         known_at_rule="session 15:30 JST（東京クローズ）",
         required_fields=("Code", "Date", "C"),
         observed_fields=("AdjC", "AdjFactor", "AdjH", "AdjL", "AdjO", "AdjVo", "C", "Code",
                          "Date", "ExRT", "H", "L", "LL", "MktCap", "O", "UL", "Va", "Vo")),
    _cap(dataset="listed_master", endpoint="/equities/master", plan="Free/Light",
         entitlement_status=AVAILABLE_ON_CURRENT_PLAN, strategy_status=ALREADY_INGESTED,
         frequency_class=REFERENCE,
         publication_semantics="日次 snapshot（Date=基準日）。date指定で過去日付の snapshot も取得可"
                               "（run #20: date=2026-06-26 → 4,439行）",
         historical_depth="date指定で過去snapshot取得可（深さは未測定。2026-06-26は取得済み）",
         pagination="1 page（4,441行・約1.45MB）",
         request_pattern="date=<effective_date>（週1回）＋ seed window 開始日の snapshot",
         canonical_store="jquants_light/canonical/security_master.jsonl（record_id=sec_<code>_<date>）",
         consumers=("internals.universe", "internals.sector", "internals.size"),
         morning_role=ROLE_INTERNALS,
         fallback_policy="session 以前で最新の snapshot を使う。無ければ最古を遡及適用し "
                         "master_applied_backwards として明示（KNOWN_LIMITATION_HISTORICAL_UNIVERSE）",
         last_live_verified_at=RUN20,
         refresh_policy="週1回（月曜朝）＋ 上場/廃止イベント時。毎朝は取らない",
         known_at_rule="snapshot Date（参照データ）",
         required_fields=("Code", "Date", "CoName"),
         observed_fields=("CoName", "CoNameEn", "Code", "Date", "Mkt", "MktNm", "Mrgn",
                          "MrgnNm", "ProdCat", "S17", "S17Nm", "S33", "S33Nm", "ScaleCat")),
    _cap(dataset="investor_types", endpoint="/equities/investor-types", plan="Light",
         entitlement_status=AVAILABLE_ON_CURRENT_PLAN, strategy_status=ALREADY_INGESTED,
         frequency_class=WEEKLY,
         publication_semantics="**週次**。PubDate（公表日）と StDate/EnDate（対象週）が別項目。"
                               "Section = TSEPrime / TSEStandard / TSEGrowth / TokyoNagoya（run #20）",
         historical_depth="実測 直近120日で64期間（P2-H）/ 60日で18週×4section（run #20）",
         pagination="from/to レンジ・1 page",
         request_pattern="from=<latest_stored_period_end-14d>&to=<today>（差分。1リクエスト）",
         canonical_store="jquants_light/canonical/investor_type_flows.jsonl",
         consumers=("internals.investor_flow",),
         morning_role=ROLE_OPTIONAL,
         fallback_policy="無ければ investor_flow MISSING/STALE（Compass継続）",
         last_live_verified_at=RUN20,
         refresh_policy="毎朝1リクエストで新規公表週の有無を確認（新規のみ追記）。"
                        "publication前の週は使わない",
         known_at_rule="PubDate の 16:00 JST（config publication_hour_jst）",
         required_fields=("Section", "PubDate", "StDate", "EnDate"),
         observed_fields=("Section", "PubDate", "StDate", "EnDate", "FrgnBuy", "FrgnSell",
                          "FrgnBal", "FrgnTot", "IndBuy", "IndSell", "IndBal", "IndTot",
                          "TrstBnkBuy", "TrstBnkSell", "TrstBnkBal", "TrstBnkTot", "BusCoBuy",
                          "BusCoSell", "BusCoBal", "BusCoTot", "TotBuy", "TotSell", "TotBal",
                          "TotTot")),
    _cap(dataset="fins_summary", endpoint="/fins/summary", plan="Free/Light",
         entitlement_status=AVAILABLE_ON_CURRENT_PLAN, strategy_status=ALREADY_INGESTED,
         frequency_class=EVENT_DRIVEN,
         publication_semantics="開示単位（DiscDate/DiscTime/DiscNo）。実績・当期予想・翌期予想が別項目",
         historical_depth="code指定で複数世代（22〜31件/銘柄・P2-H実測）",
         pagination="code指定: 1 page",
         request_pattern="code=<code>（開示があった銘柄のみ）。date指定の可否は run #21 で実測",
         canonical_store="jquants_light/canonical/financial_summaries.jsonl",
         consumers=("facts.jquants_builder(reported/forecast)",),
         morning_role=ROLE_NONE,
         fallback_policy="朝の Compass は使わない（Company Intelligence 用）。欠けても影響なし",
         last_live_verified_at=P2H_RUN3 + " / " + RUN19 + " (jquants fact pilot)",
         refresh_policy="event-driven: 前営業日の決算予定（earnings calendar）に載った銘柄だけ "
                        "code指定で取得。全銘柄の毎朝再取得はしない",
         known_at_rule="DiscDate の東京クローズ後（jquants_builder._known_at）",
         required_fields=("Code", "DiscDate")),
    _cap(dataset="equities_earnings_cal", endpoint="/equities/earnings-calendar",
         plan="Free/Light", entitlement_status=AVAILABLE_ON_CURRENT_PLAN,
         strategy_status=ALREADY_INGESTED, frequency_class=EVENT_DRIVEN,
         publication_semantics="公表済みの決算発表**予定**（Date=予定日）。変更されれば新しい予定が返る",
         historical_depth="将来分のみ意味を持つ（実測: run #1 は1件）",
         pagination="1 page",
         request_pattern="レンジ無し or from/to（今日〜+90日）。1リクエスト",
         canonical_store="jquants_light/canonical/earnings_schedule.jsonl（record_id=ern_<code>_<date>）",
         consumers=("facts.jquants_builder.earnings_schedule", "context.builders.event_proximity"),
         morning_role=ROLE_OPTIONAL,
         fallback_policy="無ければ event_proximity Context なし（Compass継続）",
         last_live_verified_at=P2H_RUN3,
         refresh_policy="毎朝1リクエスト（予定は変更され得るため）。旧予定は削除せず別recordとして残す",
         known_at_rule="取得時刻（公表済み予定のみ。未公表の予定は存在しない＝look-aheadにならない）",
         required_fields=("Code", "Date")),
    _cap(dataset="fins_earnings_date", endpoint="/fins/earnings-date", plan="Free",
         entitlement_status=ENTITLEMENT_UNKNOWN, strategy_status=DEFERRED,
         frequency_class=EVENT_DRIVEN,
         publication_semantics="run #1: HTTP 400（パラメータ契約違い）。entitlement 未確定",
         historical_depth="未測定", pagination="未測定",
         request_pattern="code / date / scheduled_date のいずれか1つ（応答メッセージ）",
         canonical_store="なし", consumers=(), morning_role=ROLE_NONE,
         fallback_policy="equities_earnings_cal で用途充足", last_live_verified_at=P2H_RUN1,
         note="用途重複のため DEFERRED。再probeしない"),
    # ---- NOT_ENTITLED（run #1 で 403 実測。**再probeしない・迂回しない**）
    _cap(dataset="indices_bars_daily", endpoint="/indices/bars/daily", plan="Standard",
         entitlement_status=NOT_ENTITLED, strategy_status=PLAN_UPGRADE_CANDIDATE,
         frequency_class=DAILY, publication_semantics="TOPIX以外の指数四本値",
         historical_depth="未取得", pagination="未取得", request_pattern="未取得",
         canonical_store="なし", consumers=(), morning_role=ROLE_NONE,
         fallback_policy="Nikkei225 は legacy approved source（Market Data Bank）で充足",
         last_live_verified_at=P2H_RUN1 + " HTTP 403"),
    _cap(dataset="fins_dividend", endpoint="/fins/dividend", plan="Standard",
         entitlement_status=NOT_ENTITLED, strategy_status=DEFERRED, frequency_class=EVENT_DRIVEN,
         publication_semantics="配当", historical_depth="未取得", pagination="未取得",
         request_pattern="未取得", canonical_store="なし", consumers=(), morning_role=ROLE_NONE,
         fallback_policy="Morning Compass に不要", last_live_verified_at=P2H_RUN1 + " HTTP 403"),
    _cap(dataset="fins_details", endpoint="/fins/details", plan="Standard",
         entitlement_status=NOT_ENTITLED, strategy_status=DEFERRED, frequency_class=EVENT_DRIVEN,
         publication_semantics="詳細財務", historical_depth="未取得", pagination="未取得",
         request_pattern="未取得", canonical_store="なし", consumers=(), morning_role=ROLE_NONE,
         fallback_policy="fins_summary で充足", last_live_verified_at=P2H_RUN1 + " HTTP 403"),
    _cap(dataset="markets_short_ratio", endpoint="/markets/short-ratio", plan="Standard",
         entitlement_status=NOT_ENTITLED, strategy_status=PLAN_UPGRADE_CANDIDATE,
         frequency_class=DAILY, publication_semantics="業種別空売り比率",
         historical_depth="未取得", pagination="未取得", request_pattern="未取得",
         canonical_store="なし", consumers=(), morning_role=ROLE_NONE,
         fallback_policy="代替なし（需給次元は investor_types 週次で部分充足）",
         last_live_verified_at=P2H_RUN1 + " HTTP 403"),
    _cap(dataset="equities_bars_am", endpoint="/equities/bars/daily/am", plan="Premium",
         entitlement_status=NOT_ENTITLED, strategy_status=DEFERRED, frequency_class=DAILY,
         publication_semantics="前場四本値", historical_depth="未取得", pagination="未取得",
         request_pattern="未取得", canonical_store="なし", consumers=(), morning_role=ROLE_NONE,
         fallback_policy="朝のCompassは前営業日クローズ基準のため不要",
         last_live_verified_at=P2H_RUN1 + " HTTP 403"),
    _cap(dataset="markets_breakdown", endpoint="/markets/breakdown", plan="Premium",
         entitlement_status=NOT_ENTITLED, strategy_status=DEFERRED, frequency_class=DAILY,
         publication_semantics="売買内訳", historical_depth="未取得", pagination="未取得",
         request_pattern="未取得", canonical_store="なし", consumers=(), morning_role=ROLE_NONE,
         fallback_policy="代替なし", last_live_verified_at=P2H_RUN1 + " HTTP 403"),
    # ---- J-Quants Light に無いデータで、承認済み代替 source を使うもの（J-Quants First 監査用）
    _cap(dataset="nikkei225", endpoint="(not J-Quants) legacy yfinance ^N225 / Market Data Bank",
         plan="n/a", entitlement_status=NOT_ENTITLED, strategy_status=ALTERNATIVE_APPROVED_SOURCE,
         frequency_class=DAILY, publication_semantics="前営業日終値",
         historical_depth="Market Data Bank", pagination="n/a", request_pattern="n/a",
         canonical_store="databank/market/normalized/observations.jsonl", consumers=("facts", "context"),
         morning_role=ROLE_REQUIRED, fallback_policy="J-Quants indices_bars_daily は Standard（NOT_ENTITLED）",
         last_live_verified_at=RUN20, note="J-Quants Light では取得不可のため承認済み代替を継続"),
    _cap(dataset="usd_jpy", endpoint="(not J-Quants) legacy yfinance JPY=X / Market Data Bank",
         plan="n/a", entitlement_status=NOT_ENTITLED, strategy_status=ALTERNATIVE_APPROVED_SOURCE,
         frequency_class=DAILY, publication_semantics="前日終値（global）",
         historical_depth="Market Data Bank", pagination="n/a", request_pattern="n/a",
         canonical_store="databank/market/normalized/observations.jsonl", consumers=("facts", "context"),
         morning_role=ROLE_OPTIONAL, fallback_policy="J-Quants に為替 endpoint なし",
         last_live_verified_at=RUN20),
    _cap(dataset="us_treasury_par", endpoint="(not J-Quants) US Treasury par yield CSV",
         plan="n/a", entitlement_status=NOT_ENTITLED, strategy_status=ALTERNATIVE_APPROVED_SOURCE,
         frequency_class=DAILY, publication_semantics="米国営業日の公表値",
         historical_depth="Market Data Bank", pagination="n/a", request_pattern="n/a",
         canonical_store="databank/market/normalized/observations.jsonl", consumers=("facts", "context"),
         morning_role=ROLE_OPTIONAL, fallback_policy="J-Quants に米金利 endpoint なし",
         last_live_verified_at=RUN20),
    _cap(dataset="jgb10y", endpoint="(not J-Quants) MOF JGB yield CSV",
         plan="n/a", entitlement_status=NOT_ENTITLED, strategy_status=ALTERNATIVE_APPROVED_SOURCE,
         frequency_class=DAILY, publication_semantics="財務省公表値（15時）",
         historical_depth="Market Data Bank", pagination="n/a", request_pattern="n/a",
         canonical_store="databank/market/normalized/observations.jsonl", consumers=("facts", "context"),
         morning_role=ROLE_OPTIONAL, fallback_policy="J-Quants に国債利回り endpoint なし",
         last_live_verified_at=RUN20),
)}

#: J-Quants endpoint（代替 source を除く）
JQUANTS_DATASETS: Tuple[str, ...] = tuple(
    k for k, c in REGISTRY.items() if c.strategy_status != ALTERNATIVE_APPROVED_SOURCE)


def dataset(key: str) -> DatasetCapability:
    return REGISTRY[key]


def by_status(status: str) -> List[DatasetCapability]:
    return [c for c in REGISTRY.values()
            if status in (c.entitlement_status, c.strategy_status)]


def morning_datasets(*roles: str) -> List[DatasetCapability]:
    wanted = set(roles) if roles else {ROLE_REQUIRED, ROLE_INTERNALS, ROLE_OPTIONAL}
    return [c for c in REGISTRY.values() if c.morning_role in wanted]


def registry_rows() -> List[Dict[str, object]]:
    return [c.as_dict() for c in REGISTRY.values()]


def frequency_table() -> Dict[str, List[str]]:
    out: Dict[str, List[str]] = {f: [] for f in FREQUENCY_CLASSES}
    for c in REGISTRY.values():
        out[c.frequency_class].append(c.dataset)
    return out
