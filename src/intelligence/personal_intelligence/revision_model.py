"""P10-A2 — Personal Profile ／ Attention の不変の revision の共通の意味（純 ・時計なし ・保存なし ・file の入出力なし）。

- root（安定 id）と revision（内容 address の id）。revision は `seq`（1 から連番）・`prev_revision_id`（直前の revision）・
  `reviewed_at`（caller が渡す aware な人の審査の瞬間 ・非減少）・`author_ref`（`human:` 接頭辞）を持つ。上書きは無い。
- 変更の種類（`ChangeKind`）: `CREATE`（seq 1）・`REVISE` ・`CORRECTION` ・`TRANSITION`。種類は内容の差を意味しない（同じ内容の
  REVISE も有効）。差が要る消費者は欄を明示に比べる。どの種類を受けるかは各 model が決める（Attention は CORRECTION を受けない）。
- 時点 T の状態 ＝ 検査済みの鎖のうち `reviewed_at <= T` の最大の `seq`（`state_at` ・`states_at`）。物理の順は authority ではない。
- Phase 9 の参照の構文（発行体 ・Watchlist ／ Thesis の root ・revision の id）は構造だけの複製。凍結 P9 との一致は test が pin する。
  実在の検査は A4（A1 の adapter）。

記録: `docs/databank/PHASE10_A2_PROFILE_ATTENTION_SEMANTICS.md`。
"""
from __future__ import annotations

import json
import re
from datetime import datetime
from enum import Enum
from typing import Any, Callable, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

from ..core.ids import content_id
from ..core.time import to_utc_iso

PERSONAL_RULES_VERSION = "p10_personal_semantics:0.1.0"
#: Phase 9 の参照の構文（構造だけの複製。凍結 P9 との一致は test が pin）
P9_ISSUER_ID_PREFIX = "p8iss"
P9_WATCH_ENTRY_ID_PREFIX = "p9wat"
P9_WATCH_REVISION_ID_PREFIX = "p9wrv"
P9_THESIS_ID_PREFIX = "p9ths"
P9_THESIS_REVISION_ID_PREFIX = "p9trv"
_HUMAN_AUTHOR_RE = re.compile(r"^human:[A-Za-z0-9][A-Za-z0-9_.:@-]{0,113}$")
_CONTROL_RE = re.compile(r"[\x00-\x08\x0b-\x1f\x7f]")                              # 改行（\n）・tab は許す
CREDENTIAL_MARKERS = ("apikey", "api_key", "api-key", "token", "password", "passwd", "secret", "bearer",
                      "authorization")
MAX_NOTE_LEN = 2000


class PersonalModelError(ValueError):
    def __init__(self, code: str, detail: str = "") -> None:
        super().__init__(f"{code}: {detail}" if detail else code)
        self.code = code
        self.detail = detail


def require(condition: bool, code: str, detail: str = "") -> None:
    if not condition:
        raise PersonalModelError(code, detail)


class ChangeKind(str, Enum):
    CREATE = "CREATE"
    REVISE = "REVISE"
    CORRECTION = "CORRECTION"
    TRANSITION = "TRANSITION"


def canonical_json(payload: Mapping[str, Any]) -> str:
    """正準の JSON（key の文字の順 ・区切りの空白なし ・非 ASCII はそのまま）。"""
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def derive_id(prefix: str, payload: Mapping[str, Any]) -> str:
    """内容 address の id（sha256 の先頭 24 hex）。payload は正準の JSON。乱数は使わない。"""
    return content_id(prefix, canonical_json(payload))


def id_pattern(prefix: str) -> "re.Pattern[str]":
    return re.compile(rf"^{prefix}_[0-9a-f]{{24}}$")


def check_id(value: Any, pattern: "re.Pattern[str]", field_name: str) -> str:
    require(isinstance(value, str) and bool(pattern.match(value)), f"INVALID_{field_name.upper()}", field_name)
    return value


def check_author(value: Any) -> str:
    """人の authority だけ（`human:` 接頭辞）。code ・LLM ・system の著者は無い。"""
    require(isinstance(value, str) and bool(_HUMAN_AUTHOR_RE.match(value)), "AUTHOR_NOT_HUMAN", "author_ref")
    require(not any(marker in value.lower() for marker in CREDENTIAL_MARKERS), "CREDENTIAL_LIKE_TEXT", "author_ref")
    return value


def check_instant(value: Any, field_name: str) -> datetime:
    require(isinstance(value, datetime) and value.tzinfo is not None and value.tzinfo.utcoffset(value) is not None,
            "INSTANT_NOT_AWARE", field_name)                                     # caller が渡す（時計 ・既定は無い）
    return value


def check_note(value: Any, field_name: str, *, required: bool) -> str:
    """人が書く質的な文。語 ・数字は検閲しない（数の authority は型の欄にしか無い ・文は解釈しない）。
    文字列 ・長さ ・制御文字 ・credential らしい文だけを検査する。"""
    require(isinstance(value, str), "NOTE_NOT_STRING", field_name)
    if value == "":
        require(not required, "NOTE_REQUIRED", field_name)
        return value
    require(value.strip() != "" and len(value) <= MAX_NOTE_LEN, "INVALID_NOTE", field_name)
    require(not _CONTROL_RE.search(value), "CONTROL_CHARACTER", field_name)
    require(not any(marker in value.lower() for marker in CREDENTIAL_MARKERS), "CREDENTIAL_LIKE_TEXT", field_name)
    return value


def iso_instant(value: datetime) -> str:
    return to_utc_iso(value)


# ---------------------------------------------------------------- 鎖 ・時点の状態（物理の順は使わない）


def check_successor_frame(prev: Any, nxt: Any) -> None:
    """全 revision に共通の連続の規則（同じ root ・seq ＋1 ・直前の revision ・reviewed_at の非減少 ・CREATE は 1 回だけ）。"""
    require(nxt.root_id == prev.root_id, "ROOT_MISMATCH", "root_id")
    require(nxt.seq == prev.seq + 1, "SEQ_NOT_CONSECUTIVE", "seq")
    require(nxt.prev_revision_id == prev.revision_id, "PREV_REVISION_MISMATCH", "prev_revision_id")
    require(nxt.reviewed_at >= prev.reviewed_at, "REVIEWED_AT_REGRESSED", "reviewed_at")
    require(nxt.change_kind is not ChangeKind.CREATE, "CREATE_NOT_FIRST", "change_kind")


def ordered_chain(revisions: Iterable[Any], validate_successor: Callable[[Any, Any, Sequence[Any]], None]) -> List[Any]:
    """1 つの root の revision の集まり → seq 順の検査済みの鎖。入力の順には依らない。"""
    chain = sorted(revisions, key=lambda r: r.seq)
    require(len(chain) >= 1, "EMPTY_CHAIN", "revisions")
    require(chain[0].seq == 1 and chain[0].change_kind is ChangeKind.CREATE and chain[0].prev_revision_id == "",
            "INVALID_INITIAL_REVISION", "seq")
    require(len({r.revision_id for r in chain}) == len(chain), "DUPLICATE_REVISION", "revision_id")
    for index in range(1, len(chain)):
        validate_successor(chain[index - 1], chain[index], chain[:index])
    return chain


def revision_at_seq(chain: Sequence[Any], seq: int) -> Any:
    """検査済みの鎖の seq の revision（無ければ fail closed）。"""
    require(type(seq) is int and seq >= 1, "INVALID_SEQ", "seq")
    found = [r for r in chain if r.seq == seq]
    require(len(found) == 1, "SEQ_NOT_FOUND", str(seq))
    return found[0]


def state_at(chain: Sequence[Any], instant: Any) -> Optional[Any]:
    """時点 T の状態: 検査済みの鎖の `reviewed_at <= T` の最大の seq（無ければ None）。"""
    at = check_instant(instant, "at")
    visible = [r for r in chain if r.reviewed_at <= at]
    return max(visible, key=lambda r: r.seq) if visible else None


def states_at(chains: Mapping[str, Sequence[Any]], instant: Any) -> Dict[str, Any]:
    """root → 時点 T の状態（T にまだ無い root は含まない）。root の id の文字の順。"""
    at = check_instant(instant, "at")
    return {root: head for root in sorted(chains) if (head := state_at(chains[root], at)) is not None}


def group_chains(revisions: Sequence[Any], validate_chain: Callable[[Sequence[Any]], Tuple[Any, ...]],
                 kind: type) -> Dict[str, Tuple[Any, ...]]:
    """revision の集まり → root → 検査済みの鎖（root の id の文字の順）。"""
    require(isinstance(revisions, (list, tuple)), "INVALID_REVISIONS", kind.__name__)
    for revision in revisions:
        require(isinstance(revision, kind), "INVALID_REVISION", kind.__name__)
    roots = sorted({revision.root_id for revision in revisions})
    return {root: validate_chain([r for r in revisions if r.root_id == root]) for root in roots}


__all__ = ["CREDENTIAL_MARKERS", "ChangeKind", "MAX_NOTE_LEN", "P9_ISSUER_ID_PREFIX", "P9_THESIS_ID_PREFIX",
           "P9_THESIS_REVISION_ID_PREFIX", "P9_WATCH_ENTRY_ID_PREFIX", "P9_WATCH_REVISION_ID_PREFIX",
           "PERSONAL_RULES_VERSION", "PersonalModelError", "canonical_json", "check_author", "check_id",
           "check_instant", "check_note", "check_successor_frame", "derive_id", "group_chains", "id_pattern",
           "iso_instant", "ordered_chain", "require", "revision_at_seq", "state_at", "states_at"]
