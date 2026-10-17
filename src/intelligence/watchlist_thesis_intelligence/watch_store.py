"""P9-A3 — Watchlist の authority の検査済みの read-only の像（`watchlist_authority.jsonl`）。

読み込みのたびに全行を A2 の model で復元し、root ごとの鎖（seq ・prev ・不変の欄 ・reviewed_at の非減少 ・終端の後なし ・人の著者）と、
全ての審査の瞬間で「発行体ごとに REMOVED でない項目は高々 1 つ」を検査する。追記は `AuthorityStores` だけ。

記録: `docs/databank/PHASE9_A3_AUTHORITY_STORES.md`。
"""
from __future__ import annotations

from typing import Mapping, Tuple

from .revision_model import state_at
from .serialization import watch_from_dict, watch_line
from .store_io import AuthorityStoreError, RevisionStore, StoreFailureCategory
from .watch_model import WatchEntryRevision, WatchStatus, validate_watch_chain

WATCHLIST_FILENAME = "watchlist_authority.jsonl"


class WatchlistStore(RevisionStore):
    FILENAME = WATCHLIST_FILENAME
    _parse = staticmethod(watch_from_dict)
    _validate_chain = staticmethod(validate_watch_chain)
    _line = staticmethod(watch_line)

    def _check_store_invariants(self, chains: Mapping[str, Tuple[WatchEntryRevision, ...]]) -> None:
        instants = sorted({r.reviewed_at for chain in chains.values() for r in chain})
        for instant in instants:
            live = [head.issuer_id for chain in chains.values() if (head := state_at(chain, instant))
                    and head.status is not WatchStatus.REMOVED]
            if len(live) != len(set(live)):
                raise AuthorityStoreError(StoreFailureCategory.STORE_CORRUPTION, "DUPLICATE_LIVE_WATCH_ENTRY",
                                          instant.isoformat())


__all__ = ["WATCHLIST_FILENAME", "WatchlistStore"]
