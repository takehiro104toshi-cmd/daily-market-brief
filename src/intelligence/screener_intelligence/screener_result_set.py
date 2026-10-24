"""P8-B5B — 複数発行体の screen の型つきの全結果の集合（private ・派生 ・保存しない）。

答える問い: 「宣言した Universe のすべての member に何が起きたか」。「どの発行体が MATCH したか」だけではない（MATCH だけの出力は、財務 data の
欠損 ・identity の未解決 ・取得の失敗 ・予算の延期 ・authority の失敗 ・不適格を隠し、coverage の偏りを作る）。

- 2 つの粒度を分ける: **Universe の member の結果**（provider の上場物 code ごとに 1 つ）と **発行体の screen の結果**（審査済みの IssuerId
  ごとに 1 つ）。複数の code が同じ発行体に解けても、発行体の評価は 1 つ（主の上場物は選ばない）。identity の解決 ・適格の実行は本 module に
  無い（後の実行器 B5C が渡す）。
- 発行体の結果は凍結 B4A の `SafeScreenerSummary` を合成する（凍結 B2 ／ B4A の状態の語彙 MATCH ／ NO_MATCH ／ HOLD ／ NOT_EVALUABLE ／
  AUTHORITY_FAILURE をそのまま持つ。部分の MATCH ・点数 ・確信 ・順位は無い）。観測値 ・閾値は持たない。
- 順: member の結果は Universe の宣言の順（非意味）。発行体の結果は、その発行体を参照する最初の member の宣言の位置の順（非意味。状態 ・
  基準の数 ・値で並べない）。順が違う入力は並べ替えず拒む（`assemble_result_set` が決定論の順を作る）。
- 実行の完全性（COMPLETE ／ PARTIAL）と財務 data の完全性（件数）は別。NOT_EVALUABLE ・NO_MATCH ・AUTHORITY_FAILURE は実行として終端。
- MATCH の部分集合は全結果から派生するだけ（別の authority ・保存 ・順位は無い）。
- 結果は DERIVED_NON_AUTHORITY_NON_PERSISTENT。journal ・database ・現在の結果の file ・MATCH の store ・時計 ・network ・IO は無い。
記録: `docs/databank/PHASE8_B5B_RESULT_SET.md`。
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from enum import Enum
from typing import Any, Dict, Mapping, Optional, Sequence, Tuple

from ..core.ids import content_id
from ..core.time import to_utc_iso
from .identity_bootstrap_model import day_start_jst
from .identity_model import IDENTIFIER_PATTERNS, IdentifierScheme, canonical_json, is_issuer_id
from .metric_model import DERIVED_NON_AUTHORITY_NON_PERSISTENT
from .screener_criteria_model import DataCompleteness, ScreenerAuthorityMode, ScreenerState
from .screener_result_summary import SafeScreenerSummary

RESULT_SET_SCHEMA_VERSION = "p8_screener_result_set:0.1.0"
RESULT_SET_RULES_VERSION = "p8_screener_result_set:0.1.0"
RESULT_SET_ID_PREFIX = "p8srs"
#: 順の規則（直列化だけ。順位 ・優先 ・魅力 ・確信ではない）
MEMBER_ORDER_RULE = "UNIVERSE_DECLARED_ORDER_NON_SEMANTIC"
ISSUER_ORDER_RULE = "FIRST_REFERENCING_MEMBER_DECLARED_POSITION_NON_SEMANTIC"
#: 実行の完全性の規則（すべての member が終端の試みに達したか。財務 data の完全性ではない）
EXECUTION_COMPLETENESS_RULE = "COMPLETE_IFF_NO_MEMBER_BUDGET_DEFERRED_OR_NOT_ATTEMPTED"
#: MATCH の意味（これ以上の意味は無い）
MATCH_SUBSET_MEANING = "ISSUERS_WHOSE_EVALUATION_MATCHED_EVERY_CRITERION_OF_THE_EXPLICIT_POLICY"
_UNIVERSE_ID_RE = re.compile(r"^p8uni_[0-9a-f]{24}$")
_POLICY_ID_RE = re.compile(r"^p8pol_[0-9a-f]{24}$")
_REASON_CODE_RE = re.compile(r"^[A-Z][A-Z0-9_]*(:[A-Za-z0-9_]+)*$")
_CODE_RE = IDENTIFIER_PATTERNS[IdentifierScheme.JQUANTS_CODE]


class ResultSetError(ValueError):
    def __init__(self, code: str, detail: str = "") -> None:
        super().__init__(f"{code}: {detail}" if detail else code)
        self.code = code
        self.detail = detail


def _require(condition: bool, code: str, detail: str = "") -> None:
    if not condition:
        raise ResultSetError(code, detail)


class MemberOutcomeKind(str, Enum):
    """Universe の member（provider の上場物 code）ごとの閉じた結果。"""

    EVALUATED = "EVALUATED"                          # 発行体に解け、発行体の評価に結び付いた
    NOT_ELIGIBLE = "NOT_ELIGIBLE"                    # D0 の master で適格でない（凍結 LIVE1 の理由）
    IDENTITY_UNRESOLVED = "IDENTITY_UNRESOLVED"      # 審査済みの identity に解けない
    ACQUISITION_FAILED = "ACQUISITION_FAILED"        # 取得 ・authority の構築が終端で失敗した
    BUDGET_DEFERRED = "BUDGET_DEFERRED"              # 予算のため後の batch に延ばした（未終端）
    NOT_ATTEMPTED = "NOT_ATTEMPTED"                  # まだ試みていない（未終端）


class ExecutionCompleteness(str, Enum):
    COMPLETE = "COMPLETE"
    PARTIAL = "PARTIAL"


#: 実行として終端の member の結果（財務の結果とは別）
TERMINAL_MEMBER_OUTCOMES: Tuple[MemberOutcomeKind, ...] = (MemberOutcomeKind.EVALUATED, MemberOutcomeKind.NOT_ELIGIBLE,
                                                           MemberOutcomeKind.IDENTITY_UNRESOLVED,
                                                           MemberOutcomeKind.ACQUISITION_FAILED)


def _reason_codes(value: Any) -> Tuple[str, ...]:
    _require(isinstance(value, tuple) and all(isinstance(c, str) and bool(_REASON_CODE_RE.match(c)) for c in value),
             "INVALID_REASON_CODES", "reason_codes")
    _require(list(value) == sorted(set(value)), "REASON_CODES_NOT_CANONICAL", "reason_codes")
    return value


@dataclass(frozen=True, kw_only=True)
class MemberOutcome:
    """1 つの Universe の member の結果。EVALUATED だけが発行体を参照し、他は Screener の状態を持たない（捏造しない）。"""

    member_code: str
    kind: MemberOutcomeKind
    issuer_id: Optional[str] = None
    reason_codes: Tuple[str, ...] = ()

    def __post_init__(self) -> None:
        _require(isinstance(self.member_code, str) and bool(_CODE_RE.match(self.member_code)), "INVALID_MEMBER_CODE",
                 "member_code")
        _require(isinstance(self.kind, MemberOutcomeKind), "INVALID_MEMBER_OUTCOME", "kind")
        _reason_codes(self.reason_codes)
        if self.kind is MemberOutcomeKind.EVALUATED:
            _require(is_issuer_id(self.issuer_id), "EVALUATED_REQUIRES_ISSUER", "issuer_id")
        else:
            _require(self.issuer_id is None, "ISSUER_ONLY_FOR_EVALUATED", "issuer_id")
            _require(len(self.reason_codes) >= 1, "NON_EVALUATED_REQUIRES_REASON", "reason_codes")

    def as_dict(self) -> Dict[str, Any]:
        return {"issuer_id": self.issuer_id, "kind": self.kind.value, "member_code": self.member_code,
                "reason_codes": list(self.reason_codes)}


@dataclass(frozen=True, kw_only=True)
class IssuerResult:
    """審査済みの発行体ごとの 1 つの評価（凍結 B4A の投影を合成）。参照元の member は全結果の集合から派生する。"""

    issuer_id: str
    evaluation: SafeScreenerSummary

    def __post_init__(self) -> None:
        _require(is_issuer_id(self.issuer_id), "INVALID_ISSUER", "issuer_id")
        _require(isinstance(self.evaluation, SafeScreenerSummary), "INVALID_EVALUATION", "evaluation")

    @property
    def state(self) -> ScreenerState:
        return self.evaluation.state

    @property
    def completeness(self) -> DataCompleteness:
        return self.evaluation.completeness

    def as_dict(self) -> Dict[str, Any]:
        return {"evaluation": self.evaluation.as_dict(), "issuer_id": self.issuer_id}


# ---------------------------------------------------------------- 全結果の集合


@dataclass(frozen=True, kw_only=True)
class ScreenResultSet:
    """1 つの Universe × 1 つの方針 × 1 つの authority mode × 1 つの評価の瞬間（D0 の中）の型つきの全結果。保存しない。"""

    universe_id: str
    universe_version: int
    universe_members: Tuple[str, ...]
    policy_id: str
    policy_version: int
    authority_mode: ScreenerAuthorityMode
    authority_day: date
    evaluation_as_of: datetime
    member_outcomes: Tuple[MemberOutcome, ...]
    issuer_results: Tuple[IssuerResult, ...]
    rules_version: str = RESULT_SET_RULES_VERSION
    authority_class: str = DERIVED_NON_AUTHORITY_NON_PERSISTENT

    def __post_init__(self) -> None:
        _require(isinstance(self.universe_id, str) and bool(_UNIVERSE_ID_RE.match(self.universe_id)),
                 "INVALID_UNIVERSE_ID", "universe_id")
        _require(type(self.universe_version) is int and self.universe_version >= 1, "INVALID_VERSION",
                 "universe_version")
        _require(isinstance(self.universe_members, tuple) and len(self.universe_members) >= 1, "EMPTY_UNIVERSE",
                 "universe_members")
        _require(all(isinstance(c, str) and bool(_CODE_RE.match(c)) for c in self.universe_members),
                 "INVALID_MEMBER_CODE", "universe_members")
        _require(len(set(self.universe_members)) == len(self.universe_members), "DUPLICATE_UNIVERSE_MEMBER",
                 "universe_members")
        _require(isinstance(self.policy_id, str) and bool(_POLICY_ID_RE.match(self.policy_id)), "INVALID_POLICY_ID",
                 "policy_id")
        _require(type(self.policy_version) is int and self.policy_version >= 1, "INVALID_VERSION", "policy_version")
        _require(isinstance(self.authority_mode, ScreenerAuthorityMode), "INVALID_AUTHORITY_MODE", "authority_mode")
        _require(type(self.authority_day) is date, "INVALID_AUTHORITY_DAY", "authority_day")
        _require(isinstance(self.evaluation_as_of, datetime) and self.evaluation_as_of.tzinfo is not None
                 and self.evaluation_as_of.tzinfo.utcoffset(self.evaluation_as_of) is not None,
                 "NAIVE_OR_MISSING_DATETIME", "evaluation_as_of")
        start = day_start_jst(self.authority_day)
        _require(start <= self.evaluation_as_of < start + timedelta(days=1), "EVALUATION_OUTSIDE_AUTHORITY_DAY",
                 "evaluation_as_of")                                             # 単一の authority の日（JST の D0）
        _require(self.rules_version == RESULT_SET_RULES_VERSION, "RULES_VERSION_MISMATCH", "rules_version")
        _require(self.authority_class == DERIVED_NON_AUTHORITY_NON_PERSISTENT, "AUTHORITY_CLASS_MISMATCH",
                 "authority_class")
        self._check_members()
        self._check_issuers()

    def _check_members(self) -> None:
        _require(isinstance(self.member_outcomes, tuple)
                 and all(isinstance(m, MemberOutcome) for m in self.member_outcomes), "INVALID_MEMBER_OUTCOMES",
                 "member_outcomes")
        codes = [m.member_code for m in self.member_outcomes]
        _require(len(set(codes)) == len(codes), "DUPLICATE_MEMBER_OUTCOME", "member_outcomes")
        _require(not set(codes) - set(self.universe_members), "EXTRA_MEMBER_OUTCOME", "member_outcomes")
        _require(not set(self.universe_members) - set(codes), "MISSING_MEMBER_OUTCOME", "member_outcomes")
        _require(tuple(codes) == self.universe_members, "MEMBER_ORDER_NOT_DECLARED_ORDER", "member_outcomes")

    def _check_issuers(self) -> None:
        _require(isinstance(self.issuer_results, tuple)
                 and all(isinstance(r, IssuerResult) for r in self.issuer_results), "INVALID_ISSUER_RESULTS",
                 "issuer_results")
        ids = [r.issuer_id for r in self.issuer_results]
        _require(len(set(ids)) == len(ids), "DUPLICATE_ISSUER_RESULT", "issuer_results")
        referenced = [m.issuer_id for m in self.member_outcomes if m.kind is MemberOutcomeKind.EVALUATED]
        _require(not set(referenced) - set(ids), "EVALUATED_MEMBER_WITHOUT_ISSUER_RESULT", "member_outcomes")
        _require(not set(ids) - set(referenced), "ORPHAN_ISSUER_RESULT", "issuer_results")
        expected_order = list(dict.fromkeys(referenced))                         # 最初に参照する member の宣言の位置の順
        _require(ids == expected_order, "ISSUER_ORDER_NOT_FIRST_MEMBER_ORDER", "issuer_results")
        for result in self.issuer_results:
            evaluation = result.evaluation
            _require(evaluation.policy_ref == self.policy_id and evaluation.policy_version == self.policy_version,
                     "POLICY_MISMATCH", result.issuer_id)
            _require(evaluation.authority_mode is self.authority_mode, "AUTHORITY_MODE_MISMATCH", result.issuer_id)
            _require(evaluation.evaluation_as_of == self.evaluation_as_of, "EVALUATION_INSTANT_MISMATCH",
                     result.issuer_id)

    # ------------------------------------------------------------ 派生（保存しない）

    def source_members(self, issuer_id: str) -> Tuple[str, ...]:
        """発行体に解けた member の code（宣言の順。主の上場物は選ばない）。"""
        return tuple(m.member_code for m in self.member_outcomes
                     if m.kind is MemberOutcomeKind.EVALUATED and m.issuer_id == issuer_id)

    @property
    def execution_completeness(self) -> ExecutionCompleteness:
        terminal = all(m.kind in TERMINAL_MEMBER_OUTCOMES for m in self.member_outcomes)
        return ExecutionCompleteness.COMPLETE if terminal else ExecutionCompleteness.PARTIAL

    @property
    def member_outcome_counts(self) -> Dict[str, int]:
        counts = {kind.value: 0 for kind in MemberOutcomeKind}
        for outcome in self.member_outcomes:
            counts[outcome.kind.value] += 1
        return counts

    @property
    def screener_state_counts(self) -> Dict[str, int]:
        counts = {state.value: 0 for state in ScreenerState}
        for result in self.issuer_results:
            counts[result.state.value] += 1
        return counts

    @property
    def data_completeness_counts(self) -> Dict[str, int]:
        counts = {level.value: 0 for level in DataCompleteness}
        for result in self.issuer_results:
            counts[result.completeness.value] += 1
        return counts

    @property
    def match_issuer_ids(self) -> Tuple[str, ...]:
        """派生の MATCH の部分集合（発行体の結果の順。非意味。別の authority ・保存 ・順位は無い）。"""
        return tuple(r.issuer_id for r in self.issuer_results if r.state is ScreenerState.MATCH)

    def identity_payload(self) -> Dict[str, Any]:
        return {"authority_day": self.authority_day.isoformat(), "authority_mode": self.authority_mode.value,
                "evaluation_as_of": to_utc_iso(self.evaluation_as_of),
                "issuer_results": [r.as_dict() for r in self.issuer_results],
                "member_outcomes": [m.as_dict() for m in self.member_outcomes], "policy_id": self.policy_id,
                "policy_version": self.policy_version, "rules_version": self.rules_version,
                "schema_version": RESULT_SET_SCHEMA_VERSION, "universe_id": self.universe_id,
                "universe_members": list(self.universe_members), "universe_version": self.universe_version}

    @property
    def screen_result_id(self) -> str:
        """決定論の参照（同じ入力 ・同じ結果 ＝ 同じ id）。時計なし ・保存しない。P9 が正確な結果を参照するため。"""
        return content_id(RESULT_SET_ID_PREFIX, canonical_json(self.identity_payload()))

    def as_dict(self) -> Dict[str, Any]:
        """private の全結果（発行体の id ・member の code を含む。公開しない）。"""
        return {**self.identity_payload(), "authority_class": self.authority_class,
                "data_completeness_counts": self.data_completeness_counts,
                "execution_completeness": self.execution_completeness.value,
                "match_issuer_ids": list(self.match_issuer_ids), "match_subset_meaning": MATCH_SUBSET_MEANING,
                "member_outcome_counts": self.member_outcome_counts, "screen_result_id": self.screen_result_id,
                "screener_state_counts": self.screener_state_counts}


def assemble_result_set(*, universe_id: str, universe_version: int, universe_members: Sequence[str], policy_id: str,
                        policy_version: int, authority_mode: ScreenerAuthorityMode, authority_day: date,
                        evaluation_as_of: datetime, member_outcomes: Mapping[str, MemberOutcome],
                        issuer_results: Sequence[IssuerResult]) -> ScreenResultSet:
    """決定論の順で組み立てる: member は Universe の宣言の順、発行体は最初に参照する member の位置の順。検査は全結果の集合が行う。"""
    _require(isinstance(member_outcomes, Mapping), "INVALID_MEMBER_OUTCOMES", "member_outcomes")
    members = tuple(universe_members)
    _require(set(member_outcomes) <= set(members), "EXTRA_MEMBER_OUTCOME", "member_outcomes")
    _require(set(members) <= set(member_outcomes), "MISSING_MEMBER_OUTCOME", "member_outcomes")
    ordered = tuple(member_outcomes[code] for code in members)
    _require(all(isinstance(o, MemberOutcome) and o.member_code == code for code, o in zip(members, ordered)),
             "MEMBER_OUTCOME_KEY_MISMATCH", "member_outcomes")
    by_issuer: Dict[str, IssuerResult] = {}
    for result in issuer_results:
        _require(isinstance(result, IssuerResult), "INVALID_ISSUER_RESULTS", "issuer_results")
        _require(result.issuer_id not in by_issuer, "DUPLICATE_ISSUER_RESULT", "issuer_results")
        by_issuer[result.issuer_id] = result
    referenced = list(dict.fromkeys(o.issuer_id for o in ordered if o.kind is MemberOutcomeKind.EVALUATED))
    _require(not set(by_issuer) - set(referenced), "ORPHAN_ISSUER_RESULT", "issuer_results")
    _require(not set(referenced) - set(by_issuer), "EVALUATED_MEMBER_WITHOUT_ISSUER_RESULT", "member_outcomes")
    return ScreenResultSet(universe_id=universe_id, universe_version=universe_version, universe_members=members,
                           policy_id=policy_id, policy_version=policy_version, authority_mode=authority_mode,
                           authority_day=authority_day, evaluation_as_of=evaluation_as_of, member_outcomes=ordered,
                           issuer_results=tuple(by_issuer[i] for i in referenced))


__all__ = ["EXECUTION_COMPLETENESS_RULE", "ISSUER_ORDER_RULE", "MATCH_SUBSET_MEANING", "MEMBER_ORDER_RULE",
           "RESULT_SET_ID_PREFIX", "RESULT_SET_RULES_VERSION", "RESULT_SET_SCHEMA_VERSION",
           "TERMINAL_MEMBER_OUTCOMES", "ExecutionCompleteness", "IssuerResult", "MemberOutcome", "MemberOutcomeKind",
           "ResultSetError", "ScreenResultSet", "assemble_result_set"]
