"""Market Signal 射影（Phase 4 P4-2 v0.1.0）。

検証済みの `MorningBrief` **だけ**を入力に、見通しを 5 段階の方向シグナルへ
**決定論的に射影**する純関数。

    UPWARD_LEAN / SLIGHT_UPWARD_LEAN / NEUTRAL_RANGE /
    SLIGHT_DOWNWARD_LEAN / DOWNWARD_LEAN

規律（`docs/databank/MARKET_SIGNAL_SPEC.md` / `docs/databank/PHASE4_ENTRY_CONTRACT.md`）:
- **純関数**。入出力・永続化・data root・時刻・乱数・環境変数・外部サービスに触れない。
- **第二の分析器にしない**。材料を数え直さず、閾値を持たず、方向も確度も作らない。
  `compass.outlook` が決定済みの `direction` / `confidence` を写像するだけ。
- **quality gate を迂回しない**。入力は `MorningBrief` のみ。`CompassDraft` も
  `EvidencePackage` も raw claim も受け取らないため、gate 前の材料へ到達できない。
- **助言にしない**。売買・推奨・目標株価・期待リターン・確率を持たない。
  段階は方向の傾きの表現であり、投資スタンスではない。
- **fail closed**。写像に無い構造状態は、段階を作らず例外で止める。
- 顧客向け日本語は `SIGNAL_LEVEL_JA`（表示語彙）。model は日本語を持たない。
- Decision / formal_review / corpus / replay / shadow_review / evaluation と
  legacy / 外部記事基盤 / Phase 5 / 生成モデルは import しない。
- 依存は **MorningBrief → MarketSignal の一方向**。P4-1 側はこの module を参照しない。
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from enum import Enum
from typing import Dict, Mapping, Optional

from ..compass.model import Confidence, OutlookDirection, QualityVerdict
from ..core.ids import content_id
from .model import USABLE_VERDICTS, MorningBrief

MARKET_SIGNAL_SCHEMA_VERSION = "0.1.0"

#: 機械可読な unavailable 理由（顧客向け散文ではない）
R_DRAFT_NOT_USABLE = "draft_not_usable"
R_DRAFT_ABSTAINED = "draft_abstained"
R_TIER3_UNAVAILABLE = "tier3_unavailable"
R_NO_OUTLOOK = "no_outlook"
R_DIRECTION_MIXED = "direction_mixed"
R_DIRECTION_UNCERTAIN = "direction_uncertain"

#: unavailable 理由の形（P4-1 の表示側と同じ規約。自由文を持ち込まない）
_SAFE_REASON = re.compile(r"\A[a-z0-9_]{1,64}\Z")


class SignalLevel(str, Enum):
    """5 段階の方向シグナル（P4-2 §2）。

    投資スタンス語ではなく**相場の方向の傾き**を表す統制語彙。
    顧客へ出すのは `SIGNAL_LEVEL_JA` の日本語だけで、順序値は公開しない。
    """

    UPWARD_LEAN = "UPWARD_LEAN"
    SLIGHT_UPWARD_LEAN = "SLIGHT_UPWARD_LEAN"
    NEUTRAL_RANGE = "NEUTRAL_RANGE"
    SLIGHT_DOWNWARD_LEAN = "SLIGHT_DOWNWARD_LEAN"
    DOWNWARD_LEAN = "DOWNWARD_LEAN"


#: 顧客向け日本語ラベル（表示語彙。`SignalLevel` の全値を明示的に持つ）
SIGNAL_LEVEL_JA: Dict[str, str] = {
    SignalLevel.UPWARD_LEAN.value: "上昇寄り",
    SignalLevel.SLIGHT_UPWARD_LEAN.value: "やや上昇寄り",
    SignalLevel.NEUTRAL_RANGE.value: "中立（レンジ）",
    SignalLevel.SLIGHT_DOWNWARD_LEAN.value: "やや下落寄り",
    SignalLevel.DOWNWARD_LEAN.value: "下落寄り",
}

#: (outlook direction, confidence) → 段階。**承認済みの組み合わせだけ**を持つ。
#: HIGH と MEDIUM を同じ段階へ畳むのは 5 段階という制約のためで、
#: 失われる区別は `MarketSignal.confidence` が構造として保持する。
LEVEL_BY_STATE: Dict[tuple, SignalLevel] = {
    (OutlookDirection.UPWARD_BIAS.value, Confidence.HIGH.value): SignalLevel.UPWARD_LEAN,
    (OutlookDirection.UPWARD_BIAS.value, Confidence.MEDIUM.value): SignalLevel.UPWARD_LEAN,
    (OutlookDirection.UPWARD_BIAS.value, Confidence.LOW.value): SignalLevel.SLIGHT_UPWARD_LEAN,
    (OutlookDirection.DOWNWARD_BIAS.value, Confidence.HIGH.value): SignalLevel.DOWNWARD_LEAN,
    (OutlookDirection.DOWNWARD_BIAS.value, Confidence.MEDIUM.value): SignalLevel.DOWNWARD_LEAN,
    (OutlookDirection.DOWNWARD_BIAS.value, Confidence.LOW.value): SignalLevel.SLIGHT_DOWNWARD_LEAN,
    (OutlookDirection.RANGE_BOUND.value, Confidence.LOW.value): SignalLevel.NEUTRAL_RANGE,
}

#: 段階を作らない方向（**確度に依存しない**）。
#: 「強弱が拮抗している」「判断材料が無い」を「中立」と表示しないための分岐であり、
#: 将来 confidence が変わっても unavailable のまま安全に落ちる。
UNAVAILABLE_BY_DIRECTION: Dict[str, str] = {
    OutlookDirection.MIXED.value: R_DIRECTION_MIXED,
    OutlookDirection.UNCERTAIN.value: R_DIRECTION_UNCERTAIN,
}

_KNOWN_DIRECTIONS = frozenset(d.value for d in OutlookDirection)
_KNOWN_CONFIDENCES = frozenset(c.value for c in Confidence)


class UnmappedSignalState(KeyError):
    """写像を持たない構造状態（fail closed）。

    段階を作ることも、代替ラベルを当てることもしない。
    """


@dataclass(frozen=True, kw_only=True)
class MarketSignal:
    """session 単位の方向シグナル。`signal_id` は内容アドレス（同じ射影→同じ ID）。"""

    signal_id: str
    session_date: str
    reference_session: str
    available: bool
    level: Optional[SignalLevel] = None
    confidence: str = ""
    horizon: str = ""
    brief_id: str = ""
    unavailable_reason: str = ""
    schema_version: str = MARKET_SIGNAL_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if not self.signal_id or not self.session_date:
            raise ValueError("MarketSignal requires signal_id and session_date")
        if not self.brief_id:
            raise ValueError("MarketSignal requires brief_id")
        if self.available:
            if self.level is None:
                raise UnmappedSignalState("available signal without level")
            if self.unavailable_reason:
                raise UnmappedSignalState("available signal with unavailable_reason")
        else:
            if self.level is not None:
                raise UnmappedSignalState("unavailable signal with level")
            if not _SAFE_REASON.match(self.unavailable_reason):
                raise UnmappedSignalState("unavailable signal without machine-readable reason")

    @property
    def label(self) -> str:
        """顧客向け日本語ラベル。段階が無い日は空（散文を作らない）。"""
        return "" if self.level is None else signal_label(self.level)

    def as_dict(self) -> Dict[str, object]:
        return {"signal_id": self.signal_id, **signal_payload(
            schema_version=self.schema_version, session_date=self.session_date,
            reference_session=self.reference_session, available=self.available,
            level=self.level, confidence=self.confidence, horizon=self.horizon,
            brief_id=self.brief_id, unavailable_reason=self.unavailable_reason)}


def signal_label(level: SignalLevel) -> str:
    """段階 → 顧客向け日本語。対応表に無い値は生値も代替語も出さない。"""
    try:
        return SIGNAL_LEVEL_JA[level.value if isinstance(level, SignalLevel) else str(level)]
    except KeyError:
        raise UnmappedSignalState(f"signal level has no customer label: {level!r}") from None


def signal_payload(*, schema_version: str, session_date: str, reference_session: str,
                   available: bool, level: Optional[SignalLevel], confidence: str,
                   horizon: str, brief_id: str, unavailable_reason: str) -> Dict[str, object]:
    """`signal_id` の材料であり、`as_dict()` の本体でもある正規化 payload。

    日本語ラベルは含めない（表示語彙を変えても ID が動かないようにする）。
    """
    return {
        "schema_version": schema_version,
        "session_date": session_date,
        "reference_session": reference_session,
        "available": available,
        "level": "" if level is None else level.value,
        "confidence": confidence,
        "horizon": horizon,
        "brief_id": brief_id,
        "unavailable_reason": unavailable_reason,
    }


def canonical_signal(payload: Mapping[str, object]) -> str:
    """決定論的な正規化文字列（key 順固定・空白なし）。時刻も path も含めない。"""
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def make_signal_id(payload: Mapping[str, object]) -> str:
    """**決定論的**な signal_id。同じ射影 → 同じ ID、違えば別 ID。"""
    return content_id("signal", canonical_signal(payload))


def _safe_reason(candidate: str, fallback: str) -> str:
    """機械可読な理由だけを引き継ぐ（自由文・内部語彙を顧客側へ運ばない）。"""
    return candidate if _SAFE_REASON.match(candidate or "") else fallback


def _build(*, brief: MorningBrief, available: bool, level: Optional[SignalLevel],
           confidence: str, horizon: str, reason: str) -> MarketSignal:
    payload = signal_payload(
        schema_version=MARKET_SIGNAL_SCHEMA_VERSION,
        session_date=brief.session_date, reference_session=brief.reference_session,
        available=available, level=level, confidence=confidence, horizon=horizon,
        brief_id=brief.brief_id, unavailable_reason=reason)
    return MarketSignal(
        signal_id=make_signal_id(payload), session_date=brief.session_date,
        reference_session=brief.reference_session, available=available, level=level,
        confidence=confidence, horizon=horizon, brief_id=brief.brief_id,
        unavailable_reason=reason, schema_version=MARKET_SIGNAL_SCHEMA_VERSION)


def build_market_signal(brief: MorningBrief) -> MarketSignal:
    """検証済み `MorningBrief` → Market Signal（純関数・決定論的・冪等）。

    段階は `brief.tier3.outlook` の direction / confidence だけから決まる。
    欠落次元・不確かな次元は **ここで再度減点しない**——Compass / MorningBrief が
    既に confidence と availability へ反映済みであり、二重計上になるため。
    """
    if brief.verdict not in USABLE_VERDICTS:
        fallback = (R_DRAFT_ABSTAINED if brief.verdict is QualityVerdict.ABSTAINED
                    else R_DRAFT_NOT_USABLE)
        return _build(brief=brief, available=False, level=None, confidence="", horizon="",
                      reason=_safe_reason(brief.abstain_reason, fallback))

    tier3 = brief.tier3
    if not tier3.available:
        return _build(brief=brief, available=False, level=None, confidence="", horizon="",
                      reason=_safe_reason(tier3.unavailable_reason, R_TIER3_UNAVAILABLE))

    outlook = tier3.outlook
    if outlook is None:
        return _build(brief=brief, available=False, level=None, confidence="", horizon="",
                      reason=R_NO_OUTLOOK)

    direction, confidence = outlook.direction, outlook.confidence
    if direction not in _KNOWN_DIRECTIONS:
        raise UnmappedSignalState(f"unknown outlook direction: {direction!r}")
    if confidence not in _KNOWN_CONFIDENCES:
        raise UnmappedSignalState(f"unknown outlook confidence: {confidence!r}")

    # 方向だけで決まる unavailable を、確度を見る前に確定させる
    reason = UNAVAILABLE_BY_DIRECTION.get(direction)
    if reason is not None:
        return _build(brief=brief, available=False, level=None, confidence=confidence,
                      horizon=outlook.horizon, reason=reason)

    try:
        level = LEVEL_BY_STATE[(direction, confidence)]
    except KeyError:
        raise UnmappedSignalState(
            f"no approved signal level for state: {(direction, confidence)!r}") from None
    return _build(brief=brief, available=True, level=level, confidence=confidence,
                  horizon=outlook.horizon, reason="")
