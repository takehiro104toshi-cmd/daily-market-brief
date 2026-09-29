"""P8-A2 — PIT の市場 ／ 財務の観測の純 model（authority の観測 record・語彙・値・時間・期間・履歴の不変条件）。

答える問い: どの Security ／ Issuer の、どの市場の日 ／ 会計の期間について、どの出所から、どの値が観測され、それは
いつ知り得たか。良い会社か ・割安か ・screen を通るか ・Theme の受益か ・買うべきかは答えない（派生指標も作らない）。

- 観測の class は 3 つで互いに化けない: `MarketObservation`（Security の日次の四本値 ・出来高）・`FundamentalActual`
  （報告された実績。財務諸表の値は Issuer、発行済株式数は Security）・`FundamentalForecast`（会社予想。Issuer）。
- 市場の値は `RAW_REPORTED` と `PROVIDER_ADJUSTED`（業者が計算した調整値。計算の参照を必須にする）を別の slot に持つ。
  調整値は生値を置き換えない。後の調整は新しい知識の時刻を持つ別の revision で、過去へ漏れない。
- 知り得た時刻は `KnowledgeTime`: 正確な時刻（TIMESTAMP）か、日付だけ（DATE。東京の暦日のどこか）。日付だけの知識に
  時刻を作らない（午前 0 時 ・開場 ・引けとみなさない）。
- 値は 10 進の正準の文字列（float を拒否）と、量の種類 ・通貨 ・桁の単位を持つ。値が無いことは MISSING ／ NOT_REPORTED ／
  NOT_APPLICABLE の状態で表し、0 と区別する。
- 訂正 ／ 修正は古い record を書き換えず、`supersedes` で前の record を指す新しい record（同じ slot の一本の鎖。分岐なし）。
- 主語は A1 の identity（`IdentityHistory`）に登録済みでなければならない。観測から identity を作らない ・推測しない。

契約: `docs/databank/PHASE8_PIT_OBSERVATION_CONTRACT.md`。
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from enum import Enum
from typing import Any, ClassVar, Dict, FrozenSet, Iterable, List, Mapping, Optional, Tuple

from ..core.ids import content_id
from ..core.time import from_iso, to_utc_iso
from .identity_model import (CREDENTIAL_MARKERS, IdentityHistory, SourceClass, SubjectKind, canonical_json,
                             is_issuer_id, is_security_id)

SCHEMA_VERSION = "p8_observation_record:0.1.0"
RECORD_ID_PREFIX = "p8obs"
#: 観測の record の authority の種類（契約 §2）
AUTHORITATIVE_OBSERVATION_RECORD = "AUTHORITATIVE_OBSERVATION_RECORD"
#: 日付だけの知識 ・市場の日を読む暦（東京。固定の UTC+9。夏時間なし）
TOKYO = timezone(timedelta(hours=9), "JST")

MAX_INTEGER_DIGITS = 20
MAX_FRACTION_DIGITS = 10
_RECORD_ID_RE = re.compile(rf"^{RECORD_ID_PREFIX}_[0-9a-f]{{24}}$")
_SOURCE_REF_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:#-]{0,159}$")
_SOURCE_FIELD_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_]{0,31}$")
_DECIMAL_TEXT_RE = re.compile(r"^-?[0-9]+(\.[0-9]+)?$")
MAX_FISCAL_YEAR_DAYS = 550


class ObservationModelError(ValueError):
    """構造・語彙・値の違反（fail closed）。detail は field 名だけで、値を入れない。"""

    def __init__(self, code: str, detail: str = "") -> None:
        super().__init__(f"{code}: {detail}" if detail else code)
        self.code = code
        self.detail = detail


class ObservationHistoryError(ValueError):
    """履歴の不変条件の違反（未登録の主語 ・鎖の分岐 ・知識の逆行 ・coverage との矛盾）。"""

    def __init__(self, code: str, detail: str = "") -> None:
        super().__init__(f"{code}: {detail}" if detail else code)
        self.code = code
        self.detail = detail


def _require(condition: bool, code: str, detail: str = "") -> None:
    if not condition:
        raise ObservationModelError(code, detail)


# ---------------------------------------------------------------- 語彙（閉じた集合）


class ObservationClass(str, Enum):
    MARKET_OBSERVATION = "MARKET_OBSERVATION"
    FUNDAMENTAL_ACTUAL = "FUNDAMENTAL_ACTUAL"
    FUNDAMENTAL_FORECAST = "FUNDAMENTAL_FORECAST"


class RecordKind(str, Enum):
    MARKET_OBSERVATION = "MARKET_OBSERVATION"
    FUNDAMENTAL_ACTUAL = "FUNDAMENTAL_ACTUAL"
    FUNDAMENTAL_FORECAST = "FUNDAMENTAL_FORECAST"
    OBSERVATION_COVERAGE = "OBSERVATION_COVERAGE"


class MarketField(str, Enum):
    OPEN = "OPEN"
    HIGH = "HIGH"
    LOW = "LOW"
    CLOSE = "CLOSE"
    VOLUME = "VOLUME"


class FundamentalField(str, Enum):
    REVENUE = "REVENUE"
    OPERATING_INCOME = "OPERATING_INCOME"
    NET_INCOME = "NET_INCOME"
    EPS = "EPS"
    EQUITY = "EQUITY"
    TOTAL_ASSETS = "TOTAL_ASSETS"
    OPERATING_CASH_FLOW = "OPERATING_CASH_FLOW"
    SHARES_OUTSTANDING = "SHARES_OUTSTANDING"


class PriceBasis(str, Enum):
    RAW_REPORTED = "RAW_REPORTED"
    PROVIDER_ADJUSTED = "PROVIDER_ADJUSTED"


class StatementBasis(str, Enum):
    CONSOLIDATED = "CONSOLIDATED"
    NON_CONSOLIDATED = "NON_CONSOLIDATED"


class PeriodBasis(str, Enum):
    FISCAL_YEAR = "FISCAL_YEAR"
    SINGLE_QUARTER = "SINGLE_QUARTER"
    CUMULATIVE_YEAR_TO_DATE = "CUMULATIVE_YEAR_TO_DATE"


class KnowledgePrecision(str, Enum):
    TIMESTAMP = "TIMESTAMP"
    DATE = "DATE"


class ValueState(str, Enum):
    VALUE_PRESENT = "VALUE_PRESENT"
    MISSING = "MISSING"
    NOT_REPORTED = "NOT_REPORTED"
    NOT_APPLICABLE = "NOT_APPLICABLE"


class Measure(str, Enum):
    PRICE = "PRICE"
    TRADED_VOLUME = "TRADED_VOLUME"
    MONETARY_AMOUNT = "MONETARY_AMOUNT"
    PER_SHARE_AMOUNT = "PER_SHARE_AMOUNT"
    SHARE_COUNT = "SHARE_COUNT"


class Currency(str, Enum):
    JPY = "JPY"


class Scale(str, Enum):
    ONE = "ONE"
    THOUSAND = "THOUSAND"
    MILLION = "MILLION"


class CoverageDataset(str, Enum):
    MARKET_DAILY = "MARKET_DAILY"
    FUNDAMENTAL_DISCLOSURE = "FUNDAMENTAL_DISCLOSURE"


class _Sign(str, Enum):
    POSITIVE = "POSITIVE"
    NON_NEGATIVE = "NON_NEGATIVE"
    ANY = "ANY"


MARKET_MEASURES: Mapping[MarketField, Measure] = {
    MarketField.OPEN: Measure.PRICE, MarketField.HIGH: Measure.PRICE, MarketField.LOW: Measure.PRICE,
    MarketField.CLOSE: Measure.PRICE, MarketField.VOLUME: Measure.TRADED_VOLUME}
FUNDAMENTAL_MEASURES: Mapping[FundamentalField, Measure] = {
    FundamentalField.REVENUE: Measure.MONETARY_AMOUNT, FundamentalField.OPERATING_INCOME: Measure.MONETARY_AMOUNT,
    FundamentalField.NET_INCOME: Measure.MONETARY_AMOUNT, FundamentalField.EPS: Measure.PER_SHARE_AMOUNT,
    FundamentalField.EQUITY: Measure.MONETARY_AMOUNT, FundamentalField.TOTAL_ASSETS: Measure.MONETARY_AMOUNT,
    FundamentalField.OPERATING_CASH_FLOW: Measure.MONETARY_AMOUNT,
    FundamentalField.SHARES_OUTSTANDING: Measure.SHARE_COUNT}
#: 実績の主語（財務諸表の値は Issuer。発行済株式数は上場物の値なので Security）
FUNDAMENTAL_SUBJECT: Mapping[FundamentalField, SubjectKind] = {
    field: (SubjectKind.SECURITY if field is FundamentalField.SHARES_OUTSTANDING else SubjectKind.ISSUER)
    for field in FundamentalField}
#: 会社予想になり得る値（会社予想は Issuer の値だけ）
FORECAST_FIELDS: FrozenSet[FundamentalField] = frozenset({
    FundamentalField.REVENUE, FundamentalField.OPERATING_INCOME, FundamentalField.NET_INCOME, FundamentalField.EPS})
#: 量の種類ごとの通貨 ・桁の単位 ・符号の規則
MEASURE_RULES: Mapping[Measure, Tuple[Optional[Currency], FrozenSet[Scale], _Sign]] = {
    Measure.PRICE: (Currency.JPY, frozenset({Scale.ONE}), _Sign.POSITIVE),
    Measure.TRADED_VOLUME: (None, frozenset({Scale.ONE, Scale.THOUSAND}), _Sign.NON_NEGATIVE),
    Measure.MONETARY_AMOUNT: (Currency.JPY, frozenset(Scale), _Sign.ANY),
    Measure.PER_SHARE_AMOUNT: (Currency.JPY, frozenset({Scale.ONE}), _Sign.ANY),
    Measure.SHARE_COUNT: (None, frozenset({Scale.ONE, Scale.THOUSAND}), _Sign.NON_NEGATIVE),
}
#: 観測の種類 ×（市場は価格の基準）ごとに authority を持てる出所（契約 §17）
SOURCE_COMPATIBILITY: Mapping[Tuple[RecordKind, Optional[PriceBasis]], FrozenSet[SourceClass]] = {
    (RecordKind.MARKET_OBSERVATION, PriceBasis.RAW_REPORTED): frozenset({SourceClass.JQUANTS,
                                                                         SourceClass.OFFICIAL_EXCHANGE}),
    (RecordKind.MARKET_OBSERVATION, PriceBasis.PROVIDER_ADJUSTED): frozenset({SourceClass.JQUANTS}),
    (RecordKind.FUNDAMENTAL_ACTUAL, None): frozenset({SourceClass.ISSUER_DISCLOSURE, SourceClass.JQUANTS,
                                                      SourceClass.HUMAN_REVIEWED}),
    (RecordKind.FUNDAMENTAL_FORECAST, None): frozenset({SourceClass.ISSUER_DISCLOSURE, SourceClass.JQUANTS}),
    (RecordKind.OBSERVATION_COVERAGE, None): frozenset({SourceClass.JQUANTS, SourceClass.OFFICIAL_EXCHANGE,
                                                        SourceClass.HUMAN_REVIEWED}),
}
DATASET_FOR_CLASS: Mapping[ObservationClass, CoverageDataset] = {
    ObservationClass.MARKET_OBSERVATION: CoverageDataset.MARKET_DAILY,
    ObservationClass.FUNDAMENTAL_ACTUAL: CoverageDataset.FUNDAMENTAL_DISCLOSURE,
    ObservationClass.FUNDAMENTAL_FORECAST: CoverageDataset.FUNDAMENTAL_DISCLOSURE}


# ---------------------------------------------------------------- 値の検査


def _enum(value: Any, enum_type, field_name: str):
    if isinstance(value, enum_type):
        return value
    raise ObservationModelError("INVALID_VOCABULARY", field_name)


def _parse_enum(value: Any, enum_type, field_name: str):
    try:
        return enum_type(value)
    except (ValueError, TypeError):
        raise ObservationModelError("INVALID_VOCABULARY", field_name) from None


def _plain_date(value: Any, field_name: str) -> date:
    _require(type(value) is date, "INVALID_DATE", field_name)                   # datetime（date の subclass）を拒む
    return value


def _parse_date(value: Any, field_name: str) -> date:
    _require(isinstance(value, str), "INVALID_DATE", field_name)
    try:
        parsed = date.fromisoformat(value)
    except ValueError:
        raise ObservationModelError("INVALID_DATE", field_name) from None
    _require(parsed.isoformat() == value, "INVALID_DATE", field_name)
    return parsed


def _aware(value: Any, field_name: str) -> datetime:
    _require(isinstance(value, datetime), "INVALID_DATETIME", field_name)
    _require(value.tzinfo is not None and value.tzinfo.utcoffset(value) is not None, "NAIVE_DATETIME", field_name)
    return value


def _parse_datetime(value: Any, field_name: str) -> datetime:
    _require(isinstance(value, str), "INVALID_DATETIME", field_name)
    try:
        return from_iso(value)
    except ValueError:
        raise ObservationModelError("INVALID_DATETIME", field_name) from None


def day_start(day: date) -> datetime:
    """東京の暦日の始まり（aware）。"""
    return datetime(day.year, day.month, day.day, tzinfo=TOKYO)


def _no_credential_marker(value: str, field_name: str) -> None:
    lowered = value.lower()
    _require(not any(marker in lowered for marker in CREDENTIAL_MARKERS), "CREDENTIAL_LIKE_TEXT", field_name)


def canonical_decimal(value: Any) -> str:
    """10 進の正準の文字列（指数なし ・末尾の 0 なし ・0 は "0"）。float ／ bool ／ 非有限を拒む。"""
    _require(not isinstance(value, (bool, float)), "FLOAT_REJECTED" if isinstance(value, float) else "INVALID_AMOUNT",
             "amount")
    if isinstance(value, int):
        number = Decimal(value)
    elif isinstance(value, Decimal):
        number = value
    elif isinstance(value, str):
        _require(bool(_DECIMAL_TEXT_RE.match(value)), "INVALID_AMOUNT", "amount")
        try:
            number = Decimal(value)
        except InvalidOperation:
            raise ObservationModelError("INVALID_AMOUNT", "amount") from None
    else:
        raise ObservationModelError("INVALID_AMOUNT", "amount")
    _require(number.is_finite(), "INVALID_AMOUNT", "amount")
    if number == 0:
        return "0"
    text = format(number.normalize(), "f")
    integer, _, fraction = text.lstrip("-").partition(".")
    _require(len(integer) <= MAX_INTEGER_DIGITS and len(fraction) <= MAX_FRACTION_DIGITS, "AMOUNT_OUT_OF_RANGE",
             "amount")
    return text


# ---------------------------------------------------------------- 時間 ・期間 ・値 ・出所


class KnowledgeState(str, Enum):
    KNOWN = "KNOWN"
    UNKNOWN = "UNKNOWN"
    UNCERTAIN = "UNCERTAIN"


@dataclass(frozen=True)
class KnowledgeTime:
    """知り得た時刻。TIMESTAMP は正確な時刻、DATE は東京の暦日のどこか（時刻を作らない）。"""

    precision: KnowledgePrecision
    at: Optional[datetime] = None
    on: Optional[date] = None

    def __post_init__(self) -> None:
        _enum(self.precision, KnowledgePrecision, "precision")
        if self.precision is KnowledgePrecision.TIMESTAMP:
            _aware(self.at, "known_at")
            _require(self.on is None, "INVALID_KNOWLEDGE", "known_on")
        else:
            _plain_date(self.on, "known_on")
            _require(self.at is None, "INVALID_KNOWLEDGE", "known_at")

    @classmethod
    def exact(cls, at: datetime) -> "KnowledgeTime":
        return cls(KnowledgePrecision.TIMESTAMP, at=at)

    @classmethod
    def date_only(cls, on: date) -> "KnowledgeTime":
        return cls(KnowledgePrecision.DATE, on=on)

    @property
    def earliest(self) -> datetime:
        """知り得た可能性のある最初の瞬間。"""
        return self.at if self.at is not None else day_start(self.on)

    @property
    def certain_by(self) -> datetime:
        """これ以後は確かに知られている瞬間（DATE は翌日の始まり）。"""
        return self.at if self.at is not None else day_start(self.on + timedelta(days=1))

    def state_at(self, cutoff: datetime) -> KnowledgeState:
        if self.certain_by <= cutoff:
            return KnowledgeState.KNOWN
        if self.earliest > cutoff:
            return KnowledgeState.UNKNOWN
        return KnowledgeState.UNCERTAIN

    def as_dict(self) -> Dict[str, Any]:
        value = to_utc_iso(self.at) if self.at is not None else self.on.isoformat()
        return {"precision": self.precision.value, "value": value}

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "KnowledgeTime":
        _reject_unknown(data, ("precision", "value"), "knowledge")
        precision = _parse_enum(data["precision"], KnowledgePrecision, "precision")
        if precision is KnowledgePrecision.TIMESTAMP:
            return cls.exact(_parse_datetime(data["value"], "known_at"))
        return cls.date_only(_parse_date(data["value"], "known_on"))


@dataclass(frozen=True)
class ReportingPeriod:
    """会計の期間（日付は両端を含む）。TTM ・年率換算の基準は無い。"""

    basis: PeriodBasis
    fiscal_year_start: date
    fiscal_year_end: date
    period_start: date
    period_end: date
    quarter: int = 0

    def __post_init__(self) -> None:
        _enum(self.basis, PeriodBasis, "period_basis")
        for name in ("fiscal_year_start", "fiscal_year_end", "period_start", "period_end"):
            _plain_date(_period_date(self, name), name)
        _require(isinstance(self.quarter, int) and not isinstance(self.quarter, bool), "INVALID_PERIOD", "quarter")
        _require(self.fiscal_year_start < self.fiscal_year_end, "INVALID_PERIOD", "fiscal_year")
        _require((self.fiscal_year_end - self.fiscal_year_start).days <= MAX_FISCAL_YEAR_DAYS, "INVALID_PERIOD",
                 "fiscal_year")
        _require(self.fiscal_year_start <= self.period_start <= self.period_end <= self.fiscal_year_end,
                 "INVALID_PERIOD", "period")
        if self.basis is PeriodBasis.FISCAL_YEAR:
            _require(self.quarter == 0 and self.period_start == self.fiscal_year_start
                     and self.period_end == self.fiscal_year_end, "INVALID_PERIOD", "fiscal_year_period")
        elif self.basis is PeriodBasis.CUMULATIVE_YEAR_TO_DATE:
            _require(self.quarter in (1, 2, 3) and self.period_start == self.fiscal_year_start
                     and self.period_end < self.fiscal_year_end, "INVALID_PERIOD", "cumulative_period")
        else:
            _require(self.quarter in (1, 2, 3, 4), "INVALID_PERIOD", "single_quarter")

    def as_dict(self) -> Dict[str, Any]:
        return {"basis": self.basis.value, "fiscal_year_end": self.fiscal_year_end.isoformat(),
                "fiscal_year_start": self.fiscal_year_start.isoformat(), "period_end": self.period_end.isoformat(),
                "period_start": self.period_start.isoformat(), "quarter": self.quarter}

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "ReportingPeriod":
        _reject_unknown(data, ("basis", "fiscal_year_end", "fiscal_year_start", "period_end", "period_start",
                               "quarter"), "period")
        return cls(basis=_parse_enum(data["basis"], PeriodBasis, "period_basis"),
                   fiscal_year_start=_parse_date(data["fiscal_year_start"], "fiscal_year_start"),
                   fiscal_year_end=_parse_date(data["fiscal_year_end"], "fiscal_year_end"),
                   period_start=_parse_date(data["period_start"], "period_start"),
                   period_end=_parse_date(data["period_end"], "period_end"), quarter=data["quarter"])


def _period_date(period: "ReportingPeriod", name: str) -> Any:
    return {"fiscal_year_start": period.fiscal_year_start, "fiscal_year_end": period.fiscal_year_end,
            "period_start": period.period_start, "period_end": period.period_end}[name]


@dataclass(frozen=True)
class ObservationValue:
    """値（状態 ・量の種類 ・10 進の正準の文字列 ・通貨 ・桁の単位）。値が無い状態は数も単位も持たない。"""

    state: ValueState
    measure: Measure
    amount: Optional[str] = None
    currency: Optional[Currency] = None
    scale: Optional[Scale] = None

    def __post_init__(self) -> None:
        _enum(self.state, ValueState, "value_state")
        _enum(self.measure, Measure, "measure")
        if self.state is not ValueState.VALUE_PRESENT:
            _require(self.amount is None and self.currency is None and self.scale is None, "ABSENT_VALUE_HAS_AMOUNT",
                     "value")
            return
        object.__setattr__(self, "amount", canonical_decimal(self.amount))
        currency, scales, sign = MEASURE_RULES[self.measure]
        _require(self.currency is currency, "INVALID_CURRENCY", "currency")
        _require(isinstance(self.scale, Scale) and self.scale in scales, "INVALID_SCALE", "scale")
        number = Decimal(self.amount)
        if sign is _Sign.POSITIVE:
            _require(number > 0, "INVALID_SIGN", "amount")
        elif sign is _Sign.NON_NEGATIVE:
            _require(number >= 0, "INVALID_SIGN", "amount")

    @classmethod
    def present(cls, measure: Measure, amount: Any, *, currency: Optional[Currency] = None,
                scale: Scale = Scale.ONE) -> "ObservationValue":
        return cls(ValueState.VALUE_PRESENT, measure, amount, currency, scale)

    @classmethod
    def absent(cls, measure: Measure, state: ValueState) -> "ObservationValue":
        _require(state is not ValueState.VALUE_PRESENT, "INVALID_VOCABULARY", "value_state")
        return cls(state, measure)

    def as_dict(self) -> Dict[str, Any]:
        return {"amount": self.amount, "currency": self.currency.value if self.currency else None,
                "measure": self.measure.value, "scale": self.scale.value if self.scale else None,
                "state": self.state.value}

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "ObservationValue":
        _reject_unknown(data, ("amount", "currency", "measure", "scale", "state"), "value")
        amount = data["amount"]
        _require(amount is None or isinstance(amount, str), "INVALID_AMOUNT", "amount")
        value = cls(state=_parse_enum(data["state"], ValueState, "value_state"),
                    measure=_parse_enum(data["measure"], Measure, "measure"), amount=amount,
                    currency=None if data["currency"] is None else _parse_enum(data["currency"], Currency, "currency"),
                    scale=None if data["scale"] is None else _parse_enum(data["scale"], Scale, "scale"))
        _require(value.amount == amount, "NON_CANONICAL_AMOUNT", "amount")
        return value


@dataclass(frozen=True)
class ObservationProvenance:
    """出所（閉じた class ・出所の record の参照 ・出所の欄 ・業者の調整の参照）。本文 ・path ・credential を持たない。"""

    source_class: SourceClass
    source_record_ref: str
    source_field: str = ""
    adjustment_ref: str = ""

    def __post_init__(self) -> None:
        _enum(self.source_class, SourceClass, "source_class")
        for name, value, pattern, optional in (("source_record_ref", self.source_record_ref, _SOURCE_REF_RE, False),
                                               ("source_field", self.source_field, _SOURCE_FIELD_RE, True),
                                               ("adjustment_ref", self.adjustment_ref, _SOURCE_REF_RE, True)):
            _require(isinstance(value, str), "INVALID_SOURCE_REF", name)
            if value == "" and optional:
                continue
            _require(bool(pattern.match(value)), "INVALID_SOURCE_REF", name)
            _no_credential_marker(value, name)

    def as_dict(self) -> Dict[str, Any]:
        return {"adjustment_ref": self.adjustment_ref, "source_class": self.source_class.value,
                "source_field": self.source_field, "source_record_ref": self.source_record_ref}

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "ObservationProvenance":
        _reject_unknown(data, ("adjustment_ref", "source_class", "source_field", "source_record_ref"), "provenance")
        return cls(source_class=_parse_enum(data["source_class"], SourceClass, "source_class"),
                   source_record_ref=data["source_record_ref"], source_field=data["source_field"],
                   adjustment_ref=data["adjustment_ref"])


def _reject_unknown(data: Mapping[str, Any], allowed: Iterable[str], name: str) -> None:
    _require(isinstance(data, Mapping), "INVALID_RECORD", name)
    _require(set(data) <= set(allowed), "UNKNOWN_FIELD", name)
    _require(set(allowed) <= set(data), "MISSING_FIELD", name)


def _check_supersedes(value: Any) -> str:
    _require(isinstance(value, str) and (value == "" or bool(_RECORD_ID_RE.match(value))), "INVALID_ID", "supersedes")
    return value


# ---------------------------------------------------------------- record


class _Record:
    """record の共通部（不変 ・内容 address）。"""

    KIND: ClassVar[RecordKind]
    AUTHORITY_CLASS: ClassVar[str] = AUTHORITATIVE_OBSERVATION_RECORD
    provenance: ObservationProvenance

    def _payload(self) -> Dict[str, Any]:
        raise NotImplementedError

    def _check_source(self, basis: Optional[PriceBasis] = None) -> None:
        _require(isinstance(self.provenance, ObservationProvenance), "INVALID_PROVENANCE", "provenance")
        _require(self.provenance.source_class in SOURCE_COMPATIBILITY[(self.KIND, basis)],
                 "SOURCE_NOT_COMPATIBLE", self.KIND.value)

    def identity_payload(self) -> Dict[str, Any]:
        return {"schema_version": SCHEMA_VERSION, "record_kind": self.KIND.value, "payload": self._payload(),
                "provenance": self.provenance.as_dict()}

    @property
    def record_id(self) -> str:
        return content_id(RECORD_ID_PREFIX, canonical_json(self.identity_payload()))

    def as_dict(self) -> Dict[str, Any]:
        return {**self.identity_payload(), "record_id": self.record_id}

    def canonical_line(self) -> str:
        return canonical_json(self.as_dict()) + "\n"


class _Observation(_Record):
    """観測の record（主語 ・slot ・知識の時刻 ・前の record を持つ）。"""

    CLASS: ClassVar[ObservationClass]
    knowledge: KnowledgeTime
    value: ObservationValue
    supersedes: str

    @property
    def subject_kind(self) -> SubjectKind:
        raise NotImplementedError

    @property
    def subject_id(self) -> str:
        raise NotImplementedError

    @property
    def data_date(self) -> date:
        """coverage を測る日（市場は取引日、財務は期間の末日）。"""
        raise NotImplementedError

    def slot_fields(self) -> Dict[str, Any]:
        raise NotImplementedError

    @property
    def slot_key(self) -> str:
        return canonical_json({**self.slot_fields(), "source_class": self.provenance.source_class.value})

    def _check_common(self) -> None:
        _require(isinstance(self.knowledge, KnowledgeTime), "INVALID_KNOWLEDGE", "knowledge")
        _require(isinstance(self.value, ObservationValue), "INVALID_VALUE", "value")
        _check_supersedes(self.supersedes)


def market_slot_fields(security_id: str, field: MarketField, basis: PriceBasis, session_date: date) -> Dict[str, Any]:
    return {"basis": basis.value, "class": ObservationClass.MARKET_OBSERVATION.value, "date": session_date.isoformat(),
            "field": field.value, "subject_id": security_id}


def fundamental_slot_fields(observation_class: ObservationClass, subject_id: str, field: FundamentalField,
                            basis: StatementBasis, period: ReportingPeriod) -> Dict[str, Any]:
    return {"basis": basis.value, "class": observation_class.value, "field": field.value,
            "period": period.as_dict(), "subject_id": subject_id}


def slot_key_for(slot_fields: Mapping[str, Any], source_class: SourceClass) -> str:
    return canonical_json({**slot_fields, "source_class": source_class.value})


@dataclass(frozen=True, kw_only=True)
class MarketObservation(_Observation):
    """Security の日次の市場の観測（生値 ／ 業者の調整値）。指標 ・return ・変動率 ・時価総額は作らない。"""

    KIND: ClassVar[RecordKind] = RecordKind.MARKET_OBSERVATION
    CLASS: ClassVar[ObservationClass] = ObservationClass.MARKET_OBSERVATION
    security_id: str
    field: MarketField
    basis: PriceBasis
    session_date: date
    value: ObservationValue
    knowledge: KnowledgeTime
    provenance: ObservationProvenance
    supersedes: str = ""

    def __post_init__(self) -> None:
        _require(is_security_id(self.security_id), "INVALID_SUBJECT", "security_id")
        _enum(self.field, MarketField, "field")
        _enum(self.basis, PriceBasis, "basis")
        _plain_date(self.session_date, "session_date")
        self._check_common()
        _require(self.value.measure is MARKET_MEASURES[self.field], "MEASURE_MISMATCH", "value")
        _require(self.knowledge.earliest >= day_start(self.session_date), "KNOWN_BEFORE_SESSION", "knowledge")
        self._check_source(self.basis)
        adjusted = self.basis is PriceBasis.PROVIDER_ADJUSTED
        _require((self.provenance.adjustment_ref != "") is adjusted, "ADJUSTMENT_REF_RULE", "adjustment_ref")
        _require(self.provenance.source_field != "", "INVALID_SOURCE_REF", "source_field")

    @property
    def subject_kind(self) -> SubjectKind:
        return SubjectKind.SECURITY

    @property
    def subject_id(self) -> str:
        return self.security_id

    @property
    def data_date(self) -> date:
        return self.session_date

    def slot_fields(self) -> Dict[str, Any]:
        return market_slot_fields(self.security_id, self.field, self.basis, self.session_date)

    def _payload(self) -> Dict[str, Any]:
        return {"basis": self.basis.value, "field": self.field.value, "knowledge": self.knowledge.as_dict(),
                "security_id": self.security_id, "session_date": self.session_date.isoformat(),
                "supersedes": self.supersedes, "value": self.value.as_dict()}

    @classmethod
    def _from_payload(cls, payload: Mapping[str, Any], provenance: ObservationProvenance) -> "MarketObservation":
        _reject_unknown(payload, ("basis", "field", "knowledge", "security_id", "session_date", "supersedes", "value"),
                        cls.KIND.value)
        return cls(security_id=payload["security_id"], field=_parse_enum(payload["field"], MarketField, "field"),
                   basis=_parse_enum(payload["basis"], PriceBasis, "basis"),
                   session_date=_parse_date(payload["session_date"], "session_date"),
                   value=ObservationValue.from_dict(payload["value"]),
                   knowledge=KnowledgeTime.from_dict(payload["knowledge"]), provenance=provenance,
                   supersedes=payload["supersedes"])


@dataclass(frozen=True, kw_only=True)
class FundamentalActual(_Observation):
    """報告された実績（財務諸表の値は Issuer、発行済株式数は Security）。比率 ・成長率 ・TTM を作らない。"""

    KIND: ClassVar[RecordKind] = RecordKind.FUNDAMENTAL_ACTUAL
    CLASS: ClassVar[ObservationClass] = ObservationClass.FUNDAMENTAL_ACTUAL
    subject: str
    field: FundamentalField
    statement_basis: StatementBasis
    period: ReportingPeriod
    value: ObservationValue
    knowledge: KnowledgeTime
    provenance: ObservationProvenance
    supersedes: str = ""

    def __post_init__(self) -> None:
        _enum(self.field, FundamentalField, "field")
        expected = FUNDAMENTAL_SUBJECT[self.field]
        check = is_security_id if expected is SubjectKind.SECURITY else is_issuer_id
        _require(check(self.subject), "INVALID_SUBJECT", "subject")
        _enum(self.statement_basis, StatementBasis, "statement_basis")
        _require(isinstance(self.period, ReportingPeriod), "INVALID_PERIOD", "period")
        self._check_common()
        _require(self.value.measure is FUNDAMENTAL_MEASURES[self.field], "MEASURE_MISMATCH", "value")
        _require(self.knowledge.earliest >= day_start(self.period.period_end + timedelta(days=1)),
                 "ACTUAL_KNOWN_BEFORE_PERIOD_END", "knowledge")
        self._check_source()
        _require(self.provenance.adjustment_ref == "", "ADJUSTMENT_REF_RULE", "adjustment_ref")
        _require(self.provenance.source_field != "", "INVALID_SOURCE_REF", "source_field")

    @property
    def subject_kind(self) -> SubjectKind:
        return FUNDAMENTAL_SUBJECT[self.field]

    @property
    def subject_id(self) -> str:
        return self.subject

    @property
    def data_date(self) -> date:
        return self.period.period_end

    def slot_fields(self) -> Dict[str, Any]:
        return fundamental_slot_fields(self.CLASS, self.subject, self.field, self.statement_basis, self.period)

    def _payload(self) -> Dict[str, Any]:
        return {"field": self.field.value, "knowledge": self.knowledge.as_dict(), "period": self.period.as_dict(),
                "statement_basis": self.statement_basis.value, "subject": self.subject,
                "supersedes": self.supersedes, "value": self.value.as_dict()}

    @classmethod
    def _from_payload(cls, payload: Mapping[str, Any], provenance: ObservationProvenance) -> "FundamentalActual":
        _reject_unknown(payload, ("field", "knowledge", "period", "statement_basis", "subject", "supersedes",
                                  "value"), cls.KIND.value)
        return cls(subject=payload["subject"], field=_parse_enum(payload["field"], FundamentalField, "field"),
                   statement_basis=_parse_enum(payload["statement_basis"], StatementBasis, "statement_basis"),
                   period=ReportingPeriod.from_dict(payload["period"]),
                   value=ObservationValue.from_dict(payload["value"]),
                   knowledge=KnowledgeTime.from_dict(payload["knowledge"]), provenance=provenance,
                   supersedes=payload["supersedes"])


@dataclass(frozen=True, kw_only=True)
class FundamentalForecast(_Observation):
    """会社予想（対象の期間 ・知り得た時刻つき）。実績として返らない。後の実績は予想の履歴を書き換えない。"""

    KIND: ClassVar[RecordKind] = RecordKind.FUNDAMENTAL_FORECAST
    CLASS: ClassVar[ObservationClass] = ObservationClass.FUNDAMENTAL_FORECAST
    issuer_id: str
    field: FundamentalField
    statement_basis: StatementBasis
    target_period: ReportingPeriod
    value: ObservationValue
    knowledge: KnowledgeTime
    provenance: ObservationProvenance
    supersedes: str = ""

    def __post_init__(self) -> None:
        _require(is_issuer_id(self.issuer_id), "INVALID_SUBJECT", "issuer_id")
        _enum(self.field, FundamentalField, "field")
        _require(self.field in FORECAST_FIELDS, "NOT_FORECASTABLE", "field")
        _enum(self.statement_basis, StatementBasis, "statement_basis")
        _require(isinstance(self.target_period, ReportingPeriod), "INVALID_PERIOD", "target_period")
        self._check_common()
        _require(self.value.measure is FUNDAMENTAL_MEASURES[self.field], "MEASURE_MISMATCH", "value")
        self._check_source()
        _require(self.provenance.adjustment_ref == "", "ADJUSTMENT_REF_RULE", "adjustment_ref")
        _require(self.provenance.source_field != "", "INVALID_SOURCE_REF", "source_field")

    @property
    def subject_kind(self) -> SubjectKind:
        return SubjectKind.ISSUER

    @property
    def subject_id(self) -> str:
        return self.issuer_id

    @property
    def data_date(self) -> date:
        return self.target_period.period_end

    def slot_fields(self) -> Dict[str, Any]:
        return fundamental_slot_fields(self.CLASS, self.issuer_id, self.field, self.statement_basis,
                                       self.target_period)

    def _payload(self) -> Dict[str, Any]:
        return {"field": self.field.value, "issuer_id": self.issuer_id, "knowledge": self.knowledge.as_dict(),
                "statement_basis": self.statement_basis.value, "supersedes": self.supersedes,
                "target_period": self.target_period.as_dict(), "value": self.value.as_dict()}

    @classmethod
    def _from_payload(cls, payload: Mapping[str, Any], provenance: ObservationProvenance) -> "FundamentalForecast":
        _reject_unknown(payload, ("field", "issuer_id", "knowledge", "statement_basis", "supersedes",
                                  "target_period", "value"), cls.KIND.value)
        return cls(issuer_id=payload["issuer_id"], field=_parse_enum(payload["field"], FundamentalField, "field"),
                   statement_basis=_parse_enum(payload["statement_basis"], StatementBasis, "statement_basis"),
                   target_period=ReportingPeriod.from_dict(payload["target_period"]),
                   value=ObservationValue.from_dict(payload["value"]),
                   knowledge=KnowledgeTime.from_dict(payload["knowledge"]), provenance=provenance,
                   supersedes=payload["supersedes"])


@dataclass(frozen=True, kw_only=True)
class ObservationCoverage(_Record):
    """取り込みの完全性の宣言: `dataset` の data の日 `[data_from, data_to)` について、知り得た時刻が
    `complete_through` 以前の観測はすべて store にある。store の metadata で、世界の事実ではない。"""

    KIND: ClassVar[RecordKind] = RecordKind.OBSERVATION_COVERAGE
    dataset: CoverageDataset
    data_from: date
    data_to: date
    complete_through: datetime
    provenance: ObservationProvenance

    def __post_init__(self) -> None:
        _enum(self.dataset, CoverageDataset, "dataset")
        _plain_date(self.data_from, "data_from")
        _plain_date(self.data_to, "data_to")
        _require(self.data_from < self.data_to, "INVALID_INTERVAL", "coverage")
        _aware(self.complete_through, "complete_through")
        self._check_source()
        _require(self.provenance.source_field == "" and self.provenance.adjustment_ref == "", "INVALID_SOURCE_REF",
                 "coverage")

    def covers(self, day: date) -> bool:
        return self.data_from <= day < self.data_to

    def _payload(self) -> Dict[str, Any]:
        return {"complete_through": to_utc_iso(self.complete_through), "data_from": self.data_from.isoformat(),
                "data_to": self.data_to.isoformat(), "dataset": self.dataset.value}

    @classmethod
    def _from_payload(cls, payload: Mapping[str, Any], provenance: ObservationProvenance) -> "ObservationCoverage":
        _reject_unknown(payload, ("complete_through", "data_from", "data_to", "dataset"), cls.KIND.value)
        return cls(dataset=_parse_enum(payload["dataset"], CoverageDataset, "dataset"),
                   data_from=_parse_date(payload["data_from"], "data_from"),
                   data_to=_parse_date(payload["data_to"], "data_to"),
                   complete_through=_parse_datetime(payload["complete_through"], "complete_through"),
                   provenance=provenance)


RECORD_TYPES: Mapping[RecordKind, type] = {cls.KIND: cls for cls in (
    MarketObservation, FundamentalActual, FundamentalForecast, ObservationCoverage)}
OBSERVATION_TYPES: Tuple[type, ...] = (MarketObservation, FundamentalActual, FundamentalForecast)


def is_observation_record(value: Any) -> bool:
    return type(value) in RECORD_TYPES.values()


def parse_observation_record(data: Mapping[str, Any]):
    """直列化された 1 record を検査して復元する（未知の field ・版 ・id の不一致を拒む）。"""
    _reject_unknown(data, ("payload", "provenance", "record_id", "record_kind", "schema_version"), "record")
    _require(data["schema_version"] == SCHEMA_VERSION, "UNSUPPORTED_SCHEMA_VERSION", "schema_version")
    kind = _parse_enum(data["record_kind"], RecordKind, "record_kind")
    provenance = ObservationProvenance.from_dict(data["provenance"])
    _require(isinstance(data["payload"], Mapping), "INVALID_RECORD", "payload")
    record = RECORD_TYPES[kind]._from_payload(data["payload"], provenance)
    _require(data["record_id"] == record.record_id, "ID_MISMATCH", "record_id")
    return record


def parse_canonical_line(line: str):
    """1 行を復元し、それが record の正準の直列化と byte 一致することを確かめる。"""
    try:
        data = json.loads(line)
    except ValueError:
        raise ObservationModelError("MALFORMED_JSON", "line") from None
    _require(isinstance(data, dict), "NOT_AN_OBJECT", "line")
    record = parse_observation_record(data)
    _require(record.canonical_line() == line, "NON_CANONICAL_LINE", "line")
    return record


# ---------------------------------------------------------------- 履歴（slot ごとの一本の鎖 ・coverage との整合）


class ObservationHistory:
    """観測の record 列に履歴の不変条件を適用した、検証済みの authority の像。

    - 主語は A1 の identity に登録済み（種類も一致）。観測から identity を作らない。
    - slot（class ・主語 ・欄 ・基準 ・日 ／ 期間 ・出所）ごとに一本の鎖: 最初の record は `supersedes=""`、以後の revision は
      その時点の鎖の末尾だけを指す（分岐 ・別の slot ・未知の record を指すことを拒む）。知り得た最初の瞬間は鎖の中で
      非減少。
    - coverage が完全だと宣言した範囲（data の日と `complete_through`）の中へ、後から観測を足せない（過去の確かな答えを
      変えさせない）。
    - byte 一致の同じ record は収束する。append の順序は知識の時刻の順でなくてよい（過去の開示の取り込みを許す）。
    """

    def __init__(self, identity: IdentityHistory, records: Iterable[Any] = ()) -> None:
        if not isinstance(identity, IdentityHistory):
            raise ObservationHistoryError("IDENTITY_REQUIRED", "an A1 identity history is required")
        self.identity = identity
        self._records: List[Any] = []
        self._by_id: Dict[str, Any] = {}
        self.chains: Dict[str, List[Any]] = {}
        self.coverages: List[ObservationCoverage] = []
        for record in records:
            self.add(record)

    @property
    def records(self) -> Tuple[Any, ...]:
        return tuple(self._records)

    def contains(self, record_id: str) -> bool:
        return record_id in self._by_id

    def get(self, record_id: str) -> Optional[Any]:
        return self._by_id.get(record_id)

    def add(self, record: Any) -> bool:
        """検査して加える。byte 一致の同じ record なら何もしない（False）。"""
        if is_observation_record(record) and record.record_id in self._by_id:
            return False
        self.check(record)
        self._records.append(record)
        self._by_id[record.record_id] = record
        if record.KIND is RecordKind.OBSERVATION_COVERAGE:
            self.coverages.append(record)
        else:
            self.chains.setdefault(record.slot_key, []).append(record)
        return True

    def check(self, record: Any) -> None:
        if not is_observation_record(record):
            raise ObservationHistoryError("INVALID_TYPE", "not an observation record")
        if record.KIND is RecordKind.OBSERVATION_COVERAGE:
            return
        known = self.identity.securities if record.subject_kind is SubjectKind.SECURITY else self.identity.issuers
        if record.subject_id not in known:
            raise ObservationHistoryError("UNKNOWN_SUBJECT", record.subject_kind.value)
        chain = self.chains.get(record.slot_key, [])
        if record.supersedes == "":
            if chain:
                raise ObservationHistoryError("FORK", "slot already has a root")
        else:
            predecessor = self._by_id.get(record.supersedes)
            if predecessor is None or predecessor.KIND is RecordKind.OBSERVATION_COVERAGE:
                raise ObservationHistoryError("UNKNOWN_PREDECESSOR", "supersedes")
            if predecessor.slot_key != record.slot_key:
                raise ObservationHistoryError("PREDECESSOR_WRONG_SLOT", "supersedes")
            if chain[-1].record_id != record.supersedes:
                raise ObservationHistoryError("FORK", "supersedes is not the chain terminal")
            if record.knowledge.earliest < predecessor.knowledge.earliest:
                raise ObservationHistoryError("NON_MONOTONIC_KNOWLEDGE", "revision known before its predecessor")
        dataset = DATASET_FOR_CLASS[record.CLASS]
        for coverage in self.coverages:
            if coverage.dataset is dataset and coverage.covers(record.data_date) \
                    and record.knowledge.earliest <= coverage.complete_through:
                raise ObservationHistoryError("COVERAGE_CONTRADICTION", dataset.value)


__all__ = ["AUTHORITATIVE_OBSERVATION_RECORD", "Currency", "CoverageDataset", "DATASET_FOR_CLASS",
           "FORECAST_FIELDS", "FUNDAMENTAL_MEASURES", "FUNDAMENTAL_SUBJECT", "FundamentalActual",
           "FundamentalField", "FundamentalForecast", "KnowledgePrecision", "KnowledgeState", "KnowledgeTime",
           "MARKET_MEASURES", "MEASURE_RULES", "MarketField", "MarketObservation", "Measure", "OBSERVATION_TYPES",
           "ObservationClass", "ObservationCoverage", "ObservationHistory", "ObservationHistoryError",
           "ObservationModelError", "ObservationProvenance", "ObservationValue", "PeriodBasis", "PriceBasis",
           "RECORD_ID_PREFIX", "RECORD_TYPES", "RecordKind", "ReportingPeriod", "SCHEMA_VERSION",
           "SOURCE_COMPATIBILITY", "Scale", "StatementBasis", "TOKYO", "ValueState", "canonical_decimal", "day_start",
           "fundamental_slot_fields", "is_observation_record", "market_slot_fields", "parse_canonical_line",
           "parse_observation_record", "slot_key_for"]
