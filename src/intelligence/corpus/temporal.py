"""Temporal semantics（Phase 3.7 §14）。

混同してはならない 5 つの時刻:
- document_date          … 紙面の発行日（page-1 の「YYYY年M月D日」）
- publication_date       … 判明する場合のみ（PDF metadata CreationDate。JST）
- received_at            … Corpus が bytes を受領した時刻（ingest 時に注入）
- referenced_market_session … 本文・ヘッダー表が参照する取引 session。
                            営業日カレンダーで決定的に確定できなければ UNKNOWN
- future_event_date      … 本文中の将来イベント日（解決せず mention として保持）
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from typing import Dict, List, Mapping, Optional, Sequence, Tuple

UNKNOWN = "UNKNOWN"
BASIS_CALENDAR = "CALENDAR"           # 営業日カレンダーで確定

# ---- publication time provenance（Phase 3.75 pre-flight）。PDF metadata を無条件の真実にしない。
PUB_SOURCE_DOCUMENT_TEXT = "DOCUMENT_TEXT"        # 紙面に明記された発行時刻（例: 右上の 7:30）
PUB_SOURCE_PDF_METADATA = "PDF_METADATA"          # PDF CreationDate（ファイル生成時刻。発行時刻の近似）
PUB_SOURCE_RECEIVED_TIME = "RECEIVED_TIME"        # 受領時刻しか分からない（pipeline は自動採用しない）
PUB_SOURCE_EXTERNAL_VERIFIED = "EXTERNAL_VERIFIED"  # 外部で検証済み（将来用。今回は付与しない）
PUB_SOURCE_UNKNOWN = "UNKNOWN"
PUBLICATION_TIME_SOURCES = (PUB_SOURCE_DOCUMENT_TEXT, PUB_SOURCE_PDF_METADATA,
                            PUB_SOURCE_RECEIVED_TIME, PUB_SOURCE_EXTERNAL_VERIFIED,
                            PUB_SOURCE_UNKNOWN)
_TEXT_TIME = re.compile(r"(?<!\d)(\d{1,2})[:：](\d{2})(?!\d)")
_TEXT_TIME_SCAN_LINES = 12                         # page-1 冒頭（タイトル・日付・発行時刻の領域）のみ
BASIS_NO_CALENDAR = "NO_CALENDAR"     # カレンダー無し → UNKNOWN
BASIS_OUT_OF_RANGE = "OUT_OF_RANGE"   # カレンダー範囲外 → UNKNOWN

_JP_DATE = re.compile(r"(20\d\d)年\s?(\d{1,2})月\s?(\d{1,2})日")
_FOOT_DAY = re.compile(r"東京時間(\d{1,2})日(\d{1,2})時時点")
_PDF_DATE = re.compile(r"D:(\d{4})(\d{2})(\d{2})(\d{2})?(\d{2})?(\d{2})?")
_FUTURE = re.compile(r"(\d{1,2})月(\d{1,2})日|(\d{1,2})[-〜～](\d{1,2})日|(?<![\d年月])(\d{1,2})日(?![\d時])")


@dataclass(frozen=True)
class DocumentDateDecision:
    document_date: str                 # ISO or ""
    basis: str                         # PAGE1_TEXT / PDF_METADATA / ""
    footnote_day: Optional[int]
    metadata_date: str
    conflicts: Tuple[str, ...]

    def as_dict(self) -> Dict[str, object]:
        return {"document_date": self.document_date, "basis": self.basis,
                "footnote_day": self.footnote_day, "metadata_date": self.metadata_date,
                "conflicts": list(self.conflicts)}


def parse_pdf_date(value: str) -> Tuple[str, str]:
    """PDF metadata 'D:YYYYMMDDhhmmss...' → (ISO date, ISO time or '')。"""
    m = _PDF_DATE.search(str(value or ""))
    if not m:
        return "", ""
    y, mo, d = m.group(1), m.group(2), m.group(3)
    try:
        iso = date(int(y), int(mo), int(d)).isoformat()
    except ValueError:
        return "", ""
    hh, mm, ss = m.group(4) or "00", m.group(5) or "00", m.group(6) or "00"
    return iso, f"{hh}:{mm}:{ss}"


def extract_document_date(page1_text: str, metadata: Optional[Mapping[str, str]] = None
                          ) -> DocumentDateDecision:
    """page-1 本文の最初の「YYYY年M月D日」を document_date とする。

    脚注「東京時間DD日7時時点」の日と PDF CreationDate を突き合わせ、矛盾は conflicts に残す
    （矛盾があっても本文日付を優先。ただし本文日付が無ければ metadata で代替せず "" ＝ QUARANTINE 対象）。"""
    conflicts: List[str] = []
    m = _JP_DATE.search(page1_text or "")
    doc_date = ""
    basis = ""
    if m:
        try:
            doc_date = date(int(m.group(1)), int(m.group(2)), int(m.group(3))).isoformat()
            basis = "PAGE1_TEXT"
        except ValueError:
            conflicts.append("PAGE1_DATE_INVALID")
    foot = _FOOT_DAY.search(page1_text or "")
    foot_day = int(foot.group(1)) if foot else None
    meta_date = ""
    if metadata:
        meta_date, _ = parse_pdf_date(str(metadata.get("/CreationDate") or metadata.get("CreationDate") or ""))
    if doc_date and foot_day is not None and int(doc_date[-2:]) != foot_day:
        conflicts.append("FOOTNOTE_DAY_MISMATCH")
    if doc_date and meta_date and meta_date != doc_date:
        conflicts.append("METADATA_DATE_MISMATCH")
    return DocumentDateDecision(document_date=doc_date, basis=basis, footnote_day=foot_day,
                                metadata_date=meta_date, conflicts=tuple(conflicts))


@dataclass(frozen=True)
class TemporalSemantics:
    document_date: str
    publication_date: str                 # "" if unknown
    publication_time_jst: str             # "" if unknown
    received_at: str                      # ISO datetime（UTC）
    referenced_market_session: str        # ISO date or UNKNOWN
    referenced_session_basis: str
    candidate_previous_weekday: str       # ヒント（session ではない。祝日を考慮しない）
    future_event_mentions: Tuple[str, ...] = ()
    conflicts: Tuple[str, ...] = ()
    publication_time_source: str = PUB_SOURCE_UNKNOWN   # DOCUMENT_TEXT / PDF_METADATA / … / UNKNOWN
    metadata_creation_date: str = ""      # PDF CreationDate（参考値。publication と分離して保持）
    metadata_creation_time_jst: str = ""

    def as_dict(self) -> Dict[str, object]:
        return {"document_date": self.document_date,
                "publication_date": self.publication_date,
                "publication_time_jst": self.publication_time_jst,
                "publication_time_source": self.publication_time_source,
                "metadata_creation_date": self.metadata_creation_date,
                "metadata_creation_time_jst": self.metadata_creation_time_jst,
                "received_at": self.received_at,
                "referenced_market_session": self.referenced_market_session,
                "referenced_session_basis": self.referenced_session_basis,
                "candidate_previous_weekday": self.candidate_previous_weekday,
                "future_event_mentions": list(self.future_event_mentions),
                "conflicts": list(self.conflicts)}


def previous_weekday(iso: str) -> str:
    """祝日を考慮しない前営業日候補（ヒント用。referenced session には使わない）。"""
    try:
        d = date.fromisoformat(iso)
    except ValueError:
        return ""
    d -= timedelta(days=1)
    while d.weekday() >= 5:
        d -= timedelta(days=1)
    return d.isoformat()


def resolve_referenced_session(document_date: str, trading_days: Optional[Sequence[str]]
                               ) -> Tuple[str, str]:
    """document_date の **直前** の営業日（紙面ヘッダーの「終値」が指す session）。

    営業日カレンダーが無ければ UNKNOWN（推測しない）。"""
    if not document_date:
        return UNKNOWN, BASIS_NO_CALENDAR
    if not trading_days:
        return UNKNOWN, BASIS_NO_CALENDAR
    days = sorted(str(d) for d in trading_days)
    if document_date <= days[0] or document_date > _next_after(days[-1]):
        return UNKNOWN, BASIS_OUT_OF_RANGE
    prev = [d for d in days if d < document_date]
    if not prev:
        return UNKNOWN, BASIS_OUT_OF_RANGE
    return prev[-1], BASIS_CALENDAR


def _next_after(iso: str) -> str:
    try:
        return (date.fromisoformat(iso) + timedelta(days=7)).isoformat()
    except ValueError:
        return iso


def future_event_mentions(texts: Sequence[str], limit: int = 20) -> Tuple[str, ...]:
    """本文中の日付らしい token（「6月24日」「23-25日」等）を **解決せず** そのまま保持する。"""
    found: List[str] = []
    for text in texts:
        for m in _FUTURE.finditer(text or ""):
            token = m.group(0)
            if token not in found:
                found.append(token)
            if len(found) >= limit:
                return tuple(found)
    return tuple(found)


def extract_publication_time_text(page1_text: str) -> str:
    """page-1 冒頭に明記された発行時刻（"7:30" 等）→ "HH:MM:00"。無ければ ""（捏造しない）。"""
    lines = [l.strip() for l in (page1_text or "").splitlines() if l.strip()][:_TEXT_TIME_SCAN_LINES]
    for line in lines:
        m = _TEXT_TIME.search(line)
        if m:
            hh, mm = int(m.group(1)), int(m.group(2))
            if 0 <= hh < 24 and 0 <= mm < 60:
                return f"{hh:02d}:{mm:02d}:00"
    return ""


def publication_provenance(document_date: str, page1_text: str,
                           metadata: Optional[Mapping[str, str]] = None
                           ) -> Tuple[str, str, str, str, str]:
    """→ (publication_date, publication_time_jst, source, metadata_date, metadata_time)。

    優先順位: 紙面の明記時刻（DOCUMENT_TEXT）＞ PDF CreationDate（PDF_METADATA）＞ UNKNOWN。
    received_at は別 field。時刻が分からなければ空のまま（RECEIVED_TIME で埋めない）。"""
    meta_date, meta_time = "", ""
    if metadata:
        meta_date, meta_time = parse_pdf_date(str(metadata.get("/CreationDate")
                                                  or metadata.get("CreationDate") or ""))
    text_time = extract_publication_time_text(page1_text)
    if document_date and text_time:
        return document_date, text_time, PUB_SOURCE_DOCUMENT_TEXT, meta_date, meta_time
    if meta_date:
        return meta_date, meta_time, PUB_SOURCE_PDF_METADATA, meta_date, meta_time
    return "", "", PUB_SOURCE_UNKNOWN, meta_date, meta_time


def temporal_semantics(document_date: str, *, received_at: datetime,
                       metadata: Optional[Mapping[str, str]] = None,
                       trading_days: Optional[Sequence[str]] = None,
                       body_texts: Sequence[str] = (),
                       conflicts: Sequence[str] = ()) -> TemporalSemantics:
    page1 = body_texts[0] if body_texts else ""
    pub_date, pub_time, pub_source, meta_date, meta_time = publication_provenance(
        document_date, page1, metadata)
    session, basis = resolve_referenced_session(document_date, trading_days)
    if received_at.tzinfo is None:
        received_at = received_at.replace(tzinfo=timezone.utc)
    return TemporalSemantics(
        document_date=document_date, publication_date=pub_date, publication_time_jst=pub_time,
        received_at=received_at.astimezone(timezone.utc).isoformat(),
        publication_time_source=pub_source, metadata_creation_date=meta_date,
        metadata_creation_time_jst=meta_time,
        referenced_market_session=session, referenced_session_basis=basis,
        candidate_previous_weekday=previous_weekday(document_date),
        future_event_mentions=future_event_mentions(body_texts),
        conflicts=tuple(conflicts))
