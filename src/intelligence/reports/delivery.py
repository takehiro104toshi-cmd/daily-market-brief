"""Morning Delivery packaging（Phase 4 P4-3a v0.1.0）。

凍結済みの Phase 4 成果物を、1 つの不変な配信物へ**束ねるだけ**の純関数。

    MorningBrief（P4-1・凍結）
      + MarketSignal（P4-2・凍結）
      + 逐語 Markdown（P4-1B renderer の戻り値）
        → MorningDelivery → 顧客向け公開 JSON payload

規律（`docs/databank/MORNING_DELIVERY_SPEC.md`）:
- **純関数**。入出力・永続化・data root・時刻・乱数・環境変数・外部サービスに触れない。
  ファイルへ書くのは emitter（`delivery_emit.py`）だけ。
- **再解釈しない**。brief も signal も分解せず参照のまま持つ。方向・確度・段階・本文を
  作り直さない。新しい市場判断も新しいラベル語彙も作らない。
- **Markdown を書き換えない**。renderer の戻り値を**バイト単位で verbatim**に運ぶ。
  見出しも footer も id も空白も末尾改行も足さない。
- **公開 JSON は監査 dump ではない**。`MorningBrief.as_dict()` / `MarketSignal.as_dict()`
  を丸ごと出さず、明示的な顧客向け射影だけを出す（内部語彙が配信 API になるのを防ぐ）。
- **fail closed**。binding 不一致・未承認 format・内部語彙混入は、黙って通さず例外で止める。
- Decision / formal_review / corpus / replay / shadow_review / evaluation と
  legacy（notifiers / main / 旧 report・analysis・collectors 系）/
  外部記事基盤 / Phase 5 / 生成モデルは import しない。
- 依存は **MorningBrief・MarketSignal → MorningDelivery の一方向**。凍結側は本 module を
  参照しない。
"""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from enum import Enum
from typing import Dict, Mapping, Tuple

from ..core.ids import content_id
from .market_signal import SIGNAL_LEVEL_JA, MarketSignal
from .model import MorningBrief

MORNING_DELIVERY_SCHEMA_VERSION = "0.1.0"


class DeliveryFormat(str, Enum):
    """P4-3a が出す配信形式。HTML は P4-3b 以降（将来値を先置きしない）。"""

    MARKDOWN = "MARKDOWN"
    JSON = "JSON"


#: P4-3a の配信形式（順序固定。同一性 payload に入るため揺れさせない）
DELIVERY_FORMATS: Tuple[DeliveryFormat, ...] = (DeliveryFormat.MARKDOWN, DeliveryFormat.JSON)

#: 公開 JSON の top-level key（**この集合以外を出さない**）
PUBLIC_KEYS: Tuple[str, ...] = (
    "schema_version", "delivery_id", "session_date", "reference_session",
    "brief_id", "signal_id", "markdown_sha256", "markdown_bytes", "signal",
)
#: 公開 JSON の signal key
PUBLIC_SIGNAL_KEYS: Tuple[str, ...] = ("available", "label", "unavailable_reason")

#: 公開してよい unavailable 理由（固定・機械可読・内部自由文ではない）。
#: 将来 UI が「本日は方向を出せません」の出し分けに使うための安定状態語彙であり、
#: ここに無い値は公開しない（内部理由をそのまま配信面へ流さないため）。
PUBLIC_UNAVAILABLE_REASONS: Tuple[str, ...] = (
    "draft_not_usable", "draft_abstained", "tier3_unavailable",
    "no_outlook", "direction_mixed", "direction_uncertain",
)

#: 公開 JSON に現れてはならない内部語彙（fail closed の最終防壁）
FORBIDDEN_PUBLIC_SUBSTRINGS: Tuple[str, ...] = (
    "UPWARD_BIAS", "DOWNWARD_BIAS", "RANGE_BOUND", "MIXED", "UNCERTAIN",
    "HIGH", "MEDIUM", "LOW", "next_tokyo_session", "JP_",
    "UPWARD_LEAN", "SLIGHT_UPWARD_LEAN", "NEUTRAL_RANGE",
    "SLIGHT_DOWNWARD_LEAN", "DOWNWARD_LEAN",
    "draft_id", "package_id", "claim_id", "fact_id", "ctx_id",
    "compass_", "evpkg_", "rule_ref", "principle_refs",
    "japan_equities", "nikkei_vs_topix", "nt_ratio", "japan_rates",
    "us_rates_2y", "us_rates_10y", "us_curve", "usd_jpy",
    "breadth", "turnover", "sector_leadership", "size_leadership", "investor_flow",
    "STALE", "NOT_ENTITLED", "INSUFFICIENT_HISTORY", "CONFLICTED", "LIMITED_USE",
)

_SHA256 = re.compile(r"\A[0-9a-f]{64}\Z")


class UnmappedDeliveryState(KeyError):
    """束ねられない構造状態（fail closed）。

    配信物を作ることも、欠けた値を代替で埋めることもしない。
    """


@dataclass(frozen=True, kw_only=True)
class MorningDelivery:
    """当日の配信物。`delivery_id` は内容アドレス（同じ束ね方→同じ ID）。

    `brief` / `signal` は**凍結済み成果物への不変参照**であり、分析フィールドを
    組み直さない。`markdown` は renderer の戻り値そのもの。
    """

    delivery_id: str
    session_date: str
    reference_session: str
    brief: MorningBrief
    signal: MarketSignal
    markdown: str
    markdown_sha256: str
    markdown_bytes: int
    formats: Tuple[DeliveryFormat, ...] = DELIVERY_FORMATS
    schema_version: str = MORNING_DELIVERY_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if not self.delivery_id or not self.session_date:
            raise ValueError("MorningDelivery requires delivery_id and session_date")
        if tuple(self.formats) != DELIVERY_FORMATS:
            raise UnmappedDeliveryState(f"unapproved delivery formats: {self.formats!r}")
        if not _SHA256.match(self.markdown_sha256):
            raise UnmappedDeliveryState("markdown_sha256 must be lowercase sha256 hex")
        encoded = self.markdown.encode("utf-8")
        if len(encoded) != self.markdown_bytes:
            raise UnmappedDeliveryState("markdown_bytes does not match the markdown body")
        if hashlib.sha256(encoded).hexdigest() != self.markdown_sha256:
            raise UnmappedDeliveryState("markdown_sha256 does not match the markdown body")


def _check_binding(brief: MorningBrief, signal: MarketSignal) -> None:
    """凍結 2 成果物が同じ朝のものであることを確かめる（食い違いは束ねない）。"""
    if signal.brief_id != brief.brief_id:
        raise UnmappedDeliveryState("signal.brief_id does not match brief.brief_id")
    if signal.session_date != brief.session_date:
        raise UnmappedDeliveryState("signal.session_date does not match brief.session_date")
    if signal.reference_session != brief.reference_session:
        raise UnmappedDeliveryState(
            "signal.reference_session does not match brief.reference_session")


def delivery_payload(*, schema_version: str, session_date: str, reference_session: str,
                     brief_id: str, signal_id: str, markdown_sha256: str,
                     markdown_bytes: int,
                     formats: Tuple[DeliveryFormat, ...]) -> Dict[str, object]:
    """`delivery_id` の材料となる正規化 payload。

    Markdown 本文そのものは含めない（`markdown_sha256` が完全に決定するため）。
    日本語ラベル・出力先・ファイル名・時刻も含めない。
    """
    return {
        "schema_version": schema_version,
        "session_date": session_date,
        "reference_session": reference_session,
        "brief_id": brief_id,
        "signal_id": signal_id,
        "markdown_sha256": markdown_sha256,
        "markdown_bytes": markdown_bytes,
        "formats": [f.value for f in formats],
    }


def canonical_delivery(payload: Mapping[str, object]) -> str:
    """決定論的な正規化文字列（key 順固定・空白なし）。時刻も path も含めない。"""
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def make_delivery_id(payload: Mapping[str, object]) -> str:
    """**決定論的**な delivery_id。同じ束ね方 → 同じ ID、違えば別 ID。"""
    return content_id("delivery", canonical_delivery(payload))


def build_morning_delivery(brief: MorningBrief, signal: MarketSignal,
                           markdown: str) -> MorningDelivery:
    """凍結 2 成果物 ＋ 逐語 Markdown → 配信物（純関数・決定論的）。

    Compass も MorningBrief 合成も MarketSignal 写像も**再実行しない**。
    呼び出し側が凍結済みの成果物を渡す。
    """
    _check_binding(brief, signal)
    encoded = markdown.encode("utf-8")
    digest = hashlib.sha256(encoded).hexdigest()
    payload = delivery_payload(
        schema_version=MORNING_DELIVERY_SCHEMA_VERSION,
        session_date=brief.session_date, reference_session=brief.reference_session,
        brief_id=brief.brief_id, signal_id=signal.signal_id,
        markdown_sha256=digest, markdown_bytes=len(encoded), formats=DELIVERY_FORMATS)
    return MorningDelivery(
        delivery_id=make_delivery_id(payload),
        session_date=brief.session_date, reference_session=brief.reference_session,
        brief=brief, signal=signal, markdown=markdown,
        markdown_sha256=digest, markdown_bytes=len(encoded),
        formats=DELIVERY_FORMATS, schema_version=MORNING_DELIVERY_SCHEMA_VERSION)


def _public_signal(signal: MarketSignal) -> Dict[str, object]:
    """配信面の signal。段階が無い日に方向を作らない。"""
    if signal.available:
        label = signal.label
        if label not in SIGNAL_LEVEL_JA.values():
            raise UnmappedDeliveryState(f"signal label is not an approved label: {label!r}")
        return {"available": True, "label": label, "unavailable_reason": ""}
    reason = signal.unavailable_reason
    if reason not in PUBLIC_UNAVAILABLE_REASONS:
        raise UnmappedDeliveryState(f"unavailable reason is not publishable: {reason!r}")
    return {"available": False, "label": "", "unavailable_reason": reason}


def delivery_public_payload(delivery: MorningDelivery) -> Dict[str, object]:
    """**顧客向け公開 JSON**（配信契約。監査 dump ではない）。

    `MorningBrief.as_dict()` / `MarketSignal.as_dict()` を丸ごと出さず、ここで
    明示した key だけを出す。将来そのまま静的配信できる形であること。
    """
    payload: Dict[str, object] = {
        "schema_version": delivery.schema_version,
        "delivery_id": delivery.delivery_id,
        "session_date": delivery.session_date,
        "reference_session": delivery.reference_session,
        "brief_id": delivery.brief.brief_id,
        "signal_id": delivery.signal.signal_id,
        "markdown_sha256": delivery.markdown_sha256,
        "markdown_bytes": delivery.markdown_bytes,
        "signal": _public_signal(delivery.signal),
    }
    if tuple(payload) != PUBLIC_KEYS:
        raise UnmappedDeliveryState("public payload key set drifted from the contract")
    if tuple(payload["signal"]) != PUBLIC_SIGNAL_KEYS:          # type: ignore[arg-type]
        raise UnmappedDeliveryState("public signal key set drifted from the contract")
    blob = canonical_delivery(payload)
    for forbidden in FORBIDDEN_PUBLIC_SUBSTRINGS:
        if forbidden in blob:
            raise UnmappedDeliveryState(f"internal vocabulary reached the public payload: {forbidden}")
    return payload


def delivery_public_json(delivery: MorningDelivery) -> str:
    """公開 JSON の**決定論的**な文字列表現（artifact のバイト列そのもの）。"""
    return json.dumps(delivery_public_payload(delivery), ensure_ascii=False,
                      sort_keys=True, indent=2) + "\n"
