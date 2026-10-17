"""P8-ADP0 — J-Quants `/v2/fins/summary` の純 adapter の入力 ・出力の model（派生 ・非 authority ・非永続。書かない）。

- 入力 `FinancialSummaryRow`: 公式の行のうち、provider の identity ・知識の時刻 ・期間 ・意味の写し ・承認済みの 4 欄に要る **14 欄だけ**を
  文字列のまま持つ（境界つき。111 欄の汎用の model ではない）。厳密の方針: 14 欄はすべて必須（`PROVIDER_FIELD_MISSING`）、値は文字列
  （`PROVIDER_VALUE_NOT_TEXT`）、公式に列挙された他の欄は**捨てて保持しない**、公式の一覧に無い key は拒む（`PROVIDER_FIELD_UNKNOWN`。
  schema のずれ）。元の行を保持しない。
- provider の record の identity `ProviderRecordIdentity`: 自然 key（Code ・DiscDate ・DiscTime ・DiscNo ・DocType）＋
  14 欄の正準 JSON の sha256（key の順に依らない）。同じ自然 key で内容が違えば別の revision の identity（上書きの意味を持たない）。DiscNo だけを鍵にしない。
  時計 ・乱数 ・UUID ・filesystem を使わない。
- 出力 `AdapterResult`: `ELIGIBLE` ／ `HOLD`。ELIGIBLE は後の EXE が再導出するための材料（凍結の A2 の観測の record（根の形。
  `supersedes` は EXE が決める）・A2R の注記 ・provenance ・知識の時刻 ・期間 ・版）、HOLD は凍結の ST1 の `HeldObservation`（**append しない**）。
  raw の行 ・`payload` の欄は無い。
- authority: `DERIVED_NON_AUTHORITY_NON_PERSISTENT`。EXE は本結果を信用せず、authority の入力 ・文脈から写しと適格を再実行する。

記録: `docs/databank/PHASE8_ADP0_JQUANTS_FINANCIAL_SUMMARY_ADAPTER.md`。
"""
from __future__ import annotations

import hashlib
import re
from dataclasses import asdict, dataclass
from datetime import datetime
from enum import Enum
from typing import Any, Dict, Mapping, Optional, Tuple

from .held_observation_model import HeldObservation, HeldReason
from .identity_model import CREDENTIAL_MARKERS, canonical_json
from .observation_model import FundamentalActual, KnowledgeTime, ReportingPeriod
from .observation_semantics_model import ObservationSemantics, SemanticMappingProvenance

ADAPTER_RULES_VERSION = "p8_jquants_fins_summary_adapter:0.1.0"
ADAPTER_SCHEMA_FAMILY = "JQUANTS_V2_FINS_SUMMARY"
#: 結果の authority の種類（record ではない ・保存しない ・EXE は信用しない）
DERIVED_NON_AUTHORITY_NON_PERSISTENT = "DERIVED_NON_AUTHORITY_NON_PERSISTENT"
PROVIDER_RECORD_REF_PREFIX = "jq.fins_summary"
MAX_PROVIDER_VALUE_LENGTH = 64
#: 公式の `/v2/fins/summary` の欄の一覧（111。公式の文書 2026-09-28。P8-A2R 再実行 §5.1）。一覧に無い key は schema のずれとして拒む
OFFICIAL_FINS_SUMMARY_FIELDS: Tuple[str, ...] = (
    "DiscDate", "DiscTime", "Code", "DiscNo", "DocType", "CurPerType", "CurPerSt", "CurPerEn", "CurFYSt", "CurFYEn",
    "NxtFYSt", "NxtFYEn", "Sales", "OP", "OdP", "NP", "EPS", "DEPS", "TA", "Eq", "EqAR", "BPS", "CFO", "CFI", "CFF",
    "CashEq", "Div1Q", "Div2Q", "Div3Q", "DivFY", "DivAnn", "DivUnit", "DivTotalAnn", "PayoutRatioAnn", "FDiv1Q",
    "FDiv2Q", "FDiv3Q", "FDivFY", "FDivAnn", "FDivUnit", "FDivTotalAnn", "FPayoutRatioAnn", "NxFDiv1Q", "NxFDiv2Q",
    "NxFDiv3Q", "NxFDivFY", "NxFDivAnn", "NxFDivUnit", "NxFPayoutRatioAnn", "FSales2Q", "FOP2Q", "FOdP2Q", "FNP2Q",
    "FEPS2Q", "NxFSales2Q", "NxFOP2Q", "NxFOdP2Q", "NxFNp2Q", "NxFEPS2Q", "FSales", "FOP", "FOdP", "FNP", "FEPS",
    "NxFSales", "NxFOP", "NxFOdP", "NxFNp", "NxFEPS", "MatChgSub", "SigChgInC", "ChgByASRev", "ChgNoASRev", "ChgAcEst",
    "RetroRst", "ShOutFY", "TrShFY", "AvgSh", "NCSales", "NCOP", "NCOdP", "NCNP", "NCEPS", "NCTA", "NCEq", "NCEqAR",
    "NCBPS", "FNCSales2Q", "FNCOP2Q", "FNCOdP2Q", "FNCNP2Q", "FNCEPS2Q", "NxFNCSales2Q", "NxFNCOP2Q", "NxFNCOdP2Q",
    "NxFNCNP2Q", "NxFNCEPS2Q", "FNCSales", "FNCOP", "FNCOdP", "FNCNP", "FNCEPS", "NxFNCSales", "NxFNCOP", "NxFNCOdP",
    "NxFNCNP", "NxFNCEPS", "ShEq", "NCShEq", "ROE", "NCROE")
#: adapter が読む 14 欄（provider の identity ・知識の時刻 ・期間 ・意味 ・承認済みの 4 欄）
SUPPORTED_FIELDS: Tuple[str, ...] = ("Code", "DiscDate", "DiscTime", "DiscNo", "DocType", "CurPerType", "CurPerSt",
                                     "CurPerEn", "CurFYSt", "CurFYEn", "Sales", "OP", "NP", "TA")
#: 自然 key を作る欄
NATURAL_KEY_FIELDS: Tuple[str, ...] = ("Code", "DiscDate", "DiscTime", "DiscNo", "DocType")
#: provider の値（文字列のまま。制御文字なし ・64 文字まで。空は「記載なし」）
_PROVIDER_VALUE_RE = re.compile(r"^[^\x00-\x1f\x7f]{0,64}$")
#: 参照に入れる token（英数 ・`_` ・`-` だけ。他は参照を作れない → HOLD）
_REF_TOKEN_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
_DIGEST_HEX = 64


class AdapterInputError(ValueError):
    """入力の契約の違反（行の形 ・欄の欠落 ・型 ・未知の key ・文脈の型）。HOLD ではなく拒否。detail は field 名だけ。"""

    def __init__(self, code: str, detail: str = "") -> None:
        super().__init__(f"{code}: {detail}" if detail else code)
        self.code = code
        self.detail = detail


def _require(condition: bool, code: str, detail: str = "") -> None:
    if not condition:
        raise AdapterInputError(code, detail)


def _provider_text(value: Any, field_name: str) -> str:
    _require(isinstance(value, str), "PROVIDER_VALUE_NOT_TEXT", field_name)
    _require(bool(_PROVIDER_VALUE_RE.match(value)), "PROVIDER_VALUE_OUT_OF_BOUNDS", field_name)
    lowered = value.lower()
    _require(not any(marker in lowered for marker in CREDENTIAL_MARKERS), "CREDENTIAL_LIKE_TEXT", field_name)
    return value


@dataclass(frozen=True, kw_only=True)
class FinancialSummaryRow:
    """adapter が読む 14 欄（provider の文字列のまま。数にしない ・欠損を埋めない）。"""

    Code: str
    DiscDate: str
    DiscTime: str
    DiscNo: str
    DocType: str
    CurPerType: str
    CurPerSt: str
    CurPerEn: str
    CurFYSt: str
    CurFYEn: str
    Sales: str
    OP: str
    NP: str
    TA: str

    def __post_init__(self) -> None:
        for name, value in asdict(self).items():
            _provider_text(value, name)

    @classmethod
    def from_provider_mapping(cls, mapping: Any) -> "FinancialSummaryRow":
        """公式の行（Mapping）から 14 欄を取る。14 欄は必須、公式の他の欄は捨てる、公式に無い key は拒む。"""
        _require(isinstance(mapping, Mapping), "PROVIDER_ROW_NOT_MAPPING", "row")
        keys = set(mapping)
        _require(all(isinstance(key, str) for key in keys), "PROVIDER_FIELD_UNKNOWN", "row")
        unknown = keys - set(OFFICIAL_FINS_SUMMARY_FIELDS)
        _require(not unknown, "PROVIDER_FIELD_UNKNOWN", ",".join(sorted(unknown))[:160])
        missing = set(SUPPORTED_FIELDS) - keys
        _require(not missing, "PROVIDER_FIELD_MISSING", ",".join(sorted(missing)))
        return cls(**{name: mapping[name] for name in SUPPORTED_FIELDS})

    def supported_values(self) -> Dict[str, str]:
        return dict(asdict(self))

    def canonical_digest(self) -> str:
        """14 欄の正準 JSON（key を整列 ・値は文字列のまま ・空文字を残す）の sha256。key の順に依らない。"""
        return hashlib.sha256(canonical_json(self.supported_values()).encode("utf-8")).hexdigest()


@dataclass(frozen=True, kw_only=True)
class ProviderRecordIdentity:
    """provider の record の identity（自然 key ＋ 正準の digest）。同じ自然 key ・違う digest ＝ 別の revision。"""

    natural_key: Tuple[str, str, str, str, str]
    digest: str

    def __post_init__(self) -> None:
        _require(isinstance(self.natural_key, tuple) and len(self.natural_key) == len(NATURAL_KEY_FIELDS),
                 "INVALID_NATURAL_KEY", "natural_key")
        for value in self.natural_key:
            _require(isinstance(value, str), "INVALID_NATURAL_KEY", "natural_key")
        _require(isinstance(self.digest, str) and len(self.digest) == _DIGEST_HEX
                 and all(c in "0123456789abcdef" for c in self.digest), "INVALID_DIGEST", "digest")

    @classmethod
    def of(cls, row: FinancialSummaryRow) -> "ProviderRecordIdentity":
        values = row.supported_values()
        return cls(natural_key=tuple(values[name] for name in NATURAL_KEY_FIELDS), digest=row.canonical_digest())

    @property
    def code(self) -> str:
        return self.natural_key[0]

    def reference(self) -> Optional[str]:
        """A2 の `source_record_ref` ・ST1 の `provider_record_ref` に入る参照。token が参照の形に合わなければ None（→ HOLD）。"""
        code, _, _, disc_no, doc_type = self.natural_key
        for token in (code, disc_no, doc_type):
            if not _REF_TOKEN_RE.match(token):
                return None
        return f"{PROVIDER_RECORD_REF_PREFIX}:{code}.{disc_no}.{doc_type}:{self.digest[:24]}"

    def as_dict(self) -> Dict[str, Any]:
        return {"digest": self.digest, "natural_key": dict(zip(NATURAL_KEY_FIELDS, self.natural_key)),
                "reference": self.reference()}


@dataclass(frozen=True, kw_only=True)
class AdapterContext:
    """caller が明示に渡す文脈。identity は解決済みの A1 の参照だけ（Code から作らない）。取得の時刻は別の軸で、知識に使わない。"""

    issuer_id: str = ""
    acquired_at: Optional[datetime] = None

    def __post_init__(self) -> None:
        _require(isinstance(self.issuer_id, str), "INVALID_CONTEXT", "issuer_id")
        if self.acquired_at is not None:
            _require(isinstance(self.acquired_at, datetime) and self.acquired_at.tzinfo is not None
                     and self.acquired_at.tzinfo.utcoffset(self.acquired_at) is not None, "INVALID_CONTEXT",
                     "acquired_at")


class AdapterStatus(str, Enum):
    ELIGIBLE = "ELIGIBLE"
    HOLD = "HOLD"


@dataclass(frozen=True, kw_only=True)
class EligibleMaterial:
    """EXE が再導出するための材料（凍結の record の型そのもの。append はしない）。"""

    issuer_id: str
    knowledge: KnowledgeTime
    period: ReportingPeriod
    observations: Tuple[FundamentalActual, ...]
    annotations: Tuple[Tuple[ObservationSemantics, SemanticMappingProvenance], ...]

    def as_dict(self) -> Dict[str, Any]:
        return {"annotations": [[s.as_dict(), p.as_dict()] for s, p in self.annotations],
                "issuer_id": self.issuer_id, "knowledge": self.knowledge.as_dict(),
                "observations": [o.as_dict() for o in self.observations], "period": self.period.as_dict()}


@dataclass(frozen=True, kw_only=True)
class AdapterResult:
    """純 adapter の結果（派生 ・非 authority ・非永続）。raw の行 ・payload は無い。"""

    status: AdapterStatus
    provider_record: ProviderRecordIdentity
    reasons: Tuple[HeldReason, ...]
    eligible: Optional[EligibleMaterial] = None
    held: Optional[HeldObservation] = None
    mapping_rule_version: str = ""
    rules_version: str = ADAPTER_RULES_VERSION
    authority_class: str = DERIVED_NON_AUTHORITY_NON_PERSISTENT

    def __post_init__(self) -> None:
        _require(isinstance(self.status, AdapterStatus), "INVALID_RESULT", "status")
        _require(isinstance(self.provider_record, ProviderRecordIdentity), "INVALID_RESULT", "provider_record")
        if self.status is AdapterStatus.ELIGIBLE:
            _require(self.reasons == () and isinstance(self.eligible, EligibleMaterial) and self.held is None,
                     "INVALID_RESULT", "eligible")
        else:
            _require(len(self.reasons) > 0 and self.eligible is None and isinstance(self.held, HeldObservation),
                     "INVALID_RESULT", "held")
            _require(self.held.reasons == self.reasons, "INVALID_RESULT", "reasons")

    def as_dict(self) -> Dict[str, Any]:
        return {"authority_class": self.authority_class, "eligible": self.eligible.as_dict() if self.eligible else None,
                "held": self.held.as_dict() if self.held else None,
                "mapping_rule_version": self.mapping_rule_version, "provider_record": self.provider_record.as_dict(),
                "reasons": [r.value for r in self.reasons], "rules_version": self.rules_version,
                "status": self.status.value}


__all__ = ["ADAPTER_RULES_VERSION", "ADAPTER_SCHEMA_FAMILY", "DERIVED_NON_AUTHORITY_NON_PERSISTENT",
           "NATURAL_KEY_FIELDS", "OFFICIAL_FINS_SUMMARY_FIELDS", "PROVIDER_RECORD_REF_PREFIX", "SUPPORTED_FIELDS",
           "AdapterContext", "AdapterInputError", "AdapterResult", "AdapterStatus", "EligibleMaterial",
           "FinancialSummaryRow", "ProviderRecordIdentity"]
