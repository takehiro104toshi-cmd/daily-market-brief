"""Market historical backfill（Phase 2-D PART G/H）。

- CORE系列の日足履歴を1系列=1リクエストで取得し、raw保存→正規化→QA→bankへ流す
  （BACKFILL IS A DATA MIGRATION NOT A FILE COPY——P2-C原則の市場データ版）。
- **run manifest**（MarketBackfillRun・append-only）: run_id / provider / 系列別結果 /
  期間 / 件数 / 版数（catalog / ingest / policy）を監査可能に記録する。
- probe系列（legacy実績なしsymbol）の取得失敗はSOURCE GAPであってエラーではない。
- QAはEvidence QA（P1-E assess_observation）を**そのまま**使う。履歴取込のため
  HISTORICAL policy（古さでLIMITしない・他Gateは全て維持）。reference_timeは
  取得時刻（now()は使わない——決定論）。
- サニティはingestの検知結果とQA次元のみ。**知識で値を補正しない**。
- 冪等: observation_idが決定論のため、再実行は既存分をskipし新規のみ追加する
  （QA assessmentは新規observationにのみ発行——再評価は明示操作として別途）。
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from typing import Dict, List, Optional, Tuple

from ..core.ids import new_id
from ..core.types import SCHEMA_VERSION, SourceTier
from ..evidence_qa.assess import assess_observation
from ..evidence_qa.model import EvidenceAssessment, SourceInfo
from ..evidence_qa.policy import TrustPolicy
from .derived import derive_cross_series, derive_per_series
from .ingest import INGEST_VERSION, build_observations
from .model import Observation, latest_revisions
from .providers import MarketDataProvider
from .series_catalog import SeriesCatalog, SeriesSpec
from .store import MarketBankStore


@dataclass(frozen=True, kw_only=True)
class SeriesRunResult:
    """run manifest内の1系列分の結果。"""

    series_id: str
    symbol: str = ""
    status: str = ""  # success / gap / failed
    http_status: int = 0
    error_kind: str = ""
    records_seen: int = 0
    observations_added: int = 0
    revisions: int = 0
    source_changes: int = 0
    issue_count: int = 0
    issue_sample: Tuple[str, ...] = ()  # 先頭数件（全量はrun外の品質レポート）
    qa_decisions: Tuple[str, ...] = ()  # "decision:count"（serialization roundtrip安全な同種tuple）
    fetch_attempt_id: str = ""
    raw_item_id: str = ""
    probe: bool = False


@dataclass(frozen=True, kw_only=True)
class MarketBackfillRun:
    """取得run manifest（append-only監査履歴。backfill_runs.jsonl）。"""

    run_id: str  # mbf_<ULID>
    started_at: datetime
    completed_at: Optional[datetime] = None
    provider_id: str = ""
    catalog_version: str = ""
    ingest_version: str = ""
    trust_policy: str = ""  # 例 "HISTORICAL:1.0.0"
    range_start: str = ""   # 要求期間（YYYY-MM-DD）
    range_end: str = ""
    series_requested: int = 0
    series_success: int = 0
    series_gap: int = 0
    series_failed: int = 0
    observations_added: int = 0
    derived_added: int = 0
    results: Tuple[SeriesRunResult, ...] = ()
    status: str = "running"  # running / completed
    schema_version: str = SCHEMA_VERSION


def provider_source_info(catalog: SeriesCatalog, provider_id: str) -> SourceInfo:
    """カタログのprovider定義 → QA用SourceInfo（MARKET_DATA_PROVIDER種別）。"""
    info = catalog.providers[provider_id]
    return SourceInfo(
        source_id=provider_id,
        tier=SourceTier(info.tier),
        investment_value="HIGH",
        health_state="unverified",  # 死活registry未整備の正直な申告（P1-B統合は将来）
        usage_status="public_feed",
    )


class MarketBackfillEngine:
    """CORE系列backfillの実行本体（providerはProtocol注入——実装非依存）。"""

    def __init__(
        self,
        store: MarketBankStore,
        catalog: SeriesCatalog,
        provider: MarketDataProvider,
        policy: TrustPolicy,
        sleeper=None,  # Callable[[float], None]（系列間の礼儀sleep。テストはno-op注入）
    ) -> None:
        self.store = store
        self.catalog = catalog
        self.provider = provider
        self.policy = policy
        self.sleeper = sleeper
        self._source_info = provider_source_info(catalog, provider.provider_id)

    # ------------------------------------------------------------- 1系列

    def run_series(self, spec: SeriesSpec, *, start: date, end: date) -> SeriesRunResult:
        result = self.provider.fetch_daily_history(spec, start=start, end=end)
        attempt_id, raw_item_id = self.store.record_provider_fetch(
            result, new_id("fetch", result.retrieved_at))

        if not result.ok:
            status = "gap" if spec.probe or result.error_kind in ("no_data", "no_symbol") \
                else "failed"
            return SeriesRunResult(
                series_id=spec.series_id, symbol=result.symbol, status=status,
                http_status=result.status_code, error_kind=result.error_kind,
                fetch_attempt_id=attempt_id, raw_item_id=raw_item_id or "",
                probe=spec.probe,
            )

        outcome = build_observations(
            spec, result,
            existing_by_date=self.store.current_by_date(spec.series_id),
            source_document_id="",
        )
        new_obs = [o for o in outcome.observations
                   if self.store.normalized.get_observation(o.observation_id) is None]
        added = self.store.add_observations(new_obs)

        decisions: Dict[str, int] = {}
        for obs in new_obs:
            assessment = assess_observation(
                obs, source_info=self._source_info, policy=self.policy,
                reference_time=result.retrieved_at)
            self.store.add_assessment(assessment)
            decisions[assessment.decision.value] = decisions.get(assessment.decision.value, 0) + 1

        return SeriesRunResult(
            series_id=spec.series_id, symbol=result.symbol, status="success",
            http_status=result.status_code, records_seen=outcome.records_seen,
            observations_added=added, revisions=len(outcome.new_revisions),
            source_changes=len(outcome.source_changes),
            issue_count=len(outcome.issues), issue_sample=outcome.issues[:5],
            qa_decisions=tuple(f"{k}:{v}" for k, v in sorted(decisions.items())),
            fetch_attempt_id=attempt_id, raw_item_id=raw_item_id or "",
            probe=spec.probe,
        )

    # ------------------------------------------------------------- 派生（PART F）

    def run_derivations(self) -> int:
        """全enabled系列＋cross系列の派生を計算しbankへ追加（冪等）。戻り値=新規追加数。"""
        added = 0
        latest_assessment = self._latest_assessment_map()

        def qa_and_add(derived: Tuple[Observation, ...]) -> int:
            count = 0
            for obs in derived:
                if self.store.normalized.get_observation(obs.observation_id) is not None:
                    continue
                count += self.store.add_observations([obs])
                inputs = [latest_assessment[i] for i in obs.inputs if i in latest_assessment]
                assessment = assess_observation(
                    obs, source_info=self._source_info, policy=self.policy,
                    reference_time=obs.as_of, input_assessments=inputs)
                self.store.add_assessment(assessment)
                latest_assessment[obs.observation_id] = assessment
            return count

        raw_current: Dict[str, Tuple[Observation, ...]] = {}
        for spec in self.catalog.enabled_series():
            observations = latest_revisions(tuple(
                o for o in self.store.observations_for_series(spec.series_id)
                if o.kind.value == "raw"))
            if not observations:
                continue
            raw_current[spec.series_id] = observations
            added += qa_and_add(derive_per_series(
                spec, self.catalog.per_series_derivations, observations))

        for cross in self.catalog.cross_series_derivations:
            left = raw_current.get(cross.inputs[0])
            right = raw_current.get(cross.inputs[1])
            if not left or not right:
                continue  # 入力系列に実データが無ければ出力しない（捏造しない）
            added += qa_and_add(derive_cross_series(cross, left, right))
        return added

    def _latest_assessment_map(self) -> Dict[str, EvidenceAssessment]:
        """record_id → 最新assessment（1パス導出。O(n²)のlatest_for連打をしない）。"""
        latest: Dict[str, EvidenceAssessment] = {}
        for a in self.store.qa.iter_assessments():
            latest[a.record_id] = a  # append順=時系列（同時刻は後勝ち=追記順）
        return latest

    # ------------------------------------------------------------- 全系列run

    def run(
        self,
        *,
        start: date,
        end: date,
        now: Optional[datetime] = None,
        series_ids: Optional[Tuple[str, ...]] = None,
        with_derivations: bool = True,
    ) -> MarketBackfillRun:
        started = now or datetime.now(timezone.utc)
        specs = [s for s in self.catalog.enabled_series()
                 if series_ids is None or s.series_id in series_ids]
        results: List[SeriesRunResult] = []
        for i, spec in enumerate(specs):
            if i and self.sleeper is not None:
                self.sleeper(1.0)  # 系列間1秒（無料providerへの礼儀。bulk同時要求しない）
            results.append(self.run_series(spec, start=start, end=end))
        derived_added = self.run_derivations() if with_derivations else 0

        run = MarketBackfillRun(
            run_id=new_id("mbf", started),
            started_at=started,
            completed_at=datetime.now(timezone.utc),
            provider_id=self.provider.provider_id,
            catalog_version=self.catalog.catalog_version,
            ingest_version=INGEST_VERSION,
            trust_policy=f"{self.policy.name}:{self.policy.version}",
            range_start=start.isoformat(),
            range_end=end.isoformat(),
            series_requested=len(specs),
            series_success=sum(1 for r in results if r.status == "success"),
            series_gap=sum(1 for r in results if r.status == "gap"),
            series_failed=sum(1 for r in results if r.status == "failed"),
            observations_added=sum(r.observations_added for r in results),
            derived_added=derived_added,
            results=tuple(results),
            status="completed",
        )
        self.store.add_run(run)
        return run


def default_range(*, days: int = 400, today: Optional[date] = None) -> Tuple[date, date]:
    """既定取得期間: 約400暦日 ≒ 1年強の営業日（過剰収集しない・6ヶ月以上を保証）。"""
    end = today or datetime.now(timezone.utc).date()
    return end - timedelta(days=days), end
