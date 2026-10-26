"""P8-ACQ0 — 取得 event（`AcquisitionEvent`）の純 model: 「何を ・どの範囲で ・いつ取得を試み ・完了 ／ 途中 ／ 失敗 ／ 空だったか」の証拠。

取得の証拠であって、次のどれでも**ない**（監督の決定。記録 `docs/databank/PHASE8_ACQ0_ACQUISITION_EVENT_AUTHORITY.md`）:
- 市場 ・identity ・財務の真実（観測は A1 ／ A2 の record。本 record は観測ではない）
- coverage（「十分に観測したので不在に意味がある」という宣言ではない。`COMPLETE` ・`EMPTY` から coverage は作らない）
- provider の履歴の完全性の主張（`COMPLETE` は「caller の承認済みの手順が完了した」だけ。`pagination_key` が無いことを
  provider の意味の真実にしない）
- 本番の解釈の規則

内容:
- 範囲（`RequestScope`）: 凍結 LIVE1 の endpoint（`ALLOWED_PATHS`）と、許した非秘密の query の次元だけ（master: `date` だけ。
  fins: `code` ／ `date` の 1 つ以上）。credential の key ・header ・URL ・`pagination_key` は範囲に入らない。鍵は整列して正準。
- `acquired_at`: caller が渡す aware な時刻（新しい取得の時だけ時計を読んでよい ＝ caller の責任。model ・store ・replay は時計を
  読まない。保存は UTC の ISO 8601）。
- 内容の digest: 凍結 LIVE1 の bounded な handoff の欄だけ（master: `ELIGIBILITY_FIELDS` の 6 欄、fins: `SUPPORTED_FIELDS` の 14 欄）
  を、**受け取った順のまま**（整列しない）正準 JSON にして sha256。raw の本文 ・header ・値そのものは持たない。
- 状態: `COMPLETE` ／ `PARTIAL_PAGINATED` ／ `FAILED` ／ `EMPTY`（取得の完全性だけ。意味を足さない）。
- identity は内容 address（`p8acq_`）。参照の形は `jq.acq:<24 hex>`（A1 の `Coverage` ・A2 の `ObservationCoverage` への配線は
  後の gate。本 gate では配線しない）。
"""
from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Any, Dict, Iterable, Mapping, Tuple

from .identity_model import CREDENTIAL_MARKERS, SourceClass, canonical_json
from .jquants_adapter_model import SUPPORTED_FIELDS
from .jquants_live_model import ALLOWED_PATHS, FINS_SUMMARY_PATH, MASTER_PATH, LiveInputError, canonical_query
from .jquants_master_ingress import ELIGIBILITY_FIELDS
from ..core.ids import content_id
from ..core.time import from_iso, to_utc_iso

ACQUISITION_SCHEMA_VERSION = "p8_acquisition_event:0.1.0"
ACQUISITION_RULES_VERSION = "p8_acquisition_event_authority:0.1.0"
ACQUISITION_RECORD_KIND = "ACQUISITION_EVENT"
ACQUISITION_ID_PREFIX = "p8acq"
#: 取得の証拠の authority の種類（観測 ・coverage ・authority の record ではない）
ACQUISITION_EVIDENCE_RECORD = "ACQUISITION_EVIDENCE_RECORD"
API_VERSION = "v2"
#: 参照の形 `jq.acq:<digest 24 hex>`（record id から導く。A1 ・A2 の `source_record_ref` の文字の集合の中）
REFERENCE_PREFIX = "jq.acq:"
#: 内容の digest の行の順: 受け取った順のまま。provider ・caller が正準の順を宣言するまで整列しない
ROW_ORDER_RULE = "HANDOFF_ORDER_AS_RECEIVED"
#: endpoint ごとに範囲に入れてよい query の次元（`pagination_key` は範囲ではなく状態）
SCOPE_KEYS: Mapping[str, Tuple[str, ...]] = {MASTER_PATH: ("date",), FINS_SUMMARY_PATH: ("code", "date")}
#: endpoint ごとの bounded な handoff の欄（凍結 LIVE1 の境界。広げない）
BOUNDED_FIELDS: Mapping[str, Tuple[str, ...]] = {MASTER_PATH: ELIGIBILITY_FIELDS, FINS_SUMMARY_PATH: SUPPORTED_FIELDS}
_DIGEST_RE = re.compile(r"^[0-9a-f]{64}$")
_REFERENCE_RE = re.compile(r"^jq\.acq:[0-9a-f]{24}$")
_FAILURE_CODE_RE = re.compile(r"^[A-Z][A-Z0-9_]{0,63}$")
_RULE_VERSION_RE = re.compile(r"^[a-z][a-z0-9_]{0,63}:[0-9]+\.[0-9]+\.[0-9]+$")
_MAX_COUNT = 10_000_000


class AcquisitionModelError(ValueError):
    """record の構造 ・語彙 ・値の違反（fail closed）。detail は field 名だけ。"""

    def __init__(self, code: str, detail: str = "") -> None:
        super().__init__(f"{code}: {detail}" if detail else code)
        self.code = code
        self.detail = detail


def _require(condition: bool, code: str, detail: str = "") -> None:
    if not condition:
        raise AcquisitionModelError(code, detail)


def _enum(value: Any, kind: type, field_name: str) -> None:
    _require(isinstance(value, kind), "INVALID_VOCABULARY", field_name)


def _aware(value: Any, field_name: str) -> datetime:
    _require(isinstance(value, datetime), "INVALID_DATETIME", field_name)
    _require(value.tzinfo is not None and value.tzinfo.utcoffset(value) is not None, "NAIVE_DATETIME", field_name)
    return value


def _count(value: Any, field_name: str) -> int:
    _require(type(value) is int and 0 <= value <= _MAX_COUNT, "INVALID_COUNT", field_name)
    return value


def _no_credential_marker(value: str, field_name: str) -> None:
    lowered = value.lower()
    _require(not any(marker in lowered for marker in CREDENTIAL_MARKERS), "CREDENTIAL_LIKE_TEXT", field_name)


def _reject_unknown(data: Mapping[str, Any], allowed: Iterable[str], name: str) -> None:
    _require(isinstance(data, Mapping), "INVALID_RECORD", name)
    _require(set(data) <= set(allowed), "UNKNOWN_FIELD", name)
    _require(set(allowed) <= set(data), "MISSING_FIELD", name)


class AcquisitionStatus(str, Enum):
    """取得の完全性だけ（provider の意味 ・不在の意味 ・coverage を含まない）。"""

    COMPLETE = "COMPLETE"
    PARTIAL_PAGINATED = "PARTIAL_PAGINATED"
    FAILED = "FAILED"
    EMPTY = "EMPTY"


# ---------------------------------------------------------------- 範囲


@dataclass(frozen=True)
class RequestScope:
    """bounded な request の範囲: 凍結 LIVE1 の endpoint ＋ 許した非秘密の query の次元（整列 ・正準）。URL ・header は無い。"""

    endpoint: str
    params: Tuple[Tuple[str, str], ...]

    def __post_init__(self) -> None:
        _require(isinstance(self.endpoint, str) and self.endpoint in ALLOWED_PATHS, "ENDPOINT_NOT_ALLOWED", "endpoint")
        _require(isinstance(self.params, tuple) and all(isinstance(p, tuple) and len(p) == 2 for p in self.params),
                 "INVALID_SCOPE", "params")
        try:
            canonical = canonical_query(dict(self.params))               # credential の key ・不正な値 ・未知の key を拒む
        except LiveInputError as exc:
            raise AcquisitionModelError(exc.code, "params") from None
        _require(canonical == self.params, "SCOPE_NOT_CANONICAL", "params")
        keys = tuple(key for key, _ in canonical)
        _require(len(set(keys)) == len(keys), "SCOPE_DUPLICATE_KEY", "params")
        allowed = SCOPE_KEYS[self.endpoint]
        _require(all(key in allowed for key in keys), "SCOPE_KEY_NOT_ALLOWED", "params")
        _require(len(keys) >= 1, "SCOPE_EMPTY", "params")
        if self.endpoint == MASTER_PATH:
            _require(keys == ("date",), "SCOPE_KEY_NOT_ALLOWED", "params")
        for key, value in canonical:
            _no_credential_marker(key, "params")
            _no_credential_marker(value, key)

    @classmethod
    def of(cls, endpoint: str, params: Mapping[str, str]) -> "RequestScope":
        """caller の mapping から正準の範囲を作る（整列は `canonical_query` に任せる）。"""
        _require(isinstance(endpoint, str) and endpoint in ALLOWED_PATHS, "ENDPOINT_NOT_ALLOWED", "endpoint")
        try:
            canonical = canonical_query(params)
        except LiveInputError as exc:
            raise AcquisitionModelError(exc.code, "params") from None
        return cls(endpoint=endpoint, params=canonical)

    def as_dict(self) -> Dict[str, Any]:
        return {"endpoint": self.endpoint, "params": [[key, value] for key, value in self.params]}

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "RequestScope":
        _reject_unknown(data, ("endpoint", "params"), "scope")
        _require(isinstance(data["params"], list) and all(isinstance(p, list) and len(p) == 2 for p in data["params"]),
                 "INVALID_SCOPE", "params")
        return cls(endpoint=data["endpoint"], params=tuple((str(k), str(v)) for k, v in data["params"]))


# ---------------------------------------------------------------- bounded な内容の digest


@dataclass(frozen=True)
class BoundedContent:
    """bounded な handoff の行の digest と行数（値そのものは持たない）。"""

    row_count: int
    digest: str

    def __post_init__(self) -> None:
        _count(self.row_count, "row_count")
        _require(isinstance(self.digest, str) and bool(_DIGEST_RE.match(self.digest)), "INVALID_DIGEST", "digest")


def bounded_content_digest(endpoint: str, rows: Iterable[Mapping[str, Any]]) -> BoundedContent:
    """endpoint の bounded な欄だけを、受け取った順のまま正準 JSON にして sha256（`ROW_ORDER_RULE`）。他の欄は拒む。"""
    _require(isinstance(endpoint, str) and endpoint in BOUNDED_FIELDS, "ENDPOINT_NOT_ALLOWED", "endpoint")
    fields = BOUNDED_FIELDS[endpoint]
    canonical_rows = []
    for row in rows:
        _require(isinstance(row, Mapping), "INVALID_ROW", "rows")
        _require(set(row) == set(fields), "ROW_FIELDS_NOT_BOUNDED", "rows")
        _require(all(isinstance(row[name], str) for name in fields), "INVALID_ROW", "rows")
        canonical_rows.append(canonical_json({name: row[name] for name in fields}))
    payload = canonical_json({"endpoint": endpoint, "row_order": ROW_ORDER_RULE, "rows": canonical_rows})
    return BoundedContent(row_count=len(canonical_rows),
                          digest=hashlib.sha256(payload.encode("utf-8")).hexdigest())


# ---------------------------------------------------------------- event


@dataclass(frozen=True, kw_only=True)
class AcquisitionEvent:
    """1 回の bounded な取得の手順の証拠（不変 ・内容 address）。raw の本文 ・header ・credential ・値を持てない。"""

    KIND = ACQUISITION_RECORD_KIND
    AUTHORITY_CLASS = ACQUISITION_EVIDENCE_RECORD
    provider: SourceClass
    scope: RequestScope
    acquired_at: datetime
    status: AcquisitionStatus
    row_count: int
    pagination_key_present: bool
    pages_followed: int
    content_digest: str
    failure_code: str = ""
    authority_version: str = ACQUISITION_RULES_VERSION

    def __post_init__(self) -> None:
        _enum(self.provider, SourceClass, "provider")
        _require(self.provider is SourceClass.JQUANTS, "PROVIDER_NOT_ALLOWED", "provider")
        _require(isinstance(self.scope, RequestScope), "INVALID_SCOPE", "scope")
        _aware(self.acquired_at, "acquired_at")
        _enum(self.status, AcquisitionStatus, "status")
        _count(self.row_count, "row_count")
        _require(type(self.pagination_key_present) is bool, "INVALID_FLAG", "pagination_key_present")
        _count(self.pages_followed, "pages_followed")
        _require(isinstance(self.content_digest, str) and bool(_DIGEST_RE.match(self.content_digest)),
                 "INVALID_DIGEST", "content_digest")
        _require(isinstance(self.failure_code, str) and (self.failure_code == ""
                 or bool(_FAILURE_CODE_RE.match(self.failure_code))), "INVALID_FAILURE_CODE", "failure_code")
        if self.failure_code:
            _no_credential_marker(self.failure_code, "failure_code")
        _require(isinstance(self.authority_version, str) and bool(_RULE_VERSION_RE.match(self.authority_version)),
                 "INVALID_RULE_VERSION", "authority_version")
        if self.status is AcquisitionStatus.FAILED:
            _require(self.failure_code != "", "FAILURE_CODE_REQUIRED", "failure_code")
        else:
            _require(self.failure_code == "", "FAILURE_CODE_NOT_ALLOWED", "failure_code")
            _require(self.pages_followed >= 1, "PAGES_REQUIRED", "pages_followed")
        if self.status is AcquisitionStatus.COMPLETE:
            _require(self.row_count >= 1 and not self.pagination_key_present, "STATUS_INCONSISTENT", "status")
        elif self.status is AcquisitionStatus.EMPTY:
            _require(self.row_count == 0 and not self.pagination_key_present, "STATUS_INCONSISTENT", "status")
        elif self.status is AcquisitionStatus.PARTIAL_PAGINATED:
            _require(self.pagination_key_present, "STATUS_INCONSISTENT", "status")

    def identity_payload(self) -> Dict[str, Any]:
        return {"acquired_at": to_utc_iso(self.acquired_at), "api_version": API_VERSION,
                "authority_version": self.authority_version, "content_digest": self.content_digest,
                "failure_code": self.failure_code, "pages_followed": self.pages_followed,
                "pagination_key_present": self.pagination_key_present, "provider": self.provider.value,
                "record_kind": ACQUISITION_RECORD_KIND, "row_count": self.row_count,
                "row_order": ROW_ORDER_RULE, "schema_version": ACQUISITION_SCHEMA_VERSION,
                "scope": self.scope.as_dict(), "status": self.status.value}

    @property
    def record_id(self) -> str:
        return content_id(ACQUISITION_ID_PREFIX, canonical_json(self.identity_payload()))

    @property
    def reference(self) -> str:
        """`jq.acq:<24 hex>`（A1 ・A2 の provenance の参照に使える形。配線は後の gate）。"""
        return acquisition_reference(self.record_id)

    def as_dict(self) -> Dict[str, Any]:
        return {**self.identity_payload(), "record_id": self.record_id}

    def canonical_line(self) -> str:
        return canonical_json(self.as_dict()) + "\n"

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "AcquisitionEvent":
        _reject_unknown(data, ("acquired_at", "api_version", "authority_version", "content_digest", "failure_code",
                               "pages_followed", "pagination_key_present", "provider", "record_id", "record_kind",
                               "row_count", "row_order", "schema_version", "scope", "status"), "record")
        _require(data["schema_version"] == ACQUISITION_SCHEMA_VERSION, "SCHEMA_MISMATCH", "schema_version")
        _require(data["record_kind"] == ACQUISITION_RECORD_KIND, "KIND_MISMATCH", "record_kind")
        _require(data["api_version"] == API_VERSION, "API_VERSION_MISMATCH", "api_version")
        _require(data["row_order"] == ROW_ORDER_RULE, "ROW_ORDER_MISMATCH", "row_order")
        _require(isinstance(data["acquired_at"], str), "INVALID_DATETIME", "acquired_at")
        try:
            acquired_at = from_iso(data["acquired_at"])
        except ValueError:
            raise AcquisitionModelError("INVALID_DATETIME", "acquired_at") from None
        try:
            provider = SourceClass(data["provider"])
            status = AcquisitionStatus(data["status"])
        except ValueError:
            raise AcquisitionModelError("INVALID_VOCABULARY", "status") from None
        record = cls(provider=provider, scope=RequestScope.from_dict(data["scope"]), acquired_at=acquired_at,
                     status=status, row_count=data["row_count"], pagination_key_present=data["pagination_key_present"],
                     pages_followed=data["pages_followed"], content_digest=data["content_digest"],
                     failure_code=data["failure_code"], authority_version=data["authority_version"])
        _require(record.record_id == data["record_id"], "RECORD_ID_MISMATCH", "record_id")
        return record


def acquisition_reference(record_id: Any) -> str:
    """record id → 参照 `jq.acq:<24 hex>`（決定論）。"""
    _require(isinstance(record_id, str) and record_id.startswith(ACQUISITION_ID_PREFIX + "_")
             and len(record_id) == len(ACQUISITION_ID_PREFIX) + 25, "INVALID_RECORD_ID", "record_id")
    return REFERENCE_PREFIX + record_id[len(ACQUISITION_ID_PREFIX) + 1:]


def is_acquisition_reference(value: Any) -> bool:
    return isinstance(value, str) and bool(_REFERENCE_RE.match(value))


def is_acquisition_event(value: Any) -> bool:
    return isinstance(value, AcquisitionEvent)


__all__ = ["ACQUISITION_EVIDENCE_RECORD", "ACQUISITION_ID_PREFIX", "ACQUISITION_RECORD_KIND",
           "ACQUISITION_RULES_VERSION", "ACQUISITION_SCHEMA_VERSION", "API_VERSION", "BOUNDED_FIELDS",
           "REFERENCE_PREFIX", "ROW_ORDER_RULE", "SCOPE_KEYS", "AcquisitionEvent", "AcquisitionModelError",
           "AcquisitionStatus", "BoundedContent", "RequestScope", "acquisition_reference", "bounded_content_digest",
           "is_acquisition_event", "is_acquisition_reference"]
