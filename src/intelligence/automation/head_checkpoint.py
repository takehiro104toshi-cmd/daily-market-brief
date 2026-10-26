"""P12-A3 — ledger の head の独立な checkpoint（`ledger/head.json`。P12-OBS-002 の解消）。

- 内容は record_count ・head_digest ・ledger_version だけ。commit 済みの ledger から導き、原子的に置換する。
- 開く時に ledger と照合する（`classify_checkpoint`）:
  - `CHECKPOINT_OK`      count ＝ record 数 ・digest ＝ head（ledger が空で checkpoint も無い ＝ fresh も OK）
  - `CHECKPOINT_STALE`   count ＜ record 数 ・digest ＝ その位置の record の digest（ledger に正しい新しい尾がある。crash の窓 B）
  - `LEDGER_INVALID:TAIL_TRUNCATED`       count ＞ record 数（尾が切られた ・または checkpoint が先行）
  - `LEDGER_INVALID:CHECKPOINT_MISMATCH`  digest が一致しない
  - `LEDGER_INVALID:CHECKPOINT_MALFORMED` 形が違う
- 過信しない: これは偶然の divergence ・尾の切り捨ての検出であり、両方の file を書き換えられる攻撃者への防御ではない。
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Optional, Sequence

from .canonical import canonical_json, is_digest, require_fields
from .failure_codes import AutomationError
from .ledger_model import GENESIS_DIGEST, LEDGER_RECORD_VERSION, LedgerError, LedgerRecord

CHECKPOINT_SCHEMA_VERSION = "p12_ledger_head:0.1.0"
CHECKPOINT_OK = "CHECKPOINT_OK"
CHECKPOINT_STALE = "CHECKPOINT_STALE"
_CHECKPOINT_FIELDS = frozenset({"schema_version", "ledger_version", "record_count", "head_digest"})


@dataclass(frozen=True)
class HeadCheckpoint:
    record_count: int
    head_digest: str
    ledger_version: str = LEDGER_RECORD_VERSION
    schema_version: str = CHECKPOINT_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.schema_version != CHECKPOINT_SCHEMA_VERSION or self.ledger_version != LEDGER_RECORD_VERSION:
            raise LedgerError("CHECKPOINT_MALFORMED")
        if isinstance(self.record_count, bool) or not isinstance(self.record_count, int) or self.record_count < 0:
            raise LedgerError("CHECKPOINT_MALFORMED")
        if not is_digest(self.head_digest) or (self.record_count == 0) != (self.head_digest == GENESIS_DIGEST):
            raise LedgerError("CHECKPOINT_MALFORMED")

    def to_dict(self) -> Dict[str, Any]:
        return {"schema_version": self.schema_version, "ledger_version": self.ledger_version,
                "record_count": self.record_count, "head_digest": self.head_digest}

    def to_bytes(self) -> bytes:
        return (canonical_json(self.to_dict()) + "\n").encode("utf-8")

    @classmethod
    def from_dict(cls, data: Any) -> "HeadCheckpoint":
        try:
            fields = require_fields(data, _CHECKPOINT_FIELDS, "CHECKPOINT")
        except AutomationError:
            raise LedgerError("CHECKPOINT_MALFORMED") from None
        return cls(record_count=fields["record_count"], head_digest=fields["head_digest"],
                   ledger_version=fields["ledger_version"], schema_version=fields["schema_version"])

    @classmethod
    def of(cls, records: Sequence[LedgerRecord]) -> "HeadCheckpoint":
        return cls(record_count=len(records), head_digest=records[-1].record_digest if records else GENESIS_DIGEST)


def classify_checkpoint(records: Sequence[LedgerRecord], checkpoint: Optional[HeadCheckpoint]) -> str:
    """検証済みの record の列と checkpoint の関係（上の分類）。不正は `LedgerError` ではなく分類の code で返す。"""
    if checkpoint is None:
        return CHECKPOINT_OK if not records else CHECKPOINT_STALE                      # 無い checkpoint: 空なら fresh ・あれば遅れ
    if checkpoint.record_count > len(records):
        return "LEDGER_INVALID:TAIL_TRUNCATED"
    expected = records[checkpoint.record_count - 1].record_digest if checkpoint.record_count else GENESIS_DIGEST
    if checkpoint.head_digest != expected:
        return "LEDGER_INVALID:CHECKPOINT_MISMATCH"
    return CHECKPOINT_OK if checkpoint.record_count == len(records) else CHECKPOINT_STALE


__all__ = ["CHECKPOINT_OK", "CHECKPOINT_SCHEMA_VERSION", "CHECKPOINT_STALE", "HeadCheckpoint", "classify_checkpoint"]
