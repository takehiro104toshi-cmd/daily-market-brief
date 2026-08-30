"""TOPIXのfreshness判定とG10 gap状態（Phase 2-G.1 STEP 4/5/8）。

監督者指示の3区別を型で分ける:
  1. API CONNECTION（接続できたか）
  2. HISTORICAL DATA AVAILABILITY（25DMA以上の履歴があるか）
  3. CURRENT / MORNING-USABLE（Morning Compassの当日入力として使えるか）

**DO NOT LIE ABOUT FRESHNESS**: fetch成功だけでRESOLVEDにしない。
遅延データしか無ければ HISTORICAL_RESOLVED_CURRENT_BLOCKED として区別する。

判定基準（休日カレンダーを推測しない）:
- 同一取引所セッション（東京・現物指数15:30クローズ）の**実データ**を基準系列
  （既定: 日経平均）として使い、TOPIXの最新trading_dateが基準系列の最新
  セッションに追いついているかで判定する。祝日・臨時休場を暦から当てにいかない。
- 基準系列が無い場合のみ lag_days の閾値で暫定判定し、その事実をreason codeで
  明示する（弱い根拠であることを隠さない）。
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from typing import Dict, List, Optional, Tuple

TOPIX_SERIES_ID = "index:topix.close.closing.tokyo"
#: 同一セッション（東京現物・15:30クローズ）の基準系列
REFERENCE_SERIES_ID = "index:nikkei225.close.closing.tokyo"

#: 25DMA計算に必要な最低観測数（監督者要件）
MIN_HISTORY_ROWS = 25
#: 基準系列が使えない場合の暫定lag上限（週末＋祝日を吸収する日数）
MAX_LAG_DAYS_WITHOUT_REFERENCE = 4

CURRENT_USABLE = "CURRENT_USABLE"
DELAYED_NOT_CURRENT = "DELAYED_NOT_CURRENT"
NO_DATA = "NO_DATA"

G10_RESOLVED = "RESOLVED"
G10_HISTORICAL_ONLY = "HISTORICAL_RESOLVED_CURRENT_BLOCKED"
G10_PARTIAL = "PARTIALLY_RESOLVED"
G10_BLOCKED = "BLOCKED"


@dataclass(frozen=True, kw_only=True)
class TopixFreshness:
    """TOPIXの鮮度評価（Morning Compass当日入力としての可否）。"""

    verdict: str                       # CURRENT_USABLE / DELAYED_NOT_CURRENT / NO_DATA
    history_rows: int = 0
    latest_trading_date: str = ""
    lag_days: int = -1                 # 実行日 − 最新trading_date（-1=不明）
    reference_series_id: str = ""
    reference_latest_trading_date: str = ""
    gap_sessions: int = -1             # 基準系列で「より新しい」セッション数（-1=不明）
    first_trading_date: str = ""
    reason_codes: Tuple[str, ...] = ()

    @property
    def morning_usable(self) -> bool:
        return self.verdict == CURRENT_USABLE

    @property
    def history_ok(self) -> bool:
        return self.history_rows >= MIN_HISTORY_ROWS

    def as_dict(self) -> Dict[str, object]:
        return {
            "verdict": self.verdict,
            "history_rows": self.history_rows,
            "first_trading_date": self.first_trading_date,
            "latest_trading_date": self.latest_trading_date,
            "lag_days": self.lag_days,
            "reference_series_id": self.reference_series_id,
            "reference_latest_trading_date": self.reference_latest_trading_date,
            "gap_sessions": self.gap_sessions,
            "history_ok_25dma": self.history_ok,
            "morning_usable": self.morning_usable,
            "reason_codes": list(self.reason_codes),
        }


def _trading_dates(index, series_id: str) -> List[str]:
    rows = index.query(series_id=series_id, kind="raw", limit=1000000)
    return sorted({str(r["trading_date"]) for r in rows if r["trading_date"]})


def evaluate_topix_freshness(
    index,
    *,
    now: datetime,
    topix_series_id: str = TOPIX_SERIES_ID,
    reference_series_id: str = REFERENCE_SERIES_ID,
) -> TopixFreshness:
    """SQLite index上のTOPIX観測 → 鮮度評価（読み取りのみ）。"""
    topix_dates = _trading_dates(index, topix_series_id)
    if not topix_dates:
        return TopixFreshness(verdict=NO_DATA, reason_codes=("no_topix_observations",))

    latest = topix_dates[-1]
    lag_days = (now.date() - date.fromisoformat(latest)).days
    reference_dates = _trading_dates(index, reference_series_id)

    if reference_dates:
        newer = [d for d in reference_dates if d > latest]
        gap = len(newer)
        common = dict(
            history_rows=len(topix_dates), latest_trading_date=latest,
            first_trading_date=topix_dates[0], lag_days=lag_days,
            reference_series_id=reference_series_id,
            reference_latest_trading_date=reference_dates[-1], gap_sessions=gap)
        if gap == 0:
            return TopixFreshness(
                verdict=CURRENT_USABLE, **common,
                reason_codes=("matches_reference_tokyo_session",))
        return TopixFreshness(
            verdict=DELAYED_NOT_CURRENT, **common,
            reason_codes=("behind_reference_tokyo_session", f"gap_sessions:{gap}"))

    # 基準系列が無い（＝比較不能）。暫定でlag閾値のみ——根拠が弱いことを明示する
    common = dict(
        history_rows=len(topix_dates), latest_trading_date=latest,
        first_trading_date=topix_dates[0], lag_days=lag_days,
        reference_series_id="", reference_latest_trading_date="", gap_sessions=-1)
    if lag_days <= MAX_LAG_DAYS_WITHOUT_REFERENCE:
        return TopixFreshness(
            verdict=CURRENT_USABLE, **common,
            reason_codes=("reference_series_unavailable", "lag_threshold_basis_only",
                          f"lag_days:{lag_days}"))
    return TopixFreshness(
        verdict=DELAYED_NOT_CURRENT, **common,
        reason_codes=("reference_series_unavailable", f"lag_days:{lag_days}"))


def g10_state(
    freshness: TopixFreshness, *, credential_present: bool
) -> Tuple[str, Tuple[str, ...]]:
    """freshness＋credential有無 → G10状態（reason code必須）。

    RESOLVED は「live取得済み＋25DMA可能な履歴＋当日セッション利用可能」の
    3条件が揃った場合のみ（fetch成功だけでは宣言しない）。
    """
    if freshness.verdict == NO_DATA:
        if not credential_present:
            return G10_PARTIAL, ("topix_credential_missing",
                                 "adapter_implemented_not_live_validated")
        return G10_BLOCKED, ("topix_fetch_failed_with_credential",)
    if not freshness.history_ok:
        return G10_PARTIAL, ("insufficient_history_for_25dma",
                             f"rows:{freshness.history_rows}")
    if freshness.verdict == CURRENT_USABLE:
        return G10_RESOLVED, ("live_authenticated_fetch",
                              "history_ge_25dma",
                              "current_session_available") + freshness.reason_codes
    return G10_HISTORICAL_ONLY, ("history_ge_25dma",
                                 "current_session_not_available") + freshness.reason_codes


def access_requirement_report(freshness: TopixFreshness) -> Dict[str, object]:
    """STEP 5: plan/access判断のための事実報告（コード側で回避しない）。

    観測された遅延と、Morning Compassが必要とする鮮度を並べて提示するだけ。
    plan選択はユーザーの判断事項。
    """
    return {
        "morning_compass_requirement":
            "同日朝（JST 6-9時）時点で、直近に完了した東京セッションのTOPIX終値が"
            "取得できること（基準系列と同一セッション）",
        "observed_verdict": freshness.verdict,
        "observed_lag_days": freshness.lag_days,
        "observed_gap_sessions": freshness.gap_sessions,
        "observed_latest_trading_date": freshness.latest_trading_date,
        "required_access_level": (
            "現行取得内容で要件充足" if freshness.morning_usable else
            "遅延のないTOPIX指数配信を含むJ-Quants有料プラン（Light以上）"
            "——Freeプランは公表上12週遅延"),
        "no_proxy_fallback":
            "1306.T等ETF・TOPIX先物・近似指数への自動fallbackは行わない",
    }
