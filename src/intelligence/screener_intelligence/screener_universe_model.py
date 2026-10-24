"""P8-B5A — 明示の有限な Universe の意味（UniverseSpec）と人が審査した Universe の authority record。

答える問い: 「この screen は、どの有限な上場物の provider code の集合を対象にするつもりか」だけ。
推奨 ・魅力 ・順位 ・Theme の受益 ・watchlist ・portfolio の候補の集合ではない。発見と評価の明示の範囲だけ。

- member は明示の provider の上場物 code（J-Quants の 5 文字 code。凍結 A1 の `JQUANTS_CODE` の形）。構文だけを検査する。正規化
  （空白 ・小文字 ・全角）はしない（曖昧な正規化を拒む）。重複は拒む。宣言の順は保つが **意味を持たない**（直列化 ・人の意図の順だけ。
  順位 ・優先 ・魅力 ・確信ではない）。
- screen の主語は発行体。code → 上場物 → 審査済みの SecurityId → 審査済みの IssuerId の解決と、同じ発行体の code の束ねは後の実行（B5C）。
  本 module は identity を解かず、provider の適格を実行せず、上場の状態を推定しない。
- 適格の規則の版（凍結 LIVE1 の `LIVE_RULES_VERSION`）と、単一の authority の日の規則を束ねる（規則が変わっても Universe の意味は黙って
  変わらない）。Universe は上場の継続 ・code の継続 ・発行体の継続を証明しない（I1 は延期）。
- 大きさの上限は凍結の master の取り込みの上限（1 つの snapshot の行数）。実行の batch の大きさ（request の予算）とは別の概念。
- identity: `universe_id` は意味の内容（鍵 ・版 ・意図 ・member の宣言の順 ・規則の束ね）の内容 address。`membership_digest` は順を除いた
  member の集合の digest（同じ集合の比較のため。identity ではない）。latest ・既定 ・暗黙の全市場の Universe は無い。
- 時計 ・network ・IO ・既定の reviewed_at ・既定の著者は無い。
記録: `docs/databank/PHASE8_B5A_UNIVERSE_AUTHORITY.md`。
"""
from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Dict, Mapping, Tuple

from ..core.ids import content_id
from ..core.time import from_iso, to_utc_iso
from .identity_model import (CREDENTIAL_MARKERS, IDENTIFIER_PATTERNS, IdentifierScheme, canonical_json)
from .jquants_live_model import LIVE_RULES_VERSION
from .jquants_master_ingress import MAX_MASTER_ROWS

UNIVERSE_SCHEMA_VERSION = "p8_screener_universe:0.1.0"
UNIVERSE_RULES_VERSION = "p8_screener_universe:0.1.0"
UNIVERSE_ID_PREFIX = "p8uni"
UNIVERSE_AUTHORITY_RECORD_KIND = "SCREENER_UNIVERSE_AUTHORITY"
UNIVERSE_AUTHORITY_SCHEMA_VERSION = "p8_screener_universe_authority:0.1.0"
UNIVERSE_AUTHORITY_RULES_VERSION = "p8_screener_universe_authority:0.1.0"
#: 人が明示に審査した Universe（それ以上の意味は無い）
HUMAN_REVIEWED_SCREENING_UNIVERSE = "HUMAN_REVIEWED_SCREENING_UNIVERSE"
#: この authority が意味しないもの
NOT_IMPLIED_BY_UNIVERSE: Tuple[str, ...] = ("RECOMMENDED_SECURITIES", "RANKED_SECURITIES", "THEME_BENEFICIARIES",
                                           "WATCHLIST_MEMBERS", "PORTFOLIO_CANDIDATES", "LISTING_CONTINUITY",
                                           "ISSUER_IDENTITY", "PROVIDER_ELIGIBILITY")
#: member の識別子の体系（凍結 A1 の J-Quants の 5 文字 code。構文だけ）
MEMBER_SCHEME = IdentifierScheme.JQUANTS_CODE.value
#: 宣言の順の意味（直列化 ・人の意図の順だけ）
MEMBER_ORDER_RULE = "DECLARED_ORDER_SERIALIZATION_ONLY_NON_SEMANTIC_NOT_A_RANKING"
#: screen の主語（code は発見 ・取得の入力。主語は審査済みの identity で解いた発行体。解決は後の実行）
SUBJECT_RULE = "ISSUER_RESOLVED_LATER_THROUGH_REVIEWED_IDENTITY_NOT_THE_PROVIDER_CODE"
#: 単一の authority の日（identity の審査 ・取得 ・評価は 1 つの D0。複数日の継続は I1 で延期）
AUTHORITY_DAY_RULE = "SINGLE_AUTHORITY_DAY_D0_NO_MULTI_DAY_CONTINUITY"
#: 適格の規則の版（凍結 LIVE1。本 module は規則を実行しない）
ELIGIBILITY_RULES_VERSION = LIVE_RULES_VERSION
#: member の数の上限（凍結の master の 1 snapshot の取り込みの上限。実行の batch の大きさとは別）
MAX_UNIVERSE_MEMBERS = MAX_MASTER_ROWS
MAX_UNIVERSE_INTENT_LEN = 500
#: 意図に置かない語（推奨 ・順位の語。凍結 B1 の方針の意図と同じ集合を test が pin する）
FORBIDDEN_UNIVERSE_INTENT_WORDS: Tuple[str, ...] = ("buy", "sell", "recommend", "watchlist", "portfolio",
                                                    "target price", "expected return", "score", "rank", "rating",
                                                    "best", "推奨", "注目", "おすすめ", "有望", "割安", "上位", "買い",
                                                    "売り")
_KEY_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")
_AUTHOR_REF_RE = re.compile(r"^human:[A-Za-z0-9][A-Za-z0-9_.:@-]{0,113}$")
_UNIVERSE_ID_RE = re.compile(r"^p8uni_[0-9a-f]{24}$")
_CONTROL_RE = re.compile(r"[\x00-\x1f\x7f]")
_CODE_RE = IDENTIFIER_PATTERNS[IdentifierScheme.JQUANTS_CODE]
_SPEC_FIELDS = frozenset(("authority_day_rule", "eligibility_rules_version", "intent", "member_order_rule",
                          "member_scheme", "members", "membership_digest", "rules_version", "schema_version",
                          "subject_rule", "universe_id", "universe_key", "version"))
_RECORD_FIELDS = frozenset(("author_ref", "authority_class", "record_kind", "reviewed_at", "rules_version",
                            "schema_version", "universe"))


class UniverseModelError(ValueError):
    def __init__(self, code: str, detail: str = "") -> None:
        super().__init__(f"{code}: {detail}" if detail else code)
        self.code = code
        self.detail = detail


def _require(condition: bool, code: str, detail: str = "") -> None:
    if not condition:
        raise UniverseModelError(code, detail)


def _text(value: Any, field_name: str, pattern: "re.Pattern[str]") -> None:
    _require(isinstance(value, str) and bool(pattern.match(value)), f"INVALID_{field_name.upper()}", field_name)


def _aware(value: Any, field_name: str) -> None:
    _require(isinstance(value, datetime) and value.tzinfo is not None and value.tzinfo.utcoffset(value) is not None,
             "NAIVE_OR_MISSING_DATETIME", field_name)


def check_member_code(code: Any) -> str:
    """1 つの member の構文（5 文字の英大文字 ・数字）。正規化しない（空白 ・小文字 ・全角は拒む）。適格 ・identity は判定しない。"""
    _require(isinstance(code, str) and bool(_CODE_RE.match(code)), "INVALID_MEMBER_CODE", "members")
    return code


# ---------------------------------------------------------------- UniverseSpec


@dataclass(frozen=True, kw_only=True)
class UniverseSpec:
    """有限 ・明示 ・版つきの上場物の code の集合。宣言の順は意味を持たない。identity は内容 address。"""

    universe_key: str
    version: int
    intent: str
    members: Tuple[str, ...]
    eligibility_rules_version: str = ELIGIBILITY_RULES_VERSION
    authority_day_rule: str = AUTHORITY_DAY_RULE
    member_scheme: str = MEMBER_SCHEME
    member_order_rule: str = MEMBER_ORDER_RULE
    subject_rule: str = SUBJECT_RULE
    rules_version: str = UNIVERSE_RULES_VERSION

    def __post_init__(self) -> None:
        _text(self.universe_key, "universe_key", _KEY_RE)
        _require(type(self.version) is int and self.version >= 1, "INVALID_VERSION", "version")
        _require(isinstance(self.intent, str) and 1 <= len(self.intent) <= MAX_UNIVERSE_INTENT_LEN
                 and not _CONTROL_RE.search(self.intent) and self.intent == self.intent.strip(),
                 "INVALID_INTENT", "intent")
        lowered = self.intent.lower()
        _require(not any(marker in lowered for marker in CREDENTIAL_MARKERS), "CREDENTIAL_LIKE_TEXT", "intent")
        _require(not any(word in lowered for word in FORBIDDEN_UNIVERSE_INTENT_WORDS),
                 "FORBIDDEN_INTENT_VOCABULARY", "intent")
        _require(isinstance(self.members, tuple), "MEMBERS_NOT_TUPLE", "members")
        _require(len(self.members) >= 1, "EMPTY_UNIVERSE", "members")
        _require(len(self.members) <= MAX_UNIVERSE_MEMBERS, "UNIVERSE_TOO_LARGE", "members")
        for code in self.members:
            check_member_code(code)
        _require(len(set(self.members)) == len(self.members), "DUPLICATE_MEMBER", "members")
        _require(self.eligibility_rules_version == ELIGIBILITY_RULES_VERSION, "ELIGIBILITY_RULES_VERSION_UNKNOWN",
                 "eligibility_rules_version")
        _require(self.authority_day_rule == AUTHORITY_DAY_RULE, "AUTHORITY_DAY_RULE_UNKNOWN", "authority_day_rule")
        _require(self.member_scheme == MEMBER_SCHEME, "MEMBER_SCHEME_UNKNOWN", "member_scheme")
        _require(self.member_order_rule == MEMBER_ORDER_RULE, "MEMBER_ORDER_RULE_UNKNOWN", "member_order_rule")
        _require(self.subject_rule == SUBJECT_RULE, "SUBJECT_RULE_UNKNOWN", "subject_rule")
        _require(self.rules_version == UNIVERSE_RULES_VERSION, "RULES_VERSION_MISMATCH", "rules_version")

    def identity_payload(self) -> Dict[str, Any]:
        """identity に入る欄: 鍵 ・版 ・意図 ・member（宣言の順）・規則の束ね。審査者 ・審査の瞬間は入れない（record の欄）。"""
        return {"authority_day_rule": self.authority_day_rule,
                "eligibility_rules_version": self.eligibility_rules_version, "intent": self.intent,
                "member_order_rule": self.member_order_rule, "member_scheme": self.member_scheme,
                "members": list(self.members), "rules_version": self.rules_version,
                "schema_version": UNIVERSE_SCHEMA_VERSION, "subject_rule": self.subject_rule,
                "universe_key": self.universe_key, "version": self.version}

    @property
    def universe_id(self) -> str:
        return content_id(UNIVERSE_ID_PREFIX, canonical_json(self.identity_payload()))

    @property
    def membership_digest(self) -> str:
        """順を除いた member の集合の sha256（同じ集合の比較のため。identity ではない）。"""
        return hashlib.sha256(canonical_json({"members": sorted(self.members)}).encode("utf-8")).hexdigest()

    @property
    def member_count(self) -> int:
        return len(self.members)

    def as_dict(self) -> Dict[str, Any]:
        return {**self.identity_payload(), "membership_digest": self.membership_digest,
                "universe_id": self.universe_id}

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "UniverseSpec":
        _require(isinstance(data, Mapping), "INVALID_RECORD", "universe")
        _require(set(data) == _SPEC_FIELDS, "UNKNOWN_FIELD" if set(data) - _SPEC_FIELDS else "MISSING_FIELD",
                 "universe")
        _require(data["schema_version"] == UNIVERSE_SCHEMA_VERSION, "SCHEMA_MISMATCH", "universe.schema_version")
        _require(isinstance(data["members"], list), "INVALID_RECORD", "universe.members")
        spec = cls(universe_key=data["universe_key"], version=data["version"], intent=data["intent"],
                   members=tuple(data["members"]), eligibility_rules_version=data["eligibility_rules_version"],
                   authority_day_rule=data["authority_day_rule"], member_scheme=data["member_scheme"],
                   member_order_rule=data["member_order_rule"], subject_rule=data["subject_rule"],
                   rules_version=data["rules_version"])
        _require(spec.universe_id == data["universe_id"], "UNIVERSE_ID_MISMATCH", "universe_id")
        _require(spec.membership_digest == data["membership_digest"], "MEMBERSHIP_DIGEST_MISMATCH",
                 "membership_digest")
        return spec


def is_universe_id(value: Any) -> bool:
    return isinstance(value, str) and bool(_UNIVERSE_ID_RE.match(value))


# ---------------------------------------------------------------- 人が審査した Universe の authority record


@dataclass(frozen=True, kw_only=True)
class UniverseAuthorityRecord:
    """1 つの人が審査した Universe。identity は `universe.universe_id`（1 つの Universe に 1 つの審査）。自動の承認は無い。"""

    universe: UniverseSpec
    author_ref: str
    reviewed_at: datetime
    authority_class: str = HUMAN_REVIEWED_SCREENING_UNIVERSE
    schema_version: str = UNIVERSE_AUTHORITY_SCHEMA_VERSION
    rules_version: str = UNIVERSE_AUTHORITY_RULES_VERSION

    def __post_init__(self) -> None:
        _require(isinstance(self.universe, UniverseSpec), "INVALID_UNIVERSE", "universe")
        _text(self.author_ref, "author_ref", _AUTHOR_REF_RE)                      # 人の出所だけ（`human:` で始まる）
        _require(not any(marker in self.author_ref.lower() for marker in CREDENTIAL_MARKERS),
                 "CREDENTIAL_LIKE_TEXT", "author_ref")
        _aware(self.reviewed_at, "reviewed_at")
        _require(self.authority_class == HUMAN_REVIEWED_SCREENING_UNIVERSE, "AUTHORITY_CLASS_MISMATCH",
                 "authority_class")
        _require(self.schema_version == UNIVERSE_AUTHORITY_SCHEMA_VERSION, "SCHEMA_MISMATCH", "schema_version")
        _require(self.rules_version == UNIVERSE_AUTHORITY_RULES_VERSION, "RULES_VERSION_MISMATCH", "rules_version")

    @property
    def record_id(self) -> str:
        return self.universe.universe_id

    @property
    def universe_key(self) -> str:
        return self.universe.universe_key

    @property
    def version(self) -> int:
        return self.universe.version

    def as_dict(self) -> Dict[str, Any]:
        return {"author_ref": self.author_ref, "authority_class": self.authority_class,
                "record_kind": UNIVERSE_AUTHORITY_RECORD_KIND, "reviewed_at": to_utc_iso(self.reviewed_at),
                "rules_version": self.rules_version, "schema_version": self.schema_version,
                "universe": self.universe.as_dict()}

    def canonical_line(self) -> str:
        return canonical_json(self.as_dict()) + "\n"

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "UniverseAuthorityRecord":
        _require(isinstance(data, Mapping), "INVALID_RECORD", "record")
        _require(set(data) == _RECORD_FIELDS, "UNKNOWN_FIELD" if set(data) - _RECORD_FIELDS else "MISSING_FIELD",
                 "record")
        _require(data["record_kind"] == UNIVERSE_AUTHORITY_RECORD_KIND, "INVALID_RECORD", "record_kind")
        _require(data["schema_version"] == UNIVERSE_AUTHORITY_SCHEMA_VERSION, "SCHEMA_MISMATCH", "schema_version")
        _require(data["rules_version"] == UNIVERSE_AUTHORITY_RULES_VERSION, "RULES_VERSION_MISMATCH", "rules_version")
        _require(data["authority_class"] == HUMAN_REVIEWED_SCREENING_UNIVERSE, "AUTHORITY_CLASS_MISMATCH",
                 "authority_class")
        _require(isinstance(data["reviewed_at"], str), "INVALID_RECORD", "reviewed_at")
        try:
            reviewed_at = from_iso(data["reviewed_at"])
        except ValueError:
            raise UniverseModelError("NAIVE_OR_MISSING_DATETIME", "reviewed_at") from None
        return cls(universe=UniverseSpec.from_dict(data["universe"]), author_ref=data["author_ref"],
                   reviewed_at=reviewed_at)


def is_universe_authority_record(value: Any) -> bool:
    return isinstance(value, UniverseAuthorityRecord)


@dataclass(frozen=True, kw_only=True)
class UniverseMetadata:
    """人が選ぶための metadata（member の code ・意図 ・著者は含まない）。「現在」「既定」の意味は無い。"""

    universe_id: str
    universe_key: str
    version: int
    member_count: int
    reviewed_at: datetime

    @classmethod
    def of(cls, record: UniverseAuthorityRecord) -> "UniverseMetadata":
        return cls(universe_id=record.universe.universe_id, universe_key=record.universe_key,
                   version=record.version, member_count=record.universe.member_count,
                   reviewed_at=record.reviewed_at)


__all__ = ["AUTHORITY_DAY_RULE", "ELIGIBILITY_RULES_VERSION", "FORBIDDEN_UNIVERSE_INTENT_WORDS",
           "HUMAN_REVIEWED_SCREENING_UNIVERSE", "MAX_UNIVERSE_INTENT_LEN", "MAX_UNIVERSE_MEMBERS",
           "MEMBER_ORDER_RULE", "MEMBER_SCHEME", "NOT_IMPLIED_BY_UNIVERSE", "SUBJECT_RULE",
           "UNIVERSE_AUTHORITY_RECORD_KIND", "UNIVERSE_AUTHORITY_RULES_VERSION", "UNIVERSE_AUTHORITY_SCHEMA_VERSION",
           "UNIVERSE_ID_PREFIX", "UNIVERSE_RULES_VERSION", "UNIVERSE_SCHEMA_VERSION", "UniverseAuthorityRecord",
           "UniverseMetadata", "UniverseModelError", "UniverseSpec", "check_member_code",
           "is_universe_authority_record", "is_universe_id"]
