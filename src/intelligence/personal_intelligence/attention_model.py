"""P10-A2 — Attention（FOCUS ／ MUTE）の意味の model（人の authority ・表示の意図だけ ・不変の revision ・純）。

Attention ＝ 人が「この調べの記録をもっと出す（FOCUS）／ あまり出さない（MUTE）」と決めた印。投資の意味は無い。順位 ・
優先度 ・緊急度 ・重み ・確信 ・推奨 ・売買の数は無く、FOCUS と MUTE の間に順序は無い（表示の意図の列挙だけ）。自由文の欄も無い。

- 対象: P9 の root の id ちょうど 1 つ（Watchlist の項目 `p9wat_` か Thesis `p9ths_`）。発行体だけの印は無い（P9 の Watchlist の
  意味を複製しない）。印は後の P9 の revision を越えて生きる（P9 の revision が増えても黙って無効にならない）。
  `observed_p9_revision_id` は人が印を作る ／ 改める時に見た P9 の revision（出所 ・文脈だけ ・authority ではない）。
- root: `attention_id`（`p10att_<24 hex>`）＝ 対象の種類 ・対象の root ・作成の著者 ・reviewed_at から導く。
- revision: `revision_id`（`p10arv_<24 hex>`）＝ 全欄の内容 address。
- 状態: `FOCUS` ・`MUTE` ・`CLEARED`（終端 ＝ この記録をもう個人化しない）。印が無いこと ＝ 既定（NORMAL は保存しない）。
  CREATE → FOCUS か MUTE ／ FOCUS ⇄ MUTE ・FOCUS ／ MUTE → CLEARED（TRANSITION）／ 同じ状態のまま見た revision を改める（REVISE）。
  CLEARED の後に同じ対象へ印を付け直すのは新しい root。CORRECTION は無い（直す内容が状態と見た revision だけで、TRANSITION ・REVISE と
  同じ変化に 2 つの書き方を作らない）。対象の誤りは CLEARED ＋ 正しい対象の新しい root。
- 実在（対象の root ・見た revision が P9 に在る ・同じ鎖）の検査は A4（A1 の adapter）。A2 は構文だけ。

記録: `docs/databank/PHASE10_A2_PROFILE_ATTENTION_SEMANTICS.md`。
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Any, Dict, Sequence, Tuple

from .revision_model import (ChangeKind, P9_THESIS_ID_PREFIX, P9_THESIS_REVISION_ID_PREFIX, P9_WATCH_ENTRY_ID_PREFIX,
                             P9_WATCH_REVISION_ID_PREFIX, PERSONAL_RULES_VERSION, check_author, check_id,
                             check_instant, check_successor_frame, derive_id, id_pattern, iso_instant, ordered_chain,
                             require)

ATTENTION_ID_PREFIX = "p10att"
ATTENTION_REVISION_ID_PREFIX = "p10arv"
ATTENTION_SCHEMA_VERSION = "p10_attention_revision:0.1.0"
ATTENTION_AUTHORITY_CLASS = "HUMAN_REVIEWED_DISPLAY_INTENT_ONLY_NOT_A_RANK_NOT_A_RECOMMENDATION"
_ATTENTION_RE = id_pattern(ATTENTION_ID_PREFIX)
_ATTENTION_REVISION_RE = id_pattern(ATTENTION_REVISION_ID_PREFIX)


class AttentionTargetKind(str, Enum):
    P9_WATCH_ENTRY = "P9_WATCH_ENTRY"
    P9_THESIS = "P9_THESIS"


#: 対象の種類 → (root の id の構文, 見た revision の id の構文)
ATTENTION_TARGET_SYNTAX: Dict[AttentionTargetKind, Tuple[str, str]] = {
    AttentionTargetKind.P9_WATCH_ENTRY: (P9_WATCH_ENTRY_ID_PREFIX, P9_WATCH_REVISION_ID_PREFIX),
    AttentionTargetKind.P9_THESIS: (P9_THESIS_ID_PREFIX, P9_THESIS_REVISION_ID_PREFIX),
}
_TARGET_RES = {kind: (id_pattern(root), id_pattern(revision)) for kind, (root, revision) in
               ATTENTION_TARGET_SYNTAX.items()}


class AttentionState(str, Enum):
    FOCUS = "FOCUS"
    MUTE = "MUTE"
    CLEARED = "CLEARED"


#: 生きている印（対象ごとに時点ごと高々 1 つ ・cross_rules）。順序は無い
LIVE_ATTENTION_STATES = frozenset({AttentionState.FOCUS, AttentionState.MUTE})
#: 状態機械（人の TRANSITION だけ）。CLEARED は終端
ATTENTION_TRANSITIONS: Dict[AttentionState, Tuple[AttentionState, ...]] = {
    AttentionState.FOCUS: (AttentionState.MUTE, AttentionState.CLEARED),
    AttentionState.MUTE: (AttentionState.FOCUS, AttentionState.CLEARED),
    AttentionState.CLEARED: (),
}
ATTENTION_CHANGE_KINDS = (ChangeKind.CREATE, ChangeKind.REVISE, ChangeKind.TRANSITION)


def derive_attention_id(*, target_kind: AttentionTargetKind, target_root_id: str, author_ref: str,
                        reviewed_at: datetime) -> str:
    """root の安定 id（対象の種類 ・対象の root ・作成の著者 ・審査の瞬間）。付け直しは別の reviewed_at → 別の root。"""
    return derive_id(ATTENTION_ID_PREFIX, {"author_ref": author_ref, "reviewed_at": iso_instant(reviewed_at),
                                           "schema_version": ATTENTION_SCHEMA_VERSION,
                                           "target_kind": target_kind.value, "target_root_id": target_root_id})


@dataclass(frozen=True, kw_only=True)
class AttentionRevision:
    """Attention の不変の 1 revision（人の authority ・表示の意図だけ）。未知の欄は型が受けない（kw_only）。"""

    attention_id: str
    seq: int
    prev_revision_id: str
    change_kind: ChangeKind
    target_kind: AttentionTargetKind
    target_root_id: str
    observed_p9_revision_id: str
    state: AttentionState
    author_ref: str
    reviewed_at: datetime
    authority_class: str = ATTENTION_AUTHORITY_CLASS
    rules_version: str = PERSONAL_RULES_VERSION
    schema_version: str = ATTENTION_SCHEMA_VERSION

    def __post_init__(self) -> None:
        check_id(self.attention_id, _ATTENTION_RE, "attention_id")
        require(type(self.seq) is int and self.seq >= 1, "INVALID_SEQ", "seq")
        require(isinstance(self.change_kind, ChangeKind), "INVALID_CHANGE_KIND", "change_kind")
        require(self.change_kind in ATTENTION_CHANGE_KINDS, "CHANGE_KIND_NOT_SUPPORTED", self.change_kind.value)
        require(isinstance(self.target_kind, AttentionTargetKind), "INVALID_TARGET_KIND", "target_kind")
        require(isinstance(self.state, AttentionState), "INVALID_STATE", "state")
        root_re, revision_re = _TARGET_RES[self.target_kind]
        check_id(self.target_root_id, root_re, "target_root_id")
        check_id(self.observed_p9_revision_id, revision_re, "observed_p9_revision_id")
        check_author(self.author_ref)
        check_instant(self.reviewed_at, "reviewed_at")
        if self.seq == 1:
            require(self.change_kind is ChangeKind.CREATE and self.prev_revision_id == ""
                    and self.state in LIVE_ATTENTION_STATES, "INVALID_INITIAL_REVISION", "seq")
            require(self.attention_id == derive_attention_id(target_kind=self.target_kind,
                                                             target_root_id=self.target_root_id,
                                                             author_ref=self.author_ref,
                                                             reviewed_at=self.reviewed_at),
                    "ATTENTION_ID_MISMATCH", "attention_id")
        else:
            check_id(self.prev_revision_id, _ATTENTION_REVISION_RE, "prev_revision_id")
        require(self.authority_class == ATTENTION_AUTHORITY_CLASS, "AUTHORITY_CLASS_MISMATCH", "authority_class")
        require(self.rules_version == PERSONAL_RULES_VERSION, "RULES_VERSION_MISMATCH", "rules_version")
        require(self.schema_version == ATTENTION_SCHEMA_VERSION, "SCHEMA_MISMATCH", "schema_version")

    @property
    def root_id(self) -> str:
        return self.attention_id

    def identity_payload(self) -> Dict[str, Any]:
        return {"attention_id": self.attention_id, "authority_class": self.authority_class,
                "author_ref": self.author_ref, "change_kind": self.change_kind.value,
                "observed_p9_revision_id": self.observed_p9_revision_id, "prev_revision_id": self.prev_revision_id,
                "reviewed_at": iso_instant(self.reviewed_at), "rules_version": self.rules_version,
                "schema_version": self.schema_version, "seq": self.seq, "state": self.state.value,
                "target_kind": self.target_kind.value, "target_root_id": self.target_root_id}

    @property
    def revision_id(self) -> str:
        return derive_id(ATTENTION_REVISION_ID_PREFIX, self.identity_payload())

    def as_dict(self) -> Dict[str, Any]:
        return {**self.identity_payload(), "revision_id": self.revision_id}


def validate_attention_successor(prev: AttentionRevision, nxt: AttentionRevision,
                                 chain: Sequence[AttentionRevision] = ()) -> None:
    """直前の revision → 次の revision の規則（純）。対象は変わらない ・CLEARED からの復活は無い。"""
    require(isinstance(prev, AttentionRevision) and isinstance(nxt, AttentionRevision), "INVALID_REVISION",
            "revision")
    check_successor_frame(prev, nxt)
    require(prev.state is not AttentionState.CLEARED, "TERMINAL_STATE", prev.state.value)
    require(nxt.target_kind is prev.target_kind and nxt.target_root_id == prev.target_root_id, "TARGET_CHANGED",
            "target_root_id")
    if nxt.change_kind is ChangeKind.TRANSITION:
        require(nxt.state in ATTENTION_TRANSITIONS[prev.state], "ILLEGAL_TRANSITION",
                f"{prev.state.value}->{nxt.state.value}")
    else:                                                                        # REVISE は状態を変えない
        require(nxt.state is prev.state, "STATE_CHANGE_REQUIRES_TRANSITION", nxt.change_kind.value)


def validate_attention_chain(revisions: Sequence[AttentionRevision]) -> Tuple[AttentionRevision, ...]:
    """1 つの root の revision の集まり → seq 順の検査済みの鎖（入力の順に依らない）。"""
    for revision in revisions:
        require(isinstance(revision, AttentionRevision), "INVALID_REVISION", "revision")
    return tuple(ordered_chain(revisions, validate_attention_successor))


__all__ = ["ATTENTION_AUTHORITY_CLASS", "ATTENTION_CHANGE_KINDS", "ATTENTION_ID_PREFIX",
           "ATTENTION_REVISION_ID_PREFIX", "ATTENTION_SCHEMA_VERSION", "ATTENTION_TARGET_SYNTAX",
           "ATTENTION_TRANSITIONS", "AttentionRevision", "AttentionState", "AttentionTargetKind",
           "LIVE_ATTENTION_STATES", "derive_attention_id", "validate_attention_chain", "validate_attention_successor"]
