"""P8-ID1 — J-Quants の master snapshot からの identity bootstrap の model（機械の提案 → 人の審査 manifest → 登録 plan）。

authority の境界（監督の決定 D1。凍結）:
- provider の code は provider の識別子であり、canonical の identity ではない。`IssuerId(Code)` ・`SecurityId(Code)` は作らない。
  canonical の id は凍結 A1 の `derive_issuer_id` ／ `derive_security_id`（anchor だけから）で導く。
- 機械の提案（`IdentityProposal`）・manifest ・登録 plan は **DERIVED ・NON_AUTHORITY ・NON_PERSISTENT**。A1 の store には書かない。
- 人の審査（`ReviewedManifest`。reviewer は `HUMAN` だけ）が登録の前に要る authorization の artifact。審査は機械の提案の内容（digest）に
  結びつき、内容が変われば失効する（古い承認の再利用なし ・既定の承認なし ・自動の承認なし）。
- anchor は `<batch>:iss.<Code>` ／ `<batch>:sec.<Code>`（A3R §4.2。一括の id ＋ 種類 ＋ その時の code）。**承認の後は不変の token** で、
  後の provider の data から計算し直さない。
- D0（bootstrap の日）は caller が明示に渡す。時計を読まない。D0 より前の identity ・coverage を作らない。

入力は公式の master の行のうち 5 欄（`Date` ・`Code` ・`CoName` ・`CoNameEn` ・`Mkt`）だけを文字列で読む。公式に観測された他の欄は捨てて
保持しない。公式の一覧に無い key は拒む（schema のずれ）。raw の行は保持しない。

記録: `docs/databank/PHASE8_ID1_IDENTITY_BOOTSTRAP.md`。
"""
from __future__ import annotations

import hashlib
import re
from dataclasses import asdict, dataclass
from datetime import date, datetime, timedelta
from enum import Enum
from typing import Any, Dict, Mapping, Optional, Tuple

from .identity_model import (CREDENTIAL_MARKERS, IDENTIFIER_PATTERNS, IdentifierScheme, IssueClass, canonical_json,
                             derive_issuer_id, derive_security_id, is_issuer_id, is_security_id)
from .jquants_adapter_model import DERIVED_NON_AUTHORITY_NON_PERSISTENT
from .observation_model import TOKYO

BOOTSTRAP_RULES_VERSION = "p8_identity_bootstrap:0.1.0"
MANIFEST_SCHEMA_VERSION = "p8_bootstrap_manifest:0.1.0"
PROVIDER_RECORD_REF_PREFIX = "jq.eq_master"
#: 公式 `/v2/equities/master` で観測された欄（repo の research: A3R §4.1 ・real data mapping audit）。一覧に無い key は拒む
OFFICIAL_MASTER_FIELDS: Tuple[str, ...] = ("Code", "CoName", "CoNameEn", "Date", "Mkt", "MktNm", "Mrgn", "MrgnNm",
                                           "ProdCat", "S17", "S17Nm", "S33", "S33Nm", "ScaleCat")
#: bootstrap が読む 5 欄（provider の識別子 ・snapshot の日 ・表示名 ・市場区分）
SUPPORTED_MASTER_FIELDS: Tuple[str, ...] = ("Date", "Code", "CoName", "CoNameEn", "Mkt")
MAX_MASTER_VALUE_LENGTH = 120
_MASTER_VALUE_RE = re.compile(r"^[^\x00-\x1f\x7f]{0,120}$")
_BATCH_ID_RE = re.compile(r"^p8boot[1-9][0-9]{0,3}$")
_DATE_RE = re.compile(r"^[0-9]{4}-[0-9]{2}-[0-9]{2}$")
_DIGEST_HEX = 64
_NOTE_RE = re.compile(r"^[^\x00-\x1f\x7f]{0,200}$")


class BootstrapInputError(ValueError):
    """入力の契約 ・model の違反（HOLD ではなく拒否）。detail は field 名 ・code だけ。"""

    def __init__(self, code: str, detail: str = "") -> None:
        super().__init__(f"{code}: {detail}" if detail else code)
        self.code = code
        self.detail = detail


def _require(condition: bool, code: str, detail: str = "") -> None:
    if not condition:
        raise BootstrapInputError(code, detail)


def _text(value: Any, field_name: str, pattern: "re.Pattern[str]" = _MASTER_VALUE_RE) -> str:
    _require(isinstance(value, str), "PROVIDER_VALUE_NOT_TEXT", field_name)
    _require(bool(pattern.match(value)), "PROVIDER_VALUE_OUT_OF_BOUNDS", field_name)
    lowered = value.lower()
    _require(not any(marker in lowered for marker in CREDENTIAL_MARKERS), "CREDENTIAL_LIKE_TEXT", field_name)
    return value


def _digest(payload: Mapping[str, Any]) -> str:
    return hashlib.sha256(canonical_json(payload).encode("utf-8")).hexdigest()


def _check_digest(value: Any, field_name: str) -> str:
    _require(isinstance(value, str) and len(value) == _DIGEST_HEX and all(c in "0123456789abcdef" for c in value),
             "INVALID_DIGEST", field_name)
    return value


def _aware(value: Any, field_name: str) -> datetime:
    _require(isinstance(value, datetime) and value.tzinfo is not None
             and value.tzinfo.utcoffset(value) is not None, "INVALID_DATETIME", field_name)
    return value


def day_start_jst(day: date) -> datetime:
    """D0 の始まり（JST）。有効時間の起点。"""
    return datetime(day.year, day.month, day.day, tzinfo=TOKYO)


# ---------------------------------------------------------------- 入力（master の行）


@dataclass(frozen=True, kw_only=True)
class MasterRow:
    """bootstrap が読む 5 欄（provider の文字列のまま）。`CoNameEn` は空を許す（公式: 記載なし）。"""

    Date: str
    Code: str
    CoName: str
    CoNameEn: str
    Mkt: str

    def __post_init__(self) -> None:
        for name, value in asdict(self).items():
            _text(value, name)

    @classmethod
    def from_provider_mapping(cls, mapping: Any) -> "MasterRow":
        _require(isinstance(mapping, Mapping), "PROVIDER_ROW_NOT_MAPPING", "row")
        keys = set(mapping)
        _require(all(isinstance(key, str) for key in keys), "PROVIDER_FIELD_UNKNOWN", "row")
        unknown = keys - set(OFFICIAL_MASTER_FIELDS)
        _require(not unknown, "PROVIDER_FIELD_UNKNOWN", ",".join(sorted(unknown))[:160])
        missing = set(SUPPORTED_MASTER_FIELDS) - keys
        _require(not missing, "PROVIDER_FIELD_MISSING", ",".join(sorted(missing)))
        return cls(**{name: mapping[name] for name in SUPPORTED_MASTER_FIELDS})

    def supported_values(self) -> Dict[str, str]:
        return dict(asdict(self))

    def canonical_digest(self) -> str:
        return _digest(self.supported_values())

    def provider_record_ref(self) -> Optional[str]:
        """A1 の `source_record_ref` に入る参照（`jq.eq_master:<Code>.<Date>:<digest24>`）。形に合わなければ None。"""
        if not re.match(r"^[A-Za-z0-9_-]{1,64}$", self.Code) or not _DATE_RE.match(self.Date):
            return None
        return f"{PROVIDER_RECORD_REF_PREFIX}:{self.Code}.{self.Date}:{self.canonical_digest()[:24]}"


# ---------------------------------------------------------------- 一括（batch）と D0


@dataclass(frozen=True, kw_only=True)
class BootstrapBatch:
    """bootstrap の一括: id（anchor の接頭）・D0（明示）・支える市場区分の code（明示。既定なし）。"""

    batch_id: str
    d0: date
    supported_markets: Tuple[str, ...]

    def __post_init__(self) -> None:
        _require(isinstance(self.batch_id, str) and bool(_BATCH_ID_RE.match(self.batch_id)), "INVALID_BATCH_ID",
                 "batch_id")
        _require(type(self.d0) is date, "INVALID_D0", "d0")
        _require(isinstance(self.supported_markets, tuple) and len(self.supported_markets) > 0
                 and all(isinstance(m, str) and m != "" for m in self.supported_markets), "INVALID_MARKETS",
                 "supported_markets")

    def issuer_anchor(self, code: str) -> str:
        return f"{self.batch_id}:iss.{code}"

    def security_anchor(self, code: str) -> str:
        return f"{self.batch_id}:sec.{code}"

    @property
    def effective_from(self) -> datetime:
        return day_start_jst(self.d0)

    @property
    def coverage_to(self) -> datetime:
        return day_start_jst(self.d0 + timedelta(days=1))

    def as_dict(self) -> Dict[str, Any]:
        return {"batch_id": self.batch_id, "d0": self.d0.isoformat(), "supported_markets": list(self.supported_markets)}


# ---------------------------------------------------------------- 提案 ・保留 ・審査の要否


class ProposalDisposition(str, Enum):
    PROPOSED = "PROPOSED"                            # 機械の提案（審査の対象）
    HELD = "HELD"                                    # 決定論の保留（登録しない）
    HUMAN_REVIEW_REQUIRED = "HUMAN_REVIEW_REQUIRED"  # 人が決める事（code の変更 ・廃止 ／ 再上場 ・複数の上場物 …）
    REUSE = "REUSE"                                  # 同じ identity が A1 に既にある（重複の登録をしない）
    CONFLICT = "CONFLICT"                            # code が別の canonical identity に結ばれている（fail closed）


class BootstrapReason(str, Enum):
    CODE_MALFORMED = "CODE_MALFORMED"
    CODE_NOT_COMMON_EQUITY = "CODE_NOT_COMMON_EQUITY"
    CODE_CONFLICTING_ROWS = "CODE_CONFLICTING_ROWS"
    SNAPSHOT_DATE_MISMATCH = "SNAPSHOT_DATE_MISMATCH"
    NAME_MISSING = "NAME_MISSING"
    MARKET_UNSUPPORTED = "MARKET_UNSUPPORTED"
    PROVIDER_REF_UNAVAILABLE = "PROVIDER_REF_UNAVAILABLE"
    MULTIPLE_LISTINGS_SUSPECTED = "MULTIPLE_LISTINGS_SUSPECTED"
    CODE_BOUND_TO_OTHER_IDENTITY = "CODE_BOUND_TO_OTHER_IDENTITY"
    CODE_PREVIOUSLY_RETIRED = "CODE_PREVIOUSLY_RETIRED"
    LISTING_ENDED_IN_AUTHORITY = "LISTING_ENDED_IN_AUTHORITY"
    EXISTING_IDENTITY_INCOMPLETE = "EXISTING_IDENTITY_INCOMPLETE"
    CODE_ABSENT_FROM_SNAPSHOT = "CODE_ABSENT_FROM_SNAPSHOT"
    ISSUER_SECURITY_RELATION_CONFLICT = "ISSUER_SECURITY_RELATION_CONFLICT"


_REASON_ORDER = {reason: index for index, reason in enumerate(BootstrapReason)}


def ordered_bootstrap_reasons(reasons: Any) -> Tuple[BootstrapReason, ...]:
    _require(isinstance(reasons, (tuple, list)) and all(isinstance(r, BootstrapReason) for r in reasons),
             "INVALID_REASONS", "reasons")
    return tuple(sorted(set(reasons), key=_REASON_ORDER.__getitem__))


@dataclass(frozen=True, kw_only=True)
class IdentityProposal:
    """1 つの普通株の code に対する Issuer ＋ Security の機械の提案（内容 address。派生 ・非 authority）。"""

    batch_id: str
    d0: date
    code: str
    issuer_anchor: str
    security_anchor: str
    issuer_id: str
    security_id: str
    issue_class: IssueClass
    name_ja: str
    name_en: str
    market: str
    provider_record_ref: str
    provider_record_digest: str
    rules_version: str = BOOTSTRAP_RULES_VERSION

    def __post_init__(self) -> None:
        _require(bool(_BATCH_ID_RE.match(self.batch_id)), "INVALID_BATCH_ID", "batch_id")
        _require(type(self.d0) is date, "INVALID_D0", "d0")
        _require(bool(IDENTIFIER_PATTERNS[IdentifierScheme.JQUANTS_CODE].match(self.code)), "INVALID_PROPOSAL", "code")
        _require(self.issuer_anchor == f"{self.batch_id}:iss.{self.code}", "INVALID_PROPOSAL", "issuer_anchor")
        _require(self.security_anchor == f"{self.batch_id}:sec.{self.code}", "INVALID_PROPOSAL", "security_anchor")
        _require(self.issuer_id == derive_issuer_id(self.issuer_anchor), "INVALID_PROPOSAL", "issuer_id")
        _require(self.security_id == derive_security_id(self.security_anchor), "INVALID_PROPOSAL", "security_id")
        _require(is_issuer_id(self.issuer_id) and is_security_id(self.security_id), "INVALID_PROPOSAL", "ids")
        _require(isinstance(self.issue_class, IssueClass), "INVALID_PROPOSAL", "issue_class")
        _text(self.name_ja, "name_ja")
        _text(self.name_en, "name_en")
        _require(self.name_ja != "", "INVALID_PROPOSAL", "name_ja")
        _text(self.market, "market")
        _text(self.provider_record_ref, "provider_record_ref")
        _check_digest(self.provider_record_digest, "provider_record_digest")

    def content(self) -> Dict[str, Any]:
        return {"batch_id": self.batch_id, "code": self.code, "d0": self.d0.isoformat(),
                "issue_class": self.issue_class.value, "issuer_anchor": self.issuer_anchor,
                "issuer_id": self.issuer_id, "market": self.market, "name_en": self.name_en, "name_ja": self.name_ja,
                "provider_record_digest": self.provider_record_digest, "provider_record_ref": self.provider_record_ref,
                "rules_version": self.rules_version, "security_anchor": self.security_anchor,
                "security_id": self.security_id}

    @property
    def digest(self) -> str:
        return _digest(self.content())

    @property
    def proposal_id(self) -> str:
        return f"p8prop_{self.digest[:24]}"

    def as_dict(self) -> Dict[str, Any]:
        return {**self.content(), "digest": self.digest, "proposal_id": self.proposal_id}

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "IdentityProposal":
        _require(isinstance(data, Mapping) and set(data) == set(cls.from_dict_fields()), "INVALID_PROPOSAL", "fields")
        proposal = cls(batch_id=data["batch_id"], d0=_parse_date(data["d0"]), code=data["code"],
                       issuer_anchor=data["issuer_anchor"], security_anchor=data["security_anchor"],
                       issuer_id=data["issuer_id"], security_id=data["security_id"],
                       issue_class=_parse_issue_class(data["issue_class"]), name_ja=data["name_ja"],
                       name_en=data["name_en"], market=data["market"],
                       provider_record_ref=data["provider_record_ref"],
                       provider_record_digest=data["provider_record_digest"], rules_version=data["rules_version"])
        _require(proposal.digest == data["digest"] and proposal.proposal_id == data["proposal_id"],
                 "PROPOSAL_DIGEST_MISMATCH", "digest")
        return proposal

    @staticmethod
    def from_dict_fields() -> Tuple[str, ...]:
        return ("batch_id", "code", "d0", "digest", "issue_class", "issuer_anchor", "issuer_id", "market", "name_en",
                "name_ja", "proposal_id", "provider_record_digest", "provider_record_ref", "rules_version",
                "security_anchor", "security_id")


def _parse_date(value: Any) -> date:
    _require(isinstance(value, str) and bool(_DATE_RE.match(value)), "INVALID_D0", "d0")
    try:
        return date.fromisoformat(value)
    except ValueError:
        raise BootstrapInputError("INVALID_D0", "d0") from None


def _parse_issue_class(value: Any) -> IssueClass:
    try:
        return IssueClass(value)
    except (ValueError, TypeError):
        raise BootstrapInputError("INVALID_PROPOSAL", "issue_class") from None


@dataclass(frozen=True, kw_only=True)
class ReviewItem:
    """提案にならなかった code（保留 ・人の審査 ・再利用 ・衝突）。理由は閉じた code だけ。"""

    code: str
    disposition: ProposalDisposition
    reasons: Tuple[BootstrapReason, ...]
    provider_record_digest: str = ""
    existing_issuer_id: str = ""
    existing_security_id: str = ""

    def __post_init__(self) -> None:
        _text(self.code, "code")
        _require(isinstance(self.disposition, ProposalDisposition)
                 and self.disposition is not ProposalDisposition.PROPOSED, "INVALID_REVIEW_ITEM", "disposition")
        _require(self.reasons == ordered_bootstrap_reasons(self.reasons), "INVALID_REVIEW_ITEM", "reasons")
        _require(self.disposition is ProposalDisposition.REUSE or self.reasons != (), "INVALID_REVIEW_ITEM", "reasons")
        _require(self.provider_record_digest == "" or bool(_check_digest(self.provider_record_digest, "digest")),
                 "INVALID_REVIEW_ITEM", "digest")
        _require(self.existing_issuer_id == "" or is_issuer_id(self.existing_issuer_id), "INVALID_REVIEW_ITEM",
                 "existing_issuer_id")
        _require(self.existing_security_id == "" or is_security_id(self.existing_security_id), "INVALID_REVIEW_ITEM",
                 "existing_security_id")

    def as_dict(self) -> Dict[str, Any]:
        return {"code": self.code, "disposition": self.disposition.value,
                "existing_issuer_id": self.existing_issuer_id, "existing_security_id": self.existing_security_id,
                "provider_record_digest": self.provider_record_digest, "reasons": [r.value for r in self.reasons]}

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "ReviewItem":
        _require(isinstance(data, Mapping) and set(data) == {"code", "disposition", "existing_issuer_id",
                                                             "existing_security_id", "provider_record_digest",
                                                             "reasons"}, "INVALID_REVIEW_ITEM", "fields")
        try:
            disposition = ProposalDisposition(data["disposition"])
            reasons = tuple(BootstrapReason(r) for r in data["reasons"])
        except (ValueError, TypeError):
            raise BootstrapInputError("INVALID_REVIEW_ITEM", "vocabulary") from None
        return cls(code=data["code"], disposition=disposition, reasons=reasons,
                   provider_record_digest=data["provider_record_digest"],
                   existing_issuer_id=data["existing_issuer_id"], existing_security_id=data["existing_security_id"])


# ---------------------------------------------------------------- manifest（人の審査の対象）


@dataclass(frozen=True, kw_only=True)
class BootstrapManifest:
    """決定論の審査 manifest。提案は code の順（順序は digest に影響しない: 入力の順に依らない）。"""

    batch: BootstrapBatch
    proposals: Tuple[IdentityProposal, ...]
    review_items: Tuple[ReviewItem, ...]
    rules_version: str = BOOTSTRAP_RULES_VERSION
    schema_version: str = MANIFEST_SCHEMA_VERSION
    authority_class: str = DERIVED_NON_AUTHORITY_NON_PERSISTENT

    def __post_init__(self) -> None:
        _require(isinstance(self.batch, BootstrapBatch), "INVALID_MANIFEST", "batch")
        _require(isinstance(self.proposals, tuple) and all(isinstance(p, IdentityProposal) for p in self.proposals),
                 "INVALID_MANIFEST", "proposals")
        _require(isinstance(self.review_items, tuple) and all(isinstance(i, ReviewItem) for i in self.review_items),
                 "INVALID_MANIFEST", "review_items")
        codes = [p.code for p in self.proposals]
        _require(codes == sorted(codes) and len(set(codes)) == len(codes), "INVALID_MANIFEST", "proposal_order")
        item_codes = [i.code for i in self.review_items]
        _require(item_codes == sorted(item_codes) and len(set(item_codes)) == len(item_codes), "INVALID_MANIFEST",
                 "review_item_order")
        _require(not set(codes) & set(item_codes), "INVALID_MANIFEST", "code_in_both")
        for proposal in self.proposals:
            _require(proposal.batch_id == self.batch.batch_id and proposal.d0 == self.batch.d0, "INVALID_MANIFEST",
                     "proposal_batch")

    def content(self) -> Dict[str, Any]:
        return {"authority_class": self.authority_class, "batch": self.batch.as_dict(),
                "proposal_digests": [p.digest for p in self.proposals],
                "proposals": [p.as_dict() for p in self.proposals],
                "review_items": [i.as_dict() for i in self.review_items], "rules_version": self.rules_version,
                "schema_version": self.schema_version}

    @property
    def manifest_digest(self) -> str:
        return _digest(self.content())

    def proposal(self, proposal_id: str) -> Optional[IdentityProposal]:
        for proposal in self.proposals:
            if proposal.proposal_id == proposal_id:
                return proposal
        return None

    def as_dict(self) -> Dict[str, Any]:
        return {**self.content(), "manifest_digest": self.manifest_digest}

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "BootstrapManifest":
        """直列化した manifest の復元。digest が一致しなければ拒む（fail closed）。"""
        _require(isinstance(data, Mapping) and set(data) == {"authority_class", "batch", "manifest_digest",
                                                             "proposal_digests", "proposals", "review_items",
                                                             "rules_version", "schema_version"}, "INVALID_MANIFEST",
                 "fields")
        _require(data["schema_version"] == MANIFEST_SCHEMA_VERSION, "UNSUPPORTED_SCHEMA_VERSION", "schema_version")
        batch_data = data["batch"]
        _require(isinstance(batch_data, Mapping) and set(batch_data) == {"batch_id", "d0", "supported_markets"},
                 "INVALID_MANIFEST", "batch")
        batch = BootstrapBatch(batch_id=batch_data["batch_id"], d0=_parse_date(batch_data["d0"]),
                               supported_markets=tuple(batch_data["supported_markets"]))
        manifest = cls(batch=batch, proposals=tuple(IdentityProposal.from_dict(p) for p in data["proposals"]),
                       review_items=tuple(ReviewItem.from_dict(i) for i in data["review_items"]),
                       rules_version=data["rules_version"], authority_class=data["authority_class"])
        _require(manifest.manifest_digest == data["manifest_digest"]
                 and [p.digest for p in manifest.proposals] == list(data["proposal_digests"]),
                 "MANIFEST_DIGEST_MISMATCH", "manifest_digest")
        return manifest


# ---------------------------------------------------------------- 人の審査


class ReviewDisposition(str, Enum):
    APPROVE = "APPROVE"
    REJECT = "REJECT"
    DEFER = "DEFER"


class ReviewerClass(str, Enum):
    HUMAN = "HUMAN"


@dataclass(frozen=True, kw_only=True)
class ProposalReview:
    """1 提案への人の判断。提案の digest に結びつく（内容が変われば失効）。note は境界つきの短文で identity を運ばない。"""

    proposal_id: str
    proposal_digest: str
    disposition: ReviewDisposition
    note: str = ""

    def __post_init__(self) -> None:
        _require(isinstance(self.proposal_id, str) and bool(re.match(r"^p8prop_[0-9a-f]{24}$", self.proposal_id)),
                 "INVALID_REVIEW", "proposal_id")
        _check_digest(self.proposal_digest, "proposal_digest")
        _require(self.proposal_id == f"p8prop_{self.proposal_digest[:24]}", "INVALID_REVIEW", "proposal_id")
        _require(isinstance(self.disposition, ReviewDisposition), "INVALID_REVIEW", "disposition")
        _text(self.note, "note", _NOTE_RE)

    def as_dict(self) -> Dict[str, Any]:
        return {"disposition": self.disposition.value, "note": self.note, "proposal_digest": self.proposal_digest,
                "proposal_id": self.proposal_id}


@dataclass(frozen=True, kw_only=True)
class ReviewedManifest:
    """人の審査の結果（authorization の artifact）。manifest の digest ・各提案の digest に結びつく。

    部分の審査を許す: review の無い提案は **未審査で、登録の権限を持たない**（暗黙の承認 ・繰り越しは無い）。
    `accepted_at` は審査の受理の時刻（caller が明示に渡す。system の知識の時刻 `known_at` になる）。時計を読まない。
    """

    manifest_digest: str
    reviews: Tuple[ProposalReview, ...]
    accepted_at: datetime
    reviewer_class: ReviewerClass = ReviewerClass.HUMAN

    def __post_init__(self) -> None:
        _check_digest(self.manifest_digest, "manifest_digest")
        _require(isinstance(self.reviews, tuple) and all(isinstance(r, ProposalReview) for r in self.reviews),
                 "INVALID_REVIEW", "reviews")
        ids = [r.proposal_id for r in self.reviews]
        _require(ids == sorted(ids) and len(set(ids)) == len(ids), "INVALID_REVIEW", "review_order")
        _aware(self.accepted_at, "accepted_at")
        _require(self.reviewer_class is ReviewerClass.HUMAN, "INVALID_REVIEW", "reviewer_class")

    def review_for(self, proposal_id: str) -> Optional[ProposalReview]:
        for review in self.reviews:
            if review.proposal_id == proposal_id:
                return review
        return None

    def content(self) -> Dict[str, Any]:
        return {"accepted_at": self.accepted_at.isoformat(), "manifest_digest": self.manifest_digest,
                "reviewer_class": self.reviewer_class.value, "reviews": [r.as_dict() for r in self.reviews]}

    @property
    def reviewed_digest(self) -> str:
        return _digest(self.content())

    def as_dict(self) -> Dict[str, Any]:
        return {**self.content(), "reviewed_digest": self.reviewed_digest}


# ---------------------------------------------------------------- 登録 plan（派生 ・非 authority ・非永続）


class PlanSkipReason(str, Enum):
    NOT_REVIEWED = "NOT_REVIEWED"
    REJECTED = "REJECTED"
    DEFERRED = "DEFERRED"


@dataclass(frozen=True, kw_only=True)
class PlannedRegistration:
    """承認された 1 提案の、凍結 A1 の record の列（append の順）。"""

    proposal_id: str
    code: str
    issuer_id: str
    security_id: str
    records: Tuple[Any, ...]

    def as_dict(self) -> Dict[str, Any]:
        return {"code": self.code, "issuer_id": self.issuer_id, "proposal_id": self.proposal_id,
                "record_ids": [r.record_id for r in self.records],
                "record_kinds": [r.KIND.value for r in self.records], "security_id": self.security_id}


@dataclass(frozen=True, kw_only=True)
class RegistrationPlan:
    """承認済みの提案だけから導いた登録 plan。**A1 に append しない**。後の実行は manifest と A1 の状態を再検証する。"""

    batch: BootstrapBatch
    manifest_digest: str
    reviewed_digest: str
    entries: Tuple[PlannedRegistration, ...]
    coverage: Tuple[Any, ...]
    skipped: Tuple[Tuple[str, PlanSkipReason], ...]
    rules_version: str = BOOTSTRAP_RULES_VERSION
    authority_class: str = DERIVED_NON_AUTHORITY_NON_PERSISTENT

    @property
    def records(self) -> Tuple[Any, ...]:
        """append の順の全 record（登録 → 識別子 ・名前 ・上場 → 一括の coverage）。"""
        planned: Tuple[Any, ...] = ()
        for entry in self.entries:
            planned += entry.records
        return planned + self.coverage

    def as_dict(self) -> Dict[str, Any]:
        return {"authority_class": self.authority_class, "batch": self.batch.as_dict(),
                "coverage_record_ids": [r.record_id for r in self.coverage],
                "entries": [e.as_dict() for e in self.entries], "manifest_digest": self.manifest_digest,
                "reviewed_digest": self.reviewed_digest, "rules_version": self.rules_version,
                "skipped": [[proposal_id, reason.value] for proposal_id, reason in self.skipped]}

    @property
    def plan_digest(self) -> str:
        return _digest(self.as_dict())


__all__ = ["BOOTSTRAP_RULES_VERSION", "MANIFEST_SCHEMA_VERSION", "OFFICIAL_MASTER_FIELDS", "PROVIDER_RECORD_REF_PREFIX",
           "SUPPORTED_MASTER_FIELDS", "BootstrapBatch", "BootstrapInputError", "BootstrapManifest", "BootstrapReason",
           "IdentityProposal", "MasterRow", "PlanSkipReason", "PlannedRegistration", "ProposalDisposition",
           "ProposalReview", "RegistrationPlan", "ReviewDisposition", "ReviewItem", "ReviewedManifest",
           "ReviewerClass", "day_start_jst", "ordered_bootstrap_reasons"]
