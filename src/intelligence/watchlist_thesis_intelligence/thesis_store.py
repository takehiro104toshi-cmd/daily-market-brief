"""P9-A3 — Thesis の authority の検査済みの read-only の像（`thesis_authority.jsonl`）。

読み込みのたびに全行を A2 の model で復元し、root ごとの鎖（seq ・prev ・不変の発行体 ／ Watchlist の項目 ・reviewed_at の非減少 ・
終端の後なし ・無効の条件の参照 ・人の著者）を検査する。Watchlist との不変条件は `AuthorityStores`。追記は `AuthorityStores` だけ。

記録: `docs/databank/PHASE9_A3_AUTHORITY_STORES.md`。
"""
from __future__ import annotations

from .serialization import thesis_from_dict, thesis_line
from .store_io import RevisionStore
from .thesis_model import validate_thesis_chain

THESIS_FILENAME = "thesis_authority.jsonl"


class ThesisStore(RevisionStore):
    FILENAME = THESIS_FILENAME
    _parse = staticmethod(thesis_from_dict)
    _validate_chain = staticmethod(validate_thesis_chain)
    _line = staticmethod(thesis_line)


__all__ = ["THESIS_FILENAME", "ThesisStore"]
