"""Theme 土台 model（Phase 6 P6-A4a）— 純 model 層。永続化・resolver・discovery は含まない。

契約: docs/databank/PHASE6_THEME_SEMANTICS_AUTHORITY_CONTRACT.md（A1）、
      docs/databank/PHASE6_THEME_IDENTITY_EVIDENCE_CONTRACT.md（A2）、
      docs/databank/PHASE6_THEME_PERSISTENCE_REVISION_CONTRACT.md（A3）。

5 つの canonical record（A3 §3）:
    ThemeRootRecord / ThemeObservation / ThemeGovernanceEvent / ThemeMetadataRecord / ThemeSeriesMapping

設計原則（P5 record の前例を継承）:
- frozen dataclass。構築時に fail closed（`ThemeModelError`。機械可読 `code` 付き）。
- content id は **identity payload だけ**から `core.ids.content_id(prefix, canonical_json(payload))` で導出する
  （A2 §4 / A3 §6）。provenance / audit（`recorded_at`）は canonical 行（`as_dict`）に含むが id には含めない。
- DERIVED（fingerprint・資格判定・diversity・DIRECTLY_EVIDENCED link）は record に持たない
  （`fingerprint.py` / `qualification.py` の純関数で再計算する。A3 §6）。
- root id は生成 id（`theme_<ULID>`）であり内容から導出しない（A2 §3）。`new_root_id` だけが生成 primitive。
- 集合的 field は構築時に canonical 順へ正規化する（Python の set / dict 順序が id に影響しない）。
- validator は現在時刻・乱数を呼ばない。時刻は呼び出し側が注入する（aware 必須）。
- label / description / taxonomy / alias は ThemeObservation に存在しない（ThemeMetadataRecord。A2 §16）。
- lifecycle 状態・prediction horizon・expected return・BUY / SELL・prose authority は存在しない（A1）。
"""
from __future__ import annotations

import json
import re
import unicodedata
from dataclasses import dataclass, fields, is_dataclass
from datetime import date, datetime
from enum import Enum
from typing import Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

from ..core.ids import content_id, new_id
from ..core.time import ensure_aware, from_iso, to_utc_iso

# ---------------------------------------------------------------- schema / vocabulary versions

THEME_ROOT_SCHEMA_VERSION = "theme_root:0.1.0"
THEME_OBSERVATION_SCHEMA_VERSION = "theme_observation:0.1.0"
THEME_GOVERNANCE_SCHEMA_VERSION = "theme_governance:0.1.0"
THEME_METADATA_SCHEMA_VERSION = "theme_metadata:0.1.0"
THEME_SERIES_MAPPING_SCHEMA_VERSION = "theme_series_mapping:0.1.0"

MECHANISM_VOCABULARY_VERSION = "mechanism_vocabulary:0.1.0"
GOVERNANCE_VOCABULARY_VERSION = "governance_vocabulary:0.1.0"
METADATA_FIELD_VOCABULARY_VERSION = "metadata_field_vocabulary:0.1.0"

#: id prefix（`core.ids` の規約: prefix + "_" + 本体）
ROOT_ID_PREFIX = "theme"            # 生成 id: theme_<ULID 26 文字>
OBSERVATION_ID_PREFIX = "thobs"     # content-addressed: thobs_<sha256[:24]>
GOVERNANCE_EVENT_ID_PREFIX = "thgov"
METADATA_ID_PREFIX = "thmeta"
MAPPING_ID_PREFIX = "thmap"

_ROOT_ID_RE = re.compile(r"^theme_[0-9A-HJKMNP-TV-Z]{26}$")
_CONTENT_ID_RE = {
    OBSERVATION_ID_PREFIX: re.compile(r"^thobs_[0-9a-f]{24}$"),
    GOVERNANCE_EVENT_ID_PREFIX: re.compile(r"^thgov_[0-9a-f]{24}$"),
    METADATA_ID_PREFIX: re.compile(r"^thmeta_[0-9a-f]{24}$"),
    MAPPING_ID_PREFIX: re.compile(r"^thmap_[0-9a-f]{24}$"),
}
_KEY_RE = re.compile(r"^[a-z0-9][a-z0-9_.:-]{0,63}$")
_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")

#: 長さ上限（実装判断。意味論は変えない）
MAX_STATEMENT_LEN = 240
MAX_REF_LEN = 200
MAX_LOCATOR_LEN = 500
MAX_EXCERPT_LEN = 300
MAX_NOTE_LEN = 500
MAX_LABEL_LEN = 120
MAX_DESCRIPTION_LEN = 2000


# ---------------------------------------------------------------- errors

class ThemeModelError(ValueError):
    """model level の fail closed。`code` は機械可読（A3 §7 / §23 の code と整合）。"""

    def __init__(self, code: str, message: str = "") -> None:
        self.code = code
        super().__init__(f"{code}: {message}" if message else code)


def _fail(code: str, message: str = "") -> None:
    raise ThemeModelError(code, message)


def _require(condition: bool, code: str, message: str = "") -> None:
    if not condition:
        _fail(code, message)


# ---------------------------------------------------------------- enums（凍結語彙）

class ProvenanceClass(str, Enum):
    """役割 provenance / 作成者 class / actor class（A2 §10、A3 §4 / §10 / §12）。"""

    RULE = "RULE"
    HUMAN = "HUMAN"
    LLM_PROPOSAL = "LLM_PROPOSAL"


class AssertionProvenance(str, Enum):
    """機構 component の主張 provenance（A2 §11）。SOURCE_CLAIM は evidence 参照必須。"""

    HUMAN = "HUMAN"
    RULE = "RULE"
    LLM_PROPOSAL = "LLM_PROPOSAL"
    SOURCE_CLAIM = "SOURCE_CLAIM"


class MechanismCertainty(str, Enum):
    """A1 §12.1 の 4 値。順序・数値 rank・平均は存在しない。
    EXPLICIT_SOURCE_CAUSAL_CLAIM は HYPOTHESIZED_MECHANISM より「上」ではない（attribution）。"""

    OBSERVED_ASSOCIATION = "OBSERVED_ASSOCIATION"
    HYPOTHESIZED_MECHANISM = "HYPOTHESIZED_MECHANISM"
    EVIDENCE_SUPPORTED_MECHANISM = "EVIDENCE_SUPPORTED_MECHANISM"
    EXPLICIT_SOURCE_CAUSAL_CLAIM = "EXPLICIT_SOURCE_CAUSAL_CLAIM"


class ComponentType(str, Enum):
    DRIVER = "DRIVER"
    TRANSMISSION_CHANNEL = "TRANSMISSION_CHANNEL"
    AFFECTED_DOMAIN = "AFFECTED_DOMAIN"
    EXPECTED_OBSERVABLE_CONSEQUENCE = "EXPECTED_OBSERVABLE_CONSEQUENCE"


class ExpectedChange(str, Enum):
    """定性的な期待変化（A2 §11）。価格 target・horizon・正誤ではない。"""

    INCREASE = "INCREASE"
    DECREASE = "DECREASE"
    WIDEN = "WIDEN"
    NARROW = "NARROW"
    ELEVATED = "ELEVATED"
    DEPRESSED = "DEPRESSED"
    UNSPECIFIED = "UNSPECIFIED"


class ScopeDimension(str, Enum):
    REGION = "REGION"
    INDUSTRY = "INDUSTRY"
    ASSET_CLASS = "ASSET_CLASS"
    PERIOD_FRAME = "PERIOD_FRAME"


#: PERIOD_FRAME の予約値。A1 Q4（単一 event / 単一 session は Theme ではない）。model は保持できるが資格判定で
#: DOES_NOT_QUALIFY になる（`qualification.evaluate_qualification`）。
SINGLE_PERIOD_FRAMES = ("single_session", "single_event")


class LimitationCategory(str, Enum):
    SCOPE_LIMIT = "SCOPE_LIMIT"
    DATA_GAP = "DATA_GAP"
    CONFOUNDER = "CONFOUNDER"
    MEASUREMENT = "MEASUREMENT"
    OTHER = "OTHER"


class EvidenceKind(str, Enum):
    """付与可能な evidence kind（A2 §6）。CONTEXT_ITEM は後続 gate まで存在しない（PROHIBITED_EVIDENCE_KIND）。"""

    FACT = "FACT"
    OBSERVATION = "OBSERVATION"
    SOURCE_DOCUMENT = "SOURCE_DOCUMENT"
    NEWS_ITEM = "NEWS_ITEM"
    STATEMENT = "STATEMENT"


#: 付与を明示的に禁止する kind 名（enum 外。from_dict で専用 code を返すため）
PROHIBITED_EVIDENCE_KINDS = ("CONTEXT_ITEM",)


class EvidenceAuthorityClass(str, Enum):
    """A2 §5 の 4 class。attachment に許されるのは PRIMARY_OBSERVATIONAL のみ（Phase 6。A3 §7）。"""

    PRIMARY_OBSERVATIONAL = "PRIMARY_OBSERVATIONAL"
    DERIVED_INTERPRETIVE = "DERIVED_INTERPRETIVE"
    PROPOSAL_ONLY = "PROPOSAL_ONLY"
    NOT_THEME_EVIDENCE = "NOT_THEME_EVIDENCE"


class EvidenceRole(str, Enum):
    """A2 §9。TRIGGER は role ではなく flag（`EvidenceAttachment.is_trigger`）。"""

    SUPPORTS = "SUPPORTS"
    CONTRADICTS = "CONTRADICTS"
    CONTEXT = "CONTEXT"
    INVALIDATES = "INVALIDATES"


class EvidenceTimeBasis(str, Enum):
    """EVIDENCE_TIME の由来（A2 §7）。retrieved_at / ingestion / created_at は存在しない（代替禁止）。"""

    KNOWN_AT = "KNOWN_AT"          # Fact.time.known_at
    AS_OF = "AS_OF"                # Observation.as_of
    PUBLISHED_AT = "PUBLISHED_AT"  # SourceDocument / NewsItem.published_at（Statement は link 先文書）
    EVENT_TIME = "EVENT_TIME"      # Statement.event_time
    NONE = "NONE"                  # quality MISSING のときのみ


class EvidenceTimeQuality(str, Enum):
    RELIABLE = "RELIABLE"
    DECLARED = "DECLARED"    # Fact 層の宣言を採用（basis を本層で検証できない）
    INFERRED = "INFERRED"    # published_inferred（limited_use 必須）
    MISSING = "MISSING"      # CONTEXT のみ・資格非算入


#: kind ごとに許される basis（A2 §7 の表）
EVIDENCE_TIME_BASIS_BY_KIND: Mapping[EvidenceKind, Tuple[EvidenceTimeBasis, ...]] = {
    EvidenceKind.FACT: (EvidenceTimeBasis.KNOWN_AT,),
    EvidenceKind.OBSERVATION: (EvidenceTimeBasis.AS_OF,),
    EvidenceKind.SOURCE_DOCUMENT: (EvidenceTimeBasis.PUBLISHED_AT,),
    EvidenceKind.NEWS_ITEM: (EvidenceTimeBasis.PUBLISHED_AT,),
    EvidenceKind.STATEMENT: (EvidenceTimeBasis.EVENT_TIME, EvidenceTimeBasis.PUBLISHED_AT),
}

#: kind ごとに許される quality（A2 §7 の表）
EVIDENCE_TIME_QUALITY_BY_KIND: Mapping[EvidenceKind, Tuple[EvidenceTimeQuality, ...]] = {
    EvidenceKind.FACT: (EvidenceTimeQuality.RELIABLE, EvidenceTimeQuality.DECLARED, EvidenceTimeQuality.MISSING),
    EvidenceKind.OBSERVATION: (EvidenceTimeQuality.RELIABLE,),
    EvidenceKind.SOURCE_DOCUMENT: (EvidenceTimeQuality.RELIABLE, EvidenceTimeQuality.INFERRED,
                                   EvidenceTimeQuality.MISSING),
    EvidenceKind.NEWS_ITEM: (EvidenceTimeQuality.RELIABLE, EvidenceTimeQuality.INFERRED,
                             EvidenceTimeQuality.MISSING),
    EvidenceKind.STATEMENT: (EvidenceTimeQuality.RELIABLE, EvidenceTimeQuality.DECLARED,
                             EvidenceTimeQuality.INFERRED, EvidenceTimeQuality.MISSING),
}

#: kind ごとの ref_id prefix（現行 primitive の id 規約。A2 §1）
REF_ID_PREFIX_BY_KIND: Mapping[EvidenceKind, str] = {
    EvidenceKind.FACT: "fact_",
    EvidenceKind.OBSERVATION: "obs_",
    EvidenceKind.SOURCE_DOCUMENT: "doc_",
    EvidenceKind.NEWS_ITEM: "news_",
    EvidenceKind.STATEMENT: "",  # producer 未確定（現ブランチに producer なし）
}


class OriginKind(str, Enum):
    """source origin の種別（A2 §8）。UNKNOWN は決して独立 origin に数えない。"""

    MARKET_SERIES = "MARKET_SERIES"        # (source_id, series_id)
    OFFICIAL_RELEASE = "OFFICIAL_RELEASE"  # 元 publisher の release / record
    PUBLISHER_ARTICLE = "PUBLISHER_ARTICLE"  # article identity（転載は同一）
    DERIVED = "DERIVED"                    # 入力 origin の和集合（lineage_refs で表す）
    UNKNOWN = "UNKNOWN"


class ThemeEntityKind(str, Enum):
    """entity typed reference の kind。`databank.news_model.EntityKind` と同じ値集合（import せず鏡像。test で一致検証）。"""

    COUNTRY = "country"
    COMPANY = "company"
    TICKER = "ticker"
    SECTOR = "sector"
    INDUSTRY = "industry"
    COMMODITY = "commodity"
    CURRENCY = "currency"
    CENTRAL_BANK = "central_bank"
    INDEX = "index"
    GOVERNMENT = "government"
    PERSON = "person"


class EntityLinkClass(str, Enum):
    """A2 §13。observation の semantic content に入るのは INFERRED_EXPOSURE のみ。
    DIRECTLY_EVIDENCED は DERIVED（`qualification.directly_evidenced_links`）、
    TAXONOMIC_ASSOCIATION は metadata（ThemeMetadataRecord の TAXONOMY）。"""

    DIRECTLY_EVIDENCED = "DIRECTLY_EVIDENCED"
    INFERRED_EXPOSURE = "INFERRED_EXPOSURE"
    TAXONOMIC_ASSOCIATION = "TAXONOMIC_ASSOCIATION"


class ExposureKind(str, Enum):
    BENEFICIARY = "BENEFICIARY"
    ADVERSELY_EXPOSED = "ADVERSELY_EXPOSED"
    MIXED = "MIXED"
    UNSPECIFIED = "UNSPECIFIED"


class ExposureUncertainty(str, Enum):
    """推定 exposure の不確実性 class（数値でない。A2 §13）。"""

    HYPOTHESIZED = "HYPOTHESIZED"
    PARTIALLY_EVIDENCED = "PARTIALLY_EVIDENCED"
    SOURCE_ASSERTED = "SOURCE_ASSERTED"


class CreationMethod(str, Enum):
    CANDIDATE = "CANDIDATE"
    MERGE_RESULT = "MERGE_RESULT"
    SPLIT_RESULT = "SPLIT_RESULT"
    SUCCESSOR_RESULT = "SUCCESSOR_RESULT"


class GovernanceEventType(str, Enum):
    """A3 §10.1 の最小集合。lifecycle 状態名は P6-C（語彙 version の追加で拡張）。"""

    CANDIDATE_ACCEPTED = "CANDIDATE_ACCEPTED"
    CANDIDATE_REJECTED = "CANDIDATE_REJECTED"
    RETIRED = "RETIRED"
    REOPENED = "REOPENED"
    MERGE = "MERGE"
    SPLIT = "SPLIT"
    SUPERSEDED_BY_ROOT = "SUPERSEDED_BY_ROOT"
    ROLE_CORRECTION_APPROVED = "ROLE_CORRECTION_APPROVED"
    CERTAINTY_CHANGE_APPROVED = "CERTAINTY_CHANGE_APPROVED"
    METADATA_CORRECTION_APPROVED = "METADATA_CORRECTION_APPROVED"
    EVENT_REVERSED = "EVENT_REVERSED"


class MetadataField(str, Enum):
    LABEL = "LABEL"
    DESCRIPTION = "DESCRIPTION"
    TAXONOMY = "TAXONOMY"
    ALIAS = "ALIAS"


#: 集合 snapshot として保持する metadata field（A3 §12）
SET_VALUED_METADATA_FIELDS = (MetadataField.TAXONOMY, MetadataField.ALIAS)


class MappingRole(str, Enum):
    CONFIRMATION_CANDIDATE = "CONFIRMATION_CANDIDATE"
    DRIVER_PROXY = "DRIVER_PROXY"
    DOMAIN_PROXY = "DOMAIN_PROXY"


class ExpectedRelation(str, Enum):
    """mapping の定性的期待関係（A2 §14）。評価・calibration・prediction target ではない。"""

    SAME_DIRECTION = "SAME_DIRECTION"
    OPPOSITE_DIRECTION = "OPPOSITE_DIRECTION"
    UNSPECIFIED = "UNSPECIFIED"


# ---------------------------------------------------------------- 機構語彙（mechanism_vocabulary:0.1.0）

OTHER_CATEGORY = "OTHER"

#: 小さく version 付きの管理語彙（A2 §11。shape は凍結、内容は語彙 version で拡張。企業名・銘柄名は含めない）
MECHANISM_CATEGORIES: Mapping[ComponentType, Tuple[str, ...]] = {
    ComponentType.DRIVER: (
        "POLICY_RATE", "FX_RATE", "COMMODITY_PRICE", "DEMAND_SHIFT", "SUPPLY_CONSTRAINT",
        "REGULATION", "TECHNOLOGY_ADOPTION", "FISCAL_POLICY", "CAPITAL_FLOW", OTHER_CATEGORY),
    ComponentType.TRANSMISSION_CHANNEL: (
        "INPUT_COST", "PRICING_POWER", "VOLUME_DEMAND", "CAPEX_CYCLE", "CREDIT_CONDITIONS",
        "TRADE_FLOW", "EARNINGS_REVISION", "VALUATION_DISCOUNT_RATE", OTHER_CATEGORY),
    ComponentType.AFFECTED_DOMAIN: (
        "SECTOR", "INDUSTRY", "ASSET_CLASS", "REGION", "MACRO_AGGREGATE", "INSTRUMENT_GROUP", OTHER_CATEGORY),
    ComponentType.EXPECTED_OBSERVABLE_CONSEQUENCE: (
        "PRICE_LEVEL", "RETURN_SPREAD", "VOLUME", "FLOW", "MACRO_STATISTIC", "EARNINGS_METRIC",
        "CREDIT_SPREAD", "VOLATILITY", "PUBLICATION_EVENT", OTHER_CATEGORY),
}


# ---------------------------------------------------------------- 正規化 / 検査 helper

_WS_RE = re.compile(r"\s+")
_DRIVE_PATH_RE = re.compile(r"(?:^|[\s\"'(\[])[A-Za-z]:[\\/]")
_UNC_PATH_RE = re.compile(r"\\\\[^\\\s]+\\")
_USERINFO_URL_RE = re.compile(r"://[^/\s]*@")
_SECRET_QUERY_RE = re.compile(r"[?&](?:token|key|api_key|apikey|password|secret|signature|sig)=", re.IGNORECASE)


def normalize_text(value: str) -> str:
    """NFKC → 空白圧縮 → strip → casefold（A2 §11 の normalized_statement / subject 規約）。"""
    return _WS_RE.sub(" ", unicodedata.normalize("NFKC", value)).strip().casefold()


def _check_prohibited_content(value: str, name: str) -> None:
    """credential 付き URL・secret query・機械固有 path を semantic / metadata field に入れない（A3 §7 / §25）。"""
    if (_USERINFO_URL_RE.search(value) or _SECRET_QUERY_RE.search(value)
            or _DRIVE_PATH_RE.search(value) or _UNC_PATH_RE.search(value)):
        _fail("PROHIBITED_CONTENT", f"{name} contains a credential-bearing URL or machine-specific path")


def _text(value: object, name: str, *, max_len: int, required: bool = False,
          normalized: bool = False) -> str:
    _require(isinstance(value, str), "INVALID_TYPE", f"{name} must be str")
    text = str(value)
    if required:
        _require(text != "", "MISSING_FIELD", f"{name} is required")
    _require(len(text) <= max_len, "FIELD_TOO_LONG", f"{name} exceeds {max_len} characters")
    _require("\n" not in text and "\r" not in text, "INVALID_TEXT", f"{name} must be single-line")
    if text:
        _check_prohibited_content(text, name)
    if normalized and text:
        _require(text == normalize_text(text), "NOT_NORMALIZED",
                 f"{name} must be normalized (NFKC / casefold / collapsed whitespace)")
    return text


def _key(value: object, name: str) -> str:
    _require(isinstance(value, str) and bool(_KEY_RE.match(str(value))), "INVALID_KEY",
             f"{name} must match [a-z0-9][a-z0-9_.:-]{{0,63}}")
    return str(value)


def _aware(value: object, name: str) -> datetime:
    _require(isinstance(value, datetime), "INVALID_TYPE", f"{name} must be datetime")
    try:
        return ensure_aware(value, name)  # type: ignore[arg-type]
    except ValueError as exc:
        raise ThemeModelError("NAIVE_DATETIME", str(exc)) from None


def _canonical_date(value: object, name: str) -> str:
    _require(isinstance(value, str) and bool(_DATE_RE.match(str(value))), "INVALID_DATE",
             f"{name} must be YYYY-MM-DD")
    try:
        parsed = date.fromisoformat(str(value))
    except ValueError:
        _fail("INVALID_DATE", f"{name} is not a calendar date")
    _require(parsed.isoformat() == value, "INVALID_DATE", f"{name} must be canonical YYYY-MM-DD")
    return str(value)


def _sorted_unique(values: object, name: str, *, max_len: int = MAX_REF_LEN) -> Tuple[str, ...]:
    _require(isinstance(values, (tuple, list, frozenset, set)), "INVALID_TYPE",
             f"{name} must be a collection of str")
    out = set()
    for item in values:  # type: ignore[union-attr]
        out.add(_text(item, name, max_len=max_len, required=True))
    return tuple(sorted(out))


def _enum(value: object, enum_cls: type, name: str):
    if isinstance(value, enum_cls):
        return value
    _fail("INVALID_VOCABULARY", f"{name} must be {enum_cls.__name__}, got {value!r}")


def _parse_enum(value: object, enum_cls: type, name: str):
    try:
        return enum_cls(str(value))
    except ValueError:
        if enum_cls is EvidenceKind and str(value) in PROHIBITED_EVIDENCE_KINDS:
            _fail("PROHIBITED_EVIDENCE_KIND", f"{value} is not attachable in Phase 6")
        _fail("INVALID_VOCABULARY", f"{name}: unknown {enum_cls.__name__} value {value!r}")


def is_root_id(value: object) -> bool:
    return isinstance(value, str) and bool(_ROOT_ID_RE.match(value))


def is_content_id(value: object, prefix: str) -> bool:
    return isinstance(value, str) and bool(_CONTENT_ID_RE[prefix].match(value))


def _root_id(value: object, name: str) -> str:
    _require(is_root_id(value), "INVALID_ROOT_ID", f"{name} must be theme_<ULID>, got {value!r}")
    return str(value)


def _content_ref(value: object, prefix: str, name: str, *, required: bool) -> str:
    if value == "" and not required:
        return ""
    _require(is_content_id(value, prefix), "INVALID_RECORD_ID",
             f"{name} must be {prefix}_<24 hex>, got {value!r}")
    return str(value)


def new_root_id(now: Optional[datetime] = None) -> str:
    """不透明な root id を生成する（A2 §3: 生成 id。内容から導出しない）。

    唯一の生成 primitive。validator からは呼ばれない。`now` は test の時刻順検証用（乱数部は残る）。
    """
    return new_id(ROOT_ID_PREFIX, now)


# ---------------------------------------------------------------- canonical 直列化

def _as_json(value):
    """JSON 互換の決定論的値へ変換する（dataclass → dict、Enum → value、datetime → UTC ISO、tuple → list）。"""
    if is_dataclass(value) and not isinstance(value, type):
        return {f.name: _as_json(getattr(value, f.name)) for f in fields(value)}
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, datetime):
        return to_utc_iso(value)
    if isinstance(value, (tuple, list)):
        return [_as_json(v) for v in value]
    if isinstance(value, Mapping):
        return {str(k): _as_json(v) for k, v in value.items()}
    if value is None or isinstance(value, (str, int, bool)):
        return value
    raise ThemeModelError("NON_CANONICAL_RECORD", f"unsupported value type {type(value).__name__}")


def canonical_json(payload) -> str:
    """P5 と同じ canonical JSON（sort_keys / compact separators / ensure_ascii=False）。"""
    return json.dumps(_as_json(payload), ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def canonical_line(record) -> str:
    """canonical 1 行（`\\n` 終端）。store（A4b）が append する bytes の定義。"""
    return canonical_json(record.as_dict()) + "\n"


def record_digest(record) -> str:
    """canonical 行全体の digest（conflict 検出用）。root_id とは別物であり identity ではない。"""
    return content_id("thdigest", canonical_line(record))


def _sort_canonical(items: Iterable) -> Tuple:
    return tuple(sorted(items, key=lambda item: canonical_json(item)))


def _reject_unknown(data: Mapping[str, object], cls: type) -> None:
    known = {f.name for f in fields(cls)}
    unknown = sorted(set(data) - known)
    _require(not unknown, "UNKNOWN_FIELDS", f"unknown {cls.__name__} fields: {unknown}")


def _str(data: Mapping[str, object], key: str, default: str = "") -> str:
    value = data.get(key, default)
    return default if value is None else str(value)


def _bool(data: Mapping[str, object], key: str) -> bool:
    value = data.get(key, False)
    _require(isinstance(value, bool), "INVALID_TYPE", f"{key} must be bool")
    return bool(value)


# ---------------------------------------------------------------- semantic components

@dataclass(frozen=True, kw_only=True)
class EntityRef:
    """entity の typed reference（A2 §13）。entity catalog を前提にしない。"""

    kind: ThemeEntityKind
    value: str

    def __post_init__(self) -> None:
        _enum(self.kind, ThemeEntityKind, "EntityRef.kind")
        object.__setattr__(self, "value", _text(self.value, "EntityRef.value", max_len=MAX_REF_LEN, required=True))

    @classmethod
    def from_dict(cls, data: Mapping[str, object]) -> "EntityRef":
        _reject_unknown(data, cls)
        return cls(kind=_parse_enum(data.get("kind"), ThemeEntityKind, "EntityRef.kind"), value=_str(data, "value"))


@dataclass(frozen=True, kw_only=True)
class ThemeSubject:
    """主題（A1 §6 A）。normalized_subject は正規化済み（`normalize_text`）であること。"""

    normalized_subject: str
    typed_reference: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(self, "normalized_subject", _text(
            self.normalized_subject, "ThemeSubject.normalized_subject", max_len=MAX_STATEMENT_LEN,
            required=True, normalized=True))
        object.__setattr__(self, "typed_reference", _text(
            self.typed_reference, "ThemeSubject.typed_reference", max_len=MAX_REF_LEN))

    @classmethod
    def from_dict(cls, data: Mapping[str, object]) -> "ThemeSubject":
        _reject_unknown(data, cls)
        return cls(normalized_subject=_str(data, "normalized_subject"), typed_reference=_str(data, "typed_reference"))


@dataclass(frozen=True, kw_only=True)
class ScopeToken:
    dimension: ScopeDimension
    value: str

    def __post_init__(self) -> None:
        _enum(self.dimension, ScopeDimension, "ScopeToken.dimension")
        object.__setattr__(self, "value", _text(self.value, "ScopeToken.value", max_len=MAX_REF_LEN,
                                                required=True, normalized=True))

    @classmethod
    def from_dict(cls, data: Mapping[str, object]) -> "ScopeToken":
        _reject_unknown(data, cls)
        return cls(dimension=_parse_enum(data.get("dimension"), ScopeDimension, "ScopeToken.dimension"),
                   value=_str(data, "value"))


def _check_assertion(provenance: object, ref: object, name: str) -> Tuple[AssertionProvenance, str]:
    prov = _enum(provenance, AssertionProvenance, f"{name}.assertion_provenance")
    ref_text = _text(ref, f"{name}.provenance_ref", max_len=MAX_REF_LEN)
    if prov in (AssertionProvenance.RULE, AssertionProvenance.LLM_PROPOSAL, AssertionProvenance.SOURCE_CLAIM):
        _require(ref_text != "", "MISSING_PROVENANCE", f"{name}: {prov.value} requires provenance_ref")
    return prov, ref_text


def _check_category(component_type: ComponentType, category: object, statement: str, name: str) -> str:
    _require(isinstance(category, str) and category in MECHANISM_CATEGORIES[component_type], "INVALID_VOCABULARY",
             f"{name}: category {category!r} is not in {MECHANISM_VOCABULARY_VERSION} for {component_type.value}")
    if category == OTHER_CATEGORY:
        _require(statement != "", "MISSING_FIELD", f"{name}: category OTHER requires normalized_statement")
    return str(category)


@dataclass(frozen=True, kw_only=True)
class MechanismComponent:
    """DRIVER / TRANSMISSION_CHANNEL / AFFECTED_DOMAIN（A2 §11）。prose ではなく型付き component。"""

    component_type: ComponentType
    component_key: str
    category: str
    typed_reference: str = ""
    normalized_statement: str = ""
    assertion_provenance: AssertionProvenance
    provenance_ref: str = ""

    def __post_init__(self) -> None:
        _enum(self.component_type, ComponentType, "MechanismComponent.component_type")
        _require(self.component_type is not ComponentType.EXPECTED_OBSERVABLE_CONSEQUENCE, "INVALID_MECHANISM",
                 "consequences are ExpectedConsequence, not MechanismComponent")
        object.__setattr__(self, "component_key", _key(self.component_key, "MechanismComponent.component_key"))
        object.__setattr__(self, "typed_reference", _text(self.typed_reference, "MechanismComponent.typed_reference",
                                                          max_len=MAX_REF_LEN))
        object.__setattr__(self, "normalized_statement", _text(
            self.normalized_statement, "MechanismComponent.normalized_statement", max_len=MAX_STATEMENT_LEN,
            normalized=True))
        object.__setattr__(self, "category", _check_category(self.component_type, self.category,
                                                             self.normalized_statement, "MechanismComponent"))
        prov, ref = _check_assertion(self.assertion_provenance, self.provenance_ref, "MechanismComponent")
        object.__setattr__(self, "assertion_provenance", prov)
        object.__setattr__(self, "provenance_ref", ref)

    @classmethod
    def from_dict(cls, data: Mapping[str, object]) -> "MechanismComponent":
        _reject_unknown(data, cls)
        return cls(
            component_type=_parse_enum(data.get("component_type"), ComponentType, "component_type"),
            component_key=_str(data, "component_key"), category=_str(data, "category"),
            typed_reference=_str(data, "typed_reference"), normalized_statement=_str(data, "normalized_statement"),
            assertion_provenance=_parse_enum(data.get("assertion_provenance"), AssertionProvenance,
                                             "assertion_provenance"),
            provenance_ref=_str(data, "provenance_ref"))


@dataclass(frozen=True, kw_only=True)
class ExpectedConsequence:
    """EXPECTED_OBSERVABLE_CONSEQUENCE（A2 §11）。observable_target は必須。価格 target / horizon / 正誤は持たない。"""

    component_key: str
    category: str
    observable_target: str
    expected_change: ExpectedChange
    normalized_statement: str = ""
    assertion_provenance: AssertionProvenance
    provenance_ref: str = ""

    component_type: ComponentType = ComponentType.EXPECTED_OBSERVABLE_CONSEQUENCE

    def __post_init__(self) -> None:
        _require(self.component_type is ComponentType.EXPECTED_OBSERVABLE_CONSEQUENCE, "INVALID_MECHANISM",
                 "ExpectedConsequence.component_type is fixed")
        object.__setattr__(self, "component_key", _key(self.component_key, "ExpectedConsequence.component_key"))
        object.__setattr__(self, "observable_target", _text(
            self.observable_target, "ExpectedConsequence.observable_target", max_len=MAX_REF_LEN, required=True))
        _enum(self.expected_change, ExpectedChange, "ExpectedConsequence.expected_change")
        object.__setattr__(self, "normalized_statement", _text(
            self.normalized_statement, "ExpectedConsequence.normalized_statement", max_len=MAX_STATEMENT_LEN,
            normalized=True))
        object.__setattr__(self, "category", _check_category(
            ComponentType.EXPECTED_OBSERVABLE_CONSEQUENCE, self.category, self.normalized_statement,
            "ExpectedConsequence"))
        prov, ref = _check_assertion(self.assertion_provenance, self.provenance_ref, "ExpectedConsequence")
        object.__setattr__(self, "assertion_provenance", prov)
        object.__setattr__(self, "provenance_ref", ref)

    @classmethod
    def from_dict(cls, data: Mapping[str, object]) -> "ExpectedConsequence":
        _reject_unknown(data, cls)
        component_type = _parse_enum(data.get("component_type", ComponentType.EXPECTED_OBSERVABLE_CONSEQUENCE.value),
                                     ComponentType, "component_type")
        return cls(
            component_key=_str(data, "component_key"), category=_str(data, "category"),
            observable_target=_str(data, "observable_target"),
            expected_change=_parse_enum(data.get("expected_change"), ExpectedChange, "expected_change"),
            normalized_statement=_str(data, "normalized_statement"),
            assertion_provenance=_parse_enum(data.get("assertion_provenance"), AssertionProvenance,
                                             "assertion_provenance"),
            provenance_ref=_str(data, "provenance_ref"), component_type=component_type)


def _typed_components(items: object, component_type: ComponentType, name: str) -> Tuple[MechanismComponent, ...]:
    _require(isinstance(items, (tuple, list)), "INVALID_TYPE", f"Mechanism.{name} must be a tuple")
    out: List[MechanismComponent] = []
    for item in items:  # type: ignore[union-attr]
        _require(isinstance(item, MechanismComponent), "INVALID_TYPE", f"Mechanism.{name} items must be MechanismComponent")
        _require(item.component_type is component_type, "INVALID_MECHANISM",
                 f"Mechanism.{name} contains a {item.component_type.value} component")
        out.append(item)
    _require(len(out) >= 1, "INVALID_MECHANISM", f"Mechanism.{name} requires at least one component")
    return _sort_canonical(out)


@dataclass(frozen=True, kw_only=True)
class Mechanism:
    """driver → transmission channel → affected domain → expected observable consequences（A1 §12 / A2 §11）。各 ≥ 1。"""

    drivers: Tuple[MechanismComponent, ...]
    channels: Tuple[MechanismComponent, ...]
    domains: Tuple[MechanismComponent, ...]
    consequences: Tuple[ExpectedConsequence, ...]

    def __post_init__(self) -> None:
        object.__setattr__(self, "drivers", _typed_components(self.drivers, ComponentType.DRIVER, "drivers"))
        object.__setattr__(self, "channels", _typed_components(self.channels, ComponentType.TRANSMISSION_CHANNEL,
                                                               "channels"))
        object.__setattr__(self, "domains", _typed_components(self.domains, ComponentType.AFFECTED_DOMAIN, "domains"))
        _require(isinstance(self.consequences, (tuple, list)), "INVALID_TYPE", "Mechanism.consequences must be a tuple")
        consequences = tuple(self.consequences)
        _require(all(isinstance(c, ExpectedConsequence) for c in consequences), "INVALID_TYPE",
                 "Mechanism.consequences items must be ExpectedConsequence")
        _require(len(consequences) >= 1, "MISSING_OBSERVABLE_CONSEQUENCE",
                 "a mechanism without expected observable consequences is unfalsifiable (A1 Q6)")
        object.__setattr__(self, "consequences", _sort_canonical(consequences))
        keys = [c.component_key for c in self.all_components()]
        _require(len(keys) == len(set(keys)), "DUPLICATE_KEY", "mechanism component keys must be unique")

    def all_components(self) -> Tuple[object, ...]:
        return tuple(self.drivers) + tuple(self.channels) + tuple(self.domains) + tuple(self.consequences)

    @property
    def consequence_keys(self) -> Tuple[str, ...]:
        return tuple(c.component_key for c in self.consequences)

    @classmethod
    def from_dict(cls, data: Mapping[str, object]) -> "Mechanism":
        _reject_unknown(data, cls)
        return cls(
            drivers=tuple(MechanismComponent.from_dict(d) for d in (data.get("drivers") or ())),
            channels=tuple(MechanismComponent.from_dict(d) for d in (data.get("channels") or ())),
            domains=tuple(MechanismComponent.from_dict(d) for d in (data.get("domains") or ())),
            consequences=tuple(ExpectedConsequence.from_dict(d) for d in (data.get("consequences") or ())))


@dataclass(frozen=True, kw_only=True)
class Limitation:
    """Theme 記述自体の既知の弱点（A2 §15）。typed item。"""

    category: LimitationCategory
    normalized_statement: str

    def __post_init__(self) -> None:
        _enum(self.category, LimitationCategory, "Limitation.category")
        object.__setattr__(self, "normalized_statement", _text(
            self.normalized_statement, "Limitation.normalized_statement", max_len=MAX_STATEMENT_LEN,
            required=True, normalized=True))

    @classmethod
    def from_dict(cls, data: Mapping[str, object]) -> "Limitation":
        _reject_unknown(data, cls)
        return cls(category=_parse_enum(data.get("category"), LimitationCategory, "Limitation.category"),
                   normalized_statement=_str(data, "normalized_statement"))


@dataclass(frozen=True, kw_only=True)
class InvalidationCondition:
    """何が観測されれば Theme が弱まる / 崩れるか（A1 Q6 / A2 §15）。INVALIDATES attachment が condition_key で参照する。"""

    condition_key: str
    normalized_statement: str
    observable_target: str = ""
    expected_change: ExpectedChange = ExpectedChange.UNSPECIFIED

    def __post_init__(self) -> None:
        object.__setattr__(self, "condition_key", _key(self.condition_key, "InvalidationCondition.condition_key"))
        object.__setattr__(self, "normalized_statement", _text(
            self.normalized_statement, "InvalidationCondition.normalized_statement", max_len=MAX_STATEMENT_LEN,
            required=True, normalized=True))
        object.__setattr__(self, "observable_target", _text(
            self.observable_target, "InvalidationCondition.observable_target", max_len=MAX_REF_LEN))
        _enum(self.expected_change, ExpectedChange, "InvalidationCondition.expected_change")

    @classmethod
    def from_dict(cls, data: Mapping[str, object]) -> "InvalidationCondition":
        _reject_unknown(data, cls)
        return cls(condition_key=_str(data, "condition_key"), normalized_statement=_str(data, "normalized_statement"),
                   observable_target=_str(data, "observable_target"),
                   expected_change=_parse_enum(data.get("expected_change", ExpectedChange.UNSPECIFIED.value),
                                               ExpectedChange, "expected_change"))


@dataclass(frozen=True, kw_only=True)
class InferredExposureLink:
    """INFERRED_EXPOSURE_LINK（A2 §13）。semantic content（identity core 外）。推奨ではない（BUY / SELL / weight なし）。"""

    entity: EntityRef
    exposure_kind: ExposureKind
    uncertainty: ExposureUncertainty
    provenance_class: ProvenanceClass
    provenance_ref: str = ""
    note: str = ""

    link_class: EntityLinkClass = EntityLinkClass.INFERRED_EXPOSURE

    def __post_init__(self) -> None:
        _require(isinstance(self.entity, EntityRef), "INVALID_TYPE", "InferredExposureLink.entity must be EntityRef")
        _enum(self.exposure_kind, ExposureKind, "InferredExposureLink.exposure_kind")
        _enum(self.uncertainty, ExposureUncertainty, "InferredExposureLink.uncertainty")
        _enum(self.provenance_class, ProvenanceClass, "InferredExposureLink.provenance_class")
        _require(self.link_class is EntityLinkClass.INFERRED_EXPOSURE, "INVALID_VOCABULARY",
                 "only INFERRED_EXPOSURE links are observation semantic content (A2 §13)")
        object.__setattr__(self, "provenance_ref", _text(self.provenance_ref, "InferredExposureLink.provenance_ref",
                                                         max_len=MAX_REF_LEN))
        if self.provenance_class in (ProvenanceClass.RULE, ProvenanceClass.LLM_PROPOSAL):
            _require(self.provenance_ref != "", "MISSING_PROVENANCE",
                     f"InferredExposureLink: {self.provenance_class.value} requires provenance_ref")
        object.__setattr__(self, "note", _text(self.note, "InferredExposureLink.note", max_len=MAX_NOTE_LEN))

    @classmethod
    def from_dict(cls, data: Mapping[str, object]) -> "InferredExposureLink":
        _reject_unknown(data, cls)
        return cls(
            entity=EntityRef.from_dict(data.get("entity") or {}),
            exposure_kind=_parse_enum(data.get("exposure_kind"), ExposureKind, "exposure_kind"),
            uncertainty=_parse_enum(data.get("uncertainty"), ExposureUncertainty, "uncertainty"),
            provenance_class=_parse_enum(data.get("provenance_class"), ProvenanceClass, "provenance_class"),
            provenance_ref=_str(data, "provenance_ref"), note=_str(data, "note"),
            link_class=_parse_enum(data.get("link_class", EntityLinkClass.INFERRED_EXPOSURE.value), EntityLinkClass,
                                   "link_class"))


# ---------------------------------------------------------------- evidence attachment

@dataclass(frozen=True, kw_only=True)
class SourceOrigin:
    """出所 identity（A2 §8）。独立性判定の材料であり、判定は `qualification` の純関数が行う。

    origin_key: 同一 origin を束ねる canonical key（例 "article:<article_id>"、"series:<source_id>/<series_id>"、
                "release:<source_id>/<doc_id>"、"derived:<fact_id>"）。UNKNOWN では空。
    lineage_refs: 上流 record id（derived の inputs、Fact の元 observation、article の member document、revision_of 等）。
    """

    origin_kind: OriginKind
    origin_key: str = ""
    source_ids: Tuple[str, ...] = ()
    publisher: str = ""
    lineage_refs: Tuple[str, ...] = ()

    def __post_init__(self) -> None:
        _enum(self.origin_kind, OriginKind, "SourceOrigin.origin_kind")
        object.__setattr__(self, "origin_key", _text(self.origin_key, "SourceOrigin.origin_key", max_len=MAX_REF_LEN))
        if self.origin_kind is OriginKind.UNKNOWN:
            _require(self.origin_key == "", "INVALID_ORIGIN", "UNKNOWN origin must not carry an origin_key")
        else:
            _require(self.origin_key != "", "INVALID_ORIGIN", f"{self.origin_kind.value} origin requires origin_key")
        object.__setattr__(self, "source_ids", _sorted_unique(self.source_ids, "SourceOrigin.source_ids"))
        object.__setattr__(self, "publisher", _text(self.publisher, "SourceOrigin.publisher", max_len=MAX_REF_LEN))
        object.__setattr__(self, "lineage_refs", _sorted_unique(self.lineage_refs, "SourceOrigin.lineage_refs"))
        if self.origin_kind is OriginKind.DERIVED:
            _require(len(self.lineage_refs) >= 1, "INVALID_ORIGIN", "DERIVED origin requires lineage_refs (inputs)")

    @property
    def is_known(self) -> bool:
        return self.origin_kind is not OriginKind.UNKNOWN

    @classmethod
    def from_dict(cls, data: Mapping[str, object]) -> "SourceOrigin":
        _reject_unknown(data, cls)
        return cls(origin_kind=_parse_enum(data.get("origin_kind"), OriginKind, "origin_kind"),
                   origin_key=_str(data, "origin_key"), source_ids=tuple(data.get("source_ids") or ()),
                   publisher=_str(data, "publisher"), lineage_refs=tuple(data.get("lineage_refs") or ()))


#: 資格判定・EVIDENCE_SUPPORTED 要件に算入する role（A2 §19）
EVIDENTIARY_ROLES = (EvidenceRole.SUPPORTS, EvidenceRole.CONTRADICTS, EvidenceRole.INVALIDATES)


@dataclass(frozen=True, kw_only=True)
class EvidenceAttachment:
    """evidence の参照（値の複製ではない。A2 §6）。1 attachment に 1 role。TRIGGER は flag。"""

    evidence_kind: EvidenceKind
    authority_class: EvidenceAuthorityClass
    ref_id: str
    source_origin: SourceOrigin
    evidence_time: Optional[datetime]
    evidence_time_basis: EvidenceTimeBasis
    evidence_time_quality: EvidenceTimeQuality
    evidence_date: str = ""                 # YYYY-MM-DD（Fact primary_date / trading_date / 公表日）。MISSING では空
    attached_at: datetime
    role: EvidenceRole
    role_provenance: ProvenanceClass
    role_asserted_by: str
    consequence_ref: str = ""
    invalidation_condition_ref: str = ""
    is_trigger: bool = False
    source_causal_claim: bool = False
    limited_use: bool = False
    qa_decision_at_attachment: str = ""
    revision_of_at_attachment: str = ""
    subject_refs: Tuple[EntityRef, ...] = ()   # evidence の subject entity の snapshot（DIRECTLY_EVIDENCED の材料）
    locator: str = ""
    excerpt: str = ""
    note: str = ""

    def __post_init__(self) -> None:
        kind = _enum(self.evidence_kind, EvidenceKind, "EvidenceAttachment.evidence_kind")
        klass = _enum(self.authority_class, EvidenceAuthorityClass, "EvidenceAttachment.authority_class")
        _require(klass is EvidenceAuthorityClass.PRIMARY_OBSERVATIONAL, "PROHIBITED_EVIDENCE_CLASS",
                 f"{klass.value} cannot be attached as Theme evidence in Phase 6 (A2 §5 / A3 §7)")
        ref_id = _text(self.ref_id, "EvidenceAttachment.ref_id", max_len=MAX_REF_LEN, required=True)
        prefix = REF_ID_PREFIX_BY_KIND[kind]
        _require(ref_id.startswith(prefix), "REF_ID_KIND_MISMATCH",
                 f"{kind.value} ref_id must start with {prefix!r}")
        object.__setattr__(self, "ref_id", ref_id)
        _require(isinstance(self.source_origin, SourceOrigin), "INVALID_TYPE",
                 "EvidenceAttachment.source_origin must be SourceOrigin")
        basis = _enum(self.evidence_time_basis, EvidenceTimeBasis, "EvidenceAttachment.evidence_time_basis")
        quality = _enum(self.evidence_time_quality, EvidenceTimeQuality, "EvidenceAttachment.evidence_time_quality")
        _require(quality in EVIDENCE_TIME_QUALITY_BY_KIND[kind], "INVALID_EVIDENCE_TIME",
                 f"{kind.value} does not admit quality {quality.value}")
        attached_at = _aware(self.attached_at, "EvidenceAttachment.attached_at")
        if quality is EvidenceTimeQuality.MISSING:
            _require(self.evidence_time is None and basis is EvidenceTimeBasis.NONE and self.evidence_date == "",
                     "INVALID_EVIDENCE_TIME", "MISSING quality requires no evidence_time / basis NONE / no date")
        else:
            _require(self.evidence_time is not None, "MISSING_EVIDENCE_TIME",
                     f"{quality.value} quality requires evidence_time")
            evidence_time = _aware(self.evidence_time, "EvidenceAttachment.evidence_time")
            _require(basis in EVIDENCE_TIME_BASIS_BY_KIND[kind], "INVALID_EVIDENCE_TIME",
                     f"{kind.value} does not admit basis {basis.value}")
            _require(evidence_time <= attached_at, "EVIDENCE_AFTER_ATTACHMENT",
                     "evidence_time must not be later than attached_at (A2 §7)")
            object.__setattr__(self, "evidence_date", _canonical_date(self.evidence_date,
                                                                      "EvidenceAttachment.evidence_date"))
        role = _enum(self.role, EvidenceRole, "EvidenceAttachment.role")
        if quality is EvidenceTimeQuality.MISSING:
            _require(role is EvidenceRole.CONTEXT, "MISSING_EVIDENCE_TIME",
                     "evidence without a reliable evidence_time may only be CONTEXT (A2 §7)")
        if quality is EvidenceTimeQuality.INFERRED:
            _require(self.limited_use is True, "INVALID_EVIDENCE_TIME",
                     "INFERRED evidence_time requires limited_use=True (A2 §7)")
        prov = _enum(self.role_provenance, ProvenanceClass, "EvidenceAttachment.role_provenance")
        object.__setattr__(self, "role_asserted_by", _text(self.role_asserted_by, "EvidenceAttachment.role_asserted_by",
                                                           max_len=MAX_REF_LEN, required=True))
        object.__setattr__(self, "consequence_ref", "" if self.consequence_ref == "" else _key(
            self.consequence_ref, "EvidenceAttachment.consequence_ref"))
        object.__setattr__(self, "invalidation_condition_ref", "" if self.invalidation_condition_ref == "" else _key(
            self.invalidation_condition_ref, "EvidenceAttachment.invalidation_condition_ref"))
        if role is EvidenceRole.INVALIDATES:
            _require(self.invalidation_condition_ref != "", "MISSING_INVALIDATION_REF",
                     "INVALIDATES requires invalidation_condition_ref (A2 §9)")
        else:
            _require(self.invalidation_condition_ref == "", "INVALID_ROLE_COMBINATION",
                     "invalidation_condition_ref is only valid with role INVALIDATES")
        for flag_name in ("is_trigger", "source_causal_claim", "limited_use"):
            _require(isinstance(getattr(self, flag_name), bool), "INVALID_TYPE", f"{flag_name} must be bool")
        if self.source_causal_claim:
            _require(kind in (EvidenceKind.SOURCE_DOCUMENT, EvidenceKind.NEWS_ITEM, EvidenceKind.STATEMENT),
                     "INVALID_ROLE_COMBINATION", "source_causal_claim requires a textual evidence kind")
        object.__setattr__(self, "qa_decision_at_attachment", _text(
            self.qa_decision_at_attachment, "EvidenceAttachment.qa_decision_at_attachment", max_len=MAX_REF_LEN))
        object.__setattr__(self, "revision_of_at_attachment", _text(
            self.revision_of_at_attachment, "EvidenceAttachment.revision_of_at_attachment", max_len=MAX_REF_LEN))
        _require(isinstance(self.subject_refs, (tuple, list)) and all(isinstance(e, EntityRef) for e in self.subject_refs),
                 "INVALID_TYPE", "subject_refs must be a tuple of EntityRef")
        object.__setattr__(self, "subject_refs", _sort_canonical(set(self.subject_refs)))
        object.__setattr__(self, "locator", _text(self.locator, "EvidenceAttachment.locator", max_len=MAX_LOCATOR_LEN))
        object.__setattr__(self, "excerpt", _text(self.excerpt, "EvidenceAttachment.excerpt", max_len=MAX_EXCERPT_LEN))
        object.__setattr__(self, "note", _text(self.note, "EvidenceAttachment.note", max_len=MAX_NOTE_LEN))
        if prov is ProvenanceClass.HUMAN:
            _require(self.note != "", "MISSING_REASON", "HUMAN role assertion requires a note (reason) (A2 §6)")

    @property
    def attachment_key(self) -> str:
        """observation 内で一意（A2 §9: (ref_id, consequence_ref) につき高々 1）。governance の配分が参照する。"""
        return f"{self.ref_id}#{self.consequence_ref}"

    @property
    def is_evidentiary(self) -> bool:
        return self.role in EVIDENTIARY_ROLES

    @classmethod
    def from_dict(cls, data: Mapping[str, object]) -> "EvidenceAttachment":
        _reject_unknown(data, cls)
        evidence_time = data.get("evidence_time")
        return cls(
            evidence_kind=_parse_enum(data.get("evidence_kind"), EvidenceKind, "evidence_kind"),
            authority_class=_parse_enum(data.get("authority_class"), EvidenceAuthorityClass, "authority_class"),
            ref_id=_str(data, "ref_id"),
            source_origin=SourceOrigin.from_dict(data.get("source_origin") or {}),
            evidence_time=None if not evidence_time else from_iso(str(evidence_time)),
            evidence_time_basis=_parse_enum(data.get("evidence_time_basis"), EvidenceTimeBasis, "evidence_time_basis"),
            evidence_time_quality=_parse_enum(data.get("evidence_time_quality"), EvidenceTimeQuality,
                                              "evidence_time_quality"),
            evidence_date=_str(data, "evidence_date"),
            attached_at=from_iso(_str(data, "attached_at")),
            role=_parse_enum(data.get("role"), EvidenceRole, "role"),
            role_provenance=_parse_enum(data.get("role_provenance"), ProvenanceClass, "role_provenance"),
            role_asserted_by=_str(data, "role_asserted_by"),
            consequence_ref=_str(data, "consequence_ref"),
            invalidation_condition_ref=_str(data, "invalidation_condition_ref"),
            is_trigger=_bool(data, "is_trigger"), source_causal_claim=_bool(data, "source_causal_claim"),
            limited_use=_bool(data, "limited_use"),
            qa_decision_at_attachment=_str(data, "qa_decision_at_attachment"),
            revision_of_at_attachment=_str(data, "revision_of_at_attachment"),
            subject_refs=tuple(EntityRef.from_dict(e) for e in (data.get("subject_refs") or ())),
            locator=_str(data, "locator"), excerpt=_str(data, "excerpt"), note=_str(data, "note"))


# ---------------------------------------------------------------- provenance（observation）

@dataclass(frozen=True, kw_only=True)
class DroppedAttachment:
    """新 observation が除いた attachment の記録（A3 §15）。旧 observation は参照を保持し続ける。"""

    ref_id: str
    reason: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "ref_id", _text(self.ref_id, "DroppedAttachment.ref_id", max_len=MAX_REF_LEN,
                                                 required=True))
        object.__setattr__(self, "reason", _text(self.reason, "DroppedAttachment.reason", max_len=MAX_NOTE_LEN,
                                                 required=True))

    @classmethod
    def from_dict(cls, data: Mapping[str, object]) -> "DroppedAttachment":
        _reject_unknown(data, cls)
        return cls(ref_id=_str(data, "ref_id"), reason=_str(data, "reason"))


@dataclass(frozen=True, kw_only=True)
class ObservationProvenance:
    """observation を書いた主体（A2 §4 PROVENANCE / A3 §5）。canonical 行に含み、observation_id には含めない。"""

    writer_class: ProvenanceClass
    writer_ref: str = ""
    reason: str = ""
    governance_event_id: str = ""
    dropped_attachments: Tuple[DroppedAttachment, ...] = ()

    def __post_init__(self) -> None:
        _enum(self.writer_class, ProvenanceClass, "ObservationProvenance.writer_class")
        object.__setattr__(self, "writer_ref", _text(self.writer_ref, "ObservationProvenance.writer_ref",
                                                     max_len=MAX_REF_LEN))
        if self.writer_class in (ProvenanceClass.RULE, ProvenanceClass.LLM_PROPOSAL):
            _require(self.writer_ref != "", "MISSING_PROVENANCE",
                     f"{self.writer_class.value} writer requires writer_ref (rule id / model reference)")
        object.__setattr__(self, "reason", _text(self.reason, "ObservationProvenance.reason", max_len=MAX_NOTE_LEN))
        object.__setattr__(self, "governance_event_id", _content_ref(
            self.governance_event_id, GOVERNANCE_EVENT_ID_PREFIX, "ObservationProvenance.governance_event_id",
            required=False))
        _require(isinstance(self.dropped_attachments, (tuple, list))
                 and all(isinstance(d, DroppedAttachment) for d in self.dropped_attachments),
                 "INVALID_TYPE", "dropped_attachments must be a tuple of DroppedAttachment")
        object.__setattr__(self, "dropped_attachments", _sort_canonical(set(self.dropped_attachments)))

    @classmethod
    def from_dict(cls, data: Mapping[str, object]) -> "ObservationProvenance":
        _reject_unknown(data, cls)
        return cls(writer_class=_parse_enum(data.get("writer_class"), ProvenanceClass, "writer_class"),
                   writer_ref=_str(data, "writer_ref"), reason=_str(data, "reason"),
                   governance_event_id=_str(data, "governance_event_id"),
                   dropped_attachments=tuple(DroppedAttachment.from_dict(d)
                                             for d in (data.get("dropped_attachments") or ())))


# ---------------------------------------------------------------- ThemeObservation

def _normalize_semantics(*, subject, mechanism, certainty_class, scope, limitations, invalidation_conditions,
                         inferred_links, attachments) -> Dict[str, object]:
    """semantic content の型検査と canonical 順への正規化（`ThemeObservation.__post_init__` と `build` が共有）。"""
    _require(isinstance(subject, ThemeSubject), "INVALID_TYPE", "subject must be ThemeSubject")
    _require(isinstance(mechanism, Mechanism), "INVALID_MECHANISM", "mechanism must be Mechanism")
    _enum(certainty_class, MechanismCertainty, "certainty_class")
    _require(isinstance(scope, (tuple, list)) and all(isinstance(s, ScopeToken) for s in scope), "INVALID_TYPE",
             "scope must be a tuple of ScopeToken")
    scope_t = _sort_canonical(set(scope))
    _require(len(scope_t) >= 1, "MISSING_SCOPE", "scope must be declared (A1 Q3)")
    frames = [s for s in scope_t if s.dimension is ScopeDimension.PERIOD_FRAME]
    _require(len(frames) == 1, "MISSING_SCOPE", "scope must declare exactly one PERIOD_FRAME token (A1 §6 D)")
    _require(isinstance(limitations, (tuple, list)) and all(isinstance(l, Limitation) for l in limitations),
             "INVALID_TYPE", "limitations must be a tuple of Limitation")
    _require(isinstance(invalidation_conditions, (tuple, list))
             and all(isinstance(c, InvalidationCondition) for c in invalidation_conditions),
             "INVALID_TYPE", "invalidation_conditions must be a tuple of InvalidationCondition")
    conditions = _sort_canonical(set(invalidation_conditions))
    _require(len(conditions) >= 1, "MISSING_INVALIDATION_CONDITION",
             "a Theme without an invalidation condition is unfalsifiable (A1 Q6 / A2 §15)")
    condition_keys = [c.condition_key for c in conditions]
    _require(len(condition_keys) == len(set(condition_keys)), "DUPLICATE_KEY", "condition keys must be unique")
    _require(isinstance(inferred_links, (tuple, list)) and all(isinstance(l, InferredExposureLink)
                                                               for l in inferred_links),
             "INVALID_TYPE", "inferred_links must be a tuple of InferredExposureLink")
    links = _sort_canonical(set(inferred_links))
    entities = [(l.entity.kind, l.entity.value) for l in links]
    _require(len(entities) == len(set(entities)), "DUPLICATE_KEY", "one inferred link per entity")
    _require(isinstance(attachments, (tuple, list)) and all(isinstance(a, EvidenceAttachment) for a in attachments),
             "INVALID_TYPE", "attachments must be a tuple of EvidenceAttachment")
    atts = tuple(sorted(attachments, key=lambda a: (a.attachment_key, canonical_json(a))))
    att_keys = [a.attachment_key for a in atts]
    _require(len(att_keys) == len(set(att_keys)), "DUPLICATE_ATTACHMENT",
             "an evidence item appears at most once per (ref_id, consequence_ref) (A2 §9)")
    return {"subject": subject, "mechanism": mechanism, "certainty_class": certainty_class, "scope": scope_t,
            "limitations": _sort_canonical(set(limitations)), "invalidation_conditions": conditions,
            "inferred_links": links, "attachments": atts}


def observation_identity_payload(*, schema_version: str, mechanism_vocabulary_version: str, root_id: str,
                                 previous_observation_id: str, semantics: Mapping[str, object]) -> Dict[str, object]:
    """observation_id の材料（A2 §4 IDENTITY / SEMANTIC CONTENT のみ）。provenance / recorded_at / DERIVED を含まない。"""
    return {
        "schema_version": schema_version,
        "mechanism_vocabulary_version": mechanism_vocabulary_version,
        "root_id": root_id,
        "previous_observation_id": previous_observation_id,
        "subject": semantics["subject"],
        "mechanism": semantics["mechanism"],
        "certainty_class": semantics["certainty_class"],
        "scope": semantics["scope"],
        "limitations": semantics["limitations"],
        "invalidation_conditions": semantics["invalidation_conditions"],
        "inferred_links": semantics["inferred_links"],
        "attachments": semantics["attachments"],
    }


def make_observation_id(payload: Mapping[str, object]) -> str:
    return content_id(OBSERVATION_ID_PREFIX, canonical_json(payload))


@dataclass(frozen=True, kw_only=True)
class ThemeObservation:
    """ある時点の Theme の完全な意味論的状態の不変 snapshot（A2 §2.2 Level B / A3 §5）。

    field 分類（A2 §4）:
      IDENTITY / SEMANTIC … schema_version / mechanism_vocabulary_version / root_id / previous_observation_id /
                            subject / mechanism / certainty_class / scope / limitations / invalidation_conditions /
                            inferred_links / attachments   → observation_id の材料
      PROVENANCE          … provenance（writer / reason / governance ref / dropped）  → 行に含む、id 外
      AUDIT               … recorded_at                                             → 行に含む、id 外
      DERIVED / 非保持    … fingerprint / 資格判定 / diversity / DIRECTLY_EVIDENCED link / flag
      存在しない          … label / description / taxonomy / alias / lifecycle / horizon / return / 推奨
    """

    schema_version: str = THEME_OBSERVATION_SCHEMA_VERSION
    mechanism_vocabulary_version: str = MECHANISM_VOCABULARY_VERSION
    observation_id: str
    root_id: str
    previous_observation_id: str = ""     # genesis は空
    subject: ThemeSubject
    mechanism: Mechanism
    certainty_class: MechanismCertainty
    scope: Tuple[ScopeToken, ...]
    limitations: Tuple[Limitation, ...] = ()
    invalidation_conditions: Tuple[InvalidationCondition, ...]
    inferred_links: Tuple[InferredExposureLink, ...] = ()
    attachments: Tuple[EvidenceAttachment, ...] = ()
    provenance: ObservationProvenance
    recorded_at: datetime

    def __post_init__(self) -> None:
        _require(self.schema_version == THEME_OBSERVATION_SCHEMA_VERSION, "UNSUPPORTED_SCHEMA_VERSION",
                 f"unsupported ThemeObservation schema {self.schema_version!r}")
        _require(self.mechanism_vocabulary_version == MECHANISM_VOCABULARY_VERSION, "UNSUPPORTED_SCHEMA_VERSION",
                 f"unsupported mechanism vocabulary {self.mechanism_vocabulary_version!r}")
        object.__setattr__(self, "root_id", _root_id(self.root_id, "ThemeObservation.root_id"))
        object.__setattr__(self, "previous_observation_id", _content_ref(
            self.previous_observation_id, OBSERVATION_ID_PREFIX, "ThemeObservation.previous_observation_id",
            required=False))
        semantics = _normalize_semantics(
            subject=self.subject, mechanism=self.mechanism, certainty_class=self.certainty_class, scope=self.scope,
            limitations=self.limitations, invalidation_conditions=self.invalidation_conditions,
            inferred_links=self.inferred_links, attachments=self.attachments)
        for name, value in semantics.items():
            object.__setattr__(self, name, value)
        _require(isinstance(self.provenance, ObservationProvenance), "INVALID_TYPE",
                 "provenance must be ObservationProvenance")
        recorded_at = _aware(self.recorded_at, "ThemeObservation.recorded_at")
        self._validate_cross_references(recorded_at)
        expected = make_observation_id(self.identity_payload())
        _require(is_content_id(self.observation_id, OBSERVATION_ID_PREFIX), "INVALID_RECORD_ID",
                 "observation_id must be thobs_<24 hex>")
        _require(self.observation_id == expected, "IDENTITY_MISMATCH",
                 "observation_id does not match the semantic identity payload")
        _require(self.previous_observation_id != self.observation_id, "INVALID_RECORD_ID",
                 "an observation cannot be its own predecessor")

    def _validate_cross_references(self, recorded_at: datetime) -> None:
        consequence_keys = set(self.mechanism.consequence_keys)
        condition_keys = {c.condition_key for c in self.invalidation_conditions}
        ref_ids = {a.ref_id for a in self.attachments}
        for att in self.attachments:
            if att.consequence_ref:
                _require(att.consequence_ref in consequence_keys, "DANGLING_CONSEQUENCE_REF",
                         f"attachment {att.ref_id} references unknown consequence {att.consequence_ref!r}")
            if att.invalidation_condition_ref:
                _require(att.invalidation_condition_ref in condition_keys, "DANGLING_INVALIDATION_REF",
                         f"attachment {att.ref_id} references unknown condition {att.invalidation_condition_ref!r}")
            _require(att.attached_at <= recorded_at, "ATTACHED_AT_OUT_OF_RANGE",
                     f"attachment {att.ref_id} attached_at is later than recorded_at (A3 §7)")
        for component in self.mechanism.all_components():
            if component.assertion_provenance is AssertionProvenance.SOURCE_CLAIM:
                _require(component.provenance_ref in ref_ids, "DANGLING_SOURCE_CLAIM",
                         f"component {component.component_key} cites {component.provenance_ref!r} which is not attached")
        if self.certainty_class is MechanismCertainty.EXPLICIT_SOURCE_CAUSAL_CLAIM:
            _require(any(a.source_causal_claim for a in self.attachments), "MISSING_SOURCE_CAUSAL_CLAIM",
                     "EXPLICIT_SOURCE_CAUSAL_CLAIM requires an attachment flagged source_causal_claim (A2 §11)")
        if self.certainty_class is MechanismCertainty.EVIDENCE_SUPPORTED_MECHANISM:
            _require(any(a.role is EvidenceRole.SUPPORTS and a.consequence_ref
                         and a.evidence_time_quality is not EvidenceTimeQuality.MISSING
                         and a.role_provenance is not ProvenanceClass.LLM_PROPOSAL
                         for a in self.attachments),
                     "UNSUPPORTED_CERTAINTY_CLASS",
                     "EVIDENCE_SUPPORTED_MECHANISM requires a SUPPORTS attachment bound to a consequence (A1 §12.2 / A2 §6)")

    # ------------------------------------------------------------ identity / derived accessors

    def semantics(self) -> Dict[str, object]:
        return {"subject": self.subject, "mechanism": self.mechanism, "certainty_class": self.certainty_class,
                "scope": self.scope, "limitations": self.limitations,
                "invalidation_conditions": self.invalidation_conditions, "inferred_links": self.inferred_links,
                "attachments": self.attachments}

    def identity_payload(self) -> Dict[str, object]:
        return observation_identity_payload(
            schema_version=self.schema_version, mechanism_vocabulary_version=self.mechanism_vocabulary_version,
            root_id=self.root_id, previous_observation_id=self.previous_observation_id, semantics=self.semantics())

    @property
    def canonical_identity(self) -> str:
        return canonical_json(self.identity_payload())

    @property
    def is_genesis(self) -> bool:
        return self.previous_observation_id == ""

    def attachment(self, attachment_key: str) -> Optional[EvidenceAttachment]:
        for att in self.attachments:
            if att.attachment_key == attachment_key:
                return att
        return None

    # ------------------------------------------------------------ construction

    @classmethod
    def build(cls, *, root_id: str, previous_observation_id: str = "", subject: ThemeSubject, mechanism: Mechanism,
              certainty_class: MechanismCertainty, scope: Sequence[ScopeToken],
              limitations: Sequence[Limitation] = (), invalidation_conditions: Sequence[InvalidationCondition],
              inferred_links: Sequence[InferredExposureLink] = (), attachments: Sequence[EvidenceAttachment] = (),
              provenance: ObservationProvenance, recorded_at: datetime) -> "ThemeObservation":
        """semantic content から observation_id を計算して構築する（時計は注入。永続化しない）。"""
        semantics = _normalize_semantics(
            subject=subject, mechanism=mechanism, certainty_class=certainty_class, scope=tuple(scope),
            limitations=tuple(limitations), invalidation_conditions=tuple(invalidation_conditions),
            inferred_links=tuple(inferred_links), attachments=tuple(attachments))
        root = _root_id(root_id, "root_id")
        previous = _content_ref(previous_observation_id, OBSERVATION_ID_PREFIX, "previous_observation_id",
                                required=False)
        observation_id = make_observation_id(observation_identity_payload(
            schema_version=THEME_OBSERVATION_SCHEMA_VERSION, mechanism_vocabulary_version=MECHANISM_VOCABULARY_VERSION,
            root_id=root, previous_observation_id=previous, semantics=semantics))
        return cls(observation_id=observation_id, root_id=root, previous_observation_id=previous,
                   provenance=provenance, recorded_at=recorded_at, **semantics)

    # ------------------------------------------------------------ serialization

    def as_dict(self) -> Dict[str, object]:
        return _as_json(self)

    @classmethod
    def from_dict(cls, data: Mapping[str, object]) -> "ThemeObservation":
        _reject_unknown(data, cls)
        return cls(
            schema_version=_str(data, "schema_version"),
            mechanism_vocabulary_version=_str(data, "mechanism_vocabulary_version"),
            observation_id=_str(data, "observation_id"), root_id=_str(data, "root_id"),
            previous_observation_id=_str(data, "previous_observation_id"),
            subject=ThemeSubject.from_dict(data.get("subject") or {}),
            mechanism=Mechanism.from_dict(data.get("mechanism") or {}),
            certainty_class=_parse_enum(data.get("certainty_class"), MechanismCertainty, "certainty_class"),
            scope=tuple(ScopeToken.from_dict(s) for s in (data.get("scope") or ())),
            limitations=tuple(Limitation.from_dict(l) for l in (data.get("limitations") or ())),
            invalidation_conditions=tuple(InvalidationCondition.from_dict(c)
                                          for c in (data.get("invalidation_conditions") or ())),
            inferred_links=tuple(InferredExposureLink.from_dict(l) for l in (data.get("inferred_links") or ())),
            attachments=tuple(EvidenceAttachment.from_dict(a) for a in (data.get("attachments") or ())),
            provenance=ObservationProvenance.from_dict(data.get("provenance") or {}),
            recorded_at=from_iso(_str(data, "recorded_at")))


# ---------------------------------------------------------------- ThemeRootRecord

@dataclass(frozen=True, kw_only=True)
class ThemeRootRecord:
    """root 作成事実のみ（A3 §4）。Theme の現在状態を一切持たない（current_* 禁止）。root_id は内容から導出しない。"""

    schema_version: str = THEME_ROOT_SCHEMA_VERSION
    root_id: str
    created_at: datetime
    creation_method: CreationMethod
    creator_class: ProvenanceClass
    creation_provenance: str
    origin_event_id: str = ""
    genesis_observation_id: str

    def __post_init__(self) -> None:
        _require(self.schema_version == THEME_ROOT_SCHEMA_VERSION, "UNSUPPORTED_SCHEMA_VERSION",
                 f"unsupported ThemeRootRecord schema {self.schema_version!r}")
        object.__setattr__(self, "root_id", _root_id(self.root_id, "ThemeRootRecord.root_id"))
        _aware(self.created_at, "ThemeRootRecord.created_at")
        method = _enum(self.creation_method, CreationMethod, "ThemeRootRecord.creation_method")
        _enum(self.creator_class, ProvenanceClass, "ThemeRootRecord.creator_class")
        object.__setattr__(self, "creation_provenance", _text(
            self.creation_provenance, "ThemeRootRecord.creation_provenance", max_len=MAX_REF_LEN, required=True))
        needs_event = method is not CreationMethod.CANDIDATE
        object.__setattr__(self, "origin_event_id", _content_ref(
            self.origin_event_id, GOVERNANCE_EVENT_ID_PREFIX, "ThemeRootRecord.origin_event_id", required=needs_event))
        if not needs_event:
            _require(self.origin_event_id == "", "INVALID_ORIGIN_EVENT", "CANDIDATE roots have no origin event")
        if needs_event:
            _require(self.creator_class is ProvenanceClass.HUMAN, "INVALID_ROLE_COMBINATION",
                     f"{method.value} roots are created by a HUMAN governance decision (A2 §17 / A3 §10)")
        object.__setattr__(self, "genesis_observation_id", _content_ref(
            self.genesis_observation_id, OBSERVATION_ID_PREFIX, "ThemeRootRecord.genesis_observation_id",
            required=True))

    def as_dict(self) -> Dict[str, object]:
        return _as_json(self)

    @classmethod
    def from_dict(cls, data: Mapping[str, object]) -> "ThemeRootRecord":
        _reject_unknown(data, cls)
        return cls(schema_version=_str(data, "schema_version"), root_id=_str(data, "root_id"),
                   created_at=from_iso(_str(data, "created_at")),
                   creation_method=_parse_enum(data.get("creation_method"), CreationMethod, "creation_method"),
                   creator_class=_parse_enum(data.get("creator_class"), ProvenanceClass, "creator_class"),
                   creation_provenance=_str(data, "creation_provenance"),
                   origin_event_id=_str(data, "origin_event_id"),
                   genesis_observation_id=_str(data, "genesis_observation_id"))


def make_root_record(*, root_id: str, created_at: datetime, creation_method: CreationMethod,
                     creator_class: ProvenanceClass, creation_provenance: str, genesis_observation_id: str,
                     origin_event_id: str = "") -> ThemeRootRecord:
    """RootRecord を構築する（root_id は呼び出し側が `new_root_id` で生成して渡す。時計は注入）。"""
    return ThemeRootRecord(root_id=root_id, created_at=created_at, creation_method=creation_method,
                           creator_class=creator_class, creation_provenance=creation_provenance,
                           origin_event_id=origin_event_id, genesis_observation_id=genesis_observation_id)


# ---------------------------------------------------------------- ThemeGovernanceEvent

@dataclass(frozen=True, kw_only=True)
class EvidenceAllocation:
    """MERGE / SPLIT / SUCCESSOR の attachment 配分（A3 §10 / §17 / §18）。明示列挙のみ。黙った複製なし。"""

    source_observation_id: str
    attachment_key: str
    result_root_id: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "source_observation_id", _content_ref(
            self.source_observation_id, OBSERVATION_ID_PREFIX, "EvidenceAllocation.source_observation_id",
            required=True))
        object.__setattr__(self, "attachment_key", _text(self.attachment_key, "EvidenceAllocation.attachment_key",
                                                         max_len=MAX_REF_LEN + 70, required=True))
        object.__setattr__(self, "result_root_id", _root_id(self.result_root_id, "EvidenceAllocation.result_root_id"))

    @classmethod
    def from_dict(cls, data: Mapping[str, object]) -> "EvidenceAllocation":
        _reject_unknown(data, cls)
        return cls(source_observation_id=_str(data, "source_observation_id"),
                   attachment_key=_str(data, "attachment_key"), result_root_id=_str(data, "result_root_id"))


_RESULT_EVENT_TYPES = (GovernanceEventType.MERGE, GovernanceEventType.SPLIT, GovernanceEventType.SUPERSEDED_BY_ROOT)


def governance_identity_payload(*, schema_version: str, governance_vocabulary_version: str,
                                event_type: GovernanceEventType, subject_roots: Tuple[str, ...],
                                result_roots: Tuple[str, ...], related_observations: Tuple[str, ...],
                                previous_event_ids: Tuple[Tuple[str, str], ...], reverses_event_id: str,
                                evidence_allocation: Tuple[EvidenceAllocation, ...], reason: str,
                                actor_class: ProvenanceClass) -> Dict[str, object]:
    """event_id の材料（A3 §10: actor_ref / recorded_at を含まない）。"""
    return {
        "schema_version": schema_version,
        "governance_vocabulary_version": governance_vocabulary_version,
        "event_type": event_type,
        "subject_roots": subject_roots,
        "result_roots": result_roots,
        "related_observations": related_observations,
        "previous_event_ids": [list(pair) for pair in previous_event_ids],
        "reverses_event_id": reverses_event_id,
        "evidence_allocation": evidence_allocation,
        "reason": reason,
        "actor_class": actor_class,
    }


def make_governance_event_id(payload: Mapping[str, object]) -> str:
    return content_id(GOVERNANCE_EVENT_ID_PREFIX, canonical_json(payload))


@dataclass(frozen=True, kw_only=True)
class ThemeGovernanceEvent:
    """semantic observation ではない行為の不変 record（A3 §10）。observation を削除・改変しない。状態解決は A4c。"""

    schema_version: str = THEME_GOVERNANCE_SCHEMA_VERSION
    governance_vocabulary_version: str = GOVERNANCE_VOCABULARY_VERSION
    event_id: str
    event_type: GovernanceEventType
    subject_roots: Tuple[str, ...]
    result_roots: Tuple[str, ...] = ()
    related_observations: Tuple[str, ...] = ()
    previous_event_ids: Tuple[Tuple[str, str], ...] = ()   # (subject root, その root の直前 terminal event)
    reverses_event_id: str = ""
    evidence_allocation: Tuple[EvidenceAllocation, ...] = ()
    reason: str
    actor_class: ProvenanceClass
    actor_ref: str
    recorded_at: datetime

    def __post_init__(self) -> None:
        _require(self.schema_version == THEME_GOVERNANCE_SCHEMA_VERSION, "UNSUPPORTED_SCHEMA_VERSION",
                 f"unsupported ThemeGovernanceEvent schema {self.schema_version!r}")
        _require(self.governance_vocabulary_version == GOVERNANCE_VOCABULARY_VERSION, "UNSUPPORTED_SCHEMA_VERSION",
                 f"unsupported governance vocabulary {self.governance_vocabulary_version!r}")
        event_type = _enum(self.event_type, GovernanceEventType, "ThemeGovernanceEvent.event_type")
        subjects = tuple(sorted({_root_id(r, "subject_roots") for r in self.subject_roots}))
        results = tuple(sorted({_root_id(r, "result_roots") for r in self.result_roots}))
        _require(len(subjects) >= 1, "MALFORMED_GOVERNANCE_EVENT", "at least one subject root is required")
        _require(not set(subjects) & set(results), "MALFORMED_GOVERNANCE_EVENT",
                 "a root cannot be both subject and result")
        object.__setattr__(self, "subject_roots", subjects)
        object.__setattr__(self, "result_roots", results)
        related_prefix = (METADATA_ID_PREFIX if event_type is GovernanceEventType.METADATA_CORRECTION_APPROVED
                          else OBSERVATION_ID_PREFIX)
        related = tuple(sorted({_content_ref(r, related_prefix, "related_observations", required=True)
                                for r in self.related_observations}))
        object.__setattr__(self, "related_observations", related)
        previous: List[Tuple[str, str]] = []
        for pair in self.previous_event_ids:
            _require(isinstance(pair, (tuple, list)) and len(pair) == 2, "MALFORMED_GOVERNANCE_EVENT",
                     "previous_event_ids entries are (root_id, event_id) pairs")
            root = _root_id(pair[0], "previous_event_ids.root")
            _require(root in subjects, "MALFORMED_GOVERNANCE_EVENT",
                     "previous_event_ids keys must be subject roots (A3 §10)")
            previous.append((root, _content_ref(pair[1], GOVERNANCE_EVENT_ID_PREFIX, "previous_event_ids.event",
                                                required=True)))
        roots_seen = [p[0] for p in previous]
        _require(len(roots_seen) == len(set(roots_seen)), "MALFORMED_GOVERNANCE_EVENT",
                 "one previous event per subject root")
        object.__setattr__(self, "previous_event_ids", tuple(sorted(previous)))
        object.__setattr__(self, "reverses_event_id", _content_ref(
            self.reverses_event_id, GOVERNANCE_EVENT_ID_PREFIX, "ThemeGovernanceEvent.reverses_event_id",
            required=event_type is GovernanceEventType.EVENT_REVERSED))
        _require(isinstance(self.evidence_allocation, (tuple, list))
                 and all(isinstance(a, EvidenceAllocation) for a in self.evidence_allocation),
                 "INVALID_TYPE", "evidence_allocation must be a tuple of EvidenceAllocation")
        allocation = _sort_canonical(set(self.evidence_allocation))
        object.__setattr__(self, "evidence_allocation", allocation)
        object.__setattr__(self, "reason", _text(self.reason, "ThemeGovernanceEvent.reason", max_len=MAX_NOTE_LEN,
                                                 required=True))
        actor_class = _enum(self.actor_class, ProvenanceClass, "ThemeGovernanceEvent.actor_class")
        _require(actor_class is ProvenanceClass.HUMAN, "INVALID_ROLE_COMBINATION",
                 "governance events are human decisions in Phase 6 (A1 §16 / A3 §10); rules and LLMs only propose")
        object.__setattr__(self, "actor_ref", _text(self.actor_ref, "ThemeGovernanceEvent.actor_ref",
                                                    max_len=MAX_REF_LEN, required=True))
        _aware(self.recorded_at, "ThemeGovernanceEvent.recorded_at")
        self._validate_shape(event_type, subjects, results, related, allocation, self.reverses_event_id)
        expected = make_governance_event_id(self.identity_payload())
        _require(is_content_id(self.event_id, GOVERNANCE_EVENT_ID_PREFIX), "INVALID_RECORD_ID",
                 "event_id must be thgov_<24 hex>")
        _require(self.event_id == expected, "IDENTITY_MISMATCH", "event_id does not match the identity payload")
        _require(self.reverses_event_id != self.event_id, "MALFORMED_REVERSAL", "an event cannot reverse itself")

    @staticmethod
    def _validate_shape(event_type, subjects, results, related, allocation, reverses_event_id: str = "") -> None:
        if event_type is GovernanceEventType.MERGE:
            _require(len(subjects) >= 2, "MALFORMED_MERGE", "MERGE requires at least two subject roots")
            _require(len(results) == 1, "MALFORMED_MERGE", "MERGE declares exactly one result root (A3 §17)")
        elif event_type is GovernanceEventType.SPLIT:
            _require(len(subjects) == 1, "MALFORMED_SPLIT", "SPLIT has exactly one subject root")
            _require(len(results) >= 2, "MALFORMED_SPLIT", "SPLIT declares at least two result roots (A3 §18)")
        elif event_type is GovernanceEventType.SUPERSEDED_BY_ROOT:
            _require(len(subjects) == 1 and len(results) == 1, "MALFORMED_SUCCESSOR",
                     "SUPERSEDED_BY_ROOT relates exactly one old root to one new root (A3 §19)")
        elif event_type is GovernanceEventType.EVENT_REVERSED:
            _require(len(results) == 0, "MALFORMED_REVERSAL", "EVENT_REVERSED declares no result roots")
        else:
            _require(len(subjects) == 1, "MALFORMED_GOVERNANCE_EVENT",
                     f"{event_type.value} applies to exactly one subject root")
            _require(len(results) == 0, "MALFORMED_GOVERNANCE_EVENT",
                     f"{event_type.value} declares no result roots")
        if event_type is not GovernanceEventType.EVENT_REVERSED:
            _require(reverses_event_id == "", "MALFORMED_REVERSAL",
                     f"{event_type.value} must not carry reverses_event_id")
        if event_type in _RESULT_EVENT_TYPES:
            for item in allocation:
                _require(item.result_root_id in results, "ALLOCATION_VIOLATION",
                         "evidence_allocation must target a declared result root")
        else:
            _require(len(allocation) == 0, "ALLOCATION_VIOLATION",
                     f"{event_type.value} carries no evidence_allocation")
        if event_type in (GovernanceEventType.ROLE_CORRECTION_APPROVED,
                          GovernanceEventType.CERTAINTY_CHANGE_APPROVED,
                          GovernanceEventType.METADATA_CORRECTION_APPROVED):
            _require(len(related) >= 1, "MALFORMED_GOVERNANCE_EVENT",
                     f"{event_type.value} must reference the approved record(s)")

    def identity_payload(self) -> Dict[str, object]:
        return governance_identity_payload(
            schema_version=self.schema_version, governance_vocabulary_version=self.governance_vocabulary_version,
            event_type=self.event_type, subject_roots=self.subject_roots, result_roots=self.result_roots,
            related_observations=self.related_observations, previous_event_ids=self.previous_event_ids,
            reverses_event_id=self.reverses_event_id, evidence_allocation=self.evidence_allocation,
            reason=self.reason, actor_class=self.actor_class)

    @classmethod
    def build(cls, *, event_type: GovernanceEventType, subject_roots: Sequence[str], reason: str, actor_ref: str,
              recorded_at: datetime, actor_class: ProvenanceClass = ProvenanceClass.HUMAN,
              result_roots: Sequence[str] = (), related_observations: Sequence[str] = (),
              previous_event_ids: Sequence[Tuple[str, str]] = (), reverses_event_id: str = "",
              evidence_allocation: Sequence[EvidenceAllocation] = ()) -> "ThemeGovernanceEvent":
        subjects = tuple(sorted({_root_id(r, "subject_roots") for r in subject_roots}))
        results = tuple(sorted({_root_id(r, "result_roots") for r in result_roots}))
        related_prefix = (METADATA_ID_PREFIX if event_type is GovernanceEventType.METADATA_CORRECTION_APPROVED
                          else OBSERVATION_ID_PREFIX)
        related = tuple(sorted({_content_ref(r, related_prefix, "related_observations", required=True)
                                for r in related_observations}))
        previous = tuple(sorted((str(a), str(b)) for a, b in previous_event_ids))
        allocation = _sort_canonical(set(evidence_allocation))
        _enum(event_type, GovernanceEventType, "event_type")
        _enum(actor_class, ProvenanceClass, "actor_class")
        event_id = make_governance_event_id(governance_identity_payload(
            schema_version=THEME_GOVERNANCE_SCHEMA_VERSION, governance_vocabulary_version=GOVERNANCE_VOCABULARY_VERSION,
            event_type=event_type, subject_roots=subjects, result_roots=results, related_observations=related,
            previous_event_ids=previous, reverses_event_id=str(reverses_event_id), evidence_allocation=allocation,
            reason=str(reason), actor_class=actor_class))
        return cls(event_id=event_id, event_type=event_type, subject_roots=subjects, result_roots=results,
                   related_observations=related, previous_event_ids=previous, reverses_event_id=reverses_event_id,
                   evidence_allocation=allocation, reason=reason, actor_class=actor_class, actor_ref=actor_ref,
                   recorded_at=recorded_at)

    def as_dict(self) -> Dict[str, object]:
        return _as_json(self)

    @classmethod
    def from_dict(cls, data: Mapping[str, object]) -> "ThemeGovernanceEvent":
        _reject_unknown(data, cls)
        return cls(
            schema_version=_str(data, "schema_version"),
            governance_vocabulary_version=_str(data, "governance_vocabulary_version"),
            event_id=_str(data, "event_id"),
            event_type=_parse_enum(data.get("event_type"), GovernanceEventType, "event_type"),
            subject_roots=tuple(str(r) for r in (data.get("subject_roots") or ())),
            result_roots=tuple(str(r) for r in (data.get("result_roots") or ())),
            related_observations=tuple(str(r) for r in (data.get("related_observations") or ())),
            previous_event_ids=tuple((str(p[0]), str(p[1])) for p in (data.get("previous_event_ids") or ())),
            reverses_event_id=_str(data, "reverses_event_id"),
            evidence_allocation=tuple(EvidenceAllocation.from_dict(a) for a in (data.get("evidence_allocation") or ())),
            reason=_str(data, "reason"),
            actor_class=_parse_enum(data.get("actor_class"), ProvenanceClass, "actor_class"),
            actor_ref=_str(data, "actor_ref"), recorded_at=from_iso(_str(data, "recorded_at")))


# ---------------------------------------------------------------- ThemeMetadataRecord

def metadata_identity_payload(*, schema_version: str, metadata_field_vocabulary_version: str, root_id: str,
                              field: MetadataField, value: Tuple[str, ...], previous_metadata_id: str,
                              provenance_class: ProvenanceClass, governance_event_id: str) -> Dict[str, object]:
    """metadata_id の材料（A3 §12: provenance_ref / reason / recorded_at を含まない）。"""
    return {
        "schema_version": schema_version,
        "metadata_field_vocabulary_version": metadata_field_vocabulary_version,
        "root_id": root_id,
        "field": field,
        "value": value,
        "previous_metadata_id": previous_metadata_id,
        "provenance_class": provenance_class,
        "governance_event_id": governance_event_id,
    }


def make_metadata_id(payload: Mapping[str, object]) -> str:
    return content_id(METADATA_ID_PREFIX, canonical_json(payload))


@dataclass(frozen=True, kw_only=True)
class ThemeMetadataRecord:
    """label / description / taxonomy / alias の追記専用履歴（A3 §12）。ThemeObservation の外。semantic revision を生まない。

    value は常に tuple: 単一値 field（LABEL / DESCRIPTION）は要素 1 つ、集合 field（TAXONOMY / ALIAS）は
    その field の **全集合 snapshot**（差分ではない。空集合も可）。
    """

    schema_version: str = THEME_METADATA_SCHEMA_VERSION
    metadata_field_vocabulary_version: str = METADATA_FIELD_VOCABULARY_VERSION
    metadata_id: str
    root_id: str
    field: MetadataField
    value: Tuple[str, ...]
    previous_metadata_id: str = ""
    provenance_class: ProvenanceClass
    provenance_ref: str = ""
    reason: str = ""
    governance_event_id: str = ""
    recorded_at: datetime

    def __post_init__(self) -> None:
        _require(self.schema_version == THEME_METADATA_SCHEMA_VERSION, "UNSUPPORTED_SCHEMA_VERSION",
                 f"unsupported ThemeMetadataRecord schema {self.schema_version!r}")
        _require(self.metadata_field_vocabulary_version == METADATA_FIELD_VOCABULARY_VERSION,
                 "UNSUPPORTED_SCHEMA_VERSION",
                 f"unsupported metadata field vocabulary {self.metadata_field_vocabulary_version!r}")
        object.__setattr__(self, "root_id", _root_id(self.root_id, "ThemeMetadataRecord.root_id"))
        field = _enum(self.field, MetadataField, "ThemeMetadataRecord.field")
        object.__setattr__(self, "value", _normalize_metadata_value(field, self.value))
        object.__setattr__(self, "previous_metadata_id", _content_ref(
            self.previous_metadata_id, METADATA_ID_PREFIX, "ThemeMetadataRecord.previous_metadata_id", required=False))
        prov = _enum(self.provenance_class, ProvenanceClass, "ThemeMetadataRecord.provenance_class")
        object.__setattr__(self, "provenance_ref", _text(self.provenance_ref, "ThemeMetadataRecord.provenance_ref",
                                                         max_len=MAX_REF_LEN))
        if prov in (ProvenanceClass.RULE, ProvenanceClass.LLM_PROPOSAL):
            _require(self.provenance_ref != "", "MISSING_PROVENANCE", f"{prov.value} metadata requires provenance_ref")
        object.__setattr__(self, "reason", _text(self.reason, "ThemeMetadataRecord.reason", max_len=MAX_NOTE_LEN))
        object.__setattr__(self, "governance_event_id", _content_ref(
            self.governance_event_id, GOVERNANCE_EVENT_ID_PREFIX, "ThemeMetadataRecord.governance_event_id",
            required=False))
        _aware(self.recorded_at, "ThemeMetadataRecord.recorded_at")
        expected = make_metadata_id(self.identity_payload())
        _require(is_content_id(self.metadata_id, METADATA_ID_PREFIX), "INVALID_RECORD_ID",
                 "metadata_id must be thmeta_<24 hex>")
        _require(self.metadata_id == expected, "IDENTITY_MISMATCH", "metadata_id does not match the identity payload")
        _require(self.previous_metadata_id != self.metadata_id, "INVALID_RECORD_ID",
                 "a metadata record cannot be its own predecessor")

    def identity_payload(self) -> Dict[str, object]:
        return metadata_identity_payload(
            schema_version=self.schema_version,
            metadata_field_vocabulary_version=self.metadata_field_vocabulary_version, root_id=self.root_id,
            field=self.field, value=self.value, previous_metadata_id=self.previous_metadata_id,
            provenance_class=self.provenance_class, governance_event_id=self.governance_event_id)

    @classmethod
    def build(cls, *, root_id: str, field: MetadataField, value: Sequence[str], provenance_class: ProvenanceClass,
              recorded_at: datetime, previous_metadata_id: str = "", provenance_ref: str = "", reason: str = "",
              governance_event_id: str = "") -> "ThemeMetadataRecord":
        field_v = _enum(field, MetadataField, "field")
        normalized = _normalize_metadata_value(field_v, tuple(value))
        metadata_id = make_metadata_id(metadata_identity_payload(
            schema_version=THEME_METADATA_SCHEMA_VERSION,
            metadata_field_vocabulary_version=METADATA_FIELD_VOCABULARY_VERSION, root_id=_root_id(root_id, "root_id"),
            field=field_v, value=normalized,
            previous_metadata_id=_content_ref(previous_metadata_id, METADATA_ID_PREFIX, "previous_metadata_id",
                                              required=False),
            provenance_class=_enum(provenance_class, ProvenanceClass, "provenance_class"),
            governance_event_id=_content_ref(governance_event_id, GOVERNANCE_EVENT_ID_PREFIX, "governance_event_id",
                                             required=False)))
        return cls(metadata_id=metadata_id, root_id=root_id, field=field_v, value=normalized,
                   previous_metadata_id=previous_metadata_id, provenance_class=provenance_class,
                   provenance_ref=provenance_ref, reason=reason, governance_event_id=governance_event_id,
                   recorded_at=recorded_at)

    def as_dict(self) -> Dict[str, object]:
        return _as_json(self)

    @classmethod
    def from_dict(cls, data: Mapping[str, object]) -> "ThemeMetadataRecord":
        _reject_unknown(data, cls)
        return cls(
            schema_version=_str(data, "schema_version"),
            metadata_field_vocabulary_version=_str(data, "metadata_field_vocabulary_version"),
            metadata_id=_str(data, "metadata_id"), root_id=_str(data, "root_id"),
            field=_parse_enum(data.get("field"), MetadataField, "field"),
            value=tuple(str(v) for v in (data.get("value") or ())),
            previous_metadata_id=_str(data, "previous_metadata_id"),
            provenance_class=_parse_enum(data.get("provenance_class"), ProvenanceClass, "provenance_class"),
            provenance_ref=_str(data, "provenance_ref"), reason=_str(data, "reason"),
            governance_event_id=_str(data, "governance_event_id"), recorded_at=from_iso(_str(data, "recorded_at")))


def _normalize_metadata_value(field: MetadataField, value: object) -> Tuple[str, ...]:
    _require(isinstance(value, (tuple, list, set, frozenset)), "INVALID_TYPE", "metadata value must be a tuple of str")
    max_len = MAX_DESCRIPTION_LEN if field is MetadataField.DESCRIPTION else MAX_LABEL_LEN
    if field in SET_VALUED_METADATA_FIELDS:
        return _sorted_unique(value, f"ThemeMetadataRecord.value[{field.value}]", max_len=max_len)
    items = tuple(value)  # type: ignore[arg-type]
    _require(len(items) == 1, "INVALID_METADATA_VALUE", f"{field.value} holds exactly one value")
    return (_text(items[0], f"ThemeMetadataRecord.value[{field.value}]", max_len=max_len, required=True),)


# ---------------------------------------------------------------- ThemeSeriesMapping

def mapping_identity_payload(*, schema_version: str, root_id: str, consequence_ref: str, series_ref: str,
                             mapping_role: MappingRole, expected_relation: ExpectedRelation, valid_from: datetime,
                             supersedes_mapping_id: str, provenance_class: ProvenanceClass) -> Dict[str, object]:
    """mapping_id の材料（provenance_ref / reason / recorded_at を含まない）。"""
    return {
        "schema_version": schema_version,
        "root_id": root_id,
        "consequence_ref": consequence_ref,
        "series_ref": series_ref,
        "mapping_role": mapping_role,
        "expected_relation": expected_relation,
        "valid_from": valid_from,
        "supersedes_mapping_id": supersedes_mapping_id,
        "provenance_class": provenance_class,
    }


def make_mapping_id(payload: Mapping[str, object]) -> str:
    return content_id(MAPPING_ID_PREFIX, canonical_json(payload))


@dataclass(frozen=True, kw_only=True)
class ThemeSeriesMapping:
    """Theme-to-Series の運用的 mapping（A2 §14 Option C / A3 §3）。identity・fingerprint・P5・昇格 / 降格に関与しない。"""

    schema_version: str = THEME_SERIES_MAPPING_SCHEMA_VERSION
    mapping_id: str
    root_id: str
    consequence_ref: str = ""
    series_ref: str                    # series_id / instrument_id / Fact subject key
    mapping_role: MappingRole
    expected_relation: ExpectedRelation = ExpectedRelation.UNSPECIFIED
    valid_from: datetime
    supersedes_mapping_id: str = ""
    provenance_class: ProvenanceClass
    provenance_ref: str = ""
    reason: str = ""
    recorded_at: datetime

    def __post_init__(self) -> None:
        _require(self.schema_version == THEME_SERIES_MAPPING_SCHEMA_VERSION, "UNSUPPORTED_SCHEMA_VERSION",
                 f"unsupported ThemeSeriesMapping schema {self.schema_version!r}")
        object.__setattr__(self, "root_id", _root_id(self.root_id, "ThemeSeriesMapping.root_id"))
        object.__setattr__(self, "consequence_ref", "" if self.consequence_ref == "" else _key(
            self.consequence_ref, "ThemeSeriesMapping.consequence_ref"))
        object.__setattr__(self, "series_ref", _text(self.series_ref, "ThemeSeriesMapping.series_ref",
                                                     max_len=MAX_REF_LEN, required=True))
        _enum(self.mapping_role, MappingRole, "ThemeSeriesMapping.mapping_role")
        _enum(self.expected_relation, ExpectedRelation, "ThemeSeriesMapping.expected_relation")
        _aware(self.valid_from, "ThemeSeriesMapping.valid_from")
        object.__setattr__(self, "supersedes_mapping_id", _content_ref(
            self.supersedes_mapping_id, MAPPING_ID_PREFIX, "ThemeSeriesMapping.supersedes_mapping_id", required=False))
        prov = _enum(self.provenance_class, ProvenanceClass, "ThemeSeriesMapping.provenance_class")
        object.__setattr__(self, "provenance_ref", _text(self.provenance_ref, "ThemeSeriesMapping.provenance_ref",
                                                         max_len=MAX_REF_LEN))
        if prov in (ProvenanceClass.RULE, ProvenanceClass.LLM_PROPOSAL):
            _require(self.provenance_ref != "", "MISSING_PROVENANCE", f"{prov.value} mapping requires provenance_ref")
        object.__setattr__(self, "reason", _text(self.reason, "ThemeSeriesMapping.reason", max_len=MAX_NOTE_LEN))
        _aware(self.recorded_at, "ThemeSeriesMapping.recorded_at")
        expected = make_mapping_id(self.identity_payload())
        _require(is_content_id(self.mapping_id, MAPPING_ID_PREFIX), "INVALID_RECORD_ID",
                 "mapping_id must be thmap_<24 hex>")
        _require(self.mapping_id == expected, "IDENTITY_MISMATCH", "mapping_id does not match the identity payload")
        _require(self.supersedes_mapping_id != self.mapping_id, "INVALID_RECORD_ID",
                 "a mapping cannot supersede itself")

    def identity_payload(self) -> Dict[str, object]:
        return mapping_identity_payload(
            schema_version=self.schema_version, root_id=self.root_id, consequence_ref=self.consequence_ref,
            series_ref=self.series_ref, mapping_role=self.mapping_role, expected_relation=self.expected_relation,
            valid_from=self.valid_from, supersedes_mapping_id=self.supersedes_mapping_id,
            provenance_class=self.provenance_class)

    @classmethod
    def build(cls, *, root_id: str, series_ref: str, mapping_role: MappingRole, valid_from: datetime,
              provenance_class: ProvenanceClass, recorded_at: datetime, consequence_ref: str = "",
              expected_relation: ExpectedRelation = ExpectedRelation.UNSPECIFIED, supersedes_mapping_id: str = "",
              provenance_ref: str = "", reason: str = "") -> "ThemeSeriesMapping":
        mapping_id = make_mapping_id(mapping_identity_payload(
            schema_version=THEME_SERIES_MAPPING_SCHEMA_VERSION, root_id=_root_id(root_id, "root_id"),
            consequence_ref="" if consequence_ref == "" else _key(consequence_ref, "consequence_ref"),
            series_ref=str(series_ref), mapping_role=_enum(mapping_role, MappingRole, "mapping_role"),
            expected_relation=_enum(expected_relation, ExpectedRelation, "expected_relation"),
            valid_from=_aware(valid_from, "valid_from"),
            supersedes_mapping_id=_content_ref(supersedes_mapping_id, MAPPING_ID_PREFIX, "supersedes_mapping_id",
                                               required=False),
            provenance_class=_enum(provenance_class, ProvenanceClass, "provenance_class")))
        return cls(mapping_id=mapping_id, root_id=root_id, consequence_ref=consequence_ref, series_ref=series_ref,
                   mapping_role=mapping_role, expected_relation=expected_relation, valid_from=valid_from,
                   supersedes_mapping_id=supersedes_mapping_id, provenance_class=provenance_class,
                   provenance_ref=provenance_ref, reason=reason, recorded_at=recorded_at)

    def as_dict(self) -> Dict[str, object]:
        return _as_json(self)

    @classmethod
    def from_dict(cls, data: Mapping[str, object]) -> "ThemeSeriesMapping":
        _reject_unknown(data, cls)
        return cls(
            schema_version=_str(data, "schema_version"), mapping_id=_str(data, "mapping_id"),
            root_id=_str(data, "root_id"), consequence_ref=_str(data, "consequence_ref"),
            series_ref=_str(data, "series_ref"),
            mapping_role=_parse_enum(data.get("mapping_role"), MappingRole, "mapping_role"),
            expected_relation=_parse_enum(data.get("expected_relation", ExpectedRelation.UNSPECIFIED.value),
                                          ExpectedRelation, "expected_relation"),
            valid_from=from_iso(_str(data, "valid_from")),
            supersedes_mapping_id=_str(data, "supersedes_mapping_id"),
            provenance_class=_parse_enum(data.get("provenance_class"), ProvenanceClass, "provenance_class"),
            provenance_ref=_str(data, "provenance_ref"), reason=_str(data, "reason"),
            recorded_at=from_iso(_str(data, "recorded_at")))


#: 5 canonical record 型（A3 §3）
CANONICAL_RECORD_TYPES = (ThemeRootRecord, ThemeObservation, ThemeGovernanceEvent, ThemeMetadataRecord,
                          ThemeSeriesMapping)

SCHEMA_VERSIONS = {
    "ThemeRootRecord": THEME_ROOT_SCHEMA_VERSION,
    "ThemeObservation": THEME_OBSERVATION_SCHEMA_VERSION,
    "ThemeGovernanceEvent": THEME_GOVERNANCE_SCHEMA_VERSION,
    "ThemeMetadataRecord": THEME_METADATA_SCHEMA_VERSION,
    "ThemeSeriesMapping": THEME_SERIES_MAPPING_SCHEMA_VERSION,
}
