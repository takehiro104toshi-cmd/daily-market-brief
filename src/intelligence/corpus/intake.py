"""Mobile Intake adapter boundary（Phase 3.7 §27）。

    incoming file → Compass Intake API / service boundary（本モジュール）→ Corpus

Google Drive / iCloud / Dropbox / iPhone Shortcut 等の adapter は **IntakeRequest を作るだけ**。
Corpus core は cloud SDK に依存しない（Phase 3.7 ではクラウド接続そのものを実装しない）。
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Dict, Mapping, Optional, Sequence, Tuple

from .config import CorpusConfig
from .extraction import TextLayerExtractor
from .status import DUPLICATE, FAILED, QUARANTINED
from .store import CorpusStore

SOURCE_LOCAL_FILE = "LOCAL_FILE"
SOURCE_HISTORICAL_IMPORT = "HISTORICAL_IMPORT"
SOURCE_INBOX = "INBOX"
SOURCE_MOBILE_UPLOAD = "MOBILE_UPLOAD"
SOURCE_TYPES = (SOURCE_LOCAL_FILE, SOURCE_HISTORICAL_IMPORT, SOURCE_INBOX, SOURCE_MOBILE_UPLOAD)

ACCEPTED = "ACCEPTED"
OUTCOME_DUPLICATE = DUPLICATE
OUTCOME_QUARANTINED = QUARANTINED
OUTCOME_FAILED = FAILED
OUTCOME_REJECTED = "REJECTED"   # boundary で拒否（拡張子・source_type 不正）


@dataclass(frozen=True)
class IntakeRequest:
    path: Path
    original_filename: str
    source_type: str
    received_at: datetime
    channel: str = ""                 # adapter 名（"local" / "inbox" / 将来 "drive" 等）。値は記録のみ

    def as_dict(self) -> Dict[str, object]:
        return {"original_filename": self.original_filename, "source_type": self.source_type,
                "received_at": self.received_at.isoformat(), "channel": self.channel}


@dataclass(frozen=True)
class IntakeOutcome:
    status: str
    document_id: str
    reasons: Tuple[str, ...]
    quality: str = ""
    duplicate_of: str = ""
    corpus_status: str = ""
    recovered: bool = False

    def as_dict(self) -> Dict[str, object]:
        return {"status": self.status, "document_id": self.document_id,
                "reasons": list(self.reasons), "quality": self.quality,
                "duplicate_of": self.duplicate_of, "corpus_status": self.corpus_status,
                "recovered": self.recovered}


class CompassIntakeService:
    """Corpus への唯一の投入口。adapter はこれを呼ぶ。"""

    def __init__(self, store: CorpusStore, config: CorpusConfig, extractor: TextLayerExtractor, *,
                 trading_days: Optional[Sequence[str]] = None,
                 market_lookup: Optional[Callable] = None,
                 context_labels: Optional[Callable[[str], Mapping[str, str]]] = None,
                 recover_environment_failures: bool = False) -> None:
        self.store = store
        self.config = config
        self.extractor = extractor
        self.trading_days = trading_days
        self.market_lookup = market_lookup
        self.context_labels = context_labels
        self.recover_environment_failures = recover_environment_failures   # environment 由来 FAILED の再検証を許すか

    def submit(self, request: IntakeRequest) -> IntakeOutcome:
        from .pipeline import ingest_path

        if request.source_type not in SOURCE_TYPES:
            return IntakeOutcome(OUTCOME_REJECTED, "", ("UNKNOWN_SOURCE_TYPE",))
        if Path(request.original_filename).suffix.lower() != ".pdf":
            return IntakeOutcome(OUTCOME_REJECTED, "", ("NOT_PDF_FILENAME",))
        received = request.received_at
        if received.tzinfo is None:
            received = received.replace(tzinfo=timezone.utc)
        result = ingest_path(self.store, request.path, config=self.config, extractor=self.extractor,
                             now=received, source_type=request.source_type,
                             original_filename=request.original_filename,
                             trading_days=self.trading_days, market_lookup=self.market_lookup,
                             context_labels=self.context_labels,
                             recover_environment_failures=self.recover_environment_failures)   # ExtractorUnavailable は伝播
        if result.status == DUPLICATE:
            return IntakeOutcome(OUTCOME_DUPLICATE, result.document_id, result.reasons,
                                 duplicate_of=result.duplicate_of, corpus_status=result.status)
        if result.status == QUARANTINED:
            return IntakeOutcome(OUTCOME_QUARANTINED, result.document_id, result.reasons,
                                 corpus_status=result.status)
        if result.status == FAILED:
            return IntakeOutcome(OUTCOME_FAILED, result.document_id, result.reasons,
                                 corpus_status=result.status)
        return IntakeOutcome(ACCEPTED, result.document_id, result.reasons, quality=result.quality,
                             corpus_status=result.status, recovered=result.recovered)
