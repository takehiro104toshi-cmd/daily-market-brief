"""処理結果（Phase 3.75 §12 / §18）。machine-readable、本文を含まない、ユーザーが次に何をすべきか分かる。"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, Mapping, Optional, Sequence

SUCCESS = "SUCCESS"
DUPLICATE = "DUPLICATE"
WAITING_UNSTABLE = "WAITING_UNSTABLE"
QUARANTINED = "QUARANTINED"
FAILED = "FAILED"
RESULTS = (SUCCESS, DUPLICATE, WAITING_UNSTABLE, QUARANTINED, FAILED)

# reason codes
R_OK = "OK"
R_ALREADY_REGISTERED = "ALREADY_REGISTERED"
R_NOT_PDF = "NOT_PDF"
R_NOT_COMPASS = "NOT_COMPASS"
R_UNSTABLE_TRANSFER = "UNSTABLE_TRANSFER"
R_SYNC_PLACEHOLDER = "SYNC_PLACEHOLDER"
R_UNREADABLE_PDF = "UNREADABLE_PDF"
R_DATE_UNKNOWN = "DATE_UNKNOWN"
R_SYNC_NOT_AVAILABLE = "SYNC_NOT_AVAILABLE"
R_LOCKED = "LOCKED"
R_TIMEOUT_UNSTABLE = "TIMEOUT_UNSTABLE"
R_INTERNAL_ERROR = "INTERNAL_ERROR"

HINTS_JA: Dict[str, str] = {
    R_OK: "羅針盤を Corpus に追加しました。",
    R_ALREADY_REGISTERED: "この羅針盤は既に登録済みです（重複送信は問題ありません）。",
    R_NOT_PDF: "PDF ではありません。羅針盤の PDF を共有してください。",
    R_NOT_COMPASS: "羅針盤（グローバル投資の羅針盤）として認識できませんでした。別の資料か、1ページ目が欠けている可能性があります。",
    R_UNSTABLE_TRANSFER: "転送中です。同期が終わると自動で処理されます。",
    R_SYNC_PLACEHOLDER: "iCloud / OneDrive にまだ本体がありません。PC の同期が終わるまでお待ちください。",
    R_UNREADABLE_PDF: "PDF を読めませんでした。iPhone でもう一度開いて共有し直してください。",
    R_DATE_UNKNOWN: "発行日を紙面から読み取れませんでした。1ページ目が正しい PDF か確認してください。",
    R_SYNC_NOT_AVAILABLE: "Inbox フォルダに到達できません。iCloud for Windows などの同期を確認してください。",
    R_LOCKED: "別の処理が進行中です。次回の実行で処理されます。",
    R_TIMEOUT_UNSTABLE: "転送が完了しませんでした。iPhone からもう一度共有してください。",
    R_INTERNAL_ERROR: "内部エラーです。ログ（ledger）を確認してください。",
}


def reason_from_corpus(status: str, reasons: Sequence[str]) -> str:
    """Corpus の validation reason → ユーザー向け reason code。"""
    joined = ",".join(reasons)
    if status == DUPLICATE:
        return R_ALREADY_REGISTERED
    if "NOT_PDF_BYTES" in joined:
        return R_NOT_PDF
    if "PDF_UNREADABLE" in joined or "NO_PAGES" in joined:
        return R_UNREADABLE_PDF
    if "FAMILY_CONFIDENCE" in joined or "PAGE_COUNT_OUT_OF_RANGE" in joined:
        return R_NOT_COMPASS
    if "DOCUMENT_DATE_MISSING" in joined:
        return R_DATE_UNKNOWN
    if status in (SUCCESS, "ANALYZED", "PARTIAL", "ACCEPTED"):
        return R_OK
    return R_INTERNAL_ERROR


@dataclass(frozen=True)
class ProcessingResult:
    result: str
    file: str                        # basename のみ（full path は出さない）
    sha256: str
    document_id: str
    document_date: str
    received_at: str
    reason_code: str
    hint: str
    processing_duration_seconds: float
    corpus_count_before: int
    corpus_count_after: int
    milestone: Mapping[str, object] = field(default_factory=dict)
    quality: str = ""
    research: Mapping[str, object] = field(default_factory=dict)   # Phase 3.8 hook の結果（任意）

    def as_dict(self) -> Dict[str, object]:
        return {"result": self.result, "file": self.file, "sha256": self.sha256,
                "document_id": self.document_id, "document_date": self.document_date,
                "received_at": self.received_at, "reason_code": self.reason_code,
                "hint": self.hint,
                "processing_duration_seconds": round(self.processing_duration_seconds, 3),
                "corpus_count_before": self.corpus_count_before,
                "corpus_count_after": self.corpus_count_after,
                "milestone": dict(self.milestone), "quality": self.quality,
                "research": dict(self.research)}
