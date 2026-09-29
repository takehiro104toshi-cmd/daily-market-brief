"""P6-B7F — 検証済み plan の提出結果の純 model（非 authority。I/O なし）。

提出は既存の proposal authority（B3 / B5C）に**提案**を置くことだけであり、次のどれでもない（凍結文言）:

- 提案 ≠ decision（ACCEPT / REJECT / DEFER / NOT_DUPLICATE は人間の後段）
- 提案 ≠ 受理された Theme（ThemeRoot / ThemeObservation を作らない）
- 提案 ≠ evidence attachment（Foundation に付与しない）
- 提案 ≠ relation assertion（B5B に主張を書かない。SOURCE_ASSERTED は提案のまま）

結果は決定論的で、score・確信度・順位・severity・推奨の強さを持たない。
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum
from typing import Dict, Tuple

from ..themes.model import canonical_json

SUBMISSION_RESULT_SCHEMA_VERSION = "theme_llm_proposal_submission:0.1.0"

#: 凍結文言（contract / test で固定する）
PROPOSAL_IS_NOT_DECISION = ("a submitted proposal is not a decision, an accepted Theme, an evidence attachment or a "
                            "relation assertion")
SUBMISSION_IS_NOT_A_BACKTEST = ("submission runs against the current proposal authority only; it must not be used for "
                                "historical replay or backtests")

_CODE_RE = re.compile(r"^[A-Z][A-Z0-9_:]{0,95}$")


class SubmissionModelError(ValueError):
    def __init__(self, code: str, detail: str = "") -> None:
        super().__init__(f"{code}: {detail}" if detail else code)
        self.code = code
        self.detail = detail


def _require(condition: bool, code: str, detail: str = "") -> None:
    if not condition:
        raise SubmissionModelError(code, detail)


class AuthorityFamily(str, Enum):
    """提出先。既存の L1 proposal authority だけ（新しい authority は作らない）。"""

    B3_PROPOSALS = "B3_PROPOSALS"                       # B3 EVIDENCE_CANDIDATE / THEME_CANDIDATE
    B5C_RELATION_PROPOSALS = "B5C_RELATION_PROPOSALS"   # B5C RELATION_CANDIDATE


#: 追記の順序（family → 上流 proposal id）。LLM の候補順に依らない
FAMILY_ORDER: Tuple[AuthorityFamily, ...] = (AuthorityFamily.B3_PROPOSALS, AuthorityFamily.B5C_RELATION_PROPOSALS)


class SubmissionAction(str, Enum):
    NEW_PROPOSAL_APPENDED = "NEW_PROPOSAL_APPENDED"
    EXISTING_PROPOSAL_REUSED = "EXISTING_PROPOSAL_REUSED"
    DUPLICATE_IN_SUBMISSION = "DUPLICATE_IN_SUBMISSION"   # 同じ提出の中の同一提案（1 回だけ扱う）
    NOT_SUBMITTED = "NOT_SUBMITTED"


class ReuseKind(str, Enum):
    NONE = "NONE"
    EXACT = "EXACT"              # 既存行と byte 一致（同じ提出の再実行）
    CONVERGENT = "CONVERGENT"    # 意味 identity は同じで、provenance / created_at だけが違う（B5 §10.1 の収束）


class SubmissionStatus(str, Enum):
    SUBMITTED = "SUBMITTED"                    # 予定した全 action を終えた（新規 0 件の全再利用を含む）
    REJECTED = "REJECTED"                      # 書き込み 0 件で止まった
    PARTIAL_SUBMISSION = "PARTIAL_SUBMISSION"  # 追記の途中で失敗した（巻き戻さない）


SUBMISSION_FAILURE_CODES: Tuple[str, ...] = (
    "INVALID_SUBMISSION_INPUT", "PLAN_INTEGRITY_FAILURE", "UPSTREAM_ID_MISMATCH", "AUTHORITY_CORRUPTION",
    "PROPOSAL_CONFLICT", "APPEND_FAILURE", "PARTIAL_SUBMISSION")


@dataclass(frozen=True, kw_only=True)
class PlanSubmission:
    """plan 1 件の扱い。`line_appended` は authority に 1 行が加わったかどうか。"""

    plan_id: str
    family: AuthorityFamily
    upstream_proposal_id: str
    action: SubmissionAction
    reuse: ReuseKind = ReuseKind.NONE
    line_appended: bool = False
    failure_code: str = ""

    def __post_init__(self) -> None:
        _require(isinstance(self.family, AuthorityFamily) and isinstance(self.action, SubmissionAction)
                 and isinstance(self.reuse, ReuseKind), "INVALID_RESULT", "family, action and reuse are enums")
        _require(self.line_appended == (self.action is SubmissionAction.NEW_PROPOSAL_APPENDED), "INVALID_RESULT",
                 "only a new proposal adds a line")
        _require((self.reuse is not ReuseKind.NONE) == (self.action is SubmissionAction.EXISTING_PROPOSAL_REUSED),
                 "INVALID_RESULT", "only a reused proposal names its reuse kind")
        _require(self.failure_code == "" or (self.action is SubmissionAction.NOT_SUBMITTED
                                             and self.failure_code in SUBMISSION_FAILURE_CODES),
                 "INVALID_RESULT", "a failure code belongs to a plan that was not submitted")


@dataclass(frozen=True, kw_only=True)
class SubmissionResult:
    result_schema_version: str = SUBMISSION_RESULT_SCHEMA_VERSION
    status: SubmissionStatus
    actions: Tuple[PlanSubmission, ...] = ()
    failure_code: str = ""
    failure_detail: str = ""        # 上流の有界 code だけ（本文・秘密値を入れない）

    def __post_init__(self) -> None:
        _require(isinstance(self.status, SubmissionStatus), "INVALID_RESULT", "status is an enum")
        _require(all(isinstance(a, PlanSubmission) for a in self.actions), "INVALID_RESULT", "actions are PlanSubmission")
        object.__setattr__(self, "actions", tuple(sorted(self.actions, key=lambda a: (
            FAMILY_ORDER.index(a.family), a.upstream_proposal_id, a.plan_id))))
        _require(self.failure_detail == "" or bool(_CODE_RE.match(self.failure_detail)), "INVALID_RESULT",
                 "failure detail is a bounded code")
        appended = self.appended_count()
        if self.status is SubmissionStatus.SUBMITTED:
            _require(self.failure_code == "" and not any(a.failure_code for a in self.actions)
                     and not any(a.action is SubmissionAction.NOT_SUBMITTED for a in self.actions), "INVALID_RESULT",
                     "a completed submission has no failure")
        elif self.status is SubmissionStatus.REJECTED:
            _require(self.failure_code in SUBMISSION_FAILURE_CODES and appended == 0, "INVALID_RESULT",
                     "a rejected submission names its failure and added nothing")
        else:
            _require(self.failure_code == "PARTIAL_SUBMISSION" and appended >= 1, "INVALID_RESULT",
                     "a partial submission added at least one line before failing")

    def appended_count(self) -> int:
        return sum(1 for a in self.actions if a.line_appended)

    def as_dict(self) -> Dict[str, object]:
        return {"result_schema_version": self.result_schema_version, "status": self.status,
                "actions": self.actions, "failure_code": self.failure_code, "failure_detail": self.failure_detail}

    def canonical_json(self) -> str:
        return canonical_json(self.as_dict())


__all__ = ["AuthorityFamily", "FAMILY_ORDER", "PROPOSAL_IS_NOT_DECISION", "PlanSubmission", "ReuseKind",
           "SUBMISSION_FAILURE_CODES", "SUBMISSION_IS_NOT_A_BACKTEST", "SUBMISSION_RESULT_SCHEMA_VERSION",
           "SubmissionAction", "SubmissionModelError", "SubmissionResult", "SubmissionStatus"]
