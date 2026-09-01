"""J-Quants **Light plan** core dataset レジストリ（Phase 2-H STEP 2/3/19）。

**取得可能だから実装するのではなく、「どのInvestment Intelligence機能で使うのか」が
説明できるdatasetだけを採用する**（MINIMAL / REUSABLE / AUDITABLE / FAIL-CLOSED）。

entitlement・endpoint・項目名はすべて **live probe run #1（2026-09-01）の実測**
に基づく。公式ドキュメントからの類推でAVAILABLE扱いしたものは無い。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, Mapping, Optional, Tuple

#: core data分類（STEP 3）
REQUIRED = "REQUIRED"
USEFUL = "USEFUL"
DEFER = "DEFER"

#: entitlement（実測）
AVAILABLE = "AVAILABLE"
NOT_ENTITLED = "NOT_ENTITLED"
UNKNOWN = "UNKNOWN"

#: 更新頻度
DAILY = "daily"
WEEKLY = "weekly"
EVENT_DRIVEN = "event_driven"
SNAPSHOT = "snapshot"


@dataclass(frozen=True, kw_only=True)
class LightDataset:
    """1 datasetの契約（endpoint・必須項目・用途・分類）。"""

    key: str
    path: str
    entitlement: str
    classification: str
    frequency: str
    #: 実測で確認した必須項目（不足があればschema_errorで**1行も取り込まない**）
    required_fields: Tuple[str, ...] = ()
    #: 実測で観測した項目名の全量（schema変化の検知に使う）
    observed_fields: Tuple[str, ...] = ()
    #: **どの機能で使うのか**（説明できないdatasetは採用しない）
    investment_use: str = ""
    #: 既定パラメータ（呼び出し側が上書きできる）
    default_params: Mapping[str, str] = field(default_factory=dict)
    #: 実測メモ（件数・日付レンジ・制約など）
    evidence: str = ""
    #: 採用しない理由（DEFER/NOT_ENTITLEDのとき）
    note: str = ""
    #: **どのストアが所有するか**（二重保管＝二重の真実を作らないための宣言）。
    #: "jquants_light" … P2-Hのlight store / "market_bank" … 既存Market Data Bank
    ingestion_owner: str = "jquants_light"


#: ---------------------------------------------------------------- REQUIRED
_REQUIRED: Tuple[LightDataset, ...] = (
    LightDataset(
        key="listed_master", path="/equities/master",
        entitlement=AVAILABLE, classification=REQUIRED, frequency=SNAPSHOT,
        required_fields=("Code", "Date", "CoName"),
        observed_fields=("CoName", "CoNameEn", "Code", "Date", "Mkt", "MktNm",
                         "Mrgn", "MrgnNm", "ProdCat", "S17", "S17Nm", "S33",
                         "S33Nm", "ScaleCat"),
        investment_use="日本株のsecurity master。Company Intelligence / "
                       "Long-Term Screener / Japan Market Internals が銘柄・市場区分・"
                       "業種（17/33）・規模区分で母集団を定義するための基盤。",
        evidence="run #1: 200 / 4,441件 / Date=2026-09-01 / pagination無し"),
    LightDataset(
        key="daily_bars", path="/equities/bars/daily",
        entitlement=AVAILABLE, classification=REQUIRED, frequency=DAILY,
        required_fields=("Code", "Date", "C"),
        observed_fields=("AdjC", "AdjFactor", "AdjH", "AdjL", "AdjO", "AdjVo",
                         "C", "Code", "Date", "ExRT", "H", "L", "LL", "MktCap",
                         "O", "UL", "Va", "Vo"),
        investment_use="個別銘柄の日次価格。Morning Compass（銘柄の値動き）・"
                       "Japan Market Internals（騰落・売買代金）・Screener（長期リターン）"
                       "の一次入力。",
        default_params={"code": "72030"},
        evidence="run #1: 200 / code指定9件 / 生四本値(O/H/L/C)と調整後(Adj*)＋"
                 "AdjFactorが別項目で併存 / MktCap・売買代金Vaあり"),
    LightDataset(
        key="fins_summary", path="/fins/summary",
        entitlement=AVAILABLE, classification=REQUIRED, frequency=EVENT_DRIVEN,
        required_fields=("Code", "DiscDate"),
        observed_fields=("Code", "DiscDate", "DiscTime", "DiscNo", "DocType",
                         "CurPerType", "CurFYSt", "CurFYEn", "CurPerSt", "CurPerEn",
                         "NxtFYSt", "NxtFYEn", "Sales", "OP", "OdP", "NP", "EPS",
                         "DEPS", "BPS", "ROE", "TA", "Eq", "EqAR", "ShEq",
                         "CFO", "CFI", "CFF", "CashEq", "FSales", "FOP", "FOdP",
                         "FNP", "FEPS", "NxFSales", "NxFOP", "NxFOdP", "NxFNp",
                         "NxFEPS", "RetroRst", "AvgSh", "ShOutFY", "TrShFY"),
        investment_use="財務サマリー（実績＋会社予想）。Company Intelligence・"
                       "Long-Term Screener の一次入力。**P2-Hではscore/推奨を作らず"
                       "raw/normalizedまで**。",
        default_params={"code": "72030"},
        evidence="run #1: 200 / code指定20件 / 実績・会社予想(F*)・翌期予想(NxF*)・"
                 "単体(NC*)が別項目で併存"),
    LightDataset(
        key="equities_earnings_cal", path="/equities/earnings-calendar",
        entitlement=AVAILABLE, classification=REQUIRED, frequency=EVENT_DRIVEN,
        required_fields=("Code", "Date"),
        observed_fields=("CoName", "Code", "Date", "FQ", "FY", "Section", "SectorNm"),
        investment_use="決算発表予定。Morning Brief / Watchlist が「決算まで何日」を"
                       "計算するための基盤。",
        evidence="run #1: 200 / 1件（3・9月期決算会社のみ・Date=2026-08-17）"),
    LightDataset(
        key="markets_calendar", path="/markets/calendar",
        entitlement=AVAILABLE, classification=REQUIRED, frequency=SNAPSHOT,
        required_fields=("Date", "HolDiv"),
        observed_fields=("Date", "HolDiv"),
        investment_use="東証取引カレンダー。**latest completed Tokyo session** の"
                       "正式判定基盤（P2-G.2のNikkei参照系列依存を補強する）。",
        evidence="run #1: 200 / 2026-08-01〜09-30で61件（暦日ベース・HolDivで区分）"),
    LightDataset(
        key="topix", path="/indices/bars/daily/topix",
        entitlement=AVAILABLE, classification=REQUIRED, frequency=DAILY,
        required_fields=("Date", "C"),
        observed_fields=("C", "Date", "H", "L", "O"),
        investment_use="TOPIX指数。P2-G.2で解決済み（G10 RESOLVED）。NT倍率・"
                       "Morning Compassの東京市場ベンチマーク。",
        ingestion_owner="market_bank",
        note="**P2-Hのlight storeへは保存しない**。TOPIXは既にMarket Data Bankの"
             "Observation系列（index:topix.close.closing.tokyo）として正規に"
             "取り込まれており、二重保管は二重の真実を生む。P2-Hでは"
             "(1) V2経路のregression確認 (2) 取引カレンダー区分の実測検証 "
             "の入力としてのみ使う。",
        evidence="run #1: 200 / 項目はP2-G.2実測と一致（C/Date/H/L/O）"),
)

#: ---------------------------------------------------------------- USEFUL
_USEFUL: Tuple[LightDataset, ...] = (
    LightDataset(
        key="investor_types", path="/equities/investor-types",
        entitlement=AVAILABLE, classification=USEFUL, frequency=WEEKLY,
        required_fields=("Section", "PubDate", "StDate", "EnDate"),
        observed_fields=("Section", "PubDate", "StDate", "EnDate",
                         "FrgnBuy", "FrgnSell", "FrgnBal", "FrgnTot",
                         "IndBuy", "IndSell", "IndBal", "IndTot",
                         "TrstBnkBuy", "TrstBnkSell", "TrstBnkBal", "TrstBnkTot",
                         "BusCoBuy", "BusCoSell", "BusCoBal", "BusCoTot",
                         "TotBuy", "TotSell", "TotBal", "TotTot"),
        investment_use="投資部門別売買動向。Japan Market Internals の需給観測。"
                       "**週次**であり日次market flowとして扱わない——"
                       "PubDate（公表日）とStDate/EnDate（対象期間）を分離して保存する。",
        evidence="run #1: 200 / 2026-07-01〜09-01で36件 / 週次・公表日と対象期間が別項目"),
)

#: ---------------------------------------------------------------- DEFER
_DEFER: Tuple[LightDataset, ...] = (
    LightDataset(
        key="fins_earnings_date", path="/fins/earnings-date",
        entitlement=UNKNOWN, classification=DEFER, frequency=EVENT_DRIVEN,
        investment_use="決算発表予定日（equities_earnings_calと用途が重複する可能性）。",
        note="run #1で **HTTP 400**: 'Specify exactly one of the following "
             "parameters: code, date, or scheduled_date.' —— endpointは実在し"
             "パラメータ契約が異なるだけ。entitlementは未確定のため"
             "**UNKNOWNのまま**にしてAVAILABLE扱いしない。用途はequities_earnings_calで"
             "充足するためP2-Hでは採用しない。"),
)

#: ------------------------------------------- NOT_ENTITLED（迂回実装しない証拠）
_NOT_ENTITLED: Tuple[LightDataset, ...] = tuple(
    LightDataset(key=key, path=path, entitlement=NOT_ENTITLED,
                 classification=DEFER, frequency=DAILY,
                 investment_use=use,
                 note="run #1実測: HTTP 403 'This API is not available on your "
                      "subscription.' —— Light契約の対象外。**別endpointでの"
                      "迂回実装はしない**（プラン制約をコードで回避しない）。")
    for key, path, use in (
        ("indices_bars_daily", "/indices/bars/daily",
         "TOPIX以外の指数四本値（Japan Market Internals の指数横断）"),
        ("fins_dividend", "/fins/dividend", "配当（Screenerのインカム観点）"),
        ("fins_details", "/fins/details", "詳細財務（Company Intelligence 深掘り）"),
        ("markets_short_ratio", "/markets/short-ratio", "業種別空売り比率（需給）"),
        ("equities_bars_am", "/equities/bars/daily/am", "前場四本値（Morning Compass当日性）"),
        ("markets_breakdown", "/markets/breakdown", "売買内訳（需給）"),
    )
)

#: 全datasetの索引
ALL_DATASETS: Dict[str, LightDataset] = {
    d.key: d for d in (_REQUIRED + _USEFUL + _DEFER + _NOT_ENTITLED)
}

#: P2-Hのlight storeが**保存する**dataset（REQUIRED+USEFUL・AVAILABLE・所有者がlight）
INGESTED_DATASETS: Tuple[LightDataset, ...] = tuple(
    d for d in (_REQUIRED + _USEFUL)
    if d.entitlement == AVAILABLE and d.classification in (REQUIRED, USEFUL)
    and d.ingestion_owner == "jquants_light"
)

#: 取得はするが保存は既存Market Data Bankが担うdataset（二重保管しない）
MARKET_BANK_OWNED: Tuple[LightDataset, ...] = tuple(
    d for d in (_REQUIRED + _USEFUL) if d.ingestion_owner == "market_bank"
)


def get_dataset(key: str) -> Optional[LightDataset]:
    return ALL_DATASETS.get(key)


def capability_matrix() -> Tuple[Dict[str, str], ...]:
    """STEP 19: dataset × Light可用性 × 用途 × 実装状況の一覧。"""
    ingested = {d.key for d in INGESTED_DATASETS}
    return tuple(
        {
            "dataset": d.key,
            "endpoint": d.path,
            "light_availability": d.entitlement,
            "classification": d.classification,
            "frequency": d.frequency,
            "investment_use": d.investment_use,
            "ingestion_owner": d.ingestion_owner,
            "implementation_status": (
                "INGESTED_LIGHT_STORE" if d.key in ingested
                else "INGESTED_MARKET_BANK" if d.ingestion_owner == "market_bank"
                else "NOT_IMPLEMENTED"),
            "evidence": d.evidence or d.note,
        }
        for d in ALL_DATASETS.values()
    )
