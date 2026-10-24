"""EvaluationRecord — Phase 5 P5-2A（不変の評価記録・決定論的 identity・realized outcome 契約）。

PredictionRecord が「予測時に系が何と言ったか」であるのに対し、EvaluationRecord は
「その不変の予測について、特定の検証済み outcome / 証拠 context のもとで**後から**どんな評価が
なされたか」を表す**別の不変の事実**である。outcome が届いても PredictionRecord は変更しない。
EvaluationRecord は `prediction_id` で予測を参照し、PredictionRecord を複製しない。

本 module が凍結するのは **object だけ**である（`docs/databank/PHASE5_ENTRY_CONTRACT.md` §14）:
schema / identity / realized return の表現 / 分類 / EVALUATED・DEFERRED の状態機械 / defer 理由 /
session 検証の証拠 / provenance / supersession。TOPIX の取得・取引カレンダー照会・return の計算・
自動評価・store・較正・正誤判定・runtime 統合は**含まない**（P5-2B 以降）。

契約（凍結 N-2 / N-4 / N-5）:

- target は TOPIX（`index:topix.close.closing.tokyo`）のみ。
- horizon は「`reference_session` の TOPIX close → `session_date` の TOPIX close」の
  **1 検証済み東京取引 session** close-to-close。open-to-close・intraday・翌々 session・
  暦日 return・weekday 演算 fallback は表現しない。
- realized_return = `close(session_date) / close(reference_session) − 1`。**Decimal**・分類前に
  丸めない・float 不可。連続値を必ず保存する（UP / RANGE / DOWN だけを保存しない）。
- 分類 `topix_neutral_band:1.0.0`: `UP: r > +0.003` / `RANGE: −0.003 <= r <= +0.003`（閉区間）/
  `DOWN: r < −0.003`。比較は Decimal。N-2 の表で「NEUTRAL_RANGE」と書かれた realized の区分は
  記録上 `RANGE` で表す（予測 level の `NEUTRAL_RANGE` と語彙を分ける。境界は不変）。
- **予測 level（5 値）と realized outcome（3 値）は別概念。** 正誤・hit / miss・accuracy・
  score・direction_correct は本 record に存在しない（後続の較正 gate が定義する）。
- EVALUATED = 必要な検証済み outcome 証拠がすべて揃い、連続 realized_return ＋ 分類を表現できる。
  DEFERRED = 予測は存在するが、評価契約のもとで権威ある評価を現時点で完了できない。
  DEFERRED は RANGE でも不正解でも零 return でも「予測が unavailable」でもない。
- 予測の availability と outcome の evaluability は別。unavailable な予測も TOPIX の outcome を
  持ちうる。棄権を理由に DEFERRED にしない。棄権の正誤も決めない。
- session の証拠（§10）: EVALUATED には `SessionVerification`（既存 `CalendarValidation` と同じ
  実測検証の要約 ＋ 検証済み session / 直前 session）が必須で、`verified_session == session_date`
  かつ `verified_previous_session == reference_session`。関係を立証できなければ DEFERRED。
- 訂正（§14）: 歴史的 EvaluationRecord は書き換えない。市場データが訂正されたら
  `supersedes_evaluation_id` で前の評価を参照する**新しい** EvaluationRecord を作る。
  in-place 変更・「最新が勝つ」・chain 走査は本 module に無い（自己 supersession だけ拒否）。
- `created_at` は評価時刻の audit metadata であり identity に入らない。module 内で
  `datetime.now()` を呼ばない（呼び出し側が明示する）。

Decimal の canonical 直列化（§17）: `canonical_decimal()` は context に依存せず
`as_tuple()` から末尾ゼロだけを落として指数なしの平文十進で表す。`0.01` と `0.0100` は同じ
文字列、`-0` は `0`、`1E-7` は `0.0000001`、NaN / Infinity / float は拒否、桁は落とさない。
`from_dict` は canonical でない文字列を拒否する（strict boundary）。

field 分類（§13）:

    A. SEMANTIC_IDENTITY_INPUT … schema_version / prediction_id / target / reference_session /
       session_date / classification_version / status / realized_return / realized_outcome /
       defer_reason / supersedes_evaluation_id
    B. PROVENANCE（hash 外）   … reference_close / target_close / reference_observation_id /
       target_observation_id / source_id / market_schema_version / session_verification
    C. AUDIT（hash 外）        … created_at
    D. DERIVED（保存しない）    … identity payload / canonical 文字列 / is_deferred / is_correction
    E. FORBIDDEN               … hit / miss / correct / accuracy / score / win / loss /
       direction_correct / 予測 level・confidence の複製 / label / display_text / delivery_id /
       Markdown / HTML / path

`supersedes_evaluation_id` を identity に含める理由: 訂正は「別の評価事象」であり、同じ数値に
再評価されても訂正 record は必ず新しい evaluation_id を得なければならない（§14）。参照は
`Observation.revision_of` と同じ provenance link であり、新しい hash chain ではない（N-3）。
"""
from __future__ import annotations

import json
from dataclasses import dataclass, fields
from datetime import date, datetime
from decimal import Decimal
from enum import Enum
from string import hexdigits
from typing import Dict, Mapping, Optional, Tuple

from ..core.ids import content_id
from ..core.time import ensure_aware, from_iso, to_utc_iso
from .prediction_record import PREDICTION_ID_PREFIX

#: EvaluationRecord 自身の schema 版（prediction_record:0.1.0 とも topix_neutral_band:1.0.0 とも別）
EVALUATION_RECORD_SCHEMA_VERSION = "evaluation_record:0.1.0"
EVALUATION_ID_PREFIX = "eval"

#: 凍結 N-2（realized outcome 分類規則の版。閾値と return 定義を含む）
NEUTRAL_BAND_RULE_VERSION = "topix_neutral_band:1.0.0"
SUPPORTED_CLASSIFICATION_VERSIONS: Tuple[str, ...] = (NEUTRAL_BAND_RULE_VERSION,)
NEUTRAL_BAND = Decimal("0.003")               # ±0.30%（fraction）
RETURN_DEFINITION = "close(session_date) / close(reference_session) - 1"

#: 凍結 N-4（target）
TARGET_TOPIX = "index:topix.close.closing.tokyo"
SUPPORTED_TARGETS: Tuple[str, ...] = (TARGET_TOPIX,)

#: content ID の hex 長（`core.ids.content_id`）
_ID_HEX_LENGTH = 24

#: canonical identity payload の key（**この 11 個だけ**。昇順に直列化される）
IDENTITY_KEYS: Tuple[str, ...] = (
    "classification_version", "defer_reason", "prediction_id", "realized_outcome",
    "realized_return", "reference_session", "schema_version", "session_date", "status",
    "supersedes_evaluation_id", "target",
)


class EvaluationStatus(str, Enum):
    EVALUATED = "EVALUATED"
    DEFERRED = "DEFERRED"


class RealizedOutcome(str, Enum):
    """realized outcome の 3 値。予測 level（5 値）とは別語彙。"""

    UP = "UP"
    RANGE = "RANGE"
    DOWN = "DOWN"


class DeferReason(str, Enum):
    """権威ある評価を完了できない理由（fail closed の語彙。後続 evaluator が記録に使う）。"""

    CALENDAR_UNVERIFIED = "calendar_unverified"                  # 取引カレンダーを検証できない
    REFERENCE_SESSION_UNVERIFIED = "reference_session_unverified"  # 直前検証済み session 関係を立証できない
    REFERENCE_CLOSE_UNAVAILABLE = "reference_close_unavailable"  # reference_session の TOPIX close 無し
    TARGET_CLOSE_UNAVAILABLE = "target_close_unavailable"        # session_date の TOPIX close 無し
    OBSERVATION_INVALID = "observation_invalid"                  # 必要な市場観測が無効（欠測値・非正・失効等）
    SOURCE_UNSUPPORTED = "source_unsupported"                    # source データ / schema 版が未対応


class InvalidEvaluationRecord(ValueError):
    """凍結契約に反する状態（fail closed。正規化も推測も修復もしない）。"""


# ---------------------------------------------------------------- Decimal（§17）

def canonical_decimal(value: Decimal) -> str:
    """Decimal → 唯一の canonical 文字列（context 非依存・指数なし・末尾ゼロなし・`-0` は `0`）。

    float / int / str は受け取らない。NaN / sNaN / Infinity は拒否。桁を落とさない。
    """
    if not isinstance(value, Decimal):
        raise InvalidEvaluationRecord(f"Decimal required, got {type(value).__name__}")
    if value.is_nan() or value.is_infinite():
        raise InvalidEvaluationRecord("NaN / Infinity cannot be a realized value")
    sign, digits, exponent = value.as_tuple()
    digits = list(digits)
    while len(digits) > 1 and digits[-1] == 0:
        digits.pop()
        exponent += 1
    if digits == [0]:
        return "0"                                   # 零・負の零・0E-10 はすべて "0"
    body = "".join(str(d) for d in digits)
    if exponent >= 0:
        text = body + "0" * exponent
    else:
        point = len(body) + exponent
        text = (body[:point] + "." + body[point:]) if point > 0 else ("0." + "0" * (-point) + body)
    return ("-" if sign else "") + text


def parse_canonical_decimal(text: str, field_name: str) -> Decimal:
    """canonical 文字列だけを受理する strict parser（非 canonical は修復せず拒否）。"""
    if not isinstance(text, str) or text == "":
        raise InvalidEvaluationRecord(f"{field_name} must be a canonical decimal string")
    try:
        value = Decimal(text)
    except Exception:  # noqa: BLE001 - decimal.InvalidOperation and friends
        raise InvalidEvaluationRecord(f"{field_name} is not a decimal: {text!r}") from None
    if canonical_decimal(value) != text:
        raise InvalidEvaluationRecord(f"{field_name} is not in canonical form: {text!r}")
    return value


# ---------------------------------------------------------------- classification（N-2）

def classify_realized_return(realized_return: Decimal, *,
                             classification_version: str = NEUTRAL_BAND_RULE_VERSION,
                             ) -> RealizedOutcome:
    """`topix_neutral_band:1.0.0`: UP > +0.003 / RANGE −0.003..+0.003（閉区間）/ DOWN < −0.003。"""
    _require(classification_version in SUPPORTED_CLASSIFICATION_VERSIONS,
             f"unknown classification version: {classification_version!r}")
    canonical_decimal(realized_return)                # Decimal / 有限であることを強制
    if realized_return > NEUTRAL_BAND:
        return RealizedOutcome.UP
    if realized_return < -NEUTRAL_BAND:
        return RealizedOutcome.DOWN
    return RealizedOutcome.RANGE


# ---------------------------------------------------------------- session verification（§10）

@dataclass(frozen=True, kw_only=True)
class SessionVerification:
    """N-5 の session 証拠（既存 `tokyo_calendar.CalendarValidation` の実測検証の要約）。

    `validated` は CalendarValidation と同じ規則（1 件でも食い違えば未検証）。EVALUATED では
    `verified_session == session_date` と `verified_previous_session == reference_session` を要求する。
    """

    calendar_source_id: str
    trading_divisions: Tuple[str, ...]
    checked_dates: int
    agreements: int
    disagreement_count: int
    verified_session: str
    verified_previous_session: str

    def __post_init__(self) -> None:
        _require(isinstance(self.calendar_source_id, str), "calendar_source_id must be str")
        _require(isinstance(self.trading_divisions, tuple) and bool(self.trading_divisions)
                 and all(isinstance(d, str) and d for d in self.trading_divisions),
                 "trading_divisions must be a non-empty tuple of non-empty strings")
        for name in ("checked_dates", "agreements", "disagreement_count"):
            value = getattr(self, name)
            _require(isinstance(value, int) and not isinstance(value, bool) and value >= 0,
                     f"{name} must be a non-negative int")
        _require(self.agreements + self.disagreement_count <= self.checked_dates,
                 "agreements + disagreements cannot exceed checked_dates")
        for name in ("verified_session", "verified_previous_session"):
            value = getattr(self, name)
            _require(isinstance(value, str), f"{name} must be str")
            if value:
                _validate_iso_date(name, value)
        if self.verified_session and self.verified_previous_session:
            _require(self.verified_previous_session < self.verified_session,
                     "verified_previous_session must precede verified_session")

    @property
    def validated(self) -> bool:
        return (self.checked_dates > 0 and self.disagreement_count == 0
                and self.agreements == self.checked_dates and bool(self.calendar_source_id))

    def as_dict(self) -> Dict[str, object]:
        return {
            "calendar_source_id": self.calendar_source_id,
            "trading_divisions": list(self.trading_divisions),
            "checked_dates": self.checked_dates,
            "agreements": self.agreements,
            "disagreement_count": self.disagreement_count,
            "verified_session": self.verified_session,
            "verified_previous_session": self.verified_previous_session,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, object]) -> "SessionVerification":
        known = {f.name for f in fields(cls)}
        unknown = sorted(set(data) - known)
        _require(not unknown, f"unknown SessionVerification fields: {unknown}")
        _require(not (known - set(data)), f"missing SessionVerification fields: {sorted(known - set(data))}")
        divisions = data["trading_divisions"]
        _require(isinstance(divisions, (list, tuple)), "trading_divisions must be a list")
        return cls(
            calendar_source_id=data["calendar_source_id"],           # type: ignore[arg-type]
            trading_divisions=tuple(divisions),                      # type: ignore[arg-type]
            checked_dates=data["checked_dates"],                     # type: ignore[arg-type]
            agreements=data["agreements"],                           # type: ignore[arg-type]
            disagreement_count=data["disagreement_count"],           # type: ignore[arg-type]
            verified_session=data["verified_session"],               # type: ignore[arg-type]
            verified_previous_session=data["verified_previous_session"],  # type: ignore[arg-type]
        )


# ---------------------------------------------------------------- identity（§13）

def identity_payload(
    *, schema_version: str, prediction_id: str, target: str, reference_session: str,
    session_date: str, classification_version: str, status: EvaluationStatus,
    realized_return: Optional[Decimal], realized_outcome: Optional[RealizedOutcome],
    defer_reason: Optional[DeferReason], supersedes_evaluation_id: str,
) -> Dict[str, object]:
    """`evaluation_id` の材料となる**意味論だけ**の正規化 payload（欠落は空文字。JSON null 無し）。"""
    _require(isinstance(status, EvaluationStatus), "status must be EvaluationStatus")
    _require(realized_outcome is None or isinstance(realized_outcome, RealizedOutcome),
             "realized_outcome must be RealizedOutcome or None")
    _require(defer_reason is None or isinstance(defer_reason, DeferReason),
             "defer_reason must be DeferReason or None")
    return {
        "schema_version": schema_version,
        "prediction_id": prediction_id,
        "target": target,
        "reference_session": reference_session,
        "session_date": session_date,
        "classification_version": classification_version,
        "status": status.value,
        "realized_return": "" if realized_return is None else canonical_decimal(realized_return),
        "realized_outcome": "" if realized_outcome is None else realized_outcome.value,
        "defer_reason": "" if defer_reason is None else defer_reason.value,
        "supersedes_evaluation_id": supersedes_evaluation_id,
    }


def canonical_identity(payload: Mapping[str, object]) -> str:
    if tuple(sorted(payload)) != IDENTITY_KEYS:
        raise InvalidEvaluationRecord(f"identity payload keys drifted: {sorted(payload)!r}")
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def make_evaluation_id(payload: Mapping[str, object]) -> str:
    """`eval_` + SHA-256(canonical UTF-8)[:24]（`core.ids.content_id`。新しい hash chain ではない）。"""
    return content_id(EVALUATION_ID_PREFIX, canonical_identity(payload))


# ---------------------------------------------------------------- record

@dataclass(frozen=True, kw_only=True)
class EvaluationRecord:
    """1 件の不変の評価記録（field 分類は module docstring §13）。"""

    # -- A. identity / semantics
    schema_version: str = EVALUATION_RECORD_SCHEMA_VERSION
    evaluation_id: str
    prediction_id: str
    target: str = TARGET_TOPIX
    reference_session: str
    session_date: str
    classification_version: str = NEUTRAL_BAND_RULE_VERSION
    status: EvaluationStatus
    realized_return: Optional[Decimal] = None
    realized_outcome: Optional[RealizedOutcome] = None
    defer_reason: Optional[DeferReason] = None
    supersedes_evaluation_id: str = ""
    # -- B. provenance（identity に入らない）
    reference_close: Optional[Decimal] = None
    target_close: Optional[Decimal] = None
    reference_observation_id: str = ""
    target_observation_id: str = ""
    source_id: str = ""
    market_schema_version: str = ""
    session_verification: Optional[SessionVerification] = None
    # -- C. audit（identity に入らない）
    created_at: datetime

    # ------------------------------------------------------------ validation（fail closed）

    def __post_init__(self) -> None:
        _require(self.schema_version == EVALUATION_RECORD_SCHEMA_VERSION,
                 f"unsupported evaluation record schema: {self.schema_version!r}")
        _validate_content_id("prediction_id", self.prediction_id, PREDICTION_ID_PREFIX)
        _require(self.target in SUPPORTED_TARGETS, f"unsupported target: {self.target!r}")
        _validate_iso_date("session_date", self.session_date)
        _validate_iso_date("reference_session", self.reference_session)
        _require(self.reference_session < self.session_date,
                 "reference_session must precede session_date (schema-local ordering)")
        _require(self.classification_version in SUPPORTED_CLASSIFICATION_VERSIONS,
                 f"unknown classification version: {self.classification_version!r}")
        _require(isinstance(self.status, EvaluationStatus), "status must be EvaluationStatus")
        for name in ("realized_return", "reference_close", "target_close"):
            value = getattr(self, name)
            if value is not None:
                canonical_decimal(value)             # Decimal・有限（float は拒否）
        for name in ("reference_close", "target_close"):
            value = getattr(self, name)
            _require(value is None or value > 0, f"{name} must be positive when present")
        for name in ("reference_observation_id", "target_observation_id", "source_id",
                     "market_schema_version"):
            _require(isinstance(getattr(self, name), str), f"{name} must be str")
        _require(self.session_verification is None
                 or isinstance(self.session_verification, SessionVerification),
                 "session_verification must be SessionVerification or None")
        if self.status is EvaluationStatus.EVALUATED:
            self._validate_evaluated()
        else:
            self._validate_deferred()
        _require(isinstance(self.supersedes_evaluation_id, str), "supersedes_evaluation_id must be str")
        if self.supersedes_evaluation_id:
            _validate_content_id("supersedes_evaluation_id", self.supersedes_evaluation_id,
                                 EVALUATION_ID_PREFIX)
        ensure_aware(self.created_at, "EvaluationRecord.created_at")
        expected = make_evaluation_id(self.identity_payload())
        _require(self.evaluation_id == expected,
                 "evaluation_id does not match the semantic identity payload")
        _require(self.supersedes_evaluation_id != self.evaluation_id,
                 "an evaluation cannot supersede itself")

    def _validate_evaluated(self) -> None:
        _require(self.realized_return is not None, "EVALUATED requires realized_return")
        _require(self.realized_outcome is not None, "EVALUATED requires realized_outcome")
        _require(self.defer_reason is None, "EVALUATED must not carry a defer_reason")
        _require(isinstance(self.realized_outcome, RealizedOutcome),
                 "realized_outcome must be RealizedOutcome")
        expected = classify_realized_return(self.realized_return,
                                            classification_version=self.classification_version)
        _require(self.realized_outcome is expected,
                 f"realized_outcome {self.realized_outcome.value} contradicts realized_return "
                 f"{canonical_decimal(self.realized_return)} under {self.classification_version}")
        _require(self.reference_close is not None and self.target_close is not None,
                 "EVALUATED requires reference_close and target_close provenance")
        _require(self.session_verification is not None,
                 "EVALUATED requires session_verification evidence")
        proof = self.session_verification
        _require(proof.validated, "EVALUATED requires a validated trading calendar")
        _require(proof.verified_session == self.session_date,
                 "session_date is not the verified trading session")
        _require(proof.verified_previous_session == self.reference_session,
                 "reference_session is not the verified immediately previous trading session")

    def _validate_deferred(self) -> None:
        _require(self.realized_return is None, "DEFERRED must not carry realized_return")
        _require(self.realized_outcome is None, "DEFERRED must not carry realized_outcome")
        _require(isinstance(self.defer_reason, DeferReason), "DEFERRED requires a defer_reason")
        if self.defer_reason is DeferReason.REFERENCE_CLOSE_UNAVAILABLE:
            _require(self.reference_close is None, "reference_close_unavailable contradicts a reference_close")
        if self.defer_reason is DeferReason.TARGET_CLOSE_UNAVAILABLE:
            _require(self.target_close is None, "target_close_unavailable contradicts a target_close")
        if self.defer_reason is DeferReason.CALENDAR_UNVERIFIED:
            _require(self.session_verification is None or not self.session_verification.validated,
                     "calendar_unverified contradicts a validated session_verification")

    # ------------------------------------------------------------ derived（保存しない）

    def identity_payload(self) -> Dict[str, object]:
        return identity_payload(
            schema_version=self.schema_version, prediction_id=self.prediction_id,
            target=self.target, reference_session=self.reference_session,
            session_date=self.session_date, classification_version=self.classification_version,
            status=self.status, realized_return=self.realized_return,
            realized_outcome=self.realized_outcome, defer_reason=self.defer_reason,
            supersedes_evaluation_id=self.supersedes_evaluation_id)

    @property
    def canonical(self) -> str:
        return canonical_identity(self.identity_payload())

    @property
    def is_deferred(self) -> bool:
        return self.status is EvaluationStatus.DEFERRED

    @property
    def is_correction(self) -> bool:
        return bool(self.supersedes_evaluation_id)

    # ------------------------------------------------------------ serialization（round-trip）

    def as_dict(self) -> Dict[str, object]:
        """JSON 互換 dict（Decimal は canonical 文字列・欠落は None・表示文字列を含まない）。"""
        return {
            "schema_version": self.schema_version,
            "evaluation_id": self.evaluation_id,
            "prediction_id": self.prediction_id,
            "target": self.target,
            "reference_session": self.reference_session,
            "session_date": self.session_date,
            "classification_version": self.classification_version,
            "status": self.status.value,
            "realized_return": _opt_decimal(self.realized_return),
            "realized_outcome": None if self.realized_outcome is None else self.realized_outcome.value,
            "defer_reason": None if self.defer_reason is None else self.defer_reason.value,
            "supersedes_evaluation_id": self.supersedes_evaluation_id,
            "reference_close": _opt_decimal(self.reference_close),
            "target_close": _opt_decimal(self.target_close),
            "reference_observation_id": self.reference_observation_id,
            "target_observation_id": self.target_observation_id,
            "source_id": self.source_id,
            "market_schema_version": self.market_schema_version,
            "session_verification": (None if self.session_verification is None
                                     else self.session_verification.as_dict()),
            "created_at": to_utc_iso(self.created_at),
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, object]) -> "EvaluationRecord":
        """strict: 未知 field・非 canonical Decimal・欠落 key を拒否。migration / repair / 現在時刻注入なし。"""
        known = {f.name for f in fields(cls)}
        unknown = sorted(set(data) - known)
        _require(not unknown, f"unknown EvaluationRecord fields: {unknown}")
        missing = sorted(known - set(data))
        _require(not missing, f"missing EvaluationRecord fields: {missing}")

        def opt_decimal(name: str) -> Optional[Decimal]:
            value = data[name]
            return None if value is None else parse_canonical_decimal(value, name)  # type: ignore[arg-type]

        def opt_enum(name: str, enum_cls):
            value = data[name]
            if value is None:
                return None
            try:
                return enum_cls(value)
            except ValueError:
                raise InvalidEvaluationRecord(f"unknown {name}: {value!r}") from None

        status = opt_enum("status", EvaluationStatus)
        _require(status is not None, "status is required")
        verification = data["session_verification"]
        _require(verification is None or isinstance(verification, Mapping),
                 "session_verification must be an object or null")
        created_at = data["created_at"]
        _require(isinstance(created_at, str) and created_at, "created_at must be an ISO datetime")
        try:
            created = from_iso(created_at)
        except ValueError as exc:
            raise InvalidEvaluationRecord(f"created_at: {exc}") from None
        return cls(
            schema_version=_str(data, "schema_version"),
            evaluation_id=_str(data, "evaluation_id"),
            prediction_id=_str(data, "prediction_id"),
            target=_str(data, "target"),
            reference_session=_str(data, "reference_session"),
            session_date=_str(data, "session_date"),
            classification_version=_str(data, "classification_version"),
            status=status,
            realized_return=opt_decimal("realized_return"),
            realized_outcome=opt_enum("realized_outcome", RealizedOutcome),
            defer_reason=opt_enum("defer_reason", DeferReason),
            supersedes_evaluation_id=_str(data, "supersedes_evaluation_id"),
            reference_close=opt_decimal("reference_close"),
            target_close=opt_decimal("target_close"),
            reference_observation_id=_str(data, "reference_observation_id"),
            target_observation_id=_str(data, "target_observation_id"),
            source_id=_str(data, "source_id"),
            market_schema_version=_str(data, "market_schema_version"),
            session_verification=(None if verification is None
                                  else SessionVerification.from_dict(verification)),
            created_at=created,
        )


# ---------------------------------------------------------------- factory

def make_evaluation_record(
    *,
    prediction_id: str,
    reference_session: str,
    session_date: str,
    status: EvaluationStatus,
    created_at: datetime,
    realized_return: Optional[Decimal] = None,
    realized_outcome: Optional[RealizedOutcome] = None,
    defer_reason: Optional[DeferReason] = None,
    supersedes_evaluation_id: str = "",
    target: str = TARGET_TOPIX,
    classification_version: str = NEUTRAL_BAND_RULE_VERSION,
    reference_close: Optional[Decimal] = None,
    target_close: Optional[Decimal] = None,
    reference_observation_id: str = "",
    target_observation_id: str = "",
    source_id: str = "",
    market_schema_version: str = "",
    session_verification: Optional[SessionVerification] = None,
) -> EvaluationRecord:
    """明示 field から不変レコードを作る（`evaluation_id` は意味論から決定論的に導く）。

    realized_return は呼び出し側（後続 evaluator）が Decimal で渡す。ここでは市場データから
    計算しない。`realized_outcome` を省略した EVALUATED は凍結分類規則で導く（矛盾する値は拒否）。
    created_at は呼び出し側が明示する（module は現在時刻を読まない）。
    """
    if (status is EvaluationStatus.EVALUATED and realized_outcome is None
            and realized_return is not None):
        realized_outcome = classify_realized_return(
            realized_return, classification_version=classification_version)
    payload = identity_payload(
        schema_version=EVALUATION_RECORD_SCHEMA_VERSION, prediction_id=prediction_id,
        target=target, reference_session=reference_session, session_date=session_date,
        classification_version=classification_version, status=status,
        realized_return=realized_return, realized_outcome=realized_outcome,
        defer_reason=defer_reason, supersedes_evaluation_id=supersedes_evaluation_id)
    return EvaluationRecord(
        evaluation_id=make_evaluation_id(payload), prediction_id=prediction_id, target=target,
        reference_session=reference_session, session_date=session_date,
        classification_version=classification_version, status=status,
        realized_return=realized_return, realized_outcome=realized_outcome,
        defer_reason=defer_reason, supersedes_evaluation_id=supersedes_evaluation_id,
        reference_close=reference_close, target_close=target_close,
        reference_observation_id=reference_observation_id,
        target_observation_id=target_observation_id, source_id=source_id,
        market_schema_version=market_schema_version, session_verification=session_verification,
        created_at=created_at)


# ---------------------------------------------------------------- invariants

def _require(condition: bool, message: str) -> None:
    if not condition:
        raise InvalidEvaluationRecord(message)


def _str(data: Mapping[str, object], name: str) -> str:
    value = data[name]
    _require(isinstance(value, str), f"{name} must be a string")
    return value  # type: ignore[return-value]


def _opt_decimal(value: Optional[Decimal]) -> Optional[str]:
    return None if value is None else canonical_decimal(value)


def _validate_iso_date(name: str, value: str) -> None:
    try:
        parsed = date.fromisoformat(value)
    except (TypeError, ValueError):
        raise InvalidEvaluationRecord(f"{name} must be an ISO date (YYYY-MM-DD)") from None
    _require(parsed.isoformat() == value, f"{name} must be canonical YYYY-MM-DD")


def _validate_content_id(name: str, value: str, prefix: str) -> None:
    expected_prefix = prefix + "_"
    _require(isinstance(value, str) and value.startswith(expected_prefix)
             and len(value) == len(expected_prefix) + _ID_HEX_LENGTH
             and all(c in hexdigits and not c.isupper() for c in value[len(expected_prefix):]),
             f"{name} must look like {expected_prefix}<{_ID_HEX_LENGTH} hex>")
