"""Derived formal review artifacts（Phase 3.9.5）— `<data_root>/compass_formal_review/`。

すべて derived・rebuildable・atomic replace。人間の真実（formal Decision）は `compass_decisions/decisions.jsonl`
だけであり、ここには一切書かない（second truth store を作らない）。
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional

from ..core.paths import data_root
from ..replay.store import atomic_write_json

FORMAL_REVIEW_ROOT_NAME = "compass_formal_review"
BUILD_MANIFEST_FILE = "build_manifest.json"
QUEUE_FILE = "queue.json"
SUMMARY_FILE = "summary.json"
PACKETS_DIR = "packets"


def formal_review_root(base: Optional[Path] = None) -> Path:
    return Path(base or data_root()) / FORMAL_REVIEW_ROOT_NAME


class FormalReviewStore:
    def __init__(self, root: Path) -> None:
        self.root = Path(root)                      # 読み取りでは mkdir しない

    @property
    def packets_dir(self) -> Path:
        return self.root / PACKETS_DIR

    def packet_path(self, pattern_id: str) -> Path:
        return self.packets_dir / f"{pattern_id}.json"

    def exists(self) -> bool:
        return (self.root / QUEUE_FILE).is_file()

    # ------------------------------------------------------------- write（derived only）
    def write_build(self, *, manifest: Mapping[str, Any], queue: Mapping[str, Any], summary: Mapping[str, Any],
                    packets: Mapping[str, Mapping[str, Any]]) -> Dict[str, int]:
        self.packets_dir.mkdir(parents=True, exist_ok=True)
        for pid, packet in packets.items():
            atomic_write_json(self.packet_path(pid), packet)
        # 前回 build の packet で今回対象外になったものは削除（derived なので rebuild で復元できる）
        keep = {f"{pid}.json" for pid in packets}
        for stale in self.packets_dir.glob("*.json"):
            if stale.name not in keep:
                stale.unlink()
        atomic_write_json(self.root / QUEUE_FILE, queue)
        atomic_write_json(self.root / SUMMARY_FILE, summary)
        atomic_write_json(self.root / BUILD_MANIFEST_FILE, manifest)
        return {"packets": len(packets)}

    # ------------------------------------------------------------- read
    def _read(self, path: Path) -> Dict[str, Any]:
        return dict(json.loads(path.read_text(encoding="utf-8"))) if path.is_file() else {}

    def queue(self) -> Dict[str, Any]:
        return self._read(self.root / QUEUE_FILE)

    def summary(self) -> Dict[str, Any]:
        return self._read(self.root / SUMMARY_FILE)

    def manifest(self) -> Dict[str, Any]:
        return self._read(self.root / BUILD_MANIFEST_FILE)

    def packet(self, pattern_id: str) -> Optional[Dict[str, Any]]:
        p = self.packet_path(pattern_id)
        return dict(json.loads(p.read_text(encoding="utf-8"))) if p.is_file() else None

    def packet_ids(self) -> List[str]:
        return sorted(p.stem for p in self.packets_dir.glob("*.json")) if self.packets_dir.is_dir() else []
