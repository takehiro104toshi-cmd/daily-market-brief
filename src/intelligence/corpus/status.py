"""Document status と遷移（Phase 3.7 §5）。silent failure 禁止＝必ず status event を残す。"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import datetime
from typing import Dict, FrozenSet, Optional

RECEIVED = "RECEIVED"                  # bytes を受領・identity 確定
VALIDATED = "VALIDATED"                # PDF / family / date 検証通過
DUPLICATE = "DUPLICATE"                # 同一 hash 再投入（documents には追加しない。ledger のみ）
EXTRACTION_READY = "EXTRACTION_READY"  # 原本を immutable store へ登録済み
EXTRACTED = "EXTRACTED"                # text layer artifact 作成済み
ANALYZED = "ANALYZED"                  # structured record / quality / coverage 作成済み（quality VALID）
PARTIAL = "PARTIAL"                    # 解析はできたが quality が PARTIAL / LIMITED_USE
QUARANTINED = "QUARANTINED"            # family confidence 不足・日付不明など（fail-closed）
FAILED = "FAILED"                      # PDF として読めない等

ALL_STATUSES = (RECEIVED, VALIDATED, DUPLICATE, EXTRACTION_READY, EXTRACTED,
                ANALYZED, PARTIAL, QUARANTINED, FAILED)

#: 許可される遷移（from → to）。DUPLICATE は document の状態ではなく投入イベント。
TRANSITIONS: Dict[str, FrozenSet[str]] = {
    "": frozenset({RECEIVED}),
    RECEIVED: frozenset({VALIDATED, QUARANTINED, FAILED}),
    VALIDATED: frozenset({EXTRACTION_READY, FAILED}),
    EXTRACTION_READY: frozenset({EXTRACTED, FAILED, QUARANTINED}),
    EXTRACTED: frozenset({ANALYZED, PARTIAL, FAILED}),
    ANALYZED: frozenset({ANALYZED, PARTIAL}),      # 再解析（新 version）
    PARTIAL: frozenset({ANALYZED, PARTIAL}),
    QUARANTINED: frozenset({VALIDATED}),           # marker version 更新後の再検証のみ
    FAILED: frozenset(),
}

TERMINAL_FOR_ANALYSIS = frozenset({ANALYZED, PARTIAL})


def can_transition(current: str, target: str) -> bool:
    return target in TRANSITIONS.get(current or "", frozenset())


@dataclass(frozen=True)
class StatusEvent:
    event_id: str
    document_id: str
    status: str
    reason: str
    at: datetime
    version: str = ""          # extractor / analysis version（該当する場合）

    def as_dict(self) -> Dict[str, str]:
        return {"event_id": self.event_id, "document_id": self.document_id,
                "status": self.status, "reason": self.reason,
                "at": self.at.isoformat(), "version": self.version}


def status_event(document_id: str, status: str, reason: str, at: datetime,
                 version: str = "", sequence: Optional[int] = None) -> StatusEvent:
    """event_id は (document_id, status, version, sequence) から決定的に作る。

    `sequence` は同一 document の event 通番。同じ status を再度記録する場合（再解析）は
    通番が進むので id が衝突しない。"""
    seed = f"{document_id}|{status}|{version}|{sequence if sequence is not None else 0}"
    event_id = "cse_" + hashlib.sha1(seed.encode("utf-8")).hexdigest()[:16]
    return StatusEvent(event_id=event_id, document_id=document_id, status=status,
                       reason=reason, at=at, version=version)
