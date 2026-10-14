"""P9-A2 — Watchlist と Thesis の記録をまたぐ不変条件（純 ・自動の書き換えなし）。

時点 T の像（各 root の `reviewed_at <= T` の最大の seq）で:
1. 発行体ごとに REMOVED でない Watchlist の項目は高々 1 つ。
2. 生きている Thesis（ACTIVE ・CHALLENGED）は、T に存在し REMOVED でない Watchlist の項目を指し、発行体が同じ。
   → Watchlist の項目は、生きている Thesis がある間は REMOVED にできない。Thesis は REMOVED でない項目なしに作れない。
3. 全ての Thesis の発行体は、指す Watchlist の項目の発行体と同じ。
4. Watchlist の `thesis_ids` は人が宣言した索引だけ（authority ではない）: 宣言した各 id は T に存在し、その Thesis の
   `watch_entry_id` が自分を指す（link の authority は Thesis 側）。索引が全てを列挙することは要求しない。

`check_world` は全 revision の審査の瞬間ごとに像を検査する（後の revision の追加が過去の時点を壊すことも検出する）。記録を書き換える ・
状態を自動で変える関数は無い。store ・A1 の identity ・P8 の再構成を要る検査は A3 ／ A4（文書 §8）。
"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, Mapping, Sequence, Tuple

from .revision_model import check_instant, require, state_at
from .thesis_model import LIVE_THESIS_STATUSES, ThesisRevision, validate_thesis_chain
from .watch_model import WatchEntryRevision, WatchStatus, validate_watch_chain


def _chains(revisions: Sequence[Any], validate, kind: type) -> Dict[str, Tuple[Any, ...]]:
    require(isinstance(revisions, (list, tuple)), "INVALID_REVISIONS", kind.__name__)
    for revision in revisions:
        require(isinstance(revision, kind), "INVALID_REVISION", kind.__name__)
    roots = sorted({revision.root_id for revision in revisions})
    return {root: validate([r for r in revisions if r.root_id == root]) for root in roots}


def check_snapshot(watch_chains: Mapping[str, Tuple[WatchEntryRevision, ...]],
                   thesis_chains: Mapping[str, Tuple[ThesisRevision, ...]], at: datetime) -> None:
    """時点 T の像の不変条件（1〜4）。違えば fail closed。"""
    instant = check_instant(at, "at")
    watch_heads = {root: head for root, chain in watch_chains.items() if (head := state_at(chain, instant))}
    thesis_heads = {root: head for root, chain in thesis_chains.items() if (head := state_at(chain, instant))}
    live_by_issuer: Dict[str, str] = {}
    for root, head in watch_heads.items():
        if head.status is not WatchStatus.REMOVED:
            require(head.issuer_id not in live_by_issuer, "DUPLICATE_LIVE_WATCH_ENTRY", head.issuer_id)
            live_by_issuer[head.issuer_id] = root
    for root, head in thesis_heads.items():
        watch = watch_heads.get(head.watch_entry_id)
        require(watch is not None, "THESIS_WITHOUT_WATCH_ENTRY", root)
        require(watch.issuer_id == head.issuer_id, "THESIS_ISSUER_MISMATCH", root)
        if head.status in LIVE_THESIS_STATUSES:
            require(watch.status is not WatchStatus.REMOVED, "LIVE_THESIS_ON_REMOVED_WATCH_ENTRY", root)
    for root, head in watch_heads.items():
        for thesis_id in head.thesis_ids:
            thesis = thesis_heads.get(thesis_id)
            require(thesis is not None and thesis.watch_entry_id == root, "DECLARED_THESIS_LINK_INVALID", thesis_id)


def check_world(watch_revisions: Sequence[WatchEntryRevision],
                thesis_revisions: Sequence[ThesisRevision]) -> Tuple[Dict[str, Tuple[WatchEntryRevision, ...]],
                                                                     Dict[str, Tuple[ThesisRevision, ...]]]:
    """全ての鎖を検査し、全 revision の審査の瞬間ごとに像の不変条件を検査する（純 ・file の順に依らない）。"""
    watch_chains = _chains(watch_revisions, validate_watch_chain, WatchEntryRevision)
    thesis_chains = _chains(thesis_revisions, validate_thesis_chain, ThesisRevision)
    instants = sorted({r.reviewed_at for chain in (*watch_chains.values(), *thesis_chains.values()) for r in chain})
    for instant in instants:
        check_snapshot(watch_chains, thesis_chains, instant)
    return watch_chains, thesis_chains


__all__ = ["check_snapshot", "check_world"]
