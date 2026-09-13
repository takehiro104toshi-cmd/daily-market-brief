"""既存 historical Compass の棚卸し（Phase 3.7 §21–§22）。

- PDF_SOURCE: 実在する原本 PDF（hash で unique 化。複数 location は同一 document）
- DERIVED_HISTORICAL_ARTIFACT: Phase 0 の解析成果物（docs/compass_dna 等）。**PDF corpus source ではない**
- DERIVED_TEXT_ARTIFACT: legacy の text（.md/.txt）。原本ではない
走査対象 dir は呼び出し側（config / CLI）が渡す。存在しない source を count しない。
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Sequence, Tuple

from .identity import document_id_for, sha256_file

PDF_SOURCE = "PDF_SOURCE"
DERIVED_HISTORICAL_ARTIFACT = "DERIVED_HISTORICAL_ARTIFACT"
DERIVED_TEXT_ARTIFACT = "DERIVED_TEXT_ARTIFACT"


@dataclass(frozen=True)
class InventoryItem:
    kind: str
    sha256: str
    document_id: str            # PDF_SOURCE のみ（他は ""）
    byte_size: int
    original_filename: str
    locations: Tuple[str, ...]  # 相対/絶対 path 文字列（記録用）

    def as_dict(self) -> Dict[str, object]:
        return {"kind": self.kind, "sha256": self.sha256, "document_id": self.document_id,
                "byte_size": self.byte_size, "original_filename": self.original_filename,
                "locations": list(self.locations)}


@dataclass(frozen=True)
class CorpusInventory:
    scanned_dirs: Tuple[str, ...]
    missing_dirs: Tuple[str, ...]
    pdf_items: Tuple[InventoryItem, ...]
    derived_items: Tuple[InventoryItem, ...]
    duplicate_copies: int

    @property
    def unique_pdf_documents(self) -> int:
        return len(self.pdf_items)

    def as_dict(self) -> Dict[str, object]:
        return {"scanned_dirs": list(self.scanned_dirs), "missing_dirs": list(self.missing_dirs),
                "unique_pdf_documents": self.unique_pdf_documents,
                "duplicate_copies": self.duplicate_copies,
                "derived_artifacts": len(self.derived_items),
                "pdf_items": [i.as_dict() for i in self.pdf_items],
                "derived_items": [i.as_dict() for i in self.derived_items]}


def inventory(source_dirs: Sequence[Path], derived_paths: Sequence[Path] = (),
              text_dirs: Sequence[Path] = ()) -> CorpusInventory:
    scanned: List[str] = []
    missing: List[str] = []
    by_hash: Dict[str, Dict[str, object]] = {}
    copies = 0
    for d in source_dirs:
        d = Path(d)
        if not d.is_dir():
            missing.append(str(d))
            continue
        scanned.append(str(d))
        for pdf in sorted(p for p in d.rglob("*") if p.is_file() and p.suffix.lower() == ".pdf"):
            digest = sha256_file(pdf)
            entry = by_hash.setdefault(digest, {"size": pdf.stat().st_size, "name": pdf.name,
                                                "locations": []})
            if entry["locations"]:
                copies += 1
            entry["locations"].append(str(pdf))
    pdf_items = tuple(
        InventoryItem(kind=PDF_SOURCE, sha256=h, document_id=document_id_for(h),
                      byte_size=int(e["size"]), original_filename=str(e["name"]),
                      locations=tuple(e["locations"]))
        for h, e in sorted(by_hash.items(), key=lambda kv: kv[1]["name"]))
    derived: List[InventoryItem] = []
    for p in derived_paths:
        p = Path(p)
        if p.is_file():
            derived.append(InventoryItem(kind=DERIVED_HISTORICAL_ARTIFACT, sha256=sha256_file(p),
                                         document_id="", byte_size=p.stat().st_size,
                                         original_filename=p.name, locations=(str(p),)))
    for d in text_dirs:
        d = Path(d)
        if not d.is_dir():
            continue
        for f in sorted(p for p in d.iterdir() if p.is_file() and p.suffix.lower() in (".md", ".txt")
                        and p.name.lower() != "readme.md"):
            derived.append(InventoryItem(kind=DERIVED_TEXT_ARTIFACT, sha256=sha256_file(f),
                                         document_id="", byte_size=f.stat().st_size,
                                         original_filename=f.name, locations=(str(f),)))
    return CorpusInventory(scanned_dirs=tuple(scanned), missing_dirs=tuple(missing),
                           pdf_items=pdf_items, derived_items=tuple(derived),
                           duplicate_copies=copies)
