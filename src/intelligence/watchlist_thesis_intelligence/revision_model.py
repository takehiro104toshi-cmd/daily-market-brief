"""P9-A2 — Watchlist ／ Thesis の不変の revision の共通の意味（純 ・時計なし ・保存なし）。

- root（安定 id）と revision（内容 address の id）。revision は `seq`（1 から連番）・`prev_revision_id`（直前の revision）・
  `reviewed_at`（caller が渡す aware な人の審査の瞬間 ・非減少）・`author_ref`（`human:` 接頭辞）を持つ。上書きは無い。
- 変更の種類（`ChangeKind`）: `CREATE`（seq 1）・`REVISE`（内容 ・状態は同じ）・`TRANSITION`（状態だけが変わる。状態機械に従う）・
  `CORRECTION`（以前の revision の誤りを、状態を変えずに新しい revision で正す。過去の revision は書き換えない）。
- 時点 T の状態 ＝ 検査済みの鎖のうち `reviewed_at <= T` の最大の `seq`。file の順は authority ではない（`state_at`）。
- 発行体の id の構文は凍結 A1 の IssuerId（`p8iss_<24 hex>`）と同じ。一致は test が凍結 A1 の検査関数で pin する。

記録: `docs/databank/PHASE9_A2_WATCHLIST_THESIS_SEMANTICS.md`。
"""
from __future__ import annotations

import json
import re
from datetime import date, datetime
from enum import Enum
from typing import Any, Iterable, List, Mapping, Optional, Sequence, Tuple

from ..core.ids import content_id
from ..core.time import to_utc_iso

SEMANTICS_RULES_VERSION = "p9_watchlist_thesis_semantics:0.1.0"
#: 凍結 A1 の IssuerId の構文（複製。一致は test が pin）
_ISSUER_ID_RE = re.compile(r"^p8iss_[0-9a-f]{24}$")
_HUMAN_AUTHOR_RE = re.compile(r"^human:[A-Za-z0-9][A-Za-z0-9_.:@-]{0,113}$")
_CONTROL_RE = re.compile(r"[\x00-\x08\x0b-\x1f\x7f]")                              # 改行（\n）・tab は許す
CREDENTIAL_MARKERS = ("apikey", "api_key", "api-key", "token", "password", "passwd", "secret", "bearer",
                      "authorization")
MAX_TEXT_LEN = 4000
MAX_SHORT_TEXT_LEN = 500
MAX_LIST_ITEMS = 50


class SemanticModelError(ValueError):
    def __init__(self, code: str, detail: str = "") -> None:
        super().__init__(f"{code}: {detail}" if detail else code)
        self.code = code
        self.detail = detail


def require(condition: bool, code: str, detail: str = "") -> None:
    if not condition:
        raise SemanticModelError(code, detail)


class ChangeKind(str, Enum):
    CREATE = "CREATE"
    REVISE = "REVISE"
    TRANSITION = "TRANSITION"
    CORRECTION = "CORRECTION"


def canonical_json(payload: Mapping[str, Any]) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def derive_id(prefix: str, payload: Mapping[str, Any]) -> str:
    """内容 address の id（sha256 の先頭 24 hex ＝ 96 bit）。payload は正準の JSON。"""
    return content_id(prefix, canonical_json(payload))


def id_pattern(prefix: str) -> "re.Pattern[str]":
    return re.compile(rf"^{prefix}_[0-9a-f]{{24}}$")


def is_issuer_id(value: Any) -> bool:
    return isinstance(value, str) and bool(_ISSUER_ID_RE.match(value))


def check_id(value: Any, pattern: "re.Pattern[str]", field_name: str) -> str:
    require(isinstance(value, str) and bool(pattern.match(value)), f"INVALID_{field_name.upper()}", field_name)
    return value


def check_issuer(value: Any) -> str:
    require(is_issuer_id(value), "INVALID_ISSUER_ID", "issuer_id")
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


def check_date(value: Any, field_name: str, *, required: bool) -> Optional[date]:
    if value is None:
        require(not required, "DATE_REQUIRED", field_name)
        return None
    require(type(value) is date, "INVALID_DATE", field_name)                     # datetime は受けない（日だけ）
    return value


def check_text(value: Any, field_name: str, *, required: bool = True, max_len: int = MAX_TEXT_LEN) -> str:
    """人が書く自由文。普通の語は検閲しない（構造の guard を優先）。制御文字 ・credential らしい文 ・長さだけを検査する。"""
    require(isinstance(value, str), "TEXT_NOT_STRING", field_name)
    if not required and value == "":
        return value
    require(value.strip() != "" and len(value) <= max_len, "INVALID_TEXT", field_name)
    require(not _CONTROL_RE.search(value), "CONTROL_CHARACTER", field_name)
    require(not any(marker in value.lower() for marker in CREDENTIAL_MARKERS), "CREDENTIAL_LIKE_TEXT", field_name)
    return value


def check_text_list(values: Any, field_name: str, *, max_len: int = MAX_SHORT_TEXT_LEN) -> Tuple[str, ...]:
    require(isinstance(values, tuple) and len(values) <= MAX_LIST_ITEMS, "INVALID_TEXT_LIST", field_name)
    for value in values:
        check_text(value, field_name, max_len=max_len)
    require(len(set(values)) == len(values), "DUPLICATE_TEXT_ITEM", field_name)
    return values


def iso_date(value: Optional[date]) -> Optional[str]:
    return value.isoformat() if value is not None else None


def iso_instant(value: datetime) -> str:
    return to_utc_iso(value)


# ---------------------------------------------------------------- 鎖 ・時点の状態（file の順は使わない）


def check_successor_frame(prev: Any, nxt: Any) -> None:
    """全 revision に共通の連続の規則（同じ root ・seq ＋1 ・直前の revision ・reviewed_at の非減少 ・CREATE は 1 回だけ）。"""
    require(nxt.root_id == prev.root_id, "ROOT_MISMATCH", "root_id")
    require(nxt.seq == prev.seq + 1, "SEQ_NOT_CONSECUTIVE", "seq")
    require(nxt.prev_revision_id == prev.revision_id, "PREV_REVISION_MISMATCH", "prev_revision_id")
    require(nxt.reviewed_at >= prev.reviewed_at, "REVIEWED_AT_REGRESSED", "reviewed_at")
    require(nxt.change_kind is not ChangeKind.CREATE, "CREATE_NOT_FIRST", "change_kind")


def check_correction_reference(chain: Sequence[Any], nxt: Any) -> None:
    """CORRECTION は同じ鎖の既存の revision を正す（対象は直前以前）。"""
    if nxt.change_kind is ChangeKind.CORRECTION:
        require(nxt.corrects_revision_id in {r.revision_id for r in chain}, "CORRECTION_TARGET_UNKNOWN",
                "corrects_revision_id")


def ordered_chain(revisions: Iterable[Any], validate_successor) -> List[Any]:
    """revision の集まり → seq 順の検査済みの鎖。入力の順（file の順）には依らない。"""
    chain = sorted(revisions, key=lambda r: r.seq)
    require(len(chain) >= 1, "EMPTY_CHAIN", "revisions")
    require(chain[0].seq == 1 and chain[0].change_kind is ChangeKind.CREATE and chain[0].prev_revision_id == "",
            "INVALID_INITIAL_REVISION", "seq")
    require(len({r.revision_id for r in chain}) == len(chain), "DUPLICATE_REVISION", "revision_id")
    for index in range(1, len(chain)):
        validate_successor(chain[index - 1], chain[index], chain[:index])
    return chain


def state_at(chain: Sequence[Any], instant: Any) -> Optional[Any]:
    """時点 T の状態: 検査済みの鎖の `reviewed_at <= T` の最大の seq（無ければ None）。"""
    at = check_instant(instant, "as_of")
    visible = [r for r in chain if r.reviewed_at <= at]
    return max(visible, key=lambda r: r.seq) if visible else None


__all__ = ["CREDENTIAL_MARKERS", "ChangeKind", "MAX_LIST_ITEMS", "MAX_SHORT_TEXT_LEN", "MAX_TEXT_LEN",
           "SEMANTICS_RULES_VERSION", "SemanticModelError", "canonical_json", "check_author", "check_correction_reference",
           "check_date", "check_id", "check_instant", "check_issuer", "check_successor_frame", "check_text",
           "check_text_list", "derive_id", "id_pattern", "is_issuer_id", "iso_date", "iso_instant", "ordered_chain",
           "require", "state_at"]
