"""Direction validator（Phase 3-C §14 / §36「USDJPY逆方向」）。

claim文中の**方向語**を統制語彙（lexicon）で読み、対応するContextの `direction`
と一致することを要求する。

- 方向語は**直前に出た主語**（無ければ直後の主語）に結び付ける（日本語の主題継続）
- 「上回る／下回る」はMA乖離（25日移動平均）または日経 vs TOPIXの相対比較に写像する
  （日経平均が主語なら OUTPERFORM/UNDERPERFORM を反転）
- 円安／円高は常にドル円、スティープ化／フラット化は常にスプレッドに写像する
- 対応するContextがpackageに無ければ direction_unsupported、向きが違えば
  direction_mismatch（いずれも error）
- OUTLOOK claimは見通し語彙（outlook.BIAS_LEXICON）とoutlook.directionを照合する
"""
from __future__ import annotations

from typing import FrozenSet, List, Optional, Sequence, Tuple

from ..context.builders import (
    CURVE_SHAPE,
    FX_DIRECTION,
    INDEX_DIRECTION,
    NIKKEI,
    NT_RATIO_STATE,
    RATE_DIRECTION,
    RELATIVE_PERFORMANCE,
    TOPIX,
    TREND_VS_MA,
)
from ..context.model import ContextItem, Direction
from .evidence_package import EvidencePackage
from .lexicon import (
    CURVE_FROM_LEVEL,
    CURVE_KEY,
    DIRECTION_GROUPS,
    DIRECTION_PATTERN,
    FX_FROM_LEVEL,
    FX_KEY,
    KEY_SUBJECT,
    MA_KEY,
    NIKKEI_KEY,
    NT_KEY,
    SUBJECT_PATTERN,
    TOPIX_KEY,
)
from .model import (
    SEVERITY_ERROR,
    ClaimRole,
    CompassClaim,
    CompassOutlook,
    ValidationIssue,
)
from .outlook import asserted_bias

VALIDATOR = "direction"

_CHECKED_ROLES = (ClaimRole.HEADLINE, ClaimRole.WHAT_HAPPENED, ClaimRole.WHY,
                  ClaimRole.RISK)
_KEY_CONTEXT_TYPE = {
    TOPIX_KEY: INDEX_DIRECTION, NIKKEI_KEY: INDEX_DIRECTION, NT_KEY: NT_RATIO_STATE,
    CURVE_KEY: CURVE_SHAPE, "jgb10y": RATE_DIRECTION, "ust10y": RATE_DIRECTION,
    "ust2y": RATE_DIRECTION, FX_KEY: FX_DIRECTION,
}
_INVERT = {Direction.OUTPERFORM: Direction.UNDERPERFORM,
           Direction.UNDERPERFORM: Direction.OUTPERFORM}


def _issue(claim: CompassClaim, code: str, message: str) -> ValidationIssue:
    return ValidationIssue(validator=VALIDATOR, code=code, message=message,
                           severity=SEVERITY_ERROR, claim_id=claim.claim_id)


def _mentions(text: str) -> List[Tuple[int, str]]:
    out: List[Tuple[int, str]] = []
    for m in SUBJECT_PATTERN.finditer(text):
        out.append((m.start(), m.lastgroup or ""))
    return out


def _directions(text: str) -> List[Tuple[int, str, FrozenSet[Direction]]]:
    out = []
    for m in DIRECTION_PATTERN.finditer(text):
        kind, dirs = DIRECTION_GROUPS[m.lastgroup or ""]
        out.append((m.start(), kind, dirs))
    return out


def _nearest_subject(pos: int, mentions: Sequence[Tuple[int, str]]) -> Optional[str]:
    before = [(p, k) for p, k in mentions if p < pos]
    if before:
        return before[-1][1]
    after = [(p, k) for p, k in mentions if p > pos]
    return after[0][1] if after else None


def _contexts(package: EvidencePackage, claim: CompassClaim, context_type: str,
              subject_id: str) -> List[ContextItem]:
    """引用Contextを優先し、無ければpackage内の最新Contextを候補にする。"""
    cited = [package.context(c) for c in claim.supporting_context_ids]
    hits = [c for c in cited if c is not None and c.context_type == context_type
            and c.subject.subject_id == subject_id]
    if hits:
        return hits
    latest = package.context_for(context_type, subject_id)
    return [latest] if latest is not None else []


def _relative_target(pos: int, mentions: Sequence[Tuple[int, str]]
                     ) -> Tuple[str, str, bool]:
    """上回る/下回る → (context_type, subject_id, invert)。"""
    before = [k for p, k in mentions if p < pos]
    index_key = TOPIX_KEY
    for key in reversed(before):
        if key in (TOPIX_KEY, NIKKEI_KEY):
            index_key = key
            break
    if MA_KEY in before:
        return TREND_VS_MA, KEY_SUBJECT[index_key], False
    if TOPIX_KEY in before and NIKKEI_KEY in before:
        first = next(k for k in before if k in (TOPIX_KEY, NIKKEI_KEY))
        return RELATIVE_PERFORMANCE, f"{NIKKEI}|{TOPIX}", first == NIKKEI_KEY
    return "", KEY_SUBJECT.get(index_key, TOPIX), False


def _check_sentence(claim: CompassClaim, sentence: str, package: EvidencePackage
                    ) -> List[ValidationIssue]:
    issues: List[ValidationIssue] = []
    mentions = _mentions(sentence)
    for pos, kind, dirs in _directions(sentence):
        candidates: List[ContextItem] = []
        expected: FrozenSet[Direction] = dirs
        label = ""
        if kind == "fx":
            candidates = _contexts(package, claim, FX_DIRECTION, KEY_SUBJECT[FX_KEY])
            label = "ドル円"
        elif kind == "curve":
            subject = _nearest_subject(pos, mentions)
            if subject != CURVE_KEY and dirs & {Direction.STEEPENING,
                                                Direction.FLATTENING} and \
                    sentence[pos:pos + 2] in ("拡大", "縮小"):
                continue                # 「拡大／縮小」はスプレッド以外では方向語にしない
            candidates = _contexts(package, claim, CURVE_SHAPE, KEY_SUBJECT[CURVE_KEY])
            label = "米10年-2年スプレッド"
        elif kind == "relative":
            ctype, subject_id, invert = _relative_target(pos, mentions)
            if not ctype:
                for ctype_try in (TREND_VS_MA, RELATIVE_PERFORMANCE):
                    sid = subject_id if ctype_try == TREND_VS_MA else f"{NIKKEI}|{TOPIX}"
                    candidates = _contexts(package, claim, ctype_try, sid)
                    if candidates:
                        ctype = ctype_try
                        break
            else:
                candidates = _contexts(package, claim, ctype, subject_id)
            if invert:
                expected = frozenset(_INVERT.get(d, d) for d in dirs)
            label = "相対比較/MA乖離"
        else:                                   # level（上昇／下落／横ばい）
            subject = _nearest_subject(pos, mentions)
            if subject is None:
                continue                        # 主語の無い方向語は検査対象外
            if subject == MA_KEY:
                issues.append(_issue(claim, "direction_unsupported",
                                     "移動平均そのものの方向はContextに無い"))
                continue
            if subject == FX_KEY:
                expected = frozenset(FX_FROM_LEVEL[d] for d in dirs if d in FX_FROM_LEVEL)
            elif subject == CURVE_KEY:
                expected = frozenset(CURVE_FROM_LEVEL[d] for d in dirs
                                     if d in CURVE_FROM_LEVEL)
            candidates = _contexts(package, claim, _KEY_CONTEXT_TYPE[subject],
                                   KEY_SUBJECT[subject])
            label = subject
        if not candidates:
            issues.append(_issue(claim, "direction_unsupported",
                                 f"{label}の方向を裏付けるContextがpackageに無い"))
            continue
        if not any(c.direction in expected for c in candidates):
            actual = ",".join(sorted({c.direction.value for c in candidates}))
            issues.append(_issue(claim, "direction_mismatch",
                                 f"{label}: 文は{'/'.join(sorted(d.value for d in expected))}"
                                 f"だがContextは{actual}"))
    return issues


def validate_direction(claim: CompassClaim, package: EvidencePackage,
                       outlook: Optional[CompassOutlook] = None) -> List[ValidationIssue]:
    if claim.claim_role is ClaimRole.OUTLOOK:
        if outlook is None:
            return [_issue(claim, "outlook_direction_unsupported", "outlookが無い")]
        bias = asserted_bias(claim.text)
        if bias is None:
            return [_issue(claim, "outlook_direction_unsupported",
                           "見通し語彙が無く方向を検証できない")]
        if bias is not outlook.direction:
            return [_issue(claim, "outlook_direction_mismatch",
                           f"文は{bias.value}だがoutlookは{outlook.direction.value}")]
        return []
    if claim.claim_role not in _CHECKED_ROLES:
        return []
    issues: List[ValidationIssue] = []
    for sentence in claim.text.split("。"):
        if sentence.strip():
            issues.extend(_check_sentence(claim, sentence, package))
    return issues
