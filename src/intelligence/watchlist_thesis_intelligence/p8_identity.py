"""P9-A4 — `MANUAL` の出所の発行体を、凍結 A1 の identity の authority で read-only に確かめる（no-network ・no-credential ・no-write）。

**意味（正直な主張だけ）**: 「この `issuer_id` は、凍結 A1 の identity の authority にある **人が審査した発行体の登録の record**
（`IssuerRegistration` ・出所 `HUMAN_REVIEWED`）に対応し、その record は P9 の `reviewed_at` 以前に知られていた（`known_at <=
reviewed_at`）」。凍結 A1 の coverage は authority の日（D0）だけで、複数日の継続（I1）は延期のまま。したがって本 module は
**`reviewed_at` の時点の上場 ・coverage ・identity の解決を主張しない**（凍結の resolver を後の日に使うと coverage の外になる）。
A1R の訂正の履歴（後の退役 ・統合）も評価しない（record の存在だけ）。

P8 の store は `open(read_only=True)` だけ（`initialize` ／ `append` なし）。identity の意味は凍結 A1 の model が持ち、本 module は
複製しない（登録の record の有無 ・出所の class ・既知の時刻を読むだけ）。

記録: `docs/databank/PHASE9_A4_HUMAN_DECISION_EXECUTOR.md`。
"""
from __future__ import annotations

import os.path
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from ..screener_intelligence.identity_model import SourceClass
from ..screener_intelligence.identity_store import IdentityStore, IdentityStoreError

#: 主張の意味（上場 ・coverage ・時点の identity の解決ではない）
ISSUER_RECORD_SEMANTICS = "HUMAN_REVIEWED_A1_ISSUER_REGISTRATION_RECORD_KNOWN_BY_REVIEWED_AT_NOT_A_LISTING_OR_COVERAGE_CLAIM"


class IssuerRecordError(ValueError):
    def __init__(self, code: str, detail: str = "") -> None:
        super().__init__(f"{code}: {detail}" if detail else code)
        self.code = code
        self.detail = detail


def _require(condition: bool, code: str, detail: str = "") -> None:
    if not condition:
        raise IssuerRecordError(code, detail)


@dataclass(frozen=True, kw_only=True)
class IssuerRecordConfirmation:
    issuer_id: str
    semantics: str = ISSUER_RECORD_SEMANTICS


def confirm_reviewed_issuer_record(p8_root: Any, issuer_id: str, reviewed_at: datetime) -> IssuerRecordConfirmation:
    """凍結 A1 の人が審査した発行体の登録の record が `reviewed_at` 以前に知られていたことを read-only で確かめる。"""
    _require(isinstance(p8_root, (str, Path)) and str(p8_root).strip() != "", "P8_ROOT_REQUIRED", "p8_root")
    root = Path(os.path.normpath(str(p8_root)))
    _require(root.is_absolute(), "P8_ROOT_NOT_ABSOLUTE", "p8_root")
    _require(root.is_dir(), "P8_ROOT_MISSING", "p8_root")                       # 作らない
    _require(isinstance(reviewed_at, datetime) and reviewed_at.tzinfo is not None
             and reviewed_at.tzinfo.utcoffset(reviewed_at) is not None, "INSTANT_NOT_AWARE", "reviewed_at")
    try:
        history = IdentityStore.open(root, read_only=True).history              # 無ければ例外（作らない）
    except IdentityStoreError as exc:
        raise IssuerRecordError("IDENTITY_AUTHORITY_UNAVAILABLE", exc.code) from None
    registration = history.issuers.get(issuer_id)
    _require(registration is not None, "ISSUER_AUTHORITY_UNKNOWN", "issuer_id")
    _require(registration.provenance.source_class is SourceClass.HUMAN_REVIEWED, "ISSUER_NOT_HUMAN_REVIEWED",
             "issuer_id")
    _require(registration.provenance.known_at <= reviewed_at, "ISSUER_NOT_KNOWN_BY_REVIEWED_AT", "issuer_id")
    return IssuerRecordConfirmation(issuer_id=issuer_id)


__all__ = ["ISSUER_RECORD_SEMANTICS", "IssuerRecordConfirmation", "IssuerRecordError",
           "confirm_reviewed_issuer_record"]
