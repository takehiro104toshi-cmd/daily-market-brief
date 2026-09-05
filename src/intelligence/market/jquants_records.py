"""J-Quants Light core の構造化レコード（Phase 2-H STEP 4/5/7/8/9/10/11/12）。

**God Objectを作らない**: dataset種別ごとに別recordへ分離する。時系列observation
（`market.model.Observation`）とは責務が違う——会社名や市場区分は「観測値」ではない
ため、Observationへ押し込まない。

共通規律:
- 値は**stringトークンのまま**保持し、数値化が必要なものだけDecimalへ（float非経由）。
- 欠測は欠測のまま（0や前値で埋めない）。
- 全recordが `RecordProvenance` を必須で持つ（source / provider / api_version /
  endpoint family / retrieved_at / raw参照 / normalizer version）。
- **identityを潰さない**:
  - Company（企業）と listed security（上場銘柄）を同一視しない。
  - raw close と adjusted close を同一視しない。
  - 公表日（PubDate）と対象期間（StDate/EnDate）を同一視しない。

項目名はすべて **live probe run #1（2026-09-01）の実測**に基づく（V2は項目名が
短縮されているため、旧仕様・他datasetからの類推でmappingしない）。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from typing import Dict, Mapping, Optional, Tuple

#: normalizer版数（mapping規則を変えたら上げる。provenanceへ載る）
NORMALIZER_VERSION = "jquants_light_normalizer:1.0.0"

#: security_idの名前空間（tickerそのものをIDにしない——市場や体系が変わりうるため）
SECURITY_ID_PREFIX = "jp:security"


@dataclass(frozen=True, kw_only=True)
class RecordProvenance:
    """全J-Quants recordが持つ出所情報（STEP 12）。"""

    source: str = "jquants"          # 一次公表元（JPX系）
    provider: str = "jquants"        # 取得プロバイダ
    api_version: str = "v2"
    endpoint: str = ""               # endpoint family（/equities/master 等）
    retrieved_at: str = ""           # 取得時刻（UTC ISO8601）
    raw_item_id: str = ""            # RawItem参照（生応答へ辿れる）
    fetch_attempt_id: str = ""
    normalizer_version: str = NORMALIZER_VERSION

    def as_dict(self) -> Dict[str, str]:
        return {
            "source": self.source, "provider": self.provider,
            "api_version": self.api_version, "endpoint": self.endpoint,
            "retrieved_at": self.retrieved_at, "raw_item_id": self.raw_item_id,
            "fetch_attempt_id": self.fetch_attempt_id,
            "normalizer_version": self.normalizer_version,
        }


def _text(row: Mapping, key: str) -> str:
    """stringトークンをそのまま取り出す（欠測は空文字）。"""
    value = row.get(key)
    return "" if value is None else str(value).strip()


def to_decimal(token: str) -> Optional[Decimal]:
    """stringトークン→Decimal（float非経由）。空・非数値はNone（**0で埋めない**）。"""
    if token == "":
        return None
    try:
        return Decimal(token)
    except (InvalidOperation, ValueError):
        return None


def security_id_for(code: str) -> str:
    return f"{SECURITY_ID_PREFIX}:{code}"


# ============================================================ STEP 4: security master

@dataclass(frozen=True, kw_only=True)
class SecurityMasterRecord:
    """上場銘柄（tradable/listed security）1件。

    **Company entity とは別概念**: 本recordは「市場に上場している銘柄」を表す。
    企業そのもの（Entity Catalogのcompany entity）とは1対1とは限らず、
    上場廃止・市場変更・複数上場があり得る。`company_name` は銘柄に紐づく
    表示名として保持するだけで、company entityのidentityは張らない
    （既存Entity Catalogの責務を侵さない）。
    """

    security_id: str
    code: str                       # J-Quants Code（実測は5桁）
    company_name: str = ""
    company_name_en: str = ""
    market_code: str = ""           # Mkt
    market_name: str = ""           # MktNm
    sector17_code: str = ""         # S17
    sector17_name: str = ""         # S17Nm
    sector33_code: str = ""         # S33
    sector33_name: str = ""         # S33Nm
    scale_category: str = ""        # ScaleCat
    margin_code: str = ""           # Mrgn
    margin_name: str = ""           # MrgnNm
    product_category: str = ""      # ProdCat
    effective_date: str = ""        # Date（この銘柄情報が有効な基準日）
    listing_status: str = "listed"  # 本endpointは上場銘柄一覧のため既定はlisted
    provenance: RecordProvenance = field(default_factory=RecordProvenance)

    @property
    def record_id(self) -> str:
        return f"sec_{self.code}_{self.effective_date}"


def parse_security_master(row: Mapping, provenance: RecordProvenance) -> Optional[SecurityMasterRecord]:
    code = _text(row, "Code")
    if not code:
        return None
    return SecurityMasterRecord(
        security_id=security_id_for(code), code=code,
        company_name=_text(row, "CoName"), company_name_en=_text(row, "CoNameEn"),
        market_code=_text(row, "Mkt"), market_name=_text(row, "MktNm"),
        sector17_code=_text(row, "S17"), sector17_name=_text(row, "S17Nm"),
        sector33_code=_text(row, "S33"), sector33_name=_text(row, "S33Nm"),
        scale_category=_text(row, "ScaleCat"),
        margin_code=_text(row, "Mrgn"), margin_name=_text(row, "MrgnNm"),
        product_category=_text(row, "ProdCat"),
        effective_date=_text(row, "Date"), provenance=provenance)


# ============================================================ STEP 5: daily price

@dataclass(frozen=True, kw_only=True)
class DailyPriceRecord:
    """個別銘柄の日次価格1件。

    **PRICE IDENTITY（混同禁止）**:
    - `close` … 生の終値（O/H/L/C の C）。その日に実際についた値段。
    - `adjusted_close` … 分割・併合等の調整後終値（AdjC）。時系列比較用。
    - `adjustment_factor` … 当日の調整係数（AdjFactor）。
    - total return（配当込みリターン）は**このsourceに存在しない**——作らない。
    生と調整後を同じフィールドへ入れない・相互に代替しない。
    """

    security_id: str
    code: str
    trading_date: str               # Date（取引日。as_ofとは別概念）
    as_of: str = ""                 # 東京現物クローズのUTC時刻（呼び出し側が付与）
    open: str = ""                  # O
    high: str = ""                  # H
    low: str = ""                   # L
    close: str = ""                 # C（**生**の終値）
    volume: str = ""                # Vo（出来高）
    turnover_value: str = ""        # Va（売買代金）
    adjusted_open: str = ""         # AdjO
    adjusted_high: str = ""         # AdjH
    adjusted_low: str = ""          # AdjL
    adjusted_close: str = ""        # AdjC（**調整後**の終値）
    adjusted_volume: str = ""       # AdjVo
    adjustment_factor: str = ""     # AdjFactor
    upper_limit: str = ""           # UL
    lower_limit: str = ""           # LL
    market_cap: str = ""            # MktCap
    provenance: RecordProvenance = field(default_factory=RecordProvenance)

    @property
    def record_id(self) -> str:
        return f"px_{self.code}_{self.trading_date}"

    @property
    def close_decimal(self) -> Optional[Decimal]:
        return to_decimal(self.close)

    @property
    def adjusted_close_decimal(self) -> Optional[Decimal]:
        return to_decimal(self.adjusted_close)


def parse_daily_price(row: Mapping, provenance: RecordProvenance) -> Optional[DailyPriceRecord]:
    code, trading_date = _text(row, "Code"), _text(row, "Date")
    if not code or not trading_date:
        return None
    return DailyPriceRecord(
        security_id=security_id_for(code), code=code, trading_date=trading_date,
        open=_text(row, "O"), high=_text(row, "H"), low=_text(row, "L"),
        close=_text(row, "C"), volume=_text(row, "Vo"),
        turnover_value=_text(row, "Va"),
        adjusted_open=_text(row, "AdjO"), adjusted_high=_text(row, "AdjH"),
        adjusted_low=_text(row, "AdjL"), adjusted_close=_text(row, "AdjC"),
        adjusted_volume=_text(row, "AdjVo"),
        adjustment_factor=_text(row, "AdjFactor"),
        upper_limit=_text(row, "UL"), lower_limit=_text(row, "LL"),
        market_cap=_text(row, "MktCap"), provenance=provenance)


# ============================================================ STEP 7: financial summary

@dataclass(frozen=True, kw_only=True)
class FinancialSummaryRecord:
    """財務サマリー1件（開示単位）。

    **実績 / 会社予想 / 翌期予想を混同しない**:
    - 実績: Sales / OP / OdP / NP / EPS ...
    - 当期会社予想: F* （FSales / FOP / FOdP / FNP / FEPS）
    - 翌期会社予想: NxF*（NxFSales / NxFOP / NxFOdP / NxFNp / NxFEPS）
    連結(既定)と単体(NC*)も別概念だが、P2-Hでは**連結ベースの主要項目**に絞る
    （必要になった時点でNC*を別フィールドとして追加する——推測で混ぜない）。

    **P2-Hはraw/normalizedまで**。growth/quality/valuation score・推奨は作らない。
    """

    security_id: str
    code: str
    disclosed_date: str             # DiscDate（開示日）
    disclosed_time: str = ""        # DiscTime
    disclosure_number: str = ""     # DiscNo（開示単位の識別子）
    document_type: str = ""         # DocType
    period_type: str = ""           # CurPerType（四半期区分等）
    fiscal_year_start: str = ""     # CurFYSt
    fiscal_year_end: str = ""       # CurFYEn
    period_start: str = ""          # CurPerSt
    period_end: str = ""            # CurPerEn
    next_fiscal_year_start: str = ""  # NxtFYSt
    next_fiscal_year_end: str = ""    # NxtFYEn
    # --- 実績
    net_sales: str = ""             # Sales
    operating_profit: str = ""      # OP
    ordinary_profit: str = ""       # OdP
    net_profit: str = ""            # NP
    eps: str = ""                   # EPS
    diluted_eps: str = ""           # DEPS
    bps: str = ""                   # BPS
    roe: str = ""                   # ROE
    total_assets: str = ""          # TA
    equity: str = ""                # Eq
    equity_ratio: str = ""          # EqAR
    cash_flow_operating: str = ""   # CFO
    cash_flow_investing: str = ""   # CFI
    cash_flow_financing: str = ""   # CFF
    cash_and_equivalents: str = ""  # CashEq
    # --- 当期会社予想
    forecast_net_sales: str = ""    # FSales
    forecast_operating_profit: str = ""  # FOP
    forecast_ordinary_profit: str = ""   # FOdP
    forecast_net_profit: str = ""   # FNP
    forecast_eps: str = ""          # FEPS
    # --- 翌期会社予想
    next_forecast_net_sales: str = ""    # NxFSales
    next_forecast_operating_profit: str = ""  # NxFOP
    next_forecast_ordinary_profit: str = ""   # NxFOdP
    next_forecast_net_profit: str = ""        # NxFNp
    next_forecast_eps: str = ""     # NxFEPS
    # --- 修正・遡及の文脈（revision context）
    retrospective_restatement: str = ""   # RetroRst
    provenance: RecordProvenance = field(default_factory=RecordProvenance)

    @property
    def record_id(self) -> str:
        key = self.disclosure_number or f"{self.disclosed_date}_{self.period_end}"
        return f"fin_{self.code}_{key}"


def parse_financial_summary(row: Mapping, provenance: RecordProvenance) -> Optional[FinancialSummaryRecord]:
    code, disclosed = _text(row, "Code"), _text(row, "DiscDate")
    if not code or not disclosed:
        return None
    return FinancialSummaryRecord(
        security_id=security_id_for(code), code=code, disclosed_date=disclosed,
        disclosed_time=_text(row, "DiscTime"), disclosure_number=_text(row, "DiscNo"),
        document_type=_text(row, "DocType"), period_type=_text(row, "CurPerType"),
        fiscal_year_start=_text(row, "CurFYSt"), fiscal_year_end=_text(row, "CurFYEn"),
        period_start=_text(row, "CurPerSt"), period_end=_text(row, "CurPerEn"),
        next_fiscal_year_start=_text(row, "NxtFYSt"), next_fiscal_year_end=_text(row, "NxtFYEn"),
        net_sales=_text(row, "Sales"), operating_profit=_text(row, "OP"),
        ordinary_profit=_text(row, "OdP"), net_profit=_text(row, "NP"),
        eps=_text(row, "EPS"), diluted_eps=_text(row, "DEPS"), bps=_text(row, "BPS"),
        roe=_text(row, "ROE"), total_assets=_text(row, "TA"), equity=_text(row, "Eq"),
        equity_ratio=_text(row, "EqAR"), cash_flow_operating=_text(row, "CFO"),
        cash_flow_investing=_text(row, "CFI"), cash_flow_financing=_text(row, "CFF"),
        cash_and_equivalents=_text(row, "CashEq"),
        forecast_net_sales=_text(row, "FSales"), forecast_operating_profit=_text(row, "FOP"),
        forecast_ordinary_profit=_text(row, "FOdP"), forecast_net_profit=_text(row, "FNP"),
        forecast_eps=_text(row, "FEPS"),
        next_forecast_net_sales=_text(row, "NxFSales"),
        next_forecast_operating_profit=_text(row, "NxFOP"),
        next_forecast_ordinary_profit=_text(row, "NxFOdP"),
        next_forecast_net_profit=_text(row, "NxFNp"),
        next_forecast_eps=_text(row, "NxFEPS"),
        retrospective_restatement=_text(row, "RetroRst"), provenance=provenance)


# ============================================================ STEP 8: earnings schedule

@dataclass(frozen=True, kw_only=True)
class EarningsScheduleRecord:
    """決算発表予定1件（「決算まで何日」を将来計算できる形にする）。"""

    security_id: str
    code: str
    announcement_date: str          # Date（発表予定日）
    company_name: str = ""          # CoName
    fiscal_quarter: str = ""        # FQ
    fiscal_year: str = ""           # FY
    section: str = ""               # Section
    sector_name: str = ""           # SectorNm
    provenance: RecordProvenance = field(default_factory=RecordProvenance)

    @property
    def record_id(self) -> str:
        return f"ern_{self.code}_{self.announcement_date}"


def parse_earnings_schedule(row: Mapping, provenance: RecordProvenance) -> Optional[EarningsScheduleRecord]:
    code, date_ = _text(row, "Code"), _text(row, "Date")
    if not code or not date_:
        return None
    return EarningsScheduleRecord(
        security_id=security_id_for(code), code=code, announcement_date=date_,
        company_name=_text(row, "CoName"), fiscal_quarter=_text(row, "FQ"),
        fiscal_year=_text(row, "FY"), section=_text(row, "Section"),
        sector_name=_text(row, "SectorNm"), provenance=provenance)


# ============================================================ STEP 9: trading calendar

@dataclass(frozen=True, kw_only=True)
class TradingCalendarRecord:
    """東証取引カレンダー1日分。

    `holiday_division`（HolDiv）は**source側のコード値をそのまま保持**する。
    「どの値が営業日か」は推測せず、実データとの突き合わせで確定する
    （`tokyo_calendar` モジュール参照）。
    """

    calendar_date: str              # Date
    holiday_division: str           # HolDiv（source原値）
    provenance: RecordProvenance = field(default_factory=RecordProvenance)

    @property
    def record_id(self) -> str:
        return f"cal_{self.calendar_date}"


def parse_trading_calendar(row: Mapping, provenance: RecordProvenance) -> Optional[TradingCalendarRecord]:
    date_ = _text(row, "Date")
    if not date_:
        return None
    return TradingCalendarRecord(
        calendar_date=date_, holiday_division=_text(row, "HolDiv"),
        provenance=provenance)


# ============================================================ STEP 10: investor-type flow

@dataclass(frozen=True, kw_only=True)
class InvestorTypeFlowRecord:
    """投資部門別売買動向1件（**週次**）。

    **temporal semantics（混同禁止）**:
    - `published_date`（PubDate） … 公表日
    - `period_start` / `period_end`（StDate / EnDate） … 対象期間
    - `frequency` = weekly —— 日次market flowとして扱わない。

    **P2-Hでは「海外投資家が買っている」等のanalysisを生成しない**。
    structured recordとして保存するだけ。
    """

    section: str                    # Section（市場区分）
    published_date: str             # PubDate
    period_start: str               # StDate
    period_end: str                 # EnDate
    frequency: str = "weekly"
    #: 投資部門ごとの {buy, sell, total, balance}（stringトークンのまま）
    flows: Mapping[str, Mapping[str, str]] = field(default_factory=dict)
    provenance: RecordProvenance = field(default_factory=RecordProvenance)

    @property
    def record_id(self) -> str:
        return f"flow_{self.section}_{self.period_start}_{self.period_end}"


#: 実測field名の接頭辞 → 投資部門名（run #1で観測したもののみ）
INVESTOR_TYPE_PREFIXES: Tuple[Tuple[str, str], ...] = (
    ("Frgn", "foreign_investors"),
    ("Ind", "individuals"),
    ("TrstBnk", "trust_banks"),
    ("BusCo", "business_corporations"),
    ("InsCo", "insurance_companies"),
    ("InvTr", "investment_trusts"),
    ("Bank", "banks"),
    ("OthFin", "other_financial_institutions"),
    ("SecCo", "securities_companies"),
    ("OthCo", "other_corporations"),
    ("Brk", "brokerages"),
    ("Prop", "proprietary"),
    ("Tot", "total"),
)


def parse_investor_type_flow(row: Mapping, provenance: RecordProvenance) -> Optional[InvestorTypeFlowRecord]:
    published = _text(row, "PubDate")
    start, end = _text(row, "StDate"), _text(row, "EnDate")
    if not published or not start or not end:
        return None
    flows: Dict[str, Dict[str, str]] = {}
    for prefix, name in INVESTOR_TYPE_PREFIXES:
        entry = {
            "buy": _text(row, f"{prefix}Buy"),
            "sell": _text(row, f"{prefix}Sell"),
            "total": _text(row, f"{prefix}Tot"),
            "balance": _text(row, f"{prefix}Bal"),
        }
        if any(entry.values()):
            flows[name] = entry
    return InvestorTypeFlowRecord(
        section=_text(row, "Section"), published_date=published,
        period_start=start, period_end=end, flows=flows, provenance=provenance)


#: dataset key → (record class, parser)
PARSERS = {
    "listed_master": parse_security_master,
    "daily_bars": parse_daily_price,
    "fins_summary": parse_financial_summary,
    "equities_earnings_cal": parse_earnings_schedule,
    "markets_calendar": parse_trading_calendar,
    "investor_types": parse_investor_type_flow,
}
