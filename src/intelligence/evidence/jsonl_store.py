"""JSONLベースのEvidence参照実装ストア（Phase 1-A）。

位置づけ: production DBではない。domain model・repository interface・serializationの
成立を実証するリファレンス実装（テスト・初期蓄積用。標準ライブラリのみ）。
保存形式の決定理由: docs/evidence/STORAGE_DECISION.md。

重複ID規約（EVIDENCE_INVARIANTS.md §8）:
- 既存IDと**同一内容**の追記 → 冪等スキップ（戻り値の件数に含めない）
- 既存IDと**異なる内容**の追記 → ValueError（Evidenceは不変。改定はrevision_ofで新IDを積む）
"""
from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from typing import Any, Dict, Iterable, Optional, Sequence

from ..core.serialization import decode, encode, register_domain_types
from ..market.model import Observation
from ..sources.model import RawItem, SourceDocument
from .model import EvidenceLink, Statement

_FILES = {
    "documents": "source_documents.jsonl",
    "raw_items": "raw_items.jsonl",
    "statements": "statements.jsonl",
    "links": "evidence_links.jsonl",
    "observations": "observations.jsonl",
}

_ID_FIELDS = {
    "documents": "source_document_id",
    "raw_items": "raw_item_id",
    "statements": "statement_id",
    "links": "link_id",
    "observations": "observation_id",
}


class JsonlEvidenceStore:
    """ディレクトリ配下のJSONL群にEvidenceドメインを追記保存する。"""

    def __init__(self, root: Path) -> None:
        register_domain_types()
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)

    # ---- 低レベル ----
    def _path(self, kind: str) -> Path:
        return self.root / _FILES[kind]

    def _load_raw(self, kind: str) -> Dict[str, Dict[str, Any]]:
        path = self._path(kind)
        result: Dict[str, Dict[str, Any]] = {}
        if not path.exists():
            return result
        with path.open(encoding="utf-8") as f:
            for line in f:
                if not line.strip():
                    continue
                data = json.loads(line)
                result[data[_ID_FIELDS[kind]]] = data
        return result

    def _append(self, kind: str, items: Iterable[Any]) -> int:
        existing = self._load_raw(kind)
        id_field = _ID_FIELDS[kind]
        added = 0
        with self._path(kind).open("a", encoding="utf-8") as f:
            for item in items:
                data = encode(item)
                item_id = data[id_field]
                if item_id in existing:
                    if existing[item_id] == data:
                        continue  # 冪等スキップ
                    raise ValueError(
                        f"duplicate id with different content: {item_id} "
                        "(Evidence is immutable; use revision_of for changes)"
                    )
                f.write(json.dumps(data, ensure_ascii=False) + "\n")
                existing[item_id] = data
                added += 1
        return added

    def _load_all(self, kind: str) -> Sequence[Any]:
        return [decode(d) for d in self._load_raw(kind).values()]

    # ---- EvidenceRepository契約 ----
    def add_documents(self, docs: Iterable[SourceDocument]) -> int:
        return self._append("documents", docs)

    def add_raw_items(self, items: Iterable[RawItem]) -> int:
        return self._append("raw_items", items)

    def add_statements(self, statements: Iterable[Statement]) -> int:
        return self._append("statements", statements)

    def add_links(self, links: Iterable[EvidenceLink]) -> int:
        return self._append("links", links)

    def get_document(self, document_id: str) -> Optional[SourceDocument]:
        data = self._load_raw("documents").get(document_id)
        return decode(data) if data else None

    def statements_on(self, day: date) -> Sequence[Statement]:
        """dayは**UTC暦日**として解釈する（保存時にUTC正規化されるため。契約に明記）。"""
        from datetime import timezone

        def _utc_date(dt) -> date:
            return dt.astimezone(timezone.utc).date()

        return [
            s
            for s in self._load_all("statements")
            if _utc_date(s.created_at) == day
            or (s.event_time is not None and _utc_date(s.event_time) == day)
        ]

    def all_statements(self) -> Sequence[Statement]:
        return self._load_all("statements")

    def links_for(self, claim_id: str) -> Sequence[EvidenceLink]:
        return [l for l in self._load_all("links") if l.claim_id == claim_id]

    def all_links(self) -> Sequence[EvidenceLink]:
        return self._load_all("links")

    # ---- MarketRepository契約 ----
    def record(self, observations: Iterable[Observation]) -> int:
        return self._append("observations", observations)

    def series(self, entity_id: str, metric: str, start: date, end: date) -> Sequence[Observation]:
        return sorted(
            (
                o
                for o in self._load_all("observations")
                if o.entity_id == entity_id
                and o.metric == metric
                and start <= o.as_of.date() <= end
            ),
            key=lambda o: o.as_of,
        )
