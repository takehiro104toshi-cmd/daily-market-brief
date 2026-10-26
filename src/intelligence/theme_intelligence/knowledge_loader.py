"""P6-B4B — versioned knowledge（Theme taxonomy / entity catalog）の共通 primitive と YAML loader。

責務:
- 純 primitive: `KnowledgeError`、`KnowledgeProvenance`、version 文字列の解析 / 比較、token 正規化、canonical JSON、
  content digest、published_at / date の解析。
- YAML I/O（本 module にのみ許す）: strict SafeLoader（重複 key 拒否・単一 document・root は mapping）で読み、
  snapshot envelope（schema_version / <version key> / published_at / content_digest / <records key>）を検証して
  **plain な Python 構造**を返す。model への変換は `taxonomy_model` / `entity_model` が行う。
- version / cutoff / digest の gate: expected_version 不一致・published_at > cutoff・digest 不一致は fail closed。

持たないもの: 現在時刻、「latest」解決、書き込み、network、data_root、Foundation / proposal store への参照。
knowledge は **VERSIONED KNOWLEDGE** であり authority journal ではない（監督指示 B4B §2）。
"""
from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from dataclasses import dataclass
from datetime import date, datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

KNOWLEDGE_DIRNAME = "theme_intelligence"
KNOWLEDGE_FILENAME_TEMPLATES: Mapping[str, str] = {
    "taxonomy": "theme_taxonomy.{version}.yaml",
    "entity_catalog": "entity_catalog.{version}.yaml",
}
DIGEST_ALGORITHM = "sha256"
MAX_TEXT_LEN = 240
MAX_REF_LEN = 200
MAX_NOTE_LEN = 500

_VERSION_RE = re.compile(r"^(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)$")
_SLUG_RE = re.compile(r"^[a-z][a-z0-9_]{0,63}$")
_DIGEST_RE = re.compile(r"^[0-9a-f]{64}$")
_WS_RE = re.compile(r"\s+")
_DRIVE_PATH_RE = re.compile(r"(?:^|[\s\"'(\[])[A-Za-z]:[\\/]")
_UNC_PATH_RE = re.compile(r"\\\\[^\\\s]+\\")
_USERINFO_URL_RE = re.compile(r"://[^/\s]*@")
_SECRET_QUERY_RE = re.compile(r"[?&](?:token|key|api_key|apikey|password|secret|signature|sig)=", re.IGNORECASE)


# ---------------------------------------------------------------- errors


class KnowledgeError(ValueError):
    """knowledge の読み込み / 検証 / 解決の失敗。`code` は機械可読、`where` は document 内の位置（file system path ではない）。"""

    def __init__(self, code: str, detail: str = "", *, where: str = "") -> None:
        self.code = code
        self.detail = detail
        self.where = where
        location = f" at {where}" if where else ""
        super().__init__(f"{code}{location}: {detail}" if detail else f"{code}{location}")


def _fail(code: str, detail: str = "", *, where: str = "") -> None:
    raise KnowledgeError(code, detail, where=where)


def _require(condition: bool, code: str, detail: str = "", *, where: str = "") -> None:
    if not condition:
        _fail(code, detail, where=where)


# ---------------------------------------------------------------- pure primitives


class KnowledgeOrigin(str, Enum):
    """knowledge record の由来 class（抽象）。原文・号 / 頁・named chain は記録しない。"""
    SUPERVISOR_DECISION = "SUPERVISOR_DECISION"
    HISTORICAL_SLUG_SEED = "HISTORICAL_SLUG_SEED"    # historical taxonomy の slug 名だけを再利用（信号語・説明文は不採用）
    PUBLIC_STANDARD = "PUBLIC_STANDARD"              # ISO code・公開指数名などの公的 / 公開標準
    MVP_FIXTURE = "MVP_FIXTURE"                      # 検証専用の架空 record（実在企業 / 顧客 watchlist 由来ではない）


@dataclass(frozen=True, kw_only=True)
class KnowledgeProvenance:
    origin: KnowledgeOrigin
    approver_ref: str          # 仮名 / role id。個人識別情報を置かない
    reason: str

    def __post_init__(self) -> None:
        _require(isinstance(self.origin, KnowledgeOrigin), "INVALID_TYPE", "provenance.origin must be KnowledgeOrigin")
        object.__setattr__(self, "approver_ref", checked_text(self.approver_ref, "provenance.approver_ref",
                                                              max_len=MAX_REF_LEN, required=True))
        object.__setattr__(self, "reason", checked_text(self.reason, "provenance.reason", max_len=MAX_NOTE_LEN,
                                                        required=True))

    def to_plain(self) -> Dict[str, str]:
        return {"origin": self.origin.value, "approver_ref": self.approver_ref, "reason": self.reason}

    @classmethod
    def from_plain(cls, data: object, *, where: str) -> "KnowledgeProvenance":
        mapping = plain_mapping(data, where=where)
        require_keys(mapping, allowed=("origin", "approver_ref", "reason"), required=("origin", "approver_ref", "reason"),
                     where=where)
        return cls(origin=parse_enum(mapping["origin"], KnowledgeOrigin, where=f"{where}.origin"),
                   approver_ref=plain_str(mapping, "approver_ref", where=where),
                   reason=plain_str(mapping, "reason", where=where))


def parse_version(text: object, *, where: str) -> Tuple[int, int, int]:
    """`MAJOR.MINOR.PATCH`（各 10 進、先頭 0 なし）のみ受理。"""
    _require(isinstance(text, str), "INVALID_VERSION", f"{where} must be a str", where=where)
    match = _VERSION_RE.match(str(text))
    _require(match is not None, "INVALID_VERSION", f"{where} must be MAJOR.MINOR.PATCH", where=where)
    return tuple(int(part) for part in match.groups())  # type: ignore[return-value]


def version_key(text: str) -> Tuple[int, int, int]:
    return parse_version(text, where="version")


def is_slug(value: object) -> bool:
    return isinstance(value, str) and _SLUG_RE.match(value) is not None


def normalize_token(text: str) -> str:
    """NFKC → 空白圧縮 → strip → casefold。slug / alias / 入力 token に同一規則を適用する（決定論、部分一致なし）。"""
    return _WS_RE.sub(" ", unicodedata.normalize("NFKC", str(text))).strip().casefold()


def check_prohibited_content(value: str, where: str) -> None:
    """credential 付き URL・secret query・機械固有 path を knowledge の文字列 field に入れない。"""
    if (_USERINFO_URL_RE.search(value) or _SECRET_QUERY_RE.search(value)
            or _DRIVE_PATH_RE.search(value) or _UNC_PATH_RE.search(value)):
        _fail("PROHIBITED_CONTENT", f"{where} contains a credential-bearing URL or machine-specific path", where=where)


def checked_text(value: object, where: str, *, max_len: int, required: bool = False) -> str:
    _require(isinstance(value, str), "INVALID_TYPE", f"{where} must be a str", where=where)
    text = str(value)
    _require(text == text.strip(), "NOT_NORMALIZED", f"{where} must not have surrounding whitespace", where=where)
    if required:
        _require(text != "", "MISSING_FIELD", f"{where} is required", where=where)
    _require(len(text) <= max_len, "TEXT_TOO_LONG", f"{where} exceeds {max_len} characters", where=where)
    _require("\n" not in text and "\r" not in text, "INVALID_TEXT", f"{where} must be a single line", where=where)
    check_prohibited_content(text, where)
    return text


def canonical_json(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)


def content_digest(payload: Mapping[str, object]) -> str:
    """semantic payload の canonical JSON に対する sha256 hex。payload は `content_digest` を含まないこと。"""
    _require("content_digest" not in payload, "INVALID_DIGEST_PAYLOAD", "payload must not contain content_digest")
    return hashlib.new(DIGEST_ALGORITHM, canonical_json(payload).encode("utf-8")).hexdigest()


def is_digest(value: object) -> bool:
    return isinstance(value, str) and _DIGEST_RE.match(value) is not None


def to_utc_iso(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat()


def parse_published_at(value: object, *, where: str) -> datetime:
    """ISO 8601 文字列（offset 必須）または aware datetime のみ受理し、UTC に正規化する。naive / date / その他は拒否。"""
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00") if value.endswith("Z") else value)
        except ValueError:
            _fail("INVALID_DATETIME", f"{where} is not ISO 8601", where=where)
    else:
        _fail("INVALID_DATETIME", f"{where} must be an ISO 8601 string", where=where)
    _require(parsed.tzinfo is not None and parsed.utcoffset() is not None, "INVALID_DATETIME",
             f"{where} must carry an explicit UTC offset", where=where)
    return parsed.astimezone(timezone.utc)


def parse_date(value: object, *, where: str) -> date:
    """`YYYY-MM-DD` 文字列または date（datetime ではない）のみ受理。"""
    if isinstance(value, datetime):
        _fail("INVALID_DATE", f"{where} must be a calendar date, not a datetime", where=where)
    if isinstance(value, date):
        return value
    _require(isinstance(value, str), "INVALID_DATE", f"{where} must be YYYY-MM-DD", where=where)
    try:
        return date.fromisoformat(str(value))
    except ValueError:
        _fail("INVALID_DATE", f"{where} must be YYYY-MM-DD", where=where)
    raise AssertionError("unreachable")


def require_aware(value: object, *, where: str) -> datetime:
    _require(isinstance(value, datetime), "INVALID_CUTOFF", f"{where} must be a datetime", where=where)
    dt = value  # type: ignore[assignment]
    _require(dt.tzinfo is not None and dt.utcoffset() is not None, "INVALID_CUTOFF", f"{where} must be aware", where=where)
    return dt.astimezone(timezone.utc)


def parse_enum(value: object, enum_type: type, *, where: str):
    _require(isinstance(value, str), "INVALID_VOCABULARY", f"{where} must be a str", where=where)
    try:
        return enum_type(value)
    except ValueError:
        _fail("INVALID_VOCABULARY", f"{where}: unknown value {value!r}", where=where)
    raise AssertionError("unreachable")


# ---------------------------------------------------------------- plain-structure helpers（型検査は fail closed）


def plain_mapping(data: object, *, where: str) -> Mapping[str, object]:
    _require(isinstance(data, Mapping), "INVALID_TYPE", f"{where} must be a mapping", where=where)
    for key in data:  # type: ignore[union-attr]
        _require(isinstance(key, str), "INVALID_TYPE", f"{where} keys must be str", where=where)
    return data  # type: ignore[return-value]


def require_keys(data: Mapping[str, object], *, allowed: Sequence[str], required: Sequence[str], where: str) -> None:
    unknown = sorted(set(data) - set(allowed))
    _require(not unknown, "UNKNOWN_FIELD", f"{where} has unknown field(s) {unknown}", where=where)
    missing = [key for key in required if key not in data]
    _require(not missing, "MISSING_FIELD", f"{where} is missing {missing}", where=where)


def plain_str(data: Mapping[str, object], key: str, *, where: str, default: Optional[str] = None) -> str:
    if key not in data:
        _require(default is not None, "MISSING_FIELD", f"{where}.{key} is required", where=where)
        return str(default)
    value = data[key]
    _require(isinstance(value, str), "INVALID_TYPE", f"{where}.{key} must be a str", where=f"{where}.{key}")
    return str(value)


def plain_str_list(data: Mapping[str, object], key: str, *, where: str, required: bool = False) -> Tuple[str, ...]:
    if key not in data:
        _require(not required, "MISSING_FIELD", f"{where}.{key} is required", where=where)
        return ()
    value = data[key]
    _require(isinstance(value, list), "INVALID_TYPE", f"{where}.{key} must be a list", where=f"{where}.{key}")
    out: List[str] = []
    for index, item in enumerate(value):  # type: ignore[union-attr]
        _require(isinstance(item, str), "INVALID_TYPE", f"{where}.{key}[{index}] must be a str", where=f"{where}.{key}")
        out.append(str(item))
    return tuple(out)


def plain_list_of_mappings(data: Mapping[str, object], key: str, *, where: str) -> Tuple[Mapping[str, object], ...]:
    value = data.get(key)
    _require(isinstance(value, list), "INVALID_TYPE", f"{where}.{key} must be a list", where=f"{where}.{key}")
    return tuple(plain_mapping(item, where=f"{where}.{key}[{index}]") for index, item in enumerate(value))  # type: ignore[union-attr]


def plain_str_mapping(data: Mapping[str, object], key: str, *, where: str) -> Tuple[Tuple[str, str], ...]:
    """`{str: str}` を sorted な pair tuple にする（順序非依存の digest のため）。"""
    if key not in data:
        return ()
    mapping = plain_mapping(data[key], where=f"{where}.{key}")
    pairs: List[Tuple[str, str]] = []
    for name, value in mapping.items():
        _require(isinstance(value, str), "INVALID_TYPE", f"{where}.{key}.{name} must be a str", where=f"{where}.{key}")
        pairs.append((name, str(value)))
    return tuple(sorted(pairs))


def sorted_unique(values: Iterable[str], *, where: str, key=None) -> Tuple[str, ...]:
    items = list(values)
    keyed = [key(v) if key else v for v in items]
    _require(len(set(keyed)) == len(keyed), "DUPLICATE_VALUE", f"{where} contains duplicates", where=where)
    return tuple(sorted(items, key=key) if key else sorted(items))


# ---------------------------------------------------------------- paths（列挙 / latest はしない）


def knowledge_path(knowledge_root: Path, kind: str, version: str) -> Path:
    """`<knowledge_root>/theme_intelligence/<kind file>.<version>.yaml`。version は caller が明示する。"""
    _require(isinstance(knowledge_root, Path), "INVALID_TYPE", "knowledge_root must be a pathlib.Path")
    _require(kind in KNOWLEDGE_FILENAME_TEMPLATES, "INVALID_KNOWLEDGE_KIND", f"unknown knowledge kind {kind!r}")
    parse_version(version, where="version")
    return knowledge_root / KNOWLEDGE_DIRNAME / KNOWLEDGE_FILENAME_TEMPLATES[kind].format(version=version)


# ---------------------------------------------------------------- YAML（本 module のみ）


def _strict_loader():
    import yaml

    class _StrictLoader(yaml.SafeLoader):
        def construct_mapping(self, node, deep: bool = False):  # type: ignore[override]
            seen = set()
            for key_node, _value_node in node.value:
                key = self.construct_object(key_node, deep=deep)
                if key in seen:
                    raise KnowledgeError("DUPLICATE_KEY", f"duplicate mapping key {key!r}",
                                         where=f"line {key_node.start_mark.line + 1}")
                seen.add(key)
            return super().construct_mapping(node, deep=deep)

    return yaml, _StrictLoader


def read_yaml_document(path: Path) -> Mapping[str, object]:
    """単一 document・root mapping・重複 key なしの YAML だけを plain 構造として返す。"""
    _require(isinstance(path, Path), "INVALID_TYPE", "path must be a pathlib.Path")
    _require(path.is_file(), "FILE_MISSING", f"knowledge file {path.name} does not exist", where=path.name)
    try:
        text = path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        _fail("INVALID_ENCODING", f"{path.name} is not valid UTF-8", where=path.name)
    yaml, loader = _strict_loader()
    try:
        documents = list(yaml.load_all(text, Loader=loader))
    except KnowledgeError:
        raise
    except yaml.YAMLError as exc:  # noqa: PERF203
        raise KnowledgeError("INVALID_YAML", type(exc).__name__, where=path.name) from None
    _require(len(documents) == 1, "MULTIPLE_DOCUMENTS", f"{path.name} must contain exactly one document", where=path.name)
    return plain_mapping(documents[0], where=path.name)


# ---------------------------------------------------------------- snapshot envelope


@dataclass(frozen=True, kw_only=True)
class SnapshotEnvelope:
    """検証済み envelope。records は未変換の plain mapping（model 化は各 model module）。"""
    schema_version: str
    version: str
    published_at: datetime
    content_digest: str           # 著者が宣言した digest（"" は authoring 時のみ許される）
    records: Tuple[Mapping[str, object], ...]
    document_name: str


def read_snapshot_envelope(path: Path, *, schema_version: str, version_key: str, records_key: str,
                           allow_missing_digest: bool = False) -> SnapshotEnvelope:
    document = read_yaml_document(path)
    where = path.name
    allowed = ("schema_version", version_key, "published_at", "content_digest", records_key)
    required = ("schema_version", version_key, "published_at", records_key) + (() if allow_missing_digest else ("content_digest",))
    require_keys(document, allowed=allowed, required=required, where=where)
    declared_schema = plain_str(document, "schema_version", where=where)
    _require(declared_schema == schema_version, "UNSUPPORTED_SCHEMA_VERSION",
             f"expected {schema_version}, found {declared_schema}", where=where)
    version = plain_str(document, version_key, where=where)
    parse_version(version, where=f"{where}.{version_key}")
    published_at = parse_published_at(document["published_at"], where=f"{where}.published_at")
    digest = plain_str(document, "content_digest", where=where, default="" if allow_missing_digest else None)
    if not allow_missing_digest:      # authoring 補助（compute_*_digest）は宣言値を読まないので形式検査も行わない
        _require(is_digest(digest), "INVALID_DIGEST", "content_digest must be 64 lowercase hex characters",
                 where=f"{where}.content_digest")
    records = plain_list_of_mappings(document, records_key, where=where)
    return SnapshotEnvelope(schema_version=declared_schema, version=version, published_at=published_at,
                            content_digest=digest, records=records, document_name=where)


def check_version_and_cutoff(envelope: SnapshotEnvelope, *, expected_version: str, cutoff: datetime) -> None:
    """expected_version は完全一致、published_at ≤ cutoff。どちらも fail closed。"""
    parse_version(expected_version, where="expected_version")
    cutoff_utc = require_aware(cutoff, where="cutoff")
    _require(envelope.version == expected_version, "VERSION_MISMATCH",
             f"expected {expected_version}, found {envelope.version}", where=envelope.document_name)
    _require(envelope.published_at <= cutoff_utc, "FUTURE_VERSION",
             f"published_at {to_utc_iso(envelope.published_at)} is after cutoff {to_utc_iso(cutoff_utc)}",
             where=envelope.document_name)


def check_digest(envelope: SnapshotEnvelope, computed: str) -> None:
    _require(envelope.content_digest == computed, "DIGEST_MISMATCH",
             f"declared {envelope.content_digest[:12]}… computed {computed[:12]}…", where=envelope.document_name)
