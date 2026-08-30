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

#: plan能力（遅延・履歴範囲）の確証状態——公式documentation evidenceまたは
#: 実credentialでの取得結果が得られるまでUNVERIFIEDを維持する（推測で断定しない）
PLAN_CAPABILITY_UNVERIFIED = "UNVERIFIED"
PLAN_CAPABILITY_VERIFIED = "VERIFIED"

#: 公式documentation evidence（J-Quants公式クイックスタートV2の実コード・実文言）。
#: **entitlement次元のみ**が確定した根拠であり、プラン別の遅延・履歴範囲までは
#: 断定しない（監督者訂正の趣旨を維持する）。
PLAN_CAPABILITY_EVIDENCE_TOPIX_TIER = (
    "公式クイックスタート(V2): TOPIX四本値(/indices/bars/daily/topix)は"
    "「Lightプラン以上のプランで利用できるAPI」に分類。"
    "データ更新時刻は毎営業日16:30頃（JST）"
)
#: TOPIX四本値の公表時刻（JST・公式クイックスタートV2記載）
TOPIX_UPDATE_TIME_LOCAL = "16:30"

#: V1 EOL（2026-06-01）起点の原因分類（jquants_v2.classify_v2_failure と対応）
CAUSE_LEGACY_V1_ENDPOINT = "legacy_v1_endpoint"
CAUSE_API_VERSION_MISMATCH = "api_version_mismatch"
CAUSE_PLAN_NOT_ENTITLED = "plan_not_entitled"

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


#: credential有りでデータ0件のとき、fetch失敗理由をG10のreason codeへ写像する
#: （監督者指定の結果状態 C: ACCESS_LEVEL_INSUFFICIENT / D: AUTH_FAILURE）
_AUTH_FAILURE_KINDS = ("auth_error",)
_DATASET_UNAVAILABLE_KINDS = ("no_data", "http_error", "identity_mismatch",
                              "schema_error", "no_symbol")


def g10_state(
    freshness: TopixFreshness, *, credential_present: bool,
    fetch_error_kind: str = "", failure_cause: str = "",
) -> Tuple[str, Tuple[str, ...]]:
    """freshness＋credential有無＋fetch結果 → G10状態（reason code必須）。

    監督者指定の結果状態:
      A. auth＋history＋current freshness PASS → RESOLVED
      B. auth＋history PASSだがcurrent freshness FAIL
         → HISTORICAL_RESOLVED_CURRENT_BLOCKED
      C. auth PASSだが期待するTOPIX datasetを取得できない
         → BLOCKED / access_level_insufficient
      D. auth FAIL → BLOCKED / auth_failure

    RESOLVED は「live取得済み＋25DMA可能な履歴＋当日セッション利用可能」の
    3条件が揃った場合のみ（fetch成功だけでは宣言しない）。
    """
    if freshness.verdict == NO_DATA:
        if not credential_present:
            return G10_PARTIAL, ("topix_credential_missing",
                                 "adapter_implemented_not_live_validated")
        if failure_cause in (CAUSE_API_VERSION_MISMATCH, CAUSE_LEGACY_V1_ENDPOINT):
            # 認証情報の問題ではなくAPI版数の問題（V1は2026-06-01終了）
            return G10_BLOCKED, (failure_cause, f"error:{fetch_error_kind}")
        if failure_cause == CAUSE_PLAN_NOT_ENTITLED:
            return G10_BLOCKED, ("access_level_insufficient", failure_cause,
                                 f"error:{fetch_error_kind}")
        if fetch_error_kind in _AUTH_FAILURE_KINDS:
            return G10_BLOCKED, (("auth_failure", f"error:{fetch_error_kind}")
                                 + ((f"cause:{failure_cause}",) if failure_cause
                                    else ()))
        if fetch_error_kind in _DATASET_UNAVAILABLE_KINDS:
            return G10_BLOCKED, ("access_level_insufficient",
                                 "authenticated_but_dataset_unavailable",
                                 f"error:{fetch_error_kind}")
        return G10_BLOCKED, (("topix_fetch_failed_with_credential",)
                             + ((f"error:{fetch_error_kind}",)
                                if fetch_error_kind else ()))
    if not freshness.history_ok:
        return G10_PARTIAL, ("insufficient_history_for_25dma",
                             f"rows:{freshness.history_rows}")
    if freshness.verdict == CURRENT_USABLE:
        return G10_RESOLVED, ("live_authenticated_fetch",
                              "history_ge_25dma",
                              "current_session_available") + freshness.reason_codes
    return G10_HISTORICAL_ONLY, ("history_ge_25dma",
                                 "current_session_not_available") + freshness.reason_codes


def access_requirement_report(
    freshness: TopixFreshness, *, plan_capability_evidence: str = ""
) -> Dict[str, object]:
    """STEP 5: plan/access判断のための事実報告（コード側で回避しない）。

    **PLAN_CAPABILITY = UNVERIFIED**（監督者訂正・P2-G.1レビュー）:
    「Free=12週遅延 / Light以上=当日利用可」等のplan能力は公式ドキュメントから
    機械取得できていない。system ground truthとして固定せず、
    実credentialでの取得結果、または取得可能な公式documentation evidenceで
    確定する。ここでは**観測事実**のみを提示し、plan選択はユーザーの判断事項。
    """
    return {
        "morning_compass_requirement":
            "同日朝（JST 6-9時）時点で、直近に完了した東京セッションのTOPIX終値が"
            "取得できること（基準系列と同一セッション）",
        "observed_verdict": freshness.verdict,
        "observed_lag_days": freshness.lag_days,
        "observed_gap_sessions": freshness.gap_sessions,
        "observed_latest_trading_date": freshness.latest_trading_date,
        "plan_capability": (PLAN_CAPABILITY_VERIFIED if plan_capability_evidence
                            else PLAN_CAPABILITY_UNVERIFIED),
        "plan_capability_scope": (
            "entitlement次元のみ（どのプランで当該APIを使えるか）。"
            "プラン別の遅延日数・履歴範囲は依然UNVERIFIED——実取得結果で確定する"),
        "plan_capability_evidence": (
            plan_capability_evidence
            or "未取得（公式docsはJS描画で本文を機械抽出できず・"
               "実credentialでの取得結果も未取得）"),
        "topix_update_time_local": TOPIX_UPDATE_TIME_LOCAL,
        "required_access_level": (
            "現行取得内容で要件充足（実測ベース）" if freshness.morning_usable else
            "未確定——現行アクセスでは当日分が観測できていない。"
            "必要なaccess tierは実credentialでの取得結果または公式documentation"
            "evidenceで確定する（プラン名を推測で断定しない）"),
        "no_proxy_fallback":
            "1306.T等ETF・TOPIX先物・近似指数への自動fallbackは行わない",
    }
