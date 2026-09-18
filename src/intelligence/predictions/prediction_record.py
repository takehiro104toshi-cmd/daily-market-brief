"""PredictionRecord — Phase 5 P5-1A（不変の point-in-time 予測観測記録と決定論的 identity）。

「1 件の point-in-time 予測観測とは何か」を型として固定する。Phase 4 が**既に生成した**
`MorningBrief` ＋ `MarketSignal` の意味論を写すだけの不変レコードであり、

- 第二の分析結果ではない
- 売買推奨ではない
- EvaluationRecord でも realized outcome でもない
- CompassDraft でも delivery / publication identity でもない

規律（`docs/databank/PHASE5_ENTRY_CONTRACT.md` N-1 / §5 / §6 / §7）:

- **identity は意味論だけから決める。** `prediction_id` は §「canonical identity payload」の
  9 key を決定論的に直列化した SHA-256 から作る。`brief_id` / `signal_id` は provenance で
  あって hash payload に**入らない**。`delivery_id` / 表示文字列 / Markdown は**持たない**。
- **不変。** `frozen` dataclass。更新 API・同一日付上書き・「最新が古い記録を置換」を持たない。
- **fail closed。** 凍結 P4 語彙（5 level / 3 confidence / 6 unavailable reason /
  既知 horizon）以外、矛盾する状態（available なのに level 無し等）、P4 が生成しえない
  (level, confidence) 組、`reference_session >= session_date`、naive datetime は
  `InvalidPredictionRecord`。**黙って正規化しない。**
- **未来を持ち込まない。** realized outcome・評価状態・閾値版・市場観測の field は存在しない。
- **schema-local 検証と verified-calendar 検証は別物。** ここで検証するのは
  「`reference_session < session_date`」までであり、「直前の検証済み東京取引 session で
  あること」は P5-2 の verified-calendar 境界に属する（本 module は暦を持たず、weekday
  演算も行わない）。
- このモジュールは persistence・ingestion・評価を**実装しない**（P5-1B / P5-1C / P5-2）。
"""
from __future__ import annotations

import json
from dataclasses import dataclass, fields
from datetime import date, datetime
from enum import Enum
from typing import Dict, Mapping, Optional, Tuple

from ..compass.model import Confidence
from ..core.ids import content_id
from ..core.time import ensure_aware, ensure_aware_or_none, from_iso, to_utc_iso
from ..reports.market_signal import (
    APPROVED_UNAVAILABLE_REASONS,
    LEVEL_BY_STATE,
    MARKET_SIGNAL_SCHEMA_VERSION,
    R_DIRECTION_MIXED,
    R_DIRECTION_UNCERTAIN,
    SignalLevel,
)
from ..reports.model import MORNING_BRIEF_SCHEMA_VERSION

#: PredictionRecord の schema 版。realized-outcome 分類版（`topix_neutral_band:1.0.0`）とは
#: **別概念**であり、ここに閾値版を持ち込まない。
PREDICTION_RECORD_SCHEMA_VERSION = "prediction_record:0.1.0"

#: identity の prefix（`core.ids.content_id` の規約: prefix + "_" + sha256 先頭 24 hex）
PREDICTION_ID_PREFIX = "pred"

#: 凍結 P4 語彙（import 元が権威。ここで書き写さない）
SIGNAL_LEVELS: Tuple[str, ...] = tuple(level.value for level in SignalLevel)
CONFIDENCES: Tuple[str, ...] = tuple(c.value for c in Confidence)
UNAVAILABLE_REASONS: Tuple[str, ...] = tuple(APPROVED_UNAVAILABLE_REASONS)

#: P4 `build_market_signal` が生成しうる (level, confidence) の組（`LEVEL_BY_STATE` の値域）。
#: 例: NEUTRAL_RANGE は LOW としか組まない。これ以外は P4 が作らないため矛盾として拒否する。
APPROVED_LEVEL_CONFIDENCE_PAIRS: Tuple[Tuple[str, str], ...] = tuple(sorted({
    (level.value, confidence) for (_direction, confidence), level in LEVEL_BY_STATE.items()
}))

#: 既知の horizon token。P4 の `compass.config.outlook_horizon` 既定値と N-5
#: （1 東京取引 session の close-to-close）に対応する。新しい horizon は契約改訂で追加する。
KNOWN_HORIZONS: Tuple[str, ...] = ("next_tokyo_session",)

#: unavailable のうち、P4 が outlook の confidence / horizon を**保持したまま**返す理由
#: （`UNAVAILABLE_BY_DIRECTION` 分岐）。それ以外の unavailable は両方とも空文字である。
REASONS_WITH_OUTLOOK_STATE: Tuple[str, ...] = (R_DIRECTION_MIXED, R_DIRECTION_UNCERTAIN)

#: 受理する source schema 版（P4 は FROZEN。版が動いたら fail closed で気づく）
SUPPORTED_MORNING_BRIEF_SCHEMA_VERSIONS: Tuple[str, ...] = (MORNING_BRIEF_SCHEMA_VERSION,)
SUPPORTED_MARKET_SIGNAL_SCHEMA_VERSIONS: Tuple[str, ...] = (MARKET_SIGNAL_SCHEMA_VERSION,)

#: canonical identity payload の key（**この 9 つだけ**。昇順に直列化される）
IDENTITY_KEYS: Tuple[str, ...] = (
    "available", "confidence", "horizon", "level", "origin",
    "reference_session", "schema_version", "session_date", "unavailable_reason",
)


class PredictionOrigin(str, Enum):
    """記録の由来。LIVE と REPLAY を同じ identity にしない（§7 point-in-time）。"""

    LIVE = "LIVE"
    REPLAY = "REPLAY"


class InvalidPredictionRecord(ValueError):
    """凍結契約に反する状態（fail closed。正規化も推測もしない）。"""


# ---------------------------------------------------------------- identity（N-1）

def identity_payload(
    *,
    schema_version: str,
    session_date: str,
    reference_session: str,
    origin: PredictionOrigin,
    available: bool,
    level: Optional[SignalLevel],
    confidence: str,
    horizon: str,
    unavailable_reason: str,
) -> Dict[str, object]:
    """`prediction_id` の材料となる**意味論だけ**の正規化 payload。

    provenance（brief_id / signal_id / package_id / draft_id）・audit（recorded_at / cutoff /
    principle_refs / source 版）・表示（label / display_text / Markdown）は**含めない**。
    欠落は空文字で表し、JSON null を使わない。enum 以外の level / origin は正規化せず拒否する。
    """
    _require(isinstance(origin, PredictionOrigin), "origin must be PredictionOrigin")
    _require(level is None or isinstance(level, SignalLevel),
             "level must be a SignalLevel or None")
    return {
        "schema_version": schema_version,
        "session_date": session_date,
        "reference_session": reference_session,
        "origin": origin.value,
        "available": bool(available),
        "level": "" if level is None else level.value,
        "confidence": confidence,
        "horizon": horizon,
        "unavailable_reason": unavailable_reason,
    }


def canonical_identity(payload: Mapping[str, object]) -> str:
    """決定論的直列化: key 昇順・区切り `,` `:`・空白なし・`ensure_ascii=False`（UTF-8）。

    Python の repr に依存しない。bool は JSON true/false、文字列はそのまま、None は使わない。
    """
    if tuple(sorted(payload)) != IDENTITY_KEYS:
        raise InvalidPredictionRecord(
            f"identity payload keys drifted: {sorted(payload)!r}")
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def make_prediction_id(payload: Mapping[str, object]) -> str:
    """`pred_` + SHA-256(canonical UTF-8 bytes) の先頭 24 hex（`brief_id` / `signal_id` と同じ機構）。"""
    return content_id(PREDICTION_ID_PREFIX, canonical_identity(payload))


# ---------------------------------------------------------------- record

@dataclass(frozen=True, kw_only=True)
class PredictionRecord:
    """1 件の point-in-time 予測観測（不変）。

    field 分類（`docs/databank/PHASE5_ENTRY_CONTRACT.md` §5 / P5-1A）:

    A. SEMANTIC_IDENTITY_INPUT … schema_version / session_date / reference_session / origin /
       available / level / confidence / horizon / unavailable_reason
    B. PROVENANCE_ONLY         … brief_id / signal_id / package_id / draft_id /
       morning_brief_schema_version / market_signal_schema_version
    C. AUDIT_METADATA          … recorded_at / cutoff / principle_refs / market_principle_version /
       outlook_rule_version（P4 `CompassOutlook.rule_version` の写し。outlook が無い記録では空）
    D. DERIVED / NOT_STORED    … identity payload・canonical 文字列・abstention 判定・表示ラベル
    E. FORBIDDEN               … delivery_id / markdown_sha256 / markdown_bytes / label /
       display_text / text / Markdown / HTML / realized outcome / 評価状態 / 閾値版 / 市場観測
    """

    # -- identity / version
    schema_version: str = PREDICTION_RECORD_SCHEMA_VERSION
    prediction_id: str
    # -- time / session
    session_date: str
    reference_session: str
    origin: PredictionOrigin
    # -- signal semantics（P4 MarketSignal の写し）
    available: bool
    level: Optional[SignalLevel]
    confidence: str
    horizon: str
    unavailable_reason: str
    # -- provenance（identity に入らない）
    brief_id: str
    signal_id: str
    package_id: str = ""
    draft_id: str = ""
    morning_brief_schema_version: str
    market_signal_schema_version: str
    # -- audit metadata（identity に入らない）
    recorded_at: datetime
    cutoff: Optional[datetime] = None
    principle_refs: Tuple[str, ...] = ()
    market_principle_version: str = ""
    outlook_rule_version: str = ""

    # ------------------------------------------------------------ validation（fail closed）

    def __post_init__(self) -> None:
        _require(self.schema_version == PREDICTION_RECORD_SCHEMA_VERSION,
                 f"unsupported prediction record schema: {self.schema_version!r}")
        _validate_sessions(self.session_date, self.reference_session)
        _require(isinstance(self.origin, PredictionOrigin), "origin must be PredictionOrigin")
        _require(isinstance(self.available, bool), "available must be bool")
        _validate_signal_state(
            available=self.available, level=self.level, confidence=self.confidence,
            horizon=self.horizon, unavailable_reason=self.unavailable_reason)
        _require(bool(self.brief_id), "brief_id (provenance) is required")
        _require(bool(self.signal_id), "signal_id (provenance) is required")
        _require(self.morning_brief_schema_version in SUPPORTED_MORNING_BRIEF_SCHEMA_VERSIONS,
                 f"unsupported MorningBrief schema: {self.morning_brief_schema_version!r}")
        _require(self.market_signal_schema_version in SUPPORTED_MARKET_SIGNAL_SCHEMA_VERSIONS,
                 f"unsupported MarketSignal schema: {self.market_signal_schema_version!r}")
        ensure_aware(self.recorded_at, "PredictionRecord.recorded_at")
        ensure_aware_or_none(self.cutoff, "PredictionRecord.cutoff")
        _require(isinstance(self.principle_refs, tuple)
                 and all(isinstance(r, str) and r for r in self.principle_refs),
                 "principle_refs must be a tuple of non-empty strings")
        _require(isinstance(self.market_principle_version, str)
                 and isinstance(self.outlook_rule_version, str),
                 "rule / principle versions must be strings")
        expected = make_prediction_id(self.identity_payload())
        _require(self.prediction_id == expected,
                 "prediction_id does not match the semantic identity payload")

    # ------------------------------------------------------------ derived（保存しない）

    def identity_payload(self) -> Dict[str, object]:
        return identity_payload(
            schema_version=self.schema_version, session_date=self.session_date,
            reference_session=self.reference_session, origin=self.origin,
            available=self.available, level=self.level, confidence=self.confidence,
            horizon=self.horizon, unavailable_reason=self.unavailable_reason)

    @property
    def canonical(self) -> str:
        return canonical_identity(self.identity_payload())

    @property
    def is_abstention(self) -> bool:
        """棄権 = `available == False`。NEUTRAL_RANGE は棄権ではない。"""
        return not self.available

    # ------------------------------------------------------------ serialization（round-trip）

    def as_dict(self) -> Dict[str, object]:
        """JSON 互換 dict（決定論的・secret や表示文字列を含まない）。"""
        return {
            "schema_version": self.schema_version,
            "prediction_id": self.prediction_id,
            "session_date": self.session_date,
            "reference_session": self.reference_session,
            "origin": self.origin.value,
            "available": self.available,
            "level": "" if self.level is None else self.level.value,
            "confidence": self.confidence,
            "horizon": self.horizon,
            "unavailable_reason": self.unavailable_reason,
            "brief_id": self.brief_id,
            "signal_id": self.signal_id,
            "package_id": self.package_id,
            "draft_id": self.draft_id,
            "morning_brief_schema_version": self.morning_brief_schema_version,
            "market_signal_schema_version": self.market_signal_schema_version,
            "recorded_at": to_utc_iso(self.recorded_at),
            "cutoff": None if self.cutoff is None else to_utc_iso(self.cutoff),
            "principle_refs": list(self.principle_refs),
            "market_principle_version": self.market_principle_version,
            "outlook_rule_version": self.outlook_rule_version,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, object]) -> "PredictionRecord":
        known = {f.name for f in fields(cls)}
        unknown = sorted(set(data) - known)
        if unknown:
            raise InvalidPredictionRecord(f"unknown PredictionRecord fields: {unknown}")
        level = data.get("level") or ""
        return cls(
            schema_version=str(data.get("schema_version", "")),
            prediction_id=str(data.get("prediction_id", "")),
            session_date=str(data.get("session_date", "")),
            reference_session=str(data.get("reference_session", "")),
            origin=PredictionOrigin(str(data.get("origin", ""))),
            available=bool(data.get("available")),
            level=None if level == "" else SignalLevel(str(level)),
            confidence=str(data.get("confidence", "")),
            horizon=str(data.get("horizon", "")),
            unavailable_reason=str(data.get("unavailable_reason", "")),
            brief_id=str(data.get("brief_id", "")),
            signal_id=str(data.get("signal_id", "")),
            package_id=str(data.get("package_id", "") or ""),
            draft_id=str(data.get("draft_id", "") or ""),
            morning_brief_schema_version=str(data.get("morning_brief_schema_version", "")),
            market_signal_schema_version=str(data.get("market_signal_schema_version", "")),
            recorded_at=from_iso(str(data.get("recorded_at", ""))),
            cutoff=None if not data.get("cutoff") else from_iso(str(data["cutoff"])),
            principle_refs=tuple(str(r) for r in (data.get("principle_refs") or ())),
            market_principle_version=str(data.get("market_principle_version", "") or ""),
            outlook_rule_version=str(data.get("outlook_rule_version", "") or ""),
        )


# ---------------------------------------------------------------- factory

def make_prediction_record(
    *,
    session_date: str,
    reference_session: str,
    origin: PredictionOrigin,
    available: bool,
    level: Optional[SignalLevel],
    confidence: str,
    horizon: str,
    unavailable_reason: str,
    brief_id: str,
    signal_id: str,
    morning_brief_schema_version: str,
    market_signal_schema_version: str,
    recorded_at: datetime,
    package_id: str = "",
    draft_id: str = "",
    cutoff: Optional[datetime] = None,
    principle_refs: Tuple[str, ...] = (),
    market_principle_version: str = "",
    outlook_rule_version: str = "",
) -> PredictionRecord:
    """明示 field から不変レコードを作る（`prediction_id` は意味論から決定論的に導く）。

    表示文字列・delivery_id・realized outcome を受け取る引数は**存在しない**。
    P4 オブジェクトからの写し取り（ingestion）は P5-1C の責務であり、ここでは行わない。
    """
    payload = identity_payload(
        schema_version=PREDICTION_RECORD_SCHEMA_VERSION, session_date=session_date,
        reference_session=reference_session, origin=origin, available=available,
        level=level, confidence=confidence, horizon=horizon,
        unavailable_reason=unavailable_reason)
    return PredictionRecord(
        prediction_id=make_prediction_id(payload),
        session_date=session_date, reference_session=reference_session, origin=origin,
        available=available, level=level, confidence=confidence, horizon=horizon,
        unavailable_reason=unavailable_reason, brief_id=brief_id, signal_id=signal_id,
        package_id=package_id, draft_id=draft_id,
        morning_brief_schema_version=morning_brief_schema_version,
        market_signal_schema_version=market_signal_schema_version,
        recorded_at=recorded_at, cutoff=cutoff, principle_refs=tuple(principle_refs),
        market_principle_version=market_principle_version,
        outlook_rule_version=outlook_rule_version)


# ---------------------------------------------------------------- invariants

def _require(condition: bool, message: str) -> None:
    if not condition:
        raise InvalidPredictionRecord(message)


def _validate_sessions(session_date: str, reference_session: str) -> None:
    """schema-local 検証: ISO 日付であること・`reference_session < session_date`。

    「直前の**検証済み**東京取引 session であること」は verified-calendar 境界（P5-2）で
    検証する。ここでは暦を持たず、weekday 演算も行わない。
    """
    for name, value in (("session_date", session_date), ("reference_session", reference_session)):
        try:
            parsed = date.fromisoformat(value)
        except (TypeError, ValueError):
            raise InvalidPredictionRecord(f"{name} must be an ISO date (YYYY-MM-DD)") from None
        _require(parsed.isoformat() == value, f"{name} must be canonical YYYY-MM-DD")
    _require(reference_session < session_date,
             "reference_session must precede session_date (schema-local ordering)")


def _validate_signal_state(
    *, available: bool, level: Optional[SignalLevel], confidence: str, horizon: str,
    unavailable_reason: str,
) -> None:
    """P4 MarketSignal の状態機械をそのまま写す（矛盾は拒否・正規化しない）。

    AVAILABLE:   level ∈ 5 値 / confidence ∈ 3 値 / horizon ∈ 既知 / (level, confidence) は
                 P4 が生成しうる組 / unavailable_reason == ""
    UNAVAILABLE: level is None / unavailable_reason ∈ 6 値 /
                 direction_mixed・direction_uncertain のときだけ confidence・horizon が
                 outlook の値を保持し（両方非空）、それ以外は両方空
    """
    if available:
        _require(isinstance(level, SignalLevel), "available record requires a SignalLevel")
        _require(confidence in CONFIDENCES,
                 f"available record requires confidence in {CONFIDENCES}: {confidence!r}")
        _require(horizon in KNOWN_HORIZONS,
                 f"available record requires a known horizon: {horizon!r}")
        _require((level.value, confidence) in APPROVED_LEVEL_CONFIDENCE_PAIRS,
                 f"P4 never produces (level, confidence) = {(level.value, confidence)!r}")
        _require(unavailable_reason == "",
                 "available record must not carry an unavailable_reason")
        return
    _require(level is None, "unavailable record must not carry a level")
    _require(unavailable_reason in UNAVAILABLE_REASONS,
             f"unavailable_reason must be one of {UNAVAILABLE_REASONS}: {unavailable_reason!r}")
    if unavailable_reason in REASONS_WITH_OUTLOOK_STATE:
        _require(confidence in CONFIDENCES and horizon in KNOWN_HORIZONS,
                 f"{unavailable_reason} carries the outlook confidence/horizon in P4")
    else:
        _require(confidence == "" and horizon == "",
                 f"{unavailable_reason} carries no confidence/horizon in P4")
