"""P10-A1 — 凍結の Phase 9 の authority を read-only で読む専用の adapter（Phase 10 の唯一の Phase 9 の importer）。

P9-OBS-019: P9 の `AuthorityStores` は追記の API を持つので下流の interface にしない。本 module は:
- P9 の read-only の store の型（`WatchlistStore` ・`ThesisStore`）を `open` だけで開く（`initialize` ・追記 ・修復 ・作成なし ・無ければ
  fail closed）。store の object は返さない ・保持しない（関数の中だけで使う）。
- 凍結 P9 の `cross_rules.check_world` を両方の全ての鎖で呼ぶ（`AuthorityStores.open` を使わないため。不変条件は複製しない ・
  P10-OBS-003）。違えば fail closed。
- 明示の瞬間 `at`（aware）・日 `as_of_date` だけ（時計 ・最新 ・現在なし）。凍結 P9 の時点の意味（`reviewed_at <= T` の最大の seq）。
- 返すのは Phase 10 が持つ不変の型（凍結の dataclass ・tuple ・文字列 ・数 ・日）だけ。

2 つの interface:
- `read_p9_safe_view`（既定）: 凍結 P9 の安全な投影（件数だけ）を不変の型に写す。発行体 ・P9 の id ・文 ・run ／ 結果の id は無い。
- `read_p9_private_snapshot`（private ・local だけ）: 時点 T の各 root の最小の状態（P9 の id ・先頭の revision の id ・発行体 ・状態 ・
  見直しの日 ・出所の種類 ／ Thesis の link）。文 ・根拠 ・run ／ 結果の id ・著者 ・瞬間は無い。

network ・credential ・P8 ・J-Quants ・LLM ・書き込みは無い。記録: `docs/databank/PHASE10_A1_P9_READONLY_ADAPTER.md`。
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from typing import Any, Dict, Mapping, Optional, Tuple

from ..watchlist_thesis_intelligence.cross_rules import check_world
from ..watchlist_thesis_intelligence.projection import safe_projection
from ..watchlist_thesis_intelligence.revision_model import SemanticModelError
from ..watchlist_thesis_intelligence.store_io import AuthorityStoreError
from ..watchlist_thesis_intelligence.thesis_store import ThesisStore
from ..watchlist_thesis_intelligence.watch_store import WatchlistStore

P9_VIEW_SCHEMA_VERSION = "p10_p9_view:0.1.0"
P9_VIEW_RULES_VERSION = "p10_p9_view:0.1.0"
SAFE_VIEW_CLASS = "P9_SAFE_VIEW_COUNTS_ONLY_DERIVED_NON_AUTHORITY_READ_ONLY"
PRIVATE_SNAPSHOT_CLASS = "P9_PRIVATE_SNAPSHOT_LOCAL_ONLY_DERIVED_NON_AUTHORITY_READ_ONLY"
Counts = Tuple[Tuple[str, int], ...]


class P9ViewError(ValueError):
    """読み込みの失敗（fail closed）。P9 の root には何も書かない ・修復しない ・path を detail に入れない。"""

    def __init__(self, code: str, detail: str = "") -> None:
        super().__init__(f"{code}: {detail}" if detail else code)
        self.code = code
        self.detail = detail


def _require(condition: bool, code: str, detail: str = "") -> None:
    if not condition:
        raise P9ViewError(code, detail)


def _instant(value: Any) -> datetime:
    _require(isinstance(value, datetime) and value.tzinfo is not None and value.tzinfo.utcoffset(value) is not None,
             "INSTANT_NOT_AWARE", "at")
    return value


def _day(value: Any) -> date:
    _require(type(value) is date, "INVALID_DATE", "as_of_date")
    return value


def _counts(mapping: Mapping[str, int]) -> Counts:
    return tuple((key, mapping[key]) for key in sorted(mapping))


class _ReadOnlyWorld:
    """関数の中だけで使う read-only の像（両方の store ＋ 世界の検査）。外へ返さない。"""

    __slots__ = ("watch", "thesis")

    def __init__(self, p9_root: Any) -> None:
        try:
            self.watch = WatchlistStore.open(p9_root)                            # open だけ（作らない ・無ければ例外）
            self.thesis = ThesisStore.open(p9_root)
        except AuthorityStoreError as exc:
            raise P9ViewError("P9_STORE_UNAVAILABLE", f"{exc.category.value}:{exc.code}") from None
        try:
            check_world(list(self.watch.all_revisions()), list(self.thesis.all_revisions()))
        except SemanticModelError as exc:
            raise P9ViewError("P9_WORLD_INVALID", exc.code) from None


# ---------------------------------------------------------------- 安全な view（既定 ・件数だけ）


@dataclass(frozen=True, kw_only=True)
class P9SafeView:
    as_of_date: date
    watch_count: int
    watch_status_counts: Counts
    watch_provenance_kind_counts: Counts
    watch_review_due_count: int
    watch_declared_thesis_link_count: int
    thesis_count: int
    thesis_status_counts: Counts
    thesis_review_due_count: int
    thesis_invalidation_basis_counts: Counts
    thesis_supporting_evidence_kind_counts: Counts
    thesis_counter_evidence_kind_counts: Counts
    view_class: str = SAFE_VIEW_CLASS
    rules_version: str = P9_VIEW_RULES_VERSION
    schema_version: str = P9_VIEW_SCHEMA_VERSION


def read_p9_safe_view(p9_root: Any, *, at: Any, as_of_date: Any) -> P9SafeView:
    """凍結 P9 の安全な投影（件数だけ）を時点 `at` ・日 `as_of_date` で読み、不変の型に写す。"""
    instant, day = _instant(at), _day(as_of_date)
    world = _ReadOnlyWorld(p9_root)
    view = safe_projection(world, at=instant, as_of_date=day)
    return P9SafeView(
        as_of_date=view.as_of_date, watch_count=view.watch_entry_count,
        watch_status_counts=_counts(view.watch_status_counts),
        watch_provenance_kind_counts=_counts(view.watch_provenance_kind_counts),
        watch_review_due_count=view.watch_review_due_count,
        watch_declared_thesis_link_count=view.watch_declared_thesis_link_count, thesis_count=view.thesis_count,
        thesis_status_counts=_counts(view.thesis_status_counts), thesis_review_due_count=view.thesis_review_due_count,
        thesis_invalidation_basis_counts=_counts(view.thesis_invalidation_basis_counts),
        thesis_supporting_evidence_kind_counts=_counts(view.thesis_supporting_evidence_kind_counts),
        thesis_counter_evidence_kind_counts=_counts(view.thesis_counter_evidence_kind_counts))


# ---------------------------------------------------------------- private な snapshot（local だけ ・最小の欄）


@dataclass(frozen=True, kw_only=True)
class P9WatchState:
    watch_entry_id: str
    revision_id: str
    issuer_id: str
    status: str
    review_due_on: Optional[date]
    provenance_kind: str


@dataclass(frozen=True, kw_only=True)
class P9ThesisState:
    thesis_id: str
    revision_id: str
    watch_entry_id: str
    status: str
    review_due_on: Optional[date]


@dataclass(frozen=True, kw_only=True)
class P9PrivateSnapshot:
    """時点 T の各 root の最小の状態（root の id の文字の順 ・非意味）。文 ・根拠 ・run ／ 結果の id ・著者 ・瞬間は無い。"""

    watch: Tuple[P9WatchState, ...]
    thesis: Tuple[P9ThesisState, ...]
    snapshot_class: str = PRIVATE_SNAPSHOT_CLASS
    rules_version: str = P9_VIEW_RULES_VERSION
    schema_version: str = P9_VIEW_SCHEMA_VERSION


def read_p9_private_snapshot(p9_root: Any, *, at: Any) -> P9PrivateSnapshot:
    """時点 `at` の Watchlist ／ Thesis の各 root の最小の状態（private ・local だけ）。"""
    instant = _instant(at)
    world = _ReadOnlyWorld(p9_root)
    watch_heads: Dict[str, Any] = world.watch.states_at(instant)
    thesis_heads: Dict[str, Any] = world.thesis.states_at(instant)
    watch = tuple(P9WatchState(watch_entry_id=h.watch_entry_id, revision_id=h.revision_id, issuer_id=h.issuer_id,
                               status=h.status.value, review_due_on=h.review_due_on,
                               provenance_kind=h.provenance.kind.value)
                  for _, h in sorted(watch_heads.items()))
    thesis = tuple(P9ThesisState(thesis_id=h.thesis_id, revision_id=h.revision_id, watch_entry_id=h.watch_entry_id,
                                 status=h.status.value, review_due_on=h.review_due_on)
                   for _, h in sorted(thesis_heads.items()))
    return P9PrivateSnapshot(watch=watch, thesis=thesis)


__all__ = ["P9PrivateSnapshot", "P9SafeView", "P9ThesisState", "P9ViewError", "P9WatchState",
           "P9_VIEW_RULES_VERSION", "P9_VIEW_SCHEMA_VERSION", "PRIVATE_SNAPSHOT_CLASS", "SAFE_VIEW_CLASS",
           "read_p9_private_snapshot", "read_p9_safe_view"]
