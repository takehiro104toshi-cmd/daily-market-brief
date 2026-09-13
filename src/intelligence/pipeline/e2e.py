"""E2Eパイプライン実行（Phase 2-A）。1ソース＝1リクエスト。bulk禁止。

各層は実装をそのまま使う（mockなし）。注入点はHttpTransportのみ
（オフラインテストはスタブtransport、実行はUrllibTransport）。
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Mapping, Optional, Tuple

from ..core.types import SourceTier
from ..evidence_qa.assess import assess_source_document, load_source_info
from ..evidence_qa.model import EvidenceAssessment, GateDecision
from ..evidence_qa.policy import TrustPolicy
from ..evidence_qa.store import JsonlAssessmentStore
from ..ingestion.fetcher import Fetcher, FetchOutcome
from ..ingestion.raw_store import JsonlRawRepository
from ..ingestion.transport import HttpTransport
from ..normalization.feed_normalizer import SourceMeta, normalize_feed_raw_item
from ..normalization.model import NormalizationResult, NormalizationStatus
from ..normalization.store import JsonlNormalizedStore
from ..sources.model import SourceEndpoint


@dataclass(frozen=True, kw_only=True)
class PipelineSourceResult:
    """1ソース分のE2E結果（全段の生成物ID・判定を保持）。"""

    source_id: str
    fetch_outcome: FetchOutcome
    normalization: Optional[NormalizationResult] = None
    assessments: Tuple[EvidenceAssessment, ...] = ()

    @property
    def stage_reached(self) -> str:
        if self.assessments:
            return "evidence_qa"
        if self.normalization is not None and self.normalization.documents:
            return "normalized"
        if self.normalization is not None:
            return "normalization_rejected"
        if self.fetch_outcome.raw_item is not None:
            return "raw_stored"
        return "fetch_only"

    @property
    def decisions(self) -> Mapping[str, int]:
        counts: dict = {}
        for a in self.assessments:
            counts[a.decision.value] = counts.get(a.decision.value, 0) + 1
        return counts


class Pipeline:
    """Registry→…→GateDecisionの編成。ストア群は実物（JSONL）を使う。"""

    def __init__(
        self,
        workdir: Path,
        transport: HttpTransport,
        policy: TrustPolicy,
        *,
        clock=lambda: datetime.now(timezone.utc),
        sleeper=None,  # retry待機の注入（テスト高速化用。Noneで実sleep）
    ) -> None:
        self.raw = JsonlRawRepository(Path(workdir) / "raw")
        self.normalized = JsonlNormalizedStore(Path(workdir) / "normalized")
        self.qa = JsonlAssessmentStore(Path(workdir) / "evidence_qa")
        fetcher_kwargs = {"clock": clock}
        if sleeper is not None:
            fetcher_kwargs["sleeper"] = sleeper
        self._fetcher = Fetcher(transport, self.raw, **fetcher_kwargs)
        self._policy = policy
        self._clock = clock

    def run_source(self, catalog_feed: Mapping[str, object]) -> PipelineSourceResult:
        """カタログエントリ1件を全層通す。失敗はstructuredに残る（例外を投げない）。"""
        source_id = str(catalog_feed["id"])
        endpoint = SourceEndpoint(
            source_id=source_id, url=str(catalog_feed["endpoint"]["url"]))

        # Fetch → Raw（失敗してもFetchAttemptは必ず記録される）
        outcome = self._fetcher.fetch(endpoint)
        if outcome.raw_item is None or outcome.response is None or not outcome.response.body:
            return PipelineSourceResult(source_id=source_id, fetch_outcome=outcome)

        # Normalize（REJECTEDでもNormalizationEventは残る）
        meta = SourceMeta(
            source_id=source_id,
            tier=SourceTier(int(catalog_feed.get("tier", 3))),
            publisher=str(catalog_feed.get("name", "")),
            default_language=str(catalog_feed.get("lang", "")),
        )
        norm = normalize_feed_raw_item(
            outcome.raw_item, outcome.response.body, meta,
            existing_documents=tuple(self.normalized.iter_documents()),
            now=self._clock(),
        )
        self.normalized.add_documents(norm.documents)
        if norm.event is not None:
            self.normalized.add_event(norm.event)
        if norm.status is NormalizationStatus.REJECTED or not norm.documents:
            # NO FALSE EVIDENCE: 文書ゼロならEvidenceAssessmentは一切作らない
            return PipelineSourceResult(
                source_id=source_id, fetch_outcome=outcome, normalization=norm)

        # Evidence QA → Gate
        info = load_source_info(catalog_feed)
        events = tuple(self.normalized.iter_events())
        existing = tuple(self.normalized.iter_documents())
        assessments = []
        for doc in norm.documents:
            assessment = assess_source_document(
                doc,
                source_info=info,
                policy=self._policy,
                reference_time=self._clock(),
                raw_repository=self.raw,
                normalization_events=events,
                existing_documents=existing,
            )
            self.qa.add_assessment(assessment)
            assessments.append(assessment)
        return PipelineSourceResult(
            source_id=source_id, fetch_outcome=outcome, normalization=norm,
            assessments=tuple(assessments),
        )


def accepted_assessments(result: PipelineSourceResult) -> Tuple[EvidenceAssessment, ...]:
    return tuple(a for a in result.assessments if a.decision is GateDecision.ACCEPT)
