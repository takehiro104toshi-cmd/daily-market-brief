"""P10-A3 — Attention の authority の検査済みの read-only の像（`attention_authority.jsonl`）。

読み込みのたびに全行を A2 の型で復元し、root ごとの鎖（FOCUS ／ MUTE ／ CLEARED の状態機械 ・CLEARED の終端 ・対象の不変 ・見た
revision の構文 ・seq ・prev ・reviewed_at の非減少 ・人の著者 ・決定論の id）と A2 の `check_personal_world`（全ての審査の瞬間で P9 の
対象ごとに生きている印は高々 1 つ）を検査する。P9 の root ／ revision の実在は検査しない（A4）。追記の API は無い（coordinator だけ）。

記録: `docs/databank/PHASE10_A3_PROFILE_ATTENTION_STORES.md`。
"""
from __future__ import annotations

from typing import Dict, Sequence, Tuple

from .attention_model import AttentionRevision
from .cross_rules import check_personal_world
from .serialization import attention_from_record, attention_line
from .store_io import ATTENTION_FILENAME, AuthorityFile


def _attention_chains(revisions: Sequence[AttentionRevision]) -> Dict[str, Tuple[AttentionRevision, ...]]:
    _, attention = check_personal_world([], list(revisions))
    return attention


class AttentionStore(AuthorityFile):
    FILENAME = ATTENTION_FILENAME
    KIND = "attention"
    _parse = staticmethod(attention_from_record)
    _chains_of = staticmethod(_attention_chains)
    _line = staticmethod(attention_line)


__all__ = ["AttentionStore"]
