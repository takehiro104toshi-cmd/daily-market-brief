"""P10-A3 — Personal Profile の authority の検査済みの read-only の像（`profile_authority.jsonl`）。

読み込みのたびに全行を A2 の型で復元し、root ごとの鎖（seq ・prev ・reviewed_at の非減少 ・状態機械 ・終端 ・人の著者 ・決定論の id）と
A2 の `check_personal_world`（全ての審査の瞬間で ACTIVE な profile は高々 1 つ）を検査する。追記の API は無い（coordinator だけ）。

記録: `docs/databank/PHASE10_A3_PROFILE_ATTENTION_STORES.md`。
"""
from __future__ import annotations

from typing import Dict, Sequence, Tuple

from .cross_rules import check_personal_world
from .profile_model import PersonalProfileRevision
from .serialization import profile_from_record, profile_line
from .store_io import PROFILE_FILENAME, AuthorityFile


def _profile_chains(revisions: Sequence[PersonalProfileRevision]) -> Dict[str, Tuple[PersonalProfileRevision, ...]]:
    profiles, _ = check_personal_world(list(revisions), [])
    return profiles


class ProfileStore(AuthorityFile):
    FILENAME = PROFILE_FILENAME
    KIND = "profile"
    _parse = staticmethod(profile_from_record)
    _chains_of = staticmethod(_profile_chains)
    _line = staticmethod(profile_line)


__all__ = ["ProfileStore"]
